"""Release tests for patent legal production completion gate (PATLAW-164).

Acceptance:

* One content-free immutable receipt proves every mandatory gate on the
  current tree
* Mismatched / stale / missing / unknown evidence blocks
* No legal opinion, patentability guarantee, filing claim, or publication
  claim appears without corresponding reviewed evidence
* Root goal remains active until this receipt and every child receipt
  validate
* Task / goal / drained-board status alone cannot satisfy acceptance
* Child receipts for PATLAW-143, 151, 155, 160, 163 are bound

Validation::

    python -m pytest tests/release/test_patent_legal_production_release.py -q
    python scripts/ops/uspto/validate_production_release.py --offline
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
_GATE_PATH = _REPO_ROOT / "scripts" / "ops" / "uspto" / "validate_production_release.py"
_SCHEMA_PATH = (
    _REPO_ROOT
    / "data"
    / "release"
    / "patent_legal_intelligence"
    / "production_receipt.schema.json"
)
_RUNBOOK_PATH = (
    _REPO_ROOT / "docs" / "operations" / "PATENT_LEGAL_PRODUCTION_RELEASE.md"
)


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "uspto_validate_production_release_rel", _GATE_PATH
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
    assert _RUNBOOK_PATH.is_file()


def test_module_identity_and_policy() -> None:
    assert gate.TASK_ID == "PATLAW-164"
    assert gate.GOAL_ID == "PATLAW-G192"
    assert gate.SCHEMA_VERSION == "patent-legal.production-release.v1"
    assert gate.INTERFACE == "PatentLegalProductionRelease@1"
    assert gate.POLICY_ID == "patent-legal-production-release/v1"
    assert gate.is_rejected_substitute("task_status")
    assert gate.is_rejected_substitute("todo_status")
    assert gate.is_rejected_substitute("goal_status")
    assert gate.is_rejected_substitute("backlog_status")
    assert gate.is_rejected_substitute("drained_board")
    assert not gate.is_rejected_substitute("validation_receipt")
    for mid in (
        "git_tree_binding",
        "config_digest",
        "source_roots_current_through",
        "corpus_index_model_qrels_roots",
        "retrieval_metrics",
        "private_isolation_provider_calls",
        "filing_handoff_receipts",
        "hub_commit_viewer_verification",
        "paired_repository_shas",
        "supervisor_merge_receipts",
        "child_receipts_validated",
        "production_status_surface",
        "no_unreviewed_legal_claims",
        "stale_missing_mismatch_blocks",
        "root_goal_active_until_validated",
        "prior_tasks_on_branch",
        "no_blocked_unknown_gates",
        "task_status_alone_rejected",
    ):
        assert mid in gate.MANDATORY_GATES


def test_required_prior_tasks_match_depends_on() -> None:
    ids = [t["task_id"] for t in gate.REQUIRED_PRIOR_TASKS]
    assert ids == [
        "PATLAW-143",
        "PATLAW-151",
        "PATLAW-155",
        "PATLAW-160",
        "PATLAW-163",
    ]


def test_prior_task_outputs_present_on_tree() -> None:
    prior = gate.inventory_prior_tasks(_REPO_ROOT, include_supporting=True)
    assert prior["all_required_present"] is True, prior["missing_task_ids"]
    assert prior["all_present"] is True, prior["missing_task_ids"]
    for task in prior["tasks"]:
        assert task["status"] == "present", task
        assert not task["missing_outputs"], task


def test_production_receipt_schema_identity() -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$id"].endswith("patent-legal-production-release.v1.schema.json")
    assert schema["properties"]["schema_version"]["const"] == gate.SCHEMA_VERSION
    assert schema["properties"]["interface"]["const"] == gate.INTERFACE
    assert schema["properties"]["task_id"]["const"] == gate.TASK_ID
    assert schema["properties"]["goal_id"]["const"] == gate.GOAL_ID
    assert schema["properties"]["content_free"]["const"] is True
    required = set(schema["required"])
    for key in (
        "digests",
        "bindings",
        "child_receipts",
        "supervisor_merge_receipts",
        "claim_surface",
        "root_goal",
        "gates",
        "policy",
        "receipt_digest_sha256",
    ):
        assert key in required


def test_runbook_documents_gate_and_policy() -> None:
    text = _RUNBOOK_PATH.read_text(encoding="utf-8")
    assert "PATLAW-164" in text
    assert "PATLAW-G192" in text
    assert "content-free" in text.lower() or "content free" in text.lower()
    assert "validate_production_release.py" in text
    assert "child" in text.lower()
    for claim in (
        "legal opinion",
        "patentability",
        "filing claim",
        "publication claim",
    ):
        assert claim in text.lower()


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
        "source",
        "index",
        "model",
        "qrels",
        "retrieval_metrics",
        "filing",
        "hub",
        "sync",
        "test",
    ):
        assert digests[key]["complete"] is True, digests[key]
        assert digests[key]["missing"] == []
        assert gate.SHA256_RE.match(digests[key]["digest_sha256"])


def test_production_bindings_pass_on_tree() -> None:
    digests = gate.compute_all_digests(_REPO_ROOT)
    bindings = gate.build_production_bindings(_REPO_ROOT, digests)
    assert bindings["content_free"] is True
    for key in (
        "source_roots",
        "corpus_index_model_qrels",
        "retrieval_metrics",
        "private_isolation",
        "filing_handoff",
        "hub_verification",
        "paired_repositories",
        "production_status",
    ):
        assert bindings[key]["status"] == "passed", bindings[key]
        assert bindings[key]["content_free"] is True
    assert bindings["private_isolation"]["provider_calls_total"] == 0
    assert bindings["private_isolation"]["no_disclosure"] is True
    assert bindings["private_isolation"]["isolation_incidents"] == 0
    assert bindings["filing_handoff"]["filing_claim_asserted"] is False
    assert bindings["hub_verification"]["publication_claim_asserted"] is False


# ---------------------------------------------------------------------------
# Task / goal / drained status alone cannot satisfy acceptance
# ---------------------------------------------------------------------------


def test_task_status_alone_is_rejected_substitute() -> None:
    assert gate.is_rejected_substitute("task_status")
    assert gate.is_rejected_substitute("goal_status")
    assert gate.is_rejected_substitute("drained_board")
    assert not gate._task_status_only_would_pass()
    gate.validate_task_status_alone_rejected()


def test_task_status_only_receipt_rejected() -> None:
    claim: dict[str, Any] = {
        "schema_version": gate.SCHEMA_VERSION,
        "interface": gate.INTERFACE,
        "policy_id": gate.POLICY_ID,
        "task_id": gate.TASK_ID,
        "goal_id": gate.GOAL_ID,
        "receipt_id": "bad-task-status",
        "status": "accepted",
        "mode": "offline",
        "started_at_utc": gate.utc_now(),
        "completed_at_utc": gate.utc_now(),
        "git": {},
        "digests": {},
        "bindings": {},
        "child_receipts": {},
        "test_results": [],
        "supervisor_merge_receipts": {},
        "claim_surface": {
            "legal_opinion": {"asserted": False, "reviewed_evidence_present": False},
            "patentability_guarantee": {
                "asserted": False,
                "reviewed_evidence_present": False,
            },
            "filing_claim": {"asserted": False, "reviewed_evidence_present": False},
            "publication_claim": {"asserted": False, "reviewed_evidence_present": False},
            "content_free": True,
            "unreviewed_claims_block": True,
            "any_unreviewed_asserted": False,
        },
        "root_goal": {
            "goal_id": gate.GOAL_ID,
            "status": "active",
            "requires_receipt_and_children": True,
            "this_receipt_validated": False,
            "children_validated": False,
            "completion_eligible": False,
            "task_status_alone_insufficient": True,
            "content_free": True,
        },
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
            "stale_missing_mismatch_block": True,
            "unreviewed_claims_block": True,
            "root_goal_active_until_validated": True,
            "child_receipts_required": True,
            "receipts_outside_tracked_source_default": True,
            "drained_board_not_evidence": True,
        },
        "content_free": True,
        "notes": ["task_status_only", "goal_status_only", "drained_board_only"],
    }
    body = {k: v for k, v in claim.items() if k != "receipt_digest_sha256"}
    claim["receipt_digest_sha256"] = gate.sha256_hex(gate.canonical_json(body))
    errors = gate.validate_receipt_struct(claim)
    assert errors


# ---------------------------------------------------------------------------
# Fresh offline receipt
# ---------------------------------------------------------------------------


def test_collect_tree_evidence_offline_accepted() -> None:
    receipt = gate.collect_tree_evidence(_REPO_ROOT, mode="offline")
    assert receipt["task_id"] == "PATLAW-164"
    assert receipt["goal_id"] == "PATLAW-G192"
    assert receipt["schema_version"] == gate.SCHEMA_VERSION
    assert receipt["interface"] == gate.INTERFACE
    assert receipt["content_free"] is True
    assert receipt["status"] == "accepted", {
        g["gate_id"]: g["status"]
        for g in receipt["gates"]
        if g.get("status") != "passed"
    }

    # Digests
    assert receipt["digests"]["all_complete"] is True
    assert gate.SHA256_RE.match(receipt["digests"]["aggregate_sha256"])

    # Child receipts
    children = receipt["child_receipts"]
    assert children["all_validated"] is True
    assert children["content_free"] is True
    assert set(children["required_task_ids"]) == {
        "PATLAW-143",
        "PATLAW-151",
        "PATLAW-155",
        "PATLAW-160",
        "PATLAW-163",
    }
    for cr in children["receipts"]:
        assert cr["status"] == "validated"
        assert cr["content_free"] is True
        assert not cr["missing_outputs"]

    # Supervisor merge
    sm = receipt["supervisor_merge_receipts"]
    assert sm["status"] == "passed"
    assert sm["content_free"] is True
    assert sm["prior_tasks_bound"] is True
    assert any(r["task_id"] == "PATLAW-143" for r in sm["receipts"])

    # Claim surface — no unreviewed claims
    cs = receipt["claim_surface"]
    assert cs["content_free"] is True
    assert cs["unreviewed_claims_block"] is True
    assert cs["any_unreviewed_asserted"] is False
    for kind in gate.CLAIM_KINDS:
        assert cs[kind]["asserted"] is False

    # Root goal completion-eligible only after receipt + children
    rg = receipt["root_goal"]
    assert rg["goal_id"] == "PATLAW-G192"
    assert rg["requires_receipt_and_children"] is True
    assert rg["this_receipt_validated"] is True
    assert rg["children_validated"] is True
    assert rg["completion_eligible"] is True
    assert rg["content_free"] is True

    # Policy
    assert receipt["policy"]["task_status_alone_insufficient"] is True
    assert receipt["policy"]["goal_status_alone_insufficient"] is True
    assert receipt["policy"]["fail_closed"] is True
    assert receipt["policy"]["unknown_mandatory_gates_block"] is True
    assert receipt["policy"]["stale_missing_mismatch_block"] is True
    assert receipt["policy"]["unreviewed_claims_block"] is True
    assert receipt["policy"]["root_goal_active_until_validated"] is True
    assert receipt["policy"]["child_receipts_required"] is True
    assert receipt["policy"]["drained_board_not_evidence"] is True

    # All mandatory gates present and passed
    gate_map = {g["gate_id"]: g for g in receipt["gates"]}
    for mid in gate.MANDATORY_GATES:
        assert mid in gate_map, mid
        assert gate_map[mid]["status"] == "passed", gate_map[mid]
        assert gate_map[mid]["status"] not in {
            "blocked",
            "unknown",
            "stale",
            "mismatched",
            "missing",
        }

    gate.assert_content_free(receipt)
    gate.assert_receipt_valid(receipt)


def test_receipt_digest_is_stable_for_identical_body() -> None:
    receipt = gate.collect_tree_evidence(_REPO_ROOT, mode="offline")
    body = {k: v for k, v in receipt.items() if k != "receipt_digest_sha256"}
    expected = gate.sha256_hex(gate.canonical_json(body))
    assert receipt["receipt_digest_sha256"] == expected


def test_blocked_stale_unknown_gates_fail_closed() -> None:
    assert gate.receipt_status_from_gates(
        [gate.make_gate("a", status="blocked")]
    ) == "blocked"
    assert gate.receipt_status_from_gates(
        [gate.make_gate("a", status="unknown")]
    ) == "blocked"
    assert gate.receipt_status_from_gates(
        [gate.make_gate("a", status="stale")]
    ) == "blocked"
    assert gate.receipt_status_from_gates(
        [gate.make_gate("a", status="mismatched")]
    ) == "blocked"
    assert gate.receipt_status_from_gates(
        [gate.make_gate("a", status="missing")]
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
        g for g in receipt["gates"] if g.get("gate_id") != "retrieval_metrics"
    ]
    incomplete["status"] = "accepted"
    body = {k: v for k, v in incomplete.items() if k != "receipt_digest_sha256"}
    incomplete["receipt_digest_sha256"] = gate.sha256_hex(gate.canonical_json(body))
    errors = gate.validate_receipt_struct(incomplete)
    assert any("retrieval_metrics" in e or "mandatory gate" in e for e in errors)


def test_missing_prior_task_fails_inventory(tmp_path: Path) -> None:
    prior = gate.inventory_prior_tasks(tmp_path, include_supporting=False)
    assert prior["all_required_present"] is False
    assert set(prior["missing_task_ids"]) == {
        t["task_id"] for t in gate.REQUIRED_PRIOR_TASKS
    }


def test_content_free_rejects_secret_markers() -> None:
    with pytest.raises(gate.ProductionReleaseGateError):
        gate.assert_content_free({"note": "authorization: bearer leaked-token"})
    with pytest.raises(gate.ProductionReleaseGateError):
        gate.assert_content_free({"api_key": "should-not-appear"})


def test_unreviewed_patentability_claim_blocks() -> None:
    digests = gate.compute_all_digests(_REPO_ROOT)
    bindings = gate.build_production_bindings(_REPO_ROOT, digests)
    surface = gate.build_claim_surface(
        bindings=bindings,
        claims={
            "patentability_guarantee": {
                "asserted": True,
                "reviewed_evidence_present": False,
            }
        },
    )
    assert surface["any_unreviewed_asserted"] is True
    assert surface["patentability_guarantee"]["status"] == "unreviewed"

    receipt = gate.collect_tree_evidence(
        _REPO_ROOT,
        mode="offline",
        claim_overrides={
            "legal_opinion": {
                "asserted": True,
                "reviewed_evidence_present": False,
            }
        },
    )
    assert receipt["status"] == "blocked"
    gate_map = {g["gate_id"]: g for g in receipt["gates"]}
    assert gate_map["no_unreviewed_legal_claims"]["status"] == "blocked"


def test_reviewed_claim_with_evidence_allowed() -> None:
    digests = gate.compute_all_digests(_REPO_ROOT)
    bindings = gate.build_production_bindings(_REPO_ROOT, digests)
    surface = gate.build_claim_surface(
        bindings=bindings,
        claims={
            "filing_claim": {
                "asserted": True,
                "reviewed_evidence_present": True,
                "evidence_ref": "review-ref:filing-ack-1",
            }
        },
    )
    assert surface["any_unreviewed_asserted"] is False
    assert surface["filing_claim"]["status"] == "reviewed"


def test_root_goal_active_without_children() -> None:
    rg = gate.build_root_goal(
        children_validated=False,
        this_receipt_gates_pass=False,
    )
    assert rg["status"] == "active"
    assert rg["completion_eligible"] is False
    assert rg["requires_receipt_and_children"] is True

    rg2 = gate.build_root_goal(
        children_validated=True,
        this_receipt_gates_pass=True,
    )
    assert rg2["completion_eligible"] is True
    assert rg2["status"] == "completion_eligible"


def test_child_receipts_validate_all_required() -> None:
    digests = gate.compute_all_digests(_REPO_ROOT)
    prior = gate.inventory_prior_tasks(_REPO_ROOT, include_supporting=False)
    git_info = gate.inspect_git(_REPO_ROOT)
    children = gate.build_child_receipts(
        prior=prior, git_info=git_info, digests=digests, synthetic=True
    )
    assert children["status"] == "passed"
    assert children["all_validated"] is True
    assert children["missing_or_invalid"] == []
    assert len(children["receipts"]) == 5


def test_run_release_gate_offline_writes_outside_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    out = tmp_path / "receipts" / "offline-prod.json"
    result = gate.run_release_gate(
        repo_root=_REPO_ROOT,
        mode="offline",
        output_path=out,
        write_receipt=True,
    )
    assert result["ok"] is True, result
    assert out.is_file()
    default_dir = gate.default_receipt_dir()
    assert "patent_legal_intelligence" in str(default_dir)
    assert "production_release" in str(default_dir)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    gate.assert_receipt_valid(loaded)
    assert loaded["status"] == "accepted"
    assert "data/release" not in str(out)


def test_offline_self_check_passes() -> None:
    report = gate.offline_self_check(_REPO_ROOT)
    assert report["ok"] is True, [
        c for c in report["checks"] if c.get("status") != "passed"
    ]
    assert report["task_id"] == "PATLAW-164"
    assert report["goal_id"] == "PATLAW-G192"


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
    assert payload["task_id"] == "PATLAW-164"
    assert payload["goal_id"] == "PATLAW-G192"
    assert payload["receipt"]["status"] == "accepted"
    assert payload["receipt"]["prior_tasks_present"] is True
    assert payload["receipt"]["children_validated"] is True
    assert payload["receipt"]["completion_eligible"] is True
    assert payload["receipt"]["unreviewed_claims"] is False
    assert payload["receipt"]["no_disclosure"] is True
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
        "bindings": {},
        "child_receipts": {},
        "test_results": [],
        "supervisor_merge_receipts": {},
        "claim_surface": {
            "legal_opinion": {"asserted": False, "reviewed_evidence_present": False},
            "patentability_guarantee": {
                "asserted": False,
                "reviewed_evidence_present": False,
            },
            "filing_claim": {"asserted": False, "reviewed_evidence_present": False},
            "publication_claim": {"asserted": False, "reviewed_evidence_present": False},
            "content_free": True,
            "unreviewed_claims_block": True,
            "any_unreviewed_asserted": False,
        },
        "root_goal": {
            "goal_id": gate.GOAL_ID,
            "status": "active",
            "requires_receipt_and_children": True,
            "this_receipt_validated": False,
            "children_validated": False,
            "completion_eligible": False,
            "task_status_alone_insufficient": True,
            "content_free": True,
        },
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
            "stale_missing_mismatch_block": True,
            "unreviewed_claims_block": True,
            "root_goal_active_until_validated": True,
            "child_receipts_required": True,
            "receipts_outside_tracked_source_default": True,
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
