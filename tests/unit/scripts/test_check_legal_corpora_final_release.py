"""Hermetic combined final-release controls for LCR-069."""

from __future__ import annotations

import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest


MODULE = "scripts.ops.legal_data.check_legal_corpora_final_release"


@pytest.fixture(scope="module")
def check():
    return importlib.import_module(MODULE)


def _write_board(check, root: Path, *, incomplete: int | None = None) -> Path:
    blocks: list[str] = []
    for index in range(check.SEALED_INITIAL_LAST + 1):
        task_id = f"LCR-{index:03d}"
        if index == check.SEALED_INITIAL_LAST:
            status = "todo"
        elif index == incomplete:
            status = "blocked"
        else:
            status = "completed"
        blocks.append(
            f"## {task_id} Synthetic task\n"
            f"- Status: {status}\n"
            "- Goal id: LCR-G000\n"
        )
    blocks.append(
        "## LCR-094 Post-terminal consumer\n"
        "- Status: todo\n"
        "- Goal id: LCR-G150\n"
    )
    path = root / check.TODO_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def _sealed_receipt(check) -> dict:
    return {
        "acceptance": check.expected_acceptance(),
        "board": {
            "missing_work": [],
            "ready_blocked_active": [],
            "status_projection": {"all_lanes_have_completed_task_state": True},
        },
        "fixture_only": False,
        "gate_count": len(check.ROOT_GATE_IDS),
        "live_network": False,
        "mutation_executed": False,
        "pins": {"count": 4},
        "schema": check.RECEIPT_SCHEMA,
        "status": "sealed",
        "task_id": check.TASK_ID,
    }


def test_help_identity_and_source_has_no_remote_writer(check) -> None:
    assert check.main(["--help"]) == 0
    assert check.TASK_ID == "LCR-069"
    assert check.DEPENDS_ON == ("LCR-068",)
    assert check.ROOT_GOAL_ID == "LCR-G000"
    assert check.FIRST_PACKAGE_ID == "FR-1936-03-14"
    assert check.FIRST_ISSUE_DATE == "1936-03-14"
    source = Path(check.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "HfApi",
        "upload_folder",
        "invoke_protected_hf_write",
        "authorize_and_mutate(",
    ):
        assert forbidden not in source
    assert "bounded refill" in source
    assert "completion reconciliation" in source


def test_root_gate_and_acceptance_contracts_are_complete(check) -> None:
    assert len(check.ROOT_GATE_IDS) == 15
    assert check.ROOT_GATE_IDS[0] == "exact_51_plus_dc"
    assert check.ROOT_GATE_IDS[-1] == (
        "combined_terminal_binds_pins_manifests_canaries_gaps"
    )
    acceptance = check.expected_acceptance()
    assert acceptance["exact_51_plus_dc"] is True
    assert acceptance["federal_first_issue_and_frontier"] is True
    assert acceptance["every_root_gate_passes_against_both_public_revisions"] is True
    assert acceptance["fixture_only"] is False
    assert acceptance["no_remote_mutation"] is True
    assert acceptance["no_unresolved_refill_finding"] is True


def test_public_pair_and_manifest_extraction_fail_closed(check) -> None:
    receipt = {
        "public_sha": "a" * 40,
        "previous_public_pin": "b" * 40,
        "final_manifest_digest": "c" * 64,
    }
    assert check.extract_public_pair(receipt, corpus="test") == (
        "a" * 40,
        "b" * 40,
    )
    assert check.extract_manifest_digest(receipt, name="test") == "c" * 64
    with pytest.raises(check.FinalReleaseMismatchError, match="equals"):
        check.extract_public_pair(
            {"public_sha": "a" * 40, "old_sha": "a" * 40}, corpus="test"
        )
    with pytest.raises((check.FinalReleaseMismatchError, check.MutableRevisionError)):
        check.extract_public_pair(
            {"public_sha": "main", "old_sha": "b" * 40}, corpus="test"
        )
    with pytest.raises(check.FinalReleaseMismatchError, match="SHA-256"):
        check.extract_manifest_digest({"manifest_digest": "bad"}, name="test")


def test_board_reconciliation_accepts_only_closed_predecessors(check, tmp_path) -> None:
    _write_board(check, tmp_path)
    result = check.reconcile_completion(repo_root=tmp_path)
    assert result["missing_work"] == []
    assert result["sealed_initial_complete_except_terminal"] is True
    assert result["terminal_status"] == "todo"
    assert result["post_terminal_consumers"] == ["LCR-094"]

    _write_board(check, tmp_path, incomplete=12)
    with pytest.raises(check.FinalReleaseMismatchError, match="incomplete"):
        check.reconcile_completion(repo_root=tmp_path)


def test_board_reconciliation_rejects_missing_or_open_continuation(
    check, tmp_path
) -> None:
    board = _write_board(check, tmp_path)
    text = board.read_text(encoding="utf-8")
    board.write_text(text.replace("## LCR-010 Synthetic task", "## OTHER-010 Synthetic task"), encoding="utf-8")
    with pytest.raises(check.FinalReleaseMismatchError, match="missing tasks"):
        check.reconcile_completion(repo_root=tmp_path)

    _write_board(check, tmp_path)
    with board.open("a", encoding="utf-8") as handle:
        handle.write(
            "\n## LCR-070 Open continuation\n"
            "- Status: ready\n"
            "- Goal id: LCR-G010\n"
        )
    with pytest.raises(check.FinalReleaseMismatchError, match="continuation"):
        check.reconcile_completion(repo_root=tmp_path)


def test_status_projection_is_explicit_and_confined_to_temp_root(check, tmp_path) -> None:
    _write_board(check, tmp_path)
    config = tmp_path / check.STATUS_CONFIG_RELPATH
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "max_lanes": 3,
                "runtime_paths": {"state": check.STATUS_STATE_RELPATH.as_posix()},
                "task_prefix": "lcr-test",
            }
        ),
        encoding="utf-8",
    )
    board = check.reconcile_completion(repo_root=tmp_path)
    result = check.project_terminal_status_completion(
        repo_root=tmp_path,
        board=board,
    )
    assert result["ok"] is True
    assert result["lane_count"] == 3
    assert len(result["written"]) == 3
    for relpath in result["written"]:
        path = tmp_path / relpath
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["completed_count"] == payload["task_count"]
        assert payload["ready_count"] == 0
        assert payload["blocked_count"] == 0
        assert payload["implementation_in_progress"] is False


def test_status_projection_refuses_missing_work(check, tmp_path) -> None:
    config = tmp_path / check.STATUS_CONFIG_RELPATH
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "max_lanes": 1,
                "runtime_paths": {"state": check.STATUS_STATE_RELPATH.as_posix()},
                "task_prefix": "lcr-test",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(check.FinalReleaseMismatchError, match="missing work"):
        check.project_terminal_status_completion(
            repo_root=tmp_path,
            board={"missing_work": ["LCR-001"], "ready_blocked_active": []},
        )


def test_root_gate_builder_rejects_false_and_keeps_relative_evidence(check) -> None:
    item = check._gate(
        "example",
        passed=True,
        path=Path("docs/reports/example.json"),
        digest="a" * 64,
        public_sha="b" * 40,
    )
    assert item == {
        "digest": "a" * 64,
        "id": "example",
        "passed": True,
        "path": "docs/reports/example.json",
        "public_sha": "b" * 40,
    }
    with pytest.raises(check.FinalReleaseMismatchError, match="root gate failed"):
        check._gate(
            "example",
            passed=False,
            path=Path("docs/reports/example.json"),
            digest="a" * 64,
        )


def test_bounded_refill_scan_rejects_open_finding(
    check, tmp_path, monkeypatch
) -> None:
    relpath = Path("docs/reports/one.json")
    path = tmp_path / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"findings": []}), encoding="utf-8")
    monkeypatch.setattr(check, "BOUND_EVIDENCE", (("one", relpath),))
    monkeypatch.setattr(check, "load_state_publication", lambda **_: {})
    monkeypatch.setattr(check, "load_federal_publication", lambda **_: {})
    monkeypatch.setattr(check, "load_state_post_publication_audit", lambda **_: {})
    monkeypatch.setattr(check, "load_state_final_receipt", lambda **_: {})
    monkeypatch.setattr(
        check,
        "audit_refill_closure",
        lambda **_: {"closed": True, "unresolved_count": 0},
    )
    result = check.scan_bounded_refill(repo_root=tmp_path)
    assert result["bounded"] is True
    assert result["scanned_count"] == 1
    assert result["unresolved_count"] == 0

    path.write_text(
        json.dumps({"findings": [{"status": "open", "kind": "gap"}]}),
        encoding="utf-8",
    )
    with pytest.raises(check.FinalReleaseMismatchError, match="unresolved work"):
        check.scan_bounded_refill(repo_root=tmp_path)


def test_check_is_read_only_and_does_not_project_status(
    check, tmp_path, monkeypatch
) -> None:
    receipt = _sealed_receipt(check)
    path = tmp_path / "final_release_receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(check, "build_final_receipt", lambda **_: deepcopy(receipt))
    monkeypatch.setattr(check, "prove_public_revisions", lambda **_: {"ok": True})
    monkeypatch.setattr(
        check,
        "project_terminal_status_completion",
        lambda **_: pytest.fail("--check must not write scheduler state"),
    )
    result = check.check_final_release(path=path, repo_root=tmp_path)
    assert result["ok"] is True
    assert result["status_projection"]["read_only"] is True
    assert result["status_projection"]["written"] == []


def test_missing_receipt_fails_without_fabricating_evidence(check, tmp_path) -> None:
    missing = tmp_path / "final_release_receipt.json"
    with pytest.raises(check.FinalReleaseMissingInputError):
        check.check_final_release(path=missing, repo_root=tmp_path)
    assert not missing.exists()


def test_receipt_comparison_ignores_only_self_digest_fields(check) -> None:
    left = {"task_id": "LCR-069", "value": 1, "digest": "a" * 64}
    right = {"task_id": "LCR-069", "value": 1, "digest": "b" * 64}
    assert check.compare_receipts(left, right) == []
    right["value"] = 2
    assert check.compare_receipts(left, right) == ["field mismatch: value"]


def test_fixture_public_canary_cannot_satisfy_terminal_pin_contract(check) -> None:
    with pytest.raises(check.FederalPublicPinError):
        check.assert_federal_public_pin_contract(
            {
                "fixture_only": True,
                "live_network": False,
                "public_sha": "a" * 40,
            }
        )


def test_secret_path_and_explicit_temp_output_guards(check, tmp_path) -> None:
    with pytest.raises(check.FinalReleaseSafetyError):
        check.reject_secrets_in_argv(["--hf_token=hf_abcdefghijklmnopqrstuvwxyz"])
    with pytest.raises(check.FinalReleaseSafetyError):
        check.reject_credentials_in_payload(
            {"authorization": "Bearer secret"}, label="test"
        )
    with pytest.raises(check.FinalReleaseSafetyError):
        check.reject_path_leaks({"path": "/home/operator/private"}, label="test")
    output = tmp_path / "receipt.json"
    check.write_json(output, {"task_id": "LCR-069"})
    assert json.loads(output.read_text(encoding="utf-8"))["task_id"] == "LCR-069"
