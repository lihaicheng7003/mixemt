"""

assemble.py

This module contains functions for interpretting the output from our EM
algorithm: the vector of haplogroup contributions and the matrix of
read-haplogroup assignments. From these two data sets, we want to extract the
number of contributors and the fraction of the sample that is attributible to
each and individual assemblies for each contributor.

Sam Vohr (svohr@soe.ucsc.edu)

Wed Apr 13 10:57:39 PDT 2016

"""

import numpy
import pysam
import operator
import collections
import sys

import phylotree


def report_top_props(haplogroups, props, top_n=10):
    """
    Prints to stderr the names and fractions of the n haplogroups with the
    highest estimated proportions.
    """
    order = numpy.argsort(props)[::-1]
    sys.stderr.write('\nTop %d haplogroups by proportion...\n' % (top_n))
    for i in xrange(top_n):
        sys.stderr.write("%d\t%0.6f\t%s\n" % (i + 1, props[order[i]],
                                              haplogroups[order[i]]))
    sys.stderr.write('\n')
    return


def report_read_votes(haplogroups, read_hap_mat, top_n=10):
    """
    Each read "votes" for a haplogroup; the haplogroup with the highest
    probability. Report the vote counts for the top N.
    """
    votes = numpy.argmax(read_hap_mat, 1)
    vote_count = collections.Counter(votes)
    for hap_i, count in vote_count.most_common(top_n):
        sys.stderr.write("%s\t%d\n" % (haplogroups[hap_i], count))
    return


def report_contributors(out, contribs, contrib_reads, wts):
    """
    Prints a table that summarizes the contributors, their proportions and
    number of reads assigned to each. Formats the output nicely if out is
    a TTY, otherwise prints a tab-delimited table.
    """
    if out.isatty():
        out.write("hap#   Haplogroup      Contribution   Reads\n")
        out.write("-------------------------------------------\n")
    for hap_id, haplogroup, prop in contribs:
        total_reads = 0
        for read_index in contrib_reads[hap_id]:
            total_reads += wts[read_index]
        if out.isatty():
            prop_str = '%.4f' % (prop)
            read_str = '%d' % (total_reads)
            out.write('%s %s %s %s\n' % (hap_id.ljust(6),
                                         haplogroup.ljust(15),
                                         prop_str.rjust(12),
                                         read_str.rjust(7)))
        else:
            out.write('%s\t%s\t%.4f\t%d\n' % (hap_id, haplogroup,
                                              prop, total_reads))
    return


def get_contributors(phylo, obs_tab, haplogroups, em_results, args):
    """
    Takes the haplogroup tree, table of observed bases by reference position,
    a list of haplogroup IDs and a tuple representing the results from EM
    (haplogroup proportions and read/haplogroup probabilities) and identifies
    contributors that pass our filtering steps.

    For a haplogroups to be considered a contributor:
    1) There must exist k reads where that haplogroup represent the most
       probable source of that read. (Candidate contributor)
    2) A majority of the variant bases that are associated with the candidate
       contributor, but no other candidate contributor are observed in the
       sample.

    This function returns a list of hap numbers, haplogroup IDs and estimated
    contributions.
    """
    props, read_hap_mat = em_results

    contributors = list()
    vote_count = collections.Counter(numpy.argmax(read_hap_mat, 1))
    contributors = [con for con in vote_count
                    if vote_count[con] >= args.min_reads]
    contrib_prop = [[haplogroups[con], props[con]] for con in contributors]
    contrib_prop.sort(key=operator.itemgetter(1), reverse=True)

    if args.var_check:
        # Remove haplogroups with minimal variant support.
        contrib_prop = check_contrib_phy_vars(phylo, obs_tab,
                                              contrib_prop, args)

    # Add a friendly name, not associated with a haplogroup
    name_fmt = "hap%%0%dd" % (len(str(len(contrib_prop) + 1)))
    hap_num = 1
    for con in contrib_prop:
        con.insert(0, name_fmt % (hap_num))
        hap_num += 1

    return contrib_prop


def check_contrib_phy_vars(phylo, obs_tab, contribs, args):
    """
    Checks if each candidate contributor from contribs passes our variant base
    check. The strategy for this is to start with the highest estimated
    contributors and an empty list of variant positions. For each contributor,
    we identify the variant bases that are unique from the previous candidates.
    We check the observation table to verify that those bases are observed in
    the sample.
    """
    used_vars = set()
    ignore_haps = set()

    for hap, _ in contribs:
        # get variant for this haplogroup
        uniq_vars = set(phylo.hap_var[hap]) - used_vars
        found = 0
        for var in uniq_vars:
            pos = phylotree.pos_from_var(var)
            der = phylotree.der_allele(var)
            if obs_tab[pos][der] >= args.min_reads:
                found += 1
        if uniq_vars and float(found) / len(uniq_vars) < 0.5:
            if args.verbose:
                sys.stderr.write("Ignoring '%s': "
                                 "only %d/%d unique variant bases observed.\n"
                                 % (hap, found, len(uniq_vars)))
            ignore_haps.add(hap)
        else:
            # Looks good, these variants can't be used again.
            used_vars.update(uniq_vars)

    pass_contribs = [con for con in contribs if con[0] not in ignore_haps]

    return pass_contribs


def assign_reads(samfile, contribs, em_results, haps, reads, args):
    """
    Assigns reads from the BAM file to contributors using the results from EM.

    Args:
        samfile: The original samfile containing the reads to be assigned to
                 contributors.
        contribs: The table of contributors as returned by get_contributors()
        em_results: A tuple containing the final mixture proportion vector and
                    the read/haplogroup conditional probabilities from EM.
        haps: A list haplogroup IDs/label for each column in the matrix.
        reads: A list of lists where each row index in the matrix is associated
               with the read ID(s) it represents.
        args: From argparse.

    Returns: A table that maps contributor names to a list of AlignedSegments
             reprenting the reads that have been assigned to that contributor.
    """
    contrib_reads = collections.defaultdict(list)
    read_to_con = dict()
    con_read_indexes = assign_read_indexes(contribs, em_results,
                                           haps, reads, args.min_fold)
    for con in con_read_indexes:
        con_read_ids = get_contrib_read_ids(con_read_indexes(con), reads)
        for read_id in con_read_ids:
            read_to_con[read_id] = contrib_reads[con]

    for aln in samfile.fetch():
        if aln.query_name in read_to_con:
            read_to_con[aln.query].append(aln)

    return contrib_reads


def _find_best_n_for_read(read_prob, con_indexes, top_n=2):
    """
    Takes a vector of haplogroup probabilities for a single read (read_prob)
    and a list of indexes of identified contributors and returns a list of
    N (top_n) indexes in con_indexes that have the highest probabilities.
    """
    order = numpy.argsort(read_prob)[::-1]
    results = list()
    i = 0

    while len(results) < top_n:
        if order[i] in con_indexes:
            results.append(order[i])
        i += 1
    return results


def assign_read_indexes(contribs, em_results, haps, reads, min_fold):
    """
    Takes the list of identified contributors, the list of haplotype ids and
    the read-haplogroup probability under mixture proportions matrix, and
    returns a table mapping the identified contributors to the indexes of all
    reads (rows in the matrix) that have been assigned to that haplotype and a
    set of read indexes that were not assigned to a contributor. A read is
    assigned to a haplogroup if its highest probability out of all identified
    contributors is at least min_fold times greater than the probability of
    the next contributor _after_ normalizing out the contribution proportion
    of each. This way, reads that could be assigned to more than 1
    contributor are not simply assigned to the contributor that represents
    the larger proportion of the mixture.

    Args:
        contribs: The table of contributors as returned by get_contributors()
        em_results: A tuple containing the final mixture proportion vector and
                    the read/haplogroup conditional probabilities from EM.
        haps: A list haplogroup IDs/label for each column in the matrix.
        reads: The sub-haplotype identifier (read signature) for each row
               in the matrix.
        min_fold: The minimum odds ratio between top two contributors to assign
                  a read to a contributor.
    Returns: A dictionary mapping contributor names to a list of indexes to
             entries in 'reads'
    """
    props, read_hap_mat = em_results
    contrib_reads = collections.defaultdict(set)

    index_to_hap = dict([(haps.index(group), hap_n)
                        for hap_n, group, _ in contribs])
    con_indexes = set(index_to_hap.keys())
    for read_i in xrange(len(reads)):
        if len(contribs) > 1:
            read_probs = read_hap_mat[read_i, ]
            best_hap, next_hap = _find_best_n_for_read(read_probs,
                                                       con_indexes,
                                                       top_n=2)
            rel_prob = ((read_probs[best_hap] / props[best_hap]) /
                        (read_probs[next_hap] / props[next_hap]))
            if rel_prob >= min_fold:
                contrib_reads[index_to_hap[best_hap]].add(read_i)
            else:
                contrib_reads['unassigned'].add(read_i)
        else:
            # Only 1 identified contributor, use the first field of the first
            # entry in the contributors table.
            contrib_reads[contribs[0][0]].add(read_i)
    return contrib_reads


def get_contrib_read_ids(indexes, reads):
    """
    Takes a set of indexes from assign_reads and the list of read signatures
    plus the dictionary mapping signatures to aligned read IDs and returns
    the set of corresponding aligned read IDs (SAM/BAM query IDs).
    """
    hap_read_ids = set()
    for read_idx in indexes:
        for read_id in reads[read_idx]:
            hap_read_ids.add(read_id)
    return hap_read_ids


def write_haplotypes(samfile, contrib_reads, args):
    """
    Writes a new BAM file based on the original 'samfile' for each contributor
    described in the table 'contrib_reads' that maps a haplotype id to a list
    of pysam AlignedSegment objects.

    Args:
        samfile: a pysam AlignmentFile for the original BAM file.

        contrib_reads: a dictionary mapping our haplotype label to a list of
            pysam AlignedSegments for the reads that have been assigned to this
            contributor.

        args: arguments namespace from argparse. Used to get filename prefix
            for new BAM files and whether verbose mode is enabled.

    Returns:
        0 if all files written successfully, 1 otherwise.
    """
    # Set up for opening new bam files.
    ext = samfile.filename[-3:]
    mode = 'wb'
    if ext != 'bam':
        mode = 'w'

    if args.verbose:
        sys.stderr.write('\nWriting haplotype alignment files...\n')

    for contrib in contrib_reads:
        if not contrib_reads[contrib]:
            # No reads assigned to this contributor
            continue
        hap_fn = "%s.%s.%s" % (args.prefix, contrib, ext)
        try:
            hap_samfile = pysam.AlignmentFile(hap_fn, mode, template=samfile)
            written = 0
            for aln in contrib_reads[contrib]:
                hap_samfile.write(aln)
                written += 1
            if args.verbose:
                sys.stderr.write('  Wrote %d aligned segments to %s\n'
                                 % (written, hap_fn))
            hap_samfile.close()
        except (ValueError, IOError) as inst:
            sys.stderr.write("Error writing '%s': %s\n" % (hap_fn, inst))
            return 1
    return 0


def assemble_haplotypes(samfile, em_results, contribs, args):
    """
    This function encapsulates the steps of assigning reads to contributors
    from the EM results and any attempts to extend the assemblies.

    Args:
    Returns:
    Raises:
    """
    # Assign reads based on em_results

    # If enabled, try to extend the assembly
    return
