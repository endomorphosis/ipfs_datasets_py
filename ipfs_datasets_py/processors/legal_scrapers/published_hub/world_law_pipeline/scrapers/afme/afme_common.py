"""Shared helpers for the afme (Africa & Middle East) lane. Rebuilt 2026-11-02."""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, re, shutil, sys, time, resource
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("ARCHIVE_LANE", "afme")
ARCHIVE_LANE = os.environ["ARCHIVE_LANE"]
ROOT = Path(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law"))
OUT = ROOT / "out"
RAW = OUT / "afme" / "raw"            # unvalidated crawl output, per CC
DONE = OUT / "afme" / "done"          # done TSVs per country
STAGE = ROOT / "staging" / "afme"
LOGS = STAGE / "_logs"
CONFIG = OUT / "afme_config"
sys.path.insert(0, str(ROOT / "pipeline"))

UA = ("WorldLaw-afme/1.0 (JusticeDAO world_municipal_law legal research; "
      "+https://github.com/endomorphosis/ipfs_datasets_py; low-rate, contact via repo issues)")
DISK_STOP_GIB, DISK_WARN_GIB = 10.0, 12.0
RSS_LIMIT_MB = 300
# robots.txt is NOT enforced (Benjamin, 2026-11-01). Every live row says so honestly.
LIVE_POLICY = "robots_not_checked"

FORBIDDEN_FRAGMENTS = ("archive.today", "archive.ph", "archive.is")


def utc_ts():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DiskLow(SystemExit):
    pass


# Confirm / retry knobs (env-overridable for tests). Never stop on one reading.
DISK_CONFIRM_SECS = float(os.environ.get("AFME_DISK_CONFIRM_SECS", "240"))
DISK_CONFIRM_SAMPLES = max(2, int(os.environ.get("AFME_DISK_CONFIRM_SAMPLES", "3")))
DISK_RETRY_MAX_SECS = float(os.environ.get("AFME_DISK_RETRY_MAX_SECS", "7200"))
DISK_RETRY_SLEEP_SECS = float(os.environ.get("AFME_DISK_RETRY_SLEEP_SECS", "60"))


def disk_probe(path=ROOT):
    """Independent free-space readings (df / statvfs / shutil). Returns GiB dict; never raises."""
    path = str(path)
    out = {
        "path": path, "device": None,
        "df_avail_gib": None, "statvfs_avail_gib": None, "shutil_free_gib": None,
        "min_gib": None, "ok": False, "error": None,
    }
    try:
        out["device"] = os.stat(path).st_dev
    except OSError as e:
        out["error"] = f"stat:{e}"
        return out
    try:
        import subprocess
        r = subprocess.run(["df", "-P", path], capture_output=True, text=True, timeout=15)
        lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
        if len(lines) >= 2:
            cols = lines[-1].split()
            # Filesystem 1024-blocks Used Available Capacity Mounted-on
            out["df_avail_gib"] = int(cols[3]) * 1024 / 1024**3
    except Exception as e:  # noqa: BLE001
        out["df_error"] = str(e)
    try:
        st = os.statvfs(path)
        out["statvfs_avail_gib"] = st.f_bavail * st.f_frsize / 1024**3
    except OSError as e:
        out["statvfs_error"] = str(e)
    try:
        out["shutil_free_gib"] = shutil.disk_usage(path).free / 1024**3
    except OSError as e:
        out["shutil_error"] = str(e)
    vals = [v for v in (out["df_avail_gib"], out["statvfs_avail_gib"], out["shutil_free_gib"]) if v is not None]
    if vals:
        out["min_gib"] = min(vals)
        out["ok"] = out["min_gib"] >= DISK_STOP_GIB
    return out


def format_disk_probe(p):
    return (
        f"path={p.get('path')} dev={p.get('device')} "
        f"df={p.get('df_avail_gib')}G statvfs={p.get('statvfs_avail_gib')}G "
        f"shutil={p.get('shutil_free_gib')}G min={p.get('min_gib')}G ok={p.get('ok')}"
    )


def disk_check(path=ROOT, *, confirm_secs=None, confirm_samples=None, retry_max_secs=None):
    """Stop only when multi-source free space stays < DISK_STOP_GIB across a confirm
    window (default 4 min, >=2 samples) and still after a longer retry. Never stops
    on a single transient low reading. Warns below DISK_WARN_GIB.
    """
    confirm_secs = DISK_CONFIRM_SECS if confirm_secs is None else float(confirm_secs)
    confirm_samples = DISK_CONFIRM_SAMPLES if confirm_samples is None else max(2, int(confirm_samples))
    retry_max_secs = DISK_RETRY_MAX_SECS if retry_max_secs is None else float(retry_max_secs)

    probe = disk_probe(path)
    free = probe.get("min_gib")
    if free is None:
        log(f"WARN disk_check: no free-space readings ({format_disk_probe(probe)}); treating as OK this tick")
        return None
    if free >= DISK_STOP_GIB:
        if free < DISK_WARN_GIB:
            log(f"WARN disk {free:.1f} GiB free (< {DISK_WARN_GIB} GiB) {format_disk_probe(probe)}")
        return free

    # Apparent floor trip: confirm over confirm_secs with multi-source samples.
    log(f"disk below floor on first probe; confirming over {confirm_secs:.0f}s: {format_disk_probe(probe)}")
    samples = [probe]
    gaps = confirm_samples - 1
    interval = confirm_secs / gaps if gaps > 0 else confirm_secs
    all_low = True
    for i in range(1, confirm_samples):
        time.sleep(interval)
        p2 = disk_probe(path)
        samples.append(p2)
        log(f"disk confirm sample {i + 1}/{confirm_samples}: {format_disk_probe(p2)}")
        if p2.get("ok") or (p2.get("min_gib") is not None and p2["min_gib"] >= DISK_STOP_GIB):
            all_low = False
            free = p2["min_gib"]
            log(f"disk_ok: false low-disk reading discarded after confirm; continuing (min={free:.1f} GiB)")
            if free < DISK_WARN_GIB:
                log(f"WARN disk {free:.1f} GiB free (< {DISK_WARN_GIB} GiB)")
            return free
        if p2.get("min_gib") is not None:
            free = p2["min_gib"]

    if not (all_low and all(
        (s.get("min_gib") is not None and s["min_gib"] < DISK_STOP_GIB) for s in samples
    )):
        # Mixed/empty samples during confirm — do not stop
        log(f"WARN disk_check: inconclusive confirm ({format_disk_probe(samples[-1])}); not stopping")
        return samples[-1].get("min_gib")

    # Still low after confirm window: longer retry, recover ASAP if space returns.
    t0 = time.time()
    log(f"disk still low after {confirm_secs:.0f}s confirm; retrying up to {retry_max_secs:.0f}s "
        f"(floor={DISK_STOP_GIB} GiB, last min={free:.1f})")
    while (time.time() - t0) < retry_max_secs:
        time.sleep(DISK_RETRY_SLEEP_SECS)
        p3 = disk_probe(path)
        log(f"disk retry t={time.time() - t0:.0f}s: {format_disk_probe(p3)}")
        if p3.get("ok") or (p3.get("min_gib") is not None and p3["min_gib"] >= DISK_STOP_GIB):
            free = p3["min_gib"]
            log(f"disk recovered during retry (min={free:.1f} GiB); continuing")
            if free < DISK_WARN_GIB:
                log(f"WARN disk {free:.1f} GiB free (< {DISK_WARN_GIB} GiB)")
            return free
        if p3.get("min_gib") is not None:
            free = p3["min_gib"]

    raise DiskLow(
        f"disk guard: {free:.1f} GiB free < {DISK_STOP_GIB} GiB persisted "
        f"{confirm_secs:.0f}s confirm + {retry_max_secs:.0f}s retry "
        f"({format_disk_probe(disk_probe(path))}), stopping"
    )


def rss_mb():
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def mem_check():
    m = rss_mb()
    if m > RSS_LIMIT_MB:
        raise SystemExit(f"memory guard: RSS {m:.0f} MB > {RSS_LIMIT_MB} MB, stopping")
    return m


def cap_address_space():
    """Hard backstop: cap virtual memory a bit above the soft RSS limit (single process)."""
    lim = int(os.environ.get("AFME_AS_LIMIT_MB", "1200")) * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
    except (ValueError, OSError):
        pass


def log(msg):
    print(f"{utc_iso()} [afme] {msg}", file=sys.stderr, flush=True)


# --- challenge / WAF detection: we never bypass, we skip ---
_CHALLENGE_RE = re.compile(
    rb"(cf-browser-verification|challenge-platform|__cf_chl_|Just a moment\.\.\.|Attention Required! \| Cloudflare|"
    rb"g-recaptcha|h-captcha|hcaptcha\.com|captcha-delivery|Incapsula incident|_Incapsula_Resource|"
    rb"Request unsuccessful\. Incapsula|Access Denied.{0,200}Reference #|sucuri_cloudproxy|"
    rb"The requested URL was rejected\. Please consult with your administrator|ddos-guard)", re.I | re.S)


def is_challenge(status, headers, body: bytes):
    h = {k.lower(): str(v).lower() for k, v in (headers or {}).items()}
    if h.get("cf-mitigated") == "challenge":
        return "cloudflare_challenge"
    if status in (403, 429, 503) and ("cloudflare" in h.get("server", "") or "cf-ray" in h):
        return f"cloudflare_{status}"
    if _CHALLENGE_RE.search(body[:200_000] if body else b""):
        return "challenge_page"
    return None


# --- done TSVs: one per country, columns key \t status \t utc \t note ---
def done_path(kind, cc):
    DONE.mkdir(parents=True, exist_ok=True)
    return DONE / f"{kind}_{cc}.tsv"


def load_done(kind, cc):
    p = done_path(kind, cc)
    s = set()
    if p.exists():
        for line in p.open(encoding="utf-8"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[1] in ("ok", "miss", "skip_challenge", "empty"):
                s.add(parts[0])
    return s


def mark_done(kind, cc, key, status, note=""):
    with done_path(kind, cc).open("a", encoding="utf-8") as f:
        f.write(f"{key}\t{status}\t{utc_iso()}\t{note.replace(chr(9), ' ').replace(chr(10), ' ')[:300]}\n")


def write_raw(cc, pkey, tag, rows):
    """Write crawl output atomically to out/afme/raw/<CC>/<pkey>.<tag><UTC>.jsonl (not staged yet)."""
    if not rows:
        return None
    disk_check()
    d = RAW / cc
    d.mkdir(parents=True, exist_ok=True)
    final = d / f"{pkey}.{tag}{utc_ts()}.jsonl"
    n = 1
    while final.exists():
        final = d / f"{pkey}.{tag}{utc_ts()}b{n:04d}.jsonl"; n += 1
    tmp = final.with_name(final.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())
    os.rename(tmp, final)
    return final


def load_config(cc):
    p = CONFIG / f"{cc.upper()}.json"
    return json.loads(p.read_text(encoding="utf-8"))
