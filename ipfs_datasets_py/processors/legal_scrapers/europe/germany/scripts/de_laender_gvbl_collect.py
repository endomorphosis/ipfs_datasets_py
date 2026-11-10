#!/usr/bin/env python3
"""DE Länder GVBl / Verkündungsplattform gazette collector (non-juris).

Collects official Gesetz- und Verordnungsblatt PDFs for Länder where juris
landesrecht portals TLS-EOF, plus DE-NI (skipped in de_laender_collect.py).

Supported (keyless, verify=True):
  DE-NI  https://www.verkuendung-niedersachsen.de  (pubStore + /api/... PDF)
  DE-BE  https://www.berlin.de/sen/justiz/.../gesetze-und-verordnungen/{year}/
  DE-HH  https://www.luewu.de/gesetz-und-verordnungsblatt/ (+ /gvbl/ issue PDFs)

Hard rules: ZERO deletes; TLS verify ON; polite UA; max(Crawl-delay, 2s);
no curl --retry; no juris token minting; 3-strike on 403/503; stop on 429/WAF/captcha;
MALLOC_ARENA_MAX=2; RSS<=300MB (soft); stop if MemAvailable < 3.2 GiB.
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmlmod
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MALLOC_ARENA_MAX", "2")

UA = "CountryLawScraper/1.0 (+https://huggingface.co/endomorphosis; research; polite; keyless)"
DELAY = 2.05
MEM_FLOOR_GIB = 3.2
MEM_LAUNCH_GIB = 4.2
MAX_PDF_BYTES = 50 * 1024 * 1024
RSS_SOFT_MB = 300
STRIKES_MAX = 3

ROOT = Path("/workspace/legal-corpora/de_laender_gvbl_20261105")
STATE_PATH = ROOT / "state.json"
ROWS = ROOT / "rows"
LOG_DIR = Path("/workspace/logs")

CTX = ssl.create_default_context()
assert CTX.verify_mode == ssl.CERT_REQUIRED and CTX.check_hostname


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def mem_available_gib() -> float:
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / (1024 * 1024)
    return 0.0


def rss_mb() -> float:
    # VmRSS from self status
    for line in open("/proc/self/status"):
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024.0
    return 0.0


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"lands": {}, "created_at": now_iso()}


def save_state(st: dict) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    # additive: write via temp then replace (no delete of prior; keep .bak_timestamp copy first)
    if STATE_PATH.exists():
        bak = STATE_PATH.with_name(f"state.json.bak_{datetime.now().strftime('%Y%m%dT%H%M%S')}")
        # copy-only bak if not exists for this second
        if not bak.exists():
            bak.write_bytes(STATE_PATH.read_bytes())
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, STATE_PATH)


def robots_crawl_delay(host_root: str) -> float:
    """Fetch robots.txt once; return max(Crawl-delay, DELAY). Never raises fatal."""
    url = host_root.rstrip("/") + "/robots.txt"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, context=CTX, timeout=20) as r:
            text = r.read(100000).decode("utf-8", "replace")
        delay = DELAY
        # crude parse: Crawl-delay under * or our UA
        cur_ua = None
        for line in text.splitlines():
            low = line.strip().lower()
            if low.startswith("user-agent:"):
                cur_ua = low.split(":", 1)[1].strip()
            elif low.startswith("crawl-delay:") and cur_ua in ("*", UA.lower().split("/")[0].lower()):
                try:
                    delay = max(delay, float(low.split(":", 1)[1].strip()))
                except ValueError:
                    pass
        return delay
    except Exception:
        return DELAY


def http_get(url: str, timeout: int = 40, max_bytes: int | None = None) -> tuple[int, bytes, str, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/pdf,application/json,text/html,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, context=CTX, timeout=timeout) as resp:
        # stream with size cap
        chunks = []
        total = 0
        limit = max_bytes or MAX_PDF_BYTES
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise RuntimeError(f"response exceeds {limit} bytes")
            chunks.append(chunk)
        body = b"".join(chunks)
        return resp.status, body, resp.geturl(), (resp.headers.get("Content-Type") or "")


def http_post_json(url: str, payload: dict, timeout: int = 40) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, context=CTX, timeout=timeout) as resp:
        return json.loads(resp.read())


def pdf_to_text(pdf_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(pdf_bytes)
        path = tf.name
    try:
        # pdftotext -layout -enc UTF-8
        p = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", path, "-"],
            capture_output=True,
            timeout=120,
        )
        text = p.stdout.decode("utf-8", "replace")
        if not text.strip():
            # fallback raw
            text = p.stderr.decode("utf-8", "replace") and "" or ""
        return text
    finally:
        try:
            os.unlink(path)  # only the temp extract file we created this call — not corpora
        except OSError:
            pass


def strike_or_stop(st_land: dict, status: int | None, err: str | None) -> str | None:
    """Return 'STOP' to abort land, 'HOLD' after 3 strikes, else None."""
    msg = (err or "") + str(status or "")
    low = msg.lower()
    if status == 429 or "captcha" in low or "waf" in low or "cf-ray" in low:
        st_land["status"] = "STOP"
        st_land["reason"] = f"429/captcha/WAF: {msg[:200]}"
        st_land["at"] = now_iso()
        return "STOP"
    if status in (403, 503):
        st_land["strikes"] = int(st_land.get("strikes") or 0) + 1
        st_land["last_strike"] = {"status": status, "at": now_iso(), "err": (err or "")[:200]}
        if st_land["strikes"] >= STRIKES_MAX:
            st_land["status"] = "HOLD"
            st_land["reason"] = f"3-strike 403/503"
            return "HOLD"
    return None


def append_row(land: str, row: dict) -> None:
    ROWS.mkdir(parents=True, exist_ok=True)
    path = ROWS / f"DE-{land}.jsonl"
    with open(path, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# -------------------- DE-NI --------------------

def ni_sheet_slug(sheet: str) -> str:
    return sheet.lower().replace(".", "").replace(" ", "")


def collect_NI(st: dict, budget_s: float, delay: float) -> None:
    land = "NI"
    L = st["lands"].setdefault(land, {"done": [], "status": "RUNNING", "ok": 0, "fail": 0})
    if L.get("status") in ("STOP",):
        return
    done = set(L.get("done") or [])
    t0 = time.time()
    time.sleep(delay)
    # catalog
    status, body, final, ctype = http_get("https://www.verkuendung-niedersachsen.de/pubStore", timeout=60)
    cat = json.loads(body)
    gvbl = [x for x in cat if x.get("proclamation_sheet") == "Nds. GVBl."]
    L["catalog_gvbl"] = len(gvbl)
    save_state(st)
    for item in gvbl:
        if time.time() - t0 > budget_s:
            L["status"] = "PAUSED_BUDGET"
            L["at"] = now_iso()
            save_state(st)
            return
        if mem_available_gib() < MEM_FLOOR_GIB:
            L["status"] = "PAUSED_MEM"
            L["at"] = now_iso()
            save_state(st)
            return
        if rss_mb() > RSS_SOFT_MB:
            time.sleep(2)
            if rss_mb() > RSS_SOFT_MB:
                L["status"] = "PAUSED_RSS"
                L["at"] = now_iso()
                save_state(st)
                return
        year = (item.get("issuing_date") or item.get("date") or "1970")[:4]
        # better year from fundstelle "Nds. GVBl. - 2024, Nr. 1"
        m = re.search(r"(\d{4})", item.get("fundstelle") or "")
        if m:
            year = m.group(1)
        nr = str(item.get("proclamation_nr") or "").strip()
        key = f"{year}-{nr}"
        if key in done:
            continue
        slug = ni_sheet_slug(item.get("proclamation_sheet") or "Nds. GVBl.")
        detail_url = f"https://www.verkuendung-niedersachsen.de/api/{slug}/{year}/{nr}"
        time.sleep(delay)
        try:
            stt, raw, _, _ = http_get(detail_url, timeout=30)
            detail = json.loads(raw)
            dl = detail.get("mainDocument", {}).get("file", {}).get("downloadLink")
            if not dl:
                L["fail"] = L.get("fail", 0) + 1
                continue
            pdf_url = urllib.parse.urljoin("https://www.verkuendung-niedersachsen.de/", dl)
            time.sleep(delay)
            pst, pdf, pfinal, pct = http_get(pdf_url, timeout=60, max_bytes=MAX_PDF_BYTES)
            if not pdf.startswith(b"%PDF"):
                L["fail"] = L.get("fail", 0) + 1
                continue
            text = pdf_to_text(pdf)
            if not (text or "").strip():
                # keep row with empty? skip empty text
                L["fail"] = L.get("fail", 0) + 1
                L.setdefault("empty_text", 0)
                L["empty_text"] += 1
                # still mark done to avoid hammering
                done.add(key)
                L["done"] = list(done)
                save_state(st)
                continue
            title = (detail.get("title") or item.get("title") or f"Nds. GVBl. {year} Nr. {nr}").strip()
            sha = hashlib.sha256(pdf).hexdigest()
            row = {
                "id": f"DE-NI:GVBl-{year}-{nr}",
                "jurisdiction": "DE-NI",
                "land": "NI",
                "gbl": f"{year}-{nr}",
                "title": title,
                "text": text,
                "text_chars": len(text),
                "source_type": "gazette_as_published",
                "consolidated": False,
                "source_url": f"https://www.verkuendung-niedersachsen.de/{slug}/{year}/{nr}/",
                "pdf_url": pdf_url,
                "pdf_sha256": sha,
                "host": "www.verkuendung-niedersachsen.de",
                "robots_disallowed": False,
                "transport": "https",
                "retrieved_at": now_iso(),
                "proclamation_type": detail.get("proclamation_type") or item.get("proclamationType"),
                "fundstelle": detail.get("fundstelle") or item.get("fundstelle"),
            }
            append_row(land, row)
            done.add(key)
            L["done"] = list(done)
            L["ok"] = L.get("ok", 0) + 1
            L["status"] = "RUNNING"
            L["at"] = now_iso()
            if L["ok"] % 5 == 0:
                save_state(st)
                print(f"NI ok={L['ok']} last={key} rss={rss_mb():.0f}MB mem={mem_available_gib():.1f}G", flush=True)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            status = None
            if isinstance(e, urllib.error.HTTPError):
                status = e.code
            stop = strike_or_stop(L, status, err)
            L["fail"] = L.get("fail", 0) + 1
            L["last_error"] = err[:300]
            save_state(st)
            print(f"NI fail {key}: {err[:120]}", flush=True)
            if stop:
                return
    L["status"] = "DONE" if len(done) >= len(gvbl) else "PAUSED_BUDGET"
    L["at"] = now_iso()
    save_state(st)


# -------------------- DE-BE --------------------

def collect_BE(st: dict, budget_s: float, delay: float, years: list[int]) -> None:
    land = "BE"
    L = st["lands"].setdefault(land, {"done": [], "status": "RUNNING", "ok": 0, "fail": 0})
    done = set(L.get("done") or [])
    t0 = time.time()
    base = "https://www.berlin.de"
    for year in years:
        if time.time() - t0 > budget_s:
            break
        list_url = f"{base}/sen/justiz/service/gesetze-und-verordnungen/{year}/"
        time.sleep(delay)
        try:
            stt, body, final, ctype = http_get(list_url, timeout=30)
        except Exception as e:
            status = e.code if isinstance(e, urllib.error.HTTPError) else None
            if strike_or_stop(L, status, str(e)):
                save_state(st)
                return
            L["fail"] = L.get("fail", 0) + 1
            continue
        html = body.decode("utf-8", "replace")
        pdfs = re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I)
        # unique preserve order
        seen_u = set()
        urls = []
        for p in pdfs:
            u = urllib.parse.urljoin(list_url, htmlmod.unescape(p))
            # strip cache bust query for id but keep for fetch
            if u in seen_u:
                continue
            seen_u.add(u)
            urls.append(u)
        L.setdefault("listed", {})[str(year)] = len(urls)
        for pdf_url in urls:
            if time.time() - t0 > budget_s or mem_available_gib() < MEM_FLOOR_GIB:
                L["status"] = "PAUSED_BUDGET" if time.time() - t0 > budget_s else "PAUSED_MEM"
                L["at"] = now_iso()
                save_state(st)
                return
            # id from filename
            path = urllib.parse.urlparse(pdf_url).path
            fname = path.rsplit("/", 1)[-1]
            key = f"{year}:{fname}"
            if key in done:
                continue
            # parse issue nr
            m = re.search(r"ausgabe[_-]?nr[._-]*(\d+)", fname, re.I)
            nr = m.group(1) if m else hashlib.sha256(fname.encode()).hexdigest()[:10]
            time.sleep(delay)
            try:
                pst, pdf, pfinal, pct = http_get(pdf_url, timeout=60, max_bytes=MAX_PDF_BYTES)
                if not pdf.startswith(b"%PDF"):
                    L["fail"] = L.get("fail", 0) + 1
                    continue
                text = pdf_to_text(pdf)
                if not text.strip():
                    done.add(key)
                    L["done"] = list(done)
                    L.setdefault("empty_text", 0)
                    L["empty_text"] += 1
                    continue
                title = f"Berlin GVBl. {year} Nr. {nr}"
                # try better title from filename date
                md = re.search(r"vom[_-]?(\d+)", fname, re.I)
                row = {
                    "id": f"DE-BE:GVBl-{year}-{nr}",
                    "jurisdiction": "DE-BE",
                    "land": "BE",
                    "gbl": f"{year}-{nr}",
                    "title": title,
                    "text": text,
                    "text_chars": len(text),
                    "source_type": "gazette_as_published",
                    "consolidated": False,
                    "source_url": list_url,
                    "pdf_url": pdf_url.split("?")[0],
                    "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
                    "host": "www.berlin.de",
                    "robots_disallowed": False,
                    "transport": "https",
                    "retrieved_at": now_iso(),
                }
                append_row(land, row)
                done.add(key)
                L["done"] = list(done)
                L["ok"] = L.get("ok", 0) + 1
                L["status"] = "RUNNING"
                L["at"] = now_iso()
                if L["ok"] % 5 == 0:
                    save_state(st)
                    print(f"BE ok={L['ok']} last={key} rss={rss_mb():.0f}MB", flush=True)
            except Exception as e:
                status = e.code if isinstance(e, urllib.error.HTTPError) else None
                stop = strike_or_stop(L, status, str(e))
                L["fail"] = L.get("fail", 0) + 1
                L["last_error"] = f"{type(e).__name__}: {e}"[:300]
                save_state(st)
                print(f"BE fail {key}: {str(e)[:120]}", flush=True)
                if stop:
                    return
    L["status"] = "DONE" if L.get("ok", 0) else L.get("status", "DONE")
    # mark DONE if no more pending in listed years — approximate
    L["at"] = now_iso()
    save_state(st)


# -------------------- DE-HH --------------------

def collect_HH(st: dict, budget_s: float, delay: float, max_pages: int = 5) -> None:
    land = "HH"
    L = st["lands"].setdefault(land, {"done": [], "status": "RUNNING", "ok": 0, "fail": 0})
    done = set(L.get("done") or [])
    t0 = time.time()
    issue_urls = []
    for page in range(1, max_pages + 1):
        if page == 1:
            list_url = "https://www.luewu.de/gesetz-und-verordnungsblatt/"
        else:
            list_url = f"https://www.luewu.de/gesetz-und-verordnungsblatt/?paged1={page}"
        time.sleep(delay)
        try:
            stt, body, final, ctype = http_get(list_url, timeout=30)
        except Exception as e:
            status = e.code if isinstance(e, urllib.error.HTTPError) else None
            if strike_or_stop(L, status, str(e)):
                save_state(st)
                return
            break
        html = body.decode("utf-8", "replace")
        found = re.findall(r'href=["\'](https://www\.luewu\.de/gvbl/ausgabe-nr-[^"\']+)["\']', html, re.I)
        found += re.findall(r'href=["\'](/gvbl/ausgabe-nr-[^"\']+)["\']', html, re.I)
        for h in found:
            u = urllib.parse.urljoin(list_url, h)
            if u not in issue_urls:
                issue_urls.append(u)
    L["listed_issues"] = len(issue_urls)
    save_state(st)
    for issue_url in issue_urls:
        if time.time() - t0 > budget_s or mem_available_gib() < MEM_FLOOR_GIB:
            L["status"] = "PAUSED_BUDGET" if time.time() - t0 > budget_s else "PAUSED_MEM"
            L["at"] = now_iso()
            save_state(st)
            return
        slug = issue_url.rstrip("/").rsplit("/", 1)[-1]
        if slug in done:
            continue
        time.sleep(delay)
        try:
            stt, body, final, ctype = http_get(issue_url, timeout=30)
            html = body.decode("utf-8", "replace")
            pdfs = re.findall(r'href=["\'](https://www\.luewu\.de/wp-content/uploads/[^"\']+\.pdf)["\']', html, re.I)
            if not pdfs:
                L["fail"] = L.get("fail", 0) + 1
                continue
            pdf_url = pdfs[0]
            time.sleep(delay)
            pst, pdf, pfinal, pct = http_get(pdf_url, timeout=60, max_bytes=MAX_PDF_BYTES)
            if not pdf.startswith(b"%PDF"):
                L["fail"] = L.get("fail", 0) + 1
                continue
            text = pdf_to_text(pdf)
            if not text.strip():
                done.add(slug)
                L["done"] = list(done)
                continue
            m = re.search(r"ausgabe-nr-(\d+)-vom-(\d{2})-(\d{2})-(\d{4})", slug)
            if m:
                nr, dd, mm, yyyy = m.group(1), m.group(2), m.group(3), m.group(4)
                gbl = f"{yyyy}-{nr}"
                title = f"HmbGVBl. {yyyy} Nr. {nr} vom {dd}.{mm}.{yyyy}"
            else:
                gbl = slug
                title = f"Hamburgisches GVBl. {slug}"
                yyyy = "0000"
                nr = slug
            row = {
                "id": f"DE-HH:GVBl-{gbl}",
                "jurisdiction": "DE-HH",
                "land": "HH",
                "gbl": gbl,
                "title": title,
                "text": text,
                "text_chars": len(text),
                "source_type": "gazette_as_published",
                "consolidated": False,
                "source_url": issue_url,
                "pdf_url": pdf_url,
                "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
                "host": "www.luewu.de",
                "robots_disallowed": False,
                "transport": "https",
                "retrieved_at": now_iso(),
            }
            append_row(land, row)
            done.add(slug)
            L["done"] = list(done)
            L["ok"] = L.get("ok", 0) + 1
            L["status"] = "RUNNING"
            L["at"] = now_iso()
            if L["ok"] % 5 == 0:
                save_state(st)
                print(f"HH ok={L['ok']} last={slug} rss={rss_mb():.0f}MB", flush=True)
        except Exception as e:
            status = e.code if isinstance(e, urllib.error.HTTPError) else None
            stop = strike_or_stop(L, status, str(e))
            L["fail"] = L.get("fail", 0) + 1
            L["last_error"] = f"{type(e).__name__}: {e}"[:300]
            save_state(st)
            print(f"HH fail {slug}: {str(e)[:120]}", flush=True)
            if stop:
                return
    L["status"] = "DONE"
    L["at"] = now_iso()
    save_state(st)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lands", default="NI,BE,HH", help="comma list")
    ap.add_argument("--budget-sec", type=int, default=540, help="wall budget seconds (~9 min default)")
    ap.add_argument("--be-years", default="2026,2025,2024")
    ap.add_argument("--hh-pages", type=int, default=4)
    args = ap.parse_args()

    mem = mem_available_gib()
    print(f"start mem={mem:.2f}GiB rss={rss_mb():.0f}MB lands={args.lands}", flush=True)
    if mem < MEM_FLOOR_GIB:
        print("ABORT MemAvailable < 3.2 GiB", flush=True)
        sys.exit(2)

    ROOT.mkdir(parents=True, exist_ok=True)
    ROWS.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    st = load_state()
    st["updated_at"] = now_iso()
    lands = [x.strip().upper() for x in args.lands.split(",") if x.strip()]

    # per-host robots delay (once each)
    delays = {
        "NI": robots_crawl_delay("https://www.verkuendung-niedersachsen.de"),
        "BE": robots_crawl_delay("https://www.berlin.de"),
        "HH": robots_crawl_delay("https://www.luewu.de"),
    }
    for k, v in delays.items():
        print(f"crawl_delay {k}={v}", flush=True)
        time.sleep(DELAY)

    t_end = time.time() + args.budget_sec
    be_years = [int(y) for y in args.be_years.split(",") if y.strip()]

    for land in lands:
        remaining = t_end - time.time()
        if remaining < 30:
            print("budget nearly exhausted, stop scheduling", flush=True)
            break
        if mem_available_gib() < MEM_FLOOR_GIB:
            print("mem floor hit", flush=True)
            break
        delay = delays.get(land, DELAY)
        print(f"=== collect {land} budget_left={remaining:.0f}s ===", flush=True)
        if land == "NI":
            collect_NI(st, remaining, delay)
        elif land == "BE":
            collect_BE(st, remaining, delay, be_years)
        elif land == "HH":
            collect_HH(st, remaining, delay, max_pages=args.hh_pages)
        else:
            print(f"no collector yet for {land}", flush=True)
        save_state(st)

    # summary
    for land, L in st.get("lands", {}).items():
        print(f"SUMMARY {land} status={L.get('status')} ok={L.get('ok')} fail={L.get('fail')} done={len(L.get('done') or [])}", flush=True)
    save_state(st)


if __name__ == "__main__":
    main()
