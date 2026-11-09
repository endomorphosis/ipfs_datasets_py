"""Separate adjudication authenticates declarations without applying source law.

All text, keys, principals, findings, and decisions below are engineering
fixtures. Externally shaped registries do not represent real human review.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_responses as responses
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_review as source
from ipfs_datasets_py.logic.autoformal import legal_graph_review as trust
from ipfs_datasets_py.logic.profile_g import Ed25519Signer


DECLARED = "2026-10-14T09:01:00Z"
SIGNED = "2026-10-14T09:02:00Z"
EVALUATED = "2026-10-14T09:03:00Z"
DECLARATION_ID = "fixture:separate-legacy-source-adjudication-body"


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def helper():
    spec = importlib.util.spec_from_file_location(
        "authored_legacy_typed_responses_for_separate_adjudication",
        Path(__file__).with_name("test_corpus_legacy_source_responses.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_adjudication

    return corpus_legacy_source_adjudication


def source_case(*, disposition="evidence_declared"):
    data = helper().response_case(responses, disposition=disposition)
    data["typed_assessment"] = helper().assess(responses, data)
    data["response_inputs"] = deepcopy(helper().assessment_arguments(data))
    return data


def declaration_arguments(data):
    return {
        "expected_typed_assessment_sha256": sha(wire(data["typed_assessment"])),
        "response_inputs": data["response_inputs"],
    }


def declaration_inputs(data):
    return (data["preparation"], data["typed_assessment"], data["registry"],
            data["policy"], data["reviews"])


def decisions(data, *, unresolved=False):
    refs = [{"artifact_id": "fixture:legacy-source-declaration",
             "sha256": sha(data["evidence_artifacts"]["fixture:legacy-source-declaration"])}]
    return [{
        "slot_id": question["slot_id"],
        "decision": "unresolved" if unresolved else "select_existing_variant",
        "selected_variant_ref": None if unresolved else deepcopy(question["answer_variant_refs"][0]),
        "rationale": "Separate fictional adjudication of the complete retained source evidence.",
        "evidence_refs": [] if unresolved else deepcopy(refs),
    } for question in data["typed_assessment"]["pending_questions"]]


def record(owner, data, choices=None, *, declared=DECLARED):
    return owner.record_legacy_source_adjudication_declaration(
        *declaration_inputs(data), decisions(data) if choices is None else choices,
        declared_at_utc=declared, **declaration_arguments(data))


def resign(data):
    adjudication = data["adjudication"]
    adjudication["policy"]["registry_sha256"] = sha(wire(adjudication["registry"]))
    for index, signed in enumerate(adjudication["reviews"]):
        body = {key: deepcopy(value) for key, value in signed.items()
                if key not in {"signer_did", "signature_alg", "signature"}}
        body["registry_sha256"] = sha(wire(adjudication["registry"]))
        body["policy_sha256"] = sha(wire(adjudication["policy"]))
        adjudication["reviews"][index] = adjudication["signers"][index].sign(body)


def signed_case(owner, *, data=None, choices=None, declared=DECLARED):
    data = source_case() if data is None else data
    choices = decisions(data) if choices is None else choices
    body = record(owner, data, choices, declared=declared)
    raw = wire(body)
    subject = data["preparation"]["subjects"][0]
    signers = [Ed25519Signer.generate(f"did:example:separate-source-adjudicator:{index}")
               for index in range(2)]
    registry = deepcopy(data["registry"])
    registry["process_id"] = "fixture:separate-source-adjudication-process"
    for index, key in enumerate(registry["keys"]):
        key.update(key_id=f"fixture:separate-source-adjudication-key:{index}",
                   principal_id=f"fixture:separate-source-adjudicator:{index}",
                   signer_did=signers[index].did,
                   public_key_hex=signers[index].public_key.public_bytes(
                       serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex())
    policy = deepcopy(data["policy"])
    policy.update(policy_id="fixture:separate-source-adjudication-policy",
                  process_id=registry["process_id"], registry_sha256=sha(wire(registry)),
                  action=owner.ACTION, audience=owner.AUDIENCE)
    variants = {row["record_cid"]: row for row in data["typed_assessment"]["answer_variants"]}
    unresolved = [row["slot_id"] for row in choices if row["decision"] == "unresolved"]
    closure = {
        "status": "open" if unresolved else "declared_complete", "unresolved": unresolved,
        "obligations": [{
            "slot_id": row["slot_id"],
            "disposition": "open" if row["decision"] == "unresolved" else {
                "evidence_declared": "resolved_by_evidence", "not_applicable": "not_applicable",
            }[variants[row["selected_variant_ref"]["record_cid"]]["answer"]["disposition"]],
            "evidence_refs": [{"artifact_id": DECLARATION_ID, "sha256": sha(raw)}],
        } for row in choices],
    }
    reviews = []
    for index, signer in enumerate(signers):
        review = {key: deepcopy(value) for key, value in data["reviews"][index].items()
                  if key not in {"signer_did", "signature_alg", "signature"}}
        review.update(schema=owner.CLAIM_SCHEMA, action=owner.ACTION, audience=owner.AUDIENCE,
                      review_id=f"fixture:separate-source-adjudication:{index}",
                      key_id=registry["keys"][index]["key_id"],
                      principal_id=registry["keys"][index]["principal_id"],
                      registry_sha256=sha(wire(registry)), policy_sha256=sha(wire(policy)),
                      issued_at_utc=SIGNED, subject=deepcopy(subject), context_closure=deepcopy(closure))
        reviews.append(signer.sign(review))
    data["adjudication"] = {"registry": registry, "policy": policy, "reviews": reviews,
                            "signers": signers, "declaration": body, "raw": raw,
                            "choices": choices, "evidence_artifacts": {
                                **data["evidence_artifacts"], DECLARATION_ID: raw}}
    return data


def assessment_arguments(data):
    adjudication = data["adjudication"]
    return {
        **declaration_arguments(data),
        "declaration_artifact_id": DECLARATION_ID,
        "expected_declaration_sha256": sha(adjudication["raw"]),
        "expected_adjudication_registry_sha256": sha(wire(adjudication["registry"])),
        "expected_adjudication_policy_sha256": sha(wire(adjudication["policy"])),
        "expected_adjudication_reviews_sha256": sha(wire(adjudication["reviews"])),
        "at_time_utc": EVALUATED,
        "observed_artifact_sha256s": data["observed_artifact_sha256s"],
        "observed_pins": data["observed_pins"],
        "evidence_artifacts": adjudication["evidence_artifacts"],
    }


def assessment_inputs(data):
    adjudication = data["adjudication"]
    return (*declaration_inputs(data), adjudication["registry"], adjudication["policy"],
            adjudication["reviews"])


def assess(owner, data, **overrides):
    return owner.assess_legacy_source_adjudication(
        *assessment_inputs(data), **{**assessment_arguments(data), **overrides})


def no_source_decision(result):
    assert result["selected_occurrence"] is None
    assert result["counts"]["source_decisions_applied"] == 0
    assert len(result["pending_slots"]) == 9
    for flag in trust.FALSE_AUTHORITY:
        assert result[flag] is False


def test_blank_template_preserves_all_questions_without_being_submittable(owner):
    data = source_case()
    template = owner.prepare_legacy_source_adjudication_template(
        *declaration_inputs(data), **declaration_arguments(data))
    draft = template["declaration"]
    assert draft["declared_at_utc"] is None
    assert len(draft["decisions"]) == 9
    assert [row["slot_id"] for row in draft["decisions"]] == [
        row["slot_id"] for row in data["typed_assessment"]["pending_questions"]]
    assert all(row == {"slot_id": row["slot_id"], "decision": None,
                       "selected_variant_ref": None, "rationale": None, "evidence_refs": []}
               for row in draft["decisions"])
    with pytest.raises(ValueError):
        record(owner, data, draft["decisions"], declared=draft["declared_at_utc"])


def test_declaration_round_trip_is_exact_and_does_not_mutate_source_evidence(owner):
    data = source_case()
    choices = decisions(data)
    before = deepcopy((declaration_inputs(data), declaration_arguments(data), choices))
    body = record(owner, data, choices)
    assert owner.validate_legacy_source_adjudication_declaration(
        body, *declaration_inputs(data), choices, declared_at_utc=DECLARED,
        **declaration_arguments(data)) == body
    assert (declaration_inputs(data), declaration_arguments(data), choices) == before
    assert body["decisions"] == choices
    assert body["selected_occurrence"] is None


def test_independent_signed_declaration_qualifies_evidence_only(owner):
    data = signed_case(owner)
    result = assess(owner, data)
    assert result["original_typed_assessment"] == data["typed_assessment"]
    assert result["declaration_record"] == data["adjudication"]["declaration"]
    assert not result["content_blockers"]
    assert not result["separation_and_chronology_blockers"]
    assert result["authority_assessment"]["authenticated_evidence_count"] == 2
    assert result["current_source_authority_assessment"]["authenticated_evidence_count"] == 2
    assert result["authority_prerequisites_satisfied_under_selected_trust"] is True
    assert result["counts"]["declared_selected_slots"] == 9
    assert result["counts"]["unresolved_or_absent_slots"] == 0
    no_source_decision(result)
    assert owner.validate_legacy_source_adjudication(
        result, *assessment_inputs(data), **assessment_arguments(data)) == result


def test_distinct_answer_variants_survive_a_declared_choice(owner):
    data = source_case()
    data["responses"][1]["answers"][0]["finding"]["statement"] = "A conflicting fictional finding."
    helper().install_record(data, 1, helper().record(responses, data, data["responses"][1]))
    data["typed_assessment"] = helper().assess(responses, data)
    data["response_inputs"] = deepcopy(helper().assessment_arguments(data))
    assert len(data["typed_assessment"]["pending_questions"][0]["answer_variant_refs"]) == 2
    data = signed_case(owner, data=data)
    result = assess(owner, data)
    assert result["original_typed_assessment"] == data["typed_assessment"]
    assert len(result["original_typed_assessment"]["pending_questions"][0]["answer_variant_refs"]) == 2
    no_source_decision(result)


def test_unresolved_declaration_keeps_every_slot_pending(owner):
    data = source_case()
    data = signed_case(owner, data=data, choices=decisions(data, unresolved=True))
    result = assess(owner, data)
    assert result["counts"]["declared_selected_slots"] == 0
    assert result["counts"]["unresolved_or_absent_slots"] == 9
    assert result["authority_prerequisites_satisfied_under_selected_trust"] is False
    no_source_decision(result)


@pytest.mark.parametrize("damage", ["missing", "reordered", "extra", "unknown_slot", "foreign_variant",
                                     "wrong_variant_slot", "no_evidence", "resolved_null", "unresolved_ref"])
def test_unsupported_or_incomplete_declaration_cannot_be_recorded(owner, damage):
    data = source_case()
    choices = decisions(data)
    if damage == "missing":
        choices.pop()
    elif damage == "reordered":
        choices.reverse()
    elif damage == "extra":
        choices.append(deepcopy(choices[0]))
    elif damage == "unknown_slot":
        choices[0]["slot_id"] = "fixture:invented-active-slot"
    elif damage == "foreign_variant":
        choices[0]["selected_variant_ref"]["sha256"] = "0" * 64
    elif damage == "wrong_variant_slot":
        choices[0]["selected_variant_ref"] = deepcopy(choices[1]["selected_variant_ref"])
    elif damage == "no_evidence":
        choices[0]["evidence_refs"] = []
    elif damage == "resolved_null":
        choices[0]["selected_variant_ref"] = None
    else:
        choices[0]["decision"] = "unresolved"
    with pytest.raises(ValueError):
        record(owner, data, choices)


def test_authenticated_unresolved_variant_cannot_be_selected_as_resolved(owner):
    data = source_case(disposition="unresolved")
    assert data["typed_assessment"]["counts"]["authenticated_typed_responses"] == 2
    with pytest.raises(ValueError):
        record(owner, data)


@pytest.mark.parametrize("damage", ["stale_hash", "invented_variant", "bool_alias", "changed_source_bytes"])
def test_pinned_typed_assessment_requires_full_regeneration(owner, damage):
    data = source_case()
    arguments = declaration_arguments(data)
    choices = decisions(data)
    if damage == "stale_hash":
        arguments["expected_typed_assessment_sha256"] = "0" * 64
    elif damage == "invented_variant":
        data["typed_assessment"]["answer_variants"][0]["answer"]["finding"]["statement"] = "Invented after authentication."
        arguments["expected_typed_assessment_sha256"] = sha(wire(data["typed_assessment"]))
    elif damage == "bool_alias":
        data["typed_assessment"]["admitted"] = 0
        arguments["expected_typed_assessment_sha256"] = sha(wire(data["typed_assessment"]))
    else:
        data["response_inputs"]["paired_row_bytes"][0] += b" "
    with pytest.raises(ValueError):
        owner.record_legacy_source_adjudication_declaration(
            *declaration_inputs(data), choices, declared_at_utc=DECLARED, **arguments)


@pytest.mark.parametrize("damage", ["missing_body", "changed_body", "invalid_json", "empty_claims"])
def test_absent_or_invalid_declaration_cannot_qualify(owner, damage):
    data = signed_case(owner)
    adjudication = data["adjudication"]
    if damage == "missing_body":
        del adjudication["evidence_artifacts"][DECLARATION_ID]
    elif damage == "changed_body":
        adjudication["evidence_artifacts"][DECLARATION_ID] += b" "
    elif damage == "invalid_json":
        adjudication["raw"] = b"not a declaration"
        adjudication["evidence_artifacts"][DECLARATION_ID] = adjudication["raw"]
        for review in adjudication["reviews"]:
            for obligation in review["context_closure"]["obligations"]:
                obligation["evidence_refs"][0]["sha256"] = sha(adjudication["raw"])
        resign(data)
    else:
        adjudication["reviews"] = []
    result = assess(owner, data)
    assert result["authority_prerequisites_satisfied_under_selected_trust"] is False
    if damage != "empty_claims":
        assert result["declaration_record"] is None
        assert result["content_blockers"]
    no_source_decision(result)


@pytest.mark.parametrize("damage", ["different_body", "extra_body", "wrong_disposition", "wrong_status", "wrong_unresolved"])
def test_every_signed_obligation_must_bind_the_same_declaration_exactly(owner, damage):
    data = signed_case(owner)
    closure = data["adjudication"]["reviews"][1]["context_closure"]
    if damage in {"different_body", "extra_body"}:
        name = "fixture:duplicate-adjudication-bytes-different-identity"
        data["adjudication"]["evidence_artifacts"][name] = data["adjudication"]["raw"]
        ref = {"artifact_id": name, "sha256": sha(data["adjudication"]["raw"])}
        if damage == "different_body":
            closure["obligations"][0]["evidence_refs"] = [ref]
        else:
            closure["obligations"][0]["evidence_refs"].append(ref)
    elif damage == "wrong_disposition":
        closure["obligations"][0]["disposition"] = "not_applicable"
    elif damage == "wrong_status":
        closure["status"] = "open"
    else:
        closure["unresolved"] = [closure["obligations"][0]["slot_id"]]
    resign(data)
    result = assess(owner, data)
    assert result["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert result["content_blockers"]
    no_source_decision(result)


@pytest.mark.parametrize("field", ["schema", "action", "audience"])
def test_source_domain_claims_cannot_authorize_adjudication(owner, field):
    data = signed_case(owner)
    old = {"schema": source.CLAIM_SCHEMA, "action": source.ACTION, "audience": source.AUDIENCE}
    data["adjudication"]["reviews"][0][field] = old[field]
    resign(data)
    with pytest.raises(ValueError):
        assess(owner, data)


@pytest.mark.parametrize("field", ["action", "audience"])
def test_source_domain_policy_cannot_authorize_adjudication(owner, field):
    data = signed_case(owner)
    data["adjudication"]["policy"][field] = getattr(source, field.upper())
    resign(data)
    with pytest.raises(ValueError):
        assess(owner, data)


@pytest.mark.parametrize("reuse", ["principal", "did", "public_key"])
def test_original_source_reviewer_cannot_be_its_own_separate_adjudicator(owner, reuse):
    data = signed_case(owner)
    adjudication = data["adjudication"]
    key = adjudication["registry"]["keys"][0]
    source_key = data["registry"]["keys"][0]
    if reuse == "principal":
        key["principal_id"] = source_key["principal_id"]
        adjudication["reviews"][0]["principal_id"] = source_key["principal_id"]
    elif reuse == "did":
        signer = Ed25519Signer.generate(source_key["signer_did"])
        adjudication["signers"][0] = signer
        key["signer_did"] = signer.did
        key["public_key_hex"] = signer.public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    else:
        # A new declared DID must not hide reuse of the same signing key.
        adjudication["signers"][0] = Ed25519Signer(
            key["signer_did"], data["signers"][0].private_key)
        key["public_key_hex"] = source_key["public_key_hex"]
    resign(data)
    result = assess(owner, data)
    assert result["authority_assessment"]["authenticated_evidence_count"] == 2
    assert result["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert result["separation_and_chronology_blockers"]
    no_source_decision(result)


def test_claim_signed_before_declaration_cannot_qualify(owner):
    data = signed_case(owner)
    data["adjudication"]["reviews"][0]["issued_at_utc"] = "2026-10-14T09:00:30Z"
    resign(data)
    result = assess(owner, data)
    assert result["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert result["separation_and_chronology_blockers"]
    no_source_decision(result)


def test_declaration_after_evaluation_cannot_qualify(owner):
    data = signed_case(owner, declared="2026-10-14T09:04:00Z")
    result = assess(owner, data)
    assert result["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert result["separation_and_chronology_blockers"]
    no_source_decision(result)


def test_declaration_cannot_precede_the_typed_assessment(owner):
    data = source_case()
    with pytest.raises(ValueError):
        record(owner, data, declared="2026-10-14T08:59:59Z")


def test_source_claim_expiry_is_rechecked_at_adjudication_time(owner):
    data = source_case()
    for review in data["reviews"]:
        review["expires_at_utc"] = "2026-10-14T09:01:30Z"
    helper().helper().refresh_signatures(data)
    data["typed_assessment"] = helper().assess(responses, data)
    data["response_inputs"] = deepcopy(helper().assessment_arguments(data))
    assert data["typed_assessment"]["counts"]["authenticated_typed_responses"] == 2
    data = signed_case(owner, data=data)
    # Adjudicators have a fresh independent interval; only the original source
    # claims expire between the preserved assessment and the final evaluation.
    for review in data["adjudication"]["reviews"]:
        review["expires_at_utc"] = "2026-10-15T08:00:00Z"
    resign(data)
    result = assess(owner, data)
    assert result["authority_assessment"]["authenticated_evidence_count"] == 2
    assert result["current_source_authority_assessment"]["authenticated_evidence_count"] == 0
    assert result["authority_prerequisites_satisfied_under_selected_trust"] is False
    no_source_decision(result)


def test_malformed_typed_response_does_not_supply_an_authenticated_source_role(owner):
    data = source_case()
    ref = data["response_bindings"][1]
    data["evidence_artifacts"][ref["artifact_id"]] = b"{}"
    data["typed_assessment"] = helper().assess(responses, data)
    data["response_inputs"] = deepcopy(helper().assessment_arguments(data))
    assert data["typed_assessment"]["raw_source_assessment"]["authenticated_evidence_count"] == 2
    assert data["typed_assessment"]["counts"]["authenticated_typed_responses"] == 1
    data = signed_case(owner, data=data)
    result = assess(owner, data)
    assert result["authority_prerequisites_satisfied_under_selected_trust"] is False
    no_source_decision(result)


def test_synthetic_adjudication_trust_cannot_satisfy_external_authority(owner):
    data = signed_case(owner)
    data["adjudication"]["registry"]["mode"] = "synthetic_fixture"
    data["adjudication"]["policy"]["mode"] = "synthetic_fixture"
    resign(data)
    result = assess(owner, data)
    assert result["authority_assessment"]["authenticated_evidence_count"] == 2
    assert result["authority_prerequisites_satisfied_under_selected_trust"] is False
    no_source_decision(result)


def test_current_dependency_changes_do_not_reuse_the_old_source_assessment(owner):
    data = signed_case(owner)
    observed = deepcopy(data["observed_artifact_sha256s"])
    key = data["preparation"]["subjects"][0]["required_dependency_ids"][0]
    observed[key] = "0" * 64
    result = assess(owner, data, observed_artifact_sha256s=observed)
    assert result["original_typed_assessment"] == data["typed_assessment"]
    assert result["authority_prerequisites_satisfied_under_selected_trust"] is False
    no_source_decision(result)


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_declared_selection_supporting_evidence_is_checked_as_exact_bytes(owner, damage):
    data = signed_case(owner)
    name = "fixture:legacy-source-declaration"
    if damage == "missing":
        del data["adjudication"]["evidence_artifacts"][name]
    else:
        data["adjudication"]["evidence_artifacts"][name] += b" Changed supporting evidence."
    result = assess(owner, data)
    assert result["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert result["content_blockers"]
    no_source_decision(result)


@pytest.mark.parametrize("target", ["declaration", "assessment"])
def test_canonical_replay_distinguishes_false_from_zero(owner, target):
    data = signed_case(owner)
    if target == "declaration":
        changed = deepcopy(data["adjudication"]["declaration"])
        changed["admitted"] = 0
        with pytest.raises(ValueError):
            owner.validate_legacy_source_adjudication_declaration(
                changed, *declaration_inputs(data), data["adjudication"]["choices"],
                declared_at_utc=DECLARED, **declaration_arguments(data))
    else:
        changed = assess(owner, data)
        changed["admitted"] = 0
        with pytest.raises(ValueError):
            owner.validate_legacy_source_adjudication(
                changed, *assessment_inputs(data), **assessment_arguments(data))
