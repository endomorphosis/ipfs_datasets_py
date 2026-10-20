"""Counties that still have no stored ordinances, joined to Wikidata places.

The queue is the Census 2024 county or county-equivalent whose name does not
resolve to an authority in the American municipal corpus. Each row keeps the
Wikidata place already stored in ``seeds/americas/US_wikidata.jsonl`` when the
Census GNIS matches one item. A name is used only when the GNIS is missing
from that file and exactly one stored place has that name. Official websites
on the matched row are copied. Wikipedia article titles are not invented.
Bots read ``seeds/americas/US_county_gaps.jsonl``.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Iterable, Mapping

_SEEDS = Path(__file__).resolve().parent / "seeds"
_WIKIDATA = _SEEDS / "americas" / "US_wikidata.jsonl"
_QUEUE = _SEEDS / "americas" / "US_county_gaps.jsonl"
# Census LSAD values kept by county_geography. The label is the kind of the
# names that use that code in cb_2024_us_county_500k.
_LEGAL_LSAD = frozenset({"00", "03", "04", "05", "06", "07", "10", "12", "13", "15", "25"})
_LSAD_LEVEL = {
    "03": "city and borough",
    "04": "borough",
    "05": "census area",
    "06": "county",
    "07": "district",
    "10": "island",
    "12": "municipality",
    "13": "municipio",
    "15": "parish",
    "25": "city",
}


def queue_path() -> Path:
    return _QUEUE


def load_county_gap_queue(path: Path | None = None) -> list[dict[str, object]]:
    """Read the county scrape queue. An empty file returns an empty list."""

    target = _QUEUE if path is None else path
    rows: list[dict[str, object]] = []
    if not target.is_file():
        return rows
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _dbf_rows(path: Path) -> list[dict[str, str]]:
    data = path.read_bytes()
    count, header_len, record_len = struct.unpack_from("<IHH", data, 4)
    fields: list[tuple[str, int]] = []
    cursor = 32
    while cursor < header_len - 1 and data[cursor] != 0x0D:
        name = data[cursor : cursor + 11].split(b"\x00", 1)[0].decode("ascii")
        fields.append((name, data[cursor + 16]))
        cursor += 32
    rows: list[dict[str, str]] = []
    for index in range(count):
        record = data[header_len + index * record_len : header_len + (index + 1) * record_len]
        offset = 1
        row: dict[str, str] = {}
        for name, length in fields:
            raw = record[offset : offset + length]
            offset += length
            row[name] = raw.decode("utf-8").strip()
        rows.append(row)
    return rows


def _gnis_key(value: object) -> str:
    text = str(value or "").strip()
    if text.isdigit():
        return str(int(text))
    return text


def _level(lsad: str, name: str) -> str:
    if lsad == "00":
        lowered = name.casefold()
        if lowered == "district of columbia":
            return "district"
        if lowered.endswith(" city"):
            return "city"
        if lowered.endswith(" island"):
            return "island"
        return "county_equivalent"
    return _LSAD_LEVEL.get(lsad, "county")


def _wikidata_indexes(
    path: Path,
) -> tuple[dict[str, list[dict[str, object]]], dict[str, list[dict[str, object]]]]:
    from ipfs_datasets_py.processors.legal_data.municipal_place_query import fold_place

    by_gnis: dict[str, list[dict[str, object]]] = {}
    by_name: dict[str, list[dict[str, object]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            continue
        keys = [_gnis_key(row.get("gnis"))]
        alts = row.get("gnis_alt")
        if isinstance(alts, list):
            keys.extend(_gnis_key(item) for item in alts)
        for key in keys:
            if key:
                by_gnis.setdefault(key, []).append(row)
        for label in (row.get("name"), row.get("wikidata_label")):
            if isinstance(label, str) and label.strip():
                by_name.setdefault(fold_place(label), []).append(row)
    return by_gnis, by_name


def _sample_points(path: Path | None) -> dict[tuple[str, str], int]:
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    points: dict[tuple[str, str], int] = {}
    for item in payload.get("missing_counties") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        state = str(item.get("state") or "")
        count = item.get("points")
        if name and state and isinstance(count, int):
            points[(name, state)] = count
    return points


def _urls(row: Mapping[str, object]) -> list[str]:
    from ipfs_datasets_py.processors.legal_scrapers.municipal.websites import clean_website

    raw = row.get("source_urls")
    if not isinstance(raw, list):
        return []
    found: list[str] = []
    for url in raw:
        if not isinstance(url, str):
            continue
        cleaned = clean_website(url)
        if cleaned and cleaned not in found:
            found.append(cleaned)
    return found


def _choose(candidates: Iterable[Mapping[str, object]]) -> tuple[str, Mapping[str, object] | None, list[str]]:
    by_qid: dict[str, Mapping[str, object]] = {}
    for row in candidates:
        qid = str(row.get("qid") or "")
        if qid and qid not in by_qid:
            by_qid[qid] = row
    qids = sorted(by_qid)
    if len(qids) == 1:
        return "gnis", by_qid[qids[0]], qids
    if len(qids) > 1:
        return "ambiguous", None, qids
    return "absent", None, []


def build_county_gap_rows(
    dbf_path: Path,
    wikidata_path: Path | None = None,
    sample_path: Path | None = None,
) -> list[dict[str, object]]:
    """Census counties with no corpus, plus the stored Wikidata place."""

    import ipfs_datasets_py.processors.legal_data.county_geography as geography
    import ipfs_datasets_py.processors.legal_data.municipal_section_search as sections
    from ipfs_datasets_py.processors.legal_data.municipal_place_query import fold_place

    by_gnis, by_name = _wikidata_indexes(_WIKIDATA if wikidata_path is None else wikidata_path)
    sampled = _sample_points(sample_path)
    entries = sections.load_authority_index()
    original = sections.load_authority_index
    sections.load_authority_index = lambda: entries
    rows: list[dict[str, object]] = []
    try:
        for area in _dbf_rows(dbf_path):
            if area.get("LSAD") not in _LEGAL_LSAD:
                continue
            name = area["NAMELSAD"]
            state = area["STUSPS"]
            if geography._corpus_fold(name, state):
                continue
            census_gnis = area.get("COUNTYNS") or ""
            match, chosen, qids = _choose(by_gnis.get(_gnis_key(census_gnis), []))
            if match == "absent":
                named, name_row, name_qids = _choose(by_name.get(fold_place(name), []))
                if named == "gnis":
                    match, chosen, qids = "name", name_row, name_qids
            if match == "ambiguous":
                match, chosen, qids = "absent", None, []
            qid = qids[0] if match in {"gnis", "name"} and qids else ""
            urls = _urls(chosen) if chosen is not None else []
            if urls:
                from ipfs_datasets_py.processors.legal_scrapers.municipal.seed_harvest import (
                    classify_urls,
                )

                url_class, publisher = classify_urls(urls)
            else:
                url_class, publisher = "none", ""
            hits = sampled.get((name, state), 0)
            rows.append(
                {
                    "admin_level": _level(area["LSAD"], name),
                    "census_geoid": area.get("GEOID") or "",
                    "census_gnis": census_gnis,
                    "census_lsad": area.get("LSAD") or "",
                    "census_name": name,
                    "country_code": "US",
                    "geonames_id": str(chosen.get("geonames_id") or "") if chosen is not None else "",
                    "gnis": _gnis_key(census_gnis),
                    "match": match,
                    "name": name,
                    "place_name": name,
                    "population": str(chosen.get("population") or "") if chosen is not None else "",
                    "publisher": publisher,
                    "qid": qid,
                    "qids": qids,
                    "region": "americas",
                    "sample_points": hits,
                    "source_urls": urls,
                    "state_code": state,
                    "state_name": area.get("STATE_NAME") or "",
                    "status": "not_scraped",
                    "url_class": url_class,
                    "wikidata_class": str(chosen.get("wikidata_class") or "") if chosen is not None else "",
                    "wikidata_label": str(chosen.get("wikidata_label") or "") if chosen is not None else "",
                    "wikidata_url": f"https://www.wikidata.org/wiki/{qid}" if qid else "",
                }
            )
    finally:
        sections.load_authority_index = original
    rows.sort(key=lambda row: (str(row["state_code"]), str(row["census_name"]), str(row["gnis"])))
    return rows


def write_county_gap_queue(rows: list[dict[str, object]], path: Path | None = None) -> Path:
    target = _QUEUE if path is None else path
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)
    return target
