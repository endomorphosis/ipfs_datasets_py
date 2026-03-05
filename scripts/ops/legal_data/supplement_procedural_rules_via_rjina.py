#!/usr/bin/env python3
"""Supplement US state procedural rules using r.jina.ai mirrored pages.

This script targets states with no matches in the existing procedural-rules
summary, fetches state legal index pages via r.jina.ai, extracts civil/criminal
procedure links, and writes supplemental records. It can also produce a merged
JSONL for downstream use.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import US_STATES

LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<url>https?://[^)]+)\)")

CIVIL_RE = re.compile(r"civil\s+procedure|code\s+of\s+civil\s+procedure|cplr|ccp", re.IGNORECASE)
CRIMINAL_RE = re.compile(r"criminal\s+procedure|code\s+of\s+criminal\s+procedure|crim", re.IGNORECASE)


def _justia_slug(state_name: str) -> str:
    slug = state_name.lower().strip().replace("&", "and")
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _rjina_fetch(url: str, timeout: int = 45) -> str:
    mirror = f"https://r.jina.ai/http://{url.replace('https://', '').replace('http://', '')}"
    resp = requests.get(mirror, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return resp.text


def _classify(label: str, url: str) -> Optional[str]:
    text = f"{label}\n{url}"
    civ = CIVIL_RE.search(text) is not None
    cri = CRIMINAL_RE.search(text) is not None
    if civ and cri:
        return "civil_and_criminal_procedure"
    if civ:
        return "civil_procedure"
    if cri:
        return "criminal_procedure"
    return None


def _extract_matches(markdown_text: str) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    for m in LINK_RE.finditer(markdown_text):
        label = m.group("label").strip()
        url = m.group("url").strip()
        family = _classify(label, url)
        if family:
            out.append((family, label, url))
    return out


def _state_seed_urls(state_code: str, state_name: str) -> List[str]:
    slug = _justia_slug(state_name)
    seeds = [f"https://law.justia.com/codes/{slug}/"]
    if state_code == "NJ":
        seeds.append("https://www.njcourts.gov/attorneys/rules-of-court")
    if state_code == "DC":
        seeds.extend([
            "https://www.dccourts.gov/superior-court/rules",
            "https://www.dccourts.gov/services/civil-matters/rules-civil-procedure",
            "https://www.dccourts.gov/services/criminal-matters/rules-criminal-procedure",
        ])
    return seeds


def _load_no_match_states(summary_path: Path) -> List[str]:
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    states = payload.get("supported_with_no_procedural_matches") or []
    return [str(s).upper() for s in states if str(s).upper() in US_STATES]


def run(
    summary_path: Path,
    output_jsonl: Path,
    merged_output_jsonl: Optional[Path],
    base_jsonl: Optional[Path],
    sleep_s: float,
) -> Dict[str, Any]:
    targets = _load_no_match_states(summary_path)
    supplemental: List[Dict[str, Any]] = []
    states_with_hits: Dict[str, int] = {}
    errors: Dict[str, str] = {}

    for state_code in targets:
        state_name = US_STATES[state_code]
        state_hits = 0
        for seed in _state_seed_urls(state_code, state_name):
            try:
                markdown = _rjina_fetch(seed)
            except Exception as exc:
                errors[f"{state_code}:{seed}"] = str(exc)
                continue

            for family, label, url in _extract_matches(markdown):
                supplemental.append(
                    {
                        "jurisdiction_code": state_code,
                        "jurisdiction_name": state_name,
                        "territory": False,
                        "procedure_family": family,
                        "ipfs_cid": None,
                        "name": label,
                        "titleName": None,
                        "chapterName": None,
                        "sectionName": label,
                        "sourceUrl": url,
                        "code_name": "supplemental_procedural_rules_rjina",
                        "text": None,
                        "record": {
                            "source": "r.jina.ai",
                            "seed_url": seed,
                            "label": label,
                            "target_url": url,
                        },
                    }
                )
                state_hits += 1

            time.sleep(max(0.0, sleep_s))

        if state_hits > 0:
            states_with_hits[state_code] = state_hits

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w", encoding="utf-8") as handle:
        for row in supplemental:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    merged_count = None
    if merged_output_jsonl and base_jsonl and base_jsonl.exists():
        merged_output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        seen = set()
        merged_rows: List[Dict[str, Any]] = []

        for path in [base_jsonl, output_jsonl]:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    key = (
                        obj.get("jurisdiction_code"),
                        obj.get("procedure_family"),
                        obj.get("sourceUrl"),
                        obj.get("name"),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    merged_rows.append(obj)

        with merged_output_jsonl.open("w", encoding="utf-8") as handle:
            for row in merged_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        merged_count = len(merged_rows)

    return {
        "status": "success",
        "targets": targets,
        "targets_count": len(targets),
        "supplemental_records": len(supplemental),
        "states_with_hits_count": len(states_with_hits),
        "states_with_hits": states_with_hits,
        "errors_count": len(errors),
        "errors_sample": dict(list(errors.items())[:20]),
        "supplemental_output": str(output_jsonl),
        "merged_output": str(merged_output_jsonl) if merged_output_jsonl else None,
        "merged_count": merged_count,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Supplement state procedural rules via r.jina.ai")
    parser.add_argument(
        "--summary-json",
        default=str(Path.home() / ".ipfs_datasets" / "state_laws" / "procedural_rules" / "us_state_procedural_rules_summary.json"),
    )
    parser.add_argument(
        "--base-jsonl",
        default=str(Path.home() / ".ipfs_datasets" / "state_laws" / "procedural_rules" / "us_state_procedural_rules.jsonl"),
    )
    parser.add_argument(
        "--output-jsonl",
        default=str(Path.home() / ".ipfs_datasets" / "state_laws" / "procedural_rules" / "us_state_procedural_rules_supplemental_rjina.jsonl"),
    )
    parser.add_argument(
        "--merged-output-jsonl",
        default=str(Path.home() / ".ipfs_datasets" / "state_laws" / "procedural_rules" / "us_state_procedural_rules_merged_with_rjina.jsonl"),
    )
    parser.add_argument("--sleep-s", type=float, default=0.1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run(
        summary_path=Path(args.summary_json).expanduser().resolve(),
        output_jsonl=Path(args.output_jsonl).expanduser().resolve(),
        merged_output_jsonl=Path(args.merged_output_jsonl).expanduser().resolve(),
        base_jsonl=Path(args.base_jsonl).expanduser().resolve(),
        sleep_s=float(args.sleep_s),
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
