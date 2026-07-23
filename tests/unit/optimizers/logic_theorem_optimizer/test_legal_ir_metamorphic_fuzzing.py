"""Tests for LegalIR metamorphic and differential fuzzing."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import (
    FUZZING_TARGETS,
    LEGAL_IR_FUZZING_SCHEMA_VERSION,
    SEMANTICS_CHANGING,
    SEMANTICS_PRESERVING,
    TARGET_DECOMPILER,
    TARGET_DETERMINISTIC_IR,
    TARGET_LEARNED_IR,
    TARGET_OBLIGATIONS,
    TARGET_TEXT,
    LegalIRFuzzer,
    LegalIRFuzzingConfig,
    minimize_legal_ir_counterexample,
    run_legal_ir_metamorphic_fuzzing,
)


LEGAL_TEXT = (
    "The agency shall provide notice unless emergency conditions exist "
    "within 30 days."
)


def test_fuzzer_generates_preserving_and_changing_mutations_for_all_legal_ir_surfaces() -> None:
    report = run_legal_ir_metamorphic_fuzzing(LEGAL_TEXT, sample_id="lir-fuzz-unit")

    assert report.schema_version == LEGAL_IR_FUZZING_SCHEMA_VERSION
    assert report.passed is True
    assert report.mutation_count >= len(FUZZING_TARGETS) * 2
    for target in FUZZING_TARGETS:
        assert report.coverage_by_target[target][SEMANTICS_PRESERVING] >= 1
        assert report.coverage_by_target[target][SEMANTICS_CHANGING] >= 1

    preserving = [
        result
        for result in report.results
        if result.mutation.relation == SEMANTICS_PRESERVING
    ]
    changing = [
        result
        for result in report.results
        if result.mutation.relation == SEMANTICS_CHANGING
    ]

    assert preserving
    assert all(result.invariant_holds for result in preserving)
    assert all(result.verified for result in preserving)
    assert changing
    assert all(result.expected_change_detected for result in changing)
    assert all(result.verified for result in changing)


def test_differential_checks_cover_compiler_learned_hammer_and_decompiler_round_trips() -> None:
    report = run_legal_ir_metamorphic_fuzzing(LEGAL_TEXT, sample_id="lir-fuzz-diff")

    for result in report.results:
        metrics = result.differential_metrics
        assert "compiler_vs_learned_guidance" in metrics
        assert "compiler_vs_decompiler" in metrics
        assert "hammer_obligation_delta" in metrics
        assert "baseline_round_trip" in metrics
        assert "mutated_round_trip" in metrics
        assert "proof_obligation_delta" in metrics
        assert "round_trip_structural_delta" in metrics
        assert "structural_equivalence" in result.semantic_metrics["scores"]
        assert "obligation_equivalence" in result.semantic_metrics["scores"]

    by_operator = {result.mutation.operator: result for result in report.results}
    assert by_operator["learned_ir_modality_flip"].learned_similarity < 1.0
    assert by_operator["obligation_statement_mutation"].hammer_obligation_similarity < 1.0
    assert by_operator["decompiler_feature_drop"].decompiler_similarity < 1.0
    assert by_operator["decompiler_source_copy_violation"].grammar_rejections


def test_trusted_negative_candidates_are_verified_and_source_copy_safe() -> None:
    report = run_legal_ir_metamorphic_fuzzing(LEGAL_TEXT, sample_id="lir-fuzz-neg")

    assert report.trusted_negative_candidates
    changing_ids = {
        result.mutation.mutation_id
        for result in report.results
        if result.mutation.relation == SEMANTICS_CHANGING and result.verified
    }
    preserving_ids = {
        result.mutation.mutation_id
        for result in report.results
        if result.mutation.relation == SEMANTICS_PRESERVING
    }
    for candidate in report.trusted_negative_candidates:
        payload = candidate.to_dict()
        assert payload["trusted"] is True
        assert payload["training_partition"] == "trusted_negative"
        assert payload["verification"]["verified"] is True
        assert payload["source_mutation_id"] in changing_ids
        assert payload["source_mutation_id"] not in preserving_ids
        assert payload["source_text_sha256"]
        assert payload["mutated_payload_sha256"]
        assert "verified_by" in payload["verification"]

    unsafe = next(
        candidate
        for candidate in report.trusted_negative_candidates
        if candidate.target == TARGET_DECOMPILER
        and "unsafe_decompiler_source_copy_policy"
        in candidate.verification["grammar_rejections"]
    )
    assert _contains_hash_only_redaction(unsafe.to_dict()["minimal_counterexample"])


def test_unverified_mutations_are_not_stored_as_trusted_negatives() -> None:
    fuzzer = LegalIRFuzzer(
        config=LegalIRFuzzingConfig(targets=(TARGET_DETERMINISTIC_IR,))
    )
    baseline = fuzzer._bundle_from_text(LEGAL_TEXT, sample_id="lir-fuzz-unverified")
    preserving = next(
        mutation
        for mutation in fuzzer.generate_mutations(baseline)
        if mutation.target == TARGET_DETERMINISTIC_IR
        and mutation.relation == SEMANTICS_PRESERVING
    )

    result = fuzzer.evaluate_mutation(
        baseline,
        preserving,
        sample_id="lir-fuzz-unverified",
    )

    assert result.verified is True
    assert result.counterexample is None


def test_counterexample_minimizer_preserves_verification_predicate() -> None:
    payload = {
        "family": "decompiler",
        "target_view": "deontic.ir",
        "source_copy_policy": "raw_source",
        "steps": [
            {"op": "emit_text", "surface": LEGAL_TEXT},
            {"op": "unused", "surface": "remove me"},
        ],
        "metadata": {"noise": "remove"},
    }

    minimized = minimize_legal_ir_counterexample(
        payload,
        lambda item: isinstance(item, dict)
        and item.get("source_copy_policy") == "raw_source",
    )

    assert minimized == {"source_copy_policy": "raw_source"}


def test_config_can_focus_individual_targets_without_losing_surface_semantics() -> None:
    for target in (
        TARGET_TEXT,
        TARGET_DETERMINISTIC_IR,
        TARGET_LEARNED_IR,
        TARGET_OBLIGATIONS,
        TARGET_DECOMPILER,
    ):
        report = run_legal_ir_metamorphic_fuzzing(
            LEGAL_TEXT,
            sample_id=f"lir-fuzz-{target}",
            config=LegalIRFuzzingConfig(targets=(target,)),
        )

        assert report.passed is True
        assert set(result.mutation.target for result in report.results) == {target}
        assert report.coverage_by_target[target][SEMANTICS_PRESERVING] >= 1
        assert report.coverage_by_target[target][SEMANTICS_CHANGING] >= 1


def _contains_hash_only_redaction(value: object) -> bool:
    if isinstance(value, dict):
        if value.get("source_copy_policy") == "hash_only" and value.get("redacted"):
            return True
        return any(_contains_hash_only_redaction(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_hash_only_redaction(item) for item in value)
    return False
