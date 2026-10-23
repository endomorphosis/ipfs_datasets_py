"""World Law Scraper States & Provinces lane - shared helpers.

Lane:      states  (bot dir staging/states/, ARCHIVE_LANE=states)
Contract:  pipeline/SCHEMA.md v1.2.0 (adm1 => place_id iso:<ISO 3166-2>, admin_level "adm1", world_national_law)
Politeness: RFC 9309 robots (pipeline/scrapers/web/rfc9309.py), identifying UA, >= max(Crawl-delay, MIN_DELAY) per host,
           backoff on 429/5xx, no Cloudflare/captcha bypass, no proxies. Challenge pages abort the source.
Guards:    RSS <= RSS_LIMIT_MB (default 900), free disk on /workspace >= MIN_FREE_GB (35) before every write.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import fcntl, json, os, re, resource, shutil, sys, time, hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

PIPE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
sys.path.insert(0, str(PIPE)); sys.path.insert(0, str(PIPE / "scrapers" / "web"))
from schema import place_key, validate_record, validate_file  # noqa: E402
from rfc9309 import Robots  # noqa: E402

LANE = "states"
STAGING = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging")) / LANE
UA_TOKEN = "WorldLawStatesBot"
UA = (f"{UA_TOKEN}/0.1 (+https://github.com/endomorphosis/ipfs_datasets_py; state/provincial law research "
      "archive for endomorphosis/world_national_law; polite, ~1 req per 2-10 s per host)")
MIN_DELAY = float(os.environ.get("STATES_MIN_DELAY", "2.0"))
RSS_LIMIT_MB = int(os.environ.get("STATES_RSS_MB", "900"))
MIN_FREE_GB = float(os.environ.get("STATES_MIN_FREE_GB", "35"))
OCR_MANIFEST = STAGING / "_scanned_pdfs_manifest.jsonl"   # same format as asia_latam/eap (ocr/pdf_collect.load_eap)
CHALLENGE_MARKERS = (b"challenges.cloudflare.com", b"Just a moment...", b"cf-chl-", b"captcha", b"Request blocked.")


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def batch_ts():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class GuardError(RuntimeError):
    pass


def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


DISK_PAUSE_S = int(os.environ.get("STATES_DISK_PAUSE_S", "300"))


def check_guards():
    """Called before every write. Disk below the floor -> PAUSE (sleep and re-check, never crash, never delete);
    the pause is logged to stderr and to staging/states/_logs/DISK_FLOOR_HIT.log (no write while below the floor)."""
    free = shutil.disk_usage("/workspace").free / 1e9
    if free < MIN_FREE_GB:
        import sys as _s
        t0 = time.time()
        msg = f"{utcnow()} pid={os.getpid()} {' '.join(_s.argv)[:160]}: free disk {free:.1f} GB < {MIN_FREE_GB} GB - pausing writes"
        print(msg, file=_s.stderr, flush=True)
        try:
            with open(STAGING / "_logs" / "DISK_FLOOR_HIT.log", "a") as _f:
                _f.write(msg + "\n")
        except OSError:
            pass
        while free < MIN_FREE_GB:
            time.sleep(DISK_PAUSE_S)
            free = shutil.disk_usage("/workspace").free / 1e9
        print(f"{utcnow()} pid={os.getpid()}: free disk {free:.1f} GB again, resuming after {time.time() - t0:.0f}s", file=_s.stderr, flush=True)
    if rss_mb() > RSS_LIMIT_MB:
        raise GuardError(f"RSS {rss_mb():.0f} MB > {RSS_LIMIT_MB} MB")


# Hosts whose robots.txt answers 401/403 (no challenge) where the coordinator approved RFC 9309 "4xx => allow"
# semantics (2026-10-18). Content 403s/challenges still raise PermissionError and stop the run.
RFC9309_4XX_ALLOW_HOSTS = {"minio.legsanjuan.gob.ar"}


class PoliteSession:
    """requests.Session with RFC 9309 robots, per-host delay and challenge detection. Live fetches only."""

    def __init__(self, log=print):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en"})
        self.robots, self.last, self.log = {}, {}, log
        self.req_rate = {}   # host -> seconds per request from a non-standard 'Request-rate: n/s' line (honoured conservatively)

    def robots_for(self, url):
        p = urlparse(url); host = f"{p.scheme}://{p.netloc}"
        if host not in self.robots:
            try:
                r = self.s.get(host + "/robots.txt", timeout=30, allow_redirects=True)
                body = r.content
                if p.netloc in RFC9309_4XX_ALLOW_HOSTS and r.status_code in (401, 403) and not any(m in body for m in CHALLENGE_MARKERS):
                    # coordinator decision 2026-10-18: RFC 9309 sec. 2.3.1.3 (4xx => allow) for these hosts only;
                    # content pages must still serve normally (a 403/challenge on content stops the run)
                    rb, policy = Robots(allow_all=True), "robots_4xx_allow_rfc9309"
                elif any(m in body for m in CHALLENGE_MARKERS) or r.status_code in (401, 403):
                    rb, policy = Robots(disallow_all=True), "robots_unreachable"   # challenge/forbidden => disallow
                elif r.status_code >= 500:
                    rb, policy = Robots(disallow_all=True), "robots_unreachable"
                elif 400 <= r.status_code < 500 or "text/html" in r.headers.get("content-type", ""):
                    rb, policy = Robots(allow_all=True), "robots_404_allow_rfc9309"
                else:
                    rb, policy = Robots(r.text), "robots_allowed_rfc9309"
                    m = re.search(r"(?im)^\s*request-rate\s*:\s*(\d+)\s*/\s*(\d+)\s*([smh]?)", r.text)
                    if m and int(m.group(1)) > 0:
                        sec = int(m.group(2)) * {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(3).lower()]
                        self.req_rate[host] = sec / int(m.group(1))
            except requests.RequestException as e:
                self.log(f"robots unreachable {host}: {e}")
                rb, policy = Robots(disallow_all=True), "robots_unreachable"
            self.robots[host] = (rb, policy)
        return self.robots[host]

    def allowed(self, url):
        rb, policy = self.robots_for(url)
        return rb.can_fetch(UA, url), policy

    def delay_for(self, url):
        rb, _ = self.robots_for(url)
        p = urlparse(url)
        return max(MIN_DELAY, rb.crawl_delay(UA) or 0, self.req_rate.get(f"{p.scheme}://{p.netloc}", 0))

    def get(self, url, *, max_bytes=60_000_000, tries=4):
        ok, policy = self.allowed(url)
        if not ok:
            raise PermissionError(f"robots disallows {url} ({policy})")
        host = urlparse(url).netloc
        for attempt in range(tries):
            wait = self.last.get(host, 0) + self.delay_for(url) - time.time()
            if wait > 0:
                time.sleep(wait)
            self.last[host] = time.time()
            try:
                r = self.s.get(url, timeout=60, stream=True)
                body = r.raw.read(max_bytes + 1, decode_content=True); r.close()
            except requests.RequestException as e:
                self.log(f"neterr {url}: {e}"); time.sleep(5 * 2 ** attempt); continue
            if len(body) > max_bytes:
                raise ValueError(f"too large: {url}")
            if r.status_code == 429 or r.status_code >= 500:
                ra = r.headers.get("Retry-After", "")
                time.sleep(int(ra) if ra.isdigit() else 10 * 2 ** attempt); continue
            if r.status_code == 403 or any(m in body[:20000] for m in CHALLENGE_MARKERS[:3]):
                raise PermissionError(f"challenge/forbidden at {url} (status {r.status_code}) - not bypassing")
            r._content = body
            return r, policy
        raise RuntimeError(f"giving up on {url}")

    def post(self, url, *, data=None, max_bytes=60_000_000, tries=4):
        """Read-only form POST (only for sites whose public pages fetch their content this way); same robots/delay rules as get."""
        ok, policy = self.allowed(url)
        if not ok:
            raise PermissionError(f"robots disallows {url} ({policy})")
        host = urlparse(url).netloc
        for attempt in range(tries):
            wait = self.last.get(host, 0) + self.delay_for(url) - time.time()
            if wait > 0:
                time.sleep(wait)
            self.last[host] = time.time()
            try:
                r = self.s.post(url, data=data, timeout=60, stream=True)
                body = r.raw.read(max_bytes + 1, decode_content=True); r.close()
            except requests.RequestException as e:
                self.log(f"neterr {url}: {e}"); time.sleep(5 * 2 ** attempt); continue
            if len(body) > max_bytes:
                raise ValueError(f"too large: {url}")
            if r.status_code == 429 or r.status_code >= 500:
                ra = r.headers.get("Retry-After", "")
                time.sleep(int(ra) if ra.isdigit() else 10 * 2 ** attempt); continue
            if r.status_code == 403 or any(m in body[:20000] for m in CHALLENGE_MARKERS[:3]):
                raise PermissionError(f"challenge/forbidden at {url} (status {r.status_code}) - not bypassing")
            r._content = body
            return r, policy
        raise RuntimeError(f"giving up on {url}")


def stage_place(cc, place_id, rows, *, tag, review=False):
    """Validate rows and atomically write staging/states/<CC>/<place_key>.<tag>-<UTC>.jsonl. Returns (path, errors)."""
    check_guards()
    good, errors = [], []
    for r in rows:
        e = validate_record(r)
        (errors.append({"doc_id": r.get("doc_id"), "errors": e}) if e else good.append(r))
    if not good:
        return None, errors
    d = (STAGING / "_review" / cc) if review else (STAGING / cc); d.mkdir(parents=True, exist_ok=True)
    final = d / f"{place_key(place_id)}.{tag}-{batch_ts()}.jsonl"
    tmp = final.with_name("." + final.name)   # dot-file: ignored by run_loop until renamed; keeps .jsonl suffix for validate_file
    with tmp.open("w", encoding="utf-8") as f:
        for r in good:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())
    v = validate_file(str(tmp), expect_place_key=place_key(place_id))
    if not v.get("ok") or v.get("bad_rows") or v.get("file_errors"):
        errors.append({"file_validation": {"bad_rows": v.get("bad_rows"), "errors": [list(map(str, e)) for e in v.get("errors", [])[:20]],
                                           "file_errors": v.get("file_errors")}})
        bad_path = STAGING / "_rejected" / cc / final.name
        bad_path.parent.mkdir(parents=True, exist_ok=True); os.rename(tmp, bad_path)
        return None, errors
    os.rename(tmp, final)
    return final, errors


def queue_scanned_pdf(doc_id, place_id, cc, pdf_url, source_policy):
    """Append an image-only PDF to the lane's OCR handoff manifest (eap/asia_latam format), dedup by (place_key, doc_id)."""
    check_guards()
    STAGING.mkdir(parents=True, exist_ok=True)
    pk = place_key(place_id)
    rec = {"doc_id": doc_id, "place_key": pk, "place_id": place_id, "country_code": cc, "source_url": pdf_url,
           "local_path": None, "ocr_done": False, "source_policy": source_policy, "lane": LANE,
           "law_file": f"hf://endomorphosis/world_national_law/world_law/data/{cc}/{pk}_html.parquet",
           "queued_at": utcnow()}
    with open(OCR_MANIFEST.with_suffix(".lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        seen = set()
        if OCR_MANIFEST.exists():
            for line in OCR_MANIFEST.open(encoding="utf-8"):
                try:
                    o = json.loads(line); seen.add((o["place_key"], o["doc_id"]))
                except Exception:
                    pass
        if (pk, doc_id) in seen:
            return False
        with OCR_MANIFEST.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())
    return True


def pdf_has_text(data: bytes, min_chars=200):
    """True if pdftotext yields >= min_chars non-space chars (text layer present). Never OCRs."""
    import subprocess, tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf") as t:
        t.write(data); t.flush()
        out = subprocess.run(["pdftotext", "-layout", t.name, "-"], capture_output=True, timeout=120).stdout
    txt = out.decode("utf-8", "replace")
    return len("".join(txt.split())) >= min_chars, txt


def sha1(s):
    return hashlib.sha1(s.encode()).hexdigest()


def promote(review_path):
    """Move a reviewed file from staging/states/_review/<CC>/ to staging/states/<CC>/ (same FS, atomic rename) after re-validating."""
    check_guards()
    src = Path(review_path); cc = src.parent.name
    v = validate_file(str(src))
    if not v.get("ok") or v.get("bad_rows") or v.get("file_errors"):
        raise ValueError(f"validation failed: {v.get('bad_rows')} bad rows, {v.get('file_errors')}")
    dst = STAGING / cc / src.name; dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise FileExistsError(dst)
    os.rename(src, dst)
    return dst
