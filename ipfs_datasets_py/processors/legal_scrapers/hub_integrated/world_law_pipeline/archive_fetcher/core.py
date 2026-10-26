"""Shared web-archive fetcher: Common Crawl (CDX + WARC range) first, then Wayback (CDX + id_ raw).

Wraps the vendored ipfs_datasets_py legal_scrapers tooling (vendor/legal_scrapers, unmodified):
URLArchiveCache (URL key scheme + "newest good capture" text cache) and the CC/WARC + Wayback
fallback order of parallel_web_archiver / common_crawl_scraper, re-implemented synchronously here
because the originals need the HF pointer dataset, aiohttp and the full package.

Politeness: box-wide limiter in ratelimit.py (flock under archive/_ratelimit/: one in-flight request per host family,
exponential backoff on 429/5xx with a shared cool-down, descriptive User-Agent. Never touches
archive.today/archive.ph or anything behind a captcha. No proxies.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import os
import random
import re
import threading
import time
from contextlib import contextmanager
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional
from urllib.parse import quote, urlsplit

import requests

from . import ratelimit  # box-wide limiter (see README)
from . import deferral  # per-host cool-down + per-lane spacing (429/5xx -> ArchiveDeferred, no in-process retry)

log = logging.getLogger("world_law.archive")

HERE = Path(__file__).resolve().parent
DEFAULT_CACHE = Path(os.environ.get("WORLD_LAW_ARCHIVE_CACHE", str(HERE / "_cache")))
# 2026-10-11: lowered from 30 GB to 8 GB (disk pressure on the shared box); env var still overrides.
DEFAULT_CACHE_MAX_BYTES = int(os.environ.get("WORLD_LAW_ARCHIVE_CACHE_MAX_BYTES", str(8 * 1024**3)))
UA = os.environ.get(
    "WORLD_LAW_ARCHIVE_UA",
    "WorldLaw-ArchiveFetcher/1.0 (JusticeDAO world_municipal_law legal research; "
    "+https://github.com/endomorphosis/ipfs_datasets_py; low-rate, contact via repo issues)",
)
CC_INDEX = "https://index.commoncrawl.org"
CC_DATA = "https://data.commoncrawl.org"
WB_CDX = "https://web.archive.org/cdx/search/cdx"
WB_WEB = "https://web.archive.org/web"
FORBIDDEN_HOSTS = re.compile(r"(^|\.)(archive\.(today|ph|is|li|vn|fo|md))$", re.I)
TODAY = datetime(2026, 10, 10, tzinfo=timezone.utc)
STALE_DAYS = 730

# Rate limits live in ratelimit.py (box-wide, not configurable per process).

ERROR_PAGE_RE = re.compile(
    r"just\s+a\s+moment|cf-browser-verification|attention\s+required|checking\s+your\s+browser|"
    r"captcha|request\s+rejected|access\s+denied|403\s+forbidden|404\s+not\s+found|page\s+not\s+found|"
    r"страница\s+не\s+найдена|página\s+no\s+encontrada|halaman\s+tidak\s+ditemukan|"
    r"service\s+unavailable|bad\s+gateway|gateway\s+time-?out|internal\s+server\s+error|"
    r"the\s+requested\s+url\s+was\s+rejected|bobcmn|tspd_|"
    r"wayback\s+machine\s+has\s+not\s+archived|got\s+an\s+http\s+\d{3}\s+response\s+at\s+crawl\s+time",
    re.I,
)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_to_iso(ts: str) -> str:
    ts = (ts + "00000000000000")[:14]
    return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:14]}Z"


def is_stale(ts: str, today: datetime = TODAY, days: int = STALE_DAYS) -> bool:
    try:
        d = datetime.strptime((ts + "00000000000000")[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (today - d).days > days


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------
@dataclass
class Capture:
    source: str            # "commoncrawl" | "wayback"
    crawl_id: str          # CC crawl (CC-MAIN-2026-39) or "wayback"
    timestamp: str         # YYYYMMDDhhmmss
    original_url: str
    status: Optional[int] = None
    mime: Optional[str] = None
    digest: Optional[str] = None
    length: Optional[int] = None
    filename: Optional[str] = None   # CC WARC path
    offset: Optional[int] = None     # CC WARC offset
    truncated: Optional[str] = None  # CC index "truncated" field if any

    @property
    def replay_url(self) -> str:
        if self.source == "wayback":
            return f"{WB_WEB}/{self.timestamp}id_/{self.original_url}"
        return f"{CC_DATA}/{self.filename}#offset={self.offset}&length={self.length}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ArchivedDoc:
    original_url: str
    archive_source: str        # commoncrawl | wayback
    archive_crawl_id: str      # CC-MAIN-YYYY-WW | wayback
    archive_timestamp: str     # ISO 8601 UTC of the capture
    archive_url: str           # replay/WARC locator
    http_status: int
    content_type: str
    body: bytes = field(repr=False, default=b"")
    content_complete: bool = True
    possibly_stale: bool = False
    incomplete_reason: Optional[str] = None
    fetched_at: str = field(default_factory=utcnow)
    from_cache: bool = False
    # per-call fetch context (NOT dataclass fields: not cached / compared). Set by fetch_best / fetch_newest:
    # incomplete=True when another source failed transiently (a fuller/newer copy may exist later; see .deferral),
    # unrelated to content_complete (truncated body). fetch_info: FetchInfo.
    incomplete = False
    deferral = None
    fetch_info = None

    def provenance(self) -> Dict[str, Any]:
        """Fields every staged archived document must carry (see README §Provenance)."""
        return {
            "archive_source": self.archive_source,
            "archive_crawl_id": self.archive_crawl_id,
            "archive_timestamp": self.archive_timestamp,
            "archive_url": self.archive_url,
            "original_url": self.original_url,
            "content_complete": self.content_complete,
            "possibly_stale": self.possibly_stale,
        }

    def text_charset(self) -> str:
        if self.body[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return "utf-16"
        if self.body[:3] == b"\xef\xbb\xbf":
            return "utf-8-sig"
        m = re.search(r"charset=([\w-]+)", self.content_type or "", re.I)
        if m:
            return m.group(1)
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", self.body[:4000], re.I)
        return m.group(1).decode("ascii", "ignore") if m else "utf-8"

    def text(self) -> str:
        cs = self.text_charset()
        try:
            return self.body.decode(cs, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


class ArchiveError(Exception):
    """Base archive error. .kind names the failure type (set by the class / where raised, never parsed from the
    message); .status is the HTTP status when one caused it.
    .permanent is CONSERVATIVE (2026-10-18 r5): True only for an explicit 400/404/410 status or where the raiser
    passes permanent=True (Wayback 403 "blocked by site owner"). Everything else - no status, parse errors, unknown
    errors, 403 from *.commoncrawl.org (rate limiting), 5xx - is retryable, so a listing with such a gap never
    looks final."""
    kind = "error"
    PERMANENT_STATUSES = (400, 404, 410)

    def __init__(self, msg: str = "", *, status: Optional[int] = None, kind: Optional[str] = None,
                 permanent: Optional[bool] = None):
        super().__init__(msg)
        self.status = status
        if kind:
            self.kind = kind
        if permanent is not None:
            self._permanent = permanent

    @property
    def permanent(self) -> bool:
        p = self.__dict__.get("_permanent")
        if p is not None:
            return p
        return getattr(self, "status", None) in self.PERMANENT_STATUSES


class ArchiveTransient(ArchiveError):
    """Retries exhausted, family in backoff, or slot busy: never negatively cached; a later run retries.
    Typed subclasses (2026-10-18): ArchiveTimeout, ArchiveBreakerOpen, ArchiveBusy; a bad/garbled response is
    ArchiveTransient(kind="bad_response")."""
    kind = "transient"
    permanent = False


class ArchiveTimeout(ArchiveTransient):
    """Timeout / network error after the retry budget (timeout_retries)."""
    kind = "timeout"


class ArchiveBreakerOpen(ArchiveTransient):
    """The box-wide Wayback breaker is open: no request was sent."""
    kind = "breaker_open"


class ArchiveBusy(ArchiveTransient):
    """No limiter slot within max_wait / the family is backing off: no request was sent."""
    kind = "busy"


class ArchiveDeferred(ArchiveTransient):
    """Come back later: 429 / 5xx or a host cool-down (reason "throttled"/"cooldown"), and - for the high-level calls
    (fetch_best / fetch_newest / listings with on_deferred="raise") - also timeouts after the retry budget, slot busy
    and the Wayback breaker being open (reason "timeout" / "busy" / "breaker_open"; not_before = now + that family's
    backoff, or the breaker's next probe). NOT retried in-process. Requeue the item for `not_before` (epoch s;
    `retry_in` = seconds left). Subclass of ArchiveTransient, so existing `except ArchiveTransient` handlers keep
    working. 429/5xx deferrals are never counted as Wayback breaker failures (timeouts are)."""
    incomplete = True

    def __init__(self, msg: str, *, url: str = "", host: str = "", family: str = "", status=None,
                 retry_after: Optional[float] = None, not_before: float = 0.0, lane: str = "",
                 families: Optional[List[str]] = None, hosts: Optional[List[str]] = None,
                 partial: Optional[list] = None, reason: Optional[str] = None,
                 reasons: Optional[List[str]] = None, fetch_info: Optional["FetchInfo"] = None):
        super().__init__(msg, status=status)
        self.url, self.host, self.family, self.status = url, host, family, status
        self.retry_after, self.not_before, self.lane = retry_after, not_before, lane
        self.families = sorted(set(families or ([family] if family else [])))   # e.g. ["cc_index", "wayback"]
        self.hosts = sorted(set(hosts or ([host] if host else [])))
        self.partial = partial      # listings: captures collected before the deferral (incomplete!)
        self.reason = reason or ("cooldown" if status is None else "throttled")
        self.reasons = sorted(set(reasons or [self.reason]))
        self.kind = "deferred" if self.reason in ("throttled", "cooldown") else self.reason
        self.fetch_info = fetch_info  # per-call context of fetch_best/fetch_newest (see FetchInfo)

    @property
    def retry_in(self) -> float:
        return max(0.0, self.not_before - time.time())

    @property
    def sources(self) -> List[str]:
        """'commoncrawl' / 'wayback' for the deferred families."""
        return sorted({"commoncrawl" if f.startswith("cc_") else f for f in self.families})


def merge_deferrals(defs: List["ArchiveDeferred"], what: str, partial: Optional[list] = None) -> "ArchiveDeferred":
    """One ArchiveDeferred for several: earliest not_before (the soonest time any deferred source may be retried),
    union of families/hosts/reasons; host/status/url of that earliest one."""
    first = min(defs, key=lambda d: d.not_before or float("inf"))
    fams = sorted({f for d in defs for f in (d.families or [d.family]) if f})
    hosts = sorted({h for d in defs for h in (d.hosts or [d.host]) if h})
    reasons = sorted({r for d in defs for r in (getattr(d, "reasons", None) or [getattr(d, "reason", "throttled")])})
    return ArchiveDeferred(f"{what}: deferred ({','.join(fams)}; {','.join(reasons)}; hosts {','.join(hosts)}), "
                           f"retry in {max(0.0, first.not_before - time.time()):.0f}s: {first}",
                           url=first.url, host=first.host, family=first.family, status=first.status,
                           retry_after=first.retry_after, not_before=first.not_before, lane=first.lane,
                           families=fams, hosts=hosts, partial=partial, reasons=reasons,
                           reason=getattr(first, "reason", None))


class FetchInfo:
    """Per-call result context of fetch_best / fetch_newest (also attached to the returned doc as doc.fetch_info and
    to a raised ArchiveDeferred as e.fetch_info). Unlike fx.last_* it is not overwritten by nested calls.
      deferrals  [ArchiveDeferred]  every source failure that may succeed later (throttle, cool-down, timeout,
                                    busy, breaker open), already normalised to ArchiveDeferred
      errors     [str]              "<source>: <message>" of every failed capture / lookup (permanent ones too)
      cc_deferred / wb_deferred     counts of CC / Wayback captures or lookups deferred or skipped
      incomplete                    True if any source failed transiently: a doc returned anyway may not be the
                                    newest/complete copy - come back after deferral.not_before for a fuller one
      deferral                      merged ArchiveDeferred (earliest not_before) or None
      exception                     what fetch_best/fetch_newest raise (or would raise with raise_deferred=False)
      skip_sources {source: reason} sources skipped for the rest of the call after a timeout / throttle / busy /
                                    breaker-open failure; skipped {source: n} = captures skipped (no request sent)"""

    def __init__(self):
        self.deferrals: List[ArchiveDeferred] = []
        self.errors: List[str] = []
        self.cc_deferred = 0
        self.wb_deferred = 0
        self.exception: Optional[ArchiveDeferred] = None
        self.skip_sources: Dict[str, str] = {}   # source -> reason ("timeout"/"throttled"/"breaker_open"/"busy"...)
        self.skipped: Dict[str, int] = {}        # source -> captures skipped without a request in this call

    @property
    def incomplete(self) -> bool:
        return bool(self.deferrals)

    @property
    def deferral(self) -> Optional[ArchiveDeferred]:
        return merge_deferrals(self.deferrals, "fetch") if self.deferrals else None

    def sources_with_deferral(self) -> set:
        return {s for d in self.deferrals for s in d.sources}

    def add(self, d: ArchiveDeferred, source: str, n: int = 1) -> None:
        self.deferrals.append(d)
        if source == "wayback":
            self.wb_deferred += n
        else:
            self.cc_deferred += n

    def absorb(self, other: "FetchInfo") -> None:
        self.deferrals += other.deferrals
        self.errors += other.errors
        self.cc_deferred += other.cc_deferred
        self.wb_deferred += other.wb_deferred
        for k, v in other.skip_sources.items():
            self.skip_sources.setdefault(k, v)
        for k, v in other.skipped.items():
            self.skipped[k] = self.skipped.get(k, 0) + v

    def __repr__(self) -> str:
        return (f"FetchInfo(incomplete={self.incomplete}, cc_deferred={self.cc_deferred}, "
                f"wb_deferred={self.wb_deferred}, errors={len(self.errors)})")


class CaptureList(list):
    """list of Capture (fully list-compatible) with completeness flags:
      truncated        True if the listing may be INCOMPLETE: a source was deferred, timed out, was busy, the Wayback
                       breaker was open, a crawl failed, the crawl list was unavailable or the CC breaker stopped early
      truncated_reason first reason ("deferred", "timeout", "breaker_open", "busy", "crawl_failed",
                       "crawl_list_unavailable", "cc_breaker", "wb_failed")
      errors           ["<what>: <message>", ...] every failure seen
      deferred         True if .deferral is set (a transient failure with a retry time)
      deferral         merged ArchiveDeferred (earliest not_before) or None (permanent failures only)
      retryable_truncation       .deferral is set: re-list after .deferral.not_before
      complete_except_permanent  no retryable gap (complete, or only permanent gaps): final"""
    deferred = False
    truncated = False
    truncated_reason: Optional[str] = None
    deferral: Optional["ArchiveDeferred"] = None
    errors: tuple = ()

    @property
    def retryable_truncation(self) -> bool:
        """True if at least one gap may fill on a later run (.deferral set; retry after .deferral.not_before)."""
        return self.deferral is not None

    @property
    def complete_except_permanent(self) -> bool:
        """True if there is no retryable gap: the listing is complete, or its only gaps are permanent (a 4xx crawl,
        a permanently missing crawl index). Re-listing will not help; treat it as final."""
        return self.deferral is None

    def flag(self, d: Optional["ArchiveDeferred"], reason: Optional[str] = None) -> "CaptureList":
        if d is not None:
            self.deferral = d if self.deferral is None else merge_deferrals([self.deferral, d], "listing")
            self.deferred = True
            self.mark(reason or getattr(d, "reason", None) or "deferred", str(d))
        return self

    def mark(self, reason: str, err: Optional[str] = None) -> "CaptureList":
        self.truncated = True
        if self.truncated_reason is None:
            self.truncated_reason = reason
        if err:
            self.errors = list(self.errors) + [f"{reason}: {err}"[:500]]
        return self


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------
class DiskCache:
    """_cache/cdx/<k>.json  (CDX pages; TTL)  and  _cache/body/<k[:2]>/<k>.{json,bin.gz} (captures).

    Size-aware eviction: evict(max_bytes) removes least-recently-used body blobs (mtime touched
    on read) until the cache is under max_bytes. CDX pages are small and kept unless --all.
    """

    def __init__(self, root: Path, max_bytes: int = DEFAULT_CACHE_MAX_BYTES):
        self.root = Path(root)
        (self.root / "cdx").mkdir(parents=True, exist_ok=True)
        (self.root / "body").mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self._puts = 0

    @staticmethod
    def _atomic(path: Path, data: bytes) -> None:
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        with open(tmp, "wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)

    # CDX
    def cdx_get(self, key: str, ttl_days: float) -> Optional[Any]:
        p = self.root / "cdx" / f"{_sha(key)}.json"
        if not p.exists():
            return None
        if ttl_days >= 0 and time.time() - p.stat().st_mtime > ttl_days * 86400:
            return None
        try:
            return json.loads(p.read_text())["data"]
        except Exception:
            return None

    def cdx_put(self, key: str, data: Any) -> None:
        self._atomic(self.root / "cdx" / f"{_sha(key)}.json",
                     json.dumps({"key": key, "at": utcnow(), "data": data}).encode())

    # bodies
    def _bp(self, key: str):
        k = _sha(key)
        d = self.root / "body" / k[:2]
        return d, d / f"{k}.json", d / f"{k}.bin.gz"

    def body_get(self, key: str) -> Optional[ArchivedDoc]:
        d, mp, bp = self._bp(key)
        if not (mp.exists() and bp.exists()):
            return None
        try:
            meta = json.loads(mp.read_text())
            body = gzip.decompress(bp.read_bytes())
            os.utime(bp, None)
        except Exception:
            return None
        meta.pop("body_len", None)
        return ArchivedDoc(body=body, from_cache=True, **meta)

    def body_put(self, key: str, doc: ArchivedDoc) -> None:
        d, mp, bp = self._bp(key)
        d.mkdir(parents=True, exist_ok=True)
        meta = {k: v for k, v in asdict(doc).items() if k not in ("body", "from_cache")}
        meta["body_len"] = len(doc.body)
        self._atomic(bp, gzip.compress(doc.body, 6))
        self._atomic(mp, json.dumps(meta, ensure_ascii=False).encode())
        self._puts += 1
        if self._puts % 500 == 0:
            self.evict(self.max_bytes)

    def negative_get(self, key: str) -> Optional[str]:
        d, mp, _ = self._bp("NEG|" + key)
        if mp.exists():
            try:
                return json.loads(mp.read_text()).get("reason")
            except Exception:
                return None
        return None

    def negative_put(self, key: str, reason: str) -> None:
        d, mp, _ = self._bp("NEG|" + key)
        d.mkdir(parents=True, exist_ok=True)
        self._atomic(mp, json.dumps({"key": key, "reason": reason, "at": utcnow()}).encode())

    def size(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())

    def evict(self, max_bytes: int, include_cdx: bool = False) -> Dict[str, int]:
        files = []
        for p in (self.root / "body").rglob("*.bin.gz"):
            st = p.stat(); files.append((st.st_mtime, st.st_size, p))
        if include_cdx:
            for p in (self.root / "cdx").glob("*.json"):
                st = p.stat(); files.append((st.st_mtime, st.st_size, p))
        total = self.size()
        removed = freed = 0
        for mt, sz, p in sorted(files):
            if total <= max_bytes:
                break
            try:
                p.unlink(); total -= sz; freed += sz; removed += 1
                mp = p.with_name(p.name.replace(".bin.gz", ".json"))
                if mp.exists():
                    freed += mp.stat().st_size; total -= mp.stat().st_size; mp.unlink()
            except FileNotFoundError:
                pass
        return {"removed": removed, "freed": freed, "total": total}


# ---------------------------------------------------------------------------
# WARC parsing
# ---------------------------------------------------------------------------
def parse_warc_record(raw_gz: bytes) -> Dict[str, Any]:
    """Return {warc_headers, http_status, http_headers, body, complete, reason} from one gzip member."""
    try:
        raw = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw_gz)
    except zlib.error as e:
        raise ArchiveError(f"warc_gzip:{e}")
    head, _, rest = raw.partition(b"\r\n\r\n")
    wh: Dict[str, str] = {}
    for line in head.split(b"\r\n")[1:]:
        k, _, v = line.decode("latin-1").partition(":")
        wh[k.strip().lower()] = v.strip()
    clen = int(wh.get("content-length", "0") or 0)
    block = rest[:clen]
    complete, reason = True, None
    if len(block) < clen:
        complete, reason = False, f"warc_block_short:{len(block)}<{clen}"
    if wh.get("warc-truncated"):
        complete, reason = False, f"warc_truncated:{wh['warc-truncated']}"
    hhead, _, body = block.partition(b"\r\n\r\n")
    lines = hhead.split(b"\r\n")
    m = re.match(rb"HTTP/\S+\s+(\d{3})", lines[0] if lines else b"")
    status = int(m.group(1)) if m else 0
    hh: Dict[str, str] = {}
    for line in lines[1:]:
        k, _, v = line.decode("latin-1").partition(":")
        hh[k.strip().lower()] = v.strip()
    # CC stores the payload decoded but keeps original headers; respect a declared length
    declared = hh.get("content-length") or hh.get("x-crawler-content-length")
    if declared and declared.isdigit() and int(declared) > len(body) and "gzip" not in hh.get("x-crawler-content-encoding", ""):
        complete, reason = False, reason or f"body_short:{len(body)}<{declared}"
    return {"warc_headers": wh, "http_status": status, "http_headers": hh, "body": body,
            "complete": complete, "reason": reason}


# ---------------------------------------------------------------------------
# fetcher
# ---------------------------------------------------------------------------
class ArchiveFetcher:
    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE, *, user_agent: str = UA,
                 cc_crawls: int | List[str] = 12, use_cc: bool = True, use_wayback: bool = True,
                 max_body_bytes: int = 25 * 1024 * 1024, cdx_ttl_days: float = 14,
                 max_retries: int = 6, timeout: Optional[float] = None, cache_max_bytes: int = DEFAULT_CACHE_MAX_BYTES,
                 lane: Optional[str] = None, cc_max_wait: Optional[float] = None,
                 defer_on_throttle: Optional[bool] = None, raise_deferred: Optional[bool] = None,
                 listing_deferred: Optional[str] = None, timeout_retries: Optional[int] = None):
        """lane: fair-share lane for the box-wide limiter (default $ARCHIVE_LANE, see ratelimit.current_lane).
        timeout: override the read timeout (s) for every family; default ratelimit.TIMEOUTS
        (wayback 10+20 s, CC 10+30 s). cc_max_wait: Common Crawl is optional; if its slot is not free
        within this many seconds (queue or CC backoff) the CC step is skipped instead of stalling the
        worker (default 30 s, env WORLD_LAW_CC_MAX_WAIT).
        defer_on_throttle (default True, env WORLD_LAW_ARCHIVE_DEFER=0 to disable): on 429/5xx raise
        ArchiveDeferred at once (per-host cool-down, no breaker failure) instead of retrying the same URL.
        raise_deferred (default True, env WORLD_LAW_ARCHIVE_RAISE_DEFERRED=0): fetch_best / fetch_newest raise a merged
        ArchiveDeferred when they found nothing usable and a source was deferred (False: old return-None).
        listing_deferred (default "flag", env WORLD_LAW_ARCHIVE_LISTING_DEFERRED): cc_captures / list_captures on a
        deferral stop and return a CaptureList flagged .deferred/.truncated ("flag") or raise ArchiveDeferred
        with .partial ("raise"). Per-call override: on_deferred=.
        timeout_retries (default 1, env WORLD_LAW_ARCHIVE_TIMEOUT_RETRIES): retries of the same URL after a timeout /
        network error (each still counts toward the Wayback breaker and sets the family backoff, which the retry
        waits out); then ArchiveTransient."""
        self.cache = DiskCache(Path(cache_dir), cache_max_bytes)
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self.cc_crawls_spec = cc_crawls
        self.use_cc, self.use_wayback = use_cc, use_wayback
        self.max_body = max_body_bytes
        self.cdx_ttl = cdx_ttl_days
        self.max_retries = max_retries
        if defer_on_throttle is None:
            defer_on_throttle = os.environ.get("WORLD_LAW_ARCHIVE_DEFER", "1") != "0"
        self.defer_on_throttle = bool(defer_on_throttle)
        if raise_deferred is None:
            raise_deferred = os.environ.get("WORLD_LAW_ARCHIVE_RAISE_DEFERRED", "1") != "0"
        self.raise_deferred = bool(raise_deferred)
        self.listing_deferred = listing_deferred or os.environ.get("WORLD_LAW_ARCHIVE_LISTING_DEFERRED", "flag")
        if self.listing_deferred not in ("flag", "raise"):
            raise ValueError(f"listing_deferred must be 'flag' or 'raise', not {self.listing_deferred!r}")
        self.timeout_retries = int(timeout_retries if timeout_retries is not None
                                   else os.environ.get("WORLD_LAW_ARCHIVE_TIMEOUT_RETRIES", "1"))
        # deferral info of the last fetch_best / fetch_newest / cc_captures / list_captures call
        self.last_cc_deferred = 0          # Common Crawl captures/queries deferred
        self.last_deferral: Optional[ArchiveDeferred] = None   # merged; None if nothing was deferred
        self._soft_fail = False
        self.request_deadline = {"wayback": 90.0, "cc_index": 120.0, "cc_data": 120.0}  # wall clock per body
        self.lane = ratelimit.current_lane(lane)
        self.last_wb_deferred = 0   # Wayback captures skipped in the last fetch_best/fetch_newest (breaker open)
        self.cc_max_wait = float(cc_max_wait if cc_max_wait is not None else os.environ.get("WORLD_LAW_CC_MAX_WAIT", "30"))
        self.cc_index_retries = int(os.environ.get("WORLD_LAW_CC_INDEX_RETRIES", "3"))
        self.cc_breaker = int(os.environ.get("WORLD_LAW_CC_BREAKER", "2"))  # consecutive failed crawls -> skip rest
        self.timeout = timeout
        self._crawls: Optional[List[str]] = None
        self.stats: Dict[str, int] = {}
        try:  # reuse the repo's URL cache for "newest good capture" pointers + text
            import sys
            if str(HERE) not in sys.path:
                sys.path.insert(0, str(HERE))
            from vendor.legal_scrapers.url_archive_cache import URLArchiveCache
            self.url_cache = URLArchiveCache(metadata_dir=str(Path(cache_dir) / "url_archive_cache"),
                                             persist_to_ipfs=False)
        except Exception as e:  # pragma: no cover
            log.warning("URLArchiveCache unavailable: %s", e)
            self.url_cache = None

    # -- per-call breaker budget: one public call adds at most ONE breaker failure per family ---------------
    @contextmanager
    def _call_scope(self):
        tl = self.__dict__.setdefault("_tl", threading.local())
        outer = getattr(tl, "scope", None)
        if outer is None:
            tl.scope = set()
        try:
            yield
        finally:
            if outer is None:
                tl.scope = None

    def _brk_once(self, req, family: str) -> None:
        """Called before req.fail(): within a public call only the first failure per family reaches the box-wide
        breaker (later ones still pause the family, but are marked as already recorded)."""
        tl = self.__dict__.get("_tl")
        scope = getattr(tl, "scope", None) if tl is not None else None
        if scope is None:
            return
        if family in scope:
            if not getattr(req, "_brk_done", False):
                req._brk_done = True
                self._bump(f"{family}_breaker_fail_suppressed")
        else:
            scope.add(family)

    def _bump(self, k: str, n: int = 1) -> None:
        self.stats[k] = self.stats.get(k, 0) + n

    # -- HTTP with pacing/backoff -------------------------------------------------
    def _get(self, family: str, url: str, *, headers: Optional[dict] = None, stream: bool = False,
             ok_status=(200, 206), retry_404: bool = False) -> requests.Response:
        """Every archive request goes through ratelimit.slot(family): box-wide, one in flight,
        min spacing, shared exponential backoff on 429/5xx/network errors."""
        host = urlsplit(url).hostname or ""
        if FORBIDDEN_HOSTS.search(host):
            raise ArchiveError(f"forbidden archive host {host}")
        last = None
        tries = self.max_retries if family != "cc_index" else min(self.max_retries, self.cc_index_retries)
        ct, rt = ratelimit.TIMEOUTS[family]
        if self.timeout is not None:
            rt = self.timeout
        max_wait = self.cc_max_wait if family.startswith("cc_") else None
        soft = 0
        for attempt in range(tries):
            if self.defer_on_throttle:
                self._check_cooldown(family, host, url)
                deferral.lane_wait(self.lane, family)              # outside the slot: don't hold it while sleeping
            try:
                with ratelimit.slot(family, lane=self.lane, max_wait=max_wait) as req:
                    req.tag = url[:200]
                    if self.defer_on_throttle:
                        self._check_cooldown(family, host, url)     # cool-down may have started while queued
                        deferral.lane_wait(self.lane, family, stamp=True)
                    self._soft_fail = False
                    r, last = self._attempt(family, url, headers, (ct, rt), ok_status, req, attempt)
            except ratelimit.SlotBusy as e:
                self._bump(f"{family}_skipped_breaker" if isinstance(e, getattr(ratelimit, "WaybackDown", ())) else f"{family}_skipped_busy")
                cls = ArchiveBreakerOpen if isinstance(e, getattr(ratelimit, "WaybackDown", ())) else ArchiveBusy
                raise cls(f"{family} giving up (slot busy / backing off): {e}")
            if isinstance(last, ArchiveDeferred):
                raise last
            if r is not None:
                if self.defer_on_throttle:
                    deferral.record_success(host)
                return r
            if self._soft_fail:
                soft += 1
                if soft > self.timeout_retries:
                    self._bump(f"{family}_timeout_gaveup")
                    raise ArchiveTimeout(f"{family} giving up on {url[:160]} after {soft} timeout/network "
                                           f"failure(s) (timeout_retries={self.timeout_retries}): {last}")
        cls = ArchiveTimeout if self._soft_fail else ArchiveTransient
        raise cls(f"{family} giving up on {url[:160]}: {last}")

    def _attempt(self, family, url, headers, timeout, ok_status, req, attempt):
        """One request inside the slot. Returns (response, None) or (None, error) for a retry.
        Timeouts and network errors, 429 and 5xx (and 403 from data.commoncrawl.org) call req.fail(),
        which pauses only this family."""
        try:
            r = self.s.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
            r._wl_trunc = None
            if r.status_code in ok_status:
                buf = io.BytesIO()
                deadline = time.time() + self.request_deadline[family]
                try:
                    for chunk in r.iter_content(65536):
                        buf.write(chunk)
                        if buf.tell() > self.max_body:
                            r._wl_trunc = f"max_body_bytes:{self.max_body}"
                            break
                        if time.time() > deadline:
                            r._wl_trunc = f"deadline:{self.request_deadline[family]}s"
                            break
                except requests.RequestException as e:
                    if buf.tell() == 0:
                        raise
                    r._wl_trunc = f"stream_error:{type(e).__name__}"
                r._content = buf.getvalue()
            else:
                r._content = r.raw.read(200000, decode_content=True) if r.raw else b""
            r._content_consumed = True
            r.close()
        except requests.RequestException as e:
            last = f"{type(e).__name__}:{str(e)[:120]}"
            kind = "timeout" if isinstance(e, requests.Timeout) else "neterr"
            self._soft_fail = True
            self._bump(f"{family}_{kind}")
            self._brk_once(req, family)
            pause = req.fail(kind)
            log.warning("%s %s %s %s; %s paused %.0fs (attempt %d)", family, url[:120], kind, last, family, pause, attempt + 1)
            return None, last
        if r.status_code in ok_status:
            req.ok(r.status_code)
            self._bump(f"{family}_ok")
            return r, None
        cc403 = r.status_code == 403 and (urlsplit(url).hostname or "").endswith("commoncrawl.org")
        if self.defer_on_throttle and (r.status_code == 429 or r.status_code >= 500 or cc403):
            # No in-process retry and no breaker failure: per-host cool-down, caller requeues.
            ra_raw = r.headers.get("Retry-After")
            host = urlsplit(url).hostname or ""
            info = deferral.record_deferral(host, r.status_code, ra_raw, self.lane)
            req.outcome, req.status = "deferred", r.status_code   # not "ok": family state is not cleared
            req._brk_done = True                                  # never recorded as a breaker failure
            self._bump(f"{family}_{r.status_code}")
            self._bump(f"{family}_deferred")
            why = (f"Retry-After {ra_raw!r}" if info["retry_after"] is not None else f"no Retry-After, cool-down #{info['consec']}")
            log.warning("%s %s -> %s; deferred, host %s cooling %.0fs (%s)", family, url[:120], r.status_code, host,
                        info["wait"], why)
            return None, ArchiveDeferred(f"{family} {r.status_code} on {url[:160]}: deferred {info['wait']:.0f}s ({why})",
                                         url=url, host=host, family=family, status=r.status_code,
                                         retry_after=info["retry_after"], not_before=info["not_before"], lane=self.lane)
        if r.status_code == 429 or r.status_code >= 500 or cc403:
            ra = r.headers.get("Retry-After")
            self._brk_once(req, family)
            pause = req.fail(r.status_code, float(ra) if ra and ra.isdigit() else None)
            self._bump(f"{family}_{r.status_code}")
            log.warning("%s %s -> %s; %s paused %.0fs (attempt %d)", family, url[:120], r.status_code, family, pause, attempt + 1)
            return None, f"http_{r.status_code}"
        req.ok(r.status_code)
        self._bump(f"{family}_{r.status_code}")
        return r, None  # 404 etc. returned to caller

    def _check_cooldown(self, family: str, host: str, url: str) -> None:
        left = deferral.host_cooldown(host)
        if left > 0:
            self._bump(f"{family}_deferred_cooldown")
            self._bump(f"{family}_skipped_busy")      # no request sent (EUArchiveFetcher relies on this key)
            raise ArchiveDeferred(f"{family}: host {host} cooling down, {left:.0f}s left; deferred {url[:160]}",
                                  url=url, host=host, family=family, status=None, retry_after=None,
                                  not_before=time.time() + left, lane=self.lane)

    # -- Common Crawl ------------------------------------------------------------------
    def cc_crawls(self) -> List[str]:
        if self._crawls is None:
            if isinstance(self.cc_crawls_spec, list):
                self._crawls = list(self.cc_crawls_spec)
            else:
                data = self.cache.cdx_get("CC|collinfo", 1)
                if data is None:
                    r = self._get("cc_index", f"{CC_INDEX}/collinfo.json")
                    if r.status_code != 200:
                        raise ArchiveError(f"cc collinfo {r.status_code}", status=r.status_code)
                    try:
                        data = r.json()
                    except ValueError:
                        raise ArchiveTransient("cc collinfo non-json", kind="bad_response")
                    self.cache.cdx_put("CC|collinfo", data)
                ids = [c["id"] for c in data]  # newest first
                n = int(self.cc_crawls_spec)
                self._crawls = ids if n <= 0 else ids[:n]
        return self._crawls

    def _cc_query(self, crawl: str, url: str, match: str, *, limit_pages: int = 200,
                  filters: Optional[List[str]] = None) -> List[Capture]:
        base = f"{CC_INDEX}/{crawl}-index?url={quote(url, safe=':/*')}&matchType={match}&output=json"
        for flt in filters or []:  # pywb syntax: field:regex  (url, mime, status, ...)
            base += "&filter=" + quote(flt, safe=':*!~')
        fk = "|".join(filters or [])
        np_key = f"CC|{crawl}|{match}|{url}|{fk}|numpages"
        npg = self.cache.cdx_get(np_key, self.cdx_ttl if crawl == self.cc_crawls()[0] else 3650)
        if npg is None:
            r = self._get("cc_index", base + "&showNumPages=true", ok_status=(200,))
            if r.status_code == 404:
                npg = 0
            elif r.status_code != 200:
                raise ArchiveError(f"cc numpages {r.status_code}", status=r.status_code)
            else:
                try:
                    npg = int(json.loads(r.text.strip().splitlines()[-1]).get("pages", 0))
                except Exception:
                    npg = 0
            self.cache.cdx_put(np_key, npg)
        out: List[Capture] = []
        for page in range(min(npg, limit_pages)):
            key = f"CC|{crawl}|{match}|{url}|{fk}|p{page}"
            rows = self.cache.cdx_get(key, self.cdx_ttl if crawl == self.cc_crawls()[0] else 3650)
            if rows is None:
                r = self._get("cc_index", f"{base}&page={page}", ok_status=(200,))
                if r.status_code == 404:  # "No Captures found"
                    rows = []
                elif r.status_code != 200:
                    raise ArchiveError(f"cc page {r.status_code}", status=r.status_code)
                else:
                    rows = []
                    for line in r.text.splitlines():
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                self.cache.cdx_put(key, rows)
            for d in rows:
                try:
                    out.append(Capture("commoncrawl", crawl, d["timestamp"], d["url"],
                                       int(d.get("status") or 0) or None, d.get("mime-detected") or d.get("mime"),
                                       d.get("digest"), int(d.get("length") or 0), d.get("filename"),
                                       int(d.get("offset") or 0), d.get("truncated")))
                except (KeyError, ValueError):
                    continue
        return out

    # -- transient failure -> deferral ---------------------------------------------------------------
    FAMILY_HOST = {"wayback": "web.archive.org", "cc_index": "index.commoncrawl.org", "cc_data": "data.commoncrawl.org"}
    TRANSIENT_MIN_WAIT = 60.0

    def _as_deferral(self, e: Exception, family: str, url: str = "", reason: Optional[str] = None) -> "ArchiveDeferred":
        """Normalise a transient failure into an ArchiveDeferred with a retry time. The reason is the exception's
        typed .kind (ArchiveTimeout -> "timeout", ArchiveBreakerOpen -> "breaker_open", ArchiveBusy -> "busy",
        "bad_response", retryable HTTP ArchiveError -> "error"->"transient"); messages are never parsed.
        Throttle/cool-down deferrals are returned as they are; breaker open -> the breaker's next probe; anything
        else -> now + max(60 s, the family's current backoff); cc_breaker -> now + 1 h."""
        if isinstance(e, ArchiveDeferred):
            return e
        now = time.time()
        if reason is None:
            reason = getattr(e, "kind", None) if isinstance(e, ArchiveError) else None
            if not reason or reason == "error":
                st = getattr(e, "status", None)
                reason = "transient" if isinstance(e, ArchiveTransient) or (isinstance(st, int) and st >= 408) \
                    else "unknown_error"   # no status / parse error / code bug: retry in 1 h
        if reason == "breaker_open":
            try:
                b = ratelimit.breaker_status()
                nb = float(b.get("last_probe") or now) + float(getattr(ratelimit, "BREAKER_PROBE_EVERY", 1800.0))
            except Exception:  # noqa: BLE001
                nb = now + 1800.0
            nb = max(nb, now + self.TRANSIENT_MIN_WAIT)
        elif reason in ("cc_breaker", "unknown_error"):
            nb = now + 3600.0
        else:
            try:
                bo = ratelimit.backoff_remaining(family)
            except Exception:  # noqa: BLE001
                bo = 0.0
            nb = now + max(self.TRANSIENT_MIN_WAIT, bo)
        return ArchiveDeferred(f"{family} {reason}: {e}", url=url, host=self.FAMILY_HOST.get(family, ""),
                               family=family, status=None, not_before=nb, lane=self.lane, reason=reason)

    @staticmethod
    def _treason(d: "ArchiveDeferred") -> str:
        return "deferred" if d.reason in ("throttled", "cooldown") else d.reason

    def cc_captures(self, url: str, match: str = "exact", crawls: Optional[List[str]] = None,
                    on_error: str = "skip", filters: Optional[List[str]] = None,
                    on_deferred: Optional[str] = None) -> "CaptureList":
        """Common Crawl captures over the selected crawls. filters use Wayback names (original:/mimetype:/statuscode:)
        or pywb names (url:/mime:/status:).
        Returns a CaptureList; .truncated=True (+ .truncated_reason, .errors) whenever the listing may be incomplete:
        throttled/cooling down ("deferred"; stops the crawl loop), timeout / busy / breaker ("timeout", ...; the loop
        goes on), a failed crawl ("crawl_failed"), the crawl list unavailable ("crawl_list_unavailable") or the CC
        breaker stopping early ("cc_breaker"). Transient failures also set .deferral (with not_before).
        on_deferred "flag" (default, see listing_deferred) returns the flagged list; "raise" raises the merged
        ArchiveDeferred (.partial = captures so far) whenever .deferral is set (permanent failures stay flagged only).
        on_error="raise" raises at the first failure: transient ones as ArchiveDeferred (.partial), others as is."""
        mode = on_deferred or self.listing_deferred
        tr = {"original:": "url:", "mimetype:": "mime:", "statuscode:": "status:"}
        cfl = []
        for f in filters or []:
            for a, b in tr.items():
                if f.startswith(a):
                    f = b + f[len(a):]
            cfl.append(f)
        with self._call_scope():
            return self._cc_captures(url, match, crawls, on_error, cfl, mode)

    def _cc_captures(self, url, match, crawls, on_error, cfl, mode) -> "CaptureList":
        out = CaptureList()
        fails = 0
        timeout_counted = False

        def finish():
            self.last_cc_deferred = 1 if out.deferred else 0
            self.last_deferral = out.deferral
            if out.truncated:
                self._bump("cc_listing_truncated")
                log.warning("CC listing %s INCOMPLETE (%s%s); %d captures", url[:120], out.truncated_reason,
                            "" if out.retryable_truncation else ", permanent", len(out))
            if mode == "raise" and out.deferral is not None:
                raise merge_deferrals([out.deferral], f"cc_captures {url[:120]}", partial=list(out))
            return out

        def failed(e, what):
            """transient (typed ArchiveTransient, or an HTTP 5xx/408/429 ArchiveError) -> deferral + flag;
            permanent (4xx, other ArchiveError) -> marked only (no deferral: re-listing won't help)."""
            self._bump("cc_query_failed")
            if isinstance(e, ArchiveTransient) or not e.permanent:
                d = self._as_deferral(e, "cc_index", url)
                if isinstance(e, ArchiveDeferred):
                    self._bump("cc_query_deferred")
                if on_error == "raise":
                    raise merge_deferrals([d], f"cc_captures {url[:120]}", partial=list(out))
                out.flag(d, reason=self._treason(d) if what != "crawl_list_unavailable" else what)
                return d
            if on_error == "raise":
                raise e
            out.mark(what, f"permanent: {e}")
            return None
        try:
            crawl_list = crawls or self.cc_crawls()
        except Exception as e:  # noqa: BLE001 - parse errors / code bugs are retryable gaps, not crashes
            if not isinstance(e, ArchiveError):
                e = ArchiveError(f"crawl list: {type(e).__name__}: {e}")
            log.warning("CC crawl list unavailable: %s", e)
            failed(e, "crawl_list_unavailable")
            if not out.truncated:
                out.mark("crawl_list_unavailable", str(e))
            return finish()
        for i, crawl in enumerate(crawl_list):
            try:
                out.extend(self._cc_query(crawl, url, match, filters=cfl))
                fails = 0
            except Exception as e:  # noqa: BLE001
                if not isinstance(e, ArchiveError):
                    e = ArchiveError(f"crawl {crawl}: {type(e).__name__}: {e}")
                is_to = isinstance(e, ArchiveTimeout)
                if not is_to or not timeout_counted:           # timeouts count ONCE per call toward the CC breaker
                    fails += 1
                timeout_counted = timeout_counted or is_to
                log.warning("CC %s %s failed: %s", crawl, url, e)
                d = failed(e, "crawl_failed")
                if d is not None and isinstance(e, ArchiveDeferred):
                    break                                     # host cooling down: the other crawls would defer too
                if self.cc_breaker and fails >= self.cc_breaker and i + 1 < len(crawl_list):
                    self._bump("cc_breaker_open")
                    log.warning("CC index unavailable for %s after %d failed crawls; skipping the rest", url, fails)
                    # the remaining crawls were never asked: a retryable gap (retry in 1 h)
                    out.flag(self._as_deferral(ArchiveTransient(f"cc_breaker: stopped after {fails} consecutive "
                                                                f"failed crawls, {len(crawl_list) - i - 1} not queried"),
                                               "cc_index", url, reason="cc_breaker"), reason="cc_breaker")
                    break
        return finish()

    def fetch_cc(self, cap: Capture) -> ArchivedDoc:
        if not (cap.filename and cap.length):
            raise ArchiveError("cc capture without WARC pointer")
        end = cap.offset + cap.length - 1
        r = self._get("cc_data", f"{CC_DATA}/{cap.filename}", headers={"Range": f"bytes={cap.offset}-{end}"},
                      ok_status=(206, 200))
        if r.status_code not in (200, 206):
            raise ArchiveError(f"cc_data http {r.status_code}", status=r.status_code)
        raw = r.content
        if r.status_code == 200 and len(raw) > cap.length:  # server ignored Range
            raw = raw[cap.offset:cap.offset + cap.length]
        rec = parse_warc_record(raw)
        complete, reason = rec["complete"], rec["reason"]
        if cap.truncated:
            complete, reason = False, f"cc_index_truncated:{cap.truncated}"
        return ArchivedDoc(
            original_url=cap.original_url, archive_source="commoncrawl", archive_crawl_id=cap.crawl_id,
            archive_timestamp=ts_to_iso(cap.timestamp), archive_url=cap.replay_url,
            http_status=rec["http_status"], content_type=rec["http_headers"].get("content-type", cap.mime or ""),
            body=rec["body"], content_complete=complete, incomplete_reason=reason,
            possibly_stale=is_stale(cap.timestamp))

    # -- Wayback -----------------------------------------------------------------------
    def wb_captures(self, url: str, match: str = "exact", *, status200: bool = True,
                    collapse: Optional[str] = None, limit: Optional[int] = None,
                    from_ts: Optional[str] = None, to_ts: Optional[str] = None,
                    page_size: int = 10000, max_rows: int = 2_000_000,
                    filters: Optional[List[str]] = None) -> List[Capture]:
        """Wayback CDX. For prefix/domain listings pass collapse='urlkey' (oldest per URL) or
        'timestamp:4' (one row per URL per year; newest year = last row). limit<0 → newest N."""
        if not ratelimit.wayback_available():
            self._bump("wayback_skipped_breaker")
            raise ArchiveBreakerOpen("wayback breaker open (box-wide); skipped")
        params = [("url", url), ("matchType", match), ("output", "json"),
                  ("fl", "timestamp,original,mimetype,statuscode,digest,length")]
        if status200:
            params.append(("filter", "statuscode:200"))
        for flt in filters or []:  # e.g. "original:.*nota_detalle.*", "mimetype:text/html"
            params.append(("filter", flt))
        if collapse:
            params.append(("collapse", collapse))
        if from_ts:
            params.append(("from", from_ts))
        if to_ts:
            params.append(("to", to_ts))
        out: List[Capture] = []
        resume = None
        part = 0
        while True:
            p = list(params)
            if limit is not None:
                p.append(("limit", str(limit)))
            else:
                p += [("limit", str(page_size)), ("showResumeKey", "true")]
                if resume:
                    p.append(("resumeKey", resume))
            q = "&".join(f"{k}={quote(v, safe=':/*,!')}" for k, v in p)
            key = f"WB|{q}"
            data = self.cache.cdx_get(key, self.cdx_ttl)
            if data is None:
                r = self._get("wayback", f"{WB_CDX}?{q}", ok_status=(200,))
                if r.status_code != 200:
                    raise ArchiveError(f"wayback cdx {r.status_code}", status=r.status_code,
                                       permanent=True if r.status_code == 403 else None)
                try:
                    data = r.json() if r.text.strip() else []
                except ValueError:
                    raise ArchiveTransient("wayback cdx non-json", kind="bad_response")
                self.cache.cdx_put(key, data)
            rows = data[1:] if data and data[0] and data[0][0] == "timestamp" else data
            resume = None
            if limit is None and len(rows) >= 2 and rows[-2] == [] and len(rows[-1]) == 1:
                resume = rows[-1][0]; rows = rows[:-2]
            for row in rows:
                if len(row) < 6:
                    continue
                ts, orig, mime, st, dg, ln = row[:6]
                out.append(Capture("wayback", "wayback", ts, orig, int(st) if str(st).isdigit() else None,
                                   mime, dg, int(ln) if str(ln).isdigit() else None))
            part += 1
            if not resume or len(out) >= max_rows:
                break
            log.info("wayback cdx %s: %d rows so far (part %d)", url, len(out), part)
        return out

    def fetch_wayback(self, cap: Capture) -> ArchivedDoc:
        url = f"{WB_WEB}/{cap.timestamp}id_/{cap.original_url}"
        r = self._get("wayback", url, ok_status=(200,), stream=True)
        if r.status_code != 200:
            raise ArchiveError(f"wayback replay http {r.status_code}", status=r.status_code,
                               permanent=True if r.status_code == 403 else None)   # 403: excluded by site owner
        body = r.content
        complete, reason = (False, r._wl_trunc) if r._wl_trunc else (True, None)
        cl = r.headers.get("Content-Length")
        if complete and cl and cl.isdigit() and int(cl) > len(body) and not r.headers.get("Content-Encoding"):
            complete, reason = False, f"body_short:{len(body)}<{cl}"
        # Wayback echoes the original status in X-Archive-Orig-* / Link headers; use the CDX status
        mem_ts = r.headers.get("Memento-Datetime")
        ts = cap.timestamp
        m = re.search(r"/web/(\d{14})id_/", r.url or "")
        if m:
            ts = m.group(1)  # redirect to nearest capture
        return ArchivedDoc(
            original_url=cap.original_url, archive_source="wayback", archive_crawl_id="wayback",
            archive_timestamp=ts_to_iso(ts), archive_url=f"{WB_WEB}/{ts}id_/{cap.original_url}",
            http_status=cap.status or 200, content_type=r.headers.get("Content-Type", cap.mime or ""),
            body=body, content_complete=complete, incomplete_reason=reason, possibly_stale=is_stale(ts))

    # -- unified API -------------------------------------------------------------------
    def list_captures(self, url: str, match: str = "exact", *, sources: Iterable[str] = ("commoncrawl", "wayback"),
                      only_ok: bool = True, wb_collapse: Optional[str] = None, newest_per_url: bool = False,
                      cc_crawls: Optional[List[str]] = None, on_deferred: Optional[str] = None) -> "CaptureList":
        """All captures for url (match: exact|prefix|host|domain), newest first, CC + Wayback.
        url may also be a CDX wildcard like 'example.org/laws/*' (→ prefix).
        The CaptureList is flagged .truncated (+ .truncated_reason, .errors, .deferral for transient failures) when
        CC was incomplete (see cc_captures) or the Wayback CDX lookup failed: throttled ("deferred"), breaker open
        ("breaker_open"), timeout ("timeout"), busy, or another error ("wb_failed"). on_deferred "raise" raises the
        merged ArchiveDeferred (.partial) whenever a transient failure occurred."""
        with self._call_scope():
            return self._list_captures(url, match, sources, only_ok, wb_collapse, newest_per_url, cc_crawls,
                                       on_deferred or self.listing_deferred)

    def _list_captures(self, url, match, sources, only_ok, wb_collapse, newest_per_url, cc_crawls, mode):
        if url.endswith("*") and match == "exact":
            url, match = url.rstrip("*"), "prefix"
        caps: List[Capture] = []
        flags = CaptureList()
        cc_def = 0
        if "commoncrawl" in sources and self.use_cc:
            got = self.cc_captures(url, match, crawls=cc_crawls, on_deferred="flag")
            caps += got
            if got.truncated:
                if got.deferral is not None:
                    flags.flag(got.deferral, reason=got.truncated_reason)
                    flags.errors = list(flags.errors)[:-1]
                    cc_def = 1
                flags.mark(got.truncated_reason or "cc_incomplete")
                flags.errors = list(flags.errors) + [f"cc: {e}" for e in got.errors]
        if "wayback" in sources and self.use_wayback:
            try:
                caps += self.wb_captures(url, match, status200=only_ok, collapse=wb_collapse)
            except ArchiveTransient as e:
                d = self._as_deferral(e, "wayback", url)
                log.warning("wayback cdx %s %s: %s - listing INCOMPLETE", url, d.reason, e)
                self._bump("wb_query_deferred" if isinstance(e, ArchiveDeferred) else "wb_query_failed")
                flags.flag(d, reason=self._treason(d))
            except ArchiveError as e:
                log.warning("wayback cdx %s failed: %s - listing INCOMPLETE", url, e)
                self._bump("wb_query_failed")
                if e.permanent:
                    flags.mark("wb_failed", f"permanent: {e}")
                else:                                         # e.g. a 5xx that came back as a plain ArchiveError
                    flags.flag(self._as_deferral(e, "wayback", url), reason="wb_failed")
        if only_ok:
            caps = [c for c in caps if c.status in (200, None)]
        caps.sort(key=lambda c: (c.timestamp, c.source == "commoncrawl"), reverse=True)
        if newest_per_url:
            seen, uniq = set(), []
            for c in caps:
                k = canonical_url(c.original_url)
                if k not in seen:
                    seen.add(k); uniq.append(c)
            caps = uniq
        out = CaptureList(caps)
        out.deferred, out.truncated, out.truncated_reason = flags.deferred, flags.truncated, flags.truncated_reason
        out.deferral, out.errors = flags.deferral, list(flags.errors)
        self.last_cc_deferred = cc_def
        self.last_deferral = out.deferral
        if out.deferral is not None and mode == "raise":
            raise merge_deferrals([out.deferral], f"list_captures {url[:120]}", partial=list(caps))
        return out

    def fetch_capture(self, cap: Capture) -> ArchivedDoc:
        key = f"{cap.source}|{cap.crawl_id}|{cap.timestamp}|{cap.original_url}"
        doc = self.cache.body_get(key)
        if doc is not None:
            self._bump("cache_hit")
            return doc
        neg = self.cache.negative_get(key)
        if neg:
            raise ArchiveError(f"cached failure: {neg}")
        try:
            doc = self.fetch_cc(cap) if cap.source == "commoncrawl" else self.fetch_wayback(cap)
        except ArchiveError as e:
            if not isinstance(e, ArchiveTransient) and "giving up" not in str(e):  # permanent-ish failures only
                self.cache.negative_put(key, str(e)[:300])
            raise
        self.cache.body_put(key, doc)
        return doc

    def _set_last(self, info: "FetchInfo", wb_count: Optional[int] = None) -> None:
        """Backward-compatible instance attributes. UNRELIABLE with nested calls (each public call overwrites them):
        prefer doc.fetch_info / e.fetch_info / fetch_best_ex()."""
        self.last_wb_deferred = info.wb_deferred if wb_count is None else wb_count
        self.last_cc_deferred = info.cc_deferred
        self.last_deferral = info.deferral

    @staticmethod
    def _attach(doc: "ArchivedDoc", info: "FetchInfo") -> "ArchivedDoc":
        doc.fetch_info = info
        doc.incomplete = info.incomplete
        doc.deferral = info.deferral
        return doc

    def fetch_best_ex(self, caps: List[Capture], *, validator=None, max_tries: int = 4,
                      policy: str = "cc_first", newer_wb_days: int = 365, raise_deferred: bool = False,
                      _skip: Optional[Dict[str, str]] = None) -> tuple:
        """Like fetch_best but returns (doc_or_None, FetchInfo). info.exception is the ArchiveDeferred fetch_best
        would raise (doc is None and a source failed transiently). raise_deferred defaults to False here (NOT the
        fetcher default): pass True to raise info.exception instead of returning it (the exception carries the same
        info as e.fetch_info). Unknown keyword arguments raise TypeError."""
        with self._call_scope():
            doc, info = self._fetch_best_ex(caps, validator, max_tries, policy, newer_wb_days, _skip)
        if raise_deferred and doc is None and info.exception is not None:
            raise info.exception
        return doc, info

    def _fetch_best_ex(self, caps, validator, max_tries, policy, newer_wb_days, _skip):
        caps = [c for c in caps if c.status in (200, None)]
        cc = sorted([c for c in caps if c.source == "commoncrawl"], key=lambda c: c.timestamp, reverse=True)
        wb = sorted([c for c in caps if c.source == "wayback"], key=lambda c: c.timestamp, reverse=True)
        if policy == "newest":
            order = sorted(caps, key=lambda c: (c.timestamp, c.source == "commoncrawl"), reverse=True)
        else:
            order = cc + wb
            if cc and wb:
                gap = (_ts_dt(wb[0].timestamp) - _ts_dt(cc[0].timestamp)).days
                if gap > newer_wb_days:
                    order = wb[:1] + cc + wb[1:]
        info = FetchInfo()
        if wb and not ratelimit.wayback_available():          # breaker open: Common Crawl only
            order = [c for c in order if c.source != "wayback"]
            info.add(self._as_deferral(ArchiveBreakerOpen("wayback breaker open (box-wide); skipped"), "wayback",
                                       wb[0].replay_url), "wayback", len(wb))
            info.errors.append("wayback: breaker open")
            info.skip_sources["wayback"] = "breaker_open"
            info.skipped["wayback"] = info.skipped.get("wayback", 0) + len(wb)
            self._bump("wayback_skipped_breaker", len(wb))
        partial: Optional[ArchivedDoc] = None
        result: Optional[ArchivedDoc] = None
        tried = 0
        for src, why in (_skip or {}).items():               # carried over from an earlier step of the same call
            info.skip_sources.setdefault(src, why)
        skip_src = info.skip_sources
        for cap in order:
            if cap.source in skip_src:                        # timeout / throttled / busy / breaker: no request
                if cap.source == "wayback":
                    info.wb_deferred += 1
                else:
                    info.cc_deferred += 1
                info.skipped[cap.source] = info.skipped.get(cap.source, 0) + 1
                if cap.source not in info.sources_with_deferral():
                    info.add(self._as_deferral(ArchiveTransient(f"{cap.source} skipped ({skip_src[cap.source]}) "
                                                                f"earlier in this call"),
                                               "wayback" if cap.source == "wayback" else "cc_data", cap.replay_url,
                                               reason=skip_src[cap.source]), cap.source, 0)
                self._bump(f"{cap.source}_skipped_{skip_src[cap.source]}")
                continue
            if tried >= max_tries:
                break
            tried += 1
            try:
                doc = self.fetch_capture(cap)
            except ArchiveTransient as e:                     # incl. ArchiveDeferred
                fam = "wayback" if cap.source == "wayback" else "cc_data"
                d = self._as_deferral(e, fam, cap.replay_url)
                log.info("capture %s %s %s: %s", d.reason, cap.source, cap.original_url[:100], e)
                info.add(d, cap.source)
                info.errors.append(f"{cap.source}: {e}"[:300])
                # any transient failure skips the rest of that source for this call: after a timeout (its single
                # retry already spent) the source is not hit again, so one item can't trip the breaker alone
                skip_src[cap.source] = d.reason
                if isinstance(e, ArchiveDeferred) or isinstance(e, (ArchiveBreakerOpen, ArchiveBusy)):
                    tried -= 1                                # no request was answered: not a real try
                continue
            except ArchiveError as e:
                log.info("capture failed %s %s: %s", cap.source, cap.original_url[:100], e)
                info.errors.append(f"{cap.source}: {e}"[:300])
                continue
            if not good_doc(doc):
                self._bump("bad_page")
                continue
            if validator is not None and not validator(doc):
                self._bump("validator_reject")
                continue
            if not doc.content_complete:
                partial = partial or doc
                continue  # keep looking for a complete copy
            result = doc
            break
        if result is None:
            result = partial
        if result is None and info.deferrals:
            info.exception = merge_deferrals(info.deferrals, "fetch_best")
            info.exception.fetch_info = info
        self._set_last(info)
        if result is not None:
            self._attach(result, info)
        return result, info

    def fetch_best(self, caps: List[Capture], *, validator=None, max_tries: int = 4,
                   policy: str = "cc_first", newer_wb_days: int = 365,
                   raise_deferred: Optional[bool] = None) -> Optional[ArchivedDoc]:
        """Try captures until one is good (2xx, not an error/challenge page, validator OK).

        policy 'cc_first' (default): CC captures newest-first, then Wayback newest-first — unless
        the newest Wayback capture is > newer_wb_days newer than the newest CC capture, in which
        case Wayback goes first. policy 'newest': strictly by timestamp.

        None means strictly: every tried source answered and nothing usable was found. If nothing usable was found
        and any source failed transiently - throttled / cooling down, timed out after the retry budget, slot busy, or
        Wayback breaker open - ONE merged ArchiveDeferred is raised (earliest not_before, .families, .hosts,
        .reasons, .fetch_info), unless raise_deferred=False (ctor / env default) which returns None.
        A doc found despite such failures is returned with doc.incomplete=True, doc.deferral, doc.fetch_info
        (come back after doc.deferral.not_before for a fuller copy). After a throttle deferral or breaker skip the
        rest of that source is skipped without a request and does not use up max_tries. After a timeout (once its
        single retry is spent) the rest of that source is skipped too (the timed-out capture counts as one try);
        skips are in info.skip_sources / info.skipped. One call adds at most one breaker failure per family.
        fx.last_deferral / last_cc_deferred / last_wb_deferred are kept for compatibility but are overwritten by
        nested calls - prefer doc.fetch_info, e.fetch_info or fetch_best_ex().
        """
        doc, info = self.fetch_best_ex(caps, validator=validator, max_tries=max_tries, policy=policy,
                                       newer_wb_days=newer_wb_days, raise_deferred=False)
        rd = self.raise_deferred if raise_deferred is None else raise_deferred
        if doc is None and info.exception is not None and rd:
            raise info.exception
        return doc

    def fetch_newest_ex(self, url: str, *, validator=None, policy: str = "cc_first", max_tries: int = 4,
                        wb_newest_n: int = 5, raise_deferred: bool = False) -> tuple:
        """Like fetch_newest but returns (doc_or_None, FetchInfo); same raise_deferred / TypeError rules as
        fetch_best_ex (default False: never raises for deferrals)."""
        with self._call_scope():
            doc, info = self._fetch_newest_ex(url, validator, policy, max_tries, wb_newest_n)
        if raise_deferred and doc is None and info.exception is not None:
            raise info.exception
        return doc, info

    def _fetch_newest_ex(self, url, validator, policy, max_tries, wb_newest_n):
        info = FetchInfo()
        caps: List[Capture] = []
        if self.use_cc:
            got = self.cc_captures(url, "exact", on_deferred="flag")
            caps += got
            if got.deferral is not None:
                info.add(got.deferral, "commoncrawl")
            info.errors += [f"cc listing: {e}" for e in got.errors]
        doc = None
        if caps:
            doc, i1 = self._fetch_best_ex(caps, validator, max_tries, policy, 365, None)
            info.absorb(i1)
            if doc is not None and doc.content_complete and not doc.possibly_stale:
                return self._newest_done(doc, info, url)
        if self.use_wayback:
            wb: List[Capture] = []
            try:
                wb = self.wb_captures(url, "exact", limit=-wb_newest_n)
            except ArchiveError as e:
                log.warning("wayback cdx %s failed: %s", url, e)
                info.errors.append(f"wayback cdx: {e}"[:300])
                if isinstance(e, ArchiveTransient) or not e.permanent:
                    info.add(self._as_deferral(e, "wayback", url), "wayback")
            if wb:
                doc2, i2 = self._fetch_best_ex(caps + wb, validator, max_tries + 2, policy, 365, dict(info.skip_sources))
                info.absorb(i2)
                if doc2 is not None:
                    doc = doc2
        return self._newest_done(doc, info, url)

    def _newest_done(self, doc, info, url):
        if doc is not None:
            self._set_last(info, wb_count=0)                  # old fetch_newest: 0 when a doc was found
            self._attach(doc, info)
            self._remember(doc)
            return doc, info
        if info.deferrals:
            info.exception = merge_deferrals(info.deferrals, f"fetch_newest {url[:120]}")
            info.exception.fetch_info = info
        self._set_last(info)
        return None, info

    def fetch_newest(self, url: str, *, validator=None, policy: str = "cc_first", max_tries: int = 4,
                     wb_newest_n: int = 5, raise_deferred: Optional[bool] = None) -> Optional[ArchivedDoc]:
        """Newest good capture of one exact URL (CC first, then Wayback). Same contract as fetch_best, covering the
        CDX lookups too: None = every source answered and nothing usable; any transient failure (throttle, cool-down,
        timeout, busy, breaker open) with nothing usable -> merged ArchiveDeferred (unless raise_deferred=False);
        a doc found anyway carries doc.incomplete / doc.deferral / doc.fetch_info."""
        doc, info = self.fetch_newest_ex(url, validator=validator, policy=policy, max_tries=max_tries,
                                         wb_newest_n=wb_newest_n, raise_deferred=False)
        rd = self.raise_deferred if raise_deferred is None else raise_deferred
        if doc is None and info.exception is not None and rd:
            raise info.exception
        return doc

    def _remember(self, doc: ArchivedDoc) -> None:
        if self.url_cache is None or not doc.body:
            return
        try:
            import asyncio
            asyncio.run(self.url_cache.put(url=doc.original_url, content=doc.archive_url,
                                           source=doc.archive_source, metadata=doc.provenance()))
        except Exception as e:  # pragma: no cover
            log.debug("url_cache put failed: %s", e)


def _ts_dt(ts: str) -> datetime:
    return datetime.strptime((ts + "00000000000000")[:14], "%Y%m%d%H%M%S")


def canonical_url(u: str) -> str:
    """Scheme/www/port/trailing-slash-insensitive key for de-duplicating captures of the same page."""
    u = u.strip()
    u = re.sub(r"^https?://", "", u, flags=re.I)
    u = re.sub(r"^www\.", "", u, flags=re.I)
    host, _, rest = u.partition("/")
    host = host.lower().split(":")[0]
    rest = rest.split("#")[0]
    return host + "/" + rest.rstrip("/")


def good_doc(doc: ArchivedDoc, min_bytes: int = 200) -> bool:
    if not (200 <= (doc.http_status or 200) < 300):
        return False
    if len(doc.body) < min_bytes:
        return False
    ct = (doc.content_type or "").lower()
    if "pdf" in ct or doc.body[:5] == b"%PDF-":
        return True
    head = doc.body[:20000].decode("utf-8", "ignore")
    title = re.search(r"<title[^>]*>(.*?)</title>", head, re.I | re.S)
    blob = (title.group(1) if title else "") + " " + head[:3000]
    if ERROR_PAGE_RE.search(blob) and len(doc.body) < 60000:
        return False
    return True
