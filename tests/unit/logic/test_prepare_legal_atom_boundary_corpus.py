"""Integrity/coverage tests; fresh fixtures are authored locally before fitting."""
from copy import deepcopy
from pathlib import Path
import json
import re
import subprocess
import sys
import pytest
from scripts.ops.legal_ir import prepare_legal_atom_boundary_corpus as c

@pytest.fixture(scope='module')
def panels():return c.make_panels()

@pytest.fixture(scope='module')
def materialized(tmp_path_factory):
    path=tmp_path_factory.mktemp('atom')/'corpus'
    pin=c.freeze(path)
    return path,pin,c.read_ref(pin)


def test_exact_factor_inventory_and_realized_headers(panels):
    pp,_,ledger,counts=panels
    for panel,n in c.COUNTS.items():
        assert len(pp[panel])==counts[panel]['documents']==n
        labels=[a for a in ledger['document_rows'] if a['panel']==panel]
        assert len(labels)==n
        for key,values in [('first_modality','OPF'),('front_class',c.FRONT_CLASSES),('preceding_time_kind',c.TIME_KINDS),('clause_count',(2,3))]:
            assert counts[panel]['factor_counts'][key]=={str(v):n//len(values) for v in values}
        assert {h:sum(h in r['source_text'] for r in pp[panel]) for h in c.HEADINGS}==dict.fromkeys(c.HEADINGS,n//2)
        assert all(len(c.boundary.tokenize(r['source_text']))<=512 for r in pp[panel])


def test_train_rotation_preserves_exact_bodies_and_meanings(panels):
    pp,pairs,_,_=panels;c.validate_training_pairs(pp['train'],pairs['train'])
    lookup={r['candidate_id']:r for r in pp['train']}
    for p in pairs['train']:
        assert set(p)==c.TRAIN_PAIR_KEYS
        left,right=(lookup[p[k]] for k in ('forward_id','rotated_id'))
        assert [x['rule'] for x in right['clauses']]==[x['rule'] for x in left['clauses']][-1:]+[x['rule'] for x in left['clauses']][:-1]


def test_eval_independent_nested_exact_local_body_pairs(panels):
    pp,pairs,_,_=panels
    for panel in ('tuning','fresh'):
        c.previous.validate_pairs(pp[panel],pairs[panel],c.COUNTS[panel]//2)
        assert all(r['clauses']==[] for r in pp[panel] if not r['supported'])


def test_role_order_is_structural_and_not_entity_identity(panels):
    _,_,ledger,_=panels
    realized={p:set() for p in c.COUNTS}
    for a in ledger['document_rows']:
        child=a['local_clause_coordinates'][a['body_order'].index(1)];spans=child['facet_spans'];note=child['editorial_context'][0]
        positions={'time':spans['temporal'][0],'heading':note['start_char'],
            'qualifiers':min(spans[k][0] for k in ('conditions','exceptions') if spans[k]),'actor':spans['actor'][0]}
        realized[a['panel']].add('_'.join(sorted(positions,key=positions.get)))
    assert realized=={p:{s} for p,s in c.STRUCTURES.items()}


def test_every_exact_coordinate_and_all_cues(panels):
    pp,_,ledger,_=panels;lookup={r['candidate_id']:r for rows in pp.values() for r in rows}
    for a in ledger['document_rows']:c.validate_document(lookup[a['candidate_id']],a)
    texts='\n'.join(r['source_text'] for r in pp['train'])
    assert all(cue in texts for cue in ('If ','When ','In cases where ','Unless ','Except when ','Except where ','Dept.'))


def test_opaque_sources_no_class_or_case_metadata(panels):
    pp,_,_,_=panels
    for rows in pp.values():
        for row in rows:
            source=c.source_row(row)
            assert set(source)=={'candidate_id','source_text','source_sha256'}
            assert re.fullmatch(r'scope-[a-f0-9]{64}',source['candidate_id'])
            assert source['candidate_id']=='scope-'+c.sha(source['source_text'].encode())


def test_all_split_sources_and_meanings_disjoint(panels):
    pp,_,ledger,_=panels
    textsets=[{c.temporal.prior.normalized_source(r['source_text']) for r in pp[p]} for p in c.COUNTS]
    meanings=[{c.boundary.digest(o['rule']) for a in ledger['document_rows'] if a['panel']==p for o in a['local_clause_coordinates']} for p in c.COUNTS]
    assert all(not a&b for data in (textsets,meanings) for i,a in enumerate(data) for b in data[i+1:])


def test_atom_indices_independently_match_all_tokens(panels):
    pp,_,ledger,_=panels;roles=c.training_atom_roles(pp['train'],ledger)
    lookup={r['candidate_id']:r for r in pp['train']}
    for record in roles:
        row=lookup[record['candidate_id']];tokens=c.boundary.tokenize(row['source_text'])
        ends={x['char_end'] for x in row['clauses']}
        assert set(record)==c.ATOM_ROLE_KEYS
        assert record['inter_clause_end_token_indices']==[i for i,t in enumerate(tokens) if t['char_end'] in ends-{max(ends)}]
        expected=[i for i,t in enumerate(tokens) if t['char_end'] not in ends and any(s['char_start']<=t['char_start']<t['char_end']<=s['char_end'] for s in record['atom_spans'])]
        assert record['atom_interior_negative_token_indices']==expected
        assert any(tokens[i]['text'].isalnum() for i in expected)
        assert not set(expected)&set(record['inter_clause_end_token_indices'])


def test_new_temporal_actor_and_exception_negative_coverage(panels):
    pp,_,ledger,_=panels
    records=c.training_atom_roles(pp['train'],ledger)
    counts=c.atom_role_counts(records)
    assert counts=={'documents':144,'inter_clause_end_tokens':216,'atom_interior_negative_tokens':4038,
        'span_counts':{'actor':360,'exceptions':240,'temporal':318}}
    assert all(r['inter_clause_end_token_indices'] and r['atom_interior_negative_token_indices'] for r in records)


def test_unsupported_supervision_rejected(panels):
    pp,_,_,_=panels
    row=next(r for r in pp['tuning'] if not r['supported'])
    with pytest.raises(ValueError,match='unsupported'):c.training_atom_roles([row])


def test_repeated_occurrences_preserved_not_deduplicated(panels):
    pp,_,ledger,_=panels
    repeated=[r for r in pp['train'] if r['repeated_rule_occurrences']]
    assert repeated
    for row,roles in zip(repeated,c.training_atom_roles(repeated,ledger),strict=True):
        assert sum(s['kind']=='actor' for s in roles['atom_spans'])==3
        assert len(roles['inter_clause_end_token_indices'])==2


@pytest.mark.parametrize('mutation',('body_hash','rotation','same_id','rule'))
def test_training_pair_tampering_fails(panels,mutation):
    pp,pairs,_,_=deepcopy(panels);rows=pp['train'];pair=pairs['train'][0]
    if mutation=='body_hash':pair['local_clause_body_sha256'][0]='0'*64
    elif mutation=='rotation':pair['rotated_id']=pairs['train'][1]['rotated_id']
    elif mutation=='same_id':pair['rotated_id']=pair['forward_id']
    else:
        row=next(r for r in rows if r['candidate_id']==pair['rotated_id']);row['clauses'][0]['rule']['modality']='F'
    with pytest.raises(ValueError):c.validate_training_pairs(rows,pairs['train'])


@pytest.mark.parametrize('mutation',('facet','heading','order','time','modality','endpoint'))
def test_source_annotation_tampering_fails(panels,mutation):
    pp,_,ledger,_=deepcopy(panels)
    row=pp['train'][0];a=next(x for x in ledger['document_rows'] if x['candidate_id']==row['candidate_id'])
    if mutation=='facet':a['local_clause_coordinates'][0]['facet_spans']['actor'][1]+=1
    elif mutation=='heading':a['local_clause_coordinates'][a['body_order'].index(1)]['editorial_context'][0]['end_char']+=1
    elif mutation=='order':a['factors']['child_structure']=c.STRUCTURES['fresh']
    elif mutation=='time':a['factors']['preceding_time_kind']='none' if a['factors']['preceding_time_kind']!='none' else 'days'
    elif mutation=='modality':a['factors']['first_modality']='P' if a['factors']['first_modality']!='P' else 'O'
    else:row['clauses'][0]['char_end']-=1
    with pytest.raises(ValueError):c.validate_document(row,a)


def test_ambiguous_atom_occurrence_fails(panels):
    pp,_,_,_=deepcopy(panels);row=pp['train'][0];clause=row['clauses'][0]
    # A canonical atom matching repeated common words is not uniquely grounded.
    clause['rule']['actor']='the'
    with pytest.raises(ValueError,match='uniquely'):c.training_atom_roles([row])


def test_overlapping_canonical_atom_roles_fail(panels):
    pp,_,_,_=deepcopy(panels);row=pp['train'][0];clause=row['clauses'][0]
    clause['rule']['exceptions']=[clause['rule']['actor']]
    with pytest.raises(ValueError,match='overlap'):c.training_atom_roles([row])


def test_real_historical_mask_coverage_and_exact_train_preservation(materialized):
    path,_,manifest=materialized;loaded=c.load_training_inputs(path/'manifest.json')
    old=c.heading.load_training_inputs(c.DEFAULT_HEADING)
    assert loaded['replay']==old['replay'] and loaded['new_train']==old['new_train']
    assert loaded['boundary_training'][:720]==old['boundary_training']
    assert loaded['training_token_roles'][:720]==old['training_token_roles']
    assert len(loaded['boundary_training'])==864 and len(loaded['tuning'])==22
    assert sum(map(len,loaded['tuning'].values()))==2448
    assert manifest['training_atom_role_counts']=={'documents':864,'inter_clause_end_tokens':1320,
        'atom_interior_negative_tokens':18284,'span_counts':{'actor':2184,'exceptions':1176,'temporal':1026}}


def test_training_annotation_ledger_contains_no_evaluation_labels(materialized):
    _,_,m=materialized
    ledger=c.read_ref(m['artifacts']['training_annotation_ledger'])
    assert len(ledger['document_rows'])==144 and {r['panel'] for r in ledger['document_rows']}=={'train'}
    evaluation=c.read_ref(m['artifacts']['annotation_ledger'])
    assert len(evaluation['document_rows'])==288 and {r['panel'] for r in evaluation['document_rows']}=={'tuning','fresh'}


def test_actual_exposure_audit_has_zero_full_layout_matches(materialized):
    _,_,m=materialized;e=c.read_ref(m['artifacts']['exposure_audit'])
    assert len(e['rows'])==192 and all(not r['matching_pools'] for r in e['rows'])
    assert e['new_source_overlap_count']==0 and e['real_exposed_views']==86
    assert {'new_train','new_tuning','prior_heading_fresh','prior_heading_tuning'}<=set(e['known_role_masked_layouts'])


def test_source_only_loader_zero_reads_of_all_four_sealed_files(materialized):
    path,_,m=materialized
    code='''import json,pathlib,sys
from scripts.ops.legal_ir import prepare_legal_atom_boundary_corpus as c
manifest=pathlib.Path(sys.argv[1]);m=json.loads(manifest.read_text())
blocked={str(pathlib.Path(m['artifacts'][k]['path']).resolve()) for k in m['sealed_artifacts']}
attempts=[]
def hook(event,args):
 if event=='open' and isinstance(args[0],(str,bytes)) and str(pathlib.Path(args[0]).resolve()) in blocked:
  attempts.append(str(args[0]));raise RuntimeError('sealed reference opened')
sys.addaudithook(hook)
x=c.load_training_inputs(manifest)
assert len(x['fresh_sources'])==192 and len(x['boundary_training'])==864 and not attempts
print('sealed_open_attempts=0')
'''
    result=subprocess.run([sys.executable,'-c',code,str(path/'manifest.json')],cwd=c.ROOT,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert 'sealed_open_attempts=0' in result.stdout


def test_deterministic_source_order_and_pair_inventory(panels):
    assert c.make_panels()==panels
