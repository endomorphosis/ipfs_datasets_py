#!/usr/bin/env python3
"""Audit Bluebook citation matches for exact-anchor guarantee compliance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.processors.legal_scrapers import (
    BluebookCitationResolver,
    audit_bluebook_exact_anchor_guarantees_for_documents,
)


def _parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run exact-anchor Bluebook citation guarantee audit against a JSON document bundle."
        )
    )
    parser.add_argument("--input", required=True, help="Path to input JSON. Accepts a list of documents or an object with 'documents'.")
    parser.add_argument("--state-code", default="", help="Optional state code hint (e.g., OR, MN).")
    parser.add_argument("--no-exhaustive", action="store_true", help="Disable exhaustive fallback query pass.")
    parser.add_argument(
        "--allow-non-exact",
        action="store_true",
        help="Use permissive resolver mode (legacy matching) before auditing guarantees.",
    )
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    parser.add_argument("--report-output", default="", help="Optional text report output path.")
    parser.add_argument("--json", action="store_true", help="Print JSON payload to stdout.")
    return parser.parse_args(args)


def _load_documents(input_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        documents = payload.get("documents")
        if isinstance(documents, list):
            return [dict(item) for item in documents if isinstance(item, dict)]
        return [dict(payload)]
    return []


def _render_text_report(audit: dict[str, Any]) -> str:
    lines = [
        "Bluebook Exact-Anchor Guarantee Audit",
        "=" * 40,
        f"require_exact_anchor: {bool(audit.get('require_exact_anchor'))}",
        f"document_count: {int(audit.get('document_count') or 0)}",
        f"citation_count: {int(audit.get('citation_count') or 0)}",
        f"matched_citation_count: {int(audit.get('matched_citation_count') or 0)}",
        f"exact_anchor_match_count: {int(audit.get('exact_anchor_match_count') or 0)}",
        f"non_exact_match_count: {int(audit.get('non_exact_match_count') or 0)}",
        f"exact_anchor_match_ratio: {float(audit.get('exact_anchor_match_ratio') or 0.0):.4f}",
        "",
        "Non-Exact Matches",
        "-" * 40,
    ]
    non_exact = [dict(item) for item in list(audit.get("non_exact_matches") or []) if isinstance(item, dict)]
    if not non_exact:
        lines.append("(none)")
    else:
        for item in non_exact:
            lines.append(
                " | ".join(
                    [
                        f"doc={str(item.get('document_id') or '')}",
                        f"citation={str(item.get('citation_text') or '')}",
                        f"type={str(item.get('citation_type') or '')}",
                        f"corpus={str(item.get('corpus_key') or '')}",
                        f"method={str(item.get('resolution_method') or '')}",
                        f"quality={str(item.get('resolution_quality') or '')}",
                    ]
                )
            )
    return "\n".join(lines) + "\n"


def main(args: list[str] | None = None) -> int:
    parsed = _parse_args(args)
    input_path = Path(parsed.input).expanduser().resolve()
    documents = _load_documents(input_path)

    resolver = BluebookCitationResolver(
        allow_hf_fallback=True,
        require_exact_anchor=not bool(parsed.allow_non_exact),
    )
    audit = audit_bluebook_exact_anchor_guarantees_for_documents(
        documents,
        state_code=(str(parsed.state_code or "").strip().upper() or None),
        resolver=resolver,
        exhaustive=not bool(parsed.no_exhaustive),
    )
    audit["input_path"] = str(input_path)

    if parsed.output:
        output_path = Path(parsed.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")

    report_text = _render_text_report(audit)
    if parsed.report_output:
        report_path = Path(parsed.report_output).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")

    if parsed.json:
        print(json.dumps(audit, indent=2, ensure_ascii=False))
    else:
        print(report_text, end="")

    return 0 if int(audit.get("non_exact_match_count") or 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
