"""State civil/criminal procedure-rules scraper orchestration.

This module reuses the state-laws scraping pipeline, then keeps only
records that match civil/criminal procedure rule patterns.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .state_laws_scraper import US_STATES, list_state_jurisdictions, scrape_state_laws

logger = logging.getLogger(__name__)

_CIVIL_PATTERNS = [
    re.compile(r"rules?\s+of\s+civil\s+procedure", re.IGNORECASE),
    re.compile(r"civil\s+procedure", re.IGNORECASE),
    re.compile(r"code\s+of\s+civil\s+procedure", re.IGNORECASE),
    re.compile(r"civil\s+practice", re.IGNORECASE),
    re.compile(r"civil\s+actions?", re.IGNORECASE),
    re.compile(r"rules?\s+of\s+court", re.IGNORECASE),
]

_CRIMINAL_PATTERNS = [
    re.compile(r"rules?\s+of\s+criminal\s+procedure", re.IGNORECASE),
    re.compile(r"criminal\s+procedure", re.IGNORECASE),
    re.compile(r"code\s+of\s+criminal\s+procedure", re.IGNORECASE),
    re.compile(r"criminal\s+practice", re.IGNORECASE),
    re.compile(r"criminal\s+actions?", re.IGNORECASE),
]


def _signal_text(statute: Dict[str, Any]) -> str:
    fields: List[str] = []
    is_part_of = statute.get("isPartOf")
    if isinstance(is_part_of, dict):
        name = is_part_of.get("name")
        if isinstance(name, str):
            fields.append(name)

    for key in [
        "code_name",
        "name",
        "titleName",
        "chapterName",
        "sectionName",
        "legislationType",
        "official_cite",
        "section_name",
        "full_text",
        "text",
        "source_url",
    ]:
        value = statute.get(key)
        if isinstance(value, str):
            fields.append(value)

    return "\n".join(v for v in fields if v)


def _classify_procedure_family(statute: Dict[str, Any]) -> Optional[str]:
    signal = _signal_text(statute)
    civil = any(pattern.search(signal) for pattern in _CIVIL_PATTERNS)
    criminal = any(pattern.search(signal) for pattern in _CRIMINAL_PATTERNS)

    if civil and criminal:
        return "civil_and_criminal_procedure"
    if civil:
        return "civil_procedure"
    if criminal:
        return "criminal_procedure"
    return None


def _resolve_output_dir(output_dir: Optional[str] = None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    return (Path.home() / ".ipfs_datasets" / "state_procedure_rules").resolve()


def _write_jsonld_files(filtered_data: List[Dict[str, Any]], output_dir: Path) -> List[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: List[str] = []

    for state_block in filtered_data:
        state_code = str(state_block.get("state_code") or "").strip().upper()
        statutes = state_block.get("statutes") or []
        if not state_code or not isinstance(statutes, list):
            continue

        out_path = output_dir / f"STATE-{state_code}.jsonld"
        lines = 0
        with out_path.open("w", encoding="utf-8") as handle:
            for statute in statutes:
                if not isinstance(statute, dict):
                    continue
                payload = dict(statute)
                payload["procedure_family"] = _classify_procedure_family(statute)
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                lines += 1

        if lines > 0:
            written.append(str(out_path))
        else:
            out_path.unlink(missing_ok=True)

    return written


async def list_state_procedure_rule_jurisdictions() -> Dict[str, Any]:
    return await list_state_jurisdictions()


async def scrape_state_procedure_rules(
    states: Optional[List[str]] = None,
    output_format: str = "json",
    include_metadata: bool = True,
    rate_limit_delay: float = 2.0,
    max_rules: Optional[int] = None,
    output_dir: Optional[str] = None,
    write_jsonld: bool = True,
    strict_full_text: bool = False,
    min_full_text_chars: int = 300,
    hydrate_rule_text: bool = True,
    parallel_workers: int = 6,
    per_state_retry_attempts: int = 1,
    retry_zero_rule_states: bool = True,
) -> Dict[str, Any]:
    try:
        selected_states = [s.upper() for s in (states or []) if s and str(s).upper() in US_STATES]
        if not selected_states or "ALL" in selected_states:
            selected_states = list(US_STATES.keys())

        start = time.time()
        base_result = await scrape_state_laws(
            states=selected_states,
            legal_areas=None,
            output_format=output_format,
            include_metadata=include_metadata,
            rate_limit_delay=rate_limit_delay,
            max_statutes=None,
            output_dir=None,
            write_jsonld=False,
            strict_full_text=strict_full_text,
            min_full_text_chars=min_full_text_chars,
            hydrate_statute_text=hydrate_rule_text,
            parallel_workers=parallel_workers,
            per_state_retry_attempts=per_state_retry_attempts,
            retry_zero_statute_states=retry_zero_rule_states,
        )

        raw_data = list(base_result.get("data") or [])
        filtered_data: List[Dict[str, Any]] = []
        rules_count = 0
        zero_rule_states: List[str] = []
        family_counts: Dict[str, int] = {
            "civil_procedure": 0,
            "criminal_procedure": 0,
            "civil_and_criminal_procedure": 0,
        }

        for state_block in raw_data:
            if not isinstance(state_block, dict):
                continue

            state_code = str(state_block.get("state_code") or "").upper()
            statutes = list(state_block.get("statutes") or [])
            procedure_statutes: List[Dict[str, Any]] = []

            for statute in statutes:
                if not isinstance(statute, dict):
                    continue
                family = _classify_procedure_family(statute)
                if not family:
                    continue
                enriched = dict(statute)
                enriched["procedure_family"] = family
                procedure_statutes.append(enriched)
                family_counts[family] = int(family_counts.get(family, 0)) + 1

            if max_rules and max_rules > 0:
                procedure_statutes = procedure_statutes[: int(max_rules)]

            out_block = dict(state_block)
            out_block["title"] = f"{US_STATES.get(state_code, state_code)} Procedure Rules"
            out_block["source"] = "Official State Legislative/Judicial Sources"
            out_block["statutes"] = procedure_statutes
            out_block["rules_count"] = len(procedure_statutes)
            filtered_data.append(out_block)

            rules_count += len(procedure_statutes)
            if len(procedure_statutes) == 0 and state_code:
                zero_rule_states.append(state_code)

        jsonld_paths: List[str] = []
        jsonld_dir: Optional[str] = None
        if write_jsonld:
            output_root = _resolve_output_dir(output_dir)
            jsonld_root = output_root / "state_procedure_rules_jsonld"
            jsonld_paths = _write_jsonld_files(filtered_data, jsonld_root)
            jsonld_dir = str(jsonld_root)

        elapsed = time.time() - start
        metadata = {
            "states_scraped": selected_states,
            "states_count": len(selected_states),
            "rules_count": rules_count,
            "family_counts": family_counts,
            "elapsed_time_seconds": elapsed,
            "scraped_at": datetime.now().isoformat(),
            "rate_limit_delay": rate_limit_delay,
            "parallel_workers": int(parallel_workers),
            "per_state_retry_attempts": int(per_state_retry_attempts),
            "retry_zero_rule_states": bool(retry_zero_rule_states),
            "strict_full_text": bool(strict_full_text),
            "min_full_text_chars": int(min_full_text_chars),
            "hydrate_rule_text": bool(hydrate_rule_text),
            "zero_rule_states": sorted(set(zero_rule_states)) if zero_rule_states else None,
            "jsonld_dir": jsonld_dir,
            "jsonld_files": jsonld_paths if jsonld_paths else None,
            "base_status": base_result.get("status"),
            "base_metadata": base_result.get("metadata") if include_metadata else None,
        }

        status = "success"
        if base_result.get("status") in {"error", "partial_success"}:
            status = "partial_success"
        if rules_count == 0:
            status = "partial_success"

        return {
            "status": status,
            "data": filtered_data,
            "metadata": metadata,
            "output_format": output_format,
        }

    except Exception as exc:
        logger.error("State procedure-rules scraping failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "data": [],
            "metadata": {},
        }


__all__ = [
    "list_state_procedure_rule_jurisdictions",
    "scrape_state_procedure_rules",
]
