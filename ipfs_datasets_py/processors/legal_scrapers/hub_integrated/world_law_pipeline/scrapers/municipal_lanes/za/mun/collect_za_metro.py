#!/usr/bin/env python3
"""ZA metro by-law densify (batch 6): City of Cape Town (www.capetown.gov.za) and City of Johannesburg
(joburg.org.za) official by-law PDFs, appended to endomorphosis/ipfs_south_africa_municipal_laws.
Fetch core adapted from the fleet CM densify collector (itself derived from endomorphosis/ipfs_datasets_py
@a1b5c73e5b687d8bd6c3b3051788860fd6e2f07a national_collectors). Policies:
  * Origin hosts only (www.capetown.gov.za, joburg.org.za); no Wayback/CC; no logins/forms.
  * TLS verify ON; fail closed on TLS errors.
  * Every send (incl. robots.txt and redirects) via fleet robots_guard + per-host pacer
    gap >= max(8 s, Crawl-Delay), one request in flight, fleet UA (robots_guard.ROBOTS_UA).
  * Hard stop on 403/429/503 or challenge markup. Timeouts/connection resets: retry once, then skip.
  * Light-runner watchdog: hard stop MemAvailable < 1.5 GiB held 15 s; tree RSS cap 300 MB.
  * pdftotext text layers only; PDFs without usable text are marked needs_ocr (separate OCR step).
  * Resumable (catalog.json, results.jsonl, cache/).
Usage: collect_za_metro.py --catalog-only | [--max N]    Env: ZA_WORK
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import hashlib, json, os, re, subprocess, sys, threading, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

W = Path(os.environ.get("ZA_WORK", (str(_LEGAL_WS) + "/world_laws/za_metro")))
os.environ["LEGAL_CORPORA_ROOT"] = str(W / "root")
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import robots_guard as rg  # noqa: E402  (fleet copy)
except ImportError:  # shipped name in the pack's scrapers/
    import robots_guard_b6 as rg  # noqa: E402
import requests  # noqa: E402

rg.set_country("za")
ALLOWED = {"www.capetown.gov.za", "joburg.org.za"}
FLOOR = max(8.0, float(os.environ.get("ZA_FLOOR", "8")))
MAX_DOC = 60 * 1024 * 1024
CHAL = re.compile(r"<title[^>]*>\s*(?:Just a moment|Attention Required|Access denied|Please wait|One more step)|"
                  r"_cf_chl_opt|cf-browser-verification|challenge-platform|cf-turnstile|checking your browser|"
                  r"Enable JavaScript and cookies to continue|sgcaptcha|ddos-guard|incapsula|px-captcha|"
                  r"datadome|awswaf|hcaptcha|recaptcha|imunify360|bot-check", re.I)
CAT, RES, REQ, STATUS = W / "catalog.json", W / "results.jsonl", W / "requests.jsonl", W / "status.txt"
PDF, TXT = W / "cache" / "pdf", W / "cache" / "text"


class HardStop(Exception):
    pass


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def status(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    with open(STATUS, "a") as fh:
        fh.write(line + "\n")


def mem_gib():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable:"):
            return int(l.split()[1]) / 2**20
    return 0.0


def disk_mib():
    s = os.statvfs("/")
    return s.f_bavail * s.f_frsize / 2**20


def rss_mib():
    tot = 0
    me = str(os.getpid())
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            st = open(f"/proc/{p}/stat").read().rsplit(")", 1)[1].split()
            if p == me or st[1] == me:
                tot += int(st[21]) * os.sysconf("SC_PAGE_SIZE")
        except Exception:
            pass
    return tot / 2**20


STOP = {"reason": None}
LOW = {"hard": None, "soft": None}
PEAK = {"rss": 0.0}


def watchdog():
    while STOP["reason"] is None:
        m = mem_gib(); now = time.time()
        LOW["hard"] = (LOW["hard"] or now) if m < 1.5 else None
        LOW["soft"] = (LOW["soft"] or now) if m < 1.5 else None
        if LOW["hard"] and now - LOW["hard"] >= 15:
            STOP["reason"] = f"hard_stop MemAvailable {m:.2f} GiB < 1.5 GiB held 15 s (light-runner)"
        elif disk_mib() < 12500:
            STOP["reason"] = f"hard_stop disk {disk_mib():.0f} MiB < 12500"
        elif rss_mib() > 286:
            STOP["reason"] = f"hard_stop RSS {rss_mib():.0f} MiB > 300 MB; LIGHT-RUNNER EXCEPTION FORFEITED"
        PEAK["rss"] = max(PEAK["rss"], rss_mib())
        time.sleep(2)


def gates():
    if STOP["reason"]:
        raise HardStop(STOP["reason"])
    if LOW["soft"] and time.time() - LOW["soft"] >= 60:
        status(f"PAUSE MemAvailable {mem_gib():.2f} GiB < 4 GiB held 60 s (BR priority); checkpointed")
        t0, ok = time.time(), None
        while True:
            if STOP["reason"]:
                raise HardStop(STOP["reason"])
            if mem_gib() >= 5.5:
                ok = ok or time.time()
                if time.time() - ok >= 120:
                    status("RESUME MemAvailable >= 5.5 GiB held 120 s"); LOW["soft"] = None; return
            else:
                ok = None
            if time.time() - t0 > 3600:
                status("BLOCKED_GATES paused > 60 min; exiting (resumable)")
                raise SystemExit(5)
            time.sleep(5)


LAST = {}
LOCK = threading.Lock()


def pace(url, kind):
    host = (urlsplit(url).hostname or "").lower()
    if host not in ALLOWED or not url.startswith("https://"):
        raise HardStop(f"host/scheme not allowed: {url}")
    st = rg._cache.get(f"https://{host}")
    gap = max(FLOOR, float(getattr(st, "crawl_delay", 0) or 0))
    with LOCK:
        last = LAST.get(host)
        if last is not None:
            w = last + gap - time.time()
            if w > 0:
                time.sleep(w + 0.05)
        t = time.time(); LAST[host] = t
    return t, gap


def reqlog(row):
    with open(REQ, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_prior_sends():
    if REQ.exists():
        for l in open(REQ):
            try:
                d = json.loads(l)
                h = urlsplit(d["url"]).hostname
                t = datetime.fromisoformat(d["sent_at"].replace("Z", "+00:00")).timestamp()
                LAST[h] = max(LAST.get(h, 0), t)
            except Exception:
                pass


def paced_robots(robots_url):
    t, gap = pace(robots_url, "robots_txt")
    stt, txt, err = rg._default_fetch(robots_url)
    reqlog({"url": robots_url, "kind": "robots_txt", "status": stt, "error": err, "sent_at": utc()})
    if stt in (403, 429, 503) or (txt and CHAL.search(txt[:20000])):
        raise HardStop(f"robots.txt {robots_url} http {stt} / challenge")
    return stt, txt, err


class Transient(Exception):
    pass


def _transient(e):
    return isinstance(e, (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError,
                          requests.exceptions.ChunkedEncodingError)) and not isinstance(e, requests.exceptions.SSLError)


def get(url, kind, stream_to: Path | None = None):
    gates()
    d = rg.check(url)
    if not d.allowed:
        reqlog({"url": url, "kind": kind, "status": "robots_blocked", "reason": d.reason, "rule": d.rule, "sent_at": utc()})
        return None, None
    t, gap = pace(url, kind)
    sent = utc()
    try:
        r = requests.get(url, timeout=(20, 180), verify=rg.ca_verify_for(url), stream=True, allow_redirects=False,
                         headers={"User-Agent": rg.ROBOTS_UA, "Accept": "application/json,text/html,application/pdf,*/*",
                                  "Connection": "close"})
    except Exception as e:
        reqlog({"url": url, "kind": kind, "status": f"error {type(e).__name__}", "sent_at": sent})
        if _transient(e):
            raise Transient(f"{type(e).__name__} {url}")
        raise HardStop(f"network/TLS error (not retried) {url}: {type(e).__name__} {str(e)[:120]}")
    row = {"url": url, "kind": kind, "status": r.status_code, "ctype": r.headers.get("content-type", ""),
           "server": r.headers.get("server", ""), "cf_mitigated": r.headers.get("cf-mitigated"), "sent_at": sent, "gap_s": gap}
    if r.status_code in (301, 302, 303, 307, 308):
        row["location"] = r.headers.get("location"); reqlog(row); r.close()
        loc = urljoin(url, r.headers.get("location") or "")
        if (urlsplit(loc).hostname or "") not in ALLOWED:
            raise HardStop(f"redirect off-host {url} -> {loc}")
        return get(loc, kind + "_redirect", stream_to)
    if r.status_code in (403, 429, 503) or r.headers.get("cf-mitigated"):
        reqlog(row); r.close()
        raise HardStop(f"HTTP {r.status_code} at {url} (hard stop; no retry)")
    if stream_to is not None and r.status_code == 200 and "html" not in row["ctype"].lower():
        n = 0; h = hashlib.sha256(); tmp = stream_to.with_suffix(".part")
        try:
            with open(tmp, "wb") as fh:
                for ch in r.iter_content(262144):
                    n += len(ch); h.update(ch)
                    if n > MAX_DOC:
                        break
                    fh.write(ch)
        except Exception as e:
            r.close(); tmp.unlink(missing_ok=True)
            reqlog({**row, "status": f"error {type(e).__name__}", "bytes": n})
            if _transient(e):
                raise Transient(f"{type(e).__name__} {url}")
            raise
        r.close(); row["bytes"] = n; reqlog(row)
        if n > MAX_DOC:
            tmp.unlink(missing_ok=True); return "too_large", None
        head = open(tmp, "rb").read(5)
        if head != b"%PDF-":
            body = open(tmp, "rb").read(20000).decode("latin-1", "replace"); tmp.unlink(missing_ok=True)
            if CHAL.search(body):
                raise HardStop(f"challenge body at {url}")
            return "not_pdf", None
        tmp.rename(stream_to)
        return 200, {"sha256": h.hexdigest(), "bytes": n}
    body = b""
    for ch in r.iter_content(262144):
        body += ch
        if len(body) > 20 * 1024 * 1024:
            break
    r.close(); row["bytes"] = len(body); reqlog(row)
    txt = body.decode(r.encoding or "utf-8", "replace")
    if "<html" in txt[:5000].lower() and CHAL.search(txt[:400000]):
        raise HardStop(f"challenge markup at {url}")
    return r.status_code, txt



LISTINGS = [("cpt", "https://www.capetown.gov.za/work-and-business/city-publications/policies-and-by-laws/policies-by-laws-and-publications/", r'href="(/media/[^"]+\.pdf)"'),
            ("jhb", "https://joburg.org.za/documents_/Pages/Key%20Documents/By-Laws/By-Laws.aspx", r'href="(/documents_/Documents/[^"]+\.pdf)"')]
HTMLC = W / "cache" / "html"


def clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).replace("&nbsp;", " ").replace("&amp;", "&").strip()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:140]


def discover():
    if CAT.exists():
        return json.load(open(CAT))
    from urllib.parse import unquote
    items, seen = [], set()
    for city, url, pat in LISTINGS:
        st, html = with_retry(url, "listing_html")
        if st != 200 or not html:
            raise HardStop(f"listing {city} status {st}")
        (HTMLC / f"listing_{city}.html").write_text(html)
        for href, lab in re.findall(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', html, re.I | re.S):
            if not re.fullmatch(pat[6:-1], href):
                continue
            full = urljoin(url, href)
            if full in seen:
                continue
            seen.add(full)
            fn = unquote(full.rsplit("/", 1)[-1])
            items.append({"src": city, "ident": f"{city}-" + slug(fn[:-4]), "url": full, "title": clean(lab) or fn, "filename": fn, "listing_url": url})
        status(f"listing {city} catalog={len(items)}")
    json.dump(items, open(CAT, "w"), indent=1, ensure_ascii=False)
    status(f"CATALOG_DONE n={len(items)}")
    return items


def extract(pdf: Path):
    out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"], capture_output=True, timeout=300)
    txt = out.stdout.decode("utf-8", "replace")
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
    m = re.search(r"Pages:\s*(\d+)", info); pages = int(m.group(1)) if m else 0
    alpha = sum(c.isalpha() for c in txt)
    return txt, pages, (pages > 0 and alpha >= 200 * max(1, pages // 4) and alpha >= 400)


def html_main_text(html):
    h = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", html)
    m = re.search(r'(?is)<div[^>]+class="[^"]*(?:field-name-body|field-item|item-page|node-content|content clearfix)[^"]*"[^>]*>(.*)', h)
    seg = m.group(1) if m else h
    seg = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", seg)
    t = re.sub(r"<[^>]+>", " ", seg)
    import html as H
    t = H.unescape(t)
    return "\n".join(re.sub(r"[ \t]+", " ", l).strip() for l in t.splitlines() if l.strip())


def with_retry(url, kind, **kw):
    for attempt in (1, 2):
        try:
            return get(url, kind, **kw)
        except Transient as e:
            status(f"TRANSIENT attempt={attempt} {e}")
    return "skip_timeout", None


def main():
    catalog_only = "--catalog-only" in sys.argv
    mx = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 0
    for d in (PDF, TXT, HTMLC):
        d.mkdir(parents=True, exist_ok=True)
    _load_prior_sends()
    rg._robots_fetcher = paced_robots
    threading.Thread(target=watchdog, daemon=True).start()
    items = discover()
    if catalog_only:
        return 0
    todo = set(json.load(open(W / "todo.json")))
    done = set()
    if RES.exists():
        for l in open(RES):
            d = json.loads(l)
            if d.get("status") in (200, "no_document", "not_found", "not_pdf", "too_large"):
                done.add(d["ident"])
    n = 0
    for it in items:
        if it["ident"] not in todo or it["ident"] in done:
            continue
        if mx and n >= mx:
            break
        res = {"ident": it["ident"], "url": it["url"], "src": it["src"]}
        if True:
            pdfs = [it["url"]]
            pdf = PDF / f"{it['ident']}.pdf"
            if pdfs and not pdf.exists():
                st2, meta = with_retry(pdfs[0], "pdf", stream_to=pdf)
                res.update(pdf_url=pdfs[0], pdf_status=st2, **(meta if isinstance(meta, dict) else {}))
            elif pdfs:
                res.update(pdf_url=pdfs[0], pdf_status=200, cached=True, sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(), bytes=pdf.stat().st_size)
            if pdf.exists():
                txt, pages, usable = extract(pdf)
                (TXT / f"{it['ident']}.txt").write_text(txt)
                res.update(status=200, text_from="pdf", pages=pages, text_layer_usable=usable, chars=len(txt), needs_ocr=not usable)
            else:
                ps = res.get("pdf_status")
                res.update(status="not_found" if ps == 404 else (ps if ps not in (None, 200) else "no_document"))
            res["retrieved_at"] = utc()
        with open(RES, "a") as fh:
            fh.write(json.dumps(res, ensure_ascii=False) + "\n")
        n += 1
        if n % 10 == 0:
            status(f"progress fetched={n} last={it['ident']} mem={mem_gib():.2f}GiB rss={rss_mib():.0f}MiB")
    status(f"FETCH_DONE this_run={n} peak_rss={PEAK['rss']:.0f}MiB")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HardStop as e:
        status(f"HARD_STOP {e}")
        sys.exit(3)
