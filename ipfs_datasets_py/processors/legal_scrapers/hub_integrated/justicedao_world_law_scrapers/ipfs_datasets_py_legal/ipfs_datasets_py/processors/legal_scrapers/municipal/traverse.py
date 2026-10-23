"""Journaled class walk. The router only classifies ambiguous labels.

Websites and GNIS ids are copied from SPARQL bindings. A router reply that
names a QID or a URL that was not in the prompt is ignored.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import (
    _cell,
    _load_progress,
    _qid,
    _save_progress,
    _write_jsonl,
    fetch_class_rows,
    finalize_world,
    level_from_label,
    parts_root,
    sparql,
)

Generate = Callable[[str], str]
LEVELS = {
    "municipality",
    "district",
    "parish",
    "state",
    "province",
    "territory",
    "governorate",
    "oblast",
    "region",
    "canton",
    "prefecture",
    "department",
    "county",
    "emirate",
}
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)
_DROP_LABEL = re.compile(
    r"\b(list of|historical|ancient|abolished|former)\b|czechoslovak|"
    r"ashkharh|suyu|branch secretariat|community development council|"
    r"provincial administration commission|regional government|regional service commission|"
    r"census area|council of governments|transitional",
    re.I,
)
_PLACE_WORD = re.compile(
    r"\b(cities|city|towns?|villages?|boroughs?|communes?|hamlets?|townships?)\b",
    re.I,
)
_EXTRA_LEVEL = (
    (re.compile(r"\batolls?\b", re.I), "territory"),
    (re.compile(r"\bautonomous (island|sector|territorial unit)\b", re.I), "territory"),
    (re.compile(r"\bconstituent country\b|\bdependenc(?:y|ies)\b|\bisland group\b|\bouter islands\b|\boverseas collectivity\b", re.I), "territory"),
    (re.compile(r"\bdivisions?\b|\bdecentralized administration\b|\bentity of\b|\b(?:dzongdey|mkhare)\b", re.I), "region"),
    (re.compile(r"\bfirst-level administrative\b|\bprovincial-level\b", re.I), "province"),
    (re.compile(r"\bquarters?\b|\b(?:kozhuun|ulus)\b|dzielnic", re.I), "district"),
    (re.compile(r"\bsheadings?\b", re.I), "parish"),
    (re.compile(r"\bregional capital\b|einheitsgemeinde|megyei|okrug|rural community|şəhər|council of tuvalu", re.I), "municipality"),
    (re.compile(r"regency-level", re.I), "district"),
)


def router_prompt(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = [f"{row['qid']}\t{row['label']}" for row in rows]
    return (
        "Classify each Wikidata class. Return a JSON array. Each object has "
        "qid, action, and level. action is keep or drop. level is one of "
        "municipality, district, parish, state, province, territory. "
        "Use only the QID on that line. Drop awards, historical empires, and lists.\n"
        + "\n".join(lines)
    )


def reply_text(result: object) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("text", "content", "generated_text", "output"):
            value = result.get(key)
            if isinstance(value, str):
                return value
    return str(result)


def _payload_from_reply(reply: str) -> list[Any]:
    text = _FENCE.sub("", (reply or "").strip())
    candidates = [text]
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payload = payload.get("items") or payload.get("classes") or [payload]
        if isinstance(payload, list):
            return payload
    found: list[dict[str, str]] = []
    for line in text.splitlines():
        match = re.match(r"(Q\d+)\s+(keep|drop)\s*([A-Za-z]*)", line.strip(), re.I)
        if not match:
            continue
        found.append({"qid": match.group(1), "action": match.group(2).lower(), "level": match.group(3).lower()})
    return found


def parse_router_reply(rows: Sequence[Mapping[str, Any]], reply: str) -> dict[str, dict[str, Any]]:
    """Keep decisions whose QID was in the prompt and whose level is known."""
    allowed = {str(row.get("qid") or "") for row in rows}
    decided: dict[str, dict[str, Any]] = {}
    for item in _payload_from_reply(reply):
        if not isinstance(item, dict):
            continue
        qid = str(item.get("qid") or "")
        if qid not in allowed or qid in decided:
            continue
        action = str(item.get("action") or "").lower()
        level = str(item.get("level") or "")
        if action == "drop":
            decided[qid] = {"keep": False, "level": ""}
        elif action == "keep" and level in LEVELS:
            decided[qid] = {"keep": True, "level": level}
    return decided


def audit_targets(counts: Mapping[str, int], mapped: Sequence[str], *, below: int = 20) -> list[str]:
    """Mapped countries with no rows, or fewer than `below` places."""
    return [iso for iso in mapped if iso != "EU" and int(counts.get(iso) or 0) < below]


_BARE_CLASS = re.compile(
    r"^(town|city|village|municipality|district|commune|parish|county|province|state|region|quarter|atoll)s?$",
    re.I,
)


def select_audit_classes(
    rows: Sequence[Mapping[str, Any]],
    done: Sequence[str] | None = None,
    *,
    max_count: int = 2000,
) -> list[dict[str, Any]]:
    """Keep government classes the label rules already understand."""
    finished = set(done or ())
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        qid = str(row.get("qid") or "")
        label = str(row.get("label") or "")
        if (
            not qid
            or qid in finished
            or qid in seen
            or _BARE_CLASS.match(label.strip())
            or " " not in label.strip()
        ):
            continue
        count = int(row.get("n") or 0)
        if count < 1 or count > max_count:
            continue
        choice = decision_from_label(label)
        if not choice or not choice["keep"]:
            continue
        seen.add(qid)
        chosen.append({"qid": qid, "label": label, "n": count, "admin_level": choice["level"], "keep": True, "source": "audit"})
    return chosen


def decision_from_label(label: str) -> dict[str, Any] | None:
    """Classify a class name without the router. None means the label is ambiguous."""
    if _DROP_LABEL.search(label or "") or not (label or "").strip():
        return {"keep": False, "level": ""}
    level = level_from_label(label)
    if level:
        return {"keep": True, "level": level}
    text = label or ""
    if "federal subject" in text.lower() or "federative entity" in text.lower():
        return {"keep": True, "level": "state"}
    if re.search(r"\bland\b", text, re.I):
        return {"keep": True, "level": "state"}
    if re.search(r"\bkraj\b", text, re.I):
        return {"keep": True, "level": "region"}
    if _PLACE_WORD.search(text):
        return {"keep": True, "level": "municipality"}
    for pattern, level in _EXTRA_LEVEL:
        if pattern.search(text):
            return {"keep": True, "level": level}
    return None


def split_pending(rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    clear: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    for row in rows:
        choice = decision_from_label(str(row.get("label") or ""))
        if choice is None:
            ambiguous.append(dict(row))
            continue
        clear.append({**dict(row), "admin_level": choice["level"], "keep": choice["keep"], "source": "label"})
    return clear, ambiguous


def apply_router(
    rows: Sequence[Mapping[str, Any]],
    generate: Generate,
    *,
    batch_size: int = 20,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return kept decisions and rows the router did not decide."""
    kept: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    items = [dict(row) for row in rows]
    for start in range(0, len(items), batch_size):
        chunk = items[start : start + batch_size]
        try:
            reply = reply_text(generate(router_prompt(chunk)))
        except Exception as exc:
            for row in chunk:
                row["router_error"] = f"{type(exc).__name__}: {exc}"
                pending.append(row)
            continue
        decided = parse_router_reply(chunk, reply)
        if not decided:
            print(f"router unparsed {reply[:240]!r}", flush=True)
        for row in chunk:
            choice = decided.get(str(row.get("qid") or ""))
            if not choice:
                pending.append(row)
                continue
            if choice["keep"]:
                kept.append({**row, "admin_level": choice["level"], "keep": True, "source": "router"})
            else:
                kept.append({**row, "admin_level": "", "keep": False, "source": "router"})
    return kept, pending


_COVERAGE_LABEL = re.compile(
    r"\b(?:districts?|parishes?|municipalit(?:y|ies)|villages?|towns?|boroughs?|"
    r"dependenc(?:y|ies)|quarters?|localit(?:y|ies)|nagar|constituenc(?:y|ies))\b",
    re.I,
)


def coverage_query(country_qid: str) -> str:
    """Places in one country whose class name is a local-government word."""
    return f"""
SELECT ?item ?en ?class ?classLabel ?site ?gnis ?geonames ?pop WHERE {{
  {{ ?item wdt:P17 wd:{country_qid} }} UNION {{ ?item wdt:P131 wd:{country_qid} }}
  ?item wdt:P31 ?class .
  ?class rdfs:label ?classLabel .
  FILTER(LANG(?classLabel) = "en")
  FILTER(REGEX(STR(?classLabel), "(district|parish|municipalit|village|town|borough|dependency|quarter|localit|nagar|constituenc)", "i"))
  FILTER NOT EXISTS {{ ?item wdt:P576 ?dissolved }}
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item wdt:P856 ?site }}
  OPTIONAL {{ ?item wdt:P590 ?gnis }}
  OPTIONAL {{ ?item wdt:P1566 ?geonames }}
  OPTIONAL {{ ?item wdt:P1082 ?pop }}
}}
LIMIT 800
"""


def rows_from_coverage_bindings(bindings: Sequence[Mapping[str, Any]], iso: str) -> list[dict[str, Any]]:
    """Build seed rows for one country. The class itself is not stored."""
    from ipfs_datasets_py.processors.legal_scrapers.municipal.seed_harvest import classify_urls
    from ipfs_datasets_py.processors.legal_scrapers.regions.mapping import region_for_country

    grouped: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        qid = _qid(_cell(binding, "item"))
        class_label = _cell(binding, "classLabel")
        if not qid or not _COVERAGE_LABEL.search(class_label):
            continue
        row = grouped.get(qid)
        if row is None:
            choice = decision_from_label(class_label)
            row = {
                "qid": qid,
                "name": "",
                "sites": [],
                "gnises": [],
                "geonames": [],
                "pops": [],
                "class_qid": _qid(_cell(binding, "class")),
                "admin_level": (choice or {}).get("level") or "municipality",
            }
            grouped[qid] = row
        name = _cell(binding, "en")
        if name and not row["name"]:
            row["name"] = name
        for key, bucket in (("site", "sites"), ("gnis", "gnises"), ("geonames", "geonames"), ("pop", "pops")):
            value = _cell(binding, key)
            if value and value not in row[bucket]:
                row[bucket].append(value)
    try:
        region = region_for_country(iso)
    except KeyError:
        region = "unassigned"
    built: list[dict[str, Any]] = []
    for row in grouped.values():
        url_class, publisher = classify_urls(row["sites"])
        built.append(
            {
                "qid": row["qid"],
                "gnis": row["gnises"][0] if row["gnises"] else "",
                "gnis_alt": row["gnises"][1:],
                "geonames_id": row["geonames"][0] if row["geonames"] else "",
                "name": row["name"],
                "wikidata_label": row["name"],
                "official_name": "",
                "country_code": iso,
                "region": region,
                "admin_level": row["admin_level"],
                "wikidata_class": row["class_qid"],
                "parent_qid": "",
                "iso_3166_2": "",
                "lat": "",
                "lon": "",
                "population": row["pops"][0] if row["pops"] else "",
                "source_urls": row["sites"],
                "url_class": url_class,
                "publisher": publisher,
                "status": "not_scraped",
                "lang": [],
            }
        )
    return built


def country_qids(isos: Sequence[str]) -> dict[str, str]:
    """Prefer the shortest English label when several items share an ISO code."""
    found: dict[str, list[tuple[str, str]]] = {}
    for start in range(0, len(isos), 40):
        chunk = list(isos)[start : start + 40]
        values = " ".join(f'"{iso}"' for iso in chunk)
        query = f"""
SELECT ?iso ?country ?countryLabel WHERE {{
  VALUES ?iso {{ {values} }}
  ?country p:P297 ?stmt .
  ?stmt ps:P297 ?iso .
  FILTER NOT EXISTS {{ ?country wdt:P576 ?end }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
"""
        for binding in sparql(query, attempts=3, timeout=90.0):
            iso = _cell(binding, "iso")
            qid = _qid(_cell(binding, "country"))
            label = _cell(binding, "countryLabel") or qid
            if iso and qid:
                found.setdefault(iso, []).append((qid, label))
    chosen: dict[str, str] = {}
    for iso, options in found.items():
        options.sort(key=lambda item: len(item[1]))
        chosen[iso] = options[0][0]
    return chosen


def country_class_histogram(country_qid: str) -> list[dict[str, Any]]:
    query = f"""
SELECT ?class ?classLabel (COUNT(?item) AS ?n) WHERE {{
  ?item wdt:P17 wd:{country_qid} .
  ?item wdt:P31 ?class .
  FILTER NOT EXISTS {{ ?item wdt:P576 ?end }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
GROUP BY ?class ?classLabel
HAVING (?n >= 1)
ORDER BY DESC(?n)
LIMIT 12
"""
    rows: list[dict[str, Any]] = []
    for binding in sparql(query, attempts=2, timeout=45.0):
        qid = _qid(_cell(binding, "class"))
        if not qid:
            continue
        rows.append(
            {
                "qid": qid,
                "label": _cell(binding, "classLabel") or qid,
                "n": int(_cell(binding, "n") or "0"),
            }
        )
    return rows


def journal_qids(path: Path) -> set[str]:
    found: set[str] = set()
    if not path.is_file():
        return found
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            qid = str(row.get("qid") or "")
            if qid and row.get("action") in {"fetch", "drop"}:
                found.add(qid)
    return found


def _fetch_queue(
    queue: Sequence[Mapping[str, Any]],
    part_dir: Path,
    progress: dict[str, Any],
    done: set[str],
    journal_path: Path,
    delay: float,
) -> tuple[int, int, int]:
    fetched = 0
    places = 0
    errors = 0
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a", encoding="utf-8") as journal:
        for index, row in enumerate(queue, start=1):
            qid = str(row["qid"])
            label = str(row.get("label") or qid)
            if row.get("keep") is False:
                journal.write(
                    json.dumps(
                        {"qid": qid, "label": label, "action": "drop", "source": row.get("source") or "label"},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                print(f"DROP {index}/{len(queue)} {qid} {label}", flush=True)
                continue
            level = str(row.get("admin_level") or "municipality")
            try:
                found = fetch_class_rows(qid, delay=delay, admin_level=level)
            except Exception as exc:
                errors += 1
                progress.setdefault("failed", {})[qid] = f"{label}: {type(exc).__name__}: {exc}"
                _save_progress(part_dir / "progress.json", progress)
                journal.write(
                    json.dumps(
                        {
                            "qid": qid,
                            "label": label,
                            "action": "error",
                            "admin_level": level,
                            "source": row.get("source"),
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                journal.flush()
                print(f"FAIL {index}/{len(queue)} {qid} {label}: {exc}", flush=True)
                continue
            _write_jsonl(part_dir / f"{qid}.jsonl", found)
            if qid not in done:
                progress.setdefault("done", []).append(qid)
                done.add(qid)
            progress.setdefault("failed", {}).pop(qid, None)
            progress.setdefault("counts", {})[qid] = len(found)
            _save_progress(part_dir / "progress.json", progress)
            fetched += 1
            places += len(found)
            journal.write(
                json.dumps(
                    {
                        "qid": qid,
                        "label": label,
                        "action": "fetch",
                        "admin_level": level,
                        "source": row.get("source"),
                        "rows": len(found),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            journal.flush()
            print(f"OK {index}/{len(queue)} {qid} {label} {level} rows={len(found)}", flush=True)
    return fetched, places, errors


def traverse_catalog(
    dest: Path,
    *,
    generate: Generate | None = None,
    parts: Path | None = None,
    delay: float = 0.35,
    limit: int | None = None,
) -> dict[str, Any]:
    """Fetch catalog classes that are not done. Ambiguous labels go to the router."""
    catalog_path = dest / "class_catalog.json"
    records = json.loads(catalog_path.read_text(encoding="utf-8"))
    journal_path = dest / "traverse_journal.jsonl"
    finished = journal_qids(journal_path)
    part_dir = parts or parts_root()
    progress = _load_progress(part_dir / "progress.json")
    done = set(progress.get("done") or [])
    pending = [
        row
        for row in records
        if not row.get("done") and str(row.get("qid") or "") not in done and str(row.get("qid") or "") not in finished
    ]
    if limit is not None:
        pending = pending[:limit]
    clear, ambiguous = split_pending(pending)
    print(f"traverse pending {len(pending)} clear {len(clear)} ambiguous {len(ambiguous)}", flush=True)
    fetched, places, _errors = _fetch_queue(clear, part_dir, progress, done, journal_path, delay)
    router_kept: list[dict[str, Any]] = []
    still_open: list[dict[str, Any]] = list(ambiguous)
    if generate and ambiguous:
        print(f"router batches {((len(ambiguous) - 1) // 20) + 1}", flush=True)
        router_kept, still_open = apply_router(ambiguous, generate)
    dropped = [row for row in router_kept if not row.get("keep")]
    accepted = [row for row in router_kept if row.get("keep")]
    more_fetched, more_places, _more_errors = _fetch_queue(
        accepted, part_dir, progress, done, journal_path, delay
    )
    fetched += more_fetched
    places += more_places
    with journal_path.open("a", encoding="utf-8") as journal:
        for row in dropped:
            journal.write(
                json.dumps(
                    {"qid": row["qid"], "label": row["label"], "action": "drop", "source": "router"},
                    ensure_ascii=False,
                )
                + "\n"
            )
    summary = finalize_world(dest, part_dir) if fetched or dropped else {"countries": 0, "rows": 0}
    summary["fetched_classes"] = fetched
    summary["places"] = places
    summary["dropped"] = len(dropped)
    summary["still_open"] = len(still_open)
    summary["journal"] = str(journal_path)
    return summary
