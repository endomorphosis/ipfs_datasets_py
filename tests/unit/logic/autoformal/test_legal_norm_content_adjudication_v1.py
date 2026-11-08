"""Fictional norm-answer adjudication authenticates custody, never legal meaning.

Public cases replay real authored source/context evidence. Tests named pure use
the same genuinely prepared source reports with the downstream content/trust
seams; they do not claim that those seams replace public source replay. Every
key, registry, review and evidence declaration here is an engineering fixture.
"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_graph_review as auth
from ipfs_datasets_py.logic.autoformal import legal_norm_content_responses_v1 as content
from ipfs_datasets_py.logic.autoformal import legal_norm_interpretation_review_v1 as norm


DECLARED = "2026-10-15T12:01:00Z"
SIGNED = "2026-10-15T12:02:00Z"
EVALUATED = "2026-10-15T12:03:00Z"
EXPIRES = "2026-10-16T11:00:00Z"
BODY_ID = "fixture:norm-adjudication-common-body"
SUPPORT_ID = "fixture:norm-adjudication-support"


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_fixture(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fixtures():
    return {
        "norm": load_fixture("_adjudication_authored_norm_source", "test_legal_norm_interpretation_review_v1.py"),
        "content": load_fixture("_adjudication_authored_typed_answers", "test_legal_norm_content_responses_v1.py"),
    }


@pytest.fixture(scope="module")
def owner():
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1

    return legal_norm_content_adjudication_v1


def clone_source(value):
    result = deepcopy({key: child for key, child in value.items() if key != "signers"})
    result["signers"] = list(value["signers"])
    return result


def refresh_source_reports(fixtures, source):
    helper = fixtures["content"]
    original_helper = fixtures["norm"]
    source["typed_assessment"] = helper.assess(content, original_helper, source)
    args, inputs = helper.assessment_arguments(content, original_helper, source)
    source["response_inputs"] = inputs
    current_inputs = {**inputs, "at_time_utc": EVALUATED}
    source["current_typed"] = content.assess_norm_content_responses_v1(*args, **current_inputs)
    return source


@pytest.fixture(scope="module")
def materialized(fixtures):
    return fixtures["norm"].materialize(norm, with_context=True)


@pytest.fixture(scope="module")
def source_base(fixtures, materialized):
    source = fixtures["content"].signed_content(content, fixtures["norm"], materialized)
    # This is an authored wire fixture for selected-trust checks, not a supplied
    # production registry or evidence of human identity/independence.
    source["registry"]["mode"] = source["policy"]["mode"] = "external_pinned_trust"
    fixtures["norm"].refresh(source)
    return refresh_source_reports(fixtures, source)


def source_arguments(source):
    return (source["typed_assessment"], source["subject"], source["registry"], source["policy"],
            source["reviews"], source["manifest"])


def declaration_arguments(source):
    return {"expected_typed_assessment_sha256": content.norm_content_sha256(source["typed_assessment"]),
            "response_inputs": source["response_inputs"]}


def choices(source, *, all_unresolved=False):
    typed = source["typed_assessment"]
    refs = [{"artifact_id": SUPPORT_ID, "sha256": sha(b"Fictional adjudication support; no accepted statutory meaning.")}]
    result = []
    for question in typed["pending_questions"]:
        candidates = [ref for ref in question["answer_variant_refs"]
                      if typed["answer_variants"][ref["variant_index"]]["answer"]["disposition"] != "unresolved"]
        selected = None if all_unresolved or not candidates else deepcopy(candidates[0])
        result.append({"slot_id": question["slot_id"], "kind": question["kind"],
            "obligation_sha256": question["obligation_sha256"],
            "decision": "unresolved" if selected is None else "select_existing_variant",
            "selected_variant_ref": selected,
            "rationale": "Fictional existing-answer reference; no statutory decision is applied.",
            "evidence_refs": [] if selected is None else deepcopy(refs)})
    return result


@pytest.fixture(scope="module")
def declared_base(owner, source_base):
    return owner.build_norm_content_adjudication_declaration_v1(
        *source_arguments(source_base), choices(source_base), declared_at_utc=DECLARED,
        **declaration_arguments(source_base))


def claim_closure(record, typed, body_ref):
    unresolved = []
    obligations = []
    dispositions = {"evidence_declared": "resolved_by_evidence", "not_applicable": "not_applicable"}
    for decision in record["decisions"]:
        if decision["decision"] == "unresolved":
            disposition = "open"
            unresolved.append(decision["slot_id"])
        else:
            answer = typed["answer_variants"][decision["selected_variant_ref"]["variant_index"]]["answer"]
            disposition = dispositions[answer["disposition"]]
        obligations.append({"slot_id": decision["slot_id"], "disposition": disposition,
                            "evidence_refs": [deepcopy(body_ref)]})
    return {"status": "open" if unresolved else "declared_complete",
            "unresolved": unresolved, "obligations": obligations}


def resign_adjudication(case):
    adjudication = case["adjudication"]
    adjudication["policy"]["registry_sha256"] = auth.digest(adjudication["registry"])
    for index, claim in enumerate(adjudication["reviews"]):
        body = {key: deepcopy(value) for key, value in claim.items()
                if key not in {"signer_did", "signature_alg", "signature"}}
        body.update(registry_sha256=auth.digest(adjudication["registry"]),
                    policy_sha256=auth.digest(adjudication["policy"]))
        adjudication["reviews"][index] = adjudication["signers"][index].sign(body)


def signed_case(owner, source, *, record=None):
    from cryptography.hazmat.primitives import serialization
    from ipfs_datasets_py.logic.profile_g import Ed25519Signer

    source = clone_source(source)
    record = owner._declaration(source["typed_assessment"], source["subject"], source["reviews"],
                                choices(source), DECLARED) if record is None else deepcopy(record)
    raw = wire(record)
    signers = [Ed25519Signer.generate("did:example:norm-adjudicator:" + str(index)) for index in range(2)]
    registry = deepcopy(source["registry"])
    registry["process_id"] = "fixture:norm-adjudication-process"
    for index, key in enumerate(registry["keys"]):
        key.update(key_id="fixture:norm-adjudication-key:" + str(index),
            principal_id="fixture:norm-adjudicator:" + str(index), signer_did=signers[index].did,
            public_key_hex=signers[index].public_key.public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex(), revoked_at_utc=None)
    policy = deepcopy(source["policy"])
    policy.update(policy_id="fixture:norm-adjudication-policy", process_id=registry["process_id"],
                  registry_sha256=auth.digest(registry), action=owner.ACTION, audience=owner.AUDIENCE)
    body_ref = {"artifact_id": BODY_ID, "sha256": sha(raw)}
    closure = claim_closure(record, source["typed_assessment"], body_ref)
    reviews = []
    for index, signer in enumerate(signers):
        claim = {key: deepcopy(value) for key, value in source["reviews"][index].items()
                 if key not in {"signer_did", "signature_alg", "signature"}}
        claim.update(schema=owner.CLAIM_SCHEMA, action=owner.ACTION, audience=owner.AUDIENCE,
            review_id="fixture:norm-adjudication-review:" + str(index),
            key_id=registry["keys"][index]["key_id"], principal_id=registry["keys"][index]["principal_id"],
            registry_sha256=auth.digest(registry), policy_sha256=auth.digest(policy),
            issued_at_utc=SIGNED, expires_at_utc=EXPIRES, subject=deepcopy(source["subject"]),
            context_closure=deepcopy(closure), interpretation={"decision": "support",
                "reviewed_graph_sha256": source["subject"]["graph_sha256"],
                "reviewed_ast_sha256": source["subject"]["ast_sha256"],
                "rationale": "Fictional common-body authentication only; no legal acceptance.", "ambiguity": []})
        reviews.append(signer.sign(claim))
    source["adjudication"] = {"registry": registry, "policy": policy, "reviews": reviews,
        "signers": signers, "declaration": record, "raw": raw,
        "evidence_artifacts": {**source["evidence_artifacts"], BODY_ID: raw,
            SUPPORT_ID: b"Fictional adjudication support; no accepted statutory meaning."}}
    return source


@pytest.fixture
def case(owner, source_base, declared_base):
    return signed_case(owner, source_base, record=declared_base)


def adjudication_arguments(case):
    adjudication = case["adjudication"]
    return {"declaration_artifact_id": BODY_ID,
        "expected_declaration_raw_sha256": sha(adjudication["raw"]),
        "expected_declaration_sha256": content.norm_content_sha256(adjudication["declaration"]),
        "expected_adjudication_registry_sha256": auth.digest(adjudication["registry"]),
        "expected_adjudication_policy_sha256": auth.digest(adjudication["policy"]),
        "expected_adjudication_reviews_sha256": auth.digest(adjudication["reviews"]),
        "at_time_utc": EVALUATED, "observed_artifact_sha256s": case["observed_artifact_sha256s"],
        "observed_pins": case["observed_pins"], "evidence_artifacts": adjudication["evidence_artifacts"]}


def authority_arguments(case):
    adjudication = case["adjudication"]
    return (adjudication["registry"], adjudication["policy"], adjudication["reviews"])


def assess(owner, case, **overrides):
    return owner.assess_norm_content_adjudication_v1(*source_arguments(case), *authority_arguments(case),
        **{**declaration_arguments(case), **adjudication_arguments(case), **overrides})


def assess_pure(owner, case, **overrides):
    """Real compact trust/content checks over already replayed source reports."""
    typed, subject, registry, policy, reviews, manifest = source_arguments(case)
    return owner._assess_prepared(typed, case["current_typed"], subject, registry, policy, reviews,
        manifest, *authority_arguments(case), **{**adjudication_arguments(case), **overrides})


def content_pure(owner, case, **overrides):
    adjudication = case["adjudication"]
    values = {"identity": BODY_ID, "expected_raw_sha256": sha(adjudication["raw"]),
        "expected_canonical_sha256": content.norm_content_sha256(adjudication["declaration"]),
        "evidence": adjudication["evidence_artifacts"], "claims": adjudication["reviews"],
        "typed": case["typed_assessment"], "subject": case["subject"], "source_reviews": case["reviews"],
        "response_body_ids": {row["artifact_id"] for row in case["response_bindings"]},
        "response_body_sha256s": {row["raw_sha256"] for row in case["response_bindings"]}}
    return owner._content(**{**values, **overrides})


def assert_unapplied(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert report["norm_interpretation_ready"] is False
    assert report["selected_interpretation"] is report["accepted_interpretation"] is report["governing_definition_use"] is None
    for field in ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"):
        assert type(report[field]) is int and report[field] == 0
    if report["schema"].endswith("assessment/v1"):
        assert report["closed_context_prerequisites_satisfied"] is False
        assert report["counts"]["decisions_applied"] == report["counts"]["definition_applications"] == 0
        assert all(row["decision_applied"] is False for row in report["pending_slots"])
        raw = report["raw_adjudication_authority_assessment"]
        assert raw["review_prerequisites_satisfied_under_selected_trust"] is False
        assert "authenticated_complete_context_declarations_missing" in raw["blockers"]


def install_declaration(case, record, *, raw=None):
    adjudication = case["adjudication"]
    adjudication["declaration"] = deepcopy(record)
    adjudication["raw"] = wire(record) if raw is None else raw
    adjudication["evidence_artifacts"][BODY_ID] = adjudication["raw"]
    body_ref = {"artifact_id": BODY_ID, "sha256": sha(adjudication["raw"])}
    closure = claim_closure(record, case["typed_assessment"], body_ref)
    for claim in adjudication["reviews"]:
        claim["context_closure"] = deepcopy(closure)
    resign_adjudication(case)


def selected_choice(record):
    return next(choice for choice in record["decisions"] if choice["decision"] == "select_existing_variant")


def test_public_complete_replay_authenticates_partial_custody_with_every_semantic_gate_open(owner, case):
    template = owner.build_norm_content_adjudication_template_v1(
        *source_arguments(case), **declaration_arguments(case))
    draft = template["declaration"]
    assert draft["declared_at_utc"] is None
    assert len(draft["decisions"]) == len(case["typed_assessment"]["original_obligations"])
    assert all(row["decision"] is row["selected_variant_ref"] is row["rationale"] is None
               and row["evidence_refs"] == [] for row in draft["decisions"])
    assert template["answer_variants"] == case["typed_assessment"]["answer_variants"]
    assert_unapplied(template)
    original = wire(case["typed_assessment"])
    report = assess(owner, case)
    assert wire(report["original_typed_assessment"]) == original == wire(case["typed_assessment"])
    assert report["current_typed_assessment"] == case["current_typed"]
    assert report["common_body_authenticated_under_selected_trust"] is True
    assert report["current_source_prerequisites_satisfied"] is True
    assert report["adjudication_prerequisites_satisfied_under_selected_trust"] is True
    assert report["raw_adjudication_authority_assessment"]["authenticated_evidence_count"] == 2
    assert not report["content_blockers"] and not report["separation_and_chronology_blockers"]
    assert report["counts"]["source_reviews"] == 2
    assert report["counts"]["declared_selected_slots"] + report["counts"]["unresolved_or_absent_slots"] == len(draft["decisions"])
    assert_unapplied(report)
    args = (*source_arguments(case), *authority_arguments(case))
    kwargs = {**declaration_arguments(case), **adjudication_arguments(case)}
    validated = owner.validate_norm_content_adjudication_v1(report, *args,
        expected_report_sha256=owner.norm_content_adjudication_sha256(report), **kwargs)
    assert validated == report
    validated["pending_slots"].clear()
    assert report["pending_slots"]
    forged = deepcopy(report)
    forged["authority"][next(iter(forged["authority"]))] = 0
    with pytest.raises(ValueError):
        owner.validate_norm_content_adjudication_v1(forged, *args,
            expected_report_sha256=owner.norm_content_adjudication_sha256(forged), **kwargs)


def test_public_replay_preserves_dissenting_answer_variants_after_a_declared_choice(owner, fixtures, source_base):
    source = clone_source(source_base)
    helper = fixtures["content"]
    record = helper.current_record(source, 1)
    finding = helper.answer_for(record, "source_meaning")["finding"]
    finding["source_assertions"][0]["assessment"] = "dispute"
    finding["statement"] = "A conflicting fictional finding retained without majority selection."
    helper.replace_record(fixtures["norm"], source, 1, record)
    refresh_source_reports(fixtures, source)
    case = signed_case(owner, source)
    report = assess(owner, case)
    slot = helper.answer_for(record, "source_meaning")["slot_id"]
    assert len([v for v in report["original_typed_assessment"]["answer_variants"] if v["slot_id"] == slot]) == 2
    assert report["original_typed_assessment"] == source["typed_assessment"]
    assert report["current_typed_assessment"] == source["current_typed"]
    assert report["adjudication_prerequisites_satisfied_under_selected_trust"] is True
    assert_unapplied(report)


@pytest.mark.parametrize("event", ["expiry", "scheduled_revocation"])
def test_public_recheck_activates_original_snapshot_time_constraints_without_rewriting_old_report(owner, fixtures, source_base, event):
    source = clone_source(source_base)
    if event == "expiry":
        source["reviews"][0]["expires_at_utc"] = "2026-10-15T12:02:30Z"
    else:
        source["registry"]["keys"][0]["revoked_at_utc"] = "2026-10-15T12:02:30Z"
    fixtures["norm"].refresh(source)
    refresh_source_reports(fixtures, source)
    assert source["typed_assessment"]["counts"]["authenticated_typed_responses"] == 2
    assert source["current_typed"]["counts"]["authenticated_typed_responses"] == 1
    case = signed_case(owner, source)
    original = wire(source["typed_assessment"])
    report = assess(owner, case)
    assert wire(report["original_typed_assessment"]) == original
    assert report["original_typed_assessment"]["raw_norm_assessment"]["evaluation_time_utc"] == fixtures["norm"].NOW
    assert report["current_typed_assessment"]["raw_norm_assessment"]["evaluation_time_utc"] == EVALUATED
    blocker = "review_not_current" if event == "expiry" else "key_revoked"
    assert blocker in report["current_typed_assessment"]["raw_norm_assessment"]["reviews"][0]["blockers"]
    assert report["common_body_authenticated_under_selected_trust"] is True
    assert report["current_source_prerequisites_satisfied"] is False
    assert report["adjudication_prerequisites_satisfied_under_selected_trust"] is False
    assert report["raw_adjudication_authority_assessment"]["authenticated_evidence_count"] == 2
    assert_unapplied(report)


def test_public_current_observations_invalidate_dependencies_without_replacing_original_assessment(owner, case):
    observed = deepcopy(case["observed_artifact_sha256s"])
    observed[case["subject"]["graph_id"]] = "0" * 64
    report = assess(owner, case, observed_artifact_sha256s=observed)
    assert report["original_typed_assessment"] == case["typed_assessment"]
    assert "required_dependency_closure_not_current" in report["current_typed_assessment"]["raw_norm_assessment"]["blockers"]
    assert report["current_source_prerequisites_satisfied"] is False
    assert report["adjudication_prerequisites_satisfied_under_selected_trust"] is False
    assert_unapplied(report)


def test_public_absent_declaration_keeps_complete_population_pending_without_inventing_choices(owner, case):
    case["adjudication"]["reviews"] = []
    report = assess(owner, case, declaration_artifact_id=None,
                    expected_declaration_raw_sha256=None, expected_declaration_sha256=None)
    assert report["declaration_record"] is None
    assert report["common_body_content_status"] == "absent"
    assert report["counts"]["declaration_bodies"] == report["counts"]["authenticated_authority_claims"] == 0
    assert report["counts"]["unresolved_or_absent_slots"] == len(case["typed_assessment"]["original_obligations"])
    assert all(row["declared_decision"] is None for row in report["pending_slots"])
    assert report["adjudication_prerequisites_satisfied_under_selected_trust"] is False
    assert_unapplied(report)


@pytest.mark.parametrize("damage", [
    "missing", "reordered", "kind", "obligation_hash", "foreign_variant", "variant_other_slot",
    "unresolved_variant", "definition_selection", "unresolved_reference", "missing_evidence", "replacement_ast",
])
def test_pure_complete_choices_bind_original_obligations_and_authenticated_existing_variants(owner, case, damage):
    decisions = choices(case)
    selected = next(row for row in decisions if row["decision"] == "select_existing_variant")
    if damage == "missing": decisions.pop()
    elif damage == "reordered": decisions.reverse()
    elif damage == "kind": decisions[0]["kind"] = "interpretation_question"
    elif damage == "obligation_hash": selected["obligation_sha256"] = "0" * 64
    elif damage == "foreign_variant": selected["selected_variant_ref"]["sha256"] = "0" * 64
    elif damage == "variant_other_slot": selected["selected_variant_ref"] = deepcopy(case["typed_assessment"]["pending_questions"][0]["answer_variant_refs"][0])
    elif damage == "unresolved_variant":
        decisions[0].update(decision="select_existing_variant", evidence_refs=deepcopy(selected["evidence_refs"]),
            selected_variant_ref=deepcopy(case["typed_assessment"]["pending_questions"][0]["answer_variant_refs"][0]))
    elif damage == "definition_selection":
        index = next(index for index, row in enumerate(case["typed_assessment"]["original_obligations"])
                     if row.get("question") == "definition_applicability")
        decisions[index].update(decision="select_existing_variant", evidence_refs=deepcopy(selected["evidence_refs"]),
            selected_variant_ref=deepcopy(case["typed_assessment"]["pending_questions"][index]["answer_variant_refs"][0]))
    elif damage == "unresolved_reference": decisions[0]["selected_variant_ref"] = deepcopy(selected["selected_variant_ref"])
    elif damage == "missing_evidence": selected["evidence_refs"] = []
    else: selected["replacement_ast"] = {}
    with pytest.raises(ValueError):
        owner._declaration(case["typed_assessment"], case["subject"], case["reviews"], decisions, DECLARED)


@pytest.mark.parametrize("damage", ["wrong_index_type", "respondent_identity", "unauthenticated_respondent"])
def test_pure_variant_selection_checks_exact_respondent_and_answer_not_only_variant_hash(owner, case, damage):
    typed = deepcopy(case["typed_assessment"])
    decisions = choices(case)
    choice = next(row for row in decisions if row["decision"] == "select_existing_variant")
    ref = choice["selected_variant_ref"]
    if damage == "wrong_index_type":
        ref["variant_index"] = True
    else:
        variant = typed["answer_variants"][ref["variant_index"]]
        respondent = variant["respondents"][0]
        if damage == "respondent_identity": respondent["principal_id"] = "fixture:forged-respondent"
        else: typed["response_results"][respondent["response_result_index"]]["authenticated_typed_content"] = False
        ref["sha256"] = content.norm_content_sha256(variant)
        pending = next(row for row in typed["pending_questions"] if row["slot_id"] == choice["slot_id"])
        pending["answer_variant_refs"] = [deepcopy(ref)]
    with pytest.raises(ValueError):
        owner._declaration(typed, case["subject"], case["reviews"], decisions, DECLARED)


@pytest.mark.parametrize("damage", ["body_alias", "extra_reference", "disposition", "status", "unresolved_order"])
def test_pure_valid_signatures_do_not_hide_wrong_whole_body_or_choice_closure(owner, case, damage):
    closure = case["adjudication"]["reviews"][1]["context_closure"]
    if damage in {"body_alias", "extra_reference"}:
        alias = "fixture:same-common-body-under-other-id"
        case["adjudication"]["evidence_artifacts"][alias] = case["adjudication"]["raw"]
        ref = {"artifact_id": alias, "sha256": sha(case["adjudication"]["raw"])}
        if damage == "body_alias": closure["obligations"][0]["evidence_refs"] = [ref]
        else: closure["obligations"][0]["evidence_refs"].append(ref)
    elif damage == "disposition": closure["obligations"][0]["disposition"] = "not_applicable"
    elif damage == "status": closure["status"] = "declared_complete"
    else: closure["unresolved"].reverse()
    resign_adjudication(case)
    report = assess_pure(owner, case)
    assert report["raw_adjudication_authority_assessment"]["authenticated_evidence_count"] == 2
    assert report["common_body_content_status"] == "rejected"
    assert report["common_body_authenticated_under_selected_trust"] is False
    assert report["content_blockers"]
    assert_unapplied(report)


@pytest.mark.parametrize("damage", ["missing", "changed", "canonical_pin", "duplicate_json"])
def test_pure_exact_common_raw_and_canonical_pins_are_independent(owner, case, damage):
    if damage == "missing": del case["adjudication"]["evidence_artifacts"][BODY_ID]
    elif damage == "changed": case["adjudication"]["evidence_artifacts"][BODY_ID] += b" "
    elif damage == "duplicate_json":
        record = case["adjudication"]["declaration"]
        raw = b'{"schema":' + wire(record["schema"]) + b"," + wire(record)[1:]
        assert json.loads(raw) == record
        install_declaration(case, record, raw=raw)
    overrides = {"expected_canonical_sha256": "0" * 64} if damage == "canonical_pin" else {}
    record, blockers = content_pure(owner, case, **overrides)
    assert record is None and blockers


def test_pure_pretty_raw_body_preserves_canonical_identity_but_requires_its_exact_signed_raw_hash(owner, case):
    record = case["adjudication"]["declaration"]
    original_raw_hash = sha(case["adjudication"]["raw"])
    canonical_pin = content.norm_content_sha256(record)
    pretty = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False).encode()
    install_declaration(case, record, raw=pretty)
    assert sha(pretty) != original_raw_hash
    assert content.norm_content_sha256(json.loads(pretty)) == canonical_pin
    checked, blockers = content_pure(owner, case)
    assert checked == record and blockers == []
    report = assess_pure(owner, case)
    assert report["common_body_authenticated_under_selected_trust"] is True
    assert_unapplied(report)


@pytest.mark.parametrize("damage", ["missing_support", "changed_support", "source_body_id", "source_body_hash_alias"])
def test_pure_supporting_evidence_cannot_be_missing_changed_or_alias_a_source_response(owner, case, damage):
    if damage == "missing_support": del case["adjudication"]["evidence_artifacts"][SUPPORT_ID]
    elif damage == "changed_support": case["adjudication"]["evidence_artifacts"][SUPPORT_ID] += b" changed"
    else:
        source = case["response_bindings"][0]
        identity = source["artifact_id"]
        if damage == "source_body_hash_alias":
            identity = "fixture:source-body-byte-identical-alias"
            case["adjudication"]["evidence_artifacts"][identity] = case["evidence_artifacts"][source["artifact_id"]]
        decisions = deepcopy(case["adjudication"]["declaration"]["decisions"])
        next(row for row in decisions if row["decision"] == "select_existing_variant")["evidence_refs"] = [
            {"artifact_id": identity, "sha256": source["raw_sha256"]}]
        record = owner._declaration(case["typed_assessment"], case["subject"], case["reviews"], decisions, DECLARED)
        install_declaration(case, record)
    record, blockers = content_pure(owner, case)
    assert record is None and blockers


@pytest.mark.parametrize("field", ["schema", "action", "audience"])
def test_pure_original_norm_claim_domain_cannot_authorize_adjudication(owner, case, field):
    case["adjudication"]["reviews"][0][field] = getattr(norm, "CLAIM_SCHEMA" if field == "schema" else field.upper())
    resign_adjudication(case)
    with pytest.raises(ValueError):
        assess_pure(owner, case)


@pytest.mark.parametrize("field", ["action", "audience"])
def test_pure_original_norm_policy_cannot_authorize_adjudication(owner, case, field):
    case["adjudication"]["policy"][field] = getattr(norm, field.upper())
    resign_adjudication(case)
    with pytest.raises(ValueError):
        assess_pure(owner, case)


@pytest.mark.parametrize("damage,blocker", [
    ("signature", "signature_invalid"), ("role", "unauthorized_review_role"),
    ("expiry", "review_not_current"), ("revoked_key", "key_revoked"), ("subject", "signed_subject_differs"),
])
def test_pure_real_shared_authentication_rejects_invalid_authority_without_hiding_raw_blockers(owner, case, damage, blocker):
    adjudication = case["adjudication"]
    if damage == "signature": adjudication["reviews"][0]["interpretation"]["rationale"] += " unsigned edit"
    else:
        if damage == "role": adjudication["registry"]["keys"][0]["roles"] = ["formal_review"]
        elif damage == "expiry": adjudication["reviews"][0]["expires_at_utc"] = EVALUATED
        elif damage == "revoked_key": adjudication["registry"]["keys"][0]["revoked_at_utc"] = EVALUATED
        else: adjudication["reviews"][0]["subject"]["native_ast_sha256"] = "0" * 64
        resign_adjudication(case)
    report = assess_pure(owner, case)
    assert blocker in report["raw_adjudication_authority_assessment"]["reviews"][0]["blockers"]
    assert report["common_body_authenticated_under_selected_trust"] is False
    assert report["adjudication_prerequisites_satisfied_under_selected_trust"] is False
    assert_unapplied(report)


@pytest.mark.parametrize("reuse", ["principal", "did", "public_key"])
def test_pure_real_signatures_cannot_hide_reuse_of_a_source_actor_under_adjudication_labels(owner, case, reuse):
    from cryptography.hazmat.primitives import serialization
    from ipfs_datasets_py.logic.profile_g import Ed25519Signer

    adjudication = case["adjudication"]
    key = adjudication["registry"]["keys"][0]
    source_key = case["registry"]["keys"][0]
    if reuse == "principal":
        key["principal_id"] = source_key["principal_id"]
        adjudication["reviews"][0]["principal_id"] = source_key["principal_id"]
    elif reuse == "did":
        signer = Ed25519Signer.generate(source_key["signer_did"])
        adjudication["signers"][0] = signer
        key.update(signer_did=signer.did, public_key_hex=signer.public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex())
    else:
        adjudication["signers"][0] = Ed25519Signer(key["signer_did"], case["signers"][0].private_key)
        key["public_key_hex"] = source_key["public_key_hex"]
    resign_adjudication(case)
    report = assess_pure(owner, case)
    assert report["raw_adjudication_authority_assessment"]["authenticated_evidence_count"] == 2
    assert report["common_body_authenticated_under_selected_trust"] is True
    assert report["current_source_prerequisites_satisfied"] is True
    assert report["adjudication_prerequisites_satisfied_under_selected_trust"] is False
    assert report["separation_and_chronology_blockers"]
    assert_unapplied(report)


def test_pure_actor_inventory_keeps_claimed_and_registered_identities_from_an_outlier_claim(owner, case):
    outlier = deepcopy(case["reviews"][0])
    outlier.update(review_id="fixture:rejected-source-outlier", principal_id="fixture:claimed-outlier-principal",
                   signer_did="did:example:claimed-outlier")
    # The mismatched claim is deliberately not authenticated here. This pure
    # inventory boundary must retain both its claim and its known key's actor.
    reviews = [*case["reviews"], outlier]
    inventory = owner._source_exclusions(case["registry"], reviews)
    registered = case["registry"]["keys"][0]
    assert len(inventory["actors"]) == 3
    assert {outlier["principal_id"], registered["principal_id"]} <= set(inventory["excluded_principal_ids"])
    assert {outlier["signer_did"], registered["signer_did"]} <= set(inventory["excluded_signer_dids"])
    assert registered["public_key_hex"] in inventory["excluded_public_keys"]
    assert inventory["actors"][-1]["claimed_principal_id"] == outlier["principal_id"]
    assert inventory["actors"][-1]["registered_principal_id"] == registered["principal_id"]


def test_pure_unknown_source_key_blocks_complete_inventory_over_genuinely_replayed_source_reports(owner, fixtures, source_base):
    from ipfs_datasets_py.logic.profile_g import Ed25519Signer

    source = clone_source(source_base)
    signer = Ed25519Signer.generate("did:example:unregistered-source-outlier")
    claim = deepcopy(source["reviews"][0])
    claim.update(review_id="fixture:unknown-source-key-review", key_id="fixture:unregistered-source-key",
                 principal_id="fixture:unregistered-source-principal")
    body = fixtures["content"].current_record(source)
    body.update(review_id=claim["review_id"], principal_id=claim["principal_id"])
    raw = wire(body)
    artifact_id = "fixture:unregistered-source-response-body"
    source["evidence_artifacts"][artifact_id] = raw
    source["response_bindings"].append({"review_id": claim["review_id"], "artifact_id": artifact_id, "raw_sha256": sha(raw)})
    for obligation in claim["context_closure"]["obligations"]:
        obligation["evidence_refs"] = [{"artifact_id": artifact_id, "sha256": sha(raw)}]
    unsigned = {key: value for key, value in claim.items() if key not in {"signer_did", "signature_alg", "signature"}}
    source["reviews"].append(signer.sign(unsigned))
    source["signers"].append(signer)
    refresh_source_reports(fixtures, source)
    assert len(source["reviews"]) == 3
    assert source["typed_assessment"]["raw_norm_assessment"]["authenticated_evidence_count"] == 2
    case = signed_case(owner, source)
    report = assess_pure(owner, case)
    assert report["source_reviewer_exclusions"]["unknown_key_review_ids"] == [claim["review_id"]]
    assert len(report["source_reviewer_exclusions"]["actors"]) == 3
    assert "source_cohort_public_key_inventory_incomplete" in report["current_source_blockers"]
    assert "source_cohort_public_key_inventory_incomplete" in report["separation_and_chronology_blockers"]
    assert report["current_source_prerequisites_satisfied"] is False
    assert report["adjudication_prerequisites_satisfied_under_selected_trust"] is False
    assert_unapplied(report)


@pytest.mark.parametrize("alias", ["did", "public_key"])
def test_pure_shared_trust_registry_refuses_aliasing_the_two_adjudicator_keys(owner, case, alias):
    keys = case["adjudication"]["registry"]["keys"]
    field = "signer_did" if alias == "did" else "public_key_hex"
    keys[1][field] = keys[0][field]
    resign_adjudication(case)
    with pytest.raises(ValueError, match="duplicate review key identity"):
        assess_pure(owner, case)


def test_pure_synthetic_trust_cannot_satisfy_partial_production_custody(owner, case):
    case["adjudication"]["registry"]["mode"] = case["adjudication"]["policy"]["mode"] = "synthetic_fixture"
    resign_adjudication(case)
    report = assess_pure(owner, case)
    assert report["raw_adjudication_authority_assessment"]["authenticated_evidence_count"] == 2
    assert "production_trust_registry_unavailable" in report["raw_adjudication_authority_assessment"]["blockers"]
    assert "adjudication_production_trust_unavailable" in report["separation_and_chronology_blockers"]
    assert report["adjudication_prerequisites_satisfied_under_selected_trust"] is False
    assert_unapplied(report)


@pytest.mark.parametrize("event,blocker", [
    ("claim_before_body", "authority_claim_predates_common_declaration"),
    ("body_after_evaluation", "common_declaration_postdates_evaluation"),
])
def test_pure_valid_signatures_cannot_override_declaration_chronology(owner, case, event, blocker):
    if event == "claim_before_body":
        case["adjudication"]["reviews"][0]["issued_at_utc"] = "2026-10-15T12:00:30Z"
        resign_adjudication(case)
    else:
        record = owner._declaration(case["typed_assessment"], case["subject"], case["reviews"],
                                    choices(case), "2026-10-15T12:04:00Z")
        install_declaration(case, record)
    report = assess_pure(owner, case)
    assert report["raw_adjudication_authority_assessment"]["authenticated_evidence_count"] == 2
    assert blocker in report["separation_and_chronology_blockers"]
    assert report["adjudication_prerequisites_satisfied_under_selected_trust"] is False
    assert_unapplied(report)


def test_pure_declaration_cannot_precede_the_considered_source_assessment(owner, case):
    with pytest.raises(ValueError, match="predates"):
        owner._declaration(case["typed_assessment"], case["subject"], case["reviews"],
                           choices(case), "2026-10-15T11:59:59Z")


@pytest.mark.parametrize("damage", ["extra_field", "missing_field"])
def test_closed_original_response_inputs_refuse_before_any_source_replay(owner, case, monkeypatch, damage):
    if damage == "extra_field": case["response_inputs"]["binding_inputs"] = None
    else: case["response_inputs"].pop("expected_response_bindings_sha256")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("source replay")
        raise AssertionError("malformed response inputs reached source replay")

    monkeypatch.setattr(content, "validate_norm_content_assessment_v1", forbidden)
    with pytest.raises(ValueError):
        assess(owner, case)
    assert calls == []


def test_final_template_serialization_fences_original_source_inputs(owner, case, monkeypatch):
    serialize = norm._wire
    reached = []

    def mutating(value):
        raw = serialize(value)
        if type(value) is dict and value.get("schema") == owner.TEMPLATE_SCHEMA:
            reached.append("template serialized")
            case["response_inputs"]["correspondence_inputs"]["scope_replay_inputs"]["expected_raw_bytes"] += 1
        return raw

    monkeypatch.setattr(norm, "_wire", mutating)
    with pytest.raises(ValueError, match="changed"):
        owner.build_norm_content_adjudication_template_v1(*source_arguments(case), **declaration_arguments(case))
    assert reached == ["template serialized"]


@pytest.mark.parametrize("module_name", ["adjudication", "content"])
def test_live_owner_source_drift_refuses_before_replay_without_writing_source_files(owner, case, monkeypatch, module_name):
    module = owner if module_name == "adjudication" else content
    selected = Path(module.__file__).resolve()
    read_bytes = Path.read_bytes
    original = read_bytes(selected)

    def observed(path):
        return original + b"\n# Fictional observed drift; source bytes are not written.\n" \
            if path.resolve() == selected else read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", observed)
    with pytest.raises(ValueError, match="changed"):
        owner.build_norm_content_adjudication_template_v1(*source_arguments(case), **declaration_arguments(case))


def test_pure_unresolved_signing_bound_refuses_instead_of_discarding_obligations(owner, case, monkeypatch):
    monkeypatch.setattr(owner, "MAX_UNRESOLVED", 1)
    with pytest.raises(ValueError, match="bound"):
        owner._declaration(case["typed_assessment"], case["subject"], case["reviews"], choices(case), DECLARED)


def test_public_rehashed_report_cannot_apply_choices_or_close_definition_context(owner, case):
    report = assess(owner, case)
    forged = deepcopy(report)
    forged["closed_context_prerequisites_satisfied"] = True
    forged["counts"]["decisions_applied"] = 1
    forged["pending_slots"][0]["decision_applied"] = True
    with pytest.raises(ValueError, match="regeneration"):
        owner.validate_norm_content_adjudication_v1(
            forged, *source_arguments(case), *authority_arguments(case),
            expected_report_sha256=owner.norm_content_adjudication_sha256(forged),
            **declaration_arguments(case), **adjudication_arguments(case))
    assert_unapplied(report)


def test_public_rehashed_incomplete_typed_population_cannot_drop_a_pending_question(owner, case):
    case["typed_assessment"]["pending_questions"].pop()
    # declaration_arguments deliberately supplies the altered report's fresh
    # complete digest. Source replay must still reject that changed denominator.
    with pytest.raises(ValueError, match="exact full replay"):
        assess(owner, case)


# Reviewed-admission V2: this entire miniature Act, its source actors, signing
# credentials and review process are fictional engineering fixtures. A positive
# semantic-use result below is never a reviewed United States statutory record.
REVIEWED_START = "2026-10-01T00:00:00Z"
REVIEWED_END = "2026-11-01T00:00:00Z"
REVIEWED_PROCESS_ID = "fixture:reviewed-process-evidence"


def reviewed_prepare_arguments_v2(case):
    """Exact public preparation replay shared with the owning consumer tests."""
    return {"expected_declaration_sha256": norm.norm_review_sha256(case["declaration"]),
        "source_inputs": case["source_inputs"], "relational_inputs": case["relational_inputs"],
        "dependency_manifest": case["manifest"],
        "expected_manifest_sha256": case["manifest"]["manifest_sha256"]}


def reviewed_assessment_arguments_v2(owner, case):
    return (case["preparation"], case["registry"], case["policy"], case["reviews"]), {
        "expected_preparation_sha256": norm.norm_review_sha256(case["preparation"]),
        "preparation_inputs": {"declaration": case["declaration"], **reviewed_prepare_arguments_v2(case)},
        "expected_registry_sha256": auth.digest(case["registry"]),
        "expected_policy_sha256": auth.digest(case["policy"]),
        "expected_reviews_sha256": auth.digest(case["reviews"]), "at_time_utc": EVALUATED,
        "observed_artifact_sha256s": case["observed_artifacts"],
        "observed_pins": case["observed_pins"], "evidence_artifacts": case["evidence"]}


def reviewed_resign_v2(case):
    """Re-sign explicit fixture edits; this does not choose a legal meaning."""
    case["policy"]["registry_sha256"] = auth.digest(case["registry"])
    for index, claim in enumerate(case["reviews"]):
        body = {key: deepcopy(value) for key, value in claim.items()
                if key not in {"signer_did", "signature_alg", "signature"}}
        body["registry_sha256"] = auth.digest(case["registry"])
        body["policy_sha256"] = auth.digest(case["policy"])
        case["reviews"][index] = case["signers"][index].sign(body)


def reviewed_norm_fixture_v2(owner):
    """One fictional definition and two distinct complete normative provisions.

    This public test helper deliberately exercises the existing source,
    TypedExpression, dependency and detached-signature owners. It is reusable
    by the consumer's owning tests; no retained runtime artifact is imported.
    """
    from cryptography.hazmat.primitives import serialization
    from ipfs_datasets_py.logic.profile_g import Ed25519Signer
    from ipfs_datasets_py.logic.autoformal import corpus_source as source_owner
    from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as deps
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational

    helper = load_fixture("_reviewed_admission_relational_fixture", "test_legal_relational_norm_v1.py")
    builder = helper.Builder()
    definition_request = helper.request_for(builder,
        builder.binary("iff", builder.atom("CoveredOfficer", "officer"),
                       builder.atom("AppointedByBoard", "officer")),
        [("CoveredOfficer", ("officer",)), ("AppointedByBoard", ("officer",))],
        [("officer", "forall")])
    builder = helper.Builder()
    duty_request = helper.request_for(builder,
        builder.binary("implies", builder.atom("CoveredOfficer", "officer"),
            builder.binary("implies", helper.ast.mk_not(builder.nid(), builder.atom("Excused", "officer")),
                builder.modal("O", builder.atom("FilesReport", "officer")))),
        [("CoveredOfficer", ("officer",)), ("Excused", ("officer",)), ("FilesReport", ("officer",))],
        [("officer", "forall")])
    builder = helper.Builder()
    permission_request = helper.request_for(builder,
        builder.binary("implies", builder.atom("CoveredOfficer", "officer"),
                       builder.modal("P", builder.atom("InspectsRegister", "officer"))),
        [("CoveredOfficer", ("officer",)), ("InspectsRegister", ("officer",))],
        [("officer", "forall")])
    texts = [
        "For this fictional Act, a covered officer means an officer appointed by the Board. Café.",
        "Every covered officer must file a report unless the Board expressly excuses that officer.",
        "A covered officer may inspect the register.",
    ]
    requests = [definition_request, duty_request, permission_request]
    source_inputs, relational_inputs, units = {}, {}, []
    for index, (text, request) in enumerate(zip(texts, requests)):
        unit_id = "fixture:act-v1/unit-" + str(index + 1)
        raw = text.encode("utf-8")
        version = source_owner.build_source_version(source_id=unit_id, release_id="fixture:act-v1",
            edition="fictional-edition-1", provision_id=unit_id, raw_bytes=raw,
            expected_raw_sha256=sha(raw), extracted_text=text, expected_extracted_sha256=sha(raw),
            extraction_profile="identity/v1", normalization_profile="identity/v1", media_type="text/plain")
        occurrence = source_owner.build_source_occurrence(version, expected_raw_sha256=sha(raw),
            extracted_text=text, expected_extracted_sha256=sha(raw), start_char=0, end_char=len(text),
            start_utf8=0, end_utf8=len(raw))
        request_raw = wire(request)
        report = relational.prepare_relational_norm_v1(request_raw, expected_request_sha256=sha(request_raw))
        source_inputs[unit_id] = {"raw_bytes": raw, "extracted_text": text}
        relational_inputs[unit_id] = {"request_raw": request_raw, "report": report,
            "expected_report_sha256": relational.relational_norm_report_sha256(report)}
        units.append({"unit_id": unit_id, "kind": "definition" if index == 0 else "norm",
            "source_version": version, "occurrence": occurrence, "document_revision": "fixture:act-v1/revision-1",
            "parent_unit_ids": [], "relational_request_sha256": sha(request_raw),
            "source_artifact_id": unit_id + ":source", "ir_artifact_id": unit_id + ":ir",
            "coverage": [{"typed_path": row["typed_path"], "start_char": 0, "end_char": len(text),
                "start_utf8": 0, "end_utf8": len(raw)} for row in report["structural_mapping"]]})
    process_raw = b"Fictional independent review process record. No actual statutory or human-review claim."
    process_ref = {"artifact_id": REVIEWED_PROCESS_ID, "sha256": sha(process_raw)}
    definition_uses = []
    for unit in units[1:]:
        report = relational_inputs[unit["unit_id"]]["report"]
        paths = []
        for mapping in report["structural_mapping"]:
            if mapping["kind"] != "predicate":
                continue
            node = report["typed_expression"]
            for token in mapping["typed_path"].split("/")[1:]:
                node = node[int(token)] if type(node) is list else node[token]
            if node["symbol"] == "CoveredOfficer":
                paths.append(mapping["typed_path"])
        definition_uses.append({"definition_unit_id": units[0]["unit_id"],
            "use_unit_id": unit["unit_id"], "use_occurrence_cid": unit["occurrence"]["record_cid"],
            "target_typed_paths": paths, "defined_predicate": "CoveredOfficer", "applicability": "governing",
            "interpretation_id": "fixture:act-v1/selected-interpretation", "evidence_refs": [deepcopy(process_ref)]})
    source_signer = Ed25519Signer.generate("did:example:fictional-source-author")
    declaration = {"schema": "legal-reviewed-norm-declaration/v2", "component_id": "fixture:reviewed-act-v1",
        "provenance_kind": "fictional_fixture", "interpretation_id": "fixture:act-v1/selected-interpretation",
        "governing_context": {"jurisdiction": "fictional-jurisdiction", "instrument_id": "fixture:act-v1",
            "governing_edition": "fictional-edition-1", "legal_as_of_utc": EVALUATED,
            "valid_from_utc": REVIEWED_START, "valid_until_utc": REVIEWED_END},
        "units": units, "definition_uses": definition_uses, "cross_references": [],
        "permitted_uses": ["formalization", "training", "heldout_evaluation", "proof_obligation"],
        "unresolved": [], "unsupported": [], "assumptions": [],
        "source_actors": [{"principal_id": "fixture:source-author", "signer_did": source_signer.did,
            "public_key_hex": source_signer.public_key.public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()}], "declared_at_utc": DECLARED}
    artifacts = [{"artifact_id": declaration["component_id"],
        "artifact_sha256": norm.norm_review_sha256(declaration),
        "dependency_pins": {kind: [] for kind in deps.PIN_KINDS}}]
    for unit in units:
        for artifact_id, digest in ((unit["source_artifact_id"], norm.norm_review_sha256(unit["source_version"])),
                                    (unit["ir_artifact_id"], unit["relational_request_sha256"])):
            artifacts.append({"artifact_id": artifact_id, "artifact_sha256": digest,
                              "dependency_pins": {kind: [] for kind in deps.PIN_KINDS}})
    manifest = deps.build_dependency_manifest(artifacts,
        [{"dependent_id": declaration["component_id"], "dependency_id": row["artifact_id"]}
         for row in artifacts[1:]], expected_artifact_ids=[row["artifact_id"] for row in artifacts])
    case = {"declaration": declaration, "source_inputs": source_inputs, "relational_inputs": relational_inputs,
        "manifest": manifest, "observed_artifacts": {row["artifact_id"]: row["artifact_sha256"] for row in artifacts},
        "observed_pins": {kind: {} for kind in deps.PIN_KINDS}}
    preparation = owner.prepare_reviewed_norm_admission_v2(declaration, **reviewed_prepare_arguments_v2(case))
    case["preparation"] = preparation
    subject = preparation["subject"]
    signers = [Ed25519Signer.generate("did:example:reviewed-norm-" + role) for role in auth.ROLES]
    keys = [{"key_id": "fixture:reviewed-key:" + str(index), "signer_did": signer.did,
        "public_key_hex": signer.public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex(),
        "principal_id": "fixture:reviewed-principal:" + str(index), "roles": [role],
        "scope_ids": [subject["scope_id"]], "valid_from_utc": REVIEWED_START,
        "valid_until_utc": REVIEWED_END, "revoked_at_utc": None}
        for index, (signer, role) in enumerate(zip(signers, auth.ROLES))]
    registry = {"schema": auth.REGISTRY_SCHEMA, "mode": "external_pinned_trust",
        "process_id": "fixture:reviewed-process", "generation": 1, "revocation_generation": 0,
        "valid_from_utc": REVIEWED_START, "valid_until_utc": REVIEWED_END,
        "keys": keys, "revoked_principals": []}
    policy = {"schema": auth.POLICY_SCHEMA, "mode": registry["mode"], "policy_id": "fixture:reviewed-policy",
        "process_id": registry["process_id"], "registry_sha256": auth.digest(registry),
        "action": owner.REVIEWED_ACTION, "audience": owner.REVIEWED_AUDIENCE,
        "required_roles": list(auth.ROLES), "valid_from_utc": REVIEWED_START,
        "valid_until_utc": REVIEWED_END, "max_review_age_seconds": 86400}
    declaration_raw = norm._wire(declaration)
    body_ref = {"artifact_id": declaration["component_id"], "sha256": sha(declaration_raw)}
    closure = {"status": "declared_complete", "obligations": [{"slot_id": slot,
        "disposition": "resolved_by_evidence", "evidence_refs": [deepcopy(body_ref), deepcopy(process_ref)]}
        for slot in subject["context_slot_ids"]], "unresolved": []}
    reviews = [signer.sign({"schema": owner.REVIEWED_CLAIM_SCHEMA, "action": owner.REVIEWED_ACTION,
        "audience": owner.REVIEWED_AUDIENCE, "review_id": "fixture:reviewed-review:" + str(index),
        "key_id": keys[index]["key_id"], "principal_id": keys[index]["principal_id"], "role": role,
        "registry_sha256": auth.digest(registry), "policy_sha256": auth.digest(policy),
        "issued_at_utc": SIGNED, "expires_at_utc": EXPIRES, "subject": deepcopy(subject),
        "interpretation": {"decision": "support", "reviewed_graph_sha256": subject["graph_sha256"],
            "reviewed_ast_sha256": subject["ast_sha256"], "rationale": "Entirely fictional reviewed-meaning fixture.",
            "ambiguity": []}, "context_closure": deepcopy(closure)})
        for index, (signer, role) in enumerate(zip(signers, auth.ROLES))]
    case.update(registry=registry, policy=policy, reviews=reviews, signers=signers,
                evidence={declaration["component_id"]: declaration_raw, REVIEWED_PROCESS_ID: process_raw})
    return case


@pytest.fixture
def reviewed_case_v2(owner):
    return reviewed_norm_fixture_v2(owner)


def assess_reviewed_fixture_v2(owner, case, **overrides):
    args, inputs = reviewed_assessment_arguments_v2(owner, case)
    return owner.assess_reviewed_norm_admission_v2(*args, **dict(inputs, **overrides))


def test_reviewed_v2_complete_fictional_transition_uses_full_sources_and_typed_ir(owner, reviewed_case_v2):
    case = reviewed_case_v2
    before = norm._snapshot({key: value for key, value in case.items() if key != "signers"})[1]
    report = assess_reviewed_fixture_v2(owner, case)
    assert report["semantic_use_eligible"] is True
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert report["Lean_admitted"] is False
    args, inputs = reviewed_assessment_arguments_v2(owner, case)
    replayed = owner.validate_reviewed_norm_admission_v2(report, *args,
        expected_report_sha256=norm.norm_review_sha256(report), **inputs)
    assert replayed == report
    assert before == norm._snapshot({key: value for key, value in case.items() if key != "signers"})[1]
    declaration = case["declaration"]
    assert declaration["provenance_kind"] == "fictional_fixture"
    assert len(declaration["definition_uses"]) == 2
    assert len({use["use_occurrence_cid"] for use in declaration["definition_uses"]}) == 2
    assert len({use["use_unit_id"] for use in declaration["definition_uses"]}) == 2
    assert all(case["relational_inputs"][unit["unit_id"]]["report"]["typed_expression"]
               for unit in declaration["units"])


@pytest.mark.parametrize("damage", ["source_bytes", "source_text", "source_revision", "geometry", "governing_edition",
    "legal_as_of", "interpretation", "coverage", "definition_missing", "definition_duplicate_use",
    "definition_wrong_occurrence", "definition_wrong_path", "unresolved", "unsupported", "IR_request", "IR_report",
    "dependency_source", "dependency_root", "unknown_unit", "permission", "provenance",
    "assumptions", "definition_binder", "definition_root", "definition_unrelated_symbol"])
def test_reviewed_v2_rejects_incomplete_or_changed_preparation(owner, reviewed_case_v2, damage):
    case = reviewed_case_v2
    declaration = case["declaration"]
    unit = declaration["units"][0]
    unit_id = unit["unit_id"]
    if damage == "source_bytes": case["source_inputs"][unit_id]["raw_bytes"] += b" changed"
    elif damage == "source_text": case["source_inputs"][unit_id]["extracted_text"] += " changed"
    elif damage == "source_revision": unit["document_revision"] += " changed"
    elif damage == "geometry": unit["coverage"][0]["end_utf8"] -= 1
    elif damage == "governing_edition": declaration["governing_context"]["governing_edition"] = None
    elif damage == "legal_as_of": declaration["governing_context"]["legal_as_of_utc"] = None
    elif damage == "interpretation": declaration["definition_uses"][0]["interpretation_id"] += " other"
    elif damage == "coverage": unit["coverage"].pop()
    elif damage == "definition_missing": declaration["definition_uses"].pop()
    elif damage == "definition_duplicate_use": declaration["definition_uses"][1] = deepcopy(declaration["definition_uses"][0])
    elif damage == "definition_wrong_occurrence": declaration["definition_uses"][0]["use_occurrence_cid"] = unit["occurrence"]["record_cid"]
    elif damage == "definition_wrong_path": declaration["definition_uses"][0]["target_typed_paths"] = ["/missing"]
    elif damage == "unresolved": declaration["unresolved"] = ["missing governing meaning"]
    elif damage == "unsupported": declaration["unsupported"] = ["unrepresented exception"]
    elif damage == "IR_request": case["relational_inputs"][unit_id]["request_raw"] += b" "
    elif damage == "IR_report": case["relational_inputs"][unit_id]["report"]["typed_expression"] = {}
    elif damage == "dependency_source": case["manifest"]["artifacts"][1]["artifact_sha256"] = "f" * 64
    elif damage == "dependency_root": case["manifest"]["artifacts"][0]["artifact_sha256"] = "f" * 64
    elif damage == "unknown_unit": case["source_inputs"]["fixture:unknown"] = deepcopy(case["source_inputs"][unit_id])
    elif damage == "permission": declaration["permitted_uses"] = ["implicit_all_uses"]
    elif damage == "provenance": declaration["provenance_kind"] = "verified_gold_fixture"
    elif damage == "assumptions": declaration["assumptions"] = ["An unrepresented premise supplied by the caller."]
    elif damage in {"definition_binder", "definition_root", "definition_unrelated_symbol"}:
        use = declaration["definition_uses"][0]
        report = case["relational_inputs"][use["use_unit_id"]]["report"]
        if damage == "definition_binder":
            use["target_typed_paths"] = [next(row["typed_path"] for row in report["structural_mapping"]
                                                   if row["kind"] == "binder")]
        elif damage == "definition_root":
            use["target_typed_paths"] = ["/root"]
        else:
            use["defined_predicate"] = "FilesReport"
        # Fresh transport pins keep this an intrinsic applicability check.
        reviewed_refresh_manifest_v2(case)
    with pytest.raises((ValueError, TypeError)):
        owner.prepare_reviewed_norm_admission_v2(declaration, **reviewed_prepare_arguments_v2(case))


@pytest.mark.parametrize("damage", ["signature", "wrong_domain", "revoked_key", "revoked_principal", "expired",
    "review_disagreement", "review_ambiguity", "missing_review", "same_principal", "source_reviewer",
    "body_changed", "process_changed", "process_missing", "body_only", "source_stale", "missing_dependency"])
def test_reviewed_v2_review_and_current_dependency_controls(owner, reviewed_case_v2, damage):
    case = reviewed_case_v2
    if damage == "signature": case["reviews"][0]["interpretation"]["rationale"] += " unsigned"
    else:
        if damage == "wrong_domain": case["reviews"][0]["action"] = owner.ACTION
        elif damage == "revoked_key": case["registry"]["keys"][0]["revoked_at_utc"] = EVALUATED
        elif damage == "revoked_principal": case["registry"]["revoked_principals"] = [
            {"principal_id": case["registry"]["keys"][0]["principal_id"], "revoked_at_utc": EVALUATED}]
        elif damage == "expired": case["reviews"][0]["expires_at_utc"] = EVALUATED
        elif damage == "review_disagreement": case["reviews"][1]["interpretation"]["decision"] = "reject"
        elif damage == "review_ambiguity": case["reviews"][1]["interpretation"]["ambiguity"] = ["unresolved exception scope"]
        elif damage == "missing_review": case["reviews"].pop()
        elif damage == "same_principal":
            principal = case["registry"]["keys"][0]["principal_id"]
            case["registry"]["keys"][1]["principal_id"] = principal
            case["reviews"][1]["principal_id"] = principal
        elif damage == "source_reviewer":
            principal = case["declaration"]["source_actors"][0]["principal_id"]
            case["registry"]["keys"][0]["principal_id"] = principal
            case["reviews"][0]["principal_id"] = principal
        elif damage == "body_changed": case["evidence"][case["declaration"]["component_id"]] += b" changed"
        elif damage == "process_changed": case["evidence"][REVIEWED_PROCESS_ID] += b" changed"
        elif damage == "process_missing": case["evidence"].pop(REVIEWED_PROCESS_ID)
        elif damage == "body_only":
            for claim in case["reviews"]:
                for obligation in claim["context_closure"]["obligations"]:
                    obligation["evidence_refs"] = obligation["evidence_refs"][:1]
        elif damage == "source_stale":
            identity = case["declaration"]["units"][0]["source_artifact_id"]
            case["observed_artifacts"][identity] = "f" * 64
        elif damage == "missing_dependency": case["observed_artifacts"].pop(next(iter(case["observed_artifacts"])))
        reviewed_resign_v2(case)
    try:
        report = assess_reviewed_fixture_v2(owner, case)
    except (ValueError, TypeError):
        return
    assert report["semantic_use_eligible"] is False
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0


def test_reviewed_v2_resealed_positive_report_requires_complete_public_replay(owner, reviewed_case_v2):
    case = reviewed_case_v2
    report = assess_reviewed_fixture_v2(owner, case)
    forged = deepcopy(report)
    forged["training_mask"] = 1
    args, inputs = reviewed_assessment_arguments_v2(owner, case)
    with pytest.raises(ValueError):
        owner.validate_reviewed_norm_admission_v2(forged, *args,
            expected_report_sha256=norm.norm_review_sha256(forged), **inputs)


def test_reviewed_v2_synthetic_trust_cannot_be_promoted_to_production_review(owner, reviewed_case_v2):
    case = reviewed_case_v2
    case["registry"]["mode"] = case["policy"]["mode"] = "synthetic_fixture"
    reviewed_resign_v2(case)
    report = assess_reviewed_fixture_v2(owner, case)
    assert report["semantic_use_eligible"] is False
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0


def reviewed_refresh_manifest_v2(case):
    """Rebuild fixture custody after edits so rejection tests reach their seam."""
    from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as deps
    declaration = case["declaration"]
    artifacts = [{"artifact_id": declaration["component_id"],
        "artifact_sha256": norm.norm_review_sha256(declaration),
        "dependency_pins": {kind: [] for kind in deps.PIN_KINDS}}]
    for unit in declaration["units"]:
        for identity, digest in ((unit["source_artifact_id"], norm.norm_review_sha256(unit["source_version"])),
                                  (unit["ir_artifact_id"], unit["relational_request_sha256"])):
            artifacts.append({"artifact_id": identity, "artifact_sha256": digest,
                              "dependency_pins": {kind: [] for kind in deps.PIN_KINDS}})
    for ref in declaration["cross_references"]:
        artifacts.append({"artifact_id": ref["dependency_artifact_id"],
            "artifact_sha256": ref["dependency_sha256"], "dependency_pins": {kind: [] for kind in deps.PIN_KINDS}})
    case["manifest"] = deps.build_dependency_manifest(artifacts,
        [{"dependent_id": declaration["component_id"], "dependency_id": row["artifact_id"]}
         for row in artifacts[1:]], expected_artifact_ids=[row["artifact_id"] for row in artifacts])
    case["observed_artifacts"] = {row["artifact_id"]: row["artifact_sha256"] for row in artifacts}


def test_reviewed_v2_relabeling_one_physical_paragraph_cannot_supply_two_statutory_uses(owner, reviewed_case_v2):
    from ipfs_datasets_py.logic.autoformal import corpus_source as sources
    case = reviewed_case_v2
    original, relabeled = case["declaration"]["units"][1:]
    source_input = deepcopy(case["source_inputs"][original["unit_id"]])
    raw, text = source_input["raw_bytes"], source_input["extracted_text"]
    # New metadata and a different IR create a different occurrence CID, but
    # the exact raw artifact/view/geometry remains the same physical paragraph.
    version = sources.build_source_version(source_id=relabeled["unit_id"], release_id="fixture:act-v1",
        edition="fictional-edition-1", provision_id=relabeled["unit_id"], raw_bytes=raw,
        expected_raw_sha256=sha(raw), extracted_text=text, expected_extracted_sha256=sha(raw),
        extraction_profile="identity/v1", normalization_profile="identity/v1", media_type="text/plain")
    occurrence = sources.build_source_occurrence(version, expected_raw_sha256=sha(raw), extracted_text=text,
        expected_extracted_sha256=sha(raw), start_char=0, end_char=len(text), start_utf8=0, end_utf8=len(raw))
    assert occurrence["record_cid"] != original["occurrence"]["record_cid"]
    relabeled["source_version"], relabeled["occurrence"] = version, occurrence
    case["source_inputs"][relabeled["unit_id"]] = source_input
    for row in relabeled["coverage"]:
        row.update(start_char=0, end_char=len(text), start_utf8=0, end_utf8=len(raw))
    case["declaration"]["definition_uses"][1]["use_occurrence_cid"] = occurrence["record_cid"]
    reviewed_refresh_manifest_v2(case)
    with pytest.raises(ValueError):
        owner.prepare_reviewed_norm_admission_v2(case["declaration"], **reviewed_prepare_arguments_v2(case))


@pytest.mark.parametrize("witness", ["source_record", "source_bytes", "IR_request", "IR_report"])
def test_reviewed_v2_source_or_ir_payload_cannot_replace_independent_process_evidence(owner, reviewed_case_v2, witness):
    case = reviewed_case_v2
    unit = case["declaration"]["units"][0]
    if witness == "source_record":
        identity, raw = unit["source_artifact_id"], norm._wire(unit["source_version"])
    elif witness == "source_bytes":
        identity, raw = "fixture:raw-source-alias", case["source_inputs"][unit["unit_id"]]["raw_bytes"]
    elif witness == "IR_request":
        identity, raw = unit["ir_artifact_id"], case["relational_inputs"][unit["unit_id"]]["request_raw"]
    else:
        identity, raw = "fixture:ir-report-alias", norm._wire(case["relational_inputs"][unit["unit_id"]]["report"])
    case["evidence"][identity] = raw
    ref = {"artifact_id": identity, "sha256": sha(raw)}
    for claim in case["reviews"]:
        for obligation in claim["context_closure"]["obligations"]:
            obligation["evidence_refs"] = [obligation["evidence_refs"][0], deepcopy(ref)]
    reviewed_resign_v2(case)
    report = assess_reviewed_fixture_v2(owner, case)
    assert report["semantic_use_eligible"] is False
