"""Fresh fixed-domain source review over genuinely minted complete banks.

Only immutable original-validated preparation data is reused. Every positive
call performs fresh source-domain trust/signature/time/dependency/role checks.
No signed review, authority, history, governing source or meaning is cached.
"""
from __future__ import annotations

import hashlib
import json

from . import legal_shared_source_bank_context_v1 as banks
from . import legal_source_correspondence_requests_v1 as correspondence
from . import corpus_legacy_source_review as source

SCHEMA = "legal-shared-bank-source-reviews/v1"
PROFILE = "fresh-fixed-domain-source-reviews-from-minted-banks/v1"
DEFAULT_LIMITS = {**banks.DEFAULT_LIMITS, "max_review_calls": 128,
    "max_review_input_bytes": 8 * 1024**2, "max_review_evidence_bytes": 8 * 1024**2}
AUTHORITY = {**banks.AUTHORITY, "review_evidence_is_source_adoption": False}
_CALL = {"epoch_id", "bank_id", "request_ordinal", "assessment_inputs"}
_AUTH = {"registry", "policy", "reviews", "expected_preparation_manifest_sha256",
    "expected_registry_sha256", "expected_policy_sha256", "expected_reviews_sha256", "at_time_utc",
    "observed_artifact_sha256s", "observed_pins", "evidence_artifacts"}
LIMITATIONS = [
    "The genuine public bank-context preparation replays original source banks once. Only its complete preparation manifest/request/subject/dependency/source-section data is reused through private immutable owner-minted capabilities.",
    "Every supplied positive assessment performs the unchanged fixed-domain source verifier freshly, including selected registry/policy/review pins, signatures, time, revocation, roles/scope, dependency observations, evidence and conflicts. No positive authority result is memoized.",
    "A literal null assessment_inputs is explicitly not assessed because inputs are missing. Malformed or mismatched positive inputs refuse; they are never converted into missing-input rows or fabricated empty trust registries.",
    "Nested positive source assessments retain exact legacy JSON semantics: authenticated declarations do not select occurrences, authenticate statutory truth or apply a source/meaning decision. Planned epochs are not authenticated history epochs.",
    "This slice does not implement typed response/adjudication/cohort/history sharing. Existing history actor unions cover source reviewers across supplied branches, including rejected/mismatched/unknown-key claims; they are not an all-role independence inventory.",
    "Existing public source-review signatures, guards, original replay, signing domain and caps remain. The new batch has its own aggregate review-input/evidence caps and does not raise old history or per-review limits.",
    "Private capability/type/registry gates and closing checks are cooperative Python custody, not arbitrary-reflection/monkeypatch attestation or an OS sandbox. No measured runtime, RSS, token savings, model, Lean or convergence claim follows.",
]


class SharedBankSourceReviewsError(ValueError):
    """A complete original/review call, capability or fresh replay differs."""


def _need(condition, message):
    if not condition:
        raise SharedBankSourceReviewsError(message)


def _bounded(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except (banks.SharedSourceBankContextError, correspondence.SourceCorrespondenceRequestsError) as error:
        raise SharedBankSourceReviewsError(str(error)) from error


def _keys(value, fields, label):
    _need(type(value) is dict and len(value) == len(fields) and all(type(key) is str for key in value)
          and set(value) == fields, "closed " + label + " required")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value):
    return correspondence._wire(value)


def _plain(value, bounds, maximum):
    return _bounded(correspondence._plain, value, bounds, maximum)


def _digest(value, label):
    return _bounded(correspondence._digest, value, label)


def _limits(value):
    _need(value is None or type(value) is dict, "plain lower-only review limits required")
    _need(value is None or (len(value) <= len(DEFAULT_LIMITS) and all(type(key) is str for key in value)),
          "bounded plain review limit keys required")
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        _need(key in result and type(bound) is int and 0 < bound <= result[key],
              "unknown, raised or noninteger review limit")
        result[key] = bound
    return result


def _bank_limits(bounds):
    return {key: bounds[key] for key in banks.DEFAULT_LIMITS}


def _calls_shape(calls, bounds):
    _need(type(calls) is list and 0 < len(calls) <= bounds["max_review_calls"],
          "complete bounded ordered source review calls required")
    evidence_bytes = 0
    for row in calls:
        _keys(row, _CALL, "source review call")
        for key in ("epoch_id", "bank_id"):
            _need(type(row[key]) is str and 0 < len(row[key]) <= 4096, "plain bounded review call identity required")
        _need(type(row["request_ordinal"]) is int and 0 <= row["request_ordinal"] < 64,
              "plain bounded review request ordinal required")
        params = row["assessment_inputs"]
        if params is None:
            continue
        _keys(params, _AUTH, "fresh source review assessment inputs")
        evidence = params["evidence_artifacts"]
        _need(type(evidence) is dict and len(evidence) <= 256 and all(type(key) is str for key in evidence),
              "bounded exact source evidence mapping required")
        for raw in evidence.values():
            _need(type(raw) is bytes, "immutable source evidence bytes required")
            evidence_bytes += len(raw)
            _need(evidence_bytes <= bounds["max_review_evidence_bytes"], "aggregate source review evidence cap exceeded")


def _calls_commitment(calls, bounds):
    result = []
    for row in calls:
        params = row["assessment_inputs"]
        if params is not None:
            params = {**params, "evidence_artifacts": {
                identity: {"bytes": len(raw), "sha256": _sha(raw)}
                for identity, raw in params["evidence_artifacts"].items()}}
        result.append({**row, "assessment_inputs": params})
    return _plain(result, bounds, bounds["max_review_input_bytes"])[1]


def _review_capture(calls, bounds):
    _calls_shape(calls, bounds)
    copied = _bounded(correspondence._Budget(bounds, bounds["max_review_input_bytes"]).copy,
                      calls, bytes_allowed=True)
    # No bytes are allowed outside the designated evidence body mapping.
    for row in copied:
        params = row["assessment_inputs"]
        if params is not None:
            _plain({key: value for key, value in params.items() if key != "evidence_artifacts"},
                   bounds, bounds["max_review_input_bytes"])
    return copied, _calls_commitment(copied, bounds)


def shared_bank_source_review_calls_sha256(review_calls, *, limits=None):
    """Hash bounded supplied call metadata and exact evidence descriptors only.

    Replace each positive assessment_inputs.evidence_artifacts byte body with
    {bytes, sha256}; retain the ordered calls and all other values, including
    explicit null inputs, then SHA256 canonical compact Unicode JSON without LF.
    This helper validates no source, trust, signature or review truth.
    """
    bounds = _limits(limits)
    copied, frozen = _review_capture(review_calls, bounds)
    result = _sha(frozen)
    _need(_limits(limits) == bounds and _review_capture(review_calls, bounds)[1] == frozen
          and _review_capture(copied, bounds)[1] == frozen, "review call inputs/limits changed during hashing")
    return result


def _capture(shared_report, packet, source_raw, replay_raw, calls, originals, bounds, offered=None):
    """One mixed root counts original and review evidence bodies before hashing."""
    _bounded(correspondence._shape, originals, correspondence._limits({
        key: bounds[key] for key in correspondence.DEFAULT_LIMITS}))
    _calls_shape(calls, bounds)
    for raw in (source_raw, replay_raw):
        _need(type(raw) is bytes and 0 < len(raw) <= bounds["max_request_bytes"],
              "bounded immutable original request required")
    graph = {"shared_report": shared_report, "packet": packet, "source_request_raw": source_raw,
        "replay_request_raw": replay_raw, "review_calls": calls, "original_banks": originals, "offered_report": offered}
    copied = _bounded(correspondence._Budget(bounds, bounds["max_original_bytes"]).copy, graph, bytes_allowed=True)
    # The complete graph has now passed aggregate/node/depth bounds, before any
    # body hashing or full original/report serialization.
    for key in ("shared_report", "packet", "offered_report"):
        _plain(copied[key], bounds, bounds["max_original_bytes"])
    review_copy, review_wire = _review_capture(copied["review_calls"], bounds)
    copied["review_calls"] = review_copy
    _, bank_wire, _ = _bounded(correspondence._capture, copied["original_banks"], {
        key: bounds[key] for key in correspondence.DEFAULT_LIMITS})
    committed = {key: copied[key] for key in ("shared_report", "packet", "offered_report")}
    committed["original_banks"] = json.loads(bank_wire)
    committed["review_calls"] = json.loads(review_wire)
    for key in ("source_request_raw", "replay_request_raw"):
        raw = copied[key]
        _need(type(raw) is bytes and 0 < len(raw) <= bounds["max_request_bytes"], "bounded immutable original request required")
        committed[key] = {"bytes": len(raw), "sha256": _sha(raw)}
    return copied, _plain(committed, bounds, bounds["max_original_bytes"])[1], review_wire


def _auth_fingerprint(inputs, bounds):
    # Fresh preflight copies are also guarded across the actual verifier call.
    params = {key: value for key, value in inputs.items() if key != "request_ordinal"}
    wrapped = [{"epoch_id": "internal:fresh", "bank_id": "internal:fresh",
        "request_ordinal": inputs["request_ordinal"], "assessment_inputs": params}]
    return _review_capture(wrapped, bounds)[1]


def assess_shared_bank_source_reviews_v1(shared_report, packet, source_request_raw, replay_request_raw, review_calls, *,
        expected_shared_report_sha256, expected_packet_sha256, expected_source_request_sha256,
        expected_replay_request_sha256, expected_review_calls_sha256, original_banks, limits=None):
    """Mint original-bound banks once; freshly assess every supplied positive call."""
    bounds = _limits(limits)
    copied, frozen, call_wire = _capture(shared_report, packet, source_request_raw, replay_request_raw,
        review_calls, original_banks, bounds)
    def fence():
        _need(_limits(limits) == bounds, "caller review limits changed")
        _need(_capture(shared_report, packet, source_request_raw, replay_request_raw, review_calls, original_banks, bounds)[1] == frozen,
              "caller source/review originals changed")
        _need(_capture(copied["shared_report"], copied["packet"], copied["source_request_raw"], copied["replay_request_raw"],
            copied["review_calls"], copied["original_banks"], bounds)[1] == frozen, "detached source/review inputs changed")
    failure = None
    try:
        _digest(expected_review_calls_sha256, "source review call population")
        _need(_sha(call_wire) == expected_review_calls_sha256, "independent source review calls SHA differs")
        offered_shared = copied["shared_report"]
        _need(type(offered_shared) is dict and type(offered_shared.get("schedule")) is dict,
              "complete offered planned schedule required")
        offered_requests = offered_shared["schedule"].get("requests")
        _need(type(offered_requests) is list and len(offered_requests) == len(copied["review_calls"]),
              "complete review-call roster differs from offered schedule")
        for call, planned in zip(copied["review_calls"], offered_requests, strict=True):
            _need(type(planned) is dict and all(key in planned for key in ("epoch_id", "bank_id", "request_ordinal"))
                  and all(type(call[key]) is type(planned[key]) and call[key] == planned[key]
                      for key in ("epoch_id", "bank_id", "request_ordinal")),
                  "review-call order/identity differs from offered schedule")
        context_report = banks.prepare_shared_source_bank_context_v1(copied["shared_report"], copied["packet"],
            copied["source_request_raw"], copied["replay_request_raw"],
            expected_shared_report_sha256=expected_shared_report_sha256, expected_packet_sha256=expected_packet_sha256,
            expected_source_request_sha256=expected_source_request_sha256,
            expected_replay_request_sha256=expected_replay_request_sha256,
            original_banks=copied["original_banks"], limits=_bank_limits(bounds))
        projections = context_report["projections"]
        _need(len(copied["review_calls"]) == len(projections), "every planned request requires exactly one review-call disposition")
        capabilities, token, capability_by_bank = {}, object(), {}
        source_packet = context_report["shared_report"]["source_packet"]
        for bank in source_packet["banks"]:
            capability_by_bank[bank["bank_id"]] = source._mint_source_review_preparation(bank["preparation"],
                generation_sha256=context_report["context_generation_sha256"], registry=capabilities, mint_token=token)
        rows, assessed = [], 0
        for call, projection in zip(copied["review_calls"], projections, strict=True):
            _need(all(call[key] == projection[key] for key in ("epoch_id", "bank_id", "request_ordinal")),
                  "source review call order or planned identity differs")
            params = call["assessment_inputs"]
            assessment = None
            if params is not None:
                capability = capability_by_bank[call["bank_id"]]
                preparation = source._source_review_preparation(capability, registry=capabilities, mint_token=token)
                _, auth_inputs = source._source_review_auth_inputs(preparation,
                    request_ordinal=call["request_ordinal"], **params)
                auth_wire = _auth_fingerprint(auth_inputs, bounds)
                assessment = source._assess_source_review_prepared(capability, auth_inputs,
                    capability_registry=capabilities, mint_token=token)
                _need(_auth_fingerprint(auth_inputs, bounds) == auth_wire,
                      "fresh detached source verifier inputs changed during assessment")
                assessed += 1
            rows.append({"epoch_id": call["epoch_id"], "bank_id": call["bank_id"], "request_ordinal": call["request_ordinal"],
                "context_id": projection["context_id"], "physical_references": projection["physical_references"],
                "assessment_status": "not_assessed_missing_inputs" if params is None else "assessed_fresh_under_supplied_inputs",
                "assessment": assessment, "assessment_sha256": None if assessment is None else _sha(_wire(assessment)),
                "decision_applied": False})
            _plain(rows, bounds, bounds["max_report_bytes"])
        report = {"schema": SCHEMA, "profile": PROFILE, "status": "complete_declared_source_review_call_population",
            "source_shared_report_sha256": expected_shared_report_sha256, "review_calls_sha256": expected_review_calls_sha256,
            "bank_context_report": context_report, "bank_context_report_sha256": _sha(_wire(context_report)), "rows": rows,
            "coverage": {"planned_calls": len(rows), "assessed_calls": assessed, "missing_input_calls": len(rows) - assessed,
                "physical_references": sum(len(row["physical_references"]) for row in rows),
                "candidate_occurrence_references": sum(ref["candidate_count"] for row in rows for ref in row["physical_references"]),
                "full_declared_population_retained": True},
            "work": {"bank_context_prepare_calls": 1, "source_bank_preparations": len(source_packet["banks"]),
                "private_preparation_capability_mints": len(capability_by_bank), "fresh_source_assessments": assessed,
                "fresh_fixed_domain_verifier_calls": assessed, "source_bank_reparses_during_assessment": 0,
                "history_epoch_replays": 0, "authority_cache_hits": 0},
            "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
            "inference_view": None, "limitations": list(LIMITATIONS)}
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
            BaseException.add_note(failure, "A closing shared source review original/limit comparison also failed.")


def shared_bank_source_reviews_sha256(report, *, limits=None):
    """Bounded JSON content identity only; not original or authority validation."""
    bounds = _limits(limits)
    return _sha(_plain(report, bounds, bounds["max_report_bytes"])[1])


def validate_shared_bank_source_reviews_v1(report, shared_report, packet, source_request_raw, replay_request_raw, review_calls, *,
        expected_report_sha256, expected_shared_report_sha256, expected_packet_sha256, expected_source_request_sha256,
        expected_replay_request_sha256, expected_review_calls_sha256, original_banks, limits=None):
    """Remint from originals, freshly reassess all positive calls, compare exactly."""
    bounds = _limits(limits)
    copied, frozen, _ = _capture(shared_report, packet, source_request_raw, replay_request_raw,
        review_calls, original_banks, bounds, report)
    def fence():
        _need(_limits(limits) == bounds, "caller review validation limits changed")
        _need(_capture(shared_report, packet, source_request_raw, replay_request_raw, review_calls, original_banks, bounds, report)[1] == frozen,
              "caller originals or offered source review report changed")
        _need(_capture(copied["shared_report"], copied["packet"], copied["source_request_raw"], copied["replay_request_raw"],
            copied["review_calls"], copied["original_banks"], bounds, copied["offered_report"])[1] == frozen,
            "detached source review validation inputs changed")
    failure = None
    try:
        _digest(expected_report_sha256, "shared source review report")
        checked, raw = _plain(copied["offered_report"], bounds, bounds["max_report_bytes"])
        _need(_sha(raw) == expected_report_sha256, "independent shared source review report SHA differs")
        expected = assess_shared_bank_source_reviews_v1(copied["shared_report"], copied["packet"], copied["source_request_raw"],
            copied["replay_request_raw"], copied["review_calls"], expected_shared_report_sha256=expected_shared_report_sha256,
            expected_packet_sha256=expected_packet_sha256, expected_source_request_sha256=expected_source_request_sha256,
            expected_replay_request_sha256=expected_replay_request_sha256, expected_review_calls_sha256=expected_review_calls_sha256,
            original_banks=copied["original_banks"], limits=bounds)
        _need(_wire(expected) == raw, "shared source review report differs from complete fresh original replay")
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
            BaseException.add_note(failure, "A closing shared source review validation original/limit comparison also failed.")


__all__ = ["SharedBankSourceReviewsError", "shared_bank_source_review_calls_sha256",
    "assess_shared_bank_source_reviews_v1", "shared_bank_source_reviews_sha256", "validate_shared_bank_source_reviews_v1"]
