#!/usr/bin/env python3
"""EU-lane archive harvests for sources that are NETWORK-BLOCKED from the box.

Uses ONLY the shared fetcher /workspace/world_law/pipeline/archive (ArchiveFetcher + box-wide limiter,
StagedWriter, provenance_fields). Never a private Wayback/CC client. Never used to get around a robots.txt
Disallow: every original URL is checked against the site's robots.txt (archived copy when the live one is
unreachable) with common/rfc9309.py before it is fetched from the archive.

Targets
  at   Austria RIS Gemeinderecht   www.ris.bka.gv.at/Dokumente/Gemeinderecht/<Dokumentnummer>/<Dokumentnummer>.{pdf,html,rtf}
  pl   Poland journals KP/LB/WP    /WDU_<X>/<year>/<pos>/akt.pdf, .../Oryginal/akt.pdf, GetActPdf.ashx?year=&book=0&position=

Usage (interpreter: /workspace/world_law/pipeline/venv/bin/python)
  archive_jobs.py discover at|pl      # list captures (CC first, then Wayback) -> candidates.jsonl (resumable, cached)
  archive_jobs.py fetch at|pl [--limit N] [--test N]
  archive_jobs.py all at|pl           # discover (if needed) + fetch; re-run to resume
  archive_jobs.py status
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import argparse
import csv
import json
import logging
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
PIPE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
sys.path.insert(0, str(PIPE))
sys.path.insert(0, str(HERE))
os.environ.setdefault("WORLD_LAW_CC_INDEX_RETRIES", "2")
os.environ.setdefault("ARCHIVE_LANE", "eu")

from archive import ArchiveFetcher, StagedWriter, provenance_fields  # noqa: E402
from archive.core import Capture  # noqa: E402
from common.rfc9309 import Robots  # noqa: E402
from common.eu_wayback import EUArchiveFetcher  # noqa: E402  (EU Wayback policy, 2026-10-18)
from common.xwalk import XWALK  # noqa: E402
import schema  # noqa: E402

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu"))
STATE = STAGE / "_state" / "archive"
LOGS = STAGE / "_logs"
UNM = STAGE / "_unmatched"
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
UA_ROBOTS = "world-municipal-law-research/1.0"
BATCH = 50          # was 200: at ~25 docs/h per process (shared wayback slot) a 200-doc batch took 4-8 h to flush
FLUSH_SECS = 900    # also flush whatever is buffered every 15 min
STOP = [False]      # SIGTERM -> flush buffered docs at the next doc boundary, then exit (resume = same command)


def _on_term(*_):
    STOP[0] = True
USE_CC = os.environ.get("ARCHIVE_JOBS_NO_CC") != "1"
CC_CRAWLS = 3  # CC index has been 504-ing box-wide on 2026-10-10; keep the listing bounded

log = logging.getLogger("archive_jobs")


def new_fx(**kw):
    """THE EU-lane fetcher (2026-10-18): shared ArchiveFetcher/limiter/breaker, lane eu, 1 EU Wayback request in flight
    box-wide, one attempt per Wayback call; 429/5xx -> shared ArchiveDeferred + host cool-down (common/eu_wayback.py).
    Loops requeue deferred items for e.not_before and pause a target on Wayback deferrals (no sleep-retry). SIGTERM-aware."""
    kw.setdefault("cc_crawls", CC_CRAWLS)
    kw.setdefault("use_cc", USE_CC)
    return EUArchiveFetcher(stop=lambda: STOP[0], **kw)

# ---- Wayback circuit breaker (ratelimit v4, 2026-10-13): defer, never fail/done, items Wayback could not serve ----
DEFERRED = "deferred_wayback"
ITEM_DEF = [0]          # per-item counter: Wayback lookups/captures skipped because the breaker is open


ITEM_DEFS: list = []     # 2026-10-18 v3: ArchiveDeferred seen in this item's own lookups (CC listing truncated / CDX deferred)


def item_reset() -> None:
    ITEM_DEF[0] = 0
    ITEM_DEFS.clear()


def item_deferral():
    """Merged ArchiveDeferred of this item's lookups, or None."""
    if not ITEM_DEFS:
        return None
    from archive.core import merge_deferrals
    return merge_deferrals(list(ITEM_DEFS), "item lookups")


def defer_info(e) -> tuple:
    """(not_before, involves_wayback) for an item that failed with e: ArchiveDeferred -> e.not_before (round 3: also
    timeouts / busy / breaker_open from the high-level calls); a raw ArchiveBreakerOpen -> next breaker probe (Wayback);
    any other ArchiveTransient -> now + 600 s."""
    from common.eu_wayback import deferred_until, is_wayback_deferral
    nb = deferred_until(e)
    if nb:
        return nb, is_wayback_deferral(e)
    if getattr(e, "kind", "") == "breaker_open":
        try:
            from archive import ratelimit
            b = ratelimit.breaker_status()
            nb = float(b.get("last_probe") or time.time()) + float(getattr(ratelimit, "BREAKER_PROBE_EVERY", 1800.0))
        except Exception:  # noqa: BLE001
            nb = time.time() + 1800
        return max(nb, time.time() + 60), True
    return time.time() + 600, False


def as_deferral(fx, e, family, url=""):
    """Round 3: normalise a raw failure of a low-level call (wb_captures / _cc_query raise ArchiveTimeout,
    ArchiveBreakerOpen, ArchiveBusy, retryable ArchiveError) into an ArchiveDeferred with not_before, via the shared
    fetcher's own _as_deferral (typed .kind, never message parsing). Permanent errors (400/403/404/410) -> None."""
    from archive.core import ArchiveDeferred, ArchiveError, ArchiveTransient
    if isinstance(e, ArchiveDeferred):
        return e
    if not isinstance(e, ArchiveError) or (not isinstance(e, ArchiveTransient) and getattr(e, "permanent", False)):
        return None
    conv = getattr(fx, "_as_deferral", None)
    if conv is not None:
        return conv(e, family, url)
    return ArchiveDeferred(f"{family}: {e}", family=family, url=url, not_before=time.time() + 600,
                           reason=getattr(e, "kind", None) or "transient")


INCOMPLETE = Counter()   # round 3: docs accepted although another source failed (doc.incomplete), per reason


def _accept_incomplete(d, defs=()):
    """A doc returned while another source failed (doc.incomplete / lookup deferrals): ACCEPTED. A fuller copy would
    cost a re-lookup of every source after not_before (not cheap for these lanes), and the item already has a usable
    doc; counted in INCOMPLETE and runner.json instead of requeued."""
    dd = getattr(d, "deferral", None) if getattr(d, "incomplete", False) else None
    allds = ([dd] if dd is not None else []) + list(defs)
    if allds:
        for r in sorted({r for x in allds for r in (getattr(x, "reasons", None) or ["deferred"])}):
            INCOMPLETE[r] += 1
    return d


UNKNOWN_CAP = int(os.environ.get("EU_UNKNOWN_ERROR_CAP", "6"))   # round 5: unknown_error gaps come back hourly forever


def unknown_capped(target, key, e) -> bool:
    """True once item `key` has been deferred UNKNOWN_CAP times for unknown_error ONLY (no status / parse error / code
    bug in the shared fetcher: retried hourly with no module cap). The caller then records it as done-with-gaps
    (failed*.jsonl why=unknown_error_cap) instead of requeueing it again. Counts persist in <target>/unknown_defer.json."""
    rs = set(getattr(e, "reasons", None) or ([getattr(e, "reason", "")] if getattr(e, "reason", "") else []))
    if not rs or rs - {"unknown_error"}:
        return False
    f = STATE / target / "unknown_defer.json"
    try:
        c = json.loads(f.read_text())
    except Exception:  # noqa: BLE001
        c = {}
    c[key] = int(c.get(key, 0)) + 1
    tmp = f.with_suffix(".tmp"); tmp.write_text(json.dumps(c)); tmp.replace(f)
    return c[key] >= UNKNOWN_CAP


class Looked(list):
    """Captures of one lookup + the deferrals that made it incomplete (fbest raises them instead of a false miss)."""
    def __init__(self, it=(), deferrals=()):
        super().__init__(it)
        self.deferrals = list(deferrals)


def _note_listing(caps, sink=None):
    """A flagged CaptureList (shared v3) that was truncated by a deferral -> remember the deferral for this item."""
    if getattr(caps, "truncated", False) and getattr(caps, "deferral", None) is not None:
        ITEM_DEFS.append(caps.deferral)
        if sink is not None:
            sink.append(caps.deferral)
    return caps


def lookup_caps(fx, urls, match="exact", cc=True):
    """Captures for exact URLs: Common Crawl (if enabled) + Wayback CDX. Deferred / truncated lookups -> ITEM_DEFS
    (fbest then raises instead of returning a false miss); breaker-open Wayback -> ITEM_DEF += 1."""
    from archive.core import ArchiveDeferred, ArchiveError
    caps = Looked()
    for u in urls:
        if cc and fx.use_cc:
            try:
                caps += _note_listing(fx.cc_captures(u, match, on_error="skip"), caps.deferrals)
            except ArchiveDeferred as e:
                ITEM_DEFS.append(e); caps.deferrals.append(e)
            except Exception as e:  # noqa: BLE001
                log.info("cc lookup %s: %s", u[:100], str(e)[:120])
        try:
            caps += fx.wb_captures(u, match)
        except ArchiveError as e:   # round 3: timeout / breaker / busy / throttle -> deferral; 403/404 -> permanent gap
            d = as_deferral(fx, e, "wayback", u)
            if d is not None:
                ITEM_DEFS.append(d); caps.deferrals.append(d)
            else:
                log.info("wayback cdx %s: permanent %s", u[:100], str(e)[:120])
    return caps


def fbest(fx, caps, **kw):
    """fetch_best_ex for the current item (round 3; per-call FetchInfo, no fx.last_*). None ONLY if every source
    answered with nothing usable AND the item's own lookups were complete. Otherwise raises one merged ArchiveDeferred
    (fetch exception: throttle / timeout / busy / breaker_open, plus lookup deferrals of a truncated listing).
    A doc found while another source failed (doc.incomplete) is accepted (_accept_incomplete)."""
    from archive.core import merge_deferrals
    defs = list(getattr(caps, "deferrals", None) or [])
    d, info = fx.fetch_best_ex(caps, **kw) if caps else (None, None)
    if d is None:
        exc = getattr(info, "exception", None)
        if exc is not None:
            defs = [exc] + defs
        if defs:
            e = defs[0] if len(defs) == 1 else merge_deferrals(defs, "item fetch")
            if getattr(e, "fetch_info", None) is None:
                e.fetch_info = info
            raise e
        return None
    return _accept_incomplete(d, defs)


def cc_extra(fx, caps):
    """While Wayback is down: add CC captures of the same original URLs (stored candidate caps are Wayback-only)."""
    from archive import ratelimit
    if not fx.use_cc or ratelimit.wayback_available():
        return caps
    urls = list(dict.fromkeys(c.original_url for c in caps))[:2]
    out = Looked(caps, getattr(caps, "deferrals", ()))
    for u in urls:
        out += _cc_only(fx, u, out.deferrals)
    return out


def _cc_only(fx, u, sink=None):
    from archive.core import ArchiveDeferred
    try:
        return _note_listing(fx.cc_captures(u, "exact", on_error="skip"), sink)
    except ArchiveDeferred as e:
        ITEM_DEFS.append(e)
        if sink is not None:
            sink.append(e)
        return []
    except Exception:  # noqa: BLE001
        return []


def defer_log(target, key, why):
    with (STATE / target / "deferred_wayback.tsv").open("a", encoding="utf-8") as f:
        f.write(f"{key}\t{utcnow()}\t{why}\n")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def setup_logging(target: str) -> None:
    for d in (STATE / target, LOGS, UNM):
        d.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", "%Y-%m-%dT%H:%M:%S%z")
    log.setLevel(logging.INFO)
    if not log.handlers:
        for h in (logging.FileHandler(LOGS / f"archive_{target}.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)):
            h.setFormatter(fmt)
            log.addHandler(h)


def atomic_write(path: Path, rows: list) -> None:
    tmp = path.with_name("." + path.name[:-len(".jsonl")] + ".tmp.jsonl")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, path)


def pdf_to_text(b: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
        tf.write(b)
        tf.flush()
        p = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", tf.name, "-"], capture_output=True, timeout=300)
    t = p.stdout.decode("utf-8", "replace").replace("\f", "\n")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n ", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def html_to_text(b: bytes) -> str:
    from bs4 import BeautifulSoup
    s = BeautifulSoup(b, "lxml")
    for x in s(["script", "style", "nav", "header", "footer"]):
        x.decompose()
    root = s.select_one("div.documentContent") or s.select_one("#content") or s.body or s
    t = root.get_text("\n")
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def rtf_to_text(b: bytes) -> str:
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "x.rtf"
        src.write_bytes(b)
        subprocess.run(["soffice", "--headless", "--convert-to", "txt:Text (encoded):UTF8", "--outdir", d, str(src)],
                       capture_output=True, timeout=180)
        out = Path(d) / "x.txt"
        return out.read_text("utf-8", "replace").strip() if out.exists() else ""


# ----------------------------------------------------------------------------- robots (archived copy when live is unreachable)
_ROBOTS: dict = {}


def robots_for(fx: ArchiveFetcher, host: str) -> tuple[Optional[Robots], str]:
    """Live robots.txt is unreachable for these hosts (network block). Use the newest archived copy."""
    if host in _ROBOTS:
        return _ROBOTS[host]
    res = (None, "no archived robots.txt")
    for scheme_host in (f"https://{host}/robots.txt", f"https://{host.removeprefix('www.')}/robots.txt"):
        from archive.core import ArchiveTransient
        try:            # round 3: fetch_newest_ex -> (doc, info); info.exception = deferral when nothing usable
            d, info = fx.fetch_newest_ex(scheme_host, raise_deferred=True)
        except ArchiveTransient:
            raise            # 2026-10-18: deferred/unavailable is NOT "no robots.txt" - caller defers, nothing cached
        except Exception as e:  # noqa: BLE001
            d = None
            log.warning("robots %s: %s", scheme_host, e)
        if d and d.body and b"<html" not in d.body[:500].lower():
            res = (Robots(d.text()), f"archived {d.archive_source} {d.archive_timestamp}")
            break
    _ROBOTS[host] = res
    log.info("robots %s -> %s", host, res[1])
    return res


# ----------------------------------------------------------------------------- Austria
AT_STATE = {"BU": "1", "KA": "2", "NI": "3", "OB": "4", "SA": "5", "ST": "6", "TI": "7", "VO": "8", "WI": "9"}
AT_STATE_NAME = {"1": "Burgenland", "2": "Kärnten", "3": "Niederösterreich", "4": "Oberösterreich", "5": "Salzburg",
                 "6": "Steiermark", "7": "Tirol", "8": "Vorarlberg", "9": "Wien"}
AT_HOST = "www.ris.bka.gv.at"
AT_PREFIX = "www.ris.bka.gv.at/Dokumente/Gemeinderecht/"
AT_RE = re.compile(r"/Dokumente/Gemeinderecht/(GEMRE_([A-Z]{2})_(\d{5})_[^/]+)/\1\.(pdf|html|rtf)$", re.I)
MONTHS_DE = {m: i for i, m in enumerate(["jänner", "februar", "märz", "april", "mai", "juni", "juli", "august", "september",
                                          "oktober", "november", "dezember"], 1)}
MONTHS_DE["januar"] = 1


def at_norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    s = re.sub(r"\s*\(.*?\)|, Austria$", "", s)
    s = re.sub(r"\bSt\.\s*", "Sankt ", s)
    s = re.sub(r"\ba\.\s*d\.\s*", "an der ", s)
    return " ".join(s.lower().split())


class ATPlaces:
    def __init__(self) -> None:
        self.gkz = {r["gkz"]: r["name"] for r in csv.DictReader((HERE / "data" / "at_gkz_2026.csv").open(encoding="utf-8"))}
        byn = defaultdict(list)
        self.states = {}
        for r in csv.DictReader(CAND.open(encoding="utf-8")):
            if r["country_code"] != "AT":
                continue
            if r["admin_level"] == "municipality":
                byn[at_norm(r["place_name"])].append(r)
            elif r["iso_3166_2"]:
                self.states[r["iso_3166_2"]] = r
        self.byn = byn
        self.cand_by_pid = {r["place_id"]: r for rs in byn.values() for r in rs}
        dup = Counter(at_norm(v) for v in self.gkz.values())
        self.dup = {k for k, n in dup.items() if n > 1}

    def resolve(self, gkz: str) -> dict:
        st = gkz[0]
        iso = f"AT-{st}"
        base = dict(place_id=None, place_name=None, qid=None, iso_3166_2=iso, admin_level="municipality",
                    level="municipality", gkz=gkz, match=None, gkz_name=self.gkz.get(gkz))
        if gkz == "90101" or gkz.startswith("9"):  # Wien: city = Land
            s = self.states.get(iso, {})
            return dict(base, place_id=f"iso:{iso}", place_name="Wien", qid=s.get("qid") or None, admin_level="adm1",
                        level="municipality+state", match="gkz->wien=state")
        xp = XWALK.get("AT", gkz)   # shared crosswalk (at_gkz / Wikidata P964 + official list) preferred
        if xp:
            r = self.cand_by_pid.get(xp, {})
            return dict(base, place_id=xp, place_name=r.get("place_name") or self.gkz.get(gkz), qid=xp[3:],
                        match="gkz->crosswalk")
        name = self.gkz.get(gkz)
        if not name:
            return dict(base, match="gkz_unknown_2026")  # e.g. pre-2015 Styrian codes
        k = at_norm(name)
        c = self.byn.get(k, [])
        if len(c) == 1 and k not in self.dup:
            r = c[0]
            return dict(base, place_id=r["place_id"] or f"wd:{r['qid']}", place_name=r["place_name"], qid=r["qid"],
                        match="gkz->statistik_name->candidate")
        return dict(base, match="ambiguous_name" if c else "name_not_in_candidate")


def _wb_list(fx, url, match, **kw):
    """wb_captures for discovery listings: transient failures re-raised as ArchiveDeferred (not_before), permanent as is."""
    from archive.core import ArchiveError
    try:
        return fx.wb_captures(url, match, **kw)
    except ArchiveError as e:
        d = as_deferral(fx, e, "wayback", url)
        raise (d if d is not None else e)


def at_discover(fx: ArchiveFetcher) -> dict:
    caps = []
    try:
        if not USE_CC:
            raise RuntimeError("CC disabled (--no-cc: index.commoncrawl.org 504s / box-wide slot starvation)")
        cc = fx.cc_captures(AT_PREFIX, "prefix", on_error="skip", filters=["status:200"])
        log.info("AT CC captures: %d", len(cc))
        caps += cc
    except Exception as e:  # noqa: BLE001
        cc = None
        log.warning("AT CC listing failed: %s", e)
    if getattr(cc, "deferral", None) is not None:   # round 3: retryable gap -> discovery NOT complete, nothing written
        raise cc.deferral
    if getattr(cc, "truncated", False):             # permanent gaps only (400/404/410 crawl): final, logged
        log.warning("AT CC listing has permanent gaps (%s): %s", cc.truncated_reason, list(cc.errors)[:3])
    wb = _wb_list(fx, AT_PREFIX, "prefix", collapse="digest")
    log.info("AT Wayback captures: %d", len(wb))
    caps += wb
    rb, rb_src = robots_for(fx, AT_HOST)
    docs: dict = defaultdict(list)
    skipped = Counter()
    for c in caps:
        m = AT_RE.search(c.original_url.split("?")[0])
        if not m:
            skipped["pattern"] += 1
            continue
        if rb and not rb.can_fetch(UA_ROBOTS, c.original_url):
            skipped["robots"] += 1
            continue
        docs[m.group(1)].append(asdict(c))
    out = STATE / "at" / "candidates.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for k in sorted(docs):
            m = re.match(r"GEMRE_([A-Z]{2})_(\d{5})_", k, re.I)
            f.write(json.dumps({"key": k, "state": m.group(1).upper(), "gkz": m.group(2), "caps": docs[k]}, ensure_ascii=False) + "\n")
    info = {"captures": len(caps), "docs": len(docs), "skipped": skipped, "robots": rb_src, "at": utcnow()}
    (STATE / "at" / "discover.json").write_text(json.dumps(info, default=dict))
    return info


def at_title(text: str) -> str:
    lines, started = [], False
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            if started and len(" ".join(lines)) > 25:
                break
            continue
        started = True
        lines.append(s)
        if len(lines) >= 8:
            break
    return " ".join(" ".join(lines).split())[:500]


def at_date(t: str) -> Optional[str]:
    m = re.search(r"vom\s+(\d{1,2})\.\s*([A-Za-zÄäöü]+)\s+(\d{4})", t)
    if m and m.group(2).lower() in MONTHS_DE:
        return f"{m.group(3)}-{MONTHS_DE[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?((?:19|20)\d\d)\b", t)
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(1)) <= 31:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def at_fetch_one(fx, cand) -> tuple[Optional[dict], str]:
    caps = [Capture(**c) for c in cand["caps"]]
    fmt_order = ("pdf", "html", "rtf")
    for ext in fmt_order:
        cs = [c for c in caps if c.original_url.split("?")[0].lower().endswith("." + ext)]
        if not cs:
            continue
        val = (lambda d: d.body[:4] == b"%PDF") if ext == "pdf" else \
              (lambda d: b"{\\rtf" in d.body[:20]) if ext == "rtf" else (lambda d: len(d.body) > 500)
        d = fbest(fx, cc_extra(fx, cs), max_tries=3, validator=val)
        if not d:
            continue
        text = pdf_to_text(d.body) if ext == "pdf" else html_to_text(d.body) if ext == "html" else rtf_to_text(d.body)
        if len(text) >= 80:
            return {"doc": d, "text": text, "ext": ext}, "ok"
    return None, "no_good_capture"


def at_record(cand, got, pl) -> dict:
    d, text, ext = got["doc"], got["text"], got["ext"]
    title = at_title(text)
    key = cand["key"]
    return {
        "place_id": pl["place_id"], "country_code": "AT", "doc_id": f"at_ris_gr:{key}",
        "source_platform": "at_ris_gemeinderecht", "source_url": d.original_url, "doc_type": "ordinance",
        "language": "de", "title_native": title or key, "number": key,
        "adopted_date": at_date(title), "published_date": None, "effective_date": None, "in_force": None,
        "consolidated": False, "content_format": "pdf_text" if ext == "pdf" else "html" if ext == "html" else "docx_text",
        "text": text, "retrieved_at": utcnow(),
        "place_name": pl["place_name"], "qid": pl["qid"], "iso_3166_2": pl["iso_3166_2"], "admin_level": pl["admin_level"],
        "platform": "at_ris", "platform_place_id": cand["gkz"],
        # extras
        "gkz": cand["gkz"], "gkz_name_2026": pl.get("gkz_name"), "state": AT_STATE_NAME.get(cand["gkz"][0]),
        "ris_state_code": cand["state"], "ris_dokumentnummer": key, "level": pl["level"], "place_match": pl["match"],
        "text_source": ext, "source_format": "rtf" if ext == "rtf" else ext,
        "rights": "amtliches Werk (§ 7 UrhG); RIS data CC BY 4.0",
        **provenance_fields(d),
    }


# ----------------------------------------------------------------------------- Poland KP / LB / WP
PL_HOSTS = {"KP": ("edzienniki.bydgoszcz.uw.gov.pl", "PL-04", "Kujawsko-Pomorskiego"),
            "LB": ("edziennik.lublin.uw.gov.pl", "PL-06", "Lubelskiego"),
            "WP": ("edziennik.poznan.uw.gov.pl", "PL-30", "Wielkopolskiego"),
            # OP (2026-10-13): live host 403 > 6 h (pl_run archive_request_OP.json); candidates_OP.jsonl is built from
            # the live pass-1 queue minus done (op_candidates()), not from a prefix listing; captures per item.
            "OP": ("duwo.opole.uw.gov.pl", "PL-16", "Opolskiego")}
PL_DISCOVER = ("KP", "LB", "WP")
PL_RE = [(1, re.compile(r"/WDU_\w/(\d{4})/(\d+)/akt\.pdf$", re.I)),
         (2, re.compile(r"/WDU_\w/(\d{4})/(\d+)/Oryginal/akt\.pdf$", re.I)),
         (3, re.compile(r"/GetActPdf\.ashx\?year=(\d{4})&book=0&position=(\d+)$", re.I))]
MONTHS_PL = {m: i for i, m in enumerate(["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia",
                                          "września", "października", "listopada", "grudnia"], 1)}
PL_HEAD = re.compile(r"^(UCHWAŁA|ZARZĄDZENIE|ROZPORZĄDZENIE|OBWIESZCZENIE|POSTANOWIENIE|POROZUMIENIE|ANEKS|STATUT|INFORMACJA|"
                     r"OGŁOSZENIE|DECYZJA|SPRAWOZDANIE|ROZSTRZYGNIĘCIE|WYROK|UMOWA|REGULAMIN|KOMUNIKAT)\b", re.I)


def pl_discover(fx: ArchiveFetcher) -> dict:
    info = {}
    for woj in PL_DISCOVER:
        host, iso, _ = PL_HOSTS[woj]
        caps = []
        try:
            if not USE_CC:
                raise RuntimeError("CC disabled (--no-cc)")
            cc = fx.cc_captures(host + "/", "prefix", on_error="skip", filters=["status:200"])
            log.info("%s CC captures: %d", woj, len(cc))
            caps += cc
        except Exception as e:  # noqa: BLE001
            cc = None
            log.warning("%s CC listing failed: %s", woj, e)
        if getattr(cc, "deferral", None) is not None:  # round 3: retryable gap -> this voivodeship NOT complete
            raise cc.deferral
        if getattr(cc, "truncated", False):
            log.warning("%s CC listing has permanent gaps (%s): %s", woj, cc.truncated_reason, list(cc.errors)[:3])
        wb = _wb_list(fx, host + "/", "prefix", collapse="digest")
        log.info("%s Wayback captures: %d", woj, len(wb))
        caps += wb
        rb, rb_src = robots_for(fx, host)
        acts: dict = defaultdict(list)
        sk = Counter()
        for c in caps:
            u = c.original_url
            path = re.sub(r"^https?://[^/]+", "", u)
            if path.lower().startswith("/login"):
                sk["robots_login"] += 1
                continue
            if rb and not rb.can_fetch(UA_ROBOTS, u):
                sk["robots"] += 1
                continue
            for prio, rx in PL_RE:
                m = rx.search(path)
                if m:
                    d = asdict(c)
                    d["prio"] = prio
                    acts[(int(m.group(1)), int(m.group(2)))].append(d)
                    break
            else:
                sk["pattern"] += 1
        with (STATE / "pl" / f"candidates_{woj}.jsonl").open("w", encoding="utf-8") as f:
            for (y, p) in sorted(acts, key=lambda k: (-k[0], -k[1])):
                f.write(json.dumps({"key": f"POL_WOJ_{woj}/{y}/{p}", "woj": woj, "year": y, "pos": p,
                                    "caps": acts[(y, p)]}, ensure_ascii=False) + "\n")
        info[woj] = {"captures": len(caps), "acts": len(acts), "skipped": dict(sk),
                     "robots": rb_src + ("; assumed ABC PRO platform default 'Disallow: /login'" if not rb else "")}
    info["at"] = utcnow()
    (STATE / "pl" / "discover.json").write_text(json.dumps(info))
    return info


def pl_head(text: str) -> tuple[str, Optional[str]]:
    """Rebuild the catalog-style title from the act's first lines: 'Uchwała Nr X Rady Gminy Y z dnia ... w sprawie ...'."""
    lines = [ln.strip() for ln in text.splitlines()]
    start = next((i for i, ln in enumerate(lines[:60]) if PL_HEAD.match(ln)), None)
    if start is None:
        return "", None
    parts, seen_sprawie = [], False
    for ln in lines[start:start + 25]:
        if not ln:
            if seen_sprawie:
                break
            continue
        if re.match(r"^(Na podstawie|§\s*1|Działając|W związku)", ln):
            break
        parts.append(ln)
        if re.match(r"^w sprawie", ln, re.I):
            seen_sprawie = True
    title = " ".join(" ".join(parts).split())
    typ = PL_HEAD.match(title).group(1).capitalize()
    return title[:600], typ


def pl_date(t: str) -> Optional[str]:
    m = re.search(r"z dnia\s+(\d{1,2})\s+([a-ząćęłńóśźż]+)\s+(\d{4})", t, re.I)
    if m and m.group(2).lower() in MONTHS_PL:
        return f"{m.group(3)}-{MONTHS_PL[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return None


def pl_fetch_one(fx, cand) -> tuple[Optional[dict], str]:
    if not cand.get("caps") and cand.get("urls"):      # OP: built from the live queue, captures looked up per item
        d = fbest(fx, lookup_caps(fx, cand["urls"]), max_tries=3, validator=lambda d: d.body[:4] == b"%PDF")
        if d:
            text = pdf_to_text(d.body)
            if len(text) >= 100:
                return {"doc": d, "text": text, "prio": 4}, "ok"
        return None, "no_good_capture"
    caps = [Capture(**{k: v for k, v in c.items() if k != "prio"}) for c in sorted(cand["caps"], key=lambda c: c["prio"])]
    by = defaultdict(list)
    for c, raw in zip(caps, sorted(cand["caps"], key=lambda c: c["prio"])):
        by[raw["prio"]].append(c)
    for prio in sorted(by):
        d = fbest(fx, cc_extra(fx, by[prio]), max_tries=3, validator=lambda d: d.body[:4] == b"%PDF")
        if d:
            text = pdf_to_text(d.body)
            if len(text) >= 100:
                return {"doc": d, "text": text, "prio": prio}, "ok"
    return None, "no_good_capture"


# ----------------------------------------------------------------------------- generic fetch loop
def op_candidates() -> int:
    """Remaining live OP pass-1 acts (queue_OP minus done_OP / pl_done.sqlite) -> candidates_OP.jsonl (rebuilt)."""
    import sqlite3
    live = STAGE / "_state" / "pl"
    done = set((live / "done_OP.txt").read_text().split()) if (live / "done_OP.txt").exists() else set()
    try:
        c = sqlite3.connect(f"file:{live / 'pl_done.sqlite'}?mode=ro", uri=True)
        done |= {r[0] for r in c.execute("SELECT eli FROM done WHERE eli LIKE 'POL_WOJ_OP/%'")}
    except Exception:  # noqa: BLE001
        pass
    n = 0
    tmp = STATE / "pl" / "candidates_OP.jsonl.tmp"
    with tmp.open("w", encoding="utf-8") as f:
        for ln in (live / "queue_OP.jsonl").open(encoding="utf-8"):
            it = json.loads(ln)
            if it["eli"] in done:
                continue
            u = f"https://duwo.opole.uw.gov.pl/api/eli/acts/{it['eli']}/text.pdf"
            f.write(json.dumps({"key": it["eli"], "woj": "OP", "year": it["year"], "pos": it["pos"], "caps": [],
                                "urls": [u, u.replace("https://", "http://", 1)]}, ensure_ascii=False) + "\n")
            n += 1
    os.replace(tmp, STATE / "pl" / "candidates_OP.jsonl")
    return n


def load_done(p: Path) -> set:
    return set(p.read_text().split()) if p.exists() else set()


def fetch(target: str, limit: Optional[int], test: Optional[int], wojs=None, skip=frozenset()) -> dict:
    """Returns {"todo": n, "deferred": [keys]} (deferred = Wayback breaker open; not done, not failed)."""
    fx = new_fx()
    deferred = []
    sfx = "_test" if test else ""
    if target == "at":
        files = [STATE / "at" / "candidates.jsonl"]
        places = ATPlaces()
    else:
        files = [STATE / "pl" / f"candidates_{w}.jsonl" for w in (wojs or PL_DISCOVER)]
        import pl_dzienniki as P  # PlaceMap, in_pass1 rules, issuer parsing
        pm = P.PlaceMap()
    done_p = STATE / target / f"done{sfx}.txt"
    done = load_done(done_p)
    bno_p = STATE / target / f"batchno{sfx}.txt"
    bno = int(bno_p.read_text()) if bno_p.exists() else 0
    todo = []
    for fp in files:
        if not fp.exists():
            log.error("missing %s (run discover)", fp)
            continue
        if target == "at":
            todo += [ln for ln in fp.open(encoding="utf-8")]
        else:
            # interleave hosts so each gets steady progress
            todo.append([ln for ln in fp.open(encoding="utf-8")])
    if target == "pl":
        inter = []
        for i in range(max((len(x) for x in todo), default=0)):
            for x in todo:
                if i < len(x):
                    inter.append(x[i])
        todo = inter
    todo = [ln for ln in todo if json.loads(ln)["key"] not in done and json.loads(ln)["key"] not in skip]
    if test:
        random.seed(7)
        todo = random.sample(todo, min(test, len(todo)))
    if limit:
        todo = todo[:limit]
    log.info("%s fetch: todo=%d done=%d", target, len(todo), len(done))
    rows, skipped, reasons = [], [], Counter()
    t0 = time.time()
    tf = time.time()
    import signal
    signal.signal(signal.SIGTERM, _on_term)
    paused = 0.0     # 2026-10-18 v3: an item deferred on Wayback (ArchiveDeferred) -> flush, return, runner resumes after it
    dnb = {}         # key -> not_before of deferred items (runner skips them until then)
    with done_p.open("a", encoding="utf-8") as df, (STATE / target / f"failed{sfx}.jsonl").open("a", encoding="utf-8") as ff:
        for i, ln in enumerate(todo, 1):
            halt = STOP[0] or bool(paused)
            if halt:
                i -= 1
            cand = json.loads(ln) if not halt else None
            item_reset()
            try:
                if cand is None:
                    pass
                elif target == "at":
                    got, why = at_fetch_one(fx, cand)
                    if got:
                        rows.append(at_record(cand, got, places.resolve(cand["gkz"])))
                else:
                    got, why = pl_fetch_one(fx, cand)
                    if got:
                        rec, why = pl_record(P, pm, cand, got)
                        if rec:
                            rows.append(rec)
                if cand is not None and why == "no_good_capture" and ITEM_DEFS:
                    raise item_deferral()          # lookups were throttled: not a genuine miss
                if cand is not None and why == "no_good_capture" and ITEM_DEF[0]:   # legacy (round 3: never set)
                    why = DEFERRED
                if cand is not None and why == DEFERRED:
                    deferred.append(cand["key"])
                    reasons[why] += 1
                    defer_log(target, cand["key"], f"wayback breaker open ({ITEM_DEF[0]} skipped)")
                elif cand is not None and why != "ok":
                    skipped.append(cand["key"])
                    reasons[why] += 1
                    if why == "no_good_capture":
                        ff.write(json.dumps({"key": cand["key"], "why": why, "at": utcnow()}) + "\n")
                        ff.flush()
            except Exception as e:  # noqa: BLE001  (ArchiveError 'giving up' etc.: not marked done -> retried on resume)
                from archive.core import ArchiveTransient
                if isinstance(e, ArchiveTransient) and unknown_capped(target, cand["key"], e):
                    skipped.append(cand["key"]); reasons["unknown_error_cap"] += 1     # done-with-gaps
                    ff.write(json.dumps({"key": cand["key"], "why": "unknown_error_cap", "error": str(e)[:300],
                                         "at": utcnow()}) + "\n")
                    ff.flush()
                elif isinstance(e, ArchiveTransient) or ITEM_DEF[0]:
                    nb, wbk = defer_info(e)
                    deferred.append(cand["key"])
                    dnb[cand["key"]] = nb
                    reasons[DEFERRED] += 1
                    defer_log(target, cand["key"], f"until {time.strftime('%H:%M:%S', time.localtime(nb))} {str(e)[:110]}")
                    if wbk and not paused:
                        paused = nb
                        log.info("%s: Wayback deferred until %s; pausing target at %d/%d", target,
                                 time.strftime("%H:%M:%S %Z", time.localtime(nb)), i, len(todo))
                else:
                    reasons["error"] += 1
                    log.warning("%s %s: %s", target, cand["key"], str(e)[:200])
                    ff.write(json.dumps({"key": cand["key"], "error": str(e)[:300], "at": utcnow()}) + "\n")
                    ff.flush()
            n_buf = len(rows) + len(skipped)
            if n_buf and (n_buf >= BATCH or i == len(todo) or halt or time.time() - tf >= FLUSH_SECS) or \
                    (not n_buf and reasons and (i == len(todo) or halt or time.time() - tf >= FLUSH_SECS)):
                if not n_buf:     # only deferrals since the last flush: just log progress
                    tf = time.time()
                    log.info("%s progress %s | %d/%d", target, dict(reasons), i, len(todo))
                    reasons = Counter()
                    if halt:
                        log.info("%s %s: exiting (resume with the same command)", target, "SIGTERM" if STOP[0] else "Wayback deferred")
                        return {"todo": len(todo), "deferred": deferred, "stopped": STOP[0], "paused_until": paused,
                                "deferred_nb": dnb}
                    continue
                tf = time.time()
                bno += 1
                st = flush(target, bno, rows, test)
                for k in [r["doc_id_key"] for r in rows] + skipped:
                    df.write(k + "\n")
                df.flush()
                os.fsync(df.fileno())
                bno_p.write_text(str(bno))
                rate = i / max(time.time() - t0, 1)
                log.info("%s batch %05d matched=%d unmatched=%d skipped=%s | %d/%d (%.2f doc/s, ETA %.1fh)", target, bno,
                         st["matched"], st["unmatched"], dict(reasons), i, len(todo), rate, (len(todo) - i) / rate / 3600)
                rows, skipped, reasons = [], [], Counter()
            if halt:
                log.info("%s %s: buffer flushed, exiting (resume with the same command)", target, "SIGTERM" if STOP[0] else "Wayback deferred")
                return {"todo": len(todo), "deferred": deferred, "stopped": STOP[0], "paused_until": paused,
                        "deferred_nb": dnb}
    log.info("%s fetch finished (deferred %d)", target, len(deferred))
    return {"todo": len(todo), "deferred": deferred, "stopped": False, "paused_until": paused, "deferred_nb": dnb}


def pl_record(P, pm, cand, got) -> tuple[Optional[dict], str]:
    d, text = got["doc"], got["text"]
    woj = cand["woj"]
    host, iso, gen = PL_HOSTS[woj]
    title, typ = pl_head(text)
    if not typ:
        return None, "no_title"
    org = P.issuer_from_title(title, typ)
    lvl = P.organ_level(org) if org else "unknown"
    tl = typ.lower()
    cons = tl == "obwieszczenie" and re.search(r"jednolit", title, re.I)
    if not (tl in P.TYPES_P1 or cons):
        return None, "type"
    if lvl not in ("gmina", "powiat", "voivodeship", "voivode"):
        return None, "organ"
    if not cons and P.BUDGET.search(title):
        return None, "budget"
    pl = pm.resolve(woj, org, lvl)
    m = re.search(r"\bnr\.?\s+(\S+)", title[:120], re.I)
    rec = {
        "place_id": pl["place_id"], "country_code": "PL", "doc_id": cand["key"], "source_platform": "pl_edziennik",
        "source_url": d.original_url, "doc_type": "gazette_act", "language": "pl", "title_native": title,
        "number": f"Dz. Urz. Woj. {gen} z {cand['year']} r. poz. {cand['pos']}",
        "adopted_date": pl_date(title), "published_date": None, "effective_date": None, "in_force": None,
        "consolidated": bool(cons), "content_format": "pdf_text", "text": text, "retrieved_at": utcnow(),
        "place_name": pl["place_name"], "qid": pl["qid"], "iso_3166_2": pl["iso_3166_2"],
        "admin_level": pl["admin_level"] or pl["level"], "platform": "pl_edziennik", "platform_place_id": pl["teryt"],
        "act_type": typ, "act_number": m.group(1) if m else None, "status": None,
        "issuing_body_name": org, "issuing_body_code": pl["teryt"], "issuing_body_qid": pl["qid"],
        "level": pl["level"], "place_match": pl["match"], "toponym": pl.get("toponym"),
        "voivodeship": woj, "journal": host, "eli": cand["key"], "year": cand["year"], "position": cand["pos"],
        "pdf_url": d.original_url, "text_source": "pdf", "title_source": "pdf_first_lines",
        "pdf_capture_kind": {1: "akt.pdf", 2: "Oryginal/akt.pdf", 3: "GetActPdf.ashx", 4: "api/eli/text.pdf"}[got["prio"]],
        "withdrawn_date": None, "rights": "official act; not subject to copyright (art. 4 Polish Copyright Act)",
        **provenance_fields(d),
    }
    return rec, "ok"


def flush(target: str, bno: int, rows: list, test) -> Counter:
    cc = "AT" if target == "at" else "PL"
    tagp = ("atgr" if target == "at" else "pldz_KPLBWP") + f"_archive_b{bno:05d}_"
    st = Counter()
    by = defaultdict(list)
    unm = []
    for r in rows:
        r["doc_id_key"] = r["doc_id"].removeprefix("at_ris_gr:")
        (by[r["place_id"]] if r["place_id"] else unm).append(r)
    stage = STAGE / "_test_archive" if test else STAGE
    for pid, rs in by.items():
        w = StagedWriter(stage, cc, pid, batch_prefix=tagp, chunk=10 ** 9)
        for r in rs:
            rec = {k: v for k, v in r.items() if k != "doc_id_key"}
            err = w.add(rec)
            if err:
                (STAGE / "_invalid").mkdir(exist_ok=True)
                atomic_write(STAGE / "_invalid" / f"{schema.place_key(pid)}.{tagp}{r['doc_id_key'].replace('/', '_')}.jsonl",
                             [dict(rec, _errors=err)])
                log.warning("invalid %s: %s", r["doc_id"], err)
            else:
                st["matched"] += 1
        w.flush()
    if unm:
        d = (STAGE / "_test_archive" / "_unmatched") if test else UNM
        d.mkdir(parents=True, exist_ok=True)
        atomic_write(d / f"{target}_archive_unmatched_b{bno:05d}.jsonl",
                     [{k: v for k, v in r.items() if k != "doc_id_key"} for r in unm])
        st["unmatched"] += len(unm)
    return st


def status() -> None:
    for t in ("at", "pl"):
        dj = STATE / t / "discover.json"
        disc = json.loads(dj.read_text()) if dj.exists() else {}
        nd = len(load_done(STATE / t / "done.txt"))
        print(f"== {t}: discover={json.dumps(disc, ensure_ascii=False)[:600]}\n   done={nd}")
    cnt = Counter()
    places = defaultdict(set)
    for cc, pat in (("AT", "*.atgr_archive_*.jsonl"), ("PL", "*.pldz_KPLBWP_archive_*.jsonl")):
        for f in (STAGE / cc).glob(pat):
            n = sum(1 for _ in f.open(encoding="utf-8"))
            cnt[cc] += n
            places[cc].add(f.name.split(".")[0])
    for cc in ("AT", "PL"):
        print(f"{cc}: matched docs={cnt[cc]} distinct places={len(places[cc])}")
    for t in ("at", "pl"):
        u = list(UNM.glob(f"{t}_archive_unmatched_*.jsonl"))
        rows = [json.loads(l) for f in u for l in f.open(encoding="utf-8")]
        print(f"{t} unmatched docs={len(rows)} by match={Counter(r.get('place_match') for r in rows).most_common(6)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["discover", "fetch", "all", "status"])
    ap.add_argument("target", nargs="?", choices=["at", "pl"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--test", type=int)
    ap.add_argument("--no-cc", action="store_true", help="Wayback only (NOT while the Wayback breaker is open: CC is the fallback)")
    a = ap.parse_args()
    if a.no_cc:
        global USE_CC
        USE_CC = False
    if a.cmd == "status":
        return status()
    setup_logging(a.target)
    fx = new_fx()
    cand = STATE / a.target / ("candidates.jsonl" if a.target == "at" else "candidates_WP.jsonl")
    if a.cmd == "discover" or (a.cmd == "all" and not cand.exists()):
        info = at_discover(fx) if a.target == "at" else pl_discover(fx)
        log.info("%s discover: %s", a.target, json.dumps(info, ensure_ascii=False, default=dict))
    if a.cmd in ("fetch", "all"):
        fetch(a.target, a.limit, a.test)


if __name__ == "__main__":
    main()
