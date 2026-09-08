"""PCPR-083: Datasets binding to Accelerate authority bypass."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.authority_bypass import (
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    ESCALATION_ORDER,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    OPERATOR_BLOCKING_TASK_ID,
    OBJECTIVE_KIND,
    OutcomeProbe,
    PCPR_083_GOAL_ID,
    PCPR_083_TASK_ID,
    PINNED_BINDING_CID,
    PINNED_CHAIN_CID,
    PINNED_CURRENT_ROOT_CID,
    PINNED_IDEA_DIGEST,
    PINNED_OBJECTIVE_CID,
    PINNED_PACK_CID,
    PROTOCOL_INTERFACE,
    SCHEMA,
    SEALED_PATH,
    SEALED_PYTHON,
    DatasetsAuthorityBypassError,
    current_head_static_probes,
    pcpr_083_receipt_promotion,
    qualify_authority_bypass,
    qualify_current_head_authority_bypass,
    refuse_database_edit,
    refuse_model_completion,
    refuse_pack_cid_remint,
    refuse_stale_as_current,
    refuse_unaffected_as_stale,
    render_declared_binding,
    semantic_identities_survive_bypass,
    sidecar_owned_by_datasets,
    verify_authority_bypass_files,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST
from ipfs_datasets_py.logic.platform.authority_bypass import (
    AUTHORITY_BYPASS_INTERFACE,
    AUTHORITY_BYPASS_KIND,
)


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_083_requirements() -> None:
    assert PCPR_083_TASK_ID == "PCPR-083"
    assert PCPR_083_GOAL_ID == "PCPR-G800"
    assert INTERFACE == "DatasetsAuthorityBypassBinding@1"
    assert SCHEMA == "ipfs_datasets_py/assurance/authority-bypass-binding@1"
    assert OBJECTIVE_KIND == "declared_authority_bypass_binding"
    assert OPERATOR_BLOCKING_TASK_ID == (
        "pcpr-083-operator-live-external-client-authority-bypass"
    )
    assert PROTOCOL_INTERFACE == "LogicProviderProtocol@2"
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith(
        "test_pcpr_083_authority_bypass.py"
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
    assert binding["context_pack"]["rejected"] is True
    assert binding["context_pack"]["survives_bypass"] is True
    assert binding["storage"]["stored"] is True
    assert binding["storage"]["stored_by"] == "ipfs_kit_py"
    client = binding["authority_bypass"]
    assert client["kind"] == AUTHORITY_BYPASS_KIND
    assert client["owned_by"] == "ipfs_datasets_py"
    assert client["classified_by"] == "ipfs_accelerate_py"
    assert client["remints_protocol"] is False
    assert client["adds_protocol_operation"] is False
    assert client["stale_rejected"] is True
    assert client["unaffected_completion_preserved"] is True
    assert client["survives_client"] is True
    assert client["survives_bypass"] is True
    assert client["idempotent"] is True
    assert client["history_mutated"] is False
    assert client["sidecar"]["interface"] == AUTHORITY_BYPASS_INTERFACE
    assert binding["duckdb_or_quack_state_written"] is False
    assert binding["objective_cid"] == PINNED_OBJECTIVE_CID
    assert binding["idea_digest"] == PINNED_IDEA_DIGEST
    assert binding["context_pack"]["pack_cid"] == PINNED_PACK_CID
    assert binding["storage"]["current_root_cid"] == PINNED_CURRENT_ROOT_CID
    assert binding["final_receipt_chain"]["chain_cid"] == PINNED_CHAIN_CID
    assert binding["binding_cid"] == PINNED_BINDING_CID
    assert binding["operator_blocking_task"]["status"] == "typed_blocked"
    assert tuple(binding["escalation_order"]) == ESCALATION_ORDER
    assert refuse_pack_cid_remint(PINNED_PACK_CID) == PINNED_PACK_CID
    with pytest.raises(DatasetsAuthorityBypassError, match="remints"):
        refuse_pack_cid_remint(
            "baguqeerabbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        )
    with pytest.raises(DatasetsAuthorityBypassError, match="cannot complete"):
        refuse_model_completion("frontier_model")
    with pytest.raises(DatasetsAuthorityBypassError, match="DuckDB"):
        refuse_database_edit(edited=True)
    with pytest.raises(DatasetsAuthorityBypassError, match="rejected"):
        refuse_stale_as_current(
            identity="DatasetsContextPack@1", admitted_as_current=True
        )
    with pytest.raises(DatasetsAuthorityBypassError, match="not stale"):
        refuse_unaffected_as_stale(
            identity="tests/unit/test_pcpr_017_solver_qualification.py",
            rejected=True,
        )
    assert sidecar_owned_by_datasets() is True
    assert semantic_identities_survive_bypass() is True


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_authority_bypass()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.live_application is False
    assert verdict.live_client is False
    assert verdict.operator_blocking_task == OPERATOR_BLOCKING_TASK_ID
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.pack_cid == PINNED_PACK_CID
    assert verdict.binding_cid == PINNED_BINDING_CID
    assert verdict.chain_cid == PINNED_CHAIN_CID
    assert verdict.blockers == ()
    section = pcpr_083_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None


def test_static_probes_show_declared_binding_constraints() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["binding_files_match_generator"].present is True
    assert probes["pyproject_authority_bypass_table"].present is True
    assert probes["manifest_advertises_authority_bypass"].present is True
    assert probes["owner_pack_cid_matches_pin"].present is True
    assert probes["client_owned_by_accelerate"].present is True
    assert probes["protocol_identity_not_reminted"].present is True
    assert probes["sidecar_is_authority_bypass"].present is True
    assert probes["stale_identities_remain_rejected"].present is True
    assert probes["unaffected_completion_preserved"].present is True
    assert probes["semantic_identities_survive_bypass"].present is True
    assert probes["idempotent_binding"].present is True
    assert probes["datasets_identity_reminted"].present is False
    assert probes["kit_identity_reminted"].present is False
    assert probes["chain_identity_reminted"].present is False
    assert probes["live_application"].evidence_kind == "unavailable"
    assert probes["live_client"].evidence_kind == "unavailable"
    for probe in probes.values():
        assert probe.live is False
        assert probe.simulated_represented_as_live is False


def test_committed_files_match_generator() -> None:
    verified = verify_authority_bypass_files()
    assert verified["ok"] is True
    assert verified["binding_cid"] == PINNED_BINDING_CID
    pyproject = (_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'interface = "DatasetsAuthorityBypassBinding@1"' in pyproject
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions[INTERFACE] == "1"


def test_manifest_handshake_advertises_authority_bypass() -> None:
    manifest = DEFAULT_LOGIC_PLATFORM_MANIFEST
    assert manifest.interface_versions[INTERFACE] == "1"
    assert manifest.schema_roots["datasets_authority_bypass"] == SCHEMA
    assert manifest.operation_versions["authority_bypass"] == "1"


def test_simulated_live_probe_is_rejected() -> None:
    dummy = "baguqeerabbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    with pytest.raises(DatasetsAuthorityBypassError, match="simulated"):
        qualify_authority_bypass(
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
            pack_cid=dummy,
            binding_cid=dummy,
            current_root_cid=dummy,
            chain_cid=dummy,
            objective_cid=dummy,
            idea_digest_cid=dummy,
        )
    with pytest.raises(DatasetsAuthorityBypassError, match="measured_live"):
        qualify_authority_bypass(
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
            pack_cid=dummy,
            binding_cid=dummy,
            current_root_cid=dummy,
            chain_cid=dummy,
            objective_cid=dummy,
            idea_digest_cid=dummy,
        )
