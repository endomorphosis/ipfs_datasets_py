"""Bounded notification-only reuse of the existing repository watcher.

Hints never publish a source head or select model/proof work. A consumer must
perform its ordinary complete native capture and admission after a hint.
"""
from __future__ import annotations
import threading
import time

from . import codebase_repository_shards as shards
from .codebase_resources import acquire_codebase_resources
from .codebase_scan_policy import CodebaseScanPolicy
from .codebase_scan_policy_live import verify_policy_current
from .semantic_index.scanner import RepositoryScanner
from .semantic_index.snapshot import snapshot_repository,GIT_COMMAND_TIMEOUT_SECONDS
from .semantic_index.watch import RepositoryWatch
from ...duckdb_control.codebase_catalog import CodebaseHead


def watch_repository_shards(index,repository,*,root_cid,maximum_scans=8,maximum_notifications=4,
        duration_seconds=3,poll_interval_ms=100,scheduler=None,parent_lease=None,cancel_event=None,memory_mb=512):
    require=shards.require
    require(type(maximum_scans) is int and 2<=maximum_scans<=32,'bounded watcher scan count required')
    require(type(maximum_notifications) is int and 1<=maximum_notifications<=16,'bounded watcher notification count required')
    require(type(duration_seconds) in (int,float) and 0<duration_seconds<=30,'bounded watcher lifetime required')
    require(type(poll_interval_ms) is int and 50<=poll_interval_ms<=1000,'bounded watcher cadence required')
    deadline=time.monotonic()+duration_seconds
    stopped=threading.Event();lock=threading.Lock();notifications=[];coalesced=0
    class BoundedScanner(RepositoryScanner):
        def __init__(self):
            super().__init__(repository_id=head.repository_id,exclusions=policy.exclusions)
            self.scans=0;self.last_error=None
        def scan(self,root,*,previous_state=None,snapshot=None):
            if self.scans>=maximum_scans or time.monotonic()>=deadline or signal.is_set():
                stopped.set();raise shards.RepositoryShardsError('watcher finite scan/deadline budget exhausted')
            self.scans+=1
            # Snapshot limits precede every native parser input; no event path
            # can narrow or substitute the complete inventory.
            captured=snapshot_repository(root,repository_id=head.repository_id,max_entries=policy.max_entries,
                max_file_bytes=policy.max_file_bytes,exclusions=policy.exclusions)
            result=super().scan(root,previous_state=previous_state,snapshot=captured)
            if time.monotonic()>=deadline or signal.is_set():stopped.set()
            return result
    def notified(notification):
        nonlocal coalesced
        hint=dict(previous_state_cid=notification.previous_state_cid,state_cid=notification.state_cid,
            action='request_fresh_complete_native_capture',source_root_cid=root_cid,
            source_head_published=False,parser_or_model_authority=False)
        with lock:
            if len(notifications)==maximum_notifications:
                notifications[-1]=hint;coalesced+=1
            else:notifications.append(hint)
    with acquire_codebase_resources(scheduler=scheduler,parent_lease=parent_lease,cancel_event=cancel_event,
            timeout_seconds=duration_seconds,memory_mb=memory_mb) as lease:
        signal=lease.combined_cancellation_signal(cancel_event)
        source=shards.load_repository_shards(index,root_cid)
        head=CodebaseHead.from_dict(source['source_head']);policy=CodebaseScanPolicy.from_dict(source['source_policy'])
        remaining=deadline-time.monotonic()
        require(remaining>0 and not signal.is_set(),'watcher preparation consumed deadline or was cancelled')
        verify_policy_current(index,repository,expected_head=head,receipt_cid=source['policy_receipt_cid'],
            parent_lease=lease,cancel_event=signal,timeout_seconds=remaining,memory_mb=memory_mb)
        scanner=BoundedScanner()
        watcher=RepositoryWatch(repository,notified,scanner=scanner,debounce_ms=0,poll_interval_ms=poll_interval_ms)
        try:
            watcher.start()
            while not stopped.is_set() and time.monotonic()<deadline and not signal.is_set():stopped.wait(.02)
        finally:
            # Existing native Git operations have their own fixed timeout.
            # Drain the bounded scan; don't leave a watcher using a released lease.
            watcher.stop(join_timeout_s=float(GIT_COMMAND_TIMEOUT_SECONDS)+duration_seconds+3)
            require(not watcher.is_running,'bounded watcher failed to drain before releasing its lease')
        return dict(schema='codebase-repository-shard-watch@1',source_root_cid=root_cid,hints=notifications,
            coalesced_notifications=coalesced,scans=scanner.scans,maximum_scans=maximum_scans,
            maximum_notifications=maximum_notifications,cancelled=signal.is_set(),watcher_drained=True,
            last_scan_error=None if watcher.last_scan_error is None else str(watcher.last_scan_error),
            authority='notification_only_requires_new_capture_admission',**shards.FALSE)


__all__=['watch_repository_shards']
