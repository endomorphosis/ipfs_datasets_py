#!/usr/bin/env python3
"""South African metro by-laws from the metros' OFFICIAL websites -> endomorphosis/ipfs_south_africa_municipal_laws.

Batch 1 (CoS GO 2026-10-04): eThekwini (durban.gov.za), Ekurhuleni (ekurhuleni.gov.za), Buffalo City (buffalocity.gov.za).
Parked: Johannesburg, Nelson Mandela Bay (terms). Deferred: Tshwane (OCR). Skipped: Cape Town, Mangaung (terms).

Rules: every request + redirect hop via robots_guard (>=5 s per host); challenge page => hard stop (no workarounds);
no logins. TLS: system CA verification everywhere; for www.durban.gov.za (server omits its intermediate) a
host-scoped bundle = Sectigo DV R36 intermediate (fetched from the leaf's AIA CA-Issuers URL via robots_guard) +
system CAs, hostname verification on. If that host still fails TLS the site is SKIPPED (no verify=False).
Gates: hard stop if disk free on / < 12,500 MiB, MemAvailable < 3 GiB at any moment or < 4 GiB held 60 s.
Staging: /dev/shm/muni_africa/za (<1.5 GB). PDFs streamed to /dev/shm tmp, pdftotext, deleted. Resumable via records.jsonl.
This collector only fetches + extracts text; selection/dedupe/notice-split/section-split happen offline in
stage_za_metros_muni.py.
Run only under:  flock -n -E 75 /dev/shm/muni_runner.lock python3 collect_za_metros_muni.py
"""
from __future__ import annotations
import hashlib, html as _html, json, os, re, subprocess, sys, threading, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

STAGE = Path(os.environ.get("MUNI_STAGE", "/dev/shm/muni_africa/za"))
os.environ.setdefault("LEGAL_CORPORA_ROOT", str(STAGE / "root"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import certifi  # noqa: E402
import robots_guard as rg  # noqa: E402

rg.set_country("za")
REC = STAGE / "records.jsonl"
LISTINGS = STAGE / "listings.jsonl"
STATE = STAGE / "state.json"
TMP = STAGE / "tmp"
DURBAN_BUNDLE = STAGE / "tls" / "durban_bundle.pem"
TSHWANE_BUNDLE = STAGE / "tls" / "tshwane_bundle.pem"
OCR_DIR = STAGE / "ocr"
BATCH = int(os.environ.get("ZA_BATCH", "1"))
OCR_ENABLED = os.environ.get("ZA_OCR", "0") == "1"
OCR_DPI = int(os.environ.get("ZA_OCR_DPI", "250"))
DISK_STOP_MIB = 12500
MEM_HARD_GIB = 3.0
MEM_SOFT_GIB = 4.0
MEM_SOFT_HOLD_S = 60
STAGE_MAX_BYTES = int(float(os.environ.get("ZA_STAGE_MAX_GB", "1.0")) * 1024**3)   # fleet rules v2: RAM staging <= 1 GB
RSS_MAX_BYTES = int(float(os.environ.get("ZA_RSS_MAX_GB", "1.0")) * 1024**3)       # v2: runner RSS (whole process tree) <= 1 GiB
OCR_WORKERS = max(1, min(3, int(os.environ.get("ZA_OCR_WORKERS", "3"))))          # v2: <= 3 OCR worker processes
MAX_PENDING_DOCS = int(os.environ.get("ZA_OCR_PENDING_DOCS", "3"))                # fetched docs waiting for OCR
# v2 slots: the wrapper passes the slot it holds; the newest-started slot pauses first under memory pressure
SLOT = os.environ.get("MUNI_SLOT", "")
SLOT_LOCKS = {"slot1": "/dev/shm/muni_runner.lock", "slot2": "/dev/shm/muni_runner.slot2.lock",
              "slot3": "/dev/shm/muni_runner.slot3.lock"}
SLOT_STARTS = Path(os.environ.get("MUNI_SLOT_STARTS", "/dev/shm/muni_slot_starts"))
MAX_DOC = 40 * 1024 * 1024
MAX_HTML = 15 * 1024 * 1024
CHALLENGE = re.compile(r"Just a moment\.\.\.|_cf_chl_opt|cf-browser-verification|challenge-platform|captcha|Attention Required|Incapsula|Request Rejected", re.I)

METROS = {
    "eth": {"name": "eThekwini Metropolitan Municipality", "listing": "https://www.durban.gov.za/pages/government/documents?d=Promulgated%20By-Laws"},
    "ekh": {"name": "City of Ekurhuleni Metropolitan Municipality", "listing": "https://www.ekurhuleni.gov.za/my-council/by-laws-policies/by-laws/"},
    "bcm": {"name": "Buffalo City Metropolitan Municipality", "listing": "https://www.buffalocity.gov.za/folder.php?id=sSWeUsCZg"},
    "tsh": {"name": "City of Tshwane Metropolitan Municipality", "listing": "https://www.tshwane.gov.za/?page_id=7469"},
}
# Host-scoped CA bundles (system CAs + the intermediate the server omits, fetched from the leaf's AIA via robots_guard).
# Hostname verification stays on; no verify=False anywhere.
HOST_VERIFY = {"www.durban.gov.za": str(DURBAN_BUNDLE), "durban.gov.za": str(DURBAN_BUNDLE),
               "www.tshwane.gov.za": str(TSHWANE_BUNDLE), "tshwane.gov.za": str(TSHWANE_BUNDLE)}
# robots_guard's own robots.txt fetch uses the same host bundles (certifi for every other host; TLS failure = fail closed).
for _h, _p in HOST_VERIFY.items():
    if hasattr(rg, "set_ca_bundle"):
        rg.set_ca_bundle(_h, _p)


def _verify_for(url):
    """certifi by default; the host-only bundle where the server omits its intermediate. Never False."""
    h = urlsplit(url).hostname or ""
    if h in HOST_VERIFY:
        return HOST_VERIFY[h]
    return rg.ca_verify_for(url) if hasattr(rg, "ca_verify_for") else certifi.where()

S = rg.GuardedSession()
S.headers["User-Agent"] = rg.ROBOTS_UA
S.min_interval = 5.0
S.max_redirects = 5
COUNT = {"requests": 0, "robots_skips": 0, "errors": 0, "too_large": 0, "tls_fail": 0}


class HardStop(Exception):
    pass


class SiteSkip(Exception):
    pass


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def du(p: Path) -> int:
    t = 0
    for dp, _, fs in os.walk(p):
        for f in fs:
            try:
                t += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return t


def mem_gib():
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 2**20
    return 0.0


STOP = {"reason": None, "kind": None}      # kind: hard | pause | slice
_ACTIVE, _ACTIVE_LOCK = set(), threading.Lock()


def run_cmd(args, timeout, env=None):
    """subprocess.run replacement that registers the child so a hard stop can kill it immediately."""
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    with _ACTIVE_LOCK:
        _ACTIVE.add(p)
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out
    except subprocess.TimeoutExpired:
        p.kill(); p.communicate()
        return -9, b""
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(p)


def kill_children():
    with _ACTIVE_LOCK:
        for p in list(_ACTIVE):
            try:
                p.kill()
            except Exception:
                pass


def stop(reason, kind):
    if STOP["reason"] is None:
        STOP["reason"], STOP["kind"] = reason, kind
        log("STOP requested:", kind, reason)
    kill_children()


def tree_rss_bytes():
    """VmRSS of this process plus all its descendants (OCR workers: pdftoppm / tesseract / soffice)."""
    kids = {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                ppid = int(open(f"/proc/{d}/stat").read().rsplit(")", 1)[1].split()[1])
                kids.setdefault(ppid, []).append(int(d))
            except Exception:
                pass
    tot, todo = 0, [os.getpid()]
    while todo:
        pid = todo.pop()
        todo += kids.get(pid, [])
        try:
            for line in open(f"/proc/{pid}/status"):
                if line.startswith("VmRSS:"):
                    tot += int(line.split()[1]) * 1024
                    break
        except Exception:
            pass
    return tot


def _proc_start(pid):
    try:
        ticks = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[19])
        btime = next(int(l.split()[1]) for l in open("/proc/stat") if l.startswith("btime"))
        return btime + ticks / os.sysconf("SC_CLK_TCK")
    except Exception:
        return None


def slot_starts():
    """{slot: start_epoch} for every slot whose lock is currently held. Start = the slot's start file
    (/dev/shm/muni_slot_starts/<slot>, written by runners that record it) when its lock_pid matches the
    holder in /proc/locks, else the start time of the holder process itself."""
    holders = {}
    try:
        locks = open("/proc/locks").read().splitlines()
    except OSError:
        locks = []
    for slot, path in SLOT_LOCKS.items():
        try:
            st = os.stat(path)
        except OSError:
            continue
        dev = f"{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino}"
        for l in locks:
            f = l.split()
            if "FLOCK" in f and "->" not in f and dev in f:
                holders[slot] = int(f[f.index(dev) - 1])
    out = {}
    for slot, pid in holders.items():
        t = None
        try:
            j = json.loads((SLOT_STARTS / slot).read_text())
            if int(j.get("lock_pid", -1)) == pid:
                t = float(j["start"])
        except Exception:
            pass
        out[slot] = t if t is not None else _proc_start(pid)
    return out


def newer_slots_than_mine():
    """How many other held slots started after ours (0 = we are the newest)."""
    ss = slot_starts()
    mine = ss.get(SLOT)
    if mine is None:
        return 0
    return sum(1 for k, v in ss.items() if k != SLOT and v is not None and v > mine)


def watchdog():
    """Fleet rules v2. MemAvailable < 3 GiB (instant) or disk < 12,500 MiB: checkpoint + stop now (hard).
    MemAvailable < 4 GiB held 60 s: the newest-started slot pauses first; a slot with k newer slots waits
    another 60 s per newer slot and pauses only if the condition persists. RSS (process tree) > 1 GiB or
    staging > 1 GB: checkpoint + stop."""
    low_since, n = None, 0
    while STOP["reason"] is None:
        m = mem_gib()
        st = os.statvfs("/")
        free = st.f_bavail * st.f_frsize / 2**20
        if m < MEM_HARD_GIB:
            stop(f"MemAvailable {m:.2f} GiB < {MEM_HARD_GIB} (instant)", "hard")
        elif free < DISK_STOP_MIB:
            stop(f"disk free {free:.0f} MiB < {DISK_STOP_MIB}", "hard")
        elif m < MEM_SOFT_GIB:
            low_since = low_since or time.time()
            held = time.time() - low_since
            if held >= MEM_SOFT_HOLD_S:
                k = newer_slots_than_mine()
                if held >= MEM_SOFT_HOLD_S * (k + 1):
                    stop(f"MemAvailable < {MEM_SOFT_GIB} GiB held {held:.0f}s; {k} newer slot(s) held; pausing {SLOT or 'slot?'}", "pause")
        else:
            low_since = None
        rss = tree_rss_bytes()
        if rss > RSS_MAX_BYTES:
            stop(f"runner RSS {rss / 2**20:.0f} MiB > {RSS_MAX_BYTES / 2**20:.0f}", "hard")
        n += 1
        if n % 6 == 0 and du(STAGE) > STAGE_MAX_BYTES:
            stop(f"staging > {STAGE_MAX_BYTES / 2**30:.1f} GB", "hard")
        time.sleep(5)


def gates():
    if STOP["reason"]:
        raise HardStop(STOP["reason"])
    m = mem_gib()
    if m < MEM_HARD_GIB:
        raise HardStop(f"MemAvailable {m:.2f} GiB < {MEM_HARD_GIB}")
    st = os.statvfs("/")
    if st.f_bavail * st.f_frsize / 2**20 < DISK_STOP_MIB:
        raise HardStop("disk free < 12500 MiB")
    if du(STAGE) > STAGE_MAX_BYTES:
        raise HardStop(f"staging >= {STAGE_MAX_BYTES / 2**30:.1f} GB")


def get(url, *, stream_to: Path | None = None, cap=MAX_HTML):
    """Guarded GET. Returns (status, text|None, final_url, nbytes, ctype)."""
    gates()
    verify = _verify_for(url)
    for attempt in range(3):
        try:
            COUNT["requests"] += 1
            r = S.get(url, timeout=(20, 120), stream=True, verify=verify)
        except rg.RobotsBlocked as e:
            COUNT["robots_skips"] += 1
            rg.log_robots_blocked(e, caller="collect_za_metros_muni")
            return ("robots", None, url, 0, "")
        except Exception as e:
            if "SSL" in type(e).__name__ or "CERTIFICATE" in str(e).upper():
                COUNT["tls_fail"] += 1
                raise SiteSkip(f"TLS verification failed for {urlsplit(url).hostname}: {str(e)[:160]}")
            COUNT["errors"] += 1
            log("net error", url, type(e).__name__, str(e)[:120])
            time.sleep(30)
            continue
        COUNT["requests"] += len(r.history)
        if r.status_code in (429, 502, 503, 504):
            r.close()
            log("backoff", r.status_code, url)
            time.sleep(60 * (attempt + 1))
            continue
        ctype = r.headers.get("content-type", "")
        clen = int(r.headers.get("content-length") or 0)
        if clen and clen > cap:
            r.close()
            COUNT["too_large"] += 1
            return ("too_large", None, r.url, clen, ctype)
        n = 0
        if stream_to is not None:
            with open(stream_to, "wb") as fh:
                for ch in r.iter_content(262144):
                    n += len(ch)
                    if n > cap:
                        r.close()
                        COUNT["too_large"] += 1
                        return ("too_large", None, r.url, n, ctype)
                    fh.write(ch)
            r.close()
            head = open(stream_to, "rb").read(4096)
            if b"<html" in head.lower() and CHALLENGE.search(head.decode("latin-1")):
                raise HardStop(f"WAF/challenge page at {url} - stopping (no workarounds)")
            return (r.status_code, None, r.url, n, ctype)
        raw = b""
        for ch in r.iter_content(262144):
            raw += ch
            if len(raw) > cap:
                break
        r.close()
        txt = raw.decode(r.encoding or "utf-8", "replace")
        if CHALLENGE.search(txt[:8000]):
            raise HardStop(f"WAF/challenge page at {url} - stopping (no workarounds)")
        return (r.status_code, txt, r.url, len(raw), ctype)
    return ("failed", None, url, 0, "")


def clean(s):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


# ---------------------------------------------------------------- listings
def list_eth(h, base):
    out = []
    for href, title, date in re.findall(
            r'<a href="([^"]+\.pdf)"[^>]*>\s*<div class="services-box-2.*?<h4[^>]*>(.*?)</h4>\s*<small[^>]*>(.*?)</small>', h, re.S):
        out.append({"url": urljoin(base, _html.unescape(href)), "list_title": clean(title), "list_date": clean(date)})
    return out


def list_ekh(h, base):
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
        cells = [clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        links = re.findall(r'href="([^"]+\.pdf)"', row)
        if cells and links:
            out.append({"url": urljoin(base, _html.unescape(links[0])), "list_title": cells[0], "list_date": cells[-1]})
    return out


def list_bcm(h, base):
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
        cells = [clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        links = re.findall(r"href=['\"]([^'\"]+)['\"]", row)
        if len(cells) >= 3 and links:
            out.append({"url": urljoin(base, _html.unescape(links[0])), "list_title": cells[1], "list_date": cells[2]})
    return out


def list_tsh(h, base):
    """Promulgated by-laws page: WP File Download links (admin-ajax ... task=file.download ... wpfd_file_id=N, plain
    public links in the HTML, no nonce) plus direct /wp-content/uploads PDFs."""
    out, seen = [], set()
    i = h.find("Promulgated By-Laws")
    body = h[i:] if i > 0 else h
    for href, inner in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
        u = urljoin(base, _html.unescape(href))
        if not ("wpfd_file_id=" in u or re.search(r"/wp-content/uploads/.+\.pdf$", u, re.I)):
            continue
        t = clean(inner)
        if not t or u in seen:
            continue
        seen.add(u)
        out.append({"url": u, "list_title": t, "list_date": ""})
    return out


LISTERS = {"eth": list_eth, "ekh": list_ekh, "bcm": list_bcm, "tsh": list_tsh}

# Obvious non-candidates (never fetched). Everything else is fetched; the stager makes the final call.
PREDROP = [
    (re.compile(r"isizulu|\(zulu\)|\(sotho\)|zulu\.pdf|sotho\.pdf", re.I), "language_variant"),
    (re.compile(r"\bdraft", re.I), "draft"),
    (re.compile(r"\bform(s)?\b|_form\b|application.form", re.I), "form"),
    (re.compile(r"bylaws-unpacked|unpacked", re.I), "explainer"),
    (re.compile(r"polic(y|_)", re.I), "policy"),
    (re.compile(r"conditions of carriage", re.I), "other_conditions_of_carriage"),
    (re.compile(r"splum by-law schedule", re.I), "other_schedule_only"),
    (re.compile(r"^correction notice", re.I), "correction_notice"),
    (re.compile(r"town-?planning scheme", re.I), "not_bylaw_town_planning_scheme"),
    (re.compile(r"for gazetting", re.I), "pre_gazette_version"),
]
POLICY_EXEMPT = re.compile(r"by-?laws?\s+and\s+polic", re.I)   # e.g. "Property Rates By-Law And Policy" (gazetted by-law)


def predrop(item):
    s = item["list_title"] + " " + item["url"]
    for rx, why in PREDROP:
        if why == "policy" and POLICY_EXEMPT.search(item["list_title"]):
            continue
        if rx.search(s):
            return why
    return None


STAMP_LINES = re.compile(r"(?im)^.*(?:Reproduced by Sabinet|Copyright Authority No|GICS\.co\.za|PROVINCIAL GAZETTE|PROVINSIALE KOERANT|"
                         r"^\s*(?:LOCAL AUTHORITY|PROVINCIAL) NOTICE \d+\s*$|^\s*\d{1,4}\s*$).*$")


def extract(path: Path, ctype: str, url: str):
    head = open(path, "rb").read(8)
    if head.startswith(b"%PDF"):
        info = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=60).stdout
        pages = re.search(r"Pages:\s+(\d+)", info)
        txt = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
                             capture_output=True, timeout=300).stdout.decode("utf-8", "replace")
        return txt, "pdftotext", int(pages.group(1)) if pages else None
    if head.startswith(b"\xd0\xcf\x11\xe0") or url.lower().endswith((".doc", ".docx")) or head.startswith(b"PK"):
        out = TMP / "docout"
        out.mkdir(exist_ok=True)
        src = TMP / ("doc" + (".docx" if head.startswith(b"PK") else ".doc"))
        path.rename(src)
        subprocess.run(["soffice", "--headless", "--convert-to", "txt:Text", "--outdir", str(out), str(src)],
                       capture_output=True, timeout=300)
        t = out / (src.stem + ".txt")
        txt = t.read_text("utf-8", "replace") if t.exists() else ""
        for p in (t, src):
            try:
                p.unlink()
            except OSError:
                pass
        return txt, "soffice_txt", None
    return "", "unknown_format", None


def _mean_conf(tsv_path):
    tot = n = 0.0
    try:
        for line in open(tsv_path, encoding="utf-8", errors="replace").read().splitlines()[1:]:
            c = line.split("\t")
            if len(c) >= 12 and c[11].strip():
                try:
                    v = float(c[10])
                except ValueError:
                    continue
                if v >= 0:
                    tot += v; n += 1
    except OSError:
        pass
    return (tot / n if n else None), int(n)


def count_renderable_pages(pdf: Path, cap=400):
    """Fallback page count when pdfinfo fails: render each page at 10 dpi until pdftoppm produces nothing."""
    n = 0
    for k in range(1, cap + 1):
        base = TMP / "probe"
        subprocess.run(["pdftoppm", "-f", str(k), "-l", str(k), "-r", "10", "-gray", "-png", "-singlefile",
                        str(pdf), str(base)], capture_output=True, timeout=120)
        img = TMP / "probe.png"
        if not img.exists():
            break
        img.unlink()
        n = k
    return n


def ocr_page(pdf: Path, workdir: Path, n: int):
    """OCR ONE page (pdftoppm -f N -l N -> tesseract eng txt+tsv -> delete the image). Runs in a worker thread;
    each worker drives one pdftoppm/tesseract process at a time (OMP_THREAD_LIMIT=1), so <= OCR_WORKERS OCR
    processes. Checkpoint: pNNNN.txt then pNNNN.json, each written to a temp name and renamed; the .json is
    written last and marks the page done, so a stop at any moment leaves either a complete page or none."""
    txt_p, meta_p = workdir / f"p{n:04d}.txt", workdir / f"p{n:04d}.json"
    if meta_p.exists() or STOP["reason"]:
        return
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    tag = TMP / f"ocr_{workdir.name}_{n:04d}"
    img = Path(str(tag) + ".png")
    conf, words, err = None, 0, None
    try:
        run_cmd(["pdftoppm", "-f", str(n), "-l", str(n), "-r", str(OCR_DPI), "-gray", "-png", "-singlefile",
                 str(pdf), str(tag)], 300)
        txt = ""
        if img.exists() and not STOP["reason"]:
            rc, _ = run_cmd(["tesseract", str(img), str(tag), "-l", "eng", "--psm", "3", "txt", "tsv"], 600, env=env)
            t = Path(str(tag) + ".txt")
            txt = t.read_text("utf-8", "replace") if t.exists() else ""
            conf, words = _mean_conf(Path(str(tag) + ".tsv"))
            if rc != 0:
                err = f"tesseract_rc_{rc}"
        if STOP["reason"]:          # killed mid-page: leave no checkpoint for this page
            return
        tmp_t, tmp_m = txt_p.with_suffix(".txt.part"), meta_p.with_suffix(".json.part")
        tmp_t.write_text(txt)
        os.replace(tmp_t, txt_p)
        tmp_m.write_text(json.dumps({"page": n, "conf": conf, "words": words, "rendered": img.exists(), "error": err}))
        os.replace(tmp_m, meta_p)
    finally:
        for suf in (".png", ".txt", ".tsv"):
            try:
                os.unlink(str(tag) + suf)
            except OSError:
                pass


def ocr_assemble(workdir: Path, npages: int):
    texts, confs = [], []
    for n in range(1, npages + 1):
        texts.append((workdir / f"p{n:04d}.txt").read_text("utf-8", "replace"))
        confs.append(json.loads((workdir / f"p{n:04d}.json").read_text()))
    ws = sum(c["words"] for c in confs)
    mean = (sum((c["conf"] or 0) * c["words"] for c in confs) / ws) if ws else None
    return "\f".join(texts), mean, [round(c["conf"], 1) if c["conf"] is not None else None for c in confs]


def ocr_missing(workdir: Path, npages: int):
    return [n for n in range(1, npages + 1) if not (workdir / f"p{n:04d}.json").exists()]


OCR_MAX_PAGES = int(os.environ.get("ZA_OCR_MAX_PAGES", "300"))


def _sha_index(h, url):
    if not h:
        return
    idx_p = STAGE / "doc_sha1.json"
    idx = json.loads(idx_p.read_text()) if idx_p.exists() else {}
    idx.setdefault(h, url)
    idx_p.write_text(json.dumps(idx))


def fetch_and_extract(code, it, rec):
    """Fetch one document and extract text. With ZA_OCR=1, PDFs without a text layer are OCRed page by page;
    the PDF is kept in OCR_DIR/<sha1> until its OCR completes (resume mid-document), then deleted."""
    wid = OCR_DIR / hashlib.sha1(it["url"].encode()).hexdigest()[:16]
    pdf_keep = wid / "doc.pdf"
    tmp = TMP / "doc.bin"
    if pdf_keep.exists() and (wid / "fetch.json").exists():   # resume an interrupted OCR: no re-fetch
        st, final_u, n, ctype = 200, json.loads((wid / "fetch.json").read_text())["final_url"], pdf_keep.stat().st_size, "application/pdf"
        src = pdf_keep
    else:
        st, _, final_u, n, ctype = get(it["url"], stream_to=tmp, cap=MAX_DOC)
        src = tmp
    rec.update({"status": st, "final_url": final_u, "bytes": n, "content_type": ctype})
    if st == 200:
        h = hashlib.sha1(open(src, "rb").read()).hexdigest()
        rec["sha1"] = h
        idx_p = STAGE / "doc_sha1.json"
        idx = json.loads(idx_p.read_text()) if idx_p.exists() else {}
        if h not in idx and OCR_DIR.exists():      # also match documents still being OCRed (pending jobs)
            for fj in OCR_DIR.glob("*/fetch.json"):
                try:
                    j = json.loads(fj.read_text())
                except Exception:
                    continue
                if j.get("sha1") == h and j.get("url") != it["url"]:
                    idx = dict(idx, **{h: j["url"]})
                    break
        if h in idx and idx[h] != it["url"]:       # byte-identical repeat upload: no second OCR
            rec.update({"text": "", "text_backend": "duplicate_bytes", "duplicate_of": idx[h], "final": True})
            src.unlink()
            if wid.exists():
                for q in wid.glob("*"):
                    q.unlink()
                wid.rmdir()
            return rec
    if st != 200:
        rec["final"] = st in ("robots", "too_large")
        try:
            tmp.unlink()
        except OSError:
            pass
        return rec
    try:
        txt, backend, pages = extract(src, ctype, it["url"])
    except Exception as e:
        txt, backend, pages = "", f"extract_error_{type(e).__name__}", None
    # body text only: reproduction stamps (Sabinet / GICS) and gazette page headers are a text layer on otherwise scanned
    # pages (batch 3 finding: Tshwane Flats/Hostels 2010 had only these lines), so they must not count as a text layer
    body = STAMP_LINES.sub("", txt)
    no_layer = len(re.sub(r"\s", "", body)) < max(200, 100 * (pages or 1))
    if OCR_ENABLED and no_layer and backend == "pdftotext":
        if pages is None:          # pdfinfo could not read the page tree: probe-render until a page fails (cap)
            pages = count_renderable_pages(src)
            if not pages:
                rec.update({"text": "", "text_backend": "ocr_skipped_unreadable_pdf", "pages": None, "no_text_layer": True})
                try:
                    src.unlink()
                except OSError:
                    pass
                return rec
        if pages > OCR_MAX_PAGES:
            rec.update({"text": "", "text_backend": "ocr_skipped_too_many_pages", "pages": pages, "no_text_layer": True})
            src.unlink()
            return rec
        wid.mkdir(parents=True, exist_ok=True)
        if src != pdf_keep:
            (wid / "fetch.json").write_text(json.dumps({"url": it["url"], "final_url": final_u, "pages": pages,
                                                         "sha1": rec.get("sha1"), "bytes": n, "content_type": ctype}))
            src.rename(pdf_keep)
        todo = ocr_missing(wid, pages)
        log(f"  OCR queued {len(todo)}/{pages} pages: {it['list_title'][:70]}")
        return {"_ocr_job": True, "rec": rec, "wid": wid, "pdf": pdf_keep, "pages": pages, "url": it["url"],
                "title": it["list_title"], "t0": time.time()}
    txt = re.sub(r"[ \t]+\n", "\n", txt)
    _sha_index(rec.get("sha1"), it["url"])
    rec.update({"text": txt, "text_backend": backend, "text_source": backend, "pages": pages, "no_text_layer": no_layer})
    try:
        src.unlink()
    except OSError:
        pass
    return rec


def _write_rec(rec):
    with open(REC, "a") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _reap(pending, block=False):
    """Finalize OCR jobs whose pages are all checkpointed (main thread only). With block=True wait until at
    least one job finishes (or a stop is requested)."""
    while True:
        finished_any = False
        for job in list(pending):
            if all(f.done() for f in job["futs"]):
                finished_any = True
                for f in job["futs"]:
                    if f.exception() is not None:
                        log("  ocr worker error:", repr(f.exception())[:200])
                missing = ocr_missing(job["wid"], job["pages"])
                pending.remove(job)
                if missing:          # stopped mid-document: pages stay checkpointed for the next slice
                    continue
                txt, mean, pconfs = ocr_assemble(job["wid"], job["pages"])
                rec = job["rec"]
                _sha_index(rec.get("sha1"), job["url"])
                rec.update({"text": txt, "text_backend": "ocr_tesseract_eng", "text_source": "ocr_tesseract_eng",
                            "ocr_dpi": OCR_DPI, "ocr_mean_conf": round(mean, 1) if mean is not None else None,
                            "ocr_page_conf": pconfs, "pages": job["pages"], "no_text_layer": True,
                            "ocr_workers": OCR_WORKERS})
                _write_rec(rec)
                for q in sorted(job["wid"].glob("*")):
                    q.unlink()
                job["wid"].rmdir()          # raw PDF deleted once its OCR is complete
                log(f"  OCR done {job['pages']}p conf={rec['ocr_mean_conf']} in {time.time() - job['t0']:.0f}s: {job['title'][:60]}")
                job["done_set"].add(job["url"])
        if not block or finished_any or not pending or STOP["reason"]:
            return
        time.sleep(1)


def main():
    import signal
    from concurrent.futures import ThreadPoolExecutor
    # graceful end of a 3 h slice (timeout sends TERM): stop at the next gate check; OCR checkpoints are per page
    signal.signal(signal.SIGTERM, lambda *_: stop("SIGTERM (slice end)", "slice"))
    STAGE.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=watchdog, daemon=True).start()
    gates()
    if SLOT:
        # v2 stagger, belt and braces: other bots may not touch /dev/shm/muni_last_start, so also refuse to start
        # within 300 s of another slot's start as seen in /proc/locks (wrapper treats rc 76 as 'retry in 60 s').
        mine_t = time.time()
        recent = {k: round(mine_t - v) for k, v in slot_starts().items() if k != SLOT and v and 0 <= mine_t - v < 300}
        if recent:
            log(f"stagger: other slot(s) started {recent} s ago (<300 s); not starting")
            return 76
        # record our slot start (v2: lets runners tell which slot started most recently)
        SLOT_STARTS.mkdir(parents=True, exist_ok=True)
        lock_pid = None
        try:
            st = os.stat(SLOT_LOCKS[SLOT])
            dev = f"{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino}"
            for l in open("/proc/locks").read().splitlines():
                f = l.split()
                if "FLOCK" in f and "->" not in f and dev in f:
                    lock_pid = int(f[f.index(dev) - 1])
        except Exception:
            pass
        (SLOT_STARTS / SLOT).write_text(json.dumps({"bot": "africa-za", "slot": SLOT, "lock_pid": lock_pid,
                                                    "runner_pid": os.getpid(), "start": time.time(), "at": now()}))
        log(f"slot {SLOT} (lock holder pid {lock_pid}); OCR workers={OCR_WORKERS}")
    pool = ThreadPoolExecutor(max_workers=OCR_WORKERS) if OCR_ENABLED else None
    pending = []
    done = set()
    if REC.exists():
        for line in open(REC):
            try:
                r = json.loads(line)
                if r.get("status") == 200 or r.get("final"):
                    done.add(r["url"])
            except Exception:
                pass
    only = [m for m in os.environ.get("ZA_METROS", "eth,ekh,bcm").split(",") if m]
    stopped, site_status = None, {}
    try:
        for code in only:
            meta = METROS[code]
            try:
                st, h, final, _, _ = get(meta["listing"])
                if st != 200 or not h:
                    site_status[code] = f"listing_failed_{st}"
                    log("listing failed", code, st)
                    continue
                items = LISTERS[code](h, final)
                with open(LISTINGS, "a") as fh:
                    fh.write(json.dumps({"metro": code, "batch": BATCH, "listing_url": meta["listing"], "retrieved_at": now(),
                                         "items": items}, ensure_ascii=False) + "\n")
                log(f"{code}: listed {len(items)} items, already done {sum(1 for i in items if i['url'] in done)}")
                for it in items:
                    if it["url"] in done:
                        continue
                    why = predrop(it)
                    rec = {"metro": code, "url": it["url"], "list_title": it["list_title"], "list_date": it["list_date"],
                           "listing_url": meta["listing"], "retrieved_at": now(), "batch": BATCH}
                    if why:
                        rec.update({"status": "predropped", "drop_reason": why, "final": True})
                    else:
                        rec = fetch_and_extract(code, it, rec)
                    if isinstance(rec, dict) and rec.get("_ocr_job"):
                        job = rec
                        job["done_set"] = done
                        job["futs"] = [pool.submit(ocr_page, job["pdf"], job["wid"], n) for n in ocr_missing(job["wid"], job["pages"])]
                        pending.append(job)
                    else:
                        _write_rec(rec)
                        done.add(it["url"])
                    _reap(pending)
                    while len(pending) >= MAX_PENDING_DOCS and not STOP["reason"]:   # bound PDFs waiting in staging
                        _reap(pending, block=True)
                    gates()
                while pending and not STOP["reason"]:
                    _reap(pending, block=True)
                gates()
                site_status[code] = "ok"
            except SiteSkip as e:
                site_status[code] = f"SKIPPED: {e}"
                log("SITE SKIP", code, e)
            STATE.write_text(json.dumps({"last_metro": code, "site_status": site_status, "count": COUNT, "at": now()}))
    except HardStop as e:
        stopped = str(e)
        log("HARD STOP:", stopped)
    if pool:
        if stopped:
            kill_children()
        pool.shutdown(wait=True, cancel_futures=True)
        _reap(pending)            # finalize anything that completed before the stop
    kind = STOP["kind"]
    STOP["reason"] = STOP["reason"] or "exit"
    if SLOT:
        try:
            (SLOT_STARTS / SLOT).unlink()
        except OSError:
            pass
    ocr_dirs = sorted(p.name for p in OCR_DIR.glob("*")) if OCR_DIR.exists() else []
    STATE.write_text(json.dumps({"finished": stopped is None, "stopped": stopped, "stop_kind": kind, "site_status": site_status,
                                 "count": COUNT, "ocr_in_progress": ocr_dirs, "at": now()}))
    log("DONE", json.dumps(COUNT), "site_status=", json.dumps(site_status), "stopped=", stopped, "kind=", kind)
    # rc: 0 finished; 4 memory pause (re-queue in 30 min); 3 hard stop (resumable); 124 is set by timeout on slice end
    return 0 if not stopped else (4 if kind == "pause" else 3)


if __name__ == "__main__":
    sys.exit(main())
