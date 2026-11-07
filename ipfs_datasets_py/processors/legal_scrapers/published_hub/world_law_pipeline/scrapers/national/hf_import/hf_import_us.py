#!/usr/bin/env python3
"""READ-ONLY import of US sets from HF into staging/national/US/:
  usc    justicedao/ipfs_uscode  uscode_parquet/laws.parquet -> iso:US, one doc per USC section (2024 ed.)
  states justicedao/ipfs_state_laws state_laws_parquet_cid/STATE-XX.parquet -> iso:US-XX (adm1)
Resumable per file (state/US_<set>.json + US.done_ids). Reuses hf_import writer conventions.
Usage: hf_import_us.py usc|states [XX ...]
"""
import json, os, re, sys, shutil
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hf_import as H
from hf_import import log, check_disk, existing_keys, STAGE, STATE, CACHE, RUN_TS
from schema import place_key, validate_record, validate_file
import pyarrow.parquet as pq
from huggingface_hub import HfApi, hf_hub_download

def nn(v): return None if v in (None, "", "None", "nan") else v

class W:
    def __init__(self, key):
        self.sf = STATE / f"US_{key}.json"; self.idf = STATE / "US.done_ids"
        self.st = json.load(open(self.sf)) if self.sf.exists() else {"files": {}, "part": 0, "stats": {}}
        self.done = set(self.idf.read_text().split("\n")) if self.idf.exists() else set()
        self.ids, self.urls, _ = existing_keys("US"); self.buf = {}; self.sz = 0
    def save(self):
        t = self.sf.with_suffix(".tmp"); t.write_text(json.dumps(self.st, indent=1)); os.replace(t, self.sf)
    def add(self, rec, stats):
        if rec["doc_id"] in self.done or (rec["place_id"], rec["doc_id"]) in self.ids or rec["source_url"] in self.urls:
            stats["dupes"] = stats.get("dupes", 0) + 1; return
        self.buf.setdefault(rec["place_id"], []).append(rec); self.done.add(rec["doc_id"])
        self.sz += len(rec["text"].encode())
        if len(self.buf[rec["place_id"]]) >= H.MAX_DOCS or self.sz >= H.MAX_BYTES: self.flush(stats); return True
    def flush(self, stats):
        for pid in list(self.buf):
            rows = [r for r in self.buf.pop(pid) if not validate_record(r) or stats.__setitem__("invalid", stats.get("invalid", 0) + 1)]
            if not rows: continue
            self.st["part"] += 1; pk = place_key(pid); d = STAGE / "US"; d.mkdir(exist_ok=True)
            final = d / f"{pk}.hf{RUN_TS}p{self.st['part']:04d}.jsonl"; tmp = final.with_name(final.name + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush(); os.fsync(f.fileno())
            os.rename(tmp, final)
            if final.stat().st_size < (200 << 20):
                v = validate_file(final, expect_place_key=pk)
                if not v["ok"]: log("US validate_file not ok", final.name, v["errors"][:2])
            with self.idf.open("a") as f: f.write("\n".join(r["doc_id"] for r in rows) + "\n"); f.flush(); os.fsync(f.fileno())
            stats["staged"] = stats.get("staged", 0) + len(rows); stats["bytes"] = stats.get("bytes", 0) + final.stat().st_size
            bp = stats.setdefault("by_place", {}); bp[pid] = bp.get(pid, 0) + len(rows)
            log("US wrote", final.name, len(rows), final.stat().st_size)
        self.sz = 0; self.save(); check_disk()

def usc_rec(r, ds, sha):
    t, s = nn(r["title_number"]), nn(r["section_number"])
    if not (t and s and nn(r["text"])): return None
    ch = {}
    try: ch = json.loads(r.get("chapter_json") or "{}")
    except Exception: pass
    return {"place_id": "iso:US", "country_code": "US", "doc_id": f"usc-{t}-{s}", "source_platform": "us_uscode",
            "source_url": nn(r["source_url"]) or f"https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title{t}-section{s}",
            "doc_type": "code_section", "language": "en", "title_native": f"{t} U.S.C. § {s} - {nn(r['law_name']) or ''}".strip(" -"),
            "number": f"{t} U.S.C. {s}", "published_date": (nn(r["date_modified"]) or "")[:4] or None, "in_force": True,
            "consolidated": True, "content_format": "html", "text": r["text"],
            "place_name": "United States", "admin_level": "country", "platform": "us_uscode",
            "source": f"hf:{ds}", "source_revision": sha, "hf_dataset": ds, "hf_ipfs_cid": nn(r["ipfs_cid"]),
            "usc_title": t, "usc_title_name": nn(r["title_name"]), "usc_chapter": ch.get("chapter_label"),
            "usc_chapter_name": ch.get("chapter_name"), "urn": nn(r["jsonld_id"]), "source_official": True,
            "license_note": "US Code: public domain (17 U.S.C. 105)"}

def state_rec(r, ds, sha, sc):
    if not nn(r["text"]): return None
    lt = (nn(r.get("legislation_type")) or "statute").lower()
    url = nn(r["source_url"])
    if not (url and url.startswith("http")): url = f"https://huggingface.co/datasets/{ds}"
    rec = {"place_id": f"iso:US-{sc}", "country_code": "US", "doc_id": nn(r["source_id"]) or nn(r["ipfs_cid"]),
           "source_platform": f"us_{sc.lower()}_statutes", "source_url": url,
           "doc_type": "regulation" if re.search(r"rule|regul|admin", lt) else "code_section", "language": "en",
           "title_native": " ".join(x for x in (nn(r["identifier"]), nn(r["name"])) if x) or None, "number": nn(r["identifier"]),
           "in_force": None, "consolidated": True, "content_format": "html", "text": r["text"],
           "place_name": sc, "iso_3166_2": f"US-{sc}", "state_code": sc, "admin_level": "adm1", "platform": f"us_{sc.lower()}_statutes",
           "source": f"hf:{ds}", "source_revision": sha, "hf_dataset": ds, "hf_ipfs_cid": nn(r["ipfs_cid"]),
           "legislation_type": lt, "source_official": None}
    return {k: v for k, v in rec.items() if v is not None}

def run(kind, only):
    ds = "justicedao/ipfs_uscode" if kind == "usc" else "justicedao/ipfs_state_laws"
    info = HfApi().dataset_info(ds, files_metadata=True); sha = info.sha
    if kind == "usc": files = ["uscode_parquet/laws.parquet"]
    else:
        files = sorted(s.rfilename for s in info.siblings if re.match(r"state_laws_parquet_cid/STATE-[A-Z]{2}\.parquet$", s.rfilename))
        if only: files = [f for f in files if f[-10:-8] in only]
    w = W(kind)
    for f in files:
        fs = w.st["files"].setdefault(f, {"done": False, "rows": 0})
        if fs["done"]: continue
        check_disk(); p = hf_hub_download(ds, f, repo_type="dataset", revision=sha, cache_dir=str(CACHE))
        pf = pq.ParquetFile(p); stats = w.st["stats"].setdefault(kind, {})
        cols = ["ipfs_cid", "title_number", "title_name", "section_number", "law_name", "jsonld_id", "date_modified", "source_url", "text", "chapter_json"] if kind == "usc" else None
        sc = f[-10:-8]; n = 0
        log("US", kind, f, pf.metadata.num_rows, "rows")
        for b in pf.iter_batches(batch_size=200, columns=cols):
            for r in b.to_pylist():
                n += 1
                if n <= fs["rows"]: continue
                stats["rows_read"] = stats.get("rows_read", 0) + 1
                rec = usc_rec(r, ds, sha) if kind == "usc" else state_rec(r, ds, sha, sc)
                if rec is None: stats["empty"] = stats.get("empty", 0) + 1; continue
                if w.add(rec, stats): fs["rows"] = n; w.save()
        fs["done"] = True; w.flush(stats); w.save(); del pf
        shutil.rmtree(CACHE, ignore_errors=True); CACHE.mkdir(parents=True, exist_ok=True)
    log("US", kind, "DONE", json.dumps(w.st["stats"].get(kind, {}))[:2000])

if __name__ == "__main__":
    run(sys.argv[1], set(x.upper() for x in sys.argv[2:]))
