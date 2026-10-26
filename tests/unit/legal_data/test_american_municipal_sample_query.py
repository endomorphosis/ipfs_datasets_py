"""Sample real American municipal rows and query them back.

The rows come from the local v4 tree of snapshot 24cac8b72a91. Each part
below is one 20,000-row shard. The opener holds only the named ordinances
plus one neighboring city from that shard, so the query has to keep the
requested place, section, and date apart from real lookalikes. This does
not mark a pin searchable and does not turn the query flag on outside the
test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.query_legal_records import (
    LegalQueryDisabled,
    query_legal_records,
)

_TREE = Path(
    "/home/barberb/.ipfs_datasets/country-laws-ir/norm-export/"
    "24cac8b72a91f1c196bef47a8bd0398b103f26ba/american_municipal_law_v4"
)
_PARTS = (
    "part-0000",
    "part-0001",
    "part-0450",
    "part-0815",
    "part-0818",
    "part-0848",
)
_PIN = "c" * 40
# These entry ids were read from the v4 tree. They are the sample, not a guess.
HAMILTON = "bafkreidv7v36nziazhrgnteywosdvepjldsftmyssgcu6wt2rptxrjwwja"
VENTURA = "bafkreibhwy7msj2pgqs7bbqbqo2crnbvtxgrfzypkxodj4tkcvkrr2vghe"
COUNTY = "bafkreibwjofzetxd4io6bwhub2aflbxsriuxulexsvdrbpsuz2wytxatym"
IOWA = "bafkreifihbbkbejxpa4mawzuenewlycqmvogynr44o5y6jdold6x2ukwvq"
PITTSBURGH = "bafkreiblbboocb2u2ayufcbl4zvjsycqdqzxlh7qgk2rssymj5agtoaliy"
SNOHOMISH = "bafkreif2f5nlip7rqx6gybbczoskmi6c3dz2mqcdzj4yisivtci5nsnzpu"
SNOHOMISH_DATED = "bafkreidbslo7xwfqzpxzcp2wdvb3qe5shs37lqjfrbybkwhj4wx2dk2cve"
_WANTED = {
    HAMILTON,
    VENTURA,
    COUNTY,
    IOWA,
    PITTSBURGH,
    SNOHOMISH,
    SNOHOMISH_DATED,
}


def _load_sample() -> tuple[dict[str, object], ...]:
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    if not (_TREE / "manifest.json").is_file():
        pytest.skip("local american v4 tree is not on this machine")
    manifest = json.loads((_TREE / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("normalizer_version") != "american-municipal-html/v4+legal-record/v1":
        pytest.fail("sample tree is not american-municipal-html/v4")
    if manifest.get("source_revision") != "24cac8b72a91f1c196bef47a8bd0398b103f26ba":
        pytest.fail("sample tree is not snapshot 24cac8b72a91")
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    wanted = pa.array(sorted(_WANTED))
    for part in _PARTS:
        table = pq.read_table(_TREE / "data" / part / "laws.parquet")
        picked = table.filter(pc.is_in(table.column("entry_cid"), value_set=wanted))
        chosen = picked.to_pylist()
        rows.extend(chosen)
        seen.update(str(row["entry_cid"]) for row in chosen)
        pairs = {
            (row.get("authority"), row.get("jurisdiction"))
            for row in chosen
        }
        authorities = table.column("authority").to_pylist()
        jurisdictions = table.column("jurisdiction").to_pylist()
        for index, pair in enumerate(zip(authorities, jurisdictions)):
            if pair in pairs or not pair[0]:
                continue
            rows.append(table.slice(index, 1).to_pylist()[0])
            break
    missing = _WANTED - seen
    if missing:
        pytest.fail(f"sample rows missing from the v4 tree: {sorted(missing)}")
    return tuple(rows)


@pytest.fixture(scope="module")
def sample_rows() -> tuple[dict[str, object], ...]:
    return _load_sample()


@pytest.fixture
def municipal_query(monkeypatch, sample_rows):
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")

    def readable(repo: str) -> bool:
        return repo == "american_municipal_law_norm"

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.query_legal_records.pin_readable",
        readable,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.query_legal_records.pin_revision",
        lambda repo: _PIN if repo == "american_municipal_law_norm" else None,
    )
    calls: list[str] = []

    def opener(repo: str) -> tuple[dict[str, object], ...]:
        calls.append(repo)
        return sample_rows

    return opener, calls


def _row(rows: tuple[dict[str, object], ...], entry_cid: str) -> dict[str, object]:
    return next(row for row in rows if row["entry_cid"] == entry_cid)


def _provenance(row: dict[str, object]) -> dict[str, object]:
    raw = row.get("provenance")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    return {}


def _property(document: dict[str, object], property_id: str) -> str | None:
    raw = document.get("additionalProperty")
    if not isinstance(raw, list):
        return None
    for item in raw:
        if isinstance(item, dict) and item.get("propertyID") == property_id:
            value = item.get("value")
            return value if isinstance(value, str) else None
    return None


def test_place_name_keeps_ventura_city_county_and_iowa_apart(municipal_query, sample_rows) -> None:
    opener, calls = municipal_query
    city = query_legal_records(jurisdiction="US", place="Ventura", limit=20, corpus_opener=opener)
    assert calls == ["justicedao/american_municipal_law_norm"]
    assert city.jurisdiction == "US"
    assert city.place_name == "Ventura"
    assert city.place_state == "CA"
    assert city.place_latitude == "34.26778"
    assert city.place_longitude == "-119.254206"
    assert city.territory_name is None
    assert city.county_name == "Ventura County"
    assert city.county_state == "CA"
    assert COUNTY in {row["entry_cid"] for row in city.county_records}
    assert {row["authority"] for row in city.county_records} == {"Ventura County"}
    assert VENTURA in {row["entry_cid"] for row in city.records}
    assert COUNTY not in {row["entry_cid"] for row in city.records}
    assert IOWA not in {row["entry_cid"] for row in city.records}
    assert {row["authority"] for row in city.records} == {"Ventura"}
    assert {row["jurisdiction"] for row in city.records} == {"US-CA"}
    source = _row(sample_rows, VENTURA)
    hit = next(row for row in city.records if row["entry_cid"] == VENTURA)
    assert hit["citation"] == source["citation"]
    assert hit["text"] == source["text"]
    assert "County Code" not in str(hit["citation"])

    county = query_legal_records(
        jurisdiction="US",
        place="Ventura County",
        limit=20,
        corpus_opener=opener,
    )
    assert county.place_name == "Ventura County"
    assert county.place_state is None
    assert county.place_latitude is None
    assert {row["entry_cid"] for row in county.records} == {
        row["entry_cid"]
        for row in sample_rows
        if row.get("authority") == "Ventura County"
    }
    county_hit = next(row for row in county.records if row["entry_cid"] == COUNTY)
    assert county_hit["citation"] == _row(sample_rows, COUNTY)["citation"]
    assert "County Code" in str(county_hit["citation"])

    iowa = query_legal_records(
        jurisdiction="US",
        place="City of Ventura",
        limit=20,
        corpus_opener=opener,
    )
    assert iowa.place_name == "City of Ventura"
    assert iowa.place_state == "IA"
    assert [row["entry_cid"] for row in iowa.records] == [IOWA]
    assert iowa.county_name == "Cerro Gordo County"
    assert iowa.county_state == "IA"
    assert iowa.county_records == ()


def test_coordinates_select_the_sampled_city(municipal_query) -> None:
    opener, calls = municipal_query
    # The seed gives this point to both Ventura and City of San Buenaventura.
    # A coordinate alone must not guess between them. The county polygon is
    # still Ventura County.
    from ipfs_datasets_py.processors.legal_data.county_geography import (
        locate_governments,
    )
    from ipfs_datasets_py.processors.legal_data.query_legal_records import (
        LegalQueryInputError,
    )

    located = locate_governments("34.26778", "-119.254206")
    if located.status != "one":
        with pytest.raises(LegalQueryInputError) as tied:
            query_legal_records(
                jurisdiction="US",
                latitude="34.26778",
                longitude="-119.254206",
                corpus_opener=opener,
            )
        assert tied.value.code == "ambiguous_place"
    else:
        tied_point = query_legal_records(
            jurisdiction="US",
            latitude="34.26778",
            longitude="-119.254206",
            corpus_opener=opener,
        )
        assert tied_point.place_name is None
        assert tied_point.place_ambiguous is True
        assert tied_point.records == ()
        assert tied_point.county_name == "Ventura County"
        assert tied_point.county_state == "CA"
        assert tied_point.county_records
        assert {row["authority"] for row in tied_point.county_records} == {"Ventura County"}
        assert tied_point.territory_name is None
    assert calls == []
    ventura = query_legal_records(
        jurisdiction="US",
        place="Ventura",
        latitude="34.26778",
        longitude="-119.254206",
        limit=20,
        corpus_opener=opener,
    )
    assert ventura.place_name == "Ventura"
    assert ventura.place_state == "CA"
    assert ventura.place_ambiguous is False
    assert {row["authority"] for row in ventura.records} == {"Ventura"}
    assert VENTURA in {row["entry_cid"] for row in ventura.records}
    if located.status == "one":
        assert ventura.county_name == "Ventura County"
        assert ventura.county_state == "CA"
        assert ventura.county_records
        assert {row["authority"] for row in ventura.county_records} == {"Ventura County"}
        assert VENTURA not in {row["entry_cid"] for row in ventura.county_records}
    ohio = query_legal_records(
        jurisdiction="US",
        place="City of Hamilton",
        latitude="39.395833333333",
        longitude="-84.565",
        limit=20,
        corpus_opener=opener,
    )
    assert ohio.place_state == "OH"
    assert {row["jurisdiction"] for row in ohio.records} == {"US-OH"}
    assert HAMILTON in {row["entry_cid"] for row in ohio.records}
    mismatch = query_legal_records(
        jurisdiction="US",
        place="Ventura",
        latitude="39.395833333333",
        longitude="-84.565",
        corpus_opener=opener,
    )
    assert mismatch.records == ()
    assert mismatch.place_name is None


def test_section_and_date_return_the_sampled_ordinance(municipal_query, sample_rows) -> None:
    opener, _calls = municipal_query
    county = query_legal_records(
        jurisdiction="US",
        place="Ventura County",
        chapter="2",
        section="1231",
        subsection="a",
        as_of="2009-02-24",
        representation="jsonld",
        corpus_opener=opener,
    )
    assert len(county.records) == 1
    document = county.records[0]
    source = _row(sample_rows, COUNTY)
    assert document["@type"] == "Legislation"
    assert document["legislationDate"] == "2009-02-24"
    assert document["legislationJurisdiction"] == "US-CA"
    assert document["legislationIdentifier"] == source["citation"]
    assert _property(document, "section") == "1231"
    assert _property(document, "subsection") == "a, b"
    assert _property(document, "authority") == "Ventura County"
    assert "dateModified" not in document
    assert document["text"]
    early = query_legal_records(
        jurisdiction="US",
        place="Ventura County",
        section="1231",
        as_of="2009-02-23",
        corpus_opener=opener,
    )
    assert early.records == ()
    other_subsection = query_legal_records(
        jurisdiction="US",
        place="Ventura County",
        section="1231",
        subsection="c",
        corpus_opener=opener,
    )
    assert other_subsection.records == ()

    city = query_legal_records(
        jurisdiction="US",
        place="Ventura",
        chapter="1",
        section="3101",
        as_of="2024-09-24",
        corpus_opener=opener,
    )
    assert [row["entry_cid"] for row in city.records] == [VENTURA]
    assert city.records[0]["citation"] == _row(sample_rows, VENTURA)["citation"]
    assert city.records[0]["effective_date"] == "2024-09-24"

    hamilton = query_legal_records(
        jurisdiction="US",
        place="Hamilton, Ohio",
        section="3.11",
        as_of="2020-11-03",
        representation="jsonld",
        corpus_opener=opener,
    )
    assert len(hamilton.records) == 1
    assert hamilton.records[0]["legislationDate"] == "2020-11-03"
    assert hamilton.records[0]["legislationJurisdiction"] == "US-OH"
    assert _property(hamilton.records[0], "authority") == "City of Hamilton"
    assert _property(hamilton.records[0], "section") == "3.11"
    before = query_legal_records(
        jurisdiction="US",
        place="Hamilton, OH",
        section="3.11",
        as_of="2020-11-02",
        corpus_opener=opener,
    )
    assert before.records == ()


def test_pittsburgh_and_snohomish_samples_round_trip(municipal_query, sample_rows) -> None:
    opener, _calls = municipal_query
    pittsburgh = query_legal_records(
        jurisdiction="US",
        place="Pittsburgh, Pennsylvania",
        title="CHA",
        section="104",
        as_of="2025-02-14",
        corpus_opener=opener,
    )
    assert [row["entry_cid"] for row in pittsburgh.records] == [PITTSBURGH]
    assert pittsburgh.records[0]["jurisdiction"] == "US-PA"
    assert pittsburgh.records[0]["authority"] == "City of Pittsburgh"
    assert pittsburgh.records[0]["effective_date"] == _row(sample_rows, PITTSBURGH)["effective_date"]
    assert _provenance(pittsburgh.records[0]).get("title") == "CHA"

    undated = query_legal_records(
        jurisdiction="US",
        place="Snohomish, WA",
        section="1.01.010",
        corpus_opener=opener,
    )
    assert [row["entry_cid"] for row in undated.records] == [SNOHOMISH]
    assert undated.records[0]["effective_date"] is None
    assert undated.records[0]["citation"] == _row(sample_rows, SNOHOMISH)["citation"]
    assert "§ 1.01.010" in str(undated.records[0]["citation"])
    dated_only = query_legal_records(
        jurisdiction="US",
        place="City of Snohomish",
        section="1.01.010",
        as_of="2020-01-01",
        corpus_opener=opener,
    )
    assert dated_only.records == ()
    historical = query_legal_records(
        jurisdiction="US",
        place="Snohomish, Washington",
        section="5.28.210",
        as_of="1893-05-23",
        corpus_opener=opener,
    )
    assert [row["entry_cid"] for row in historical.records] == [SNOHOMISH_DATED]
    assert historical.records[0]["effective_date"] == "1893-05-23"


def test_a_state_route_does_not_read_the_municipal_sample(monkeypatch, sample_rows) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    calls: list[str] = []

    def opener(repo: str) -> tuple[dict[str, object], ...]:
        calls.append(repo)
        return sample_rows

    result = query_legal_records(
        jurisdiction="US-CA",
        place="Ventura",
        latitude="34.26778",
        longitude="-119.254206",
        section="3101",
        corpus_opener=opener,
    )
    assert result.coverage == "not_published"
    assert result.records == ()
    assert calls == []
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "0")
    with pytest.raises(LegalQueryDisabled):
        query_legal_records(
            jurisdiction="US",
            place="Ventura",
            corpus_opener=opener,
        )
    assert calls == []
