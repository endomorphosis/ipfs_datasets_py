"""Pure admission controls for the fixed observational trace recipe."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[5]

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value

subject=module('_trace_benchmark_tests',ROOT/'scripts/ops/autoencoder/benchmark_decoder_gradient_trace.py')
prior=module('_exposure_benchmark_tests',ROOT/'scripts/ops/autoencoder/benchmark_decoder_count_exposure.py')


def recipe():
    return dict(schema='decoder-gradient-trace-plan/v1',representation_dimension=384,
        arms=[dict(name='current_stage',count_exposure='current_stage',guide_boundary=False,cardinality_weight=.25),
              dict(name='balanced_all',count_exposure='balanced_all',guide_boundary=False,cardinality_weight=.25)],
        seed_order=[1729,2718],conditioning='every_step',loss='semantic_fields',epochs_per_source_stage=20,
        expected_optimizer_steps_per_arm=340,expected_training_token_presentations_per_arm=225840,
        expected_count_presentations_per_arm=2440,batch_size=8,learning_rate=.001,max_seconds_per_arm=60,
        validation_interval=4,fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,projection_frozen=True,
        teacher_distillation_used=False,selection_unchanged=True,no_downloads=True,generation_reference_count_access=False,
        native_qualification=False,gradient_trace=dict(enabled=True,threshold=50.0,top_k=2,module_summaries=True),
        event_replay_seconds=30,event_replay_memory_bytes=536870912)


def test_trace_admission_preserves_recipe_and_prior_validation():
    plan=recipe();before=deepcopy(plan)
    subject.validate_plan(plan,prior.validate_plan)
    assert plan==before
    assert subject.FALSE['qualified'] is False
    assert subject.FALSE['lake_executed'] is False


@pytest.mark.parametrize('key,value',[
    ('schema','decoder-count-exposure-plan/v1'),('representation_dimension',768),('learning_rate',.002),
    ('fixed_encoder_context_tokens',1024),('fixed_decoder_output_limit',1024),('seed_order',[1729]),
    ('projection_frozen',False),('native_qualification',True),('selection_unchanged',False),
    ('no_downloads',False),('generation_reference_count_access',True),('expected_count_presentations_per_arm',0),
    ('event_replay_seconds',31),('event_replay_seconds',True),('event_replay_seconds',float('nan')),
    ('event_replay_memory_bytes',1073741824),('event_replay_memory_bytes',False),
])
def test_trace_admission_rejects_budget_or_scope_drift(key,value):
    plan=recipe();plan[key]=value
    with pytest.raises(ValueError):subject.validate_plan(plan,prior.validate_plan)


@pytest.mark.parametrize('key,value',[
    ('enabled',False),('top_k',3),('top_k',True),('threshold',49.0),('threshold',float('inf')),
    ('module_summaries',False),('unexpected',1),
])
def test_trace_policy_is_exact_not_runtime_tunable(key,value):
    plan=recipe();plan['gradient_trace'][key]=value
    with pytest.raises(ValueError):subject.validate_plan(plan,prior.validate_plan)


def test_fixed_recipe_cannot_enable_guidance():
    plan=recipe();plan['arms'][1]['guide_boundary']=True
    with pytest.raises(ValueError):subject.validate_plan(plan,prior.validate_plan)


def test_exposure_helper_digest_checked_before_import(tmp_path):
    relative='scripts/ops/autoencoder/benchmark_decoder_count_exposure.py';path=tmp_path/relative
    path.parent.mkdir(parents=True);path.write_text('raise AssertionError("must not import")\n')
    with pytest.raises(ValueError,match='frozen exposure'):
        subject.load_exposure_helper(tmp_path,{relative:'0'*64})


def test_exposure_helper_imports_the_exact_pinned_bytes(tmp_path):
    relative='scripts/ops/autoencoder/benchmark_decoder_count_exposure.py';path=tmp_path/relative
    path.parent.mkdir(parents=True);content=b'identity = "pinned"\n';path.write_bytes(content)
    helper=subject.load_exposure_helper(tmp_path,{relative:hashlib.sha256(content).hexdigest()})
    assert helper.identity=='pinned'


def orchestration_fixture():
    event=dict(optimizer_step_before=3,preclip_norm=70.,event_sha256='capture',complete=True,committed=True)
    steps=[dict(optimizer_step_before=1,preclip_norm=50.,committed=True),
           dict(optimizer_step_before=2,preclip_norm=90.,committed=False),
           {key:event[key] for key in ('optimizer_step_before','preclip_norm','committed')}]
    result=dict(gradient_events=[event],uncommitted_gradient_events=[],
        report=dict(gradient_trace=dict(configuration=recipe()['gradient_trace'],steps=steps,
            captured_event_summaries=[dict(event_sha256='capture')])))
    ctx=dict(rows=dict(train=['training rows']),references=dict(train=['training references']),
        donor=dict(codec='codec',input_transform='transform'),validate_rule='validator')
    return event,result,ctx


def require(value,reason):
    if not value:raise ValueError(reason)


def durable_save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value))
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size)


class ReplayStub:
    calls=[]
    @staticmethod
    def pack_event(event):return dict(event=event)
    @staticmethod
    def unpack_event(packet,**kwargs):return packet['event']
    def replay_event(self,model,event,rows,references,codec,transform,**kwargs):
        self.calls.append((model,event,rows,references,codec,transform,kwargs))
        return dict(complete=True,full_step_exact=True,event_sha256=event['event_sha256'],
            live_training_modified=False,used_for_selection=False,attribution=dict(branches_reconcile=True),attribution_valid=True,
            optimizer_steps_on_private_copy=1,elapsed_seconds=.125)


def test_replay_uses_durable_packet_and_training_inputs_only(tmp_path):
    event,result,ctx=orchestration_fixture();owner=ReplayStub();owner.calls=[]
    report=subject.replay_captured_events(owner,'template',result,ctx,recipe(),tmp_path,durable_save,require)
    call=owner.calls[0]
    assert call[1]==event and call[1] is not event
    assert call[2:6]==(['training rows'],['training references'],'codec','transform')
    assert call[6]==dict(strategy='semantic_fields',validate_rule='validator',max_seconds=30,max_memory_bytes=536870912)
    assert report['complete'] and report['event_count']==report['optimizer_steps_on_private_copies']==1
    assert report['replay_elapsed_seconds']==.125 and not report['qualified']
    assert len(list((tmp_path/'gradient-events').glob('*.json')))==2


def test_replay_accepts_no_exceptional_steps_without_inventing_captures(tmp_path):
    _,result,ctx=orchestration_fixture();result['gradient_events']=[]
    result['report']['gradient_trace']['steps']=[];result['report']['gradient_trace']['captured_event_summaries']=[]
    report=subject.replay_captured_events(ReplayStub(),'template',result,ctx,recipe(),tmp_path,durable_save,require)
    assert report['complete'] and report['event_count']==report['optimizer_steps_on_private_copies']==0


def test_uncommitted_packet_is_retained_without_replay(tmp_path):
    event,result,ctx=orchestration_fixture();aborted={**event,'committed':False,'complete':False,'optimizer_step_before':7}
    result['uncommitted_gradient_events']=[aborted];owner=ReplayStub();owner.calls=[]
    report=subject.replay_captured_events(owner,'template',result,ctx,recipe(),tmp_path,durable_save,require)
    assert len(owner.calls)==1 and not report['complete']
    assert report['uncommitted'][0]['replayed'] is False
    assert (tmp_path/'gradient-events/step-7.uncommitted.json').exists()


@pytest.mark.parametrize('failure',['wrong_topk','tampered_file','inexact_replay','selection_change'])
def test_replay_orchestration_fails_closed(tmp_path,failure):
    _,result,ctx=orchestration_fixture();owner=ReplayStub();save=durable_save
    if failure=='wrong_topk':result['gradient_events'][0]['optimizer_step_before']=0
    if failure=='tampered_file':
        def save(path,value):
            receipt=durable_save(path,value);path.write_text('{}');return receipt
    if failure in ('inexact_replay','selection_change'):
        original=owner.replay_event
        def replay(*args,**kwargs):
            value=original(*args,**kwargs)
            value['full_step_exact' if failure=='inexact_replay' else 'used_for_selection']=failure=='selection_change'
            return value
        owner.replay_event=replay
    with pytest.raises(ValueError):
        subject.replay_captured_events(owner,'template',result,ctx,recipe(),tmp_path,save,require)
