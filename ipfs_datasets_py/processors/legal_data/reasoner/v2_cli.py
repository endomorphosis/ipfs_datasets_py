"""CLI for hybrid legal V2 pipeline orchestration.

This module keeps execution logic inside the package and can be called from
ops scripts or directly via `python -m`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .hybrid_v2_blueprint import run_v2_pipeline_with_defaults


def _load_sentences_from_jsonl(path: Path, sentence_field: str) -> List[str]:
    sentences: List[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if sentence_field in row and str(row[sentence_field]).strip():
                sentences.append(str(row[sentence_field]).strip())
    return sentences


def run_v2_cli(
    *,
    sentences: Iterable[str],
    jurisdiction: str,
    enable_optimizer: bool,
    enable_kg: bool,
    enable_prover: bool,
    prover_backend_id: str,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    failures = 0

    for sentence in sentences:
        text = str(sentence or "").strip()
        if not text:
            continue
        try:
            result = run_v2_pipeline_with_defaults(
                text,
                jurisdiction=jurisdiction,
                enable_optimizer=enable_optimizer,
                enable_kg=enable_kg,
                enable_prover=enable_prover,
                prover_backend_id=prover_backend_id,
            )
            rows.append(
                {
                    "sentence": text,
                    "status": "ok",
                    "norm_count": len((result.get("ir").norms if result.get("ir") else {})),
                    "frame_count": len((result.get("ir").frames if result.get("ir") else {})),
                    "optimizer_applied": bool((result.get("optimizer_report") or {}).get("applied")),
                    "kg_applied": bool((result.get("kg_report") or {}).get("applied")),
                    "prover_applied": bool((result.get("prover_report") or {}).get("applied")),
                    "dcec_formula_count": len(result.get("dcec") or []),
                    "tdfol_formula_count": len(result.get("tdfol") or []),
                }
            )
        except Exception as exc:  # pragma: no cover - defensive path
            failures += 1
            rows.append(
                {
                    "sentence": text,
                    "status": "error",
                    "error": str(exc),
                }
            )

    return {
        "summary": {
            "total": len(rows),
            "ok": sum(1 for r in rows if r.get("status") == "ok"),
            "error": failures,
            "jurisdiction": jurisdiction,
            "enable_optimizer": bool(enable_optimizer),
            "enable_kg": bool(enable_kg),
            "enable_prover": bool(enable_prover),
            "prover_backend_id": prover_backend_id,
        },
        "results": rows,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run hybrid legal V2 pipeline for one or more CNL sentences.")
    p.add_argument("--sentence", action="append", default=[], help="CNL sentence (repeatable).")
    p.add_argument("--input-jsonl", default="", help="Optional JSONL input containing sentence records.")
    p.add_argument("--sentence-field", default="sentence", help="JSONL field name that contains sentence text.")
    p.add_argument("--jurisdiction", default="us/federal", help="Jurisdiction label.")
    p.add_argument("--disable-optimizer", action="store_true", help="Disable optimizer hook.")
    p.add_argument("--disable-kg", action="store_true", help="Disable KG hook.")
    p.add_argument("--disable-prover", action="store_true", help="Disable prover hook.")
    p.add_argument("--prover-backend-id", default="mock_smt", help="Prover backend ID for default registry.")
    p.add_argument("--output-json", default="", help="Optional output JSON path.")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    sentences: List[str] = [s for s in args.sentence if str(s).strip()]
    if args.input_jsonl:
        sentences.extend(_load_sentences_from_jsonl(Path(args.input_jsonl), args.sentence_field))

    if not sentences:
        parser.error("Provide at least one --sentence or --input-jsonl with valid sentence records.")

    payload = run_v2_cli(
        sentences=sentences,
        jurisdiction=args.jurisdiction,
        enable_optimizer=not args.disable_optimizer,
        enable_kg=not args.disable_kg,
        enable_prover=not args.disable_prover,
        prover_backend_id=args.prover_backend_id,
    )

    if args.output_json:
        out_path = Path(args.output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True),
            encoding="utf-8",
        )

    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if payload["summary"]["error"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
