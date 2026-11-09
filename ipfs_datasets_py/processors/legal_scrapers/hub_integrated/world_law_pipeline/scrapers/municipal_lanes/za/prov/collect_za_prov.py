#!/usr/bin/env python3
"""ZA provincial pack1 (batch 1): ENACTED provincial Acts from the Western Cape Provincial Parliament (www.wcpp.gov.za)
and the KwaZulu-Natal Legislature (kznlegislature.gov.za /acts-bills/), for the new repo
endomorphosis/ipfs_south_africa_provincial_laws. Fetch core adapted from the fleet ZA metro batch-6 collector (itself derived
from endomorphosis/ipfs_datasets_py @a1b5c73e5b687d8bd6c3b3051788860fd6e2f07a national_collectors: catalog -> fetch -> extract).
Policies:
  * Origin hosts only (www.wcpp.gov.za, kznlegislature.gov.za, + www.wikidata.org Special:EntityData for 2 QIDs); https only;
    no Wayback/CC; no logins/forms; no challenge bypass; fleet UA unchanged (robots_guard.ROBOTS_UA).
  * TLS verify ON; fail closed on TLS errors.
  * Every send (incl. robots.txt and each redirect hop) via fleet robots_guard + per-host pacer gap >= max(8 s, Crawl-Delay)
    (wcpp asks Crawl-delay 10), one request in flight.
  * Hard stop on 403/429/503 or challenge markup. Timeouts/connection resets: retry once, then skip.
  * v2 watchdog: pause MemAvailable < 4 GiB held 60 s (resume >= 5.5 GiB held 120 s); hard stop < 3 GiB held 15 s; tree RSS <= 1 GiB.
  * pdftotext text layers only; PDFs without usable text are marked needs_ocr (separate OCR step).
  * Resumable (catalog.json, results.jsonl, cache/).
Usage: collect_za_prov.py --catalog-only | [--max N]    Env: ZA_WORK
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

W = Path(os.environ.get("ZA_WORK", (str(_LEGAL_WS) + "/world_laws/za_prov")))
os.environ["LEGAL_CORPORA_ROOT"] = str(W / "root")
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import robots_guard as rg  # noqa: E402  (fleet copy)
except ImportError:  # shipped name in the pack's scrapers/
    import robots_guard_b1 as rg  # noqa: E402
import requests  # noqa: E402

rg.set_country("za")
ALLOWED = {"www.wcpp.gov.za", "kznlegislature.gov.za", "www.kznlegislature.gov.za", "www.wikidata.org"}
FLOOR = max(8.0, float(os.environ.get("ZA_FLOOR", "8")))
MAX_DOC = 60 * 1024 * 1024
CHAL_V1 = re.compile(r"<title[^>]*>\s*(?:Just a moment|Attention Required|Access denied|Please wait|One more step)|"
                  r"_cf_chl_opt|cf-browser-verification|challenge-platform|cf-turnstile|checking your browser|"
                  r"Enable JavaScript and cookies to continue|sgcaptcha|ddos-guard|incapsula|px-captcha|"
                  r"datadome|awswaf|hcaptcha|recaptcha|imunify360|bot-check", re.I)
# v2 (narrowed after the 2026-10-13 KZN re-read, only if that re-read classified the hit as a passive captcha script include):
# bare 'recaptcha'/'hcaptcha' no longer match (a site-key script on a normal page); a captcha only counts when it is the page's
# interstitial (captcha/verify/security-check title, or a captcha widget on a page with almost no content). 403/429/503 and
# cf-mitigated stops are unchanged; every real interstitial/JS-wall marker of v1 is kept.
CHAL_V2 = re.compile(r"<title[^>]*>\s*(?:Just a moment|Attention Required|Access denied|Please wait|One more step|"
                  r"[^<]{0,40}(?:captcha|verify you are human|are you a robot|security check|bot verification))|"
                  r"_cf_chl_opt|cf-browser-verification|challenge-platform|cf-turnstile|checking your browser|"
                  r"Enable JavaScript and cookies to continue|sgcaptcha|ddos-guard|incapsula|px-captcha|"
                  r"datadome|awswaf|imunify360|bot-check|verify you are human|please complete the security check", re.I)
CAPTCHA_WIDGET = re.compile(r'class="[^"]*(?:g-recaptcha|h-captcha)[^"]*"', re.I)
DETECTOR_FILE = W / "detector_v2.json"


class _Chal:
    def search(self, txt):
        if not DETECTOR_FILE.exists():
            return CHAL_V1.search(txt)
        m = CHAL_V2.search(txt)
        if m:
            return m
        vis = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>|<[^>]+>", " ", txt)
        if CAPTCHA_WIDGET.search(txt) and len(vis.split()) < 150:
            return CAPTCHA_WIDGET.search(txt)
        return None


CHAL = _Chal()
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
LIGHT = os.environ.get("ZA_LIGHT_FETCH") == "1"  # light fetch lane: hard <1.5 GiB 15 s, tree RSS 300 MB, no soft pause
HARD_G, RSS_CAP = (1.5, 300) if LIGHT else (3.0, 1024)
LOW = {"hard": None, "soft": None}
PEAK = {"rss": 0.0}


def watchdog():
    while STOP["reason"] is None:
        m = mem_gib(); now = time.time()
        LOW["hard"] = (LOW["hard"] or now) if m < HARD_G else None
        LOW["soft"] = (LOW["soft"] or now) if (m < 4.0 and not LIGHT) else None
        r = rss_mib()
        if LOW["hard"] and now - LOW["hard"] >= 15:
            STOP["reason"] = f"hard_stop MemAvailable {m:.2f} GiB < {HARD_G} GiB held 15 s ({'light' if LIGHT else 'v2'})"
        elif disk_mib() < 12500:
            STOP["reason"] = f"hard_stop disk {disk_mib():.0f} MiB < 12500"
        elif r > RSS_CAP:
            STOP["reason"] = f"hard_stop tree RSS {r:.0f} MiB > {RSS_CAP} MiB ({'light' if LIGHT else 'v2'})"
        PEAK["rss"] = max(PEAK["rss"], r)
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


def get(url, kind, stream_to: Path | None = None, detect=True):
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
    if detect and "<html" in txt[:5000].lower() and CHAL.search(txt[:400000]):
        raise HardStop(f"challenge markup at {url}")
    return r.status_code, txt



LISTINGS_ALL = [("wc", "https://www.wcpp.gov.za/?q=legislation"), ("wc", "https://www.wcpp.gov.za/?q=bill-tracking-view"),
                ("kzn", "https://kznlegislature.gov.za/acts-bills/")]
PROVS = set(os.environ.get("ZA_PROVINCES", "wc").split(","))  # pack1 = WC only (CoS GO 2026-10-13); KZN not in pack1
LISTINGS = [x for x in LISTINGS_ALL if x[0] in PROVS]
KZN_URL = "https://kznlegislature.gov.za/acts-bills/"
PAGER = re.compile(r"[?&](?:page|paged|cp)=\d+|/page/\d+/?$")
HTMLC = W / "cache" / "html"
QIDS = {k: v for k, v in {"wc": "Q127167", "kzn": "Q81725"}.items() if k in PROVS}


def clean(s):
    import html as H
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:140]


def links(html, base):
    for href, lab in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', html, re.I | re.S):
        yield urljoin(base, href.replace("&amp;", "&")), clean(lab)


def discover():
    if CAT.exists():
        return json.load(open(CAT))
    from urllib.parse import unquote
    items, seen, pages = [], set(), 0
    for prov, root in LISTINGS:
        queue, done = [root], set()
        while queue and len(done) < 80:
            url = queue.pop(0)
            if url in done:
                continue
            done.add(url)
            ck = HTMLC / f"url_{hashlib.sha256(url.encode()).hexdigest()[:20]}.html"
            if ck.exists():
                st, html = 200, ck.read_text()  # resume: listing already fetched this job series
            else:
                st, html = with_retry(url, "listing_html")
                if st == 200 and html: ck.write_text(html)
            if st != 200 or not html:
                status(f"listing {url} status {st} (skipped)"); continue
            pages += 1
            (HTMLC / f"listing_{prov}_{len(done)}_{slug(urlsplit(url).path + urlsplit(url).query)[:60]}.html").write_text(html)
            base_host = urlsplit(root).hostname; root_key = (urlsplit(root).path, re.sub(r"&?(?:page|paged|cp)=\d+", "", urlsplit(root).query))
            for full, lab in links(html, url):
                s = urlsplit(full)
                if (s.hostname or "") not in ALLOWED or s.scheme != "https":
                    continue
                if PAGER.search(full) and (re.sub(r"/page/\d+/?$", "/", s.path) == root_key[0] or s.path == root_key[0]) and \
                        re.sub(r"&?(?:page|paged|cp)=\d+", "", s.query).strip("&") == root_key[1] and full not in done and full not in queue:
                    queue.append(full); continue
                if prov == "wc":
                    ok = s.path.lower().endswith(".pdf") and "/sites/default/files/" in s.path
                else:
                    ok = s.path.startswith("/download/") or (s.path.lower().endswith(".pdf") and "/wp-content/uploads/" in s.path)
                if not ok or full in seen or not lab:
                    continue
                seen.add(full)
                fn = unquote(s.path.rstrip("/").rsplit("/", 1)[-1])
                items.append({"src": prov, "ident": f"{prov}-" + slug(re.sub(r"\.pdf$", "", fn, flags=re.I)), "url": full, "title": lab,
                              "filename": fn, "listing_url": url})
        status(f"listing {prov} {root} pages={len(done)} catalog={len(items)}")
    json.dump(items, open(CAT, "w"), indent=1, ensure_ascii=False)
    status(f"CATALOG_DONE n={len(items)} pages={pages}")
    return items


def qids():
    out = W / "qids.json"
    if out.exists():
        return
    res = {}
    for prov, q in QIDS.items():
        st, txt = with_retry(f"https://www.wikidata.org/wiki/Special:EntityData/{q}.json", "wikidata_entity")
        lab = None
        if st == 200 and txt:
            try:
                e = json.loads(txt)["entities"]; e = e.get(q) or next(iter(e.values()))
                lab = e["labels"]["en"]["value"]
            except Exception:
                lab = None
        res[prov] = {"qid": q, "status": st, "label_en": lab}
    json.dump(res, open(out, "w"), indent=1)
    status(f"QIDS {json.dumps(res)}")


def resolve_kzn(it):
    """kznlegislature /download/<slug>/ pages (WordPress Download Manager): find the same-host file link on the page."""
    st, html = with_retry(it["url"], "download_page_html")
    if st != 200 or not html:
        return None, st
    (HTMLC / f"dl_{it['ident']}.html").write_text(html)
    cands = []
    for full, lab in links(html, it["url"]):
        s = urlsplit(full)
        if (s.hostname or "") not in ALLOWED:
            continue
        if "wpdmdl=" in s.query or s.path.lower().endswith(".pdf"):
            cands.append(full)
    cands += [urljoin(it["url"], u.replace("&amp;", "&")) for u in re.findall(r'data-downloadurl="([^"]+)"', html)]
    cands = [c for c in cands if (urlsplit(c).hostname or "") in ALLOWED and "Booklet-public-participation" not in c]
    return (cands[0] if cands else None), st


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


def kzn_reread():
    """ONE gated re-read of the KZN listing (CoS GO 2026-10-13), saved to disk; classify which v1 pattern fired.
    403/429/503/cf-mitigated still hard-stop inside get(). Never retried, never bypassed."""
    out = W / "kzn_reread.json"
    if out.exists():
        return
    rg.check  # robots_guard on the hop happens inside get()
    try:
        st, html = get(KZN_URL, "kzn_reread_html", detect=False)
    except (HardStop, Transient) as e:
        if STOP["reason"]:
            raise
        rep = {"url": KZN_URL, "result": "hard_stop_or_error", "error": str(e)[:200], "decision": "park_kzn"}
        json.dump(rep, open(out, "w"), indent=1); status(f"KZN_REREAD {rep['result']}"); return
    html = html or ""
    if st == 200 and html:
        (HTMLC / "kzn_reread_acts-bills.html").write_text(html)
    hits = []
    for m in CHAL_V1.finditer(html[:400000]):
        a = max(0, m.start() - 160); ctx = re.sub(r"\s+", " ", html[a:m.end() + 160])
        hits.append({"pattern": m.group(0)[:60], "offset": m.start(), "in_script_tag": bool(re.search(r"<script[^>]*$", html[a:m.start()], re.I) or
                     re.search(r"<script[^>]*src=[^>]*$", html[max(0, m.start()-400):m.start()], re.I)), "context": ctx[:400]})
    title = clean((re.search(r"(?is)<title[^>]*>(.*?)</title>", html) or [None, ""])[1])
    vis = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>|<[^>]+>", " ", html)
    words = len(vis.split())
    kl = [(f, l) for f, l in links(html, KZN_URL) if (urlsplit(f).hostname or "") in ALLOWED and
          (urlsplit(f).path.startswith("/download/") or (urlsplit(f).path.lower().endswith(".pdf") and "/wp-content/uploads/" in urlsplit(f).path))]
    real = bool(CHAL_V2.search(html[:400000])) or (CAPTCHA_WIDGET.search(html) and words < 150)
    passive = bool(hits) and all(re.fullmatch(r"(?i)recaptcha|hcaptcha", h["pattern"]) for h in hits) and not real and words >= 500 and len(kl) > 0
    # count enacted KZN Acts on the readable listing using the pack scope filter (labels only; nothing fetched)
    n_act = None
    if passive or (not hits and st == 200):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from plan_za_prov import NONACT, fold as _f
        acts = {}
        for f, l in kl:
            both = f"{l} {unquote_(f)}"
            if re.search(r"(?i)\bact\b", _f(both)) and not NONACT.search(_f(both)):
                acts[f] = l
        n_act = len(acts)
        json.dump([{"url": f, "label": l} for f, l in acts.items()], open(W / "kzn_enacted_acts_listing.json", "w"), indent=1, ensure_ascii=False)
    rep = {"url": KZN_URL, "http_status": st, "bytes": len(html.encode()), "title": title, "visible_words": words,
           "listing_doc_links": len(kl), "v1_hits": hits, "v2_real_interstitial": bool(real),
           "classification": "passive_captcha_script_include" if passive else ("no_v1_hit" if not hits else "possible_real_challenge"),
           "decision": "narrow_detector_v2" if passive else ("no_change" if not hits and st == 200 else "park_kzn"),
           "kzn_enacted_acts_on_listing": n_act, "saved_html": "cache/html/kzn_reread_acts-bills.html" if html else None, "read_at": utc()}
    json.dump(rep, open(out, "w"), indent=1, ensure_ascii=False)
    if passive:
        json.dump({"detector": "v2", "since": utc(), "reason": "KZN re-read: v1 hit was only a passive reCAPTCHA/hCaptcha include on a normally served page",
                   "removed": ["bare 'recaptcha'", "bare 'hcaptcha'"], "added": ["captcha/verify/security-check <title>", "captcha widget on near-empty page",
                   "'verify you are human'", "'please complete the security check'"], "kept": "403/429/503 + cf-mitigated hard stops and all v1 interstitial/JS-wall markers"},
                  open(DETECTOR_FILE, "w"), indent=1)
    elif rep["decision"] == "park_kzn":
        (W / "PARKED_kzn.md").write_text(f"# KZN PARKED ({utc()})\nThe gated re-read of {KZN_URL} looks like a real challenge or failed: "
                                         f"classification={rep['classification']}, http={st}. See kzn_reread.json. No retry, no bypass.\n")
    status(f"KZN_REREAD http={st} hits={[h['pattern'] for h in hits]} class={rep['classification']} decision={rep['decision']} kzn_acts={n_act}")


def unquote_(s):
    from urllib.parse import unquote
    return unquote(s)


def main():
    catalog_only = "--catalog-only" in sys.argv
    mx = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 0
    for d in (PDF, TXT, HTMLC):
        d.mkdir(parents=True, exist_ok=True)
    _load_prior_sends()
    rg._robots_fetcher = paced_robots
    threading.Thread(target=watchdog, daemon=True).start()
    items = discover()
    qids()
    if "--kzn-reread" in sys.argv:
        kzn_reread()
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
            if it["src"] == "kzn" and not it["url"].lower().endswith(".pdf"):
                f, st0 = resolve_kzn(it); pdfs = [f] if f else []
                res["download_page_status"] = st0
            else:
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
