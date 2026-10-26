"""The county scrape queue names governments that have no stored ordinances."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_scrapers.municipal.county_gap_queue import (
    load_county_gap_queue,
    queue_path,
)

_DBF = Path("/tmp/grok-barberb/county-geo/cb_2024_us_county_500k.dbf")
_SAMPLE = Path("/tmp/grok-barberb/municipal-search-sample/county-gaps.json")


def _by_name(rows: list[dict[str, object]]) -> dict[tuple[str, str], dict[str, object]]:
    return {(str(row["census_name"]), str(row["state_code"])): row for row in rows}


def test_queue_lists_counties_without_ordinances() -> None:
    rows = load_county_gap_queue()
    found = _by_name(rows)
    harris = found[("Harris County", "TX")]
    assert harris["qid"]
    assert harris["wikidata_url"] == f"https://www.wikidata.org/wiki/{harris['qid']}"
    assert harris["sample_points"] == 14
    assert harris["status"] == "not_scraped"
    assert harris["match"] == "gnis"
    assert isinstance(harris["source_urls"], list)
    assert "wikipedia.org" not in " ".join(str(url) for url in harris["source_urls"])
    district = found[("District of Columbia", "DC")]
    assert district["match"] == "name"
    assert district["qid"] == "Q3551781"
    assert any("dc.gov" in str(url) for url in district["source_urls"])
    assert ("Los Angeles County", "CA") not in found
    assert ("Dallas County", "TX") not in found
    assert all(row["status"] == "not_scraped" for row in rows)
    assert all("wikipedia_url" not in row for row in rows)
    assert queue_path().is_file()


def test_queue_matches_a_fresh_census_join() -> None:
    import pytest

    if not _DBF.is_file():
        pytest.skip("Census county table is not on this machine")
    from ipfs_datasets_py.processors.legal_data.municipal_section_search import (
        MunicipalSectionError,
        load_authority_index,
    )
    from ipfs_datasets_py.processors.legal_scrapers.municipal.county_gap_queue import (
        build_county_gap_rows,
    )

    try:
        load_authority_index()
    except MunicipalSectionError:
        pytest.skip("local american v4 authority index is not on this machine")
    sample = _SAMPLE if _SAMPLE.is_file() else None
    fresh = build_county_gap_rows(_DBF, sample_path=sample)
    stored = load_county_gap_queue()
    assert [(row["census_geoid"], row["qid"], row["sample_points"]) for row in fresh] == [
        (row["census_geoid"], row["qid"], row["sample_points"]) for row in stored
    ]
    if sample is not None:
        payload = json.loads(_SAMPLE.read_text(encoding="utf-8"))
        names = {
            (item["name"], item["state"])
            for item in payload["missing_counties"]
        }
        queued = {(row["census_name"], row["state_code"]) for row in stored}
        assert names <= queued
