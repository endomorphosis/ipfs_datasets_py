"""Unit contracts for shared constraint and applicability interfaces.

Covers ConstraintArtifact@1, ApplicabilityEvidence@1, and SelectedPremiseSet@1
using a fake domain only — no Legal/Security corpus, solver, or registry.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.formalization.constraint_contracts import (
    APPLICABILITY_EVIDENCE_INTERFACE,
    CONSTRAINT_ARTIFACT_INTERFACE,
    SELECTED_PREMISE_SET_INTERFACE,
    ApplicabilityEvidence,
    ApplicabilitySelector,
    ApplicabilityStatus,
    ConstraintArtifact,
    ConstraintRole,
    ConstraintStatement,
    ConstraintValidationError,
    CoverageGap,
    CoverageGapKind,
    NativeViewBinding,
    PremiseSelectionMethod,
    ReconstructionReceipt,
    SelectedPremise,
    SelectedPremiseSet,
    TranslationReceipt,
    WorldPolicy,
    WorldPolicyKind,
    forbid_silent_logic_concatenation,
    reject_result_authority_substitution,
)
from ipfs_datasets_py.logic.formalization.views import FormalSymbol, SymbolTable
from ipfs_datasets_py.logic.ir_core.claims import Assumption, ProofObligation
from ipfs_datasets_py.logic.ir_core.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticLocation,
    DiagnosticReport,
    DiagnosticSeverity,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    AuthorityKind,
    AuthorityMismatchError,
    ResultAuthority,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
DIGEST_A = f"sha256:{SHA_A}"
DIGEST_B = f"sha256:{SHA_B}"


def _vocabulary() -> SymbolTable:
    return SymbolTable(
        table_id="vocab:fake-1",
        symbols=(
            FormalSymbol(
                symbol_id="symbol:actor",
                name="agent",
                kind="constant",
                sort="principal",
                source_ref_ids=("source:fixture",),
                span_ids=("span:1",),
            ),
            FormalSymbol(
                symbol_id="symbol:action",
                name="publish",
                kind="predicate",
                sort="action",
                source_ref_ids=("source:fixture",),
                span_ids=("span:1",),
            ),
        ),
    )


def _grant_statement(**overrides: object) -> ConstraintStatement:
    base = dict(
        statement_id="stmt:grant-publish",
        role=ConstraintRole.GRANT,
        logic_family="deontic",
        expression={
            "operator": "permitted",
            "predicate": "publish",
            "arguments": ["agent"],
        },
        symbol_ids=("symbol:actor", "symbol:action"),
        source_ref_ids=("source:fixture",),
        span_ids=("span:1",),
        view_id="view:deontic",
    )
    base.update(overrides)
    return ConstraintStatement(**base)  # type: ignore[arg-type]


def _invariant_statement() -> ConstraintStatement:
    return ConstraintStatement(
        statement_id="stmt:safety-invariant",
        role=ConstraintRole.INVARIANT,
        logic_family="first_order",
        expression={"predicate": "no_exfiltration", "arguments": ["agent"]},
        symbol_ids=("symbol:actor",),
        source_ref_ids=("source:fixture",),
        span_ids=("span:1",),
        view_id="view:fol",
    )


def _native_views() -> tuple[NativeViewBinding, ...]:
    return (
        NativeViewBinding(
            view_id="view:deontic",
            logic_family="deontic",
            statement_ids=("stmt:grant-publish",),
            capabilities=("modality", "grants"),
            description="Deontic permission view",
        ),
        NativeViewBinding(
            view_id="view:fol",
            logic_family="first_order",
            statement_ids=("stmt:safety-invariant",),
            capabilities=("invariants",),
            description="First-order safety view",
        ),
    )


def _selectors() -> tuple[ApplicabilitySelector, ...]:
    return (
        ApplicabilitySelector(
            selector_id="sel:jurisdiction",
            dimension="jurisdiction",
            value="US-OR",
            source_ref_ids=("source:fixture",),
        ),
        ApplicabilitySelector(
            selector_id="sel:action",
            dimension="action",
            value="publish",
            source_ref_ids=("source:fixture",),
        ),
    )


def _world_policy(*, kind: WorldPolicyKind = WorldPolicyKind.CLOSED) -> WorldPolicy:
    return WorldPolicy(
        kind=kind,
        default_on_unknown="indeterminate",
        allow_negation_as_failure=kind is WorldPolicyKind.CLOSED,
    )


def _assumptions() -> tuple[Assumption, ...]:
    return (
        Assumption(
            assumption_id="assumption:actor-exists",
            statement="the actor exists",
            source_refs=("source:fixture",),
        ),
    )


def _obligations() -> tuple[ProofObligation, ...]:
    return (
        ProofObligation(
            obligation_id="obligation:permit-publish",
            statement="permitted(publish(agent))",
            assumption_ids=("assumption:actor-exists",),
            logic_family="deontic",
            source_refs=("source:fixture",),
        ),
        ProofObligation(
            obligation_id="obligation:no-exfil",
            statement="no_exfiltration(agent)",
            assumption_ids=("assumption:actor-exists",),
            logic_family="first_order",
            source_refs=("source:fixture",),
        ),
    )


def _selected_premises() -> SelectedPremiseSet:
    return SelectedPremiseSet(
        set_id="premises:1",
        premises=(
            SelectedPremise(
                premise_id="premise:actor",
                statement="the actor exists",
                source_ref_ids=("source:fixture",),
                logic_family="first_order",
                rank=0,
                selection_method=PremiseSelectionMethod.HARD_FILTER,
                assumption_id="assumption:actor-exists",
            ),
            SelectedPremise(
                premise_id="premise:grant",
                statement="publish is granted when jurisdiction matches",
                source_ref_ids=("source:fixture",),
                logic_family="deontic",
                rank=1,
                score=0.91,
                selection_method=PremiseSelectionMethod.DETERMINISTIC_RANK,
                statement_id="stmt:grant-publish",
            ),
        ),
        selection_method=PremiseSelectionMethod.DETERMINISTIC_RANK,
        considered_count=5,
        filtered_count=3,
        budget=8,
        config_id="config:fake",
        query_digest=DIGEST_A,
    )


def _applicability(
    *,
    status: ApplicabilityStatus = ApplicabilityStatus.APPLICABLE,
    gaps: tuple[CoverageGap, ...] = (),
) -> ApplicabilityEvidence:
    matched = ("sel:jurisdiction", "sel:action")
    rejected: tuple[str, ...] = ()
    if status is ApplicabilityStatus.NOT_APPLICABLE:
        matched = ("sel:jurisdiction",)
        rejected = ("sel:action",)
    return ApplicabilityEvidence(
        evidence_id="evidence:1",
        status=status,
        selectors=_selectors(),
        matched_selector_ids=matched,
        rejected_selector_ids=rejected,
        coverage_gaps=gaps,
        constraint_artifact_id="artifact:fake-1",
        constraint_artifact_digest=DIGEST_A,
        invocation_digest=DIGEST_B,
        world_policy=_world_policy(),
        required_authority=AuthorityKind.THEOREM_PROOF,
        notes="hard filters only",
    )


def _diagnostics() -> DiagnosticReport:
    return DiagnosticReport(
        report_id="diagnostics:constraint-1",
        diagnostics=(
            Diagnostic(
                code=DiagnosticCode.UNSUPPORTED_FEATURE,
                message="opaque human confirmation retained",
                severity=DiagnosticSeverity.WARNING,
                location=DiagnosticLocation(
                    subject_ids=("stmt:grant-publish",),
                    source_ref_ids=("source:fixture",),
                    span_ids=("span:1",),
                ),
                producer_id="adapter:fake",
            ),
        ),
        producer_id="adapter:fake",
    )


def _artifact(**overrides: object) -> ConstraintArtifact:
    base: dict[str, object] = dict(
        artifact_id="artifact:fake-1",
        domain="fake-domain",
        logic_family="deontic",
        source_id="source:fixture",
        corpus_id="corpus:fake-v1",
        config_id="config:fake",
        declaration_id="decl:publish-rule",
        declaration_digest=DIGEST_A,
        vocabulary=_vocabulary(),
        native_views=_native_views(),
        statements=(_grant_statement(), _invariant_statement()),
        world_policy=_world_policy(),
        assumptions=_assumptions(),
        proof_obligations=_obligations(),
        applicability_selectors=_selectors(),
        applicability_evidence=_applicability(),
        selected_premises=_selected_premises(),
        translations=(
            TranslationReceipt(
                translation_id="translation:deontic-fol",
                source_logic_family="deontic",
                target_logic_family="first_order",
                source_view_id="view:deontic",
                target_view_id="view:fol",
                source_statement_ids=("stmt:grant-publish",),
                target_statement_ids=("stmt:safety-invariant",),
                translator_id="translator:fake",
                translator_version="1.0",
                lossy=True,
            ),
        ),
        reconstructions=(
            ReconstructionReceipt(
                reconstruction_id="recon:fol-1",
                logic_family="first_order",
                view_id="view:fol",
                statement_ids=("stmt:safety-invariant",),
                reconstructor_id="reconstructor:fake",
                reconstructor_version="1.0",
                source_digest=DIGEST_A,
                reconstructed_digest=DIGEST_B,
                faithful=True,
            ),
        ),
        coverage_gaps=(),
        diagnostics=_diagnostics(),
        adapter_id="adapter:fake",
        compiler_id="compiler:fake",
        ontology_id="ontology:fake",
        policy_id="policy:fake",
        producer_id="producer:fake",
        required_authority=AuthorityKind.THEOREM_PROOF,
        metadata={"fixture": True},
    )
    base.update(overrides)
    return ConstraintArtifact(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Happy path: identities, immutability, round-trip
# ---------------------------------------------------------------------------


def test_constraint_artifact_binds_identities_and_round_trips() -> None:
    artifact = _artifact()

    assert artifact.INTERFACE == CONSTRAINT_ARTIFACT_INTERFACE
    assert artifact.domain == "fake-domain"
    assert artifact.source_id == "source:fixture"
    assert artifact.corpus_id == "corpus:fake-v1"
    assert artifact.config_id == "config:fake"
    assert artifact.logic_family == "deontic"
    assert artifact.declaration_digest == DIGEST_A
    assert artifact.world_policy.kind is WorldPolicyKind.CLOSED
    assert len(artifact.native_views) == 2
    assert len(artifact.statements) == 2
    assert len(artifact.proof_obligations) == 2
    assert artifact.digest
    assert artifact.cid.startswith("b")
    assert ConstraintArtifact.from_json(artifact.to_json()).digest == artifact.digest
    assert ConstraintArtifact.from_dict(artifact.to_dict()) == artifact


def test_constraint_artifact_is_immutable_and_defensively_copies_maps() -> None:
    meta = {"label": "original"}
    artifact = _artifact(metadata=meta)
    meta["label"] = "mutated"

    assert artifact.metadata.to_dict()["label"] == "original"
    with pytest.raises(FrozenInstanceError):
        artifact.domain = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        artifact.statements[0] = _grant_statement()  # type: ignore[index]


def test_stable_obligation_digests_are_deterministic() -> None:
    first = _artifact()
    second = _artifact()
    digests = first.obligation_digests()

    assert digests == second.obligation_digests()
    assert set(digests) == {
        "obligation:no-exfil",
        "obligation:permit-publish",
    }
    assert all(len(value) == 64 for value in digests.values())


def test_vocabulary_and_typed_roles_are_preserved() -> None:
    artifact = _artifact()
    roles = {item.statement_id: item.role for item in artifact.statements}

    assert roles["stmt:grant-publish"] is ConstraintRole.GRANT
    assert roles["stmt:safety-invariant"] is ConstraintRole.INVARIANT
    assert artifact.vocabulary["symbol:action"].name == "publish"
    assert artifact.native_views[0].logic_family in {"deontic", "first_order"}


# ---------------------------------------------------------------------------
# Applicability evidence
# ---------------------------------------------------------------------------


def test_applicability_evidence_round_trips_and_enforces_required_selectors() -> None:
    evidence = _applicability()

    assert evidence.INTERFACE == APPLICABILITY_EVIDENCE_INTERFACE
    assert evidence.status is ApplicabilityStatus.APPLICABLE
    assert ApplicabilityEvidence.from_json(evidence.to_json()).digest == evidence.digest

    with pytest.raises(ConstraintValidationError, match="required selectors"):
        ApplicabilityEvidence(
            evidence_id="evidence:bad",
            status=ApplicabilityStatus.APPLICABLE,
            selectors=_selectors(),
            matched_selector_ids=("sel:jurisdiction",),  # missing required action
        )


def test_applicability_rejects_gaps_on_applicable_and_requires_gaps_for_coverage() -> None:
    gap = CoverageGap(
        gap_id="gap:jurisdiction",
        kind=CoverageGapKind.MISSING_JURISDICTION,
        description="no rule for jurisdiction",
        related_selector_ids=("sel:jurisdiction",),
    )
    with pytest.raises(ConstraintValidationError, match="coverage gaps"):
        _applicability(
            status=ApplicabilityStatus.APPLICABLE,
            gaps=(gap,),
        )

    evidence = ApplicabilityEvidence(
        evidence_id="evidence:gap",
        status=ApplicabilityStatus.COVERAGE_GAP,
        selectors=_selectors(),
        matched_selector_ids=("sel:action",),
        rejected_selector_ids=(),
        coverage_gaps=(gap,),
    )
    assert evidence.status is ApplicabilityStatus.COVERAGE_GAP
    assert evidence.coverage_gaps[0].kind is CoverageGapKind.MISSING_JURISDICTION

    with pytest.raises(ConstraintValidationError, match="coverage gap"):
        ApplicabilityEvidence(
            evidence_id="evidence:gap-empty",
            status=ApplicabilityStatus.COVERAGE_GAP,
            selectors=_selectors(),
            matched_selector_ids=(),
            coverage_gaps=(),
        )


def test_open_and_closed_world_policy_rules() -> None:
    closed = WorldPolicy(
        kind=WorldPolicyKind.CLOSED,
        allow_negation_as_failure=True,
    )
    open_policy = WorldPolicy(kind=WorldPolicyKind.OPEN)

    assert closed.kind is WorldPolicyKind.CLOSED
    assert open_policy.allow_negation_as_failure is False
    with pytest.raises(ConstraintValidationError, match="negation-as-failure"):
        WorldPolicy(kind=WorldPolicyKind.OPEN, allow_negation_as_failure=True)


# ---------------------------------------------------------------------------
# Premise selection
# ---------------------------------------------------------------------------


def test_selected_premise_set_requires_grounding_and_respects_budget() -> None:
    premises = _selected_premises()

    assert premises.INTERFACE == SELECTED_PREMISE_SET_INTERFACE
    assert len(premises.premises) == 2
    assert SelectedPremiseSet.from_dict(premises.to_dict()).digest == premises.digest

    with pytest.raises(ConstraintValidationError, match="ungrounded"):
        SelectedPremise(
            premise_id="premise:bad",
            statement="no source",
            source_ref_ids=(),
        )

    with pytest.raises(ConstraintValidationError, match="budget"):
        SelectedPremiseSet(
            set_id="premises:over",
            premises=premises.premises,
            budget=1,
            considered_count=5,
        )


def test_premise_ranking_score_rejects_non_finite() -> None:
    with pytest.raises(ConstraintValidationError, match="finite"):
        SelectedPremise(
            premise_id="premise:nan",
            statement="bad score",
            source_ref_ids=("source:fixture",),
            score=float("nan"),
        )


# ---------------------------------------------------------------------------
# Rejections: ungrounded, authority, schema, mutable, silent concat
# ---------------------------------------------------------------------------


def test_rejects_ungrounded_constraint_statements() -> None:
    with pytest.raises(ConstraintValidationError, match="source-grounded"):
        ConstraintStatement(
            statement_id="stmt:ungrounded",
            role=ConstraintRole.CLAIM,
            logic_family="first_order",
            expression={"predicate": "p"},
            source_ref_ids=(),
            span_ids=(),
        )


def test_rejects_unknown_logic_family_and_schema() -> None:
    with pytest.raises(ConstraintValidationError, match="unknown logic family"):
        ConstraintStatement(
            statement_id="stmt:weird",
            role=ConstraintRole.CLAIM,
            logic_family="quantum-fuzzy-logic",
            expression={"predicate": "p"},
            source_ref_ids=("source:fixture",),
        )

    with pytest.raises(ConstraintValidationError, match="unsupported"):
        WorldPolicy(
            kind=WorldPolicyKind.CLOSED,
            schema_version="world-policy/v999",
        )

    with pytest.raises(ConstraintValidationError, match="unsupported constraint artifact"):
        replace(_artifact(), schema_version="constraint-artifact/v999")


def test_rejects_result_authority_substitution() -> None:
    artifact = _artifact()
    with pytest.raises(AuthorityMismatchError, match="substitution"):
        artifact.require_authority(AuthorityKind.SATISFIABILITY)

    with pytest.raises(AuthorityMismatchError, match="substitution"):
        reject_result_authority_substitution(
            AuthorityKind.POLICY_APPROVAL,
            AuthorityKind.THEOREM_PROOF,
        )

    authority = ResultAuthority(
        kind=AuthorityKind.EVIDENCE_READINESS,
        issuer="issuer:test",
        method="checklist",
        scope_digest=SHA_A,
    )
    with pytest.raises(AuthorityMismatchError):
        reject_result_authority_substitution(
            authority, AuthorityKind.THEOREM_PROOF
        )

    # Exact match is allowed.
    reject_result_authority_substitution(
        AuthorityKind.THEOREM_PROOF, AuthorityKind.THEOREM_PROOF
    )
    artifact.require_authority(AuthorityKind.THEOREM_PROOF)

    evidence = _applicability()
    with pytest.raises(AuthorityMismatchError):
        evidence.require_authority(AuthorityKind.SATISFIABILITY)


def test_rejects_silent_modal_datalog_temporal_hoare_smt_concatenation() -> None:
    with pytest.raises(ConstraintValidationError, match="silent logic concatenation"):
        forbid_silent_logic_concatenation(("modal", "datalog", "smt"))

    with pytest.raises(ConstraintValidationError, match="silent logic concatenation"):
        ConstraintStatement(
            statement_id="stmt:blend",
            role=ConstraintRole.CLAIM,
            logic_family="modal",
            expression={
                "predicate": "p",
                "logic_families": ["modal", "temporal", "hoare"],
            },
            source_ref_ids=("source:fixture",),
        )

    # Distinct native views with different families are allowed; silent
    # blending inside one statement is not.
    artifact = _artifact()
    families = {view.logic_family for view in artifact.native_views}
    assert families == {"deontic", "first_order"}
    assert len(artifact.translations) == 1


def test_rejects_unknown_vocabulary_and_view_cross_refs() -> None:
    with pytest.raises(ConstraintValidationError, match="unknown vocabulary"):
        _artifact(
            statements=(
                _grant_statement(symbol_ids=("symbol:missing",)),
                _invariant_statement(),
            )
        )

    with pytest.raises(ConstraintValidationError, match="unknown view"):
        _artifact(
            statements=(
                _grant_statement(view_id="view:missing"),
                _invariant_statement(),
            )
        )


def test_rejects_logic_disagreement_between_statement_and_view() -> None:
    with pytest.raises(ConstraintValidationError, match="disagrees with native view"):
        _artifact(
            statements=(
                _grant_statement(logic_family="smt"),
                _invariant_statement(),
            )
        )


def test_rejects_mutable_set_collections_for_premises() -> None:
    with pytest.raises(ConstraintValidationError, match="mutable set"):
        SelectedPremiseSet(
            set_id="premises:set",
            premises=set(),  # type: ignore[arg-type]
        )


def test_rejects_unknown_interface_and_fields() -> None:
    payload = _artifact().to_dict()
    payload["interface"] = "ConstraintArtifact@9"
    with pytest.raises(ConstraintValidationError, match="unknown constraint artifact interface"):
        ConstraintArtifact.from_dict(payload)

    payload = _artifact().to_dict()
    payload["unexpected"] = True
    with pytest.raises(ConstraintValidationError, match="unknown constraint artifact field"):
        ConstraintArtifact.from_dict(payload)


def test_rejects_ungrounded_selected_premise_on_artifact_link() -> None:
    with pytest.raises(ConstraintValidationError, match="unknown assumption"):
        _artifact(
            selected_premises=SelectedPremiseSet(
                set_id="premises:bad-link",
                premises=(
                    SelectedPremise(
                        premise_id="premise:orphan",
                        statement="orphan",
                        source_ref_ids=("source:fixture",),
                        assumption_id="assumption:missing",
                    ),
                ),
                considered_count=1,
            )
        )


def test_translation_requires_distinct_families_and_views() -> None:
    with pytest.raises(ConstraintValidationError, match="change logic family"):
        TranslationReceipt(
            translation_id="translation:same",
            source_logic_family="deontic",
            target_logic_family="deontic",
            source_view_id="view:deontic",
            target_view_id="view:fol",
        )

    with pytest.raises(ConstraintValidationError, match="views must differ"):
        TranslationReceipt(
            translation_id="translation:same-view",
            source_logic_family="deontic",
            target_logic_family="first_order",
            source_view_id="view:deontic",
            target_view_id="view:deontic",
        )


def test_coverage_gaps_and_diagnostics_bind_into_artifact() -> None:
    gap = CoverageGap(
        gap_id="gap:authority",
        kind=CoverageGapKind.MISSING_AUTHORITY,
        description="no binding authority for subject",
        related_selector_ids=("sel:jurisdiction",),
    )
    artifact = _artifact(
        applicability_evidence=_applicability(
            status=ApplicabilityStatus.COVERAGE_GAP,
            gaps=(gap,),
        ),
        coverage_gaps=(gap,),
    )
    assert artifact.coverage_gaps[0].kind is CoverageGapKind.MISSING_AUTHORITY
    assert artifact.diagnostics is not None
    assert artifact.diagnostics.warning_count == 1


def test_identity_is_stable_under_reordering() -> None:
    left = _artifact()
    right = _artifact(
        statements=(_invariant_statement(), _grant_statement()),
        native_views=tuple(reversed(_native_views())),
        proof_obligations=tuple(reversed(_obligations())),
    )
    assert left.digest == right.digest
    assert left.cid == right.cid
