#!/usr/bin/env python3
"""Burundi (bi): official law / décret / ordonnance PDFs from *.bi / *.gouv.bi / *.gov.bi.

Official only:
  - https://presidence.gov.bi/ (Présidence — textes légaux / décrets / Constitution PDF)
  - https://primature.gov.bi/ (Primature — lois et décrets / Constitution 2018)
  - https://justice.gov.bi/ / https://finances.gov.bi/ / https://senat.bi/
  - https://amategeko.gov.bi/ (CEDJ / BOB — when live)
  - Wayback/CDX of the same official *.bi / *.gov.bi / *.gouv.bi URLs

Filter: prefer loi/ordonnance/décret/constitution/code; soft-drop pure nominations;
skip PDFs >12MB. Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
NOTE: country code bi = Burundi. Leave rw/cd/tz alone.
"""
from __future__ import annotations

import html as html_lib
import json
import logging
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit, quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import (
    cdx_urls,
    env_int,
    fetch_official,
    live_get,
    pdf_to_text,
    save_instrument,
    setup_log,
    slug_id,
)

CC, COUNTRY, LANG = "bi", "Burundi", "fr"
SOURCE_TYPE = "burundi_official"
LICENSE = (
    "République du Burundi — Présidence (presidence.gov.bi) / Primature "
    "(primature.gov.bi) / Justice / Finances / Sénat / CEDJ-amategeko "
    "(*.bi / *.gov.bi / *.gouv.bi). Authentic Bulletin Officiel / official text "
    "prevails. Not legal advice."
)
UA = (
    "legal-corpora-collector/1.0 (research; source=https://presidence.gov.bi/; "
    "Burundi=bi)"
)
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("bi")

MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED_SUFFIXES = (
    "presidence.gov.bi",
    "primature.gov.bi",
    "justice.gov.bi",
    "finances.gov.bi",
    "amategeko.gov.bi",
    "senat.bi",
    "www.senat.bi",
    "assemblee.bi",
    "www.assemblee.bi",
    "obr.bi",
    "www.obr.bi",
    "gouv.bi",
    "www.gouv.bi",
    "gov.bi",
    "www.gov.bi",
)

# Broad allow: any host under *.gov.bi / *.gouv.bi / selected *.bi
ALLOWED_ENDS = (
    ".gov.bi",
    ".gouv.bi",
)

KEEP_RE = re.compile(
    r"(loi|ordonnance|ordonn|d[eé]cret|decret|arr[eê]t[eé]|arrete|constitution|code|"
    r"bulletin.?officiel|\bbob\b|organique|r[eè]glement|charte|statut|"
    r"wp-content/uploads|/uploads/|/documents?/|textes?|"
    r"amategeko|burundi)",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|burundi.?lii|droit-afrique|gazettes\.africa|law\.africa|"
    r"discours|allocution|communique|photo|banner|logo|cv[-_]|"
    r"biographie|rapport[-_ ]annuel|presentation|organigramme|"
    r"newsletter|recrutement|facebook|twitter|linkedin|"
    r"album|actualites|appel.?d.?offres|indongozi|"
    r"cmq[-_]?cm|compte[-_ ]rendu|conseil[-_ ]des[-_ ]ministres|"
    r"\brw\b|\.rw/|minijust\.gov\.rw|presidence\.cd|\.cd/)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|ordonnance|d[eé]cret|decret|constitution|bulletin\s+officiel|"
    r"code|r[eé]publique\s+du\s+burundi|assembl[eé]e\s+nationale|"
    r"pr[eé]sident\s+de\s+la\s+r[eé]publique|promulgue|partie\s+officielle|"
    r"conseil\s+des\s+ministres|s[eé]nat|arr[eê]t[eé])\b",
    re.I,
)
NOMINATION_RE = re.compile(
    r"(?i)portant\s+nomination|portant\s+affectation|"
    r"portant\s+d[eé]l[eé]gation\s+de\s+signature|"
    r"portant\s+avancement|nomination\s+d",
)

SEED_PDFS = [
    "https://presidence.gov.bi/wp-content/uploads/2018/07/constitution-promulguee-le-7-juin-2018-1.pdf",
    "https://primature.gov.bi/wp-content/uploads/2026/06/constitution_du_burundi_2018.pdf",
]

HOMES = [
    "https://presidence.gov.bi/",
    "https://presidence.gov.bi/category/textes-legaux/",
    "https://presidence.gov.bi/category/textes-legaux/decrets/decrets-2026/",
    "https://presidence.gov.bi/category/lois-promulguees/",
    "https://primature.gov.bi/",
    "https://primature.gov.bi/category/lois-et-decrets/",
    "https://primature.gov.bi/category/lois-promulguees/",
    "https://primature.gov.bi/constitution/",
    "https://justice.gov.bi/",
    "https://finances.gov.bi/",
    "https://senat.bi/",
    "https://amategeko.gov.bi/",
]

WP_BASES = (
    "https://presidence.gov.bi",
    "https://primature.gov.bi",
)

# (base, category_id or None, slug hint, priority)
WP_CATEGORIES = [
    # Présidence
    ("https://presidence.gov.bi", 171, "lois-promulguees", 2),
    ("https://presidence.gov.bi", 175, "lois-2023", 2),
    ("https://presidence.gov.bi", 30, "decrets-2026", 12),
    ("https://presidence.gov.bi", 28, "decrets-2025", 14),
    ("https://presidence.gov.bi", 176, "decrets-2024", 16),
    ("https://presidence.gov.bi", 25, "decrets-2023", 18),
    ("https://presidence.gov.bi", 24, "decrets", 20),
    # Primature
    ("https://primature.gov.bi", 1, "lois-promulguees", 1),
    ("https://primature.gov.bi", 3, "lois-et-decrets", 3),
    ("https://primature.gov.bi", 7, "decrets", 10),
    ("https://primature.gov.bi", 55, "ordonnances-ministerielles", 8),
    ("https://primature.gov.bi", 18, "arretes", 11),
    ("https://primature.gov.bi", 8, "textes-nationaux", 4),
]

MEDIA_SEARCHES = (
    "loi",
    "constitution",
    "ordonnance",
    "code",
    "decret",
    "budget",
)

CDX_PREFIXES = (
    "presidence.gov.bi/wp-content/uploads/",
    "www.presidence.gov.bi/wp-content/uploads/",
    "primature.gov.bi/wp-content/uploads/",
    "www.primature.gov.bi/wp-content/uploads/",
    "justice.gov.bi/",
    "www.justice.gov.bi/",
    "finances.gov.bi/",
    "amategeko.gov.bi/",
    "senat.bi/",
    "www.senat.bi/",
)


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(
        x in host
        for x in (
            "africanlii",
            "droit-afrique",
            "gazettes.africa",
            "law.africa",
        )
    ):
        return False
    # Never harvest Rwanda / DRC / Tanzania hosts from this collector
    if host.endswith(".rw") or host.endswith(".cd") or host.endswith(".tz"):
        return False
    if host.endswith(".gov.bi") or host.endswith(".gouv.bi"):
        return True
    return any(host == s or host.endswith("." + s) for s in ALLOWED_SUFFIXES)


def _norm_url(url: str) -> str:
    url = html_lib.unescape((url or "").split("#")[0].strip())
    if not url:
        return ""
    url = url.replace(":80/", "/").replace(":80?", "?")
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    if url.startswith("//"):
        url = "https:" + url
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        parts = []
        for seg in p.path.split("/"):
            if not seg:
                parts.append(seg)
                continue
            parts.append(seg if "%" in seg else quote(seg, safe="._-()[]',"))
        url = urlunsplit((p.scheme or "https", host, "/".join(parts), "", ""))
    except Exception:
        url = url.replace(" ", "%20")
    return url


def _ident_from_url(url: str, title: str | None = None) -> str:
    path = unquote(urlsplit(url).path)
    if title:
        t = re.sub(r"\W+", "-", html_lib.unescape(title)).strip("-").lower()[:100]
        if t and len(t) > 8:
            return t
    name = Path(path).name or path
    stem = Path(name).stem
    return re.sub(r"\W+", "-", stem).strip("-").lower()[:160] or re.sub(r"\W+", "-", url)[-80:]


def _extract_pdfs_from_html(html: str, base: str) -> list[str]:
    out: list[str] = []
    if not html:
        return out
    for href in re.findall(r'href=["\']([^"\']+)["\']', html, re.I):
        full = urljoin(base, html_lib.unescape(href))
        if ".pdf" in full.lower():
            out.append(full.split("&")[0].split("?")[0] if "viewer?url=" not in full.lower() else full)
    for m in re.findall(r'(?:viewer\?url=|url=)(https?%3A%2F%2F[^"\'&\s]+\.pdf)', html, re.I):
        out.append(unquote(m))
    for m in re.findall(r'(https?://[^\s"\'<>]+\.pdf)', html, re.I):
        out.append(html_lib.unescape(m))
    # clean google-viewer wrappers
    cleaned = []
    for u in out:
        if "viewer?url=" in u.lower() or "docs.google.com" in u.lower():
            mm = re.search(r"url=([^&]+)", u, re.I)
            if mm:
                cleaned.append(unquote(mm.group(1)))
            continue
        cleaned.append(u.split("#")[0])
    return cleaned


def _keep(url: str, title: str | None = None) -> bool:
    if not _host_ok(url):
        return False
    blob = unquote(urlsplit(url).path) + " " + url + " " + (title or "")
    if DROP_RE.search(blob):
        return False
    low = url.lower().split("?")[0]
    if not (low.endswith(".pdf") or "/download" in low or "/document/" in low):
        return False
    return bool(KEEP_RE.search(blob))


def _is_nomination(url: str, title: str | None = None) -> bool:
    blob = unquote(urlsplit(url).path) + " " + (title or "")
    return bool(NOMINATION_RE.search(blob))


def ocr_pdf(raw: bytes) -> str:
    max_pages = env_int("MAX_OCR_PAGES", 12)
    dpi = env_int("OCR_DPI", 140)
    try:
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "doc.pdf"
            pdf.write_bytes(raw)
            proc = subprocess.run(
                [
                    "pdftoppm", "-png", "-r", str(dpi),
                    "-f", "1", "-l", str(max_pages),
                    str(pdf), str(Path(td) / "p"),
                ],
                check=False, capture_output=True, timeout=240,
            )
            if proc.returncode != 0:
                return ""
            chunks = []
            for img in sorted(Path(td).glob("p*.png")):
                tproc = subprocess.run(
                    ["tesseract", str(img), "stdout", "-l", "fra", "--psm", "6"],
                    check=False, capture_output=True, timeout=120,
                )
                if tproc.returncode == 0 and tproc.stdout:
                    chunks.append(tproc.stdout.decode("utf-8", "replace").strip())
            return "\n\n".join(c for c in chunks if c).strip()
    except Exception as exc:
        log.warning("ocr_pdf: %s", exc)
        return ""


def fetch_bi(url: str, wayback_ts: str | None = None) -> dict:
    got = fetch_official(url, ua=UA, verify=False, min_text=120, wayback=True, wayback_ts=wayback_ts)
    if got.get("status") == "success" and len(got.get("text") or "") >= 120:
        return got
    body = got.get("content") or b""
    if not (isinstance(body, bytes) and body[:4] == b"%PDF"):
        try:
            r = live_get(url, ua=UA, verify=False, timeout=(20, 90), retries=2)
            if getattr(r, "status_code", 0) == 200 and (r.content or b"")[:4] == b"%PDF":
                body = r.content
                got["method"] = "live_pdf"
        except Exception as exc:
            got["error"] = (got.get("error") or "") + f";live_pdf:{exc}"
            return got
    if not (isinstance(body, bytes) and body[:4] == b"%PDF"):
        return got
    if len(body) > MAX_PDF_BYTES:
        got["error"] = f"pdf_too_large:{len(body)}"
        return got
    text = pdf_to_text(body)
    if len(text) >= 120:
        got.update(status="success", text=text, content=body, method=got.get("method") or "http_pdf")
        return got
    max_ocr_bytes = env_int("MAX_OCR_BYTES", 8 * 1024 * 1024)
    if len(body) > max_ocr_bytes:
        got["error"] = (got.get("error") or "") + f";skip_ocr_large:{len(body)}"
        return got
    log.info("OCR fra %s bytes=%s", _ident_from_url(url)[:40], len(body))
    ocr = ocr_pdf(body)
    if len(ocr) >= 120:
        got.update(status="success", text=ocr, content=body, method="ocr_fra")
        return got
    got["error"] = (got.get("error") or "") + ";ocr_short"
    return got


def _add(items, seen, ident, url, ts=None, priority=50, size_hint=None, title=None):
    url = _norm_url(url)
    if not url or not _keep(url, title=title):
        return
    key = url.lower().split("?")[0]
    key2 = key.replace("://www.", "://")
    if key in seen or key2 in seen:
        return
    if size_hint and size_hint > MAX_PDF_BYTES:
        return
    # Soft-demote nominations
    if _is_nomination(url, title):
        priority = max(priority, 40)
    seen.add(key)
    seen.add(key2)
    ident = re.sub(r"\W+", "-", (ident or _ident_from_url(url, title)).strip("-")).lower()[:160]
    items.append((priority, ident, url, ts, size_hint, title))


def _wp_json(url: str):
    try:
        r = live_get(url, ua=UA, verify=False, timeout=(15, 60), retries=2)
    except Exception as exc:
        log.info("wp err %s %s", url[:80], exc)
        return None, {}
    if getattr(r, "status_code", 0) != 200:
        log.info("wp status=%s %s", getattr(r, "status_code", None), url[:80])
        return None, {}
    try:
        return r.json(), dict(getattr(r, "headers", {}) or {})
    except Exception as exc:
        log.info("wp json %s", exc)
        return None, {}


def _discover_wp_media(items, seen):
    per = env_int("MEDIA_PER_QUERY", 40)
    max_pages = env_int("MEDIA_MAX_PAGES", 3)
    for base in WP_BASES:
        for q in MEDIA_SEARCHES:
            for page in range(1, max_pages + 1):
                url = (
                    f"{base}/wp-json/wp/v2/media"
                    f"?search={quote(q)}&per_page={min(20, per)}&page={page}"
                    f"&mime_type=application/pdf&orderby=date&order=desc"
                )
                rows, headers = _wp_json(url)
                if not isinstance(rows, list) or not rows:
                    break
                for row in rows:
                    src = row.get("source_url") or ""
                    title = html_lib.unescape((row.get("title") or {}).get("rendered") or "")
                    pri = 22
                    low = (src + " " + title).lower()
                    if "constitut" in low:
                        pri = 1
                    elif re.search(r"(?i)\bloi\b|ordonnance|code", low):
                        pri = 6
                    elif re.search(r"(?i)decret|d[eé]cret", low):
                        pri = 15
                    _add(items, seen, _ident_from_url(src, title), src, priority=pri, title=title or None)
                total_pages = int(headers.get("X-WP-TotalPages") or headers.get("x-wp-totalpages") or "1")
                if page >= total_pages or len(rows) < min(20, per):
                    break
                time.sleep(0.12)
            log.info("media %s q=%s catalog+=%s", base.split("//")[1], q, len(items))


def _discover_wp_posts(items, seen):
    per = env_int("POSTS_PER_CAT", 30)
    max_pages = env_int("POST_MAX_PAGES", 3)
    for base, cat_id, slug_hint, pri in WP_CATEGORIES:
        got_n = 0
        for page in range(1, max_pages + 1):
            url = (
                f"{base}/wp-json/wp/v2/posts"
                f"?categories={cat_id}&per_page={min(20, per)}&page={page}"
                f"&orderby=date&order=desc"
            )
            rows, headers = _wp_json(url)
            if not isinstance(rows, list) or not rows:
                break
            for row in rows[:per]:
                title = html_lib.unescape((row.get("title") or {}).get("rendered") or "")
                link = row.get("link") or base
                content = (row.get("content") or {}).get("rendered") or ""
                pdfs = _extract_pdfs_from_html(content, link)
                # also media?parent=
                pid = row.get("id")
                if pid and not pdfs:
                    mrows, _ = _wp_json(f"{base}/wp-json/wp/v2/media?parent={pid}&per_page=10")
                    if isinstance(mrows, list):
                        for m in mrows:
                            src = m.get("source_url") or ""
                            if src:
                                pdfs.append(src)
                for pdf in pdfs:
                    ppri = pri
                    low = (pdf + " " + title).lower()
                    if "constitut" in low:
                        ppri = 1
                    elif re.search(r"(?i)\bloi\b|ordonnance|code", low):
                        ppri = min(ppri, 5)
                    _add(items, seen, _ident_from_url(pdf, title), pdf, priority=ppri, title=title or None)
                    got_n += 1
            total_pages = int(headers.get("X-WP-TotalPages") or headers.get("x-wp-totalpages") or "1")
            if page >= total_pages:
                break
            time.sleep(0.12)
        log.info("posts %s/%s links=%s", base.split("//")[1], slug_hint, got_n)


def discover():
    items = []
    seen = set()

    for seed in SEED_PDFS:
        _add(items, seen, _ident_from_url(seed), seed, ts=None, priority=1)

    _discover_wp_media(items, seen)
    _discover_wp_posts(items, seen)

    for home in HOMES:
        try:
            r = live_get(home, ua=UA, verify=False, timeout=(12, 40), retries=1)
            if getattr(r, "status_code", 0) != 200:
                log.info("home status=%s %s", getattr(r, "status_code", None), home)
                continue
            text = r.text or ""
            n = 0
            for full in _extract_pdfs_from_html(text, home):
                pri = 18
                low = unquote(full).lower()
                if "constitut" in low:
                    pri = 1
                elif re.search(r"(?i)(loi|ordonnance|code)", low):
                    pri = 8
                _add(items, seen, _ident_from_url(full), full, ts=None, priority=pri)
                n += 1
            # shallow crawl of promising subpages (max 6 per home)
            sub = []
            for href in re.findall(r'href=["\']([^"\']+)["\']', text, re.I):
                full = urljoin(home, html_lib.unescape(href))
                if not _host_ok(full):
                    continue
                low = unquote(full).lower()
                if any(
                    k in low
                    for k in (
                        "loi", "decret", "code", "constitut", "texte", "document",
                        "download", "upload", "ordonnance", "bob", "amategeko",
                        "legislation", "juridique",
                    )
                ):
                    if full not in sub and not low.endswith(".pdf"):
                        sub.append(full)
            for sub_url in sub[:6]:
                try:
                    r2 = live_get(sub_url, ua=UA, verify=False, timeout=(10, 30), retries=1)
                    if getattr(r2, "status_code", 0) != 200:
                        continue
                    for full in _extract_pdfs_from_html(r2.text or "", sub_url):
                        pri = 19
                        low = unquote(full).lower()
                        if "constitut" in low:
                            pri = 1
                        elif re.search(r"(?i)(loi|ordonnance|code)", low):
                            pri = 9
                        _add(items, seen, _ident_from_url(full), full, ts=None, priority=pri)
                        n += 1
                except Exception as exc:
                    log.info("sub %s %s", sub_url[:80], exc)
            log.info("home %s links=%s", home, n)
        except Exception as exc:
            log.info("home %s %s", home, exc)

    for prefix in CDX_PREFIXES:
        try:
            hits = cdx_urls(
                prefix,
                limit=env_int("CDX_LIMIT", 200),
                match_type="prefix",
                extra_filters=["statuscode:200", "mimetype:application/pdf"],
            ) or []
        except Exception as exc:
            log.info("cdx %s %s", prefix, exc)
            hits = []
        if len(hits) < 5:
            try:
                hits2 = cdx_urls(
                    prefix,
                    limit=env_int("CDX_LIMIT", 200),
                    match_type="prefix",
                    extra_filters=["statuscode:200"],
                ) or []
                for h in hits2:
                    orig = (h.get("original") or "").lower()
                    if ".pdf" in orig:
                        hits.append(h)
            except Exception as exc:
                log.info("cdx2 %s %s", prefix, exc)
        for h in hits:
            orig = h.get("original") or ""
            ts = (h.get("timestamp") or "")[:14] or None
            try:
                length = int(h.get("length") or 0)
            except Exception:
                length = 0
            if length and length > MAX_PDF_BYTES:
                continue
            if not _keep(orig):
                continue
            pri = 28
            low = unquote(orig).lower()
            if "constitut" in low:
                pri = 1
            elif re.search(r"(?i)(loi|ordonnance|code)", low):
                pri = 10
            elif re.search(r"(?i)(decret|d[eé]cret|arrete)", low):
                pri = 22
            _add(items, seen, _ident_from_url(orig), orig, ts=ts, priority=pri, size_hint=length or None)

    items.sort(key=lambda x: (x[0], x[1]))
    out = [(ident, url, ts, size, title) for _, ident, url, ts, size, title in items]
    log.info("catalog %s", len(out))
    return out


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    already = len(done)
    target_total = env_int("TARGET_TOTAL", 0)
    ok = skip = fail = 0
    for ident, url, ts, size_hint, title in discover():
        if max_new and ok >= max_new:
            break
        if target_total and (already + ok) >= target_total:
            break
        if time.time() - t_start > max_seconds:
            break
        if size_hint and size_hint > MAX_PDF_BYTES:
            skip += 1
            continue
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        if not _host_ok(url):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "host_not_bi"})
            continue
        # Prefer substantive instruments: skip nomination-only when we already have stock
        if _is_nomination(url, title) and ok >= env_int("MAX_NOMINATIONS", 15) and already + ok >= 25:
            skip += 1
            continue
        got = fetch_bi(url, wayback_ts=ts)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error"), "wayback_ts": ts})
            continue
        if len(text) > 2_500_000:
            log.info("skip huge text chars=%s %s", len(text), ident[:50])
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_too_large", "chars": len(text)})
            continue
        if not TEXT_KEEP_RE.search(text[:8000]):
            if not re.search(r"(?i)(loi|ordonnance|decret|constitut|code|bob)", ident):
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_not_legal"})
                continue
        use_title = title
        if not use_title:
            for line in text.splitlines():
                if len(line.strip()) > 18:
                    use_title = line.strip()[:240]
                    break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=use_title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_bi.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "wayback_ts": ts, "size_hint": size_hint},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s ts=%s", ident[:60], got.get("method"), len(text), ts)
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY,
        source="Burundi Présidence / Primature / Justice / Finances / Sénat / CEDJ (*.bi / *.gov.bi)",
        source_urls=[
            "https://presidence.gov.bi/",
            "https://primature.gov.bi/",
            "https://primature.gov.bi/constitution/",
            "https://justice.gov.bi/",
            "https://finances.gov.bi/",
            "https://senat.bi/",
            "https://amategeko.gov.bi/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (WP REST media/posts on presidence.gov.bi + primature.gov.bi + live crawl + CDX PDF)",
        notes=(
            "Official *.bi / *.gov.bi / *.gouv.bi PDFs only (Présidence, Primature, Justice, "
            "Finances, Sénat, CEDJ). OCR fra for scans. Not AfricanLII. No WAF bypass. "
            "Not legal advice. bi=Burundi (not rw/cd/tz)."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
