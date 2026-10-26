#!/usr/bin/env python3
"""Targeted council-website harvester (own official sites only; robots.txt RFC 9309 + Crawl-delay; ~1 req / 1.5 s per host).

Profiles
  gb  UK principal councils (municipality/unitary/council_area/principal_area/county) + parish/town/community councils:
      byelaw pages and byelaw documents only (link text / URL contains "byelaw", "bye-law", "bye law").  source tag `ukbyelaw`
  ro  Romania primării: "Monitorul Oficial Local" (mandatory since OUG 57/2019 Codul administrativ art. 197-199 + HG 830/2022):
      hotărâri ale consiliului local (HCL) and dispoziții with regulatory keywords.  source tag `romol`
  sk  Slovakia obce/mestá: všeobecne záväzné nariadenia (VZN).  source tag `skvzn`        (2026-10-18)
  cz  Czechia obce: obecně závazné vyhlášky (OZV) / nařízení obce.  source tag `czozv`     (2026-10-18)
  at  Austria Gemeinden: Verordnungen des Gemeinderates (Gemeinderecht).  source tag `atgvo` (2026-10-18)
Per site: homepage (https; port 80 is closed on the box) -> links whose text/URL match the profile's NAV words (depth <= 2,
same site, <= MAX_PAGES pages) -> documents (PDF / DOCX / HTML) whose text/URL match DOC words. Text: pdftotext / docx XML.
No logins, no forms, no search endpoints, no third-party hosts except the site's own document CDN subdomain.
State: _state/council_<cc>/done.sqlite (doc url keys + "site:<place_id>" when a site pass completed).
Usage: python3 council_docs.py <gb|ro|sk|cz|at> run [--workers 8] [--limit-sites N] [--sites place_id,...] | test <place_id> | status
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
import hashlib
import io
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from html import unescape
from urllib.parse import unquote
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.live import STAGE, Done, PoliteSession, Stager, get_logger, utcnow  # noqa: E402
from common.xwalk import denied  # noqa: E402

CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
MAX_PAGES, MAX_DOCS_SITE, MAX_PDF = 60, 3000, 40 * 1024 * 1024
# 2026-10-18 (EU Wayback policy): live council crawls never contact the Wayback Machine / archive.org - not by link, sitemap,
# robots.txt or redirect. Archived copies of unusable sites come only from archive target `cee` (cee_archive.py) through the
# shared ArchiveFetcher (lane eu, common/eu_wayback.py). Audit 2026-10-18: no council_<cc> log ever showed an archive.org URL.
ARCHIVE_HOST = re.compile(r"(^|\.)archive\.org$", re.I)


class ArchiveHostRefused(PermissionError):
    pass


def _refuse_archive_redirect(r, *a, **k):
    loc = r.headers.get("Location") if r.is_redirect else None
    if loc and ARCHIVE_HOST.search(urlparse(urljoin(r.url, loc)).hostname or ""):
        r.close()
        raise ArchiveHostRefused(f"redirect to archive.org refused (live crawl; archive only via cee/ArchiveFetcher): {r.url[:120]}")


A_RE = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']?([^\"' >]+)[^>]*>(.*?)</a>", re.I | re.S)
PROFILES = {
    "gb": dict(cc="GB", source="ukbyelaw", lang="en", doc_type="ordinance",
               levels={"municipality", "unitary_authority", "council_area", "principal_area", "county", "parish",
                       "community", "district"},
               nav=re.compile(r"bye-?\s?laws?|byelaw", re.I),
               doc=re.compile(r"bye-?\s?laws?|byelaw", re.I),
               nav_hint=["/byelaws", "/bye-laws"],
               skip=re.compile(r"consultation response|privacy|cookie|\bmaps?\b|plan\b \(pdf", re.I)),
    "ro": dict(cc="RO", source="romol", lang="ro", doc_type="decision",
               levels={"municipality"},
               nav=re.compile(r"monitorul[\s\-_]*oficial[\s\-_]*local|hot[aă]r[aâ]ri|\bhcl\b|regulamente|"
                              r"hotararile|hot[aă]r[aâ]rile consiliului", re.I),
               doc=re.compile(r"\bhcl\b|hot[aă]r[aâ]re|hotarare|regulament|dispozi[tţț]i", re.I),
               nav_hint=["/monitorul-oficial-local", "/mol"],
               skip=re.compile(r"proiect de buget|anunt angajare|concurs|achizi", re.I)),
    # 2026-10-18 CEE: municipal general binding regulations from the municipality's own site (live, robots-checked)
    "sk": dict(cc="SK", source="skvzn", lang="sk", doc_type="ordinance", levels={"municipality"},
               nav=re.compile(r"v[šs]eobecn[eé][\s\-_]*z[áa]v[äa]zn|\bvzn\b|nariadeni[ae]|samospr[áa]v|legislat", re.I),
               accept=re.compile(r"v[šs]eobecn[eé][\s\-_]*z[áa]v[äa]zn|\bvzn\b|nariadeni", re.I),
               doc=re.compile(r"\bvzn\b|v[šs]eobecn[eé][\s\-_]*z[áa]v[äa]zn|nariadeni[ea]", re.I),
               num=re.compile(r"(?:VZN|nariadeni[ea])\s*(?:obce|mesta)?\s*(?:[čc]\.|[čc][íi]slo)?\s*(\d{1,3})\s*[/\-]\s*((?:19|20)\d\d)", re.I),
               text_req=re.compile(r"(?i)v[šs]eobecne\s+z[áa]v[äa]zn|\bVZN\b|nariadeni[ea]\s+(obce|mesta)"),
               nav_hint=["/vzn", "/vseobecne-zavazne-nariadenia"], skip_url=re.compile(r"navrh", re.I),
               skip=re.compile(r"n[áa]vrh|ozn[áa]meni[ea] o zverejnen|rozpo[čc]et|z[áa]pisnic|uznesen", re.I),
               rights="všeobecne záväzné nariadenie obce: právny predpis, excluded from copyright (zákon 185/2015 Z.z. § 5 písm. a)"),
    "cz": dict(cc="CZ", source="czozv", lang="cs", doc_type="ordinance", levels={"municipality"},
               nav=re.compile(r"obecn[ěe][\s\-_]*z[áa]vazn|vyhl[áa][šs]k|\bozv\b|pr[áa]vn[íi][\s\-_]*p[řr]edpis|na[řr][íi]zen[íi]", re.I),
               accept=re.compile(r"obecn[ěe][\s\-_]*z[áa]vazn|vyhl[áa][šs]k|\bozv\b|pr[áa]vn[íi][\s\-_]*p[řr]edpis", re.I),
               doc=re.compile(r"\bozv\b|obecn[ěe][\s\-_]*z[áa]vazn|vyhl[áa][šs]k|na[řr][íi]zen[íi][\s\-_]*(obce|m[ěe]sta)", re.I),
               num=re.compile(r"(?:vyhl[áa][šs]k[ay]|na[řr][íi]zen[íi])\s*(?:obce|m[ěe]sta)?[^\n]{0,40}?[čc]\.\s*(\d{1,3})\s*[/\-]\s*((?:19|20)\d\d)", re.I),
               text_req=re.compile(r"(?i)obecn[ěe]\s+z[áa]vazn[áa]\s+vyhl[áa][šs]k|na[řr][íi]zen[íi]\s+(obce|m[ěe]sta)|vyhl[áa][šs]ka\s+(obce|m[ěe]sta)"),
               nav_hint=["/obecne-vyhlasky", "/vyhlasky"], skip_url=re.compile(r"navrh", re.I),
               skip=re.compile(r"n[áa]vrh|z[áa]pis\b|usnesen|rozpo[čc]et|ve[řr]ejn[áa] zak[áa]zk", re.I),
               rights="obecně závazná vyhláška / nařízení obce: právní předpis, excluded from copyright (zákon 121/2000 Sb. § 3 písm. a)"),
    "at": dict(cc="AT", source="atgvo", lang="de", doc_type="ordinance", levels={"municipality"},
               nav=re.compile(r"verordnung|kundmachung|amtstafel|amtsblatt|gemeinderecht|satzung|tarifordnung", re.I),
               accept=re.compile(r"verordnung|gemeinderecht", re.I),
               doc=re.compile(r"verordnung|tarifordnung|geb[üu]hrenordnung|abgabenordnung|haus(halts)?ordnung|satzung", re.I),
               num=re.compile(r"(?:Zl\.|Zahl:?|GZ\.?)\s*([\w\-/.]{3,30}?)\s*[-/]\s*((?:19|20)\d\d)\b", re.I),
               text_req=re.compile(r"(?i)\bVerordnung\b|verordnet|Gemeinderat\w*\s+.{0,80}beschlossen"),
               nav_hint=["/verordnungen", "/Verordnungen"], skip_url=re.compile(r"entwurf", re.I),
               skip=re.compile(r"entwurf|protokoll|niederschrift|stellenausschreib|wahl|bauverhandlung|ediktal", re.I),
               rights="Verordnung des Gemeinderates: amtliches Werk, frei nach § 7 UrhG (AT)"),
}
DOC_EXT = re.compile(r"\.(pdf|docx)(\?|$)", re.I)


def fold(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in s if not unicodedata.combining(c)).lower()).strip()


def strip_html(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|nav|header|footer|noscript)\b.*?</\1>", " ", h)
    t = unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</tr>", "\n", h)))
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def site_key(host: str) -> str:
    p = host.lower().split(".")
    return ".".join(p[-3:]) if len(p) > 2 and p[-2] in ("co", "gov", "org", "ac", "ltd", "plc", "net") else ".".join(p[-2:])


class Site:
    def __init__(self, prof, row, log, done: Done, out: "queue.Queue"):
        self.p, self.r, self.log, self.done, self.out = prof, row, log, done, out
        u = re.split(r"[,\s]+", row["source_url"].strip())[0]   # some candidate rows hold "url1, url2"
        u = re.sub(r"^http://", "https://", u if "://" in u else "https://" + u)
        self.home = u
        self.key = site_key(urlparse(u).hostname or "")
        self.sess = PoliteSession(log, min_interval=1.5, retries=2)
        self.sess.s.hooks.setdefault("response", []).append(_refuse_archive_redirect)
        _rs = self.sess._rsess                         # robots.txt sessions too

        def _rsess():
            rs = _rs()
            rs.hooks.setdefault("response", []).append(_refuse_archive_redirect)
            return rs
        self.sess._rsess = _rsess
        self.pages = 0
        self.ndocs = 0

    def same(self, url):
        h = urlparse(url).hostname or ""
        return site_key(h) == self.key

    def get(self, url, **kw):
        if ARCHIVE_HOST.search(urlparse(url).hostname or ""):
            raise ArchiveHostRefused(f"archive.org URL not fetched live (archive only via cee/ArchiveFetcher): {url[:120]}")
        self.pages += 1
        return self.sess.get(url, timeout=None, **kw) if False else self.sess.get(url, **kw)

    def links(self, base, html):
        for href, txt in A_RE.findall(html):
            href = unescape(href.strip())
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            u = urldefrag(urljoin(base, href))[0]
            if u.startswith("http://"):
                u = "https://" + u[7:]
            if u.startswith("https://"):
                yield u, re.sub(r"\s+", " ", strip_html(txt))[:300]

    def run(self):
        P = self.p
        seen, frontier, docs = set(), [(self.home, 0)], {}
        for h in P["nav_hint"]:
            frontier.append((urljoin(self.home, h), 1))
        for u in self.sitemap_hits():
            frontier.insert(1, (u, 1))
        while frontier and self.pages < MAX_PAGES:
            url, d = frontier.pop(0)
            if url in seen:
                continue
            seen.add(url)
            try:
                r = self.get(url)
            except Exception as e:  # noqa: BLE001
                alt = self.alt_home(url, e) if d == 0 else None
                if alt:      # same site under www./bare host (TLS name mismatch / dead www. host), 2026-10-18
                    self.log.info("site %s home %s failed (%s); trying %s", self.r["place_id"], url, str(e)[:80], alt)
                    self.home, self.key = alt, site_key(urlparse(alt).hostname or "")
                    seen.discard(alt)
                    frontier.insert(0, (alt, 0))
                    continue
                if d == 0:
                    self.log.info("site %s home failed: %s", self.r["place_id"], str(e)[:150])
                    return "home_failed"
                continue
            ct = r.headers.get("content-type", "")
            if "html" not in ct:
                continue
            if "charset" not in ct.lower():      # 2026-10-18: requests falls back to ISO-8859-1 (CZ/SK cp1250/utf-8 pages)
                m = re.search(rb"""<meta[^>]+charset=["']?([\w-]+)""", r.content[:4000], re.I)
                r.encoding = m.group(1).decode() if m else (r.apparent_encoding or "utf-8")
            html = r.text[:3_000_000]
            if P.get("accept"):   # sk/cz/at: page URL, <title> or <h1> must name the act type (menus in the head don't count)
                th = " ".join(re.findall(r"(?is)<(?:title|h1)\b[^>]*>(.*?)</(?:title|h1)>", html[:400_000])[:3])
                here_nav = bool(P["accept"].search(urlparse(url).path) or P["accept"].search(strip_html(th)))
            else:
                here_nav = bool(P["nav"].search(url) or P["nav"].search(html[:2000]))
            for u, t in self.links(r.url, html):
                if not self.same(u):
                    continue
                navm = P["nav"].search(t) or P["nav"].search(urlparse(u).path)
                if DOC_EXT.search(u):
                    if (P["doc"].search(t) or P["doc"].search(u) or (here_nav and d >= 1)) and not P["skip"].search(t) and not (P.get("skip_url") and P["skip_url"].search(u)):
                        docs.setdefault(u, t)
                elif navm and d < 2 and u not in seen:
                    frontier.append((u, d + 1))
                elif here_nav and d >= 1 and d < 3 and re.search(r"[?&](page|pagina|p)=\d+|/page/\d+", u) and u not in seen:
                    frontier.append((u, d))          # pagination inside a byelaw / MOL listing
            if here_nav and d >= 1 and P["source"] == "ukbyelaw" and P["doc"].search(url):
                txt = strip_html(html)
                if len(txt) > 800 and re.search(r"\b(byelaws?|bye-laws?)\b.*\b(made|confirm|under section)", txt, re.I | re.S):
                    docs.setdefault("html:" + r.url, re.sub(r"\s+", " ", (re.findall(r"(?is)<title>(.*?)</title>", html) or [url])[0]).strip()[:300])
                    self._html_cache = getattr(self, "_html_cache", {})
                    self._html_cache["html:" + r.url] = txt
        if getattr(self, "list_only", False):        # --list-notext: discovery only, never download documents
            return docs
        for u, t in list(docs.items())[:MAX_DOCS_SITE]:
            key = "doc:" + hashlib.sha1(u.encode()).hexdigest()[:20]
            if self.done.has(key):
                continue
            try:
                text, fmt = self.fetch_doc(u)
            except Exception as e:  # noqa: BLE001
                self.log.info("doc fail %s: %s", u[:120], str(e)[:120])
                continue
            why = "ok" if len(text) >= 200 else "no_text"
            if why == "ok" and P.get("text_req") and not (P["doc"].search(t) or P["doc"].search(u)) \
                    and not P["text_req"].search(text[:3000]):
                why = "not_act"          # found on an act listing page, but neither link nor text names the act type
            self.out.put((self.row_for(u, t, text, fmt, key), key, why))
            self.ndocs += 1
        return f"pages={self.pages} docs={len(docs)}"

    def alt_home(self, url, err):
        if getattr(self, "_alt_tried", False) or self.p["cc"] not in ("SK", "CZ", "AT"):
            return None
        self._alt_tried = True
        pu = urlparse(url)
        h = pu.hostname or ""
        if not re.search(r"SSL|certificate|hostname|Name or service|NameResolution|robots", str(err), re.I):
            return None
        nh = h[4:] if h.startswith("www.") else "www." + h
        return f"https://{nh}{pu.path or '/'}"

    def sitemap_hits(self, max_maps=12):
        """URLs from the site's own sitemap(s) (robots.txt Sitemap: lines, else /sitemap.xml) matching NAV words."""
        P, hits = self.p, []
        maps = []
        try:
            rt = self.get(urljoin(self.home, "/robots.txt")).text
            maps = re.findall(r"(?im)^\s*sitemap\s*:\s*(\S+)", rt)
        except Exception:  # noqa: BLE001
            pass
        maps = [m.replace("http://", "https://", 1) for m in maps] or [urljoin(self.home, "/sitemap.xml")]
        seen = set()
        while maps and len(seen) < max_maps:
            m = maps.pop(0)
            if m in seen:
                continue
            seen.add(m)
            try:
                x = self.get(m).content[:30_000_000]
                if x[:2] == b"\x1f\x8b":
                    import gzip
                    x = gzip.decompress(x)
                locs = re.findall(rb"<loc>\s*([^<\s]+)\s*</loc>", x)
            except Exception:  # noqa: BLE001
                continue
            idx = b"<sitemapindex" in x[:3000]
            for l in locs:
                u = unescape(l.decode("utf-8", "replace")).replace("http://", "https://", 1)
                if idx:
                    maps.append(u)
                elif P["nav"].search(urlparse(u).path) and self.same(u):
                    hits.append(u)
            if idx:   # prefer sub-sitemaps whose name matches (pages / documents) first
                maps.sort(key=lambda u: 0 if re.search(r"page|content|node|document|bylaw|byelaw|hotar", u, re.I) else 1)
        return hits[:30]

    def fetch_doc(self, u):
        if u.startswith("html:"):
            return self._html_cache[u], "html"
        r = self.get(u, stream=True)
        with tempfile.NamedTemporaryFile(suffix=".bin", dir="/tmp") as tf:
            n = 0
            for ch in r.iter_content(256 * 1024):
                n += len(ch)
                if n > MAX_PDF:
                    break
                tf.write(ch)
            r.close()
            tf.flush()
            head = open(tf.name, "rb").read(4)
            if n > MAX_PDF:
                return "", "pdf_text"
            if head == b"%PDF":
                o = subprocess.run(["pdftotext", "-q", "-enc", "UTF-8", tf.name, "-"], capture_output=True, timeout=180)
                return o.stdout.decode("utf-8", "replace").strip(), "pdf_text"
            if head[:2] == b"PK":
                with zipfile.ZipFile(tf.name) as z:
                    x = z.read("word/document.xml").decode("utf-8", "replace")
                x = re.sub(r"</w:p>", "\n", x)
                return unescape(re.sub(r"<[^>]+>", "", x)).strip(), "docx_text"
            return "", "pdf_text"

    def row_for(self, u, title, text, fmt, key):
        P, r = self.p, self.r
        src_url = u[5:] if u.startswith("html:") else u
        if P.get("text_req") and (len(title) < 8 or re.match(r"(?i)\s*(stiahnu|stiahn|download|st[áa]hnout|zobrazit|"
                                                               r"herunterladen|pdf|docx?|otvori|soubor|s[úu]bor)\b", title)):
            first = next((ln.strip() for ln in text.splitlines() if len(ln.strip()) > 25), "")
            fn = re.sub(r"\.(pdf|docx?)$", "", unquote(src_url.rsplit("/", 1)[-1].split("?")[0]), flags=re.I)
            title = (first or fn)[:300]
        num = None
        m = (P.get("num") or re.compile(r"(?:HCL|hot[aă]r[aâ]rea?|nr\.?)\s*(?:nr\.?)?\s*(\d{1,4})\s*[/.\-]\s*((?:19|20)\d\d)", re.I)
             ).search(title + " " + text[:400])
        if m:
            num = f"{m.group(1)}/{m.group(2)}"
        yr = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", title) or re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", text[:1500])
        return {
            "place_id": r["place_id"], "country_code": P["cc"], "doc_id": f"{P['source']}:{key[4:]}",
            "source_platform": f"council_site_{P['cc'].lower()}", "source_url": src_url, "doc_type": P["doc_type"],
            "language": P["lang"], "title_native": title or src_url.rsplit("/", 1)[-1], "number": num,
            "adopted_date": None, "published_date": None, "effective_date": None, "in_force": None,
            "consolidated": False, "content_format": fmt, "text": text, "retrieved_at": utcnow(),
            "place_name": r["place_name"], "qid": r["qid"], "iso_3166_2": r.get("iso_3166_2") or None,
            "admin_level": r["admin_level"], "level": r["admin_level"], "platform": "official_council_website",
            "platform_place_id": None, "place_match": "candidate_source_url", "year_hint": yr.group(1) if yr else None,
            "source_official": True, "rights": P.get("rights") or "official publication of the council (UK: OGL/Crown or council copyright; "
                                              "RO: acte normative, Legea 8/1996 art. 9 exempt from copyright)",
        }


def load_sites(prof, only=None):
    out = []
    for r in csv.DictReader(CAND.open(encoding="utf-8")):
        if r["country_code"] != prof["cc"] or r["admin_level"] not in prof["levels"] or not r["source_url"].strip():
            continue
        if denied(r["place_id"]) or (only and r["place_id"] not in only):
            continue
        out.append(r)
    pri = {"county": 0, "unitary_authority": 0, "council_area": 0, "principal_area": 0, "municipality": 0, "district": 0}
    def pop(v):
        try:
            return float(v or 0)
        except ValueError:
            return 0.0
    out.sort(key=lambda r: (pri.get(r["admin_level"], 1), -pop(r["population"])))
    return out


def _place_key(pid):
    sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
    import schema
    return schema.place_key(pid)


def list_notext(P, a, log, st):
    """Re-crawl the RO sites (same discovery, robots, UA, rate limits; no document downloads) and write the URLs of
    docs whose key is why='no_text' in done.sqlite -> notext_urls.jsonl (append-only), sites -> notext_sites.txt.
    Sites whose previous pass found docs=0 (council_ro.log) are skipped. Never writes done.sqlite or staged files."""
    import json
    import sqlite3
    c = sqlite3.connect(f"file:{st / 'done.sqlite'}?mode=ro", uri=True)
    notext = {r[0] for r in c.execute("SELECT id FROM done WHERE why='no_text'")}
    c.close()
    outp, sitesp = st / "notext_urls.jsonl", st / "notext_sites.txt"
    found = set()
    if outp.exists():
        for ln in outp.open(encoding="utf-8"):
            try:
                found.add(json.loads(ln)["doc_key"])
            except Exception:  # noqa: BLE001  (torn last line after a kill)
                pass
    sdone = set(sitesp.read_text().split()) if sitesp.exists() else set()
    last = {}
    lp = STAGE / "_logs" / f"council_{a.profile}.log"
    if lp.exists():
        for ln in lp.open(encoding="utf-8", errors="replace"):
            m = re.search(r"\] site \d+/\d+ (\S+) .*? -> (.*)$", ln)
            if m:
                last[m.group(1)] = m.group(2)
    sites = [r for r in load_sites(P) if r["place_id"] not in sdone]
    skip0 = [r for r in sites if re.match(r"pages=\d+ docs=0\b", last.get(r["place_id"], "")) or
             last.get(r["place_id"], "").startswith("home_failed")]
    todo = [r for r in sites if r not in skip0]
    if a.limit_sites:
        todo = todo[:a.limit_sites]
    log.info("list-notext: %d no_text keys (%d already listed); sites %d, skipped (docs=0/home_failed before) %d, to do %d",
             len(notext), len(found), len(sites), len(skip0), len(todo))
    lock, work, n = threading.Lock(), queue.Queue(), [0, 0]
    for r in todo:
        work.put(r)
    of, sf = outp.open("a", encoding="utf-8"), sitesp.open("a", encoding="utf-8")

    def worker():
        while True:
            try:
                r = work.get_nowait()
            except queue.Empty:
                return
            s = Site(P, r, log, None, None)
            s.list_only = True
            try:
                docs = s.run()
            except Exception as e:  # noqa: BLE001
                docs = f"crash {str(e)[:100]}"
            k = 0
            with lock:
                if isinstance(docs, dict):
                    for u, t in docs.items():
                        key = "doc:" + hashlib.sha1(u.encode()).hexdigest()[:20]
                        if key in notext and key not in found:
                            found.add(key)
                            row = {"place_id": r["place_id"], "place_name": r["place_name"],
                                   "source_url": u[5:] if u.startswith("html:") else u, "title": t, "doc_key": key,
                                   "site": s.home}
                            if P["cc"] != "RO":   # staging place_key (schema.place_key, e.g. wd:Q774015 -> wd_Q774015)
                                row["place_key"] = _place_key(r["place_id"])
                            of.write(json.dumps(row, ensure_ascii=False) + "\n")
                            k += 1
                    of.flush()
                sf.write(r["place_id"] + "\n")
                sf.flush()
                n[0] += 1
                n[1] += k
                log.info("notext site %d/%d %s %s -> %s, +%d listed (total %d of %d)", n[0], len(todo), r["place_id"],
                         r["place_name"], f"docs={len(docs)}" if isinstance(docs, dict) else docs, k, len(found), len(notext))
    ts = [threading.Thread(target=worker, daemon=True) for _ in range(a.workers)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    log.info("list-notext finished: listed %d of %d no_text keys; unmatched %d", len(found), len(notext), len(notext - found))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profile", choices=list(PROFILES))
    ap.add_argument("cmd", choices=["run", "test", "status"])
    ap.add_argument("place", nargs="?")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit-sites", type=int)
    ap.add_argument("--sites")
    ap.add_argument("--list-notext", action="store_true", help="ro: list no_text doc URLs (no downloads); see list_notext()")
    a = ap.parse_args()
    P = PROFILES[a.profile]
    log = get_logger(f"council_{a.profile}")
    st = STAGE / "_state" / f"council_{a.profile}"
    if a.list_notext:
        return list_notext(P, a, log, st)
    done = Done(st / "done.sqlite")
    if a.cmd == "status":
        print("sites done", done.c.execute("select count(*) from done where id like 'site:%'").fetchone()[0],
              "docs", done.count("ok"), "no_text", done.count("no_text"))
        return
    only = set((a.sites or a.place or "").split(",")) - {""}
    sites = load_sites(P, only or None)
    if a.cmd == "test":
        q = queue.Queue()
        s = Site(P, sites[0], log, done, q)
        print(s.home, s.run())
        while not q.empty():
            row, key, why = q.get()
            print(why, row["content_format"], len(row["text"]), row["number"], row["title_native"][:90], "|", row["source_url"][:110])
        return
    todo = [r for r in sites if not done.has("site:" + r["place_id"])]
    if a.limit_sites:
        todo = todo[:a.limit_sites]
    log.info("%s: %d sites total, %d to do, workers=%d", a.profile, len(sites), len(todo), a.workers)
    stg = Stager(P["cc"], P["source"], log, max_docs=150, max_secs=900).graceful(done)
    q, work = queue.Queue(maxsize=200), queue.Queue()
    for r in todo:
        work.put(r)
    nsites = [0]

    def worker():
        while True:
            try:
                r = work.get_nowait()
            except queue.Empty:
                return
            try:
                res = Site(P, r, log, done, q).run()
            except Exception as e:  # noqa: BLE001
                res = f"crash {str(e)[:120]}"
            q.put((None, "site:" + r["place_id"], "site_" + res.split(" ")[0].split("=")[0]))
            nsites[0] += 1
            log.info("site %d/%d %s %s -> %s", nsites[0], len(todo), r["place_id"], r["place_name"], res)
    ts = [threading.Thread(target=worker, daemon=True) for _ in range(a.workers)]
    for t in ts:
        t.start()
    while any(t.is_alive() for t in ts) or not q.empty():
        try:
            row, key, why = q.get(timeout=5)
            if row is not None and why != "ok":
                row = None
            stg.add(row, key, why)
        except queue.Empty:
            pass
        if stg.due():
            log.info("flush %s | done %d", dict(stg.flush(done)), done.count())
    if stg.keys:
        log.info("flush %s | done %d", dict(stg.flush(done)), done.count())
    log.info("finished %s", dict(stg.total))


if __name__ == "__main__":
    main()
