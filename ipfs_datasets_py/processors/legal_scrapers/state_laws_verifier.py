"""State laws verification engine.

Verification suite for testing state law scraper JSON-LD completeness and
structure quality across jurisdictions.
"""

import json
import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .state_laws_scraper import scrape_state_laws
except Exception:
    scrape_state_laws = None  # type: ignore[assignment]

try:
    from .state_laws_scraper import US_STATES
except Exception:
    US_STATES = {}


_VERIFY_SCAFFOLD_RE = re.compile(r"^\s*Section\s+Section-\d+\s*:", re.IGNORECASE)
_VERIFY_STATUTE_SIGNAL_RE = re.compile(
    r"(?:\b\d{1,4}[A-Za-z]?(?:[.\-]\d+[A-Za-z]*)+\b|§\s*\d+[A-Za-z]?(?:[.\-]\d+[A-Za-z]*)+|\b(?:section|sec\.?|s\.)\s*\d+[A-Za-z]?(?:[.\-]\d+[A-Za-z]*)*\b)",
    re.IGNORECASE,
)


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _build_operational_diagnostics(metadata: Dict[str, Any], *, top_n: int = 8) -> Dict[str, Any]:
    coverage = metadata.get("coverage_summary") or {}
    etl = metadata.get("etl_readiness") or {}
    fetch = metadata.get("fetch_analytics") or {}
    fetch_by_state = metadata.get("fetch_analytics_by_state") or {}
    quality_by_state = metadata.get("quality_by_state") or {}

    coverage_gap_states = list(coverage.get("coverage_gap_states") or [])

    weak_fetch_states: List[Dict[str, Any]] = []
    if isinstance(fetch_by_state, dict):
        for state_code, metrics in fetch_by_state.items():
            if not isinstance(metrics, dict):
                continue
            attempted = int(metrics.get("attempted", 0) or 0)
            success = int(metrics.get("success", 0) or 0)
            fallback_count = int(metrics.get("fallback_count", 0) or 0)
            success_ratio = _safe_ratio(success, attempted)
            fallback_ratio = _safe_ratio(fallback_count, attempted)
            weak_fetch_states.append(
                {
                    "state": str(state_code),
                    "attempted": attempted,
                    "success": success,
                    "success_ratio": round(success_ratio, 3),
                    "fallback_count": fallback_count,
                    "fallback_ratio": round(fallback_ratio, 3),
                    "last_error": metrics.get("last_error"),
                }
            )

    weak_fetch_states.sort(key=lambda row: (row.get("success_ratio", 1.0), -int(row.get("attempted", 0) or 0)))

    weak_quality_states: List[Dict[str, Any]] = []
    if isinstance(quality_by_state, dict):
        for state_code, metrics in quality_by_state.items():
            if not isinstance(metrics, dict):
                continue
            weak_quality_states.append(
                {
                    "state": str(state_code),
                    "total": int(metrics.get("total", 0) or 0),
                    "scaffold_ratio": float(metrics.get("scaffold_ratio", 0.0) or 0.0),
                    "nav_like_ratio": float(metrics.get("nav_like_ratio", 0.0) or 0.0),
                    "fallback_section_ratio": float(metrics.get("fallback_section_ratio", 0.0) or 0.0),
                    "numeric_section_name_ratio": float(metrics.get("numeric_section_name_ratio", 0.0) or 0.0),
                }
            )

    weak_quality_states.sort(
        key=lambda row: (
            -float(row.get("scaffold_ratio", 0.0) or 0.0),
            -float(row.get("nav_like_ratio", 0.0) or 0.0),
            -float(row.get("fallback_section_ratio", 0.0) or 0.0),
        )
    )

    return {
        "coverage": {
            "states_targeted": int(coverage.get("states_targeted", 0) or 0),
            "states_returned": int(coverage.get("states_returned", 0) or 0),
            "states_with_nonzero_statutes": int(coverage.get("states_with_nonzero_statutes", 0) or 0),
            "coverage_gap_states": coverage_gap_states,
        },
        "fetch": {
            "attempted": int(fetch.get("attempted", 0) or 0),
            "success": int(fetch.get("success", 0) or 0),
            "success_ratio": float(fetch.get("success_ratio", 0.0) or 0.0),
            "fallback_count": int(fetch.get("fallback_count", 0) or 0),
            "providers": fetch.get("providers") if isinstance(fetch.get("providers"), dict) else {},
            "weak_states": weak_fetch_states[: max(1, int(top_n or 1))],
        },
        "etl_readiness": {
            "ready_for_kg_etl": bool(etl.get("ready_for_kg_etl")),
            "total_statutes": int(etl.get("total_statutes", 0) or 0),
            "full_text_ratio": float(etl.get("full_text_ratio", 0.0) or 0.0),
            "jsonld_ratio": float(etl.get("jsonld_ratio", 0.0) or 0.0),
            "citation_ratio": float(etl.get("citation_ratio", 0.0) or 0.0),
            "states_with_zero_statutes": int(etl.get("states_with_zero_statutes", 0) or 0),
        },
        "quality": {
            "weak_states": weak_quality_states[: max(1, int(top_n or 1))],
        },
    }


class StateLawsVerifier:
    """Verification suite for state law scraper output quality."""

    def __init__(self):
        self.results: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "tests": [],
            "summary": {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "warnings": 0,
            },
        }
        self._last_scrape_metadata: Dict[str, Any] = {}

    def log_test(self, name: str, status: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        test_result = {
            "name": name,
            "status": status,
            "message": message,
            "details": details or {},
        }
        self.results["tests"].append(test_result)
        self.results["summary"]["total"] += 1
        if status == "PASS":
            self.results["summary"]["passed"] += 1
        elif status == "FAIL":
            self.results["summary"]["failed"] += 1
        elif status == "WARN":
            self.results["summary"]["warnings"] += 1

    @staticmethod
    def _coverage_ratio(total: int, have: int) -> float:
        if total <= 0:
            return 0.0
        return float(have) / float(total)

    async def verify_jsonld_completeness(
        self,
        *,
        states: Optional[List[str]] = None,
        max_statutes: int = 400,
        min_full_text_chars: int = 300,
        rate_limit_delay: float = 0.5,
    ) -> Dict[str, Any]:
        if scrape_state_laws is None:
            self.log_test(
                "Scraper Import",
                "FAIL",
                "state_laws_scraper could not be imported",
            )
            return self.results

        result = await scrape_state_laws(
            states=states,
            max_statutes=max_statutes,
            rate_limit_delay=rate_limit_delay,
            write_jsonld=True,
            strict_full_text=True,
            min_full_text_chars=min_full_text_chars,
        )

        if result.get("status") not in {"success", "partial_success"}:
            self.log_test(
                "State Scrape",
                "FAIL",
                "state scrape failed",
                {"error": result.get("error")},
            )
            return self.results

        data = result.get("data") or []
        records: List[Dict[str, Any]] = []
        for state_block in data:
            statutes = state_block.get("statutes") if isinstance(state_block, dict) else []
            if isinstance(statutes, list):
                for statute in statutes:
                    if isinstance(statute, dict):
                        records.append(statute)

        total = len(records)
        if total == 0:
            self.log_test("Dataset Non-Empty", "FAIL", "No statutes returned")
            return self.results

        preamble_count = 0
        subsections_count = 0
        citations_count = 0
        jsonld_count = 0
        scaffold_count = 0
        weak_text_count = 0
        legal_signal_count = 0

        for statute in records:
            structured = statute.get("structured_data") or {}
            if not isinstance(structured, dict):
                continue

            full_text = str(statute.get("full_text") or statute.get("text") or "")
            section_name = str(statute.get("section_name") or statute.get("sectionName") or "")
            source_url = str(statute.get("source_url") or statute.get("sourceUrl") or "")

            if _VERIFY_SCAFFOLD_RE.match(full_text):
                scaffold_count += 1
            nav_url = any(tok in source_url.lower() for tok in ("/calendar", "/meeting", "/roster", "/blog", "/news", "/jobs", "/contact"))
            if len(full_text.strip()) < int(min_full_text_chars) or nav_url:
                weak_text_count += 1
            if _VERIFY_STATUTE_SIGNAL_RE.search(full_text) or _VERIFY_STATUTE_SIGNAL_RE.search(section_name):
                legal_signal_count += 1

            preamble = structured.get("preamble")
            if isinstance(preamble, str) and preamble.strip():
                preamble_count += 1

            subsections = structured.get("subsections")
            if isinstance(subsections, list) and len(subsections) > 0:
                subsections_count += 1

            citations = structured.get("citations")
            if isinstance(citations, dict):
                cite_total = sum(len(v) for v in citations.values() if isinstance(v, list))
                if cite_total > 0:
                    citations_count += 1

            payload = structured.get("jsonld")
            if isinstance(payload, dict) and payload.get("@type") == "Legislation":
                jsonld_count += 1

        preamble_cov = self._coverage_ratio(total, preamble_count)
        subsections_cov = self._coverage_ratio(total, subsections_count)
        citations_cov = self._coverage_ratio(total, citations_count)
        jsonld_cov = self._coverage_ratio(total, jsonld_count)
        scaffold_rate = self._coverage_ratio(total, scaffold_count)
        title_without_body_rate = self._coverage_ratio(total, weak_text_count)
        legal_signal_rate = self._coverage_ratio(total, legal_signal_count)

        details = {
            "total_statutes": total,
            "preamble_coverage": preamble_cov,
            "subsections_coverage": subsections_cov,
            "citations_coverage": citations_cov,
            "jsonld_coverage": jsonld_cov,
            "scaffold_rate": scaffold_rate,
            "title_without_body_rate": title_without_body_rate,
            "legal_signal_rate": legal_signal_rate,
            "source_metadata": result.get("metadata") or {},
        }
        self._last_scrape_metadata = result.get("metadata") or {}

        if scaffold_rate > 0.15 or title_without_body_rate > 0.30 or legal_signal_rate < 0.60:
            self.log_test(
                "JSON-LD Completeness",
                "FAIL",
                "Statute quality thresholds failed (scaffold/title-only contamination)",
                details,
            )
        elif jsonld_cov >= 0.95 and preamble_cov >= 0.80 and subsections_cov >= 0.50:
            self.log_test(
                "JSON-LD Completeness",
                "PASS",
                "State statute JSON-LD coverage is healthy",
                details,
            )
        elif jsonld_cov >= 0.80:
            self.log_test(
                "JSON-LD Completeness",
                "WARN",
                "JSON-LD present but content coverage can be improved",
                details,
            )
        else:
            self.log_test(
                "JSON-LD Completeness",
                "FAIL",
                "JSON-LD coverage is below acceptable threshold",
                details,
            )

        return self.results

    def verify_operational_readiness(
        self,
        *,
        require_kg_ready: bool = False,
        min_fetch_success_ratio: Optional[float] = None,
        max_fetch_fallback_ratio: Optional[float] = None,
        max_coverage_gap_states: Optional[int] = None,
    ) -> Dict[str, Any]:
        metadata = self._last_scrape_metadata or {}
        if not metadata:
            self.log_test(
                "Operational Readiness",
                "WARN",
                "No scrape metadata available for operational diagnostics",
            )
            return self.results

        diagnostics = _build_operational_diagnostics(metadata)
        reasons: List[str] = []

        fetch_block = diagnostics.get("fetch") or {}
        coverage_block = diagnostics.get("coverage") or {}
        etl_block = diagnostics.get("etl_readiness") or {}

        fetch_success_ratio = float(fetch_block.get("success_ratio", 0.0) or 0.0)
        fetch_attempted = int(fetch_block.get("attempted", 0) or 0)
        fetch_fallback_count = int(fetch_block.get("fallback_count", 0) or 0)
        fetch_fallback_ratio = _safe_ratio(fetch_fallback_count, fetch_attempted)
        coverage_gap_states = list(coverage_block.get("coverage_gap_states") or [])
        is_kg_ready = bool(etl_block.get("ready_for_kg_etl"))

        if require_kg_ready and not is_kg_ready:
            reasons.append("kg-etl-not-ready")
        if min_fetch_success_ratio is not None and fetch_success_ratio < float(min_fetch_success_ratio):
            reasons.append("fetch-success-ratio-below-threshold")
        if max_fetch_fallback_ratio is not None and fetch_fallback_ratio > float(max_fetch_fallback_ratio):
            reasons.append("fetch-fallback-ratio-above-threshold")
        if max_coverage_gap_states is not None and len(coverage_gap_states) > int(max_coverage_gap_states):
            reasons.append("too-many-coverage-gap-states")

        details = {
            "thresholds": {
                "require_kg_ready": bool(require_kg_ready),
                "min_fetch_success_ratio": min_fetch_success_ratio,
                "max_fetch_fallback_ratio": max_fetch_fallback_ratio,
                "max_coverage_gap_states": max_coverage_gap_states,
            },
            "diagnostics": diagnostics,
            "computed": {
                "fetch_success_ratio": round(fetch_success_ratio, 3),
                "fetch_fallback_ratio": round(fetch_fallback_ratio, 3),
                "coverage_gap_state_count": len(coverage_gap_states),
                "kg_ready": is_kg_ready,
            },
            "reasons": reasons,
        }

        if reasons:
            self.log_test(
                "Operational Readiness",
                "FAIL",
                "Operational thresholds failed",
                details,
            )
            return self.results

        if not is_kg_ready or len(coverage_gap_states) > 0:
            self.log_test(
                "Operational Readiness",
                "WARN",
                "Operational diagnostics detected residual risk",
                details,
            )
            return self.results

        self.log_test(
            "Operational Readiness",
            "PASS",
            "Operational readiness metrics are healthy",
            details,
        )
        return self.results

    async def verify_state_smoke_coverage(
        self,
        *,
        states: Optional[List[str]] = None,
        per_state_max_statutes: int = 20,
        min_full_text_chars: int = 300,
        rate_limit_delay: float = 0.2,
    ) -> Dict[str, Any]:
        if scrape_state_laws is None:
            self.log_test(
                "State Smoke Coverage",
                "FAIL",
                "state_laws_scraper could not be imported",
            )
            return self.results

        selected_states = states or sorted(list(US_STATES.keys()))
        if not selected_states:
            self.log_test("State Smoke Coverage", "FAIL", "No states available for smoke coverage")
            return self.results

        state_results: List[Dict[str, Any]] = []
        failed_states: List[str] = []
        empty_states: List[str] = []

        for state_code in selected_states:
            state_code = str(state_code).upper()
            try:
                result = await scrape_state_laws(
                    states=[state_code],
                    max_statutes=per_state_max_statutes,
                    rate_limit_delay=rate_limit_delay,
                    write_jsonld=True,
                    strict_full_text=True,
                    min_full_text_chars=min_full_text_chars,
                )
            except Exception as exc:
                failed_states.append(state_code)
                state_results.append(
                    {
                        "state": state_code,
                        "status": "exception",
                        "error": str(exc),
                    }
                )
                continue

            status = str(result.get("status") or "unknown")
            data_blocks = result.get("data") or []
            statutes_count = 0
            strict_removed_total = int((result.get("metadata") or {}).get("strict_removed_total") or 0)
            for block in data_blocks:
                statutes = block.get("statutes") if isinstance(block, dict) else []
                if isinstance(statutes, list):
                    statutes_count += len(statutes)

            if status not in {"success", "partial_success"}:
                failed_states.append(state_code)
            elif statutes_count == 0:
                empty_states.append(state_code)

            state_results.append(
                {
                    "state": state_code,
                    "status": status,
                    "statutes": statutes_count,
                    "strict_removed_total": strict_removed_total,
                    "error": result.get("error"),
                }
            )

        total_states = len(selected_states)
        passed_states = total_states - len(failed_states) - len(empty_states)
        pass_ratio = self._coverage_ratio(total_states, passed_states)

        details = {
            "total_states": total_states,
            "passed_states": passed_states,
            "empty_states": empty_states,
            "failed_states": failed_states,
            "pass_ratio": pass_ratio,
            "per_state_max_statutes": per_state_max_statutes,
            "state_results": state_results,
        }

        if pass_ratio >= 0.95:
            self.log_test(
                "State Smoke Coverage",
                "PASS",
                f"{passed_states}/{total_states} states returned statutes",
                details,
            )
        elif pass_ratio >= 0.75:
            self.log_test(
                "State Smoke Coverage",
                "WARN",
                f"Partial state coverage: {passed_states}/{total_states} states",
                details,
            )
        else:
            self.log_test(
                "State Smoke Coverage",
                "FAIL",
                f"Low state coverage: {passed_states}/{total_states} states",
                details,
            )

        return self.results

    async def run_all_tests(
        self,
        *,
        states: Optional[List[str]] = None,
        max_statutes: int = 400,
        per_state_max_statutes: int = 20,
        require_kg_ready: bool = False,
        min_fetch_success_ratio: Optional[float] = None,
        max_fetch_fallback_ratio: Optional[float] = None,
        max_coverage_gap_states: Optional[int] = None,
    ) -> int:
        await self.verify_jsonld_completeness(states=states, max_statutes=max_statutes)
        self.verify_operational_readiness(
            require_kg_ready=require_kg_ready,
            min_fetch_success_ratio=min_fetch_success_ratio,
            max_fetch_fallback_ratio=max_fetch_fallback_ratio,
            max_coverage_gap_states=max_coverage_gap_states,
        )
        await self.verify_state_smoke_coverage(states=states, per_state_max_statutes=per_state_max_statutes)

        output_file = Path.home() / ".ipfs_datasets" / "state_laws" / "verification_results.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(self.results, indent=2), encoding="utf-8")

        return 0 if int(self.results["summary"].get("failed", 0)) == 0 else 1


async def verify_state_laws_scraper(
    states: Optional[List[str]] = None,
    max_statutes: int = 400,
    per_state_max_statutes: int = 20,
) -> Dict[str, Any]:
    verifier = StateLawsVerifier()
    await verifier.run_all_tests(
        states=states,
        max_statutes=max_statutes,
        per_state_max_statutes=per_state_max_statutes,
    )
    return verifier.results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify state law scraper quality and coverage.")
    parser.add_argument(
        "--states",
        type=str,
        default="all",
        help="Comma-separated state codes (e.g., CA,NY,TX) or 'all'.",
    )
    parser.add_argument(
        "--max-statutes",
        type=int,
        default=400,
        help="Max statutes for aggregate completeness run.",
    )
    parser.add_argument(
        "--per-state-max-statutes",
        type=int,
        default=20,
        help="Per-state max statutes for smoke coverage run.",
    )
    parser.add_argument(
        "--require-kg-ready",
        action="store_true",
        help="Fail verification when ETL readiness is not marked ready_for_kg_etl.",
    )
    parser.add_argument(
        "--min-fetch-success-ratio",
        type=float,
        default=None,
        help="Optional fail threshold for aggregate fetch success ratio (0.0-1.0).",
    )
    parser.add_argument(
        "--max-fetch-fallback-ratio",
        type=float,
        default=None,
        help="Optional fail threshold for aggregate fetch fallback ratio (0.0-1.0).",
    )
    parser.add_argument(
        "--max-coverage-gap-states",
        type=int,
        default=None,
        help="Optional fail threshold for number of coverage gap states.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    import asyncio

    args = _parse_args()
    if str(args.states).strip().lower() == "all":
        state_list = None
    else:
        state_list = [item.strip().upper() for item in str(args.states).split(",") if item.strip()]

    verifier = StateLawsVerifier()
    exit_code = asyncio.run(
        verifier.run_all_tests(
            states=state_list,
            max_statutes=int(args.max_statutes),
            per_state_max_statutes=int(args.per_state_max_statutes),
            require_kg_ready=bool(args.require_kg_ready),
            min_fetch_success_ratio=args.min_fetch_success_ratio,
            max_fetch_fallback_ratio=args.max_fetch_fallback_ratio,
            max_coverage_gap_states=args.max_coverage_gap_states,
        )
    )
    raise SystemExit(exit_code)


__all__ = [
    "StateLawsVerifier",
    "_build_operational_diagnostics",
    "verify_state_laws_scraper",
]
