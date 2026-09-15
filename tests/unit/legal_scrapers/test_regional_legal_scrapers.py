from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.africa import Africa
from ipfs_datasets_py.processors.legal_scrapers.americas import Americas
from ipfs_datasets_py.processors.legal_scrapers.asia_pacific import AsiaPacific
from ipfs_datasets_py.processors.legal_scrapers.europe import Europe
from ipfs_datasets_py.processors.legal_scrapers.international.api import (
    resolve_legal_source,
    scrape_legal_data,
    snapshot_catalog_summary,
)
from ipfs_datasets_py.processors.legal_scrapers.canonical_legal_corpora import (
    infer_canonical_legal_corpus_for_dataset_id,
)
from ipfs_datasets_py.processors.legal_scrapers.international.catalog import list_snapshot_corpora
from ipfs_datasets_py.processors.legal_scrapers.mena import MENA
from ipfs_datasets_py.processors.legal_scrapers.municipal import Municipal
from ipfs_datasets_py.processors.legal_scrapers.regions import get_region, list_regions
from ipfs_datasets_py.processors.legal_scrapers.regions.mapping import (
    COUNTRY_TO_REGION,
    REGION_IDS,
    region_for_country,
)
from ipfs_datasets_py.processors.legal_scrapers.state import State


def test_every_catalog_country_has_exactly_one_region():
    unassigned = []
    for entry in list_snapshot_corpora(include_aliases=False):
        try:
            region = region_for_country(entry.country_code)
        except KeyError:
            unassigned.append((entry.slug, entry.country_code))
            continue
        assert entry.region == region
        assert region in REGION_IDS
    assert unassigned == []


def test_region_classes_partition_harvested_corpora():
    regions = list_regions()
    assert [region.region_id for region in regions] == list(REGION_IDS)
    seen: set[str] = set()
    for region in regions:
        for entry in region.corpora(include_aliases=False):
            assert entry.country_code not in seen
            seen.add(entry.country_code)
    catalog_codes = {entry.country_code for entry in list_snapshot_corpora(include_aliases=False)}
    assert seen == catalog_codes
    summary = snapshot_catalog_summary()
    assert set(summary["by_region"]) == set(REGION_IDS)
    assert sum(summary["by_region"].values()) == summary["canonical_count"]


def test_americas_europe_mena_africa_asia_pacific_membership():
    assert Americas.contains("brazil")
    assert Americas.contains("canada")
    assert not Americas.contains("germany")
    assert Europe.get("germany").country_code == "DE"
    assert Europe.contains("eu")
    assert MENA.contains("egypt")
    assert MENA.contains("turkey")
    assert not MENA.contains("kenya")
    assert Africa.contains("kenya")
    assert Africa.contains("southafrica")
    assert not Africa.contains("egypt")
    assert AsiaPacific.contains("japan")
    assert AsiaPacific.contains("australia")
    assert AsiaPacific.contains("newzealand")
    assert get_region("asia-pacific") is get_region("asia_pacific")


def test_region_inspect_does_not_scrape_every_country():
    europe = scrape_legal_data("europe", mode="inspect")
    assert europe["status"] == "success"
    assert europe["source"]["kind"] == "region_family"
    assert europe["region"]["region_id"] == "europe"
    assert any(item["country_code"] == "DE" for item in europe["sources"])
    brazil = Americas.scrape("brazil", mode="inspect")
    assert brazil["source"]["dataset_id"] == "endomorphosis/ipfs_brazil_laws"


def test_state_and_municipal_classes_wrap_native_us_scrapers():
    state_summary = State.summary()
    assert state_summary["region_id"] == "state"
    assert state_summary["jurisdiction_count"] >= 50
    codes = {item["key"] for item in State.sources()}
    assert {"CA", "NY", "OR", "TX"} <= codes
    municipal_summary = Municipal.summary()
    assert municipal_summary["hub_jurisdiction_count"] >= 3000
    assert municipal_summary["city_count"] >= 7000
    assert municipal_summary["state_count"] >= 50
    cities = Municipal.cities()
    assert "NYC" in cities
    buncombe = Municipal.get("1008538")
    assert buncombe["state_code"] == "NC"
    portland = Municipal.search("Portland", limit=20)
    assert portland["count"] >= 1
    assert any("Portland" in item["place_name"] for item in portland["jurisdictions"])
    assert resolve_legal_source("state").handler == "state"
    assert resolve_legal_source("municipal").handler == "municipal"
    assert infer_canonical_legal_corpus_for_dataset_id("endomorphosis/american_municipal_law").key == "municipal_laws"
