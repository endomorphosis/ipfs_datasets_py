#!/usr/bin/env python3
"""Shared helpers for national legislation collectors."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import hashlib
import html
import json
import os
import re
import tempfile
import threading
import time
import traceback
from collections import Counter
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Optional
from xml.etree import ElementTree as ET

import requests
from requests.adapters import HTTPAdapter

# --- robots.txt guard wiring (CoS-approved 2026-10-01) ----------------------------------------
# Every request sent through get_session() / http_get() is checked against the host's robots.txt first
# (robots_guard: fetched once per scheme+host and cached for the run, RFC 9309 matching, dated
# snapshot under <cc>/logs/robots/) and spaced by the host's Crawl-delay (per-host sleep).
# Policy is robots_guard's documented one: robots.txt 404/410/other 4xx = no rules = allow;
# 5xx/429/401/403/WAF page/timeout/network error = fail CLOSED (RobotsUnavailable).
# A refused URL is never requested: the guard logs it (logger "robots_guard", message
# "RobotsBlocked ...", plus a row in <cc>/logs/robots_blocked.jsonl) and RobotsBlockedFetch is
# raised inside the send; it subclasses robots_guard.RobotsBlocked (PermissionError),
# requests.RequestException and RuntimeError, so the existing `except` clauses around these
# helpers turn it into their usual error value (error dict / [] / None / failure) unchanged.
import logging as _rg_logging
from urllib.parse import urlsplit as _rg_urlsplit
try:
    import robots_guard as _rg
except ImportError:  # package-style import (ipfs_datasets_py) or loaded via a compat shim
    try:
        from . import robots_guard as _rg  # type: ignore
        import sys as _rg_sys
        _rg_sys.modules.setdefault("robots_guard", _rg)  # one guard + one robots cache per process
    except Exception:
        import importlib.util as _rg_ilu
        import sys as _rg_sys
        from pathlib import Path as _rg_Path
        try:  # sibling file next to this canonical module (shims execute it by path)
            _rg_path = _rg_Path(__file__).resolve().with_name("robots_guard.py")
            _rg_spec = _rg_ilu.spec_from_file_location("robots_guard", _rg_path)
            _rg = _rg_ilu.module_from_spec(_rg_spec)
            _rg_sys.modules["robots_guard"] = _rg
            _rg_spec.loader.exec_module(_rg)
        except Exception:  # pragma: no cover
            _rg_sys.modules.pop("robots_guard", None)
            _rg = None


def _robots_guard_on():
    """robots_guard.guard_enabled(), honoring the env switch even if the guard failed to import."""
    if _rg is not None and hasattr(_rg, "guard_enabled"):
        return _rg.guard_enabled()
    return (os.environ.get("IPFS_DATASETS_LEGAL_ROBOTS_GUARD") or "").strip().lower() not in {"0", "false", "off", "no"}
_rg_log = _rg_logging.getLogger("robots_guard")
if _rg is None:  # pragma: no cover
    _rg_log.warning("robots_guard module not importable: common fetches will fail closed")
    _RG_BASE = PermissionError
else:
    _RG_BASE = _rg.RobotsBlocked


class RobotsBlockedFetch(_RG_BASE, requests.exceptions.RequestException, RuntimeError):
    """robots.txt disallows the URL (or robots.txt is unavailable: fail closed); not fetched."""

    def __init__(self, msg, decision=None):
        PermissionError.__init__(self, msg)
        self.decision = decision
        self.response = None
        self.request = None


def _robots_blocked(url, caller=""):
    """None if the URL may be fetched (after the per-host Crawl-delay wait); else the refusing
    robots_guard.Decision (already logged)."""
    if not _robots_guard_on():
        return None
    if _rg is None:
        raise RobotsBlockedFetch("robots_guard unavailable; refusing unguarded request")
    if not url:
        return None
    sp = _rg_urlsplit(str(url))
    if (sp.scheme or "").lower() not in ("http", "https"):
        return None
    d = _rg.check(str(url))
    if not d.allowed:
        _rg.report_blocked(d, caller)
        _rg_log.warning("RobotsBlocked %s: %s (%s) caller=%s", d.reason, url, d.rule, caller)
        return d
    # shared per-host clock in robots_guard: waits Crawl-delay once per request, measured from the
    # last request to the host; a pre-flight robots_guard.guard()/wait() of this request is not repeated
    (getattr(_rg, "wait_send", None) or _rg.wait)(str(url))
    return None


def _robots_gate(url, caller=""):
    d = _robots_blocked(url, caller)
    if d is not None:
        raise RobotsBlockedFetch(f"RobotsBlocked: robots guard {d.reason} {url} ({d.rule})", d)


class _RobotsSession(requests.Session):
    """requests.Session whose every send() (each redirect hop too) passes the robots gate."""

    robots_caller = "common"

    def send(self, request, **kwargs):
        _robots_gate(request.url, self.robots_caller)
        return super().send(request, **kwargs)
# --- end robots.txt guard wiring --------------------------------------------------------------

ROOT = Path(os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", os.environ.get("LEGAL_CORPORA_ROOT", str(Path.home() / ".ipfs_datasets" / "legal_corpora"))))
SCHEMA_PATH = ROOT / "_templates" / "collection_record.schema.json"
PT = timezone(timedelta(hours=-7))
DEFAULT_UA = (
    "legal-corpora-collector/1.0 "
    "(research archive of official national gazettes; polite; "
    "no commercial scraping; contact via local operator)"
)
INDEX_FIELDS = (
    "id", "path", "title", "identifier", "eli", "source_url", "source_type",
    "jurisdiction", "language", "law_status", "date", "retrieved_at",
    "article_count", "bytes",
)

# Per-scraper page-fetch concurrency (Cap/thin/deepen harvest).
# Env: PAGE_FETCH_WORKERS or WORKERS. Conservative default 8 (was typically 3–4
# hardcoded, or 1 for sequential Cap collectors). Prefer <=8 against a single
# host; raise SLEEP / back off on 429. CDX/Wayback remain separately rate-limited
# in archive_fallbacks (~1 req/s Wayback, ~0.35s CC).
def _env_workers(default: int = 8) -> int:
    for key in ("PAGE_FETCH_WORKERS", "WORKERS"):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        try:
            return max(1, int(raw))
        except Exception:
            continue
    return max(1, int(default))


DEFAULT_PAGE_FETCH_WORKERS = _env_workers(8)
PAGE_FETCH_WORKERS = DEFAULT_PAGE_FETCH_WORKERS
# Alias used by ThreadPool collectors that `from common import DEFAULT_WORKERS`.
DEFAULT_WORKERS = DEFAULT_PAGE_FETCH_WORKERS

_tls = threading.local()
_index_lock = threading.Lock()
_fail_lock = threading.Lock()
_schema = None
_schema_lock = threading.Lock()


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def pt_from_iso(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return iso
    return dt.astimezone(PT).strftime("%Y-%m-%d %H:%M:%S PT")


def localtag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def slug_id(cc: str, official: str) -> str:
    s = (official or "").strip()
    s = s.replace("https://", "").replace("http://", "")
    s = re.sub(r"[/\\]+", "__", s)
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", s)
    s = s.strip("-._")
    if not s:
        s = "unknown"
    s = s.lower()
    if not s.startswith(cc.lower() + "-"):
        s = f"{cc.lower()}-{s}"
    if s[0] not in "abcdefghijklmnopqrstuvwxyz0123456789":
        s = "x" + s
    return s[:180]


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()


def get_session(ua: str = DEFAULT_UA, pool: int | None = None) -> requests.Session:
    if pool is None:
        pool = max(8, min(32, int(PAGE_FETCH_WORKERS) * 2))
    s = getattr(_tls, "session", None)
    if s is None or getattr(_tls, "ua", None) != ua or getattr(_tls, "pool", None) != pool:
        s = _RobotsSession()  # robots-gated (see robots.txt guard wiring above)
        s.headers.update({
            "User-Agent": ua,
            "Accept": "application/json, application/xml, text/xml, text/html, */*",
            "Accept-Language": "en,*;q=0.8",
        })
        ad = HTTPAdapter(pool_connections=pool, pool_maxsize=pool, max_retries=0)
        s.mount("https://", ad)
        s.mount("http://", ad)
        _tls.session = s
        _tls.ua = ua
        _tls.pool = pool
    return s


def map_parallel(fn, items, *, workers: int | None = None):
    """Run fn over items with a ThreadPool (order-preserving).

    workers defaults to PAGE_FETCH_WORKERS. Used by Cap/thin/deepen harvest
    paths and ThreadPool collectors for page-fetch concurrency.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    seq = list(items)
    if not seq:
        return []
    n = max(1, int(workers if workers is not None else PAGE_FETCH_WORKERS))
    if n == 1 or len(seq) == 1:
        return [fn(x) for x in seq]
    out: list = [None] * len(seq)
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(fn, item): i for i, item in enumerate(seq)}
        for fut in as_completed(futs):
            out[futs[fut]] = fut.result()
    return out


def http_get(
    url: str,
    *,
    ua: str = DEFAULT_UA,
    timeout: tuple = (20, 90),
    retries: int = 5,
    sleep: float = 0.35,
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    allow_empty: bool = False,
) -> requests.Response:
    last = None
    hdrs = headers or {}
    for attempt in range(1, retries + 1):
        try:
            if sleep:
                time.sleep(sleep)
            resp = get_session(ua).get(url, timeout=timeout, headers=hdrs, params=params)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(min(30, 2 ** attempt))
                last = resp
                continue
            if resp.status_code == 200 and (allow_empty or resp.content):
                return resp
            if resp.status_code in (404, 410, 403, 401):
                return resp
            last = resp
            if attempt < retries:
                time.sleep(min(20, 1.5 * attempt))
                continue
            return resp
        except RobotsBlockedFetch:
            raise  # robots.txt refused the URL (logged); not fetched, no retries
        except requests.RequestException as exc:
            last = exc
            time.sleep(min(20, 1.5 * attempt))
    if isinstance(last, requests.Response):
        return last
    raise RuntimeError(f"GET failed {url}: {last}")


class _HTMLText(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self._block = {
            "p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
            "article", "section", "blockquote", "pre", "td", "th", "dt", "dd",
        }

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag in {"br", "p", "tr", "div", "li", "h1", "h2", "h3"} and self.skip == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self._block and self.skip == 0:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip == 0:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    p = _HTMLText()
    try:
        p.feed(raw)
        p.close()
    except Exception:
        raw = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
        raw = re.sub(r"(?is)<style.*?>.*?</style>", " ", raw)
        raw = re.sub(r"(?is)<[^>]+>", " ", raw)
        return re.sub(r"[ \t]+\n", "\n", html.unescape(raw)).strip()
    text = "".join(p.parts)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def xml_to_text(raw: str, skip_tags: Optional[set[str]] = None) -> str:
    skip_tags = skip_tags or {
        "meta", "identification", "references", "classification",
        "workflow", "analysis", "proprietary", "presentation",
    }
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return html_to_text(raw)
    parts: list[str] = []

    def walk(el: ET.Element) -> None:
        tag = localtag(el.tag).lower()
        if tag in skip_tags:
            return
        if el.text and el.text.strip():
            parts.append(el.text.strip())
        for child in list(el):
            walk(child)
            if child.tail and child.tail.strip():
                parts.append(child.tail.strip())
        if tag in {"p", "article", "chapter", "section", "alinea", "paragraph", "item"}:
            parts.append("\n")

    walk(root)
    text = " ".join(parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


ARTICLE_SPLIT = re.compile(
    r"(?im)^\s*((?:art(?:icle|ikel|\.)|§|článek|článok|član|artikkel|articolo|"
    r"artigo|artículo|artykuł|art\.\s*|str\.\s*|para(?:graph)?\.?|szakasz|"
    r"άρθρο|Άρθρο|ΑΡΘΡΟ)\s+"
    r"[\dIVXLCDMΑ-Ω]+[a-zA-ZΑ-Ωa-z]?)\b"
)



def split_articles(text: str, law_id: str, source_url: str, date: Optional[str] = None) -> list[dict]:
    if not text or len(text) < 40:
        return []
    matches = list(ARTICLE_SPLIT.finditer(text))
    if len(matches) < 2:
        return []
    docs = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        heading = chunk.split("\n", 1)[0][:200]
        docs.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": heading,
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "collector"}},
        })
        if len(docs) >= 4000:
            break
    return docs


def load_schema():
    global _schema
    with _schema_lock:
        if _schema is None:
            with SCHEMA_PATH.open(encoding="utf-8") as f:
                _schema = json.load(f)
        return _schema


def validate_record(record: dict) -> Optional[str]:
    try:
        import jsonschema
        jsonschema.Draft202012Validator(load_schema()).validate(record)
        return None
    except Exception as exc:
        return str(exc)


def existing_ids(cc: str) -> set[str]:
    d = ROOT / cc / "instruments"
    if not d.exists():
        return set()
    return {p.stem for p in d.glob("*.json")}


def _quality_reject(cc: str, record: dict):
    """env-gated quality filter (QUALITY_FILTER=1; module via QUALITY_FILTER_MODULE, default tip+29q). Fail-open on errors."""
    if os.environ.get("QUALITY_FILTER") != "1":
        return None
    try:
        import sys as _sys
        _lp = str(_SCRAPERS.parent / "logs")
        if _lp not in _sys.path:
            _sys.path.append(_lp)
        import importlib as _il
        _qf = _il.import_module(os.environ.get("QUALITY_FILTER_MODULE", "quality_filter_tip30a"))
        return _qf.classify_new(cc, record, None)  # classify + exact-duplicate vs tip+29p LIVE baseline
    except Exception:
        return None


# tip+29t WRITE-ONCE SAFETY: a closer must NEVER overwrite/modify an existing instrument file (baseline text or title).
# Active for the tip-pipeline CCs always (and for any CC when WRITE_ONCE=1). If the target exists, the record is written
# under a NEW unique id (<id>-wN) instead; the quality filter then judges the new row (dup_url/dup_content -> quarantine).
_WRITE_ONCE_CCS = {"bo", "az", "al", "ao", "do", "et", "ir", "mw", "zm", "la", "lk", "tn", "rs"}
_WRITE_ONCE_LOG = str(_SCRAPERS.parent / "logs" / "write_once_guard.log")


def _write_once_ident(cc: str, ident: str) -> str:
    if cc not in _WRITE_ONCE_CCS and os.environ.get("WRITE_ONCE") != "1":
        return ident
    idir = ROOT / cc / "instruments"
    if not (idir / f"{ident}.json").exists():
        return ident
    n = 2
    while (idir / f"{ident}-w{n}.json").exists():
        n += 1
    new_ident = f"{ident}-w{n}"
    try:
        with open(_WRITE_ONCE_LOG, "a", encoding="utf-8") as _fh:
            _fh.write(json.dumps({"ts": utcnow(), "cc": cc, "refused_overwrite": ident, "written_as": new_ident,
                                  "argv": " ".join(__import__("sys").argv)[:200]}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return new_ident


def write_instrument(cc: str, record: dict) -> Path:
    ident = _write_once_ident(cc, record["id"])
    if ident != record["id"]:
        record = dict(record, id=ident)
    dest = ROOT / cc / "instruments" / f"{ident}.json"
    if dest.exists():  # hard guard (race): never overwrite
        return dest
    _qr = _quality_reject(cc, record)
    if _qr and not dest.exists():
        qdest = ROOT / cc / os.environ.get("QUALITY_QDIR", "quarantine_quality_tip29q") / f"{ident}.json"
        qdest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(qdest, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        try:
            with open(os.environ.get("QUALITY_REJECT_LOG", str(_SCRAPERS.parent / "logs" / "quality_reject_tip29q.log")), "a", encoding="utf-8") as _fh:
                _fh.write(json.dumps({"cc": cc, "id": ident, "reason": _qr, "url": record.get("source_url")}, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return qdest
    if _qr:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    atomic_write(dest, body)
    index_line = {k: record.get(k) for k in INDEX_FIELDS if k != "path" and k != "bytes" and k != "article_count"}
    index_line["path"] = f"instruments/{ident}.json"
    index_line["article_count"] = record.get("article_count") or len(record.get("documents") or [])
    index_line["bytes"] = dest.stat().st_size
    index_line["id"] = ident
    with _index_lock:
        with (ROOT / cc / "index.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(index_line, ensure_ascii=False) + "\n")
    return dest


def log_failure(cc: str, payload: dict) -> None:
    path = ROOT / cc / "failures.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("retrieved_at", utcnow())
    with _fail_lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def append_catalog(cc: str, row: dict) -> None:
    path = ROOT / cc / "raw" / "catalog.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _index_lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def law_status_hist(cc: str) -> Counter:
    c: Counter = Counter()
    d = ROOT / cc / "instruments"
    if not d.exists():
        return c
    for p in d.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
            c[rec.get("law_status") or "unknown"] += 1
        except Exception:
            c["unknown"] += 1
    return c


def corpus_bytes(cc: str) -> int:
    d = ROOT / cc / "instruments"
    if not d.exists():
        return 0
    return sum(p.stat().st_size for p in d.glob("*.json"))


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    with path.open(encoding="utf-8") as f:
        for _ in f:
            n += 1
    return n


def write_summary(
    cc: str,
    *,
    country: str,
    source: str,
    source_urls: Iterable[str],
    license_text: str,
    discovered: int,
    fetched: int,
    skipped: int,
    failed: int,
    coverage: str,
    notes: str,
    last_run: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    last_run = last_run or utcnow()
    instr = ROOT / cc / "instruments"
    n_json = len(list(instr.glob("*.json"))) if instr.exists() else 0
    n_index = count_jsonl(ROOT / cc / "index.jsonl")
    hist = law_status_hist(cc)
    nbytes = corpus_bytes(cc)
    lines = [
        f"# {country} legislation corpus",
        "",
        f"- jurisdiction: {cc.upper()}",
        f"- source: {source}",
        f"- last_run_retrieved_at: {last_run} (PT: {pt_from_iso(last_run)})",
        f"- instruments_json: {n_json}",
        f"- index_jsonl_lines: {n_index}",
        f"- discovered: {discovered}",
        f"- fetched: {fetched}",
        f"- skipped: {skipped}",
        f"- failed: {failed}",
        "- law_status: " + ", ".join(f"{k}={v}" for k, v in sorted(hist.items())) if hist else "- law_status: (none)",
        f"- coverage: {coverage}",
        f"- total_json_bytes: {nbytes}",
        f"- license: {license_text}",
        "- source_urls:",
    ]
    for u in source_urls:
        lines.append(f"  - {u}")
    lines.append("- notes:")
    for n in (notes or "").splitlines():
        lines.append(f"  {n}")
    if extra:
        lines.append("")
        lines.append(extra)
    lines.append("")
    atomic_write(ROOT / cc / "SUMMARY.md", "\n".join(lines))


def base_record(
    *,
    cc: str,
    country: str,
    language: str,
    ident: str,
    title: str,
    text: str,
    source_url: str,
    source_type: str,
    license_text: str,
    collector: str,
    eli: Optional[str] = None,
    date: Optional[str] = None,
    official_identifier: Optional[str] = None,
    document_type: str = "statute",
    law_status: str = "current",
    is_current: Optional[bool] = True,
    documents: Optional[list] = None,
    extra_meta: Optional[dict] = None,
    extra_fields: Optional[dict] = None,
) -> dict:
    rid = slug_id(cc, ident)
    docs = documents if documents is not None else split_articles(text, rid, source_url, date)
    rec = {
        "schema_version": "collection_record.v1",
        "record_type": "law",
        "id": rid,
        "title": title or ident,
        "text": text or "",
        "source_url": source_url,
        "source_type": source_type,
        "date": date,
        "jurisdiction": cc.upper(),
        "country": country,
        "language": language,
        "eli": eli,
        "license": license_text,
        "retrieved_at": utcnow(),
        "identifier": official_identifier or ident,
        "official_identifier": official_identifier or ident,
        "law_identifier": official_identifier or ident,
        "document_type": document_type,
        "law_status": law_status,
        "is_current": is_current,
        "canonical_law_url": source_url,
        "article_count": len(docs),
        "article_extraction_status": "ok" if docs else "missing",
        "documents": docs,
        "metadata": {
            "collector": collector,
            "schema": "collection_record.v1",
            "source_host": re.sub(r"^https?://", "", source_url).split("/")[0] if source_url else "",
            "content_sha256": sha256_text(text or ""),
            "rights": {
                "not_legal_advice": True,
                "official_reuse_url": source_url,
                "license": license_text,
            },
            "text_extraction": {"source": "official", "backend": "collector"},
        },
    }
    if extra_meta:
        rec["metadata"].update(extra_meta)
    if extra_fields:
        rec.update(extra_fields)
    return rec


def ensure_dirs(cc: str) -> Path:
    root = ROOT / cc
    (root / "instruments").mkdir(parents=True, exist_ok=True)
    (root / "raw").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    return root


def iso_date(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    val = str(val).strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", val)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", val)
    if m:
        return m.group(1)
    m = re.match(r"^(\d{2})[./](\d{2})[./](\d{4})$", val)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None
