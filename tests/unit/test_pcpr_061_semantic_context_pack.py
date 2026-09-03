"""PCPR-061: Datasets-owned semantic ContextPack construction."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.semantic_context_pack import (
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    OPERATOR_BLOCKING_TASK_ID,
    OBJECTIVE_KIND,
    OutcomeProbe,
    PCPR_061_GOAL_ID,
    PCPR_061_TASK_ID,
    PINNED_IDEA_DIGEST,
    PINNED_OBJECTIVE_CID,
    PINNED_PACK_CID,
    PINNED_PACK_DOCUMENT_CID,
    SCHEMA,
    SEALED_PATH,
    SEALED_PYTHON,
    DatasetsSemanticContextPackError,
    current_head_static_probes,
    pcpr_061_receipt_promotion,
    qualify_current_head_semantic_context_pack,
    qualify_semantic_context_pack,
    refuse_idea_digest_remint,
    refuse_objective_remint,
    refuse_pack_cid_remint,
    render_declared_context_pack,
    verify_semantic_context_pack_files,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST
from ipfs_datasets_py.proof_context.context_pack import StaleContextError


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_061_requirements() -> None:
    assert PCPR_061_TASK_ID == "PCPR-061"
    assert PCPR_061_GOAL_ID == "PCPR-G700"
    assert INTERFACE == "DatasetsSemanticContextPack@1"
    assert SCHEMA == "ipfs_datasets_py/assurance/semantic-context-pack@1"
    assert OBJECTIVE_KIND == "declared_semantic_context_pack"
    assert OPERATOR_BLOCKING_TASK_ID == (
        "pcpr-061-operator-live-context-pack-admission"
    )
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith(
        "test_pcpr_061_semantic_context_pack.py"
    )
    assert SEALED_PATH == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
    assert SEALED_PYTHON == "/usr/bin/python3.12"
    document = render_declared_context_pack()
    assert document["applied"] is False
    assert document["live"] is False
    assert document["release_claim"] is False
    assert document["closed_release_outcome"] is None
    assert document["context_pack"]["constructed"] is True
    assert document["context_pack"]["live"] is False
    assert document["context_pack"]["admitted_live"] is False
    assert document["context_pack"]["interface"] == "DatasetsContextPack@1"
    assert document["stale_tree_rejected"] is True
    assert document["duckdb_or_quack_state_written"] is False
    assert document["storage"]["stored"] is False
    assert document["objective_cid"] == PINNED_OBJECTIVE_CID
    assert document["idea_digest"] == PINNED_IDEA_DIGEST
    assert document["context_pack"]["pack_cid"] == PINNED_PACK_CID
    assert document["pack_document_cid"] == PINNED_PACK_DOCUMENT_CID
    assert document["operator_blocking_task"]["status"] == "typed_blocked"
    assert refuse_pack_cid_remint(PINNED_PACK_CID) == PINNED_PACK_CID
    assert refuse_objective_remint(PINNED_OBJECTIVE_CID) == PINNED_OBJECTIVE_CID
    assert refuse_idea_digest_remint(PINNED_IDEA_DIGEST) == PINNED_IDEA_DIGEST
    with pytest.raises(DatasetsSemanticContextPackError, match="remints"):
        refuse_pack_cid_remint(
            "baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_semantic_context_pack()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.sibling_source_required is False
    assert verdict.live_context_pack_admission is False
    assert verdict.live_solver_impact is False
    assert verdict.live_storage is False
    assert verdict.operator_blocking_task == OPERATOR_BLOCKING_TASK_ID
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.pack_cid == PINNED_PACK_CID
    assert verdict.blockers == ()
    section = pcpr_061_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_declared_pack_constraints() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["pack_files_match_generator"].present is True
    assert probes["pyproject_semantic_context_pack_table"].present is True
    assert probes["manifest_advertises_semantic_context_pack"].present is True
    assert probes["datasets_context_pack_admitted"].present is True
    assert probes["pack_cid_matches_pin"].present is True
    assert probes["semantic_impact_inspected"].present is True
    assert probes["stale_tree_rejected"].present is True
    assert probes["selected_tests_only"].present is True
    assert probes["unaffected_proofs_marked_reusable"].present is True
    assert probes["proof_obligations_declared_not_verified"].present is True
    assert probes["storage_deferred_to_pcpr_062"].present is True
    assert probes["current_root_published"].present is False
    assert probes["sibling_import_observed"].present is False
    assert probes["live_context_pack_admission"].evidence_kind == "unavailable"
    assert probes["live_solver_impact"].evidence_kind == "unavailable"
    for probe in probes.values():
        assert probe.live is False
        assert probe.simulated_represented_as_live is False


def test_manifest_advertises_semantic_context_pack() -> None:
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions["DatasetsSemanticContextPack@1"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots[
        "datasets_semantic_context_pack"
    ].endswith("semantic-context-pack@1")
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions[
        "semantic_context_pack"
    ] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False


def test_committed_files_match_generator() -> None:
    verified = verify_semantic_context_pack_files()
    assert verified["ok"] is True
    pyproject = (_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'interface = "DatasetsSemanticContextPack@1"' in pyproject


def test_stale_and_simulated_live_probes_are_rejected() -> None:
    from ipfs_datasets_py.assurance.semantic_context_pack import (
        mint_datasets_context_pack,
    )
    from ipfs_datasets_py.proof_context.context_pack import admit_datasets_context_pack

    minted = mint_datasets_context_pack(_PACKAGE_ROOT)
    with pytest.raises(StaleContextError):
        admit_datasets_context_pack(
            {
                "repository_state_cid": minted["repository_state_cid"],
                "scanned_tree_oid": minted["scanned_tree_oid"],
                "surrounding_source_cid": minted["required_source_cids"][
                    "surrounding_source"
                ],
                "target_source_cid": minted["required_source_cids"]["target_source"],
                "test_source_cid": minted["required_source_cids"]["test_source"],
                "task_id": PCPR_061_TASK_ID,
                "freshness": "stale",
            }
        )
    with pytest.raises(DatasetsSemanticContextPackError, match="simulated"):
        qualify_semantic_context_pack(
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
            pack_document_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            objective_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            idea_digest_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
    with pytest.raises(DatasetsSemanticContextPackError, match="measured_live"):
        qualify_semantic_context_pack(
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
            pack_document_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            objective_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            idea_digest_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
