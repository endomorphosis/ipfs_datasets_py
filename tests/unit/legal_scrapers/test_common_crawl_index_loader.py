from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers.common_crawl_index_loader import CommonCrawlIndexLoader


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
