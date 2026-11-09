#!/usr/bin/env python3
"""Normalize DE-BW Gesetzblatt JSONL → endomorphosis/ipfs_germany_laws laws schema (append-only parquet).

Input default: /workspace/legal-corpora/de_laender_20261102/rows/DE-BW.jsonl
Output default: /workspace/staging/de_laender_append_20261105/data/laws_de_bw_20261105.parquet

Hard rules: no deletes; no HF push; streaming-friendly; CERT verify not involved (offline normalize).
"""
from __future__ import annotations
import argparse, json, hashlib, re
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

LAWS_COLS = [
    "id","title","text","source_url","source_type","jurisdiction","country","language","eli",
    "date","date_issued","retrieved_at","license","law_status","identifier","official_identifier",
    "article_count","json_path","metadata_json","version_date","supersedes","superseded_by",
    "is_current","effective_from",
]
LICENSE = (
    "Public domain (gemeinfrei): amtliche Werke i.S.d. § 5 Abs. 1 UrhG; "
    "Land Baden-Württemberg / baden-wuerttemberg.de (Gesetzblatt / GBl route)"
)
MONTHS = {
    "januar":1,"februar":2,"märz":3,"marz":3,"april":4,"mai":5,"juni":6,
    "juli":7,"august":8,"september":9,"oktober":10,"november":11,"dezember":12,
}

def sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()

def to_utc_z(ts: str | None) -> str | None:
    if not ts:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})([+-]\d{2})(\d{2})$", ts)
    if m:
        ts2 = f"{m.group(1)}{m.group(2)}:{m.group(3)}"
        return datetime.fromisoformat(ts2).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ts

def norm_id(raw_id: str | None, gbl: str | None) -> str:
    if raw_id and raw_id.startswith("DE-BW:"):
        rest = raw_id.split(":", 1)[1]
        slug = re.sub(r"[^A-Za-z0-9]+", "-", rest).strip("-").lower()
        return f"de-bw-{slug}"
    return f"de-bw-gbl-{(gbl or 'unknown').lower()}"

def guess_doc_type(title: str) -> str:
    t = (title or "").lower()
    if "gesetz" in t and "verordnung" not in t:
        return "statute"
    if "verordnung" in t:
        return "regulation"
    if "bekanntmachung" in t:
        return "notice"
    return "gazette_issue"

def parse_date(text: str, gbl: str | None):
    m = re.search(r"Ausgegeben[^,\n]*,[^,\n]*,\s*(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s+(\d{4})", text or "")
    if m:
        mon = MONTHS.get(m.group(2).lower())
        if mon:
            return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(1)):02d}", "parsed_from_gbl_header"
    if gbl and re.match(r"^\d{4}-", str(gbl)):
        return f"{str(gbl).split('-')[0]}-01-01", "year_from_gbl"
    return None, None

def normalize(src: Path):
    seen: OrderedDict[str, dict] = OrderedDict()
    raw_n = empty = dups = 0
    for line in open(src):
        raw_n += 1
        r = json.loads(line)
        if not (r.get("text") or "").strip() or not (r.get("title") or "").strip():
            empty += 1
            continue
        if r.get("jurisdiction") != "DE-BW":
            continue
        nid = norm_id(r.get("id"), r.get("gbl"))
        if nid in seen:
            dups += 1
            if len(r.get("text") or "") <= len(seen[nid].get("text") or ""):
                continue
        seen[nid] = r
    rows = []
    for nid, r in seen.items():
        text = r["text"]; title = (r.get("title") or "").strip()
        source_url = r.get("source_url") or ""; gbl = r.get("gbl")
        date, prec = parse_date(text, gbl)
        ident = f"bw-gbl:{gbl}" if gbl else nid
        meta = {
            "schema_version": "collection_record.v1",
            "record_type": "law",
            "law_identifier": ident,
            "document_type": guess_doc_type(title),
            "is_current": True,
            "canonical_law_url": source_url,
            "metadata": {
                "license": LICENSE,
                "retrieved_at": r.get("retrieved_at"),
                "publisher": "Land Baden-Württemberg / Staatsministerium",
                "source_name": "baden-wuerttemberg.de Gesetzblatt",
                "source_type_detail": "gazette_as_published",
                "consolidated": bool(r.get("consolidated")),
                "gbl": gbl,
                "pdf_url": r.get("pdf_url"),
                "pdf_sha256": r.get("pdf_sha256"),
                "page_hash": r.get("page_hash"),
                "pdf_hash_match": r.get("pdf_hash_match"),
                "host": r.get("host"),
                "robots_disallowed": bool(r.get("robots_disallowed")),
                "transport": r.get("transport") or "https",
                "text_sha256": sha256_text(text),
                "text_chars": len(text),
                "collector": "de_laender_collect_bwstream.py",
                "benjamin_route": "gazette (GBl) — no juris token minting",
                "date_precision": prec,
            },
        }
        rows.append({
            "id": nid, "title": title, "text": text, "source_url": source_url,
            "source_type": "bw_gesetzblatt", "jurisdiction": "DE-BW", "country": "Germany",
            "language": "de", "eli": None, "date": date, "date_issued": date,
            "retrieved_at": to_utc_z(r.get("retrieved_at")), "license": LICENSE,
            "law_status": "current", "identifier": ident,
            "official_identifier": f"GBl. {gbl}" if gbl else None,
            "article_count": 0, "json_path": None,
            "metadata_json": json.dumps(meta, ensure_ascii=False, separators=(",", ":")),
            "version_date": None, "supersedes": None, "superseded_by": None,
            "is_current": True, "effective_from": None,
        })
    return rows, {"raw": raw_n, "empty_or_no_title": empty, "dups_collapsed": dups, "final": len(rows)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=Path("/workspace/legal-corpora/de_laender_20261102/rows/DE-BW.jsonl"))
    ap.add_argument("--out-parquet", type=Path, default=Path("/workspace/staging/de_laender_append_20261105/data/laws_de_bw_20261105.parquet"))
    ap.add_argument("--out-jsonl", type=Path, default=None)
    args = ap.parse_args()
    rows, stats = normalize(args.src)
    args.out_parquet.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([(c, pa.bool_() if c == "is_current" else (pa.int64() if c == "article_count" else pa.string())) for c in LAWS_COLS])
    table = pa.table({c: pa.array([r[c] for r in rows], type=schema.field(c).type) for c in LAWS_COLS}, schema=schema)
    pq.write_table(table, args.out_parquet, compression="zstd")
    if args.out_jsonl:
        args.out_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out_jsonl, "w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"stats": stats, "out": str(args.out_parquet)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
