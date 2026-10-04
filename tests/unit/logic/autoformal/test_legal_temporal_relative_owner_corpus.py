from collections import Counter
from copy import deepcopy
import builtins
import io
import json
from pathlib import Path
import pytest
from ipfs_datasets_py.logic.autoformal import legal_temporal_relative_owner_corpus as c

@pytest.fixture(scope='module')
def panels():
    return {k:c.make_panel(k) for k in c.UNITS}

@pytest.fixture(scope='module')
def train_references():
    return [r for u in range(12) for s in range(5) for r in c.coupled.render_source('fresh_lexical',u,s)]

@pytest.fixture(scope='module')
def contrasts(train_references):
    targets=[c.project_reference(r) for r in train_references]
    values,groups=c.build_other_norm_contrasts(targets,train_references)
    return targets,values,groups

@pytest.mark.parametrize('panel',list(c.UNITS))
def test_balanced_complete_panels_preserve_query_only_features(panels,panel):
    rows,units=panels[panel]
    assert len(rows)==144 and len(units)==12 and len({r['source_sha256'] for r in rows})==60
    assert Counter(r['label'] for r in rows)==Counter({k:36 for k in c.LABELS})
    assert Counter(r['annotation']['modality'] for r in rows)==Counter({k:48 for k in 'OPF'})
    assert Counter(r['annotation']['time_form'] for r in rows)==Counter({k:36 for k in c.TIME_FORMS})
    assert all(set(c.source_row(r))==c.SOURCE_KEYS and set(c.project_reference(r))==c.TARGET_KEYS for r in rows)
    known={c.stability.body_layout(r) for oldpanel in c.coupled.UNITS for r in c.coupled.make_panel(oldpanel)[0]}
    assert all(c.stability.body_layout(r) in known for r in rows)

def test_all_four_panel_namespaces_and_literals_are_disjoint(panels):
    seen_sources=set();seen_ids=set();seen_groups=set();seen_times=set();seen_names=set()
    for k,(rows,_) in panels.items():
        for values,seen in [({r['source_sha256'] for r in rows},seen_sources),({r['id'] for r in rows},seen_ids),
                            ({r['group_id'] for r in rows},seen_groups),({r['annotation']['time_span']['text'] for r in rows},seen_times),
                            (set(c.VOCAB[k]['names']),seen_names)]:
            assert not values&seen;seen.update(values)

def test_norm_only_full_role_negatives_preserve_untimed_and_same_type_anchors(contrasts,train_references):
    targets,values,groups=contrasts
    assert len(values)==len(targets) and len(groups)==60
    nonempty=0
    for target,rich in zip(targets,train_references):
        expected=[] if target['label']!='norm' else [o['anchor_span'] for o in c.concrete_owner_anchors(rich)
                  if o['owner_type']=='norm' and o['anchor_span']!=target['owner_anchor_span']]
        assert values[target['id']]['negative_owner_spans']==expected
        nonempty+=bool(expected)
    assert nonempty>0

@pytest.mark.parametrize('mutation',['positive','query','duplicate','unsorted','omitted','non_norm','source_hash','time_span','extra','float_alias'])
def test_repaired_norm_negative_metadata_is_rejected(contrasts,train_references,mutation):
    targets,original,groups=contrasts;values=deepcopy(original)
    t=next(t for t in targets if len(values[t['id']]['negative_owner_spans'])>=2);r=values[t['id']]
    if mutation=='positive':r['negative_owner_spans'].append(t['owner_anchor_span'])
    elif mutation=='query':r['negative_owner_spans'][0]=t['proposed_time_span']
    elif mutation=='duplicate':r['negative_owner_spans'].append(r['negative_owner_spans'][0])
    elif mutation=='unsorted':r['negative_owner_spans'].reverse()
    elif mutation=='omitted':r['negative_owner_spans'].pop()
    elif mutation=='non_norm':values[next(t['id'] for t in targets if t['label']=='condition')]['negative_owner_spans']=[t['owner_anchor_span']]
    elif mutation=='source_hash':r['source_sha256']='0'*64
    elif mutation=='time_span':r['proposed_time_span']['char_end']-=1
    elif mutation=='extra':r['label']='norm'
    else:r['negative_owner_spans'][0]['char_start']=float(r['negative_owner_spans'][0]['char_start'])
    with pytest.raises(ValueError,match='metadata'):c.validate_other_norm_contrasts(targets,train_references,values,groups)

@pytest.mark.parametrize('mutation',['missing_group','missing_query','duplicate','wrong_source'])
def test_complete_training_source_groups_cannot_be_changed(contrasts,train_references,mutation):
    targets,values,original=contrasts;groups=deepcopy(original)
    if mutation=='missing_group':groups.pop()
    elif mutation=='missing_query':groups[0]['query_ids'].pop()
    elif mutation=='duplicate':groups.append(deepcopy(groups[0]))
    else:groups[0]['source_sha256']='0'*64
    with pytest.raises(ValueError):c.validate_other_norm_contrasts(targets,train_references,values,groups)

def test_incomplete_source_occurrence_queries_are_rejected(train_references):
    rows=train_references[:-1]
    with pytest.raises(ValueError):c.build_other_norm_contrasts([c.project_reference(r) for r in rows],rows)

@pytest.mark.parametrize('panel',list(c.UNITS))
def test_repeated_norm_maps_the_queried_occurrence_not_first_action(panels,panel):
    r=next(r for r in panels[panel][0] if r['label']=='norm' and len(r['annotation']['norm_occurrences'])>1
           and r['proposed_time_span']['char_start']!=r['annotation']['norm_occurrences'][0]['time_span']['char_start'])
    assert c.project_reference(r)['owner_anchor_span']['char_start']!=r['annotation']['norm_occurrences'][0]['action_span']['char_start']

@pytest.fixture
def miniature(monkeypatch,tmp_path,train_references):
    tuning=[r for s in range(5) for r in c.paired.render_source('tuning',0,s)]
    retained={k:c.old.make_group('fresh',i) for i,k in enumerate(c.RETENTION)}
    source='Historical source-only document without a current proposed occurrence.'
    historical=c.write_new(tmp_path/'historical-source-pack.json',[{'candidate_id':'old-document','source_text':source,'source_sha256':c.sha(source)}])
    data={'training':train_references,'tuning':tuning,'retention':retained,'history':{'training':train_references,'selection':tuning,**retained},'historical_source_packs':[historical]}
    monkeypatch.setattr(c,'admitted_inputs',lambda _:deepcopy(data))
    prior=tmp_path/'fictional-prior.json';prior.write_text('{}')
    return c.build_corpus(tmp_path/'corpus',prior)

def install_denial(monkeypatch,paths):
    attempts=[]
    def wrap(original):
        def call(path,*a,**k):
            if isinstance(path,(str,Path)) and str(Path(path).resolve()) in paths:
                attempts.append(str(path));raise AssertionError('sealed reference read')
            return original(path,*a,**k)
        return call
    monkeypatch.setattr(builtins,'open',wrap(builtins.open));monkeypatch.setattr(io,'open',wrap(io.open))
    return attempts

def test_fit_loader_opens_zero_of_eight_semantic_files(miniature,monkeypatch):
    m=c.read_ref(miniature['manifest']);paths={m['artifacts'][k]['path'] for k in c.SEALED}
    assert len(paths)==8 and set(c.CALIBRATION_SEALED).isdisjoint(c.FRESH_SEALED)
    attempts=install_denial(monkeypatch,paths);loaded=c.load_training_inputs(miniature['manifest']['path'])
    assert attempts==[] and len(loaded['training_other_norm_contrasts'])==144
    assert all(len(loaded[k+'_sources'])==144 for k in c.UNITS)
    assert not any(k.endswith('_targets') for k in loaded if k.startswith(('calibration','fresh')))

def test_calibration_reference_validation_never_opens_fresh(miniature,monkeypatch):
    m=c.read_ref(miniature['manifest']);a=m['artifacts']
    attempts=install_denial(monkeypatch,{a[k]['path'] for k in c.FRESH_SEALED})
    targets={k:c.read_ref(a[k+'_targets']) for k in c.CALIBRATION_PANELS};ledger=c.read_ref(a['calibration_annotation_ledger'])
    assert c.validate_stage_references(targets,ledger,stage='calibration') is True and attempts==[]
    ledger['stage']='fresh'
    with pytest.raises(ValueError):c.validate_stage_references(targets,ledger,stage='calibration')

@pytest.mark.parametrize('mutation',['contrast_hash_repaired','producer_float','artifact_alias','sealed_stage_swap'])
def test_loader_rejects_repaired_artifacts_and_manifest_aliases(miniature,mutation):
    p=Path(miniature['manifest']['path']);m=json.loads(p.read_text())
    if mutation=='contrast_hash_repaired':
        f=Path(m['artifacts']['training_other_norm_contrasts']['path']);x=json.loads(f.read_text())
        next(r for r in x.values() if r['negative_owner_spans'])['negative_owner_spans'].pop();f.write_text(json.dumps(x));m['artifacts']['training_other_norm_contrasts']=c.file_ref(f)
    elif mutation=='producer_float':m['producer_files'][0]['bytes']=float(m['producer_files'][0]['bytes'])
    elif mutation=='artifact_alias':m['artifacts']['calibration_annotation_ledger']=m['artifacts']['fresh_annotation_ledger']
    else:m['calibration_sealed_artifacts']=list(c.FRESH_SEALED)
    p.write_text(json.dumps(m))
    with pytest.raises(ValueError):c.load_training_inputs(p)

def test_old_inputs_and_existing_output_are_never_overwritten(tmp_path):
    with pytest.raises(ValueError,match='preserve'):c.build_corpus(tmp_path,'/must/not/read')
