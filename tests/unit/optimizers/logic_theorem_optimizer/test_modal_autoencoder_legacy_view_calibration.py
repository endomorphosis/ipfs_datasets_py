"""Contract tests for calibrated legacy feature-to-LegalIR-view reuse."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import (
    LegalIRSplitExample,
    LegalIRSplitManifest,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_legacy_view_calibration import (
    LEGACY_VIEW_CALIBRATION_HEADS,
    LEGACY_VIEW_CALIBRATION_METRICS,
    FamilyCalibrationMetrics,
    HeadCalibration,
    LegacyViewCalibrationConfig,
    LegacyViewCalibrationError,
    LegacyViewCalibrationExample,
    LegacyViewCalibrationLineage,
    LegacyViewCalibrationSearchResult,
    LegacyViewCalibrationSearchSpace,
    LegacyViewEvaluationReport,
    ViewCalibration,
    apply_legacy_view_calibration,
    calibrate_feature_legal_ir_view_logits,
    calibrate_legacy_view_logits,
    compare_legacy_view_reports,
    evaluate_legacy_view_calibration,
    promote_legacy_view_calibration,
    search_legacy_view_calibration,
    verify_legacy_view_calibration_report,
)


ROOT = Path(__file__).resolve().parents[4]
_HASH = {
    name: "sha256:" + character * 64
    for name, character in {
        "teacher": "a",
        "student": "b",
        "canary": "c",
        "compiler": "d",
        "schema": "e",
    }.items()
}
_VIEWS = {
    "deontic": "deontic.ir",
    "frame_logic": "modal.frame_logic",
    "tdfol": "TDFOL.prover",
    "knowledge_graph": "knowledge_graphs.neo4j_compat",
    "cec": "CEC.native",
    "prover": "external_provers.router",
    "global": "modal.ir_decompiler",
}


def _examples() -> tuple[LegacyViewCalibrationExample, ...]:
    result = []
    for head, view in _VIEWS.items():
        wrong = f"{view}.wrong"
        result.append(
            LegacyViewCalibrationExample(
                sample_id=f"sample-{head}",
                head=head,
                target_distribution={view: 1.0, wrong: 0.0},
                current_logits={view: 0.0, wrong: 2.0},
                legacy_logits={view: 8.0, wrong: 0.0},
                outcomes_by_view={
                    view: {
                        "semantic_equivalence": 1.0,
                        "proof_reconstruction": 1.0,
                        "source_copy": 0.0,
                    },
                    wrong: {
                        "semantic_equivalence": 0.0,
                        "proof_reconstruction": 0.0,
                        "source_copy": 1.0,
                    },
                },
            )
        )
    return tuple(result)


def _manifest(
    examples: tuple[LegacyViewCalibrationExample, ...] | None = None,
) -> LegalIRSplitManifest:
    examples = examples or _examples()
    split_examples = tuple(
        LegalIRSplitExample(
            sample_id=item.sample_id,
            content_hash=f"{index + 1:064x}",
            source_span_key=f"doc-{index}:0:1",
        )
        for index, item in enumerate(examples)
    )
    return LegalIRSplitManifest(
        examples=split_examples,
        assignments={item.sample_id: "validation" for item in split_examples},
        config_digest="test-split-config",
    )


def _lineage(manifest: LegalIRSplitManifest) -> LegacyViewCalibrationLineage:
    return LegacyViewCalibrationLineage(
        teacher_state_sha256=_HASH["teacher"],
        student_state_sha256=_HASH["student"],
        split_manifest_sha256="sha256:" + manifest.digest,
        canary_artifact_sha256=_HASH["canary"],
        compiler_sha256=_HASH["compiler"],
        schema_sha256=_HASH["schema"],
        seed=17,
    )


def _metrics(
    *,
    ce: float = 0.30,
    cosine: float = 0.80,
    calibration: float = 0.10,
    semantic: float = 0.80,
    proof: float = 0.80,
    copy: float = 0.10,
    uncertainty: float = 0.20,
) -> FamilyCalibrationMetrics:
    return FamilyCalibrationMetrics(
        sample_count=4,
        cross_entropy=ce,
        cosine=cosine,
        calibration_error=calibration,
        semantic_equivalence=semantic,
        proof_reconstruction=proof,
        source_copy=copy,
        uncertainty=uncertainty,
    )


def _report(
    config: LegacyViewCalibrationConfig,
    *,
    split: str,
    overrides: dict[str, FamilyCalibrationMetrics] | None = None,
) -> LegacyViewEvaluationReport:
    overrides = overrides or {}
    return LegacyViewEvaluationReport(
        config_digest=config.digest,
        split=split,
        family_metrics={
            head: overrides.get(head, _metrics())
            for head in LEGACY_VIEW_CALIBRATION_HEADS
        },
    )


def test_alpha_zero_is_an_exact_nested_identity_and_never_adds_legacy_rows() -> None:
    current = {
        "feature-a": {"deontic.ir": 0.12345678901234567},
        "feature-b": {"modal.frame_logic": -4.5},
    }
    legacy = {
        "feature-a": {"deontic.ir": 99.0, "new-view": 88.0},
        "legacy-only": {"TDFOL.prover": 77.0},
    }

    calibrated = calibrate_feature_legal_ir_view_logits(
        current,
        legacy,
        LegacyViewCalibrationConfig.alpha_zero(),
    )

    assert calibrated == current
    assert calibrated is not current
    assert calibrated["feature-a"] is not current["feature-a"]
    assert "legacy-only" not in calibrated
    assert "new-view" not in calibrated["feature-a"]


def test_per_head_and_per_view_temperature_interpolation_and_confidence_gate() -> None:
    config = LegacyViewCalibrationConfig(
        heads={
            "deontic": HeadCalibration(
                temperature=2.0,
                alpha=0.5,
                minimum_confidence=0.0,
            ),
            "prover": HeadCalibration(
                temperature=1.0,
                alpha=0.75,
                minimum_confidence=0.99,
            ),
        },
        views={
            "deontic.special": ViewCalibration(
                temperature=1.0,
                alpha=0.25,
            )
        },
    )

    calibrated = calibrate_legacy_view_logits(
        {
            "deontic.ir": 2.0,
            "deontic.special": 4.0,
            "external_provers.router": 3.0,
        },
        {
            "deontic.ir": 10.0,
            "deontic.special": 8.0,
            "external_provers.router": 1.0,
        },
        config,
    )

    assert calibrated.logits["deontic.ir"] == pytest.approx(3.5)
    assert calibrated.logits["deontic.special"] == pytest.approx(5.0)
    assert calibrated.logits["external_provers.router"] == 3.0
    assert calibrated.effective_alpha_by_view["external_provers.router"] == 0.0
    assert calibrated.rejected_views["external_provers.router"] == (
        "below_minimum_confidence"
    )


def test_application_changes_only_feature_view_table_on_a_copied_state() -> None:
    current = ModalAutoencoderTrainingState(
        feature_family_logits={"keep": {"deontic": 2.0}},
        feature_legal_ir_view_logits={"feature": {"deontic.ir": 0.0}},
        legal_ir_view_logits={"global": 3.0},
    )
    legacy = ModalAutoencoderTrainingState(
        feature_family_logits={"do-not-transfer": {"deontic": 99.0}},
        feature_legal_ir_view_logits={"feature": {"deontic.ir": 8.0}},
        legal_ir_view_logits={"do-not-transfer": 99.0},
    )
    config = LegacyViewCalibrationConfig(
        heads={"deontic": HeadCalibration(alpha=0.5)}
    )

    candidate = apply_legacy_view_calibration(current, legacy, config)

    assert candidate is not current
    assert candidate.feature_legal_ir_view_logits["feature"]["deontic.ir"] == 4.0
    assert candidate.feature_family_logits == current.feature_family_logits
    assert candidate.legal_ir_view_logits == current.legal_ir_view_logits
    assert current.feature_legal_ir_view_logits["feature"]["deontic.ir"] == 0.0


def test_full_transfer_and_nonfinite_or_invalid_calibration_fail_closed() -> None:
    with pytest.raises(LegacyViewCalibrationError, match="full legacy"):
        LegacyViewCalibrationConfig(
            default=HeadCalibration(alpha=1.0)
        )
    with pytest.raises(LegacyViewCalibrationError, match="positive"):
        HeadCalibration(temperature=0.0)
    with pytest.raises(LegacyViewCalibrationError, match="finite"):
        HeadCalibration(alpha=float("nan"))
    with pytest.raises(LegacyViewCalibrationError, match="alpha one"):
        LegacyViewCalibrationSearchSpace(alphas=(0.0, 1.0))


def test_unknown_or_ambiguous_declared_heads_fail_closed() -> None:
    with pytest.raises(LegacyViewCalibrationError, match="unknown calibration head"):
        LegacyViewCalibrationConfig(
            heads={"deontci": HeadCalibration(alpha=0.25)}
        )
    with pytest.raises(LegacyViewCalibrationError, match="duplicate calibration head"):
        LegacyViewCalibrationConfig(
            heads={
                "deontic_ir": HeadCalibration(alpha=0.25),
                "deontic": HeadCalibration(alpha=0.5),
            }
        )
    with pytest.raises(LegacyViewCalibrationError, match="may not be empty"):
        LegacyViewCalibrationConfig(
            views={"": ViewCalibration(alpha=0.25)}
        )
    with pytest.raises(
        LegacyViewCalibrationError,
        match="unknown calibration example head",
    ):
        LegacyViewCalibrationExample(
            sample_id="bad-head",
            head="deontci",
            target_distribution={"deontic.ir": 1.0},
            current_logits={"deontic.ir": 0.0},
            legacy_logits={"deontic.ir": 1.0},
        )


def test_evaluation_reports_every_required_family_and_metric_independently() -> None:
    baseline = evaluate_legacy_view_calibration(_examples())

    assert tuple(baseline.family_metrics) == LEGACY_VIEW_CALIBRATION_HEADS
    serialized = baseline.to_dict()
    assert tuple(serialized["metric_names"]) == LEGACY_VIEW_CALIBRATION_METRICS
    for head, metrics in baseline.family_metrics.items():
        assert metrics.sample_count == 1
        assert metrics.cross_entropy > 2.0
        assert metrics.semantic_equivalence == 0.0
        assert metrics.proof_reconstruction == 0.0
        assert metrics.source_copy == 1.0
        assert 0.0 <= metrics.calibration_error <= 1.0
        assert 0.0 <= metrics.uncertainty <= 1.0
        assert serialized["family_metrics"][head]["ir_cross_entropy_loss"] == (
            metrics.cross_entropy
        )


def test_family_regression_cannot_be_masked_by_better_aggregate() -> None:
    config = LegacyViewCalibrationConfig.alpha_zero()
    baseline = _report(config, split="validation")
    candidate = _report(
        config,
        split="validation",
        overrides={
            "deontic": _metrics(ce=0.01, cosine=0.99),
            "cec": _metrics(ce=0.31),
        },
    )

    gate = compare_legacy_view_reports(baseline, candidate)

    assert gate.accepted is False
    assert gate.failed_families == ("cec",)
    assert "family_regression:cec:cross_entropy" in gate.reasons
    assert gate.to_dict()["aggregate_improvement_has_admission_authority"] is False


def test_report_comparison_rejects_split_or_population_mismatch() -> None:
    config = LegacyViewCalibrationConfig.alpha_zero()
    baseline = _report(config, split="validation")
    wrong_split = _report(config, split="canary")
    wrong_population = _report(
        config,
        split="validation",
        overrides={
            "global": FamilyCalibrationMetrics(
                sample_count=5,
                cross_entropy=0.30,
                cosine=0.80,
                calibration_error=0.10,
                semantic_equivalence=0.80,
                proof_reconstruction=0.80,
                source_copy=0.10,
                uncertainty=0.20,
            )
        },
    )

    assert compare_legacy_view_reports(
        baseline,
        wrong_split,
    ).reasons == ("evaluation_split_mismatch",)
    population_gate = compare_legacy_view_reports(
        baseline,
        wrong_population,
    )
    assert population_gate.accepted is False
    assert population_gate.failed_families == ("global",)
    assert "sample_count_mismatch:global" in population_gate.reasons


def test_search_is_lineage_bound_to_development_and_keeps_canary_hidden() -> None:
    examples = _examples()
    manifest = _manifest(examples)
    result = search_legacy_view_calibration(
        examples,
        lineage=_lineage(manifest),
        split_manifest=manifest,
        search_space=LegacyViewCalibrationSearchSpace(
            alphas=(0.0, 0.75),
            temperatures=(1.0,),
            minimum_confidences=(0.0,),
            confidence_powers=(0.0,),
            refine_views=False,
        ),
    )

    assert result.config.is_alpha_zero is False
    assert result.config.is_full_transfer is False
    assert result.development_gate.accepted is True
    assert result.development_report.family_metrics["knowledge_graph"].cross_entropy < (
        result.baseline_report.family_metrics["knowledge_graph"].cross_entropy
    )
    report = result.to_dict()
    assert verify_legacy_view_calibration_report(report) == report["report_sha256"]
    assert report["canary"] == {
        "artifact_sha256": _HASH["canary"],
        "hidden_during_search": True,
        "metrics_present": False,
    }
    assert "sample-deontic" not in repr(report)

    mismatched = LegacyViewCalibrationLineage(
        teacher_state_sha256=_HASH["teacher"],
        student_state_sha256=_HASH["student"],
        split_manifest_sha256="sha256:" + "f" * 64,
        canary_artifact_sha256=_HASH["canary"],
        compiler_sha256=_HASH["compiler"],
        schema_sha256=_HASH["schema"],
        seed=17,
    )
    with pytest.raises(LegacyViewCalibrationError, match="digest"):
        search_legacy_view_calibration(
            examples,
            lineage=mismatched,
            split_manifest=manifest,
            search_space=LegacyViewCalibrationSearchSpace(
                alphas=(0.0,),
                temperatures=(1.0,),
                minimum_confidences=(0.0,),
                confidence_powers=(0.0,),
            ),
        )


def test_promotion_rejects_canary_family_regression_and_lineage_mismatch() -> None:
    examples = _examples()
    manifest = _manifest(examples)
    search = search_legacy_view_calibration(
        examples,
        lineage=_lineage(manifest),
        split_manifest=manifest,
        search_space=LegacyViewCalibrationSearchSpace(
            alphas=(0.0, 0.75),
            temperatures=(1.0,),
            minimum_confidences=(0.0,),
            confidence_powers=(0.0,),
            refine_views=False,
        ),
    )
    canary_baseline = _report(
        LegacyViewCalibrationConfig.alpha_zero(), split="canary"
    )
    improvements = {
        head: _metrics(
            ce=0.20,
            cosine=0.90,
            calibration=0.05,
            semantic=0.90,
            proof=0.90,
            copy=0.05,
            uncertainty=0.10,
        )
        for head in LEGACY_VIEW_CALIBRATION_HEADS
    }
    improvements["tdfol"] = _metrics(
        ce=0.31,
        cosine=0.90,
        calibration=0.05,
        semantic=0.90,
        proof=0.90,
        copy=0.05,
        uncertainty=0.10,
    )
    canary_candidate = _report(
        search.config,
        split="canary",
        overrides=improvements,
    )

    decision = promote_legacy_view_calibration(
        search,
        canary_baseline,
        canary_candidate,
        canary_artifact_sha256="sha256:" + "f" * 64,
    )

    assert decision.accepted is False
    assert "canary_lineage_mismatch" in decision.reasons
    assert "tdfol" in decision.failed_families
    assert "canary:family_regression:tdfol:cross_entropy" in decision.reasons


def test_promotion_always_rejects_explicit_full_legacy_transfer() -> None:
    examples = _examples()
    manifest = _manifest(examples)
    baseline_config = LegacyViewCalibrationConfig.alpha_zero()
    full_transfer = LegacyViewCalibrationConfig(
        default=HeadCalibration(alpha=1.0),
        full_transfer_allowed=True,
    )
    development_baseline = _report(
        baseline_config,
        split="validation",
    )
    development_candidate = _report(
        full_transfer,
        split="validation",
    )
    search = LegacyViewCalibrationSearchResult(
        lineage=_lineage(manifest),
        config=full_transfer,
        baseline_report=development_baseline,
        development_report=development_candidate,
        development_gate=compare_legacy_view_reports(
            development_baseline,
            development_candidate,
        ),
        evaluated_candidate_count=1,
        rejected_candidate_count=0,
    )

    decision = promote_legacy_view_calibration(
        search,
        _report(baseline_config, split="canary"),
        _report(full_transfer, split="canary"),
        canary_artifact_sha256=_HASH["canary"],
    )

    assert decision.accepted is False
    assert "full_legacy_transfer_forbidden" in decision.reasons


def test_promotion_accepts_only_selected_lineage_bound_nonregressing_candidate() -> None:
    examples = _examples()
    manifest = _manifest(examples)
    search = search_legacy_view_calibration(
        examples,
        lineage=_lineage(manifest),
        split_manifest=manifest,
        search_space=LegacyViewCalibrationSearchSpace(
            alphas=(0.0, 0.75),
            temperatures=(1.0,),
            minimum_confidences=(0.0,),
            confidence_powers=(0.0,),
            refine_views=False,
        ),
    )
    baseline = _report(
        LegacyViewCalibrationConfig.alpha_zero(), split="canary"
    )
    candidate = _report(
        search.config,
        split="canary",
        overrides={
            head: _metrics(
                ce=0.20,
                cosine=0.90,
                calibration=0.05,
                semantic=0.90,
                proof=0.90,
                copy=0.05,
                uncertainty=0.10,
            )
            for head in LEGACY_VIEW_CALIBRATION_HEADS
        },
    )

    decision = promote_legacy_view_calibration(
        search,
        baseline,
        candidate,
        canary_artifact_sha256=_HASH["canary"],
    )

    assert decision.accepted is True
    assert decision.failed_families == ()


def test_evaluator_packet_rejects_canary_observations() -> None:
    module_path = (
        ROOT / "scripts" / "ops" / "legal_ir" / "evaluate_legacy_view_calibration.py"
    )
    spec = importlib.util.spec_from_file_location(
        "evaluate_legacy_view_calibration_under_test", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    with pytest.raises(LegacyViewCalibrationError, match="remain hidden"):
        module.evaluate_packet({"canary_examples": []})
    with pytest.raises(LegacyViewCalibrationError, match="remain hidden"):
        module.evaluate_packet(
            {"metadata": {"canary_metrics": {"cross_entropy": 0.1}}}
        )


def test_evaluator_packet_emits_source_free_hidden_canary_report() -> None:
    module_path = (
        ROOT / "scripts" / "ops" / "legal_ir" / "evaluate_legacy_view_calibration.py"
    )
    spec = importlib.util.spec_from_file_location(
        "evaluate_legacy_view_calibration_packet_under_test", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    examples = _examples()
    manifest = _manifest(examples)
    packet_examples = [
        {
            "current_logits": dict(example.current_logits),
            "family": example.head,
            "legacy_logits": dict(example.legacy_logits),
            "outcomes_by_view": {
                view: dict(metrics)
                for view, metrics in example.outcomes_by_view.items()
            },
            "sample_id": example.sample_id,
            "target_distribution": dict(example.target_distribution),
        }
        for example in examples
    ]

    report = module.evaluate_packet(
        {
            "development_examples": packet_examples,
            "lineage": _lineage(manifest).to_dict(),
            "search_space": {
                "alphas": [0.0, 0.75],
                "confidence_powers": [0.0],
                "minimum_confidences": [0.0],
                "refine_views": False,
                "temperatures": [1.0],
            },
            "split_manifest": manifest.to_dict(),
        }
    )

    assert report["canary"]["hidden_during_search"] is True
    assert report["canary"]["metrics_present"] is False
    assert report["development_gate"]["accepted"] is True
    for example in examples:
        assert example.sample_id not in repr(report)
