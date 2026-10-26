#!/usr/bin/env python3
"""Italy municipal TRANCHE 1 harvester (regolamenti comunali + statuto).

Derived from the pilot harvester (it_pilot/scripts/harvest_it.py) with
three tranche-1 changes, everything else byte-identical in behaviour:
(a) DOC_KW also matches the German titles used by Südtirol (BZ) comuni
    (Verordnung/Satzung) — the pilot's Italian-only pattern could not
    see German-titled PDF links on the Civis tenants;
(b) OpenPA/OpenCity deepening: sitemap discovery, /content/search
    pagination following, any-PDF acceptance on /openpa/object/ pages,
    larger page/doc caps — the pilot took only each tenant's
    homepage-featured regolamento;
(c) summary defaults to out/tranche1_summary.json.

Per comune: robots check -> listing discovery -> download
regolamenti/statuto PDFs -> extract (PyMuPDF -> pdfplumber ->
pdftotext -> tesseract-ita OCR via the persistent tessroot wrapper;
every digital method must pass the pilot's extraction-usability gate)
-> split on Art. headings -> world_municipal 19-column rows ->
fail-closed validation -> parquet + validation sidecar per comune.
Everything cached on disk so reruns resume; summary merged
incrementally.

Usage: harvest_t1.py CODE [CODE ...]
Artifacts: out/{code}_html.parquet, out/{code}_validation.json,
out/tranche1_summary.json, raw/listings/<code>/, raw/pdf/<code>/.
"""
import html as html_mod
import json
import os
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from net import fetch, make_session  # noqa: E402

sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py"))
from ipfs_datasets_py.processors.legal_scrapers.world_municipal import (  # noqa: E402
    jurisdiction,
    normalize,
    parquet_io,
    schema as wm_schema,
)
import pyarrow as pa  # noqa: E402

RAW = HERE.parent / "raw"
OUT = HERE.parent / "out"
RETRIEVED = date.today().isoformat()
PACING_S = 2.0
MAX_DOCS = 60
EXTRA_COLS = [("platform", pa.string())]
TESSERACT = str(Path.home() / "workspace/tools/bin/tesseract")
KW = re.compile(r"regolament|statut|verordnung|satzung", re.I)
DOC_KW = re.compile(r"regolament|statut|verordnung|satzung", re.I)

# Codes and names are ISTAT-registry-exact (verified against
# jurisdictions.jsonl 2026-10-14 — an earlier draft carried wrong
# codes for Colorno/Riva/Arco/Rovereto, caught by the registry
# cross-check below before anything mislabeled could validate).
COMUNI = {
    "034014": dict(name="Fidenza", region="Emilia-Romagna", platform="wordpress",
                   base="https://www.comune.fidenza.pr.it",
                   seeds=["/statuto-e-regolamenti/"]),
    "034010": dict(name="Colorno", region="Emilia-Romagna", platform="plone_myportal",
                   base="https://www.comune.colorno.pr.it",
                   seeds=["/statuto-e-regolamenti", "/regolamenti"]),
    "022153": dict(name="Riva del Garda", region="Trentino-Alto Adige/Südtirol",
                   platform="openpa_opencity",
                   base="https://www.comune.rivadelgarda.tn.it",
                   seeds=["/content/search?SearchText=regolamenti"]),
    "022006": dict(name="Arco", region="Trentino-Alto Adige/Südtirol",
                   platform="openpa_opencity",
                   base="https://www.comune.arco.tn.it",
                   seeds=["/content/search?SearchText=regolamenti"]),
    "021051": dict(name="Merano", region="Trentino-Alto Adige/Südtirol",
                   platform="civis",
                   base="https://www.comune.merano.bz.it", seeds=[]),
    "021013": dict(name="Brunico", region="Trentino-Alto Adige/Südtirol",
                   platform="civis",
                   base="https://www.comune.brunico.bz.it", seeds=[]),
    "022161": dict(name="Rovereto", region="Trentino-Alto Adige/Südtirol",
                   platform="opencity_like",
                   base="https://www.comune.rovereto.tn.it",
                   seeds=["/Amministrazione/Documenti-e-dati"]),
    "022205": dict(name="Trento", region="Trentino-Alto Adige/Südtirol",
                   platform="custom", tree=True,
                   base="https://www.comune.trento.it", seeds=[]),
    "021008": dict(name="Bolzano", region="Trentino-Alto Adige/Südtirol",
                   platform="custom", tree=True,
                   base="https://www.comune.bolzano.bz.it", seeds=[]),
    "021004": dict(name="Appiano sulla strada del vino",
                   region="Trentino-Alto Adige/Südtirol", platform="civis",
                   base="https://www.comune.appiano.bz.it", seeds=[]),
    "021040": dict(name="Laives", region="Trentino-Alto Adige/Südtirol",
                   platform="civis",
                   base="https://www.comune.laives.bz.it", seeds=[]),
    "021041": dict(name="Lana", region="Trentino-Alto Adige/Südtirol",
                   platform="civis",
                   base="https://www.comune.lana.bz.it", seeds=[]),
    "022139": dict(name="Pergine Valsugana", region="Trentino-Alto Adige/Südtirol",
                   platform="openpa_opencity",
                   base="https://www.comune.pergine.tn.it",
                   seeds=["/content/search?SearchText=regolamenti"]),
    "022001": dict(name="Ala", region="Trentino-Alto Adige/Südtirol",
                   platform="openpa_opencity",
                   base="https://www.comune.ala.tn.it",
                   seeds=["/content/search?SearchText=regolamenti"]),
    "022104": dict(name="Levico Terme", region="Trentino-Alto Adige/Südtirol",
                   platform="openpa_opencity",
                   base="https://www.comune.levico-terme.tn.it",
                   seeds=["/content/search?SearchText=regolamenti"]),
}

S = make_session()

_REGISTRY = None


def registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = {
            r["code"]: r
            for r in map(json.loads, (OUT / "jurisdictions.jsonl")
                         .read_text(encoding="utf-8").splitlines())
        }
    return _REGISTRY


def robots_check(base):
    """Return (excerpt, disallow_prefixes, sitemaps, crawl_delay).
    Best-effort: unreachable robots is recorded, harvest proceeds only
    for paths not known-disallowed. Only the User-agent: * group is
    parsed (the files also carry per-bot blocklists we are not in)."""
    try:
        status, _, body = fetch(S, base + "/robots.txt", timeout=(15, 30),
                                tries=3, max_bytes=200_000)
        if status != 200:
            return f"robots.txt HTTP {status}", [], [], 0.0
        txt = body.decode("utf-8", errors="replace")
        dis, sitemaps, delay = [], [], 0.0
        in_star = True  # rules before any User-agent line are global
                        # (GEM2GO robots files have no User-agent line)
        for ln in txt.splitlines():
            low = ln.strip().lower()
            if low.startswith("user-agent:"):
                in_star = low.split(":", 1)[1].strip() == "*"
                continue
            if low.startswith("sitemap:"):
                sitemaps.append(ln.split(":", 1)[1].strip())
            if not in_star:
                continue
            if low.startswith("disallow:") and len(ln.strip()) > 10:
                dis.append(ln.split(":", 1)[1].strip())
            elif low.startswith("crawl-delay:"):
                try:
                    delay = float(ln.split(":", 1)[1].strip())
                except ValueError:
                    pass
        return txt[:600], [d for d in dis if d and d != "/"], sitemaps, delay
    except Exception as e:
        return f"robots unreachable: {type(e).__name__}", [], [], 0.0


def is_disallowed(url, dis_prefixes):
    path = urlparse(url).path
    return any(path.startswith(d) for d in dis_prefixes)


PACING_CUR = PACING_S  # raised per comune when robots asks Crawl-delay


def fetch_post(url, data, tries=4, deadline=600):
    """POST with the same retry posture as net.fetch (which is GET-only).
    Needed for the GEM2GO datei.aspx module's search/pager forms.
    Returns (status, final_url, bytes); raises the last error."""
    import requests as _rq

    last = None
    t0 = time.time()
    for attempt in range(tries):
        try:
            with S.post(url, data=data, timeout=(20, 90), stream=True) as r:
                chunks, total = [], 0
                for chunk in r.iter_content(65536):
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= 4_000_000:
                        break
                time.sleep(PACING_CUR)
                return r.status_code, r.url, b"".join(chunks)
        except (_rq.ConnectionError, _rq.Timeout,
                _rq.exceptions.ChunkedEncodingError) as e:
            last = e
            if attempt + 1 < tries and time.time() - t0 < deadline:
                time.sleep(5.0 * (attempt + 1))
            if time.time() - t0 >= deadline:
                break
    raise last  # type: ignore[misc]


def get_page(url, cache_dir, tag):
    """Fetch an HTML page with on-disk cache. Returns (status, final_url, soup)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", tag)[:80]
    cpath = cache_dir / f"{safe}.html"
    if cpath.exists() and cpath.stat().st_size > 0:
        body = cpath.read_bytes()
        status, final = 200, url
    else:
        status, final, body = fetch(S, url, timeout=(20, 90), tries=4,
                                    deadline=600)
        if status == 200:
            cpath.write_bytes(body)
        time.sleep(PACING_CUR)
    if status != 200:
        return status, final, None
    return status, final, BeautifulSoup(body.decode("utf-8", errors="replace"),
                                        "html.parser")


TREE_PREFIXES = ("/Amministrazione-Trasparente/Disposizioni-generali",
                 "/Amministrazione/Documenti-e-dati")
TREE_PLATFORMS = ("openpa_opencity", "opencity_like")


def is_doc_link(href):
    low = href.lower().split("?")[0]
    return (low.endswith(".pdf") or "/content/download/" in low
            or "getdocument" in low
            or ("/download" in low and "pdf" in low))


def discover_docs(code, cfg, dis_prefixes, sitemap_urls=()):
    """Return ordered unique [{url, title}] of regolamenti/statuto PDFs."""
    base = cfg["base"]
    cache = RAW / "listings" / code
    listing_urls = [urljoin(base, s) for s in cfg["seeds"]]
    if cfg["platform"] == "openpa_opencity":
        listing_urls.append(urljoin(base, "/content/search?SearchText=statuto"))
    docs, seen_docs = [], set()
    visited = set()
    page_cap = 48 if cfg["platform"] == "openpa_opencity" else 20

    def add_doc(href, txt, listing):
        if href not in seen_docs and not is_disallowed(href, dis_prefixes):
            seen_docs.add(href)
            docs.append({"url": href,
                         "title": txt or unquote(Path(urlparse(href).path).name),
                         "listing": listing})

    def scan_page(url, tag, depth, phase_cap=None):
        # phase_cap lets a later discovery phase (the sitemap scan)
        # spend its own page budget: the shared visited counter would
        # otherwise be exhausted by the tree crawl before the sitemap
        # phase starts, silently starving it (Trento: 0 docs while an
        # isolated sitemap scan found 61).
        limit = page_cap if phase_cap is None else phase_cap
        if url in visited or len(visited) > limit:
            return
        visited.add(url)
        if is_disallowed(url, dis_prefixes):
            print(f"  robots-disallowed, skip: {url}", flush=True)
            return
        try:
            status, final, soup = get_page(url, cache, tag)
        except Exception as e:
            print(f"  listing FAIL {url}: {type(e).__name__} {e}"[:160], flush=True)
            return
        if soup is None:
            print(f"  listing HTTP {status}: {url}", flush=True)
            return
        fo = urlparse(final)
        origin = f"{fo.scheme}://{fo.netloc}"
        on_object_page = "/openpa/object/" in fo.path
        on_doc_page = (("/Dokumente/" in fo.path or "/Documenti/" in fo.path)
                       and DOC_KW.search(final))
        follow = []
        for a in soup.find_all("a", href=True):
            href = urljoin(final, a["href"]).split("#")[0]
            if not href:
                continue
            txt = a.get_text(" ", strip=True)
            low = href.lower().split("?")[0]
            if is_doc_link(href) and (DOC_KW.search(href) or DOC_KW.search(txt)
                                      or DOC_KW.search(url) or on_object_page
                                      or on_doc_page):
                add_doc(href, txt, final)
            elif (depth < 3 and (href.startswith(base) or href.startswith(origin))
                    and ("(offset)" in href and "content/search" in href
                         or KW.search(txt)
                         or "/dokumente" in low or "/documenti" in low)
                    and not low.endswith((".pdf", ".zip", ".doc", ".docx",
                                          ".xls", ".xlsx", ".jpg", ".png"))):
                follow.append((href, txt))
        for href, txt in follow[:24]:
            scan_page(href, f"sub_{txt[:30]}", depth + 1)

    def scan_tree():
        """eZ/OpenCity tenants: /content/search and /opendata are
        robots-disallowed, but the Amministrazione Trasparente
        'Disposizioni generali' tree and the Documenti-e-dati area are
        server-rendered. BFS those subtrees (own-host links only),
        accepting doc links whose anchor text, page path or URL path
        carries a document keyword. Documenti-e-dati is queued first
        and keyword-path children jump the queue — a plain BFS drowns
        in the transparency tree's index pages before reaching the
        document leaves."""
        roots = [urljoin(base, p) for p in reversed(TREE_PREFIXES)]
        queue = [(r, 0) for r in roots]
        seen_pages = set()
        n = 0
        while queue and n < 260:
            url, depth = queue.pop(0)
            # Only the tree's own seen set gates processing: pages the
            # generic homepage scan already visited must STILL be
            # processed here, or their tree children are never queued
            # (that bug capped Trento's crawl at 10 pages for hours).
            if url in seen_pages:
                continue
            seen_pages.add(url)
            if is_disallowed(url, dis_prefixes):
                continue
            try:
                # Cache tag MUST be URL-derived: positional tags
                # (tree<len>) silently rebind to the wrong page when
                # the crawl order shifts (fragment-era caches did
                # exactly that to Trento).
                tag = "tree_" + re.sub(r"[^A-Za-z0-9]+", "_",
                                       urlparse(url).path)[-70:]
                status, final, soup = get_page(url, cache, tag)
            except Exception as e:
                print(f"  tree FAIL {url}: {type(e).__name__}"[:140], flush=True)
                continue
            if soup is None:
                continue
            n += 1
            visited.add(url)
            fo = urlparse(final)
            origin = f"{fo.scheme}://{fo.netloc}"
            children = []
            for a in soup.find_all("a", href=True):
                href = urljoin(final, a["href"]).split("#")[0]
                if not href:
                    continue
                txt = a.get_text(" ", strip=True)
                hp = urlparse(href)
                if is_doc_link(href) and (DOC_KW.search(href)
                                          or DOC_KW.search(txt)
                                          or DOC_KW.search(final)):
                    add_doc(href, txt, final)
                elif (depth < 6 and (href.startswith(base)
                                     or href.startswith(origin))
                        and any(hp.path.startswith(p) for p in TREE_PREFIXES)
                        and not hp.path.lower().endswith(
                            (".pdf", ".zip", ".doc", ".docx", ".xls",
                             ".xlsx", ".jpg", ".png"))):
                    children.append((href, depth + 1))
            queue = [c for c in children if DOC_KW.search(c[0])] \
                + [c for c in children if not DOC_KW.search(c[0])] + queue
        print(f"  tree crawl: {n} pages, {len(docs)} docs so far", flush=True)

    def scan_sitemap():
        """Follow the robots-declared sitemaps (plus the conventional
        /sitemap.xml); harvest every sitemap URL whose path carries a
        document keyword as a listing page. GEM2GO tenants declare
        sub-sitemaps on their alternate-language official domains —
        those are the comune's own sitemap files and are followed."""
        urls = list(sitemap_urls) or [urljoin(base, "/sitemap.xml")]
        locs = []
        for su in urls[:2]:
            if is_disallowed(su, dis_prefixes):
                print(f"  sitemap robots-disallowed, skip: {su}", flush=True)
                continue
            try:
                status, _, body = fetch(S, su, timeout=(20, 60), tries=2,
                                        deadline=240, max_bytes=3_000_000)
                if status == 200:
                    locs += re.findall(r"<loc>\s*([^<]+?)\s*</loc>",
                                       body.decode("utf-8", errors="replace"))
            except Exception as e:
                print(f"  sitemap FAIL {su}: {type(e).__name__}", flush=True)
        subs = [u for u in dict.fromkeys(locs) if u.endswith(".xml")][:4]
        for su in subs:
            if is_disallowed(su, dis_prefixes):
                continue
            try:
                status, _, body = fetch(S, su, timeout=(20, 60), tries=2,
                                        deadline=240, max_bytes=6_000_000)
                if status == 200:
                    locs += re.findall(
                        r"<loc>\s*([^<]+?)\s*</loc>",
                        body.decode("utf-8", errors="replace"))
            except Exception:
                pass
        hits = [u for u in dict.fromkeys(locs)
                if KW.search(urlparse(u).path)
                or re.search(r"dokument|documenti", urlparse(u).path, re.I)]
        print(f"  sitemap: {len(locs)} URLs, {len(hits)} keyword hits",
              flush=True)
        # Document-node pages inside the transparency/document trees
        # come first (they carry the download links); generic keyword
        # pages (news, notices) are mostly noise.
        tree_hits = [u for u in hits
                     if any(urlparse(u).path.startswith(p)
                            for p in TREE_PREFIXES)]
        rest = [u for u in hits if u not in tree_hits]
        phase_cap = len(visited) + 130  # this phase's own page budget
        for u in tree_hits[:90] + rest[:20]:
            # URL-derived cache tag (positional tags rebind silently
            # when scan order shifts between runs — same Trento lesson
            # as the tree crawl).
            tag = "sm_" + re.sub(r"[^A-Za-z0-9]+", "_",
                                 urlparse(u).path)[-70:]
            scan_page(u, tag, 1, phase_cap=phase_cap)

    def scan_doc_page(url, tag):
        """A document-detail page (GEM2GO): accept any download link
        on it — the page itself is the document's context."""
        if url in visited:
            return
        visited.add(url)
        if is_disallowed(url, dis_prefixes):
            return
        try:
            status, final, soup = get_page(url, cache, tag)
        except Exception:
            return
        if soup is None:
            return
        for a in soup.find_all("a", href=True):
            href = urljoin(final, a["href"])
            if is_doc_link(href):
                add_doc(href, a.get_text(" ", strip=True), final)

    def discover_gem2go():
        """GEM2GO tenants (the BZ 'Civis' family): the Dokumente /
        Documenti index is an ASP.NET datei.aspx module whose full
        list is reachable only through the module's own pager POSTs
        (the pager anchors are javascript:void(0)). Parse the form
        generically (hidden __VIEWSTATE + search-<id> / pager-<id>),
        page the whole list, keep document pages whose slug carries a
        document keyword, then read each page's download link."""
        doc_pages, seen_dp = [], set()
        seen_all = set()

        def collect(soup, origin):
            """Track every document-page link (for paging termination)
            but harvest only keyword-slug ones. Returns new-link count."""
            new = 0
            for a in soup.find_all("a", href=True):
                href = urljoin(origin, a["href"])
                p = urlparse(href).path
                if "/Dokumente/" in p or "/Documenti/" in p:
                    if href not in seen_all:
                        seen_all.add(href)
                        new += 1
                    if DOC_KW.search(p) and href not in seen_dp:
                        seen_dp.add(href)
                        doc_pages.append(href)
            return new

        # NB: the index pages are usually already in `visited` (reached
        # via homepage follows) — that must NOT skip them here: the
        # point is parsing their pager form, and get_page serves the
        # cached copy.
        for ii, iu in enumerate((urljoin(base, "/de/Verwaltung/Dokumente"),
                                 urljoin(base, "/it/Amministrazione/"
                                            "Documenti_e_dati"))):
            try:
                status, final, soup0 = get_page(iu, cache, f"gem2go_idx{ii}")
            except Exception:
                continue
            if soup0 is None:
                continue
            collect(soup0, final)
            form = soup0.find("form",
                              action=lambda x: x and "datei.aspx" in x)
            if form is None:
                continue
            action = urljoin(final, form["action"])
            fields, search_n, pager_n, btn_n = {}, None, None, None
            for el in form.find_all(["input", "button"]):
                nm = el.get("name") or ""
                if el.get("type") == "hidden" or nm.startswith("__"):
                    fields[nm] = el.get("value") or ""
                if nm.startswith("search-"):
                    search_n = nm
                elif nm.startswith("pager-"):
                    pager_n = nm
                elif nm.startswith("searchButton"):
                    btn_n = nm
            if not (search_n and pager_n):
                continue

            def post_page(term, page):
                data = dict(fields)
                data[search_n] = term
                data[pager_n] = str(page)
                if btn_n:
                    data[btn_n] = ""
                st, furl, body = fetch_post(action, data)
                if st != 200:
                    return 0
                return collect(BeautifulSoup(
                    body.decode("utf-8", errors="replace"), "html.parser"),
                    furl)

            # Term searches first (the module's own search filters the
            # list server-side), then unfiltered paging as backstop.
            # Paging terminates when a page adds no new document links
            # at all — NOT when it adds no keyword doc (those cluster
            # deep in the alphabetical list: V for Verordnung).
            for term in ("Verordnung", "Satzung", "Regolamento", "Statuto"):
                try:
                    post_page(term, 0)
                except Exception as e:
                    print(f"  gem2go search FAIL {term}: {type(e).__name__}",
                          flush=True)
            print(f"  gem2go after search: {len(doc_pages)} doc pages",
                  flush=True)
            for page in range(20):
                try:
                    new = post_page("", page)
                except Exception as e:
                    print(f"  gem2go POST FAIL p{page}: {type(e).__name__}",
                          flush=True)
                    break
                print(f"  gem2go datei p{page}: {len(doc_pages)} doc pages",
                      flush=True)
                if new == 0 and page > 0:
                    break
        print(f"  gem2go: {len(doc_pages)} keyword doc pages", flush=True)
        for i, dp in enumerate(doc_pages[:MAX_DOCS]):
            scan_doc_page(dp, f"gem2go_doc{i}")

    # homepage first (follow its keyword links), then seeds, then the
    # transparency-tree crawl (eZ tenants), the GEM2GO datei module
    # (BZ tenants), then sitemap discovery.
    scan_page(base, "home", 0)
    for i, u in enumerate(listing_urls):
        scan_page(u, f"seed{i}", 1)
    if cfg["platform"] in TREE_PLATFORMS or cfg.get("tree"):
        scan_tree()
    if cfg["platform"] == "civis":
        discover_gem2go()
    scan_sitemap()
    return docs[:MAX_DOCS], len(visited)


_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f�]")


def garble_ratio(text):
    """Share of control/replacement chars — catches PDFs whose embedded
    font encoding makes digital extraction return glyph garbage
    (observed: Levico Terme OpenPA download, 73% control chars,
    accepted by a naive length check before this gate existed)."""
    if not text:
        return 1.0
    return len(_CTRL_RE.findall(text)) / len(text)


def _usable(text):
    """A digital extraction counts only if it is real text: long enough,
    ~no control chars, not made of (cid:N) glyph tokens (PDFs without
    ToUnicode maps — pdfplumber emits those verbatim), and letters are
    a plausible share of the whole (Italian legal prose ~55-70%)."""
    if len(text.strip()) < 300 or garble_ratio(text) > 0.02:
        return False
    if text.count("(cid:") > len(text) / 2000:
        return False
    letters = sum(1 for ch in text if ch.isalpha())
    return letters / len(text) >= 0.45


def extract_text(pdf_path):
    """PDF chain: PyMuPDF -> pdfplumber -> pdftotext -> OCR(ita).
    Every digital method must pass the garble gate, else fall through
    (OCR renders pixels and is immune to font-encoding garbage).
    Returns (text, method, pages)."""
    import fitz

    pages = 0
    try:
        doc = fitz.open(pdf_path)
        pages = doc.page_count
        text = "\n".join(p.get_text() for p in doc)
        doc.close()
        if _usable(text):
            return text, "pymupdf", pages
    except Exception:
        pass
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            pages = pages or len(pdf.pages)
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        if _usable(text):
            return text, "pdfplumber", pages
    except Exception:
        pass
    try:
        out = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"],
                             capture_output=True, timeout=180)
        text = out.stdout.decode("utf-8", errors="replace")
        if _usable(text):
            return text, "pdftotext", pages
    except Exception:
        pass
    # OCR fallback via the persistent tessroot wrapper (ita)
    try:
        if pages and pages <= 80:
            with __import__("tempfile").TemporaryDirectory() as td:
                subprocess.run(["pdftoppm", "-r", "300", "-png",
                                str(pdf_path), str(Path(td) / "pg")],
                               capture_output=True, timeout=600)
                texts = []
                for img in sorted(Path(td).glob("pg*.png")):
                    o = subprocess.run([TESSERACT, str(img), "stdout",
                                        "-l", "ita"],
                                       capture_output=True, timeout=300)
                    texts.append(o.stdout.decode("utf-8", errors="replace"))
                text = "\n".join(texts)
                if text.strip():
                    return text, "ocr_tesseract_ita", pages
    except Exception:
        pass
    return "", "none", pages


ART_RE = re.compile(
    r"(?m)^[ \t]*(Art\.\s*\d+[a-z]?(?:\s*[-–]\s*[^\n]{0,80})?|Articolo\s+\d+[a-z]?)\s*$"
    r"|^[ \t]*(Art\.\s*\d+[a-z]?)\s+[A-ZÀÈÉÌÒÙ]")


def split_articles(text):
    """Split regolamento text at 'Art. N' / 'Articolo N' headings."""
    matches = list(ART_RE.finditer(text))
    if len(matches) < 2:
        return [("", text.strip())]
    segs = []
    pre = text[: matches[0].start()].strip()
    if len(pre) >= 40:
        segs.append(("Premessa", pre))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        seg = text[m.start():end].strip()
        if seg:
            label = (m.group(1) or m.group(2) or "Art.").strip()
            segs.append((re.sub(r"\s+", " ", label)[:60], seg))
    return segs or [("", text.strip())]


EFF_RE = re.compile(
    r"in vigore[^\n]{0,50}?(\d{1,2})[./](\d{1,2})[./](\d{4})|"
    r"(\d{1,2})[./](\d{1,2})[./](\d{4})[^\n]{0,30}?in vigore", re.I)


def date_effective(text):
    m = EFF_RE.search(text)
    if not m:
        return ""
    g = [x for x in m.groups() if x]
    if len(g) == 3:
        d, mo, y = g
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return ""


def text_to_html(text):
    esc = html_mod.escape(text)
    return "<p>" + esc.replace("\n", "<br/>\n") + "</p>"


def harvest_comune(code):
    cfg = COMUNI[code]
    code = jurisdiction.get_scheme("IT").normalize(code)
    # Fail-closed registry cross-check: the config's name must be the
    # ISTAT registry's name for this exact code (a wrong code/name
    # pairing must never reach a parquet).
    reg = registry().get(code)
    if reg is None:
        raise RuntimeError(f"code {code} not in ISTAT registry")
    if reg["name"] != cfg["name"]:
        raise RuntimeError(
            f"registry name mismatch for {code}: registry={reg['name']!r} "
            f"config={cfg['name']!r}")
    t0 = time.time()
    stats = {"code": code, "name": cfg["name"], "region": cfg["region"],
             "platform": cfg["platform"], "docs_listed": 0, "downloaded": 0,
             "extracted": 0, "scanned_or_empty": 0, "download_failed": 0,
             "name_hits": 0, "pages": 0, "methods": {}}
    # Liveness pre-check tuned to the observed regime (2026-10-14 late:
    # egress not dead but ~30 s+ latency — curl fetched istat.it with a
    # 200 at the 30 s mark while 15 s connect timeouts all failed).
    try:
        fetch(S, cfg["base"], timeout=(20, 60), tries=2, deadline=150,
              max_bytes=100_000)
    except Exception as e:
        stats["errors"] = [f"host unreachable this pass: {type(e).__name__}"]
        stats["rows"] = 0
        stats["valid"] = False
        stats["seconds"] = round(time.time() - t0, 1)
        print(f"{code} {cfg['name']}: SKIPPED (host unreachable)", flush=True)
        return stats
    global PACING_CUR
    robots_excerpt, dis, sitemaps, crawl_delay = robots_check(cfg["base"])
    PACING_CUR = max(PACING_S, crawl_delay)
    stats["robots"] = robots_excerpt[:200]
    stats["robots_disallows"] = dis
    stats["crawl_delay"] = crawl_delay
    docs, n_pages = discover_docs(code, cfg, dis, sitemaps)
    stats["docs_listed"] = len(docs)
    stats["listing_pages"] = n_pages
    print(f"{code} {cfg['name']}: {len(docs)} docs from {n_pages} listing pages",
          flush=True)
    pdf_dir = RAW / "pdf" / code
    pdf_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    name_probe = cfg["name"].split("/")[0].strip().lower()
    for di, doc in enumerate(docs):
        fname = unquote(Path(urlparse(doc["url"]).path).name) or f"doc{di}.pdf"
        fname = re.sub(r"[^A-Za-z0-9._-]+", "_", fname)[:120]
        dest = pdf_dir / fname
        try:
            if not dest.exists() or dest.stat().st_size == 0:
                status, _, body = fetch(S, doc["url"], binary=True,
                                        timeout=(20, 120), tries=4,
                                        max_bytes=30_000_000, deadline=1200)
                if status != 200 or not body.startswith(b"%PDF"):
                    raise RuntimeError(f"HTTP {status} / not a PDF")
                dest.write_bytes(body)
                time.sleep(PACING_CUR)
            stats["downloaded"] += 1
        except Exception as e:
            stats["download_failed"] += 1
            print(f"  DL FAIL {doc['url'][:90]}: {e}"[:170], flush=True)
            continue
        text, method, pages = extract_text(dest)
        stats["pages"] += pages
        stats["methods"][method] = stats["methods"].get(method, 0) + 1
        if len(text.strip()) < 100:
            stats["scanned_or_empty"] += 1
            continue
        stats["extracted"] += 1
        if name_probe and name_probe in text.lower():
            stats["name_hits"] += 1
        title = doc["title"] or fname
        slug = normalize.slugify(Path(fname).stem) or f"doc{di}"
        segs = split_articles(text)
        for si, (label, seg) in enumerate(segs):
            doc_id = f"{code}-{slug}"
            if len(segs) > 1:
                doc_id = f"{doc_id}-{si}"
            rows.append(normalize.make_row(
                jurisdiction_id=code,
                jurisdiction_name=cfg["name"],
                country="IT",
                doc_id=doc_id,
                regeling_id=slug,
                regeling_work_id=slug,
                title=title,
                structural_path=title,
                node_label=label,
                body_html=text_to_html(seg),
                text=seg,
                source_url=doc["url"],
                date_effective=date_effective(text),
                date_modified="",
                retrieved=RETRIEVED,
                platform=cfg["platform"],
            ))
    rows = normalize.finalize_rows(normalize.drop_empty_rows(rows))
    table = wm_schema.rows_to_table(rows, extra_columns=EXTRA_COLS)
    report = wm_schema.validation_report(
        table, jurisdiction_id=code, jurisdiction_name=cfg["name"], country="IT")
    if table.num_rows > 0:
        parquet_io.write_html_parquet(OUT / f"{code}_html.parquet", table)
    parquet_io.write_validation_report(OUT / f"{code}_validation.json", report)
    stats["rows"] = table.num_rows
    stats["valid"] = report["valid"]
    stats["errors"] = report["errors"]
    stats["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(stats, ensure_ascii=False), flush=True)
    return stats


def main():
    summary_path = Path(os.environ.get(
        "IT_SUMMARY", str(OUT / "tranche1_summary.json")))
    all_stats = []
    if summary_path.exists():
        all_stats = json.loads(summary_path.read_text(encoding="utf-8"))
    by_code = {s["code"]: s for s in all_stats}

    def is_done(code):
        s = by_code.get(code)
        return bool(s and s.get("valid") and s.get("rows", 0) > 0)

    queue = [c for c in sys.argv[1:] if not is_done(c)]
    for c in sys.argv[1:]:
        if is_done(c):
            print(f"skip {c} (already valid in summary)", flush=True)
    # two passes: egress windows open and close over time; a comune that
    # fails pass 1 gets a second chance after the others have run.
    for pass_no in (1, 2):
        remaining = []
        for code in queue:
            st = harvest_comune(code)
            by_code[code] = st
            all_stats = list(by_code.values())
            summary_path.write_text(json.dumps(all_stats, indent=1,
                                               ensure_ascii=False),
                                    encoding="utf-8")
            if not (st.get("valid") and st.get("rows", 0) > 0):
                remaining.append(code)
        queue = remaining
        if not queue:
            break
        print(f"pass {pass_no} done; retrying {queue}", flush=True)


if __name__ == "__main__":
    main()
