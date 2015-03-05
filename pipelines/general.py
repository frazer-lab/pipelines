import os

def _cutadapt_trim(fastq, length, out, bg=False):
    """
    Cut a specified number of bases from a fastq file using cutadapt. Cutadapt
    should be installed in your python environment.

    Parameters
    ----------
    fastq : str
        Fastq or gzipped/bzipped fastq.

    length : int
        Positive or negative integer. Positive numbers remove bases at the front
        of the read and negative numbers remove bases at the end of the read.

    out : str
        Path to output (optionally gzipped/bzipped) fastq files.

    bg : boolean
        Whether to run the process in the background (i.e. include an ampersand
        at the end of the command).

    Returns
    -------
    lines : str
        Lines to be written to PBS/shell script.

    """
    line = 'cutadapt --cut {} -o {} {}'.format(length, out, fastq)
    if bg:
        line += ' &\n'
    else:
        line += '\n'
    return line

def _bedgraph_to_bigwig(bedgraph, bigwig, bedgraph_to_bigwig_path,
                        bedtools_path):
    bedtools_genome_path = os.path.join(
        os.path.split(os.path.split(bedtools_path)[0])[0], 'genomes',
        'human.hg19.genome')
    lines =  ' '.join(['{} {}'.format(bedgraph_to_bigwig_path, bedgraph),
                       '{}'.format(bedtools_genome_path),
                       '{} &\n'.format(bigwig)])
    return lines

def _flagstat(bam, stats_file, samtools_path):
    """
    Run flagstat for a bam file.

    Parameters
    ----------
    bam : str
        Bam file to calculate coverage for.

    stats_file : str
        File to write flagstats to.

    samtools_path : str
        Path to samtools executable.

    Returns
    -------
    lines : str
        Lines to be written to PBS/shell script.

    """
    lines = '{} flagstat {} > {} &\n\n'.format(samtools_path, bam, stats_file)
    return lines

def _coverage_bedgraph(bam, bedgraph, bedtools_path, sample_name, strand='.'):
    """
    Make lines that create a coverage bedgraph file.

    Parameters
    ----------
    bam : str
        Bam file to calculate coverage for.

    bedgraph : str
        Path to output bedgraph file.

    bedtools_path : str
        Path to bedtools.

    sample_name : str
        Sample name for naming files etc.

    strand : str
        If '+' or '-', calculate strand-specific coverage. Otherwise, calculate
        coverage using all reads.

    Returns
    -------
    lines : str
        Lines to be written to PBS/shell script.

    """
    if strand == '+' or strand == '-':
        if strand == '+':
            name = '{}_plus'.format(sample_name)
        else:
            name = '{}_minus'.format(sample_name)
        lines = ' \\\n'.join(['{} genomecov -ibam'.format(bedtools_path),
                              '\t{}'.format(bam),
                              '\t-g hg19.genome -split -bg ',
                              '\t-strand {} -trackline'.format(strand),
                              '\t-trackopts \'name="{}"\''.format(name),
                              '\t> {} &\n\n'.format(bedgraph)])
    else:
        name = sample_name
        lines = ' \\\n'.join(['{} genomecov -ibam'.format(bedtools_path),
                              '\t{}'.format(bam),
                              '\t-g hg19.genome -split -bg ',
                              '\t-trackline'.format(strand),
                              '\t-trackopts \'name="{}"\''.format(name),
                              '\t> {} &\n\n'.format(bedgraph)])
    return lines

def _bigwig_files(in_bam, out_bigwig, sample_name, bedgraph_to_bigwig_path,
                  bedtools_path, out_bigwig_minus=''):
    """
    Make bigwig coverage files.

    Parameters
    ----------
    in_bam : str
        Path to bam file to create bigwigs for.

    out_bigwig : str
        Path to output bigwig file. If out_bigwig_minus is provided, out_bigwig
        has the plus strand coverage.

    out_bigwig_minus : str
        Path to output bigwig file for minus strand. If out_bigwig_minus is not
        provided, the coverage is calculated using reads from both strands and
        written to out_bigwig.

    Returns
    -------
    lines : str
        Lines to be printed to shell/PBS script.

    """
    lines = ''
    if out_bigwig_minus != '':
        lines += _coverage_bedgraph(in_bam, 'plus.bg', bedtools_path,
                                    sample_name, strand='+')
        lines += _coverage_bedgraph(in_bam, 'minus.bg', bedtools_path,
                                    sample_name, strand='-')
        lines += ('wait\n\n')
        lines += (_bedgraph_to_bigwig('plus.bg', out_bigwig,
                                      bedgraph_to_bigwig_path, bedtools_path))
        lines += (_bedgraph_to_bigwig('minus.bg', out_bigwig_minus,
                                      bedgraph_to_bigwig_path, bedtools_path))
        lines += ('\nwait\n\n')
        lines += ('rm plus.bg minus.bg\n\n')
    
    else:
        lines = _coverage_bedgraph(in_bam, 'both.bg', bedtools_path,
                                   sample_name)
        lines += ('wait\n\n')
        lines += (_bedgraph_to_bigwig('both.bg', out_bigwig,
                                      bedgraph_to_bigwig_path, bedtools_path))
        lines += ('wait\n\n')
        lines += ('rm both.bg\n\n')
    return lines
    
def _process_fastqs(fastqs, tempdir):
    """
    Create list of temporary fastq paths.

    Parameters
    ----------
    fastqs : list or str
        Either a list of paths to gzipped fastq files or path to a single
        gzipped fastq file.

    tempdir : str
        Path to temporary directory where fastq files will be copied to.

    Returns
    -------
    temp_fastqs : list
        List of paths to temporary fastq files.

    """
    if type(fastqs) == list:
        fns = [os.path.split(x)[1] for x in fastqs]
        temp_fastqs = sorted([os.path.join(tempdir, x) for x in fns])
    elif type(fastqs) == str:
        temp_fastqs = [os.path.join(tempdir, os.path.split(fastqs)[1])]
    return temp_fastqs

def _fastqc(fastqs, threads, outdir, fastqc_path):
    """
    Run FastQC

    Parameters
    ----------
    fastqs : str or list
        Path to fastq file or list of paths to fastq files.

    threads : int
        Number of threads to run FastQC with.

    outdir : str
        Path to directory to store FastQC results to.

    fastqc_path : str
        Path to FastQC.

    Returns
    -------
    lines : str
        Lines to be printed to shell/PBS script.

    """
    if type(fastqs) == list:
        fastqs = ' '.join(fastqs)
    lines = ('{} --outdir {} --nogroup \\\n'.format(fastqc_path, outdir) + 
             '\t--extract --threads {} {}\n\n'.format(threads, fastqs))
    return lines

def _make_softlink(fn, sample_name, link_dir):
    """
    Make softlink for file fn in link_dir. sample_name followed by an underscore
    will be appended to the front of fn if the sample_name isn't in fn.

    Parameters
    ----------
    fn : str
        Full path to file to make link to.

    sample_name : str
        Sample name used for naming files.

    link_dir : str
        Path to directory where softlink should be made.

    Returns
    -------
    lines : str
        Lines to be printed to shell/PBS script.

    name : str
        File name for the softlink.

    """
    if sample_name not in os.path.split(fn)[1]:
        name = '{}_{}'.format(sample_name, os.path.split(fn)[1])
    else:
        name = os.path.split(fn)[1]
    lines = 'ln -s {} {}\n'.format(fn, os.path.join(link_dir, name))
    return lines, name

def _pbs_header(out, err, name, threads, queue='high'):
    """
    Write header for PBS script

    Parameters
    ----------
    out : str
        Path to file for recording standard out.

    err : str
        Path to file for recording standard error.

    Returns
    -------
    lines : str
        Lines to be printed to shell/PBS script.

    """
    lines = ('\n'.join(['#PBS -q {}'.format(queue),
                        '#PBS -N {}'.format(name),
                        '#PBS -l nodes=1:ppn={}'.format(threads),
                        '#PBS -o {}'.format(out),
                        '#PBS -e {}\n\n'.format(err)]))
    return lines

def _picard_index(in_bam, index, picard_memory, picard_path, tempdir):
    """
    Index bam file using Picard Tools.

    Parameters
    ----------
    in_bam : str
        Path to file input bam file.

    index : str
        Path to index file for input bam file.

    Returns
    -------
    index : str
        Path to index file for input bam file.

    """
    line = (' \\\n'.join(['java -Xmx{}g -jar'.format(picard_memory),
                          '\t-XX:-UseGCOverheadLimit -XX:-UseParallelGC',
                          '\t-Djava.io.tmpdir={}'.format(tempdir),
                          '\t-jar {} BuildBamIndex'.format(picard_path),
                          '\tI={}'.format(in_bam),
                          '\tO={} &\n\n'.format(index)]))
    return line

def _samtools_index(in_bam, samtools_path, index=''):
    """
    Index bam file using samtools.

    Parameters
    ----------
    in_bam : str
        Path to file input bam file.

    index : str
        Path to index file to be written. If not provided, the index is written
        to the samtools default {in_bam}.bai in the current working directory.

    Returns
    -------
    index : str
        Path to index file for input bam file.

    """
    if index == '':
        line = 'samtools index {} &\n\n'.format(in_bam)
    else:
        line = 'samtools index {} {} &\n\n'.format(in_bam, index)
    return line

def _picard_remove_duplicates(in_bam, out_bam, duplicate_metrics, picard_path,
                              picard_memory, tempdir):
    """
    Coordinate sort using Picard Tools.

    Parameters
    ----------
    in_bam : str
        Path to input bam file.

    out_bam : str
        Path to output bam file.

    duplicate_metrics : str
        Path to index file for input bam file.

    """
    lines = (' \\\n'.join(['java -Xmx{}g -jar '.format(picard_memory),
                           '\t-XX:-UseGCOverheadLimit -XX:-UseParallelGC',
                           '\t-Djava.io.tmpdir={}'.format(tempdir), 
                           '\t-jar {} MarkDuplicates'.format(picard_path),
                           '\tMETRICS_FILE={}'.format(duplicate_metrics),
                           '\tREMOVE_DUPLICATES=TRUE',
                           '\tVALIDATION_STRINGENCY=SILENT',
                           '\tASSUME_SORTED=TRUE',
                           '\tI={}'.format(in_bam), 
                           '\tO={}\n'.format(out_bam)]))
    return lines

def wasp_allele_swap(bam, find_intersecting_snps_path, snp_dir, sample_name,
                     outdir, tempdir, conda_env='', shell=False):
    """
    Write pbs or shell script for identifying reads in a bam file that overlap
    specified variants and switching the variant allele. This is done using
    find_intersecting_snps.py from WASP.

    Parameters
    ----------
    bam : str
        Path to input bam file.

    find_intersecting_snps_path : str
        Path to find_intersecting_snps.py script.

    snp_dir : str
        Path to directory containing SNP input files for WASP.
    
    sample_name : str
        Sample name used for naming files etc.

    outdir : str
        Directory to store PBS/shell file and aligment results.

    tempdir : str
        Directory to store temporary files.

    conda_env : str
        If provided, load conda environment with this name.

    shell : boolean
        If true, make a shell script rather than a PBS script.

    """
    if shell:
        pbs = False
    else: 
        pbs = True
    
    jobname = '{}_wasp_allele_swap'.format(sample_name)

    tempdir = os.path.join(tempdir, jobname)
    outdir = os.path.join(outdir, jobname)

    # I'm going to define some file names used later.
    temp_bam = os.path.join(tempdir, os.path.split(bam)[1])
    
    # Files to copy to output directory.
    prefix = os.path.splitext(os.path.split(bam)[1])[0]
    files_to_copy = [
        '{}.keep.bam'.format(prefix),
        '{}.remap.fq1.gz'.format(prefix),
        '{}.remap.fq2.gz'.format(prefix),
        '{}.to.remap.bam'.format(prefix),
        '{}.to.remap.num.gz'.format(prefix)
    ]
    # Temporary files that can be deleted at the end of the job. We may not want
    # to delete the temp directory if the temp and output directory are the
    # same.
    files_to_remove = []
    if os.path.realpath(temp_bam) != os.path.realpath(bam):
        files_to_remove.append(temp_bam)

    try:
        os.makedirs(outdir)
    except OSError:
        pass

    if shell:
        fn = os.path.join(outdir, '{}.sh'.format(jobname))
    else:
        fn = os.path.join(outdir, '{}.pbs'.format(jobname))

    f = open(fn, 'w')
    f.write('#!/bin/bash\n\n')
    if pbs:
        out = os.path.join(outdir, '{}.out'.format(jobname))
        err = os.path.join(outdir, '{}.err'.format(jobname))
        f.write(_pbs_header(out, err, jobname, threads))
    
    if conda_env != '':
        f.write('source activate {}\n'.format(conda_env))
    f.write('mkdir -p {}\n'.format(tempdir))
    f.write('cd {}\n'.format(tempdir))
    f.write('rsync -avz \\\n\t{} \\\n\t{} \n\n'.format(bam, temp_bam))
    
    f.write('python {} -p {} {}\n\n'.format(find_intersecting_snps_path,
                                            temp_bam, snp_dir))
    
    if len(files_to_copy) > 0:
        f.write('rsync -avz \\\n\t{} \\\n \t{}\n\n'.format(
            ' \\\n\t'.join(files_to_copy),
            outdir))
    if len(files_to_remove) > 0:
        f.write('rm \\\n\t{}\n\n'.format(' \\\n\t'.join(files_to_remove)))

    if tempdir != outdir:
        f.write('rm -r {}\n'.format(tempdir))
    f.close()

    return fn

def wasp_alignment_compare(to_remap_bam, to_remap_num, remapped_bam,
                           filter_remapped_reads_path, sample_name, outdir,
                           tempdir, conda_env='', shell=False):
    """
    Write pbs or shell script for checking original mapping position of reads
    against remapping after swapping alleles using WASP.

    Parameters
    ----------
    to_remap_bam : str
        Bam file from find_intersecting_snps.py that has reads that will be
        remapped (e.g. *.to.remap.bam).

    to_remap_num : str
        Gzipped text file from find_intersecting_snps.py (e.g.
        *.to.remap.num.gz).

    remapped_bam : str
        Bam file with remapped reads.

    filter_remapped_reads_path : str
        Path to filter_remapped_reads.py script.

    sample_name : str
        Sample name used for naming files etc.

    outdir : str
        Directory to store PBS/shell file and aligment results.

    tempdir : str
        Directory to store temporary files.

    conda_env : str
        If provided, load conda environment with this name.

    shell : boolean
        If true, make a shell script rather than a PBS script.

    """
    if shell:
        pbs = False
    else: 
        pbs = True
    
    jobname = '{}_wasp_alignment_compare'.format(sample_name)

    tempdir = os.path.join(tempdir, jobname)
    outdir = os.path.join(outdir, jobname)

    # I'm going to define some file names used later.
    temp_to_remap_bam = os.path.join(tempdir, os.path.split(to_remap_bam)[1])
    temp_to_remap_num = os.path.join(tempdir, os.path.split(to_remap_num)[1])
    temp_remapped_bam = os.path.join(tempdir, os.path.split(remapped_bam)[1])
    temp_final_bam = os.path.join(tempdir,
                                  '{}_filtered.bam'.format(sample_name))
    
    # Files to copy to output directory.
    files_to_copy = [temp_final_bam]
    # Temporary files that can be deleted at the end of the job. We may not want
    # to delete the temp directory if the temp and output directory are the
    # same.
    files_to_remove = []
    if os.path.realpath(temp_to_remap_bam) != os.path.realpath(to_remap_bam):
        files_to_remove.append(temp_to_remap_bam)
    if os.path.realpath(temp_remapped_bam) != os.path.realpath(remapped_bam):
        files_to_remove.append(temp_remapped_bam)

    try:
        os.makedirs(outdir)
    except OSError:
        pass

    if shell:
        fn = os.path.join(outdir, '{}.sh'.format(jobname))
    else:
        fn = os.path.join(outdir, '{}.pbs'.format(jobname))

    f = open(fn, 'w')
    f.write('#!/bin/bash\n\n')
    if pbs:
        out = os.path.join(outdir, '{}.out'.format(jobname))
        err = os.path.join(outdir, '{}.err'.format(jobname))
        f.write(_pbs_header(out, err, jobname, threads))
    
    if conda_env != '':
        f.write('source activate {}\n'.format(conda_env))
    f.write('mkdir -p {}\n'.format(tempdir))
    f.write('cd {}\n'.format(tempdir))
    f.write('rsync -avz \\\n\t{} \\\n\t{} \n\n'.format(to_remap_bam,
                                                       temp_to_remap_bam))
    f.write('rsync -avz \\\n\t{} \\\n\t{} \n\n'.format(to_remap_num,
                                                       temp_to_remap_num))
    f.write('rsync -avz \\\n\t{} \\\n\t{} \n\n'.format(remapped_bam,
                                                       temp_remapped_bam))
    
    f.write('python {} -p {} {} {} {}\n\n'.format(
        filter_remapped_reads_path, temp_to_remap_bam, temp_remapped_bam,
        temp_final_bam, temp_to_remap_num))
    
    if len(files_to_copy) > 0:
        f.write('rsync -avz \\\n\t{} \\\n \t{}\n\n'.format(
            ' \\\n\t'.join(files_to_copy),
            outdir))
    if len(files_to_remove) > 0:
        f.write('rm \\\n\t{}\n\n'.format(' \\\n\t'.join(files_to_remove)))

    if tempdir != outdir:
        f.write('rm -r {}\n'.format(tempdir))
    f.close()

    return fn
