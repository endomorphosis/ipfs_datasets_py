from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers.common_crawl_index_loader import CommonCrawlIndexLoader


def test_loader_prefers_env_local_index_root(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_COMMON_CRAWL_INDEX_ROOT", str(tmp_path / "cc"))
    loader = CommonCrawlIndexLoader(local_base_dir=None, use_hf_fallback=False)
    assert loader.local_base_dir == Path(tmp_path / "cc")


def test_load_federal_index_redirects_to_state_in_admin_rules_mode(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_ADMIN_RULES_DIRECT_AGENTIC_ALL_STATES", "1")

    loader = CommonCrawlIndexLoader.__new__(CommonCrawlIndexLoader)
    loader._loaded_indexes = {}

    observed: dict[str, object] = {}

    def _fake_load_state_index(self, state_code=None, force_refresh=False):
        observed["state_code"] = state_code
        observed["force_refresh"] = force_refresh
        return {"kind": "state"}

    monkeypatch.setattr(CommonCrawlIndexLoader, "load_state_index", _fake_load_state_index)

    result = CommonCrawlIndexLoader.load_federal_index(loader, force_refresh=True)

    assert result == {"kind": "state"}
    assert observed == {"state_code": None, "force_refresh": True}


def test_query_municipal_index_filters_local_parquet_by_place_and_state(tmp_path) -> None:
    index_dir = tmp_path / "municipal"
    index_dir.mkdir()
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "domain": "portlandoregon.gov",
                    "url": "https://www.portland.gov/code",
                    "collection": "CC-MAIN-2024-10",
                    "timestamp": "20240101000000",
                    "mime": "text/html",
                    "status": 200,
                    "warc_filename": "crawl-data/example.warc.gz",
                    "warc_offset": 10,
                    "warc_length": 20,
                    "gnis": "2411471",
                    "place_name": "City of Portland",
                    "state_code": "OR",
                },
                {
                    "domain": "portlandmaine.gov",
                    "url": "https://www.portlandmaine.gov/code",
                    "collection": "CC-MAIN-2024-10",
                    "timestamp": "20240101000000",
                    "mime": "text/html",
                    "status": 200,
                    "warc_filename": "crawl-data/example2.warc.gz",
                    "warc_offset": 30,
                    "warc_length": 40,
                    "gnis": "0",
                    "place_name": "City of Portland",
                    "state_code": "ME",
                },
            ]
        ),
        index_dir / "municipal.parquet",
    )

    loader = CommonCrawlIndexLoader(local_base_dir=tmp_path, use_hf_fallback=False)

    rows = loader.query_municipal_index(
        place_name="Portland",
        state_code="OR",
        url_terms=["code", "ordinance"],
        max_results=10,
    )

    assert len(rows) == 1
    assert rows[0]["domain"] == "portlandoregon.gov"
    assert rows[0]["gnis"] == "2411471"


def test_query_state_index_filters_local_parquet_by_state_domain_and_url(tmp_path) -> None:
    index_dir = tmp_path / "state"
    index_dir.mkdir()
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "domain": "www.legislature.ms.gov",
                    "url": "https://www.legislature.ms.gov/legislation/",
                    "collection": "CC-MAIN-2024-10",
                    "timestamp": "20240101000000",
                    "mime": "text/html",
                    "status": 200,
                    "warc_filename": "crawl-data/ms.warc.gz",
                    "warc_offset": 100,
                    "warc_length": 200,
                    "gnis": None,
                    "place_name": None,
                    "state_code": "MS",
                },
                {
                    "domain": "www.legislature.ms.gov",
                    "url": "https://www.legislature.ms.gov/media/summary.pdf",
                    "collection": "CC-MAIN-2024-10",
                    "timestamp": "20240102000000",
                    "mime": "application/pdf",
                    "status": 200,
                    "warc_filename": "crawl-data/ms2.warc.gz",
                    "warc_offset": 300,
                    "warc_length": 400,
                    "gnis": None,
                    "place_name": None,
                    "state_code": "MS",
                },
                {
                    "domain": "www.ncleg.gov",
                    "url": "https://www.ncleg.gov/Laws/GeneralStatutesTOC",
                    "collection": "CC-MAIN-2024-10",
                    "timestamp": "20240103000000",
                    "mime": "text/html",
                    "status": 200,
                    "warc_filename": "crawl-data/nc.warc.gz",
                    "warc_offset": 500,
                    "warc_length": 600,
                    "gnis": None,
                    "place_name": None,
                    "state_code": "NC",
                },
            ]
        ),
        index_dir / "state.parquet",
    )

    loader = CommonCrawlIndexLoader(local_base_dir=tmp_path, use_hf_fallback=False)

    rows = loader.query_state_index(
        state_code="MS",
        domain_terms=["legislature.ms.gov"],
        url_terms=["legislation"],
        mime_terms=["html"],
        max_results=10,
    )

    assert len(rows) == 1
    assert rows[0]["domain"] == "www.legislature.ms.gov"
    assert rows[0]["state_code"] == "MS"
    assert rows[0]["url"] == "https://www.legislature.ms.gov/legislation/"


def test_query_state_index_falls_back_when_local_state_code_is_null(tmp_path) -> None:
    index_dir = tmp_path / "state"
    index_dir.mkdir()
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "domain": "billstatus.ls.state.ms.us",
                    "url": "https://billstatus.ls.state.ms.us/2026/pdf/code_sections/097/00030007.xml",
                    "collection": "CC-MAIN-2024-10",
                    "timestamp": "20240101000000",
                    "mime": "text/html",
                    "status": 200,
                    "warc_filename": "crawl-data/ms.warc.gz",
                    "warc_offset": 100,
                    "warc_length": 200,
                    "gnis": None,
                    "place_name": None,
                    "state_code": None,
                },
                {
                    "domain": "www.ncleg.gov",
                    "url": "https://www.ncleg.gov/Laws/GeneralStatutesTOC",
                    "collection": "CC-MAIN-2024-10",
                    "timestamp": "20240103000000",
                    "mime": "text/html",
                    "status": 200,
                    "warc_filename": "crawl-data/nc.warc.gz",
                    "warc_offset": 500,
                    "warc_length": 600,
                    "gnis": None,
                    "place_name": None,
                    "state_code": None,
                },
            ]
        ),
        index_dir / "state.parquet",
    )

    loader = CommonCrawlIndexLoader(local_base_dir=tmp_path, use_hf_fallback=False)

    rows = loader.query_state_index(
        state_code="MS",
        domain_terms=["ls.state.ms.us"],
        url_terms=["code_sections"],
        mime_terms=["html"],
        max_results=10,
    )

    assert len(rows) == 1
    assert rows[0]["domain"] == "billstatus.ls.state.ms.us"
    assert rows[0]["state_code"] == "MS"
    assert "code_sections" in rows[0]["url"]


def test_materialize_state_query_sidecar_builds_filtered_local_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_COMMON_CRAWL_USE_STATE_QUERY_SIDECAR", "1")
    index_dir = tmp_path / "state"
    index_dir.mkdir()
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "domain": "billstatus.ls.state.ms.us",
                    "url": "https://billstatus.ls.state.ms.us/2026/pdf/code_sections/097/00030007.xml",
                    "collection": "CC-MAIN-2024-10",
                    "timestamp": "20240101000000",
                    "mime": "text/html",
                    "status": 200,
                    "warc_filename": "crawl-data/ms.warc.gz",
                    "warc_offset": 100,
                    "warc_length": 200,
                    "gnis": None,
                    "place_name": None,
                    "state_code": None,
                },
                {
                    "domain": "www.ncleg.gov",
                    "url": "https://www.ncleg.gov/Laws/GeneralStatutesTOC",
                    "collection": "CC-MAIN-2024-10",
                    "timestamp": "20240103000000",
                    "mime": "text/html",
                    "status": 200,
                    "warc_filename": "crawl-data/nc.warc.gz",
                    "warc_offset": 500,
                    "warc_length": 600,
                    "gnis": None,
                    "place_name": None,
                    "state_code": None,
                },
            ]
        ),
        index_dir / "state.parquet",
    )

    loader = CommonCrawlIndexLoader(local_base_dir=tmp_path, use_hf_fallback=False)
    sidecar = loader.materialize_state_query_sidecar(
        state_code="MS",
        domain_terms=["ls.state.ms.us"],
        url_terms=["code_sections"],
        mime_terms=["html"],
    )

    assert sidecar is not None
    assert sidecar.exists()

    cached_rows = pq.read_table(sidecar).to_pylist()
    assert len(cached_rows) == 1
    assert cached_rows[0]["domain"] == "billstatus.ls.state.ms.us"
    assert "code_sections" in cached_rows[0]["url"]


def test_query_state_index_uses_state_query_sidecar_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_COMMON_CRAWL_USE_STATE_QUERY_SIDECAR", "1")
    index_dir = tmp_path / "state"
    index_dir.mkdir()
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "domain": "billstatus.ls.state.ms.us",
                    "url": "https://billstatus.ls.state.ms.us/2026/pdf/code_sections/097/00030007.xml",
                    "collection": "CC-MAIN-2024-10",
                    "timestamp": "20240101000000",
                    "mime": "text/html",
                    "status": 200,
                    "warc_filename": "crawl-data/ms.warc.gz",
                    "warc_offset": 100,
                    "warc_length": 200,
                    "gnis": None,
                    "place_name": None,
                    "state_code": None,
                }
            ]
        ),
        index_dir / "state.parquet",
    )

    loader = CommonCrawlIndexLoader(local_base_dir=tmp_path, use_hf_fallback=False)
    rows = loader.query_state_index(
        state_code="MS",
        domain_terms=["ls.state.ms.us"],
        url_terms=["code_sections"],
        mime_terms=["html"],
        max_results=5,
    )

    assert len(rows) == 1
    assert rows[0]["state_code"] == "MS"
    assert rows[0]["domain"] == "billstatus.ls.state.ms.us"
    assert loader._state_query_sidecar_path(
        state_code="MS",
        domain_terms=["ls.state.ms.us"],
        url_terms=["code_sections"],
        mime_terms=["html"],
    ).exists()


def test_materialize_state_index_locally_downloads_parquet_and_queries_it(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_file = source_dir / "state_source.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "domain": "www.legislature.ms.gov",
                    "url": "https://www.legislature.ms.gov/legislation/",
                    "collection": "CC-MAIN-2024-10",
                    "timestamp": "20240101000000",
                    "mime": "text/html",
                    "status": 200,
                    "warc_filename": "crawl-data/ms.warc.gz",
                    "warc_offset": 100,
                    "warc_length": 200,
                    "gnis": None,
                    "place_name": None,
                    "state_code": "MS",
                }
            ]
        ),
        source_file,
    )

    loader = CommonCrawlIndexLoader(local_base_dir=tmp_path / "indexes", use_hf_fallback=True)
    monkeypatch.setattr(
        loader,
        "_get_hf_parquet_urls",
        lambda index_type: [source_file.resolve().as_uri()] if index_type == "state" else [],
    )

    downloaded = loader.materialize_state_index_locally()

    assert len(downloaded) == 1
    assert downloaded[0].exists()

    rows = loader.query_state_index(
        state_code="MS",
        domain_terms=["legislature.ms.gov"],
        url_terms=["legislation"],
        max_results=5,
    )

    assert len(rows) == 1
    assert rows[0]["state_code"] == "MS"
    assert rows[0]["domain"] == "www.legislature.ms.gov"
