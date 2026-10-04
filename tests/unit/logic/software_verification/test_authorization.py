"""Contracts for authorization, Datalog, and SecPAL-style semantics (LFV-G028)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.software_verification.authorization import (
    AUTHORIZATION_IR_INTERFACE,
    MAX_DELEGATION_DEPTH,
    AtomPolarity,
    AuthorizationAtom,
    AuthorizationConstraint,
    AuthorizationEvidenceAuthority,
    AuthorizationFact,
    AuthorizationIR,
    AuthorizationPrincipal,
    AuthorizationRole,
    AuthorizationRule,
    AuthorizationTerm,
    AuthorizationValidationError,
    ConflictResolution,
    ConstraintKind,
    DecisionExplanation,
    DecisionOutcome,
    DecisionQuery,
    DelegationStatement,
    EffectKind,
    ExplanationStep,
    ExplanationStepKind,
    GeneratedCodeCorrectness,
    PolicyBounds,
    PolicyDecision,
    PrecedencePolicy,
    PredicateSignature,
    PrincipalKind,
    RuleKind,
    SpeaksForRelation,
    TermKind,
    authority_is_authorization_only,
    distinct_decision_outcomes,
)

SOURCE_ID = "source:policy"
SPAN_ID = "span:policy"


def _source() -> SourceRef:
    return SourceRef(
        ref_id=SOURCE_ID,
        source_uri="file:///policies/document-access.policy.json",
        source_id="document-access.policy.json",
        source_revision="git:0123456789abcdef",
        content_sha256="a" * 64,
    )


def _span() -> SourceSpan:
    return SourceSpan(
        span_id=SPAN_ID,
        source_ref_id=SOURCE_ID,
        start_byte=0,
        end_byte=2048,
        start_line=1,
        start_column=1,
        end_line=80,
        end_column=2,
    )


def _mapped() -> dict[str, tuple[str, ...]]:
    return {"source_ref_ids": (SOURCE_ID,), "span_ids": (SPAN_ID,)}


def _const(value: str, sort: str = "principal") -> AuthorizationTerm:
    return AuthorizationTerm.constant(value, sort)


def _var(value: str, sort: str = "principal") -> AuthorizationTerm:
    return AuthorizationTerm.variable(value, sort)


def _atom(
    predicate_id: str,
    *args: AuthorizationTerm,
    polarity: AtomPolarity = AtomPolarity.POSITIVE,
) -> AuthorizationAtom:
    return AuthorizationAtom(predicate_id, args, polarity)


def _document(
    *,
    observations: dict[str, object] | None = None,
    bounds: PolicyBounds | None = None,
    precedence: PrecedencePolicy | None = None,
) -> AuthorizationIR:
    principals = (
        AuthorizationPrincipal(
            "principal:root",
            "PolicyRoot",
            PrincipalKind.SYSTEM,
            **_mapped(),
        ),
        AuthorizationPrincipal(
            "principal:alice",
            "Alice",
            PrincipalKind.USER,
            **_mapped(),
        ),
        AuthorizationPrincipal(
            "principal:bob",
            "Bob",
            PrincipalKind.USER,
            **_mapped(),
        ),
        AuthorizationPrincipal(
            "principal:service",
            "DocService",
            PrincipalKind.SERVICE,
            **_mapped(),
        ),
    )
    roles = (
        AuthorizationRole(
            "role:admin",
            "Administrator",
            member_principal_ids=("principal:alice",),
            **_mapped(),
        ),
        AuthorizationRole(
            "role:reader",
            "Reader",
            member_principal_ids=("principal:bob",),
            **_mapped(),
        ),
    )
    predicates = (
        PredicateSignature(
            "pred:role",
            "role",
            2,
            ("principal", "role"),
            is_intensional=False,
            **_mapped(),
        ),
        PredicateSignature(
            "pred:may",
            "may",
            3,
            ("principal", "action", "resource"),
            is_intensional=True,
            **_mapped(),
        ),
        PredicateSignature(
            "pred:denied",
            "denied",
            3,
            ("principal", "action", "resource"),
            is_intensional=True,
            **_mapped(),
        ),
        PredicateSignature(
            "pred:sensitive",
            "sensitive",
            1,
            ("resource",),
            is_intensional=False,
            **_mapped(),
        ),
    )
    facts = (
        AuthorizationFact(
            "fact:alice-admin",
            _atom(
                "pred:role",
                _const("principal:alice"),
                _const("role:admin", "role"),
            ),
            issuer_principal_id="principal:root",
            **_mapped(),
        ),
        AuthorizationFact(
            "fact:bob-reader",
            _atom(
                "pred:role",
                _const("principal:bob"),
                _const("role:reader", "role"),
            ),
            issuer_principal_id="principal:root",
            **_mapped(),
        ),
        AuthorizationFact(
            "fact:doc-sensitive",
            _atom("pred:sensitive", _const("resource:payroll", "resource")),
            issuer_principal_id="principal:root",
            **_mapped(),
        ),
    )
    constraints = (
        AuthorizationConstraint(
            "constraint:path-scope",
            ConstraintKind.SCOPE,
            expression={"path_prefix": "docs/"},
            statement="Resource paths must remain under docs/.",
            **_mapped(),
        ),
        AuthorizationConstraint(
            "constraint:active-window",
            ConstraintKind.TEMPORAL_WINDOW,
            expression={"not_before": 0, "not_after": 9_999_999_999},
            statement="Grants are only valid inside the declared window.",
            **_mapped(),
        ),
    )
    rules = (
        AuthorizationRule(
            "rule:admin-may-read",
            head=_atom(
                "pred:may",
                _var("P"),
                _const("read", "action"),
                _var("R", "resource"),
            ),
            body=(
                _atom(
                    "pred:role",
                    _var("P"),
                    _const("role:admin", "role"),
                ),
            ),
            kind=RuleKind.DATALOG,
            effect=EffectKind.ALLOW,
            stratum=1,
            constraint_ids=("constraint:path-scope",),
            **_mapped(),
        ),
        AuthorizationRule(
            "rule:deny-sensitive-non-admin",
            head=_atom(
                "pred:denied",
                _var("P"),
                _const("read", "action"),
                _var("R", "resource"),
            ),
            body=(
                _atom("pred:sensitive", _var("R", "resource")),
                _atom(
                    "pred:role",
                    _var("P"),
                    _const("role:admin", "role"),
                    polarity=AtomPolarity.NEGATIVE,
                ),
            ),
            kind=RuleKind.DATALOG,
            effect=EffectKind.DENY,
            stratum=1,
            **_mapped(),
        ),
        AuthorizationRule(
            "rule:root-says-service-may",
            head=_atom(
                "pred:may",
                _const("principal:service"),
                _const("read", "action"),
                _const("resource:payroll", "resource"),
            ),
            body=(),
            kind=RuleKind.SECPAL_SAYS,
            effect=EffectKind.ALLOW,
            stratum=0,
            issuer_principal_id="principal:root",
            constraint_ids=("constraint:active-window",),
            **_mapped(),
        ),
    )
    speaks_for = (
        SpeaksForRelation(
            "speaks-for:service-alice",
            speaker_principal_id="principal:service",
            subject_principal_id="principal:alice",
            max_composition_depth=2,
            **_mapped(),
        ),
    )
    delegations = (
        DelegationStatement(
            "delegation:root-alice",
            issuer_principal_id="principal:root",
            subject_principal_id="principal:alice",
            capability="read",
            delegation_depth=2,
            resource_scope=("docs/",),
            constraint_ids=("constraint:path-scope",),
            **_mapped(),
        ),
        DelegationStatement(
            "delegation:alice-bob",
            issuer_principal_id="principal:alice",
            subject_principal_id="principal:bob",
            capability="read",
            delegation_depth=1,
            parent_delegation_id="delegation:root-alice",
            resource_scope=("docs/public/",),
            **_mapped(),
        ),
    )
    queries = (
        DecisionQuery(
            "query:alice-read-payroll",
            principal_id="principal:alice",
            action="read",
            resource="resource:payroll",
            goal_atom=_atom(
                "pred:may",
                _const("principal:alice"),
                _const("read", "action"),
                _const("resource:payroll", "resource"),
            ),
            constraint_ids=("constraint:path-scope",),
            **_mapped(),
        ),
        DecisionQuery(
            "query:bob-read-payroll",
            principal_id="principal:bob",
            action="read",
            resource="resource:payroll",
            **_mapped(),
        ),
        DecisionQuery(
            "query:unknown-action",
            principal_id="principal:bob",
            action="delete",
            resource="resource:payroll",
            **_mapped(),
        ),
        DecisionQuery(
            "query:conflict-case",
            principal_id="principal:bob",
            action="read",
            resource="resource:payroll",
            context={"fixture": "allow-and-deny"},
            **_mapped(),
        ),
    )
    explanations = (
        DecisionExplanation(
            "explanation:alice-allow",
            query_id="query:alice-read-payroll",
            outcome=DecisionOutcome.ALLOW,
            steps=(
                ExplanationStep(
                    "step:trust",
                    ExplanationStepKind.TRUST_ROOT,
                    "principal:root",
                    "Root is a declared trust root.",
                ),
                ExplanationStep(
                    "step:fact",
                    ExplanationStepKind.FACT,
                    "fact:alice-admin",
                    "Alice holds the admin role.",
                ),
                ExplanationStep(
                    "step:rule",
                    ExplanationStepKind.RULE,
                    "rule:admin-may-read",
                    "Admins may read scoped resources.",
                ),
                ExplanationStep(
                    "step:precedence",
                    ExplanationStepKind.PRECEDENCE,
                    "explicit_conflict",
                    "No opposing deny evidence under explicit conflict policy.",
                ),
            ),
            **_mapped(),
        ),
        DecisionExplanation(
            "explanation:bob-deny",
            query_id="query:bob-read-payroll",
            outcome=DecisionOutcome.DENY,
            steps=(
                ExplanationStep(
                    "step:deny-rule",
                    ExplanationStepKind.RULE,
                    "rule:deny-sensitive-non-admin",
                    "Non-admins are denied sensitive resources.",
                ),
            ),
            **_mapped(),
        ),
        DecisionExplanation(
            "explanation:unknown",
            query_id="query:unknown-action",
            outcome=DecisionOutcome.UNKNOWN,
            steps=(
                ExplanationStep(
                    "step:bound",
                    ExplanationStepKind.BOUND,
                    "bounds",
                    "No applicable allow or deny evidence within bounds.",
                ),
            ),
        ),
        DecisionExplanation(
            "explanation:conflict",
            query_id="query:conflict-case",
            outcome=DecisionOutcome.CONFLICT,
            steps=(
                ExplanationStep(
                    "step:allow-rule",
                    ExplanationStepKind.RULE,
                    "rule:admin-may-read",
                ),
                ExplanationStep(
                    "step:deny-rule-2",
                    ExplanationStepKind.RULE,
                    "rule:deny-sensitive-non-admin",
                ),
                ExplanationStep(
                    "step:conflict-precedence",
                    ExplanationStepKind.PRECEDENCE,
                    "precedence",
                    "Explicit conflict resolution retains conflict.",
                ),
            ),
        ),
    )
    decisions = (
        PolicyDecision(
            "decision:alice-allow",
            query_id="query:alice-read-payroll",
            outcome=DecisionOutcome.ALLOW,
            explanation_id="explanation:alice-allow",
            **_mapped(),
        ),
        PolicyDecision(
            "decision:bob-deny",
            query_id="query:bob-read-payroll",
            outcome=DecisionOutcome.DENY,
            explanation_id="explanation:bob-deny",
            **_mapped(),
        ),
        PolicyDecision(
            "decision:unknown",
            query_id="query:unknown-action",
            outcome=DecisionOutcome.UNKNOWN,
            explanation_id="explanation:unknown",
        ),
        PolicyDecision(
            "decision:conflict",
            query_id="query:conflict-case",
            outcome=DecisionOutcome.CONFLICT,
            explanation_id="explanation:conflict",
        ),
    )
    return AuthorizationIR(
        sources=(_source(),),
        spans=(_span(),),
        principals=principals,
        trust_root_principal_ids=("principal:root",),
        roles=roles,
        predicates=predicates,
        facts=facts,
        rules=rules,
        constraints=constraints,
        speaks_for=speaks_for,
        delegations=delegations,
        bounds=bounds
        or PolicyBounds(
            max_delegation_depth=4,
            max_derivation_depth=32,
            max_stratum=8,
            universe_size=64,
        ),
        precedence=precedence
        or PrecedencePolicy(ConflictResolution.EXPLICIT_CONFLICT),
        queries=queries,
        explanations=explanations,
        decisions=decisions,
        metadata={"policy": "document-access", "version": 1},
        observations=observations or {},
    )


def test_interface_and_complete_semantic_vocabulary() -> None:
    document = _document()

    assert document.interface == AUTHORIZATION_IR_INTERFACE
    assert document.interface == "AuthorizationIR@1"
    assert document.principals
    assert document.roles
    assert document.predicates
    assert document.facts
    assert document.rules
    assert document.constraints
    assert document.speaks_for
    assert document.delegations
    assert document.queries
    assert document.explanations
    assert document.decisions
    assert document.trust_root_principal_ids == ("principal:root",)
    assert document.bounds.max_delegation_depth == 4
    assert {rule.kind for rule in document.rules} >= {
        RuleKind.DATALOG,
        RuleKind.SECPAL_SAYS,
    }
    assert {rule.effect for rule in document.rules} >= {
        EffectKind.ALLOW,
        EffectKind.DENY,
    }
    assert {decision.outcome for decision in document.decisions} == set(
        DecisionOutcome
    )
    assert distinct_decision_outcomes() == {
        "allow",
        "deny",
        "conflict",
        "unknown",
    }


def test_model_is_deeply_immutable_and_round_trips_losslessly() -> None:
    document = _document()
    encoded = document.to_json()
    restored = AuthorizationIR.from_json(encoded)

    assert restored == document
    assert restored.document_id == document.document_id
    assert restored.to_dict() == document.to_dict()
    assert restored.semantic_bytes() == document.semantic_bytes()
    with pytest.raises(TypeError):
        document.metadata["new"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        document.principals[0].name = "Changed"  # type: ignore[misc]


def test_identity_is_order_independent_and_excludes_observations() -> None:
    first = _document(
        observations={
            "started_at": "2026-07-29T00:00:00Z",
            "duration_ms": 4,
            "host": "runner-a",
        }
    )
    second = replace(
        _document(
            observations={
                "started_at": "2030-01-01T00:00:00Z",
                "duration_ms": 900,
                "host": "runner-b",
            }
        ),
        principals=tuple(reversed(first.principals)),
        rules=tuple(reversed(first.rules)),
        facts=tuple(reversed(first.facts)),
        decisions=tuple(reversed(first.decisions)),
    )

    assert first.document_id == second.document_id
    assert first.semantic_dict() == second.semantic_dict()
    assert first.to_dict()["observations"] != second.to_dict()["observations"]
    assert "runner-a" not in first.semantic_bytes().decode()


def test_decision_outcomes_are_distinct_and_precedence_maps_them() -> None:
    deny_overrides = PrecedencePolicy(ConflictResolution.DENY_OVERRIDES)
    allow_overrides = PrecedencePolicy(ConflictResolution.ALLOW_OVERRIDES)
    explicit = PrecedencePolicy(ConflictResolution.EXPLICIT_CONFLICT)
    first_applicable = PrecedencePolicy(ConflictResolution.FIRST_APPLICABLE)

    assert deny_overrides.resolve(False, False) is DecisionOutcome.UNKNOWN
    assert deny_overrides.resolve(True, False) is DecisionOutcome.ALLOW
    assert deny_overrides.resolve(False, True) is DecisionOutcome.DENY
    assert deny_overrides.resolve(True, True) is DecisionOutcome.DENY
    assert allow_overrides.resolve(True, True) is DecisionOutcome.ALLOW
    assert explicit.resolve(True, True) is DecisionOutcome.CONFLICT
    assert (
        first_applicable.resolve(True, True, first_effect=EffectKind.ALLOW)
        is DecisionOutcome.ALLOW
    )
    assert (
        first_applicable.resolve(True, True, first_effect=EffectKind.DENY)
        is DecisionOutcome.DENY
    )
    assert len({outcome.value for outcome in DecisionOutcome}) == 4


def test_stratification_rejects_negative_cycles_at_same_or_higher_stratum() -> None:
    document = _document()
    bad = document.to_dict()
    bad["document_id"] = ""
    # Head of deny rule is denied at stratum 1; make a same-stratum negative
    # dependence on an intensional predicate also defined at stratum 1.
    bad["rules"].append(
        AuthorizationRule(
            "rule:unstratified",
            head=_atom(
                "pred:may",
                _var("P"),
                _const("write", "action"),
                _var("R", "resource"),
            ),
            body=(
                _atom(
                    "pred:denied",
                    _var("P"),
                    _const("write", "action"),
                    _var("R", "resource"),
                    polarity=AtomPolarity.NEGATIVE,
                ),
            ),
            stratum=1,
            effect=EffectKind.ALLOW,
            **_mapped(),
        ).to_dict()
    )
    with pytest.raises(AuthorizationValidationError, match="not stratified"):
        AuthorizationIR.from_dict(bad)


def test_stratified_negation_against_lower_stratum_is_accepted() -> None:
    document = _document()
    payload = document.to_dict()
    payload["document_id"] = ""
    # Move the deny rule that defines pred:denied to stratum 0 so a stratum-1
    # negative reference remains stratified.
    for rule in payload["rules"]:
        if rule["rule_id"] == "rule:deny-sensitive-non-admin":
            rule["stratum"] = 0
            # The body still negates pred:role which is EDB-only (facts).
            break
    restored = AuthorizationIR.from_dict(payload)
    assert any(
        rule.rule_id == "rule:deny-sensitive-non-admin" and rule.stratum == 0
        for rule in restored.rules
    )


def test_delegation_depth_and_trust_roots_are_bounded() -> None:
    with pytest.raises(AuthorizationValidationError, match="exceeds"):
        DelegationStatement(
            "delegation:too-deep",
            issuer_principal_id="principal:root",
            subject_principal_id="principal:alice",
            capability="read",
            delegation_depth=MAX_DELEGATION_DEPTH + 1,
            **_mapped(),
        )
    with pytest.raises(AuthorizationValidationError, match="hard ceiling"):
        PolicyBounds(max_delegation_depth=MAX_DELEGATION_DEPTH + 1)
    with pytest.raises(AuthorizationValidationError, match="must not be empty"):
        replace(_document(), trust_root_principal_ids=(), document_id="")

    payload = _document().to_dict()
    payload["document_id"] = ""
    payload["bounds"] = PolicyBounds(max_delegation_depth=2).to_dict()
    # Child depth is not strictly less than its parent depth.
    for item in payload["delegations"]:
        if item["delegation_id"] == "delegation:root-alice":
            item["delegation_depth"] = 2
        if item["delegation_id"] == "delegation:alice-bob":
            item["delegation_depth"] = 2
    with pytest.raises(AuthorizationValidationError, match="strictly smaller"):
        AuthorizationIR.from_dict(payload)

    too_deep = _document().to_dict()
    too_deep["document_id"] = ""
    too_deep["bounds"] = PolicyBounds(max_delegation_depth=1).to_dict()
    with pytest.raises(AuthorizationValidationError, match="exceeds"):
        AuthorizationIR.from_dict(too_deep)


def test_authorization_decisions_cannot_masquerade_as_theorem_proof() -> None:
    with pytest.raises(AuthorizationValidationError, match="masquerade|authorization"):
        PolicyDecision(
            "decision:bad-authority",
            query_id="query:alice-read-payroll",
            outcome=DecisionOutcome.ALLOW,
            authority="theorem",  # type: ignore[arg-type]
        )
    with pytest.raises(
        AuthorizationValidationError, match="not_established|generated-code"
    ):
        PolicyDecision(
            "decision:bad-correctness",
            query_id="query:alice-read-payroll",
            outcome=DecisionOutcome.ALLOW,
            generated_code_correctness="established",  # type: ignore[arg-type]
        )

    decision = PolicyDecision(
        "decision:ok",
        query_id="query:alice-read-payroll",
        outcome=DecisionOutcome.ALLOW,
    )
    assert decision.authority is AuthorizationEvidenceAuthority.AUTHORIZATION
    assert (
        decision.generated_code_correctness
        is GeneratedCodeCorrectness.NOT_ESTABLISHED
    )
    assert decision.is_theorem_authority is False
    assert authority_is_authorization_only("authorization")
    assert not authority_is_authorization_only("theorem")
    assert not authority_is_authorization_only("proof")


def test_facts_must_be_finite_ground_and_positive() -> None:
    with pytest.raises(AuthorizationValidationError, match="ground"):
        AuthorizationFact(
            "fact:open",
            _atom("pred:role", _var("P"), _const("role:admin", "role")),
            **_mapped(),
        )
    with pytest.raises(AuthorizationValidationError, match="positive"):
        AuthorizationFact(
            "fact:neg",
            _atom(
                "pred:role",
                _const("principal:alice"),
                _const("role:admin", "role"),
                polarity=AtomPolarity.NEGATIVE,
            ),
            **_mapped(),
        )


def test_source_mapping_and_unknown_fields_fail_closed() -> None:
    with pytest.raises(AuthorizationValidationError, match="source mapped"):
        AuthorizationPrincipal("principal:x", "X", PrincipalKind.USER)
    with pytest.raises(AuthorizationValidationError, match="unknown"):
        AuthorizationPrincipal.from_dict(
            {
                "principal_id": "principal:x",
                "name": "X",
                "kind": "user",
                "source_ref_ids": [SOURCE_ID],
                "unexpected": True,
            }
        )


def test_secpal_says_requires_issuer_and_speaks_for_is_asymmetric() -> None:
    with pytest.raises(AuthorizationValidationError, match="issuer_principal_id"):
        AuthorizationRule(
            "rule:orphan-says",
            head=_atom(
                "pred:may",
                _const("principal:bob"),
                _const("read", "action"),
                _const("resource:payroll", "resource"),
            ),
            kind=RuleKind.SECPAL_SAYS,
            effect=EffectKind.ALLOW,
            **_mapped(),
        )
    with pytest.raises(AuthorizationValidationError, match="must differ"):
        SpeaksForRelation(
            "speaks-for:self",
            speaker_principal_id="principal:alice",
            subject_principal_id="principal:alice",
            **_mapped(),
        )


def test_atom_arity_and_sorts_are_checked_against_predicates() -> None:
    document = _document()
    payload = document.to_dict()
    payload["document_id"] = ""
    payload["facts"][0]["atom"]["arguments"] = [
        AuthorizationTerm.constant("principal:alice").to_dict()
    ]
    with pytest.raises(AuthorizationValidationError, match="arity"):
        AuthorizationIR.from_dict(payload)


def test_decision_explanation_must_agree_with_decision_outcome() -> None:
    document = _document()
    payload = document.to_dict()
    payload["document_id"] = ""
    for decision in payload["decisions"]:
        if decision["decision_id"] == "decision:alice-allow":
            decision["outcome"] = "deny"
            break
    with pytest.raises(AuthorizationValidationError, match="outcome must match"):
        AuthorizationIR.from_dict(payload)


def test_terms_distinguish_constants_and_variables() -> None:
    constant = AuthorizationTerm.constant("alice")
    variable = AuthorizationTerm.variable("X")
    assert constant.kind is TermKind.CONSTANT
    assert variable.kind is TermKind.VARIABLE
    assert constant.is_ground
    assert not variable.is_ground
    assert AuthorizationTerm.from_dict(constant.to_dict()) == constant


def test_metadata_rejects_observational_keys() -> None:
    with pytest.raises(AuthorizationValidationError, match="observational"):
        replace(
            _document(),
            metadata={"duration_ms": 12},
            document_id="",
        )


@pytest.mark.parametrize(
    "outcome",
    [
        DecisionOutcome.ALLOW,
        DecisionOutcome.DENY,
        DecisionOutcome.CONFLICT,
        DecisionOutcome.UNKNOWN,
    ],
)
def test_each_decision_outcome_is_constructible(outcome: DecisionOutcome) -> None:
    decision = PolicyDecision(
        f"decision:{outcome.value}",
        query_id="query:alice-read-payroll",
        outcome=outcome,
    )
    assert decision.outcome is outcome
    assert decision.authority is AuthorizationEvidenceAuthority.AUTHORIZATION
