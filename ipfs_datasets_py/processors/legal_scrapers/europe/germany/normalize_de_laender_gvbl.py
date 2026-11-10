#!/usr/bin/env python3
"""Normalize DE-* GVBl gazette JSONL rows → hub laws schema parquet (append-only files).

Reads /workspace/legal-corpora/de_laender_gvbl_20261105/rows/DE-<LAND>.jsonl
Writes /workspace/staging/de_laender_append_20261105/data/laws_de_<land>_20261105.parquet
No deletes; no HF push.
"""
from __future__ import annotations
import argparse, json, hashlib, re, os
from collections import OrderedDict, Counter
from datetime import datetime, timezone
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

os.environ.setdefault("MALLOC_ARENA_MAX", "2")

LAWS_COLS = [
    "id","title","text","source_url","source_type","jurisdiction","country","language","eli",
    "date","date_issued","retrieved_at","license","law_status","identifier","official_identifier",
    "article_count","json_path","metadata_json","version_date","supersedes","superseded_by",
    "is_current","effective_from",
]

LICENSE = {
    "NI": "Public domain (gemeinfrei): amtliche Werke i.S.d. § 5 Abs. 1 UrhG; Niedersächsische Staatskanzlei / verkuendung-niedersachsen.de (Nds. GVBl.)",
    "BE": "Public domain (gemeinfrei): amtliche Werke i.S.d. § 5 Abs. 1 UrhG; Land Berlin / berlin.de SenJust (GVBl.)",
    "HH": "Public domain (gemeinfrei): amtliche Werke i.S.d. § 5 Abs. 1 UrhG; Freie und Hansestadt Hamburg / luewu.de (HmbGVBl.)",
    "BW": "Public domain (gemeinfrei): amtliche Werke i.S.d. § 5 Abs. 1 UrhG; Land Baden-Württemberg / baden-wuerttemberg.de (Gesetzblatt / GBl route)",
}
PUBLISHER = {
    "NI": "Niedersächsische Staatskanzlei",
    "BE": "Senatsverwaltung für Justiz Berlin",
    "HH": "Freie und Hansestadt Hamburg (HmbGVBl via Lütcke & Wulff)",
    "BW": "Land Baden-Württemberg / Staatsministerium",
}
SOURCE_TYPE = {
    "NI": "nds_gvbl",
    "BE": "berlin_gvbl",
    "HH": "hmb_gvbl",
    "BW": "bw_gesetzblatt",
}

def sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode()).hexdigest()

def to_utc_z(ts: str | None):
    if not ts: return None
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})([+-]\d{2}):?(\d{2})$", ts)
    if m:
        ts2 = f"{m.group(1)}{m.group(2)}:{m.group(3)}"
        return datetime.fromisoformat(ts2).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if ts.endswith("Z"): return ts
    return ts

def norm_id(land: str, raw_id: str, gbl: str) -> str:
    if raw_id and raw_id.startswith(f"DE-{land}:"):
        rest = raw_id.split(":",1)[1]
        slug = re.sub(r"[^A-Za-z0-9]+","-", rest).strip("-").lower()
        return f"de-{land.lower()}-{slug}"
    return f"de-{land.lower()}-gvbl-{(gbl or 'unknown').lower()}"

def normalize_land(land: str, src: Path):
    seen = OrderedDict()
    raw_n = empty = dups = 0
    for line in open(src):
        raw_n += 1
        r = json.loads(line)
        if r.get("jurisdiction") != f"DE-{land}":
            continue
        if not (r.get("text") or "").strip() or not (r.get("title") or "").strip():
            empty += 1
            continue
        nid = norm_id(land, r.get("id"), r.get("gbl"))
        if nid in seen:
            dups += 1
            if len(r.get("text") or "") <= len(seen[nid].get("text") or ""):
                continue
        seen[nid] = r
    rows = []
    lic = LICENSE.get(land, LICENSE["NI"])
    for nid, r in seen.items():
        text = r["text"]; title = (r.get("title") or "").strip()
        source_url = r.get("source_url") or ""
        gbl = r.get("gbl")
        date = None
        # HH title has vom DD.MM.YYYY
        m = re.search(r"vom\s+(\d{2})\.(\d{2})\.(\d{4})", title)
        if m:
            date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        elif gbl and re.match(r"^\d{4}-", str(gbl)):
            date = f"{str(gbl).split('-')[0]}-01-01"
        ident = f"{land.lower()}-gvbl:{gbl}" if gbl else nid
        meta = {
            "schema_version": "collection_record.v1",
            "record_type": "law",
            "law_identifier": ident,
            "document_type": "gazette_issue",
            "is_current": True,
            "canonical_law_url": source_url,
            "metadata": {
                "license": lic,
                "retrieved_at": r.get("retrieved_at"),
                "publisher": PUBLISHER.get(land),
                "source_name": r.get("host"),
                "source_type_detail": "gazette_as_published",
                "consolidated": bool(r.get("consolidated")),
                "gbl": gbl,
                "pdf_url": r.get("pdf_url"),
                "pdf_sha256": r.get("pdf_sha256"),
                "host": r.get("host"),
                "robots_disallowed": bool(r.get("robots_disallowed")),
                "transport": r.get("transport") or "https",
                "text_sha256": sha256_text(text),
                "text_chars": len(text),
                "collector": "de_laender_gvbl_collect.py",
                "fundstelle": r.get("fundstelle"),
                "proclamation_type": r.get("proclamation_type"),
                "review_pkg": "de_laender_append_20261105",
            },
        }
        rows.append({
            "id": nid, "title": title, "text": text, "source_url": source_url,
            "source_type": SOURCE_TYPE.get(land, "gvbl_gazette"),
            "jurisdiction": f"DE-{land}", "country": "Germany", "language": "de",
            "eli": None, "date": date, "date_issued": date,
            "retrieved_at": to_utc_z(r.get("retrieved_at")), "license": lic,
            "law_status": "current", "identifier": ident,
            "official_identifier": (r.get("fundstelle") or (f"GVBl. {gbl}" if gbl else None)),
            "article_count": 0, "json_path": None,
            "metadata_json": json.dumps(meta, ensure_ascii=False, separators=(",", ":")),
            "version_date": None, "supersedes": None, "superseded_by": None,
            "is_current": True, "effective_from": None,
        })
    return rows, {"raw": raw_n, "empty": empty, "dups": dups, "final": len(rows)}

def write_parquet(rows, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([(c, pa.bool_() if c=="is_current" else (pa.int64() if c=="article_count" else pa.string())) for c in LAWS_COLS])
    table = pa.table({c: pa.array([r[c] for r in rows], type=schema.field(c).type) for c in LAWS_COLS}, schema=schema)
    pq.write_table(table, out, compression="zstd")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lands", default="NI,BE,HH")
    ap.add_argument("--src-dir", type=Path, default=Path("/workspace/legal-corpora/de_laender_gvbl_20261105/rows"))
    ap.add_argument("--stage", type=Path, default=Path("/workspace/staging/de_laender_append_20261105"))
    args = ap.parse_args()
    summary = {}
    for land in [x.strip().upper() for x in args.lands.split(",") if x.strip()]:
        src = args.src_dir / f"DE-{land}.jsonl"
        if not src.exists():
            print(f"skip {land}: no {src}")
            continue
        rows, stats = normalize_land(land, src)
        outp = args.stage / "data" / f"laws_de_{land.lower()}_20261105.parquet"
        outj = args.stage / "data" / f"DE-{land}.normalized.jsonl"
        write_parquet(rows, outp)
        with open(outj, "w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False)+"\n")
        summary[land] = {"stats": stats, "parquet": str(outp), "rows": len(rows)}
        print(json.dumps({"land": land, **stats, "out": str(outp)}, ensure_ascii=False))
    (args.stage / "gvbl_normalize_summary.json").write_text(json.dumps(summary, indent=2)+"\n")

if __name__ == "__main__":
    main()
