#!/usr/bin/env python3
"""Shared helpers for national legislation collectors."""
from __future__ import annotations

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

ROOT = Path(
    os.environ.get(
        "LEGAL_CORPORA_ROOT",
        str(Path.home() / ".ipfs_datasets" / "legal-corpora"),
    )
)
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


def get_session(ua: str = DEFAULT_UA, pool: int = 8) -> requests.Session:
    s = getattr(_tls, "session", None)
    if s is None or getattr(_tls, "ua", None) != ua:
        s = requests.Session()
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
    return s


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


def write_instrument(cc: str, record: dict) -> Path:
    ident = record["id"]
    dest = ROOT / cc / "instruments" / f"{ident}.json"
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
