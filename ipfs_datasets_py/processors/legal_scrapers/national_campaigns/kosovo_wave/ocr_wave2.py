#!/usr/bin/env python3
"""Kosovo OCR wave 2 — work the scanned-PDF queue left by the dedicated
Kosovo wave (2026-10-12/13).

Queue definition (from ../stats/attempts.jsonl, LATEST outcome per ActID):
result == pdf_short, text_len == 0, pdf_bytes >= 20000, minus ActIDs already
on HF (fresh dedupe in ../stats/baseline.json), already in the local corpus,
or already ok_ocr in ../stats/ocr_attempts.jsonl (timeouts/failures remain
candidates, per the wave-1 note).

Ordering rule: pdf_bytes DESCENDING — page counts are not known before
download, so PDF size is the substance proxy: multi-page laws/decisions
(large scans) before the numerous small 1-page notary notices.

Modes:
  retry-errors : one fresh download attempt for every ActID whose latest
                 attempts outcome is error/error_retry (the still-open
                 GZK read-timeout set). Digital text -> saved; scanned ->
                 recorded pdf_short (joins the OCR queue); still failing ->
                 recorded error_retry2 and left open.
  ocr          : the OCR pipeline over the queue in the order above.
                 Per act: download via collect_xk.download_act_pdf, cheap
                 digital-text guard (world_lib.pdf_to_text), else render
                 at 200 dpi (pdftoppm) and OCR pages with tesseract -l sqi
                 (tessdata in ../tessdata/), up to 2 pages concurrently
                 (2-core VM). Gate: >=300 chars and >=50% alphabetic.
                 Successes saved via world_lib.save_instrument with
                 fetch_method=aspnet_pdf_postback_ocr.

Checkpointing (same files/format as wave 1): every outcome appended to
../stats/ocr_attempts.jsonl; successes also appended to
../stats/attempts.jsonl as ok_ocr; progress snapshot rewritten per act to
../stats/ocr_wave2_progress.json. Safe to kill/resume.

Env: XK_OCR2_MAX (acts this run), XK_OCR2_MAX_SECONDS, XK_OCR2_MAX_PAGES
(default 50; longer deferred + recorded), XK_OCR2_PAGE_TIMEOUT (default 900).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.expanduser("~/workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers/national_collectors"))
import collect_xk
from common import existing_ids, slug_id
from world_lib import pdf_to_text, save_instrument, setup_log, env_int

WAVE = os.path.expanduser("~/workspace/goals/global-law-scraping-coverage/hidden_files/kosovo_wave")
TESS = os.path.join(WAVE, "tessdata")
ATTEMPTS = os.path.join(WAVE, "stats", "attempts.jsonl")
OCR_ATTEMPTS = os.path.join(WAVE, "stats", "ocr_attempts.jsonl")
PROGRESS = os.path.join(WAVE, "stats", "ocr_wave2_progress.json")


def latest_outcomes():
    latest = {}
    for line in open(ATTEMPTS):
        try:
            r = json.loads(line)
        except Exception:
            continue
        latest[int(r["act_id"])] = r
    return latest


def hf_numeric_ids():
    b = json.load(open(os.path.join(WAVE, "stats", "baseline.json")))
    return set(b["numeric"])


def ocr_done_ok():
    done = set()
    if os.path.exists(OCR_ATTEMPTS):
        for line in open(OCR_ATTEMPTS):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("result") == "ok_ocr":
                done.add(int(r["act_id"]))
    return done


def build_queue():
    latest = latest_outcomes()
    hf = hf_numeric_ids()
    local = existing_ids("xk")
    local_nums = set()
    for rid in local:
        if rid.startswith("xk-") and rid[3:].isdigit():
            local_nums.add(int(rid[3:]))
    done = ocr_done_ok()
    q = []
    for aid, r in latest.items():
        if r.get("result") != "pdf_short":
            continue
        if r.get("text_len", 999) != 0:
            continue
        if r.get("pdf_bytes", 0) < 20000:
            continue
        if aid in hf or aid in local_nums or aid in done:
            continue
        q.append((aid, r.get("pdf_bytes", 0)))
    q.sort(key=lambda t: (-t[1], -t[0]))  # pdf_bytes desc, then ActID desc
    return [aid for aid, _ in q], dict(q)


def ocr_pdf(raw, max_pages, page_timeout):
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "doc.pdf")
        open(p, "wb").write(raw)
        info = subprocess.run(["pdfinfo", p], capture_output=True, text=True, timeout=60)
        pages = 0
        for line in info.stdout.splitlines():
            if line.startswith("Pages:"):
                pages = int(line.split(":")[1])
        if pages == 0:
            return "", 0, "pdfinfo_failed"
        if pages > max_pages:
            return "", pages, "deferred_long"
        subprocess.run(["pdftoppm", "-r", "200", "-png", p, os.path.join(td, "pg")],
                       capture_output=True, timeout=1200)
        env = dict(os.environ)
        env["TESSDATA_PREFIX"] = TESS
        env["OMP_THREAD_LIMIT"] = "1"
        pngs = sorted(fn for fn in os.listdir(td) if fn.startswith("pg") and fn.endswith(".png"))
        if not pngs:
            return "", pages, "render_failed"
        texts = [""] * len(pngs)

        def ocr_one(i):
            fn = pngs[i]
            r = subprocess.run(["tesseract", os.path.join(td, fn), "stdout", "-l", "sqi",
                                "--psm", "6"], capture_output=True, text=True,
                               timeout=page_timeout, env=env)
            texts[i] = r.stdout or ""

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(ocr_one, range(len(pngs))))
        return "\n".join(texts).strip(), pages, ""


def write_progress(d):
    tmp = PROGRESS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, PROGRESS)


def do_retry_errors():
    setup_log("xk")
    latest = latest_outcomes()
    ids = sorted((aid for aid, r in latest.items()
                  if str(r.get("result", "")).startswith("error")), reverse=True)
    hf = hf_numeric_ids()
    local = existing_ids("xk")
    print(f"retry-errors: {len(ids)} ids with latest outcome error*", flush=True)
    af = open(ATTEMPTS, "a")
    ok = scanned = nopdf = still = skip = 0
    t0 = time.time()
    for aid in ids:
        rid = slug_id("xk", str(aid))
        if aid in hf or rid in local:
            skip += 1
            continue
        t1 = time.time()
        try:
            raw, title, date = collect_xk.download_act_pdf(aid)
        except Exception as exc:
            af.write(json.dumps({"act_id": aid, "result": f"error_retry2:{exc}"[:160],
                                 "wave": "ocr2"}) + "\n")
            af.flush(); still += 1; continue
        if not raw:
            af.write(json.dumps({"act_id": aid, "result": "no_pdf", "retry2": True,
                                 "secs": round(time.time() - t1, 1)}) + "\n")
            af.flush(); nopdf += 1; time.sleep(0.6); continue
        text = pdf_to_text(raw)
        if len(text) < 120:
            af.write(json.dumps({"act_id": aid, "result": "pdf_short", "retry2": True,
                                 "pdf_bytes": len(raw), "text_len": len(text),
                                 "secs": round(time.time() - t1, 1)}) + "\n")
            af.flush(); scanned += 1; time.sleep(0.6); continue
        url = f"https://gzk.rks-gov.net/ActDetail.aspx?ActID={aid}"
        saved = save_instrument(cc="xk", country="Kosovo", language="sq", ident=str(aid),
                                title=title or f"Act {aid}", text=text, source_url=url,
                                source_type=collect_xk.SOURCE_TYPE,
                                license_text=collect_xk.LICENSE, collector="collect_xk.py",
                                date=date or None, article_re=collect_xk.ART,
                                extra_meta={"fetch_method": "aspnet_pdf_postback", "act_id": aid})
        af.write(json.dumps({"act_id": aid, "result": "ok" if saved else "save_failed",
                             "retry2": True, "text_len": len(text),
                             "secs": round(time.time() - t1, 1)}) + "\n")
        af.flush()
        if saved:
            ok += 1
            print(f"retry2 ok {aid} chars={len(text)}", flush=True)
        time.sleep(0.6)
    af.close()
    print(f"RETRY2 DONE ok={ok} scanned={scanned} no_pdf={nopdf} still_error={still} "
          f"skip={skip} elapsed={time.time()-t0:.0f}s", flush=True)


def do_ocr():
    setup_log("xk")
    max_n = env_int("XK_OCR2_MAX", 100000)
    max_s = env_int("XK_OCR2_MAX_SECONDS", 10 ** 9)
    max_pages = env_int("XK_OCR2_MAX_PAGES", 50)
    page_timeout = env_int("XK_OCR2_PAGE_TIMEOUT", 900)
    queue, sizes = build_queue()
    print(f"ocr wave2 queue={len(queue)} max={max_n} max_pages={max_pages}", flush=True)
    op = open(OCR_ATTEMPTS, "a")
    ap = open(ATTEMPTS, "a")
    ok = fail = 0
    processed = 0
    t0 = time.time()
    ok_ids = []
    for idx, aid in enumerate(queue):
        if processed >= max_n:
            print("ocr2 max acts", flush=True); break
        if time.time() - t0 > max_s:
            print("ocr2 max_seconds", flush=True); break
        t1 = time.time()
        processed += 1
        try:
            raw, title, date = collect_xk.download_act_pdf(aid)
        except Exception as exc:
            op.write(json.dumps({"act_id": aid, "result": f"error:{exc}"[:160],
                                 "wave": "ocr2"}) + "\n"); op.flush(); fail += 1; continue
        if not raw:
            op.write(json.dumps({"act_id": aid, "result": "no_pdf", "wave": "ocr2"}) + "\n")
            op.flush(); fail += 1; continue
        # cheap digital guard (queue should be scans, but content can change)
        dtext = pdf_to_text(raw)
        if len(dtext) >= 300:
            url = f"https://gzk.rks-gov.net/ActDetail.aspx?ActID={aid}"
            saved = save_instrument(cc="xk", country="Kosovo", language="sq", ident=str(aid),
                                    title=title or f"Act {aid}", text=dtext, source_url=url,
                                    source_type=collect_xk.SOURCE_TYPE,
                                    license_text=collect_xk.LICENSE, collector="collect_xk.py",
                                    date=date or None, article_re=collect_xk.ART,
                                    extra_meta={"fetch_method": "aspnet_pdf_postback",
                                                "act_id": aid})
            rec = {"act_id": aid, "result": "ok_digital" if saved else "save_failed",
                   "text_len": len(dtext), "secs": round(time.time() - t1, 1), "wave": "ocr2"}
            op.write(json.dumps(rec) + "\n"); op.flush()
            if saved:
                ok += 1; ok_ids.append(aid)
                ap.write(json.dumps({"act_id": aid, "result": "ok", "text_len": len(dtext),
                                     "wave": "ocr2"}) + "\n"); ap.flush()
                print(f"ocr2 digital {aid} chars={len(dtext)} total_ok={ok} "
                      f"done={processed}/{len(queue)} elapsed={time.time()-t0:.0f}s", flush=True)
            else:
                fail += 1
            time.sleep(0.6)
            continue
        try:
            text, pages, err = ocr_pdf(raw, max_pages, page_timeout)
        except Exception as exc:
            op.write(json.dumps({"act_id": aid, "result": f"ocr_error:{exc}"[:160],
                                 "secs": round(time.time() - t1, 1), "wave": "ocr2"}) + "\n")
            op.flush(); fail += 1; continue
        if err:
            op.write(json.dumps({"act_id": aid, "result": err, "pages": pages,
                                 "secs": round(time.time() - t1, 1), "wave": "ocr2"}) + "\n")
            op.flush(); fail += 1; continue
        alpha = sum(c.isalpha() for c in text)
        ratio = alpha / max(1, len(text))
        if len(text) < 300 or ratio < 0.5:
            op.write(json.dumps({"act_id": aid, "result": "ocr_short_or_junk", "pages": pages,
                                 "text_len": len(text), "alpha_ratio": round(ratio, 2),
                                 "secs": round(time.time() - t1, 1), "wave": "ocr2"}) + "\n")
            op.flush(); fail += 1; continue
        url = f"https://gzk.rks-gov.net/ActDetail.aspx?ActID={aid}"
        saved = save_instrument(cc="xk", country="Kosovo", language="sq", ident=str(aid),
                                title=title or f"Act {aid}", text=text, source_url=url,
                                source_type=collect_xk.SOURCE_TYPE,
                                license_text=collect_xk.LICENSE, collector="collect_xk.py",
                                date=date or None, article_re=collect_xk.ART,
                                extra_meta={"fetch_method": "aspnet_pdf_postback_ocr",
                                            "act_id": aid,
                                            "ocr": {"engine": "tesseract", "lang": "sqi",
                                                    "dpi": 200, "pages": pages,
                                                    "wave": "ocr2"}})
        rec = {"act_id": aid, "result": "ok_ocr" if saved else "save_failed",
               "pages": pages, "text_len": len(text),
               "secs": round(time.time() - t1, 1), "wave": "ocr2"}
        op.write(json.dumps(rec) + "\n"); op.flush()
        if saved:
            ok += 1; ok_ids.append(aid)
            ap.write(json.dumps({"act_id": aid, "result": "ok_ocr", "text_len": len(text),
                                 "wave": "ocr2"}) + "\n"); ap.flush()
            print(f"ocr2 ok {aid} pages={pages} chars={len(text)} total_ok={ok} "
                  f"done={processed}/{len(queue)} elapsed={time.time()-t0:.0f}s", flush=True)
        else:
            fail += 1
        write_progress({"queue_total": len(queue), "processed": processed,
                        "ok": ok, "fail": fail, "ok_ids": ok_ids,
                        "last_act_id": aid, "elapsed_s": round(time.time() - t0, 1),
                        "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        time.sleep(0.6)
    op.close(); ap.close()
    write_progress({"queue_total": len(queue), "processed": processed,
                    "ok": ok, "fail": fail, "ok_ids": ok_ids, "finished": True,
                    "elapsed_s": round(time.time() - t0, 1),
                    "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    print(f"OCR2 DONE ok={ok} fail={fail} processed={processed}/{len(queue)} "
          f"elapsed={time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "ocr"
    if mode == "retry-errors":
        do_retry_errors()
    elif mode == "queue":
        q, sizes = build_queue()
        print(f"queue={len(q)}")
        print(q[:50])
    else:
        do_ocr()
