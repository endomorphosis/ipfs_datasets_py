"""Deterministic policy resolver.

Resolves which policy pack applies for a given (jurisdiction, date, query)
in a fully deterministic, replay-stable manner.
Schema version: 1.0
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


RESOLVER_SCHEMA_VERSION = "1.0"


RESOLVER_ERROR_CODES: Dict[str, str] = {
    "no_matching_packs": "PR_ERR_NO_MATCHING_PACKS",
    "ambiguous_resolution": "PR_ERR_AMBIGUOUS_RESOLUTION",
    "invalid_date_format": "PR_ERR_INVALID_DATE_FORMAT",
}


class PolicyResolutionError(ValueError):
    """Raised when policy resolution fails."""

    def __init__(self, message: str, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _parse_date(date_str: str) -> datetime:
    """Parse an ISO-8601 date string, raising PolicyResolutionError on failure."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError) as exc:
        raise PolicyResolutionError(
            f"Invalid date format '{date_str}'; expected YYYY-MM-DD",
            error_code=RESOLVER_ERROR_CODES["invalid_date_format"],
        ) from exc


def resolve_policy_pack(
    packs: List[dict],
    jurisdiction: str,
    date: str,
    query: Optional[dict] = None,
) -> Dict[str, Any]:
    """Deterministically resolve which policy pack applies.

    Resolution algorithm:
    1. Filter packs by exact jurisdiction match.
    2. Filter packs where effective_date <= date.
    3. Select the pack with the most recent effective_date.
    4. Tie-break deterministically: lexicographic by pack_id (if present on
       all tied packs), otherwise by original index position (lowest wins first,
       then highest index for most-recent—see note below).

    Tie-break detail: among packs with the same effective_date, if every
    tied pack has a non-empty pack_id, sort ascending by pack_id and pick
    the first. Otherwise sort ascending by original index and pick the first
    (lowest index) for a stable "first-wins" positional rule.

    Args:
        packs: List of raw policy pack dicts.
        jurisdiction: Exact jurisdiction string to match.
        date: Query date in YYYY-MM-DD format.
        query: Optional additional query context (reserved for future use).

    Returns:
        Decision envelope dict with keys: ``schema_version``,
        ``selected_pack_id``, ``selected_pack_index``, ``jurisdiction``,
        ``date``, ``tie_break_applied``, ``trace``.

    Raises:
        PolicyResolutionError: If no packs match or the date is invalid.
    """
    query_dt = _parse_date(date)
    trace: List[Dict[str, Any]] = []

    # Step 1: filter by jurisdiction
    jurisdiction_matches = [
        (idx, p) for idx, p in enumerate(packs)
        if p.get("jurisdiction") == jurisdiction
    ]
    trace.append({
        "step": "jurisdiction_filter",
        "jurisdiction": jurisdiction,
        "matched_indices": [idx for idx, _ in jurisdiction_matches],
    })

    # Step 2: filter by effective_date <= query date
    date_matches = []
    for idx, p in jurisdiction_matches:
        eff_date_str = p.get("effective_date", "")
        try:
            eff_dt = _parse_date(eff_date_str)
        except PolicyResolutionError:
            trace.append({
                "step": "date_filter_skip",
                "index": idx,
                "reason": f"unparseable effective_date '{eff_date_str}'",
            })
            continue
        if eff_dt <= query_dt:
            date_matches.append((idx, p, eff_dt))

    trace.append({
        "step": "date_filter",
        "query_date": date,
        "matched_indices": [idx for idx, _, _ in date_matches],
    })

    if not date_matches:
        raise PolicyResolutionError(
            f"No policy packs found for jurisdiction='{jurisdiction}' on date='{date}'",
            error_code=RESOLVER_ERROR_CODES["no_matching_packs"],
        )

    # Step 3: find the most recent effective_date
    max_eff_dt = max(eff_dt for _, _, eff_dt in date_matches)
    candidates = [(idx, p) for idx, p, eff_dt in date_matches if eff_dt == max_eff_dt]

    tie_break_applied = len(candidates) > 1
    trace.append({
        "step": "most_recent_filter",
        "most_recent_effective_date": max_eff_dt.strftime("%Y-%m-%d"),
        "candidate_indices": [idx for idx, _ in candidates],
        "tie_break_applied": tie_break_applied,
    })

    # Step 4: deterministic tie-break
    if tie_break_applied:
        all_have_pack_id = all(
            p.get("pack_id") not in (None, "") for _, p in candidates
        )
        if all_have_pack_id:
            # Lexicographic ascending by pack_id
            candidates.sort(key=lambda t: t[1]["pack_id"])
            trace.append({"step": "tie_break", "method": "pack_id_lexicographic"})
        else:
            # Ascending by original index (pick the first = lowest index)
            candidates.sort(key=lambda t: t[0])
            trace.append({"step": "tie_break", "method": "index_ascending"})

    selected_index, selected_pack = candidates[0]
    selected_pack_id = selected_pack.get("pack_id") or f"pack_index_{selected_index}"

    trace.append({
        "step": "selected",
        "selected_index": selected_index,
        "selected_pack_id": selected_pack_id,
    })

    return {
        "schema_version": RESOLVER_SCHEMA_VERSION,
        "selected_pack_id": selected_pack_id,
        "selected_pack_index": selected_index,
        "jurisdiction": jurisdiction,
        "date": date,
        "tie_break_applied": tie_break_applied,
        "trace": trace,
    }
