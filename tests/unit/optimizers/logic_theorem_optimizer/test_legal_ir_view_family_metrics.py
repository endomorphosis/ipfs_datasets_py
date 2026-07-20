"""Contract tests for validation metrics split by canonical LegalIR family."""

from __future__ import annotations

from copy import deepcopy

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    uscode_modal_daemon_runner as runner,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    LEGAL_IR_VIEW_FAMILIES,
    LEGAL_IR_VIEW_FAMILY_METRIC_NAMES,
    LEGAL_IR_VIEW_FAMILY_METRIC_SCHEMA_VERSION,
    _legal_ir_objective_component,
    hammer_guidance_metric_block,
    legal_ir_view_family_metric_block,
    legal_ir_view_family_name,
)


FAMILY_VIEWS = {
    "deontic": "deontic.ir",
    "frame_logic": "modal.frame_logic",
    "tdfol": "TDFOL.prover",
    "kg": "knowledge_graphs.neo4j_compat",
    "cec": "CEC.native",
    "external_provers": "external_provers.router",
    "decompiler": "modal.ir_decompiler",
}


def _artifact(family: str, index: int) -> dict:
    succeeded = index % 2 == 0
    return {
        "backend_statuses": {"z3": "proved" if succeeded else "failed"},
        "contract_id": f"legal-ir-view/{family.replace('_', '-')}/v1",
        "guidance_id": f"guidance-{family}",
        "legal_ir_view": FAMILY_VIEWS[family],
        "proof_checked": succeeded,
        "proved": succeeded,
        "reconstruction_status": "verified" if succeeded else "kernel_rejected",
        "schema_version": "legal-ir-hammer-guidance-v1",
        "source": "hammer_verified_guidance",
        "source_copy_rejected": not succeeded,
        "target_component": FAMILY_VIEWS[family],
        "trusted": succeeded,
    }


def _ir_metrics() -> dict:
    return {
        "view_family_metrics": {
            family: {
                "ir_cross_entropy_loss": 0.10 + index * 0.01,
                "ir_cosine_similarity": 0.90 - index * 0.01,
                "sample_count": index + 1,
            }
            for index, family in enumerate(LEGAL_IR_VIEW_FAMILIES)
        }
    }


def _autoencoder_metrics() -> dict:
    return {
        "legal_ir_view_family_metrics": {
            family: {
                "autoencoder_cross_entropy_loss": 0.20 + index * 0.01,
                "autoencoder_cosine_similarity": 0.80 - index * 0.01,
                "sample_count": index + 1,
            }
            for index, family in enumerate(LEGAL_IR_VIEW_FAMILIES)
        }
    }


def test_canonical_family_resolver_covers_contract_aliases() -> None:
    assert tuple(FAMILY_VIEWS) == LEGAL_IR_VIEW_FAMILIES
    for family, view in FAMILY_VIEWS.items():
        assert legal_ir_view_family_name(view) == family
    assert legal_ir_view_family_name("legal-ir-view/external-provers/v1") == (
        "external_provers"
    )
    assert legal_ir_view_family_name("legal-ir-view/decompiler/v1") == "decompiler"


def test_hammer_metrics_report_each_family_without_cross_family_leakage() -> None:
    artifacts = [
        _artifact(family, index)
        for index, family in enumerate(LEGAL_IR_VIEW_FAMILIES)
    ]

    block = hammer_guidance_metric_block(artifacts)

    assert block["hammer_artifact_count"] == len(LEGAL_IR_VIEW_FAMILIES)
    assert tuple(block["view_family_metrics"]) == LEGAL_IR_VIEW_FAMILIES
    for index, family in enumerate(LEGAL_IR_VIEW_FAMILIES):
        expected = 1.0 if index % 2 == 0 else 0.0
        metrics = block["view_family_metrics"][family]
        assert metrics["artifact_count"] == 1
        assert metrics["hammer_proof_success_rate"] == expected
        assert metrics["reconstruction_success_rate"] == expected
        assert metrics["symbolic_validity_success_rate"] == expected
        assert metrics["source_copy_penalty"] == 1.0 - expected
        prefix = f"legal_ir_view_family_{family}"
        assert block[f"{prefix}_hammer_proof_success_rate"] == expected
        assert block[f"{prefix}_source_copy_penalty"] == 1.0 - expected

    sparse = legal_ir_view_family_metric_block(hammer_guidance=[artifacts[0]])
    assert "hammer_proof_success_rate" in sparse["view_family_metrics"]["deontic"][
        "observed_metrics"
    ]
    assert sparse["view_family_metrics"]["kg"]["observed_metrics"] == []


def test_validation_block_reports_and_scores_all_eight_metrics_per_family() -> None:
    artifacts = [
        _artifact(family, index)
        for index, family in enumerate(LEGAL_IR_VIEW_FAMILIES)
    ]

    block = legal_ir_view_family_metric_block(
        ir_metrics=_ir_metrics(),
        autoencoder_metrics=_autoencoder_metrics(),
        hammer_guidance=artifacts,
    )

    assert block["schema_version"] == LEGAL_IR_VIEW_FAMILY_METRIC_SCHEMA_VERSION
    assert tuple(block["families"]) == LEGAL_IR_VIEW_FAMILIES
    assert tuple(block["metric_names"]) == LEGAL_IR_VIEW_FAMILY_METRIC_NAMES
    assert 0.0 < block["macro_score"] < 1.0
    for index, family in enumerate(LEGAL_IR_VIEW_FAMILIES):
        metrics = block["view_family_metrics"][family]
        assert set(metrics["observed_metrics"]) == set(
            LEGAL_IR_VIEW_FAMILY_METRIC_NAMES
        )
        assert metrics["metric_coverage"] == 1.0
        assert metrics["ir_cross_entropy_loss"] == pytest.approx(
            0.10 + index * 0.01
        )
        assert metrics["autoencoder_cross_entropy_loss"] == pytest.approx(
            0.20 + index * 0.01
        )
        assert 0.0 <= metrics["score"] <= 1.0
        for metric_name in LEGAL_IR_VIEW_FAMILY_METRIC_NAMES:
            flat_name = f"legal_ir_view_family_{family}_{metric_name}"
            assert block["flat_metrics"][flat_name] == metrics[metric_name]


def test_runner_projects_family_metrics_into_validation_report() -> None:
    artifacts = [
        _artifact(family, index)
        for index, family in enumerate(LEGAL_IR_VIEW_FAMILIES)
    ]

    report = runner.legal_ir_validation_view_family_metric_block(
        compiler_ir_validation=_ir_metrics(),
        autoencoder_validation=_autoencoder_metrics(),
        hammer_validation=artifacts,
    )

    assert report["family_count"] == 7
    assert report["view_family_metrics"]["external_provers"][
        "autoencoder_cosine_similarity"
    ] == pytest.approx(0.75)
    assert report["view_family_metrics"]["decompiler"][
        "ir_cosine_similarity"
    ] == pytest.approx(0.84)


def test_family_guardrail_regression_increases_training_objective() -> None:
    artifacts = [
        _artifact(family, 0) for family in LEGAL_IR_VIEW_FAMILIES
    ]
    before = legal_ir_view_family_metric_block(
        ir_metrics=_ir_metrics(),
        autoencoder_metrics=_autoencoder_metrics(),
        hammer_guidance=artifacts,
    )
    regressed_artifacts = deepcopy(artifacts)
    regressed_artifacts[0].update(
        {
            "proof_checked": False,
            "proved": False,
            "reconstruction_status": "kernel_rejected",
            "source_copy_rejected": True,
            "trusted": False,
        }
    )
    after = legal_ir_view_family_metric_block(
        ir_metrics=_ir_metrics(),
        autoencoder_metrics=_autoencoder_metrics(),
        hammer_guidance=regressed_artifacts,
    )

    assert after["view_family_metrics"]["deontic"]["score"] < before[
        "view_family_metrics"
    ]["deontic"]["score"]
    assert after["macro_score"] < before["macro_score"]
    assert _legal_ir_objective_component(after["flat_metrics"]) > (
        _legal_ir_objective_component(before["flat_metrics"])
    )
