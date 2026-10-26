#!/usr/bin/env python3
"""German archive pass (Common Crawl first, then Wayback) for places the live pass could not get.

Uses ONLY the shared /workspace/world_law/pipeline/archive ArchiveFetcher (box-wide limiter, lane 'web').
Never makes a live request to a municipal site: candidate links come from (a) section pages cached
by the live pass (local _raw store) and (b) ARCHIVED copies of seed/section pages.

Targets: _state/place_results.jsonl with status in TARGET_STATUSES.
Output : staging/web/DE/<place_key>.archive<UTC>p<NNNN>.jsonl via archive.StagedWriter (validated, atomic),
         provenance sidecar in staging/web/_archive_provenance/DE/.
State  : staging/web/DE/_archive_work/{done.jsonl,_progress.json,pending_docs.jsonl}; logs staging/web/DE/_logs/archive_*.log

Deferral (0.3, 2026-10-18): the fetcher raises ArchiveDeferred (429/5xx or host cool-down) instead of retrying.
A Wayback deferral requeues the place (if discovery was incomplete) or only the deferred doc URLs of the place
(docs already staged stay staged; state in pending_docs.jsonl survives restarts) for no earlier than
e.not_before, and the worker moves on. Deferred places are never written to done.jsonl nor counted as failures.
Fresh places wait while Wayback is cooling down; when everything is cooling the workers sleep until the earliest
not_before (cap IDLE_WAIT_CAP_S). Deferrals are logged at most once per place per cool-down, and the fetcher's
own warnings are rate-limited per message template.
0.4 (fetcher of 12:10 PT): fetch_best/fetch_newest RAISE ArchiveDeferred when nothing usable was found and CC or
Wayback was throttled (None = genuine miss); cc_captures/list_captures return CaptureLists flagged .truncated when a
source was deferred mid-listing -> such listings are incomplete: not cached, and the doc / place is requeued instead
of being counted as no_capture / no_candidates. CC deferrals are requeued too (for their not_before); only a Wayback
cool-down makes a worker skip the rest of a place (CC-throttled docs can still come from Wayback).
0.5 (fetcher round 3, 12:25 PT): timeouts / busy / open breaker with nothing usable also RAISE ArchiveDeferred
(-> requeue; breaker reason keeps the breaker kind and retries at the next probe); fx.last_wb_deferred is no longer
read (None = genuine miss). Listings are requeued only when they carry a .deferral; a permanent .truncated is
accepted. CC-only deferrals are accepted after MAX_CC_DEFER_ROUNDS requeued segments (recorded, no endless loop).
Docs returned with doc.incomplete=True are staged and listed in _archive_work/incomplete_docs.jsonl. The idle log
line is written only when the idle state changes.
0.6 (2026-10-19): candidate doc URLs already published by the older endomorphosis/justicedao repos or
world_municipal_law (tools/old_url_check, keys dedup_index.norm_url) are skipped before any archive request
(skipped_covered); a place whose candidates are all covered finishes as covered_elsewhere. Shared Amt/VG sites
(AmtIndex): another member town's own law is skipped, a shared doc is staged once (under the Amt place_id if the
registry has one, else the first member; claims in _archive_work/shared_amt_claims.jsonl). Fetcher round 4/5:
CaptureList.retryable_truncation, typed ArchiveTimeout/ArchiveBreakerOpen/ArchiveBusy for listing errors,
'unknown_error' gaps accepted after MAX_UNKNOWN_ROUNDS.
The Wayback breaker deferral (README "Wayback circuit breaker") keeps its 30-min / breaker-closed retry.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import argparse, collections, gzip, json, logging, os, re, signal, sqlite3, subprocess, sys, threading, time, traceback, types
import urllib.parse
from pathlib import Path

sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
os.environ.setdefault("ARCHIVE_LANE", "web")
from archive import ArchiveFetcher, StagedWriter, provenance_fields  # noqa: E402
from archive.core import canonical_url, ArchiveError, ArchiveTransient, ArchiveDeferred  # noqa: E402
try:  # fetcher round 4 typed exceptions (all subclass ArchiveTransient)
    from archive.core import ArchiveTimeout, ArchiveBreakerOpen, ArchiveBusy  # noqa: E402
except ImportError:  # pragma: no cover
    ArchiveTimeout = ArchiveBreakerOpen = ArchiveBusy = ()
from archive import ratelimit, deferral  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.argv_saved = list(sys.argv)
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("de_crawler", HERE / "de_ortsrecht_crawler.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)
from rfc9309 import Robots  # noqa: E402  (vendored, same dir)
from bs4 import BeautifulSoup  # noqa: E402

S = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/web/DE"))
STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/web"))
WORK = S / "_archive_work"
TMP = WORK / "_tmp"
LOGS = S / "_logs"
ROBOTS_DIR = S / "_state" / "robots"
ROBOT_STATUSES = {"docs_robots_disallowed", "robots_disallowed", "robots_disallowed_partial"}
ERROR_STATUSES = {"http_error", "unreachable", "timeout"}
TARGET_STATUSES = ROBOT_STATUSES | ERROR_STATUSES
MAX_DOCS_PER_PLACE = 60
MAX_EXACT_LOOKUPS = 20          # per-URL CDX lookups per place (when no listing covers a URL)
MAX_ARCHIVED_PAGES = 8          # archived HTML pages parsed per place
MAX_LISTING_ROWS = 20000
PLACE_BUDGET_S = 40 * 60
SOURCE_PLATFORM = C.SOURCE_PLATFORM
VERSION = "de_archive_pass/0.6"
QUAR = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/quarantine/web/DE/deferred_wayback"))
DEFER_RETRY_S = 30 * 60   # matches BREAKER_PROBE_EVERY
SHARED_HOSTS = re.compile(r"(^|\.)verwaltungsportal\.de$|(^|\.)komm\.one$|(^|\.)kdo\.de$|(^|\.)ekom21\.de$|(^|\.)wittich\.de$")

_log_lock = threading.Lock()
LOG_FH = None


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    with _log_lock:
        if LOG_FH:
            LOG_FH.write(line + "\n"); LOG_FH.flush()
        else:
            print(line, flush=True)


# ------------------------------------------------------------------ robots (crawl-time records only)
_rob_cache: dict = {}
_rob_lock = threading.Lock()


def crawl_robots(url: str):
    """Return (disallowed: bool|None, basis: str) using ONLY the robots.txt recorded at live-crawl time."""
    p = urllib.parse.urlsplit(url)
    host = p.netloc.lower()
    key = f"{p.scheme}_{host}"
    with _rob_lock:
        st = _rob_cache.get(key)
    if st is None:
        fn = ROBOTS_DIR / (re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json")
        if not fn.exists():  # try the other scheme
            alt = ("https" if p.scheme == "http" else "http") + "_" + host
            fn = ROBOTS_DIR / (re.sub(r"[^A-Za-z0-9_.-]", "_", alt) + ".json")
        if fn.exists():
            try:
                d = json.loads(fn.read_text())
                st = (d.get("state"), d.get("note") or "", Robots(d.get("text") or "") if d.get("state") == "ok" else None,
                      d.get("fetched_at"), d.get("status"))
            except Exception:
                st = ("none", "", None, None, None)
        else:
            st = ("none", "", None, None, None)
        with _rob_lock:
            if len(_rob_cache) > 3000:
                _rob_cache.clear()
            _rob_cache[key] = st
    state, note, rp, at, code = st
    if state == "ok":
        try:
            ok = rp.can_fetch(C.UA_TOKEN, url)
        except Exception:
            ok = False
        return (not ok), (f"robots.txt at crawl {at}: " + ("Disallow matches path" if not ok else "allowed"))
    if state == "allow_all":
        return False, f"robots.txt {code} at crawl {at} (4xx = allow)"
    if state in ("disallow_all", "unreachable"):
        return True, f"robots.txt {note or state} at crawl {at} (5xx/unreachable = disallow-all policy)"
    return None, "no robots.txt record from live crawl"


# ------------------------------------------------------------------ helpers
def load_results():
    res = {}
    with (S / "_state/place_results.jsonl").open() as fh:
        for l in fh:
            try:
                r = json.loads(l)
            except Exception:
                continue
            res[r["place_id"]] = r   # last record wins
    return res


def is_doc_url(u: str) -> bool:
    return bool(C.DOC_EXT.search(u)) or bool(C.DOWNLOAD_HINT.search(u) and re.search(r"\.(pdf|doc|docx)\b", u, re.I))


def links_of(html: str, base: str):
    soup = BeautifulSoup(html, "lxml")
    try:
        b = soup.find("base", href=True)
        basehref = urllib.parse.urljoin(base, b["href"]) if b else base
        out, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.lower().startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
                continue
            u = C.canon(urllib.parse.urljoin(basehref, href))
            if not u or u in seen:
                continue
            seen.add(u)
            t = a.get_text(" ", strip=True) or a.get("title", "") or ""
            out.append((u, re.sub(r"\s+", " ", t)[:300]))
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        return out, title
    finally:
        soup.decompose()


def doc_link_ok(text: str, url: str, from_section: bool) -> bool:
    lf = C._fold(text + " " + urllib.parse.unquote(url))
    if re.search(r"bebauungsplan|b-plan|bplan|flachennutzungsplan|formular|antrag|flyer|broschure|"
                 r"datenschutz|impressum|stellenaus|haushaltsplan|jahresabschluss|wahlbekannt|"
                 r"tagesordnung|niederschrift|protokoll|einladung|planzeichnung|begrundung", lf):
        return False
    if C.GAZETTE_RE.search(lf) and not re.search(r"satzung|verordnung", lf):
        return False
    if C.DOC_RE.search(lf):
        return True
    return from_section


def doc_priority(text: str, url: str) -> int:
    t = C._fold(text + " " + urllib.parse.unquote(url))
    s = 0
    if re.search(r"hauptsatzung|satzung|verordnung|ortsrecht", t): s += 10
    if re.search(r"gebuhr|gebuehr|beitrag|steuer|benutzung|ordnung", t): s += 5
    if re.search(r"haushaltssatzung", t): s -= 6
    return s


def pdf_to_text(body: bytes) -> tuple[str, str]:
    TMP.mkdir(parents=True, exist_ok=True)
    p = TMP / f"a{os.getpid()}_{threading.get_ident()}.pdf"
    try:
        with p.open("wb") as f:
            f.write(body)
        return C.pdf_text(str(p))
    finally:
        p.unlink(missing_ok=True)


def listing_key(url: str) -> tuple[str, str]:
    """(prefix, kind). For shared vendor file hosts use the place-specific directory, else the host."""
    p = urllib.parse.urlsplit(url)
    host = p.netloc.lower()
    if SHARED_HOSTS.search(host):
        segs = [x for x in p.path.split("/") if x]
        # verwaltungsportal: /dateien/seitengenerator/<hash>/file.pdf -> keep /dateien/seitengenerator/<hash>/
        if len(segs) >= 4 and len(segs[2]) >= 16:
            return host + "/" + "/".join(segs[:3]) + "/", "prefix"
        return "", "exact"
    return host + "/", "prefix"


# ------------------------------------------------------------------ throttle deferral (ArchiveDeferred, 2026-10-18)
WB_HOST = "web.archive.org"
DEFER_MIN_S = 5.0          # never requeue sooner than this, even with Retry-After: 0
IDLE_WAIT_CAP_S = 60.0     # max single sleep while every item is cooling down (re-checks breaker/cooldown files)
CONT_F = WORK / "pending_docs.jsonl"   # continuation state of partially staged places (last line per place wins)


def _is_deferral(e) -> bool:
    """ArchiveDeferred (429/5xx or host cool-down, CC or Wayback): requeue for e.not_before."""
    return isinstance(e, ArchiveDeferred)


def _truncated(caps):
    """A listing to requeue: CaptureList.retryable_truncation (round 4; = a .deferral is set). A listing that is
    .complete_except_permanent (only 400/404/410 gaps) is final and accepted, never requeued."""
    rt = getattr(caps, "retryable_truncation", None)
    if rt is not None:
        return bool(rt)
    return getattr(caps, "deferral", None) is not None


def _reasons(e) -> set:
    return {r for r in (getattr(e, "reasons", None) or [getattr(e, "reason", None) or getattr(e, "kind", None)]) if r}


def _transient_deferral(e, family: str = "wayback"):
    """Typed ArchiveTransient raised by a listing call (wb_captures / list_captures) -> (kind, ArchiveDeferred|None).
    Breaker open -> 'breaker' (retried at the next probe / when the breaker lets Wayback through); timeout / busy /
    bad response -> 'throttle' in >= 60 s; anything else -> legacy breaker path (None)."""
    k = getattr(e, "kind", None)
    if (ArchiveBreakerOpen and isinstance(e, ArchiveBreakerOpen)) or k == "breaker_open":
        return "breaker", None
    if (ArchiveTimeout and isinstance(e, (ArchiveTimeout, ArchiveBusy))) or k in ("timeout", "busy", "bad_response"):
        return "throttle", ArchiveDeferred(str(e), family=family, host=WB_HOST if family == "wayback" else "",
                                           not_before=time.time() + 60.0, reason=k or "transient")
    return "breaker", None


def _cc_only(e) -> bool:
    fams = getattr(e, "families", None) or [getattr(e, "family", "") or ""]
    return bool(fams) and all(str(f).startswith("cc_") for f in fams)


def _defer_kind(e) -> str:
    """'breaker' if the only reason is the open Wayback breaker, else 'throttle' (429/5xx, cool-down, timeout, busy)."""
    rs = set(getattr(e, "reasons", None) or [getattr(e, "reason", None)])
    return "breaker" if rs == {"breaker_open"} else "throttle"


MAX_CC_DEFER_ROUNDS = 3    # CC-only deferrals of one place: after this many requeued segments accept what we have
MAX_UNKNOWN_ROUNDS = 3     # round 5: 'unknown_error' gaps retry hourly forever in the module; lanes must cap them
_inc_lock = threading.Lock()


def record_incomplete(rec: dict) -> None:
    """_archive_work/incomplete_docs.jsonl: staged docs with doc.incomplete=True (another source failed, a better
    capture may exist) and listings/docs accepted partial after MAX_CC_DEFER_ROUNDS. Re-check later; never looped on."""
    rec = {"t": C.now_iso(), **rec}
    with _inc_lock:
        with (WORK / "incomplete_docs.jsonl").open("a") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def _deferral_info(d) -> dict:
    if d is None:
        return {}
    return {"families": list(getattr(d, "families", None) or []), "hosts": list(getattr(d, "hosts", None) or []),
            "reasons": list(getattr(d, "reasons", None) or ([getattr(d, "reason", None)] if getattr(d, "reason", None) else [])),
            "not_before": getattr(d, "not_before", None)}


def wb_not_before(e=None) -> float:
    """Epoch time before which a throttled item must not be retried (e.not_before; else the Wayback cool-down)."""
    nb = float(getattr(e, "not_before", 0) or 0) if e is not None else 0.0
    if not nb:
        try:
            nb = time.time() + deferral.host_cooldown(WB_HOST)
        except Exception:
            nb = 0.0
    return max(nb, time.time() + DEFER_MIN_S)


def wb_cooling() -> float:
    try:
        return deferral.host_cooldown(WB_HOST)
    except Exception:
        return 0.0


# ------------------------------------------------------------------ already-covered URLs (2026-10-19)
TOOLS_DIR = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/tools")


class CoverChecker:
    """Is a doc URL already published by the older endomorphosis/justicedao repos or world_municipal_law?
    tools/old_url_check.UrlChecker (read-only sqlite, keys dedup_index.norm_url). Imports fine in the pipeline
    venv, so no CLI pre-pass is needed. ONE instance per process (sqlite page cache only, a few MB), shared by the
    workers behind a lock. Fails OPEN: if the index is missing or unreadable (e.g. being rebuilt) the URL is
    fetched as before and cover_check_err is counted."""

    def __init__(self, enabled: bool = True):
        self.lock = threading.Lock()
        self.c = None
        self.err = None
        self.stats = collections.Counter()
        self._memo: "collections.OrderedDict[str, object]" = collections.OrderedDict()
        if not enabled:
            self.err = "disabled"
            return
        try:
            if TOOLS_DIR not in sys.path:
                sys.path.insert(0, TOOLS_DIR)
            from old_url_check import UrlChecker   # noqa: WPS433
            self.c = UrlChecker()
            if not self.c.old.exists() and (self.c.pub is None or not self.c.pub.exists()):
                self.err = "index files missing"
                self.c = None
        except Exception as e:   # noqa: BLE001
            self.err = f"{type(e).__name__}: {e}"
            self.c = None

    @property
    def active(self) -> bool:
        return self.c is not None

    def covered(self, url: str):
        """'endomorphosis/...' | 'world_municipal_law:<ref>' | None (not covered / unknown)."""
        if self.c is None:
            return None
        with self.lock:
            if url in self._memo:
                self._memo.move_to_end(url)
                return self._memo[url]
            try:
                cov = self.c.covered(url)
                self.stats["cover_checks"] += 1
            except Exception as e:   # noqa: BLE001  (sqlite locked / rebuilt underneath us)
                self.stats["cover_check_err"] += 1
                if self.stats["cover_check_err"] in (1, 100, 1000):
                    log(f"  cover check error ({self.stats['cover_check_err']}x, failing open): {type(e).__name__}: {e}")
                return None
            self._memo[url] = cov
            if len(self._memo) > 20000:
                self._memo.popitem(last=False)
            return cov

    def close(self):
        if self.c is not None:
            try:
                self.c.close()
            except Exception:
                pass


COVER = CoverChecker(enabled=False)   # replaced in main(); tests may set their own


# ------------------------------------------------------------------ shared Amt / Verbandsgemeinde sites (2026-10-19)
AMT_MAX_MEMBERS = 60   # largest VGs have ~45 member towns; more places on one host = a portal
AMT_HOST_RE = re.compile(r"(^|[.-])(amt|aemter|vg|vgem|verbandsgemeinde|samtgemeinde|sg|verwaltungsgemeinschaft|vwg|"
                         r"gvv|verwaltungsverband|gemeindeverwaltungsverband)[-.]", re.I)
AMT_WORD_RE = re.compile(r"\b(vg|verbandsgemeinde|amt|amtes|samtgemeinde|verwaltungsgemeinschaft|verwaltungsverband|"
                         r"gemeindeverwaltungsverband)\b")


def _host(u: str) -> str:
    h = (urllib.parse.urlsplit(u).hostname or "").lower().rstrip(".")
    return h[4:] if h.startswith("www.") else h


def _name_re(name: str):
    nf = C._fold(name or "")
    nf = re.sub(r"\s*\(.*?\)\s*", " ", nf).strip()          # "Neustadt (Wied)" -> "neustadt"
    return re.compile(r"(^|[^a-z])" + re.escape(nf) + r"([^a-z]|$)") if len(nf) >= 3 else None


class AmtIndex:
    """Which hosts are shared Amt/VG sites, and who owns a shared (not member-specific) document there.

    A host is a shared Amt/VG site if >= 2 DE target places use it (homepage / code links) or its name looks like
    one (amt-*, vg-*, verbandsgemeinde-*, samtgemeinde-* ...); vendor file hosts (SHARED_HOSTS) are not.
    Member-specific test = the live crawler's member_mode rule (de_ortsrecht_crawler): a doc whose link text / file
    name names a member town belongs to that town; one that names no member (or names the VG/Amt) is the Amt's.
    Owner of a shared doc: the Amt's own place_id when the registry has one for that host (xdedup.is_amt names,
    or _archive_work/amt_map.json {host: place_id}); otherwise the first member place that stages it (persistent
    claim in _archive_work/shared_amt_claims.jsonl), so it is staged ONCE, not under every member."""

    def __init__(self, targets, amt_map: dict = None, claims_path: Path = None):
        self.host_places = collections.defaultdict(set)
        self.names = {}
        self.info = {}
        for t in targets:
            pid = t["place_id"]
            self.names[pid] = t.get("name") or ""
            self.info[pid] = t
            hosts = {_host(t.get("homepage") or "")} | {_host(l.get("url", "")) for l in (t.get("code_links") or [])}
            for h in hosts:
                if h and not SHARED_HOSTS.search(h):
                    self.host_places[h].add(pid)
        self._re = {}
        self.amt_place = {}                       # host -> registry place_id of the Amt itself
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
            import xdedup as XD                   # same Amt/VG name rule as the normalizer's canonical choice
            is_amt = XD.is_amt
        except Exception:                          # noqa: BLE001
            is_amt = lambda n: bool(re.match(r"(?i)(amt|verbandsgemeinde|vg|samtgemeinde|verwaltungsgemeinschaft)\b", n or ""))
        for pid, nm in self.names.items():
            if is_amt(nm):
                h = _host(self.info[pid].get("homepage") or "")
                if h:
                    self.amt_place[h] = pid
        for h, pid in (amt_map or {}).items():
            self.amt_place[h.lower().removeprefix("www.")] = pid
        self.claims_path = claims_path
        self.claims = {}                          # norm_url -> owner place_id
        self.lock = threading.Lock()
        if claims_path and claims_path.exists():
            for l in claims_path.open():
                try:
                    d = json.loads(l)
                    self.claims.setdefault(d["norm"], d["owner"])
                except Exception:
                    continue

    def _rx(self, pid):
        if pid not in self._re:
            self._re[pid] = _name_re(self.names.get(pid, ""))
        return self._re[pid]

    def shared(self, host: str) -> bool:
        if not host or SHARED_HOSTS.search(host):
            return False
        n = len(self.host_places.get(host, ()))
        if n > AMT_MAX_MEMBERS:               # state/district-wide portal, not one Amt/VG
            return False
        return n >= 2 or bool(AMT_HOST_RE.search(host))

    def classify(self, place_id: str, url: str, anchor: str):
        """('own'|'other_member'|'shared', owner_place_id|None)."""
        h = _host(url)
        if not self.shared(h):
            return "own", None
        seg = C._fold((anchor or "") + " " + urllib.parse.unquote(url).split("?")[0].rstrip("/").rsplit("/", 1)[-1])
        own = self._rx(place_id)
        if own is not None and own.search(seg):
            return "own", None
        for pid in sorted(self.host_places.get(h, ())):
            if pid == place_id:
                continue
            rx = self._rx(pid)
            if rx is not None and rx.search(seg) and not AMT_WORD_RE.search(seg):
                return "other_member", pid
        return "shared", self.amt_place.get(h)

    def claimed_by(self, norm: str):
        with self.lock:
            return self.claims.get(norm)

    def claim(self, norm: str, owner: str, by_place: str, url: str) -> bool:
        """Atomically claim a shared doc for owner; False if somebody else already has it."""
        with self.lock:
            cur = self.claims.get(norm)
            if cur is not None:
                return cur == owner
            self.claims[norm] = owner
            if self.claims_path:
                with self.claims_path.open("a") as fh:
                    fh.write(json.dumps({"t": C.now_iso(), "norm": norm, "owner": owner, "by": by_place,
                                         "url": url, "host": _host(url)}, ensure_ascii=False) + "\n")
            return True


AMT = AmtIndex([])   # replaced in main(); tests may set their own


def norm_key(url: str) -> str:
    """dedup_index.norm_url (same key as the covered-URL index); falls back to the crawler's canon()."""
    try:
        import dedup_index as DX   # pipeline dir is on sys.path
        return DX.norm_url(url) or C.canon(url)
    except Exception:   # noqa: BLE001
        return C.canon(url)


# ------------------------------------------------------------------ per place
RES_COUNTERS = ("docs", "pdf_docs", "html_docs", "cc_docs", "wb_docs", "robots_policy_docs", "no_capture",
                "fetch_fail", "no_text", "wb_deferred_docs", "incomplete_docs",
                "skipped_covered", "skipped_shared_amt", "skipped_other_member", "shared_amt_docs", "amt_attributed_docs")
SKIP_KEYS = ("skipped_covered", "skipped_shared_amt", "skipped_other_member")
RUN_SKIPS = collections.Counter()      # this process, incl. places not finished yet (progress.json)
_skips_lock = threading.Lock()


def bump_skip(k: str):
    with _skips_lock:
        RUN_SKIPS[k] += 1


class PlaceArchiver:
    """One place. run() does collect + a doc segment; if doc URLs are deferred (Wayback throttle or breaker)
    they stay in self.pending and the caller requeues this object (or its saved state, see state()/from_state),
    and a later run() processes only those docs. Docs already staged stay staged (no duplicates, no quarantine)."""

    def __init__(self, fx: ArchiveFetcher, target: dict, result: dict, db_path: Path, stop: threading.Event,
                 cont: dict = None):
        self.fx, self.t, self.r, self.stop = fx, target, result, stop
        self.db_path = db_path
        self.db = sqlite3.connect(str(db_path), timeout=60)
        self.listings: dict = {}          # (prefix, html) -> {canonical_url: [Capture]}  (complete listings only)
        self._partial: dict = {}          # (prefix, html) -> (map, kind): incomplete listings, this segment only
        self.start = time.time()
        self.stats = collections.Counter()
        self.wb_deferred = 0              # Wayback work skipped (breaker open / transient): place must be retried
        self.throttled = 0                # Wayback ArchiveDeferred events this segment
        self.throttle_nb = 0.0            # latest not_before seen this segment
        self._last_throttled = False
        self._last_kind = None
        self._last_exc = None
        self._cc_seg = False              # a CC-only deferral happened this segment
        self.cc_rounds = 0                # requeued segments with CC-only deferrals (see MAX_CC_DEFER_ROUNDS)
        self.unknown_rounds = 0           # requeued segments whose deferrals were all 'unknown_error'
        self._unk_seg = False
        self.amt_files: list = []         # files staged under an Amt place_id (shared Amt/VG docs)
        self.seg_kinds: set = set()
        self.group = "robots" if result["status"] in ROBOT_STATUSES else "error"
        # continuation state
        self.collected = False
        self.pending: list = []           # [[url, anchor, section, kind]]  kind: throttle|breaker|stop
        self.seen_ids: set = set()
        self.n = 0
        self.lookups = [0]
        self.files: list = []
        self.segments = 0
        self.candidates = 0
        self.acc = {k: 0 for k in RES_COUNTERS}
        if cont:
            self.collected = True
            self.pending = [list(p) for p in cont.get("pending") or []]
            self.seen_ids = set(cont.get("seen_ids") or [])
            self.n = int(cont.get("n", 0) or 0)
            self.lookups = [int(cont.get("lookups", 0) or 0)]
            self.files = list(cont.get("files") or [])
            self.segments = int(cont.get("segments", 0) or 0)
            self.candidates = int(cont.get("candidates", 0) or 0)
            self.cc_rounds = int(cont.get("cc_rounds", 0) or 0)
            self.unknown_rounds = int(cont.get("unknown_rounds", 0) or 0)
            self.amt_files = list(cont.get("amt_files") or [])
            for k in RES_COUNTERS:
                self.acc[k] = int((cont.get("acc") or {}).get(k, 0) or 0)
            self.stats.update(cont.get("stats") or {})

    def state(self) -> dict:
        return {"place_id": self.t["place_id"], "t": C.now_iso(), "pending": self.pending, "seen_ids": sorted(self.seen_ids),
                "n": self.n, "lookups": self.lookups[0], "files": self.files, "segments": self.segments,
                "candidates": self.candidates, "acc": self.acc, "stats": dict(self.stats), "cc_rounds": self.cc_rounds,
                "unknown_rounds": self.unknown_rounds, "amt_files": self.amt_files}

    def rebind(self, fx: ArchiveFetcher):
        """Reuse a requeued archiver from another worker thread (own fetcher + sqlite connection)."""
        self.fx = fx
        try:
            self.db.close()
        except Exception:
            pass
        self.db = sqlite3.connect(str(self.db_path), timeout=60)

    def close(self):
        try:
            self.db.close()
        except Exception:
            pass

    def _amt_writer(self, pid: str) -> StagedWriter:
        if not hasattr(self, "_amt_w"):
            self._amt_w = {}
        if pid not in self._amt_w:
            self._amt_w[pid] = StagedWriter(STAGE, "DE", pid, batch_prefix="archive", chunk=25, max_bytes=30 * 1024 * 1024)
        return self._amt_w[pid]

    def _flush_amt(self):
        for aw in getattr(self, "_amt_w", {}).values():
            aw.flush()
            self.amt_files += [Path(p).name for p in aw.written if Path(p).name not in self.amt_files]
        self._amt_w = {}

    def budget(self):
        return (time.time() - self.start) < PLACE_BUDGET_S and not self.stop.is_set()

    # -- deferral detection (fetcher round 3): fetch_best/fetch_newest RAISE ArchiveDeferred for throttles, timeouts,
    #    busy slots and the open Wayback breaker when nothing usable was found (None = every source answered: a
    #    genuine miss); listings carry .deferral for the same transient causes. This is the ONLY deferral path for
    #    docs: fx.last_wb_deferred is not consulted (unreliable per README), so nothing is handled twice. --
    def _accept_cc(self, e) -> bool:
        """Accept a retryable gap as final (no more requeues): CC-only after MAX_CC_DEFER_ROUNDS, or only
        'unknown_error' reasons after MAX_UNKNOWN_ROUNDS (README round 5)."""
        if _cc_only(e) and self.cc_rounds >= MAX_CC_DEFER_ROUNDS:
            return True
        rs = _reasons(e)
        return bool(rs) and rs <= {"unknown_error"} and self.unknown_rounds >= MAX_UNKNOWN_ROUNDS

    def _note_throttle(self, e=None):
        self.throttled += 1
        self.stats["throttle_events"] += 1
        kind = _defer_kind(e) if e is not None else "throttle"
        self.seg_kinds.add(kind)
        self._last_kind = kind
        if e is not None and _cc_only(e):
            self._cc_seg = True
        if e is not None and _reasons(e) and _reasons(e) <= {"unknown_error"}:
            self._unk_seg = True
        fams = getattr(e, "families", None) or ([getattr(e, "family", "")] if e is not None else [])
        for f in fams or ["?"]:
            self.stats[f"throttle_{f}"] += 1
        for r in (getattr(e, "reasons", None) or [getattr(e, "reason", None)]) if e is not None else []:
            if r:
                self.stats[f"defer_reason_{r}"] += 1
        self.throttle_nb = max(self.throttle_nb, wb_not_before(e))

    def _guard(self, fn, *a, **k):
        self._last_throttled, self._last_kind, self._last_exc = False, None, None
        try:
            out = fn(*a, **k)
        except ArchiveDeferred as e:
            self._last_exc = e
            if self._accept_cc(e):
                self.stats["cc_deferral_accepted"] += 1     # caller treats it as a plain failure, no requeue
            else:
                self._last_throttled = True
                self._note_throttle(e)
            raise
        d = getattr(out, "deferral", None)
        if d is not None:
            if self._accept_cc(d):
                self.stats["cc_listing_partial_accepted"] += 1
                self._last_exc = d
            else:
                self._last_throttled = True
                self._note_throttle(d)
        elif getattr(out, "truncated", False):
            self.stats["listing_truncated_permanent"] += 1
        return out

    # -- listing captures by prefix (CC first, then Wayback) --
    def listing(self, prefix: str, html: bool = False):
        """Returns (map, deferred_kind). An incomplete listing (Wayback throttled / breaker) is not cached."""
        key = (prefix, html)
        if key in self.listings:
            return self.listings[key], None
        if key in self._partial:          # incomplete earlier in this segment: don't re-list, still deferred
            return self._partial[key]
        caps = []
        dk = None
        flt_cc = ["mime:text/html", "status:200"] if html else ["mime:application/pdf", "status:200"]
        if html:
            flt_wb = ["mimetype:text/html", r"original:(?i).*(ortsrecht|satzung|rechtsgrundlage|verordnung|stadtrecht|ortsgesetz|bekanntmachung).*"]
            flt_cc.append(r"url:(?i).*(ortsrecht|satzung|rechtsgrundlage|verordnung|stadtrecht|ortsgesetz|bekanntmachung).*")
        else:
            flt_wb = ["mimetype:application/pdf"]
        try:
            caps += self._guard(self.fx.cc_captures, prefix, "prefix", filters=flt_cc)
            self.stats["cc_listings"] += 1
            if self._last_throttled:
                self.stats["cc_listing_deferred"] += 1
                dk = self._last_kind      # CC listing truncated by a deferral: incomplete, don't cache
            elif self._last_exc is not None:
                record_incomplete({"kind": "listing_partial_cc", "place_id": self.t["place_id"], "prefix": prefix,
                                   "html": html, "cc_rounds": self.cc_rounds, **_deferral_info(self._last_exc)})
        except Exception as e:
            if self._last_throttled:
                self.stats["cc_listing_deferred"] += 1
                dk = self._last_kind
            else:
                self.stats["cc_listing_err"] += 1
                if not isinstance(e, ArchiveTransient):
                    log(f"  cc listing err {prefix}: {e}")
        try:
            caps += self._guard(self.fx.wb_captures, prefix, "prefix", filters=flt_wb, collapse="timestamp:4",
                                max_rows=MAX_LISTING_ROWS)
            self.stats["wb_listings"] += 1
        except Exception as e:
            if self._last_throttled:
                self.stats["wb_listing_deferred"] += 1
                dk = "throttle" if "throttle" in (dk, self._last_kind) else self._last_kind
            else:
                self.stats["wb_listing_err"] += 1
                if isinstance(e, ArchiveTransient) or not ratelimit.wayback_available():
                    tk, td = _transient_deferral(e) if isinstance(e, ArchiveTransient) else ("breaker", None)
                    if td is not None:            # timeout / busy: short requeue, not the 30-min breaker wait
                        self._note_throttle(td)
                        dk = "throttle"
                    else:
                        self.wb_deferred += 1
                        dk = dk or "breaker"
                else:
                    log(f"  wb listing err {prefix}: {e}")
        m = collections.defaultdict(list)
        for c in caps:
            if c.status not in (200, None):
                continue
            m[canonical_url(c.original_url)].append(c)
        if dk is None:
            self.listings[key] = m
        else:
            self._partial[key] = (m, dk)
        return m, dk

    def caps_for(self, url: str, lookups: list):
        """(captures, deferred_kind)."""
        pref, kind = listing_key(url)
        if kind == "prefix":
            m, dk = self.listing(pref)
            return m.get(canonical_url(url), []), dk
        if lookups[0] >= MAX_EXACT_LOOKUPS:
            self.stats["exact_lookup_cap"] += 1
            return [], None
        lookups[0] += 1
        dk = None
        try:
            caps = self._guard(self.fx.list_captures, url, "exact")
        except Exception as e:
            if not self._last_throttled and not isinstance(e, ArchiveTransient):
                log(f"  exact lookup err {url[:120]}: {e}")
            caps = []
        if self._last_throttled:
            dk = self._last_kind
        elif not caps and not ratelimit.wayback_available():
            self.wb_deferred += 1     # Wayback CDX skipped: not a real "no capture"
            dk = "breaker"
        if dk and not caps:
            lookups[0] -= 1           # the retry gets its lookup back
        return caps, dk

    # -- candidate collection --
    def cached_html(self, url: str):
        try:
            row = self.db.execute("select path from fetch where url=?", (url,)).fetchone()
        except Exception:
            return None
        if not row or not row[0] or not str(row[0]).endswith(".html.gz"):
            return None
        try:
            with gzip.open(row[0]) as fh:
                return fh.read(C.MAX_HTML_BYTES).decode("utf-8", "replace")
        except Exception:
            return None

    def seed_urls(self) -> list:
        seeds = []
        for sp in self.r.get("section_pages") or []:
            seeds.append(sp)
        for e in self.r.get("first_errors") or []:
            m = re.search(r"(https?://\S+)$", e)
            if m:
                seeds.append(m.group(1))
        links = sorted(self.t.get("code_links") or [], key=lambda l: -C.score_seed(l))
        for l in links[:6]:
            if C.score_seed(l) > 0:
                seeds.append(l["url"])
        if self.t.get("homepage"):
            seeds.append(self.t["homepage"])
        out, seen = [], set()
        for u in seeds:
            cu = C.canon(u)
            if cu and cu not in seen:
                seen.add(cu); out.append(cu)
        return out

    def collect(self) -> dict:
        cands = {}  # url -> (anchor, from_section_url)

        def take(links, page):
            sect = bool(C.SECTION_RE.search(C._fold(page)))
            for u, txt in links:
                if is_doc_url(u) and doc_link_ok(txt, u, sect):
                    if u not in cands:
                        cands[u] = (txt, page)
        seeds = self.seed_urls()
        # first-errors that are themselves doc URLs (robots-blocked PDFs)
        for u in seeds:
            if is_doc_url(u) and u not in cands:
                cands[u] = ("", "")
        # (a) live-pass cached HTML (fetched under robots allow at crawl time; local, no network)
        local_pages = 0
        for sp in self.r.get("section_pages") or []:
            h = self.cached_html(sp)
            if h:
                local_pages += 1
                lk, _ = links_of(h, sp)
                take(lk, sp)
        self.stats["local_pages"] = local_pages
        # (b) archived HTML pages for sites without usable cached pages
        if len(cands) < 3:
            pages_done = 0
            html_pages = [u for u in seeds if not is_doc_url(u)]
            hosts = []
            for u in html_pages:
                h = urllib.parse.urlsplit(u).netloc.lower()
                if h not in hosts and not SHARED_HOSTS.search(h):
                    hosts.append(h)
            # html listing per host (keyword pages) to find archived section pages beyond the seeds
            listed = []
            for h in hosts[:2]:
                if not self.budget() or self.throttled:
                    break
                m, _dk = self.listing(h + "/", html=True)
                for cu, caps in m.items():
                    listed.append((C.score_seed({"url": caps[0].original_url, "text": ""}), caps))
            listed.sort(key=lambda x: -x[0])
            queue = []  # (url, caps|None)
            for u in html_pages[:4]:
                queue.append((u, None))
            for sc, caps in listed[:10]:
                if sc > 0:
                    queue.append((caps[0].original_url, caps))
            seen = set()
            while queue and pages_done < MAX_ARCHIVED_PAGES and self.budget():
                if self.throttled:
                    break             # Wayback cooling: the whole place is requeued, don't spin through pages
                u, caps = queue.pop(0)
                cu = canonical_url(u)
                if cu in seen:
                    continue
                seen.add(cu)
                try:
                    if caps is None:
                        # check listings first to avoid a per-URL query
                        for (pref, ishtml), m in self.listings.items():
                            if ishtml and m.get(cu):
                                caps = m[cu]; break
                    doc = (self._guard(self.fx.fetch_best, caps, max_tries=3) if caps
                           else self._guard(self.fx.fetch_newest, u, max_tries=3))
                except Exception as e:
                    if not self._last_throttled and not isinstance(e, ArchiveTransient):
                        log(f"  archived page err {u[:100]}: {e}")
                    doc = None
                if doc is None:
                    if self._last_throttled:  # ArchiveDeferred: discovery incomplete -> place is requeued
                        self.stats["archived_page_deferred"] += 1
                        continue
                    self.stats["archived_page_miss"] += 1   # None: genuine miss (fetcher round 3)
                    continue
                ct = (doc.content_type or "").lower()
                if "html" not in ct and not doc.body[:500].lstrip().lower().startswith((b"<!doctype", b"<html")):
                    continue
                pages_done += 1
                self.stats["archived_pages"] += 1
                lk, title = links_of(doc.text(), doc.original_url)
                take(lk, doc.original_url)
                # one hop: section-like subpages on the same host
                base_host = urllib.parse.urlsplit(doc.original_url).netloc.lower()
                for lu, txt in lk:
                    if urllib.parse.urlsplit(lu).netloc.lower() != base_host or is_doc_url(lu):
                        continue
                    f = C._fold(txt + " " + lu)
                    if C.SECTION_RE.search(f) and not C.EXCLUDE_RE.search(C._fold(txt)) and len(queue) < 20:
                        queue.append((lu, None))
        return cands

    # -- run --
    def _res(self) -> dict:
        res = {"place_id": self.t["place_id"], "name": self.t.get("name"), "live_status": self.r["status"],
               "group": self.group, "candidates": self.candidates, "files": [], "status": ""}
        res.update(self.acc)
        for k in RES_COUNTERS[9:]:
            if not res.get(k):
                res.pop(k, None)
        return res

    def _deferred_res(self, res: dict) -> dict:
        kinds = {p[3] for p in self.pending} or set(self.seg_kinds)
        if self.stop.is_set() and kinds <= {"stop"}:
            res["status"] = "interrupted"
        elif "throttle" in kinds:
            res["status"] = "deferred_throttle"
        else:
            res["status"] = "deferred_wayback"
        if self._cc_seg:
            self.cc_rounds += 1
        if self._unk_seg:
            self.unknown_rounds += 1
        res["cc_rounds"] = self.cc_rounds
        res["unknown_rounds"] = self.unknown_rounds
        res["wb_deferred"] = self.wb_deferred
        res["throttled"] = self.throttled
        res["not_before"] = self.throttle_nb
        res["pending_docs"] = len(self.pending)
        res["files"] = list(self.files)
        res.update({k: v for k, v in self.stats.items()})
        return res

    def run(self) -> dict:
        self.start = time.time()
        self.throttled, self.throttle_nb, self.wb_deferred = 0, 0.0, 0
        self._partial = {}
        self._cc_seg = False
        self._unk_seg = False
        self.seg_kinds = set()
        self.segments += 1
        res = self._res()
        if not self.collected:
            cands = self.collect()
            res["candidates"] = self.candidates = len(cands)
            if self.throttled or self.wb_deferred:
                # discovery was incomplete (Wayback throttled / breaker): requeue the whole place, nothing staged
                self.segments -= 1
                return self._deferred_res(res)
            if not cands:
                res["status"] = "no_candidates"
                res.update({k: v for k, v in self.stats.items()})
                return res
            self.collected = True
            order = sorted(cands.items(), key=lambda kv: -doc_priority(kv[1][0], kv[0]))[:MAX_DOCS_PER_PLACE * 2]
            items = [[u, a, s, ""] for u, (a, s) in order]
        else:
            items, self.pending = self.pending, []
        w = StagedWriter(STAGE, "DE", self.t["place_id"], batch_prefix="archive", chunk=25, max_bytes=30 * 1024 * 1024)
        acc = self.acc
        try:
            for idx, it in enumerate(items):
                url, anchor, section = it[0], it[1], it[2]
                if self.n >= MAX_DOCS_PER_PLACE:
                    break
                if not self.budget():
                    if self.stop.is_set():   # interrupted: keep the rest for the resumed run
                        self.pending.extend([[x[0], x[1], x[2], "stop"] for x in items[idx:]])
                    break
                if self.throttled and (wb_cooling() > 0 or ("breaker" in self.seg_kinds and not ratelimit.wayback_available())):
                    # Wayback is cooling down / breaker open: requeue the rest of this place at once, go do other work
                    self.pending.extend([[x[0], x[1], x[2], "throttle"] for x in items[idx:]])
                    break
                # (1) already published by the old repos / world_municipal_law: don't fetch it again
                cov = COVER.covered(url)
                if cov:
                    acc["skipped_covered"] += 1
                    self.stats["covered_by_published" if str(cov).startswith("world_municipal_law:") else "covered_by_old_repo"] += 1
                    bump_skip("skipped_covered")
                    continue
                # (2) shared Amt / VG site: another member's own law -> skip; a shared doc -> staged ONCE (Amt place
                #     if the registry has one, else the first member that stages it)
                shared_owner, shared_nk = None, None
                cls, other = AMT.classify(self.t["place_id"], url, anchor)
                if cls == "other_member":
                    acc["skipped_other_member"] += 1
                    bump_skip("skipped_other_member")
                    continue
                if cls == "shared":
                    shared_nk = norm_key(url)
                    shared_owner = other or self.t["place_id"]
                    if AMT.claimed_by(shared_nk) is not None:      # already staged (by the Amt or a member)
                        acc["skipped_shared_amt"] += 1
                        bump_skip("skipped_shared_amt")
                        continue
                caps, dk = self.caps_for(url, self.lookups)
                if not caps and dk:
                    self.pending.append([url, anchor, section, dk])
                    continue
                if not caps:
                    acc["no_capture"] += 1
                    continue
                try:
                    doc = self._guard(self.fx.fetch_best, caps, max_tries=3)
                except Exception as e:
                    if not self._last_throttled and not isinstance(e, ArchiveDeferred):
                        log(f"  fetch err {url[:100]}: {e}")
                    doc = None
                if doc is None:
                    if self._last_throttled:  # ArchiveDeferred (throttle/timeout/busy/breaker): requeue the doc
                        if self._last_kind == "breaker":
                            acc["wb_deferred_docs"] += 1
                        self.pending.append([url, anchor, section, self._last_kind or "throttle"])
                        continue
                    if dk:                    # listing incomplete (deferral / legacy breaker skip): a capture may exist
                        if dk == "breaker":
                            self.wb_deferred += 1
                            acc["wb_deferred_docs"] += 1
                        self.pending.append([url, anchor, section, dk])
                        continue
                    if self._last_exc is not None:   # CC-only deferral accepted after MAX_CC_DEFER_ROUNDS
                        record_incomplete({"kind": "doc_cc_deferred_gave_up", "place_id": self.t["place_id"],
                                           "url": url, "cc_rounds": self.cc_rounds, **_deferral_info(self._last_exc)})
                    acc["fetch_fail"] += 1    # None: every source answered with nothing usable
                    continue
                body = doc.body
                is_pdf = "pdf" in (doc.content_type or "").lower() or body[:5] == b"%PDF-"
                if is_pdf:
                    text, err = pdf_to_text(body)
                else:
                    soup = BeautifulSoup(doc.text(), "lxml")
                    text, err = C.html_main_text(soup), ""
                    soup.decompose()
                size = len(body)
                import hashlib
                sha = hashlib.sha256(body).hexdigest()
                body = None
                doc.body = b""
                if len((text or "").strip()) < 50:
                    acc["no_text"] += 1
                    if is_pdf:
                        with (WORK / "_scanned_pdfs_need_ocr.jsonl").open("a") as fh:
                            fh.write(json.dumps({"place_id": self.t["place_id"], "original_url": url,
                                                 "archive_url": doc.archive_url, "err": err}) + "\n")
                    continue
                did = C.stable_doc_id(url)
                if did in self.seen_ids:
                    continue
                self.seen_ids.add(did)
                disallowed, basis = crawl_robots(url)
                if disallowed:
                    policy = "archived_robots_disallowed"
                    acc["robots_policy_docs"] += 1
                else:
                    policy = "archived_live_unavailable"
                owner = shared_owner or self.t["place_id"]
                tinfo = self.t if owner == self.t["place_id"] else (AMT.info.get(owner) or {"place_id": owner})
                if shared_nk is not None and not AMT.claim(shared_nk, owner, self.t["place_id"], url):
                    acc["skipped_shared_amt"] += 1            # another member staged it meanwhile
                    bump_skip("skipped_shared_amt")
                    continue
                d = {
                    "place_id": owner, "requested_url": url, "doc_url": url,
                    "title": anchor or url.split("?")[0].rsplit("/", 1)[-1],
                    "doc_type_guess": C.guess_doc_type((anchor or "") + " " + url + " " + text[:500]),
                    "content_type": "pdf" if is_pdf else "html", "text": text,
                    "fetched_at": doc.fetched_at, "municipality_name": tinfo.get("name"), "qid": tinfo.get("qid"),
                    "source_url": tinfo.get("source_url"), "homepage": tinfo.get("homepage"),
                    "section_url": section or None, "http_content_type": doc.content_type, "sha256": sha,
                    "size_bytes": size, "raw_path": None,
                    "text_extraction": ("pdftotext" + (f" ({err})" if err else "")) if is_pdf else "html_main_text",
                    "template": None, "crawler": VERSION,
                }
                rec = C.to_schema_record(d, self.n)
                rec["retrieved_at"] = doc.fetched_at
                rec.update(provenance_fields(doc, policy, basis))
                rec["live_status"] = self.r["status"]
                if shared_nk is not None:
                    rec["shared_amt_site"] = _host(url)
                    if owner != self.t["place_id"]:
                        rec["found_via_place_id"] = self.t["place_id"]
                e = (w if owner == self.t["place_id"] else self._amt_writer(owner)).add(rec)
                if e:
                    log(f"  invalid record {url[:100]}: {e}")
                    continue
                self.n += 1
                acc["docs"] += 1
                if shared_nk is not None:
                    acc["shared_amt_docs"] += 1
                    if owner != self.t["place_id"]:
                        acc["amt_attributed_docs"] += 1
                if getattr(doc, "incomplete", False):
                    # staged, but another source failed: list it for a later re-check (no requeue, no loop)
                    acc["incomplete_docs"] += 1
                    record_incomplete({"kind": "doc", "place_id": self.t["place_id"], "doc_id": rec.get("doc_id"),
                                       "url": url, "archive_source": doc.archive_source,
                                       "archive_timestamp": doc.archive_timestamp, "archive_url": doc.archive_url,
                                       "content_complete": doc.content_complete,
                                       **_deferral_info(getattr(doc, "deferral", None))})
                acc["pdf_docs" if is_pdf else "html_docs"] += 1
                acc["cc_docs" if doc.archive_source == "commoncrawl" else "wb_docs"] += 1
            w.flush()
            self._flush_amt()
        except Exception:
            # flush whatever is validated so far, then re-raise
            try:
                w.flush()
                self._flush_amt()
            except Exception:
                pass
            self.files += [Path(p).name for p in w.written if Path(p).name not in self.files]
            raise
        self.files += [Path(p).name for p in w.written if Path(p).name not in self.files]
        res = self._res()
        if self.pending:
            # DEFER: not done, not failed. Staged docs stay; only self.pending is retried (requeue).
            return self._deferred_res(res)
        res["files"] = list(self.files)
        if self.amt_files:
            res["amt_files"] = list(self.amt_files)
        covered_n = res.get("skipped_covered", 0) + res.get("skipped_shared_amt", 0)
        if res["docs"]:
            res["status"] = "recovered"
        elif covered_n and not (res["no_capture"] or res["fetch_fail"] or res["no_text"]):
            res["status"] = "covered_elsewhere"   # every candidate is already published / staged under another place
        else:
            res["status"] = "no_capture" if res["no_capture"] and not res["fetch_fail"] else "no_docs"
        res["exact_lookups"] = self.lookups[0]
        res["segments"] = self.segments
        res.update({k: v for k, v in self.stats.items()})
        return res


# ------------------------------------------------------------------ runner
class DeferLog:
    """Log a deferral at most once per place per cool-down (the 422 MB stdout log came from DEFERRED churn)."""

    def __init__(self):
        self.until: dict = {}
        self.suppressed = 0
        self.lock = threading.Lock()

    def should_log(self, place_id: str, nb: float) -> bool:
        now = time.time()
        with self.lock:
            prev = self.until.get(place_id)
            if prev is not None and now < prev:
                self.suppressed += 1
                return False
            self.until[place_id] = max(nb, now + DEFER_MIN_S)
            return True


class ArchiveLogLimiter(logging.Filter):
    """Rate-limit the fetcher's own warnings ('world_law.archive' logger -> stderr -> *.log.stdout):
    at most PER_WINDOW lines per message template per WINDOW s; the next line after a window reports
    how many were suppressed."""
    WINDOW, PER_WINDOW = 600.0, 5

    def __init__(self):
        super().__init__()
        self.win: dict = {}
        self.lock = threading.Lock()

    def filter(self, record):
        key = str(record.msg)[:80]
        now = time.time()
        with self.lock:
            t0, n, sup = self.win.get(key, (now, 0, 0))
            if now - t0 >= self.WINDOW:
                if sup:
                    record.msg = f"[{sup} similar suppressed in last {int(now - t0)}s] " + str(record.msg)
                t0, n, sup = now, 0, 0
            if n >= self.PER_WINDOW:
                self.win[key] = (t0, n, sup + 1)
                return False
            self.win[key] = (t0, n + 1, sup)
        return True


def setup_archive_logging():
    lg = logging.getLogger("world_law.archive")
    if any(isinstance(f, ArchiveLogLimiter) for h in lg.handlers for f in h.filters):
        return
    h = logging.StreamHandler(sys.stderr)
    h.setLevel(logging.WARNING)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    h.addFilter(ArchiveLogLimiter())
    lg.addHandler(h)
    lg.propagate = False


def idle_state_key(n_deferred: int, n_fresh: int, cool: float, breaker: str) -> tuple:
    """What counts as an idle-state change (one log line each): queue sizes, cooling yes/no, breaker state."""
    return (n_deferred, n_fresh, cool > 0, breaker)


def load_continuations(done: set) -> dict:
    out = {}
    if CONT_F.exists():
        for l in CONT_F.open():
            try:
                d = json.loads(l)
            except Exception:
                continue
            if d.get("cleared"):
                out.pop(d.get("place_id"), None)
            elif d.get("place_id"):
                out[d["place_id"]] = d
    return {k: v for k, v in out.items() if k not in done}


class Scheduler:
    """Fresh queue + deferred items. A deferred item is {"r", "nb", "kind", "pa"(PlaceArchiver|None), "cont"}.
    Throttle items are due at nb (and only while Wayback is not cooling down); breaker items at nb or as soon
    as the breaker lets Wayback through (old behaviour). Fresh places wait while Wayback is cooling down or
    the breaker is closed to traffic, so we don't churn through every place deferring it."""

    def __init__(self, todo, conts):
        self.q = list(todo)
        self.deferred: list = []
        self.lock = threading.Lock()
        self.busy = 0
        self.conts = conts
        self.n_deferred = 0
        self.n_throttle = 0
        self.kick = threading.Event()   # set on requeue/finish/stop: idle workers re-plan at once

    def requeue(self, r, nb, kind, pa=None, cont=None):
        with self.lock:
            self.deferred.append({"r": r, "nb": nb, "kind": kind, "pa": pa, "cont": cont})
            self.busy -= 1
            self.n_deferred += 1
            if kind == "throttle":
                self.n_throttle += 1
        self.kick.set()

    def done_one(self):
        with self.lock:
            self.busy -= 1
        self.kick.set()

    def next(self):
        """(item|None, wait_s|None). item = (r, pa, cont); wait None + item None => finished."""
        now = time.time()
        cool = wb_cooling()
        wb_ok = cool <= 0 and ratelimit.wayback_available()
        with self.lock:
            best = None
            for d in self.deferred:
                if d["kind"] == "throttle":
                    due = d["nb"] <= now and cool <= 0
                else:
                    due = (d["nb"] <= now or wb_ok) and cool <= 0
                if due and (best is None or d["nb"] < best["nb"]):
                    best = d
            if best is not None:
                self.deferred.remove(best)
                self.busy += 1
                return (best["r"], best["pa"], best["cont"]), None
            if self.q and wb_ok:
                r = self.q.pop(0)
                self.busy += 1
                return (r, None, self.conts.pop(r["place_id"], None)), None
            if not self.q and not self.deferred and self.busy == 0:
                return None, None
            # an overdue item still waits for the host cool-down (no 1 s polling while Wayback is cooling)
            wake = [max(d["nb"], now + cool) for d in self.deferred]
            if cool > 0 and self.q:
                wake.append(now + cool)
            nxt = min(wake) if wake else now + IDLE_WAIT_CAP_S
            return None, min(IDLE_WAIT_CAP_S, max(1.0, nxt - now))

    def pending(self):
        with self.lock:
            return len(self.deferred), len(self.q)


def main():
    global LOG_FH
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="comma separated place_ids")
    ap.add_argument("--lane", default=os.environ.get("ARCHIVE_LANE", "web"))
    ap.add_argument("--cc-crawls", type=int, default=4)
    ap.add_argument("--log", default="")
    ap.add_argument("--no-cover-check", action="store_true", help="don't skip URLs the old repos / world_municipal_law publish")
    a = ap.parse_args()
    a.workers = max(1, min(3, a.workers))
    os.environ["ARCHIVE_LANE"] = a.lane
    WORK.mkdir(parents=True, exist_ok=True); LOGS.mkdir(parents=True, exist_ok=True)
    if a.log:
        LOG_FH = open(a.log, "a")
    setup_archive_logging()
    global COVER, AMT
    results = load_results()
    tlist = C.load_targets()
    targets = {t["place_id"]: t for t in tlist}
    import resource
    rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    COVER = CoverChecker(enabled=not a.no_cover_check)
    try:
        amt_map = json.loads((WORK / "amt_map.json").read_text())
    except (OSError, ValueError):
        amt_map = {}
    AMT = AmtIndex(tlist, amt_map=amt_map, claims_path=WORK / "shared_amt_claims.jsonl")
    rss1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    log(f"cover check: {'on' if COVER.active else 'OFF (' + str(COVER.err) + ')'}; amt index: "
        f"{sum(1 for h in AMT.host_places if AMT.shared(h))} shared Amt/VG hosts, {len(AMT.amt_place)} Amt places, "
        f"{len(AMT.claims)} claims; maxrss +{(rss1 - rss0) / 1024:.1f} MB")
    todo = [r for r in results.values() if r["status"] in TARGET_STATUSES]
    if a.only:
        ids = set(a.only.split(","))
        todo = [r for r in todo if r["place_id"] in ids]
    done_f = WORK / "done.jsonl"
    done = set()
    agg = collections.Counter()
    last = {}
    if done_f.exists():
        for l in done_f.open():
            try:
                d = json.loads(l)
            except Exception:
                continue
            if d.get("requeue"):          # {"place_id":..,"requeue":true} re-opens an item
                last.pop(d["place_id"], None); continue
            last[d["place_id"]] = d
    for pid, d in last.items():
        done.add(pid); agg_add(agg, d)
    total = len(todo)
    # robots-blocked first (Benjamin's approved case), host-sorted for listing cache locality
    todo.sort(key=lambda r: (r["status"] not in ROBOT_STATUSES, (r.get("section_pages") or r.get("first_errors") or [""])[0]))
    todo = [r for r in todo if r["place_id"] not in done]
    conts = load_continuations(done)
    # partially staged places resume first (only their pending docs)
    todo.sort(key=lambda r: r["place_id"] not in conts)
    if a.limit:
        todo = todo[:a.limit]
    log(f"archive pass start: targets={total} done={len(done)} todo={len(todo)} continuations={len(conts)} "
        f"workers={a.workers} lane={a.lane} version={VERSION}")
    stop = threading.Event()
    sch = Scheduler(todo, conts)

    def _stop(*_):
        stop.set(); sch.kick.set()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    dlog = DeferLog()
    t0 = time.time()
    n_run = [0]
    idle = {"key": None}
    fl = threading.Lock()

    def write_progress(final=False):
        nd, nq = sch.pending()
        p = {"updated": C.now_iso(), "targets": total, "done": len(done), "this_run": n_run[0],
             "elapsed_s": round(time.time() - t0), "agg": dict(agg),
             "deferred_pending": nd, "queue_fresh": nq, "deferred_events": sch.n_deferred,
             "deferred_throttle_events": sch.n_throttle, "deferral_logs_suppressed": dlog.suppressed,
             "wayback_cooldown_s": round(wb_cooling()), "finished": final and len(done) >= total,
             "skips_this_run": dict(RUN_SKIPS), "cover_check": ("on" if COVER.active else f"off: {COVER.err}"),
             "cover_stats": dict(COVER.stats),
             "lane": a.lane, "version": VERSION}
        tmp = WORK / "_progress.json.tmp"
        tmp.write_text(json.dumps(p, indent=1)); os.replace(tmp, WORK / "_progress.json")

    def save_cont(state):
        with fl:
            with CONT_F.open("a") as fh:
                fh.write(json.dumps(state, ensure_ascii=False) + "\n")

    def worker(i):
        fx = ArchiveFetcher(lane=a.lane, cc_crawls=a.cc_crawls, cc_max_wait=30, raise_deferred=True, listing_deferred="flag")
        db = S / "_state/fetch_cache.sqlite"
        while not stop.is_set():
            sch.kick.clear()
            item, wait = sch.next()
            if item is None:
                if wait is None:
                    return
                with fl:
                    nd, nq = sch.pending()
                    cool = wb_cooling()
                    brk = "ok" if ratelimit.wayback_available() else "open"
                    key = idle_state_key(nd, nq, cool, brk)
                    if key != idle["key"]:            # only on a change of idle state, not every check
                        idle["key"] = key
                        log(f"[w{i}] idle: {nd} deferred, {nq} fresh waiting; wayback cooldown {cool:.0f}s, "
                            f"breaker {brk}; next check in {wait:.0f}s")
                sch.kick.wait(wait)
                continue
            r, pa, cont = item
            pid = r["place_id"]
            t = targets.get(pid, {"place_id": pid, "name": r.get("name"), "qid": r.get("qid")})
            ts = time.time()
            try:
                if pa is None:
                    pa = PlaceArchiver(fx, t, r, db, stop, cont=cont)
                else:
                    pa.rebind(fx)
                res = pa.run()
            except Exception as e:
                if pa is None:   # constructor failed: minimal stand-in so the bookkeeping below works
                    pa = types.SimpleNamespace(files=[], collected=False, pending=[], acc={}, segments=1,
                                               close=lambda: None, state=lambda: {})
                res = {"place_id": pid, "live_status": r["status"],
                       "group": "robots" if r["status"] in ROBOT_STATUSES else "error", "status": "error",
                       "error": f"{type(e).__name__}: {str(e)[:300]}", "docs": 0}
                if _is_deferral(e):
                    res.update(status="deferred_throttle", not_before=wb_not_before(e), throttled=1)
                elif isinstance(e, (ArchiveTransient, ratelimit.WaybackDown)) or "wayback breaker open" in str(e):
                    res["status"] = "deferred_wayback"; res["wb_deferred"] = 1
                else:
                    log(f"[w{i}] ERROR {pid}: {type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}")
                if pa.files:   # docs staged before the error: keep them, mark done with what we have
                    res["files"] = list(pa.files); res["docs"] = pa.acc.get("docs", 0)
            st = res.get("status")
            if stop.is_set() and st != "recovered":
                if pa.files or pa.collected and pa.pending:
                    if st == "interrupted" or pa.pending:
                        save_cont(pa.state())
                pa.close()
                sch.done_one()
                return  # interrupted: not marked done; resumes from pending_docs.jsonl (or from scratch)
            if st in ("deferred_throttle", "deferred_wayback", "interrupted"):
                kind = "throttle" if st == "deferred_throttle" else ("breaker" if st == "deferred_wayback" else "throttle")
                if kind == "throttle":
                    nb = max(float(res.get("not_before") or 0), time.time() + DEFER_MIN_S)
                elif res.get("not_before"):           # ArchiveDeferred(breaker_open): the breaker's next probe
                    nb = max(float(res["not_before"]), time.time() + DEFER_MIN_S)
                else:                                 # legacy breaker skip without a retry time
                    nb = time.time() + DEFER_RETRY_S
                keep = pa if isinstance(pa, PlaceArchiver) else None
                if keep is not None and not pa.collected:
                    pa.listings.clear(); pa._partial = {}   # place-level: collect is redone, keep only counters
                if keep is not None and pa.files:
                    save_cont(pa.state())             # survive restarts without re-staging docs
                pa.close()                            # sqlite is per thread; rebind() reopens it
                sch.requeue(r, nb, kind, pa=keep)
                if dlog.should_log(pid, nb):
                    tsv = "deferred_wayback.tsv" if kind == "breaker" else "deferred_throttle.tsv"
                    with fl:
                        with (WORK / tsv).open("a") as fh:
                            fh.write(f"{C.now_iso()}\t{pid}\t{res.get('wb_deferred', 0) if kind == 'breaker' else res.get('throttled', 0)}"
                                     f"\t{res.get('pending_docs', 0)}\t{time.strftime('%H:%M:%S', time.localtime(nb))}"
                                     f"\t{','.join(res.get('files') or [])}\n")
                        write_progress()
                    why = ("wayback breaker" if kind == "breaker" else "wayback throttled (429/5xx cool-down)")
                    log(f"[w{i}] {pid} {r.get('name')} -> DEFERRED ({why}; pending_docs={res.get('pending_docs', 0)} "
                        f"staged_docs={pa.acc.get('docs', 0)}) {round(time.time()-ts)}s; requeued for >= "
                        f"{time.strftime('%H:%M:%S', time.localtime(nb))} PT  [{len(done)}/{total}]")
                continue
            res["elapsed_s"] = round(time.time() - ts, 1)
            res["finished_at"] = C.now_iso()
            pa.close()
            with fl:
                with done_f.open("a") as fh:
                    fh.write(json.dumps(res, ensure_ascii=False) + "\n")
                if pa.segments > 1 or cont is not None:
                    with CONT_F.open("a") as fh:
                        fh.write(json.dumps({"place_id": pid, "cleared": True, "t": C.now_iso()}) + "\n")
                done.add(pid); n_run[0] += 1
                agg_add(agg, res)
                write_progress()
            sch.done_one()
            log(f"[w{i}] {pid} {r.get('name')} live={r['status']} -> {res['status']} docs={res.get('docs',0)} "
                f"cands={res.get('candidates',0)} seg={res.get('segments', 1)} skipped_covered={res.get('skipped_covered', 0)} "
                f"shared_amt={res.get('shared_amt_docs', 0)}/{res.get('skipped_shared_amt', 0)} "
                f"other_member={res.get('skipped_other_member', 0)} {res['elapsed_s']}s  [{len(done)}/{total}]")

    def progress_loop():
        while not stop.wait(60):
            with fl:
                write_progress()

    threading.Thread(target=progress_loop, daemon=True).start()
    ths = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(a.workers)]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    with fl:
        write_progress(final=True)
    COVER.close()
    log(f"archive pass exit: done={len(done)}/{total} agg={dict(agg)} deferral_logs_suppressed={dlog.suppressed} "
        f"skips_this_run={dict(RUN_SKIPS)}")


def agg_add(agg, d):
    g = d.get("group", "?")
    agg[f"{g}_places"] += 1
    agg[f"status_{d.get('status')}"] += 1
    if d.get("docs"):
        agg[f"{g}_recovered_places"] += 1
        agg[f"{g}_docs"] += d["docs"]
    for k in ("pdf_docs", "html_docs", "cc_docs", "wb_docs", "robots_policy_docs", "skipped_covered",
              "skipped_shared_amt", "skipped_other_member", "shared_amt_docs", "amt_attributed_docs"):
        agg[k] += d.get(k, 0) or 0


if __name__ == "__main__":
    main()
