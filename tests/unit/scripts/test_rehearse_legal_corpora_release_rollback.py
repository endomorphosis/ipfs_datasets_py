"""Hermetic dual-release rollback controls for LCR-068."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


MODULE = "scripts.ops.legal_data.rehearse_legal_corpora_release_rollback"


@pytest.fixture(scope="module")
def rehearsal():
    return importlib.import_module(MODULE)


def _new_pins(rehearsal) -> tuple[str, str]:
    reserved = {
        rehearsal.STATE_PREVIOUS_PUBLIC_PIN,
        rehearsal.FEDERAL_PREVIOUS_PUBLIC_PIN,
    }
    choices = ("a" * 40, "b" * 40, "c" * 40, "d" * 40)
    available = [pin for pin in choices if pin not in reserved]
    assert len(available) >= 2
    return available[0], available[1]


def _query_evidence(rehearsal) -> dict:
    state_new, federal_new = _new_pins(rehearsal)
    return {
        "state_new": state_new,
        "state_previous": rehearsal.STATE_PREVIOUS_PUBLIC_PIN,
        "federal_new": federal_new,
        "federal_previous": rehearsal.FEDERAL_PREVIOUS_PUBLIC_PIN,
        "state_canary": {
            "public_sha": state_new,
            "canaries": {"bm25": {"ok": True}, "filter": {"ok": True}},
        },
        "federal_canary": {
            "public_sha": federal_new,
            "acceptance": {
                "public_artifacts_equal_staged_candidate": True,
                "sparse_queries_within_budget": True,
            },
        },
        "state_baseline": {
            "acceptance": {
                "jurisdictions": rehearsal.EXPECTED_JURISDICTION_COUNT,
                "pinned_revision": rehearsal.STATE_HISTORICAL_BASELINE_PIN,
            }
        },
        "federal_baseline": {
            "acceptance": {
                "pinned_revision": rehearsal.FEDERAL_PREVIOUS_PUBLIC_PIN,
            }
        },
        "cross_canary": {
            "acceptance": {
                "cross_corpus_queries_reproducible": True,
                "provenance_safe": True,
            }
        },
    }


def test_help_identity_and_source_is_non_mutating(rehearsal) -> None:
    assert rehearsal.main(["--help"]) == 0
    assert rehearsal.TASK_ID == "LCR-068"
    assert rehearsal.DEPENDS_ON == ("LCR-047", "LCR-067")
    assert rehearsal.PIN_ROLES == (
        "state_new",
        "state_previous",
        "federal_new",
        "federal_previous",
    )
    assert rehearsal.STATE_PREVIOUS_PUBLIC_PIN != (
        rehearsal.STATE_HISTORICAL_BASELINE_PIN
    )
    source = Path(rehearsal.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "HfApi",
        "upload_folder",
        "invoke_protected_hf_write",
        "authorize_and_mutate(",
    ):
        assert forbidden not in source
    assert "without deleting" in source
    assert "daily versus jurisdictional" in source


def test_four_pin_query_rehearsal_is_bounded_and_isolated(rehearsal) -> None:
    result = rehearsal.rehearse_four_pin_query(**_query_evidence(rehearsal))
    assert result["all_four_queryable"] is True
    assert result["cross_pin_trees_isolated"] is True
    assert result["pin_count"] == 4
    assert result["offline"] is True
    assert set(result["after_forward"]) == set(rehearsal.PIN_ROLES)
    assert all(result["after_forward"].values())
    assert all(result["after_rollback"].values())
    assert {item["transport"] for item in (
        result["pins"][role]["fetch"] for role in rehearsal.PIN_ROLES
    )} == {"mapping"}


def test_four_pin_query_rejects_mutable_duplicate_or_unproved_pins(rehearsal) -> None:
    evidence = _query_evidence(rehearsal)
    with pytest.raises((rehearsal.MutableRevisionError, rehearsal.RehearsalMismatchError)):
        rehearsal.rehearse_four_pin_query(**{**evidence, "state_new": "main"})
    with pytest.raises(rehearsal.RehearsalMismatchError, match="four pins"):
        rehearsal.rehearse_four_pin_query(
            **{**evidence, "federal_new": evidence["state_new"]}
        )
    bad_canary = {**evidence["cross_canary"], "acceptance": {}}
    with pytest.raises(rehearsal.RehearsalMismatchError, match="cross-corpus"):
        rehearsal.rehearse_four_pin_query(
            **{**evidence, "cross_canary": bad_canary}
        )


def test_dual_rollback_is_pointer_only_bounded_and_reversible(rehearsal) -> None:
    state_new, federal_new = _new_pins(rehearsal)
    result = rehearsal.rehearse_dual_rollback(
        state_new=state_new,
        state_previous=rehearsal.STATE_PREVIOUS_PUBLIC_PIN,
        state_manifest_digest="1" * 64,
        federal_new=federal_new,
        federal_previous=rehearsal.FEDERAL_PREVIOUS_PUBLIC_PIN,
        federal_manifest_digest="2" * 64,
    )
    assert result["bounded"] is True
    assert result["reversible"] is True
    assert result["pointer_only"] is True
    assert result["deletes"] is False
    assert result["public_advertisement_changed"] is False
    for corpus in ("state_laws", "federal_register"):
        item = result["corpora"][corpus]
        assert item["new_pin_retained"] is True
        assert item["previous_pin_retained"] is True
        assert item["legacy_files_deleted"] is False
        assert item["back"]["payload"]["force_push"] is False
        assert item["forward"]["payload"]["deletes"] is False


def test_rollback_rejects_equal_pins_and_forbidden_operations(rehearsal) -> None:
    with pytest.raises(rehearsal.RehearsalMismatchError, match="must differ"):
        rehearsal.rehearse_corpus_rollback(
            corpus="state_laws",
            dataset_repo_id=rehearsal.DEFAULT_STATE_REPO,
            new_pin="a" * 40,
            previous_pin="a" * 40,
            manifest_digest="1" * 64,
            factory=rehearsal.StateRollbackRecord,
            schema_version="state-laws-rollback-rehearsal/v1",
            back_operation="re_advertise_state_previous_pin",
            forward_operation="re_advertise_state_new_pin",
        )
    with pytest.raises(rehearsal.RehearsalSafetyError, match="forbidden"):
        rehearsal.reject_forbidden_operations(["force_push"])


def test_refill_closure_accepts_closed_ledger_and_rejects_open_work(rehearsal) -> None:
    inputs = {
        "state_publication": {"refill_findings": []},
        "federal_publication": {"refill_findings": []},
        "state_audit": {
            "delta_refill": {
                "count": 0,
                "findings": [],
                "mixed_into_this_release": False,
                "ok": True,
            }
        },
        "state_final": {"acceptance": {"no_unresolved_gap": True}},
    }
    result = rehearsal.audit_refill_closure(**inputs)
    assert result["closed"] is True
    assert result["unresolved_count"] == 0
    with pytest.raises(rehearsal.RehearsalMismatchError, match="unresolved"):
        rehearsal.audit_refill_closure(
            **inputs,
            extra_findings=[{"status": "open", "kind": "test-gap"}],
        )


def test_update_semantics_keep_daily_and_jurisdictional_units_distinct(
    rehearsal,
) -> None:
    audit = {
        "update_checkpoints": {
            "atomic_per_jurisdiction": True,
            "completion_basis": "source_frontier",
        },
        "update_plan": {
            "delta_only": True,
            "preserves_exact_51": True,
            "preserves_transactional_gates": True,
        },
    }
    result = rehearsal.explicit_update_semantics(state_audit=audit)
    assert result["federal_register"]["kind"] == "daily"
    assert result["federal_register"]["unit"] == "publication_date"
    assert result["state_laws"]["kind"] == "jurisdictional"
    assert result["state_laws"]["unit"] == "jurisdiction"
    assert result["must_not_conflate"] is True
    with pytest.raises(rehearsal.RehearsalMismatchError):
        rehearsal.explicit_update_semantics(state_audit={})


def test_live_evidence_loaders_reject_fixture_or_offline_inputs(
    rehearsal, tmp_path
) -> None:
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "fixture_only": True,
                "live_network": False,
                "mutation_executed": False,
                "remote_write_contacted": False,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(rehearsal.RehearsalMismatchError, match="fixture"):
        rehearsal.load_state_publication(path=fixture, repo_root=tmp_path)
    with pytest.raises(rehearsal.RehearsalMismatchError, match="fixture"):
        rehearsal.load_federal_public_canary(path=fixture, repo_root=tmp_path)
    with pytest.raises(rehearsal.RehearsalMismatchError, match="fixture"):
        rehearsal.load_cross_corpus_canary(path=fixture, repo_root=tmp_path)


def test_runbook_documents_combined_operations(rehearsal) -> None:
    result = rehearsal.validate_operator_docs(repo_root=rehearsal.REPOSITORY_ROOT)
    assert result["ok"] is True
    assert result["update_semantics_documented"] is True
    assert result["runbook"]["required_phrase_count"] == len(
        rehearsal.RUNBOOK_REQUIRED_PHRASES
    )


def test_missing_sealed_report_fails_without_creating_evidence(
    rehearsal, tmp_path
) -> None:
    missing = tmp_path / "dual_rollback_rehearsal.json"
    with pytest.raises(rehearsal.RehearsalMissingInputError):
        rehearsal.check_rehearsal(path=missing, repo_root=tmp_path)
    assert not missing.exists()


def test_digest_comparison_and_explicit_temp_output(rehearsal, tmp_path) -> None:
    left = {"task_id": "LCR-068", "value": 1, "digest": "a" * 64}
    right = {"task_id": "LCR-068", "value": 1, "digest": "b" * 64}
    assert rehearsal.compare_rehearsals(left, right) == []
    right["value"] = 2
    assert rehearsal.compare_rehearsals(left, right) == ["field mismatch: value"]
    output = tmp_path / "report.json"
    rehearsal.write_json(output, left)
    assert json.loads(output.read_text(encoding="utf-8"))["task_id"] == "LCR-068"


def test_secret_and_absolute_path_guards(rehearsal) -> None:
    with pytest.raises(rehearsal.RehearsalSafetyError):
        rehearsal.reject_secrets_in_argv(["--hf_token=hf_abcdefghijklmnopqrstuvwxyz"])
    with pytest.raises(rehearsal.RehearsalSafetyError):
        rehearsal.reject_credentials_in_payload(
            {"authorization": "Bearer secret"}, label="test"
        )
    with pytest.raises(rehearsal.RehearsalSafetyError):
        rehearsal.reject_path_leaks({"path": "/home/operator/private"}, label="test")
