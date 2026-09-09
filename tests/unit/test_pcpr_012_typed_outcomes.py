"""PCPR-012: Datasets typed-outcome canonicalization."""

from __future__ import annotations

import ast
import os
from dataclasses import replace
from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.typed_outcomes import (
    CANONICAL_CLOSED_OUTCOMES,
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    SURFACE_MATURITIES,
    LoadDatasetSurface,
    OutcomeProbe,
    PCPR_012_GOAL_ID,
    PCPR_012_TASK_ID,
    TypedOutcomeError,
    bind_load_dataset_surface,
    current_head_runtime_probes,
    current_head_static_probes,
    discover_datasets_root,
    is_unavailable_surface,
    pcpr_012_receipt_promotion,
    probe_typed_outcome_runtime,
    qualify_current_head_typed_outcomes,
    qualify_typed_outcomes_canonical,
    resolve_load_dataset_surface,
    unavailable_load_dataset,
)


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_012_requirements() -> None:
    assert PCPR_012_TASK_ID == "PCPR-012"
    assert PCPR_012_GOAL_ID == "PCPR-G210"
    assert INTERFACE == "DatasetsTypedOutcomesCanonical@1"
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert "Unavailable" in CANONICAL_CLOSED_OUTCOMES
    assert "Verified" in CANONICAL_CLOSED_OUTCOMES
    assert "unavailable" in SURFACE_MATURITIES
    assert "stable" in SURFACE_MATURITIES
    assert "simulation_only" in SURFACE_MATURITIES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith("test_pcpr_012_typed_outcomes.py")


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_typed_outcomes()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.untyped_none_fallback_present is False
    assert verdict.typed_outcomes_canonical is True
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.live_solver_qualified is False
    assert verdict.live_solver_evidence_kind == "unavailable"
    assert verdict.live_hub_qualified is False
    assert verdict.live_hub_evidence_kind == "unavailable"
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.blockers == ()
    section = pcpr_012_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["untyped_none_fallback_present"] is False
    assert section["typed_outcomes_canonical"] is True
    assert section["live_solver_qualified"] is False
    assert section["live_hub_qualified"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_untyped_none_removed() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["init_module_level_load_dataset_none"].present is False
    assert probes["init_getattr_load_dataset_none"].present is False
    assert probes["dataset_manager_load_dataset_none"].present is False
    assert probes["dataset_loader_hf_load_dataset_none"].present is False
    assert probes["canonical_closed_outcomes_present"].present is True
    assert probes["live_solver_qualification"].evidence_kind == "unavailable"
    assert probes["live_solver_qualification"].present is None
    assert probes["live_solver_qualification"].live is False
    assert probes["live_hub_qualification"].evidence_kind == "unavailable"
    assert probes["live_hub_qualification"].present is None


def test_package_init_has_no_load_dataset_none_assignment() -> None:
    source = (_PACKAGE_ROOT / "ipfs_datasets_py" / "__init__.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not (isinstance(node.value, ast.Constant) and node.value.value is None):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                assert target.id != "load_dataset"
            if isinstance(target, ast.Subscript) and isinstance(
                target.slice, ast.Constant
            ):
                assert target.slice.value != "load_dataset"


def test_public_load_dataset_is_typed_not_none() -> None:
    from ipfs_datasets_py import load_dataset

    assert load_dataset is not None
    assert is_unavailable_surface(load_dataset) or isinstance(
        load_dataset, LoadDatasetSurface
    )
    assert getattr(load_dataset, "live", False) is False
    maturity = getattr(load_dataset, "surface_maturity", "unavailable")
    assert maturity in SURFACE_MATURITIES
    if is_unavailable_surface(load_dataset):
        result = load_dataset("squad")
        assert result["status"] != "success"
        assert result["ok"] is False
        assert result["live"] is False
        assert result["outcome"] == "Unavailable"
        assert result["dataset"] is None
        assert result["surface_maturity"] == "unavailable"


def test_unavailable_stand_in_is_not_success_or_live() -> None:
    assert unavailable_load_dataset is not None
    assert bool(unavailable_load_dataset) is False
    assert unavailable_load_dataset.unavailable is True
    assert unavailable_load_dataset.live is False
    result = unavailable_load_dataset("mnist")
    assert result["status"] == "unavailable"
    assert result["ok"] is False
    assert result["live"] is False
    assert result["disposition"] == "non_success"
    assert result["simulated_represented_as_live"] is False


def test_explicit_simulation_is_not_live(monkeypatch) -> None:
    monkeypatch.delenv("IPFS_DATASETS_EXPLICIT_SIMULATION", raising=False)
    simulated = unavailable_load_dataset("x", explicit_simulation=True)
    assert simulated["status"] in {"simulated", "unavailable"}
    assert simulated["live"] is False
    assert simulated["simulated_represented_as_live"] is False
    assert simulated["ok"] is False
    monkeypatch.setenv("IPFS_DATASETS_EXPLICIT_SIMULATION", "1")
    env_sim = unavailable_load_dataset("x")
    assert env_sim["status"] == "simulated"
    assert env_sim["live"] is False
    assert env_sim["simulated_represented_as_live"] is False


def test_bind_none_is_unavailable_not_none() -> None:
    bound = bind_load_dataset_surface(None)
    assert bound is unavailable_load_dataset
    assert bound is not None
    assert is_unavailable_surface(bound) is True
    assert resolve_load_dataset_surface(minimal_imports=True) is unavailable_load_dataset


def test_runtime_probes_show_typed_unavailable() -> None:
    observation = probe_typed_outcome_runtime()
    assert observation["status"] == "observed"
    assert observation["evidence_kind"] == "measured"
    assert observation["live"] is False
    assert observation["simulated_represented_as_live"] is False
    assert observation["public_load_is_none"] is False
    assert observation["payload_ok"] is False
    assert observation["payload_live"] is False
    assert observation["payload_status"] != "success"
    for probe in current_head_runtime_probes():
        assert probe.present is False
        assert probe.live is False
        assert probe.simulated_represented_as_live is False


def test_fallback_ipfs_datasets_is_typed_unavailable() -> None:
    from ipfs_datasets_py import _FallbackIPFSDatasets

    datasets = _FallbackIPFSDatasets()
    assert datasets.unavailable is True
    assert datasets.surface_maturity == "unavailable"
    assert datasets.live is False
    assert datasets.status == "unavailable"


def test_simulated_live_probe_is_rejected() -> None:
    with pytest.raises(TypedOutcomeError, match="simulated"):
        qualify_typed_outcomes_canonical(
            (
                OutcomeProbe(
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
    with pytest.raises(TypedOutcomeError, match="measured_live"):
        qualify_typed_outcomes_canonical(
            (
                OutcomeProbe(
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
    verdict = qualify_current_head_typed_outcomes()
    with pytest.raises(TypedOutcomeError, match="closed release"):
        pcpr_012_receipt_promotion(
            replace(verdict, closed_release_outcome="release_candidate_qualified")
        )
    with pytest.raises(TypedOutcomeError, match="PCPR release"):
        pcpr_012_receipt_promotion(replace(verdict, release_claim=True))


def test_discover_datasets_root_finds_package() -> None:
    root = discover_datasets_root()
    assert root is not None
    assert (root / "ipfs_datasets_py" / "__init__.py").is_file()
    assert os.environ.get("IPFS_DATASETS_EXPLICIT_SIMULATION") in {None, ""}
