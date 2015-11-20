import os

from general import JobScript

class RNAJobScript(JobScript):
    def star_align(
        self,
        r1_fastq, 
        r2_fastq, 
        rgpl, 
        rgpu, 
        star_index, 
        threads,
        genome_load='LoadAndRemove',
        transcriptome_align=True,
        star_path='STAR',
    ):
        """
        Align paired fastq files with STAR.
    
        Parameters
        ----------
        r1_fastq : str 
            Path to R1 fastq file.
    
        r2_fastq : str 
            Path to R2 fastq file.
    
        rgpl : str
            Read Group platform (e.g. illumina, solid). 
    
        rgpu : str
            Read Group platform unit (eg. run barcode). 

        Returns
        -------
        bam : str
            Path to output alignment bam file.
        
        log_out : str
            Path to log file.

        log_final_out : str
            Path to final log file.
        
        log_progress_out : str
        Path to progress log file.
        
        sj_out : str
            Path to output SJ.out.tab file.

        transcriptome_bam : str
            Path to output transcriptome alignment bam file. This is returned
            only if transcriptome_align == True.
    
        """
        lines = (' \\\n\t'.join([
            star_path, 
            '--runThreadN {}'.format(threads),
            '--genomeDir {}'.format(star_index), 
            '--genomeLoad {}'.format(genome_load),
            '--readFilesCommand zcat',
            '--readFilesIn {} {}'.format(r1_fastq, r2_fastq),
            '--outSAMattributes All', 
            '--outSAMunmapped Within',
            '--outSAMattrRGline ID:1 PL:{} PU:{} LB:{} SM:{}'.format(
                rgpl, rgpu, self.sample_name, self.sample_name),
            '--outFilterMultimapNmax 20', 
            '--outFilterMismatchNmax 999',
            '--alignIntronMin 20',
            '--alignIntronMax 1000000',
            '--alignMatesGapMax 1000000',
            '--outSAMtype BAM Unsorted']))
        if transcriptome_align:
            lines +=  ' \\\n\t--quantMode TranscriptomeSAM'
        lines += '\n\n'
        lines += 'if [ -d _STARtmp ] ; then rm -r _STARtmp ; fi\n\n'
        bam = os.path.join(
            self.tempdir, '{}.bam'.format(sample_name))
        log_out = os.path.join(
            self.tempdir, '{}_Log.out'.format(self.sample_name))
        log_final_out = os.path.join(
            self.tempdir, '{}_Log.final.out'.format(self.sample_name))
        log_progress_out = os.path.join(
            self.tempdir, '{}_Log.progress.out'.format(self.sample_name))
        sj_out = os.path.join(
            self.tempdir, '{}_SJ.out.tab'.format(self.sample_name))
        transcriptome_bam = os.path.join(
            self.tempdir, '{}_transcriptome.bam'.format(self.sample_name))
        lines += 'mv Aligned.out.bam {}\n'.format(bam)
        lines += 'mv Log.out {}\n'.format(log_out)
        lines += 'mv Log.final.out {}\n'.format(log_final_out)
        lines += 'mv Log.progress.out {}\n'.format(log_progress_out)
        lines += 'mv SJ.out.tab {}\n'.format(sj_out)
        lines += 'mv Aligned.toTranscriptome.out.bam {\n\n}'.format(
            transcriptome_bam)
        with open(job.filename, "a") as f:
            f.write(lines)
        if transcriptome_align:
            return (bam, log_out, log_final_out, log_progress_out, sj_out,
                    transcriptome_bam)
        else:
            return bam, log_out, log_final_out, log_progress_out, sj_out

    def rsem_calculate_expression(
        self,
        bam, 
        reference, 
        threads=1, 
        ci_mem=1024, 
        strand_specific=True,
        rsem_calculate_expression_path='rsem-calculate-expression',
    ):
        """
        Estimate expression using RSEM.
    
        Parameters
        ----------
        bam : str
            Transcriptome bam file.
    
        reference : str
            RSEM reference.
    
        ci_mem : int
            Amount of memory in mb to give RSEM for calculating confidence
            intervals. Passed to --ci-memory for RSEM.
    
        strand_specific : boolean
            True if the data is strand-specific. False otherwise. For now, this
            means that the R1 read is on the reverse strand.
    
        Returns
        -------
        genes : str
            Path to genes output file.

        isoforms : str
            Path to isoforms output file.

        stats : str
            Path to output stats files.

        """
        genes = os.path.join(self.tempdir,
                             '{}.genes.results'.format(self.sample_name))
        isoforms = os.path.join(self.tempdir,
                                '{}.isoforms.results'.format(self.sample_name))
        stats = os.path.join(self.tempdir, '{}.stat'.format(self.sample_name))
        line = ('{} --bam --paired-end --num-threads {} '
                '--no-bam-output --seed 3272015 --calc-ci '
                '--ci-memory {} --estimate-rspd \\\n\t{} \\\n\t{} {}'.format(
                    rsem_calculate_expression_path, threads, ci_mem, bam,
                    reference, self.sample_name))
        if strand_specific:
            line += '\\\n\t--forward-prob 0'
        line += '\n'
        with open(job.filename, "a") as f:
            f.write(line)
        return genes, isoforms, stats

    def dexseq_count(
        self,
        bam, 
        dexseq_annotation, 
        paired=True,
        strand_specific=True, 
        dexseq_count_path=None,
        samtools_path='samtools'):
        """
        Count reads overlapping exonic bins for DEXSeq.
    
        Parameters
        ----------
        bam : str
            Path to coordinate sorted bam file to count reads for.
    
        dexseq_annotation : str
            Path to DEXSeq exonic bins GFF file.
    
        paired : boolean
            True if the data is paired-end. False otherwise.
    
        strand_specific : boolean
            True if the data is strand-specific. False otherwise.

        dexseq_count_path : str
            Path to dexseq_count.py script. If not provided, rpy2 will look for
            the path in R.
    
        Returns
        -------
        counts_file : str
            Path to file with bin counts.
    
        """
        counts_file = os.path.join(
            self.tempdir, '{}_dexseq_counts.tsv'.format(self.sample_name))
        if dexseq_count_path is None:
            import readline
            import rpy2.robjects as robjects
            robjects.r('suppressPackageStartupMessages(library(DEXSeq))')
            scripts = robjects.r('system.file("python_scripts", package="DEXSeq")')
            g = scripts.items()
            scripts_path = g.next()[1]
            dexseq_count_path = os.path.join(scripts_path, 'dexseq_count.py')
        if paired:
            p = 'yes'
        else:
            p = 'no'
        if strand_specific:
            s = 'reverse'
        else:
            s = 'no'
        lines = (
            '{} view -h -f 2 {} \\\n\t'.format(samtools_path, bam) +
            '| cut -f1-16,20- \\\n\t| python {} \\\n\t'.format(dexseq_count_path) + 
            '-p {} -s {} -a 0 -r pos -f sam \\\n\t'.format(p, s) + 
            '{} \\\n\t- {}\n\n'.format(dexseq_annotation, counts_file)
        )
        with open(job.filename, "a") as f:
            f.write(line)
        return counts_file
    
    def htseq_count(
        self,
        bam, 
        gtf, 
        strand_specific=False,
        samtools_path='samtools',
    ):
        """
        Count reads overlapping genes for use with DESeq etc.
    
        Parameters
        ----------
        bam : str
            Path to coordinate sorted bam file to count reads for.
    
        gtf : str
            Path to GTF file to count against. Optimized for use with Gencode
            GTF.
    
        strand_specific : boolean
            True if the data is strand-specific. False otherwise.
    
        Returns
        -------
        lines : str
            Lines to be printed to shell script.
    
        name : str
            File name for the softlink.
   
        Returns
        -------
        counts_file : str
            Path to file with gene counts.
    
        stats_file : str
            Path to file with counting stats.
    
        """
        counts_file = os.path.join(
            self.tempdir, '{}_gene_counts.tsv'.format(self.sample_name))
        stats_file = os.path.join(
            self.tempdir, '{}_gene_count_stats.tsv'.format(self.sample_name))
        import HTSeq
        if strand_specific:
            s = 'reverse'
        else:
            s = 'no'
        script = os.path.join(HTSeq.__path__[0], 'scripts', 'count.py')
        lines = ('python {} \\\n\t-f bam -r pos -s {} '.format(script, s) + 
                 '-a 0 -t exon -i gene_id -m union \\\n\t' + 
                 '{} \\\n\t{} \\\n\t> temp_out.tsv\n'.format(bam, gtf))
        lines += 'tail -n 5 temp_out.tsv > {}\n'.format(stats_file)
        lines += 'lines=$(wc -l <temp_out.tsv)\n'
        lines += 'wanted=`expr $lines - 5`\n'
        lines += 'head -n $wanted temp_out.tsv > {}\n'.format(counts_file)
        lines += 'rm temp_out.tsv\n\n'
        with open(job.filename, "a") as f:
            f.write(line)
        return counts_file, stats_file

    def bedgraph_from_bam(
        self,
        bam, 
        strand=None,
        scale=None,
        bedtools_path='bedtools',
        sambamba_path='sambamba',
    ):
        """
        Make lines that create a coverage bedgraph file.
    
        Parameters
        ----------
        bam : str
            Bam file to calculate coverage for.
    
        bedtools_path : str
            Path to bedtools.
    
        sample_name : str
            Sample name for naming files etc.
    
        strand : str
            If '+' or '-', calculate strand-specific coverage. Otherwise,
            calculate coverage using all reads.
    
        scale : float
            Scale the bigwig by this amount.

        bedtools_path : str
            Path to bedtools. If bedtools_path == 'bedtools', it is assumed that
            the hg19 human.hg19.genome file from bedtools is also in your path.

        Returns
        -------
        bedgraph : str
            Path to output bedgraph file.
    
        """
        fn_root = self.sample_name
        if strand:
            fn_root += '_{}'.format(strand)
        if scale:
            fn_root += '_scaled'.format(scale)
        bedgraph = os.path.join(self.tempdir, '{}.bg'.format(fn_root))

        if bedtools_path == 'bedtools':
            genome_file = 'human.hg19.genome'
        else:
            genome_file = os.path.join(
                os.path.split(os.path.split(bedtools_path)[0])[0], 'genomes',
                'human.hg19.genome')

        if strand == '+':
            lines = (
                '{} view -f bam -F (first_of_pair and mate_is_reverse_strand) '
                'or (second_of_pair and reverse_strand) {} | {} genomecov '
                '-ibam stdin -g {} -split -bg -trackline -trackopts '
                '\'name="{}"\' '.format(
                    sambamba_path, bam, bedtools_path, genome_file, fn_root))
        if strand == '-':
            lines = (
                '{} view -f bam -F (second_of_pair and mate_is_reverse_strand) '
                'or (first_of_pair and reverse_strand) {} \\\n | {} genomecov '
                '-ibam stdin -g {} -split -bg -trackline -trackopts '
                '\'name="{}"\' '.format(
                    sambamba_path, bam, bedtools_path, genome_file, fn_root))
        if scale:
            lines += ' -scale {}'.format(scale)
        
        lines += ' > {}\n\n'.format( bedgraph)

        with open(job.filename, "a") as f:
            f.write(lines)
        return bedgraph
    
    def bigwig_from_bedgraph(
        self,
        bedgraph,
        strand=None,
        scale=None,
        web_available=True,
        write_to_outdir=False,
        bedGraphToBigWig_path='bedGraphToBigWig',
        bedtools_path='bedtools',
    ):
        """
        Make bigwig coverage file from bam file.
    
        Parameters
        ----------
        bedgraph : str
            Path to bedgraph file to create bigwig for.
        
        strand : str
            If '+' or '-', add this information to trackline.
    
        scale : float
            Add note to trackline that data is scaled.

        web_available : bool
            If True, write trackline to self.links_tracklines, make softlink to
            self.linkdir, and set write_to_outdir = True.

        write_to_outdir : bool
            If True, write output files directly to self.outdir.
    
        bedGraphToBigWig_path : str
            Path to bedGraphToBigWig executable.

        bedtools_path : str
            Path to bedtools. If bedtools_path == 'bedtools', it is assumed that
            the hg19 human.hg19.genome file from bedtools is also in your path.

        Returns
        -------
        bigwig : str
            Path to output bigwig file.
    
        """
        if write_to_outdir or web_available:
            dy = self.outdir
        else:
            dy = self.tempdir
        if bedtools_path == 'bedtools':
            genome_file = 'human.hg19.genome'
        else:
            genome_file = os.path.join(
                os.path.split(os.path.split(bedtools_path)[0])[0], 'genomes',
                'human.hg19.genome')
        root = os.path.splitext(os.path.split(bedgraph)[1])[0]
        bigwig = os.path.join(dy, '{}.bw'.format(root))
        lines = '{} {} {} {}\n\n'.format(bedGraphToBigWig_path, bedgraph,
                                     genome_file, bigwig)
        with open(job.filename, "a") as f:
            f.write(lines)
        if web_available:
            name = '{}_rna_'.format(self.sample_name)
            desc = 'RNAseq coverage for {}.'.format(self.sample_name)
            if strand == '+':
                name += '_plus'
                desc = desc.replace('RNAseq coverage', 
                                    'RNAseq plus strand coverage')
            elif strand == '-':
                name += '_minus'
                desc = desc.replace('RNAseq coverage', 
                                    'RNAseq minus strand coverage')
            if scale:
                name += '_scaled'
                desc = desc.replace('RNAseq', 'Scaled RNAseq')

            url = self.webpath + '/' + os.path.split(bigwig)[1]
            t_lines = (
                'track type=bigWig name="{}" '
                'description="{}" '
                'visibility=0 db=hg19 bigDataUrl={}\n'.format(
                    name, desc, url))
            with open(self.links_tracklines, "a") as f:
                f.write(t_lines)
            link = self.add_softlink(bigwig)

        return bigwig
        
def pipeline(
    r1_fastqs, 
    r2_fastqs, 
    outdir, 
    sample_name, 
    star_index,
    ref_flat, 
    rrna_intervals,
    dexseq_annotation,
    gene_gtf,
    exon_bed,
    rsem_reference,
    find_intersecting_snps_path, 
    filter_remapped_reads_path,
    genome_fasta,
    linkdir=None,
    webpath_file=None,
    vcf=None,
    vcf_sample_name=None,
    is_phased=False,
    conda_env=None,
    modules=None,
    queue=None,
    star_genome_load='LoadAndRemove',
    rgpl='ILLUMINA',
    rgpu='',
    strand_specific=True, 
    tempdir=None,
    mappability=None,
    star_path='STAR',
    picard_path='$picard',
    bedtools_path='bedtools',
    bedGraphToBigWig_path='bedGraphToBigWig',
    fastqc_path='fastqc',
    samtools_path='samtools',
    sambamba_path='sambamba',
    rsem_calculate_expression_path='rsem-calculate-expression',
    gatk_path='$GATK',
    bigWigAverageOverBed_path='bigWigAverageOverBed',
    bcftools_path='bcftools',
):
    """
    Make a shell script for aligning RNA-seq reads with STAR. The defaults are
    set for use on the Frazer lab's SGE scheduler on flh1/flh2.

    Parameters
    ----------
    r1_fastqs : list or str
        Either a list of paths to gzipped fastq files with R1 reads or path to a
        single gzipped fastq file with R1 reads.

    r2_fastqs : list or str
        Either a list of paths to gzipped fastq files with R2 reads or path to a
        single gzipped fastq file with R2 reads.

    outdir : str
        Directory to store shell file and aligment results.

    sample_name : str
        Sample name used for naming files etc.

    star_index : str
        Path to STAR index.

    ref_flat : str
        Path to refFlat file with non-rRNA genes. Can ge gzipped.

    rrna_intervals : str
        Path to interval list file with rRNA intervals.

    dexseq_annotation : str
        Path to DEXSeq exonic bins GFF file.

    gene_gtf : str
        Path to GTF file with gene annotations.

    exon_bed : str
        Path to bed file with exon definitions. The exons should be merged so
        that no bed file entries overlap each other.

    rsem_reference : str
        Directory with RSEM reference.

    find_intersecting_snps_path : str
        Path to find_intersecting_snps.py from WASP.
    
    filter_remapped_reads_path : str
        Path to filter_remapped_reads.py from WASP.

    linkdir : str
        Path to directory where softlinks should be made. Some pipeline parts
        may make softlinks output files here for display on the web.

    webpath_file : str
        File whose first line is the URL that points to linkdir. For example,
        if we make a link to the file s1_coord_sorted.bam in linkdir and
        webpath_file has http://site.com/files on its first line, then
        http://site.com/files/s1_coord_sorted.bam should be available on the
        web. If the web directory is password protected (it probably should be),
        then the URL should look like http://username:password@site.com/files.
        This is a file so you don't have to make the username/password combo
        public (although I'd recommend not using a sensitive password). You can
        just put the webpath_file in a directory that isn't tracked by git, 
        figshare, etc.

    vcf : str
        VCF file containing exonic variants used for ASE.
    
    vcf_sample_name : str
        Sample name of this sample in the VCF file (if different than
        sample_name). For instance, the sample name in the VCF file may be the
        sample name for WGS data which may differ from the RNA-seq sample name.

    conda_env : str
        Conda environment to load at the beginning of the script.

    modules : str
        Comma-separated list of modules to load at the beginning of the script.

    rgpl : str
        Read Group platform (e.g. illumina, solid). 

    rgpu : str
        Read Group platform unit (eg. run barcode). 

    strand_specific : boolean
        If false, data is not strand specific.

    tempdir : str
        Directory to store temporary files.

    star_path : str
        Path to STAR aligner.

    picard_path : str
        Path to Picard tools.

    bedtools_path : str
        Path to bedtools.

    bedGraphToBigWig_path : str
        Path bedGraphToBigWig executable.

    Returns
    -------
    fn : str
        Path to shell script.

    """
    with open(webpath_file) as wpf:
        webpath = wpf.readline().strip()

    # Bash commands to submit jobs. I'll collect these as I make the jobs and
    # then write them to a file at the end.
    submit_commands = []
    
    ##### Job 1: Combine fastqs and align with STAR. #####
    job = RNAJobScript(
        sample_name, 
        job_suffix='alignment',
        outdir=os.path.join(outdir, 'alignment'), 
        threads=8, 
        memory=32,
        linkdir=linkdir,
        webpath=webpath,
        tempdir=tempdir, 
        queue=queue, 
        conda_env=conda_env,
        modules=modules,
    )
    alignment_jobname = job.jobname
    
    # Input files.
    for fq in r1_fastqs + r2_fastqs:
        job.add_input_file(fq)

    # Combine R1 and R2 fastqs.
    combined_r1 = job.combine_fastqs(r1_fastqs, combined_r1, bg=True)
    combined_r2 = job.combine_fastqs(r2_fastqs, combined_r2, bg=True)
    # We don't want to keep the fastqs indefinitely, but we need them for the
    # fastQC step later.
    job.add_output_file(combined_r1)
    job.add_output_file(combined_r2)

    # Align reads.
    (star_bam, log_out, log_final_out, log_progress_out, sj_out, 
     transcriptome_bam) = \
            job.star_align(combined_r1, combined_r2, rgpl, rgpu, star_index,
                            job.threads, genome_load=star_genome_load)
    star_bam = job.add_output_file(star_bam)
    transcriptome_bam = job.add_output_file(transcriptome_bam)
    log_final_out = job.add_output_file(log_final_out)
    [job.add_output_file(x) for x in [log_out, log_progress_out, sj_out]]
    job.write_end()
    submit_commands.append(job.sge_submit_comand())

    ##### Job 2: Run fastQC. ##### 
    job = JobScript(
        sample_name, 
        job_suffix='fastqc', 
        outdir=os.path.join(outdir, 'qc'), 
        shell_fn=fastqc_shell,
        threads=1, 
        memory=4,
        linkdir=linkdir,
        webpath=webpath,
        tempdir=tempdir, 
        queue=queue, 
        conda_env=conda_env,
        modules=modules, 
        wait_for=[alignment_jobname]
    )
    fastqc_jobname = job.jobname
 
    # Input files.
    job.add_input_file(combined_r1, delete_original=True)
    job.add_input_file(combined_r2, delete_original=True)

    # Run fastQC.
    fastqc_html, fastqc_zip = job.fastqc([combined_r1, combined_r2], job.outdir,
                                         job.threads, fastqc_path)
    job.add_output_file(fastqc_html)
    job.add_output_file(fastqc_zip)
        
    job.write_end()
    submit_commands.append(job.sge_submit_comand())

    ##### Job 3: Coordinate sort, mark duplicates and index bam. #####
    job = JobScript(
        sample_name, 
        job_suffix = 'sort_mdup_index',
        outdir=os.path.join(outdir, 'alignment'), 
        threads=1, 
        memory=4,
        linkdir=linkdir,
        webpath=webpath,
        tempdir=tempdir, 
        queue=queue, 
        conda_env=conda_env,
        modules=modules,
        wait_for=[alignment_jobname]
    )
    sort_mdup_index_jobname = job.jobname

    # Input files.
    star_bam = job.add_input_file(star_bam, delete_original=True)

    # Coordinate sort.
    job.temp_files_to_delete.append(star_bam)
    coord_sorted_bam = job.picard_coord_sort(
        star_bam, 
        picard_path=picard_path,
        picard_memory=job.memory,
        picard_tempdir=job.tempdir)
    job.add_temp_file(coord_sorted_bam)

    # Mark duplicates.
    mdup_bam, duplicates_metrics = job.picard_mark_duplicates(
        coord_sorted_bam, 
        picard_path=picard_path,
        picard_memory=job.memory,
        picard_tempdir=job.tempdir)
    job.add_output_file(mdup_bam)
    job.add_output_file(duplicate_metrics)
    link = job.add_softlink(mdup_bam)
    # TODO: Add trackline. Maybe move softlinks to mdup function?
    ## name = os.path.split(mdup_bam)[1]
    ## job.add_softlink(os.path.join(job.outdir, name), 
    ##                  os.path.join(link_dir, 'bam', name))
    ## with open(tracklines_file, "a") as tf:
    ##     tf_lines = ('track type=bam name="{}_rna_bam" '
    ##                 'description="RNAseq for {}" '
    ##                 'bigDataUrl={}/bam/{}\n'.format(
    ##                     sample_name, sample_name, webpath, name))
    ##     tf.write(tf_lines)

    # Index bam file.
    bam_index = job.picard_index(
        mdup_bam, 
        picard_path=picard_path,
        picard_memory=job.memory,
        picard_tempdir=job.tempdir, 
        bg=False)
    job.add_output_file(bam_index)
    link = job.add_softlink(bam_index)

    job.write_end()
    submit_commands.append(job.sge_submit_comand())

    ##### Job 4: Collect Picard metrics. #####
    job = JobScript(
        sample_name, 
        job_suffix, 
        job_suffix = 'picard_metrics',
        os.path.join(outdir, 'qc'),
        threads=1, 
        memory=4, 
        linkdir=linkdir,
        webpath=webpath,
        tempdir=tempdir, 
        queue=queue,
        conda_env=conda_env, 
        modules=modules,
        wait_for=[sort_mdup_index_jobname],
    )
    picard_metrics_jobname = job.jobname
    
    # Input files.
    mdup_bam = job.add_input_file(mdup_bam)

    # Collect several different Picard metrics including insert size.
    metrics_files = job.picard_collect_multiple_metrics(
        mdup_bam, 
        picard_path=picard_path, 
        picard_memory=job.memory,
        picard_tempdir=job.tempdir,
        bg=False)
    for fn in metrics_files:
        job.add_output_file(fn)

    # Collect RNA seq metrics.
    metrics, chart = job.picard_collect_rna_seq_metrics(
        mdup_bam, 
        ref_flat, 
        rrna_intervals,
        picard_path=picard_path,
        picard_memory=job.memory,
        picard_tempdir=job.tempdir,
        strand_specific=strand_specific, 
        bg=False)
    job.add_output_file(metrics)
    job.add_output_file(chart)

    # Collect index stats.
    index_out, index_err = job.picard_bam_index_stats(
        mdup_bam, 
        picard_path=picard_path,
        picard_memory=job.memory,
        picard_tempdir=job.tempdir,
        bg=False)
    job.add_output_file(index_out)
    job.add_output_file(index_err)

    job.write_end()
    submit_commands.append(job.sge_submit_comand())

    ##### Job 5: Make md5 has for final bam file. #####
    job = JobScript(
        sample_name, 
        job_suffix = 'md5',
        outdir=os.path.join(outdir, 'alignment'), 
        threads=1, 
        memory=1,
        linkdir=linkdir,
        webpath=webpath,
        tempdir=tempdir, 
        queue=queue, 
        conda_env=conda_env,
        modules=modules,
        wait_for=[sort_mdup_index_jobname],
    )
    md5_jobname = job.jobname
    
    # Input files.
    mdup_bam = job.add_input_file(mdup_bam)

    # Make md5 hash for output bam file.
    md5sum = job.make_md5sum(mdup_bam)
    job.add_output_file(md5sum)

    job.write_end()
    submit_commands.append(job.sge_submit_comand())
       
    ##### Job 6: Make bigwig files for final bam file. #####
    job_suffix = 'bigwig'
    bigwig_jobname = '{}_{}'.format(sample_name, job_suffix)
    bigwig_shell = os.path.join(outdir, 'sh', '{}.sh'.format(bigwig_jobname))
    exists = os.path.exists(bigwig_shell)
    if exists:
        bigwig_shell = tempfile.NamedTemporaryFile(delete=False).name

    job = JobScript(
        sample_name, 
        job_suffix, 
        os.path.join(outdir, 'alignment'), 
        threads=1, 
        memory=4,
        linkdir=linkdir,
        webpath=webpath,
        tempdir=tempdir, 
        queue=queue, 
        conda_env=conda_env,
        modules=modules,
        wait_for=[sort_mdup_index_jobname])
        
    # Input files.
    mdup_bam = job.add_input_file(mdup_bam)

    # First make bigwig from both strands.
    bg = bedgraph_from_bam(
        mdup_bam, 
        bedtools_path=bedtools_path,
        sambamba_path=sambamba_path,
    )
    job.temp_files_to_delete.append(bg)
    bw = job.bigwig_from_bedgraph(
        bg,
        bedGraphToBigWig_path=bedGraphToBigWig_path,
        bedtools_path=bedtools_path,
    )
    job.add_output_file(bw)

    # Now for genes on the plus strand.
    plus_bg = bedgraph_from_bam(
        mdup_bam, 
        strand='+',
        bedtools_path=bedtools_path,
        sambamba_path=sambamba_path,
    )
    job.temp_files_to_delete.append(plus_bg)
    plus_bw = job.bigwig_from_bedgraph(
        bg,
        strand='+',
        scale=None,
        bedGraphToBigWig_path=bedGraphToBigWig_path,
        bedtools_path=bedtools_path,
    )
    job.add_output_file(plus_bw)

    # Now for genes on the minus strand.
    minus_bg = bedgraph_from_bam(
        mdup_bam, 
        strand='-',
        bedtools_path=bedtools_path,
        sambamba_path=sambamba_path,
    )
    job.temp_files_to_delete.append(minus_bg)
    minus_bw = job.bigwig_from_bedgraph(
        bg,
        strand='-',
        scale=None,
        bedGraphToBigWig_path=bedGraphToBigWig_path,
        bedtools_path=bedtools_path,
    )
    job.add_output_file(minus_bw)

    # Now we'll make scaled versions.
    # # TODO: working here. Needed to figure out how to make scaled versions.
    # # Both strands.
    # bg = bedgraph_from_bam(
    #     mdup_bam, 
    #     bedtools_path=bedtools_path,
    #     sambamba_path=sambamba_path,
    # )
    # job.temp_files_to_delete.append(bg)
    # bw = job.bigwig_from_bedgraph(
    #     bg,
    #     bedGraphToBigWig_path=bedGraphToBigWig_path,
    #     bedtools_path=bedtools_path,
    # )
    # job.output_files_to_copy.append(bw)

    # # Now for genes on the plus strand.
    # plus_bg = bedgraph_from_bam(
    #     mdup_bam, 
    #     strand='+',
    #     bedtools_path=bedtools_path,
    #     sambamba_path=sambamba_path,
    # )
    # job.temp_files_to_delete.append(plus_bg)
    # plus_bw = job.bigwig_from_bedgraph(
    #     bg,
    #     strand='+',
    #     scale=None,
    #     bedGraphToBigWig_path=bedGraphToBigWig_path,
    #     bedtools_path=bedtools_path,
    # )
    # job.output_files_to_copy.append(plus_bw)

    # # Now for genes on the minus strand.
    # minus_bg = bedgraph_from_bam(
    #     mdup_bam, 
    #     strand='-',
    #     bedtools_path=bedtools_path,
    #     sambamba_path=sambamba_path,
    # )
    # job.temp_files_to_delete.append(minus_bg)
    # minus_bw = job.bigwig_from_bedgraph(
    #     bg,
    #     strand='-',
    #     scale=None,
    #     bedGraphToBigWig_path=bedGraphToBigWig_path,
    #     bedtools_path=bedtools_path,
    # )
    # job.output_files_to_copy.append(minus_bw)

    job.write_end()
    submit_commands.append(job.sge_submit_comand())
    
    ##### Job 7: Get HTSeq and DEXSeq counts. #####
    job = RNAJobScript(
        sample_name, 
        job_suffix = 'counts',
        outdir=os.path.join(outdir, 'counts'), 
        threads=1, 
        memory=4,
        linkdir=linkdir,
        webpath=webpath,
        tempdir=tempdir, 
        queue=queue, 
        conda_env=conda_env,
        modules=modules,
        wait_for=[sort_mdup_index_jobname],
    )
    counts_jobname = job.jobname
    
    # Input files.
    mdup_bam = job.add_input_file(mdup_bam)

    # Get gene counts.
    gene_counts, gene_count_stats = job.htseq_count(
        mdup_bam, 
        gene_gtf, 
        strand_specific=strand_specific,
        samtools_path=samtools_path)
    job.add_output_file(gene_counts)
    job.add_output_file(gene_count_stats)

    # Get DEXSeq bin counts.
    dexseq_counts = job.dexseq_count(
        mdup_bam, 
        dexseq_annotation,
        paired=True, 
        strand_specific=strand_specific,
        samtools_path=samtools_path)
    job.add_output_file(dexseq_counts)

    job.write_end()
    submit_commands.append(job.sge_submit_comand())
    
    ##### Job 8: Run RSEM. #####
    job = RNAJobScript(
        sample_name, 
        job_suffix = 'rsem',
        outdir=os.path.join(outdir, 'rsem'),
        threads=8, 
        memory=4, 
        linkdir=linkdir,
        webpath=webpath,
        tempdir=tempdir, queue=queue,
        conda_env=conda_env, 
        modules=modules,
        wait_for=[sort_mdup_index_jobname],
    )
    rsem_jobname = job.jobname
    
    # Input files.
    transcriptome_bam = job.add_input_file(mdup_bam)

    # Run RSEM.
    genes, isoforms, stats = job.rsem_calculate_expression(
        transcriptome_bam, 
        rsem_reference, 
        threads=job.threads, 
        ci_mem=1024,
        strand_specific=strand_specific,
        rsem_calculate_expression_path=rsem_calculate_expression_path,
    )
    job.add_output_file(genes)
    job.add_output_file(isoforms)
    job.add_output_file(stats)

    job.write_end()
    submit_commands.append(job.sge_submit_comand())
   
    # We'll only go through the ASE steps if a VCF was provided.
    if vcf:
        ##### Job 9: WASP first step. #####
        job = JobScript(
            sample_name, 
            job_suffix = 'wasp_allele_swap',
            outdir=os.path.join(outdir, 'wasp'),
            threads=1, 
            memory=4, 
            linkdir=linkdir,
            webpath=webpath,
            tempdir=tempdir, 
            queue=queue,
            conda_env=conda_env, 
            modules=modules,
            wait_for=[sort_mdup_index_jobname],
        )
        wasp_allele_swap_jobname = job.jobname
           
        # Input files.
        mdup_bam = job.add_input_file(mdup_bam)
        # The VCF might be large so we probably don't want to copy it ever.
        vcf = job.add_input_file(vcf, copy=False)
        # The exon bed file is small so we don't need to copy it ever.
        exon_bed = job.add_input_file(exon_bed, copy=False)

        # Run WASP allele swap.
        if not vcf_sample_name:
            vcf_sample_name = sample_name
        (snp_directory, keep_bam, wasp_r1_fastq, wasp_r2_fastq, to_remap_bam,
         to_remap_num) = job.wasp_allele_swap(
            mdup_bam, 
            find_intersecting_snps_path, 
            vcf, 
            exon_bed,
            vcf_sample_name=vcf_sample_name, 
            threads=1,
            samtools_path='samtools',
        )
        # WASP outputs a file (keep_bam) that has reads that don't overlap
        # variants.  I'm going to discard that file.
        job.add_temp_file(keep_bam)
        job.add_output_file(snp_directory)
        job.add_output_file(wasp_r1_fastq)
        job.add_output_file(wasp_r2_fastq)
        job.add_output_file(to_remap_bam)
        job.add_output_file(to_remap_num)

        job.write_end()
        submit_commands.append(job.sge_submit_comand())
        
        ##### Job 10: WASP second step. #####
        job = JobScript(
            sample_name, 
            job_suffix = 'wasp_remap',
            os.path.join(outdir, 'wasp'),
            threads=8, 
            memory=10, 
            linkdir=linkdir,
            webpath=webpath,
            tempdir=tempdir,
            queue=queue, 
            conda_env=conda_env, 
            modules=modules,
            wait_for=[wasp_allele_swap_jobname],
        )
        wasp_remap_jobname = job.jobname
        
        # Input files.
        wasp_r1_fastq = job.add_input_file(wasp_r1_fastq, delete_original=True)
        wasp_r2_fastq = job.add_input_file(wasp_r2_fastq, delete_original=True)

        # Realign allele-swapped fastqs.
        remapped_bam, log_out, log_final_out, log_progress_out, sj_out = \
                job.star_align(wasp_r1_fastq, wasp_r2_fastq, rgpl, rgpu,
                               star_index, job.threads,
                               genome_load=star_genome_load,
                               transcriptome_align=False)
        job.add_output_file(remapped_bam)
        job.add_output_file(log_out)
        job.add_output_file(log_final_out)
        job.add_output_file(log_progress_out)
        job.add_temp_file(sj_out)

        job.write_end()
        submit_commands.append(job.sge_submit_comand())
        
        ##### Job 11: WASP third step. #####
        job = JobScript(
            sample_name, 
            job_suffix = 'wasp_alignment_compare',
            outdir=os.path.join(outdir, 'wasp'),
            threads=1, 
            memory=4, 
            linkdir=linkdir,
            webpath=webpath,
            tempdir=tempdir, 
            queue=queue,
            conda_env=conda_env, 
            modules=modules,
            wait_for=[wasp_remap_jobname],
        )
        wasp_alignment_compare_jobname = job.jobname

        # Input files.
        to_remap_bam = job.add_input_file(to_remap_bam, delete_original=True)
        to_remap_num = job.add_input_file(to_remap_num, delete_original=True)
        remapped_bam = job.add_input_file(remapped_bam, delete_original=True)

        # Compare alignments.
        temp_filtered_bam = job.wasp_alignment_compare(
            to_remap_bam, 
            to_remap_num,
            remapped_bam, 
            filter_remapped_reads_path,
        )
        job.add_temp_file(temp_filtered_bam)
            
        # Coordinate sort and index filtered bam file.
        wasp_filtered_bam, wasp_bam_index = job.picard_coord_sort(
            temp_filtered_bam, 
            bam_index=True,
            picard_path=picard_path,
            picard_memory=job.memory,
            picard_tempdir=job.tempdir)
        job.add_output_file(wasp_filtered_bam)
        job.add_output_file(wasp_bam_index)

        # Get allele counts.
        allele_counts = job.count_allele_coverage(
            wasp_filtered_bam, 
            vcf,
            genome_fasta, 
            gatk_path=gatk_path,
        )
        job.add_output_file(allele_counts)

        job.write_end()
        submit_commands.append(job.sge_submit_comand())
        
        ##### Job 12: Run MBASED for ASE. #####
        job = JobScript(
            job_suffix = 'mbased',
            outdir=os.path.join(outdir, 'mbased'),
            threads=8, 
            memory=16, 
            linkdir=linkdir,
            webpath=webpath,
            tempdir=tempdir, 
            queue=queue,
            conda_env=conda_env, 
            modules=modules)
        mbased_jobname = job.jobname
    
        # Input files.
        allele_counts = job.add_input_file(allele_counts)

        mbased_infile, locus_outfile, snv_outfile = job.mbased(
            allele_counts, 
            feature_bed, 
            is_phased=is_phased, 
            num_sim=1000000, 
            threads=8, 
            vcf=vcf,
            vcf_sample_name=vcf_sample_name, 
            mappability=mappability,
            bigWigAverageOverBed_path=bigWigAverageOverBed_path,
        )
        job.add_output_file(mbased_infile)
        job.add_output_file(locus_outfile)
        job.add_output_file(snv_outfile)

        job.write_end()
        submit_commands.append(job.sge_submit_comand())

    ##### Submission script #####
    # Now we'll make a submission script that submits the jobs with the
    # appropriate dependencies.
    submit_fn = os.path.join(outdir, 'sh', 'submit.sh')
    with open(submit_fn, 'w') as f:
        f.write('#!/bin/bash\n\n')
        while True:
            try:
                jn,holds = job_holds.popitem(False)
            except:
                break
            if holds:
                f.write('qsub -hold_jid {} {}.sh\n'.format(
                    ','.join(holds), os.path.join(outdir, jn)))
            else:
                f.write('qsub {}.sh\n'.format(os.path.join(outdir, jn)))

    return submit_fn
