"""Shared plumbing for the ukie lane (UK + Ireland local law).

* PoliteSession: per-host spacing (>= 2 s, or robots Crawl-delay if larger), RFC 9309 robots (common/rfc9309.py,
  copied from scrapers/eu/common), no retries on 401/403/challenge pages (never bypass WAF/captcha).
* State: sqlite (resumable): places / docs / items tables + progress.json summary.
* stage(): wraps archive.staging.StagedWriter (validate -> .tmp -> fsync -> rename; provenance sidecar).
* guard(): disk (>= 35 GB free) and RSS (< 900 MB) checks; raise StopRun when violated.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import json
import logging
import os
import resource
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.rfc9309 import RobotsCache  # noqa: E402

LANE = "ukie"
os.environ.setdefault("ARCHIVE_LANE", LANE)
STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/ukie"))
STATE_DIR = STAGE / "_state"
LOGS = STAGE / "_logs"
UA = "world-municipal-law-research/1.0 (ukie lane: UK/IE local law; open-data reuse; >=2 s per host)"
MIN_FREE_GB = 35
MAX_RSS_MB = 900


class StopRun(Exception):
    pass


class Blocked(Exception):
    """Host refused us (robots, 401/403, WAF challenge, 429). Never retried live; archive fallback instead."""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def guard():
    free = shutil.disk_usage("/workspace").free / 1e9
    if free < MIN_FREE_GB:
        raise StopRun(f"disk free {free:.1f} GB < {MIN_FREE_GB} GB")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    if rss > MAX_RSS_MB:
        raise StopRun(f"peak RSS {rss:.0f} MB > {MAX_RSS_MB} MB")
    return free, rss


def get_logger(name: str) -> logging.Logger:
    LOGS.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(name)
    if not log.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", "%Y-%m-%dT%H:%M:%S%z")
        for h in (logging.FileHandler(LOGS / f"{name}.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)):
            h.setFormatter(fmt)
            log.addHandler(h)
        log.setLevel(logging.INFO)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
    return log


CHALLENGE_TITLE = ("just a moment", "attention required", "access denied", "are you a robot", "security check",
                   "request unsuccessful", "pardon our interruption", "ddos-guard")
CHALLENGE_MARK = ("cf-chl-", "/cdn-cgi/challenge-platform/", "_incapsula_resource", "captcha-delivery.com")


class PoliteSession:
    def __init__(self, log, min_interval: float = 2.0, retries: int = 3):
        self.log, self.min_interval, self.retries = log, min_interval, retries
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.8"})
        self.last: dict = {}
        self.robots = RobotsCache(lambda base: self._rsess(), UA, log=log)
        self.nreq = 0

    def _rsess(self):
        s = requests.Session()
        s.headers["User-Agent"] = UA
        return s

    def robots_status(self, url):
        """(allowed, basis) for url."""
        rb = self.robots.get(url)
        p = urlparse(url)
        st = self.robots.cache.get(f"{p.scheme}://{p.netloc}", (None, None, None))[2]
        ok = rb.can_fetch(UA, url)
        return ok, f"robots.txt {st}" + ("" if ok else " => disallow")

    def get(self, url: str, stream=False, max_bytes=None) -> requests.Response:
        ok, basis = self.robots_status(url)
        if not ok:
            raise Blocked(f"robots: {basis}")
        host = urlparse(url).netloc
        cd = self.robots.get(url).crawl_delay(UA) or 0
        gap = max(self.min_interval, min(float(cd), 30.0))
        err = None
        for a in range(self.retries):
            w = gap - (time.monotonic() - self.last.get(host, 0))
            if w > 0:
                time.sleep(w)
            self.last[host] = time.monotonic()
            self.nreq += 1
            try:
                r = self.s.get(url, timeout=(15, 60), stream=stream, allow_redirects=True)
            except requests.RequestException as e:
                err = e
                time.sleep(3 * (a + 1))
                continue
            if r.status_code in (401, 403, 451) or r.status_code == 429:
                raise Blocked(f"HTTP {r.status_code}")
            if r.status_code >= 500:
                err = Exception(f"HTTP {r.status_code}")
                time.sleep(5 * (a + 1))
                continue
            if r.status_code != 200:
                raise FileNotFoundError(f"HTTP {r.status_code}")
            if not stream and "html" in r.headers.get("content-type", ""):
                head = r.text[:20000].lower()
                import re as _re
                title = " ".join(_re.findall(r"<title[^>]*>(.*?)</title>", head, _re.S)[:1])
                if any(c in title for c in CHALLENGE_TITLE) or (len(r.text) < 30000 and any(
                        m in head for m in CHALLENGE_MARK)):
                    raise Blocked("challenge page")
            # redirected off-site to a disallowed path?
            if r.url != url and not self.robots.can_fetch(r.url):
                raise Blocked(f"robots (after redirect to {r.url})")
            return r
        raise err or Exception("fetch failed")


class State:
    """Resumable lane state. One sqlite file for all phases:
       places(place_id, cc, phase, name, tier, site, status, mode, docs, ocr, last_run, note)
         phase: 1 = GB principal councils, 2 = GB town/parish/community councils, 3 = IE local authorities
         status: todo | done | partial | blocked | error | done_robots_docs | deferred (archive items requeued,
                 see archive_deferrals; never done/blocked while any are pending)
       docs(doc_id, place_id, url, status, fmt, chars, staged_file, ts)   status: staged | needs_ocr | skipped:<why>
       items(key, source, status, place_id, info, ts)                    legislation.gov.uk / ISB items
       archive_deferrals(place_id, key, url, not_before, ..., state)    ArchiveDeferred requeue (not_before epoch s)
    """

    def __init__(self, path: Path = STATE_DIR / "ukie_state.sqlite"):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.c = sqlite3.connect(str(path), timeout=60)
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.executescript("""
        CREATE TABLE IF NOT EXISTS places(place_id TEXT PRIMARY KEY, cc TEXT, phase INT, name TEXT, tier TEXT,
            site TEXT, status TEXT DEFAULT 'todo', mode TEXT, docs INT DEFAULT 0, ocr INT DEFAULT 0, last_run TEXT,
            note TEXT);
        CREATE TABLE IF NOT EXISTS docs(doc_id TEXT, place_id TEXT, url TEXT, status TEXT, fmt TEXT, chars INT,
            staged_file TEXT, ts TEXT, PRIMARY KEY(place_id, doc_id));
        CREATE TABLE IF NOT EXISTS items(key TEXT PRIMARY KEY, source TEXT, status TEXT, place_id TEXT, info TEXT,
            ts TEXT);
        CREATE TABLE IF NOT EXISTS archive_deferrals(place_id TEXT, key TEXT, url TEXT, not_before REAL,
            host TEXT, status TEXT, reason TEXT, info TEXT, tries INT DEFAULT 0, state TEXT DEFAULT 'pending',
            first_ts TEXT, ts TEXT, updated REAL, PRIMARY KEY(place_id, key));
        CREATE INDEX IF NOT EXISTS archive_deferrals_pending ON archive_deferrals(state, place_id, not_before);
        """)
        self.c.commit()

    def upsert_place(self, **kw):
        cols = ",".join(kw)
        q = ",".join("?" * len(kw))
        upd = ",".join(f"{k}=COALESCE(excluded.{k},{k})" for k in kw if k != "place_id")
        self.c.execute(f"INSERT INTO places({cols}) VALUES({q}) ON CONFLICT(place_id) DO UPDATE SET {upd}",
                       list(kw.values()))
        self.c.commit()

    def place(self, pid):
        r = self.c.execute("SELECT * FROM places WHERE place_id=?", (pid,)).fetchone()
        if not r:
            return None
        return dict(zip([d[0] for d in self.c.execute("SELECT * FROM places LIMIT 0").description], r))

    def doc_done(self, pid, doc_id):
        r = self.c.execute("SELECT status FROM docs WHERE place_id=? AND doc_id=?", (pid, doc_id)).fetchone()
        return r[0] if r else None

    def mark_doc(self, pid, doc_id, url, status, fmt=None, chars=None, staged_file=None):
        self.c.execute("INSERT OR REPLACE INTO docs VALUES(?,?,?,?,?,?,?,?)",
                       (doc_id, pid, url, status, fmt, chars, staged_file, utcnow()))
        self.c.commit()

    def item(self, key):
        r = self.c.execute("SELECT status FROM items WHERE key=?", (key,)).fetchone()
        return r[0] if r else None

    def mark_item(self, key, source, status, place_id=None, info=None):
        self.c.execute("INSERT OR REPLACE INTO items VALUES(?,?,?,?,?,?)",
                       (key, source, status, place_id, json.dumps(info) if info is not None else None, utcnow()))
        self.c.commit()

    # ---- archive throttle deferrals (2026-10-18: ArchiveFetcher raises ArchiveDeferred instead of retrying) ----
    # One row per (place, key); key = archive candidate URL, or '__discover__' for the archive discovery step.
    # state: pending (requeued, retry no earlier than not_before) | resolved | superseded | gave_up (unknown_error cap).
    # info.incomplete=True: the doc is staged from an incomplete fetch (doc.incomplete); revisit for a complete copy.
    # Rows are never deleted.
    def defer(self, pid, key, url, not_before, host=None, status=None, reason=None, info=None):
        now = time.time()
        self.c.execute(
            "INSERT INTO archive_deferrals(place_id,key,url,not_before,host,status,reason,info,tries,state,first_ts,ts,"
            "updated) VALUES(?,?,?,?,?,?,?,?,1,'pending',?,?,?) ON CONFLICT(place_id,key) DO UPDATE SET "
            "url=excluded.url, not_before=excluded.not_before, host=excluded.host, status=excluded.status, "
            "reason=excluded.reason, info=COALESCE(excluded.info, info), tries=tries+1, state='pending', "
            "ts=excluded.ts, updated=excluded.updated",
            (pid, key, url, float(not_before), host, None if status is None else str(status), reason,
             json.dumps(info) if info is not None else None, utcnow(), utcnow(), now))
        self.c.commit()
        r = self.c.execute("SELECT tries FROM archive_deferrals WHERE place_id=? AND key=?", (pid, key)).fetchone()
        return r[0] if r else 1

    def pending_incomplete(self, pid, key) -> bool:
        r = self.c.execute("SELECT info FROM archive_deferrals WHERE place_id=? AND key=? AND state='pending'",
                           (pid, key)).fetchone()
        try:
            return bool(r and r[0] and json.loads(r[0]).get("incomplete"))
        except ValueError:
            return False

    def resolve_deferral(self, pid, key, state="resolved"):
        self.c.execute("UPDATE archive_deferrals SET state=?, ts=?, updated=? WHERE place_id=? AND key=? "
                       "AND state='pending'", (state, utcnow(), time.time(), pid, key))
        self.c.commit()

    def supersede_deferrals(self, pid, before: float):
        """A full re-run of the place reconsidered every item: pending rows it did not re-defer are stale."""
        self.c.execute("UPDATE archive_deferrals SET state='superseded', ts=?, updated=? WHERE place_id=? "
                       "AND state='pending' AND updated < ?", (utcnow(), time.time(), pid, before))
        self.c.commit()

    def pending_deferrals(self, pid):
        cols = ("key", "url", "not_before", "host", "status", "reason", "info", "tries")
        out = []
        for r in self.c.execute(f"SELECT {','.join(cols)} FROM archive_deferrals WHERE place_id=? AND state='pending' "
                                "ORDER BY not_before", (pid,)):
            d = dict(zip(cols, r))
            d["info"] = json.loads(d["info"]) if d["info"] else {}
            out.append(d)
        return out

    def place_not_before(self, pid) -> Optional[float]:
        """Earliest not_before over the place's pending deferrals (None if it has none)."""
        r = self.c.execute("SELECT MIN(not_before) FROM archive_deferrals WHERE place_id=? AND state='pending'",
                           (pid,)).fetchone()
        return r[0] if r and r[0] is not None else None

    def summary(self):
        s = {"updated": utcnow(), "phases": {}, "docs": {}, "items": {}}
        for ph, st, n, d, o in self.c.execute(
                "SELECT phase, status, COUNT(*), SUM(docs), SUM(ocr) FROM places GROUP BY phase, status"):
            s["phases"].setdefault(str(ph), {})[st] = {"places": n, "docs": d or 0, "ocr": o or 0}
        for st, n in self.c.execute("SELECT status, COUNT(*) FROM docs GROUP BY status"):
            s["docs"][st] = n
        for src, st, n in self.c.execute("SELECT source, status, COUNT(*) FROM items GROUP BY source, status"):
            s["items"].setdefault(src, {})[st] = n
        s["archive_deferrals"] = {st: n for st, n in self.c.execute(
            "SELECT state, COUNT(*) FROM archive_deferrals GROUP BY state")}
        tmp = STATE_DIR / "progress.json.tmp"
        tmp.write_text(json.dumps(s, indent=1))
        os.replace(tmp, STATE_DIR / "progress.json")
        return s


def append_jsonl(path: Path, rec: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
