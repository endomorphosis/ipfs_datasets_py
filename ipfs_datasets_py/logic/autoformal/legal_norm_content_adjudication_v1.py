"""Separately authenticated common choices over existing norm answer proposals.

The original and current typed response reports are replayed without changing
their selected trust snapshots. This fixed signing domain authenticates a common
declaration, not statutory meaning. Definition applicability remains open, every
choice remains unapplied, and no signer, trust, clock or interpretation is supplied.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import legal_norm_content_responses_v1 as content
from . import legal_norm_interpretation_review_v1 as norm
from . import legal_paired_manifest_inventory_v1 as reader

PROFILE = "unapplied-common-norm-answer-adjudication/v1"
SUBJECT_SCHEMA = norm.SUBJECT_SCHEMA
DECLARATION_SCHEMA = "legal-norm-content-adjudication-declaration/v1"
TEMPLATE_SCHEMA = "legal-norm-content-adjudication-template/v1"
CLAIM_SCHEMA = "legal-norm-content-adjudication-signed-claim/v1"
ACTION = "record_norm_content_adjudication_declaration/v1"
AUDIENCE = "legal-autoformalization-norm-content-adjudication/v1"
AUTHORITY_SCHEMA = "legal-norm-content-adjudication-authority-assessment/v1"
ASSESSMENT_SCHEMA = "legal-norm-content-adjudication-assessment/v1"
MAX_REPORT_BYTES = norm.MAX_BYTES
MAX_OBLIGATIONS = norm.MAX_OBLIGATIONS
MAX_UNRESOLVED = 32  # Unchanged shared signing-engine unresolved-list bound.
RESPONSE_FIELDS = content._ASSESS_FIELDS | {"response_bindings", "expected_response_bindings_sha256"}
AUTHORITY = dict(content.FALSE_FLAGS, adjudicated_norm_meaning_verified=False,
    decisions_applied=False, adjudicator_human_independence_verified=False,
    cross_candidate_cohort_verified=False, global_reviewer_cohort_verified=False,
    evaluation_clock_authenticated=False, current_registry_freshness_authenticated=False)
_DIRECT_PINS = {str(Path(module.__file__).resolve()): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                for module in (content, norm, reader)}
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_need, _keys, _sha = norm._need, norm._keys, norm._sha


def norm_content_adjudication_sha256(value):
    """Complete bounded norm canonical UTF8 SHA256, including embedded digests.

    Raw declaration evidence hashes exact bytes. Compact claims/registry/policy
    retain the shared review digest and accepted integer-only JSON profile.
    """
    return norm.norm_review_sha256(value)


def _auth():
    return norm._owners()[1]


def _domain():
    return _auth()._ReviewDomain(SUBJECT_SCHEMA, CLAIM_SCHEMA, ACTION, AUDIENCE,
                               AUTHORITY_SCHEMA, norm._subject, MAX_OBLIGATIONS)


def _pins():
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "norm adjudication producer changed since import")
    _need({path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _DIRECT_PINS} == _DIRECT_PINS,
          "direct norm adjudication producer changed since import")
    pins = dict(content._pins())
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    return pins


def _finish(original, detached, commitment, pins, report):
    raw = norm._wire(report)
    _need(len(raw) <= MAX_REPORT_BYTES, "complete norm adjudication report byte bound exceeded")
    _need(norm._snapshot(original)[1] == commitment and norm._snapshot(detached)[1] == commitment,
          "norm adjudication inputs changed during operation")
    _need(_pins() == pins, "norm adjudication producers changed during operation")
    return json.loads(raw)


def _seal(schema, **values):
    return {"schema": schema, "profile": PROFILE, **values, **AUTHORITY,
        "authority": dict(AUTHORITY), "norm_interpretation_ready": False,
        "selected_interpretation": None, "accepted_interpretation": None,
        "governing_definition_use": None, "semantic_mask": 0, "consumer_mask": 0,
        "training_mask": 0, "evaluation_gold_mask": 0}


def _source_args(typed_assessment, subject, registry, policy, reviews, manifest,
                 expected_typed_assessment_sha256, response_inputs):
    return dict(typed_assessment=typed_assessment, subject=subject, source_registry=registry,
        source_policy=policy, source_reviews=reviews, manifest=manifest,
        expected_typed_assessment_sha256=expected_typed_assessment_sha256, response_inputs=response_inputs)


def _context(value):
    _keys(value["response_inputs"], RESPONSE_FIELDS, "complete original norm response replay inputs")
    _sha(value["expected_typed_assessment_sha256"], "complete original typed assessment")
    typed = content.validate_norm_content_assessment_v1(value["typed_assessment"], value["subject"],
        value["source_registry"], value["source_policy"], value["source_reviews"], value["manifest"],
        expected_report_sha256=value["expected_typed_assessment_sha256"], **value["response_inputs"])
    _need(norm._same(typed["subject"], value["subject"]), "typed assessment names another exact norm subject")
    return typed


def _variant(typed, index, ref):
    _keys(ref, {"variant_index", "sha256"}, "existing norm answer variant reference")
    ordinal = ref["variant_index"]
    _need(type(ordinal) is int and 0 <= ordinal < len(typed["answer_variants"]), "exact existing global variant index required")
    _sha(ref["sha256"], "complete existing answer variant")
    pending = typed["pending_questions"][index]
    _need(any(norm._same(ref, offered) for offered in pending["answer_variant_refs"]),
          "variant belongs to another original obligation or generation")
    variant = typed["answer_variants"][ordinal]
    _need(norm.norm_review_sha256(variant) == ref["sha256"] and variant["slot_id"] == pending["slot_id"],
          "complete existing variant commitment differs")
    answer = variant["answer"]
    _need(answer["slot_id"] == pending["slot_id"] and answer["disposition"] in {"evidence_declared", "not_applicable"}
          and type(variant["respondents"]) is list and bool(variant["respondents"]),
          "only authenticated non-unresolved answer proposals may be selected")
    for respondent in variant["respondents"]:
        result_index = respondent["response_result_index"]
        _need(type(result_index) is int and 0 <= result_index < len(typed["response_results"]),
              "exact authenticated response index required")
        result = typed["response_results"][result_index]
        _need(result["authenticated_typed_content"] is True and result["response_record"] is not None
              and all(respondent[field] == result[field] for field in ("review_id", "principal_id", "role"))
              and norm._same(result["response_record"]["answers"][index], answer),
              "variant respondent or exact authenticated answer differs")
    return variant


def _declaration(typed, subject, source_reviews, decisions, declared_at_utc):
    auth = _auth()
    declared = auth._time(declared_at_utc)
    _need(declared >= auth._time(typed["raw_norm_assessment"]["evaluation_time_utc"])
          and all(declared >= auth._time(row["issued_at_utc"]) for row in source_reviews),
          "declaration predates its considered assessment or source review")
    obligations = typed["original_obligations"]
    _need(type(decisions) is list and 0 < len(decisions) == len(obligations) <= MAX_OBLIGATIONS,
          "complete ordered norm adjudication choices required")
    _need(len(typed["pending_questions"]) == len(obligations), "complete pending question population required")
    for index, (choice, obligation) in enumerate(zip(decisions, obligations, strict=True)):
        _keys(choice, {"slot_id", "kind", "obligation_sha256", "decision", "selected_variant_ref", "rationale", "evidence_refs"},
              "norm adjudication choice")
        _need(choice["slot_id"] == obligation["slot_id"] and choice["kind"] == obligation["kind"]
              and choice["obligation_sha256"] == norm.norm_review_sha256(obligation)
              and type(choice["decision"]) is str and choice["decision"] in {"select_existing_variant", "unresolved"},
              "choice differs from exact ordered original obligation")
        content._text(choice["rationale"], "adjudication rationale")
        content._refs(choice["evidence_refs"])
        if obligation.get("question") == "definition_applicability":
            _need(choice["decision"] == "unresolved" and choice["selected_variant_ref"] is None,
                  "definition applicability must remain explicitly unresolved")
        if choice["decision"] == "unresolved":
            _need(choice["selected_variant_ref"] is None, "unresolved choice cannot select a variant")
        else:
            _need(bool(choice["evidence_refs"]), "selected proposal needs independent supporting evidence")
            _variant(typed, index, choice["selected_variant_ref"])
    _need(sum(row["decision"] == "unresolved" for row in decisions) <= MAX_UNRESOLVED,
          "shared unresolved obligation bound exceeded")
    record = _seal(DECLARATION_SCHEMA, subject_sha256=auth.digest(subject),
        typed_assessment_sha256=norm_content_adjudication_sha256(typed),
        preparation_sha256=typed["preparation_sha256"],
        dependency_manifest_sha256=subject["dependency_manifest_sha256"],
        original_obligations_sha256=norm.norm_review_sha256(obligations),
        pending_questions_sha256=norm.norm_review_sha256(typed["pending_questions"]),
        considered_answer_variants_sha256=norm.norm_review_sha256(typed["answer_variants"]),
        considered_candidate_proposals_sha256=norm.norm_review_sha256(typed["candidate_proposals"]),
        source_review_population_sha256=auth.digest(source_reviews),
        declared_at_utc=declared_at_utc, decisions=decisions,
        status="declared_unauthenticated_common_norm_answer_choices")
    auth.wire(record)
    reader._wire(record, norm.MAX_BYTES)
    return record


def _closure(record, typed):
    obligations, unresolved = [], []
    for index, choice in enumerate(record["decisions"]):
        if choice["decision"] == "unresolved":
            disposition = "open"
            unresolved.append(choice["slot_id"])
        else:
            disposition = content.DISPOSITIONS[_variant(typed, index, choice["selected_variant_ref"])["answer"]["disposition"]]
        obligations.append({"slot_id": choice["slot_id"], "disposition": disposition})
    return {"status": "open" if unresolved else "declared_complete", "obligations": obligations, "unresolved": unresolved}


def _source_exclusions(source_registry, source_reviews):
    """Inventory every supplied claim plus its registered actor, even if rejected."""
    keys = {row["key_id"]: row for row in source_registry["keys"]}
    principals, dids, public_keys, unknown, actors = set(), set(), set(), [], []
    for claim in source_reviews:
        principals.add(claim["principal_id"])
        dids.add(claim["signer_did"])
        key = keys.get(claim["key_id"])
        if key is None:
            unknown.append(claim["review_id"])
        else:
            principals.add(key["principal_id"])
            dids.add(key["signer_did"])
            public_keys.add(key["public_key_hex"])
        actors.append({"review_id": claim["review_id"], "key_id": claim["key_id"],
            "claimed_principal_id": claim["principal_id"], "claimed_signer_did": claim["signer_did"],
            "registered_principal_id": None if key is None else key["principal_id"],
            "registered_signer_did": None if key is None else key["signer_did"],
            "registered_public_key_hex": None if key is None else key["public_key_hex"]})
    return {"excluded_principal_ids": sorted(principals), "excluded_signer_dids": sorted(dids),
        "excluded_public_keys": sorted(public_keys), "unknown_key_review_ids": unknown, "actors": actors,
        "scope": "complete supplied one-subject review population; not cross-candidate or global completeness"}


def _distinct_pair(claims, keys):
    return any(left["role"] == "legal_review" and right["role"] == "formal_review"
        and left["key_id"] in keys and right["key_id"] in keys
        and left["principal_id"] != right["principal_id"] and left["key_id"] != right["key_id"]
        and left["signer_did"] != right["signer_did"]
        and keys[left["key_id"]]["public_key_hex"] != keys[right["key_id"]]["public_key_hex"]
        for left in claims for right in claims)


def _content(identity, expected_raw_sha256, expected_canonical_sha256, evidence, claims,
             typed, subject, source_reviews, response_body_ids, response_body_sha256s):
    if identity is None:
        return None, []
    try:
        record = content._load_body(evidence.get(identity), expected_raw_sha256)
        _need(norm_content_adjudication_sha256(record) == expected_canonical_sha256,
              "independent complete common declaration canonical pin differs")
        expected = _declaration(typed, subject, source_reviews, record["decisions"], record["declared_at_utc"])
        _need(norm._same(record, expected), "common declaration differs from complete original population regeneration")
        closure = _closure(record, typed)
        body_ref = {"artifact_id": identity, "sha256": expected_raw_sha256}
        for obligation in closure["obligations"]:
            obligation["evidence_refs"] = [body_ref]
        _need(all(norm._same(claim["context_closure"], closure) for claim in claims),
              "signed declaration choices, order, unresolved population or complete body reference differs")
        forbidden_ids = set(response_body_ids) | {identity}
        forbidden_sha256s = set(response_body_sha256s) | {expected_raw_sha256}
        for choice in record["decisions"]:
            for ref in choice["evidence_refs"]:
                raw = evidence.get(ref["artifact_id"])
                _need(ref["artifact_id"] not in forbidden_ids and ref["sha256"] not in forbidden_sha256s
                      and type(raw) is bytes and hashlib.sha256(raw).hexdigest() == ref["sha256"],
                      "independent choice evidence missing, changed or aliases a supplied response/common body")
        return record, []
    except (ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
        return None, [str(error) or "invalid common norm adjudication content"]


def _authority_inputs(registry, policy, reviews, identity, raw_pin, canonical_pin,
                      registry_pin, policy_pin, reviews_pin, evidence):
    auth = _auth()
    for pin in (registry_pin, policy_pin, reviews_pin):
        _sha(pin, "independent adjudication trust/review population")
    auth._trust(registry, policy, registry_pin, policy_pin, action=ACTION, audience=AUDIENCE)
    _need(type(reviews) is list and len(reviews) <= auth.MAX_REVIEWS and auth.digest(reviews) == reviews_pin,
          "independently pinned complete adjudication review population differs")
    _need(type(evidence) is dict and len(evidence) <= auth.MAX_EVIDENCE
          and all(type(key) is str and type(raw) is bytes for key, raw in evidence.items())
          and sum(map(len, evidence.values())) <= auth.MAX_BYTES, "bounded immutable adjudication evidence required")
    for key in evidence:
        auth._id(key, "adjudication evidence identity")
    _need(sum(len(auth.wire(value)) for value in (registry, policy, reviews))
          + sum(map(len, evidence.values())) <= auth.MAX_BYTES,
          "aggregate adjudication trust and evidence byte bound exceeded")
    if identity is None:
        _need(raw_pin is None and canonical_pin is None and reviews == [],
              "absent declaration requires absent raw/canonical pins and no authority claims")
    else:
        auth._id(identity, "common declaration identity")
        _sha(raw_pin, "common declaration raw bytes")
        _sha(canonical_pin, "complete common declaration canonical value")


def _assess_prepared(typed, current_typed, subject, source_registry, source_policy, source_reviews,
        manifest, adjudication_registry, adjudication_policy, adjudication_reviews, *, declaration_artifact_id,
        expected_declaration_raw_sha256, expected_declaration_sha256, expected_adjudication_registry_sha256,
        expected_adjudication_policy_sha256, expected_adjudication_reviews_sha256, at_time_utc,
        observed_artifact_sha256s, observed_pins, evidence_artifacts):
    """Downstream unit seam; public intake first fully replays both typed reports."""
    auth = _auth()
    _authority_inputs(adjudication_registry, adjudication_policy, adjudication_reviews,
        declaration_artifact_id, expected_declaration_raw_sha256, expected_declaration_sha256,
        expected_adjudication_registry_sha256, expected_adjudication_policy_sha256,
        expected_adjudication_reviews_sha256, evidence_artifacts)
    _need(current_typed["raw_norm_assessment"]["evaluation_time_utc"] == at_time_utc,
          "current typed source assessment uses another explicit clock")
    _need(norm._same(typed["subject"], subject) and norm._same(current_typed["subject"], subject),
          "original/current typed assessments name another exact subject")
    authority = auth._assess_reviews(subject, adjudication_registry, adjudication_policy, adjudication_reviews,
        manifest, domain=_domain(), expected_subject_sha256=auth.digest(subject),
        expected_registry_sha256=expected_adjudication_registry_sha256,
        expected_policy_sha256=expected_adjudication_policy_sha256,
        expected_reviews_sha256=expected_adjudication_reviews_sha256,
        expected_manifest_sha256=subject["dependency_manifest_sha256"], at_time_utc=at_time_utc,
        observed_artifact_sha256s=observed_artifact_sha256s, observed_pins=observed_pins,
        evidence_artifacts=evidence_artifacts)
    response_body_ids = {row["artifact_id"] for row in typed["response_bindings"]}
    response_body_sha256s = {row["raw_sha256"] for row in typed["response_bindings"]}
    record, content_blockers = _content(declaration_artifact_id, expected_declaration_raw_sha256,
        expected_declaration_sha256, evidence_artifacts, adjudication_reviews, typed, subject, source_reviews,
        response_body_ids, response_body_sha256s)
    inventory = _source_exclusions(source_registry, source_reviews)
    source_keys = {row["key_id"]: row for row in source_registry["keys"]}
    adjudicator_keys = {row["key_id"]: row for row in adjudication_registry["keys"]}
    blockers = []
    if inventory["unknown_key_review_ids"]:
        blockers.append("source_cohort_public_key_inventory_incomplete")
    for claim in adjudication_reviews:
        key = adjudicator_keys.get(claim["key_id"])
        if claim["principal_id"] in inventory["excluded_principal_ids"] or key is not None and key["principal_id"] in inventory["excluded_principal_ids"]:
            blockers.append("adjudicator_reuses_supplied_source_claimed_or_registered_principal")
        if claim["signer_did"] in inventory["excluded_signer_dids"] or key is not None and key["signer_did"] in inventory["excluded_signer_dids"]:
            blockers.append("adjudicator_reuses_supplied_source_claimed_or_registered_did")
        if key is not None and key["public_key_hex"] in inventory["excluded_public_keys"]:
            blockers.append("adjudicator_reuses_supplied_source_registered_public_key")
    authenticated_adj_ids = {row["review_id"] for row in authority["reviews"] if row["status"] == "authenticated"}
    authenticated_adj = [row for row in adjudication_reviews if row["review_id"] in authenticated_adj_ids]
    if not _distinct_pair(authenticated_adj, adjudicator_keys):
        blockers.append("distinct_authenticated_adjudicator_principal_key_did_public_key_roles_missing")
    if any(row["interpretation"]["decision"] != "support" or row["interpretation"]["ambiguity"] for row in authenticated_adj):
        blockers.append("adjudication_claims_reject_or_dispute_common_declaration")
    evaluation = auth._time(at_time_utc)
    if evaluation < auth._time(typed["raw_norm_assessment"]["evaluation_time_utc"]):
        blockers.append("adjudication_evaluation_predates_original_typed_assessment")
    if record is not None:
        declared = auth._time(record["declared_at_utc"])
        if declared > evaluation:
            blockers.append("common_declaration_postdates_evaluation")
        if any(auth._time(row["issued_at_utc"]) < declared for row in adjudication_reviews):
            blockers.append("authority_claim_predates_common_declaration")
    raw_current = current_typed["raw_norm_assessment"]
    current_ids = {row["review_id"] for row in current_typed["response_results"] if row["authenticated_typed_content"] is True}
    current_source_claims = [row for row in source_reviews if row["review_id"] in current_ids]
    source_blockers = []
    if not source_reviews or len(current_ids) != len(source_reviews) or raw_current["authenticated_evidence_count"] != len(source_reviews):
        source_blockers.append("complete_original_source_claims_and_typed_bodies_not_currently_authenticated")
    if not _distinct_pair(current_source_claims, source_keys):
        source_blockers.append("distinct_current_authenticated_source_principal_key_did_public_key_roles_missing")
    if raw_current["trust_mode"] != "external_pinned_trust":
        source_blockers.append("original_source_production_trust_unavailable")
    if "required_dependency_closure_not_current" in raw_current["blockers"]:
        source_blockers.append("original_source_dependency_closure_not_current")
    if inventory["unknown_key_review_ids"]:
        source_blockers.append("source_cohort_public_key_inventory_incomplete")
    source_ready = not source_blockers
    body_authenticated = (record is not None and not content_blockers and bool(adjudication_reviews)
                          and len(authenticated_adj) == len(adjudication_reviews))
    if authority["trust_mode"] != "external_pinned_trust":
        blockers.append("adjudication_production_trust_unavailable")
    if "required_dependency_closure_not_current" in authority["blockers"]:
        blockers.append("adjudication_dependency_closure_not_current")
    custody_ready = body_authenticated and source_ready and not blockers
    selected = 0 if record is None else sum(row["decision"] == "select_existing_variant" for row in record["decisions"])
    return _seal(ASSESSMENT_SCHEMA, subject=subject,
        expected_typed_assessment_sha256=norm_content_adjudication_sha256(typed),
        original_typed_assessment=typed, current_typed_assessment=current_typed,
        raw_adjudication_authority_assessment=authority,
        declaration_artifact_ref=None if declaration_artifact_id is None else {
            "artifact_id": declaration_artifact_id, "sha256": expected_declaration_raw_sha256},
        expected_declaration_sha256=expected_declaration_sha256,
        observed_declaration_raw_sha256=None if declaration_artifact_id not in evidence_artifacts else hashlib.sha256(evidence_artifacts[declaration_artifact_id]).hexdigest(),
        declaration_record=record, common_body_content_status="absent" if declaration_artifact_id is None else "rejected" if content_blockers else "valid_declared_content",
        content_blockers=content_blockers, source_reviewer_exclusions=inventory,
        separation_and_chronology_blockers=sorted(set(blockers)), current_source_blockers=source_blockers,
        common_body_authenticated_under_selected_trust=bool(body_authenticated),
        current_source_prerequisites_satisfied=bool(source_ready),
        adjudication_prerequisites_satisfied_under_selected_trust=bool(custody_ready),
        prerequisite_scope="partial common-declaration custody only; shared open-context readiness is unchanged",
        closed_context_prerequisites_satisfied=False,
        closed_context_blockers=["definition_applicability_required_unresolved", "no_semantic_admission_or_decision_application"],
        pending_slots=[{"slot_id": row["slot_id"], "kind": row["kind"], "decision_applied": False,
            "declared_decision": None if record is None else record["decisions"][index]["decision"],
            "status": "pending_unapplied_norm_content_choice"} for index, row in enumerate(typed["original_obligations"])],
        counts={"source_reviews": len(source_reviews), "declaration_bodies": int(declaration_artifact_id is not None),
            "authenticated_authority_claims": authority["authenticated_evidence_count"],
            "declared_selected_slots": selected, "unresolved_or_absent_slots": len(typed["original_obligations"]) - selected,
            "decisions_applied": 0, "definition_applications": 0},
        evidence_scope="Opaque referenced response attachments remain bytes; no bridge, declaration-author or nested-evidence verification.")


def build_norm_content_adjudication_template_v1(typed_assessment, subject, source_registry,
        source_policy, source_reviews, manifest, *, expected_typed_assessment_sha256, response_inputs):
    original = _source_args(typed_assessment, subject, source_registry, source_policy, source_reviews,
                           manifest, expected_typed_assessment_sha256, response_inputs)
    detached, commitment = norm._snapshot(original)
    _keys(detached["response_inputs"], RESPONSE_FIELDS, "complete original norm response replay inputs")
    pins = _pins()
    typed = _context(detached)
    report = _seal(TEMPLATE_SCHEMA, subject_sha256=_auth().digest(detached["subject"]),
        typed_assessment_sha256=expected_typed_assessment_sha256,
        original_obligations=typed["original_obligations"], answer_variants=typed["answer_variants"],
        pending_questions=typed["pending_questions"], candidate_proposals=typed["candidate_proposals"],
        declaration={"declared_at_utc": None, "decisions": [{"slot_id": row["slot_id"], "kind": row["kind"],
            "obligation_sha256": norm.norm_review_sha256(row), "decision": None,
            "selected_variant_ref": None, "rationale": None, "evidence_refs": []} for row in typed["original_obligations"]]},
        status="blank_unsubmitted_common_norm_adjudication_template", producer_pins=pins)
    return _finish(original, detached, commitment, pins, report)


def build_norm_content_adjudication_declaration_v1(typed_assessment, subject, source_registry,
        source_policy, source_reviews, manifest, decisions, *, declared_at_utc,
        expected_typed_assessment_sha256, response_inputs):
    original = dict(_source_args(typed_assessment, subject, source_registry, source_policy, source_reviews,
        manifest, expected_typed_assessment_sha256, response_inputs), decisions=decisions, declared_at_utc=declared_at_utc)
    detached, commitment = norm._snapshot(original)
    _keys(detached["response_inputs"], RESPONSE_FIELDS, "complete original norm response replay inputs")
    pins = _pins()
    typed = _context(detached)
    report = _declaration(typed, detached["subject"], detached["source_reviews"], detached["decisions"], detached["declared_at_utc"])
    return _finish(original, detached, commitment, pins, report)


def assess_norm_content_adjudication_v1(typed_assessment, subject, source_registry, source_policy,
        source_reviews, manifest, adjudication_registry, adjudication_policy, adjudication_reviews, *,
        expected_typed_assessment_sha256, response_inputs, declaration_artifact_id,
        expected_declaration_raw_sha256, expected_declaration_sha256, expected_adjudication_registry_sha256,
        expected_adjudication_policy_sha256, expected_adjudication_reviews_sha256, at_time_utc,
        observed_artifact_sha256s, observed_pins, evidence_artifacts):
    original = dict(_source_args(typed_assessment, subject, source_registry, source_policy, source_reviews,
        manifest, expected_typed_assessment_sha256, response_inputs),
        adjudication_registry=adjudication_registry, adjudication_policy=adjudication_policy,
        adjudication_reviews=adjudication_reviews, declaration_artifact_id=declaration_artifact_id,
        expected_declaration_raw_sha256=expected_declaration_raw_sha256, expected_declaration_sha256=expected_declaration_sha256,
        expected_adjudication_registry_sha256=expected_adjudication_registry_sha256,
        expected_adjudication_policy_sha256=expected_adjudication_policy_sha256,
        expected_adjudication_reviews_sha256=expected_adjudication_reviews_sha256, at_time_utc=at_time_utc,
        observed_artifact_sha256s=observed_artifact_sha256s, observed_pins=observed_pins, evidence_artifacts=evidence_artifacts)
    detached, commitment = norm._snapshot(original)
    _keys(detached["response_inputs"], RESPONSE_FIELDS, "complete original norm response replay inputs")
    pins = _pins()
    authority_fields = {key: detached[key] for key in ("declaration_artifact_id", "expected_declaration_raw_sha256",
        "expected_declaration_sha256", "expected_adjudication_registry_sha256", "expected_adjudication_policy_sha256",
        "expected_adjudication_reviews_sha256", "at_time_utc", "observed_artifact_sha256s", "observed_pins", "evidence_artifacts")}
    _authority_inputs(detached["adjudication_registry"], detached["adjudication_policy"], detached["adjudication_reviews"],
        detached["declaration_artifact_id"], detached["expected_declaration_raw_sha256"], detached["expected_declaration_sha256"],
        detached["expected_adjudication_registry_sha256"], detached["expected_adjudication_policy_sha256"],
        detached["expected_adjudication_reviews_sha256"], detached["evidence_artifacts"])
    typed = _context(detached)
    current_inputs = dict(detached["response_inputs"], at_time_utc=detached["at_time_utc"],
        observed_artifact_sha256s=detached["observed_artifact_sha256s"], observed_pins=detached["observed_pins"])
    current = content.assess_norm_content_responses_v1(detached["subject"], detached["source_registry"],
        detached["source_policy"], detached["source_reviews"], detached["manifest"], **current_inputs)
    report = _assess_prepared(typed, current, detached["subject"], detached["source_registry"],
        detached["source_policy"], detached["source_reviews"], detached["manifest"], detached["adjudication_registry"],
        detached["adjudication_policy"], detached["adjudication_reviews"], **authority_fields)
    report["producer_pins"] = pins
    report["assessment_sha256"] = norm_content_adjudication_sha256(report)
    return _finish(original, detached, commitment, pins, report)


def validate_norm_content_adjudication_v1(report, *args, expected_report_sha256, **kwargs):
    original = dict(report=report, args=list(args), kwargs=kwargs)
    detached, commitment = norm._snapshot(original)
    pins = _pins()
    _sha(expected_report_sha256, "complete norm adjudication report")
    _need(norm_content_adjudication_sha256(detached["report"]) == expected_report_sha256,
          "independently pinned norm adjudication report differs")
    expected = assess_norm_content_adjudication_v1(*detached["args"], **detached["kwargs"])
    _need(norm._same(detached["report"], expected), "norm adjudication differs from complete exact regeneration")
    return _finish(original, detached, commitment, pins, expected)


__all__ = ["build_norm_content_adjudication_template_v1", "build_norm_content_adjudication_declaration_v1",
    "assess_norm_content_adjudication_v1", "validate_norm_content_adjudication_v1", "norm_content_adjudication_sha256"]
