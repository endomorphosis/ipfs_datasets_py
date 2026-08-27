#!/usr/bin/env python3
"""Aggregate all cohort receipts into the exact 51-jurisdiction coverage matrix (LCR-022).

Read-only over committed cohort receipts. Never rewrites adapters, never
uploads to the Hub, and fails closed when the union is not the sealed
50-state-plus-DC set or any jurisdiction is missing, duplicated,
non-success, production-upload, or nonzero failed-final.

Offline usage::

    python scripts/ops/legal_data/certify_state_laws_full_scrape.py --require-jurisdictions 51 --check
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    canonical_jurisdiction_codes,
    evaluate_jurisdiction_receipt,
    has_explicit_official_source_authority,
    reconcile_disposition,
    source_authority_class,
)

TASK_ID = "LCR-022"
GOAL_ID = "LCR-G024"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "certify_state_laws_full_scrape.py"
REPORT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-full-scrape-coverage@1"
EXPECTED_JURISDICTION_COUNT = 51
LIVE_FULL_CORPUS_EVIDENCE_MODE = "live_full_corpus"
COHORT_LETTERS: tuple[str, ...] = tuple("ABCDEFGHIJKLM")
DEFAULT_RECEIPT_DIR = Path("docs/reports/legal_corpora_reindex")
DEFAULT_REPORT_RELPATH = Path("docs/reports/legal_corpora_reindex/full_scrape_coverage.json")

HF_TOKEN_RE = re.compile(r"hf_[A-Za-z0-9]{8,}")
BEARER_RE = re.compile(r"Bearer\s+\S+")
HOME_PATH_RE = re.compile(r"/home/")
API_KEY_ASSIGN_RE = re.compile(
    r"(api[_-]?key|hf_token|authorization)\s*[\"']?\s*[:=]\s*[\"']?(?!\[REDACTED\])[A-Za-z0-9_\-]{8,}",
    re.IGNORECASE,
)
SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")


class FullScrapeCertifyError(RuntimeError):
    """Raised when full-scrape aggregation cannot complete fail-closed."""


def _load_module(filename: str, module_name: str):
    path = Path(__file__).with_name(filename)
    if not path.is_file():
        raise FullScrapeCertifyError(f"required module missing: {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise FullScrapeCertifyError(f"unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_runner_module():
    return _load_module(
        "run_legal_corpora_reindex_cohort.py",
        "lcr022_run_legal_corpora_reindex_cohort",
    )


def _load_cohort_certifier():
    return _load_module(
        "certify_state_laws_cohort.py",
        "lcr022_certify_state_laws_cohort",
    )


def repository_root(repo_root: Path | str | None = None) -> Path:
    if repo_root is None:
        return REPOSITORY_ROOT
    return Path(repo_root).expanduser().resolve()


def default_receipt_dir(repo_root: Path | str | None = None) -> Path:
    return repository_root(repo_root) / DEFAULT_RECEIPT_DIR


def default_report_path(repo_root: Path | str | None = None) -> Path:
    return repository_root(repo_root) / DEFAULT_REPORT_RELPATH


def canonical_jurisdictions(runner: Any | None = None) -> tuple[str, ...]:
    """Return the sealed 51-code tuple (50 states then DC) from the cohort runner."""
    mod = runner or _load_runner_module()
    codes = tuple(str(code).upper() for code in mod.CANONICAL_JURISDICTIONS)
    if len(codes) != EXPECTED_JURISDICTION_COUNT:
        raise FullScrapeCertifyError(
            f"runner canonical set is {len(codes)} codes, expected {EXPECTED_JURISDICTION_COUNT}"
        )
    if len(set(codes)) != len(codes):
        raise FullScrapeCertifyError("runner canonical set contains duplicates")
    if "DC" not in codes:
        raise FullScrapeCertifyError("runner canonical set omits DC")
    completeness_codes = canonical_jurisdiction_codes()
    if set(codes) != set(completeness_codes):
        raise FullScrapeCertifyError(
            "runner CANONICAL_JURISDICTIONS diverges from completeness oracle"
        )
    return codes


def cohort_receipt_path(receipt_dir: Path, cohort: str) -> Optional[Path]:
    letter = str(cohort).strip().upper()
    lower = letter.lower()
    candidates = [
        receipt_dir / f"cohort_{lower}.json",
        receipt_dir / f"cohort-{letter}.json",
        receipt_dir / "receipts" / f"cohort-{letter}.json",
        receipt_dir / letter / f"cohort-{letter}.json",
    ]
    for path in candidates:
        if path.is_file() and not path.is_symlink():
            return path
    return None


def load_json_object(path: Path) -> Dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FullScrapeCertifyError(f"receipt must be a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FullScrapeCertifyError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise FullScrapeCertifyError(f"JSON root must be an object: {path}")
    return copy.deepcopy(payload)


def _safe_receipt_label(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def scan_sensitive_material(payload: Any, *, label: str) -> List[str]:
    """Fail closed on absolute home paths or token-like material in receipts."""
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


def _failed_final_value(entry: Mapping[str, Any]) -> Optional[int]:
    disposition = entry.get("disposition")
    candidates = [entry.get("failed_final")]
    if isinstance(disposition, Mapping):
        candidates.append(disposition.get("failed_final"))
    observed = [item for item in candidates if item is not None]
    if not observed:
        return None
    ints = [_as_int(item) for item in observed]
    if any(item is None for item in ints):
        return None
    return ints[0]


def _status_of(entry: Mapping[str, Any], runner: Any) -> str:
    return runner.promote_state_status(str(entry.get("status") or ""))


def _boolish(value: Any) -> bool:
    return bool(value) and value not in (0, "0", "false", "False")


def _jurisdiction_entries(
    receipt: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Prefer detailed jurisdiction_receipts; fall back to state_results."""
    detailed = receipt.get("jurisdiction_receipts")
    summary = receipt.get("state_results")
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(detailed, Mapping):
        for raw_code, entry in detailed.items():
            code = str(raw_code).strip().upper()
            if isinstance(entry, Mapping):
                out[code] = dict(entry)
    if isinstance(summary, Mapping):
        for raw_code, entry in summary.items():
            code = str(raw_code).strip().upper()
            if not isinstance(entry, Mapping):
                continue
            if code in out:
                for key, value in entry.items():
                    out[code].setdefault(key, value)
            else:
                out[code] = dict(entry)
    states = receipt.get("states")
    if isinstance(states, Sequence) and not isinstance(states, (str, bytes)):
        for raw in states:
            code = str(raw).strip().upper()
            out.setdefault(code, {})
    return out


def _append_finding(findings: List[str], message: str) -> None:
    if message not in findings:
        findings.append(message)


def _cell_from_entry(
    *,
    code: str,
    cohort: str,
    entry: Mapping[str, Any],
    runner: Any,
    findings: List[str],
) -> Dict[str, Any]:
    status = _status_of(entry, runner)
    if status != "success":
        _append_finding(findings, f"{code}: status={status} (not success)")

    failed_final = _failed_final_value(entry)
    if failed_final is None:
        _append_finding(findings, f"{code}: failed_final missing")
        failed_final_out = None
    else:
        failed_final_out = failed_final
        if failed_final != 0:
            _append_finding(findings, f"{code}: failed_final={failed_final}")

    if _boolish(entry.get("production_upload")):
        _append_finding(findings, f"{code}: production_upload")
    if _boolish(entry.get("partial_checkpoint_promoted")) or _boolish(
        (entry.get("checkpoint") or {}).get("promoted_success")
        if isinstance(entry.get("checkpoint"), Mapping)
        else False
    ):
        _append_finding(findings, f"{code}: partial checkpoint promoted")
    if _boolish(entry.get("timeout_promoted_to_success")):
        _append_finding(findings, f"{code}: timeout promoted to success")

    declared = str(entry.get("jurisdiction") or "").strip().upper()
    if declared and declared != code:
        _append_finding(
            findings, f"{code}: internally contradictory jurisdiction={declared}"
        )

    disposition = entry.get("disposition")
    discovered = fetched = excluded = quarantined = duplicates = None
    if isinstance(disposition, Mapping):
        ok, detail = reconcile_disposition(disposition)
        if not ok:
            _append_finding(findings, f"{code}: {detail}")
        discovered = _as_int(disposition.get("discovered"))
        fetched = _as_int(disposition.get("fetched"))
        excluded = _as_int(disposition.get("excluded"))
        quarantined = _as_int(disposition.get("quarantined"))
        duplicates = _as_int(disposition.get("duplicates"))
        disp_failed = _as_int(disposition.get("failed_final"))
        top_failed = _as_int(entry.get("failed_final"))
        if (
            disp_failed is not None
            and top_failed is not None
            and disp_failed != top_failed
        ):
            _append_finding(
                findings,
                f"{code}: internally contradictory failed_final "
                f"top={top_failed} disposition={disp_failed}",
            )
    elif entry:
        _append_finding(findings, f"{code}: disposition object missing")

    frontier = entry.get("frontier") if isinstance(entry.get("frontier"), Mapping) else {}
    frontier_closed = frontier.get("closed") is True or entry.get("frontier_closed") is True
    if entry and not frontier_closed:
        _append_finding(findings, f"{code}: open frontier")

    content = entry.get("content") if isinstance(entry.get("content"), Mapping) else {}
    non_placeholder = content.get("non_placeholder_full_text")
    if non_placeholder is False:
        _append_finding(findings, f"{code}: placeholder or missing full text")

    authority = source_authority_class(entry)
    explicit_official = has_explicit_official_source_authority(entry)
    if not explicit_official:
        _append_finding(
            findings,
            (
                f"{code}: secondary-only or unofficial source; explicit official "
                f"authority required (official_source={entry.get('official_source')!r}, "
                f"source_authority_class={authority or '<missing>'})"
            ),
        )

    index_keys = entry.get("index_keys") if isinstance(entry.get("index_keys"), Mapping) else {}
    stale_keys = list(index_keys.get("stale_keys") or [])
    if stale_keys or index_keys.get("parity_ok") is False:
        _append_finding(findings, f"{code}: stale or drifted index keys")

    sample_cap = entry.get("sample_cap")
    runtime_caps = entry.get("runtime_caps")
    if sample_cap not in (None, False, 0, "", [], {}) or runtime_caps not in (
        None,
        False,
        0,
        "",
        [],
        {},
    ):
        _append_finding(findings, f"{code}: truncated by sample/runtime cap")

    replay = entry.get("replay") if isinstance(entry.get("replay"), Mapping) else {}
    content_digest = str(
        content.get("content_digest") or entry.get("content_digest") or ""
    )
    replay_digest = str(replay.get("content_digest") or "")
    if content_digest and replay_digest and content_digest != replay_digest:
        _append_finding(findings, f"{code}: internally contradictory content digest")
    replay_closed = replay.get("closed")
    if replay and replay_closed is False:
        _append_finding(findings, f"{code}: replay not closed")

    row_count = _as_int(entry.get("row_count"))
    statutes_count = _as_int(entry.get("statutes_count"))
    if (
        row_count is not None
        and fetched is not None
        and row_count != fetched
        and row_count != statutes_count
    ):
        _append_finding(
            findings,
            f"{code}: internally contradictory row_count={row_count} fetched={fetched}",
        )

    evidence_mode = str(entry.get("evidence_mode") or "").strip().lower()
    source_artifact = (
        entry.get("source_artifact")
        if isinstance(entry.get("source_artifact"), Mapping)
        else {}
    )
    source_artifact_sha256 = str(source_artifact.get("sha256") or "").strip().lower()
    source_artifact_row_count = _as_int(source_artifact.get("row_count"))
    live_full_corpus_evidence = bool(
        evidence_mode == LIVE_FULL_CORPUS_EVIDENCE_MODE
        and SHA256_RE.fullmatch(source_artifact_sha256)
        and row_count is not None
        and row_count > 0
        and source_artifact_row_count == row_count
    )
    if evidence_mode != LIVE_FULL_CORPUS_EVIDENCE_MODE:
        _append_finding(
            findings,
            f"{code}: evidence_mode={evidence_mode or '<missing>'} is not live_full_corpus",
        )
    if not SHA256_RE.fullmatch(source_artifact_sha256):
        _append_finding(findings, f"{code}: source artifact SHA-256 binding missing")
    if row_count is None or row_count <= 0 or source_artifact_row_count != row_count:
        _append_finding(
            findings,
            (
                f"{code}: source artifact row-count binding mismatch "
                f"artifact={source_artifact_row_count!r} receipt={row_count!r}"
            ),
        )

    if isinstance(entry, Mapping) and (
        entry.get("jurisdiction") or entry.get("disposition") or entry.get("frontier")
    ):
        verdict = evaluate_jurisdiction_receipt(entry, case_id=f"jurisdiction-{code}")
        if not verdict.complete:
            for item in verdict.findings:
                _append_finding(findings, f"{code}: {item.kind.value}: {item.detail}")

    return {
        "jurisdiction": code,
        "cohort": cohort,
        "status": status,
        "complete": status == "success"
        and failed_final_out == 0
        and frontier_closed
        and not stale_keys
        and explicit_official
        and live_full_corpus_evidence,
        "failed_final": failed_final_out,
        "discovered": discovered,
        "fetched": fetched,
        "excluded": excluded,
        "quarantined": quarantined,
        "duplicates": duplicates,
        "row_count": row_count,
        "statutes_count": statutes_count,
        "frontier_closed": frontier_closed,
        "official_source": explicit_official,
        "source_authority_class": authority or None,
        "source_domain": str(entry.get("source_domain") or "") or None,
        "content_digest": content_digest or None,
        "non_placeholder_full_text": non_placeholder is True,
        "replay_closed": replay_closed is True if replay else entry.get("replay_closed") is True,
        "index_parity_ok": index_keys.get("parity_ok") is True,
        "stale_keys": stale_keys,
        "sample_cap": sample_cap,
        "runtime_caps": runtime_caps,
        "partial_checkpoint_promoted": _boolish(entry.get("partial_checkpoint_promoted")),
        "timeout_promoted_to_success": _boolish(entry.get("timeout_promoted_to_success")),
        "production_upload": _boolish(entry.get("production_upload")),
        "evidence_mode": evidence_mode or None,
        "source_artifact_sha256": source_artifact_sha256 or None,
        "source_artifact_row_count": source_artifact_row_count,
        "live_full_corpus_evidence": live_full_corpus_evidence,
    }


def _sum_optional(cells: Iterable[Mapping[str, Any]], field: str) -> int:
    total = 0
    for cell in cells:
        value = _as_int(cell.get(field))
        if value is not None:
            total += value
    return total


def aggregate_full_scrape(
    *,
    receipt_dir: Path | str | None = None,
    receipts: Optional[Mapping[str, Mapping[str, Any]]] = None,
    require_jurisdictions: int = EXPECTED_JURISDICTION_COUNT,
    repo_root: Path | str | None = None,
    runner: Any | None = None,
    certifier: Any | None = None,
) -> Dict[str, Any]:
    """Reconcile all thirteen cohort receipts into the exact-51 coverage matrix."""
    root = repository_root(repo_root)
    mod = runner or _load_runner_module()
    cert = certifier or _load_cohort_certifier()
    expected = list(canonical_jurisdictions(mod))
    findings: List[str] = []

    if require_jurisdictions != EXPECTED_JURISDICTION_COUNT:
        _append_finding(
            findings,
            (
                f"require-jurisdictions={require_jurisdictions} is not the sealed "
                f"exact-{EXPECTED_JURISDICTION_COUNT} set; downward redefinition is forbidden"
            ),
        )

    loaded: Dict[str, Dict[str, Any]] = {}
    receipt_labels: Dict[str, str] = {}
    if receipts is not None:
        for letter in COHORT_LETTERS:
            payload = receipts.get(letter) or receipts.get(letter.lower())
            if payload is None:
                _append_finding(findings, f"cohort {letter}: receipt missing")
                continue
            if not isinstance(payload, Mapping):
                _append_finding(findings, f"cohort {letter}: receipt root must be object")
                continue
            loaded[letter] = copy.deepcopy(dict(payload))
            receipt_labels[letter] = f"cohort_{letter.lower()}.json"
    else:
        directory = (
            Path(receipt_dir).expanduser().resolve()
            if receipt_dir is not None
            else default_receipt_dir(root)
        )
        if not directory.is_dir():
            raise FullScrapeCertifyError(f"receipt directory missing: {directory}")
        for letter in COHORT_LETTERS:
            path = cohort_receipt_path(directory, letter)
            if path is None:
                _append_finding(
                    findings, f"cohort {letter}: receipt missing under {directory.name}"
                )
                continue
            loaded[letter] = load_json_object(path)
            receipt_labels[letter] = _safe_receipt_label(path, root)

    owners: Dict[str, List[str]] = {}
    matrix: Dict[str, Dict[str, Any]] = {}
    cohort_summaries: List[Dict[str, Any]] = []
    production_upload = False
    shared_combined_write = False
    cohort_live_evidence: Dict[str, bool] = {}

    for letter in COHORT_LETTERS:
        payload = loaded.get(letter)
        if payload is None:
            cohort_summaries.append(
                {
                    "cohort": letter,
                    "status": "fail",
                    "path": receipt_labels.get(letter),
                    "states": list(mod.cohort_states(letter)),
                    "findings": [item for item in findings if f"cohort {letter}:" in item],
                }
            )
            continue

        for item in scan_sensitive_material(payload, label=f"cohort {letter}"):
            _append_finding(findings, item)

        if _boolish(payload.get("production_upload")):
            production_upload = True
            _append_finding(findings, f"cohort {letter}: production_upload")
        if _boolish(payload.get("shared_combined_write")):
            shared_combined_write = True
            _append_finding(findings, f"cohort {letter}: shared_combined_write")
        if str(payload.get("status") or "").strip().lower() not in {"success", "pass", ""}:
            _append_finding(
                findings,
                f"cohort {letter}: status={payload.get('status')} (not success)",
            )

        evidence_mode = str(payload.get("evidence_mode") or "").strip().lower()
        software_contract_only = payload.get("proves_software_contract_only")
        has_sample_counts = "statutes_sample_counts" in payload
        cohort_live_evidence[letter] = bool(
            evidence_mode == LIVE_FULL_CORPUS_EVIDENCE_MODE
            and software_contract_only is False
            and not has_sample_counts
        )
        if evidence_mode != LIVE_FULL_CORPUS_EVIDENCE_MODE:
            _append_finding(
                findings,
                (
                    f"cohort {letter}: evidence_mode={evidence_mode or '<missing>'} "
                    "is not live_full_corpus"
                ),
            )
        if software_contract_only is not False:
            _append_finding(
                findings,
                f"cohort {letter}: proves_software_contract_only must be explicitly false",
            )
        if has_sample_counts:
            _append_finding(
                findings,
                f"cohort {letter}: compact statutes_sample_counts receipt cannot certify a full corpus",
            )

        cert_result = cert.certify_cohort_receipt(payload, cohort=letter, runner=mod)
        for item in cert_result.get("findings") or []:
            _append_finding(findings, f"cohort {letter}: {item}")

        entries = _jurisdiction_entries(payload)
        observed_codes = sorted(entries)
        expected_codes = list(mod.cohort_states(letter))
        if set(observed_codes) != set(expected_codes):
            missing = sorted(set(expected_codes) - set(observed_codes))
            extra = sorted(set(observed_codes) - set(expected_codes))
            _append_finding(
                findings,
                f"cohort {letter}: jurisdiction set mismatch missing={missing} extra={extra}",
            )

        for code, entry in entries.items():
            owners.setdefault(code, []).append(letter)
            cell = _cell_from_entry(
                code=code,
                cohort=letter,
                entry=entry,
                runner=mod,
                findings=findings,
            )
            cell["cohort_task_id"] = payload.get("task_id")
            cell["receipt"] = receipt_labels.get(letter)
            matrix[code] = cell

        cohort_summaries.append(
            {
                "cohort": letter,
                "status": cert_result.get("status") or "fail",
                "path": receipt_labels.get(letter),
                "task_id": payload.get("task_id"),
                "states": expected_codes,
                "observed_states": observed_codes,
                "production_upload": _boolish(payload.get("production_upload")),
                "shared_combined_write": _boolish(payload.get("shared_combined_write")),
                "evidence_mode": evidence_mode or None,
                "proves_software_contract_only": software_contract_only,
                "live_full_corpus_evidence": cohort_live_evidence[letter],
            }
        )

    duplicate_codes = sorted(code for code, cohort_list in owners.items() if len(cohort_list) > 1)
    for code in duplicate_codes:
        _append_finding(
            findings,
            f"{code}: duplicate across cohorts {owners[code]}",
        )

    extras = sorted(code for code in matrix if code not in set(expected))
    missing = [code for code in expected if code not in matrix]
    for code in missing:
        _append_finding(findings, f"{code}: missing from cohort union")
    for code in extras:
        _append_finding(findings, f"{code}: extra jurisdiction not in sealed 51-set")
    if "DC" not in matrix:
        _append_finding(findings, "DC: missing from cohort union")

    observed_count = len(set(matrix))
    if observed_count != require_jurisdictions and require_jurisdictions == EXPECTED_JURISDICTION_COUNT:
        _append_finding(
            findings,
            (
                f"observed unique postal codes={observed_count} "
                f"!= required {require_jurisdictions}"
            ),
        )

    cells = [matrix[code] for code in expected if code in matrix]
    totals = {
        "discovered": _sum_optional(cells, "discovered"),
        "fetched": _sum_optional(cells, "fetched"),
        "excluded": _sum_optional(cells, "excluded"),
        "quarantined": _sum_optional(cells, "quarantined"),
        "failed_final": _sum_optional(cells, "failed_final"),
        "duplicates": _sum_optional(cells, "duplicates"),
        "row_count": _sum_optional(cells, "row_count"),
        "statutes_count": _sum_optional(cells, "statutes_count"),
        "success_count": sum(1 for cell in cells if cell.get("status") == "success"),
        "complete_count": sum(1 for cell in cells if cell.get("complete") is True),
    }

    exact_51 = (
        not missing
        and not extras
        and not duplicate_codes
        and observed_count == EXPECTED_JURISDICTION_COUNT
        and "DC" in matrix
        and require_jurisdictions == EXPECTED_JURISDICTION_COUNT
    )
    failed_final_zero = totals["failed_final"] == 0 and all(
        cell.get("failed_final") == 0 for cell in cells
    )
    all_success = bool(cells) and all(cell.get("status") == "success" for cell in cells) and not missing
    closed_frontier = bool(cells) and all(cell.get("frontier_closed") for cell in cells) and not missing
    official_only = bool(cells) and all(cell.get("official_source") for cell in cells) and not missing
    no_placeholder = bool(cells) and all(
        cell.get("non_placeholder_full_text") for cell in cells
    ) and not missing
    no_stale = bool(cells) and all(not cell.get("stale_keys") for cell in cells) and not missing
    no_truncation = bool(cells) and all(
        cell.get("sample_cap") in (None, False, 0, "", [], {})
        and cell.get("runtime_caps") in (None, False, 0, "", [], {})
        for cell in cells
    ) and not missing
    live_full_corpus_evidence = bool(cells) and all(
        cell.get("live_full_corpus_evidence") is True for cell in cells
    ) and all(cohort_live_evidence.get(letter) is True for letter in COHORT_LETTERS)
    no_home_or_tokens = not any(
        " /home/" in item or item.endswith("/home/ path") or "token" in item or "api_key" in item
        for item in findings
    )

    acceptance = {
        "exact_51": exact_51,
        "includes_dc": "DC" in matrix,
        "no_missing": not missing,
        "no_extra": not extras,
        "no_duplicates": not duplicate_codes,
        "failed_final_zero": failed_final_zero,
        "all_success": all_success,
        "no_production_upload": not production_upload,
        "no_shared_combined_write": not shared_combined_write,
        "closed_frontier": closed_frontier,
        "no_truncation": no_truncation,
        "no_stale_keys": no_stale,
        "official_source_only": official_only,
        "non_placeholder_full_text": no_placeholder,
        "live_full_corpus_evidence": live_full_corpus_evidence,
        "no_software_contract_receipts": all(
            cohort_live_evidence.get(letter) is True for letter in COHORT_LETTERS
        ),
        "disposition_reconciled": not any("discovered=" in item for item in findings),
        "no_absolute_home_paths": not any("/home/" in item for item in findings),
        "no_token_material": no_home_or_tokens
        and not any("token" in item or "api_key" in item or "Bearer" in item for item in findings),
    }
    status = "pass" if not findings and exact_51 and all(acceptance.values()) else "fail"
    return {
        "schema": REPORT_SCHEMA,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "status": status,
        "required_jurisdictions": require_jurisdictions,
        "expected_jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "observed_jurisdiction_count": observed_count,
        "includes_dc": "DC" in matrix,
        "canonical_jurisdictions": expected,
        "observed_jurisdictions": [code for code in expected if code in matrix] + extras,
        "missing_jurisdictions": missing,
        "extra_jurisdictions": extras,
        "duplicate_jurisdictions": duplicate_codes,
        "cohorts": list(COHORT_LETTERS),
        "cohort_receipts": cohort_summaries,
        "production_upload": production_upload,
        "shared_combined_write": shared_combined_write,
        "totals": totals,
        "acceptance": acceptance,
        "findings": findings,
        "matrix": {code: matrix[code] for code in expected if code in matrix},
        "jurisdictions": [matrix[code] for code in expected if code in matrix],
        "pass_count": totals["success_count"],
        "fail_count": EXPECTED_JURISDICTION_COUNT - totals["success_count"] if missing or not all_success else 0,
    }


def acceptance_projection(report: Mapping[str, Any]) -> Dict[str, Any]:
    acceptance = report.get("acceptance")
    if not isinstance(acceptance, Mapping):
        return {}
    return {key: acceptance[key] for key in sorted(acceptance)}


def check_coverage_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Fail closed unless the report is an exact-51 passing matrix."""
    mismatches: List[str] = []
    if report.get("schema") != REPORT_SCHEMA:
        mismatches.append(f"schema={report.get('schema')!r}")
    if report.get("task_id") != TASK_ID:
        mismatches.append(f"task_id={report.get('task_id')!r}")
    if report.get("status") != "pass":
        mismatches.append(f"status={report.get('status')!r}")
    codes = report.get("canonical_jurisdictions") or []
    if not isinstance(codes, Sequence) or set(codes) != set(canonical_jurisdiction_codes()):
        mismatches.append("canonical_jurisdictions is not the exact 51-set")
    if int(report.get("observed_jurisdiction_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        mismatches.append("observed_jurisdiction_count != 51")
    if report.get("includes_dc") is not True:
        mismatches.append("DC missing")
    if report.get("missing_jurisdictions"):
        mismatches.append(f"missing={report.get('missing_jurisdictions')}")
    if report.get("extra_jurisdictions"):
        mismatches.append(f"extra={report.get('extra_jurisdictions')}")
    if report.get("duplicate_jurisdictions"):
        mismatches.append(f"duplicates={report.get('duplicate_jurisdictions')}")
    if report.get("production_upload"):
        mismatches.append("production_upload")
    if report.get("findings"):
        mismatches.append(f"findings={report.get('findings')}")
    acceptance = report.get("acceptance") if isinstance(report.get("acceptance"), Mapping) else {}
    for key, value in (acceptance or {}).items():
        if value is not True:
            mismatches.append(f"acceptance.{key}={value!r}")
    if mismatches:
        raise FullScrapeCertifyError(
            "full scrape coverage check failed: " + "; ".join(mismatches)
        )
    return {
        "ok": True,
        "task_id": TASK_ID,
        "observed_jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "includes_dc": True,
        "mismatches": [],
        "acceptance": dict(acceptance),
    }


def write_coverage_report(report: Mapping[str, Any], path: Path | str) -> Path:
    report_path = Path(path).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(report), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if HOME_PATH_RE.search(text) or HF_TOKEN_RE.search(text) or BEARER_RE.search(text):
        raise FullScrapeCertifyError(
            "refusing to write coverage report that contains /home/ paths or tokens"
        )
    report_path.write_text(text, encoding="utf-8")
    return report_path


def load_coverage_report(path: Path | str) -> Dict[str, Any]:
    report_path = Path(path).expanduser().resolve()
    if not report_path.is_file() or report_path.is_symlink():
        raise FullScrapeCertifyError(f"coverage report must be a regular file: {report_path}")
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FullScrapeCertifyError(f"cannot read coverage report {report_path}: {exc}") from exc
    if not isinstance(payload, MutableMapping):
        raise FullScrapeCertifyError("coverage report must be a JSON object")
    return dict(payload)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate all state-law cohort receipts into the exact 51-jurisdiction "
            "coverage matrix (LCR-022). Offline; no Hub upload."
        )
    )
    parser.add_argument(
        "--require-jurisdictions",
        type=int,
        default=EXPECTED_JURISDICTION_COUNT,
        help="Required unique postal-code count (must be 51).",
    )
    parser.add_argument(
        "--receipt-dir",
        default="",
        help=(
            "Directory of cohort_*.json receipts "
            f"(default: {DEFAULT_RECEIPT_DIR.as_posix()})"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=f"Coverage matrix path (default: {DEFAULT_REPORT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero unless the exact 51-set passes against committed receipts.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the aggregated coverage matrix to --report.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full JSON report")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_report_path()
    )
    receipt_dir = (
        Path(args.receipt_dir).expanduser().resolve()
        if str(args.receipt_dir or "").strip()
        else default_receipt_dir()
    )
    try:
        report = aggregate_full_scrape(
            receipt_dir=receipt_dir,
            require_jurisdictions=int(args.require_jurisdictions),
        )
        if args.write:
            write_coverage_report(report, report_path)
            print(f"wrote coverage report: {report_path}", file=sys.stderr)

        if args.check:
            if report.get("status") != "pass":
                print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
                print("RESULT: FAIL", file=sys.stderr)
                return 1
            check_coverage_report(report)
            if report_path.is_file():
                on_disk = load_coverage_report(report_path)
                check_coverage_report(on_disk)
                if acceptance_projection(on_disk) != acceptance_projection(report):
                    raise FullScrapeCertifyError(
                        "on-disk coverage acceptance diverges from recomputed receipts"
                    )
                disk_codes = list(on_disk.get("canonical_jurisdictions") or [])
                live_codes = list(report.get("canonical_jurisdictions") or [])
                if disk_codes != live_codes:
                    raise FullScrapeCertifyError(
                        "on-disk canonical_jurisdictions diverge from recomputed receipts"
                    )
            elif args.write is False and report_path == default_report_path():
                raise FullScrapeCertifyError(
                    f"coverage report not found for --check: {report_path}"
                )
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
            else:
                print(f"status: {report.get('status')}")
                print(f"jurisdictions: {report.get('observed_jurisdiction_count')}")
                print(f"includes_dc: {report.get('includes_dc')}")
                print(f"findings: {len(report.get('findings') or [])}")
            print("RESULT: PASS")
            return 0

        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        else:
            print(f"status: {report.get('status')}")
            print(f"jurisdictions: {report.get('observed_jurisdiction_count')}")
            print(f"includes_dc: {report.get('includes_dc')}")
            print(f"findings: {len(report.get('findings') or [])}")
        return 0 if report.get("status") == "pass" else 1
    except FullScrapeCertifyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if args.check:
            print("RESULT: FAIL", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
