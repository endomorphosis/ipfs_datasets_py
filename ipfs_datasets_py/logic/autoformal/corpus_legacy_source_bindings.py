"""Authenticate candidate stored-text tuples without adopting governing law.

Fully replay the supplied history before checking exact section/occurrence
geometry and separate binding signatures. Legal region and applicability are
explicit declarations. There is no file, network, model or publication access.
"""
from __future__ import annotations

from datetime import date
import re

from . import corpus_contracts as contracts
from . import corpus_legacy_source_adjudication as adjudication
from . import corpus_legacy_source_application as application
from . import corpus_legacy_source_cohort as cohorts
from . import corpus_legacy_source_history as history
from . import corpus_legacy_source_responses as responses
from . import corpus_legacy_source_review as source
from . import corpus_source as geometry
from . import legal_graph_review as auth

PROFILE = "signed-legacy-candidate-structured-source-bindings/v1"
DECLARATION_SCHEMA = "legal-corpus-legacy-source-binding-declaration/v1"
CLAIM_SCHEMA = "legal-corpus-legacy-source-binding-signed-claim/v1"
ACTION = "record_legacy_candidate_structured_source_binding/v1"
AUDIENCE = "legal-autoformalization-legacy-source-bindings/v1"
ASSESSMENT_SCHEMA = "legal-corpus-legacy-source-binding-authority-assessment/v1"
REPORT_SCHEMA = "legal-corpus-legacy-source-binding-assessment/v1"
EFFECT = "record_exact_declared_stored_section_occurrence_applicability_tuple_only"
FALSE_FLAGS = {**history.FALSE_FLAGS, "structured_binding_establishes_legal_truth": False,
    "applicability_semantics_verified": False, "governing_source_adoption_applied": False}
REGION_ROLES = ("operative_body", "editorial_note", "source_credit", "unknown")
MAX_BINDING_BYTES = auth.MAX_BYTES
_DOMAIN = auth._ReviewDomain(source.SUBJECT_SCHEMA, CLAIM_SCHEMA, ACTION, AUDIENCE,
                             ASSESSMENT_SCHEMA, source._subject, 9)
_REPLAY = {"genesis_report", "genesis_inputs", "revision_steps", "genesis_epoch_id",
    "current_epoch_id", "at_time_utc", "expected_genesis_assessment_sha256",
    "expected_revision_step_sha256s"}
_ENTRY = {"bank_id", "request_ordinal", "binding_registry", "binding_policy",
          "binding_reviews", "assessment_inputs"}
_PARAMS = {"declaration_artifact_id", "expected_declaration_sha256",
    "expected_binding_registry_sha256", "expected_binding_policy_sha256",
    "expected_binding_reviews_sha256", "observed_artifact_sha256s", "observed_pins", "evidence_artifacts"}
_CHOICE = {"source_section_index", "source_section_sha256", "source_version_ref",
    "source_occurrence_ref", "context_ref", "declared_region_role", "applicability"}
_APPLICABILITY = {"scope_id", "jurisdiction_id", "instrument_id",
                  "legal_as_of_civil_date", "evidence_occurrence_refs"}


def _fail(message):
    raise contracts.CorpusContractError(message)


def legacy_source_binding_input_sha256(entry):
    """Commit complete entry metadata and exact immutable evidence byte hashes."""
    contracts.require_keys(entry, _ENTRY, "binding entry")
    contracts.require_keys(entry["assessment_inputs"], _PARAMS, "binding assessment inputs")
    return history._freeze(entry)[1]


def _entries(values, pins):
    if (type(values) is not list or not 0 < len(values) <= cohorts.MAX_REQUESTS
            or type(pins) is not list or len(pins) != len(values)):
        _fail("complete bounded ordered binding entries and independent pins required")
    total = 0
    for entry, expected in zip(values, pins, strict=True):
        contracts.require_sha256(expected, "binding input SHA256")
        if legacy_source_binding_input_sha256(entry) != expected:
            _fail("independently pinned complete binding input differs")
        auth._id(entry["bank_id"], "binding bank identity")
        contracts.require_int(entry["request_ordinal"], "binding ordinal", maximum=cohorts.MAX_REQUESTS - 1)
        params = entry["assessment_inputs"]
        params["evidence_artifacts"] = adjudication._evidence(params["evidence_artifacts"])
        auth._trust(entry["binding_registry"], entry["binding_policy"],
            params["expected_binding_registry_sha256"], params["expected_binding_policy_sha256"],
            action=ACTION, audience=AUDIENCE)
        claims = entry["binding_reviews"]
        contracts.require_sha256(params["expected_binding_reviews_sha256"], "binding claim-list SHA256")
        if (type(claims) is not list or len(claims) > auth.MAX_REVIEWS
                or auth.digest(claims) != params["expected_binding_reviews_sha256"]):
            _fail("complete pinned binding claims required")
        identity = params["declaration_artifact_id"]
        if identity is None:
            if params["expected_declaration_sha256"] is not None or claims:
                _fail("absent binding requires absent declaration hash and claims")
        else:
            auth._id(identity, "binding declaration identity")
            contracts.require_sha256(params["expected_declaration_sha256"], "binding declaration SHA256")
            if identity in params["evidence_artifacts"] and len(params["evidence_artifacts"][identity]) > contracts.MAX_RECORD_BYTES:
                _fail("binding declaration exceeds record bound")
        total += len(auth.wire(application._commitment(entry))) + sum(map(len, params["evidence_artifacts"].values()))
        if total > MAX_BINDING_BYTES:
            _fail("aggregate binding input byte bound exceeded")
    return values


def _preflight(report, replay, extra, expected):
    # One budget covers history and prospective binding input before any replay.
    detached, _ = history._freeze({"report": report, "replay": replay, "extra": extra})
    report, replay, extra = (detached[key] for key in ("report", "replay", "extra"))
    contracts.require_keys(replay, _REPLAY, "complete history replay inputs")
    contracts.require_sha256(expected, "history assessment SHA256")
    if auth.digest(report) != expected:
        _fail("independently pinned history assessment differs")
    return report, replay, extra


def _replay(report, replay):
    checked = history.validate_legacy_source_history(report, **replay)
    current_id = replay["current_epoch_id"]
    current = replay["genesis_inputs"] if current_id == replay["genesis_epoch_id"] else next(
        step["inputs"] for step in replay["revision_steps"] if step["epoch_id"] == current_id)
    epoch = next(item["report"] for item in checked["epochs"] if item["epoch_id"] == current_id)
    contexts = []
    for bank in current["banks"]:
        preparation = bank["preparation"]
        for ordinal, member in enumerate(bank["requests"]):
            index = len(contexts)
            row = checked["current_request_results"][index]
            request = preparation["requests"][ordinal]
            if (row["bank_id"] != bank["bank_id"] or row["request_ordinal"] != ordinal
                    or not cohorts._same(row["request_ref"], responses._ref(request))):
                _fail("current history population differs from exact source requests")
            contexts.append({"bank_id": bank["bank_id"], "request_ordinal": ordinal,
                "preparation": preparation, "member": member, "request": request,
                "subject": preparation["subjects"][ordinal],
                "manifest": preparation["dependency_manifests"][ordinal], "current": row,
                "snapshot": epoch["request_results"][index],
                "upstream": current["applications" if current_id == replay["genesis_epoch_id"] else "revisions"][index]})
    if len(contexts) != len(checked["current_request_results"]):
        _fail("complete current history population required")
    actors = history._union([replay["genesis_inputs"]["cohort"]]
        + [step["inputs"]["cohort"] for step in replay["revision_steps"]])
    return checked, contexts, actors


def _reference(value, schema, label):
    contracts.require_keys(value, {"record_cid", "sha256", "schema"}, label)
    contracts.require_cid(value["record_cid"], label + " CID", codecs=("dag-json",))
    contracts.require_sha256(value["sha256"], label + " SHA256")
    if value["schema"] != schema:
        _fail("binding reference schema differs")


def _choice(value, context):
    value = contracts.clone_json(value)
    contracts.require_keys(value, _CHOICE, "explicit legacy stored-source tuple")
    sections = context["preparation"]["source_sections"]
    index = contracts.require_int(value["source_section_index"], "source section index", maximum=len(sections) - 1)
    section = sections[index]
    contracts.require_sha256(value["source_section_sha256"], "complete source section SHA256")
    if value["source_section_sha256"] != auth.digest(section):
        _fail("binding complete source section differs")
    source_ref = {"section_index": index, "sha256": auth.digest(section),
                  "source_version_cid": section["source_version"]["record_cid"]}
    if not any(cohorts._same(source_ref, ref) for ref in context["request"]["source_section_refs"]):
        _fail("binding section outside original complete request population")
    for key, schema in (("source_version_ref", geometry.SOURCE_VERSION_SCHEMA),
                        ("source_occurrence_ref", geometry.SOURCE_OCCURRENCE_SCHEMA),
                        ("context_ref", geometry.CONTEXT_DECLARATION_SCHEMA)):
        _reference(value[key], schema, key)
    if not cohorts._same(value["source_version_ref"], responses._ref(section["source_version"])):
        _fail("binding source version differs from selected section")
    candidates = [item for item in context["request"]["original_row"]["candidates"]
                  if item["source_section_index"] == index]
    candidate = next((item for item in candidates if cohorts._same(
        value["source_occurrence_ref"], responses._ref(item["source_occurrence"]))), None)
    if candidate is None or not cohorts._same(value["context_ref"], responses._ref(candidate["context_declaration"])):
        _fail("binding occurrence and context must be one exact original request candidate")
    text, expected = section["extracted_text"], section["provenance"]["text_sha256"]
    version = geometry.validate_source_version(section["source_version"], expected_raw_sha256=expected,
        extracted_text=text, expected_extracted_sha256=expected, raw_bytes=text.encode("utf-8"))
    occurrence = geometry.validate_source_occurrence(candidate["source_occurrence"], source_version=version,
        expected_raw_sha256=expected, extracted_text=text, expected_extracted_sha256=expected)
    geometry.validate_context_declaration(candidate["context_declaration"], source_occurrence=occurrence,
                                        expected_occurrence_cid=occurrence["record_cid"])
    if value["declared_region_role"] not in REGION_ROLES:
        _fail("explicit declared source region role required")
    applicability = value["applicability"]
    contracts.require_keys(applicability, _APPLICABILITY, "explicit declared applicability")
    for key in ("scope_id", "jurisdiction_id", "instrument_id"):
        auth._id(applicability[key], "declared applicability " + key)
    civil = applicability["legal_as_of_civil_date"]
    if civil is not None:
        if (type(civil) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", civil) is None
                or date.fromisoformat(civil).isoformat() != civil):
            _fail("canonical declared civil legal-as-of date or explicit null required")
    evidence = applicability["evidence_occurrence_refs"]
    if type(evidence) is not list or not 0 < len(evidence) <= 256:
        _fail("nonempty bounded applicability evidence occurrences required")
    seen = set()
    for ref in evidence:
        _reference(ref, geometry.SOURCE_OCCURRENCE_SCHEMA, "applicability evidence occurrence")
        if ref["record_cid"] in seen or not any(cohorts._same(ref, responses._ref(item["source_occurrence"])) for item in candidates):
            _fail("applicability evidence must be distinct request candidates in the selected section/version")
        seen.add(ref["record_cid"])
    return value


def _declaration(checked, context, choice, declared_at_utc, rationale, evidence_refs):
    current = context["current"]
    if not current["current_use_eligible"] or len(current["active_answer_variant_refs"]) != 9:
        _fail("binding authoring requires all nine current history answer references")
    choice = _choice(choice, context)
    declared = auth._time(declared_at_utc)
    upstream = context["snapshot"]["declaration_record"]
    claims = context["upstream"]["revision_reviews"]
    if declared > auth._time(checked["evaluation_time_utc"]):
        _fail("binding declaration follows current history evaluation")
    if any(declared < auth._time(time) for time in
           [upstream["declared_at_utc"], *[claim["issued_at_utc"] for claim in claims]]):
        _fail("binding declaration predates selected revision declaration or claims")
    contracts.require_text(rationale, "binding rationale", max_bytes=8192)
    refs = contracts.clone_json(evidence_refs)
    responses._refs(refs)
    if not refs:
        _fail("binding requires explicit supporting evidence")
    return contracts.seal_record({"schema": DECLARATION_SCHEMA, "profile": PROFILE,
        "binding_effect": EFFECT, "history_assessment_ref": history._report_ref(checked),
        "current_epoch_id": checked["current_epoch_id"], "current_history_result_sha256": auth.digest(current),
        "bank_id": context["bank_id"], "request_ordinal": context["request_ordinal"],
        "request_ref": responses._ref(context["request"]), "subject_ref": responses._ref(context["subject"]),
        "preparation_manifest_sha256": auth.digest(context["preparation"]["manifest"]),
        "source_binding_sha256": context["request"]["source_binding_sha256"],
        "selected_answer_variant_refs": current["active_answer_variant_refs"],
        "choice": choice, "declared_at_utc": declared_at_utc, "rationale": rationale,
        "evidence_refs": refs, "deferred_review_slot_ids": context["request"]["deferred_review_slot_ids"],
        "status": "declared_unauthenticated_candidate_stored_source_binding", "view": "candidate",
        **FALSE_FLAGS, **source._UNSELECTED})


def record_legacy_source_binding_declaration(history_report, history_replay_inputs, choice, *,
        bank_id, request_ordinal, expected_history_assessment_sha256, declared_at_utc, rationale, evidence_refs):
    """Author supplied candidate intent after full history replay; do not sign."""
    offered, replay, inputs = _preflight(history_report, history_replay_inputs,
        {"choice": choice, "evidence_refs": evidence_refs, "rationale": rationale,
         "declared_at_utc": declared_at_utc, "bank_id": bank_id, "request_ordinal": request_ordinal},
        expected_history_assessment_sha256)
    auth._id(inputs["bank_id"], "binding bank identity")
    contracts.require_int(inputs["request_ordinal"], "binding request ordinal", maximum=cohorts.MAX_REQUESTS - 1)
    checked, contexts, _ = _replay(offered, replay)
    context = next((item for item in contexts if item["bank_id"] == inputs["bank_id"]
                    and item["request_ordinal"] == inputs["request_ordinal"]), None)
    if context is None:
        _fail("binding request absent from complete history")
    return _declaration(checked, context, inputs["choice"], inputs["declared_at_utc"],
                        inputs["rationale"], inputs["evidence_refs"])


def validate_legacy_source_binding_declaration(record, *args, **kwargs):
    checked = contracts.clone_json(record)
    if not cohorts._same(checked, record_legacy_source_binding_declaration(*args, **kwargs)):
        _fail("legacy binding declaration differs from exact regeneration")
    return checked


def _content(entry, checked, context):
    params = entry["assessment_inputs"]
    identity, evidence = params["declaration_artifact_id"], params["evidence_artifacts"]
    if identity is None:
        return None, []
    try:
        record = contracts.load_record_bytes(evidence.get(identity), expected_sha256=params["expected_declaration_sha256"])
        expected = _declaration(checked, context, record["choice"], record["declared_at_utc"],
                                 record["rationale"], record["evidence_refs"])
        if not cohorts._same(record, expected):
            _fail("binding body differs from exact history, source tuple or declared inputs")
        for ref in record["evidence_refs"]:
            body = evidence.get(ref["artifact_id"])
            if ref["artifact_id"] == identity or body is None or adjudication._sha(body) != ref["sha256"]:
                _fail("binding supporting evidence missing, changed or self-referential")
        variants = {item["record_cid"]: item for item in context["member"]["typed_assessment"]["answer_variants"]}
        common = {"artifact_id": identity, "sha256": params["expected_declaration_sha256"]}
        closure = {"status": "declared_complete", "unresolved": [], "obligations": [
            {"slot_id": slot, "disposition": responses.DISPOSITIONS[variants[ref["record_cid"]]["answer"]["disposition"]],
             "evidence_refs": [common]} for slot, ref in zip(context["request"]["context_slot_ids"],
                 record["selected_answer_variant_refs"], strict=True)]}
        if any(not cohorts._same(claim["context_closure"], closure) for claim in entry["binding_reviews"]):
            _fail("every binding claim must sign one exact complete nine-slot declaration")
        return record, []
    except (ValueError, TypeError, KeyError, IndexError, StopIteration, RecursionError) as error:
        return None, [str(error)[:512] or "invalid_binding_content"]


def assess_legacy_source_bindings(history_report, history_replay_inputs, bindings, *,
        expected_history_assessment_sha256, expected_binding_input_sha256s):
    """Regenerate every history epoch, then authenticate candidate source tuples."""
    offered, replay, extra = _preflight(history_report, history_replay_inputs,
        {"bindings": bindings, "pins": expected_binding_input_sha256s}, expected_history_assessment_sha256)
    entries = _entries(extra["bindings"], extra["pins"])
    checked, contexts, actors = _replay(offered, replay)
    if len(entries) != len(contexts):
        _fail("complete current history binding population required")
    rows = []
    for entry, context in zip(entries, contexts, strict=True):
        if entry["bank_id"] != context["bank_id"] or entry["request_ordinal"] != context["request_ordinal"]:
            _fail("binding entries moved across source requests")
        params = entry["assessment_inputs"]
        authority = auth._assess_reviews(context["subject"], entry["binding_registry"], entry["binding_policy"],
            entry["binding_reviews"], context["manifest"], domain=_DOMAIN,
            expected_subject_sha256=auth.digest(context["subject"]), expected_manifest_sha256=context["manifest"]["manifest_sha256"],
            expected_registry_sha256=params["expected_binding_registry_sha256"], expected_policy_sha256=params["expected_binding_policy_sha256"],
            expected_reviews_sha256=params["expected_binding_reviews_sha256"], at_time_utc=checked["evaluation_time_utc"],
            observed_artifact_sha256s=params["observed_artifact_sha256s"], observed_pins=params["observed_pins"],
            evidence_artifacts=params["evidence_artifacts"])
        authority.pop("assessment_sha256")
        authority["coverage_scope"] = "legacy_candidate_stored_source_tuple_authority_only"
        authority["assessment_sha256"] = auth.digest(authority)
        record, content_blockers = _content(entry, checked, context)
        matches = application._matches({"application_registry": entry["binding_registry"],
                                        "application_reviews": entry["binding_reviews"]}, actors)
        blockers = []
        if not context["current"]["current_use_eligible"]:
            blockers.append("current_history_candidate_prerequisites_unavailable")
        if matches:
            blockers.append("binding_actor_matches_all_epoch_source_reviewers")
        if actors["counts"]["unknown_key_reviews"]:
            blockers.append("all_epoch_source_key_inventory_incomplete")
        if record is not None:
            if any(auth._time(claim["issued_at_utc"]) < auth._time(record["declared_at_utc"])
                   for claim in entry["binding_reviews"]):
                blockers.append("binding_claim_predates_common_declaration")
            if record["choice"]["declared_region_role"] == "unknown":
                blockers.append("declared_source_region_role_unavailable")
            if record["choice"]["applicability"]["legal_as_of_civil_date"] is None:
                blockers.append("declared_legal_as_of_civil_date_unavailable")
        eligible = record is not None and not content_blockers and not blockers and authority["review_prerequisites_satisfied_under_selected_trust"]
        identity, evidence = params["declaration_artifact_id"], params["evidence_artifacts"]
        rows.append({"bank_id": context["bank_id"], "request_ordinal": context["request_ordinal"],
            "request_ref": responses._ref(context["request"]), "current_history_result_sha256": auth.digest(context["current"]),
            "declaration_artifact_ref": None if identity is None else {"artifact_id": identity, "sha256": params["expected_declaration_sha256"]},
            "observed_declaration_sha256": adjudication._sha(evidence[identity]) if identity in evidence else None,
            "declaration_record": record, "declaration_content_status": "absent" if identity is None else "valid_declared_content" if record is not None else "rejected",
            "content_blockers": content_blockers, "authority_assessment": authority,
            "exclusion_matches": matches, "binding_blockers": blockers,
            "structured_source_binding_declared_under_selected_profile": eligible,
            "declared_binding_refs": [responses._ref(record)] if eligible else [],
            "deferred_review_slot_ids": context["request"]["deferred_review_slot_ids"],
            "original_contexts_remain_required_unavailable": True, "decision_applied": False})
    report = {"schema": REPORT_SCHEMA, "profile": PROFILE, "binding_effect": EFFECT,
        "history_assessment": checked, "history_assessment_ref": history._report_ref(checked),
        "current_epoch_id": checked["current_epoch_id"], "evaluation_time_utc": checked["evaluation_time_utc"],
        "expected_binding_input_sha256s": extra["pins"], "all_epoch_source_exclusion_sha256": auth.digest(actors),
        "request_results": rows, "counts": {"requests": len(rows),
            "declared_structured_bindings": sum(row["structured_source_binding_declared_under_selected_profile"] for row in rows),
            "binding_bodies": sum(row["declaration_artifact_ref"] is not None for row in rows),
            "authenticated_binding_claims": sum(row["authority_assessment"]["authenticated_evidence_count"] for row in rows),
            "source_decisions_applied": 0, "physical_governing_bindings_applied": 0},
        "coordinate_scope": "exact_retained_stored_text_plain_unicode_codepoint_and_utf8_half_open_ranges",
        "coverage_scope": "complete_supplied_history_and_explicit_candidate_binding_declarations_only",
        "view": "candidate", **FALSE_FLAGS, **source._UNSELECTED}
    report["assessment_sha256"] = auth.digest(report)
    return cohorts._freeze(report)


def validate_legacy_source_bindings(report, *args, **kwargs):
    checked = cohorts._freeze(report)
    if not cohorts._same(checked, assess_legacy_source_bindings(*args, **kwargs)):
        _fail("legacy source bindings differ from exact regeneration")
    return checked


__all__ = ["legacy_source_binding_input_sha256", "record_legacy_source_binding_declaration",
           "validate_legacy_source_binding_declaration", "assess_legacy_source_bindings",
           "validate_legacy_source_bindings"]
