#!/usr/bin/env python3
"""Montserrat: gov.ms Attorney General's Chambers (Revised Edition Acts 2025/2019 +
Annual Acts Passed + SROs / Resolutions) + mcrs.gov.ms Customs legislation PDFs.

Official-only *.gov.ms (prefer www.gov.ms / mcrs.gov.ms). Live WordPress shelves
+ CDX of official wp-content/uploads PDFs. Skip bills/press/forms. Not vLex /
commercial aggregators. parliament.ms catalog is official Legislative Assembly
but PDFs are not exposed as direct downloads — rely on gov.ms mirrors.
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
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text
import requests

CC, COUNTRY, LANG = "ms", "Montserrat", "en"
SOURCE_TYPE = "gov_ms_agc"
LICENSE = (
    "Government of Montserrat — Attorney General's Chambers (gov.ms; Revised Edition "
    "of the Laws / Acts Passed / Statutory Rules and Orders / Resolutions) + Montserrat "
    "Customs & Revenue Service (mcrs.gov.ms legislation). Authentic Official Gazette / "
    "Government Printer / printed Revised Edition prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://www.gov.ms/)"
)
ART = re.compile(
    r"(?im)^\s*((?:Section|Article|Art\.?|SCHEDULE|Schedule|PART)\s+[0-9]+[A-Za-z]?|"
    r"s\.\s*[0-9]+[A-Za-z]?)\b"
)
log = logging.getLogger("ms")
MAX_PDF = env_int("MAX_PDF_BYTES", 12 * 1024 * 1024)

HOST_OK = (
    "gov.ms", "www.gov.ms", "mcrs.gov.ms", "www.mcrs.gov.ms",
    "agc.gov.ms", "www.agc.gov.ms",
)
SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|minutes|hansard|favicon|"
    r"vacancy|tender|questionnaire|organisational.?chart|organizational.?chart|"
    r"explanatory.?memorandum|\bbill\b|/bills/|_INTRODUCED|draft-|draft_|draft\s|"
    r"privacy.?policy|faqs|press.?release|speech|budget.?address|throne.?speech|"
    r"consultation.?paper|travel.?protocols|photo.?competition|subscription.?form|"
    r"fact.?sheet|progress.?report|missive|appointment.?of|"
    r"\.docx?$|\.jpe?g$|\.png$|\.doc$|\.css$|\.webp$)",
    re.I,
)
KEEP_RE = re.compile(
    r"(legislation|gazette|act|acts|constitution|ordinance|regulation|order|rules?|"
    r"statutory|instrument|notice|proclamation|subsidiary|revised|s\.?r\.?o|"
    r"sros?|resolution|wp-content/uploads|customs|revenue)",
    re.I,
)
CDX_PREFIXES = (
    "www.gov.ms/wp-content/uploads/",
    "gov.ms/wp-content/uploads/",
    "mcrs.gov.ms/wp-content/uploads/",
    "agc.gov.ms/wp-content/uploads/",
)
# Prefer 2025 Revised Edition, then Constitution, annual Acts, SROs
LIVE_SHELVES = (
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/acts-revised-2025/", "REVISED_2025"),
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/acts-passed-2026/", "ACT"),
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/acts-passed-2025/", "ACT"),
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/acts-passed-2024/", "ACT"),
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/acts-passed-2023/", "ACT"),
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/acts-passed-2022/", "ACT"),
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/acts-passed-2021/", "ACT"),
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/acts-passed-2018-2020/", "ACT"),
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/acts-passed-2016/", "ACT"),
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/sros/", "SRO"),
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/sros-2018/", "SRO"),
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/sros-2015-2016/", "SRO"),
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/sros-2013-2014/", "SRO"),
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/resolutions/", "RESOLUTION"),
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/acts-revised-2019/", "REVISED_2019"),
    ("https://mcrs.gov.ms/legislation/", "MCRS"),
    ("https://www.gov.ms/government/legal-department/attorney-generals-chambers/", "AGC_HOME"),
)
SEED_DOCS = (
    (
        "https://www.gov.ms/wp-content/uploads/2026/02/1.01-Constitution-of-Montserrat-Act.pdf",
        "Constitution of Montserrat Act",
        "CONSTITUTION",
    ),
)
PDF_HREF_RE = re.compile(
    r'href=["\']([^"\']+\.pdf[^"\']*)["\']',
    re.I,
)
PDF_ABS_RE = re.compile(
    r'(https?://(?:(?:www\.)?(?:gov|mcrs|agc)\.ms)/[^\s"\'<>]+\.pdf)',
    re.I,
)


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if not url:
        return url
    if "&amp;" in url:
        url = url.replace("&amp;", "&")
    if "?" in url and ".pdf" in url.lower():
        url = url.split("?")[0]
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("gov.ms"):
        url = url.replace("http://", "https://").replace(":80/", "/")
    if host == "gov.ms":
        url = url.replace("://gov.ms", "://www.gov.ms", 1)
    if host == "www.mcrs.gov.ms":
        url = url.replace("://www.mcrs.gov.ms", "://mcrs.gov.ms", 1)
    if host == "www.agc.gov.ms":
        url = url.replace("://www.agc.gov.ms", "://agc.gov.ms", 1)
    try:
        parts = urlparse(url)
        if parts.path and (" " in parts.path or any(ord(c) < 33 for c in parts.path)):
            segs = parts.path.split("/")
            enc = "/".join(quote(unquote(s), safe=".-_()%~[],") for s in segs)
            url = parts._replace(path=enc).geturl()
    except Exception:
        pass
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h == host or host.endswith("." + h) for h in HOST_OK) or host.endswith(".gov.ms")


def _category(url: str, hint: str = "", shelf: str = "") -> str:
    blob = f"{url} {hint} {shelf}".lower()
    path = unquote(urlparse(url).path).lower()
    if "constitut" in blob or re.search(r"/1\.01-", path):
        return "CONSTITUTION"
    if shelf == "REVISED_2025" or "/2026/02/" in path and re.search(r"/\d+\.\d+-", path):
        if "amendment" in blob or "amending" in blob:
            return "AMENDING_ACT"
        return "REVISED_2025"
    if shelf == "REVISED_2019" or ("revised" in blob and "2019" in blob):
        return "REVISED_2019"
    if shelf == "RESOLUTION" or "resolution" in blob:
        return "RESOLUTION"
    if shelf == "SRO" or re.search(r"\bs\.?r\.?o\b|/sro", blob):
        return "SRO"
    if re.search(r"\bact\b", blob) and "bill" not in blob:
        if re.search(r"amendment|amending", blob):
            return "AMENDING_ACT"
        return "ACT"
    if re.search(
        r"regulation|rules?|order|notice|proclamation|instrument|"
        r"subsidiary|commencement|by-?laws?",
        blob,
    ):
        return "SRO"
    if shelf in ("ACT", "MCRS", "AGC_HOME"):
        return "ACT" if shelf == "ACT" else ("SRO" if "sro" in blob else "ACT")
    return ""


def _ident_from_url(url: str, hint: str = "") -> str:
    path = unquote(urlparse(url).path)
    # Chapter-style revised: 1.01-Constitution-of-Montserrat-Act.pdf
    m = re.search(r"/(\d+\.\d+-[^/]+?)(?:\.pdf)?$", path, re.I)
    if m:
        return re.sub(r"[^\w.\-]+", "_", m.group(1)).strip("_")[:160]
    # Act No. N of YYYY
    m = re.search(r"/(Act[-_. ]No\.?[-_. ]?\d+[-_. ]of[-_. ]\d{4}[^/]*?)(?:\.pdf)?$", path, re.I)
    if m:
        return re.sub(r"[^\w.\-]+", "_", m.group(1)).strip("_")[:160]
    # SRO No. N of YYYY
    m = re.search(r"/(S\.?R\.?O\.?[-_. ]No\.?[-_. ]?\d+[-_. ]of[-_. ]\d{4}[^/]*?)(?:\.pdf)?$", path, re.I)
    if m:
        return re.sub(r"[^\w.\-]+", "_", m.group(1)).strip("_")[:160]
    if hint:
        h = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if h and len(h) > 4:
            return h
    stem = Path(path).stem
    if stem:
        return re.sub(r"[^\w.\-]+", "_", unquote(stem)).strip("_")[:160]
    return ("doc_" + re.sub(r"[^\w.\-]+", "_", path)).strip("_")[:160]


def _rank(ident: str, cat: str, url: str) -> int:
    blob = f"{ident} {cat} {url}".lower()
    if cat == "CONSTITUTION" or "constitut" in blob:
        return 0
    if cat == "REVISED_2025":
        return 1
    if cat == "ACT" and "amendment" not in blob:
        return 2
    if cat in ("AMENDING_ACT", "REVISED_2019"):
        return 3
    if cat == "SRO":
        return 4
    if cat == "RESOLUTION":
        return 5
    return 6


def _title_from_path(url: str) -> str:
    path = unquote(urlparse(url).path)
    stem = Path(path.rstrip("/")).name
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    stem = re.sub(r"^(\d+\.\d+)-", "", stem)  # strip chapter
    stem = re.sub(r"^Act[-_. ]No\.?[-_. ]?", "Act No. ", stem, flags=re.I)
    stem = re.sub(r"^S\.?R\.?O\.?[-_. ]No\.?[-_. ]?", "SRO No. ", stem, flags=re.I)
    return stem.replace("-", " ").replace("_", " ").replace("+", " ")[:200].strip()


def _session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "Referer": "https://www.gov.ms/government/legal-department/attorney-generals-chambers/",
        }
    )
    sess.verify = False
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    return sess


def discover():
    seen_url, best = set(), {}
    sess = _session()

    def add(url, ts="", title_hint="", cat="", shelf=""):
        url = _norm(url)
        if not url:
            return
        low = url.lower()
        if ".pdf" not in low:
            return
        if not _host_ok(url):
            return
        blob = f"{low} {title_hint} {cat} {shelf}"
        if SKIP_RE.search(blob):
            return
        if "/bills/" in low:
            return
        if re.search(r"\bbill\b", title_hint or "", re.I) and "act" not in (title_hint or "").lower():
            return
        if not KEEP_RE.search(blob):
            return
        cat = cat or _category(url, title_hint, shelf)
        if not cat:
            if "constitut" in blob:
                cat = "CONSTITUTION"
            elif re.search(r"\bs\.?r\.?o\b", blob):
                cat = "SRO"
            elif re.search(r"\bact\b", blob):
                cat = "REVISED_2025" if re.search(r"/\d+\.\d+-", low) else "ACT"
            elif "resolution" in blob:
                cat = "RESOLUTION"
            else:
                cat = "SRO"
        ident = _ident_from_url(url, title_hint)
        if not ident:
            return
        if url in seen_url:
            return
        seen_url.add(url)
        row = (ident, url, (title_hint or "").strip()[:200], cat, ts or "", shelf or "")
        prev = best.get(ident)
        if prev is None:
            best[ident] = row
        else:
            pr = _rank(prev[0], prev[3], prev[1])
            nr = _rank(row[0], row[3], row[1])
            if nr < pr or (nr == pr and (ts or "") > (prev[4] or "")):
                best[ident] = row

    for url, hint, cat in SEED_DOCS:
        add(url, "", hint, cat, shelf="CONSTITUTION")

    for base, shelf in LIVE_SHELVES:
        try:
            r = sess.get(base, timeout=90)
            if r.status_code != 200:
                log.warning("live %s status=%s", base, r.status_code)
                continue
            before = len(best)
            hrefs = PDF_HREF_RE.findall(r.text or "")
            abs_pdfs = PDF_ABS_RE.findall(r.text or "")
            for href in list(hrefs) + list(abs_pdfs):
                full = href if href.startswith("http") else urljoin(base, href)
                tip = _title_from_path(full)
                add(full, "", tip, shelf=shelf)
            log.info("shelf %s +%s catalog=%s", shelf, len(best) - before, len(best))
        except Exception as exc:
            log.warning("shelf %s fail: %s", shelf, exc)

    lim = env_int("CDX_LIMIT", 1500)
    for prefix in CDX_PREFIXES:
        try:
            before = len(best)
            hits = list(
                cdx_urls(
                    prefix,
                    limit=lim,
                    match_type="prefix",
                    extra_filters=["mimetype:application/pdf"],
                )
            )
            for h in hits:
                orig = h.get("original") or ""
                ts = h.get("timestamp") or ""
                if not orig or ".pdf" not in orig.lower():
                    continue
                tip = _title_from_path(orig)
                add(orig, ts, tip)
            log.info("cdx %s +%s catalog=%s", prefix, len(best) - before, len(best))
        except Exception as exc:
            log.warning("cdx %s fail: %s", prefix, exc)

    items = [
        (ident, url, hint, cat, ts)
        for ident, url, hint, cat, ts, shelf in best.values()
    ]
    items.sort(key=lambda it: (_rank(it[0], it[3], it[1]), it[1]))
    log.info("catalog %s", len(items))
    return items


def ocr_pdf(raw: bytes) -> tuple[str, str, int]:
    os.environ.setdefault("TESSDATA_PREFIX", "/home/box/tessdata")
    ocr_pages = env_int("OCR_PAGES", 10)
    return extract_pdf_text(raw, enable_ocr=True, ocr_lang="eng", ocr_max_pages=ocr_pages)


def fetch_pdf(url: str, wayback_ts: str = "") -> dict:
    sess = _session()
    sess.headers["Referer"] = "https://www.gov.ms/government/legal-department/attorney-generals-chambers/"
    sess.headers["Accept"] = "application/pdf,application/octet-stream,text/html,*/*;q=0.8"
    url = _norm(url)
    candidates = [url]
    # also try without www / with www
    if "://www.gov.ms/" in url:
        candidates.append(url.replace("://www.gov.ms/", "://gov.ms/", 1))
    elif "://gov.ms/" in url:
        candidates.append(url.replace("://gov.ms/", "://www.gov.ms/", 1))

    for cand in candidates:
        try:
            r = sess.get(cand, timeout=90, allow_redirects=True)
            body = r.content or b""
            if r.status_code == 200 and body[:4] == b"%PDF" and len(body) <= MAX_PDF:
                from world_lib import pdf_to_text

                text = pdf_to_text(body)
                if text and len(text) >= 120:
                    return {
                        "status": "success",
                        "text": text,
                        "content": body,
                        "method": "http_pdf_session",
                        "error": "",
                        "source_url": cand,
                    }
                text2, how, pages = ocr_pdf(body)
                if text2 and len(text2) >= 100:
                    return {
                        "status": "success",
                        "text": text2,
                        "content": body,
                        "method": f"ocr:{how}",
                        "error": "",
                        "source_url": cand,
                    }
        except Exception as exc:
            log.debug("session fetch fail %s: %s", cand[:80], exc)

    got = fetch_official(
        url,
        ua=UA,
        verify=False,
        min_text=120,
        wayback_ts=wayback_ts or None,
    )
    if got.get("status") == "success":
        return got
    raw = got.get("content") or b""
    if isinstance(raw, bytes) and raw[:4] == b"%PDF" and len(raw) <= MAX_PDF:
        text, how, pages = ocr_pdf(raw)
        if text and len(text) >= 100:
            got.update(status="success", text=text, method=f"ocr:{how}", error="")
            return got
        got["error"] = (got.get("error") or "") + f";ocr_failed:{how}"
    return got


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 175)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = ocr_used = 0
    for ident, url, hint, cat, ts in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_pdf(url, ts)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        if "ocr" in str(got.get("method") or "").lower():
            ocr_used += 1
        title = hint or None
        if not title:
            for line in text.splitlines():
                if len(line.strip()) > 18:
                    title = line.strip()[:240]
                    break
        if cat and title and cat.lower().replace("_", " ") not in title.lower():
            title = f"{title} [{cat}]"
        src = got.get("source_url") or url
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title or ident,
            text=text,
            source_url=src,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_ms.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "category": cat, "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC,
        country=COUNTRY,
        source=(
            "Attorney General's Chambers (gov.ms Revised Edition Acts / Acts Passed / "
            "SROs / Resolutions) / MCRS legislation (mcrs.gov.ms)"
        ),
        source_urls=[
            "https://www.gov.ms/government/legal-department/attorney-generals-chambers/",
            "https://www.gov.ms/government/legal-department/attorney-generals-chambers/acts-revised-2025/",
            "https://www.gov.ms/government/legal-department/attorney-generals-chambers/acts-passed-2026/",
            "https://www.gov.ms/government/legal-department/attorney-generals-chambers/sros/",
            "https://mcrs.gov.ms/legislation/",
            "https://parliament.ms/assembly-documents/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (gov.ms AGC 2025 Revised Acts + Annual Acts "
            "+ SROs/Resolutions + mcrs.gov.ms + CDX; parliament.ms PDFs not direct)"
        ),
        notes=(
            f"Official gov.ms/wp-content AGC Revised 2025 + Annual Acts Passed + SRO "
            f"shelves + mcrs.gov.ms Customs legislation + Wayback CDX of official "
            f"*.gov.ms uploads. Prefer Constitution + Revised 2025 + Annual Acts. "
            f"Skip bills/drafts/press/travel-protocols. OCR eng used={ocr_used}. "
            f"Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
