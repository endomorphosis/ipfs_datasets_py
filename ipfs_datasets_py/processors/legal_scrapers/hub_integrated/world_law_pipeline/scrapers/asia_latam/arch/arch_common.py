"""Shared helpers for the asia_latam archive backfill jobs (built ONLY on pipeline/archive's ArchiveFetcher,
StagedWriter and box-wide limiter; no own Wayback/CC client).  State: staging/asia_latam/_archive_work/<job>/."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import json, logging, os, re, resource, signal, subprocess, sys, tempfile, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
# fair-share lane for the box-wide archive limiter (archive/README.md "Lanes and fair sharing")
os.environ.setdefault("ARCHIVE_LANE", "asia_latam")
from archive import ArchiveFetcher, StagedWriter, provenance_fields  # noqa: E402,F401
from archive.core import ArchiveError, Capture  # noqa: E402,F401
try:  # shared fetcher >= 2026-10-18 12:00 PT: 429/5xx -> ArchiveDeferred(not_before), per-host box-wide cool-down
    from archive.core import ArchiveDeferred  # noqa: E402
    from archive.core import ArchiveTransient  # noqa: E402
    from archive import deferral as _deferral  # noqa: E402
except ImportError:  # pragma: no cover
    class ArchiveTransient(ArchiveError):
        pass

    class ArchiveDeferred(ArchiveTransient):
        not_before = 0.0
    _deferral = None
ARCHIVE_HOSTS = ("web.archive.org", "data.commoncrawl.org", "index.commoncrawl.org")
try:
    from archive.ratelimit import WaybackDown  # noqa: E402  (ratelimit v4 breaker)
except ImportError:  # pragma: no cover
    class WaybackDown(Exception):
        pass


DEFERRED = {"n": 0}   # items deferred in this process (Wayback breaker open)
EXIT_DEFERRED = 75     # job exit code when items were deferred: breaker_loop.sh waits for the breaker, then reruns


DEFER_END = {"flag": False}   # pass ended early because the archive hosts are cooling down (exit 75, not a _STOP)
DEFER_RUN_END = int(os.environ.get("ARCH_DEFER_RUN_END", "25"))
NEXT = {"nb": 0.0}      # earliest not_before among items deferred in this process (epoch s; 0 = unknown)
DISC = {"incomplete": []}
DISC_MARK = "_DISCOVERY_INCOMPLETE"   # discovery listings that failed with a deferral/breaker in this process


def note_nb(nb):
    """Remember a deferral's not_before (earliest wins) for breaker_loop.sh (env ARCH_NEXT_FILE)."""
    if nb and (not NEXT["nb"] or nb < NEXT["nb"]):
        NEXT["nb"] = float(nb)


def cooling_nb():
    """Latest not_before among the archive hosts currently cooling down (0 if none)."""
    if _deferral is None:
        return 0.0
    nb = 0.0
    for h in ARCHIVE_HOSTS:
        left = _deferral.host_cooldown(h)
        if left > 0:
            nb = max(nb, time.time() + left)
    return nb


def _breaker_open():
    try:
        from archive import ratelimit as _rl
        return not _rl.wayback_available()
    except Exception:
        return False


def listing_failed(e, what=""):
    """Call from a discovery `except ArchiveError` block. A deferral (429/5xx cool-down) or open breaker makes this
    process's candidate list incomplete: counted as deferred (exit 75) and candidates.jsonl is set aside at exit
    (renamed, never deleted) so the next run rediscovers after not_before."""
    if isinstance(e, ArchiveDeferred) or "breaker" in str(e).lower() or "cooling" in str(e).lower():
        DISC["incomplete"].append(what or str(e)[:80]); DEFERRED["n"] += 1
        if JOBNAME["job"] != "?":   # survives a crash: State() sets the candidates aside on the next start
            try:
                (WORK / JOBNAME["job"] / DISC_MARK).write_text(f"{utc()}\t{what}\t{str(e)[:200]}\n")
            except OSError:
                pass
        note_nb(getattr(e, "not_before", 0) or cooling_nb())
        logging.getLogger(JOBNAME["job"]).warning("listing %s deferred (%s) -> discovery incomplete", what, str(e)[:120])
        return True
    return False


def _set_candidates_aside(d):
    """Rename (never delete) a candidates.jsonl built from a truncated/deferred listing so the next run rediscovers."""
    cp = d / "candidates.jsonl"
    if cp.exists():
        os.replace(cp, cp.with_name(f"candidates.incomplete_{time.strftime('%Y%m%dT%H%M%S')}.jsonl"))
    m = d / DISC_MARK
    if m.exists():
        os.replace(m, d / (DISC_MARK + ".handled"))


def exit_code():
    """For __main__: 75 if anything was deferred (and no _STOP), else 0. Writes the earliest not_before to
    $ARCH_NEXT_FILE (breaker_loop.sh sleeps until then) and sets an incomplete candidates.jsonl aside."""
    if DISC["incomplete"] and JOBNAME["job"] != "?":
        _set_candidates_aside(WORK / JOBNAME["job"])
        logging.getLogger(JOBNAME["job"]).warning("discovery incomplete %s -> candidates set aside, rediscover next run",
                                                  DISC["incomplete"][:5])
    nf = os.environ.get("ARCH_NEXT_FILE")
    if nf and DEFERRED["n"]:
        try:
            Path(nf).write_text(str(NEXT["nb"] or cooling_nb() or 0))
        except OSError:
            pass
    return EXIT_DEFERRED if DEFERRED["n"] and (DEFER_END["flag"] or not STOP["flag"]) else 0


class WBDeferred(Exception):
    """Raised inside a job when a sub-fetch (e.g. an attached PDF) was skipped because the Wayback breaker is open."""


def wb_deferred(fx, doc=None, exc=None):
    """True when an item must be DEFERRED (requeued), not failed: doc is None and the fetcher skipped Wayback captures
    because the box-wide Wayback breaker is open (archive/README.md, ratelimit v4), or the call raised WaybackDown /
    a 'wayback breaker open' ArchiveTransient."""
    dnb = getattr(fx, "deferred_nb", 0.0)
    if fx is not None:
        fx.deferred_nb = 0.0            # consumed per item
    if doc is not None:
        return False
    if isinstance(exc, ArchiveDeferred):                    # 429/5xx or host cooling: requeue after not_before
        note_nb(exc.not_before or cooling_nb()); fx.last_deferral_nb = exc.not_before or cooling_nb(); return True
    ld = getattr(fx, "last_deferral", None)
    if ld is not None and getattr(ld, "not_before", 0):     # fetcher-reported deferral of the last fetch_best/newest
        dnb = max(dnb, ld.not_before)
    if exc is not None and isinstance(exc, ArchiveTransient) and not dnb and "breaker" not in str(exc).lower():
        nb = time.time() + 600                              # timeout/network after the retry budget: requeue in 10 min
        note_nb(nb); fx.last_deferral_nb = nb; return True
    if dnb:                                                 # a capture fetch inside fetch_best was deferred (CC or WB)
        note_nb(dnb); fx.last_deferral_nb = dnb; return True
    if getattr(fx, "last_wb_deferred", 0):
        nb = cooling_nb(); note_nb(nb); fx.last_deferral_nb = nb
        return True
    return exc is not None and (isinstance(exc, (WaybackDown, WBDeferred)) or "breaker" in str(exc).lower()
                                or "cooling" in str(exc).lower())

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam"))
WORK = STAGE / "_archive_work"
LOGS = STAGE / "_logs" / "archive"
STOP = {"flag": False}


def _stop(*_):
    STOP["flag"] = True


JOBNAME = {"job": "?"}


STOP_DIRS = []


def _stop_file_watch():
    """Clean stop via file: touch _archive_work/<job>/_STOP -> the job finishes the current doc, flushes, exits."""
    while True:
        time.sleep(3)
        for d in list(STOP_DIRS):
            if (d / "_STOP").exists():
                if not STOP["flag"]:
                    logging.getLogger(JOBNAME["job"]).warning("_STOP file found in %s -> stopping cleanly", d)
                STOP["flag"] = True


def setup(job, mem_gb=1.5):
    JOBNAME["job"] = job
    LOGS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:  # keep the job lean on the shared 16 GB box
        lim = int(mem_gb * 1024**3)
        resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
    except Exception:
        pass
    d = WORK / job
    d.mkdir(parents=True, exist_ok=True)
    sf = d / "_STOP"
    if sf.exists():  # a stale stop request from the previous run; a fresh launch clears it
        sf.unlink()
        logging.getLogger(job).info("cleared stale _STOP")
    if not STOP_DIRS:
        import threading
        threading.Thread(target=_stop_file_watch, daemon=True).start()
    STOP_DIRS.append(d)
    logging.getLogger(job).info("archive lane=%s", os.environ.get("ARCHIVE_LANE"))
    return d


def utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_text(t):
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t\u00a0]+", " ", t or "")).strip()


def html_soup_text(html, selectors=None, drop=("script", "style", "noscript", "nav", "header", "footer", "iframe", "svg",
                                               "select", "button", "form")):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    t = soup.find("title")
    page_title = t.get_text(" ", strip=True) if t else ""
    links = [a.get("href") for a in soup.find_all("a", href=True)]
    for tag in soup(list(drop)):
        tag.decompose()
    text = ""
    for sel in selectors or []:
        try:
            nodes = soup.select(sel)
        except Exception:
            nodes = []
        tt = "\n".join(n.get_text("\n", strip=True) for n in nodes)
        if len(tt) > 150:
            text = tt
            break
    if not text:
        text = (soup.body or soup).get_text("\n", strip=True)
    return soup, page_title[:500], clean_text(text), links


def pdf_text(body: bytes, timeout=180) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(body); f.flush()
        try:
            out = subprocess.run(["pdftotext", "-q", "-enc", "UTF-8", "-layout", f.name, "-"], capture_output=True,
                                 timeout=timeout)
            return clean_text(out.stdout.decode("utf-8", "replace"))
        except subprocess.TimeoutExpired:
            return ""


def is_pdf(doc):
    return doc.body[:5] == b"%PDF-" or "pdf" in (doc.content_type or "").lower()


class State:
    """done.tsv (key -> outcome) + stats.json; writers per place; flush marks pending keys done."""

    def __init__(self, job, cc, batch_prefix, chunk=200):
        self.dir = setup(job)
        import fcntl
        self._lockf = open(self.dir / "_job.lock", "w")
        try:  # one instance per job (resumable re-runs must not overlap)
            fcntl.flock(self._lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f"{job}: another instance is running")
        self._lockf.write(str(os.getpid())); self._lockf.flush()
        self.job, self.cc, self.prefix, self.chunk = job, cc, batch_prefix, chunk
        if (self.dir / DISC_MARK).exists():
            logging.getLogger(job).warning("previous discovery was truncated (%s) -> candidates set aside, rediscover",
                                           (self.dir / DISC_MARK).read_text().strip()[:200])
            _set_candidates_aside(self.dir)
        self.done = {}
        self.stats = Counter()
        self.writers = {}
        self.pending = []
        self.pending_urls = []
        self.files = []
        dp = self.dir / "done.tsv"
        if dp.exists():
            for line in dp.open(encoding="utf-8"):
                p = line.rstrip("\n").split("\t")
                if len(p) >= 2:
                    if p[1] == "requeue":          # a later line re-opens an item (e.g. failed during a Wayback outage)
                        self.done.pop(p[0], None)
                    else:
                        self.done[p[0]] = p[1]
        self.deferred = set()   # deferred this run (Wayback breaker open): skipped in-memory, never written to done.tsv
        # deferrals with a not_before still in the future (4th column of deferred_wayback.tsv): skipped this run too
        self.not_before = {}
        dw = self.dir / "deferred_wayback.tsv"
        if dw.exists():
            for line in dw.open(encoding="utf-8"):
                p = line.rstrip("\n").split("\t")
                if len(p) >= 4 and p[0] not in self.done:
                    try:
                        self.not_before[p[0]] = float(p[3])
                    except ValueError:
                        pass
        now = time.time()
        for k, nb in self.not_before.items():
            if nb > now:
                self.deferred.add(k); note_nb(nb)
        if any(nb > now for nb in self.not_before.values()):
            n = sum(1 for nb in self.not_before.values() if nb > now)
            DEFERRED["n"] += n; self.stats["deferred_not_before_pending"] += n
            logging.getLogger(job).info("%d items still cooling down (not_before in the future) -> skipped this run", n)
        self.last_flush = time.time()

    def mark(self, key, outcome):
        with (self.dir / "done.tsv").open("a", encoding="utf-8") as f:
            f.write(f"{key}\t{outcome}\t{utc()}\n")
        self.done[key] = outcome
        self._consec_defer = 0

    def defer(self, key, why="wayback_breaker", not_before=None):
        """Requeue: not marked done/failed, so a later run retries it, but not before `not_before` (epoch s; default:
        the deferral just seen by wb_deferred / the archive hosts' cool-down). Audit + schedule in
        <work>/deferred_wayback.tsv: key, why, utc, not_before."""
        if key in self.deferred:
            return
        fx = _FETCHERS[-1] if _FETCHERS else None
        nb = not_before or (getattr(fx, "last_deferral_nb", 0.0) if fx else 0.0) or cooling_nb()
        if fx is not None:
            fx.last_deferral_nb = 0.0
        if nb and why == "wayback_breaker" and nb > time.time():
            why = "deferred_throttle"
        self.deferred.add(key)
        DEFERRED["n"] += 1
        note_nb(nb)
        # every item goes through the same archive hosts: once a run of deferrals hits a live host cool-down, end the
        # pass early (exit 75, breaker_loop sleeps until not_before) instead of writing the whole queue to the tsv
        self._consec_defer = getattr(self, "_consec_defer", 0) + 1
        if self._consec_defer >= DEFER_RUN_END and not STOP["flag"] and (cooling_nb() > time.time() + 5 or _breaker_open()):
            DEFER_END["flag"] = True; STOP["flag"] = True
            logging.getLogger(self.job).warning("%d consecutive deferrals, archive hosts cooling until %s or Wayback breaker open -> ending pass",
                                                self._consec_defer, (time.strftime("%H:%M:%S", time.localtime(NEXT["nb"] or cooling_nb())) if (NEXT["nb"] or cooling_nb()) else "n/a"))
        self.stats["deferred_wayback"] += 1
        with (self.dir / "deferred_wayback.tsv").open("a", encoding="utf-8") as f:
            f.write(f"{key}\t{why}\t{utc()}\t{nb or 0:.0f}\n")

    def add(self, key, rec):
        apply_policy(rec)
        pid = rec["place_id"]
        w = self.writers.get(pid)
        if w is None:
            w = self.writers[pid] = StagedWriter(STAGE, self.cc, pid, batch_prefix=self.prefix, chunk=self.chunk)
        n0 = len(w.written)
        err = w.add(rec)
        if err:
            self.stats["invalid"] += 1
            self.mark(key, "invalid:" + err[:80])
            return False
        self.stats["staged"] += 1
        self.stats["src_" + rec.get("archive_source", "?")] += 1
        self.stats["complete" if rec.get("content_complete") else "incomplete"] += 1
        self.stats["stale" if rec.get("possibly_stale") else "fresh"] += 1
        self.pending.append(key)
        a = (rec.get("extra_metadata") or {}).get("archive") or {}
        self.pending_urls += [u for u in [rec.get("archive_url"), a.get("archive_url")] +
                              [x.get("archive_url") for x in (a.get("pdfs") or []) if isinstance(x, dict)] if u]
        if len(w.written) > n0:
            self.files += w.written[n0:]
        if not any(x.buf for x in self.writers.values()):
            for k in self.pending:
                self.mark(k, "staged")
            self.pending = []
            evict_staged_bodies(self.pending_urls); self.pending_urls = []
        return True

    def maybe_flush(self, secs=900):
        if time.time() - self.last_flush > secs:
            self.flush()

    def flush(self):
        for w in self.writers.values():
            if w.buf:
                p = w.flush()
                self.files.append(str(p))
                logging.getLogger(self.job).info("staged %s", p)
        for k in self.pending:
            self.mark(k, "staged")
        self.pending = []
        evict_staged_bodies(self.pending_urls); self.pending_urls = []
        self.last_flush = time.time()
        # drop writers without buffered docs to keep memory flat
        self.writers = {k: w for k, w in self.writers.items() if w.buf}

    def save(self, fx=None, final=False, **extra):
        st = dict(self.stats)
        st["done_total"] = len(self.done)
        st["staged_total"] = sum(1 for v in self.done.values() if v == "staged")
        if fx is not None:
            st["fetcher"] = dict(fx.stats)
        st.update(extra)
        st["updated"] = utc()
        st["final"] = final
        st["pid"] = os.getpid()
        tmp = self.dir / "stats.json.tmp"
        tmp.write_text(json.dumps(st, indent=1))
        os.replace(tmp, self.dir / "stats.json")


def append_csv(path, header, row):
    import csv
    new = not Path(path).exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow(row)


# ---------------------------------------------------------------------------------------------
# robots meta TAGGING (Benjamin via coordinator 2026-10-10, replaces the earlier skip rule): an archived page whose
# <meta name=robots|googlebot..> carries noarchive/noindex is still staged, but tagged source_policy=noarchive_meta
# (or noindex_meta); every such page is logged to _robots_meta_skips.csv (action=tagged). PDFs carry no meta.
from robots_meta import robots_meta_flags, policy_for  # noqa: E402
from archive import provenance_fields as _prov  # noqa: E402

SKIPS_CSV = STAGE / "_robots_meta_skips.csv"


_FETCHERS = []


def evict_staged_bodies(urls):
    """Disk hygiene (coordinator 2026-10-11): once a doc's text is staged in a validated, renamed file, drop the raw
    archived body we cached for it (shared pipeline/archive/_cache). Robots-meta-flagged captures are kept for audits.
    Every eviction is logged to _logs/_archive_cache_evicted.jsonl."""
    n = 0
    for f in _FETCHERS:
        for u in urls:
            key = f.cache_keys.pop(u, None)
            if not key:
                continue
            _, jp, bp = f.cache._bp(key)
            z = bp.stat().st_size if bp.exists() else 0
            for x in (bp, jp):
                try:
                    x.unlink()
                except FileNotFoundError:
                    pass
            n += 1
            with open(STAGE / "_logs" / "_archive_cache_evicted.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"archive_url": u, "bytes": z, "job": JOBNAME.get("job"), "evicted_at": utc()}) + "\n")
    return n


class CheckedFetcher(ArchiveFetcher):
    def __init__(self, *a, **k):
        k.setdefault("lane", os.environ.get("ARCHIVE_LANE") or "asia_latam")
        super().__init__(*a, **k)
        self.robots_flagged = {}
        self.deferred_nb = 0.0         # set when a capture fetch raised ArchiveDeferred; consumed by wb_deferred()
        self.last_deferral_nb = 0.0    # not_before of the last deferral wb_deferred() reported; used by State.defer()
        self.cache_keys = {}      # archive_url -> body cache key (for evict_staged_bodies)
        _FETCHERS.append(self)

    def fetch_best(self, caps, *a, **k):
        try:
            return super().fetch_best(caps, *a, **k)
        except ArchiveDeferred as e:   # nothing usable + CC/Wayback throttled: remember even if the caller swallows it
            self.deferred_nb = max(getattr(self, "deferred_nb", 0.0), e.not_before or cooling_nb())
            raise

    def cc_captures(self, *a, **k):
        caps = super().cc_captures(*a, **k)
        if getattr(caps, "truncated", False):   # deferred mid-listing: discovery incomplete (never kept as final)
            listing_failed(caps.deferral or ArchiveDeferred("cc listing truncated"), "cc:" + str(a[0] if a else k.get("url")))
        return caps

    def list_captures(self, *a, **k):
        caps = super().list_captures(*a, **k)
        if getattr(caps, "truncated", False):
            listing_failed(caps.deferral or ArchiveDeferred("listing truncated"), "list:" + str(a[0] if a else k.get("url")))
        return caps

    def fetch_capture(self, cap):
        try:
            doc = super().fetch_capture(cap)
        except ArchiveDeferred as e:   # fetch_best swallows it (CC silently): remember for wb_deferred()
            self.deferred_nb = max(getattr(self, "deferred_nb", 0.0), e.not_before or cooling_nb())
            raise
        flags = robots_meta_flags(doc.body, content_type=doc.content_type or "")
        doc.robots_flags = flags
        if not flags and doc.archive_url:
            self.cache_keys[doc.archive_url] = f"{cap.source}|{cap.crawl_id}|{cap.timestamp}|{cap.original_url}"
        if flags:
            self.robots_flagged[doc.original_url] = flags
            self._bump("robots_meta_tagged")
            logging.getLogger(JOBNAME["job"]).info("robots meta %s -> tag %s", ",".join(flags), doc.original_url)
            append_csv(SKIPS_CSV, ["at", "job", "original_url", "archive_url", "archive_timestamp", "flags", "action"],
                       [utc(), JOBNAME["job"], doc.original_url, doc.archive_url, doc.archive_timestamp,
                        ",".join(flags), "tagged"])
        return doc


def provenance_fields(doc):  # noqa: F811  (wraps archive.provenance_fields; carries the robots meta flags)
    out = _prov(doc)
    flags = getattr(doc, "robots_flags", None)
    if flags:
        out["robots_meta"] = list(flags)
    return out


def apply_policy(rec):
    """Final source_policy: robots meta noarchive/noindex wins (noarchive_meta > noindex_meta); otherwise the job's
    own value (archived_robots_disallowed / network_* fallback). robots.txt-disallowed sources keep a flag."""
    pol = policy_for(rec.get("robots_meta") or [])
    if pol:
        if rec.get("source_policy") == "archived_robots_disallowed":
            rec["robots_txt_disallowed"] = True
        rec["source_policy"] = pol
    return rec
