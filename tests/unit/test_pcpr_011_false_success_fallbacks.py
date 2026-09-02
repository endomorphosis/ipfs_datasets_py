"""PCPR-011: Datasets false-success fallback removal."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.false_success_fallbacks import (
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    FallbackProbe,
    FalseSuccessFallbackError,
    PCPR_011_GOAL_ID,
    PCPR_011_TASK_ID,
    current_head_runtime_probes,
    current_head_static_probes,
    discover_datasets_root,
    pcpr_011_receipt_promotion,
    probe_fallback_runtime,
    qualify_current_head_false_success_fallbacks,
    qualify_false_success_fallback_removal,
)


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_011_requirements() -> None:
    assert PCPR_011_TASK_ID == "PCPR-011"
    assert PCPR_011_GOAL_ID == "PCPR-G210"
    assert INTERFACE == "DatasetsFalseSuccessFallbackRemoval@1"
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith(
        "test_pcpr_011_false_success_fallbacks.py"
    )


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_false_success_fallbacks()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.false_success_fallback_present is False
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.live_solver_qualified is False
    assert verdict.live_solver_evidence_kind == "unavailable"
    assert verdict.live_transport_qualified is False
    assert verdict.live_transport_evidence_kind == "unavailable"
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.blockers == ()
    section = pcpr_011_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["false_success_fallback_present"] is False
    assert section["live_solver_qualified"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_false_success_removed() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["fallback_download_status_success"].present is False
    assert probes["fallback_upload_status_success"].present is False
    assert probes["fallback_class_status_success_literal"].present is False
    assert probes["libp2p_kit_status_success"].present is False
    assert probes["libp2p_kit_stub_status_success"].present is False
    assert probes["libp2p_kit_stub_implementation_success"].present is False
    assert probes["libp2p_stub_file_stub_implementation_success"].present is False
    assert probes["live_solver_qualification"].evidence_kind == "unavailable"
    assert probes["live_solver_qualification"].present is None
    assert probes["live_solver_qualification"].live is False
    assert probes["live_transport_qualification"].evidence_kind == "unavailable"
    assert probes["live_transport_qualification"].present is None


def test_package_init_fallback_has_no_status_success_literal() -> None:
    source = (_PACKAGE_ROOT / "ipfs_datasets_py" / "__init__.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "_FallbackIPFSDatasets"
    )
    segment = ast.get_source_segment(source, class_node)
    assert segment is not None
    assert '"status": "success"' not in segment
    assert "download_dataset" in segment
    assert "upload_dataset" in segment


def test_libp2p_stubs_have_no_status_success_literal() -> None:
    for relpath in (
        "ipfs_datasets_py/p2p_networking/libp2p_kit.py",
        "ipfs_datasets_py/p2p_networking/libp2p_kit_stub.py",
    ):
        source = (_PACKAGE_ROOT / relpath).read_text(encoding="utf-8")
        assert '"status": "success"' not in source
        assert "Stub implementation" not in source or '"status": "success"' not in source


def test_runtime_fallbacks_are_typed_unavailable_not_success() -> None:
    observation = probe_fallback_runtime()
    assert observation["status"] == "observed"
    assert observation["evidence_kind"] == "measured"
    assert observation["live"] is False
    assert observation["simulated_represented_as_live"] is False
    assert observation["download_success"] is False
    assert observation["upload_success"] is False
    assert observation["libp2p_success"] is False
    assert observation["libp2p_stub_success"] is False
    assert observation["download"]["status"] == "unavailable"
    assert observation["download"]["ok"] is False
    assert observation["upload"]["status"] == "unavailable"
    assert observation["libp2p_kit_create"]["status"] == "unavailable"
    assert observation["libp2p_stub_create"]["status"] == "unavailable"
    assert observation["explicit_simulation_download"]["status"] in {
        "simulated",
        "unavailable",
    }
    assert observation["explicit_simulation_download"]["live"] is False
    assert observation["explicit_simulation_libp2p"]["status"] == "simulated"
    assert observation["explicit_simulation_libp2p"]["simulated"] is True
    assert observation["explicit_simulation_libp2p"]["simulated_represented_as_live"] is False
    for probe in current_head_runtime_probes():
        assert probe.present is False
        assert probe.live is False
        assert probe.simulated_represented_as_live is False


def test_fallback_instance_download_and_upload_are_unavailable() -> None:
    from ipfs_datasets_py import _FallbackIPFSDatasets

    datasets = _FallbackIPFSDatasets()
    assert datasets.status == "unavailable"
    download = datasets.download_dataset("mnist")
    upload = datasets.upload_dataset("mnist")
    assert download["status"] != "success"
    assert upload["status"] != "success"
    assert download["ok"] is False
    assert upload["ok"] is False
    assert download["disposition"] == "non_success"
    assert download["live"] is False
    assert download["dataset"] is None
    assert download["defect_id"] == "DS-FALSE-001"
    assert upload["defect_id"] == "DS-FALSE-003"


def test_explicit_simulation_is_not_live(monkeypatch) -> None:
    from ipfs_datasets_py import _FallbackIPFSDatasets
    from ipfs_datasets_py.p2p_networking.libp2p_kit import DistributedDatasetManager

    monkeypatch.delenv("IPFS_DATASETS_EXPLICIT_SIMULATION", raising=False)
    fallback = _FallbackIPFSDatasets()
    simulated = fallback.download_dataset("x", explicit_simulation=True)
    assert simulated["status"] in {"simulated", "unavailable"}
    assert simulated["live"] is False
    assert simulated["simulated_represented_as_live"] is False
    manager = DistributedDatasetManager(explicit_simulation=True)
    created = manager.create_distributed_dataset("x")
    assert created["status"] == "simulated"
    assert created["ok"] is False
    assert created["live"] is False
    ordinary = DistributedDatasetManager().create_distributed_dataset("x")
    assert ordinary["status"] == "unavailable"
    monkeypatch.setenv("IPFS_DATASETS_EXPLICIT_SIMULATION", "1")
    env_sim = DistributedDatasetManager().create_distributed_dataset("x")
    assert env_sim["status"] == "simulated"
    assert env_sim["simulated_represented_as_live"] is False


def test_simulated_live_probe_is_rejected() -> None:
    with pytest.raises(FalseSuccessFallbackError, match="simulated"):
        qualify_false_success_fallback_removal(
            (
                FallbackProbe(
                    probe_id="bogus",
                    present=False,
                    evidence_kind="simulated",
                    live=False,
                    simulated_represented_as_live=True,
                    reason="must fail",
                ),
            )
        )


def test_live_claim_without_measured_live_is_rejected() -> None:
    with pytest.raises(FalseSuccessFallbackError, match="measured_live"):
        qualify_false_success_fallback_removal(
            (
                FallbackProbe(
                    probe_id="bogus",
                    present=False,
                    evidence_kind="measured",
                    live=True,
                    simulated_represented_as_live=False,
                    reason="must fail",
                ),
            )
        )


def test_receipt_promotion_rejects_closed_release() -> None:
    verdict = qualify_current_head_false_success_fallbacks()
    from dataclasses import replace

    with pytest.raises(FalseSuccessFallbackError, match="closed release"):
        pcpr_011_receipt_promotion(
            replace(verdict, closed_release_outcome="release_candidate_qualified")
        )
    with pytest.raises(FalseSuccessFallbackError, match="PCPR release"):
        pcpr_011_receipt_promotion(replace(verdict, release_claim=True))


def test_discover_datasets_root_finds_package() -> None:
    root = discover_datasets_root()
    assert root is not None
    assert (root / "ipfs_datasets_py" / "__init__.py").is_file()
    assert os.environ.get("IPFS_DATASETS_EXPLICIT_SIMULATION") in {None, ""}
