"""Regional Common Crawl shard indexes for government hosts.

Local lookup uses the regional DuckDB files when they are present. The
Hugging Face dataset ``Publicus/government_cc_shard_indexes`` stores the same
tables as ZSTD Parquet so the datasets library can open one config and split.
A stored domain covers that host and its subdomains. ``dom_row_start`` and
``dom_row_end`` are inclusive-exclusive row offsets in the sorted pointer
parquet named by ``shard_file``.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

GOVERNMENT_SHARD_REPO = "Publicus/government_cc_shard_indexes"
GOVERNMENT_SHARD_TABLES = (
    "cc_domain_shards",
    "query_domains",
    "domain_coverage",
    "build_info",
)
DATASETS_PARQUET_API = "https://datasets-server.huggingface.co/parquet"
GOVERNMENT_SHARD_REGIONS = (
    "americas",
    "europe",
    "mena",
    "africa",
    "asia_pacific",
    "unassigned",
)
BUILTIN_SHARD_DIR = Path("/storage/ccindex_duckdb/government_primary_sources_by_region")
_SHARD_COLUMNS = (
    "query_domain",
    "host_rev",
    "collection",
    "year",
    "shard_file",
    "source_path",
    "parquet_relpath",
    "row_group",
    "rg_row_start",
    "rg_row_end",
    "dom_row_start",
    "dom_row_end",
    "dom_rg_row_start",
    "dom_rg_row_end",
)


def shard_index_enabled() -> bool:
    raw = os.getenv("GOVERNMENT_CC_SHARD_INDEX")
    if raw is None:
        return True
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _mapping():
    try:
        from .mapping import normalize_region_id, region_for_country
    except ImportError:
        path = Path(__file__).resolve().with_name("mapping.py")
        spec = importlib.util.spec_from_file_location("legal_region_mapping_standalone", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load region mapping from {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        normalize_region_id = module.normalize_region_id
        region_for_country = module.region_for_country
    return normalize_region_id, region_for_country


def normalize_shard_region(value: str) -> str:
    normalize_region_id, _region_for_country = _mapping()
    text = normalize_region_id(value)
    if text == "unassigned":
        return text
    if text not in GOVERNMENT_SHARD_REGIONS:
        raise KeyError(f"Unknown government shard region: {value}")
    return text


def region_for_country_code(country_code: str) -> str:
    _normalize_region_id, region_for_country = _mapping()
    code = str(country_code or "").strip().upper()
    if code == "UK":
        code = "GB"
    try:
        return region_for_country(code)
    except KeyError:
        return "unassigned"


def host_key(value: str) -> str:
    raw = str(value or "").strip()
    if "://" in raw:
        raw = urlparse(raw).hostname or ""
    host = raw.lower().strip().strip(".")
    while host.startswith("www."):
        host = host[4:]
    return host


def region_for_host(host: str) -> Optional[str]:
    """Infer a shard region from a government ccTLD or a US .gov host."""
    host = host_key(host)
    if not host or "." not in host:
        return None
    last = host.rsplit(".", 1)[-1]
    if last in {"gov", "mil"} or host.endswith(".us"):
        return "americas"
    if last in {"uk", "eu"}:
        return "europe"
    if len(last) != 2 or last.isdigit():
        return None
    try:
        region = region_for_country_code(last)
    except KeyError:
        return None
    if region == "unassigned":
        return None
    return region


def _candidate_dirs(
    extra_dirs: Optional[Sequence[os.PathLike[str] | str]] = None,
) -> list[Path]:
    dirs: list[Path] = []
    configured = str(os.getenv("GOVERNMENT_CC_SHARD_DIR") or "").strip()
    if configured:
        dirs.append(Path(configured).expanduser())
    dirs.append(BUILTIN_SHARD_DIR)
    for extra in extra_dirs or ():
        path = Path(extra).expanduser()
        if path not in dirs:
            dirs.append(path)
    return dirs


def shard_db_path(
    region: str,
    *,
    download: bool = False,
    cache_dir: Optional[os.PathLike[str] | str] = None,
    extra_dirs: Optional[Sequence[os.PathLike[str] | str]] = None,
) -> Optional[Path]:
    """Return a local regional DuckDB. Remote copies are Parquet, not DuckDB."""
    del download, cache_dir
    normalized = normalize_shard_region(region)
    filename = f"{normalized}.duckdb"
    for directory in _candidate_dirs(extra_dirs):
        path = directory / filename
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def shard_parquet_path(
    region: str,
    table: str,
    *,
    extra_dirs: Optional[Sequence[os.PathLike[str] | str]] = None,
) -> Optional[Path]:
    """Return one local ZSTD Parquet file for a region table."""
    if table not in GOVERNMENT_SHARD_TABLES:
        raise KeyError(f"Unknown government shard table: {table}")
    normalized = normalize_shard_region(region)
    relative = Path(table) / f"{normalized}.parquet"
    for directory in _candidate_dirs(extra_dirs):
        for path in (directory / "parquet" / relative, directory / relative):
            if path.is_file() and path.stat().st_size > 0:
                return path
    return None


def parquet_urls_from_datasets_payload(
    payload: Mapping[str, object],
    *,
    table: str,
    region: str,
) -> list[str]:
    """Keep datasets-server parquet URLs for one config and split."""
    urls: list[str] = []
    files = payload.get("parquet_files") or []
    if not isinstance(files, list):
        return urls
    for item in files:
        if not isinstance(item, Mapping):
            continue
        config = str(item.get("config") or "")
        split = str(item.get("split") or "")
        if config not in {"", table} or split not in {"", region}:
            continue
        file_url = str(item.get("url") or "")
        if file_url:
            urls.append(file_url)
    return urls


def government_shard_parquet_urls(region: str, table: str) -> list[str]:
    """Resolve Parquet URLs for one split through the datasets API.

    The datasets server is checked first. The datasets library's dataset
    builder is the fallback and reads the same config paths from the dataset
    card.
    """
    normalized = normalize_shard_region(region)
    if table not in GOVERNMENT_SHARD_TABLES:
        raise KeyError(f"Unknown government shard table: {table}")
    query = urlencode(
        {
            "dataset": GOVERNMENT_SHARD_REPO,
            "config": table,
            "split": normalized,
        }
    )
    try:
        with urlopen(Request(f"{DATASETS_PARQUET_API}?{query}"), timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        urls = parquet_urls_from_datasets_payload(
            payload, table=table, region=normalized
        )
        if urls:
            return urls
    except Exception:
        urls = []
    try:
        from datasets import load_dataset_builder
    except ImportError:
        return []
    try:
        builder = load_dataset_builder(GOVERNMENT_SHARD_REPO, table)
        data_files = builder.config.data_files
        items = data_files[normalized] if data_files is not None else []
    except Exception:
        return []
    resolved: list[str] = []
    for item in items:
        file_url = getattr(item, "url", None) or getattr(item, "filename", None) or str(item)
        if file_url:
            resolved.append(str(file_url))
    return resolved


def _regions_for_query(
    host: str,
    *,
    region: Optional[str],
    country_code: Optional[str],
) -> list[str]:
    if region:
        return [normalize_shard_region(region)]
    if country_code:
        return [region_for_country_code(country_code)]
    inferred = region_for_host(host)
    return [inferred] if inferred else []


def _parquet_scan(paths: Sequence[str]) -> str:
    quoted = ", ".join(_sql_quote(str(path)) for path in paths)
    if len(paths) == 1:
        return f"read_parquet({_sql_quote(str(paths[0]))})"
    return f"read_parquet([{quoted}])"


def _rows_from_shard_sql(connection, sql: str, params: Sequence[object], region_id: str):
    result = connection.execute(sql, list(params))
    names = [str(item[0]) for item in (result.description or ())]
    rows = []
    for values in result.fetchall():
        row = dict(zip(names, values))
        row["region"] = region_id
        row["hf_repo"] = GOVERNMENT_SHARD_REPO
        rows.append(row)
    return rows


def _query_duckdb_file(
    path: Path,
    host: str,
    *,
    region_id: str,
    collection: Optional[str],
    limit: int,
) -> list[dict[str, object]]:
    import duckdb

    columns = ", ".join(_SHARD_COLUMNS)
    connection = duckdb.connect(str(path), read_only=True)
    try:
        cover = _covering_domain(connection, host)
        if not cover:
            return []
        sql = f"SELECT {columns} FROM cc_domain_shards WHERE query_domain = ?"
        params: list[object] = [cover]
        if collection:
            sql += " AND collection = ?"
            params.append(str(collection))
        sql += " ORDER BY year DESC, collection DESC, dom_row_start LIMIT ?"
        params.append(limit)
        return _rows_from_shard_sql(connection, sql, params, region_id)
    finally:
        connection.close()


def _covering_domain_parquet(connection, scan: str, host: str) -> str:
    parts = host.split(".")
    for index in range(len(parts)):
        candidate = ".".join(parts[index:])
        found = connection.execute(
            f"SELECT 1 FROM {scan} WHERE domain = ? LIMIT 1",
            [candidate],
        ).fetchone()
        if found:
            return candidate
    return ""


def _query_parquet_files(
    domain_files: Sequence[str],
    shard_files: Sequence[str],
    host: str,
    *,
    region_id: str,
    collection: Optional[str],
    limit: int,
) -> list[dict[str, object]]:
    import duckdb

    if not domain_files or not shard_files:
        return []
    columns = ", ".join(_SHARD_COLUMNS)
    domains = _parquet_scan(domain_files)
    shards = _parquet_scan(shard_files)
    connection = duckdb.connect()
    try:
        cover = _covering_domain_parquet(connection, domains, host)
        if not cover:
            return []
        sql = f"SELECT {columns} FROM {shards} WHERE query_domain = ?"
        params: list[object] = [cover]
        if collection:
            sql += " AND collection = ?"
            params.append(str(collection))
        sql += " ORDER BY year DESC, collection DESC, dom_row_start LIMIT ?"
        params.append(limit)
        return _rows_from_shard_sql(connection, sql, params, region_id)
    finally:
        connection.close()


def _materialize_parquet_urls(
    urls: Sequence[str],
    *,
    cache_dir: Optional[os.PathLike[str] | str],
) -> list[str]:
    local: list[str] = []
    remote = [
        url
        for url in urls
        if str(url).startswith(("http://", "https://", "hf://"))
    ]
    plain = [str(url) for url in urls if str(url) not in remote]
    local.extend(plain)
    if not remote:
        return local
    try:
        from datasets.utils.file_utils import cached_path
    except ImportError:
        return local
    for url in remote:
        try:
            downloaded = cached_path(
                url,
                cache_dir=str(cache_dir) if cache_dir else None,
            )
        except Exception:
            continue
        if downloaded:
            local.append(str(downloaded))
    return local


def query_government_shards(
    host: str,
    *,
    region: Optional[str] = None,
    country_code: Optional[str] = None,
    collection: Optional[str] = None,
    max_segments: int = 50,
    download: bool = False,
    cache_dir: Optional[os.PathLike[str] | str] = None,
    extra_dirs: Optional[Sequence[os.PathLike[str] | str]] = None,
) -> list[dict[str, object]]:
    """Return pointer-parquet ranges for a government host.

    A local DuckDB is used when that region file exists. Otherwise local ZSTD
    Parquet is used. With ``download=True``, missing files are resolved through
    the Hugging Face datasets API.
    """
    if not shard_index_enabled():
        return []
    normalized_host = host_key(host)
    if not normalized_host or "." not in normalized_host:
        return []
    try:
        import duckdb  # noqa: F401
    except ImportError:
        return []

    limit = max(1, int(max_segments or 1))
    for region_id in _regions_for_query(
        normalized_host, region=region, country_code=country_code
    ):
        database = shard_db_path(region_id, extra_dirs=extra_dirs)
        if database is not None:
            rows = _query_duckdb_file(
                database,
                normalized_host,
                region_id=region_id,
                collection=collection,
                limit=limit,
            )
            if rows:
                return rows
            continue
        domain_path = shard_parquet_path(
            region_id, "query_domains", extra_dirs=extra_dirs
        )
        shard_path = shard_parquet_path(
            region_id, "cc_domain_shards", extra_dirs=extra_dirs
        )
        if domain_path is not None and shard_path is not None:
            rows = _query_parquet_files(
                [str(domain_path)],
                [str(shard_path)],
                normalized_host,
                region_id=region_id,
                collection=collection,
                limit=limit,
            )
            if rows:
                return rows
            continue
        if not download:
            continue
        domain_urls = _materialize_parquet_urls(
            government_shard_parquet_urls(region_id, "query_domains"),
            cache_dir=cache_dir,
        )
        shard_urls = _materialize_parquet_urls(
            government_shard_parquet_urls(region_id, "cc_domain_shards"),
            cache_dir=cache_dir,
        )
        rows = _query_parquet_files(
            domain_urls,
            shard_urls,
            normalized_host,
            region_id=region_id,
            collection=collection,
            limit=limit,
        )
        if rows:
            return rows
    return []


def _covering_domain(connection, host: str) -> str:
    parts = host.split(".")
    for index in range(len(parts)):
        candidate = ".".join(parts[index:])
        found = connection.execute(
            "SELECT 1 FROM query_domains WHERE domain = ?",
            [candidate],
        ).fetchone()
        if found:
            return candidate
    return ""


def shard_collections(
    host: str,
    *,
    region: Optional[str] = None,
    country_code: Optional[str] = None,
    limit: int = 8,
    download: bool = False,
) -> list[str]:
    """Newest Common Crawl collection ids that contain this host."""
    rows = query_government_shards(
        host,
        region=region,
        country_code=country_code,
        max_segments=max(1, int(limit or 1)) * 40,
        download=download,
    )
    collections: list[str] = []
    for row in rows:
        collection = str(row.get("collection") or "")
        if collection and collection not in collections:
            collections.append(collection)
        if len(collections) >= max(1, int(limit or 1)):
            break
    return collections


def pointer_parquet_path(
    row: Mapping[str, object],
    parquet_root: Optional[os.PathLike[str] | str] = None,
) -> Optional[Path]:
    source = Path(str(row.get("source_path") or ""))
    if str(source) and source.is_file():
        return source
    year = str(row.get("year") or "")
    collection = str(row.get("collection") or "")
    shard = str(row.get("shard_file") or "")
    if not (year and collection and shard):
        return None
    roots: list[Path] = []
    if parquet_root:
        roots.append(Path(parquet_root))
    configured = str(os.getenv("CCINDEX_PARQUET_ROOT") or "").strip()
    if configured:
        roots.append(Path(configured).expanduser())
    roots.append(Path("/storage/ccindex_parquet"))
    for root in roots:
        for candidate in (
            root / "cc_pointers_by_collection" / year / collection / shard,
            root / year / collection / shard,
        ):
            if candidate.is_file():
                return candidate
    return None


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def read_pointer_records(
    rows: Sequence[Mapping[str, object]],
    *,
    max_matches: int,
    parquet_root: Optional[os.PathLike[str] | str] = None,
) -> list[dict[str, object]]:
    """Read WARC pointer rows for the given shard windows."""
    if not rows or max_matches < 1:
        return []
    try:
        import duckdb
    except ImportError:
        return []
    records: list[dict[str, object]] = []
    connection = duckdb.connect()
    try:
        for row in rows:
            if len(records) >= max_matches:
                break
            path = pointer_parquet_path(row, parquet_root)
            if path is None:
                continue
            start = int(row.get("dom_row_start") or 0)
            end = int(row.get("dom_row_end") or 0)
            if end <= start:
                continue
            remaining = max_matches - len(records)
            limit = min(remaining, end - start)
            fetched = connection.execute(
                f"""
                SELECT collection, shard_file, url, host, status, mime, digest,
                       warc_filename, warc_offset, warc_length
                FROM read_parquet({_sql_quote(str(path))})
                WHERE file_row_number >= ? AND file_row_number < ?
                LIMIT {int(limit)}
                """,
                [start, end],
            ).fetchall()
            for item in fetched:
                records.append(
                    {
                        "collection": item[0],
                        "shard_file": item[1],
                        "url": item[2],
                        "host": item[3],
                        "status": item[4],
                        "mime": item[5],
                        "digest": item[6],
                        "warc_filename": item[7],
                        "warc_offset": item[8],
                        "warc_length": item[9],
                        "warc_record_offset": item[8],
                        "warc_record_length": item[9],
                        "region": row.get("region"),
                        "query_domain": row.get("query_domain"),
                        "source": "government_cc_shard_index",
                    }
                )
    finally:
        connection.close()
    return records


def iter_local_regions() -> Iterable[str]:
    found = []
    for region in GOVERNMENT_SHARD_REGIONS:
        if shard_db_path(region, download=False) is not None:
            found.append(region)
    return found
