"""Pair semantics, held-out layouts and sealed source-only training IO."""
from collections import Counter
from copy import deepcopy
import builtins
import json
from pathlib import Path
import subprocess
import sys
import pytest
from scripts.ops.legal_ir import prepare_legal_clause_consistency_corpus as c

@pytest.fixture(scope='module')
def panels(): return c.make_panels()

@pytest.fixture(scope='module')
def frozen(tmp_path_factory):
    path=tmp_path_factory.mktemp('clause-consistency')/'corpus'
    c.freeze(path)
    return path/'manifest.json'

def test_complete_pair_case_and_panel_inventory(panels):
    p,pairs,ledger=panels;c.validate_panels(p,pairs,ledger)
    assert {k:len(v) for k,v in p.items()}=={'train':384,'tuning':96,'fresh':144,'document':96}
    assert len({r['case_group'] for r in pairs['train']})==96
    assert len({r['case_group'] for r in pairs['tuning']})==24

@pytest.mark.parametrize('panel,count',[('train',192),('tuning',48)])
def test_every_pair_preserves_all_atoms_with_independent_coordinates(panels,panel,count):
    p,pairs,_=panels;by_id={r['id']:r for r in p[panel]}
    c.validate_pairs(p[panel],pairs[panel],count)
    different_coordinates=0
    for pair in pairs[panel]:
        a,b=by_id[pair['left_id']],by_id[pair['right_id']]
        assert a['canonical_ir']==b['canonical_ir'] and a['source_text']!=b['source_text']
        different_coordinates += a['facet_spans']!=b['facet_spans']
        c.mixed.validate_row(a);c.mixed.validate_row(b)
    assert different_coordinates==count

@pytest.mark.parametrize('panel',['train','tuning'])
def test_presence_masks_modality_and_neighbor_contrasts_are_balanced(panels,panel):
    p,pairs,_=panels;rules=[r['canonical_ir']['rules'][0] for r in p[panel]]
    masks=Counter(tuple(bool(r[f]) for f in c.FIELDS[3:]) for r in rules)
    assert len(masks)==8 and len(set(masks.values()))==1
    assert len(set(Counter(r['modality'] for r in rules).values()))==1
    by_id={r['id']:r for r in p[panel]}
    for a,b in zip(pairs[panel][::2],pairs[panel][1::2]):
        ra,rb=by_id[a['left_id']]['canonical_ir']['rules'][0],by_id[b['left_id']]['canonical_ir']['rules'][0]
        changed=[f for f in ra if ra[f]!=rb[f]]
        assert len(changed)==1 and changed[0] in c.FIELDS[3:]
        assert a['case_group']==b['case_group']

@pytest.mark.parametrize('family',c.FAMILIES)
def test_fresh_forms_preserve_each_meaning_with_absent_facets(family):
    for case in range(36):
        row,a=c.render('fresh',case,family)
        other,_=c.render('fresh',case,c.FAMILIES[0])
        assert row['canonical_ir']==other['canonical_ir']
        assert sum(bool(row['canonical_ir']['rules'][0][f]) for f in c.FIELDS[3:])==2
        assert not c.documents.boundary.UNSUPPORTED.search(row['source_text'])
        c.mixed.validate_row(row)

def test_fresh_case_groups_have_four_distinct_forms(panels):
    p,_,ledger=panels;annotations={a['id']:a for a in ledger['single_rows']}
    groups={}
    for r in p['fresh']:groups.setdefault(annotations[r['id']]['case_group'],[]).append(r)
    assert len(groups)==36
    for rows in groups.values():
        assert len({r['source_text'] for r in rows})==4
        assert len({c.sha(c.prior.canonical_bytes(r['canonical_ir'])) for r in rows})==1

def test_new_lexical_cues_have_individual_training_exposure(frozen):
    m=json.loads(frozen.read_bytes());e=c.read_ref(m['artifacts']['exposure_audit']);rows={r['id']:r for r in c.read_ref(m['artifacts']['new_training'])}
    assert set(e['lexical_cue_training_rows'])==set(c.CUES)
    for cue,ids in e['lexical_cue_training_rows'].items():
        assert ids
        for identity in ids:
            row=rows[identity]
            assert cue in row['source_text'].casefold()
            assert sum(bool(row['canonical_ir']['rules'][0][f]) for f in c.FIELDS[3:])==1

def test_fresh_layouts_absent_from_all_historical_and_current_pools(frozen):
    m=json.loads(frozen.read_bytes());e=c.read_ref(m['artifacts']['exposure_audit'])
    assert len(e['single_rows'])==144 and len(e['document_clause_rows'])==172
    assert all(not r['matching_pools'] for r in e['single_rows']+e['document_clause_rows'])
    assert {'new_consistency_train','new_consistency_tuning','exposed_recent_boundary_fresh_clauses'}<=set(e['known_pool_references'])
    assert set(e['known_pool_references'])==set(e['known_role_masked_layouts'])==set(e['known_pool_counts'])

def test_document_occurrences_and_guards(panels):
    p,_,ledger=panels;by_id={a['candidate_id']:a for a in ledger['document_rows']}
    assert Counter(r['supported'] for r in p['document'])=={True:72,False:24}
    assert Counter(r['unsupported_reason'] for r in p['document'] if not r['supported'])=={g:6 for g in c.boundary_corpus.GUARDS}
    repeated=[r for r in p['document'] if r['repeated_rule_occurrences']];assert repeated
    for row in p['document']:
        c.boundary_corpus.validate_document(row,by_id[row['candidate_id']])
        if not row['supported']:assert row['clauses']==[]
    for row in repeated:
        a,b=row['clauses'][0],row['clauses'][2]
        assert a['rule']==b['rule'] and a['char_start']!=b['char_start']

def test_cross_meaning_pair_refused(panels):
    p,pairs,_=panels;bad=deepcopy(pairs['train']);bad[0]['right_id']=bad[1]['right_id']
    with pytest.raises(ValueError,match='canonical atoms'):c.validate_pairs(p['train'],bad,192)

def test_duplicate_pair_membership_refused(panels):
    p,pairs,_=panels;bad=deepcopy(pairs['train']);bad[1]=deepcopy(bad[0]);bad[1]['pair_id']='duplicate'
    with pytest.raises(ValueError,match='exactly one pair'):c.validate_pairs(p['train'],bad,192)

def test_corrupt_pair_commitment_refused(panels):
    p,pairs,_=panels;bad=deepcopy(pairs['train']);bad[0]['canonical_ir_sha256']='0'*64
    with pytest.raises(ValueError,match='commitment'):c.validate_pairs(p['train'],bad,192)

def test_copied_absolute_coordinates_between_paraphrases_refused(panels):
    p,pairs,_=panels;by_id={r['id']:r for r in p['train']};pair=pairs['train'][0]
    bad=deepcopy(by_id[pair['right_id']]);bad['facet_spans']=by_id[pair['left_id']]['facet_spans']
    with pytest.raises(ValueError):c.mixed.validate_row(bad)

def test_actual_loader_cannot_read_fresh_labels_or_layout_evidence(frozen,monkeypatch):
    m=json.loads(frozen.read_bytes());denied={Path(m['artifacts'][key]['path']).resolve() for key in c.SEALED};attempts=[]
    old=builtins.open;old_path=Path.open
    def check(p):
        if isinstance(p,(str,bytes,Path)) and Path(p).resolve() in denied:
            attempts.append(str(p));raise AssertionError('sealed artifact opened')
    def guarded(p,*a,**kw):check(p);return old(p,*a,**kw)
    def guarded_path(p,*a,**kw):check(p);return old_path(p,*a,**kw)
    monkeypatch.setattr(builtins,'open',guarded);monkeypatch.setattr(Path,'open',guarded_path)
    x=c.load_training_inputs(frozen)
    assert len(x['new_train'])==384 and len(x['new_tuning'])==96
    assert len(x['fresh_sources'])==144 and len(x['fresh_document_sources'])==96
    assert not attempts

def test_os_audit_loader_has_zero_sealed_opens(frozen):
    code='''
import json,pathlib,sys
from scripts.ops.legal_ir import prepare_legal_clause_consistency_corpus as c
p=pathlib.Path(sys.argv[1]);m=json.loads(p.read_bytes())
denied={str(pathlib.Path(m['artifacts'][key]['path']).resolve()) for key in c.SEALED}
def audit(event,args):
 if event=='open' and isinstance(args[0],(str,bytes)) and str(pathlib.Path(args[0]).resolve()) in denied:raise RuntimeError('sealed artifact opened')
sys.addaudithook(audit)
x=c.load_training_inputs(p)
assert len(x['new_train'])==384 and len(x['training_pairs'])==192
print('sealed access guard passed')
'''
    r=subprocess.run([sys.executable,'-c',code,str(frozen)],cwd=c.ROOT,text=True,capture_output=True)
    assert r.returncode==0,r.stdout+r.stderr
    assert 'sealed access guard passed' in r.stdout

def test_source_only_schema_refuses_target_injection(frozen,tmp_path):
    m=json.loads(frozen.read_bytes());rows=c.read_ref(m['artifacts']['challenge_sources']);rows[0]['canonical_ir']={}
    source=tmp_path/'source.json';source.write_text(json.dumps(rows));m['artifacts']['challenge_sources']=c.file_ref(source)
    path=tmp_path/'manifest.json';path.write_text(json.dumps(m))
    with pytest.raises(ValueError,match='closed fresh single'):c.load_training_inputs(path)

def test_pinned_training_source_hash_corruption_refused(frozen,tmp_path):
    m=json.loads(frozen.read_bytes());source=tmp_path/'source.json';source.write_text('[]');m['artifacts']['new_training']['path']=str(source)
    path=tmp_path/'manifest.json';path.write_text(json.dumps(m))
    with pytest.raises(ValueError):c.load_training_inputs(path)

def test_frozen_output_must_not_be_overwritten(frozen):
    with pytest.raises(ValueError,match='already exists'):c.freeze(frozen.parent)
