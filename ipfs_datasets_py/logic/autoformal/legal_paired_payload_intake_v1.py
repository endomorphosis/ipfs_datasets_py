"""Selected paired payloads to opaque corpus candidates, without a feed DB.

The feed's stateless guard and census owner verify retained transport evidence;
the corpus adapter preserves each resulting row. This does not select a source
occurrence, interpret a formal payload, qualify training data or admit a law.
Parquet rows are serialized here for custody: these are derived JSON bytes,
not recovered original producer JSON. Every physical row gets a disposition.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

SCHEMA = "legal-paired-payload-intake/v1"
SCHEMA_V2 = "legal-paired-payload-intake/v2"
ROW_SERIALIZATION = "derived-parquet-row/sorted-ascii-json-v1"
DEFAULT_LIMITS = {"max_bytes": 64 * 1024**2, "max_rows": 64,
                  "max_decoded_bytes": 64 * 1024**2, "max_report_bytes": 16 * 1024**2}
AUTHORITY = dict.fromkeys(("source_authenticity_verified", "source_semantics_verified",
    "semantic_review_verified", "training_qualified", "evaluation_gold_qualified",
    "admitted", "formalized", "proof_authority", "Lean_admitted", "model_executed",
    "training_executed", "native_build_executed", "enqueued", "published"), False)


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def paired_payload_report_sha256(report):
    """Commit to the complete report, including all candidate/failure rows."""
    return _sha(_wire(report))


def _limits(supplied):
    _need(supplied is None or type(supplied) is dict, "ordinary lower-only limits required")
    result = dict(DEFAULT_LIMITS)
    for key, value in (supplied or {}).items():
        _need(key in result and type(value) is int and 0 < value <= result[key],
              "unknown, nonpositive or raised payload intake limit")
        result[key] = value
    return result


def _pins(*, coordinate=False):
    from . import (corpus_contracts, corpus_graph, corpus_source, corpus_span_adapter,
                   paired_span_census, span_cache_exchange, span_cache_feed,
                   learned_formula_observation, legal_paired_manifest_inventory_v1)
    modules = (corpus_contracts, corpus_graph, corpus_source, corpus_span_adapter,
               paired_span_census, span_cache_exchange, span_cache_feed, learned_formula_observation,
               legal_paired_manifest_inventory_v1)
    if coordinate:
        from . import span_cache, uscode_ingest
        modules += (span_cache, uscode_ingest)
    paths = [Path(__file__).resolve(), *(Path(module.__file__).resolve() for module in modules)]
    root = Path(__file__).resolve().parent
    _need(all(path.parent == root for path in paths), "operation owner escaped the selected source tree")
    return {str(path): _sha(path.read_bytes()) for path in paths}


def _prepare(*, repository_root, repository_id, revision, manifest_path_in_repo,
        expected_manifest_sha256, source_bindings=None, limits=None, coordinate=False,
        expected_source_coordinate_report_sha256=None):
    """Verify one selected local bundle and retain its complete row population.

    ``repository_root`` contains the exact repository layout for ``revision``.
    The revision is a caller-supplied acquisition identity, not authenticated by
    reading a local path. An acquisition receipt must bind it to the manifest.
    Source bindings, when provided, are an ordered list with one explicit
    six-field binding (or None) per physical row. There is no fuzzy/text join.
    A whole-bundle integrity failure raises; a corpus adapter refusal is retained
    per row. No fallback migration is performed.
    """
    bounds = _limits(limits)
    _need(type(revision) is str and re.fullmatch(r"[0-9a-f]{40}", revision),
          "immutable forty-hex revision required")
    _need(type(expected_manifest_sha256) is str
          and re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256),
          "independently supplied manifest SHA256 required")
    _need(type(repository_id) is str and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository_id),
          "explicit repository identity required")
    version_pattern = "3" if coordinate else "[12]"
    _need(type(manifest_path_in_repo) is str and re.fullmatch(
        r"autoformal/uscode/paired-v" + version_pattern + r"/manifests/[A-Za-z0-9_-]+/manifest-[0-9a-f]{64}\.json",
        manifest_path_in_repo), "supported explicit paired payload profile required")
    if coordinate:
        _need(type(expected_source_coordinate_report_sha256) is str
              and re.fullmatch(r"[0-9a-f]{64}", expected_source_coordinate_report_sha256),
              "independently supplied source coordinate report SHA256 required")
    from . import corpus_span_adapter as adapter
    from .corpus_contracts import CorpusContractError
    from .span_cache_feed import load_paired_payload, paired_source_records
    from .legal_paired_manifest_inventory_v1 import _wire as bounded_binding_wire

    pins = _pins(coordinate=coordinate)
    root = Path(repository_root)
    loaded = load_paired_payload(root / manifest_path_in_repo, repository_root=root,
        repository_id=repository_id, path_in_repo=manifest_path_in_repo,
        expected_manifest_sha256=expected_manifest_sha256,
        max_bytes=bounds["max_bytes"], max_rows=bounds["max_rows"],
        max_decoded_bytes=bounds["max_decoded_bytes"])
    # This existing projection checks producer/model/source agreement in legacy
    # as well as current rows. Keep physical rows below, rather than merging the
    # projection's same-source observations into a misleading unique population.
    paired_source_records(loaded, repository_id=repository_id, revision=revision,
                          manifest_in_repo=manifest_path_in_repo)
    values = loaded["paired_spans"]
    coordinates, carrier = None, None
    if coordinate:
        from .paired_span_census import decode_artifact, validate_paired_source_coordinates
        coordinates = validate_paired_source_coordinates(loaded,
            expected_report_sha256=expected_source_coordinate_report_sha256)
        _need(coordinates is not None and len(coordinates["rows"]) == len(values),
              "complete source coordinate row population required")
        artifact_sha = loaded["coordinate_transport"]["report_artifact_sha256"]
        artifact = next(row for row in loaded["artifacts"] if row["artifact_sha256"] == artifact_sha)
        report_raw = decode_artifact(artifact)
        carrier = {"report_raw_utf8": report_raw.decode("utf-8"), "report_bytes": len(report_raw),
                   "report_artifact_sha256": artifact_sha, "report_sha256": coordinates["report_sha256"]}
    _need(source_bindings is None or (type(source_bindings) is list and len(source_bindings) == len(values)),
          "source binding population must match all physical paired rows")
    # Commit even refused bindings: identical error text is not input identity.
    # Reuse the metadata owner's strict ordinary-JSON/depth/node/byte guard.
    binding_raw = bounded_binding_wire(source_bindings, bounds["max_decoded_bytes"])
    binding_pin = _sha(binding_raw)
    bindings = [None] * len(values) if source_bindings is None else json.loads(binding_raw)
    manifest = loaded["manifest"]
    rows = []
    counts = dict.fromkeys(("physical_rows", "candidate_unbound", "candidate_bound",
                            "adapter_rejected", "interpretations"), 0)
    charged = 0
    for ordinal, (row, binding) in enumerate(zip(values, bindings)):
        raw = _wire(row)
        identity = _sha(raw)
        candidate, error = None, None
        try:
            candidate = adapter.adapt_paired_span_bytes(raw,
                expected_row_sha256=identity, source_binding=binding)
            disposition = "candidate_unbound" if binding is None else "candidate_bound"
            counts["interpretations"] += len(candidate["interpretations"])
        except CorpusContractError as refusal:
            disposition = "adapter_rejected"
            error = {"type": type(refusal).__name__, "message": str(refusal)[:512]}
        entry = {"row_ordinal": ordinal, "observation_id": row["observation_id"],
            "row_sha256": identity, "derived_row_json": raw.decode("utf-8"),
            "disposition": disposition, "candidate": candidate, "error": error}
        if coordinate:
            provenance = coordinates["rows"][ordinal]["source_provenance_json"]
            entry.update(source_provenance_json=provenance,
                source_coordinate_report_sha256=coordinates["report_sha256"],
                source_coordinate_span_index=json.loads(provenance)["span_index"])
        charged += len(_wire(entry))
        _need(charged <= bounds["max_report_bytes"], "complete payload intake report exceeds byte bound")
        rows.append(entry)
        counts["physical_rows"] += 1
        counts[disposition] += 1
    report = {"schema": SCHEMA_V2 if coordinate else SCHEMA, "repository_id": repository_id, "revision": revision,
        "revision_evidence": "caller_supplied_acquisition_identity",
        "repository_root": str(root), "manifest_path_in_repo": manifest_path_in_repo,
        "manifest_sha256": expected_manifest_sha256, "manifest_fingerprint": manifest["fingerprint"],
        "manifest_schema": manifest["schema"], "exporter_sha256": manifest.get("exporter_sha256"),
        "original_receipt_artifact_sha256": manifest.get("original_receipt_artifact_sha256"),
        "tables": manifest["tables"], "decoded_input_bytes": loaded["decoded_bytes"],
        "limits": bounds, "row_serialization": ROW_SERIALIZATION,
        "rows": rows, "counts": counts, "source_pins": pins,
        "source_pins_scope": "selected_owner_file_observations_not_complete_execution_closure",
        "loaded_byte_identity_verified": False,
        "bundle_integrity_verified": True, "whole_repository_inventory_complete": False,
        "source_binding_population_supplied": source_bindings is not None,
        "source_bindings_sha256": binding_pin,
        "source_occurrence_search_performed": False, "authority": dict(AUTHORITY)}
    if coordinate:
        report["source_coordinates"] = carrier
    _need(len(_wire(report)) <= bounds["max_report_bytes"], "complete payload intake report exceeds byte bound")
    _need(pins == _pins(coordinate=coordinate), "payload intake operation owner changed during preparation")
    return report


def prepare_paired_payload_intake(*, repository_root, repository_id, revision,
        manifest_path_in_repo, expected_manifest_sha256, source_bindings=None, limits=None):
    """Preserve the legacy v1/v2 payload shape; v3 requires explicit v2 intake."""
    return _prepare(repository_root=repository_root, repository_id=repository_id, revision=revision,
        manifest_path_in_repo=manifest_path_in_repo, expected_manifest_sha256=expected_manifest_sha256,
        source_bindings=source_bindings, limits=limits)


def prepare_paired_payload_intake_v2(*, repository_root, repository_id, revision,
        manifest_path_in_repo, expected_manifest_sha256, expected_source_coordinate_report_sha256,
        source_bindings=None, limits=None):
    """Replay v3 only, retaining one exact report string and original row refs.

    Report custody grants no source authenticity, context permission or binding
    to a separately supplied corpus occurrence. Source bindings stay explicit.
    """
    return _prepare(repository_root=repository_root, repository_id=repository_id, revision=revision,
        manifest_path_in_repo=manifest_path_in_repo, expected_manifest_sha256=expected_manifest_sha256,
        source_bindings=source_bindings, limits=limits, coordinate=True,
        expected_source_coordinate_report_sha256=expected_source_coordinate_report_sha256)


def _validate(report, *, expected_report_sha256, coordinate=False, **inputs):
    _need(type(expected_report_sha256) is str
          and re.fullmatch(r"[0-9a-f]{64}", expected_report_sha256),
          "independently supplied report SHA256 required")
    raw = _wire(report)
    _need(len(raw) <= DEFAULT_LIMITS["max_report_bytes"], "complete report exceeds byte bound")
    _need(_sha(raw) == expected_report_sha256, "payload intake report SHA256 differs")
    expected = (prepare_paired_payload_intake_v2 if coordinate else prepare_paired_payload_intake)(**inputs)
    _need(raw == _wire(expected), "payload intake report differs from full input replay")
    return expected


def validate_paired_payload_intake(report, *, expected_report_sha256, **inputs):
    """Replay all legacy tables/rows and explicit source bindings, without writes."""
    return _validate(report, expected_report_sha256=expected_report_sha256, **inputs)


def validate_paired_payload_intake_v2(report, *, expected_report_sha256, **inputs):
    """Regenerate the complete v3 report carrier, row references and candidates."""
    return _validate(report, expected_report_sha256=expected_report_sha256, coordinate=True, **inputs)
