#!/usr/bin/env python3
"""Single-process, low-memory Poland fetcher (replaces the 3 `pl_dzienniki.py all` workers).

* ONE process, a small pool of worker threads (default 6) that round-robin over the reachable voivodeship hosts.
  A host is used by at most one worker at a time and `Host.get` keeps >= 0.7 s (or robots Crawl-delay) between its
  requests, so each host stays at <= ~1.4 req/s.
* Queue on disk: `_state/pl/queue_<WOJ>.jsonl` (pass-1 items, newest first; built once by streaming the catalog with
  byte offsets) and a sqlite done-set `_state/pl/pl_done.sqlite` (imports the old `done_<WOJ>.txt`; they are still appended).
* PDFs are streamed to a temp file (never held in memory) and converted with the pdftotext subprocess.
* Per-host batches flush at 100 docs / 8 MB text / 15 min. Batch names carry a UTC timestamp:
  `PL/<place_key>.pldz_<WOJ>_<YYYYMMDDTHHMMSSZ>p<NNNN>.jsonl`, `_unmatched/pl_<WOJ>_unmatched_<UTC>p0001.jsonl`.
* Graceful stop: SIGTERM -> workers finish the current doc, all buffers are flushed, then exit.

Run:  MALLOC_ARENA_MAX=2 nohup python3 pl_run.py [--woj ...] [--workers 6] >> _logs/pl_run.nohup.out 2>&1 &
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import signal
import sqlite3
import tempfile
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

import pl_dzienniki as P

STATE, OUT, PL_DIR, UNM_DIR = P.STATE, P.OUT, P.PL_DIR, P.UNM_DIR
log = P.log
BLOCKED = {"KP", "LB", "WP"}            # network-blocked; handled by archive_jobs.py pl
FLUSH_DOCS, FLUSH_BYTES, FLUSH_SECS = 100, 8 * 1024 * 1024, 900
KEEP = ("year", "pos", "type", "title", "status", "displayAddress", "promulgation", "announcementDate", "changeDate", "address")
STOP = threading.Event()


def utc_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ----------------------------------------------------------------------------- disk queue
def build_queue(woj: str) -> Path:
    cat = STATE / f"catalog_{woj}.jsonl"
    qp, mp = STATE / f"queue_{woj}.jsonl", STATE / f"queue_{woj}.meta.json"
    if qp.exists() and mp.exists() and json.loads(mp.read_text()).get("cat_size") == cat.stat().st_size:
        return qp
    pub = f"POL_WOJ_{woj}"
    seen, keys, why, off, n = set(), [], Counter(), 0, 0
    with cat.open("rb") as f:
        for raw in f:
            it = json.loads(raw)
            eli = it.get("eli") or f"{pub}/{it['year']}/{it['pos']}"
            if eli not in seen:
                seen.add(eli)
                n += 1
                ok, reason, org, lvl = P.in_pass1(it)
                why[reason] += 1
                if ok:
                    keys.append((-int(it["year"] or 0), -int(it["pos"] or 0), off))
            off += len(raw)
    del seen
    keys.sort()
    tmp = qp.with_suffix(".tmp")
    with cat.open("rb") as f, tmp.open("w", encoding="utf-8") as o:
        for _, _, off in keys:
            f.seek(off)
            it = json.loads(f.readline())
            ok, reason, org, lvl = P.in_pass1(it)
            d = {k: it.get(k) for k in KEEP}
            d.update(eli=it.get("eli") or f"{pub}/{it['year']}/{it['pos']}", _org=org, _lvl=lvl)
            o.write(json.dumps(d, ensure_ascii=False) + "\n")
    os.rename(tmp, qp)
    mp.write_text(json.dumps({"cat_size": cat.stat().st_size, "catalog": n, "pass1": len(keys), "filter": why}, default=dict))
    (STATE / f"scope_{woj}.json").write_text(json.dumps({"catalog": n, "pass1": len(keys), "filter": why}, default=dict))
    del keys
    gc.collect()
    return qp


class DoneDB:
    def __init__(self, path: Path):
        self.c = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.execute("PRAGMA cache_size=-8000")   # 8 MB page cache
        self.c.execute("CREATE TABLE IF NOT EXISTS done (eli TEXT PRIMARY KEY)")
        self.lock = threading.Lock()

    def import_txt(self, p: Path) -> None:
        if not p.exists():
            return
        with self.lock, p.open(encoding="utf-8") as f:
            self.c.execute("BEGIN")
            for ln in f:
                if ln.strip():
                    self.c.execute("INSERT OR IGNORE INTO done VALUES (?)", (ln.strip(),))
            self.c.execute("COMMIT")

    def has(self, eli: str) -> bool:
        with self.lock:
            return self.c.execute("SELECT 1 FROM done WHERE eli=?", (eli,)).fetchone() is not None

    def add_many(self, elis) -> None:
        with self.lock:
            self.c.execute("BEGIN")
            self.c.executemany("INSERT OR IGNORE INTO done VALUES (?)", [(e,) for e in elis])
            self.c.execute("COMMIT")

    def count_prefix(self, pre: str) -> int:
        with self.lock:
            return self.c.execute("SELECT count(*) FROM done WHERE eli >= ? AND eli < ?", (pre, pre + "\uffff")).fetchone()[0]


# ----------------------------------------------------------------------------- hosts
class HS:
    def __init__(self, woj: str, db: DoneDB):
        self.woj, self.db = woj, db
        self.h = P.Host(woj)
        self.qf = build_queue(woj).open(encoding="utf-8")
        self.rows: list = []
        self.bytes = 0
        self.t_flush = time.time()
        self.busy = False
        self.exhausted = False
        self.n = 0
        self.st = Counter()
        self.done_f = (STATE / f"done_{woj}.txt").open("a", encoding="utf-8")
        self.fail_f = (STATE / f"failed_{woj}.jsonl").open("a", encoding="utf-8")

    def next_item(self):
        for ln in self.qf:
            it = json.loads(ln)
            if not self.db.has(it["eli"]):
                return it
        self.exhausted = True
        return None


def fetch_pdf_text(h: P.Host, eli: str) -> tuple[str, dict]:
    r = h.get(f"/api/eli/acts/{eli}/text.pdf", stream=True)
    clen = int(r.headers.get("Content-Length") or 0)
    if clen > P.MAX_PDF:
        r.close()
        raise requests.HTTPError(f"pdf too large ({clen} bytes), skipped")
    sha, n, head = hashlib.sha256(), 0, b""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
        for chunk in r.iter_content(65536):
            if not head:
                head = chunk[:4]
            sha.update(chunk)
            tf.write(chunk)
            n += len(chunk)
            if n > P.MAX_PDF:
                break
        r.close()
        tf.flush()
        meta = {"pdf_bytes": n, "pdf_sha256": sha.hexdigest(), "pdf_truncated": n > P.MAX_PDF}
        text = ""
        if not meta["pdf_truncated"] and head == b"%PDF":
            text = P.pdf_text_file(tf.name)
    return text, meta


def process(hs: HS, pm: P.PlaceMap, it: dict) -> None:
    eli, org, lvl = it["eli"], it.pop("_org"), it.pop("_lvl")
    h = hs.h
    try:
        pl = pm.resolve(hs.woj, org, lvl)
        text, src, meta = "", "pdf", {}
        try:
            text, meta = fetch_pdf_text(h, eli)
        except requests.HTTPError as e:
            meta = {"pdf_error": str(e)[:200]}
        if len(text) < 200:
            try:
                hr = h.get(f"/api/eli/acts/{eli}/text.html", retries=3)
                ht = P.html_text(hr.text)
                if len(ht) > len(text):
                    text, src = ht, "html_first_page_only"
            except Exception as e:  # noqa: BLE001
                meta["html_error"] = str(e)[:200]
        if not text.strip():
            raise RuntimeError("no text (scanned PDF without text layer?)")
        it["eli"] = eli
        row = P.build(h, it, org, lvl, pl, text, src, meta)
        hs.rows.append(row)
        hs.bytes += len(text)
    except Exception as e:  # noqa: BLE001
        log.warning("%s FAIL %s: %s", hs.woj, eli, str(e)[:300])
        hs.fail_f.write(json.dumps({"eli": eli, "error": str(e)[:500], "at": P.utcnow()}, ensure_ascii=False) + "\n")
        hs.fail_f.flush()
    hs.n += 1


def flush_hs(hs: HS, force=False) -> None:
    if not hs.rows or not (force or len(hs.rows) >= FLUSH_DOCS or hs.bytes >= FLUSH_BYTES
                           or time.time() - hs.t_flush >= FLUSH_SECS):
        return
    st = P.flush_utc(hs.woj, hs.rows)
    elis = [r["doc_id"] for r in hs.rows]
    for e in elis:
        hs.done_f.write(e + "\n")
    hs.done_f.flush()
    os.fsync(hs.done_f.fileno())
    hs.db.add_many(elis)
    hs.st.update(st)
    log.info("%s flush matched=%d unmatched=%d | session %d docs, done total %d", hs.woj, st["matched"], st["unmatched"],
             hs.n, hs.db.count_prefix(f"POL_WOJ_{hs.woj}/"))
    hs.rows, hs.bytes, hs.t_flush = [], 0, time.time()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--woj", nargs="*", default=[w for w in P.HOSTS if w not in BLOCKED])
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    P.setup_logging()
    threading.current_thread().name = "pl_run"
    db = DoneDB(STATE / "pl_done.sqlite")
    for w in a.woj:
        db.import_txt(STATE / f"done_{w}.txt")
    pm = P.PlaceMap()
    hosts = []
    for w in a.woj:
        if not (STATE / f"catalog_{w}.jsonl").exists():
            log.warning("%s: no catalog, skipped", w)
            continue
        hosts.append(HS(w, db))
        gc.collect()
    log.info("pl_run start: hosts=%s workers=%d", [h.woj for h in hosts], a.workers)
    lock = threading.Lock()
    rr = [0]

    def pick():
        with lock:
            for k in range(len(hosts)):
                hs = hosts[(rr[0] + k) % len(hosts)]
                if not hs.busy and not hs.exhausted and hs.h.parked_until <= time.time():
                    hs.busy = True
                    rr[0] = (rr[0] + k + 1) % len(hosts)
                    return hs
        return None

    def worker(i):
        threading.current_thread().name = f"w{i}"
        while not STOP.is_set():
            hs = pick()
            if hs is None:
                if all(h.exhausted for h in hosts):
                    return
                time.sleep(2)
                continue
            try:
                it = hs.next_item()
                if it is not None:
                    process(hs, pm, it)
                flush_hs(hs, force=hs.exhausted)
            except Exception as e:  # noqa: BLE001
                log.error("%s worker error: %s", hs.woj, e)
            finally:
                hs.busy = False

    def on_term(sig, frm):
        log.info("signal %s: finishing current docs, flushing", sig)
        STOP.set()
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    ts = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(a.workers)]
    for t in ts:
        t.start()
    last_gc = time.time()
    while any(t.is_alive() for t in ts):
        time.sleep(5)
        if time.time() - last_gc > 300:
            gc.collect()
            last_gc = time.time()
    for hs in hosts:
        try:
            flush_hs(hs, force=True)
        except Exception as e:  # noqa: BLE001
            log.error("%s final flush failed: %s", hs.woj, e)
    log.info("pl_run stopped: %s", {h.woj: dict(h.st) for h in hosts})


if __name__ == "__main__":
    main()
