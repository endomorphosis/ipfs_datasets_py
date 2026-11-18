"""Bounded unsigned stored-source adoption requests and supplied declarations.

The original source-correspondence owner regenerates the complete packet.
This authoring prerequisite creates no signatures, authenticated reviews,
source applications, accepted meanings, model, database or proof operations.
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import re

from . import legal_source_correspondence_requests_v1 as correspondence
from . import corpus_contracts as contracts

SCHEMA = "legal-stored-source-adoption-requests/v1"
PROFILE = "unsigned-stored-source-adoption-authoring/v1"
SIGNING_PROFILE = "reviewed-stored-source-adoption/v1"
SUBJECT_SCHEMA = "legal-stored-source-adoption-subject/v1"
DECLARATION_SCHEMA = "legal-stored-source-adoption-declaration/v1"
CLAIM_SCHEMA = "legal-stored-source-adoption-signed-claim/v1"
ACTION = "apply_reviewed_stored_source_adoption/v1"
AUDIENCE = "legal-autoformalization-stored-source-adoption/v1"
EFFECT = "adopt_exact_stored_occurrence_for_explicit_scope_role_and_legal_as_of_only/v1"
SIGNING_DOMAIN = {"profile": SIGNING_PROFILE, "subject_schema": SUBJECT_SCHEMA,
    "claim_schema": CLAIM_SCHEMA, "action": ACTION, "audience": AUDIENCE, "effect": EFFECT}
DEFAULT_LIMITS = dict(correspondence.DEFAULT_LIMITS)
AUTHORITY = {**correspondence.AUTHORITY, **dict.fromkeys(("source_adoption_authorized",
    "source_adoption_applied", "meaning_accepted", "reviewer_authenticated", "actual_review_completed"), False)}
PENDING_OBLIGATIONS = (
    "actual_nine_source_answers_unavailable", "actual_typed_source_reviews_unavailable",
    "actual_source_adjudication_unavailable", "complete_cohort_actor_exclusions_unavailable",
    "current_history_and_binding_replay_unavailable", "new_effect_specific_authority_unavailable",
    "exact_text_context_resolution_unavailable", "source_edition_applicability_review_unavailable",
    "meaning_review_deferred", "global_dependency_split_review_deferred", "training_and_Lean_admission_deferred")
LIMITATIONS = [
    "This is unsigned authoring only: no source choice is applied and no review, signature, evidence body, history or legal meaning is authenticated.",
    "Prepared subjects bind the complete physical reference and candidate population. They cannot authorize a later supplied choice: future authorization must bind the exact sealed declaration body, source use, evidence and dependency identities in the new effect domain.",
    "All original alternatives, stored text and required_unavailable/declaration_only contexts remain unchanged. Declared evidence references have no verified evidence bodies in this API.",
    "Declared purpose, role, scope, legal-as-of, edition and view are intent metadata, not historical-producer attestation or authenticated governing law.",
    "No training/gold, global partition, semantic graph, Lean, source equivalence or convergence authority follows. A selected pilot need not wait for global identity grouping, but global closure remains necessary for corpus-wide eligibility.",
    "Closing comparisons observe cooperative Python boundaries, not an OS sandbox, arbitrary-monkeypatch attestation or atomic multi-file snapshot.",
]
_PHYSICAL_REF = {"bank_id", "physical_row_ordinal", "physical_identity", "paired_row_sha256"}
_CHOICE = {"source_section_index", "source_section_sha256", "source_version_ref",
    "source_occurrence_ref", "context_ref"}
_SOURCE_USE = {"purpose", "declared_region_role", "scope_id", "jurisdiction_id", "instrument_id",
    "legal_as_of_civil_date", "edition", "view_profile"}
_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_CIVIL = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_EVIDENCE_ID = re.compile(r"[a-z0-9][a-z0-9_.:@/-]{0,255}\Z")


class StoredSourceAdoptionRequestsError(ValueError):
    """A finite original, unsigned choice or complete regeneration differs."""


def _need(condition, message):
    if not condition:
        raise StoredSourceAdoptionRequestsError(message)


def _keys(value, expected, label):
    _need(type(value) is dict and len(value) == len(expected) and
          all(type(key) is str for key in value) and set(value) == expected,
          "closed " + label + " required")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value):
    return correspondence._wire(value)


def _bounded(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except correspondence.SourceCorrespondenceRequestsError as error:
        raise StoredSourceAdoptionRequestsError(str(error)) from error


def _limits(value):
    return _bounded(correspondence._limits, value)


def _plain(value, bounds, maximum):
    return _bounded(correspondence._plain, value, bounds, maximum)


def _digest(value, label):
    return _bounded(correspondence._digest, value, label)


def _capture(packet, request_raw, original_banks, extras, bounds):
    """One mixed-body graph budget precedes every hash and project replay."""
    _bounded(correspondence._shape, original_banks, bounds)
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= bounds["max_request_bytes"],
          "bounded immutable original correspondence request required")
    graph = {"packet": packet, "request_raw": request_raw,
             "original_banks": original_banks, "extras": extras}
    copied = _bounded(correspondence._Budget(bounds, bounds["max_original_bytes"]).copy,
                      graph, bytes_allowed=True)
    # Reject bytes anywhere outside the designated original byte fields before
    # constructing any byte descriptor. The ordinary portions are still bounded.
    plain_packet, _ = _plain(copied["packet"], bounds, bounds["max_report_bytes"])
    plain_extras, _ = _plain(copied["extras"], bounds, bounds["max_original_bytes"])
    _, bank_commitment, _ = _bounded(correspondence._capture, copied["original_banks"], bounds)
    committed = {"packet": plain_packet, "request_raw": {"bytes": len(request_raw), "sha256": _sha(request_raw)},
        "original_bank_commitments": json.loads(bank_commitment), "extras": plain_extras}
    fingerprint = _plain(committed, bounds, bounds["max_original_bytes"])[1]
    return copied, fingerprint


def _ref(record):
    return {"record_cid": record["record_cid"], "sha256": _sha(_wire(record))}


def _physical(row):
    return {key: row[key] for key in ("bank_id", "physical_row_ordinal", "physical_identity", "paired_row_sha256")}


def _choices(packet, row):
    bank = packet["banks"][row["bank_ordinal"]]
    preparation = bank["preparation"]
    request = preparation["requests"][row["request_ordinal"]]
    result = []
    for candidate in request["original_row"]["candidates"]:
        section = preparation["source_sections"][candidate["source_section_index"]]
        result.append({"source_section_index": candidate["source_section_index"],
            "source_section_sha256": _sha(_wire(section)), "source_version_ref": _ref(section["source_version"]),
            "source_occurrence_ref": _ref(candidate["source_occurrence"]),
            "context_ref": _ref(candidate["context_declaration"])})
    return result, request


def _authority_fields():
    return {"decision_applied": False, "authority": dict(AUTHORITY),
        "training_mask": 0, "evaluation_gold_mask": 0, "inference_view": None}


def _subject(row, request, choices, packet_sha, request_sha):
    return contracts.seal_record({"schema": SUBJECT_SCHEMA, "profile": SIGNING_PROFILE,
        "signing_domain": dict(SIGNING_DOMAIN), "source_packet_sha256": packet_sha,
        "source_request_sha256": request_sha, "physical_reference": _physical(row),
        "request_ref": row["request_ref"], "source_subject_ref": row["subject_ref"],
        "source_preparation_manifest_sha256": row["preparation_manifest_sha256"],
        "candidate_choices_sha256": _sha(_wire(choices)),
        "active_slot_ids": request["context_slot_ids"], "deferred_slot_ids": request["deferred_review_slot_ids"],
        "pending_obligations": list(PENDING_OBLIGATIONS), **_authority_fields()})


def prepare_stored_source_adoption_requests_v1(packet, request_raw, *, expected_packet_sha256,
        expected_request_sha256, original_banks, limits=None):
    """Regenerate the source packet, then create complete unsigned requests."""
    bounds = _limits(limits)
    copied, frozen = _capture(packet, request_raw, original_banks, None, bounds)
    _digest(expected_packet_sha256, "source packet")
    _digest(expected_request_sha256, "source request")
    def fence():
        _need(_limits(limits) == bounds, "caller limits changed during authoring")
        _need(_capture(packet, request_raw, original_banks, None, bounds)[1] == frozen,
              "caller originals changed during authoring")
        _need(_capture(copied["packet"], copied["request_raw"], copied["original_banks"], None, bounds)[1] == frozen,
              "detached originals changed during authoring")
    failure = None
    try:
        checked = correspondence.validate_source_correspondence_requests_v1(copied["packet"], copied["request_raw"],
            expected_report_sha256=expected_packet_sha256, expected_request_sha256=expected_request_sha256,
            original_banks=copied["original_banks"], limits=bounds)
        rows = []
        for row in checked["physical_rows"]:
            choices, request = _choices(checked, row)
            subject = _subject(row, request, choices, expected_packet_sha256, expected_request_sha256)
            rows.append({"physical_reference": _physical(row), "request_ref": row["request_ref"],
                "source_subject_ref": row["subject_ref"],
                "source_preparation_manifest_sha256": row["preparation_manifest_sha256"],
                "candidate_choices": choices, "subject": subject,
                "declaration_template": {"choice": None, "source_use": None, "declared_at_utc": None,
                    "rationale": None, "evidence_refs": []},
                "pending_obligations": list(PENDING_OBLIGATIONS),
                "status": "pending_actual_source_adoption_inputs", **_authority_fields()})
        coverage = checked["coverage"]
        report = {"schema": SCHEMA, "profile": PROFILE, "signing_domain": dict(SIGNING_DOMAIN),
            "source_packet_sha256": expected_packet_sha256, "source_request_sha256": expected_request_sha256,
            "source_packet": checked, "rows": rows,
            "coverage": {"physical_rows": len(rows), "logical_requests": coverage["logical_requests"],
                "source_sections": coverage["distinct_source_sections"],
                "candidate_occurrence_references": coverage["candidate_occurrence_references"],
                "pending_rows": len(rows), "submitted_declarations": 0, "applied_source_decisions": 0,
                "full_declared_population_retained": True},
            "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0, "inference_view": None,
            "status": "pending_actual_source_adoption_inputs", "limitations": list(LIMITATIONS)}
        return _plain(report, bounds, bounds["max_report_bytes"])[0]
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing stored-source authoring original/limit comparison also failed.")


def stored_source_adoption_requests_sha256(report, *, limits=None):
    """Bounded content identity only; this helper authenticates no originals."""
    bounds = _limits(limits)
    return _sha(_plain(report, bounds, bounds["max_report_bytes"])[1])


def validate_stored_source_adoption_requests_v1(report, packet, request_raw, *, expected_report_sha256,
        expected_packet_sha256, expected_request_sha256, original_banks, limits=None):
    """Compare the complete supplied report to original-bound regeneration."""
    bounds = _limits(limits)
    extras = {"offered_report": report}
    copied, frozen = _capture(packet, request_raw, original_banks, extras, bounds)
    def fence():
        _need(_limits(limits) == bounds, "caller limits changed during preparation validation")
        _need(_capture(packet, request_raw, original_banks, extras, bounds)[1] == frozen,
              "caller originals or offered preparation changed during validation")
        _need(_capture(copied["packet"], copied["request_raw"], copied["original_banks"], copied["extras"], bounds)[1] == frozen,
              "detached preparation-validation inputs changed")
    failure = None
    try:
        _digest(expected_report_sha256, "adoption preparation")
        checked, raw = _plain(copied["extras"]["offered_report"], bounds, bounds["max_report_bytes"])
        _need(_sha(raw) == expected_report_sha256, "independent adoption preparation SHA256 differs")
        expected = prepare_stored_source_adoption_requests_v1(copied["packet"], copied["request_raw"],
            expected_packet_sha256=expected_packet_sha256, expected_request_sha256=expected_request_sha256,
            original_banks=copied["original_banks"], limits=bounds)
        _need(_wire(expected) == raw, "adoption preparation differs from complete original regeneration")
        return checked
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing adoption-preparation validation input/limit comparison also failed.")


def _text(value, label, maximum=4096):
    _need(type(value) is str and 0 < len(value) <= maximum and value.strip() and "\x00" not in value,
          "bounded nonempty " + label + " required")
    _need(len(value.encode("utf-8")) <= maximum, "UTF8 byte bound exceeded: " + label)


def _source_use(value, extraction_profile):
    _keys(value, _SOURCE_USE, "source use declaration")
    _need(value["purpose"] in ("retained_source_analysis", "governing_normative_source"), "explicit source purpose required")
    _need(value["declared_region_role"] in ("operative_body", "editorial_note", "source_credit", "unknown"),
          "explicit declared region role required")
    for key in _SOURCE_USE - {"purpose", "declared_region_role"}:
        if value[key] is not None:
            _text(value[key], key)
    civil = value["legal_as_of_civil_date"]
    if civil is not None:
        _need(_CIVIL.fullmatch(civil) is not None, "canonical civil legal-as-of date required")
        try:
            _need(date.fromisoformat(civil).isoformat() == civil, "valid civil legal-as-of date required")
        except ValueError as error:
            raise StoredSourceAdoptionRequestsError("valid civil legal-as-of date required") from error
    _need(value["view_profile"] is None or value["view_profile"] == extraction_profile,
          "declared view differs from exact original extraction profile")
    return value


def _evidence(refs):
    _need(type(refs) is list and 0 < len(refs) <= 8, "nonempty bounded declared evidence references required")
    seen = set()
    for ref in refs:
        _keys(ref, {"artifact_id", "sha256"}, "declared evidence reference")
        identity = ref["artifact_id"]
        _need(type(identity) is str and _EVIDENCE_ID.fullmatch(identity) is not None,
              "canonical declared evidence identity required")
        _digest(ref["sha256"], "declared evidence")
        _need(identity not in seen, "duplicate declared evidence identity")
        seen.add(identity)


def record_stored_source_adoption_declaration_v1(preparation, choice, *, physical_reference, source_use,
        declared_at_utc, rationale, evidence_refs, packet, request_raw, expected_preparation_sha256,
        expected_packet_sha256, expected_request_sha256, original_banks, limits=None):
    """Record explicitly supplied intent after replay; do not sign or apply it."""
    bounds = _limits(limits)
    extras = {"preparation": preparation, "choice": choice, "physical_reference": physical_reference,
        "source_use": source_use, "declared_at_utc": declared_at_utc, "rationale": rationale, "evidence_refs": evidence_refs}
    copied, frozen = _capture(packet, request_raw, original_banks, extras, bounds)
    values = copied["extras"]
    def fence():
        _need(_limits(limits) == bounds, "caller limits changed during declaration")
        _need(_capture(packet, request_raw, original_banks, extras, bounds)[1] == frozen,
              "caller originals or declaration inputs changed")
        _need(_capture(copied["packet"], copied["request_raw"], copied["original_banks"], copied["extras"], bounds)[1] == frozen,
              "detached declaration originals changed")
    failure = None
    try:
        checked = validate_stored_source_adoption_requests_v1(values["preparation"], copied["packet"], copied["request_raw"],
            expected_report_sha256=expected_preparation_sha256, expected_packet_sha256=expected_packet_sha256,
            expected_request_sha256=expected_request_sha256, original_banks=copied["original_banks"], limits=bounds)
        physical = values["physical_reference"]
        _keys(physical, _PHYSICAL_REF, "physical adoption reference")
        ordinal = physical["physical_row_ordinal"]
        _need(type(ordinal) is int and ordinal >= 0, "plain physical reference ordinal required")
        target = next((row for row in checked["rows"] if _wire(row["physical_reference"]) == _wire(physical)), None)
        _need(target is not None, "physical reference outside complete preparation")
        offered = values["choice"]
        _keys(offered, _CHOICE, "explicit existing source candidate choice")
        _need(type(offered["source_section_index"]) is int and offered["source_section_index"] >= 0,
              "plain candidate section index required")
        _need(any(_wire(offered) == _wire(item) for item in target["candidate_choices"]),
              "choice must be one exact original physical request candidate")
        source_row = next(row for row in checked["source_packet"]["physical_rows"] if _wire(_physical(row)) == _wire(physical))
        source_bank = checked["source_packet"]["banks"][source_row["bank_ordinal"]]["preparation"]
        request = source_bank["requests"][source_row["request_ordinal"]]
        candidate = next(item for item in request["original_row"]["candidates"]
            if item["source_section_index"] == offered["source_section_index"]
            and _wire(_ref(item["source_occurrence"])) == _wire(offered["source_occurrence_ref"])
            and _wire(_ref(item["context_declaration"])) == _wire(offered["context_ref"]))
        section = source_bank["source_sections"][offered["source_section_index"]]
        use = _source_use(values["source_use"], section["source_version"]["extracted_view"]["extraction_profile"])
        issued = values["declared_at_utc"]
        _need(type(issued) is str and _UTC.fullmatch(issued) is not None, "canonical explicit UTC seconds required")
        try:
            datetime.fromisoformat(issued.replace("Z", "+00:00"))
        except ValueError as error:
            raise StoredSourceAdoptionRequestsError("valid declaration UTC calendar required") from error
        _text(values["rationale"], "declaration rationale", 8192)
        _evidence(values["evidence_refs"])
        pending = list(PENDING_OBLIGATIONS)
        pending.extend("declared_" + key + "_unknown" for key in sorted(use)
                       if use[key] is None or (key == "declared_region_role" and use[key] == "unknown"))
        record = contracts.seal_record({"schema": DECLARATION_SCHEMA, "profile": PROFILE,
            "signing_domain": dict(SIGNING_DOMAIN), "preparation_sha256": expected_preparation_sha256,
            "source_packet_sha256": expected_packet_sha256, "source_request_sha256": expected_request_sha256,
            "physical_reference": physical, "subject_ref": _ref(target["subject"]), "choice": offered,
            "source_use": use, "considered_candidate_choices_sha256": _sha(_wire(target["candidate_choices"])),
            "original_context": candidate["context_declaration"], "declared_at_utc": issued,
            "rationale": values["rationale"], "evidence_refs": values["evidence_refs"],
            "pending_obligations": pending, "status": "declared_unsigned_unapplied_source_adoption_intent",
            "intent": "deliberate_adoption", "signature": None, **_authority_fields()})
        return _plain(record, bounds, min(contracts.MAX_RECORD_BYTES, bounds["max_report_bytes"]))[0]
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing unsigned declaration original/limit comparison also failed.")


def validate_stored_source_adoption_declaration_v1(declaration, preparation, choice, *, expected_declaration_sha256,
        physical_reference, source_use, declared_at_utc, rationale, evidence_refs, packet, request_raw,
        expected_preparation_sha256, expected_packet_sha256, expected_request_sha256, original_banks, limits=None):
    """Regenerate the complete unsigned body from all original supplied inputs."""
    bounds = _limits(limits)
    extras = {"declaration": declaration, "preparation": preparation, "choice": choice,
        "physical_reference": physical_reference, "source_use": source_use,
        "declared_at_utc": declared_at_utc, "rationale": rationale, "evidence_refs": evidence_refs}
    copied, frozen = _capture(packet, request_raw, original_banks, extras, bounds)
    def fence():
        _need(_limits(limits) == bounds, "caller limits changed during declaration validation")
        _need(_capture(packet, request_raw, original_banks, extras, bounds)[1] == frozen,
              "caller originals or offered declaration changed during validation")
        _need(_capture(copied["packet"], copied["request_raw"], copied["original_banks"], copied["extras"], bounds)[1] == frozen,
              "detached declaration-validation inputs changed")
    failure = None
    try:
        _digest(expected_declaration_sha256, "unsigned declaration")
        values = copied["extras"]
        checked, raw = _plain(values["declaration"], bounds, min(contracts.MAX_RECORD_BYTES, bounds["max_report_bytes"]))
        _need(_sha(raw) == expected_declaration_sha256, "independent unsigned declaration SHA256 differs")
        expected = record_stored_source_adoption_declaration_v1(values["preparation"], values["choice"],
            physical_reference=values["physical_reference"], source_use=values["source_use"], declared_at_utc=values["declared_at_utc"],
            rationale=values["rationale"], evidence_refs=values["evidence_refs"], packet=copied["packet"], request_raw=copied["request_raw"],
            expected_preparation_sha256=expected_preparation_sha256, expected_packet_sha256=expected_packet_sha256,
            expected_request_sha256=expected_request_sha256, original_banks=copied["original_banks"], limits=bounds)
        _need(_wire(expected) == raw, "unsigned declaration differs from complete original regeneration")
        return checked
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing unsigned-declaration validation input/limit comparison also failed.")


__all__ = ["StoredSourceAdoptionRequestsError", "prepare_stored_source_adoption_requests_v1",
    "stored_source_adoption_requests_sha256", "validate_stored_source_adoption_requests_v1",
    "record_stored_source_adoption_declaration_v1", "validate_stored_source_adoption_declaration_v1"]
