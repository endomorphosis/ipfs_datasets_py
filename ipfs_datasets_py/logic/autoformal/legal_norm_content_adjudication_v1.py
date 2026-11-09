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


# A separate signing domain is necessary: V1 signs unapplied proposals and can
# never authorize this transition. The initial V2 fragment deliberately reuses
# the complete relational owner; unsupported counting/temporal terms refuse.
REVIEWED_PROFILE = "complete-reviewed-norm-admission/v2"
REVIEWED_DECLARATION_SCHEMA = "legal-reviewed-norm-declaration/v2"
REVIEWED_SUBJECT_SCHEMA = "legal-reviewed-norm-subject/v2"
REVIEWED_CLAIM_SCHEMA = "legal-reviewed-norm-signed-claim/v2"
REVIEWED_ACTION = "admit_complete_reviewed_norm_meaning/v2"
REVIEWED_AUDIENCE = "legal-autoformalization-reviewed-norm/v2"
REVIEWED_SLOTS = ("complete_reviewed_meaning", "governing_context",
    "definition_use_applicability", "complete_dependency_inventory", "permitted_uses")
REVIEWED_USES = ("formalization", "training", "hparam_selection", "heldout_evaluation", "proof_obligation")


def _reviewed_owners():
    from . import corpus_source, corpus_contracts, legal_relational_norm_v1, legal_graph_dependencies
    return corpus_source, corpus_contracts, legal_relational_norm_v1, legal_graph_dependencies


def _reviewed_pins():
    source, contracts, relational, dependencies = _reviewed_owners()
    pins = _pins()
    pins.update(relational._owners()[-1])
    for module in (source, contracts, dependencies):
        path = Path(module.__file__).resolve()
        pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    # Source record CIDs and signature verification have their own owners.
    from ipfs_datasets_py.utils import cid_utils
    from .. import profile_g
    for module in (cid_utils, profile_g):
        path = Path(module.__file__).resolve()
        pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return pins


def _reviewed_finish(original, detached, commitment, pins, report):
    raw = norm._wire(report)
    _need(len(raw) <= _auth().MAX_BYTES, "complete reviewed admission report byte bound exceeded")
    _need(norm._snapshot(original)[1] == commitment and norm._snapshot(detached)[1] == commitment,
          "reviewed admission inputs changed during operation")
    _need(_reviewed_pins() == pins, "reviewed admission producers changed during operation")
    return json.loads(raw)


def _reviewed_refs(refs):
    _need(type(refs) is list and 0 < len(refs) <= 8, "independent process evidence references required")
    seen = set()
    for ref in refs:
        _keys(ref, {"artifact_id", "sha256"}, "reviewed process evidence")
        _auth()._id(ref["artifact_id"], "reviewed evidence identity")
        _sha(ref["sha256"], "reviewed process evidence")
        _need(ref["artifact_id"] not in seen, "duplicate process evidence identity")
        seen.add(ref["artifact_id"])


def _reviewed_subject(subject, manifest):
    auth = _auth()
    _keys(subject, {"schema", "graph_id", "graph_sha256", "ast_sha256", "scope_id",
        "context_slot_ids", "dependency_manifest_sha256", "required_dependency_ids",
        "declaration_sha256", "source_binding_sha256", "context_packet_sha256"}, "reviewed norm subject")
    _need(subject["schema"] == REVIEWED_SUBJECT_SCHEMA and subject["context_slot_ids"] == list(REVIEWED_SLOTS),
          "fixed complete reviewed norm signing subject required")
    for key, value in subject.items():
        if key.endswith("_sha256"):
            _sha(value, key)
    auth._id(subject["graph_id"], "reviewed component identity")
    auth._text(subject["scope_id"], "reviewed jurisdiction")
    reachable, _ = auth._closure(manifest, subject["graph_id"], subject["graph_sha256"])
    _need(subject["graph_sha256"] == subject["declaration_sha256"]
          and subject["required_dependency_ids"] == reachable, "complete reviewed dependency closure differs")


def _reviewed_units(body, source_inputs, relational_inputs):
    source, _, relational, _ = _reviewed_owners()
    units = body["units"]
    _need(type(units) is list and 3 <= len(units) <= 16, "bounded definition and distinct-use component required")
    ids = [row.get("unit_id") for row in units if type(row) is dict]
    _need(len(ids) == len(units) and all(type(key) is str for key in ids) and len(set(ids)) == len(ids),
          "unique complete source unit identities required")
    _need(type(source_inputs) is dict and type(relational_inputs) is dict
          and set(source_inputs) == set(relational_inputs) == set(ids), "complete original source and IR inputs required")
    results, expected_artifacts, occurrences, norm_intervals = [], {}, set(), []
    for unit in units:
        _keys(unit, {"unit_id", "kind", "source_version", "occurrence", "document_revision",
            "parent_unit_ids", "relational_request_sha256", "source_artifact_id", "ir_artifact_id", "coverage"},
            "complete reviewed source unit")
        identity = unit["unit_id"]
        _auth()._id(identity, "reviewed unit")
        _need(unit["kind"] in ("norm", "definition"), "supported complete unit kind required")
        _auth()._text(unit["document_revision"], "exact document revision")
        parents = unit["parent_unit_ids"]
        _need(type(parents) is list and len(parents) == len(set(parents)) and all(
            type(key) is str and key in ids and key != identity for key in parents), "explicit distinct parent unit references required")
        inputs = source_inputs[identity]
        _keys(inputs, {"raw_bytes", "extracted_text"}, "complete original source bytes and view")
        version = unit["source_version"]
        raw_sha, view_sha = version["raw_artifact"]["sha256"], version["extracted_view"]["sha256"]
        _need(type(inputs["raw_bytes"]) is bytes, "original raw source bytes required")
        source.validate_source_version(version, expected_raw_sha256=raw_sha, raw_bytes=inputs["raw_bytes"],
            extracted_text=inputs["extracted_text"], expected_extracted_sha256=view_sha)
        occurrence = source.validate_source_occurrence(unit["occurrence"], source_version=version,
            expected_raw_sha256=raw_sha, extracted_text=inputs["extracted_text"], expected_extracted_sha256=view_sha)
        # Aliases, source labels and record seals cannot turn the same retained
        # artifact/view interval into an additional physical statutory use.
        physical_parent = (raw_sha, view_sha)
        physical = physical_parent + (occurrence["start_char"], occurrence["end_char"])
        _need(physical not in occurrences, "two interpretations of one physical occurrence are not distinct units")
        occurrences.add(physical)
        if unit["kind"] == "norm":
            _need(not any(parent == physical_parent and max(start, occurrence["start_char"]) < min(end, occurrence["end_char"])
                for parent, start, end in norm_intervals), "overlapping interpretations are not two distinct normative uses")
            norm_intervals.append((physical_parent, occurrence["start_char"], occurrence["end_char"]))
        if body["provenance_kind"] == "statutory":
            _need(not any(str(version[key]).startswith("fixture:") for key in ("source_id", "release_id", "provision_id")),
                  "fictional source identities cannot be promoted to statutory evidence")
        ir_inputs = relational_inputs[identity]
        _keys(ir_inputs, {"request_raw", "report", "expected_report_sha256"}, "complete relational replay inputs")
        report = relational.validate_relational_norm_v1(ir_inputs["report"], ir_inputs["request_raw"],
            expected_request_sha256=unit["relational_request_sha256"], expected_report_sha256=ir_inputs["expected_report_sha256"])
        coverage = unit["coverage"]
        paths = [row["typed_path"] for row in report["structural_mapping"]]
        _need(type(coverage) is list and len(coverage) == len(paths), "complete typed-node source correspondence required")
        intervals = []
        for row, path in zip(coverage, paths, strict=True):
            _keys(row, {"typed_path", "start_char", "end_char", "start_utf8", "end_utf8"}, "typed-node correspondence")
            _need(row["typed_path"] == path, "complete ordered typed-node population differs")
            _need(all(type(row[key]) is int for key in ("start_char", "end_char", "start_utf8", "end_utf8")),
                  "exact integer source coordinates required")
            _need(occurrence["start_char"] <= row["start_char"] < row["end_char"] <= occurrence["end_char"],
                  "typed-node correspondence leaves the reviewed occurrence")
            source.build_source_occurrence(version, expected_raw_sha256=raw_sha,
                extracted_text=inputs["extracted_text"], expected_extracted_sha256=view_sha,
                **{key: row[key] for key in ("start_char", "end_char", "start_utf8", "end_utf8")})
            intervals.append((row["start_char"], row["end_char"]))
        frontier = occurrence["start_char"]
        for start, end in sorted(intervals):
            _need(start <= frontier, "reviewed source coverage has a gap")
            frontier = max(frontier, end)
        _need(frontier == occurrence["end_char"], "reviewed source coverage is incomplete")
        for field, pin in (("source_artifact_id", norm_content_adjudication_sha256(version)),
                           ("ir_artifact_id", unit["relational_request_sha256"])):
            artifact = unit[field]
            _auth()._id(artifact, field)
            _need(artifact not in expected_artifacts, "source and IR artifacts need distinct identities")
            expected_artifacts[artifact] = pin
        results.append({"unit_id": identity, "kind": unit["kind"], "source_text": occurrence["span_text"],
            "occurrence_cid": occurrence["record_cid"], "source_version_cid": version["record_cid"],
            "canonical_ir": {"profile": report["profile"], "typed_expression": report["typed_expression"],
                "argument_roles": report["argument_roles"], "assumptions": body["assumptions"],
                "governing_context": body["governing_context"], "interpretation_id": body["interpretation_id"],
                "source_binding": {"source_version_cid": version["record_cid"],
                    "occurrence_cid": occurrence["record_cid"], "document_revision": unit["document_revision"]},
                "definition_uses": [use for use in body["definition_uses"]
                    if use.get("use_unit_id") == identity or use.get("definition_unit_id") == identity],
                "cross_references": [ref for ref in body["cross_references"] if ref.get("from_unit_id") == identity]},
            "argument_roles": report["argument_roles"],
            "relational_profile": report["profile"], "typed_paths": paths})
    return results, expected_artifacts


def _reviewed_body(body, source_inputs, relational_inputs):
    _keys(body, {"schema", "component_id", "provenance_kind", "interpretation_id", "governing_context",
        "units", "definition_uses", "cross_references", "permitted_uses", "unresolved", "unsupported",
        "assumptions", "source_actors", "declared_at_utc"}, "complete reviewed meaning declaration")
    _need(body["schema"] == REVIEWED_DECLARATION_SCHEMA and body["provenance_kind"] in ("fictional_fixture", "statutory"),
          "explicit complete reviewed declaration and provenance required")
    auth = _auth()
    auth._id(body["component_id"], "reviewed component")
    auth._id(body["interpretation_id"], "selected interpretation")
    declared = auth._time(body["declared_at_utc"])
    context = body["governing_context"]
    _keys(context, {"jurisdiction", "instrument_id", "governing_edition", "legal_as_of_utc",
        "valid_from_utc", "valid_until_utc"}, "governing legal context")
    for key in ("jurisdiction", "instrument_id", "governing_edition"):
        auth._text(context[key], key)
    start, end = auth._interval(context)
    _need(start <= auth._time(context["legal_as_of_utc"]) < end, "legal-as-of lies outside declared applicability interval")
    _need(body["unresolved"] == [] and body["unsupported"] == [], "unresolved or unsupported meaning cannot be admitted")
    assumptions = body["assumptions"]
    _need(type(assumptions) is list and assumptions == [],
          "nonempty formal assumptions require a separately supported typed-premise profile")
    uses = body["permitted_uses"]
    _need(type(uses) is list and uses and all(type(use) is str and use in REVIEWED_USES for use in uses)
          and len(set(uses)) == len(uses), "distinct explicitly permitted semantic uses required")
    actors = body["source_actors"]
    _need(type(actors) is list and 0 < len(actors) <= 32, "complete declared source/IR producer actor inventory required")
    for actor in actors:
        _keys(actor, {"principal_id", "signer_did", "public_key_hex"}, "source producer actor")
        auth._id(actor["principal_id"], "source principal")
        _need(type(actor["signer_did"]) is str and auth._DID.fullmatch(actor["signer_did"]), "source signer DID required")
        _sha(actor["public_key_hex"], "source Ed25519 public key")
    units, artifacts = _reviewed_units(body, source_inputs, relational_inputs)
    by_id = {row["unit_id"]: row for row in units}
    definitions = {key for key, row in by_id.items() if row["kind"] == "definition"}
    norms = {key for key, row in by_id.items() if row["kind"] == "norm"}
    _need(definitions and len(norms) >= 2, "a governing definition and two actual normative uses are required")
    applications, applied, distinct, governed = body["definition_uses"], set(), set(), set()
    _need(type(applications) is list and 2 <= len(applications) <= 64, "complete every-use definition applicability required")
    for use in applications:
        _keys(use, {"definition_unit_id", "defined_predicate", "use_unit_id", "use_occurrence_cid", "target_typed_paths",
            "applicability", "interpretation_id", "evidence_refs"}, "reviewed definition use")
        definition, target = use["definition_unit_id"], use["use_unit_id"]
        _need(definition in definitions and target in norms and use["applicability"] == "governing"
              and use["interpretation_id"] == body["interpretation_id"], "selected governing definition and interpretation required")
        _need(use["use_occurrence_cid"] == by_id[target]["occurrence_cid"] and (definition, target) not in applied,
              "definition use duplicates a physical use or names another occurrence")
        symbol = use["defined_predicate"]
        _auth()._text(symbol, "defined predicate identity")
        definition_ir = by_id[definition]["canonical_ir"]
        node, binders = definition_ir["typed_expression"]["root"], []
        while node["kind"] == "forall":
            binders.extend(binder["name"] for binder in node["binders"])
            node = node["arguments"][0]
        _need(node["kind"] == "iff" and node["arguments"][0]["kind"] == "predicate",
              "supported definition must universally bind a predicate equivalence")
        left = node["arguments"][0]
        _need(left["symbol"] == symbol and [argument["symbol"] for argument in left["arguments"]] == binders,
              "defined predicate must apply to the complete ordered definition binders")
        definition_roles = next(row["roles"] for row in definition_ir["argument_roles"] if row["symbol"] == symbol)
        norm_ir = by_id[target]["canonical_ir"]
        norm_roles = [row["roles"] for row in norm_ir["argument_roles"] if row["symbol"] == symbol]
        _need(norm_roles == [definition_roles], "governing predicate arity or ordered argument roles differ")
        actual_paths = []
        for path in by_id[target]["typed_paths"]:
            selected = norm_ir["typed_expression"]
            for token in path.split("/")[1:]:
                selected = selected[int(token)] if type(selected) is list else selected[token]
            if type(selected) is dict and selected.get("kind") == "predicate" and selected.get("symbol") == symbol:
                actual_paths.append(path)
        paths = use["target_typed_paths"]
        _need(type(paths) is list and bool(paths) and paths == actual_paths,
              "complete ordered predicate definition-use targets required")
        for path in paths:
            _need((target, path) not in governed, "competing governing definitions for one typed use remain unresolved")
            governed.add((target, path))
        _reviewed_refs(use["evidence_refs"])
        applied.add((definition, target))
        distinct.add(target)
    _need(distinct == norms and {key for key, _ in applied} == definitions,
          "every normative use and governing definition must be reviewed")
    refs = body["cross_references"]
    _need(type(refs) is list and len(refs) <= 64, "bounded complete cross-reference inventory required")
    for ref in refs:
        _keys(ref, {"from_unit_id", "dependency_artifact_id", "dependency_sha256", "version", "evidence_refs"},
              "versioned reviewed cross reference")
        _need(ref["from_unit_id"] in by_id, "cross reference names another source unit")
        auth._id(ref["dependency_artifact_id"], "cross-reference dependency")
        _sha(ref["dependency_sha256"], "cross-reference dependency version")
        auth._text(ref["version"], "cross-reference version")
        _reviewed_refs(ref["evidence_refs"])
        key = ref["dependency_artifact_id"]
        _need(key not in artifacts or artifacts[key] == ref["dependency_sha256"], "conflicting dependency versions")
        artifacts[key] = ref["dependency_sha256"]
    return units, artifacts, declared


def prepare_reviewed_norm_admission_v2(declaration, *, expected_declaration_sha256,
        source_inputs, relational_inputs, dependency_manifest, expected_manifest_sha256):
    """Replay a complete meaning proposal; preparation grants no authority.

    Full source geometry and the existing strict typed relational profile are
    checked mechanically. Meaning, governing context and dependency completeness
    are explicit review subjects, not facts inferred from hashes or compilation.
    """
    original = dict(declaration=declaration, expected_declaration_sha256=expected_declaration_sha256,
        source_inputs=source_inputs, relational_inputs=relational_inputs,
        dependency_manifest=dependency_manifest, expected_manifest_sha256=expected_manifest_sha256)
    detached, commitment = norm._snapshot(original)
    pins = _reviewed_pins()
    _sha(expected_declaration_sha256, "complete reviewed declaration")
    body = detached["declaration"]
    _need(norm_content_adjudication_sha256(body) == expected_declaration_sha256, "complete reviewed declaration pin differs")
    units, artifacts, _ = _reviewed_body(body, detached["source_inputs"], detached["relational_inputs"])
    dependencies = _reviewed_owners()[-1]
    manifest = dependencies.validate_dependency_manifest(detached["dependency_manifest"],
        expected_manifest_sha256=expected_manifest_sha256)
    root = body["component_id"]
    _need(root not in artifacts, "component and dependency artifact identities must differ")
    artifacts = {root: expected_declaration_sha256, **artifacts}
    _need({row["artifact_id"]: row["artifact_sha256"] for row in manifest["artifacts"]} == artifacts,
          "source, IR or cross-reference dependency version omitted or changed")
    reachable, _ = _auth()._closure(manifest, root, expected_declaration_sha256)
    _need(set(reachable) == set(artifacts) and not manifest["missing_dependencies"] and not manifest["cycles"],
          "complete acyclic reviewed dependency closure required")
    subject = {"schema": REVIEWED_SUBJECT_SCHEMA, "graph_id": root,
        "graph_sha256": expected_declaration_sha256, "declaration_sha256": expected_declaration_sha256,
        "ast_sha256": norm_content_adjudication_sha256([{key: row[key] for key in
            ("unit_id", "canonical_ir", "argument_roles", "relational_profile")} for row in units]),
        "source_binding_sha256": norm_content_adjudication_sha256(body["units"]),
        "scope_id": body["governing_context"]["jurisdiction"], "context_slot_ids": list(REVIEWED_SLOTS),
        "context_packet_sha256": norm_content_adjudication_sha256({"declaration": body, "producer_pins": pins}),
        "dependency_manifest_sha256": expected_manifest_sha256, "required_dependency_ids": reachable}
    _reviewed_subject(subject, manifest)
    report = {"schema": "legal-reviewed-norm-preparation/v2", "profile": REVIEWED_PROFILE,
        "declaration_sha256": expected_declaration_sha256, "declaration": body, "subject": subject,
        "units": units, "producer_pins": pins, "semantic_use_eligible": False,
        "training_mask": 0, "evaluation_gold_mask": 0, "Lean_admitted": False, "proof_authority": False}
    return _reviewed_finish(original, detached, commitment, pins, report)


def assess_reviewed_norm_admission_v2(preparation, registry, policy, reviews, *,
        expected_preparation_sha256, preparation_inputs, expected_registry_sha256,
        expected_policy_sha256, expected_reviews_sha256, at_time_utc,
        observed_artifact_sha256s, observed_pins, evidence_artifacts):
    """Admit declared semantic uses only after fresh full replay and review.

    The caller supplies independent trust pins and current observations. This
    API authenticates neither human competence nor the freshness of an external
    clock/registry. It never establishes formal assumptions or proof/corpus entry.
    """
    original = dict(preparation=preparation, registry=registry, policy=policy, reviews=reviews,
        expected_preparation_sha256=expected_preparation_sha256, preparation_inputs=preparation_inputs,
        expected_registry_sha256=expected_registry_sha256, expected_policy_sha256=expected_policy_sha256,
        expected_reviews_sha256=expected_reviews_sha256, at_time_utc=at_time_utc,
        observed_artifact_sha256s=observed_artifact_sha256s, observed_pins=observed_pins, evidence_artifacts=evidence_artifacts)
    detached, commitment = norm._snapshot(original)
    pins = _reviewed_pins()
    _sha(expected_preparation_sha256, "complete reviewed preparation")
    _need(norm_content_adjudication_sha256(detached["preparation"]) == expected_preparation_sha256,
          "independently pinned reviewed preparation differs")
    prepared = prepare_reviewed_norm_admission_v2(**detached["preparation_inputs"])
    _need(norm._same(detached["preparation"], prepared), "reviewed preparation differs from complete original replay")
    body, subject, auth = prepared["declaration"], prepared["subject"], _auth()
    domain = auth._ReviewDomain(REVIEWED_SUBJECT_SCHEMA, REVIEWED_CLAIM_SCHEMA, REVIEWED_ACTION,
        REVIEWED_AUDIENCE, "legal-reviewed-norm-authority-assessment/v2", _reviewed_subject, len(REVIEWED_SLOTS))
    authority = auth._assess_reviews(subject, detached["registry"], detached["policy"], detached["reviews"],
        detached["preparation_inputs"]["dependency_manifest"], domain=domain,
        **{key: detached[key] for key in ("expected_registry_sha256", "expected_policy_sha256", "expected_reviews_sha256",
            "at_time_utc", "observed_artifact_sha256s", "observed_pins", "evidence_artifacts")},
        expected_subject_sha256=auth.digest(subject), expected_manifest_sha256=subject["dependency_manifest_sha256"])
    blockers = [] if authority["review_prerequisites_satisfied_under_selected_trust"] else [
        item for item in authority["blockers"] if item not in
        ("downstream_semantic_validation_required", "downstream_Lean_kernel_admission_required")]
    keys = {key["key_id"]: key for key in detached["registry"]["keys"]}
    current = [claim for claim in detached["reviews"] if any(row["review_id"] == claim["review_id"]
        and row["status"] == "authenticated" for row in authority["reviews"])]
    if not _distinct_pair(current, keys):
        blockers.append("independent_review_roles_missing")
    body_ref = {"artifact_id": body["component_id"], "sha256": prepared["declaration_sha256"]}
    evidence = detached["evidence_artifacts"]
    if evidence.get(body["component_id"]) != norm._wire(body):
        blockers.append("complete_signed_declaration_evidence_missing_or_changed")
    declared = auth._time(body["declared_at_utc"])
    if declared > auth._time(at_time_utc) or any(auth._time(claim["issued_at_utc"]) < declared for claim in detached["reviews"]):
        blockers.append("review_or_evaluation_predates_declaration")
    excluded_ids = {body["component_id"]}
    excluded_hashes = {prepared["declaration_sha256"], expected_preparation_sha256,
        expected_registry_sha256, expected_policy_sha256, expected_reviews_sha256}
    for unit in body["units"]:
        excluded_ids.update((unit["source_artifact_id"], unit["ir_artifact_id"]))
        excluded_hashes.update((unit["source_version"]["raw_artifact"]["sha256"],
            unit["source_version"]["extracted_view"]["sha256"], unit["occurrence"]["span_sha256"],
            norm_content_adjudication_sha256(unit["source_version"]),
            norm_content_adjudication_sha256(unit["occurrence"]),
            unit["relational_request_sha256"],
            detached["preparation_inputs"]["relational_inputs"][unit["unit_id"]]["expected_report_sha256"]))
    excluded_ids.update(ref["dependency_artifact_id"] for ref in body["cross_references"])
    excluded_hashes.update(ref["dependency_sha256"] for ref in body["cross_references"])
    excluded_hashes.update(auth.digest(claim) for claim in detached["reviews"])
    for claim in detached["reviews"]:
        key = keys.get(claim["key_id"])
        if any(claim["principal_id"] == actor["principal_id"] or claim["signer_did"] == actor["signer_did"]
               or key is not None and (key["principal_id"] == actor["principal_id"]
                   or key["signer_did"] == actor["signer_did"] or key["public_key_hex"] == actor["public_key_hex"])
               for actor in body["source_actors"]):
            blockers.append("reviewer_reuses_source_or_IR_producer_identity")
        for obligation in claim["context_closure"]["obligations"]:
            refs = obligation["evidence_refs"]
            independent = [ref for ref in refs if ref["artifact_id"] not in excluded_ids
                and ref["sha256"] not in excluded_hashes]
            if obligation["disposition"] != "resolved_by_evidence" or body_ref not in refs or not independent:
                blockers.append("whole_body_and_independent_process_evidence_required_for_each_review_obligation")
    for item in body["definition_uses"] + body["cross_references"]:
        for ref in item["evidence_refs"]:
            raw = evidence.get(ref["artifact_id"])
            if ref["artifact_id"] in excluded_ids or ref["sha256"] in excluded_hashes or type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
                blockers.append("definition_or_cross_reference_process_evidence_missing_or_changed")
    eligible = not blockers
    statutory = body["provenance_kind"] == "statutory"
    report = {"schema": "legal-reviewed-norm-admission-assessment/v2", "profile": REVIEWED_PROFILE,
        "declaration_sha256": prepared["declaration_sha256"], "preparation_sha256": expected_preparation_sha256,
        "provenance_kind": body["provenance_kind"], "semantic_use_eligible": eligible,
        "permitted_uses": body["permitted_uses"] if eligible else [], "blockers": sorted(set(blockers)),
        "units": prepared["units"], "producer_pins": pins, "review_authority": authority,
        "training_mask": int(eligible and statutory and "training" in body["permitted_uses"]),
        "evaluation_gold_mask": int(eligible and statutory and "heldout_evaluation" in body["permitted_uses"]),
        "fixture_only": not statutory, "eligibility_scope": "declared semantic uses under supplied current trust and observations",
        "formal_assumptions": body["assumptions"], "formal_assumptions_proved": False,
        "human_identity_and_competence_verified": False, "global_reviewer_cohort_verified": False,
        "evaluation_clock_authenticated": False, "registry_freshness_authenticated": False,
        "Lean_admitted": False, "proof_authority": False, "semantic_graph_admitted": False,
        "corpus_admitted": False, "training_executed": False}
    return _reviewed_finish(original, detached, commitment, pins, report)


def validate_reviewed_norm_admission_v2(report, *args, expected_report_sha256, **kwargs):
    """Recompute eligibility from complete original inputs, never saved flags."""
    original = dict(report=report, args=list(args), kwargs=kwargs)
    detached, commitment = norm._snapshot(original)
    pins = _reviewed_pins()
    _sha(expected_report_sha256, "reviewed admission report")
    _need(norm_content_adjudication_sha256(detached["report"]) == expected_report_sha256,
          "independent reviewed admission report pin differs")
    expected = assess_reviewed_norm_admission_v2(*detached["args"], **detached["kwargs"])
    _need(norm._same(expected, detached["report"]), "reviewed admission report differs from complete current replay")
    return _reviewed_finish(original, detached, commitment, pins, expected)


__all__ += ["prepare_reviewed_norm_admission_v2", "assess_reviewed_norm_admission_v2",
    "validate_reviewed_norm_admission_v2", "REVIEWED_PROFILE", "REVIEWED_DECLARATION_SCHEMA",
    "REVIEWED_SUBJECT_SCHEMA", "REVIEWED_CLAIM_SCHEMA", "REVIEWED_ACTION", "REVIEWED_AUDIENCE", "REVIEWED_SLOTS"]
