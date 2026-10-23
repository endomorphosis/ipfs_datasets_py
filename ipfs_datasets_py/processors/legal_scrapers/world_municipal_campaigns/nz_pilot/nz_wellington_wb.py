"""Wellington City (047) — one Wayback attempt.

Live wellington.govt.nz has timed out from this egress in both prior
workers (180 s reads, repeatedly). Robots basis: worker 1's documented
2026-10-12 live check — Allow / (Disallow /search/, /~/search/,
epetition signatures); bylaw PDFs are robots-allowed. This script
fetches Wayback Machine snapshots of the same public URLs (index ->
bylaw detail pages -> PDFs), writes PDFs to pdfs/047/ and records the
council into fetch_manifest.json in nz_fetch.py's format with
source="wayback" per file. One pass only; whatever fails is recorded
and the pilot moves on.
"""
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "nz_pilot"
sys.path.insert(0, str(OUT))
from nz_pilot_build import PoliteSession, pdf_links  # noqa: E402
from nz_fetch import stream_download, slugify, load_manifest, save_manifest  # noqa: E402

CODE = "047"
NAME = "Wellington City"
INDEX = "https://wellington.govt.nz/your-council/plans-policies-and-bylaws/bylaws"
AGENT = {"User-Agent": "world-municipal-law-pilot"}
SAMPLE = 4


def wb_available(url):
    """Availability lookup with retries — the egress proxy intermittently
    drops archive.org connections / returns non-JSON error pages."""
    api = f"https://archive.org/wayback/available?url={quote(url, safe='')}"
    last = None
    for attempt in range(1, 5):
        try:
            r = requests.get(api, timeout=120, headers=AGENT)
            snap = (r.json().get("archived_snapshots") or {}).get("closest") or {}
            if snap.get("available") and snap.get("url"):
                return re.sub(r"/web/(\d+)", r"/web/\1id_", snap["url"], count=1), snap.get("timestamp", "")
            return None, ""
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"  WB lookup FAIL #{attempt} {type(exc).__name__} {url[:70]}", flush=True)
            time.sleep(15 * attempt)
    raise RuntimeError(f"wayback lookup failed after retries: {last}")


def wb_get_text(url):
    wb_url, ts = wb_available(url)
    if not wb_url:
        print(f"  WB none: {url}", flush=True)
        return None
    last = None
    for attempt in range(1, 4):
        try:
            r = requests.get(wb_url, timeout=300, headers=AGENT)
            r.raise_for_status()
            print(f"  WB {r.status_code} {len(r.content)}B ts={ts} {url[:90]}", flush=True)
            return r.text
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"  WB get FAIL #{attempt} {type(exc).__name__} {url[:70]}", flush=True)
            time.sleep(15 * attempt)
    raise RuntimeError(f"wayback fetch failed after retries: {last}")


def main():
    manifest = load_manifest()
    entry = {"name": NAME, "index_url": INDEX,
             "robots": {"status": "documented-allow",
                        "basis": "2026-10-12 documented check (nz_pilot_build.py header): "
                                 "Allow /, Disallow /search/ etc.; live host ReadTimeout "
                                 "from this egress in all three workers — Wayback snapshots "
                                 "of the same public URLs used",
                        "seconds": None},
             "files": []}
    manifest["councils"][CODE] = entry
    save_manifest(manifest)
    t0 = time.monotonic()
    sess = PoliteSession()

    try:
        html_text = wb_get_text(INDEX)
    except Exception as exc:  # noqa: BLE001
        entry["error"] = f"wayback index fetch: {type(exc).__name__}: {str(exc)[:160]}"
        entry["wall_seconds"] = round(time.monotonic() - t0, 1)
        save_manifest(manifest)
        print(f"[047] FAILED: {entry['error']}")
        return
    if html_text is None:
        entry["error"] = "wayback: no snapshot of bylaws index"
        entry["wall_seconds"] = round(time.monotonic() - t0, 1)
        save_manifest(manifest)
        print("[047] FAILED: no wayback index snapshot")
        return
    soup = BeautifulSoup(html_text, "html.parser")
    details, seen = [], set()
    for a in soup.find_all("a", href=True):
        full = urljoin(INDEX, a["href"])
        if "/bylaws/" in full and full.rstrip("/") != INDEX.rstrip("/") \
                and ".pdf" not in full.lower() and full not in seen:
            seen.add(full)
            details.append(full)
    print(f"[047] wayback index: {len(details)} detail pages", flush=True)
    found = []
    for d in details:
        if len(found) >= SAMPLE:
            break
        try:
            dtext = wb_get_text(d)
        except Exception as exc:  # noqa: BLE001
            print(f"  WB detail FAIL {type(exc).__name__} {d[:90]}", flush=True)
            continue
        if not dtext:
            continue
        links = pdf_links(d, dtext, must_contain=("bylaws/files",)) or pdf_links(d, dtext)
        if links:
            found.append(links[0])
    print(f"[047] discovered {len(found)} bylaw PDFs via wayback", flush=True)
    entry["discovered"] = len(found)
    cdir = OUT / "pdfs" / CODE
    cdir.mkdir(parents=True, exist_ok=True)
    files = []
    for i, (pdf_url, link_text) in enumerate(found, start=1):
        rec = {"url": pdf_url, "link_text": link_text,
               "path": str((cdir / slugify(pdf_url, i)).relative_to(OUT)),
               "status": "failed", "source": None, "size": 0, "sha256": "",
               "seconds": 0.0, "attempts": 0, "errors": []}
        final_path = cdir / slugify(pdf_url, i)
        t1 = time.monotonic()
        wb_url, ts = wb_available(pdf_url)
        if not wb_url:
            rec["errors"].append("wayback: no snapshot of PDF")
        else:
            rec["wayback_url"] = wb_url
            rec["wayback_timestamp"] = ts
            part = final_path.with_suffix(".pdf.part")
            for attempt in range(1, 4):
                rec["attempts"] = attempt
                try:
                    stream_download(sess, wb_url, part)
                    break
                except Exception as exc:  # noqa: BLE001
                    rec["errors"].append(f"wayback#{attempt}: {type(exc).__name__}: {str(exc)[:120]}")
                    time.sleep(10 * attempt)
            import hashlib
            if part.exists() and part.stat().st_size > 0 and part.open("rb").read(4) == b"%PDF":
                part.rename(final_path)
                data = final_path.read_bytes()
                rec.update(status="ok", source="wayback", size=len(data),
                           sha256=hashlib.sha256(data).hexdigest())
                print(f"    DL OK wayback {len(data)}B {pdf_url[:90]}", flush=True)
            else:
                rec["errors"].append("wayback: no usable PDF bytes")
                part.unlink(missing_ok=True)
        rec["seconds"] = round(time.monotonic() - t1, 1)
        files.append(rec)
        entry["files"] = files
        save_manifest(manifest)
    entry["wall_seconds"] = round(time.monotonic() - t0, 1)
    ok = sum(1 for f in files if f["status"] == "ok")
    print(f"[047] done: {ok}/{len(found)} PDFs via wayback, wall {entry['wall_seconds']}s", flush=True)
    save_manifest(manifest)


if __name__ == "__main__":
    main()
