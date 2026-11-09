#!/usr/bin/env python3
"""Kenya, Samburu County Assembly Acts -> endomorphosis/ipfs_kenya_municipal_laws, batch 2 (shard 00002; gap fill: Kenya
Law has no Samburu county legislation, so batch 1 has none).

Source: https://www.samburuassembly.go.ke/acts/ ('Samburu County Acts', the official county assembly site), documents served
by the site's file-download plugin under https://www.samburuassembly.go.ke/download/119/acts/<id>/<slug>.pdf.
Host touched: www.samburuassembly.go.ke ONLY (no other host, no off-host redirects; the Google Docs 'Preview' links on the
page are never followed; no forms, no logins, no admin-ajax calls).
Selection: every document link of the page is classified; Samburu County Acts are kept (the stager confirms the maker from
the enacting clause of each PDF: 'ENACTED by the County Assembly of Samburu'); bills, national Acts, policies, reports and
anything else go to the listing exclusions with a reason and are not fetched.
Fetch rules (standing Phase-B rules; fetch code shared with collect_ug_kcca_muni.py):
  * robots_guard on every send (GuardedSession; each redirect hop checked); robots.txt read ONCE per run at the start
    through a paced, logged fetcher (an absent robots.txt would be robots_guard's 'missing' case: allowed).
  * hard pre-request pacer: before EVERY send (robots.txt, page, PDF, each redirect hop) the gap since the last send to the
    host family must be >= max(5 s, KE_PACE_S, robots Crawl-Delay), using the send times of ALL runs (KE_PACING_LOGS,
    including the Phase-A probe log); sleeps, re-checks, raises PacingError (rc 3) instead of sending early.
  * TLS verify=True; one request in flight; https only.
  * HARD STOP (rc 3, no retry) on any Cloudflare / WAF / bot-check signal (cf-mitigated / cf-chl headers, challenge
    scripts, 'Just a moment' titles, captcha vendors, Imunify360 bot-check pages) or HTTP 403 / 429 / 503.
Modes: KE_MODE=collect (default; network): listing, selection, PDF downloads, text-layer assessment per page.
       KE_MODE=reassess (offline): redo the text-layer assessment / text files for PDFs on disk.
       KE_MODE=ocr (offline): OCR of the pages that need it, quality metrics, merged text per document (text-layer pages
       in pdftotext -raw order: the Samburu PDFs are Adobe Scan phone captures of two-page gazette spreads, and the raw
       content-stream order of the scanner's OCR layer reads the left page, then the right page, line by line).
Text: a page keeps its PDF text layer when it has >= 100 body characters and the document's layer is not garbled
(function-word share >= 0.25 and short-line share <= 0.75); born-digital Word/ODF would be converted, never OCRed.
Other pages (scans, phone captures, garbled layers) are OCRed: pdftoppm 300 dpi gray -> tesseract eng (KE_OCR_PSM, default
3), OMP_THREAD_LIMIT=1, KE_OCR_WORKERS processes (default 2; capped at 2 whenever another fleet runner holds a slot,
FLEET_RULES_v2 s.1). OCR quality per page and per law: mean tesseract word confidence, share of words with confidence >= 70,
and the lexical share (alphabetic tokens of >= 3 letters found in tesseract's own English word list, extracted from
eng.traineddata with combine_tessdata + dawg2wordlist). The stager flags laws whose text is too degraded to split.
Memory rule (no runner slot; small job): MemAvailable < 3 GiB or disk < 12,500 MiB => stop (rc 3); < 4 GiB held 60 s =>
pause (rc 4 after 30 min); RSS of this process plus its children (pdftoppm / tesseract) > 1 GiB => stop (rc 3). Resumable
(records.jsonl, ocr/<key>/pNNNN.json). Never uploads.
rc: 0 done | 3 hard stop | 4 memory pause timeout.
"""
from __future__ import annotations
import collections, glob, hashlib, html, json, os, re, subprocess, sys, threading, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote, unquote

STAGE = Path(os.environ.get("MUNI_STAGE", "/dev/shm/muni_africa/ke/samburu"))
os.environ.setdefault("LEGAL_CORPORA_ROOT", str(STAGE / "root"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import robots_guard as rg  # noqa: E402
import requests  # noqa: E402

rg.set_country("ke")
PARSER_VERSION = "ke-samburu-assembly-2026.10.04-b2"
HOST = "https://www.samburuassembly.go.ke"
ALLOWED = {"www.samburuassembly.go.ke", "samburuassembly.go.ke"}
FAMILY = "samburuassembly.go.ke"
LIST_URL = os.environ.get("KE_LIST_URL", HOST + "/acts/")
PACE = max(5.0, float(os.environ.get("KE_PACE_S", "5.0")))
PACING_LOGS = os.environ.get("KE_PACING_LOGS", f"{STAGE}/requests.jsonl {STAGE.parent}/samburu*/requests.jsonl "
                             "/dev/shm/muni_africa/next_probe/probe2_requests.jsonl /dev/shm/muni_africa/next_probe/requests.jsonl").split()
DISK_STOP_MIB, MEM_HARD_GIB, MEM_SOFT_GIB, MEM_SOFT_HOLD_S, PAUSE_MAX_S = 12500, 3.0, 4.0, 60, 1800
MAX_DOC = 40 * 1024 * 1024
CF_BODY = re.compile(r"<title[^>]*>\s*(?:Just a moment|Attention Required|Access denied|Please wait|One more step|DDoS protection)|"
                     r"Just a moment\.\.\.|_cf_chl_opt|cf-browser-verification|/cdn-cgi/challenge-platform|challenge-platform|cf-turnstile|"
                     r"checking your browser|Checking if the site connection is secure|Enable JavaScript and cookies to continue|"
                     r"/cdn-cgi/challenge|sgcaptcha|ddos-guard|__ddg|incapsula|_Incapsula_Resource|perimeterx|px-captcha|datadome|"
                     r"captcha-delivery\.com|awswaf|aws-waf-token|hcaptcha|recaptcha|captcha|imunify360|imunify-bot-check|bot-check", re.I)
COUNT = collections.Counter()
RUN_NOTES = []


class HardStop(Exception):
    pass


class PacingError(HardStop):
    """Raised instead of sending when a request would go out before the required gap (never caught and retried)."""


def iso_ms(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def reqlog(row):
    STAGE.mkdir(parents=True, exist_ok=True)
    with open(STAGE / "requests.jsonl", "a") as fh:
        fh.write(json.dumps(dict(row, parser_version=PARSER_VERSION), ensure_ascii=False) + "\n")


def _wire_send(session, prep, **kw):
    """The only place a request leaves the process (pages, PDFs, every redirect hop, every robots.txt hop)."""
    return requests.Session.send(session, prep, **kw)


def _fam(h):
    return re.sub(r"^www\.", "", (h or "").lower())


class Pacer:
    """Hard pre-request pacing for the Samburu County Assembly host family (www. and bare host share ONE clock). Before EVERY
    send: required gap = max(5 s, KE_PACE_S, robots Crawl-Delay of the host (persisted value before robots.txt is read));
    last send = the latest send to the family in every log of KE_PACING_LOGS (all runs; 'sent_at' list or string, +1 ms
    rounding margin) and this run's sends. Sleeps until the gap has passed, re-checks, raises PacingError otherwise."""

    def __init__(self):
        self.last, self.sends, self.persisted_cd = None, [], 0.0
        times = []
        for g in PACING_LOGS:
            for p in sorted(glob.glob(g)):
                for line in open(p):
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if _fam(urlparse(d.get("url") or "").hostname) != FAMILY:
                        continue
                    st = d.get("sent_at") or d.get("ts") or []
                    st = [st] if isinstance(st, str) else st
                    for x in st:
                        try:
                            times.append(datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp() + 0.001)
                        except ValueError:
                            pass
        snap = rg.load_persisted_snapshot("www." + FAMILY)
        if snap:
            try:
                g = rg.parse_robots(snap.get("body") or "").select()
                self.persisted_cd = float(g.crawl_delay or 0) if g else 0.0
            except Exception:
                pass
        self.last = max(times) if times else None

    def gap(self):
        cds = [st.crawl_delay or 0.0 for o, st in list(rg._cache.items()) if (urlparse(o).hostname or "") in ALLOWED]
        cd = max(cds) if cds else self.persisted_cd
        return max(5.0, PACE, cd)

    def before_send(self, url, kind):
        host = (urlparse(url).hostname or "").lower()
        if host not in ALLOWED or urlparse(url).scheme != "https":
            raise HardStop(f"pacer: host/scheme not allowed: {url}")
        gap = self.gap()
        actual = None
        if self.last is not None:
            wait = self.last + gap - time.time()
            if wait > 0:
                time.sleep(wait + 0.05)
            actual = time.time() - self.last
            if actual < gap:
                raise PacingError(f"pacing assert: {kind} {url} would go out {actual:.3f} s after the previous send "
                                  f"(required {gap:.1f} s); not sent")
        t = time.time()
        self.last = t
        self.sends.append((t, host, kind, url, gap, actual))
        return t


PACER = None


def paced_robots_fetch(robots_url):
    """robots_guard fetcher hook: hop by hop, each hop paced + logged (kind robots_txt), TLS verified, assembly host only,
    hard stop on WAF signals / 403 / 429 / 503. Returns (status, text, error) like robots_guard._default_fetch."""
    url = robots_url
    COUNT["robots_fetches"] += 1
    with requests.Session() as sess:
        for _hop in range(4):
            t = PACER.before_send(url, "robots_txt")
            prep = sess.prepare_request(requests.Request("GET", url, headers={"User-Agent": rg.ROBOTS_UA, "Accept": "text/plain,*/*"}))
            try:
                r = _wire_send(sess, prep, allow_redirects=False, timeout=rg.ROBOTS_TIMEOUT, verify=rg.ca_verify_for(url), stream=True)
            except Exception as e:
                reqlog({"url": url, "kind": "robots_txt", "status": f"error {type(e).__name__}", "sent_at": [iso_ms(t)], "at": now()})
                raise HardStop(f"robots.txt fetch failed (not retried): {type(e).__name__} {str(e)[:160]}")
            reqlog({"url": url, "kind": "robots_txt", "status": r.status_code, "sent_at": [iso_ms(t)], "server": r.headers.get("server", ""),
                    "cf_mitigated": r.headers.get("cf-mitigated"), "at": now()})
            if r.headers.get("cf-mitigated") or any(k.lower().startswith("cf-chl") for k in r.headers) or r.status_code in (403, 429, 503):
                COUNT["cloudflare_signals"] += 1
                r.close()
                raise HardStop(f"CLOUDFLARE/WAF signal on robots.txt {url}: http {r.status_code} cf-mitigated={r.headers.get('cf-mitigated')}")
            loc = r.headers.get("Location")
            if r.status_code in (301, 302, 303, 307, 308) and loc:
                r.close()
                url = urljoin(url, loc)
                if (urlparse(url).hostname or "") not in ALLOWED or urlparse(url).scheme != "https":
                    raise HardStop(f"robots.txt redirect left the assembly https host: {url}")
                continue
            raw = b""
            for ch in r.iter_content(65536):
                raw += ch
                if len(raw) >= rg.MAX_ROBOTS_BYTES:
                    break
            r.close()
            txt = raw[:rg.MAX_ROBOTS_BYTES].decode("utf-8-sig", "replace")
            if "<html" in txt[:3000].lower() and CF_BODY.search(txt[:20000]):
                COUNT["cloudflare_signals"] += 1
                raise HardStop(f"CLOUDFLARE challenge markup on robots.txt {url}")
            RUN_NOTES.append({"robots_url": robots_url, "http_status": r.status_code, "bytes": len(raw),
                              "case": "absent (404): robots_guard 'missing' = no rules, allowed" if r.status_code == 404 else "present"})
            return r.status_code, txt, ""
    return 0, "", "too_many_redirects"


class PacedSession(rg.GuardedSession):
    """GuardedSession whose every send (each redirect hop too) passes robots_guard.guard_send (robots allow/deny) and the
    hard PACER gate before going on the wire."""
    hop_times = None

    def send(self, request, **kwargs):
        rg.check(request.url)               # robots.txt of the origin, read once per run (cached by robots_guard)
        rg.guard_send(request.url, min_interval=self.min_interval, caller="collect_ke_samburu_muni")
        t = PACER.before_send(request.url, "request")
        if self.hop_times is not None:
            self.hop_times.append(iso_ms(t))
        return _wire_send(self, request, **kwargs)


S = PacedSession()
S.headers["User-Agent"] = rg.ROBOTS_UA
# no keep-alive reuse: with >= 5 s between sends the server (Apache KeepAliveTimeout, default 5 s) closes an idle pooled
# connection just as the next request reuses it (batch 2 run 1 stopped on such a RemoteDisconnected); one connection per send
S.headers["Connection"] = "close"
S.min_interval = PACE
S.max_redirects = 3


def start_pacing():
    global PACER
    PACER = Pacer()
    rg._robots_fetcher = paced_robots_fetch
    return PACER


def mem_gib():
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 2**20
    return 0.0


def disk_mib():
    st = os.statvfs("/")
    return st.f_bavail * st.f_frsize / 2**20


STOP, LOW = {"reason": None}, {"since": None}


def watchdog():
    while STOP["reason"] is None:
        m = mem_gib()
        if m < MEM_HARD_GIB:
            STOP["reason"] = f"MemAvailable {m:.2f} GiB < {MEM_HARD_GIB} GiB"
        elif disk_mib() < DISK_STOP_MIB:
            STOP["reason"] = f"disk free {disk_mib():.0f} MiB < {DISK_STOP_MIB}"
        LOW["since"] = (LOW["since"] or time.time()) if m < MEM_SOFT_GIB else None
        time.sleep(5)


def gates():
    if STOP["reason"]:
        raise HardStop(STOP["reason"])
    if LOW["since"] and time.time() - LOW["since"] >= MEM_SOFT_HOLD_S:
        log("memory pause: MemAvailable < 4 GiB held >= 60 s; waiting")
        t0, ok_since = time.time(), None
        while True:
            if STOP["reason"]:
                raise HardStop(STOP["reason"])
            if mem_gib() >= MEM_SOFT_GIB:
                ok_since = ok_since or time.time()
                if time.time() - ok_since >= 60:
                    LOW["since"] = None
                    log("memory recovered; resuming")
                    return
            else:
                ok_since = None
            if time.time() - t0 > PAUSE_MAX_S:
                raise SystemExit(4)
            time.sleep(5)


def cf_check(r, head_text):
    sig = []
    if r.headers.get("cf-mitigated"):
        sig.append(f"cf-mitigated={r.headers.get('cf-mitigated')}")
    if any(k.lower().startswith("cf-chl") for k in r.headers):
        sig.append("cf-chl header")
    if r.status_code in (403, 429, 503):
        sig.append(f"http_{r.status_code}")
    if head_text and ("<html" in head_text[:5000].lower() or "<!doctype" in head_text[:500].lower()):
        m = CF_BODY.search(head_text[:400000])
        if m:
            sig.append("challenge_markup:" + m.group(0)[:40])
    if sig:
        COUNT["cloudflare_signals"] += 1
        raise HardStop(f"CLOUDFLARE/WAF signal at {r.url}: {sig} (hard stop; no retry, no workaround)")


def get(url, *, stream_to: Path | None = None, cap=8 * 1024 * 1024):
    assert (urlparse(url).hostname or "") in ALLOWED and url.startswith("https://"), f"host not allowed: {url}"
    gates()
    S.hop_times = sent = []
    try:
        COUNT["requests"] += 1
        r = S.get(url, timeout=(20, 120), stream=True, verify=rg.ca_verify_for(url))
    except HardStop:
        if sent:
            reqlog({"url": url, "status": "stopped", "sent_at": sent, "at": now()})
        raise
    except rg.RobotsBlocked as e:
        COUNT["robots_skips"] += 1
        rg.log_robots_blocked(e, caller="collect_ke_samburu_muni")
        reqlog({"url": url, "status": "robots_blocked", "sent_at": sent, "at": now()})
        return ("robots", None, url, 0, "")
    except Exception as e:
        COUNT["errors"] += 1
        reqlog({"url": url, "status": f"error {type(e).__name__}", "sent_at": sent, "at": now()})
        raise HardStop(f"network/TLS error (not retried): {type(e).__name__} {str(e)[:160]}")
    finally:
        S.hop_times = None
    hops = [h.url for h in r.history]
    if any((urlparse(h).hostname or "") not in ALLOWED for h in hops + [r.url]):
        r.close()
        reqlog({"url": url, "status": r.status_code, "final": r.url, "hops": hops, "sent_at": sent, "at": now(), "note": "redirect off-host"})
        raise HardStop(f"redirect left the assembly host: {hops + [r.url]}")
    ctype = r.headers.get("content-type", "")
    reqlog({"url": url, "status": r.status_code, "final": r.url, "hops": hops, "ctype": ctype, "server": r.headers.get("server", ""),
            "cf_ray": bool(r.headers.get("cf-ray")), "cf_mitigated": r.headers.get("cf-mitigated"), "sent_at": sent, "at": now()})
    if "html" in ctype.lower() or r.status_code != 200 or stream_to is None:
        raw = b""
        for ch in r.iter_content(262144):
            raw += ch
            if len(raw) > cap:
                break
        r.close()
        txt = raw.decode(r.encoding or "utf-8", "replace")
        cf_check(r, txt)
        return (r.status_code if stream_to is None else "not_pdf", txt, r.url, len(raw), ctype)
    cf_check(r, "")
    n = 0
    with open(stream_to, "wb") as fh:
        for ch in r.iter_content(262144):
            n += len(ch)
            if n > MAX_DOC:
                r.close()
                return ("too_large", None, r.url, n, ctype)
            fh.write(ch)
    r.close()
    head = open(stream_to, "rb").read(20000).decode("latin-1", "replace")
    if not head.startswith("%PDF") and CF_BODY.search(head):
        COUNT["cloudflare_signals"] += 1
        raise HardStop(f"CLOUDFLARE challenge body at {url}")
    return (r.status_code, None, r.url, n, ctype)


# ------------------------------------------------------------------ RSS (self + children)
RSS_MAX_MIB = float(os.environ.get("KE_RSS_MAX_MIB", "1024"))


def rss_tree_mib():
    """RSS of this process and all its descendants (MiB), from /proc."""
    me = os.getpid()
    kids, rss = {}, {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            st = open(f"/proc/{d}/stat").read()
            ppid = int(st.rsplit(")", 1)[1].split()[1])
            kids.setdefault(ppid, []).append(int(d))
            for line in open(f"/proc/{d}/status"):
                if line.startswith("VmRSS:"):
                    rss[int(d)] = int(line.split()[1]) / 1024
                    break
        except (OSError, ValueError, IndexError):
            continue
    tot, todo = 0.0, [me]
    while todo:
        p = todo.pop()
        tot += rss.get(p, 0.0)
        todo.extend(kids.get(p, []))
    return tot


PEAK = {"rss_mib": 0.0}


def watchdog2():
    while STOP["reason"] is None:
        r = rss_tree_mib()
        PEAK["rss_mib"] = max(PEAK["rss_mib"], r)
        if r > RSS_MAX_MIB:
            STOP["reason"] = f"RSS of collector + children {r:.0f} MiB > {RSS_MAX_MIB:.0f} MiB"
        time.sleep(2)


def other_runner_slots():
    """Fleet runner slots currently held (lslocks; read only, no lock taken)."""
    try:
        out = run(["lslocks", "-n", "-o", "PATH"]).stdout.split()
    except Exception:
        return []
    return sorted({p for p in out if re.search(r"/dev/shm/muni_runner(\.slot\d)?\.lock$", p)})


# ------------------------------------------------------------------ listing + selection
A_RX = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
DOC_RX = re.compile(r"\.(?:pdf|docx?|odt)(?:$|\?)", re.I)


def norm_url(u, base):
    u = urljoin(base, html.unescape(u.strip()))
    p = urlparse(u)
    if (p.hostname or "") in ALLOWED:
        u = "https://www." + FAMILY + quote(unquote(p.path), safe="/,()-_.~") + (("?" + p.query) if p.query else "")
    return u


def parse_links(page):
    """Document links of the listing in page order; the same URL appears as the title link and as 'Download' (the title
    text is kept); off-host links (Google Docs 'Preview') are recorded as excluded, never fetched."""
    out, idx = [], {}
    for href, inner in A_RX.findall(page):
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", inner))).strip()
        if "{{" in href or not t:
            continue
        u = norm_url(href, LIST_URL)
        host = urlparse(u).hostname or ""
        if host in ALLOWED and not DOC_RX.search(urlparse(u).path):
            continue
        if host not in ALLOWED and t.lower() != "preview":
            continue
        if u in idx:
            if out[idx[u]]["title"].lower() in ("download", "preview") and t.lower() not in ("download", "preview"):
                out[idx[u]]["title"] = t
            continue
        idx[u] = len(out)
        out.append({"url": u, "title": t, "href_raw": href})
    return out


def classify(it):
    t, u = it["title"], it["url"]
    if (urlparse(u).hostname or "") not in ALLOWED:
        return "exclude", "off_host_preview_link (Google Docs viewer of a listed file; never fetched)"
    if re.search(r"\bBill\b", t, re.I):
        return "exclude", "bill (not enacted)"
    if re.search(r"\bpolic(?:y|ies)\b", t, re.I):
        return "exclude", "policy (not legislation)"
    if re.search(r"\breports?\b|\bhansard\b|\bminutes\b|\bplan\b|\bbudget\b|\bstatement\b", t, re.I):
        return "exclude", "report_or_paper (not legislation)"
    if re.search(r"\bRegulations?\b|\bRules\b", t, re.I) and not re.search(r"\bSamburu\b", t, re.I):
        return "exclude", "national_subsidiary_legislation (not made by the county assembly)"
    if re.search(r"\bAct\b", t, re.I) and re.search(r"\bSamburu\b", t, re.I):
        return "keep", "samburu_county_act_by_title; maker confirmed from the enacting clause by the stager"
    if re.search(r"\bAct\b", t, re.I):
        return "exclude", "national_act (not made by the county assembly)"
    return "exclude", "not_legislation"


# ------------------------------------------------------------------ text
FUNC_WORDS = frozenset("""the of and to in a by be shall or any for is on as at with from this that such which under these all are
not an no county assembly act person may who has have it its other made than into each been section schedule within upon said
where his her their there was were will if out so then per one two fees fee time period day days""".split())


def function_word_share(text):
    toks = re.findall(r"[A-Za-z]{2,}", text)
    return round(sum(1 for x in toks if x.lower() in FUNC_WORDS) / len(toks), 3) if len(toks) >= 30 else None


def short_line_share(text):
    ls = [l for l in text.splitlines() if l.strip()]
    return round(sum(1 for l in ls if len(l.split()) <= 3) / len(ls), 3) if ls else None


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def pdf_info(pdf):
    out = run(["pdfinfo", str(pdf)]).stdout
    d = {}
    for l in out.splitlines():
        if ":" in l:
            k, v = l.split(":", 1)
            d[k.strip()] = v.strip()
    fonts = run(["pdffonts", str(pdf)]).stdout.splitlines()[2:]
    return {"pages": int(d.get("Pages", "0") or 0), "producer": d.get("Producer", ""), "creator": d.get("Creator", ""),
            "pdf_title": d.get("Title", ""), "fonts": len(fonts), "page_size": d.get("Page size", "")}


def image_pages(pdf):
    out = run(["pdfimages", "-list", str(pdf)]).stdout.splitlines()[2:]
    big = {}
    for l in out:
        p = l.split()
        try:
            if int(p[3]) * int(p[4]) >= 40000:
                big[int(p[0])] = max(big.get(int(p[0]), 0), int(p[12]) if len(p) > 12 and p[12].isdigit() else 0)
        except (ValueError, IndexError):
            pass
    return big   # page -> x-ppi of its largest image


def pages_text(pdf, layout):
    """layout=True: -layout; False: default reading order; "raw": content-stream order (the order in which a scanner app
    wrote its OCR layer: lines in order, left page of a two-page spread before the right page)."""
    a = ["pdftotext", "-enc", "UTF-8"] + (["-raw"] if layout == "raw" else ["-layout"] if layout else []) + [str(pdf), "-"]
    return run(a).stdout.split("\f")


def body_chars(t):
    return len(re.sub(r"\s+", "", t))


def assess(pdf):
    """Text-layer assessment (no OCR): which pages keep their text layer and which need OCR."""
    info = pdf_info(pdf)
    n = info["pages"]
    lay, pla, raw = pages_text(pdf, True), pages_text(pdf, False), pages_text(pdf, "raw")
    lay, pla, raw = (lay + [""] * n)[:n], (pla + [""] * n)[:n], (raw + [""] * n)[:n]
    imgs = image_pages(pdf)
    alltxt = "\n".join(pla)
    fws, sls = function_word_share(alltxt), short_line_share(alltxt)
    garbled = body_chars(alltxt) >= 200 and ((fws is not None and fws < 0.25) or (sls is not None and sls > 0.75))
    need = [i + 1 for i in range(n) if garbled or body_chars(pla[i]) < 100]
    # page-level garble: a kept text-layer page whose lexical share is below PAGE_LEX_MIN is a garbled layer
    # (phone captures: one half of a spread can be badly recognised) -> OCR candidate; the merge keeps whichever
    # of layer / OCR scores higher on that page.
    page_garbled = []
    for i in range(n):
        if (i + 1) in need:
            continue
        pl, nt = lexical_share(raw[i])
        if pl is not None and nt >= 40 and pl < PAGE_LEX_MIN:
            page_garbled.append({"page": i + 1, "layer_lexical_share": pl, "alpha_tokens": nt})
    need = sorted(set(need) | {g["page"] for g in page_garbled})
    scan = len(imgs) >= n > 0   # every page carries a page-size image (phone / scanner capture)
    full_need = [p for p in need if p not in {g["page"] for g in page_garbled}]
    kind = (("scan_with_usable_text_layer" if scan else "born_digital_text_layer") if not full_need else "scan_no_text_layer" if body_chars(alltxt) < 200 else
            "garbled_text_layer" if garbled else "mixed")
    return {**info, "image_pages": sorted(imgs), "image_ppi": {str(k): v for k, v in sorted(imgs.items())},
            "function_word_share": fws, "short_line_share": sls, "text_layer_chars": body_chars(alltxt),
            "text_layer_garbled": garbled, "garbled_layer_pages": page_garbled, "ocr_needed_pages": need, "doc_kind": kind}, lay, raw


_WORDS = None


def wordlist():
    """tesseract's own English word list (eng.traineddata word DAWG), extracted once into the stage dir."""
    global _WORDS
    if _WORDS is None:
        wl = STAGE / "eng_wordlist.txt"
        if not wl.exists():
            tmp = STAGE / "tmp" / "tessdata_unpack"
            tmp.mkdir(parents=True, exist_ok=True)
            td = os.environ.get("TESSDATA_PREFIX") or "/usr/share/tesseract-ocr/5/tessdata"
            run(["combine_tessdata", "-u", str(Path(td) / "eng.traineddata"), str(tmp / "eng.")])
            run(["dawg2wordlist", str(tmp / "eng.lstm-unicharset"), str(tmp / "eng.lstm-word-dawg"), str(wl)])
            for p in tmp.iterdir():
                p.unlink()
            tmp.rmdir()
        _WORDS = {w.strip().lower() for w in open(wl) if w.strip()}
    return _WORDS


def lexical_share(text):
    toks = [t.lower() for t in re.findall(r"[A-Za-z]{3,}", text)]
    return (round(sum(1 for t in toks if t in wordlist()) / len(toks), 3) if len(toks) >= 20 else None), len(toks)


PSM = os.environ.get("KE_OCR_PSM", "3")
PAGE_LEX_MIN = float(os.environ.get("KE_PAGE_LEX_MIN", "0.85"))


def ocr_page(pdf, pno, odir):
    """OCR one page; result cached as odir/pNNNN.json (resumable)."""
    out = odir / f"p{pno:04d}.json"
    if out.exists():
        return json.loads(out.read_text())
    gates()
    base = odir / f"p{pno:04d}"
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    run(["pdftoppm", "-r", "300", "-gray", "-png", "-f", str(pno), "-l", str(pno), "-singlefile", str(pdf), str(base)])
    png = Path(str(base) + ".png")
    tsv = run(["tesseract", str(png), "stdout", "-l", "eng", "--psm", PSM, "-c", "preserve_interword_spaces=1", "tsv"], env=env).stdout
    png.unlink(missing_ok=True)
    rows = [r.split("\t") for r in tsv.splitlines()[1:]]
    words = [(r, float(r[10])) for r in rows if len(r) > 11 and r[11].strip() and r[10] not in ("-1", "")]
    # rebuild text from the TSV (block/par/line structure) so text and confidences come from ONE tesseract pass
    lines, key = [], None
    for r, c in words:
        k = (r[2], r[3], r[4])
        if k != key:
            if key is not None and k[:2] != key[:2]:
                lines.append("")
            lines.append(r[11]); key = k
        else:
            lines[-1] += " " + r[11]
    text = "\n".join(lines)
    confs = [c for _, c in words]
    lex, ntok = lexical_share(text)
    res = {"page": pno, "text": text, "words": len(confs), "mean_conf": round(sum(confs) / len(confs), 1) if confs else None,
           "hi_conf_share": round(sum(1 for c in confs if c >= 70) / len(confs), 3) if confs else None,
           "lexical_share": lex, "alpha_tokens": ntok, "psm": PSM}
    out.write_text(json.dumps(res, ensure_ascii=False))
    return res


def reassess():
    """KE_MODE=reassess (offline): re-run the text-layer assessment on PDFs already on disk (records.jsonl rewritten,
    text/<key>.layout.txt + .raw.txt regenerated); no network."""
    recs = [json.loads(l) for l in open(STAGE / "records.jsonl")]
    out = []
    for r in recs:
        pdf = STAGE / "pdf" / f"{r.get('key')}.pdf"
        if r.get("sha256") and pdf.exists():
            meta, lay, raw = assess(pdf)
            (STAGE / "text" / f"{r['key']}.layout.txt").write_text("\f".join(lay))
            (STAGE / "text" / f"{r['key']}.raw.txt").write_text("\f".join(raw))
            r.update(meta)
        out.append(r)
    (STAGE / "records.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
    log("reassess:", {k: sum(1 for r in out if r.get("doc_kind") == k) for k in sorted({r.get("doc_kind") for r in out})})
    return 0


def ocr_all():
    """KE_MODE=ocr (offline): OCR the pages flagged by the assessment, merge with kept text-layer pages, write
    text/<key>.txt (pages separated by form feeds) and ocr_results.jsonl (per-law quality)."""
    from concurrent.futures import ThreadPoolExecutor
    threading.Thread(target=watchdog, daemon=True).start()
    threading.Thread(target=watchdog2, daemon=True).start()
    held = other_runner_slots()
    want = int(os.environ.get("KE_OCR_WORKERS", "2"))
    workers = max(1, min(want, 2 if held else 3))
    log(f"OCR workers {workers} (requested {want}; runner slots held by others: {held})")
    recs = [json.loads(l) for l in open(STAGE / "records.jsonl")]
    results = {}
    if (STAGE / "ocr_results.jsonl").exists():
        for l in open(STAGE / "ocr_results.jsonl"):
            r = json.loads(l); results[r["key"]] = r
    for r in recs:
        if not r.get("sha256") or (r["key"] in results and results[r["key"]].get("ocr_pages") == (r.get("ocr_needed_pages") or [])):
            continue
        pdf = STAGE / "pdf" / f"{r['key']}.pdf"
        lay = (STAGE / "text" / f"{r['key']}.raw.txt").read_text().split("\f")   # kept text-layer pages: raw order
        need = r.get("ocr_needed_pages") or []
        odir = STAGE / "ocr" / r["key"]; odir.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            pages = list(ex.map(lambda p: ocr_page(pdf, p, odir), need))
        if STOP["reason"]:
            raise HardStop(STOP["reason"])
        byp = {p["page"]: p for p in pages}
        choice = {}
        for g in r.get("garbled_layer_pages") or []:   # page-level garble: keep the better of layer / OCR
            o = byp.get(g["page"])
            if o is not None and (o["lexical_share"] or 0) <= g["layer_lexical_share"]:
                byp.pop(g["page"]); choice[g["page"]] = "text_layer_kept"
            elif o is not None:
                choice[g["page"]] = "ocr"
        merged = [byp[i + 1]["text"] if (i + 1) in byp else lay[i] for i in range(r["pages"])]
        (STAGE / "text" / f"{r['key']}.txt").write_text("\f".join(merged))
        ws_ = sum(p["words"] for p in pages)
        conf = round(sum((p["mean_conf"] or 0) * p["words"] for p in pages) / ws_, 1) if ws_ else None
        toks = sum(p["alpha_tokens"] for p in pages)
        lex = round(sum((p["lexical_share"] or 0) * p["alpha_tokens"] for p in pages) / toks, 3) if toks else None
        res = {"key": r["key"], "url": r["url"], "pages": r["pages"], "ocr_pages": need, "ocr_words": ws_,
               "ocr_mean_conf": conf, "ocr_hi_conf_share": round(sum((p["hi_conf_share"] or 0) * p["words"] for p in pages) / ws_, 3) if ws_ else None,
               "ocr_lexical_share": lex, "pages_low_quality": [p["page"] for p in pages if (p["mean_conf"] or 0) < 60 or (p["lexical_share"] or 0) < 0.6],
               "page_metrics": [{k: p[k] for k in ("page", "words", "mean_conf", "hi_conf_share", "lexical_share")} for p in pages],
               "text_backend": ("pdf_text_layer" if not need else "ocr_tesseract_eng" if len(need) == r["pages"] else "pdf_text_layer+ocr_tesseract_eng"),
               "garbled_layer_pages": r.get("garbled_layer_pages") or [], "garbled_page_choice": choice,
               "ocr_psm": PSM, "ocr_workers": workers, "seconds": round(time.time() - t0, 1), "at": now()}
        results[r["key"]] = res
        (STAGE / "ocr_results.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in results.values()))
        log(f"{r['key']} {r['list_title'][:50]}: ocr {len(need)}/{r['pages']} pages conf={conf} lex={lex} {res['seconds']} s "
            f"peak RSS {PEAK['rss_mib']:.0f} MiB")
    log(f"OCR DONE; peak RSS (self + children) {PEAK['rss_mib']:.0f} MiB")
    return 0


# ------------------------------------------------------------------ main
def main():
    if os.environ.get("KE_MODE") == "ocr":
        return ocr_all()
    if os.environ.get("KE_MODE") == "reassess":
        return reassess()
    STAGE.mkdir(parents=True, exist_ok=True)
    for d in ("pdf", "text", "tmp"):
        (STAGE / d).mkdir(exist_ok=True)
    threading.Thread(target=watchdog, daemon=True).start()
    threading.Thread(target=watchdog2, daemon=True).start()
    start_pacing()
    log(f"pacer: last send to {FAMILY} in logs: {iso_ms(PACER.last) if PACER.last else None}; gap {PACER.gap()} s")
    d = rg.check(LIST_URL)   # the only robots.txt fetch of this run (robots_guard caches it for the run)
    RUN_NOTES.append({"robots_check": {"url": LIST_URL, "allowed": d.allowed, "reason": d.reason, "robots_status": d.robots_status,
                                       "robots_http_status": d.robots_http_status, "crawl_delay": d.crawl_delay, "at": now()}})
    log("robots:", d.reason, d.robots_status, d.robots_http_status, "crawl_delay", d.crawl_delay)
    if not d.allowed:
        raise HardStop(f"robots: listing not allowed ({d.reason})")
    st, page, final, n, ctype = get(LIST_URL)
    if st != 200:
        raise HardStop(f"listing http {st}")
    (STAGE / "listing_acts.html").write_bytes(page.encode("utf-8"))
    items = parse_links(page)
    keep, excl = [], []
    for k, it in enumerate(items, 1):
        dec, why = classify(it)
        (keep if dec == "keep" else excl).append({"listing_ordinal": k, **it, "decision": dec, "reason": why, "listing_url": LIST_URL})
    sel = {"listing_url": LIST_URL, "listing_sha256": hashlib.sha256(page.encode()).hexdigest(), "listing_bytes": len(page.encode()),
           "document_links": len(items), "keep": keep, "excluded": excl, "at": now(),
           "page_title": (re.search(r"<title>(.*?)</title>", page, re.S | re.I) or [None, ""])[1]}
    (STAGE / "selection.json").write_text(json.dumps(sel, indent=1, ensure_ascii=False))
    log(f"listing: {len(items)} document links; keep {len(keep)}; exclude {len(excl)}")
    done = {}
    if (STAGE / "records.jsonl").exists():
        for l in open(STAGE / "records.jsonl"):
            r = json.loads(l); done[r["url"]] = r
    for it in keep:
        if it["url"] in done:
            continue
        h = hashlib.sha1(it["url"].encode()).hexdigest()[:12]
        pdf = STAGE / "pdf" / f"{h}.pdf"
        st, _, final, n, ctype = get(it["url"], stream_to=pdf)
        rec = {"url": it["url"], "final_url": final, "list_title": it["title"], "listing_ordinal": it["listing_ordinal"],
               "http_status": st, "ctype": ctype, "bytes": n, "retrieved_at": now(), "key": h}
        if st == 200 and pdf.exists() and open(pdf, "rb").read(5).startswith(b"%PDF"):
            b = pdf.read_bytes()
            rec.update({"sha256": hashlib.sha256(b).hexdigest(), "sha1": hashlib.sha1(b).hexdigest()})
            meta, lay, raw = assess(pdf)
            (STAGE / "text" / f"{h}.layout.txt").write_text("\f".join(lay))
            (STAGE / "text" / f"{h}.raw.txt").write_text("\f".join(raw))
            rec.update(meta)
            COUNT["pdf_downloads"] += 1
        else:
            rec["error"] = f"not a PDF (status {st}, {ctype})"
        with open(STAGE / "records.jsonl", "a") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log(f"{it['title'][:60]}: {st} {n} B pages={rec.get('pages')} kind={rec.get('doc_kind')} ocr_pages={len(rec.get('ocr_needed_pages') or [])}")
    summ = {"parser_version": PARSER_VERSION, "finished_at": now(), "counts": dict(COUNT), "notes": RUN_NOTES,
            "peak_rss_mib": round(PEAK["rss_mib"]),
            "sends_this_run": [{"sent_at": iso_ms(t), "host": h, "kind": k, "url": u, "required_gap_s": g,
                                "gap_s": (round(a, 3) if a is not None else None)} for t, h, k, u, g, a in PACER.sends]}
    with open(STAGE / "collect_runs.jsonl", "a") as fh:
        fh.write(json.dumps(summ, ensure_ascii=False) + "\n")
    gaps = [a for *_, a in PACER.sends if a is not None]
    log(f"DONE {dict(COUNT)} sends={len(PACER.sends)} min_gap={min(gaps) if gaps else None}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HardStop as e:
        log("HARD STOP:", e)
        with open(STAGE / "collect_runs.jsonl", "a") as fh:
            fh.write(json.dumps({"hard_stop": str(e), "at": now(), "counts": dict(COUNT)}) + "\n")
        sys.exit(3)
