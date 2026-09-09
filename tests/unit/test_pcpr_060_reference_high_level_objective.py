"""PCPR-060: Datasets binding to the reference high-level objective."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.reference_high_level_objective import (
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    OPERATOR_BLOCKING_TASK_ID,
    OBJECTIVE_KIND,
    OutcomeProbe,
    PCPR_060_GOAL_ID,
    PCPR_060_TASK_ID,
    PINNED_IDEA_DIGEST,
    PINNED_LOCK_CID,
    PINNED_OBJECTIVE_CID,
    SCHEMA,
    SEALED_PATH,
    SEALED_PYTHON,
    DatasetsReferenceHighLevelObjectiveError,
    current_head_static_probes,
    pcpr_060_receipt_promotion,
    qualify_current_head_reference_high_level_objective,
    qualify_reference_high_level_objective,
    refuse_idea_digest_remint,
    refuse_lock_remint,
    refuse_objective_remint,
    render_declared_binding,
    verify_reference_objective_files,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_060_requirements() -> None:
    assert PCPR_060_TASK_ID == "PCPR-060"
    assert PCPR_060_GOAL_ID == "PCPR-G700"
    assert INTERFACE == "DatasetsReferenceHighLevelObjectiveBinding@1"
    assert SCHEMA == (
        "ipfs_datasets_py/assurance/reference-high-level-objective-binding@1"
    )
    assert OBJECTIVE_KIND == "declared_reference_high_level_objective_binding"
    assert OPERATOR_BLOCKING_TASK_ID == (
        "pcpr-060-operator-live-objective-materialization"
    )
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith(
        "test_pcpr_060_reference_high_level_objective.py"
    )
    assert SEALED_PATH == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
    assert SEALED_PYTHON == "/usr/bin/python3.12"
    binding = render_declared_binding()
    assert binding["applied"] is False
    assert binding["live"] is False
    assert binding["release_claim"] is False
    assert binding["closed_release_outcome"] is None
    assert binding["context_pack"]["constructed"] is False
    assert binding["duckdb_or_quack_state_written"] is False
    assert binding["lock_cid"] == PINNED_LOCK_CID
    assert binding["objective_cid"] == PINNED_OBJECTIVE_CID
    assert binding["idea_digest"] == PINNED_IDEA_DIGEST
    assert binding["operator_blocking_task"]["status"] == "typed_blocked"
    assert refuse_objective_remint(PINNED_OBJECTIVE_CID) == PINNED_OBJECTIVE_CID
    assert refuse_idea_digest_remint(PINNED_IDEA_DIGEST) == PINNED_IDEA_DIGEST
    assert refuse_lock_remint(PINNED_LOCK_CID) == PINNED_LOCK_CID
    with pytest.raises(DatasetsReferenceHighLevelObjectiveError, match="remints"):
        refuse_objective_remint(
            "baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_reference_high_level_objective()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.sibling_source_required is False
    assert verdict.live_objective_submission is False
    assert verdict.live_materialization is False
    assert verdict.live_context_pack is False
    assert verdict.operator_blocking_task == OPERATOR_BLOCKING_TASK_ID
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.blockers == ()
    section = pcpr_060_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_declared_binding_constraints() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["binding_files_match_generator"].present is True
    assert probes["pyproject_reference_high_level_objective_table"].present is True
    assert probes["manifest_advertises_reference_high_level_objective"].present is True
    assert probes["objective_cid_matches_pin"].present is True
    assert probes["idea_digest_matches_pin"].present is True
    assert probes["lock_cid_matches_pin"].present is True
    assert probes["context_pack_not_constructed"].present is True
    assert probes["operator_blocking_task_emitted"].present is True
    assert probes["context_pack_constructed"].present is False
    assert probes["sibling_import_observed"].present is False
    assert probes["live_materialization"].evidence_kind == "unavailable"
    for probe in probes.values():
        assert probe.live is False
        assert probe.simulated_represented_as_live is False


def test_manifest_advertises_reference_high_level_objective() -> None:
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions["DatasetsReferenceHighLevelObjectiveBinding@1"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots[
        "datasets_reference_high_level_objective"
    ].endswith("reference-high-level-objective-binding@1")
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions[
        "reference_high_level_objective"
    ] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_repository_layout() is False


def test_committed_files_match_generator() -> None:
    verified = verify_reference_objective_files()
    assert verified["ok"] is True
    pyproject = (_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'interface = "DatasetsReferenceHighLevelObjectiveBinding@1"' in pyproject


def test_simulated_live_probe_is_rejected() -> None:
    with pytest.raises(DatasetsReferenceHighLevelObjectiveError, match="simulated"):
        qualify_reference_high_level_objective(
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
            objective_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            idea_digest_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            binding_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
