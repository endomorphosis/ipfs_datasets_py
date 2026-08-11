"""Concurrency, crash, corruption, and stall chaos tests (DQK-051).

Inject failures at claim, heartbeat, proof publication, graph/vector/wallet
batch, checkpoint, export, merge, backup, Quack response, and process death
boundaries; prove bounded recovery and no duplicate authority.

Acceptance coverage:

* Stale fences cannot publish
* No-progress and deadlock diagnoses are typed
* Recovery preserves dirty work and immutable evidence

Live DuckDB / Quack / network are never required. The hermetic harness lives in
``scripts/validation/validate_duckdb_quack_chaos.py``.
"""

from __future__ import annotations

import builtins
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()
_CHAOS_PATH = _REPO_ROOT / "scripts/validation/validate_duckdb_quack_chaos.py"


def _prefer_sealed_accelerate_checkout() -> None:
    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        for candidate in (
            Path(
                os.environ.get(
                    "IPFS_ACCELERATE_AGENT_ADMITTED_ACCELERATE_ROOT",
                    "",
                )
            ),
            _REPO_ROOT.parents[3] / "ipfs_accelerate_py"
            if len(_REPO_ROOT.parents) >= 4
            else Path(),
            Path("/home/barberb/lift_coding/.worktrees/ipfs-datasets-duckdb-quack")
            / "ipfs_accelerate_py",
        ):
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            runtime = (
                resolved
                / "ipfs_accelerate_py"
                / "agent_supervisor"
                / "validation_runtime.py"
            )
            if runtime.is_file():
                accelerate_paths.append(resolved)
                break
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_chaos_module() -> ModuleType:
    """Load the validation script without requiring scripts.validation package."""

    module_name = "validate_duckdb_quack_chaos"
    existing = sys.modules.get(module_name)
    if existing is not None and getattr(existing, "CONTRACT_TASK_ID", None) == "DQK-051":
        return existing
    spec = importlib.util.spec_from_file_location(module_name, _CHAOS_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load chaos module from {_CHAOS_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


chaos = _load_chaos_module()


# ---------------------------------------------------------------------------
# Import-time safety
# ---------------------------------------------------------------------------


def test_chaos_module_import_is_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = {"duckdb", "duckdb.experimental"}
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".", 1)[0]
        if root in forbidden or name in forbidden:
            raise AssertionError(f"import of {name!r} is forbidden at module import")
        return real_import(name, globals, locals, fromlist, level)

    sys.modules.pop("validate_duckdb_quack_chaos", None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    mod = _load_chaos_module()
    assert mod.CHAOS_CONTRACT_SCHEMA.startswith("ipfs_datasets_py/")
    assert mod.CONTRACT_TASK_ID == "DQK-051"
    assert mod.PROGRAM_ID == "ipfs-datasets-duckdb-quack-v1"


def test_install_check_pins_boundaries_and_typed_diagnoses() -> None:
    report = chaos.install_check()
    assert report["ok"] is True
    assert report["owner_task_id"] == "DQK-051"
    assert set(report["failure_boundaries"]) == set(chaos.FAILURE_BOUNDARIES)
    assert set(chaos.FAILURE_BOUNDARIES) == {
        "claim",
        "heartbeat",
        "proof_publication",
        "graph_batch",
        "vector_batch",
        "wallet_batch",
        "checkpoint",
        "export",
        "merge",
        "backup",
        "quack_response",
        "process_death",
    }
    assert "no_progress" in report["typed_required_diagnoses"]
    assert "deadlock" in report["typed_required_diagnoses"]
    assert report["max_recovery_steps"] == chaos.MAX_RECOVERY_STEPS


# ---------------------------------------------------------------------------
# Acceptance: stale fences cannot publish
# ---------------------------------------------------------------------------


def test_stale_fences_cannot_publish() -> None:
    result = chaos.prove_stale_fences_cannot_publish()
    assert result["ok"] is True
    assert result["stale_fence_blocked"] is True
    assert result["expired_fence_blocked"] is True
    assert result["coordinator_expired_blocked"] is True
    assert result["follower_blocked"] is True
    assert result["duplicate_publish_blocked"] is True


def test_harness_stale_and_foreign_fence_publish_rejected() -> None:
    plane = chaos.ChaosControlPlane(lease_seconds=10.0)
    fence = plane.claim_fence("k1", owner_id="owner")
    foreign = chaos.FenceState(
        fence_id=fence.fence_id,
        owner_id="intruder",
        generation=fence.generation,
        token="tok:deadbeefdeadbeef",
        expires_at=fence.expires_at,
    )
    with pytest.raises(chaos.StalePublishError, match="stale"):
        plane.publish_authority("k1", {"v": 1}, foreign)

    # Successful publish then re-use of same fence is stale.
    plane.publish_authority(
        "k1",
        {"v": 1},
        fence,
        evidence_label="auth-1",
    )
    with pytest.raises(chaos.StalePublishError):
        plane.publish_authority("k1-again", {"v": 2}, fence)

    # Duplicate key authority blocked even with a fresh fence.
    fence2 = plane.claim_fence("k1", owner_id="owner-2")
    # k1 already published — claim may supersede fence but publish of same key
    # is still blocked when we try a new key first then duplicate.
    plane2 = chaos.ChaosControlPlane()
    f = plane2.claim_fence("dup-key", owner_id="a")
    plane2.publish_authority("dup-key", {"n": 1}, f, evidence_label="d1")
    f2 = plane2.claim_fence("other", owner_id="b")
    # Directly inject a second authority attempt for same key via map guard.
    with pytest.raises(chaos.DuplicateAuthorityError):
        # Force past fence by using a new live fence but same published key.
        plane2._published_keys.add("dup-key")  # already present
        plane2.publish_authority("dup-key", {"n": 2}, f2)


# ---------------------------------------------------------------------------
# Acceptance: no-progress and deadlock diagnoses are typed
# ---------------------------------------------------------------------------


def test_no_progress_and_deadlock_diagnoses_are_typed() -> None:
    result = chaos.prove_typed_no_progress_and_deadlock()
    assert result["ok"] is True
    assert result["deadlock_kind"] == "deadlock"
    assert result["no_progress_kind"] == "no_progress"
    assert "deadlock" in result["typed_kinds"]
    assert "no_progress" in result["typed_kinds"]


def test_diagnosis_kind_is_closed_enum() -> None:
    plane = chaos.ChaosControlPlane()
    d1 = plane.diagnose(chaos.DiagnosisKind.DEADLOCK, reason="cycle")
    d2 = plane.diagnose(chaos.DiagnosisKind.NO_PROGRESS, reason="stall")
    assert d1.kind is chaos.DiagnosisKind.DEADLOCK
    assert d2.kind is chaos.DiagnosisKind.NO_PROGRESS
    assert d1.to_dict()["schema"] == chaos.DIAGNOSIS_SCHEMA
    assert d2.to_dict()["kind"] == "no_progress"
    with pytest.raises(chaos.ChaosError, match="unknown diagnosis"):
        plane.diagnose("not_a_real_kind")


def test_wait_for_cycle_emits_typed_deadlock() -> None:
    plane = chaos.ChaosControlPlane()
    plane.set_wait_edge("a", "b")
    plane.set_wait_edge("b", "c")
    plane.set_wait_edge("c", "a")
    diag = plane.detect_deadlock()
    assert diag is not None
    assert diag.kind is chaos.DiagnosisKind.DEADLOCK
    assert "cycle" in diag.attributes


def test_stalled_progress_marker_emits_typed_no_progress() -> None:
    plane = chaos.ChaosControlPlane()
    seen: chaos.TypedDiagnosis | None = None
    for _ in range(chaos.NO_PROGRESS_THRESHOLD_STEPS + 2):
        seen = plane.observe_progress("merge-pipeline", sequence=7)
    assert seen is not None
    assert seen.kind is chaos.DiagnosisKind.NO_PROGRESS
    assert seen.kind.value == "no_progress"


# ---------------------------------------------------------------------------
# Acceptance: recovery preserves dirty work and immutable evidence
# ---------------------------------------------------------------------------


def test_recovery_preserves_dirty_work_and_immutable_evidence() -> None:
    result = chaos.prove_recovery_preserves_dirty_and_evidence()
    assert result["ok"] is True
    assert result["recovery_checkpoint_ok"] is True
    assert result["retention_blocked_referenced_evidence"] is True
    for item in result["boundary_results"]:
        assert item["evidence_preserved"] is True
        if item["crashed"]:
            assert item["dirty_preserved"] is True
            assert item["recovered"] is True


def test_inject_and_recover_preserves_seeded_evidence_per_boundary() -> None:
    for boundary in chaos.FailureBoundary:
        plane = chaos.ChaosControlPlane()
        seed = plane.register_evidence(
            f"seed-{boundary.value}",
            payload=f"seed-{boundary.value}".encode("utf-8"),
        )
        outcome = plane.inject_and_recover(
            boundary, operation_id=f"op:test:{boundary.value}"
        )
        assert seed.object_digest in plane.evidence_digests()
        assert outcome.evidence_preserved is True
        dirty_ids = {d.dirty_id for d in plane.dirty_records()}
        assert dirty_ids, f"{boundary.value}: dirty work missing after recovery"
        for entry in plane.journal():
            assert entry.diagnosis in chaos.DiagnosisKind
            assert seed.object_digest in entry.preserved_evidence_digests or (
                outcome.crashed and entry.action == "recover_dirty_and_evidence"
            )


# ---------------------------------------------------------------------------
# All failure boundaries: bounded recovery, no duplicate authority
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("boundary", list(chaos.FailureBoundary))
def test_inject_failure_at_boundary_recovers_without_duplicate_authority(
    boundary: Any,
) -> None:
    plane = chaos.ChaosControlPlane()
    result = plane.inject_and_recover(
        boundary, operation_id=f"op:param:{boundary.value}"
    )
    assert result.boundary is boundary
    assert result.steps <= chaos.MAX_RECOVERY_STEPS
    assert result.duplicate_authority is False
    if result.crashed:
        assert result.recovered is True
        assert result.dirty_preserved is True
        assert result.evidence_preserved is True
        assert result.diagnosis in {
            chaos.DiagnosisKind.CRASH_RECOVERED,
            chaos.DiagnosisKind.BOUNDED_RECOVERY,
            chaos.DiagnosisKind.EVIDENCE_PRESERVED,
            chaos.DiagnosisKind.DIRTY_WORK_PRESERVED,
        }
    # At most one authority record per key.
    keys = [a.key for a in plane._authority.values()]
    assert len(keys) == len(set(keys))


def test_bounded_recovery_no_duplicate_authority_suite() -> None:
    result = chaos.prove_bounded_recovery_no_duplicate_authority()
    assert result["ok"] is True
    assert list(result["boundaries"]) == list(chaos.FAILURE_BOUNDARIES)
    assert result["authority_dual_write_recovered"] is True
    for item in result["outcomes"]:
        assert item["steps"] <= chaos.MAX_RECOVERY_STEPS
        assert item["duplicate_authority"] is False


def test_unknown_boundary_rejected() -> None:
    plane = chaos.ChaosControlPlane()
    with pytest.raises(chaos.ChaosError, match="unknown failure boundary"):
        plane.set_crash_at("not_a_boundary")
    with pytest.raises(chaos.ChaosError, match="unknown failure boundary"):
        plane.inject_and_recover("not_a_boundary")


# ---------------------------------------------------------------------------
# Live module integration slices
# ---------------------------------------------------------------------------


def test_publication_stale_fence_and_quack_isolation() -> None:
    result = chaos.prove_publication_stale_fence_and_quack_isolation()
    assert result["ok"] is True
    assert result["stale_publication_rejected"] is True
    assert result["live_materialization_ok"] is True
    assert result["authority_catalogs_attached"] is False


def test_heartbeat_capacity_and_export_readonly() -> None:
    result = chaos.prove_heartbeat_capacity_and_export_readonly()
    assert result["ok"] is True
    assert result["heartbeat_samples"] >= 1
    assert result["heartbeat_within_slo"] is True
    assert result["export_read_only"] is True
    assert result["export_non_authoritative"] is True
    assert result["export_mutated_source"] is False


def test_graph_vector_wallet_batch_crash_and_recover() -> None:
    for domain in ("graph", "vector", "wallet"):
        plane = chaos.ChaosControlPlane()
        boundary = {
            "graph": chaos.FailureBoundary.GRAPH_BATCH,
            "vector": chaos.FailureBoundary.VECTOR_BATCH,
            "wallet": chaos.FailureBoundary.WALLET_BATCH,
        }[domain]
        result = plane.inject_and_recover(
            boundary, operation_id=f"op:batch:{domain}"
        )
        assert result.crashed is True
        assert result.recovered is True
        assert result.evidence_preserved is True
        assert any(
            d.boundary is boundary for d in plane.dirty_records()
        ) or any(
            d.key.startswith("pre-crash:") for d in plane.dirty_records()
        )


def test_checkpoint_export_merge_backup_quack_process_death() -> None:
    for boundary in (
        chaos.FailureBoundary.CHECKPOINT,
        chaos.FailureBoundary.EXPORT,
        chaos.FailureBoundary.MERGE,
        chaos.FailureBoundary.BACKUP,
        chaos.FailureBoundary.QUACK_RESPONSE,
        chaos.FailureBoundary.PROCESS_DEATH,
    ):
        plane = chaos.ChaosControlPlane()
        result = plane.inject_and_recover(
            boundary, operation_id=f"op:ops:{boundary.value}"
        )
        assert result.crashed is True, boundary.value
        assert result.recovered is True, boundary.value
        assert result.dirty_preserved is True, boundary.value
        assert result.evidence_preserved is True, boundary.value


def test_claim_and_heartbeat_boundaries() -> None:
    plane = chaos.ChaosControlPlane()
    claim = plane.inject_and_recover(
        chaos.FailureBoundary.CLAIM, operation_id="op:claim"
    )
    assert claim.crashed is True
    assert claim.recovered is True

    plane2 = chaos.ChaosControlPlane()
    hb = plane2.inject_and_recover(
        chaos.FailureBoundary.HEARTBEAT, operation_id="op:hb"
    )
    assert hb.crashed is True
    assert hb.recovered is True


def test_proof_publication_boundary_and_no_duplicate() -> None:
    plane = chaos.ChaosControlPlane()
    # Crash before publish completes.
    crashed = plane.inject_and_recover(
        chaos.FailureBoundary.PROOF_PUBLICATION,
        operation_id="op:proof:crash",
    )
    assert crashed.crashed is True
    assert crashed.recovered is True

    # Clean publish path: single authority only.
    plane2 = chaos.ChaosControlPlane()
    fence = plane2.claim_fence("proof:clean", owner_id="producer")
    rec = plane2.publish_authority(
        "proof:clean",
        {"status": "proved"},
        fence,
        evidence_label="proof-clean",
    )
    assert rec.authority_digest.startswith("sha256:")
    assert plane2.authority_count() == 1
    with pytest.raises(chaos.DuplicateAuthorityError):
        fence2 = plane2.claim_fence("proof:clean-b", owner_id="other")
        # Force same key
        plane2.publish_authority(
            "proof:clean", {"status": "proved-again"}, fence2
        )


# ---------------------------------------------------------------------------
# Full suite / receipt / CLI
# ---------------------------------------------------------------------------


def test_run_chaos_suite_passes_all_checks() -> None:
    report = chaos.run_chaos_suite()
    assert report["ok"] is True, report.get("errors")
    assert report["task_id"] == "DQK-051"
    assert report["failed"] == 0
    assert report["passed"] >= 8
    acceptance = report["acceptance"]
    assert acceptance["stale_fences_cannot_publish"] is True
    assert acceptance["no_progress_and_deadlock_diagnoses_are_typed"] is True
    assert (
        acceptance["recovery_preserves_dirty_work_and_immutable_evidence"]
        is True
    )
    names = {r["name"] for r in report["results"]}
    assert "all_failure_boundaries" in names
    assert "stale_fences_cannot_publish" in names


def test_build_chaos_receipt_requires_passing_suite() -> None:
    report = chaos.run_chaos_suite()
    assert report["ok"] is True
    receipt = chaos.build_chaos_receipt(suite_report=report)
    assert receipt["schema"] == chaos.CHAOS_RECEIPT_SCHEMA
    assert receipt["task_id"] == "DQK-051"
    assert receipt["ok"] is True
    assert receipt["suite_digest"].startswith("sha256:")
    assert set(receipt["failure_boundaries"]) == set(chaos.FAILURE_BOUNDARIES)


def test_cli_json_and_receipt(capsys: pytest.CaptureFixture[str]) -> None:
    rc = chaos.main(["--json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["task_id"] == "DQK-051"

    rc2 = chaos.main(["--emit-receipt"])
    assert rc2 == 0
    out2 = capsys.readouterr().out
    wrapped = json.loads(out2)
    assert wrapped["report"]["ok"] is True
    assert wrapped["chaos_receipt"]["schema"] == chaos.CHAOS_RECEIPT_SCHEMA


def test_self_check_ok() -> None:
    report = chaos.self_check()
    assert report["ok"] is True
    assert report["install"]["owner_task_id"] == "DQK-051"
    assert report["suite"]["ok"] is True
