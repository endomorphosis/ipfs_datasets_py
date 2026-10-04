"""Source-complete contrasts, independent candidate coordinates, and seal tests."""
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import pytest
from ipfs_datasets_py.logic.autoformal import legal_paired_temporal_ownership_corpus as c
from ipfs_datasets_py.logic.autoformal import legal_temporal_owner_candidates as owners


@pytest.fixture(scope='module')
def panels():
    return {name:c.make_panel(name) for name in c.COUNTS}


@pytest.mark.parametrize('split',list(c.COUNTS))
def test_complete_source_balanced_units_and_replay(panels,split):
    rows,units=panels[split];c.validate_units(rows,units,split)
    assert len({r['source_sha256'] for r in rows})==c.UNITS[split]*5
    for label in c.LABELS:
        selected=[r for r in rows if r['label']==label]
        assert len(selected)==len(rows)//4
        assert Counter(r['annotation']['modality'] for r in selected)=={m:len(rows)//12 for m in 'OPF'}
        assert Counter(r['annotation']['time_form'] for r in selected)=={f:len(rows)//16 for f in c.TIME_FORMS}


def test_every_candidate_passes_independent_coordinate_contract(panels):
    for rows,_ in panels.values():
        for row in rows:
            report=owners.prepare_owner_candidates(c.source_row(row),c.candidate_coordinate_inputs(row))
            assert report['coordinate_integrity_verified'] is True
            assert report['owner_occurrence_resolved'] is False
            a=row['annotation']
            assert a['gold_filtered_owner_candidates'] is True
            assert a['candidate_inventory_usage']=='reference_only_not_inference_inputs'
            assert a['candidate_scope_semantics']=='structural_enclosing_extent_not_semantic_closure'


def test_same_owner_pairs_and_triples_have_distinct_exact_anchors(panels):
    for rows,_ in panels.values():
        groups=defaultdict(list)
        for row in rows:groups[row['source_sha256']].append(row)
        for cardinality in (2,3):
            for label in c.LABELS:
                selected=[v for v in groups.values() if len(v)==cardinality and {r['label'] for r in v}=={label}]
                assert selected,(cardinality,label)
                for group in selected:
                    if label=='ambiguous':continue
                    ids=[r['annotation']['owner_candidates'][0]['owner_occurrence_id'] for r in group]
                    assert len(set(ids))==cardinality
        assert any(len({r['label'] for r in v})==3 for v in groups.values())


def test_complete_proposal_and_source_only_features(panels):
    for rows,_ in panels.values():
        sources=[c.source_row(r) for r in rows];c.validate_query_inventory(sources)
        for row in sources:
            assert set(row)==c.SOURCE_KEYS
            assert row['id'].startswith('occ-') and len(row['id'])==68
            assert all(label not in row['id'] for label in c.LABELS)
        with pytest.raises(ValueError):c.validate_query_inventory(sources[:-1])


def test_actual_encoder_token_budget_and_time_alignment(panels):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
    for rows,_ in panels.values():
        for row in rows:
            tokens=span.tokenize_source(row['source_text']);t=row['proposed_time_span']
            assert len(tokens)<=256
            assert t['char_start'] in {v['start'] for v in tokens}
            assert t['char_end'] in {v['end'] for v in tokens}


def test_ambiguity_countermodels_are_not_legal_truth(panels):
    for rows,_ in panels.values():
        for row in rows:
            a=row['annotation'];assert a['legal_gold'] is False and a['independently_reviewed'] is False
            assert a['flat_logic_profile_admission'] is False
            if row['label']=='ambiguous':
                assert a['unique_owner_type_asserted'] is False
                assert a['countermodels']['legal_truth_verified'] is False
                assert {v['owner_type'] for v in a['owner_candidates']} in ({'norm','condition'},{'norm','exception'})
            else:assert a['countermodels'] is None


@pytest.mark.parametrize('change',['label','scope','cue','ownerid','factor_float','source','authority','countermodel'])
def test_repaired_reference_changes_fail(change):
    row=deepcopy(next(r for r in c.render_source('train',0,1) if r['label']=='ambiguous'));a=row['annotation']
    if change=='label':row['label']='norm'
    elif change=='scope':a['owner_candidates'][0]['scope_span']=deepcopy(a['heading_span'])
    elif change=='cue':a['attachment_cue_spans'][0]['span']=deepcopy(a['time_span'])
    elif change=='ownerid':a['owner_candidates'][0]['owner_occurrence_id']='owner-'+'0'*64
    elif change=='factor_float':a['unit_index']=0.0
    elif change=='source':
        row['source_text']=row['source_text'].replace(' is valid',' was received').replace(' is active',' was issued')
        row['source_sha256']=c.sha(row['source_text']);row['id']=c.query(row['source_text'],row['proposed_time_span'])['id']
    elif change=='authority':a['legal_gold']=True
    else:a['countermodels']['legal_truth_verified']=True
    with pytest.raises(ValueError):c.validate_target(row)


@pytest.mark.parametrize('change',['duplicate_row','missing_row','unit_cross_join','duplicate_unit','unit_label','unit_extra'])
def test_unit_integrity_rejects_missing_duplicate_or_broken_groups(panels,change):
    rows,units=deepcopy(panels['tuning'])
    if change=='duplicate_row':rows[-1]=deepcopy(rows[0])
    elif change=='missing_row':rows.pop()
    elif change=='unit_cross_join':units[0]['query_ids'][0]=units[1]['query_ids'][0];units[0]['query_ids'].sort()
    elif change=='duplicate_unit':units[0]=deepcopy(units[1])
    elif change=='unit_label':rows[0]['label']='wrong'
    else:units[0]['label']='norm'
    with pytest.raises(ValueError):c.validate_units(rows,units,'tuning')


def empty_prior():
    return {'train':[],'tuning':[],'fresh_sources':[],'multi_fresh_sources':[],'manifest_ref':None}


def test_exposure_has_real_structural_holdout_and_shared_lexical_layouts(panels):
    a=c.exposure_audit(panels,empty_prior(),[])
    assert a['panels']['fresh_structural']['matches_train_or_tuning_body_layout_queries']==0
    assert a['panels']['fresh_lexical']['matches_train_body_layout_queries']>0
    assert a['cross_split_literal_overlap']==0
    assert a['shared_local_attachment_grammar'] is True
    for name,record in a['panels'].items():
        assert record['queries']==c.COUNTS[name]
        assert record['source_cardinality_and_distinct_owner_types']['3occ/1types']>0


def test_exposure_refuses_history_source_or_target_leakage(panels,tmp_path):
    row=panels['train'][0][0];pin=c.write_new(tmp_path/'history.json',[{'candidate_id':'old',**{k:row[k] for k in ('source_text','source_sha256')}}])
    with pytest.raises(ValueError,match='overlap'):c.exposure_audit(panels,empty_prior(),[pin])
    target=c.write_new(tmp_path/'bad.json',[row])
    with pytest.raises(ValueError,match='source pack'):c.exposure_audit(panels,empty_prior(),[target])


def test_collapsed_structural_partition_is_rejected(panels):
    values=deepcopy(panels)
    for row in values['fresh_structural'][0]:
        row['annotation']['source_role_spans']=[]
    # The declared partition is audited from actual normalized source structure,
    # not merely the family string. Replacing a whole structural panel is rejected.
    values['fresh_structural']=deepcopy(values['fresh_lexical'])
    with pytest.raises(ValueError):c.exposure_audit(values,empty_prior(),[])


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    base=tmp_path_factory.mktemp('paired-corpus')
    prior=c.old.build_corpus(base/'prior',[])
    return Path(c.build_corpus(base/'current',prior['path'])['path'])


def test_loader_complete_interface_and_cli_alias(built):
    loaded=c.load_training_inputs(built)
    for key,count in {'single_training':768,'single_tuning':144,'paired_training':864,'paired_tuning':288,
                      'sampling_units':72,'tuning_units':24,'fresh_lexical_sources':144,'fresh_structural_sources':144}.items():
        assert len(loaded[key])==count
    assert len(loaded['regression_sources']['single'])==192 and len(loaded['regression_sources']['multi'])==96
    assert loaded['manifest']['sealed_artifacts']==list(c.SEALED)
    root=Path(__file__).resolve().parents[4]
    sys.path.insert(0,str(root/'scripts/ops/legal_ir'))
    import prepare_legal_paired_temporal_ownership_corpus as cli
    assert cli.load_training_inputs is c.load_training_inputs


def test_loader_opens_neither_four_seals_nor_old_regression_targets(built):
    script='''
import json,sys
from pathlib import Path
from ipfs_datasets_py.logic.autoformal import legal_paired_temporal_ownership_corpus as c
p=Path(sys.argv[1]);m=json.loads(p.read_text());blocked={str(Path(m['artifacts'][k]['path']).resolve()) for k in c.SEALED}
blocked.update(str(Path(m['regression_references'][k]['path']).resolve()) for k in ('single_targets','multi_targets'))
attempts=[]
def guard(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)) and str(Path(args[0]).resolve()) in blocked:
  attempts.append(str(args[0]));raise AssertionError('sealed path')
sys.addaudithook(guard)
x=c.load_training_inputs(p)
assert len(x['paired_training'])==864 and not attempts
print('zero sealed or regression-target reads')
'''
    result=subprocess.run([sys.executable,'-c',script,str(built)],capture_output=True,text=True,cwd=Path(__file__).resolve().parents[4])
    assert result.returncode==0,result.stderr
    assert 'zero sealed' in result.stdout


@pytest.mark.parametrize('change',['count_float','producer_float','authority','artifact_alias','extra','regression_pin'])
def test_repaired_manifest_rejected(built,tmp_path,change):
    m=json.loads(built.read_text())
    if change=='count_float':m['counts']['train']=864.0
    elif change=='producer_float':m['producer_files'][0]['bytes']=float(m['producer_files'][0]['bytes'])
    elif change=='authority':m['independent_legal_gold']=True
    elif change=='artifact_alias':m['artifacts']['fresh_lexical_targets']=m['artifacts']['train_targets']
    elif change=='extra':m['extra']=True
    else:m['regression_references']['single_targets']=m['regression_references']['multi_targets']
    p=c.write_new(tmp_path/'manifest.json',m)['path']
    with pytest.raises(ValueError):c.load_training_inputs(p)


def test_no_materialized_corpus_overwrite(built):
    with pytest.raises(ValueError,match='new corpus'):c.build_corpus(built.parent,built)
