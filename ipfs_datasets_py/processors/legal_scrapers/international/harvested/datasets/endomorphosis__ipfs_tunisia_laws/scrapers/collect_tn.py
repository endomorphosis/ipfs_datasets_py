#!/usr/bin/env python3
"""Tunisia: Journal Officiel (IORT / JORT).

Live iort.gov.tn TLS often fails; legislation.tn often 503.
Primary harvest: official gazette PDFs mirrored at lake.jort.tn (synced from
iort.tn) and extractable French OCR markdown at ocr.jort.tn.
Wayback of official legislation.tn / iort.gov.tn URLs remains secondary.
No WAF bypass. Not legal advice.
"""
from __future__ import annotations
import json, logging, re, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "tn", "Tunisia", "ar"
SOURCE_TYPE = "iort_jo"
LICENSE = (
    "Journal Officiel de la République Tunisienne (IORT / iort.tn). "
    "Arabic authentic; French informative (loi 93-64). Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.iort.tn/)"
ART = re.compile(r"(?im)^\s*((?:الفصل|Article|Art\.?)\s+[0-9]+[A-Za-z]?)\b")
JUNK_HTML = re.compile(
    r"(La session n'existe plus|contexte auquel cette requ|"
    r"ERR_DISCONNECTED|Vous avez été déconnecté|Relancer l'application|"
    r"WD120Awp\.exe)",
    re.I,
)
log = logging.getLogger("tn")


def quarantine_junk() -> int:
    instr = ROOT / CC / "instruments"
    q = ROOT / CC / "quarantine_nonlaws"
    q.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in list(instr.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        url = (rec.get("source_url") or "").lower()
        rid = (rec.get("id") or p.stem).lower()
        drop = False
        if url.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            drop = True
        if "wd120awp" in url or "wd120awp" in rid:
            drop = True
        if JUNK_HTML.search(text[:800]):
            drop = True
        if len(text) < 250 and ("session" in text.lower() or "requête" in text.lower()):
            drop = True
        # OCR garbage: very high symbol ratio, almost no Arabic/Latin letters
        letters = sum(1 for c in text[:2000] if c.isalpha())
        if len(text) > 800 and letters < max(40, len(text[:2000]) * 0.08):
            # keep if already has honest article splits; else quarantine weak OCR
            if not (rec.get("documents") or []):
                drop = True
        if drop:
            shutil.move(str(p), str(q / p.name))
            n += 1
            log.info("quarantine %s", p.name)
    return n


def discover_jort_lake():
    """Official gazette issues via index.jort.tn (PDFs synced from iort.tn)."""
    items = []
    year_from = env_int("JORT_YEAR_FROM", 2018)
    year_to = env_int("JORT_YEAR_TO", 2026)
    prefer_ocr = env_int("JORT_PREFER_OCR", 1)
    max_per_year = env_int("JORT_MAX_PER_YEAR", 40)
    try:
        r = live_get("https://index.jort.tn/", ua=UA, verify=False, retries=2)
        idx = r.json()
    except Exception as exc:
        log.warning("jort index fail: %s", exc)
        return items
    jo = None
    for c in idx.get("collections") or []:
        if c.get("id") == "journal-officiel":
            jo = c
            break
    if not jo:
        return items
    years = jo.get("years") or {}
    for year in sorted(years.keys(), reverse=True):
        try:
            y = int(year)
        except Exception:
            continue
        if y < year_from or y > year_to:
            continue
        counts = years[year] or {}
        # Prefer French OCR (extractable); Arabic PDF secondary if needed
        fr_n = int(counts.get("fr") or 0)
        ar_n = int(counts.get("ar") or 0)
        # harvest newest issues first within year
        n_fr = min(fr_n, max_per_year)
        for i in range(fr_n, max(0, fr_n - n_fr), -1):
            issue = f"{i:03d}"
            if prefer_ocr:
                md = f"https://ocr.jort.tn/journal-officiel/fr/{year}/{issue}.md"
                items.append((f"jort-fr-{year}-{issue}-md", md, "ocr_md"))
            pdf = f"https://lake.jort.tn/journal-officiel/fr/{year}/{issue}.pdf"
            items.append((f"jort-fr-{year}-{issue}", pdf, "pdf"))
        # a smaller Arabic PDF sample for authenticity (Arabic prevails)
        n_ar = min(ar_n, max(8, max_per_year // 4))
        for i in range(ar_n, max(0, ar_n - n_ar), -1):
            issue = f"{i:03d}"
            pdf = f"https://lake.jort.tn/journal-officiel/ar/{year}/{issue}.pdf"
            items.append((f"jort-ar-{year}-{issue}", pdf, "pdf"))
    log.info("jort lake catalog %s", len(items))
    return items


def discover_legislation_cdx():
    items = []
    for prefix in (
        "www.legislation.tn/sites/default/files/",
        "legislation.tn/sites/default/files/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 120), match_type="prefix"):
            orig = h.get("original") or ""
            low = orig.lower()
            if not orig or not low.endswith(".pdf"):
                continue
            # skip obvious non-law attachments
            if any(k in low for k in ("deed_of_covenant", "image", ".png", "photo")):
                continue
            ident = re.sub(r"^https?://[^/]+/", "", orig).replace("/", "-")[:160]
            items.append((ident, orig, "cdx_pdf"))
    log.info("legislation cdx %s", len(items))
    return items


def discover():
    # Prefer lake OCR/PDF first, then CDX
    lake = discover_jort_lake()
    cdx = discover_legislation_cdx()
    seen = set()
    out = []
    for ident, url, kind in lake + cdx:
        key = url.lower().split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append((ident, url, kind))
    log.info("catalog %s", len(out))
    return out


def fetch_item(url: str, kind: str) -> dict:
    if kind == "ocr_md" or url.endswith(".md"):
        try:
            r = live_get(url, ua=UA, verify=False, retries=2)
            if r.status_code == 200 and r.text and len(r.text) >= 120:
                text = r.text
                # strip page markers noise lightly
                if "Journal Officiel" in text or "Article" in text or "Art." in text:
                    return {"status": "success", "text": text, "method": "jort_ocr_md", "error": ""}
            return {"status": "error", "text": "", "method": "", "error": f"md_{getattr(r,'status_code', '?')}"}
        except Exception as exc:
            return {"status": "error", "text": "", "method": "", "error": f"md:{exc}"}
    return fetch_official(url, ua=UA, verify=False, min_text=200)


def is_junk_text(text: str) -> bool:
    if not text or len(text) < 120:
        return True
    if JUNK_HTML.search(text[:1000]):
        return True
    letters = sum(1 for c in text[:2500] if c.isalpha())
    if letters < 50:
        return True
    return False


def main():
    setup_log(CC)
    t0 = utcnow()
    qn = quarantine_junk()
    log.info("quarantined %s", qn)
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for ident, url, kind in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        # Prefer OCR md: if PDF twin already saved for same issue, still allow md
        got = fetch_item(url, kind)
        text = got.get("text") or ""
        if got.get("status") != "success" or is_junk_text(text):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error") or "junk"})
            continue
        title = None
        for line in text.splitlines():
            s = line.strip().lstrip("#").strip()
            if len(s) > 12 and "Signature numérique" not in s and "page:" not in s.lower():
                title = s[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_tn.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method") or kind},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s bytes=%s", ident[:70], got.get("method") or kind, len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="IORT Journal Officiel (lake.jort.tn / ocr.jort.tn synced from iort.tn)",
        source_urls=[
            "https://www.iort.tn/",
            "https://lake.jort.tn/",
            "https://ocr.jort.tn/",
            "http://www.legislation.tn/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (JORT lake OCR/PDF + legislation.tn Wayback)",
        notes=(
            "Live iort.gov.tn TLS often fails; legislation.tn often 503. "
            "Harvest uses official gazette PDFs mirrored from iort.tn at lake.jort.tn "
            "and extractable French OCR at ocr.jort.tn. Arabic authentic. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
