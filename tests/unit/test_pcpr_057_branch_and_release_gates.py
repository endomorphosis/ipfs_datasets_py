"""PCPR-057: Datasets binding to branch and release gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.branch_and_release_gates import (
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    OPERATOR_BLOCKING_TASK_ID,
    OutcomeProbe,
    PCPR_057_GOAL_ID,
    PCPR_057_TASK_ID,
    PINNED_BRANCH_POLICY_CID,
    PINNED_LOCK_CID,
    PINNED_RELEASE_GATE_CID,
    POLICY_KIND,
    SCHEMA,
    SEALED_PATH,
    SEALED_PYTHON,
    DatasetsBranchAndReleaseGatesError,
    current_head_static_probes,
    pcpr_057_receipt_promotion,
    qualify_branch_and_release_gates,
    qualify_current_head_branch_and_release_gates,
    refuse_gate_remint,
    refuse_lock_remint,
    refuse_policy_remint,
    render_declared_binding,
    verify_branch_and_release_gate_files,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_057_requirements() -> None:
    assert PCPR_057_TASK_ID == "PCPR-057"
    assert PCPR_057_GOAL_ID == "PCPR-G600"
    assert INTERFACE == "DatasetsBranchAndReleaseGatesBinding@1"
    assert SCHEMA == (
        "ipfs_datasets_py/assurance/branch-and-release-gates-binding@1"
    )
    assert POLICY_KIND == "declared_branch_protection_policy_binding"
    assert OPERATOR_BLOCKING_TASK_ID == "pcpr-057-operator-github-governance"
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith(
        "test_pcpr_057_branch_and_release_gates.py"
    )
    assert SEALED_PATH == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
    assert SEALED_PYTHON == "/usr/bin/python3.12"
    binding = render_declared_binding()
    assert binding["applied"] is False
    assert binding["live"] is False
    assert binding["release_claim"] is False
    assert binding["closed_release_outcome"] is None
    assert binding["governance_gate_complete"] is False
    assert binding["source"]["mutable_main_reference"] is False
    assert binding["lock_cid"] == PINNED_LOCK_CID
    assert binding["branch_policy_cid"] == PINNED_BRANCH_POLICY_CID
    assert binding["release_gate_cid"] == PINNED_RELEASE_GATE_CID
    assert binding["partial_required_build_failure_prohibits_release"] is True
    assert refuse_policy_remint(PINNED_BRANCH_POLICY_CID) == PINNED_BRANCH_POLICY_CID
    assert refuse_gate_remint(PINNED_RELEASE_GATE_CID) == PINNED_RELEASE_GATE_CID
    assert refuse_lock_remint(PINNED_LOCK_CID) == PINNED_LOCK_CID
    with pytest.raises(DatasetsBranchAndReleaseGatesError, match="remints"):
        refuse_policy_remint(
            "baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_branch_and_release_gates()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.sibling_source_required is False
    assert verdict.hashes_invented is False
    assert verdict.signatures_invented is False
    assert verdict.live_branch_protection is False
    assert verdict.governance_gate_complete is False
    assert verdict.operator_blocking_task == OPERATOR_BLOCKING_TASK_ID
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.blockers == ()
    section = pcpr_057_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_declared_gate_constraints() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["binding_files_match_generator"].present is True
    assert probes["core_release_profile_is_empty"].present is True
    assert probes["pyproject_branch_and_release_gates_table"].present is True
    assert probes["manifest_advertises_branch_and_release_gates"].present is True
    assert probes["branch_policy_cid_matches_pin"].present is True
    assert probes["release_gate_cid_matches_pin"].present is True
    assert probes["lock_cid_matches_pin"].present is True
    assert probes["governance_gate_is_not_complete"].present is True
    assert probes["operator_blocking_task_emitted"].present is True
    assert probes["mutable_main_reference"].present is False
    assert probes["live_branch_protection"].evidence_kind == "unavailable"
    for probe in probes.values():
        assert probe.live is False
        assert probe.simulated_represented_as_live is False


def test_manifest_advertises_branch_and_release_gates() -> None:
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions["DatasetsBranchAndReleaseGatesBinding@1"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots[
        "datasets_branch_and_release_gates"
    ].endswith("branch-and-release-gates-binding@1")
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions[
        "branch_and_release_gates"
    ] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_repository_layout() is False


def test_committed_files_match_generator() -> None:
    verified = verify_branch_and_release_gate_files()
    assert verified["ok"] is True
    pyproject = (_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'interface = "DatasetsBranchAndReleaseGatesBinding@1"' in pyproject


def test_simulated_live_probe_is_rejected() -> None:
    with pytest.raises(DatasetsBranchAndReleaseGatesError, match="simulated"):
        qualify_branch_and_release_gates(
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
            branch_policy_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            release_gate_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            binding_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            lock_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
