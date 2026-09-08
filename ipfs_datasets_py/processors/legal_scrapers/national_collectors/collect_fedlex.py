#!/usr/bin/env python3
"""Collect current Swiss federal classified compilation (SR) from Fedlex."""
from __future__ import annotations

import concurrent.futures
import hashlib
import html
import io
import json
import logging
import os
import random
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path("/workspace/legal-corpora/ch")
INSTR = ROOT / "instruments"
LOGS = ROOT / "logs"
TMP = ROOT / "tmp"
INDEX = ROOT / "index.jsonl"
SUMMARY = ROOT / "SUMMARY.md"
CATALOG = TMP / "catalog.json"
FAILED = LOGS / "failed.jsonl"

SPARQL_ENDPOINT = "https://fedlex.data.admin.ch/sparqlendpoint"
TODAY = "2026-09-02"
USER_AGENT = "legal-corpora-ch-collector/1.0 (research corpus; polite; contact via local operator)"
IN_FORCE = "https://fedlex.data.admin.ch/vocabulary/enforcement-status/0"
LANG_URI = {
    "de": "http://publications.europa.eu/resource/authority/language/DEU",
    "fr": "http://publications.europa.eu/resource/authority/language/FRA",
    "it": "http://publications.europa.eu/resource/authority/language/ITA",
    "rm": "http://publications.europa.eu/resource/authority/language/ROH",
    "en": "http://publications.europa.eu/resource/authority/language/ENG",
}
URI_LANG = {v: k for k, v in LANG_URI.items()}
FMT_RANK = {
    "https://fedlex.data.admin.ch/vocabulary/user-format/xml": 0,
    "https://fedlex.data.admin.ch/vocabulary/user-format/html": 1,
    "https://fedlex.data.admin.ch/vocabulary/user-format/pdf-a": 2,
    "https://fedlex.data.admin.ch/vocabulary/user-format/pdf": 3,
    "https://fedlex.data.admin.ch/vocabulary/user-format/pdf-x": 4,
    "https://fedlex.data.admin.ch/vocabulary/user-format/docx": 5,
    "https://fedlex.data.admin.ch/vocabulary/user-format/doc": 6,
}
FMT_NAME = {
    "https://fedlex.data.admin.ch/vocabulary/user-format/xml": "xml",
    "https://fedlex.data.admin.ch/vocabulary/user-format/html": "html",
    "https://fedlex.data.admin.ch/vocabulary/user-format/pdf-a": "pdf-a",
    "https://fedlex.data.admin.ch/vocabulary/user-format/pdf": "pdf",
    "https://fedlex.data.admin.ch/vocabulary/user-format/pdf-x": "pdf-x",
    "https://fedlex.data.admin.ch/vocabulary/user-format/docx": "docx",
    "https://fedlex.data.admin.ch/vocabulary/user-format/doc": "doc",
}
LICENSE = (
    "Official legislative texts are not protected by copyright (URG Art. 5; "
    "https://www.fedlex.admin.ch/eli/cc/1993/1798_1798_1798/de). "
    "Consultation and download for reuse are free (PublG Art. 19; PublV Art. 48). "
    "Reuse is subject to PublV Art. 49 (SR 170.512.1): do not alter the wording; "
    "visually distinguish the text from commentary; include the notice "
    "'Dies ist keine amtliche Veröffentlichung. Massgebend ist allein die "
    "Veröffentlichung durch die Bundeskanzlei.'; do not present the copy as an "
    "official publication; paid redistribution only in added-value form. "
    "See https://www.fedlex.admin.ch/de/legal-information and "
    "https://www.fedlex.admin.ch/de/broadcasters"
)
REUSE_NOTICE = (
    "Dies ist keine amtliche Veröffentlichung. Massgebend ist allein die "
    "Veröffentlichung durch die Bundeskanzlei."
)

WORKERS = 8
HTTP_TIMEOUT = 90
SPARQL_TIMEOUT = 180
MAX_BYTES = 80 * 1024 * 1024
RETRIES = 5

log = logging.getLogger("collector")
index_lock = threading.Lock()
fail_lock = threading.Lock()
stats_lock = threading.Lock()
STATS = {
    "listed": 0,
    "collected": 0,
    "failed": 0,
    "skipped_resume": 0,
    "bytes": 0,
    "empty_text": 0,
    "started_at": None,
    "by_format": {},
    "by_lang_primary": {},
}


def setup_logging() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    INSTR.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    fh = logging.FileHandler(LOGS / "collector.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def strip_markup(s: str | None) -> str | None:
    if not s:
        return s
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def safe_id(sr: str) -> str:
    sid = re.sub(r"[^0-9A-Za-z._-]+", "_", sr.strip())
    sid = sid.strip("._") or "unknown"
    if len(sid) > 180:
        sid = sid[:160] + "_" + hashlib.sha1(sr.encode()).hexdigest()[:10]
    return sid


def sparql(query: str, timeout: int = SPARQL_TIMEOUT) -> list[dict]:
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            data = urllib.parse.urlencode({"query": query}).encode("utf-8")
            req = urllib.request.Request(
                SPARQL_ENDPOINT,
                data=data,
                headers={
                    "Accept": "application/sparql-results+json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": USER_AGENT,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            rows = []
            for b in payload.get("results", {}).get("bindings", []):
                rows.append({k: v.get("value") for k, v in b.items()})
            return rows
        except Exception as e:
            last = e
            wait = min(60, 2 ** attempt) + random.random()
            log.warning("SPARQL attempt %s failed: %s; sleep %.1fs", attempt, e, wait)
            time.sleep(wait)
    raise RuntimeError(f"SPARQL failed after retries: {last}")


def http_get(url: str, timeout: int = HTTP_TIMEOUT) -> tuple[bytes, str, str]:
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "*/*",
                    "Accept-Encoding": "identity",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ctype = resp.headers.get("Content-Type") or ""
                final = resp.geturl()
                chunks = []
                total = 0
                while True:
                    buf = resp.read(256 * 1024)
                    if not buf:
                        break
                    total += len(buf)
                    if total > MAX_BYTES:
                        raise RuntimeError(f"response exceeds {MAX_BYTES} bytes")
                    chunks.append(buf)
                return b"".join(chunks), ctype, final
        except Exception as e:
            last = e
            wait = min(45, 1.5 ** attempt) + random.random()
            log.warning("GET %s attempt %s failed: %s; sleep %.1fs", url, attempt, e, wait)
            time.sleep(wait)
    raise RuntimeError(f"GET failed {url}: {last}")


class HTMLTextParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.seen_lawcontent = False
        self.in_law = False
        self.capture_all = False

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        ad = {k.lower(): (v or "") for k, v in attrs}
        if tag in self.SKIP:
            self.skip += 1
            return
        if ad.get("id") == "lawcontent":
            self.seen_lawcontent = True
            self.in_law = True
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "article",
                   "section", "br", "dt", "blockquote", "pre", "figcaption"}:
            self.parts.append("\n")
        elif tag in {"td", "th", "dd"}:
            self.parts.append("\t")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP and self.skip:
            self.skip -= 1
            return
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "article", "section"}:
            self.parts.append("\n")
        if tag == "div" and self.in_law:
            # keep capturing nested; parser is not stack-precise for lawcontent end
            pass

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self.seen_lawcontent and not self.in_law and not self.capture_all:
            return
        if data and data.strip():
            self.parts.append(data)
        elif data:
            self.parts.append(" ")


def html_to_text(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace")
    p = HTMLTextParser()
    try:
        p.feed(text)
        p.close()
    except Exception:
        pass
    if p.seen_lawcontent and not any(x.strip() for x in p.parts):
        p = HTMLTextParser()
        p.capture_all = True
        p.in_law = True
        p.feed(text)
    out = "".join(p.parts)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def localname(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    if tag.startswith("{") is False and ":" in tag:
        return tag.split(":", 1)[-1]
    return tag


SKIP_XML = {
    "meta", "identification", "publication", "lifecycle", "workflow",
    "analysis", "references", "classification", "proprietary",
}


def xml_to_text(raw: bytes) -> str:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        # try recovering by taking inner well-known start
        txt = raw.decode("utf-8", "replace")
        txt = re.sub(r"&(?!#|amp;|lt;|gt;|quot;|apos;)", "&amp;", txt)
        root = ET.fromstring(txt.encode("utf-8"))
    parts: list[str] = []

    def walk(el: ET.Element, skip_depth: int = 0) -> None:
        name = localname(el.tag).lower()
        if name in SKIP_XML:
            return
        if name in {"p", "paragraph", "article", "chapter", "section", "book", "title",
                    "subtitle", "formula", "preamble", "preface", "conclusion",
                    "alinea", "list", "point", "recital", "heading", "num", "content"}:
            parts.append("\n")
        if el.text and el.text.strip():
            parts.append(el.text)
        elif el.text and "\n" in el.text:
            parts.append("\n")
        for child in list(el):
            walk(child)
            if child.tail and child.tail.strip():
                parts.append(child.tail)
            elif child.tail and "\n" in child.tail:
                parts.append("\n")

    walk(root)
    out = " ".join(parts)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" *\n *", "\n", out)
    out = out.strip()
    if len(out) < 40:
        fallback = []
        for el in root.iter():
            if el.text and el.text.strip():
                fallback.append(el.text.strip())
            if el.tail and el.tail.strip():
                fallback.append(el.tail.strip())
        fb = "\n".join(fallback).strip()
        if len(fb) > len(out):
            out = fb
    return out


def pdf_to_text(raw: bytes, stem: str) -> str:
    pdf_path = TMP / f"{stem}.pdf"
    pdf_path.write_bytes(raw)
    try:
        r = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf_path), "-"],
            capture_output=True,
            timeout=120,
        )
        if r.returncode != 0:
            r = subprocess.run(
                ["pdftotext", "-enc", "UTF-8", str(pdf_path), "-"],
                capture_output=True,
                timeout=120,
            )
        text = r.stdout.decode("utf-8", "replace")
        return text.strip()
    finally:
        try:
            pdf_path.unlink(missing_ok=True)
        except Exception:
            pass


def docx_to_text(raw: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    parts: list[str] = []
    for el in root.iter():
        name = localname(el.tag)
        if name == "tab":
            parts.append("\t")
        elif name == "br":
            parts.append("\n")
        elif name == "p":
            parts.append("\n")
        if el.text:
            parts.append(el.text)
        if el.tail:
            parts.append(el.tail)
    out = "".join(parts)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def extract_text(fmt_name: str, raw: bytes, stem: str) -> str:
    if fmt_name == "xml":
        return xml_to_text(raw)
    if fmt_name == "html":
        return html_to_text(raw)
    if fmt_name in {"pdf", "pdf-a", "pdf-x"}:
        return pdf_to_text(raw, stem)
    if fmt_name == "docx":
        return docx_to_text(raw)
    if fmt_name == "doc":
        raise RuntimeError("doc binary skipped (no converter); use pdf/html/xml)")
    raise RuntimeError(f"unknown format {fmt_name}")


def load_done() -> set[str]:
    done: set[str] = set()
    if not INDEX.exists():
        return done
    with INDEX.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = rec.get("id")
            st = rec.get("status")
            if rid and st == "ok":
                done.add(rid)
            elif rid and st == "failed":
                done.discard(rid)  # retry failed
    return done


def append_index(rec: dict) -> None:
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with index_lock:
        with INDEX.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


def append_failed(rec: dict) -> None:
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with fail_lock:
        with FAILED.open("a", encoding="utf-8") as f:
            f.write(line)


def write_summary(extra: dict | None = None) -> None:
    extra = extra or {}
    with stats_lock:
        s = dict(STATS)
    collected_bytes = 0
    n_files = 0
    if INSTR.exists():
        for p in INSTR.glob("*.json"):
            n_files += 1
            try:
                collected_bytes += p.stat().st_size
            except OSError:
                pass
    listed = s.get("listed") or extra.get("listed") or 0
    body = f"""# Switzerland — Classified Compilation (SR / Classified Compilation)

**Retrieved:** {now_iso()} (UTC) / {datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")}
**Source:** Fedlex (Federal Chancellery / Swiss Confederation)
- Portal: https://www.fedlex.admin.ch/
- SPARQL/LINDAS: https://fedlex.data.admin.ch/sparqlendpoint
- ELI CC: https://www.fedlex.admin.ch/eli/cc
- Legal info: https://www.fedlex.admin.ch/de/legal-information

## Scope
Current **in-force** entries of the **Systematische Rechtssammlung (SR)** /
**Classified Compilation (CC)**, including domestic federal law and
international-law texts classified in the SR (chapter 0). Historical
Official Compilation (AS / OC) amending acts are **not** stored as separate
instruments; their effect is already consolidated in the current SR text.

In-force filter: `jolux:inForceStatus` =
`https://fedlex.data.admin.ch/vocabulary/enforcement-status/0` ("In force")
as of {TODAY}.

## Counts
- Listed (in-force SR instruments): **{listed}**
- Collected (JSON with non-empty primary text): **{s.get("collected", 0)}**
- Failed: **{s.get("failed", 0)}**
- Resumed/skipped already-ok: **{s.get("skipped_resume", 0)}**
- Empty-text: **{s.get("empty_text", 0)}**
- Instrument JSON files on disk: **{n_files}**
- Instrument JSON bytes: **{collected_bytes}** ({collected_bytes/1024/1024:.1f} MiB)

## Formats used (primary text)
{json.dumps(s.get("by_format") or {}, ensure_ascii=False, indent=2)}

## Primary language of stored record
{json.dumps(s.get("by_lang_primary") or {}, ensure_ascii=False, indent=2)}

## Record layout
- `instruments/{{safe_id}}.json` — one file per SR number
- `index.jsonl` — append-only collection log (resume key: `id` + `status=ok`)
- German is the primary `text` when available; French/Italian (and RM/EN if
  present) are listed in `metadata.languages` and stored under `documents`
  when XML/HTML could be fetched without extra PDF-only downloads.

## Copyright / reuse
{LICENSE}

Required reuse notice: {REUSE_NOTICE}

## Collector
- Script: `/workspace/legal-corpora/ch/collector.py`
- Log: `/workspace/legal-corpora/ch/logs/collector.log`
- Started (UTC): {s.get("started_at")}
- Workers: {WORKERS}
- No git clone; no git commit; streamed to disk.

## Blockers
{extra.get("blockers", "None at summary write.")}
"""
    SUMMARY.write_text(body, encoding="utf-8")




def fetch_catalog() -> list[dict]:
    if CATALOG.exists():
        try:
            data = json.loads(CATALOG.read_text(encoding="utf-8"))
            if isinstance(data, list) and len(data) >= 5000:
                with_files = sum(1 for a in data if a.get("files"))
                if with_files >= 5000:
                    log.info("Loaded cached catalog: %s acts (%s with files)", len(data), with_files)
                    return data
                log.info("Cached catalog incomplete (%s/%s with files); rebuilding", with_files, len(data))
        except Exception as e:
            log.warning("Catalog cache unreadable: %s", e)

    log.info("SPARQL: listing in-force ConsolidationAbstracts + titles")
    meta_q = f"""
PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT DISTINCT ?abstract ?sr ?lang ?title ?dateDocument ?dateEntryInForce ?historicalId
WHERE {{
  ?abstract a jolux:ConsolidationAbstract ;
            jolux:inForceStatus <{IN_FORCE}> ;
            jolux:classifiedByTaxonomyEntry ?tax .
  ?tax skos:notation ?sr .
  OPTIONAL {{ ?abstract jolux:dateDocument ?dateDocument }}
  OPTIONAL {{ ?abstract jolux:dateEntryInForce ?dateEntryInForce }}
  OPTIONAL {{ ?abstract jolux:historicalLegalId ?historicalId }}
  ?abstract jolux:isRealizedBy ?expr .
  ?expr jolux:language ?lang .
  OPTIONAL {{ ?expr jolux:title ?title }}
}}
"""
    meta_rows = sparql(meta_q, timeout=180)
    log.info("Title rows: %s", len(meta_rows))

    acts: dict[str, dict] = {}
    for row in meta_rows:
        uri = row.get("abstract")
        if not uri:
            continue
        rec = acts.setdefault(
            uri,
            {
                "abstract": uri,
                "sr": row.get("sr") or "",
                "historical_id": row.get("historicalId"),
                "date_document": row.get("dateDocument"),
                "date_entry_in_force": row.get("dateEntryInForce"),
                "titles": {},
                "languages": set(),
                "files": [],
                "cons": None,
                "cons_date": None,
            },
        )
        lang = URI_LANG.get(row.get("lang") or "", None)
        if lang:
            rec["languages"].add(lang)
            title = strip_markup(row.get("title"))
            if title:
                rec["titles"].setdefault(lang, title)
        if row.get("sr") and not rec["sr"]:
            rec["sr"] = row["sr"]

    log.info("Distinct in-force abstracts from titles: %s", len(acts))

    # One SPARQL per (language, format) to stay under Virtuoso result-size caps.
    fmt_list = [
        ("xml", "https://fedlex.data.admin.ch/vocabulary/user-format/xml"),
        ("html", "https://fedlex.data.admin.ch/vocabulary/user-format/html"),
        ("pdf-a", "https://fedlex.data.admin.ch/vocabulary/user-format/pdf-a"),
    ]
    lang_list = [("de", LANG_URI["de"]), ("fr", LANG_URI["fr"]), ("it", LANG_URI["it"])]
    url_rows: list[dict] = []
    for lang_code, lang_uri in lang_list:
        for fmt_name, fmt_uri in fmt_list:
            log.info("SPARQL: latest manifestations lang=%s fmt=%s", lang_code, fmt_name)
            url_q = f"""
PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?abstract ?cons ?date ?url
WHERE {{
  ?abstract a jolux:ConsolidationAbstract ;
            jolux:inForceStatus <{IN_FORCE}> .
  ?cons jolux:isMemberOf ?abstract ;
        jolux:dateApplicability ?date ;
        jolux:isRealizedBy ?expr .
  FILTER(?date <= xsd:date("{TODAY}"))
  FILTER NOT EXISTS {{
    ?c2 jolux:isMemberOf ?abstract ;
        jolux:dateApplicability ?d2 .
    FILTER(?d2 <= xsd:date("{TODAY}") && ?d2 > ?date)
    ?c2 jolux:isRealizedBy ?e2 .
    ?e2 jolux:isEmbodiedBy ?m2 .
    ?m2 jolux:isExemplifiedBy ?x .
  }}
  ?expr jolux:language <{lang_uri}> ;
        jolux:isEmbodiedBy ?manif .
  ?manif jolux:userFormat <{fmt_uri}> ;
         jolux:isExemplifiedBy ?url .
}}
"""
            rows = sparql(url_q, timeout=180)
            log.info("  %s/%s -> %s rows", lang_code, fmt_name, len(rows))
            for row in rows:
                row["lang"] = lang_uri
                row["fmt"] = fmt_uri
            url_rows.extend(rows)

    log.info("Total manifestation rows: %s", len(url_rows))
    seen_files = set()
    for row in url_rows:
        uri = row.get("abstract")
        if not uri:
            continue
        if uri not in acts:
            acts[uri] = {
                "abstract": uri,
                "sr": "",
                "historical_id": None,
                "date_document": None,
                "date_entry_in_force": None,
                "titles": {},
                "languages": set(),
                "files": [],
                "cons": None,
                "cons_date": None,
            }
        rec = acts[uri]
        rec["cons"] = row.get("cons")
        rec["cons_date"] = row.get("date")
        lang = URI_LANG.get(row.get("lang") or "", None)
        fmt = row.get("fmt")
        url = row.get("url")
        if not (lang and fmt and url):
            continue
        key = (uri, lang, fmt, url)
        if key in seen_files:
            continue
        seen_files.add(key)
        rec["languages"].add(lang)
        rec["files"].append({"lang": lang, "fmt": fmt, "url": url, "rank": FMT_RANK.get(fmt, 99)})

    catalog = []
    n_with = 0
    for rec in acts.values():
        rec["languages"] = sorted(rec["languages"])
        rec["files"].sort(key=lambda x: (x["lang"], x["rank"], x["url"]))
        if rec["files"]:
            n_with += 1
        catalog.append(rec)
    catalog.sort(key=lambda r: tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", r["sr"] or "")))
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    log.info("Wrote catalog %s (%s acts, %s with files)", CATALOG, len(catalog), n_with)
    return catalog


def pick_files(files: list[dict], lang: str, allow_pdf: bool) -> tuple[str | None, list[str]]:
    ranked: dict[int, list[str]] = {}
    for f in files:
        if f["lang"] != lang:
            continue
        rank = f.get("rank", 99)
        if rank > 6:
            continue
        name = FMT_NAME.get(f["fmt"])
        if name is None:
            continue
        if not allow_pdf and name in {"pdf", "pdf-a", "pdf-x", "doc"}:
            continue
        ranked.setdefault(rank, []).append(f["url"])
    if not ranked:
        return None, []
    best = min(ranked)
    fmt_uri = None
    for uri, r in FMT_RANK.items():
        if r == best:
            fmt_uri = uri
            break
    return FMT_NAME.get(fmt_uri or "", None), sorted(set(ranked[best]))


def sniff_format(claimed: str, raw: bytes, ctype: str) -> str:
    head = raw[:8]
    cl = (ctype or "").lower()
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK"):
        return "docx"
    if head.lstrip().startswith(b"<?xml") or head.lstrip().startswith(b"<akn") or head.lstrip().startswith(b"<AKN"):
        return "xml"
    if b"<html" in raw[:4000].lower() or "html" in cl:
        if claimed in {"html", "xml"}:
            return "html" if claimed == "html" or b"<html" in raw[:4000].lower() else claimed
    if "pdf" in cl:
        return "pdf"
    return claimed


def formats_for_lang(files: list[dict], lang: str, allow_pdf: bool) -> list[tuple[str, list[str]]]:
    """Return (fmt_name, urls) groups in rank order so empty XML can fall through to PDF."""
    grouped: dict[int, list[str]] = {}
    rank_name: dict[int, str] = {}
    for f in files:
        if f["lang"] != lang:
            continue
        rank = f.get("rank", 99)
        name = FMT_NAME.get(f["fmt"])
        if name is None:
            continue
        if not allow_pdf and name in {"pdf", "pdf-a", "pdf-x", "doc"}:
            continue
        rank_name[rank] = name
        grouped.setdefault(rank, [])
        if f["url"] not in grouped[rank]:
            grouped[rank].append(f["url"])
    out = []
    for rank in sorted(grouped):
        out.append((rank_name[rank], grouped[rank]))
    return out


def fetch_lang_text(act: dict, lang: str, allow_pdf: bool) -> dict | None:
    sid = safe_id(act["sr"])
    groups = formats_for_lang(act.get("files") or [], lang, allow_pdf=allow_pdf)
    if not groups:
        return None
    last_err = None
    for fmt, urls in groups:
        texts = []
        used = []
        used_fmt = fmt
        for i, url in enumerate(urls):
            try:
                raw, ctype, final = http_get(url)
            except Exception as e:
                last_err = e
                log.warning("GET %s %s %s failed: %s", act["sr"], lang, url, e)
                continue
            actual = sniff_format(fmt, raw, ctype)
            stem = f"{sid}_{lang}_{actual}_{i}"
            try:
                t = extract_text(actual, raw, stem)
            except Exception as e:
                last_err = e
                log.warning("extract %s %s %s failed: %s", act["sr"], lang, actual, e)
                continue
            if t and t.strip():
                texts.append(t.strip())
                used.append(final or url)
                used_fmt = actual
        if texts:
            title = act.get("titles", {}).get(lang) or act.get("titles", {}).get("de") or f"SR {act['sr']}"
            return {
                "id": f"{act['sr']}-{lang}",
                "title": title,
                "text": "\n\n".join(texts),
                "source_url": used[0],
                "metadata": {
                    "language": lang,
                    "format": used_fmt,
                    "source_urls": used,
                    "consolidation": act.get("cons"),
                    "consolidation_date": act.get("cons_date"),
                    "parts": len(used),
                },
            }
        log.info("empty extract %s lang=%s fmt=%s; trying next format", act["sr"], lang, fmt)
    if last_err:
        log.warning("all formats empty for %s lang=%s last_err=%s", act["sr"], lang, last_err)
    return None


def build_record(act: dict) -> dict:
    langs_avail = act.get("languages") or []
    documents = []
    # German first; empty XML/HTML falls through to PDF inside fetch_lang_text
    de_doc = fetch_lang_text(act, "de", allow_pdf=True)
    if de_doc:
        documents.append(de_doc)
    # Other langs: XML/HTML first, then PDF if those are empty
    for lang in ("fr", "it", "rm", "en"):
        if lang not in langs_avail:
            continue
        allow_pdf = True
        try:
            doc = fetch_lang_text(act, lang, allow_pdf=allow_pdf)
        except Exception as e:
            log.warning("lang %s for %s failed: %s", lang, act["sr"], e)
            doc = None
        if doc:
            documents.append(doc)

    primary = None
    primary_lang = None
    for lang in ("de", "fr", "it", "rm", "en"):
        for d in documents:
            if d["metadata"]["language"] == lang:
                primary = d
                primary_lang = lang
                break
        if primary:
            break

    if not primary or not (primary.get("text") or "").strip():
        raise RuntimeError("no extractable text in de/fr/it")

    eli_data = act["abstract"]
    eli_www = eli_data.replace("https://fedlex.data.admin.ch/", "https://www.fedlex.admin.ch/")
    title = (
        act.get("titles", {}).get("de")
        or act.get("titles", {}).get(primary_lang)
        or f"SR {act['sr']}"
    )
    date_issued = None
    dd = act.get("date_document")
    if dd:
        date_issued = str(dd)[:10]

    rec = {
        "schema_version": "collection_record.v1",
        "record_type": "law",
        "id": act["sr"],
        "title": title,
        "jurisdiction": "CH",
        "country": "Switzerland",
        "language": primary_lang,
        "source_type": "fedlex",
        "source_url": eli_www,
        "eli": eli_data,
        "date": date_issued,
        "date_issued": date_issued,
        "retrieved_at": now_iso(),
        "identifier": act["sr"],
        "official_identifier": act["sr"],
        "law_identifier": act["sr"],
        "law_status": "current",
        "is_current": True,
        "license": "unknown",
        "text": primary["text"],
        "documents": documents,
        "metadata": {
            "license": LICENSE,
            "retrieved_at": now_iso(),
            "official_id": act["sr"],
            "publisher": "Fedlex / Swiss Confederation",
            "source_name": "fedlex.admin.ch",
            "languages": langs_avail,
            "historical_legal_id": act.get("historical_id"),
            "date_entry_in_force": (str(act["date_entry_in_force"])[:10] if act.get("date_entry_in_force") else None),
            "consolidation_date": act.get("cons_date"),
            "consolidation_eli": act.get("cons"),
            "reuse_notice": REUSE_NOTICE,
            "copyright_basis": "URG Art. 5; PublV Art. 48–49",
            "in_force_status": IN_FORCE,
            "primary_format": primary["metadata"].get("format"),
        },
    }
    return rec


def process_act(act: dict) -> tuple[str, str, int, str | None]:
    sr = act.get("sr") or "unknown"
    sid = safe_id(sr)
    path = INSTR / f"{sid}.json"
    rec = build_record(act)
    tmp = path.with_suffix(".json.tmp")
    data = json.dumps(rec, ensure_ascii=False, indent=2).encode("utf-8")
    tmp.write_bytes(data)
    tmp.replace(path)
    fmt = rec["metadata"].get("primary_format") or "?"
    lang = rec.get("language") or "?"
    return sid, fmt, len(data), lang


def main() -> int:
    setup_logging()
    STATS["started_at"] = now_iso()
    log.info("START collector Swiss SR/CC")
    catalog = fetch_catalog()
    STATS["listed"] = len(catalog)
    done = load_done()
    log.info("Catalog %s acts; already ok in index: %s", len(catalog), len(done))
    pending = [a for a in catalog if a.get("sr") and safe_id(a["sr"]) not in done and a["sr"] not in done]
    # resume uses safe_id and raw sr
    pending = []
    for a in catalog:
        sr = a.get("sr") or ""
        sid = safe_id(sr)
        if sid in done or sr in done:
            STATS["skipped_resume"] += 1
            continue
        pending.append(a)
    log.info("Pending: %s", len(pending))
    write_summary()

    def worker(act: dict) -> None:
        sr = act.get("sr") or "unknown"
        sid = safe_id(sr)
        try:
            time.sleep(random.uniform(0.0, 0.15))
            sid, fmt, nbytes, lang = process_act(act)
            append_index({
                "id": sr,
                "safe_id": sid,
                "file": f"instruments/{sid}.json",
                "status": "ok",
                "bytes": nbytes,
                "format": fmt,
                "language": lang,
                "retrieved_at": now_iso(),
            })
            with stats_lock:
                STATS["collected"] += 1
                STATS["bytes"] += nbytes
                STATS["by_format"][fmt] = STATS["by_format"].get(fmt, 0) + 1
                STATS["by_lang_primary"][lang] = STATS["by_lang_primary"].get(lang, 0) + 1
            n = STATS["collected"] + STATS["failed"]
            if n % 25 == 0:
                log.info("progress collected=%s failed=%s last=%s %s bytes=%s",
                         STATS["collected"], STATS["failed"], sr, fmt, nbytes)
            if n % 100 == 0:
                write_summary()
        except Exception as e:
            log.error("FAIL %s: %s", sr, e)
            append_index({
                "id": sr,
                "safe_id": sid,
                "status": "failed",
                "error": str(e)[:500],
                "retrieved_at": now_iso(),
            })
            append_failed({"id": sr, "error": str(e)[:1000], "trace": traceback.format_exc()[-2000:]})
            with stats_lock:
                STATS["failed"] += 1
                if "no extractable text" in str(e):
                    STATS["empty_text"] += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(worker, a) for a in pending]
        concurrent.futures.wait(futs)

    write_summary({"listed": len(catalog), "blockers": "See logs/failed.jsonl for per-act errors."})
    log.info("DONE listed=%s collected=%s failed=%s bytes=%s",
             STATS["listed"], STATS["collected"], STATS["failed"], STATS["bytes"])
    return 0 if STATS["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
