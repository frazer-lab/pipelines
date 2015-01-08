import os

from general import _bedgraph_to_bigwig
from general import _bigwig_files
from general import _coverage_bedgraph
from general import _make_softlink
from general import _pbs_header
from general import _process_fastqs

def _cbarrett_paired_dup_removal(r1_fastqs, r2_fastqs, r1_nodup, r2_nodup,
                                 temp_dir):
    """
    Remove duplicates from paired fastq files using UNIX sort and uniq. Read 
    pairs with exactly the same sequences are removed such that every read pair
    has a different sequence. 

    Parameters
    ----------
    r1_fastqs : str
        R1 fastq file(s). If multiple files, each file should be separated by s
        space and should be ordered the same as the R2 files.

    r2_fastqs : str
        R2 fastq file(s). If multiple files, each file should be separated by s
        space and should be ordered the same as the R1 files.

    r1_nodup : str
        Path to write gzipped R1 fastq file with duplicates removed.

    r2_nodup : str
        Path to write gzipped R2 fastq file with duplicates removed.

    temp_dir : str
        Path to temporary directory where fastq files will be copied to.

    Returns
    -------
    lines : str
        Lines to be printed to shell/PBS script.

    """
    lines = []
    lines.append('paste \\\n')
    lines.append('\t<(zcat {} | \\\n'.format(r1_fastqs) + 
                 '\t\tawk \'0==(NR+3)%4{ORS=" "; split($0,a," "); ' + 
                 'print substr(a[1],2)}0==(NR+2)%4{print} (NR!=1 && 0==NR%4)' + 
                 '{ORS="\\n";print}\') \\\n')
    lines.append('\t<(zcat {} | \\\n'.format(r2_fastqs) + 
                 '\t\tawk \'0==(NR+3)%4{ORS=" "; split($0,a," "); ' + 
                 'print substr(a[1],2)}0==(NR+2)%4{print} (NR!=1 && 0==NR%4)' + 
                 '{ORS="\\n";print}\') | \\\n')
    lines.append('\tawk \'{if ($2 < $5) printf "%s %s %s %s %s %s\\n",'
                 '$1,$3,$4,$6,$2,$5; else printf "%s %s %s %s %s %s\\n",'
                 '$1,$6,$4,$3,$5,$2}\' | \\\n')
    lines.append('\tsort -k 5,5 -k 6,6 -T {0} -S 30G --parallel=8 | '
                 'uniq -f 4 | \\\n'.format(temp_dir))
    lines.append('\tawk \'{printf "@%s\\n%s\\n+\\n%s\\n",$1,$5,$2 | '
                 '"gzip -c > ' + r1_nodup + 
                 '"; printf "@%s\\n%s\\n+\\n%s\\n",$3,$6,$4 | "gzip -c > ' + 
                  r2_nodup + '"}\'\n\n')
    return ''.join(lines)

def _star_align(r1_fastqs, r2_fastqs, sample, rgpl, rgpu, star_index, star_path,
                threads):
    """
    Align paired fastq files with STAR.

    Parameters
    ----------
    r1_fastqs : str
        Gzipped R1 fastq file(s). If multiple files, each file should be
        separated by s space and should be ordered the same as the R2 files.

    r2_fastqs : str
        Gzipped R2 fastq file(s). If multiple files, each file should be
        separated by s space and should be ordered the same as the R1 files.

    sample : str
        Sample name.

    rgpl : str
        Read Group platform (e.g. illumina, solid). 

    rgpu : str
        Read Group platform unit (eg. run barcode). 

    """
    # I use threads - 2 for STAR so there are open processors for reading and
    # writing.
    line = (' \\\n'.join([star_path, 
                          '\t--runThreadN {}'.format(threads - 2),
                          '\t--genomeDir {}'.format(star_index), 
                          '\t--genomeLoad NoSharedMemory', 
                          '\t--readFilesCommand zcat',
                          '\t--readFilesIn {} {}'.format(r1_fastqs, 
                                                         r2_fastqs),
                          '\t--outSAMtype BAM Unsorted', 
                          '\t--outSAMattributes All', 
                          '\t--outSAMunmapped Within',
                          ('\t--outSAMattrRGline ID:1 ' + 
                           'PL:{} '.format(rgpl) + 
                           'PU:{} '.format(rgpu) + 
                           'LB:{0} SM:{0}'.format(sample)), 
                          '\t--outFilterMultimapNmax 20', 
                          '\t--outFilterMismatchNmax 999',
                          '\t--outFilterMismatchNoverLmax 0.04',
                          ('\t--outFilterIntronMotifs '
                           'RemoveNoncanonicalUnannotated'),
                           '\t--outSJfilterOverhangMin 6 6 6 6',
                           '\t--seedSearchStartLmax 20',
                           '\t--alignSJDBoverhangMin 1', 
                          '\t--quantMode TranscriptomeSAM']) + '\n\n') 
    return line

def _picard_coord_sort(in_bam, out_bam, bam_index, picard_path, picard_memory,
                       temp_dir):
    """
    Coordinate sort using Picard Tools.

    Parameters
    ----------
    in_bam : str
        Path to input bam file.

    out_bam : str
        Path to output bam file.

    bam_index : str
        Path to index file for input bam file.

    """
    lines = (' \\\n'.join(['java -Xmx{}g -jar '.format(picard_memory),
                           '\t-XX:-UseGCOverheadLimit -XX:-UseParallelGC',
                           '\t-Djava.io.tmpdir={}'.format(temp_dir), 
                           '\t-jar {} SortSam'.format(picard_path),
                           '\tVALIDATION_STRINGENCY=SILENT',
                           '\tCREATE_INDEX=TRUE', 
                           '\tCREATE_MD5_FILE=TRUE',
                           '\tI={}'.format(in_bam), 
                           '\tO={}'.format(out_bam),
                           '\tSO=coordinate\n']))
    index = '.'.join(out_bam.split('.')[0:-1]) + '.bai'
    lines += 'mv {} {}\n\n'.format(index, bam_index)

    return lines

def _genome_browser_files(tracklines_file, link_dir, web_path_file,
                          coord_sorted_bam, bam_index, bigwig, sample_name,
                          out_dir, bigwig_minus=''):
    """
    Make files and softlinks for displaying results on UCSC genome browser.

    Parameters
    ----------
    tracklines_file : str
        Path to file for writing tracklines. The tracklines will be added to the
        file; the contents of the file will not be overwritten. These tracklines
        can be pasted into the genome browser upload for custom data.

    link_dir : str
        Path to directory where softlink should be made.

    web_path_file : str
        File whose first line is the URL that points to link_dir. For example,
        if we make a link to the file s1_coord_sorted.bam in link_dir and
        web_path_file has http://site.com/files on its first line, then
        http://site.com/files/s1_coord_sorted.bam should be available on the
        web. If the web directory is password protected (it probably should be),
        then the URL should look like http://username:password@site.com/files.
        This is a file so you don't have to make the username/password combo
        public (although I'd recommend not using a sensitive password). You can
        just put the web_path_file in a directory that isn't tracked by git, 
        figshare, etc.

    coord_sorted_bam : str
        Path to coordinate sorted bam file.

    bam_index : str
        Path to index file for coordinate sorted bam file.

    bigwig : str
        Path to bigwig file. If bigwig_minus is provided, bigwig has the plus
        strand coverage.

    sample_name : str
        Sample name used for naming files.

    bigwig_minus : str
        Path to bigwig file for minus strand. If bigwig_minus is not provided,
        bigwig is assumed to have coverage for both plus and minus stand reads.

    Returns
    -------
    lines : str
        Lines to be printed to shell/PBS script.

    """
    lines = ''

    with open(web_path_file) as wpf:
        web_path = wpf.readline().strip()

    # File with UCSC tracklines.
    if os.path.exists(tracklines_file):
        with open(tracklines_file) as f:
            tf_lines = f.read()
    else:
        tf_lines = ''
    
    # Bam file and index.
    fn = os.path.join(out_dir, os.path.split(coord_sorted_bam)[1])
    new_lines, bam_name = _make_softlink(fn, sample_name, link_dir)
    lines += new_lines

    fn = os.path.join(out_dir, os.path.split(bam_index)[1])
    new_lines, index_name = _make_softlink(fn, sample_name, link_dir)
    lines += new_lines

    tf_lines += ' '.join(['track', 'type=bam',
                          'name="{}_bam"'.format(sample_name),
                          'description="RNAseq for {}"'.format(sample_name),
                          'bigDataUrl={}/{}\n'.format(web_path, bam_name)])
    
    # Bigwig file(s).
    if bigwig_minus != '':
        fn = os.path.join(out_dir, os.path.split(bigwig)[1])
        new_lines, plus_name = _make_softlink(fn, sample_name, link_dir)
        lines += new_lines
        
        fn = os.path.join(out_dir, os.path.split(bigwig_minus)[1])
        new_lines, minus_name = _make_softlink(fn, sample_name, link_dir)
        lines += new_lines

        tf_lines += ' '.join(['track', 'type=bigWig',
                              'name="{}_plus_cov"'.format(sample_name),
                              ('description="RNAseq plus strand coverage for '
                               '{}"'.format(sample_name)),
                              'bigDataUrl={}/{}\n'.format(web_path,
                                                          plus_name)])
        tf_lines += ' '.join(['track', 'type=bigWig',
                              'name="{}_minus_cov"'.format(sample_name),
                              ('description="RNAseq minus strand coverage for '
                               '{}"'.format(sample_name)),
                              'bigDataUrl={}/{}\n'.format(web_path,
                                                          minus_name)])
    else:
        fn = os.path.join(out_dir, os.path.split(bigwig)[1])
        new_lines, bigwig_name = _make_softlink(fn, sample_name, link_dir)
        lines += new_lines

        tf_lines += ' '.join(['track', 'type=bigWig',
                              'name="{}_cov"'.format(sample_name),
                              ('description="RNAseq coverage for '
                               '{}"'.format(sample_name)),
                              'bigDataUrl={}/{}\n'.format(web_path,
                                                          bigwig_name)])
    
    with open(tracklines_file, 'w') as tf:
        tf.write(tf_lines)
    
    lines += '\n'
    return lines

def align_and_sort(
    r1_fastqs, 
    r2_fastqs, 
    out_dir, 
    sample_name, 
    star_index,
    tracklines_file,
    link_dir,
    web_path_file,
    star_path,
    picard_path,
    bedtools_path,
    bedgraph_to_bigwig_path,
    rgpl='ILLUMINA',
    rgpu='',
    temp_dir='/scratch', 
    threads=32, 
    picard_memory=58, 
    remove_dup=True, 
    strand_specific=False, 
    shell=False
):
    """
    Make a PBS or shell script for aligning RNA-seq reads with STAR. The
    defaults are set for use on the Frazer lab's PBS scheduler on FLC.

    Parameters
    ----------
    r1_fastqs : list or str
        Either a list of paths to gzipped fastq files with R1 reads or path to a
        single gzipped fastq file with R1 reads.

    r2_fastqs : list or str
        Either a list of paths to gzipped fastq files with R2 reads or path to a
        single gzipped fastq file with R2 reads.

    out_dir : str
        Directory to store PBS/shell file and aligment results.

    sample_name : str
        Sample name used for naming files etc.

    star_index : str
        Path to STAR index.

    tracklines_file : str
        Path to file for writing tracklines. The tracklines will be added to the
        file; the contents of the file will not be overwritten. These tracklines
        can be pasted into the genome browser upload for custom data.

    link_dir : str
        Path to directory where softlinks for genome browser should be made.

    web_path_file : str
        File whose first line is the URL that points to link_dir. For example,
        if we make a link to the file s1_coord_sorted.bam in link_dir and
        web_path_file has http://site.com/files on its first line, then
        http://site.com/files/s1_coord_sorted.bam should be available on the
        web. If the web directory is password protected (it probably should be),
        then the URL should look like http://username:password@site.com/files.
        This is a file so you don't have to make the username/password combo
        public (although I'd recommend not using a sensitive password). You can
        just put the web_path_file in a directory that isn't tracked by git, 
        figshare, etc.

    star_path : str
        Path to STAR aligner.

    picard_path : str
        Path to Picard tools.

    bedtools_path : str
        Path to bedtools.

    bedgraph_to_bigwig_path : str
        Path bedGraphToBigWig executable.

    rgpl : str
        Read Group platform (e.g. illumina, solid). 

    rgpu : str
        Read Group platform unit (eg. run barcode). 

    temp_dir : str
        Directory to store files as STAR runs.

    threads : int
        Number of threads to reserve using PBS scheduler. This number of threads
        minus 2 will be used by STAR, so this must be at least 3.

    picard_memory : int
        Amount of memory (in gb) to give Picard Tools.

    remove_dup : boolean
        Whether to remove duplicate reads prior to alignment.

    strand_specific : boolean
        If true, make strand specific bigwig files. 

    shell : boolean
        If true, make a shell script rather than a PBS script.

    Returns
    -------
    fn : str
        Path to PBS/shell script.

    """
    assert threads >= 3

    if shell:
        pbs = False
    else: 
        pbs = True

    temp_dir = os.path.join(temp_dir, '{}_alignment'.format(sample_name))
    out_dir = os.path.join(out_dir, '{}_alignment'.format(sample_name))

    # I'm going to define some file names used later.
    r1_fastqs, temp_r1_fastqs = _process_fastqs(r1_fastqs, temp_dir)
    r2_fastqs, temp_r2_fastqs = _process_fastqs(r2_fastqs, temp_dir)
    r1_nodup = os.path.join(temp_dir, 'nodup_R1.fastq.gz')
    r2_nodup = os.path.join(temp_dir, 'nodup_R2.fastq.gz')
    aligned_bam = os.path.join(temp_dir, 'Aligned.out.bam')
    coord_sorted_bam = os.path.join(temp_dir, 'Aligned.out.coord.sorted.bam')
    bam_index = os.path.join(temp_dir, 'Aligned.out.coord.sorted.bam.bai')
    
    # Files to copy to output directory.
    files_to_copy = [coord_sorted_bam, bam_index, 'Log.out', 'Log.final.out',
                     'Log.progress.out', 'SJ.out.tab',
                     'Aligned.toTranscriptome.out.bam',
                     'Aligned.out.coord.sorted.bam.md5']
    # Temporary files that can be deleted at the end of the job. We may not want
    # to delete the temp directory if the temp and output directory are the
    # same.
    files_to_remove = [temp_r1_fastqs, temp_r2_fastqs, r1_nodup, r2_nodup]

    if strand_specific:
        out_bigwig_plus = os.path.join(temp_dir,
                                       '{}_plus_rna.bw'.format(sample_name))
        out_bigwig_minus = os.path.join(temp_dir,
                                        '{}_minus_rna.bw'.format(sample_name))
        files_to_copy.append(out_bigwig_plus)
        files_to_copy.append(out_bigwig_minus)
    else:
        out_bigwig = os.path.join(temp_dir, '{}_rna.bw'.format(sample_name))
        files_to_copy.append(out_bigwig)

    try:
        os.makedirs(out_dir)
    except OSError:
        pass

    if shell:
        fn = os.path.join(out_dir, '{}_alignment.sh'.format(sample_name))
    else:
        fn = os.path.join(out_dir, '{}_alignment.pbs'.format(sample_name))

    f = open(fn, 'w')
    f.write('#!/bin/bash\n\n')
    if pbs:
        out = os.path.join(out_dir, '{}_alignment.out'.format(sample_name))
        err = os.path.join(out_dir, '{}_alignment.err'.format(sample_name))
        job_name = '{}_align'.format(sample_name)
        f.write(_pbs_header(out, err, job_name, threads))

    f.write('mkdir -p {}\n'.format(temp_dir))
    f.write('cd {}\n'.format(temp_dir))
    f.write('rsync -avz {} {} .\n\n'.format(r1_fastqs, r2_fastqs))

    # Remove duplicates if desired and align.
    if remove_dup:
        lines = _cbarrett_paired_dup_removal(temp_r1_fastqs, temp_r2_fastqs,
                                             r1_nodup, r2_nodup, temp_dir)
        f.write(lines)
        f.write('wait\n\n')

        lines = _star_align(r1_nodup, r2_nodup, sample_name, rgpl, rgpu,
                            star_index, star_path, threads)
        f.write(lines)
        f.write('wait\n\n')
    else:
        lines = _star_align(temp_r1_fastqs, temp_r2_fastqs, sample_name, rgpl,
                            rgpu, star_index, star_path, threads)
        f.write(lines)
        f.write('wait\n\n')

    # Coordinate sort bam file.
    lines = _picard_coord_sort(aligned_bam, coord_sorted_bam, bam_index,
                               picard_path, picard_memory, temp_dir)
    f.write(lines)
    f.write('wait\n\n')

    # Make bigwig files for displaying coverage.
    if strand_specific:
        lines = _bigwig_files(coord_sorted_bam, out_bigwig_plus, sample_name,
                              bedgraph_to_bigwig_path, bedtools_path,
                              out_bigwig_minus=out_bigwig_minus)
    else:
        lines = _bigwig_files(coord_sorted_bam, out_bigwig, sample_name,
                              bedgraph_to_bigwig_path, bedtools_path)
    f.write(lines)
    f.write('wait\n\n')

    # Make softlinks and tracklines for genome browser.
    if strand_specific:
        lines = _genome_browser_files(tracklines_file, link_dir, web_path_file,
                                      coord_sorted_bam, bam_index,
                                      out_bigwig_plus, sample_name, out_dir,
                                      bigwig_minus=out_bigwig_minus)
    else:
        lines = _genome_browser_files(tracklines_file, link_dir, web_path_file,
                                      coord_sorted_bam, bam_index, out_dir,
                                      out_bigwig, sample_name)
    f.write(lines)
    f.write('wait\n\n')

    f.write('rsync -avz \\\n\t{} \\\n \t{}\n\n'.format(
        ' \\\n\t'.join(files_to_copy),
        out_dir))
    f.write('rm \\\n\t{}\n\n'.format(' \\\n\t'.join(files_to_remove)))

    if temp_dir != out_dir:
        f.write('rm -r {}\n'.format(temp_dir))
    f.close()

    return fn

def _dexseq_count(bam, counts_file, dexseq_annotation, paired=True,
                  stranded=False, samtools_path='.'):
    """
    Count reads overlapping exonic bins for DEXSeq.

    Parameters
    ----------
    bam : str
        Path to coordinate sorted bam file to count reads for.

    counts_file : str
        File to write bin counts to.

    dexseq_annotation : str
        Path to DEXSeq exonic bins GFF file.

    paired : boolean
        True if the data is paired-end. False otherwise.

    stranded : boolean
        True if the data is strand-specific. False otherwise.

    Returns
    -------
    lines : str
        Lines to be printed to shell/PBS script.

    name : str
        File name for the softlink.

    """
    import readline
    import rpy2.robjects as robjects
    robjects.r('suppressPackageStartupMessages(library(DEXSeq))')
    scripts = robjects.r('system.file("python_scripts", package="DEXSeq")')
    g = scripts.items()
    scripts_path = g.next()[1]
    script = os.path.join(scripts_path, 'dexseq_count.py')
    if paired:
        p = 'yes'
    else:
        p = 'no'
    if stranded:
        s = 'yes'
    else:
        s = 'no'
    lines = (
        '{} view -h -f 2 {} | '.format(samtools_path, bam) +
        'cut -f1-17,20- | python {} '.format(script) + 
        '-p {} -s {} -a 0 -r pos -f sam '.format(p, s) + 
        '{} - {} &\n\n'.format(dexseq_annotation, counts_file)
    )
    return lines

def _htseq_count(bam, counts_file, stats_file, gtf, samtools_path,
                 stranded=False):
    """
    Count reads overlapping genes for use with DESeq etc.

    Parameters
    ----------
    bam : str
        Path to coordinate sorted bam file to count reads for.

    counts_file : str
        File to write counts to.

    stats_file : str
        File to write counting stats to.

    gtf : str
        Path to GTF file to count against. Optimized for use with Gencode GTF.

    stranded : boolean
        True if the data is strand-specific. False otherwise.

    Returns
    -------
    lines : str
        Lines to be printed to shell/PBS script.

    name : str
        File name for the softlink.

    """
    import HTSeq
    if stranded:
        s = 'yes'
    else:
        s = 'no'
    script = os.path.join(HTSeq.__path__[0], 'scripts', 'count.py')
    lines = ('python {} -f bam -r pos -s {} '.format(script, s) + 
             '-a 0 -t exon -i gene_id -m union ' + 
             '{} {} > temp_out.tsv\n'.format(bam, gtf))
    lines += 'tail -n 5 temp_out.tsv > {}\n'.format(stats_file)
    lines += 'lines=$(wc -l <temp_out.tsv)\n'
    lines += 'wanted=`expr $lines - 5`\n'
    lines += 'head -n $wanted temp_out.tsv > {}\n'.format(counts_file)
    lines += 'rm temp_out.tsv\n\n'

    return lines

def get_counts(bam, out_dir, sample_name, temp_dir, dexseq_annotation, gtf,
               samtools_path, conda_env='', rpy2_file='', paired=True,
               stranded=False, shell=False):
    """
    Make a PBS or shell script for counting reads that overlap genes for DESeq2
    and exonic bins for DEXSeq.

    Parameters
    ----------
    bam : str
        Coordinate sorted bam file (genomic coordinates).

    out_dir : str
        Directory to store PBS/shell file and aligment results.

    sample_name : str
        Sample name used for naming files etc.

    temp_dir : str
        Directory to store temporary files.

    dexseq_annotation : str
        Path to DEXSeq exonic bins GFF file.

    gtf : str
        Path to GTF file to count against. Optimized for use with Gencode GTF.

    conda_env : str
        If provided, load conda environment with this name.

    rpy2_file : str
        If provided, this file will be sourced to set the environment for rpy2.

    paired : boolean
        True if the data is paired-end. False otherwise.

    stranded : boolean
        True if the data is strand-specific. False otherwise.

    shell : boolean
        If true, make a shell script rather than a PBS script.

    """
    threads = 6

    if shell:
        pbs = False
    else: 
        pbs = True

    temp_dir = os.path.join(temp_dir, '{}_counts'.format(sample_name))
    out_dir = os.path.join(out_dir, '{}_counts'.format(sample_name))

    # I'm going to define some file names used later.
    temp_bam = os.path.join(temp_dir, os.path.split(bam)[1])
    dexseq_counts = os.path.join(out_dir, 'dexseq_counts.tsv')
    gene_counts = os.path.join(out_dir, 'gene_counts.tsv')
    gene_count_stats = os.path.join(out_dir, 'gene_count_stats.tsv')
    
    # Files to copy to output directory.
    files_to_copy = []
    
    # Temporary files that can be deleted at the end of the job. We may not want
    # to delete the temp directory if the temp and output directory are the
    # same.
    files_to_remove = []

    try:
        os.makedirs(out_dir)
    except OSError:
        pass

    if shell:
        fn = os.path.join(out_dir, '{}_counts.sh'.format(sample_name))
    else:
        fn = os.path.join(out_dir, '{}_counts.pbs'.format(sample_name))

    f = open(fn, 'w')
    f.write('#!/bin/bash\n\n')
    if pbs:
        out = os.path.join(out_dir, '{}_counts.out'.format(sample_name))
        err = os.path.join(out_dir, '{}_counts.err'.format(sample_name))
        job_name = '{}_counts'.format(sample_name)
        f.write(_pbs_header(out, err, job_name, threads))

    f.write('mkdir -p {}\n'.format(temp_dir))
    f.write('cd {}\n'.format(temp_dir))
    f.write('rsync -avz {} .\n\n'.format(bam))

    if conda_env != '':
        f.write('source activate {}\n\n'.format(conda_env))
    if rpy2_file != '':
        f.write('source {}\n\n'.format(rpy2_file))

    lines = _dexseq_count(temp_bam, dexseq_counts, dexseq_annotation,
                          paired=True, stranded=stranded,
                          samtools_path=samtools_path)
    f.write(lines)
    lines = _htseq_count(temp_bam, gene_counts, gene_count_stats, gtf,
                         stranded=stranded, samtools_path=samtools_path)
    f.write(lines)
    f.write('wait\n\n')
    
    if len(files_to_copy) > 0:
        f.write('rsync -avz \\\n\t{} \\\n \t{}\n\n'.format(
            ' \\\n\t'.join(files_to_copy),
            out_dir))
    if len(files_to_remove) > 0:
        f.write('rm \\\n\t{}\n\n'.format(' \\\n\t'.join(files_to_remove)))

    if temp_dir != out_dir:
        f.write('rm -r {}\n'.format(temp_dir))
    f.close()

    return fn
