"""PCPR-062: Datasets binding to the Kit ContextPack current root."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.context_pack_storage import (
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    OPERATOR_BLOCKING_TASK_ID,
    OBJECTIVE_KIND,
    OutcomeProbe,
    PCPR_062_GOAL_ID,
    PCPR_062_TASK_ID,
    PINNED_BINDING_CID,
    PINNED_CURRENT_ROOT_CID,
    PINNED_IDEA_DIGEST,
    PINNED_OBJECTIVE_CID,
    PINNED_PACK_CID,
    SCHEMA,
    SEALED_PATH,
    SEALED_PYTHON,
    DatasetsContextPackStorageError,
    current_head_static_probes,
    pcpr_062_receipt_promotion,
    qualify_context_pack_storage,
    qualify_current_head_context_pack_storage,
    refuse_current_root_remint,
    refuse_pack_cid_remint,
    render_declared_binding,
    verify_context_pack_storage_files,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_062_requirements() -> None:
    assert PCPR_062_TASK_ID == "PCPR-062"
    assert PCPR_062_GOAL_ID == "PCPR-G700"
    assert INTERFACE == "DatasetsContextPackStorageBinding@1"
    assert SCHEMA == "ipfs_datasets_py/assurance/context-pack-storage-binding@1"
    assert OBJECTIVE_KIND == "declared_context_pack_root_binding"
    assert OPERATOR_BLOCKING_TASK_ID == "pcpr-062-operator-live-context-pack-root"
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith(
        "test_pcpr_062_context_pack_storage.py"
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
    assert binding["storage"]["current_root_published"] is True
    assert binding["storage"]["live"] is False
    assert binding["execution"]["performed"] is False
    assert binding["duckdb_or_quack_state_written"] is False
    assert binding["objective_cid"] == PINNED_OBJECTIVE_CID
    assert binding["idea_digest"] == PINNED_IDEA_DIGEST
    assert binding["context_pack"]["pack_cid"] == PINNED_PACK_CID
    assert binding["storage"]["current_root_cid"] == PINNED_CURRENT_ROOT_CID
    assert binding["binding_cid"] == PINNED_BINDING_CID
    assert binding["operator_blocking_task"]["status"] == "typed_blocked"
    assert refuse_pack_cid_remint(PINNED_PACK_CID) == PINNED_PACK_CID
    assert refuse_current_root_remint(PINNED_CURRENT_ROOT_CID) == PINNED_CURRENT_ROOT_CID
    with pytest.raises(DatasetsContextPackStorageError, match="remints"):
        refuse_pack_cid_remint(
            "baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_context_pack_storage()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.sibling_source_required is False
    assert verdict.live_storage is False
    assert verdict.live_current_root is False
    assert verdict.operator_blocking_task == OPERATOR_BLOCKING_TASK_ID
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.pack_cid == PINNED_PACK_CID
    assert verdict.binding_cid == PINNED_BINDING_CID
    assert verdict.current_root_cid == PINNED_CURRENT_ROOT_CID
    assert verdict.blockers == ()
    section = pcpr_062_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_declared_binding_constraints() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["binding_files_match_generator"].present is True
    assert probes["pyproject_context_pack_storage_table"].present is True
    assert probes["manifest_advertises_context_pack_storage"].present is True
    assert probes["owner_pack_cid_matches_pin"].present is True
    assert probes["kit_current_root_bound_not_minted"].present is True
    assert probes["storage_owned_by_kit"].present is True
    assert probes["sibling_import_observed"].present is False
    assert probes["datasets_identity_reminted"].present is False
    assert probes["kit_identity_reminted"].present is False
    assert probes["live_storage"].evidence_kind == "unavailable"
    for probe in probes.values():
        assert probe.live is False
        assert probe.simulated_represented_as_live is False


def test_manifest_advertises_context_pack_storage() -> None:
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions["DatasetsContextPackStorageBinding@1"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots[
        "datasets_context_pack_storage"
    ].endswith("context-pack-storage-binding@1")
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions[
        "context_pack_storage"
    ] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False


def test_committed_files_match_generator() -> None:
    verified = verify_context_pack_storage_files()
    assert verified["ok"] is True
    pyproject = (_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'interface = "DatasetsContextPackStorageBinding@1"' in pyproject


def test_simulated_live_probe_is_rejected() -> None:
    with pytest.raises(DatasetsContextPackStorageError, match="simulated"):
        qualify_context_pack_storage(
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
            current_root_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            objective_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            idea_digest_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
    with pytest.raises(DatasetsContextPackStorageError, match="measured_live"):
        qualify_context_pack_storage(
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
            current_root_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            objective_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            idea_digest_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
