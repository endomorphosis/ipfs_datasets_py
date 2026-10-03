"""Read-only live scope fencing for the frozen scan-policy owner."""
from __future__ import annotations

from pathlib import Path
import math
import time
from types import SimpleNamespace

from .codebase_resources import acquire_codebase_resources
from .codebase_git_operation import GitOperationError, GitScanOperation
from .codebase_ir import CodebaseScanLimits
from .codebase_scan_policy import (
    CodebaseScanPolicy, CodebaseScanPolicyError, load_policy_receipt,
    _external_ignore_scope, _repository_rule_paths,
)
from .content import cid_for_bytes


def verify_policy_current(index, repository, *, expected_head, receipt_cid,
        scheduler=None, parent_lease=None, cancel_event=None,
        timeout_seconds=120.0, memory_mb=512):
    """Join historical scope to current native source and exact ignore inputs.

    No source publication, fitting, checker execution or artifact write occurs.
    The scope helper's capture sink only computes the content identity; the
    historical receipt loader independently checks the previously stored bytes.
    Git metadata subprocesses keep their existing bounded process profiles.
    This point-in-time observation does not lock subsequent repository edits.
    """
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise CodebaseScanPolicyError("live scan timeout must be finite and positive")
    deadline = time.monotonic() + timeout_seconds
    try:
        with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
                cancel_event=cancel_event, timeout_seconds=min(30.0, timeout_seconds),
                memory_mb=memory_mb) as lease:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
                LeaseCancelledError, LeaseTimeoutError,
            )
            cancelled = lease.combined_cancellation_signal(cancel_event)
            def remaining():
                if cancelled.is_set():
                    raise LeaseCancelledError("live scan policy cancelled")
                duration = deadline - time.monotonic()
                if duration <= 0:
                    raise LeaseTimeoutError("live scan policy deadline expired")
                return duration
            remaining()
            root = Path(repository).resolve()
            receipt = load_policy_receipt(index, receipt_cid)
            if receipt["head"] != expected_head.to_dict():
                raise CodebaseScanPolicyError("scan policy receipt and expected source head differ")
            policy = CodebaseScanPolicy.from_dict(receipt["policy"])
            CodebaseScanLimits(policy.max_entries, policy.max_file_bytes).validate_reservation(memory_mb)
            identities = SimpleNamespace(artifacts=SimpleNamespace(put_bytes=cid_for_bytes))
            with GitScanOperation(root, checkpoint=remaining, cancellation=cancelled,
                                  max_file_bytes=policy.max_file_bytes, memory_mb=memory_mb):
                def scope():
                    remaining()
                    if (_external_ignore_scope(identities, root) != receipt["external_ignores"]
                            or _repository_rule_paths(root, policy) != receipt["repository_ignore_rules"]):
                        raise CodebaseScanPolicyError("current ignore/configuration scope differs from the frozen policy")
                    remaining()
                def observe():
                    duration = remaining()
                    index.observe_current(root, expected_head=expected_head, parent_lease=lease,
                        cancel_event=cancelled, timeout_seconds=duration,
                        admission_timeout_seconds=min(30.0, duration), memory_mb=memory_mb)
                scope()
                observe()
                scope()
                observe()
                remaining()
                return receipt
    except GitOperationError as error:
        raise CodebaseScanPolicyError(str(error)) from error


__all__ = ["verify_policy_current"]
