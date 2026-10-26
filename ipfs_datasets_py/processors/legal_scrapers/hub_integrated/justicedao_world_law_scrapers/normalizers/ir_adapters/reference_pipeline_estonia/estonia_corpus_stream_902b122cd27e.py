#!/usr/bin/env python3
"""Memsafe Estonia corpus build — no full entries list / no law row copies."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import gc, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MALLOC_TRIM_THRESHOLD_", "100000")
sys.path.insert(0, "/workspace/country-laws-ir")

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from country_laws_ir.build import CACHE, REPORTS, _log
from country_laws_ir.mem import mem_available_gib, rss_gib
from country_laws_ir.normalize import (
    _law_cid,
    SCHEMA_VERSION,
    _base_record,
    _parse_meta,
    _s,
    normalize_text,
)
from country_laws_ir import ENTRY_IDENTITY_SCHEMA, LAW_IDENTITY_SCHEMA

SLUG = "estonia"
TIP = "902b122cd27eed93e96c28a0ba5a70e9cb36ab7d"
TIP_SHORT = TIP[:12]
SRC = Path(f"/workspace/country-laws-ir/cache/{SLUG}_filtered_{TIP_SHORT}")
CORPUS_CKPT = CACHE / f"{SLUG}_corpus_{TIP_SHORT}.parquet"
PARTS = CACHE / f"{SLUG}_corpus_parts_{TIP_SHORT}"
LOG = Path(f"/workspace/country-laws-ir/reports/{SLUG}_corpus_stream_{TIP_SHORT}.log")
CHUNK = 20_000
SOURCE_DATASET = "endomorphosis/ipfs_estonia_laws"



def lean_law_map(laws: pd.DataFrame) -> dict:
    out = {}
    # columnar access
    ids = laws["id"].astype(str).map(_s)
    titles = laws["title"].astype(str).map(_s) if "title" in laws.columns else pd.Series([""]*len(laws))
    juris = (laws["jurisdiction"] if "jurisdiction" in laws.columns else laws.get("country", pd.Series([""]*len(laws)))).astype(str).map(_s)
    langs = laws["language"].astype(str).map(_s) if "language" in laws.columns else pd.Series([""]*len(laws))
    urls = laws["source_url"].astype(str).map(_s) if "source_url" in laws.columns else pd.Series([""]*len(laws))
    licenses = laws["license"].astype(str).map(_s) if "license" in laws.columns else pd.Series([""]*len(laws))
    elis = laws["eli"].astype(str).map(_s) if "eli" in laws.columns else pd.Series([""]*len(laws))
    idents = laws["identifier"].astype(str).map(_s) if "identifier" in laws.columns else ids
    offids = laws["official_identifier"].astype(str).map(_s) if "official_identifier" in laws.columns else pd.Series([""]*len(laws))
    stypes = laws["source_type"].astype(str).map(_s) if "source_type" in laws.columns else pd.Series([""]*len(laws))
    countries = laws["country"].astype(str).map(_s) if "country" in laws.columns else pd.Series([""]*len(laws))
    statuses = laws["law_status"].astype(str).map(_s) if "law_status" in laws.columns else pd.Series([""]*len(laws))
    retrieved = laws["retrieved_at"].astype(str).map(_s) if "retrieved_at" in laws.columns else pd.Series([""]*len(laws))
    date_iss = laws["date_issued"].astype(str).map(_s) if "date_issued" in laws.columns else pd.Series([""]*len(laws))
    dates = laws["date"].astype(str).map(_s) if "date" in laws.columns else pd.Series([""]*len(laws))
    metas = laws["metadata_json"].astype(str) if "metadata_json" in laws.columns else pd.Series([""]*len(laws))

    for i in range(len(laws)):
        iid = ids.iloc[i]
        title = titles.iloc[i]
        jur = juris.iloc[i]
        lang = langs.iloc[i]
        snap = ""
        for cand in (retrieved.iloc[i], date_iss.iloc[i], dates.iloc[i]):
            if cand and cand not in ("nan", "None"):
                snap = cand[:10] if len(cand) >= 10 and cand[4] == "-" else cand
                break
        out[iid] = {
            "instrument_title": title,
            "law_cid": _law_cid(iid, title, jur, lang, SOURCE_DATASET),
            "jurisdiction": jur,
            "language": lang,
            "source_url": urls.iloc[i] if urls.iloc[i] not in ("nan", "None") else "",
            "license": licenses.iloc[i] if licenses.iloc[i] not in ("nan", "None") else "",
            "eli": elis.iloc[i] if elis.iloc[i] not in ("nan", "None") else "",
            "identifier": idents.iloc[i] if idents.iloc[i] not in ("nan", "None") else iid,
            "official_identifier": offids.iloc[i] if offids.iloc[i] not in ("nan", "None") else "",
            "source_type": stypes.iloc[i] if stypes.iloc[i] not in ("nan", "None") else "",
            "country": countries.iloc[i] if countries.iloc[i] not in ("nan", "None") else "",
            "law_status": statuses.iloc[i] if statuses.iloc[i] not in ("nan", "None") else "",
            "snapshot_date": snap,
            "metadata": _parse_meta(metas.iloc[i] if metas.iloc[i] not in ("nan", "None") else ""),
        }
        if i and i % 20000 == 0:
            _log(f"law_map @{i} rss={rss_gib():.2f}G mem={mem_available_gib():.2f}G")
    return out


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    log_f = LOG.open("w", encoding="utf-8")

    class Tee:
        def write(self, d):
            sys.__stdout__.write(d); sys.__stdout__.flush()
            log_f.write(d); log_f.flush()
        def flush(self):
            sys.__stdout__.flush(); log_f.flush()

    sys.stdout = Tee(); sys.stderr = Tee()
    try:
        _log(f"corpus_stream start mem={mem_available_gib():.2f}G")
        laws_path = SRC / "data" / "laws.parquet"
        arts_path = SRC / "data" / "articles.parquet"
        # load laws lean cols only
        law_cols = [c for c in pq.read_schema(laws_path).names if c != "text"]
        laws = pd.read_parquet(laws_path, columns=law_cols)
        _log(f"laws loaded n={len(laws)} (no text) rss={rss_gib():.2f}G")
        law_map = lean_law_map(laws)
        n_laws = len(laws)
        del laws
        gc.collect()
        _log(f"law_map n={len(law_map)} rss={rss_gib():.2f}G mem={mem_available_gib():.2f}G")

        if PARTS.exists():
            import shutil
            shutil.rmtree(PARTS)
        PARTS.mkdir(parents=True)

        drops = {"empty_body": 0, "missing_instrument": 0, "duplicate_cid": 0}
        seen: set[str] = set()
        part_i = 0
        buf: list[dict] = []
        n_out = 0
        # read articles in row groups / batches
        pf = pq.ParquetFile(arts_path)
        batch_rows = 0
        for batch in pf.iter_batches(batch_size=CHUNK, columns=["law_id", "id", "title", "text", "source_url", "article_number", "metadata_json"]):
            df = batch.to_pandas()
            for row in df.itertuples(index=False):
                source_id = _s(getattr(row, "id", ""))
                instrument_id = _s(getattr(row, "law_id", ""))
                body = _s(getattr(row, "text", ""))
                article_title = _s(getattr(row, "title", ""))
                article_number = _s(getattr(row, "article_number", ""))
                if not body:
                    drops["empty_body"] += 1
                    continue
                parent = law_map.get(instrument_id)
                if not parent:
                    drops["missing_instrument"] += 1
                    continue
                art_meta = _parse_meta(_s(getattr(row, "metadata_json", "") or ""))
                merged_meta = {**parent["metadata"], **art_meta}
                src_url = _s(getattr(row, "source_url", "")) or parent["source_url"]
                rec = _base_record(
                    record_type="article",
                    source_dataset=SOURCE_DATASET,
                    source_revision=TIP,
                    instrument_id=instrument_id,
                    instrument_title=parent["instrument_title"],
                    law_cid=parent["law_cid"],
                    article_number=article_number,
                    article_title=article_title,
                    body=body,
                    jurisdiction=parent["jurisdiction"],
                    language=parent["language"],
                    source_url=src_url,
                    snapshot_date=parent["snapshot_date"],
                    coverage="article-level",
                    license_expr=parent["license"],
                    collector=f"endomorphosis/ipfs_datasets_py ({SOURCE_DATASET})",
                    source_id=source_id,
                    extra={
                        "eli": parent["eli"],
                        "identifier": parent["identifier"],
                        "official_identifier": parent["official_identifier"],
                        "source_type": parent["source_type"],
                        "country": parent["country"],
                        "law_status": parent["law_status"],
                        "parent_law_id": instrument_id,
                        "article_id": source_id,
                    },
                )
                cid = rec["entry_cid"]
                if cid in seen:
                    drops["duplicate_cid"] += 1
                    continue
                seen.add(cid)
                buf.append(rec)
            batch_rows += len(df)
            del df
            if len(buf) >= CHUNK:
                # sort buffer locally then assign provisional; final reindex after concat
                part = pd.DataFrame(buf)
                part = part.sort_values(["instrument_id", "article_number", "source_id"]).reset_index(drop=True)
                outp = PARTS / f"part-{part_i:05d}.parquet"
                part.to_parquet(outp, index=False)
                n_out += len(part)
                _log(f"part {part_i} rows={len(part)} total={n_out} rss={rss_gib():.2f}G mem={mem_available_gib():.2f}G")
                part_i += 1
                buf.clear()
                gc.collect()
            if batch_rows % 100000 == 0:
                _log(f"articles scanned={batch_rows} n_out={n_out} rss={rss_gib():.2f}G")

        if buf:
            part = pd.DataFrame(buf)
            part = part.sort_values(["instrument_id", "article_number", "source_id"]).reset_index(drop=True)
            outp = PARTS / f"part-{part_i:05d}.parquet"
            part.to_parquet(outp, index=False)
            n_out += len(part)
            part_i += 1
            buf.clear()
            gc.collect()

        del law_map, seen
        gc.collect()
        _log(f"parts done n_parts={part_i} n_out={n_out} rss={rss_gib():.2f}G")

        # concat + global sort + document_index
        files = sorted(PARTS.glob("part-*.parquet"))
        tables = [pq.read_table(f) for f in files]
        table = pa.concat_tables(tables)
        del tables
        gc.collect()
        corpus = table.to_pandas()
        del table
        gc.collect()
        corpus = corpus.sort_values(["instrument_id", "article_number", "source_id"]).reset_index(drop=True)
        corpus["document_index"] = np.arange(len(corpus), dtype=np.int64)
        corpus["corpus_index"] = corpus["document_index"]
        CORPUS_CKPT.parent.mkdir(parents=True, exist_ok=True)
        corpus.to_parquet(CORPUS_CKPT, index=False)
        n = len(corpus)
        _log(f"corpus written n={n} path={CORPUS_CKPT} rss={rss_gib():.2f}G")

        report = {
            "source_dataset": SOURCE_DATASET,
            "source_revision": TIP,
            "n_laws_in": n_laws,
            "n_articles_in": int(pq.ParquetFile(arts_path).metadata.num_rows),
            "unit": "article",
            "drops": drops,
            "n_out": n,
            "n_dropped_total": sum(drops.values()),
            "via": "estonia_corpus_stream",
            "record_type_breakdown": {str(k): int(v) for k, v in corpus["record_type"].value_counts().items()},
            "language_breakdown": {str(k): int(v) for k, v in corpus["language"].fillna("").value_counts().items()},
            "never_invented_legal_text": True,
        }
        del corpus
        gc.collect()
        (REPORTS / f"{SLUG}_normalization.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        (REPORTS / f"{SLUG}_corpus_stream_{TIP_SHORT}_result.json").write_text(
            json.dumps({"n": n, "drops": drops, "corpus": str(CORPUS_CKPT), "finished_utc": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n"
        )
        print(json.dumps({"ok": True, "n": n, "drops": drops}, indent=2))
        return 0
    finally:
        try:
            log_f.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
