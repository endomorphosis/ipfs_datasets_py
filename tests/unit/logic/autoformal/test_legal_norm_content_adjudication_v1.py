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


def reviewed_norm_fixture_v2(owner, *, fixture_namespace="act-v1", source_texts=None,
        permitted_uses=None, predicate_prefix=None, document_revision=None,
        governing_instrument_id=None, definition_provision_id=None,
        cross_references=None, dependency_artifacts=None, source_bindings=None):
    """One fictional definition and two distinct complete normative provisions.

    This public test helper deliberately exercises the existing source,
    TypedExpression, dependency and detached-signature owners. It is reusable
    by the consumer's owning tests; no retained runtime artifact is imported.
    """
    # Explicit fictional fixture options enter BEFORE preparation, dependency
    # subjects, registry/policy digests and all original detached signatures.
    # Defaults retain the original fixture's permitted uses and predicates.
    if document_revision is not None:
        assert type(document_revision) is str and 0 < len(document_revision) <= 512
    if permitted_uses is not None:
        assert type(permitted_uses) is list and permitted_uses and len(set(permitted_uses)) == len(permitted_uses)
        assert all(type(use) is str and use in owner.REVIEWED_USES for use in permitted_uses)
    if predicate_prefix is not None:
        assert type(predicate_prefix) is str and 0 < len(predicate_prefix) <= 32
        assert predicate_prefix.isascii() and predicate_prefix.isalpha()
    if cross_references is not None:
        assert type(cross_references) is list and len(cross_references) <= 64
    if dependency_artifacts is not None:
        assert type(dependency_artifacts) is dict
        assert all(type(key) is str and type(value) is bytes and 0 < len(value) <= 1_000_000
                   for key, value in dependency_artifacts.items())
        assert {row["dependency_artifact_id"] for row in (cross_references or [])} == set(dependency_artifacts)
        assert all(row["dependency_sha256"] == sha(dependency_artifacts[row["dependency_artifact_id"]])
                   for row in cross_references)
    def predicate(name):
        return name if predicate_prefix is None else predicate_prefix + name
    instrument_id = "fixture:" + fixture_namespace
    component_id = "fixture:reviewed-" + fixture_namespace
    from cryptography.hazmat.primitives import serialization
    from ipfs_datasets_py.logic.profile_g import Ed25519Signer
    from ipfs_datasets_py.logic.autoformal import corpus_source as source_owner
    from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as deps
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational

    helper = load_fixture("_reviewed_admission_relational_fixture", "test_legal_relational_norm_v1.py")
    builder = helper.Builder()
    definition_request = helper.request_for(builder,
        builder.binary("iff", builder.atom(predicate("CoveredOfficer"), "officer"),
                       builder.atom(predicate("AppointedByBoard"), "officer")),
        [(predicate("CoveredOfficer"), ("officer",)), (predicate("AppointedByBoard"), ("officer",))],
        [("officer", "forall")])
    builder = helper.Builder()
    duty_request = helper.request_for(builder,
        builder.binary("implies", builder.atom(predicate("CoveredOfficer"), "officer"),
            builder.binary("implies", helper.ast.mk_not(builder.nid(), builder.atom(predicate("Excused"), "officer")),
                builder.modal("O", builder.atom(predicate("FilesReport"), "officer")))),
        [(predicate("CoveredOfficer"), ("officer",)), (predicate("Excused"), ("officer",)), (predicate("FilesReport"), ("officer",))],
        [("officer", "forall")])
    builder = helper.Builder()
    permission_request = helper.request_for(builder,
        builder.binary("implies", builder.atom(predicate("CoveredOfficer"), "officer"),
                       builder.modal("P", builder.atom(predicate("InspectsRegister"), "officer"))),
        [(predicate("CoveredOfficer"), ("officer",)), (predicate("InspectsRegister"), ("officer",))],
        [("officer", "forall")])
    texts = [
        "For this fictional Act, a covered officer means an officer appointed by the Board. Café.",
        "Every covered officer must file a report unless the Board expressly excuses that officer.",
        "A covered officer may inspect the register.",
    ]
    requests = [definition_request, duty_request, permission_request]
    if source_texts is not None:
        assert type(source_texts) in (list, tuple) and len(source_texts) == len(requests)
        texts = list(source_texts)
    if source_bindings is not None:
        assert type(source_bindings) is dict
        assert set(source_bindings) == {
            instrument_id + "/unit-" + str(index + 1) for index in range(len(requests))}
    source_inputs, relational_inputs, units = {}, {}, []
    for index, (text, request) in enumerate(zip(texts, requests)):
        unit_id = instrument_id + "/unit-" + str(index + 1)
        raw = text.encode("utf-8")
        provision_id = definition_provision_id if index == 0 and definition_provision_id is not None else unit_id
        version = source_owner.build_source_version(source_id=unit_id, release_id=instrument_id,
            edition="fictional-edition-1", provision_id=provision_id, raw_bytes=raw,
            expected_raw_sha256=sha(raw), extracted_text=text, expected_extracted_sha256=sha(raw),
            extraction_profile="identity/v1", normalization_profile="identity/v1", media_type="text/plain")
        occurrence = source_owner.build_source_occurrence(version, expected_raw_sha256=sha(raw),
            extracted_text=text, expected_extracted_sha256=sha(raw), start_char=0, end_char=len(text),
            start_utf8=0, end_utf8=len(raw))
        extracted_text = text
        if source_bindings is not None:
            selected = source_bindings[unit_id]
            assert type(selected) is dict and set(selected) == {
                "source_version", "occurrence", "raw_bytes", "extracted_text"}
            assert type(selected["raw_bytes"]) is bytes and type(selected["extracted_text"]) is str
            version, occurrence = deepcopy(selected["source_version"]), deepcopy(selected["occurrence"])
            raw, extracted_text = selected["raw_bytes"], selected["extracted_text"]
            source_owner.validate_source_version(version, expected_raw_sha256=sha(raw), raw_bytes=raw,
                extracted_text=extracted_text, expected_extracted_sha256=sha(extracted_text.encode("utf-8")))
            source_owner.validate_source_occurrence(occurrence, source_version=version,
                expected_raw_sha256=sha(raw), extracted_text=extracted_text,
                expected_extracted_sha256=sha(extracted_text.encode("utf-8")))
        request_raw = wire(request)
        report = relational.prepare_relational_norm_v1(request_raw, expected_request_sha256=sha(request_raw))
        source_inputs[unit_id] = {"raw_bytes": raw, "extracted_text": extracted_text}
        relational_inputs[unit_id] = {"request_raw": request_raw, "report": report,
            "expected_report_sha256": relational.relational_norm_report_sha256(report)}
        units.append({"unit_id": unit_id, "kind": "definition" if index == 0 else "norm",
            "source_version": version, "occurrence": occurrence, "document_revision": (instrument_id + "/revision-1"
                if document_revision is None else document_revision),
            "parent_unit_ids": [], "relational_request_sha256": sha(request_raw),
            "source_artifact_id": unit_id + ":source", "ir_artifact_id": unit_id + ":ir",
            "coverage": [{"typed_path": row["typed_path"],
                **{key: occurrence[key] for key in ("start_char", "end_char", "start_utf8", "end_utf8")}}
                for row in report["structural_mapping"]]})
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
            if node["symbol"] == predicate("CoveredOfficer"):
                paths.append(mapping["typed_path"])
        definition_uses.append({"definition_unit_id": units[0]["unit_id"],
            "use_unit_id": unit["unit_id"], "use_occurrence_cid": unit["occurrence"]["record_cid"],
            "target_typed_paths": paths, "defined_predicate": predicate("CoveredOfficer"), "applicability": "governing",
            "interpretation_id": instrument_id + "/selected-interpretation", "evidence_refs": [deepcopy(process_ref)]})
    source_signer = Ed25519Signer.generate("did:example:fictional-source-author")
    declaration = {"schema": "legal-reviewed-norm-declaration/v2", "component_id": component_id,
        "provenance_kind": "fictional_fixture", "interpretation_id": instrument_id + "/selected-interpretation",
        "governing_context": {"jurisdiction": "fictional-jurisdiction", "instrument_id": governing_instrument_id or instrument_id,
            "governing_edition": "fictional-edition-1", "legal_as_of_utc": EVALUATED,
            "valid_from_utc": REVIEWED_START, "valid_until_utc": REVIEWED_END},
        "units": units, "definition_uses": definition_uses,
        "cross_references": [] if cross_references is None else deepcopy(cross_references),
        "permitted_uses": (["formalization", "training", "heldout_evaluation", "proof_obligation"]
                           if permitted_uses is None else list(permitted_uses)),
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
    # Explicit fictional external dependencies are frozen BEFORE preparation
    # and detached review signatures. Existing defaults add no artifacts.
    for artifact_id, raw in (dependency_artifacts or {}).items():
        assert artifact_id not in {row["artifact_id"] for row in artifacts}
        artifacts.append({"artifact_id": artifact_id, "artifact_sha256": sha(raw),
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
                evidence={declaration["component_id"]: declaration_raw, REVIEWED_PROCESS_ID: process_raw,
                          **(dependency_artifacts or {})})
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
    # Several legal units may refer to the same exact physical artifact.
    # The graph manifest has one record per identity; the declaration retains
    # every distinct use. Conflicting bytes under one identity must refuse.
    by_identity = {}
    for artifact in artifacts:
        previous = by_identity.setdefault(artifact["artifact_id"], artifact)
        if previous != artifact:
            raise ValueError("conflicting fixture artifact identity")
    artifacts = list(by_identity.values())
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


# Complete candidate syntax uses a single explicitly fictional, unreviewed
# provision. It does not synthesize a three-unit review, signer or approval.
def complete_candidate_fixture_v1():
    from ipfs_datasets_py.logic.autoformal import corpus_source as sources
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational

    helper = load_fixture("_complete_candidate_relational_fixture", "test_legal_relational_norm_v1.py")
    builder = helper.Builder()
    request = helper.request_for(builder,
        builder.binary("implies", builder.atom("CoveredOfficer", "officer"),
            builder.modal("O", builder.atom("Assigns", "officer", "clerk"))),
        [("CoveredOfficer", ("officer",)), ("Assigns", ("officer", "clerk"))],
        [("officer", "forall"), ("clerk", "exists")])
    raw = wire(request)
    prepared = relational.prepare_relational_norm_v1(raw, expected_request_sha256=sha(raw))
    text = "For this fictional proposal, every covered officer must assign a clerk. Café."
    source_raw = text.encode("utf-8")
    version = sources.build_source_version(source_id="fixture:candidate-use", release_id="fixture:candidate-act",
        edition="fictional-candidate-edition", provision_id="fixture:candidate-use", raw_bytes=source_raw,
        expected_raw_sha256=sha(source_raw), extracted_text=text, expected_extracted_sha256=sha(source_raw),
        extraction_profile="identity/v1", normalization_profile="identity/v1", media_type="text/plain")
    occurrence = sources.build_source_occurrence(version, expected_raw_sha256=sha(source_raw),
        extracted_text=text, expected_extracted_sha256=sha(source_raw), start_char=0, end_char=len(text),
        start_utf8=0, end_utf8=len(source_raw))
    binding = {"source_version_cid": version["record_cid"], "occurrence_cid": occurrence["record_cid"],
        "document_revision": "fixture:candidate-revision-1"}
    context = {"jurisdiction": "fictional-candidate-jurisdiction", "instrument_id": "fixture:candidate-act",
        "governing_edition": "fictional-candidate-edition", "legal_as_of_utc": EVALUATED,
        "valid_from_utc": REVIEWED_START, "valid_until_utc": REVIEWED_END}
    return {"profile": prepared["profile"], "typed_expression": prepared["typed_expression"],
        "argument_roles": prepared["argument_roles"], "assumptions": [], "governing_context": context,
        "interpretation_id": "fixture:candidate-unreviewed", "source_binding": binding,
        "definition_uses": [], "cross_references": []}


@pytest.fixture
def complete_candidate_v1():
    return complete_candidate_fixture_v1()


def validate_complete_candidate_v1(owner, candidate, **overrides):
    return owner.validate_complete_norm_candidate_v1(candidate,
        **dict({"known_source_binding": deepcopy(candidate["source_binding"]),
                "known_governing_context": deepcopy(candidate["governing_context"])}, **overrides))


def test_candidate_v1_known_input_normalizer_needs_no_candidate_or_relational_preparation(owner, complete_candidate_v1, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational

    def forbidden(*args, **kwargs):
        raise AssertionError("known source facts must not invent a candidate or prepare a fragment")

    monkeypatch.setattr(relational, "prepare_relational_norm_v1", forbidden)
    binding, context = complete_candidate_v1["source_binding"], complete_candidate_v1["governing_context"]
    result = owner.validate_complete_norm_known_input_v1(known_source_binding=binding, known_governing_context=context)
    assert result == {"schema": owner.CANDIDATE_KNOWN_INPUT_SCHEMA,
        "source_binding": binding, "governing_context": context}
    result["source_binding"]["document_revision"] = "fixture:mutated-copy"
    assert binding["document_revision"] == "fixture:candidate-revision-1"


def test_candidate_v1_preserves_full_nine_fields_and_all_authority_stays_false(owner, complete_candidate_v1):
    original = deepcopy(complete_candidate_v1)
    result = validate_complete_candidate_v1(owner, complete_candidate_v1)
    assert result["schema"] == owner.CANDIDATE_SYNTAX_SCHEMA
    assert result["profile"] == owner.CANDIDATE_SYNTAX_PROFILE
    assert result["status"] == "candidate_syntax_validated_unreviewed"
    assert result["candidate"] == original
    assert len(result["candidate"]) == 9
    assert result["candidate_sha256"] == owner.norm_content_adjudication_sha256(original)
    assert result["known_source_binding_matches"] is result["known_governing_context_matches"] is True
    assert result["semantic_use_eligible"] is False
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    assert result["authority"] and all(value is False for value in result["authority"].values())
    result["authority"]["eligible_for_training"] = True
    result["candidate"]["argument_roles"][1]["roles"].reverse()
    assert complete_candidate_v1 == original
    fresh = validate_complete_candidate_v1(owner, complete_candidate_v1)
    assert fresh["authority"]["eligible_for_training"] is False
    assert fresh["candidate"] == original


def test_candidate_v1_does_not_replay_or_construct_admission_or_review(owner, complete_candidate_v1, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("candidate syntax cannot call legal review or admission")

    for name in ("prepare_reviewed_norm_admission_v2", "assess_reviewed_norm_admission_v2",
                 "validate_reviewed_norm_admission_v2", "_reviewed_body", "_reviewed_units"):
        monkeypatch.setattr(owner, name, forbidden)
    assert validate_complete_candidate_v1(owner, complete_candidate_v1)["semantic_use_eligible"] is False


def test_candidate_v1_preserves_untrusted_definition_and_versioned_reference_declarations(owner, complete_candidate_v1):
    candidate = complete_candidate_v1
    candidate["definition_uses"] = [{"definition_unit_id": "fixture:unreviewed-definition",
        "defined_predicate": "CoveredOfficer", "use_unit_id": "fixture:candidate-use",
        "use_occurrence_cid": candidate["source_binding"]["occurrence_cid"],
        "target_typed_paths": ["/root/arguments/0/arguments/0/arguments/0"], "applicability": "governing",
        "interpretation_id": candidate["interpretation_id"], "evidence_refs": []}]
    candidate["cross_references"] = [{"from_unit_id": "fixture:candidate-use",
        "dependency_artifact_id": "fixture:unreviewed-external-dependency", "dependency_sha256": "4" * 64,
        "version": "fictional-version-1", "evidence_refs": []}]
    result = validate_complete_candidate_v1(owner, candidate)
    assert result["candidate"]["definition_uses"] == candidate["definition_uses"]
    assert result["candidate"]["cross_references"] == candidate["cross_references"]
    assert result["authority"]["governing_definitions_verified"] is False
    assert result["authority"]["cross_reference_dependencies_verified"] is False
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0


@pytest.mark.parametrize("damage", ["source_extra", "source_missing", "source_cid", "occurrence_cid",
    "revision_blank", "context_extra", "context_missing", "jurisdiction_type", "as_of_outside", "interval_reversed"])
def test_candidate_v1_known_facts_require_complete_supported_shapes(owner, complete_candidate_v1, damage):
    binding, context = deepcopy(complete_candidate_v1["source_binding"]), deepcopy(complete_candidate_v1["governing_context"])
    if damage == "source_extra":
        binding["source_authenticity_verified"] = True
    elif damage == "source_missing":
        binding.pop("document_revision")
    elif damage == "source_cid":
        binding["source_version_cid"] = "not-a-CID"
    elif damage == "occurrence_cid":
        binding["occurrence_cid"] = None
    elif damage == "revision_blank":
        binding["document_revision"] = " "
    elif damage == "context_extra":
        context["reviewed"] = True
    elif damage == "context_missing":
        context.pop("governing_edition")
    elif damage == "jurisdiction_type":
        context["jurisdiction"] = True
    elif damage == "as_of_outside":
        context["legal_as_of_utc"] = REVIEWED_END
    else:
        context["valid_from_utc"], context["valid_until_utc"] = context["valid_until_utc"], context["valid_from_utc"]
    with pytest.raises(ValueError):
        owner.validate_complete_norm_known_input_v1(known_source_binding=binding, known_governing_context=context)


@pytest.mark.parametrize("field", ["profile", "typed_expression", "argument_roles", "assumptions",
    "governing_context", "interpretation_id", "source_binding", "definition_uses", "cross_references"])
def test_candidate_v1_rejects_each_omitted_full_target_field(owner, complete_candidate_v1, field):
    binding, context = deepcopy(complete_candidate_v1["source_binding"]), deepcopy(complete_candidate_v1["governing_context"])
    complete_candidate_v1.pop(field)
    with pytest.raises(ValueError, match="nine-field"):
        owner.validate_complete_norm_candidate_v1(complete_candidate_v1,
            known_source_binding=binding, known_governing_context=context)


@pytest.mark.parametrize("field", ["accepted", "review", "training_mask", "source_text"])
def test_candidate_v1_rejects_extra_approval_or_hidden_text_fields(owner, complete_candidate_v1, field):
    complete_candidate_v1[field] = True
    with pytest.raises(ValueError, match="nine-field"):
        validate_complete_candidate_v1(owner, complete_candidate_v1)


@pytest.mark.parametrize("group,field", [("source_binding", "source_version_cid"), ("source_binding", "occurrence_cid"),
    ("source_binding", "document_revision"), ("governing_context", "jurisdiction"),
    ("governing_context", "instrument_id"), ("governing_context", "governing_edition"),
    ("governing_context", "legal_as_of_utc"), ("governing_context", "valid_from_utc"),
    ("governing_context", "valid_until_utc")])
def test_candidate_v1_refuses_every_known_source_or_context_mismatch(owner, complete_candidate_v1, group, field):
    binding, context = deepcopy(complete_candidate_v1["source_binding"]), deepcopy(complete_candidate_v1["governing_context"])
    complete_candidate_v1[group][field] = "changed-candidate-value"
    with pytest.raises(ValueError, match="differs"):
        owner.validate_complete_norm_candidate_v1(complete_candidate_v1,
            known_source_binding=binding, known_governing_context=context)


@pytest.mark.parametrize("damage", ["profile", "nonempty_assumptions", "expression_metadata"])
def test_candidate_v1_reports_known_unsupported_profiles_without_omission(owner, complete_candidate_v1, damage):
    if damage == "profile":
        complete_candidate_v1["profile"] = "unsupported-full-norm-profile/v99"
    elif damage == "nonempty_assumptions":
        complete_candidate_v1["assumptions"] = ["fictional premise not supported by this profile"]
    else:
        complete_candidate_v1["typed_expression"]["metadata"] = {"unparsed_qualification": "fictional extra meaning"}
    original = deepcopy(complete_candidate_v1)
    with pytest.raises(owner.CompleteNormCandidateUnsupportedError):
        validate_complete_candidate_v1(owner, complete_candidate_v1)
    assert complete_candidate_v1 == original


@pytest.mark.parametrize("damage", ["missing_role", "duplicate_role", "repeated_label", "wrong_role_arity", "malformed_expression"])
def test_candidate_v1_reuses_strict_typed_and_ordered_role_checks(owner, complete_candidate_v1, damage):
    roles = complete_candidate_v1["argument_roles"]
    if damage == "missing_role":
        roles.pop()
    elif damage == "duplicate_role":
        roles[1] = deepcopy(roles[0])
    elif damage == "repeated_label":
        roles[1]["roles"] = ["officer", "officer"]
    elif damage == "wrong_role_arity":
        roles[1]["roles"] = ["officer"]
    else:
        complete_candidate_v1["typed_expression"]["root"]["arguments"] = []
    with pytest.raises(ValueError):
        validate_complete_candidate_v1(owner, complete_candidate_v1)


@pytest.mark.parametrize("damage", ["definition_extra", "same_unit", "unknown_predicate", "bad_path", "duplicate_path",
    "interpretation", "bad_occurrence", "bad_evidence", "cross_extra", "conflicting_dependency"])
def test_candidate_v1_refuses_malformed_dependency_declarations(owner, complete_candidate_v1, damage):
    candidate = complete_candidate_v1
    use = {"definition_unit_id": "fixture:unreviewed-definition", "defined_predicate": "CoveredOfficer",
        "use_unit_id": "fixture:candidate-use", "use_occurrence_cid": candidate["source_binding"]["occurrence_cid"],
        "target_typed_paths": ["/root/arguments/0"], "applicability": "governing",
        "interpretation_id": candidate["interpretation_id"], "evidence_refs": []}
    ref = {"from_unit_id": "fixture:candidate-use", "dependency_artifact_id": "fixture:external-dependency",
        "dependency_sha256": "4" * 64, "version": "fictional-v1", "evidence_refs": []}
    candidate["definition_uses"], candidate["cross_references"] = [use], [ref]
    if damage == "definition_extra":
        use["approved"] = True
    elif damage == "same_unit":
        use["definition_unit_id"] = use["use_unit_id"]
    elif damage == "unknown_predicate":
        use["defined_predicate"] = "OtherPredicate"
    elif damage == "bad_path":
        use["target_typed_paths"] = ["/root/arguments/00"]
    elif damage == "duplicate_path":
        use["target_typed_paths"] *= 2
    elif damage == "interpretation":
        use["interpretation_id"] = "fixture:another-interpretation"
    elif damage == "bad_occurrence":
        use["use_occurrence_cid"] = "not-a-CID"
    elif damage == "bad_evidence":
        use["evidence_refs"] = [{"artifact_id": "fixture:untrusted-evidence", "sha256": "4" * 64, "verified": True}]
    elif damage == "cross_extra":
        ref["reviewed"] = True
    else:
        candidate["cross_references"].append(dict(ref, from_unit_id="fixture:another-use", dependency_sha256="5" * 64))
    with pytest.raises(ValueError):
        validate_complete_candidate_v1(owner, candidate)


@pytest.mark.parametrize("damage", ["candidate", "known_binding", "known_context", "returned_expression", "returned_roles", "returned_authority"])
def test_candidate_v1_fences_input_mutations_and_relational_contract_drift(owner, complete_candidate_v1, monkeypatch, damage):
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational

    binding, context = deepcopy(complete_candidate_v1["source_binding"]), deepcopy(complete_candidate_v1["governing_context"])
    original = relational.prepare_relational_norm_v1

    def mutate(*args, **kwargs):
        report = original(*args, **kwargs)
        if damage == "candidate":
            complete_candidate_v1["argument_roles"][1]["roles"].reverse()
        elif damage == "known_binding":
            binding["document_revision"] = "fixture:changed-after-validation"
        elif damage == "known_context":
            context["governing_edition"] = "fictional-changed-after-validation"
        elif damage == "returned_expression":
            report["typed_expression"]["metadata"] = {"changed_after_validation": True}
        elif damage == "returned_roles":
            report["argument_roles"][1]["roles"].reverse()
        else:
            report["authority"]["admitted"] = True
        return report

    monkeypatch.setattr(relational, "prepare_relational_norm_v1", mutate)
    with pytest.raises(ValueError):
        owner.validate_complete_norm_candidate_v1(complete_candidate_v1,
            known_source_binding=binding, known_governing_context=context)


@pytest.mark.parametrize("damage", ["source_mutation", "output_expression", "output_authority"])
def test_candidate_v1_final_serialization_cannot_change_inputs_or_grant_authority(owner, complete_candidate_v1, monkeypatch, damage):
    original = norm._wire

    def mutate(value):
        if type(value) is dict and value.get("schema") == owner.CANDIDATE_SYNTAX_SCHEMA:
            if damage == "source_mutation":
                raw = original(value)
                complete_candidate_v1["source_binding"]["document_revision"] = "fixture:serialization-race"
                return raw
            value = deepcopy(value)
            if damage == "output_expression":
                value["candidate"]["interpretation_id"] = "fixture:changed-serialized-candidate"
            else:
                value["authority"]["eligible_for_training"] = True
        return original(value)

    monkeypatch.setattr(norm, "_wire", mutate)
    with pytest.raises(ValueError):
        validate_complete_candidate_v1(owner, complete_candidate_v1)


def candidate_path_declaration_v2(candidate, path):
    """Unreviewed external-use metadata, never a source correspondence proof."""
    candidate["definition_uses"] = [{"definition_unit_id": "fixture:unreviewed-definition",
        "defined_predicate": "CoveredOfficer", "use_unit_id": "fixture:candidate-use",
        "use_occurrence_cid": candidate["source_binding"]["occurrence_cid"],
        "target_typed_paths": [path], "applicability": "governing",
        "interpretation_id": candidate["interpretation_id"], "evidence_refs": []}]


@pytest.mark.parametrize("path", ["/root/5", "/root/arguments", "/root/extension/5",
    "/root/arguments/00", "/root/arguments/-1", "/root/unknown/0", "/root/extension",
    "/root/extension/children", "/root/children/0", "root/arguments/0", "/root/arguments/+1",
    "/root/arguments/١", "/root/arguments/0/", "/root/arguments//0", ""])
def test_candidate_v2_typed_path_grammar_rejects_malformed_token_order(owner, complete_candidate_v1, path):
    candidate_path_declaration_v2(complete_candidate_v1, path)
    with pytest.raises(ValueError):
        validate_complete_candidate_v1(owner, complete_candidate_v1)


@pytest.mark.parametrize("path", ["/root", "/root/arguments/0", "/root/binders/0",
    "/root/extension/children/0", "/root/arguments/0/extension/children/0/arguments/1",
    "/root/arguments/0/binders/0"])
def test_candidate_v2_typed_path_grammar_preserves_unreviewed_external_references(owner, complete_candidate_v1, path):
    candidate_path_declaration_v2(complete_candidate_v1, path)
    result = validate_complete_candidate_v1(owner, complete_candidate_v1)
    assert result["candidate"]["definition_uses"][0]["target_typed_paths"] == [path]
    # This finite grammar does not resolve an external use's AST or prove that
    # the path selects a predicate to which the declared definition applies.
    assert result["authority"]["governing_definitions_verified"] is False
    assert result["authority"]["source_correspondence_verified"] is False
    assert result["semantic_use_eligible"] is False


def caller_selection_fixture_v2():
    # A separate caller declaration, never derived by reading a target field.
    # This opaque identity has no reviewed meaning or interpretation policy.
    return {"schema": "caller-known-interpretation-selection/v1",
        "interpretation_id": "fixture:candidate-unreviewed", "selection_mode": "identifier_only"}


def validate_identifier_bound_candidate_v2(owner, candidate, *, selection=None):
    return owner.validate_complete_norm_candidate_v2(candidate,
        known_source_binding=deepcopy(candidate["source_binding"]),
        known_governing_context=deepcopy(candidate["governing_context"]),
        known_selection_context=caller_selection_fixture_v2() if selection is None else selection)


def test_candidate_v3_known_selection_normalizer_has_no_candidate_or_meaning_input(owner, complete_candidate_v1, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("known selection normalization must not invent or validate a target")

    monkeypatch.setattr(owner, "validate_complete_norm_candidate_v1", forbidden)
    selection = caller_selection_fixture_v2()
    result = owner.validate_complete_norm_known_input_v2(
        known_source_binding=complete_candidate_v1["source_binding"],
        known_governing_context=complete_candidate_v1["governing_context"], known_selection_context=selection)
    assert result == {"schema": owner.CANDIDATE_KNOWN_INPUT_SCHEMA_V2,
        "source_binding": complete_candidate_v1["source_binding"],
        "governing_context": complete_candidate_v1["governing_context"],
        "selection_context": selection, "semantic_selection_supported": False}
    result["selection_context"]["interpretation_id"] = "fixture:mutated-copy"
    assert selection["interpretation_id"] == "fixture:candidate-unreviewed"


def test_candidate_v3_identifier_equality_preserves_all_predicted_fields_and_no_authority(owner, complete_candidate_v1):
    before = deepcopy(complete_candidate_v1)
    result = validate_identifier_bound_candidate_v2(owner, complete_candidate_v1)
    assert result["schema"] == owner.CANDIDATE_SYNTAX_SCHEMA_V2
    assert result["profile"] == owner.CANDIDATE_SYNTAX_PROFILE_V2
    assert result["candidate"] == before
    assert len(result["candidate"]) == 9
    assert result["known_interpretation_identifier_matches"] is True
    assert result["selection_context"] == caller_selection_fixture_v2()
    assert result["semantic_selection_supported"] is False
    assert result["semantic_use_eligible"] is False
    assert all(value is False for value in result["authority"].values())
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    result["selection_context"]["interpretation_id"] = "fixture:changed-result-only"
    assert complete_candidate_v1 == before


def test_candidate_v3_same_opaque_id_is_not_a_meaning_or_role_equivalence_claim(owner, complete_candidate_v1):
    alternate = deepcopy(complete_candidate_v1)
    alternate["argument_roles"][1]["roles"].reverse()
    first = validate_identifier_bound_candidate_v2(owner, complete_candidate_v1)
    second = validate_identifier_bound_candidate_v2(owner, alternate)
    assert first["candidate"]["interpretation_id"] == second["candidate"]["interpretation_id"]
    assert first["candidate_sha256"] != second["candidate_sha256"]
    assert first["candidate"]["argument_roles"] != second["candidate"]["argument_roles"]
    assert first["semantic_selection_supported"] is second["semantic_selection_supported"] is False
    assert first["authority"]["legal_meaning_verified"] is second["authority"]["legal_meaning_verified"] is False


@pytest.mark.parametrize("damage", ["missing", "extra_target", "extra_meaning", "schema", "blank_id", "id_type", "mode_type"])
def test_candidate_v3_known_selection_is_a_closed_explicit_declaration(owner, complete_candidate_v1, damage):
    selection = caller_selection_fixture_v2()
    if damage == "missing":
        selection.pop("interpretation_id")
    elif damage == "extra_target":
        selection["reference_target"] = deepcopy(complete_candidate_v1)
    elif damage == "extra_meaning":
        selection["meaning_description"] = "Unprovided policy must not silently become supported."
    elif damage == "schema":
        selection["schema"] = "unprovided-interpretation-policy/v99"
    elif damage == "blank_id":
        selection["interpretation_id"] = ""
    elif damage == "id_type":
        selection["interpretation_id"] = True
    else:
        selection["selection_mode"] = None
    with pytest.raises(ValueError):
        owner.validate_complete_norm_known_input_v2(known_source_binding=complete_candidate_v1["source_binding"],
            known_governing_context=complete_candidate_v1["governing_context"], known_selection_context=selection)


@pytest.mark.parametrize("mode", ["meaning_policy", "all_interpretations", "meaning_resolved"])
def test_candidate_v3_meaning_resolving_policy_modes_are_explicitly_unsupported(owner, complete_candidate_v1, mode):
    selection = dict(caller_selection_fixture_v2(), selection_mode=mode)
    with pytest.raises(owner.CompleteNormCandidateUnsupportedError, match="policy is unsupported"):
        validate_identifier_bound_candidate_v2(owner, complete_candidate_v1, selection=selection)


@pytest.mark.parametrize("identity", ["fixture:another-choice", "fixture:only-the-target-declares-this", None])
def test_candidate_v3_changed_or_missing_predicted_identity_is_never_filled(owner, complete_candidate_v1, identity):
    complete_candidate_v1["interpretation_id"] = identity
    before = deepcopy(complete_candidate_v1)
    with pytest.raises(ValueError, match="identity differs"):
        validate_identifier_bound_candidate_v2(owner, complete_candidate_v1)
    assert complete_candidate_v1 == before


def test_candidate_v3_omitted_interpretation_field_is_not_completed_from_known_context(owner, complete_candidate_v1):
    complete_candidate_v1.pop("interpretation_id")
    before = deepcopy(complete_candidate_v1)
    with pytest.raises(ValueError, match="nine-field"):
        validate_identifier_bound_candidate_v2(owner, complete_candidate_v1)
    assert complete_candidate_v1 == before


def test_candidate_v3_definition_use_identity_must_match_the_explicit_choice(owner, complete_candidate_v1):
    candidate_path_declaration_v2(complete_candidate_v1, "/root/arguments/0")
    complete_candidate_v1["definition_uses"][0]["interpretation_id"] = "fixture:another-definition-choice"
    with pytest.raises(ValueError, match="interpretation"):
        validate_identifier_bound_candidate_v2(owner, complete_candidate_v1)


def test_candidate_v3_default_v1_remains_an_unreviewed_hypothesis_without_selection_input(owner, complete_candidate_v1):
    complete_candidate_v1["interpretation_id"] = "fixture:another-unreviewed-hypothesis"
    result = validate_complete_candidate_v1(owner, complete_candidate_v1)
    assert result["schema"] == owner.CANDIDATE_SYNTAX_SCHEMA
    assert result["candidate"]["interpretation_id"] == "fixture:another-unreviewed-hypothesis"
    assert "selection_context" not in result
    assert result["authority"]["interpretation_accepted"] is False


def test_candidate_v3_selection_mutation_during_relational_validation_is_refused(owner, complete_candidate_v1, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational

    selection = caller_selection_fixture_v2()
    original = relational.prepare_relational_norm_v1

    def mutate(*args, **kwargs):
        report = original(*args, **kwargs)
        selection["interpretation_id"] = "fixture:changed-during-validation"
        return report

    monkeypatch.setattr(relational, "prepare_relational_norm_v1", mutate)
    with pytest.raises(ValueError, match="inputs changed"):
        validate_identifier_bound_candidate_v2(owner, complete_candidate_v1, selection=selection)


@pytest.mark.parametrize("stage", ["known", "candidate"])
@pytest.mark.parametrize("damage", ["input_selection", "serialized_selection", "semantic_claim"])
def test_candidate_v3_selection_serialization_cannot_rewrite_facts_or_claim_meaning(owner, complete_candidate_v1, monkeypatch, stage, damage):
    selection = caller_selection_fixture_v2()
    original = norm._wire
    schema = owner.CANDIDATE_KNOWN_INPUT_SCHEMA_V2 if stage == "known" else owner.CANDIDATE_SYNTAX_SCHEMA_V2

    def mutate(value):
        if type(value) is dict and value.get("schema") == schema:
            if damage == "input_selection":
                raw = original(value)
                selection["interpretation_id"] = "fixture:changed-during-serialization"
                return raw
            value = deepcopy(value)
            if damage == "serialized_selection":
                value["selection_context"]["interpretation_id"] = "fixture:rewritten-output-selection"
            else:
                value["semantic_selection_supported"] = True
        return original(value)

    monkeypatch.setattr(norm, "_wire", mutate)
    with pytest.raises(ValueError):
        validate_identifier_bound_candidate_v2(owner, complete_candidate_v1, selection=selection)


@pytest.mark.parametrize("damage", ["authority", "training_mask", "extra_policy"])
def test_candidate_v3_delegated_syntax_cannot_supply_meaning_or_approval_fields(owner, complete_candidate_v1, monkeypatch, damage):
    original = owner.validate_complete_norm_candidate_v1

    def mutate(*args, **kwargs):
        report = original(*args, **kwargs)
        if damage == "authority":
            report["authority"]["interpretation_accepted"] = True
        elif damage == "training_mask":
            report["training_mask"] = 1
        else:
            report["meaning_policy_applied"] = True
        return report

    monkeypatch.setattr(owner, "validate_complete_norm_candidate_v1", mutate)
    with pytest.raises(ValueError):
        validate_identifier_bound_candidate_v2(owner, complete_candidate_v1)


@pytest.fixture
def mixed_candidate_v3():
    from tests.unit.logic.autoformal import test_legal_reviewed_norm_admission_v3 as mixed
    candidate = complete_candidate_fixture_v1()
    request = mixed.mixed_request()
    candidate.update(profile=request['profile'], typed_expression=request['expression'],
                     argument_roles=request['argument_roles'])
    # A syntax-only proposal: equality to a declared source binding cannot
    # establish that this different formula faithfully translates its text.
    known = dict(known_source_binding=deepcopy(candidate['source_binding']),
        known_governing_context=deepcopy(candidate['governing_context']),
        known_selection_context=caller_selection_fixture_v2())
    return candidate, known


def test_candidate_mixed_v3_delegates_genuine_many_sorted_lowering_without_authority(owner, mixed_candidate_v3, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
    candidate, known = mixed_candidate_v3; original = deepcopy(candidate)
    prepare = relational.prepare_mixed_relational_norm_v1; calls = []
    def observed(raw, **kwargs):
        request = json.loads(raw); calls.append(request)
        assert kwargs['expected_request_sha256'] == sha(raw)
        assert request['profile'] == relational.MIXED_PROFILE and request['source_binding'] is None
        return prepare(raw, **kwargs)
    monkeypatch.setattr(relational, 'prepare_mixed_relational_norm_v1', observed)
    result = owner.validate_complete_norm_candidate_v3(candidate, **known)
    assert len(calls) == 1
    assert result['schema'] == owner.CANDIDATE_SYNTAX_SCHEMA_V3
    assert result['profile'] == owner.CANDIDATE_SYNTAX_PROFILE_V3
    assert result['candidate'] == original and candidate == original
    assert result['candidate_sha256'] == owner.norm_content_adjudication_sha256(original)
    assert result['known_interpretation_identifier_matches'] is True
    assert result['semantic_selection_supported'] is result['semantic_use_eligible'] is False
    assert result['authority'] and all(value is False for value in result['authority'].values())
    assert result['training_mask'] == result['evaluation_gold_mask'] == 0
    result['candidate']['argument_roles'][1]['roles'].reverse()
    assert candidate == original


def test_candidate_mixed_v3_preserves_legacy_refusals(owner, mixed_candidate_v3):
    candidate, known = mixed_candidate_v3
    with pytest.raises(owner.CompleteNormCandidateUnsupportedError):
        owner.validate_complete_norm_candidate_v1(candidate, **{k: v for k, v in known.items() if k != 'known_selection_context'})
    with pytest.raises(owner.CompleteNormCandidateUnsupportedError):
        owner.validate_complete_norm_candidate_v2(candidate, **known)


def test_candidate_mixed_v3_retains_object_route_under_distinct_report_identity(owner, complete_candidate_v1):
    known = dict(known_source_binding=deepcopy(complete_candidate_v1['source_binding']),
        known_governing_context=deepcopy(complete_candidate_v1['governing_context']),
        known_selection_context=caller_selection_fixture_v2())
    old = owner.validate_complete_norm_candidate_v2(complete_candidate_v1, **known)
    new = owner.validate_complete_norm_candidate_v3(complete_candidate_v1, **known)
    assert old['schema'] != new['schema'] and old['profile'] != new['profile']
    assert {k: v for k, v in old.items() if k not in ('schema', 'profile')} == {k: v for k, v in new.items() if k not in ('schema', 'profile')}


@pytest.mark.parametrize('field', ['profile', 'typed_expression', 'argument_roles', 'assumptions',
    'governing_context', 'interpretation_id', 'source_binding', 'definition_uses', 'cross_references'])
def test_candidate_mixed_v3_requires_every_predicted_field(owner, mixed_candidate_v3, field):
    candidate, known = mixed_candidate_v3; candidate.pop(field)
    with pytest.raises(ValueError, match='nine-field'):
        owner.validate_complete_norm_candidate_v3(candidate, **known)


@pytest.mark.parametrize('which', ['source', 'context', 'selection'])
def test_candidate_mixed_v3_rejects_independent_fact_mismatches_before_lowering(owner, mixed_candidate_v3, monkeypatch, which):
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
    candidate, known = mixed_candidate_v3
    if which == 'source': known['known_source_binding']['document_revision'] = 'fixture:different-revision'
    elif which == 'context': known['known_governing_context']['governing_edition'] = 'fixture:different-edition'
    else: known['known_selection_context']['interpretation_id'] = 'fixture:different-selection'
    monkeypatch.setattr(relational, 'prepare_mixed_relational_norm_v1', lambda *_a, **_k: pytest.fail('mismatched facts reached lowering'))
    with pytest.raises(ValueError, match='differs'):
        owner.validate_complete_norm_candidate_v3(candidate, **known)


@pytest.mark.parametrize('damage', ['authority', 'source_bound', 'source_translation_performed',
    'native_build_executed', 'training_mask', 'evaluation_gold_mask', 'semantic_mask', 'consumer_mask'])
def test_candidate_mixed_v3_refuses_delegated_authority_or_execution(owner, mixed_candidate_v3, monkeypatch, damage):
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
    candidate, known = mixed_candidate_v3; original = relational.prepare_mixed_relational_norm_v1
    def mutate(*args, **kwargs):
        report = original(*args, **kwargs)
        if damage == 'authority': report['authority']['source_translation_verified'] = True
        elif damage.endswith('_mask'): report[damage] = 1
        else: report[damage] = True
        return report
    monkeypatch.setattr(relational, 'prepare_mixed_relational_norm_v1', mutate)
    with pytest.raises(ValueError):
        owner.validate_complete_norm_candidate_v3(candidate, **known)


@pytest.mark.parametrize('damage', ['unknown-profile', 'nonempty-assumptions', 'selection-policy'])
def test_candidate_mixed_v3_keeps_unsupported_constructs_explicit(owner, mixed_candidate_v3, damage):
    candidate, known = mixed_candidate_v3
    if damage == 'unknown-profile': candidate['profile'] = 'unknown-many-sorted/v999'
    elif damage == 'nonempty-assumptions': candidate['assumptions'] = ['unrepresented fictional premise']
    else: known['known_selection_context']['selection_mode'] = 'meaning-resolved'
    with pytest.raises(owner.CompleteNormCandidateUnsupportedError):
        owner.validate_complete_norm_candidate_v3(candidate, **known)


@pytest.mark.parametrize("conflicting_bytes", [False, True])
def test_reviewed_v2_manifest_refresh_preserves_shared_uses_and_refuses_conflicting_bytes(
        reviewed_case_v2, conflicting_bytes):
    case = reviewed_case_v2
    dependency_id = "fixture:shared-physical-crosswalk"
    dependency_raw = b"fictional shared crosswalk; no statutory review"
    process = dict(artifact_id=REVIEWED_PROCESS_ID,
                   sha256=sha(case["evidence"][REVIEWED_PROCESS_ID]))
    references = [dict(from_unit_id=unit["unit_id"], dependency_artifact_id=dependency_id,
        dependency_sha256=sha(dependency_raw), version="fictional-shared/v1",
        evidence_refs=[deepcopy(process)]) for unit in case["declaration"]["units"]]
    assert len(references) == 3
    if conflicting_bytes:
        references[1]["dependency_sha256"] = sha(dependency_raw + b" changed")
    case["declaration"]["cross_references"] = references
    units_before = deepcopy(case["declaration"]["units"])
    references_before = deepcopy(references)
    manifest_before = deepcopy(case["manifest"])
    if conflicting_bytes:
        with pytest.raises(ValueError, match="conflicting fixture artifact identity"):
            reviewed_refresh_manifest_v2(case)
        assert case["manifest"] == manifest_before
    else:
        reviewed_refresh_manifest_v2(case)
        manifest = case["manifest"]
        expected = [case["declaration"]["component_id"]]
        for unit in units_before:
            expected.extend([unit["source_artifact_id"], unit["ir_artifact_id"]])
        expected.append(dependency_id)
        assert manifest["expected_artifact_ids"] == expected
        assert len(expected) == len(set(expected)) == 8
        assert [edge for edge in manifest["edges"] if edge["dependency_id"] == dependency_id] == [
            dict(dependent_id=case["declaration"]["component_id"], dependency_id=dependency_id)]
        assert case["observed_artifacts"][dependency_id] == sha(dependency_raw)
    assert case["declaration"]["units"] == units_before
    assert case["declaration"]["cross_references"] == references_before


# Repeated-source controls are fictional and keep the source text and typed IR
# together. Alternate raw encodings are not additional legal uses.
def reviewed_repeated_permission_source_v2(case, mutation):
    from ipfs_datasets_py.logic.autoformal import corpus_source as sources
    alternate, original = case["declaration"]["units"][1:]
    old, alternate_old = original["source_version"], alternate["source_version"]
    text = case["source_inputs"][original["unit_id"]]["extracted_text"]
    original_length = len(text)
    identity = {key: old[key] for key in ("source_id", "release_id", "edition", "provision_id")}
    if mutation == "different_provision":
        identity = {key: alternate_old[key] for key in identity}
    elif mutation == "different_release":
        identity["release_id"] += ":separately-reviewed-legal-release"
    elif mutation == "different_edition":
        identity["edition"] += ":separately-reviewed-legal-edition"
    alternate["document_revision"] = original["document_revision"]
    if mutation in ("document_revision_label", "different_view_and_document_revision_label"):
        alternate["document_revision"] += ":artifact-label-only"
    for field in ("coverage", "relational_request_sha256"):
        alternate[field] = deepcopy(original[field])
    if "relational_profile" in original:
        alternate["relational_profile"] = original["relational_profile"]
    case["relational_inputs"][alternate["unit_id"]] = deepcopy(case["relational_inputs"][original["unit_id"]])
    original_use = next(row for row in case["declaration"]["definition_uses"]
                        if row["use_unit_id"] == original["unit_id"])
    alternate_use = next(row for row in case["declaration"]["definition_uses"]
                         if row["use_unit_id"] == alternate["unit_id"])
    alternate_use["target_typed_paths"] = deepcopy(original_use["target_typed_paths"])

    def install(unit, ids, view, raw, start, end, extraction):
        assert (raw.decode("utf-8-sig") if extraction == "fixture:utf8-sig/v1" else raw.decode("utf-8")) == view
        version = sources.build_source_version(**ids, raw_bytes=raw, expected_raw_sha256=sha(raw),
            extracted_text=view, expected_extracted_sha256=sha(view.encode("utf-8")),
            extraction_profile=extraction, normalization_profile="identity/v1", media_type="text/plain")
        occurrence = sources.build_source_occurrence(version, expected_raw_sha256=sha(raw),
            extracted_text=view, expected_extracted_sha256=sha(view.encode("utf-8")),
            start_char=start, end_char=end, start_utf8=len(view[:start].encode("utf-8")),
            end_utf8=len(view[:end].encode("utf-8")))
        unit.update(source_version=version, occurrence=occurrence)
        case["source_inputs"][unit["unit_id"]] = {"raw_bytes": raw, "extracted_text": view}
        for row in unit["coverage"]:
            row.update({key: occurrence[key] for key in ("start_char", "end_char", "start_utf8", "end_utf8")})
        use = next(row for row in case["declaration"]["definition_uses"] if row["use_unit_id"] == unit["unit_id"])
        use["use_occurrence_cid"] = occurrence["record_cid"]

    if mutation in ("nonoverlapping_paragraphs", "nonoverlapping_paragraphs_different_source_id"):
        view = text + "\n" + text
        raw = view.encode("utf-8")
        install(original, identity, view, raw, 0, original_length, "identity/v1")
        alternate_identity = dict(identity)
        if mutation == "nonoverlapping_paragraphs_different_source_id":
            alternate_identity["source_id"] = alternate["unit_id"]
        install(alternate, alternate_identity, view, raw, original_length + 1, len(view), "identity/v1")
    elif mutation in ("different_unaligned_view", "different_view_and_document_revision_label"):
        view = "\n" + text
        install(alternate, identity, view, view.encode("utf-8"), 1, len(view), "identity/v1")
    elif mutation == "physical_alias":
        identity = {key: alternate_old[key] for key in identity}
        install(alternate, identity, text, text.encode("utf-8"), 0, original_length, "identity/v1")
    else:
        raw = b"\xef\xbb\xbf" + text.encode("utf-8")
        start, end = (1, original_length - 1) if mutation == "overlapping_repackage" else (0, original_length)
        install(alternate, identity, text, raw, start, end, "fixture:utf8-sig/v1")
    return original, alternate


def reviewed_refresh_signed_preparation_v2(owner, case):
    reviewed_refresh_manifest_v2(case)
    case["preparation"] = owner.prepare_reviewed_norm_admission_v2(case["declaration"],
        **reviewed_prepare_arguments_v2(case))
    subject = case["preparation"]["subject"]
    raw = norm._wire(case["declaration"])
    case["evidence"][case["declaration"]["component_id"]] = raw
    for claim in case["reviews"]:
        claim["subject"] = deepcopy(subject)
        claim["interpretation"].update(reviewed_graph_sha256=subject["graph_sha256"],
                                       reviewed_ast_sha256=subject["ast_sha256"])
        for obligation in claim["context_closure"]["obligations"]:
            obligation["evidence_refs"][0] = {"artifact_id": case["declaration"]["component_id"], "sha256": sha(raw)}
    reviewed_resign_v2(case)


@pytest.mark.parametrize("mutation,reason", [
    ("duplicate_repackage", "logical source occurrence"),
    ("overlapping_repackage", "overlapping logical source"),
    ("document_revision_label", "logical source occurrence"),
    ("different_unaligned_view", "unsupported source-view alignment"),
    ("different_view_and_document_revision_label", "unsupported source-view alignment"),
    ("physical_alias", "physical occurrence"),
])
def test_reviewed_v2_raw_repackaging_and_artifact_labels_do_not_create_legal_uses(owner, reviewed_case_v2, mutation, reason):
    case = reviewed_case_v2
    original, alternate = reviewed_repeated_permission_source_v2(case, mutation)
    if mutation != "physical_alias":
        assert original["source_version"]["raw_artifact"]["sha256"] != alternate["source_version"]["raw_artifact"]["sha256"]
    reviewed_refresh_manifest_v2(case)
    with pytest.raises(ValueError, match=reason):
        owner.prepare_reviewed_norm_admission_v2(case["declaration"], **reviewed_prepare_arguments_v2(case))
    # The public assessment replays original sources; an old ready preparation
    # cannot substitute for the newly offered duplicate source population.
    with pytest.raises(ValueError, match=reason):
        assess_reviewed_fixture_v2(owner, case)


@pytest.mark.parametrize("mutation", ["different_provision", "different_release", "different_edition", "nonoverlapping_paragraphs", "nonoverlapping_paragraphs_different_source_id"])
def test_reviewed_v2_distinct_legal_identities_and_nonoverlapping_uses_survive(owner, reviewed_case_v2, mutation):
    case = reviewed_case_v2
    original, alternate = reviewed_repeated_permission_source_v2(case, mutation)
    if mutation == "nonoverlapping_paragraphs_different_source_id":
        first, second = original["source_version"], alternate["source_version"]
        assert first["raw_artifact"]["sha256"] == second["raw_artifact"]["sha256"]
        assert first["extracted_view"]["sha256"] == second["extracted_view"]["sha256"]
        assert first["source_id"] != second["source_id"] == alternate["unit_id"]
        assert all(first[field] == second[field] for field in ("release_id", "edition", "provision_id"))
        assert original["occurrence"]["end_char"] < alternate["occurrence"]["start_char"]
        assert original["occurrence"]["end_utf8"] < alternate["occurrence"]["start_utf8"]
    reviewed_refresh_signed_preparation_v2(owner, case)
    report = assess_reviewed_fixture_v2(owner, case)
    assert report["semantic_use_eligible"] is True and report["blockers"] == []
    assert report["fixture_only"] and report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert report["Lean_admitted"] is report["proof_authority"] is report["corpus_admitted"] is False
    assert len({row["occurrence_cid"] for row in report["units"] if row["kind"] == "norm"}) == 2
    assert original["occurrence"]["span_text"] == alternate["occurrence"]["span_text"]


def test_reviewed_v2_alternate_view_of_same_raw_paragraph_requires_distinct_use_witness(owner, reviewed_case_v2):
    from ipfs_datasets_py.logic.autoformal import corpus_source as sources
    # Preparation-only fictional counterexample: no modified signed reviews
    # are submitted to an assessor, and no statutory meaning is asserted.
    case = reviewed_case_v2
    original, relabeled = case["declaration"]["units"][1:]
    assert original["kind"] == relabeled["kind"] == "norm"
    source_input = deepcopy(case["source_inputs"][original["unit_id"]])
    raw, first_view = source_input["raw_bytes"], source_input["extracted_text"]
    first_version, first_occurrence = original["source_version"], original["occurrence"]
    second_view = "\n" + first_view
    raw_sha = sha(raw)
    second_view_sha = sha(second_view.encode("utf-8"))
    assert first_version["raw_artifact"]["sha256"] == raw_sha
    assert second_view_sha != first_version["extracted_view"]["sha256"]
    version = sources.build_source_version(
        source_id=relabeled["unit_id"], release_id=first_version["release_id"],
        edition=first_version["edition"], provision_id=first_version["provision_id"],
        raw_bytes=raw, expected_raw_sha256=raw_sha,
        extracted_text=second_view, expected_extracted_sha256=second_view_sha,
        extraction_profile="fixture-leading-newline-derived-view/v1",
        normalization_profile="preserved-paragraph-leading-newline/v1", media_type="text/plain")
    occurrence = sources.build_source_occurrence(
        version, expected_raw_sha256=raw_sha, extracted_text=second_view,
        expected_extracted_sha256=second_view_sha,
        start_char=first_occurrence["start_char"] + 1,
        end_char=first_occurrence["end_char"] + 1,
        start_utf8=first_occurrence["start_utf8"] + 1,
        end_utf8=first_occurrence["end_utf8"] + 1)
    assert sources.validate_source_version(version, expected_raw_sha256=raw_sha,
        raw_bytes=raw, extracted_text=second_view,
        expected_extracted_sha256=second_view_sha) == version
    assert sources.validate_source_occurrence(occurrence, source_version=version,
        expected_raw_sha256=raw_sha, extracted_text=second_view,
        expected_extracted_sha256=second_view_sha) == occurrence
    assert version["raw_artifact"] == first_version["raw_artifact"]
    assert occurrence["span_text"] == first_occurrence["span_text"]
    assert occurrence["span_sha256"] == first_occurrence["span_sha256"]
    assert occurrence["record_cid"] != first_occurrence["record_cid"]
    relabeled.update(source_version=version, occurrence=occurrence,
        document_revision=original["document_revision"])
    case["source_inputs"][relabeled["unit_id"]] = {
        "raw_bytes": raw, "extracted_text": second_view}
    for coverage in relabeled["coverage"]:
        coverage.update({key: occurrence[key] for key in
            ("start_char", "end_char", "start_utf8", "end_utf8")})
    use = next(row for row in case["declaration"]["definition_uses"]
               if row["use_unit_id"] == relabeled["unit_id"])
    use["use_occurrence_cid"] = occurrence["record_cid"]
    reviewed_refresh_manifest_v2(case)
    assert len(case["declaration"]["units"]) == 3
    assert len(case["declaration"]["definition_uses"]) == 2
    # Different view coordinates cannot establish a second operative physical
    # use. This declaration supplies no common physical-coordinate witness.
    with pytest.raises(ValueError, match=r"same raw|cross.view|physical.*(witness|coordinate)|distinct.*(use|view)"):
        owner.prepare_reviewed_norm_admission_v2(
            case["declaration"], **reviewed_prepare_arguments_v2(case))



@pytest.mark.parametrize("shape", ["parent-two", "parent-three", "governing-parent", "acyclic"])
def test_reviewed_v2_checks_unit_dependencies_before_signed_admission(owner, reviewed_case_v2, shape):
    from tests.unit.logic.autoformal.test_legal_reviewed_norm_admission_v3 import refresh_signed_reviews

    case = reviewed_case_v2
    definition, first, second = case["declaration"]["units"]
    if shape == "parent-two":
        first["parent_unit_ids"] = [second["unit_id"]]
        second["parent_unit_ids"] = [first["unit_id"]]
    elif shape == "parent-three":
        definition["parent_unit_ids"] = [first["unit_id"]]
        first["parent_unit_ids"] = [second["unit_id"]]
        second["parent_unit_ids"] = [definition["unit_id"]]
    elif shape == "governing-parent":
        definition["parent_unit_ids"] = [first["unit_id"]]
    else:
        first["parent_unit_ids"] = [definition["unit_id"]]
        second["parent_unit_ids"] = [first["unit_id"], definition["unit_id"]]
    reviewed_refresh_manifest_v2(case)
    assert case["manifest"]["cycles"] == case["manifest"]["missing_dependencies"] == []
    arguments = reviewed_prepare_arguments_v2(case)
    try:
        case["preparation"] = owner.prepare_reviewed_norm_admission_v2(case["declaration"], **arguments)
    except ValueError as error:
        assert shape != "acyclic"
        assert str(error) == "cyclic or unresolved reviewed governing dependency"
        return
    # A producer that accepts the cycle can issue a newly signed and replayable
    # assessment for it. Verify this on the pre-fix owner before failing.
    refresh_signed_reviews(case, owner)
    report = assess_reviewed_fixture_v2(owner, case)
    assert report["semantic_use_eligible"] and report["blockers"] == []
    assert report["fixture_only"] and report["training_mask"] == report["evaluation_gold_mask"] == 0
    replay_args, replay_options = reviewed_assessment_arguments_v2(owner, case)
    assert owner.validate_reviewed_norm_admission_v2(
        report, *replay_args, expected_report_sha256=norm.norm_review_sha256(report), **replay_options) == report
    assert shape == "acyclic", "cyclic declaration reached signed V2 semantic eligibility"
    assert case["preparation"]["declaration"]["units"] == case["declaration"]["units"]


@pytest.mark.parametrize("versions, shared_id", [
    (("fictional-crosswalk/v1", "fictional-crosswalk/v2"), True),
    (("fictional-crosswalk/v2", "fictional-crosswalk/v1"), True),
    (("fictional-crosswalk/v1", "fictional-crosswalk/v1"), True),
    (("fictional-crosswalk/v1", "fictional-crosswalk/v2"), False),
], ids=["shared-forward-conflict", "shared-reverse-conflict", "shared-equal", "distinct-identities"])
def test_reviewed_v2_cross_reference_version_consistency(owner, reviewed_case_v2, versions, shared_id):
    from tests.unit.logic.autoformal.test_legal_reviewed_norm_admission_v3 import (
        assert_signatures_valid, refresh_signed_reviews,
    )

    case = reviewed_case_v2
    declaration = case["declaration"]
    artifact_ids = (
        "fixture:crosswalk-a", "fixture:crosswalk-a" if shared_id else "fixture:crosswalk-b",
    )
    dependency = b"Identical fictional crosswalk bytes"
    dependency_sha = sha(dependency)
    process = {
        "artifact_id": REVIEWED_PROCESS_ID,
        "sha256": sha(case["evidence"][REVIEWED_PROCESS_ID]),
    }
    references = [
        {"from_unit_id": unit["unit_id"], "dependency_artifact_id": identity,
         "dependency_sha256": dependency_sha, "version": version,
         "evidence_refs": [deepcopy(process)]}
        for unit, identity, version in zip(declaration["units"][1:], artifact_ids, versions, strict=True)
    ]
    declaration["cross_references"] = references
    for identity in set(artifact_ids):
        case["evidence"][identity] = dependency
    reviewed_refresh_manifest_v2(case)
    artifacts = case["manifest"]["artifacts"]
    assert {row["artifact_id"]: row["artifact_sha256"] for row in artifacts
            if row["artifact_id"] in artifact_ids} == dict.fromkeys(artifact_ids, dependency_sha)
    assert case["manifest"]["cycles"] == []
    conflict = shared_id and versions[0] != versions[1]
    try:
        case["preparation"] = owner.prepare_reviewed_norm_admission_v2(
            declaration, **reviewed_prepare_arguments_v2(case))
    except ValueError as error:
        if not conflict:
            raise
        assert "conflicting dependency versions" in str(error)
        return

    refresh_signed_reviews(case, owner)
    assert_signatures_valid(case)
    report = assess_reviewed_fixture_v2(owner, case)
    assert report["semantic_use_eligible"] and report["blockers"] == []
    assert report["fixture_only"] and report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert [unit["canonical_ir"]["cross_references"][0] for unit in report["units"][1:]] == references
    assert not conflict, "contradictory dependency version labels became eligible in a freshly signed V2 review"


@pytest.mark.parametrize("shape", ["independent", "identity", "nested-self-use"])
def test_reviewed_v2_requires_nonrecursive_governing_definition(owner, reviewed_case_v2, shape, tmp_path):
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
    helper = load_fixture("_reviewed_v2_nonrecursive_relational_fixture", "test_legal_relational_norm_v1.py")
    case = reviewed_case_v2
    definition = case["declaration"]["units"][0]
    assert definition["kind"] == "definition"
    builder = helper.Builder()
    head = builder.atom("CoveredOfficer", "officer")
    roles = [("CoveredOfficer", ("officer",))]
    if shape == "identity":
        right = builder.atom("CoveredOfficer", "officer")
    else:
        right = builder.atom("AppointedByBoard", "officer")
        roles.append(("AppointedByBoard", ("officer",)))
        if shape == "nested-self-use":
            right = builder.binary("and", right, builder.atom("CoveredOfficer", "officer"))
    request = helper.request_for(builder, builder.binary("iff", head, right), roles, [("officer", "forall")])
    raw = wire(request)
    request_sha = sha(raw)
    typed = relational.prepare_relational_norm_v1(raw, expected_request_sha256=request_sha)
    assert typed["typed_expression"]["root"]["arguments"][0]["kind"] == "iff"
    definition["relational_request_sha256"] = request_sha
    occurrence = definition["occurrence"]
    definition["coverage"] = [
        {"typed_path": item["typed_path"], **{key: occurrence[key] for key in
            ("start_char", "end_char", "start_utf8", "end_utf8")}}
        for item in typed["structural_mapping"]
    ]
    case["relational_inputs"][definition["unit_id"]] = {
        "request_raw": raw, "report": typed,
        "expected_report_sha256": relational.relational_norm_report_sha256(typed),
    }
    try:
        reviewed_refresh_signed_preparation_v2(owner, case)
    except ValueError as exc:
        assert shape != "independent", str(exc)
        assert "predicate occurs in its own definition" in str(exc)
        return
    keys = {row["key_id"]: row for row in case["registry"]["keys"]}
    assert all(auth._verify_signature(claim, keys[claim["key_id"]]) == "valid" for claim in case["reviews"])
    observed = assess_reviewed_fixture_v2(owner, case)
    observation = {
        "shape": shape, "semantic_use_eligible": observed["semantic_use_eligible"],
        "fixture_only": observed["fixture_only"], "training_mask": observed["training_mask"],
        "evaluation_gold_mask": observed["evaluation_gold_mask"], "Lean_admitted": observed["Lean_admitted"],
        "proof_authority": observed["proof_authority"], "blockers": observed["blockers"],
        "preparation_sha256": norm.norm_review_sha256(case["preparation"]),
        "assessment_sha256": norm.norm_review_sha256(observed),
        "review_statuses": [row["status"] for row in observed["review_authority"]["reviews"]],
    }
    (tmp_path / "nonrecursive-v2-observation.json").write_text(json.dumps(observation, sort_keys=True, indent=2) + "\n")
    if shape != "independent":
        pytest.fail(f"Recursive {shape} passed real V2 typed preparation and was assessed as semantic_use_eligible={observed['semantic_use_eligible']} under exact fictional signatures.")
    assert observed["semantic_use_eligible"] is True
    assert observed["fixture_only"] is True
    assert observed["training_mask"] == observed["evaluation_gold_mask"] == 0
    assert observed["Lean_admitted"] is observed["proof_authority"] is False
