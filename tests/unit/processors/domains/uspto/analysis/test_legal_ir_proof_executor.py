"""Unit tests for privacy-safe Legal IR proof execution (PATLAW-126).

Covers known satisfiable, contradictory, incomplete, and timeout fixtures;
premise and engine/config identity citations; unavailable/unsupported logic
→ unknown; and mapping/compiler adapter paths.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.legal_ir_contracts import (
    LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
    ActorRole,
    AssertionKind,
    AssumptionRef,
    AuthorityBinding,
    AuthorityRank,
    AuthorityResolutionState,
    CitationRef,
    CounterEvidenceRef,
    DisclosureMetadata,
    LegalIRContractBundle,
    LegalModality,
    MappingStatus,
    NormalizedProposition,
    ProofObligation,
    SourceIdentity,
    SubmissionFactRef,
    TemporalMetadata,
    TriStateOutcome,
    UsptoSpanRef,
    build_legal_ir_mapping,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.legal_ir_proof_executor import (
    LEGAL_IR_PROOF_EXECUTOR_INTERFACE,
    LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
    PROOF_KERNEL_IDENTITY,
    AtomicLiteral,
    ExecutionRoute,
    FixtureKind,
    LegalIRProofExecutor,
    LogicFamily,
    PremiseCitation,
    ProofExecutionRequest,
    ProofExecutorConfig,
    ProofOutcome,
    ProofProblem,
    ProofReasonCode,
    build_fixture_problem,
    conclusion_cites_premises_and_engine,
    execute_legal_ir_proof,
    expected_fixture_outcome,
    map_proof_engine_status,
    problem_from_mapping,
    run_local_bounded_kernel,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
PRIVATE_CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"


# ---------------------------------------------------------------------------
# Fixtures helpers for Legal IR contracts
# ---------------------------------------------------------------------------


def _source_identity() -> SourceIdentity:
    return SourceIdentity(
        schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        artifact_id="artifact:oa:1",
        content_digest=DIGEST_A,
        media_type="application/pdf",
        private_cid=PRIVATE_CID,
        public_cid=None,
        parser_version="patlaw-126.v1",
        source_receipt_id="receipt:odp:1",
        labels={"doc_code": "CTFR"},
    )


def _temporal() -> TemporalMetadata:
    return TemporalMetadata(
        schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        as_of="2026-08-01",
        effective_start="2024-01-01",
        effective_end=None,
        retrieval_utc="2026-08-03T12:00:00Z",
        edition_or_version="2024-11",
        release_point="rp-2024-11",
        jurisdiction="US",
        labels={},
    )


def _disclosure(
    classification: DisclosureClassification = DisclosureClassification.PUBLIC_OFFICIAL,
) -> DisclosureMetadata:
    return DisclosureMetadata(
        schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        classification=classification,
        quarantine_required=False,
        redaction_policy_id=None,
        labels={},
    )


def _span() -> UsptoSpanRef:
    return UsptoSpanRef(
        schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        span_id="span:1",
        artifact_id="artifact:oa:1",
        page_index=0,
        char_start=10,
        char_end=40,
        text_digest=DIGEST_B,
        image_digest=None,
        reading_order=1,
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
    )


def _authority() -> AuthorityBinding:
    return AuthorityBinding(
        schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        binding_id="auth:1",
        state=AuthorityResolutionState.RESOLVED,
        authority_rank=AuthorityRank.OFFICIAL_BASE,
        temporal=_temporal(),
        citation_ids=("cite:112b",),
        selected_node_ids=("node:35usc112b",),
        selected_versions=("2024-11",),
        reasons=(),
    )


def _proposition(
    proposition_id: str = "prop:1",
    **overrides: object,
) -> NormalizedProposition:
    payload: dict[str, object] = {
        "schema_version": LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        "proposition_id": proposition_id,
        "assertion_kind": AssertionKind.DETERMINISTIC_NORMALIZATION,
        "modality": LegalModality.OBLIGATION,
        "actor_role": ActorRole.APPLICANT,
        "predicate": "amend_claim",
        "subject": "claim:1",
        "object_ref": None,
        "condition_ids": (),
        "exception_ids": (),
        "deadline_ids": (),
        "citation_ids": ("cite:112b",),
        "source_span_ids": ("span:1",),
        "normalizer_id": "norm:uspto-req",
        "normalizer_version": "1.0.0",
        "proposition_digest": DIGEST_C,
        "labels": {},
    }
    payload.update(overrides)
    return NormalizedProposition(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Schema / identity pins
# ---------------------------------------------------------------------------


def test_schema_version_and_interface_pinned() -> None:
    assert LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION == "uspto.legal-ir-proof-executor.v1"
    assert LEGAL_IR_PROOF_EXECUTOR_INTERFACE == "UsptoLegalIRProofExecutor@1"
    assert PROOF_KERNEL_IDENTITY == "uspto.local-bounded-proof-kernel@1"


# ---------------------------------------------------------------------------
# Known fixtures map correctly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        FixtureKind.SATISFIABLE,
        FixtureKind.CONTRADICTORY,
        FixtureKind.INCOMPLETE,
        FixtureKind.TIMEOUT,
    ],
)
def test_known_fixture_outcomes(kind: FixtureKind) -> None:
    executor = LegalIRProofExecutor()
    result = executor.execute_fixture(kind)
    assert result.outcome is expected_fixture_outcome(kind)
    assert result.fixture_kind is kind
    assert result.schema_version == LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION
    assert result.remote_call_count == 0


def test_fixture_satisfiable_is_proved_with_premises_and_engine() -> None:
    result = LegalIRProofExecutor().execute_fixture(FixtureKind.SATISFIABLE)
    assert result.outcome is ProofOutcome.PROVED
    assert result.conclusion.tri_state is TriStateOutcome.SATISFIED
    assert result.conclusion.premise_citations
    assert result.conclusion.engine_config.engine_id == PROOF_KERNEL_IDENTITY
    assert result.conclusion.engine_config.config_digest
    assert result.conclusion.engine_config.config_profile
    assert conclusion_cites_premises_and_engine(result.conclusion)
    assert ProofReasonCode.PREMISES_ENTAIL_GOAL.value in result.conclusion.reason_codes
    assert ProofReasonCode.FIXTURE_SATISFIABLE.value in result.conclusion.reason_codes


def test_fixture_contradictory_is_disproved_with_countermodel() -> None:
    result = LegalIRProofExecutor().execute_fixture(FixtureKind.CONTRADICTORY)
    assert result.outcome is ProofOutcome.DISPROVED
    assert result.conclusion.tri_state is TriStateOutcome.UNSATISFIED
    assert result.conclusion.countermodels
    assert ProofReasonCode.PREMISES_CONTRADICT.value in result.conclusion.reason_codes
    assert result.conclusion.engine_config.engine_id
    assert result.conclusion.engine_config.config_digest


def test_fixture_incomplete_is_unknown() -> None:
    result = LegalIRProofExecutor().execute_fixture(FixtureKind.INCOMPLETE)
    assert result.outcome is ProofOutcome.UNKNOWN
    assert result.conclusion.tri_state is TriStateOutcome.UNKNOWN
    assert ProofReasonCode.INCOMPLETE_PREMISES.value in result.conclusion.reason_codes
    assert result.conclusion.engine_config.config_digest


def test_fixture_timeout_is_timeout() -> None:
    result = LegalIRProofExecutor().execute_fixture(FixtureKind.TIMEOUT)
    assert result.outcome is ProofOutcome.TIMEOUT
    assert ProofReasonCode.TIMEOUT_BUDGET.value in result.conclusion.reason_codes
    assert result.conclusion.engine_config.engine_id == PROOF_KERNEL_IDENTITY


def test_zero_timeout_budget_yields_timeout() -> None:
    problem = ProofProblem(
        problem_id="p:budget",
        logic_family=LogicFamily.ENTAILMENT_CHECK,
        goal=AtomicLiteral("atom:g", True),
        premises=(AtomicLiteral("atom:g", True),),
        required_premise_ids=(),
        assumption_ids=(),
        counter_evidence_ids=(),
        premise_citations=(),
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
    )
    kernel = run_local_bounded_kernel(problem, timeout_ms=0, max_steps=100)
    assert kernel.outcome is ProofOutcome.TIMEOUT


def test_step_budget_exhaustion_timeout() -> None:
    premises = tuple(AtomicLiteral(f"atom:{i}", True) for i in range(50))
    problem = ProofProblem(
        problem_id="p:steps",
        logic_family=LogicFamily.ENTAILMENT_CHECK,
        goal=AtomicLiteral("atom:0", True),
        premises=premises,
        required_premise_ids=(),
        assumption_ids=(),
        counter_evidence_ids=(),
        premise_citations=(),
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
    )
    kernel = run_local_bounded_kernel(problem, timeout_ms=60_000, max_steps=2)
    assert kernel.outcome is ProofOutcome.TIMEOUT


# ---------------------------------------------------------------------------
# Every conclusion cites premises and engine/config identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", list(FixtureKind))
def test_every_conclusion_cites_engine_config(kind: FixtureKind) -> None:
    result = LegalIRProofExecutor().execute_fixture(kind)
    cfg = result.conclusion.engine_config
    assert cfg.engine_id
    assert cfg.config_digest
    assert cfg.config_profile
    assert cfg.route is ExecutionRoute.LOCAL_BOUNDED_KERNEL
    assert cfg.schema_version == LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION
    # Result-level identity matches conclusion identity.
    assert result.engine_config.config_digest == cfg.config_digest
    assert result.engine_config.engine_id == cfg.engine_id


def test_proved_and_disproved_cite_premises() -> None:
    proved = LegalIRProofExecutor().execute_fixture(FixtureKind.SATISFIABLE)
    disproved = LegalIRProofExecutor().execute_fixture(FixtureKind.CONTRADICTORY)
    assert proved.conclusion.premise_citations
    assert disproved.conclusion.premise_citations
    for cite in proved.conclusion.premise_citations:
        assert cite.premise_id
        assert cite.kind


def test_result_to_dict_and_audit_dict_are_structured() -> None:
    result = LegalIRProofExecutor().execute_fixture(FixtureKind.SATISFIABLE)
    payload = result.to_dict()
    assert payload["outcome"] == "proved"
    assert payload["engine_config"]["engine_id"] == PROOF_KERNEL_IDENTITY
    assert payload["conclusion"]["premise_citations"]
    audit = result.audit_dict()
    assert "receipt_id" in audit
    assert audit["remote_call_count"] == 0
    assert "reason_codes" in audit


# ---------------------------------------------------------------------------
# Unsupported / unavailable → unknown
# ---------------------------------------------------------------------------


def test_unsupported_logic_returns_unknown() -> None:
    problem = ProofProblem(
        problem_id="p:unsupported",
        logic_family=LogicFamily.UNSUPPORTED,
        goal=AtomicLiteral("atom:g", True),
        premises=(AtomicLiteral("atom:g", True),),
        required_premise_ids=(),
        assumption_ids=(),
        counter_evidence_ids=(),
        premise_citations=(
            PremiseCitation(premise_id="atom:g", kind="atom", digest=DIGEST_A),
        ),
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
    )
    result = LegalIRProofExecutor().execute(
        ProofExecutionRequest(request_id="req:u", problem=problem)
    )
    assert result.outcome is ProofOutcome.UNKNOWN
    assert ProofReasonCode.UNSUPPORTED_LOGIC.value in result.conclusion.reason_codes


def test_deontic_external_without_engine_returns_unknown() -> None:
    problem = ProofProblem(
        problem_id="p:deontic",
        logic_family=LogicFamily.DEONTIC_EXTERNAL,
        goal=AtomicLiteral("atom:g", True),
        premises=(),
        required_premise_ids=(),
        assumption_ids=(),
        counter_evidence_ids=(),
        premise_citations=(),
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
    )
    result = LegalIRProofExecutor(
        ProofExecutorConfig(allow_external_provers=True)
    ).execute(
        ProofExecutionRequest(
            request_id="req:d",
            problem=problem,
            preferred_route=ExecutionRoute.LOCAL_PROOF_ENGINE,
        )
    )
    assert result.outcome is ProofOutcome.UNKNOWN
    codes = set(result.conclusion.reason_codes)
    assert (
        ProofReasonCode.ENGINE_UNAVAILABLE.value in codes
        or ProofReasonCode.UNSUPPORTED_LOGIC.value in codes
    )


def test_map_proof_engine_status_covers_known_values() -> None:
    assert map_proof_engine_status("success")[0] is ProofOutcome.PROVED
    assert map_proof_engine_status("failure")[0] is ProofOutcome.DISPROVED
    assert map_proof_engine_status("timeout")[0] is ProofOutcome.TIMEOUT
    assert map_proof_engine_status("unsupported")[0] is ProofOutcome.UNKNOWN
    assert map_proof_engine_status("error")[0] is ProofOutcome.ERROR
    assert map_proof_engine_status("weird")[0] is ProofOutcome.UNKNOWN


# ---------------------------------------------------------------------------
# Mapping / compiler adapter
# ---------------------------------------------------------------------------


def test_problem_from_mapping_and_execute() -> None:
    mapping = build_legal_ir_mapping(
        mapping_id="map:proof:1",
        assertion_kind=AssertionKind.DETERMINISTIC_NORMALIZATION,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        citations=(
            CitationRef(
                schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
                citation_id="cite:112b",
                surface="35 U.S.C. 112(b)",
                citation_key="35usc112b",
                authority_rank=AuthorityRank.OFFICIAL_BASE,
                family="usc",
                edition_or_version="2024",
                node_id="node:35usc112b",
                quote_text_digest=DIGEST_B,
                labels={},
            ),
        ),
        authority=_authority(),
        desired_outcome=TriStateOutcome.UNKNOWN,
        confidence=0.9,
        proposition=_proposition("prop:goal"),
        facts=(
            SubmissionFactRef(
                schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
                fact_id="fact:1",
                fact_type="claim_limitation_present",
                evidence_span_id="span:1",
                affected_claims=("1",),
                version="1",
                extraction_status="ok",
                classification=DisclosureClassification.PUBLIC_OFFICIAL,
                assertion_kind=AssertionKind.DETERMINISTIC_NORMALIZATION,
                labels={},
            ),
        ),
        proof_obligation=ProofObligation(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            obligation_id="obl:1",
            proposition_id="prop:goal",
            required_outcome=TriStateOutcome.SATISFIED,
            premise_proposition_ids=("prop:goal",),
            premise_fact_ids=("fact:1",),
            assumption_ids=(),
            proof_receipt_id=None,
            labels={},
        ),
    )
    problem = problem_from_mapping(mapping)
    assert problem.goal is not None
    assert problem.goal.atom_id == "prop:goal"
    assert any(p.atom_id == "fact:1" for p in problem.premises)

    class _StubCompiler:
        def compile(self, source: Any, **kwargs: Any) -> Any:
            return SimpleNamespace(
                successful=True,
                result_id="lir-compiler-result-test",
                status="ok",
                exit_code=0,
                to_dict=lambda: {"ok": True, "source_keys": sorted(source.keys())},
            )

    executor = LegalIRProofExecutor(compiler=_StubCompiler())
    result = executor.execute(
        ProofExecutionRequest(
            request_id="req:map:1",
            mapping=mapping,
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
        )
    )
    assert result.outcome is ProofOutcome.PROVED
    assert result.compilation is not None
    assert result.compilation.successful is True
    assert result.compilation.compiler_options_digest
    assert result.remote_call_count == 0
    assert result.conclusion.premise_citations
    assert result.conclusion.engine_config.config_digest


def test_mapping_with_missing_required_premise_is_unknown() -> None:
    mapping = build_legal_ir_mapping(
        mapping_id="map:incomplete:1",
        assertion_kind=AssertionKind.DETERMINISTIC_NORMALIZATION,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(
            DisclosureClassification.CONFIDENTIAL_APPLICATION
        ),
        source_spans=(_span(),),
        citations=(),
        authority=_authority(),
        desired_outcome=TriStateOutcome.UNKNOWN,
        confidence=None,
        proposition=_proposition("prop:only"),
        facts=(),
        proof_obligation=ProofObligation(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            obligation_id="obl:miss",
            proposition_id="prop:only",
            required_outcome=TriStateOutcome.SATISFIED,
            premise_proposition_ids=("prop:missing",),
            premise_fact_ids=(),
            assumption_ids=(),
            proof_receipt_id=None,
            labels={},
        ),
    )
    result = LegalIRProofExecutor().execute(
        ProofExecutionRequest(request_id="req:miss", mapping=mapping)
    )
    assert result.outcome is ProofOutcome.UNKNOWN
    assert ProofReasonCode.INCOMPLETE_PREMISES.value in result.conclusion.reason_codes


def test_bundle_execution_selects_obligation_mapping() -> None:
    mapping = build_legal_ir_mapping(
        mapping_id="map:bundle:1",
        assertion_kind=AssertionKind.DETERMINISTIC_NORMALIZATION,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        citations=(),
        authority=_authority(),
        desired_outcome=TriStateOutcome.UNKNOWN,
        confidence=None,
        proposition=_proposition("prop:b"),
        facts=(),
        proof_obligation=ProofObligation(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            obligation_id="obl:b",
            proposition_id="prop:b",
            required_outcome=TriStateOutcome.SATISFIED,
            premise_proposition_ids=("prop:b",),
            premise_fact_ids=(),
            assumption_ids=("asm:1",),
            proof_receipt_id=None,
            labels={},
        ),
        assumptions=(
            AssumptionRef(
                schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
                assumption_id="asm:1",
                description_digest=DIGEST_A,
                asserted_by=ActorRole.SYSTEM,
                labels={},
            ),
        ),
    )
    bundle = LegalIRContractBundle(
        schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        bundle_id="bundle:1",
        mappings=(mapping,),
        parser_version="patlaw-126",
        ruleset_version="rules@1",
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        labels={},
    )
    result = LegalIRProofExecutor().execute(
        ProofExecutionRequest(request_id="req:bundle", bundle=bundle)
    )
    assert result.outcome is ProofOutcome.PROVED
    assert "asm:1" in result.conclusion.assumption_ids


def test_counter_evidence_on_goal_disproves() -> None:
    mapping = build_legal_ir_mapping(
        mapping_id="map:counter:1",
        assertion_kind=AssertionKind.DETERMINISTIC_NORMALIZATION,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        citations=(),
        authority=_authority(),
        desired_outcome=TriStateOutcome.UNKNOWN,
        confidence=None,
        proposition=_proposition("prop:g"),
        facts=(
            SubmissionFactRef(
                schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
                fact_id="prop:g",
                fact_type="negation_marker",
                evidence_span_id="span:1",
                affected_claims=(),
                version="1",
                extraction_status="ok",
                classification=DisclosureClassification.PUBLIC_OFFICIAL,
                assertion_kind=AssertionKind.DETERMINISTIC_NORMALIZATION,
                labels={},
            ),
        ),
        counter_evidence=(
            CounterEvidenceRef(
                schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
                counter_id="ctr:1",
                span_ids=("span:1",),
                fact_ids=("prop:g",),
                reason_codes=("contradiction",),
                labels={},
            ),
        ),
        proof_obligation=ProofObligation(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            obligation_id="obl:c",
            proposition_id="prop:g",
            required_outcome=TriStateOutcome.SATISFIED,
            premise_proposition_ids=(),
            premise_fact_ids=(),
            assumption_ids=(),
            proof_receipt_id=None,
            labels={},
        ),
    )
    result = LegalIRProofExecutor().execute(
        ProofExecutionRequest(request_id="req:ctr", mapping=mapping)
    )
    assert result.outcome is ProofOutcome.DISPROVED
    assert result.conclusion.countermodels or (
        ProofReasonCode.PREMISES_CONTRADICT.value in result.conclusion.reason_codes
    )


def test_compiler_failure_is_recorded_but_kernel_still_runs() -> None:
    class _FailingCompiler:
        def compile(self, source: Any, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

    problem = build_fixture_problem(FixtureKind.SATISFIABLE)
    result = LegalIRProofExecutor(compiler=_FailingCompiler()).execute(
        ProofExecutionRequest(
            request_id="req:cfail",
            problem=problem,
            compiler_source={"x": 1},
        )
    )
    # Kernel path still proves the fixture; compile receipt records failure.
    assert result.outcome is ProofOutcome.PROVED
    assert result.compilation is not None
    assert result.compilation.successful is False
    assert ProofReasonCode.COMPILER_FAILED.value in result.compilation.reason_codes


def test_module_level_execute_helper() -> None:
    result = execute_legal_ir_proof(
        ProofExecutionRequest(
            request_id="req:helper",
            fixture_kind=FixtureKind.SATISFIABLE,
        )
    )
    assert result.outcome is ProofOutcome.PROVED


def test_goal_negation_disproves_entailment() -> None:
    problem = ProofProblem(
        problem_id="p:neg",
        logic_family=LogicFamily.ENTAILMENT_CHECK,
        goal=AtomicLiteral("atom:g", True),
        premises=(AtomicLiteral("atom:g", False),),
        required_premise_ids=(),
        assumption_ids=(),
        counter_evidence_ids=(),
        premise_citations=(
            PremiseCitation(premise_id="atom:g", kind="atom"),
        ),
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
    )
    kernel = run_local_bounded_kernel(problem, timeout_ms=1000, max_steps=100)
    assert kernel.outcome is ProofOutcome.DISPROVED
    assert ProofReasonCode.GOAL_NEGATED_BY_PREMISES.value in kernel.reason_codes


def test_config_digest_is_stable() -> None:
    a = ProofExecutorConfig(timeout_ms=1000, max_steps=10)
    b = ProofExecutorConfig(timeout_ms=1000, max_steps=10)
    c = ProofExecutorConfig(timeout_ms=2000, max_steps=10)
    assert a.config_digest() == b.config_digest()
    assert a.config_digest() != c.config_digest()


def test_invalid_request_without_problem_errors() -> None:
    result = LegalIRProofExecutor().execute(
        ProofExecutionRequest(request_id="req:empty")
    )
    assert result.outcome is ProofOutcome.ERROR
    assert ProofReasonCode.INVALID_REQUEST.value in result.conclusion.reason_codes


def test_derivation_steps_recorded_for_satisfiable() -> None:
    result = LegalIRProofExecutor().execute_fixture(FixtureKind.SATISFIABLE)
    assert result.conclusion.derivation_steps
    rules = {d.rule for d in result.conclusion.derivation_steps}
    assert "assert_premise" in rules or "unit_entailment" in rules
