"""Pinned Arrow schemas + cast/validate helpers for the world-laws datasets.

Two layers are pinned here:

1. RAW layer, ``endomorphosis/ipfs_<slug>_laws``
   ``data/laws*.parquet``     -> RAW_LAWS_SCHEMA     (19 columns)
   ``data/articles*.parquet`` -> RAW_ARTICLES_SCHEMA (9 columns)
2. NORMALIZED layer, ``justicedao/ipfs_<slug>_laws_ir``
   ``data/corpus/part-*.parquet`` -> IR_CORPUS_SCHEMA (49 columns,
   ``country-laws-ir-graphrag/v1``, country_laws_ir v0.5.0)

Pinning rules (raw layer; see SCHEMA.md for the rationale):
  * every text column is ``pa.string()`` (never large_string, never null-typed);
  * ``article_count`` is ``pa.int64()``;
  * exactly the canonical columns, in canonical order;
  * municipal / per-country extra columns are folded into the
    ``metadata_json`` string as ``{"extras": {...}}`` instead of widening the
    table; ``municipality_qid`` is renamed to ``wikidata_qid`` on the way;
  * required identity columns (laws: id,title,text; articles: id,law_id,title,
    text) are never invented: a null/empty id fails validation.

Usage (streaming, constant memory):

    import pyarrow.parquet as pq
    from schema import RAW_LAWS_SCHEMA, cast_batch, validate_table
    pf = pq.ParquetFile("data/laws.parquet")
    with pq.ParquetWriter("out/laws.parquet", RAW_LAWS_SCHEMA, compression="zstd") as w:
        for b in pf.iter_batches(batch_size=2048):
            w.write_batch(cast_batch(b, "laws"))
"""

from __future__ import annotations

import json
from typing import Iterable, Iterator, Literal

import pyarrow as pa

SCHEMA_DOC_VERSION = "world-laws-raw/v1"

Kind = Literal["laws", "articles"]

RAW_LAWS_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string(), nullable=False),
        pa.field("title", pa.string()),
        pa.field("text", pa.string()),
        pa.field("source_url", pa.string()),
        pa.field("source_type", pa.string()),
        pa.field("jurisdiction", pa.string()),
        pa.field("country", pa.string()),
        pa.field("language", pa.string()),
        pa.field("eli", pa.string()),
        pa.field("date", pa.string()),
        pa.field("date_issued", pa.string()),
        pa.field("retrieved_at", pa.string()),
        pa.field("license", pa.string()),
        pa.field("law_status", pa.string()),
        pa.field("identifier", pa.string()),
        pa.field("official_identifier", pa.string()),
        pa.field("article_count", pa.int64()),
        pa.field("json_path", pa.string()),
        pa.field("metadata_json", pa.string()),
    ],
    metadata={b"schema_doc_version": SCHEMA_DOC_VERSION.encode(), b"layer": b"raw_laws"},
)

RAW_ARTICLES_SCHEMA = pa.schema(
    [
        pa.field("law_id", pa.string(), nullable=False),
        pa.field("id", pa.string(), nullable=False),
        pa.field("title", pa.string()),
        pa.field("text", pa.string()),
        pa.field("source_url", pa.string()),
        pa.field("document_number", pa.string()),
        pa.field("article_number", pa.string()),
        pa.field("record_type", pa.string()),
        pa.field("metadata_json", pa.string()),
    ],
    metadata={b"schema_doc_version": SCHEMA_DOC_VERSION.encode(), b"layer": b"raw_articles"},
)

RAW_SCHEMAS = {"laws": RAW_LAWS_SCHEMA, "articles": RAW_ARTICLES_SCHEMA}
REQUIRED = {
    "laws": ("id", "title", "text"),
    "articles": ("id", "law_id", "title", "text"),
}
# Column aliases seen in the wild -> canonical name (applied before extras folding).
ALIASES = {"municipality_qid": "wikidata_qid"}

# ---------------------------------------------------------------------------
# Normalized layer (justicedao/ipfs_<slug>_laws_ir  data/corpus/part-*.parquet)
# ---------------------------------------------------------------------------
IR_SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
_S = pa.string()
IR_CORPUS_SCHEMA = pa.schema(
    [
        ("record_type", _S), ("source_dataset", _S), ("source_revision", _S),
        ("source_id", _S), ("instrument_id", _S), ("instrument_title", _S),
        ("law_id", _S), ("law_cid", _S), ("article_number", _S), ("article_title", _S),
        ("title", _S), ("body", _S), ("body_sha256", _S), ("jurisdiction", _S),
        ("language", _S), ("source_url", _S), ("snapshot_date", _S), ("coverage", _S),
        ("license", _S), ("collector", _S), ("schema_version", _S),
        ("entry_identity_schema_version", _S), ("eli", _S), ("identifier", _S),
        ("official_identifier", _S), ("source_type", _S), ("country", _S),
        ("law_status", _S), ("parent_law_id", _S), ("article_id", _S),
        ("reconstructed_from_articles", pa.bool_()), ("hierarchy_kind", _S),
        ("hierarchy_path", _S), ("title_number", _S), ("chapter_number", _S),
        ("part_number", _S), ("section_number", _S),
        ("subsections", pa.list_(pa.string())),
        ("official_citation", _S), ("bluebook_citation", _S), ("cite_key", _S),
        ("citation_status", _S), ("pinpoint", _S), ("entry_cid", _S),
        ("title_length", pa.int64()), ("body_length", pa.int64()),
        ("document_length", pa.int64()), ("document_index", pa.int64()),
        ("corpus_index", pa.int64()),
    ],
    metadata={b"schema_version": IR_SCHEMA_VERSION.encode(), b"layer": b"ir_corpus"},
)
IR_OPTIONAL_COLUMNS = {
    # present only in 3 repos built with the reconstruction pass (54-column variant)
    "reconstruction_truncated": pa.bool_(),
    "reconstruction_gap_note": pa.string(),
    "reconstruction_article_count": pa.float64(),
    "reconstruction_article_ids": pa.list_(pa.string()),
    "reconstruction_article_sha256": pa.list_(pa.string()),
    # legacy 37-col builds only
    "orphan_parent": None,
}
IR_REQUIRED = ("record_type", "source_id", "law_id", "entry_cid", "body", "body_sha256", "schema_version")


class SchemaError(ValueError):
    pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _py(v):
    # keep JSON-able extras (dates -> iso strings, bytes -> repr)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


def _merge_extras(meta_value, extras: dict) -> str:
    """Return metadata_json string with ``extras`` merged under key "extras"."""
    if not extras:
        return meta_value if isinstance(meta_value, str) else "{}"
    base: dict
    if isinstance(meta_value, str) and meta_value.strip():
        try:
            parsed = json.loads(meta_value)
            base = parsed if isinstance(parsed, dict) else {"_orig_metadata": parsed}
        except Exception:
            base = {"_orig_metadata_raw": meta_value}
    else:
        base = {}
    prior = base.get("extras")
    if isinstance(prior, dict):
        merged = dict(extras)
        merged.update(prior)  # existing explicit extras win
        extras = merged
    base["extras"] = extras
    return json.dumps(base, ensure_ascii=False, sort_keys=True)


def cast_batch(batch: "pa.RecordBatch | pa.Table", kind: Kind) -> pa.Table:
    """Cast one batch/table to the pinned raw schema.

    * drops nothing silently: unknown columns are folded into metadata_json["extras"];
    * adds missing optional columns as nulls (missing REQUIRED columns raise);
    * normalizes string/large_string/null/int32 drift.
    Returns a ``pa.Table`` (one chunk per column) whose schema equals the pinned schema.
    """
    target = RAW_SCHEMAS[kind]
    tbl = pa.Table.from_batches([batch]) if isinstance(batch, pa.RecordBatch) else batch
    names = list(tbl.column_names)
    # 1) aliases
    ren = [ALIASES[n] if (n in ALIASES and ALIASES[n] not in names) else n for n in names]
    if ren != names:
        tbl = tbl.rename_columns(ren)
        names = ren
    missing_req = [c for c in REQUIRED[kind] if c not in names]
    if missing_req:
        raise SchemaError(f"{kind}: missing required columns {missing_req}; present={names}")
    # 2) fold extras
    extra_cols = [n for n in names if n not in target.names]
    meta_col = tbl.column("metadata_json").to_pylist() if "metadata_json" in names else [None] * tbl.num_rows
    if extra_cols:
        ex_vals = {n: tbl.column(n).to_pylist() for n in extra_cols}
        new_meta = []
        for i in range(tbl.num_rows):
            ex = {n: _py(ex_vals[n][i]) for n in extra_cols if ex_vals[n][i] is not None and ex_vals[n][i] != ""}
            new_meta.append(_merge_extras(meta_col[i], ex))
        meta_arr = pa.array(new_meta, type=pa.string())
    else:
        meta_arr = None
    # 3) build pinned columns
    cols = []
    for f in target:
        if f.name == "metadata_json" and meta_arr is not None:
            cols.append(meta_arr)
        elif f.name in names:
            col = tbl.column(f.name)
            if pa.types.is_null(col.type):
                col = pa.nulls(len(col), type=f.type)
            else:
                col = col.cast(f.type, safe=True)
            cols.append(col)
        else:
            cols.append(pa.nulls(tbl.num_rows, type=f.type))
    out = pa.Table.from_arrays([c.combine_chunks() if isinstance(c, pa.ChunkedArray) else c for c in cols],
                               schema=target.remove_metadata())
    return out.replace_schema_metadata(target.metadata)


def cast_table(tbl: pa.Table, kind: Kind, batch_rows: int = 4096) -> pa.Table:
    """Convenience for small tables; use cast_batch + ParquetWriter for big ones."""
    parts = [cast_batch(b, kind) for b in tbl.to_batches(max_chunksize=batch_rows)]
    return pa.concat_tables(parts) if parts else RAW_SCHEMAS[kind].empty_table()


def iter_cast_parquet(path: str, kind: Kind, batch_rows: int = 2048) -> Iterator[pa.Table]:
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    for b in pf.iter_batches(batch_size=batch_rows):
        yield cast_batch(b, kind)


def schema_matches(schema: pa.Schema, kind: Kind) -> bool:
    t = RAW_SCHEMAS[kind]
    return schema.names == t.names and all(a.type == b.type for a, b in zip(schema, t))


def validate_table(tbl: "pa.Table | pa.RecordBatch", kind: Kind, *, strict_types: bool = True) -> list[str]:
    """Return a list of problems (empty == valid). Does not mutate."""
    problems: list[str] = []
    t = RAW_SCHEMAS[kind]
    names = tbl.schema.names
    if names != t.names:
        problems.append(f"column set/order differs: extra={[n for n in names if n not in t.names]} "
                        f"missing={[n for n in t.names if n not in names]}")
    if strict_types:
        for f in tbl.schema:
            if f.name in t.names and f.type != t.field(f.name).type:
                problems.append(f"dtype {f.name}: {f.type} != pinned {t.field(f.name).type}")
    ids = tbl.column("id") if "id" in names else None
    if ids is not None:
        nulls = ids.null_count
        pylist = ids.to_pylist() if nulls == 0 else []
        empties = sum(1 for x in pylist if not str(x).strip())
        if nulls or empties:
            problems.append(f"id: {nulls} null, {empties} empty")
    if kind == "articles" and "law_id" in names:
        c = tbl.column("law_id")
        if c.null_count or any(not str(x).strip() for x in c.to_pylist()):
            problems.append("law_id: null/empty values")
    return problems


def validate_ir_schema(schema: pa.Schema) -> list[str]:
    """Check an IR corpus parquet schema against IR_CORPUS_SCHEMA (older builds have fewer columns)."""
    problems = []
    for n in IR_REQUIRED:
        if n not in schema.names:
            problems.append(f"IR missing required column {n}")
    stale = [n for n in IR_CORPUS_SCHEMA.names if n not in schema.names]
    if stale:
        problems.append(f"IR older build: lacks {len(stale)} current columns (rebuild with country_laws_ir v0.5.0): {stale}")
    for f in schema:
        if f.name in IR_CORPUS_SCHEMA.names:
            want = IR_CORPUS_SCHEMA.field(f.name).type
            got = f.type
            if got != want and not (pa.types.is_large_string(got) and want == pa.string()):
                problems.append(f"IR dtype {f.name}: {got} != {want}")
    unknown = [n for n in schema.names if n not in IR_CORPUS_SCHEMA.names and n not in IR_OPTIONAL_COLUMNS]
    if unknown:
        problems.append(f"IR unknown columns {unknown}")
    return problems



# ---------------------------------------------------------------------------
# Municipal / sub-national variant  (world-laws-municipal/v1)
# ---------------------------------------------------------------------------
MUNICIPAL_SCHEMA_VERSION = "world-laws-municipal/v1"
JURISDICTION_LEVELS = ("national", "state", "regional", "municipal", "local")
# nominal OSM-style admin levels used when the collector does not know better
DEFAULT_ADMIN_LEVEL = {"national": 2, "state": 4, "regional": 6, "municipal": 8, "local": 10}
MUNICIPAL_EXTRA_FIELDS = [
    pa.field("jurisdiction_level", pa.string(), nullable=False),
    pa.field("admin_level", pa.int64()),
    pa.field("country_iso", pa.string(), nullable=False),
    pa.field("admin1", pa.string()),
    pa.field("municipality", pa.string()),
    pa.field("municipality_code", pa.string()),
    pa.field("source_body", pa.string()),
]
MUNICIPAL_LAWS_SCHEMA = pa.schema(
    list(RAW_LAWS_SCHEMA) + MUNICIPAL_EXTRA_FIELDS,
    metadata={b"schema_doc_version": MUNICIPAL_SCHEMA_VERSION.encode(), b"layer": b"raw_municipal_laws"},
)
MUNICIPAL_ARTICLES_SCHEMA = RAW_ARTICLES_SCHEMA  # articles join to laws via law_id; unchanged
# legacy column / metadata_json.extras key -> new first-class column (first non-empty wins)
MUNICIPAL_PROMOTIONS = {
    "municipality": ("municipality", "municipality_name", "municipality_name_en", "municipality_name_fr", "municipality_name_sw"),
    "municipality_code": ("municipality_code", "municipality_id", "wikidata_qid", "municipality_qid"),
    "admin1": ("admin1", "province", "region", "state"),
    "source_body": ("source_body", "issuer", "issuer_organ", "council_normalized", "council"),
    "jurisdiction_level": ("jurisdiction_level",),
    "admin_level": ("admin_level",),
    "country_iso": ("country_iso",),
}


import re as _re_mod
_ISO_PREFIX = _re_mod.compile(r"^([A-Z]{2})(?:$|[-/_ ])")
_ISO_SUBDIV = _re_mod.compile(r"^[A-Z]{2}-[A-Z0-9]{1,3}$")


def _extras_of(meta) -> dict:
    if not isinstance(meta, str) or not meta.strip():
        return {}
    try:
        d = json.loads(meta)
    except Exception:
        return {}
    if not isinstance(d, dict):
        return {}
    ex = d.get("extras")
    return {**d, **ex} if isinstance(ex, dict) else d


def cast_municipal_batch(batch: "pa.RecordBatch | pa.Table", *, default_level: str = "municipal",
                         country_iso: str | None = None) -> pa.Table:
    """Cast a raw municipal batch (legacy wide columns OR already-folded extras) to MUNICIPAL_LAWS_SCHEMA.

    Promotion order per new column: an existing column of that name, then the legacy aliases in
    MUNICIPAL_PROMOTIONS (as columns, then as metadata_json extras keys). Legacy columns stay preserved in
    metadata_json.extras (nothing dropped). country_iso falls back to ``jurisdiction`` (2 letters) or the arg;
    admin_level falls back to DEFAULT_ADMIN_LEVEL[jurisdiction_level].
    """
    tbl = pa.Table.from_batches([batch]) if isinstance(batch, pa.RecordBatch) else batch
    names = set(tbl.column_names)
    raw = {n: tbl.column(n).to_pylist() for n in names if any(n in v for v in MUNICIPAL_PROMOTIONS.values())}
    metas = tbl.column("metadata_json").to_pylist() if "metadata_json" in names else [None] * tbl.num_rows
    juris = tbl.column("jurisdiction").to_pylist() if "jurisdiction" in names else [None] * tbl.num_rows
    countries = tbl.column("country").to_pylist() if "country" in names else [None] * tbl.num_rows
    new_names = {f.name for f in MUNICIPAL_EXTRA_FIELDS}
    core = cast_batch(tbl.drop([n for n in tbl.column_names if n in new_names]), "laws")
    out = {k: [] for k in new_names}
    for i in range(tbl.num_rows):
        ex = _extras_of(metas[i])
        for col, aliases in MUNICIPAL_PROMOTIONS.items():
            val = None
            for a in aliases:
                v = raw[a][i] if a in raw else ex.get(a)
                if v is not None and str(v).strip() != "":
                    val = v
                    break
            out[col].append(val)
        j = juris[i] if isinstance(juris[i], str) else ""
        lvl = out["jurisdiction_level"][i]
        if not lvl:
            lvl = "national" if j.lower().endswith("-national") else default_level
        lvl = str(lvl).lower()
        out["jurisdiction_level"][i] = lvl
        try:
            out["admin_level"][i] = int(out["admin_level"][i])
        except (TypeError, ValueError):  # missing or a word such as "county" (kept in extras)
            out["admin_level"][i] = DEFAULT_ADMIN_LEVEL.get(lvl)
        m_iso = _ISO_PREFIX.match(j)
        ctry = countries[i] if isinstance(countries[i], str) and len(countries[i]) == 2 else None
        iso = out["country_iso"][i] or country_iso or (m_iso.group(1) if m_iso else None) or ctry
        out["country_iso"][i] = iso.upper() if isinstance(iso, str) else iso
        if not out["admin1"][i]:
            m_sub = _ISO_SUBDIV.match(j)
            if m_sub and not j.lower().endswith("-national"):
                out["admin1"][i] = m_sub.group(0)  # ISO 3166-2 style code, e.g. AT-2, ET-AA
        for c in ("municipality", "municipality_code", "admin1", "source_body"):
            if out[c][i] is not None:
                out[c][i] = str(out[c][i])
    for f in MUNICIPAL_EXTRA_FIELDS:
        core = core.append_column(f.name, pa.array(out[f.name], type=f.type))
    return core.replace_schema_metadata(MUNICIPAL_LAWS_SCHEMA.metadata)


def validate_municipal_table(tbl: "pa.Table", *, strict_types: bool = True) -> list[str]:
    problems: list[str] = []
    t = MUNICIPAL_LAWS_SCHEMA
    if tbl.schema.names != t.names:
        problems.append(f"column set/order differs: extra={[n for n in tbl.schema.names if n not in t.names]} "
                        f"missing={[n for n in t.names if n not in tbl.schema.names]}")
        return problems
    if strict_types:
        for f in tbl.schema:
            if f.type != t.field(f.name).type:
                problems.append(f"dtype {f.name}: {f.type} != pinned {t.field(f.name).type}")
    problems += validate_table(tbl.select(RAW_LAWS_SCHEMA.names), "laws", strict_types=strict_types)
    lv = tbl.column("jurisdiction_level").to_pylist()
    bad = sorted({x for x in lv if x not in JURISDICTION_LEVELS})
    if bad:
        problems.append(f"jurisdiction_level not in {JURISDICTION_LEVELS}: {bad[:5]}")
    iso = tbl.column("country_iso").to_pylist()
    nbad = sum(1 for x in iso if not (isinstance(x, str) and len(x) == 2 and x.isupper()))
    if nbad:
        problems.append(f"country_iso missing/not ISO-3166 alpha-2 in {nbad} rows")
    mun = tbl.column("municipality").to_pylist(); code = tbl.column("municipality_code").to_pylist()
    nmun = sum(1 for l, m, c in zip(lv, mun, code) if l in ("municipal", "local") and not m and not c)
    if nmun:
        problems.append(f"{nmun} municipal/local rows have neither municipality nor municipality_code")
    return problems


def municipal_law_id(country_iso: str, municipality_code: str, native_id: str) -> str:
    """Dedup id rule: <cc>-mun-<municipality_code>-<native id slug> (lowercase, [a-z0-9._-])."""
    import re as _re

    def slug(x: str) -> str:
        return _re.sub(r"[^a-z0-9._-]+", "-", str(x).strip().lower()).strip("-")

    return f"{slug(country_iso)}-mun-{slug(municipality_code)}-{slug(native_id)}"


if __name__ == "__main__":  # smoke test
    import sys

    t = pa.table({"id": ["a"], "title": ["T"], "text": ["x"], "article_count": pa.array([3], pa.int32()),
                  "eli": pa.nulls(1), "municipality_qid": ["Q1"], "municipality_name": ["Foo"],
                  "metadata_json": ['{"k": 1}']}, )
    out = cast_table(t, "laws")
    assert schema_matches(out.schema, "laws"), out.schema
    assert not validate_table(out, "laws"), validate_table(out, "laws")
    print(out.to_pylist()[0]["metadata_json"])
    # municipal smoke test: legacy wide columns
    m = pa.table({"id": ["ke-1"], "title": ["By-law"], "text": ["body text"], "jurisdiction": ["KE"],
                  "municipality_id": ["nairobi"], "municipality_name": ["Nairobi"], "wikidata_qid": ["Q3870"],
                  "council": ["Nairobi City County"], "article_count": pa.array([2], pa.int32())})
    mo = cast_municipal_batch(m)
    assert not validate_municipal_table(mo), validate_municipal_table(mo)
    r = mo.to_pylist()[0]
    assert (r["municipality"], r["municipality_code"], r["source_body"], r["country_iso"], r["admin_level"]) == \
        ("Nairobi", "nairobi", "Nairobi City County", "KE", 8), r
    # already-folded extras (pinned raw rows) promote too
    mo2 = cast_municipal_batch(cast_table(m, "laws"))
    assert mo2.to_pylist()[0]["municipality"] == "Nairobi"
    assert municipal_law_id("KE", "Nairobi", "By-law 12/2020") == "ke-mun-nairobi-by-law-12-2020"
    print("municipal ok")
    print("ok")
    sys.exit(0)
