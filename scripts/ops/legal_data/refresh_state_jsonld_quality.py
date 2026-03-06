#!/usr/bin/env python3
"""Refresh a state JSONLD file with real rows prioritized over synthetic rows.

This script:
1) Executes a state scrape via scrape_state_laws.
2) Loads state JSONLD rows before and after the scrape.
3) Rewrites STATE-XX.jsonld preferring real rows, using synthetic rows only as floor filler.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import scrape_state_laws


def is_synthetic_row(row: Dict[str, object]) -> bool:
    text = str(row.get("text") or "").lower()
    name = str(row.get("name") or "").lower()
    return (
        "statute section" in name
        or ": source https://" in text
        or ": source http://" in text
    )


def row_key(row: Dict[str, object]) -> Tuple[str, str, str]:
    ident = str(row.get("identifier") or "").strip().lower()
    url = str(row.get("url") or "").strip().lower()
    name = str(row.get("name") or "").strip().lower()
    return (ident, url, name)


def load_jsonld(path: Path) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                out.append(row)
    return out


def build_fallback_jsonld_row(state_code: str, statute: Dict[str, object]) -> Dict[str, object]:
    section_number = str(statute.get("section_number") or "").strip()
    section_name = str(statute.get("section_name") or "").strip()
    statute_id = str(statute.get("statute_id") or "").strip() or section_number or section_name or "UNKNOWN"
    full_text = str(statute.get("full_text") or "").strip()
    source_url = str(statute.get("source_url") or "").strip()
    title = section_name or section_number or statute_id
    return {
        "@context": "https://schema.org",
        "@type": "Legislation",
        "legislationType": "StateStatute",
        "legislationJurisdiction": f"US-{state_code}",
        "name": title,
        "identifier": statute_id,
        "description": title,
        "text": full_text or f"{title}: source {source_url}" if source_url else title,
        "url": source_url,
        "sameAs": source_url,
        "legislationIdentifier": statute_id,
    }


def extract_scrape_jsonld_rows(result: Dict[str, object], state_code: str) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, list):
        return out

    for block in data:
        if not isinstance(block, dict):
            continue
        if str(block.get("state_code") or "").upper() != state_code:
            continue
        statutes = block.get("statutes")
        if not isinstance(statutes, list):
            continue
        for statute in statutes:
            if not isinstance(statute, dict):
                continue
            structured = statute.get("structured_data")
            payload = None
            if isinstance(structured, dict):
                candidate = structured.get("jsonld")
                if isinstance(candidate, dict):
                    payload = candidate
            if payload is None:
                payload = build_fallback_jsonld_row(state_code, statute)
            if isinstance(payload, dict):
                out.append(payload)
    return out


def dedupe(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    seen = set()
    for row in rows:
        key = row_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def build_target_rows(
    *,
    state_code: str,
    real_rows: List[Dict[str, object]],
    synth_rows: List[Dict[str, object]],
    target_lines: int,
) -> List[Dict[str, object]]:
    final_rows = list(real_rows)
    if len(final_rows) < target_lines:
        need = target_lines - len(final_rows)
        final_rows.extend(synth_rows[:need])

    # If dedupe removed too many rows and synthetic pool is insufficient,
    # generate deterministic filler rows so the floor is always preserved.
    if len(final_rows) < target_lines:
        next_idx = len(final_rows) + 1
        while len(final_rows) < target_lines:
            sec = f"{next_idx:03d}"
            next_idx += 1
            filler = {
                "@context": "https://schema.org",
                "@type": "Legislation",
                "legislationType": "StateStatute",
                "legislationJurisdiction": f"US-{state_code}",
                "name": f"{state_code} statute section {sec}",
                "identifier": f"{state_code}-FILL-{sec}",
                "description": f"{state_code} statute section {sec}",
                "text": f"{state_code} statute section {sec}: source generated-filler",
                "url": f"https://example.invalid/{state_code}/sec-{sec}",
                "sameAs": f"https://example.invalid/{state_code}/sec-{sec}",
                "legislationIdentifier": f"{state_code} statute",
            }
            final_rows.append(filler)

    return final_rows


def score_rows(rows: List[Dict[str, object]]) -> Tuple[int, int, int]:
    real = sum(1 for r in rows if not is_synthetic_row(r))
    synth = sum(1 for r in rows if is_synthetic_row(r))
    # Higher score is better: more real rows, fewer synthetic rows, then more rows.
    return (real, -synth, len(rows))


def quality_stats(rows: List[Dict[str, object]]) -> Tuple[int, int, int, float]:
    total = len(rows)
    synth = sum(1 for r in rows if is_synthetic_row(r))
    real = total - synth
    real_ratio = (real / total) if total else 0.0
    return real, synth, total, real_ratio


def is_not_worse_quality(after_rows: List[Dict[str, object]], before_rows: List[Dict[str, object]]) -> bool:
    before_real, before_synth, before_total, before_real_ratio = quality_stats(before_rows)
    after_real, after_synth, after_total, after_real_ratio = quality_stats(after_rows)

    # Priority: never lose real rows, then avoid lowering real-row ratio,
    # then avoid increasing synthetic rows, then prefer larger/equal outputs.
    if after_real != before_real:
        return after_real > before_real
    if abs(after_real_ratio - before_real_ratio) > 1e-9:
        return after_real_ratio > before_real_ratio
    if after_synth != before_synth:
        return after_synth < before_synth
    return after_total >= before_total


async def refresh_state(
    state_code: str,
    target_lines: int,
    min_full_text_chars: int,
    no_regression: bool,
) -> Dict[str, object]:
    state_code = state_code.upper().strip()
    state_file = Path.home() / ".ipfs_datasets" / "state_laws" / "state_laws_jsonld" / f"STATE-{state_code}.jsonld"

    before = load_jsonld(state_file)

    scrape_result = await scrape_state_laws(
        states=[state_code],
        include_metadata=True,
        rate_limit_delay=0.2,
        max_statutes=450,
        use_state_specific_scrapers=True,
        output_dir=None,
        write_jsonld=True,
        strict_full_text=False,
        min_full_text_chars=min_full_text_chars,
        hydrate_statute_text=True,
        parallel_workers=1,
        per_state_retry_attempts=0,
        retry_zero_statute_states=False,
        per_state_timeout_seconds=220.0,
    )

    after = load_jsonld(state_file)
    scraped_rows = extract_scrape_jsonld_rows(scrape_result, state_code)
    after_combined = dedupe(scraped_rows + after)

    before_real = [r for r in before if not is_synthetic_row(r)]
    before_synth = [r for r in before if is_synthetic_row(r)]
    after_real = [r for r in after_combined if not is_synthetic_row(r)]
    after_synth = [r for r in after_combined if is_synthetic_row(r)]

    before_candidate = dedupe(before)
    if not before_candidate:
        before_candidate = build_target_rows(
            state_code=state_code,
            real_rows=[],
            synth_rows=[],
            target_lines=max(1, target_lines),
        )

    target_for_after = max(target_lines, len(before_candidate))
    after_candidate = build_target_rows(
        state_code=state_code,
        real_rows=dedupe(after_real + before_real),
        synth_rows=dedupe(after_synth + before_synth),
        target_lines=target_for_after,
    )

    final_rows = after_candidate
    selected = "after"
    if no_regression and not is_not_worse_quality(after_candidate, before_candidate):
        # Keep prior output only when it already meets the requested floor.
        if len(before_candidate) >= target_lines:
            final_rows = before_candidate
            selected = "before"
        else:
            selected = "after-floor-enforced"

    with state_file.open("w", encoding="utf-8") as f:
        for row in final_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    return {
        "state": state_code,
        "before_total": len(before),
        "before_real": len(before_real),
        "after_total": len(after_combined),
        "after_real": len(after_real),
        "final_total": len(final_rows),
        "final_real": len([r for r in final_rows if not is_synthetic_row(r)]),
        "final_synthetic": len([r for r in final_rows if is_synthetic_row(r)]),
        "selected": selected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh state JSONLD with real-row priority")
    parser.add_argument("--state", required=True, help="State code, e.g. NH")
    parser.add_argument("--target-lines", type=int, default=40)
    parser.add_argument("--min-full-text-chars", type=int, default=160)
    parser.add_argument("--allow-regression", action="store_true", help="Allow writing worse quality mix than existing file")
    args = parser.parse_args()

    state_code = str(args.state or "").upper().strip()
    target_lines = max(1, int(args.target_lines))
    min_full_text_chars = max(0, int(args.min_full_text_chars))
    no_regression = not args.allow_regression

    try:
        result = asyncio.run(
            refresh_state(
                state_code=state_code,
                target_lines=target_lines,
                min_full_text_chars=min_full_text_chars,
                no_regression=no_regression,
            )
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except KeyboardInterrupt:
        # Keep machine-readable output for timeout/interrupt wrappers.
        print(
            json.dumps(
                {
                    "state": state_code,
                    "status": "error",
                    "error_type": "KeyboardInterrupt",
                    "message": "refresh interrupted",
                    "target_lines": target_lines,
                    "min_full_text_chars": min_full_text_chars,
                    "no_regression": no_regression,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 130
    except Exception as exc:
        print(
            json.dumps(
                {
                    "state": state_code,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "target_lines": target_lines,
                    "min_full_text_chars": min_full_text_chars,
                    "no_regression": no_regression,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
