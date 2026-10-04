"""Unit tests for EndGoalFormalizer@1 (FVT-011 / FVT-G022).

Acceptance coverage:

* deterministic controlled-language cases round trip;
* learned parsing is candidate-only;
* every clause maps to prompt/repository spans;
* hidden assumptions and ungrounded identifiers are rejected; and
* unsupported or underspecified semantics remain explicit.

Also asserts the formalizer never mutates the frozen caller request and never
admits a candidate.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    AssumptionClass,
    AuthorityCeiling,
    PropertyClass,
    QuantifierKind,
    ResourceBounds,
    SourceSpanBinding,
)
from ipfs_datasets_py.logic.software_verification.tactician.end_goal_formalizer import (
    END_GOAL_FORMALIZER_INTERFACE,
    EndGoalCandidate,
    EndGoalFormalizer,
    EndGoalFormalizerError,
    EndGoalFormalizerRequest,
    EndGoalFormalizerResult,
    FormalizationMode,
    FormalizationStatus,
    render_controlled_english,
    render_controlled_language,
)


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _source(**overrides: Any) -> SourceSpanBinding:
    payload = {
        "tree_id": "tree:repo@abc",
        "source_ref_ids": ("source:prompt", "source:lease.py"),
        "span_ids": ("span:caller",),
        "ast_scope_ids": ("symbol:claim_lease",),
        "snapshot_id": "snap:1",
    }
    payload.update(overrides)
    return SourceSpanBinding(**payload)


def _controlled_language_doc() -> str:
    return "\n".join(
        [
            "PROPERTY existential_reachability",
            "QUANTIFIER exists",
            "QUANTIFIER eventually",
            "ACTOR scheduler",
            "ACTOR worker",
            "STATE phase",
            "STATE owner",
            "CURRENT phase=init",
            "TARGET phase=ready",
            "TRANSITION claim",
            "TRANSITION release",
            "ENVIRONMENT network=async",
            "INTERFERENCE preempt=true",
            "ASSUME must_prove: tokens are totally ordered",
            "BOUND wall_time_ms=5000",
            "BOUND max_steps=32",
            "ASSURANCE bounded",
            "LOGIC temporal.ltl",
            "PROVIDER provider:z3",
            "ACCEPT receipt:kernel",
            "RECEIPT proof-receipt",
            "RECEIPT counterexample",
        ]
    )


def _request(
    text: str | None = None,
    **overrides: Any,
) -> EndGoalFormalizerRequest:
    payload: dict[str, Any] = {
        "caller_text": text if text is not None else _controlled_language_doc(),
        "source": _source(),
        "goal_id": "goal:lease-ready",
        "root_goal_id": "goal:lease-ready",
        "known_identifiers": (
            "scheduler",
            "worker",
            "phase",
            "owner",
            "claim",
            "release",
            "network",
            "preempt",
            "init",
            "ready",
        ),
        "repository_source_ref_ids": ("source:lease.py",),
        "prefer_controlled_language": True,
        "max_candidates": 8,
        "logic_family": "temporal.ltl",
        "provider_ids": ("provider:z3",),
        "bounds": ResourceBounds(
            wall_time_ms=1_000,
            max_steps=8,
            network_allowed=False,
        ),
    }
    payload.update(overrides)
    if isinstance(payload.get("source"), dict):
        payload["source"] = SourceSpanBinding(**payload["source"])
    if isinstance(payload.get("bounds"), dict):
        payload["bounds"] = ResourceBounds(**payload["bounds"])
    return EndGoalFormalizerRequest(**payload)


@pytest.fixture
def formalizer() -> EndGoalFormalizer:
    return EndGoalFormalizer()


# ---------------------------------------------------------------------------
# Interface / freeze / non-admission
# ---------------------------------------------------------------------------


def test_interface_constant() -> None:
    assert END_GOAL_FORMALIZER_INTERFACE == "EndGoalFormalizer@1"
    assert EndGoalFormalizer.INTERFACE == "EndGoalFormalizer@1"


def test_request_digest_stable_and_frozen(formalizer: EndGoalFormalizer) -> None:
    request = _request()
    digest_before = request.request_digest
    original_text = request.caller_text
    result = formalizer.formalize(request)
    assert result.request_digest == digest_before
    assert result.frozen_caller_text == original_text
    assert request.caller_text == original_text
    assert request.request_digest == digest_before
    assert result.admitted is False
    assert all(not c.admitted and not c.selected for c in result.candidates)


def test_request_from_mapping_round_trip_fields() -> None:
    request = _request()
    rebuilt = EndGoalFormalizerRequest.from_dict(request.to_dict())
    assert rebuilt.caller_text == request.caller_text
    assert rebuilt.source.tree_id == request.source.tree_id
    assert rebuilt.request_digest == request.request_digest


def test_result_cannot_admit() -> None:
    with pytest.raises(EndGoalFormalizerError, match="cannot admit"):
        EndGoalFormalizerResult(
            status=FormalizationStatus.CANDIDATE,
            request_digest="sha256:dead",
            frozen_caller_text="x",
            admitted=True,
        )


def test_candidate_cannot_select_or_admit(formalizer: EndGoalFormalizer) -> None:
    result = formalizer.formalize(_request())
    assert result.candidates
    goal = result.candidates[0].end_goal
    with pytest.raises(EndGoalFormalizerError, match="cannot be admitted"):
        EndGoalCandidate(
            candidate_id="c1",
            end_goal=goal,
            mode=FormalizationMode.CONTROLLED_LANGUAGE,
            controlled_english="x",
            admitted=True,
        )
    with pytest.raises(EndGoalFormalizerError, match="cannot be admitted"):
        EndGoalCandidate(
            candidate_id="c1",
            end_goal=goal,
            mode=FormalizationMode.CONTROLLED_LANGUAGE,
            controlled_english="x",
            selected=True,
        )


def test_request_rejects_admission_meta() -> None:
    with pytest.raises(EndGoalFormalizerError, match="cannot claim"):
        _request(meta={"admitted": True})


# ---------------------------------------------------------------------------
# Deterministic controlled-language extraction + round trip
# ---------------------------------------------------------------------------


def test_controlled_language_extracts_all_bindings(
    formalizer: EndGoalFormalizer,
) -> None:
    result = formalizer.formalize(_request())
    assert result.status is FormalizationStatus.CANDIDATE
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.mode is FormalizationMode.CONTROLLED_LANGUAGE
    goal = candidate.end_goal

    assert goal.property_class is PropertyClass.EXISTENTIAL_REACHABILITY
    assert QuantifierKind.EXISTS in goal.quantifiers
    assert QuantifierKind.EVENTUALLY in goal.quantifiers
    assert set(goal.actors) == {"scheduler", "worker"}
    assert "phase" in goal.state_variables
    assert "owner" in goal.state_variables
    assert goal.current_state["phase"] == "init"
    assert goal.target_state["phase"] == "ready"
    assert set(goal.transitions) == {"claim", "release"}
    assert goal.environment["network"] == "async"
    assert goal.interference["preempt"] is True
    assert len(goal.assumptions) == 1
    assumption = goal.assumptions[0]
    assert assumption.assumption_class is AssumptionClass.MUST_PROVE
    assert "totally ordered" in assumption.statement
    assert goal.bounds.wall_time_ms == 5000
    assert goal.bounds.max_steps == 32
    assert goal.assurance_target is AuthorityCeiling.BOUNDED
    assert goal.logic_family == "temporal.ltl"
    assert "provider:z3" in goal.provider_ids
    assert "receipt:kernel" in goal.acceptance_evidence
    assert "proof-receipt" in goal.expected_receipt_classes
    assert goal.proof_claimed is False
    assert goal.completion_claimed is False
    assert goal.authority in {
        AuthorityCeiling.NONE,
        AuthorityCeiling.ADVISORY,
        AuthorityCeiling.CANDIDATE,
    }


def test_controlled_language_round_trip_semantic_identity(
    formalizer: EndGoalFormalizer,
) -> None:
    request = _request()
    original, replayed, digest_a, digest_b = formalizer.round_trip(request)
    assert digest_a == digest_b
    assert original.property_class == replayed.property_class
    assert set(original.quantifiers) == set(replayed.quantifiers)
    assert set(original.actors) == set(replayed.actors)
    assert original.current_state == replayed.current_state
    assert original.target_state == replayed.target_state
    assert set(original.transitions) == set(replayed.transitions)
    assert original.environment == replayed.environment
    assert original.interference == replayed.interference
    assert original.bounds.wall_time_ms == replayed.bounds.wall_time_ms
    assert original.bounds.max_steps == replayed.bounds.max_steps
    assert original.assurance_target == replayed.assurance_target
    assert original.logic_family == replayed.logic_family
    assert set(original.acceptance_evidence) == set(
        replayed.acceptance_evidence
    )
    assert len(original.assumptions) == len(replayed.assumptions)
    assert (
        original.assumptions[0].assumption_class
        == replayed.assumptions[0].assumption_class
    )
    assert (
        original.assumptions[0].statement
        == replayed.assumptions[0].statement
    )


def test_render_controlled_language_is_deterministic(
    formalizer: EndGoalFormalizer,
) -> None:
    result = formalizer.formalize(_request())
    goal = result.candidates[0].end_goal
    first = render_controlled_language(goal)
    second = EndGoalFormalizer.render_controlled_language(goal)
    assert first == second
    assert "PROPERTY existential_reachability" in first
    assert "ACTOR scheduler" in first
    assert "ASSUME must_prove:" in first


def test_render_controlled_english_mentions_property(
    formalizer: EndGoalFormalizer,
) -> None:
    result = formalizer.formalize(_request())
    goal = result.candidates[0].end_goal
    english = render_controlled_english(goal)
    assert "existential reachability" in english
    assert "scheduler" in english
    assert result.candidates[0].controlled_english


def test_round_trip_twice_is_stable(formalizer: EndGoalFormalizer) -> None:
    request = _request()
    _, mid, d1, d2 = formalizer.round_trip(request)
    assert d1 == d2
    rendered = render_controlled_language(mid)
    again = formalizer.formalize(
        _request(text=rendered, prefer_controlled_language=True)
    )
    assert again.candidates
    third = again.candidates[0].end_goal
    # Re-render and compare semantic digests via another round trip.
    r2 = EndGoalFormalizerRequest(
        caller_text=render_controlled_language(third),
        source=_source(),
        goal_id="goal:lease-ready",
        known_identifiers=request.known_identifiers,
        prefer_controlled_language=True,
    )
    _, _, d3, d4 = formalizer.round_trip(r2)
    assert d3 == d4


# ---------------------------------------------------------------------------
# Prose path
# ---------------------------------------------------------------------------


def test_prose_existential_reachability(formalizer: EndGoalFormalizer) -> None:
    text = (
        "The system reaches ready from init via claim under fair scheduling. "
        "Actors: scheduler, worker. "
        "Assume must_prove: tokens are totally ordered. "
        "Assurance bounded. Accept receipt:kernel. "
        "Logic temporal.ltl. max_steps=32"
    )
    result = formalizer.formalize(
        _request(
            text=text,
            prefer_controlled_language=False,
            known_identifiers=(
                "scheduler",
                "worker",
                "ready",
                "init",
                "claim",
            ),
        )
    )
    assert result.status is FormalizationStatus.CANDIDATE
    goal = result.candidates[0].end_goal
    assert goal.property_class is PropertyClass.EXISTENTIAL_REACHABILITY
    assert QuantifierKind.EXISTS in goal.quantifiers
    assert goal.target_state.get("phase") == "ready"
    assert goal.current_state.get("phase") == "init"
    assert "claim" in goal.transitions
    assert goal.environment.get("scheduler") == "fair"
    assert any("totally ordered" in a.statement for a in goal.assumptions)
    assert goal.bounds.max_steps == 32
    assert "receipt:kernel" in goal.acceptance_evidence


def test_prose_universal_reachability(formalizer: EndGoalFormalizer) -> None:
    text = "Every execution eventually reaches ready."
    result = formalizer.formalize(
        _request(
            text=text,
            prefer_controlled_language=False,
            known_identifiers=("ready",),
        )
    )
    goal = result.candidates[0].end_goal
    assert goal.property_class is PropertyClass.UNIVERSAL_REACHABILITY
    assert QuantifierKind.FORALL in goal.quantifiers
    assert QuantifierKind.EVENTUALLY in goal.quantifiers


def test_prose_invariance(formalizer: EndGoalFormalizer) -> None:
    text = "The ready flag remains an invariant after initialization."
    result = formalizer.formalize(
        _request(text=text, prefer_controlled_language=False)
    )
    goal = result.candidates[0].end_goal
    assert goal.property_class is PropertyClass.INVARIANCE
    assert QuantifierKind.ALWAYS in goal.quantifiers


def test_prose_termination(formalizer: EndGoalFormalizer) -> None:
    text = "The program terminates within 1000 ms."
    result = formalizer.formalize(
        _request(text=text, prefer_controlled_language=False)
    )
    goal = result.candidates[0].end_goal
    assert goal.property_class is PropertyClass.TERMINATION
    assert goal.bounds.wall_time_ms == 1000


# ---------------------------------------------------------------------------
# Phrase-to-clause provenance / spans
# ---------------------------------------------------------------------------


def test_every_clause_maps_to_prompt_or_repository_spans(
    formalizer: EndGoalFormalizer,
) -> None:
    result = formalizer.formalize(_request())
    goal = result.candidates[0].end_goal
    assert goal.provenance, "expected non-empty phrase provenance"

    prompt_refs = set(goal.source.source_ref_ids)
    assert "source:prompt" in prompt_refs or any(
        "prompt" in ref for ref in prompt_refs
    )
    assert "source:lease.py" in prompt_refs

    # Every provenance row binds source refs and span ids with ordered offsets.
    for item in goal.provenance:
        assert item.phrase
        assert item.clause_id.startswith("clause:")
        assert item.source_ref_ids, f"missing source refs on {item.clause_id}"
        assert item.span_ids, f"missing span ids on {item.clause_id}"
        assert item.end_offset >= item.start_offset
        # Spans must reference the prompt or a repository source.
        for ref in item.source_ref_ids:
            assert ref in prompt_refs or ref.startswith("source:")

    # Field families that were populated must appear in clause ids.
    clause_blob = " ".join(p.clause_id for p in goal.provenance)
    for kind in (
        "prompt",
        "property",
        "actor",
        "target",
        "transition",
        "assume",
        "bound",
    ):
        assert kind in clause_blob, f"missing provenance for {kind}"


def test_prose_provenance_offsets_lie_within_prompt(
    formalizer: EndGoalFormalizer,
) -> None:
    text = "Some execution reaches ready via claim."
    result = formalizer.formalize(
        _request(
            text=text,
            prefer_controlled_language=False,
            known_identifiers=("ready", "claim"),
        )
    )
    goal = result.candidates[0].end_goal
    length = len(text)
    for item in goal.provenance:
        assert 0 <= item.start_offset <= length
        assert 0 <= item.end_offset <= length
        if item.end_offset > item.start_offset and item.phrase in text:
            assert text[item.start_offset : item.end_offset] == item.phrase or (
                item.phrase.lower() in text.lower()
            )


# ---------------------------------------------------------------------------
# Hidden assumptions and ungrounded identifiers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "We have a hidden assumption that the heap is well-formed.",
        "Implicitly assume the lock is held.",
        "We assume without stating that memory is infinite.",
        "The claim is obviously true under fair scheduling.",
        "Take for granted that clocks are synchronized.",
        "W.l.o.g. the graph is connected.",
    ],
)
def test_hidden_assumptions_are_rejected(
    formalizer: EndGoalFormalizer, phrase: str
) -> None:
    result = formalizer.formalize(
        _request(text=phrase, prefer_controlled_language=False)
    )
    assert result.status is FormalizationStatus.REJECTED
    assert result.candidates == ()
    assert any(r.code == "hidden_assumption" for r in result.rejections)
    assert result.admitted is False


def test_declared_assume_is_accepted(formalizer: EndGoalFormalizer) -> None:
    text = (
        "PROPERTY safety\n"
        "ASSUME hypothetical: tokens are totally ordered\n"
        "TARGET phase=ready\n"
    )
    result = formalizer.formalize(
        _request(
            text=text,
            known_identifiers=("phase", "ready", "tokens"),
        )
    )
    assert result.status is FormalizationStatus.CANDIDATE
    goal = result.candidates[0].end_goal
    assert any("totally ordered" in a.statement for a in goal.assumptions)


def test_ungrounded_overlay_identifier_rejected(
    formalizer: EndGoalFormalizer,
) -> None:
    result = formalizer.formalize(
        _request(
            text="PROPERTY safety\nTARGET phase=ready\n",
            known_identifiers=("phase", "ready"),
            intent_overlay={
                "actors": ["ghost_actor_not_in_prompt"],
            },
        )
    )
    assert result.status is FormalizationStatus.REJECTED
    assert any(r.code == "ungrounded_identifier" for r in result.rejections)


def test_hidden_overlay_assumption_rejected(
    formalizer: EndGoalFormalizer,
) -> None:
    result = formalizer.formalize(
        _request(
            text="PROPERTY safety\nTARGET phase=ready\n",
            known_identifiers=("phase", "ready"),
            intent_overlay={
                "assumptions": [
                    {
                        "statement": "heap is secretly well formed",
                        "assumption_class": "trusted",
                    }
                ]
            },
        )
    )
    assert result.status is FormalizationStatus.REJECTED
    assert any(r.code == "hidden_assumption" for r in result.rejections)


def test_denied_identifier_rejected(formalizer: EndGoalFormalizer) -> None:
    text = (
        "PROPERTY safety\n"
        "ACTOR evil\n"
        "TARGET phase=ready\n"
    )
    result = formalizer.formalize(
        _request(
            text=text,
            known_identifiers=("evil", "phase", "ready"),
            meta={"denied_identifiers": ["evil"]},
        )
    )
    assert result.status is FormalizationStatus.REJECTED
    assert any(r.code == "denied_identifier" for r in result.rejections)


# ---------------------------------------------------------------------------
# Learned parsing is candidate-only
# ---------------------------------------------------------------------------


def test_learned_proposal_is_candidate_only(
    formalizer: EndGoalFormalizer,
) -> None:
    text = (
        "PROPERTY existential_reachability\n"
        "ACTOR scheduler\n"
        "TARGET phase=ready\n"
        "TRANSITION claim\n"
    )
    learned = {
        "property_class": "universal_reachability",
        "quantifiers": ["forall", "eventually"],
        "actors": ["scheduler"],
        "state_variables": ["phase"],
        "transitions": ["claim"],
        "target_state": {"phase": "ready"},
        "assurance_target": "theorem",  # must be demoted
    }
    result = formalizer.formalize(
        _request(
            text=text,
            known_identifiers=("scheduler", "phase", "ready", "claim"),
            learned_proposal=learned,
        )
    )
    assert result.status is FormalizationStatus.CANDIDATE
    assert len(result.candidates) >= 2
    learned_candidates = [
        c
        for c in result.candidates
        if c.mode is FormalizationMode.LEARNED_CANDIDATE
    ]
    assert learned_candidates, "expected a learned candidate"
    learned_c = learned_candidates[0]
    assert learned_c.admitted is False
    assert learned_c.selected is False
    assert learned_c.authority is AuthorityCeiling.CANDIDATE
    assert learned_c.end_goal.authority is AuthorityCeiling.CANDIDATE
    assert learned_c.end_goal.proof_claimed is False
    assert learned_c.end_goal.completion_claimed is False
    # Demoted assurance — never theorem from learned path.
    assert learned_c.end_goal.assurance_target is AuthorityCeiling.CANDIDATE


def test_learned_proposal_cannot_claim_admission(
    formalizer: EndGoalFormalizer,
) -> None:
    with pytest.raises(EndGoalFormalizerError, match="cannot claim"):
        _request(
            learned_proposal={
                "property_class": "safety",
                "admitted": True,
            }
        )


def test_learned_proposal_ungrounded_identifier_rejected(
    formalizer: EndGoalFormalizer,
) -> None:
    text = "PROPERTY safety\nTARGET phase=ready\n"
    result = formalizer.formalize(
        _request(
            text=text,
            known_identifiers=("phase", "ready"),
            learned_proposal={
                "property_class": "safety",
                "actors": ["not_in_source_at_all"],
            },
        )
    )
    # Deterministic candidate may still succeed; learned path is rejected.
    assert any(
        r.code == "learned_ungrounded_identifier" for r in result.rejections
    )
    assert all(
        c.mode is not FormalizationMode.LEARNED_CANDIDATE
        for c in result.candidates
    )


def test_learned_hidden_assumption_rejected(
    formalizer: EndGoalFormalizer,
) -> None:
    text = "PROPERTY safety\nTARGET phase=ready\n"
    result = formalizer.formalize(
        _request(
            text=text,
            known_identifiers=("phase", "ready"),
            learned_proposal={
                "property_class": "safety",
                "assumptions": [
                    {"statement": "secret well-formed heap"},
                ],
            },
        )
    )
    assert any(
        r.code == "learned_hidden_assumption" for r in result.rejections
    )


# ---------------------------------------------------------------------------
# Unsupported / underspecified remain explicit
# ---------------------------------------------------------------------------


def test_underspecified_prose_is_explicit(
    formalizer: EndGoalFormalizer,
) -> None:
    text = "Please make it correct somehow."
    result = formalizer.formalize(
        _request(text=text, prefer_controlled_language=False)
    )
    assert result.status in {
        FormalizationStatus.UNDERSPECIFIED,
        FormalizationStatus.UNSUPPORTED,
        FormalizationStatus.CANDIDATE,
    }
    if result.candidates:
        goal = result.candidates[0].end_goal
        # Property may be unspecified and listed as unsupported/underspecified.
        assert (
            goal.property_class is PropertyClass.UNSPECIFIED
            or "underspecified_property_class" in goal.unsupported_semantics
            or "property_class" in result.underspecified_fields
        )
    assert (
        "underspecified_property_class" in result.unsupported_semantics
        or "property_class" in result.underspecified_fields
        or (
            result.candidates
            and result.candidates[0].end_goal.property_class
            is PropertyClass.UNSPECIFIED
        )
    )


def test_explicit_unsupported_directive(
    formalizer: EndGoalFormalizer,
) -> None:
    text = (
        "PROPERTY safety\n"
        "UNSUPPORTED continuous_time_dynamics\n"
        "TARGET phase=ready\n"
    )
    result = formalizer.formalize(
        _request(
            text=text,
            known_identifiers=("phase", "ready", "continuous_time_dynamics"),
        )
    )
    assert result.candidates
    goal = result.candidates[0].end_goal
    assert "continuous_time_dynamics" in goal.unsupported_semantics
    assert "continuous_time_dynamics" in result.unsupported_semantics


def test_prose_unsupported_marker(formalizer: EndGoalFormalizer) -> None:
    text = (
        "The system reaches ready. Unsupported continuous_time_dynamics."
    )
    result = formalizer.formalize(
        _request(
            text=text,
            prefer_controlled_language=False,
            known_identifiers=("ready", "continuous_time_dynamics"),
        )
    )
    assert result.candidates
    assert (
        "continuous_time_dynamics"
        in result.candidates[0].end_goal.unsupported_semantics
    )


# ---------------------------------------------------------------------------
# Mapping entry / stability
# ---------------------------------------------------------------------------


def test_formalize_accepts_mapping(formalizer: EndGoalFormalizer) -> None:
    request = _request()
    payload = request.to_dict()
    # Ensure deep copy is independent.
    payload_copy = copy.deepcopy(payload)
    result = formalizer.formalize(payload_copy)
    assert result.status is FormalizationStatus.CANDIDATE
    assert payload_copy["caller_text"] == payload["caller_text"]


def test_content_ids_change_when_semantics_change(
    formalizer: EndGoalFormalizer,
) -> None:
    a = formalizer.formalize(_request()).candidates[0].end_goal.content_id
    alt = _controlled_language_doc().replace(
        "existential_reachability", "universal_reachability"
    ).replace("QUANTIFIER exists", "QUANTIFIER forall")
    b = (
        formalizer.formalize(_request(text=alt))
        .candidates[0]
        .end_goal.content_id
    )
    assert a != b


def test_assumption_source_spans_are_bound(
    formalizer: EndGoalFormalizer,
) -> None:
    result = formalizer.formalize(_request())
    assumption = result.candidates[0].end_goal.assumptions[0]
    assert assumption.source.tree_id
    assert assumption.source.source_ref_ids
    assert assumption.source.span_ids
    assert assumption.authority is AuthorityCeiling.NONE
    assert assumption.reviewable is True
