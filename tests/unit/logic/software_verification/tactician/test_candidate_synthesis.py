"""Unit tests for ProofCandidatePortfolio@1 (FVT-017 / FVT-G033).

Acceptance:

* Every candidate records source/provider/provenance/trust/budget and targeted
  holes.
* Autoencoder, Leanstral, SymAI, embeddings, and model output remain
  proposal-only.
* Legal obligations delegate evidence routing to the existing legal tactician
  compatibility adapter.
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    AuthorityCeiling,
    CandidateStatus,
    HoleKind,
    HoleStatus,
    ProofHole,
    PropertyClass,
    ResourceBounds,
    SourceSpanBinding,
)
from ipfs_datasets_py.logic.software_verification.tactician.candidate_synthesis import (
    DEFAULT_BUDGET,
    LEGAL_TACTICIAN_ADAPTER_ID,
    LEGAL_TACTICIAN_CLASS,
    LEGAL_TACTICIAN_MODULE,
    PORTFOLIO_ALGORITHM_VERSION,
    PROOF_CANDIDATE_PORTFOLIO_INTERFACE,
    CandidatePortfolioResult,
    CandidateProposal,
    CandidateSourceHit,
    CandidateSourceKind,
    CandidateSynthesisError,
    CandidateTrust,
    LegalEvidenceRoutingAdapter,
    ProofCandidatePortfolio,
    ReviewedTemplateSource,
    StaticCandidateSource,
    default_source_kinds,
    is_legal_hole,
    is_proposal_only_provider,
    is_proposal_only_source,
    synthesize_candidate_portfolio,
)


def _source(**overrides: Any) -> SourceSpanBinding:
    payload = {
        "tree_id": "tree:repo@abc",
        "source_ref_ids": ("source:lease.py",),
        "span_ids": ("span:claim",),
        "ast_scope_ids": ("symbol:claim_lease",),
        "snapshot_id": "snap:1",
    }
    payload.update(overrides)
    return SourceSpanBinding(**payload)


def _bounds(**overrides: Any) -> ResourceBounds:
    payload = {
        "wall_time_ms": 10_000,
        "memory_bytes": 64 * 1024 * 1024,
        "max_steps": 32,
        "max_depth": 8,
        "max_nodes": 64,
        "max_candidates": 16,
        "network_allowed": False,
    }
    payload.update(overrides)
    return ResourceBounds(**payload)


def _hole(
    hole_id: str = "hole:site:loop:loop_invariant",
    *,
    kind: HoleKind = HoleKind.LOOP_INVARIANT,
    status: HoleStatus = HoleStatus.OPEN,
    reason: str = "Required loop_invariant is missing",
    statement: str = "missing loop_invariant",
    formal_goal_id: str = "formal:lease-ready",
    **overrides: Any,
) -> ProofHole:
    payload: dict[str, Any] = {
        "hole_id": hole_id,
        "kind": kind,
        "reason": reason,
        "source": _source(),
        "formal_goal_id": formal_goal_id,
        "expected_authority": AuthorityCeiling.SATISFIABILITY,
        "status": status,
        "property_class": PropertyClass.INVARIANCE,
        "statement": statement,
        "provider_ids": ("provider:z3",),
        "bounds": _bounds(),
        "proof_claimed": False,
        "completion_claimed": False,
    }
    payload.update(overrides)
    return ProofHole(**payload)


def _legal_hole() -> ProofHole:
    return _hole(
        "hole:site:evidence:missing_evidence",
        kind=HoleKind.MISSING_EVIDENCE,
        reason="Legal docket evidence is required for the authorization premise",
        statement="missing legal evidence",
        expected_authority=AuthorityCeiling.ATTESTATION,
        property_class=PropertyClass.AUTHORIZATION,
    )


# ---------------------------------------------------------------------------
# Interface / vocabulary
# ---------------------------------------------------------------------------


def test_portfolio_interface_constant() -> None:
    assert (
        ProofCandidatePortfolio.INTERFACE == PROOF_CANDIDATE_PORTFOLIO_INTERFACE
    )
    assert PROOF_CANDIDATE_PORTFOLIO_INTERFACE == "ProofCandidatePortfolio@1"
    assert PORTFOLIO_ALGORITHM_VERSION.startswith("proof-candidate-portfolio/")


def test_default_source_kinds_cover_required_portfolio() -> None:
    kinds = default_source_kinds()
    values = {kind.value for kind in kinds}
    required = {
        "corpus_exact",
        "cache_hit",
        "hammer_retrieval",
        "reviewed_template",
        "houdini_elimination",
        "smt_unsat_core",
        "smt_interpolation",
        "chc_pdr_ic3",
        "sygus",
        "legal_evidence_routing",
        "learned_autoencoder",
        "learned_leanstral",
        "learned_symai",
        "learned_embeddings",
        "learned_model",
    }
    assert required.issubset(values)
    for kind in (
        CandidateSourceKind.LEARNED_AUTOENCODER,
        CandidateSourceKind.LEARNED_LEANSTRAL,
        CandidateSourceKind.LEARNED_SYMAI,
        CandidateSourceKind.LEARNED_EMBEDDINGS,
        CandidateSourceKind.LEARNED_MODEL,
    ):
        assert is_proposal_only_source(kind)


def test_proposal_only_provider_detection() -> None:
    assert is_proposal_only_provider("provider:autoencoder")
    assert is_proposal_only_provider("provider:leanstral")
    assert is_proposal_only_provider("provider:symai")
    assert is_proposal_only_provider("provider:embeddings")
    assert is_proposal_only_provider("provider:model")
    assert not is_proposal_only_provider("provider:z3")
    assert not is_proposal_only_provider("provider:hammer")


# ---------------------------------------------------------------------------
# Acceptance: every candidate records source/provider/provenance/trust/budget
# and targeted holes
# ---------------------------------------------------------------------------


def test_every_candidate_records_source_provider_provenance_trust_budget_holes() -> None:
    hole = _hole()
    corpus = StaticCandidateSource(
        source_kind=CandidateSourceKind.CORPUS_EXACT,
        hits_by_hole={
            hole.hole_id: (
                {
                    "statement": "inv: owner = None \\/ holds(owner, lease)",
                    "provider_id": "provider:proof-corpus",
                    "provenance": {
                        "corpus_entry_id": "corpus:lease-inv-1",
                        "digest": "sha256:abc",
                    },
                    "evidence_ids": ("evidence:corpus:lease-inv-1",),
                },
            )
        },
    )
    templates = ReviewedTemplateSource(
        templates={
            HoleKind.LOOP_INVARIANT.value: (
                "template: loop head preserves bound and ownership",
            )
        }
    )
    smt = StaticCandidateSource(
        source_kind=CandidateSourceKind.SMT_UNSAT_CORE,
        hits_by_hole={
            hole.hole_id: (
                {
                    "statement": "core-guard: bound > 0",
                    "provider_id": "provider:z3",
                    "provenance": {"core_ids": ["a1", "a2"], "method": "mus"},
                },
            )
        },
    )
    portfolio = ProofCandidatePortfolio(
        sources=(corpus, templates, smt),
        budget=_bounds(max_candidates=16),
        include_builtin_legal_adapter=False,
        formal_goal_id="formal:lease-ready",
    )
    result = portfolio.synthesize([hole])

    assert result.INTERFACE == PROOF_CANDIDATE_PORTFOLIO_INTERFACE
    assert result.proof_claimed is False
    assert result.completion_claimed is False
    assert result.formal_goal_id == "formal:lease-ready"
    assert hole.hole_id in result.targeted_hole_ids
    assert len(result.proposals) >= 3

    for proposal in result.proposals:
        assert proposal.source_kind in CandidateSourceKind
        assert proposal.provider_id
        assert isinstance(proposal.provenance, dict)
        assert proposal.provenance.get("source_kind") == proposal.source_kind.value
        assert proposal.provenance.get("provider_id") == proposal.provider_id
        assert proposal.trust in CandidateTrust
        assert isinstance(proposal.budget, ResourceBounds)
        assert proposal.budget.wall_time_ms >= 0
        assert hole.hole_id in proposal.targeted_hole_ids
        assert proposal.step.hole_id == hole.hole_id
        assert proposal.step.proof_claimed is False
        assert proposal.step.completion_claimed is False
        assert proposal.step.status is CandidateStatus.PROPOSED
        assert proposal.step.authority in {
            AuthorityCeiling.NONE,
            AuthorityCeiling.ADVISORY,
            AuthorityCeiling.CANDIDATE,
        }
        # Wire record includes required acceptance fields.
        record = proposal.to_dict()
        assert record["source_kind"]
        assert record["provider_id"]
        assert record["provenance"]
        assert record["trust"]
        assert record["budget"]
        assert hole.hole_id in record["targeted_hole_ids"]


def test_portfolio_result_round_trip() -> None:
    hole = _hole()
    result = synthesize_candidate_portfolio(
        [hole],
        sources=(
            ReviewedTemplateSource(
                templates={
                    HoleKind.LOOP_INVARIANT.value: ("inv: true",),
                }
            ),
        ),
        include_builtin_legal_adapter=False,
        formal_goal_id="formal:lease-ready",
    )
    restored = CandidatePortfolioResult.from_dict(result.to_dict())
    assert restored.portfolio_id == result.portfolio_id
    assert restored.content_id == result.content_id
    assert len(restored.proposals) == len(result.proposals)
    assert restored.proof_claimed is False


def test_multi_source_portfolio_composes_all_typed_sources() -> None:
    hole = _hole()
    kinds = (
        CandidateSourceKind.CORPUS_EXACT,
        CandidateSourceKind.CACHE_HIT,
        CandidateSourceKind.HAMMER_RETRIEVAL,
        CandidateSourceKind.HOUDINI_ELIMINATION,
        CandidateSourceKind.SMT_INTERPOLATION,
        CandidateSourceKind.CHC_PDR_IC3,
        CandidateSourceKind.SYGUS,
    )
    sources = []
    for kind in kinds:
        sources.append(
            StaticCandidateSource(
                source_kind=kind,
                hits_by_hole={
                    hole.hole_id: (
                        {
                            "statement": f"candidate from {kind.value}",
                            "provenance": {"origin": kind.value},
                        },
                    )
                },
            )
        )
    sources.append(
        ReviewedTemplateSource(
            templates={HoleKind.LOOP_INVARIANT.value: ("template inv",)}
        )
    )
    result = ProofCandidatePortfolio(
        sources=tuple(sources),
        include_builtin_legal_adapter=False,
        budget=_bounds(max_candidates=32),
    ).synthesize([hole])
    used = set(result.source_kinds_used)
    for kind in kinds:
        assert kind.value in used
    assert CandidateSourceKind.REVIEWED_TEMPLATE.value in used
    assert len(result.proposals) == len(kinds) + 1


# ---------------------------------------------------------------------------
# Acceptance: learned sources remain proposal-only
# ---------------------------------------------------------------------------


def test_learned_sources_remain_proposal_only() -> None:
    hole = _hole()
    learned_kinds = (
        CandidateSourceKind.LEARNED_AUTOENCODER,
        CandidateSourceKind.LEARNED_LEANSTRAL,
        CandidateSourceKind.LEARNED_SYMAI,
        CandidateSourceKind.LEARNED_EMBEDDINGS,
        CandidateSourceKind.LEARNED_MODEL,
    )
    sources = [
        StaticCandidateSource(
            source_kind=kind,
            hits_by_hole={
                hole.hole_id: (
                    {
                        "statement": f"learned proposal via {kind.value}",
                        "provider_id": f"provider:{kind.value.removeprefix('learned_')}",
                        "provenance": {"model": kind.value, "temperature": "0"},
                    },
                )
            },
        )
        for kind in learned_kinds
    ]
    result = ProofCandidatePortfolio(
        sources=tuple(sources),
        include_builtin_legal_adapter=False,
    ).synthesize([hole])

    assert len(result.proposals) == len(learned_kinds)
    assert set(result.proposal_only_candidate_ids) == {
        p.candidate_id for p in result.proposals
    }
    for proposal in result.proposals:
        assert proposal.proposal_only is True
        assert proposal.trust is CandidateTrust.LEARNED_PROPOSAL
        assert proposal.step.authority is AuthorityCeiling.CANDIDATE
        assert proposal.step.proof_claimed is False
        assert proposal.step.completion_claimed is False
        assert proposal.provenance.get("proposal_only") is True
        assert is_proposal_only_source(proposal.source_kind)


def test_learned_hit_cannot_disable_proposal_only_flag() -> None:
    with pytest.raises(CandidateSynthesisError, match="proposal-only"):
        CandidateSourceHit(
            source_kind=CandidateSourceKind.LEARNED_LEANSTRAL,
            hole_id="hole:x",
            statement="bad elevation",
            proposal_only=False,
        )


def test_proposal_rejects_proof_claims() -> None:
    hole = _hole()
    hit = CandidateSourceHit(
        source_kind=CandidateSourceKind.REVIEWED_TEMPLATE,
        hole_id=hole.hole_id,
        statement="inv: x >= 0",
    )
    portfolio = ProofCandidatePortfolio(
        sources=(
            StaticCandidateSource(
                source_kind=CandidateSourceKind.REVIEWED_TEMPLATE,
                hits_by_hole={hole.hole_id: (hit,)},
            ),
        ),
        include_builtin_legal_adapter=False,
    )
    result = portfolio.synthesize([hole])
    payload = result.proposals[0].to_dict()
    payload["proof_claimed"] = True
    with pytest.raises(CandidateSynthesisError, match="proof or completion"):
        CandidateProposal.from_dict(payload)


def test_portfolio_result_rejects_proof_claims() -> None:
    hole = _hole()
    result = synthesize_candidate_portfolio(
        [hole],
        sources=(
            ReviewedTemplateSource(
                templates={HoleKind.LOOP_INVARIANT.value: ("inv",)}
            ),
        ),
        include_builtin_legal_adapter=False,
    )
    payload = result.to_dict()
    payload["completion_claimed"] = True
    with pytest.raises(CandidateSynthesisError, match="proof or completion"):
        CandidatePortfolioResult.from_dict(payload)


# ---------------------------------------------------------------------------
# Acceptance: legal obligations delegate to legal tactician adapter
# ---------------------------------------------------------------------------


def test_legal_obligations_delegate_to_legal_tactician_adapter() -> None:
    legal = _legal_hole()
    assert is_legal_hole(legal)

    def plan_builder(hole: ProofHole) -> dict[str, Any]:
        return {
            "plan_id": f"legal-plan:{hole.hole_id}",
            "recommended_route": [
                "local_docket_documents",
                "authority_list",
                "legal_dataset_api",
            ],
            "search_stages": [
                {"stage": "local", "source_type": "local_docket_documents"},
                {"stage": "authority", "source_type": "authority_list"},
            ],
            "evidence_ids": ("evidence:docket:1",),
        }

    adapter = LegalEvidenceRoutingAdapter(plan_builder=plan_builder)
    result = ProofCandidatePortfolio(
        sources=(adapter,),
        include_builtin_legal_adapter=False,
        formal_goal_id="formal:authz",
    ).synthesize([legal])

    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.source_kind is CandidateSourceKind.LEGAL_EVIDENCE_ROUTING
    assert proposal.delegated_to == LEGAL_TACTICIAN_ADAPTER_ID
    assert proposal.provider_id == LEGAL_TACTICIAN_ADAPTER_ID
    assert proposal.trust is CandidateTrust.LEGAL_DELEGATED
    assert proposal.candidate_id in result.legal_delegated_candidate_ids
    assert proposal.provenance["adapter_id"] == LEGAL_TACTICIAN_ADAPTER_ID
    assert proposal.provenance["module"] == LEGAL_TACTICIAN_MODULE
    assert proposal.provenance["class"] == LEGAL_TACTICIAN_CLASS
    assert proposal.provenance["delegation"] == "legal_evidence_routing"
    assert "local_docket_documents" in proposal.provenance["recommended_route"]
    assert proposal.metadata.get("compatibility_adapter") is True
    assert proposal.metadata.get("owns_search") is False
    assert "evidence:docket:1" in proposal.step.evidence_ids


def test_builtin_legal_adapter_activates_for_missing_evidence_holes() -> None:
    legal = _legal_hole()
    loop = _hole()
    result = ProofCandidatePortfolio(
        sources=(),
        include_builtin_legal_adapter=True,
    ).synthesize([legal, loop])
    legal_props = result.proposals_of_source(
        CandidateSourceKind.LEGAL_EVIDENCE_ROUTING
    )
    assert len(legal_props) == 1
    assert legal_props[0].targeted_hole_ids == (legal.hole_id,)
    # Loop invariant is not a legal hole — no legal candidate for it.
    assert result.proposals_for_hole(loop.hole_id) == ()


def test_legal_proposal_requires_delegated_to() -> None:
    hole = _legal_hole()
    step_payload = {
        "candidate_id": "candidate:legal:x",
        "hole_id": hole.hole_id,
        "kind": "legal_evidence_delegation",
        "statement": "delegate",
        "status": "proposed",
        "source": hole.source.to_dict(),
        "provider_ids": [LEGAL_TACTICIAN_ADAPTER_ID],
        "authority": "candidate",
        "rank_score_millionths": 600_000,
        "new_assumption_ids": [],
        "evidence_ids": [],
        "provenance": {},
        "proof_claimed": False,
        "completion_claimed": False,
    }
    from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
        CandidateProofStep,
    )

    step = CandidateProofStep.from_dict(step_payload)
    with pytest.raises(CandidateSynthesisError, match="delegated_to"):
        CandidateProposal(
            candidate_id="candidate:legal:x",
            source_kind=CandidateSourceKind.LEGAL_EVIDENCE_ROUTING,
            provider_id=LEGAL_TACTICIAN_ADAPTER_ID,
            provenance={"adapter_id": LEGAL_TACTICIAN_ADAPTER_ID},
            trust=CandidateTrust.LEGAL_DELEGATED,
            budget=DEFAULT_BUDGET,
            targeted_hole_ids=(hole.hole_id,),
            step=step,
            delegated_to="",  # missing
        )


# ---------------------------------------------------------------------------
# Fail-closed / hygiene
# ---------------------------------------------------------------------------


def test_non_proof_holes_are_skipped() -> None:
    unsupported = _hole(
        "hole:site:ffi:unsupported_semantics",
        kind=HoleKind.UNSUPPORTED_SEMANTICS,
        status=HoleStatus.UNSUPPORTED,
        reason="inline assembly unsupported",
        statement="unsupported semantics",
    )
    unavailable = _hole(
        "hole:site:tool:unavailable_tool",
        kind=HoleKind.UNAVAILABLE_TOOL,
        status=HoleStatus.UNAVAILABLE,
        reason="cvc5 missing",
        statement="tool unavailable",
    )
    result = synthesize_candidate_portfolio(
        [unsupported, unavailable],
        sources=(
            ReviewedTemplateSource(
                templates={
                    HoleKind.UNSUPPORTED_SEMANTICS.value: ("should not emit",),
                    HoleKind.UNAVAILABLE_TOOL.value: ("should not emit",),
                }
            ),
        ),
        include_builtin_legal_adapter=False,
    )
    assert result.proposals == ()
    assert result.targeted_hole_ids == ()


def test_duplicate_hole_ids_fail_closed() -> None:
    hole = _hole()
    with pytest.raises(CandidateSynthesisError, match="duplicate hole"):
        ProofCandidatePortfolio(include_builtin_legal_adapter=False).synthesize(
            [hole, hole]
        )


def test_max_candidates_budget_is_respected() -> None:
    hole = _hole()
    statements = [f"template inv {i}" for i in range(10)]
    result = ProofCandidatePortfolio(
        sources=(
            ReviewedTemplateSource(
                templates={HoleKind.LOOP_INVARIANT.value: tuple(statements)}
            ),
        ),
        include_builtin_legal_adapter=False,
        max_candidates_per_hole=3,
        budget=_bounds(max_candidates=3),
    ).synthesize([hole])
    assert len(result.proposals) == 3


def test_ranking_prefers_exact_corpus_over_learned() -> None:
    hole = _hole()
    sources = (
        StaticCandidateSource(
            source_kind=CandidateSourceKind.LEARNED_MODEL,
            hits_by_hole={
                hole.hole_id: (
                    {"statement": "learned guess", "provider_id": "provider:model"},
                )
            },
        ),
        StaticCandidateSource(
            source_kind=CandidateSourceKind.CORPUS_EXACT,
            hits_by_hole={
                hole.hole_id: (
                    {
                        "statement": "exact corpus lemma",
                        "provider_id": "provider:proof-corpus",
                    },
                )
            },
        ),
    )
    result = ProofCandidatePortfolio(
        sources=sources,
        include_builtin_legal_adapter=False,
    ).synthesize([hole])
    assert result.proposals[0].source_kind is CandidateSourceKind.CORPUS_EXACT
    assert result.proposals[-1].source_kind is CandidateSourceKind.LEARNED_MODEL


def test_convenience_entry_point() -> None:
    hole = _hole()
    result = synthesize_candidate_portfolio(
        [hole],
        sources=(
            StaticCandidateSource(
                source_kind=CandidateSourceKind.HAMMER_RETRIEVAL,
                hits_by_hole={
                    hole.hole_id: (
                        {
                            "statement": "hammer premise P",
                            "provenance": {"hammer_query": "P"},
                        },
                    )
                },
            ),
        ),
        include_builtin_legal_adapter=False,
        formal_goal_id="formal:lease-ready",
    )
    assert len(result.proposals) == 1
    assert result.proposals[0].source_kind is CandidateSourceKind.HAMMER_RETRIEVAL
    assert result.to_record()["content_id"].startswith("sha256:")


def test_candidate_source_hit_defaults_and_round_trip() -> None:
    hit = CandidateSourceHit(
        source_kind=CandidateSourceKind.HOUDINI_ELIMINATION,
        hole_id="hole:h1",
        statement="candidate predicate A",
    )
    assert hit.provider_id == "provider:houdini"
    assert hit.trust is CandidateTrust.SYNTHESIS
    assert hit.proposal_only is False
    restored = CandidateSourceHit.from_dict(hit.to_dict())
    assert restored.statement == hit.statement
    assert restored.source_kind is hit.source_kind


def test_empty_holes_yields_empty_portfolio() -> None:
    result = ProofCandidatePortfolio(
        include_builtin_legal_adapter=False
    ).synthesize([])
    assert result.proposals == ()
    assert result.targeted_hole_ids == ()
    assert result.proof_claimed is False
