"""Wikipedia municipalities missing from the scraped American corpus."""

from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.municipal.municipality_gaps import (
    ambiguous_path,
    gaps_path,
    load_municipality_gaps,
    ready_path,
)


def _named(rows: list[dict[str, object]], name: str, state: str) -> list[dict[str, object]]:
    return [
        row
        for row in rows
        if row.get("name") == name and row.get("state_code") == state
    ]


def test_gap_file_splits_missing_domain_from_missing_scraper() -> None:
    rows = load_municipality_gaps()
    reasons = {str(row["gap_reason"]) for row in rows}
    assert reasons == {"both", "no_scraper"}
    assert sum(row["gap_reason"] == "both" for row in rows) == 5112
    assert sum(row["gap_reason"] == "no_scraper" for row in rows) == 1612
    assert all(row["country_code"] == "US" for row in rows)
    assert all(row["status"] == "not_scraped" for row in rows)
    assert all(row["place_name"] == row["name"] for row in rows)
    assert all("wikipedia.org" not in " ".join(str(url) for url in row["source_urls"]) for row in rows)
    bakersfield = _named(rows, "Bakersfield", "CA")
    assert len(bakersfield) == 1
    assert bakersfield[0]["gap_reason"] == "no_scraper"
    assert bakersfield[0]["code_platform"] == "municipal.codes"
    assert "bakersfield.municipal.codes" in str(bakersfield[0]["source_urls"][0])
    ponce = [row for row in rows if row.get("name") == "Ponce" and not row.get("state_code")]
    assert ponce
    assert all(row["gap_reason"] == "both" and row["source_urls"] == [] for row in ponce)
    assert _named(rows, "Los Angeles", "CA") == []
    assert gaps_path().is_file()


def test_ready_and_ambiguous_files_stay_out_of_the_gap_list() -> None:
    ready = load_municipality_gaps(ready_path())
    ambiguous = load_municipality_gaps(ambiguous_path())
    assert len(ready) == 21
    assert {row["gap_reason"] for row in ready} == {"ready_unscraped"}
    indio = _named(ready, "Indio", "CA")
    assert len(indio) == 1
    assert indio[0]["publisher"] == "amlegal"
    assert len(ambiguous) == 3374
    assert {row["gap_reason"] for row in ambiguous} == {"ambiguous_name"}
    assert _named(ambiguous, "Los Angeles", "CA") == []
