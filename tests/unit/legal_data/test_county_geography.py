"""A requested coordinate also names the county and the territory.

City ordinances stay in records. County and territory ordinances are
separate. A tied city is not guessed. A government with no stored
authority is named and its rows stay empty.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_data.county_geography import (
    CountyGeographyError,
    locate_governments,
    ring_contains,
)
from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
    fold_place,
    resolve_municipal_place,
)
from ipfs_datasets_py.processors.legal_data.municipal_section_search import (
    MunicipalSectionError,
    load_authority_index,
)
from ipfs_datasets_py.processors.legal_data.query_legal_records import (
    LegalQueryInputError,
    query_legal_records,
)


@pytest.fixture(autouse=True)
def _normalized_query(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")


def _ready() -> None:
    try:
        load_authority_index()
    except MunicipalSectionError:
        pytest.skip("local american v4 tree is not on this machine")
    if locate_governments("34.05223", "-118.24368").status == "unindexed":
        pytest.skip("county boundary index is not on this machine")


def _folds(rows: tuple[dict[str, object], ...]) -> set[str]:
    return {fold_place(str(row.get("authority"))) for row in rows}


def test_ring_contains_counts_the_boundary() -> None:
    square = ((0, 0), (10, 0), (10, 10), (0, 10), (0, 0))
    assert ring_contains(5, 5, square)
    assert ring_contains(0, 5, square)
    assert ring_contains(10, 10, square)
    assert not ring_contains(11, 5, square)
    assert not ring_contains(5, -1, square)


def test_polygons_name_the_government_that_contains_the_point() -> None:
    _ready()
    los_angeles = locate_governments("34.05223", "-118.24368")
    assert los_angeles.status == "one"
    assert los_angeles.county is not None
    assert los_angeles.county.name == "Los Angeles County"
    assert los_angeles.county.state_code == "CA"
    assert los_angeles.county.authority_fold == "los angeles county"
    assert los_angeles.territory is None

    honolulu = locate_governments("21.306944", "-157.858333")
    assert honolulu.status == "one"
    assert honolulu.county is not None
    assert honolulu.county.name == "Honolulu County"
    assert honolulu.county.authority_fold == "city and county of honolulu"
    assert honolulu.territory is None

    anchorage = locate_governments("61.2181", "-149.9003")
    assert anchorage.county is not None
    assert anchorage.county.name == "Anchorage Municipality"
    assert anchorage.county.authority_fold == "municipality of anchorage"

    orleans = locate_governments("29.9511", "-90.0715")
    assert orleans.county is not None
    assert orleans.county.name == "Orleans Parish"
    assert orleans.county.authority_fold is None

    baltimore = locate_governments("39.2904", "-76.6122")
    assert baltimore.county is not None
    assert baltimore.county.name == "Baltimore city"
    assert baltimore.county.state_code == "MD"
    assert baltimore.county.authority_fold == "city of baltimore"

    district = locate_governments("38.895", "-77.036666666667")
    assert district.county is not None
    assert district.county.name == "District of Columbia"
    assert district.county.authority_fold is None
    assert district.territory is None

    san_juan = locate_governments("18.465277777778", "-66.116666666667")
    assert san_juan.county is not None
    assert san_juan.county.name == "San Juan Municipio"
    assert san_juan.county.authority_fold == "san juan"
    assert san_juan.territory is not None
    assert san_juan.territory.name == "Puerto Rico"
    assert san_juan.territory.state_code == "PR"
    assert san_juan.territory.authority_fold is None

    assert locate_governments("41.7637", "-72.6851").status == "none"
    assert locate_governments("0", "0").status == "none"
    border = locate_governments("31.000884", "-85.243632")
    assert border.status == "ambiguous"
    assert border.county is None


def test_missing_index_does_not_guess_a_tied_city(monkeypatch) -> None:
    def unavailable() -> tuple[object, ...]:
        raise CountyGeographyError("county boundary index is not on this machine")

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.county_geography._load_areas",
        unavailable,
    )
    with pytest.raises(LegalQueryInputError) as raised:
        query_legal_records(
            jurisdiction="US",
            latitude="34.26778",
            longitude="-119.254206",
            text_query="zoning",
            retrieval="keyword",
        )
    assert raised.value.code == "ambiguous_place"


def test_shared_border_does_not_choose_a_county() -> None:
    _ready()
    latitude = "31.000884"
    longitude = "-85.243632"
    resolved = resolve_municipal_place(None, latitude, longitude)
    assert resolved is not None
    found = query_legal_records(
        jurisdiction="US",
        latitude=latitude,
        longitude=longitude,
        limit=3,
    )
    assert found.place_name == resolved.name
    assert found.place_state == resolved.state_code
    assert found.place_ambiguous is False
    assert found.records == ()
    assert found.county_name is None
    assert found.county_records == ()
    assert found.territory_name is None


def test_naming_the_county_keeps_that_government() -> None:
    _ready()
    named = query_legal_records(
        jurisdiction="US",
        place="Ventura County",
        text_query="the",
        retrieval="keyword",
        limit=3,
    )
    assert named.place_name == "Ventura County"
    assert named.county_name is None
    assert named.county_records == ()
    assert named.territory_name is None
    assert named.records
    assert _folds(named.records) == {"ventura county"}


def test_city_name_returns_the_city_and_its_county() -> None:
    _ready()
    found = query_legal_records(
        jurisdiction="US",
        place="Ventura",
        text_query="the",
        retrieval="keyword",
        limit=4,
    )
    assert found.place_name == "Ventura"
    assert found.place_state == "CA"
    assert found.records
    assert _folds(found.records) == {"ventura"}
    assert found.county_name == "Ventura County"
    assert found.county_state == "CA"
    assert found.county_records
    assert _folds(found.county_records) == {"ventura county"}
    assert {row.get("entry_cid") for row in found.records}.isdisjoint(
        {row.get("entry_cid") for row in found.county_records}
    )
    assert found.territory_name is None


def test_coordinate_returns_the_city_and_the_county() -> None:
    _ready()
    found = query_legal_records(
        jurisdiction="US",
        place="Ventura",
        latitude="34.26778",
        longitude="-119.254206",
        text_query="the",
        retrieval="keyword",
        limit=4,
    )
    assert found.place_name == "Ventura"
    assert found.place_state == "CA"
    assert found.place_ambiguous is False
    assert found.records
    assert _folds(found.records) == {"ventura"}
    assert {row.get("jurisdiction") for row in found.records} == {"US-CA"}
    assert found.county_name == "Ventura County"
    assert found.county_state == "CA"
    assert found.county_records
    assert _folds(found.county_records) == {"ventura county"}
    assert {row.get("jurisdiction") for row in found.county_records} == {"US-CA"}
    assert found.territory_name is None
    city_ids = {row.get("entry_cid") for row in found.records}
    county_ids = {row.get("entry_cid") for row in found.county_records}
    assert city_ids.isdisjoint(county_ids)
    assert all(row.get("text") for row in found.county_records)


def test_unincorporated_point_returns_the_county() -> None:
    _ready()
    found = query_legal_records(
        jurisdiction="US",
        latitude="20.7984",
        longitude="-156.3319",
        text_query="the",
        retrieval="keyword",
        limit=3,
    )
    assert found.place_name is None
    assert found.place_ambiguous is False
    assert found.records == ()
    assert found.county_name == "Maui County"
    assert found.county_state == "HI"
    assert found.county_records
    assert _folds(found.county_records) == {"maui county"}
    assert {row.get("jurisdiction") for row in found.county_records} == {"US-HI"}
    assert found.territory_name is None


def test_planning_region_is_not_a_county() -> None:
    _ready()
    found = query_legal_records(
        jurisdiction="US",
        latitude="41.7637",
        longitude="-72.6851",
        text_query="the",
        retrieval="keyword",
        limit=3,
    )
    assert found.place_name == "City of Hartford"
    assert found.place_state == "CT"
    assert found.records
    assert _folds(found.records) == {"city of hartford"}
    assert found.county_name is None
    assert found.county_records == ()
    assert found.territory_name is None


def test_territory_is_named_without_invented_statutes() -> None:
    _ready()
    found = query_legal_records(
        jurisdiction="US",
        latitude="18.465277777778",
        longitude="-66.116666666667",
        text_query="the",
        retrieval="keyword",
        limit=5,
    )
    assert found.place_name == "San Juan"
    assert found.place_state == "PR"
    assert found.records
    assert _folds(found.records) == {"san juan"}
    assert found.county_name == "San Juan Municipio"
    assert found.county_state == "PR"
    assert found.county_records == ()
    assert found.territory_name == "Puerto Rico"
    assert found.territory_state == "PR"
    assert found.territory_records == ()


def test_independent_city_is_not_the_surrounding_county() -> None:
    _ready()
    found = query_legal_records(
        jurisdiction="US",
        latitude="39.2904",
        longitude="-76.6122",
        text_query="the",
        retrieval="keyword",
        limit=5,
    )
    assert found.place_name == "City of Baltimore"
    assert found.place_state == "MD"
    assert found.records
    assert _folds(found.records) == {"city of baltimore"}
    assert found.county_name == "Baltimore city"
    assert found.county_state == "MD"
    assert found.county_records == ()
    assert found.territory_name is None
    assert "baltimore county" not in _folds(found.records)


def test_district_is_a_county_equivalent() -> None:
    _ready()
    found = query_legal_records(
        jurisdiction="US",
        latitude="38.895",
        longitude="-77.036666666667",
        text_query="the",
        retrieval="keyword",
        limit=5,
    )
    assert found.place_name == "City of Washington"
    assert found.place_state == "DC"
    assert found.records
    assert _folds(found.records) == {"city of washington"}
    assert found.county_name == "District of Columbia"
    assert found.county_state == "DC"
    assert found.county_records == ()
    assert found.territory_name is None
    assert found.territory_records == ()


def test_parish_name_does_not_relabel_the_city() -> None:
    _ready()
    city = query_legal_records(
        jurisdiction="US",
        latitude="29.9511",
        longitude="-90.0715",
        text_query="the",
        retrieval="keyword",
        limit=3,
    )
    assert city.place_name == "City of New Orleans"
    assert city.place_state == "LA"
    assert city.records
    assert _folds(city.records) == {"city of new orleans"}
    assert city.county_name == "Orleans Parish"
    assert city.county_state == "LA"
    assert city.county_records == ()
    assert city.territory_name is None

    parish = query_legal_records(
        jurisdiction="US",
        latitude="29.9841",
        longitude="-90.1528",
        text_query="the",
        retrieval="keyword",
        limit=3,
    )
    assert parish.place_name == "City of Harahan"
    assert parish.place_state == "LA"
    assert parish.records
    assert _folds(parish.records) == {"city of harahan"}
    assert parish.county_name == "Jefferson Parish"
    assert parish.county_state == "LA"
    assert parish.county_records
    assert _folds(parish.county_records) == {"jefferson"}
    assert {row.get("jurisdiction") for row in parish.county_records} == {"US-LA"}
    city_ids = {row.get("entry_cid") for row in parish.records}
    parish_ids = {row.get("entry_cid") for row in parish.county_records}
    assert city_ids.isdisjoint(parish_ids)


def test_county_without_a_corpus_is_named() -> None:
    _ready()
    found = query_legal_records(
        jurisdiction="US",
        latitude="39.395833333333",
        longitude="-84.565",
        text_query="the",
        retrieval="keyword",
        limit=3,
    )
    assert found.place_name == "City of Hamilton"
    assert found.place_state == "OH"
    assert found.records
    assert _folds(found.records) == {"city of hamilton"}
    assert found.county_name == "Butler County"
    assert found.county_state == "OH"
    assert found.county_records == ()
    assert found.territory_name is None

    elsewhere = query_legal_records(
        jurisdiction="US",
        place="Ventura",
        latitude="39.395833333333",
        longitude="-84.565",
        text_query="the",
        retrieval="keyword",
        limit=3,
    )
    assert elsewhere.place_name is None
    assert elsewhere.records == ()
    assert elsewhere.county_name == "Butler County"
    assert elsewhere.county_state == "OH"
    assert elsewhere.county_records == ()
