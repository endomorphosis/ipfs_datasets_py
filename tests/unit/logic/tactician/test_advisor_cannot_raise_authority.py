"""LPC-071: Advisors cannot raise proof authority.

Acceptance (all required):

* Advisors cannot mark proposals proved.
* Advisors cannot raise authority.
* Advisors cannot choose verification keys.
* Advisors cannot skip reconstruction.
* Advisors cannot approve production.
* Advisors cannot silently add assumptions.
* Advisors cannot drop blocking obligations.

Coverage spans the domain-neutral tactician surface, software-verification
proposal contracts, candidate portfolio caps, formalization/proposal advisors,
toolchain advisor roles, reconstruction hard-caps, and ranking hard-prunes.
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.backends.advisor_execution_v2 import (
    advisor_never_establishes_proof,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
    role_can_satisfy_certified_authority,
)
from ipfs_datasets_py.logic.formalization.advisor import (
    PROTECTED_SEMANTIC_FIELDS,
    AdviceKind,
    AdvisorCandidate,
    AdvisorConfig,
    AdvisorValidationError,
    BoundedFormalizationAdvisor,
    FormalizationAdvisorRequest,
    FormulaRepair,
    RepairScope,
)
from ipfs_datasets_py.logic.formalization.checkpoints import CheckpointManifest
from ipfs_datasets_py.logic.formalization.compiler import (
    FormalizationArtifact,
    FormalizationCompilerConfig,
)
from ipfs_datasets_py.logic.formalization.features import FormalizationFeatures
from ipfs_datasets_py.logic.formalization.proposal_advisors import (
    UNVERIFIED_AUTHORITY,
    ProposalAdvisorValidationError,
    ProposalCandidate,
    ProposalKind,
    ProposalProvider,
    accept_candidate,
    confidence_never_yields_proof,
)
from ipfs_datasets_py.logic.formalization.views import (
    FormalFormula,
    FormalSymbol,
    FormalizationView,
    SymbolTable,
    ViewRegistry,
)
from ipfs_datasets_py.logic.ir_core.claims import Assumption
from ipfs_datasets_py.logic.ir_core.diagnostics import DiagnosticReport
from ipfs_datasets_py.logic.ir_core.provenance import (
    ConfigBinding,
    ProducerBinding,
    Provenance,
    ProvenanceBinding,
    SourceRef,
    SourceSpan,
)
from ipfs_datasets_py.logic.software_verification.tactician.candidate_synthesis import (
    CandidateSourceKind,
    CandidateTrust,
    is_proposal_only_provider,
    is_proposal_only_source,
    _cap_authority_for_source,
)
from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    AuthorityCeiling,
    CandidateProofStep,
    CandidateStatus,
    GoalDirectedProofPlan,
    PlanStatus,
    ResourceBounds,
    SourceSpanBinding,
    TacticianContractError,
    _PROPOSAL_FORBIDDEN_TRUE_CLAIMS,
)
from ipfs_datasets_py.logic.software_verification.tactician.proof_graph import (
    ReconstructionMethod,
    cap_experimental_authority,
    is_experimental_reconstruction,
)
from ipfs_datasets_py.logic.software_verification.tactician.proof_plan import (
    HardPruneReason,
    MissingProofPlanAlternative,
    ProofPlanRankingPolicy,
    ProofPlanStepSpec,
    StepKind,
    build_missing_proof_plan,
    collect_hard_failures,
    complete_step,
)
from ipfs_datasets_py.logic.tactician import (
    RouteDisposition,
    StopDisposition,
    TacticianGoal,
    TacticianPlan,
    TacticianPolicy,
    TacticianRoute,
    TacticianSource,
    TacticianSubgoal,
    TacticianValidationError,
    default_policy,
)
from ipfs_datasets_py.logic.tactician.receipts import ReceiptError, TacticianReceipt
from ipfs_datasets_py.logic.zkp.ceremony import validate_groth16_mpc_ceremony


# ---------------------------------------------------------------------------
# Shared fixtures / builders
# ---------------------------------------------------------------------------

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
ONTOLOGY_IDENTITY = f"sha256:{SHA_B}"


def _source_binding() -> SourceSpanBinding:
    return SourceSpanBinding(
        tree_id="tree:repo@abc",
        source_ref_ids=("source:lease.py",),
        span_ids=("span:claim",),
        ast_scope_ids=("symbol:claim_lease",),
        snapshot_id="snap:1",
    )


def _bounds(**overrides: Any) -> ResourceBounds:
    payload = {
        "wall_time_ms": 5_000,
        "memory_bytes": 64 * 1024 * 1024,
        "max_steps": 32,
        "max_depth": 8,
        "max_nodes": 64,
        "max_candidates": 16,
        "network_allowed": False,
    }
    payload.update(overrides)
    return ResourceBounds(**payload)


def _candidate(**overrides: Any) -> CandidateProofStep:
    payload: dict[str, Any] = {
        "candidate_id": "cand:inv-a",
        "hole_id": "hole:loop-inv-1",
        "kind": "loop_invariant",
        "statement": "invariant(owner_holds_token)",
        "status": CandidateStatus.PROPOSED,
        "source": _source_binding(),
        "provider_ids": ("advisor:leanstral",),
        "authority": AuthorityCeiling.CANDIDATE,
        "rank_score_millionths": 100,
        "new_assumption_ids": (),
        "evidence_ids": (),
        "proof_claimed": False,
        "completion_claimed": False,
    }
    payload.update(overrides)
    return CandidateProofStep(**payload)


def _plan(**overrides: Any) -> GoalDirectedProofPlan:
    candidates = overrides.pop("candidates", (_candidate(),))
    payload: dict[str, Any] = {
        "plan_id": "plan:lease-1",
        "formal_goal_id": "formal:lease-ready",
        "graph_id": "graph:lease-1",
        "tree_id": "tree:repo@abc",
        "candidates": candidates,
        "step_order": tuple(c.candidate_id for c in candidates),
        "status": PlanStatus.DRAFT,
        "bounds": _bounds(),
        "provider_ids": ("advisor:leanstral",),
        "rank_score_millionths": 0,
        "root_goal_id": "goal:lease-ready",
        "authority": AuthorityCeiling.CANDIDATE,
        "proof_claimed": False,
        "completion_claimed": False,
        "metadata": {},
    }
    payload.update(overrides)
    return GoalDirectedProofPlan(**payload)


def _route() -> TacticianRoute:
    return TacticianRoute(
        route_id="r1",
        source_id="s1",
        source_class="model_hypothesis",
        stage_index=0,
        disposition=RouteDisposition.SELECTED,
        rationale="advisor nomination",
        addresses_gaps=["gap1"],
    )


def _tactician_plan(**overrides: Any) -> TacticianPlan:
    kwargs: dict[str, Any] = {
        "goal_id": "g1",
        "goal_root": "gr",
        "corpus_root": "cr",
        "config_root": "cfg",
        "authority_roots": {"tree": "t1"},
        "policy_id": "p1",
        "planner_id": "planner",
        "selected_routes": [_route()],
        "excluded_routes": [],
        "proof_gaps": ["gap1"],
        "subgoals": [
            TacticianSubgoal(
                subgoal_id="subgoal:gap1",
                parent_goal_id="g1",
                statement_ref="stmt#gap1",
                depends_on=[],
                addresses_gaps=["gap1"],
                rationale="cover",
            )
        ],
        "stop_conditions": ["done"],
        "abstain_conditions": ["authority_promotion_attempt"],
        "stop_disposition": StopDisposition.CONTINUE,
    }
    kwargs.update(overrides)
    return TacticianPlan.build(**kwargs)


def _registry() -> ViewRegistry:
    return ViewRegistry(
        (
            FormalizationView(
                view_id="view:modal",
                logic_family="deontic",
                capabilities=("modality", "typed_symbols"),
            ),
        ),
        registry_id="registry:intent:v1",
    )


def _compiler_config() -> FormalizationCompilerConfig:
    return FormalizationCompilerConfig(
        compiler_id="intent:compiler",
        compiler_version="1",
        config_id="intent:compiler-config",
        producer_id="intent:compiler",
        target_view_ids=("view:modal",),
    )


def _expression(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "operator": "intended",
        "body": {"predicate": "publish", "arguments": ["agent"]},
        "policy": {
            "assumptions": ["actor-exists"],
            "license_expression": "MIT",
            "trust_status": "human_reviewed",
        },
    }
    value.update(changes)
    return value


def _source_map() -> Provenance:
    config = _compiler_config()
    return Provenance(
        provenance_id="intent:provenance:1",
        sources=(
            SourceRef(
                ref_id="source:1",
                source_uri="ipfs://fixture",
                source_id="fixture",
                source_revision="v1",
                content_sha256=SHA_A,
            ),
        ),
        spans=(
            SourceSpan(
                span_id="span:1",
                source_ref_id="source:1",
                start_byte=0,
                end_byte=10,
            ),
        ),
        producers=(
            ProducerBinding(
                producer_id="intent:compiler",
                name="Intent compiler",
                version="1",
            ),
        ),
        configs=(
            ConfigBinding(
                config_id="intent:compiler-config",
                content_sha256=config.identity.hexdigest,
                schema_id=config.schema_version,
            ),
        ),
        bindings=(
            ProvenanceBinding(
                binding_id="binding:sample",
                subject_id="sample:1",
                source_ref_ids=("source:1",),
                span_ids=("span:1",),
            ),
            ProvenanceBinding(
                binding_id="binding:node",
                subject_id="node:goal",
                source_ref_ids=("source:1",),
                span_ids=("span:1",),
            ),
            ProvenanceBinding(
                binding_id="binding:formula",
                subject_id="formula:goal",
                source_ref_ids=("source:1",),
                span_ids=("span:1",),
                producer_id="intent:compiler",
                config_id="intent:compiler-config",
                parent_subject_ids=("node:goal",),
                derived=True,
            ),
        ),
    )


def _artifact() -> FormalizationArtifact:
    source_map = _source_map()
    return FormalizationArtifact(
        sample_id="sample:1",
        domain="intent",
        declaration_id="node:goal",
        declaration_digest=f"sha256:{SHA_A}",
        compiler_config=_compiler_config(),
        view_registry=_registry(),
        symbol_table=SymbolTable(
            table_id="symbols:1",
            symbols=(
                FormalSymbol(
                    symbol_id="symbol:actor",
                    name="agent",
                    kind="constant",
                    sort="principal",
                    source_ref_ids=("source:1",),
                    span_ids=("span:1",),
                ),
                FormalSymbol(
                    symbol_id="symbol:publish",
                    name="publish",
                    kind="predicate",
                    sort="action",
                    source_ref_ids=("source:1",),
                    span_ids=("span:1",),
                ),
            ),
        ),
        formulas=(
            FormalFormula(
                formula_id="formula:goal",
                view_id="view:modal",
                expression=_expression(),
                symbol_ids=("symbol:actor", "symbol:publish"),
                source_ref_ids=("source:1",),
                span_ids=("span:1",),
                assumption_ids=("assumption:1",),
                input_node_ids=("node:goal",),
                metadata={"review_status": "human_reviewed"},
            ),
        ),
        cross_view_links=(),
        assumptions=(
            Assumption(
                assumption_id="assumption:1",
                statement="the actor exists",
                source_refs=("source:1",),
            ),
        ),
        proof_obligations=(),
        source_map=source_map,
        diagnostics=DiagnosticReport(
            report_id="diagnostics:1",
            diagnostics=(),
            provenance_id=source_map.provenance_id,
        ),
        metadata={
            "license_expression": "MIT",
            "trust_status": "human_reviewed",
        },
    )


def _features() -> FormalizationFeatures:
    return FormalizationFeatures.from_values(
        sample_id="sample:1",
        domain="intent",
        declaration_digest=f"sha256:{SHA_A}",
        features={
            "statement.count": 1.0,
            "statement.modality.intended.count": 1.0,
        },
        extractor_id="intent:feature-extractor",
        extractor_version="1",
    )


def _checkpoint() -> CheckpointManifest:
    return CheckpointManifest(
        checkpoint_id="intent:checkpoint:advisor-v1",
        domain="intent",
        head_id="intent:head:formula",
        model_id="shared:formalization-encoder",
        model_version="1",
        weights_digest=f"sha256:{SHA_C}",
        training_config_identity=f"sha256:{SHA_A}",
        ontology_identity=ONTOLOGY_IDENTITY,
        view_registry_identity=_registry().identity.digest,
        feature_schema_version=_features().schema_version,
    )


def _advisor_request(**changes: object) -> FormalizationAdvisorRequest:
    values: dict[str, object] = {
        "artifact": _artifact(),
        "features": _features(),
        "checkpoint": _checkpoint(),
        "ontology_identity": ONTOLOGY_IDENTITY,
        "repair_scope": RepairScope(
            formula_ids=("formula:goal",),
            allowed_paths=("/body/predicate",),
            max_operations=1,
        ),
    }
    values.update(changes)
    return FormalizationAdvisorRequest(**values)  # type: ignore[arg-type]


class _FakeModel:
    def __init__(self, output: object) -> None:
        self.output = output

    def generate_candidates(self, request):  # noqa: ANN001
        del request
        return self.output


def _formalization_advisor(output: object) -> BoundedFormalizationAdvisor:
    return BoundedFormalizationAdvisor(
        _FakeModel(output),
        AdvisorConfig(advisor_id="advisor:generic", advisor_version="1"),
    )


def _proposal_candidate(**overrides: Any) -> ProposalCandidate:
    payload: dict[str, Any] = {
        "candidate_id": "candidate:lemma-1",
        "kind": ProposalKind.LEMMA,
        "body": "lemma helper : True := trivial",
        "source_ref_ids": ("source:1",),
        "provider": ProposalProvider.LEANSTRAL,
        "confidence": 0.99,
        "rationale": "high confidence nomination",
        "metadata": {},
        "authority": UNVERIFIED_AUTHORITY,
    }
    payload.update(overrides)
    return ProposalCandidate(**payload)


# ---------------------------------------------------------------------------
# 1. Cannot mark proposals proved
# ---------------------------------------------------------------------------


def test_candidate_and_plan_cannot_mark_proved() -> None:
    with pytest.raises(TacticianContractError, match="cannot claim"):
        _candidate(proof_claimed=True)
    with pytest.raises(TacticianContractError, match="cannot claim"):
        _plan(proof_claimed=True)
    with pytest.raises(TacticianContractError, match="cannot claim"):
        _plan(completion_claimed=True)

    payload = _candidate().to_dict()
    payload["proof_claimed"] = True
    with pytest.raises(TacticianContractError, match="cannot claim"):
        CandidateProofStep.from_dict(payload)

    plan_payload = _plan().to_dict()
    plan_payload["proved"] = True
    with pytest.raises(TacticianContractError, match="cannot claim"):
        GoalDirectedProofPlan.from_dict(plan_payload)


def test_tactician_plan_and_receipt_cannot_hold_semantic_authority() -> None:
    plan = _tactician_plan()
    assert plan.semantic_authority is False
    with pytest.raises(TacticianValidationError, match="semantic_authority"):
        bad = TacticianPlan(
            plan_id=plan.plan_id,
            goal_id=plan.goal_id,
            goal_root=plan.goal_root,
            corpus_root=plan.corpus_root,
            config_root=plan.config_root,
            authority_roots=plan.authority_roots,
            policy_id=plan.policy_id,
            planner_id=plan.planner_id,
            selected_routes=plan.selected_routes,
            excluded_routes=plan.excluded_routes,
            proof_gaps=plan.proof_gaps,
            subgoals=plan.subgoals,
            stop_conditions=plan.stop_conditions,
            abstain_conditions=plan.abstain_conditions,
            stop_disposition=plan.stop_disposition,
            semantic_authority=True,
        )
        bad.validate()

    policy = default_policy()
    receipt = TacticianReceipt.from_plan(plan, policy)
    assert receipt.semantic_authority is False
    with pytest.raises(ReceiptError, match="semantic_authority"):
        TacticianReceipt(
            receipt_id=receipt.receipt_id,
            plan=receipt.plan,
            policy_digest=receipt.policy_digest,
            planner_id=receipt.planner_id,
            semantic_authority=True,
        ).validate()


def test_proposal_forbidden_true_claims_cover_proof_vocabulary() -> None:
    required = {
        "proof_claimed",
        "proved",
        "complete",
        "completion_claimed",
        "kernel_verified",
        "admitted",
    }
    assert required.issubset(_PROPOSAL_FORBIDDEN_TRUE_CLAIMS)


def test_ranking_hard_prunes_proof_claims_on_steps() -> None:
    step = complete_step(
        "step:1",
        "obl:required",
        authority=AuthorityCeiling.BOUNDED,
        root=True,
    )
    # Bypass complete_step defaults to simulate an advisor-forged proof claim.
    forged = ProofPlanStepSpec(
        step_id=step.step_id,
        obligation_id=step.obligation_id,
        kind=step.kind,
        statement=step.statement,
        dependencies=step.dependencies,
        expected_receipts=step.expected_receipts,
        validation=step.validation,
        fallback=step.fallback,
        resources=step.resources,
        completion_conditions=step.completion_conditions,
        authority=step.authority,
        proof_claimed=True,
        metadata=step.metadata,
    )
    plan = MissingProofPlanAlternative(
        plan_id="plan:forged",
        formal_goal_id="formal:1",
        graph_id="graph:1",
        tree_id="tree:1",
        steps=(forged,),
        covered_obligation_ids=("obl:required",),
        required_obligation_ids=("obl:required",),
        proof_claimed=False,
    )
    failures = collect_hard_failures(plan, ProofPlanRankingPolicy())
    assert any(item.reason is HardPruneReason.PROOF_CLAIM for item in failures)


# ---------------------------------------------------------------------------
# 2. Cannot raise authority
# ---------------------------------------------------------------------------


def test_candidate_authority_capped_and_learned_sources_proposal_only() -> None:
    with pytest.raises(TacticianContractError, match="capped at candidate"):
        _candidate(authority=AuthorityCeiling.THEOREM)
    with pytest.raises(TacticianContractError, match="capped at candidate"):
        _candidate(authority=AuthorityCeiling.RECONSTRUCTION)
    with pytest.raises(TacticianContractError, match="theorem or attestation"):
        _plan(authority=AuthorityCeiling.THEOREM)
    with pytest.raises(TacticianContractError, match="theorem or attestation"):
        _plan(authority=AuthorityCeiling.ATTESTATION)

    assert is_proposal_only_source(CandidateSourceKind.LEARNED_LEANSTRAL)
    assert is_proposal_only_provider("advisor:leanstral")
    assert (
        _cap_authority_for_source(
            CandidateSourceKind.LEARNED_MODEL, AuthorityCeiling.THEOREM
        )
        is AuthorityCeiling.CANDIDATE
    )
    assert (
        _cap_authority_for_source(
            CandidateSourceKind.LEARNED_AUTOENCODER,
            AuthorityCeiling.ATTESTATION,
        )
        is AuthorityCeiling.CANDIDATE
    )


def test_advisor_role_and_confidence_never_raise_authority() -> None:
    assert (
        role_can_satisfy_certified_authority(
            ToolRole.ADVISOR, ToolchainAuthorityCeiling.ADVISORY
        )
        is False
    )
    assert (
        role_can_satisfy_certified_authority(
            ToolRole.ADVISOR, ToolchainAuthorityCeiling.KERNEL
        )
        is False
    )
    assert advisor_never_establishes_proof(confidence=1.0, parse_ok=True) is False
    assert confidence_never_yields_proof(confidence=1.0, is_valid=True) is False

    candidate = _proposal_candidate(confidence=1.0)
    assert candidate.is_proved is False
    assert candidate.authority == UNVERIFIED_AUTHORITY
    with pytest.raises(ProposalAdvisorValidationError, match="cannot claim authority"):
        _proposal_candidate(authority="theorem")

    # High confidence alone cannot admit a candidate.
    rejected = accept_candidate(
        candidate, compiled=False, independently_validated=False
    )
    assert rejected.accepted is False
    assert rejected.authority == UNVERIFIED_AUTHORITY


def test_tactician_policy_rejects_capability_and_authority_promotion() -> None:
    with pytest.raises(TacticianValidationError):
        TacticianPolicy(policy_id="p1", semantic_authority=True).validate()
    with pytest.raises(TacticianValidationError):
        TacticianPolicy(policy_id="p1", proof_execution_allowed=True).validate()
    with pytest.raises(TacticianValidationError):
        TacticianPolicy(policy_id="p1", write_allowed=True).validate()
    with pytest.raises(TacticianValidationError):
        TacticianPolicy(policy_id="p1", network_allowed=True).validate()

    with pytest.raises(TacticianValidationError, match="authority promotion"):
        TacticianGoal(
            goal_id="g1",
            statement_ref="s1",
            goal_family="family",
            goal_root="g",
            corpus_root="c",
            config_root="cfg",
            metadata={"proof_authority": True},
        ).validate()
    with pytest.raises(TacticianValidationError, match="authority promotion"):
        TacticianSource(
            source_id="s1",
            source_class="model_hypothesis",
            precedence=0,
            rationale="r",
            metadata={"semantic_authority": True},
        ).validate()


# ---------------------------------------------------------------------------
# 3. Cannot choose verification keys
# ---------------------------------------------------------------------------


def test_proposals_cannot_smuggle_verification_keys() -> None:
    plan_payload = _plan().to_dict()
    plan_payload["verification_key_id"] = "vk:advisor-chosen"
    with pytest.raises(TacticianContractError, match="unsupported fields"):
        GoalDirectedProofPlan.from_dict(plan_payload)

    candidate_payload = _candidate().to_dict()
    candidate_payload["verification_key"] = {"path": "/tmp/advisor.vk"}
    with pytest.raises(TacticianContractError, match="unsupported fields"):
        CandidateProofStep.from_dict(candidate_payload)

    with pytest.raises(ProposalAdvisorValidationError, match="authority"):
        _proposal_candidate(metadata={"verification_status": "verified"})
    with pytest.raises(ProposalAdvisorValidationError, match="authority"):
        _proposal_candidate(metadata={"verification_result": "ok"})
    with pytest.raises(ProposalAdvisorValidationError, match="authority"):
        _proposal_candidate(metadata={"proof_status": "proved"})


def test_advisor_claims_do_not_select_production_verification_keys() -> None:
    # An advisor-shaped empty ceremony cannot become production-eligible or
    # choose a verification key merely by asserting completeness.
    result = validate_groth16_mpc_ceremony(
        {
            "status": "complete",
            "verificationKey": {"path": "advisor-chosen.vkey", "sha256": "not-a-hash"},
            "contributions": (),
        }
    )
    assert result.production_eligible is False
    assert result.valid is False or result.reasons


# ---------------------------------------------------------------------------
# 4. Cannot skip reconstruction
# ---------------------------------------------------------------------------


def test_experimental_reconstruction_cannot_skip_to_trusted_authority() -> None:
    assert is_experimental_reconstruction(ReconstructionMethod.STRING_EQUALITY)
    assert is_experimental_reconstruction(ReconstructionMethod.EXPERIMENTAL_CEC)
    assert is_experimental_reconstruction(
        ReconstructionMethod.FORWARD_RULE_APPLICATION
    )
    assert not is_experimental_reconstruction(ReconstructionMethod.KERNEL)
    assert not is_experimental_reconstruction(ReconstructionMethod.SOURCE_VC)

    # Advisor/experimental paths that claim theorem authority are demoted.
    assert (
        cap_experimental_authority(AuthorityCeiling.THEOREM)
        is AuthorityCeiling.CANDIDATE
    )
    assert (
        cap_experimental_authority(AuthorityCeiling.RECONSTRUCTION)
        is AuthorityCeiling.CANDIDATE
    )
    assert (
        cap_experimental_authority(AuthorityCeiling.ADVISORY)
        is AuthorityCeiling.ADVISORY
    )


def test_ranking_rejects_insufficient_authority_for_reconstruction_floor() -> None:
    step = complete_step(
        "step:adv",
        "obl:kernel",
        authority=AuthorityCeiling.CANDIDATE,
        provider_ids=("advisor:model",),
        root=True,
    )
    plan = build_missing_proof_plan(
        "plan:skip-recon",
        formal_goal_id="formal:1",
        graph_id="graph:1",
        tree_id="tree:1",
        steps=(step,),
        required_obligation_ids=("obl:kernel",),
        covered_obligation_ids=("obl:kernel",),
    )
    policy = ProofPlanRankingPolicy(minimum_authority=AuthorityCeiling.RECONSTRUCTION)
    failures = collect_hard_failures(plan, policy)
    assert any(
        item.reason is HardPruneReason.INSUFFICIENT_AUTHORITY for item in failures
    )


# ---------------------------------------------------------------------------
# 5. Cannot approve production
# ---------------------------------------------------------------------------


def test_plans_cannot_approve_production_via_metadata_or_capabilities() -> None:
    with pytest.raises(TacticianContractError, match="metadata"):
        _plan(metadata={"complete": True})
    with pytest.raises(TacticianContractError, match="metadata"):
        _plan(metadata={"proved": True})

    policy = default_policy()
    assert policy.network_allowed is False
    assert policy.write_allowed is False
    assert policy.proof_execution_allowed is False
    assert policy.semantic_authority is False
    assert "authority_promotion_attempt" in policy.abstain_conditions

    # Plan status vocabulary has no self-complete / production-approved terminal.
    assert "COMPLETE" not in PlanStatus.__members__
    assert "PROVED" not in PlanStatus.__members__
    assert "PRODUCTION" not in PlanStatus.__members__


def test_advisor_acceptance_is_not_production_approval() -> None:
    candidate = _proposal_candidate()
    staged = accept_candidate(
        candidate, compiled=True, independently_validated=True
    )
    assert staged.accepted is True
    # Even staged acceptance is not theorem / production authority.
    assert staged.authority == "candidate_admitted_for_validation"
    assert staged.authority != "theorem"
    assert staged.authority != "production_approved"

    with pytest.raises(ProposalAdvisorValidationError, match="proof authority"):
        from ipfs_datasets_py.logic.formalization.proposal_advisors import (
            ProposalAcceptance,
        )

        ProposalAcceptance(
            candidate_id=candidate.candidate_id,
            accepted=True,
            compiled=True,
            independently_validated=True,
            authority="production_approved",
        )


# ---------------------------------------------------------------------------
# 6. Cannot silently add assumptions
# ---------------------------------------------------------------------------


def test_formalization_advisor_cannot_silently_add_assumptions() -> None:
    assert "assumptions" in PROTECTED_SEMANTIC_FIELDS
    assert "assumption_ids" in PROTECTED_SEMANTIC_FIELDS
    assert "provenance" in PROTECTED_SEMANTIC_FIELDS
    assert "trust_status" in PROTECTED_SEMANTIC_FIELDS

    advisor = _formalization_advisor(
        (
            AdvisorCandidate(
                candidate_id="candidate:unsafe-assumption",
                kind=AdviceKind.REPAIR,
                repairs=(
                    FormulaRepair(
                        formula_id="formula:goal",
                        path="/policy/assumptions/0",
                        replacement="model-invented-axiom",
                    ),
                ),
            ),
        )
    )
    with pytest.raises(AdvisorValidationError, match="cannot alter"):
        advisor.advise(
            _advisor_request(
                repair_scope=RepairScope(
                    formula_ids=("formula:goal",),
                    allowed_paths=("/policy/assumptions/0",),
                    max_operations=1,
                )
            )
        )


def test_new_assumptions_must_be_explicit_and_bounded() -> None:
    # Explicit listing is allowed; silent free-form smuggling is not.
    explicit = _candidate(new_assumption_ids=("assumption:frame_closed",))
    assert explicit.new_assumption_ids == ("assumption:frame_closed",)
    assert explicit.proof_claimed is False

    steps = (
        complete_step(
            "step:1",
            "obl:a",
            root=True,
            new_assumption_ids=tuple(f"assumption:{i}" for i in range(5)),
        ),
    )
    plan = build_missing_proof_plan(
        "plan:assumptions",
        formal_goal_id="formal:1",
        graph_id="graph:1",
        tree_id="tree:1",
        steps=steps,
        required_obligation_ids=("obl:a",),
        covered_obligation_ids=("obl:a",),
    )
    assert len(plan.new_assumption_ids) == 5
    policy = ProofPlanRankingPolicy(max_new_assumptions=2)
    failures = collect_hard_failures(plan, policy)
    assert any("max_new_assumptions_exceeded" in item.reason_codes for item in failures)


# ---------------------------------------------------------------------------
# 7. Cannot drop blocking obligations
# ---------------------------------------------------------------------------


def test_ranking_cannot_drop_required_blocking_obligations() -> None:
    # Advisor proposes a plan that covers only a non-blocking obligation.
    plan = build_missing_proof_plan(
        "plan:drop-blocking",
        formal_goal_id="formal:1",
        graph_id="graph:1",
        tree_id="tree:1",
        steps=(
            complete_step(
                "step:easy",
                "obl:easy",
                root=True,
                authority=AuthorityCeiling.BOUNDED,
            ),
        ),
        required_obligation_ids=("obl:blocking", "obl:easy"),
        covered_obligation_ids=("obl:easy",),
    )
    failures = collect_hard_failures(plan, ProofPlanRankingPolicy())
    assert any(item.reason is HardPruneReason.MISSING_COVERAGE for item in failures)
    assert any(
        "uncovered:obl:blocking" in code
        for item in failures
        for code in item.reason_codes
    )


def test_incomplete_steps_and_missing_fallbacks_are_hard_pruned() -> None:
    incomplete = ProofPlanStepSpec(
        step_id="step:incomplete",
        obligation_id="obl:blocking",
        kind=StepKind.SOLVE,
        statement="pretend closed",
        dependencies=(),
        expected_receipts=(),
        validation=(),
        fallback=(),
        resources=(),
        completion_conditions=(),
        authority=AuthorityCeiling.CANDIDATE,
        metadata={"root": True},
    )
    plan = MissingProofPlanAlternative(
        plan_id="plan:incomplete",
        formal_goal_id="formal:1",
        graph_id="graph:1",
        tree_id="tree:1",
        steps=(incomplete,),
        covered_obligation_ids=("obl:blocking",),
        required_obligation_ids=("obl:blocking",),
    )
    failures = collect_hard_failures(plan, ProofPlanRankingPolicy())
    assert any(item.reason is HardPruneReason.INCOMPLETE_STEP for item in failures)
    # Dropping validation / fallback / receipts cannot be compensated by ranking.
    codes = {code for item in failures for code in item.reason_codes}
    assert "missing_expected_receipts" in codes
    assert "missing_validation" in codes
    assert "missing_fallback" in codes


def test_tactician_plan_retains_blocking_subgoals_and_gaps() -> None:
    plan = _tactician_plan()
    assert "gap1" in plan.proof_gaps
    assert any(sg.subgoal_id == "subgoal:gap1" for sg in plan.subgoals)
    # Content identity changes if a blocking gap is dropped — advisors cannot
    # rewrite the body while keeping the same plan_id.
    dropped = _tactician_plan(proof_gaps=[], subgoals=[])
    assert dropped.plan_id != plan.plan_id
    assert dropped.proof_gaps == []


# ---------------------------------------------------------------------------
# Combined acceptance surface
# ---------------------------------------------------------------------------


def test_lpc071_acceptance_surface_is_proposal_only_end_to_end() -> None:
    """Single integrated check of the seven forbidden actions."""

    # 1–2. proved + raised authority rejected on the proposal plan surface.
    with pytest.raises(TacticianContractError):
        _candidate(proof_claimed=True, authority=AuthorityCeiling.THEOREM)

    # 3. verification key smuggling rejected.
    payload = _plan().to_dict()
    payload["verification_key_id"] = "vk:self"
    with pytest.raises(TacticianContractError):
        GoalDirectedProofPlan.from_dict(payload)

    # 4. reconstruction skip demoted / hard-pruned.
    assert (
        cap_experimental_authority(AuthorityCeiling.THEOREM)
        is AuthorityCeiling.CANDIDATE
    )

    # 5. production capabilities closed on the tactician policy.
    policy = default_policy()
    assert policy.proof_execution_allowed is False

    # 6. silent assumption mutation rejected by formalization advisor.
    advisor = _formalization_advisor(
        (
            AdvisorCandidate(
                candidate_id="candidate:ax",
                kind=AdviceKind.REPAIR,
                repairs=(
                    FormulaRepair(
                        formula_id="formula:goal",
                        path="/policy/assumptions/0",
                        replacement="silent-axiom",
                    ),
                ),
            ),
        )
    )
    with pytest.raises(AdvisorValidationError):
        advisor.advise(
            _advisor_request(
                repair_scope=RepairScope(
                    formula_ids=("formula:goal",),
                    allowed_paths=("/policy/assumptions/0",),
                    max_operations=1,
                )
            )
        )

    # 7. dropping a blocking obligation hard-prunes the ranked alternative.
    plan = build_missing_proof_plan(
        "plan:e2e",
        formal_goal_id="formal:1",
        graph_id="graph:1",
        tree_id="tree:1",
        steps=(complete_step("step:1", "obl:other", root=True),),
        required_obligation_ids=("obl:blocking",),
        covered_obligation_ids=("obl:other",),
    )
    failures = collect_hard_failures(plan, ProofPlanRankingPolicy())
    assert any(item.reason is HardPruneReason.MISSING_COVERAGE for item in failures)

    # Advisor toolchain cannot certify regardless of confidence.
    assert advisor_never_establishes_proof(confidence=1.0) is False
    assert CandidateTrust.LEARNED_PROPOSAL.value == "learned_proposal"
