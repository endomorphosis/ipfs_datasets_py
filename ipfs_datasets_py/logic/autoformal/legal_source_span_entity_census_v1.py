"""Attach a pinned prior entity census to an original-bound source/span join.

The existing join is replayed unchanged. The entity owner checks the original
file and footer against an independently retained v2 census without decoding
rows again. Neither coverage observation supplies entity-to-source semantics.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from .legal_paired_manifest_inventory_v1 import _keys, _read_json, _wire

REQUEST_SCHEMA = "legal-source-span-entity-census-request/v1"
SCHEMA = "legal-source-span-entity-census/v1"
MAX_REQUEST_BYTES = 128 * 1024
MAX_CENSUS_BYTES = 1024 * 1024
MAX_JOIN_BYTES = 16 * 1024 * 1024
MAX_REPORT_BYTES = 32 * 1024 * 1024
MAX_ORIGINAL_BYTES = 64 * 1024 * 1024
AUTHORITY = dict.fromkeys((
    "remote_revisions_authenticated", "whole_repository_inventory_complete",
    "source_semantics_verified", "semantic_review_verified", "context_closure_verified",
    "entity_semantic_bindings_verified", "graph_admitted", "Lean_admitted",
    "proof_authority", "admitted", "formalized", "training_qualified",
    "evaluation_gold_qualified", "model_executed", "training_executed",
), False)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_OWNER_PINS = None
_LIMITS = ("max_rows", "batch_size", "max_file_bytes", "max_decoded_bytes",
           "max_row_group_bytes", "max_batch_bytes", "max_row_bytes", "max_scratch_bytes")
_ORIGINAL_FIELDS = {"request_raw", "source_request_raw", "source_metadata_bytes",
    "paired_inventory_request_raw", "paired_manifest_bytes", "entity_info_raw",
    "expected_request_sha256", "legacy_join_inputs"}


def _need(ok, message):
    if not ok:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value, label):
    _need(type(value) is str and _SHA.fullmatch(value), "exact SHA256 required: " + label)


def _owners():
    from . import (legal_source_span_entity_join_v1 as join,
                   legal_entity_index_intake as entity,
                   legal_paired_manifest_inventory_v1 as ordinary)
    global _OWNER_PINS
    pins = {str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
            for module in (join, entity, ordinary)}
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "census companion changed since import")
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    if _OWNER_PINS is None:
        _OWNER_PINS = dict(pins)
    _need(pins == _OWNER_PINS, "census companion owners changed since first use")
    return join, entity, dict(pins)


def _originals(value):
    """Detach the existing owner's exact original arguments within one bound."""
    _keys(value, _ORIGINAL_FIELDS, "complete original join arguments")
    captured, identities, total = {}, {}, 0

    def raw(data, label, maximum):
        nonlocal total
        _need(type(data) is bytes and 0 < len(data) <= maximum,
              "bounded exact original bytes required: " + label)
        total += len(data)
        _need(total <= MAX_ORIGINAL_BYTES, "aggregate original join byte bound exceeded")
        return {"sha256": _sha(data), "bytes": len(data)}

    for key in ("request_raw", "source_request_raw", "paired_inventory_request_raw", "entity_info_raw"):
        identities[key] = raw(value[key], key, 256 * 1024)
        captured[key] = value[key]
    for key in ("source_metadata_bytes", "paired_manifest_bytes"):
        entries = value[key]
        _need(type(entries) is dict and len(entries) <= 16, "bounded original byte mapping required: " + key)
        captured[key], identities[key] = {}, {}
        for path, data in entries.items():
            _need(type(path) is str and 0 < len(path) <= 512, "bounded original metadata path required")
            identities[key][path] = raw(data, path, 16 * 1024 * 1024)
            captured[key][path] = data
    _digest(value["expected_request_sha256"], "original join request")
    _need(_sha(captured["request_raw"]) == value["expected_request_sha256"],
          "original join request differs from independent pin")
    captured["expected_request_sha256"] = identities["expected_request_sha256"] = value["expected_request_sha256"]
    joins = value["legacy_join_inputs"]
    _need(joins is None or type(joins) is dict and len(joins) <= 16, "bounded original legacy join mapping required")
    captured["legacy_join_inputs"] = None if joins is None else {}
    identities["legacy_join_inputs"] = None if joins is None else {}
    for path, entry in (joins or {}).items():
        _need(type(path) is str and 0 < len(path) <= 512, "bounded legacy manifest path required")
        _keys(entry, {"expected_population", "producer_receipt_bytes", "expected_producer_receipt_sha256",
                      "source_sections", "expected_source_sections"}, "original legacy join arguments")
        receipt = entry["producer_receipt_bytes"]
        receipt_identity = None if receipt is None else raw(receipt, "legacy receipt", 32 * 1024 * 1024)
        body_raw = _wire({key: item for key, item in entry.items() if key != "producer_receipt_bytes"},
                         4 * 1024 * 1024)
        body_identity = raw(body_raw, "legacy arguments", 4 * 1024 * 1024)
        body = _read_json(body_raw, 4 * 1024 * 1024, "legacy arguments")
        body["producer_receipt_bytes"] = receipt
        captured["legacy_join_inputs"][path] = body
        identities["legacy_join_inputs"][path] = {"body": body_identity, "receipt": receipt_identity}
    return captured, _sha(_wire(identities, MAX_REQUEST_BYTES))


def _preflight(request_raw, join_report, census_raw, entity_path, expected_request_sha256):
    _digest(expected_request_sha256, "companion request")
    _need(type(request_raw) is bytes and len(request_raw) <= MAX_REQUEST_BYTES
          and _sha(request_raw) == expected_request_sha256, "companion request differs from independent pin")
    request = _read_json(request_raw, MAX_REQUEST_BYTES, "companion request")
    _keys(request, {"schema", "join_report_sha256", "census_raw_sha256", "census_sha256", "entity", "census_limits"},
          "census companion request")
    _need(request["schema"] == REQUEST_SCHEMA, "unsupported census companion profile")
    for key in ("join_report_sha256", "census_raw_sha256", "census_sha256"):
        _digest(request[key], key)
    joined = _read_json(join_report if type(join_report) is bytes else _wire(join_report, MAX_JOIN_BYTES),
                        MAX_JOIN_BYTES, "original join report")
    _need(_sha(_wire(joined, MAX_JOIN_BYTES)) == request["join_report_sha256"], "original join report pin differs")
    _need(type(census_raw) is bytes and 0 < len(census_raw) <= MAX_CENSUS_BYTES
          and _sha(census_raw) == request["census_raw_sha256"], "prior census bytes differ from independent raw pin")
    census = _read_json(census_raw, MAX_CENSUS_BYTES, "prior census")
    _need(type(census) is dict and census.get("schema") == "legal-materialized-entity-index-census/v2"
          and census.get("census_sha256") == request["census_sha256"]
          and _sha(_wire({key: item for key, item in census.items() if key != "census_sha256"}, MAX_CENSUS_BYTES))
          == request["census_sha256"], "independently pinned complete v2 census required")
    entity = request["entity"]
    _keys(entity, {"repository_id", "revision", "configuration", "file_sha256", "file_bytes", "rows"},
          "entity file selection")
    _need(entity["repository_id"] == "justicedao/uscode-autoformal-entity-cache"
          and entity["configuration"] == "autoformal_uscode" and type(entity["revision"]) is str
          and _REVISION.fullmatch(entity["revision"]), "exact supported entity identity required")
    _digest(entity["file_sha256"], "entity file")
    _need(type(entity["file_bytes"]) is int and 0 < entity["file_bytes"] <= 64 * 1024 * 1024
          and type(entity["rows"]) is int and 0 <= entity["rows"] <= 3_000_000,
          "bounded entity file size and population required")
    _keys(request["census_limits"], set(_LIMITS), "original census limits")
    _need(all(type(request["census_limits"][key]) is int and request["census_limits"][key] > 0
              for key in _LIMITS), "positive integer original census limits required")
    _need(type(entity_path) in (str, type(Path())), "ordinary entity source path required")
    path = str(entity_path)
    _need(0 < len(path) <= 4096 and Path(path).is_absolute(), "absolute retained entity source path required")
    source = census.get("source")
    _need(type(source) is dict and source.get("path") == path
          and source.get("file_sha256") == entity["file_sha256"]
          and source.get("file_bytes") == entity["file_bytes"]
          and source.get("revision") == entity["revision"] and source.get("revision_supplied") is True
          and source.get("expected_rows") == census.get("rows") == entity["rows"],
          "prior census source identity differs from explicit entity selection")
    _need(census.get("limits") == request["census_limits"], "original census limits differ")
    return request, joined, census, path



def _report_identity(value, maximum, label):
    captured = _read_json(value if type(value) is bytes else _wire(value, maximum), maximum, label)
    return _sha(_wire(captured, maximum))


def _finish_custody(checks, primary):
    """Attempt every closing check without replacing an operational failure."""
    failures = []
    for label, check in checks:
        try:
            check()
        except Exception as error:
            failures.append((label, error))
    if not failures:
        return
    if primary is not None:
        for label, error in failures:
            primary.add_note("secondary closing custody failure (" + label + "): "
                             + type(error).__name__ + ": " + str(error)[:512])
        return
    first_label, first = failures[0]
    first.add_note("closing custody check: " + first_label)
    for label, error in failures[1:]:
        first.add_note("additional closing custody failure (" + label + "): "
                       + type(error).__name__ + ": " + str(error)[:512])
    raise first


def prepare_source_span_entity_census_v1(request_raw, join_report, census_raw, entity_path, *,
                                        expected_request_sha256, join_originals):
    """Replay the join and freshly verify custody of a pinned prior v2 census.

    Original entity source.path is part of census identity: copying the file
    does not authorize rewriting that field. This operation performs no entity
    row decoding, graph reconstruction, semantic review or model execution.
    """
    request, joined, census, path = _preflight(request_raw, join_report, census_raw, entity_path,
                                             expected_request_sha256)
    originals, original_identity = _originals(join_originals)
    join, entity, before = _owners()
    primary = None
    try:
        ceilings = (entity.MAX_ROWS, entity.MAX_BATCH_SIZE, entity.MAX_FILE_BYTES, entity.MAX_DECODED_BYTES,
                    entity.MAX_ROW_GROUP_BYTES, entity.MAX_BATCH_BYTES, entity.MAX_ROW_BYTES, entity.MAX_SCRATCH_BYTES)
        _need(all(request["census_limits"][key] <= ceiling for key, ceiling in zip(_LIMITS, ceilings)),
              "census limit exceeds existing owner bound")
        selection = request["entity"]
        # Validate the pinned prior census before the more expensive join replay.
        # These are ordered custody observations, not an atomic multi-file view.
        binding = entity.validate_census_bindings(census, path,
            expected_census_sha256=request["census_sha256"], expected_file_sha256=selection["file_sha256"],
            expected_rows=selection["rows"], revision=selection["revision"], endpoint_details=True,
            **request["census_limits"])
        joined = join.validate_source_span_entity_join_manifest(joined, originals["request_raw"],
            originals["source_request_raw"], originals["source_metadata_bytes"],
            originals["paired_inventory_request_raw"], originals["paired_manifest_bytes"], originals["entity_info_raw"],
            expected_report_sha256=request["join_report_sha256"],
            expected_request_sha256=originals["expected_request_sha256"],
            legacy_join_inputs=originals["legacy_join_inputs"])
        metadata = joined["entity_metadata"]
        _need(all(metadata[key] == selection[key] for key in ("repository_id", "revision", "configuration"))
              and metadata["declared_rows"] == selection["rows"] and metadata["schema_fields"] == list(entity.FIELDS),
              "replayed join and physical entity census identities differ")
        rows = [{"reference_ordinal": ordinal, "physical_identity_sha256": row["physical_identity_sha256"],
                 "row_sha256": row["row_sha256"], "entity_semantic_binding": None,
                 "reason": "semantic_companions_not_supplied", "training_mask": 0, "evaluation_gold_mask": 0}
                for ordinal, row in enumerate(joined["row_references"])]
        report = {"schema": SCHEMA, "request": request, "request_raw_utf8": request_raw.decode("utf-8"),
            "request_sha256": expected_request_sha256, "join_report": joined,
            "join_report_sha256": request["join_report_sha256"], "join_originals_sha256": original_identity,
            "census": {"raw_utf8": census_raw.decode("utf-8"), "raw_sha256": request["census_raw_sha256"],
                       "census_sha256": request["census_sha256"], "report": census},
            "entity_file": {"path": path, **selection, "schema_fields": list(entity.FIELDS)},
            "census_binding_validation": binding, "row_references": rows,
            "counts": {"selected_paired_row_references": len(rows),
                       "selected_physical_paired_rows": joined["counts"]["physical_paired_rows"],
                       "prior_entity_census_rows": census["rows"], "fresh_entity_rows_decoded": 0,
                       "entity_semantic_bindings": None},
            "evidence": {"source_span_join_replayed": True, "prior_entity_row_census_retained": True,
            "verification_order": ["entity_prior_census_binding", "source_span_join_replay"],
            "atomic_multi_file_snapshot_verified": False,
                "fresh_entity_file_and_footer_verified": True, "fresh_entity_row_replay_performed": False,
                "source_current_rows_replayed": False, "entity_semantic_binding_status": "unavailable_semantic_companions_not_supplied",
                "revision_identity_scope": "caller_supplied_acquisition_identity_not_remote_authentication",
                "coverage_scope": "selected_source_span_join_and_exact_pinned_prior_entity_file_census"},
            "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
            "producer_pins": before,
            "producer_pins_scope": "selected_owner_file_observations_not_complete_execution_closure",
            "loaded_byte_identity_verified": False}
        return _read_json(_wire(report, MAX_REPORT_BYTES), MAX_REPORT_BYTES, "census companion report")
    except BaseException as error:
        primary = error
        raise
    finally:
        _finish_custody((
            ("original join arguments", lambda: _need(_originals(join_originals)[1] == original_identity,
                "original join arguments changed during preparation")),
            ("offered join report", lambda: _need(_report_identity(join_report, MAX_JOIN_BYTES, "offered join report")
                == request["join_report_sha256"], "offered join report changed during preparation")),
            ("producer sources", lambda: _need(_owners()[-1] == before,
                "census companion owners changed during preparation")),
        ), primary)


def source_span_entity_census_sha256(report):
    """Canonical full companion identity, distinct from raw census file SHA256."""
    return _sha(_wire(report, MAX_REPORT_BYTES))


def validate_source_span_entity_census_v1(report, request_raw, join_report, census_raw, entity_path, *,
        expected_report_sha256, expected_request_sha256, join_originals):
    """Require independent identity and full original-input companion replay."""
    _digest(expected_report_sha256, "census companion report")
    captured = _read_json(report if type(report) is bytes else _wire(report, MAX_REPORT_BYTES),
                          MAX_REPORT_BYTES, "census companion report")
    _need(source_span_entity_census_sha256(captured) == expected_report_sha256, "census companion report pin differs")
    primary = None
    try:
        expected = prepare_source_span_entity_census_v1(request_raw, join_report, census_raw, entity_path,
            expected_request_sha256=expected_request_sha256, join_originals=join_originals)
        _need(_wire(captured, MAX_REPORT_BYTES) == _wire(expected, MAX_REPORT_BYTES),
              "census companion differs from full original-input replay")
        return expected
    except BaseException as error:
        primary = error
        raise
    finally:
        _finish_custody((("offered companion report", lambda: _need(
            _report_identity(report, MAX_REPORT_BYTES, "offered companion report") == expected_report_sha256,
            "offered companion report changed during validation")),), primary)


__all__ = ["prepare_source_span_entity_census_v1", "source_span_entity_census_sha256",
           "validate_source_span_entity_census_v1"]


# Coordinate compatibility is additive: the original v1 definitions above keep
# their closed request and legacy join profile.
REQUEST_SCHEMA_V2 = "legal-source-span-entity-census-request/v2"
SCHEMA_V2 = "legal-source-span-entity-census/v2"
COORDINATE_PROFILE = "paired-coordinate-entity-census/v1"
MAX_COORDINATE_ROWS = 64
MAX_COORDINATE_ORIGINAL_BYTES = 8 * 1024 * 1024
_COORDINATE_FIELDS = ("source_provenance_json", "source_coordinate_report_sha256",
                      "source_coordinate_span_index")


def _coordinate_originals(value):
    """Reuse the original commitment format within the coordinate-only bound."""
    def bounded(arguments):
        _keys(arguments, _ORIGINAL_FIELDS, "complete coordinate join originals")
        total = 0
        for key in ("request_raw", "source_request_raw", "paired_inventory_request_raw", "entity_info_raw"):
            raw = arguments[key]
            _need(type(raw) is bytes and 0 < len(raw) <= 256 * 1024,
                  "bounded exact coordinate original bytes required: " + key)
            total += len(raw)
        for key in ("source_metadata_bytes", "paired_manifest_bytes"):
            entries = arguments[key]
            _need(type(entries) is dict and 0 < len(entries) <= 16,
                  "bounded nonempty coordinate metadata mapping required: " + key)
            for name, raw in entries.items():
                _need(type(name) is str and 0 < len(name.encode("utf-8")) <= 512
                      and type(raw) is bytes and 0 < len(raw) <= MAX_COORDINATE_ORIGINAL_BYTES,
                      "bounded exact coordinate metadata names and bytes required")
                total += len(raw)
        _need(total <= MAX_COORDINATE_ORIGINAL_BYTES, "coordinate original input aggregate exceeds bound")
        legacy = arguments["legacy_join_inputs"]
        _need(legacy is None or type(legacy) is dict and not legacy,
              "coordinate census cannot mix legacy occurrence inputs")

    bounded(value)
    captured, identity = _originals(value)
    bounded(captured)
    return captured, identity


def source_span_entity_census_join_originals_sha256(join_originals):
    """Commit exact coordinate replay inputs without granting semantic authority."""
    return _coordinate_originals(join_originals)[1]


def _coordinate_preflight(request_raw, join_report, census_raw, entity_path, expected_request_sha256):
    _digest(expected_request_sha256, "coordinate companion request")
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_REQUEST_BYTES
          and _sha(request_raw) == expected_request_sha256,
          "coordinate companion request differs from independent pin")
    request = _read_json(request_raw, MAX_REQUEST_BYTES, "coordinate companion request")
    _keys(request, {"schema", "join_report_sha256", "census_raw_sha256", "census_sha256", "entity", "census_limits",
                    "join_originals_sha256", "source_coordinate_report_sha256"}, "coordinate census request")
    _need(request["schema"] == REQUEST_SCHEMA_V2, "unsupported coordinate census companion profile")
    for key in ("join_report_sha256", "census_raw_sha256", "census_sha256",
                "join_originals_sha256", "source_coordinate_report_sha256"):
        _digest(request[key], key)
    joined = _read_json(join_report if type(join_report) is bytes else _wire(join_report, MAX_JOIN_BYTES),
                        MAX_JOIN_BYTES, "original coordinate join report")
    _need(_sha(_wire(joined, MAX_JOIN_BYTES)) == request["join_report_sha256"],
          "original coordinate join report pin differs")
    _need(type(joined) is dict and joined.get("schema") == "legal-source-span-entity-join-manifest/v2"
          and joined.get("source_compatibility_profile") == "paired-coordinate-three-cache-join/v1",
          "explicit coordinate join v2 required")
    _need(type(census_raw) is bytes and 0 < len(census_raw) <= MAX_CENSUS_BYTES
          and _sha(census_raw) == request["census_raw_sha256"], "prior census bytes differ from independent raw pin")
    census = _read_json(census_raw, MAX_CENSUS_BYTES, "prior census")
    _need(type(census) is dict and census.get("schema") == "legal-materialized-entity-index-census/v2"
          and census.get("census_sha256") == request["census_sha256"]
          and _sha(_wire({key: item for key, item in census.items() if key != "census_sha256"}, MAX_CENSUS_BYTES))
          == request["census_sha256"], "independently pinned complete v2 census required")
    selection = request["entity"]
    _keys(selection, {"repository_id", "revision", "configuration", "file_sha256", "file_bytes", "rows"},
          "entity file selection")
    _need(selection["repository_id"] == "justicedao/uscode-autoformal-entity-cache"
          and selection["configuration"] == "autoformal_uscode" and type(selection["revision"]) is str
          and _REVISION.fullmatch(selection["revision"]), "exact supported entity identity required")
    _digest(selection["file_sha256"], "entity file")
    _need(type(selection["file_bytes"]) is int and 0 < selection["file_bytes"] <= 64 * 1024 * 1024
          and type(selection["rows"]) is int and 0 <= selection["rows"] <= 3_000_000,
          "bounded entity file size and population required")
    _keys(request["census_limits"], set(_LIMITS), "original census limits")
    _need(all(type(request["census_limits"][key]) is int and request["census_limits"][key] > 0
              for key in _LIMITS), "positive integer original census limits required")
    _need(type(entity_path) in (str, type(Path())), "ordinary entity source path required")
    path = str(entity_path)
    _need(0 < len(path) <= 4096 and Path(path).is_absolute(), "absolute retained entity source path required")
    source = census.get("source")
    _need(type(source) is dict and source.get("path") == path
          and source.get("file_sha256") == selection["file_sha256"]
          and source.get("file_bytes") == selection["file_bytes"]
          and source.get("revision") == selection["revision"] and source.get("revision_supplied") is True
          and source.get("expected_rows") == census.get("rows") == selection["rows"],
          "prior census source identity differs from explicit entity selection")
    _need(census.get("limits") == request["census_limits"], "original census limits differ")
    return request, joined, census, path


def _coordinate_references(joined, request):
    """Retain complete physical order and exact global-coordinate ancestry."""
    bundles, refs, physical = (joined["paired_bundles"], joined["row_references"], joined["physical_rows"])
    _need(joined.get("selection_complete") is True and type(bundles) is list and len(bundles) == 1
          and type(refs) is list and type(physical) is list
          and 1 <= len(refs) == len(physical) <= MAX_COORDINATE_ROWS,
          "one complete bounded coordinate bundle required")
    intake = bundles[0]["payload_intake"]
    _need(intake.get("schema") == "legal-paired-payload-intake/v2", "explicit coordinate payload v2 required")
    payload_rows = intake["rows"]
    _need(type(payload_rows) is list and len(payload_rows) == len(refs),
          "complete coordinate payload population required")
    carrier = intake["source_coordinates"]
    _keys(carrier, {"report_raw_utf8", "report_bytes", "report_artifact_sha256", "report_sha256"},
          "complete coordinate report carrier")
    _need(type(carrier["report_raw_utf8"]) is str and type(carrier["report_bytes"]) is int
          and carrier["report_bytes"] == len(carrier["report_raw_utf8"].encode("utf-8"))
          and carrier["report_artifact_sha256"] == _sha(carrier["report_raw_utf8"].encode("utf-8"))
          and carrier["report_sha256"] == request["source_coordinate_report_sha256"],
          "coordinate report differs from independent census pin or exact carrier bytes")
    identities, rows = set(), []
    for ordinal, (row, physical_row, payload_row) in enumerate(zip(refs, physical, payload_rows)):
        identity = row["physical_identity_sha256"]
        _need(identity not in identities and physical_row["physical_identity_sha256"] == identity
              and physical_row["physical_identity"] == row["physical_identity"]
              and type(row["physical_identity"]["row_ordinal"]) is int
              and row["physical_identity"]["row_ordinal"] == ordinal
              and type(payload_row["row_ordinal"]) is int and payload_row["row_ordinal"] == ordinal
              and physical_row["row_sha256"] == row["row_sha256"] == payload_row["row_sha256"],
              "complete ordered coordinate physical identity required")
        identities.add(identity)
        values = {key: row[key] for key in _COORDINATE_FIELDS}
        _need(type(values["source_provenance_json"]) is str
              and type(values["source_coordinate_span_index"]) is int and values["source_coordinate_span_index"] >= 0
              and values["source_coordinate_report_sha256"] == carrier["report_sha256"]
              and all(payload_row[key] == value for key, value in values.items()),
              "exact per-physical-row coordinate ancestry required")
        _need(row.get("coordinate_transport_status") == "complete_report_occurrence_replayed"
              and row.get("source_candidate_record") is None and row.get("selected_occurrence") is None
              and row.get("current_source_release_correspondence") == "unverified_no_independent_crosswalk"
              and row.get("entity_binding") == "unavailable_semantic_companions_not_supplied"
              and type(row.get("training_mask")) is int and row["training_mask"] == 0
              and type(row.get("evaluation_gold_mask")) is int and row["evaluation_gold_mask"] == 0,
              "coordinate custody cannot promote source or entity semantics")
        rows.append({"reference_ordinal": ordinal, "physical_identity_sha256": identity,
            "row_sha256": row["row_sha256"], **values, "entity_semantic_binding": None,
            "reason": "semantic_companions_not_supplied", "training_mask": 0, "evaluation_gold_mask": 0})
    return rows


def _finish_coordinate_custody(checks, primary):
    """Attempt every v2 closing check, retaining even a BaseException primary."""
    failures = []
    for label, check in checks:
        try:
            check()
        except BaseException as error:
            failures.append((label, error))
    if primary is not None:
        for label, error in failures:
            primary.add_note("secondary closing custody failure (" + label + "): "
                             + type(error).__name__ + ": " + str(error)[:512])
        return
    if failures:
        first_label, first = failures[0]
        first.add_note("closing custody check: " + first_label)
        for label, error in failures[1:]:
            first.add_note("additional closing custody failure (" + label + "): "
                           + type(error).__name__ + ": " + str(error)[:512])
        raise first


def prepare_source_span_entity_census_v2(request_raw, join_report, census_raw, entity_path, *,
                                        expected_request_sha256, join_originals):
    """Replay a coordinate join and bind the original prior entity census.

    The original entity file is rehashed and its footer checked on opening and
    closing, including failure paths. No entity rows are decoded, and exact
    coordinate custody does not establish edition correspondence or meaning.
    """
    request, joined, census, path = _coordinate_preflight(request_raw, join_report, census_raw, entity_path,
                                                        expected_request_sha256)
    originals, original_identity = _coordinate_originals(join_originals)
    _need(original_identity == request["join_originals_sha256"], "independent join originals commitment differs")
    join, entity, before = _owners()
    selection = request["entity"]
    paired_closure = None

    def bind_entity():
        return entity.validate_census_bindings(census, path,
            expected_census_sha256=request["census_sha256"], expected_file_sha256=selection["file_sha256"],
            expected_rows=selection["rows"], revision=selection["revision"], endpoint_details=True,
            **request["census_limits"])

    def check_originals():
        _need(_coordinate_originals(join_originals)[1] == request["join_originals_sha256"]
              and _coordinate_originals(originals)[1] == request["join_originals_sha256"],
              "coordinate original join arguments changed during preparation")

    def check_paired_files():
        if paired_closure is not None:
            location, selected, expected = paired_closure
            observed = join._coordinate_file_witnesses(location, selected)
            _need(_wire(observed, MAX_REQUEST_BYTES) == expected,
                  "coordinate bundle file witnesses changed during census preparation")

    primary = None
    try:
        ceilings = (entity.MAX_ROWS, entity.MAX_BATCH_SIZE, entity.MAX_FILE_BYTES, entity.MAX_DECODED_BYTES,
                    entity.MAX_ROW_GROUP_BYTES, entity.MAX_BATCH_BYTES, entity.MAX_ROW_BYTES, entity.MAX_SCRATCH_BYTES)
        _need(all(request["census_limits"][key] <= ceiling for key, ceiling in zip(_LIMITS, ceilings)),
              "census limit exceeds existing owner bound")
        binding = bind_entity()
        original_request = _read_json(originals["request_raw"], 256 * 1024, "original coordinate join request")
        locations, selections = original_request["paired_bundles"], joined["span_inventory"]["manifests"]
        _need(type(locations) is list and len(locations) == 1
              and type(selections) is list and len(selections) == 1,
              "one complete coordinate bundle required for closing file custody")
        # Freeze the pinned report's witnesses before delegation. The genuine
        # join owns its opening/closing decoder fence; this later observation
        # also catches physical drift after that public validator returns.
        paired_closure = (locations[0],
            _read_json(_wire(selections[0], MAX_JOIN_BYTES), MAX_JOIN_BYTES, "retained coordinate manifest"),
            _wire(joined["retained_file_witnesses"], MAX_REQUEST_BYTES))
        joined = join.validate_source_span_entity_join_manifest_v2(joined, originals["request_raw"],
            originals["source_request_raw"], originals["source_metadata_bytes"],
            originals["paired_inventory_request_raw"], originals["paired_manifest_bytes"], originals["entity_info_raw"],
            expected_report_sha256=request["join_report_sha256"],
            expected_request_sha256=originals["expected_request_sha256"],
            legacy_join_inputs=originals["legacy_join_inputs"])
        metadata = joined["entity_metadata"]
        _need(all(metadata[key] == selection[key] for key in ("repository_id", "revision", "configuration"))
              and type(metadata["declared_rows"]) is int and metadata["declared_rows"] == selection["rows"]
              and metadata["schema_fields"] == list(entity.FIELDS)
              and type(metadata["verified_file_rows"]) is int and metadata["verified_file_rows"] == 0
              and metadata["scope"] == "metadata_only_no_entity_file_or_semantic_companions",
              "replayed coordinate join and physical entity census identities differ")
        rows = _coordinate_references(joined, request)
        report = {"schema": SCHEMA_V2, "source_compatibility_profile": COORDINATE_PROFILE,
            "request": request, "request_raw_utf8": request_raw.decode("utf-8"),
            "request_sha256": expected_request_sha256, "join_report": joined,
            "join_report_sha256": request["join_report_sha256"], "join_originals_sha256": original_identity,
            "source_coordinate_report_sha256": request["source_coordinate_report_sha256"],
            "census": {"raw_utf8": census_raw.decode("utf-8"), "raw_sha256": request["census_raw_sha256"],
                       "census_sha256": request["census_sha256"], "report": census},
            "entity_file": {"path": path, **selection, "schema_fields": list(entity.FIELDS)},
            "census_binding_validation": binding, "row_references": rows,
            "counts": {"selected_paired_row_references": len(rows),
                       "selected_physical_paired_rows": joined["counts"]["physical_paired_rows"],
                       "coordinate_occurrence_replayed_rows": len(rows),
                       "prior_entity_census_rows": census["rows"], "fresh_entity_rows_decoded": 0,
                       "entity_semantic_bindings": None},
            "evidence": {"source_span_join_replayed": True, "upstream_reexecution_performed": True,
                "prior_entity_row_census_retained": True,
                "verification_order": ["entity_prior_census_binding_open", "source_span_join_replay",
                                       "entity_prior_census_binding_close", "paired_bundle_file_witnesses_close"],
                "atomic_multi_file_snapshot_verified": False,
                "fresh_entity_file_and_footer_verified": True, "closing_entity_file_and_footer_verified": True,
                "closing_paired_bundle_file_witnesses_verified": True,
                "fresh_entity_row_replay_performed": False, "source_current_rows_replayed": False,
                "coordinate_carrier_scope": "complete_original_report_retained_once_in_unchanged_join",
                "entity_semantic_binding_status": "unavailable_semantic_companions_not_supplied",
                "revision_identity_scope": "caller_supplied_acquisition_identity_not_remote_authentication",
                "coverage_scope": "selected_coordinate_source_span_join_and_exact_pinned_prior_entity_file_census"},
            "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
            "producer_pins": before,
            "producer_pins_scope": "selected_owner_file_observations_not_complete_execution_closure",
            "loaded_byte_identity_verified": False}
        return _read_json(_wire(report, MAX_REPORT_BYTES), MAX_REPORT_BYTES, "coordinate census companion report")
    except BaseException as error:
        primary = error
        raise
    finally:
        _finish_coordinate_custody((
            ("entity prior census binding", bind_entity),
            ("paired bundle file witnesses", check_paired_files),
            ("original join arguments", check_originals),
            ("offered join report", lambda: _need(_report_identity(join_report, MAX_JOIN_BYTES, "offered join report")
                == request["join_report_sha256"], "offered join report changed during preparation")),
            ("captured join report", lambda: _need(_report_identity(joined, MAX_JOIN_BYTES, "captured join report")
                == request["join_report_sha256"], "captured join report changed during preparation")),
            ("producer sources", lambda: _need(_owners()[-1] == before,
                "census companion owners changed during preparation")),
        ), primary)


def validate_source_span_entity_census_v2(report, request_raw, join_report, census_raw, entity_path, *,
        expected_report_sha256, expected_request_sha256, join_originals):
    """Require independently pinned coordinate custody and full original replay."""
    _digest(expected_report_sha256, "coordinate census companion report")
    captured = _read_json(report if type(report) is bytes else _wire(report, MAX_REPORT_BYTES),
                          MAX_REPORT_BYTES, "coordinate census companion report")
    _need(type(captured) is dict and captured.get("schema") == SCHEMA_V2
          and captured.get("source_compatibility_profile") == COORDINATE_PROFILE,
          "explicit coordinate census companion v2 required")
    _need(source_span_entity_census_sha256(captured) == expected_report_sha256,
          "coordinate census companion report pin differs")
    primary = None
    try:
        expected = prepare_source_span_entity_census_v2(request_raw, join_report, census_raw, entity_path,
            expected_request_sha256=expected_request_sha256, join_originals=join_originals)
        _need(_wire(captured, MAX_REPORT_BYTES) == _wire(expected, MAX_REPORT_BYTES),
              "coordinate census companion differs from full original-input replay")
        return expected
    except BaseException as error:
        primary = error
        raise
    finally:
        _finish_coordinate_custody((("offered coordinate companion report", lambda: _need(
            _report_identity(report, MAX_REPORT_BYTES, "offered coordinate companion report") == expected_report_sha256,
            "offered coordinate companion report changed during validation")),), primary)


__all__ += ["prepare_source_span_entity_census_v2", "validate_source_span_entity_census_v2",
            "source_span_entity_census_join_originals_sha256"]
