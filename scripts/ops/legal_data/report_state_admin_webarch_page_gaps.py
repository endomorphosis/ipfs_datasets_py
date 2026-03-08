#!/usr/bin/env python3
"""Page-level gap report for admin-rule web-archiving audits."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Summarize page-level gaps from admin webarch audits")
    p.add_argument(
        "--per-page-jsonl",
        action="append",
        required=True,
        help="Path to a per_page.jsonl produced by audit_state_admin_webarch_gaps.py",
    )
    p.add_argument("--output-json", required=True)
    p.add_argument("--output-md", required=True)
    p.add_argument("--top-states", type=int, default=12)
    p.add_argument("--top-pages", type=int, default=12)
    return p.parse_args()


def _load_rows(paths: List[Path]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for path in paths:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if not isinstance(row, dict):
                    continue
                key = (
                    str(row.get("state_code") or ""),
                    str(row.get("url") or ""),
                    str(row.get("title") or ""),
                    bool(row.get("success")),
                )
                if key in seen:
                    continue
                seen.add(key)
                out.append(row)
    return out


def _category(row: Dict[str, Any]) -> str:
    if bool(row.get("substantive_admin")):
        return "candidate_substantive"
    if bool(row.get("blocked_or_transport_error")):
        return "blocked_or_transport"
    if bool(row.get("success")) and int(row.get("text_len") or 0) < 240:
        return "thin_success"
    if bool(row.get("success")):
        return "non_substantive_success"
    return "other_failure"


def _sort_pages(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    priority = {
        "blocked_or_transport": 0,
        "non_substantive_success": 1,
        "thin_success": 2,
        "candidate_substantive": 3,
        "other_failure": 4,
    }
    return sorted(
        rows,
        key=lambda r: (
            priority.get(r["page_category"], 99),
            -(len(r.get("error_messages") or [])),
            -int(r.get("text_len") or 0),
            str(r.get("url") or ""),
        ),
    )


def build_payload(rows: List[Dict[str, Any]], top_states: int, top_pages: int) -> Dict[str, Any]:
    by_state: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        state = str(row.get("state_code") or "").upper().strip()
        if not state:
            continue
        enriched = dict(row)
        enriched["page_category"] = _category(row)
        by_state[state].append(enriched)

    state_rows: List[Dict[str, Any]] = []
    for state, srows in sorted(by_state.items()):
        blocked = sum(1 for r in srows if r["page_category"] == "blocked_or_transport")
        thin = sum(1 for r in srows if r["page_category"] == "thin_success")
        non_sub = sum(1 for r in srows if r["page_category"] == "non_substantive_success")
        candidate = sum(1 for r in srows if r["page_category"] == "candidate_substantive")
        success = sum(1 for r in srows if bool(r.get("success")))
        state_rows.append(
            {
                "state": state,
                "pages_total": len(srows),
                "success_pages": success,
                "blocked_pages": blocked,
                "thin_success_pages": thin,
                "non_substantive_pages": non_sub,
                "candidate_substantive_pages": candidate,
                "problem_score": blocked * 4 + non_sub * 3 + thin * 2 - candidate,
                "problem_pages": _sort_pages(srows)[:top_pages],
            }
        )

    weak_states = sorted(
        state_rows,
        key=lambda r: (-r["problem_score"], -r["blocked_pages"], -r["non_substantive_pages"], r["state"]),
    )[: max(1, top_states)]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "states_total": len(state_rows),
        "pages_total": sum(r["pages_total"] for r in state_rows),
        "blocked_pages_total": sum(r["blocked_pages"] for r in state_rows),
        "thin_success_pages_total": sum(r["thin_success_pages"] for r in state_rows),
        "non_substantive_pages_total": sum(r["non_substantive_pages"] for r in state_rows),
        "candidate_substantive_pages_total": sum(r["candidate_substantive_pages"] for r in state_rows),
        "weak_states": [r["state"] for r in weak_states],
    }
    return {"summary": summary, "states": state_rows, "weak_states": weak_states}


def to_markdown(payload: Dict[str, Any]) -> str:
    summary = payload["summary"]
    weak_states = payload["weak_states"]
    lines: List[str] = []
    lines.append("# State Admin WebArch Page Gap Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Generated: `{summary['generated_at']}`")
    lines.append(f"- States: **{summary['states_total']}**")
    lines.append(f"- Pages total: **{summary['pages_total']}**")
    lines.append(f"- Blocked pages: **{summary['blocked_pages_total']}**")
    lines.append(f"- Thin success pages: **{summary['thin_success_pages_total']}**")
    lines.append(f"- Non-substantive success pages: **{summary['non_substantive_pages_total']}**")
    lines.append(f"- Candidate substantive pages: **{summary['candidate_substantive_pages_total']}**")
    lines.append(f"- Weak states: `{', '.join(summary['weak_states'])}`")
    lines.append("")
    lines.append("## Weak States")
    lines.append("")
    lines.append("| State | Pages | Success | Blocked | Thin | Non-substantive | Candidate Substantive |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for st in weak_states:
        lines.append(
            f"| {st['state']} | {st['pages_total']} | {st['success_pages']} | {st['blocked_pages']} | {st['thin_success_pages']} | {st['non_substantive_pages']} | {st['candidate_substantive_pages']} |"
        )
    for st in weak_states:
        lines.append("")
        lines.append(f"### {st['state']} Problem Pages")
        lines.append("")
        lines.append("| Category | URL | Title | Text Len | In Corpus |")
        lines.append("|---|---|---|---:|:---:|")
        for row in st.get("problem_pages") or []:
            lines.append(
                f"| {row['page_category']} | {row.get('url','')} | {str(row.get('title') or '').replace('|',' ')} | {int(row.get('text_len') or 0)} | {'Yes' if row.get('in_existing_corpus') else 'No'} |"
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    paths = [Path(p).expanduser().resolve() for p in args.per_page_jsonl]
    rows = _load_rows(paths)
    payload = build_payload(rows, top_states=max(1, int(args.top_states)), top_pages=max(1, int(args.top_pages)))

    out_json = Path(args.output_json).expanduser().resolve()
    out_md = Path(args.output_md).expanduser().resolve()
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(to_markdown(payload), encoding="utf-8")

    print(json.dumps({"summary": payload["summary"], "output_json": str(out_json), "output_md": str(out_md)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
