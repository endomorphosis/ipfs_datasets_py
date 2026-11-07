#!/usr/bin/env python3
"""Cyprus: official GPO gazette (mof.gov.cy). PDF body extraction. Not cylaw.org."""
from __future__ import annotations
import io, json, logging, os, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC, COUNTRY, SOURCE_TYPE = "cy", "Cyprus", "gpo_gazette"
LICENSE = "Official Gazette of the Republic of Cyprus, Government Printing Office (mof.gov.cy/gpo). cylaw.org is unofficial and is NOT used."
UA = DEFAULT_UA + " source=https://www.mof.gov.cy/mof/gpo/"
log = logging.getLogger("cy")

ASSET_RE = re.compile(r"\.(css|js|png|jpe?g|gif|svg|ico|woff2?|ttf|map)(\?|$)", re.I)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])



def known_fail_keys() -> set[str]:
    """Skip identifiers / URL keys that already failed empty extracts this session history."""
    out = set()
    fp = ROOT / CC / "failures.jsonl"
    if not fp.exists():
        return out
    for line in fp.open(encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        ident = str(d.get("identifier") or "")
        url = str(d.get("source_url") or "")
        if ident:
            out.add(ident.lower())
        if url:
            out.add(unquote(url).lower())
    return out


def try_get(url, verify_first=True):
    last = None
    order = (True, False) if verify_first else (False, True)
    for verify in order:
        try:
            time.sleep(0.35)
            r = get_session(UA).get(url, timeout=(5, 15), verify=verify,
                                    headers={"User-Agent": UA, "Accept": "text/html, application/pdf, */*"})
            return r, verify
        except Exception as exc:
            last = exc
    return last, None


def pdf_to_text(data: bytes) -> str:
    """Extract PDF text; prefer pdfplumber (ipfs_datasets_py IntegratedPDFProcessor path)."""
    # 1) pdfplumber — same primary backend as IntegratedPDFProcessor._extract_text_from_pdf
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            parts = []
            for page in pdf.pages[:120]:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    continue
            text = "\n".join(parts)
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if len(text) >= 40:
                return text
    except Exception as exc:
        log.info("pdfplumber fail: %s", exc)
    # 2) pypdf fallback
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages[:120]:
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


def is_gazette_pdf_url(url: str) -> bool:
    u = (url or "").lower()
    if "cylaw.org" in u:
        return False
    if ASSET_RE.search(u):
        return False
    uq = unquote(u)
    if ("$file/" in uq or "%24file/" in u) and (uq.rstrip().endswith(".pdf") or ".pdf" in uq):
        if "mof.gov.cy" in u and "gpo" in u:
            return True
    if uq.rstrip().endswith(".pdf") and "mof.gov.cy" in u and "gpo" in u:
        return True
    return False


def fetch_pdf(url: str, ts: str = "", *, prefer_wayback: bool = False) -> tuple[str, str, str]:
    """Return (text, source_url, kind). When CDX ts known, try Wayback first to avoid live hangs."""
    def _live():
        r, verify = try_get(url, verify_first=False)
        if hasattr(r, "status_code") and r.status_code == 200 and r.content and r.content[:5] == b"%PDF-":
            text = pdf_to_text(r.content)
            if len(text) >= 80:
                return text, url, "pdf_live"
        return None

    def _wb(ts_in: str):
        try:
            t = ts_in
            u = url
            if not t:
                hits = af.search_wayback_machine(u, limit=1, collapse="")
                if hits:
                    t = hits[0].get("timestamp") or ""
                    u = hits[0].get("original") or u
            if not t:
                return None
            w = af.get_wayback_content(u, timestamp=t)
            if w.get("status") == "success":
                content = w.get("content")
                if isinstance(content, bytes) and content[:5] == b"%PDF-":
                    text = pdf_to_text(content)
                    if len(text) >= 80:
                        return text, w.get("url") or u, "pdf_wayback"
        except Exception as exc:
            log.info("wayback pdf %s: %s", url[-50:], exc)
        return None

    # Live mof.gov.cy often hangs; when CDX ts is known, Wayback-only.
    if prefer_wayback and ts:
        got = _wb(ts)
        if got:
            return got
        return "", url, "none"
    for fn in (_live, _wb):
        got = fn(ts) if fn is _wb else _live()
        if got:
            return got
    return "", url, "none"


def cdx_pdf_candidates(limit: int = 400) -> list[tuple[str, str]]:
    """Return list of (url, timestamp) for official GPO gazette PDFs via Wayback CDX."""
    out, seen = [], set()
    # Direct CDX with mime filter — more reliable than generic helper for Domino $file PDFs
    import requests
    params = {
        "url": "www.mof.gov.cy/mof/gpo/gazette.nsf/*",
        "output": "json",
        "fl": "timestamp,original,mimetype,statuscode",
        "filter": ["mimetype:application/pdf", "statuscode:200"],
        "collapse": "urlkey",
        "limit": str(limit),
    }
    try:
        import json
        q = [
            ("url", "www.mof.gov.cy/mof/gpo/gazette.nsf/*"),
            ("output", "json"),
            ("fl", "timestamp,original,mimetype,statuscode"),
            ("filter", "mimetype:application/pdf"),
            ("filter", "statuscode:200"),
            ("collapse", "urlkey"),
            ("limit", str(limit)),
        ]
        last = None
        for attempt in range(1, 5):
            time.sleep(0.6 * attempt)
            r = requests.get("https://web.archive.org/cdx/search/cdx", params=q, timeout=(20, 120),
                             headers={"User-Agent": UA})
            last = r
            if r.status_code == 200 and r.content and r.content[:1] == b"[":
                rows = json.loads(r.content)
                for row in rows[1:]:
                    ts, orig = row[0], row[1]
                    if not is_gazette_pdf_url(orig):
                        continue
                    key = unquote(orig).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append((orig, ts))
                log.info("cdx mime-pdf unique=%s", len(out))
                break
            log.info("cdx attempt %s HTTP %s", attempt, getattr(r, "status_code", "?"))
            time.sleep(2 * attempt)
        else:
            log.info("cdx direct exhausted last=%s", getattr(last, "status_code", last))
    except Exception as exc:
        log.info("cdx direct fail: %s", exc)
    if len(out) < 20:
        # fallback via helper + $file filter
        try:
            hits = af.search_wayback_machine(
                "www.mof.gov.cy/mof/gpo/gazette.nsf/*", limit=limit, match_type="prefix", collapse="urlkey"
            )
            for h in hits or []:
                u = (h.get("original") or "").strip()
                if not is_gazette_pdf_url(u):
                    continue
                key = unquote(u).lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append((u, h.get("timestamp") or ""))
            log.info("cdx helper pdf unique=%s", len(out))
        except Exception as exc:
            log.info("cdx helper fail: %s", exc)
    out.sort(key=lambda x: x[1] or "", reverse=True)
    return out


def main():
    setup(); t0 = utcnow()
    max_new = int(os.environ.get("MAX_NEW", "0") or 0)
    max_seconds = int(os.environ.get("MAX_SECONDS", "0") or 0)
    t_start = time.time()
    notes = ["PDF-focused CDX of official GPO gazette.nsf $file URLs. cylaw.org not used."]
    cands = cdx_pdf_candidates(int(os.environ.get("MAX_CATALOG", "400") or 400))
    # Also scrape live listing pages for any $file PDF hrefs
    seeds = [
        "https://www.mof.gov.cy/mof/gpo/gazette.nsf/dmlgaz_NEW_gr/dmlgaz_NEW_gr?OpenDocument",
        "https://www.mof.gov.cy/mof/gpo/gazette.nsf/dmlgaz_app_gr/dmlgaz_app_gr?OpenDocument",
        "https://www.mof.gov.cy/mof/gpo/gazette.nsf/dmlgazette_archive_gr/dmlgazette_archive_gr?OpenForm",
        "https://www.mof.gov.cy/mof/gpo/gazette.nsf/officialgazette-el/officialgazette-el?OpenDocument",
    ]
    seen = {unquote(u).lower() for u, _ in cands}
    for url in seeds:
        r, verify = try_get(url, verify_first=False)
        if not hasattr(r, "status_code"):
            notes.append(f"seed {url} ERROR {r}")
            continue
        notes.append(f"seed {url} -> HTTP {r.status_code} bytes={len(r.content or b'')} verify={verify}")
        if r.status_code == 200 and r.content:
            for href in re.findall(r'href=["\']([^"\']+)["\']', r.text, flags=re.I):
                href = urljoin(url, href)
                if is_gazette_pdf_url(href) and unquote(href).lower() not in seen:
                    seen.add(unquote(href).lower())
                    cands.append((href, ""))
    log.info("pdf candidates %s", len(cands))
    done = existing_ids(CC); ok = skip = fail = 0
    known_fail = known_fail_keys()
    log.info("known_fail keys=%s", len(known_fail))
    for href, ts in cands:
        if max_new and ok >= max_new:
            break
        if max_seconds and (time.time() - t_start) > max_seconds:
            break
        ident = re.sub(r"^https?://", "", href)
        # Prefer filename as stable id when Domino $file present
        m = re.search(r"\$file/([^/?#]+)", href, re.I)
        if m:
            ident = "gpo-pdf-" + unquote(m.group(1))
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        if ident.lower() in known_fail or unquote(href).lower() in known_fail:
            skip += 1
            continue
        log.info("try %s ts=%s", ident[:80], (ts or "")[:14])
        text, src, kind = fetch_pdf(href, ts, prefer_wayback=bool(ts))
        if len(text) < 80:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": href, "status": "failed", "reason": f"empty_{kind}"})
            log.info("fail %s kind=%s", ident[:70], kind)
            continue
        title = unquote(m.group(1)) if m else ident
        for line in text.splitlines():
            if len(line.strip()) > 12:
                title = line.strip()[:240]
                break
        rec = base_record(
            cc=CC, country=COUNTRY, language="el", ident=ident, title=title, text=text,
            source_url=src, source_type=SOURCE_TYPE, license_text=LICENSE,
            collector="cy-gpo-gazette-pdf", eli=None, date=None, official_identifier=ident,
            document_type="gazette_pdf", law_status="unknown", is_current=None,
            documents=[],  # whole-issue PDFs; no honest per-article split from structure
            extra_meta={"discovery": {"backend": kind, "original_url": href, "wayback_ts": ts,
                                      "article_note": "whole_issue_pdf_articles_0"}},
        )
        write_instrument(CC, rec); ok += 1; done.add(rid)
        log.info("ok %s kind=%s chars=%s", rid[:70], kind, len(text))
        if ok and ok % 10 == 0:
            write_summary(CC, country=COUNTRY, source="Cyprus GPO gazette PDFs",
                          source_urls=["https://www.mof.gov.cy/mof/gpo/gazette.nsf/"],
                          license_text=LICENSE, discovered=len(cands), fetched=ok, skipped=skip, failed=fail,
                          coverage="shard", notes="\n".join(notes), last_run=utcnow())
    if not ok:
        notes.append(
            "Blocker: few/no extractable PDF bodies this run. legislation.gov.cy NXDOMAIN; "
            "GPO TLS incomplete chain; cylaw.org forbidden. Used Wayback CDX of official $file PDFs."
        )
    write_summary(CC, country=COUNTRY, source="Cyprus Government Printing Office gazette PDFs",
                  source_urls=["https://www.mof.gov.cy/mof/gpo/gazette.nsf/officialgazette-el/officialgazette-el?OpenDocument",
                               "https://www.gov.cy/en/service/episimi-efimerida-tis-dimokratias/"],
                  license_text=LICENSE, discovered=len(cands), fetched=ok, skipped=skip, failed=fail,
                  coverage="catalog-backed incomplete", notes="\n".join(notes), last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s fail=%s skip=%s", len(cands), ok, fail, skip)


if __name__ == "__main__":
    main()
