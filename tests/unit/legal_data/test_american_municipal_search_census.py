"""Census of municipal and county search across random USA coordinates.

Thousands of coordinates are drawn in the continental United States,
Alaska, Hawaii, and Puerto Rico, plus points moved a short distance
from real seed places. A state the boxes miss gets one seed coordinate.
A state whose seed coordinates are tied is searched by place name.
Each resolved city is searched with keywords taken from its ordinances,
random token strings, and vector queries. The same points must name the
Census county, parish, borough, or other county equivalent, and return
that government's stored ordinances when the query asks for them.
Failures are written to a report so the dataset or the query can be
corrected. A miss outside 25 km is coverage, not a crash. An equal
distance stays ambiguous and is recorded, not guessed. A county with no
stored authority is named and contributes no rows.
"""

from __future__ import annotations

import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.county_geography import (
    locate_governments,
)
from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
    MAX_PLACE_METERS,
    PlaceConstraint,
    PlaceQueryError,
    constraint_from_place,
    distance_meters,
    fold_place,
    municipal_places,
    resolve_municipal_place,
)
from ipfs_datasets_py.processors.legal_data.municipal_section_search import (
    MunicipalSectionError,
    corpus_authority_fold,
    document_tokens,
    load_authority_index,
    load_place_section,
    resolve_corpus_authority,
)
from ipfs_datasets_py.processors.legal_data import query_legal_records as query_mod
from ipfs_datasets_py.processors.legal_data.query_legal_records import (
    LegalQueryInputError,
    query_legal_records,
)

_REPORT = Path("/tmp/grok-barberb/municipal-search-sample/report-county.json")
_PROGRESS = Path("/tmp/grok-barberb/municipal-search-sample/census-county.progress")
_REPO = "justicedao/american_municipal_law_norm"
_SEED = 20261020
_BOX_POINTS = 5000
_JITTER_POINTS = 2000
_SEARCH_PLACES = 160
_FULL_LOADER = 15
_COUNTY_CORPORA = 36
_UNINCORPORATED = 20
_REGIONS = (
    ("conus", 24_500_000, 49_400_000, -124_800_000, -66_900_000, 76),
    ("alaska", 51_200_000, 71_400_000, -168_000_000, -129_000_000, 15),
    ("hawaii", 18_900_000, 22_300_000, -160_300_000, -154_800_000, 5),
    ("puerto_rico", 17_900_000, 18_520_000, -67_300_000, -65_200_000, 4),
)


def _micro(value: int) -> str:
    sign = "-" if value < 0 else ""
    whole, frac = divmod(abs(value), 1_000_000)
    return f"{sign}{whole}.{frac:06d}"


def _section(row: dict[str, object]) -> str | None:
    raw = row.get("provenance")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if isinstance(raw, dict):
        value = raw.get("section")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _region(rng: random.Random) -> tuple[str, int, int]:
    roll = rng.randrange(100)
    cursor = 0
    for name, lat0, lat1, lon0, lon1, weight in _REGIONS:
        cursor += weight
        if roll < cursor:
            return name, rng.randint(lat0, lat1), rng.randint(lon0, lon1)
    name, lat0, lat1, lon0, lon1, _weight = _REGIONS[0]
    return name, rng.randint(lat0, lat1), rng.randint(lon0, lon1)


def _tied(lat_micro: int, lon_micro: int) -> list[dict[str, object]]:
    found: list[tuple[int, str, str, str]] = []
    for place in municipal_places():
        meters = distance_meters(lat_micro, lon_micro, place.lat_micro, place.lon_micro)
        if meters <= MAX_PLACE_METERS:
            found.append((meters, place.name, place.state_code, place.gnis))
    found.sort()
    if len(found) < 2 or found[0][0] != found[1][0]:
        return []
    distance = found[0][0]
    return [
        {"meters": meters, "name": name, "state": state, "gnis": gnis}
        for meters, name, state, gnis in found
        if meters == distance
    ][:6]


def _slot_rows(index: dict[str, dict[str, object]], folded: str, state: str) -> int:
    slot = index.get(f"{folded}\tUS-{state}")
    rows = slot.get("rows") if isinstance(slot, dict) else 0
    return rows if isinstance(rows, int) else 0


def _index_rows(index: dict[str, dict[str, object]], name: str, state: str) -> int:
    return _slot_rows(index, corpus_authority_fold(name, state), state)


def _rare_targets(
    rows: list[dict[str, object]],
    limit: int,
) -> list[tuple[dict[str, object], tuple[str, str]]]:
    frequencies: Counter[str] = Counter()
    prepared: list[tuple[dict[str, object], tuple[str, ...]]] = []
    for row in rows:
        text = row.get("text")
        if not isinstance(text, str) or len(text) < 80:
            continue
        tokens = tuple(token for token in document_tokens(row) if len(token) >= 8)
        if len(set(tokens)) < 2:
            continue
        prepared.append((row, tokens))
        frequencies.update(set(tokens))
    targets: list[tuple[dict[str, object], tuple[str, str]]] = []
    used: set[str] = set()
    for row, tokens in prepared:
        cid = row.get("entry_cid")
        if not isinstance(cid, str) or cid in used:
            continue
        rare = [token for token in tokens if frequencies[token] == 1]
        if len(rare) < 2:
            continue
        used.add(cid)
        targets.append((row, (rare[0], rare[1])))
        if len(targets) == limit:
            break
    return targets


def _query(latitude: str, longitude: str, text: str, retrieval: str, opener):
    return query_legal_records(
        jurisdiction="US",
        latitude=latitude,
        longitude=longitude,
        text_query=text,
        retrieval=retrieval,
        limit=20,
        corpus_opener=opener,
    )


def _check_layers(result, latitude: str, longitude: str, errors: list[dict[str, object]], label: str) -> None:
    """The point's county and territory must be the governments that contain it."""

    located = locate_governments(latitude, longitude)
    if located.status != "one" or located.county is None:
        if result.county_name or result.county_records or result.territory_name or result.territory_records:
            errors.append(
                {
                    "kind": "county_guessed",
                    "label": label,
                    "status": located.status,
                    "latitude": latitude,
                    "longitude": longitude,
                    "county_name": result.county_name,
                    "territory_name": result.territory_name,
                }
            )
        return
    county = located.county
    if result.county_name != county.name or result.county_state != county.state_code:
        errors.append(
            {
                "kind": "wrong_county",
                "label": label,
                "latitude": latitude,
                "longitude": longitude,
                "expected": f"{county.name}, {county.state_code}",
                "county_name": result.county_name,
                "county_state": result.county_state,
            }
        )
        return
    city_fold = None
    if isinstance(result.place_name, str) and isinstance(result.place_state, str):
        try:
            city_fold = corpus_authority_fold(result.place_name, result.place_state)
        except MunicipalSectionError:
            city_fold = None
    fold = county.authority_fold
    if not isinstance(fold, str) or fold == city_fold:
        if result.county_records:
            errors.append(
                {
                    "kind": "county_rows_unexpected",
                    "label": label,
                    "county_name": county.name,
                    "fold": fold,
                    "entry_cid": result.county_records[0].get("entry_cid"),
                }
            )
    else:
        for row in result.county_records:
            authority = row.get("authority")
            jurisdiction = row.get("jurisdiction")
            if fold_place(str(authority)) != fold or jurisdiction != f"US-{county.state_code}":
                errors.append(
                    {
                        "kind": "wrong_county_authority",
                        "label": label,
                        "expected": f"{fold}, US-{county.state_code}",
                        "authority": authority,
                        "jurisdiction": jurisdiction,
                        "entry_cid": row.get("entry_cid"),
                    }
                )
                break
    territory = located.territory
    if territory is None:
        if result.territory_name or result.territory_records:
            errors.append(
                {
                    "kind": "unexpected_territory",
                    "label": label,
                    "latitude": latitude,
                    "longitude": longitude,
                    "territory_name": result.territory_name,
                }
            )
        return
    if result.territory_name != territory.name or result.territory_state != territory.state_code:
        errors.append(
            {
                "kind": "wrong_territory",
                "label": label,
                "expected": f"{territory.name}, {territory.state_code}",
                "territory_name": result.territory_name,
                "territory_state": result.territory_state,
            }
        )
        return
    taken = {fold, city_fold}
    tfold = territory.authority_fold
    if not isinstance(tfold, str) or tfold in taken:
        if result.territory_records:
            errors.append(
                {
                    "kind": "territory_rows_unexpected",
                    "label": label,
                    "territory_name": territory.name,
                    "entry_cid": result.territory_records[0].get("entry_cid"),
                }
            )
    else:
        for row in result.territory_records:
            if fold_place(str(row.get("authority"))) != tfold or row.get("jurisdiction") != f"US-{territory.state_code}":
                errors.append(
                    {
                        "kind": "wrong_territory_authority",
                        "label": label,
                        "expected": tfold,
                        "authority": row.get("authority"),
                        "entry_cid": row.get("entry_cid"),
                    }
                )
                break


def _check_city(
    result,
    place,
    errors: list[dict[str, object]],
    label: str,
    latitude: str,
    longitude: str,
) -> None:
    if result.place_name != place.name or result.place_state != place.state_code:
        errors.append(
            {
                "kind": "wrong_place",
                "label": label,
                "expected": f"{place.name}, {place.state_code}",
                "place_name": result.place_name,
                "place_state": result.place_state,
            }
        )
    for row in result.records:
        authority = row.get("authority")
        jurisdiction = row.get("jurisdiction")
        expected = corpus_authority_fold(place.name, place.state_code)
        if fold_place(str(authority)) != expected or jurisdiction != f"US-{place.state_code}":
            errors.append(
                {
                    "kind": "wrong_authority",
                    "label": label,
                    "expected": f"{place.name}, US-{place.state_code}",
                    "authority": authority,
                    "jurisdiction": jurisdiction,
                    "entry_cid": row.get("entry_cid"),
                }
            )
            break
    _check_layers(result, latitude, longitude, errors, label)


def _note(started: float, message: str) -> None:
    _PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    elapsed = int(time.perf_counter() - started)
    _PROGRESS.write_text(f"{elapsed}s {message}\n", encoding="utf-8")


def _census() -> dict[str, object]:
    started = time.perf_counter()
    rng = random.Random(_SEED)
    places = municipal_places()
    index = load_authority_index()
    authority_cache: dict[tuple[str, str], tuple] = {}
    original_cache = query_mod._cached_authority_rows

    def cached_authority(name: str, state: str):
        key = (name, state)
        found = authority_cache.get(key)
        if found is None:
            found = original_cache.__wrapped__(name, state)
            authority_cache[key] = found
        return found

    query_mod._cached_authority_rows = cached_authority
    _note(started, "index loaded")
    box_counts: Counter[str] = Counter()
    resolved_counts: Counter[str] = Counter()
    hits: list[dict[str, object]] = []
    miss_examples: list[dict[str, object]] = []
    ambiguous: list[dict[str, object]] = []
    ambiguous_count = 0
    switched_count = 0
    switched: list[dict[str, object]] = []
    coordinates = 0
    drawn: list[tuple[str, str]] = []

    def classify(region: str, kind: str, lat_micro: int, lon_micro: int, origin: str | None) -> None:
        nonlocal coordinates
        coordinates += 1
        latitude = _micro(lat_micro)
        longitude = _micro(lon_micro)
        drawn.append((latitude, longitude))
        box_counts[f"{kind}:{region}"] += 1
        try:
            place = resolve_municipal_place(None, latitude, longitude)
        except PlaceQueryError as exc:
            nonlocal ambiguous_count
            ambiguous_count += 1
            if len(ambiguous) < 80:
                ambiguous.append(
                    {
                        "kind": kind,
                        "region": region,
                        "latitude": latitude,
                        "longitude": longitude,
                        "code": exc.code,
                        "origin": origin,
                        "tied": _tied(lat_micro, lon_micro),
                    }
                )
            return
        if place is None:
            if len(miss_examples) < 40:
                miss_examples.append(
                    {
                        "kind": kind,
                        "region": region,
                        "latitude": latitude,
                        "longitude": longitude,
                    }
                )
            resolved_counts[f"miss:{region}"] += 1
            return
        if origin is not None and place.gnis != origin:
            nonlocal switched_count
            switched_count += 1
            if len(switched) < 40:
                switched.append(
                    {
                        "region": region,
                        "latitude": latitude,
                        "longitude": longitude,
                        "from_gnis": origin,
                        "to_name": place.name,
                        "to_state": place.state_code,
                        "to_gnis": place.gnis,
                    }
                )
        resolved_counts[f"hit:{place.state_code}"] += 1
        hits.append(
            {
                "latitude": latitude,
                "longitude": longitude,
                "name": place.name,
                "state": place.state_code,
                "gnis": place.gnis,
                "region": region,
                "kind": kind,
            }
        )

    for _ in range(_BOX_POINTS):
        region, lat_micro, lon_micro = _region(rng)
        classify(region, "box", lat_micro, lon_micro, None)
    for _ in range(_JITTER_POINTS):
        place = places[rng.randrange(len(places))]
        classify(
            place.state_code,
            "jitter",
            place.lat_micro + rng.randint(-6_000, 6_000),
            place.lon_micro + rng.randint(-6_000, 6_000),
            place.gnis,
        )

    anchor_points = 0
    states_hit = {str(hit["state"]) for hit in hits}
    for state in sorted({place.state_code for place in places}):
        if state in states_hit:
            continue
        ordered = [place for place in places if place.state_code == state]
        ordered.sort(
            key=lambda place: (
                0 if _index_rows(index, place.name, place.state_code) > 0 else 1,
                place.gnis,
            )
        )
        for place in ordered:
            before_hits = len(hits)
            classify(state, "anchor", place.lat_micro, place.lon_micro, place.gnis)
            anchor_points += 1
            if len(hits) > before_hits:
                states_hit.add(str(hits[-1]["state"]))
                break

    by_state: dict[str, list[dict[str, object]]] = defaultdict(list)
    seen_gnis: set[str] = set()
    for hit in hits:
        if hit["gnis"] in seen_gnis:
            continue
        seen_gnis.add(str(hit["gnis"]))
        by_state[str(hit["state"])].append(hit)
    chosen: list[dict[str, object]] = []
    while len(chosen) < _SEARCH_PLACES:
        progressed = False
        for state in sorted(by_state):
            bucket = by_state[state]
            if not bucket:
                continue
            chosen.append(bucket.pop())
            progressed = True
            if len(chosen) == _SEARCH_PLACES:
                break
        if not progressed:
            break
    covered = set(by_state)
    for state in sorted({place.state_code for place in places}):
        if state in covered:
            continue
        for place in places:
            if place.state_code != state or _index_rows(index, place.name, place.state_code) <= 0:
                continue
            chosen.append(
                {
                    "latitude": place.latitude,
                    "longitude": place.longitude,
                    "name": place.name,
                    "state": place.state_code,
                    "gnis": place.gnis,
                    "region": state,
                    "kind": "name",
                }
            )

    errors: list[dict[str, object]] = []
    unexpected: list[dict[str, object]] = []
    corpus_gaps: list[dict[str, object]] = []
    thin_text: list[dict[str, object]] = []
    positive_keyword = 0
    positive_vector = 0
    random_keyword = 0
    random_vector = 0
    garbage_queries = 0
    full_loader = 0
    searched_states: set[str] = set()

    def remember(kind: str, exc: BaseException, detail: dict[str, object]) -> None:
        item = {"kind": kind, "error": type(exc).__name__, "detail": str(exc)[:300], **detail}
        if isinstance(exc, (LegalQueryInputError, PlaceQueryError, MunicipalSectionError)):
            errors.append(item)
        else:
            unexpected.append(item)

    audit_county = 0
    audit_named_without_rows = 0
    audit_unincorporated = 0
    audit_territory = 0
    audit_ambiguous_city = 0
    audit_no_county = 0
    county_candidates: list[tuple[str, str, str, str]] = []
    unincorporated: list[tuple[str, str, str, str]] = []
    seen_county: set[tuple[str, str]] = set()
    for index_point, (latitude, longitude) in enumerate(drawn):
        if index_point % 1000 == 0:
            _note(started, f"audit {index_point}/{len(drawn)} errors={len(errors)}")
        located = locate_governments(latitude, longitude)
        try:
            named = query_legal_records(
                jurisdiction="US",
                latitude=latitude,
                longitude=longitude,
                limit=5,
            )
        except LegalQueryInputError as exc:
            if exc.code == "ambiguous_place" and located.status != "one":
                audit_ambiguous_city += 1
                continue
            remember("audit", exc, {"latitude": latitude, "longitude": longitude})
            continue
        except Exception as exc:
            remember("audit", exc, {"latitude": latitude, "longitude": longitude})
            continue
        _check_layers(named, latitude, longitude, errors, "audit")
        if named.records:
            errors.append(
                {
                    "kind": "audit_loaded_rows",
                    "latitude": latitude,
                    "longitude": longitude,
                    "entry_cid": named.records[0].get("entry_cid"),
                }
            )
        city_was_tied = False
        try:
            resolved = resolve_municipal_place(None, latitude, longitude)
        except PlaceQueryError as exc:
            audit_ambiguous_city += 1
            city_was_tied = True
            if exc.code != "ambiguous_place" or not named.place_ambiguous or named.place_name:
                errors.append(
                    {
                        "kind": "ambiguous_city_guessed",
                        "latitude": latitude,
                        "longitude": longitude,
                        "place_name": named.place_name,
                        "code": exc.code,
                    }
                )
            resolved = None
        else:
            if resolved is None:
                if named.place_name or named.place_ambiguous:
                    errors.append(
                        {
                            "kind": "miss_returned_city",
                            "latitude": latitude,
                            "longitude": longitude,
                            "place_name": named.place_name,
                        }
                    )
            elif (
                named.place_name != resolved.name
                or named.place_state != resolved.state_code
                or named.place_ambiguous
            ):
                errors.append(
                    {
                        "kind": "audit_wrong_place",
                        "latitude": latitude,
                        "longitude": longitude,
                        "expected": f"{resolved.name}, {resolved.state_code}",
                        "place_name": named.place_name,
                        "place_state": named.place_state,
                    }
                )
        if located.status != "one" or located.county is None:
            audit_no_county += 1
            continue
        audit_county += 1
        if located.territory is not None:
            audit_territory += 1
        fold = located.county.authority_fold
        if not isinstance(fold, str):
            audit_named_without_rows += 1
            continue
        if resolved is None and not city_was_tied:
            audit_unincorporated += 1
        key = (fold, located.county.state_code)
        if key in seen_county:
            continue
        seen_county.add(key)
        item = (latitude, longitude, fold, located.county.state_code)
        if resolved is None and not city_was_tied:
            unincorporated.append(item)
        elif resolved is not None:
            try:
                city_fold = corpus_authority_fold(resolved.name, resolved.state_code)
            except MunicipalSectionError:
                continue
            if city_fold != fold:
                county_candidates.append(item)
    _note(
        started,
        f"audit done points={len(drawn)} counties={audit_county} errors={len(errors)}",
    )

    for place_index, hit in enumerate(chosen):
        if place_index % 10 == 0:
            _note(started, f"city {place_index}/{len(chosen)} errors={len(errors)}")
        place = next(item for item in places if item.gnis == hit["gnis"])
        searched_states.add(place.state_code)
        rows_in_index = _index_rows(index, place.name, place.state_code)
        if rows_in_index == 0:
            corpus_gaps.append(
                {
                    "name": place.name,
                    "state": place.state_code,
                    "gnis": place.gnis,
                    "latitude": hit["latitude"],
                    "longitude": hit["longitude"],
                }
            )
            continue
        try:
            loaded = load_place_section(constraint_from_place(place))
        except MunicipalSectionError as exc:
            remember("load", exc, {"name": place.name, "state": place.state_code})
            continue
        if not loaded:
            corpus_gaps.append(
                {
                    "name": place.name,
                    "state": place.state_code,
                    "gnis": place.gnis,
                    "latitude": hit["latitude"],
                    "longitude": hit["longitude"],
                    "index_rows": rows_in_index,
                    "loaded_rows": 0,
                }
            )
            continue
        section = list(loaded)
        if len(section) > 2_500:
            section = rng.sample(section, 2_500)
        targets = _rare_targets(section, 4)
        if not targets:
            thin_text.append(
                {
                    "name": place.name,
                    "state": place.state_code,
                    "gnis": place.gnis,
                    "rows": len(section),
                }
            )

        def opener(repo: str, rows: tuple[dict[str, object], ...] = tuple(section)) -> tuple[dict[str, object], ...]:
            assert repo == _REPO
            return rows

        latitude = str(hit["latitude"])
        longitude = str(hit["longitude"])
        if hit.get("kind") == "name":
            point_lat, point_lon = place.latitude, place.longitude
        else:
            point_lat, point_lon = latitude, longitude

        def ask(text: str, retrieval: str):
            if hit.get("kind") == "name":
                return query_legal_records(
                    jurisdiction="US",
                    place=f"{place.name}, {place.state_code}",
                    text_query=text,
                    retrieval=retrieval,
                    limit=20,
                    corpus_opener=opener,
                )
            return _query(latitude, longitude, text, retrieval, opener)

        for target, terms in targets:
            query = " ".join(terms)
            try:
                found = ask(query, "keyword")
            except (LegalQueryInputError, PlaceQueryError, MunicipalSectionError) as exc:
                remember("keyword", exc, {"name": place.name, "state": place.state_code, "query": query})
                continue
            except Exception as exc:
                remember("keyword", exc, {"name": place.name, "state": place.state_code, "query": query})
                continue
            positive_keyword += 1
            _check_city(found, place, errors, "keyword", point_lat, point_lon)
            cids = [row.get("entry_cid") for row in found.records]
            if target["entry_cid"] not in cids:
                errors.append(
                    {
                        "kind": "keyword_miss",
                        "name": place.name,
                        "state": place.state_code,
                        "query": query,
                        "entry_cid": target["entry_cid"],
                        "section": _section(target),
                    }
                )
            else:
                hit_row = next(row for row in found.records if row.get("entry_cid") == target["entry_cid"])
                if _section(hit_row) != _section(target):
                    errors.append(
                        {
                            "kind": "section_changed",
                            "name": place.name,
                            "state": place.state_code,
                            "entry_cid": target["entry_cid"],
                            "stored": _section(target),
                            "returned": _section(hit_row),
                        }
                    )
            vector_query = f"{query} spacecraft"
            try:
                ranked = ask(vector_query, "vector")
            except (LegalQueryInputError, PlaceQueryError, MunicipalSectionError) as exc:
                remember("vector", exc, {"name": place.name, "state": place.state_code, "query": vector_query})
                continue
            except Exception as exc:
                remember("vector", exc, {"name": place.name, "state": place.state_code, "query": vector_query})
                continue
            positive_vector += 1
            _check_city(ranked, place, errors, "vector", point_lat, point_lon)
            ranked_cids = [row.get("entry_cid") for row in ranked.records]
            if target["entry_cid"] not in ranked_cids[:5]:
                errors.append(
                    {
                        "kind": "vector_miss",
                        "name": place.name,
                        "state": place.state_code,
                        "query": vector_query,
                        "entry_cid": target["entry_cid"],
                        "top": ranked_cids[:5],
                    }
                )
        vocabulary = [token for token in document_tokens(section[0]) if len(token) >= 4]
        for row in section[1:40]:
            vocabulary.extend(token for token in document_tokens(row) if len(token) >= 4)
        vocabulary = vocabulary[:400]
        for _ in range(5):
            if len(vocabulary) >= 2:
                query = " ".join(vocabulary[rng.randrange(len(vocabulary))] for _ in range(rng.randint(2, 4)))
            else:
                query = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(10))
            try:
                found = ask(query, "keyword")
                random_keyword += 1
                _check_city(found, place, errors, "random_keyword", point_lat, point_lon)
            except (LegalQueryInputError, PlaceQueryError, MunicipalSectionError) as exc:
                remember("random_keyword", exc, {"name": place.name, "state": place.state_code, "query": query})
            except Exception as exc:
                remember("random_keyword", exc, {"name": place.name, "state": place.state_code, "query": query})
            if len(vocabulary) >= 3:
                vector_query = " ".join(vocabulary[rng.randrange(len(vocabulary))] for _ in range(rng.randint(3, 6)))
            else:
                vector_query = query
            try:
                ranked = ask(vector_query, "vector")
                random_vector += 1
                _check_city(ranked, place, errors, "random_vector", point_lat, point_lon)
            except (LegalQueryInputError, PlaceQueryError, MunicipalSectionError) as exc:
                remember("random_vector", exc, {"name": place.name, "state": place.state_code, "query": vector_query})
            except Exception as exc:
                remember("random_vector", exc, {"name": place.name, "state": place.state_code, "query": vector_query})
        for _ in range(2):
            garbage = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(14))
            for retrieval in ("keyword", "vector"):
                try:
                    found = ask(garbage, retrieval)
                    garbage_queries += 1
                    _check_city(found, place, errors, "garbage", point_lat, point_lon)
                    if retrieval == "keyword" and (
                        found.records or found.county_records or found.territory_records
                    ):
                        errors.append(
                            {
                                "kind": "garbage_hit",
                                "name": place.name,
                                "state": place.state_code,
                                "query": garbage,
                            }
                        )
                except (LegalQueryInputError, PlaceQueryError, MunicipalSectionError) as exc:
                    remember("garbage", exc, {"name": place.name, "state": place.state_code, "query": garbage})
                except Exception as exc:
                    remember("garbage", exc, {"name": place.name, "state": place.state_code, "query": garbage})

    full_candidates = [
        hit
        for hit in chosen
        if hit.get("kind") != "name"
        and 20 <= _index_rows(index, str(hit["name"]), str(hit["state"])) <= 2_000
    ][:_FULL_LOADER]
    for hit in full_candidates:
        place = next(item for item in places if item.gnis == hit["gnis"])
        try:
            loaded = load_place_section(constraint_from_place(place))
        except MunicipalSectionError as exc:
            remember("full_loader", exc, {"name": place.name, "state": place.state_code})
            continue
        targets = _rare_targets(list(loaded), 1)
        if not targets:
            continue
        target, terms = targets[0]
        query = " ".join(terms)
        try:
            found = query_legal_records(
                jurisdiction="US",
                latitude=str(hit["latitude"]),
                longitude=str(hit["longitude"]),
                text_query=query,
                retrieval="keyword",
                limit=20,
            )
        except (LegalQueryInputError, PlaceQueryError, MunicipalSectionError) as exc:
            remember("full_loader", exc, {"name": place.name, "state": place.state_code, "query": query})
            continue
        except Exception as exc:
            remember("full_loader", exc, {"name": place.name, "state": place.state_code, "query": query})
            continue
        full_loader += 1
        _check_city(found, place, errors, "full_loader", str(hit["latitude"]), str(hit["longitude"]))
        if target["entry_cid"] not in {row.get("entry_cid") for row in found.records}:
            errors.append(
                {
                    "kind": "full_loader_miss",
                    "name": place.name,
                    "state": place.state_code,
                    "query": query,
                    "entry_cid": target["entry_cid"],
                }
            )

    def spread(items: list[tuple[str, str, str, str]], limit: int) -> list[tuple[str, str, str, str]]:
        by_state: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
        for item in items:
            by_state[item[3]].append(item)
        picked: list[tuple[str, str, str, str]] = []
        while len(picked) < limit:
            progressed = False
            for state in sorted(by_state):
                bucket = by_state[state]
                if not bucket:
                    continue
                picked.append(bucket.pop())
                progressed = True
                if len(picked) == limit:
                    break
            if not progressed:
                break
        return picked

    county_positive_keyword = 0
    county_positive_vector = 0
    county_random_keyword = 0
    county_random_vector = 0
    unincorporated_keyword = 0
    unincorporated_vector = 0

    def search_county(
        kind: str,
        latitude: str,
        longitude: str,
        fold: str,
        state: str,
        *,
        target_limit: int,
        random_draws: int,
    ) -> None:
        nonlocal county_positive_keyword, county_positive_vector
        nonlocal county_random_keyword, county_random_vector
        nonlocal unincorporated_keyword, unincorporated_vector
        try:
            loaded = load_place_section(PlaceConstraint(name=fold, state_code=state))
        except MunicipalSectionError as exc:
            remember(kind, exc, {"fold": fold, "state": state, "latitude": latitude, "longitude": longitude})
            return
        if not loaded:
            return
        targets = _rare_targets(list(loaded), target_limit)
        try:
            resolved = resolve_municipal_place(None, latitude, longitude)
        except PlaceQueryError:
            resolved = None

        def accept(found, label: str) -> None:
            _check_layers(found, latitude, longitude, errors, label)
            if resolved is None:
                if found.place_name or found.records or found.place_ambiguous:
                    errors.append(
                        {
                            "kind": "county_search_guessed_city",
                            "label": label,
                            "latitude": latitude,
                            "longitude": longitude,
                            "place_name": found.place_name,
                        }
                    )
                return
            if found.place_name != resolved.name or found.place_state != resolved.state_code:
                errors.append(
                    {
                        "kind": "county_search_wrong_city",
                        "label": label,
                        "expected": f"{resolved.name}, {resolved.state_code}",
                        "place_name": found.place_name,
                        "place_state": found.place_state,
                    }
                )
            expected = corpus_authority_fold(resolved.name, resolved.state_code)
            for row in found.records:
                if fold_place(str(row.get("authority"))) != expected or row.get("jurisdiction") != f"US-{resolved.state_code}":
                    errors.append(
                        {
                            "kind": "county_search_city_authority",
                            "label": label,
                            "expected": expected,
                            "authority": row.get("authority"),
                            "entry_cid": row.get("entry_cid"),
                        }
                    )
                    break

        for target, terms in targets:
            query = " ".join(terms)
            for retrieval in ("keyword", "vector"):
                text = query if retrieval == "keyword" else f"{query} spacecraft"
                try:
                    found = query_legal_records(
                        jurisdiction="US",
                        latitude=latitude,
                        longitude=longitude,
                        text_query=text,
                        retrieval=retrieval,
                        limit=20,
                    )
                except (LegalQueryInputError, PlaceQueryError, MunicipalSectionError) as exc:
                    remember(kind, exc, {"fold": fold, "state": state, "query": text})
                    continue
                except Exception as exc:
                    remember(kind, exc, {"fold": fold, "state": state, "query": text})
                    continue
                label = f"{kind}_{retrieval}"
                accept(found, label)
                cids = [row.get("entry_cid") for row in found.county_records]
                wanted = cids if retrieval == "keyword" else cids[:5]
                if target["entry_cid"] not in wanted:
                    errors.append(
                        {
                            "kind": f"{kind}_{retrieval}_miss",
                            "fold": fold,
                            "state": state,
                            "latitude": latitude,
                            "longitude": longitude,
                            "query": text,
                            "entry_cid": target["entry_cid"],
                            "top": cids[:5],
                        }
                    )
                    continue
                if kind == "county" and retrieval == "keyword":
                    county_positive_keyword += 1
                elif kind == "county":
                    county_positive_vector += 1
                elif retrieval == "keyword":
                    unincorporated_keyword += 1
                else:
                    unincorporated_vector += 1
        vocabulary = [token for token in document_tokens(loaded[0]) if len(token) >= 4]
        for row in loaded[1:40]:
            vocabulary.extend(token for token in document_tokens(row) if len(token) >= 4)
        vocabulary = vocabulary[:400]
        for _ in range(random_draws):
            if len(vocabulary) >= 2:
                query = " ".join(vocabulary[rng.randrange(len(vocabulary))] for _ in range(rng.randint(2, 4)))
            else:
                query = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(10))
            try:
                found = query_legal_records(
                    jurisdiction="US",
                    latitude=latitude,
                    longitude=longitude,
                    text_query=query,
                    retrieval="keyword",
                    limit=20,
                )
                accept(found, f"{kind}_random_keyword")
                if kind == "county":
                    county_random_keyword += 1
                else:
                    county_random_keyword += 1
            except (LegalQueryInputError, PlaceQueryError, MunicipalSectionError) as exc:
                remember(kind, exc, {"fold": fold, "state": state, "query": query})
            except Exception as exc:
                remember(kind, exc, {"fold": fold, "state": state, "query": query})
            if len(vocabulary) >= 3:
                vector_query = " ".join(
                    vocabulary[rng.randrange(len(vocabulary))] for _ in range(rng.randint(3, 6))
                )
            else:
                vector_query = query
            try:
                ranked = query_legal_records(
                    jurisdiction="US",
                    latitude=latitude,
                    longitude=longitude,
                    text_query=vector_query,
                    retrieval="vector",
                    limit=20,
                )
                accept(ranked, f"{kind}_random_vector")
                county_random_vector += 1
            except (LegalQueryInputError, PlaceQueryError, MunicipalSectionError) as exc:
                remember(kind, exc, {"fold": fold, "state": state, "query": vector_query})
            except Exception as exc:
                remember(kind, exc, {"fold": fold, "state": state, "query": vector_query})
        garbage = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(14))
        try:
            found = query_legal_records(
                jurisdiction="US",
                latitude=latitude,
                longitude=longitude,
                text_query=garbage,
                retrieval="keyword",
                limit=20,
            )
            accept(found, f"{kind}_garbage")
            if found.records or found.county_records or found.territory_records:
                errors.append(
                    {
                        "kind": "county_garbage_hit",
                        "fold": fold,
                        "state": state,
                        "query": garbage,
                    }
                )
        except (LegalQueryInputError, PlaceQueryError, MunicipalSectionError) as exc:
            remember(kind, exc, {"fold": fold, "state": state, "query": garbage})
        except Exception as exc:
            remember(kind, exc, {"fold": fold, "state": state, "query": garbage})

    for county_index, (latitude, longitude, fold, state) in enumerate(spread(county_candidates, _COUNTY_CORPORA)):
        if county_index % 4 == 0:
            _note(started, f"county {county_index} errors={len(errors)}")
        search_county(
            "county",
            latitude,
            longitude,
            fold,
            state,
            target_limit=2,
            random_draws=2,
        )
    for latitude, longitude, fold, state in spread(unincorporated, _UNINCORPORATED):
        search_county(
            "unincorporated",
            latitude,
            longitude,
            fold,
            state,
            target_limit=1,
            random_draws=1,
        )
    _note(started, f"county search done errors={len(errors)}")

    missing_seed: list[dict[str, str]] = []
    missing_by_state: Counter[str] = Counter()
    prefix_recovered: list[dict[str, str]] = []
    prefix_ambiguous: list[dict[str, str]] = []
    prefix_recovered_count = 0
    prefix_ambiguous_count = 0
    exact_missing = 0
    reachable: set[str] = set()
    for place in places:
        fold, status = resolve_corpus_authority(place.name, place.state_code)
        if status in {"exact", "prefix"}:
            reachable.add(f"{fold}\tUS-{place.state_code}")
        if status == "exact":
            continue
        exact_missing += 1
        item = {
            "name": place.name,
            "state": place.state_code,
            "gnis": place.gnis,
            "latitude": place.latitude,
            "longitude": place.longitude,
            "status": status,
            "corpus_fold": fold,
        }
        if status == "prefix":
            prefix_recovered_count += 1
            if len(prefix_recovered) < 80:
                prefix_recovered.append(item)
            continue
        if status == "ambiguous":
            prefix_ambiguous_count += 1
            if len(prefix_ambiguous) < 40:
                prefix_ambiguous.append(item)
            continue
        missing_by_state[place.state_code] += 1
        if len(missing_seed) < 300:
            missing_seed.append(item)
    unseeded: list[dict[str, object]] = []
    unseeded_rows = 0
    for key, slot in index.items():
        if key in reachable:
            continue
        rows = slot.get("rows") if isinstance(slot, dict) else 0
        if not isinstance(rows, int):
            continue
        unseeded_rows += rows
        authority, _, jurisdiction = key.partition("\t")
        unseeded.append({"authority": authority, "jurisdiction": jurisdiction, "rows": rows})
    unseeded.sort(key=lambda item: -int(item["rows"]))
    query_mod._cached_authority_rows = original_cache
    _note(started, f"finished errors={len(errors)} unexpected={len(unexpected)}")
    return {
        "seed": _SEED,
        "coordinates": coordinates,
        "anchor_points": anchor_points,
        "box_points": _BOX_POINTS,
        "jitter_points": _JITTER_POINTS,
        "resolved_hits": len(hits),
        "unique_hit_places": len(seen_gnis),
        "places_searched": len(chosen),
        "name_searches": sum(1 for hit in chosen if hit.get("kind") == "name"),
        "states_searched": sorted(searched_states),
        "region_draws": dict(sorted(box_counts.items())),
        "outcome_counts": dict(sorted(resolved_counts.items())),
        "ambiguous": ambiguous_count,
        "jitter_switched": switched_count,
        "ambiguous_examples": [item for item in ambiguous if "latitude" in item],
        "miss_examples": miss_examples,
        "jitter_switched_examples": switched,
        "positive_keyword": positive_keyword,
        "positive_vector": positive_vector,
        "random_keyword": random_keyword,
        "random_vector": random_vector,
        "garbage_queries": garbage_queries,
        "full_loader": full_loader,
        "audit_points": len(drawn),
        "audit_with_county": audit_county,
        "audit_county_named_without_rows": audit_named_without_rows,
        "audit_unincorporated": audit_unincorporated,
        "audit_territory": audit_territory,
        "audit_ambiguous_city": audit_ambiguous_city,
        "audit_no_county": audit_no_county,
        "county_corpora_considered": len(county_candidates),
        "unincorporated_counties_considered": len(unincorporated),
        "county_positive_keyword": county_positive_keyword,
        "county_positive_vector": county_positive_vector,
        "county_random_keyword": county_random_keyword,
        "county_random_vector": county_random_vector,
        "unincorporated_keyword": unincorporated_keyword,
        "unincorporated_vector": unincorporated_vector,
        "county_authorities_loaded": len(authority_cache),
        "corpus_gaps": corpus_gaps,
        "thin_text": thin_text[:80],
        "seed_places": len(places),
        "seed_places_exact_missing": exact_missing,
        "prefix_recovered_count": prefix_recovered_count,
        "prefix_recovered": prefix_recovered,
        "prefix_ambiguous_count": prefix_ambiguous_count,
        "prefix_ambiguous": prefix_ambiguous,
        "seed_places_without_rows": sum(missing_by_state.values()),
        "seed_gaps_by_state": dict(sorted(missing_by_state.items())),
        "seed_gap_examples": missing_seed,
        "unseeded_authorities": len(unseeded),
        "unseeded_rows": unseeded_rows,
        "unseeded_examples": unseeded[:100],
        "correctness_errors": errors[:500],
        "correctness_error_count": len(errors),
        "unexpected_exceptions": unexpected[:100],
        "unexpected_exception_count": len(unexpected),
        "elapsed_seconds": int(time.perf_counter() - started),
    }


def test_usa_search_census_collects_failures(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    try:
        municipal_places()
        load_authority_index()
    except MunicipalSectionError:
        pytest.skip("local american v4 tree is not on this machine")
    report = _census()
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    assert report["coordinates"] == _BOX_POINTS + _JITTER_POINTS + report["anchor_points"]
    assert "HI" in report["states_searched"]
    assert "PR" in report["states_searched"]
    assert report["places_searched"] >= 80
    assert report["positive_keyword"] >= 80
    assert report["positive_vector"] >= 80
    assert report["random_keyword"] >= 200
    assert report["random_vector"] >= 200
    assert report["audit_points"] >= _BOX_POINTS
    assert report["audit_with_county"] >= 1000
    assert report["county_positive_keyword"] >= 20
    assert report["county_positive_vector"] >= 20
    assert report["county_random_keyword"] >= 40
    assert report["county_random_vector"] >= 40
    assert report["unincorporated_keyword"] >= 8
    assert report["unexpected_exception_count"] == 0
    assert report["correctness_error_count"] == 0, report["correctness_errors"][:8]
