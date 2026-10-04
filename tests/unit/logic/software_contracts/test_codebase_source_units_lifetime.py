"""Logical replay-graph lifetime, result isolation and two source fences.

Actual validator with controlled immutable-loader/admission seams; no native
index, decoder, provider, model qualification or resident-memory measurement.
"""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
import weakref

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_source_units_384 as owner
from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead


@pytest.fixture
def replay_case(monkeypatch):
    cid=cid_for_structured({'declared_fixture':True})
    head=CodebaseHead('fixture',1,cid,cid,f'rev:fixture:snapshot:{cid}',cid).to_dict()
    saved={'key':{'source_head':head,'version_id':'fixture-parent'},'preparation':{
        'paths':['module.py'],'max_functions':1024,'max_selected_units':128},
        'output':{'rows':[{'candidate':{'declared_fixture':True}}]}}
    report={'artifact':{'declared_fixture':True},'report':saved,
        'native_worker_executed':True,'inference_executed':True,**owner.FALSE}
    case=SimpleNamespace(report=report,observations=[],refs=[],load_calls=[],mutate=None,
        failure_at=None,failure=RuntimeError('declared source refusal'),cancelled=False,closed=False)
    class ReplayGraph(dict):pass
    signal=SimpleNamespace(is_set=lambda:case.cancelled)
    lease=SimpleNamespace(combined_cancellation_signal=lambda cancel:signal)
    @contextmanager
    def acquire(**kwargs):
        case.admission=kwargs
        try:yield lease
        finally:case.closed=True
    def observe(repository,**kwargs):
        case.observations.append({'duplicate_released':bool(case.refs) and case.refs[-1]() is None,
                                  'kwargs':kwargs})
        if case.failure_at==len(case.observations):raise case.failure
    index=SimpleNamespace(observe_current=observe); registry=object()
    def load(observed,models,artifact,**kwargs):
        assert observed is index and models is registry and artifact==report['artifact']
        case.load_calls.append(kwargs)
        actual=ReplayGraph(deepcopy(report['report']))
        if case.mutate:case.mutate(actual)
        case.refs.append(weakref.ref(actual))
        return actual
    def owners(observed,models):assert observed is index and models is registry
    monkeypatch.setattr(owner.shared,'_owners',owners)
    monkeypatch.setattr(owner,'acquire_codebase_resources',acquire)
    monkeypatch.setattr(owner,'load_source_unit_inference',load)
    case.run=lambda:owner.validate_shared_parent_units(index,'declared-fixture-root',report,
        registry=registry,embedding_snapshot='declared-fixture-snapshot',timeout_seconds=30,memory_mb=4096)
    return case


def test_duplicate_native_report_released_before_second_source_observation(replay_case):
    case=replay_case; before=deepcopy(case.report)
    returned=case.run()
    assert len(case.observations)==2 and not case.observations[0]['duplicate_released']
    assert case.observations[1]['duplicate_released']
    assert returned==before and case.report==before and returned is not case.report
    returned['report']['output']['rows'][0]['candidate']['new']=True
    assert case.report==before
    assert case.closed and case.refs[0]() is None
    assert case.admission['memory_mb']==4096
    assert 0<case.admission['timeout_seconds']<=30
    for observed in case.observations:
        assert 0<observed['kwargs']['timeout_seconds']<=30
        assert observed['kwargs']['memory_mb']==4096


def test_admission_and_source_fences_share_the_original_deadline(replay_case,monkeypatch):
    case=replay_case
    ticks=iter([100.,105.,106.,110.])
    monkeypatch.setattr(owner,'time',SimpleNamespace(monotonic=lambda:next(ticks)))
    case.run()
    assert case.admission['timeout_seconds']==25.
    assert [item['kwargs']['timeout_seconds'] for item in case.observations]==[24.,20.]
    assert case.closed


@pytest.mark.parametrize('damage',['report_bytes','execution_flags'])
def test_duplicate_report_is_fully_checked_before_second_fence(replay_case,damage):
    case=replay_case
    if damage=='report_bytes':case.mutate=lambda actual:actual.update(extra='different native report')
    else:case.report['inference_executed']=False
    with pytest.raises(ValueError,match='retained source-unit'):case.run()
    assert len(case.observations)==1 and case.closed


@pytest.mark.parametrize('boundary',[1,2])
def test_both_fresh_source_refusals_remain_authoritative(replay_case,boundary):
    case=replay_case;case.failure_at=boundary
    with pytest.raises(RuntimeError) as error:case.run()
    assert error.value is case.failure and len(case.observations)==boundary
    assert len(case.load_calls)==boundary-1 and case.closed


def test_cancellation_between_load_and_second_observation_still_refuses(replay_case):
    case=replay_case
    def cancel(actual):case.cancelled=True
    case.mutate=cancel
    with pytest.raises(ValueError,match='deadline or cancellation'):case.run()
    assert len(case.observations)==1 and case.closed
