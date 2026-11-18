"""Fresh exact typed source responses over genuinely minted complete banks.

Only immutable original-validated preparation data is reused. Every positive
call performs fresh source-domain trust/signature/time/dependency/role checks
and unchanged typed-content/variant/pending-question evaluation.
No signed review, authority, history, governing source or meaning is cached.
"""
from __future__ import annotations

import hashlib
import json

from . import legal_shared_source_bank_context_v1 as banks
from . import legal_source_correspondence_requests_v1 as correspondence
from . import corpus_legacy_source_review as source
from . import corpus_legacy_source_responses as responses

SCHEMA = "legal-shared-bank-source-responses/v1"
PROFILE = "fresh-typed-source-responses-from-minted-banks/v1"
DEFAULT_LIMITS = {**banks.DEFAULT_LIMITS, "max_response_calls": 128,
    "max_response_input_bytes": 8 * 1024**2, "max_response_evidence_bytes": 8 * 1024**2}
AUTHORITY = {**banks.AUTHORITY, "review_evidence_is_source_adoption": False,
    "typed_response_decision_applied": False}
_CALL = {"epoch_id", "bank_id", "request_ordinal", "response_inputs"}
_AUTH = {"registry", "policy", "reviews", "expected_preparation_manifest_sha256",
    "expected_registry_sha256", "expected_policy_sha256", "expected_reviews_sha256", "at_time_utc",
    "observed_artifact_sha256s", "observed_pins", "evidence_artifacts",
    "response_bindings", "expected_response_bindings_sha256"}
LIMITATIONS = [
    "The genuine public bank-context preparation replays original banks once. Only complete immutable preparation/request/subject/dependency/source-section outputs are reused; original internal receipt parsing is not shared across fresh public operations.",
    "Every positive response call freshly checks the source signing domain, registry/policy/review pins, signatures, time, revocation, roles/scope, dependency observations and evidence, then validates the exact typed bodies/bindings and retains all variants and pending questions. No raw preverified assessment or portable context is accepted.",
    "A literal null response_inputs is not assessed because inputs are missing. Malformed positive inputs refuse; missing/malformed individual body content remains a rejected content row exactly as under the old owner. Missing inputs never become an empty registry, an answer, a variant, or a completed review.",
    "Exact legacy response JSON is retained. Authenticated typed declarations can remain unresolved and do not require whole source prerequisites to be satisfied. Nine active answer questions, seven deferred questions and every supplied review/body result remain; authentication and exact-answer equality are not adjudication or statutory truth.",
    "Planned epochs are not executed history. No adjudication/cohort/history adaptation, source adoption, governing source, legal meaning, graph, Lean, training admission, model convergence or token/performance result is supplied here. Existing history actor unions cover source reviewers, including rejected/mismatched/unknown-key claims, not an all-role independence inventory.",
    "Existing public source/response signatures, guard order, complete original regeneration and caps remain. The new batch has separate aggregate call/evidence bounds and raises no old review, preparation or history limit.",
    "Private capability/type/registry gates and closing comparisons are cooperative Python custody, not arbitrary-reflection/monkeypatch attestation or an OS sandbox. No evidence body or raw receipt is embedded in this batch's metadata commitment.",
]


class SharedBankSourceResponsesError(ValueError):
    """A complete original/response call, capability or fresh replay differs."""


def _need(condition, message):
    if not condition:
        raise SharedBankSourceResponsesError(message)


def _bounded(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except (banks.SharedSourceBankContextError, correspondence.SourceCorrespondenceRequestsError) as error:
        raise SharedBankSourceResponsesError(str(error)) from error


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
    _need(value is None or type(value) is dict, "plain lower-only response limits required")
    _need(value is None or (len(value) <= len(DEFAULT_LIMITS) and all(type(key) is str for key in value)),
          "bounded plain response limit keys required")
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        _need(key in result and type(bound) is int and 0 < bound <= result[key],
              "unknown, raised or noninteger response limit")
        result[key] = bound
    return result


def _bank_limits(bounds):
    return {key: bounds[key] for key in banks.DEFAULT_LIMITS}


def _calls_shape(calls, bounds):
    _need(type(calls) is list and 0 < len(calls) <= bounds["max_response_calls"],
          "complete bounded ordered source response calls required")
    evidence_bytes = 0
    for row in calls:
        _keys(row, _CALL, "source response call")
        for key in ("epoch_id", "bank_id"):
            _need(type(row[key]) is str and 0 < len(row[key]) <= 4096, "plain bounded response call identity required")
        _need(type(row["request_ordinal"]) is int and 0 <= row["request_ordinal"] < 64,
              "plain bounded response request ordinal required")
        params = row["response_inputs"]
        if params is None:
            continue
        _keys(params, _AUTH, "fresh source response assessment inputs")
        evidence = params["evidence_artifacts"]
        _need(type(evidence) is dict and len(evidence) <= 256 and all(type(key) is str for key in evidence),
              "bounded exact source evidence mapping required")
        for raw in evidence.values():
            _need(type(raw) is bytes, "immutable source evidence bytes required")
            evidence_bytes += len(raw)
            _need(evidence_bytes <= bounds["max_response_evidence_bytes"], "aggregate source response evidence cap exceeded")


def _calls_commitment(calls, bounds):
    result = []
    for row in calls:
        params = row["response_inputs"]
        if params is not None:
            params = {**params, "evidence_artifacts": {
                identity: {"bytes": len(raw), "sha256": _sha(raw)}
                for identity, raw in params["evidence_artifacts"].items()}}
        result.append({**row, "response_inputs": params})
    return _plain(result, bounds, bounds["max_response_input_bytes"])[1]


def _response_capture(calls, bounds):
    _calls_shape(calls, bounds)
    copied = _bounded(correspondence._Budget(bounds, bounds["max_response_input_bytes"]).copy,
                      calls, bytes_allowed=True)
    # No bytes are allowed outside the designated evidence body mapping.
    for row in copied:
        params = row["response_inputs"]
        if params is not None:
            _plain({key: value for key, value in params.items() if key != "evidence_artifacts"},
                   bounds, bounds["max_response_input_bytes"])
    return copied, _calls_commitment(copied, bounds)


def shared_bank_source_response_calls_sha256(response_calls, *, limits=None):
    """Hash bounded supplied call metadata and exact evidence descriptors only.

    Replace each positive response_inputs.evidence_artifacts byte body with
    {bytes, sha256}; retain the ordered calls and all other values, including
    explicit null inputs, then SHA256 canonical compact Unicode JSON without LF.
    This helper validates no source, trust, signature or review truth.
    """
    bounds = _limits(limits)
    copied, frozen = _response_capture(response_calls, bounds)
    result = _sha(frozen)
    _need(_limits(limits) == bounds and _response_capture(response_calls, bounds)[1] == frozen
          and _response_capture(copied, bounds)[1] == frozen, "response call inputs/limits changed during hashing")
    return result


def _capture(shared_report, packet, source_raw, replay_raw, calls, originals, bounds, offered=None):
    """One mixed root counts original and response evidence before hashing."""
    _bounded(correspondence._shape, originals, correspondence._limits({
        key: bounds[key] for key in correspondence.DEFAULT_LIMITS}))
    _calls_shape(calls, bounds)
    for raw in (source_raw, replay_raw):
        _need(type(raw) is bytes and 0 < len(raw) <= bounds["max_request_bytes"],
              "bounded immutable original request required")
    graph = {"shared_report": shared_report, "packet": packet, "source_request_raw": source_raw,
        "replay_request_raw": replay_raw, "response_calls": calls, "original_banks": originals, "offered_report": offered}
    copied = _bounded(correspondence._Budget(bounds, bounds["max_original_bytes"]).copy, graph, bytes_allowed=True)
    # The complete graph has now passed aggregate/node/depth bounds, before any
    # body hashing or full original/report serialization.
    for key in ("shared_report", "packet", "offered_report"):
        _plain(copied[key], bounds, bounds["max_original_bytes"])
    response_copy, response_wire = _response_capture(copied["response_calls"], bounds)
    copied["response_calls"] = response_copy
    _, bank_wire, _ = _bounded(correspondence._capture, copied["original_banks"], {
        key: bounds[key] for key in correspondence.DEFAULT_LIMITS})
    committed = {key: copied[key] for key in ("shared_report", "packet", "offered_report")}
    committed["original_banks"] = json.loads(bank_wire)
    committed["response_calls"] = json.loads(response_wire)
    for key in ("source_request_raw", "replay_request_raw"):
        raw = copied[key]
        _need(type(raw) is bytes and 0 < len(raw) <= bounds["max_request_bytes"], "bounded immutable original request required")
        committed[key] = {"bytes": len(raw), "sha256": _sha(raw)}
    return copied, _plain(committed, bounds, bounds["max_original_bytes"])[1], response_wire


def _auth_fingerprint(inputs, bindings, bindings_sha256, bounds):
    # Fresh preflight copies are also guarded across the actual verifier call.
    params = {key: value for key, value in inputs.items() if key != "request_ordinal"}
    params.update(response_bindings=bindings, expected_response_bindings_sha256=bindings_sha256)
    wrapped = [{"epoch_id": "internal:fresh", "bank_id": "internal:fresh",
        "request_ordinal": inputs["request_ordinal"], "response_inputs": params}]
    return _response_capture(wrapped, bounds)[1]


def assess_shared_bank_source_responses_v1(shared_report, packet, source_request_raw, replay_request_raw, response_calls, *,
        expected_shared_report_sha256, expected_packet_sha256, expected_source_request_sha256,
        expected_replay_request_sha256, expected_response_calls_sha256, original_banks, limits=None):
    """Mint banks once; freshly authenticate and type-check each positive call."""
    bounds = _limits(limits)
    copied, frozen, call_wire = _capture(shared_report, packet, source_request_raw, replay_request_raw,
        response_calls, original_banks, bounds)
    def fence():
        _need(_limits(limits) == bounds, "caller response limits changed")
        _need(_capture(shared_report, packet, source_request_raw, replay_request_raw, response_calls, original_banks, bounds)[1] == frozen,
              "caller source/response originals changed")
        _need(_capture(copied["shared_report"], copied["packet"], copied["source_request_raw"], copied["replay_request_raw"],
            copied["response_calls"], copied["original_banks"], bounds)[1] == frozen, "detached source/response inputs changed")
    failure = None
    try:
        _digest(expected_response_calls_sha256, "source response call population")
        _need(_sha(call_wire) == expected_response_calls_sha256, "independent source response calls SHA differs")
        offered_shared = copied["shared_report"]
        _need(type(offered_shared) is dict and type(offered_shared.get("schedule")) is dict,
              "complete offered planned schedule required")
        offered_requests = offered_shared["schedule"].get("requests")
        _need(type(offered_requests) is list and len(offered_requests) == len(copied["response_calls"]),
              "complete response-call roster differs from offered schedule")
        for call, planned in zip(copied["response_calls"], offered_requests, strict=True):
            _need(type(planned) is dict and all(key in planned for key in ("epoch_id", "bank_id", "request_ordinal"))
                  and all(type(call[key]) is type(planned[key]) and call[key] == planned[key]
                      for key in ("epoch_id", "bank_id", "request_ordinal")),
                  "response-call order/identity differs from offered schedule")
        context_report = banks.prepare_shared_source_bank_context_v1(copied["shared_report"], copied["packet"],
            copied["source_request_raw"], copied["replay_request_raw"],
            expected_shared_report_sha256=expected_shared_report_sha256, expected_packet_sha256=expected_packet_sha256,
            expected_source_request_sha256=expected_source_request_sha256,
            expected_replay_request_sha256=expected_replay_request_sha256,
            original_banks=copied["original_banks"], limits=_bank_limits(bounds))
        projections = context_report["projections"]
        _need(len(copied["response_calls"]) == len(projections), "every planned request requires exactly one response-call disposition")
        capabilities, token, capability_by_bank = {}, object(), {}
        source_packet = context_report["shared_report"]["source_packet"]
        for bank in source_packet["banks"]:
            capability_by_bank[bank["bank_id"]] = source._mint_source_review_preparation(bank["preparation"],
                generation_sha256=context_report["context_generation_sha256"], registry=capabilities, mint_token=token)
        rows, assessed = [], 0
        for call, projection in zip(copied["response_calls"], projections, strict=True):
            _need(all(call[key] == projection[key] for key in ("epoch_id", "bank_id", "request_ordinal")),
                  "source response call order or planned identity differs")
            params = call["response_inputs"]
            assessment = None
            if params is not None:
                capability = capability_by_bank[call["bank_id"]]
                preparation = source._source_review_preparation(capability, registry=capabilities, mint_token=token)
                response_pin = params["expected_response_bindings_sha256"]
                preparation, reviews, bindings, evidence = responses._source_response_inputs(preparation,
                    params["reviews"], params["response_bindings"], response_pin, params["evidence_artifacts"])
                auth_params = {key: value for key, value in params.items()
                    if key not in ("response_bindings", "expected_response_bindings_sha256")}
                auth_params.update(reviews=reviews, evidence_artifacts=evidence)
                _, auth_inputs = source._source_review_auth_inputs(preparation,
                    request_ordinal=call["request_ordinal"], **auth_params)
                auth_wire = _auth_fingerprint(auth_inputs, bindings, response_pin, bounds)
                assessment = responses._assess_source_responses_prepared(capability, auth_inputs,
                    response_bindings=bindings, expected_response_bindings_sha256=response_pin,
                    capability_registry=capabilities, mint_token=token)
                _need(_auth_fingerprint(auth_inputs, bindings, response_pin, bounds) == auth_wire,
                      "fresh detached source/response inputs changed during assessment")
                assessed += 1
            rows.append({"epoch_id": call["epoch_id"], "bank_id": call["bank_id"], "request_ordinal": call["request_ordinal"],
                "context_id": projection["context_id"], "physical_references": projection["physical_references"],
                "assessment_status": "not_assessed_missing_inputs" if params is None else "assessed_fresh_under_supplied_inputs",
                "assessment": assessment, "assessment_sha256": None if assessment is None else _sha(_wire(assessment)),
                "decision_applied": False})
            _plain(rows, bounds, bounds["max_report_bytes"])
        report = {"schema": SCHEMA, "profile": PROFILE, "status": "complete_declared_source_response_call_population",
            "source_shared_report_sha256": expected_shared_report_sha256, "response_calls_sha256": expected_response_calls_sha256,
            "bank_context_report": context_report, "bank_context_report_sha256": _sha(_wire(context_report)), "rows": rows,
            "coverage": {"planned_calls": len(rows), "assessed_calls": assessed, "missing_input_calls": len(rows) - assessed,
                "physical_references": sum(len(row["physical_references"]) for row in rows),
                "candidate_occurrence_references": sum(ref["candidate_count"] for row in rows for ref in row["physical_references"]),
                "full_declared_population_retained": True},
            "work": {"bank_context_prepare_calls": 1, "source_bank_preparations": len(source_packet["banks"]),
                "private_preparation_capability_mints": len(capability_by_bank), "fresh_typed_response_assessments": assessed,
                "fresh_source_assessments": assessed,
                "fresh_fixed_domain_verifier_calls": assessed,
                "typed_response_content_checks": sum(len(row["assessment"]["response_results"]) for row in rows if row["assessment"] is not None),
                "source_bank_reparses_during_assessment": 0,
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
            BaseException.add_note(failure, "A closing shared source response original/limit comparison also failed.")


def shared_bank_source_responses_sha256(report, *, limits=None):
    """Bounded JSON content identity only; not original or authority validation."""
    bounds = _limits(limits)
    return _sha(_plain(report, bounds, bounds["max_report_bytes"])[1])


def validate_shared_bank_source_responses_v1(report, shared_report, packet, source_request_raw, replay_request_raw, response_calls, *,
        expected_report_sha256, expected_shared_report_sha256, expected_packet_sha256, expected_source_request_sha256,
        expected_replay_request_sha256, expected_response_calls_sha256, original_banks, limits=None):
    """Remint originals, freshly authenticate/check typed content, compare exactly."""
    bounds = _limits(limits)
    copied, frozen, _ = _capture(shared_report, packet, source_request_raw, replay_request_raw,
        response_calls, original_banks, bounds, report)
    def fence():
        _need(_limits(limits) == bounds, "caller response validation limits changed")
        _need(_capture(shared_report, packet, source_request_raw, replay_request_raw, response_calls, original_banks, bounds, report)[1] == frozen,
              "caller originals or offered source response report changed")
        _need(_capture(copied["shared_report"], copied["packet"], copied["source_request_raw"], copied["replay_request_raw"],
            copied["response_calls"], copied["original_banks"], bounds, copied["offered_report"])[1] == frozen,
            "detached source response validation inputs changed")
    failure = None
    try:
        _digest(expected_report_sha256, "shared source response report")
        checked, raw = _plain(copied["offered_report"], bounds, bounds["max_report_bytes"])
        _need(_sha(raw) == expected_report_sha256, "independent shared source response report SHA differs")
        expected = assess_shared_bank_source_responses_v1(copied["shared_report"], copied["packet"], copied["source_request_raw"],
            copied["replay_request_raw"], copied["response_calls"], expected_shared_report_sha256=expected_shared_report_sha256,
            expected_packet_sha256=expected_packet_sha256, expected_source_request_sha256=expected_source_request_sha256,
            expected_replay_request_sha256=expected_replay_request_sha256, expected_response_calls_sha256=expected_response_calls_sha256,
            original_banks=copied["original_banks"], limits=bounds)
        _need(_wire(expected) == raw, "shared source response report differs from complete fresh original replay")
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
            BaseException.add_note(failure, "A closing shared source response validation original/limit comparison also failed.")


__all__ = ["SharedBankSourceResponsesError", "shared_bank_source_response_calls_sha256",
    "assess_shared_bank_source_responses_v1", "shared_bank_source_responses_sha256", "validate_shared_bank_source_responses_v1"]
