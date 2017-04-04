`mixemt` - Deconvolving mtDNA Mixtures by Expectation Maximization
==================================================================

[![Build Status](https://travis-ci.org/svohr/mixemt.svg?branch=master)](https://travis-ci.org/svohr/mixemt)

`mixemt` is a program for making sense of mixtures of human mitochondrial
sequences. It takes as input a BAM file containing reads mapped to the human
mitochondrial reference sequence and uses a representation of the
mitochondrial haplogroup phylogeny from [Phylotree.org](http://www.phylotree.org/)
to infer the haplogroups present in the mixture. `mixemt` scans each mapped
read for variants described in Phylotree and estimates the probability of the
read originating from each candidate haplotype (haplogroup). This information
is used to estimate the mixture proportions for the sample and to identify the
most likely haplogroups contributing to the sample. The program produces as
output a table, written to standard output, that describes the detected
haplogroups and their estimated percent contribution to the sample. The program
can also produce new BAM files of input fragments partitioned by the most
likely contributor of origin, tab-delimited files containing statistics for
each reference position, and verbose output detailing the results from each
step.


## Requirements

`mixemt` is written in Python and requires a few additional packages:

* [NumPy/SciPy](http://scipy.org/)
* [Biopython](http://biopython.org/)
* [pysam](https://github.com/pysam-developers/pysam)

[R](https://www.r-project.org/) and [ggplot2](http://ggplot2.org/) are required
to use the plotting scripts included in the directory `plot/`.


## Installation

`mixemt` can be installed from this repository using [pip](https://pip.pypa.io/).

```
git clone https://github.com/svohr/mixemt.git
cd mixemt
pip install .
```

Missing requirements will be automatically downloaded and installed as well.


## Usage

```
mixemt [options] <reads.bam>
```


## Preparing input sequences

`mixemt` takes as input a BAM file containing alignments of sequences to a
reference sequence. The Reconstructed Sapiens Reference Sequence (RSRS) is
typically used the reference sequence, although reads may be mapped to the
Revised Cambridge Reference Sequence (rCRS) as both share a common coordinate
system.

Aligned sequences are provided to `mixemt` as a BAM file. Alignments should be
filtered prior to input using `samtools` or a similar program. Internally,
`mixemt` treats alignments sharing the same query template name as a single
fragment and does not check read pairs for orientation, insert size, unaligned
segments, or secondary alignments. The options `-q` and `-Q` allow for basic
filtering of alignments and base calls based on map quality and base quality
scores.

Since the mitochondrial genome is circular, it may be advantageous to align
reads across the junction of the start and end of the reference sequence,
split the reads, and correct the mapping coordinates. A basic implementation of
these steps can be found in the repository
[circ\_aln](https://github.com/svohr/circ_aln).


## Options

### Basic options

#### `-h, --help`
Print help message describing usage and options.

#### `-v, --verbose`
Print detailed status with useful information while running.

#### `--ref ref.fasta`
Specify a FASTA file containing the reference sequence. The first sequence in
the file will be used. The reference sequence must match the variants
contained in the Phylotree input to avoid unexpected behavior. The
Recontructed Sapiens Reference Sequence (RSRS) contained in
`mixemt/ref/RSRS.mtDNA.fa` is used by default.

#### `--phy phylotree.csv`
Specify a Phylotree CSV file to use. By default, the file for Phylotree
Build 17 (`mixemt/phylotree/mtDNA_tree_Build_17.csv`) is used.

### Customization options

#### `-H custom.tab, --haps custom.tab`
Use the haplotypes described in the specified file alonge with the
haplogroups from Phylotree. A haplotype file consists of lines representing
haplotypes. Each line contains a distinct haplotype identifier, a tab
character, and a comma-separated list of variants in the form
`[Ancestral/Reference Base][position][Derived/Variant Base]`.

```
custom_hap1	C152T,A2758G,C2885T,G7146A,T8468C
custom_hap2	C4670T,A5282G,C9007T,G12192A,T15604C
```

Positions that do not appear in the variant list are assumed to contain the
reference base and positions that have been excluded from analysis are not used.
Variants that appear at novel positions (i.e., no known variants in Phylotree)
can be used, but it is assumed that all Phylotree haplogroups carry the
reference base.

#### `-e SITES, --exclude_pos SITES`
Specify a comma-separated list of 1-based positions or 'start-end' ranges to be
excluded from consideration.

#### `-A, --anon-haps`
Ignore Phylotree haplogroups without IDs. By default, a placeholder name is
generated for these haplogroups using the parent haplogroup's ID and an integer
number (e.g., `H1[2]` is a unnamed subgroup of haplogroup `H1`).

#### `-U, --unstable`
Ignore sites with variants listed as unstable in Phylotree.

### Quality filters
These options provide basic filtering of mapped sequences and base
observations.

#### `-q INT, --min-MQ INT`
Ignore alignments with mapping quality less than `INT` (default: 30).

#### `-Q INT, --min-BQ INT`
Ignore bases with base quality scores less than `INT` (default: 30).

### Expectation-maximization
Options for setting the parameters used during the expectation-maximization
step where the mixture proportions are inferred. The default values should
work well most of the time, but adjusting these values may be useful in
some situtations.

#### `-i ALPHA, --init ALPHA`
Use parameter `ALPHA` to initialize haplogroup contributions from Dirichlet
distribution (default: 1.0)

#### `-T TOLERANCE, --converge TOLERANCE`
Stop EM iteration when absolute difference between current and previous
contribution estimates is less than `TOLERANCE` (default: 0.0001)

#### `-m N, --max-em-iter N`
Maximum of number of EM iterations to run (default: 10000)

#### `-M N, --multi-em N`
Run EM until convergence multiple times and report the results averaged
over all runs (default: 1)

### Contributor detection options
Once the mixture proportions have been inferred, two filtering steps are
applied to narrow the field of contributing to haplotypes to only the
strongest candidates. First, we examine the read/haplogroup probablities
to find the haplogroup associated with the highest probablilty for each
read. Haplogroups that have no or little read support are removed from
consideration (see `-r` option). Second, using the haplogroups that pass
the previous filter, we verify that the variants that define each contributor
are in fact present in the mixture. This step removes haplotype signals
that are most likely driven by one or two private mutations.

#### `-C HAP1,HAP2,...,HAPN, --contributors HAP1,HAP2,...,HAPN`
Skip contributor detection step and use the specified comma-separated list of
haplogroups instead (be careful)

#### `-r N, --min-reads N`
Haplogroup must have N reads to be considered a contributor (default: 10). This
value should be adjusted when coverage is high to avoid signals caused by
sequencing errors and when coverage is low and allelic dropout may be likely.

#### `-R N, --var-min-reads N`
Variant base must be found in `N` reads to be considered as present in sample
(default: 3). This value should be above the expected number of base errors
given the sequence coverage.

#### `-f F, --var-fraction F`
Fraction of unique defining variants that must be observed to call a haplogroup
present (default: 0.5). This value should be adjusted based on the likelihood
of allelic dropout and the number of variant differences between contributors.

#### `-n N, --var-count N`
Call haplogroup a contributor if it has at least N unique variants observed in
the sample, regardless of total number of defining variants. Use when allelic
dropout is likely. (default: None).

#### `-V, --no-var-check`
Disable requirement that the majority of contributors's unique defining
variants are present in the sample. Use when coverage is very low and dropout
is likely.

#### `-E`
Skip contribution estimate refinement and report proportions from intial EM
run.

### Assembly options
#### `-a ODDS, --assign-odds ODDS`
Minimum odds ratio (probability between best and second best haplogroup)
required to assign read to a contributor (default: 2.0)

#### `-x, --extend-assemblies`
Attempt to extend haplotype assemblies iteratively by identifying novel
variants from contributor consensus sequences assigning reads based off of
them.

#### `-c N, --cons-cov N`
When extending assemblies with `-x`, sets the depth of coverage required to call
a base for a contributor (default: 2)


## Output
