#!/usr/bin/env python3
"""Kenya county legislation (municipal/local law) from Kenya Law (National Council for
Law Reporting) -> endomorphosis/ipfs_kenya_municipal_laws.

Source: https://new.kenyalaw.org/legislation/counties  (47 counties, /legislation/ke-0NN/)
Rules (CoS muni Phase B): every request + redirect hop via robots_guard (Crawl-delay 5),
no WAF/captcha workarounds (challenge page => stop), official source only, staging only in
/dev/shm/muni_africa/ke (<1.5 GB), hard stop if free disk on / < 12,500 MiB or
MemAvailable < 4 GiB. Resumable (records.jsonl). PDFs are streamed to /dev/shm, text
extracted with pdftotext, then deleted.
Run only under:  flock -n /dev/shm/muni_runner.lock python3 collect_ke_counties_muni.py
"""
from __future__ import annotations
import html as _html, json, os, re, shutil, subprocess, sys, time, unicodedata
from datetime import datetime, timezone
from pathlib import Path

STAGE = Path(os.environ.get("MUNI_STAGE", "/dev/shm/muni_africa/ke"))
os.environ.setdefault("LEGAL_CORPORA_ROOT", str(STAGE / "root"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import robots_guard as rg  # noqa: E402
import urllib3  # noqa: E402
urllib3.disable_warnings()

rg.set_country("ke")
PORTAL = "https://new.kenyalaw.org"
SEEDS = Path(os.environ.get("MUNI_SEEDS_KE", str(Path(__file__).resolve().parent / "seeds" / "KE.jsonl")))
REC = STAGE / "records.jsonl"
STATE = STAGE / "state.json"
TMP = STAGE / "tmp"
DISK_STOP_MIB = 12500
MEM_STOP_GIB = 4.0
STAGE_MAX_BYTES = int(1.5 * 1024**3)
MAX_PDF = 40 * 1024 * 1024
MAX_HTML = 15 * 1024 * 1024
SOURCE_TYPE = "kenyalaw_county_legislation"
LICENSE = ("Kenya Law (National Council for Law Reporting) county legislation; site states its "
           "contents are public domain except material expressly marked with a Creative Commons "
           "licence (see new.kenyalaw.org/terms-of-use/).")
CHALLENGE = re.compile(r"Just a moment\.\.\.|_cf_chl_opt|cf-browser-verification|challenge-platform|captcha", re.I)

S = rg.GuardedSession()
S.headers["User-Agent"] = rg.ROBOTS_UA
S.max_redirects = 5
COUNT = {"requests": 0, "robots_skips": 0, "errors": 0, "pdf_skipped_large": 0}


class HardStop(Exception):
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


def gates():
    st = os.statvfs("/")
    free_mib = st.f_bavail * st.f_frsize / 2**20
    mem = 0.0
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            mem = int(line.split()[1]) / 2**20
    if free_mib < DISK_STOP_MIB:
        raise HardStop(f"disk free {free_mib:.0f} MiB < {DISK_STOP_MIB}")
    if mem < MEM_STOP_GIB:
        raise HardStop(f"MemAvailable {mem:.2f} GiB < {MEM_STOP_GIB}")
    return free_mib, mem


def get(url, *, stream_to: Path | None = None, cap=MAX_HTML):
    """Guarded GET with gates. Returns (status, text|None, final_url, nbytes)."""
    gates()
    for attempt in range(3):
        try:
            COUNT["requests"] += 1
            r = S.get(url, timeout=(20, 120), stream=True, verify=False)
        except rg.RobotsBlocked as e:
            COUNT["robots_skips"] += 1
            rg.log_robots_blocked(e, caller="collect_ke_counties_muni")
            return ("robots", None, url, 0)
        except Exception as e:  # network
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
        clen = int(r.headers.get("content-length") or 0)
        if clen and clen > cap:
            r.close()
            return ("too_large", None, r.url, clen)
        n = 0
        if stream_to is not None:
            with open(stream_to, "wb") as fh:
                for ch in r.iter_content(262144):
                    n += len(ch)
                    if n > cap:
                        r.close()
                        return ("too_large", None, r.url, n)
                    fh.write(ch)
            r.close()
            head = open(stream_to, "rb").read(2048)
            if b"<html" in head.lower() and CHALLENGE.search(head.decode("latin-1")):
                raise HardStop(f"WAF/challenge page at {url} — stopping (no workarounds)")
            return (r.status_code, None, r.url, n)
        raw = b""
        for ch in r.iter_content(262144):
            raw += ch
            if len(raw) > cap:
                break
        r.close()
        txt = raw.decode(r.encoding or "utf-8", "replace")
        if CHALLENGE.search(txt[:6000]):
            raise HardStop(f"WAF/challenge page at {url} — stopping (no workarounds)")
        return (r.status_code, txt, r.url, len(raw))
    return ("failed", None, url, 0)


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(county|city|government)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


def seed_map():
    m = {}
    for line in open(SEEDS):
        r = json.loads(line)
        if r.get("admin_level") == "county":
            m[norm(r["name"])] = r
    return m


def strip_tags(h):
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>|</(p|div|h[1-6]|li|tr|section)>", "\n", h, flags=re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    h = _html.unescape(h)
    h = re.sub(r"[ \t\xa0]+", " ", h)
    return re.sub(r"\n\s*\n+", "\n\n", h).strip()


def discover_counties():
    st, t, _, _ = get(f"{PORTAL}/legislation/counties")
    if st != 200 or not t:
        raise HardStop(f"counties index failed: {st}")
    out = []
    for code, name in re.findall(r'href="/legislation/(ke-0\d\d)/"[^>]*>\s*([^<]+?)\s*<', t):
        name = _html.unescape(name).strip()
        if (code, name) not in out:
            out.append((code, name))
    return out


def list_county(code):
    items, page, seen = [], 1, set()
    while True:
        url = f"{PORTAL}/legislation/{code}/" + (f"?page={page}" if page > 1 else "")
        st, t, _, _ = get(url)
        if st != 200 or not t:
            log("list fail", code, page, st)
            break
        # rows: <a href="/akn/ke-0NN/act/...">Title</a> ... citation
        for href, title in re.findall(r'href="(/akn/%s/[^"#?]+)"[^>]*>\s*(.*?)\s*</a>' % code, t, re.S):
            work = href.split("/eng@")[0]
            if work in seen:
                continue
            seen.add(work)
            items.append({"href": href, "work": work, "list_title": strip_tags(title)[:400]})
        pages = [int(p) for p in re.findall(r'[?&]page=(\d+)', t)]
        if pages and max(pages) > page:
            page += 1
            if page > 40:
                break
        else:
            break
    return items


SEC_LINE = re.compile(r"(?m)^[ \t]*(\d{1,3}[A-Z]?)\.[ \t]+([A-Z][^\n]{1,160})$")


def split_sections(text, law_id):
    ms = list(SEC_LINE.finditer(text or ""))
    # keep a monotone-ish run: drop TOC duplicates by keeping the LAST occurrence block start
    if len(ms) < 2:
        return []
    # find the start of the body: the second occurrence of section "1." if a TOC exists
    ones = [i for i, m in enumerate(ms) if m.group(1) == "1"]
    if len(ones) >= 2:
        ms = ms[ones[1]:]
    out, seen = [], set()
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        chunk = text[m.start():end].strip()
        num = m.group(1)
        if len(chunk) < 15 or num in seen:
            continue
        seen.add(num)
        out.append({"num": num, "title": f"{num}. {m.group(2).strip()}"[:200], "text": chunk})
    return out if len(out) >= 2 else []


def akn_sections(h):
    out = []
    for m in re.finditer(r'<section[^>]+class="[^"]*akn-section[^"]*"[^>]*id="([^"]+)"[^>]*>', h):
        start = m.start()
        nxt = re.search(r'<section[^>]+class="[^"]*akn-section', h[m.end():])
        end = m.end() + nxt.start() if nxt else min(len(h), m.end() + 400000)
        txt = strip_tags(h[start:end])
        if len(txt) < 10:
            continue
        num = re.match(r"\s*(\d{1,3}[A-Z]?)\.?", txt)
        out.append({"num": num.group(1) if num else m.group(1), "title": txt.split("\n", 1)[0][:200], "text": txt})
    return out


def fetch_doc(it, county, seed):
    url = PORTAL + it["href"]
    st, h, final, n = get(url)
    rec = {"href": it["href"], "work": it["work"], "county_code": county[0], "county_name": county[1],
           "qid": seed.get("qid", ""), "retrieved_at": now(), "page_status": st}
    if st != 200 or not h:
        rec["error"] = f"page_{st}"
        return rec
    title = re.findall(r"<title>\s*(.*?)\s*-\s*Kenya Law\s*</title>", h, re.S)
    rec["title"] = _html.unescape(title[0].strip()) if title else it["list_title"]
    disp = re.search(r'data-display-type="([a-z]+)"', h)
    rec["display_type"] = disp.group(1) if disp else ""
    exp = re.search(r"/eng@(\d{4}-\d{2}-\d{2})", it["href"])
    rec["expression_date"] = exp.group(1) if exp else ""
    m = re.search(r"Commenced\s*(?:on)?\s*</?[^>]*>?\s*(\d{1,2} \w+ \d{4})", h)
    rec["commenced"] = m.group(1) if m else ""
    cit = re.search(r"((?:Act No\.|Legal Notice)\s*[0-9A-Za-z]+ of \d{4})", strip_tags(h[:200000]))
    rec["citation"] = cit.group(1) if cit else ""
    rec["source_url"] = url
    if rec["display_type"] == "pdf":
        pdfp = re.search(r'data-pdf="([^"]+)"', h)
        purl = PORTAL + (pdfp.group(1) if pdfp else it["href"] + "/source.pdf")
        TMP.mkdir(parents=True, exist_ok=True)
        tmp = TMP / "doc.pdf"
        pst, _, pfinal, pn = get(purl, stream_to=tmp, cap=MAX_PDF)
        rec["pdf_url"] = purl
        rec["pdf_bytes"] = pn
        if pst == "too_large":
            COUNT["pdf_skipped_large"] += 1
            rec["error"] = "pdf_too_large"
            rec["text"] = ""
        elif pst == 200:
            try:
                txt = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(tmp), "-"],
                                     capture_output=True, timeout=180).stdout.decode("utf-8", "replace")
            except Exception as e:
                txt = ""
                rec["error"] = f"pdftotext_{type(e).__name__}"
            txt = re.sub(r"[ \t]+\n", "\n", txt).replace("\f", "\n")
            rec["text"] = txt.strip()
            rec["text_backend"] = "pdftotext"
            if len(re.sub(r"\s", "", txt)) < 200:
                rec["no_text_layer"] = True
        else:
            rec["error"] = f"pdf_{pst}"
            rec["text"] = ""
        try:
            tmp.unlink()
        except OSError:
            pass
        rec["sections"] = split_sections(rec.get("text", ""), "")
    else:
        m = re.search(r'<div[^>]+id="document-content"[^>]*>', h)
        chunk = h[m.end():] if m else h
        cut = re.search(r'<div[^>]+class="tab-pane[^"]*"[^>]+id="(?!document)', chunk)
        chunk = chunk[: cut.start()] if cut else chunk
        rec["sections"] = akn_sections(chunk)
        rec["text"] = strip_tags(chunk)
        rec["text_backend"] = "akn_html"
        if not rec["sections"]:
            rec["sections"] = split_sections(rec["text"], "")
    return rec


def main():
    STAGE.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    gates()
    seeds = seed_map()
    done = set()
    if REC.exists():
        for line in open(REC):
            try:
                r = json.loads(line)
                if not r.get("error", "").startswith(("page_failed", "page_robots")):
                    done.add(r["work"])
            except Exception:
                pass
    counties = discover_counties()
    log("counties", len(counties), "done works", len(done))
    unmatched = [c for c in counties if norm(c[1]) not in seeds]
    if unmatched:
        log("WARN unmatched counties (no seed QID):", unmatched)
    stopped = None
    try:
        for ci, county in enumerate(counties):
            seed = seeds.get(norm(county[1]), {})
            items = list_county(county[0])
            log(f"[{ci+1}/{len(counties)}] {county[0]} {county[1]} qid={seed.get('qid')} items={len(items)}")
            for it in items:
                if it["work"] in done:
                    continue
                if du(STAGE) > STAGE_MAX_BYTES:
                    raise HardStop("staging >= 1.5 GB")
                rec = fetch_doc(it, county, seed)
                with open(REC, "a") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                done.add(it["work"])
            STATE.write_text(json.dumps({"last_county": county[0], "count": COUNT, "at": now()}))
    except HardStop as e:
        stopped = str(e)
        log("HARD STOP:", stopped)
    STATE.write_text(json.dumps({"finished": stopped is None, "stopped": stopped, "count": COUNT, "at": now()}))
    log("DONE", json.dumps(COUNT), "stopped=", stopped)
    return 3 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
