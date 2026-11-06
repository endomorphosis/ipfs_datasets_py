"""Candidate source-answer snapshots need a distinct current application action.

All identities, evidence, and findings are fictional engineering fixtures.
Even a successful snapshot preserves source-law and training authority barriers.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_adjudication as adjudication
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_cohort as cohort_owner
from ipfs_datasets_py.logic.autoformal.corpus_contracts import seal_record
from ipfs_datasets_py.logic.autoformal import legal_graph_review as trust
from ipfs_datasets_py.logic.profile_g import Ed25519Signer


DECLARED = "2026-10-14T09:04:00Z"
SIGNED = "2026-10-14T09:05:00Z"
EVALUATED = "2026-10-14T09:06:00Z"
EXPIRES = "2026-10-15T08:00:00Z"


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def helper():
    spec = importlib.util.spec_from_file_location(
        "authored_complete_source_cohort_for_application",
        Path(__file__).with_name("test_corpus_legacy_source_cohort.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_application

    return corpus_legacy_source_application


def descriptor():
    return {"snapshot_id": "fixture:candidate-source-answer-snapshot",
            "use_scope": "candidate_source_context_answers", "generation": 1,
            "previous_snapshot_manifest_ref": None}


def source_support(data):
    name = "fixture:legacy-source-declaration"
    return [{"artifact_id": name, "sha256": sha(data["evidence_artifacts"][name])}]


def record_arguments(data, bank_id, ordinal, source_data, *, declared=DECLARED):
    return {**data["cohort_arguments"], "bank_id": bank_id, "request_ordinal": ordinal,
            "declared_at_utc": declared,
            "rationale": "Fictional candidate answer snapshot; no physical or governing source choice.",
            "evidence_refs": source_support(source_data)}


def resign(data, index):
    row = data["applications"][index]
    registry, policy = row["application_registry"], row["application_policy"]
    policy["registry_sha256"] = sha(wire(registry))
    for ordinal, review in enumerate(row["application_reviews"]):
        body = {key: deepcopy(value) for key, value in review.items()
                if key not in {"signer_did", "signature_alg", "signature"}}
        body["registry_sha256"], body["policy_sha256"] = sha(wire(registry)), sha(wire(policy))
        row["application_reviews"][ordinal] = data["signers"][index][ordinal].sign(body)
    row["assessment_inputs"].update(
        expected_application_registry_sha256=sha(wire(registry)),
        expected_application_policy_sha256=sha(wire(policy)),
        expected_application_reviews_sha256=sha(wire(row["application_reviews"])))


def application_case(owner, *, groups=None, declared=DECLARED):
    groups = helper().cohort_case((1,)) if groups is None else groups
    original, inputs, kwargs = helper().assess(cohort_owner, groups)
    cohort, banks, adjudications = inputs
    data = {"groups": groups, "cohort": cohort, "banks": banks, "adjudications": adjudications,
            "cohort_arguments": kwargs, "original_cohort_assessment": original,
            "descriptor": descriptor(), "applications": [], "signers": [], "declarations": []}
    for bank_id, group in groups:
        for ordinal, source_data in enumerate(group):
            body = owner.record_legacy_source_application_declaration(
                cohort, banks, adjudications, data["descriptor"],
                **record_arguments(data, bank_id, ordinal, source_data, declared=declared))
            raw = wire(body)
            identity = f"fixture:application-body:{bank_id}:{ordinal}"
            prior = source_data["adjudication"]
            registry, policy = deepcopy(prior["registry"]), deepcopy(prior["policy"])
            policy.update(policy_id=f"fixture:separate-application-policy:{bank_id}:{ordinal}",
                          action=owner.ACTION, audience=owner.AUDIENCE)
            reviews = []
            for index, signed in enumerate(prior["reviews"]):
                review = {key: deepcopy(value) for key, value in signed.items()
                          if key not in {"signer_did", "signature_alg", "signature"}}
                review.update(schema=owner.CLAIM_SCHEMA, action=owner.ACTION, audience=owner.AUDIENCE,
                              review_id=f"fixture:application-claim:{bank_id}:{ordinal}:{index}",
                              issued_at_utc=SIGNED, expires_at_utc=EXPIRES)
                for obligation in review["context_closure"]["obligations"]:
                    obligation["evidence_refs"] = [{"artifact_id": identity, "sha256": sha(raw)}]
                reviews.append(review)
            row = {"bank_id": bank_id, "request_ordinal": ordinal,
                "application_registry": registry, "application_policy": policy,
                "application_reviews": reviews,
                "assessment_inputs": {
                    "declaration_artifact_id": identity, "expected_declaration_sha256": sha(raw),
                    "expected_application_registry_sha256": sha(wire(registry)),
                    "expected_application_policy_sha256": sha(wire(policy)),
                    "expected_application_reviews_sha256": sha(wire(reviews)),
                    "observed_artifact_sha256s": deepcopy(source_data["observed_artifact_sha256s"]),
                    "observed_pins": deepcopy(source_data["observed_pins"]),
                    "evidence_artifacts": {**prior["evidence_artifacts"], identity: raw},
                }}
            data["applications"].append(row)
            data["signers"].append(list(prior["signers"]))
            data["declarations"].append(body)
            resign(data, len(data["applications"]) - 1)
    return data


def assessment_inputs(data):
    return (data["cohort"], data["banks"], data["adjudications"],
            data["applications"], data["descriptor"])


def assessment_arguments(owner, data, *, evaluated=EVALUATED):
    return {**data["cohort_arguments"], "at_time_utc": evaluated,
            "expected_application_input_sha256s": [owner.legacy_source_application_input_sha256(row)
                                                   for row in data["applications"]]}


def assess(owner, data, **overrides):
    return owner.assess_legacy_source_applications(
        *assessment_inputs(data), **{**assessment_arguments(owner, data), **overrides})


def no_authority(report):
    assert report["selected_occurrence"] is None
    assert report["counts"]["source_decisions_applied"] == 0
    assert report["counts"]["physical_governing_bindings_applied"] == 0
    for flag in trust.FALSE_AUTHORITY:
        assert report[flag] is False
    for result in report["request_results"]:
        assert result["decision_applied"] is False


def test_new_application_action_activates_nine_candidate_answers_without_promoting_authority(owner):
    data = application_case(owner)
    original_reports = wire([row["assessment"] for row in data["adjudications"]])
    original = data["adjudications"][0]["assessment"]
    original_adjudication_time = original["authority_assessment"]["evaluation_time_utc"]
    original_source_time = original["original_typed_assessment"]["raw_source_assessment"]["evaluation_time_utc"]
    assert original_adjudication_time != EVALUATED and original_source_time != EVALUATED
    report = assess(owner, data)
    result = report["request_results"][0]
    assert result["source_answer_snapshot_activated_under_selected_profile"] is True
    assert result["activated_answer_variant_refs"] == data["declarations"][0]["selected_answer_variant_refs"]
    assert len(result["activated_answer_variant_refs"]) == len(data["declarations"][0]["active_slot_ids"]) == 9
    assert result["authority_assessment"]["authenticated_evidence_count"] == 2
    assert result["current_adjudication_assessment"]["authority_prerequisites_satisfied_under_selected_trust"] is True
    current = result["current_adjudication_assessment"]
    assert report["evaluation_time_utc"] == EVALUATED
    assert result["authority_assessment"]["evaluation_time_utc"] == EVALUATED
    assert current["authority_assessment"]["evaluation_time_utc"] == EVALUATED
    assert current["current_source_authority_assessment"]["evaluation_time_utc"] == EVALUATED
    assert current["original_typed_assessment"]["raw_source_assessment"]["evaluation_time_utc"] == original_source_time
    assert report["counts"]["activated_requests"] == 1
    assert report["counts"]["activated_answer_references"] == 9
    assert original_reports == wire([row["assessment"] for row in data["adjudications"]])
    assert data["adjudications"][0]["assessment"]["authority_assessment"]["evaluation_time_utc"] == original_adjudication_time
    assert owner.validate_legacy_source_applications(
        report, *assessment_inputs(data), **assessment_arguments(owner, data)) == report
    bank_id, group = data["groups"][0]
    assert owner.validate_legacy_source_application_declaration(
        data["declarations"][0], data["cohort"], data["banks"], data["adjudications"], data["descriptor"],
        **record_arguments(data, bank_id, 0, group[0])) == data["declarations"][0]
    no_authority(report)


@pytest.mark.parametrize("damage", ["omission", "reordering"])
def test_resealed_partial_or_reordered_answer_sets_are_rejected_atomically(owner, damage):
    data = application_case(owner)
    body = deepcopy(data["declarations"][0])
    if damage == "omission":
        body["selected_answer_variant_refs"].pop()
    else:
        body["selected_answer_variant_refs"].reverse()
    changed = seal_record({key: value for key, value in body.items()
                           if key not in {"record_cid", "cid_scope"}})
    raw = wire(changed)
    row = data["applications"][0]
    inputs = row["assessment_inputs"]
    inputs["evidence_artifacts"][inputs["declaration_artifact_id"]] = raw
    inputs["expected_declaration_sha256"] = sha(raw)
    for review in row["application_reviews"]:
        for obligation in review["context_closure"]["obligations"]:
            obligation["evidence_refs"][0]["sha256"] = sha(raw)
    resign(data, 0)
    report = assess(owner, data)
    result = report["request_results"][0]
    assert result["source_answer_snapshot_activated_under_selected_profile"] is False
    assert result["activated_answer_variant_refs"] == []
    assert result["content_blockers"]
    no_authority(report)


@pytest.mark.parametrize("expired", ["source", "adjudication", "application"])
def test_old_success_is_requalified_at_the_single_application_time(owner, expired):
    groups = helper().cohort_case((1,))
    source_data = groups[0][1][0]
    if expired == "source":
        for review in source_data["reviews"]:
            review["expires_at_utc"] = "2026-10-14T09:05:30Z"
        helper().refresh_source_and_declaration(source_data)
    elif expired == "adjudication":
        for review in source_data["adjudication"]["reviews"]:
            review["expires_at_utc"] = "2026-10-14T09:05:30Z"
        helper().helper().resign(source_data)
    data = application_case(owner, groups=groups)
    assert data["original_cohort_assessment"]["counts"]["eligible_requests"] == 1
    if expired == "application":
        for review in data["applications"][0]["application_reviews"]:
            review["expires_at_utc"] = "2026-10-14T09:05:30Z"
        resign(data, 0)
    report = assess(owner, data)
    result = report["request_results"][0]
    assert result["source_answer_snapshot_activated_under_selected_profile"] is False
    assert result["activated_answer_variant_refs"] == []
    assert report["counts"]["activated_answer_references"] == 0
    no_authority(report)


@pytest.mark.parametrize("damage", ["missing_body", "changed_body", "missing_support", "one_slot_wrong_body"])
def test_incomplete_evidence_never_partially_activates_an_answer_set(owner, damage):
    data = application_case(owner)
    row = data["applications"][0]
    inputs = row["assessment_inputs"]
    identity = inputs["declaration_artifact_id"]
    if damage == "missing_body":
        del inputs["evidence_artifacts"][identity]
    elif damage == "changed_body":
        inputs["evidence_artifacts"][identity] += b" "
    elif damage == "missing_support":
        del inputs["evidence_artifacts"]["fixture:legacy-source-declaration"]
    else:
        duplicate = "fixture:different-application-body-identity"
        inputs["evidence_artifacts"][duplicate] = inputs["evidence_artifacts"][identity]
        row["application_reviews"][0]["context_closure"]["obligations"][0]["evidence_refs"][0]["artifact_id"] = duplicate
        resign(data, 0)
    report = assess(owner, data)
    result = report["request_results"][0]
    assert result["source_answer_snapshot_activated_under_selected_profile"] is False
    assert result["activated_answer_variant_refs"] == []
    assert result["content_blockers"]
    no_authority(report)


@pytest.mark.parametrize("attribute", ["principal", "did", "public_key"])
def test_source_reviewer_from_other_bank_cannot_authorize_application(owner, attribute):
    data = application_case(owner, groups=helper().cohort_case())
    source_data = data["groups"][0][1][0]
    row = data["applications"][1]
    key, original = row["application_registry"]["keys"][0], source_data["registry"]["keys"][0]
    if attribute == "principal":
        key["principal_id"] = original["principal_id"]
        row["application_reviews"][0]["principal_id"] = original["principal_id"]
    elif attribute == "did":
        signer = Ed25519Signer.generate(original["signer_did"])
        data["signers"][1][0] = signer
        key.update(signer_did=signer.did, public_key_hex=signer.public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex())
    else:
        data["signers"][1][0] = Ed25519Signer(key["signer_did"], source_data["signers"][0].private_key)
        key["public_key_hex"] = original["public_key_hex"]
    resign(data, 1)
    report = assess(owner, data)
    unaffected = report["request_results"][0]
    assert unaffected["source_answer_snapshot_activated_under_selected_profile"] is True
    assert len(unaffected["activated_answer_variant_refs"]) == 9
    result = report["request_results"][1]
    assert result["authority_assessment"]["authenticated_evidence_count"] == 2
    assert result["current_adjudication_assessment"]["authority_prerequisites_satisfied_under_selected_trust"] is True
    assert result["source_answer_snapshot_activated_under_selected_profile"] is False
    assert result["activated_answer_variant_refs"] == []
    assert result["exclusion_matches"]
    assert report["counts"]["activated_requests"] == 1
    assert report["counts"]["activated_answer_references"] == 9
    no_authority(report)


@pytest.mark.parametrize("field", ["schema", "action", "audience"])
def test_adjudication_signature_domain_cannot_substitute_for_application(owner, field):
    data = application_case(owner)
    row = data["applications"][0]
    row["application_reviews"][0][field] = {
        "schema": adjudication.CLAIM_SCHEMA, "action": adjudication.ACTION,
        "audience": adjudication.AUDIENCE}[field]
    resign(data, 0)
    with pytest.raises(ValueError):
        assess(owner, data)


@pytest.mark.parametrize("damage", ["body_before_old_assessment", "claim_before_body", "body_after_evaluation"])
def test_application_chronology_cannot_authorize_retroactive_use(owner, damage):
    data = application_case(owner, declared="2026-10-14T09:07:00Z" if damage == "body_after_evaluation" else DECLARED)
    if damage == "body_before_old_assessment":
        bank_id, group = data["groups"][0]
        with pytest.raises(ValueError):
            owner.record_legacy_source_application_declaration(
                data["cohort"], data["banks"], data["adjudications"], data["descriptor"],
                **record_arguments(data, bank_id, 0, group[0], declared="2026-10-14T09:02:59Z"))
        return
    if damage == "claim_before_body":
        data["applications"][0]["application_reviews"][0]["issued_at_utc"] = "2026-10-14T09:03:30Z"
        resign(data, 0)
    report = assess(owner, data)
    result = report["request_results"][0]
    assert result["source_answer_snapshot_activated_under_selected_profile"] is False
    assert result["activated_answer_variant_refs"] == []
    assert result["separation_and_chronology_blockers"]
    no_authority(report)


@pytest.mark.parametrize("damage", ["missing_request", "duplicate_request", "reordered", "wrong_input_digest",
                                     "cohort_tamper", "prior_report_tamper", "bool_ordinal"])
def test_application_replays_complete_ordered_cohort_and_original_reports(owner, damage):
    data = application_case(owner, groups=helper().cohort_case() if damage in {
        "duplicate_request", "reordered"} else None)
    kwargs = assessment_arguments(owner, data)
    if damage == "missing_request":
        data["applications"].pop()
    elif damage == "duplicate_request":
        data["applications"][1] = deepcopy(data["applications"][0])
        kwargs = assessment_arguments(owner, data)
    elif damage == "reordered":
        data["applications"].reverse()
        kwargs = assessment_arguments(owner, data)
    elif damage == "wrong_input_digest":
        kwargs["expected_application_input_sha256s"][0] = "0" * 64
    elif damage == "cohort_tamper":
        data["cohort"]["excluded_principal_ids"] = []
        kwargs["expected_cohort_sha256"] = sha(wire(data["cohort"]))
    elif damage == "prior_report_tamper":
        data["adjudications"][0]["assessment"]["authority_prerequisites_satisfied_under_selected_trust"] = False
        kwargs["expected_adjudication_assessment_sha256s"][0] = sha(wire(data["adjudications"][0]["assessment"]))
    else:
        data["applications"][0]["request_ordinal"] = False
        with pytest.raises(ValueError):
            kwargs["expected_application_input_sha256s"][0] = owner.legacy_source_application_input_sha256(
                data["applications"][0])
            owner.assess_legacy_source_applications(*assessment_inputs(data), **kwargs)
        return
    with pytest.raises(ValueError):
        owner.assess_legacy_source_applications(*assessment_inputs(data), **kwargs)


def test_current_dependency_invalidation_blocks_candidate_snapshot(owner):
    data = application_case(owner)
    observations = data["applications"][0]["assessment_inputs"]["observed_artifact_sha256s"]
    identity = data["banks"][0]["preparation"]["subjects"][0]["required_dependency_ids"][0]
    observations[identity] = "0" * 64
    report = assess(owner, data)
    result = report["request_results"][0]
    assert result["source_answer_snapshot_activated_under_selected_profile"] is False
    assert result["activated_answer_variant_refs"] == []
    no_authority(report)


@pytest.mark.parametrize("damage", ["bool_generation", "generation_two", "non_null_predecessor",
                                     "governing_scope", "unsigned_descriptor_change"])
def test_snapshot_descriptor_is_scoped_and_bound_to_signed_content(owner, damage):
    data = application_case(owner)
    if damage == "bool_generation":
        data["descriptor"]["generation"] = True
    elif damage == "generation_two":
        data["descriptor"]["generation"] = 2
    elif damage == "non_null_predecessor":
        data["descriptor"]["previous_snapshot_manifest_ref"] = {
            "record_cid": data["declarations"][0]["record_cid"],
            "sha256": sha(wire(data["declarations"][0])),
            "schema": data["declarations"][0]["schema"],
        }
    elif damage == "governing_scope":
        data["descriptor"]["use_scope"] = "accepted_governing_source_law"
    else:
        data["descriptor"]["snapshot_id"] = "fixture:different-unsigned-snapshot"
    if damage != "unsigned_descriptor_change":
        with pytest.raises(ValueError):
            assess(owner, data)
    else:
        report = assess(owner, data)
        result = report["request_results"][0]
        assert result["source_answer_snapshot_activated_under_selected_profile"] is False
        assert result["activated_answer_variant_refs"] == []
        assert result["content_blockers"]
        no_authority(report)


def test_unresolved_adjudication_choices_cannot_author_application(owner):
    groups = helper().cohort_case((1,))
    source_data = groups[0][1][0]
    previous = helper().helper()
    previous.signed_case(adjudication, data=source_data,
                         choices=previous.decisions(source_data, unresolved=True))
    assert all(choice["decision"] == "unresolved"
               for choice in source_data["adjudication"]["declaration"]["decisions"])
    with pytest.raises(ValueError, match="nine existing resolved adjudication choices"):
        application_case(owner, groups=groups)


def test_absent_application_preserves_every_request_as_pending(owner):
    data = application_case(owner)
    row = data["applications"][0]
    row["application_reviews"] = []
    row["assessment_inputs"].update(declaration_artifact_id=None, expected_declaration_sha256=None,
                                    evidence_artifacts={})
    resign(data, 0)
    report = assess(owner, data)
    assert report["counts"]["requests"] == len(report["request_results"]) == 1
    assert report["counts"]["activated_requests"] == report["counts"]["activated_answer_references"] == 0
    result = report["request_results"][0]
    assert result["current_adjudication_assessment"]["authority_prerequisites_satisfied_under_selected_trust"] is True
    assert result["current_adjudication_assessment"]["authority_assessment"]["evaluation_time_utc"] == EVALUATED
    assert result["declaration_record"] is None and result["declaration_content_status"] == "absent"
    assert result["authority_assessment"]["review_count"] == 0
    assert result["authority_assessment"]["authenticated_evidence_count"] == 0
    assert result["source_answer_snapshot_activated_under_selected_profile"] is False
    assert result["activated_answer_variant_refs"] == []
    assert len(result["active_slot_ids"]) == 9
    no_authority(report)


def test_canonical_report_replay_distinguishes_false_from_zero(owner):
    data = application_case(owner)
    report = assess(owner, data)
    report["admitted"] = 0
    with pytest.raises(ValueError):
        owner.validate_legacy_source_applications(report, *assessment_inputs(data),
                                                 **assessment_arguments(owner, data))
