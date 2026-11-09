"""Replay legacy stored-source joins into a distinct source-review domain.

All alternatives and complete stored sections survive. This profile supplies
review requests and authenticates separately supplied evidence declarations;
it does not recover historical character selection, authenticate an official
edition, interpret answers, select legal meaning, or admit training targets.
There is no file/network/model/clock access or default trust in this owner.
"""
from __future__ import annotations

import hashlib
import json

from . import corpus_contracts as contracts
from . import corpus_legacy_source_join as joins
from . import corpus_source_review as questions
from . import corpus_source_review_packets as wording
from . import legal_graph_dependencies as dependencies
from . import legal_graph_review as review

PROFILE = "complete-legacy-stored-source-candidate-review/v1"
MANIFEST_SCHEMA = "legal-corpus-legacy-source-review-manifest/v1"
REQUEST_SCHEMA = "legal-corpus-legacy-source-review-request/v1"
SUBJECT_SCHEMA = "legal-corpus-legacy-source-review-subject/v1"
CLAIM_SCHEMA = "legal-corpus-legacy-source-review-signed-claim/v1"
ACTION = "record_legacy_source_context_review_evidence/v1"
AUDIENCE = "legal-autoformalization-legacy-source-context-review/v1"
ASSESSMENT_SCHEMA = "legal-corpus-legacy-source-review-assessment/v1"
MAX_COLLECTION_BYTES = review.MAX_BYTES
FALSE_FLAGS = {
    **review.FALSE_AUTHORITY,
    **dict.fromkeys(("original_producer_occurrence_attested", "source_authenticity_verified",
                    "official_html_view_mapping_verified", "source_review_completed",
                    "source_review_decisions_applied", "semantic_graph_verified"), False),
}
_UNSELECTED = {"selected_occurrence": None, "governing_source": None,
               "selected_meaning": None}
_BUNDLE_KEYS = {"manifest", "source_sections", "requests", "subjects", "dependency_manifests"}
_SUBJECT_FIELDS = {
    "profile", "review_request_cid", "graph_id", "graph_sha256", "ast_sha256",
    "scope_id", "context_slot_ids", "deferred_review_slot_ids", "source_binding_sha256",
    "hash_recipes", "dependency_manifest_sha256", "required_dependency_ids",
    "dependency_artifacts", "view", *FALSE_FLAGS, *_UNSELECTED,
}


def _fail(message):
    raise contracts.CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return review.digest(value)


def _record(schema, **values):
    return contracts.seal_record({"schema": schema, "profile": PROFILE, **values,
        "view": "candidate", **FALSE_FLAGS, **_UNSELECTED})


def _ref(value):
    return {"record_cid": value["record_cid"], "sha256": _digest(value)}


def _dependency_manifest(request, ledger, join_sha256):
    artifacts, seen = [], {}

    def add(identity, sha256):
        if identity in seen:
            if seen[identity] != sha256:
                _fail("conflicting review dependency identity")
            return
        seen[identity] = sha256
        artifacts.append({"artifact_id": identity, "artifact_sha256": sha256,
                          "dependency_pins": {kind: [] for kind in dependencies.PIN_KINDS}})

    def record(value):
        add(value["record_cid"], _digest(value))

    record(request)
    add("legacy-review-join:sha256:" + join_sha256, join_sha256)
    add("legacy-review-questions:sha256:" + request["questions_sha256"], request["questions_sha256"])
    row = request["original_row"]
    add("legacy-review-paired-row:sha256:" + row["row_sha256"], row["row_sha256"])
    if ledger["producer_receipt"] is not None:
        pin = ledger["producer_receipt"]["sha256"]
        add("legacy-review-producer-receipt:sha256:" + pin, pin)
    # Keep the complete declared source population, including zero-hit rows.
    # Parquet custody is a declared parent dependency, not reread by this API.
    for section in ledger["source_sections"]:
        record(section["source_version"])
        for key in ("artifact_sha256", "text_sha256"):
            pin = section["provenance"][key]
            add("legacy-review-source:" + key + ":sha256:" + pin, pin)
        pin = _digest(section)
        add("legacy-review-complete-section:sha256:" + pin, pin)
    for candidate in row["candidates"]:
        record(candidate["source_occurrence"])
        record(candidate["context_declaration"])
    identities = [item["artifact_id"] for item in artifacts]
    return dependencies.build_dependency_manifest(artifacts,
        [{"dependent_id": identities[0], "dependency_id": child} for child in identities[1:]],
        expected_artifact_ids=identities)


def _build_subject(request, manifest):
    reachable, artifacts = review._closure(manifest, request["record_cid"], _digest(request))
    return _record(SUBJECT_SCHEMA, review_request_cid=request["record_cid"],
        graph_id=request["record_cid"], graph_sha256=_digest(request),
        ast_sha256=request["questions_sha256"], scope_id=request["review_scope_id"],
        context_slot_ids=request["context_slot_ids"],
        deferred_review_slot_ids=request["deferred_review_slot_ids"],
        source_binding_sha256=request["source_binding_sha256"],
        hash_recipes={
            "graph_id": "compatibility alias for legacy source-review request CID; no semantic graph",
            "graph_sha256": "FULL canonical sealed legacy source-review request SHA256; no graph interpretation",
            "ast_sha256": "canonical sixteen source/context/deferred questions SHA256; no native AST",
            "scope_id": "exact legacy join and paired observation review scope; no governing legal scope inferred",
        }, dependency_manifest_sha256=manifest["manifest_sha256"],
        required_dependency_ids=reachable, dependency_artifacts=artifacts)


def _subject(subject, manifest):
    """Fixed domain validator; the public wrapper first replays all source inputs."""
    checked = contracts.validate_record(subject, schema=SUBJECT_SCHEMA, fields=_SUBJECT_FIELDS)
    if checked["profile"] != PROFILE or checked["graph_id"] != checked["review_request_cid"]:
        _fail("legacy source-only review domain differs")
    active, deferred = checked["context_slot_ids"], checked["deferred_review_slot_ids"]
    if (type(active) is not list or len(active) != 9 or type(deferred) is not list or len(deferred) != 7
            or any(type(item) is not str for item in (*active, *deferred))
            or len(set((*active, *deferred))) != 16):
        _fail("complete distinct legacy review questions required")
    if (any(checked[key] is not False for key in FALSE_FLAGS)
            or any(checked[key] is not None for key in _UNSELECTED)):
        _fail("legacy review cannot select occurrences or claim authority")
    reachable, artifacts = review._closure(manifest, checked["graph_id"], checked["graph_sha256"])
    if checked["required_dependency_ids"] != reachable or checked["dependency_artifacts"] != artifacts:
        _fail("complete legacy review dependency closure differs")


def _detach(preparation):
    contracts.require_keys(preparation, _BUNDLE_KEYS, "legacy source-review preparation")
    for key in _BUNDLE_KEYS - {"manifest"}:
        cap = joins.MAX_SECTIONS if key == "source_sections" else joins.MAX_ROWS
        if type(preparation[key]) is not list or len(preparation[key]) > cap:
            _fail("complete bounded legacy source-review population required")
    raw = review.wire(preparation)
    if len(raw) > MAX_COLLECTION_BYTES:
        _fail("complete legacy source-review byte bound exceeded")
    return json.loads(raw)


def prepare_legacy_source_review_requests(join_bytes, paired_row_bytes, *,
        expected_join_sha256, **independent_join_inputs):
    """Regenerate a pinned join, then preserve every original row and candidate.

    Supply exactly the original ``build_legacy_source_join`` independent inputs.
    Input receipt hashes bind supplied bytes, not producer identity. Questions
    reuse the existing source-review vocabulary under a separate signing domain.
    Large producer receipts are replayed once; they are not review evidence
    bodies and are not embedded in each subject. Exceeding any bound refuses
    the entire preparation; nothing is truncated or selected automatically.
    """
    retained = contracts.load_record_bytes(join_bytes, expected_sha256=expected_join_sha256)
    ledger = joins.validate_legacy_source_join(retained, paired_row_bytes, **independent_join_inputs)
    binding = {"join_raw_sha256": expected_join_sha256, "join_raw_bytes": len(join_bytes),
        "join_record_cid": ledger["record_cid"], "join_canonical_sha256": _digest(ledger)}
    requests, subjects, manifests = [], [], []
    retained_bytes = len(review.wire(ledger["source_sections"]))
    for ordinal, row in enumerate(ledger["rows"]):
        unit = "legacy:" + ledger["record_cid"] + ":" + str(ordinal)
        slots = questions._questions(unit)
        for slot in slots:
            slot.update(prompt=wording.PROMPTS[slot["kind"]], answer=None)
        active = [slot["slot_id"] for slot in slots
                  if slot["assessment_scope"] == "source_context_evidence_declaration"]
        deferred = [slot["slot_id"] for slot in slots if slot["slot_id"] not in active]
        if len(active) != 9 or len(deferred) != 7:
            _fail("upstream review question contract changed")
        request = _record(REQUEST_SCHEMA, queue_ordinal=ordinal,
            review_unit_id=unit, review_scope_id=unit,
            unit_kind="legacy_paired_observation_all_stored_source_candidates",
            original_row=row, input_binding=binding,
            source_section_refs=[{"section_index": index, "sha256": _digest(section),
                                  "source_version_cid": section["source_version"]["record_cid"]}
                                 for index, section in enumerate(ledger["source_sections"])],
            source_binding_sha256=_digest({"input_binding": binding, "original_row": row,
                "expected_source_sections": ledger["expected_source_sections"]}),
            review_questions=slots, questions_sha256=_digest(slots),
            context_slot_ids=active, deferred_review_slot_ids=deferred,
            reviewer=None, reviewed_at_utc=None, reviewer_exposure=None,
            reviewer_independence=None, reviewer_role=None,
            present_day_occurrence_proposal=None,
            status="pending_independent_source_context_review",
            occurrence_selection_scope="present_day_proposal_and_historical_producer_attestation_are_distinct")
        manifest = _dependency_manifest(request, ledger, expected_join_sha256)
        requests.append(request)
        subjects.append(_build_subject(request, manifest))
        manifests.append(manifest)
        retained_bytes += sum(len(review.wire(item)) for item in (request, subjects[-1], manifest))
        if retained_bytes > MAX_COLLECTION_BYTES:
            _fail("complete legacy source-review byte bound exceeded during preparation")
    root = _record(MANIFEST_SCHEMA, input_binding=binding,
        source_section_sha256s=[_digest(section) for section in ledger["source_sections"]],
        request_refs=[_ref(item) for item in requests], subject_refs=[_ref(item) for item in subjects],
        dependency_manifest_sha256s=[item["manifest_sha256"] for item in manifests],
        counts={**ledger["counts"], "requests": len(requests), "active_questions": 9 * len(requests),
                "deferred_questions": 7 * len(requests), "submitted_reviews": 0, "selected_occurrences": 0},
        population_complete=True, coverage_scope="exact_supplied_legacy_join_population_only",
        source_coordinates="stored_text_plain_unicode_codepoint_and_utf8_half_open_ranges",
        response_content_adjudication_available=False)
    return _detach({"manifest": root, "source_sections": ledger["source_sections"],
        "requests": requests, "subjects": subjects, "dependency_manifests": manifests})


def validate_legacy_source_review_requests(preparation, *args, **kwargs):
    """Regenerate the full collection under independent original inputs."""
    checked = _detach(preparation)
    expected = prepare_legacy_source_review_requests(*args, **kwargs)
    if review.wire(checked) != review.wire(expected):
        _fail("legacy source-review preparation differs from exact regeneration")
    return checked


_DOMAIN = review._ReviewDomain(SUBJECT_SCHEMA, CLAIM_SCHEMA, ACTION, AUDIENCE,
                             ASSESSMENT_SCHEMA, _subject, 9)


class _SourceReviewPreparation:
    """Private immutable complete-preparation capability, never a public input."""
    __slots__ = ("_raw", "_payload", "_generation", "_mint_token")

    def __new__(cls, *args, **kwargs):
        _fail("source review preparation requires a validated internal mint")

    def __setattr__(self, name, value):
        _fail("source review preparation capability is immutable")

    def __delattr__(self, name):
        _fail("source review preparation capability is immutable")

    def __reduce__(self):
        _fail("source review preparation capability is nonserializable")

    def __reduce_ex__(self, protocol):
        _fail("source review preparation capability is nonserializable")


def _freeze_source_preparation(value):
    if type(value) is dict:
        return ("d", tuple((key, _freeze_source_preparation(child)) for key, child in value.items()))
    if type(value) is list:
        return ("l", tuple(_freeze_source_preparation(child) for child in value))
    return ("v", value)


def _thaw_source_preparation(value):
    kind, payload = value
    if kind == "d":
        return {key: _thaw_source_preparation(child) for key, child in payload}
    if kind == "l":
        return [_thaw_source_preparation(child) for child in payload]
    if kind != "v":
        _fail("source preparation immutable tag differs")
    return payload


def _mint_source_review_preparation(checked, *, generation_sha256, registry, mint_token):
    """Internal boundary: callers must first genuinely replay complete originals.

    The old public owner calls this after its unchanged full regeneration. The
    fixed shared-bank owner calls it after the genuine public bank-context mint.
    This private hook accepts no caller 'verified' flag or public parsed cache.
    It is cooperative custody, not protection against arbitrary Python access.
    """
    contracts.require_sha256(generation_sha256, "source preparation generation")
    detached = _detach(checked)
    raw = review.wire(detached)
    capability = object.__new__(_SourceReviewPreparation)
    object.__setattr__(capability, "_raw", raw)
    object.__setattr__(capability, "_payload", _freeze_source_preparation(detached))
    object.__setattr__(capability, "_generation", generation_sha256)
    object.__setattr__(capability, "_mint_token", mint_token)
    registry[id(capability)] = (capability, raw, generation_sha256, mint_token, capability._payload)
    return capability


def _source_review_preparation(capability, *, registry, mint_token):
    if type(capability) is not _SourceReviewPreparation:
        _fail("exact private source preparation capability required")
    witness = registry.get(id(capability))
    if (witness is None or witness[0] is not capability or witness[1] is not capability._raw
            or witness[2] != capability._generation or witness[3] is not capability._mint_token
            or witness[3] is not mint_token or witness[4] is not capability._payload):
        _fail("source preparation owner/generation/payload witness differs")
    return _thaw_source_preparation(capability._payload)


def _source_review_auth_inputs(preparation, registry, policy, reviews, *, request_ordinal,
        expected_preparation_manifest_sha256, expected_registry_sha256, expected_policy_sha256,
        expected_reviews_sha256, at_time_utc, observed_artifact_sha256s, observed_pins,
        evidence_artifacts):
    """The unchanged public preflight, before expensive original regeneration."""
    detached = _detach(preparation)
    contracts.require_sha256(expected_preparation_manifest_sha256, "preparation manifest SHA256")
    if _digest(detached["manifest"]) != expected_preparation_manifest_sha256:
        _fail("independent legacy review preparation manifest differs")
    contracts.require_int(request_ordinal, "request ordinal", maximum=len(detached["requests"]) - 1)
    # Refuse malformed/oversized authentication inputs before parsing a large
    # producer receipt. Freeze caller-owned JSON before source regeneration.
    registry, policy, reviews, observed_artifact_sha256s, observed_pins = (
        json.loads(review.wire(item)) for item in
        (registry, policy, reviews, observed_artifact_sha256s, observed_pins))
    review._trust(registry, policy, expected_registry_sha256, expected_policy_sha256,
                  action=ACTION, audience=AUDIENCE)
    review._time(at_time_utc)
    if type(reviews) is not list or len(reviews) > review.MAX_REVIEWS or _digest(reviews) != expected_reviews_sha256:
        _fail("independently pinned complete legacy review population differs")
    if (type(evidence_artifacts) is not dict or len(evidence_artifacts) > review.MAX_EVIDENCE
            or any(type(key) is not str or type(raw) is not bytes for key, raw in evidence_artifacts.items())):
        _fail("bounded immutable legacy review evidence bodies required")
    evidence_artifacts = dict(evidence_artifacts)
    total = sum(len(review.wire(item)) for item in (detached["subjects"][request_ordinal],
        registry, policy, reviews, detached["dependency_manifests"][request_ordinal]))
    if total + sum(map(len, evidence_artifacts.values())) > review.MAX_BYTES:
        _fail("aggregate legacy review evidence byte bound exceeded")
    return detached, {"registry": registry, "policy": policy, "reviews": reviews,
        "request_ordinal": request_ordinal,
        "expected_preparation_manifest_sha256": expected_preparation_manifest_sha256,
        "expected_registry_sha256": expected_registry_sha256, "expected_policy_sha256": expected_policy_sha256,
        "expected_reviews_sha256": expected_reviews_sha256, "at_time_utc": at_time_utc,
        "observed_artifact_sha256s": observed_artifact_sha256s, "observed_pins": observed_pins,
        "evidence_artifacts": evidence_artifacts}


def _assess_source_review_prepared(capability, auth_inputs, *, capability_registry, mint_token):
    """Fixed fresh auth/report kernel; never accepts a parsed preparation dict."""
    checked = _source_review_preparation(capability, registry=capability_registry, mint_token=mint_token)
    request_ordinal = auth_inputs["request_ordinal"]
    subject = checked["subjects"][request_ordinal]
    manifest = checked["dependency_manifests"][request_ordinal]
    assessment = review._assess_reviews(subject, auth_inputs["registry"], auth_inputs["policy"], auth_inputs["reviews"], manifest,
        domain=_DOMAIN, expected_subject_sha256=_digest(subject),
        expected_registry_sha256=auth_inputs["expected_registry_sha256"],
        expected_policy_sha256=auth_inputs["expected_policy_sha256"],
        expected_reviews_sha256=auth_inputs["expected_reviews_sha256"],
        expected_manifest_sha256=manifest["manifest_sha256"], at_time_utc=auth_inputs["at_time_utc"],
        observed_artifact_sha256s=auth_inputs["observed_artifact_sha256s"], observed_pins=auth_inputs["observed_pins"],
        evidence_artifacts=auth_inputs["evidence_artifacts"])
    assessment.pop("assessment_sha256")
    assessment.update(profile=PROFILE, preparation_manifest_sha256=auth_inputs["expected_preparation_manifest_sha256"],
        request_ordinal=request_ordinal, deferred_review_slot_ids=subject["deferred_review_slot_ids"],
        deferred_questions_remain_pending=True, response_content_adjudication_available=False,
        coverage_scope="exact_legacy_source_request_nine_evidence_declarations_and_declared_custody_only",
        **FALSE_FLAGS, **_UNSELECTED)
    assessment["assessment_sha256"] = _digest(assessment)
    return assessment


def assess_legacy_source_review(preparation, registry, policy, reviews, *, request_ordinal,
        expected_preparation_manifest_sha256, expected_registry_sha256, expected_policy_sha256,
        expected_reviews_sha256, at_time_utc, observed_artifact_sha256s, observed_pins,
        evidence_artifacts, join_bytes, paired_row_bytes, expected_join_sha256,
        **independent_join_inputs):
    """Replay source preparation, then use the existing fixed-domain verifier.

    Original public signature, preflight order, full original replay, signing
    domain, caps and JSON outcomes remain unchanged. No authority is memoized.
    """
    detached, inputs = _source_review_auth_inputs(preparation, registry, policy, reviews,
        request_ordinal=request_ordinal, expected_preparation_manifest_sha256=expected_preparation_manifest_sha256,
        expected_registry_sha256=expected_registry_sha256, expected_policy_sha256=expected_policy_sha256,
        expected_reviews_sha256=expected_reviews_sha256, at_time_utc=at_time_utc,
        observed_artifact_sha256s=observed_artifact_sha256s, observed_pins=observed_pins,
        evidence_artifacts=evidence_artifacts)
    checked = validate_legacy_source_review_requests(detached, join_bytes, paired_row_bytes,
        expected_join_sha256=expected_join_sha256, **independent_join_inputs)
    capabilities, token = {}, object()
    capability = _mint_source_review_preparation(checked, generation_sha256=_digest(checked["manifest"]),
        registry=capabilities, mint_token=token)
    return _assess_source_review_prepared(capability, inputs, capability_registry=capabilities, mint_token=token)


def validate_legacy_source_review_assessment(assessment, *args, **kwargs):
    expected = assess_legacy_source_review(*args, **kwargs)
    if review.wire(assessment) != review.wire(expected):
        _fail("legacy source-review assessment differs from exact regeneration")
    return expected


__all__ = ["prepare_legacy_source_review_requests", "validate_legacy_source_review_requests",
           "assess_legacy_source_review", "validate_legacy_source_review_assessment"]
