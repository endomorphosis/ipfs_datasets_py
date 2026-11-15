"""Original-body content catalog and complete planned replay schedule.

Catalog reuse does not cache parsed validation, signatures, authority or history.
The existing public correspondence validator regenerates the source packet.
Epochs here are plans, not authenticated or executed review/history epochs.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import legal_source_correspondence_requests_v1 as correspondence

PROFILE = "shared-original-catalog-planned-replay/v1"
SCHEMA = "legal-shared-source-replay/v1"
REQUEST_SCHEMA = "legal-shared-source-replay-request/v1"
CATALOG_SCHEMA = "legal-shared-source-original-catalog/v1"
SCHEDULE_SCHEMA = "legal-shared-source-planned-schedule/v1"
DEFAULT_LIMITS = {**correspondence.DEFAULT_LIMITS, "max_epochs": 8,
    "max_scheduled_requests": 128, "max_expanded_reference_bytes": 1024**3}
AUTHORITY = {**correspondence.AUTHORITY, **dict.fromkeys(("planned_schedule_is_executed",
    "shared_parsed_validation_implemented", "history_replay_qualified", "authority_memoized"), False)}
PARSER_PROFILES = {"join": "legacy-source-join-canonical-record/v1",
    "paired": "paired-span-census-record/v1", "receipt": "legacy-producer-receipt-json/v1"}
LEGACY_HISTORY_INPUT_CAP = 512 * 1024**2
LIMITATIONS = [
    "The content catalog covers designated immutable join, paired-row and producer-receipt bodies only. Complete source texts and metadata remain bound by original bank commitments and the unchanged source packet.",
    "Content identity includes raw SHA256, byte length, media type and fixed parser profile. Equal content never merges origins, physical occurrences, logical requests, planned branches or evidence roles.",
    "The catalog itself parses no original body. Shared parsed validation, authenticated history replay and authority memoization are unimplemented. Source packet regeneration still uses the existing complete public validator.",
    "Epochs are a complete independently pinned plan, not executed or authenticated review/history epochs. Forecast expanded references are accounting quantities, not completed workload or a change to any legacy limit.",
    "Per-construction-pass hash/comparison counters describe this catalog algorithm only; outer custody checks and helper calls can make additional passes. They do not measure total runtime hashing, parsing, RSS, speedup or token savings.",
    "Physical cache coordinates remain independently pinned supplied declarations; no cache table, parent Parquet or metadata shard is opened here. All source selection, legal meaning, training, Lean and convergence authority remains false.",
    "Closing comparisons observe cooperative Python boundaries, not an OS sandbox, arbitrary-monkeypatch attestation or atomic multi-file snapshot.",
]
_ID = re.compile(r"[a-z0-9][a-z0-9_.:@/-]{0,255}\Z")
_REQUEST = {"schema", "profile", "bank_commitments", "catalog_sha256", "schedule_sha256", "epochs"}


class SharedSourceReplayError(ValueError):
    """A bounded original catalog, complete schedule or regeneration differs."""


def _need(condition, message):
    if not condition:
        raise SharedSourceReplayError(message)


def _bounded(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except correspondence.SourceCorrespondenceRequestsError as error:
        raise SharedSourceReplayError(str(error)) from error


def _keys(value, fields, label):
    _need(type(value) is dict and len(value) == len(fields) and
        all(type(key) is str for key in value) and set(value) == fields, "closed " + label + " required")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value):
    return correspondence._wire(value)


def _digest(value, label):
    return _bounded(correspondence._digest, value, label)


def _limits(value):
    _need(value is None or type(value) is dict, "plain lower-only limits required")
    _need(value is None or (len(value) <= len(DEFAULT_LIMITS) and all(type(key) is str for key in value)),
          "bounded plain limit keys required")
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        _need(key in result and type(bound) is int and 0 < bound <= result[key], "unknown, raised or noninteger bound")
        result[key] = bound
    return result


def _delegate_limits(bounds):
    return {key: bounds[key] for key in correspondence.DEFAULT_LIMITS}


def _plain(value, bounds, maximum):
    return _bounded(correspondence._plain, value, bounds, maximum)


def _epochs(value, bounds):
    _need(type(value) is list and 0 < len(value) <= bounds["max_epochs"], "complete bounded planned epochs required")
    seen = set()
    for ordinal, row in enumerate(value):
        _keys(row, {"epoch_id", "parent_epoch_id"}, "planned epoch")
        identity, parent = row["epoch_id"], row["parent_epoch_id"]
        _need(type(identity) is str and _ID.fullmatch(identity) is not None and identity not in seen,
              "distinct canonical planned epoch identity required")
        _need((ordinal == 0 and parent is None) or (ordinal > 0 and type(parent) is str and parent in seen),
              "one first root and earlier declared parent required")
        seen.add(identity)


def _capture(original_banks, epochs, bounds, *, packet=None, source_request_raw=None, replay_request_raw=None, extra=None):
    """One graph budget covers all supplied bodies before hashes/replay."""
    _bounded(correspondence._shape, original_banks, _delegate_limits(bounds))
    _epochs(epochs, bounds)
    scheduled = sum(len(bank["paired_row_bytes"]) for bank in original_banks) * len(epochs)
    _need(scheduled <= bounds["max_scheduled_requests"], "complete planned logical request count exceeds bound")
    for raw in (source_request_raw, replay_request_raw):
        _need(raw is None or (type(raw) is bytes and 0 < len(raw) <= bounds["max_request_bytes"]),
              "bounded immutable canonical request bytes required")
    graph = {"original_banks": original_banks, "epochs": epochs, "packet": packet,
        "source_request_raw": source_request_raw, "replay_request_raw": replay_request_raw, "extra": extra}
    copied = _bounded(correspondence._Budget(bounds, bounds["max_original_bytes"]).copy, graph, bytes_allowed=True)
    # The generic mixed visitor permits only designated immutable original
    # bodies. Ordinary request/report/epoch structures are independently plain.
    for key in ("epochs", "packet", "extra"):
        _plain(copied[key], bounds, bounds["max_original_bytes"])
    _, bank_wire, bank_pins = _bounded(correspondence._capture, copied["original_banks"], _delegate_limits(bounds))
    commitment = {key: copied[key] for key in ("epochs", "packet", "extra")}
    commitment["original_banks"] = json.loads(bank_wire)
    for key in ("source_request_raw", "replay_request_raw"):
        raw = copied[key]
        commitment[key] = None if raw is None else {"bytes": len(raw), "sha256": _sha(raw)}
    frozen = _plain(commitment, bounds, bounds["max_original_bytes"])[1]
    return copied, frozen, bank_pins


def _catalog(banks):
    records, bodies, origins, bank_rows = {}, {}, [], []
    calls = hashed = comparisons = compared = 0
    def add(bank_id, kind, ordinal, raw):
        nonlocal calls, hashed, comparisons, compared
        if raw is None:
            return None
        profile = PARSER_PROFILES[kind]
        content_id = None
        # Only exact raw-byte equality under the same fixed profile and length
        # permits reuse. Python equality's visited CPU bytes are not measured;
        # the recorded byte count is a conservative candidate-length bound.
        for identity, record in records.items():
            if record["parser_profile"] == profile and record["bytes"] == len(raw):
                comparisons += 1
                compared += len(raw)
                if bodies[identity] == raw:
                    content_id = identity
                    break
        if content_id is None:
            digest = _sha(raw)
            calls += 1
            hashed += len(raw)
            key = {"sha256": digest, "bytes": len(raw), "media_type": "application/json",
                "parser_profile": profile}
            content_id = "sha256:" + _sha(_wire(key))
            _need(content_id not in records, "contradictory bytes for one complete content identity")
            records[content_id], bodies[content_id] = {"content_id": content_id, **key}, raw
        digest = records[content_id]["sha256"]
        origin_key = {"bank_id": bank_id, "kind": kind, "logical_row_ordinal": ordinal}
        origin_id = "sha256:" + _sha(_wire(origin_key))
        _need(all(row["origin_id"] != origin_id for row in origins), "duplicate or contradictory original origin")
        origins.append({"origin_id": origin_id, **origin_key, "content_id": content_id,
            "raw_sha256": digest, "raw_bytes": len(raw)})
        return origin_id
    for bank in banks:
        identity = bank["bank_id"]
        join = add(identity, "join", None, bank["join_bytes"])
        paired = [add(identity, "paired", ordinal, raw) for ordinal, raw in enumerate(bank["paired_row_bytes"])]
        receipt = add(identity, "receipt", None, bank["join_inputs"]["producer_receipt_bytes"])
        bank_rows.append({"bank_id": identity, "join_origin_id": join, "paired_origin_ids": paired,
                          "producer_receipt_origin_id": receipt})
    ordered = [records[key] for key in sorted(records)]
    catalog = {"schema": CATALOG_SCHEMA, "profile": PROFILE, "records": ordered,
        "origins": origins, "banks": bank_rows,
        "coverage": {"content_records": len(ordered), "origin_references": len(origins),
            "unique_content_bytes": sum(row["bytes"] for row in ordered),
            "origin_reference_bytes": sum(row["raw_bytes"] for row in origins),
            "unique_receipt_bytes": sum(row["bytes"] for row in ordered if row["parser_profile"] == PARSER_PROFILES["receipt"]),
            "receipt_origin_bytes": sum(row["raw_bytes"] for row in origins if row["kind"] == "receipt")}}
    work = {"body_sha256_calls": calls, "body_sha256_input_bytes": hashed,
        "equality_comparisons": comparisons, "compared_candidate_bytes_upper_bound": compared}
    return catalog, work


def _schedule(banks, epochs, catalog, bounds):
    by_origin = {row["origin_id"]: row for row in catalog["origins"]}
    requests, expanded = [], 0
    receipt_expanded = physical = 0
    for epoch in epochs:
        for bank, binding in zip(banks, catalog["banks"], strict=True):
            for ordinal, paired in enumerate(binding["paired_origin_ids"]):
                receipt = binding["producer_receipt_origin_id"]
                refs = [binding["join_origin_id"], paired] + ([] if receipt is None else [receipt])
                expanded += sum(by_origin[ref]["raw_bytes"] for ref in refs)
                receipt_expanded += 0 if receipt is None else by_origin[receipt]["raw_bytes"]
                _need(expanded <= bounds["max_expanded_reference_bytes"], "planned expanded reference byte bound exceeded")
                physical_rows = [row["physical_row_ordinal"] for row in bank["physical_rows"] if row["request_ordinal"] == ordinal]
                physical += len(physical_rows)
                requests.append({"epoch_id": epoch["epoch_id"], "bank_id": bank["bank_id"],
                    "request_ordinal": ordinal, "join_origin_id": binding["join_origin_id"],
                    "paired_origin_id": paired, "producer_receipt_origin_id": receipt,
                    "physical_row_ordinals": physical_rows})
    forks = []
    for epoch in epochs:
        children = [row["epoch_id"] for row in epochs if row["parent_epoch_id"] == epoch["epoch_id"]]
        if len(children) > 1:
            forks.append({"parent_epoch_id": epoch["epoch_id"], "child_epoch_ids": children})
    return {"schema": SCHEDULE_SCHEMA, "profile": PROFILE, "epochs": epochs,
        "requests": requests, "forks": forks, "coverage": {"epochs": len(epochs),
            "scheduled_logical_requests": len(requests), "scheduled_physical_references": physical,
            "expanded_reference_bytes": expanded, "expanded_receipt_reference_bytes": receipt_expanded,
            "legacy_history_input_cap": LEGACY_HISTORY_INPUT_CAP,
            "receipt_reference_lower_bound_exceeds_legacy_cap": receipt_expanded > LEGACY_HISTORY_INPUT_CAP}}


def _construct(copied, bank_pins, bounds):
    catalog, work = _catalog(copied["original_banks"])
    schedule = _schedule(copied["original_banks"], copied["epochs"], catalog, bounds)
    _, cat_wire = _plain(catalog, bounds, bounds["max_report_bytes"])
    _, schedule_wire = _plain(schedule, bounds, bounds["max_report_bytes"])
    return {"catalog": catalog, "catalog_sha256": _sha(cat_wire), "schedule": schedule,
        "schedule_sha256": _sha(schedule_wire), "bank_commitments": [
            {"bank_id": bank["bank_id"], "original_bank_sha256": pin}
            for bank, pin in zip(copied["original_banks"], bank_pins, strict=True)], "catalog_work": work}


def prepare_shared_source_replay_commitments_v1(original_banks, epochs, *, limits=None):
    """Bounded content/plan identities only; no source validator or parser runs."""
    bounds = _limits(limits)
    copied, frozen, pins = _capture(original_banks, epochs, bounds)
    def fence():
        _need(_limits(limits) == bounds, "caller limits changed during commitments")
        _need(_capture(original_banks, epochs, bounds)[1] == frozen, "caller original/epoch inputs changed")
        _need(_capture(copied["original_banks"], copied["epochs"], bounds)[1] == frozen, "detached commitment inputs changed")
    failure = None
    try:
        return _plain(_construct(copied, pins, bounds), bounds, bounds["max_report_bytes"])[0]
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing catalog commitment input/limit check also failed.")


def _request(raw, expected, bounds):
    """Bound raw request before JSON parsing, then require its exact wire."""
    _need(type(raw) is bytes and 0 < len(raw) <= bounds["max_request_bytes"], "bounded immutable replay request required")
    def pairs(items):
        value = {}
        for key, child in items:
            _need(key not in value, "duplicate replay request JSON key")
            value[key] = child
        return value
    def constant(_):
        raise SharedSourceReplayError("nonfinite replay request refused")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError) as error:
        if isinstance(error, SharedSourceReplayError):
            raise
        raise SharedSourceReplayError("ordinary replay request JSON required") from error
    # Parse a bounded raw request to discover the epoch graph, but do not hash
    # or serialize the full request until the combined original root is bounded.
    value = _bounded(correspondence._Budget(bounds, bounds["max_request_bytes"]).copy, value)
    _keys(value, _REQUEST, "shared replay request")
    _need(value["schema"] == REQUEST_SCHEMA and value["profile"] == PROFILE, "shared replay request domain differs")
    _epochs(value["epochs"], bounds)
    # expected SHA is checked only after the complete original root is bounded.
    return value


def prepare_shared_source_replay_v1(packet, source_request_raw, replay_request_raw, *, expected_packet_sha256,
        expected_source_request_sha256, expected_replay_request_sha256, original_banks, limits=None):
    """Regenerate the source packet once, catalog originals and retain a plan."""
    bounds = _limits(limits)
    request = _request(replay_request_raw, expected_replay_request_sha256, bounds)
    copied, frozen, pins = _capture(original_banks, request["epochs"], bounds,
        packet=packet, source_request_raw=source_request_raw, replay_request_raw=replay_request_raw, extra=request)
    def fence():
        _need(_limits(limits) == bounds, "caller limits changed during shared replay preparation")
        _need(_capture(original_banks, request["epochs"], bounds, packet=packet,
            source_request_raw=source_request_raw, replay_request_raw=replay_request_raw, extra=request)[1] == frozen,
            "caller originals or replay request changed")
        _need(_capture(copied["original_banks"], copied["epochs"], bounds, packet=copied["packet"],
            source_request_raw=copied["source_request_raw"], replay_request_raw=copied["replay_request_raw"], extra=copied["extra"])[1] == frozen,
            "detached shared replay inputs changed")
    failure = None
    try:
        for value, label in ((expected_packet_sha256, "source packet"), (expected_source_request_sha256, "source request"),
                (expected_replay_request_sha256, "replay request")):
            _digest(value, label)
        _need(_sha(replay_request_raw) == expected_replay_request_sha256, "independent replay request SHA differs")
        _need(_wire(copied["extra"]) == copied["replay_request_raw"],
              "canonical compact replay request without final LF required")
        built = _construct(copied, pins, bounds)
        for key in ("catalog_sha256", "schedule_sha256", "bank_commitments"):
            _need(_wire(copied["extra"][key]) == _wire(built[key]), "independent catalog/schedule/bank commitment differs: " + key)
        checked = correspondence.validate_source_correspondence_requests_v1(copied["packet"], copied["source_request_raw"],
            expected_report_sha256=expected_packet_sha256, expected_request_sha256=expected_source_request_sha256,
            original_banks=copied["original_banks"], limits=_delegate_limits(bounds))
        work = built["catalog_work"]
        report = {"schema": SCHEMA, "profile": PROFILE, "status": "cataloged_originals_planned_schedule_only",
            "source_packet_sha256": expected_packet_sha256, "source_request_sha256": expected_source_request_sha256,
            "replay_request_sha256": expected_replay_request_sha256, "replay_request": copied["extra"],
            "source_packet": checked, "catalog": built["catalog"], "catalog_sha256": built["catalog_sha256"],
            "schedule": built["schedule"], "schedule_sha256": built["schedule_sha256"],
            "physical_references": checked["physical_rows"],
            "work": {"source_packet_validation_calls": 1, "source_bank_preparations": len(copied["original_banks"]),
                "catalog_raw_body_parses": 0, "history_epoch_replays": 0, "authority_memoizations": 0,
                "catalog_construction_scope": "one complete catalog construction pass; outer custody/hash helpers may run additional passes",
                "catalog_body_sha256_calls_per_construction_pass": work["body_sha256_calls"],
                "catalog_body_sha256_input_bytes_per_construction_pass": work["body_sha256_input_bytes"],
                "catalog_equality_comparisons_per_construction_pass": work["equality_comparisons"],
                "catalog_compared_candidate_bytes_upper_bound_per_construction_pass": work["compared_candidate_bytes_upper_bound"],
                "planned_candidate_occurrence_references": checked["coverage"]["candidate_occurrence_references"] * len(copied["epochs"])},
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
            BaseException.add_note(failure, "A closing shared replay original/limit comparison also failed.")


def shared_source_replay_sha256(report, *, limits=None):
    """Bounded report identity only; no source validation or planned work runs."""
    bounds = _limits(limits)
    return _sha(_plain(report, bounds, bounds["max_report_bytes"])[1])


def validate_shared_source_replay_v1(report, packet, source_request_raw, replay_request_raw, *, expected_report_sha256,
        expected_packet_sha256, expected_source_request_sha256, expected_replay_request_sha256, original_banks, limits=None):
    """Regenerate the complete catalog/plan/source report from original bodies."""
    bounds = _limits(limits)
    request = _request(replay_request_raw, expected_replay_request_sha256, bounds)
    extras = {"request": request, "offered_report": report}
    copied, frozen, _ = _capture(original_banks, request["epochs"], bounds, packet=packet,
        source_request_raw=source_request_raw, replay_request_raw=replay_request_raw, extra=extras)
    def fence():
        _need(_limits(limits) == bounds, "caller limits changed during shared replay validation")
        _need(_capture(original_banks, request["epochs"], bounds, packet=packet,
            source_request_raw=source_request_raw, replay_request_raw=replay_request_raw, extra=extras)[1] == frozen,
            "caller originals or offered report changed during validation")
        _need(_capture(copied["original_banks"], copied["epochs"], bounds, packet=copied["packet"],
            source_request_raw=copied["source_request_raw"], replay_request_raw=copied["replay_request_raw"], extra=copied["extra"])[1] == frozen,
            "detached shared replay validation inputs changed")
    failure = None
    try:
        _digest(expected_report_sha256, "shared replay report")
        checked, raw = _plain(copied["extra"]["offered_report"], bounds, bounds["max_report_bytes"])
        _need(_sha(raw) == expected_report_sha256, "independent shared replay report SHA differs")
        expected = prepare_shared_source_replay_v1(copied["packet"], copied["source_request_raw"], copied["replay_request_raw"],
            expected_packet_sha256=expected_packet_sha256, expected_source_request_sha256=expected_source_request_sha256,
            expected_replay_request_sha256=expected_replay_request_sha256, original_banks=copied["original_banks"], limits=bounds)
        _need(_wire(expected) == raw, "shared replay report differs from complete original regeneration")
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
            BaseException.add_note(failure, "A closing shared replay validation original/limit comparison also failed.")


__all__ = ["SharedSourceReplayError", "prepare_shared_source_replay_commitments_v1",
    "prepare_shared_source_replay_v1", "shared_source_replay_sha256", "validate_shared_source_replay_v1"]
