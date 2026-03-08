#!/usr/bin/env python3
"""Page-level gap audit for state-law JSON-LD corpora.

Focuses on per-page/path quality signals:
- duplicate source URLs reused across many rows
- placeholder/synthetic rows
- short-text rows likely lacking substantive law content
- weak states ranked by real-ratio and URL concentration
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence
from urllib.parse import urlparse

STATES_50 = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]


@dataclass
class RowRecord:
    state: str
    url: str
    text_len: int
    synthetic: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit page-level gaps in state-law corpus")
    parser.add_argument(
        "--jsonld-dir",
        default=str(Path.home() / ".ipfs_datasets/state_laws/state_laws_jsonld"),
        help="Directory containing STATE-XX.jsonld files",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Optional JSON output file",
    )
    parser.add_argument(
        "--output-md",
        default="",
        help="Optional Markdown output file",
    )
    parser.add_argument(
        "--top-states",
        type=int,
        default=12,
        help="How many weak states to highlight",
    )
    parser.add_argument(
        "--top-pages",
        type=int,
        default=12,
        help="How many problematic pages to show per weak state",
    )
    return parser.parse_args()


def is_synthetic_row(name: str, text: str, ident: str) -> bool:
    lname = (name or "").lower()
    ltext = (text or "").lower()
    lident = (ident or "").lower()
    return (
        "generated-filler" in ltext
        or "example.invalid" in ltext
        or "-fill-" in lident
        or ": source http://" in ltext
        or ": source https://" in ltext
        or ("statute section" in lname and len(ltext) < 240)
    )


def pick_url(obj: Dict[str, object]) -> str:
    for key in ("sourceUrl", "url", "sameAs"):
        val = str(obj.get(key) or "").strip()
        if val.startswith("http://") or val.startswith("https://"):
            return val
    return ""


def load_records(jsonld_dir: Path) -> List[RowRecord]:
    rows: List[RowRecord] = []
    for st in STATES_50:
        fp = jsonld_dir / f"STATE-{st}.jsonld"
        if not fp.exists():
            continue
        with fp.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    rows.append(RowRecord(state=st, url="", text_len=0, synthetic=True))
                    continue
                if not isinstance(obj, dict):
                    rows.append(RowRecord(state=st, url="", text_len=0, synthetic=True))
                    continue
                name = str(obj.get("name") or "")
                text = str(obj.get("text") or "")
                ident = str(obj.get("identifier") or "")
                rows.append(
                    RowRecord(
                        state=st,
                        url=pick_url(obj),
                        text_len=len(text.strip()),
                        synthetic=is_synthetic_row(name, text, ident),
                    )
                )
    return rows


def build_payload(rows: Sequence[RowRecord], top_states: int, top_pages: int) -> Dict[str, object]:
    by_state: Dict[str, List[RowRecord]] = defaultdict(list)
    for r in rows:
        by_state[r.state].append(r)

    state_rows: List[Dict[str, object]] = []
    for st in STATES_50:
        srows = by_state.get(st, [])
        total = len(srows)
        real = sum(1 for r in srows if not r.synthetic)
        synth = sum(1 for r in srows if r.synthetic)
        short_real = sum(1 for r in srows if (not r.synthetic and r.text_len < 240))

        url_counts = Counter(r.url for r in srows if r.url)
        top_url, top_url_hits = ("", 0)
        if url_counts:
            top_url, top_url_hits = url_counts.most_common(1)[0]

        # Problematic pages: high repetition and/or mostly synthetic rows.
        by_url_rows: Dict[str, List[RowRecord]] = defaultdict(list)
        for r in srows:
            if r.url:
                by_url_rows[r.url].append(r)

        page_problems: List[Dict[str, object]] = []
        for url, items in by_url_rows.items():
            n = len(items)
            synth_n = sum(1 for x in items if x.synthetic)
            short_n = sum(1 for x in items if (not x.synthetic and x.text_len < 240))
            if n >= 2 or synth_n > 0 or short_n > 0:
                page_problems.append(
                    {
                        "url": url,
                        "domain": urlparse(url).netloc,
                        "rows": n,
                        "synthetic_rows": synth_n,
                        "short_real_rows": short_n,
                    }
                )
        page_problems.sort(key=lambda x: (-(x["synthetic_rows"]), -(x["rows"]), -(x["short_real_rows"]), x["url"]))

        state_rows.append(
            {
                "state": st,
                "total_rows": total,
                "real_rows": real,
                "synthetic_rows": synth,
                "real_ratio": round((real / total), 3) if total else 0.0,
                "short_real_rows": short_real,
                "unique_urls": len(url_counts),
                "top_url": top_url,
                "top_url_hits": top_url_hits,
                "top_url_share": round((top_url_hits / total), 3) if total else 0.0,
                "problem_pages": page_problems[:top_pages],
            }
        )

    weak_states = sorted(
        state_rows,
        key=lambda r: (r["real_ratio"], r["real_rows"], r["unique_urls"], -r["total_rows"], r["state"]),
    )[: max(1, top_states)]

    summary = {
        "states_total": len(STATES_50),
        "rows_total": sum(r["total_rows"] for r in state_rows),
        "real_total": sum(r["real_rows"] for r in state_rows),
        "synthetic_total": sum(r["synthetic_rows"] for r in state_rows),
        "avg_real_ratio": round(sum(r["real_ratio"] for r in state_rows) / len(STATES_50), 3),
        "weak_states": [r["state"] for r in weak_states],
    }

    return {
        "summary": summary,
        "states": state_rows,
        "weak_states": weak_states,
    }


def to_markdown(payload: Dict[str, object]) -> str:
    summary = payload["summary"]
    weak_states = payload["weak_states"]
    lines: List[str] = []
    lines.append("# State Law Page-Level Gap Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- States: **{summary['states_total']}**")
    lines.append(f"- Rows total: **{summary['rows_total']}**")
    lines.append(f"- Real total: **{summary['real_total']}**")
    lines.append(f"- Synthetic total: **{summary['synthetic_total']}**")
    lines.append(f"- Avg real ratio: **{summary['avg_real_ratio']}**")
    lines.append(f"- Weak states: `{', '.join(summary['weak_states'])}`")
    lines.append("")

    lines.append("## Weak States")
    lines.append("")
    lines.append("| State | Total | Real | Synthetic | Real Ratio | Unique URLs | Top URL Share | Short Real Rows |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for st in weak_states:
        lines.append(
            f"| {st['state']} | {st['total_rows']} | {st['real_rows']} | {st['synthetic_rows']} | {st['real_ratio']:.3f} | {st['unique_urls']} | {st['top_url_share']:.3f} | {st['short_real_rows']} |"
        )

    for st in weak_states:
        lines.append("")
        lines.append(f"### {st['state']} Problem Pages")
        lines.append("")
        lines.append("| URL | Domain | Rows | Synthetic Rows | Short Real Rows |")
        lines.append("|---|---|---:|---:|---:|")
        problems = st.get("problem_pages") or []
        if not problems:
            lines.append("| - | - | 0 | 0 | 0 |")
            continue
        for p in problems:
            lines.append(
                f"| {p['url']} | {p['domain']} | {p['rows']} | {p['synthetic_rows']} | {p['short_real_rows']} |"
            )

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    jsonld_dir = Path(args.jsonld_dir).expanduser().resolve()

    rows = load_records(jsonld_dir)
    payload = build_payload(rows, top_states=max(1, int(args.top_states)), top_pages=max(1, int(args.top_pages)))

    print(json.dumps(payload["summary"], indent=2, sort_keys=True))

    if args.output_json:
        out_json = Path(args.output_json).expanduser().resolve()
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote_json: {out_json}")

    if args.output_md:
        out_md = Path(args.output_md).expanduser().resolve()
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(to_markdown(payload), encoding="utf-8")
        print(f"wrote_md: {out_md}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
