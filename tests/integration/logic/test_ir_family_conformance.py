"""Cross-domain conformance for the reviewed Legal, Security, and Intent IR family."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib

import pytest

from ipfs_datasets_py.logic.formalization.compiler import (
    FormalizationArtifact,
    FormalizationCompiler,
)
from ipfs_datasets_py.logic.formalization.samples import FormalizationSample
from ipfs_datasets_py.logic.intent_ir.decoder import migrate_intent_ir
from ipfs_datasets_py.logic.intent_ir.formalize.compiler import (
    IntentFormalizationCompiler,
)
from ipfs_datasets_py.logic.intent_ir.schema import (
    IntentAction,
    IntentIRDocument,
    IntentKind,
    IntentModality,
    IntentStatement,
    LEGACY_INTENT_IR_SCHEMA_VERSION,
    ReviewStatus,
    SourceRef,
    StatementKind,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    AttemptStatus,
    AuthorityKind,
    AuthorityMismatchError,
    BackendAttempt,
    EvidenceGateResult,
    ProofReceipt,
    QueryKind,
    ResourceUsage,
    ResultAuthority,
    ResultStatus,
)
from ipfs_datasets_py.logic.ir_core.provenance import Provenance
from ipfs_datasets_py.logic.legal_ir.adapter import (
    LegalIRFormalizationAdapter,
)
from ipfs_datasets_py.logic.security_ir.formalization_adapter import (
    SecurityIRFormalizationAdapter,
)
from ipfs_datasets_py.logic.security_ir.model import (
    Policy,
    PolicyEffect,
    SecurityClaim,
    SecurityIR,
    SecuritySource,
    ThreatAssumption,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    LegalSample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


def _legal_fixture(*, predicate: str = "publish_notice") -> LegalSample:
    text = "Agency shall publish notice."
    document = ModalIRDocument(
        document_id="legal:notice",
        source="us_code",
        normalized_text=text,
        formulas=[
            ModalIRFormula(
                formula_id="legal:notice:formula",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name=predicate,
                    arguments=["agency", "notice"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="legal:notice",
                    start_char=0,
                    end_char=len(text),
                    citation="Fixture § 1",
                ),
            )
        ],
        metadata={"fixture": "cross-domain"},
    )
    sample = LegalSample(
        sample_id="legal:notice",
        source="us_code",
        title="Fixture",
        section="1",
        citation="Fixture § 1",
        text=text,
        normalized_text=text,
        embedding_model="fixture:embedding/v1",
        embedding_vector=[0.0],
        modal_ir=document,
        selected_frame="",
    )
    sample.validate()
    return sample


def _security_fixture(*, statement: str = "Only approved bytes are signed.") -> SecurityIR:
    content = b"reviewed security fixture"
    source = SecuritySource(
        source_id="source:security",
        uri="repo://fixtures/security.md",
        revision="revision-1",
        content_sha256=hashlib.sha256(content).hexdigest(),
        review_status="trusted_fixture",
    )
    assumption = ThreatAssumption(
        assumption_id="assumption:isolated-runtime",
        statement="The runtime isolates signing keys.",
        source_ids=(source.source_id,),
    )
    policy = Policy(
        policy_id="policy:approval",
        name="require_approval",
        effect=PolicyEffect.REQUIRE,
        source_ids=(source.source_id,),
    )
    claim = SecurityClaim(
        claim_id="claim:approved-signing",
        statement=statement,
        domain="signing",
        assumption_ids=(assumption.assumption_id,),
        policy_ids=(policy.policy_id,),
        source_ids=(source.source_id,),
    )
    return SecurityIR(
        declaration_id="security:signing",
        sources=(source,),
        assumptions=(assumption,),
        policies=(policy,),
        claims=(claim,),
    )


def _intent_fixture(*, goal_predicate: str = "publish") -> IntentIRDocument:
    source = SourceRef(
        ref_id="source:intent",
        source_uri="repo://fixtures/intent.md",
        source_id="intent-fixture",
        source_revision="revision-1",
        content_sha256=hashlib.sha256(b"reviewed intent fixture").hexdigest(),
        review_status=ReviewStatus.TRUSTED_FIXTURE,
    )
    statements = (
        IntentStatement(
            statement_id="statement:goal",
            kind=StatementKind.GOAL,
            modality=IntentModality.INTENDED,
            normalized_text="Publish the result.",
            predicate=goal_predicate,
            arguments=("result",),
            source_ref_ids=(source.ref_id,),
            review_status=ReviewStatus.TRUSTED_FIXTURE,
        ),
        IntentStatement(
            statement_id="statement:effect",
            kind=StatementKind.EFFECT,
            modality=IntentModality.ASSERTED,
            normalized_text="The result is published.",
            predicate="published",
            arguments=("result",),
            source_ref_ids=(source.ref_id,),
            review_status=ReviewStatus.TRUSTED_FIXTURE,
        ),
        IntentStatement(
            statement_id="statement:verify",
            kind=StatementKind.VERIFICATION,
            modality=IntentModality.REQUIRED,
            normalized_text="The publication is observable.",
            predicate="observed",
            arguments=("result",),
            source_ref_ids=(source.ref_id,),
            review_status=ReviewStatus.TRUSTED_FIXTURE,
        ),
    )
    document = IntentIRDocument(
        document_id="intent:publish",
        title="Publish a result",
        intent_kind=IntentKind.PROCEDURE,
        sources=(source,),
        statements=statements,
        actions=(
            IntentAction(
                action_id="action:publish",
                actor="agent",
                verb="publish",
                object_refs=("result",),
                source_ref_ids=(source.ref_id,),
                effect_ids=("statement:effect",),
                verification_ids=("statement:verify",),
            ),
        ),
        entry_action_ids=("action:publish",),
        terminal_action_ids=("action:publish",),
        tags=("conformance",),
    )
    document.validate()
    return document


def _domain_cases() -> tuple[tuple[str, FormalizationCompiler, object], ...]:
    return (
        ("legal", LegalIRFormalizationAdapter(), _legal_fixture()),
        ("security", SecurityIRFormalizationAdapter(), _security_fixture()),
        ("intent", IntentFormalizationCompiler(), _intent_fixture()),
    )


def test_all_domain_adapters_emit_immutable_source_grounded_shared_contracts() -> None:
    artifacts: list[FormalizationArtifact] = []

    for domain, adapter, declaration in _domain_cases():
        sample = adapter.adapt_sample(declaration)  # type: ignore[attr-defined]
        artifact = adapter.compile(  # type: ignore[attr-defined]
            sample,
            adapter.default_config(sample),  # type: ignore[attr-defined]
        )

        assert isinstance(adapter, FormalizationCompiler)
        assert isinstance(sample, FormalizationSample)
        assert isinstance(artifact, FormalizationArtifact)
        assert sample.domain == artifact.domain == domain
        assert sample.declaration_id == artifact.declaration_id
        assert sample.declaration_digest == artifact.declaration_digest
        assert isinstance(artifact.source_map, Provenance)
        artifact.source_map.validate()
        assert artifact.formulas
        bindings = {
            binding.subject_id: binding
            for binding in artifact.source_map.bindings
        }
        assert all(formula.source_ref_ids for formula in artifact.formulas)
        assert all(
            set(formula.source_ref_ids)
            <= set(bindings[formula.formula_id].source_ref_ids)
            for formula in artifact.formulas
        )
        assert FormalizationSample.from_json(sample.to_json()) == sample
        assert FormalizationArtifact.from_json(artifact.to_json()) == artifact
        assert adapter.compile(  # type: ignore[attr-defined]
            sample,
            adapter.default_config(sample),  # type: ignore[attr-defined]
        ).digest == artifact.digest
        with pytest.raises(FrozenInstanceError):
            artifact.domain = "mutated"  # type: ignore[misc]
        artifacts.append(artifact)

    assert {artifact.domain for artifact in artifacts} == {
        "legal",
        "security",
        "intent",
    }
    assert len({artifact.digest for artifact in artifacts}) == 3
    view_sets = [
        set(artifact.view_registry.view_ids) for artifact in artifacts
    ]
    assert all(
        view_sets[left].isdisjoint(view_sets[right])
        for left in range(len(view_sets))
        for right in range(left + 1, len(view_sets))
    )


def test_semantic_mutation_changes_each_domain_artifact_identity() -> None:
    legal = LegalIRFormalizationAdapter()
    security = SecurityIRFormalizationAdapter()
    intent = IntentFormalizationCompiler()

    pairs = (
        (legal.adapt(_legal_fixture()), legal.adapt(_legal_fixture(predicate="withhold_notice"))),
        (
            security.adapt(_security_fixture()),
            security.adapt(
                _security_fixture(statement="All transaction bytes may be signed.")
            ),
        ),
        (
            intent.compile(_intent_fixture()),
            intent.compile(_intent_fixture(goal_predicate="archive")),
        ),
    )

    for baseline, mutated in pairs:
        assert baseline.declaration_digest != mutated.declaration_digest
        assert baseline.digest != mutated.digest
        assert baseline.formulas != mutated.formulas


def test_intent_schema_migration_is_exact_versioned_and_receipted() -> None:
    current = _intent_fixture().to_dict()
    legacy = dict(current)
    legacy["schema_version"] = LEGACY_INTENT_IR_SCHEMA_VERSION
    for collection in ("statements", "actions", "control_edges"):
        legacy[collection] = [
            {key: value for key, value in item.items() if key != "grounding"}
            for item in current[collection]
        ]

    first = migrate_intent_ir(legacy)
    second = migrate_intent_ir(legacy)

    assert first.document == second.document
    assert first.receipt == second.receipt
    assert first.receipt is not None
    assert first.receipt.verifies(legacy, first.document.to_dict())
    assert first.source_version == LEGACY_INTENT_IR_SCHEMA_VERSION
    assert first.target_version == first.document.schema_version
    assert {
        diagnostic.code for diagnostic in first.diagnostics
    } >= {"node_grounding_classified", "schema_version_upgraded"}


def test_non_proof_authority_cannot_issue_a_theorem_receipt() -> None:
    compiler = IntentFormalizationCompiler()
    artifact = compiler.compile(_intent_fixture())
    from ipfs_datasets_py.logic.intent_ir.formalize.obligations import (
        IntentProofObligations,
    )

    packet = IntentProofObligations().generate(artifact)
    request = packet.requests[0]
    attempt = BackendAttempt(
        attempt_id="attempt:evidence-gate",
        request_digest=request.digest,
        backend_id="evidence-gate",
        backend_version="1",
        status=AttemptStatus.SUCCEEDED,
        bounds=request.bounds,
        usage=ResourceUsage(),
        output_digest="1" * 64,
    )
    evidence_request = replace(
        request,
        query_kind=QueryKind.EVIDENCE_READINESS,
    )
    # Rebind the attempt because changing query authority changes request identity.
    attempt = replace(attempt, request_digest=evidence_request.digest)
    result = EvidenceGateResult.for_attempt(
        evidence_request,
        attempt,
        result_id="result:evidence-gate",
        authority=ResultAuthority(
            kind=AuthorityKind.EVIDENCE_READINESS,
            issuer="evidence-gate",
            method="fixture/v1",
            scope_digest=evidence_request.digest,
            configuration_digest="2" * 64,
        ),
        status=ResultStatus.READY,
        output_digest=attempt.output_digest,
    )

    with pytest.raises(AuthorityMismatchError):
        ProofReceipt.issue(
            packet.claim,
            evidence_request,
            attempt,
            result,
            receipt_id="receipt:forged-proof",
            verifier="integration-fixture",
        )
