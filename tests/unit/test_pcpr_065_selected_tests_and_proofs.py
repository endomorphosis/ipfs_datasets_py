"""PCPR-065: Datasets binding to Accelerate selected tests and proofs."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.selected_tests_and_proofs import (
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    ESCALATION_ORDER,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    OPERATOR_BLOCKING_TASK_ID,
    OBJECTIVE_KIND,
    OutcomeProbe,
    PCPR_065_GOAL_ID,
    PCPR_065_TASK_ID,
    PINNED_BINDING_CID,
    PINNED_CURRENT_ROOT_CID,
    PINNED_IDEA_DIGEST,
    PINNED_OBJECTIVE_CID,
    PINNED_PACK_CID,
    PINNED_PATCH_CID,
    PINNED_ROUTE_CID,
    SCHEMA,
    SEALED_PATH,
    SEALED_PYTHON,
    SELECTED_TESTS,
    DatasetsSelectedTestsAndProofsError,
    current_head_static_probes,
    pcpr_065_receipt_promotion,
    qualify_current_head_selected_tests_and_proofs,
    qualify_selected_tests_and_proofs,
    refuse_incomplete_selection_as_sufficient,
    refuse_model_completion,
    refuse_pack_cid_remint,
    refuse_patch_cid_remint,
    refuse_route_cid_remint,
    render_declared_binding,
    selected_tests_owned_by_datasets,
    verify_selected_tests_and_proofs_files,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_065_requirements() -> None:
    assert PCPR_065_TASK_ID == "PCPR-065"
    assert PCPR_065_GOAL_ID == "PCPR-G700"
    assert INTERFACE == "DatasetsSelectedTestsAndProofsBinding@1"
    assert SCHEMA == (
        "ipfs_datasets_py/assurance/selected-tests-and-proofs-binding@1"
    )
    assert OBJECTIVE_KIND == "declared_selected_tests_and_proofs_binding"
    assert OPERATOR_BLOCKING_TASK_ID == (
        "pcpr-065-operator-live-selected-tests-and-proofs"
    )
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith(
        "test_pcpr_065_selected_tests_and_proofs.py"
    )
    assert SEALED_PATH == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
    assert SEALED_PYTHON == "/usr/bin/python3.12"
    binding = render_declared_binding()
    assert binding["applied"] is False
    assert binding["live"] is False
    assert binding["release_claim"] is False
    assert binding["closed_release_outcome"] is None
    assert binding["context_pack"]["constructed"] is True
    assert binding["context_pack"]["constructed_by"] == "ipfs_datasets_py"
    assert binding["context_pack"]["reminted"] is False
    assert binding["storage"]["stored"] is True
    assert binding["storage"]["stored_by"] == "ipfs_kit_py"
    assert binding["route"]["executed"] is True
    assert binding["route"]["executed_by"] == "ipfs_accelerate_py"
    assert binding["bounded_patch"]["produced"] is True
    assert binding["bounded_patch"]["produced_by"] == "ipfs_accelerate_py"
    assert binding["bounded_patch"]["live"] is False
    assert binding["bounded_patch"]["remints_protocol"] is False
    assert binding["selected_tests"]["run"] is True
    assert binding["selected_tests"]["live"] is False
    assert binding["selected_tests"]["owned_by"] == "ipfs_datasets_py"
    assert binding["selected_tests"]["executed_by"] == "ipfs_accelerate_py"
    assert list(binding["selected_tests"]["paths"]) == list(SELECTED_TESTS)
    assert binding["selected_tests"][
        "incomplete_selection_requires_full_validation"
    ] is True
    assert binding["duckdb_or_quack_state_written"] is False
    assert binding["objective_cid"] == PINNED_OBJECTIVE_CID
    assert binding["idea_digest"] == PINNED_IDEA_DIGEST
    assert binding["context_pack"]["pack_cid"] == PINNED_PACK_CID
    assert binding["storage"]["current_root_cid"] == PINNED_CURRENT_ROOT_CID
    assert binding["route"]["route_cid"] == PINNED_ROUTE_CID
    assert binding["bounded_patch"]["patch_cid"] == PINNED_PATCH_CID
    assert binding["binding_cid"] == PINNED_BINDING_CID
    assert binding["operator_blocking_task"]["status"] == "typed_blocked"
    assert tuple(binding["escalation_order"]) == ESCALATION_ORDER
    assert refuse_pack_cid_remint(PINNED_PACK_CID) == PINNED_PACK_CID
    assert refuse_route_cid_remint(PINNED_ROUTE_CID) == PINNED_ROUTE_CID
    assert refuse_patch_cid_remint(PINNED_PATCH_CID) == PINNED_PATCH_CID
    with pytest.raises(DatasetsSelectedTestsAndProofsError, match="remints"):
        refuse_pack_cid_remint(
            "baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
    with pytest.raises(DatasetsSelectedTestsAndProofsError, match="cannot complete"):
        refuse_model_completion("medium_model")
    with pytest.raises(
        DatasetsSelectedTestsAndProofsError, match="cannot count as selected-test"
    ):
        refuse_incomplete_selection_as_sufficient(
            incomplete=True,
            full_validation_required=False,
        )
    assert selected_tests_owned_by_datasets() is True


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_selected_tests_and_proofs()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.sibling_source_required is False
    assert verdict.live_application is False
    assert verdict.live_selected_tests is False
    assert verdict.operator_blocking_task == OPERATOR_BLOCKING_TASK_ID
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.pack_cid == PINNED_PACK_CID
    assert verdict.binding_cid == PINNED_BINDING_CID
    assert verdict.patch_cid == PINNED_PATCH_CID
    assert verdict.route_cid == PINNED_ROUTE_CID
    assert verdict.current_root_cid == PINNED_CURRENT_ROOT_CID
    assert verdict.blockers == ()
    section = pcpr_065_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_declared_binding_constraints() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["binding_files_match_generator"].present is True
    assert probes["pyproject_selected_tests_and_proofs_table"].present is True
    assert probes["manifest_advertises_selected_tests_and_proofs"].present is True
    assert probes["owner_pack_cid_matches_pin"].present is True
    assert probes["run_owned_by_accelerate"].present is True
    assert probes["protocol_identity_not_reminted"].present is True
    assert probes["selected_tests_owned_by_datasets"].present is True
    assert probes["incomplete_selection_requires_full_validation"].present is True
    assert probes["model_assertion_cannot_complete_work"].present is True
    assert probes["sibling_import_observed"].present is False
    assert probes["datasets_identity_reminted"].present is False
    assert probes["kit_identity_reminted"].present is False
    assert probes["live_selected_tests"].evidence_kind == "unavailable"
    for probe in probes.values():
        assert probe.live is False
        assert probe.simulated_represented_as_live is False


def test_manifest_advertises_selected_tests_and_proofs() -> None:
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions["DatasetsSelectedTestsAndProofsBinding@1"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots[
        "datasets_selected_tests_and_proofs"
    ].endswith("selected-tests-and-proofs-binding@1")
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions[
        "selected_tests_and_proofs"
    ] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False


def test_committed_files_match_generator() -> None:
    verified = verify_selected_tests_and_proofs_files()
    assert verified["ok"] is True
    pyproject = (_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'interface = "DatasetsSelectedTestsAndProofsBinding@1"' in pyproject


def test_simulated_live_probe_is_rejected() -> None:
    with pytest.raises(DatasetsSelectedTestsAndProofsError, match="simulated"):
        qualify_selected_tests_and_proofs(
            (
                OutcomeProbe(
                    probe_id="bogus",
                    present=False,
                    evidence_kind="simulated",
                    live=False,
                    simulated_represented_as_live=True,
                    reason="must fail",
                ),
            ),
            pack_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            binding_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            patch_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            route_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            current_root_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            objective_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            idea_digest_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
    with pytest.raises(DatasetsSelectedTestsAndProofsError, match="measured_live"):
        qualify_selected_tests_and_proofs(
            (
                OutcomeProbe(
                    probe_id="bogus",
                    present=True,
                    evidence_kind="measured",
                    live=True,
                    simulated_represented_as_live=False,
                    reason="must fail",
                ),
            ),
            pack_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            binding_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            patch_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            route_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            current_root_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            objective_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            idea_digest_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
