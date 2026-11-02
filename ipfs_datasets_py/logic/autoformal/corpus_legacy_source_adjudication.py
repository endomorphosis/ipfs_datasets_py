"""Common legacy source adjudication declarations, without source decisions.

Replays every typed response, then authenticates a separate fixed declaration
domain through the existing review verifier. Original evidence and conflicts
remain intact. No signer, policy, clock, occurrence selection, legal meaning or
training authority is supplied here. Historical complete-parent APIs are not
imported as though they accepted the legacy profile.
"""
from __future__ import annotations

import hashlib
import json

from . import corpus_contracts as contracts
from . import corpus_legacy_source_join as joins
from . import corpus_legacy_source_review as source
from . import corpus_legacy_source_responses as responses
from . import legal_graph_review as auth

PROFILE = "explicit-dual-role-legacy-source-adjudication/v1"
DECLARATION_SCHEMA = "legal-corpus-legacy-source-adjudication-declaration/v1"
TEMPLATE_SCHEMA = "legal-corpus-legacy-source-adjudication-template/v1"
CLAIM_SCHEMA = "legal-corpus-legacy-source-adjudication-signed-claim/v1"
ACTION = "record_legacy_source_adjudication_declaration/v1"
AUDIENCE = "legal-autoformalization-legacy-source-adjudication/v1"
ASSESSMENT_SCHEMA = "legal-corpus-legacy-source-adjudication-authority-assessment/v1"
REPORT_SCHEMA = "legal-corpus-legacy-source-adjudication-assessment/v1"
FALSE_FLAGS = {**responses.FALSE_FLAGS, **dict.fromkeys(("adjudicated_source_meaning_verified",
    "source_selection_applied", "adjudicator_human_independence_verified"), False)}
_REPLAY_FIELDS = responses._SOURCE_FIELDS | {"response_bindings", "expected_response_bindings_sha256"}
_DOMAIN = auth._ReviewDomain(source.SUBJECT_SCHEMA, CLAIM_SCHEMA, ACTION, AUDIENCE,
                             ASSESSMENT_SCHEMA, source._subject, 9)


def _fail(message):
    raise contracts.CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return auth.digest(value)


def _same(left, right):
    return auth.wire(left) == auth.wire(right)


def _ref(record):
    return responses._ref(record)


def _seal(schema, **values):
    return contracts.seal_record({"schema": schema, "profile": PROFILE, **values,
        "view": "candidate", **FALSE_FLAGS, **source._UNSELECTED})


def _evidence(values):
    if (type(values) is not dict or len(values) > auth.MAX_EVIDENCE
            or any(type(key) is not str or type(raw) is not bytes for key, raw in values.items())
            or sum(map(len, values.values())) > auth.MAX_BYTES):
        _fail("bounded immutable adjudication evidence required")
    for key in values:
        auth._id(key, "evidence identity")
    return dict(values)


def _replay_inputs(values):
    """Detach existing bounded byte/JSON inputs; no ambient source authority."""
    contracts.require_keys(values, _REPLAY_FIELDS, "complete typed response replay inputs")
    rows = values["paired_row_bytes"]
    if (type(rows) is not list or len(rows) > joins.MAX_ROWS
            or any(type(raw) is not bytes for raw in rows)
            or sum(map(len, rows)) > joins.MAX_PAIRED_INPUT_BYTES):
        _fail("bounded original paired row bytes required")
    for name, cap in (("join_bytes", contracts.MAX_RECORD_BYTES),
                      ("producer_receipt_bytes", joins.MAX_RECEIPT_BYTES)):
        raw = values[name]
        if name == "producer_receipt_bytes" and raw is None:
            continue
        if type(raw) is not bytes or len(raw) > cap:
            _fail("bounded original source bytes required")
    evidence = _evidence(values["evidence_artifacts"])
    byte_fields = {"join_bytes", "producer_receipt_bytes", "paired_row_bytes", "evidence_artifacts"}
    detached = json.loads(auth.wire({key: value for key, value in values.items() if key not in byte_fields}))
    return {**detached, "join_bytes": values["join_bytes"], "producer_receipt_bytes": values["producer_receipt_bytes"],
            "paired_row_bytes": list(rows), "evidence_artifacts": evidence}


def _context(preparation, typed_assessment, registry, policy, reviews, expected_sha256, response_inputs):
    contracts.require_sha256(expected_sha256, "complete typed assessment SHA256")
    offered = json.loads(auth.wire(typed_assessment))
    if _digest(offered) != expected_sha256:
        _fail("independently pinned typed assessment differs")
    preparation = source._detach(preparation)
    registry, policy, reviews = (json.loads(auth.wire(value)) for value in (registry, policy, reviews))
    inputs = _replay_inputs(response_inputs)
    checked = responses.validate_legacy_source_responses(offered, preparation, registry, policy, reviews, **inputs)
    ordinal = inputs["request_ordinal"]
    return (preparation, checked, registry, policy, reviews, inputs,
            preparation["requests"][ordinal], preparation["subjects"][ordinal],
            preparation["dependency_manifests"][ordinal])


def _declaration(request, subject, typed, original_reviews, decisions, declared_at_utc):
    declared = auth._time(declared_at_utc)
    if (declared < auth._time(typed["raw_source_assessment"]["evaluation_time_utc"])
            or any(declared < auth._time(row["issued_at_utc"]) for row in original_reviews)):
        _fail("adjudication declaration predates its considered source review")
    decisions = contracts.clone_json(decisions)
    if type(decisions) is not list or len(decisions) != 9:
        _fail("complete nine ordered adjudication choices required")
    by_cid = {row["record_cid"]: row for row in typed["answer_variants"]}
    for choice, slot in zip(decisions, typed["pending_questions"], strict=True):
        contracts.require_keys(choice, {"slot_id", "decision", "selected_variant_ref", "rationale", "evidence_refs"},
                               "declared source adjudication choice")
        if choice["slot_id"] != slot["slot_id"] or choice["decision"] not in ("select_existing_variant", "unresolved"):
            _fail("exact supported original adjudication choice required")
        contracts.require_text(choice["rationale"], "adjudication rationale", max_bytes=8192)
        responses._refs(choice["evidence_refs"])
        ref = choice["selected_variant_ref"]
        if choice["decision"] == "unresolved":
            if ref is not None:
                _fail("unresolved adjudication cannot select a variant")
        else:
            if (type(ref) is not dict or not any(_same(ref, item) for item in slot["answer_variant_refs"])
                    or not choice["evidence_refs"]):
                _fail("selected adjudication needs an existing variant and exact evidence")
            selected = by_cid.get(ref.get("record_cid"))
            if (selected is None or not _same(_ref(selected), ref) or selected["slot_id"] != slot["slot_id"]
                    or selected["answer"]["disposition"] not in ("evidence_declared", "not_applicable")
                    or not selected["respondents"]):
                _fail("unresolved or unauthenticated variant cannot be selected")
    return _seal(DECLARATION_SCHEMA, request_ref=_ref(request), subject_ref=_ref(subject),
        preparation_manifest_sha256=typed["preparation_manifest_sha256"],
        typed_assessment_sha256=_digest(typed), request_ordinal=request["queue_ordinal"],
        source_binding_sha256=request["source_binding_sha256"], questions_sha256=request["questions_sha256"],
        pending_slot_refs=[_ref(row) for row in typed["pending_questions"]],
        considered_answer_variant_refs=[_ref(row) for row in typed["answer_variants"]],
        considered_occurrence_proposals_sha256=_digest(typed["occurrence_proposals"]),
        declared_at_utc=declared_at_utc, decisions=decisions,
        deferred_review_slot_ids=request["deferred_review_slot_ids"],
        status="declared_unauthenticated_source_adjudication")


def record_legacy_source_adjudication_declaration(preparation, typed_assessment, source_registry,
        source_policy, source_reviews, decisions, *, expected_typed_assessment_sha256, declared_at_utc, response_inputs):
    """Record explicit supplied choices after full replay; no signature or action."""
    decisions = contracts.clone_json(decisions)
    context = _context(preparation, typed_assessment, source_registry, source_policy, source_reviews,
                       expected_typed_assessment_sha256, response_inputs)
    _, typed, _, _, reviews, _, request, subject, _ = context
    return _declaration(request, subject, typed, reviews, decisions, declared_at_utc)


def validate_legacy_source_adjudication_declaration(record, *args, **kwargs):
    checked = contracts.clone_json(record)
    expected = record_legacy_source_adjudication_declaration(*args, **kwargs)
    if not _same(checked, expected):
        _fail("source adjudication declaration differs from exact regeneration")
    return checked


def prepare_legacy_source_adjudication_template(preparation, typed_assessment, source_registry,
        source_policy, source_reviews, *, expected_typed_assessment_sha256, response_inputs):
    """Retain all choices as blank fields, not invented unresolved decisions."""
    context = _context(preparation, typed_assessment, source_registry, source_policy, source_reviews,
                       expected_typed_assessment_sha256, response_inputs)
    _, typed, _, _, _, _, request, subject, _ = context
    return _seal(TEMPLATE_SCHEMA, request_ref=_ref(request), subject_ref=_ref(subject),
        typed_assessment_sha256=_digest(typed), pending_slot_refs=[_ref(row) for row in typed["pending_questions"]],
        considered_answer_variant_refs=[_ref(row) for row in typed["answer_variants"]],
        declaration={"declared_at_utc": None, "decisions": [{"slot_id": row["slot_id"],
            "decision": None, "selected_variant_ref": None, "rationale": None, "evidence_refs": []}
            for row in typed["pending_questions"]]}, deferred_review_slot_ids=request["deferred_review_slot_ids"],
        status="blank_unsubmitted_adjudication_template")


def _content(identity, expected_sha256, evidence, claims, request, subject, typed, original_reviews):
    if identity is None:
        return None, []
    try:
        raw = evidence.get(identity)
        record = contracts.load_record_bytes(raw, expected_sha256=expected_sha256)
        expected = _declaration(request, subject, typed, original_reviews, record["decisions"], record["declared_at_utc"])
        if not _same(record, expected):
            _fail("adjudication_source_or_considered_population_differs")
        by_cid = {row["record_cid"]: row for row in typed["answer_variants"]}
        obligations, unresolved = [], []
        common_ref = {"artifact_id": identity, "sha256": expected_sha256}
        for choice in record["decisions"]:
            if choice["decision"] == "unresolved":
                disposition = "open"
                unresolved.append(choice["slot_id"])
            else:
                answer = by_cid[choice["selected_variant_ref"]["record_cid"]]["answer"]
                disposition = responses.DISPOSITIONS[answer["disposition"]]
            obligations.append({"slot_id": choice["slot_id"], "disposition": disposition, "evidence_refs": [common_ref]})
            for ref in choice["evidence_refs"]:
                body = evidence.get(ref["artifact_id"])
                if ref["artifact_id"] == identity or body is None or _sha(body) != ref["sha256"]:
                    _fail("adjudication_supporting_evidence_missing_changed_or_self_referential")
        closure = {"status": "open" if unresolved else "declared_complete", "obligations": obligations, "unresolved": unresolved}
        if any(not _same(claim["context_closure"], closure) for claim in claims):
            _fail("adjudication_signed_choices_or_common_body_differ")
        return record, []
    except (ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
        return None, [str(error)[:512] or "invalid_adjudication_content"]


def assess_legacy_source_adjudication(preparation, typed_assessment, source_registry, source_policy,
        source_reviews, adjudication_registry, adjudication_policy, adjudication_reviews, *,
        expected_typed_assessment_sha256, response_inputs, declaration_artifact_id, expected_declaration_sha256,
        expected_adjudication_registry_sha256, expected_adjudication_policy_sha256,
        expected_adjudication_reviews_sha256, at_time_utc, observed_artifact_sha256s, observed_pins, evidence_artifacts):
    """Replay all responses; check common declarations under separate authority.

    The original source authority is checked again at the supplied adjudication
    time with the supplied current dependency observations. These checks operate
    under explicit registry/revocation snapshots and an unauthenticated caller
    clock. A positive prerequisite result authenticates declarations, not law.
    """
    adjudication_registry, adjudication_policy, adjudication_reviews, observed_artifact_sha256s, observed_pins = (
        json.loads(auth.wire(value)) for value in (adjudication_registry, adjudication_policy,
            adjudication_reviews, observed_artifact_sha256s, observed_pins))
    authority_keys, _ = auth._trust(adjudication_registry, adjudication_policy,
        expected_adjudication_registry_sha256, expected_adjudication_policy_sha256, action=ACTION, audience=AUDIENCE)
    evaluation = auth._time(at_time_utc)
    contracts.require_sha256(expected_adjudication_reviews_sha256, "adjudication reviews SHA256")
    if (type(adjudication_reviews) is not list or len(adjudication_reviews) > auth.MAX_REVIEWS
            or _digest(adjudication_reviews) != expected_adjudication_reviews_sha256):
        _fail("independently pinned complete adjudication review population differs")
    evidence = _evidence(evidence_artifacts)
    if declaration_artifact_id is None:
        if expected_declaration_sha256 is not None or adjudication_reviews:
            _fail("absent declaration requires absent pin and no authority claims")
    else:
        auth._id(declaration_artifact_id, "common declaration identity")
        contracts.require_sha256(expected_declaration_sha256, "common declaration SHA256")
        body = evidence.get(declaration_artifact_id)
        if body is not None and len(body) > contracts.MAX_RECORD_BYTES:
            _fail("common declaration exceeds corpus record bound")
    total = sum(len(auth.wire(value)) for value in (adjudication_registry, adjudication_policy, adjudication_reviews))
    if total + sum(map(len, evidence.values())) > auth.MAX_BYTES:
        _fail("aggregate adjudication input budget exceeded before source replay")
    context = _context(preparation, typed_assessment, source_registry, source_policy, source_reviews,
                       expected_typed_assessment_sha256, response_inputs)
    _, typed, source_registry, source_policy, source_reviews, original_inputs, request, subject, manifest = context
    common = dict(expected_subject_sha256=_digest(subject), expected_manifest_sha256=manifest["manifest_sha256"],
        at_time_utc=at_time_utc, observed_artifact_sha256s=observed_artifact_sha256s, observed_pins=observed_pins)
    current_source = auth._assess_reviews(subject, source_registry, source_policy, source_reviews, manifest,
        domain=source._DOMAIN, expected_registry_sha256=original_inputs["expected_registry_sha256"],
        expected_policy_sha256=original_inputs["expected_policy_sha256"],
        expected_reviews_sha256=original_inputs["expected_reviews_sha256"],
        evidence_artifacts=original_inputs["evidence_artifacts"], **common)
    authority = auth._assess_reviews(subject, adjudication_registry, adjudication_policy, adjudication_reviews,
        manifest, domain=_DOMAIN, expected_registry_sha256=expected_adjudication_registry_sha256,
        expected_policy_sha256=expected_adjudication_policy_sha256,
        expected_reviews_sha256=expected_adjudication_reviews_sha256, evidence_artifacts=evidence, **common)
    for assessment, scope in ((current_source, "current_selected_legacy_source_review_authority_and_dependencies_only"),
                              (authority, "common_legacy_source_adjudication_declaration_authority_only")):
        assessment.pop("assessment_sha256")
        assessment["coverage_scope"] = scope
        assessment["assessment_sha256"] = _digest(assessment)
    record, content_blockers = _content(declaration_artifact_id, expected_declaration_sha256, evidence,
        adjudication_reviews, request, subject, typed, source_reviews)
    extra = []
    source_keys = {key["key_id"]: key for key in source_registry["keys"]}
    principals = {row["principal_id"] for row in source_reviews}
    dids = {row["signer_did"] for row in source_reviews}
    public_keys = {source_keys[row["key_id"]]["public_key_hex"] for row in source_reviews if row["key_id"] in source_keys}
    if any(row["principal_id"] in principals for row in adjudication_reviews):
        extra.append("adjudicator_is_a_supplied_original_reviewer")
    if any(row["signer_did"] in dids for row in adjudication_reviews):
        extra.append("adjudicator_reuses_an_original_reviewer_did")
    if any(authority_keys.get(row["key_id"], {}).get("public_key_hex") in public_keys for row in adjudication_reviews):
        extra.append("adjudicator_reuses_an_original_reviewer_public_key")
    if evaluation < auth._time(typed["raw_source_assessment"]["evaluation_time_utc"]):
        extra.append("adjudication_evaluation_predates_considered_source_assessment")
    if record is not None:
        declared = auth._time(record["declared_at_utc"])
        if declared > evaluation:
            extra.append("adjudication_declared_after_evaluation")
        if any(auth._time(row["issued_at_utc"]) < declared for row in adjudication_reviews):
            extra.append("authority_claim_predates_common_declaration")
    if current_source["trust_mode"] != "external_pinned_trust":
        extra.append("original_source_review_production_trust_unavailable")
    if current_source["authenticated_evidence_count"] != len(source_reviews):
        extra.append("original_source_reviews_not_currently_authenticated")
    if "required_dependency_closure_not_current" in current_source["blockers"]:
        extra.append("original_source_dependency_closure_not_current")
    valid_ids = {row["review_id"] for row in typed["response_results"] if row["authenticated_typed_content"]}
    if len(valid_ids) != len(source_reviews):
        extra.append("original_typed_content_not_fully_authenticated")
    current_rows = [row for row in current_source["reviews"] if row["status"] == "authenticated" and row["review_id"] in valid_ids]
    if not any(a["role"] == "legal_review" and b["role"] == "formal_review"
               and a["principal_id"] != b["principal_id"] and a["key_id"] != b["key_id"]
               for a in current_rows for b in current_rows):
        extra.append("original_authenticated_typed_distinct_source_roles_missing")
    prerequisites = (record is not None and not content_blockers and not extra
                     and authority["review_prerequisites_satisfied_under_selected_trust"])
    selected = 0 if record is None else sum(row["decision"] == "select_existing_variant" for row in record["decisions"])
    report = {"schema": REPORT_SCHEMA, "profile": PROFILE, "request_ref": _ref(request),
        "expected_typed_assessment_sha256": expected_typed_assessment_sha256,
        "original_typed_assessment": typed, "declaration_artifact_ref": None if declaration_artifact_id is None else
            {"artifact_id": declaration_artifact_id, "sha256": expected_declaration_sha256},
        "observed_declaration_sha256": None if declaration_artifact_id not in evidence else _sha(evidence[declaration_artifact_id]),
        "declaration_record": record, "declaration_content_status": "absent" if declaration_artifact_id is None else
            "valid_declared_content" if record is not None else "rejected", "content_blockers": content_blockers,
        "authority_assessment": authority, "current_source_authority_assessment": current_source,
        "separation_and_chronology_blockers": sorted(set(extra)),
        "authority_prerequisites_satisfied_under_selected_trust": prerequisites,
        "pending_slots": [{"slot_id": row["slot_id"], "decision_applied": False,
            "declared_decision": None if record is None else record["decisions"][index]["decision"],
            "status": "pending_source_decision_not_applied"} for index, row in enumerate(typed["pending_questions"])],
        "deferred_review_slot_ids": request["deferred_review_slot_ids"], "original_contexts_remain_required_unavailable": True,
        "counts": {"declaration_bodies": int(declaration_artifact_id is not None),
            "authenticated_authority_claims": authority["authenticated_evidence_count"],
            "declared_selected_slots": selected, "unresolved_or_absent_slots": 9 - selected,
            "source_decisions_applied": 0, "adjudications_applied": 0},
        "evaluation_clock_authenticated": False, "registry_snapshot_currentness_authenticated": False,
        "view": "candidate", **FALSE_FLAGS, **source._UNSELECTED}
    report["assessment_sha256"] = _digest(report)
    return json.loads(auth.wire(report))


def validate_legacy_source_adjudication(report, *args, **kwargs):
    checked = json.loads(auth.wire(report))
    expected = assess_legacy_source_adjudication(*args, **kwargs)
    if not _same(checked, expected):
        _fail("legacy source adjudication assessment differs from exact regeneration")
    return checked


__all__ = ["record_legacy_source_adjudication_declaration", "validate_legacy_source_adjudication_declaration",
           "prepare_legacy_source_adjudication_template", "assess_legacy_source_adjudication",
           "validate_legacy_source_adjudication"]
