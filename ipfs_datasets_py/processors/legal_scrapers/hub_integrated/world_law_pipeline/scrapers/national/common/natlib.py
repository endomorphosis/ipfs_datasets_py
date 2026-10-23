"""Shared helpers for phase-3 national/subnational collectors.
- PoliteSession: RFC 9309 robots gate (unreachable/5xx robots => disallow-all), Crawl-delay honoured,
  min delay between requests, retries with backoff on 429/5xx, no TLS relaxing, honest UA.
- Stager: SCHEMA.md §2 staged JSONL writer (.tmp -> fsync -> validate -> os.rename), one place per file,
  resumable via _work/<CC>/<name>.done ids.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, re, sys, time, html as _html, logging
from datetime import datetime, timezone
from pathlib import Path
import requests
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/common"))
from schema import place_key, validate_record, validate_file  # noqa
from robots import robots_for, UA  # noqa

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national"))

class Blocked(Exception):
    pass

class PoliteSession:
    def __init__(self, min_delay=2.0, timeout=60, log=None):
        self.s = requests.Session(); self.s.headers["User-Agent"] = UA
        self.min_delay = min_delay; self.timeout = timeout; self.last = {}
        self.log = log or logging.getLogger("natlib")
    def get(self, url, tries=4, **kw):
        rb, info = robots_for(url)
        if not (rb.can_fetch(UA, url) and rb.can_fetch("*", url)):
            raise Blocked(f"robots disallow ({info.get('rule')}) {url}")
        host = re.sub(r"^https?://", "", url).split("/")[0]
        delay = max(self.min_delay, rb.crawl_delay(UA) or 0)
        err = None
        for i in range(tries):
            wait = delay - (time.time() - self.last.get(host, 0))
            if wait > 0: time.sleep(wait)
            self.last[host] = time.time()
            try:
                r = self.s.get(url, timeout=kw.pop("timeout", self.timeout), **kw)
            except requests.RequestException as e:
                err = e; time.sleep(min(60, 5 * 2 ** i)); continue
            if r.status_code in (429, 500, 502, 503, 504):
                err = f"HTTP {r.status_code}"; time.sleep(min(120, 10 * 2 ** i)); continue
            if r.status_code in (401, 403):
                raise Blocked(f"HTTP {r.status_code} {url}")
            return r
        raise RuntimeError(f"GET failed {url}: {err}")

def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def norm_date(v):
    if not v: return None
    s = str(v).strip()
    m = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})", s)
    if m: return f"{m[1]}-{m[2]}-{m[3]}"
    m = re.match(r"^(\d{4})$", s)
    return m[1] if m else None

def html_to_text(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</li>|</tr>", "\n", h)
    t = _html.unescape(re.sub(r"<[^>]+>", " ", h))
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()

class Stager:
    def __init__(self, cc, name, chunk=500, log=None):
        self.cc = cc; self.name = name; self.chunk = chunk
        self.work = STAGE / "_work" / cc; self.work.mkdir(parents=True, exist_ok=True)
        self.out = STAGE / cc; self.out.mkdir(parents=True, exist_ok=True)
        self.done_f = self.work / f"{name}.done"
        self.done = set(self.done_f.read_text().split("\n")) if self.done_f.exists() else set()
        self.buf = {}; self.part = 0; self.n = 0; self.bad = 0
        self.log = log or logging.getLogger(name)
    def seen(self, doc_id):
        return str(doc_id) in self.done
    def add(self, rec):
        rec.setdefault("retrieved_at", utcnow())
        rec = {k: v for k, v in rec.items() if v is not None and v != ""}
        errs = validate_record(rec)
        if errs:
            self.bad += 1; self.log.warning("invalid %s %s", rec.get("doc_id"), errs); return False
        self.buf.setdefault(rec["place_id"], []).append(rec)
        if len(self.buf[rec["place_id"]]) >= self.chunk: self.flush(rec["place_id"])
        return True
    def flush(self, pid=None):
        for p in ([pid] if pid else list(self.buf)):
            rows = self.buf.pop(p, [])
            if not rows: continue
            self.part += 1
            pk = place_key(p)
            batch = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"{self.name}{self.part:04d}"
            batch = re.sub(r"[^A-Za-z0-9_-]", "", batch)
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
            self.n += len(rows); self.log.info("staged %s (%d docs, total %d)", final.name, len(rows), self.n)

def setup_log(cc, name):
    p = STAGE / "_logs" / "full" / f"{cc}_{name}.log"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(p), logging.StreamHandler()])
    return logging.getLogger(name)
