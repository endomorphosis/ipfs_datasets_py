"""Selected paired-v1/v2 manifest metadata, without reading any table body.

This stateless adapter delegates paired transport validation to the existing
feed owner. Declared rows and physical table paths are different measures;
neither establishes source occurrence, learned attempt or semantic coverage.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

REQUEST_SCHEMA = "legal-paired-manifest-inventory-request/v1"
SCHEMA = "legal-paired-manifest-inventory/v1"
REQUEST_SCHEMA_V2 = "legal-paired-manifest-inventory-request/v2"
SCHEMA_V2 = "legal-paired-manifest-inventory/v2"
REPOSITORY = "justicedao/uscode-autoformal-span-cache"
SELECTION_SCOPE = "explicit_paired_manifest_selection"
MAX_MANIFESTS = 16
MAX_REQUEST_BYTES = 128 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_MANIFEST_TOTAL_BYTES = 512 * 1024
MAX_REPORT_BYTES = 4 * 1024 * 1024
TABLES = ("paired_spans", "goals", "artifacts")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_PAIRED_PATH = re.compile(r"autoformal/uscode/paired-v([12])/manifests/[A-Za-z0-9_-]+/manifest-[0-9a-f]{64}\.json\Z")
_COORDINATE_PATH = re.compile(r"autoformal/uscode/paired-v(3)/manifests/[A-Za-z0-9_-]+/manifest-[0-9a-f]{64}\.json\Z")
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_OWNER_PINS = None
AUTHORITY = dict.fromkeys((
    "remote_inventory_exhaustive", "corpus_inventory_exhaustive",
    "table_bodies_verified", "Arrow_schemas_verified", "table_rows_verified",
    "artifact_bodies_verified", "learned_capture_verified", "source_occurrences_bound",
    "source_semantics_verified", "semantic_review_verified", "globally_consistent",
    "accepted", "admitted", "formalized", "proof_authority", "Lean_admitted",
    "training_qualified", "evaluation_gold_qualified", "model_executed",
    "training_executed", "native_build_executed", "enqueued", "published",
), False)


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _keys(value, fields, label):
    _need(type(value) is dict and set(value) == set(fields), "closed exact fields required: " + label)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value, label):
    _need(type(value) is str and _SHA.fullmatch(value), "lowercase SHA256 required: " + label)


def _wire(value, maximum):
    remaining = 100000

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        _need(remaining >= 0 and depth <= 32, "bounded ordinary JSON required")
        if type(item) is dict:
            for key, child in item.items():
                _need(type(key) is str, "ordinary JSON keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need(len(item) <= maximum and "\x00" not in item and
                  not any(0xD800 <= ord(char) <= 0xDFFF for char in item), "bounded UTF8 string required")
        elif item is None or type(item) is bool:
            pass
        elif type(item) is int:
            _need(-(1 << 63) <= item < (1 << 63), "bounded JSON integer required")
        elif type(item) is float:
            _need(math.isfinite(item), "finite JSON number required")
        else:
            raise ValueError("ordinary finite JSON required")

    visit(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("ordinary UTF8 JSON required") from error
    _need(len(raw) <= maximum, "complete JSON byte bound exceeded")
    return raw


def _pairs(rows):
    result = {}
    for key, value in rows:
        _need(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _read_json(raw, maximum, label):
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded exact " + label + " bytes required")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("finite JSON required")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded duplicate-free UTF8 JSON required: " + label) from error
    _wire(value, maximum)
    return value


def _preflight(request_raw, manifest_bytes, expected_request_sha256, *, coordinate=False):
    """Reject untrusted input shapes and pins before importing operation owners."""
    _digest(expected_request_sha256, "request")
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_REQUEST_BYTES,
          "bounded exact request bytes required")
    _need(_sha(request_raw) == expected_request_sha256, "request SHA256 mismatch")
    request = _read_json(request_raw, MAX_REQUEST_BYTES, "request")
    _keys(request, {"schema", "repository_id", "revision", "selection_scope", "manifests"}, "request")
    _need(request["schema"] == (REQUEST_SCHEMA_V2 if coordinate else REQUEST_SCHEMA) and request["repository_id"] == REPOSITORY
          and request["selection_scope"] == SELECTION_SCOPE, "unsupported explicit paired selection")
    _need(type(request["revision"]) is str and _REVISION.fullmatch(request["revision"]),
          "immutable lowercase forty-hex revision required")
    _need(type(request["manifests"]) is list and len(request["manifests"]) <= MAX_MANIFESTS,
          "bounded ordered manifest selection required")
    _need(type(manifest_bytes) is dict, "ordinary exact manifest byte mapping required")
    _need(all(type(key) is str for key in manifest_bytes), "ordinary manifest mapping path keys required")
    seen, total = set(), 0
    captured = {}
    for entry in request["manifests"]:
        fields = {"path_in_repo", "bytes", "sha256"}
        if coordinate:
            fields.add("source_coordinate_report_sha256")
        _keys(entry, fields, "manifest selection")
        path = entry["path_in_repo"]
        pattern = _COORDINATE_PATH if coordinate else _PAIRED_PATH
        _need(type(path) is str and len(path) <= 512 and pattern.fullmatch(path),
              "supported exact paired manifest path required")
        _need(path not in seen, "duplicate selected manifest path")
        seen.add(path)
        size = entry["bytes"]
        _need(type(size) is int and 0 < size <= MAX_MANIFEST_BYTES, "bounded exact manifest size required")
        total += size
        _need(total <= MAX_MANIFEST_TOTAL_BYTES, "selected manifest total byte bound exceeded")
        _digest(entry["sha256"], "manifest")
        if coordinate:
            _digest(entry["source_coordinate_report_sha256"], "source coordinate report")
    _need(set(manifest_bytes) == seen, "manifest byte mapping population differs from exact selection")
    for entry in request["manifests"]:
        raw = manifest_bytes[entry["path_in_repo"]]
        _need(type(raw) is bytes and len(raw) == entry["bytes"] and _sha(raw) == entry["sha256"],
              "selected manifest bytes or SHA256 mismatch")
        _need(type(_read_json(raw, MAX_MANIFEST_BYTES, "manifest")) is dict,
              "ordinary manifest object required")
        captured[entry["path_in_repo"]] = raw
    return request, captured


def _owners():
    from . import span_cache_exchange, span_cache_feed, span_evidence, supervisor_queue, supervisor_todo

    global _OWNER_PINS
    modules = (span_cache_feed, span_cache_exchange, span_evidence, supervisor_queue, supervisor_todo)
    pins = {str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes()) for module in modules}
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "manifest inventory producer changed since import")
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    if _OWNER_PINS is None:
        _OWNER_PINS = dict(pins)
    _need(pins == _OWNER_PINS, "manifest inventory operation owner changed since first use")
    return span_cache_feed, dict(pins)


def _empty_counts():
    return {"manifest_reference_count": 0, "declared_row_sum": 0,
            "distinct_physical_path_count": 0, "distinct_path_declared_row_sum": 0,
            "declared_bytes_references": 0, "distinct_path_declared_bytes": 0,
            "distinct_declared_sha256_count": 0}


def _analysis(rows, versions=(1, 2)):
    banks = {"paired-v" + str(version): {kind: _empty_counts() for kind in TABLES} for version in versions}
    physical = {}
    hashes = {(bank, kind): set() for bank in banks for kind in TABLES}
    references = []
    for row in sorted(rows, key=lambda item: item["path_in_repo"]):
        for kind in TABLES:
            descriptor = row["manifest"]["tables"][kind]
            path = descriptor["path_in_repo"]
            identity = _wire(descriptor, MAX_MANIFEST_BYTES)
            if path in physical:
                _need(physical[path] == identity, "conflicting descriptors for one physical table path")
            counts = banks[row["bank"]][kind]
            counts["manifest_reference_count"] += 1
            counts["declared_row_sum"] += descriptor["row_count"]
            counts["declared_bytes_references"] += descriptor["bytes"]
            if path not in physical:
                counts["distinct_physical_path_count"] += 1
                counts["distinct_path_declared_row_sum"] += descriptor["row_count"]
                counts["distinct_path_declared_bytes"] += descriptor["bytes"]
                physical[path] = identity
            hashes[row["bank"], kind].add(descriptor["sha256"])
            references.append({"manifest_path": row["path_in_repo"], "bank": row["bank"],
                               "table": kind, "descriptor": descriptor})
    for (bank, kind), values in hashes.items():
        banks[bank][kind]["distinct_declared_sha256_count"] = len(values)
    return {"banks": banks, "descriptor_references": references,
            "distinct_physical_table_path_count": len(physical),
            "selected_manifest_count": len(rows),
            "selected_manifest_bytes": sum(row["bytes"] for row in rows),
            "unique_source_occurrence_count": None, "unique_formalization_attempt_count": None,
            "declared_rows_are_unique_sources": False,
            "declared_rows_are_verified_table_population": False}


def _prepare(request_raw, manifest_bytes, *, expected_request_sha256, coordinate=False):
    request, captured = _preflight(request_raw, manifest_bytes, expected_request_sha256, coordinate=coordinate)
    feed, before = _owners()
    rows = []
    for ordinal, selected in enumerate(request["manifests"]):
        path, raw = selected["path_in_repo"], captured[selected["path_in_repo"]]
        value = feed._manifest_json(raw)
        _need(feed._manifest_match(path) is not None, "existing owner did not recognize paired manifest")
        _need(value.get("repository_id") == request["repository_id"] and value.get("path_in_repo") == path,
              "manifest repository or exact path differs from request")
        feed._paired_descriptors(value, path)
        if coordinate:
            transport = value.get("coordinate_transport")
            _keys(transport, {"schema", "report_artifact_sha256", "report_sha256", "index_artifact_sha256"},
                  "coordinate transport metadata")
            _need(transport["schema"] == "paired-source-coordinate-transport/v1",
                  "unsupported coordinate transport metadata schema")
            for key in ("report_artifact_sha256", "report_sha256", "index_artifact_sha256"):
                _digest(transport[key], "coordinate transport " + key)
            _need(transport["report_sha256"] == selected["source_coordinate_report_sha256"],
                  "independent source coordinate report SHA256 differs")
        rows.append({"selection_ordinal": ordinal, **selected,
                     "bank": "paired-v" + (_COORDINATE_PATH if coordinate else _PAIRED_PATH).fullmatch(path)[1],
                     "schema": value["schema"], "fingerprint": value["fingerprint"],
                     "producer": value["agent_id"], "raw_utf8": raw.decode("utf-8"), "manifest": value})
    report = {"schema": SCHEMA_V2 if coordinate else SCHEMA, "repository_id": request["repository_id"], "revision": request["revision"],
        "selection_scope": SELECTION_SCOPE, "selection_complete": True,
        "status": "selected_metadata_validated" if rows else "empty_explicit_selection_no_evidence",
        "coverage_scope": "exact_explicitly_selected_manifest_metadata_only",
        "request": request, "request_raw_utf8": request_raw.decode("utf-8"),
        "request_sha256": expected_request_sha256, "manifests": rows,
        "analysis": _analysis(rows, (3,)) if coordinate else _analysis(rows),
        "metadata_validation": {"manifest_bytes_pinned": True, "manifest_content_fingerprints_verified": True,
            "paired_transport_descriptors_verified": True, "descriptor_file_paths_opened": False,
            "table_bytes_read": False, "Arrow_loaded": False, "table_rows_read": False,
            "artifacts_decoded": False, "learned_captures_verified": False,
            "remote_revision_authenticated_by_this_operation": False},
        "source_join": {"status": "unresolved_not_attempted", "source_occurrences": None,
                        "formalization_attempts": None, "bindings": [],
                        "reason": "selected_manifest_metadata_contains_no_verified_source_or_attempt_rows"},
        "migration_eligibility": "unknown_table_and_source_evidence_not_read",
        "producer_pins": before, "authority": dict(AUTHORITY),
        "human_reviews": 0, "signatures_constructed": 0, "admissions": 0, "graph_admissions": 0,
        "training_mask": 0, "evaluation_gold_mask": 0,
        "limits": {"max_manifests": MAX_MANIFESTS, "max_request_bytes": MAX_REQUEST_BYTES,
            "max_manifest_bytes": MAX_MANIFEST_BYTES, "max_manifest_total_bytes": MAX_MANIFEST_TOTAL_BYTES,
            "max_report_bytes": MAX_REPORT_BYTES},
        "assumptions": [
            "The caller selects metadata at a declared immutable revision; this operation makes no remote request.",
            "Selection completeness concerns only the exact supplied manifest population, including an empty selection.",
            "Manifest-reference rows, distinct physical-path rows and distinct declared hashes remain separate measures.",
            "Identical content at different paths does not establish identical source occurrences or inference attempts.",
            "No source location, producer inference, legal meaning, graph admission or Lean build is validated.",
        ]}
    _wire(report, MAX_REPORT_BYTES)
    _need(_owners()[-1] == before, "manifest inventory owners changed during preparation")
    return report


def prepare_paired_manifest_inventory(request_raw: bytes, manifest_bytes: dict, *, expected_request_sha256):
    """Validate selected v1/v2 metadata, retaining the legacy report shape."""
    return _prepare(request_raw, manifest_bytes, expected_request_sha256=expected_request_sha256)


def prepare_paired_manifest_inventory_v2(request_raw: bytes, manifest_bytes: dict, *, expected_request_sha256):
    """Validate only v3 metadata and independently pinned report declarations.

    No report artifact, Arrow table or source occurrence is read or verified.
    """
    return _prepare(request_raw, manifest_bytes, expected_request_sha256=expected_request_sha256, coordinate=True)


def paired_manifest_inventory_sha256(report):
    """Hash the complete report without following any offered path or loading owners."""
    return _sha(_wire(report, MAX_REPORT_BYTES))


def _validate(report, request_raw, manifest_bytes, *, expected_request_sha256, expected_report_sha256,
              coordinate=False):
    _digest(expected_report_sha256, "report")
    _preflight(request_raw, manifest_bytes, expected_request_sha256, coordinate=coordinate)
    if type(report) is bytes:
        report = _read_json(report, MAX_REPORT_BYTES, "report")
    _need(type(report) is dict, "ordinary report object or exact report JSON bytes required")
    _need(paired_manifest_inventory_sha256(report) == expected_report_sha256, "report SHA256 mismatch")
    regenerated = _prepare(request_raw, manifest_bytes,
        expected_request_sha256=expected_request_sha256, coordinate=coordinate)
    offered = _wire(report, MAX_REPORT_BYTES)
    _need(offered == _wire(regenerated, MAX_REPORT_BYTES), "manifest inventory differs from full authoritative replay")
    _need(_owners()[-1] == regenerated["producer_pins"], "manifest inventory owners changed during validation")
    return regenerated


def validate_paired_manifest_inventory(report, request_raw, manifest_bytes, *,
                                       expected_request_sha256, expected_report_sha256):
    """Require an independent report pin and complete legacy regeneration."""
    return _validate(report, request_raw, manifest_bytes, expected_request_sha256=expected_request_sha256,
                     expected_report_sha256=expected_report_sha256)


def validate_paired_manifest_inventory_v2(report, request_raw, manifest_bytes, *,
                                          expected_request_sha256, expected_report_sha256):
    """Replay the exact v3 metadata selection and its independent report pins."""
    return _validate(report, request_raw, manifest_bytes, expected_request_sha256=expected_request_sha256,
                     expected_report_sha256=expected_report_sha256, coordinate=True)
