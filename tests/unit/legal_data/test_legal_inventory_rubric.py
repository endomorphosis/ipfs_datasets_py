"""Offline Hub inventory and republication rubric. No network."""

from __future__ import annotations

import inspect
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.iso_slug_crosswalk import (
    _PUBLISHED_MUNICIPAL_SLUGS,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.inventory import (
    _fetch_public,
    classify_inventory,
    list_public_datasets,
    load_inventory,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.project_world_v11_row import (
    drop_reason,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.review_row import (
    AMERICAN_COLUMNS,
    HTML_MUNICIPAL_COLUMNS,
    review_row,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import (
    _DROP_POLICIES,
    WORLD_V11_COLUMNS,
)

_MISSING_MUNICIPAL = {
    "austria_municipal",
    "belgium_municipal",
    "brazil_municipal",
    "canada_municipal",
    "indonesia_municipal",
    "korea_municipal",
    "latvia_municipal",
    "netherlands_municipal",
    "new_zealand_municipal",
    "portugal_municipal",
    "slovenia_municipal",
}

_IR_CREATES = {
    "austria_municipal",
    "korea_municipal",
    "latvia_municipal",
    "netherlands_municipal",
    "slovenia_municipal",
    "brazil_municipal",
}

_HTML_NORM = {
    "belgium_municipal",
    "canada_municipal",
    "indonesia_municipal",
    "portugal_municipal",
    "new_zealand_municipal",
}


def _world_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {name: None for name in WORLD_V11_COLUMNS}
    row.update(
        {
            "cid": "cid-1",
            "doc_id": "doc-1",
            "doc_order": 1,
            "country_code": "FR",
            "doc_type": "statute",
            "title_native": "Code",
            "text": "Les lois",
            "language": "fr",
            "license_note": "research-only",
            "published_date": "2020-01-02",
            "source_official": True,
            "content_complete": True,
        }
    )
    row.update(overrides)
    return row


def _html_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {name: None for name in HTML_MUNICIPAL_COLUMNS}
    row.update({"cid": "cid-h", "country": "Canada", "doc_id": "d", "doc_order": 1, "text": "Bylaw"})
    row.update(overrides)
    return row


def test_fixture_counts_and_municipal_commands() -> None:
    classified = classify_inventory()
    orgs = classified["orgs"]
    assert orgs["endomorphosis"] == {"datasets": 265, "models": 20, "spaces": 0}
    assert orgs["justicedao"] == {"datasets": 273, "models": 0, "spaces": 0}
    partition = classified["family_partition"]
    assert partition["national_pattern"] == 222
    assert partition["with_ir"] == 219
    assert partition["calendar_stale"] + partition["same_utc_day"] + partition["ir_newer"] == 219
    municipal = classified["municipal"]
    assert len(municipal) == 30
    assert {row["slug"] for row in municipal} == set(_PUBLISHED_MUNICIPAL_SLUGS)
    by_slug = {row["slug"]: row for row in municipal}
    assert by_slug["czech_municipal"]["command"] == "reindex"
    assert by_slug["estonia_municipal"]["command"] == "reindex"
    assert by_slug["spain_municipal"]["command"] == "load_sharded_laws"
    assert by_slug["spain_municipal"]["sidecar_not_projected"] is True
    assert by_slug["brazil_municipal"]["command"] == "load_sharded_laws"
    assert by_slug["canada_municipal"]["command"] == "export_norm_html"
    assert set(classified["missing_municipal_irs"]) == _MISSING_MUNICIPAL
    assert set(classified["ir_creates"]) == _IR_CREATES
    assert set(classified["html_norm_exports"]) == _HTML_NORM
    for row in municipal:
        if row["slug"] in _HTML_NORM:
            assert row["default_query_repo"] == f"justicedao/ipfs_{row['slug']}_laws_ir"
            assert row["ir_action"] == "export_norm_html"
        assert row["sha_gap"] == "unproven"
    canada = by_slug["canada_municipal"]["html_counts"]
    assert canada[0] == {
        "sha": "7ef1bd20e2eca296c2d106e50ff665bdc2d92c5e",
        "html_parquet": 27,
    }
    assert canada[1]["sha"] == "04f02e4cf3ed25558280408ef1bf96761df3cbdd"
    assert canada[1]["html_parquet"] == 28


def test_stale_aliases_unpublished_and_non_corpora() -> None:
    classified = classify_inventory()
    stale = classified["calendar_stale"]
    assert len(stale) == 21
    assert {row["sha_gap"] for row in stale} == {"unproven"}
    assert {row["slug"] for row in stale} >= {"uk", "el_salvador", "papua_new_guinea", "ghana"}
    pairs = {tuple(pair) for pair in classified["alias_pairs"]}
    assert ("el_salvador", "elsalvador") in pairs
    assert ("papua_new_guinea", "papuanewguinea") in pairs
    assert len(pairs) == 6
    unpublished = {row["id"]: row for row in classified["subnational_exact"]}
    assert set(unpublished) == {
        "ipfs_egypt_governorate_laws",
        "ipfs_south_africa_provincial_laws",
        "ipfs_wallis_futuna_laws",
    }
    for row in unpublished.values():
        assert row["route"] == "none"
        assert row["coverage"] == "not_published"
    local_acts = classified["uk_local_acts"]
    assert local_acts["gb_route"] is False
    assert local_acts["gb_repo"] == "justicedao/ipfs_uk_laws_ir"
    assert local_acts["ir"] == "justicedao/ipfs_uk_local_acts_ir"
    crawl_ids = {row["id"] for row in classified["common_crawl"]}
    assert crawl_ids == {
        "common_crawl_pointers_by_collection",
        "common_crawl_meta_indexes",
        "common_crawl_municipal_index",
        "common_crawl_state_index",
        "common_crawl_federal_index",
    }
    assert "legal_scrapers" in classified["non_corpus"]
    assert "211-info" in classified["non_corpus"]
    assert classified["models"][0]["id"] == "world_law_pipeline"
    assert classified["models"][0]["corpus"] is False
    statuses = {row["repo"]: row["export_status"] for row in classified["norm_destinations"]}
    assert statuses["justicedao/world_national_law"] == "missing"
    assert statuses["justicedao/world_municipal_law"] == "missing"
    assert statuses["justicedao/american_municipal_law_norm"] == "missing"
    assert classified["blocked_repos"] == [
        "justicedao/ipfs_state_laws",
        "justicedao/ipfs_federal_register",
    ]
    assert classified["legacy_american"]["export_status"] == "present_stale_calendar"
    world = classified["world"]
    assert world["law_shards"] == ["iso_AE_html.parquet"]
    assert world["ignored"] == ["places.parquet", "articles-00001.parquet"]
    assert world["world_national_law"]["admin_level"] == "country"
    assert world["world_municipal_law"]["admin_level"] == "municipality"
    assert world["world_municipal_law"]["card_configs_without_files"] == ["CL", "HU"]


def test_world_writer_reason_matches_drop_reason_and_findings_stay_separate() -> None:
    kept = _world_row()
    decision = review_row(kept, family="world-national")
    assert decision.writer_drop_reason == drop_reason(kept, drop_us=True) is None
    assert decision.safe_to_copy is True
    assert decision.admin_level == "country"
    assert decision.findings == ()
    municipal = review_row(kept, family="world-municipal")
    assert municipal.admin_level == "municipality"
    assert municipal.writer_drop_reason is None
    for policy in sorted(_DROP_POLICIES):
        row = _world_row(source_policy=policy)
        reviewed = review_row(row, family="world-national")
        assert reviewed.writer_drop_reason == drop_reason(row, drop_us=True) == policy
        assert reviewed.safe_to_copy is False
    unofficial = _world_row(source_official=False)
    assert review_row(unofficial, family="world-national").writer_drop_reason == "source_official_false"
    omitted = _world_row(country_code="US")
    us = review_row(omitted, family="world-national")
    assert us.writer_drop_reason == "us_omitted"
    assert "unresolved_country_code" not in us.findings
    partial = {"country_code": "FR", "text": "Les lois", "source_official": True}
    schema = review_row(partial, family="world-national")
    assert schema.writer_drop_reason is None
    assert schema.safe_to_copy is True
    assert "schema_invalid" in schema.findings
    unresolved = _world_row(country_code="ZZ")
    assert "unresolved_country_code" in review_row(unresolved, family="world-national").findings
    seen: set[tuple[str, ...]] = set()
    first = review_row(kept, family="world-national", seen=seen)
    second = review_row(dict(kept), family="world-national", seen=seen)
    assert "duplicate_identity" not in first.findings
    assert "duplicate_identity" in second.findings
    assert second.safe_to_copy is True
    assert second.writer_drop_reason is None


def test_html_and_american_reviews_do_not_invent_writer_drops() -> None:
    kept = review_row(_html_row(date_effective="2022-01-03"), family="html-municipal-19")
    assert kept.safe_to_copy is True
    assert kept.writer_drop_reason is None
    assert kept.admin_level == "municipality"
    assert "license_note_missing" in kept.findings
    assert "temporal_missing" not in kept.findings
    null_text = review_row(_html_row(text=None, html=None), family="html-municipal-19")
    assert null_text.safe_to_copy is True
    assert null_text.writer_drop_reason is None
    unknown = review_row(_html_row(country="Narnia"), family="html-municipal-19")
    assert unknown.writer_drop_reason == "unknown_country"
    assert unknown.safe_to_copy is False
    american = {name: None for name in AMERICAN_COLUMNS}
    american.update({"cid": "c", "doc_id": "d", "doc_order": 1, "html_title": "City", "html": "<p>x</p>"})
    reviewed = review_row(american, family="american-5")
    assert reviewed.safe_to_copy is True
    assert reviewed.writer_drop_reason is None
    assert reviewed.admin_level == "us-municipal"
    assert "temporal_missing" in reviewed.findings
    broken = dict(american)
    del broken["html"]
    assert review_row(broken, family="american-5").safe_to_copy is False


def test_live_lister_is_unauthenticated_and_unused_by_default(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "secret-token-value")
    monkeypatch.setenv("HF_TOKEN_FILE", "/tmp/not-a-token")
    calls: list[str] = []

    def opener(url: str) -> tuple[list[dict[str, str]], None]:
        calls.append(url)
        assert "Authorization" not in url
        return ([{"id": "endomorphosis/world_national_law"}], None)

    rows = list_public_datasets("endomorphosis", opener=opener)
    assert rows == [{"id": "endomorphosis/world_national_law"}]
    assert calls[0].startswith("https://huggingface.co/api/datasets?author=endomorphosis")
    lister = inspect.getsource(list_public_datasets)
    fetcher = inspect.getsource(_fetch_public)
    assert "os.environ" not in lister
    assert "os.environ" not in fetcher
    assert "add_header(\"Authorization\"" not in fetcher
    module = Path(inspect.getsourcefile(list_public_datasets) or "").read_text(encoding="utf-8")
    assert "huggingface_hub" not in module
    assert load_inventory()["captured_on"] == "2026-10-14"
