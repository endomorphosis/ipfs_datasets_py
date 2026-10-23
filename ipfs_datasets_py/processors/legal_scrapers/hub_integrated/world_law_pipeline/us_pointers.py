"""US pointer rows for world_municipal_law/world_law/places.parquet.

The US municipal corpus stays in endomorphosis/american_municipal_law (read-only for us; never written). Each
GNIS place there gets ONE row in world_municipal_law's places.parquet with has_local_data=false, source_repo and
source_paths (every html parquet holding that GNIS: american_law/data/, data_2/, data_3/ and the repo root).
html_path is the copy with the most rows (the one the loader reads), total_docs is that row count.

Refreshed from the US repo listing at most once per REFRESH_S (cache: state/us_pointers.json). Only new or
changed html files (by blob oid) get their parquet footer read; only new metadata JSON is fetched. Any failure
keeps the previous cache, so a Hub problem never drops the pointer rows or fails the run."""
import concurrent.futures as cf
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

US_REPO = "endomorphosis/american_municipal_law"
REFRESH_S = 24 * 3600
_HTML = re.compile(r"^(?:american_law/(?:data|data_2|data_3)/)?(\d+)_html\.parquet$")
_META = re.compile(r"^(?:american_law/(?:data/|data_2/)?)?metadata/(\d+)\.json$")
_DIR_RANK = {"american_law/data_3": 0, "american_law/data_2": 1, "american_law/data": 2, "": 3}


def admin_level(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    n = name.lower()
    if re.search(r"\b(county|parish|borough of .* county)\b", n) or n.endswith(" county"):
        return "county"
    if "township" in n:
        return "township"
    return "municipality"


def _log(msg):
    try:
        from run_loop import log  # type: ignore
        log(msg)
    except Exception:  # noqa: BLE001
        print(msg, flush=True)


def _footer_rows(fs, rev: str, path: str) -> Optional[int]:
    import pyarrow.parquet as pq
    for _ in range(3):
        try:
            with fs.open(f"datasets/{US_REPO}@{rev}/{path}", "rb") as fh:
                return pq.ParquetFile(fh).metadata.num_rows
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


def _meta(api, rev: str, path: str) -> Optional[Dict[str, Any]]:
    from huggingface_hub import hf_hub_download
    for _ in range(3):
        try:
            return json.loads(Path(hf_hub_download(US_REPO, path, repo_type="dataset", revision=rev)).read_text())
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


def refresh(cache_path: Path, api=None, force: bool = False, workers: int = 16,
            seed_rows: Optional[Dict[str, tuple]] = None, seed_meta_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Return the cache dict {built_at, revision, files:{path:{oid,rows}}, meta:{path:{...}}, rows:[...]}."""
    cache: Dict[str, Any] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except Exception:  # noqa: BLE001
            cache = {}
    if not force and cache.get("rows") and time.time() - cache.get("built_ts", 0) < REFRESH_S:
        return cache
    try:
        from huggingface_hub import HfApi, HfFileSystem
        api = api or HfApi()
        rev = api.dataset_info(US_REPO).sha
        files: Dict[str, Any] = dict(cache.get("files") or {})
        meta: Dict[str, Any] = dict(cache.get("meta") or {})
        html, metas, sizes = {}, {}, {}
        for e in api.list_repo_tree(US_REPO, repo_type="dataset", revision=rev, recursive=True):
            p = getattr(e, "path", "")
            if _HTML.match(p):
                html[p] = getattr(e, "blob_id", None) or getattr(e, "oid", None)
                sizes[p] = getattr(e, "size", None)
            elif _META.match(p):
                metas[p] = getattr(e, "blob_id", None) or getattr(e, "oid", None)
        todo = [p for p, oid in html.items() if files.get(p, {}).get("oid") != oid or files[p].get("rows") is None]
        for p in todo:
            # seed_rows: {path: (size, rows)} from an earlier footer scan; used only when the size still matches
            if seed_rows and p in seed_rows and p not in files and seed_rows[p][0] == sizes.get(p):
                files[p] = {"oid": html[p], "rows": seed_rows[p][1]}
        todo = [p for p in todo if files.get(p, {}).get("oid") != html[p] or files[p].get("rows") is None]
        fs = HfFileSystem()
        with cf.ThreadPoolExecutor(workers) as ex:
            for p, n in zip(todo, ex.map(lambda q: _footer_rows(fs, rev, q), todo)):
                files[p] = {"oid": html[p], "rows": n}
        mtodo = [p for p, oid in metas.items() if (meta.get(p) or {}).get("_oid") != oid]
        if seed_meta_dir:
            for p in list(mtodo):
                f = seed_meta_dir / p
                if f.exists() and p not in meta:
                    meta[p] = json.loads(f.read_text()) | {"_oid": metas[p]}
            mtodo = [p for p in mtodo if (meta.get(p) or {}).get("_oid") != metas[p]]
        with cf.ThreadPoolExecutor(workers) as ex:
            for p, m in zip(mtodo, ex.map(lambda q: _meta(api, rev, q), mtodo)):
                if m is not None:
                    meta[p] = m | {"_oid": metas[p]}
        files = {p: v for p, v in files.items() if p in html}
        meta = {p: v for p, v in meta.items() if p in metas}
        rows = build_rows(files, meta)
        cache = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "built_ts": time.time(),
                 "revision": rev, "files": files, "meta": meta, "rows": rows}
        tmp = cache_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cache))
        os.replace(tmp, cache_path)
        _log(f"US pointers refreshed from {US_REPO}@{rev[:8]}: {len(rows)} places "
             f"({len(todo)} footers, {len(mtodo)} metadata fetched)")
    except Exception as e:  # noqa: BLE001
        _log(f"WARN US pointer refresh failed, keeping cached rows ({len(cache.get('rows') or [])}): {e!r}")
    return cache


def build_rows(files: Dict[str, Any], meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_g: Dict[str, List[str]] = {}
    for p in files:
        by_g.setdefault(_HTML.match(p).group(1), []).append(p)
    m_by_g: Dict[str, tuple] = {}
    for p, m in meta.items():
        g = _META.match(p).group(1)
        prev = m_by_g.get(g)
        if prev is None or (m.get("last_updated") or 0) > (prev[1].get("last_updated") or 0):
            m_by_g[g] = (p, m)
    rows = []
    for g in sorted(by_g, key=int):
        paths = sorted(by_g[g], key=lambda q: (-(files[q].get("rows") or 0), _DIR_RANK.get(q.rpartition("/")[0], 9)))
        mp, m = m_by_g.get(g, (None, {}))
        lu = m.get("last_updated")
        rows.append({
            "place_id": f"gnis:{g}", "place_key": g, "qid": None, "gnis": g, "country_code": "US",
            "iso_3166_2": f"US-{m['state_code']}" if m.get("state_code") else None,
            "admin_level": admin_level(m.get("place_name")), "place_name": m.get("place_name"),
            "platform": None, "platform_place_id": None,
            "total_docs": files[paths[0]].get("rows"), "html_path": paths[0], "metadata_path": mp,
            "last_updated": int(lu) if isinstance(lu, (int, float)) else None, "n_shards": 1,
            "source_repo": US_REPO, "source_paths": sorted(paths), "has_local_data": False})
    return rows


def pointer_rows(state_dir: Path, timeout_s: float = 900) -> List[Dict[str, Any]]:
    """For run_loop: cached rows, refreshed at most daily, never blocking a run longer than timeout_s."""
    import threading
    cache_path = state_dir / "us_pointers.json"
    box: Dict[str, Any] = {}
    th = threading.Thread(target=lambda: box.update(c=refresh(cache_path)), daemon=True)
    th.start()
    th.join(timeout_s)
    if "c" not in box:
        _log(f"WARN US pointer refresh still running after {timeout_s:.0f}s; using the cached rows")
        try:
            return json.loads(cache_path.read_text()).get("rows") or []
        except Exception:  # noqa: BLE001
            return []
    return box["c"].get("rows") or []
