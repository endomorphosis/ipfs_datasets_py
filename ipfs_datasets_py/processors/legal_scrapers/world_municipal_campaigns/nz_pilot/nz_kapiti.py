"""Kāpiti Coast District (043) — group C: JS document-library API attempt.

The council's /bylaws listing is client-rendered; the pilot confirmed
zero document links in the server HTML. Reverse-engineered from the
site's own /static/main.js (fetched 2026-10-13, tranche 1): the listing
calls the Umbraco reports API

  POST /umbraco/api/reports/getreportsusingdeliveryapi/
  {"criteria": {"Search": "", "Topic": "", "Type": "Bylaws",
                "SubType": "", "Year": null, "Sort": 0,
                "Skip": 0, "Take": 50}}

which returns {total, items: [{id, name, url, reportDate, documents:
[{url, name, documentType, size}]}]} — documents[].url is a direct
download href (createDocumentEl in main.js). This script calls that
API once, takes up to 4 bylaw PDFs, downloads them with the pilot's
checkpointed streamer, records pdfs/043/ + a fetch_manifest.json entry
(source "live", route note "umbraco-api"), then builds with nz_build3
and publishes via nz_tranche1 helpers. Robots: kapiticoast.govt.nz
robots.txt was fetched live in the pilot (200, allows the bylaws area);
it is re-fetched and the API + document URLs are robotparser-checked
here before any document download.
"""
import hashlib
import json
import sys
import time
from pathlib import Path
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

OUT = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "nz_pilot"
sys.path.insert(0, str(OUT))

import nz_tranche1 as T  # noqa: E402
from nz_fetch import stream_download, slugify  # noqa: E402

CODE = "043"
BASE = "https://www.kapiticoast.govt.nz"
API = BASE + "/umbraco/api/reports/getreportsusingdeliveryapi/"
AGENT = T.AGENT


def main():
    tm = T.load_tm()
    rec = T.tm_record(tm, CODE)
    rec["status"] = "harvesting"
    T.tm_save(tm)
    t0 = time.monotonic()
    sess = T.make_session()
    # robots re-check
    rp, rstatus, rsecs, _rt = T.fetch_robots_live(sess, BASE)
    print(f"[043] robots {rstatus} {rsecs}s", flush=True)
    if rp is not None and not rp.can_fetch(AGENT, API):
        rec.update({"status": "dead_end", "category": "robots_disallowed",
                    "evidence": "robots.txt disallows the Umbraco reports API path",
                    "wall_seconds": round(time.monotonic() - t0, 1), "updated": T.TODAY})
        T.tm_save(tm)
        print("[043] DEAD_END robots_disallowed (API)")
        return
    payload = {"criteria": {"Search": "", "Topic": "", "Type": "Bylaws",
                            "SubType": "", "Year": None, "Sort": 0,
                            "Skip": 0, "Take": 50}}
    data = None
    last_exc = None
    for attempt in range(1, 4):
        try:
            r = sess.s.post(API, json=payload, timeout=(30, 600),
                            headers={"Content-Type": "application/json"})
            r.raise_for_status()
            data = r.json()
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(f"[043] API POST FAIL #{attempt} {type(exc).__name__}: {str(exc)[:120]}", flush=True)
            time.sleep(30 * attempt)
    if data is None:
        rec.update({"status": "dead_end", "category": "js_api_needed",
                    "evidence": f"Umbraco reports API call failed after 3 attempts (600 s read cap): {type(last_exc).__name__}: {str(last_exc)[:150]}",
                    "wall_seconds": round(time.monotonic() - t0, 1), "updated": T.TODAY})
        T.tm_save(tm)
        print(f"[043] DEAD_END js_api_needed: API call failed {last_exc}")
        return
    items = data.get("items") or []
    print(f"[043] API total={data.get('total')} items={len(items)}", flush=True)
    docs = []
    for it in items:
        for d in (it.get("documents") or []):
            u = d.get("url") or ""
            if ".pdf" not in u.lower():
                continue
            docs.append((urljoin(BASE, u), d.get("name") or it.get("name") or u))
        if len(docs) >= T.SAMPLE:
            break
    docs = docs[:T.SAMPLE]
    if not docs:
        rec.update({"status": "dead_end", "category": "no_bylaws_found",
                    "evidence": f"Umbraco reports API (Type=Bylaws) returned {len(items)} items but no PDF documents",
                    "wall_seconds": round(time.monotonic() - t0, 1), "updated": T.TODAY})
        T.tm_save(tm)
        print("[043] DEAD_END no_bylaws_found via API")
        return
    cdir = T.PDFS / CODE
    cdir.mkdir(exist_ok=True)
    _fm, fentry = T.fetch_entry(CODE)
    fentry.update({"name": "Kāpiti Coast District", "index_url": BASE + "/bylaws",
                   "robots": {"status": rstatus, "seconds": rsecs,
                              "basis": "live re-check (tranche 1, nz_kapiti.py)"},
                   "discovered": len(docs),
                   "route_note": "Umbraco reports API (JS document library)"})
    files = []
    for i, (pdf_url, link_text) in enumerate(docs, start=1):
        final_path = cdir / slugify(pdf_url, i)
        frec = {"url": pdf_url, "link_text": link_text,
                "path": str(final_path.relative_to(OUT)), "status": "failed",
                "source": None, "size": 0, "sha256": "", "seconds": 0.0,
                "attempts": 0, "errors": []}
        if rp is not None and not rp.can_fetch(AGENT, pdf_url):
            frec["status"] = "robots_disallowed"
            frec["errors"].append("robotparser can_fetch=False")
            files.append(frec)
            fentry["files"] = files
            T.save_fetch_entry(CODE, fentry)
            continue
        t1 = time.monotonic()
        ok, errors = T.download_live(sess, pdf_url, final_path)
        frec["errors"] = errors
        frec["seconds"] = round(time.monotonic() - t1, 1)
        if ok:
            data_b = final_path.read_bytes()
            frec.update({"status": "ok", "source": "live", "size": len(data_b),
                         "sha256": hashlib.sha256(data_b).hexdigest()})
            print(f"    DL OK {len(data_b)}B {pdf_url[:90]}", flush=True)
        files.append(frec)
        fentry["files"] = files
        T.save_fetch_entry(CODE, fentry)
    fentry["wall_seconds"] = round(time.monotonic() - t0, 1)
    T.save_fetch_entry(CODE, fentry)
    ok_files = [f for f in files if f["status"] == "ok"]
    rec["wall_seconds"] = round(time.monotonic() - t0, 1)
    if not ok_files:
        rec.update({"status": "dead_end", "category": "transfer_stall",
                    "evidence": "Umbraco API yielded PDF URLs but all downloads failed",
                    "updated": T.TODAY})
        T.tm_save(tm)
        print("[043] DEAD_END transfer_stall (API docs)")
        return
    rec["docs"] = len(ok_files)
    T.tm_save(tm)
    try:
        T.build_and_publish(tm, CODE, "live (umbraco-api)")
    except BaseException as exc:  # noqa: BLE001
        rec.update({"status": "dead_end", "category": "build_gate_failed",
                    "evidence": f"build/gates failed: {str(exc)[:220]}", "updated": T.TODAY})
        T.tm_save(tm)
        print(f"[043] BUILD FAILED {exc}")


if __name__ == "__main__":
    main()
