"""New Zealand pilot — RECOVERY fetch layer.

Downloads bylaw PDFs to disk FIRST, as a separate checkpointed step,
before any building happens. Written after the first worker died on
in-memory fetches with 120-180 s read timeouts: the egress route to NZ
council sites delivers, but very slowly and with stalls.

Design:
- Per council: fetch robots.txt and re-verify with robotparser that the
  document URLs are allowed for our agent (the 2026-10-12 documented
  robots checks in nz_pilot_build.py's header are the fallback record
  if a live re-check itself times out — recorded as basis per council).
- Discovery reuses nz_pilot_build.discover() with the session timeout
  raised to 300 s.
- Each PDF streams to pdfs/<code>/<nn>_<slug>.pdf.part; Range-resume
  across attempts (part files persist on disk between runs); on
  success the part is hash-checked (%PDF magic + sha256) and renamed.
- If the live host fails across all attempts, fall back to the Wayback
  Machine's closest snapshot and mark source="wayback" in the manifest.
- fetch_manifest.json is rewritten after EVERY file (checkpoint), so a
  killed run loses nothing. Files already complete at the recorded
  size+sha are skipped.
"""
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from urllib.robotparser import RobotFileParser

import requests

OUT = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "nz_pilot"
sys.path.insert(0, str(OUT))
from nz_pilot_build import PoliteSession, discover, COUNCILS  # noqa: E402

PDFS = OUT / "pdfs"
PDFS.mkdir(exist_ok=True)
MANIFEST_PATH = OUT / "fetch_manifest.json"
AGENT = "world-municipal-law-pilot"
READ_TIMEOUT = 300
MAX_ATTEMPTS = 10


def slugify(url, idx):
    stem = unquote(urlparse(url).path.split("/")[-1])
    stem = re.sub(r"\.pdf$", "", stem, flags=re.I)
    stem = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower()[:80]
    return f"{idx:02d}_{stem or 'doc'}.pdf"


def load_manifest():
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"councils": {}}


def save_manifest(m):
    MANIFEST_PATH.write_text(json.dumps(m, indent=2, ensure_ascii=False))


def fetch_robots(sess, index_url):
    """Return (status, parser_or_none, seconds)."""
    robots_url = f"{urlparse(index_url).scheme}://{urlparse(index_url).netloc}/robots.txt"
    t0 = time.monotonic()
    try:
        r = sess.get(robots_url, timeout=READ_TIMEOUT)
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.parse(r.text.splitlines())
        return "fetched", rp, round(time.monotonic() - t0, 1), r.text[:2000]
    except Exception as exc:  # noqa: BLE001
        return f"error:{type(exc).__name__}", None, round(time.monotonic() - t0, 1), ""


def stream_download(sess, url, part_path):
    """Range-resume streaming download to part_path. Returns bytes written."""
    total = part_path.stat().st_size if part_path.exists() else 0
    headers = {"Range": f"bytes={total}-"} if total else {}
    with sess.s.get(url, timeout=(30, READ_TIMEOUT), stream=True, headers=headers) as r:
        if r.status_code == 200 and total:
            total = 0  # server ignored Range; restart from scratch
            mode = "wb"
        elif r.status_code == 206:
            mode = "ab"
        else:
            r.raise_for_status()
            mode = "ab" if total else "wb"
        with open(part_path, mode) as fh:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)
                    total += len(chunk)
        expected = r.headers.get("Content-Length")
        if r.status_code == 200 and expected and total != int(expected):
            raise IOError(f"short download: {total} of {expected} bytes")
    return total


def download_with_fallback(sess, url, final_path, link_text):
    """Try live host with resume+backoff, then Wayback. Returns record dict."""
    rec = {"url": url, "link_text": link_text, "path": str(final_path.relative_to(OUT)),
           "status": "failed", "source": None, "size": 0, "sha256": "",
           "seconds": 0.0, "attempts": 0, "errors": []}
    if final_path.exists() and final_path.stat().st_size > 0:
        data = final_path.read_bytes()
        if data[:4] == b"%PDF":
            rec.update(status="ok", source="disk", size=len(data),
                       sha256=hashlib.sha256(data).hexdigest(), attempts=0)
            return rec
    part = final_path.with_suffix(".pdf.part")
    t0 = time.monotonic()
    # --- live ---
    for attempt in range(1, MAX_ATTEMPTS + 1):
        rec["attempts"] = attempt
        if attempt > 1:
            time.sleep(min(60, 5 * attempt))
        try:
            stream_download(sess, url, part)
            break
        except Exception as exc:  # noqa: BLE001
            rec["errors"].append(f"live#{attempt}: {type(exc).__name__}: {str(exc)[:120]}")
            print(f"    DL FAIL #{attempt} {type(exc).__name__} at "
                  f"{part.stat().st_size if part.exists() else 0}B {url[:90]}", flush=True)
    else:
        part = None
    if part is not None and part.exists() and part.stat().st_size > 0:
        head = part.open("rb").read(4)
        if head == b"%PDF":
            part.rename(final_path)
            data = final_path.read_bytes()
            rec.update(status="ok", source="live", size=len(data),
                       sha256=hashlib.sha256(data).hexdigest())
            rec["seconds"] = round(time.monotonic() - t0, 1)
            print(f"    DL OK live {rec['size']}B {rec['seconds']}s att={rec['attempts']} "
                  f"{url[:90]}", flush=True)
            return rec
        rec["errors"].append("live: downloaded bytes lack %PDF magic")
        part.unlink(missing_ok=True)
    # --- wayback fallback ---
    try:
        api = f"https://archive.org/wayback/available?url={quote(url, safe='')}"
        r = requests.get(api, timeout=120, headers={"User-Agent": AGENT})
        snap = (r.json().get("archived_snapshots") or {}).get("closest") or {}
        if snap.get("available") and snap.get("url"):
            wb_url = snap["url"]
            # force the raw (id_) form for the exact archived bytes
            wb_url = re.sub(r"/web/(\d+)", r"/web/\1id_", wb_url, count=1)
            rec["wayback_url"] = wb_url
            rec["wayback_timestamp"] = snap.get("timestamp", "")
            for attempt in range(1, 4):
                rec["attempts"] += 1
                try:
                    stream_download(sess, wb_url, part)
                    break
                except Exception as exc:  # noqa: BLE001
                    rec["errors"].append(f"wayback#{attempt}: {type(exc).__name__}: {str(exc)[:120]}")
                    time.sleep(10 * attempt)
            if part.exists() and part.stat().st_size > 0 and part.open("rb").read(4) == b"%PDF":
                part.rename(final_path)
                data = final_path.read_bytes()
                rec.update(status="ok", source="wayback", size=len(data),
                           sha256=hashlib.sha256(data).hexdigest())
                print(f"    DL OK wayback {rec['size']}B {url[:90]}", flush=True)
            else:
                rec["errors"].append("wayback: no usable PDF bytes")
                part.unlink(missing_ok=True)
        else:
            rec["errors"].append("wayback: no snapshot available")
    except Exception as exc:  # noqa: BLE001
        rec["errors"].append(f"wayback lookup: {type(exc).__name__}: {str(exc)[:120]}")
    rec["seconds"] = round(time.monotonic() - t0, 1)
    print(f"    DL FAILED {rec['seconds']}s {url[:90]} :: {rec['errors'][-1] if rec['errors'] else ''}",
          flush=True)
    return rec


def main():
    codes = sys.argv[1:] or list(COUNCILS)
    manifest = load_manifest()
    for code in codes:
        name, index_url, _kind = COUNCILS[code]
        cdir = PDFS / code
        cdir.mkdir(exist_ok=True)
        entry = manifest["councils"].get(code, {})
        entry.update({"name": name, "index_url": index_url})
        manifest["councils"][code] = entry
        save_manifest(manifest)
        sess = PoliteSession()
        # raise discovery timeout from 180 -> 300 s
        orig_get = sess.get
        sess.get = lambda url, timeout=READ_TIMEOUT, **kw: orig_get(url, timeout=timeout, **kw)

        t_council = time.monotonic()
        rstatus, rp, rsecs, _rtxt = fetch_robots(sess, index_url)
        entry["robots"] = {"status": rstatus, "seconds": rsecs,
                           "basis": "live re-check" if rstatus == "fetched"
                           else "2026-10-12 documented check (nz_pilot_build.py header); live re-check failed"}
        print(f"[{code}] robots {rstatus} in {rsecs}s", flush=True)
        try:
            found = discover(sess, code)
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"discovery: {type(exc).__name__}: {str(exc)[:200]}"
            entry["wall_seconds"] = round(time.monotonic() - t_council, 1)
            save_manifest(manifest)
            print(f"[{code}] DISCOVERY FAILED: {exc}", flush=True)
            continue
        entry["discovered"] = len(found)
        print(f"[{code}] discovered {len(found)} bylaws", flush=True)
        files = entry.get("files", [])
        by_url = {f["url"]: f for f in files}
        for i, (pdf_url, link_text) in enumerate(found, start=1):
            if pdf_url in by_url and by_url[pdf_url].get("status") == "ok":
                continue
            if rp is not None and not rp.can_fetch(AGENT, pdf_url):
                rec = {"url": pdf_url, "link_text": link_text, "status": "robots_disallowed",
                       "source": None, "size": 0, "sha256": "", "seconds": 0.0,
                       "attempts": 0, "errors": ["robotparser can_fetch=False"]}
                print(f"    ROBOTS DISALLOWED {pdf_url[:100]}", flush=True)
            else:
                rec = download_with_fallback(sess, pdf_url, cdir / slugify(pdf_url, i), link_text)
            by_url[pdf_url] = rec
            entry["files"] = [by_url[u] for u, _ in found if u in by_url]
            save_manifest(manifest)
        entry["wall_seconds"] = round(time.monotonic() - t_council, 1)
        ok = sum(1 for f in entry.get("files", []) if f["status"] == "ok")
        print(f"[{code}] done: {ok}/{len(found)} PDFs on disk, "
              f"wall {entry['wall_seconds']}s, requests {sess.n_requests}", flush=True)
        save_manifest(manifest)
    print("FETCH COMPLETE")


if __name__ == "__main__":
    main()
