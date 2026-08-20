"""Analytical and contract tests for versioned IRLossConfiguration@1."""

from __future__ import annotations

import math

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_grammar_decoder import (
    LEGAL_IR_CANONICAL_VOCABULARY_CID,
    LEGAL_IR_TOKEN_CLASSES,
    build_compatible_learned_architecture,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_loss_configuration import (
    IR_LOSS_COMPONENT_NAMES,
    IR_LOSS_CONFIGURATION_INTERFACE,
    IR_LOSS_CONFIGURATION_SCHEMA,
    IR_LOSS_EXCLUSIONS,
    IR_LOSS_REPORTED_TOKEN_CLASSES,
    AdaptiveWeightBoundError,
    AllRecordCosineMaximizationError,
    CANONICAL_IR_LOSS_CONFIGURATION_CID,
    DurableFloatWeightError,
    FixedPointWeight,
    IRLossBatch,
    IRLossNonfiniteError,
    IRLossPairAdmission,
    IRLossRecord,
    IsolatedLossMissingError,
    MemoryBankCheckpointMismatchError,
    ProofInGradientPathError,
    bind_memory_bank_to_checkpoint,
    canonical_ir_loss_configuration,
    evaluate_ir_composite_loss,
    filter_false_negatives,
    isolate_ir_loss_component,
    masked_token_class_cross_entropy,
    normalized_cosine_loss,
    sample_contrastive_negatives,
    supervised_contrastive_loss,
    teacher_forcing_and_free_run_results,
)


def _peaked_row(size: int, target: int, peak: float = 20.0) -> tuple[float, ...]:
    row = [0.0] * size
    row[target] = peak
    return tuple(row)


def _token_record(
    record_id: str,
    *,
    lineage_id: str = "L1",
    decode_targets: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 0),
    token_classes: tuple[str, ...] = (
        "binder",
        "operator",
        "type",
        "source",
        "family",
        "proof",
        "tactic",
        "padding",
    ),
    peak: float = 20.0,
    free_run_peak: float = 0.0,
    latent: tuple[float, ...] = (1.0, 0.0),
    **kwargs: object,
) -> IRLossRecord:
    vocab = 8
    teacher = tuple(_peaked_row(vocab, target, peak=peak) for target in decode_targets)
    free = tuple(_peaked_row(vocab, target, peak=free_run_peak) for target in decode_targets)
    return IRLossRecord(
        record_id=record_id,
        lineage_id=lineage_id,
        token_ids=decode_targets,
        token_classes=token_classes,
        teacher_forcing_logits=teacher,
        free_run_logits=free,
        latent=latent,
        reconstruction=kwargs.pop("reconstruction", (1.0, 0.0)),
        cycle_target=kwargs.pop("cycle_target", (1.0, 0.0)),
        **kwargs,
    )


def test_canonical_configuration_is_fixed_point_and_content_addressed() -> None:
    architecture = build_compatible_learned_architecture("shared_latent", seed=7)
    checkpoint = architecture.initialization_checkpoint()
    config = canonical_ir_loss_configuration(
        tokenizer_vocabulary_cid=LEGAL_IR_CANONICAL_VOCABULARY_CID,
        architecture_initialization_root=str(
            checkpoint.get("schema", "IRCompatibleArchitectureInitCheckpoint@1")
        ),
    )
    payload = config.to_dict()

    assert payload["schema"] == IR_LOSS_CONFIGURATION_SCHEMA
    assert payload["interface"] == IR_LOSS_CONFIGURATION_INTERFACE
    assert tuple(payload["exclusions"]) == IR_LOSS_EXCLUSIONS
    assert tuple(payload["components"]) == IR_LOSS_COMPONENT_NAMES
    assert config.component("proof").in_gradient_path is False
    assert config.component("proof").weight == FixedPointWeight.zero()
    assert payload["precision"]["durable_weight_encoding"] == "rational"
    assert "float" not in str(type(payload["components"]["token_class_ce"]["weight"]["numerator"]))
    assert isinstance(payload["components"]["token_class_ce"]["weight"]["numerator"], int)
    assert isinstance(payload["components"]["token_class_ce"]["weight"]["denominator"], int)
    assert config.identity() == canonical_ir_loss_configuration(
        tokenizer_vocabulary_cid=LEGAL_IR_CANONICAL_VOCABULARY_CID,
        architecture_initialization_root=config.architecture_initialization_root,
    ).identity()
    baseline = canonical_ir_loss_configuration()
    assert baseline.identity() == CANONICAL_IR_LOSS_CONFIGURATION_CID
    assert baseline.identity().startswith("sha256:")


def test_durable_weights_reject_ieee_floats() -> None:
    with pytest.raises(DurableFloatWeightError):
        FixedPointWeight.parse(0.5)
    with pytest.raises(DurableFloatWeightError):
        FixedPointWeight.parse({"numerator": 1.0, "denominator": 2})
    weight = FixedPointWeight.parse("1/2")
    assert weight.to_dict()["rational"] == "1/2"
    assert weight.as_float() == pytest.approx(0.5)


def test_masked_token_class_ce_has_analytical_goldens_and_reports_each_class() -> None:
    logits = (
        (0.0, 0.0),
        (20.0, 0.0),
        (0.0, 0.0),
    )
    mean, per_class, counts = masked_token_class_cross_entropy(
        logits,
        (0, 0, 0),
        ("binder", "padding", "operator"),
    )

    assert mean == pytest.approx(math.log(2.0))
    assert per_class["binder"] == pytest.approx(math.log(2.0))
    assert per_class["operator"] == pytest.approx(math.log(2.0))
    assert per_class["padding"] == pytest.approx(0.0, abs=1.0e-8)
    assert counts["binder"] == 1
    assert counts["padding"] == 1
    assert set(per_class) == set(IR_LOSS_REPORTED_TOKEN_CLASSES)
    assert all(name in LEGAL_IR_TOKEN_CLASSES for name in IR_LOSS_REPORTED_TOKEN_CLASSES)


def test_source_surface_tokens_are_excluded_from_canonical_ce_mean() -> None:
    logits = ((0.0, 0.0), (0.0, 0.0))
    mean, per_class, counts = masked_token_class_cross_entropy(
        logits,
        (0, 0),
        ("source_surface", "binder"),
    )

    assert mean == pytest.approx(math.log(2.0))
    assert per_class["source"] == pytest.approx(math.log(2.0))
    assert counts["source"] == 1


def test_normalized_cosine_goldens_and_all_record_prohibition() -> None:
    assert normalized_cosine_loss((3.0, 0.0), (9.0, 0.0)) == pytest.approx(0.0)
    assert normalized_cosine_loss((1.0, 0.0), (0.0, 1.0)) == pytest.approx(1.0)
    assert normalized_cosine_loss((1.0, 0.0), (-1.0, 0.0)) == pytest.approx(2.0)

    left = _token_record("a", latent=(1.0, 0.0))
    right = _token_record("b", lineage_id="L2", latent=(0.0, 1.0))
    with pytest.raises(AllRecordCosineMaximizationError):
        evaluate_ir_composite_loss(
            IRLossBatch(records=(left, right), pair_admissions=())
        )
    admitted = evaluate_ir_composite_loss(
        IRLossBatch(
            records=(left, right),
            pair_admissions=(
                IRLossPairAdmission("a", "b", pair_class="positive", admitted=True),
            ),
        )
    )
    assert admitted.component("normalized_cosine").raw == pytest.approx(1.0)


def test_supervised_contrastive_analytical_infonce_golden() -> None:
    loss = supervised_contrastive_loss(
        (1.0, 0.0),
        (2.0, 0.0),
        ((0.0, 1.0),),
        temperature=1.0,
    )
    expected = -math.log(math.e / (math.e + 1.0))
    assert loss == pytest.approx(expected)


def test_each_loss_component_is_isolatable() -> None:
    record = _token_record(
        "iso",
        structural_penalty=0.4,
        relation_penalty=0.3,
        semantic_gap=0.2,
        source_span_penalty=0.5,
        parameter_l2=0.8,
        confidence=0.9,
        correctness=0.0,
        proof_success=1.0,
    )
    batch = IRLossBatch(records=(record,))
    config = canonical_ir_loss_configuration()

    for name in IR_LOSS_COMPONENT_NAMES:
        isolated = isolate_ir_loss_component(batch, name, config)
        for other in IR_LOSS_COMPONENT_NAMES:
            if other == name:
                continue
            assert isolated.component(other).weighted == 0.0
        if name == "proof":
            assert isolated.component(name).in_gradient_path is False
            assert isolated.gradient_total == 0.0
        else:
            assert isolated.total == pytest.approx(isolated.component(name).weighted)

    with pytest.raises(IsolatedLossMissingError):
        isolate_ir_loss_component(batch, "hidden_macro_ce", config)


def test_teacher_forcing_and_free_run_are_distinct() -> None:
    record = _token_record("tf", peak=20.0, free_run_peak=0.0)
    results = teacher_forcing_and_free_run_results((record,))

    assert results["teacher_forcing"].decode_mode == "teacher_forcing"
    assert results["free_run"].decode_mode == "free_run"
    teacher_ce = results["teacher_forcing"].component("token_class_ce").raw
    free_ce = results["free_run"].component("token_class_ce").raw
    assert teacher_ce < 1.0e-6
    assert free_ce == pytest.approx(math.log(8.0))
    assert teacher_ce != free_ce
    reported = results["teacher_forcing"].component("token_class_ce").token_class_ce
    assert set(reported) >= set(IR_LOSS_REPORTED_TOKEN_CLASSES)


def test_proof_signal_is_nondifferentiable_and_rejects_prover_calls() -> None:
    record = _token_record("p", proof_label="verified", proof_success=1.0)
    result = evaluate_ir_composite_loss(IRLossBatch(records=(record,)))

    assert result.proof_in_gradient_path is False
    assert result.component("proof").in_gradient_path is False
    assert result.component("proof").weighted == 0.0
    assert result.component("proof").details["role"] == "curriculum"
    with pytest.raises(ProofInGradientPathError):
        IRLossBatch(records=(record,), proof_callable=lambda: "kernel")


def test_sampler_filters_false_negative_fixtures() -> None:
    anchor = _token_record("anchor", lineage_id="G1", pair_ids=("proof-twin",), latent=(1.0, 0.0))
    same_lineage = _token_record("sib", lineage_id="G1", latent=(0.0, 1.0))
    alpha = _token_record(
        "alpha",
        lineage_id="G2",
        false_negative_class="alpha_equivalent",
        latent=(0.0, 1.0),
    )
    notation = _token_record(
        "notation",
        lineage_id="G3",
        false_negative_class="alternate_notation",
        latent=(0.0, 1.0),
    )
    translation = _token_record(
        "trans",
        lineage_id="G4",
        false_negative_class="translation_sibling",
        latent=(0.0, 1.0),
    )
    proof_eq = _token_record("proof-twin", lineage_id="G5", latent=(0.0, 1.0))
    true_negative = _token_record("neg", lineage_id="G6", latent=(0.0, 1.0))
    admissions = (
        IRLossPairAdmission("anchor", "neg", pair_class="negative", admitted=True),
        IRLossPairAdmission("anchor", "sib", pair_class="negative", admitted=True),
        IRLossPairAdmission("anchor", "alpha", pair_class="negative", admitted=True),
        IRLossPairAdmission("anchor", "notation", pair_class="negative", admitted=True),
        IRLossPairAdmission("anchor", "trans", pair_class="negative", admitted=True),
        IRLossPairAdmission("anchor", "proof-twin", pair_class="negative", admitted=True),
    )
    kept, filtered = filter_false_negatives(
        anchor,
        (same_lineage, alpha, notation, translation, proof_eq, true_negative),
        admissions,
    )

    assert tuple(item.record_id for item in kept) == ("neg",)
    assert {item.record_id for item in filtered} == {
        "sib",
        "alpha",
        "notation",
        "trans",
        "proof-twin",
    }
    sampled, filtered_again, sampler_id = sample_contrastive_negatives(
        anchor,
        (same_lineage, alpha, notation, translation, proof_eq, true_negative),
        admissions,
        canonical_ir_loss_configuration().sampler,
        checkpoint_id="ckpt-1",
    )
    assert tuple(item.record_id for item in sampled) == ("neg",)
    assert sampler_id == canonical_ir_loss_configuration().sampler.identity()
    assert len(filtered_again) == 5


def test_memory_bank_is_bound_to_checkpoint_identity() -> None:
    bank = bind_memory_bank_to_checkpoint(
        "ckpt-32",
        keys=("n1",),
        vectors=((0, 1),),
    )
    assert bank.identity().startswith("sha256:")
    assert bank.bind("ckpt-32") is bank
    with pytest.raises(MemoryBankCheckpointMismatchError):
        bank.bind("ckpt-other")
    with pytest.raises(DurableFloatWeightError):
        bind_memory_bank_to_checkpoint("ckpt-32", keys=("n1",), vectors=((0.1, 0.2),))


def test_nonfinite_inputs_are_rejected() -> None:
    with pytest.raises(IRLossNonfiniteError):
        masked_token_class_cross_entropy(
            ((float("nan"), 0.0),),
            (0,),
            ("binder",),
        )
    with pytest.raises(IRLossNonfiniteError):
        normalized_cosine_loss((float("inf"), 0.0), (1.0, 0.0))
    exploding = _token_record("bad")
    exploding = IRLossRecord(
        record_id="bad",
        lineage_id="L",
        structural_penalty=float("nan"),
        teacher_forcing_logits=(),
        free_run_logits=(),
        token_ids=(),
        token_classes=(),
    )
    with pytest.raises(IRLossNonfiniteError):
        evaluate_ir_composite_loss(IRLossBatch(records=(exploding,)))


def test_adaptive_weights_are_optional_and_bounded() -> None:
    record = _token_record("aw", structural_penalty=1.0)
    static = evaluate_ir_composite_loss(IRLossBatch(records=(record,)))
    assert static.component("structural").weighted == pytest.approx(0.5)

    adaptive_config = canonical_ir_loss_configuration(adaptive_weights_enabled=True)
    raised = evaluate_ir_composite_loss(
        IRLossBatch(
            records=(record,),
            adaptive_weights={"structural": FixedPointWeight(2, 1)},
        ),
        adaptive_config,
    )
    assert raised.component("structural").weighted == pytest.approx(2.0)
    with pytest.raises(AdaptiveWeightBoundError):
        evaluate_ir_composite_loss(
            IRLossBatch(
                records=(record,),
                adaptive_weights={"structural": FixedPointWeight(9, 1)},
            ),
            adaptive_config,
        )
    with pytest.raises(AdaptiveWeightBoundError):
        evaluate_ir_composite_loss(
            IRLossBatch(
                records=(record,),
                adaptive_weights={"structural": FixedPointWeight(2, 1)},
            )
        )


def test_composite_reports_identities_and_gradient_policy() -> None:
    left = _token_record("a", latent=(1.0, 0.0), proof_success=0.0)
    right = _token_record(
        "b",
        lineage_id="L2",
        latent=(1.0, 0.0),
        pair_ids=(),
    )
    bank = bind_memory_bank_to_checkpoint("ckpt-7", keys=("b",), vectors=((1, 0),))
    result = evaluate_ir_composite_loss(
        IRLossBatch(
            records=(left, right),
            pair_admissions=(
                IRLossPairAdmission("a", "b", pair_class="positive"),
            ),
            checkpoint_id="ckpt-7",
            memory_bank=bank,
        )
    )
    config = canonical_ir_loss_configuration()

    assert result.schema == IR_LOSS_CONFIGURATION_SCHEMA
    assert result.configuration_identity == config.identity()
    assert result.precision_identity == config.precision.identity()
    assert result.schedule_identity == config.schedule.identity()
    assert result.sampler_identity == config.sampler.identity()
    assert result.memory_bank_identity == bank.identity()
    assert result.nonfinite_policy == "reject"
    assert result.proof_in_gradient_path is False
    assert result.gradient_total == pytest.approx(
        sum(
            result.component(name).weighted
            for name in IR_LOSS_COMPONENT_NAMES
            if result.component(name).in_gradient_path
        )
    )


def test_sampler_is_reproducible_for_the_same_seed() -> None:
    anchor = _token_record("anchor", lineage_id="A")
    pool = tuple(
        _token_record(f"n{index}", lineage_id=f"N{index}", latent=(0.0, 1.0))
        for index in range(6)
    )
    admissions = tuple(
        IRLossPairAdmission("anchor", item.record_id, pair_class="negative")
        for item in pool
    )
    first, _, identity_a = sample_contrastive_negatives(
        anchor,
        pool,
        admissions,
        canonical_ir_loss_configuration(sampler_seed=11).sampler,
        limit=3,
    )
    second, _, identity_b = sample_contrastive_negatives(
        anchor,
        pool,
        admissions,
        canonical_ir_loss_configuration(sampler_seed=11).sampler,
        limit=3,
    )
    third, _, identity_c = sample_contrastive_negatives(
        anchor,
        pool,
        admissions,
        canonical_ir_loss_configuration(sampler_seed=99).sampler,
        limit=3,
    )

    assert tuple(item.record_id for item in first) == tuple(item.record_id for item in second)
    assert identity_a == identity_b
    assert identity_a != identity_c
    assert tuple(item.record_id for item in first) != tuple(item.record_id for item in third)
