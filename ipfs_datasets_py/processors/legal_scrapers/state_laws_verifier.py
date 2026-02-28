"""State laws verification engine.

Verification suite for testing state law scraper JSON-LD completeness and
structure quality across jurisdictions.
"""

import json
import argparse
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

        for statute in records:
            structured = statute.get("structured_data") or {}
            if not isinstance(structured, dict):
                continue

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

        details = {
            "total_statutes": total,
            "preamble_coverage": preamble_cov,
            "subsections_coverage": subsections_cov,
            "citations_coverage": citations_cov,
            "jsonld_coverage": jsonld_cov,
            "source_metadata": result.get("metadata") or {},
        }

        if jsonld_cov >= 0.95 and preamble_cov >= 0.80 and subsections_cov >= 0.50:
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
    ) -> int:
        await self.verify_jsonld_completeness(states=states, max_statutes=max_statutes)
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
        )
    )
    raise SystemExit(exit_code)


__all__ = [
    "StateLawsVerifier",
    "verify_state_laws_scraper",
]
