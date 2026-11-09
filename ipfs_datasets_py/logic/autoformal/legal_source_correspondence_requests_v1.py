"""Complete declared physical cache references to existing source review requests.

This adapter replays the supplied original joins, receipt bytes, paired records
and complete stored text through the existing source-review owner. Cache table
coordinates are pinned declarations supplied by the caller, not a fresh read of
cache Parquet originals. Repeated physical references are never merged merely
because their paired bytes or logical request agree. There is no review, trust,
selection, governing-source adoption, model, database or prover operation here.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import corpus_legacy_source_review as review

REQUEST_SCHEMA = "legal-source-correspondence-request/v1"
SCHEMA = "legal-source-correspondence-requests/v1"
PROFILE = "complete-declared-physical-source-review-requests/v1"
DEFAULT_LIMITS = {"max_banks": 16, "max_physical_rows": 256,
    "max_original_bytes": 64 * 1024**2, "max_report_bytes": 32 * 1024**2,
    "max_request_bytes": 256 * 1024, "max_json_nodes": 1_000_000,
    "max_json_depth": 48, "max_string_bytes": 512 * 1024}
AUTHORITY = dict.fromkeys(("source_correspondence_verified", "physical_cache_originals_verified",
    "original_producer_occurrence_attested", "source_authority_authenticated",
    "remote_revision_authenticated", "source_semantics_verified",
    "official_edition_correspondence_verified", "current_source_release_correspondence_verified",
    "source_review_completed", "source_review_decisions_applied", "governing_source_adoption_applied",
    "context_closure_verified", "context_permission_verified", "global_holdout_verified",
    "training_qualified", "evaluation_gold_qualified", "Lean_admitted", "source_equivalence_proven",
    "convergence_proved", "admitted", "formalized", "proof_authority", "model_executed",
    "training_executed", "database_executed", "prover_executed"), False)
LIMITATIONS = [
    "Coverage is exactly the complete independently pinned supplied bank and physical-reference population; no whole-cache or whole-corpus discovery is performed.",
    "Physical cache coordinates are supplied declarations bound by this request, not fresh verification of cache Parquet bytes or authentication of remote history.",
    "Existing join replay verifies supplied original paired/receipt/stored-text custody and preserves every candidate; it does not attest the producer's intended character occurrence or governing edition.",
    "Source review questions remain unanswered. Source adoption, legal interpretation, context closure, genuine definition/use review and separately authorized applied effects remain unavailable.",
    "The nine active and seven deferred questions, complete original sections, alternatives and unresolved dispositions remain in each unchanged preparation.",
    "Equal paired bytes or source text never merge physical references. No SourcePartitions, split, inference permission, training target, Lean admission or convergence authority is assigned.",
    "Closing comparisons observe caller-owned inputs at defined boundaries; they are not an OS sandbox, atomic multi-file snapshot or attestation against arbitrary monkeypatching.",
]
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_BANK = {"bank_id", "join_bytes", "paired_row_bytes", "join_inputs", "physical_rows"}
_JOIN = {"expected_population", "producer_receipt_bytes", "expected_producer_receipt_sha256",
    "source_sections", "expected_source_sections"}
_POPULATION = {"row_sha256", "source_span_id", "text_sha256", "source_revision"}
_SECTION = {"repository_id", "revision", "path_in_repo", "artifact_sha256", "artifact_bytes",
    "release_id", "parquet_row_index", "entry_cid", "legal_id", "text_sha256"}
_PHYSICAL = {"repository_id", "revision", "path_in_repo", "artifact_sha256", "row_ordinal"}
_ROW = {"physical_row_ordinal", "request_ordinal", "physical_identity"}
_REQUEST = {"schema", "profile", "banks"}
_REQUEST_BANK = {"bank_id", "original_bank_sha256", "physical_rows", "logical_rows"}


class SourceCorrespondenceRequestsError(ValueError):
    """A bounded original, declaration population, or complete replay differs."""


def _need(condition, message):
    if not condition:
        raise SourceCorrespondenceRequestsError(message)


def _keys(value, expected, label):
    _need(type(value) is dict and len(value) == len(expected) and
          all(type(key) is str for key in value) and set(value) == expected,
          "closed " + label + " required")


def _integer(value, maximum, label):
    _need(type(value) is int and 0 <= value <= maximum, "plain bounded integer required: " + label)


def _digest(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None, "lowercase SHA256 required: " + label)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _limits(value):
    _need(value is None or type(value) is dict, "closed lower-only limits required")
    _need(value is None or (len(value) <= len(DEFAULT_LIMITS) and
          all(type(key) is str for key in value)), "plain bounded limit keys required")
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        _need(key in result and type(bound) is int and 0 < bound <= result[key],
              "unknown, noninteger or raised bound")
        result[key] = bound
    return result


class _Budget:
    """Bound traversal, scalar encoding, bytes and punctuation before full wire."""
    def __init__(self, limits, maximum):
        self.limits = limits
        self.maximum = maximum
        self.nodes = self.used = 0
        self.active = set()

    def charge(self, amount):
        _need(amount <= self.maximum - self.used, "complete aggregate byte bound exceeded")
        self.used += amount

    def copy(self, item, depth=0, *, bytes_allowed=False):
        self.nodes += 1
        _need(self.nodes <= self.limits["max_json_nodes"] and depth <= self.limits["max_json_depth"],
              "complete JSON node or depth bound exceeded")
        kind = type(item)
        if kind is bytes and bytes_allowed:
            self.charge(len(item))
            return item
        if kind is str:
            _need(len(item) <= min(self.limits["max_string_bytes"], self.maximum - self.used),
                  "string character or remaining byte bound exceeded")
            try:
                _need(len(item.encode("utf-8")) <= self.limits["max_string_bytes"],
                      "individual UTF8 string byte bound exceeded")
                raw = json.dumps(item, ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (UnicodeError, ValueError) as error:
                raise SourceCorrespondenceRequestsError("ordinary UTF8 string required") from error
            self.charge(len(raw))
            return item
        if item is None or kind is bool:
            self.charge(4 if item is None or item is True else 5)
            return item
        if kind is int:
            _need(-(2**63) <= item < 2**63, "signed64 JSON integer required")
            self.charge(len(str(item)))
            return item
        _need(kind in (dict, list), "plain finite JSON or designated immutable bytes required")
        _need(len(item) <= self.limits["max_json_nodes"], "collection node bound exceeded")
        identity = id(item)
        _need(identity not in self.active, "cyclic input collection refused")
        self.active.add(identity)
        try:
            self.charge(2 + max(0, len(item) - 1))
            if kind is list:
                return [self.copy(child, depth + 1, bytes_allowed=bytes_allowed) for child in item]
            copied = {}
            for key, child in item.items():
                _need(type(key) is str and len(key) <= 4096, "bounded string JSON keys required")
                self.charge(1)
                copied[self.copy(key, depth + 1)] = self.copy(child, depth + 1, bytes_allowed=bytes_allowed)
            return copied
        finally:
            self.active.remove(identity)


def _plain(value, bounds, maximum):
    copied = _Budget(bounds, maximum).copy(value)
    raw = _wire(copied)
    _need(len(raw) <= maximum, "complete canonical byte bound exceeded")
    return copied, raw


def _string(value, label):
    _need(type(value) is str and 0 < len(value) <= 4096, "bounded nonempty string required: " + label)


def _shape(banks, bounds):
    """Refuse collection/scalar shapes before any input hashing or cloning."""
    _need(type(banks) is list and 0 < len(banks) <= bounds["max_banks"], "complete bounded bank list required")
    bank_ids, physical_total = set(), 0
    for bank in banks:
        _keys(bank, _BANK, "original bank")
        _string(bank["bank_id"], "bank identity")
        _need(bank["bank_id"] not in bank_ids, "duplicate bank identity")
        bank_ids.add(bank["bank_id"])
        raw, rows, inputs, physical = (bank[key] for key in
            ("join_bytes", "paired_row_bytes", "join_inputs", "physical_rows"))
        _need(type(raw) is bytes and 0 < len(raw) <= 1024**2, "bounded immutable original join bytes required")
        _need(type(rows) is list and 0 < len(rows) <= 64 and
              all(type(row) is bytes and 0 < len(row) <= 1024**2 for row in rows),
              "complete bounded immutable logical paired rows required")
        _need(sum(map(len, rows)) <= 1024**2, "existing paired-row aggregate bound exceeded")
        _keys(inputs, _JOIN, "original legacy join arguments")
        population, sections, expected = (inputs[key] for key in
            ("expected_population", "source_sections", "expected_source_sections"))
        _need(type(population) is list and len(population) == len(rows), "complete logical population required")
        for pin in population:
            _keys(pin, _POPULATION, "expected logical population row")
            for key in ("row_sha256", "text_sha256"):
                _digest(pin[key], key)
            for key in ("source_span_id", "source_revision"):
                _string(pin[key], key)
        receipt = inputs["producer_receipt_bytes"]
        pin = inputs["expected_producer_receipt_sha256"]
        _need((receipt is None and pin is None) or (type(receipt) is bytes and
              0 < len(receipt) <= 32 * 1024**2), "bounded immutable producer receipt or explicit null pair required")
        if receipt is not None:
            _digest(pin, "producer receipt")
        _need(type(sections) is list and type(expected) is list and len(sections) == len(expected) <= 64,
              "complete bounded source section population required")
        for values, has_text in ((sections, True), (expected, False)):
            for section in values:
                _keys(section, _SECTION | ({"text"} if has_text else set()), "source section")
                for key, value in section.items():
                    if key in ("artifact_bytes", "parquet_row_index"):
                        _integer(value, 2**63 - 1, key)
                    else:
                        _need(type(value) is str, "plain source section string required")
        _need(type(physical) is list and 0 < len(physical) <= bounds["max_physical_rows"],
              "complete bounded ordered physical row list required")
        physical_total += len(physical)
        _need(physical_total <= bounds["max_physical_rows"], "complete physical population exceeds bound")
        mapped, coordinates = set(), set()
        for ordinal, row in enumerate(physical):
            _keys(row, _ROW, "declared physical row")
            _integer(row["physical_row_ordinal"], len(physical) - 1, "physical row ordinal")
            _need(row["physical_row_ordinal"] == ordinal, "complete physical row order required")
            _integer(row["request_ordinal"], len(rows) - 1, "logical request ordinal")
            mapped.add(row["request_ordinal"])
            identity = row["physical_identity"]
            _keys(identity, _PHYSICAL, "declared physical identity")
            for key in ("repository_id", "path_in_repo"):
                _string(identity[key], key)
            _need(type(identity["revision"]) is str and _REVISION.fullmatch(identity["revision"]) is not None,
                  "complete immutable declared cache revision required")
            _digest(identity["artifact_sha256"], "declared cache artifact")
            _integer(identity["row_ordinal"], 2**63 - 1, "declared cache row ordinal")
            path = identity["path_in_repo"]
            _need(not path.startswith("/") and "\\" not in path and "\x00" not in path and all(
                  part not in ("", ".", "..") for part in path.split("/")), "relative declared cache path required")
            coordinate = tuple(identity[key] for key in sorted(_PHYSICAL))
            _need(coordinate not in coordinates, "duplicate declared physical identity within bank")
            coordinates.add(coordinate)
        _need(mapped == set(range(len(rows))), "every logical request must retain a physical reference")


def _descriptor(raw):
    return None if raw is None else {"bytes": len(raw), "sha256": _sha(raw)}


def _commitment(bank):
    return {"bank_id": bank["bank_id"], "join_bytes": _descriptor(bank["join_bytes"]),
        "paired_row_bytes": [_descriptor(raw) for raw in bank["paired_row_bytes"]],
        "join_inputs": {**bank["join_inputs"],
            "producer_receipt_bytes": _descriptor(bank["join_inputs"]["producer_receipt_bytes"])},
        "physical_rows": bank["physical_rows"]}


def _capture(banks, bounds):
    _shape(banks, bounds)
    copied = _Budget(bounds, bounds["max_original_bytes"]).copy(banks, bytes_allowed=True)
    # All graph and aggregate byte bounds precede hashing even a receipt body.
    commitments = [_commitment(bank) for bank in copied]
    physical_commitments = {}
    for bank, commitment in zip(copied, commitments, strict=True):
        for row in bank["physical_rows"]:
            coordinate = tuple(row["physical_identity"][key] for key in sorted(_PHYSICAL))
            digest = commitment["paired_row_bytes"][row["request_ordinal"]]["sha256"]
            _need(coordinate not in physical_commitments or physical_commitments[coordinate] == digest,
                  "conflicting paired-row commitments for one declared physical identity")
            physical_commitments[coordinate] = digest
    raw = _wire(commitments)
    _need(len(raw) <= bounds["max_original_bytes"], "complete commitment byte bound exceeded")
    return copied, raw, [_sha(_wire(item)) for item in commitments]


def source_correspondence_original_bank_sha256(bank, *, limits=None):
    """Identity of bounded originals/declarations only; no delegate is called.

    Replace join bytes and each paired-row byte value with {bytes, sha256}, and
    replace producer_receipt_bytes likewise (or null). Retain every other value,
    then hash compact sorted Unicode UTF8 JSON without LF. The external request
    must be independently pinned; this helper does not authenticate its origin.
    """
    return _capture([bank], _limits(limits))[2][0]


def _request(raw, expected, banks, pins, bounds):
    _digest(expected, "request")
    _need(type(raw) is bytes and 0 < len(raw) <= bounds["max_request_bytes"],
          "bounded immutable canonical request bytes required")
    _need(_sha(raw) == expected, "independent request bytes SHA256 differs")
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "duplicate request JSON key")
            result[key] = value
        return result
    def constant(_):
        raise SourceCorrespondenceRequestsError("nonfinite request JSON refused")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        value, canonical = _plain(value, bounds, bounds["max_request_bytes"])
    except (ValueError, RecursionError) as error:
        if isinstance(error, SourceCorrespondenceRequestsError):
            raise
        raise SourceCorrespondenceRequestsError("ordinary canonical request JSON required") from error
    _need(canonical == raw, "request must be canonical compact JSON without final LF")
    _keys(value, _REQUEST, "source correspondence request")
    _need(value["schema"] == REQUEST_SCHEMA and value["profile"] == PROFILE,
          "source correspondence request domain differs")
    members = value["banks"]
    _need(type(members) is list and len(members) == len(banks), "complete ordered request bank population required")
    for declaration, bank, pin in zip(members, banks, pins, strict=True):
        _keys(declaration, _REQUEST_BANK, "request bank commitment")
        _integer(declaration["physical_rows"], bounds["max_physical_rows"], "declared physical count")
        _integer(declaration["logical_rows"], 64, "declared logical count")
        _need(declaration == {"bank_id": bank["bank_id"], "original_bank_sha256": pin,
              "physical_rows": len(bank["physical_rows"]), "logical_rows": len(bank["paired_row_bytes"])},
              "original bank commitment, count or order differs")
    return value


def _ref(record):
    return {"record_cid": record["record_cid"], "sha256": _sha(_wire(record))}


def prepare_source_correspondence_requests_v1(request_raw, *, expected_request_sha256,
        original_banks, limits=None):
    """Replay every supplied bank once and preserve all physical references.

    Logical paired rows retain the existing owner's unique-byte constraint.
    Multiple distinct physical rows may reference one logical request, and the
    same physical declaration may recur across banks. Nothing is deduplicated
    in the output. Every logical request needs at least one physical reference.
    """
    bounds = _limits(limits)
    banks, frozen, pins = _capture(original_banks, bounds)
    request = _request(request_raw, expected_request_sha256, banks, pins, bounds)
    def fence():
        _need(_limits(limits) == bounds, "caller limits changed during operation")
        _need(_capture(original_banks, bounds)[1] == frozen, "original banks changed during operation")
        _need(_capture(banks, bounds)[1] == frozen, "detached original banks changed during replay")
    failure = None
    try:
        prepared, physical_rows = [], []
        distinct_sources, distinct_physical = set(), set()
        logical_total = source_total = 0
        for bank_ordinal, (bank, pin) in enumerate(zip(banks, pins, strict=True)):
            bundle = review.prepare_legacy_source_review_requests(bank["join_bytes"],
                bank["paired_row_bytes"], expected_join_sha256=_sha(bank["join_bytes"]),
                **bank["join_inputs"])
            # Preserve the delegate's unchanged 8 MiB complete-collection cap.
            bundle, _ = _plain(bundle, bounds, min(review.MAX_COLLECTION_BYTES, bounds["max_report_bytes"]))
            prepared.append({"bank_id": bank["bank_id"], "bank_ordinal": bank_ordinal,
                             "original_bank_sha256": pin, "preparation": bundle})
            logical_total += len(bundle["requests"])
            source_total += len(bundle["source_sections"])
            for section in bundle["source_sections"]:
                provenance = section["provenance"]
                distinct_sources.add(tuple(provenance[key] for key in
                    ("repository_id", "revision", "path_in_repo", "artifact_sha256", "parquet_row_index")))
            for declared in bank["physical_rows"]:
                ordinal = declared["request_ordinal"]
                unit, subject = bundle["requests"][ordinal], bundle["subjects"][ordinal]
                original = unit["original_row"]
                identity = declared["physical_identity"]
                distinct_physical.add(tuple(identity[key] for key in sorted(_PHYSICAL)))
                physical_rows.append({"bank_id": bank["bank_id"], "bank_ordinal": bank_ordinal,
                    **declared, "paired_row_sha256": _sha(bank["paired_row_bytes"][ordinal]),
                    "request_ref": _ref(unit), "subject_ref": _ref(subject),
                    "preparation_manifest_sha256": _sha(_wire(bundle["manifest"])),
                    "source_disposition": original["disposition"], "candidate_count": original["occurrence_count"],
                    "candidate_occurrence_ids": [item["source_occurrence"]["record_cid"] for item in original["candidates"]],
                    "selected_occurrence": None, "governing_source": None,
                    "training_mask": 0, "evaluation_gold_mask": 0, "inference_view": None})
            # Check aggregate output incrementally, not only after all banks.
            _plain({"banks": prepared, "physical_rows": physical_rows}, bounds, bounds["max_report_bytes"])
            fence()
        dispositions = sorted({row["source_disposition"] for row in physical_rows})
        report = {"schema": SCHEMA, "profile": PROFILE, "status": "complete_declared_source_review_requests",
            "request_sha256": expected_request_sha256, "request": request,
            "banks": prepared, "physical_rows": physical_rows,
            "coverage": {"banks": len(prepared), "logical_requests": logical_total,
                "physical_rows": len(physical_rows), "distinct_physical_identities": len(distinct_physical),
                "source_section_references": source_total, "distinct_source_sections": len(distinct_sources),
                "candidate_occurrence_references": sum(row["candidate_count"] for row in physical_rows),
                "unique_candidate_rows": sum(row["candidate_count"] == 1 for row in physical_rows),
                "ambiguous_candidate_rows": sum(row["candidate_count"] > 1 for row in physical_rows),
                "disposition_counts": {key: sum(row["source_disposition"] == key for row in physical_rows) for key in dispositions},
                "selected_occurrences": 0, "source_decisions_applied": 0, "full_declared_population_retained": True},
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
            BaseException.add_note(failure, "A closing source-correspondence original/limit comparison also failed.")


def source_correspondence_requests_sha256(report, *, limits=None):
    """Bounded canonical report identity only; not original-input validation."""
    bounds = _limits(limits)
    return _sha(_plain(report, bounds, bounds["max_report_bytes"])[1])


def validate_source_correspondence_requests_v1(report, request_raw, *, expected_report_sha256,
        expected_request_sha256, original_banks, limits=None):
    """Regenerate all original banks and compare the entire canonical report."""
    bounds = _limits(limits)
    _digest(expected_report_sha256, "report")
    checked, raw = _plain(report, bounds, bounds["max_report_bytes"])
    _need(_sha(raw) == expected_report_sha256, "independent report SHA256 differs")
    expected = prepare_source_correspondence_requests_v1(request_raw,
        expected_request_sha256=expected_request_sha256, original_banks=original_banks, limits=limits)
    _need(_plain(expected, bounds, bounds["max_report_bytes"])[1] == raw,
          "source correspondence report differs from complete original-input regeneration")
    return checked


__all__ = ["SourceCorrespondenceRequestsError", "source_correspondence_original_bank_sha256",
    "prepare_source_correspondence_requests_v1", "source_correspondence_requests_sha256",
    "validate_source_correspondence_requests_v1"]
# Explicit original-input coordinate graph custody beside unchanged declared v1.
from pathlib import Path as _V2Path

REQUEST_SCHEMA_V2 = "legal-source-correspondence-request/v2"
SCHEMA_V2 = "legal-source-correspondence-requests/v2"
PROFILE_V2 = "original-input-coordinate-graph-v2-source-review-request-custody/v1"
DEFAULT_LIMITS_V2 = {**DEFAULT_LIMITS, "max_report_bytes": 64 * 1024**2}
_V2_GRAPH_FIELDS = {"request_raw", "eligibility_report_raw", "eligibility_request_raw",
    "join_manifest_raw", "expected_request_sha256", "join_originals", "source_bindings"}
_V2_REQUEST_FIELDS = {"schema", "profile", "graph_report_raw_sha256", "graph_report_sha256",
    "graph_originals_sha256", "source_request_sha256", "physical_review_nominations"}
_V2_SELF_PIN = _sha(_V2Path(__file__).read_bytes())
_V2_OWNER_PINS = None
_V2_AUTHORITY_KEYS = frozenset((
    "source_correspondence_verified", "physical_cache_originals_verified",
    "original_producer_occurrence_attested", "source_authority_authenticated",
    "remote_revision_authenticated", "source_semantics_verified",
    "official_edition_correspondence_verified", "current_source_release_correspondence_verified",
    "source_review_completed", "source_review_decisions_applied", "governing_source_adoption_applied",
    "context_closure_verified", "context_permission_verified", "global_holdout_verified",
    "training_qualified", "evaluation_gold_qualified", "Lean_admitted", "source_equivalence_proven",
    "convergence_proved", "admitted", "formalized", "proof_authority", "model_executed",
    "training_executed", "database_executed", "prover_executed"))
_V2_REVIEW_FALSE_KEYS = frozenset(review.FALSE_FLAGS)


def _v2_false_mapping(value, keys):
    _keys(value, keys, "unchanged false authority mapping")
    _need(all(flag is False for flag in value.values()), "v2 source custody cannot promote authority")


def _v2_check_authority(authority_keys=_V2_AUTHORITY_KEYS, review_keys=_V2_REVIEW_FALSE_KEYS):
    """Mutable legacy globals cannot promote either original or new reports."""
    _v2_false_mapping(AUTHORITY, authority_keys)
    _v2_false_mapping(review.FALSE_FLAGS, review_keys)


def _v2_unprivileged(value, *, v2=False, authority_keys=_V2_AUTHORITY_KEYS,
                     review_keys=_V2_REVIEW_FALSE_KEYS):
    _v2_false_mapping(value["authority"], authority_keys)
    for key in ("training_mask", "evaluation_gold_mask"):
        _need(type(value[key]) is int and value[key] == 0, "v2 root masks must remain integer zero")
    if v2:
        _need(all(value[key] is None for key in
                  ("selected_occurrence", "governing_source", "governing_definition_use")),
              "v2 root source and governing selections remain null")
        groups = (value["physical_review_bindings"], value["output_occurrence_bindings"])
    else:
        _need(value["inference_view"] is None, "v1 source inference view remains unavailable")
        groups = (value["physical_rows"],)
        for bank in value["banks"]:
            preparation = bank["preparation"]
            records = [preparation["manifest"], *preparation["requests"], *preparation["subjects"]]
            for record in records:
                _need(all(record[key] is False for key in review_keys)
                      and all(record[key] is None for key in
                              ("selected_occurrence", "governing_source", "selected_meaning")),
                      "existing source-review authority and selections must remain unavailable")
    for group in groups:
        for row in group:
            _need(row["selected_occurrence"] is None and row["governing_source"] is None,
                  "v2 physical/output source selection remains null")
            keys = ("source_binding_mask", "training_mask", "evaluation_gold_mask") if v2 else (
                "training_mask", "evaluation_gold_mask")
            _need(all(type(row[key]) is int and row[key] == 0 for key in keys),
                  "v2 physical/output masks must remain integer zero")


def _v2_limits(value):
    _need(value is None or type(value) is dict, "closed lower-only v2 limits required")
    result = dict(DEFAULT_LIMITS_V2)
    for key, maximum in (value or {}).items():
        _need(type(key) is str and key in result and type(maximum) is int
              and 0 < maximum <= result[key], "unknown, raised or noninteger v2 limit")
        result[key] = maximum
    return result


def _v2_snapshot(value, bounds):
    """One finite original population; repeated storage still counts repeatedly."""
    detached = _Budget(bounds, bounds["max_original_bytes"]).copy(value, bytes_allowed=True)
    digest = hashlib.sha256()

    def add(tag, raw):
        digest.update(tag + str(len(raw)).encode("ascii") + b":" + raw)

    def visit(item):
        if type(item) is bytes:
            add(b"b", item)
        elif type(item) is dict:
            add(b"d", str(len(item)).encode("ascii"))
            for key in sorted(item):
                visit(key)
                visit(item[key])
        elif type(item) is list:
            add(b"l", str(len(item)).encode("ascii"))
            for child in item:
                visit(child)
        else:
            add(b"j", _wire(item))
    visit(detached)
    return detached, digest.hexdigest()


def _v2_plain(value, bounds):
    """Only the designated graph carrier has its separate large string cap."""
    _need(type(value) is dict, "plain v2 report mapping required")
    budget = _Budget(bounds, bounds["max_report_bytes"])
    budget.charge(2 + max(0, len(value) - 1))
    copied = {}
    for key, child in value.items():
        _need(type(key) is str, "ordinary v2 report key required")
        budget.charge(1)
        copied[budget.copy(key, 1)] = None
        if key == "graph_report_raw_utf8":
            _need(type(child) is str, "exact UTF8 graph carrier required")
            remaining = budget.maximum - budget.used
            _need(len(child) <= DEFAULT_LIMITS_V2["max_report_bytes"]
                  and len(child) + 2 <= remaining,
                  "graph carrier character or remaining byte cap exceeded before encoding")
            try:
                raw = child.encode("utf-8")
                _need(len(raw) <= DEFAULT_LIMITS_V2["max_report_bytes"]
                      and len(raw) + 2 <= remaining, "graph carrier UTF8 byte cap exceeded")
                encoded = json.dumps(child, ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (ValueError, UnicodeError) as error:
                raise SourceCorrespondenceRequestsError("ordinary UTF8 graph carrier required") from error
            _need(len(raw) <= DEFAULT_LIMITS_V2["max_report_bytes"], "graph carrier byte cap exceeded")
            budget.nodes += 1
            _need(budget.nodes <= bounds["max_json_nodes"], "v2 report node cap exceeded")
            budget.charge(len(encoded))
            copied[key] = child
        else:
            copied[key] = budget.copy(child, 1)
    raw = _wire(copied)
    _need(len(raw) <= bounds["max_report_bytes"], "complete v2 report byte cap exceeded")
    return copied, raw


def _v2_parse(raw, maximum, bounds, label, *, canonical=False):
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded exact " + label + " bytes required")
    def pairs(items):
        result = {}
        for key, child in items:
            _need(key not in result, "duplicate " + label + " JSON key")
            result[key] = child
        return result
    def constant(_):
        raise SourceCorrespondenceRequestsError("nonfinite " + label + " JSON refused")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        if label == "graph report":
            # Its nested artifact strings have their upstream bounds; genuine
            # graph replay, not this outer parser, verifies that original body.
            parsing = {**bounds, "max_string_bytes": 64 * 1024**2,
                       "max_json_depth": max(bounds["max_json_depth"], 96)}
        else:
            parsing = bounds
        copied, normalized = _plain(value, parsing, maximum)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, SourceCorrespondenceRequestsError):
            raise
        raise SourceCorrespondenceRequestsError("ordinary " + label + " JSON required") from error
    _need(not canonical or normalized == raw, "canonical compact " + label + " bytes required")
    return copied


def _v2_owners():
    from . import corpus_proposed_graph_adapter as corpus
    from . import legal_span_cache_intake as intake
    from . import legal_source_span_target_eligibility_v1 as eligibility
    _need(callable(getattr(intake, "validate_coordinate_source_graph_intake_v2", None)),
          "explicit graph-v2 owner required without historical fallback")
    return corpus, intake, eligibility


def _v2_sources(owners):
    modules = (*owners, review, review.joins, review.contracts, review.questions,
               review.wording, review.dependencies, review.review)
    root = _V2Path(__file__).resolve().parents[3]
    pins = {}
    for module in modules:
        path = _V2Path(module.__file__).resolve()
        _need(path == root.joinpath(*module.__name__.split(".")).with_suffix(".py"),
              "v2 correspondence owner escaped selected source tree")
        pins[str(path)] = _sha(path.read_bytes())
    path = _V2Path(__file__).resolve()
    _need(_sha(path.read_bytes()) == _V2_SELF_PIN, "v2 correspondence source changed since import")
    pins[str(path)] = _V2_SELF_PIN
    global _V2_OWNER_PINS
    if _V2_OWNER_PINS is None:
        _V2_OWNER_PINS = dict(pins)
    _need(pins == _V2_OWNER_PINS, "v2 correspondence owners changed since first use")
    return pins


def _v2_callbacks(owners):
    corpus, intake, eligibility = owners
    return (*intake._coordinate_graph_callables(eligibility, eligibility_version=3),
        intake.validate_coordinate_source_graph_intake_v2,
        corpus.coordinate_graph_corpus_originals_sha256, corpus._corpus_intake_inputs,
        prepare_source_correspondence_requests_v1, validate_source_correspondence_requests_v1,
        source_correspondence_requests_sha256, source_correspondence_original_bank_sha256,
        review.prepare_legacy_source_review_requests, review.validate_legacy_source_review_requests,
        review.joins.validate_legacy_source_join, review.joins.build_legacy_source_join,
        review.questions._questions,
        prepare_source_correspondence_requests_v2, validate_source_correspondence_requests_v2,
        source_correspondence_requests_v2_sha256, _v2_sources, _v2_callbacks,
        _v2_snapshot, _v2_plain, _v2_parse, _v2_limits, _v2_fence, _v2_rows,
        _v2_bindings, _v2_finish, _v2_false_mapping, _v2_check_authority,
        _v2_unprivileged, _capture, _request, _plain, _shape, _wire, _sha,
        _need, _keys, _integer, _digest)


def _v2_finish(checks, primary):
    failures = []
    for label, operation in checks:
        try:
            operation()
        except BaseException as error:
            failures.append((label, error))
    if primary is not None:
        for label, error in failures:
            primary.add_note("secondary v2 correspondence failure (" + label + "): "
                             + type(error).__name__ + ": " + str(error)[:512])
    elif failures:
        label, error = failures[0]
        error.add_note("closing v2 correspondence guard: " + label)
        for other, failure in failures[1:]:
            error.add_note("secondary closing guard (" + other + "): " + str(failure)[:512])
        raise error


def _v2_fence(original, detached, commitment, limits, bounds, owners, pins, callbacks):
    _need(all(any(function is expected for expected in callbacks) for function in
              (_v2_fence, _v2_snapshot, _v2_sources, _v2_callbacks, _v2_limits,
               _v2_false_mapping, _v2_check_authority, _v2_unprivileged,
               _need, _keys, _integer, _digest)),
          "v2 guard function identities changed during operation")
    _v2_check_authority()
    _need(_v2_limits(limits) == bounds, "v2 caller limits changed during operation")
    _need(_v2_snapshot(original, bounds)[1] == commitment
          and _v2_snapshot(detached, bounds)[1] == commitment,
          "v2 original or detached inputs changed during operation")
    _need(_v2_sources(owners) == pins, "v2 source observations changed during operation")
    current = _v2_callbacks(owners)
    _need(len(current) == len(callbacks)
          and all(left is right for left, right in zip(current, callbacks, strict=True)),
          "v2 operation callbacks changed during operation")


def _v2_rows(graph, original_join_raw, bounds):
    """Recover full paired bytes only after genuine public original replay."""
    join = _v2_parse(original_join_raw, 16 * 1024**2, bounds, "original coordinate join")
    bundles = join["paired_bundles"]
    _need(type(bundles) is list, "complete genuine coordinate bundle list required")
    rows = [row for bundle in bundles for row in bundle["payload_intake"]["rows"]]
    refs = graph["row_references"]
    _need(len(rows) == len(refs), "complete coordinate physical reference population required")
    result = {}
    for row, ref in zip(rows, refs, strict=True):
        raw = row["derived_row_json"].encode("utf-8")
        _need(_sha(raw) == row["row_sha256"] == ref["row_sha256"], "actual coordinate paired bytes differ")
        identity = ref["physical_identity_sha256"]
        if identity in result:
            _need(result[identity] == raw, "conflicting coordinate bytes for one physical row")
        result[identity] = raw
    _need(list(result) == [row["physical_identity_sha256"] for row in graph["physical_rows"]],
          "complete coordinate physical order differs")
    return result


def _v2_bindings(request, graph, rows, source_preparation, banks, bounds):
    slots = request["physical_review_nominations"]
    physical = graph["physical_rows"]
    _need(0 < len(physical) <= bounds["max_physical_rows"]
          and len(graph["row_references"]) <= bounds["max_physical_rows"],
          "complete v2 physical/reference population exceeds caller limit")
    _need(type(slots) is list and len(slots) == len(physical), "complete ordered v2 physical slots required")
    consumed, physical_bindings, by_identity = set(), [], {}
    for index, (slot, row) in enumerate(zip(slots, physical, strict=True)):
        _keys(slot, {"physical_row_ordinal", "physical_identity_sha256", "review_nominations"}, "v2 physical slot")
        _integer(slot["physical_row_ordinal"], len(physical) - 1, "v2 physical slot ordinal")
        identity = row["physical_identity_sha256"]
        _need(slot["physical_row_ordinal"] == index and slot["physical_identity_sha256"] == identity,
              "v2 physical slot identity or order differs")
        nominations = slot["review_nominations"]
        _need(type(nominations) is list and len(nominations) <= bounds["max_physical_rows"],
              "complete bounded v2 source review nominations required")
        refs, prior_pair = [], None
        for nomination in nominations:
            _keys(nomination, {"bank_ordinal", "bank_physical_row_ordinal"}, "v2 review nomination")
            bank_index, physical_index = nomination["bank_ordinal"], nomination["bank_physical_row_ordinal"]
            _integer(bank_index, len(banks) - 1, "v2 bank ordinal")
            bank = banks[bank_index]
            _integer(physical_index, len(bank["physical_rows"]) - 1, "v2 bank physical ordinal")
            pair = (bank_index, physical_index)
            _need(prior_pair is None or prior_pair < pair,
                  "v2 review nominations must preserve bank and physical reference order")
            prior_pair = pair
            _need(pair not in consumed, "duplicate v2 bank physical nomination")
            consumed.add(pair)
            declared = bank["physical_rows"][physical_index]
            actual, legacy = row["physical_identity"], declared["physical_identity"]
            expected = {"repository_id": actual["repository_id"], "revision": actual["revision"],
                "path_in_repo": actual["path_in_repo"], "artifact_sha256": actual["file_sha256"],
                "row_ordinal": actual["row_ordinal"]}
            _need(legacy == expected, "v2 physical source review identity differs from actual cache row")
            ordinal = declared["request_ordinal"]
            _need(bank["paired_row_bytes"][ordinal] == rows[identity],
                  "v2 nominated legacy review paired bytes differ from actual cache row")
            prepared = source_preparation["banks"][bank_index]
            collection = prepared["preparation"]
            refs.append({"bank_ordinal": bank_index, "bank_id": bank["bank_id"],
                "bank_physical_row_ordinal": physical_index, "request_ordinal": ordinal,
                "original_bank_sha256": prepared["original_bank_sha256"],
                "request_ref": _ref(collection["requests"][ordinal]),
                "subject_ref": _ref(collection["subjects"][ordinal]),
                "preparation_manifest_sha256": _sha(_wire(collection["manifest"]))})
        binding = {"physical_row_ordinal": index, "physical_identity_sha256": identity,
            "paired_row_sha256": _sha(rows[identity]), "paired_row_bytes": len(rows[identity]),
            "review_nominations": nominations, "review_references": refs,
            "selected_occurrence": None, "governing_source": None,
            "source_binding_mask": 0, "training_mask": 0, "evaluation_gold_mask": 0,
            "disposition": "pending_source_review_alternatives" if refs else "review_inputs_unavailable"}
        physical_bindings.append(binding)
        by_identity[identity] = binding
    expected_pairs = {(index, ordinal) for index, bank in enumerate(banks)
                      for ordinal in range(len(bank["physical_rows"]))}
    _need(consumed == expected_pairs, "every supplied v1 physical reference must be consumed exactly once")
    outputs = []
    for index, output in enumerate(graph["output_occurrences"]):
        _need(type(output["output_occurrence_ordinal"]) is int
              and output["output_occurrence_ordinal"] == index, "complete graph output order required")
        parent = by_identity[output["physical_identity_sha256"]]
        refs = parent["review_references"]
        outputs.append({"output_occurrence_ordinal": index,
            "physical_identity_sha256": output["physical_identity_sha256"], "route": output["route"],
            "ordinal": output["ordinal"], "physical_row_ordinal": parent["physical_row_ordinal"],
            "upstream_output_reference": {"schema": "legal-coordinate-source-review-output-reference/v1",
                "container": "graph_report_raw_utf8", "json_pointer": "/output_occurrences/" + str(index),
                "graph_report_artifact_sha256": request["graph_report_raw_sha256"],
                "graph_report_sha256": request["graph_report_sha256"],
                "output_sha256": _sha(_wire(output))},
            "review_references": refs,
            "selected_occurrence": None, "governing_source": None,
            "source_binding_mask": 0, "training_mask": 0, "evaluation_gold_mask": 0,
            "disposition": "pending_source_review_alternatives" if refs else "review_inputs_unavailable"})
    return physical_bindings, outputs


REQUEST_SCHEMA_V3 = "legal-source-correspondence-request/v3"
SCHEMA_V3 = "legal-source-correspondence-requests/v3"
PROFILE_V3 = "original-input-wire-coordinate-graph-v3-source-review-request-custody/v1"
METADATA_PROFILE_V3 = "hf-default-parquet-envelope/v1"


def _coordinate_correspondence_owners(profile_version):
    if profile_version == 2:
        return _v2_owners()
    _need(type(profile_version) is int and profile_version == 3,
          "explicit coordinate correspondence profile required")
    from . import corpus_proposed_graph_adapter as corpus
    from . import legal_span_cache_intake as intake
    from . import legal_source_span_target_eligibility_v1 as eligibility
    _need(callable(getattr(intake, "validate_coordinate_source_graph_intake_v3", None)),
          "explicit wire graph-v3 owner required without historical fallback")
    return corpus, intake, eligibility


def _coordinate_correspondence_callbacks(owners, profile_version):
    result = _v2_callbacks(owners)
    if profile_version == 3:
        corpus, intake, eligibility = owners
        from . import legal_paired_manifest_inventory_v1 as ordinary
        result += (*intake._coordinate_graph_callables(eligibility, eligibility_version=4),
            intake.validate_coordinate_source_graph_intake_v3,
            intake._coordinate_graph_wire_unqualified, intake._coordinate_graph_runtime,
            corpus._corpus_wire_physical_plan, corpus._corpus_read,
            ordinary._read_json, ordinary._pairs, ordinary._wire, ordinary._need,
            eligibility._owners, _wire_correspondence_rows,
            _coordinate_correspondence_owners, _coordinate_correspondence_callbacks,
            _coordinate_correspondence_setup, _wire_correspondence_unprivileged,
            _prepare_source_correspondence_requests, _validate_source_correspondence_requests,
            prepare_source_correspondence_requests_v3, validate_source_correspondence_requests_v3,
            source_correspondence_requests_v3_sha256)
    return result


def _wire_correspondence_unprivileged(value):
    _need(type(value) is dict and value.get("schema") == SCHEMA_V3
          and value.get("profile") == PROFILE_V3
          and value.get("metadata_profile") == METADATA_PROFILE_V3,
          "explicit wire correspondence-v3 report required")
    _digest(value.get("source_metadata_intake_sha256"), "wire source metadata intake")
    try:
        _v2_unprivileged(value, v2=True)
        _v2_unprivileged(value["source_preparation"])
    except (KeyError, TypeError, IndexError) as error:
        raise SourceCorrespondenceRequestsError("complete unprivileged wire correspondence report required") from error
    _need(value.get("atomic_snapshot_verified") is False
          and value.get("external_complete_inputs_required") is True,
          "wire correspondence cannot grant atomic or incomplete-input authority")


def _wire_correspondence_rows(corpus, graph, original_join_raw, bounds, hold):
    """Project exact row fields from the already genuinely validated wire join.

    The existing ordinary parser owns finite-float metadata and its full-join
    bounds. The legacy row parser receives only its required row fields; the
    complete original metadata stays in the independently pinned raw carrier.
    """
    joined = corpus._corpus_read(original_join_raw, 16 * 1024**2,
        "genuinely replayed correspondence wire join")
    hold(joined, "genuine ordinary wire join parser return")
    _need(type(joined) is dict
          and joined.get("schema") == "legal-source-span-entity-join-manifest/v3"
          and joined.get("source_compatibility_profile") == "paired-coordinate-hf-wire-three-cache-join/v1"
          and joined.get("source_metadata_profile") == graph.get("metadata_profile") == METADATA_PROFILE_V3
          and joined.get("source_metadata_intake_sha256") == graph.get("source_metadata_intake_sha256"),
          "genuinely replayed wire join metadata differs from the graph")
    bundles = joined.get("paired_bundles")
    _need(type(bundles) is list, "complete genuine wire bundle population required")
    projection = {"paired_bundles": []}
    for bundle in bundles:
        _need(type(bundle) is dict and type(bundle.get("payload_intake")) is dict
              and type(bundle["payload_intake"].get("rows")) is list,
              "complete genuine wire row population required")
        rows = []
        for row in bundle["payload_intake"]["rows"]:
            _need(type(row) is dict and type(row.get("derived_row_json")) is str
                  and type(row.get("row_sha256")) is str,
                  "exact genuine wire paired-row text and hash required")
            rows.append({"derived_row_json": row["derived_row_json"], "row_sha256": row["row_sha256"]})
        projection["paired_bundles"].append({"payload_intake": {"rows": rows}})
    hold(projection, "exact private wire row projection")
    return _v2_rows(graph, _wire(projection), bounds)


def _coordinate_correspondence_setup(request_raw, graph_report_raw, source_request_raw, *,
        expected_request_sha256, graph_originals, original_banks, limits, profile_version):
    _need(type(profile_version) is int and profile_version in (2, 3),
          "explicit coordinate correspondence profile required")
    _v2_check_authority()
    bounds = _v2_limits(limits)
    _digest(expected_request_sha256, "v2 request" if profile_version == 2 else "wire v3 request")
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= bounds["max_request_bytes"]
          and type(graph_report_raw) is bytes and 0 < len(graph_report_raw) <= 64 * 1024**2
          and type(source_request_raw) is bytes
          and 0 < len(source_request_raw) <= min(bounds["max_request_bytes"], DEFAULT_LIMITS["max_request_bytes"]),
          "bounded exact coordinate request, graph artifact and existing v1 request bytes required")
    _need(_sha(request_raw) == expected_request_sha256,
          "coordinate request differs from independent raw pin")
    _keys(graph_originals, _V2_GRAPH_FIELDS, "complete graph original arguments")
    _shape(original_banks, bounds)
    original = {"request_raw": request_raw, "graph_report_raw": graph_report_raw,
        "source_request_raw": source_request_raw, "graph_originals": graph_originals,
        "original_banks": original_banks, "expected_request_sha256": expected_request_sha256}
    detached, commitment = _v2_snapshot(original, bounds)
    request = _v2_parse(detached["request_raw"], bounds["max_request_bytes"], bounds,
                        "v2 request" if profile_version == 2 else "wire v3 request", canonical=True)
    _keys(request, _V2_REQUEST_FIELDS, "v2 source correspondence request" if profile_version == 2
          else "wire v3 source correspondence request")
    _need(request["schema"] == (REQUEST_SCHEMA_V2 if profile_version == 2 else REQUEST_SCHEMA_V3)
          and request["profile"] == (PROFILE_V2 if profile_version == 2 else PROFILE_V3),
          "explicit v2 source correspondence domain required" if profile_version == 2
          else "explicit wire v3 source correspondence domain required")
    for key in _V2_REQUEST_FIELDS - {"schema", "profile", "physical_review_nominations"}:
        _digest(request[key], key)
    _need(type(detached["graph_report_raw"]) is bytes
          and 0 < len(detached["graph_report_raw"]) <= 64 * 1024**2
          and type(detached["source_request_raw"]) is bytes
          and 0 < len(detached["source_request_raw"]) <= min(bounds["max_request_bytes"], DEFAULT_LIMITS["max_request_bytes"]),
          "bounded exact graph artifact and nonempty existing v1 request bytes required")
    _need(_sha(detached["graph_report_raw"]) == request["graph_report_raw_sha256"]
          and _sha(detached["source_request_raw"]) == request["source_request_sha256"],
          "v2 exact upstream artifact or v1 request pin differs")
    offered = _v2_parse(detached["graph_report_raw"], 64 * 1024**2, bounds, "graph report")
    _need(type(offered) is dict and offered.get("schema") == (
              "legal-coordinate-source-graph-intake/v2" if profile_version == 2
              else "legal-coordinate-source-graph-intake/v3")
          and offered.get("source_compatibility_profile") == (
              "original-input-coordinate-source-graph-intake/v1" if profile_version == 2
              else "original-input-wire-coordinate-source-graph-intake/v1")
          and _sha(_wire(offered)) == request["graph_report_sha256"],
          "v2 requires the independently pinned explicit original-input graph profile" if profile_version == 2
          else "wire v3 requires the independently pinned explicit wire graph profile")
    graph_request = eligibility_request = None
    if profile_version == 3:
        graph_request = _v2_parse(detached["graph_originals"]["request_raw"], 128 * 1024,
            bounds, "wire graph v3 request")
        eligibility_request = _v2_parse(detached["graph_originals"]["eligibility_request_raw"],
            128 * 1024, bounds, "wire eligibility v4 request")
        _need(type(graph_request) is dict and type(eligibility_request) is dict
              and graph_request.get("schema") == "legal-coordinate-source-graph-intake-request/v3"
              and graph_request.get("source_compatibility_profile") == "original-input-wire-coordinate-source-graph-intake/v1"
              and eligibility_request.get("schema") == "legal-source-span-target-eligibility-request/v4"
              and eligibility_request.get("source_compatibility_profile") == "original-input-wire-coordinate-target-eligibility/v1"
              and offered.get("metadata_profile") == graph_request.get("metadata_profile")
              == eligibility_request.get("metadata_profile") == METADATA_PROFILE_V3,
              "matching explicit wire graph3 and eligibility4 requests required")
    legacy_bounds = _limits({key: min(value, DEFAULT_LIMITS[key]) for key, value in bounds.items()})
    banks, _, bank_pins = _capture(detached["original_banks"], legacy_bounds)
    _request(detached["source_request_raw"], request["source_request_sha256"], banks, bank_pins, legacy_bounds)
    owners = _coordinate_correspondence_owners(profile_version)
    corpus, intake, eligibility = owners
    pins = _v2_sources(owners)
    base_callbacks = _v2_callbacks(owners)
    callbacks = _coordinate_correspondence_callbacks(owners, profile_version)
    guard, sources, base_producers, producers, finish = (
        _v2_fence, _v2_sources, _v2_callbacks, _coordinate_correspondence_callbacks, _v2_finish)
    offered_raw = _wire(offered)
    question_prompts_raw = _wire(review.wording.PROMPTS)
    request_snapshot, bounds_snapshot, limits_snapshot = _wire(request), _wire(bounds), _wire(limits)
    parsed_snapshots = tuple(_wire(item) for item in (graph_request, eligibility_request))
    pins_snapshot = _wire(pins)
    held, plan, plan_raw, files_raw = [], None, None, None
    runtime, runtime_pins, runtime_description, runtime_function, runtime_self = (None,) * 5

    def hold(value, label):
        if profile_version == 3:
            _need(len(held) < 1024, "bounded wire correspondence return population required")
            held.append((value, _wire(value), label))
        return value

    def producers_unchanged():
        _v2_check_authority()
        _need(sources(owners) == pins, "wire correspondence producer sources changed")
        current_base = base_producers(owners)
        _need(len(current_base) == len(base_callbacks)
              and all(left is right for left, right in zip(current_base, base_callbacks, strict=True)),
              "wire correspondence legacy producer callbacks changed")
        current = producers(owners, profile_version)
        _need(len(current) == len(callbacks)
              and all(left is right for left, right in zip(current, callbacks, strict=True)),
              "wire correspondence operation callbacks changed")
        if runtime is not None:
            current_runtime, current_pins = intake._coordinate_graph_runtime(eligibility)
            operation = current_runtime.describe_runtime
            _need(current_runtime is runtime and _wire(current_pins) == runtime_pins
                  and getattr(operation, "__func__", operation) is runtime_function
                  and getattr(operation, "__self__", None) is runtime_self
                  and _wire(operation("legal_ir", eligibility_request["decoder_profile"])) == runtime_description,
                  "wire correspondence runtime identity or metadata changed")

    def original_fence():
        guard(original, detached, commitment, limits, bounds, owners, pins, base_callbacks)
        _need(_wire(offered) == offered_raw, "v2 offered graph changed during operation")
        _need(_wire(review.wording.PROMPTS) == question_prompts_raw,
              "v2 genuine source review wording changed during operation")
        _need(corpus.coordinate_graph_corpus_originals_sha256(detached["graph_originals"])
              == request["graph_originals_sha256"], "v2 graph originals commitment differs")

    def parsed_unchanged():
        _need(_wire(request) == request_snapshot and _wire(bounds) == bounds_snapshot
              and _wire(limits) == limits_snapshot and _wire(pins) == pins_snapshot
              and tuple(_wire(item) for item in (graph_request, eligibility_request)) == parsed_snapshots,
              "wire correspondence captured parsed requests, pins or limits changed")
        _need(_wire(offered) == offered_raw and _wire(review.wording.PROMPTS) == question_prompts_raw,
              "wire correspondence offered graph or review wording changed")

    def returns_unchanged():
        for value, snapshot, label in held:
            _need(_wire(value) == snapshot, "genuine wire correspondence return changed: " + label)

    def physical_unchanged():
        if files_raw is not None:
            _need(_wire(plan) == plan_raw, "wire correspondence file nomination changed before I/O")
            join = eligibility._owners()[0]
            _need(_wire(join._coordinate_file_witnesses(*plan)) == files_raw,
                  "wire correspondence physical inputs changed after genuine graph replay")

    def fence():
        if profile_version == 2:
            original_fence()
            return
        checks = (("original correspondence inputs", original_fence),
            ("parsed wire correspondence inputs", parsed_unchanged),
            ("wire correspondence sources/runtime/callbacks", producers_unchanged),
            ("live genuine correspondence returns", returns_unchanged),
            ("physical wire correspondence inputs", physical_unchanged),
            ("post-callback original inputs", original_fence),
            ("post-callback parsed inputs", parsed_unchanged),
            ("post-callback producers/runtime", producers_unchanged),
            ("post-callback live returns", returns_unchanged),
            ("final physical inputs", physical_unchanged),
            ("final original inputs", original_fence),
            ("final parsed inputs", parsed_unchanged),
            ("final live returns", returns_unchanged))
        finish(checks, None)

    def adopt(genuine, label):
        nonlocal plan, plan_raw, files_raw, runtime, runtime_pins, runtime_description, runtime_function, runtime_self
        _need(profile_version == 3, "wire adoption requires explicit correspondence v3")
        hold(genuine, label)
        # Outer parsed/caller mutations must be refused before physical nomination.
        fence()
        _need(_wire(genuine) == offered_raw,
              "genuinely regenerated wire graph differs from independently pinned original")
        intake._coordinate_graph_wire_unqualified(genuine)
        if plan is None:
            plan = list(corpus._corpus_wire_physical_plan(intake, eligibility, genuine,
                detached["graph_originals"]))
            plan_raw = _wire(plan)
            files_raw = _wire(eligibility._owners()[0]._coordinate_file_witnesses(*plan))
            runtime, observed_pins = intake._coordinate_graph_runtime(eligibility)
            runtime_pins, runtime_description = _wire(observed_pins), _wire(genuine["runtime_description"])
            operation = runtime.describe_runtime
            runtime_function, runtime_self = getattr(operation, "__func__", operation), getattr(operation, "__self__", None)
            producers_unchanged()
        return genuine

    return {"original": original, "detached": detached, "bounds": bounds,
        "request": request, "offered_graph": offered, "graph_request": graph_request,
        "eligibility_request": eligibility_request, "owners": owners, "pins": pins,
        "banks": banks, "legacy_bounds": legacy_bounds, "fence": fence,
        "producers_unchanged": producers_unchanged, "hold": hold, "adopt": adopt,
        "finish": finish, "offered_raw": offered_raw}


def _prepare_source_correspondence_requests(request_raw, graph_report_raw, source_request_raw, *,
        expected_request_sha256, graph_originals, original_banks, limits, profile_version):
    """Share complete ordered associations without generating source-review inputs."""
    state = _coordinate_correspondence_setup(request_raw, graph_report_raw, source_request_raw,
        expected_request_sha256=expected_request_sha256, graph_originals=graph_originals,
        original_banks=original_banks, limits=limits, profile_version=profile_version)
    original, detached, bounds = state["original"], state["detached"], state["bounds"]
    request, offered = state["request"], state["offered_graph"]
    owners, pins, banks, legacy_bounds = state["owners"], state["pins"], state["banks"], state["legacy_bounds"]
    corpus, intake, _ = owners
    opened_graph = opened_source = None
    graph_raw = source_raw = result_raw = None
    primary = None
    validator = intake.validate_coordinate_source_graph_intake_v3 if profile_version == 3 else None

    def fence():
        state["fence"]()
        _need(opened_graph is None or _wire(opened_graph) == graph_raw,
              "v2 genuine opened graph changed during operation")
        _need(opened_source is None or _wire(opened_source) == source_raw,
              "v2 genuine opened source preparation changed during operation")
        if opened_source is not None:
            _v2_unprivileged(opened_source)

    def replay_graph():
        arguments = detached["graph_originals"]
        if profile_version == 3:
            state["producers_unchanged"]()
        operation = intake.validate_coordinate_source_graph_intake_v2 if profile_version == 2 else validator
        value = operation(offered,
            arguments["request_raw"], arguments["eligibility_report_raw"],
            arguments["eligibility_request_raw"], arguments["join_manifest_raw"],
            expected_request_sha256=arguments["expected_request_sha256"],
            expected_report_sha256=request["graph_report_sha256"],
            join_originals=arguments["join_originals"], source_bindings=arguments["source_bindings"])
        if profile_version == 3:
            state["adopt"](value, "genuine graph validation return")
        return value

    def close_graph():
        if opened_graph is not None:
            _need(_wire(replay_graph()) == graph_raw, "v2 closing genuine graph replay differs")

    def close_source():
        if opened_source is not None:
            checked = validate_source_correspondence_requests_v1(opened_source,
                detached["source_request_raw"], expected_report_sha256=_sha(source_raw),
                expected_request_sha256=request["source_request_sha256"],
                original_banks=detached["original_banks"], limits=legacy_bounds)
            state["hold"](checked, "genuine closing v1 source validation return")
            _need(_wire(checked) == source_raw and _wire(opened_source) == source_raw,
                  "v2 closing genuine source preparation replay differs")

    try:
        fence()
        opened_graph = replay_graph()
        graph_raw = _wire(opened_graph)
        _need(graph_raw == _wire(offered), "v2 public graph replay differs from offered complete report")
        fence()
        if profile_version == 3:
            rows = _wire_correspondence_rows(corpus, opened_graph,
                detached["graph_originals"]["join_manifest_raw"], bounds, state["hold"])
        else:
            rows = _v2_rows(opened_graph, detached["graph_originals"]["join_manifest_raw"], bounds)
        opened_source = prepare_source_correspondence_requests_v1(detached["source_request_raw"],
            expected_request_sha256=request["source_request_sha256"],
            original_banks=detached["original_banks"], limits=legacy_bounds)
        state["hold"](opened_source, "genuine opened v1 source preparation")
        source_raw = _wire(opened_source)
        fence()
        physical, outputs = _v2_bindings(request, opened_graph, rows, opened_source, banks, bounds)
        result = {"schema": SCHEMA_V2 if profile_version == 2 else SCHEMA_V3,
            "profile": PROFILE_V2 if profile_version == 2 else PROFILE_V3,
            "request": request, "request_raw_utf8": request_raw.decode("utf-8"),
            "request_sha256": expected_request_sha256,
            "graph_report_raw_utf8": detached["graph_report_raw"].decode("utf-8"),
            "graph_report_reference": {"schema": "legal-coordinate-source-review-graph-reference/v1",
                "artifact_sha256": request["graph_report_raw_sha256"],
                "report_sha256": request["graph_report_sha256"], "bytes": len(detached["graph_report_raw"]),
                "graph_originals_sha256": request["graph_originals_sha256"]},
            "source_request_raw_utf8": detached["source_request_raw"].decode("utf-8"),
            "source_preparation": opened_source,
            "physical_rows": opened_graph["physical_rows"], "row_references": opened_graph["row_references"],
            "physical_review_bindings": physical, "output_occurrence_bindings": outputs,
            "population_complete": True,
            "upstream_reexecution_performed": True,
            "upstream_reexecution_requirement": ("opening_and_closing_original_input_graph_v2_public_validation"
                if profile_version == 2 else "opening_and_closing_original_input_wire_graph_v3_public_validation"),
            "counts": {"physical_rows": len(physical), "row_references": len(opened_graph["row_references"]),
                "output_occurrences": len(outputs), "banks": len(banks),
                "source_logical_requests": opened_source["coverage"]["logical_requests"],
                "bank_physical_references": len([item for bank in banks for item in bank["physical_rows"]]),
                "mapped_physical_rows": sum(bool(row["review_references"]) for row in physical),
                "unmapped_physical_rows": sum(not row["review_references"] for row in physical),
                "selected_occurrences": 0, "source_decisions_applied": 0},
            "producer_pins": pins,
            "producer_pin_scope": "listed_correspondence_and_delegate_owner_files_not_complete_execution_closure",
            "atomic_snapshot_verified": False, "external_complete_inputs_required": True,
            "selected_occurrence": None, "governing_source": None, "governing_definition_use": None,
            "training_mask": 0, "evaluation_gold_mask": 0, "authority": dict(AUTHORITY),
            "limitations": [
                "Coverage is the complete genuinely replayed graph physical/reference/output population and the complete independently supplied legacy review-bank population; no whole-corpus discovery is performed.",
                "Genuine upstream replay checks the retained cache originals under independent artifact/row pins. It does not authenticate remote history, source epoch, governing edition or legacy stored-source parent Parquet bytes.",
                *LIMITATIONS[2:],
                "This explicit profile replays physical coordinate originals; legacy producer/source/edition and legal meaning remain independently unresolved.",
                "Source-context requests do not review this association, the formal outputs, a norm interpretation or definition applicability.",
                "Graph HTML nominations and legacy stored-text candidates retain different coordinates without an independently supplied crosswalk.",
                "Complete upstream graph bytes and the unchanged v1 preparation are retained once; all original replay inputs remain required.",
                "Other ordinary original strings retain the combined profile's at-most-512KiB ceiling even where an upstream owner accepts larger source or binding strings; such complete inputs are refused, never truncated.",
                "Source/edition/meaning reviews, complete norms, genuinely distinct uses, training/gold eligibility and Lean admission remain unavailable."]}
        if profile_version == 3:
            result.update(metadata_profile=METADATA_PROFILE_V3,
                source_metadata_intake_sha256=opened_graph["source_metadata_intake_sha256"])
            state["hold"](result, "live assembled wire correspondence report")
        result, result_raw = _v2_plain(result, bounds)
        _v2_unprivileged(result, v2=True)
        if profile_version == 3:
            state["hold"](result, "detached prepared wire correspondence report")
            _wire_correspondence_unprivileged(result)
    except BaseException as error:
        primary = error
        raise
    finally:
        state["finish"]((("genuine closing source preparation replay", close_source),
                    ("genuine closing graph replay", close_graph),
                    ("inputs sources callbacks and original commitment", fence)), primary)
    if profile_version == 2:
        _need(_v2_plain(result, bounds)[1] == result_raw, "v2 detached result changed during closing replay")
        _v2_unprivileged(result, v2=True)
        return _v2_plain(result, bounds)[0]
    primary = None
    try:
        _need(_v2_plain(result, bounds)[1] == result_raw,
              "wire correspondence report changed during closing replay")
        final, final_raw = _v2_plain(result, bounds)
        state["hold"](final, "final detached wire correspondence report")
        _wire_correspondence_unprivileged(final)
        _need(final_raw == result_raw and _v2_plain(final, bounds)[1] == result_raw,
              "final wire correspondence serialization changed")
        return final
    except BaseException as error:
        primary = error
        raise
    finally:
        state["finish"]((("wire correspondence final serialization custody", fence),), primary)


def source_correspondence_requests_v2_sha256(report, *, limits=None):
    """Hash the complete bounded v2 report; no original replay or authority."""
    return _sha(_v2_plain(report, _v2_limits(limits))[1])


def _validate_source_correspondence_requests(report, request_raw, graph_report_raw, source_request_raw, *,
        expected_report_sha256, expected_request_sha256, graph_originals, original_banks, limits, profile_version):
    """Regenerate the complete association with wire-only outer custody fences."""
    bounds = _v2_limits(limits)
    _digest(expected_report_sha256, "complete v2 report" if profile_version == 2 else "complete wire v3 report")
    checked, original = _v2_plain(report, bounds)
    _need(_sha(original) == expected_report_sha256, "independent complete v2 report pin differs")
    state = None
    if profile_version == 3:
        _wire_correspondence_unprivileged(checked)
        state = _coordinate_correspondence_setup(request_raw, graph_report_raw, source_request_raw,
            expected_request_sha256=expected_request_sha256, graph_originals=graph_originals,
            original_banks=original_banks, limits=limits, profile_version=3)
        state["hold"](checked, "outer detached offered wire correspondence report")
    primary, expected = None, None
    try:
        prepare = prepare_source_correspondence_requests_v2 if profile_version == 2 else prepare_source_correspondence_requests_v3
        expected = prepare(request_raw, graph_report_raw,
            source_request_raw, expected_request_sha256=expected_request_sha256,
            graph_originals=graph_originals, original_banks=original_banks, limits=limits)
        if state is not None:
            state["hold"](expected, "outer genuine prepared correspondence report")
        _need(_v2_plain(expected, bounds)[1] == original,
              "v2 report differs from complete original-input regeneration")
        if state is not None:
            state["fence"]()
            raw = expected["graph_report_raw_utf8"].encode("utf-8")
            _need(raw == state["detached"]["graph_report_raw"],
                  "genuinely prepared wire correspondence must retain the exact original graph artifact")
            genuine_graph = _v2_parse(raw, 64 * 1024**2, bounds, "graph report")
            state["adopt"](genuine_graph, "outer genuinely regenerated wire graph")
            _wire_correspondence_unprivileged(checked)
        return checked
    except BaseException as error:
        primary = error
        raise
    finally:
        def unchanged():
            _need(_v2_limits(limits) == bounds and _v2_plain(report, bounds)[1] == original,
                  "offered v2 report or limits changed during validation")
            _need(_v2_plain(checked, bounds)[1] == original, "detached offered v2 report changed during validation")
            if state is not None and expected is not None:
                _need(_v2_plain(expected, bounds)[1] == original,
                      "genuine prepared wire correspondence changed during outer validation")
        if state is None:
            _v2_finish((("offered v2 report", unchanged),), primary)
        else:
            state["finish"]((("offered wire correspondence report", unchanged),
                ("outer original/parsed/live/physical wire custody", state["fence"]),
                ("final offered wire correspondence report", unchanged),
                ("final outer wire correspondence custody", state["fence"])), primary)


def prepare_source_correspondence_requests_v2(request_raw, graph_report_raw, source_request_raw, *,
        expected_request_sha256, graph_originals, original_banks, limits=None):
    """Bind graph-v2 originals to complete independently supplied v1 review banks."""
    return _prepare_source_correspondence_requests(request_raw, graph_report_raw, source_request_raw,
        expected_request_sha256=expected_request_sha256, graph_originals=graph_originals,
        original_banks=original_banks, limits=limits, profile_version=2)


def validate_source_correspondence_requests_v2(report, request_raw, graph_report_raw, source_request_raw, *,
        expected_report_sha256, expected_request_sha256, graph_originals, original_banks, limits=None):
    """Regenerate the complete graph-v2 association from independent originals."""
    return _validate_source_correspondence_requests(report, request_raw, graph_report_raw, source_request_raw,
        expected_report_sha256=expected_report_sha256, expected_request_sha256=expected_request_sha256,
        graph_originals=graph_originals, original_banks=original_banks, limits=limits, profile_version=2)


def prepare_source_correspondence_requests_v3(request_raw, graph_report_raw, source_request_raw, *,
        expected_request_sha256, graph_originals, original_banks, limits=None):
    """Bind genuine wire graph-v3 originals to unchanged independently supplied review banks."""
    return _prepare_source_correspondence_requests(request_raw, graph_report_raw, source_request_raw,
        expected_request_sha256=expected_request_sha256, graph_originals=graph_originals,
        original_banks=original_banks, limits=limits, profile_version=3)


def source_correspondence_requests_v3_sha256(report, *, limits=None):
    """Hash the complete bounded report with the unchanged ordinary identity recipe."""
    return source_correspondence_requests_v2_sha256(report, limits=limits)


def validate_source_correspondence_requests_v3(report, request_raw, graph_report_raw, source_request_raw, *,
        expected_report_sha256, expected_request_sha256, graph_originals, original_banks, limits=None):
    """Regenerate every wire correspondence under original, return and physical custody."""
    return _validate_source_correspondence_requests(report, request_raw, graph_report_raw, source_request_raw,
        expected_report_sha256=expected_report_sha256, expected_request_sha256=expected_request_sha256,
        graph_originals=graph_originals, original_banks=original_banks, limits=limits, profile_version=3)


__all__ += ["prepare_source_correspondence_requests_v2", "validate_source_correspondence_requests_v2",
            "source_correspondence_requests_v2_sha256", "prepare_source_correspondence_requests_v3",
            "validate_source_correspondence_requests_v3", "source_correspondence_requests_v3_sha256"]
