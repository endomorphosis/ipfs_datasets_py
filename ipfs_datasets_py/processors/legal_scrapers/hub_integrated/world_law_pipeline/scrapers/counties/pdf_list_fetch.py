#!/usr/bin/env python3
"""County lane generic PDF-list fetcher (rewrite of us_pdf_list.py, 2026-11-01).

entries JSON: {"place_id","country_code","source_platform","source_org","doc_id_prefix","language","doc_type",
               "place_name"?, "admin_level"?, "items":[{"url","title","number"?,"adopted_date"?,"published_date"?}]}
- polite: >= DELAY s (default 1.5, min 1.0) between requests per host, honest UA, no proxies, no WAF/captcha bypass
  (403/429/challenge pages are logged and skipped; 429/503 -> long backoff, then stop after repeated failures).
- robots.txt IGNORED by default (owner decision 2026-11-01); RESPECT_ROBOTS=1 honours it. The site's policy is tagged
  in source_policy: robots_allowed_rfc9309 / robots_404_allow_rfc9309 / robots_disallowed_ignored / robots_unreachable_ignored.
- text PDFs -> pdf_text rows; scanned (no text layer) -> raw PDF staged in staging/pdf/<CC>/<pkey>/ (no OCR) and a
  content_complete=false row with extra_metadata.pdf_path/scanned_pdf. Spreadsheets skipped.
- skips doc_ids/URLs in published_skip.jsonl, anything already staged (staging/counties) and the local done ledger.
- doc_id = f"{source_platform}:{doc_id_prefix}~{sha1(url)[:8]}" (FR RAA scheme) or, without doc_id_prefix,
  f"{source_platform}:{sha1(url)[:16]}" (de_by_kreisrecht scheme); both match the pre-restore crawler. Both are (or end in)
  a URL hash, so query-string URLs (e.g. showFile.jsp?pdf=...) always get a distinct doc_id.
2026-11-01 22:15 PST watchdog: every request uses (connect, read) timeouts, the body is streamed with a wall-clock deadline
  (FETCH_DEADLINE, default 120 s; robots.txt 30 s) enforced by SIGALRM, which interrupts any blocking SSL read the socket
  timeout misses (slow drip), and a size cap (FETCH_MAX_MB, default 150 MB). A large PDF still arriving at >= FETCH_MIN_KBPS
  (32 KB/s avg) may continue past the deadline up to FETCH_MAX_DEADLINE (600 s) as long as each 64 KB block lands within
  FETCH_STALL (60 s). Timeouts -> logged as ERR, skipped.
  SIGTERM/SIGINT flush the buffered chunk before exit. Resume skips doc_ids already committed anywhere: staging,
  processed/counties (drained chunks, .jsonl/.jsonl.gz), the _archive_provenance sidecars, published_skip.jsonl.
  done_<pk>.jsonl lines are now written only after the chunk holding them is flushed (= committed ledger).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, hashlib, json, os, re, signal, subprocess, sys, time, urllib.parse, urllib.robotparser, glob, gzip
from datetime import datetime, timezone
from pathlib import Path
import requests
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline"))
import importlib.util as _ilu  # load archive/staging.py directly (archive/__init__ needs deferral.py, lost in the 2026-11-01 restore)
_sp = _ilu.spec_from_file_location("county_staging", (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/archive/staging.py"))
_sm = _ilu.module_from_spec(_sp); _sp.loader.exec_module(_sm); StagedWriter = _sm.StagedWriter
from schema import place_key
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/tools")); import batch_alloc as _BA  # 2026-11-03: manifest + .ready per closed part
SCANS = []  # manifest rows (PDF_STAGING.md §3) of scanned PDFs in the part currently being written
def seal_scans():
    """Part closed: write its scanned PDFs as staging/pdf/_manifest/batch_NNNN.jsonl + empty .ready (tools/batch_alloc.py)."""
    if not SCANS: return None
    n = _BA.write_batch(PDF_STAGE / "_manifest", list(SCANS), floor=272); SCANS.clear()
    print(f"{now()} pdf batch_{n:04d} ready", flush=True); return n

HERE = Path(__file__).resolve().parent
STAGE = Path(os.environ.get("COUNTY_STAGE_DIR", str(_WORLD) + "/staging/counties"))  # env override = tests only
PDF_STAGE = Path(os.environ.get("COUNTY_PDF_STAGE_DIR", str(_WORLD) + "/staging/pdf"))
STATE = STAGE / "_state"
UA = "WorldLawBot/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law; public-law research crawler; polite)"
RESPECT_ROBOTS = os.environ.get("RESPECT_ROBOTS", "0") == "1"
SHEET_EXT = (".xls", ".xlsx", ".ods", ".csv")
STAMP_RE = re.compile(os.environ["FETCH_STAMP_RE"], re.I) if os.environ.get("FETCH_STAMP_RE") else None
PROCESSED = Path((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/processed/counties"))
PROV = STAGE / "_archive_provenance"
CONNECT_TO = float(os.environ.get("FETCH_CONNECT_TIMEOUT", "20")); READ_TO = float(os.environ.get("FETCH_READ_TIMEOUT", "60"))
DEADLINE = float(os.environ.get("FETCH_DEADLINE", "120")); MAX_DEADLINE = float(os.environ.get("FETCH_MAX_DEADLINE", "600"))
MIN_RATE = float(os.environ.get("FETCH_MIN_KBPS", "32")) * 1024  # big PDFs may run past DEADLINE only while >= MIN_RATE avg
STALL = float(os.environ.get("FETCH_STALL", "60")); MAX_BYTES = int(float(os.environ.get("FETCH_MAX_MB", "150")) * 1024 * 1024)

class FetchTimeout(Exception): pass
def _alarm(signum, frame): raise FetchTimeout(f"wall-clock deadline (SIGALRM) hit")
signal.signal(signal.SIGALRM, _alarm)

STOP = Path(os.environ.get("GUARD_STOPFILE", str(_WORLD) + "/staging/counties/_logs/.county_chain_stop"))

def now(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

_DID = re.compile(r'"doc_id":\s*"([^"]+)"')
def _scan(p, ids):
    try:
        with (gzip.open(p, "rt", errors="replace") if str(p).endswith(".gz") else open(p, errors="replace")) as f:
            for l in f:
                m = _DID.search(l)
                if m: ids.add(m.group(1))
    except Exception as e: print(f"WARN skip-scan {p}: {e}", flush=True)

def load_skip(pk=None, cc=None):
    ids, urls = set(), set()
    for p in [HERE / "published_skip.jsonl"]:  # done_*.jsonl is an audit log only (written before chunk flush)
        if p.exists():
            for l in open(p):
                try: d = json.loads(l)
                except Exception: continue
                ids.add(d.get("doc_id")); urls.add(d.get("source_url"))
    for p in STAGE.rglob("*.jsonl"):
        if any(part.startswith("_") for part in p.relative_to(STAGE).parts): continue
        for l in open(p, errors="replace"):
            m = re.search(r'"doc_id":\s*"([^"]+)"', l)
            if m: ids.add(m.group(1))
    if pk:  # chunks already drained by the Normalizer (processed/) and the provenance sidecars that survive the move
        for base in ([PROCESSED / cc] if cc else list(PROCESSED.glob("*"))) + ([PROV / cc] if cc else list(PROV.glob("*"))):
            for p in base.glob(f"{pk}.*.jsonl*"): _scan(p, ids)
    ids.discard(None); urls.discard(None)
    return ids, urls

class Polite:
    def __init__(self, delay):
        self.delay = max(1.0, delay); self.last = {}; self.robots = {}
        self.s = requests.Session(); self.s.headers.update({"User-Agent": UA, "Accept-Language": "fr,de,en;q=0.5"}); self.s.trust_env = False
    def wait(self, host):
        dt = time.time() - self.last.get(host, 0)
        if dt < self.delay: time.sleep(self.delay - dt)
        self.last[host] = time.time()
    def policy(self, url):
        u = urllib.parse.urlsplit(url); base = f"{u.scheme}://{u.netloc}"
        if base not in self.robots:
            rp = urllib.robotparser.RobotFileParser(); st = "unreachable"
            try:  # tagging only (robots ignored by default); same watchdog as documents
                self.wait(u.netloc); code, _, b, _e = self._fetch(base + "/robots.txt", 30)
                if code in (404, 410): st = "404"
                elif code == 200 and b is not None: rp.parse(b.decode("utf-8", "replace").splitlines()); st = "ok"
            except Exception: pass
            self.robots[base] = (st, rp)
        st, rp = self.robots[base]
        if st == "404": return "robots_404_allow_rfc9309", True
        if st == "unreachable": return "robots_unreachable_ignored", not RESPECT_ROBOTS
        if rp.can_fetch(UA, url): return "robots_allowed_rfc9309", True
        return "robots_disallowed_ignored", not RESPECT_ROBOTS
    def _fetch(self, url, deadline=None):
        """one GET: (connect, read) timeouts + streamed body with wall-clock deadline, size cap and SIGALRM backstop.
        returns (status, headers, body_bytes_or_None, err)."""
        deadline = deadline or DEADLINE; t0 = time.time(); signal.alarm(max(1, int(deadline) + 1)); r = None  # SIGALRM = hard wall clock
        try:
            r = self.s.get(url, timeout=(CONNECT_TO, READ_TO), stream=True)
            if r.status_code != 200: return r.status_code, r.headers, None, None
            cl = r.headers.get("Content-Length")
            if cl and cl.isdigit() and int(cl) > MAX_BYTES: return r.status_code, r.headers, None, f"too large ({cl} B > cap)"
            buf = bytearray()
            for ch in r.iter_content(65536):
                buf += ch; el = time.time() - t0
                if len(buf) > MAX_BYTES: return r.status_code, r.headers, None, f"size cap {MAX_BYTES} B exceeded"
                if el > deadline:
                    if el > MAX_DEADLINE or len(buf) / el < MIN_RATE:
                        raise FetchTimeout(f"body deadline {deadline:.0f}s exceeded after {len(buf)} B ({len(buf)/el/1024:.0f} KB/s)")
                    signal.alarm(max(1, int(min(STALL, MAX_DEADLINE - el)) + 1))  # healthy big download: next block within STALL s
            return r.status_code, r.headers, bytes(buf), None
        finally:
            signal.alarm(0)
            if r is not None:
                try: r.close()
                except Exception: pass
    def get(self, url):
        host = urllib.parse.urlsplit(url).netloc; err = None; tmo = 0
        for attempt in range(3):
            self.wait(host)
            try: st, hd, b, e = self._fetch(url)
            except FetchTimeout as e:
                err = f"TIMEOUT {e}"; tmo += 1; self.s.close()  # drop the stuck connection from the pool
                if tmo >= 2: break  # two watchdog timeouts on one URL -> give up on it
                time.sleep(10 * (attempt + 1)); continue
            except Exception as e:
                time.sleep(10 * (attempt + 1)); err = str(e)[:200]; continue
            if st in (429, 503):
                ra = hd.get("Retry-After"); time.sleep(min(int(ra) if ra and ra.isdigit() else 60 * (attempt + 1), 900)); err = str(st); continue
            if e: return None, e  # size cap: not retried
            return (st, hd, b), None
        return None, err

def pdf_text(b):
    try:
        p = subprocess.run(["pdftotext", "-layout", "-q", "-", "-"], input=b, capture_output=True, timeout=120)
        return p.stdout.decode("utf-8", "replace")
    except Exception: return ""

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("entries"); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=float(os.environ.get("POLITE_DELAY", "1.5"))); ap.add_argument("--chunk", type=int, default=100)
    a = ap.parse_args()
    E = json.load(open(a.entries)); STATE.mkdir(parents=True, exist_ok=True)
    pid, cc, plat = E["place_id"], E["country_code"], E["source_platform"]; pk = place_key(pid)
    ids, urls = load_skip(pk, cc)
    print(f"{now()} start {pk}: {len(E['items'])} items, {len(ids)} committed doc_ids known (skip)", flush=True)
    done_f = open(STATE / f"done_{pk}.jsonl", "a")
    W = StagedWriter(STAGE, cc, pid, batch_prefix=plat, chunk=a.chunk)
    pending = []  # done lines waiting for their chunk to be flushed
    def commit():
        seal_scans()
        for x in pending: done_f.write(json.dumps(x) + "\n")
        done_f.flush(); pending.clear()
    def on_term(signum, frame): raise KeyboardInterrupt(f"signal {signum}")
    signal.signal(signal.SIGTERM, on_term)
    try:
        _loop(E, a, W, ids, urls, pending, commit, pid, cc, plat, pk)
    except KeyboardInterrupt as e:
        print(f"{now()} interrupted ({e}) -> flushing buffered chunk", flush=True); rc = 130
    else: rc = 0
    finally:
        signal.alarm(0); nw = len(W.written); W.flush()
        if len(W.written) > nw or not W.buf: commit()
    if rc: print(f"{now()} flushed {W.written[-1:] or 'nothing'}; exit {rc}", flush=True); sys.exit(rc)

def _loop(E, a, W, ids, urls, pending, commit, pid, cc, plat, pk):
    P = Polite(a.delay); n = dict(ok=0, scanned=0, skip=0, err=0, sheet=0, robots=0); consec = 0
    for it in E["items"]:
        if STOP.exists(): print("stopfile -> stop", flush=True); break
        url = it["url"]; did = (f"{plat}:{E['doc_id_prefix']}~{hashlib.sha1(url.encode()).hexdigest()[:8]}" if E.get("doc_id_prefix")
               else f"{plat}:{hashlib.sha1(url.encode()).hexdigest()[:16]}")  # de_by_kreisrecht scheme
        if did in ids or url in urls: n["skip"] += 1; continue
        if url.lower().split("?")[0].endswith(SHEET_EXT): n["sheet"] += 1; continue
        pol, allowed = P.policy(url)
        if not allowed: n["robots"] += 1; continue
        r, err = P.get(url)
        if r is None or r[0] != 200:
            n["err"] += 1; consec += 1
            print(f"ERR {url[:120]} {err or r[0]}", flush=True)
            if consec >= 25: print("25 consecutive errors -> stop (no bypass)", flush=True); break
            continue
        consec = 0; ct = (r[1].get("Content-Type") or "").lower(); b = r[2]
        if "spreadsheet" in ct or "excel" in ct or "csv" in ct: n["sheet"] += 1; continue
        if not b.startswith(b"%PDF"):
            n["err"] += 1; print(f"NOTPDF {url[:120]} {ct} {b[:60]!r}", flush=True); continue
        txt = pdf_text(b); title = it["title"]
        rec = dict(place_id=pid, country_code=cc, doc_id=did, source_platform=plat, source_url=url,
                   doc_type=E.get("doc_type", "gazette_act"), language=E.get("language", "fr"), title_native=title,
                   number=it.get("number"), adopted_date=it.get("adopted_date"), published_date=it.get("published_date"),
                   consolidated=False, content_format="pdf_text", retrieved_at=now(), source_policy=pol,
                   source_official=True, source_org=E.get("source_org"))
        for k in ("place_name", "admin_level", "qid"):
            if E.get(k): rec[k] = E[k]
        # 2026-11-04: optional FETCH_STAMP_RE (env, unset = old behaviour): lines matching it (e.g. the prefecture e-transmission
        # stamp a portal overlays on scanned acts) don't count towards the 100-char text-layer test -> stamp-only scans go to staging/pdf.
        tchk = "\n".join(l for l in txt.splitlines() if not STAMP_RE.search(l)) if STAMP_RE else txt
        if len(re.sub(r"\s", "", tchk)) >= 100:
            rec["text"] = txt; n["ok"] += 1
        else:
            d = PDF_STAGE / cc / pk; d.mkdir(parents=True, exist_ok=True)
            fp = d / (did.replace(":", "_") + ".pdf"); tmp = fp.with_suffix(".pdf.tmp")
            tmp.write_bytes(b); os.rename(tmp, fp)
            rec.update(text="", content_complete=False,
                       extra_metadata={"pdf_bytes": len(b), "pdf_path": str(fp), "scanned_pdf": True}); n["scanned"] += 1
            SCANS.append(dict(doc_id=did, place_id=pid, place_key=pk, country_code=cc, source_url=url, sha256=hashlib.sha256(b).hexdigest(),
                              bytes=len(b), fetched_at=rec["retrieved_at"], source_policy=pol, lane="counties"))
        nw = len(W.written); pending.append({"doc_id": did, "source_url": url})
        e = W.add(rec)
        if e:
            if SCANS and SCANS[-1]["doc_id"] == did: SCANS.pop()
            pending.pop(); print("REJECT", did, e, flush=True); n["err"] += 1; continue
        ids.add(did)
        if len(W.written) > nw: commit()
        if a.limit and n["ok"] + n["scanned"] >= a.limit: break
    W.flush(); commit(); print("SUMMARY", pk, json.dumps(n), "files:", W.written, flush=True)

if __name__ == "__main__": main()
