"""Vector-plus-graph keyword search and the scraper gap sample."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.ducklake.legal_search_catalog import LegalSearchCatalogError
from ipfs_datasets_py.ducklake.legal_text_search import (
    GraphEdge,
    VectorProbe,
    corpus_work_todo,
    coverage_matrix,
    hash_embed,
    justicedao_index_repo,
    sample_corpus_gaps,
    search_legal_text,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.catalog import (
    target_repo,
)
from ipfs_datasets_py.processors.legal_data.justicedao_release_registry import (
    build_release_registry,
)


def test_keyword_search_uses_vector_then_graph_without_document_text() -> None:
    releases = build_release_registry(["justicedao/ipfs_uscode"])
    zoning = hash_embed("zoning ordinance")
    other = hash_embed("admiralty prize")
    found = search_legal_text(
        "zoning ordinance",
        jurisdiction="US",
        instrument_kind="statutes",
        admin_level="national",
        releases=releases,
        vector_rows=(
            VectorProbe("us:code", "cid-zoning", zoning),
            VectorProbe("us:code", "cid-other", other),
        ),
        graph_edges=(GraphEdge("us:code", "cid-zoning", "cid-neighbor", "CITES"),),
        limit=5,
    )
    assert [hit.entry_cid for hit in found.hits[:2]] == ["cid-zoning", "cid-neighbor"]
    assert found.hits[0].channel == "vector"
    assert found.hits[0].score > found.hits[1].score
    neighbor = found.hits[1]
    assert neighbor.channel == "graph"
    assert neighbor.relation == "CITES"
    assert neighbor.admin_level == "national"
    assert neighbor.instrument_kind == "statute"
    assert all(hit.authoritative is False and hit.research_only is True for hit in found.hits)
    assert all(not hasattr(hit, "text") and not hasattr(hit, "body") for hit in found.hits)
    assert found.gaps == ()

    with pytest.raises(LegalSearchCatalogError):
        search_legal_text("   ")


def test_aliased_jurisdiction_keyword_search_uses_its_vector_index() -> None:
    releases = build_release_registry(["justicedao/ipfs_dominican_republic_laws_ir"])
    zoning = hash_embed("zoning ordinance")
    found = search_legal_text(
        "zoning ordinance",
        jurisdiction="dominican_republic",
        instrument_kind="statute",
        admin_level="national",
        releases=releases,
        vector_rows=(VectorProbe("country:dominican_republic", "cid-zoning", zoning),),
        graph_edges=(
            GraphEdge(
                "country:dominican_republic",
                "cid-zoning",
                "cid-neighbor",
                "CITES",
            ),
        ),
        limit=3,
    )
    assert [hit.entry_cid for hit in found.hits] == ["cid-zoning", "cid-neighbor"]
    assert found.hits[0].channel == "vector"
    assert found.hits[1].channel == "graph"
    assert found.hits[0].hf_repo == "justicedao/ipfs_dominican_republic_laws_ir"
    assert found.gaps == ()


def test_missing_cell_is_a_gap_for_every_requested_axis() -> None:
    found = search_legal_text(
        "zoning",
        jurisdiction="france",
        instrument_kind="patent",
        admin_level="municipal",
    )
    assert found.hits == ()
    assert found.gaps[0].reason == "missing_corpus"
    assert found.gaps[0].jurisdiction == "france"
    assert found.gaps[0].admin_level == "municipal"
    assert found.gaps[0].instrument_kind == "patent"
    assert found.authoritative is False


def test_gap_sample_spans_instrument_level_and_jurisdiction() -> None:
    matrix = coverage_matrix()
    assert any(
        cell.jurisdiction == "US"
        and cell.admin_level == "national"
        and cell.instrument_kind == "statute"
        and cell.reason == "searchable_layout"
        for cell in matrix
    )
    assert any(cell.reason == "missing_corpus" for cell in matrix)
    assert {cell.admin_level for cell in matrix} == {"national", "state", "county", "municipal"}
    assert "case" in {cell.instrument_kind for cell in matrix}
    keys = {cell.jurisdiction for cell in matrix}
    assert "france" in keys
    assert "US" in keys and "us" not in keys
    assert "new_zealand" not in keys and "dominican_republic" not in keys
    dominican = next(
        cell
        for cell in matrix
        if cell.jurisdiction == "dominicanrepublic"
        and cell.admin_level == "national"
        and cell.instrument_kind == "statute"
    )
    assert dominican.reason == "searchable_layout"
    assert dominican.hf_repo == "justicedao/ipfs_dominican_republic_laws_ir"

    sample = sample_corpus_gaps(limit=36, seed=7)
    again = sample_corpus_gaps(limit=36, seed=7)
    assert again.gaps == sample.gaps
    assert len(sample.gaps) == 36
    assert sample.gap_population < sample.population
    assert len({cell.instrument_kind for cell in sample.gaps}) > 1
    assert len({cell.admin_level for cell in sample.gaps}) > 1
    assert len({cell.jurisdiction for cell in sample.gaps}) > 1
    assert all(cell.reason != "searchable_layout" for cell in sample.gaps)
    assert dict(sample.by_reason)["missing_corpus"] > 0


def test_justicedao_index_repo_keeps_the_org_and_skips_a_second_suffix() -> None:
    assert justicedao_index_repo("endomorphosis/ipfs_americansamoa_laws") == (
        "justicedao/ipfs_americansamoa_laws_ir"
    )
    assert justicedao_index_repo("justicedao/ipfs_us_cfr") == "justicedao/ipfs_us_cfr_ir"
    assert justicedao_index_repo("justicedao/ipfs_germany_laws_ir") == "justicedao/ipfs_germany_laws_ir"
    assert justicedao_index_repo("justicedao/ipfs_argentina_laws-ir") == "justicedao/ipfs_argentina_laws-ir"
    assert justicedao_index_repo("justicedao/ipfs_state_laws") == "justicedao/ipfs_state_laws_ir"
    assert justicedao_index_repo("justicedao/ipfs_federal_register") == "justicedao/ipfs_federal_register_ir"
    with pytest.raises(LegalSearchCatalogError):
        justicedao_index_repo("")
    with pytest.raises(LegalSearchCatalogError):
        justicedao_index_repo("justicedao/")


def test_work_todo_queues_real_indexes_and_skips_county_patents() -> None:
    todo = corpus_work_todo()
    queued = {(item.action, item.admin_level, item.instrument_kind, item.hf_repo, item.jurisdiction) for item in todo.queue}
    assert not any(level == "county" and kind == "patent" for _action, level, kind, _repo, _place in queued)
    assert ("index", "national", "regulation", "justicedao/ipfs_us_cfr", "US") in queued
    assert ("index", "municipal", "ordinance", "justicedao/ipfs_us_municipal_laws", "US") in queued
    assert ("index", "municipal", "ordinance", "justicedao/american_municipal_law_norm", "US") in queued
    assert not any(item.jurisdiction == "france" and item.action == "scrape_ordinances" for item in todo.queue)
    ordinance_jobs = [item for item in todo.queue if item.action == "scrape_ordinances"]
    assert ordinance_jobs
    assert all(item.admin_level == "municipal" for item in ordinance_jobs)
    assert all(not item.jurisdiction.endswith(("_state", "_county", "_provincial")) for item in ordinance_jobs)
    held = {item.hf_repo for item in todo.double_check}
    assert "justicedao/ipfs_court_rules" in held
    assert "justicedao/ipfs_state_admin_rules" in held
    assert "endomorphosis/world_municipal_law" in held
    assert "endomorphosis/ipfs_antarctica_laws" in held
    assert "endomorphosis/ipfs_tokelau_laws" in held
    assert "endomorphosis/ipfs_westernsahara_laws" in held
    assert "endomorphosis/ipfs_americansamoa_laws" in held
    assert "endomorphosis/ipfs_macao_laws" in held
    assert ("patent", "county") in {(kind, level) for kind, level, _count in todo.not_expected}
    assert ("patent", "municipal") in {(kind, level) for kind, level, _count in todo.not_expected}
    indexes = [item for item in todo.queue if item.action == "index"]
    assert len(indexes) == 64
    protected = {"justicedao/ipfs_state_laws", "justicedao/ipfs_federal_register"}
    assert all(item.publish_repo and item.publish_repo.startswith("justicedao/") for item in indexes)
    assert all(item.publish_repo not in protected for item in indexes)
    assert all(not str(item.publish_repo).startswith("endomorphosis/") for item in indexes)
    assert all(item.publish_repo != item.hf_repo for item in indexes)
    assert all(item.publish_repo is None for item in todo.queue if item.action != "index")
    island = next(item for item in indexes if item.hf_repo == "endomorphosis/ipfs_christmasisland_laws")
    assert island.publish_repo == "justicedao/ipfs_christmasisland_laws_ir"
    assert island.publish_repo == target_repo("christmasisland")
    for item in indexes:
        leaf = (item.hf_repo or "").rsplit("/", 1)[-1]
        if item.instrument_kind == "statute" and item.admin_level == "national" and leaf.endswith("_laws"):
            slug = leaf.removeprefix("ipfs_").removesuffix("_laws")
            assert item.publish_repo == target_repo(slug)
