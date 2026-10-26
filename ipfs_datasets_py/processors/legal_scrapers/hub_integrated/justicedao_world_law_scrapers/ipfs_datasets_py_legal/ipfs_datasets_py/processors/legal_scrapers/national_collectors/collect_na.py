#!/usr/bin/env python3
"""Namibia: official Bills / Acts / Gazette instruments from Parliament + BoN.

Primary: laws.parliament.na (Online Bill Tracking — embedded official Bill PDFs),
www.parliament.na (wp-content Bill / Act PDFs + wp-json media), Bank of Namibia
(bon.com.na Regulations / Determinations / Act getattachment PDFs).

Skips: lac.org.na (entirely), namiblii.org, SAFLII, gazettes.africa, speeches,
motivations, contributions, tenders, minutes, notices of award.

Live official URL first; Wayback of the same official URL on failure.
OCR=1 enables pdftoppm+tesseract for image-only official PDFs. No WAF bypass.

Gaps (recorded): www.gov.na SSL EOF from collector host; moj.gov.na timeout;
mfpe.gov.na DNS fail; laws.parliament.na/cms_documents live often 404 → Wayback; full Government Gazette series not mirrored on parliament.na.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, fetch_official_prefer_pdf, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "na", "Namibia", "en"
SOURCE_TYPE = "namibia_official_parliament_bon"
LICENSE = (
    "Laws / Bills / Gazette instruments of Namibia as published on official "
    "Parliament portals (parliament.na / laws.parliament.na) and Bank of Namibia "
    "(bon.com.na) statutory hosts. Authentic Government Gazette / Parliament text "
    "prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.parliament.na/)"
ART = re.compile(
    r"(?im)^\s*((?:Section|Sec\.|Article|Art\.|Regulation|Reg\.)\s+\d+[A-Za-z]?\.?)\b"
)
log = logging.getLogger("na")

BLOCK_HOST = re.compile(
    r"(lac\.org\.na|namiblii\.org|saflii\.org|gazettes\.africa|"
    r"africanlii\.org|commonlii\.org|ulii\.org)",
    re.I,
)
SKIP_NAME = re.compile(
    r"(contribution|motivation|response|speech|report[_\-\s]|NOTICE[_\-\s]?OF|"
    r"minutes|tender|award|vacancy|advert|newsletter|workshop|consultative|"
    r"stakeholder|explanatory[_\-\s]?memorandum|budget[_\-\s]?statement|"
    r"vote\d|sofa|upholstery|procurement[_\-\s]?notice|selection[_\-\s]?for|"
    r"cancellation[_\-\s]?of[_\-\s]?a[_\-\s]?bid|facilitator|travel[_\-\s]?management|"
    r"supply[_\-\s]?and[_\-\s]?delivery|service[_\-\s]?level[_\-\s]?agreement|"
    r"strategy[_\-\s]?advert|mefmi[_\-\s]?advertisement)",
    re.I,
)
LAWISH_NAME = re.compile(
    r"("
    r"\bbill\b|_bill_|-bill-|bill\.pdf|"
    r"\bact\b|_act_|-act-|act\.pdf|"
    r"gazette|regulation|regulations|determination|"
    r"constitution|statutory[_\-\s]?instrument|"
    r"\bb\.?\s*\d+|amendment"
    r")",
    re.I,
)
LAW_MARK = re.compile(
    r"(BE IT ENACTED|AN ACT\b|A BILL\b|BILL\b|Short title|"
    r"This Act may be cited|GOVERNMENT GAZETTE|REPUBLIC OF NAMIBIA|"
    r"ARRANGEMENT OF SECTIONS|NATIONAL ASSEMBLY|PROMULGATION OF ACT|"
    r"No\.\s*\d+\s+of\s+20\d{2}|\[B\.\s*\d+)",
    re.I,
)

CDX_PREFIXES = [
    "laws.parliament.na/cms_documents/",
    "www.parliament.na/wp-content/uploads/",
    "parliament.na/wp-content/uploads/",
    "www.bon.com.na/CMSTemplates/Bon/Files/",
    "bon.com.na/CMSTemplates/Bon/Files/",
]

LIVE_SEEDS = [
    "https://www.parliament.na/bills/",
    "https://www.parliament.na/acts-of-parliament/",
    "https://laws.parliament.na/Bill-register",
    "https://www.bon.com.na/Regulations.aspx",
    "https://www.bon.com.na/Bank/Banking-Supervision/Legal-Frameworks.aspx",
    "https://www.bon.com.na/Bank/Banking-Supervision/Legal-Frameworks/Determinations.aspx",
    "https://www.bon.com.na/Bank/Banking-Supervision/Legal-Frameworks/Regulations.aspx",
]

BON_SEED_PAGES = [
    "https://www.bon.com.na/Regulations.aspx",
    "https://www.bon.com.na/Regulations/Bank-of-Namibia-Act-2020.aspx",
    "https://www.bon.com.na/Regulations/Banking-Institutions-Act-2023.aspx",
    "https://www.bon.com.na/Regulations/Virtual-Assets-Act-2023.aspx",
    "https://www.bon.com.na/Regulations/Financial-Intelligence-Act-2012.aspx",
    "https://www.bon.com.na/Regulations/Namibia-Deposit-Guarantee-Act-2018.aspx",
    "https://www.bon.com.na/Regulations/Payment-System-Management-Act-2003.aspx",
    "https://www.bon.com.na/Regulations/Payment-System-Management-Amendment-Act-2023.aspx",
    "https://www.bon.com.na/Regulations/Currencies-and-Exchanges-Act-1933.aspx",
    "https://www.bon.com.na/Regulations/Prevention-of-Counterfeiting-of-Currency-Act-1965.aspx",
    "https://www.bon.com.na/Bank/Banking-Supervision/Legal-Frameworks/Determinations.aspx",
    "https://www.bon.com.na/Bank/Banking-Supervision/Legal-Frameworks/Regulations.aspx",
    "https://www.bon.com.na/Bank/Banking-Supervision/Legal-Frameworks/Other-Bylaws.aspx",
    "https://www.bon.com.na/Bank/National-Payment-System/Legal-Framework.aspx",
    "https://www.bon.com.na/Bank/Financial-Stability/Determinations-Regulations-and-Guidance-Notes.aspx",
]


def _norm(url: str) -> str:
    u = (url or "").split("#")[0]
    u = u.replace("http://", "https://")
    u = re.sub(r":80/", "/", u)
    u = re.sub(r"https://parliament\.na/", "https://www.parliament.na/", u)
    u = re.sub(r"https://bon\.com\.na/", "https://www.bon.com.na/", u)
    # Drop tracking query junk; keep empty for getattachment
    parts = urlparse(u)
    path = parts.path or ""
    if " " in unquote(path) or "%" in path:
        from urllib.parse import quote

        path = quote(unquote(path), safe="/%")
    return parts._replace(path=path, query="", params="", fragment="").geturl().rstrip("?")


def _ident_from_url(url: str) -> str:
    path = unquote(urlparse(url.split("?")[0]).path)
    name = Path(path).name
    if name.lower() in ("", ".aspx", ".aspx/") or name.lower() == ".aspx":
        # BoN getattachment/<uuid>/.aspx
        m = re.search(r"getattachment/([0-9a-f-]{36})", url, re.I)
        if m:
            name = f"bon-{m.group(1)[:12]}"
        else:
            name = Path(path.rstrip("/")).name or "na-doc"
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    if name.lower().endswith(".aspx"):
        name = name[:-5]
    name = re.sub(r"\s+", " ", name).strip()
    return re.sub(r"[^\w.\-]+", "-", name)[:160] or "na-doc"


def _host_ok(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    if BLOCK_HOST.search(url):
        return False
    host = (urlparse(url).hostname or "").lower()
    ok = (
        "parliament.na",
        "bon.com.na",
        "gov.na",
        "moj.gov.na",
        "mfpe.gov.na",
        "opm.gov.na",
    )
    return any(host == s or host.endswith("." + s) for s in ok)


def _is_law_url(url: str) -> bool:
    u = _norm(url)
    if not _host_ok(u):
        return False
    low = unquote(u).lower()
    if SKIP_NAME.search(low):
        return False
    # Historic laws.parliament.na statute book (live often 404 → Wayback)
    if "laws.parliament.na" in low and "/cms_documents/" in low and ".pdf" in low:
        return True
    # BoN getattachment — accepted when discovered from Act/Determination pages
    if "parliament.gov.na" in low and "/acts_documents/" in low and ".pdf" in low:
        return True
    if "bon.com.na" in low and "/getattachment/" in low:
        return True
    if "bon.com.na" in low and "/cmstemplates/bon/files/" in low and ".pdf" in low:
        return True
    if ".pdf" not in low:
        return False
    name = unquote(urlparse(u.split("?")[0]).path).split("/")[-1]
    if SKIP_NAME.search(name):
        return False
    if LAWISH_NAME.search(name) or LAWISH_NAME.search(low):
        return True
    return False


def _title_from_text(text: str, fallback: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for ln in lines[:60]:
        if re.search(r"\b(ACT|BILL|REGULATIONS?|GAZETTE|DETERMINATION)\b", ln) and 8 <= len(ln) <= 180:
            if not re.match(r"^(TITLE|PREVIOUS|NEXT|CONTENTS|EXPLANATORY)\b", ln, re.I):
                return ln[:240]
    for ln in lines:
        if len(ln) >= 12 and not ln.lower().startswith("just a moment"):
            return ln[:240]
    return fallback[:240]


def _looks_like_law(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    head = text[:10000]
    if LAW_MARK.search(head):
        return True
    secs = len(re.findall(r"(?im)^\s*Section\s+\d+", text[:25000]))
    return secs >= 5


def _add(items: list, seen: set, url: str, ident: str | None = None) -> None:
    url = _norm(url)
    if not url or url in seen or not _is_law_url(url):
        return
    seen.add(url)
    items.append((ident or _ident_from_url(url), url))


def pdf_ocr_text(raw: bytes, *, max_pages: int = 30, dpi: int = 160) -> str:
    """OCR scanned / image-only official PDFs via pdftoppm + tesseract (eng)."""
    if not raw or raw[:4] != b"%PDF":
        return ""
    max_pages = env_int("OCR_MAX_PAGES", max_pages)
    try:
        with tempfile.TemporaryDirectory() as d:
            pdf = Path(d) / "in.pdf"
            pdf.write_bytes(raw)
            subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-r",
                    str(dpi),
                    "-f",
                    "1",
                    "-l",
                    str(max_pages),
                    str(pdf),
                    str(Path(d) / "p"),
                ],
                check=False,
                capture_output=True,
                timeout=300,
            )
            pages = sorted(Path(d).glob("p*.png"))
            chunks = []
            for page in pages:
                proc = subprocess.run(
                    ["tesseract", str(page), "stdout", "-l", "eng", "--psm", "6"],
                    capture_output=True,
                    timeout=180,
                )
                if proc.stdout:
                    chunks.append(proc.stdout.decode("utf-8", "replace"))
            return "\n".join(chunks).strip()
    except Exception as exc:
        log.info("ocr fail: %s", exc)
        return ""


def fetch_na(url: str) -> dict:
    """Live (+Wayback of same official URL); OCR when OCR=1 for image-only PDFs."""
    got = fetch_official_prefer_pdf(url, ua=UA, verify=False, min_text=180)
    if got.get("status") == "success":
        return got
    if os.environ.get("OCR", "0") != "1":
        return got
    err = got.get("error") or ""
    body = got.get("content") if isinstance(got.get("content"), (bytes, bytearray)) else b""
    if not body or body[:4] != b"%PDF":
        try:
            r = live_get(url, ua=UA, verify=False, timeout=(15, 90), retries=2)
            body = r.content or b""
        except Exception:
            body = b""
        if (not body or body[:4] != b"%PDF") and "wayback" not in err:
            try:
                import archive_fallbacks as af

                w = af.get_wayback_content(url)
                if w.get("status") == "success":
                    body = w.get("content") or b""
                    if isinstance(body, str):
                        body = body.encode("latin-1", "replace")
            except Exception:
                pass
    if body and body[:4] == b"%PDF":
        text = pdf_ocr_text(bytes(body))
        if len(text) >= 180:
            got.update(
                status="success",
                text=text,
                content=bytes(body),
                method=(got.get("method") or "http") + "+ocr",
                error="",
            )
            return got
        got["error"] = (err or "") + ";ocr_short_or_failed"
    return got


def _decode_data_pdf(html: str) -> bytes:
    m = re.search(r"data:application/pdf;base64,([A-Za-z0-9+/=\s&#x0-9a-fA-F;]+)", html or "")
    if not m:
        return b""
    b64 = m.group(1)
    b64 = (
        b64.replace("&#x2B;", "+")
        .replace("&#x2F;", "/")
        .replace("&#x3D;", "=")
        .replace("&amp;", "&")
        .replace("&#43;", "+")
    )
    b64 = re.sub(r"\s+", "", b64)
    # strip residual HTML entities
    b64 = re.sub(r"&#x[0-9a-fA-F]+;", "", b64)
    b64 = re.sub(r"&#\d+;", "", b64)
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception:
        return b""
    return raw if raw[:4] == b"%PDF" else b""


def _harvest_html(url: str) -> list[str]:
    out = []
    try:
        r = live_get(url, ua=UA, verify=False, timeout=(20, 50))
    except Exception as exc:
        log.info("seed fail %s: %s", url[:90], exc)
        return out
    text = r.text or ""
    for href in re.findall(r'href=["\']([^"\']+)["\']', text, re.I):
        full = urljoin(url, href)
        if ".pdf" in full.lower() or "/getattachment/" in full.lower():
            out.append(full)
    for m in re.findall(r'(https?://[^"\'\s>]+\.pdf)', text, re.I):
        out.append(m)
    return out


def _laws_parliament_bills() -> list[tuple[str, str, str]]:
    """Return (ident, synthetic_source_url, detail_url) for Bill Tracking PDFs.

    Instruments are stored against the Public/Bills/Details/<uuid> official URL;
    PDF bytes are embedded as data:application/pdf;base64 on that page.
    """
    items, seen = [], set()
    register = "https://laws.parliament.na/Bill-register"
    try:
        r = live_get(register, ua=UA, verify=False, timeout=(25, 70))
    except Exception as exc:
        log.info("bill register fail: %s", exc)
        return items
    ids = sorted(set(re.findall(r"/Public/Bills/Details/([0-9a-f-]{36})", r.text or "", re.I)))
    log.info("laws.parliament.na bill ids %s", len(ids))
    cap = env_int("BILL_DETAILS", 120)
    for bid in ids[:cap]:
        detail = f"https://laws.parliament.na/Public/Bills/Details/{bid}"
        if detail in seen:
            continue
        seen.add(detail)
        # Title from register table if present
        m = re.search(
            rf'href=["\']/Public/Bills/Details/{bid}["\'][^>]*>([^<]{{3,120}})',
            r.text or "",
            re.I,
        )
        label = (m.group(1).strip() if m else "") or f"bill-{bid[:8]}"
        ident = re.sub(r"[^\w.\-]+", "-", label)[:120] or f"bill-{bid[:8]}"
        items.append((ident, detail, detail))
    return items


def _fetch_embedded_bill(detail_url: str) -> dict:
    out = {
        "status": "error",
        "text": "",
        "content": b"",
        "source_url": detail_url,
        "method": "",
        "error": "",
    }
    try:
        r = live_get(detail_url, ua=UA, verify=False, timeout=(30, 120), retries=2)
    except Exception as exc:
        out["error"] = f"live:{exc}"
        return out
    html = r.text or ""
    title_m = re.search(r'<h2[^>]*class="[^"]*page-title[^"]*"[^>]*>([^<]+)', html, re.I)
    page_title = (title_m.group(1).strip() if title_m else "")
    raw = _decode_data_pdf(html)
    if not raw:
        out["error"] = "no_embedded_pdf"
        return out
    # text extract
    from world_lib import pdf_to_text

    text = pdf_to_text(raw)
    method = "embedded_pdf"
    if len(text) < 180 and os.environ.get("OCR", "0") == "1":
        ocr = pdf_ocr_text(raw)
        if len(ocr) > len(text):
            text, method = ocr, "embedded_pdf+ocr"
    if len(text) < 180:
        out.update(error="pdf_extract_failed", content=raw)
        return out
    out.update(
        status="success",
        text=text,
        content=raw,
        method=method,
        source_url=detail_url,
        page_title=page_title,
    )
    return out


def _wp_json_media() -> list[tuple[str, str]]:
    items, seen = [], set()
    try:
        import requests
        from requests.packages.urllib3.exceptions import InsecureRequestWarning

        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    except Exception:
        return items
    for page in range(1, env_int("WP_MEDIA_PAGES", 8) + 1):
        url = (
            "https://www.parliament.na/wp-json/wp/v2/media"
            f"?per_page=100&page={page}&mime_type=application/pdf"
        )
        try:
            r = requests.get(url, timeout=(20, 50), headers={"User-Agent": UA}, verify=False)
        except Exception as exc:
            log.info("wp media fail page %s: %s", page, exc)
            break
        if r.status_code != 200:
            break
        data = r.json() if r.content else []
        if not data:
            break
        for it in data:
            su = it.get("source_url") or ""
            if not su or su in seen:
                continue
            if not _is_law_url(su):
                continue
            seen.add(su)
            items.append((_ident_from_url(su), su))
    log.info("wp-json lawish pdfs %s", len(items))
    return items


def _bon_attachments() -> list[tuple[str, str]]:
    items, seen = [], set()
    pages = list(BON_SEED_PAGES)
    # Expand Regulations.aspx child Act pages
    try:
        r = live_get("https://www.bon.com.na/Regulations.aspx", ua=UA, verify=False, timeout=(20, 50))
        for href in re.findall(r'href=["\']([^"\']+)["\']', r.text or "", re.I):
            full = urljoin("https://www.bon.com.na/Regulations.aspx", href)
            if re.search(r"/Regulations/[^\"']+(Act|Regulation|Determination)", full, re.I):
                if full not in pages:
                    pages.append(full)
    except Exception as exc:
        log.info("bon regulations index fail: %s", exc)

    for page in pages[: env_int("BON_PAGES", 40)]:
        try:
            r = live_get(page, ua=UA, verify=False, timeout=(20, 50))
        except Exception as exc:
            log.info("bon page fail %s: %s", page[:80], exc)
            continue
        # Prefer labelled Act/Determination attachments near lawish anchor text
        html = r.text or ""
        for href in re.findall(r'href=["\']([^"\']*getattachment[^"\']*)["\']', html, re.I):
            full = _norm(urljoin(page, href))
            if full in seen:
                continue
            # Skip obvious image/css attachments by fetching later; filter by nearby text
            seen.add(full)
            # ident from surrounding context if possible
            slug = Path(urlparse(page).path).name.replace(".aspx", "")
            m = re.search(r"getattachment/([0-9a-f-]{36})", full, re.I)
            uuid = m.group(1)[:12] if m else "att"
            ident = f"{slug}-{uuid}"[:140]
            items.append((ident, full))
    log.info("bon attachments %s", len(items))
    return items


def discover():
    items, seen = [], set()

    # 1) Live seed harvest (parliament + BoN HTML)
    for su in LIVE_SEEDS:
        for href in _harvest_html(su):
            _add(items, seen, href)

    # 2) Parliament wp-json media (Bill/Act PDFs)
    for ident, url in _wp_json_media():
        _add(items, seen, url, ident)

    # 3) BoN Act / Determination / Regulation attachments
    for ident, url in _bon_attachments():
        # BoN getattachment always allowed when harvested from Act pages
        url = _norm(url)
        if not url or url in seen or not _host_ok(url):
            continue
        if BLOCK_HOST.search(url):
            continue
        seen.add(url)
        items.append((ident, url))

    # 4) CDX of official hosts
    limit = env_int("CDX_LIMIT", 500)
    for prefix in CDX_PREFIXES:
        for h in cdx_urls(prefix, limit=limit, match_type="prefix", extra_filters=["mimetype:application/pdf"]):
            orig = (h.get("original") or "").replace("http://", "https://")
            _add(items, seen, orig)
        if len(items) >= env_int("CATALOG_CAP", 500):
            break

    log.info("catalog pdf/attach %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0

    # A) Embedded Bill PDFs from laws.parliament.na (priority — official Bill Tracking)
    for ident, source_url, detail in _laws_parliament_bills():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = _fetch_embedded_bill(detail)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": source_url, "reason": got.get("error")})
            continue
        if not _looks_like_law(text):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": source_url, "reason": "not_law_like"})
            continue
        title = got.get("page_title") or _title_from_text(text, ident)
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title,
            text=text,
            source_url=source_url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_na.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "portal": "laws.parliament.na"},
        ):
            ok += 1
            done.add(rid)
            log.info("ok bill %s chars=%s method=%s", ident[:70], len(text), got.get("method"))
        else:
            fail += 1

    # B) Direct PDF / BoN attachment catalog
    for ident, url in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_na(url)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        if not _looks_like_law(text):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "not_law_like"})
            continue
        title = _title_from_text(text, ident)
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
            collector="collect_na.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s method=%s", ident[:70], len(text), got.get("method"))
        else:
            fail += 1

    write_summary(
        CC,
        country=COUNTRY,
        source="Namibia Parliament (parliament.na / laws.parliament.na) + Bank of Namibia",
        source_urls=[
            "https://www.parliament.na/",
            "https://laws.parliament.na/",
            "https://laws.parliament.na/Bill-register",
            "https://www.bon.com.na/Regulations.aspx",
            "https://www.gov.na/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete; lac.org.na skipped by policy; "
            "gov.na/moj.gov.na/mfpe.gov.na unreachable or SSL-fail from collector host; "
            "full Government Gazette series not on parliament.na"
        ),
        notes=(
            "Official Bills from laws.parliament.na Bill Tracking (embedded PDFs) and "
            "parliament.na wp-content; BoN Act/Determination/Regulation getattachment PDFs. "
            "Skipped lac.org.na / NamibLII / SAFLII. OCR when OCR=1. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()