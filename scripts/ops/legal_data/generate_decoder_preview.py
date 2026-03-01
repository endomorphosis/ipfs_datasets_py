#!/usr/bin/env python3
"""Generate markdown decoder previews from conversion records.

This utility can force preview rows to use hybrid decoded text instead of the
pipeline's selected final output, which is useful for method-focused review.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _fmt(v: Optional[float]) -> str:
    if v is None:
        return "None"
    return f"{v:.16f}".rstrip("0").rstrip(".")


def _pick_preview_text(rec: Dict[str, Any], mode: str) -> Tuple[Optional[str], Optional[str], Optional[float]]:
    if mode == "hybrid":
        txt = rec.get("hybrid_roundtrip_text")
        cos = rec.get("semantic_similarity_hybrid")
        origin = "hybrid"
        if isinstance(txt, str) and txt.strip():
            return txt.strip(), origin, float(cos) if isinstance(cos, (int, float)) else None
        return None, None, None

    txt = rec.get("final_decoded_text")
    origin = rec.get("final_decoded_text_origin")
    cos = rec.get("semantic_similarity_final_decoded")
    if isinstance(txt, str) and txt.strip():
        return txt.strip(), str(origin) if origin else None, float(cos) if isinstance(cos, (int, float)) else None
    return None, None, None


def _build_lines(records: List[Dict[str, Any]], mode: str, max_rows: int) -> List[str]:
    kept: List[Tuple[Dict[str, Any], str, str, Optional[float]]] = []
    for rec in records:
        text, origin, cos = _pick_preview_text(rec, mode)
        if not text:
            continue
        kept.append((rec, text, origin or "none", cos))

    if max_rows > 0:
        kept = kept[:max_rows]

    cos_vals = [c for (_, _, _, c) in kept if isinstance(c, float)]
    decoder_enabled = any(bool(rec.get("llm_decoder_pass_applied")) for rec, _, _, _ in kept)
    decoder_applied_count = sum(1 for rec, _, _, _ in kept if bool(rec.get("llm_decoder_pass_applied")))
    decoder_rejected_count = sum(
        1
        for rec, _, _, _ in kept
        if isinstance(rec.get("llm_decoder_pass_notes"), str)
        and "rejected" in rec.get("llm_decoder_pass_notes", "")
    )

    lines: List[str] = []
    lines.append("# Constitution Final Decoder Preview")
    lines.append("")
    lines.append(f"- preview mode: {mode}")
    lines.append(f"- decoder enabled: {decoder_enabled}")
    lines.append(f"- decoder applied count: {decoder_applied_count}")
    lines.append(f"- decoder rejected count: {decoder_rejected_count}")
    lines.append(f"- final decoded similarity mean: {_fmt(mean(cos_vals) if cos_vals else None)}")

    by_origin: Dict[str, int] = {}
    for _, _, origin, _ in kept:
        by_origin[origin] = by_origin.get(origin, 0) + 1
    lines.append(f"- origin counts in preview: {by_origin}")
    lines.append("")

    for idx, (rec, text, origin, cos) in enumerate(kept, start=1):
        lines.append(f"## {idx}. `{rec.get('source_id', 'unknown')}`")
        lines.append(f"- original: {rec.get('text', '')}")
        lines.append(f"- baseline origin: {origin}")
        lines.append(f"- final decoded: {text}")
        lines.append(f"- decoder note: {rec.get('llm_decoder_pass_notes')}")
        lines.append(f"- final cosine: {_fmt(cos)}")
        lines.append("")

    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate markdown decoder preview from conversion records.")
    ap.add_argument("--records", required=True, help="Path to records.jsonl")
    ap.add_argument("--report", default="", help="Optional report.json path (reserved for future enrichments)")
    ap.add_argument("--output", required=True, help="Output markdown path")
    ap.add_argument(
        "--mode",
        choices=["final", "hybrid"],
        default="final",
        help="`final` uses final_decoded_text; `hybrid` forces hybrid_roundtrip_text rows only.",
    )
    ap.add_argument("--max-rows", type=int, default=50, help="Maximum rows to include (0 = all)")
    args = ap.parse_args()

    records_path = Path(args.records)
    if not records_path.exists():
        raise SystemExit(f"Records file not found: {records_path}")

    if args.report:
        report_path = Path(args.report)
        if report_path.exists():
            _ = _load_json(report_path)

    records = _load_jsonl(records_path)
    lines = _build_lines(records, mode=args.mode, max_rows=int(args.max_rows))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"WROTE {out}")


if __name__ == "__main__":
    main()
