"""world_law_loader: one table for world_municipal_law + the US corpus (american_municipal_law).

world_municipal_law/world_law/places.parquet lists every place. Rows with has_local_data=false are POINTERS: the
documents live in `source_repo` (US: endomorphosis/american_municipal_law, 5 columns cid, doc_id, doc_order,
html_title, html) at `html_path`. This loader reads both and returns the 35-column world_law html schema; US
rows get place_id gnis:N, country_code US, gnis N, content_format html, and nulls for every other column.

    from world_law_loader import places, load
    places(countries=["US", "FR"])                       # crosswalk, pandas DataFrame
    load(countries=["NL"], max_places=5)                 # pyarrow Table, 35 columns
    load(places=["gnis:1085809", "wd:Q10001"])              # by place_id (or place_key / GNIS number / QID)
    load(countries=["DE"], include_national=True)        # + world_national_law (iso:* places)

Requires: huggingface_hub, pyarrow (pandas for places()). Files are cached by huggingface_hub."""
from __future__ import annotations

import fnmatch
import re
from typing import Iterable, Iterator, List, Optional

MUNICIPAL = "endomorphosis/world_municipal_law"
NATIONAL = "endomorphosis/world_national_law"
US_REPO = "endomorphosis/american_municipal_law"
PDF_REPO = "endomorphosis/world_law_scanned_pdfs"  # raw image-only scanned PDFs (pdf_ref targets)
US_COLUMNS = ["cid", "doc_id", "doc_order", "html_title", "html"]

_S = "string"
WORLD_COLUMNS = [  # name, arrow type (all nullable in loader output)
    ("cid", _S), ("doc_id", _S), ("doc_order", "uint32"), ("html_title", _S), ("html", _S), ("place_id", _S),
    ("country_code", _S), ("gnis", _S), ("source_platform", _S), ("source_url", _S), ("doc_type", _S),
    ("language", _S), ("title_native", _S), ("number", _S), ("adopted_date", _S), ("published_date", _S),
    ("effective_date", _S), ("in_force", "bool"), ("consolidated", "bool"), ("content_format", _S), ("text", _S),
    ("retrieved_at", _S), ("archive_source", _S), ("archive_crawl_id", _S), ("archive_timestamp", _S),
    ("archive_url", _S), ("original_url", _S), ("content_complete", "bool"), ("possibly_stale", "bool"),
    ("source_policy", _S), ("source_official", "bool"), ("source_org", _S), ("license_note", _S),
    ("extra_metadata", _S), ("pdf_ref", _S)]  # pdf_ref: v1.2.0 (null in older files)


def world_schema():
    import pyarrow as pa
    t = {"string": pa.string(), "uint32": pa.uint32(), "bool": pa.bool_()}
    return pa.schema([pa.field(n, t[k], nullable=True) for n, k in WORLD_COLUMNS])


def _dl(repo: str, path: str, revision: Optional[str] = None) -> str:
    from huggingface_hub import hf_hub_download
    return hf_hub_download(repo, path, repo_type="dataset", revision=revision)


def places_table(include_national: bool = False, revision: Optional[str] = None):
    import pyarrow as pa
    import pyarrow.parquet as pq
    t = pq.read_table(_dl(MUNICIPAL, "world_law/places.parquet", revision))
    if "has_local_data" not in t.column_names:  # older places.parquet without pointer columns
        t = t.append_column("source_repo", pa.array([MUNICIPAL] * t.num_rows))
        t = t.append_column("source_paths", pa.nulls(t.num_rows, pa.list_(pa.string())))
        t = t.append_column("has_local_data", pa.array([True] * t.num_rows))
    if include_national:
        n = pq.read_table(_dl(NATIONAL, "world_law/places.parquet"))
        for c, v in (("source_repo", pa.array([NATIONAL] * n.num_rows)),
                     ("source_paths", pa.nulls(n.num_rows, pa.list_(pa.string()))),
                     ("has_local_data", pa.array([True] * n.num_rows))):
            if c not in n.column_names:
                n = n.append_column(c, v)
        t = pa.concat_tables([t, n.select(t.column_names).cast(t.schema)])
    return t


def places(countries: Optional[Iterable[str]] = None, include_national: bool = False):
    """Place crosswalk as a pandas DataFrame, optionally filtered by ISO country codes."""
    df = places_table(include_national).to_pandas()
    if countries:
        df = df[df["country_code"].isin({c.upper() for c in countries})]
    return df.reset_index(drop=True)


def _select(rows: List[dict], countries, place_filter) -> List[dict]:
    if countries:
        cs = {c.upper() for c in countries}
        rows = [r for r in rows if r["country_code"] in cs]
    if place_filter:
        want = {str(p) for p in place_filter}
        want |= {f"gnis:{p}" for p in want if p.isdigit()} | {f"wd:{p}" for p in want if p.startswith("Q")}
        rows = [r for r in rows if r["place_id"] in want or r["place_key"] in want or (r.get("gnis") or "") in want
                or (r.get("qid") or "") in want]
    return rows


def bucket(place_key: str) -> str:
    """Hash bucket of a place in big countries: first 2 hex chars of sha256(place_key)."""
    import hashlib
    return hashlib.sha256(place_key.encode("utf-8")).hexdigest()[:2]


def layout_alternatives(path: str) -> List[str]:
    """[path, same file in the other layout]. world_law/data/<CC>/<file> <-> world_law/data/<CC>/<b>/<file>
    (big countries were moved into 256 hash buckets in 2026-10; an older places.parquet may hold flat paths)."""
    parts = path.split("/")
    if len(parts) < 4 or parts[0] != "world_law" or parts[1] not in ("data", "metadata"):
        return [path]
    name = parts[-1]
    key = re.sub(r"(\.s\d{4,}(?=_html)|\.s\*(?=_html))?(_html\.parquet|\.json)$", "", name)
    if len(parts) == 4:
        return [path, "/".join(parts[:3] + [bucket(key), name])]
    if len(parts) == 5:
        return [path, "/".join(parts[:3] + [name])]
    return [path]


def _files(r: dict) -> List[str]:
    repo, p = r.get("source_repo") or MUNICIPAL, r["html_path"]
    from huggingface_hub import HfApi
    if not any(ch in p for ch in "*?["):
        cands = layout_alternatives(p)
        if len(cands) == 1:
            return cands
        try:
            have = {i.path for i in HfApi().get_paths_info(repo, cands, repo_type="dataset")}
        except Exception:  # noqa: BLE001
            return [p]
        return [next((c for c in cands if c in have), p)]
    for pat in layout_alternatives(p):  # sharded place: glob, either layout
        d = pat.rsplit("/", 1)[0]
        try:
            got = sorted(f.path for f in HfApi().list_repo_tree(repo, d, repo_type="dataset")
                         if fnmatch.fnmatch(f.path, pat))
        except Exception:  # noqa: BLE001
            got = []
        if got:
            return got
    return []


def _us_to_world(t, r: dict):
    import pyarrow as pa
    n, sch = t.num_rows, world_schema()
    fill = {"place_id": r["place_id"], "country_code": "US", "gnis": r.get("gnis") or r["place_key"],
            "content_format": "html"}
    cols = []
    for f in sch:
        if f.name in US_COLUMNS and f.name in t.column_names:
            cols.append(t.column(f.name).cast(f.type))
        elif f.name in fill:
            cols.append(pa.array([fill[f.name]] * n, f.type))
        else:
            cols.append(pa.nulls(n, f.type))
    return pa.Table.from_arrays(cols, schema=sch)


def _to_world(t):
    """Select/cast to the world schema; columns missing in older files (e.g. pdf_ref before v1.2.0) become null."""
    import pyarrow as pa
    for n, _ in WORLD_COLUMNS:
        if n not in t.column_names:
            t = t.append_column(n, pa.nulls(t.num_rows, pa.string()))
    return t.select([n for n, _ in WORLD_COLUMNS]).cast(world_schema())


# ---------------------------------------------------------------------------
# Scanned PDFs (endomorphosis/world_law_scanned_pdfs)
# ---------------------------------------------------------------------------
def load_scanned_pdf_manifest(countries: Optional[Iterable[str]] = None, published_only: bool = False,
                              revision: Optional[str] = None):
    """manifest.parquet of the scanned-PDF repo as a pyarrow Table (doc_id, place_id, country_code, source_url,
    sha256, bytes, fetched_at, source_policy, lane, law_repo, law_path, pdf_path). Filter by country codes;
    published_only keeps docs whose text row is in world_municipal_law / world_national_law."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    t = pq.read_table(_dl(PDF_REPO, "manifest.parquet", revision))
    if countries:
        t = t.filter(pc.is_in(t["country_code"], value_set=__import__("pyarrow").array(
            sorted({c.upper() for c in countries}))))
    if published_only:
        t = t.filter(pc.is_valid(t["law_repo"]))
    return t


def parse_pdf_ref_full(ref: str) -> dict:
    """Parse a pdf_ref of either layout of endomorphosis/world_law_scanned_pdfs:
      loose: '<repo>:pdfs/<CC>/[<b>/]<place_key>/<sha256>.pdf'                     -> {repo, path, sha256}
      shard: '<repo>:shards/<CC>/<YYYY>/<MM>/<CC>_<seq>.tar#member=<place_key>/<sha256>.pdf&offset=<o>&size=<n>&sha256=<h>'
                                                                                   -> {repo, path, member, offset, size, sha256}"""
    from urllib.parse import parse_qsl
    repo, sep, rest = str(ref).partition(":")
    path, _, frag = rest.partition("#")
    if not sep or not (path.startswith("pdfs/") or path.startswith("shards/")):
        raise ValueError(f"not a pdf_ref: {ref!r}")
    out = {"repo": repo, "path": path, "sha256": None}
    if frag:
        q = dict(parse_qsl(frag))
        try:
            out.update(member=q["member"], offset=int(q["offset"]), size=int(q["size"]), sha256=q.get("sha256"))
        except (KeyError, ValueError):
            raise ValueError(f"bad shard pdf_ref fragment: {ref!r}")
    elif path.startswith("shards/"):
        raise ValueError(f"shard pdf_ref without member/offset/size: {ref!r}")
    else:
        out["sha256"] = path.rsplit("/", 1)[-1][:-4]
    return out


def parse_pdf_ref(ref: str):
    """'endomorphosis/world_law_scanned_pdfs:pdfs/FR/ab/wd_Q90/<sha>.pdf' -> (repo, path). For a shard ref the
    path is the shard (.tar); use parse_pdf_ref_full for member/offset/size."""
    r = parse_pdf_ref_full(ref)
    return r["repo"], r["path"]


def _ref_of(doc) -> str:
    if isinstance(doc, str):
        return doc
    if doc.get("pdf_ref"):
        return doc["pdf_ref"]
    if doc.get("pdf_path"):
        return f"{PDF_REPO}:{doc['pdf_path']}"
    raise ValueError("doc has no pdf_ref / pdf_path (not a scanned PDF)")


def _range_get(repo: str, path: str, offset: int, size: int, revision: Optional[str] = None,
               token: Optional[str] = None, timeout: float = 120.0) -> bytes:
    """HTTP Range read of bytes [offset, offset+size) of one file of a dataset repo (resolve URL, follows the
    redirect to the CDN / xet bridge)."""
    import requests
    from huggingface_hub import hf_hub_url
    url = hf_hub_url(repo, path, repo_type="dataset", revision=revision)
    headers = {"Range": f"bytes={offset}-{offset + size - 1}"}
    if token is None:                       # same default as hf_hub_download: HF_TOKEN / saved login, if any
        try:
            from huggingface_hub import get_token
            token = get_token()
        except Exception:  # noqa: BLE001
            token = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    if r.status_code == 200 and len(r.content) > size:      # server ignored Range: slice it ourselves
        data = r.content[offset:offset + size]
    elif r.status_code in (200, 206):
        data = r.content
    else:
        raise IOError(f"range read {path} {headers['Range']}: HTTP {r.status_code}")
    if len(data) != size:
        raise IOError(f"range read {path}: got {len(data)} bytes, want {size}")
    return data


def fetch_pdf_bytes(pdf_ref, repo_id: Optional[str] = None, token: Optional[str] = None,
                    revision: Optional[str] = None, verify: bool = True) -> bytes:
    """Bytes of one scanned PDF. Shard refs: a single HTTP Range request (no tar download). Loose refs:
    hf_hub_download. verify=True checks sha256. repo_id overrides the ref's repo (e.g. a mirror)."""
    import hashlib
    r = parse_pdf_ref_full(_ref_of(pdf_ref))
    repo = repo_id or r["repo"]
    if r.get("member"):
        data = _range_get(repo, r["path"], r["offset"], r["size"], revision, token)
    else:
        from huggingface_hub import hf_hub_download
        with open(hf_hub_download(repo, r["path"], repo_type="dataset", revision=revision, token=token), "rb") as f:
            data = f.read()
    want = (pdf_ref.get("sha256") if isinstance(pdf_ref, dict) else None) or r["sha256"]
    if verify and want and hashlib.sha256(data).hexdigest() != want:
        raise IOError(f"sha256 mismatch for {r['path']} {r.get('member') or ''}")
    return data


def fetch_pdf(doc, verify: bool = True, revision: Optional[str] = None, repo_id: Optional[str] = None,
              token: Optional[str] = None, cache_dir: Optional[str] = None) -> str:
    """Download one scanned PDF and return its local (cached) path.

    doc: a pdf_ref string (loose or shard), a manifest row dict (pdf_ref / pdf_path [+ sha256]) or a law row dict.
    Loose PDFs come from the HF cache (hf_hub_download); shard members are fetched by HTTP Range and cached as
    <cache_dir or ~/.cache/world_law_pdfs>/<sha256>.pdf. verify=True re-hashes against the sha256."""
    import hashlib
    import os
    r = parse_pdf_ref_full(_ref_of(doc))
    repo = repo_id or r["repo"]
    want = (doc.get("sha256") if isinstance(doc, dict) else None) or r["sha256"]
    if r.get("member"):
        d = cache_dir or os.path.join(os.path.expanduser("~"), ".cache", "world_law_pdfs")
        os.makedirs(d, exist_ok=True)
        local = os.path.join(d, f"{want or r['path'].replace('/', '_') + '_' + str(r['offset'])}.pdf")
        if not os.path.exists(local):
            data = fetch_pdf_bytes(doc, repo_id=repo, token=token, revision=revision, verify=verify)
            tmp = local + f".{os.getpid()}.tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, local)
            return local
    else:
        from huggingface_hub import hf_hub_download
        local = hf_hub_download(repo, r["path"], repo_type="dataset", revision=revision, token=token)
    if verify and want:
        h = hashlib.sha256()
        with open(local, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != want:
            raise IOError(f"sha256 mismatch for {r['path']}: {h.hexdigest()} != {want}")
    return local


def iter_place_tables(countries=None, places=None, include_national: bool = False, include_us: bool = True,
                      max_places: Optional[int] = None) -> Iterator:
    """Yield (place_row, pyarrow.Table in the 35-column schema) per place."""
    import pyarrow.parquet as pq
    rows = _select(places_table(include_national).to_pylist(), countries, places)
    if not include_us:
        rows = [r for r in rows if r.get("has_local_data") is not False]
    rows = [r for r in rows if r.get("html_path") and (r.get("total_docs") or 0) > 0]
    for r in rows[:max_places] if max_places else rows:
        repo = r.get("source_repo") or MUNICIPAL
        for path in _files(r):
            t = pq.read_table(_dl(repo, path))
            if r.get("has_local_data") is False:
                yield r, _us_to_world(t, r)
            else:
                yield r, _to_world(t)


def load(countries=None, places=None, include_national: bool = False, include_us: bool = True,
         max_places: Optional[int] = None, columns: Optional[List[str]] = None):
    """Concatenate the selected places into one pyarrow Table (35 columns, or `columns`)."""
    import pyarrow as pa
    ts = [t if not columns else t.select(columns) for _, t in
          iter_place_tables(countries, places, include_national, include_us, max_places)]
    if not ts:
        s = world_schema()
        return s.empty_table() if not columns else s.empty_table().select(columns)
    return pa.concat_tables(ts)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--country", action="append")
    ap.add_argument("--place", action="append")
    ap.add_argument("--national", action="store_true")
    ap.add_argument("--max-places", type=int, default=3)
    ap.add_argument("--out", help="write the result to this parquet file")
    a = ap.parse_args()
    t = load(a.country, a.place, a.national, max_places=a.max_places)
    print(t.num_rows, "rows", t.num_columns, "columns")
    if a.out:
        import pyarrow.parquet as pq
        pq.write_table(t, a.out, compression="zstd")
