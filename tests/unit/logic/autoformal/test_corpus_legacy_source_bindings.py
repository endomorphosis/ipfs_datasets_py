"""Structured physical-source declarations bind existing geometry and no more.

All source, role, applicability, and signing evidence is fictional. No fixture
authenticates an official edition or establishes that a source governs law.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_history as history_owner
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_join as joins
from ipfs_datasets_py.logic.autoformal import legal_graph_review as trust
from ipfs_datasets_py.logic.autoformal.corpus_contracts import seal_record
from ipfs_datasets_py.logic.profile_g import Ed25519Signer


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def ref(value):
    return {"schema": value["schema"], "record_cid": value["record_cid"], "sha256": sha(wire(value))}


def helper():
    spec = importlib.util.spec_from_file_location(
        "authored_legacy_history_for_physical_bindings",
        Path(__file__).with_name("test_corpus_legacy_source_history.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_bindings

    return corpus_legacy_source_bindings


def history_inputs(data):
    return {"genesis_report": data["genesis_report"], "genesis_inputs": data["genesis_inputs"],
            "revision_steps": data["steps"], **helper().history_arguments(history_owner, data)}


def choice(data, candidate_index=0):
    preparation = data["history"]["steps"][-1]["inputs"]["banks"][0]["preparation"]
    candidate = preparation["requests"][0]["original_row"]["candidates"][candidate_index]
    index = candidate["source_section_index"]
    section = preparation["source_sections"][index]
    return {"source_section_index": index, "source_section_sha256": sha(wire(section)),
            "source_version_ref": ref(section["source_version"]),
            "source_occurrence_ref": ref(candidate["source_occurrence"]),
            "context_ref": ref(candidate["context_declaration"]), "declared_region_role": "operative_body",
            "applicability": {"scope_id": preparation["subjects"][0]["scope_id"],
                "jurisdiction_id": "fixture:jurisdiction", "instrument_id": "fixture:instrument",
                "legal_as_of_civil_date": "2026-10-14",
                "evidence_occurrence_refs": [ref(candidate["source_occurrence"])]}}


def record_arguments(data, *, declared=None):
    member = data["history"]["data"]["groups"][0][1][0]
    source_name = "fixture:legacy-source-declaration"
    return {"bank_id": data["history"]["data"]["groups"][0][0], "request_ordinal": 0,
        "expected_history_assessment_sha256": sha(wire(data["history_report"])),
        "declared_at_utc": declared or data["history_replay_inputs"]["at_time_utc"],
        "rationale": "Fictional stored-text region and applicability declaration; no official source authentication.",
        "evidence_refs": [{"artifact_id": source_name, "sha256": sha(member["evidence_artifacts"][source_name])}]}


def record(owner, data, selected=None, **overrides):
    return owner.record_legacy_source_binding_declaration(
        data["history_report"], data["history_replay_inputs"], choice(data) if selected is None else selected,
        **{**record_arguments(data), **overrides})


def resign(data):
    row = data["bindings"][0]
    registry, policy = row["binding_registry"], row["binding_policy"]
    policy["registry_sha256"] = sha(wire(registry))
    for index, claim in enumerate(row["binding_reviews"]):
        body = {key: deepcopy(value) for key, value in claim.items()
                if key not in {"signer_did", "signature_alg", "signature"}}
        body.update(registry_sha256=sha(wire(registry)), policy_sha256=sha(wire(policy)))
        row["binding_reviews"][index] = data["signers"][index].sign(body)
    row["assessment_inputs"].update(expected_binding_registry_sha256=sha(wire(registry)),
        expected_binding_policy_sha256=sha(wire(policy)),
        expected_binding_reviews_sha256=sha(wire(row["binding_reviews"])))


def install_body(data, body):
    data["body"] = body
    row = data["bindings"][0]
    inputs = row["assessment_inputs"]
    raw = wire(body)
    inputs["evidence_artifacts"][inputs["declaration_artifact_id"]] = raw
    inputs["expected_declaration_sha256"] = sha(raw)
    for claim in row["binding_reviews"]:
        for obligation in claim["context_closure"]["obligations"]:
            obligation["evidence_refs"] = [{"artifact_id": inputs["declaration_artifact_id"], "sha256": sha(raw)}]
    resign(data)


def binding_case(owner):
    historical = helper().genesis_case()
    helper().append_revision(history_owner, historical)
    data = {"history": historical, "history_report": helper().assess(history_owner, historical),
            "history_replay_inputs": history_inputs(historical)}
    body = record(owner, data)
    current = historical["steps"][-1]["inputs"]["revisions"][0]
    registry, policy = deepcopy(current["revision_registry"]), deepcopy(current["revision_policy"])
    registry["process_id"] = "fixture:separate-source-binding-process"
    signers = [Ed25519Signer.generate(f"did:example:source-binding:{index}") for index in range(2)]
    for index, key in enumerate(registry["keys"]):
        key.update(key_id=f"fixture:binding-key:{index}", principal_id=f"fixture:binding-principal:{index}",
                   signer_did=signers[index].did,
                   public_key_hex=signers[index].public_key.public_bytes(
                       serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex())
    policy.update(policy_id="fixture:separate-binding-policy", process_id=registry["process_id"],
                  action=owner.ACTION, audience=owner.AUDIENCE, registry_sha256=sha(wire(registry)))
    claims = []
    for index, signed in enumerate(current["revision_reviews"]):
        claim = {key: deepcopy(value) for key, value in signed.items()
                 if key not in {"signer_did", "signature_alg", "signature"}}
        claim.update(schema=owner.CLAIM_SCHEMA, action=owner.ACTION, audience=owner.AUDIENCE,
            review_id=f"fixture:source-binding-claim:{index}", key_id=registry["keys"][index]["key_id"],
            principal_id=registry["keys"][index]["principal_id"],
            issued_at_utc=data["history_replay_inputs"]["at_time_utc"])
        claims.append(claim)
    old_inputs = current["assessment_inputs"]
    data.update(signers=signers, bindings=[{
        "bank_id": current["bank_id"], "request_ordinal": current["request_ordinal"],
        "binding_registry": registry, "binding_policy": policy, "binding_reviews": claims,
        "assessment_inputs": {"declaration_artifact_id": "fixture:source-binding-body",
            "expected_declaration_sha256": sha(wire(body)),
            "expected_binding_registry_sha256": sha(wire(registry)),
            "expected_binding_policy_sha256": sha(wire(policy)),
            "expected_binding_reviews_sha256": sha(wire(claims)),
            "observed_artifact_sha256s": deepcopy(old_inputs["observed_artifact_sha256s"]),
            "observed_pins": deepcopy(old_inputs["observed_pins"]),
            "evidence_artifacts": deepcopy(old_inputs["evidence_artifacts"])}}])
    install_body(data, body)
    return data


def assessment_arguments(owner, data):
    return {"expected_history_assessment_sha256": sha(wire(data["history_report"])),
            "expected_binding_input_sha256s": [owner.legacy_source_binding_input_sha256(row)
                                               for row in data["bindings"]]}


def assess(owner, data):
    return owner.assess_legacy_source_bindings(data["history_report"], data["history_replay_inputs"],
                                             data["bindings"], **assessment_arguments(owner, data))


def no_governing_authority(report):
    assert report["selected_occurrence"] is None
    assert report["counts"]["source_decisions_applied"] == 0
    assert report["counts"]["physical_governing_bindings_applied"] == 0
    for flag in trust.FALSE_AUTHORITY:
        assert report[flag] is False
    for flag in ("structured_binding_establishes_legal_truth", "applicability_semantics_verified",
                 "governing_source_adoption_applied"):
        assert report[flag] is False


def test_explicit_binding_preserves_real_candidate_geometry_and_undeclared_edition(owner):
    data = binding_case(owner)
    before = wire(data["history_report"])
    preparation = data["history"]["steps"][-1]["inputs"]["banks"][0]["preparation"]
    original = preparation["requests"][0]["original_row"]
    candidate = original["candidates"][0]
    section = preparation["source_sections"][candidate["source_section_index"]]
    occurrence = candidate["source_occurrence"]
    assert section["extracted_text"][occurrence["start_char"]:occurrence["end_char"]] == occurrence["span_text"]
    assert section["extracted_text"].encode()[occurrence["start_utf8"]:occurrence["end_utf8"]] == occurrence["span_text"].encode()
    assert occurrence["start_char"] != occurrence["start_utf8"]
    assert section["source_version"]["raw_artifact"]["media_type"] == "text/plain"
    assert section["source_version"]["edition"] == joins.UNDECLARED_EDITION
    report = assess(owner, data)
    assert report["counts"]["declared_structured_bindings"] == 1
    assert report["counts"]["authenticated_binding_claims"] == 2
    assert report["request_results"][0]["structured_source_binding_declared_under_selected_profile"] is True
    assert report["request_results"][0]["declared_binding_refs"]
    assert len(data["body"]["selected_answer_variant_refs"]) == 9
    assert report["evaluation_time_utc"] == data["history_report"]["evaluation_time_utc"]
    assert before == wire(data["history_report"])
    assert original["selected_occurrence"] is None and original["original_producer_occurrence_attested"] is False
    assert owner.validate_legacy_source_binding_declaration(data["body"], data["history_report"],
        data["history_replay_inputs"], choice(data), **record_arguments(data)) == data["body"]
    assert owner.validate_legacy_source_bindings(report, data["history_report"], data["history_replay_inputs"],
        data["bindings"], **assessment_arguments(owner, data)) == report
    no_governing_authority(report)


def test_other_existing_occurrence_requires_its_own_exact_reference(owner):
    data = binding_case(owner)
    selected = choice(data, 1)
    assert selected["source_occurrence_ref"] != choice(data)["source_occurrence_ref"]
    install_body(data, record(owner, data, selected))
    report = assess(owner, data)
    assert report["request_results"][0]["structured_source_binding_declared_under_selected_profile"] is True
    no_governing_authority(report)


def test_independent_declared_applicability_does_not_expand_signing_scope(owner):
    data = binding_case(owner)
    selected = choice(data)
    original_scope = selected["applicability"]["scope_id"]
    selected["applicability"]["scope_id"] = "fixture:separately-declared-applicability"
    install_body(data, record(owner, data, selected))
    report = assess(owner, data)
    result = report["request_results"][0]
    assert result["structured_source_binding_declared_under_selected_profile"] is True
    assert result["declaration_record"]["choice"]["applicability"] == selected["applicability"]
    for key in data["bindings"][0]["binding_registry"]["keys"]:
        assert original_scope in key["scope_ids"]
        assert selected["applicability"]["scope_id"] not in key["scope_ids"]
    no_governing_authority(report)


@pytest.mark.parametrize("damage", ["section", "version", "occurrence", "context"])
def test_unlinked_section_or_record_references_are_refused(owner, damage):
    data = binding_case(owner)
    selected = choice(data)
    key = {"section": "source_section_sha256", "version": "source_version_ref",
           "occurrence": "source_occurrence_ref", "context": "context_ref"}[damage]
    if damage == "section":
        selected[key] = "0" * 64
    else:
        selected[key]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        record(owner, data, selected)


@pytest.mark.parametrize("unknown", ["region", "legal_date"])
def test_unknown_role_or_date_is_retained_without_binding_eligibility(owner, unknown):
    data = binding_case(owner)
    selected = choice(data)
    if unknown == "region":
        selected["declared_region_role"] = "unknown"
    else:
        selected["applicability"]["legal_as_of_civil_date"] = None
    install_body(data, record(owner, data, selected))
    report = assess(owner, data)
    result = report["request_results"][0]
    assert result["declaration_record"] is not None
    assert result["structured_source_binding_declared_under_selected_profile"] is False
    assert result["declared_binding_refs"] == [] and result["binding_blockers"]
    no_governing_authority(report)


def test_applicability_evidence_cannot_reference_an_unlinked_record(owner):
    data = binding_case(owner)
    selected = choice(data)
    selected["applicability"]["evidence_occurrence_refs"] = [selected["source_version_ref"]]
    with pytest.raises(ValueError):
        record(owner, data, selected)


def test_resealed_character_offsets_are_not_accepted_as_utf8_offsets(owner):
    data = binding_case(owner)
    preparation = data["history"]["steps"][-1]["inputs"]["banks"][0]["preparation"]
    occurrence = deepcopy(preparation["requests"][0]["original_row"]["candidates"][0]["source_occurrence"])
    assert occurrence["start_utf8"] != occurrence["start_char"]
    occurrence.update(start_utf8=occurrence["start_char"], end_utf8=occurrence["end_char"])
    forged = seal_record({key: value for key, value in occurrence.items() if key not in {"record_cid", "cid_scope"}})
    selected = choice(data)
    selected["source_occurrence_ref"] = ref(forged)
    with pytest.raises(ValueError):
        record(owner, data, selected)


def test_genesis_only_history_allows_absent_diagnostics_but_not_binding_authoring(owner):
    data = binding_case(owner)
    replay = {**data["history_replay_inputs"], "revision_steps": [],
              "current_epoch_id": helper().GENESIS, "expected_revision_step_sha256s": [],
              "at_time_utc": data["history"]["genesis_inputs"]["at_time_utc"]}
    data["history_replay_inputs"] = replay
    data["history_report"] = history_owner.assess_legacy_source_history(**replay)
    with pytest.raises(ValueError):
        record(owner, data)
    row = data["bindings"][0]
    row["binding_reviews"] = []
    row["assessment_inputs"].update(declaration_artifact_id=None, expected_declaration_sha256=None,
                                    evidence_artifacts={})
    resign(data)
    report = assess(owner, data)
    assert report["counts"]["requests"] == 1 and report["counts"]["declared_structured_bindings"] == 0
    assert report["request_results"][0]["declared_binding_refs"] == []
    no_governing_authority(report)


def test_visible_fork_prevents_binding_authoring(owner):
    data = binding_case(owner)
    helper().append_revision(history_owner, data["history"], epoch="fixture:fork", time_index=0)
    data["history_replay_inputs"] = history_inputs(data["history"])
    data["history_report"] = helper().assess(history_owner, data["history"])
    with pytest.raises(ValueError):
        record(owner, data)


def test_revision_signing_domain_cannot_authorize_source_binding(owner):
    data = binding_case(owner)
    data["bindings"][0]["binding_reviews"][0].update(
        schema=history_owner.CLAIM_SCHEMA, action=history_owner.ACTION, audience=history_owner.AUDIENCE)
    resign(data)
    with pytest.raises(ValueError):
        assess(owner, data)


def test_source_reviewer_cannot_supply_binding_authority(owner):
    data = binding_case(owner)
    principal = data["history"]["data"]["groups"][0][1][0]["registry"]["keys"][0]["principal_id"]
    row = data["bindings"][0]
    row["binding_registry"]["keys"][0]["principal_id"] = principal
    row["binding_reviews"][0]["principal_id"] = principal
    resign(data)
    report = assess(owner, data)
    result = report["request_results"][0]
    assert result["authority_assessment"]["authenticated_evidence_count"] == 2
    assert result["structured_source_binding_declared_under_selected_profile"] is False
    assert result["declared_binding_refs"] == []
    no_governing_authority(report)


@pytest.mark.parametrize("damage", ["missing_body", "bad_signature"])
def test_missing_or_unauthenticated_declaration_does_not_bind_geometry(owner, damage):
    data = binding_case(owner)
    row = data["bindings"][0]
    if damage == "missing_body":
        del row["assessment_inputs"]["evidence_artifacts"][row["assessment_inputs"]["declaration_artifact_id"]]
    else:
        signature = row["binding_reviews"][0]["signature"]
        row["binding_reviews"][0]["signature"] = ("A" if signature[0] != "A" else "B") + signature[1:]
        row["assessment_inputs"]["expected_binding_reviews_sha256"] = sha(wire(row["binding_reviews"]))
    report = assess(owner, data)
    assert report["counts"]["declared_structured_bindings"] == 0
    assert report["request_results"][0]["declared_binding_refs"] == []
    no_governing_authority(report)


@pytest.mark.parametrize("damage", ["other_body", "disposition"])
def test_valid_signatures_must_agree_on_one_exact_binding_and_all_slot_dispositions(owner, damage):
    data = binding_case(owner)
    row = data["bindings"][0]
    obligation = row["binding_reviews"][0]["context_closure"]["obligations"][0]
    if damage == "other_body":
        previous = data["history"]["steps"][-1]["inputs"]["revisions"][0]["assessment_inputs"]
        obligation["evidence_refs"] = [{"artifact_id": previous["declaration_artifact_id"],
                                        "sha256": previous["expected_declaration_sha256"]}]
    else:
        obligation["disposition"] = ("not_applicable" if obligation["disposition"] == "resolved_by_evidence"
                                      else "resolved_by_evidence")
    resign(data)
    report = assess(owner, data)
    result = report["request_results"][0]
    assert result["authority_assessment"]["authenticated_evidence_count"] == 2
    assert result["content_blockers"]
    assert result["structured_source_binding_declared_under_selected_profile"] is False
    assert result["declared_binding_refs"] == []
    no_governing_authority(report)


@pytest.mark.parametrize("declared", ["2026-10-14T09:08:30Z", "2026-10-14T09:10:01Z"])
def test_binding_declaration_must_follow_revision_claims_and_not_outlive_current_history(owner, declared):
    data = binding_case(owner)
    with pytest.raises(ValueError):
        record(owner, data, declared_at_utc=declared)


@pytest.mark.parametrize("damage", ["omitted", "duplicated"])
def test_complete_binding_disposition_population_is_required(owner, damage):
    data = binding_case(owner)
    if damage == "omitted":
        data["bindings"] = []
    else:
        data["bindings"].append(deepcopy(data["bindings"][0]))
    with pytest.raises(ValueError):
        assess(owner, data)


def test_binding_report_replay_does_not_accept_false_integer_alias(owner):
    data = binding_case(owner)
    report = assess(owner, data)
    report["admitted"] = 0
    with pytest.raises(ValueError):
        owner.validate_legacy_source_bindings(report, data["history_report"], data["history_replay_inputs"],
                                             data["bindings"], **assessment_arguments(owner, data))


@pytest.mark.parametrize("entrypoint", ["author", "assess"])
def test_complete_binding_budget_is_checked_before_history_replay(owner, monkeypatch, entrypoint):
    data = binding_case(owner)
    author_args = record_arguments(data)
    assess_args = assessment_arguments(owner, data)
    selected = choice(data)

    def replay_must_not_run(*args, **kwargs):
        pytest.fail("over-budget input reached history replay")

    monkeypatch.setattr(owner, "_replay", replay_must_not_run)
    monkeypatch.setattr(history_owner, "MAX_HISTORY_INPUT_BYTES", 1)
    with pytest.raises(ValueError, match="bound|budget"):
        if entrypoint == "author":
            owner.record_legacy_source_binding_declaration(data["history_report"],
                data["history_replay_inputs"], selected, **author_args)
        else:
            owner.assess_legacy_source_bindings(data["history_report"], data["history_replay_inputs"],
                                              data["bindings"], **assess_args)
