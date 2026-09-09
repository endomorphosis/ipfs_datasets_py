"""PCPR-071: Datasets binding to Accelerate recovery and idempotency."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.recovery_and_idempotency import (
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    ESCALATION_ORDER,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    OPERATOR_BLOCKING_TASK_ID,
    OBJECTIVE_KIND,
    OutcomeProbe,
    PCPR_071_GOAL_ID,
    PCPR_071_TASK_ID,
    PINNED_BINDING_CID,
    PINNED_CURRENT_ROOT_CID,
    PINNED_IDEA_DIGEST,
    PINNED_OBJECTIVE_CID,
    PINNED_PACK_CID,
    PINNED_PATCH_CID,
    PINNED_RESTART_CID,
    PINNED_ROUTE_CID,
    PINNED_RUN_CID,
    PROTOCOL_INTERFACE,
    SCHEMA,
    SEALED_PATH,
    SEALED_PYTHON,
    DatasetsRecoveryAndIdempotencyError,
    current_head_static_probes,
    pcpr_071_receipt_promotion,
    qualify_current_head_recovery_and_idempotency,
    qualify_recovery_and_idempotency,
    refuse_database_edit,
    refuse_model_completion,
    refuse_pack_cid_remint,
    refuse_patch_cid_remint,
    refuse_restart_cid_remint,
    refuse_route_cid_remint,
    refuse_run_cid_remint,
    refuse_stale_as_current,
    refuse_unaffected_as_stale,
    render_declared_binding,
    semantic_identities_survive_recovery,
    sidecar_owned_by_datasets,
    verify_recovery_and_idempotency_files,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST
from ipfs_datasets_py.logic.platform.recovery_and_idempotency import (
    RECOVERY_AND_IDEMPOTENCY_INTERFACE,
    RECOVERY_AND_IDEMPOTENCY_KIND,
)


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_071_requirements() -> None:
    assert PCPR_071_TASK_ID == "PCPR-071"
    assert PCPR_071_GOAL_ID == "PCPR-G700"
    assert INTERFACE == "DatasetsRecoveryAndIdempotencyBinding@1"
    assert SCHEMA == "ipfs_datasets_py/assurance/recovery-and-idempotency-binding@1"
    assert OBJECTIVE_KIND == "declared_recovery_and_idempotency_binding"
    assert OPERATOR_BLOCKING_TASK_ID == (
        "pcpr-071-operator-live-recovery-and-idempotency"
    )
    assert PROTOCOL_INTERFACE == "LogicProviderProtocol@2"
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith(
        "test_pcpr_071_recovery_and_idempotency.py"
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
    assert binding["context_pack"]["survives_recovery"] is True
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
    assert binding["selected_tests"]["run_cid"] == PINNED_RUN_CID
    assert binding["state_owner_restart"]["restart_cid"] == PINNED_RESTART_CID
    recovery = binding["recovery_and_idempotency"]
    assert recovery["kind"] == RECOVERY_AND_IDEMPOTENCY_KIND
    assert recovery["owned_by"] == "ipfs_datasets_py"
    assert recovery["classified_by"] == "ipfs_accelerate_py"
    assert recovery["remints_protocol"] is False
    assert recovery["adds_protocol_operation"] is False
    assert recovery["stale_rejected"] is True
    assert recovery["unaffected_completion_preserved"] is True
    assert recovery["survives_recovery"] is True
    assert recovery["idempotent"] is True
    assert recovery["history_mutated"] is False
    assert recovery["sidecar"]["interface"] == RECOVERY_AND_IDEMPOTENCY_INTERFACE
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
    assert refuse_run_cid_remint(PINNED_RUN_CID) == PINNED_RUN_CID
    assert refuse_restart_cid_remint(PINNED_RESTART_CID) == PINNED_RESTART_CID
    with pytest.raises(DatasetsRecoveryAndIdempotencyError, match="remints"):
        refuse_pack_cid_remint(
            "baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
    with pytest.raises(DatasetsRecoveryAndIdempotencyError, match="cannot complete"):
        refuse_model_completion("medium_model")
    with pytest.raises(DatasetsRecoveryAndIdempotencyError, match="admitted as current"):
        refuse_stale_as_current(
            identity="DatasetsContextPack@1", admitted_as_current=True
        )
    with pytest.raises(DatasetsRecoveryAndIdempotencyError, match="must be preserved"):
        refuse_unaffected_as_stale(
            identity="tests/unit/test_pcpr_017_solver_qualification.py",
            rejected=True,
        )
    with pytest.raises(DatasetsRecoveryAndIdempotencyError, match="DuckDB"):
        refuse_database_edit(edited=True)
    assert sidecar_owned_by_datasets() is True
    assert semantic_identities_survive_recovery() is True


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_recovery_and_idempotency()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.sibling_source_required is False
    assert verdict.live_application is False
    assert verdict.live_recovery is False
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
    assert verdict.run_cid == PINNED_RUN_CID
    assert verdict.restart_cid == PINNED_RESTART_CID
    assert verdict.blockers == ()
    section = pcpr_071_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_declared_binding_constraints() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["binding_files_match_generator"].present is True
    assert probes["pyproject_recovery_and_idempotency_table"].present is True
    assert probes["manifest_advertises_recovery_and_idempotency"].present is True
    assert probes["owner_pack_cid_matches_pin"].present is True
    assert probes["recovery_owned_by_accelerate"].present is True
    assert probes["protocol_identity_not_reminted"].present is True
    assert probes["sidecar_is_recovery_and_idempotency"].present is True
    assert probes["stale_identities_remain_rejected"].present is True
    assert probes["unaffected_completion_preserved"].present is True
    assert probes["semantic_identities_survive_recovery"].present is True
    assert probes["idempotent_binding"].present is True
    assert probes["model_assertion_cannot_complete_work"].present is True
    assert probes["sibling_import_observed"].present is False
    assert probes["datasets_identity_reminted"].present is False
    assert probes["kit_identity_reminted"].present is False
    assert probes["restart_identity_reminted"].present is False
    assert probes["live_application"].evidence_kind == "unavailable"
    assert probes["live_recovery"].evidence_kind == "unavailable"
    for probe in probes.values():
        assert probe.live is False
        assert probe.simulated_represented_as_live is False


def test_manifest_advertises_recovery_and_idempotency() -> None:
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions["DatasetsRecoveryAndIdempotencyBinding@1"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots[
        "datasets_recovery_and_idempotency"
    ].endswith("recovery-and-idempotency-binding@1")
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions[
        "recovery_and_idempotency"
    ] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False


def test_committed_files_match_generator() -> None:
    verified = verify_recovery_and_idempotency_files()
    assert verified["ok"] is True
    pyproject = (_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'interface = "DatasetsRecoveryAndIdempotencyBinding@1"' in pyproject
    sidecar = (
        _PACKAGE_ROOT
        / "ipfs_datasets_py"
        / "logic"
        / "platform"
        / "recovery_and_idempotency.py"
    )
    assert sidecar.is_file()


def test_simulated_live_probe_is_rejected() -> None:
    dummy = "baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    with pytest.raises(DatasetsRecoveryAndIdempotencyError, match="simulated"):
        qualify_recovery_and_idempotency(
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
            patch_cid=dummy,
            route_cid=dummy,
            current_root_cid=dummy,
            run_cid=dummy,
            restart_cid=dummy,
            objective_cid=dummy,
            idea_digest_cid=dummy,
        )
    with pytest.raises(DatasetsRecoveryAndIdempotencyError, match="measured_live"):
        qualify_recovery_and_idempotency(
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
            patch_cid=dummy,
            route_cid=dummy,
            current_root_cid=dummy,
            run_cid=dummy,
            restart_cid=dummy,
            objective_cid=dummy,
            idea_digest_cid=dummy,
        )
