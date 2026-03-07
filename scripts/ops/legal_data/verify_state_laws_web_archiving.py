#!/usr/bin/env python3
"""Verify state-law JSON-LD source URLs are retrievable via unified web archiving.

This script validates one or more state JSON-LD files by attempting unified fetches
against extracted source URLs. It runs in parallel across states and supports a
Wayback-style fallback path for URLs that fail direct fetch.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Dict, Iterable, List, Sequence, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.processors.web_archiving.contracts import OperationMode, UnifiedFetchRequest
from ipfs_datasets_py.processors.web_archiving.unified_api import UnifiedWebArchivingAPI

ALL_STATES: List[str] = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
]

URL_FIELDS: Tuple[str, ...] = ("sourceUrl", "url", "sameAs")


def is_synthetic_row(row: Dict[str, object]) -> bool:
    text = str(row.get("text") or "").lower()
    identifier = str(row.get("identifier") or "").lower()
    return (
        "generated-filler" in text
        or "example.invalid" in text
        or "-fill-" in identifier
    )


@dataclass
class StateVerificationResult:
    state: str
    success: bool
    method: str
    selected_url: str
    provider: str
    quality_score: float
    error: str
    candidate_urls: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "state": self.state,
            "success": self.success,
            "method": self.method,
            "selected_url": self.selected_url,
            "provider": self.provider,
            "quality_score": self.quality_score,
            "error": self.error,
            "candidate_urls": self.candidate_urls,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify state-law URL retrievability via unified web archiving")
    parser.add_argument(
        "--jsonld-dir",
        default=str(Path.home() / ".ipfs_datasets/state_laws/state_laws_jsonld"),
        help="Directory containing STATE-XX.jsonld files",
    )
    parser.add_argument(
        "--states",
        default="all",
        help="Comma-separated state codes, or 'all'",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=12,
        help="Parallel workers across states",
    )
    parser.add_argument(
        "--samples-per-state",
        type=int,
        default=3,
        help="Max JSON-LD rows to sample per state when extracting URLs",
    )
    parser.add_argument(
        "--per-state-max-urls",
        type=int,
        default=12,
        help="Hard cap of candidate URLs per state",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=25,
        help="Unified fetch timeout per URL",
    )
    parser.add_argument(
        "--mode",
        choices=[m.value for m in OperationMode],
        default=OperationMode.BALANCED.value,
        help="Unified operation mode",
    )
    parser.add_argument(
        "--domain",
        default="legal",
        help="Unified request domain",
    )
    parser.add_argument(
        "--disable-archive-fallback",
        action="store_true",
        help="Only test direct URLs, skip Wayback URL fallbacks",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Optional path to write full JSON report",
    )
    return parser.parse_args()


def parse_states(raw_states: str) -> List[str]:
    raw = str(raw_states or "").strip().lower()
    if raw == "all" or not raw:
        return list(ALL_STATES)

    requested = [s.strip().upper() for s in str(raw_states).split(",") if s.strip()]
    states = [s for s in requested if s in ALL_STATES]
    invalid = [s for s in requested if s not in ALL_STATES]
    if invalid:
        print(f"invalid_states_ignored: {','.join(invalid)}")
    return states


def iter_jsonld_rows(path: Path, sample_rows: int) -> Iterable[Dict[str, object]]:
    yielded = 0
    if not path.exists():
        return

    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if yielded >= sample_rows:
                return
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                yielded += 1
                yield row


def _norm_url(value: object) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if not (url.startswith("http://") or url.startswith("https://")):
        return ""
    if "example.invalid" in url:
        return ""
    if url.startswith("http://web.archive.org/"):
        url = "https://" + url[len("http://"):]
    # Repair malformed archived replay segments like .../http:/example.com.
    url = url.replace("/http:///", "/http://")
    url = url.replace("/https:///", "/https://")
    url = url.replace("/http:/", "/http://")
    url = url.replace("/https:/", "/https://")
    return url


def extract_candidate_urls(path: Path, sample_rows: int, max_urls: int) -> List[str]:
    unique: List[str] = []
    seen: Set[str] = set()

    for row in iter_jsonld_rows(path, sample_rows):
        if is_synthetic_row(row):
            continue
        for field in URL_FIELDS:
            url = _norm_url(row.get(field))
            if not url:
                continue
            if url in seen:
                continue
            seen.add(url)
            unique.append(url)
            if len(unique) >= max_urls:
                return unique

    return unique


def build_wayback_candidates(url: str) -> List[str]:
    if "web.archive.org/web/" in url:
        return [url]

    # Prefer explicit replay URLs over wildcard listing pages.
    return [
        f"https://web.archive.org/web/0/{url}",
        f"https://web.archive.org/web/2/{url}",
        f"https://web.archive.org/web/*/{url}",
    ]


def run_fetch(api: UnifiedWebArchivingAPI, url: str, timeout_seconds: int, mode: OperationMode, domain: str) -> Tuple[bool, str, str, float]:
    request = UnifiedFetchRequest(
        url=url,
        timeout_seconds=timeout_seconds,
        mode=mode,
        domain=domain,
    )
    response = api.fetch(request)

    if response.success and response.document and str(response.document.text or "").strip():
        provider = ""
        if response.trace and response.trace.provider_selected:
            provider = str(response.trace.provider_selected)
        return True, "", provider, float(response.quality_score or 0.0)

    error_messages = [str(err.message) for err in (response.errors or []) if getattr(err, "message", "")]
    error = "; ".join(error_messages) if error_messages else "no_document_text"
    return False, error, "", float(response.quality_score or 0.0)


def verify_state(
    *,
    state: str,
    jsonld_dir: Path,
    sample_rows: int,
    max_urls: int,
    timeout_seconds: int,
    mode: OperationMode,
    domain: str,
    use_archive_fallback: bool,
) -> StateVerificationResult:
    state_file = jsonld_dir / f"STATE-{state}.jsonld"
    if not state_file.exists():
        return StateVerificationResult(
            state=state,
            success=False,
            method="none",
            selected_url="",
            provider="",
            quality_score=0.0,
            error="missing_state_file",
            candidate_urls=0,
        )

    candidate_urls = extract_candidate_urls(state_file, sample_rows=sample_rows, max_urls=max_urls)
    if not candidate_urls:
        return StateVerificationResult(
            state=state,
            success=False,
            method="none",
            selected_url="",
            provider="",
            quality_score=0.0,
            error="no_candidate_urls",
            candidate_urls=0,
        )

    api = UnifiedWebArchivingAPI()
    first_error = ""

    for url in candidate_urls:
        ok, err, provider, score = run_fetch(api, url, timeout_seconds, mode, domain)
        if ok:
            return StateVerificationResult(
                state=state,
                success=True,
                method="direct",
                selected_url=url,
                provider=provider,
                quality_score=score,
                error="",
                candidate_urls=len(candidate_urls),
            )
        if not first_error:
            first_error = err

    if use_archive_fallback:
        for url in candidate_urls:
            for archive_url in build_wayback_candidates(url):
                ok, err, provider, score = run_fetch(api, archive_url, timeout_seconds, mode, domain)
                if ok:
                    return StateVerificationResult(
                        state=state,
                        success=True,
                        method="archive_fallback",
                        selected_url=archive_url,
                        provider=provider,
                        quality_score=score,
                        error="",
                        candidate_urls=len(candidate_urls),
                    )
                if not first_error:
                    first_error = err

    return StateVerificationResult(
        state=state,
        success=False,
        method="failed",
        selected_url="",
        provider="",
        quality_score=0.0,
        error=first_error or "all_attempts_failed",
        candidate_urls=len(candidate_urls),
    )


def summarize(results: Sequence[StateVerificationResult]) -> Dict[str, object]:
    total = len(results)
    successes = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    direct = [r for r in successes if r.method == "direct"]
    fallback = [r for r in successes if r.method == "archive_fallback"]

    provider_counts: Dict[str, int] = {}
    for r in successes:
        provider = r.provider or "unknown"
        provider_counts[provider] = provider_counts.get(provider, 0) + 1

    return {
        "states_total": total,
        "states_success": len(successes),
        "states_failed": len(failed),
        "direct_success": len(direct),
        "archive_fallback_success": len(fallback),
        "failed_states": [r.state for r in failed],
        "provider_counts": dict(sorted(provider_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "results": [r.to_dict() for r in sorted(results, key=lambda x: x.state)],
    }


def main() -> int:
    args = parse_args()
    jsonld_dir = Path(args.jsonld_dir).expanduser().resolve()
    states = parse_states(args.states)
    if not states:
        print("No valid states selected")
        return 2

    workers = max(1, int(args.workers))
    sample_rows = max(1, int(args.samples_per_state))
    per_state_max_urls = max(1, int(args.per_state_max_urls))
    timeout_seconds = max(1, int(args.timeout_seconds))
    mode = OperationMode(args.mode)
    use_archive_fallback = not bool(args.disable_archive_fallback)

    results: List[StateVerificationResult] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                verify_state,
                state=state,
                jsonld_dir=jsonld_dir,
                sample_rows=sample_rows,
                max_urls=per_state_max_urls,
                timeout_seconds=timeout_seconds,
                mode=mode,
                domain=str(args.domain),
                use_archive_fallback=use_archive_fallback,
            )
            for state in states
        ]

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(
                json.dumps(
                    {
                        "state": result.state,
                        "success": result.success,
                        "method": result.method,
                        "provider": result.provider,
                        "selected_url": result.selected_url,
                        "error": result.error,
                    },
                    sort_keys=True,
                )
            )

    summary = summarize(results)
    print("summary:")
    print(json.dumps(summary, indent=2, sort_keys=True))

    if args.output_json:
        output_path = Path(args.output_json).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote_report: {output_path}")

    return 0 if int(summary["states_failed"]) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
