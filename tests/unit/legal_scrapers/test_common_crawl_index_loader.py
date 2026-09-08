from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers.common_crawl_index_loader import (
    CommonCrawlIndexLoader,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_fetch import (
    ArchivalFetchClient,
)
from ipfs_datasets_py.processors.web_archiving.common_crawl_search_engine.ccindex import (
    hf_datasets_adapter,
)


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


def test_query_state_index_orders_exact_urls_ahead_of_newer_prefix_hits(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_COMMON_CRAWL_USE_STATE_QUERY_SIDECAR", "1")
    index_dir = tmp_path / "state"
    index_dir.mkdir()
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "domain": "wisconsin.gov",
                    "url": "https://docs.legis.wisconsin.gov/statutes/statutes/968/17",
                    "collection": "CC-MAIN-2025-51",
                    "timestamp": "20251217132224",
                    "mime": "text/html",
                    "status": 200,
                    "warc_filename": "crawl-data/CC-MAIN-2025-51/segments/1/warc/nested.warc.gz",
                    "warc_offset": 1,
                    "warc_length": 10,
                    "gnis": None,
                    "place_name": None,
                    "state_code": None,
                },
                {
                    "domain": "wisconsin.gov",
                    "url": "https://docs.legis.wisconsin.gov/statutes/statutes",
                    "collection": "CC-MAIN-2025-47",
                    "timestamp": "20251117043644",
                    "mime": "text/html",
                    "status": 200,
                    "warc_filename": "crawl-data/CC-MAIN-2025-47/segments/1/warc/index.warc.gz",
                    "warc_offset": 2,
                    "warc_length": 20,
                    "gnis": None,
                    "place_name": None,
                    "state_code": None,
                },
            ]
        ),
        index_dir / "state.parquet",
    )

    loader = CommonCrawlIndexLoader(local_base_dir=tmp_path, use_hf_fallback=False)
    prefix_only = loader.query_state_index(
        state_code="WI",
        domain_terms=["wisconsin.gov"],
        url_terms=["/statutes/statutes"],
        mime_terms=["html"],
        max_results=1,
    )
    exact_first = loader.query_state_index(
        state_code="WI",
        domain_terms=["wisconsin.gov"],
        url_terms=["/statutes/statutes"],
        mime_terms=["html"],
        max_results=1,
        exact_urls=["https://docs.legis.wisconsin.gov/statutes/statutes"],
    )

    assert prefix_only[0]["url"].endswith("/statutes/statutes/968/17")
    assert exact_first[0]["url"] == "https://docs.legis.wisconsin.gov/statutes/statutes"
    assert exact_first[0]["warc_filename"] == (
        "crawl-data/CC-MAIN-2025-47/segments/1/warc/index.warc.gz"
    )
    assert type(exact_first[0]["warc_offset"]) is int
    assert type(exact_first[0]["warc_length"]) is int
    assert exact_first[0]["warc_offset"] == 2
    assert exact_first[0]["warc_length"] == 20
    assert ArchivalFetchClient._common_crawl_pointer(exact_first[0]) == (
        "crawl-data/CC-MAIN-2025-47/segments/1/warc/index.warc.gz",
        2,
        20,
    )
    sidecar = loader._state_query_sidecar_path(
        state_code="WI",
        domain_terms=["wisconsin.gov"],
        url_terms=["/statutes/statutes"],
        mime_terms=["html"],
    )
    assert sidecar.exists()
    assert list((tmp_path / "state_query_sidecars").glob("*.parquet")) == [sidecar]


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


def test_materialize_state_index_locally_downloads_parquet_and_queries_it(
    tmp_path, monkeypatch
) -> None:
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


_TOKEN_ENV_NAMES = (
    "IPFS_DATASETS_PY_HF_API_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "HUGGINGFACE_API_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_API_KEY",
    "HF_TOKEN",
    "HF_API_TOKEN",
)
_UNIT_TOKEN = "hf_unit_test_token_should_not_leak"


def _clear_hf_token_env(monkeypatch) -> None:
    for name in _TOKEN_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _stub_hub_token(monkeypatch, token: str | None) -> None:
    import importlib
    import types

    real_import = importlib.import_module

    def _import(name: str, package: str | None = None):
        if name == "huggingface_hub":
            return types.SimpleNamespace(get_token=lambda: token)
        return real_import(name, package)

    monkeypatch.setattr(hf_datasets_adapter.importlib, "import_module", _import)


class _FakeParquetResponse:
    def read(self) -> bytes:
        return json.dumps(
            {
                "parquet_files": [
                    {
                        "url": "https://huggingface.co/datasets/endomorphosis/common_crawl_state_index/resolve/main/data.parquet"
                    }
                ]
            }
        ).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_get_hf_parquet_urls_sends_authorization_when_token_available(monkeypatch) -> None:
    _clear_hf_token_env(monkeypatch)
    monkeypatch.setenv("HF_TOKEN", _UNIT_TOKEN)
    _stub_hub_token(monkeypatch, None)
    captured: dict[str, object] = {}

    def _fake_urlopen(request, timeout=None):
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeParquetResponse()

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.common_crawl_index_loader.urlopen",
        _fake_urlopen,
    )
    loader = CommonCrawlIndexLoader(use_hf_fallback=True)
    urls = loader._get_hf_parquet_urls("state")
    assert urls == [
        "https://huggingface.co/datasets/endomorphosis/common_crawl_state_index/resolve/main/data.parquet"
    ]
    request = captured["request"]
    assert isinstance(request, Request)
    assert request.get_header("Authorization") == f"Bearer {_UNIT_TOKEN}"


def test_get_hf_parquet_urls_stays_anonymous_without_token(monkeypatch) -> None:
    _clear_hf_token_env(monkeypatch)
    _stub_hub_token(monkeypatch, None)
    captured: dict[str, object] = {}

    def _fake_urlopen(request, timeout=None):
        captured["request"] = request
        return _FakeParquetResponse()

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.common_crawl_index_loader.urlopen",
        _fake_urlopen,
    )
    loader = CommonCrawlIndexLoader(use_hf_fallback=True)
    assert loader._get_hf_parquet_urls("state")
    request = captured["request"]
    assert isinstance(request, Request)
    assert not request.has_header("Authorization")


def test_connect_duckdb_attaches_huggingface_secret_when_token_available(monkeypatch) -> None:
    _clear_hf_token_env(monkeypatch)
    monkeypatch.setenv("HF_TOKEN", _UNIT_TOKEN)
    _stub_hub_token(monkeypatch, None)
    connection = CommonCrawlIndexLoader._connect_duckdb()
    rows = connection.execute("SELECT name, type FROM duckdb_secrets()").fetchall()
    assert any(kind == "huggingface" for _name, kind in rows)
    dumped = str(connection.execute("SELECT * FROM duckdb_secrets()").fetchall())
    assert _UNIT_TOKEN not in dumped
