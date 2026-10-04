"""Construction objects must not overlap independent replay and source fences.

These are logical lifetime controls on the actual inference orchestration with
declared worker/storage seams, not numerical or resident-memory measurements.
"""
from contextlib import contextmanager
import json
from types import SimpleNamespace
import weakref

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_source_units_384 as owner


@pytest.fixture
def case(monkeypatch):
    class Graph(dict):
        pass

    state = SimpleNamespace(contexts=[], outputs=[], observations=[], events=[],
        committed=False, cold=True, closed=False, source_failure=None, failure='none',
        cancelled=False, stored=None, worker_calls=0, load_calls=0)
    key={'declared_key':'fixture'}; artifact={'declared_artifact':'fixture'}
    signal=SimpleNamespace(is_set=lambda:state.cancelled)
    lease=SimpleNamespace(combined_cancellation_signal=lambda cancel:signal)

    @contextmanager
    def acquire(**kwargs):
        state.admission=kwargs
        try:yield lease
        finally:state.closed=True

    def context(*args, **kwargs):
        prep=Graph(selected_inputs=[{'id':'fixture','source_text':'def f(): return 1'}])
        checkpoint=Graph(weights=[.125]*384)
        state.contexts.append((weakref.ref(prep),weakref.ref(checkpoint)))
        return (dict(key,changed=True) if state.failure=='model_drift' and len(state.contexts)>1 else key),prep,checkpoint

    def worker(payload, **kwargs):
        state.worker_calls+=1;state.events.append('worker')
        assert state.contexts[0][1]() is payload['checkpoint']
        output=Graph(rows=[{'candidate':{'declared_candidate':True}}])
        state.outputs.append(weakref.ref(output))
        return output,{'declared_receipt':'fixture'}

    def validate(*args):
        state.events.append('validate')
        if state.failure=='worker_output':raise ValueError('declared invalid output')

    def observe(*args, **kwargs):
        state.events.append('observe')
        state.observations.append(dict(checkpoint_released=bool(state.contexts) and state.contexts[0][1]() is None,
            preparation_released=bool(state.contexts) and state.contexts[0][0]() is None,
            worker_output_released=bool(state.outputs) and state.outputs[0]() is None))
        if state.source_failure==len(state.observations):raise RuntimeError('declared source refusal')

    def resolve(*args):
        return {'artifact':artifact} if state.committed or not state.cold else None

    def stage(registry, saved):
        state.events.append('stage');state.stored=json.dumps(saved)
        return artifact

    def mutate(operation, kind, payload, callback):
        state.events.append('commit');state.committed=True
        return callback(None)

    def load(*args, **kwargs):
        state.load_calls+=1;state.events.append('load')
        state.released_at_load=[(a() is None,b() is None) for a,b in state.contexts]
        state.output_released_at_load=not state.outputs or state.outputs[0]() is None
        if state.failure=='replay':raise ValueError('declared corrupt immutable replay')
        if state.failure=='cancel_after_load':state.cancelled=True
        return json.loads(state.stored) if state.stored else {'output':{'rows':[{'candidate':None}]}}

    registry=SimpleNamespace(resolve_operation=resolve,_mutate=mutate)
    index=SimpleNamespace(observe_current=observe)
    monkeypatch.setattr(owner.shared,'_owners',lambda *args:None)
    monkeypatch.setattr(owner.shared,'_stage',stage)
    monkeypatch.setattr(owner,'acquire_codebase_resources',acquire)
    monkeypatch.setattr(owner,'_context',context)
    monkeypatch.setattr(owner,'_worker',worker)
    monkeypatch.setattr(owner,'_validate_output',validate)
    monkeypatch.setattr(owner,'_coverage',lambda *args:{'declared_coverage':True})
    monkeypatch.setattr(owner,'load_source_unit_inference',load)
    state.run=lambda:owner.infer_shared_parent_units(index,'fixture-repository',expected_head='fixture-head',
        registry=registry,version_id='fixture-parent',paths=['module.py'],embedding_snapshot='fixture-snapshot',
        timeout_seconds=30,memory_mb=4096)
    return state


def test_worker_checkpoint_released_before_post_worker_source_fence(case):
    result=case.run()
    assert case.observations[1]['checkpoint_released']
    assert case.events[:4]==['observe','worker','validate','observe']
    assert result['native_worker_executed'] and result['inference_executed']
    assert case.closed and case.admission['memory_mb']==4096


@pytest.mark.parametrize('cold',[True,False])
def test_construction_graphs_released_before_independent_replay(case,cold):
    case.cold=cold;result=case.run()
    assert all(a and b for a,b in case.released_at_load)
    assert case.output_released_at_load
    assert case.observations[-1]['preparation_released']
    assert case.worker_calls==int(cold) and case.load_calls==1
    assert len(case.observations)==(4 if cold else 2)
    assert result['native_worker_executed']==cold and all(result[k] is False for k in owner.FALSE)


@pytest.mark.parametrize('boundary',[1,2,3,4])
def test_every_fresh_source_fence_can_still_refuse(case,boundary):
    case.source_failure=boundary
    with pytest.raises(RuntimeError,match='declared source refusal'):case.run()
    assert len(case.observations)==boundary and case.closed
    assert case.committed==(boundary==4)


@pytest.mark.parametrize('failure',['worker_output','model_drift','replay','cancel_after_load'])
def test_output_model_replay_and_cancellation_guards_remain_required(case,failure):
    case.failure=failure
    with pytest.raises(ValueError):case.run()
    assert case.closed
    if failure=='worker_output':assert len(case.observations)==1 and not case.committed
    if failure=='model_drift':assert len(case.observations)==2 and not case.committed
    if failure in {'replay','cancel_after_load'}:assert case.committed and case.load_calls==1
