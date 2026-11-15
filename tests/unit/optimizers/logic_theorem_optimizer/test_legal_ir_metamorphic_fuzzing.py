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


LEGAL_TEXT = "The agency shall provide notice unless emergency conditions exist within 30 days."


def test_fuzzer_generates_preserving_and_changing_mutations_for_all_legal_ir_surfaces() -> None:
    report = run_legal_ir_metamorphic_fuzzing(LEGAL_TEXT, sample_id="lir-fuzz-unit")

    assert report.schema_version == LEGAL_IR_FUZZING_SCHEMA_VERSION
    assert report.passed is True
    assert report.mutation_count >= len(FUZZING_TARGETS) * 2
    for target in FUZZING_TARGETS:
        assert report.coverage_by_target[target][SEMANTICS_PRESERVING] >= 1
        assert report.coverage_by_target[target][SEMANTICS_CHANGING] >= 1

    preserving = [
        result for result in report.results if result.mutation.relation == SEMANTICS_PRESERVING
    ]
    changing = [
        result for result in report.results if result.mutation.relation == SEMANTICS_CHANGING
    ]

    assert preserving
    assert all(result.invariant_holds for result in preserving)
    assert all(result.verified is False for result in preserving)
    assert changing
    assert all(result.expected_change_detected for result in changing)
    assert all(result.verified is False for result in changing)


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


def test_diagnostic_negative_proposals_are_untrusted_and_source_copy_safe() -> None:
    report = run_legal_ir_metamorphic_fuzzing(LEGAL_TEXT, sample_id="lir-fuzz-neg")

    assert report.schema_version == "legal-ir-metamorphic-differential-fuzzing-v2"
    assert report.trusted_negative_candidates == ()
    changing_ids = {
        result.mutation.mutation_id
        for result in report.results
        if result.mutation.relation == SEMANTICS_CHANGING
        and result.expected_change_detected and result.differential_consistent
    }
    preserving_ids = {
        result.mutation.mutation_id
        for result in report.results
        if result.mutation.relation == SEMANTICS_PRESERVING
    }
    proposals = tuple(result.counterexample for result in report.results if result.counterexample is not None)
    assert proposals
    for candidate in proposals:
        payload = candidate.to_dict()
        assert payload["trusted"] is False
        assert payload["training_partition"] == "unverified_proposal"
        assert payload["schema_version"] == "legal-ir-fuzzing-unverified-proposal-v2"
        assert payload["verification"]["verified"] is False
        assert payload["verification"]["verified_by"] == []
        assert payload["verification"]["diagnostic_checks"] == [
            "metamorphic_metric_oracle", "deterministic_compiler", "learned_guidance_projection",
            "hammer_obligation_delta", "decompiler_round_trip",
        ]
        assert payload["source_mutation_id"] in changing_ids
        assert payload["source_mutation_id"] not in preserving_ids
        assert payload["source_text_sha256"]
        assert payload["mutated_payload_sha256"]

    unsafe = next(
        candidate for candidate in proposals
        if candidate.target == TARGET_DECOMPILER
        and "unsafe_decompiler_source_copy_policy" in candidate.verification["grammar_rejections"]
    )
    assert _contains_hash_only_redaction(unsafe.to_dict()["minimal_counterexample"])

def test_unverified_mutations_are_not_stored_as_trusted_negatives() -> None:
    fuzzer = LegalIRFuzzer(config=LegalIRFuzzingConfig(targets=(TARGET_DETERMINISTIC_IR,)))
    baseline = fuzzer._bundle_from_text(LEGAL_TEXT, sample_id="lir-fuzz-unverified")
    preserving = next(
        mutation
        for mutation in fuzzer.generate_mutations(baseline)
        if mutation.target == TARGET_DETERMINISTIC_IR and mutation.relation == SEMANTICS_PRESERVING
    )

    result = fuzzer.evaluate_mutation(
        baseline,
        preserving,
        sample_id="lir-fuzz-unverified",
    )

    assert result.invariant_holds is True
    assert result.differential_consistent is True
    assert result.passed is True
    assert result.verified is False
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
        lambda item: isinstance(item, dict) and item.get("source_copy_policy") == "raw_source",
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


# Heuristic mutation diagnostics are proposals, not independently checked
# semantic labels. These controls use no model or filesystem fixture.
def test_legacy_decompiler_heuristics_without_independent_evidence_export_no_trusted_negatives() -> None:
    report = run_legal_ir_metamorphic_fuzzing(
        LEGAL_TEXT,
        sample_id="lir-legacy-decompiler-unattested-export",
        config=LegalIRFuzzingConfig(targets=(TARGET_DECOMPILER,)),
    )
    changing = tuple(
        result for result in report.results
        if result.mutation.relation == SEMANTICS_CHANGING
    )
    assert changing
    assert any(result.grammar_rejections for result in changing)
    assert all(result.differential_metrics for result in changing)
    assert all(result.semantic_metrics for result in changing)

    assert report.trusted_negative_candidates == (), (
        "heuristic and grammar diagnostics cannot supply independent semantic "
        "evidence or export trusted training negatives"
    )
    assert all(result.verified is False for result in changing)


def test_legacy_fuzzer_proposals_without_independent_evidence_admit_no_curriculum_examples() -> None:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_hard_negatives import (
        LegalIRHardNegativeConfig,
        build_legal_ir_hard_negative_curriculum,
    )

    report = run_legal_ir_metamorphic_fuzzing(
        LEGAL_TEXT,
        sample_id="lir-legacy-decompiler-unattested-curriculum",
        config=LegalIRFuzzingConfig(targets=(TARGET_DECOMPILER,)),
    )
    changing = tuple(
        result for result in report.results
        if result.mutation.relation == SEMANTICS_CHANGING
    )
    assert changing
    assert any(result.grammar_rejections for result in changing)
    proposals = tuple(
        result.counterexample for result in changing
        if result.counterexample is not None
    )
    assert proposals, "retain diagnostic proposals without promoting their authority"
    # Downgrading these detached proposal flags supplies no checking evidence.
    # The opt-out must not upgrade an explicitly untrusted proposal either.
    untrusted_proposals = []
    for proposal in proposals:
        payload = proposal.to_dict()
        payload["trusted"] = False
        payload["verification"] = {**payload["verification"], "verified": False}
        untrusted_proposals.append(payload)

    for config in (None, LegalIRHardNegativeConfig(require_verified_negatives=False)):
        curriculum = build_legal_ir_hard_negative_curriculum(
            verified_counterexamples=untrusted_proposals,
            config=config,
        )
        assert curriculum.accepted_count == 0, (
            "legacy fuzzer proposals explicitly marked untrusted cannot admit "
            "semantic training labels, including when verification is optional"
        )
        assert curriculum.examples == ()
        assert curriculum.stages == ()
        assert curriculum.ready_for_training is False
        assert curriculum.rejected_count == len(untrusted_proposals)


# Explicit caller claims below are compatibility DATA, not authenticated checker
# executions. Actual producer proposals retain their separate untrusted epoch.
def _legacy_explicit_trusted_caller_control():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import TrustedNegativeCandidate

    return TrustedNegativeCandidate(
        candidate_id="fixture:explicit-trusted-caller-control",
        source_mutation_id="fixture:caller-declared-mutation",
        target=TARGET_DETERMINISTIC_IR,
        relation=SEMANTICS_CHANGING,
        label="semantic_non_equivalence",
        minimal_counterexample={"rules": [{"actor": "agency", "action": "provide",
            "modality": "permission", "object": "notice"}]},
        verification={"verified": True,
            "verified_by": ["fixture:explicit-caller-claim-not-an-executed-checker"]},
    )


def test_legacy_actual_proposal_objects_and_wires_remain_nontraining_under_both_policies() -> None:
    from copy import deepcopy
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_hard_negatives import (
        LegalIRHardNegativeConfig, build_legal_ir_hard_negative_curriculum,
    )

    report = run_legal_ir_metamorphic_fuzzing(LEGAL_TEXT,
        sample_id="fixture:actual-proposal-policy-forms",
        config=LegalIRFuzzingConfig(targets=(TARGET_DECOMPILER,)))
    proposals = tuple(result.counterexample for result in report.results if result.counterexample is not None)
    assert proposals and all(proposal.trusted is False for proposal in proposals)
    original = deepcopy([proposal.to_dict() for proposal in proposals])
    for required in (True, False):
        config = LegalIRHardNegativeConfig(require_verified_negatives=required,
            require_all_negative_families=False)
        for offered in (proposals, tuple(proposal.to_dict() for proposal in proposals)):
            curriculum = build_legal_ir_hard_negative_curriculum(
                verified_counterexamples=offered, config=config)
            assert curriculum.accepted_count == 0
            assert curriculum.examples == curriculum.stages == ()
            assert curriculum.rejected_count == len(proposals)
            assert curriculum.ready_for_training is False
    assert [proposal.to_dict() for proposal in proposals] == original
    assert report.trusted_negative_candidates == ()


def test_legacy_proposal_epochs_and_explicit_denials_cannot_be_laundered() -> None:
    from copy import deepcopy
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_hard_negatives import (
        LegalIRHardNegativeConfig, build_legal_ir_hard_negative_curriculum,
    )

    declared = _legacy_explicit_trusted_caller_control().to_dict()
    assert declared["schema_version"] == "legal-ir-fuzzing-trusted-negative-v1"
    assert declared["trusted"] is True and declared["verification"]["verified"] is True
    denied = []
    schema_only = deepcopy(declared)
    schema_only["schema_version"] = "legal-ir-fuzzing-unverified-proposal-v2"
    denied.append(schema_only)
    partition_only = deepcopy(declared)
    partition_only["training_partition"] = "unverified_proposal"
    denied.append(partition_only)
    for value in (False, 0, "false", None):
        top = deepcopy(declared)
        top["trusted"] = value
        denied.append(top)
        nested = deepcopy(declared)
        nested["verification"]["trusted"] = value
        denied.append(nested)
    original = deepcopy(denied)
    for required in (True, False):
        config = LegalIRHardNegativeConfig(require_verified_negatives=required,
            require_all_negative_families=False)
        control = build_legal_ir_hard_negative_curriculum(verified_counterexamples=(declared,), config=config)
        assert control.accepted_count == 1 and control.ready_for_training is True
        for payload in denied:
            assert payload["verification"]["verified"] is True
            assert payload["verification"]["verified_by"]
            curriculum = build_legal_ir_hard_negative_curriculum(
                verified_counterexamples=(payload,), config=config)
            assert curriculum.accepted_count == 0 and curriculum.rejected_count == 1
            assert curriculum.examples == curriculum.stages == ()
            assert curriculum.ready_for_training is False
    assert denied == original


def test_legacy_explicit_trusted_caller_forms_survive_and_shared_verifier_honors_denial() -> None:
    from copy import deepcopy
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_hard_negatives import (
        LegalIRHardNegativeConfig, build_legal_ir_hard_negative_curriculum,
    )

    declared = _legacy_explicit_trusted_caller_control()
    assert declared.trusted is True and declared.training_partition == "trusted_negative"
    assert declared.schema_version == "legal-ir-fuzzing-trusted-negative-v1"
    for required in (True, False):
        config = LegalIRHardNegativeConfig(require_verified_negatives=required,
            require_all_negative_families=False)
        for offered in (declared, declared.to_dict()):
            curriculum = build_legal_ir_hard_negative_curriculum(
                verified_counterexamples=(offered,), config=config)
            assert curriculum.accepted_count == 1 and curriculum.rejected_count == 0
            assert curriculum.examples[0].trusted is True
            assert curriculum.examples[0].is_training_label is True
            assert curriculum.ready_for_training is True
    reference = {"citation": "fixture:declared-source", "rules": [{"actor": "agency",
        "action": "provide", "exception": "emergency conditions exist", "modality": "obligation",
        "object": "notice"}], "temporal": "within 30 days"}
    claims = {
        "source_records": {"text": LEGAL_TEXT, "reference_ir": reference,
            "sample_id": "fixture:trusted-source-record", "semantic_family": "deontic"},
        "model_negatives": {"reference_ir": reference, "candidate_ir": declared.minimal_counterexample,
            "sample_id": "fixture:declared-model-label", "semantic_family": "deontic"},
    }
    config = LegalIRHardNegativeConfig(require_all_negative_families=False)
    for lane, content in claims.items():
        trusted = dict(content, trusted=True, verification=deepcopy(dict(declared.verification)))
        control = build_legal_ir_hard_negative_curriculum(**{lane: (trusted,)}, config=config)
        assert control.accepted_count > 0
        assert all(example.is_training_label for example in control.examples)
        for location in ("top", "nested"):
            payload = deepcopy(trusted)
            if location == "top":
                payload["trusted"] = False
            else:
                payload["verification"]["trusted"] = False
            curriculum = build_legal_ir_hard_negative_curriculum(**{lane: (payload,)}, config=config)
            assert curriculum.accepted_count == 0 and curriculum.rejected_count == 1
            assert curriculum.examples == curriculum.stages == ()
            assert curriculum.ready_for_training is False
