"""Seed-row shaping for the municipal Wikidata harvest."""

from ipfs_datasets_py.processors.legal_scrapers.municipal.seed_harvest import (
    build_us_row,
    classify_urls,
    us_admin_level,
)


def test_code_host_wins_over_city_homepage() -> None:
    url_class, publisher = classify_urls(
        [
            "https://lacity.gov",
            "https://codelibrary.amlegal.com/codes/los_angeles/latest/overview",
        ]
    )
    assert url_class == "code_host"
    assert publisher == "amlegal"


def test_homepage_without_code_host_stays_official_site() -> None:
    assert classify_urls(["https://nyc.gov"]) == ("official_site", "")
    assert classify_urls([]) == ("none", "")


def test_county_without_city_word_is_adm2() -> None:
    assert us_admin_level("Buncombe County") == "adm2"
    assert us_admin_level("City and County of San Francisco") == "municipality"
    assert us_admin_level("City of Baker") == "municipality"


def test_us_row_keeps_seed_status_and_records_second_gnis() -> None:
    seed = {
        "gnis": 2395220,
        "place_name": "City of New York",
        "state_code": "NY",
        "source_urls": ["https://nyc.gov"],
        "status": "incomplete_scrape",
    }
    hits = [{"qid": "Q60", "gnis": "2395220", "label": "New York City", "country_code": "US"}]
    extras = {
        "Q60": {
            "gnises": ["2395220", "975772"],
            "sites": ["https://nyc.gov", "https://www.nyc.gov/"],
            "geonames_ids": ["5128581"],
            "langs": ["en"],
            "parent_qid": "Q1384",
            "iso_3166_2": "",
            "lat": "40.7128",
            "lon": "-74.006",
            "population": "8804190",
            "official_name": "City of New York",
        }
    }
    row = build_us_row(seed, hits, extras)
    assert row["match"] == "matched"
    assert row["qid"] == "Q60"
    assert row["status"] == "incomplete_scrape"
    assert row["gnis_alt"] == ["975772"]
    assert row["source_urls"][0] == "https://nyc.gov"
    assert "https://www.nyc.gov/" in row["source_urls"]
    assert row["region"] == "americas"
    assert row["admin_level"] == "municipality"
    assert row["url_class"] == "official_site"


def test_two_wikidata_items_for_one_gnis_stay_ambiguous() -> None:
    seed = {"gnis": "1", "place_name": "Town of Example", "state_code": "TX", "status": "not_scraped"}
    hits = [
        {"qid": "Q1", "gnis": "1", "label": "A", "country_code": "US"},
        {"qid": "Q2", "gnis": "1", "label": "B", "country_code": "US"},
    ]
    row = build_us_row(seed, hits, {})
    assert row["match"] == "ambiguous"
    assert row["qid"] == ""
    assert row["qids"] == ["Q1", "Q2"]
    assert row["status"] == "not_scraped"
