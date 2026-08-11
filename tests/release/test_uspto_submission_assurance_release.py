"""Release tests for USPTO submission-assurance current-tree gate (PATLAW-074).

Acceptance:

* Fresh receipt binds git tree, config, fixture/ruleset/parser versions,
  test results, privacy scan, and merge-queue evidence.
* Target branch / tree contains every prior task (061, 062, 072, 073, 080, 102).
* No blocked/unknown mandatory release gate remains.
* Task status alone cannot satisfy acceptance.

Validation:

    python -m pytest tests/release/test_uspto_submission_assurance_release.py -q
    python scripts/ops/uspto/validate_release.py --offline
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Paths / module load
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATE_PATH = _REPO_ROOT / "scripts" / "ops" / "uspto" / "validate_release.py"
_GITKEEP = (
    _REPO_ROOT / "data" / "release" / "uspto_submission_assurance" / ".gitkeep"
)
_COMPAT_SCHEMA = (
    _REPO_ROOT
    / "data"
    / "release"
    / "uspto_submission_assurance"
    / "compatibility_manifest.schema.json"
)


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "uspto_validate_release", _GATE_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


gate = _load_gate()


# ---------------------------------------------------------------------------
# Declared outputs / inventory
# ---------------------------------------------------------------------------


def test_declared_outputs_exist() -> None:
    assert _GATE_PATH.is_file()
    assert _GITKEEP.is_file()
    assert Path(__file__).is_file()
    # Supporting release data from PATLAW-080 remains present.
    assert _COMPAT_SCHEMA.is_file()


def test_module_identity_and_policy() -> None:
    assert gate.TASK_ID == "PATLAW-074"
    assert gate.GOAL_ID == "PATLAW-G080"
    assert gate.SCHEMA_VERSION == "uspto.submission-assurance-release.v1"
    assert gate.INTERFACE == "UsptoSubmissionAssuranceRelease@1"
    assert gate.is_rejected_substitute("task_status")
    assert gate.is_rejected_substitute("todo_status")
    assert gate.is_rejected_substitute("backlog_status")
    assert gate.is_rejected_substitute("coverage")
    assert not gate.is_rejected_substitute("validation_receipt")
    assert "git_tree_binding" in gate.MANDATORY_GATES
    assert "privacy_scan" in gate.MANDATORY_GATES
    assert "merge_queue_evidence" in gate.MANDATORY_GATES
    assert "task_status_alone_rejected" in gate.MANDATORY_GATES
    assert gate.POLICY_ID == "uspto-submission-assurance-release/v1"


def test_required_prior_tasks_match_depends_on() -> None:
    ids = [t["task_id"] for t in gate.REQUIRED_PRIOR_TASKS]
    assert ids == [
        "PATLAW-061",
        "PATLAW-062",
        "PATLAW-072",
        "PATLAW-073",
        "PATLAW-080",
        "PATLAW-102",
    ]


def test_prior_task_outputs_present_on_tree() -> None:
    prior = gate.inventory_prior_tasks(_REPO_ROOT, include_supporting=True)
    assert prior["all_required_present"] is True, prior["missing_task_ids"]
    assert prior["all_present"] is True, prior["missing_task_ids"]
    for task in prior["tasks"]:
        assert task["status"] == "present", task
        assert not task["missing_outputs"], task


# ---------------------------------------------------------------------------
# Version / config bindings
# ---------------------------------------------------------------------------


def test_fixture_ruleset_parser_versions_bound() -> None:
    versions = gate.load_fixture_versions(_REPO_ROOT)
    assert versions["parser"]
    assert isinstance(versions["parser"], str)
    assert versions["ruleset"]
    assert all(isinstance(v, str) and v for v in versions["ruleset"].values())
    fixture = versions["fixture"]
    assert fixture["gold_corpus_id"]
    assert fixture["gold_manifest_sha256"]
    assert fixture["replay_manifest_sha256"]
    assert fixture["metric_gates_sha256"]
    assert fixture["gold_case_count"] >= 1
    assert fixture["replay_network_free"] is True


def test_config_digest_complete() -> None:
    config = gate.compute_config_digest(_REPO_ROOT)
    assert config["complete"] is True
    assert config["missing"] == []
    assert gate.SHA256_RE.match(config["digest_sha256"])
    # Deterministic across two calls.
    again = gate.compute_config_digest(_REPO_ROOT)
    assert again["digest_sha256"] == config["digest_sha256"]


def test_privacy_scan_inventory_passes() -> None:
    scan = gate.privacy_scan_inventory(_REPO_ROOT)
    assert scan["status"] == "passed"
    assert scan["content_free"] is True
    assert scan["private_bytes_inspected"] is False
    assert all(scan["paths"].values())
    assert scan["markers"]


def test_merge_queue_evidence_binds_prior_tasks() -> None:
    git_info = gate.inspect_git(_REPO_ROOT)
    prior = gate.inventory_prior_tasks(_REPO_ROOT)
    mq = gate.merge_queue_evidence(
        _REPO_ROOT, prior=prior, git_info=git_info, synthetic=True
    )
    assert mq["status"] == "passed"
    assert mq["merge_receipt"]["status"] == "merged"
    assert mq["merge_receipt"]["content_free"] is True
    assert mq["prior_tasks_bound"] is True
    assert mq["compatibility_schema_present"] is True
    assert set(mq["merge_receipt"]["prior_task_ids"]) == {
        t["task_id"] for t in gate.REQUIRED_PRIOR_TASKS
    }


# ---------------------------------------------------------------------------
# Task status alone cannot satisfy acceptance
# ---------------------------------------------------------------------------


def test_task_status_alone_is_rejected_substitute() -> None:
    assert gate.is_rejected_substitute("task_status")
    assert gate._task_status_only_would_pass() is False


def test_task_status_only_receipt_fails_validation() -> None:
    gate.validate_task_status_alone_rejected()  # raises if invariant broken


def test_todo_status_evidence_kind_fails_gate() -> None:
    g = gate.make_gate(
        "fake",
        status="passed",
        detail="todo done",
        evidence_kind="todo_status",
    )
    assert g["status"] == "failed"
    assert g["evidence_kind"] == "rejected_substitute"


# ---------------------------------------------------------------------------
# Fresh receipt / offline self-check
# ---------------------------------------------------------------------------


def test_offline_self_check_passes() -> None:
    report = gate.offline_self_check(_REPO_ROOT)
    assert report["ok"] is True, report["checks"]
    names = {c["name"] for c in report["checks"]}
    assert "fresh_receipt" in names
    assert "task_status_alone_rejected" in names
    assert "prior_tasks_present" in names
    assert "version_pins" in names
    assert "blocked_unknown_fail_closed" in names
    assert all(c["status"] == "passed" for c in report["checks"]), report["checks"]
    meta = report["receipt"]
    assert meta is not None
    assert meta["status"] == "accepted"
    assert gate.SHA256_RE.match(meta["receipt_digest_sha256"])


def test_collect_offline_receipt_binds_all_acceptance_fields() -> None:
    receipt = gate.collect_tree_evidence(_REPO_ROOT, mode="offline")
    gate.assert_receipt_valid(receipt)
    assert receipt["status"] == "accepted"
    assert receipt["task_id"] == "PATLAW-074"
    assert receipt["goal_id"] == "PATLAW-G080"
    assert receipt["schema_version"] == gate.SCHEMA_VERSION
    assert receipt["content_free"] is True

    # Git tree binding
    git = receipt["git"]
    assert git.get("head_sha")
    assert git.get("tree_sha")
    assert len(git["head_sha"]) == 40
    assert len(git["tree_sha"]) == 40

    # Config
    assert receipt["config"]["complete"] is True
    assert gate.SHA256_RE.match(receipt["config"]["digest_sha256"])

    # Fixture / ruleset / parser versions
    versions = receipt["versions"]
    assert versions["parser"]
    assert versions["ruleset"]
    assert versions["fixture"]["gold_manifest_sha256"]
    assert versions["fixture"]["replay_manifest_sha256"]

    # Test results
    assert receipt["test_results"]
    assert all(r["status"] == "passed" and r["exit_code"] == 0 for r in receipt["test_results"])

    # Privacy scan
    assert receipt["privacy_scan"]["status"] == "passed"

    # Merge-queue evidence
    assert receipt["merge_queue"]["merge_receipt"]["status"] == "merged"
    assert receipt["prior_tasks"]["all_required_present"] is True

    # Policy: task status alone insufficient
    assert receipt["policy"]["task_status_alone_insufficient"] is True
    assert receipt["policy"]["fail_closed"] is True

    # All mandatory gates present and passed; none blocked/unknown
    gate_map = {g["gate_id"]: g for g in receipt["gates"]}
    for mid in gate.MANDATORY_GATES:
        assert mid in gate_map, mid
        assert gate_map[mid]["status"] == "passed", gate_map[mid]
        assert gate_map[mid]["status"] not in {"blocked", "unknown"}

    gate.assert_content_free(receipt)


def test_receipt_digest_is_stable_for_identical_body() -> None:
    receipt = gate.collect_tree_evidence(_REPO_ROOT, mode="offline")
    body = {k: v for k, v in receipt.items() if k != "receipt_digest_sha256"}
    # Re-stamp times and ids would change digest; recompute on same body.
    expected = gate.sha256_hex(gate.canonical_json(body))
    assert receipt["receipt_digest_sha256"] == expected


def test_blocked_and_unknown_gates_fail_closed() -> None:
    assert gate.receipt_status_from_gates(
        [gate.make_gate("a", status="blocked")]
    ) == "blocked"
    assert gate.receipt_status_from_gates(
        [gate.make_gate("a", status="unknown")]
    ) == "blocked"
    assert gate.receipt_status_from_gates(
        [gate.make_gate("a", status="passed")]
    ) == "accepted"
    assert gate.receipt_status_from_gates(
        [
            gate.make_gate("a", status="passed"),
            gate.make_gate("b", status="failed"),
        ]
    ) == "rejected"


def test_missing_mandatory_gate_rejected() -> None:
    receipt = gate.collect_tree_evidence(_REPO_ROOT, mode="offline")
    incomplete = dict(receipt)
    incomplete["gates"] = [
        g for g in receipt["gates"] if g.get("gate_id") != "test_results"
    ]
    incomplete["status"] = "accepted"
    body = {k: v for k, v in incomplete.items() if k != "receipt_digest_sha256"}
    incomplete["receipt_digest_sha256"] = gate.sha256_hex(gate.canonical_json(body))
    errors = gate.validate_receipt_struct(incomplete)
    assert any("test_results" in e or "mandatory gate" in e for e in errors)


def test_missing_prior_task_fails_inventory(tmp_path: Path) -> None:
    # Empty tree has no prior outputs.
    prior = gate.inventory_prior_tasks(tmp_path, include_supporting=False)
    assert prior["all_required_present"] is False
    assert set(prior["missing_task_ids"]) == {
        t["task_id"] for t in gate.REQUIRED_PRIOR_TASKS
    }


def test_content_free_rejects_secret_markers() -> None:
    with pytest.raises(gate.ReleaseGateError):
        gate.assert_content_free({"note": "authorization: bearer leaked-token"})
    with pytest.raises(gate.ReleaseGateError):
        gate.assert_content_free({"api_key": "should-not-appear"})


def test_run_release_gate_offline_writes_outside_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    out = tmp_path / "receipts" / "offline.json"
    result = gate.run_release_gate(
        repo_root=_REPO_ROOT,
        mode="offline",
        output_path=out,
        write_receipt=True,
    )
    assert result["ok"] is True, result
    assert out.is_file()
    # Default dir would be under XDG state — ensure helper points outside repo.
    default_dir = gate.default_receipt_dir()
    assert "uspto_submission_assurance" in str(default_dir)
    assert "release" in str(default_dir)
    # Written receipt is valid and accepted.
    loaded = json.loads(out.read_text(encoding="utf-8"))
    gate.assert_receipt_valid(loaded)
    assert loaded["status"] == "accepted"
    # Not written into tracked data/release by default path.
    assert "data/release" not in str(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_offline_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(_GATE_PATH), "--offline", "--no-write"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "offline"
    assert payload["task_id"] == "PATLAW-074"
    assert payload["receipt"]["status"] == "accepted"
    assert payload["receipt"]["prior_tasks_present"] is True
    gate_ids = {g["gate_id"] for g in payload["receipt"]["gate_summary"]}
    assert set(gate.MANDATORY_GATES) <= gate_ids
    assert all(g["status"] == "passed" for g in payload["receipt"]["gate_summary"])


def test_cli_validate_accepted_receipt(tmp_path: Path) -> None:
    receipt = gate.collect_tree_evidence(_REPO_ROOT, mode="offline")
    path = tmp_path / "r.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(_GATE_PATH), "--receipt", str(path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "accepted"


def test_cli_validate_task_status_only_fails(tmp_path: Path) -> None:
    # Minimal invalid "accepted" claim with only task status.
    claim: dict[str, Any] = {
        "schema_version": gate.SCHEMA_VERSION,
        "interface": gate.INTERFACE,
        "policy_id": gate.POLICY_ID,
        "task_id": gate.TASK_ID,
        "goal_id": gate.GOAL_ID,
        "receipt_id": "bad",
        "status": "accepted",
        "mode": "offline",
        "started_at_utc": gate.utc_now(),
        "completed_at_utc": gate.utc_now(),
        "git": {},
        "config": {},
        "versions": {},
        "test_results": [],
        "privacy_scan": {},
        "merge_queue": {},
        "prior_tasks": {},
        "gates": [],
        "mandatory_gates": list(gate.MANDATORY_GATES),
        "missing_mandatory_gates": list(gate.MANDATORY_GATES),
        "policy": {
            "task_status_alone_insufficient": True,
            "fail_closed": True,
            "content_free": True,
            "receipts_outside_tracked_source_default": True,
            "rejected_substitutes": sorted(gate.REJECTED_SUBSTITUTES),
            "required_prior_tasks": [t["task_id"] for t in gate.REQUIRED_PRIOR_TASKS],
        },
        "content_free": True,
        "notes": ["task_status_only"],
    }
    body = {k: v for k, v in claim.items() if k != "receipt_digest_sha256"}
    claim["receipt_digest_sha256"] = gate.sha256_hex(gate.canonical_json(body))
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(claim, indent=2, sort_keys=True), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(_GATE_PATH), "--receipt", str(path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False


def test_live_collect_binds_suite_inventory() -> None:
    receipt = gate.collect_tree_evidence(_REPO_ROOT, mode="live")
    # Live inventory should still pass when all suite files exist on tree.
    assert receipt["test_results"]
    failed = [r for r in receipt["test_results"] if r["status"] != "passed"]
    assert not failed, failed
    gate.assert_receipt_valid(receipt)
    assert receipt["status"] == "accepted"


def test_no_blocked_unknown_gate_on_fresh_receipt() -> None:
    receipt = gate.collect_tree_evidence(_REPO_ROOT, mode="offline")
    for g in receipt["gates"]:
        assert g["status"] not in {"blocked", "unknown", "failed", "error"}
    assert receipt["missing_mandatory_gates"] == []
