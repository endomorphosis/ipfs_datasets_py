"""Artifact-bound declarations do not create semantic or execution authority."""
import base64
import hashlib
from copy import deepcopy

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_qualification as qualification
from ipfs_datasets_py.logic.autoformal.corpus_contracts import CorpusContractError, seal_record


def cid(text):
    encoded = b"\x01\x55\x12\x20" + hashlib.sha256(text.encode()).digest()
    return "b" + base64.b32encode(encoded).decode().lower().rstrip("=")


ARTIFACT = cid("the exact interpreted artifact")
OTHER_ARTIFACT = cid("a different artifact")
PROFILE = "declared-unary-definition-norm/v1"


def dimension(status, *evidence):
    return {"status": status, "evidence_cids": list(evidence)}


def positive_dimensions(*, proof=False):
    statuses = {
        "processing": "complete", "source_integrity": "verified", "interpretation": "reviewed",
        "representation": "supported_complete", "dependency": "resolved",
        "native_translation": "passed", "lean_compilation": "passed",
    }
    result = {key: dimension(value, cid("evidence for " + key)) for key, value in statuses.items()}
    result["proof"] = dimension("discharged", cid("proof receipt")) if proof else dimension("not_requested")
    return result


def prepared(dimensions=None, **kwargs):
    return qualification.prepare_qualification(artifact_cid=ARTIFACT, profile=PROFILE,
                                               dimensions=dimensions, **kwargs)


def checked(record):
    return qualification.validate_qualification(record, artifact_cid=ARTIFACT, profile=PROFILE)


def views(record):
    return qualification.derive_eligibility(record, artifact_cid=ARTIFACT, profile=PROFILE)


def reseal(record):
    return seal_record({key: value for key, value in record.items() if key not in {"record_cid", "cid_scope"}})


def test_defaults_are_pending_declarations_with_no_authority():
    record = checked(prepared())
    assert {name: row["status"] for name, row in record["dimensions"].items()} == qualification.DEFAULT_STATUSES
    report = views(record)
    assert report["declaration_scope"] == "declared_evidence_only_not_admission"
    assert report["authority_policy_required"] is True
    assert all(view["declared_eligible"] is False and view["blockers"] for view in report["views"].values())
    for key in qualification.AUTHORITY_FIELDS:
        assert record[key] is False
        assert report[key] is False


def test_declared_positive_evidence_enables_views_without_authenticating_it():
    record = prepared(positive_dimensions())
    report = views(record)
    assert report["qualification_cid"] == record["record_cid"]
    assert all(view == {"declared_eligible": True, "blockers": []} for view in report["views"].values())
    assert report["evidence_authenticated"] is False
    assert report["reviewer_authenticated"] is False
    assert report["source_semantics_verified"] is False
    assert report["proof_authority"] is False


def test_candidate_partial_disputed_dependencies_do_not_promote_reviewed_views():
    states = positive_dimensions()
    states.update(interpretation=dimension("disputed"), representation=dimension("supported_partial", cid("partial profile")),
                  dependency=dimension("unresolved"), native_translation=dimension("not_run"),
                  lean_compilation=dimension("not_run"))
    report = views(prepared(states))
    assert report["views"]["candidate_graph"]["declared_eligible"] is True
    assert report["views"]["reviewed_graph"]["declared_eligible"] is False
    assert report["views"]["checked_lean"]["declared_eligible"] is False
    assert {row["dimension"] for row in report["views"]["reviewed_graph"]["blockers"]} == {
        "interpretation", "representation", "dependency"}


def test_build_success_does_not_supply_a_missing_review():
    states = positive_dimensions()
    states["interpretation"] = dimension("candidate")
    record = checked(prepared(states))
    assert record["dimensions"]["lean_compilation"]["status"] == "passed"
    assert views(record)["views"]["checked_lean"]["declared_eligible"] is False


def test_orthogonal_failed_source_is_retained_even_with_a_review_and_build():
    states = positive_dimensions()
    states["source_integrity"] = dimension("failed", cid("source failure"))
    record = checked(prepared(states))
    assert record["dimensions"]["interpretation"]["status"] == "reviewed"
    assert all(view["declared_eligible"] is False for view in views(record)["views"].values())


def test_unsupported_representation_cannot_become_checked_by_compilation():
    states = positive_dimensions()
    states["representation"] = dimension("unsupported")
    report = views(prepared(states))
    assert all(view["declared_eligible"] is False for view in report["views"].values())


@pytest.mark.parametrize("name", list(qualification.STATUS_VALUES))
def test_unknown_dimension_status_is_rejected(name):
    with pytest.raises(CorpusContractError, match="unknown .* status"):
        prepared({name: dimension("invented-success")})


@pytest.mark.parametrize("name,statuses", list(qualification.EVIDENCE_REQUIRED.items()))
def test_every_affirmative_status_requires_real_cid_reference(name, statuses):
    for status in statuses:
        with pytest.raises(CorpusContractError, match="affirmative status requires"):
            prepared({name: dimension(status)}, theorem_requested=name == "proof")


@pytest.mark.parametrize("value", [True, 1, None])
def test_status_values_are_not_coerced(value):
    with pytest.raises(CorpusContractError):
        prepared({"processing": dimension(value)})


@pytest.mark.parametrize("value", [0, 1, "false", None])
def test_theorem_request_is_exact_boolean(value):
    with pytest.raises(CorpusContractError, match="theorem_requested must be boolean"):
        prepared(theorem_requested=value)


def test_requested_theorem_starts_pending_and_blocks_checked_view():
    states = positive_dimensions()
    states.pop("proof")
    record = prepared(states, theorem_requested=True)
    assert record["dimensions"]["proof"] == dimension("pending")
    report = views(record)
    assert report["views"]["reviewed_graph"]["declared_eligible"] is True
    assert report["views"]["checked_lean"]["blockers"] == [
        {"dimension": "proof", "observed_status": "pending", "required_statuses": ["discharged"]}]


def test_requested_theorem_discharge_is_separate_from_unrequested_proof():
    record = prepared(positive_dimensions(proof=True), theorem_requested=True)
    assert views(record)["views"]["checked_lean"]["declared_eligible"] is True
    assert record["proof_authority"] is False
    assert prepared()["dimensions"]["proof"] == dimension("not_requested")


def test_contradictory_request_and_proof_states_are_rejected():
    with pytest.raises(CorpusContractError, match="contradicts theorem_requested"):
        prepared({"proof": dimension("not_requested")}, theorem_requested=True)
    with pytest.raises(CorpusContractError, match="contradicts theorem_requested"):
        prepared(positive_dimensions(proof=True))
    with pytest.raises(CorpusContractError, match="not_requested proof cannot carry"):
        prepared({"proof": dimension("not_requested", cid("unsolicited proof"))})
    states = positive_dimensions(proof=True)
    states["lean_compilation"] = dimension("failed")
    with pytest.raises(CorpusContractError, match="discharged Lean theorem requires"):
        prepared(states, theorem_requested=True)


def test_evidence_references_are_closed_bounded_unique_cids():
    for item in (dimension("complete", "not-a-cid"),
                 dimension("complete", cid("receipt"), cid("receipt")),
                 {"status": "complete", "evidence_cids": True},
                 {"status": "complete", "evidence_cids": [], "claimed_source_truth": True}):
        with pytest.raises(CorpusContractError):
            prepared({"processing": item})
    with pytest.raises(CorpusContractError, match="bounded"):
        prepared({"processing": dimension("complete", *(cid(str(n)) for n in range(257)))})


def test_unknown_dimension_is_not_silently_dropped():
    with pytest.raises(CorpusContractError, match="unknown qualification dimension"):
        prepared({"legal_truth": dimension("verified", cid("unverified claim"))})


def test_sealed_status_tampering_is_detected():
    record = prepared(positive_dimensions())
    record["dimensions"]["interpretation"]["status"] = "candidate"
    with pytest.raises(CorpusContractError):
        checked(record)


def test_resealed_authority_claims_are_still_rejected():
    for key in qualification.AUTHORITY_FIELDS:
        record = prepared(positive_dimensions())
        record[key] = True
        with pytest.raises(CorpusContractError, match="cannot grant"):
            checked(reseal(record))


def test_declared_eligibility_is_recomputed_even_after_resealing():
    record = prepared()
    report = views(record)
    assert qualification.validate_eligibility(report, record, artifact_cid=ARTIFACT, profile=PROFILE) == report
    report["views"]["checked_lean"] = {"declared_eligible": True, "blockers": []}
    with pytest.raises(CorpusContractError):
        qualification.validate_eligibility(report, record, artifact_cid=ARTIFACT, profile=PROFILE)
    with pytest.raises(CorpusContractError, match="differs from exact qualification"):
        qualification.validate_eligibility(reseal(report), record, artifact_cid=ARTIFACT, profile=PROFILE)


def test_qualification_cannot_transfer_to_another_artifact_or_profile():
    record = prepared(positive_dimensions())
    for artifact, profile in ((OTHER_ARTIFACT, PROFILE), (ARTIFACT, "another-profile/v1")):
        with pytest.raises(CorpusContractError, match="another artifact or profile"):
            qualification.validate_qualification(record, artifact_cid=artifact, profile=profile)
        with pytest.raises(CorpusContractError, match="another artifact or profile"):
            qualification.derive_eligibility(record, artifact_cid=artifact, profile=profile)


def test_legacy_admitted_formalized_flags_preserve_only_descriptive_observation():
    legacy = {"sealed": True, "status": "sealed", "admitted": True, "formalized": True}
    original = deepcopy(legacy)
    adapted = qualification.adapt_legacy_qualification(legacy, artifact_cid=ARTIFACT, profile=PROFILE)
    assert legacy == original
    assert adapted["legacy_observation"]["legacy_fields"] == original
    record = checked(adapted["qualification"])
    assert record["dimensions"]["processing"]["status"] == "complete"
    assert record["dimensions"]["source_integrity"]["status"] == "unassessed"
    assert record["dimensions"]["interpretation"]["status"] == "candidate"
    assert record["dimensions"]["lean_compilation"]["status"] == "not_run"
    assert record["dimensions"]["proof"]["status"] == "not_requested"
    assert all(view["declared_eligible"] is False for view in views(record)["views"].values())
    assert adapted["legacy_flags_grant_authority"] is False
    assert all(adapted[key] is False for key in qualification.AUTHORITY_FIELDS)


def test_legacy_gap_stays_gap_and_cannot_be_reviewed():
    adapted = qualification.adapt_legacy_qualification({"status": "gap", "sealed": False},
                                                       artifact_cid=ARTIFACT, profile=PROFILE)
    assert adapted["qualification"]["dimensions"]["processing"]["status"] == "gap"
    assert views(adapted["qualification"])["views"]["reviewed_graph"]["declared_eligible"] is False


@pytest.mark.parametrize("legacy", [
    {"sealed": "true"}, {"admitted": 1}, {"formalized": 0}, {"gap": "false"},
    {"sealed": True, "gap": True}, {"sealed": False, "status": "sealed"},
    {"sealed": True, "status": "pending"}, {"status": "invented"}, {"status": None},
    {"gap": False, "status": "gap"},
    {"artifact_cid": OTHER_ARTIFACT}, {"profile": "another/v1"},
])
def test_legacy_coercions_conflicts_and_wrong_bindings_are_rejected(legacy):
    with pytest.raises(CorpusContractError):
        qualification.adapt_legacy_qualification(legacy, artifact_cid=ARTIFACT, profile=PROFILE)


def test_prepare_validate_and_derivation_do_not_mutate_or_alias_callers():
    supplied = positive_dimensions()
    before = deepcopy(supplied)
    record = prepared(supplied)
    assert supplied == before
    supplied["interpretation"]["evidence_cids"].clear()
    assert record["dimensions"]["interpretation"]["evidence_cids"]
    record_before = deepcopy(record)
    detached = checked(record)
    detached["dimensions"]["interpretation"]["evidence_cids"].clear()
    views(record)
    assert record == record_before
