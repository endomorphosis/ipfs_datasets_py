#!/usr/bin/env python3
"""Moldova legislation collector.

legis.md is Cloudflare-blocked live. Prefer:
  - old1.parlament.md HTML legal foundation (Constitution, Regulament, etc.)
  - old1.parlament.md /download/laws/*.doc official adopted laws
  - justice.gov.md public PDFs when substantive
  - Wayback of the SAME official legis.md / parlament.md URLs only (no WAF bypass)

Rejects PDF-binary garbage previously mis-saved as wayback_html.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import logging
import os
import re
import sys
import time
import zipfile
import io
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, html_to_text, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id, pdf_to_text

CC, COUNTRY, LANG = "md", "Moldova", "ro"
SOURCE_TYPE = "moldova_official"
LICENSE = (
    "Official legislation of the Republic of Moldova "
    "(parlament.md / old1.parlament.md / legis.md State Register / justice.gov.md). "
    "Authentic register / Monitorul Oficial text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.old1.parlament.md/)"
# Romanian article headings: Art. 1 / Articolul 12 / Art.I (roman)
ART = re.compile(
    r"(?im)^\s*((?:Articolul|Art\.?)\s*(?:[0-9]+(?:\^[0-9]+)?[a-zA-Zăâîșțºª°]?|[IVXLC]{1,8}))\.?\b"
)
log = logging.getLogger("md")

OLD1 = "https://www.old1.parlament.md"
JUSTICE = "https://justice.gov.md"

HTML_SEEDS = (
    f"{OLD1}/legalfoundation/constitution/",
    f"{OLD1}/legalfoundation/declaration/",
    f"{OLD1}/legalfoundation/deputystatus/",
    f"{OLD1}/legalfoundation/regulations/",
    f"{OLD1}/legalfoundation/electoralcode/",
    f"{OLD1}/law/constitution/",
    f"{OLD1}/law/deputylaw/",
)

PDF_GARBAGE_MARKERS = (
    "%PDF-",
    " endobj",
    "/Type /Page",
    "stream\n",
    "cm /I",
    "xref\n",
)


def _is_pdf_garbage(text: str) -> bool:
    head = (text or "")[:4000]
    if not head:
        return True
    hits = sum(1 for m in PDF_GARBAGE_MARKERS if m in head)
    if hits >= 2:
        return True
    if head.lstrip().startswith("%PDF"):
        return True
    # high ratio of non-printable / replacement chars
    sample = head[:2000]
    bad = sum(1 for c in sample if ord(c) < 9 or c == "\ufffd")
    if bad > 80:
        return True
    return False


def _looks_like_law(text: str) -> bool:
    if len(text or "") < 200:
        return False
    if _is_pdf_garbage(text):
        return False
    low = text.lower()
    keys = (
        "articolul",
        "art.",
        "lege",
        "parlament",
        "monitorul oficial",
        "hotărâre",
        "hotarire",
        "constitu",
        "codul",
        "republicii moldova",
    )
    return sum(1 for k in keys if k in low) >= 2


def doc_to_text(raw: bytes) -> str:
    """Extract text from legacy .doc (OLE) or .docx; best-effort without antiword."""
    if not raw or len(raw) < 64:
        return ""
    # DOCX
    if raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                name = "word/document.xml"
                if name not in zf.namelist():
                    return ""
                xml = zf.read(name).decode("utf-8", "replace")
                xml = re.sub(r"</w:p>", "\n", xml)
                xml = re.sub(r"<[^>]+>", "", xml)
                return re.sub(r"\n{3,}", "\n\n", xml).strip()
        except Exception as exc:
            log.info("docx extract fail: %s", exc)
            return ""
    # OLE Word .doc
    if raw[:4] != b"\xd0\xcf\x11\xe0":
        return ""
    try:
        import olefile
    except ImportError:
        log.info("olefile missing; pip install olefile")
        return ""
    try:
        ole = olefile.OleFileIO(io.BytesIO(raw))
        if not ole.exists("WordDocument"):
            return ""
        stream = ole.openstream("WordDocument").read()
        # UTF-16LE printable runs
        t16 = stream.decode("utf-16le", "ignore")
        parts: list[str] = []
        cur: list[str] = []
        for ch in t16:
            if ch.isprintable() or ch in "\n\r\t":
                cur.append(ch)
            else:
                if len(cur) >= 24:
                    parts.append("".join(cur))
                cur = []
        if len(cur) >= 24:
            parts.append("".join(cur))
        text = "\n".join(parts)
        # Collapse spaced-out titles like "L E G E"
        text = re.sub(
            r"(?m)^(?:[A-Za-zăâîșțĂÂÎȘȚşţŞŢ]\s){3,}[A-Za-zăâîșțĂÂÎȘȚşţŞŢ]\s*$",
            lambda m: m.group(0).replace(" ", ""),
            text,
        )
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    except Exception as exc:
        log.info("doc ole extract fail: %s", exc)
        return ""


def _ident_from_url(url: str) -> str:
    path = unquote(urlsplit(url).path)
    name = Path(path).name or path.strip("/").replace("/", "-")
    name = re.sub(r"\.(docx?|pdf|zip|html?)$", "", name, flags=re.I)
    name = re.sub(r"[^\w.\-]+", "-", name, flags=re.UNICODE).strip("-")[:160]
    return name or re.sub(r"\W+", "-", url)[-80:]


def _add(items, seen, ident, url, meta):
    url = url.split("#")[0]
    if not url or url in seen:
        return
    if any(x in url.lower() for x in (".css", ".js", "/login", "captcha", "microsoft.com")):
        return
    seen.add(url)
    items.append((ident, url, meta))


def discover_html_foundation(items, seen):
    n0 = len(items)
    for url in HTML_SEEDS:
        _add(
            items,
            seen,
            "html-" + _ident_from_url(url),
            url,
            {"portal": "old1.parlament.md", "kind": "html"},
        )
    log.info("html foundation seeds=%s", len(items) - n0)


def discover_old1_docs(items, seen):
    """Month indexes under /laws/list/ and lawprocess detail download links."""
    n0 = len(items)
    month_urls = set()
    for seed in (f"{OLD1}/laws/list/", f"{OLD1}/lawprocess/laws/"):
        try:
            r = live_get(seed, ua=UA, timeout=(12, 30), retries=2)
        except Exception as exc:
            log.info("month seed fail %s: %s", seed, exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        for h in re.findall(r'href=["\']([^"\']+)["\']', r.text or "", re.I):
            full = urljoin(r.url, h)
            if re.search(r"/laws/list/[^/]+/?$", urlsplit(full).path) or re.search(
                r"/lawprocess/laws/[^/]+/?$", urlsplit(full).path
            ):
                if full.rstrip("/") != seed.rstrip("/"):
                    month_urls.add(full)
    log.info("month indexes=%s", len(month_urls))
    # Cap months for runtime; prefer laws/list (binary .doc of adopted laws)
    laws_list = sorted(u for u in month_urls if "/laws/list/" in u)
    lawprocess = sorted(u for u in month_urls if "/lawprocess/laws/" in u)
    # Take all laws/list + a sample of recent lawprocess months
    selected = laws_list + lawprocess[:40]
    detail_pages = []
    for mu in selected:
        try:
            r = live_get(mu, ua=UA, timeout=(10, 25), retries=1)
        except Exception:
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        for h in re.findall(r'href=["\']([^"\']+)["\']', r.text or "", re.I):
            full = urljoin(r.url, h)
            path = urlsplit(full).path.lower()
            if "/download/laws/" in path and path.endswith((".doc", ".docx", ".pdf")):
                _add(
                    items,
                    seen,
                    "doc-" + _ident_from_url(full),
                    full.replace("http://", "https://"),
                    {"portal": "old1.parlament.md", "kind": "doc"},
                )
            elif "/download/drafts/" in path and path.endswith((".doc", ".docx", ".pdf")):
                _add(
                    items,
                    seen,
                    "draft-" + _ident_from_url(full),
                    full.replace("http://", "https://"),
                    {"portal": "old1.parlament.md", "kind": "draft_doc"},
                )
            elif re.search(r"/lawprocess/laws/[^/]+/Nr\.", path):
                detail_pages.append(full)
    # Follow a bounded number of lawprocess detail pages for download links
    for du in detail_pages[:120]:
        try:
            r = live_get(du, ua=UA, timeout=(10, 20), retries=1)
        except Exception:
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        for h in re.findall(r'href=["\']([^"\']+)["\']', r.text or "", re.I):
            full = urljoin(r.url, h)
            path = urlsplit(full).path.lower()
            if "/download/" in path and path.endswith((".doc", ".docx", ".pdf")):
                kind = "draft_doc" if "/drafts/" in path else "doc"
                _add(
                    items,
                    seen,
                    f"{kind}-" + _ident_from_url(full),
                    full.replace("http://", "https://"),
                    {"portal": "old1.parlament.md", "kind": kind},
                )
    log.info("old1 docs/new=%s (details_followed=%s)", len(items) - n0, min(120, len(detail_pages)))


def discover_justice_pdfs(items, seen):
    n0 = len(items)
    seeds = [
        f"{JUSTICE}/ro/content/acte-normative",
        f"{JUSTICE}/ro/advanced-page-type/proiecte-de-acte-normative-0",
        f"{JUSTICE}/ro/content/concepte-de-acte-normative",
    ]
    for seed in seeds:
        try:
            r = live_get(seed, ua=UA, timeout=(12, 30), retries=1)
        except Exception as exc:
            log.info("justice fail %s: %s", seed[:60], exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        for h in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', r.text or "", re.I):
            full = urljoin(r.url, h)
            host = (urlsplit(full).hostname or "").lower()
            if "justice.gov.md" not in host:
                continue
            _add(
                items,
                seen,
                "justice-" + _ident_from_url(full),
                full,
                {"portal": "justice.gov.md", "kind": "pdf"},
            )
    log.info("justice pdfs new=%s", len(items) - n0)


def discover_legis_wayback(items, seen):
    """CDX of official legis.md downloadpdf / UserFiles only — no live CF bypass."""
    if os.environ.get("FORCE_CDX", "1") != "1":
        return
    n0 = len(items)
    limit = env_int("CDX_LIMIT", 200)
    for prefix in (
        "www.legis.md/cautare/downloadpdf/",
        "legis.md/cautare/downloadpdf/",
        "www.legis.md/UserFiles/",
        "legis.md/UserFiles/",
    ):
        try:
            hits = cdx_urls(prefix, limit=limit, match_type="prefix")
        except Exception as exc:
            log.info("cdx fail %s: %s", prefix, exc)
            continue
        for h in hits:
            orig = (h.get("original") or "").strip()
            if not orig:
                continue
            if orig.startswith("http://"):
                orig = "https://" + orig[len("http://") :]
            host = (urlsplit(orig).hostname or "").lower()
            if "legis.md" not in host:
                continue
            _add(
                items,
                seen,
                "legis-" + _ident_from_url(orig),
                orig,
                {"portal": "legis.md", "kind": "wayback_legis"},
            )
    log.info("legis wayback candidates new=%s", len(items) - n0)


def discover():
    items, seen = [], set()
    discover_html_foundation(items, seen)
    discover_old1_docs(items, seen)
    discover_justice_pdfs(items, seen)
    discover_legis_wayback(items, seen)

    def rank(it):
        kind = (it[2] or {}).get("kind") or ""
        portal = (it[2] or {}).get("portal") or ""
        if kind == "html":
            return 0
        if kind == "doc":
            return 1
        if kind == "pdf" and "justice" in portal:
            return 2
        if kind == "draft_doc":
            return 3
        return 4  # legis wayback last

    items.sort(key=rank)
    log.info("catalog total=%s", len(items))
    return items


def fetch_md(url: str, meta: dict) -> dict:
    kind = (meta or {}).get("kind") or ""
    # Direct DOC/PDF download via live_get (SSL fallback inside)
    if kind in ("doc", "draft_doc") or url.lower().endswith((".doc", ".docx")):
        try:
            r = live_get(url, ua=UA, timeout=(15, 60), retries=2)
        except Exception as exc:
            return {"status": "error", "error": f"live:{exc}", "text": "", "method": ""}
        if getattr(r, "status_code", 0) != 200 or not r.content:
            return {
                "status": "error",
                "error": f"http_{getattr(r, 'status_code', '?')}",
                "text": "",
                "method": "",
            }
        body = r.content
        if body[:4] == b"%PDF":
            text = pdf_to_text(body)
            method = "http_pdf"
        else:
            text = doc_to_text(body)
            method = "http_doc"
        if _looks_like_law(text):
            return {"status": "success", "text": text, "content": body, "method": method, "error": ""}
        return {"status": "error", "error": "doc_short_or_garbage", "text": text[:200], "method": method}

    got = fetch_official(url, ua=UA, min_text=150, wayback=True)
    text = got.get("text") or ""
    # Repair: Wayback sometimes returns PDF bytes decoded as "html"
    if got.get("status") == "success" and _is_pdf_garbage(text):
        body = got.get("content") or b""
        if isinstance(body, str):
            body = body.encode("latin-1", "replace")
        idx = body.find(b"%PDF") if isinstance(body, (bytes, bytearray)) else -1
        if idx >= 0:
            pdf_bytes = bytes(body[idx:])
            text2 = pdf_to_text(pdf_bytes)
            if _looks_like_law(text2):
                got.update(
                    text=text2,
                    content=pdf_bytes,
                    method=(got.get("method") or "wayback") + "+pdf_repair",
                    error="",
                )
                return got
        got.update(status="error", error="pdf_garbage_text", text="")
        return got
    if got.get("status") == "success" and not _looks_like_law(text):
        got.update(status="error", error="not_law_like", text="")
    return got


def _title_from_text(text: str, fallback: str) -> str:
    keys = (
        "constitu",
        "lege",
        "codul",
        "hotăr",
        "hotar",
        "regulament",
        "monitorul",
        "declarat",
        "statut",
    )
    cands = []
    for line in (text or "").splitlines():
        s = line.strip()
        if len(s) < 10:
            continue
        low = s.lower()
        if any(k in low for k in keys):
            return s[:240]
        if len(s) > 16:
            cands.append(s)
        if len(cands) >= 6:
            break
    return (cands[0] if cands else fallback)[:240]


def purge_garbage_instruments() -> int:
    """Remove previously saved PDF-binary garbage so packaging stays clean."""
    root = _CORPORA / CC / "instruments"
    if not root.exists():
        return 0
    removed = 0
    for p in list(root.glob("*.json")):
        try:
            import json

            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        if _is_pdf_garbage(text) or not _looks_like_law(text):
            p.unlink(missing_ok=True)
            removed += 1
    if removed:
        log.info("purged garbage instruments=%s", removed)
    return removed


def main():
    setup_log(CC)
    t0 = utcnow()
    purged = purge_garbage_instruments()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    portals: dict[str, int] = {}
    for ident, url, meta in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_md(url, meta)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(
                CC,
                {
                    "identifier": ident,
                    "source_url": url,
                    "reason": got.get("error"),
                    "portal": meta.get("portal"),
                },
            )
            continue
        title = _title_from_text(text, ident)
        portal = meta.get("portal") or "unknown"
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title,
            text=text,
            source_url=url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_md.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "portal": portal, "kind": meta.get("kind")},
        ):
            ok += 1
            done.add(rid)
            portals[portal] = portals.get(portal, 0) + 1
            log.info(
                "ok %s portal=%s chars=%s method=%s",
                ident[:70],
                portal,
                len(text),
                got.get("method"),
            )
        else:
            fail += 1
    write_summary(
        CC,
        country=COUNTRY,
        source="old1.parlament.md + justice.gov.md (+ Wayback legis.md)",
        source_urls=[
            "https://www.old1.parlament.md/legalfoundation/",
            "https://www.old1.parlament.md/laws/list/",
            "https://justice.gov.md/ro/content/acte-normative",
            "https://www.legis.md/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete; legis.md live Cloudflare — "
            "old1.parlament.md HTML/DOC primary; Wayback of official URLs only"
        ),
        notes=(
            f"Official Moldova texts. portals={portals} purged_garbage={purged}. "
            "No WAF/CF bypass. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s purged=%s portals=%s", ok, skip, fail, purged, portals)


if __name__ == "__main__":
    main()
