#!/usr/bin/env python3
"""Bounded, read-only intake audit of the pinned US Code formula-text export.

The export is a diagnostic sample, not the whole dataset or gold supervision.
This tool verifies byte identities and preserves producer claims; it does not
validate logic, run Lake, review legal meaning, or qualify training targets.
Only the four small pinned files below are fetched, never reports or models.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

SCHEMA = "legal-decoder-pilot-dataset-audit/v1"
REPOSITORY = "justicedao/uscode-autoformal-span-cache"
REVISION = "765176c6db79ba65c1697c21dead43666350b730"
MANIFEST_SHA256 = "1c3c60623f70fc1466fbe65bd57d0b5fca95670ea0c67c3e33c7c93784d8005c"
EXPORT_DIRECTORY = f"autoformal/uscode/formula-text/v1/{MANIFEST_SHA256}"
DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_RECORDS = 500
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_SOURCE_FIELDS = (
    "source_span_id", "legal_id", "producer_origin", "producer_record_source_id",
    "view_name", "format", "formula_field", "decoded_document_json_pointer",
    "source_report_path_in_repo", "source_report_revision", "source_report_sha256",
    "source_receipt_sha256", "source_document_sha256", "recorded_document_sha256",
    "recorded_document_identity_status", "learned_formula_generation",
)
_REQUIRED_FIELDS = (
    "source_span_id", "legal_id", "producer_origin", "view_name",
    "decoded_document_json_pointer", "source_report_path_in_repo",
    "source_report_revision", "source_report_sha256", "source_document_sha256",
)

# These are documented defects in the pinned EXAMPLES.md, not inferred legal
# judgements. Each note applies to the span, not necessarily every family view.
_DOCUMENTED_ISSUES = {
    "uscode-span-00884ef681cbb16df4d9e77ef0c3649dc3883b7613b68867675565f8ddee80f1":
        "Citation fragment L. was rendered as an obligation by TDFOL and DCEC.",
    "uscode-span-0819f0c9e252ecefe47fd8e0c5bf9ac66c083a395ec206c60ed760cbae45eab4":
        "Amendment-history fragment was rendered as an obligation by TDFOL.",
    "uscode-span-12e27cca693c89b19e111ce06593fe144ed4d6c2f1f74f4b112ac6f0b57db926":
        "Canonical action was to; the bridge reported an omitted scope condition.",
}
_PINNED_SOURCE_TEXTS = {
    "uscode-span-00884ef681cbb16df4d9e77ef0c3649dc3883b7613b68867675565f8ddee80f1": "L.",
    "uscode-span-0819f0c9e252ecefe47fd8e0c5bf9ac66c083a395ec206c60ed760cbae45eab4":
        "116–283, §1847(d)(1)(D)(i), redesignated pars.",
}


class AuditError(ValueError):
    """Input cannot be audited within the declared identity or resource bounds."""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _strict_json(raw: str | bytes) -> Any:
    def reject_constant(value: str) -> None:
        raise AuditError(f"non-finite JSON constant: {value}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AuditError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique_object)


def _bounded_local(path: Path, limit: int) -> bytes:
    if limit < 1 or not path.is_file() or path.stat().st_size > limit:
        raise AuditError(f"not a regular file within byte limit: {path}")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise AuditError(f"file exceeds byte limit: {path}")
    return raw


def _url(filename: str) -> str:
    path = filename if filename == "README.md" else f"{EXPORT_DIRECTORY}/{filename}"
    return f"https://huggingface.co/datasets/{REPOSITORY}/resolve/{REVISION}/{path}"


def fetch_pinned_export(
    cache_directory: Path, *, max_bytes: int = DEFAULT_MAX_BYTES,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Fetch four fixed files with a total byte budget and pinned content hashes."""
    if max_bytes < 1:
        raise AuditError("max_bytes must be positive")
    cache_directory.mkdir(parents=True, exist_ok=True)
    remaining = max_bytes
    receipts: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {}
    for filename in ("manifest.json", "README.md", "EXAMPLES.md", "formulas.jsonl"):
        if remaining < 1:
            raise AuditError("fetch exceeds total byte budget")
        url = _url(filename)
        with opener(url, timeout=30) as response:
            commit = response.headers.get("x-repo-commit")
            if commit is not None and commit != REVISION:
                raise AuditError("Hub resolved to a different revision")
            advertised_size = response.headers.get("Content-Length")
            if advertised_size is not None and int(advertised_size) > remaining:
                raise AuditError("fetch exceeds total byte budget")
            raw = response.read(remaining + 1)
        if len(raw) > remaining:
            raise AuditError("fetch exceeds total byte budget")
        remaining -= len(raw)
        expected = {
            "manifest.json": MANIFEST_SHA256,
            "README.md": "12baa9ccf9038e7799fdd0dd59991dbb202b80617f00a636f0f7963e6b2336a6",
        }.get(filename)
        if filename in {"EXAMPLES.md", "formulas.jsonl"}:
            declaration = manifest["files"]["examples" if filename == "EXAMPLES.md" else "jsonl"]
            expected = declaration["sha256"]
            if declaration["bytes"] != len(raw):
                raise AuditError(f"manifest byte count mismatch for {filename}")
        if digest(raw) != expected:
            raise AuditError(f"pinned content hash mismatch for {filename}")
        if filename == "manifest.json":
            manifest = _strict_json(raw)
        target = cache_directory / filename
        if target.is_symlink():
            raise AuditError(f"refusing a symlink cache destination: {target}")
        if target.exists() and _bounded_local(target, len(raw)) != raw:
            raise AuditError(f"refusing to overwrite different cached bytes: {target}")
        target.write_bytes(raw)
        receipts.append({
            "filename": filename, "requested_url": url, "bytes": len(raw),
            "sha256": digest(raw), "pinned_content_verified": True,
            "response_commit": commit,
        })
    receipt = {"repository": REPOSITORY, "revision": REVISION,
               "max_total_bytes": max_bytes, "files": receipts}
    (cache_directory / "fetch-receipt.json").write_text(_json(receipt) + "\n")
    return receipt


def _boolean_flags(value: Any, path: str = "") -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if isinstance(child, bool) and (
                "syntax" in key or key in {"parse_ok", "valid", "proof_ready", "requires_validation"}
            ):
                flags.append({"pointer": child_path, "value": child})
            else:
                flags.extend(_boolean_flags(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            flags.extend(_boolean_flags(child, f"{path}/{index}"))
    return flags


def audit_row(row: Mapping[str, Any], *, line_number: int, raw_line_sha256: str) -> dict[str, Any]:
    """Retain claims separately from verification; never qualify a target."""
    issues: list[str] = []
    missing = [key for key in _REQUIRED_FIELDS if not isinstance(row.get(key), str) or not row[key]]
    if missing:
        issues.append("missing_provenance")
    source = row.get("source_text")
    formula = row.get("formula_text")
    if not isinstance(source, str) or not source.strip():
        issues.append("missing_or_empty_source_text")
    if not isinstance(formula, str) or not formula.strip():
        issues.append("missing_or_empty_formula_text")
    actual_formula_hash = digest(formula.encode()) if isinstance(formula, str) else None
    formula_hash_matches = actual_formula_hash is not None and actual_formula_hash == row.get("formula_sha256")
    if not formula_hash_matches:
        issues.append("formula_hash_missing_or_mismatch")
    for name in ("source_report_sha256", "source_receipt_sha256", "source_document_sha256", "recorded_document_sha256"):
        if not isinstance(row.get(name), str) or not _SHA256.fullmatch(row[name]):
            issues.append(f"invalid_or_missing_{name}")
    if not isinstance(row.get("source_report_revision"), str) or not _REVISION.fullmatch(row["source_report_revision"]):
        issues.append("invalid_or_missing_source_report_revision")
    fallback = row.get("fallback_origin")
    if fallback is not None and type(fallback) is not bool:
        issues.append("invalid_fallback_claim")
    reported_raw = row.get("reported_validation_json")
    reported = None
    if isinstance(reported_raw, str):
        try:
            reported = _strict_json(reported_raw)
        except (ValueError, TypeError):
            issues.append("malformed_reported_validation_json")
    elif reported_raw is not None:
        issues.append("malformed_reported_validation_json")
    if row.get("admitted") is True or row.get("training_qualified") is True or row.get("independent_validation") is True:
        issues.append("qualification_claim_requires_independent_evidence")
    expected_source = _PINNED_SOURCE_TEXTS.get(row.get("source_span_id"))
    if expected_source is not None and source != expected_source:
        issues.append("known_source_identity_text_mismatch")
    documented = _DOCUMENTED_ISSUES.get(row.get("source_span_id"))
    return {
        "line_number": line_number, "raw_line_sha256": raw_line_sha256,
        "source_text": source, "source_text_sha256": digest(source.encode()) if isinstance(source, str) else None,
        "formula_text": formula, "formula_sha256": row.get("formula_sha256"),
        "computed_formula_sha256": actual_formula_hash,
        "formula_hash_verified": formula_hash_matches,
        "provenance": {field: row.get(field) for field in _SOURCE_FIELDS},
        "missing_provenance_fields": missing, "intake_issues": issues,
        "fallback_origin": fallback,  # null stays unknown, never false
        "reported_validation_json": reported_raw,
        "reported_validation_flags": _boolean_flags(reported),
        "producer_claims": {key: row.get(key) for key in ("admitted", "training_qualified", "independent_validation")},
        "verification": {
            "logic_syntax": "not_run", "family_compliance": "not_run",
            "lake": "not_run", "semantic_review": "not_performed",
            "original_report_and_document_hashes": "not_recomputed",
        },
        "documented_span_issue": documented,
        "documented_issue_evidence_url": _url("EXAMPLES.md") if documented else None,
        "training_qualified": False,
        "target_disposition": "repair_review_candidate" if documented else "unreviewed_diagnostic",
    }


def audit_export(
    input_path: Path, manifest_path: Path, *, max_bytes: int = DEFAULT_MAX_BYTES,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> dict[str, Any]:
    """Audit a prefix of the exact pinned export, verifying the complete file."""
    if max_records < 1 or max_bytes < 1:
        raise AuditError("byte and record limits must be positive")
    manifest_raw = _bounded_local(manifest_path, min(max_bytes, 1024 * 1024))
    if digest(manifest_raw) != MANIFEST_SHA256:
        raise AuditError("manifest does not match the pinned diagnostic export")
    manifest = _strict_json(manifest_raw)
    raw = _bounded_local(input_path, max_bytes - len(manifest_raw))
    declaration = manifest["files"]["jsonl"]
    if len(raw) != declaration["bytes"] or digest(raw) != declaration["sha256"]:
        raise AuditError("JSONL bytes/hash differ from the pinned manifest")
    lines = raw.splitlines()
    if len(lines) != manifest["counts"]["formula_row_count"]:
        raise AuditError("JSONL line count differs from the pinned manifest")
    records: list[dict[str, Any]] = []
    for number, line in enumerate(lines[:max_records], 1):
        try:
            row = _strict_json(line)
        except ValueError as exc:
            raise AuditError(f"invalid JSON at line {number}: {exc}") from exc
        if not isinstance(row, dict):
            raise AuditError(f"record at line {number} is not an object")
        records.append(audit_row(row, line_number=number, raw_line_sha256=digest(line)))
    fallback = Counter("true" if r["fallback_origin"] is True else "false" if r["fallback_origin"] is False else "unknown" for r in records)
    counts = {
        "formula_occurrences_audited": len(records),
        "source_span_ids_observed": len({r["provenance"]["source_span_id"] for r in records if r["provenance"]["source_span_id"]}),
        "formula_hashes_verified": sum(r["formula_hash_verified"] for r in records),
        "unique_formula_strings": len({r["formula_text"] for r in records if isinstance(r["formula_text"], str)}),
        "fallback_origin": dict(sorted(fallback.items())),
        "by_view": dict(sorted(Counter(r["provenance"]["view_name"] or "unknown" for r in records).items())),
        "intake_issues": dict(sorted(Counter(issue for r in records for issue in r["intake_issues"]).items())),
        "documented_issue_source_spans_observed": len({r["provenance"]["source_span_id"] for r in records if r["documented_span_issue"]}),
        "occurrences_from_documented_issue_spans": sum(r["documented_span_issue"] is not None for r in records),
        "occurrences_with_producer_validation_flags": sum(bool(r["reported_validation_flags"]) for r in records),
        "syntax_independently_validated": 0, "family_compliance_verified": 0,
        "lake_builds_run": 0, "semantically_reviewed": 0, "training_qualified": 0,
    }
    return {
        "schema": SCHEMA, "repository": REPOSITORY, "revision": REVISION,
        "configuration": "formal_logic_text", "storage_split": "train",
        "scope": "pinned formula-text diagnostic export only; not a census of the full dataset",
        "limits": {"max_total_local_bytes": max_bytes, "max_records": max_records},
        "input": {"path": str(input_path.resolve()), "manifest_path": str(manifest_path.resolve()),
                  "url": _url("formulas.jsonl"), "bytes": len(raw), "sha256": digest(raw),
                  "manifest_sha256": digest(manifest_raw), "pinned_content_verified": True},
        "sample": {"selection": "file order prefix; repeats retained", "representative_sample": False,
                   "truncated_by_record_limit": len(lines) > max_records,
                   "export_formula_occurrences": len(lines)},
        "manifest_reported_counts": manifest["counts"],
        "qualification_policy": "No qualification is granted by this intake audit; train, producer syntax flags and byte identity are not gold labels.",
        "counts": counts, "records": records,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="local exact pinned formulas.jsonl")
    parser.add_argument("--manifest", type=Path, help="local exact pinned manifest.json")
    parser.add_argument("--fetch", action="store_true", help="fetch only the four small pinned files")
    parser.add_argument("--cache-dir", type=Path, help="raw-input cache directory for --fetch")
    parser.add_argument("--output", type=Path, required=True, help="write reproducible audit JSON")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    args = parser.parse_args(argv)
    try:
        if args.fetch:
            if args.input or args.manifest or not args.cache_dir:
                parser.error("--fetch requires --cache-dir and excludes --input/--manifest")
            fetch_pinned_export(args.cache_dir, max_bytes=args.max_bytes)
            input_path, manifest_path = args.cache_dir / "formulas.jsonl", args.cache_dir / "manifest.json"
        else:
            if not args.input or not args.manifest:
                parser.error("provide --input and --manifest, or --fetch with --cache-dir")
            input_path, manifest_path = args.input, args.manifest
        if args.output.resolve() in {input_path.resolve(), manifest_path.resolve()}:
            raise AuditError("audit output must not overwrite raw inputs")
        report = audit_export(input_path, manifest_path, max_bytes=args.max_bytes, max_records=args.max_records)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(_json(report) + "\n", encoding="utf-8")
    except (AuditError, OSError, ValueError) as exc:
        parser.exit(1, f"audit failed: {exc}\n")
    print(_json({"output": str(args.output.resolve()), "revision": REVISION, "counts": report["counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
