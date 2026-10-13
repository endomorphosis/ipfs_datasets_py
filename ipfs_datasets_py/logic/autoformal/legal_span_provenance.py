"""Complete physical cache-row reconciliation against pinned authored literals.

Only source_span_id/legal_id/source_text are compared. A matching projection
does not identify the historical job or prove a model invocation, official
source correspondence, formal correctness, training authority or Lean proof.
Source functions are parsed as inert AST; no catalog module is executed.
"""
from __future__ import annotations

import ast
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from . import legal_span_cache_intake as intake
from . import legal_span_section_bridge as profiles

SCHEMA = "legal-span-producer-provenance-observations/v1"
CATALOG_SCHEMA = "legal-authored-span-demonstration-catalog/v1"
PROJECTION_PROFILE = "literal_rows_tuple_source_span_id_legal_id_source_text/v1"
PROJECTION_FIELDS = ("source_span_id", "legal_id", "source_text")
SOURCE_FIELDS = {"source_id", "path", "source_sha256", "function_name", "function_ast_sha256", "projection_profile"}
MAX_ROWS = 128
MAX_SOURCES = 16
MAX_DEMONSTRATIONS = 256
MAX_SOURCE_BYTES = 1024 * 1024
MAX_LITERAL_BYTES = 128 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
AUTHORITY = dict.fromkeys(("historical_job_lineage_verified", "model_invocation_verified", "entire_row_matches_authored_source",
    "official_source_correspondence_verified", "source_occurrences_bound", "source_semantics_verified", "context_closure_verified",
    "authenticated_review_verified", "training_qualified", "proof_authority", "Lean_kernel_admission", "admitted", "formalized"), False)


class SpanProvenanceError(ValueError):
    """An independent source/catalog/population/report pin or finite bound differs."""


def _need(ok, message):
    if not ok:
        raise SpanProvenanceError(message)


def _wire(value):
    return intake._wire(value)


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _sha(value):
    _need(type(value) is str and _SHA.fullmatch(value), "exact independent lowercase SHA256 required")


def _source_pins(values):
    _need(type(values) is list and 0 < len(values) <= MAX_SOURCES, "bounded complete catalog source pin population required")
    seen_ids, seen_functions = set(), set()
    for value in values:
        _need(type(value) is dict and set(value) == SOURCE_FIELDS, "closed independently supplied catalog source required")
        for key in ("source_sha256", "function_ast_sha256"): _sha(value[key])
        _need(type(value["source_id"]) is str and value["source_id"].strip() and len(value["source_id"].encode()) <= 256,
              "bounded explicit authored source identity required")
        _need(type(value["path"]) is str and Path(value["path"]).is_absolute(), "explicit absolute source file path required")
        _need(type(value["function_name"]) is str and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value["function_name"]),
              "literal top-level function name required")
        _need(value["projection_profile"] == PROJECTION_PROFILE, "unsupported authored projection profile")
        identity = (value["path"], value["function_name"])
        _need(value["source_id"] not in seen_ids and identity not in seen_functions, "duplicate catalog source/function identity")
        seen_ids.add(value["source_id"]); seen_functions.add(identity)
    return deepcopy(values)


def _read_source(pin):
    path = Path(pin["path"])
    _need(path.resolve(strict=True) == path, "authored source path is aliased")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_SOURCE_BYTES, "bounded regular authored source file required")
        raw = stream.read(MAX_SOURCE_BYTES + 1)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        _need(len(raw) == before.st_size <= MAX_SOURCE_BYTES and identity(before) == identity(os.fstat(stream.fileno()))
              == identity(path.lstat()) and path.resolve(strict=True) == path, "authored source file changed during read")
    _need(hashlib.sha256(raw).hexdigest() == pin["source_sha256"], "independently pinned catalog source bytes differ")
    return raw


def catalog_from_sources(expected_catalog_source_pins):
    """Read pinned source ASTs and extract literal rows assignments, never execute.

    This profile describes authored rows literals inside a named function, not
    the function's evaluated output or any producer's historical execution.
    Every literal tuple is retained in source/literal order, including repeats.
    """
    sources = _source_pins(expected_catalog_source_pins)
    demonstrations = []
    for source in sources:
        raw = _read_source(source)
        try:
            module = ast.parse(raw)
            functions = [node for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and node.name == source["function_name"]]
            _need(len(functions) == 1, "exact unique top-level authored function required")
            function = functions[0]
            function_sha = hashlib.sha256(ast.dump(function, include_attributes=False).encode("utf-8")).hexdigest()
            _need(function_sha == source["function_ast_sha256"], "independently pinned source function AST differs")
            assignments = [node for node in function.body if isinstance(node, ast.Assign)
                           and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "rows"]
            _need(len(assignments) == 1, "one literal rows assignment required by authored projection profile")
            values = ast.literal_eval(assignments[0].value)
        except (SyntaxError, UnicodeError, TypeError, RecursionError) as error:
            raise SpanProvenanceError("bounded authored source AST/literal profile required") from error
        _need(type(values) in (tuple, list) and len(values) <= MAX_DEMONSTRATIONS, "bounded literal demonstration population required")
        for ordinal, value in enumerate(values):
            _need(type(value) in (tuple, list) and len(value) == 3 and all(type(item) is str for item in value),
                  "closed literal source_span_id/legal_id/source_text tuple required")
            _need(value[0].strip() and value[2].strip() and len(_wire(list(value))) <= MAX_LITERAL_BYTES,
                  "bounded explicit authored identity/text required")
            _need(len(demonstrations) < MAX_DEMONSTRATIONS, "complete catalog literal bound exceeded")
            demonstrations.append({"demonstration_id": source["source_id"] + ":literal:" + str(ordinal),
                "source_id": source["source_id"], "literal_ordinal": ordinal,
                "projection": dict(zip(PROJECTION_FIELDS, value))})
    catalog = {"schema": CATALOG_SCHEMA, "sources": sources, "demonstrations": demonstrations}
    _wire(catalog)
    return catalog


def catalog_sha256(catalog):
    """Canonical complete catalog digest for independent retention."""
    return _digest(catalog)


def provenance_report_sha256(report):
    """Hash the entire report, INCLUDING its internal provenance_sha256 field."""
    return _digest(report)


def _source_identity(row):
    version = row.get("schema_version")
    paired = version in profiles.PAIRED_PROFILES
    if paired:
        observation = intake._paired_observation(row)
        projection = observation[0]
        profile = version
        values = {key: projection.get(key) for key in PROJECTION_FIELDS}
        revision, source_sha = projection.get("source_revision"), projection.get("source_sha256")
    elif version is None or version in profiles.FLAT_PROFILES:
        profile = profiles.FLAT_PROFILE if version is None else profiles.EVIDENCE_PROFILE
        values = {key: row.get(key) for key in PROJECTION_FIELDS}
        revision, source_sha = row.get("source_revision"), row.get("source_sha256")
    else:
        return {"profile": "unsupported", "declared_schema_version": deepcopy(version),
                **dict.fromkeys(PROJECTION_FIELDS), "declared_revision": None, "source_sha256_observation": None,
                "projection_complete": False, "projection_sha256": None}, [{"code": "unsupported_source_profile"}]
    complete = all(type(value) is str for value in values.values()) and bool(values["source_span_id"].strip()) and bool(values["source_text"].strip())
    issues = [] if complete else [{"code": "missing_or_nonliteral_three_field_projection"}]
    if paired: issues.append({"code": "paired_projection_only_not_supported_formal_transport"})
    if not paired:
        for alias, canonical in (("id", "source_span_id"), ("text", "source_text")):
            if alias in row and row[alias] != row.get(canonical):
                issues.append({"code": "nonmatching_alias_observation_not_used", "field": alias})
    return {"profile": profile, **values, "declared_revision": revision, "source_sha256_observation": source_sha,
            "projection_complete": complete, "projection_sha256": _digest(values) if complete else None}, issues


def reconcile_span_provenance(rows, *, cache_identity, expected_row_sha256s, expected_record_sha256s,
        demonstration_catalog, expected_catalog_sha256, expected_catalog_source_pins, start_ordinal=0):
    """Reconcile all independently pinned physical rows, without selecting a subset."""
    _sha(expected_catalog_sha256)
    _need(type(rows) is list and 0 < len(rows) <= MAX_ROWS, "bounded nonempty raw cache population required")
    _need(type(start_ordinal) is int and start_ordinal >= 0, "exact starting physical ordinal required")
    for expected in (expected_row_sha256s, expected_record_sha256s):
        _need(type(expected) in (list, tuple) and len(expected) == len(rows), "complete ordered row/record pin population required")
        for value in expected: _sha(value)
    cache = intake._cache_identity(cache_identity)
    raw_rows = json.loads(_wire(rows))
    row_hashes = [intake.row_sha256(row) for row in raw_rows]
    record_hashes = [intake.record_sha256(row, ordinal=start_ordinal + i, cache_identity=cache) for i, row in enumerate(raw_rows)]
    _need(row_hashes == list(expected_row_sha256s) and record_hashes == list(expected_record_sha256s),
          "raw membership/order/multiplicity/physical ordinal/cache identity pin differs")
    catalog = json.loads(_wire(demonstration_catalog))
    _need(catalog_sha256(catalog) == expected_catalog_sha256, "independent demonstration catalog pin differs")
    expected_catalog = catalog_from_sources(expected_catalog_source_pins)
    _need(_wire(catalog) == _wire(expected_catalog), "catalog differs from independently pinned complete authored literals")
    lookup = {}
    for demonstration in catalog["demonstrations"]:
        lookup.setdefault(_wire(demonstration["projection"]), []).append(demonstration)
    observations = []
    for index, row in enumerate(raw_rows):
        identity, issues = _source_identity(row)
        matches = lookup.get(_wire({key: identity[key] for key in PROJECTION_FIELDS}), []) if identity["projection_complete"] else []
        classification = "unsupported_source_profile" if identity["profile"] == "unsupported" else "incomplete_source_projection" if not identity["projection_complete"] else "ambiguous_authored_projection_match" if len(matches) > 1 else "exact_authored_projection_match" if matches else "no_authored_projection_match"
        observations.append({"row_ordinal": start_ordinal + index, "raw_row": row, "raw_row_sha256": row_hashes[index],
            "record_sha256": record_hashes[index], "record_id": "legal-span-cache-record:sha256:" + record_hashes[index],
            "source_identity": identity, "classification": classification, "matched_demonstrations": deepcopy(matches),
            "match_scope": "literal_source_span_id_legal_id_source_text_only", "issues": issues,
            "legacy_producer_declarations_status": "raw_observations_only_not_execution_proof", "authority": dict(AUTHORITY)})
    report = {"schema": SCHEMA, "cache_identity": cache, "start_ordinal": start_ordinal,
        "end_ordinal": start_ordinal + len(raw_rows), "row_count": len(raw_rows),
        "expected_row_sha256s": row_hashes, "expected_record_sha256s": record_hashes,
        "demonstration_catalog": catalog, "catalog_sha256": expected_catalog_sha256,
        "catalog_source_pins": deepcopy(expected_catalog_source_pins), "rows": observations,
        "classification_counts": dict(Counter(row["classification"] for row in observations)),
        "population_complete": True, "coverage_scope": "exact_independently_pinned_supplied_physical_cache_rows_only",
        "whole_cache_coverage_verified": False, "historical_producer_attribution": "not_established_by_literal_projection_match",
        "original_task_acceptance": "preparatory_subset_only", "authority": dict(AUTHORITY)}
    report["provenance_sha256"] = _digest(report)
    _wire(report)
    return deepcopy(report)


def validate_span_provenance(report, rows, *, expected_report_sha256, **trusted_inputs):
    _sha(expected_report_sha256)
    _need(provenance_report_sha256(report) == expected_report_sha256, "independent complete provenance report pin differs")
    expected = reconcile_span_provenance(rows, **trusted_inputs)
    _need(_wire(report) == _wire(expected), "provenance report differs from independent complete regeneration")
    return expected


__all__ = ["SpanProvenanceError", "catalog_from_sources", "catalog_sha256", "provenance_report_sha256",
           "reconcile_span_provenance", "validate_span_provenance"]
