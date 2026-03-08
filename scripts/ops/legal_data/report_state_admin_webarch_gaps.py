#!/usr/bin/env python3
"""Synthesize state admin web-archiving gap audits into one remediation report."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Summarize admin web-archiving gap audits")
    p.add_argument("--full-summary", required=True, help="Path to full 50-state audit summary.json")
    p.add_argument(
        "--deep-summary",
        action="append",
        default=[],
        help="Optional path(s) to deeper targeted audit summary.json files",
    )
    p.add_argument("--output-md", required=True)
    p.add_argument("--output-json", required=True)
    return p.parse_args()


def _load_states(path: Path) -> Dict[str, Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(row.get("state_code") or "").upper(): row for row in data.get("states", []) if isinstance(row, dict)}


def _best_urls(*rows: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for row in rows:
        for key in ("new_substantive_urls", "best_substantive_urls", "seed_urls"):
            for url in list(row.get(key) or []):
                text = str(url or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                out.append(text)
    return out


def _blocked_examples(*rows: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for row in rows:
        for item in list(row.get("blocked_examples") or []):
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
    return out[:5]


def _merge_state(full_row: Dict[str, Any], deep_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = [full_row] + deep_rows
    corpus_rows = max(int(row.get("corpus_rows") or 0) for row in rows)
    corpus_substantive_rows = max(int(row.get("corpus_substantive_rows") or 0) for row in rows)
    probe_success_count = max(int(row.get("probe_success_count") or 0) for row in rows)
    probe_substantive_hits = max(int(row.get("probe_substantive_hits") or 0) for row in rows)
    local_jsonld_rows = max(int(row.get("local_jsonld_rows") or 0) for row in rows)
    has_curated_seeds = any(bool(row.get("has_curated_seeds")) for row in rows)
    candidate_urls = _best_urls(*rows)
    blocked_examples = _blocked_examples(*rows)

    if corpus_substantive_rows <= 0 and probe_substantive_hits > 0:
        final_category = "corpus_gap_with_candidate_pages"
    elif probe_success_count <= 0 and blocked_examples:
        final_category = "blocked_or_transport_failures"
    elif corpus_substantive_rows <= 0 and probe_success_count > 0 and probe_substantive_hits <= 0:
        final_category = "fetchable_but_non_substantive"
    elif corpus_substantive_rows > 0 and probe_substantive_hits <= 0:
        final_category = "corpus_has_signal_but_probe_thin"
    else:
        final_category = "has_substantive_signal"

    return {
        "state_code": full_row.get("state_code"),
        "state_name": full_row.get("state_name"),
        "local_jsonld_rows": local_jsonld_rows,
        "corpus_rows": corpus_rows,
        "corpus_substantive_rows": corpus_substantive_rows,
        "probe_success_count": probe_success_count,
        "probe_substantive_hits": probe_substantive_hits,
        "has_curated_seeds": has_curated_seeds,
        "candidate_urls": candidate_urls[:8],
        "blocked_examples": blocked_examples,
        "final_category": final_category,
    }


def _render_md(summary: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    lines.append("# State Admin WebArch Gap Synthesis")
    lines.append("")
    lines.append(f"- Generated: `{summary['generated_at']}`")
    lines.append(f"- Full audit: `{summary['full_summary']}`")
    if summary["deep_summaries"]:
        lines.append("- Deep audits:")
        for path in summary["deep_summaries"]:
            lines.append(f"  - `{path}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- States with substantive corpus gaps but candidate pages found: **{summary['corpus_gap_with_candidate_pages']}**")
    lines.append(f"- States blocked by transport/access: **{summary['blocked_or_transport_failures']}**")
    lines.append(f"- States fetchable but still non-substantive: **{summary['fetchable_but_non_substantive']}**")
    lines.append(f"- States where corpus already has substantive signal: **{summary['has_or_retains_substantive_signal']}**")
    lines.append("")
    lines.append("## Priority States")
    lines.append("")
    lines.append("| State | Local JSONLD | Corpus Rows | Corpus Substantive | Probe Substantive | Final Category |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for row in rows:
        if row["final_category"] not in {
            "corpus_gap_with_candidate_pages",
            "blocked_or_transport_failures",
            "fetchable_but_non_substantive",
        }:
            continue
        lines.append(
            f"| {row['state_code']} | {row['local_jsonld_rows']} | {row['corpus_rows']} | {row['corpus_substantive_rows']} | {row['probe_substantive_hits']} | {row['final_category']} |"
        )
    lines.append("")
    lines.append("## Candidate URLs")
    lines.append("")
    for row in rows:
        if not row["candidate_urls"]:
            continue
        if row["final_category"] not in {"corpus_gap_with_candidate_pages", "has_substantive_signal", "corpus_has_signal_but_probe_thin"}:
            continue
        lines.append(f"### {row['state_code']}")
        lines.append("")
        for url in row["candidate_urls"][:5]:
            lines.append(f"- `{url}`")
        lines.append("")
    lines.append("## Blocked States")
    lines.append("")
    for row in rows:
        if row["final_category"] != "blocked_or_transport_failures":
            continue
        lines.append(f"### {row['state_code']}")
        lines.append("")
        for msg in row["blocked_examples"][:3]:
            lines.append(f"- `{msg[:180]}`")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    args = parse_args()
    full_path = Path(args.full_summary).expanduser().resolve()
    deep_paths = [Path(p).expanduser().resolve() for p in args.deep_summary]

    full_states = _load_states(full_path)
    deep_state_maps = [_load_states(path) for path in deep_paths]

    merged_rows: List[Dict[str, Any]] = []
    for state_code, full_row in sorted(full_states.items()):
        deep_rows = [m[state_code] for m in deep_state_maps if state_code in m]
        merged_rows.append(_merge_state(full_row, deep_rows))

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "full_summary": str(full_path),
        "deep_summaries": [str(path) for path in deep_paths],
        "states_total": len(merged_rows),
        "corpus_gap_with_candidate_pages": sum(1 for row in merged_rows if row["final_category"] == "corpus_gap_with_candidate_pages"),
        "blocked_or_transport_failures": sum(1 for row in merged_rows if row["final_category"] == "blocked_or_transport_failures"),
        "fetchable_but_non_substantive": sum(1 for row in merged_rows if row["final_category"] == "fetchable_but_non_substantive"),
        "has_or_retains_substantive_signal": sum(
            1
            for row in merged_rows
            if row["final_category"] in {"has_substantive_signal", "corpus_has_signal_but_probe_thin"}
        ),
    }

    out_json = Path(args.output_json).expanduser().resolve()
    out_md = Path(args.output_md).expanduser().resolve()
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({"summary": summary, "rows": merged_rows}, indent=2, sort_keys=True), encoding="utf-8")
    out_md.write_text(_render_md(summary, merged_rows), encoding="utf-8")
    print(json.dumps({"summary": summary, "output_json": str(out_json), "output_md": str(out_md)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
