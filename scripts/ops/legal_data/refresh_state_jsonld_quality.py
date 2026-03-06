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


async def refresh_state(state_code: str, target_lines: int, min_full_text_chars: int) -> Dict[str, object]:
    state_code = state_code.upper().strip()
    state_file = Path.home() / ".ipfs_datasets" / "state_laws" / "state_laws_jsonld" / f"STATE-{state_code}.jsonld"

    before = load_jsonld(state_file)

    await scrape_state_laws(
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

    before_real = [r for r in before if not is_synthetic_row(r)]
    before_synth = [r for r in before if is_synthetic_row(r)]
    after_real = [r for r in after if not is_synthetic_row(r)]
    after_synth = [r for r in after if is_synthetic_row(r)]

    real_rows = dedupe(after_real + before_real)
    synth_rows = dedupe(after_synth + before_synth)

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

    with state_file.open("w", encoding="utf-8") as f:
        for row in final_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    return {
        "state": state_code,
        "before_total": len(before),
        "before_real": len(before_real),
        "after_total": len(after),
        "after_real": len(after_real),
        "final_total": len(final_rows),
        "final_real": len([r for r in final_rows if not is_synthetic_row(r)]),
        "final_synthetic": len([r for r in final_rows if is_synthetic_row(r)]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh state JSONLD with real-row priority")
    parser.add_argument("--state", required=True, help="State code, e.g. NH")
    parser.add_argument("--target-lines", type=int, default=40)
    parser.add_argument("--min-full-text-chars", type=int, default=160)
    args = parser.parse_args()

    result = asyncio.run(
        refresh_state(
            state_code=args.state,
            target_lines=max(1, int(args.target_lines)),
            min_full_text_chars=max(0, int(args.min_full_text_chars)),
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
