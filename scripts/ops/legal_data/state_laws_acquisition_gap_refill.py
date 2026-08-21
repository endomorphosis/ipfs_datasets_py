#!/usr/bin/env python3
"""Refill and close every state-law acquisition evidence gap (LCR-023).

Consumes the LCR-022 coverage matrix as the input of record. Cohort receipts
are read-only sources of content IDs. Each remaining gap is mapped to
jurisdiction / code-family / frontier child work. Downstream admission is
blocked until replacement receipts pass.

Fail-closed rules:

* Absence of ready work WITH remaining gaps is an error.
* Absence of ready work WITH zero gaps and 51 passing receipts is success.

Offline usage::

    python scripts/ops/legal_data/state_laws_acquisition_gap_refill.py --check
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    DEFAULT_CATALOG_RELATIVE_PATH,
    get_official_source_catalog,
    load_official_source_catalog,
)


TASK_ID = "LCR-023"
GOAL_ID = "LCR-G024"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "state_laws_acquisition_gap_refill.py"
REPORT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-full-scrape-acceptance@1"
EXPECTED_JURISDICTION_COUNT = 51
COHORT_LETTERS: tuple[str, ...] = tuple("ABCDEFGHIJKLM")
DEFAULT_RECEIPT_DIR = Path("docs/reports/legal_corpora_reindex")
DEFAULT_COVERAGE_RELPATH = Path("docs/reports/legal_corpora_reindex/full_scrape_coverage.json")
DEFAULT_REPORT_RELPATH = Path("docs/reports/legal_corpora_reindex/full_scrape_acceptance.json")
DEFAULT_CATALOG_RELPATH = DEFAULT_CATALOG_RELATIVE_PATH

WORK_KIND_JURISDICTION = "jurisdiction"
WORK_KIND_CODE_FAMILY = "code-family"
WORK_KIND_FRONTIER = "frontier"
WORK_KINDS: tuple[str, ...] = (
    WORK_KIND_JURISDICTION,
    WORK_KIND_CODE_FAMILY,
    WORK_KIND_FRONTIER,
)

HF_TOKEN_RE = re.compile(r"hf_[A-Za-z0-9]{8,}")
BEARER_RE = re.compile(r"Bearer\s+\S+")
HOME_PATH_RE = re.compile(r"/home/")
API_KEY_ASSIGN_RE = re.compile(
    r"(api[_-]?key|hf_token|authorization)\s*[\"']?\s*[:=]\s*[\"']?(?!\[REDACTED\])[A-Za-z0-9_\-]{8,}",
    re.IGNORECASE,
)
FINDING_CODE_RE = re.compile(r"^([A-Z]{2})\s*:")
FINDING_COHORT_RE = re.compile(r"^cohort\s+([A-M])\s*:", re.IGNORECASE)

FRONTIER_HINTS: tuple[str, ...] = (
    "open frontier",
    "frontier",
    "failed_final",
    "unvisited",
    "continuation",
    "pagination",
    "truncated",
    "sample/runtime cap",
    "sample_cap",
    "runtime_cap",
    "replay not closed",
    "partial checkpoint",
    "timeout promoted",
)
CODE_FAMILY_HINTS: tuple[str, ...] = (
    "stale",
    "index key",
    "parity",
    "code family",
    "code-family",
    "content digest",
    "row_count",
    "derived",
)


class AcquisitionGapRefillError(RuntimeError):
    """Raised when gap refill cannot complete fail-closed."""


def _load_module(filename: str, module_name: str):
    path = Path(__file__).with_name(filename)
    if not path.is_file():
        raise AcquisitionGapRefillError(f"required module missing: {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AcquisitionGapRefillError(f"unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_coverage_module():
    return _load_module(
        "certify_state_laws_full_scrape.py",
        "lcr023_certify_state_laws_full_scrape",
    )


def repository_root(repo_root: Path | str | None = None) -> Path:
    if repo_root is None:
        return REPOSITORY_ROOT
    return Path(repo_root).expanduser().resolve()


def default_coverage_path(repo_root: Path | str | None = None) -> Path:
    return repository_root(repo_root) / DEFAULT_COVERAGE_RELPATH


def default_report_path(repo_root: Path | str | None = None) -> Path:
    return repository_root(repo_root) / DEFAULT_REPORT_RELPATH


def default_receipt_dir(repo_root: Path | str | None = None) -> Path:
    return repository_root(repo_root) / DEFAULT_RECEIPT_DIR


def default_catalog_path(repo_root: Path | str | None = None) -> Path:
    return repository_root(repo_root) / DEFAULT_CATALOG_RELPATH


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(encoded)


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _safe_relpath(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.name


def load_json_object(path: Path) -> Dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise AcquisitionGapRefillError(f"JSON must be a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AcquisitionGapRefillError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AcquisitionGapRefillError(f"JSON root must be an object: {path}")
    return copy.deepcopy(payload)


def load_coverage_matrix(path: Path | str) -> Dict[str, Any]:
    coverage_path = Path(path).expanduser().resolve()
    payload = load_json_object(coverage_path)
    return payload


def scan_sensitive_material(payload: Any, *, label: str) -> List[str]:
    serialized = json.dumps(payload, default=str)
    findings: List[str] = []
    if HOME_PATH_RE.search(serialized):
        findings.append(f"{label}: contains absolute /home/ path")
    if HF_TOKEN_RE.search(serialized):
        findings.append(f"{label}: contains hf_ token material")
    if BEARER_RE.search(serialized):
        findings.append(f"{label}: contains Bearer token material")
    if API_KEY_ASSIGN_RE.search(serialized):
        findings.append(f"{label}: contains api_key/token assignment")
    return findings


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _boolish(value: Any) -> bool:
    return bool(value) and value not in (0, "0", "false", "False")


def _empty_cap(value: Any) -> bool:
    return value in (None, False, 0, "", [], {})


def _append_unique(items: List[str], message: str) -> None:
    if message not in items:
        items.append(message)


def _canonical_codes(coverage: Mapping[str, Any], coverage_mod: Any) -> List[str]:
    declared = coverage.get("canonical_jurisdictions")
    if isinstance(declared, Sequence) and not isinstance(declared, (str, bytes)) and declared:
        return [str(code).strip().upper() for code in declared]
    return list(coverage_mod.canonical_jurisdictions())


def _matrix_of(coverage: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    matrix = coverage.get("matrix")
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(matrix, Mapping):
        for raw_code, cell in matrix.items():
            code = str(raw_code).strip().upper()
            if isinstance(cell, Mapping):
                out[code] = dict(cell)
    if out:
        return out
    rows = coverage.get("jurisdictions")
    if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            code = str(item.get("jurisdiction") or "").strip().upper()
            if code:
                out[code] = dict(item)
    return out


def _cohort_states(coverage: Mapping[str, Any], letter: str) -> List[str]:
    letter = letter.strip().upper()
    summaries = coverage.get("cohort_receipts")
    if isinstance(summaries, Sequence) and not isinstance(summaries, (str, bytes)):
        for item in summaries:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("cohort") or "").strip().upper() == letter:
                states = item.get("states") or item.get("observed_states") or []
                if isinstance(states, Sequence) and not isinstance(states, (str, bytes)):
                    return [str(code).strip().upper() for code in states if str(code).strip()]
    matrix = _matrix_of(coverage)
    return sorted(
        code
        for code, cell in matrix.items()
        if str(cell.get("cohort") or "").strip().upper() == letter
    )


def classify_kind(text: str) -> str:
    lowered = str(text or "").strip().lower()
    if any(hint in lowered for hint in FRONTIER_HINTS):
        return WORK_KIND_FRONTIER
    if any(hint in lowered for hint in CODE_FAMILY_HINTS):
        return WORK_KIND_CODE_FAMILY
    return WORK_KIND_JURISDICTION


def _cell_issue_messages(code: str, cell: Mapping[str, Any]) -> List[tuple[str, str]]:
    issues: List[tuple[str, str]] = []
    status = str(cell.get("status") or "").strip().lower()
    if status not in {"success", "pass"}:
        issues.append((WORK_KIND_JURISDICTION, f"{code}: status={status or 'missing'} (not success)"))
    failed_final = _as_int(cell.get("failed_final"))
    if failed_final is None:
        issues.append((WORK_KIND_FRONTIER, f"{code}: failed_final missing"))
    elif failed_final != 0:
        issues.append((WORK_KIND_FRONTIER, f"{code}: failed_final={failed_final}"))
    if cell.get("frontier_closed") is not True:
        issues.append((WORK_KIND_FRONTIER, f"{code}: open frontier"))
    stale = list(cell.get("stale_keys") or [])
    if stale or cell.get("index_parity_ok") is False:
        issues.append((WORK_KIND_CODE_FAMILY, f"{code}: stale or drifted index keys"))
    if not _empty_cap(cell.get("sample_cap")) or not _empty_cap(cell.get("runtime_caps")):
        issues.append((WORK_KIND_FRONTIER, f"{code}: truncated by sample/runtime cap"))
    if cell.get("official_source") is False:
        issues.append((WORK_KIND_JURISDICTION, f"{code}: secondary-only or unofficial source"))
    if cell.get("non_placeholder_full_text") is False:
        issues.append((WORK_KIND_JURISDICTION, f"{code}: placeholder or missing full text"))
    if _boolish(cell.get("production_upload")):
        issues.append((WORK_KIND_JURISDICTION, f"{code}: production_upload"))
    if _boolish(cell.get("partial_checkpoint_promoted")):
        issues.append((WORK_KIND_FRONTIER, f"{code}: partial checkpoint promoted"))
    if _boolish(cell.get("timeout_promoted_to_success")):
        issues.append((WORK_KIND_FRONTIER, f"{code}: timeout promoted to success"))
    if cell.get("complete") is False and not issues:
        issues.append((WORK_KIND_JURISDICTION, f"{code}: incomplete receipt"))
    return issues


def _jurisdictions_for_finding(
    finding: str,
    coverage: Mapping[str, Any],
    canonical: Sequence[str],
) -> List[str]:
    match = FINDING_CODE_RE.match(finding.strip())
    if match:
        return [match.group(1)]
    cohort_match = FINDING_COHORT_RE.match(finding.strip())
    if cohort_match:
        states = _cohort_states(coverage, cohort_match.group(1).upper())
        return states or list(canonical)
    extras = [
        str(code).strip().upper()
        for code in (coverage.get("extra_jurisdictions") or [])
        if str(code).strip()
    ]
    missing = [
        str(code).strip().upper()
        for code in (coverage.get("missing_jurisdictions") or [])
        if str(code).strip()
    ]
    if extras or missing:
        return missing + extras
    return list(canonical)


def classify_gaps(
    coverage: Mapping[str, Any],
    *,
    coverage_mod: Any | None = None,
) -> List[Dict[str, Any]]:
    """Turn coverage findings and incomplete cells into typed remaining gaps."""
    mod = coverage_mod or _load_coverage_module()
    canonical = _canonical_codes(coverage, mod)
    matrix = _matrix_of(coverage)
    gaps: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_gap(
        *,
        kind: str,
        jurisdiction: str,
        finding: str,
        cohort: str | None = None,
    ) -> None:
        code = str(jurisdiction or "").strip().upper()
        work_kind = kind if kind in WORK_KINDS else WORK_KIND_JURISDICTION
        key = (work_kind, code, finding)
        if key in seen:
            return
        seen.add(key)
        cell = matrix.get(code) or {}
        gaps.append(
            {
                "kind": work_kind,
                "jurisdiction": code or None,
                "cohort": cohort or str(cell.get("cohort") or "") or None,
                "finding": finding,
                "receipt": str(cell.get("receipt") or "") or None,
                "content_digest": str(cell.get("content_digest") or "") or None,
            }
        )

    findings = coverage.get("findings") or []
    if not isinstance(findings, Sequence) or isinstance(findings, (str, bytes)):
        findings = [f"coverage: findings is not a list"]
    for raw in findings:
        finding = str(raw).strip()
        if not finding:
            continue
        kind = classify_kind(finding)
        codes = _jurisdictions_for_finding(finding, coverage, canonical)
        if not codes:
            add_gap(kind=kind, jurisdiction="", finding=finding)
            continue
        for code in codes:
            add_gap(kind=kind, jurisdiction=code, finding=finding)

    for code in canonical:
        cell = matrix.get(code)
        if cell is None:
            add_gap(
                kind=WORK_KIND_JURISDICTION,
                jurisdiction=code,
                finding=f"{code}: missing from coverage matrix",
            )
            continue
        for kind, message in _cell_issue_messages(code, cell):
            add_gap(kind=kind, jurisdiction=code, finding=message)

    extras = coverage.get("extra_jurisdictions") or []
    if isinstance(extras, Sequence) and not isinstance(extras, (str, bytes)):
        for raw in extras:
            code = str(raw).strip().upper()
            if code:
                add_gap(
                    kind=WORK_KIND_JURISDICTION,
                    jurisdiction=code,
                    finding=f"{code}: extra jurisdiction not in sealed 51-set",
                )

    duplicates = coverage.get("duplicate_jurisdictions") or []
    if isinstance(duplicates, Sequence) and not isinstance(duplicates, (str, bytes)):
        for raw in duplicates:
            code = str(raw).strip().upper()
            if code:
                add_gap(
                    kind=WORK_KIND_JURISDICTION,
                    jurisdiction=code,
                    finding=f"{code}: duplicate across cohorts",
                )

    if str(coverage.get("status") or "").strip().lower() not in {"pass", "success", ""}:
        if not gaps:
            add_gap(
                kind=WORK_KIND_JURISDICTION,
                jurisdiction="",
                finding=f"coverage status={coverage.get('status')!r} is not pass",
            )

    return gaps


def code_families_for(
    jurisdiction: str,
    catalog: Any,
) -> List[str]:
    code = str(jurisdiction or "").strip().upper()
    if not code:
        return []
    try:
        record = catalog.get(code)
    except Exception:
        return []
    return [family.code_family_id for family in record.code_families]


def map_gaps_to_work(
    gaps: Sequence[Mapping[str, Any]],
    *,
    catalog: Any,
    coverage: Mapping[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """Map each remaining gap onto jurisdiction/code-family/frontier child work."""
    work: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for gap in gaps:
        kind = str(gap.get("kind") or WORK_KIND_JURISDICTION)
        if kind not in WORK_KINDS:
            kind = WORK_KIND_JURISDICTION
        code = str(gap.get("jurisdiction") or "").strip().upper()
        families = code_families_for(code, catalog) if code else []
        if not families:
            families = [""]
        for family in families:
            key = (kind, code, family)
            existing = next(
                (
                    item
                    for item in work
                    if (item["kind"], item.get("jurisdiction") or "", item.get("code_family_id") or "")
                    == key
                ),
                None,
            )
            finding = str(gap.get("finding") or "")
            if existing is not None:
                if finding and finding not in existing["source_findings"]:
                    existing["source_findings"].append(finding)
                continue
            if key in seen:
                continue
            seen.add(key)
            work_id_parts = ["LCR-023", kind]
            if code:
                work_id_parts.append(code)
            if family:
                work_id_parts.append(family)
            work.append(
                {
                    "work_id": "-".join(work_id_parts),
                    "kind": kind,
                    "jurisdiction": code or None,
                    "code_family_id": family or None,
                    "cohort": gap.get("cohort"),
                    "source_findings": [finding] if finding else [],
                    "replacement_receipt_required": True,
                    "status": "ready",
                    "blocks_downstream_admission": True,
                }
            )
    work.sort(
        key=lambda item: (
            WORK_KINDS.index(item["kind"]) if item["kind"] in WORK_KINDS else 99,
            item.get("jurisdiction") or "",
            item.get("code_family_id") or "",
        )
    )
    return work


def _passing_cell(cell: Mapping[str, Any]) -> bool:
    return (
        str(cell.get("status") or "").strip().lower() in {"success", "pass"}
        and cell.get("complete") is True
        and _as_int(cell.get("failed_final")) == 0
        and cell.get("frontier_closed") is True
        and cell.get("official_source") is True
        and cell.get("non_placeholder_full_text") is True
        and not list(cell.get("stale_keys") or [])
        and cell.get("index_parity_ok") is not False
        and _empty_cap(cell.get("sample_cap"))
        and _empty_cap(cell.get("runtime_caps"))
        and not _boolish(cell.get("production_upload"))
        and not _boolish(cell.get("partial_checkpoint_promoted"))
        and not _boolish(cell.get("timeout_promoted_to_success"))
    )


def _passing_receipts(
    coverage: Mapping[str, Any],
    *,
    catalog: Any,
    canonical: Sequence[str],
) -> List[Dict[str, Any]]:
    matrix = _matrix_of(coverage)
    rows: List[Dict[str, Any]] = []
    for code in canonical:
        cell = matrix.get(code)
        if cell is None or not _passing_cell(cell):
            continue
        families = code_families_for(code, catalog)
        rows.append(
            {
                "jurisdiction": code,
                "cohort": str(cell.get("cohort") or "") or None,
                "cohort_task_id": cell.get("cohort_task_id"),
                "receipt": str(cell.get("receipt") or "") or None,
                "content_digest": str(cell.get("content_digest") or "") or None,
                "code_family_ids": families,
                "status": str(cell.get("status") or "success"),
                "complete": True,
            }
        )
    return rows


def collect_input_content_ids(
    coverage: Mapping[str, Any],
    *,
    coverage_path: Path | None,
    receipt_dir: Path | None,
    receipts: Optional[Mapping[str, Mapping[str, Any]]] = None,
    catalog_path: Path | None,
    catalog_payload: Mapping[str, Any] | None,
    repo_root: Path,
    coverage_mod: Any,
) -> Dict[str, Any]:
    inputs: Dict[str, Any] = {}
    coverage_record = {
        "label": "coverage_matrix",
        "task_id": coverage.get("task_id") or "LCR-022",
        "schema": coverage.get("schema"),
        "content_id": sha256_file(coverage_path)
        if coverage_path is not None and coverage_path.is_file()
        else sha256_json(coverage),
        "path": _safe_relpath(coverage_path, repo_root) if coverage_path is not None else DEFAULT_COVERAGE_RELPATH.as_posix(),
        "source": "file"
        if coverage_path is not None and coverage_path.is_file()
        else "object",
    }
    inputs["coverage_matrix"] = coverage_record

    catalog_record = {
        "label": "official_source_catalog",
        "task_id": "LCR-002",
        "path": DEFAULT_CATALOG_RELPATH.as_posix(),
        "content_id": sha256_file(catalog_path)
        if catalog_path is not None and catalog_path.is_file()
        else sha256_json(catalog_payload if catalog_payload is not None else {}),
        "source": "file"
        if catalog_path is not None and catalog_path.is_file()
        else "object",
    }
    if catalog_path is not None:
        catalog_record["path"] = _safe_relpath(catalog_path, repo_root)
    inputs["official_source_catalog"] = catalog_record

    cohort_records: List[Dict[str, Any]] = []
    summaries = coverage.get("cohort_receipts") if isinstance(coverage.get("cohort_receipts"), list) else []
    summary_by_letter = {
        str(item.get("cohort") or "").strip().upper(): item
        for item in summaries
        if isinstance(item, Mapping)
    }
    for letter in COHORT_LETTERS:
        payload = None
        if receipts is not None:
            payload = receipts.get(letter) or receipts.get(letter.lower())
        path: Path | None = None
        declared = None
        summary = summary_by_letter.get(letter)
        if isinstance(summary, Mapping):
            declared = summary.get("path")
        if receipt_dir is not None:
            path = coverage_mod.cohort_receipt_path(Path(receipt_dir), letter)
        elif declared:
            candidate = Path(str(declared))
            path = candidate if candidate.is_absolute() else (repo_root / candidate)
            if path.is_symlink() or not path.is_file():
                path = None
        if path is None and receipts is None:
            path = coverage_mod.cohort_receipt_path(default_receipt_dir(repo_root), letter)
        if path is None and payload is None:
            raise AcquisitionGapRefillError(
                f"cohort {letter}: receipt missing for content-id (input of record requires all 13)"
            )
        if path is not None and path.is_file() and not path.is_symlink():
            content_id = sha256_file(path)
            rel = _safe_relpath(path, repo_root)
            source = "file"
        else:
            content_id = sha256_json(dict(payload or {}))
            rel = f"cohort_{letter.lower()}.json"
            source = "object"
        record = {
            "cohort": letter,
            "path": rel,
            "content_id": content_id,
            "source": source,
            "task_id": (summary or {}).get("task_id") if isinstance(summary, Mapping) else None,
        }
        if HOME_PATH_RE.search(rel):
            raise AcquisitionGapRefillError(
                f"cohort {letter}: receipt path contains /home/"
            )
        cohort_records.append(record)
    inputs["cohort_receipts"] = cohort_records
    return inputs


def build_acceptance_report(
    coverage: Mapping[str, Any],
    *,
    coverage_path: Path | str | None = None,
    receipt_dir: Path | str | None = None,
    receipts: Optional[Mapping[str, Mapping[str, Any]]] = None,
    catalog: Any | None = None,
    catalog_path: Path | str | None = None,
    repo_root: Path | str | None = None,
    coverage_mod: Any | None = None,
    ready_work: Optional[Sequence[Mapping[str, Any]]] = None,
    gaps: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build the LCR-023 acceptance report from the LCR-022 coverage matrix."""
    root = repository_root(repo_root)
    mod = coverage_mod or _load_coverage_module()
    coverage_obj = copy.deepcopy(dict(coverage))
    cov_path = Path(coverage_path).expanduser().resolve() if coverage_path is not None else None
    rec_dir = Path(receipt_dir).expanduser().resolve() if receipt_dir is not None else None
    cat_path = (
        Path(catalog_path).expanduser().resolve()
        if catalog_path is not None
        else default_catalog_path(root)
    )
    if catalog is None:
        catalog = (
            load_official_source_catalog(cat_path)
            if cat_path.is_file()
            else get_official_source_catalog()
        )

    classified = list(gaps) if gaps is not None else classify_gaps(coverage_obj, coverage_mod=mod)
    mapped = (
        [dict(item) for item in ready_work]
        if ready_work is not None
        else map_gaps_to_work(classified, catalog=catalog, coverage=coverage_obj)
    )

    if classified and not mapped:
        raise AcquisitionGapRefillError(
            "absence of ready work with remaining gaps is an error"
        )

    canonical = _canonical_codes(coverage_obj, mod)
    passing = _passing_receipts(coverage_obj, catalog=catalog, canonical=canonical)
    unresolved = [str(item) for item in (coverage_obj.get("findings") or []) if str(item).strip()]
    for gap in classified:
        finding = str(gap.get("finding") or "").strip()
        if finding:
            _append_unique(unresolved, finding)

    input_ids = collect_input_content_ids(
        coverage_obj,
        coverage_path=cov_path,
        receipt_dir=rec_dir,
        receipts=receipts,
        catalog_path=cat_path if cat_path.is_file() else None,
        catalog_payload=catalog.to_dict() if hasattr(catalog, "to_dict") else None,
        repo_root=root,
        coverage_mod=mod,
    )

    exact_51 = (
        len(canonical) == EXPECTED_JURISDICTION_COUNT
        and "DC" in canonical
        and len(passing) == EXPECTED_JURISDICTION_COUNT
        and not classified
        and not mapped
    )
    zero_findings = not unresolved and not classified
    status = "pass" if exact_51 and zero_findings and not mapped else "fail"

    sensitive = scan_sensitive_material(coverage_obj, label="coverage")
    sensitive.extend(scan_sensitive_material(input_ids, label="inputs"))
    sensitive.extend(scan_sensitive_material(passing, label="passing_receipts"))
    sensitive.extend(scan_sensitive_material(mapped, label="ready_work"))
    if sensitive:
        raise AcquisitionGapRefillError(
            "acceptance inputs contain /home/ paths or token material: "
            + "; ".join(sensitive)
        )

    report = {
        "schema": REPORT_SCHEMA,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "status": status,
        "required_jurisdictions": EXPECTED_JURISDICTION_COUNT,
        "observed_jurisdiction_count": len(_matrix_of(coverage_obj)),
        "includes_dc": any(row["jurisdiction"] == "DC" for row in passing)
        or "DC" in _matrix_of(coverage_obj),
        "passing_receipt_count": len(passing),
        "passing_current_receipts": passing,
        "unresolved_findings": unresolved if classified else [],
        "remaining_gaps": classified,
        "remaining_gap_count": len(classified),
        "ready_work": mapped,
        "ready_work_count": len(mapped),
        "downstream_admission_blocked": bool(classified) or bool(mapped) or status != "pass",
        "inputs": input_ids,
        "acceptance": {
            "exact_51_passing_receipts": len(passing) == EXPECTED_JURISDICTION_COUNT
            and exact_51,
            "zero_unresolved_findings": not unresolved if not classified else False,
            "zero_remaining_gaps": not classified,
            "no_ready_work_required": not mapped,
            "inputs_content_addressed": True,
            "includes_dc": any(row["jurisdiction"] == "DC" for row in passing),
            "no_absolute_home_paths": True,
            "no_token_material": True,
            "no_hub_upload": True,
            "cohort_receipts_read_only": True,
        },
    }
    if classified and not mapped:
        raise AcquisitionGapRefillError(
            "absence of ready work with remaining gaps is an error"
        )
    serialized = json.dumps(report, default=str)
    if HOME_PATH_RE.search(serialized) or HF_TOKEN_RE.search(serialized) or BEARER_RE.search(serialized):
        raise AcquisitionGapRefillError(
            "refusing to emit acceptance report that contains /home/ paths or tokens"
        )
    return report


def check_acceptance_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Fail closed unless the report is exact-51 success with zero remaining gaps."""
    mismatches: List[str] = []
    remaining = list(report.get("remaining_gaps") or [])
    ready = list(report.get("ready_work") or [])
    if remaining and not ready:
        raise AcquisitionGapRefillError(
            "absence of ready work with remaining gaps is an error"
        )
    if report.get("schema") != REPORT_SCHEMA:
        mismatches.append(f"schema={report.get('schema')!r}")
    if report.get("task_id") != TASK_ID:
        mismatches.append(f"task_id={report.get('task_id')!r}")
    if report.get("status") != "pass":
        mismatches.append(f"status={report.get('status')!r}")
    passing = report.get("passing_current_receipts") or []
    if not isinstance(passing, Sequence) or isinstance(passing, (str, bytes)):
        mismatches.append("passing_current_receipts is not a list")
        passing = []
    if len(passing) != EXPECTED_JURISDICTION_COUNT:
        mismatches.append(
            f"passing_current_receipts={len(passing)} != {EXPECTED_JURISDICTION_COUNT}"
        )
    if int(report.get("passing_receipt_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        mismatches.append("passing_receipt_count != 51")
    codes = [
        str(item.get("jurisdiction") or "").strip().upper()
        for item in passing
        if isinstance(item, Mapping)
    ]
    if len(set(codes)) != EXPECTED_JURISDICTION_COUNT or "DC" not in codes:
        mismatches.append("passing receipts are not the exact 51-set including DC")
    unresolved = report.get("unresolved_findings") or []
    if unresolved:
        mismatches.append(f"unresolved_findings={unresolved}")
    if remaining:
        mismatches.append(f"remaining_gaps={len(remaining)}")
    if ready:
        mismatches.append(f"ready_work={len(ready)}")
    if report.get("downstream_admission_blocked") is True:
        mismatches.append("downstream_admission_blocked")
    acceptance = report.get("acceptance") if isinstance(report.get("acceptance"), Mapping) else {}
    for key, value in (acceptance or {}).items():
        if value is not True:
            mismatches.append(f"acceptance.{key}={value!r}")
    inputs = report.get("inputs") if isinstance(report.get("inputs"), Mapping) else {}
    coverage_id = ((inputs or {}).get("coverage_matrix") or {}).get("content_id")
    catalog_id = ((inputs or {}).get("official_source_catalog") or {}).get("content_id")
    cohort_ids = (inputs or {}).get("cohort_receipts") or []
    if not coverage_id or not str(coverage_id).startswith("sha256:"):
        mismatches.append("coverage_matrix content_id missing")
    if not catalog_id or not str(catalog_id).startswith("sha256:"):
        mismatches.append("catalog content_id missing")
    if not isinstance(cohort_ids, Sequence) or len(cohort_ids) != len(COHORT_LETTERS):
        mismatches.append("cohort receipt content IDs are not all 13 letters")
    serialized = json.dumps(dict(report), default=str)
    if HOME_PATH_RE.search(serialized):
        mismatches.append("absolute /home/ path in acceptance report")
    if HF_TOKEN_RE.search(serialized) or BEARER_RE.search(serialized):
        mismatches.append("token material in acceptance report")
    if mismatches:
        raise AcquisitionGapRefillError(
            "full scrape acceptance check failed: " + "; ".join(mismatches)
        )
    return {
        "ok": True,
        "task_id": TASK_ID,
        "passing_receipt_count": EXPECTED_JURISDICTION_COUNT,
        "includes_dc": True,
        "remaining_gap_count": 0,
        "ready_work_count": 0,
        "mismatches": [],
    }


def write_acceptance_report(report: Mapping[str, Any], path: Path | str) -> Path:
    report_path = Path(path).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(report), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if HOME_PATH_RE.search(text) or HF_TOKEN_RE.search(text) or BEARER_RE.search(text):
        raise AcquisitionGapRefillError(
            "refusing to write acceptance report that contains /home/ paths or tokens"
        )
    report_path.write_text(text, encoding="utf-8")
    return report_path


def load_acceptance_report(path: Path | str) -> Dict[str, Any]:
    report_path = Path(path).expanduser().resolve()
    if not report_path.is_file() or report_path.is_symlink():
        raise AcquisitionGapRefillError(
            f"acceptance report must be a regular file: {report_path}"
        )
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AcquisitionGapRefillError(
            f"cannot read acceptance report {report_path}: {exc}"
        ) from exc
    if not isinstance(payload, MutableMapping):
        raise AcquisitionGapRefillError("acceptance report must be a JSON object")
    return dict(payload)


def acceptance_projection(report: Mapping[str, Any]) -> Dict[str, Any]:
    acceptance = report.get("acceptance")
    if not isinstance(acceptance, Mapping):
        return {}
    return {key: acceptance[key] for key in sorted(acceptance)}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Classify every LCR-022 coverage gap into jurisdiction/code-family/"
            "frontier child work and emit the full-scrape acceptance report "
            "(LCR-023). Offline; no Hub upload. Cohort receipts are read-only."
        )
    )
    parser.add_argument(
        "--coverage",
        type=Path,
        default=None,
        help=f"LCR-022 coverage matrix (default: {DEFAULT_COVERAGE_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--receipt-dir",
        default="",
        help=(
            "Read-only directory of cohort_*.json receipts "
            f"(default: {DEFAULT_RECEIPT_DIR.as_posix()})"
        ),
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help=f"Official source catalog (default: {DEFAULT_CATALOG_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=f"Acceptance report path (default: {DEFAULT_REPORT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero unless 51 passing receipts, zero gaps, and zero ready work.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the acceptance report to --report.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full JSON report")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    root = repository_root()
    coverage_path = (
        Path(args.coverage).expanduser().resolve()
        if args.coverage is not None
        else default_coverage_path(root)
    )
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_report_path(root)
    )
    receipt_dir = (
        Path(args.receipt_dir).expanduser().resolve()
        if str(args.receipt_dir or "").strip()
        else default_receipt_dir(root)
    )
    catalog_path = (
        Path(args.catalog).expanduser().resolve()
        if args.catalog is not None
        else default_catalog_path(root)
    )
    try:
        if not coverage_path.is_file() or coverage_path.is_symlink():
            raise AcquisitionGapRefillError(
                f"coverage matrix must be a regular file: {coverage_path}"
            )
        coverage = load_coverage_matrix(coverage_path)
        report = build_acceptance_report(
            coverage,
            coverage_path=coverage_path,
            receipt_dir=receipt_dir,
            catalog_path=catalog_path,
            repo_root=root,
        )
        if args.write:
            write_acceptance_report(report, report_path)
            print(f"wrote acceptance report: {report_path}", file=sys.stderr)

        if args.check:
            if report.get("status") != "pass":
                print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
                print("RESULT: FAIL", file=sys.stderr)
                return 1
            check_acceptance_report(report)
            if report_path.is_file():
                on_disk = load_acceptance_report(report_path)
                check_acceptance_report(on_disk)
                if acceptance_projection(on_disk) != acceptance_projection(report):
                    raise AcquisitionGapRefillError(
                        "on-disk acceptance projection diverges from recomputed coverage"
                    )
                if int(on_disk.get("passing_receipt_count") or 0) != EXPECTED_JURISDICTION_COUNT:
                    raise AcquisitionGapRefillError(
                        "on-disk passing_receipt_count is not 51"
                    )
                if on_disk.get("remaining_gaps") or on_disk.get("unresolved_findings"):
                    raise AcquisitionGapRefillError(
                        "on-disk acceptance still has remaining gaps"
                    )
            elif args.write is False and report_path == default_report_path(root):
                raise AcquisitionGapRefillError(
                    f"acceptance report not found for --check: {report_path}"
                )
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
            else:
                print(f"status: {report.get('status')}")
                print(f"passing_receipts: {report.get('passing_receipt_count')}")
                print(f"includes_dc: {report.get('includes_dc')}")
                print(f"remaining_gaps: {report.get('remaining_gap_count')}")
                print(f"ready_work: {report.get('ready_work_count')}")
                print(f"unresolved_findings: {len(report.get('unresolved_findings') or [])}")
            print("RESULT: PASS")
            return 0

        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        else:
            print(f"status: {report.get('status')}")
            print(f"passing_receipts: {report.get('passing_receipt_count')}")
            print(f"includes_dc: {report.get('includes_dc')}")
            print(f"remaining_gaps: {report.get('remaining_gap_count')}")
            print(f"ready_work: {report.get('ready_work_count')}")
        return 0 if report.get("status") == "pass" else 1
    except AcquisitionGapRefillError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if args.check:
            print("RESULT: FAIL", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
