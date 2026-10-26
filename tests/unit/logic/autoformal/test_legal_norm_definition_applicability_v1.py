"""Fictional exact-use declarations authenticate bytes, never legal meaning.

Public cases replay real source/context/definition owners. Cases named pure use
narrow contract seams over genuinely replayed reports. All keys and clocks are
engineering fixtures; no statutory decision or training admission is created.
"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_graph_review as auth
from ipfs_datasets_py.logic.autoformal import legal_norm_definition_evidence_v1 as evidence
from ipfs_datasets_py.logic.autoformal import legal_norm_interpretation_review_v1 as norm

START, END = "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"
DECLARED, SIGNED, EVALUATED = "2026-10-15T12:01:00Z", "2026-10-15T12:02:00Z", "2026-10-15T12:03:00Z"
EXPIRES = "2026-10-16T11:00:00Z"
BODY_ID, SUPPORT_ID = "fixture:applicability-common-body", "fixture:applicability-support"
SUPPORT = b"Fictional exact-use support; applicability and statutory meaning remain unverified."


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location(
        "_applicability_genuine_definition_source", Path(__file__).with_name(
            "test_legal_norm_definition_evidence_v1.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def owner():
    from ipfs_datasets_py.logic.autoformal import legal_norm_definition_applicability_v1
    return legal_norm_definition_applicability_v1


def observations(manifest):
    pins = {kind: {} for kind in dependencies.PIN_KINDS}
    for row in manifest["artifacts"]:
        for kind, entries in row["dependency_pins"].items():
            pins[kind].update({entry["key"]: entry["sha256"] for entry in entries})
    return {"observed_artifact_sha256s": {
        row["artifact_id"]: row["artifact_sha256"] for row in manifest["artifacts"]}, "observed_pins": pins}


@pytest.fixture(scope="module")
def prepared(helper):
    inputs = helper.build_case()
    companion = helper.prepare(inputs)
    preparation = inputs["norm_preparation"]
    manifest = dependencies.build_dependency_manifest(preparation["artifacts"], preparation["edges"],
        expected_artifact_ids=preparation["required_dependency_ids"])
    subject = norm.build_norm_review_subject_v1(preparation, manifest,
        expected_preparation_sha256=norm.norm_review_sha256(preparation),
        expected_manifest_sha256=manifest["manifest_sha256"],
        required_dependency_ids=preparation["required_dependency_ids"], **inputs["norm_inputs"])
    endpoint_observations = []
    for endpoint in inputs["definitions"]:
        review = endpoint["review_evidence"]
        original = None if review is None else review["assessment_inputs"]
        endpoint_observations.append({"alternative_id": endpoint["alternative_id"],
            "observations": None if original is None else {key: deepcopy(original[key]) for key in (
                "observed_artifact_sha256s", "observed_pins", "evidence_artifacts")}})
    return {"inputs": inputs, "companion": companion, "subject": subject, "manifest": manifest,
            "definition_observations": endpoint_observations, **observations(manifest)}


def original_arguments(data):
    return (data["companion"], data["subject"], data["manifest"])


def replay_arguments(data):
    return {"expected_companion_sha256": evidence.norm_definition_evidence_sha256(data["companion"]),
        "companion_inputs": data["inputs"], "expected_norm_subject_sha256": auth.digest(data["subject"]),
        "expected_norm_manifest_sha256": data["manifest"]["manifest_sha256"]}


def choices(owner, data, *, unresolved=False):
    result = []
    for use in owner._group_uses(data["companion"]):
        result.append({"use_id": use["use_id"], "use_sha256": owner.norm_definition_applicability_sha256(use),
            "decision": "unresolved" if unresolved else "declare_one_supplied_alternative_applicable",
            "selected_link_ref": None if unresolved else deepcopy(use["nominated_link_refs"][0]),
            "legal_as_of_date": None if unresolved else "2024-01-01",
            "scope_statement": None if unresolved else "Authored fixture scope for this exact occurrence only.",
            "rationale": "Fictional association declaration, no accepted legal meaning or substitution.",
            "evidence_refs": [] if unresolved else [{"artifact_id": SUPPORT_ID, "sha256": sha(SUPPORT)}]})
    return result


@pytest.fixture(scope="module")
def declared(owner, prepared):
    return owner._declaration(prepared["companion"], prepared["subject"], prepared["inputs"],
                              choices(owner, prepared), DECLARED)


def resign(case):
    case["policy"]["registry_sha256"] = auth.digest(case["registry"])
    for index, old in enumerate(case["reviews"]):
        body = {key: deepcopy(value) for key, value in old.items()
                if key not in {"signer_did", "signature_alg", "signature"}}
        body.update(registry_sha256=auth.digest(case["registry"]), policy_sha256=auth.digest(case["policy"]))
        case["reviews"][index] = case["signers"][index].sign(body)


def signed_case(owner, prepared, declaration):
    from cryptography.hazmat.primitives import serialization
    from ipfs_datasets_py.logic.profile_g import Ed25519Signer

    result = dict(prepared)
    record = deepcopy(declaration)
    raw = wire(record)
    signers = [Ed25519Signer.generate("did:example:applicability:" + str(index)) for index in range(2)]
    keys = [{"key_id": "fixture:applicability-key:" + str(index), "signer_did": signer.did,
        "public_key_hex": signer.public_key.public_bytes(serialization.Encoding.Raw,
            serialization.PublicFormat.Raw).hex(), "principal_id": "fixture:applicability-principal:" + str(index),
        "roles": [role], "scope_ids": [prepared["subject"]["scope_id"]], "valid_from_utc": START,
        "valid_until_utc": END, "revoked_at_utc": None}
        for index, (signer, role) in enumerate(zip(signers, auth.ROLES, strict=True))]
    registry = {"schema": auth.REGISTRY_SCHEMA, "mode": "external_pinned_trust",
        "process_id": "fixture:applicability-process", "generation": 1, "revocation_generation": 1,
        "valid_from_utc": START, "valid_until_utc": END, "keys": keys, "revoked_principals": []}
    policy = {"schema": auth.POLICY_SCHEMA, "mode": "external_pinned_trust",
        "policy_id": "fixture:applicability-policy", "process_id": registry["process_id"],
        "registry_sha256": auth.digest(registry), "action": owner.ACTION, "audience": owner.AUDIENCE,
        "required_roles": list(auth.ROLES), "valid_from_utc": START, "valid_until_utc": END,
        "max_review_age_seconds": 86400}
    ref = {"artifact_id": BODY_ID, "sha256": sha(raw)}
    reviews = [signer.sign({"schema": owner.CLAIM_SCHEMA, "action": owner.ACTION,
        "audience": owner.AUDIENCE, "review_id": "fixture:applicability-review:" + str(index),
        "key_id": key["key_id"], "principal_id": key["principal_id"], "role": role,
        "registry_sha256": auth.digest(registry), "policy_sha256": auth.digest(policy),
        "issued_at_utc": SIGNED, "expires_at_utc": EXPIRES, "subject": deepcopy(prepared["subject"]),
        "interpretation": {"decision": "support", "reviewed_graph_sha256": prepared["subject"]["graph_sha256"],
            "reviewed_ast_sha256": prepared["subject"]["ast_sha256"],
            "rationale": "Fixture common-body authentication only; original norm obligations stay open.",
            "ambiguity": []}, "context_closure": owner._closure(prepared["subject"], ref)})
        for index, (signer, key, role) in enumerate(zip(signers, keys, auth.ROLES, strict=True))]
    result.update(registry=registry, policy=policy, reviews=reviews, signers=signers,
                  record=record, raw=raw, evidence_artifacts={BODY_ID: raw, SUPPORT_ID: SUPPORT})
    return result


@pytest.fixture
def case(owner, prepared, declared):
    return signed_case(owner, prepared, declared)


def authority_arguments(case):
    return (case["registry"], case["policy"], case["reviews"])


def assessment_arguments(owner, case):
    return {"declaration_artifact_id": BODY_ID, "expected_declaration_raw_sha256": sha(case["raw"]),
        "expected_declaration_sha256": owner.norm_definition_applicability_sha256(case["record"]),
        "expected_applicability_registry_sha256": auth.digest(case["registry"]),
        "expected_applicability_policy_sha256": auth.digest(case["policy"]),
        "expected_applicability_reviews_sha256": auth.digest(case["reviews"]), "at_time_utc": EVALUATED,
        "observed_artifact_sha256s": case["observed_artifact_sha256s"], "observed_pins": case["observed_pins"],
        "evidence_artifacts": case["evidence_artifacts"], "definition_observations": case["definition_observations"]}


def assess(owner, case, **overrides):
    return owner.assess_norm_definition_applicability_v1(*original_arguments(case), *authority_arguments(case),
        **{**replay_arguments(case), **assessment_arguments(owner, case), **overrides})


def assert_unapplied(value):
    assert value["governing_definition_use"] is None and value["selected_interpretation"] is None
    assert all(flag is False for flag in value["authority"].values())
    for key in ("training_mask", "evaluation_gold_mask"):
        assert type(value[key]) is int and value[key] == 0


def test_pure_use_inventory_keeps_repeated_symbol_occurrences_and_competing_alternatives(owner, prepared):
    uses = owner._group_uses(prepared["companion"])
    assert len(uses) == 2
    assert uses[0]["target"] != uses[1]["target"]
    assert uses[0]["typed_node"]["symbol"] == uses[1]["typed_node"]["symbol"] == "actor"
    assert uses[0]["use_id"] != uses[1]["use_id"]
    refs = [ref for use in uses for ref in use["nominated_link_refs"]]
    assert [ref["link_index"] for ref in refs] == list(range(4))
    for ref in refs:
        assert ref["sha256"] == owner.norm_definition_applicability_sha256(
            prepared["companion"]["links"][ref["link_index"]])
    assert len(prepared["companion"]["definitions"]) == 2
    assert prepared["companion"]["all_norm_term_uses_enumerated"] is False


@pytest.mark.parametrize("damage", ["missing", "reordered", "use_id", "use_pin", "foreign_use",
    "bool_index", "link_pin", "missing_date", "invalid_date", "missing_scope", "empty_rationale",
    "no_evidence", "negative_decision", "multiple_links", "unresolved_with_selection"])
def test_pure_choices_require_complete_ordered_exact_use_link_date_scope_and_support(owner, prepared, damage):
    decisions = choices(owner, prepared)
    row = decisions[0]
    if damage == "missing": decisions.pop()
    elif damage == "reordered": decisions.reverse()
    elif damage == "use_id": row["use_id"] = decisions[1]["use_id"]
    elif damage == "use_pin": row["use_sha256"] = "0" * 64
    elif damage == "foreign_use": row["selected_link_ref"] = deepcopy(decisions[1]["selected_link_ref"])
    elif damage == "bool_index": row["selected_link_ref"]["link_index"] = False
    elif damage == "link_pin": row["selected_link_ref"]["sha256"] = "0" * 64
    elif damage == "missing_date": row["legal_as_of_date"] = None
    elif damage == "invalid_date": row["legal_as_of_date"] = "2024-02-30"
    elif damage == "missing_scope": row["scope_statement"] = None
    elif damage == "empty_rationale": row["rationale"] = ""
    elif damage == "no_evidence": row["evidence_refs"] = []
    elif damage == "negative_decision": row["decision"] = "declare_alternative_inapplicable"
    elif damage == "multiple_links": row["selected_link_ref"] = [row["selected_link_ref"], decisions[1]["selected_link_ref"]]
    else: row["decision"] = "unresolved"
    with pytest.raises(ValueError):
        owner._declaration(prepared["companion"], prepared["subject"], prepared["inputs"], decisions, DECLARED)


def test_pure_unresolved_use_is_explicit_and_does_not_declare_other_alternatives_false(owner, prepared):
    record = owner._declaration(prepared["companion"], prepared["subject"], prepared["inputs"],
                               choices(owner, prepared, unresolved=True), DECLARED)
    assert all(row["decision"] == "unresolved" and row["selected_link_ref"] is None
               for row in record["decisions"])
    assert_unapplied(record)


def test_pure_closure_keeps_every_original_norm_obligation_open_even_for_selected_associations(owner, prepared, declared):
    ref = {"artifact_id": BODY_ID, "sha256": sha(wire(declared))}
    closure = owner._closure(prepared["subject"], ref)
    slots = prepared["subject"]["context_slot_ids"]
    assert closure["status"] == "open" and closure["unresolved"] == slots
    assert [row["slot_id"] for row in closure["obligations"]] == slots
    assert all(row["disposition"] == "open" and row["evidence_refs"] == [ref]
               for row in closure["obligations"])


def test_pure_shared_unresolved_limit_refuses_instead_of_truncating_norm_questions(owner, prepared):
    subject = deepcopy(prepared["subject"])
    subject["context_slot_ids"] = ["fixture:open-slot:" + str(index) for index in range(33)]
    with pytest.raises(ValueError):
        owner._closure(subject, {"artifact_id": BODY_ID, "sha256": "0" * 64})


@pytest.fixture(scope="module")
def current_definitions(owner, prepared):
    # This calls the actual endpoint owner at the new explicit clock. The no-op
    # fence marks this cached private seam; public integrations exercise fences.
    return owner._current_definitions(prepared["inputs"], prepared["definition_observations"],
                                      EVALUATED, lambda: None)


def assess_pure(owner, case, current_definitions, **overrides):
    arguments = assessment_arguments(owner, case)
    arguments.pop("definition_observations")
    return owner._assess_prepared(case["companion"], case["subject"], case["manifest"], case["inputs"],
        current_definitions, *authority_arguments(case), **{**arguments, **overrides})


def content_pure(owner, case, **overrides):
    arguments = {"identity": BODY_ID, "raw_pin": sha(case["raw"]),
        "canonical_pin": owner.norm_definition_applicability_sha256(case["record"]),
        "evidence": case["evidence_artifacts"], "claims": case["reviews"],
        "companion": case["companion"], "subject": case["subject"], "companion_inputs": case["inputs"]}
    return owner._content(**{**arguments, **overrides})


def replace_record(owner, case, record, *, pretty=False):
    raw = (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
           if pretty else wire(record))
    case["record"], case["raw"] = record, raw
    case["evidence_artifacts"][BODY_ID] = raw
    for claim in case["reviews"]:
        claim["context_closure"] = owner._closure(case["subject"], {"artifact_id": BODY_ID, "sha256": sha(raw)})
    resign(case)


def test_public_template_and_declaration_replay_complete_inputs_without_promoting_meaning(owner, prepared):
    template = owner.build_norm_definition_applicability_template_v1(
        *original_arguments(prepared), **replay_arguments(prepared))
    assert template["declaration"]["declared_at_utc"] is None
    assert len(template["declaration"]["decisions"]) == 2
    assert template["links"] == prepared["companion"]["links"]
    assert template["alternatives"] == prepared["companion"]["definitions"]
    assert all(row["decision"] is row["selected_link_ref"] is row["rationale"] is None
               and row["evidence_refs"] == [] for row in template["declaration"]["decisions"])
    declaration = owner.build_norm_definition_applicability_declaration_v1(
        *original_arguments(prepared), choices(owner, prepared), declared_at_utc=DECLARED,
        **replay_arguments(prepared))
    assert len(declaration["decisions"]) == 2
    assert_unapplied(template)
    assert_unapplied(declaration)


def test_public_signed_body_custody_preserves_pending_endpoint_reviews_and_all_open_norm_questions(owner, case):
    before = wire(case["companion"])
    report = assess(owner, case)
    assert report["common_body_authenticated_under_selected_trust"] is True
    assert report["current_definition_endpoint_prerequisites_satisfied"] is False
    assert report["partial_declaration_custody_prerequisites_satisfied_under_selected_trust"] is False
    assert report["original_companion"] == case["companion"] and wire(case["companion"]) == before
    assert report["counts"]["authenticated_authority_claims"] == 2
    assert report["counts"]["uses"] == report["counts"]["declared_selected_uses"] == 2
    assert report["counts"]["links"] == 4 and report["counts"]["alternatives"] == 2
    assert report["counts"]["decisions_applied"] == report["counts"]["definition_applications"] == 0
    assert report["closed_context_prerequisites_satisfied"] is False
    assert report["combined_norm_meaning_prerequisites_satisfied"] is False
    assert all(row["decision_applied"] is False for row in report["pending_uses"])
    raw = report["raw_applicability_authority_assessment"]
    assert raw["review_prerequisites_satisfied_under_selected_trust"] is False
    assert raw["blockers"]
    assert all(row["current_assessment"]["evaluation_time_utc"] == EVALUATED
               and row["definition_meaning_accepted"] is row["contextual_companion_reviewed"] is False
               for row in report["current_definition_assessments"])
    assert_unapplied(report)


def test_public_full_report_regeneration_refuses_rehashed_promotion_and_preserves_inputs(owner, case):
    report = assess(owner, case)
    args = (*original_arguments(case), *authority_arguments(case))
    kwargs = {**replay_arguments(case), **assessment_arguments(owner, case)}
    checked = owner.validate_norm_definition_applicability_v1(report, *args,
        expected_report_sha256=owner.norm_definition_applicability_sha256(report), **kwargs)
    assert checked == report
    checked["pending_uses"].clear()
    assert report["pending_uses"]
    forged = deepcopy(report)
    forged["training_mask"] = True
    with pytest.raises(ValueError):
        owner.validate_norm_definition_applicability_v1(forged, *args,
            expected_report_sha256=owner.norm_definition_applicability_sha256(forged), **kwargs)


@pytest.mark.parametrize("pin", ["expected_companion_sha256", "expected_norm_subject_sha256",
                                 "expected_norm_manifest_sha256"])
def test_public_independent_complete_input_pins_cannot_be_replaced(owner, prepared, pin):
    arguments = replay_arguments(prepared)
    arguments[pin] = "0" * 64
    with pytest.raises(ValueError):
        owner.build_norm_definition_applicability_template_v1(*original_arguments(prepared), **arguments)


@pytest.mark.parametrize("damage", ["raw_pin", "canonical_pin", "duplicate_json", "changed_body"])
def test_pure_exact_raw_and_complete_canonical_body_pins_are_independent(owner, case, damage):
    overrides = {}
    if damage == "raw_pin": overrides["raw_pin"] = "0" * 64
    elif damage == "canonical_pin": overrides["canonical_pin"] = "0" * 64
    elif damage == "duplicate_json":
        raw = b'{"schema":"x","schema":"y"}'
        case["evidence_artifacts"][BODY_ID] = raw
        overrides["raw_pin"] = sha(raw)
    else: case["evidence_artifacts"][BODY_ID] += b" "
    record, blockers = content_pure(owner, case, **overrides)
    assert record is None and blockers


def test_pure_pretty_body_requires_new_exact_raw_signature_but_keeps_canonical_identity(owner, case, current_definitions):
    old_canonical = owner.norm_definition_applicability_sha256(case["record"])
    old_raw = sha(case["raw"])
    replace_record(owner, case, case["record"], pretty=True)
    assert sha(case["raw"]) != old_raw
    assert owner.norm_definition_applicability_sha256(case["record"]) == old_canonical
    report = assess_pure(owner, case, current_definitions)
    assert report["common_body_authenticated_under_selected_trust"] is True
    assert_unapplied(report)


@pytest.mark.parametrize("damage", ["body_alias", "extra_ref", "resolved_slot", "unresolved_order"])
def test_pure_valid_signatures_cannot_hide_wrong_whole_body_or_close_original_norm_slots(owner, case, current_definitions, damage):
    closure = case["reviews"][1]["context_closure"]
    if damage == "body_alias":
        case["evidence_artifacts"]["fixture:body-alias"] = case["raw"]
        closure["obligations"][0]["evidence_refs"][0]["artifact_id"] = "fixture:body-alias"
    elif damage == "extra_ref":
        closure["obligations"][0]["evidence_refs"].append({"artifact_id": SUPPORT_ID, "sha256": sha(SUPPORT)})
    elif damage == "resolved_slot": closure["obligations"][0]["disposition"] = "resolved_by_evidence"
    else: closure["unresolved"].reverse()
    resign(case)
    report = assess_pure(owner, case, current_definitions)
    assert report["common_body_authenticated_under_selected_trust"] is False
    assert report["content_blockers"]


@pytest.mark.parametrize("damage", ["missing", "changed", "source_alias", "common_body_id"])
def test_pure_support_must_be_independent_exact_raw_bytes(owner, case, damage):
    if damage == "missing": case["evidence_artifacts"].pop(SUPPORT_ID)
    elif damage == "changed": case["evidence_artifacts"][SUPPORT_ID] += b"changed"
    else:
        raw = (wire(case["inputs"]["definitions"][0]["review_evidence"]["assessment"])
               if damage == "source_alias" else case["raw"])
        record = deepcopy(case["record"])
        identity = "fixture:raw-alias" if damage == "source_alias" else BODY_ID
        record["decisions"][0]["evidence_refs"] = [{"artifact_id": identity, "sha256": sha(raw)}]
        case["evidence_artifacts"]["fixture:raw-alias"] = raw
        replace_record(owner, case, record)
    record, blockers = content_pure(owner, case)
    assert record is None and blockers


def test_pure_original_raw_source_can_support_a_declared_association_without_accepting_meaning(owner, case):
    raw = case["inputs"]["norm_inputs"]["context_inputs"]["sources"][0]["raw"]
    identity = "fixture:original-source-support"
    record = deepcopy(case["record"])
    record["decisions"][0]["evidence_refs"] = [{"artifact_id": identity, "sha256": sha(raw)}]
    case["evidence_artifacts"][identity] = raw
    replace_record(owner, case, record)
    checked, blockers = content_pure(owner, case)
    assert checked == record and blockers == []
    assert_unapplied(checked)


@pytest.mark.parametrize("field", ["schema", "action", "audience"])
def test_pure_original_norm_signature_domain_cannot_authorize_applicability(owner, case, current_definitions, field):
    case["reviews"][0][field] = {"schema": norm.CLAIM_SCHEMA, "action": norm.ACTION,
                                 "audience": norm.AUDIENCE}[field]
    resign(case)
    with pytest.raises(ValueError):
        assess_pure(owner, case, current_definitions)


@pytest.mark.parametrize("damage,blocker", [("expiry", "review_not_current"), ("revocation", "key_revoked"),
    ("subject", "signed_subject_differs"), ("signature", "signature_invalid")])
def test_pure_shared_real_signature_verifier_preserves_rejection_reasons(owner, case, current_definitions, damage, blocker):
    if damage == "expiry": case["reviews"][0]["expires_at_utc"] = "2026-10-15T12:02:30Z"
    elif damage == "revocation": case["registry"]["keys"][0]["revoked_at_utc"] = EVALUATED
    elif damage == "subject": case["reviews"][0]["subject"]["ast_sha256"] = "0" * 64
    else: case["reviews"][0]["signature"] = "A" * len(case["reviews"][0]["signature"])
    if damage != "signature": resign(case)
    report = assess_pure(owner, case, current_definitions)
    assert report["common_body_authenticated_under_selected_trust"] is False
    assert any(blocker in row["blockers"] for row in report["raw_applicability_authority_assessment"]["reviews"])


@pytest.mark.parametrize("reuse", ["principal", "did", "public_key"])
def test_pure_source_inventory_keeps_outlier_claimed_and_registered_actors_and_blocks_reuse(owner, case, current_definitions, reuse):
    case["inputs"] = deepcopy(case["inputs"])
    arguments = case["inputs"]["definitions"][0]["review_evidence"]["assessment_inputs"]
    key = deepcopy(case["registry"]["keys"][0])
    key["key_id"] = "fixture:outlier-source-key"
    if reuse != "principal": key["principal_id"] = "fixture:registered-source-principal"
    if reuse != "did": key["signer_did"] = "did:example:registered-source"
    if reuse != "public_key": key["public_key_hex"] = "01" * 32
    arguments["registry"]["keys"] = [key]
    arguments["reviews"] = [{"review_id": "fixture:rejected-source-outlier", "key_id": key["key_id"],
        "principal_id": "fixture:claimed-source-outlier", "signer_did": "did:example:claimed-source-outlier",
        "issued_at_utc": "2026-10-15T11:00:00Z"}]
    inventory = owner._source_exclusions(case["inputs"])
    assert {key["principal_id"], "fixture:claimed-source-outlier"} <= set(inventory["excluded_principal_ids"])
    assert {key["signer_did"], "did:example:claimed-source-outlier"} <= set(inventory["excluded_signer_dids"])
    assert key["public_key_hex"] in inventory["excluded_public_keys"]
    report = assess_pure(owner, case, current_definitions)
    fragment = {"principal": "source_principal", "did": "source_did", "public_key": "source_public_key"}[reuse]
    assert any(fragment in blocker for blocker in report["separation_and_chronology_blockers"])
    assert report["partial_declaration_custody_prerequisites_satisfied_under_selected_trust"] is False


@pytest.mark.parametrize("actor", ["unknown_key", "unsigned_context"])
def test_pure_incomplete_source_actor_inventory_blocks_partial_custody_independently_of_body_authentication(owner, case, current_definitions, actor):
    case["inputs"] = deepcopy(case["inputs"])
    endpoint = case["inputs"]["definitions"][0]
    if actor == "unknown_key":
        endpoint["review_evidence"]["assessment_inputs"]["reviews"] = [{
            "review_id": "fixture:unknown-source-review", "key_id": "fixture:missing-source-key",
            "principal_id": "fixture:unknown-source-principal", "signer_did": "did:example:unknown-source",
            "issued_at_utc": "2026-10-15T11:00:00Z"}]
        blocker = "definition_source_public_key_inventory_incomplete"
    else:
        endpoint["correspondence_inputs"]["contextual_replay_inputs"]["responses"] = [{
            "declaration": {"reviewer_declaration": {"principal_id": "fixture:unsigned-context-principal",
                "issued_at_utc": "2026-10-15T11:00:00Z"}}}]
        blocker = "unsigned_contextual_actor_cryptographic_inventory_unavailable"
    report = assess_pure(owner, case, current_definitions)
    assert report["common_body_authenticated_under_selected_trust"] is True
    assert blocker in report["separation_and_chronology_blockers"]
    assert report["source_reviewer_exclusions"]["cryptographic_actor_inventory_complete"] is False
    assert report["partial_declaration_custody_prerequisites_satisfied_under_selected_trust"] is False


@pytest.mark.parametrize("damage", ["missing", "reordered", "foreign", "extra_field"])
def test_pure_current_definition_observation_population_is_complete_closed_and_ordered(owner, prepared, damage):
    rows = deepcopy(prepared["definition_observations"])
    if damage == "missing": rows.pop()
    elif damage == "reordered": rows.reverse()
    elif damage == "foreign": rows[0]["alternative_id"] = "fixture:foreign-alternative"
    else: rows[0]["observations"]["assume_applicable"] = True
    with pytest.raises(ValueError):
        owner._definition_observations(prepared["inputs"], rows)


def refresh_endpoint(endpoint, signers):
    from ipfs_datasets_py.logic.autoformal import corpus_definition_review_v2 as definition_review

    evidence_record = endpoint["review_evidence"]
    arguments = evidence_record["assessment_inputs"]
    arguments["policy"]["registry_sha256"] = auth.digest(arguments["registry"])
    for index, old in enumerate(arguments["reviews"]):
        body = {key: deepcopy(value) for key, value in old.items()
                if key not in {"signer_did", "signature_alg", "signature"}}
        body.update(registry_sha256=auth.digest(arguments["registry"]),
                    policy_sha256=auth.digest(arguments["policy"]))
        arguments["reviews"][index] = signers[index].sign(body)
    arguments.update(expected_registry_sha256=auth.digest(arguments["registry"]),
        expected_policy_sha256=auth.digest(arguments["policy"]),
        expected_reviews_sha256=auth.digest(arguments["reviews"]))
    assessment = definition_review.assess_definition_reviews_v2(**arguments)
    evidence_record.update(assessment=assessment,
        expected_assessment_sha256=evidence.norm_definition_evidence_sha256(assessment))
    return assessment


@pytest.fixture(scope="module")
def signed_endpoints(owner, prepared):
    """Four genuine endpoint signatures, original and current owner replays."""
    from cryptography.hazmat.primitives import serialization
    from ipfs_datasets_py.logic.profile_g import Ed25519Signer
    from ipfs_datasets_py.logic.autoformal import corpus_definition_review_v2 as definition_review

    inputs = deepcopy(prepared["inputs"])
    all_signers = []
    for number, endpoint in enumerate(inputs["definitions"]):
        arguments = endpoint["review_evidence"]["assessment_inputs"]
        subject = arguments["subject"]
        signers = [Ed25519Signer.generate("did:example:definition-source:" + str(number) + ":" + str(index))
                   for index in range(2)]
        all_signers.append(signers)
        registry = arguments["registry"]
        registry["mode"] = "external_pinned_trust"
        registry["keys"] = [{"key_id": "fixture:definition-source-key:" + str(number) + ":" + str(index),
            "principal_id": "fixture:definition-source-principal:" + str(number) + ":" + str(index),
            "signer_did": signer.did, "public_key_hex": signer.public_key.public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex(), "roles": [role],
            "scope_ids": [subject["scope_id"]], "valid_from_utc": START,
            "valid_until_utc": END, "revoked_at_utc": None}
            for index, (signer, role) in enumerate(zip(signers, auth.ROLES, strict=True))]
        policy = arguments["policy"]
        policy["mode"] = "external_pinned_trust"
        support_id = "fixture:definition-source-context:" + str(number)
        support_raw = b"Fictional definition context declaration, not legal truth."
        arguments["evidence_artifacts"] = {support_id: support_raw}
        closure = {"status": "declared_complete", "unresolved": [], "obligations": [{
            "slot_id": slot, "disposition": "not_applicable",
            "evidence_refs": [{"artifact_id": support_id, "sha256": sha(support_raw)}]}
            for slot in subject["context_slot_ids"]]}
        arguments["reviews"] = [{"schema": definition_review.CLAIM_SCHEMA,
            "action": definition_review.ACTION, "audience": definition_review.AUDIENCE,
            "review_id": "fixture:definition-source-review:" + str(number) + ":" + str(index),
            "key_id": key["key_id"], "principal_id": key["principal_id"], "role": role,
            "registry_sha256": "0" * 64, "policy_sha256": "0" * 64,
            "issued_at_utc": "2026-10-15T11:00:00Z", "expires_at_utc": EXPIRES,
            "subject": deepcopy(subject), "context_closure": deepcopy(closure),
            "interpretation": {"decision": "support", "reviewed_graph_sha256": subject["graph_sha256"],
                "reviewed_ast_sha256": subject["ast_sha256"], "ambiguity": [],
                "rationale": "Fictional source endpoint custody; applicability remains independently declared."}}
            for index, (key, role) in enumerate(zip(registry["keys"], auth.ROLES, strict=True))]
        original = refresh_endpoint(endpoint, signers)
        assert original["authenticated_evidence_count"] == 2
    endpoint_observations = [{"alternative_id": endpoint["alternative_id"], "observations": {
        key: deepcopy(endpoint["review_evidence"]["assessment_inputs"][key]) for key in (
            "observed_artifact_sha256s", "observed_pins", "evidence_artifacts")}}
        for endpoint in inputs["definitions"]]
    current = owner._current_definitions(inputs, endpoint_observations, EVALUATED, lambda: None)
    assert all(row["current_authentication_prerequisites_satisfied"] is True for row in current)
    return {"inputs": inputs, "definition_observations": endpoint_observations,
            "signers": all_signers, "current": current}


def test_public_genuine_signed_endpoints_allow_partial_declaration_custody_while_meaning_stays_open(owner, helper, prepared, signed_endpoints):
    data = dict(prepared, inputs=signed_endpoints["inputs"],
                definition_observations=signed_endpoints["definition_observations"])
    data["companion"] = helper.prepare(data["inputs"])
    declaration = owner._declaration(data["companion"], data["subject"], data["inputs"],
                                      choices(owner, data), DECLARED)
    report = assess(owner, signed_case(owner, data, declaration))
    assert report["common_body_authenticated_under_selected_trust"] is True
    assert report["current_definition_endpoint_prerequisites_satisfied"] is True
    assert report["partial_declaration_custody_prerequisites_satisfied_under_selected_trust"] is True
    assert report["source_reviewer_exclusions"]["norm_review_actor_inventory_supplied"] is False
    assert len(report["source_reviewer_exclusions"]["actors"]) == 4
    assert report["raw_applicability_authority_assessment"]["review_prerequisites_satisfied_under_selected_trust"] is False
    assert report["combined_norm_meaning_prerequisites_satisfied"] is False
    assert report["closed_context_prerequisites_satisfied"] is False
    assert_unapplied(report)


@pytest.mark.parametrize("damage", ["expiry", "scheduled_revocation", "dependency", "context_slots", "evidence"])
def test_pure_genuine_current_endpoint_replay_activates_time_dependencies_and_context_intake(owner, signed_endpoints, damage):
    inputs = deepcopy(signed_endpoints["inputs"])
    observed = deepcopy(signed_endpoints["definition_observations"])
    endpoint = inputs["definitions"][0]
    arguments = endpoint["review_evidence"]["assessment_inputs"]
    if damage == "expiry":
        arguments["reviews"][0]["expires_at_utc"] = "2026-10-15T12:02:30Z"
        refresh_endpoint(endpoint, signed_endpoints["signers"][0])
    elif damage == "scheduled_revocation":
        arguments["registry"]["keys"][0]["revoked_at_utc"] = "2026-10-15T12:02:30Z"
        refresh_endpoint(endpoint, signed_endpoints["signers"][0])
    elif damage == "dependency":
        identity = next(iter(observed[0]["observations"]["observed_artifact_sha256s"]))
        observed[0]["observations"]["observed_artifact_sha256s"][identity] = "0" * 64
    elif damage == "context_slots":
        arguments["reviews"][0]["context_closure"]["obligations"].pop()
        refresh_endpoint(endpoint, signed_endpoints["signers"][0])
    else:
        identity = next(iter(observed[0]["observations"]["evidence_artifacts"]))
        observed[0]["observations"]["evidence_artifacts"][identity] += b"changed"
    original = wire(endpoint["review_evidence"]["assessment"])
    current = owner._current_definitions(inputs, observed, EVALUATED, lambda: None)
    assert current[0]["current_authentication_prerequisites_satisfied"] is False
    assert current[0]["current_blockers"]
    assert current[1]["current_authentication_prerequisites_satisfied"] is True
    assert wire(endpoint["review_evidence"]["assessment"]) == original
    if damage in {"expiry", "scheduled_revocation"}:
        assert endpoint["review_evidence"]["assessment"]["authenticated_evidence_count"] == 2
        assert current[0]["current_assessment"]["authenticated_evidence_count"] == 1


def test_pure_context_intake_preserves_explicit_open_scope_and_dissent_without_treating_prose_as_slot_ids(owner, signed_endpoints):
    original = signed_endpoints["inputs"]["definitions"][0]["review_evidence"]["assessment_inputs"]
    reviews = deepcopy(original["reviews"])
    # Only the exact context-intake seam is under test; these edited claims are
    # not represented as newly authenticated source reports.
    reviews[0]["interpretation"]["decision"] = "reject"
    closure = reviews[0]["context_closure"]
    closure["status"] = "open"
    closure["obligations"][0]["disposition"] = "open"
    closure["obligations"][0]["evidence_refs"] = []
    closure["unresolved"] = ["Fictional scope remains disputed; this is prose, not a slot identity."]
    assert owner._definition_context_intake(original["subject"], reviews, original["evidence_artifacts"]) == []


def test_pure_genuine_signed_endpoint_dissent_stays_authenticated_without_erasing_raw_conflict(owner, signed_endpoints):
    inputs = deepcopy(signed_endpoints["inputs"])
    endpoint = inputs["definitions"][0]
    endpoint["review_evidence"]["assessment_inputs"]["reviews"][0]["interpretation"]["decision"] = "reject"
    assessment = refresh_endpoint(endpoint, signed_endpoints["signers"][0])
    original = wire(assessment)
    current = owner._current_definitions(inputs, signed_endpoints["definition_observations"],
                                        EVALUATED, lambda: None)
    assert current[0]["current_authentication_prerequisites_satisfied"] is True
    raw = current[0]["current_assessment"]
    assert raw["authenticated_evidence_count"] == 2
    assert "authenticated_review_conflict_or_ambiguity" in raw["blockers"]
    assert any(row["declared_decision"] == "reject" for row in raw["reviews"])
    assert wire(endpoint["review_evidence"]["assessment"]) == original


@pytest.mark.parametrize("side", ["caller", "detached"])
def test_public_input_mutation_fence_rejects_changes_after_genuinely_replayed_context(owner, case, current_definitions, monkeypatch, side):
    case["inputs"] = deepcopy(case["inputs"])
    companion = case["companion"]
    def mutate(value):
        target = case["inputs"] if side == "caller" else value["companion_inputs"]
        target["definitions"][0]["alternative_id"] = "fixture:mutated-after-context"
        return companion
    # The genuinely prepared companion is reused only to isolate the outer
    # public mutation fence. Complete replay is exercised by other public cases.
    monkeypatch.setattr(owner, "_context", mutate)
    with pytest.raises(ValueError, match="changed"):
        assess(owner, case)
