"""PCPR-067: Datasets binding to Accelerate eligible reuse."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.safe_reuse import (
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    ELIGIBLE_REUSE,
    ESCALATION_ORDER,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    OPERATOR_BLOCKING_TASK_ID,
    OBJECTIVE_KIND,
    OutcomeProbe,
    PCPR_067_GOAL_ID,
    PCPR_067_TASK_ID,
    PINNED_BINDING_CID,
    PINNED_CHANGE_CID,
    PINNED_CURRENT_ROOT_CID,
    PINNED_IDEA_DIGEST,
    PINNED_OBJECTIVE_CID,
    PINNED_PACK_CID,
    PINNED_PATCH_CID,
    PINNED_ROUTE_CID,
    PINNED_RUN_CID,
    PROTOCOL_INTERFACE,
    SCHEMA,
    SEALED_PATH,
    SEALED_PYTHON,
    DatasetsSafeReuseError,
    current_head_static_probes,
    pcpr_067_receipt_promotion,
    qualify_current_head_safe_reuse,
    qualify_safe_reuse,
    refuse_change_cid_remint,
    refuse_live_reuse,
    refuse_model_completion,
    refuse_pack_cid_remint,
    refuse_patch_cid_remint,
    refuse_relevant_interface_change,
    refuse_reuse_not_demonstrated,
    refuse_route_cid_remint,
    refuse_run_cid_remint,
    render_declared_binding,
    semantic_impact_is_empty,
    sidecar_owned_by_datasets,
    verify_safe_reuse_files,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST
from ipfs_datasets_py.logic.platform.unrelated_documentation import (
    UNRELATED_DOCUMENTATION_INTERFACE,
    UNRELATED_DOCUMENTATION_KIND,
)


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_067_requirements() -> None:
    assert PCPR_067_TASK_ID == "PCPR-067"
    assert PCPR_067_GOAL_ID == "PCPR-G700"
    assert INTERFACE == "DatasetsSafeReuseBinding@1"
    assert SCHEMA == "ipfs_datasets_py/assurance/safe-reuse-binding@1"
    assert OBJECTIVE_KIND == "declared_safe_reuse_binding"
    assert OPERATOR_BLOCKING_TASK_ID == "pcpr-067-operator-live-safe-reuse"
    assert PROTOCOL_INTERFACE == "LogicProviderProtocol@2"
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith("test_pcpr_067_safe_reuse.py")
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
    assert binding["context_pack"]["reused"] is True
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
    assert binding["selected_tests"]["reused"] is True
    assert binding["selected_tests"]["run_cid"] == PINNED_RUN_CID
    change = binding["unrelated_state_change"]
    assert change["kind"] == UNRELATED_DOCUMENTATION_KIND
    assert change["owned_by"] == "ipfs_datasets_py"
    assert change["classified_by"] == "ipfs_accelerate_py"
    assert change["remints_protocol"] is False
    assert change["adds_protocol_operation"] is False
    assert change["relevant_interface_change"] is False
    assert change["reuse_demonstrated"] is False
    assert change["eligible_reuse_preserved"] is True
    assert list(change["impacted_cone"]) == []
    assert change["sidecar"]["interface"] == UNRELATED_DOCUMENTATION_INTERFACE
    reuse = binding["safe_reuse"]
    assert reuse["reuse_demonstrated"] is True
    assert reuse["live_reuse"] is False
    assert reuse["next_task_id"] == "PCPR-068"
    assert list(reuse["eligible_reuse"]) == list(ELIGIBLE_REUSE)
    assert binding["duckdb_or_quack_state_written"] is False
    assert binding["objective_cid"] == PINNED_OBJECTIVE_CID
    assert binding["idea_digest"] == PINNED_IDEA_DIGEST
    assert binding["context_pack"]["pack_cid"] == PINNED_PACK_CID
    assert binding["storage"]["current_root_cid"] == PINNED_CURRENT_ROOT_CID
    assert binding["route"]["route_cid"] == PINNED_ROUTE_CID
    assert binding["bounded_patch"]["patch_cid"] == PINNED_PATCH_CID
    assert binding["unrelated_state_change"]["change_cid"] == PINNED_CHANGE_CID
    assert binding["binding_cid"] == PINNED_BINDING_CID
    assert binding["operator_blocking_task"]["status"] == "typed_blocked"
    assert tuple(binding["escalation_order"]) == ESCALATION_ORDER
    assert refuse_pack_cid_remint(PINNED_PACK_CID) == PINNED_PACK_CID
    assert refuse_route_cid_remint(PINNED_ROUTE_CID) == PINNED_ROUTE_CID
    assert refuse_patch_cid_remint(PINNED_PATCH_CID) == PINNED_PATCH_CID
    assert refuse_run_cid_remint(PINNED_RUN_CID) == PINNED_RUN_CID
    assert refuse_change_cid_remint(PINNED_CHANGE_CID) == PINNED_CHANGE_CID
    with pytest.raises(DatasetsSafeReuseError, match="remints"):
        refuse_pack_cid_remint(
            "baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
    with pytest.raises(DatasetsSafeReuseError, match="cannot complete"):
        refuse_model_completion("medium_model")
    with pytest.raises(DatasetsSafeReuseError, match="relevant"):
        refuse_relevant_interface_change(relevant=True)
    with pytest.raises(DatasetsSafeReuseError, match="must demonstrate"):
        refuse_reuse_not_demonstrated(demonstrated=False)
    with pytest.raises(DatasetsSafeReuseError, match="live reuse"):
        refuse_live_reuse(live=True)
    assert sidecar_owned_by_datasets() is True
    assert semantic_impact_is_empty() is True


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_safe_reuse()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.sibling_source_required is False
    assert verdict.live_application is False
    assert verdict.live_reuse is False
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
    assert verdict.change_cid == PINNED_CHANGE_CID
    assert verdict.blockers == ()
    section = pcpr_067_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_declared_binding_constraints() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["binding_files_match_generator"].present is True
    assert probes["pyproject_safe_reuse_table"].present is True
    assert probes["manifest_advertises_safe_reuse"].present is True
    assert probes["owner_pack_cid_matches_pin"].present is True
    assert probes["reuse_owned_by_accelerate"].present is True
    assert probes["protocol_identity_not_reminted"].present is True
    assert probes["sidecar_remains_unrelated_documentation"].present is True
    assert probes["impacted_cone_empty"].present is True
    assert probes["eligible_reuse_demonstrated_hermetically"].present is True
    assert probes["model_assertion_cannot_complete_work"].present is True
    assert probes["sibling_import_observed"].present is False
    assert probes["datasets_identity_reminted"].present is False
    assert probes["kit_identity_reminted"].present is False
    assert probes["live_reuse_claimed"].present is False
    assert probes["live_application"].evidence_kind == "unavailable"
    for probe in probes.values():
        assert probe.live is False
        assert probe.simulated_represented_as_live is False


def test_manifest_advertises_safe_reuse() -> None:
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions["DatasetsSafeReuseBinding@1"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots[
        "datasets_safe_reuse"
    ].endswith("safe-reuse-binding@1")
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions["safe_reuse"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False


def test_committed_files_match_generator() -> None:
    verified = verify_safe_reuse_files()
    assert verified["ok"] is True
    pyproject = (_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'interface = "DatasetsSafeReuseBinding@1"' in pyproject
    sidecar = (
        _PACKAGE_ROOT
        / "ipfs_datasets_py"
        / "logic"
        / "platform"
        / "unrelated_documentation.py"
    )
    assert sidecar.is_file()


def test_simulated_live_probe_is_rejected() -> None:
    dummy = "baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    with pytest.raises(DatasetsSafeReuseError, match="simulated"):
        qualify_safe_reuse(
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
            change_cid=dummy,
            objective_cid=dummy,
            idea_digest_cid=dummy,
        )
    with pytest.raises(DatasetsSafeReuseError, match="measured_live"):
        qualify_safe_reuse(
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
            change_cid=dummy,
            objective_cid=dummy,
            idea_digest_cid=dummy,
        )
