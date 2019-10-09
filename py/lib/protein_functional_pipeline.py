"""Runs Fama functional profiling pipeline for proteins"""
import os
import gzip
import csv
from collections import defaultdict, Counter

from lib.project.project import Project
from lib.project.sample import Sample
from lib.diamond_parser.diamond_parser import DiamondParser
from lib.diamond_parser.diamond_hit import DiamondHit
from lib.diamond_parser.diamond_hit_list import DiamondHitList
from lib.output.json_util import export_annotated_reads, export_sample
from lib.functional_profiling_pipeline import run_ref_search, run_bgr_search
from lib.output.report import generate_fasta_report, generate_protein_sample_report, \
    generate_protein_project_report
from lib.output.krona_xml_writer import make_functions_chart


def import_protein_fasta(parser):
    """Reads uncompressed or gzipped FASTA file and stores protein sequences

    Args:
        parser (:obj:DiamondParser): parser object

    Returns:
        read_count (int): number of reads in the file
        base_count (int): total number of bases in all reads
    """
    fasta_file = parser.options.get_fastq_path(parser.sample.sample_id, parser.end)
    sequence = []
    current_id = ''
    read_count = 0
    base_count = 0
    file_handle = None
    if fasta_file.endswith('.gz'):
        file_handle = gzip.open(fasta_file, 'rb')
    else:
        file_handle = open(fasta_file, 'rb')
    if file_handle:
        for line in file_handle:
            line = line.decode('utf8').rstrip('\n\r')
            if line.startswith('>'):
                read_count += 1
                if current_id != '':
                    seq_id = current_id[1:].split(' ')[0]
                    parser.reads[seq_id].read_id_line = current_id
                    parser.reads[seq_id].sequence = ''.join(sequence)
                    read_count += 1
                    base_count += len(''.join(sequence))
                sequence = []
                seq_id = line[1:].split(' ')[0]
                if seq_id in parser.reads:
                    current_id = line
                else:
                    current_id = ''
                    seq_id = None
            else:
                base_count += len(line)
                if current_id != '':
                    sequence.append(line)
        if current_id != '':
            parser.reads[seq_id].read_id_line = current_id
            parser.reads[seq_id].sequence = ''.join(sequence)
        file_handle.close()
    return read_count, base_count


def load_coverage_data(parser):
    """Loads contig coverage data, if such data were provided
    in project ini

    Args:
        parser (:obj:DiamondParser): parser object

    """
    ret_val = {}
    infile = parser.options.get_coverage_path(parser.sample.sample_id)

    if infile is None:
        return ret_val
    print('Reading coverage file...')
    file_handle = None
    if infile.endswith('.gz'):
        file_handle = gzip.open(infile, 'rb')
    else:
        file_handle = open(infile, 'rb')
    if file_handle:
        for line in file_handle:
            line = line.decode('utf8').rstrip('\n\r')
            if line.startswith('#'):
                continue
            line_tokens = line.split('\t')
            contig = line_tokens[0]
            coverage = line_tokens[1]
            ret_val[contig] = float(coverage)
        file_handle.close()
    return ret_val


def get_protein_score(average_coverage, coverage):
    """Returns relative coverage

    Args:
        average_coverage (float): average read coverage in the sample
        coverage (float): read coverage of contig

    """
    result = coverage
    if average_coverage > 0:
        result = coverage / average_coverage
    return result


def compare_hits_lca(read, hit_start, hit_end, new_hit_list, bitscore_range_cutoff,
                     average_coverage, taxonomy_data, ref_data, coverage_data=None):
    """Compares DiamondHit object assigned to AnnotatedRead object with list of new
    DiamondHit objects, assigns scores to functions and taxonomy

    Args:
        read (:obj:AnnotatedRead): protein under analysis
        hit_start (int): start position of known hit
        hit_end (int): end position of known hit
        new_hit_list (:obj:'DiamondHitList'): list of hit from new search
        bitscore_range_cutoff (float): lowest acceptaple bitscore
            (relative to top bit-score, default 0.97)
        average_coverage (float): average coverage of sequence reads in the sample
        taxonomy_data (:obj:TaxonomyData): taxonomic data
        ref_data (:obj:ReferenceData): functional reference data
        coverage_data (:obj:dict[str, float]): key is contig identifier, value
            is read coverage for this contig

    This function compares one hit assigned to a protein with a list
    of new hits. It looks through the hit list, finds hits with bitscore
    above cutoff and assigns their functions to the protein. If any hits to
    reference proteins are found, the analyzed protein gets status 'function'.
    Otherwise, it gets status 'nofunction'.

    This function does not return anything. It sets status of protein and
    assigns RPKM score to each function of the protein.

    """
    # Find coverage value for protein 'read'
    protein_id = read.read_id_line
    protein_id_tokens = protein_id.split(' # ')
    contig_id = '_'.join(protein_id_tokens[0].split('_')[:-1])[1:]
    coverage = 1.0
    if coverage_data is not None and contig_id in coverage_data:
        coverage = coverage_data[contig_id]

    #
    # Find best hit
    for hit in read.hit_list.hits:
        if hit.q_start == hit_start and hit.q_end == hit_end:
            best_bitscore = 0.0
            best_hit = None
            for new_hit in new_hit_list.hits:
                bitscore = new_hit.bitscore
                if bitscore > best_bitscore:
                    best_hit = new_hit
                    best_bitscore = bitscore
            # Set status of read
            if best_hit is not None:
                if '' in best_hit.functions:
                    read.set_status('nofunction')
                    return
                else:
                    read.set_status('function')
            else:
                read.set_status('nofunction')
                return

            # Filter list of hits by bitscore
            bitscore_lower_cutoff = best_bitscore * (1.0 - bitscore_range_cutoff)
            new_hits = [
                new_hit for new_hit in new_hit_list.hits
                if new_hit.bitscore > bitscore_lower_cutoff
                ]
            if hit.subject_id not in [
                    new_hit.subject_id for new_hit in new_hits
            ] and hit.bitscore >= best_bitscore:
                new_hits.append(hit)

            # Collect taxonomy IDs of all hits for LCA inference
            taxonomy_ids = set([ref_data.lookup_protein_tax(h.subject_id) for h in new_hits])

            # Make non-redundant list of functions from hits after filtering
            new_functions = {}
            new_functions_counter = Counter()
            new_functions_dict = defaultdict(dict)
            # Find best hit for each function: only one hit with highest bitscore will be
            # reported for each function
            for new_hit in new_hits:
                for new_func in new_hit.functions:
                    new_functions_counter[new_func] += 1
                    if new_func in new_functions_dict:
                        if new_hit.bitscore > new_functions_dict[new_func]['bit_score']:
                            new_functions_dict[new_func]['bit_score'] = new_hit.bitscore
                            new_functions_dict[new_func]['hit'] = new_hit
                    else:
                        new_functions_dict[new_func]['bit_score'] = new_hit.bitscore
                        new_functions_dict[new_func]['hit'] = new_hit

            # If the most common function in new hits is unknown, set status "nofunction" and return
            if new_functions_counter.most_common(1)[0][0] == '':
                read.set_status('nofunction')
                return

            # Calculate RPK scores for functions
            for function in new_functions_dict:
                if function == '':
                    continue
                # normalize by sample size and contig coverage
                new_functions[function] = get_protein_score(average_coverage, coverage)

            read.append_functions(new_functions)

            # Set new list of hits
            _hit_list = DiamondHitList(read.read_id)
            for new_func in new_functions_dict:
                if new_func == '':
                    continue
                good_hit = new_functions_dict[new_func]['hit']
                good_hit.query_id = read.read_id
                good_hit.annotate_hit(ref_data)
                _hit_list.add_hit(good_hit)

            read.hit_list = _hit_list
            # Set read taxonomy ID
            read.taxonomy = taxonomy_data.get_lca(taxonomy_ids)


def parse_background_output(parser):
    """Reads and processes DIAMOND tabular output of the second DIAMOND
    search.

    Args:
        parser (:obj:DiamondParser): parser object

    Note: this function takes existing list of hits and compares each
    of them with results of other similarity serach (against larger DB).
    For the comparison, it calls compare_hits_lca function, which
    in turn updates entries in the 'reads' dictionary.

    Raises:
        KeyError if read identifier not found in the 'reads' dictionary
    """
    tsvfile = os.path.join(
        parser.sample.work_directory,
        parser.sample.sample_id + '_' + parser.end + '_'
        + parser.options.background_output_name
        )

    coverage_data = load_coverage_data(parser)
    total_coverage = 0.0
    if coverage_data:
        for contig_id in coverage_data.keys():
            total_coverage += coverage_data[contig_id]
        average_coverage = total_coverage/len(coverage_data)
    else:
        average_coverage = 0.0

    current_query_id = None
    _hit_list = None
    identity_cutoff = parser.config.get_identity_cutoff(parser.collection)
    length_cutoff = parser.config.get_length_cutoff(parser.collection)
    biscore_range_cutoff = parser.config.get_biscore_range_cutoff(parser.collection)
    print('Identity cutoff: ', identity_cutoff, ', Length cutoff: ', length_cutoff)

    with open(tsvfile, 'r', newline='') as infile:
        tsvin = csv.reader(infile, delimiter='\t')
        for row in tsvin:
            if current_query_id is None:
                current_query_id = row[0]
                _hit_list = DiamondHitList(current_query_id)

            hit = DiamondHit()
            hit.create_hit(row)
            # filtering by identity and length
            if hit.identity < identity_cutoff:
                continue
            if hit.length < length_cutoff:
                continue

            if hit.query_id != current_query_id:
                _hit_list.annotate_hits(parser.ref_data)
                # compare list of hits from search in background DB with existing hit
                # from search in reference DB
                current_query_id_tokens = current_query_id.split('|')
                protein_id = '|'.join(current_query_id_tokens[:-2])
                hit_start = int(current_query_id_tokens[-2])
                hit_end = int(current_query_id_tokens[-1])
                # print (read_id, hit_start, hit_end, biscore_range_cutoff)
                if protein_id in parser.reads.keys():
                    compare_hits_lca(
                        parser.reads[protein_id], hit_start, hit_end, _hit_list,
                        biscore_range_cutoff, average_coverage, parser.taxonomy_data,
                        parser.ref_data, coverage_data
                        )
                else:
                    print('Protein not found: ', protein_id)
                current_query_id = hit.query_id
                _hit_list = DiamondHitList(current_query_id)
            _hit_list.add_hit(hit)
        _hit_list.annotate_hits(parser.ref_data)
        current_query_id_tokens = current_query_id.split('|')
        protein_id = '|'.join(current_query_id_tokens[:-2])
        hit_start = int(current_query_id_tokens[-2])
        hit_end = int(current_query_id_tokens[-1])
        if protein_id in parser.reads.keys():
            compare_hits_lca(
                parser.reads[protein_id], hit_start, hit_end, _hit_list, biscore_range_cutoff,
                average_coverage, parser.taxonomy_data, parser.ref_data, coverage_data
                )
        else:
            print('Read not found: ', protein_id)


def generate_output(project):
    """Generates output after functional profiling procedure is done

    Args:
        project (:obj:Project): current project
    """
    outfile = os.path.join(project.options.work_dir, 'all_proteins.list.txt')
    with open(outfile, 'w') as out_f:
        out_f.write(
            'Sample\tProtein\tFunction(s)\tDescription\tFama %id.\tTaxonomy ID\tTaxonomy name\n'
            )
        for sample in project.list_samples():
            if 'pe1' in project.samples[sample].reads:
                for protein_id in sorted(project.samples[sample].reads['pe1'].keys()):
                    protein = project.samples[sample].reads['pe1'][protein_id]
                    if protein.status == 'function':
                        fama_identity = sum(
                            [x.identity for x in protein.hit_list.hits]
                            ) / len(protein.hit_list.hits)
                        function = ','.join(sorted(protein.functions.keys()))
                        description = '|'.join(
                            sorted([
                                project.ref_data.lookup_function_name(f) for f
                                in protein.functions.keys()
                                ])
                            )
                        out_f.write(sample + '\t' +
                                    protein_id + '\t' +
                                    function + '\t' +
                                    description + '\t' +
                                    '{0:.1f}'.format(fama_identity) + '\t' +
                                    protein.taxonomy + '\t' +
                                    project.taxonomy_data.data[protein.taxonomy]['name'] + '\n')
                out_f.write('\n')
            else:
                out_f.write('No proteins found in ' + sample + '\n\n')


def functional_profiling_pipeline(project, sample):
    """Functional profiling pipeline for single FASTA file processing

    Args:
        project (:obj:Project): current project
        sample (:obj:Sample): current sample
    """

    parser = DiamondParser(config=project.config,
                           options=project.options,
                           taxonomy_data=project.taxonomy_data,
                           ref_data=project.ref_data,
                           sample=sample,
                           end='pe1')

    if not os.path.isdir(project.options.get_project_dir(sample.sample_id)):
        os.makedirs(project.options.get_project_dir(sample.sample_id), exist_ok=True)
    if not os.path.isdir(
            os.path.join(
                project.options.get_project_dir(sample.sample_id),
                project.options.get_output_subdir(sample.sample_id)
                )
    ):
        os.mkdir(
            os.path.join(
                project.options.get_project_dir(sample.sample_id),
                project.options.get_output_subdir(sample.sample_id)
                )
            )

    # Search in reference database
    if not os.path.exists(
            os.path.join(
                parser.options.get_project_dir(parser.sample.sample_id),
                parser.sample.sample_id + '_' + parser.end + '_'
                + parser.options.ref_output_name
                )
    ):
        run_ref_search(parser, 'blastp')

    # Process output of reference DB search
    parser.parse_reference_output()
    if not parser.reads:
        print('Hits not found in sample', sample)
        return {}

    # Import sequence data for selected sequence reads
    print('Reading FASTA file')
    read_count, base_count = import_protein_fasta(parser)

    if sample.fastq_fwd_readcount == 0:
        sample.fastq_fwd_readcount = read_count
    if sample.fastq_fwd_basecount == 0:
        sample.fastq_fwd_basecount = base_count

    print('Exporting FASTA ')
    parser.export_hit_fasta()
    print('Exporting hits')
    parser.export_hit_list()

    # Search in background database
    if not os.path.exists(
            os.path.join(
                parser.options.get_project_dir(parser.sample.sample_id),
                parser.sample.sample_id + '_' + parser.end + '_'
                + parser.options.background_output_name
                )
    ):
        run_bgr_search(parser, 'blastp')

    # Process output of background DB search
    parse_background_output(parser)

#    if not parser.reads:
#        print ('Import JSON file')
#        parser.reads = import_annotated_reads(
#            os.path.join(parser.options.get_project_dir(sample),
#            sample + '_pe1_' + parser.options.get_reads_json_name())
#        )

    # calculate_protein_coverage(parser, coverage_file)
    # calculate_protein_coverage_smooth(parser, coverage_file)

    print('Exporting JSON')
    parser.export_read_fasta()
    export_annotated_reads(parser)

    # Generate output
    print('Generating reports')
    generate_fasta_report(parser)
#    generate_protein_pdf_report(parser)
    make_functions_chart(parser, metric='readcount')
    return {read_id: read for (read_id, read) in parser.reads.items() if read.status == 'function'}


def protein_pipeline(args):
    """Functional profiling pipeline for the entire project.

    Args:
        args: ArgumentParser namespace with defined args.config (path to
            program config ini file) and args.project (path to project
            options ini file)
    """
    project = Project(config_file=args.config, project_file=args.project)
    sample_ids = []

    for sample_id in project.list_samples():
        if args.sample is not None:
            if args.sample != sample_id:
                continue
        sample = Sample(sample_id)
        sample.load_sample(project.options)
        project.samples[sample_id] = sample
        project.samples[sample_id].is_paired_end = False
        project.samples[sample_id].rpkg_scaling_factor = None
        project.samples[sample_id].rpkm_scaling_factor = None
        sample_ids.append(sample_id)

    for sample_id in sample_ids:
        # End identifier in protein pipeline is always pe1
        project.samples[sample_id].reads['pe1'] = functional_profiling_pipeline(
            project, sample=project.samples[sample_id]
            )
        export_sample(project.samples[sample_id])
        # Generate output for the sample or delete sample from memory
        generate_protein_sample_report(project, sample_id, metric='readcount')
        project.options.set_sample_data(project.samples[sample_id])

    # Generate output for the project
    if args.sample is None:
        # Skip project report if the pipeline is running for only one sample
        generate_protein_project_report(project)

    generate_output(project)
    project.save_project_options()