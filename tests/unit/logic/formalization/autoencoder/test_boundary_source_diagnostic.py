"""Synthetic causal observation invariants; no trained checkpoint is evaluated."""
from copy import deepcopy
import random
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import boundary_source_diagnostic as subject
from ipfs_datasets_py.logic.formalization.autoencoder import shared_slot_source_decoder_experiment as shared
from ipfs_datasets_py.logic.formalization.autoencoder import mean_centered_source_decoder_experiment as centered
from .test_projected_source_decoder_experiment import bound, encode, rule, inputs


@pytest.fixture(autouse=True)
def one_cpu():
    previous = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def scripted(kind="projected", *, invalid=False, count_bias=0.):
    base, codec, _ = bound(dimension=8, kind="center_rms", guided=True)
    vocabulary = codec["target_vocabulary"]
    sequence = encode(codec)[1:]
    if invalid: sequence = [vocabulary.index('"agency"'), 2]

    class Positions(torch.nn.Module):
        def forward(self, values, hidden):
            position = hidden[0,:,0].long()
            output = torch.zeros(len(values), values.shape[1], len(sequence))
            for offset in range(values.shape[1]):
                output[:,offset].scatter_(1,(position+offset).clamp(max=len(sequence)-1).unsqueeze(1),1.)
            updated = hidden.clone(); updated[0,:,0] += values.shape[1]
            return output, updated

    body = base.body.body
    body.decoder = Positions()
    body.output = torch.nn.Linear(len(sequence),len(vocabulary))
    with torch.no_grad():
        body.condition.weight.zero_(); body.condition.bias.zero_()
        body.output.weight.fill_(-20.); body.output.bias.zero_()
        for index,token in enumerate(sequence): body.output.weight[token,index] = 20.
        base.count_head.bias[1] = count_bias
    if kind == "shared": model = shared.bind_shared_slot_source_model(base,head_seed=1729)
    elif kind == "raw":
        model = centered.bind_mean_centered_source_model(base,scalar_mode="raw",
            training_feature_mean_receipt=base.describe()["normalization"])
    else: model = base
    rows = [dict(id=str(index),input=vector) for index,vector in enumerate(inputs(8).tolist())]
    return model,codec,rows,sequence


def trace(model,codec,rows,**options):
    return subject.trace_boundary_generation(model,rows,codec=codec,input_transform=dict(mean=[0.]*8,scale=1.),
        max_target_tokens=options.pop('max_target_tokens',128),batch_size=2,max_seconds=30,**options)


def plain(model,codec,rows,cap=128):
    private = deepcopy(model).eval()
    with torch.inference_mode():
        return subject.core._greedy(torch,private,torch.tensor([r['input'] for r in rows]),
            cap,len(codec['target_vocabulary']),time.monotonic()+30)


@pytest.mark.parametrize("kind", ["projected", "shared", "raw"])
def test_actual_incremental_generation_matches_unobserved_path(kind):
    model,codec,rows,sequence = scripted(kind,count_bias=1.)
    expected = plain(model,codec,rows); result = trace(model,codec,rows)
    assert [row['token_ids'] for row in result['predictions']] == expected[1]
    assert [row['generation_status'] for row in result['predictions']] == expected[2]
    assert all(row['token_ids']==sequence[:-1] for row in result['predictions'])
    assert result['boundary_event_count']==4
    for row in result['rows']:
        assert row['predicted_count']==2 and len(row['count_probabilities'])==32
        assert sum(row['count_probabilities']) == pytest.approx(1.)
        assert row['syntactic_rule_count']==2 and row['syntactic_duplicate_rule_count']==1
        assert [event['completed_rules'] for event in row['boundaries']]==[1,2]
        assert [event['action'] for event in row['boundaries']]==['continue','stop']
        assert row['scalar_sites_observed']==8 and row['first_invalid_prefix_position'] is None
        for event in row['boundaries']:
            assert event['count_correction_active'] and event['scalar_guidance_overlap'] is None
            stop = event['stop_token_id']
            assert event['final_logits'][stop] == pytest.approx(event['recurrent_logits'][stop]+event['count_correction'],abs=2e-6)
            assert all(a==b for i,(a,b) in enumerate(zip(event['recurrent_logits'],event['final_logits'])) if i!=stop)
            assert event['actual_next_token_id']==event['final_argmax_token_id']
    assert result['logits_addition_replay_exact'] and result['actual_prefix_argmax_binding']
    assert not result['reference_documents_passed_to_model'] and not result['qualified']


def test_caller_tensors_gradients_modes_rng_and_hook_inventory_preserved():
    model,codec,rows,_ = scripted('shared')
    model.train(); model.body.body.eval()
    for p in model.parameters(): p.grad=torch.full_like(p,.25)
    modes={n:m.training for n,m in model.named_modules()}
    hooks={n:dict(m._forward_hooks) for n,m in model.named_modules()}
    tensor=subject.core.tensor_digest(model);gradient=subject._gradient_digest(model)
    rng=torch.get_rng_state().clone();python_rng=random.getstate()
    result=trace(model,codec,rows)
    assert subject.core.tensor_digest(model)==tensor and subject._gradient_digest(model)==gradient
    assert {n:m.training for n,m in model.named_modules()}==modes
    assert {n:dict(m._forward_hooks) for n,m in model.named_modules()}==hooks
    assert torch.equal(torch.get_rng_state(),rng) and random.getstate()==python_rng
    assert result['caller_tensors_modes_gradients_rng_preserved']


def test_invalid_prefix_has_no_invented_boundary_and_no_semantic_claim():
    model,codec,rows,_=scripted(invalid=True);result=trace(model,codec,rows)
    assert result['boundary_event_count']==0
    assert all(row['first_invalid_prefix_position']==1 and not row['boundaries']
        and row['syntactic_rule_count'] is None for row in result['rows'])
    assert all(row['eos_reached'] for row in result['rows'])


def test_output_limit_preserves_partial_prefix_and_status():
    model,codec,rows,_=scripted();expected=plain(model,codec,rows,cap=12)
    result=trace(model,codec,rows,max_target_tokens=12)
    assert [r['token_ids'] for r in result['predictions']]==expected[1]
    assert [r['generation_status'] for r in result['predictions']]==['output_limit']*2
    assert result['boundary_event_count']==0 and all(r['generated_content_tokens']==11 for r in result['rows'])


@pytest.mark.parametrize('extra',['target_ids','target','reference_count','prefix','source_text'])
def test_target_or_reference_metadata_rejected_before_generation(extra):
    model,codec,rows,_=scripted();rows[0][extra]=[1,2]
    with pytest.raises(ValueError,match='source-only row'):trace(model,codec,rows)


@pytest.mark.parametrize('cap',[True,0,513,1024])
def test_no_encoder_or_output_cap_increase(cap):
    model,codec,rows,_=scripted()
    with pytest.raises(ValueError,match='fixed512'):trace(model,codec,rows,max_target_tokens=cap)


def test_deadline_failure_and_memory_bound_leave_caller_untouched(monkeypatch):
    model,codec,rows,_=scripted();before=subject.core.tensor_digest(model)
    many=[dict(id=str(index),input=rows[0]['input']) for index in range(128)]
    with pytest.raises(ValueError,match='memory estimate'):trace(model,codec,many,max_memory_bytes=1048576)
    tick=[0.]
    def clock():tick[0]+=31.;return tick[0]
    monkeypatch.setattr(subject.time,'monotonic',clock)
    with pytest.raises(ValueError,match='deadline'):trace(model,codec,rows)
    assert subject.core.tensor_digest(model)==before


def test_frozen_prior_gives_exact_zero_guidance_without_forcing_count():
    model,codec,rows,_=scripted();result=trace(model,codec,rows)
    assert all(event['count_correction']==0. for row in result['rows'] for event in row['boundaries'])
    assert all(row['predicted_count']==1 and row['syntactic_rule_count']==2 for row in result['rows'])
    assert result['forced_closure'] is False and result['syntax_mask'] is False


def test_actual_local_argmax_flip_is_observed_without_counterfactual_rollout():
    model,codec,rows,_=scripted()
    with torch.no_grad():model.count_head.bias[0]=50.
    expected=plain(model,codec,rows);result=trace(model,codec,rows)
    assert [row['token_ids'] for row in result['predictions']]==expected[1]
    for row in result['rows']:
        event=row['boundaries'][0]
        assert event['completed_rules']==1 and event['local_argmax_changed'] is True
        assert event['recurrent_argmax_token_id']==event['continue_token_id']
        assert event['final_argmax_token_id']==event['stop_token_id']
        assert event['recurrent_stop_minus_best_other']<0<event['final_stop_minus_best_other']
        # The learned recurrent continuation still runs after the soft choice;
        # instrumentation never repairs the deliberately inconsistent sequence.
        assert row['first_invalid_prefix_position'] is not None


def test_rows_terminated_earlier_in_batch_have_no_later_phantom_events():
    model,codec,rows,_=scripted();body=model.body.body
    original=body.decoder
    class FirstRowEnds(torch.nn.Module):
        def __init__(self):super().__init__();self.original=original
        def forward(self,values,hidden):
            output,updated=self.original(values,hidden)
            output[0].zero_();output[0,:,-1]=1.  # EOS readout at every step for row0.
            return output,updated
    body.decoder=FirstRowEnds()
    result=trace(model,codec,rows);expected=plain(model,codec,rows)
    assert [r['token_ids'] for r in result['predictions']]==expected[1]
    assert result['predictions'][0]['token_ids']==[] and result['predictions'][0]['eos_reached']
    assert result['rows'][0]['boundaries']==[] and result['rows'][0]['scalar_sites_observed']==0
    assert len(result['rows'][1]['boundaries'])==2


def test_transform_cannot_smuggle_reference_metadata():
    model,codec,rows,_=scripted()
    with pytest.raises(ValueError,match='input transform'):
        subject.trace_boundary_generation(model,rows,codec=codec,
            input_transform=dict(mean=[0.]*8,scale=1.,reference_count=2))
