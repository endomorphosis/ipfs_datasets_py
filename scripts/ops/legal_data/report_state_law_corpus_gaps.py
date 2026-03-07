#!/usr/bin/env python3
"""Report per-state corpus gaps for state-law JSON-LD outputs.

This audit emphasizes depth/quality indicators beyond raw line count:
- estimated real vs synthetic rows
- unique source URL count (deduplicated pages)
- unique source domain count
- web-archiving verification outcome (optional report input)
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from urllib.parse import urlparse

STATES_50: List[str] = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]


@dataclass
class StateGapRow:
    state: str
    file_exists: bool
    records_total: int
    real_rows: int
    synthetic_rows: int
    real_ratio: float
    unique_source_urls: int
    unique_domains: int
    webarch_success: bool
    webarch_method: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "state": self.state,
            "file_exists": self.file_exists,
            "records_total": self.records_total,
            "real_rows": self.real_rows,
            "synthetic_rows": self.synthetic_rows,
            "real_ratio": round(self.real_ratio, 3),
            "unique_source_urls": self.unique_source_urls,
            "unique_domains": self.unique_domains,
            "webarch_success": self.webarch_success,
            "webarch_method": self.webarch_method,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit corpus gaps for state-law JSON-LD")
    parser.add_argument(
        "--jsonld-dir",
        default=str(Path.home() / ".ipfs_datasets/state_laws/state_laws_jsonld"),
        help="Directory containing STATE-XX.jsonld files",
    )
    parser.add_argument(
        "--verify-report",
        default="",
        help="Optional web-archiving verifier JSON report path",
    )
    parser.add_argument(
        "--output-md",
        default="",
        help="Optional markdown output path",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Optional JSON output path",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=15,
        help="How many worst states to list in summary sections",
    )
    return parser.parse_args()


def is_synthetic_row(obj: Dict[str, object]) -> bool:
    name = str(obj.get("name") or "").lower()
    text = str(obj.get("text") or "").lower()
    identifier = str(obj.get("identifier") or "").lower()
    return (
        "generated-filler" in text
        or "example.invalid" in text
        or "-fill-" in identifier
        or ": source http://" in text
        or ": source https://" in text
        or ("statute section" in name and len(text) < 240)
    )


def get_source_url(obj: Dict[str, object]) -> str:
    for key in ("sourceUrl", "url", "sameAs"):
        raw = str(obj.get(key) or "").strip()
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
    return ""


def load_webarch_results(path: Path) -> Dict[str, Dict[str, object]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: Dict[str, Dict[str, object]] = {}
    for row in payload.get("results", []):
        st = str(row.get("state") or "").upper().strip()
        if st:
            out[st] = {
                "success": bool(row.get("success", False)),
                "method": str(row.get("method") or ""),
            }
    return out


def read_state_row(path: Path, state: str, webarch: Dict[str, Dict[str, object]]) -> StateGapRow:
    if not path.exists():
        wr = webarch.get(state, {})
        return StateGapRow(
            state=state,
            file_exists=False,
            records_total=0,
            real_rows=0,
            synthetic_rows=0,
            real_ratio=0.0,
            unique_source_urls=0,
            unique_domains=0,
            webarch_success=bool(wr.get("success", False)),
            webarch_method=str(wr.get("method") or ""),
        )

    total = 0
    real = 0
    synth = 0
    urls = set()
    domains = set()

    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                obj = json.loads(line)
            except Exception:
                synth += 1
                continue
            if not isinstance(obj, dict):
                synth += 1
                continue

            url = get_source_url(obj)
            if url:
                urls.add(url)
                domain = urlparse(url).netloc.lower().strip()
                if domain:
                    domains.add(domain)

            if is_synthetic_row(obj):
                synth += 1
            else:
                real += 1

    wr = webarch.get(state, {})
    return StateGapRow(
        state=state,
        file_exists=True,
        records_total=total,
        real_rows=real,
        synthetic_rows=synth,
        real_ratio=(real / total) if total else 0.0,
        unique_source_urls=len(urls),
        unique_domains=len(domains),
        webarch_success=bool(wr.get("success", False)),
        webarch_method=str(wr.get("method") or ""),
    )


def build_summary(rows: Sequence[StateGapRow]) -> Dict[str, object]:
    total_states = len(rows)
    missing = [r.state for r in rows if not r.file_exists]
    below40 = [r.state for r in rows if r.records_total < 40]
    low_real_ratio = [r.state for r in rows if r.real_ratio < 0.5]
    low_unique_urls = [r.state for r in rows if r.unique_source_urls < 20]
    webarch_fail = [r.state for r in rows if not r.webarch_success]

    return {
        "states_total": total_states,
        "missing_files": missing,
        "below_40_records": below40,
        "low_real_ratio_below_0_5": low_real_ratio,
        "low_unique_source_urls_below_20": low_unique_urls,
        "webarch_failed": webarch_fail,
        "records_total": sum(r.records_total for r in rows),
        "real_rows_total": sum(r.real_rows for r in rows),
        "synthetic_rows_total": sum(r.synthetic_rows for r in rows),
        "avg_real_ratio": round(sum(r.real_ratio for r in rows) / total_states, 3) if total_states else 0.0,
        "avg_unique_source_urls": round(sum(r.unique_source_urls for r in rows) / total_states, 2) if total_states else 0.0,
    }


def render_markdown(rows: Sequence[StateGapRow], summary: Dict[str, object], top_n: int) -> str:
    by_real_ratio = sorted(rows, key=lambda r: (r.real_ratio, r.real_rows, r.records_total, r.state))
    by_url_depth = sorted(rows, key=lambda r: (r.unique_source_urls, r.real_rows, r.records_total, r.state))

    lines: List[str] = []
    lines.append("# State Laws Corpus Gap Report (50 States)")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- States: **{summary['states_total']}**")
    lines.append(f"- Total rows: **{summary['records_total']}**")
    lines.append(f"- Estimated real rows: **{summary['real_rows_total']}**")
    lines.append(f"- Estimated synthetic rows: **{summary['synthetic_rows_total']}**")
    lines.append(f"- Avg real ratio: **{summary['avg_real_ratio']}**")
    lines.append(f"- Avg unique source URLs/state: **{summary['avg_unique_source_urls']}**")
    lines.append(f"- Missing files: `{', '.join(summary['missing_files']) if summary['missing_files'] else 'None'}`")
    lines.append(f"- Below 40 rows: `{', '.join(summary['below_40_records']) if summary['below_40_records'] else 'None'}`")
    lines.append(f"- Real ratio < 0.5: `{', '.join(summary['low_real_ratio_below_0_5']) if summary['low_real_ratio_below_0_5'] else 'None'}`")
    lines.append(f"- Unique source URLs < 20: `{', '.join(summary['low_unique_source_urls_below_20']) if summary['low_unique_source_urls_below_20'] else 'None'}`")
    lines.append(f"- Web-archiving failed: `{', '.join(summary['webarch_failed']) if summary['webarch_failed'] else 'None'}`")
    lines.append("")

    lines.append(f"## Top {top_n} Lowest Real-Ratio States")
    lines.append("")
    lines.append("| State | Records | Real | Synthetic | Real Ratio | Unique URLs | Unique Domains | WebArch |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|:---:|")
    for r in by_real_ratio[:top_n]:
        lines.append(
            f"| {r.state} | {r.records_total} | {r.real_rows} | {r.synthetic_rows} | {r.real_ratio:.3f} | {r.unique_source_urls} | {r.unique_domains} | {'Yes' if r.webarch_success else 'No'} |"
        )
    lines.append("")

    lines.append(f"## Top {top_n} Lowest URL-Depth States")
    lines.append("")
    lines.append("| State | Unique URLs | Unique Domains | Records | Real Ratio | WebArch |")
    lines.append("|---|---:|---:|---:|---:|:---:|")
    for r in by_url_depth[:top_n]:
        lines.append(
            f"| {r.state} | {r.unique_source_urls} | {r.unique_domains} | {r.records_total} | {r.real_ratio:.3f} | {'Yes' if r.webarch_success else 'No'} |"
        )
    lines.append("")

    lines.append("## Per-State Table")
    lines.append("")
    lines.append("| State | Records | Real | Synthetic | Real Ratio | Unique URLs | Unique Domains | WebArch | Method |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|:---:|---|")
    for r in sorted(rows, key=lambda x: x.state):
        lines.append(
            f"| {r.state} | {r.records_total} | {r.real_rows} | {r.synthetic_rows} | {r.real_ratio:.3f} | {r.unique_source_urls} | {r.unique_domains} | {'Yes' if r.webarch_success else 'No'} | {r.webarch_method or '-'} |"
        )

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    jsonld_dir = Path(args.jsonld_dir).expanduser().resolve()
    verify_report = Path(args.verify_report).expanduser().resolve() if args.verify_report else None

    webarch = load_webarch_results(verify_report) if verify_report else {}
    rows = [
        read_state_row(jsonld_dir / f"STATE-{state}.jsonld", state, webarch)
        for state in STATES_50
    ]

    summary = build_summary(rows)
    payload = {
        "summary": summary,
        "rows": [r.to_dict() for r in rows],
    }

    print(json.dumps(summary, indent=2, sort_keys=True))

    if args.output_json:
        out_json = Path(args.output_json).expanduser().resolve()
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote_json: {out_json}")

    if args.output_md:
        out_md = Path(args.output_md).expanduser().resolve()
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(render_markdown(rows, summary, max(1, int(args.top_n))), encoding="utf-8")
        print(f"wrote_md: {out_md}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
