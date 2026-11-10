"""Regional government Common Crawl shard indexes.

These tests use a tiny temporary DuckDB. They must not open the built
regional files or download them from Hugging Face.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers.common_crawl_index_loader import (
    CommonCrawlIndexLoader,
)
from ipfs_datasets_py.processors.legal_scrapers.regions.base import LegalRegion
from ipfs_datasets_py.processors.legal_scrapers.regions import shard_index
from ipfs_datasets_py.processors.web_archiving.common_crawl_integration import (
    CommonCrawlSearchEngine,
    _government_shard_matches,
)

_NATIONAL_FALLBACKS = (
    Path(__file__).resolve().parents[3]
    / "ipfs_datasets_py"
    / "processors"
    / "legal_scrapers"
    / "national_collectors"
    / "archive_fallbacks.py"
)
_INTERNATIONAL_FALLBACKS = (
    Path(__file__).resolve().parents[3]
    / "ipfs_datasets_py"
    / "processors"
    / "legal_scrapers"
    / "international"
    / "helpers"
    / "archive_fallbacks.py"
)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_shard_db(path: Path, rows: list[dict]) -> None:
    import duckdb

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE query_domains (
                domain VARCHAR PRIMARY KEY,
                host_rev VARCHAR,
                sources VARCHAR
            );
            CREATE TABLE cc_domain_shards (
                query_domain VARCHAR,
                host_rev VARCHAR,
                collection VARCHAR,
                year INTEGER,
                shard_file VARCHAR,
                source_path VARCHAR,
                parquet_relpath VARCHAR,
                row_group INTEGER,
                rg_row_start BIGINT,
                rg_row_end BIGINT,
                dom_row_start BIGINT,
                dom_row_end BIGINT,
                dom_rg_row_start BIGINT,
                dom_rg_row_end BIGINT
            );
            """
        )
        domains = sorted({row["query_domain"] for row in rows})
        connection.executemany(
            "INSERT INTO query_domains VALUES (?, ?, ?)",
            [(domain, domain, "test") for domain in domains],
        )
        connection.executemany(
            """
            INSERT INTO cc_domain_shards VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (
                    row["query_domain"],
                    row["query_domain"],
                    row["collection"],
                    row["year"],
                    row.get("shard_file") or "cdx-test.parquet",
                    row.get("source_path") or "",
                    row.get("parquet_relpath") or "cdx-test.parquet",
                    0,
                    0,
                    10,
                    row["dom_row_start"],
                    row["dom_row_end"],
                    0,
                    row["dom_row_end"] - row["dom_row_start"],
                )
                for row in rows
            ],
        )
    finally:
        connection.close()


def _write_pointer_parquet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "collection": ["CC-MAIN-2025-51"] * 4,
            "shard_file": ["cdx-test.parquet"] * 4,
            "url": [f"https://legislature.mi.gov/doc/{index}" for index in range(4)],
            "host": ["legislature.mi.gov"] * 4,
            "status": ["200"] * 4,
            "mime": ["text/html"] * 4,
            "digest": [f"digest-{index}" for index in range(4)],
            "warc_filename": [f"crawl-{index}.warc.gz" for index in range(4)],
            "warc_offset": [1000 + index for index in range(4)],
            "warc_length": [50 + index for index in range(4)],
        }
    )
    pq.write_table(table, path)


def _isolate_builtin(monkeypatch, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(shard_index, "BUILTIN_SHARD_DIR", directory)
    monkeypatch.delenv("GOVERNMENT_CC_SHARD_DIR", raising=False)
    monkeypatch.delenv("GOVERNMENT_CC_SHARD_INDEX", raising=False)


def test_host_region_inference_skips_commercial_tlds() -> None:
    assert shard_index.host_key("http://www.www.comunacosoveni.ro/path") == "comunacosoveni.ro"
    assert shard_index.region_for_host("legislature.mi.gov") == "americas"
    assert shard_index.region_for_host("www.legislation.gov.uk") == "europe"
    assert shard_index.region_for_host("gov.cn") == "asia_pacific"
    assert shard_index.region_for_host("example.com") is None
    assert shard_index.region_for_host("municode.com") is None
    assert shard_index.normalize_shard_region("apac") == "asia_pacific"


def test_commercial_host_does_not_open_or_download_shard_dbs(monkeypatch) -> None:
    def _unexpected(*_args, **_kwargs):
        raise AssertionError("shard database should not be resolved")

    monkeypatch.setattr(shard_index, "shard_db_path", _unexpected)
    monkeypatch.setattr(shard_index, "government_shard_parquet_urls", _unexpected)
    assert shard_index.query_government_shards("https://example.com/a", download=True) == []
    assert shard_index.query_government_shards("municode.com", download=True) == []


def _write_zstd_parquet(path: Path, table: str, rows: list[dict]) -> None:
    import duckdb

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    try:
        if table == "query_domains":
            connection.execute(
                "CREATE TABLE query_domains (domain VARCHAR, host_rev VARCHAR, sources VARCHAR)"
            )
            connection.executemany(
                "INSERT INTO query_domains VALUES (?, ?, ?)",
                [(row["domain"], row["domain"], "test") for row in rows],
            )
            select_sql = "SELECT * FROM query_domains ORDER BY domain"
        else:
            connection.execute(
                """
                CREATE TABLE cc_domain_shards (
                    query_domain VARCHAR, host_rev VARCHAR, collection VARCHAR, year INTEGER,
                    shard_file VARCHAR, source_path VARCHAR, parquet_relpath VARCHAR,
                    row_group INTEGER, rg_row_start BIGINT, rg_row_end BIGINT,
                    dom_row_start BIGINT, dom_row_end BIGINT,
                    dom_rg_row_start INTEGER, dom_rg_row_end INTEGER
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO cc_domain_shards VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    (
                        row["query_domain"],
                        row["query_domain"],
                        row["collection"],
                        row["year"],
                        "cdx-test.parquet",
                        "",
                        "cdx-test.parquet",
                        0,
                        0,
                        10,
                        row["dom_row_start"],
                        row["dom_row_end"],
                        0,
                        row["dom_row_end"] - row["dom_row_start"],
                    )
                    for row in rows
                ],
            )
            select_sql = "SELECT * FROM cc_domain_shards"
        temporary = path.with_suffix(".parquet.partial")
        connection.execute(
            f"""
            COPY ({select_sql}) TO '{temporary}'
            (FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3, ROW_GROUP_SIZE 65536)
            """
        )
        temporary.replace(path)
    finally:
        connection.close()


def test_parquet_urls_keep_one_datasets_config_and_split() -> None:
    payload = {
        "parquet_files": [
            {"config": "cc_domain_shards", "split": "europe", "url": "https://example.test/europe.parquet"},
            {"config": "cc_domain_shards", "split": "americas", "url": "https://example.test/americas.parquet"},
            {"config": "query_domains", "split": "europe", "url": "https://example.test/domains.parquet"},
        ]
    }
    assert shard_index.parquet_urls_from_datasets_payload(
        payload, table="cc_domain_shards", region="europe"
    ) == ["https://example.test/europe.parquet"]


def test_local_zstd_parquet_answers_when_duckdb_is_absent(monkeypatch, tmp_path: Path) -> None:
    _isolate_builtin(monkeypatch, tmp_path / "empty")
    root = tmp_path / "parquet"
    _write_zstd_parquet(
        root / "query_domains" / "europe.parquet",
        "query_domains",
        [{"domain": "legislation.gov.uk"}],
    )
    _write_zstd_parquet(
        root / "cc_domain_shards" / "europe.parquet",
        "cc_domain_shards",
        [
            {
                "query_domain": "legislation.gov.uk",
                "collection": "CC-MAIN-2025-51",
                "year": 2025,
                "dom_row_start": 10,
                "dom_row_end": 12,
            }
        ],
    )
    monkeypatch.setattr(shard_index, "BUILTIN_SHARD_DIR", tmp_path)
    rows = shard_index.query_government_shards(
        "https://www.legislation.gov.uk/ukpga",
        download=False,
        max_segments=3,
    )
    assert rows[0]["query_domain"] == "legislation.gov.uk"
    assert rows[0]["region"] == "europe"
    assert rows[0]["dom_row_start"] == 10

    def _urls(region: str, table: str) -> list[str]:
        return [str(root / table / f"{region}.parquet")]

    monkeypatch.setattr(shard_index, "BUILTIN_SHARD_DIR", tmp_path / "missing")
    monkeypatch.setattr(shard_index, "government_shard_parquet_urls", _urls)
    remote = shard_index.query_government_shards(
        "www.legislation.gov.uk",
        download=True,
        max_segments=1,
    )
    assert remote[0]["collection"] == "CC-MAIN-2025-51"
    assert remote[0]["hf_repo"] == "Publicus/government_cc_shard_indexes"


def test_loader_reads_local_parquet_with_datasets(monkeypatch, tmp_path: Path) -> None:
    _isolate_builtin(monkeypatch, tmp_path / "empty-builtin")
    base = tmp_path / "indexes"
    shard_dir = base / "government_shards"
    _write_zstd_parquet(
        shard_dir / "parquet" / "cc_domain_shards" / "mena.parquet",
        "cc_domain_shards",
        [
            {
                "query_domain": "gov.sa",
                "collection": "CC-MAIN-2024-10",
                "year": 2024,
                "dom_row_start": 0,
                "dom_row_end": 4,
            }
        ],
    )
    loader = CommonCrawlIndexLoader(local_base_dir=base, use_hf_fallback=False)
    dataset = loader.load_government_shards(table="cc_domain_shards", split="mena")
    assert dataset is not None
    assert dataset[0]["query_domain"] == "gov.sa"
    assert int(dataset[0]["dom_row_end"]) == 4


def test_parent_domain_and_pointer_window(monkeypatch, tmp_path: Path) -> None:
    parquet_path = tmp_path / "pointers" / "cdx-test.parquet"
    _write_pointer_parquet(parquet_path)
    _isolate_builtin(monkeypatch, tmp_path / "shards")
    _write_shard_db(
        tmp_path / "shards" / "americas.duckdb",
        [
            {
                "query_domain": "mi.gov",
                "collection": "CC-MAIN-2024-10",
                "year": 2024,
                "source_path": str(parquet_path),
                "dom_row_start": 1,
                "dom_row_end": 3,
            },
            {
                "query_domain": "mi.gov",
                "collection": "CC-MAIN-2025-51",
                "year": 2025,
                "source_path": str(parquet_path),
                "dom_row_start": 1,
                "dom_row_end": 4,
            },
            {
                "query_domain": "municode.com",
                "collection": "CC-MAIN-2025-51",
                "year": 2025,
                "source_path": str(tmp_path / "missing.parquet"),
                "dom_row_start": 0,
                "dom_row_end": 2,
            },
        ],
    )
    _write_shard_db(
        tmp_path / "shards" / "europe.duckdb",
        [
            {
                "query_domain": "legislation.gov.uk",
                "collection": "CC-MAIN-2025-51",
                "year": 2025,
                "source_path": str(parquet_path),
                "dom_row_start": 0,
                "dom_row_end": 1,
            }
        ],
    )

    rows = shard_index.query_government_shards("https://www.legislature.mi.gov/a", max_segments=1)
    assert rows[0]["query_domain"] == "mi.gov"
    assert rows[0]["collection"] == "CC-MAIN-2025-51"
    assert rows[0]["region"] == "americas"
    assert rows[0]["hf_repo"] == "Publicus/government_cc_shard_indexes"

    records = shard_index.read_pointer_records(rows, max_matches=2)
    assert [record["url"] for record in records] == [
        "https://legislature.mi.gov/doc/1",
        "https://legislature.mi.gov/doc/2",
    ]
    assert records[0]["warc_record_offset"] == 1001
    assert records[0]["warc_filename"] == "crawl-1.warc.gz"

    assert shard_index.query_government_shards("municode.com") == []
    municipal = shard_index.query_government_shards("municode.com", country_code="US")
    assert municipal[0]["query_domain"] == "municode.com"
    assert shard_index.read_pointer_records(municipal, max_matches=5) == []

    uk = shard_index.query_government_shards("legislation.gov.uk")
    assert uk[0]["region"] == "europe"
    assert uk[0]["query_domain"] == "legislation.gov.uk"
    assert shard_index.query_government_shards("legislation.gov.uk", country_code="US") == []


def test_loader_uses_local_government_shards_before_huggingface(monkeypatch, tmp_path: Path) -> None:
    _isolate_builtin(monkeypatch, tmp_path / "empty-builtin")
    base = tmp_path / "indexes"
    _write_shard_db(
        base / "government_shards" / "americas.duckdb",
        [
            {
                "query_domain": "ca.gov",
                "collection": "CC-MAIN-2025-51",
                "year": 2025,
                "dom_row_start": 0,
                "dom_row_end": 1,
            }
        ],
    )

    loader = CommonCrawlIndexLoader(local_base_dir=base, use_hf_fallback=False)
    rows = loader.query_government_shards("www.ca.gov", max_segments=3)
    assert rows[0]["query_domain"] == "ca.gov"
    assert loader.government_shard_db("europe") is None
    info = loader.get_index_info()
    assert info["indexes"]["government_shards"]["hf_repo"] == "Publicus/government_cc_shard_indexes"
    assert info["indexes"]["government_shards"]["regions"]["americas"]["local_available"] is True
    assert info["indexes"]["government_shards"]["regions"]["europe"]["local_available"] is False


def test_region_method_and_search_domain_fast_path(monkeypatch, tmp_path: Path) -> None:
    parquet_path = tmp_path / "cdx-test.parquet"
    _write_pointer_parquet(parquet_path)
    _isolate_builtin(monkeypatch, tmp_path / "shards")
    _write_shard_db(
        tmp_path / "shards" / "americas.duckdb",
        [
            {
                "query_domain": "mi.gov",
                "collection": "CC-MAIN-2025-51",
                "year": 2025,
                "source_path": str(parquet_path),
                "dom_row_start": 2,
                "dom_row_end": 4,
            }
        ],
    )
    _write_shard_db(
        tmp_path / "shards" / "europe.duckdb",
        [
            {
                "query_domain": "legislation.gov.uk",
                "collection": "CC-MAIN-2025-51",
                "year": 2025,
                "source_path": str(parquet_path),
                "dom_row_start": 0,
                "dom_row_end": 1,
            }
        ],
    )

    americas = LegalRegion(region_id="americas", display_name="Americas")
    regional = americas.common_crawl_shards("legislature.mi.gov", download=False, max_segments=2)
    assert regional[0]["query_domain"] == "mi.gov"

    calls = {"local": 0}

    def _local(_domain, _max_matches, _collection, **_kwargs):
        calls["local"] += 1
        return [{"url": "https://example.com/fallback", "filename": "fallback.warc.gz", "offset": 9, "length": 8}]

    engine = SimpleNamespace(
        _available=True,
        mode="local",
        _hf_fallback_enabled=False,
        _normalize_records=CommonCrawlSearchEngine._normalize_records,
        _search_domain_local=_local,
    )
    hit = CommonCrawlSearchEngine.search_domain(engine, "legislature.mi.gov", max_matches=5)
    assert calls["local"] == 0
    assert hit[0]["warc_filename"] == "crawl-2.warc.gz"
    assert hit[0]["warc_record_offset"] == 1002
    assert "wayback_url" not in hit[0]

    uk = CommonCrawlSearchEngine.search_domain(
        engine,
        "legislation.gov.uk",
        max_matches=3,
        country_code="US",
        government_shard_download=True,
    )
    assert calls["local"] == 0
    assert uk[0]["query_domain"] == "legislation.gov.uk"
    assert uk[0]["region"] == "europe"

    missing = CommonCrawlSearchEngine.search_domain(engine, "example.com", max_matches=3)
    assert calls["local"] == 1
    assert missing[0]["url"] == "https://example.com/fallback"
    assert missing[0]["offset"] == 9

    monkeypatch.setenv("GOVERNMENT_CC_SHARD_INDEX", "0")
    disabled = _government_shard_matches("legislature.mi.gov", 2, None, {}, download=False)
    assert disabled is None


def test_archive_fallbacks_prefer_shard_collections_without_package_import(
    monkeypatch, tmp_path: Path
) -> None:
    for path in (_NATIONAL_FALLBACKS, _INTERNATIONAL_FALLBACKS):
        source = path.read_text(encoding="utf-8")
        assert "import ipfs_datasets_py" not in source
        if path == _INTERNATIONAL_FALLBACKS:
            # international/helpers/archive_fallbacks.py is a shim over the national module.
            assert "national_collectors" in source and "exec(compile(" in source
            source = _NATIONAL_FALLBACKS.read_text(encoding="utf-8")
        assert "regions" in source and "shard_index.py" in source

    monkeypatch.setenv("GOVERNMENT_CC_SHARD_DIR", str(tmp_path))
    monkeypatch.setenv("CC_INDEX_N", "1")
    monkeypatch.delenv("GOVERNMENT_CC_SHARD_INDEX", raising=False)
    _write_shard_db(
        tmp_path / "europe.duckdb",
        [
            {
                "query_domain": "legislation.gov.uk",
                "collection": "CC-MAIN-2024-22",
                "year": 2024,
                "dom_row_start": 0,
                "dom_row_end": 2,
            },
            {
                "query_domain": "legislation.gov.uk",
                "collection": "CC-MAIN-2025-51",
                "year": 2025,
                "dom_row_start": 0,
                "dom_row_end": 2,
            },
        ],
    )

    for name, path in (
        ("nc_archive_fallbacks_under_test", _NATIONAL_FALLBACKS),
        ("intl_archive_fallbacks_under_test", _INTERNATIONAL_FALLBACKS),
    ):
        module = _load_module(path, name)
        assert module._government_shard_indexes("https://example.com/", 4) == []
        indexes = module._government_shard_indexes("https://www.legislation.gov.uk/id/uksi", 1)
        assert indexes == ["https://index.commoncrawl.org/CC-MAIN-2025-51-index"]

        seen: list[str] = []

        class _Response:
            status_code = 200
            content = b""
            text = ""

        def _get(url, params=None, timeout=None):
            seen.append(url)
            return _Response()

        monkeypatch.setattr(module, "session", lambda: SimpleNamespace(get=_get))
        monkeypatch.setattr(module, "_sleep_cc", lambda *_args, **_kwargs: None)
        explicit = "https://index.commoncrawl.org/CC-MAIN-1999-01-index"
        assert module.search_common_crawl("https://legislation.gov.uk/a", indexes=[explicit]) == []
        assert seen == [explicit]
        seen.clear()
        assert module.search_common_crawl("https://legislation.gov.uk/a", limit=1) == []
        assert seen == ["https://index.commoncrawl.org/CC-MAIN-2025-51-index"]
        seen.clear()
