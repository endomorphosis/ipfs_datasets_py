"""Population values for the municipal seed, from Wikidata P1082."""

from __future__ import annotations

from typing import Mapping, Sequence


def choose_population(values: Sequence[str]) -> str:
    """Keep the largest numeric population. Blank when none parse."""
    best = ""
    best_number = -1.0
    for value in values:
        try:
            number = float(str(value).strip())
        except (TypeError, ValueError):
            continue
        if number > best_number:
            best_number = number
            best = str(value).strip()
    return best


def population_rank(value: str) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return -1.0


def sort_by_population(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Largest population first. Rows with no population stay at the end."""
    return sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            population_rank(str(row.get("population") or "")) < 0,
            -population_rank(str(row.get("population") or "")),
            str(row.get("name") or row.get("place_name") or "").lower(),
        ),
    )


def sort_municipalities_first(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Largest municipalities first, then other levels by population."""
    return sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            str(row.get("admin_level") or "") != "municipality",
            population_rank(str(row.get("population") or "")) < 0,
            -population_rank(str(row.get("population") or "")),
            str(row.get("name") or row.get("place_name") or "").lower(),
        ),
    )


def apply_population(row: Mapping[str, object], populations: Mapping[str, str]) -> dict[str, object]:
    updated = dict(row)
    current = str(updated.get("population") or "").strip()
    if current:
        return updated
    found = populations.get(str(updated.get("qid") or ""))
    if found:
        updated["population"] = found
    return updated
