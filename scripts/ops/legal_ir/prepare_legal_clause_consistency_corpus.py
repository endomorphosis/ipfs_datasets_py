#!/usr/bin/env python3
"""Freeze semantically identical span pairs and sealed qualifier-combination tests.

This is a controlled synthetic scope profile, not independently adjudicated legal
text. Coordinates are authored separately for each wording, never transferred
from one paraphrase to another.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import prepare_legal_boundary_curriculum as boundary_corpus
previous = boundary_corpus.previous
temporal, mixed, prior, documents = previous.temporal, previous.mixed, previous.prior, previous.documents
FIELDS, require = previous.FIELDS, previous.require
sha, file_ref, read_ref, verify_ref, write_new = previous.sha, previous.file_ref, previous.read_ref, previous.verify_ref, previous.write_new
SCHEMA = 'legal-clause-consistency-corpus/v1'
DEFAULT_BOUNDARY = prior.ARTIFACTS / 'legal-decoder-boundary-curriculum-20261002/corpus-01/manifest.json'
PREFIXES = {'train':'Coralspire', 'tuning':'Dawnspire', 'fresh':'Moonspire', 'document':'Fernspire'}
FAMILIES = ('where_front_save_where_suffix', 'except_where_front_where_suffix',
            'in_cases_where_suffix_except_where_suffix', 'in_cases_where_front_except_cases_postmodal')
TRAIN_VARIANTS = previous.FAMILIES
GRAY = (0, 1, 3, 2, 6, 7, 5, 4)
SOURCE_KEYS = previous.SOURCE_KEYS
SEALED = ('challenge_targets', 'document_challenge_targets', 'annotation_ledger', 'exposure_audit')
CUES = ('where', 'save where', 'except where', 'in cases where', 'except in cases where')


def values(panel, index, clause=0):
    require(panel in PREFIXES, 'unknown consistency panel')
    base = index // 2 if panel in ('train','tuning') else index
    name = f'{PREFIXES[panel]}{base:03d}x{clause}'
    modality = ('O','P','F')[(base + clause) % 3]
    if panel in ('train','tuning'):
        position = (base // 3) % 8
        mask = GRAY[(position + index % 2) % 8]
    else:
        mask = (3, 5, 6)[(index // 3 + clause) % 3]
    return {'actor': ('{name} Records Office','{name} Dept. of Records','{name} Registry','{name} Public Register Authority')[(base//3+clause)%4].format(name=name),
        'action': ('retain','inspect','archive','publish','review','submit')[(base//4+clause)%6],
        'object': f'the {name.lower()} register', 'conditions': f'the {name.lower()} permit is active',
        'exceptions': f'the {name.lower()} exemption is active', 'temporal': f'within {19+(base*23+clause*17)%467} days',
        'citation': f'section {11801+base}.{clause+2}', 'modality':modality, 'trigger':previous.MODALS[modality],
        'present':{f for bit,f in enumerate(FIELDS[3:]) if mask & (1<<bit)}, 'base':base}


def render(panel, index, variant, clause=0):
    require(variant in ('anchor','alternative') + FAMILIES, 'unknown consistency rendering')
    v=values(panel,index,clause); present=v['present']; w=prior.CoordinateWriter(); placed=set()
    def field(name): w.add(v[name],name)
    def q(name,cue,suffix=''):
        w.add(cue);field(name);w.add(suffix);placed.add(name)
    actual_variant=variant
    if variant=='anchor': w.add(f"Under {v['citation']}, ")
    elif variant=='alternative':
        actual_variant=TRAIN_VARIANTS[(v['base']//6)%len(TRAIN_VARIANTS)]
        # Lexical cues are individually admitted in single-qualifier training;
        # their two-qualifier combinations are reserved for the fresh panels.
        if present=={'conditions'}:
            actual_variant=('single_where_front','single_where_suffix','single_in_cases_front','single_in_cases_suffix')[(v['base']//24+index%2)%4]
        elif present=={'exceptions'}:
            actual_variant=('single_save_where_suffix','single_except_where_front','single_except_where_suffix','single_except_cases_postmodal')[(v['base']//24+index%2)%4]
    if variant in FAMILIES:
        if variant==FAMILIES[0] and 'conditions' in present: q('conditions','Where ', ', ')
        if variant==FAMILIES[1] and 'exceptions' in present: q('exceptions','Except where ', ', ')
        if variant==FAMILIES[3] and 'conditions' in present: q('conditions','In cases where ', ', ')
    else:
        if actual_variant in ('when_condition_front','single_where_front','single_in_cases_front') and 'conditions' in present:
            q('conditions',{'when_condition_front':'When ','single_where_front':'Where ','single_in_cases_front':'In cases where '}[actual_variant],', ')
        if actual_variant in ('except_when_front','single_except_where_front') and 'exceptions' in present:
            q('exceptions','Except when ' if actual_variant=='except_when_front' else 'Except where ', ', ')
    field('actor');w.add(' ');field('trigger')
    if variant==FAMILIES[3] and 'exceptions' in present: q('exceptions',', except in cases where ', ',')
    elif actual_variant=='single_except_cases_postmodal': q('exceptions',', except in cases where ', ',')
    else:
        inserted={'postmodal_condition':'conditions','postmodal_exception':'exceptions','postmodal_temporal':'temporal'}.get(actual_variant)
        if inserted in present: q(inserted,{'conditions':', if ','exceptions':', unless ','temporal':', '}[inserted],',')
    w.add(' ');field('action');w.add(' ');field('object')
    if 'temporal' in present and 'temporal' not in placed: q('temporal',' ')
    if 'conditions' in present and 'conditions' not in placed:
        cue={FAMILIES[1]:' where ',FAMILIES[2]:' in cases where ','single_where_suffix':' where ',
            'single_in_cases_suffix':' in cases where ','on_condition_that_suffix':' on condition that '}.get(actual_variant,' if ')
        q('conditions',cue)
    if 'exceptions' in present and 'exceptions' not in placed:
        cue={FAMILIES[0]:' save where ',FAMILIES[2]:' except where ',
            'single_save_where_suffix':' save where ','single_except_where_suffix':' except where '}.get(actual_variant,' unless ')
        q('exceptions',cue)
    w.add('.')
    rule={'modality':v['modality'],**{f:v[f] for f in FIELDS[:3]},**{f:[v[f]] if f in present else [] for f in FIELDS[3:]}}
    row=mixed.validate_row({'id':f'consistency-{panel}-'+sha(w.text.encode())[:20], 'source_text':w.text,
        'canonical_ir':{'rules':[rule]}, 'facet_spans':{f:w.spans.get(f) for f in FIELDS},
        'trigger_span':w.spans['trigger'],'domain':'new','trigger_supervised':True})
    annotation={'id':row['id'],'source_sha256':sha(w.text.encode()),'panel':panel,
        'case_group':f'consistency-{panel}-case-{v["base"]:03d}', 'meaning_group':f'consistency-{panel}-meaning-{index:03d}',
        'family':actual_variant,'facet_spans':row['facet_spans'],'trigger_span':row['trigger_span']}
    return row,annotation


def make_pairs(panel,count):
    rows,pairs,ledger=[],[],[]
    for index in range(count):
        left,la=render(panel,index,'anchor');right,ra=render(panel,index,'alternative')
        require(left['canonical_ir']==right['canonical_ir'] and left['source_text']!=right['source_text'],'pair requires identical meaning and different surface')
        rows.extend((left,right));ledger.extend((la,ra))
        pairs.append({'pair_id':f'consistency-{panel}-pair-{index:03d}','case_group':la['case_group'],
            'left_id':left['id'],'right_id':right['id'],'canonical_ir_sha256':sha(prior.canonical_bytes(left['canonical_ir']))})
    return rows,pairs,ledger


def authored_document(ordinal):
    require(0<=ordinal<96,'bounded document ordinal required')
    supported=ordinal<72;family=FAMILIES[ordinal%4];count=1+(ordinal//4)%4 if supported else 2
    rendered=[render('document',ordinal,family,clause)[0] for clause in range(count)]
    repeated=supported and count>=3 and (ordinal//16)%2==0
    if repeated:rendered[2]=deepcopy(rendered[0])
    clauses,coordinates,chunks,cursor=[],[],[],0
    for i,row in enumerate(rendered):
        text=row['source_text']
        if i<count-1 and ordinal%3==0:text=text[:-1]+';'
        gap=('\n' if ordinal%2==0 else ' ') if i else '';cursor+=len(gap);chunks.append(gap+text)
        clauses.append({'char_start':cursor,'char_end':cursor+len(text),'rule':row['canonical_ir']['rules'][0]})
        coordinates.append({'clause_index':i,'char_start':cursor,'char_end':cursor+len(text),'family':family,
            'facet_spans':{f:[x+cursor for x in span] if span else None for f,span in row['facet_spans'].items()},
            'trigger_span':[x+cursor for x in row['trigger_span']]})
        cursor+=len(text)
    text,reason=''.join(chunks),None
    if not supported:
        reason=boundary_corpus.GUARDS[(ordinal-72)%4];first,second=[r['source_text'] for r in rendered]
        if reason=='shared_condition_prefix':text='Both following rules share the same condition: '+first+' '+second
        elif reason=='coordinated_action':text=first[:-1]+' and publish the retained archive.'
        elif reason=='exclusive_alternative':text='Either '+first[:-1]+' or '+second
        else:text=first[:-1]+' unless '+second
        clauses,coordinates,repeated=[],[],False
    row={'candidate_id':f'consistency-document-{ordinal:03d}','source_text':text,'source_sha256':sha(text.encode()),
        'supported':supported,'construction':family if supported else 'unsupported/'+reason,'repeated_rule_occurrences':repeated,
        'clauses':clauses,'unsupported_reason':reason,'label_origin':'new_authored_restricted_flat_profile_not_legal_authority'}
    annotation={'candidate_id':row['candidate_id'],'source_sha256':row['source_sha256'],'panel':'document',
        'case_group':f'consistency-document-case-{ordinal:03d}','family':family,'supported':supported,'guard':reason,'clause_coordinates':coordinates}
    boundary_corpus.validate_document(row,annotation)
    return row,annotation


def make_panels():
    train,train_pairs,train_ledger=make_pairs('train',192)
    tuning,tuning_pairs,tuning_ledger=make_pairs('tuning',48)
    fresh,fresh_ledger=[],[]
    for case in range(36):
        for family in FAMILIES:
            row,a=render('fresh',case,family);fresh.append(row);fresh_ledger.append(a)
    docs,doc_ledger=[],[]
    for ordinal in range(96):
        row,a=authored_document(ordinal);docs.append(row);doc_ledger.append(a)
    panels={'train':train,'tuning':tuning,'fresh':fresh,'document':docs}
    ledger={'schema':'legal-clause-consistency-annotations/v1','single_rows':train_ledger+tuning_ledger+fresh_ledger,'document_rows':doc_ledger}
    pair_map={'train':train_pairs,'tuning':tuning_pairs}
    validate_panels(panels,pair_map,ledger)
    return panels,pair_map,ledger


def validate_pairs(rows,pairs,expected_pairs):
    require(len(rows)==2*expected_pairs and len(pairs)==expected_pairs,'pair denominator differs')
    by_id={r['id']:r for r in rows};require(len(by_id)==len(rows),'pair source IDs duplicate')
    used=[]
    for pair in pairs:
        require(set(pair)=={'pair_id','case_group','left_id','right_id','canonical_ir_sha256'},'closed pair metadata required')
        left,right=by_id[pair['left_id']],by_id[pair['right_id']]
        require(left['canonical_ir']==right['canonical_ir'],'paired canonical atoms differ')
        require(pair['canonical_ir_sha256']==sha(prior.canonical_bytes(left['canonical_ir'])),'pair canonical commitment differs')
        require(left['source_text']!=right['source_text'],'pair surface strings must differ')
        used.extend((left['id'],right['id']))
    require(len(set(used))==len(rows) and set(used)==set(by_id),'each row belongs to exactly one pair')
    require(len({p['pair_id'] for p in pairs})==len(pairs),'pair identifiers duplicate')


def validate_panels(panels,pairs,ledger):
    require({k:len(v) for k,v in panels.items()}=={'train':384,'tuning':96,'fresh':144,'document':96},'panel counts differ')
    validate_pairs(panels['train'],pairs['train'],192);validate_pairs(panels['tuning'],pairs['tuning'],48)
    annotations={a['id']:a for a in ledger['single_rows']};require(len(annotations)==624,'single annotation inventory differs')
    all_sources=set();groups={}
    for panel in ('train','tuning','fresh'):
        rows=panels[panel];groups[panel]=set()
        for row in rows:
            mixed.validate_row(row);a=annotations[row['id']]
            require(a['source_sha256']==sha(row['source_text'].encode()) and a['panel']==panel and a['facet_spans']==row['facet_spans'] and a['trigger_span']==row['trigger_span'],'single annotation binding differs')
            normalized=prior.normalized_source(row['source_text']);require(normalized not in all_sources,'source strings duplicate across panels')
            all_sources.add(normalized);groups[panel].add(a['case_group'])
        rules=[r['canonical_ir']['rules'][0] for r in rows]
        require(len(set(Counter(r['modality'] for r in rules).values()))==1,'modal balance differs')
        for f in FIELDS[3:]:
            present=sum(bool(r[f]) for r in rules)
            require(present==(len(rules)//2 if panel!='fresh' else 96),'qualifier presence/absence balance differs')
    for panel in ('train','tuning'):
        rows={r['id']:r for r in panels[panel]}
        for first,second in zip(pairs[panel][::2],pairs[panel][1::2]):
            left,right=rows[first['left_id']]['canonical_ir']['rules'][0],rows[second['left_id']]['canonical_ir']['rules'][0]
            changed=[f for f in left if left[f]!=right[f]]
            require(first['case_group']==second['case_group'] and len(changed)==1 and changed[0] in FIELDS[3:], 'adjacent contrast must change one optional qualifier only')
    fresh_groups={}
    for row in panels['fresh']:fresh_groups.setdefault(annotations[row['id']]['case_group'],[]).append(row)
    require(len(fresh_groups)==36,'fresh independent case denominator differs')
    for rows in fresh_groups.values():
        require(len(rows)==4 and all(r['canonical_ir']==rows[0]['canonical_ir'] for r in rows),'fresh paraphrase meanings differ')
        require({annotations[r['id']]['family'] for r in rows}==set(FAMILIES),'fresh four-family coverage differs')
    groups['document']=set()
    require(Counter(r['supported'] for r in panels['document'])=={True:72,False:24},'document support balance differs')
    doc_annotations={a['candidate_id']:a for a in ledger['document_rows']};require(len(doc_annotations)==96,'document annotation coverage differs')
    for row in panels['document']:
        a=doc_annotations[row['candidate_id']];boundary_corpus.validate_document(row,a);groups['document'].add(a['case_group'])
        normalized=prior.normalized_source(row['source_text']);require(normalized not in all_sources,'document source duplicates another panel');all_sources.add(normalized)
    for i,left in enumerate(groups):
        for right in list(groups)[i+1:]:require(not groups[left]&groups[right],'case groups cross panels')


def historical_inputs(boundary_manifest_path):
    bm=json.loads(Path(boundary_manifest_path).read_bytes());require(bm['schema']==boundary_corpus.SCHEMA,'pinned boundary corpus required')
    pm,known,excluded=boundary_corpus.load_prior_pools(bm['inputs']['previous_corpus']['path'])
    pool_refs=boundary_corpus.known_pool_references(pm)
    for panel,key in (('train','new_training_targets'),('tuning','tuning_targets'),('fresh','fresh_targets')):
        rows=read_ref(bm['artifacts'][key]);excluded.update(r['source_text'] for r in rows)
        name='exposed_recent_boundary_'+panel+'_clauses';known[name]=previous.document_clauses_for_audit(rows)
        pool_refs[name]={'reference':bm['artifacts'][key],'representation':'document_clauses'}
        excluded.update(r['source_text'] for r in known[name])
    inherited=temporal.load_training_inputs(pm['inputs']['temporal_corpus']['path'])
    return bm,pm,inherited,known,excluded,pool_refs


def freeze(output,boundary_manifest_path=DEFAULT_BOUNDARY):
    output=Path(output).resolve();require(not output.exists(),'output already exists')
    bm,pm,inherited,known,excluded,pool_refs=historical_inputs(boundary_manifest_path)
    panels,pairs,ledger=make_panels()
    normalized_excluded={prior.normalized_source(s) for s in excluded}
    for panel,rows in panels.items():
        for row in rows:
            require(prior.normalized_source(row['source_text']) not in normalized_excluded,'new source repeats prior admitted/exposed source')
            if panel=='document':
                for clause in row['clauses']:
                    require(prior.normalized_source(row['source_text'][clause['char_start']:clause['char_end']]) not in normalized_excluded,'new clause repeats prior admitted/exposed source')
    known['new_consistency_train']=panels['train'];known['new_consistency_tuning']=panels['tuning']
    layouts={name:{previous.generic_layout(r) for r in rows} for name,rows in known.items()}
    annotations={a['id']:a for a in ledger['single_rows']};single_evidence=[];document_evidence=[]
    for panel,rows in (('single',panels['fresh']),('document',previous.document_clauses_for_audit(panels['document']))):
        for row in rows:
            layout=previous.generic_layout(row);matches=sorted(n for n,shapes in layouts.items() if layout in shapes)
            require(not matches,'fresh construction overlaps known local layout: '+layout)
            item={'id':row['id'],'source_sha256':sha(row['source_text'].encode()),'role_masked_layout':layout,'matching_pools':matches}
            if panel=='single':item.update(case_group=annotations[row['id']]['case_group'],family=annotations[row['id']]['family'])
            (single_evidence if panel=='single' else document_evidence).append(item)
    cue_families={'where':('single_where_front','single_where_suffix'), 'save where':('single_save_where_suffix',),
        'except where':('single_except_where_front','single_except_where_suffix'), 'in cases where':('single_in_cases_front','single_in_cases_suffix'),
        'except in cases where':('single_except_cases_postmodal',)}
    cue_evidence={cue:[r['id'] for r in panels['train'] if annotations[r['id']]['family'] in cue_families[cue]
        and sum(bool(r['canonical_ir']['rules'][0][f]) for f in FIELDS[3:])==1] for cue in CUES}
    require(all(cue_evidence.values()),'every fresh lexical cue needs training-only single-qualifier exposure')
    output.mkdir(parents=True,exist_ok=False)
    artifacts={'new_training':write_new(output/'new-training.json',panels['train']),
        'training_pairs':write_new(output/'training-pairs.json',pairs['train']),
        'new_tuning':write_new(output/'new-tuning.json',panels['tuning']),
        'tuning_pairs':write_new(output/'tuning-pairs.json',pairs['tuning']),
        'challenge_sources':write_new(output/'challenge-sources.json',[{k:r[k] for k in ('id','source_text')} for r in panels['fresh']]),
        'challenge_targets':write_new(output/'challenge-targets.sealed.json',panels['fresh']),
        'document_challenge_sources':write_new(output/'document-challenge-sources.json',[previous.document_source(r) for r in panels['document']]),
        'document_challenge_targets':write_new(output/'document-challenge-targets.sealed.json',panels['document']),
        'annotation_ledger':write_new(output/'annotations.sealed.json',ledger)}
    pool_refs['new_consistency_train']={'reference':artifacts['new_training'],'representation':'annotated_single'}
    pool_refs['new_consistency_tuning']={'reference':artifacts['new_tuning'],'representation':'annotated_single'}
    require(set(pool_refs)==set(known),'known pool provenance inventory differs')
    exposure={'schema':'legal-clause-consistency-exposure/v1','single_rows':single_evidence,'document_clause_rows':document_evidence,
        'known_pool_references':pool_refs,'known_role_masked_layouts':{n:sorted(v) for n,v in layouts.items()},
        'known_pool_counts':{n:len(v) for n,v in known.items()},'lexical_cue_training_rows':cue_evidence,
        'fresh_single_layout_matches':0,'fresh_document_clause_layout_matches':0,
        'claim':'Four authored combinations/orderings of individually trained lexical cues versus pinned local exposed/admitted layouts. Not universal language-model pretraining novelty.',
        'guard_wrapper_novelty_claimed':False}
    artifacts['exposure_audit']=write_new(output/'exposure-audit.sealed.json',exposure)
    tm=inherited['manifest']
    manifest={'schema':SCHEMA,'generator':file_ref(__file__),
        'dependencies':{n:file_ref(m.__file__) for n,m in (('boundary_corpus',boundary_corpus),('previous',previous),('temporal',temporal),('mixed',mixed),('coordinates',prior),('documents',documents),('boundary',documents.boundary),('composition',documents.compose))},
        'artifacts':artifacts,'inputs':{'boundary_corpus':file_ref(boundary_manifest_path),'temporal_corpus':pm['inputs']['temporal_corpus']},
        'replay_inputs':{'baseline':tm['artifacts']['training_baseline'],'temporal':tm['artifacts']['temporal_training']},
        'tuning_inputs':{name:tm['artifacts']['tuning_'+name] for name in ('earlier','prior_new','temporal')},
        'counts':{'new_training':384,'training_meaning_pairs':192,'training_case_groups':96,'new_tuning':96,'tuning_meaning_pairs':48,'tuning_case_groups':24,
            'fresh':144,'fresh_case_groups':36,'fresh_variants_per_case':4,'document_fresh':96,'document_supported':72,'document_guards':24,
            'document_supported_clause_occurrences':len(document_evidence),'replay_earlier':1152,'replay_prior_new':600,'replay_temporal':600},
        'frozen_before_training':True,'training_performed':False,'qualified':False,'sealed_during_training':list(SEALED),
        'fresh_families':list(FAMILIES),'new_lexical_cues':list(CUES),'lexical_cues_individually_exposed_in_training':True,
        'source_overlap_audit':{'unique_prior_excluded_texts':len(excluded),'normalized_source_or_clause_overlaps':0},
        'construction_exposure_summary':{'fresh_single_layout_matches':0,'fresh_document_clause_layout_matches':0,'known_pool_counts':exposure['known_pool_counts'],'scope':exposure['claim']},
        'semantics':{'pairing':'Within each pair, modality and all canonical atom values are identical. Span coordinates are authored independently for the two different sources. Contrastive neighboring meaning groups are never paired.',
            'applicability':'Where C and in cases where C denote the same opaque externally valued applicability condition as if C, without calendar/event inference.',
            'exception':'Save where E, except where E and except in cases where E denote the same opaque rule-level exception as unless E in this controlled authored profile.',
            'temporal':'within N days remains the action-time facet under the inherited O/P/F activation-anchor convention.',
            'citation':'Under section N.M is contextual citation metadata and is excluded from canonical atoms.',
            'absence':'Training/tuning have all8 optional-facet presence masks equally often. Fresh has exactly2 of C/E/T; each facet absent in12 of36 cases and present in24.'},
        'limitations':['Controlled authored synthetic profile, not independent legal gold.','Fresh holdout concerns cue combinations and order; individual lexical cues are taught.',
            'Paraphrases and contrastive neighbors share case identities within a split; group-level uncertainty is required.','Guard wrapper classes intentionally recur.',
            'No optimizer execution or dimension-specific latent provenance is established by this generator.']}
    return write_new(output/'manifest.json',manifest)


def load_training_inputs(manifest_path):
    """Load admitted supervision and source-only fresh input, never sealed bytes."""
    manifest=json.loads(Path(manifest_path).read_bytes())
    require(manifest.get('schema')==SCHEMA and manifest.get('frozen_before_training') is True,'frozen consistency corpus required')
    verify_ref(manifest['generator'])
    for reference in manifest['dependencies'].values():verify_ref(reference)
    a=manifest['artifacts'];train=read_ref(a['new_training']);pairs=read_ref(a['training_pairs']);tune=read_ref(a['new_tuning']);tp=read_ref(a['tuning_pairs'])
    validate_pairs(train,pairs,192);validate_pairs(tune,tp,48)
    for row in train+tune:mixed.validate_row(row)
    baseline=read_ref(manifest['replay_inputs']['baseline']);temporal_rows=read_ref(manifest['replay_inputs']['temporal'])
    replay={'earlier':[r for r in baseline if r['domain']=='earlier'],'prior_new':[r for r in baseline if r['domain']=='new'],'temporal':temporal_rows}
    require({k:len(v) for k,v in replay.items()}=={'earlier':1152,'prior_new':600,'temporal':600},'replay inventory differs')
    tuning={k:read_ref(r) for k,r in manifest['tuning_inputs'].items()}
    require({k:len(v) for k,v in tuning.items()}=={'earlier':96,'prior_new':96,'temporal':120},'historical tuning inventory differs')
    fresh=read_ref(a['challenge_sources']);docs=read_ref(a['document_challenge_sources'])
    require(len(fresh)==144 and len(docs)==96,'fresh source denominator differs')
    require(all(set(r)=={'id','source_text'} for r in fresh),'closed fresh single sources required')
    require(all(set(r)==SOURCE_KEYS and r['source_sha256']==sha(r['source_text'].encode()) for r in docs),'closed source-only document schema/hash required')
    rows=train+tune+fresh+docs+[r for values in replay.values() for r in values]+[r for values in tuning.values() for r in values]
    require(len({prior.normalized_source(r['source_text']) for r in rows})==len(rows),'admitted source panels overlap')
    return {'manifest':manifest,'new_train':train,'training_pairs':pairs,'new_tuning':tune,'tuning_pairs':tp,
        'replay':replay,'tuning':tuning,'fresh_sources':fresh,'fresh_document_sources':docs}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--boundary-manifest',type=Path,default=DEFAULT_BOUNDARY);args=parser.parse_args()
    print(json.dumps(freeze(args.output,args.boundary_manifest),sort_keys=True))

if __name__=='__main__':main()
