#!/usr/bin/python
import os,json
from Fama.DiamondParser.DiamondHit import DiamondHit
from Fama.DiamondParser.DiamondHitList import DiamondHitList
from Fama.ReadUtil.AnnotatedRead import AnnotatedRead
from Fama.GeneAssembler.Contig import Contig
from Fama.GeneAssembler.Gene import Gene
from Fama.GeneAssembler.GeneAssembly import GeneAssembly

def decode_object(o):
    if '__AnnotatedRead__' in o:
        a = AnnotatedRead()
        a.__dict__.update(o['__AnnotatedRead__'])
        return a
    elif '__DiamondHitList__' in o:
        a = DiamondHitList()
        a.__dict__.update(o['__DiamondHitList__'])
        return a
    elif '__DiamondHit__' in o:
        a = DiamondHit()
        a.__dict__.update(o['__DiamondHit__'])
        return a
    elif '__Contig__' in o:
        a = Contig()
        a.__dict__.update(o['__Contig__'])
        return a
    elif '__Gene__' in o:
        a = Gene()
        a.__dict__.update(o['__Gene__'])
        return a
    elif '__GeneAssembly__' in o:
        a = GeneAssembly()
        a.__dict__.update(o['__GeneAssembly__'])
        return a
    return o

def decode_assembly(o):
    if '__DiamondHitList__' in o:
        a = DiamondHitList()
        a.__dict__.update(o['__DiamondHitList__'])
        return a
    elif '__DiamondHit__' in o:
        a = DiamondHit()
        a.__dict__.update(o['__DiamondHit__'])
        return a
    elif '__Contig__' in o:
        a = Contig()
        a.__dict__.update(o['__Contig__'])
        return a
    elif '__Gene__' in o:
        a = Gene()
        a.__dict__.update(o['__Gene__'])
        return a
    elif '__GeneAssembly__' in o:
        a = GeneAssembly()
        a.__dict__.update(o['__GeneAssembly__'])
        return a
    return o

def import_annotated_reads(infile):
    deserialized = None
    with open (infile, 'r') as f:
        deserialized = json.load(f, object_hook=decode_object)
        f.closed
    return deserialized

def import_gene_assembly(infile):
    deserialized = None
    with open (infile, 'r') as f:
        deserialized = json.load(f, object_hook=decode_assembly)
        f.closed
    return deserialized

def export_annotated_reads(parser):
    outfile = os.path.join(parser.project.get_project_dir(parser.sample), parser.sample + '_' + parser.end + '_' + parser.project.get_reads_json_name())
    #print pretty JSON: print(json.dumps(parser.reads,indent=4, cls=CustomEncoder))
    with open (outfile, 'w') as of:
        json.dump(parser.reads,of,cls=CustomEncoder)
        of.closed

def export_gene_assembly(assembly,outfile):
    #print pretty JSON: print(json.dumps(assembly,indent=4, cls=CustomEncoder))
    with open (outfile, 'w') as of:
        json.dump(assembly,of,indent=4,cls=CustomEncoder)
        of.closed

class CustomEncoder(json.JSONEncoder):

     def default(self, o):

         return {'__{}__'.format(o.__class__.__name__): o.__dict__}

