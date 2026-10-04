from collections import Counter
from copy import deepcopy
import builtins
import io
import json
from pathlib import Path
import pytest
from ipfs_datasets_py.logic.autoformal import legal_temporal_coupled_span_corpus as c

@pytest.fixture(scope='module')
def train_references():
    return [r for source in range(5) for r in c.paired.render_source('train', 0, source)]

@pytest.fixture(scope='module')
def contrast_fixture(train_references):
    targets=[c.project_reference(r) for r in train_references]
    contrasts,groups=c.build_training_contrasts(targets,train_references)
    return targets,contrasts,groups

@pytest.fixture(scope='module')
def panels():
    return {name:c.make_panel(name) for name in c.UNITS}

@pytest.mark.parametrize('panel',list(c.UNITS))
def test_eval_source_complete_and_balanced_shared_grammar(panels,panel):
    rows,units=panels[panel]
    assert len(rows)==144 and len(units)==12 and len({r['source_sha256'] for r in rows})==60
    assert Counter(r['label'] for r in rows)==Counter({kind:36 for kind in c.LABELS})
    assert Counter(r['annotation']['modality'] for r in rows)==Counter({kind:48 for kind in 'OPF'})
    assert Counter(r['annotation']['time_form'] for r in rows)==Counter({kind:36 for kind in c.TIME_FORMS})
    assert all(set(c.source_row(r))==c.SOURCE_KEYS and set(c.project_reference(r))==c.TARGET_KEYS for r in rows)
    c.validate_query_inventory([c.source_row(r) for r in rows],expected=144)
    known={c.stability.body_layout(r) for oldpanel in c.pointer.UNITS for r in c.pointer.make_panel(oldpanel)[0]}
    assert all(c.stability.body_layout(r) in known for r in rows)
    assert c._fixed_manifest()['structural_novelty_claimed'] is False

def test_complete_negative_inventory_includes_untimed_concrete_owners(contrast_fixture,train_references):
    targets,contrasts,groups=contrast_fixture
    assert len(contrasts)==12 and Counter(len(g['query_ids']) for g in groups)==Counter({2:3,3:2})
    for target,rich in zip(targets,train_references):
        record=contrasts[target['id']]
        assert set(record)==c.CONTRAST_KEYS
        assert record['source_sha256']==target['source_sha256'] and record['proposed_time_span']==target['proposed_time_span']
        owners=c.concrete_owner_anchors(rich)
        expected=[] if target['label']=='ambiguous' else [o['anchor_span'] for o in owners if o['anchor_span']!=target['owner_anchor_span']]
        assert record['negative_owner_spans']==expected
        if target['label']!='ambiguous': assert len(expected)>=2

def test_same_type_different_anchor_is_kept_as_negative():
    for unit in range(12):
        rows=[r for source in range(5) for r in c.previous.render_source('train',unit,source)]
        targets=[c.project_reference(r) for r in rows];contrasts,_=c.build_training_contrasts(targets,rows)
        for target,rich in zip(targets,rows):
            same=[o['anchor_span'] for o in c.concrete_owner_anchors(rich) if o['owner_type']==target['label'] and o['anchor_span']!=target['owner_anchor_span']]
            if same:
                assert all(span in contrasts[target['id']]['negative_owner_spans'] for span in same)
                return
    pytest.fail('fixture lacks concrete same-type siblings')

@pytest.mark.parametrize('mutation',['positive','query','duplicate','unsorted','omitted','ambiguous_nonempty','source_hash','time_span','extra','integer_alias'])
def test_repaired_contrast_metadata_rejected(contrast_fixture,train_references,mutation):
    targets,original,groups=contrast_fixture;contrasts=deepcopy(original)
    target=next(r for r in targets if r['label']!='ambiguous');record=contrasts[target['id']]
    if mutation=='positive':record['negative_owner_spans'].append(deepcopy(target['owner_anchor_span']))
    elif mutation=='query':record['negative_owner_spans'][0]=deepcopy(target['proposed_time_span'])
    elif mutation=='duplicate':record['negative_owner_spans'].append(deepcopy(record['negative_owner_spans'][0]))
    elif mutation=='unsorted':record['negative_owner_spans'].reverse()
    elif mutation=='omitted':record['negative_owner_spans'].pop()
    elif mutation=='ambiguous_nonempty':
        ambiguous=next(r for r in targets if r['label']=='ambiguous');contrasts[ambiguous['id']]['negative_owner_spans']=[deepcopy(target['owner_anchor_span'])]
    elif mutation=='source_hash':record['source_sha256']='0'*64
    elif mutation=='time_span':record['proposed_time_span']['char_end']-=1
    elif mutation=='extra':record['label']=target['label']
    else:record['negative_owner_spans'][0]['char_start']=float(record['negative_owner_spans'][0]['char_start'])
    with pytest.raises(ValueError,match='metadata'):c.validate_training_contrasts(targets,train_references,contrasts,groups)

@pytest.mark.parametrize('mutation',['query_omission','source_group_omission','source_group_duplicate','wrong_source','unsorted_queries'])
def test_complete_source_group_inventory_rejected(contrast_fixture,train_references,mutation):
    targets,contrasts,original=contrast_fixture;groups=deepcopy(original)
    if mutation=='query_omission':groups[0]['query_ids'].pop()
    elif mutation=='source_group_omission':groups.pop()
    elif mutation=='source_group_duplicate':groups.append(deepcopy(groups[0]))
    elif mutation=='wrong_source':groups[0]['source_sha256']='0'*64
    else:groups[0]['query_ids'].reverse()
    with pytest.raises(ValueError,match='metadata'):c.validate_training_contrasts(targets,train_references,contrasts,groups)

def test_missing_source_time_query_cannot_be_training_contrast(train_references):
    rows=train_references[:-1];targets=[c.project_reference(r) for r in rows]
    with pytest.raises(ValueError):c.build_training_contrasts(targets,rows)

@pytest.mark.parametrize('module',[c.old,c.paired,c.previous,c.stability,c.pointer])
def test_all_admitted_reference_schemas_preserve_exact_projection(module):
    rows=module.make_group('train',0) if module is c.old else module.render_source('fresh_lexical' if module in (c.stability,c.pointer) else 'train',0,0)
    for row in rows:
        assert c.project_reference(row)==c.pointer.project_reference(row)
        assert {r['owner_type'] for r in c.concrete_owner_anchors(row)}==set(c.LABELS[:3])

def test_repeated_norm_reference_maps_exact_occurrence(panels):
    row=next(r for r in panels['fresh_structural'][0] if r['label']=='norm' and len(r['annotation']['norm_occurrences'])>1 and r['proposed_time_span']['char_start']!=r['annotation']['norm_occurrences'][0]['time_span']['char_start'])
    target=c.project_reference(row)
    assert target['owner_anchor_span']['char_start']!=row['annotation']['norm_occurrences'][0]['action_span']['char_start']

def test_source_only_features_exclude_contrast_and_owner_reference(panels):
    for row in panels['fresh_lexical'][0]:
        assert set(c.source_row(row))=={'id','source_text','source_sha256','proposed_time_span'}
        assert c.project_reference(row)['owner_anchor_span'] is None if row['label']=='ambiguous' else c.project_reference(row)['owner_anchor_span'] is not None

@pytest.fixture
def miniature_admitted(monkeypatch,tmp_path,train_references):
    tuning=[r for source in range(5) for r in c.paired.render_source('tuning',0,source)]
    retained={name:c.old.make_group('fresh',i) for i,name in enumerate(c.RETENTION)}
    data={'training':train_references,'tuning':tuning,'retention':retained,'history':{'training':train_references,'selection':tuning,**retained},'historical_source_packs':[]}
    monkeypatch.setattr(c,'admitted_inputs',lambda _:deepcopy(data))
    prior=tmp_path/'fictional-prior.json';prior.write_text('{}')
    return data,prior

def test_loader_zero_four_sealed_reference_opens(miniature_admitted,tmp_path,monkeypatch):
    data,prior=miniature_admitted;result=c.build_corpus(tmp_path/'corpus',prior)
    m=c.read_ref(result['manifest']);denied={m['artifacts'][k]['path'] for k in c.SEALED};attempts=[]
    def guard(original):
        def call(path,*args,**kwargs):
            if isinstance(path,(str,Path)) and str(Path(path).resolve()) in denied:
                attempts.append(str(path));raise AssertionError('sealed reference read')
            return original(path,*args,**kwargs)
        return call
    monkeypatch.setattr(builtins,'open',guard(builtins.open));monkeypatch.setattr(io,'open',guard(io.open))
    loaded=c.load_training_inputs(result['manifest']['path'])
    assert attempts==[] and len(loaded['training_contrasts'])==12 and len(loaded['source_groups'])==5
    assert set(loaded['retention_targets'])==set(c.RETENTION)
    assert len(loaded['fresh_lexical_sources'])==len(loaded['fresh_structural_sources'])==144

@pytest.mark.parametrize('mutation',['contrast_hash_repaired','producer_float_alias','artifact_alias'])
def test_loader_detects_repaired_artifact_tampering(miniature_admitted,tmp_path,mutation):
    _,prior=miniature_admitted;result=c.build_corpus(tmp_path/'corpus',prior)
    path=Path(result['manifest']['path']);m=json.loads(path.read_text())
    if mutation=='contrast_hash_repaired':
        p=Path(m['artifacts']['training_contrasts']['path']);values=json.loads(p.read_text());item=next(v for v in values.values() if v['negative_owner_spans']);item['negative_owner_spans'].pop();p.write_text(json.dumps(values));m['artifacts']['training_contrasts']=c.file_ref(p)
    elif mutation=='producer_float_alias':m['producer_files'][0]['bytes']=float(m['producer_files'][0]['bytes'])
    else:m['artifacts']['training_source_groups']=m['artifacts']['training_contrasts']
    path.write_text(json.dumps(m))
    with pytest.raises(ValueError):c.load_training_inputs(path)

def test_existing_artifacts_are_never_overwritten(tmp_path):
    with pytest.raises(ValueError,match='preserve'):c.build_corpus(tmp_path,'/must/not/read')
