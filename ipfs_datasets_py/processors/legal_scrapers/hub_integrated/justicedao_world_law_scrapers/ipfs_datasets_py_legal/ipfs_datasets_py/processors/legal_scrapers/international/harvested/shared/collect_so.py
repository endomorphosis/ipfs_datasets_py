#!/usr/bin/env python3
"""Somalia (so): official federal law PDFs from parliament.gov.so + moj.gov.so.

Official only:
  - https://parliament.gov.so/  (Baarlamaanka Federaalka / Golaha Shacabka — WP media Sharci/Dastuur)
  - https://parliament.gov.so/document-library/
  - https://moj.gov.so/  (Ministry of Justice and Constitutional Affairs publications)
  - https://www.somalia.gov.so/ / opm.gov.so / mof.gov.so (federal *.gov.so probes)
  - Wayback/CDX of the same official *.gov.so URLs

Prefer Sharci (laws), Dastuur/Constitution, Xeerka Miisaaniyadda / Qoondaha (budget appropriation),
Ansixinta Sharci (enactments). Skip Soojeedin (motions), Hindise Sharciyeed (draft bills),
non-federal regional packs, PDFs >12MB. NOT AfricanLII / Refworld / Somaliland-only hosts.
No WAF bypass. Not legal advice.
NOTE: country code so = Somalia. Leave dj/et/er/ke alone.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import (
    cdx_urls,
    env_int,
    fetch_official,
    live_get,
    save_instrument,
    setup_log,
    slug_id,
)

CC, COUNTRY, LANG = "so", "Somalia", "so"
SOURCE_TYPE = "somalia_federal_parliament_moj"
LICENSE = (
    "Federal Republic of Somalia — Federal Parliament (parliament.gov.so / "
    "Baarlamaanka Federaalka Soomaaliya) / Ministry of Justice and Constitutional "
    "Affairs (moj.gov.so). Authentic official text prevails. Not legal advice."
)
UA = (
    "legal-corpora-collector/1.0 (research; source=https://parliament.gov.so/; "
    "Somalia=so)"
)
ART = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|Qodobka|Qodob|Cutubka|Cutub|Xubin|Section|Sec\.?)\s*\d+[a-zA-Zº°]?)\b"
)
log = logging.getLogger("so")

PARLIAMENT = "https://parliament.gov.so"
MOJ = "https://moj.gov.so"
MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED_SUFFIXES = ("gov.so",)

# Seed known official MoJ constitution amendment PDF (publications page)
SEED_PDFS = [
    (
        "moj-dastuur-wax-kabedel-cutub-1-4",
        f"{MOJ}/wp-content/uploads/2025/07/"
        "Nuqulka-Rasmiga-ah-ee-wax-kabedelka-cutubka-1aad-2aad-3aad-iyo-4aad-ee-Dastuurka.pdf",
        "Nuqulka Rasmiga ah ee wax-kabedelka cutubka 1aad–4aad ee Dastuurka",
        1,
    ),
]

KEEP_RE = re.compile(
    r"(sharci|ansixint|dastuur|constitut|miisaaniy|xeerka|xeer-hoosaad|xeerhoosaad|"
    r"qoondaha|qoondada|digreet|decree|qaanuun|legislation|xeer(?!\s*ilaali))",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|refworld|somaliland|puntland|gazettes\.africa|law\.africa|"
    r"soojeedin|suaal|su['’]?aal|isimada|yeerid|yeerayo|xildhibaan|beelaha|"
    r"dalab|aragtida|hindise|hindisa|warbixin|agenda|minutes|jadwal|calendar|"
    r"photo|banner|logo|cv[-_]|biograph|newsletter|facebook|twitter|linkedin|"
    r"album|actualites|portrait|recruitment|vacancy|tender|speech|workshop|"
    r"seminar|powerpoint|\bppt\b|cassette)",
    re.I,
)
# Allow enacted laws even if filename contains words DROP would otherwise catch
FORCE_KEEP_RE = re.compile(
    r"(?i)(^|/|-)(sharci|ansixinta?-?sharci|dastuur|constitut|xeerka-?(qoondada|miisaaniy)|"
    r"qoondaha-?miisaaniy|provisional-constitution|wax-ka-bedelka-sharci|"
    r"nuqulka-rasmiga.*dastuur)"
)
TEXT_KEEP_RE = re.compile(
    r"\b(sharci|xeer|dastuur|constitution|jamhuuriyadda\s+federaalka|"
    r"federal\s+republic\s+of\s+somalia|baarlamaanka|golaha\s+shacabka|"
    r"qodobka|article\s+\d|madaxweyne|ra.?iisul\s+wasaare|ansixin|"
    r"miisaaniyad|provisional\s+constitution)\b",
    re.I,
)

CDX_PREFIXES = (
    "parliament.gov.so/wp-content/uploads/",
    "www.parliament.gov.so/wp-content/uploads/",
    "moj.gov.so/wp-content/uploads/",
    "www.moj.gov.so/wp-content/uploads/",
    "somalia.gov.so/",
    "www.somalia.gov.so/",
)


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(x in host for x in ("africanlii", "refworld", "gazettes.africa", "law.africa", "somaliland")):
        return False
    return any(host == s or host.endswith("." + s) for s in ALLOWED_SUFFIXES)


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()


def _ident_from_url(url: str, prefix: str = "parliament") -> str:
    stem = Path(unquote(urlsplit(url).path)).stem
    stem = re.sub(r"[^\w\-]+", "-", stem).strip("-").lower()
    return f"{prefix}-{stem}"[:160]


def _priority(name: str) -> int:
    low = name.lower()
    if re.search(r"dastuur|constitut|provisional", low):
        return 1
    if re.search(r"(^|[/_\-])sharci|ansixinta.?sharci|ansixint-.*sharci", low):
        return 5
    if re.search(r"miisaaniy|qoondaha|qoondada|xeerka-miisaaniy|xeerka-qoondada", low):
        return 10
    if re.search(r"xeer-hoosaad|xeerhoosaad", low):
        return 25  # standing orders — secondary
    if re.search(r"qaraar", low):
        return 30
    return 20


def _should_keep(url: str, title: str = "") -> bool:
    blob = unquote(url) + " " + (title or "")
    if not _host_ok(url):
        return False
    if FORCE_KEEP_RE.search(blob):
        if DROP_RE.search(blob) and not KEEP_RE.search(blob):
            return False
        # still drop clear motions/drafts unless forced enacted law pattern
        if re.search(r"(?i)soojeedin|hindise|hindisa", blob) and not re.search(
            r"(?i)(ansixint|sharci(?:ga)?-|dastuur|constitut|xeerka)", blob
        ):
            return False
        return True
    if DROP_RE.search(blob):
        return False
    return bool(KEEP_RE.search(blob))


def _wp_media_pdfs(base: str, *, max_pages: int = 10) -> list[dict]:
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        url = (
            f"{base}/wp-json/wp/v2/media"
            f"?per_page=100&page={page}&mime_type=application/pdf"
            f"&orderby=date&order=desc"
        )
        try:
            r = live_get(url, ua=UA, timeout=(15, 60), retries=3)
        except Exception as exc:
            log.info("wp media %s page=%s err %s", base, page, exc)
            break
        if getattr(r, "status_code", 0) != 200:
            log.info("wp media %s page=%s status=%s", base, page, getattr(r, "status_code", None))
            break
        try:
            rows = r.json()
        except Exception as exc:
            log.info("wp json err %s", exc)
            break
        if not isinstance(rows, list) or not rows:
            break
        out.extend(rows)
        total_pages = int(r.headers.get("X-WP-TotalPages") or "1")
        if page >= total_pages:
            break
        time.sleep(0.12)
    return out


def _scrape_page_pdfs(page_url: str) -> list[tuple[str, str]]:
    """Return (url, title_guess) PDF hrefs from an HTML page."""
    try:
        r = live_get(page_url, ua=UA, timeout=(15, 45), retries=2)
    except Exception as exc:
        log.info("page %s err %s", page_url, exc)
        return []
    if getattr(r, "status_code", 0) != 200 or not r.text:
        return []
    html = r.text
    found: list[tuple[str, str]] = []
    for m in re.finditer(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I):
        href = m.group(1).replace("&amp;", "&")
        if href.startswith("/"):
            href = f"{urlsplit(page_url).scheme}://{urlsplit(page_url).hostname}{href}"
        title = unquote(Path(urlsplit(href).path).stem).replace("-", " ").replace("_", " ")
        found.append((href, title))
    return found


def discover():
    """Return list of (priority, ident, url, ts|None, title, size_hint|None)."""
    items: list[tuple] = []
    seen: set[str] = set()

    def add(url: str, *, ident: str | None = None, title: str = "", ts: str | None = None,
            size_hint: int | None = None, priority: int | None = None, prefix: str = "parliament"):
        url = (url or "").split("#")[0].strip()
        if url.startswith("http://"):
            url = "https://" + url[len("http://") :]
        if not url.startswith("http") or not _should_keep(url, title):
            return
        if ".pdf" not in url.lower():
            return
        key = url.lower()
        if key in seen:
            return
        seen.add(key)
        if size_hint and size_hint > MAX_PDF_BYTES:
            log.info("catalog skip >12MB sz=%s %s", size_hint, url.split("/")[-1][:60])
            return
        iid = ident or _ident_from_url(url, prefix=prefix)
        pri = priority if priority is not None else _priority(url + " " + title)
        items.append((pri, iid, url, ts, title or iid, size_hint))

    for ident, url, title, pri in SEED_PDFS:
        add(url, ident=ident, title=title, priority=pri, prefix="moj")

    # Parliament WP media catalog (primary)
    for it in _wp_media_pdfs(PARLIAMENT):
        src = it.get("source_url") or ""
        title = _strip_html((it.get("title") or {}).get("rendered") or "")
        sz = None
        try:
            sz = int((it.get("media_details") or {}).get("filesize") or 0) or None
        except Exception:
            sz = None
        date = (it.get("date") or "")[:10]
        add(src, title=title or date, size_hint=sz, prefix="parliament")

    # MoJ WP media if open; else publications HTML scrape
    try:
        moj_media = _wp_media_pdfs(MOJ, max_pages=3)
    except Exception:
        moj_media = []
    for it in moj_media:
        src = it.get("source_url") or ""
        title = _strip_html((it.get("title") or {}).get("rendered") or "")
        sz = None
        try:
            sz = int((it.get("media_details") or {}).get("filesize") or 0) or None
        except Exception:
            sz = None
        add(src, title=title, size_hint=sz, prefix="moj")

    for page in (
        f"{MOJ}/publications/",
        f"{PARLIAMENT}/",
        f"{PARLIAMENT}/document-library/",
        f"{PARLIAMENT}/legislation-4/",
        "https://www.somalia.gov.so/",
        "https://opm.gov.so/",
        "https://mof.gov.so/",
    ):
        prefix = "moj" if "moj.gov.so" in page else (
            "somalia" if "somalia.gov.so" in page else (
                "opm" if "opm.gov.so" in page else (
                    "mof" if "mof.gov.so" in page else "parliament"
                )
            )
        )
        for href, title in _scrape_page_pdfs(page):
            add(href, title=title, prefix=prefix)

    if env_int("INCLUDE_CDX_PDF", 1):
        for prefix in CDX_PREFIXES:
            try:
                hits = cdx_urls(
                    prefix,
                    limit=env_int("CDX_LIMIT", 80),
                    match_type="prefix",
                    extra_filters=["statuscode:200", "mimetype:application/pdf"],
                ) or []
            except Exception as exc:
                log.info("cdx %s %s", prefix, exc)
                hits = []
            for h in hits:
                orig = h.get("original") or ""
                ts = (h.get("timestamp") or "")[:14] or None
                try:
                    length = int(h.get("length") or 0)
                except Exception:
                    length = 0
                if length and length > MAX_PDF_BYTES:
                    continue
                host_prefix = "moj" if "moj.gov.so" in orig else "parliament"
                add(orig, ts=ts, size_hint=length or None, prefix=host_prefix)

    items.sort(key=lambda x: (x[0], x[1]))
    log.info("catalog %s", len(items))
    return items


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

    for pri, ident, url, ts, title, size_hint in discover():
        if max_new and ok >= max_new:
            break
        if target_total and (already + ok) >= target_total:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        if size_hint and size_hint > MAX_PDF_BYTES:
            skip += 1
            continue

        got = fetch_official(url, ua=UA, wayback=True, wayback_ts=ts, min_text=200)
        # If live returned PDF bytes too large, skip
        content = got.get("content") or b""
        if content and len(content) > MAX_PDF_BYTES:
            skip += 1
            log.info("skip >12MB downloaded %s", ident[:60])
            continue
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(
                CC,
                {
                    "identifier": ident,
                    "source_url": url,
                    "reason": got.get("error"),
                    "wayback_ts": ts,
                },
            )
            continue
        if len(text) > 2_500_000:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_too_large", "chars": len(text)})
            continue
        if not TEXT_KEEP_RE.search(text[:10000]):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_not_legal"})
            continue

        use_title = title or ident
        for line in text.splitlines():
            if len(line.strip()) > 18:
                use_title = line.strip()[:240]
                break

        # language hint: English constitutions vs Somali laws
        lang = LANG
        if re.search(r"(?i)\b(constitution|article\s+1|federal republic of somalia)\b", text[:3000]) and not re.search(
            r"(?i)\bqodobka\b", text[:3000]
        ):
            lang = "en"

        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=lang,
            ident=ident,
            title=use_title,
            text=text,
            source_url=url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_so.py",
            article_re=ART,
            extra_meta={
                "fetch_method": got.get("method"),
                "wayback_ts": ts,
                "size_hint": size_hint,
                "priority": pri,
            },
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s pri=%s", ident[:60], got.get("method"), len(text), pri)
        else:
            fail += 1

    write_summary(
        CC,
        country=COUNTRY,
        source=(
            "Somalia Federal Parliament (parliament.gov.so) / "
            "Ministry of Justice and Constitutional Affairs (moj.gov.so)"
        ),
        source_urls=[
            "https://parliament.gov.so/",
            "https://parliament.gov.so/document-library/",
            "https://parliament.gov.so/legislation-4/",
            "https://moj.gov.so/",
            "https://moj.gov.so/publications/",
            "https://www.somalia.gov.so/",
            "https://opm.gov.so/",
            "https://mof.gov.so/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (parliament.gov.so WP media Sharci/Dastuur PDFs live; "
            "moj.gov.so publications; CDX optional; PDFs >12MB skipped)"
        ),
        notes=(
            "Official federal *.gov.so only (parliament.gov.so / moj.gov.so primary). "
            "Not AfricanLII / Refworld / Somaliland regional packs. "
            "No WAF bypass. Not legal advice. so=Somalia (not dj/et/er/ke)."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
