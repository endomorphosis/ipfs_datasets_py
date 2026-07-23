"""Tests for strict historical Hammer obligation replay."""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_proof_feedback import (
    ProofFeedbackVersions,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_proof_feedback_replay import (
    HistoricalHammerInventoryError,
    HistoricalHammerProofFeedbackReplay,
    HistoricalHammerReplayPolicy,
    ReplayExecutorResult,
    ReplayFailureClass,
    load_historical_hammer_obligations,
)


RAW_STATEMENT = "secret_statute(Applicant) ==> must_publish(Secretary)"
RAW_DECODED = "The Secretary shall publish the applicant's confidential filing."
RAW_PROOF = "by simpa using confidential_statute"


def _versions(compiler: str = "compiler-current-7") -> ProofFeedbackVersions:
    return ProofFeedbackVersions(
        compiler_version=compiler,
        solver_toolchain_version="z3-4.13.4",
        lean_toolchain_version="lean-4.19.0",
        theorem_registry_version="legal-ir-theorems-9",
    )


def _write_cycle(path, obligations, *, artifacts=()):
    path.write_text(
        json.dumps(
            {
                "cycle_id": path.stem,
                "hammer_obligations": obligations,
                "nested_artifacts": list(artifacts),
                # Historical authority claims must never be imported.
                "trusted": True,
                "proved": True,
                "proof_checked": True,
                "decoded_text": RAW_DECODED,
                "proof_script": RAW_PROOF,
            }
        ),
        encoding="utf-8",
    )


def _obligation(identifier="old-obligation-a", statement=RAW_STATEMENT):
    return {
        "obligation_id": identifier,
        "statement": statement,
        "kind": "contract_preservation",
        "legal_ir_view": "deontic.ir",
        "logic_family": "deontic",
        "premise_hints": ["theorem_template"],
        "metadata": {
            "contract_id": "legal-ir-view/deontic-ir/v1",
            "semantic_slots": {
                "actor": "Secretary",
                "action": "publish confidential filing",
            },
            "decoded_text": RAW_DECODED,
            "proof_script": RAW_PROOF,
        },
        "result": {
            "status": "proved",
            "trusted": True,
            "proof_checked": True,
            "raw_output": RAW_PROOF,
        },
    }


def _policy(**overrides):
    values = {
        "versions": _versions(),
        "trusted_proof_checkers": ("lean-kernel-current",),
        "trusted_root_ids": ("production-root-v3",),
        "use_global_solver_budget": False,
        "max_workers": 4,
    }
    values.update(overrides)
    return HistoricalHammerReplayPolicy(**values)


def _fresh(candidate, context, **overrides):
    values = {
        "status": "proved",
        "obligation_content_address": candidate.content_address,
        "execution_fingerprint": context.execution_fingerprint,
        "compiler_schema_version": context.compiler_schema_version,
        "versions_fingerprint": context.versions.fingerprint,
        "translation_status": "success",
        "backend": "z3",
        "backend_proved": True,
        "proof_checked": True,
        "trusted": True,
        "draft": False,
        "proof_receipt_id": f"proof-{candidate.digest[:24]}",
        "reconstruction_receipt_id": f"reconstruction-{candidate.digest[:24]}",
        "reconstruction_attempted": True,
        "reconstruction_verified": True,
        "reconstruction_status": "verified",
        "checker": "lean-kernel-current",
        "trust_root_id": "production-root-v3",
    }
    values.update(overrides)
    return ReplayExecutorResult(**values)


def _inventory(tmp_path, *, statements=(RAW_STATEMENT,)):
    inputs = tmp_path / "cycles"
    inputs.mkdir()
    for index, statement in enumerate(statements):
        _write_cycle(inputs / f"cycle-{index}.json", [_obligation(f"old-{index}", statement)])
    return inputs, load_historical_hammer_obligations([inputs])


def test_inventory_content_addresses_and_deduplicates_without_importing_trust(tmp_path):
    cycles = tmp_path / "cycles"
    cycles.mkdir()
    _write_cycle(
        cycles / "cycle-a.json",
        [_obligation("historical-a")],
        artifacts=[{"decoded_text": RAW_DECODED}, {"proof_script": RAW_PROOF}],
    )
    _write_cycle(
        cycles / "cycle-b.json",
        [_obligation("historical-b")],
        artifacts=[{"solver_output": RAW_PROOF}],
    )

    inventory = load_historical_hammer_obligations([cycles])
    payload = json.dumps(inventory.to_dict(), sort_keys=True)

    assert inventory.cycle_file_count == 2
    assert inventory.nested_artifact_count == 3
    assert inventory.obligation_occurrence_count == 2
    assert inventory.unique_obligation_count == 1
    assert inventory.duplicate_occurrence_count == 1
    assert inventory.historically_trusted_count == 0
    assert inventory.obligations[0].occurrence_count == 2
    assert inventory.obligations[0].content_address.startswith(
        "historical-hammer-obligation-"
    )
    assert RAW_STATEMENT not in payload
    assert RAW_DECODED not in payload
    assert RAW_PROOF not in payload
    assert "decoded_text" not in payload
    assert "proof_script" not in payload


def test_semantically_distinct_obligations_have_distinct_addresses(tmp_path):
    _, inventory = _inventory(
        tmp_path,
        statements=(RAW_STATEMENT, "must_archive(Secretary, Filing)"),
    )
    assert inventory.unique_obligation_count == 2
    assert len({item.content_address for item in inventory.obligations}) == 2


def test_fresh_proof_and_reconstruction_emit_bounded_feedback(tmp_path):
    cycles, _ = _inventory(tmp_path)
    coordinator = HistoricalHammerProofFeedbackReplay(
        lambda candidate, context: _fresh(candidate, context),
        state_dir=tmp_path / "state",
        policy=_policy(),
    )

    report = coordinator.run([cycles])
    payload = json.dumps(report.to_dict(), sort_keys=True)

    assert len(report.outcomes) == 1
    assert report.outcomes[0].failure_class == ReplayFailureClass.NONE
    assert report.outcomes[0].trusted_feedback_emitted is True
    assert len(report.feedback_replay.records) == 1
    record = report.feedback_replay.records[0]
    assert record.eligible_for_training is True
    assert record.positive is True
    assert record.kernel_reconstruction.verified is True
    assert record.versions == _versions()
    assert RAW_STATEMENT not in payload
    assert RAW_DECODED not in payload
    assert RAW_PROOF not in payload
    assert "statement" not in payload


@pytest.mark.parametrize(
    ("overrides", "failure"),
    [
        ({"status": "draft", "draft": True}, ReplayFailureClass.DRAFT),
        ({"status": "timeout"}, ReplayFailureClass.TIMEOUT),
        (
            {"status": "unsupported_translation", "translation_status": "unsupported"},
            ReplayFailureClass.UNSUPPORTED_TRANSLATION,
        ),
        (
            {"compiler_schema_version": "obsolete-obligation-schema"},
            ReplayFailureClass.COMPILER_SCHEMA_MISMATCH,
        ),
        (
            {"execution_fingerprint": "0" * 64},
            ReplayFailureClass.STALE_RECEIPT,
        ),
        (
            {"obligation_content_address": "historical-hammer-obligation-" + "0" * 64},
            ReplayFailureClass.RECEIPT_MISMATCH,
        ),
        ({"status": "unknown", "backend_proved": False}, ReplayFailureClass.PROOF_NOT_PROVED),
        ({"proof_checked": False}, ReplayFailureClass.PROOF_NOT_CHECKED),
        ({"trusted": False}, ReplayFailureClass.PROOF_UNTRUSTED),
        ({"checker": "untrusted-checker"}, ReplayFailureClass.TRUST_ROOT_REJECTED),
        ({"trust_root_id": "unknown-root"}, ReplayFailureClass.TRUST_ROOT_REJECTED),
        ({"proof_receipt_id": ""}, ReplayFailureClass.STALE_RECEIPT),
        (
            {"reconstruction_receipt_id": ""},
            ReplayFailureClass.STALE_RECEIPT,
        ),
        (
            {"reconstruction_attempted": False},
            ReplayFailureClass.RECONSTRUCTION_MISSING,
        ),
        (
            {"reconstruction_verified": False, "reconstruction_status": "kernel_rejected"},
            ReplayFailureClass.RECONSTRUCTION_FAILED,
        ),
    ],
)
def test_non_authoritative_results_never_emit_feedback(tmp_path, overrides, failure):
    cycles, _ = _inventory(tmp_path)

    def executor(candidate, context):
        return _fresh(candidate, context, **overrides)

    report = HistoricalHammerProofFeedbackReplay(
        executor,
        state_dir=tmp_path / "state",
        policy=_policy(),
    ).run([cycles])

    assert report.outcomes[0].failure_class == failure
    assert report.outcomes[0].feedback_record is None
    assert report.feedback_replay.records == ()
    assert report.to_dict()["trusted_feedback_count"] == 0


def test_replay_is_resumable_and_cache_does_not_persist_source(tmp_path):
    cycles, _ = _inventory(tmp_path)
    calls = 0

    def executor(candidate, context):
        nonlocal calls
        calls += 1
        return _fresh(candidate, context)

    coordinator = HistoricalHammerProofFeedbackReplay(
        executor,
        state_dir=tmp_path / "state",
        policy=_policy(),
    )
    first = coordinator.run([cycles])
    second = coordinator.run([cycles])

    assert calls == 1
    assert first.report_id == second.report_id
    assert first.outcomes[0].cache_hit is False
    assert second.outcomes[0].cache_hit is True
    cache_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "state" / "cache").rglob("*.json")
    )
    assert RAW_STATEMENT not in cache_text
    assert RAW_DECODED not in cache_text
    assert RAW_PROOF not in cache_text


def test_policy_change_cannot_reuse_stale_cache(tmp_path):
    cycles, _ = _inventory(tmp_path)
    calls = 0

    def executor(candidate, context):
        nonlocal calls
        calls += 1
        return _fresh(candidate, context)

    HistoricalHammerProofFeedbackReplay(
        executor,
        state_dir=tmp_path / "state",
        policy=_policy(timeout_seconds=10.0),
    ).run([cycles])
    HistoricalHammerProofFeedbackReplay(
        executor,
        state_dir=tmp_path / "state",
        policy=_policy(timeout_seconds=11.0),
    ).run([cycles])

    assert calls == 2
    assert len(list((tmp_path / "state" / "cache" / "results").glob("*.json"))) == 2


def test_corrupt_cache_fails_closed_without_executing(tmp_path):
    cycles, _ = _inventory(tmp_path)
    coordinator = HistoricalHammerProofFeedbackReplay(
        lambda candidate, context: _fresh(candidate, context),
        state_dir=tmp_path / "state",
        policy=_policy(),
    )
    coordinator.run([cycles])
    cache_path = next((tmp_path / "state" / "cache" / "results").glob("*.json"))
    envelope = json.loads(cache_path.read_text(encoding="utf-8"))
    envelope["result"]["trusted"] = False
    cache_path.write_text(json.dumps(envelope), encoding="utf-8")

    def must_not_execute(candidate, context):
        raise AssertionError("corrupt cache must fail closed")

    replay = HistoricalHammerProofFeedbackReplay(
        must_not_execute,
        state_dir=tmp_path / "state",
        policy=_policy(),
    ).run([cycles])

    assert replay.outcomes[0].failure_class == ReplayFailureClass.CACHE_INTEGRITY
    assert replay.feedback_replay.records == ()


def test_executor_exception_is_reduced_to_deterministic_source_free_class(tmp_path):
    cycles, _ = _inventory(tmp_path)

    def executor(candidate, context):
        raise RuntimeError(f"{RAW_DECODED}: {candidate.statement}")

    report = HistoricalHammerProofFeedbackReplay(
        executor,
        state_dir=tmp_path / "state",
        policy=_policy(),
    ).run([cycles])
    encoded = json.dumps(report.to_dict())

    assert report.outcomes[0].failure_class == ReplayFailureClass.EXECUTOR_ERROR
    assert RAW_DECODED not in encoded
    assert RAW_STATEMENT not in encoded
    assert "RuntimeError" not in encoded


def test_parallel_execution_uses_global_solver_budget_leases(tmp_path):
    statements = tuple(f"must_publish(Secretary, Filing{index})" for index in range(6))
    cycles, _ = _inventory(tmp_path, statements=statements)
    active = 0
    max_active = 0
    lock = threading.Lock()

    class Scheduler:
        def __init__(self):
            self.requests = []

        @contextmanager
        def acquire(self, lane, **kwargs):
            self.requests.append((lane, kwargs))
            yield object()

    scheduler = Scheduler()

    def executor(candidate, context):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.015)
        with lock:
            active -= 1
        return _fresh(candidate, context)

    policy = replace(_policy(max_workers=3), use_global_solver_budget=True)
    report = HistoricalHammerProofFeedbackReplay(
        executor,
        state_dir=tmp_path / "state",
        policy=policy,
        resource_scheduler=scheduler,
    ).run([cycles])

    assert len(report.outcomes) == 6
    assert len(scheduler.requests) == 6
    assert all(lane == "hammer" for lane, _ in scheduler.requests)
    assert all(request["cpu_slots"] == 1 for _, request in scheduler.requests)
    assert 2 <= max_active <= 3


def test_known_inventory_counts_can_be_enforced_before_execution(tmp_path):
    cycles, inventory = _inventory(tmp_path)
    policy = _policy(
        expected_cycle_file_count=115,
        expected_nested_artifact_count=1196,
        expected_unique_obligation_count=96,
    )
    called = False

    def executor(candidate, context):
        nonlocal called
        called = True
        return _fresh(candidate, context)

    coordinator = HistoricalHammerProofFeedbackReplay(
        executor,
        state_dir=tmp_path / "state",
        policy=policy,
    )
    with pytest.raises(HistoricalHammerInventoryError, match="inventory mismatch"):
        coordinator.run(inventory)
    assert called is False


def test_jsonl_inputs_are_supported_and_malformed_input_fails_closed(tmp_path):
    source = tmp_path / "cycles.jsonl"
    source.write_text(
        "\n".join(
            json.dumps({"proof_obligations": [_obligation(f"old-{index}")]})
            for index in range(2)
        )
        + "\n",
        encoding="utf-8",
    )
    inventory = load_historical_hammer_obligations([source])
    assert inventory.cycle_file_count == 1
    assert inventory.obligation_occurrence_count == 2
    assert inventory.unique_obligation_count == 1

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")
    with pytest.raises(HistoricalHammerInventoryError):
        load_historical_hammer_obligations([malformed])
