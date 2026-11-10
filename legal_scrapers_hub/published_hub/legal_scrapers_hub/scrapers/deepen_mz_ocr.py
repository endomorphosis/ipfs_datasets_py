#!/usr/bin/env python3
"""Re-OCR Mozambique image-only / Pandora-watermark PDFs; expand Parlamento harvest.
No Ubercart/WAF bypass. No HF upload.
"""
from __future__ import annotations
import json, logging, os, re, sys, time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, existing_ids, log_failure, utcnow, write_summary
from world_lib import env_int, save_instrument, setup_log, slug_id
import collect_mz as mz

log = logging.getLogger("mz_ocr")
PANDORA = re.compile(r"pandora\s*box|scanned by camscanner", re.I)


def needs_ocr(rec: dict) -> bool:
    text = rec.get("text") or ""
    title = rec.get("title") or ""
    docs = rec.get("documents") or []
    if PANDORA.search(text[:500]) or PANDORA.search(title):
        return True
    if "Scanned by CamScanner" in text[:200]:
        return True
    # watermark-only short extracts
    if len(text) < 2500 and len(docs) == 0 and "Edição" in text[:80]:
        return True
    if text.lstrip().startswith("%") and len(docs) == 0:
        return True
    return False


def reocr_existing(done: set) -> tuple[int, int, int]:
    instr = ROOT / "mz" / "instruments"
    ok = fail = skip = 0
    max_n = env_int("MAX_OCR", 40)
    t0 = time.time()
    max_seconds = env_int("MAX_SECONDS", 7200)
    os.environ.setdefault("OCR", "1")
    for p in sorted(instr.glob("*.json")):
        if ok >= max_n:
            break
        if time.time() - t0 > max_seconds:
            break
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta0 = rec.get("metadata") or {}
        if "ocr" in str(meta0.get("fetch_method") or ""):
            skip += 1
            continue
        if not needs_ocr(rec):
            skip += 1
            continue
        url = rec.get("source_url") or ""
        if not url:
            skip += 1
            continue
        ident = rec.get("identifier") or p.stem.replace("mz-", "", 1)
        log.info("ocr retry %s", ident[:70])
        got = mz.fetch_mz(url)
        text = got.get("text") or ""
        method = got.get("method") or ""
        if got.get("status") != "success" or len(text) < 200:
            fail += 1
            log_failure("mz", {"identifier": ident, "source_url": url,
                               "reason": got.get("error") or "ocr_fail", "phase": "reocr"})
            continue
        title = mz._title_from_text(text, rec.get("title") or ident)
        if "+ocr" not in method and needs_ocr({"text": text, "title": title, "documents": []}):
            fail += 1
            log_failure("mz", {"identifier": ident, "source_url": url,
                               "reason": "still_watermark_no_ocr", "phase": "reocr", "method": method})
            continue
        portal = ((rec.get("metadata") or {}).get("portal")) or "mireme.gov.mz"
        if save_instrument(
            cc="mz", country=mz.COUNTRY, language=mz.LANG, ident=ident, title=title,
            text=text, source_url=url, source_type=mz.SOURCE_TYPE, license_text=mz.LICENSE,
            collector="collect_mz.py", article_re=mz.ART,
            extra_meta={"fetch_method": method, "portal": portal, "reocr": True},
        ):
            ok += 1
            done.add(slug_id("mz", ident))
            n_docs = len(json.loads((ROOT / "mz" / "instruments" / f"{slug_id('mz', ident)}.json").read_text()).get("documents") or [])
            log.info("reocr ok %s chars=%s arts=%s method=%s", ident[:60], len(text), n_docs, method)
        else:
            fail += 1
    return ok, skip, fail


def harvest_new(done: set) -> tuple[int, int, int]:
    os.environ.setdefault("OCR", "1")
    os.environ.setdefault("FORCE_CDX", "1")
    max_new = env_int("MAX_NEW", 60)
    max_seconds = env_int("MAX_SECONDS", 7200)
    t0 = time.time()
    ok = skip = fail = 0
    # expand parlamento page set for deepen
    extra_pages = [
        989, 2940, 2969, 2977, 1009, 15236, 12718, 12967, 12776, 4569,
        15237, 15238, 1008, 1010, 2950, 3000, 3100,
    ]
    # temporarily extend
    mz.PARL_PAGES = tuple(dict.fromkeys(list(mz.PARL_PAGES) + extra_pages))
    for ident, url, meta in mz.discover():
        if ok >= max_new:
            break
        if time.time() - t0 > max_seconds:
            break
        rid = slug_id("mz", ident)
        if rid in done:
            skip += 1
            continue
        # prefer parlamento / new hosts during deepen
        portal = (meta or {}).get("portal") or ""
        got = mz.fetch_mz(url)
        text = got.get("text") or ""
        method = got.get("method") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure("mz", {"identifier": ident, "source_url": url,
                               "reason": got.get("error"), "portal": portal, "phase": "new"})
            continue
        if PANDORA.search(text) and len(text) < 2500:
            fail += 1
            continue
        title = (meta.get("title") or "").strip() or mz._title_from_text(text, ident)
        if save_instrument(
            cc="mz", country=mz.COUNTRY, language=mz.LANG, ident=ident, title=title,
            text=text, source_url=url, source_type=mz.SOURCE_TYPE, license_text=mz.LICENSE,
            collector="collect_mz.py", article_re=mz.ART,
            extra_meta={"fetch_method": method, "portal": portal or "unknown", "deepen": True},
        ):
            ok += 1
            done.add(rid)
            log.info("new ok %s portal=%s chars=%s method=%s", ident[:60], portal, len(text), method)
        else:
            fail += 1
    return ok, skip, fail


def main():
    setup_log("mz", "mz_ocr")
    t0 = utcnow()
    done = existing_ids("mz")
    r_ok, r_skip, r_fail = reocr_existing(done)
    n_ok, n_skip, n_fail = harvest_new(done)
    write_summary(
        "mz",
        country=mz.COUNTRY,
        source="Boletim da República / MIREME / Parlamento (Moçambique)",
        source_urls=[
            "https://www.inm.gov.mz/",
            "https://mireme.gov.mz/documentos/legislacao/",
            "https://www.parlamento.mz/",
            "https://www.bancomoc.mz/pt/o-banco/normativos/",
        ],
        license_text=mz.LICENSE,
        discovered=r_ok + n_ok + r_skip + n_skip + r_fail + n_fail,
        fetched=r_ok + n_ok,
        skipped=r_skip + n_skip,
        failed=r_fail + n_fail,
        coverage=(
            "catalog-backed incomplete; INM Ubercart-paywalled — "
            "MIREME + Parlamento official PDFs; OCR deepen for scans"
        ),
        notes=(
            f"Deepen OCR reocr_ok={r_ok} new_ok={n_ok} "
            f"reocr_fail={r_fail} new_fail={n_fail}. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done reocr=%s new=%s", r_ok, n_ok)


if __name__ == "__main__":
    main()
