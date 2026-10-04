"""TRAIN-only mining, heterogeneous warm starts and matched condition rehearsal."""
from copy import deepcopy
from pathlib import Path
import runpy

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_facet_retention as facet
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_temporal_presence as temporal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_scope_retention as runtime

H=runpy.run_path(str(Path(__file__).with_name('test_legal_span_temporal_presence.py')))


@pytest.fixture(scope='module',autouse=True)
def threads():
    old=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


@pytest.fixture(scope='module')
def data():
    rows=[];pairs=[]
    for i in range(10):
        chunk,paired=H['rows_and_pairs'](f'scope-fit-{i}');rows.extend(chunk)
        if i==0:pairs=paired
    return rows,pairs


@pytest.fixture(scope='module')
def parents():
    originals=H['parents'].__wrapped__();rows,pairs=H['rows_and_pairs']('temporal-parent')
    updated=temporal.train_decoder(temporal.build_checkpoint(originals[True],rows,[],pairs,
        objective='base',seed=1729),rows,[],pairs,max_steps=2,max_seconds=30)['checkpoint']
    return {False:('facet_retention',originals[False]),True:('temporal_presence',updated)}


@pytest.fixture(scope='module')
def mining(parents,data):
    return {enabled:runtime.mine_condition_hard_examples(parent,kind,data[0]) for enabled,(kind,parent) in parents.items()}


def child(parents,mining,data,enabled=True,objective='condition_rehearsal'):
    kind,parent=parents[enabled]
    return runtime.build_checkpoint(parent,*data[:1],[],data[1],mining[enabled],parent_kind=kind,objective=objective,seed=1729)


@pytest.mark.parametrize('enabled',[False,True])
def test_actual_parent_kind_exact_weights_inference_and_fresh_adam(parents,mining,data,enabled):
    kind,parent=parents[enabled];cp=child(parents,mining,data,enabled)
    assert cp['frozen_parent_kind']==kind and cp['frozen_parent_checkpoint']==parent
    assert cp['model_state']==parent['model_state'] and cp['optimizer_state']['parameters']=={}
    assert cp['training_config']['learning_rate']==.00025 and cp['progress']['optimizer_steps']==0
    source=[r['source_text'] for r in data[0][-4:]]
    expected=(facet.FacetRetentionDecoder if kind=='facet_retention' else temporal.TemporalPresenceDecoder)(parent).decode_formal_logic(source)
    actual=runtime.ScopeRetentionDecoder(cp)
    assert actual.decode_formal_logic(source)['rows']==expected['rows']
    cp['model_state']={};assert actual.checkpoint['model_state']==parent['model_state']


@pytest.mark.parametrize('enabled',[False,True])
def test_mining_scores_all_train_rows_exact_classes_and_deterministic_ranking(parents,mining,data,enabled):
    kind,parent=parents[enabled];manifest=mining[enabled]
    assert len(manifest['score_rows'])==len(data[0])==260
    assert manifest==runtime.mine_condition_hard_examples(parent,kind,data[0])
    assert manifest['training_manifest_sha256']==runtime.checkpoint_digest(data[0])
    assert manifest['parent_checkpoint_sha256']==runtime.checkpoint_digest(parent)
    for present,label in ((True,'positive'),(False,'negative')):
        ranked=sorted((r for r in manifest['score_rows'] if r['condition_present'] is present),key=lambda r:(-r['condition_loss_sum'],r['id']))
        assert len(manifest['selected_ids'][label])==64
        assert manifest['selected_ids'][label]==[r['id'] for r in ranked[:64]]
    assert all(r['condition_endpoint_ce']==0 for r in manifest['score_rows'] if not r['condition_present'])


@pytest.mark.parametrize('enabled',[False,True])
@pytest.mark.parametrize('objective',['base','condition_rehearsal'])
def test_exact_resumption_including_auxiliary_schedule_moments_losses(parents,mining,data,enabled,objective):
    rows,pairs=data;cp=child(parents,mining,data,enabled,objective)
    full=runtime.train_decoder(cp,rows,[],pairs,max_steps=4,max_seconds=30)
    first=runtime.train_decoder(cp,rows,[],pairs,max_steps=1,max_seconds=30)
    resumed=runtime.train_decoder(first['checkpoint'],rows,[],pairs,max_steps=3,max_seconds=30)
    for key in ('model_state','optimizer_state','progress'):assert full['checkpoint'][key]==resumed['checkpoint'][key]
    for key in ('batch_losses','batch_loss_components','batch_exposures'):
        assert full['report'][key]==first['report'][key]+resumed['report'][key]
    for parts in full['report']['batch_loss_components']:
        assert parts['condition_positive_rows']==parts['condition_negative_rows']==2
        assert parts['total']==pytest.approx(parts['common_objective']+(.5 if objective=='condition_rehearsal' else 0)*parts['condition_rehearsal_ce'],abs=1e-6)
    assert full['report']['rehearsal_exposures']=={'positive':8,'negative':8}
    assert full['report']['teacher_state_unchanged'] and full['report']['teacher_gradients_disabled']
    if not enabled:assert all(v==0 for v in full['report']['auxiliary_gradient_norm_max'].values())


@pytest.mark.parametrize('enabled',[False,True])
def test_matched_sources_and_zero_aux_control_equals_common_objective_gradients(parents,mining,data,enabled):
    rows,pairs=data;cp=child(parents,mining,data,enabled,'base');target=child(parents,mining,data,enabled)
    a=runtime.train_decoder(cp,rows,[],pairs,max_steps=2,max_seconds=30)
    b=runtime.train_decoder(target,rows,[],pairs,max_steps=2,max_seconds=30)
    assert a['report']['batch_exposures']==b['report']['batch_exposures']
    records,_=runtime.mixed._splits(rows,[]);by_id={r['id']:r for r in records};trace=a['report']['batch_exposures'][0]
    batch=[by_id[i] for i in trace['ids']];aux=[by_id[i] for i in trace['rehearsal_ids']]
    _,model,_=runtime._restore(cp);kind,parent=parents[enabled];_,teacher,_=runtime._parent_runtime(kind)._restore(parent)
    actual,parts=runtime._loss(torch,model,teacher,batch,aux,cp['model_config'],'base')
    expected,_=facet._loss(torch,model,teacher,batch,cp['model_config'],'facet_retention')
    assert torch.equal(actual,expected) and parts['weighted_condition_rehearsal']==0
    ga=torch.autograd.grad(actual,tuple(model.parameters()),retain_graph=True)
    gb=torch.autograd.grad(expected,tuple(model.parameters()))
    assert all(torch.equal(x,y) for x,y in zip(ga,gb))


def test_full_aux_epochs_progress_and_balanced_classes(data):
    pools=runtime._pairs_and_pools(*data);counts={k:len(v) for k,v in pools.items()};progress=runtime._progress(counts,1730)
    seen={'positive':[],'negative':[]}
    for step in range(200):
        indices,progress=runtime.next_batch_indices(progress,counts,1730)
        assert progress==runtime._progress(counts,1730,step+1)
        for label in seen:
            assert len(indices['rehearsal_'+label])==2;seen[label].extend(indices['rehearsal_'+label])
    assert all(len(v)==400 and set(v)==set(range(64)) for v in seen.values())


def fake_aux():
    output=H['HELPERS']['fake_output'](4)
    _,_,record=H['HELPERS']['teacher_fixture']()
    rows=[deepcopy(record) for _ in range(4)]
    for row in rows[2:]:row['labels']['presence'][3]=False;row['labels']['spans'][3]=(-100,-100)
    return output,rows


def test_auxiliary_formula_matches_manual_ce_and_gradients_only_condition_heads():
    output,rows=fake_aux();loss,parts=runtime._condition_rehearsal_loss(torch,output,rows)
    positive=torch.nn.functional.cross_entropy(output['presence'][:2,1],torch.ones(2,dtype=torch.long))
    negative=torch.nn.functional.cross_entropy(output['presence'][2:,1],torch.zeros(2,dtype=torch.long))
    endpoints=sum(torch.nn.functional.cross_entropy(output[key][:2,3],torch.ones(2,dtype=torch.long)) for key in ('start','end'))/2
    assert torch.equal(loss,((positive+negative)/2+endpoints)/2)
    loss.backward()
    for key in ('start','end'):
        assert output[key].grad[:2,3].abs().sum()>0
        assert torch.count_nonzero(output[key].grad[2:])==0
        assert torch.count_nonzero(output[key].grad[:,:3])==torch.count_nonzero(output[key].grad[:,4:])==0
    assert output['presence'].grad[:,1].abs().sum()>0
    assert torch.count_nonzero(output['presence'].grad[:,[0,2,3]])==0


def test_absent_endpoints_cannot_influence_auxiliary_loss_and_invalid_balance_rejects():
    output,rows=fake_aux();before,_=runtime._condition_rehearsal_loss(torch,output,rows)
    with torch.no_grad():output['start'][2:]*=100;output['end'][2:]*=100
    after,_=runtime._condition_rehearsal_loss(torch,output,rows);assert torch.equal(before,after)
    rows[0]['labels']['presence'][3]=False
    with pytest.raises(ValueError,match='two condition-present'):runtime._condition_rehearsal_loss(torch,output,rows)


@pytest.mark.parametrize('mutation',['parent_hash','selected_order','source_hash','class','score_sum','score_missing','labels_authority'])
def test_mining_manifest_mutations_rejected(parents,mining,data,mutation):
    kind,parent=parents[True];bad=deepcopy(mining[True])
    if mutation=='parent_hash':bad['parent_checkpoint_sha256']='0'*64
    elif mutation=='selected_order':bad['selected_ids']['positive'].reverse()
    elif mutation=='source_hash':bad['score_rows'][0]['source_sha256']='0'*64
    elif mutation=='class':bad['score_rows'][0]['condition_present']=not bad['score_rows'][0]['condition_present']
    elif mutation=='score_sum':bad['score_rows'][0]['condition_loss_sum']+=1
    elif mutation=='score_missing':bad['score_rows'].pop()
    else:bad['tuning_or_test_used']=True
    with pytest.raises(ValueError):runtime.build_checkpoint(parent,data[0],[],data[1],bad,parent_kind=kind,objective='base',seed=1729)


def test_parent_kind_and_resume_mining_progress_mutations_rejected(parents,mining,data):
    cp=child(parents,mining,data);cp['frozen_parent_kind']='facet_retention'
    with pytest.raises(ValueError):runtime.validate_checkpoint(cp)
    cp=child(parents,mining,data);cp['progress']['rehearsal_pools']['positive']['row_cursor']=1
    with pytest.raises(ValueError,match='progress'):runtime.validate_checkpoint(cp)
    with pytest.raises(ValueError,match='max_steps'):runtime.train_decoder(child(parents,mining,data),data[0],[],data[1],max_steps=201)


def test_owned_checkpoint_roundtrip_and_immutable_mining(parents,mining,data,tmp_path):
    cp=child(parents,mining,data);pin=runtime.save_checkpoint(cp,tmp_path/'checkpoint.json')
    assert runtime.load_checkpoint(pin['path'],expected_sha256=pin['sha256'])==cp
    with pytest.raises(FileExistsError):runtime.save_checkpoint(cp,tmp_path/'checkpoint.json')
    decoder=runtime.ScopeRetentionDecoder(cp);cp['hard_mining']['selected_ids']['positive'].reverse()
    assert decoder.checkpoint['hard_mining']==mining[True]
