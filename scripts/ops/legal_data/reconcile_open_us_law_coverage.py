#!/usr/bin/env python3
"""Reconcile exact-51 jurisdiction coverage and bucket deltas (OUL-022).

The deduplicated union of certified cohort receipts must equal the sealed
50-state-plus-DC allowlist. Georgia and North Carolina require clean official
replacement evidence. Puerto Rico and federal objects stay out of the default
set. Every live-bucket inventory delta is independently classified. Unknown
or failed-final dispositions fail closed.

Validation gate (no network)::

    python scripts/ops/legal_data/reconcile_open_us_law_coverage.py --require-51 --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    COHORT_BY_JURISDICTION,
    COHORT_JURISDICTIONS,
    COHORT_TASK_IDS,
    LeaseReportError,
    assert_no_secrets,
    cohort_codes,
    default_cohort_report_path,
    find_secret_surfaces,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    CANONICAL_JURISDICTIONS,
    FORBIDDEN_DEFAULT_JURISDICTIONS,
    is_forbidden_default_jurisdiction,
    reconcile_disposition,
)


TASK_ID = "OUL-022"
GOAL_ID = "OUL-G024"
PROGRAM_ID = "open-us-law-reindex-v1"
PRODUCER = "reconcile_open_us_law_coverage.py@1"
SCHEMA_VERSION = "open-us-law-exact-51-coverage-v1"
REPORT_SCHEMA = "ipfs_datasets_py/open-us-law-exact-51-coverage@1"
CODE_VERSION = "1"
SEALED_AT = "2026-08-13T00:00:00Z"
DEFAULT_CONFIGURATION = "state_statutes_exact_51"

COVERAGE_RELPATH = Path("docs/reports/open_us_law_reindex/exact_51_coverage.json")
BUCKET_SNAPSHOT_RELPATH = Path("docs/reports/open_us_law_reindex/bucket_snapshot.json")
COHORT_REPORT_DIR_RELPATH = Path("docs/reports/open_us_law_reindex")

JURISDICTION_COUNT = 51
REQUIRED_JURISDICTION_CODES: tuple[str, ...] = CANONICAL_JURISDICTION_ORDER
CLEAN_OFFICIAL_CODES: tuple[str, ...] = ("GA", "NC")
EXCLUDED_DEFAULT_CODES: frozenset[str] = frozenset(FORBIDDEN_DEFAULT_JURISDICTIONS)
COHORT_LETTERS: tuple[str, ...] = tuple(sorted(COHORT_JURISDICTIONS))

DISPOSITION_RECONCILED = "reconciled"
DISPOSITION_FAILED_FINAL = "failed_final"
DISPOSITION_UNKNOWN = "unknown"
DISPOSITION_TYPED_QUARANTINE = "typed_quarantine"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STATUTE_PATH_RE = re.compile(r"^us_([a-z]{2})_statutes\.parquet$", re.IGNORECASE)
_FEDERAL_STATUTE_RE = re.compile(r"^us_federal_(statutes|constitutions)\.parquet$", re.IGNORECASE)
_CONSTITUTION_PATH_RE = re.compile(r"^us_([a-z]+)_constitutions\.parquet$", re.IGNORECASE)
_PR_PATH_RE = re.compile(r"^us_pr_(statutes|constitutions)\.parquet$", re.IGNORECASE)
_WITHDRAWN_STATUTE_PATHS: tuple[str, ...] = (
    "us_ga_statutes.parquet",
    "us_nc_statutes.parquet",
)

COVERAGE_DESCRIPTION = (
    "Deduplicated exact-51 coverage matrix. The official cohort union is the "
    "50 postal states plus DC counted once. Clean official Georgia and North "
    "Carolina replacements fill the withdrawn bucket statutes. Puerto Rico, "
    "federal, and constitution objects remain explicit non-default members. "
    "Every bucket inventory delta is independently classified. Unknown or "
    "failed-final dispositions fail closed."
)


class CoverageError(RuntimeError):
    """Fail-closed exact-51 coverage reconciliation failure."""


def expected_jurisdiction_codes() -> tuple[str, ...]:
    return REQUIRED_JURISDICTION_CODES


def default_coverage_path(repo_root: Path | None = None) -> Path:
    return (repo_root or REPOSITORY_ROOT) / COVERAGE_RELPATH


def default_bucket_snapshot_path(repo_root: Path | None = None) -> Path:
    return (repo_root or REPOSITORY_ROOT) / BUCKET_SNAPSHOT_RELPATH


def default_cohort_dir(repo_root: Path | None = None) -> Path:
    return (repo_root or REPOSITORY_ROOT) / COHORT_REPORT_DIR_RELPATH


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def coverage_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return sha256_bytes(coverage_json_bytes(value))


def encode_coverage(payload: Mapping[str, Any]) -> bytes:
    return coverage_json_bytes(payload)


def _strict_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CoverageError(f"{label} must be an object")
    return dict(value)


def _strict_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CoverageError(f"{label} must be a non-empty string")
    return value.strip()


def _sha256_hex(value: Any, label: str) -> str:
    digest = _strict_string(value, label).lower()
    if not _SHA256_RE.fullmatch(digest):
        raise CoverageError(f"{label} is not a SHA-256 digest")
    return digest


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CoverageError(f"{label} must be a non-negative integer")
    return value


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise CoverageError(f"{label} missing: {path.as_posix()}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise CoverageError(f"unable to read {label}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise CoverageError(f"{label} root must be an object")
    return dict(payload)


def _relative_posix(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.name


def statute_code_from_path(path: str) -> str | None:
    match = _STATUTE_PATH_RE.fullmatch(path)
    if match is None:
        return None
    return match.group(1).upper()


def _parse_admitted_body(receipt: Mapping[str, Any]) -> dict[str, Any]:
    raw = receipt.get("admitted_body")
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        if isinstance(parsed, Mapping):
            return dict(parsed)
    return {}


def _frontier_block(receipt: Mapping[str, Any]) -> dict[str, Any]:
    frontier = receipt.get("frontier")
    return dict(frontier) if isinstance(frontier, Mapping) else {}


def _text_quality_block(receipt: Mapping[str, Any]) -> dict[str, Any]:
    block = receipt.get("text_quality")
    return dict(block) if isinstance(block, Mapping) else {}


def _hash_block(receipt: Mapping[str, Any]) -> dict[str, Any]:
    block = receipt.get("hashes")
    return dict(block) if isinstance(block, Mapping) else {}


def _disposition_block(receipt: Mapping[str, Any]) -> dict[str, Any]:
    block = receipt.get("disposition")
    return dict(block) if isinstance(block, Mapping) else {}


def official_replacement_present(code: str, receipt: Mapping[str, Any]) -> bool:
    frontier = _frontier_block(receipt)
    flag = f"{str(code).strip().lower()}_contaminated_bucket_replaced"
    if frontier.get(flag) is True:
        return True
    body = _parse_admitted_body(receipt)
    if body.get("contaminated_bucket_replaced") is True:
        return True
    replacement = str(body.get("replacement_source") or "").strip().lower()
    return replacement in {"official_clean_text", "official_replacement"}


def is_clean_official_receipt(code: str, receipt: Mapping[str, Any]) -> bool:
    if not receipt:
        return False
    authority = str(receipt.get("source_authority_class") or "").strip().lower()
    if authority != "official":
        return False
    if _text_quality_block(receipt).get("contaminated") is True:
        return False
    if str(code).strip().upper() in CLEAN_OFFICIAL_CODES:
        return official_replacement_present(code, receipt)
    return True


def classify_disposition(receipt: Mapping[str, Any] | None) -> str:
    if not isinstance(receipt, Mapping) or not receipt:
        return DISPOSITION_UNKNOWN
    disposition = _disposition_block(receipt)
    if not disposition:
        return DISPOSITION_UNKNOWN
    explicit = str(
        disposition.get("status") or disposition.get("kind") or ""
    ).strip().lower()
    if explicit in {"unknown", "unspecified", "unset", "none", "null"}:
        return DISPOSITION_UNKNOWN
    ok, _detail = reconcile_disposition(disposition)
    if not ok:
        return DISPOSITION_UNKNOWN
    failed_final = disposition.get("failed_final")
    if isinstance(failed_final, int) and not isinstance(failed_final, bool) and failed_final > 0:
        return DISPOSITION_FAILED_FINAL
    quarantined = disposition.get("quarantined")
    if isinstance(quarantined, int) and not isinstance(quarantined, bool) and quarantined > 0:
        return DISPOSITION_TYPED_QUARANTINE
    return DISPOSITION_RECONCILED


def load_cohort_report(
    letter: str, *, repo_root: Path | None = None
) -> dict[str, Any]:
    root = repo_root or REPOSITORY_ROOT
    path = default_cohort_report_path(letter, root)
    payload = _load_json_object(path, f"cohort {letter} report")
    if payload.get("schema_version") != "open-us-law-cohort-evidence-v1":
        raise CoverageError(
            f"cohort {letter} schema_version must be open-us-law-cohort-evidence-v1"
        )
    observed = str(payload.get("cohort") or "").strip().upper()
    if observed != letter:
        raise CoverageError(f"cohort report {path.name} has cohort={observed!r}")
    expected = list(cohort_codes(letter))
    jurisdictions = [
        str(item).strip().upper() for item in (payload.get("jurisdictions") or [])
    ]
    if jurisdictions != expected:
        raise CoverageError(
            f"cohort {letter} jurisdictions must be {expected}, got {jurisdictions}"
        )
    if payload.get("program_id") != PROGRAM_ID:
        raise CoverageError(f"cohort {letter} program_id must be {PROGRAM_ID}")
    if payload.get("authorizing_for_publication") is not False:
        raise CoverageError(f"cohort {letter} cannot authorize publication")
    if payload.get("fixture_execution") is True:
        raise CoverageError(f"cohort {letter} fixture execution is not admissible")
    if payload.get("fixture_proves_cohort_completion") is not False:
        raise CoverageError(
            f"cohort {letter} fixture_proves_cohort_completion must be false"
        )
    if payload.get("cohort_complete") is not True:
        raise CoverageError(f"cohort {letter} is not marked cohort_complete")
    if payload.get("status") not in {"success", "passed"}:
        raise CoverageError(f"cohort {letter} status is not certified success")
    digest = _sha256_hex(payload.get("report_digest_sha256"), f"cohort {letter} digest")
    body = {key: value for key, value in payload.items() if key != "report_digest_sha256"}
    if digest != sha256_json(body):
        raise CoverageError(f"cohort {letter} report_digest_sha256 does not match bytes")
    secrets = find_secret_surfaces(payload)
    if secrets:
        raise CoverageError(
            f"cohort {letter} contains secret material: " + ",".join(secrets)
        )
    receipts = payload.get("jurisdiction_receipts")
    if not isinstance(receipts, Mapping):
        raise CoverageError(f"cohort {letter} jurisdiction_receipts must be an object")
    for code in expected:
        if code not in receipts or not isinstance(receipts[code], Mapping):
            raise CoverageError(f"cohort {letter} is missing a receipt for {code}")
    payload["_path"] = _relative_posix(path, root)
    return payload


def load_all_cohort_reports(*, repo_root: Path | None = None) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for letter in COHORT_LETTERS:
        reports[letter] = load_cohort_report(letter, repo_root=repo_root)
    return reports


def union_cohort_receipts(
    reports: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    union: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    extras: list[str] = []
    for letter, report in reports.items():
        receipts = report.get("jurisdiction_receipts")
        if not isinstance(receipts, Mapping):
            raise CoverageError(f"cohort {letter} jurisdiction_receipts must be an object")
        expected = set(cohort_codes(letter))
        for raw_code, receipt in receipts.items():
            code = str(raw_code).strip().upper()
            if is_forbidden_default_jurisdiction(code):
                extras.append(code)
                continue
            if code not in CANONICAL_JURISDICTIONS:
                extras.append(code)
                continue
            if code not in expected:
                extras.append(code)
                continue
            if code in union:
                duplicates.append(code)
                continue
            if not isinstance(receipt, Mapping):
                raise CoverageError(f"{code} receipt must be an object")
            declared = str(receipt.get("jurisdiction") or code).strip().upper()
            if declared != code:
                raise CoverageError(
                    f"cohort {letter} receipt key {code} does not match jurisdiction={declared}"
                )
            union[code] = dict(receipt)
    if extras:
        raise CoverageError(
            "default cohort union includes excluded jurisdictions: "
            + ",".join(sorted(set(extras)))
        )
    if duplicates:
        raise CoverageError(
            "jurisdiction receipts are not unique across cohorts: "
            + ",".join(sorted(set(duplicates)))
        )
    if union.get("DC") is None:
        raise CoverageError("DC must appear exactly once in the cohort union")
    return union


def load_bucket_snapshot(*, repo_root: Path | None = None) -> dict[str, Any]:
    path = default_bucket_snapshot_path(repo_root)
    payload = _load_json_object(path, "bucket snapshot")
    if payload.get("schema_version") != "open-us-law-bucket-snapshot-v1":
        raise CoverageError("bucket snapshot schema_version is not sealed")
    if payload.get("authorizing_for_publication") is not False:
        raise CoverageError("bucket snapshot cannot authorize publication")
    if payload.get("revision_pin") is not False:
        raise CoverageError("mutable bucket snapshot must not be a revision pin")
    return payload


def classify_bucket_path(path: str) -> dict[str, Any]:
    statute_code = statute_code_from_path(path)
    if _PR_PATH_RE.fullmatch(path):
        return {
            "path": path,
            "kind": "puerto_rico",
            "code": "PR",
            "in_default_set": False,
        }
    if _FEDERAL_STATUTE_RE.fullmatch(path):
        return {
            "path": path,
            "kind": "federal",
            "code": "FEDERAL",
            "in_default_set": False,
        }
    constitution = _CONSTITUTION_PATH_RE.fullmatch(path)
    if constitution is not None:
        code = constitution.group(1).upper()
        kind = "constitution"
        if code == "PR":
            kind = "puerto_rico_constitution"
        elif code == "FEDERAL":
            kind = "federal_constitution"
        return {
            "path": path,
            "kind": kind,
            "code": code,
            "in_default_set": False,
        }
    if statute_code is not None:
        forbidden = is_forbidden_default_jurisdiction(statute_code)
        return {
            "path": path,
            "kind": "statute",
            "code": statute_code,
            "in_default_set": statute_code in CANONICAL_JURISDICTIONS and not forbidden,
        }
    return {
        "path": path,
        "kind": "control",
        "code": None,
        "in_default_set": False,
    }


def collect_bucket_paths(snapshot: Mapping[str, Any]) -> list[str]:
    objects = snapshot.get("objects")
    if not isinstance(objects, Sequence) or isinstance(objects, (str, bytes)):
        reconciliation = snapshot.get("reconciliation")
        if isinstance(reconciliation, Mapping):
            live = reconciliation.get("live_parquet_paths")
            if isinstance(live, Sequence) and not isinstance(live, (str, bytes)):
                return [str(item) for item in live]
        raise CoverageError("bucket snapshot objects must be a list")
    paths: list[str] = []
    for item in objects:
        if isinstance(item, Mapping) and item.get("path"):
            paths.append(str(item["path"]))
    return paths


def reconcile_bucket_deltas(
    snapshot: Mapping[str, Any],
    *,
    official_codes: Sequence[str],
    clean_official: Mapping[str, bool],
) -> dict[str, Any]:
    paths = collect_bucket_paths(snapshot)
    classified = [classify_bucket_path(path) for path in paths]
    live_default_statutes = sorted(
        {
            item["code"]
            for item in classified
            if item["kind"] == "statute" and item["in_default_set"] and item["code"]
        }
    )
    live_pr = sorted(item["path"] for item in classified if "puerto_rico" in str(item["kind"]))
    live_federal = sorted(item["path"] for item in classified if "federal" in str(item["kind"]))
    live_constitutions = sorted(
        item["path"] for item in classified if "constitution" in str(item["kind"])
    )
    present = set(live_default_statutes)
    absent_required = [code for code in CLEAN_OFFICIAL_CODES if code not in present]
    unexpected_absent = [
        code
        for code in REQUIRED_JURISDICTION_CODES
        if code not in present and code not in CLEAN_OFFICIAL_CODES
    ]
    extra_default = [
        code for code in live_default_statutes if code not in CANONICAL_JURISDICTIONS
    ]
    pr_in_default = [code for code in live_default_statutes if code == "PR"]

    checksum = snapshot.get("checksum_manifest")
    checksum_map = checksum if isinstance(checksum, Mapping) else {}
    withdrawn_listed = [
        str(item)
        for item in (checksum_map.get("withdrawn_paths_still_listed") or [])
    ]
    stale = checksum_map.get("stale") is True
    mismatches = [
        dict(item)
        for item in (checksum_map.get("size_or_digest_mismatches") or [])
        if isinstance(item, Mapping)
    ]

    official = set(official_codes)
    ga_official = clean_official.get("GA") is True and "GA" in official
    nc_official = clean_official.get("NC") is True and "NC" in official
    absent_filled = absent_required == list(CLEAN_OFFICIAL_CODES) and ga_official and nc_official

    deltas = [
        {
            "id": "absent_required_statutes",
            "codes": absent_required,
            "expected": list(CLEAN_OFFICIAL_CODES),
            "resolution": "clean_official_replacement",
            "reconciled": absent_filled,
        },
        {
            "id": "withdrawn_checksum_listings",
            "paths": withdrawn_listed,
            "expected": list(_WITHDRAWN_STATUTE_PATHS),
            "resolution": "stale_checksum_not_admitted",
            "reconciled": withdrawn_listed == list(_WITHDRAWN_STATUTE_PATHS) and stale,
        },
        {
            "id": "federal_excluded_from_default",
            "paths": live_federal,
            "resolution": "non_default_configuration",
            "reconciled": bool(live_federal) and not any(
                item["in_default_set"] for item in classified if "federal" in str(item["kind"])
            ),
        },
        {
            "id": "pr_excluded_from_default",
            "paths": live_pr,
            "resolution": "non_default_configuration",
            "reconciled": bool(live_pr) and not pr_in_default,
        },
        {
            "id": "constitutions_excluded_from_default",
            "paths": live_constitutions,
            "resolution": "non_default_code_family",
            "reconciled": all(not item["in_default_set"] for item in classified if "constitution" in str(item["kind"])),
        },
        {
            "id": "stale_checksum_size_mismatches",
            "mismatches": mismatches,
            "resolution": "checksum_not_authoritative",
            "reconciled": stale,
        },
        {
            "id": "live_seed_statutes_not_authoritative",
            "codes": live_default_statutes,
            "resolution": "official_cohort_receipts_supersede_bucket_seed",
            "reconciled": set(live_default_statutes) <= official
            and not unexpected_absent
            and not extra_default,
        },
    ]
    unresolved = [item["id"] for item in deltas if item.get("reconciled") is not True]
    return {
        "all_reconciled": not unresolved,
        "unresolved": unresolved,
        "absent_required_statute_codes": absent_required,
        "live_default_statute_codes": live_default_statutes,
        "excluded_pr_paths": live_pr,
        "excluded_federal_paths": live_federal,
        "excluded_constitution_paths": live_constitutions,
        "withdrawn_paths_still_listed": withdrawn_listed,
        "stale_checksum": stale,
        "deltas": deltas,
        "snapshot_digest_sha256": snapshot.get("snapshot_digest_sha256"),
        "inventory_digest_sha256": snapshot.get("inventory_digest_sha256"),
    }


def _jurisdiction_row(
    code: str,
    receipt: Mapping[str, Any],
    *,
    cohort: str,
    bucket_statute_present: bool,
) -> dict[str, Any]:
    disposition = _disposition_block(receipt)
    status = classify_disposition(receipt)
    hashes = _hash_block(receipt)
    frontier = _frontier_block(receipt)
    certification_ok = True
    clean_official = is_clean_official_receipt(code, receipt)
    replacement = official_replacement_present(code, receipt) if code in CLEAN_OFFICIAL_CODES else False
    row_count = receipt.get("row_count")
    if not isinstance(row_count, int) or isinstance(row_count, bool):
        row_count = disposition.get("fetched")
    delta = "none"
    if code in CLEAN_OFFICIAL_CODES and not bucket_statute_present:
        delta = "absent_required_statute_filled_by_official"
    elif bucket_statute_present:
        delta = "bucket_seed_superseded_by_official_receipt"
    return {
        "jurisdiction_code": code,
        "cohort": cohort,
        "task_id": COHORT_TASK_IDS[cohort],
        "in_default_set": True,
        "bucket_statute_present": bucket_statute_present,
        "bucket_delta": delta,
        "clean_official": clean_official,
        "official_replacement": replacement,
        "source_authority_class": receipt.get("source_authority_class"),
        "source_domain": receipt.get("source_domain"),
        "frontier_closed": frontier.get("closed") is True,
        "contaminated": _text_quality_block(receipt).get("contaminated") is True,
        "disposition_status": status,
        "disposition": {
            "discovered": disposition.get("discovered"),
            "fetched": disposition.get("fetched"),
            "excluded": disposition.get("excluded"),
            "quarantined": disposition.get("quarantined"),
            "failed_final": disposition.get("failed_final"),
            "status": status,
        },
        "row_count": row_count,
        "admitted_body_sha256": hashes.get("admitted_body_sha256"),
        "frontier_digest_sha256": frontier.get("frontier_digest_sha256")
        or hashes.get("frontier_digest_sha256"),
        "certification_ok": certification_ok,
    }


def _aggregate_disposition(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    totals = {
        "discovered": 0,
        "fetched": 0,
        "excluded": 0,
        "quarantined": 0,
        "failed_final": 0,
        "unknown": 0,
    }
    for row in rows:
        disposition = row.get("disposition")
        if not isinstance(disposition, Mapping):
            totals["unknown"] += 1
            continue
        status = str(disposition.get("status") or "")
        if status == DISPOSITION_UNKNOWN:
            totals["unknown"] += 1
        for key in ("discovered", "fetched", "excluded", "quarantined", "failed_final"):
            value = disposition.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] += value
    ok, detail = reconcile_disposition(totals)
    return {
        **totals,
        "arithmetic_ok": ok,
        "detail": detail,
        "unknown_or_failed_final": totals["unknown"] + totals["failed_final"],
    }


def collect_open_gaps(
    *,
    rows: Sequence[Mapping[str, Any]],
    missing: Sequence[str],
    extra: Sequence[str],
    bucket: Mapping[str, Any],
    default_exclusions: Sequence[str],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for code in missing:
        gaps.append(
            {
                "kind": "missing_jurisdiction",
                "jurisdiction_code": code,
                "terminal": False,
            }
        )
    for code in extra:
        gaps.append(
            {
                "kind": "extra_default_jurisdiction",
                "jurisdiction_code": code,
                "terminal": False,
            }
        )
    for code in default_exclusions:
        gaps.append(
            {
                "kind": "excluded_code_in_default",
                "jurisdiction_code": code,
                "terminal": False,
            }
        )
    for row in rows:
        code = str(row.get("jurisdiction_code") or "")
        status = str(row.get("disposition_status") or DISPOSITION_UNKNOWN)
        if status == DISPOSITION_UNKNOWN:
            gaps.append(
                {
                    "kind": "unknown_disposition",
                    "jurisdiction_code": code,
                    "terminal": False,
                }
            )
        elif status == DISPOSITION_FAILED_FINAL:
            gaps.append(
                {
                    "kind": "failed_final",
                    "jurisdiction_code": code,
                    "terminal": False,
                }
            )
        if row.get("frontier_closed") is not True:
            gaps.append(
                {
                    "kind": "open_frontier",
                    "jurisdiction_code": code,
                    "terminal": False,
                }
            )
        if code in CLEAN_OFFICIAL_CODES and row.get("clean_official") is not True:
            gaps.append(
                {
                    "kind": "missing_clean_official_replacement",
                    "jurisdiction_code": code,
                    "terminal": False,
                }
            )
    for delta_id in bucket.get("unresolved") or []:
        gaps.append(
            {
                "kind": "unreconciled_bucket_delta",
                "delta_id": delta_id,
                "terminal": False,
            }
        )
    return gaps


def build_coverage_payload(
    *,
    repo_root: Path | None = None,
    reports: Mapping[str, Mapping[str, Any]] | None = None,
    snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = repo_root or REPOSITORY_ROOT
    loaded_reports = dict(reports) if reports is not None else load_all_cohort_reports(repo_root=root)
    loaded_snapshot = dict(snapshot) if snapshot is not None else load_bucket_snapshot(repo_root=root)
    receipts = union_cohort_receipts(loaded_reports)
    observed = [code for code in REQUIRED_JURISDICTION_CODES if code in receipts]
    extra = sorted(code for code in receipts if code not in CANONICAL_JURISDICTIONS)
    missing = [code for code in REQUIRED_JURISDICTION_CODES if code not in receipts]
    forbidden_observed = [code for code in receipts if is_forbidden_default_jurisdiction(code)]

    live_default = set()
    for path in collect_bucket_paths(loaded_snapshot):
        classified = classify_bucket_path(path)
        if classified["in_default_set"] and classified["code"]:
            live_default.add(classified["code"])

    rows: list[dict[str, Any]] = []
    for code in REQUIRED_JURISDICTION_CODES:
        receipt = receipts.get(code)
        if receipt is None:
            continue
        letter = COHORT_BY_JURISDICTION[code]
        rows.append(
            _jurisdiction_row(
                code,
                receipt,
                cohort=letter,
                bucket_statute_present=code in live_default,
            )
        )

    clean_official = {
        code: next(
            (row["clean_official"] for row in rows if row["jurisdiction_code"] == code),
            False,
        )
        for code in CLEAN_OFFICIAL_CODES
    }
    bucket = reconcile_bucket_deltas(
        loaded_snapshot,
        official_codes=list(receipts),
        clean_official=clean_official,
    )
    aggregate = _aggregate_disposition(rows)
    gaps = collect_open_gaps(
        rows=rows,
        missing=missing,
        extra=extra + forbidden_observed,
        bucket=bucket,
        default_exclusions=forbidden_observed,
    )
    cohort_digests = {
        letter: {
            "path": report.get("_path")
            or default_cohort_report_path(letter, root).name,
            "report_digest_sha256": report.get("report_digest_sha256"),
            "task_id": report.get("task_id") or COHORT_TASK_IDS[letter],
            "jurisdictions": list(report.get("jurisdictions") or cohort_codes(letter)),
        }
        for letter, report in loaded_reports.items()
    }
    payload: dict[str, Any] = {
        "authorizing_for_publication": False,
        "bucket_deltas": bucket,
        "checks": {
            "clean_official_ga_nc_required": True,
            "dc_counted_once_required": True,
            "exact_51_required": True,
            "failed_final_forbidden": True,
            "pr_and_federal_excluded_from_default": True,
            "unknown_disposition_forbidden": True,
        },
        "clean_official_ga": clean_official.get("GA") is True,
        "clean_official_nc": clean_official.get("NC") is True,
        "code_version": CODE_VERSION,
        "cohorts": cohort_digests,
        "configuration": DEFAULT_CONFIGURATION,
        "dc_counted_once": observed.count("DC") == 1 and extra.count("DC") == 0,
        "default_exclusions": sorted(EXCLUDED_DEFAULT_CODES),
        "description": COVERAGE_DESCRIPTION,
        "disposition": aggregate,
        "exact_51": observed == list(REQUIRED_JURISDICTION_CODES) and not extra and not missing,
        "excluded_from_default": {
            "federal_paths": list(bucket.get("excluded_federal_paths") or []),
            "pr_paths": list(bucket.get("excluded_pr_paths") or []),
            "codes": ["PR", "FEDERAL"],
        },
        "goal_id": GOAL_ID,
        "jurisdiction_count": len(observed),
        "jurisdiction_codes": observed,
        "jurisdictions": rows,
        "missing_jurisdiction_codes": missing,
        "open_gaps": gaps,
        "open_gap_count": len(gaps),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "schema_version": SCHEMA_VERSION,
        "sealed_at": SEALED_AT,
        "status": (
            "success"
            if (
                observed == list(REQUIRED_JURISDICTION_CODES)
                and not extra
                and not missing
                and not forbidden_observed
                and clean_official.get("GA") is True
                and clean_official.get("NC") is True
                and aggregate["unknown_or_failed_final"] == 0
                and bucket.get("all_reconciled") is True
            )
            else "failed"
        ),
        "task_id": TASK_ID,
    }
    try:
        assert_no_secrets(payload)
    except LeaseReportError as exc:
        raise CoverageError(str(exc)) from exc
    body = {key: value for key, value in payload.items() if key != "report_digest_sha256"}
    payload["report_digest_sha256"] = sha256_json(body)
    return payload


def validate_coverage(
    payload: Mapping[str, Any],
    *,
    require_51: bool = True,
    require_no_open_gaps: bool = False,
) -> dict[str, Any]:
    mapping = _strict_mapping(payload, "exact_51_coverage")
    if mapping.get("schema_version") != SCHEMA_VERSION:
        raise CoverageError("schema_version must be open-us-law-exact-51-coverage-v1")
    if mapping.get("producer") != PRODUCER:
        raise CoverageError(f"producer must be {PRODUCER}")
    if mapping.get("program_id") != PROGRAM_ID:
        raise CoverageError(f"program_id must be {PROGRAM_ID}")
    if mapping.get("task_id") != TASK_ID:
        raise CoverageError(f"task_id must be {TASK_ID}")
    if mapping.get("goal_id") != GOAL_ID:
        raise CoverageError(f"goal_id must be {GOAL_ID}")
    if mapping.get("configuration") != DEFAULT_CONFIGURATION:
        raise CoverageError("configuration must be state_statutes_exact_51")
    if mapping.get("authorizing_for_publication") is not False:
        raise CoverageError("coverage report cannot authorize publication")
    secrets = find_secret_surfaces(mapping)
    if secrets:
        raise CoverageError("coverage report contains secret material: " + ",".join(secrets))

    codes = [
        str(item).strip().upper()
        for item in (mapping.get("jurisdiction_codes") or [])
        if str(item).strip()
    ]
    if len(codes) != len(set(codes)):
        raise CoverageError("jurisdiction_codes are not unique")
    if codes.count("DC") != 1:
        raise CoverageError("DC must appear exactly once")
    extras = [code for code in codes if is_forbidden_default_jurisdiction(code)]
    if extras:
        raise CoverageError(
            "default set includes excluded jurisdictions: " + ",".join(extras)
        )
    extra_canonical = [code for code in codes if code not in CANONICAL_JURISDICTIONS]
    if extra_canonical:
        raise CoverageError(
            "default set includes non-exact-51 codes: " + ",".join(extra_canonical)
        )

    rows = mapping.get("jurisdictions")
    if not isinstance(rows, list):
        raise CoverageError("jurisdictions must be a list")
    row_codes = [
        str(item.get("jurisdiction_code") or "").strip().upper()
        for item in rows
        if isinstance(item, Mapping)
    ]
    if row_codes != codes:
        raise CoverageError("jurisdictions rows must follow jurisdiction_codes")

    if require_51:
        if mapping.get("jurisdiction_count") != JURISDICTION_COUNT:
            raise CoverageError("jurisdiction_count must be 51")
        if codes != list(REQUIRED_JURISDICTION_CODES):
            missing = [code for code in REQUIRED_JURISDICTION_CODES if code not in codes]
            extra = [code for code in codes if code not in REQUIRED_JURISDICTION_CODES]
            raise CoverageError(
                "jurisdiction set is not exact-51; "
                f"missing={missing or '[]'} extra={extra or '[]'}"
            )
        if mapping.get("exact_51") is not True:
            raise CoverageError("exact_51 must be true")
        if mapping.get("dc_counted_once") is not True:
            raise CoverageError("dc_counted_once must be true")

    ga = next((item for item in rows if isinstance(item, Mapping) and item.get("jurisdiction_code") == "GA"), None)
    nc = next((item for item in rows if isinstance(item, Mapping) and item.get("jurisdiction_code") == "NC"), None)
    if ga is None or nc is None:
        raise CoverageError("clean official GA and NC rows are required")
    if ga.get("clean_official") is not True or ga.get("official_replacement") is not True:
        raise CoverageError("GA must include clean official replacement evidence")
    if nc.get("clean_official") is not True or nc.get("official_replacement") is not True:
        raise CoverageError("NC must include clean official replacement evidence")
    if mapping.get("clean_official_ga") is not True or mapping.get("clean_official_nc") is not True:
        raise CoverageError("coverage report must flag clean official GA and NC")

    unknown: list[str] = []
    failed_final: list[str] = []
    for item in rows:
        if not isinstance(item, Mapping):
            raise CoverageError("jurisdiction rows must be objects")
        status = str(item.get("disposition_status") or DISPOSITION_UNKNOWN)
        code = str(item.get("jurisdiction_code") or "")
        if status == DISPOSITION_UNKNOWN:
            unknown.append(code)
        elif status == DISPOSITION_FAILED_FINAL:
            failed_final.append(code)
        disposition = _strict_mapping(item.get("disposition"), f"{code}.disposition")
        if disposition.get("status") != status:
            raise CoverageError(f"{code} disposition.status does not match disposition_status")
        if status == DISPOSITION_FAILED_FINAL or (
            isinstance(disposition.get("failed_final"), int)
            and not isinstance(disposition.get("failed_final"), bool)
            and disposition.get("failed_final", 0) > 0
        ):
            failed_final.append(code)
    if unknown:
        raise CoverageError("unknown dispositions present: " + ",".join(unknown))
    if failed_final:
        raise CoverageError("failed-final dispositions present: " + ",".join(sorted(set(failed_final))))

    aggregate = _strict_mapping(mapping.get("disposition"), "disposition")
    if _non_negative_int(aggregate.get("failed_final"), "disposition.failed_final") != 0:
        raise CoverageError("aggregate failed_final must be 0")
    if _non_negative_int(aggregate.get("unknown"), "disposition.unknown") != 0:
        raise CoverageError("aggregate unknown dispositions must be 0")
    if aggregate.get("unknown_or_failed_final") != 0:
        raise CoverageError("unknown or failed-final dispositions must be zero")
    if aggregate.get("arithmetic_ok") is not True:
        raise CoverageError("aggregate disposition arithmetic failed")

    excluded = _strict_mapping(mapping.get("excluded_from_default"), "excluded_from_default")
    if "PR" not in [str(item).upper() for item in (excluded.get("codes") or [])]:
        raise CoverageError("PR must be excluded from the default set")
    if not any("federal" in str(item).lower() for item in (excluded.get("codes") or [])):
        raise CoverageError("federal must be excluded from the default set")
    if not excluded.get("pr_paths") or not excluded.get("federal_paths"):
        raise CoverageError("excluded PR and federal bucket paths must be recorded")

    bucket = _strict_mapping(mapping.get("bucket_deltas"), "bucket_deltas")
    if bucket.get("all_reconciled") is not True:
        raise CoverageError(
            "bucket deltas are not fully reconciled: "
            + ",".join(str(item) for item in (bucket.get("unresolved") or []))
        )
    if list(bucket.get("absent_required_statute_codes") or []) != list(CLEAN_OFFICIAL_CODES):
        raise CoverageError("bucket deltas must record absent GA and NC statute codes")
    deltas = bucket.get("deltas")
    if not isinstance(deltas, list) or not deltas:
        raise CoverageError("bucket deltas list is required")
    if any(not isinstance(item, Mapping) or item.get("reconciled") is not True for item in deltas):
        raise CoverageError("every bucket delta must be independently reconciled")

    gaps = mapping.get("open_gaps")
    if not isinstance(gaps, list):
        raise CoverageError("open_gaps must be a list")
    if mapping.get("open_gap_count") != len(gaps):
        raise CoverageError("open_gap_count does not match open_gaps")
    if require_no_open_gaps and gaps:
        raise CoverageError(
            "open gaps remain: "
            + ",".join(str(item.get("kind") if isinstance(item, Mapping) else item) for item in gaps)
        )

    digest = _sha256_hex(mapping.get("report_digest_sha256"), "report_digest_sha256")
    body = {key: value for key, value in mapping.items() if key != "report_digest_sha256"}
    if digest != sha256_json(body):
        raise CoverageError("report_digest_sha256 does not match the canonical coverage bytes")
    if mapping.get("status") != "success":
        raise CoverageError("coverage status must be success")
    return {
        "jurisdiction_count": len(codes),
        "jurisdiction_codes": codes,
        "exact_51": codes == list(REQUIRED_JURISDICTION_CODES),
        "dc_counted_once": codes.count("DC") == 1,
        "clean_official_ga": True,
        "clean_official_nc": True,
        "pr_excluded": True,
        "federal_excluded": True,
        "bucket_deltas_reconciled": True,
        "unknown_or_failed_final": 0,
        "open_gap_count": len(gaps),
        "report_digest_sha256": digest,
    }


def audit_coverage(
    payload: Mapping[str, Any] | None = None,
    *,
    require_51: bool = True,
    require_no_open_gaps: bool = False,
) -> dict[str, Any]:
    report_payload = payload if payload is not None else load_coverage()
    projection = validate_coverage(
        report_payload,
        require_51=require_51,
        require_no_open_gaps=require_no_open_gaps,
    )
    report = {
        "report_schema": REPORT_SCHEMA,
        "code_version": CODE_VERSION,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "status": "passed",
        "require_51": require_51,
        "require_no_open_gaps": require_no_open_gaps,
        "authorizing_for_publication": False,
        **projection,
    }
    report["report_digest_sha256"] = sha256_json(report)
    return report


def load_coverage(path: Path | None = None) -> dict[str, Any]:
    return _load_json_object(path or default_coverage_path(), "exact-51 coverage report")


def write_coverage(
    path: Path,
    payload: Mapping[str, Any],
    *,
    repo_root: Path | None = None,
) -> None:
    validate_coverage(payload, require_51=True, require_no_open_gaps=False)
    encoded = encode_coverage(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(encoded)
    tmp.replace(path)


def check_committed_coverage(
    *,
    require_51: bool = True,
    require_no_open_gaps: bool = False,
    repo_root: Path | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    root = repo_root or REPOSITORY_ROOT
    committed_path = path or default_coverage_path(root)
    committed_bytes = committed_path.read_bytes() if committed_path.is_file() else b""
    generated = build_coverage_payload(repo_root=root)
    generated_bytes = encode_coverage(generated)
    if committed_bytes != generated_bytes:
        raise CoverageError(
            "committed exact_51_coverage.json differs from the deterministic "
            "builder; regenerate and commit the sealed coverage report"
        )
    return audit_coverage(
        generated,
        require_51=require_51,
        require_no_open_gaps=require_no_open_gaps,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconcile exact-51 Open US Law jurisdiction coverage and bucket deltas."
    )
    parser.add_argument(
        "--require-51",
        dest="require_51",
        action="store_true",
        help="Require exact set equality with the 50-state-plus-DC allowlist.",
    )
    parser.add_argument(
        "--require-no-open-gaps",
        dest="require_no_open_gaps",
        action="store_true",
        help="Fail if any non-terminal acquisition, rights, or frontier gap remains.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the committed exact_51_coverage.json against the sealed builder.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Regenerate and atomically write the sealed coverage report.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the audit report as JSON.",
    )
    parser.add_argument(
        "--report",
        default="",
        help="Optional coverage report path. Defaults to docs/reports/open_us_law_reindex/exact_51_coverage.json.",
    )
    return parser


def _print_json(value: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _failed_payload(exc: BaseException) -> dict[str, Any]:
    return {
        "authorizing_for_publication": False,
        "error": str(exc),
        "goal_id": GOAL_ID,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "status": "failed",
        "task_id": TASK_ID,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.check and not args.write:
        sys.stderr.write("reconcile_open_us_law_coverage: FAILED: --check is required\n")
        return 2
    if not args.require_51:
        sys.stderr.write("reconcile_open_us_law_coverage: FAILED: --require-51 is required\n")
        return 2

    report_path = (
        Path(args.report).expanduser().resolve()
        if str(args.report or "").strip()
        else default_coverage_path()
    )

    try:
        if args.write:
            payload = build_coverage_payload()
            write_coverage(report_path, payload)
            report = audit_coverage(
                payload,
                require_51=True,
                require_no_open_gaps=bool(args.require_no_open_gaps),
            )
            report["path"] = report_path.as_posix()
            report["status"] = "written" if not args.check else "passed"
        else:
            report = check_committed_coverage(
                require_51=True,
                require_no_open_gaps=bool(args.require_no_open_gaps),
                path=report_path,
            )
    except CoverageError as exc:
        if args.json:
            _print_json(_failed_payload(exc))
        else:
            sys.stderr.write(f"reconcile_open_us_law_coverage: FAILED: {exc}\n")
        return 1

    if args.json:
        _print_json(report)
    else:
        action = "WROTE" if args.write and not args.check else "PASSED"
        sys.stdout.write(
            "reconcile_open_us_law_coverage: "
            f"{action} "
            f"(jurisdictions={report['jurisdiction_count']} "
            f"exact_51={report['exact_51']} "
            f"dc_counted_once={report['dc_counted_once']} "
            f"ga_official={report['clean_official_ga']} "
            f"nc_official={report['clean_official_nc']} "
            f"bucket_deltas_reconciled={report['bucket_deltas_reconciled']} "
            f"unknown_or_failed_final={report['unknown_or_failed_final']})\n"
            f"  report_digest={report['report_digest_sha256']}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
