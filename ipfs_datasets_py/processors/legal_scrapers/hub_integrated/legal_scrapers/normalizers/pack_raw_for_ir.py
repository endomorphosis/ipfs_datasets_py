#!/usr/bin/env python3
"""Merge a (possibly sharded) raw ``endomorphosis/ipfs_<slug>_laws`` repo into ONE pinned-schema local pack.

Why: ``country_laws_ir.normalize.load_source`` only reads ``data/laws.parquet`` / ``data/articles.parquet``;
sharded repos (``data/laws-00001.parquet`` ...) therefore could not be normalized (this is why the municipal
sets had no ``justicedao/ipfs_<slug>_laws_ir``). This script streams every shard in batches through
``schema.cast_batch`` (pinned string/int64 schema, municipal extras folded into metadata_json) and writes

    <out>/data/laws.parquet, <out>/data/articles.parquet, <out>/pack_meta.json

which ``python -m country_laws_ir build --source-repo <out>`` accepts as a local pack.
Duplicate law ids across shards keep the FIRST occurrence (counted in pack_meta.json). Nothing is written to the Hub.

    python pack_raw_for_ir.py endomorphosis/ipfs_namibia_municipal_laws --out /tmp/packs/namibia_municipal
"""
from __future__ import annotations
import argparse, json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
import pyarrow as pa
import pyarrow.parquet as pq
from schema import RAW_ARTICLES_SCHEMA, RAW_LAWS_SCHEMA, cast_batch, validate_table

SHARD_RE = {"laws": re.compile(r"^data/laws(?:-[\w-]+)?\.parquet$"), "articles": re.compile(r"^data/articles(?:-[\w-]+)?\.parquet$")}


def pack(repo_id: str, out: Path, batch_rows: int = 1024, token: str | None = None) -> dict:
    from huggingface_hub import HfApi, hf_hub_download

    token = token or os.environ.get("HF_TOKEN")
    api = HfApi(token=token)
    info = api.dataset_info(repo_id)
    slug = repo_id.split("/")[-1].removeprefix("ipfs_").removesuffix("_laws")
    (out / "data").mkdir(parents=True, exist_ok=True)
    meta = {"slug": slug, "repo": repo_id, "source_dataset": repo_id, "source_revision": info.sha,
            "name": slug.replace("_", " ").title(), "indexable": True, "n": {}}
    for kind, schema in (("laws", RAW_LAWS_SCHEMA), ("articles", RAW_ARTICLES_SCHEMA)):
        files = sorted(s.rfilename for s in info.siblings if SHARD_RE[kind].match(s.rfilename))
        if not files:
            continue
        seen: set[str] = set()
        n = dup = 0
        with pq.ParquetWriter(out / "data" / f"{kind}.parquet", schema, compression="zstd") as w:
            for fn in files:
                p = hf_hub_download(repo_id, fn, repo_type="dataset", revision=info.sha, token=token,
                                    local_dir=str(out / "_shards"))
                for b in pq.ParquetFile(p).iter_batches(batch_size=batch_rows):
                    t = cast_batch(b, kind)
                    if kind == "laws":  # laws ids must be unique; article ids legitimately repeat in some packs
                        ids = t.column("id").to_pylist()
                        keep = []
                        for i, x in enumerate(ids):
                            if x in seen:
                                dup += 1
                            else:
                                seen.add(x); keep.append(i)
                        if len(keep) != len(ids):
                            t = t.take(pa.array(keep))
                    bad = validate_table(t, kind)
                    if bad:
                        raise SystemExit(f"{repo_id} {fn}: {bad}")
                    n += t.num_rows
                    w.write_table(t)
                os.remove(p)
        meta["n"][kind] = {"rows": n, "shards": len(files), "dup_ids_dropped": dup}
    shutil_rm = out / "_shards"
    import shutil
    shutil.rmtree(shutil_rm, ignore_errors=True)
    (out / "pack_meta.json").write_text(json.dumps(meta, indent=2))
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo_id")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    print(json.dumps(pack(a.repo_id, Path(a.out)), indent=2))
