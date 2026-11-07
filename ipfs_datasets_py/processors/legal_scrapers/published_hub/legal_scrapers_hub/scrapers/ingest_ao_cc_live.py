#!/usr/bin/env python3
"""Live-ingest AO PDFs discovered via Common Crawl URL list.

Prefer live official fetch (fetch_official with wayback=False). Skip WARC Range.
No Wayback CDX spam. OMP_THREAD_LIMIT=1.
"""
from __future__ import annotations
import json, logging, os, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, "/workspace/legal_scrapers/scrapers")
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import fetch_official, pdf_to_text, save_instrument, setup_log, slug_id
from collect_ao import (
    ART, CC, COUNTRY, LANG, LICENSE, SOURCE_TYPE,
    _ident_from_url, _lawish_fname, _title_from_text, _env_flag, pdf_ocr_text,
)

URLS_PATH = Path("/workspace/legal_scrapers/logs/ao_cc_urls.jsonl")
UA = "legal-corpora-collector/1.0 (research; source=https://www.imprensanacional.gov.ao/)"
ALLOWED = (
    "imprensanacional.gov.ao", "gue.gov.ao", "governo.gov.ao",
    "minfin.gov.ao", "plataformacipra.gov.ao", "portais.gov.ao", "minjusdh.gov.ao",
    "maptss.gov.ao", "minec.gov.ao", "mincom.gov.ao", "mirex.gov.ao",
    "mae.gov.ao", "mes.gov.ao", "minsa.gov.ao", "minamb.gov.ao",
    "mirempet.gov.ao", "mtti.gov.ao", "parlamento.ao", "assembleianacional.ao",
    "cij.gov.ao", "bna.ao", "tribunalconstitucional.ao",
)
MIN_TEXT = 150
log = logging.getLogger("ao_cc_live")


def host_ok(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return any(host == s or host.endswith("." + s) for s in ALLOWED)


def url_stem(url: str) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    if not name:
        parts = [p for p in path.strip("/").split("/") if p]
        name = parts[-1] if parts else "document"
    return name.strip() or "document"


def existing_stems() -> set[str]:
    stems: set[str] = set()
    d = Path("/workspace/legal-corpora/ao/instruments")
    for p in d.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for k in ("source_url", "url"):
            su = rec.get(k) or ""
            if su:
                stems.add(Path(unquote(urlparse(su).path)).name.lower())
                stems.add(url_stem(su).lower())
        stems.add((rec.get("id") or p.stem).lower())
    return stems


def is_lawish(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    stem_name = Path(unquote(urlparse(url).path)).name.lower()
    path = unquote(urlparse(url).path).lower()
    if _lawish_fname(stem_name or path, host):
        return True
    if "minfin.gov.ao" in host:
        if stem_name.endswith(".pdf") or "/edisp/" in path or "/api/assets/" in path:
            # drop obvious non-law reports later via title heuristics
            return True
    if "portais.gov.ao" in host and (
        stem_name.endswith(".pdf")
        or any(
            k in (stem_name + path)
            for k in ("decreto", "despacho", "lei", "regulament", "aviso", "estatuto", "codigo", "código", "legisl", "diploma", "portaria", "resolu")
        )
    ):
        return True
    if "plataformacipra" in host and ("gov_angola" in path or "legisl" in path):
        return True
    return False


def load_unique_urls() -> list[str]:
    seen = set()
    out = []
    if not URLS_PATH.exists():
        return out
    for line in URLS_PATH.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            u = json.loads(line).get("url") or ""
        except Exception:
            continue
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def main() -> None:
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    setup_log(CC)
    t0 = utcnow()
    max_new = int(os.environ.get("MAX_NEW", "80") or 40)
    target = int(os.environ.get("TARGET_LAWS", "420") or 420)
    max_seconds = int(os.environ.get("MAX_SECONDS", "7200") or 7200)
    allow_ocr = _env_flag("ALLOW_OCR", False) and not _env_flag("SKIP_OCR", True)
    done = existing_ids(CC)
    stems = existing_stems()
    urls = load_unique_urls()
    log.info("start urls=%s ids=%s stems=%s target=%s allow_ocr=%s", len(urls), len(done), len(stems), target, allow_ocr)
    ok = skip = fail = 0
    t_start = time.time()
    from common import ROOT
    corpus = lambda: sum(1 for _ in (ROOT / CC / "instruments").glob("*.json"))
    laws0 = corpus()

    for url in urls:
        if ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        if corpus() >= target and ok >= 1:
            log.info("target reached %s", corpus())
            break
        if not host_ok(url):
            skip += 1
            continue
        if not is_lawish(url):
            skip += 1
            continue
        # skip_guia: taxpayer how-tos are not legislation
        if "guia-rapido" in url.lower() or "guia_rapido" in url.lower():
            skip += 1
            continue
        bare = url_stem(url).lower()
        stem_name = Path(unquote(urlparse(url).path)).name.lower() or (bare + ".pdf")
        if stem_name in stems or bare in stems or bare + ".pdf" in stems:
            skip += 1
            continue
        ident = _ident_from_url(url if stem_name.endswith(".pdf") else url.rstrip("/") + "/" + bare + ".pdf")
        if not ident or ident in ("ao", "document"):
            ident = bare[:160]
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue

        # LIVE only — no Wayback (CDX 429)
        got = fetch_official(url, ua=UA, verify=False, wayback=False, min_text=MIN_TEXT)
        text = got.get("text") or ""
        method = got.get("method") or ""
        pdf = got.get("content") if isinstance(got.get("content"), (bytes, bytearray)) else b""
        # If fetch_official misclassified a PDF (short_or_spa), re-download once for OCR
        if len(text) < MIN_TEXT and allow_ocr and (not pdf or pdf[:4] != b"%PDF") and url.lower().endswith(".pdf"):
            try:
                import requests as _rq
                _rq.packages.urllib3.disable_warnings()
                rr = _rq.get(url, timeout=40, verify=False, headers={"User-Agent": UA})
                if rr.status_code == 200 and rr.content[:4] == b"%PDF":
                    pdf = rr.content
                    method = "http_pdf_redownload"
            except Exception as _e:
                log.info("redownload fail %s %s", url[:80], _e)
        if len(text) < MIN_TEXT and pdf and allow_ocr and pdf[:4] == b"%PDF":
            ocr = pdf_ocr_text(bytes(pdf))
            if len(ocr) >= MIN_TEXT:
                text = ocr
                method = (method or "live") + "+ocr"

        # drop obvious non-law financial reports if title screams report
        title_probe = (text[:400] if text else "").lower()
        if any(k in title_probe for k in ("relatório e\ncontas", "relatorio e contas", "relatório de contas")) and "lei" not in title_probe[:200]:
            # still allow if lei/decreto later? skip large enterprise reports
            if "parcerias" not in title_probe and "decreto" not in title_probe and "lei n" not in title_probe:
                log.info("skip_report %s", url[:90])
                skip += 1
                continue

        if len(text) < MIN_TEXT:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error") or "short", "portal": "cc_live"})
            log.info("fail %s err=%s", url[:90], got.get("error"))
            continue

        title = _title_from_text(text, ident.replace("-", " ")[:80])
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE,
            collector="ingest_ao_cc_live.py", article_re=ART,
            extra_meta={"fetch_method": method or "http_live", "discovery": "common_crawl_url_live"},
        ):
            ok += 1
            done.add(rid)
            stems.add(stem_name)
            stems.add(bare)
            stems.add(bare + ".pdf")
            log.info("ok %s method=%s corpus=%s", ident[:70], method, corpus())
        else:
            fail += 1
        time.sleep(0.4)

    laws = corpus()
    write_summary(
        CC, country=COUNTRY,
        source="Diário da República / Portal do Governo / GUE (Angola) + CC-discovered live PDFs",
        source_urls=[
            "https://www.imprensanacional.gov.ao/",
            "https://gue.gov.ao/portal/legislacao-portal",
            "https://governo.gov.ao/documentos/legislacao",
            "https://minfin.gov.ao/",
        ],
        license_text=LICENSE, discovered=len(urls), fetched=ok, skipped=skip, failed=fail,
        coverage="official-live-pdfs from CC URL harvest + prior",
        notes=f"ingest_ao_cc_live.py live-only. Before {laws0} after {laws}. Started {t0}.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s corpus=%s->%s", ok, skip, fail, laws0, laws)
    print(json.dumps({"ok": ok, "skip": skip, "fail": fail, "laws0": laws0, "laws": laws}, indent=2))


if __name__ == "__main__":
    main()
