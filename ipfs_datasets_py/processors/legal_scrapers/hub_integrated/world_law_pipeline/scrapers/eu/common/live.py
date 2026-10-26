"""Shared plumbing for the EU-lane live scrapers (ee_rt, lv_likumi, lt_etar, si_ul, ...).

* PoliteSession: per-host min interval, RFC 9309 robots (common/rfc9309.py) incl. Crawl-delay, exponential backoff.
* Done: sqlite done-set (low memory).
* Stager: per-place buffers flushed as UTC-timestamped, validated, atomically renamed files
  <stage>/<CC>/<place_key>.<source>_<YYYYMMDDTHHMMSSZ>p<NNNN>.jsonl ; unmatched -> _unmatched/<source>_unmatched_<UTC>p0001.jsonl
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
import sqlite3
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from common.rfc9309 import RobotsCache  # noqa: E402

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu"))
LOGS = STAGE / "_logs"
UA = "world-municipal-law-research/1.0 (EU lane; open-data reuse; ~1 req/s per host)"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def get_logger(name: str) -> logging.Logger:
    LOGS.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(name)
    if not log.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", "%Y-%m-%dT%H:%M:%S%z")
        for h in (logging.FileHandler(LOGS / f"{name}.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)):
            h.setFormatter(fmt)
            log.addHandler(h)
        log.setLevel(logging.INFO)
    return log


class PoliteSession:
    def __init__(self, log, min_interval: float = 1.0, retries: int = 6, headers: Optional[dict] = None, verify=True):
        self.log, self.min_interval, self.retries = log, min_interval, retries
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, **(headers or {})})
        self.s.verify = verify
        self.last: dict = {}
        self.robots = RobotsCache(lambda base: self._rsess(), UA, log=log)

    def _rsess(self):
        s = requests.Session()
        s.headers["User-Agent"] = UA
        s.verify = self.s.verify
        return s

    def get(self, url: str, params=None, stream=False, ok=(200,), **kw) -> requests.Response:
        if not self.robots.can_fetch(url):
            raise PermissionError(f"robots.txt (RFC 9309) disallows {url}")
        host = url.split("/")[2]
        cd = self.robots.get(url).crawl_delay(UA) or 0
        gap = max(self.min_interval, cd)
        err = None
        for a in range(self.retries):
            w = gap - (time.monotonic() - self.last.get(host, 0))
            if w > 0:
                time.sleep(w)
            self.last[host] = time.monotonic()
            try:
                r = self.s.get(url, params=params, timeout=(20, 120), stream=stream, **kw)
                if r.status_code in ok:
                    return r
                if r.status_code in (400, 404, 410):
                    r.raise_for_status()
                if r.status_code in (401, 403):
                    self.log.error("HTTP %s (blocked?) %s", r.status_code, url)
                err = RuntimeError(f"HTTP {r.status_code} {url}")
                ra = r.headers.get("Retry-After")
                back = float(ra) if ra and ra.isdigit() else min(2 ** (a + 1), 300)
            except requests.HTTPError:
                raise
            except requests.RequestException as e:
                err, back = e, min(2 ** (a + 1), 300)
            self.log.warning("retry %d/%d %s; sleep %.0fs", a + 1, self.retries, str(err)[:200], back)
            time.sleep(back)
        raise err


class Done:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.c = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.execute("CREATE TABLE IF NOT EXISTS done (id TEXT PRIMARY KEY, why TEXT)")
        self.lock = threading.Lock()

    def has(self, k: str) -> bool:
        with self.lock:
            return self.c.execute("SELECT 1 FROM done WHERE id=?", (k,)).fetchone() is not None

    def add_many(self, items) -> None:
        with self.lock:
            self.c.execute("BEGIN")
            self.c.executemany("INSERT OR REPLACE INTO done VALUES (?,?)", list(items))
            self.c.execute("COMMIT")

    def count(self, why: Optional[str] = None) -> int:
        with self.lock:
            if why:
                return self.c.execute("SELECT count(*) FROM done WHERE why=?", (why,)).fetchone()[0]
            return self.c.execute("SELECT count(*) FROM done").fetchone()[0]


def _schema():
    import schema
    return schema


def atomic_write(path: Path, rows: list, pk: Optional[str] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name[:-len(".jsonl")] + ".tmp.jsonl")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    if pk:
        v = _schema().validate_file(tmp, expect_place_key=pk)
        if not v["ok"]:
            os.unlink(tmp)
            raise RuntimeError(f"validate_file failed {path.name}: {v['errors'][:3]} {v['file_errors']}")
    os.rename(tmp, path)


_STOP = [False]


class Stager:
    """Buffers rows; flush() writes one file per place (+ one unmatched file) with a fresh UTC tag."""

    def __init__(self, cc: str, source: str, log, max_docs: int = 200, max_bytes: int = 12 * 1024 * 1024,
                 max_secs: int = 900, stage: Path = STAGE):
        self.cc, self.source, self.log = cc, source, log
        self.max_docs, self.max_bytes, self.max_secs, self.stage = max_docs, max_bytes, max_secs, stage
        self.rows: list = []
        self.keys: list = []
        self.bytes = 0
        self.t = time.time()
        self.total = Counter()
        self.places: set = set()

    def add(self, row: Optional[dict], key: str, why: str = "ok") -> None:
        if row is not None:
            self.rows.append(row)
            self.bytes += len(row.get("text") or "") + len(row.get("html") or "")
        self.keys.append((key, why))
        if _STOP[0] and getattr(self, "_done_ref", None) is not None:   # SIGTERM: flush at a safe point, then exit
            self.log.info("SIGTERM: flushing %d buffered docs and exiting (resume with the same command)", len(self.keys))
            self.flush(self._done_ref)
            sys.exit(0)

    def graceful(self, done: "Done") -> "Stager":
        """Install a SIGTERM handler: the next add() flushes the buffer (files + done marks) and exits cleanly."""
        import signal
        self._done_ref = done
        signal.signal(signal.SIGTERM, lambda *_: _STOP.__setitem__(0, True))
        return self

    def due(self) -> bool:
        return len(self.keys) >= self.max_docs or self.bytes >= self.max_bytes or \
            (self.keys and time.time() - self.t >= self.max_secs)

    def flush(self, done: Done) -> Counter:
        sch = _schema()
        st = Counter()
        ts = utc_tag()
        by = defaultdict(list)
        unm = []
        for r in self.rows:
            (by[r["place_id"]] if r.get("place_id") else unm).append(r)
        part = 0
        for pid, rs in by.items():
            bad = {r["doc_id"]: e for r in rs for e in [sch.validate_record(r)] if e}
            if bad:
                self.log.warning("%d invalid rows e.g. %s", len(bad), list(bad.items())[:1])
                atomic_write(self.stage / "_invalid" / f"{sch.place_key(pid)}.{self.source}_{ts}p{part + 1:04d}.jsonl",
                             [dict(r, _errors=bad[r["doc_id"]]) for r in rs if r["doc_id"] in bad])
                rs = [r for r in rs if r["doc_id"] not in bad]
            if not rs:
                continue
            part += 1
            pk = sch.place_key(pid)
            atomic_write(self.stage / self.cc / f"{pk}.{self.source}_{ts}p{part:04d}.jsonl", rs, pk)
            st["matched"] += len(rs)
            self.places.add(pid)
        if unm:
            atomic_write(self.stage / "_unmatched" / f"{self.source}_unmatched_{ts}p0001.jsonl", unm)
            st["unmatched"] += len(unm)
        done.add_many(self.keys)
        st["skipped"] = sum(1 for _, w in self.keys if w != "ok")
        self.total.update(st)
        self.rows, self.keys, self.bytes, self.t = [], [], 0, time.time()
        return st
