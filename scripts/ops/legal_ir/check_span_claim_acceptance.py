#!/usr/bin/env python3
"""Run the complete private-native T02 engineering gate, with no admission."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.logic.autoformal.span_claim_acceptance import (
    FALSE, SpanClaimAcceptanceError, digest, load_json, need, raw, run_private_checks,
    validate_lease,
)

LEASE_ENV = "IPFS_DATASETS_T02_VALIDATION_LEASE_ID"
STATE_ENV = "IPFS_DATASETS_T02_SCHEDULER_STATE"
POLICY_ENV = "IPFS_DATASETS_T02_SCHEDULER_POLICY_SHA256"
REQUEST_PREFIX = "legal-ir-supervisor-start:gap-T02-"


@contextmanager
def cleanup_on_sigterm():
    """Route external cancellation through the owned-child cleanup path."""
    previous = signal.getsignal(signal.SIGTERM)

    def interrupted(signum, frame):
        # A repeated cancellation must not interrupt the bounded TERM/KILL
        # cleanup already unwinding run_private_checks and its private runtime.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise SpanClaimAcceptanceError("native checker interrupted by SIGTERM")

    signal.signal(signal.SIGTERM, interrupted)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def ancestors():
    """Observe real Linux process ancestry, not caller-supplied owner IDs."""
    pid, seen = os.getpid(), set()
    for _ in range(64):
        if pid <= 1 or pid in seen:
            return seen
        seen.add(pid)
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        pid = int(fields[1])
    raise SpanClaimAcceptanceError("process ancestry exceeds bound")


class NativeValidationLeaseVerifier:
    """Observe an existing native lease; never reserve, renew or reset it."""

    def __init__(self, state_path, expected_policy):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native
        need(Path(native.__file__).resolve().is_relative_to(ROOT), "native scheduler import escaped producer tree")
        self.path = Path(state_path).resolve()
        need(self.path.is_file() and not Path(state_path).is_symlink(), "existing scheduler state required")
        self.lease_id = os.environ.get(LEASE_ENV, "")
        need(self.lease_id, "explicit externally granted T02 validation lease ID required")
        initial = load_json(self.path.read_bytes())
        self.original = deepcopy(initial["config"])
        need(digest(self.original) == expected_policy, "native scheduler policy identity differs")
        self.policy = expected_policy
        original = self.original

        class PinnedScheduler(native.GlobalResourceScheduler):
            def _new_state(self):
                raise native.SchedulerStateError("existing native scheduler disappeared")

            def _validate_state_configuration(self, state, *, allow_reconfigure=False):
                stored = deepcopy(state.get("config"))
                if stored != original:
                    raise native.ResourceConfigurationError("native scheduler policy changed")
                super()._validate_state_configuration(state, allow_reconfigure=False)
                state["config"] = stored

        config = native.ResourceSchedulerConfig(state_path=self.path, **self.original)
        need(config.proof_safety_enabled and config.reservations()["validation"].cpu_slots >= 1,
            "native proof-safety validation reserve required")
        self.scheduler = PinnedScheduler(config)

    def verify(self):
        need(load_json(self.path.read_bytes())["config"] == self.original, "native scheduler policy changed")
        records = [record for record in self.scheduler.active_leases() if record["lease_id"] == self.lease_id]
        need(len(records) == 1 and not self.scheduler.is_cancelled(self.lease_id, missing_is_cancelled=True),
            "selected native validation lease is absent, cancelled, expired or released")
        lease = records[0]
        need(lease["owner_pid"] in ancestors() and lease["lane"] == "validation"
            and lease["request_id"].startswith(REQUEST_PREFIX), "native lease owner or request scope differs")
        need(type(lease["expires_at"]) in (int, float) and lease["expires_at"] > time.time(),
            "native validation lease expired")
        return validate_lease(dict(lease_id=self.lease_id, policy_sha256=self.policy,
            lane=lease["lane"], owner_pid=lease["owner_pid"], request_id=lease["request_id"],
            cpu_slots=lease["cpu_slots"], memory_mb=lease["memory_mb"], child_process_slots=lease["child_process_slots"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--scheduler-state", type=Path)
    parser.add_argument("--expected-policy-sha256")
    args = parser.parse_args(argv)
    try:
        with cleanup_on_sigterm():
            manifest = load_json(args.manifest.read_bytes())
            state = args.scheduler_state or os.environ.get(STATE_ENV, "")
            policy = args.expected_policy_sha256 or os.environ.get(POLICY_ENV, "")
            need(state and policy, "explicit native scheduler state and expected policy required")
            verifier = NativeValidationLeaseVerifier(state, policy)
            checked = run_private_checks(ROOT, manifest, args.output, lease_verifier=verifier)
        print(json.dumps(checked, sort_keys=True))
        return 0
    except (SpanClaimAcceptanceError, OSError, ValueError, KeyError) as error:
        # Failure output is a refusal, not a fabricated positive native result.
        refusal = dict(status="blocked_engineering_checker", reason=str(error), **FALSE)
        print(json.dumps(refusal, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
