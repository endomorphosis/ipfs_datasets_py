#!/usr/bin/env python3
"""Collect in-force EU legal acts (CELEX sector 3, plus sector 1 treaties) from CELLAR.

Discovery: CELLAR SPARQL (https://publications.europa.eu/webapi/rdf/sparql)
Content:   CELLAR REST  (https://publications.europa.eu/resource/celex/{CELEX}.{LANG3})
Fallback:  EUR-Lex official HTML (legal-content/EN/TXT/HTML)

Does not use the EU-Login data dump (datadump.publications.europa.eu).
Does not git-clone. Does not touch /workspace/legal-corpora/{de,es,fr,nl,ch}.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import tempfile
import threading
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree as ET

import requests

try:
    import jsonschema
except ImportError:
    jsonschema = None  # type: ignore


ROOT = Path("/workspace/legal-corpora/eu")
SCHEMA_PATH = Path("/workspace/legal-corpora/_templates/collection_record.schema.json")
INSTRUMENTS = ROOT / "instruments"
LOGS = ROOT / "logs"
INDEX_PATH = ROOT / "index.jsonl"
FAILURES_PATH = LOGS / "failures.jsonl"
CATALOG_PATH = LOGS / "catalog.jsonl"
ITEMS_PATH = LOGS / "items.jsonl"
SUMMARY_PATH = ROOT / "SUMMARY.md"
PROGRESS_PATH = LOGS / "progress.json"
LOG_PATH = LOGS / "collector.log"

SPARQL_URL = "https://publications.europa.eu/webapi/rdf/sparql"
CELLAR_CELEX = "https://publications.europa.eu/resource/celex/"
EURLEX_TXT = "https://eur-lex.europa.eu/legal-content/{lang}/TXT/?uri=CELEX:{celex}"
EURLEX_HTML = "https://eur-lex.europa.eu/legal-content/{lang}/TXT/HTML/?uri=CELEX:{celex}"
EURLEX_NOTICE = "https://eur-lex.europa.eu/legal-content/{lang}/ALL/?uri=CELEX:{celex}"

USER_AGENT = (
    "justiceDAO-legal-corpora/1.0 "
    "(EU in-force CELEX sector-3 collector; reuse per Commission Decision 2011/833/EU; "
    "https://eur-lex.europa.eu/content/help/data-reuse/reuse-contents-eurlex-details.html)"
)

LICENSE_TEXT = (
    "Reuse of EUR-Lex legal documents per Commission Decision 2011/833/EU "
    "(OJ L 330, 14.12.2011, p. 39). Unless otherwise specified, legal documents "
    "published in EUR-Lex may be re-used for commercial or non-commercial purposes. "
    "© European Union, https://eur-lex.europa.eu. Some documents (e.g. International "
    "Accounting Standards) may be subject to special conditions stated in the OJ/document. "
    "EUR-Lex metadata is dedicated to the public domain (CC0 1.0). Editorial content, "
    "summaries of EU legislation and consolidated texts on EUR-Lex are licensed CC-BY-4.0; "
    "this corpus stores CELLAR/OJ sector-3 (and optional sector-1) legal acts, not those "
    "editorial/consolidated pages. The EUR-Lex logo may not be used without prior consent "
    "of the Publications Office. Only the Official Journal is authentic. Not legal advice."
)

OFFICIAL_REUSE_URL = "https://eur-lex.europa.eu/content/legal-notice/legal-notice.html"
REUSE_HELP_URL = "https://eur-lex.europa.eu/content/help/data-reuse/reuse-contents-eurlex-details.html"
DECISION_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32011D0833"

# ISO 639-3 (CELLAR) -> 639-1
LANG3_TO_1 = {
    "BUL": "bg", "SPA": "es", "CES": "cs", "DAN": "da", "DEU": "de", "EST": "et",
    "ELL": "el", "ENG": "en", "FRA": "fr", "GLE": "ga", "HRV": "hr", "ITA": "it",
    "LAV": "lv", "LIT": "lt", "HUN": "hu", "MLT": "mt", "NLD": "nl", "POL": "pl",
    "POR": "pt", "RON": "ro", "SLK": "sk", "SLV": "sl", "FIN": "fi", "SWE": "sv",
    "GLE": "ga",
}
LANG1_TO_3 = {v: k for k, v in LANG3_TO_1.items()}
FETCH_LANG_ORDER = ["ENG", "FRA", "DEU", "ITA", "SPA", "NLD", "POL", "POR", "RON", "CES", "SWE", "DAN"]

CELEX_TYPE_LETTER = {
    "R": ("regulation", "regulation"),
    "L": ("law", "directive"),
    "D": ("instrument", "decision"),
    "E": ("instrument", "decision_cfsp"),
    "F": ("instrument", "budget"),
    "H": ("instrument", "recommendation"),
    "A": ("instrument", "agreement"),
    "X": ("instrument", "other"),
    "Q": ("instrument", "recommendation"),
    "K": ("instrument", "recommendation"),
    "S": ("instrument", "other"),
}

RTYPE_MAP = {
    "REG": ("regulation", "regulation"),
    "REG_IMPL": ("regulation", "implementing_regulation"),
    "REG_DEL": ("regulation", "delegated_regulation"),
    "REG_FINANC": ("regulation", "regulation"),
    "DIR": ("law", "directive"),
    "DIR_IMPL": ("law", "implementing_directive"),
    "DIR_DEL": ("law", "delegated_directive"),
    "DEC": ("instrument", "decision"),
    "DEC_ENTSCHEID": ("instrument", "decision"),
    "DEC_IMPL": ("instrument", "implementing_decision"),
    "DEC_DEL": ("instrument", "delegated_decision"),
    "RECO": ("instrument", "recommendation"),
    "RES": ("instrument", "resolution"),
    "OPIN": ("instrument", "opinion"),
    "GUIDELINE": ("instrument", "guideline"),
    "TREATY": ("constitution", "treaty"),
    "PROT": ("instrument", "protocol"),
    "AGREE_INTERNATION": ("instrument", "international_agreement"),
}

NS_STRIP = re.compile(r"\{[^}]+\}")
WS_RE = re.compile(r"[ \t]+\n")
MULTI_NL = re.compile(r"\n{3,}")
MULTI_SP = re.compile(r"[ \t]{2,}")
ART_ID_RE = re.compile(r"^art_([0-9]+[a-zA-Z]?)$", re.I)
CELEX_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")

_log_lock = threading.Lock()
_index_lock = threading.Lock()
_fail_lock = threading.Lock()
_summary_lock = threading.Lock()
_stats_lock = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pt_now(iso_utc: str | None = None) -> str:
    if iso_utc:
        dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    # America/Los_Angeles = UTC-7 in early September 2026 (PDT)
    local = dt.timestamp() - 7 * 3600
    return datetime.fromtimestamp(local, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S PT")


def log(msg: str) -> None:
    line = f"{utc_now()} {msg}"
    with _log_lock:
        LOGS.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        print(line, flush=True)


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


def celex_to_id(celex: str) -> str:
    safe = CELEX_SAFE_RE.sub("-", celex)
    safe = re.sub(r"-{2,}", "-", safe).strip("-")
    return f"eu-{safe}"


def sector_of(celex: str) -> str:
    return celex[0] if celex else ""


def type_letter(celex: str) -> str:
    # 3YYYYTNNNN...
    if len(celex) >= 6 and celex[1:5].isdigit():
        return celex[5].upper()
    return ""


class RateLimiter:
    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self.lock = threading.Lock()
        self.next_t = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            sleep_for = self.next_t - now
            self.next_t = max(now, self.next_t) + self.min_interval
        if sleep_for > 0:
            time.sleep(sleep_for)


class HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "head", "title", "meta", "link"):
            self.skip += 1
        if tag in ("p", "div", "tr", "h1", "h2", "h3", "h4", "li", "br", "article"):
            self.parts.append("\n")
        if tag == "td":
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head", "title", "meta", "link") and self.skip:
            self.skip -= 1
        if tag in ("p", "div", "tr", "h1", "h2", "h3", "h4", "li"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = html.unescape(raw)
        raw = MULTI_SP.sub(" ", raw)
        raw = WS_RE.sub("\n", raw)
        raw = MULTI_NL.sub("\n\n", raw)
        return raw.strip()


def html_to_text(src: str) -> str:
    body = src
    m = re.search(r"(?is)<body\b[^>]*>(.*)</body>", src)
    if m:
        body = m.group(1)
    body = re.sub(r"(?is)<script\b[^>]*>.*?</script>", " ", body)
    body = re.sub(r"(?is)<style\b[^>]*>.*?</style>", " ", body)
    parser = HtmlText()
    try:
        parser.feed(body)
        parser.close()
        text = parser.text()
    except Exception:
        text = ""
    if not text.strip():
        tmp = re.sub(r"(?s)<[^>]+>", " ", body)
        text = MULTI_NL.sub("\n\n", html.unescape(tmp)).strip()
        text = MULTI_SP.sub(" ", text)
    return text.strip()


def local_tag(el: ET.Element) -> str:
    return NS_STRIP.sub("", el.tag)


def elem_text(el: ET.Element) -> str:
    bits: list[str] = []

    def walk(node: ET.Element) -> None:
        if node.text:
            bits.append(node.text)
        for child in list(node):
            tag = local_tag(child)
            if tag in ("p", "div", "br", "tr", "h1", "h2", "h3", "h4", "li"):
                bits.append("\n")
            walk(child)
            if child.tail:
                bits.append(child.tail)
            if tag in ("p", "div", "tr", "li"):
                bits.append("\n")

    walk(el)
    raw = "".join(bits)
    raw = MULTI_SP.sub(" ", raw)
    raw = WS_RE.sub("\n", raw)
    raw = MULTI_NL.sub("\n\n", raw)
    return raw.strip()


def parse_articles_xhtml(src: str) -> tuple[str, list[dict[str, str]], str]:
    """Return (title_guess, articles[{id,number,heading,title,text}], status)."""
    articles: list[dict[str, str]] = []
    title_guess = ""
    try:
        # CONVEX XHTML may reference a local DTD; don't resolve it.
        xml_src = re.sub(r"<!DOCTYPE[^>]*>", "", src, count=1, flags=re.I)
        root = ET.fromstring(xml_src)
    except Exception:
        return title_guess, articles, "parse_error"

    title_ps: list[str] = []
    for el in root.iter():
        tag = local_tag(el)
        cls = (el.attrib.get("class") or "")
        if "oj-doc-ti" in cls or cls == "doc-ti":
            t = "".join(el.itertext()).strip()
            if t:
                title_ps.append(t)

        eid = el.attrib.get("id") or ""
        m = ART_ID_RE.match(eid)
        if m and tag in ("div", "article"):
            number = m.group(1)
            heading = ""
            ti = ""
            for child in el.iter():
                ccls = child.attrib.get("class") or ""
                if "oj-ti-art" in ccls or ccls == "ti-art":
                    ti = "".join(child.itertext()).strip()
                    break
            for child in el.iter():
                ccls = child.attrib.get("class") or ""
                if "oj-sti-art" in ccls or ccls == "sti-art":
                    heading = "".join(child.itertext()).strip()
                    break
            body = elem_text(el)
            articles.append({
                "number": number,
                "heading": heading,
                "ti": ti or f"Article {number}",
                "text": body,
            })

    if title_ps:
        title_guess = " ".join(title_ps)
        title_guess = MULTI_SP.sub(" ", title_guess).strip()

    if articles:
        return title_guess, articles, "ok"

    # Fallback: sequential ti-art paragraphs (legacy HTML)
    ti_nodes: list[ET.Element] = []
    for el in root.iter():
        cls = el.attrib.get("class") or ""
        if "ti-art" in cls:
            ti_nodes.append(el)
    if not ti_nodes:
        return title_guess, articles, "missing"
    # Too fragile to split by following siblings in nested trees; treat as missing
    return title_guess, articles, "missing"


def parse_articles_html_regex(src: str) -> tuple[str, list[dict[str, str]], str]:
    title_ps = re.findall(
        r'class="[^"]*oj-doc-ti[^"]*"[^>]*>(.*?)</p>', src, flags=re.I | re.S
    )
    title_guess = " ".join(html_to_text(f"<p>{t}</p>") for t in title_ps[:6]).strip()
    chunks = list(re.finditer(
        r'<div[^>]*class="[^"]*eli-subdivision[^"]*"[^>]*id="(art_[^"]+)"[^>]*>',
        src, flags=re.I,
    ))
    articles: list[dict[str, str]] = []
    if not chunks:
        return title_guess, articles, "missing"
    for i, m in enumerate(chunks):
        eid = m.group(1)
        am = ART_ID_RE.match(eid)
        if not am:
            continue
        start = m.start()
        end = chunks[i + 1].start() if i + 1 < len(chunks) else len(src)
        block = src[start:end]
        # close at next top-level art or generous window
        number = am.group(1)
        ti_m = re.search(r'class="[^"]*ti-art[^"]*"[^>]*>(.*?)</p>', block, flags=re.I | re.S)
        sti_m = re.search(r'class="[^"]*sti-art[^"]*"[^>]*>(.*?)</p>', block, flags=re.I | re.S)
        ti = html_to_text(ti_m.group(1)) if ti_m else f"Article {number}"
        heading = html_to_text(sti_m.group(1)) if sti_m else ""
        text = html_to_text(block)
        articles.append({"number": number, "heading": heading, "ti": ti, "text": text})
    return title_guess, articles, ("ok" if articles else "missing")


def extract_from_content(src: str, content_type: str) -> tuple[str, str, list[dict[str, str]], str]:
    """Returns title_guess, full_text, articles, extraction_status."""
    src = src.lstrip("\ufeff")
    looks_xml = src.lstrip().startswith("<?xml") or src.lstrip().startswith("<html") or src.lstrip().startswith("<HTML")
    title_guess, articles, status = ("", [], "missing")
    if looks_xml or "xhtml" in (content_type or "") or "xml" in (content_type or ""):
        title_guess, articles, status = parse_articles_xhtml(src)
        if status != "ok":
            t2, a2, s2 = parse_articles_html_regex(src)
            if a2:
                title_guess = title_guess or t2
                articles, status = a2, s2
    else:
        title_guess, articles, status = parse_articles_html_regex(src)
        if status != "ok":
            t2, a2, s2 = parse_articles_xhtml(src)
            if a2:
                title_guess = title_guess or t2
                articles, status = a2, s2
    full = html_to_text(src)
    if not full and articles:
        full = "\n\n".join(a["text"] for a in articles if a.get("text"))
    if not articles:
        # Formex ARTICLE elements
        if "<ARTICLE" in src.upper() or "<article" in src:
            try:
                root = ET.fromstring(src.encode("utf-8"))
                arts = []
                n = 0
                for el in root.iter():
                    if local_tag(el).upper() == "ARTICLE":
                        n += 1
                        num = el.attrib.get("NO") or el.attrib.get("IDENTIFIER") or str(n)
                        body = elem_text(el)
                        arts.append({"number": str(num), "heading": "", "ti": f"Article {num}", "text": body})
                if arts:
                    articles, status = arts, "ok"
            except Exception:
                pass
    if not articles:
        status = "non_article_document" if full else "missing"
    return title_guess, full, articles, status


class CellarClient:
    def __init__(self, limiter: RateLimiter, timeout: int = 90) -> None:
        self.limiter = limiter
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        adapter = requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=16, max_retries=0)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def sparql(self, query: str, timeout: int | None = None) -> dict[str, Any]:
        self.limiter.wait()
        last_err: Exception | None = None
        for attempt in range(6):
            try:
                r = self.session.post(
                    SPARQL_URL,
                    data={"query": query, "format": "application/sparql-results+json"},
                    headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
                    timeout=timeout or 120,
                )
                if r.status_code in (429, 503, 502, 500):
                    time.sleep(min(60, 2 ** attempt))
                    continue
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last_err = e
                time.sleep(min(60, 2 ** attempt))
        raise RuntimeError(f"SPARQL failed: {last_err}")

    def fetch_celex(self, celex: str, lang3: str) -> tuple[int, str, bytes, str]:
        """Return status, final_url, content, content_type."""
        encoded = quote(celex, safe="()-._")
        url = f"{CELLAR_CELEX}{encoded}.{lang3}"
        accept = "application/xhtml+xml, text/html;q=0.9, application/xml;q=0.8, */*;q=0.1"
        self.limiter.wait()
        r = self.session.get(
            url,
            headers={"Accept": accept, "User-Agent": USER_AGENT},
            timeout=self.timeout,
            allow_redirects=True,
        )
        ctype = r.headers.get("Content-Type") or ""
        return r.status_code, r.url, r.content, ctype

    def fetch_eurlex_html(self, celex: str, lang1: str = "EN") -> tuple[int, str, bytes, str]:
        url = EURLEX_HTML.format(lang=lang1.upper(), celex=quote(celex, safe="()-._"))
        self.limiter.wait()
        r = self.session.get(
            url,
            headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": USER_AGENT},
            timeout=self.timeout,
            allow_redirects=True,
        )
        return r.status_code, r.url, r.content, r.headers.get("Content-Type") or ""

    def _retry_get(self, fn, *args, attempts: int = 6):
        last = (0, "", b"", "")
        for i in range(attempts):
            try:
                last = fn(*args)
            except Exception:
                time.sleep(min(25, 1.4 * (i + 1)))
                continue
            status, _url, content, _ctype = last
            if status == 200 and content and len(content) > 40:
                return last
            if status in (202, 429, 500, 502, 503):
                time.sleep(min(25, 1.6 * (i + 1)))
                continue
            return last
        return last

    def fetch_celex_ok(self, celex: str, lang3: str) -> tuple[int, str, bytes, str]:
        return self._retry_get(self.fetch_celex, celex, lang3)

    def fetch_eurlex_ok(self, celex: str, lang1: str = "EN") -> tuple[int, str, bytes, str]:
        return self._retry_get(self.fetch_eurlex_html, celex, lang1)



    def fetch_url(self, url: str) -> tuple[int, str, bytes, str]:
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        self.limiter.wait()
        r = self.session.get(
            url,
            headers={
                "Accept": "application/xhtml+xml, text/html;q=0.9, application/xml;q=0.8, */*;q=0.1",
                "User-Agent": USER_AGENT,
            },
            timeout=self.timeout,
            allow_redirects=True,
        )
        return r.status_code, r.url, r.content, r.headers.get("Content-Type") or ""


def maybe_unzip(content: bytes, ctype: str) -> tuple[bytes, str]:
    if not content.startswith(b"PK"):
        return content, ctype
    import io, zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
            prefer = [n for n in names if n.lower().endswith((".xhtml", ".html", ".xml"))]
            pick = prefer or names
            parts = [zf.read(n) for n in pick]
            return b"\n".join(parts), "application/xml; via=zip"
    except Exception:
        return content, ctype


def bindings(js: dict[str, Any]) -> list[dict[str, Any]]:

    return js.get("results", {}).get("bindings", [])


def bval(row: dict[str, Any], key: str) -> str:
    v = row.get(key)
    if not v:
        return ""
    return v.get("value") or ""



def catalog_sort_key(r: dict[str, Any]) -> tuple:
    c = r.get("celex") or ""
    letter = type_letter(c)
    pri = {"R": 0, "L": 1, "D": 2, "E": 3}.get(letter, 8)
    if "R(" in c:
        pri += 0.4  # corrigenda after the main act-type bucket
    sector_pri = 0 if (r.get("sector") == "3" or c.startswith("3")) else 1
    return (sector_pri, pri, r.get("year") or "", c)


def discover_catalog(client: CellarClient, sectors: list[str], years: list[str] | None) -> list[dict[str, Any]]:
    log("Discovering year histogram via SPARQL")
    year_q = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?year ?prefix (COUNT(DISTINCT ?celex) AS ?n)
WHERE {
  ?work cdm:resource_legal_in-force "true"^^xsd:boolean .
  ?work cdm:resource_legal_id_celex ?celex .
  FILTER NOT EXISTS { ?work cdm:do_not_index "true"^^xsd:boolean }
  BIND(SUBSTR(STR(?celex), 1, 1) AS ?prefix)
  BIND(SUBSTR(STR(?celex), 2, 4) AS ?year)
  FILTER(?prefix in (%s))
}
GROUP BY ?year ?prefix
ORDER BY ?prefix ?year
""" % ", ".join(f'"{s}"' for s in sectors)
    js = client.sparql(year_q)
    hist = [(bval(r, "prefix"), bval(r, "year"), int(bval(r, "n") or 0)) for r in bindings(js)]
    atomic_write(LOGS / "year_histogram.json", json.dumps(hist, indent=2) + "\n")
    log(f"Year histogram rows={len(hist)} total={sum(x[2] for x in hist)}")

    pairs: list[tuple[str, str]] = []
    for prefix, year, n in hist:
        if not year.isdigit():
            continue
        if years and year not in years:
            continue
        pairs.append((prefix, year))

    catalog: dict[str, dict[str, Any]] = {}
    for i, (prefix, year) in enumerate(pairs):
        key = f"{prefix}{year}"
        log(f"Catalog SPARQL {key} ({i+1}/{len(pairs)})")
        meta_q = f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?celex ?eli ?dateDoc ?dateForce ?rtype ?title
WHERE {{
  ?work cdm:resource_legal_in-force "true"^^xsd:boolean .
  ?work cdm:resource_legal_id_celex ?celex .
  FILTER(STRSTARTS(STR(?celex), "{key}"))
  FILTER NOT EXISTS {{ ?work cdm:do_not_index "true"^^xsd:boolean }}
  OPTIONAL {{ ?work cdm:resource_legal_eli ?eli }}
  OPTIONAL {{ ?work cdm:work_date_document ?dateDoc }}
  OPTIONAL {{ ?work cdm:resource_legal_date_entry-into-force ?dateForce }}
  OPTIONAL {{ ?work cdm:work_has_resource-type ?rtype }}
  OPTIONAL {{
    ?expr cdm:expression_belongs_to_work ?work .
    ?expr cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> .
    ?expr cdm:expression_title ?title .
  }}
}}
"""
        try:
            js = client.sparql(meta_q, timeout=180)
        except Exception as e:
            log(f"WARN catalog meta failed {key}: {e}")
            continue
        for row in bindings(js):
            celex = bval(row, "celex")
            if not celex:
                continue
            rec = catalog.setdefault(celex, {
                "celex": celex,
                "sector": prefix,
                "year": year,
                "elis": [],
                "dates_doc": [],
                "dates_force": [],
                "rtypes": [],
                "titles": [],
                "langs": [],
            })
            eli = bval(row, "eli")
            if eli and eli not in rec["elis"]:
                rec["elis"].append(eli)
            d = bval(row, "dateDoc")[:10]
            if d and d not in rec["dates_doc"]:
                rec["dates_doc"].append(d)
            d = bval(row, "dateForce")[:10]
            if d and d not in rec["dates_force"]:
                rec["dates_force"].append(d)
            rt = bval(row, "rtype")
            if rt and rt not in rec["rtypes"]:
                rec["rtypes"].append(rt)
            t = bval(row, "title")
            if t and t not in rec["titles"]:
                rec["titles"].append(t)

        lang_q = f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
SELECT DISTINCT ?celex ?langCode
WHERE {{
  ?work cdm:resource_legal_in-force "true"^^xsd:boolean .
  ?work cdm:resource_legal_id_celex ?celex .
  FILTER(STRSTARTS(STR(?celex), "{key}"))
  FILTER NOT EXISTS {{ ?work cdm:do_not_index "true"^^xsd:boolean }}
  ?expr cdm:expression_belongs_to_work ?work .
  ?expr cdm:expression_uses_language ?lang .
  ?lang dc:identifier ?langCode .
}}
"""
        try:
            js = client.sparql(lang_q, timeout=180)
            for row in bindings(js):
                celex = bval(row, "celex")
                lang = bval(row, "langCode").upper()
                rec = catalog.get(celex)
                if rec is not None and lang and lang not in rec["langs"]:
                    rec["langs"].append(lang)
        except Exception as e:
            log(f"WARN catalog langs failed {key}: {e}")

    items = list(catalog.values())
    items.sort(key=catalog_sort_key)
    with CATALOG_PATH.open("w", encoding="utf-8") as fh:
        for rec in items:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    log(f"Catalog written {len(items)} -> {CATALOG_PATH}")
    return items


def load_catalog() -> list[dict[str, Any]]:
    items = []
    if not CATALOG_PATH.exists():
        return items
    with CATALOG_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def pick_eli(elis: list[str]) -> str | None:
    if not elis:
        return None
    oj = [e for e in elis if e.rstrip("/").endswith("/oj")]
    if oj:
        return sorted(oj, key=len)[0]
    return sorted(elis, key=len)[0]


def rtype_code(uri: str) -> str:
    return uri.rstrip("/").rsplit("/", 1)[-1] if uri else ""


def classify(celex: str, rtypes: list[str]) -> tuple[str, str]:
    for rt in rtypes:
        code = rtype_code(rt)
        if code in RTYPE_MAP:
            return RTYPE_MAP[code]
    letter = type_letter(celex)
    if letter in CELEX_TYPE_LETTER:
        return CELEX_TYPE_LETTER[letter]
    if sector_of(celex) == "1":
        return "constitution", "treaty"
    return "instrument", "legal_act"


def iso_date(s: str | None) -> str | None:
    if not s:
        return None
    s = s[:10]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    return None


def existing_instrument_ids() -> set[str]:
    ids = set()
    if INSTRUMENTS.exists():
        for p in INSTRUMENTS.glob("*.json"):
            ids.add(p.stem)
    return ids


def indexed_ids() -> set[str]:
    ids = set()
    if INDEX_PATH.exists():
        with INDEX_PATH.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ids.add(json.loads(line).get("id") or "")
                except Exception:
                    continue
    ids.discard("")
    return ids


class Stats:
    def __init__(self) -> None:
        self.discovered = 0
        self.fetched = 0
        self.written = 0
        self.skipped_exists = 0
        self.failed = 0
        self.empty_text = 0
        self.by_status: Counter[str] = Counter()
        self.by_type: Counter[str] = Counter()
        self.by_sector: Counter[str] = Counter()
        self.bytes = 0
        self.start = utc_now()
        self.lock = threading.Lock()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "discovered": self.discovered,
                "fetched": self.fetched,
                "written": self.written,
                "skipped_exists": self.skipped_exists,
                "failed": self.failed,
                "empty_text": self.empty_text,
                "by_status": dict(self.by_status),
                "by_type": dict(self.by_type),
                "by_sector": dict(self.by_sector),
                "bytes": self.bytes,
                "start": self.start,
                "now": utc_now(),
            }


def write_summary(stats: Stats, extra: dict[str, Any] | None = None) -> None:
    snap = stats.snapshot()
    extra = extra or {}
    n_files = 0
    if INSTRUMENTS.exists():
        n_files = sum(1 for _ in INSTRUMENTS.glob("*.json"))
    index_lines = 0
    if INDEX_PATH.exists():
        with INDEX_PATH.open(encoding="utf-8") as fh:
            for _ in fh:
                index_lines += 1
    fail_lines = 0
    if FAILURES_PATH.exists():
        with FAILURES_PATH.open(encoding="utf-8") as fh:
            for _ in fh:
                fail_lines += 1
    try:
        total_bytes = sum(p.stat().st_size for p in INSTRUMENTS.glob("*.json")) if n_files else 0
    except OSError:
        total_bytes = snap.get("bytes") or 0
    law_status = snap.get("by_status") or {}
    now = utc_now()
    discovered = extra.get("discovered", snap["discovered"])
    coverage = "catalog-backed incomplete"
    if discovered and snap["written"] + snap["failed"] + snap["skipped_exists"] >= discovered and snap["written"]:
        if snap["failed"] == 0 and snap["written"] + snap["skipped_exists"] >= discovered:
            coverage = "full"
    body = f"""# European Union legislation corpus (EUR-Lex / CELLAR)

- jurisdiction: EU
- country: European Union
- language: en (English expression; other official language codes listed per instrument in `languages`)
- source: Publications Office of the EU — CELLAR SPARQL + CELLAR REST (EUR-Lex)
- source_type: eurlex
- identifier: CELEX (ELI when present)
- last_run_retrieved_at: {now} (PT: {pt_now(now)})
- instruments_json: {n_files}
- index_jsonl_lines: {index_lines}
- discovered: {discovered}
- fetched: {snap['fetched']}
- parsed/written: {snap['written']}
- skipped_exists: {snap['skipped_exists']}
- failed: {snap['failed']} (failures.jsonl lines: {fail_lines})
- empty_text: {snap['empty_text']}
- law_status: current={law_status.get('current', 0)} historical={law_status.get('historical', 0)} repealed={law_status.get('repealed', 0)} superseded={law_status.get('superseded', 0)} unknown={law_status.get('unknown', 0)}
- coverage: {coverage}
- instruments_bytes: {total_bytes} ({total_bytes/1e9:.3f} GB)
- dump used: **none** (EUR-Lex data dump at https://datadump.publications.europa.eu/ requires EU Login; not available in this environment)
- discovery: CELLAR SPARQL `cdm:resource_legal_in-force true` + CELEX sector prefix
- content: CELLAR REST `https://publications.europa.eu/resource/celex/{{CELEX}}.ENG` (XHTML), EUR-Lex TXT/HTML fallback

## Official sources

- EUR-Lex reuse: {REUSE_HELP_URL}
- Machine-readable retrieval PDF: https://eur-lex.europa.eu/content/tools/Retrieval_machine-readable_formats.pdf
- CELLAR SPARQL: {SPARQL_URL}
- CELLAR REST content: https://publications.europa.eu/resource/celex/{{CELEX}}.{{LANG3}}
- Data dump (EU Login, not used): https://datadump.publications.europa.eu/
- EUR-Lex: https://eur-lex.europa.eu/
- CELLAR docs: https://op.europa.eu/en/web/cellar

## License / reuse (publisher terms; not invented CC-BY for the acts)

{LICENSE_TEXT}

- Legal notice: {OFFICIAL_REUSE_URL}
- Commission Decision 2011/833/EU: {DECISION_URL}

## Scope

In-force **CELEX sector 3** legal acts (regulations, directives, decisions and other sector-3 acts still in force), plus **sector 1 treaties** when included in the catalog. Not case law (ECLI / sector 6) unless a CELEX-3/1 work is also tagged that way. Original OJ/CELLAR expressions (not CELEX sector 0 consolidations).

## Timing

- Start (UTC): {snap['start']}
- Start (PT):  {pt_now(snap['start'])}
- Last update (UTC): {now}
- Last update (PT): {pt_now(now)}

## Counts by CELEX sector

{json.dumps(snap.get('by_sector') or {}, indent=2)}

## Counts by document_type

{json.dumps(snap.get('by_type') or {}, indent=2)}

## Layout

- `instruments/{{id}}.json` — one collection_record per CELEX work (`id` = `eu-{{CELEX}}`, unsafe chars folded)
- `index.jsonl` — append-only
- `logs/catalog.jsonl` — SPARQL discovery rows
- `logs/failures.jsonl`
- `logs/collector.log`

## Blockers / notes

- Data dump of in-force acts (FMX/HTML per language) requires EU Login; collector used public CELLAR SPARQL + REST instead.
- Dataset is not legal advice (`metadata.rights.not_legal_advice: true`).
- Only the Official Journal text is authentic.
- Do not disturb sibling corpora under `/workspace/legal-corpora/{{de,es,fr,nl,ch}}`.

## Failures

See `logs/failures.jsonl` ({fail_lines} lines).
"""
    with _summary_lock:
        atomic_write(SUMMARY_PATH, body)


def append_jsonl(path: Path, obj: dict[str, Any], lock: threading.Lock) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)


def build_record(
    cat: dict[str, Any],
    *,
    text: str,
    articles: list[dict[str, str]],
    extraction_status: str,
    title_guess: str,
    source_url: str,
    content_url: str,
    content_type: str,
    http_status: int,
    raw_sha: str,
    fetched_lang3: str,
    retrieved_at: str,
) -> dict[str, Any]:
    celex = cat["celex"]
    ident = celex_to_id(celex)
    record_type, document_type = classify(celex, cat.get("rtypes") or [])
    title = (cat.get("titles") or [None])[0] or title_guess or celex
    title = MULTI_SP.sub(" ", title).strip()
    eli = pick_eli(cat.get("elis") or [])
    date = iso_date((cat.get("dates_force") or [None])[0]) or iso_date((cat.get("dates_doc") or [None])[0])
    langs3 = cat.get("langs") or []
    langs1 = []
    for L in langs3:
        langs1.append(LANG3_TO_1.get(L, L.lower()[:2] if len(L) >= 2 else L.lower()))
    # unique, English first
    seen = set()
    languages = []
    for x in ["en"] + langs1:
        if x and x not in seen:
            seen.add(x)
            languages.append(x)
    fetched_lang1 = LANG3_TO_1.get(fetched_lang3, "en")
    docs = []
    for art in articles:
        num = art["number"]
        heading = art.get("heading") or ""
        ti = art.get("ti") or f"Article {num}"
        art_title = ti if not heading else f"{ti} {heading}".strip()
        doc = {
            "id": f"{ident}-art-{num}",
            "title": art_title,
            "text": art.get("text") or "",
            "document_number": str(num),
            "source_url": source_url + f"#art_{num}",
            "record_type": "article",
            "article_number": str(num),
            "citation": f"{celex} Art. {num}",
            "law_identifier": celex,
            "law_status": "current",
            "is_current": True,
            "retrieved_at": retrieved_at,
            "metadata": {
                "text_extraction": {"source": "cellar_xhtml", "backend": "collect_eurlex"},
            },
        }
        if date:
            doc["date_filed"] = date
            doc["effective_date"] = date
        if heading:
            doc["article_heading"] = heading
        docs.append(doc)
    lang1_upper = fetched_lang1.upper() if len(fetched_lang1) == 2 else "EN"
    record = {
        "schema_version": "collection_record.v1",
        "record_type": record_type,
        "id": ident,
        "title": title,
        "canonical_title": title,
        "text": text,
        "source_url": source_url,
        "source_type": "eurlex",
        "date": date,
        "jurisdiction": "EU",
        "country": "European Union",
        "language": fetched_lang1,
        "languages": languages,
        "eli": eli,
        "celex": celex,
        "ecli": None,
        "license": LICENSE_TEXT,
        "retrieved_at": retrieved_at,
        "identifier": celex,
        "official_identifier": celex,
        "law_identifier": celex,
        "citation": celex,
        "document_type": document_type,
        "canonical_law_url": source_url,
        "canonical_document_url": content_url,
        "information_url": EURLEX_NOTICE.format(lang=lang1_upper, celex=quote(celex, safe="")),
        "law_status": "current",
        "is_current": True,
        "valid_from": iso_date((cat.get("dates_force") or [None])[0]),
        "effective_date": iso_date((cat.get("dates_force") or [None])[0]),
        "publication_date": iso_date((cat.get("dates_doc") or [None])[0]),
        "status_source": "CELLAR cdm:resource_legal_in-force",
        "status_confidence": "high",
        "status_note": "Listed in-force by CELLAR SPARQL at harvest time; original OJ/CELLAR expression (not a sector-0 consolidation).",
        "article_count": len(docs),
        "article_extraction_status": extraction_status,
        "documents": docs,
        "metadata": {
            "collector": "collect_eurlex",
            "collector_run_id": "eu-cellar-2026-09-02",
            "schema": "collection_record.v1",
            "parser": "cellar-xhtml-convex",
            "source_host": "publications.europa.eu",
            "source_path": content_url,
            "http_status": http_status,
            "content_type": content_type,
            "content_sha256": raw_sha,
            "text_extraction": {"source": "cellar_xhtml", "backend": "collect_eurlex"},
            "discovery": {
                "method": "cellar_sparql_in_force",
                "catalog_identifier": celex,
                "seed_url": SPARQL_URL,
            },
            "rights": {
                "license": LICENSE_TEXT,
                "attribution": "© European Union, https://eur-lex.europa.eu",
                "official_reuse_url": OFFICIAL_REUSE_URL,
                "not_legal_advice": True,
                "commission_decision": "2011/833/EU",
            },
            "celex": celex,
            "celex_sector": sector_of(celex),
            "resource_types": [rtype_code(x) for x in (cat.get("rtypes") or [])],
            "cellar_languages": langs3,
            "fetched_language": fetched_lang3,
            "elis": cat.get("elis") or [],
        },
        "official_metadata": {
            "celex": celex,
            "eli": eli,
            "dates_doc": cat.get("dates_doc") or [],
            "dates_force": cat.get("dates_force") or [],
            "rtypes": cat.get("rtypes") or [],
            "year": cat.get("year"),
            "sector": cat.get("sector"),
        },
    }
    for k in ("valid_from", "effective_date", "publication_date", "date"):
        if record.get(k) in (None, ""):
            record.pop(k, None)
    return record



ITEM_FMT_RANK = {"xhtml": 0, "html": 1, "fmx4": 2, "fmx": 3, "xml": 4, "txt": 5}


def load_items() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not ITEMS_PATH.exists():
        return out
    with ITEMS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("celex"):
                out[rec["celex"]] = rec
    return out


def enrich_items(client: CellarClient, catalog: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    items = load_items()
    log(f"Loaded item map {len(items)}")
    done_path = LOGS / "items_keys_done.txt"
    done = set()
    if done_path.exists():
        done = {ln.strip() for ln in done_path.read_text(encoding="utf-8").splitlines() if ln.strip()}
    need_keys = set()
    for rec in catalog:
        prefix = rec.get("sector") or rec["celex"][:1]
        year = rec.get("year") or rec["celex"][1:5]
        if year.isdigit():
            key = prefix + year
            if key not in done:
                need_keys.add(key)
    keys = sorted(need_keys)
    log(f"Item SPARQL keys to fetch: {len(keys)} (done={len(done)})")
    for i, key in enumerate(keys):
        log(f"Items SPARQL {key} ({i+1}/{len(keys)})")
        q = f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?celex ?format ?item
WHERE {{
  ?work cdm:resource_legal_in-force "true"^^xsd:boolean .
  ?work cdm:resource_legal_id_celex ?celex .
  FILTER(STRSTARTS(STR(?celex), "{key}"))
  FILTER NOT EXISTS {{ ?work cdm:do_not_index "true"^^xsd:boolean }}
  ?expr cdm:expression_belongs_to_work ?work .
  ?expr cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> .
  ?manif cdm:manifestation_manifests_expression ?expr .
  ?manif cdm:manifestation_type ?format .
  ?item cdm:item_belongs_to_manifestation ?manif .
}}
"""
        try:
            js = client.sparql(q, timeout=180)
        except Exception as e:
            log(f"WARN items SPARQL failed {key}: {e}")
            continue
        best: dict[str, tuple[int, str, str, str]] = {}
        for row in bindings(js):
            celex = bval(row, "celex")
            fmt = bval(row, "format")
            item = bval(row, "item")
            if not celex or not item:
                continue
            rank = ITEM_FMT_RANK.get(fmt, 8)
            doc1_bonus = 0 if "/DOC_1" in item or item.endswith("DOC_1") else 1
            cur = best.get(celex)
            cand = (rank, doc1_bonus, item, fmt)
            if cur is None or cand[:2] < cur[:2]:
                best[celex] = cand
        with done_path.open("a", encoding="utf-8") as fh:
            fh.write(key + "\n")
        done.add(key)
        with ITEMS_PATH.open("a", encoding="utf-8") as fh:
            for celex, (_rank, _b, item, fmt) in best.items():
                if celex in items:
                    # keep existing preferred
                    old_rank = ITEM_FMT_RANK.get(items[celex].get("format") or "", 9)
                    if old_rank <= _rank:
                        continue
                rec = {"celex": celex, "item": item, "format": fmt}
                items[celex] = rec
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    log(f"Item map size {len(items)}")
    return items


def process_one(
    client: CellarClient,
    cat: dict[str, Any],
    stats: Stats,
    validator: Any,
    max_bytes: int,
) -> str:
    celex = cat["celex"]
    ident = celex_to_id(celex)
    dest = INSTRUMENTS / f"{ident}.json"
    if dest.exists():
        with stats.lock:
            stats.skipped_exists += 1
        return "exists"

    langs = [x.upper() for x in (cat.get("langs") or [])]
    order = []
    for L in FETCH_LANG_ORDER:
        if L in langs or not langs:
            order.append(L)
    for L in langs:
        if L not in order:
            order.append(L)
    if not order:
        order = ["ENG"]

    retrieved_at = utc_now()
    last_err = ""
    status = 0
    final_url = ""
    content = b""
    ctype = ""
    used_lang = "ENG"
    used_source = "cellar"

    got = False
    item_url = cat.get("item_url") or ""
    if item_url:
        try:
            status, final_url, content, ctype = client.fetch_url(item_url)
            if status == 200 and content and len(content) > 40:
                content, ctype2 = maybe_unzip(content, ctype)
                if ctype2:
                    ctype = ctype2
                used_source = "cellar_item"
                used_lang = "ENG"
                got = True
            else:
                last_err = f"item HTTP {status} {final_url}"
                content = b""
        except Exception as e:
            last_err = f"item {e}"
            content = b""
    if not got:
        try:
            status, final_url, content, ctype = client.fetch_celex(celex, "ENG")
            if status == 200 and content and len(content) > 40:
                used_source = "cellar"
                used_lang = "ENG"
                got = True
            else:
                last_err = last_err or f"cellar HTTP {status} ENG {final_url}"
                content = b""
        except Exception as e:
            last_err = last_err or f"cellar ENG: {e}"
            content = b""

    with stats.lock:
        stats.fetched += 1

    if not content or status != 200:
        append_jsonl(FAILURES_PATH, {
            "identifier": celex,
            "id": ident,
            "source_url": EURLEX_TXT.format(lang="EN", celex=quote(celex, safe="")),
            "status": "failed",
            "reason": last_err or f"http_{status}",
            "http_status": status,
            "retrieved_at": retrieved_at,
        }, _fail_lock)
        with stats.lock:
            stats.failed += 1
        return "failed"

    # decode
    try:
        src = content.decode("utf-8")
    except UnicodeDecodeError:
        src = content.decode("utf-8", errors="replace")

    title_guess, full_text, articles, extraction_status = extract_from_content(src, ctype)
    if (not full_text or not full_text.strip()) and used_source != "eurlex_html":
        try:
            lang1 = LANG3_TO_1.get(used_lang, "en")
            st2, url2, content2, ctype2 = client.fetch_eurlex_html(celex, lang1.upper())
            if st2 == 200 and content2 and len(content2) > 40:
                status, final_url, content, ctype = st2, url2, content2, ctype2
                used_source = "eurlex_html"
                try:
                    src = content.decode("utf-8")
                except UnicodeDecodeError:
                    src = content.decode("utf-8", errors="replace")
                title_guess, full_text, articles, extraction_status = extract_from_content(src, ctype)
        except Exception:
            pass
    if not full_text or not full_text.strip():
        append_jsonl(FAILURES_PATH, {
            "identifier": celex,
            "id": ident,
            "source_url": final_url,
            "status": "failed",
            "reason": "empty_text",
            "http_status": status,
            "content_type": ctype,
            "retrieved_at": retrieved_at,
        }, _fail_lock)
        with stats.lock:
            stats.failed += 1
            stats.empty_text += 1
        return "empty"

    sha = hashlib.sha256(content).hexdigest()
    source_url = EURLEX_TXT.format(lang=LANG3_TO_1.get(used_lang, "en").upper(), celex=quote(celex, safe=""))
    record = build_record(
        cat,
        text=full_text,
        articles=articles,
        extraction_status=extraction_status,
        title_guess=title_guess,
        source_url=source_url,
        content_url=final_url,
        content_type=f"{ctype}; via={used_source}",
        http_status=status,
        raw_sha=sha,
        fetched_lang3=used_lang,
        retrieved_at=retrieved_at,
    )

    if validator is not None:
        try:
            validator.validate(record)
        except Exception as e:
            append_jsonl(FAILURES_PATH, {
                "identifier": celex,
                "id": ident,
                "source_url": source_url,
                "status": "failed",
                "reason": f"schema: {e}",
                "retrieved_at": retrieved_at,
            }, _fail_lock)
            with stats.lock:
                stats.failed += 1
            return "schema"

    body = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    atomic_write(dest, body)
    nbytes = dest.stat().st_size
    index_line = {
        "id": ident,
        "path": f"instruments/{ident}.json",
        "title": record.get("title"),
        "identifier": celex,
        "celex": celex,
        "eli": record.get("eli"),
        "source_url": source_url,
        "source_type": "eurlex",
        "jurisdiction": "EU",
        "language": record.get("language"),
        "law_status": "current",
        "date": record.get("date"),
        "retrieved_at": retrieved_at,
        "article_count": record.get("article_count") or 0,
        "bytes": nbytes,
        "document_type": record.get("document_type"),
        "sector": sector_of(celex),
    }
    append_jsonl(INDEX_PATH, index_line, _index_lock)
    with stats.lock:
        stats.written += 1
        stats.bytes += nbytes
        stats.by_status[record["law_status"]] += 1
        stats.by_type[record.get("document_type") or "unknown"] += 1
        stats.by_sector[sector_of(celex)] += 1
    return "ok"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--refresh-catalog", action="store_true")
    p.add_argument("--sectors", default="3,1", help="CELEX sector prefixes, comma-separated")
    p.add_argument("--years", default="", help="optional YYYY,YYYY filter")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--interval", type=float, default=0.12, help="min seconds between HTTP starts")
    p.add_argument("--max", type=int, default=0, help="stop after N new writes (0=all)")
    p.add_argument("--timeout", type=int, default=90)
    p.add_argument("--validate-all", action="store_true")
    p.add_argument("--max-gb", type=float, default=18.0)
    p.add_argument("--summary-every", type=int, default=50)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    INSTRUMENTS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    log(f"START collect_eurlex workers={args.workers} interval={args.interval} sectors={args.sectors}")

    limiter = RateLimiter(args.interval)
    client = CellarClient(limiter, timeout=args.timeout)
    stats = Stats()

    validator = None
    if jsonschema is not None and SCHEMA_PATH.exists():
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        log("JSON Schema validator ready")

    sectors = [s.strip() for s in args.sectors.split(",") if s.strip()]
    years = [y.strip() for y in args.years.split(",") if y.strip()] or None

    catalog: list[dict[str, Any]] = []
    if CATALOG_PATH.exists() and not args.refresh_catalog:
        catalog = load_catalog()
        log(f"Loaded existing catalog {len(catalog)}")
        if not catalog:
            catalog = discover_catalog(client, sectors, years)
    else:
        catalog = discover_catalog(client, sectors, years)

    # keep requested sectors
    catalog = [c for c in catalog if c.get("sector") in sectors or sector_of(c["celex"]) in sectors]
    if years:
        catalog = [c for c in catalog if c.get("year") in years]
    catalog.sort(key=catalog_sort_key)
    stats.discovered = len(catalog)
    log(f"Catalog size in scope: {len(catalog)}")
    item_map = enrich_items(client, catalog)
    for rec in catalog:
        info = item_map.get(rec["celex"])
        if info:
            rec["item_url"] = info.get("item")
            rec["item_format"] = info.get("format")
    n_items = sum(1 for rec in catalog if rec.get("item_url"))
    log(f"Catalog rows with ENG item URL: {n_items}/{len(catalog)}")

    have = existing_instrument_ids()
    todo = []
    for cat in catalog:
        ident = celex_to_id(cat["celex"])
        if ident in have:
            stats.skipped_exists += 1
            stats.by_status["current"] += 1
            rec_type = classify(cat["celex"], cat.get("rtypes") or [])[1]
            stats.by_type[rec_type] += 1
            stats.by_sector[sector_of(cat["celex"])] += 1
            continue
        todo.append(cat)
    log(f"Already on disk: {len(have)}; todo: {len(todo)}")
    write_summary(stats, extra={"discovered": stats.discovered})

    if not todo:
        log("Nothing to fetch")
        write_summary(stats, extra={"discovered": stats.discovered})
        return 0

    if args.max:
        todo = todo[: args.max]

    stop = threading.Event()
    done_since_summary = 0
    summary_lock = threading.Lock()

    val_n = {"n": 0}
    val_lock = threading.Lock()

    def wrapped(cat: dict[str, Any]) -> str:
        if stop.is_set():
            return "stopped"
        try:
            with val_lock:
                val_n["n"] += 1
                vn = val_n["n"]
            use_v = validator if (validator is not None and (args.validate_all or vn <= 40 or vn % 250 == 0)) else None
            return process_one(client, cat, stats, use_v, args.max_gb)
        except Exception:
            log(f"EXC {cat.get('celex')}: {traceback.format_exc()}")
            append_jsonl(FAILURES_PATH, {
                "identifier": cat.get("celex"),
                "status": "failed",
                "reason": "exception",
                "retrieved_at": utc_now(),
            }, _fail_lock)
            with stats.lock:
                stats.failed += 1
            return "exc"

    workers = max(1, args.workers)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(wrapped, cat): cat["celex"] for cat in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            celex = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = f"exc:{e}"
            if i % 20 == 0 or res not in ("ok", "exists"):
                snap = stats.snapshot()
                log(f"progress {i}/{len(todo)} last={celex} res={res} written={snap['written']} failed={snap['failed']} bytes={snap['bytes']}")
            if stats.bytes > args.max_gb * 1e9:
                log("Hit max-gb cap; stopping")
                stop.set()
            if i % args.summary_every == 0:
                write_summary(stats, extra={"discovered": stats.discovered})
            if args.max and stats.written >= args.max:
                log("Hit --max writes")
                stop.set()

    write_summary(stats, extra={"discovered": stats.discovered})
    snap = stats.snapshot()
    log(f"DONE written={snap['written']} failed={snap['failed']} skipped={snap['skipped_exists']} fetched={snap['fetched']}")
    atomic_write(PROGRESS_PATH, json.dumps(snap, indent=2) + "\n")
    return 0 if snap["written"] or snap["skipped_exists"] else 1


if __name__ == "__main__":
    sys.exit(main())
