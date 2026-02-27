"""State laws verification engine.

Verification suite for testing state law scraper JSON-LD completeness and
structure quality across jurisdictions.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .state_laws_scraper import scrape_state_laws
except Exception:
    scrape_state_laws = None  # type: ignore[assignment]


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

    async def run_all_tests(
        self,
        *,
        states: Optional[List[str]] = None,
        max_statutes: int = 400,
    ) -> int:
        await self.verify_jsonld_completeness(states=states, max_statutes=max_statutes)

        output_file = Path.home() / ".ipfs_datasets" / "state_laws" / "verification_results.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(self.results, indent=2), encoding="utf-8")

        return 0 if int(self.results["summary"].get("failed", 0)) == 0 else 1


async def verify_state_laws_scraper(
    states: Optional[List[str]] = None,
    max_statutes: int = 400,
) -> Dict[str, Any]:
    verifier = StateLawsVerifier()
    await verifier.run_all_tests(states=states, max_statutes=max_statutes)
    return verifier.results


__all__ = [
    "StateLawsVerifier",
    "verify_state_laws_scraper",
]
