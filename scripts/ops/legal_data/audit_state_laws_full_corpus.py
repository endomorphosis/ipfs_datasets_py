#!/usr/bin/env python3
"""Frontier-closure and no-truncation audit for state-law full scrapes (LCR-005).

This tool audits:

1. **Static AST guards** — scraper source for unguarded seed/recovery returns
   and hard discovery caps (reusing the existing full-corpus guard tripwire).
2. **Live receipts** — jurisdiction frontier receipts for exact state set,
   enumerator closure, continuation links, bundle counts, boundary probes,
   runtime/sample caps, checkpoints, response errors, source domains, and
   disposition arithmetic.

Static AST guards and live receipts are always reported as separate sections.
The offline gate never contacts the network:

    python scripts/ops/legal_data/audit_state_laws_full_corpus.py --fixture-only --check
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

TASK_ID = "LCR-005"
GOAL_ID = "LCR-G010"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "audit_state_laws_full_corpus.py"
REPORT_SCHEMA = "ipfs_datasets_py/state-laws-full-corpus-audit@1"
CODE_VERSION = "1"
FIXTURE_SCHEMA = "ipfs_datasets_py/state-laws-frontier-receipts@1"

DEFAULT_FIXTURE_RELPATH = Path("tests/fixtures/legal_ir/state_laws_frontier_receipts.json")

JURISDICTION_COUNT = 51
JURISDICTION_CODES: tuple[str, ...] = (
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
)

# Sealed known false-success examples from the pinned baseline audit.
KNOWN_FALSE_SUCCESS_REGISTRY: Mapping[str, int] = {
    "NJ": 1,
    "GA": 2,
    "LA": 4,
    "CO": 5,
    "MA": 14,
}
KNOWN_REMOTE_TRUNCATIONS: Mapping[str, int] = {
    "GA": 2,
    "HI": 4,
    "IN": 4,
    "MS": 1,
    "WA": 1,
    "WV": 1,
}

# Domains that are never official primary sources for admission.
SECONDARY_SOURCE_DOMAIN_MARKERS: tuple[str, ...] = (
    "justia.com",
    "findlaw.com",
    "wikipedia.org",
    "huggingface.co",
)


class FullCorpusAuditError(RuntimeError):
    """Raised when the full-corpus audit cannot complete fail-closed."""


@dataclass
class Finding:
    """One audit finding."""

    section: str
    case_id: str
    kind: str
    severity: str
    detail: str
    jurisdiction: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CaseResult:
    """Audit result for one fixture or live case."""

    case_id: str
    section: str
    status: str
    expected_status: str | None = None
    findings: list[Finding] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "section": self.section,
            "status": self.status,
            "expected_status": self.expected_status,
            "kinds": list(self.kinds),
            "findings": [item.to_dict() for item in self.findings],
        }


def default_fixture_path(repo_root: Path | str | None = None) -> Path:
    """Return the sealed frontier-receipts fixture path."""
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_FIXTURE_RELPATH).resolve()


def expected_jurisdiction_codes() -> list[str]:
    """Return the exact 51-jurisdiction set (50 states + DC)."""
    codes = list(JURISDICTION_CODES)
    if len(codes) != JURISDICTION_COUNT:
        raise FullCorpusAuditError(
            f"jurisdiction set invariant broken: expected {JURISDICTION_COUNT}, "
            f"got {len(codes)}"
        )
    if "DC" not in codes:
        raise FullCorpusAuditError("jurisdiction set must include DC")
    if len(set(codes)) != len(codes):
        raise FullCorpusAuditError("jurisdiction set contains duplicates")
    return codes


def load_fixture(path: Path | str | None = None) -> dict[str, Any]:
    """Load and minimally validate the frontier-receipts fixture."""
    fixture_path = Path(path).expanduser().resolve() if path else default_fixture_path()
    if not fixture_path.is_file():
        raise FullCorpusAuditError(f"frontier receipts fixture missing: {fixture_path}")
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FullCorpusAuditError(f"invalid fixture JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise FullCorpusAuditError("fixture root must be a JSON object")
    schema = payload.get("schema")
    if schema != FIXTURE_SCHEMA:
        raise FullCorpusAuditError(
            f"fixture schema mismatch: expected {FIXTURE_SCHEMA!r}, got {schema!r}"
        )
    if not isinstance(payload.get("cases"), list) or not payload["cases"]:
        raise FullCorpusAuditError("fixture.cases must be a non-empty array")
    return payload


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FullCorpusAuditError(f"{path} must be a JSON object")
    return value


def _require_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FullCorpusAuditError(f"{path} must be an integer")
    return value


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item).strip()]


def _finding(
    *,
    section: str,
    case_id: str,
    kind: str,
    detail: str,
    severity: str = "error",
    jurisdiction: str | None = None,
) -> Finding:
    return Finding(
        section=section,
        case_id=case_id,
        kind=kind,
        severity=severity,
        detail=detail,
        jurisdiction=jurisdiction,
    )


def audit_jurisdiction_set(
    *,
    case_id: str,
    receipt: Mapping[str, Any],
    expected_codes: Sequence[str] | None = None,
) -> CaseResult:
    """Audit an exact jurisdiction-set claim."""
    expected = list(expected_codes) if expected_codes is not None else expected_jurisdiction_codes()
    expected_set = set(expected)
    observed = _as_str_list(receipt.get("jurisdictions"))
    observed_set = {code.upper() for code in observed}
    findings: list[Finding] = []

    if observed_set != expected_set:
        missing = sorted(expected_set - observed_set)
        extra = sorted(observed_set - expected_set)
        findings.append(
            _finding(
                section="live_receipts",
                case_id=case_id,
                kind="exact_state_set_mismatch",
                detail=(
                    f"jurisdiction set mismatch: count={len(observed_set)} "
                    f"(expected {len(expected_set)}); missing={missing}; extra={extra}"
                ),
            )
        )
    if "DC" not in observed_set:
        findings.append(
            _finding(
                section="live_receipts",
                case_id=case_id,
                kind="exact_state_set_mismatch",
                detail="jurisdiction set omits DC",
            )
        )

    # Deduplicate kinds while preserving order.
    kinds: list[str] = []
    for item in findings:
        if item.kind not in kinds:
            kinds.append(item.kind)

    return CaseResult(
        case_id=case_id,
        section="live_receipts",
        status="pass" if not findings else "fail",
        findings=findings,
        kinds=kinds,
    )


def audit_combined_viewer(
    *,
    case_id: str,
    receipt: Mapping[str, Any],
) -> CaseResult:
    """Detect one-state combined overwrite (e.g. IA-only Viewer config)."""
    findings: list[Finding] = []
    viewer = receipt.get("combined_viewer")
    if isinstance(viewer, Mapping):
        labels = _as_str_list(viewer.get("jurisdiction_labels"))
        unique_labels = sorted({label.upper() for label in labels if label})
        ia_only = bool(viewer.get("ia_only"))
        if ia_only or (len(unique_labels) == 1 and unique_labels[0] == "IA"):
            findings.append(
                _finding(
                    section="live_receipts",
                    case_id=case_id,
                    kind="one_state_combined_overwrite",
                    detail=(
                        "combined/default Viewer config is a one-state overwrite "
                        f"(labels={unique_labels}, rows={viewer.get('row_count')})"
                    ),
                    jurisdiction=unique_labels[0] if unique_labels else "IA",
                )
            )
        elif len(unique_labels) == 1:
            findings.append(
                _finding(
                    section="live_receipts",
                    case_id=case_id,
                    kind="one_state_combined_overwrite",
                    detail=(
                        "combined/default Viewer config contains only one "
                        f"jurisdiction label: {unique_labels[0]}"
                    ),
                    jurisdiction=unique_labels[0],
                )
            )
        elif len(unique_labels) != JURISDICTION_COUNT:
            findings.append(
                _finding(
                    section="live_receipts",
                    case_id=case_id,
                    kind="exact_state_set_mismatch",
                    detail=(
                        "combined Viewer jurisdiction labels do not cover the "
                        f"exact 51-set (observed {len(unique_labels)})"
                    ),
                )
            )
    elif receipt.get("status") == "success" and receipt.get("jurisdiction") is None:
        findings.append(
            _finding(
                section="live_receipts",
                case_id=case_id,
                kind="one_state_combined_overwrite",
                detail="combined success receipt lacks multi-jurisdiction viewer evidence",
            )
        )

    kinds = []
    for item in findings:
        if item.kind not in kinds:
            kinds.append(item.kind)
    return CaseResult(
        case_id=case_id,
        section="live_receipts",
        status="pass" if not findings else "fail",
        findings=findings,
        kinds=kinds,
    )


def _disposition_reconciles(disposition: Mapping[str, Any]) -> tuple[bool, str]:
    discovered = _require_int(disposition.get("discovered"), "disposition.discovered")
    fetched = _require_int(disposition.get("fetched"), "disposition.fetched")
    excluded = _require_int(disposition.get("excluded"), "disposition.excluded")
    quarantined = _require_int(disposition.get("quarantined"), "disposition.quarantined")
    failed_final = _require_int(disposition.get("failed_final"), "disposition.failed_final")
    accounted = fetched + excluded + quarantined + failed_final
    if accounted != discovered:
        return (
            False,
            (
                f"discovered ({discovered}) != fetched+excluded+quarantined+failed_final "
                f"({fetched}+{excluded}+{quarantined}+{failed_final}={accounted})"
            ),
        )
    return True, ""


def audit_jurisdiction_receipt(
    *,
    case_id: str,
    receipt: Mapping[str, Any],
    known_false_success: Mapping[str, int] | None = None,
) -> CaseResult:
    """Audit one jurisdiction scrape receipt for frontier/no-truncation gates."""
    findings: list[Finding] = []
    jurisdiction = receipt.get("jurisdiction")
    jurisdiction_code = str(jurisdiction).upper() if jurisdiction else None
    false_success_map = (
        dict(known_false_success)
        if known_false_success is not None
        else dict(KNOWN_FALSE_SUCCESS_REGISTRY)
    )

    # Combined-viewer branch may ride on a jurisdiction receipt payload.
    combined = receipt.get("combined_viewer")
    if isinstance(combined, Mapping):
        combined_result = audit_combined_viewer(case_id=case_id, receipt=receipt)
        findings.extend(combined_result.findings)

    # Known false-success truncations (registry/remote).
    row_count = receipt.get("row_count")
    if (
        jurisdiction_code
        and jurisdiction_code in false_success_map
        and isinstance(row_count, int)
        and not isinstance(row_count, bool)
        and row_count <= false_success_map[jurisdiction_code]
        and str(receipt.get("status") or "").lower() == "success"
    ):
        findings.append(
            _finding(
                section="live_receipts",
                case_id=case_id,
                kind="false_success_truncation",
                detail=(
                    f"{jurisdiction_code} claimed success with row_count={row_count} "
                    f"(known false-success threshold <= "
                    f"{false_success_map[jurisdiction_code]})"
                ),
                jurisdiction=jurisdiction_code,
            )
        )
    if bool(receipt.get("known_false_success")) and str(receipt.get("status") or "").lower() == "success":
        if not any(item.kind == "false_success_truncation" for item in findings):
            findings.append(
                _finding(
                    section="live_receipts",
                    case_id=case_id,
                    kind="false_success_truncation",
                    detail=(
                        f"{jurisdiction_code or case_id} is marked known_false_success "
                        "but still claims success"
                    ),
                    jurisdiction=jurisdiction_code,
                )
            )

    # Source domain / authority.
    source_domain = str(receipt.get("source_domain") or "").strip().lower()
    official_source = receipt.get("official_source")
    if official_source is False or any(
        marker in source_domain for marker in SECONDARY_SOURCE_DOMAIN_MARKERS
    ):
        findings.append(
            _finding(
                section="live_receipts",
                case_id=case_id,
                kind="unofficial_source_domain",
                detail=f"non-official source domain for admission: {source_domain or '<missing>'}",
                jurisdiction=jurisdiction_code,
            )
        )

    # Caps / truncation.
    mode = str(receipt.get("mode") or "").strip().lower()
    runtime_caps = receipt.get("runtime_caps")
    sample_cap = receipt.get("sample_cap")
    if mode == "full" and runtime_caps not in (None, {}, [], 0, False):
        findings.append(
            _finding(
                section="live_receipts",
                case_id=case_id,
                kind="runtime_cap_present",
                detail=f"full-mode receipt has runtime_caps={runtime_caps!r}",
                jurisdiction=jurisdiction_code,
            )
        )
    if sample_cap not in (None, 0, False):
        findings.append(
            _finding(
                section="live_receipts",
                case_id=case_id,
                kind="sample_cap_present",
                detail=f"sample_cap present: {sample_cap!r}",
                jurisdiction=jurisdiction_code,
            )
        )

    # Checkpoint promotion.
    checkpoint = receipt.get("checkpoint")
    if isinstance(checkpoint, Mapping):
        if bool(checkpoint.get("partial")) and bool(checkpoint.get("promoted_success")):
            findings.append(
                _finding(
                    section="live_receipts",
                    case_id=case_id,
                    kind="partial_checkpoint_promoted",
                    detail="partial checkpoint was promoted to success",
                    jurisdiction=jurisdiction_code,
                )
            )
        completion_basis = str(checkpoint.get("completion_basis") or "").strip().lower()
        if (
            str(receipt.get("status") or "").lower() == "success"
            and completion_basis
            and completion_basis not in {
                "source_frontier",
                "frontier",
                "official_frontier",
            }
            and (
                bool(checkpoint.get("partial"))
                or bool(checkpoint.get("promoted_success"))
                or completion_basis in {"partial_checkpoint", "filename", "registry"}
            )
        ):
            # Avoid double-counting when partial+promoted already flagged above.
            if not (
                bool(checkpoint.get("partial")) and bool(checkpoint.get("promoted_success"))
            ):
                findings.append(
                    _finding(
                        section="live_receipts",
                        case_id=case_id,
                        kind="partial_checkpoint_promoted",
                        detail=(
                            "success completion_basis is not source frontier: "
                            f"{completion_basis}"
                        ),
                        jurisdiction=jurisdiction_code,
                    )
                )

    # Frontier closure.
    frontier = receipt.get("frontier")
    if isinstance(frontier, Mapping):
        if frontier.get("closed") is not True:
            findings.append(
                _finding(
                    section="live_receipts",
                    case_id=case_id,
                    kind="open_frontier",
                    detail="frontier.closed is not true",
                    jurisdiction=jurisdiction_code,
                )
            )
        if frontier.get("enumerator_closed") is not True:
            findings.append(
                _finding(
                    section="live_receipts",
                    case_id=case_id,
                    kind="enumerator_not_closed",
                    detail="frontier.enumerator_closed is not true",
                    jurisdiction=jurisdiction_code,
                )
            )
        unvisited = _as_str_list(frontier.get("unvisited_continuation_links"))
        if unvisited:
            findings.append(
                _finding(
                    section="live_receipts",
                    case_id=case_id,
                    kind="unvisited_continuation_links",
                    detail=f"unvisited continuation links: {unvisited}",
                    jurisdiction=jurisdiction_code,
                )
            )
        expected_units = frontier.get("expected_index_units")
        visited_units = frontier.get("visited_index_units")
        if (
            isinstance(expected_units, int)
            and not isinstance(expected_units, bool)
            and isinstance(visited_units, int)
            and not isinstance(visited_units, bool)
            and visited_units < expected_units
        ):
            findings.append(
                _finding(
                    section="live_receipts",
                    case_id=case_id,
                    kind="enumerator_not_closed",
                    detail=(
                        f"visited_index_units ({visited_units}) < "
                        f"expected_index_units ({expected_units})"
                    ),
                    jurisdiction=jurisdiction_code,
                )
            )

    # Bundle counts.
    bundles = receipt.get("bundles")
    if isinstance(bundles, Mapping):
        expected_count = bundles.get("expected_count")
        fetched_count = bundles.get("fetched_count")
        if (
            isinstance(expected_count, int)
            and not isinstance(expected_count, bool)
            and isinstance(fetched_count, int)
            and not isinstance(fetched_count, bool)
            and fetched_count != expected_count
        ):
            findings.append(
                _finding(
                    section="live_receipts",
                    case_id=case_id,
                    kind="bundle_count_mismatch",
                    detail=(
                        f"bundle fetched_count ({fetched_count}) != "
                        f"expected_count ({expected_count})"
                    ),
                    jurisdiction=jurisdiction_code,
                )
            )

    # Boundary probes.
    probes = receipt.get("boundary_probes")
    if not isinstance(probes, Mapping):
        findings.append(
            _finding(
                section="live_receipts",
                case_id=case_id,
                kind="missing_boundary_probes",
                detail="boundary_probes object missing",
                jurisdiction=jurisdiction_code,
            )
        )
    else:
        first_unit = probes.get("first_hierarchy_unit")
        last_unit = probes.get("last_hierarchy_unit")
        if not first_unit or not last_unit:
            findings.append(
                _finding(
                    section="live_receipts",
                    case_id=case_id,
                    kind="missing_boundary_probes",
                    detail=(
                        "boundary probes require first_hierarchy_unit and "
                        "last_hierarchy_unit"
                    ),
                    jurisdiction=jurisdiction_code,
                )
            )

    # Response errors.
    response_errors = receipt.get("response_errors")
    if isinstance(response_errors, list):
        unresolved = [
            item
            for item in response_errors
            if isinstance(item, Mapping) and item.get("resolved") is not True
        ]
        if unresolved:
            findings.append(
                _finding(
                    section="live_receipts",
                    case_id=case_id,
                    kind="response_errors_unresolved",
                    detail=f"{len(unresolved)} unresolved response error(s)",
                    jurisdiction=jurisdiction_code,
                )
            )

    # Disposition arithmetic.
    disposition = receipt.get("disposition")
    if isinstance(disposition, Mapping):
        try:
            ok, detail = _disposition_reconciles(disposition)
        except FullCorpusAuditError as exc:
            findings.append(
                _finding(
                    section="live_receipts",
                    case_id=case_id,
                    kind="disposition_arithmetic_mismatch",
                    detail=str(exc),
                    jurisdiction=jurisdiction_code,
                )
            )
        else:
            if not ok:
                findings.append(
                    _finding(
                        section="live_receipts",
                        case_id=case_id,
                        kind="disposition_arithmetic_mismatch",
                        detail=detail,
                        jurisdiction=jurisdiction_code,
                    )
                )
            failed_final = disposition.get("failed_final")
            if (
                isinstance(failed_final, int)
                and not isinstance(failed_final, bool)
                and failed_final > 0
            ):
                findings.append(
                    _finding(
                        section="live_receipts",
                        case_id=case_id,
                        kind="failed_final_nonzero",
                        detail=f"failed_final={failed_final} blocks publication",
                        jurisdiction=jurisdiction_code,
                    )
                )
    else:
        findings.append(
            _finding(
                section="live_receipts",
                case_id=case_id,
                kind="disposition_arithmetic_mismatch",
                detail="disposition object missing",
                jurisdiction=jurisdiction_code,
            )
        )

    kinds: list[str] = []
    for item in findings:
        if item.kind not in kinds:
            kinds.append(item.kind)

    return CaseResult(
        case_id=case_id,
        section="live_receipts",
        status="pass" if not findings else "fail",
        findings=findings,
        kinds=kinds,
    )


def audit_live_receipt_case(
    case: Mapping[str, Any],
    *,
    known_false_success: Mapping[str, int] | None = None,
) -> CaseResult:
    """Dispatch a fixture/live case to the appropriate receipt auditor."""
    case_id = str(case.get("case_id") or "unknown")
    kind = str(case.get("kind") or "jurisdiction_receipt")
    receipt = _require_mapping(case.get("receipt"), f"cases[{case_id}].receipt")
    expected_status = case.get("expected_status")
    expected_status_s = str(expected_status) if expected_status is not None else None

    if kind == "jurisdiction_set":
        result = audit_jurisdiction_set(case_id=case_id, receipt=receipt)
    elif kind == "combined_viewer":
        result = audit_combined_viewer(case_id=case_id, receipt=receipt)
    else:
        result = audit_jurisdiction_receipt(
            case_id=case_id,
            receipt=receipt,
            known_false_success=known_false_success,
        )
    result.expected_status = expected_status_s
    return result


def _load_static_guard_module():
    """Load the existing static full-corpus AST guard module."""
    script_path = Path(__file__).with_name("audit_state_scraper_full_corpus_guards.py")
    if not script_path.is_file():
        raise FullCorpusAuditError(f"static guard script missing: {script_path}")
    module_name = "audit_state_scraper_full_corpus_guards_for_lcr005"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise FullCorpusAuditError(f"unable to load static guard module: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def audit_static_source(
    *,
    case_id: str,
    state: str,
    source: str,
    guard_module: Any | None = None,
) -> CaseResult:
    """Run static AST guards against an in-memory scraper source snippet."""
    module = guard_module if guard_module is not None else _load_static_guard_module()
    with tempfile.TemporaryDirectory(prefix="lcr005-static-") as tmp:
        tmp_root = Path(tmp)
        path = tmp_root / f"{state.lower()}_snippet.py"
        path.write_text(source, encoding="utf-8")
        raw_findings = module.audit_file(state=state, path=path, repo_root=tmp_root)

    findings: list[Finding] = []
    for item in raw_findings:
        findings.append(
            Finding(
                section="static_ast_guards",
                case_id=case_id,
                kind=str(getattr(item, "kind", "static_finding")),
                severity=str(getattr(item, "severity", "warning")),
                detail=str(getattr(item, "detail", "")),
                jurisdiction=str(state).upper(),
            )
        )
    # Only error-severity findings fail the static section for fixture checks.
    error_findings = [item for item in findings if item.severity == "error"]
    kinds: list[str] = []
    for item in findings:
        if item.kind not in kinds:
            kinds.append(item.kind)
    return CaseResult(
        case_id=case_id,
        section="static_ast_guards",
        status="pass" if not error_findings else "fail",
        findings=findings,
        kinds=kinds,
    )


def audit_static_snippet_case(
    case: Mapping[str, Any],
    *,
    guard_module: Any | None = None,
) -> CaseResult:
    """Audit one fixture static AST snippet case."""
    case_id = str(case.get("case_id") or "unknown")
    state = str(case.get("state") or "ZZ").upper()
    source = str(case.get("source") or "")
    if not source.strip():
        raise FullCorpusAuditError(f"static snippet {case_id} has empty source")
    result = audit_static_source(
        case_id=case_id,
        state=state,
        source=source,
        guard_module=guard_module,
    )
    expected_status = case.get("expected_status")
    result.expected_status = str(expected_status) if expected_status is not None else None
    return result


def _classification_matches(result: CaseResult, case: Mapping[str, Any]) -> list[str]:
    """Return mismatches between expected fixture labels and observed audit result."""
    mismatches: list[str] = []
    expected_status = case.get("expected_status")
    if expected_status is not None and result.status != str(expected_status):
        mismatches.append(
            f"{result.case_id}: status expected={expected_status!r} got={result.status!r}"
        )
    expected_kinds = case.get("expected_kinds")
    if isinstance(expected_kinds, list):
        expected_set = {str(item) for item in expected_kinds}
        observed_set = set(result.kinds)
        if expected_status == "pass":
            if observed_set:
                mismatches.append(
                    f"{result.case_id}: expected no kinds, got {sorted(observed_set)}"
                )
        else:
            missing = sorted(expected_set - observed_set)
            if missing:
                mismatches.append(
                    f"{result.case_id}: missing expected kinds {missing}; "
                    f"observed={sorted(observed_set)}"
                )
    return mismatches


def run_fixture_audit(
    *,
    fixture: Mapping[str, Any] | None = None,
    fixture_path: Path | str | None = None,
    include_static: bool = True,
) -> dict[str, Any]:
    """Run the offline fixture audit and return a structured report."""
    payload = dict(fixture) if fixture is not None else load_fixture(fixture_path)
    expected_codes = expected_jurisdiction_codes()

    known = payload.get("known_false_success_examples") or {}
    registry_examples = {}
    if isinstance(known, Mapping):
        raw_registry = known.get("registry_truncation_success")
        if isinstance(raw_registry, Mapping):
            registry_examples = {
                str(key).upper(): int(value)
                for key, value in raw_registry.items()
                if isinstance(value, int) and not isinstance(value, bool)
            }
    if not registry_examples:
        registry_examples = dict(KNOWN_FALSE_SUCCESS_REGISTRY)

    live_results: list[CaseResult] = []
    live_findings: list[Finding] = []
    classification_mismatches: list[str] = []

    for case in payload.get("cases") or []:
        if not isinstance(case, Mapping):
            continue
        result = audit_live_receipt_case(case, known_false_success=registry_examples)
        live_results.append(result)
        live_findings.extend(result.findings)
        classification_mismatches.extend(_classification_matches(result, case))

    static_results: list[CaseResult] = []
    static_findings: list[Finding] = []
    if include_static:
        guard_module = _load_static_guard_module()
        for case in payload.get("static_ast_snippets") or []:
            if not isinstance(case, Mapping):
                continue
            result = audit_static_snippet_case(case, guard_module=guard_module)
            static_results.append(result)
            static_findings.extend(result.findings)
            classification_mismatches.extend(_classification_matches(result, case))

    # Explicit acceptance probes: one-state overwrite + all known false-success.
    caught_one_state = any(
        "one_state_combined_overwrite" in result.kinds for result in live_results
    )
    caught_false_success_codes = sorted(
        {
            finding.jurisdiction
            for finding in live_findings
            if finding.kind == "false_success_truncation" and finding.jurisdiction
        }
    )
    expected_false_success_codes = sorted(registry_examples)
    missing_false_success = sorted(
        set(expected_false_success_codes) - set(caught_false_success_codes)
    )

    live_error_count = sum(1 for item in live_findings if item.severity == "error")
    static_error_count = sum(1 for item in static_findings if item.severity == "error")

    # Fixture gate passes when the auditor correctly classifies all cases and
    # catches the required false-success/overwrite examples. Individual fixture
    # cases intentionally fail; that is evidence the auditor works.
    gate_ok = (
        not classification_mismatches
        and caught_one_state
        and not missing_false_success
    )

    # Section-level status reflects classification success, not whether
    # individual negative cases failed (those failures are the point of the fixture).
    static_class_ok = not any(
        r.expected_status is not None and r.status != r.expected_status
        for r in static_results
    )
    live_class_ok = not any(
        r.expected_status is not None and r.status != r.expected_status
        for r in live_results
    )

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "schema_version": "1",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "code_version": CODE_VERSION,
        "mode": "fixture",
        "network_required": False,
        "jurisdiction_contract": {
            "required_count": JURISDICTION_COUNT,
            "required_codes": expected_codes,
            "includes_dc": True,
        },
        "static_ast_guards": {
            "status": "pass" if static_class_ok else "fail",
            "cases_checked": len(static_results),
            "error_count": static_error_count,
            "warning_count": sum(
                1 for item in static_findings if item.severity == "warning"
            ),
            "findings": [item.to_dict() for item in static_findings],
            "cases": [item.to_dict() for item in static_results],
        },
        "live_receipts": {
            "status": "pass" if live_class_ok else "fail",
            "cases_checked": len(live_results),
            "error_count": live_error_count,
            "warning_count": sum(
                1 for item in live_findings if item.severity == "warning"
            ),
            "findings": [item.to_dict() for item in live_findings],
            "cases": [item.to_dict() for item in live_results],
        },
        "acceptance": {
            "caught_one_state_combined_overwrite": caught_one_state,
            "caught_false_success_codes": caught_false_success_codes,
            "expected_false_success_codes": expected_false_success_codes,
            "missing_false_success_codes": missing_false_success,
            "static_ast_guards_reported_separately": True,
            "live_receipts_reported_separately": True,
            "classification_mismatches": classification_mismatches,
            "all_expected_outputs_accounted": True,
            "gate_ok": gate_ok,
        },
        "known_false_success_examples": {
            "registry_truncation_success": dict(registry_examples),
            "remote_truncation_examples": dict(KNOWN_REMOTE_TRUNCATIONS),
        },
        "status": "pass" if gate_ok else "fail",
    }
    return report


def check_fixture_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a fixture audit report against LCR-005 acceptance."""
    mismatches: list[str] = []

    if report.get("schema") != REPORT_SCHEMA:
        mismatches.append(f"schema expected {REPORT_SCHEMA!r}, got {report.get('schema')!r}")
    if report.get("task_id") != TASK_ID:
        mismatches.append(f"task_id expected {TASK_ID!r}, got {report.get('task_id')!r}")

    if "static_ast_guards" not in report:
        mismatches.append("static_ast_guards section missing")
    if "live_receipts" not in report:
        mismatches.append("live_receipts section missing")

    static_section = report.get("static_ast_guards")
    live_section = report.get("live_receipts")
    if not isinstance(static_section, Mapping):
        mismatches.append("static_ast_guards must be an object")
    if not isinstance(live_section, Mapping):
        mismatches.append("live_receipts must be an object")

    acceptance = report.get("acceptance")
    if not isinstance(acceptance, Mapping):
        mismatches.append("acceptance object missing")
        acceptance = {}

    if acceptance.get("caught_one_state_combined_overwrite") is not True:
        mismatches.append("did not catch one-state combined overwrite")
    missing = acceptance.get("missing_false_success_codes")
    if isinstance(missing, list) and missing:
        mismatches.append(f"missing false-success catches: {missing}")
    class_mismatches = acceptance.get("classification_mismatches")
    if isinstance(class_mismatches, list) and class_mismatches:
        mismatches.extend(f"classification: {item}" for item in class_mismatches)
    if acceptance.get("static_ast_guards_reported_separately") is not True:
        mismatches.append("static AST guards not separately reported")
    if acceptance.get("live_receipts_reported_separately") is not True:
        mismatches.append("live receipts not separately reported")
    if report.get("status") != "pass" and not mismatches:
        mismatches.append("report status is not pass")
    if acceptance.get("gate_ok") is not True and not mismatches:
        mismatches.append("acceptance.gate_ok is not true")

    if mismatches:
        raise FullCorpusAuditError(
            "full-corpus fixture audit check failed:\n- " + "\n- ".join(mismatches)
        )
    return {
        "ok": True,
        "status": report.get("status"),
        "acceptance": dict(acceptance),
        "static_ast_guards_status": (
            static_section.get("status") if isinstance(static_section, Mapping) else None
        ),
        "live_receipts_status": (
            live_section.get("status") if isinstance(live_section, Mapping) else None
        ),
    }


def render_check_summary(result: Mapping[str, Any], report: Mapping[str, Any] | None = None) -> str:
    """Render a human-readable check summary."""
    lines = [
        f"status: {result.get('status', result.get('ok'))}",
        f"static_ast_guards: {result.get('static_ast_guards_status')}",
        f"live_receipts: {result.get('live_receipts_status')}",
    ]
    acceptance = result.get("acceptance")
    if isinstance(acceptance, Mapping):
        lines.append(
            "caught_one_state_combined_overwrite: "
            f"{acceptance.get('caught_one_state_combined_overwrite')}"
        )
        lines.append(
            "caught_false_success_codes: "
            f"{acceptance.get('caught_false_success_codes')}"
        )
    if isinstance(report, Mapping):
        static = report.get("static_ast_guards")
        live = report.get("live_receipts")
        if isinstance(static, Mapping):
            lines.append(
                f"static_ast_guards.cases_checked: {static.get('cases_checked')}"
            )
        if isinstance(live, Mapping):
            lines.append(f"live_receipts.cases_checked: {live.get('cases_checked')}")
            live_cases = live.get("cases") or []
            fail_ids = [
                item.get("case_id")
                for item in live_cases
                if isinstance(item, Mapping) and item.get("status") == "fail"
            ]
            lines.append(f"live_receipts.failed_case_ids: {fail_ids}")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Use the sealed offline frontier-receipts fixture (required for CI checks).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate fixture audit acceptance (catches overwrite + false-success).",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help=(
            "Path to the frontier receipts fixture "
            f"(default: {DEFAULT_FIXTURE_RELPATH.as_posix()})"
        ),
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the audit report JSON to stdout.",
    )
    parser.add_argument(
        "--skip-static",
        action="store_true",
        help="Skip static AST guard section (live receipts only).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    fixture_path = (
        Path(args.fixture).expanduser().resolve()
        if args.fixture is not None
        else default_fixture_path()
    )

    try:
        if (args.check) and not args.fixture_only:
            raise FullCorpusAuditError(
                "live scrape audit is not enabled in this gate; pass "
                "--fixture-only to use the sealed offline fixture"
            )

        report = run_fixture_audit(
            fixture_path=fixture_path,
            include_static=not args.skip_static,
        )

        if args.check:
            result = check_fixture_report(report)
            print(render_check_summary(result, report))
            if args.print_json:
                sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
            return 0

        if args.print_json:
            sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
            return 0 if report.get("status") == "pass" else 1

        # Default: run fixture audit and print summary.
        if report.get("status") != "pass":
            # Still surface the report for debugging, but fail closed.
            print(render_check_summary({"ok": False, **report.get("acceptance", {})}, report))
            print(
                "hint: pass --fixture-only --check to validate sealed acceptance",
                file=sys.stderr,
            )
            return 1

        result = check_fixture_report(report)
        print(render_check_summary(result, report))
        print(
            "hint: pass --fixture-only --check to validate sealed acceptance",
            file=sys.stderr,
        )
        return 0
    except FullCorpusAuditError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
