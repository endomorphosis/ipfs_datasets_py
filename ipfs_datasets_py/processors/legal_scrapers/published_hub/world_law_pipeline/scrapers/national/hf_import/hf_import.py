#!/usr/bin/env python3
"""READ-ONLY import of endomorphosis/ipfs_<country>_laws HF datasets into staging/national/<CC>/.
Streams one parquet shard at a time (hf_hub_download -> pyarrow iter_batches -> delete shard).
Docs = rows of laws*.parquet; articles*.parquet only used to rebuild text of laws with empty text.
Mapping reuses emit_staged.convert(). Resumable via _hf_import/state/<CC>.json + <CC>.done_ids.
Dedupes against existing (non-hf) staged/processed files of the same CC by doc_id, source_url, (place,number).
Usage: hf_import.py CC [dataset_id] ...   (pairs or CC alone -> looked up in _hf_by_cc.json)
"""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, re, sys, shutil, glob, time
from datetime import datetime, timezone
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
import emit_staged as ES
from schema import place_key, validate_file, validate_record
import pyarrow as pa, pyarrow.parquet as pq
pa.set_cpu_count(1); pa.set_io_thread_count(1)
from huggingface_hub import HfApi, hf_hub_download

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national"))
PROC = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/processed/national"))
BASE = STAGE / "_hf_import"; CACHE = BASE / "_cache"; STATE = BASE / "state"
for d in (CACHE, STATE): d.mkdir(parents=True, exist_ok=True)
MAX_DOCS = int(os.environ.get("HF_MAX_DOCS", "2000")); MAX_BYTES = int(os.environ.get("HF_MAX_BYTES", str(100 << 20)))
MIN_FREE = 35 << 30
HF_BY_CC = json.load(open(STAGE / "_hf_by_cc.json"))
RUN_TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def log(*a): print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)

def check_disk():
    if shutil.disk_usage("/workspace").free < MIN_FREE:
        log("FREE DISK < 35 GB, stopping"); sys.exit(3)

def existing_keys(cc):
    ids, urls, nums = set(), set(), set()
    dirs = [Path(d) for d in glob.glob(f"/workspace/world_law/staging/*/{cc}") + glob.glob(f"/workspace/world_law/processed/*/{cc}")]
    files = [p for d in dirs if d.is_dir() for p in d.glob("iso_*.jsonl") if ".hf" not in p.name]
    for p in files:
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    try: r = json.loads(line)
                    except Exception: continue
                    ids.add((r.get("place_id"), str(r.get("doc_id"))))
                    if r.get("source_url"): urls.add(r["source_url"])
                    if r.get("number"): nums.add((r.get("place_id"), r["number"]))
        except Exception as e: log(cc, "dedupe read err", p, e)
    pq_files = [p for d in dirs if d.is_dir() for p in d.glob("iso_*.parquet") if ".hf" not in p.name]
    for p in pq_files:
        try:
            pf = pq.ParquetFile(p); cols = [c for c in ("place_id", "doc_id", "source_url", "number") if c in pf.schema_arrow.names]
            for b in pf.iter_batches(columns=cols, batch_size=5000):
                for r in b.to_pylist():
                    ids.add((r.get("place_id"), str(r.get("doc_id"))))
                    if r.get("source_url"): urls.add(r["source_url"])
                    if r.get("number"): nums.add((r.get("place_id"), r["number"]))
        except Exception as e: log(cc, "dedupe pq err", p, e)
    log(cc, f"dedupe index: {len(files)+len(pq_files)} live files, {len(ids)} ids, {len(urls)} urls")
    return ids, urls, nums

def prep(r):
    md = {}
    try: md = json.loads(r.get("metadata_json") or "{}") or {}
    except Exception: pass
    for k, v in list(r.items()):
        if v in ("None", "nan", ""): r[k] = None
    for k in ("document_type", "record_type", "is_current", "consolidated", "date_published", "date_in_force",
              "publication_date", "effective_date", "canonical_law_url"):
        if r.get(k) is None and md.get(k) is not None: r[k] = md[k]
    r["metadata"] = md.get("metadata") if isinstance(md.get("metadata"), dict) else md
    return r, md

class Importer:
    def __init__(self, cc, ds):
        self.cc, self.ds = cc, ds
        self.sf = STATE / f"{cc}.json"; self.idf = STATE / f"{cc}.done_ids"
        self.st = json.load(open(self.sf)) if self.sf.exists() else {}
        info = HfApi().dataset_info(ds, files_metadata=True)
        if self.st.get("dataset") != ds or self.st.get("sha") != info.sha:
            if self.st.get("dataset") == ds: log(cc, "dataset sha changed; keeping done_ids, restarting offsets")
            self.st = {"dataset": ds, "sha": info.sha, "shard_idx": 0, "row": 0, "part": self.st.get("part", 0),
                       "stats": {"rows_read": 0, "staged": 0, "dupes": 0, "empty": 0, "by_place": {}, "bytes": 0}}
        self.sha = info.sha
        files = {s.rfilename: s.size for s in info.siblings if s.rfilename.endswith(".parquet")}
        self.laws = sorted(f for f in files if re.search(r"(^|/)laws[^/]*\.parquet$", f))
        self.arts = sorted(f for f in files if re.search(r"(^|/)articles[^/]*\.parquet$", f))
        self.st["total_bytes"] = sum(files.values())
        self.done = set(self.idf.read_text().split("\n")) if self.idf.exists() else set()
        self.ids, self.urls, self.nums = existing_keys(cc)
        self.cat = ES.CAT.get(cc, {"display_name": HF_BY_CC.get(cc, {}).get("country", cc), "language": "und", "slug": cc.lower()})
        self.buckets, self.pending = {}, {}

    def save(self):
        tmp = self.sf.with_suffix(".tmp"); tmp.write_text(json.dumps(self.st, indent=1)); os.replace(tmp, self.sf)

    def flush_all(self):
        for pid in list(self.buckets):
            rows = self.buckets.pop(pid)
            if not rows: continue
            self.st["part"] += 1
            pk = place_key(pid); outdir = STAGE / self.cc; outdir.mkdir(exist_ok=True)
            final = outdir / f"{pk}.hf{RUN_TS}p{self.st['part']:04d}.jsonl"
            tmp = final.with_name(final.name + ".tmp")
            good = []
            for r in rows:
                e = validate_record(r)
                if e: log(self.cc, "invalid row dropped", r.get("doc_id"), e[:2]); self.st["stats"]["invalid"] = self.st["stats"].get("invalid", 0) + 1
                else: good.append(r)
            if not good: continue
            with tmp.open("w", encoding="utf-8") as f:
                for r in good: f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush(); os.fsync(f.fileno())
            os.rename(tmp, final)
            # rows already passed validate_record; full validate_file re-read skipped for huge files (memory)
            if final.stat().st_size < (200 << 20):
                v = validate_file(final, expect_place_key=pk)
                if not v["ok"]: log(self.cc, "validate_file not ok", final.name, v["errors"][:2])
            with self.idf.open("a") as f:
                f.write("\n".join(r["doc_id"] for r in good) + "\n"); f.flush(); os.fsync(f.fileno())
            s = self.st["stats"]; s["staged"] += len(good); s["bytes"] += final.stat().st_size
            s["by_place"][pid] = s["by_place"].get(pid, 0) + len(good)
            log(self.cc, "wrote", final.name, len(good), "docs", final.stat().st_size, "B")
        self.save(); check_disk()

    def to_rec(self, r, md, text_override=None):
        if text_override is not None: r["text"] = text_override
        pid, rec, why = ES.convert(r, self.cc, self.cat)
        if rec is None: return None, why
        if not rec.get("source_url") or not rec["source_url"].startswith("http"):
            rec["source_url"] = f"https://huggingface.co/datasets/{self.ds}"
        rec.update({"source": f"hf:{self.ds}", "source_revision": self.sha, "hf_dataset": self.ds,
                    "source_official": None, "license_note": r.get("license")})
        if md.get("schema_version"): rec["hf_schema_version"] = md["schema_version"]
        return {k: v for k, v in rec.items() if v is not None}, None

    def is_dup(self, rec):
        s = self.st["stats"]
        if rec["doc_id"] in self.done: return True
        if ((rec["place_id"], rec["doc_id"]) in self.ids or rec["source_url"] in self.urls
                or (rec.get("number") and (rec["place_id"], rec["number"]) in self.nums)):
            s["dupes"] += 1; return True
        return False

    def add(self, rec):
        b = self.buckets.setdefault(rec["place_id"], []); b.append(rec)
        self.done.add(rec["doc_id"])
        self._sz = getattr(self, "_sz", 0) + len(rec.get("text", "").encode())
        if len(b) >= MAX_DOCS or self._sz >= MAX_BYTES:
            self._sz = 0; return True
        return False

    def dl(self, f):
        check_disk()
        p = hf_hub_download(self.ds, f, repo_type="dataset", revision=self.sha, cache_dir=str(CACHE))
        return p

    def clean(self):
        shutil.rmtree(CACHE, ignore_errors=True); CACHE.mkdir(parents=True, exist_ok=True)

    def run(self):
        st, s = self.st, self.st["stats"]
        if st.get("complete"): log(self.cc, "already complete"); return st
        while st["shard_idx"] < len(self.laws):
            f = self.laws[st["shard_idx"]]; p = self.dl(f); pf = pq.ParquetFile(p)
            log(self.cc, "shard", f, pf.metadata.num_rows, "rows; resume at", st["row"])
            row = 0
            for b in pf.iter_batches(batch_size=8):
                n = b.num_rows
                if row + n <= st["row"]: row += n; continue
                for i, r in enumerate(b.to_pylist()):
                    if row + i < st["row"]: continue
                    s["rows_read"] += 1
                    r, md = prep(r)
                    if not r.get("id"): continue
                    rec, why = self.to_rec(dict(r), md)
                    if rec is None:
                        if why == "empty_text" and self.arts and r["id"] not in self.done:
                            self.pending[r["id"]] = (r, md)
                        else: s["empty"] += 1
                        continue
                    if self.is_dup(rec): continue
                    if self.add(rec):
                        st["row"] = row + i + 1; self.flush_all()
                row += n; st["row"] = row
            self.flush_all()
            del pf; self.clean()
            st["shard_idx"] += 1; st["row"] = 0; self.save()
        if self.pending:
            log(self.cc, len(self.pending), "laws with empty text; rebuilding from articles")
            for f in self.arts:
                p = self.dl(f); pf = pq.ParquetFile(p); cur, parts = None, []
                def fin():
                    if cur and cur in self.pending and parts:
                        r, md = self.pending.pop(cur)
                        rec, _ = self.to_rec(r, md, "\n\n".join(parts))
                        if rec and not self.is_dup(rec) and self.add(rec): self.flush_all()
                for b in pf.iter_batches(batch_size=1024, columns=[c for c in ("law_id", "text") if c in pf.schema_arrow.names]):
                    for a in b.to_pylist():
                        if a.get("law_id") != cur: fin(); cur, parts = a.get("law_id"), []
                        if cur in self.pending and a.get("text"): parts.append(a["text"])
                fin(); del pf; self.clean()
            s["empty"] += len(self.pending); self.pending = {}
            self.flush_all()
        st["complete"] = True; st["finished_at"] = datetime.now(timezone.utc).isoformat(); self.save()
        log(self.cc, "DONE", json.dumps(s)); return st

def main():
    a = sys.argv[1:]; jobs = []
    i = 0
    while i < len(a):
        cc = a[i].upper(); ds = None
        if i + 1 < len(a) and "/" in a[i + 1]: ds = a[i + 1]; i += 1
        if not ds:
            ds = next((d for d in HF_BY_CC.get(cc, {}).get("datasets", []) if d.startswith("endomorphosis/")), None)
        jobs.append((cc, ds)); i += 1
    for cc, ds in jobs:
        if not ds: log(cc, "no endomorphosis dataset; skip"); continue
        try: Importer(cc, ds).run()
        except MemoryError as e:
            log(cc, "ERROR MemoryError (will retry next queue pass)"); shutil.rmtree(CACHE, ignore_errors=True); CACHE.mkdir(parents=True, exist_ok=True)
        except SystemExit: raise
        except Exception as e:
            import traceback; log(cc, "ERROR", repr(e)); traceback.print_exc()
            shutil.rmtree(CACHE, ignore_errors=True); CACHE.mkdir(parents=True, exist_ok=True)
if __name__ == "__main__": main()
