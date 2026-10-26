#!/usr/bin/env python3
"""Azerbaijan: e-qanun.az downloadDetailPdf (non-SPA PDF path) + Wayback + ID probe."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "az", "Azerbaijan", "az"
SOURCE_TYPE = "eqanun_pdf"
LICENSE = (
    "Electronic database of normative legal acts of the Republic of Azerbaijan "
    "(e-qanun.az). Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://e-qanun.az/)"
ART = re.compile(r"(?im)^\s*((?:Maddə|Madde|Article|Art\.?)\s+[0-9]+)\b")
log = logging.getLogger("az")


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0].replace("http://", "https://")
        if url in seen or "downloadDetailPdf" not in url:
            return
        # normalize .../downloadDetailPdf/12345
        m = re.search(r"downloadDetailPdf/(\d+)", url)
        if not m:
            return
        ident = m.group(1)
        url = f"https://e-qanun.az/downloadDetailPdf/{ident}"
        if url in seen:
            return
        seen.add(url)
        items.append((f"eqanun-{ident}", url))
    for prefix in (
        "e-qanun.az/downloadDetailPdf/",
        "www.e-qanun.az/downloadDetailPdf/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 400), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            orig = h.get("original") or ""
            if orig:
                add(orig)
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 300), match_type="prefix"):
            orig = h.get("original") or ""
            if orig and "downloadDetailPdf" in orig:
                add(orig)
    # Probe numeric ID ranges (official path; live may 404 — fetch_official falls to Wayback)
    id_lo = env_int("ID_START", 1)
    id_hi = env_int("ID_END", 8000)
    id_step = env_int("ID_STEP", 1)
    # Prefer denser sampling of known-good bands from CDX hits
    known = sorted(int(i.split("-")[1]) for i, _ in items if i.split("-")[-1].isdigit())
    if known:
        # expand around known IDs ±50
        for kid in known:
            for d in range(-30, 31):
                nid = kid + d
                if nid > 0:
                    add(f"https://e-qanun.az/downloadDetailPdf/{nid}")
    # sparse probe across range if still thin
    if len(items) < env_int("MIN_CATALOG", 500):
        step = max(id_step, max(1, (id_hi - id_lo) // 2000))
        for nid in range(id_lo, id_hi + 1, step):
            add(f"https://e-qanun.az/downloadDetailPdf/{nid}")
    log.info("catalog %s (cdx+probe)", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 200)
    max_seconds = env_int("MAX_SECONDS", 7200)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for ident, url in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        if __import__('os').environ.get('SKIP_LIVE','').strip() in ('1','true','yes'):
            import archive_fallbacks as af
            from world_lib import pdf_to_text
            got={'status':'error','text':'','method':'','error':''}
            try:
                w=af.get_wayback_content(url)
                body=w.get('content') or b''
                if w.get('status')=='success' and body[:4]==b'%PDF':
                    text=pdf_to_text(body)
                    if len(text)>=150:
                        got={'status':'success','text':text,'method':'wayback_pdf','error':''}
                    else:
                        got['error']='pdf_short'
                else:
                    got['error']=w.get('error') or 'wayback_fail'
            except Exception as exc:
                got['error']=str(exc)
        else:
            got = fetch_official(url, ua=UA, verify=False, min_text=150)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_az.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="e-qanun.az",
        source_urls=["https://e-qanun.az/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (downloadDetailPdf; framework SPA skipped)",
        notes="Official e-qanun PDF downloads via live/Wayback + ID probe. SPA HTML skipped. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
