#!/usr/bin/env python3
"""Pin five manually queried, full-paragraph local US Code diagnostics.

No owner references or expected labels are supplied. Context remains available
by immutable document/version references but is not silently fed to the model.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ipfs_datasets_py.logic.autoformal import legal_temporal_ownership_metrics as metrics

MANIFEST_SHA = '6d22979d7ec8162b19625aca411e3fa94bb2be2b20be6d113ff9f1ae9d3f6bdd'
SPEC = (
    ('usc:us:10:4873', 9, 'Not later than 10 days after the Secretary provides a waiver under paragraph (1)'),
    ('usc:us:10:4873', 38, 'after an opportunity for notice and comment that is not less than 12 months'),
    ('usc:us:10:4873', 40, 'after the issuance of a final rule implementing this section'),
    ('usc:us:18:3284', 0, 'until the debtor shall have been finally discharged or a discharge denied'),
    ('usc:us:18:3284', 0, 'until such final discharge or denial of discharge'),
)
require = metrics.require


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def ref(path):
    p=Path(path).resolve(); b=p.read_bytes()
    return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}


def extract(document, paragraph_index, literal):
    require(sha(document['document_text'])==document['document_text_sha256'], 'document text hash mismatch')
    paragraphs=[p for p in document['paragraphs'] if p['paragraph_index']==paragraph_index]
    require(len(paragraphs)==1, 'exact paragraph required')
    p=paragraphs[0]; text=p['text']
    require(p['kind']=='codified_body' and sha(text)==p['text_sha256'] and
            document['document_text'][p['char_start']:p['char_end']]==text, 'complete codified paragraph mismatch')
    require(type(literal) is str and literal and text.count(literal)==1, 'one exact manually supplied time occurrence required')
    a=text.index(literal); end=a+len(literal)
    count=len(re.findall(r'\w+|[^\w\s]', text, re.UNICODE))
    value={'id':'local-uscode-time-'+sha(document['document_id']+':'+str(paragraph_index)+':'+str(a)+':'+str(end)),
           'source_text':text,'source_sha256':sha(text),'proposed_time_span':{'char_start':a,'char_end':end}}
    supported=count<=256 and len(text.encode())<=40000
    if supported: metrics.validate_source(value)
    provenance={k:document[k] for k in ('document_id','html_sha256','document_text_sha256','legal_id','edition','source_url')}
    provenance.update({'id':value['id'],'paragraph_index':paragraph_index,'subsection_path':p['subsection_path'],
        'paragraph_document_span':{'char_start':p['char_start'],'char_end':p['char_end']},
        'time_document_span':{'char_start':p['char_start']+a,'char_end':p['char_start']+end},
        'source_sha256':value['source_sha256'],'source_token_count':count,'manually_supplied_time_query':True,
        'complete_paragraph_used':True,'context_truncated':False,'full_document_supplied_to_model':False,
        'within_model_source_budget':supported,'unsupported_reason':None if supported else 'complete_paragraph_exceeds_model_budget',
        'owner_reference_supplied':False,'independent_gold':False,'source_semantics_verified':False,
        'native_formula_qualification':False,'external_reference_closure_verified':False})
    return value,provenance


def run(manifest_path, output):
    pin=ref(manifest_path);require(pin['sha256']==MANIFEST_SHA,'historical official-context manifest changed')
    m=json.loads(Path(manifest_path).read_text());documents={};refs={}
    for item in m['documents']:
        p=item['document'];require(ref(p['path'])==p,'official context bytes changed')
        d=json.loads(Path(p['path']).read_text());documents[d['legal_id']]=d;refs[d['legal_id']]=p
    queries=[];provenance=[];unsupported=[]
    for legal,index,literal in SPEC:
        q,p=extract(documents[legal],index,literal);p['document_reference']=refs[legal]
        provenance.append(p)
        (queries if p['within_model_source_budget'] else unsupported).append(q)
    require(len({q['id'] for q in queries+unsupported})==5,'five unique manual occurrences required')
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    def write(name,value):
        path=out/name
        with path.open('x') as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n')
        return ref(path)
    sources=write('sources.json',queries)
    sidecar=write('provenance.json',provenance)
    rejected=write('unsupported-sources.json',unsupported)
    return write('manifest.json',{'schema':'legal-owner-pointer-real-source-diagnostics/v1','official_context_manifest':pin,
        'producer':ref(__file__),'sources':sources,'provenance':sidecar,'unsupported_sources':rejected,
        'requested_queries':5,'model_queries':len(queries),'unsupported_queries':len(unsupported),
        'unique_codified_paragraphs':len({(p['document_id'],p['paragraph_index']) for p in provenance}),
        'independent_owner_accuracy_available':False,'manual_time_proposals':True,
        'historically_exposed_source_diagnostics':True,'statutory_semantics_verified':False,'native_formula_qualification':False})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();print(json.dumps(run(args.manifest,args.output)))
