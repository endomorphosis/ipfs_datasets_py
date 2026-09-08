#!/usr/bin/env python3
"""Collect current German federal law (Bundesrecht) from gesetze-im-internet.de.

Writes:
  instruments/{safe_id}.json
  index.jsonl
  SUMMARY.md
  logs/collector.log
  logs/failures.jsonl
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path("/workspace/legal-corpora/de")
INSTRUMENTS = ROOT / "instruments"
LOGS = ROOT / "logs"
INDEX_PATH = ROOT / "index.jsonl"
SUMMARY_PATH = ROOT / "SUMMARY.md"
FAILURES_PATH = LOGS / "failures.jsonl"
TOC_CACHE = LOGS / "gii-toc.xml"
TOC_URL = "https://www.gesetze-im-internet.de/gii-toc.xml"
CACHE = ROOT / "cache"

LICENSE = (
    "Public domain (gemeinfrei): amtliche Werke i.S.d. § 5 Abs. 1 UrhG; "
    "Bundesministerium der Justiz / gesetze-im-internet.de"
)
PUBLISHER = "Bundesministerium der Justiz"
SOURCE_NAME = "gesetze-im-internet.de"
UA = "legal-corpora-collector/1.0 (research corpus; German Bundesrecht; polite; +https://www.gesetze-im-internet.de/)"
WORKERS = 6
PARSE_WORKERS = max(1, (os.cpu_count() or 8))
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 60
MAX_ZIP_BYTES = 80 * 1024 * 1024  # skip pathological zips
MAX_XML_BYTES = 60 * 1024 * 1024
BINARY_TAGS = {
    "img", "graphic", "object", "binary", "Image", "IMG", "Bild",
    "symbol", "Symbol",
}
BREAK_AFTER = {
    "P", "BR", "LA", "DT", "DD", "Title", "Ident", "pre", "TOC", "Content",
    "Footnote", "fussnoten",
}
SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
PT = timezone(timedelta(hours=-7))

log = logging.getLogger("collector")
_index_lock = threading.Lock()
_fail_lock = threading.Lock()
_tls = threading.local()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_pt(dt: datetime) -> str:
    return dt.astimezone(PT).strftime("%Y-%m-%d %H:%M:%S PT")


def local_tag(tag: Optional[str]) -> str:
    if not tag:
        return ""
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def looks_binary(text: str) -> bool:
    if len(text) < 4000:
        return False
    sample = text[:8000].replace("\n", "").replace("\r", "").replace(" ", "")
    if len(sample) < 2000:
        return False
    # base64-ish
    b64 = sum(1 for c in sample if c.isalnum() or c in "+/=") / max(len(sample), 1)
    if b64 > 0.95 and len(sample) > 4000:
        return True
    nul = sample.count("\x00")
    if nul > 10:
        return True
    return False


def extract_text(elem: Optional[ET.Element]) -> str:
    if elem is None:
        return ""
    parts: list[str] = []

    def rec(e: ET.Element) -> None:
        tag = local_tag(e.tag)
        if tag in BINARY_TAGS:
            return
        # skip attributes that are typically binary payloads
        if e.text:
            if looks_binary(e.text):
                parts.append("[binary attachment omitted]")
            else:
                parts.append(e.text)
        for child in e:
            rec(child)
            if child.tail:
                if looks_binary(child.tail):
                    continue
                parts.append(child.tail)
        if tag in BREAK_AFTER:
            parts.append("\n")

    rec(elem)
    text = "".join(parts)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    blank = False
    for ln in lines:
        if not ln:
            if not blank:
                out.append("")
            blank = True
        else:
            out.append(ln)
            blank = False
    return "\n".join(out).strip()


def child_text(parent: Optional[ET.Element], name: str) -> Optional[str]:
    if parent is None:
        return None
    el = parent.find(name)
    if el is None:
        return None
    t = "".join(el.itertext()).strip()
    return t or None


def safe_id(slug: str) -> str:
    """Filesystem-safe id. Keep leading underscores (GII slugs like _ag)."""
    s = (slug or "").strip()
    s = SAFE_RE.sub("_", s)
    if not s or s in {".", ".."}:
        s = "unnamed"
    return s[:180]


def slug_from_link(link: str) -> str:
    p = urlparse(link)
    parts = [x for x in p.path.split("/") if x]
    if parts and parts[-1].lower() in {"xml.zip", "xml"}:
        parts = parts[:-1]
    if not parts:
        raise ValueError(f"cannot parse slug from {link}")
    return parts[-1]


def https_url(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


def get_session() -> requests.Session:
    sess = getattr(_tls, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update({"User-Agent": UA, "Accept": "*/*"})
        retry = Retry(
            total=0,  # we handle retries ourselves for logging
            connect=0,
            read=0,
            redirect=3,
            backoff_factor=0,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        sess.mount("https://", adapter)
        sess.mount("http://", adapter)
        _tls.session = sess
    return sess


def http_get(url: str, retries: int = 6) -> requests.Response:
    sess = get_session()
    last_err: Optional[Exception] = None
    delay = 1.0
    for attempt in range(1, retries + 1):
        try:
            resp = sess.get(url, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), stream=True)
            if resp.status_code in (429, 500, 502, 503, 504) or resp.status_code >= 500:
                body_len = 0
                try:
                    resp.close()
                except Exception:
                    pass
                log.warning("HTTP %s for %s attempt %s/%s; sleep %.1fs",
                            resp.status_code, url, attempt, retries, delay)
                time.sleep(delay)
                delay = min(delay * 2, 32)
                continue
            if resp.status_code == 404:
                return resp
            resp.raise_for_status()
            return resp
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
            log.warning("net error %s for %s attempt %s/%s; sleep %.1fs",
                        type(e).__name__, url, attempt, retries, delay)
            time.sleep(delay)
            delay = min(delay * 2, 32)
        except requests.HTTPError as e:
            last_err = e
            code = getattr(e.response, "status_code", None)
            if code and code < 500 and code != 429:
                raise
            log.warning("HTTPError %s for %s attempt %s/%s", e, url, attempt, retries)
            time.sleep(delay)
            delay = min(delay * 2, 32)
    if last_err:
        raise last_err
    raise RuntimeError(f"failed to GET {url}")


def download_bytes(url: str) -> tuple[bytes, int]:
    resp = http_get(url)
    if resp.status_code == 404:
        raise FileNotFoundError(f"404 {url}")
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_ZIP_BYTES:
            resp.close()
            raise ValueError(f"download too large ({total} bytes): {url}")
        chunks.append(chunk)
    return b"".join(chunks), resp.status_code


def xml_from_payload(payload: bytes, url: str) -> ET.Element:
    # zip?
    if payload[:2] == b"PK":
        with zipfile.ZipFile(BytesIO(payload)) as zf:
            xml_names = [
                n for n in zf.namelist()
                if n.lower().endswith(".xml") and not n.endswith("/")
            ]
            if not xml_names:
                raise ValueError(f"no XML in zip {url}: {zf.namelist()[:20]}")
            # prefer the largest xml (main document)
            xml_names.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
            info = zf.getinfo(xml_names[0])
            if info.file_size > MAX_XML_BYTES:
                raise ValueError(f"XML too large {info.file_size} in {url}")
            raw = zf.read(xml_names[0])
    else:
        raw = payload
        if len(raw) > MAX_XML_BYTES:
            raise ValueError(f"XML too large {len(raw)} from {url}")
    # strip BOM
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        # some files may be latin-1 mislabeled
        text = raw.decode("utf-8", errors="replace")
        return ET.fromstring(text.encode("utf-8"))


def parse_toc(path: Path) -> list[dict[str, str]]:
    tree = ET.parse(path)
    items = []
    seen = set()
    for it in tree.getroot().findall("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not link:
            continue
        link = https_url(link)
        slug = slug_from_link(link)
        if slug in seen:
            continue
        seen.add(slug)
        items.append({"slug": slug, "title": title, "xml_url": link})
    return items


def load_done_ids() -> set[str]:
    done: set[str] = set()
    if not INDEX_PATH.exists():
        return done
    with INDEX_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            iid = rec.get("id")
            if iid:
                done.add(iid)
    return done


def append_index(row: dict[str, Any]) -> None:
    line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
    with _index_lock:
        with INDEX_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())


def append_failure(row: dict[str, Any]) -> None:
    line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
    with _fail_lock:
        with FAILURES_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()


def build_record(slug: str, toc_title: str, xml_url: str, root: ET.Element, retrieved_at: str) -> dict[str, Any]:
    page_url = f"https://www.gesetze-im-internet.de/{slug}/"
    eli = f"https://www.gesetze-im-internet.de/eli/{slug}"
    official_id = root.get("doknr")
    builddate = root.get("builddate")

    norms = list(root.findall("norm"))
    header_md = norms[0].find("metadaten") if norms else None
    jurabk = child_text(header_md, "jurabk")
    amtabk = child_text(header_md, "amtabk")
    langue = child_text(header_md, "langue")
    date_issued = child_text(header_md, "ausfertigung-datum")
    title = langue or toc_title or jurabk or slug
    title = re.sub(r"\s+", " ", title).strip()

    fundstelle = None
    if header_md is not None:
        fs = header_md.find("fundstelle")
        if fs is not None:
            fundstelle = {
                "typ": fs.get("typ"),
                "periodikum": child_text(fs, "periodikum"),
                "zitstelle": child_text(fs, "zitstelle"),
            }

    stand = []
    if header_md is not None:
        for sa in header_md.findall("standangabe"):
            stand.append({
                "typ": child_text(sa, "standtyp"),
                "kommentar": child_text(sa, "standkommentar"),
            })

    documents: list[dict[str, Any]] = []
    text_parts: list[str] = []

    for i, norm in enumerate(norms):
        md = norm.find("metadaten")
        td = norm.find("textdaten")
        enbez = child_text(md, "enbez")
        titel = child_text(md, "titel")
        gl = md.find("gliederungseinheit") if md is not None else None
        gl_bez = child_text(gl, "gliederungsbez") if gl is not None else None
        gl_titel = child_text(gl, "gliederungstitel") if gl is not None else None
        doknr = norm.get("doknr")

        if i == 0 and not enbez and gl is None:
            doc_title = title
            doc_id = f"{slug}:header"
        elif gl is not None:
            doc_title = " ".join(x for x in (gl_bez, gl_titel) if x) or f"gliederung-{i}"
            doc_id = f"{slug}:gl:{gl_bez or i}"
        else:
            doc_title = " ".join(x for x in (enbez, titel) if x) or f"norm-{i}"
            doc_id = f"{slug}:{enbez or i}"

        body = ""
        if td is not None:
            text_el = td.find("text")
            body = extract_text(text_el if text_el is not None else td)
            fn = td.find("fussnoten")
            fn_text = extract_text(fn) if fn is not None else ""
            if fn_text:
                body = (body + "\n\n" + fn_text).strip() if body else fn_text

        documents.append({
            "id": doc_id,
            "title": doc_title,
            "text": body,
            "source_url": page_url,
            "metadata": {
                "doknr": doknr,
                "enbez": enbez,
                "titel": titel,
                "gliederungsbez": gl_bez,
                "gliederungstitel": gl_titel,
            },
        })
        header_line = doc_title.strip()
        if header_line and body:
            text_parts.append(header_line + "\n" + body)
        elif header_line:
            text_parts.append(header_line)
        elif body:
            text_parts.append(body)

    full_text = "\n\n".join(p for p in text_parts if p).strip()

    rec_id = slug  # unique, stable, matches URL; abbreviation kept in metadata
    date = date_issued if date_issued and re.match(r"^\d{4}-\d{2}-\d{2}$", date_issued) else None
    stand_blob = " ".join((x.get("kommentar") or "") for x in stand).lower()
    if "außer kraft" in stand_blob or "ausser kraft" in stand_blob:
        law_status = "repealed"
        is_current = False
    else:
        law_status = "current"
        is_current = True
    record = {
        "schema_version": "collection_record.v1",
        "record_type": "law",
        "id": rec_id,
        "title": title,
        "jurisdiction": "DE",
        "country": "Germany",
        "language": "de",
        "source_type": "gesetze_im_internet",
        "source_url": page_url,
        "eli": None,
        "date": date,
        "date_issued": date_issued,
        "license": LICENSE,
        "retrieved_at": retrieved_at,
        "identifier": official_id or jurabk or slug,
        "official_identifier": jurabk or official_id or slug,
        "law_identifier": jurabk or slug,
        "document_type": "statute",
        "law_status": law_status,
        "is_current": is_current,
        "article_count": len(documents),
        "article_extraction_status": "ok" if documents else "missing",
        "canonical_law_url": page_url,
        "text": full_text,
        "documents": documents,
        "metadata": {
            "license": LICENSE,
            "retrieved_at": retrieved_at,
            "official_id": official_id,
            "publisher": PUBLISHER,
            "source_name": SOURCE_NAME,
            "abbreviation": jurabk,
            "amtliche_abkuerzung": amtabk,
            "slug": slug,
            "xml_url": xml_url,
            "builddate": builddate,
            "fundstelle": fundstelle,
            "standangabe": stand,
            "toc_title": toc_title,
            "n_norms": len(norms),
            "schema": "collection_record.v1",
            "collector": "collect_gii",
            "parser": "gii-xml-norm",
            "rights": {
                "not_legal_advice": True,
                "official_reuse_url": "https://www.gesetze-im-internet.de/",
                "license": LICENSE,
            },
        },
    }
    return record


def write_record(record: dict[str, Any], sid: str) -> tuple[int, dict[str, Any]]:
    out_path = INSTRUMENTS / f"{sid}.json"
    tmp_path = INSTRUMENTS / f".{sid}.json.tmp"
    data = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    encoded = data.encode("utf-8")
    with tmp_path.open("wb") as f:
        f.write(encoded)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, out_path)
    row = {
        "id": record["id"],
        "path": f"instruments/{sid}.json",
        "title": record["title"],
        "identifier": record.get("identifier"),
        "eli": record.get("eli"),
        "source_url": record["source_url"],
        "source_type": record["source_type"],
        "jurisdiction": record["jurisdiction"],
        "language": record["language"],
        "law_status": record.get("law_status"),
        "date": record.get("date"),
        "retrieved_at": record.get("retrieved_at"),
        "article_count": record.get("article_count") or len(record.get("documents") or []),
        "bytes": len(encoded),
        "byte_size": len(encoded),
    }
    return len(encoded), row


def process_item(item: dict[str, str]) -> dict[str, Any]:
    slug = item["slug"]
    sid = safe_id(slug)
    xml_url = item["xml_url"]
    cache_zip = CACHE / f"{slug}.zip"
    part = CACHE / f"{slug}.zip.part"
    if part.exists():
        raise RuntimeError(f"in-progress download {part.name}")
    if cache_zip.exists() and cache_zip.stat().st_size > 32:
        payload = cache_zip.read_bytes()
        status = 200
        retrieved_at = iso_z(datetime.fromtimestamp(cache_zip.stat().st_mtime, timezone.utc))
    else:
        payload, status = download_bytes(xml_url)
        retrieved_at = iso_z(now_utc())
        try:
            CACHE.mkdir(parents=True, exist_ok=True)
            tmp = cache_zip.with_suffix(".zip.tmp")
            tmp.write_bytes(payload)
            tmp.replace(cache_zip)
        except Exception:
            pass
    root = xml_from_payload(payload, xml_url)
    record = build_record(slug, item.get("title") or "", xml_url, root, retrieved_at)
    nbytes, row = write_record(record, sid)
    append_index(row)
    return {
        "ok": True,
        "id": slug,
        "bytes": nbytes,
        "status": status,
        "n_docs": len(record["documents"]),
        "row": row,
    }


def process_cache_item(item: dict[str, str]) -> dict[str, Any]:
    """Parse a finished cache zip. No network. Safe for ProcessPoolExecutor."""
    slug = item["slug"]
    sid = safe_id(slug)
    xml_url = item.get("xml_url") or f"https://www.gesetze-im-internet.de/{slug}/xml.zip"
    cache_zip = CACHE / f"{slug}.zip"
    part = Path(str(cache_zip) + ".part")
    try:
        if part.exists():
            return {"ok": False, "id": slug, "error": "in_progress", "transient": True}
        if not cache_zip.exists() or cache_zip.stat().st_size <= 32:
            return {"ok": False, "id": slug, "error": "missing_zip", "transient": True}
        payload = cache_zip.read_bytes()
        if not payload.startswith(b"PK"):
            return {"ok": False, "id": slug, "error": "not_a_zip"}
        retrieved_at = iso_z(datetime.fromtimestamp(cache_zip.stat().st_mtime, timezone.utc))
        root = xml_from_payload(payload, xml_url)
        record = build_record(slug, item.get("title") or "", xml_url, root, retrieved_at)
        nbytes, row = write_record(record, sid)
        return {
            "ok": True,
            "id": slug,
            "bytes": nbytes,
            "n_docs": len(record["documents"]),
            "row": row,
            "law_status": record.get("law_status"),
        }
    except Exception as e:
        return {"ok": False, "id": slug, "error": f"{type(e).__name__}: {e}"}


def process_safe(item: dict[str, str]) -> dict[str, Any]:
    slug = item["slug"]
    try:
        return process_item(item)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        log.error("FAIL %s %s", slug, err)
        append_failure({
            "id": slug,
            "title": item.get("title"),
            "xml_url": item.get("xml_url"),
            "error": err,
            "ts": iso_z(now_utc()),
        })
        return {"ok": False, "id": slug, "error": err}


def write_summary(
    toc_count: int,
    ok_count: int,
    fail_count: int,
    skip_count: int,
    total_bytes: int,
    start: datetime,
    end: datetime,
    failed_ids: list[str],
    notes: str = "",
) -> None:
    elapsed = (end - start).total_seconds()
    lines = [
        "# German federal law corpus (Bundesrecht)",
        "",
        "## Source",
        "",
        f"- Site: https://www.gesetze-im-internet.de/",
        f"- TOC: {TOC_URL}",
        f"- Per-instrument XML zip: https://www.gesetze-im-internet.de/{{slug}}/xml.zip",
        f"- Publisher: {PUBLISHER}",
        f"- Source name: {SOURCE_NAME}",
        "",
        "## License",
        "",
        LICENSE,
        "",
        "Official federal statutes and regulations published on Gesetze im Internet are",
        "amtliche Werke under § 5 Abs. 1 UrhG and are not protected by copyright.",
        "",
        "## Timing",
        "",
        f"- Start (UTC): {iso_z(start)}",
        f"- Start (PT):  {iso_pt(start)}",
        f"- End (UTC):   {iso_z(end)}",
        f"- End (PT):    {iso_pt(end)}",
        f"- Elapsed:     {elapsed:.1f} s ({elapsed/60:.1f} min)",
        "",
        "## Counts",
        "",
        f"- TOC items:              {toc_count}",
        f"- Instruments written:    {ok_count}",
        f"- Skipped (already in index): {skip_count}",
        f"- Failures:               {fail_count}",
        f"- index.jsonl lines:      {ok_count}",
        f"- Total JSON bytes:       {total_bytes} ({total_bytes/1_000_000:.2f} MB)",
        "",
        "## Layout",
        "",
        "- `instruments/{safe_id}.json` — one file per statute/regulation/treaty",
        "- `index.jsonl` — one line per instrument",
        "- `logs/collector.log`",
        "- `logs/failures.jsonl`",
        "- `logs/gii-toc.xml` — TOC snapshot used for this run",
        "",
        "## Failures",
        "",
    ]
    if not failed_ids:
        lines.append("None.")
    else:
        lines.append(f"{len(failed_ids)} failed ids:")
        lines.append("")
        for fid in failed_ids:
            lines.append(f"- `{fid}`")
    if notes:
        lines.extend(["", "## Notes", "", notes])
    lines.append("")
    SUMMARY_PATH.write_text("\n".join(lines), encoding="utf-8")


def setup_logging() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    INSTRUMENTS.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(LOGS / "collector.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.handlers.clear()
    log.addHandler(fh)
    log.addHandler(sh)


def fetch_toc() -> list[dict[str, str]]:
    log.info("Downloading TOC %s", TOC_URL)
    payload, status = download_bytes(TOC_URL)
    log.info("TOC HTTP %s bytes=%s", status, len(payload))
    TOC_CACHE.write_bytes(payload)
    items = parse_toc(TOC_CACHE)
    log.info("TOC parsed: %s unique items", len(items))
    return items


def load_toc_items() -> list[dict[str, str]]:
    """Use on-disk catalog; do not re-download the zip corpus."""
    urls_tsv = LOGS / "urls.tsv"
    if TOC_CACHE.exists() and TOC_CACHE.stat().st_size > 100:
        try:
            items = parse_toc(TOC_CACHE)
            if items:
                log.info("TOC from cache file: %s items", len(items))
                return items
        except Exception as e:
            log.warning("TOC cache parse failed: %s", e)
    if urls_tsv.exists():
        items = []
        seen = set()
        with urls_tsv.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                parts = line.split("\t")
                slug = parts[0].strip()
                xml_url = parts[1].strip() if len(parts) > 1 else f"https://www.gesetze-im-internet.de/{slug}/xml.zip"
                title = parts[2] if len(parts) > 2 else ""
                if not slug or slug in seen:
                    continue
                seen.add(slug)
                items.append({"slug": slug, "title": title, "xml_url": https_url(xml_url)})
        log.info("TOC from urls.tsv: %s items", len(items))
        return items
    return fetch_toc()


def list_finished_zips() -> list[Path]:
    if not CACHE.exists():
        return []
    out = []
    for pth in CACHE.iterdir():
        if not pth.is_file():
            continue
        if pth.suffix != ".zip":
            continue
        if pth.name.endswith(".part") or pth.name.endswith(".tmp"):
            continue
        try:
            if pth.stat().st_size <= 32:
                continue
        except OSError:
            continue
        out.append(pth)
    return out


def de_downloaders_running() -> bool:
    try:
        import subprocess
        proc = subprocess.run(["ps", "ax", "-o", "args="], capture_output=True, text=True, timeout=5)
        text = proc.stdout or ""
    except Exception:
        return False
    for line in text.splitlines():
        if "fetch_one.sh" in line:
            return True
        if "curl" in line and "gesetze-im-internet.de" in line and "/xml.zip" in line:
            return True
    return False


def part_files() -> list[Path]:
    if not CACHE.exists():
        return []
    return [p for p in CACHE.iterdir() if p.name.endswith(".part")]


def record_needs_reparse(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 20:
        return True
    head = path.read_bytes()[:6000].decode("utf-8", errors="replace")
    if '"source_type":"gesetze_im_internet"' not in head and '"source_type": "gesetze_im_internet"' not in head:
        return True
    if '"retrieved_at"' not in head:
        return True
    if '"jurisdiction":"DE"' not in head and '"jurisdiction": "DE"' not in head:
        return True
    return False


def load_written_stems() -> set[str]:
    done: set[str] = set()
    if INSTRUMENTS.exists():
        for pth in INSTRUMENTS.glob("*.json"):
            if pth.name.startswith("."):
                continue
            done.add(pth.stem)
    return done


def parse_zips_parallel(items: list[dict[str, str]], start: datetime, toc_count: int) -> tuple[int, int, list[str]]:
    """CPU-parallel parse of finished zips. Skip ids already correctly written."""
    INSTRUMENTS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    pending = []
    skip = 0
    for it in items:
        slug = it["slug"]
        sid = safe_id(slug)
        out = INSTRUMENTS / f"{sid}.json"
        if out.exists() and not record_needs_reparse(out):
            skip += 1
            continue
        zip_path = CACHE / f"{slug}.zip"
        if (CACHE / f"{slug}.zip.part").exists():
            continue
        if not zip_path.exists():
            continue
        pending.append(it)
    log.info("parse batch pending=%s skip_ok=%s workers=%s", len(pending), skip, PARSE_WORKERS)
    fail_count = 0
    failed_ids: list[str] = []
    ok_count = 0
    if not pending:
        return ok_count, fail_count, failed_ids
    processed = 0
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=PARSE_WORKERS) as ex:
        futs = {ex.submit(process_cache_item, it): it for it in pending}
        for fut in as_completed(futs):
            processed += 1
            res = fut.result()
            if res.get("ok"):
                ok_count += 1
                row = res.get("row")
                if row:
                    append_index(row)
            else:
                if res.get("transient"):
                    pass
                else:
                    fail_count += 1
                    failed_ids.append(res.get("id") or "?")
                    append_failure({
                        "id": res.get("id"),
                        "error": res.get("error"),
                        "ts": iso_z(now_utc()),
                        "status": "failed",
                    })
            if processed % 100 == 0 or processed == len(pending):
                rate = processed / max(time.time() - t0, 0.001)
                log.info(
                    "parse progress %s/%s ok=%s fail=%s rate=%.1f/s",
                    processed, len(pending), ok_count, fail_count, rate,
                )
    rewrite_summary_from_disk(items, start, failed_ids)
    return ok_count, fail_count, failed_ids


def cleanup_stripped_filenames(items: list[dict[str, str]]) -> int:
    """Remove leftover files from old safe_id() that stripped leading underscores."""
    wanted = {safe_id(it["slug"]) + ".json" for it in items}
    removed = 0
    if not INSTRUMENTS.exists():
        return 0
    for pth in list(INSTRUMENTS.glob("*.json")):
        if pth.name.startswith("."):
            continue
        if pth.name in wanted:
            continue
        # only drop the 35 stripped-underscore leftovers, not unknowns
        if pth.stem and not pth.stem.startswith("_"):
            unders = INSTRUMENTS / f"_{pth.stem}.json"
            if unders.exists() and unders.name in wanted:
                pth.unlink()
                removed += 1
    return removed


def download_missing(items: list[dict[str, str]]) -> list[str]:
    missing = []
    for it in items:
        z = CACHE / f"{it['slug']}.zip"
        if z.exists() and z.stat().st_size > 32:
            continue
        missing.append(it)
    if not missing:
        log.info("no missing TOC zips")
        return []
    log.info("fetching %s missing TOC slugs (not a full re-download)", len(missing))
    CACHE.mkdir(parents=True, exist_ok=True)
    failed = []

    def one(it: dict[str, str]) -> dict[str, Any]:
        slug = it["slug"]
        url = it["xml_url"]
        out = CACHE / f"{slug}.zip"
        if out.exists() and out.stat().st_size > 32:
            return {"ok": True, "id": slug, "skipped": True}
        tmp = CACHE / f"{slug}.zip.part"
        try:
            payload, status = download_bytes(url)
            tmp.write_bytes(payload)
            os.replace(tmp, out)
            return {"ok": True, "id": slug, "bytes": len(payload), "status": status}
        except Exception as e:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            return {"ok": False, "id": slug, "error": f"{type(e).__name__}: {e}"}

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(one, it) for it in missing]
        for fut in as_completed(futs):
            res = fut.result()
            if not res.get("ok"):
                failed.append(res.get("id") or "?")
                append_failure({
                    "id": res.get("id"),
                    "error": res.get("error"),
                    "ts": iso_z(now_utc()),
                    "status": "download_failed",
                })
                log.error("missing fetch FAIL %s %s", res.get("id"), res.get("error"))
            else:
                log.info("missing fetch OK %s", res.get("id"))
    return failed


def rewrite_summary_from_disk(items: list[dict[str, str]], start: datetime, failed_ids: list[str] | None = None) -> None:
    toc_count = len(items)
    toc_slugs = {it["slug"] for it in items}
    files = [p for p in INSTRUMENTS.glob("*.json") if not p.name.startswith(".")] if INSTRUMENTS.exists() else []
    n_files = len(files)
    total_bytes = 0
    status_hist: dict[str, int] = {}
    parsed_slugs: set[str] = set()
    for pth in files:
        total_bytes += pth.stat().st_size
        parsed_slugs.add(pth.stem)
        # law_status from filename match is enough for histogram; sample via index
    index_lines = 0
    index_ids: set[str] = set()
    if INDEX_PATH.exists():
        with INDEX_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                index_lines += 1
                try:
                    rec = json.loads(line)
                    iid = rec.get("id")
                    if iid:
                        index_ids.add(iid)
                    st = rec.get("law_status")
                    if st:
                        status_hist[st] = status_hist.get(st, 0) + 1
                except Exception:
                    pass
    # unique latest status: recount from last index occurrence is hard; compute from files if cheap
    cache_zips = len(list_finished_zips())
    parts = len(part_files())
    missing_toc = sorted(toc_slugs - parsed_slugs)
    failed_ids = failed_ids or []
    extra = sorted(parsed_slugs - toc_slugs)
    coverage = "full" if not missing_toc and not failed_ids else "catalog-backed incomplete"
    end = now_utc()
    elapsed = (end - start).total_seconds()
    hist = ", ".join(f"{k}={v}" for k, v in sorted(status_hist.items())) or "n/a (see instruments)"
    lines = [
        "# German federal law corpus (Bundesrecht)",
        "",
        "- jurisdiction: DE",
        "- source: Bundesministerium der Justiz / gesetze-im-internet.de",
        f"- last_run_retrieved_at: {iso_z(end)} (PT: {iso_pt(end)})",
        f"- instruments_json: {n_files}",
        f"- index_jsonl_lines: {index_lines}",
        f"- index_jsonl_distinct_ids: {len(index_ids)}",
        f"- discovered (TOC): {toc_count}",
        f"- fetched (cache zips): {cache_zips}",
        f"- parsed: {n_files}",
        f"- skipped: 0",
        f"- failed: {len(failed_ids)}",
        f"- law_status: {hist}",
        f"- coverage: {coverage}",
        f"- notes: source_type=gesetze_im_internet; parse from cache xml.zip; fail path logs/failures.jsonl",
        "",
        "## Source",
        "",
        "- Site: https://www.gesetze-im-internet.de/",
        f"- TOC: {TOC_URL}",
        "- Per-instrument XML zip: https://www.gesetze-im-internet.de/{slug}/xml.zip",
        f"- Publisher: {PUBLISHER}",
        f"- Source name: {SOURCE_NAME}",
        f"- source_type: gesetze_im_internet",
        "",
        "## License",
        "",
        LICENSE,
        "",
        "Official federal statutes and regulations published on Gesetze im Internet are",
        "amtliche Werke under § 5 Abs. 1 UrhG and are not protected by copyright.",
        "",
        "## Timing",
        "",
        f"- Start (UTC): {iso_z(start)}",
        f"- Start (PT):  {iso_pt(start)}",
        f"- End (UTC):   {iso_z(end)}",
        f"- End (PT):    {iso_pt(end)}",
        f"- Elapsed:     {elapsed:.1f} s ({elapsed/60:.1f} min)",
        "",
        "## Counts",
        "",
        f"- TOC items:              {toc_count}",
        f"- Cache zips (finished):  {cache_zips}",
        f"- In-progress .part:      {parts}",
        f"- Instruments written:    {n_files}",
        f"- index.jsonl lines:      {index_lines} (append-only; distinct ids {len(index_ids)})",
        f"- Failures:               {len(failed_ids)}",
        f"- TOC slugs missing parse:{len(missing_toc)}",
        f"- Extra files not in TOC: {len(extra)}",
        f"- Total JSON bytes:       {total_bytes} ({total_bytes/1_000_000:.2f} MB)",
        f"- Fail path:              {FAILURES_PATH}",
        "",
        "## Layout",
        "",
        "- `instruments/{id}.json` — one file per statute/regulation (id = GII URL slug)",
        "- `cache/{slug}.zip` — official xml.zip payloads",
        "- `index.jsonl` — append-only",
        "- `logs/collector.log`",
        "- `logs/failures.jsonl`",
        "- `logs/gii-toc.xml` / `logs/urls.tsv`",
        "",
        "## Failures",
        "",
    ]
    if not failed_ids and not missing_toc:
        lines.append("None.")
    else:
        if failed_ids:
            lines.append(f"{len(failed_ids)} failed ids:")
            lines.append("")
            for fid in failed_ids[:200]:
                lines.append(f"- `{fid}`")
            if len(failed_ids) > 200:
                lines.append(f"- … {len(failed_ids)-200} more in {FAILURES_PATH}")
        if missing_toc:
            lines.append("")
            lines.append(f"{len(missing_toc)} TOC slugs not yet parsed (see cache):")
            lines.append("")
            for fid in missing_toc[:50]:
                lines.append(f"- `{fid}`")
            if len(missing_toc) > 50:
                lines.append(f"- … {len(missing_toc)-50} more")
    lines.append("")
    SUMMARY_PATH.write_text("\n".join(lines), encoding="utf-8")


def wait_downloads_idle(idle_sec: float = 60.0, start: datetime | None = None, items: list | None = None) -> None:
    last_active = time.time() if (de_downloaders_running() or part_files()) else time.time() - idle_sec
    if not de_downloaders_running() and not part_files():
        log.info("downloaders already idle")
        return
    log.info("waiting for downloaders idle %.0fs (will keep parsing new zips)", idle_sec)
    while True:
        running = de_downloaders_running()
        parts = part_files()
        if running or parts:
            last_active = time.time()
            log.info("downloaders active fetch_one/curl=%s parts=%s", running, len(parts))
            if items is not None and start is not None:
                parse_zips_parallel(items, start, len(items))
            time.sleep(5)
            continue
        waited = time.time() - last_active
        if waited >= idle_sec:
            log.info("downloaders idle for %.1fs", waited)
            return
        time.sleep(min(5, idle_sec - waited + 0.1))


def orchestrate() -> int:
    setup_logging()
    CACHE.mkdir(parents=True, exist_ok=True)
    INSTRUMENTS.mkdir(parents=True, exist_ok=True)
    start = now_utc()
    log.info("START parse-from-cache orchestrate PARSE_WORKERS=%s", PARSE_WORKERS)
    items = load_toc_items()
    toc_count = len(items)
    log.info("catalog size %s; finished zips %s; parts %s", toc_count, len(list_finished_zips()), len(part_files()))

    # Parse whatever is already on disk without blocking leftover downloads.
    parse_zips_parallel(items, start, toc_count)
    removed = cleanup_stripped_filenames(items)
    if removed:
        log.info("removed %s leftover stripped-underscore filenames", removed)

    wait_downloads_idle(60.0, start=start, items=items)

    # After idle + no .part, fetch TOC slugs still missing, then parse those.
    if part_files():
        wait_downloads_idle(60.0, start=start, items=items)
    dl_fail = download_missing(items)
    if dl_fail:
        log.warning("missing download failures: %s", dl_fail[:20])
    ok, fail, failed_ids = parse_zips_parallel(items, start, toc_count)
    failed_ids = list(dict.fromkeys(failed_ids + dl_fail))
    removed = cleanup_stripped_filenames(items)
    if removed:
        log.info("removed %s leftover stripped-underscore filenames", removed)
    rewrite_summary_from_disk(items, start, failed_ids)

    n_files = sum(1 for pth in INSTRUMENTS.glob("*.json") if not pth.name.startswith("."))
    cache_n = len(list_finished_zips())
    total_bytes = sum(pth.stat().st_size for pth in INSTRUMENTS.glob("*.json") if not pth.name.startswith("."))
    log.info(
        "DONE toc=%s cache_zips=%s files=%s fail=%s bytes=%s fail_path=%s",
        toc_count, cache_n, n_files, len(failed_ids), total_bytes, FAILURES_PATH,
    )
    missing = toc_count - n_files
    return 0 if missing == 0 and not failed_ids else 1


def main() -> int:
    mode = "run"
    if len(sys.argv) > 1:
        a = sys.argv[1]
        if a in {"--parse", "--parse-cache", "parse"}:
            mode = "parse"
        elif a in {"--download", "download"}:
            mode = "download"
        elif a in {"--run", "run"}:
            mode = "run"
    if mode in {"run", "parse"}:
        return orchestrate()
    # legacy download+parse path (network). Prefer cache hits.
    setup_logging()
    start = now_utc()
    log.info("START collector workers=%s (download mode)", WORKERS)
    items = load_toc_items()
    toc_count = len(items)
    pending = []
    skip_count = 0
    for it in items:
        sid = safe_id(it["slug"])
        out = INSTRUMENTS / f"{sid}.json"
        if out.exists() and not record_needs_reparse(out):
            skip_count += 1
        else:
            pending.append(it)
    log.info("Pending: %s skip=%s", len(pending), skip_count)
    fail_count = 0
    failed_ids: list[str] = []
    processed = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(process_safe, it): it for it in pending}
        for fut in as_completed(futs):
            processed += 1
            res = fut.result()
            if not res.get("ok"):
                fail_count += 1
                failed_ids.append(res.get("id") or "?")
            if processed % 50 == 0 or processed == len(pending):
                rate = processed / max(time.time() - t0, 0.001)
                log.info("download-mode progress %s/%s fail=%s rate=%.1f/s", processed, len(pending), fail_count, rate)
    rewrite_summary_from_disk(items, start, failed_ids)
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
