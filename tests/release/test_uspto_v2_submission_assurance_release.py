"""Release tests for USPTO submission-assurance v2 gate (PATLAW-143).

Acceptance:

* Fresh receipt binds code/config/corpus/rules/parser/compiler/prover/model/
  test/metric digests and supervisor merge receipts
* Independent human legal-review scope and exceptions are bound
* Adversarial, privacy-lifecycle, and transactional migration gates pass
* No-disclosure and provider-call evidence is explicit
* Every unknown/blocked mandatory gate fails closed
* Task / goal status alone cannot reconcile acceptance
* Target tree contains PATLAW-142 (and supporting) outputs

Validation::

    python -m pytest tests/security/test_uspto_v2_adversarial_assurance.py \\
        tests/property/test_uspto_v2_pipeline_properties.py \\
        tests/release/test_uspto_v2_submission_assurance_release.py -q
    python scripts/ops/uspto/validate_v2_release.py --offline
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
_GATE_PATH = _REPO_ROOT / "scripts" / "ops" / "uspto" / "validate_v2_release.py"
_SCHEMA_PATH = (
    _REPO_ROOT
    / "data"
    / "release"
    / "uspto_submission_assurance"
    / "v2_receipt.schema.json"
)
_ADVERSARIAL_TEST = (
    _REPO_ROOT / "tests" / "security" / "test_uspto_v2_adversarial_assurance.py"
)
_PROPERTY_TEST = (
    _REPO_ROOT / "tests" / "property" / "test_uspto_v2_pipeline_properties.py"
)


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "uspto_validate_v2_release_rel", _GATE_PATH
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
    assert _SCHEMA_PATH.is_file()
    assert Path(__file__).is_file()
    assert _ADVERSARIAL_TEST.is_file()
    assert _PROPERTY_TEST.is_file()


def test_module_identity_and_policy() -> None:
    assert gate.TASK_ID == "PATLAW-143"
    assert gate.GOAL_ID == "PATLAW-G152"
    assert gate.SCHEMA_VERSION == "uspto.submission-assurance-release.v2"
    assert gate.INTERFACE == "UsptoSubmissionAssuranceRelease@2"
    assert gate.POLICY_ID == "uspto-submission-assurance-release/v2"
    assert gate.is_rejected_substitute("task_status")
    assert gate.is_rejected_substitute("todo_status")
    assert gate.is_rejected_substitute("goal_status")
    assert gate.is_rejected_substitute("backlog_status")
    assert not gate.is_rejected_substitute("validation_receipt")
    for mid in (
        "git_tree_binding",
        "code_digest",
        "config_digest",
        "corpus_digest",
        "rules_digest",
        "parser_digest",
        "compiler_digest",
        "prover_digest",
        "model_digest",
        "test_digest",
        "metric_digest",
        "supervisor_merge_receipts",
        "independent_legal_review",
        "adversarial_assurance",
        "privacy_lifecycle",
        "migration_transactional",
        "no_disclosure_evidence",
        "provider_call_evidence",
        "prior_tasks_on_branch",
        "no_blocked_unknown_gates",
        "task_status_alone_rejected",
    ):
        assert mid in gate.MANDATORY_GATES


def test_required_prior_tasks_match_depends_on() -> None:
    ids = [t["task_id"] for t in gate.REQUIRED_PRIOR_TASKS]
    assert ids == ["PATLAW-142"]


def test_prior_task_outputs_present_on_tree() -> None:
    prior = gate.inventory_prior_tasks(_REPO_ROOT, include_supporting=True)
    assert prior["all_required_present"] is True, prior["missing_task_ids"]
    assert prior["all_present"] is True, prior["missing_task_ids"]
    for task in prior["tasks"]:
        assert task["status"] == "present", task
        assert not task["missing_outputs"], task


def test_v2_receipt_schema_identity() -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$id"].endswith("uspto-submission-assurance-release.v2.schema.json")
    assert schema["properties"]["schema_version"]["const"] == gate.SCHEMA_VERSION
    assert schema["properties"]["interface"]["const"] == gate.INTERFACE
    assert schema["properties"]["task_id"]["const"] == gate.TASK_ID
    assert schema["properties"]["goal_id"]["const"] == gate.GOAL_ID
    assert schema["properties"]["content_free"]["const"] is True
    required = set(schema["required"])
    for key in (
        "digests",
        "supervisor_merge_receipts",
        "independent_legal_review",
        "adversarial_assurance",
        "privacy_lifecycle",
        "migration",
        "gates",
        "policy",
        "receipt_digest_sha256",
    ):
        assert key in required


# ---------------------------------------------------------------------------
# Digest bindings
# ---------------------------------------------------------------------------


def test_all_digest_categories_complete() -> None:
    digests = gate.compute_all_digests(_REPO_ROOT)
    assert digests["all_complete"] is True
    assert gate.SHA256_RE.match(digests["aggregate_sha256"])
    for key in (
        "code",
        "config",
        "corpus",
        "rules",
        "parser",
        "compiler",
        "prover",
        "model",
        "test",
        "metric",
    ):
        assert digests[key]["complete"] is True, digests[key]
        assert digests[key]["missing"] == []
        assert gate.SHA256_RE.match(digests[key]["digest_sha256"])


def test_version_pins_and_fixture_digests() -> None:
    versions = gate.load_version_pins(_REPO_ROOT)
    assert versions["parser"]
    assert versions["ruleset"]
    assert versions["compiler"]
    assert versions["prover"]
    fixture = versions["fixture"]
    assert fixture["gold_corpus_id"] or fixture["gold_manifest_sha256"]
    assert fixture["gold_manifest_sha256"]
    assert fixture["v2_recipe_sha256"]
    assert fixture["metric_gates_sha256"]
    assert fixture["named_processor_count"] >= 1


# ---------------------------------------------------------------------------
# Task / goal status alone cannot satisfy acceptance
# ---------------------------------------------------------------------------


def test_task_status_alone_is_rejected_substitute() -> None:
    assert gate.is_rejected_substitute("task_status")
    assert gate.is_rejected_substitute("goal_status")
    assert gate._task_status_only_would_pass() is False


def test_task_status_only_receipt_fails_validation() -> None:
    gate.validate_task_status_alone_rejected()


def test_goal_status_evidence_kind_fails_gate() -> None:
    g = gate.make_gate(
        "fake",
        status="passed",
        detail="goal reconciled",
        evidence_kind="goal_status",
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
    for required in (
        "schema_present",
        "policy_constants",
        "prior_tasks_present",
        "digests",
        "version_pins",
        "adversarial",
        "migration",
        "privacy_lifecycle",
        "task_status_alone_rejected",
        "fresh_receipt",
        "blocked_unknown_fail_closed",
        "missing_gate_rejected",
        "open_legal_exception_blocks",
    ):
        assert required in names, required
    assert all(c["status"] == "passed" for c in report["checks"]), report["checks"]
    meta = report["receipt"]
    assert meta is not None
    assert meta["status"] == "accepted"
    assert gate.SHA256_RE.match(meta["receipt_digest_sha256"])


def test_collect_offline_receipt_binds_all_acceptance_fields() -> None:
    receipt = gate.collect_tree_evidence(_REPO_ROOT, mode="offline")
    gate.assert_receipt_valid(receipt)
    assert receipt["status"] == "accepted"
    assert receipt["task_id"] == "PATLAW-143"
    assert receipt["goal_id"] == "PATLAW-G152"
    assert receipt["schema_version"] == gate.SCHEMA_VERSION
    assert receipt["content_free"] is True

    # Git tree binding
    git = receipt["git"]
    assert git.get("head_sha")
    assert git.get("tree_sha")
    assert len(git["head_sha"]) == 40
    assert len(git["tree_sha"]) == 40

    # Digests
    digests = receipt["digests"]
    assert digests["all_complete"] is True
    assert gate.SHA256_RE.match(digests["aggregate_sha256"])
    for key in (
        "code",
        "config",
        "corpus",
        "rules",
        "parser",
        "compiler",
        "prover",
        "model",
        "test",
        "metric",
    ):
        assert digests[key]["complete"] is True, key

    # Versions
    versions = receipt["versions"]
    assert versions["parser"]
    assert versions["ruleset"]
    assert versions["fixture"]["gold_manifest_sha256"]
    assert versions["fixture"]["v2_recipe_sha256"]
    assert versions["fixture"]["metric_gates_sha256"]

    # Test results
    assert receipt["test_results"]
    assert all(
        r["status"] == "passed" and r["exit_code"] == 0 for r in receipt["test_results"]
    )

    # Privacy scan
    assert receipt["privacy_scan"]["status"] == "passed"
    assert receipt["privacy_scan"]["private_bytes_inspected"] is False

    # Supervisor merge receipts
    sm = receipt["supervisor_merge_receipts"]
    assert sm["status"] == "passed"
    assert sm["receipts"]
    assert sm["prior_tasks_bound"] is True
    assert any(r["task_id"] == "PATLAW-142" for r in sm["receipts"])

    # Independent legal review
    lr = receipt["independent_legal_review"]
    assert lr["status"] == "accepted"
    assert lr["independent"] is True
    assert lr["human_review"] is True
    assert lr["open_exception_count"] == 0
    assert set(gate.LEGAL_REVIEW_SCOPE_AXES) <= set(lr["scope"]["axes"])
    assert lr["content_free"] is True

    # Adversarial + no-disclosure + provider-call evidence
    adv = receipt["adversarial_assurance"]
    assert adv["status"] == "passed"
    assert adv["disclosure"] is False
    assert adv["no_disclosure_evidence"] is True
    assert adv["provider_calls_total"] == 0
    pce = adv["provider_call_evidence"]
    assert pce["calls_attempted"] == 0
    assert pce["calls_completed"] == 0
    assert pce["credentials_resolved"] is False

    # Privacy lifecycle + migration
    assert receipt["privacy_lifecycle"]["status"] == "passed"
    assert receipt["migration"]["status"] == "passed"
    assert receipt["migration"]["transactional"] is True
    assert receipt["migration"]["fail_without_mutation"] is True

    # Prior tasks
    assert receipt["prior_tasks"]["all_required_present"] is True

    # Policy
    assert receipt["policy"]["task_status_alone_insufficient"] is True
    assert receipt["policy"]["goal_status_alone_insufficient"] is True
    assert receipt["policy"]["fail_closed"] is True
    assert receipt["policy"]["unknown_mandatory_gates_block"] is True
    assert receipt["policy"]["independent_legal_review_required"] is True

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
        g for g in receipt["gates"] if g.get("gate_id") != "metric_digest"
    ]
    incomplete["status"] = "accepted"
    body = {k: v for k, v in incomplete.items() if k != "receipt_digest_sha256"}
    incomplete["receipt_digest_sha256"] = gate.sha256_hex(gate.canonical_json(body))
    errors = gate.validate_receipt_struct(incomplete)
    assert any("metric_digest" in e or "mandatory gate" in e for e in errors)


def test_missing_prior_task_fails_inventory(tmp_path: Path) -> None:
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


def test_open_legal_exception_blocks_acceptance() -> None:
    digests = gate.compute_all_digests(_REPO_ROOT)
    versions = gate.load_version_pins(_REPO_ROOT)
    git_info = gate.inspect_git(_REPO_ROOT)
    blocked = gate.build_independent_legal_review(
        digests=digests,
        versions=versions,
        git_info=git_info,
        exceptions=[
            {
                "exception_id": "exc-rel-1",
                "axis": "export_control_policy",
                "status": "open",
                "summary_ref": "exception-ref:rel-open",
            }
        ],
    )
    assert blocked["status"] == "blocked"
    assert blocked["open_exception_count"] == 1


def test_run_release_gate_offline_writes_outside_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    out = tmp_path / "receipts" / "offline-v2.json"
    result = gate.run_release_gate(
        repo_root=_REPO_ROOT,
        mode="offline",
        output_path=out,
        write_receipt=True,
    )
    assert result["ok"] is True, result
    assert out.is_file()
    default_dir = gate.default_receipt_dir()
    assert "uspto_submission_assurance" in str(default_dir)
    assert "release_v2" in str(default_dir)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    gate.assert_receipt_valid(loaded)
    assert loaded["status"] == "accepted"
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
    assert payload["task_id"] == "PATLAW-143"
    assert payload["goal_id"] == "PATLAW-G152"
    assert payload["receipt"]["status"] == "accepted"
    assert payload["receipt"]["prior_tasks_present"] is True
    assert payload["receipt"]["no_disclosure"] is True
    assert payload["receipt"]["migration_fail_without_mutation"] is True
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
        "digests": {},
        "versions": {},
        "test_results": [],
        "privacy_scan": {},
        "supervisor_merge_receipts": {},
        "independent_legal_review": {},
        "adversarial_assurance": {},
        "privacy_lifecycle": {},
        "migration": {},
        "prior_tasks": {},
        "gates": [
            gate.make_gate(
                "task_status",
                status="passed",
                detail="done",
                evidence_kind="task_status",
            )
        ],
        "mandatory_gates": list(gate.MANDATORY_GATES),
        "missing_mandatory_gates": list(gate.MANDATORY_GATES),
        "policy": {
            "task_status_alone_insufficient": True,
            "goal_status_alone_insufficient": True,
            "fail_closed": True,
            "content_free": True,
            "unknown_mandatory_gates_block": True,
            "independent_legal_review_required": True,
        },
        "content_free": True,
        "notes": ["task_status_only", "goal_status_only"],
    }
    body = {k: v for k, v in claim.items() if k != "receipt_digest_sha256"}
    claim["receipt_digest_sha256"] = gate.sha256_hex(gate.canonical_json(body))
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(claim, indent=2), encoding="utf-8")
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
