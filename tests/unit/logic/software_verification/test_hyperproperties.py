"""Contracts for hyperproperty and information-flow semantics (LFV-G030)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.software_verification.hyperproperties import (
    HYPERPROPERTY_IR_INTERFACE,
    AuthorityPromotionError,
    DeclassificationPolicy,
    EvidenceAuthorityCeiling,
    ExecutionTrace,
    HyperpropertyEvaluation,
    HyperpropertyEvidenceKind,
    HyperpropertyFormula,
    HyperpropertyIR,
    HyperpropertyKind,
    HyperpropertyValidationError,
    HyperpropertyVerdict,
    InformationFlowPolicy,
    ObservationDifference,
    ObservationKind,
    ObservationSpec,
    QuantifierBinding,
    RelationalAtom,
    RelationalCondition,
    RelationalOperator,
    RelationalRole,
    SecurityLabel,
    SecurityLevel,
    SelfCompositionBound,
    TraceQuantifier,
    TraceVariable,
    WitnessRole,
    WitnessTrace,
    WitnessTraceBundle,
    quantifier_order_is_canonical,
    refuse_universal_proof,
)


def _policy(
    *,
    with_declassification: bool = False,
    observations: tuple[str, ...] = ("status", "public_token"),
) -> InformationFlowPolicy:
    labels = (
        SecurityLabel("label:user", "user_id", SecurityLevel.LOW, ObservationKind.INPUT),
        SecurityLabel("label:secret", "secret", SecurityLevel.HIGH, ObservationKind.INPUT),
        SecurityLabel(
            "label:status", "status", SecurityLevel.LOW, ObservationKind.OUTPUT
        ),
        SecurityLabel(
            "label:token",
            "public_token",
            SecurityLevel.LOW,
            ObservationKind.OUTPUT,
        ),
    )
    observation_specs = tuple(
        ObservationSpec(
            f"obs:{field}",
            field,
            ObservationKind.OUTPUT,
            SecurityLevel.LOW,
        )
        for field in observations
    )
    declassifications: tuple[DeclassificationPolicy, ...] = ()
    high = ("secret",)
    if with_declassification:
        declassifications = (
            DeclassificationPolicy(
                "decl:release-token",
                high_field="secret",
                released_as="public_token",
                condition="owner_consented == true",
                description="Explicit owner-consent declassification",
            ),
        )
    return InformationFlowPolicy(
        policy_id="policy:ni-v1",
        low_input_fields=("user_id",),
        high_input_fields=high,
        observation_fields=observations,
        labels=labels,
        observations=observation_specs,
        declassifications=declassifications,
        subject_fields=("task_id",),
        description="Two-trace noninterference policy",
    )


def _bound(
    *,
    max_traces: int = 8,
    max_pairs: int = 16,
) -> SelfCompositionBound:
    return SelfCompositionBound(
        "bound:finite",
        max_traces=max_traces,
        max_pairs=max_pairs,
        max_steps=64,
        description="Finite self-composition envelope",
    )


def _document(
    *,
    with_declassification: bool = False,
    max_traces: int = 8,
    max_pairs: int = 16,
) -> HyperpropertyIR:
    return HyperpropertyIR.noninterference_document(
        policy=_policy(with_declassification=with_declassification),
        bound=_bound(max_traces=max_traces, max_pairs=max_pairs),
        metadata={"subject": "information-flow"},
    )


def _trace(
    trace_id: str,
    *,
    user_id: str = "alice",
    secret: str = "s1",
    status: str = "ok",
    public_token: str = "tok",
    task_id: str = "task:1",
) -> ExecutionTrace:
    return ExecutionTrace(
        trace_id=trace_id,
        public_inputs={"user_id": user_id},
        private_inputs={"secret": secret},
        observations={"status": status, "public_token": public_token},
        subject={"task_id": task_id},
    )


def test_interface_and_document_are_content_addressed_and_immutable() -> None:
    document = _document()
    payload = document.to_dict()
    round_trip = HyperpropertyIR.from_dict(payload)

    assert document.INTERFACE == HYPERPROPERTY_IR_INTERFACE
    assert payload["interface"] == "HyperpropertyIR@1"
    assert document.document_id.startswith("b")
    assert round_trip == document
    assert round_trip.document_id == document.document_id
    assert document.trace_cardinality == 2
    assert document.quantifier_signature == ("forall", "forall")
    with pytest.raises(FrozenInstanceError):
        document.document_id = "changed"  # type: ignore[misc]
    with pytest.raises(HyperpropertyValidationError, match="does not match"):
        replace(document, document_id="bafkbad")


def test_trace_cardinality_and_quantifier_order_are_canonical() -> None:
    document = _document()
    formula = document.formula
    assert formula.trace_cardinality == 2
    assert formula.quantifier_signature == ("forall", "forall")
    assert quantifier_order_is_canonical(
        formula.quantifier_prefix,
        formula.quantifier_prefix,
    )

    reversed_prefix = (
        QuantifierBinding("bind:0", TraceQuantifier.FORALL, "var:pi2", 0),
        QuantifierBinding("bind:1", TraceQuantifier.FORALL, "var:pi1", 1),
    )
    reordered = HyperpropertyFormula(
        formula_id="formula:reordered",
        kind=HyperpropertyKind.NONINTERFERENCE,
        variables=(
            TraceVariable("var:pi2", "pi2"),
            TraceVariable("var:pi1", "pi1"),
        ),
        quantifier_prefix=reversed_prefix,
        matrix_statement="forall pi2, pi1. equal_low -> equal_obs",
        information_flow_policy_id="policy:ni-v1",
        preconditions=formula.preconditions,
        postconditions=formula.postconditions,
    )
    assert not quantifier_order_is_canonical(
        formula.quantifier_prefix,
        reordered.quantifier_prefix,
    )
    assert formula.semantic_dict() != reordered.semantic_dict()

    with pytest.raises(HyperpropertyValidationError, match="contiguous from zero"):
        HyperpropertyFormula(
            formula_id="formula:bad-index",
            kind=HyperpropertyKind.GENERAL,
            variables=(TraceVariable("var:pi1", "pi1"),),
            quantifier_prefix=(
                QuantifierBinding("bind:x", TraceQuantifier.EXISTS, "var:pi1", 2),
            ),
            matrix_statement="exists pi1. true",
        )


def test_quantifier_alternation_is_order_sensitive() -> None:
    forall_exists = HyperpropertyFormula(
        formula_id="formula:ae",
        kind=HyperpropertyKind.GENERAL,
        variables=(
            TraceVariable("var:pi1", "pi1"),
            TraceVariable("var:pi2", "pi2"),
        ),
        quantifier_prefix=(
            QuantifierBinding("bind:0", TraceQuantifier.FORALL, "var:pi1", 0),
            QuantifierBinding("bind:1", TraceQuantifier.EXISTS, "var:pi2", 1),
        ),
        matrix_statement="forall pi1. exists pi2. related(pi1, pi2)",
    )
    exists_forall = HyperpropertyFormula(
        formula_id="formula:ea",
        kind=HyperpropertyKind.GENERAL,
        variables=(
            TraceVariable("var:pi1", "pi1"),
            TraceVariable("var:pi2", "pi2"),
        ),
        quantifier_prefix=(
            QuantifierBinding("bind:0", TraceQuantifier.EXISTS, "var:pi1", 0),
            QuantifierBinding("bind:1", TraceQuantifier.FORALL, "var:pi2", 1),
        ),
        matrix_statement="exists pi1. forall pi2. related(pi1, pi2)",
    )
    assert forall_exists.quantifier_signature == ("forall", "exists")
    assert exists_forall.quantifier_signature == ("exists", "forall")
    assert forall_exists.semantic_dict() != exists_forall.semantic_dict()


def test_observations_and_declassification_are_explicit() -> None:
    policy = _policy(with_declassification=True)
    assert policy.observation_fields == ("status", "public_token")
    assert len(policy.observations) == 2
    assert policy.declassifications[0].high_field == "secret"
    assert policy.declassifications[0].released_as == "public_token"

    with pytest.raises(HyperpropertyValidationError, match="must not be empty"):
        InformationFlowPolicy(
            "policy:empty-obs",
            low_input_fields=("user_id",),
            high_input_fields=("secret",),
            observation_fields=(),
        )
    with pytest.raises(HyperpropertyValidationError, match="disjoint"):
        InformationFlowPolicy(
            "policy:overlap",
            low_input_fields=("secret",),
            high_input_fields=("secret",),
            observation_fields=("status",),
        )
    with pytest.raises(HyperpropertyValidationError, match="without declassification"):
        InformationFlowPolicy(
            "policy:high-obs",
            low_input_fields=("user_id",),
            high_input_fields=("secret",),
            observation_fields=("secret",),
        )
    with pytest.raises(HyperpropertyValidationError, match="rename or reclassify"):
        DeclassificationPolicy(
            "decl:bad",
            high_field="secret",
            released_as="secret",
            condition="true",
        )
    with pytest.raises(HyperpropertyValidationError, match="high_input_fields"):
        InformationFlowPolicy(
            "policy:bad-decl",
            low_input_fields=("user_id",),
            high_input_fields=("secret",),
            observation_fields=("status",),
            declassifications=(
                DeclassificationPolicy(
                    "decl:x",
                    high_field="other",
                    released_as="status",
                    condition="true",
                ),
            ),
        )


def test_relational_pre_and_postconditions_bind_trace_variables() -> None:
    formula = HyperpropertyFormula.noninterference(policy_id="policy:ni-v1")
    assert formula.preconditions[0].role is RelationalRole.PRECONDITION
    assert formula.postconditions[0].role is RelationalRole.POSTCONDITION
    assert formula.preconditions[0].atoms[0].operator is RelationalOperator.EQUAL
    assert formula.preconditions[0].referenced_variable_ids() == (
        "var:pi1",
        "var:pi2",
    )

    with pytest.raises(HyperpropertyValidationError, match="exactly two"):
        RelationalAtom(
            "atom:bad",
            RelationalOperator.EQUAL,
            "field",
            ("var:pi1",),
        )
    with pytest.raises(HyperpropertyValidationError, match="unknown variables"):
        HyperpropertyFormula(
            formula_id="formula:bad-rel",
            kind=HyperpropertyKind.RELATIONAL,
            variables=(TraceVariable("var:pi1", "pi1"),),
            quantifier_prefix=(
                QuantifierBinding("bind:0", TraceQuantifier.FORALL, "var:pi1", 0),
            ),
            matrix_statement="true",
            preconditions=(
                RelationalCondition(
                    "cond:bad",
                    RelationalRole.PRECONDITION,
                    (
                        RelationalAtom(
                            "atom:x",
                            RelationalOperator.PREDICATE,
                            "x",
                            ("var:missing",),
                            predicate="P(x)",
                        ),
                    ),
                ),
            ),
        )


def test_self_composition_requires_positive_finite_bounds() -> None:
    with pytest.raises(HyperpropertyValidationError, match="positive integer"):
        SelfCompositionBound("bound:zero", max_traces=0)
    with pytest.raises(HyperpropertyValidationError, match="positive integer"):
        SelfCompositionBound("bound:pairs", max_traces=1, max_pairs=0)

    bound = _bound(max_traces=2, max_pairs=1)
    assert bound.max_traces == 2
    assert bound.max_pairs == 1
    assert bound.max_steps == 64
    assert SelfCompositionBound.from_dict(bound.to_dict()) == bound


def test_bounded_self_composition_detects_noninterference_violation() -> None:
    document = _document()
    left = _trace("trace:a", secret="high-a", status="ok", public_token="same")
    right = _trace("trace:b", secret="high-b", status="leaked", public_token="same")

    result = document.evaluate_bounded_noninterference((left, right))

    assert result.verdict is HyperpropertyVerdict.VIOLATED
    assert result.evidence_kind is HyperpropertyEvidenceKind.BOUNDED_SELF_COMPOSITION
    assert result.authority_ceiling is EvidenceAuthorityCeiling.BOUNDED
    assert result.bounded is True
    assert result.authorizes_universal_proof is False
    assert result.witness_bundle is not None
    assert result.witness_bundle.role is WitnessRole.COUNTEREXAMPLE
    assert result.witness_bundle.authorizes_universal_proof is False
    assert result.witness_bundle.differences[0].field == "status"
    assert "private" not in result.to_dict()["witness_bundle"]["traces"][0]
    assert "secret" not in result.to_dict()["witness_bundle"]["traces"][0]["public_inputs"]


def test_clean_sample_holds_but_never_authorizes_universal_proof() -> None:
    document = _document()
    traces = (
        _trace("trace:a", secret="high-a", status="ok", public_token="tok"),
        _trace("trace:b", secret="high-b", status="ok", public_token="tok"),
    )
    result = document.evaluate_bounded_noninterference(traces)

    assert result.verdict is HyperpropertyVerdict.HOLDS
    assert result.evidence_kind is HyperpropertyEvidenceKind.CLEAN_SAMPLE
    assert result.holds is True
    assert result.authorizes_universal_proof is False
    assert result.authority_ceiling is EvidenceAuthorityCeiling.BOUNDED
    assert result.witness_bundle is not None
    assert result.witness_bundle.role is WitnessRole.SUPPORTING_SAMPLE
    assert result.witness_bundle.authorizes_universal_proof is False
    refuse_universal_proof(result)

    with pytest.raises(AuthorityPromotionError, match="universal proof"):
        HyperpropertyEvaluation(
            verdict=HyperpropertyVerdict.HOLDS,
            evidence_kind=HyperpropertyEvidenceKind.CLEAN_SAMPLE,
            authority_ceiling=EvidenceAuthorityCeiling.BOUNDED,
            formula_id=document.formula.formula_id,
            policy_id=document.information_flow_policy.policy_id,
            reason="promoted",
            authorizes_universal_proof=True,
            explored_traces=2,
            explored_pairs=1,
            maximum_pairs=16,
        )
    with pytest.raises(AuthorityPromotionError, match="authoritative"):
        HyperpropertyEvaluation(
            verdict=HyperpropertyVerdict.HOLDS,
            evidence_kind=HyperpropertyEvidenceKind.BOUNDED_SELF_COMPOSITION,
            authority_ceiling=EvidenceAuthorityCeiling.AUTHORITATIVE,
            formula_id=document.formula.formula_id,
            policy_id=document.information_flow_policy.policy_id,
            reason="promoted ceiling",
            explored_traces=2,
            explored_pairs=1,
            maximum_pairs=16,
        )


def test_bound_hit_and_missing_high_variation_are_inconclusive() -> None:
    document = _document(max_traces=1, max_pairs=1)
    many = tuple(
        _trace(f"trace:{index}", secret=f"s{index}", status="ok")
        for index in range(4)
    )
    bound_result = document.evaluate_bounded_noninterference(many)
    assert bound_result.verdict is HyperpropertyVerdict.INCONCLUSIVE
    assert bound_result.bound_hit or bound_result.explored_traces == 1
    assert bound_result.authorizes_universal_proof is False
    with pytest.raises(HyperpropertyValidationError, match="no boolean"):
        _ = bound_result.holds

    same_high = (
        _trace("trace:a", secret="same", status="ok"),
        _trace("trace:b", secret="same", status="ok"),
    )
    no_stress = _document().evaluate_bounded_noninterference(same_high)
    assert no_stress.verdict is HyperpropertyVerdict.INCONCLUSIVE
    assert "private/high" in no_stress.reason


def test_witness_bundle_rejects_unredacted_or_universal_claims() -> None:
    left = WitnessTrace.from_execution(
        trace_id="trace:a",
        variable_id="var:pi1",
        public_inputs={"user_id": "alice"},
        observations={"status": "ok"},
        private_inputs={"secret": "must-not-serialize"},
    )
    right = WitnessTrace.from_execution(
        trace_id="trace:b",
        variable_id="var:pi2",
        public_inputs={"user_id": "alice"},
        observations={"status": "bad"},
    )
    assert "secret" not in left.to_dict()["public_inputs"]
    assert left.public_ref.startswith("b")

    bundle = WitnessTraceBundle(
        bundle_id="bundle:1",
        role=WitnessRole.VIOLATION,
        formula_id="formula:noninterference",
        traces=(left, right),
        differences=(
            ObservationDifference(
                "status",
                left.observations_digest,
                right.observations_digest,
            ),
        ),
        observed_fields=("status",),
    )
    assert bundle.authorizes_universal_proof is False
    assert bundle.authority_ceiling is EvidenceAuthorityCeiling.BOUNDED
    assert WitnessTraceBundle.from_dict(bundle.to_dict()) == bundle

    with pytest.raises(HyperpropertyValidationError, match="must be redacted"):
        WitnessTraceBundle(
            bundle_id="bundle:open",
            role=WitnessRole.SUPPORTING_SAMPLE,
            formula_id="formula:noninterference",
            traces=(left,),
            redacted=False,
        )
    with pytest.raises(AuthorityPromotionError, match="authorizes_universal_proof"):
        payload = bundle.to_dict()
        payload["authorizes_universal_proof"] = True
        WitnessTraceBundle.from_dict(payload)
    with pytest.raises(HyperpropertyValidationError, match="observation differences"):
        WitnessTraceBundle(
            bundle_id="bundle:empty-diff",
            role=WitnessRole.COUNTEREXAMPLE,
            formula_id="formula:noninterference",
            traces=(left, right),
        )


def test_low_input_mismatch_and_subject_mismatch_skip_pairs() -> None:
    document = _document()
    different_low = (
        _trace("trace:a", user_id="alice", secret="s1", status="ok"),
        _trace("trace:b", user_id="bob", secret="s2", status="ok"),
    )
    result = document.evaluate_bounded_noninterference(different_low)
    assert result.verdict is HyperpropertyVerdict.INCONCLUSIVE

    different_subject = (
        _trace("trace:a", secret="s1", task_id="task:1"),
        _trace("trace:b", secret="s2", task_id="task:2"),
    )
    result2 = document.evaluate_bounded_noninterference(different_subject)
    assert result2.verdict is HyperpropertyVerdict.INCONCLUSIVE


def test_noninterference_formula_rejects_wrong_cardinality_or_exists() -> None:
    with pytest.raises(HyperpropertyValidationError, match="exactly two"):
        HyperpropertyFormula(
            formula_id="formula:one",
            kind=HyperpropertyKind.NONINTERFERENCE,
            variables=(TraceVariable("var:pi1", "pi1"),),
            quantifier_prefix=(
                QuantifierBinding("bind:0", TraceQuantifier.FORALL, "var:pi1", 0),
            ),
            matrix_statement="true",
            information_flow_policy_id="policy:ni-v1",
        )
    with pytest.raises(HyperpropertyValidationError, match="universal two-trace"):
        HyperpropertyFormula(
            formula_id="formula:exists",
            kind=HyperpropertyKind.NONINTERFERENCE,
            variables=(
                TraceVariable("var:pi1", "pi1"),
                TraceVariable("var:pi2", "pi2"),
            ),
            quantifier_prefix=(
                QuantifierBinding("bind:0", TraceQuantifier.FORALL, "var:pi1", 0),
                QuantifierBinding("bind:1", TraceQuantifier.EXISTS, "var:pi2", 1),
            ),
            matrix_statement="true",
            information_flow_policy_id="policy:ni-v1",
        )
    with pytest.raises(HyperpropertyValidationError, match="information_flow_policy_id"):
        HyperpropertyFormula(
            formula_id="formula:no-policy",
            kind=HyperpropertyKind.NONINTERFERENCE,
            variables=(
                TraceVariable("var:pi1", "pi1"),
                TraceVariable("var:pi2", "pi2"),
            ),
            quantifier_prefix=(
                QuantifierBinding("bind:0", TraceQuantifier.FORALL, "var:pi1", 0),
                QuantifierBinding("bind:1", TraceQuantifier.FORALL, "var:pi2", 1),
            ),
            matrix_statement="true",
        )


def test_document_policy_mismatch_and_unknown_fields_fail_closed() -> None:
    formula = HyperpropertyFormula.noninterference(policy_id="policy:other")
    with pytest.raises(HyperpropertyValidationError, match="does not match embedded"):
        HyperpropertyIR(
            formula=formula,
            information_flow_policy=_policy(),
            self_composition_bound=_bound(),
        )

    document = _document()
    malformed = document.to_dict()
    malformed["unexpected"] = True
    with pytest.raises(HyperpropertyValidationError, match="unknown"):
        HyperpropertyIR.from_dict(malformed)

    formula_payload = document.formula.to_dict()
    formula_payload["trace_cardinality"] = 99
    with pytest.raises(HyperpropertyValidationError, match="trace_cardinality"):
        HyperpropertyFormula.from_dict(formula_payload)


def test_execution_trace_redacts_private_inputs_in_public_projection() -> None:
    trace = _trace("trace:x", secret="top-secret")
    public = trace.to_public_dict()
    assert public["private_inputs_redacted"] is True
    assert "private_inputs" not in public
    assert "top-secret" not in str(public)
    witness = trace.to_witness("var:pi1", observation_fields=("status",))
    assert set(witness.observations) == {"status"}
    assert WitnessTrace.from_dict(witness.to_dict()) == witness


def test_security_labels_and_observation_specs_round_trip() -> None:
    label = SecurityLabel(
        "label:x",
        "user_id",
        SecurityLevel.LOW,
        ObservationKind.INPUT,
        description="public identity",
    )
    observation = ObservationSpec(
        "obs:status",
        "status",
        ObservationKind.OUTPUT,
        SecurityLevel.LOW,
    )
    assert SecurityLabel.from_dict(label.to_dict()) == label
    assert ObservationSpec.from_dict(observation.to_dict()) == observation
    with pytest.raises(HyperpropertyValidationError, match="trimmed string|stable field path"):
        SecurityLabel("label:bad", " not-a-field ", SecurityLevel.LOW)
    with pytest.raises(HyperpropertyValidationError, match="stable field path"):
        SecurityLabel("label:bad2", "bad field!", SecurityLevel.LOW)


def test_evaluation_round_trip_and_refuse_promotion_helper() -> None:
    document = _document()
    result = document.evaluate_bounded_noninterference(
        (
            _trace("trace:a", secret="a", status="ok"),
            _trace("trace:b", secret="b", status="ok"),
        )
    )
    restored = HyperpropertyEvaluation.from_dict(result.to_dict())
    assert restored.verdict is result.verdict
    assert restored.authorizes_universal_proof is False
    refuse_universal_proof(restored)

    promoted = result.to_dict()
    promoted["authorizes_universal_proof"] = True
    with pytest.raises(AuthorityPromotionError):
        HyperpropertyEvaluation.from_dict(promoted)
