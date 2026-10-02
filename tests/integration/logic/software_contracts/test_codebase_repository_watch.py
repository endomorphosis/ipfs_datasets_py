"""Actual bounded watcher notifications; injected foundation host sampler."""
import threading

import pytest

from tests.integration.logic.software_contracts.test_codebase_repository_shards import current,sharded
from ipfs_datasets_py.logic.software_contracts import codebase_repository_watch as module


def run(sharded,**options):
    current,_,source=sharded
    return module.watch_repository_shards(current[1],current[0],root_cid=source['root_cid'],
        scheduler=current[3],**options)


def test_real_watcher_changes_are_hints_only_and_scans_are_bounded(sharded,monkeypatch):
    current,_,_=sharded;before=current[1].current('scan:fixture')
    original=module.RepositoryWatch.start
    def start(watcher):
        result=original(watcher)
        (current[0]/'z.py').write_text('def target(n: int) -> int:\n    return n + 8\n')
        return result
    monkeypatch.setattr(module.RepositoryWatch,'start',start)
    result=run(sharded,maximum_scans=8,duration_seconds=6,poll_interval_ms=50)
    assert 2<=result['scans']<=8 and result['watcher_drained'] and result['hints']
    assert all(h['action']=='request_fresh_complete_native_capture' and not h['parser_or_model_authority'] for h in result['hints'])
    assert current[1].current('scan:fixture')==before and not result['current_head_published']


def test_real_watcher_coalesces_notifications_without_creating_work_authority(sharded,monkeypatch):
    root=sharded[0][0];original=module.RepositoryWatch.start
    def start(watcher):
        callback=watcher.callback;count=[1]
        def notified(value):
            callback(value);count[0]+=1
            (root/'z.py').write_text('def target(n: int) -> int:\n    return n + '+str(count[0])+'\n')
        watcher.callback=notified;value=original(watcher)
        (root/'z.py').write_text('def target(n: int) -> int:\n    return n + 0\n')
        return value
    monkeypatch.setattr(module.RepositoryWatch,'start',start)
    result=run(sharded,maximum_scans=16,maximum_notifications=1,duration_seconds=10,poll_interval_ms=50)
    assert len(result['hints'])==1 and result['coalesced_notifications']>=1 and result['scans']<=16
    assert not result['proof_authority'] and not result['inference_executed']


def test_real_watcher_cancellation_drains_before_releasing_parent(sharded,monkeypatch):
    signal=threading.Event();original=module.RepositoryWatch.start
    def start(watcher):
        value=original(watcher);signal.set();return value
    monkeypatch.setattr(module.RepositoryWatch,'start',start)
    result=run(sharded,cancel_event=signal,duration_seconds=6)
    assert result['cancelled'] and result['watcher_drained'] and not result['proof_authority']


@pytest.mark.parametrize('options',[dict(maximum_scans=0),dict(maximum_notifications=0),dict(duration_seconds=100),dict(poll_interval_ms=0)])
def test_unbounded_watch_requests_refuse_before_owner_access(options):
    with pytest.raises(module.shards.RepositoryShardsError):
        module.watch_repository_shards(None,None,root_cid='none',**options)
