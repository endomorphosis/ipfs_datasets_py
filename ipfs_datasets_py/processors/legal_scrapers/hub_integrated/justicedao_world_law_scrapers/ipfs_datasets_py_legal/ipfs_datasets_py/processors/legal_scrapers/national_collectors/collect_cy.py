#!/usr/bin/env python3
"""Cyprus: official GPO gazette (mof.gov.cy). PDF body extraction. Not cylaw.org."""
from __future__ import annotations
import io, logging, os, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC, COUNTRY, SOURCE_TYPE = "cy", "Cyprus", "gpo_gazette"
LICENSE = "Official Gazette of the Republic of Cyprus, Government Printing Office (mof.gov.cy/gpo). cylaw.org is unofficial and is NOT used."
UA = DEFAULT_UA + " source=https://www.mof.gov.cy/mof/gpo/"
log = logging.getLogger("cy")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def try_get(url, verify_first=True):
    last = None
    order = (True, False) if verify_first else (False, True)
    for verify in order:
        try:
            time.sleep(0.35)
            r = get_session(UA).get(url, timeout=(15, 60), verify=verify,
                                    headers={"User-Agent": UA, "Accept": "text/html, application/pdf, */*"})
            return r, verify
        except Exception as exc:
            last = exc
    return last, None


def pdf_to_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages[:80]:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        text = "\n".join(parts)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    except Exception as exc:
        log.info("pdf extract fail: %s", exc)
        return ""


def fetch_url_content(url: str) -> tuple[str, str, str]:
    """Return (text, source_url, kind)."""
    r, verify = try_get(url)
    if hasattr(r, "status_code") and r.status_code == 200 and r.content:
        if r.content[:5] == b"%PDF-":
            text = pdf_to_text(r.content)
            return text, url, "pdf_live"
        text = html_to_text(r.text if isinstance(getattr(r, "text", None), str) else r.content.decode("utf-8", "replace"))
        return text, url, "html_live"
    # archive fallbacks (official URL only)
    try:
        res = af.fetch_with_fallbacks(url, try_archive_is=False, try_http=False, try_cc=True)
        if isinstance(res, dict) and res.get("status") == "success":
            content = res.get("content")
            if isinstance(content, bytes) and content[:5] == b"%PDF-":
                return pdf_to_text(content), res.get("url") or url, "pdf_archive"
            raw = res.get("text") or ""
            if not raw and isinstance(content, bytes):
                raw = content.decode("utf-8", "replace")
            text = html_to_text(raw) if "<" in (raw[:200] or "") else raw
            return text, res.get("url") or url, "html_archive"
    except Exception as exc:
        log.info("archive fallback %s: %s", url[:60], exc)
    try:
        hits = af.search_wayback_machine(url, limit=5)
        for h in hits or []:
            w = af.get_wayback_content(h.get("original") or url, timestamp=h.get("timestamp"))
            if w.get("status") != "success":
                continue
            content = w.get("content")
            if isinstance(content, bytes) and content[:5] == b"%PDF-":
                return pdf_to_text(content), w.get("url") or url, "pdf_wayback"
            raw = w.get("text") or (content.decode("utf-8", "replace") if isinstance(content, bytes) else "")
            text = html_to_text(raw) if "<" in (raw[:200] or "") else raw
            if len(text) >= 80:
                return text, w.get("url") or url, "html_wayback"
    except Exception as exc:
        log.info("wayback %s: %s", url[:60], exc)
    return "", url, "none"


def main():
    setup(); t0 = utcnow()
    max_new = int(os.environ.get("MAX_NEW", "0") or 0)
    max_seconds = int(os.environ.get("MAX_SECONDS", "0") or 0)
    t_start = time.time()
    notes = []
    items = []
    seeds = [
        "https://www.mof.gov.cy/mof/gpo/gazette.nsf/officialgazette-el/officialgazette-el?OpenDocument",
        "https://www.mof.gov.cy/mof/gpo/gazette.nsf/dmlgaz_NEW_gr/dmlgaz_NEW_gr?OpenDocument",
        "https://www.mof.gov.cy/mof/gpo/gpo.nsf/index_gr/index_gr?OpenDocument",
        "https://www.mof.gov.cy/mof/gpo/gazette.nsf/dmlgaz_app_gr/dmlgaz_app_gr?OpenDocument",
        "https://www.gov.cy/en/service/episimi-efimerida-tis-dimokratias/",
    ]
    # CDX discovery for official GPO PDFs / gazette pages
    for pat in [
        "https://www.mof.gov.cy/mof/gpo/gazette.nsf/*",
        "https://www.mof.gov.cy/mof/gpo/*.pdf",
    ]:
        try:
            hits = af.search_wayback_machine(pat, limit=200, match_type="prefix")
            for h in hits or []:
                u = (h.get("original") or "").strip()
                if u and ("gazette" in u.lower() or u.lower().endswith(".pdf") or "$file" in u.lower()):
                    items.append(u)
            notes.append(f"cdx {pat} hits={len(hits or [])}")
        except Exception as exc:
            notes.append(f"cdx {pat} ERROR {exc}")

    for url in seeds:
        r, verify = try_get(url)
        if not hasattr(r, "status_code"):
            notes.append(f"seed {url} ERROR {r}")
            # still try archive of seed
            try:
                hits = af.search_wayback_machine(url, limit=3)
                for h in hits or []:
                    w = af.get_wayback_content(h.get("original") or url, timestamp=h.get("timestamp"))
                    raw = w.get("text") or ""
                    if not raw and isinstance(w.get("content"), bytes):
                        raw = w["content"].decode("utf-8", "replace")
                    for href in re.findall(r'href="([^"]+)"', raw):
                        href = urljoin(url, href)
                        if any(x in href.lower() for x in (".pdf", "gazette", "opendocument", "$file")):
                            items.append(href)
            except Exception as exc:
                notes.append(f"seed archive {url} ERROR {exc}")
            continue
        notes.append(f"seed {url} -> HTTP {r.status_code} bytes={len(r.content or b'')} verify={verify}")
        (ROOT / CC / "raw" / (re.sub(r"[^a-z0-9]+", "_", url)[:90] + ".bin")).write_bytes((r.content or b"")[:25000])
        if r.status_code == 200 and r.content:
            for href in re.findall(r'href="([^"]+)"', r.text):
                href = urljoin(url, href)
                if any(x in href.lower() for x in (".pdf", "gazette", "opendocument", "$file")):
                    items.append(href)

    done = existing_ids(CC); ok = skip = fail = 0
    seen = set(); uniq = []
    for h in items:
        if h in seen or "cylaw.org" in h.lower():
            continue
        seen.add(h); uniq.append(h)
    log.info("unique candidates %s", len(uniq))
    for href in uniq[:400]:
        if max_new and ok >= max_new:
            break
        if max_seconds and (time.time() - t_start) > max_seconds:
            break
        ident = re.sub(r"^https?://", "", href)
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1; continue
        text, src, kind = fetch_url_content(href)
        if len(text) < 80:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": href, "status": "failed", "reason": f"empty_{kind}"})
            continue
        title = ident
        # prefer first non-empty line
        for line in text.splitlines():
            if len(line.strip()) > 12:
                title = line.strip()[:240]; break
        rec = base_record(cc=CC, country=COUNTRY, language="el", ident=ident, title=title, text=text,
                          source_url=src, source_type=SOURCE_TYPE, license_text=LICENSE,
                          collector="cy-gpo-gazette-pdf", eli=None, date=None, official_identifier=ident,
                          document_type="gazette", law_status="unknown", is_current=None,
                          extra_meta={"discovery": {"backend": kind, "original_url": href}})
        write_instrument(CC, rec); ok += 1; done.add(rid)
        log.info("ok %s kind=%s chars=%s", rid[:60], kind, len(text))
    if not ok:
        notes.append(
            "Blocker: legislation.gov.cy NXDOMAIN; GPO TLS incomplete chain. "
            "cylaw.org unofficial — not used. Tried live+verify=False, Wayback/CC, PDF extract."
        )
    write_summary(CC, country=COUNTRY, source="Cyprus Government Printing Office gazette",
                  source_urls=["https://www.mof.gov.cy/mof/gpo/gazette.nsf/officialgazette-el/officialgazette-el?OpenDocument",
                               "https://www.gov.cy/en/service/episimi-efimerida-tis-dimokratias/"],
                  license_text=LICENSE, discovered=len(uniq), fetched=ok, skipped=skip, failed=fail,
                  coverage="catalog-backed incomplete", notes="\n".join(notes), last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s fail=%s", len(uniq), ok, fail)


if __name__ == "__main__":
    main()
