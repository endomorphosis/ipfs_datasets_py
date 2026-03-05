"""State administrative-rules scraper orchestration.

This module reuses the state-laws scraping pipeline, then keeps only
administrative-rule records so the output corpus is focused on state
administrative rules/codes.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .state_laws_scraper import (
    US_STATES,
    list_state_jurisdictions,
    scrape_state_laws,
)

logger = logging.getLogger(__name__)

US_50_STATE_CODES: List[str] = [code for code in US_STATES.keys() if code != "DC"]

_ADMIN_RULE_TEXT_RE = re.compile(
    r"administrative|admin\.?\s+code|code\s+of\s+regulations|regulation|agency\s+rule|oar\b|aac\b|arc\b|nmac\b",
    re.IGNORECASE,
)


def _is_admin_rule_statute(statute: Dict[str, Any]) -> bool:
    legal_area = str(statute.get("legal_area") or "")
    code_name = str(statute.get("code_name") or "")
    section_name = str(statute.get("section_name") or statute.get("short_title") or "")
    official_cite = str(statute.get("official_cite") or "")
    source_url = str(statute.get("source_url") or "")

    haystack = " ".join([legal_area, code_name, section_name, official_cite, source_url])
    if _ADMIN_RULE_TEXT_RE.search(haystack):
        return True

    # Preserve records already tagged as regulations by state-specific scrapers.
    structured_data = statute.get("structured_data") or {}
    if isinstance(structured_data, dict):
        code_type = str(structured_data.get("code_type") or structured_data.get("type") or "")
        if code_type and _ADMIN_RULE_TEXT_RE.search(code_type):
            return True

    return False


def _resolve_admin_output_dir(output_dir: Optional[str] = None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    return (Path.home() / ".ipfs_datasets" / "state_admin_rules").resolve()


def _build_admin_fallback_jsonld_payload(*, state_code: str, state_name: str, statute: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    full_text = str(statute.get("full_text") or "").strip()
    section_number = str(statute.get("section_number") or "").strip()
    section_name = str(statute.get("section_name") or "").strip()
    code_name = str(statute.get("code_name") or "").strip()
    source_url = str(statute.get("source_url") or "").strip()
    statute_id = str(statute.get("statute_id") or "").strip() or section_number or section_name

    if not (full_text or section_name or section_number or statute_id):
        return None

    title_parts = [part for part in [state_name or state_code, code_name, section_number] if part]
    title = " - ".join(title_parts) or f"{state_code} administrative rule"

    payload: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Legislation",
        "legislationType": "StateAdministrativeRule",
        "legislationJurisdiction": f"US-{state_code}",
        "name": title,
        "identifier": statute_id or title,
        "description": section_name or full_text[:500],
        "text": full_text or section_name,
        "url": source_url,
    }

    if source_url:
        payload["sameAs"] = source_url
    if code_name:
        payload["legislationIdentifier"] = code_name

    return payload


def _write_state_admin_jsonld_files(scraped_rules: List[Dict[str, Any]], jsonld_dir: Path) -> List[str]:
    written: List[str] = []
    for state_block in scraped_rules:
        state_code = str(state_block.get("state_code") or "").strip().upper()
        state_name = str(state_block.get("state_name") or "").strip()
        statutes = state_block.get("statutes") or []
        if not state_code or not isinstance(statutes, list):
            continue

        out_path = jsonld_dir / f"STATE-{state_code}.jsonld"
        lines_written = 0
        with out_path.open("w", encoding="utf-8") as handle:
            for statute in statutes:
                if not isinstance(statute, dict):
                    continue
                structured_data = statute.get("structured_data") or {}
                payload = None
                if isinstance(structured_data, dict):
                    payload = structured_data.get("jsonld")
                if not isinstance(payload, dict):
                    payload = _build_admin_fallback_jsonld_payload(
                        state_code=state_code,
                        state_name=state_name,
                        statute=statute,
                    )
                if not isinstance(payload, dict):
                    continue
                if str(payload.get("legislationType") or "").strip() == "":
                    payload["legislationType"] = "StateAdministrativeRule"
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                lines_written += 1

        if lines_written > 0:
            written.append(str(out_path))
        else:
            out_path.unlink(missing_ok=True)

    return written


def _collect_admin_source_diagnostics(states: List[str]) -> Dict[str, Dict[str, Any]]:
    try:
        from .state_scrapers import GenericStateScraper, get_scraper_for_state
    except Exception:
        return {}

    diagnostics: Dict[str, Dict[str, Any]] = {}
    for state_code in states:
        state_name = US_STATES.get(state_code, state_code)
        try:
            scraper = get_scraper_for_state(state_code, state_name)
            if not scraper:
                scraper = GenericStateScraper(state_code, state_name)

            code_list = list(scraper.get_code_list() or [])
            admin_candidates: List[str] = []
            for item in code_list:
                if not isinstance(item, dict):
                    continue
                code_name = str(item.get("name") or "")
                code_url = str(item.get("url") or "")
                code_type = str(item.get("type") or "")
                text = " ".join([code_name, code_url, code_type])
                if _ADMIN_RULE_TEXT_RE.search(text):
                    admin_candidates.append(code_name or code_url)
                    continue
                identify = getattr(scraper, "_identify_legal_area", None)
                if callable(identify) and str(identify(code_name)).strip().lower() == "administrative":
                    admin_candidates.append(code_name or code_url)

            admin_candidates = [value for value in admin_candidates if str(value or "").strip()]
            diagnostics[state_code] = {
                "total_code_sources": len(code_list),
                "admin_candidate_sources": len(admin_candidates),
                "admin_candidate_examples": admin_candidates[:5] or None,
            }
        except Exception as exc:
            diagnostics[state_code] = {
                "error": str(exc),
            }

    return diagnostics


def _filter_admin_state_blocks(
    raw_data: List[Dict[str, Any]],
    *,
    max_rules: Optional[int],
) -> tuple[List[Dict[str, Any]], int, List[str]]:
    filtered_data: List[Dict[str, Any]] = []
    admin_rule_count = 0
    zero_rule_states: List[str] = []

    for state_block in raw_data:
        if not isinstance(state_block, dict):
            continue
        state_code = str(state_block.get("state_code") or "").upper()
        statutes = list(state_block.get("statutes") or [])
        admin_statutes = [
            statute for statute in statutes
            if isinstance(statute, dict) and _is_admin_rule_statute(statute)
        ]
        if max_rules and max_rules > 0:
            admin_statutes = admin_statutes[: int(max_rules)]

        out_block = dict(state_block)
        out_block["title"] = f"{US_STATES.get(state_code, state_code)} Administrative Rules"
        out_block["source"] = "Official State Administrative Rule Sources"
        out_block["statutes"] = admin_statutes
        out_block["rules_count"] = len(admin_statutes)
        filtered_data.append(out_block)

        admin_rule_count += len(admin_statutes)
        if len(admin_statutes) == 0 and state_code:
            zero_rule_states.append(state_code)

    return filtered_data, admin_rule_count, zero_rule_states


async def list_state_admin_rule_jurisdictions(include_dc: bool = False) -> Dict[str, Any]:
    """Return available state jurisdictions for admin-rules scraping.

    By default this returns the 50 US states only (excluding DC).
    Set ``include_dc=True`` to include District of Columbia.
    """
    base = await list_state_jurisdictions()
    if base.get("status") != "success":
        return base

    states = dict(base.get("states") or {})
    if not include_dc:
        states.pop("DC", None)

    return {
        "status": "success",
        "states": states,
        "count": len(states),
        "include_dc": bool(include_dc),
        "note": "Includes all 50 US states" + (" plus DC" if include_dc else ""),
    }


async def scrape_state_admin_rules(
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
    max_base_statutes: Optional[int] = None,
    per_state_timeout_seconds: float = 480.0,
    include_dc: bool = False,
) -> Dict[str, Any]:
    """Scrape state administrative rules for selected states.

    The scraper delegates network extraction to ``scrape_state_laws`` and then
    filters the normalized output to administrative-rule records only.
    """
    try:
        allowed_state_codes = set(US_STATES.keys() if include_dc else US_50_STATE_CODES)
        selected_states = [
            s.upper()
            for s in (states or [])
            if s and str(s).upper() in allowed_state_codes
        ]
        if not selected_states or "ALL" in selected_states:
            selected_states = list(US_STATES.keys() if include_dc else US_50_STATE_CODES)

        source_diagnostics = _collect_admin_source_diagnostics(selected_states)

        start = time.time()
        effective_max_base_statutes = max_base_statutes
        if effective_max_base_statutes is None and max_rules and int(max_rules) > 0:
            effective_max_base_statutes = int(max_rules)

        base_result = await scrape_state_laws(
            states=selected_states,
            legal_areas=["administrative"],
            output_format=output_format,
            include_metadata=include_metadata,
            rate_limit_delay=rate_limit_delay,
            max_statutes=effective_max_base_statutes,
            output_dir=None,  # Keep separate admin-rules output root.
            write_jsonld=False,
            strict_full_text=strict_full_text,
            min_full_text_chars=min_full_text_chars,
            hydrate_statute_text=hydrate_rule_text,
            parallel_workers=parallel_workers,
            per_state_retry_attempts=per_state_retry_attempts,
            retry_zero_statute_states=retry_zero_rule_states,
            per_state_timeout_seconds=per_state_timeout_seconds,
        )

        raw_data = list(base_result.get("data") or [])
        filtered_data, admin_rule_count, zero_rule_states = _filter_admin_state_blocks(
            raw_data,
            max_rules=max_rules,
        )

        fallback_attempted_states: List[str] = []
        fallback_recovered_states: List[str] = []
        if retry_zero_rule_states and zero_rule_states:
            fallback_attempted_states = sorted(set(zero_rule_states))
            fallback_result = await scrape_state_laws(
                states=fallback_attempted_states,
                legal_areas=None,
                output_format=output_format,
                include_metadata=include_metadata,
                rate_limit_delay=rate_limit_delay,
                max_statutes=effective_max_base_statutes,
                output_dir=None,
                write_jsonld=False,
                strict_full_text=strict_full_text,
                min_full_text_chars=min_full_text_chars,
                hydrate_statute_text=hydrate_rule_text,
                parallel_workers=parallel_workers,
                per_state_retry_attempts=per_state_retry_attempts,
                retry_zero_statute_states=False,
                per_state_timeout_seconds=per_state_timeout_seconds,
            )

            fallback_filtered, _, _ = _filter_admin_state_blocks(
                list(fallback_result.get("data") or []),
                max_rules=max_rules,
            )
            fallback_by_state = {
                str(item.get("state_code") or "").upper(): item
                for item in fallback_filtered
                if isinstance(item, dict)
            }

            merged: List[Dict[str, Any]] = []
            for block in filtered_data:
                state_code = str((block or {}).get("state_code") or "").upper()
                replacement = fallback_by_state.get(state_code)
                if replacement and int(replacement.get("rules_count") or 0) > int(block.get("rules_count") or 0):
                    merged.append(replacement)
                    if int(block.get("rules_count") or 0) == 0:
                        fallback_recovered_states.append(state_code)
                else:
                    merged.append(block)
            filtered_data = merged
            admin_rule_count = sum(int((item or {}).get("rules_count") or 0) for item in filtered_data)
            zero_rule_states = [
                str(item.get("state_code") or "").upper()
                for item in filtered_data
                if isinstance(item, dict) and int(item.get("rules_count") or 0) == 0
            ]

        states_with_rules = sorted(
            {
                str(item.get("state_code") or "").upper()
                for item in filtered_data
                if isinstance(item, dict) and int(item.get("rules_count") or 0) > 0
            }
        )
        target_state_set = set(selected_states)
        missing_rule_states = sorted(target_state_set - set(states_with_rules))

        jsonld_paths: List[str] = []
        jsonld_dir: Optional[str] = None
        if write_jsonld:
            output_root = _resolve_admin_output_dir(output_dir)
            jsonld_root = output_root / "state_admin_rules_jsonld"
            jsonld_root.mkdir(parents=True, exist_ok=True)
            jsonld_paths = _write_state_admin_jsonld_files(filtered_data, jsonld_root)
            jsonld_dir = str(jsonld_root)

        elapsed = time.time() - start
        metadata = {
            "states_scraped": selected_states,
            "states_count": len(selected_states),
            "target_jurisdictions": "50_states" + ("+DC" if include_dc else ""),
            "include_dc": bool(include_dc),
            "rules_count": admin_rule_count,
            "elapsed_time_seconds": elapsed,
            "scraped_at": datetime.now().isoformat(),
            "scraper_type": "State admin-rules via state-specific/fallback pipeline",
            "delegated_legal_areas": ["administrative"],
            "rate_limit_delay": rate_limit_delay,
            "parallel_workers": int(parallel_workers),
            "per_state_retry_attempts": int(per_state_retry_attempts),
            "retry_zero_rule_states": bool(retry_zero_rule_states),
            "fallback_attempted_states": fallback_attempted_states or None,
            "fallback_recovered_states": sorted(set(fallback_recovered_states)) or None,
            "max_base_statutes": int(effective_max_base_statutes) if effective_max_base_statutes else None,
            "per_state_timeout_seconds": float(per_state_timeout_seconds),
            "strict_full_text": bool(strict_full_text),
            "min_full_text_chars": int(min_full_text_chars),
            "hydrate_rule_text": bool(hydrate_rule_text),
            "zero_rule_states": sorted(set(zero_rule_states)) if zero_rule_states else None,
            "states_with_rules_count": len(states_with_rules),
            "states_with_rules": states_with_rules,
            "missing_rule_states_count": len(missing_rule_states),
            "missing_rule_states": missing_rule_states,
            "coverage_ratio": (len(states_with_rules) / float(len(selected_states))) if selected_states else 0.0,
            "jsonld_dir": jsonld_dir,
            "jsonld_files": jsonld_paths if jsonld_paths else None,
            "base_status": base_result.get("status"),
            "base_metadata": base_result.get("metadata") if include_metadata else None,
            "source_diagnostics": source_diagnostics or None,
        }

        status = "success"
        if base_result.get("status") in {"error", "partial_success"}:
            status = "partial_success"
        if admin_rule_count == 0:
            status = "partial_success"

        return {
            "status": status,
            "data": filtered_data,
            "metadata": metadata,
            "output_format": output_format,
        }

    except Exception as exc:
        logger.error("State administrative-rules scraping failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "data": [],
            "metadata": {},
        }


__all__ = [
    "list_state_admin_rule_jurisdictions",
    "scrape_state_admin_rules",
]
