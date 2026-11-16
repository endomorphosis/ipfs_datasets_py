"""Published legal datasets share one observational request schema."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.ducklake.legal_dataset_schema import (
    legal_dataset_schema,
    maintain_legal_dataset_schema,
    published_dataset_ids,
    request_legal_data,
)
from ipfs_datasets_py.ducklake.legal_search_catalog import (
    LegalSearchCatalogError,
    assert_catalog_has_no_bodies,
    open_legal_search_catalog,
    register_country_ir_catalog,
)


def test_published_inventory_keeps_every_dataset_observational() -> None:
    dataset_ids = published_dataset_ids()
    releases = legal_dataset_schema(dataset_ids)
    by_repo = {item.hf_repo: item for item in releases}

    assert len(by_repo) == len(dataset_ids) == 740
    assert set(by_repo) == set(dataset_ids)
    assert sum(item.startswith("justicedao/") for item in by_repo) == 376
    assert sum(item.startswith("endomorphosis/") for item in by_repo) == 364
    assert all(item.authoritative is False for item in releases)
    assert all(item.ducklake_authoritative is False for item in releases)
    assert all(item.research_only is True for item in releases)
    assert [item.hf_repo for item in releases if item.layout_profile == "unclassified"] == [
        "justicedao/anim",
        "justicedao/ipfs_american_municipal_law_normalized_graphrag",
        "justicedao/ipfs_state_laws_normalized_graphrag",
    ]

    france = by_repo["justicedao/ipfs_france_laws_ir"]
    raw = by_repo["endomorphosis/ipfs_france_laws"]
    assert france.selected is True
    assert france.searchable is True
    assert france.corpus_id == raw.corpus_id == "country:france"
    assert raw.selected is False
    assert "endomorphosis/ipfs_france_laws" in france.supersedes

    graphrag = by_repo["justicedao/caselaw-access-project-graphrag"]
    text = by_repo["justicedao/ipfs_caselaw_access_project"]
    assert graphrag.selected is True
    assert graphrag.corpus_id == "us:caselaw-graphrag"
    assert graphrag.primary_key == "law_id"
    assert text.selected is True
    assert text.corpus_id == "us:caselaw"
    assert by_repo["justicedao/world_national_law"].selected is False
    assert by_repo["endomorphosis/world_national_law"].selected is False
    assert by_repo["endomorphosis/american_municipal_law"].selected is False
    assert by_repo["justicedao/ipfs_legal_scrapers_and_normalizers"].layout_profile == "excluded"
    assert by_repo["endomorphosis/legal_scrapers"].searchable is False
    assert by_repo["endomorphosis/ipfs_malawi_caselaw"].selected is True
    assert by_repo["endomorphosis/ipfs_malawi_caselaw"].corpus_id == "country:malawi:caselaw"
    assert by_repo["justicedao/ipfs_australia_caselaw"].selected is True
    assert by_repo["justicedao/ipfs_us_cfr"].corpus_id == "us:cfr"
    assert by_repo["justicedao/ipfs_uk_local_acts_ir"].selected is True


def test_request_routes_one_jurisdiction_without_opening_bodies() -> None:
    france = request_legal_data(jurisdiction="france", instrument_kind="statute")
    repos = [item.hf_repo for item in france.datasets]
    assert repos[0] == "justicedao/ipfs_france_laws_ir"
    assert "endomorphosis/ipfs_france_laws" not in repos
    assert all(item.selected and item.searchable and item.text_corpus for item in france.datasets)
    assert all(item.authoritative is False for item in france.datasets)
    assert france.routes == ()
    france_ir = france.datasets[0]
    assert france_ir.primary_key_field == "entry_cid"
    assert "endomorphosis/ipfs_france_laws" in france_ir.siblings
    assert any(field.field_name == "entry_cid" and field.field_role == "key" for field in france_ir.fields)
    assert any(field.field_role == "document" for field in france_ir.fields)

    explicit = request_legal_data(hf_repo="endomorphosis/ipfs_france_laws")
    assert [item.hf_repo for item in explicit.datasets] == ["endomorphosis/ipfs_france_laws"]
    assert explicit.datasets[0].selected is False

    cases = request_legal_data(jurisdiction="US", instrument_kind="case")
    case_repos = [item.hf_repo for item in cases.datasets]
    assert case_repos[0] == "justicedao/caselaw-access-project-graphrag"
    assert "justicedao/ipfs_caselaw_access_project" in case_repos
    assert "justicedao/Caselaw_Access_Project_embeddings" not in case_repos
    with_vectors = request_legal_data(
        jurisdiction="US",
        instrument_kind="case",
        text_only=False,
    )
    assert "justicedao/Caselaw_Access_Project_embeddings" in {
        item.hf_repo for item in with_vectors.datasets
    }

    with pytest.raises(LegalSearchCatalogError):
        request_legal_data()


def test_instrument_and_nested_level_select_different_corpora() -> None:
    national = request_legal_data(
        jurisdiction="US",
        instrument_kind="statutes",
        admin_level="national",
    )
    national_repos = {item.hf_repo for item in national.datasets}
    assert "justicedao/ipfs_uscode" in national_repos
    assert "justicedao/ipfs_state_laws" not in national_repos
    assert all(item.instrument_kind == "statute" for item in national.datasets)

    state = request_legal_data(
        jurisdiction="Nebraska",
        instrument_kind="statute",
        admin_level="state",
    )
    state_repos = {item.hf_repo for item in state.datasets}
    assert "justicedao/ipfs_state_laws" in state_repos
    assert "justicedao/ipfs_uscode" not in state_repos
    assert state.place is not None
    assert state.place.state_code == "NE"
    assert state.layers[0].admin_level == "state"
    assert state.layers[0].jurisdiction_code == "US-NE"

    caselaw = request_legal_data(
        jurisdiction="US",
        instrument_kind="caselaw",
        admin_level="state",
    )
    assert "justicedao/caselaw-access-project-graphrag" in {
        item.hf_repo for item in caselaw.datasets
    }

    rules = request_legal_data(
        jurisdiction="US",
        instrument_kind="rules of procedure",
        admin_level="state",
    )
    assert "justicedao/ipfs_court_rules" in {item.hf_repo for item in rules.datasets}
    assert all(item.authoritative is False for item in rules.datasets)
    assert all(item.instrument_kind == "rule" for item in rules.datasets)

    courts = request_legal_data(jurisdiction="US", instrument_kind="courts")
    assert "justicedao/ipfs_us_courts" in {item.hf_repo for item in courts.datasets}

    regulations = request_legal_data(
        jurisdiction="US",
        instrument_kind="regulations",
        admin_level="federal",
    )
    assert "justicedao/ipfs_us_cfr" in {item.hf_repo for item in regulations.datasets}
    assert "justicedao/ipfs_state_admin_rules" not in {
        item.hf_repo for item in regulations.datasets
    }

    us_municipal = request_legal_data(
        jurisdiction="US",
        instrument_kind="ordinance",
        admin_level="municipal",
    )
    assert "justicedao/ipfs_us_municipal_laws" in {
        item.hf_repo for item in us_municipal.datasets
    }
    assert all(item.instrument_kind == "ordinance" for item in us_municipal.datasets)

    municipal = request_legal_data(
        jurisdiction="france",
        instrument_kind="ordinance",
        admin_level="municipal",
    )
    assert municipal.datasets
    assert all(item.instrument_kind == "ordinance" for item in municipal.datasets)
    assert all("municipal" in item.corpus_id for item in municipal.datasets)

    with pytest.raises(LegalSearchCatalogError):
        request_legal_data(jurisdiction="US", instrument_kind="not-a-kind")


def test_gps_point_returns_the_laws_that_apply_there() -> None:
    from ipfs_datasets_py.processors.legal_data.county_geography import (
        locate_governments,
    )

    latitude = "40.8083"
    longitude = "-96.6997"
    governments = locate_governments(latitude, longitude)
    if governments.status == "unindexed":
        pytest.skip("county index is not on this machine")
    assert governments.status == "one"
    assert governments.county is not None

    found = request_legal_data(
        latitude=latitude,
        longitude=longitude,
        topic="zoning",
    )
    assert found.place is not None
    assert found.place.status == "one"
    assert found.place.country_code == "US"
    assert found.place.state_code == governments.county.state_code
    assert found.place.county_name == governments.county.name
    assert found.topic == "zoning"
    by_level = {layer.admin_level: layer for layer in found.layers}
    assert "justicedao/ipfs_uscode" in {item.hf_repo for item in by_level["national"].datasets}
    assert "justicedao/ipfs_state_laws" in {item.hf_repo for item in by_level["state"].datasets}
    assert "justicedao/ipfs_uscode" not in {item.hf_repo for item in by_level["state"].datasets}
    assert "justicedao/caselaw-access-project-graphrag" in {
        item.hf_repo for item in by_level["state"].datasets
    }
    assert found.routes == ()

    with pytest.raises(LegalSearchCatalogError):
        request_legal_data(
            jurisdiction="france",
            latitude=latitude,
            longitude=longitude,
        )


def test_catalog_schema_registers_every_dataset_and_routes_terms(tmp_path) -> None:
    connection = open_legal_search_catalog(tmp_path / "legal_search.duckdb")
    try:
        counted = maintain_legal_dataset_schema(connection)
        assert counted["datasets"] == 740
        assert counted["fields"] > 0
        assert_catalog_has_no_bodies(connection)
        columns = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'legal_dataset'
                """
            ).fetchall()
        }
        assert "hf_repo" in columns
        assert "text" not in columns
        assert "body" not in columns
        assert "embedding" not in columns

        malta = next(
            item
            for item in legal_dataset_schema()
            if item.hf_repo == "justicedao/ipfs_malta_laws_ir"
        )
        register_country_ir_catalog(
            connection,
            (malta,),
            (
                {
                    "corpus_id": "country:malta",
                    "term_low": "act",
                    "term_high": "law",
                    "shard_ordinal": 0,
                    "content_sha256": "ab" * 32,
                    "row_count": 2,
                },
            ),
        )
        found = request_legal_data(
            connection=connection,
            jurisdiction="malta",
            terms=("law",),
        )
        assert any(item.hf_repo == "justicedao/ipfs_malta_laws_ir" for item in found.datasets)
        assert [(item.corpus_id, item.shard_ordinal, item.term) for item in found.routes] == [
            ("country:malta", 0, "law")
        ]
        assert all(item.research_only is True for item in found.routes)
        stored = connection.execute("SELECT COUNT(*) FROM legal_dataset").fetchone()
        assert stored is not None and int(stored[0]) == 740
        bodies = connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main'
              AND lower(column_name) IN ('text', 'body', 'embedding', 'vector', 'token', 'path')
            """
        ).fetchall()
        assert bodies == []
    finally:
        connection.close()
