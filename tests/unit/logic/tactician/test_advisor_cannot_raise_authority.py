"""LPC-071: advisors cannot raise proof authority from proposals.

Acceptance (all required):

* Advisors cannot mark proposals proved.
* Advisors cannot raise authority.
* Advisors cannot choose verification keys.
* Advisors cannot skip reconstruction.
* Advisors cannot approve production.
* Advisors cannot silently add assumptions.
* Advisors cannot drop blocking obligations.

Live enforcement anchors include domain-neutral tactician models, software-
verification proposal contracts, formalization proposal advisors, toolchain
roles, and catalog production floors.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

import pytest

from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
    ToolchainRoleError,
    FormalVerificationToolRole,
    role_can_satisfy_certified_authority,
)
from ipfs_datasets_py.logic.families.canonical_catalog import (
    DEFAULT_CANONICAL_CATALOG_SNAPSHOT,
)
from ipfs_datasets_py.logic.formalization.proposal_advisors import (
    UNVERIFIED_AUTHORITY,
    ProposalAdvisorValidationError,
    ProposalCandidate,
    ProposalKind,
    ProposalProvider,
    accept_candidate,
    confidence_never_yields_proof,
)
from ipfs_datasets_py.logic.formalization.samples import (
    FormalizationValidationError,
)
from ipfs_datasets_py.logic.software_verification.tactician.candidate_synthesis import (
    CandidateProposal,
    CandidateSourceKind,
    CandidateSynthesisError,
    CandidateTrust,
    is_proposal_only_source,
)
from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    AuthorityCeiling,
    CandidateProofStep,
    CandidateStatus,
    EndGoalSpec,
    GoalCompletion,
    CompletionVerdict,
    ProofHole,
    HoleKind,
    PropertyClass,
    ResourceBounds,
    SourceSpanBinding,
    TacticianContractError,
    AmbiguityStatus,
)
from ipfs_datasets_py.logic.software_verification.tactician.proof_plan import (
    HardPruneReason,
    MissingProofPlanAlternative,
    ProofPlanRankingPolicy,
    ProofPlanStepSpec,
    StepKind,
    collect_hard_failures,
)
from ipfs_datasets_py.logic.tactician import (
    LogicTactician,
    ReceiptError,
    RouteDisposition,
    StopDisposition,
    TacticianGoal,
    TacticianPlan,
    TacticianPolicy,
    TacticianReceipt,
    TacticianRoute,
    TacticianSource,
    TacticianSubgoal,
    TacticianValidationError,
    default_policy,
)


# ---------------------------------------------------------------------------
# Proposal-envelope policy (fail closed; mirrors notes/advisor_authority.md)
# ---------------------------------------------------------------------------

_ADVISOR_ALLOWED_AUTHORITIES: Final[frozenset[str]] = frozenset(
    {
        "none",
        "advisory",
        "candidate",
        UNVERIFIED_AUTHORITY,
        "candidate_admitted_for_validation",
    }
)

_FORBIDDEN_TRUE_CLAIMS: Final[frozenset[str]] = frozenset(
    {
        "proof_claimed",
        "completion_claimed",
        "proved",
        "complete",
        "semantic_authority",
        "production_approved",
        "skip_reconstruction",
        "reconstruction_skipped",
        "kernel_verified",
        "admitted",
    }
)

_VERIFICATION_KEY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "verification_key_id",
        "verification_key",
        "vk_id",
        "verifying_key_cid",
        "verification_key_digest",
    }
)


@dataclass(frozen=True)
class AdvisorProposalEnvelope:
    """Minimal proposal envelope used to exercise LPC-071 admission rules."""

    proposal_id: str
    authority: str = UNVERIFIED_AUTHORITY
    proof_claimed: bool = False
    completion_claimed: bool = False
    semantic_authority: bool = False
    verification_key_id: str = ""
    skip_reconstruction: bool = False
    production_approved: bool = False
    declared_assumptions: tuple[str, ...] = ()
    introduced_assumptions: tuple[str, ...] = ()
    required_blocking_obligations: tuple[str, ...] = ()
    covered_obligations: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "authority": self.authority,
            "proof_claimed": self.proof_claimed,
            "completion_claimed": self.completion_claimed,
            "semantic_authority": self.semantic_authority,
            "verification_key_id": self.verification_key_id,
            "skip_reconstruction": self.skip_reconstruction,
            "production_approved": self.production_approved,
            "declared_assumptions": list(self.declared_assumptions),
            "introduced_assumptions": list(self.introduced_assumptions),
            "required_blocking_obligations": list(
                self.required_blocking_obligations
            ),
            "covered_obligations": list(self.covered_obligations),
            "metadata": dict(self.metadata),
        }


def advisor_proposal_rejection_reasons(
    envelope: AdvisorProposalEnvelope,
    *,
    reconstruction_required: bool = True,
) -> tuple[str, ...]:
    """Return stable reason codes for every LPC-071 violation on ``envelope``.

    Fail closed: an empty reason tuple means the envelope stayed within the
    advisor ceiling (it is still not a proof).
    """

    reasons: list[str] = []
    payload = envelope.to_dict()

    if envelope.proof_claimed or payload.get("proved") is True:
        reasons.append("advisor_marked_proposal_proved")
    if envelope.completion_claimed:
        reasons.append("advisor_marked_proposal_complete")
    if envelope.semantic_authority:
        reasons.append("advisor_raised_semantic_authority")
    if str(envelope.authority).strip().lower() not in _ADVISOR_ALLOWED_AUTHORITIES:
        reasons.append("advisor_raised_authority_ceiling")

    for key in _FORBIDDEN_TRUE_CLAIMS:
        value = envelope.metadata.get(key, payload.get(key))
        if value is True or (
            isinstance(value, str)
            and value.strip().lower() in {"true", "yes", "proved", "complete", "1"}
        ):
            reasons.append(f"forbidden_true_claim:{key}")

    for key in _VERIFICATION_KEY_FIELDS:
        chosen = envelope.metadata.get(key, "")
        if key == "verification_key_id":
            chosen = chosen or envelope.verification_key_id
        if isinstance(chosen, str) and chosen.strip():
            reasons.append("advisor_chose_verification_key")
            break

    if reconstruction_required and (
        envelope.skip_reconstruction
        or envelope.metadata.get("skip_reconstruction") is True
        or envelope.metadata.get("reconstruction_skipped") is True
    ):
        reasons.append("advisor_skipped_reconstruction")

    if envelope.production_approved or envelope.metadata.get(
        "production_approved"
    ) is True:
        reasons.append("advisor_approved_production")

    declared = {item.strip() for item in envelope.declared_assumptions if item.strip()}
    for assumption_id in envelope.introduced_assumptions:
        text = assumption_id.strip()
        if text and text not in declared:
            reasons.append(f"silent_assumption:{text}")

    required = {
        item.strip()
        for item in envelope.required_blocking_obligations
        if item.strip()
    }
    covered = {
        item.strip() for item in envelope.covered_obligations if item.strip()
    }
    for obligation_id in sorted(required - covered):
        reasons.append(f"dropped_blocking_obligation:{obligation_id}")

    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            ordered.append(reason)
    return tuple(ordered)


def advisor_proposal_is_admissible(
    envelope: AdvisorProposalEnvelope,
    *,
    reconstruction_required: bool = True,
) -> bool:
    """True only when the proposal stays within the advisor authority ceiling."""

    return not advisor_proposal_rejection_reasons(
        envelope, reconstruction_required=reconstruction_required
    )


def _note_path() -> Path:
    """Resolve the LPC-071 authority note from monorepo or nested layouts."""

    note_relative = Path(
        "data/agent_supervisor/logic_platform_canonicalization/notes/"
        "advisor_authority.md"
    )
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / note_relative
        if candidate.is_file():
            return candidate
    # tests/unit/logic/tactician → five parents reaches the monorepo root.
    return here.parents[5] / note_relative


def _source_binding() -> SourceSpanBinding:
    return SourceSpanBinding(
        tree_id="tree:lpc-071",
        source_ref_ids=("source:module.py",),
        span_ids=("span:goal",),
        ast_scope_ids=("symbol:f",),
        snapshot_id="snap:1",
    )


def _bounds() -> ResourceBounds:
    return ResourceBounds(
        wall_time_ms=1_000,
        memory_bytes=16 * 1024 * 1024,
        max_steps=8,
        max_depth=4,
        max_nodes=16,
        max_candidates=4,
        network_allowed=False,
    )


def _baseline_goal() -> TacticianGoal:
    policy = default_policy(policy_id="policy:lpc-071")
    return TacticianGoal(
        goal_id="goal:lpc-071",
        statement_ref="stmt:lpc-071",
        goal_family="advisor_authority",
        goal_root="goal-root:lpc-071",
        corpus_root="corpus-root:lpc-071",
        config_root=policy.policy_id,
        authority_roots={"tree": "tree:lpc-071", "policy": "policy:lpc-071"},
        proof_gaps=["blocking:gap-a", "blocking:gap-b"],
        assumptions=["assume:explicit-only"],
    )


def _baseline_sources() -> list[TacticianSource]:
    return [
        TacticianSource(
            source_id="src:contract",
            source_class="authoritative_contract",
            precedence=1,
            rationale="reviewed contract",
            query_hints=["signature"],
        ),
        TacticianSource(
            source_id="src:model",
            source_class="model_hypothesis",
            precedence=5,
            rationale="advisor nomination only",
            query_hints=["maybe lemma"],
            metadata={"role": "advisor"},
        ),
    ]


def _candidate_step(
    *,
    authority: AuthorityCeiling = AuthorityCeiling.CANDIDATE,
    proof_claimed: bool = False,
    completion_claimed: bool = False,
    new_assumption_ids: Sequence[str] = (),
) -> CandidateProofStep:
    return CandidateProofStep(
        candidate_id="candidate:lpc-071",
        hole_id="hole:lpc-071",
        kind="lemma",
        statement="candidate lemma body",
        status=CandidateStatus.PROPOSED,
        source=_source_binding(),
        provider_ids=("provider.leanstral",),
        authority=authority,
        new_assumption_ids=tuple(new_assumption_ids),
        proof_claimed=proof_claimed,
        completion_claimed=completion_claimed,
    )


# ---------------------------------------------------------------------------
# Note + envelope policy
# ---------------------------------------------------------------------------


def test_advisor_authority_note_documents_all_acceptance_criteria() -> None:
    note = _note_path().read_text(encoding="utf-8")
    assert "LPC-071" in note
    required_phrases = (
        "mark proposals proved",
        "raise authority",
        "verification keys",
        "skip reconstruction",
        "approve production",
        "silently add assumptions",
        "drop blocking obligations",
    )
    lowered = note.lower()
    for phrase in required_phrases:
        assert phrase in lowered, f"note missing acceptance phrase: {phrase}"


def test_admissible_advisor_envelope_stays_proposal_only() -> None:
    envelope = AdvisorProposalEnvelope(
        proposal_id="proposal:ok",
        declared_assumptions=("assume:explicit-only",),
        introduced_assumptions=("assume:explicit-only",),
        required_blocking_obligations=("obl:a", "obl:b"),
        covered_obligations=("obl:a", "obl:b"),
    )
    assert advisor_proposal_is_admissible(envelope) is True
    assert advisor_proposal_rejection_reasons(envelope) == ()


@pytest.mark.parametrize(
    ("mutator", "expected_fragment"),
    [
        (lambda e: replace(e, proof_claimed=True), "marked_proposal_proved"),
        (lambda e: replace(e, completion_claimed=True), "marked_proposal_complete"),
        (lambda e: replace(e, semantic_authority=True), "raised_semantic_authority"),
        (
            lambda e: replace(e, authority="theorem"),
            "raised_authority_ceiling",
        ),
        (
            lambda e: replace(e, verification_key_id="vk:advisor-chosen"),
            "chose_verification_key",
        ),
        (
            lambda e: replace(e, skip_reconstruction=True),
            "skipped_reconstruction",
        ),
        (
            lambda e: replace(e, production_approved=True),
            "approved_production",
        ),
        (
            lambda e: replace(
                e,
                declared_assumptions=("assume:known",),
                introduced_assumptions=("assume:known", "assume:silent"),
            ),
            "silent_assumption:assume:silent",
        ),
        (
            lambda e: replace(
                e,
                required_blocking_obligations=("obl:a", "obl:blocking"),
                covered_obligations=("obl:a",),
            ),
            "dropped_blocking_obligation:obl:blocking",
        ),
    ],
)
def test_envelope_policy_rejects_each_forbidden_advisor_action(
    mutator: Any,
    expected_fragment: str,
) -> None:
    base = AdvisorProposalEnvelope(
        proposal_id="proposal:base",
        declared_assumptions=("assume:known",),
        introduced_assumptions=("assume:known",),
        required_blocking_obligations=("obl:a", "obl:blocking"),
        covered_obligations=("obl:a", "obl:blocking"),
    )
    bad = mutator(base)
    reasons = advisor_proposal_rejection_reasons(bad)
    assert reasons
    assert any(expected_fragment in reason for reason in reasons)
    assert advisor_proposal_is_admissible(bad) is False


# ---------------------------------------------------------------------------
# 1. Cannot mark proposals proved
# ---------------------------------------------------------------------------


def test_tactician_plan_never_claims_semantic_authority_or_proof() -> None:
    plan = TacticianPlan.build(
        goal_id="g1",
        goal_root="gr",
        corpus_root="cr",
        config_root="cfg",
        authority_roots={"tree": "t1"},
        policy_id="p1",
        planner_id="planner",
        selected_routes=[
            TacticianRoute(
                route_id="r1",
                source_id="s1",
                source_class="model_hypothesis",
                stage_index=0,
                disposition=RouteDisposition.SELECTED,
                rationale="advisor route",
            )
        ],
        excluded_routes=[],
        proof_gaps=["gap"],
        subgoals=[
            TacticianSubgoal(
                subgoal_id="sg1",
                parent_goal_id="g1",
                statement_ref="ref",
                depends_on=[],
                addresses_gaps=["gap"],
            )
        ],
        stop_conditions=["stop"],
        abstain_conditions=["abstain"],
        stop_disposition=StopDisposition.CONTINUE,
    )
    assert plan.semantic_authority is False
    payload = plan.to_dict()
    assert payload["semantic_authority"] is False
    assert "proof_claimed" not in payload or payload.get("proof_claimed") is False


def test_contracts_reject_proof_and_completion_claims() -> None:
    with pytest.raises(TacticianContractError, match="proof or completion"):
        EndGoalSpec(
            goal_id="goal:1",
            caller_text="prove f",
            source=_source_binding(),
            property_class=PropertyClass.THEOREM,
            bounds=_bounds(),
            ambiguity_status=AmbiguityStatus.NONE,
            proof_claimed=True,
        )
    with pytest.raises(TacticianContractError, match="proof or completion"):
        EndGoalSpec(
            goal_id="goal:2",
            caller_text="prove g",
            source=_source_binding(),
            property_class=PropertyClass.SAFETY,
            bounds=_bounds(),
            completion_claimed=True,
        )
    with pytest.raises(TacticianContractError, match="proof or completion"):
        ProofHole(
            hole_id="hole:1",
            kind=HoleKind.LOOP_INVARIANT,
            reason="missing invariant",
            source=_source_binding(),
            proof_claimed=True,
        )
    with pytest.raises(TacticianContractError, match="proof or completion"):
        CandidateProofStep(
            candidate_id="c1",
            hole_id="h1",
            kind="lemma",
            statement="body",
            source=_source_binding(),
            proof_claimed=True,
        )


def test_proposal_candidate_never_is_proved_even_at_high_confidence() -> None:
    candidate = ProposalCandidate(
        candidate_id="cand:1",
        kind=ProposalKind.LEMMA,
        body="lemma candidate body",
        source_ref_ids=("source:module.py",),
        provider=ProposalProvider.LEANSTRAL,
        confidence=0.999,
    )
    assert candidate.authority == UNVERIFIED_AUTHORITY
    assert candidate.is_proved is False
    assert confidence_never_yields_proof(confidence=0.999, is_valid=True) is False


def test_plan_ranking_hard_prunes_proof_claims() -> None:
    step = ProofPlanStepSpec(
        step_id="step:1",
        obligation_id="obl:1",
        kind=StepKind.SOLVE,
        dependencies=("external:root",),
        expected_receipts=("receipt:check",),
        validation=("validate:local",),
        fallback=("fallback:abstain",),
        resources=("cpu",),
        completion_conditions=("done",),
        authority=AuthorityCeiling.BOUNDED,
        proof_claimed=True,
    )
    plan = MissingProofPlanAlternative(
        plan_id="plan:bad",
        formal_goal_id="fg:1",
        graph_id="graph:1",
        tree_id="tree:1",
        root_goal_id="goal:1",
        steps=(step,),
        required_obligation_ids=("obl:1",),
        bounds=_bounds(),
    )
    failures = collect_hard_failures(plan, ProofPlanRankingPolicy())
    assert any(f.reason is HardPruneReason.PROOF_CLAIM for f in failures)


# ---------------------------------------------------------------------------
# 2. Cannot raise authority
# ---------------------------------------------------------------------------


def test_tactician_policy_and_plan_reject_authority_promotion() -> None:
    with pytest.raises(TacticianValidationError, match="semantic_authority"):
        TacticianPolicy(policy_id="p1", semantic_authority=True).validate()
    with pytest.raises(TacticianValidationError, match="authority promotion"):
        TacticianGoal(
            goal_id="g1",
            statement_ref="s1",
            goal_family="f",
            goal_root="gr",
            corpus_root="cr",
            config_root="cfg",
            metadata={"proof_authority": True},
        ).validate()
    with pytest.raises(TacticianValidationError, match="authority promotion"):
        TacticianSource(
            source_id="s1",
            source_class="model_hypothesis",
            precedence=0,
            rationale="advisor",
            metadata={"semantic_authority": True},
        ).validate()

    base = TacticianPlan.build(
        goal_id="g1",
        goal_root="gr",
        corpus_root="cr",
        config_root="cfg",
        authority_roots={},
        policy_id="p1",
        planner_id="planner",
        selected_routes=[
            TacticianRoute(
                route_id="r1",
                source_id="s1",
                source_class="c",
                stage_index=0,
                disposition=RouteDisposition.SELECTED,
                rationale="ok",
            )
        ],
        excluded_routes=[],
        proof_gaps=[],
        subgoals=[],
        stop_conditions=["stop"],
        abstain_conditions=["abstain"],
    )
    bad = TacticianPlan(
        plan_id=base.plan_id,
        goal_id=base.goal_id,
        goal_root=base.goal_root,
        corpus_root=base.corpus_root,
        config_root=base.config_root,
        authority_roots=base.authority_roots,
        policy_id=base.policy_id,
        planner_id=base.planner_id,
        selected_routes=base.selected_routes,
        excluded_routes=base.excluded_routes,
        proof_gaps=base.proof_gaps,
        subgoals=base.subgoals,
        stop_conditions=base.stop_conditions,
        abstain_conditions=base.abstain_conditions,
        stop_disposition=base.stop_disposition,
        semantic_authority=True,
    )
    with pytest.raises(TacticianValidationError, match="semantic_authority"):
        bad.validate()


def test_receipt_rejects_semantic_authority() -> None:
    plan = TacticianPlan.build(
        goal_id="g1",
        goal_root="gr",
        corpus_root="cr",
        config_root="cfg",
        authority_roots={},
        policy_id="p1",
        planner_id="planner",
        selected_routes=[
            TacticianRoute(
                route_id="r1",
                source_id="s1",
                source_class="c",
                stage_index=0,
                disposition=RouteDisposition.SELECTED,
                rationale="ok",
            )
        ],
        excluded_routes=[],
        proof_gaps=[],
        subgoals=[],
        stop_conditions=["stop"],
        abstain_conditions=["abstain"],
    )
    with pytest.raises(ReceiptError, match="semantic_authority"):
        TacticianReceipt(
            receipt_id="receipt:1",
            plan=plan,
            policy_digest="policy-digest:1",
            planner_id="planner",
            semantic_authority=True,
        ).validate()


def test_candidate_and_proposal_only_sources_cannot_raise_authority() -> None:
    with pytest.raises(TacticianContractError, match="capped at candidate"):
        _candidate_step(authority=AuthorityCeiling.THEOREM)
    with pytest.raises(TacticianContractError, match="capped at candidate"):
        _candidate_step(authority=AuthorityCeiling.RECONSTRUCTION)

    assert is_proposal_only_source(CandidateSourceKind.LEARNED_LEANSTRAL) is True
    with pytest.raises(CandidateSynthesisError, match="proposal-only"):
        CandidateProposal(
            candidate_id="cand:raise",
            source_kind=CandidateSourceKind.LEARNED_LEANSTRAL,
            provider_id="provider.leanstral",
            provenance={"origin": "model"},
            trust=CandidateTrust.LEARNED_PROPOSAL,
            budget=_bounds(),
            targeted_hole_ids=("hole:lpc-071",),
            step=_candidate_step(authority=AuthorityCeiling.CANDIDATE),
            proposal_only=False,
        )

    with pytest.raises(ProposalAdvisorValidationError, match="cannot claim authority"):
        ProposalCandidate(
            candidate_id="cand:auth",
            kind=ProposalKind.TACTIC,
            body="apply rfl",
            source_ref_ids=("source:module.py",),
            provider=ProposalProvider.SYMAI,
            authority="theorem",
        )


def test_advisor_role_never_satisfies_certified_authority() -> None:
    for ceiling in ToolchainAuthorityCeiling:
        assert (
            role_can_satisfy_certified_authority(ToolRole.ADVISOR, ceiling) is False
        )
        assert (
            role_can_satisfy_certified_authority(ToolRole.CANDIDATE, ceiling) is False
        )

    with pytest.raises(ToolchainRoleError, match="cannot hold"):
        FormalVerificationToolRole(
            tool_id="tool.advisor.leanstral",
            role=ToolRole.ADVISOR,
            authority_ceiling=ToolchainAuthorityCeiling.KERNEL,
            lane_ids=("lane:advisor",),
            families=("advisor",),
            independent_reconstruction_required=True,
        )
    with pytest.raises(ToolchainRoleError, match="cannot hold"):
        FormalVerificationToolRole(
            tool_id="tool.candidate.model",
            role=ToolRole.CANDIDATE,
            authority_ceiling=ToolchainAuthorityCeiling.ATTESTATION,
            lane_ids=("lane:candidate",),
            families=("candidate",),
            independent_reconstruction_required=True,
        )


# ---------------------------------------------------------------------------
# 3. Cannot choose verification keys
# ---------------------------------------------------------------------------


def test_proposal_candidate_rejects_advisor_chosen_verification_key() -> None:
    with pytest.raises(FormalizationValidationError, match="unknown"):
        ProposalCandidate.from_dict(
            {
                "candidate_id": "cand:vk",
                "kind": "lemma",
                "body": "lemma body",
                "source_ref_ids": ["source:module.py"],
                "provider": "leanstral",
                "confidence": 0.5,
                "verification_key_id": "vk:advisor-chosen",
            }
        )

    with pytest.raises(ProposalAdvisorValidationError, match="authority"):
        ProposalCandidate(
            candidate_id="cand:vk-meta",
            kind=ProposalKind.LEMMA,
            body="lemma body",
            source_ref_ids=("source:module.py",),
            provider=ProposalProvider.LEANSTRAL,
            metadata={"verification_status": "verified"},
        )

    # Closed-field rejection is not the only barrier: the LPC-071 envelope
    # policy independently forbids advisor-chosen verification keys.
    envelope = AdvisorProposalEnvelope(
        proposal_id="proposal:vk",
        verification_key_id="vk:advisor-chosen",
        required_blocking_obligations=("obl:a",),
        covered_obligations=("obl:a",),
    )
    reasons = advisor_proposal_rejection_reasons(envelope)
    assert "advisor_chose_verification_key" in reasons
    assert advisor_proposal_is_admissible(envelope) is False


# ---------------------------------------------------------------------------
# 4. Cannot skip reconstruction
# ---------------------------------------------------------------------------


def test_advisor_cannot_skip_required_reconstruction() -> None:
    envelope = AdvisorProposalEnvelope(
        proposal_id="proposal:skip",
        skip_reconstruction=True,
        required_blocking_obligations=("obl:a",),
        covered_obligations=("obl:a",),
    )
    reasons = advisor_proposal_rejection_reasons(
        envelope, reconstruction_required=True
    )
    assert "advisor_skipped_reconstruction" in reasons
    assert advisor_proposal_is_admissible(envelope) is False

    # Even when reconstruction is not required by policy, elevating authority
    # via skip still cannot mint theorem authority for an advisor role.
    assert (
        role_can_satisfy_certified_authority(
            ToolRole.ADVISOR, ToolchainAuthorityCeiling.KERNEL
        )
        is False
    )


def test_accept_candidate_still_not_kernel_proof_without_reconstruction() -> None:
    candidate = ProposalCandidate(
        candidate_id="cand:accept",
        kind=ProposalKind.REPAIR,
        body="repair suggestion",
        source_ref_ids=("source:module.py",),
        provider=ProposalProvider.LEANSTRAL,
        confidence=0.95,
    )
    acceptance = accept_candidate(
        candidate, compiled=True, independently_validated=True
    )
    assert acceptance.accepted is True
    assert acceptance.authority == "candidate_admitted_for_validation"
    assert acceptance.authority != "theorem"
    assert candidate.is_proved is False


# ---------------------------------------------------------------------------
# 5. Cannot approve production
# ---------------------------------------------------------------------------


def test_advisor_cannot_approve_production() -> None:
    envelope = AdvisorProposalEnvelope(
        proposal_id="proposal:prod",
        production_approved=True,
        required_blocking_obligations=("obl:a",),
        covered_obligations=("obl:a",),
    )
    assert "advisor_approved_production" in advisor_proposal_rejection_reasons(
        envelope
    )


def test_catalog_presence_never_admits_production() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    assert snapshot.presence_implies_production_admission() is False
    assert snapshot.presence_implies_executability() is False


def test_goal_completion_is_not_advisor_owned() -> None:
    # Advisors/candidates cannot mint COMPLETE with advisory authority.
    with pytest.raises(TacticianContractError, match="elevated authority"):
        GoalCompletion(
            completion_id="completion:1",
            formal_goal_id="fg:1",
            root_goal_id="goal:1",
            tree_id="tree:1",
            verdict=CompletionVerdict.COMPLETE,
            authority=AuthorityCeiling.ADVISORY,
            evidence_ids=("ev:1",),
        )
    with pytest.raises(TacticianContractError, match="elevated authority"):
        GoalCompletion(
            completion_id="completion:2",
            formal_goal_id="fg:1",
            root_goal_id="goal:1",
            tree_id="tree:1",
            verdict=CompletionVerdict.COMPLETE,
            authority=AuthorityCeiling.CANDIDATE,
            evidence_ids=("ev:1",),
        )


# ---------------------------------------------------------------------------
# 6. Cannot silently add assumptions
# ---------------------------------------------------------------------------


def test_planner_does_not_silently_add_assumptions_from_sources() -> None:
    goal = _baseline_goal()
    policy = default_policy(policy_id="policy:lpc-071")
    planner = LogicTactician()
    plan = planner.plan(goal, _baseline_sources(), policy)

    # Assumptions remain the explicit goal set; sources cannot inject more.
    assert list(goal.assumptions) == ["assume:explicit-only"]
    plan_payload = plan.to_dict()
    assert "assumptions" not in plan_payload or plan_payload.get("assumptions") in (
        None,
        [],
        ["assume:explicit-only"],
    )
    assert plan.semantic_authority is False
    assert plan.proof_gaps == list(goal.proof_gaps)


def test_undeclared_assumptions_fail_envelope_and_must_be_named_on_steps() -> None:
    envelope = AdvisorProposalEnvelope(
        proposal_id="proposal:assumptions",
        declared_assumptions=("assume:known",),
        introduced_assumptions=("assume:known", "assume:silent"),
        required_blocking_obligations=("obl:a",),
        covered_obligations=("obl:a",),
    )
    reasons = advisor_proposal_rejection_reasons(envelope)
    assert "silent_assumption:assume:silent" in reasons

    # Explicit new_assumption_ids are allowed as *named* introductions on a
    # candidate step — silence is the forbidden mode, not declaration.
    step = _candidate_step(new_assumption_ids=("assume:named",))
    assert step.new_assumption_ids == ("assume:named",)
    assert step.proof_claimed is False
    assert step.authority is AuthorityCeiling.CANDIDATE


# ---------------------------------------------------------------------------
# 7. Cannot drop blocking obligations
# ---------------------------------------------------------------------------


def test_planner_preserves_blocking_proof_gaps() -> None:
    goal = _baseline_goal()
    policy = default_policy(policy_id="policy:lpc-071")
    plan = LogicTactician().plan(goal, _baseline_sources(), policy)

    assert plan.proof_gaps == ["blocking:gap-a", "blocking:gap-b"]
    addressed = {
        gap
        for subgoal in plan.subgoals
        for gap in subgoal.addresses_gaps
    }
    # Subgoals may address gaps; they must not erase the plan's gap inventory.
    assert set(plan.proof_gaps) == {"blocking:gap-a", "blocking:gap-b"}
    assert addressed.issubset(set(plan.proof_gaps))


def test_ranking_hard_prunes_dropped_blocking_obligations() -> None:
    step = ProofPlanStepSpec(
        step_id="step:only-a",
        obligation_id="obl:a",
        kind=StepKind.SOLVE,
        dependencies=("external:root",),
        expected_receipts=("receipt:check",),
        validation=("validate:local",),
        fallback=("fallback:abstain",),
        resources=("cpu",),
        completion_conditions=("done",),
        authority=AuthorityCeiling.BOUNDED,
    )
    plan = MissingProofPlanAlternative(
        plan_id="plan:drop",
        formal_goal_id="fg:1",
        graph_id="graph:1",
        tree_id="tree:1",
        root_goal_id="goal:1",
        steps=(step,),
        required_obligation_ids=("obl:a", "obl:blocking"),
        bounds=_bounds(),
    )
    policy = ProofPlanRankingPolicy()
    failures = collect_hard_failures(plan, policy)
    assert any(f.reason is HardPruneReason.MISSING_COVERAGE for f in failures)
    assert any(
        "obl:blocking" in code
        for failure in failures
        for code in failure.reason_codes
    )

    envelope = AdvisorProposalEnvelope(
        proposal_id="proposal:drop",
        required_blocking_obligations=("obl:a", "obl:blocking"),
        covered_obligations=("obl:a",),
    )
    reasons = advisor_proposal_rejection_reasons(envelope)
    assert "dropped_blocking_obligation:obl:blocking" in reasons


# ---------------------------------------------------------------------------
# Joint adversarial matrix
# ---------------------------------------------------------------------------


def test_joint_adversarial_advisor_escalation_matrix() -> None:
    """Mutating every forbidden axis must keep the joint claim fail-closed."""

    base = AdvisorProposalEnvelope(
        proposal_id="proposal:joint",
        declared_assumptions=("assume:known",),
        introduced_assumptions=("assume:known",),
        required_blocking_obligations=("obl:a", "obl:b"),
        covered_obligations=("obl:a", "obl:b"),
    )
    assert advisor_proposal_is_admissible(base) is True

    mutations: dict[str, AdvisorProposalEnvelope] = {
        "proved": replace(base, proof_claimed=True),
        "authority": replace(base, authority="attestation", semantic_authority=True),
        "verification_key": replace(base, verification_key_id="vk:evil"),
        "skip_reconstruction": replace(base, skip_reconstruction=True),
        "production": replace(base, production_approved=True),
        "silent_assumption": replace(
            base, introduced_assumptions=("assume:known", "assume:extra")
        ),
        "drop_blocking": replace(base, covered_obligations=("obl:a",)),
    }
    for label, envelope in mutations.items():
        reasons = advisor_proposal_rejection_reasons(envelope)
        assert reasons, f"expected rejection for {label}"
        assert advisor_proposal_is_admissible(envelope) is False

    # Combining all escalations still fails closed (no "any axis success" leak).
    combined = AdvisorProposalEnvelope(
        proposal_id="proposal:all-bad",
        authority="theorem",
        proof_claimed=True,
        completion_claimed=True,
        semantic_authority=True,
        verification_key_id="vk:evil",
        skip_reconstruction=True,
        production_approved=True,
        declared_assumptions=("assume:known",),
        introduced_assumptions=("assume:silent",),
        required_blocking_obligations=("obl:a", "obl:b"),
        covered_obligations=(),
    )
    combined_reasons = advisor_proposal_rejection_reasons(combined)
    assert len(combined_reasons) >= 7
    assert advisor_proposal_is_admissible(combined) is False
