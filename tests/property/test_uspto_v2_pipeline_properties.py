"""Property / privacy-lifecycle / migration tests for USPTO v2 (PATLAW-143).

Properties under test:

* v1 durable state migrates transactionally to v2 **or** fails with zero
  mutation of the source preimage
* Privacy lifecycle ops (key rotation, retention, deletion, backup, restore,
  deterministic rebuild, rollback) succeed on content-free metadata
* Digest inventory is complete and deterministic for identical trees
* Unknown mandatory gate statuses block release reconciliation
* Task / goal status alone cannot pass the gate
* Adversarial unknown families remain blocked
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATE_PATH = _REPO_ROOT / "scripts" / "ops" / "uspto" / "validate_v2_release.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "uspto_validate_v2_release_props", _GATE_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


gate = _load_gate()


# ---------------------------------------------------------------------------
# Migration properties
# ---------------------------------------------------------------------------


def test_v1_to_v2_migration_commits_transactionally() -> None:
    state = gate.make_v1_state(valid=True)
    pre = copy.deepcopy(state)
    result = gate.migrate_v1_state_transactional(state)
    assert result["disposition"] == "migrated"
    assert result["mutated"] is True
    assert result["status"] == "passed"
    assert state["schema_version"] == gate.V2_STATE_SCHEMA
    assert state["migrated_from"] == gate.V1_STATE_SCHEMA
    assert state["generation"] == pre["generation"] + 1
    assert state["tenant_id"] == pre["tenant_id"]
    assert state["content_free"] is True
    assert result["preimage_digest"]
    assert result["post_digest"]
    assert result["preimage_digest"] != result["post_digest"]


def test_corrupt_v1_state_aborts_without_mutation() -> None:
    state = gate.make_v1_state(corrupt=True)
    pre = copy.deepcopy(state)
    pre_digest = gate.sha256_hex(gate.canonical_json(pre))
    result = gate.migrate_v1_state_transactional(state)
    assert result["disposition"] == "aborted"
    assert result["mutated"] is False
    assert result["source_unmodified_on_failure"] is True
    assert state == pre
    assert gate.sha256_hex(gate.canonical_json(dict(state))) == pre_digest


def test_forced_migration_failure_restores_preimage() -> None:
    state = gate.make_v1_state(valid=True)
    pre = copy.deepcopy(state)
    result = gate.migrate_v1_state_transactional(state, force_fail=True)
    assert result["disposition"] == "aborted"
    assert result["mutated"] is False
    assert state == pre


def test_invalid_events_shape_aborts_without_mutation() -> None:
    state = gate.make_v1_state(valid=False)
    pre = copy.deepcopy(state)
    result = gate.migrate_v1_state_transactional(state)
    assert result["disposition"] == "aborted"
    assert state == pre


def test_migration_suite_proves_transactional_and_fail_closed() -> None:
    suite = gate.run_migration_suite()
    assert suite["status"] == "passed"
    assert suite["transactional"] is True
    assert suite["fail_without_mutation"] is True
    assert suite["content_free"] is True
    assert suite["success"]["disposition"] == "migrated"
    assert suite["corrupt_abort"]["disposition"] == "aborted"
    assert suite["forced_abort"]["disposition"] == "aborted"
    gate.assert_content_free(suite)


def test_migration_is_idempotent_only_from_v1() -> None:
    state = gate.make_v1_state(valid=True)
    first = gate.migrate_v1_state_transactional(state)
    assert first["disposition"] == "migrated"
    # Second migrate of already-v2 state must abort without mutation.
    mid = copy.deepcopy(state)
    second = gate.migrate_v1_state_transactional(state)
    assert second["disposition"] == "aborted"
    assert state == mid


# ---------------------------------------------------------------------------
# Privacy lifecycle properties
# ---------------------------------------------------------------------------


def test_privacy_lifecycle_covers_required_ops() -> None:
    suite = gate.run_privacy_lifecycle_suite()
    assert suite["status"] == "passed"
    ops = {o["op"] for o in suite["operations"]}
    assert set(gate.PRIVACY_LIFECYCLE_OPS) <= ops
    assert suite["private_bytes_inspected"] is False
    assert suite["content_free"] is True
    gate.assert_content_free(suite)


def test_key_rotation_never_carries_secret_material() -> None:
    suite = gate.run_privacy_lifecycle_suite()
    rotation = next(o for o in suite["operations"] if o["op"] == "key_rotation")
    assert rotation["status"] == "passed"
    assert rotation["secret_material"] is False
    assert rotation["from_key"] != rotation["to_key"]


def test_deletion_and_retention_remove_records() -> None:
    suite = gate.run_privacy_lifecycle_suite()
    deletion = next(o for o in suite["operations"] if o["op"] == "deletion")
    assert deletion["record_present"] is False
    retention = next(o for o in suite["operations"] if o["op"] == "retention_expiry")
    assert retention["deleted_count"] == 1


def test_backup_restore_and_rollback_are_deterministic() -> None:
    suite = gate.run_privacy_lifecycle_suite()
    by_op = {o["op"]: o for o in suite["operations"]}
    assert by_op["backup"]["has_backup"] is True
    assert by_op["restore"]["matches_backup"] is True
    assert by_op["deterministic_rebuild"]["status"] == "passed"
    assert by_op["rollback"]["generation"] == 1
    # Rebuild digest is stable hex.
    assert gate.SHA256_RE.match(by_op["deterministic_rebuild"]["digest"])


def test_privacy_lifecycle_shared_state_isolation() -> None:
    shared: dict[str, Any] = {}
    a = gate.run_privacy_lifecycle_suite(shared)
    b = gate.run_privacy_lifecycle_suite()
    assert a["status"] == "passed"
    assert b["status"] == "passed"
    # Shared state was rolled back to generation 1 by the suite.
    assert shared["meta"]["generation"] == 1


# ---------------------------------------------------------------------------
# Digest / gate properties
# ---------------------------------------------------------------------------


def test_digest_inventory_complete_and_deterministic() -> None:
    first = gate.compute_all_digests(_REPO_ROOT)
    second = gate.compute_all_digests(_REPO_ROOT)
    assert first["all_complete"] is True
    assert first["aggregate_sha256"] == second["aggregate_sha256"]
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
        assert first[key]["complete"] is True, key
        assert first[key]["digest_sha256"] == second[key]["digest_sha256"]
        assert gate.SHA256_RE.match(first[key]["digest_sha256"])
        assert first[key]["missing"] == []


def test_version_pins_bound_from_v2_recipe() -> None:
    versions = gate.load_version_pins(_REPO_ROOT)
    assert versions["parser"]
    assert versions["ruleset"]
    assert versions["compiler"]
    assert versions["prover"]
    fixture = versions["fixture"]
    assert fixture["gold_manifest_sha256"]
    assert fixture["v2_recipe_sha256"]
    assert fixture["metric_gates_sha256"]
    assert fixture["named_processor_count"] >= 1


def test_unknown_and_blocked_gates_block_receipt_status() -> None:
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


def test_task_and_goal_status_are_rejected_substitutes() -> None:
    for kind in (
        "task_status",
        "todo_status",
        "backlog_status",
        "goal_status",
        "completion_flag",
        "coverage",
    ):
        assert gate.is_rejected_substitute(kind)
    g = gate.make_gate(
        "fake",
        status="passed",
        detail="todo done",
        evidence_kind="goal_status",
    )
    assert g["status"] == "failed"
    assert g["evidence_kind"] == "rejected_substitute"


def test_task_status_alone_cannot_reconcile_goal() -> None:
    assert gate._task_status_only_would_pass() is False
    gate.validate_task_status_alone_rejected()


def test_open_legal_review_exception_blocks() -> None:
    digests = gate.compute_all_digests(_REPO_ROOT)
    versions = gate.load_version_pins(_REPO_ROOT)
    git_info = gate.inspect_git(_REPO_ROOT)
    blocked = gate.build_independent_legal_review(
        digests=digests,
        versions=versions,
        git_info=git_info,
        exceptions=[
            {
                "exception_id": "exc-prop-1",
                "axis": "privacy_boundary_policy",
                "status": "open",
                "summary_ref": "exception-ref:prop-open",
            }
        ],
    )
    assert blocked["status"] == "blocked"
    assert blocked["open_exception_count"] == 1
    assert blocked["independent"] is True
    assert blocked["human_review"] is True
    assert set(gate.LEGAL_REVIEW_SCOPE_AXES) <= set(blocked["scope"]["axes"])


def test_closed_exceptions_do_not_block_legal_review() -> None:
    digests = gate.compute_all_digests(_REPO_ROOT)
    versions = gate.load_version_pins(_REPO_ROOT)
    git_info = gate.inspect_git(_REPO_ROOT)
    ok = gate.build_independent_legal_review(
        digests=digests,
        versions=versions,
        git_info=git_info,
        exceptions=[
            {
                "exception_id": "exc-closed-1",
                "axis": "metric_gates",
                "status": "closed",
                "summary_ref": "exception-ref:closed",
            }
        ],
    )
    assert ok["status"] == "accepted"
    assert ok["open_exception_count"] == 0


def test_adversarial_unknown_remains_blocked_property() -> None:
    for family in ("", "not_a_family", "zero_day_x"):
        d = gate.classify_adversarial_input({"family": family})
        assert d["status"] == "blocked"
        assert d["disclosure"] is False


def test_offline_receipt_binds_all_digest_categories() -> None:
    receipt = gate.collect_tree_evidence(_REPO_ROOT, mode="offline")
    digests = receipt["digests"]
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
    assert digests["aggregate_sha256"]
    assert receipt["supervisor_merge_receipts"]["receipts"]
    assert receipt["independent_legal_review"]["scope"]["axes"]
    assert receipt["migration"]["fail_without_mutation"] is True
    assert receipt["adversarial_assurance"]["no_disclosure_evidence"] is True
    pce = receipt["adversarial_assurance"]["provider_call_evidence"]
    assert pce["calls_attempted"] == 0
    assert pce["credentials_resolved"] is False


def test_canonical_json_and_digest_are_order_independent() -> None:
    a = {"z": 1, "a": {"y": 2, "b": 3}}
    b = {"a": {"b": 3, "y": 2}, "z": 1}
    assert gate.canonical_json(a) == gate.canonical_json(b)
    assert gate.sha256_hex(gate.canonical_json(a)) == gate.sha256_hex(
        gate.canonical_json(b)
    )


def test_content_free_rejects_secret_markers() -> None:
    with pytest.raises(gate.ReleaseGateError):
        gate.assert_content_free({"note": "authorization: bearer leaked-token"})
    with pytest.raises(gate.ReleaseGateError):
        gate.assert_content_free({"api_key": "should-not-appear"})
    with pytest.raises(gate.ReleaseGateError):
        gate.assert_content_free({"note": "prompt-injection-payload-secret-x"})
