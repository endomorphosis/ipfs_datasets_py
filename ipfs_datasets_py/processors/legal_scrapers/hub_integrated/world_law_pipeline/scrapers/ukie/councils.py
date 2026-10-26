#!/usr/bin/env python3
"""Council-website local law for the ukie lane: byelaws + public spaces protection orders (PSPOs).

Live mode (robots.txt RFC 9309 + Crawl-delay, >= 2 s per host, https, same site only, no search forms/logins):
  homepage + /byelaws-style hints + sitemap URLs matching byelaw|bye-law|pspo|public-spaces-protection,
  BFS over nav-matching links (depth <= 3, <= 80 pages), then PDF / DOCX / HTML documents.
Archive mode (robots disallow / unreachable robots, 401/403/429/WAF challenge on the homepage):
  Wayback/Common Crawl through the shared box-wide limiter (pipeline/archive, lane 'ukie'); records tagged
  archive_source/archive_timestamp/... and, when robots disallows live, source_policy=archived_robots_disallowed.
doc_id = ukbyelaw:<sha1(url)[:20]> (same scheme as scrapers/eu/council_docs.py, so re-crawls of a URL the EU lane
already published merge by doc_id instead of duplicating), ukpspo:<sha1(url)[:20]> for PSPOs.
Image-only PDFs: not OCR'd; listed in staging/ukie/_state/needs_ocr/notext_urls.jsonl (same line format as the EU
lane's council_gb/notext_urls.jsonl that ocr/ocr_gb.py consumes).
Archive throttle deferral (2026-10-18, Normalizer change to pipeline/archive): on 429/5xx, or while a host is cooling
  down, ArchiveFetcher raises archive.ArchiveDeferred (subclass of ArchiveTransient) with e.not_before instead of retrying.
  The high-level calls (fetch_newest/fetch_best/list_captures/cc_captures) swallow it, so every archive call goes through
  archive_call(), which sees the raised ArchiveDeferred via a per-instance wrapper of fx._get (DeferTracker). A deferred
  item (archive doc URL, or '__discover__' for the archive discovery of a blocked site) is recorded in the state db table
  archive_deferrals with its not_before, the run moves on to the next item (no sleep, no retry), and the place gets
  status 'deferred' (never done/blocked/partial while items are pending). --archive-queue picks 'deferred' places up again
  once due: places not yet due go to the end of the queue and are re-visited once after the last place if due by then;
  the rest wait for a later pass (run_*.sh: `councils.py next-due` -> seconds until the earliest due place).
  Wayback breaker open / slot busy (plain ArchiveTransient) is deferred the same way for TRANSIENT_DEFER_S.
Usage: python3 councils.py run --places wd:Q1,wd:Q2 [--archive-docs 12] | status | next-due --places-file F
       | select-parish-archive --out F
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.util import (LANE, STAGE, STATE_DIR, Blocked, PoliteSession, State, StopRun, append_jsonl,  # noqa: E402
                         get_logger, guard, utcnow)
from places import Places, place_codes  # noqa: E402
from archive.staging import StagedWriter, provenance_fields  # noqa: E402
from archive.core import ArchiveDeferred, ArchiveTransient  # noqa: E402

log = get_logger("ukie_councils")
NAV = re.compile(r"bye-?\s?laws?|byelaw|public[\s_-]*spaces?[\s_-]*protection|\bpspos?\b", re.I)
DOC = NAV
PSPO = re.compile(r"public[\s_-]*spaces?[\s_-]*protection|\bpspos?\b", re.I)
SKIP = re.compile(r"consultation|\bdraft\b|\bmap\s*\d+|\(map|[-_]map\d+|\bschedule \d+ map|survey|equality (impact|analysis)|\beqia\b|privacy|cookie|"
                  r"questionnaire|feedback form|minutes|agenda|\bmaps?\b|plan \(pdf|cabinet report|press release", re.I)
HINTS = ["/byelaws", "/bye-laws", "/byelaw", "/council-and-democracy/byelaws", "/your-council/byelaws",
         "/council-and-democracy/constitution-and-byelaws", "/byelaws-and-public-spaces-protection-orders",
         "/public-spaces-protection-orders", "/public-space-protection-orders", "/pspo", "/pspos",
         "/community-safety/public-spaces-protection-orders", "/environment/public-spaces-protection-orders",
         "/dog-control-orders", "/dogs/public-spaces-protection-orders"]
# crawling may pass through consultation/news pages (orders are often linked only there); they are never staged
SKIP_NAV = re.compile(r"privacy|cookie|minutes|agenda|press release|survey|questionnaire|feedback form|"
                      r"\bmaps?\b|equality (impact|analysis)|\beqia\b", re.I)
LAWISH = re.compile(r"\border\b|bye|sealed|schedule|regulation|\brules\b|prohibit|control|restrict|pspo|"
                    r"designat|variation|extension|fodhl|\bdogs?\b|alcohol|fouling|leads|exclusion", re.I)
GA = re.compile(r"\b(fodhl[ií]the|comhairle|an tacht|d[ée]anfar|faoi alt)\b", re.I)
# second-tier topic sections where councils file byelaws/PSPOs without saying so in the menu (followed to depth <= 2,
# only after the byelaw/PSPO frontier is exhausted)
TOPIC = re.compile(r"\benvironment\b|community[\s_-]*safety|anti[\s_-]*social|\bdogs?\b|dog[\s_-]*(control|warden)|"
                   r"your[\s_-]*council|council[\s_-]*and[\s_-]*democracy|about[\s_-]*the[\s_-]*council|"
                   r"policies|strategies|street[\s_-]*drinking|\bparks?\b|open[\s_-]*spaces|licensing|"
                   r"environmental[\s_-]*health|crime|nuisance|regulations|legal|cemeter(y|ies)|burial|allotments?|"
                   r"governance|documents|recreation[\s_-]*ground|playing[\s_-]*fields?|"
                   r"\ba[\s-]?(?:to[\s-]?)?z\b|/(?:a-z|az|a-to-z|services)/?$", re.I)
DOC_EXT = re.compile(r"\.(pdf|docx)(\?|$)", re.I)
A_RE = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']?([^\"' >]+)[^>]*>(.*?)</a>", re.I | re.S)
MAX_PAGES, MAX_DEPTH, MAX_PDF = 80, 3, 40 * 1024 * 1024
PHASE2_PAGES = 25
# phase 2 (town/parish/community councils): a doc is staged under the parish only if it was made by a local
# council of that tier; PSPOs (a principal-council power) and district/county byelaws mirrored on parish sites are skipped
PARISH_MAKER = re.compile(r"\b(parish|town|community|village|neighbourhood|city)\s+council\b|parish meeting|"
                          r"cyngor\s+(cymuned|tref|dinas)|burial\s+(board|committee|authority)|joint burial", re.I)
PRINCIPAL_MAKER = re.compile(r"\b(district|borough|county|county borough|metropolitan borough)\s+council\b", re.I)
OCR_LIST = STATE_DIR / "needs_ocr" / "notext_urls.jsonl"
TRANSIENT_DEFER_S = 900.0     # requeue delay when the archive is unavailable without a not_before (breaker open, busy)
DISCOVER_KEY = "__discover__"
UNKNOWN_ERROR_MAX_TRIES = 6   # requeues of an 'unknown_error' gap before it is resolved as gave_up (done with gaps)
QUEUE_STATUSES = ("blocked", "done_robots_docs", "deferred")
RIGHTS = "official publication of the council (UK: OGL v3.0 / Crown or council copyright)"


def site_key(host: str) -> str:
    p = (host or "").lower().split(".")
    return ".".join(p[-3:]) if len(p) > 2 and p[-2] in ("co", "gov", "org", "ac", "net") else ".".join(p[-2:])


def strip_html(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|noscript|nav|header|footer)\b.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</tr>", "\n", h)
    t = unescape(re.sub(r"<[^>]+>", " ", h))
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n\n", t)).strip()


def clean_title(t: str, url: str) -> str:
    t = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()
    t = re.sub(r"\s*\(?(pdf|docx?|word)[^)]*\)?\s*$", "", t, flags=re.I).strip()
    t = re.sub(r"\s*(opens in (a )?new (window|tab)|\[?\d+(\.\d+)?\s*[kKmM]B\]?)\s*", " ", t).strip(" ,-|")
    if len(t) < 6 or t.lower() in ("download", "view", "here", "click here", "read more", "link"):
        t = Path(urlparse(url).path).stem.replace("-", " ").replace("_", " ").strip() or url
    return t[:300]


def h1_title(html: str, url: str) -> str:
    for h in re.findall(r"(?is)<h1[^>]*>(.*?)</h1>", html):
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)).strip()
        if t and len(t) > 3 and not re.search(r"cookie|consent|javascript|skip to|homepage|\.gov\.uk|\.ie\b|"
                                              r"^(menu|search|home)$", t, re.I):
            return t
    t = re.sub(r"\s+", " ", unescape((re.findall(r"(?is)<title>(.*?)</title>", html) or [url])[0])).strip()
    return re.split(r"\s+[|\u2013\u2014-]\s+", t)[0] or url


def kind_of(url: str, title: str, text: str) -> str:
    """local_instrument_kind from the content (doc_id prefix stays URL/title based so ids never change)."""
    head = text[:6000]
    if PSPO.search(title) or re.search(r"public spaces? protection order", head, re.I):
        return "pspo"
    if re.search(r"\bbye-?\s?laws?\b", title + " " + head, re.I):
        return "byelaw"
    return "pspo" if PSPO.search(url) else "byelaw"


HTML_DUP = re.compile(r"[?#].*$")


def doc_key(u: str) -> str:
    return hashlib.sha1(u.encode()).hexdigest()[:20]


def extract(body: bytes):
    """-> (text, fmt, image_only)"""
    with tempfile.NamedTemporaryFile(suffix=".bin", dir="/tmp") as tf:
        tf.write(body)
        tf.flush()
        if body[:4] == b"%PDF":
            o = subprocess.run(["pdftotext", "-q", "-enc", "UTF-8", "-layout", tf.name, "-"], capture_output=True,
                               timeout=180)
            txt = o.stdout.decode("utf-8", "replace").strip()
            return txt, "pdf_text", len(re.sub(r"\s", "", txt)) < 150
        if body[:2] == b"PK":
            try:
                with zipfile.ZipFile(tf.name) as z:
                    x = z.read("word/document.xml").decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                return "", "docx_text", False
            x = re.sub(r"</w:p>", "\n", x)
            return unescape(re.sub(r"<[^>]+>", "", x)).strip(), "docx_text", False
    return "", "pdf_text", False


def is_law_html(txt: str) -> bool:
    return len(txt) > 800 and bool(
        re.search(r"\b(byelaws?|bye-laws?)\b.{0,4000}\b(made|confirm|under section|interpretation)", txt, re.I | re.S)
        or re.search(r"public spaces protection order.{0,4000}\b(section 59|anti-social behaviour, crime and "
                     r"policing act|prohibit|requirement)", txt, re.I | re.S))


class DeferTracker:
    """Records every ArchiveDeferred raised inside fx._get (per-instance wrapper; the shared module is not touched)."""

    def __init__(self, fx):
        self.events = []
        orig = fx._get

        def _get(*a, **k):
            try:
                return orig(*a, **k)
            except ArchiveDeferred as e:
                self.events.append(e)
                raise
        fx._get = _get
        fx._ukie_defer = self


def _tracker(fx):
    return getattr(fx, "_ukie_defer", None) or DeferTracker(fx)


class Deferral:
    """incomplete=True: a doc WAS returned (stage it) but another source failed transiently (doc.incomplete);
    keep the requeue so a later pass tries for a complete fetch. kind: archive reason (throttled, timeout, ...)."""

    def __init__(self, not_before, host=None, status=None, reason="", kind=None, incomplete=False):
        self.not_before, self.host, self.status, self.reason = not_before, host, status, reason
        self.kind, self.incomplete = kind, incomplete


def _deferral_of(e, dt_events=()):
    evs = [x for x in [e, *dt_events] if isinstance(x, ArchiveDeferred)]
    if not evs:
        return None
    nb = max(float(x.not_before or 0) for x in evs)        # requeue no earlier than ANY seen not_before
    hosts = getattr(e, "hosts", None) or [x.host for x in evs if getattr(x, "host", None)]
    kinds = sorted(set(getattr(e, "reasons", None) or [getattr(e, "reason", None) or getattr(e, "kind", None)
                                                         or "deferred"]))
    return Deferral(max(nb, time.time() + 1), ",".join(dict.fromkeys(h for h in hosts if h)) or None,
                    getattr(e, "status", None), str(e)[:200], kind=",".join(k for k in kinds if k))


def archive_call(fx, fn, *a, **k):
    """Run one archive call -> (result, Deferral|None). Never retries or sleeps.
    Contract of pipeline/archive (2026-10-18 rounds 1-3/5, README 'Completeness signals'):
      * fetch_best/fetch_newest RAISE ArchiveDeferred for throttles, timeouts, busy and an open Wayback breaker when
        nothing usable was found -> (None, Deferral at e.not_before): requeue, never a miss
      * they return None ONLY when every source answered with nothing usable -> (None, None) = genuine miss
      * a doc returned while another source failed has doc.incomplete=True / doc.deferral
        -> (doc, Deferral(incomplete=True)): the caller stages the doc AND keeps a requeue for a complete fetch
      * listings (CaptureList): .truncated on any early stop; retryable gap (.deferral set) -> (partial, Deferral);
        only permanent gaps (complete_except_permanent) -> (list, None): final
      * wb_captures raises ArchiveDeferred / typed ArchiveTransient (ArchiveTimeout, ArchiveBreakerOpen, ArchiveBusy)
      * any other ArchiveTransient escaping -> (None, Deferral now+TRANSIENT_DEFER_S)
    Other ArchiveError / exceptions propagate to the caller as before (a miss for that item)."""
    dt = _tracker(fx)
    m, tr0 = len(dt.events), _transient(fx)
    exc = None
    try:
        res = fn(*a, **k)
    except ArchiveDeferred as e:
        return None, _deferral_of(e, dt.events[m:])
    except ArchiveTransient as e:
        res, exc = None, e
    if exc is None and isinstance(res, list) and getattr(res, "truncated", False):
        dfr = getattr(res, "deferral", None)
        if dfr is not None:                        # retryable gap: use the partial list, but it is not complete
            return res, _deferral_of(dfr, dt.events[m:])
        log.info("listing has only permanent gaps (%s): final", getattr(res, "truncated_reason", None))
        return res, None
    if exc is None and res is not None and getattr(res, "incomplete", False) is True and not isinstance(res, list):
        d = _deferral_of(getattr(res, "deferral", None), dt.events[m:]) or \
            Deferral(time.time() + TRANSIENT_DEFER_S, None, None, "doc.incomplete (another source failed)",
                     kind="incomplete")
        d.incomplete = True
        d.reason = "incomplete doc staged; " + d.reason
        return res, d
    if res:
        return res, None
    if exc is not None:
        return None, Deferral(time.time() + TRANSIENT_DEFER_S, None, None,
                              f"archive unavailable: {str(exc)[:160]}", kind=getattr(exc, "kind", "transient"))
    evs = dt.events[m:]
    if evs and not getattr(fx, "raise_deferred", False):   # legacy fetcher (raise_deferred off): None hid a deferral
        return res, _deferral_of(evs[-1], evs)
    if not getattr(fx, "raise_deferred", False) and _transient(fx) > tr0:
        return res, Deferral(time.time() + TRANSIENT_DEFER_S, None, None, "archive unavailable (legacy counters)",
                             kind="transient")
    return res, None                                # genuine miss: every source answered with nothing usable


def _fmt_ts(t):
    return time.strftime("%H:%M:%S", time.localtime(t))


class Council:
    def __init__(self, row, ps: PoliteSession, st: State, codes: dict, archive_docs: int):
        self.r, self.ps, self.st, self.codes, self.archive_docs = row, ps, st, codes, archive_docs
        site = row["site"]
        if site.startswith("http://"):
            site = "https://" + site[7:]
        self.home = site.rstrip("/") + "/"
        self.key = site_key(urlparse(self.home).hostname)
        self.pages = 0
        self.mode = "live"
        self.policy = None
        self.basis = None
        self.stats = {"docs": 0, "ocr": 0, "skipped": 0, "errors": 0}
        self.w = {}
        self.full = False
        self.seen_text = set()
        self.robots_docs = []      # live doc URLs robots disallows -> archive copies
        self.deferred = {}         # key -> Deferral, this run (archive ArchiveDeferred / transient -> requeued)

    def defer(self, key, url, d: "Deferral", info=None):
        pid = self.r["place_id"]
        info = dict(info or {})
        if d.incomplete:
            info["incomplete"] = True              # staged already; revisit for a complete fetch
            self.stats["incomplete"] = self.stats.get("incomplete", 0) + 1
        tries = self.st.defer(pid, key, url, d.not_before, d.host, d.status, d.reason, info)
        if d.kind and "unknown_error" in d.kind and tries >= UNKNOWN_ERROR_MAX_TRIES:
            # archive README round 5: no retry cap in the module; lanes cap unknown_error gaps (done-with-gaps)
            self.st.resolve_deferral(pid, key, state="gave_up")
            log.info("%s archive gave up on %s after %d unknown_error deferrals", pid, url[:100], tries)
            return
        self.deferred[key] = d
        self.stats["deferred"] = len(self.deferred)
        log.info("%s archive deferred %s until %s (%s)", pid, url[:100], _fmt_ts(d.not_before), d.reason[:120])

    def needs_refetch(self, key):
        """Already staged, but from an incomplete fetch with a pending requeue: fetch again, don't skip."""
        return self.st.pending_incomplete(self.r["place_id"], key)

    def doc_ids(self, u):
        pre = "ukpspo" if PSPO.search(u) else "ukbyelaw"
        return f"{pre}:{doc_key(u)}", f"{pre}:{doc_key('html:' + u)}"

    def same(self, u):
        return site_key(urlparse(u).hostname or "") == self.key

    def links(self, base, html):
        for href, txt in A_RE.findall(html):
            href = unescape(href.strip())
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            u = urldefrag(urljoin(base, href))[0]
            if u.startswith("http://") and self.same(u):
                u = "https://" + u[7:]
            if u.startswith("https://"):
                yield u, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", txt)).strip()

    # ---------- discovery ----------
    def sitemap_hits(self, max_maps=15):
        hits, maps = [], []
        try:
            rt = self.ps.get(self.home + "robots.txt").text
            maps = [m.strip() for m in re.findall(r"(?im)^\s*sitemap:\s*(\S+)", rt)]
        except Exception:  # noqa: BLE001
            pass
        maps = [m.replace("http://", "https://", 1) for m in maps] or [self.home + "sitemap.xml"]
        seen = set()
        while maps and len(seen) < max_maps:
            m = maps.pop(0)
            if m in seen or not self.same(m):
                continue
            seen.add(m)
            try:
                r = self.ps.get(m)
                body = r.content
                if body[:2] == b"\x1f\x8b":
                    body = gzip.decompress(body)
                x = body.decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                continue
            locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", x)
            if "<sitemapindex" in x:
                locs.sort(key=lambda u: 0 if re.search(r"page|content|node|document|file|media", u, re.I) else 1)
                maps.extend(unescape(u) for u in locs)
            else:
                hits.extend(unescape(u) for u in locs if NAV.search(u))
        return hits[:200]

    def discover_live(self):
        seen, docs = set(), {}
        frontier = [(self.home, 0)] + [(urljoin(self.home, h.lstrip("/")), 1) for h in HINTS]
        try:
            r0 = self.ps.get(self.home)
        except Blocked as e:
            raise
        except Exception as e:  # noqa: BLE001
            raise Blocked(f"home failed: {str(e)[:120]}")
        self.pages += 1
        if site_key(urlparse(r0.url).hostname) != self.key:      # e.g. huntsdc.gov.uk -> huntingdonshire.gov.uk
            log.info("%s home redirects to %s", self.r["place_id"], r0.url)
            self.key = site_key(urlparse(r0.url).hostname)
            self.home = urljoin(r0.url, "/")
            frontier += [(urljoin(self.home, h.lstrip("/")), 1) for h in HINTS]
        seen.add(self.home)
        pending = {self.home: r0}
        for u in self.sitemap_hits():
            frontier.insert(1, (u, 1))
        topics = []
        cap = PHASE2_PAGES if self.r.get("phase") == 2 else MAX_PAGES
        while (frontier or topics) and self.pages < cap:
            url, d = frontier.pop(0) if frontier else topics.pop(0)
            if url in seen and url not in pending:
                continue
            seen.add(url)
            if url in pending:
                r = pending.pop(url)
            else:
                if not self.same(url):
                    continue
                try:
                    r = self.ps.get(url)
                    self.pages += 1
                except Exception:  # noqa: BLE001
                    continue
            ct = r.headers.get("content-type", "")
            if DOC_EXT.search(r.url) or "pdf" in ct or "officedocument" in ct:
                docs.setdefault(r.url, (url.rsplit("/", 1)[-1], d))
                continue
            if "html" not in ct:
                continue
            html = r.text[:3_000_000]
            here_nav = bool(NAV.search(url) or NAV.search(re.sub(r"<[^>]+>", " ", html[:6000])[:3000]))
            for u, t in self.links(r.url, html):
                if not self.same(u):
                    continue
                if DOC_EXT.search(u):
                    if (DOC.search(t) or DOC.search(u) or (here_nav and d >= 1 and NAV.search(urlparse(url).path)
                                                            and LAWISH.search(t + " " + u))) \
                            and not SKIP.search(t + " " + u):
                        docs.setdefault(u, (t, d))
                elif (NAV.search(t) or NAV.search(urlparse(u).path)) and d < MAX_DEPTH and u not in seen \
                        and not SKIP_NAV.search(t + " " + u):
                    frontier.append((u, d + 1))
                elif d < 2 and u not in seen and TOPIC.search(t + " " + urlparse(u).path) \
                        and not SKIP_NAV.search(t + " " + u) and len(topics) < 40 and (u, d + 1) not in topics:
                    topics.append((u, d + 1))
            if d >= 1 and NAV.search(url):
                txt = strip_html(html)
                if is_law_html(txt):
                    cu = HTML_DUP.sub("", r.url)
                    if not SKIP.search(r.url + " " + h1_title(html, url)) and \
                            not re.search(r"/(news|consultations?|have-your-say|press)/", r.url, re.I) and not any(k.rstrip("/") == "html:" + cu.rstrip("/") for k in docs):
                        docs.setdefault("html:" + r.url, (h1_title(html, url), d, txt))
        return docs

    def discover_archive(self, fx, max_pages=6):
        """Mini crawl over archived copies (shared limiter, lane ukie): archived homepage + hint paths
        (cheap exact/prefix CDX lookups, never a domain-wide regex scan), follow byelaw/PSPO nav links, collect
        document URLs. Returns ({url: [Capture,...] or None}, error)."""
        host = urlparse(self.home).hostname
        dom = host[4:] if host.startswith("www.") else host
        found, pages, err = {}, [], None
        self.discover_deferred = None          # Deferral if any discovery call was throttled/unavailable
        for h in ["byelaws", "bye-laws", "public-spaces-protection-orders"]:
            try:
                caps, d = archive_call(fx, fx.wb_captures, f"{host}/{h}", "prefix", collapse="urlkey", limit=50)
            except Exception as e:  # noqa: BLE001
                err = str(e)[:150]
                continue
            if d:
                self._note_discover_deferral(d)     # use the partial listing, but discovery stays incomplete
            for c in caps or []:
                u = c.original_url
                if DOC_EXT.search(u):
                    found.setdefault(re.sub(r"^http://", "https://", u), None)
                elif NAV.search(urlparse(u).path) and not SKIP.search(u):
                    pages.append(u)
        frontier = [self.home] + sorted(set(pages), key=len)[:4]
        seen = set()
        while frontier and len(seen) < max_pages:
            u = frontier.pop(0)
            k = re.sub(r"^https?://(www\.)?", "", u).rstrip("/")
            if k in seen:
                continue
            seen.add(k)
            try:
                doc, d = archive_call(fx, fx.fetch_newest, u)
            except Exception as e:  # noqa: BLE001
                err = str(e)[:150]
                continue
            if d:
                self._note_discover_deferral(d)     # incomplete doc: use it; either way discovery is not complete
                if not d.incomplete:
                    continue
            if doc is None or "html" not in (doc.content_type or "").lower():
                continue
            html = doc.text()
            nav_here = bool(NAV.search(u))
            if nav_here:
                t = strip_html(html)
                if is_law_html(t):
                    found.setdefault("html:" + re.sub(r"^http://", "https://", doc.original_url), (doc, t))
            for lu, lt in self.links(doc.original_url, html):
                if not self.same(lu) or SKIP.search(lt + " " + lu):
                    continue
                if DOC_EXT.search(lu):
                    if DOC.search(lt) or DOC.search(lu) or nav_here:
                        found.setdefault(lu, None)
                elif NAV.search(lt) or NAV.search(urlparse(lu).path):
                    frontier.append(lu)
        items = sorted(found.items(), key=lambda kv: (0 if kv[0].startswith("html:") else 1, kv[0]))
        return dict(items[: self.archive_docs]), (err if not found else None)

    def _note_discover_deferral(self, d):
        cur = self.discover_deferred
        if cur is None or d.not_before > cur.not_before:
            self.discover_deferred = d

    # ---------- emitting ----------
    def row(self, url, title, text, fmt, kind, prov=None):
        r = self.r
        pre = "ukpspo" if kind == "pspo" else "ukbyelaw"
        hkey = ("html:" + url) if fmt == "html" else url
        yr = re.search(r"\b(1[89]\d\d|20[0-3]\d)\b", title) or re.search(r"\b(1[89]\d\d|20[0-3]\d)\b", text[:2000])
        rec = {
            "place_id": r["place_id"], "country_code": r["country_code"], "doc_id": f"{pre}:{doc_key(hkey)}",
            "source_platform": f"council_site_{r['country_code'].lower()}", "source_url": url,
            "doc_type": "ordinance", "language": "ga" if (GA.search(title) or len(GA.findall(text[:5000])) >= 3) else "en", "title_native": title, "number": None,
            "adopted_date": None, "published_date": None, "effective_date": None, "in_force": None,
            "consolidated": False, "content_format": fmt, "text": text, "retrieved_at": utcnow(),
            "place_name": r["place_name"], "qid": r["qid"], "iso_3166_2": r.get("iso_3166_2") or None,
            "admin_level": r["admin_level"], "platform": "official_council_website", "platform_place_id": None,
            "source_official": True, "source_org": r["place_name"] + " council",
            "license_note": RIGHTS if r["country_code"] == "GB" else "official publication of the local authority "
                            "(IE: bye-laws under Local Government Act 2001 Part 19; PSI re-use)",
            "local_instrument_kind": kind_of(url, title, text), "id_kind": kind, "year_hint": yr.group(1) if yr else None, "lane": LANE,
            "place_codes": self.codes.get(r["place_id"]) or None,
        }
        if prov:
            rec.update(prov)
            rec["source_url"] = prov.get("original_url") or url
        return rec

    def writer(self, archived: bool):
        k = "archive" if archived else "live"
        if self.full:          # one .full batch file for the whole place (live + archive rows)
            k = "full"
        if k not in self.w:
            pre = "full.ukie-" if self.full else ("ukie-archive" if archived else "ukie-live")
            self.w[k] = StagedWriter(STAGE, self.r["country_code"], self.r["place_id"], batch_prefix=pre,
                                     chunk=100000 if self.full else 200)
        return self.w[k]

    def emit(self, url, title, body_or_text, kind, prov=None, is_html_text=False):
        pid = self.r["place_id"]
        if is_html_text:
            text, fmt, img = body_or_text, "html", False
        else:
            text, fmt, img = extract(body_or_text)
            if not text and not img and body_or_text[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
                t = strip_html(body_or_text.decode("utf-8", "replace"))
                if is_law_html(t):
                    text, fmt = t, "html"
        pre = "ukpspo" if kind == "pspo" else "ukbyelaw"
        hkey = ("html:" + url) if fmt == "html" else url
        did = f"{pre}:{doc_key(hkey)}"
        if self.r.get("phase") == 2:
            why = parish_reject(kind, title, url, text, img)
            if why:
                self.st.mark_doc(pid, did, url, "skipped:" + why, fmt, len(text or ""))
                self.stats["skipped"] += 1
                return
        if img:
            line = {"place_id": pid, "place_name": self.r["place_name"], "source_url": url, "title": title,
                    "doc_key": "doc:" + doc_key(url), "doc_id": did, "site": self.home,
                    "place_key": pid.replace(":", "_"), "country_code": self.r["country_code"],
                    "local_instrument_kind": kind, "lane": LANE, "listed_at": utcnow(),
                    "source_policy": (prov or {}).get("source_policy")}
            if prov:
                line.update({k: prov.get(k) for k in ("archive_source", "archive_timestamp", "archive_url",
                                                      "original_url")})
            append_jsonl(OCR_LIST, line)
            self.st.mark_doc(pid, did, url, "needs_ocr", "pdf_text", 0)
            self.stats["ocr"] += 1
            return
        if len(text) < 200:
            self.st.mark_doc(pid, did, url, "skipped:short_text", fmt, len(text))
            self.stats["skipped"] += 1
            return
        h = hashlib.sha1(re.sub(r"\s+", " ", text[:50000]).strip().lower().encode()).hexdigest()
        if h in self.seen_text:
            self.st.mark_doc(pid, did, url, "skipped:duplicate_content", fmt, len(text))
            self.stats["skipped"] += 1
            return
        self.seen_text.add(h)
        rec = self.row(url, title, text, fmt, kind, prov)
        err = self.writer(bool(prov)).add(rec)
        if err:
            log.warning("invalid %s: %s", url, err)
            self.st.mark_doc(pid, did, url, "skipped:invalid", fmt, len(text))
            self.stats["errors"] += 1
            return
        self.st.mark_doc(pid, did, url, "staged", fmt, len(text))
        self.stats["docs"] += 1

    def flush(self):
        files = []
        for w in self.w.values():
            w.flush()
            files += w.written
        return files

    def run(self, fx):
        pid = self.r["place_id"]
        try:
            docs = self.discover_live()
        except Blocked as e:
            ok, basis = self.ps.robots_status(self.home)
            self.mode, self.basis = "archive", (basis if not ok else str(e))
            self.policy = "archived_robots_disallowed" if not ok else None
            log.info("%s %s live blocked (%s) -> archive", pid, self.r["place_name"], self.basis)
            return self.run_archive(fx)
        log.info("%s %s live: pages=%d docs=%d", pid, self.r["place_name"], self.pages, len(docs))
        for u, v in docs.items():
            guard()
            t = clean_title(v[0], u)
            if u.startswith("html:"):
                url = u[5:]
                kind = "pspo" if PSPO.search(url + " " + t) else "byelaw"
                if self.st.doc_done(pid, f"{'ukpspo' if kind == 'pspo' else 'ukbyelaw'}:{doc_key(u)}"):
                    continue
                self.emit(url, t, v[2], kind, is_html_text=True)
                continue
            kind = "pspo" if PSPO.search(u + " " + t) else "byelaw"
            if self.st.doc_done(pid, f"{'ukpspo' if kind == 'pspo' else 'ukbyelaw'}:{doc_key(u)}") \
                    and not (fx is not None and self.needs_refetch(u)):
                continue
            try:
                r = self.ps.get(u, stream=True)
                body = b""
                for ch in r.iter_content(256 * 1024):
                    body += ch
                    if len(body) > MAX_PDF:
                        break
                r.close()
                if len(body) > MAX_PDF:
                    self.st.mark_doc(pid, "ukbyelaw:" + doc_key(u), u, "skipped:too_large")
                    continue
            except Blocked as e:
                if str(e).startswith("robots"):
                    self.robots_docs.append((u, t, kind, str(e)))
                else:
                    self.stats["errors"] += 1
                continue
            except Exception as e:  # noqa: BLE001
                log.info("doc fail %s: %s", u[:120], str(e)[:100])
                self.stats["errors"] += 1
                continue
            self.emit(u, t, body, kind)
        if self.robots_docs and fx is not None:
            log.info("%s: %d doc URLs disallowed by robots -> archive", self.r["place_id"], len(self.robots_docs))
            for u, t, kind, why in self.robots_docs[: self.archive_docs]:
                guard()
                self.robots_doc_archive(fx, u, t, kind, why)
        elif self.robots_docs:
            self.stats["robots_disallowed_docs"] = len(self.robots_docs)
        return self.flush()

    def robots_doc_archive(self, fx, u, t, kind, why):
        """Archive copy of one live doc URL robots disallows. Deferred (requeued) on throttle; no retry here."""
        pid = self.r["place_id"]
        did = f"{'ukpspo' if kind == 'pspo' else 'ukbyelaw'}:{doc_key(u)}"
        try:
            doc, d = archive_call(fx, fx.fetch_newest, u)
        except Exception as e:  # noqa: BLE001
            log.info("archive fetch %s: %s", u[:100], str(e)[:100])
            doc, d = None, None
        info = {"kind": "robots_doc", "title": t, "doc_kind": kind, "why": why}
        if d and not d.incomplete:                     # archive throttled/unavailable, not "not archived": requeue
            self.defer(u, u, d, info)
            return
        if doc is None:                                # genuine miss: every source answered, nothing usable
            self.st.resolve_deferral(pid, u)
            self.st.mark_doc(pid, did, u, "deferred:robots_no_archive")
            return
        restaged = self.needs_refetch(u)
        if not (restaged and d):                       # a still-incomplete refetch doesn't replace the staged copy
            self.emit(u, t, doc.body, kind, provenance_fields(doc, "archived_robots_disallowed", why))
        if d:                                          # doc.incomplete: staged, keep the requeue for a full fetch
            self.defer(u, u, d, info)
        else:
            self.st.resolve_deferral(pid, u)

    def run_deferred_docs(self, fx, rows):
        """Re-visit only the requeued robots-disallowed doc URLs of a live-mode place (no live re-crawl)."""
        pid = self.r["place_id"]
        for d in rows:
            guard()
            info = d.get("info") or {}
            u = d["url"]
            if not info.get("incomplete") and \
                    self.st.doc_done(pid, f"{'ukpspo' if info.get('doc_kind') == 'pspo' else 'ukbyelaw'}:{doc_key(u)}"):
                self.st.resolve_deferral(pid, d["key"])
                continue
            self.robots_doc_archive(fx, u, info.get("title") or clean_title("", u), info.get("doc_kind") or "byelaw",
                                    info.get("why") or "robots")
        return self.flush()

    def run_archive(self, fx):
        if fx is None:
            return []
        pid = self.r["place_id"]
        items, err = self.discover_archive(fx)
        if self.discover_deferred:                     # discovery incomplete: redo it in a later pass
            self.defer(DISCOVER_KEY, self.home, self.discover_deferred, {"kind": "discover"})
        else:
            self.st.resolve_deferral(pid, DISCOVER_KEY)
            if err:
                self.basis = (self.basis or "") + f"; archive deferred: {err}"
        log.info("%s archive candidates: %d", pid, len(items))
        for u, v in items.items():
            guard()
            refetch = self.needs_refetch(u)
            if not refetch and any(self.st.doc_done(pid, i) for i in self.doc_ids(u[5:] if u.startswith("html:") else u)):
                self.st.resolve_deferral(pid, u)       # already staged/skipped by an earlier pass
                continue
            if u.startswith("html:"):
                doc, t = v
                prov = provenance_fields(doc, self.policy, self.basis if self.policy else None)
                kind = "pspo" if PSPO.search(u) else "byelaw"
                title = clean_title(h1_title(doc.text(), u[5:]), u[5:])
                self.emit(u[5:], title, t, kind, prov, is_html_text=True)
                continue
            try:
                doc, d = archive_call(fx, fx.fetch_newest, u)
            except Exception as e:  # noqa: BLE001
                log.info("archive fetch %s: %s", u[:100], str(e)[:100])
                self.stats["errors"] += 1
                continue
            if d and not d.incomplete:                 # throttled: requeue this URL, move on to the next
                self.defer(u, u, d, {"kind": "archive_doc"})
                continue
            if doc is None:                            # genuine miss
                self.st.resolve_deferral(pid, u)
                self.stats["errors"] += 1
                continue
            if not (refetch and d):                    # a still-incomplete refetch doesn't replace the staged copy
                prov = provenance_fields(doc, self.policy, self.basis if self.policy else None)
                kind = "pspo" if PSPO.search(u) else "byelaw"
                self.emit(u, clean_title("", u), doc.body, kind, prov)
            if d:                                      # doc.incomplete: staged, keep the requeue for a full fetch
                self.defer(u, u, d, {"kind": "archive_doc"})
            else:
                self.st.resolve_deferral(pid, u)
        return self.flush()


def parish_reject(kind, title, url, text, img):
    if kind == "pspo":
        return "phase2_pspo_principal_power"
    head = (text or "")[:6000]
    # 2026-10-18: parish test batch staged financial regulations / fee scales; a phase-2 doc must say bye-law(s)
    BYE = re.compile(r"bye[\s_-]?laws?|byelaws?", re.I)
    if not BYE.search(title + " " + url + ("" if img else " " + head)):
        return "phase2_not_byelaw"
    if img:   # scanned: judge by title/url only
        return None if PARISH_MAKER.search(title + " " + url) or re.search(r"parish|town[-_ ]?council|\bpc\b", url, re.I) \
            else "phase2_scanned_maker_unknown"
    if PARISH_MAKER.search(head):
        return None
    if PRINCIPAL_MAKER.search(head):
        return "phase2_principal_council_doc"
    return "phase2_maker_unknown"


def _transient(fx):
    st = getattr(fx, "stats", {}) or {}
    return sum(st.get(k, 0) for k in ("cc_query_failed", "cc_breaker_open", "wayback_skipped_breaker", "wayback_failed"))


def _read_places(a):
    plist = [p for p in a.places.split(",") if p]
    if a.places_file:
        plist += [l.split()[0] for l in open(a.places_file) if l.strip() and not l.startswith("#")]
    return plist


PARISH_ARCHIVE_BASIS = re.compile(r"robots\.txt (?:\d{3}|ok|fetched|None|disallow\w*)\b.*=> disallow|"
                                  r"ssl|tls|certificate|CERTIFICATE_VERIFY", re.I)


def select_parish_archive(st, out):
    """Phase-2 places blocked live by robots.txt (disallow) or TLS errors (robots unreachable over TLS => disallow,
    or the homepage failing at TLS), plus phase-2 places already 'deferred' by an earlier archive pass."""
    rows = st.c.execute("SELECT place_id, status, note FROM places WHERE phase=2 AND status IN ('blocked','deferred') "
                        "ORDER BY place_id").fetchall()
    keep = []
    for pid, status, note in rows:
        try:
            basis = (json.loads(note or "{}") or {}).get("basis") or ""
        except ValueError:
            basis = note or ""
        if status == "deferred" or PARISH_ARCHIVE_BASIS.search(basis):
            keep.append(f"{pid}\t{status}\t{basis[:120]}")
    tmp = Path(out).with_suffix(".tmp")
    tmp.write_text("".join(k + "\n" for k in keep))
    tmp.replace(out)
    print(f"{len(keep)} of {len(rows)} blocked/deferred phase-2 places -> {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "status", "next-due", "select-parish-archive"])
    ap.add_argument("--places", default="")
    ap.add_argument("--archive-docs", type=int, default=12)
    ap.add_argument("--no-archive", action="store_true")
    ap.add_argument("--places-file", default="")
    ap.add_argument("--out", default=str(STATE_DIR / "parish_archive_places.txt"))
    ap.add_argument("--archive-queue", action="store_true", help="only places with status blocked/done_robots_docs/"
                    "deferred (deferred ones only once their earliest not_before has passed)")
    ap.add_argument("--refresh", action="store_true", help="re-crawl a done place and re-stage its docs in a normal "
                    "(non-.full) batch: same doc_ids, newest batch wins (fixes metadata, cannot drop docs)")
    ap.add_argument("--full", action="store_true", help="re-crawl even if done; stage ONE .full batch per place "
                    "(replaces every earlier doc of the place: only for places whose docs all come from this crawler)")
    a = ap.parse_args()
    st = State()
    if a.cmd == "status":
        print(json.dumps(st.summary(), indent=1))
        return
    if a.cmd == "select-parish-archive":
        select_parish_archive(st, a.out)
        return
    if a.cmd == "next-due":
        # seconds until the earliest 'deferred' place of the list is due (0 = due now), 'none' if none is deferred
        nbs = []
        for pid in _read_places(a):
            cur = st.place(pid)
            if cur and cur["status"] == "deferred":
                nbs.append(st.place_not_before(pid) or 0)
        print("none" if not nbs else max(0, int(min(nbs) - time.time()) + 1))
        return
    P = Places()
    codes = place_codes()
    ps = PoliteSession(log)
    fx = None
    if not a.no_archive:
        from archive import ArchiveFetcher
        fx = ArchiveFetcher(lane=LANE, cc_crawls=3)
        DeferTracker(fx)
    plist = _read_places(a)
    later = []          # places deferred (not yet due, or deferred during this run): re-visited at the end of the queue

    def process(pid, revisit=False):
        """-> False to stop the run (StopRun)."""
        row = P.get(pid)
        if row and (row.get("phase") == 2 or not row.get("site")):   # phase 2 / manual sites live in the state db
            dbp = st.place(pid) or {}
            row = dict(row, site=dbp.get("site") or "")
        if not row or not row["site"]:
            log.warning("no site for %s", pid)
            return True
        cur = st.place(pid)
        if cur and cur["status"] == "excluded":
            return True
        if a.archive_queue and cur and cur["status"] not in QUEUE_STATUSES:
            return True
        if cur and cur["status"] == "done" and not (a.full or a.refresh):
            log.info("skip done %s", pid)
            return True
        if fx is None and cur and cur["status"] in ("done_robots_docs", "deferred") and not (a.full or a.refresh):
            log.info("skip %s %s (live part done; archive-queue work)", cur["status"], pid)
            return True      # resume from checkpoint: don't re-crawl live; --archive-queue handles the rest
        rows = []
        if cur and cur["status"] == "deferred" and not (a.full or a.refresh):
            nb = st.place_not_before(pid)
            if nb and nb > time.time():
                if not revisit:
                    log.info("deferred %s until %s: end of queue", pid, _fmt_ts(nb))
                    later.append(pid)
                else:
                    log.info("deferred %s still cooling until %s: left for a later pass", pid, _fmt_ts(nb))
                return True
            rows = st.pending_deferrals(pid)
        c = Council(row, ps, st, codes, a.archive_docs)
        if a.full or a.refresh:
            c.full = a.full
            st.c.execute("DELETE FROM docs WHERE place_id=?", (pid,))
            st.c.commit()
        t_start = time.time()
        only_docs = bool(rows) and (cur or {}).get("mode") == "live" and \
            all((d.get("info") or {}).get("kind") == "robots_doc" for d in rows)
        try:
            if only_docs:            # live part done earlier: re-visit only the requeued robots-disallowed doc URLs
                prev_note = json.loads((cur or {}).get("note") or "{}")
                c.pages, c.basis, c.policy = prev_note.get("pages", 0), prev_note.get("basis"), prev_note.get("policy")
                files = c.run_deferred_docs(fx, rows)
            else:
                files = c.run(fx)
                st.supersede_deferrals(pid, t_start)      # full pass reconsidered everything; stale requeues
            status = "done" if c.mode == "live" or c.stats["docs"] or c.stats["ocr"] else "partial"
            if c.mode == "archive" and fx is None:
                status = "blocked"
            elif c.mode == "live" and c.robots_docs and fx is None:
                status = "done_robots_docs"          # live part done; robots-disallowed doc URLs wait for archive queue
            if c.mode == "archive" and c.basis and "archive deferred" in c.basis:
                status = "blocked" if not (c.stats["docs"] or c.stats["ocr"]) else "partial"
            if fx is not None and st.place_not_before(pid) is not None:
                status = "deferred"                  # archive items requeued (ArchiveDeferred): never done/blocked
                if pid not in later:
                    later.append(pid)
        except StopRun as e:
            log.error("STOP: %s", e)
            c.flush()
            return False
        except Exception as e:  # noqa: BLE001
            log.exception("council %s failed", pid)
            files, status = c.flush(), "error"
            c.basis = str(e)[:200]
        prev = st.place(pid) or {}
        nb = st.place_not_before(pid)
        st.upsert_place(place_id=pid, status=status, mode=c.mode, docs=(prev.get("docs") or 0) + c.stats["docs"],
                        ocr=(prev.get("ocr") or 0) + c.stats["ocr"], last_run=utcnow(),
                        note=json.dumps({"pages": c.pages, "basis": c.basis, "policy": c.policy, **c.stats,
                                         "not_before": nb if status == "deferred" else None,
                                         "files": [Path(f).name for f in files]}))
        log.info("place %s %s -> %s %s files=%d%s", pid, row["place_name"], status, c.stats, len(files),
                 f" (requeued, earliest {_fmt_ts(nb)})" if status == "deferred" and nb else "")
        return True

    stopped = False
    for pid in plist:
        guard()
        if not process(pid):
            stopped = True
            break
    if not stopped and later and fx is not None:
        # end of the queue: one re-visit of the deferred places that are due by now (no waiting here)
        todo, later[:] = list(dict.fromkeys(later)), []
        log.info("end of queue: re-visiting %d deferred place(s) that are due", len(todo))
        for pid in todo:
            guard()
            if not process(pid, revisit=True):
                break
    print(json.dumps(st.summary(), indent=1))


if __name__ == "__main__":
    main()
