"""Keyword and vector search from generated coordinates.

The product pin for justicedao/american_municipal_law_norm is readable.
Each trial moves a real city point by a few hundred meters, resolves that
generated coordinate, and checks that both retrieval modes return an
ordinance from that city, including the section stored on the row.
"""

from __future__ import annotations

import json
import random
from collections import Counter

import pytest

from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
    PlaceConstraint,
    PlaceQueryError,
    distance_meters,
    fold_place,
    municipal_places,
    place_matches,
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
from ipfs_datasets_py.processors.legal_data.query_legal_records import (
    LegalQueryDisabled,
    LegalQueryInputError,
    query_legal_records,
)

_REVISION = "df0c0c405bf59cb948d1269dea29767a4712fb81"


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
    if not isinstance(raw, dict):
        return None
    value = raw.get("section")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _isolated_places(limit: int) -> list[object]:
    places = municipal_places()
    index = load_authority_index()
    buckets: dict[tuple[int, int], list[object]] = {}
    for place in places:
        key = (place.lat_micro // 200_000, place.lon_micro // 200_000)
        buckets.setdefault(key, []).append(place)
    names: Counter[tuple[str, str]] = Counter(
        (fold_place(place.name), place.state_code) for place in places
    )
    points: Counter[tuple[int, int]] = Counter(
        (place.lat_micro, place.lon_micro) for place in places
    )
    chosen: list[object] = []
    for place in places:
        if names[(fold_place(place.name), place.state_code)] != 1:
            continue
        if points[(place.lat_micro, place.lon_micro)] != 1:
            continue
        slot = index.get(f"{fold_place(place.name)}\tUS-{place.state_code}")
        rows = slot.get("rows") if isinstance(slot, dict) else 0
        if not isinstance(rows, int) or not 40 <= rows <= 2_500:
            continue
        lat_bucket = place.lat_micro // 200_000
        lon_bucket = place.lon_micro // 200_000
        nearest = None
        tied = False
        for lat_step in range(-2, 3):
            for lon_step in range(-2, 3):
                for other in buckets.get((lat_bucket + lat_step, lon_bucket + lon_step), ()):
                    if other.gnis == place.gnis:
                        continue
                    meters = distance_meters(
                        place.lat_micro,
                        place.lon_micro,
                        other.lat_micro,
                        other.lon_micro,
                    )
                    if nearest is None or meters < nearest:
                        nearest = meters
                        tied = False
                    elif meters == nearest:
                        tied = True
        if tied or nearest is None or nearest < 8_000:
            continue
        chosen.append(place)
        if len(chosen) == limit:
            break
    return chosen


def _target_row(rows: tuple[dict[str, object], ...]) -> tuple[dict[str, object], tuple[str, str]] | None:
    frequencies: Counter[str] = Counter()
    token_rows: list[tuple[dict[str, object], tuple[str, ...]]] = []
    for row in rows:
        if _section(row) is None:
            continue
        text = row.get("text")
        if not isinstance(text, str) or len(text) < 200:
            continue
        tokens = tuple(token for token in document_tokens(row) if len(token) >= 8)
        if len(tokens) < 2:
            continue
        token_rows.append((row, tokens))
        frequencies.update(set(tokens))
    for row, tokens in token_rows:
        rare = [token for token in tokens if frequencies[token] == 1]
        if len(rare) >= 2:
            return row, (rare[0], rare[1])
    return None


def test_flag_off_still_rejects_a_coordinate_search(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "0")
    with pytest.raises(LegalQueryDisabled):
        query_legal_records(
            jurisdiction="US",
            latitude="39.399000",
            longitude="-84.561000",
            text_query="zoning",
            retrieval="keyword",
        )


def test_tied_coordinate_does_not_guess_a_section(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    from ipfs_datasets_py.processors.legal_data.county_geography import (
        locate_governments,
    )

    located = locate_governments("34.26778", "-119.254206")
    if located.status != "one":
        with pytest.raises(LegalQueryInputError) as raised:
            query_legal_records(
                jurisdiction="US",
                latitude="34.26778",
                longitude="-119.254206",
                text_query="zoning",
                retrieval="vector",
            )
        assert raised.value.code == "ambiguous_place"
        return
    found = query_legal_records(
        jurisdiction="US",
        latitude="34.26778",
        longitude="-119.254206",
        text_query="zoning",
        retrieval="vector",
        limit=5,
    )
    assert found.place_name is None
    assert found.place_state is None
    assert found.place_ambiguous is True
    assert found.records == ()
    assert found.county_name == "Ventura County"
    assert found.county_state == "CA"
    assert found.territory_name is None
    for row in found.county_records:
        assert fold_place(str(row.get("authority"))) == "ventura county"
        assert row.get("jurisdiction") == "US-CA"


def test_generated_coordinates_retrieve_that_city(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    try:
        places = _isolated_places(40)
    except MunicipalSectionError:
        pytest.skip("local american v4 tree is not on this machine")
    assert len(places) >= 8, len(places)
    rng = random.Random(20261019)
    checked = 0
    failures: list[str] = []
    for place in places:
        if checked == 8:
            break
        lat_micro = place.lat_micro + rng.randint(-5_000, 5_000)
        lon_micro = place.lon_micro + rng.randint(-5_000, 5_000)
        if (lat_micro, lon_micro) == (place.lat_micro, place.lon_micro):
            lat_micro += 1_000
        latitude = _micro(lat_micro)
        longitude = _micro(lon_micro)
        resolved = resolve_municipal_place(None, latitude, longitude)
        if resolved is None or resolved.gnis != place.gnis:
            failures.append(f"{place.name} {place.state_code} resolved {resolved}")
            continue
        moved = distance_meters(place.lat_micro, place.lon_micro, lat_micro, lon_micro)
        if moved == 0 or moved > 2_000:
            failures.append(f"{place.name} moved {moved} m")
            continue
        from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
            constraint_from_place,
        )

        section = load_place_section(constraint_from_place(place))
        picked = _target_row(section)
        if picked is None:
            continue
        target, terms = picked
        query = " ".join(terms)
        keyword = query_legal_records(
            jurisdiction="US",
            latitude=latitude,
            longitude=longitude,
            text_query=query,
            retrieval="keyword",
            limit=20,
        )
        vector = query_legal_records(
            jurisdiction="US",
            latitude=latitude,
            longitude=longitude,
            text_query=f"{query} spacecraft",
            retrieval="vector",
            limit=20,
        )
        keyword_cids = [row.get("entry_cid") for row in keyword.records]
        vector_cids = [row.get("entry_cid") for row in vector.records]
        if keyword.source_revision != _REVISION or vector.source_revision != _REVISION:
            failures.append(f"{place.name} revision {keyword.source_revision}")
        if keyword.place_name != place.name or keyword.place_state != place.state_code:
            failures.append(
                f"{place.name} keyword place {keyword.place_name} {keyword.place_state}"
            )
        if keyword.place_ambiguous or vector.place_ambiguous:
            failures.append(f"{place.name} marked ambiguous")
        for label, result in (("keyword", keyword), ("vector", vector)):
            if result.county_name and result.county_state != place.state_code:
                failures.append(
                    f"{place.name} {label} county {result.county_name} {result.county_state}"
                )
        if target["entry_cid"] not in keyword_cids:
            failures.append(f"{place.name} keyword missed {terms}")
        if not vector.records or vector.records[0].get("entry_cid") != target["entry_cid"]:
            failures.append(f"{place.name} vector top {vector_cids[:3]}")
        for label, result in (("keyword", keyword), ("vector", vector)):
            for row in result.records:
                if row.get("jurisdiction") != f"US-{place.state_code}":
                    failures.append(f"{place.name} {label} jurisdiction {row.get('jurisdiction')}")
                if fold_place(str(row.get("authority"))) != fold_place(place.name):
                    failures.append(f"{place.name} {label} authority {row.get('authority')}")
        hits = [row for row in keyword.records if row.get("entry_cid") == target["entry_cid"]]
        if hits and _section(hits[0]) != _section(target):
            failures.append(f"{place.name} section {_section(hits[0])}")
        checked += 1
    assert checked >= 8, checked
    assert failures == [], failures


def test_generated_miss_returns_no_city(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    missed = query_legal_records(
        jurisdiction="US",
        latitude="0.000000",
        longitude="0.000000",
        text_query="zoning",
        retrieval="keyword",
    )
    assert missed.place_name is None
    assert missed.place_ambiguous is False
    assert missed.records == ()
    assert missed.county_name is None
    assert missed.county_records == ()
    assert missed.territory_name is None
    index = load_authority_index()
    rng = random.Random(19)
    seen = 0
    for _ in range(40):
        if seen == 6:
            break
        latitude = _micro(rng.randint(25_000_000, 48_000_000))
        longitude = _micro(-rng.randint(70_000_000, 124_000_000))
        try:
            resolved = resolve_municipal_place(None, latitude, longitude)
        except PlaceQueryError as exc:
            assert exc.code == "ambiguous_place"
            try:
                found = query_legal_records(
                    jurisdiction="US",
                    latitude=latitude,
                    longitude=longitude,
                    text_query="ordinance",
                    retrieval="keyword",
                    limit=5,
                )
            except LegalQueryInputError as raised:
                assert raised.value.code == "ambiguous_place"
            else:
                assert found.place_name is None
                assert found.place_ambiguous is True
                assert found.records == ()
                for row in found.county_records:
                    assert row.get("jurisdiction") == f"US-{found.county_state}"
            seen += 1
            continue
        if resolved is None:
            found = query_legal_records(
                jurisdiction="US",
                latitude=latitude,
                longitude=longitude,
                text_query="ordinance",
                retrieval="keyword",
                limit=5,
            )
            assert found.place_name is None
            assert found.records == ()
            seen += 1
            continue
        folded = corpus_authority_fold(resolved.name, resolved.state_code)
        slot = index.get(f"{folded}\tUS-{resolved.state_code}")
        rows = slot.get("rows") if isinstance(slot, dict) else 0
        if not isinstance(rows, int) or rows == 0 or rows > 1_500:
            continue
        found = query_legal_records(
            jurisdiction="US",
            latitude=latitude,
            longitude=longitude,
            text_query="ordinance",
            retrieval="keyword",
            limit=5,
        )
        assert found.place_name == resolved.name
        assert found.place_state == resolved.state_code
        for row in found.records:
            assert row.get("jurisdiction") == f"US-{resolved.state_code}"
            assert fold_place(str(row.get("authority"))) == folded
        seen += 1
    assert seen == 6


def test_unique_prefix_reads_the_stored_authority(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    try:
        load_authority_index()
    except MunicipalSectionError:
        pytest.skip("local american v4 tree is not on this machine")
    assert resolve_corpus_authority("City of Louisville", "KY") == ("louisville", "prefix")
    assert resolve_corpus_authority("City of Spokane", "WA") == ("spokane", "prefix")
    assert resolve_corpus_authority("City of Hamilton", "OH")[0] == "city of hamilton"
    assert resolve_corpus_authority("Ventura", "CA") == ("ventura", "exact")
    assert resolve_corpus_authority("City of San Buenaventura", "CA")[1] == "absent"
    assert resolve_corpus_authority("City of Chula Vista", "CA")[1] == "absent"
    assert place_matches(
        {"authority": "Louisville", "jurisdiction": "US-KY"},
        PlaceConstraint(name="City of Louisville", state_code="KY"),
    )
    assert not place_matches(
        {"authority": "Ventura", "jurisdiction": "US-CA"},
        PlaceConstraint(name="City of San Buenaventura", state_code="CA"),
    )
    assert place_matches(
        {"authority": "City of Hamilton", "jurisdiction": "US-OH"},
        PlaceConstraint(name="City of Hamilton", state_code="OH"),
    )
    loaded = load_place_section(PlaceConstraint(name="City of Louisville", state_code="KY"))
    assert loaded
    assert {fold_place(str(row["authority"])) for row in loaded} == {"louisville"}
    assert {row["jurisdiction"] for row in loaded} == {"US-KY"}
    token = next(token for token in document_tokens(loaded[0]) if len(token) >= 4)
    found = query_legal_records(
        jurisdiction="US",
        place="City of Louisville, KY",
        text_query=token,
        retrieval="keyword",
        limit=5,
    )
    assert found.place_name == "City of Louisville"
    assert found.place_state == "KY"
    assert found.records
    assert {fold_place(str(row["authority"])) for row in found.records} == {"louisville"}
    assert found.county_name == "Jefferson County"
    assert found.county_state == "KY"
    assert found.county_records == ()
    from ipfs_datasets_py.processors.legal_data.county_geography import (
        locate_governments,
    )

    located = locate_governments("38.256111111111", "-85.751388888889")
    if located.status != "one":
        with pytest.raises(LegalQueryInputError) as tied:
            query_legal_records(
                jurisdiction="US",
                latitude="38.256111111111",
                longitude="-85.751388888889",
                text_query=token,
                retrieval="keyword",
                limit=5,
            )
        assert tied.value.code == "ambiguous_place"
        return
    tied_point = query_legal_records(
        jurisdiction="US",
        latitude="38.256111111111",
        longitude="-85.751388888889",
        text_query=token,
        retrieval="keyword",
        limit=5,
    )
    assert tied_point.place_name is None
    assert tied_point.place_ambiguous is True
    assert tied_point.records == ()
    assert tied_point.county_name == "Jefferson County"
    assert tied_point.county_state == "KY"
    assert located.county is not None
    assert located.county.authority_fold is None
    assert tied_point.county_records == ()
