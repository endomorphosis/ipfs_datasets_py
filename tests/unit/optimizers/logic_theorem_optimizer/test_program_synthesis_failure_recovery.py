"""Tests for classified, bounded program-synthesis failure recovery."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.program_synthesis_failures import (
    DEFAULT_FAILURE_POLICIES,
    FailureCategory,
    FailureEvidenceStore,
    FailureObservation,
    FailureRateReporter,
    ProgramSynthesisFailureClassifier,
    ProgramSynthesisFailureRecovery,
    RecoveryOperations,
    RecoveryLedger,
    RecoveryStatus,
)


@pytest.mark.parametrize(
    ("observation", "expected"),
    [
        (
            FailureObservation(task_id="transport", exception=ConnectionError("connection reset")),
            FailureCategory.TRANSPORT,
        ),
        (
            FailureObservation(task_id="timeout", exec_status="timeout"),
            FailureCategory.PROVIDER_TIMEOUT,
        ),
        (
            FailureObservation(task_id="malformed", message="invalid JSON response"),
            FailureCategory.MALFORMED_RESPONSE,
        ),
        (
            FailureObservation(
                task_id="empty", patch_status="awaiting_codex_changes", patch=""
            ),
            FailureCategory.EMPTY_PATCH,
        ),
        (
            FailureObservation(task_id="conflict", message="git apply --check failed"),
            FailureCategory.APPLY_CONFLICT,
        ),
        (
            FailureObservation(
                task_id="stale", base_revision="old", current_revision="new",
                message="git apply failed",
            ),
            FailureCategory.STALE_BASE,
        ),
        (
            FailureObservation(
                task_id="scope", changed_files=("private/secret.py",),
                allowed_paths=("src/",),
            ),
            FailureCategory.SCOPE_VIOLATION,
        ),
        (
            FailureObservation(task_id="test", validation_status="failed"),
            FailureCategory.DETERMINISTIC_TEST_FAILURE,
        ),
        (
            FailureObservation(task_id="metric", metric_status="regressed"),
            FailureCategory.METRIC_REGRESSION,
        ),
        (
            FailureObservation(task_id="resource", exception=MemoryError("OOM")),
            FailureCategory.RESOURCE_EXHAUSTION,
        ),
        (
            FailureObservation(task_id="interrupt", exception=KeyboardInterrupt()),
            FailureCategory.SUPERVISOR_INTERRUPTION,
        ),
    ],
)
def test_classifier_covers_complete_taxonomy(observation, expected) -> None:
    result = ProgramSynthesisFailureClassifier().classify(observation)

    assert result.category is expected
    assert result.policy is DEFAULT_FAILURE_POLICIES[expected]
    assert len(result.fingerprint) == 24


def test_classifier_precedence_fails_closed_for_scope_metric_and_stale_base() -> None:
    classifier = ProgramSynthesisFailureClassifier()

    scope = classifier.classify(
        FailureObservation(
            task_id="scope-first", exec_status="timeout",
            changed_files=("unowned.py",), allowed_paths=("owned/**",),
        )
    )
    metric = classifier.classify(
        FailureObservation(
            task_id="metric-first", metric_status="regressed",
            validation_status="failed",
        )
    )
    stale = classifier.classify(
        FailureObservation(
            task_id="stale-first", base_revision="a", current_revision="b",
            apply_status="failed",
        )
    )

    assert scope.category is FailureCategory.SCOPE_VIOLATION
    assert scope.out_of_scope_files == ("unowned.py",)
    assert metric.category is FailureCategory.METRIC_REGRESSION
    assert stale.category is FailureCategory.STALE_BASE


def test_from_packet_extracts_daemon_failure_evidence(tmp_path: Path) -> None:
    packet_path = tmp_path / "packet.json"
    packet_path.write_text("{}\n", encoding="utf-8")
    packet = {
        "packet_id": "packet-7",
        "packet_path": str(packet_path),
        "program_synthesis_scopes": ["deontic.compiler"],
        "todos": [{"todo_id": "todo-7"}],
        "codex_exec": {"status": "timeout", "attempt_count": 2},
        "patch_status": "patch_generation_failed",
    }

    observation = FailureObservation.from_packet(packet)
    result = ProgramSynthesisFailureClassifier().classify(packet)

    assert observation.task_id == "todo-7"
    assert observation.scope == "deontic.compiler"
    assert observation.attempt == 2
    assert observation.artifacts == (str(packet_path),)
    assert result.category is FailureCategory.PROVIDER_TIMEOUT

    generic = ProgramSynthesisFailureClassifier().classify(
        {"task_id": "generic", "scope": "cec", "error": "connection refused"}
    )
    assert generic.category is FailureCategory.TRANSPORT


def test_packet_classifier_reads_bounded_diagnostic_artifacts(tmp_path: Path) -> None:
    stderr = tmp_path / "stderr.log"
    stderr.write_text("x" * 70_000 + "\nconnection reset by peer\n", encoding="utf-8")
    classifier = ProgramSynthesisFailureClassifier()

    result = classifier.classify(
        {
            "packet_id": "packet-log",
            "codex_exec": {"status": "failed", "stderr_path": str(stderr)},
            "patch_status": "patch_generation_failed",
        }
    )
    lock_result = classifier.classify(
        {"packet_id": "packet-lock", "patch_status": "main_apply_lock_timeout"}
    )

    assert result.category is FailureCategory.TRANSPORT
    assert lock_result.category is FailureCategory.RESOURCE_EXHAUSTION


def test_category_retry_is_bounded_and_every_attempt_preserves_evidence(tmp_path: Path) -> None:
    calls = []
    recovery = ProgramSynthesisFailureRecovery(
        tmp_path / "evidence",
        ledger_path=tmp_path / "ledger.json",
        operations=RecoveryOperations(
            retry=lambda context: calls.append(context) or {"status": "scheduled"}
        ),
        max_same_fingerprint=10,
    )
    observation = FailureObservation(
        task_id="timeout-task", scope="tdfol", exec_status="timeout",
        message="provider timeout",
    )

    first = recovery.handle(observation)
    second = recovery.handle(observation)
    terminal = recovery.handle(observation)

    assert [first.status, second.status] == [
        RecoveryStatus.RETRY_SCHEDULED,
        RecoveryStatus.RETRY_SCHEDULED,
    ]
    assert [context.retry_number for context in calls] == [1, 2]
    assert [context.retry_after_seconds for context in calls] == [5.0, 20.0]
    assert terminal.status is RecoveryStatus.TERMINAL
    assert terminal.reason == "category_retry_budget_exhausted"
    assert len(calls) == 2
    evidence_files = sorted((tmp_path / "evidence").rglob("*.json"))
    assert len(evidence_files) == 3
    assert all(
        json.loads(path.read_text())["classification"]["transient"]
        for path in evidence_files
    )


def test_stale_base_rebases_and_conflict_rescues_worktree(tmp_path: Path) -> None:
    actions = []

    def rebase(context):
        actions.append(("rebase", context.observation.task_id, context.evidence_path.exists()))
        return {"status": "rebased", "new_base": "main-2"}

    def rescue(context):
        actions.append(("rescue", context.observation.task_id, context.evidence_path.exists()))
        return {"status": "rescued", "worktree": "rescue-tree"}

    recovery = ProgramSynthesisFailureRecovery(
        tmp_path / "evidence",
        operations=RecoveryOperations(rebase=rebase, rescue=rescue),
    )

    stale = recovery.handle(
        FailureObservation(
            task_id="stale-task", scope="compiler", base_revision="1", current_revision="2"
        )
    )
    conflict = recovery.handle(
        FailureObservation(task_id="conflict-task", scope="compiler", message="apply conflict")
    )

    assert stale.status is RecoveryStatus.REBASED
    assert conflict.status is RecoveryStatus.RESCUED
    assert actions == [
        ("rebase", "stale-task", True),
        ("rescue", "conflict-task", True),
    ]


def test_failed_rebase_falls_back_to_rescue(tmp_path: Path) -> None:
    actions = []
    recovery = ProgramSynthesisFailureRecovery(
        tmp_path / "evidence",
        operations=RecoveryOperations(
            rebase=lambda context: actions.append("rebase") or {"status": "conflict"},
            rescue=lambda context: actions.append("rescue") or {"status": "rescued"},
        ),
    )

    outcome = recovery.handle(
        FailureObservation(
            task_id="fallback", base_revision="old", current_revision="head"
        )
    )

    assert actions == ["rebase", "rescue"]
    assert outcome.status is RecoveryStatus.RESCUED
    assert outcome.action_result["primary_action"] == "rebase"
    assert outcome.action_result["fallback_action"] == "rescue"


def test_failed_evidence_copies_artifacts_before_recovery(tmp_path: Path) -> None:
    log = tmp_path / "codex-stderr.log"
    log.write_text("connection reset by peer\n", encoding="utf-8")
    store = FailureEvidenceStore(tmp_path / "evidence")
    classifier = ProgramSynthesisFailureClassifier()
    observation = FailureObservation(
        task_id="artifact-task", scope="kg", exception=ConnectionError("reset"),
        patch="diff --git a/a.py b/a.py\n", response={"bad": "partial"},
        artifacts=(log,), evidence={"packet": "packet-1"},
    )

    evidence_path = store.preserve(observation, classifier.classify(observation), sequence=1)
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert payload["observation"]["patch"].startswith("diff --git")
    assert payload["observation"]["response"] == {"bad": "partial"}
    artifact = payload["artifacts"][0]
    assert artifact["copied"] is True
    copied_path = Path(artifact["evidence_path"])
    assert copied_path.read_text(encoding="utf-8") == log.read_text(encoding="utf-8")
    log.write_text("later mutation", encoding="utf-8")
    assert copied_path.read_text(encoding="utf-8") == "connection reset by peer\n"


def test_poison_fingerprint_stops_loop_and_survives_restart(tmp_path: Path) -> None:
    calls = []
    ledger_path = tmp_path / "ledger.json"
    kwargs = {
        "ledger_path": ledger_path,
        "operations": RecoveryOperations(
            retry=lambda context: calls.append(context.retry_number) or True
        ),
        "max_same_fingerprint": 2,
        "max_task_failures": 20,
    }
    observation = FailureObservation(
        task_id="poison", scope="decompiler", exception=ConnectionError("same reset")
    )
    first_manager = ProgramSynthesisFailureRecovery(tmp_path / "evidence", **kwargs)

    assert first_manager.handle(observation).terminal is False
    assert first_manager.handle(observation).terminal is False

    restarted = ProgramSynthesisFailureRecovery(tmp_path / "evidence", **kwargs)
    blocked = restarted.handle(observation)

    assert blocked.status is RecoveryStatus.TERMINAL
    assert blocked.poison_blocked is True
    assert blocked.reason == "poison_task_loop_blocked"
    assert calls == [1, 2]


@pytest.mark.parametrize(
    "category",
    [
        FailureCategory.SCOPE_VIOLATION,
        FailureCategory.DETERMINISTIC_TEST_FAILURE,
        FailureCategory.METRIC_REGRESSION,
    ],
)
def test_terminal_failures_never_invoke_mutating_operations(tmp_path: Path, category) -> None:
    calls = []
    operations = RecoveryOperations(
        retry=lambda context: calls.append("retry"),
        rebase=lambda context: calls.append("rebase"),
        rescue=lambda context: calls.append("rescue"),
    )
    recovery = ProgramSynthesisFailureRecovery(tmp_path / "evidence", operations=operations)

    outcome = recovery.handle(
        FailureObservation(task_id=category.value, category_hint=category)
    )

    assert outcome.status is RecoveryStatus.TERMINAL
    assert outcome.reason == "non_retryable_category"
    assert calls == []


def test_supervisor_interruption_preserves_without_restart(tmp_path: Path) -> None:
    recovery = ProgramSynthesisFailureRecovery(
        tmp_path / "evidence",
        operations=RecoveryOperations(retry=lambda context: pytest.fail("must not restart")),
    )

    outcome = recovery.handle(
        FailureObservation(task_id="shutdown", supervisor_interrupted=True)
    )

    assert outcome.status is RecoveryStatus.INTERRUPTED
    assert outcome.terminal is False
    assert Path(outcome.evidence_path).exists()


def test_scoped_report_separates_transient_and_terminal_rates(tmp_path: Path) -> None:
    reporter = FailureRateReporter()
    recovery = ProgramSynthesisFailureRecovery(
        tmp_path / "evidence",
        reporter=reporter,
        operations=RecoveryOperations(retry=lambda context: True),
    )

    recovery.handle(
        FailureObservation(task_id="a", scope="compiler", exception=ConnectionError("reset"))
    )
    recovery.handle(
        FailureObservation(
            task_id="b", scope="compiler", category_hint=FailureCategory.METRIC_REGRESSION
        )
    )
    recovery.handle(
        FailureObservation(task_id="c", scope="kg", validation_status="failed")
    )
    report = recovery.failure_rate_report()

    compiler = report["scopes"]["compiler"]
    kg = report["scopes"]["kg"]
    assert compiler["failure_count"] == 2
    assert compiler["transient_failure_rate"] == 0.5
    assert compiler["terminal_failure_rate"] == 0.5
    assert compiler["category_counts"] == {"metric_regression": 1, "transport": 1}
    assert kg["transient_failure_rate"] == 0.0
    assert kg["terminal_failure_rate"] == 1.0
    assert report["overall"]["transient_failure_rate"] == pytest.approx(1 / 3)

    recovery.record_success("compiler", count=2)
    compiler_with_success = recovery.failure_rate_report()["scopes"]["compiler"]
    assert compiler_with_success["attempt_count"] == 4
    assert compiler_with_success["success_count"] == 2
    assert compiler_with_success["transient_failure_rate"] == 0.25
    assert compiler_with_success["terminal_failure_rate"] == 0.25


def test_invalid_action_result_is_terminal_and_reported(tmp_path: Path) -> None:
    recovery = ProgramSynthesisFailureRecovery(
        tmp_path / "evidence",
        operations=RecoveryOperations(retry=lambda context: "not a result"),
    )

    outcome = recovery.handle(
        FailureObservation(task_id="invalid", exception=ConnectionError("reset"))
    )

    assert outcome.status is RecoveryStatus.ACTION_FAILED
    assert outcome.terminal is True
    assert outcome.action_result["error"] == "invalid_action_result:str"


def test_shared_ledger_serializes_multiple_workers(tmp_path: Path) -> None:
    ledger_path = tmp_path / "shared-ledger.json"
    ledgers = [RecoveryLedger(ledger_path) for _ in range(20)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda ledger: ledger.record(
                    "parallel-task", FailureCategory.TRANSPORT, "same-fingerprint"
                ),
                ledgers,
            )
        )

    assert sorted(item[0] for item in results) == list(range(1, 21))
    snapshot = RecoveryLedger(ledger_path).snapshot()
    assert snapshot["sequence"] == 20
    assert snapshot["task_failures"]["parallel-task"] == 20


def test_recovery_types_are_available_from_optimizer_namespace() -> None:
    import ipfs_datasets_py.optimizers.logic_theorem_optimizer as optimizer

    assert optimizer.FailureCategory is FailureCategory
    assert optimizer.ProgramSynthesisFailureRecovery is ProgramSynthesisFailureRecovery
