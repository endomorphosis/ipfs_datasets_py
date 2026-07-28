"""Unit tests for LegalConstraintQuery@1 applicability selection.

Covers hard filters (jurisdiction/territory/subject matter, authority,
temporal lifecycle, actor/subject/resource/purpose/threshold, definitions,
cross-references, exceptions, premise taint/provenance), competing-authority
resolution, contradiction preservation, review/abstain on unresolved cases,
and the invariant that retrieval rank never selects authority.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.formalization.constraint_contracts import (
    ApplicabilityStatus,
    PremiseSelectionMethod,
)
from ipfs_datasets_py.logic.legal_ir.constraint_query import (
    LEGAL_APPLICABILITY_EVIDENCE_INTERFACE,
    LEGAL_CONSTRAINT_QUERY_INTERFACE,
    LEGAL_HARD_FILTER_DIMENSIONS,
    LegalApplicabilityEvidence,
    LegalConstraintDisposition,
    LegalConstraintQuery,
    LegalConstraintQueryError,
    LegalConstraintRecord,
    LegalModality,
    LegalPremiseTaintStatus,
    LegalSelectionDisposition,
    select_applicable_legal_constraints,
)


DIGEST_A = "sha256:" + ("a" * 64)


def _query(**overrides: object) -> LegalConstraintQuery:
    base: dict[str, object] = dict(
        query_id="query:or-disclosure",
        jurisdiction="US-OR",
        as_of="2024-06-15",
        territory="Multnomah",
        subject_matter="public-records",
        actor="agency",
        subject="requester",
        resource="records",
        purpose="disclosure",
        invocation_digest=DIGEST_A,
        selection_budget=16,
    )
    base.update(overrides)
    return LegalConstraintQuery(**base)  # type: ignore[arg-type]


def _record(**overrides: object) -> LegalConstraintRecord:
    base: dict[str, object] = dict(
        constraint_id="prov:obligation-publish",
        modality=LegalModality.OBLIGATION,
        jurisdictions=("US-OR",),
        territories=("Multnomah",),
        subject_matters=("public-records",),
        authority_id="auth:or-legislature",
        hierarchy_rank=50,
        precedence=10,
        enacted_date="2019-01-01",
        effective_from="2020-01-01",
        actors=("agency",),
        subjects=("requester",),
        resources=("records",),
        purposes=("disclosure",),
        source_ref_ids=("source:or-192",),
        provenance_ids=("prov:or-192",),
        premise_taint=LegalPremiseTaintStatus.CLEAN,
        trusted_source=True,
        reviewed=True,
        statement="Agency shall disclose public records on request.",
        conflict_key="public-records-disclosure",
        retrieval_rank=99,
        retrieval_score=0.01,
    )
    base.update(overrides)
    return LegalConstraintRecord(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Contract shape / immutability
# ---------------------------------------------------------------------------


def test_query_interface_identity_and_roundtrip() -> None:
    query = _query()
    assert query.INTERFACE == LEGAL_CONSTRAINT_QUERY_INTERFACE
    assert query.digest.startswith("sha256:")
    restored = LegalConstraintQuery.from_json(query.to_json())
    assert restored.digest == query.digest
    assert restored.jurisdiction == "US-OR"
    with pytest.raises(FrozenInstanceError):
        query.jurisdiction = "US-CA"  # type: ignore[misc]


def test_query_requires_jurisdiction_and_as_of() -> None:
    with pytest.raises(LegalConstraintQueryError):
        LegalConstraintQuery(query_id="q", jurisdiction="", as_of="2024-01-01")
    with pytest.raises(LegalConstraintQueryError):
        LegalConstraintQuery(query_id="q", jurisdiction="US-OR", as_of="")
    with pytest.raises(LegalConstraintQueryError):
        LegalConstraintQuery(
            query_id="q", jurisdiction="US-OR", as_of="not-a-date"
        )


def test_hard_filter_dimensions_are_documented() -> None:
    required = {
        "jurisdiction",
        "territory",
        "subject_matter",
        "authority",
        "temporal",
        "actor",
        "subject",
        "resource",
        "purpose",
        "threshold",
        "provenance",
        "premise_taint",
        "definition_refs",
        "cross_references",
        "exceptions",
    }
    assert required.issubset(set(LEGAL_HARD_FILTER_DIMENSIONS))


# ---------------------------------------------------------------------------
# Happy path / jurisdiction binding
# ---------------------------------------------------------------------------


def test_selects_applicable_constraint_under_matching_scope() -> None:
    result = _query().select([_record()])
    assert result.disposition is LegalSelectionDisposition.APPLICABLE
    assert not result.abstains
    assert result.allows_action
    assert len(result.selected) == 1
    assert result.selected[0].constraint_id == "prov:obligation-publish"
    assert result.evidence.status is LegalSelectionDisposition.APPLICABLE
    assert result.evidence.retrieval_rank_used_for_authority is False
    assert result.evidence.shared_applicability is not None
    assert (
        result.evidence.shared_applicability.status
        is ApplicabilityStatus.APPLICABLE
    )
    assert not result.grants_security_authorization
    assert not result.grants_execution_authority


def test_jurisdiction_mismatch_is_not_applicable() -> None:
    result = _query(jurisdiction="US-CA").select([_record()])
    assert result.disposition is LegalSelectionDisposition.NOT_APPLICABLE
    assert result.selected == ()
    assessment = result.assessments[0]
    assert assessment.disposition is LegalConstraintDisposition.NOT_APPLICABLE
    assert "jurisdiction_mismatch" in assessment.reason_codes


def test_territory_and_subject_matter_mutations_change_applicability() -> None:
    base = _record()
    ok = _query().select([base])
    assert ok.disposition is LegalSelectionDisposition.APPLICABLE

    wrong_territory = _query(territory="Lane").select([base])
    assert wrong_territory.disposition is LegalSelectionDisposition.NOT_APPLICABLE

    wrong_matter = _query(subject_matter="land-use").select([base])
    assert wrong_matter.disposition is LegalSelectionDisposition.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Temporal: enactment / effective / repeal / supersession markers
# ---------------------------------------------------------------------------


def test_not_yet_effective_is_excluded() -> None:
    result = _query(as_of="2019-06-01").select(
        [_record(effective_from="2020-01-01")]
    )
    assert result.selected == ()
    assert (
        result.assessments[0].disposition
        is LegalConstraintDisposition.NOT_YET_EFFECTIVE
    )


def test_expired_and_repealed_windows() -> None:
    expired = _query(as_of="2025-01-01").select(
        [_record(effective_until="2024-12-31")]
    )
    assert (
        expired.assessments[0].disposition is LegalConstraintDisposition.EXPIRED
    )

    repealed = _query().select(
        [_record(repealed_by="prov:repealer", repeal_date="2023-01-01")]
    )
    assert (
        repealed.assessments[0].disposition is LegalConstraintDisposition.REPEALED
    )


def test_marked_superseded_on_record() -> None:
    result = _query().select(
        [_record(superseded_by="prov:v2", superseded_date="2022-01-01")]
    )
    assert (
        result.assessments[0].disposition
        is LegalConstraintDisposition.SUPERSEDED
    )


def test_express_supersession_between_candidates() -> None:
    old = _record(
        constraint_id="prov:old",
        precedence=1,
        hierarchy_rank=10,
        retrieval_rank=0,
    )
    new = _record(
        constraint_id="prov:new",
        precedence=5,
        hierarchy_rank=10,
        supersedes=("prov:old",),
        retrieval_rank=50,
    )
    result = _query().select([old, new])
    assert result.disposition is LegalSelectionDisposition.APPLICABLE
    assert [item.constraint_id for item in result.selected] == ["prov:new"]
    old_assessment = next(
        item for item in result.assessments if item.constraint_id == "prov:old"
    )
    assert old_assessment.disposition is LegalConstraintDisposition.SUPERSEDED
    assert "prov:new" in old_assessment.defeated_by
    assert any(item.kind == "supersession" for item in result.contradictions)
    assert all(
        item.resolved for item in result.contradictions if item.kind == "supersession"
    )


# ---------------------------------------------------------------------------
# Actor / subject / resource / purpose / threshold
# ---------------------------------------------------------------------------


def test_actor_resource_purpose_must_match() -> None:
    result = _query(actor="contractor").select([_record()])
    assert result.disposition is LegalSelectionDisposition.NOT_APPLICABLE
    assert "actor_mismatch" in result.assessments[0].reason_codes

    result = _query(resource="payroll").select([_record()])
    assert "resource_mismatch" in result.assessments[0].reason_codes

    result = _query(purpose="marketing").select([_record()])
    assert "purpose_mismatch" in result.assessments[0].reason_codes


def test_threshold_hard_filter() -> None:
    record = _record(thresholds={"fee_usd": {"op": "lte", "value": 25}})
    ok = _query(thresholds={"fee_usd": 10}).select([record])
    assert ok.disposition is LegalSelectionDisposition.APPLICABLE

    too_high = _query(thresholds={"fee_usd": 40}).select([record])
    assert too_high.disposition is LegalSelectionDisposition.NOT_APPLICABLE
    assert any(
        code.startswith("threshold_unsatisfied")
        for code in too_high.assessments[0].reason_codes
    )

    missing = _query(thresholds={}).select([record])
    assert missing.disposition is LegalSelectionDisposition.INDETERMINATE


# ---------------------------------------------------------------------------
# Definitions, cross-references, exceptions
# ---------------------------------------------------------------------------


def test_unresolved_definition_refs_fail_closed() -> None:
    record = _record(definition_refs=("def:public-body",))
    result = _query().select([record])
    assert result.disposition is LegalSelectionDisposition.INDETERMINATE
    assert "unresolved_definition_refs" in result.assessments[0].reason_codes

    resolved = _query().select(
        [record], known_definition_ids=("def:public-body",)
    )
    assert resolved.disposition is LegalSelectionDisposition.APPLICABLE


def test_unresolved_cross_references_fail_closed() -> None:
    record = _record(cross_references=("xref:or-192-501",))
    result = _query().select([record])
    assert result.disposition is LegalSelectionDisposition.INDETERMINATE

    via_candidate = _record(
        constraint_id="xref:or-192-501",
        modality=LegalModality.DEFINITION,
        conflict_key="defs",
    )
    both = _query().select([record, via_candidate])
    assert both.disposition is LegalSelectionDisposition.APPLICABLE
    assert "prov:obligation-publish" in {
        item.constraint_id for item in both.selected
    }


def test_applicable_exception_defeats_target_without_erasure() -> None:
    obligation = _record(
        constraint_id="prov:duty",
        modality=LegalModality.OBLIGATION,
        exception_ids=("prov:exc",),
    )
    exception = _record(
        constraint_id="prov:exc",
        modality=LegalModality.EXCEPTION,
        exception_to=("prov:duty",),
        conflict_key="public-records-disclosure",
        precedence=20,
    )
    result = _query().select([obligation, exception])
    # Exception remains selected/active; duty is defeated but preserved.
    duty = next(item for item in result.assessments if item.constraint_id == "prov:duty")
    exc = next(item for item in result.assessments if item.constraint_id == "prov:exc")
    assert duty.disposition is LegalConstraintDisposition.DEFEATED
    assert not duty.active
    assert "prov:exc" in duty.defeated_by
    assert exc.active
    assert "exception_applied" in exc.reason_codes
    assert "exceptions" in exc.matched_dimensions


def test_unresolved_exception_reference_is_indeterminate() -> None:
    record = _record(exception_ids=("prov:missing-exc",))
    result = _query().select([record])
    assert result.disposition is LegalSelectionDisposition.INDETERMINATE
    assert "unresolved_exception" in result.assessments[0].reason_codes


# ---------------------------------------------------------------------------
# Premise taint / provenance
# ---------------------------------------------------------------------------


def test_tainted_premise_requires_review_and_never_applies() -> None:
    result = _query().select(
        [_record(premise_taint=LegalPremiseTaintStatus.TAINTED)]
    )
    assert result.disposition is LegalSelectionDisposition.REVIEW_REQUIRED
    assert result.abstains
    assert result.assessments[0].disposition is LegalConstraintDisposition.TAINTED
    assert result.selected == ()


def test_missing_provenance_or_untrusted_source_fails_closed() -> None:
    missing_prov = _query().select([_record(provenance_ids=())])
    assert missing_prov.disposition is LegalSelectionDisposition.REVIEW_REQUIRED

    untrusted = _query().select([_record(trusted_source=False)])
    assert untrusted.disposition is LegalSelectionDisposition.REVIEW_REQUIRED

    unreviewed = _query().select([_record(reviewed=False)])
    assert unreviewed.disposition is LegalSelectionDisposition.REVIEW_REQUIRED

    ungrounded = _query().select([_record(source_ref_ids=())])
    assert ungrounded.disposition is LegalSelectionDisposition.REVIEW_REQUIRED


# ---------------------------------------------------------------------------
# Competing authorities / contradictions / bounded selection
# ---------------------------------------------------------------------------


def test_higher_authority_preempts_lower_on_opposed_modalities() -> None:
    federal = _record(
        constraint_id="prov:federal-prohibition",
        modality=LegalModality.PROHIBITION,
        authority_id="auth:federal",
        hierarchy_rank=100,
        precedence=1,
        retrieval_rank=5,
        statement="Disclosure is prohibited.",
    )
    state = _record(
        constraint_id="prov:state-permission",
        modality=LegalModality.PERMISSION,
        authority_id="auth:or-legislature",
        hierarchy_rank=50,
        precedence=99,
        retrieval_rank=0,
        statement="Disclosure is permitted.",
    )
    result = _query().select([state, federal])
    assert result.disposition is LegalSelectionDisposition.APPLICABLE
    assert [item.constraint_id for item in result.selected] == [
        "prov:federal-prohibition"
    ]
    loser = next(
        item
        for item in result.assessments
        if item.constraint_id == "prov:state-permission"
    )
    assert loser.disposition is LegalConstraintDisposition.SUPERSEDED
    assert "higher_authority_preempts" in loser.reason_codes
    assert any(item.kind == "authority_preemption" for item in result.contradictions)


def test_equal_authority_conflict_is_preserved_and_abstains() -> None:
    left = _record(
        constraint_id="prov:prohibition",
        modality=LegalModality.PROHIBITION,
        hierarchy_rank=50,
        precedence=10,
        retrieval_rank=0,
    )
    right = _record(
        constraint_id="prov:permission",
        modality=LegalModality.PERMISSION,
        hierarchy_rank=50,
        precedence=10,
        retrieval_rank=1,
    )
    result = _query().select([left, right])
    assert result.disposition is LegalSelectionDisposition.CONFLICT
    assert result.abstains
    assert result.selected == ()
    assert any(not item.resolved for item in result.contradictions)
    for assessment in result.assessments:
        assert assessment.disposition is LegalConstraintDisposition.CONFLICTING


def test_retrieval_rank_never_selects_authority() -> None:
    """High retrieval rank on a weaker authority cannot beat hierarchy."""

    weak_but_top_ranked = _record(
        constraint_id="prov:weak",
        modality=LegalModality.PERMISSION,
        hierarchy_rank=1,
        precedence=1,
        retrieval_rank=0,
        retrieval_score=0.99,
    )
    strong_but_low_ranked = _record(
        constraint_id="prov:strong",
        modality=LegalModality.PROHIBITION,
        hierarchy_rank=90,
        precedence=1,
        retrieval_rank=500,
        retrieval_score=0.01,
    )
    result = _query().select([weak_but_top_ranked, strong_but_low_ranked])
    assert result.selected[0].constraint_id == "prov:strong"
    assert result.evidence.retrieval_rank_used_for_authority is False
    assert "retrieval_rank" not in result.evidence.authority_selection_keys
    assert result.evidence.selection_method is PremiseSelectionMethod.HARD_FILTER
    # Advisory rank may appear in assessments but not as selection authority.
    ranks = {
        item.constraint_id: item.retrieval_rank for item in result.assessments
    }
    assert ranks["prov:weak"] == 0
    assert ranks["prov:strong"] == 500


def test_evidence_rejects_retrieval_rank_authority_flag() -> None:
    query = _query()
    result = query.select([_record()])
    payload = result.evidence.to_dict()
    payload["retrieval_rank_used_for_authority"] = True
    with pytest.raises(LegalConstraintQueryError, match="retrieval rank"):
        LegalApplicabilityEvidence.from_dict(payload)


def test_selection_budget_bounds_without_using_retrieval_rank() -> None:
    records = [
        _record(
            constraint_id=f"prov:{idx}",
            hierarchy_rank=idx,
            precedence=idx,
            retrieval_rank=100 - idx,
            conflict_key=f"key-{idx}",
            statement=f"Norm {idx}",
        )
        for idx in range(1, 6)
    ]
    result = _query(selection_budget=2).select(records)
    assert result.disposition is LegalSelectionDisposition.APPLICABLE
    assert len(result.selected) == 2
    # Highest hierarchy_rank wins budget slots, not lowest retrieval_rank.
    selected_ids = {item.constraint_id for item in result.selected}
    assert selected_ids == {"prov:5", "prov:4"}
    assert result.evidence.selected_count == 2
    assert result.evidence.selection_budget == 2


# ---------------------------------------------------------------------------
# Coverage / empty corpus / temporal binding
# ---------------------------------------------------------------------------


def test_empty_candidates_yield_coverage_gap_abstain() -> None:
    result = _query().select([])
    assert result.disposition is LegalSelectionDisposition.COVERAGE_GAP
    assert result.abstains
    assert result.evidence.coverage_gaps
    assert result.evidence.INTERFACE == LEGAL_APPLICABILITY_EVIDENCE_INTERFACE


def test_jurisdiction_coverage_gap_when_no_candidate_matches() -> None:
    result = _query(jurisdiction="US-WA").select(
        [_record(jurisdictions=("US-OR",))]
    )
    # Mismatch is not_applicable rather than gap when candidates exist but miss.
    assert result.disposition is LegalSelectionDisposition.NOT_APPLICABLE


def test_temporal_applicability_binding_excludes_law_versions() -> None:
    record = _record(law_version_id="law:v1")
    excluded = _query().select(
        [record],
        temporal_applicability={
            "proof_safe": True,
            "applicable_law_version_ids": (),
        },
    )
    assert excluded.disposition in {
        LegalSelectionDisposition.NOT_APPLICABLE,
        LegalSelectionDisposition.COVERAGE_GAP,
    }

    included = _query().select(
        [record],
        temporal_applicability={
            "proof_safe": True,
            "applicable_law_version_ids": ("law:v1",),
        },
    )
    assert included.disposition is LegalSelectionDisposition.APPLICABLE
    assert included.evidence.temporal_proof_safe is True

    unsafe = _query().select(
        [record],
        temporal_applicability={
            "proof_safe": False,
            "applicable_law_version_ids": ("law:v1",),
        },
    )
    assert unsafe.disposition is LegalSelectionDisposition.REVIEW_REQUIRED
    assert unsafe.abstains


# ---------------------------------------------------------------------------
# Evidence / premises / module API
# ---------------------------------------------------------------------------


def test_selected_premises_are_hard_filtered_not_rank_authority() -> None:
    result = _query().select([_record()])
    premises = result.evidence.selected_premises
    assert premises is not None
    assert premises.selection_method is PremiseSelectionMethod.HARD_FILTER
    assert premises.premises[0].selection_method is PremiseSelectionMethod.HARD_FILTER
    meta = premises.premises[0].metadata.to_dict()
    assert meta.get("retrieval_rank_ignored") == 99


def test_function_and_method_entry_points_agree() -> None:
    query = _query()
    candidates = [_record()]
    via_method = query.select(candidates)
    via_function = select_applicable_legal_constraints(query, candidates)
    assert via_method.digest == via_function.digest
    assert via_method.evidence.digest == via_function.evidence.digest


def test_evidence_roundtrip_json() -> None:
    result = _query().select([_record()])
    raw = result.evidence.to_json()
    restored = LegalApplicabilityEvidence.from_json(raw) if hasattr(
        LegalApplicabilityEvidence, "from_json"
    ) else LegalApplicabilityEvidence.from_dict(json.loads(raw))
    # from_json may not exist; use from_dict
    restored = LegalApplicabilityEvidence.from_dict(json.loads(raw))
    assert restored.status is result.evidence.status
    assert restored.selected_constraint_ids == result.evidence.selected_constraint_ids
    assert restored.retrieval_rank_used_for_authority is False


def test_record_rejects_wildcards_and_bad_windows() -> None:
    with pytest.raises(LegalConstraintQueryError):
        _record(jurisdictions=("*",))
    with pytest.raises(LegalConstraintQueryError):
        _record(effective_from="2024-01-01", effective_until="2020-01-01")


def test_precedence_resolves_same_hierarchy_opposed_modalities() -> None:
    low = _record(
        constraint_id="prov:low",
        modality=LegalModality.PERMISSION,
        hierarchy_rank=50,
        precedence=1,
    )
    high = _record(
        constraint_id="prov:high",
        modality=LegalModality.PROHIBITION,
        hierarchy_rank=50,
        precedence=20,
    )
    result = _query().select([low, high])
    assert [item.constraint_id for item in result.selected] == ["prov:high"]
    loser = next(item for item in result.assessments if item.constraint_id == "prov:low")
    assert "higher_precedence_provision" in loser.reason_codes


def test_query_from_dict_rejects_unknown_interface() -> None:
    payload = _query().to_dict()
    payload["interface"] = "LegalConstraintQuery@9"
    with pytest.raises(LegalConstraintQueryError):
        LegalConstraintQuery.from_dict(payload)


def test_missing_effective_date_is_indeterminate_under_closed_world() -> None:
    result = _query().select(
        [_record(effective_from="", enacted_date="")]
    )
    assert result.disposition is LegalSelectionDisposition.INDETERMINATE
    assert "missing_effective_date" in result.assessments[0].reason_codes
