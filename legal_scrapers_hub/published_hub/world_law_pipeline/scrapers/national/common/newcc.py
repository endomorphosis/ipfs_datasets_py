"""Helpers for the 2026-10-22 new-country collectors (TR mevzuat, UZ lex.uz, ...).

DedupSkip: skip docs whose source URL (any known URL variant) is already in an older
  ipfs_*_laws HF repo, via pipeline/dedup_index.py (state/dedup/old_urls.sqlite).  Read-only.
  Skips are logged to staging/national/_work/<CC>/<name>.dedup_skipped.tsv (resumable).
SafeStager: natlib.Stager but rows are validate_record()-checked BEFORE writing, written to
  <final>.tmp, flushed+fsynced, renamed, then validate_file()-checked.  Output only in
  staging/national/<CC>/.
"""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, re, sys, json, sqlite3
from datetime import datetime, timezone
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/common"))
import dedup_index as DX  # noqa
from natlib import Stager, place_key, validate_record, validate_file, STAGE  # noqa


class DedupSkip:
    def __init__(self, cc, name):
        self.con = sqlite3.connect(f"file:{DX.OLD_URLS_DB}?mode=ro", uri=True)
        self.f = (STAGE / "_work" / cc / f"{name}.dedup_skipped.tsv")
        self.f.parent.mkdir(parents=True, exist_ok=True)
        self.skipped = set()
        if self.f.exists():
            self.skipped = {l.split("\t")[0] for l in self.f.read_text().splitlines() if l}
        self.n = 0

    def lookup(self, *urls, prefix=False):
        """Return repo if any URL variant is already in an old ipfs_* repo.
        prefix=True also matches the normalized URL followed by '?...' (e.g. ONDATE variants)."""
        for u in urls:
            k = DX.norm_url(u)
            if not k: continue
            r = self.con.execute("select repo from u where url=?", (k,)).fetchone()
            if r: return r[0]
            if prefix:
                r = self.con.execute("select repo from u where url>? and url<? limit 1",
                                     (k + "?", k + "?\uffff")).fetchone()
                if r: return r[0]
        return None

    def check(self, doc_id, *urls, prefix=False):
        if str(doc_id) in self.skipped: return "already-logged"
        repo = self.lookup(*urls, prefix=prefix)
        if repo:
            with self.f.open("a") as fh:
                fh.write(f"{doc_id}\t{repo}\t{urls[0]}\n")
            self.skipped.add(str(doc_id)); self.n += 1
        return repo


class SafeStager(Stager):
    def flush(self, pid=None):
        for p in ([pid] if pid else list(self.buf)):
            rows = [r for r in self.buf.pop(p, []) if not validate_record(r)]
            if not rows: continue
            self.part += 1
            pk = place_key(p)
            batch = re.sub(r"[^A-Za-z0-9_-]", "",
                           datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"{self.name}{self.part:04d}")
            final = self.out / f"{pk}.{batch}.jsonl"; tmp = final.with_name(final.name + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush(); os.fsync(f.fileno())
            os.rename(tmp, final)
            v = validate_file(final, expect_place_key=pk)
            if not v["ok"]: self.log.error("validate_file not ok %s %s", final, v["errors"][:2])
            with self.done_f.open("a") as f:
                f.write("\n".join(str(r["doc_id"]) for r in rows) + "\n"); f.flush(); os.fsync(f.fileno())
            self.done.update(str(r["doc_id"]) for r in rows)
            self.n += len(rows); self.log.info("staged %s (%d docs, total %d, valid=%s)", final.name, len(rows), self.n, v["ok"])
