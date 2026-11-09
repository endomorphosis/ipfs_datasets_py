#!/usr/bin/env python3
"""Jordan municipal regulations and instructions (أنظمة / تعليمات), official PDFs only:
  * Greater Amman Municipality (GAM), document library "التشريعات" at https://media.ammancity.gov.jo/AR/List/التشريعات
  * Ministry of Local Administration (MoLA), "الانظمة" and "التعليمات" lists at https://www.mola.gov.jo/Ar/List/...
The MoLA "القوانين" (laws) page is NOT used (CoS 2026-10-04 16:12: laws are out of scope / national-law corpus).

MENA municipal Phase B #2 (CoS GO 2026-10-04 16:12), fleet rules v2. Rules: robots_guard on every request and every
redirect hop (GuardedSession, GET and the ASP.NET pagination POST-back), >= 1 s between requests per host, one
connection per host (requests are sequential), no logins / captcha / WAF workarounds, official hosts only, no archive
copies. HARD STOP (rc 7) on a challenge page, an HTTP 401/403, or content that is not from the official site.
www.amman.jo (a second GAM host) is only used if a listed document points there, and only after a strict robots.txt
pre-check (no TLS fallback, no redirects; 403 / challenge / HTML-instead-of-robots / TLS failure => host skipped).
RAM staging only under $JO_STAGE (<= 1 GB); PDFs are deleted after text extraction (page text + OCR are kept
gzip-compressed in textcache/ so parsing/staging can be re-run offline).
Gates / slot / stagger: run_jo_muni.sh (same logic as the TN/PS wrappers) before a slot is taken; this process re-checks
instantaneously and runs the fleet v2 resource monitor. Shared helpers (gates, monitor, PDF text + OCR extraction,
Arabic normalisation, article splitter, code bundle/scan) are imported from collect_ps_molg.py (shipped in scrapers/).
Pipeline: list (3 lists, all pages via POST-back) -> scope filter (أنظمة / تعليمات only) -> fetch PDF -> pdftotext per
page (OCR with tesseract ara for pages without a text layer, <= 3 workers) -> textcache -> parse -> overlap check against
the JO national-law corpus (Hub endomorphosis/ipfs_jordan_laws) -> QA -> Hub layout batch.
Run: ./run_jo_muni.sh                           (slot run: list + fetch + build + stage)
     python3 collect_jo_muni.py --build-offline   (re-parse + re-stage from textcache/ only; no network, no slot)
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import collections, gzip, hashlib, html, json, os, re, shutil, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
STAGE = Path(os.environ.get("JO_STAGE", "/dev/shm/muni_stage/jo"))
os.environ.setdefault("PS_STAGE", str(STAGE))          # the shared helper module reads PS_STAGE at import
import robots_guard as rg            # noqa: E402
import collect_ps_molg as base       # noqa: E402  (shared helpers; its PS-specific globals are re-pointed below)
rg.set_country("muni_mena")

TEXTCACHE = STAGE / "textcache"; TMP = STAGE / "tmp"; BATCHES = STAGE / "batches"
LISTING = STAGE / "listing.json"; LOG = STAGE / "run.log"
def _seed_path(name, fallback):
    p = SCRIPT_DIR / "seeds" / name
    return str(p) if p.exists() else fallback
SEED = Path(os.environ.get("JO_SEED", _seed_path("JO.jsonl", "/dev/shm/muni_seeds/seeds/mena/JO.jsonl")))
WD_CACHE = Path(os.environ.get("JO_WIKIDATA", _seed_path("jo_wikidata_labels.json", str(SCRIPT_DIR / "jo_wikidata_labels.json"))))
HUB_JO_LAWS = Path(os.environ.get("JO_HUB_LAWS", (str(_LEGAL_WS) + "/muni/jo_dev/hub/jo/data/laws.parquet")))
HUB_JO_REPO, HUB_JO_REV = "endomorphosis/ipfs_jordan_laws", "bd8dd9fb9fe1f5ab6c3c0b5f735840c1eca34569"
STATE_PATH = Path(os.environ.get("JO_STATE", str(SCRIPT_DIR / "jo_muni_state.json")))
HUB_REPO = "endomorphosis/ipfs_jordan_municipal_laws"
PARSER_VERSION = 2   # v2: garbled-text-layer pages re-OCRed, JO article splitter, text dedup, plausible dates only
UA = {"User-Agent": rg.ROBOTS_UA, "Accept-Language": "ar,en;q=0.5"}
GAM_QID = "Q8959166"   # Greater Amman Municipality (fleet seed JO.jsonl; label verified via Wikidata EntityData)
LICENSE = ("Official Arabic text of Jordanian local regulations and instructions (أنظمة / تعليمات) as published by the {pub}. "
           "Attribution: {pub_short}. Jordanian copyright law (Law No. 22 of 1992 on the Protection of Copyright, as amended) "
           "excludes official laws, regulations and other official documents from protection; the publisher's website notice "
           "(non-commercial use, attribution) applies to the site itself. The official text as published in the Official "
           "Gazette (الجريدة الرسمية) prevails. Not legal advice.")
SOURCES = [
    {"code": "gam", "host": "media.ammancity.gov.jo", "path": "/AR/List/التشريعات", "list": "التشريعات",
     "marker": ("أمانة عمان",), "pub": "Greater Amman Municipality (أمانة عمان الكبرى), media.ammancity.gov.jo",
     "pub_short": "Greater Amman Municipality (أمانة عمان الكبرى)"},
    {"code": "mola", "host": "www.mola.gov.jo", "path": "/Ar/List/الانظمة", "list": "الانظمة",
     "marker": ("وزارة الادارة المحليه", "وزارة الإدارة المحلية", "وزارة الادارة المحلية"),
     "pub": "Ministry of Local Administration of Jordan (وزارة الإدارة المحلية), www.mola.gov.jo",
     "pub_short": "Ministry of Local Administration, Jordan (وزارة الإدارة المحلية)"},
    {"code": "mola", "host": "www.mola.gov.jo", "path": "/Ar/List/التعليمات", "list": "التعليمات",
     "marker": ("وزارة الادارة المحليه", "وزارة الإدارة المحلية", "وزارة الادارة المحلية"),
     "pub": "Ministry of Local Administration of Jordan (وزارة الإدارة المحلية), www.mola.gov.jo",
     "pub_short": "Ministry of Local Administration, Jordan (وزارة الإدارة المحلية)"},
    # the التعليمات document library says "page 1 of 2" but renders no pager links; the sidebar's static page of the same
    # name is read as well (PDF links inside the content area), and duplicates are dropped by URL.
    {"code": "mola", "host": "www.mola.gov.jo", "path": "/AR/Pages/التعليمات", "list": "التعليمات (صفحة)", "page": True,
     "marker": ("وزارة الادارة المحليه", "وزارة الإدارة المحلية", "وزارة الادارة المحلية"),
     "pub": "Ministry of Local Administration of Jordan (وزارة الإدارة المحلية), www.mola.gov.jo",
     "pub_short": "Ministry of Local Administration, Jordan (وزارة الإدارة المحلية)"},
]
SRC_BY_CODE = {"gam": SOURCES[0], "mola": SOURCES[1]}
OFFICIAL_HOSTS = {"media.ammancity.gov.jo", "www.mola.gov.jo", "www.amman.jo"}
SOURCE_TYPE = {"gam": "jo_gam_local_regulations", "mola": "jo_mola_national_municipal_rules"}
RC_DONE, RC_SLICE, RC_STOP, RC_CHALLENGE = 0, 10, 6, 7

def log(*a):
    s = time.strftime("%Y-%m-%d %H:%M:%S %Z") + " " + " ".join(str(x) for x in a)
    print(s, flush=True)
    with open(LOG, "a") as f: f.write(s + "\n")
def load_state():
    if not STATE_PATH.exists():
        return {"source": "JO GAM التشريعات + MoLA الانظمة/التعليمات (أنظمة / تعليمات only)", "target_repo": HUB_REPO,
                "parser_version": PARSER_VERSION, "fetched": {}, "failed": {}, "batches": {}, "done": False}
    return json.loads(STATE_PATH.read_text())
def save_state(st):
    st["updated"] = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    tmp = STATE_PATH.with_suffix(".json.tmp"); tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1)); os.replace(tmp, STATE_PATH)
# re-point the shared helper module at the JO stage / log / state (monitor, hard_check, extract use these globals)
base.STAGE, base.TEXTCACHE, base.TMP, base.BATCHES, base.LOG = STAGE, TEXTCACHE, TMP, BATCHES, LOG
base.STATE_PATH, base.load_state, base.save_state, base.log = STATE_PATH, load_state, save_state, log
norm_text, n_ar = base.norm_text, base.n_ar

# ---------------------------------------------------------------- network
SESSION = None
ROBOTS_HIT = False
SKIPPED_HOSTS: dict = {}
CHALLENGE_RX = re.compile(r"cf-chl|challenge-platform|captcha|recaptcha|hcaptcha|Just a moment\.\.\.|Attention Required|"
                          r"Request Rejected|The requested URL was rejected|incapsula|_Incapsula_|distil|perimeterx|ddos-guard|"
                          r"sucuri|awswaf|Checking your browser|enable JavaScript and cookies|support ID is", re.I)
class Challenge(SystemExit): pass
def sess():
    global SESSION
    if SESSION is None:
        SESSION = rg.GuardedSession(); SESSION.min_interval = 1.0
    return SESSION
def enc_url(base_url: str, u: str) -> str:
    p = urlsplit(urljoin(base_url, u))
    return p._replace(path=quote(unquote(p.path), safe="/-_.()~!*'"), query=quote(unquote(p.query), safe="=&")).geturl()
def stop_challenge(url, why):
    st = load_state(); st.setdefault("errors", []).append({"unit": "fetch", "url": url, "error": f"HARD STOP: {why}", "at": time.strftime("%F %T %Z")})
    st["hard_stop"] = {"url": url, "why": why, "at": time.strftime("%F %T %Z")}; save_state(st)
    log(f"HARD STOP (challenge / non-official content) at {url}: {why}"); raise Challenge(RC_CHALLENGE)
def strict_robots_ok(host: str) -> bool:
    """Strict pre-check for hosts CoS asked to vet separately (www.amman.jo): plain GET of robots.txt, no TLS fallback,
    no redirects. 403 / challenge / HTML-instead-of-robots / TLS failure / other errors => host skipped for this run."""
    if host in SKIPPED_HOSTS: return False
    import requests
    try:
        r = requests.get(f"https://{host}/robots.txt", headers=UA, timeout=(15, 30), allow_redirects=False)
    except requests.exceptions.SSLError as e:
        SKIPPED_HOSTS[host] = f"TLS failure at robots.txt: {str(e)[:150]}"; return False
    except Exception as e:
        SKIPPED_HOSTS[host] = f"robots.txt error {type(e).__name__}: {str(e)[:150]}"; return False
    t = r.text
    why = ("HTTP 403" if r.status_code == 403 else "challenge markers" if CHALLENGE_RX.search(t[:20000]) else
           "HTML instead of robots rules" if r.status_code == 200 and re.search(r"<\s*(html|!doctype)", t[:800], re.I) else
           f"redirect to {r.headers.get('location')}" if 300 <= r.status_code < 400 else
           f"HTTP {r.status_code}" if r.status_code not in (200, 404, 410) else "")
    if why: SKIPPED_HOSTS[host] = why; return False
    return True
def fetch(url, want="html", data=None, marker=(), timeout=(20, 180)):
    """GET (or the pagination POST-back when data is given) through robots_guard. want='html' -> page must carry the
    publisher marker; want='pdf' -> bytes must start with %PDF. Returns (response, bytes) or None."""
    global ROBOTS_HIT
    host0 = urlsplit(url).hostname or ""
    if host0 not in OFFICIAL_HOSTS: log("not an official host; skipped", url); return None
    if host0 == "www.amman.jo" and not strict_robots_ok(host0): log("www.amman.jo skipped:", SKIPPED_HOSTS.get(host0)); return None
    for attempt in range(3):
        try:
            r = sess().post(url, data=data, headers=UA, timeout=timeout) if data is not None else sess().get(url, headers=UA, timeout=timeout)
        except rg.RobotsBlocked as e:
            rg.log_robots_blocked(e, caller="collect_jo_muni"); log("ROBOTS BLOCKED", url, e); ROBOTS_HIT = True; return None
        except Exception as e:
            log("ERR", url, type(e).__name__, e); time.sleep(5 * (attempt + 1)); continue
        host = urlsplit(r.url).hostname or ""
        if host not in OFFICIAL_HOSTS: stop_challenge(url, f"redirected off the official hosts to {host}")
        body = r.content
        if r.status_code == 404: log("HTTP 404", url); return None
        if r.status_code in (401, 403): stop_challenge(url, f"HTTP {r.status_code} (denied)")
        if r.status_code in (429, 503) or r.status_code >= 500:
            head = body[:4000].decode("utf-8", "replace")
            if CHALLENGE_RX.search(head): stop_challenge(url, f"HTTP {r.status_code} with challenge markers")
            log("HTTP", r.status_code, url, "backing off"); time.sleep(30 * (attempt + 1)); continue
        if r.status_code != 200: log("HTTP", r.status_code, url); return None
        if want == "pdf":
            if body[:5] != b"%PDF-":
                head = body[:4000].decode("utf-8", "replace")
                if CHALLENGE_RX.search(head): stop_challenge(url, "PDF URL returned a challenge page")
                log("not a PDF", url, r.headers.get("content-type")); return None
            return r, body
        txt = body.decode("utf-8", "replace")
        if CHALLENGE_RX.search(txt[:20000]) and not any(m in txt[:8000] for m in marker): stop_challenge(url, "challenge markers in HTML")
        if marker and not any(m in txt for m in marker): stop_challenge(url, "page is not publisher content (marker missing)")
        return r, body
    return None

# ---------------------------------------------------------------- listing (ASP.NET document library, POST-back pager)
ROW_RX = re.compile(r"lvDocumentLibraryView_RowItem_(\d+)\".*?<label>(.*?)</label>.*?lblFileSize_\d+\"[^>]*>(.*?)</span>.*?href='([^']+)'", re.S)
PAGER_RX = re.compile(r"<a class=\"(NumericClass|nextPreviousButtonCSS)\" href=\"javascript:__doPostBack\(&#39;([^&]+?pagerList\$[^&]+?)&#39;,&#39;&#39;\)\">([^<]+)</a>")
CUR_RX = re.compile(r"CurrentPageClass[^>]*>(\d+)<")
OF_RX = re.compile(r"صفحة\s*(\d+)\s*من\s*(\d+)")
def form_fields(t: str) -> dict:
    f = {}
    form = re.search(r"<form[^>]*id=\"ctl01\"[^>]*>(.*)</form>", t, re.S)
    for inp in re.findall(r"<input\b[^>]*>", form.group(1) if form else t):
        typ = (re.search(r'type="([^"]+)"', inp) or [None, "text"])[1].lower()
        nm = re.search(r'name="([^"]+)"', inp)
        if not nm or typ in ("submit", "image", "button", "checkbox", "radio", "file"): continue
        val = re.search(r'value="([^"]*)"', inp)
        f[html.unescape(nm.group(1))] = html.unescape(val.group(1)) if val else ""
    return f
BLOCK_SPLIT = re.compile(r"<(?:li|p|tr|br)\b[^>]*>", re.I)
def list_static_page(src: dict, url: str):
    """Static CMS page: every PDF link inside the main content; title = the link text, or (for 'انقر هنا' style links)
    the visible text of the enclosing block without the click/size boilerplate."""
    res = fetch(url, marker=src["marker"]); items = []
    if res is None: return items, {"url": url, "pages_seen": [], "requests": 1, "rows": 0}
    t = res[1].decode("utf-8", "replace")
    main = t[t.find("ContentDetails"):] if "ContentDetails" in t else t
    main = main[:main.find("MainContent_divGlobalMenu")] if "MainContent_divGlobalMenu" in main else main
    for blk in BLOCK_SPLIT.split(main):
        for href, txt in re.findall(r"<a\b[^>]*href=['\"]([^'\"]+\.pdf)['\"][^>]*>(.*?)</a>", blk, re.S | re.I):
            title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", txt))).strip()
            if len(title) < 8 or title in ("انقر هنا", "هنا", "تحميل"):
                vis = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", blk))).strip()
                vis = re.sub(r"انقر\s*هنا|\(\s*نوع الملف.*?\)|نوع الملف\s*PDF.*$", " ", vis)
                title = re.sub(r"\s+", " ", vis).strip(" -–:")
            items.append({"source": src["code"], "list": src["list"], "host": src["host"], "listing_page": 1, "row": len(items),
                          "title": title, "size_label": "", "href": html.unescape(href), "url": enc_url(f"https://{src['host']}/", html.unescape(href))})
    log(f"{src['code']}/{src['list']} static page: {len(items)} PDF links")
    return items, {"url": url, "pages_seen": [1], "pages_total": 1, "requests": 1, "rows": len(items)}
def list_source(src: dict):
    url = enc_url(f"https://{src['host']}/", src["path"])
    if src.get("page"): return list_static_page(src, url)
    items, pages_seen, total, n_req = [], set(), None, 0
    res = fetch(url, marker=src["marker"]); n_req += 1
    while res is not None:
        base.hard_check("listing")
        t = res[1].decode("utf-8", "replace")
        cur = int(CUR_RX.search(t).group(1)) if CUR_RX.search(t) else 1
        m = OF_RX.search(re.sub(r"<[^>]+>|&nbsp;", " ", t)); total = int(m.group(2)) if m else (total or 1)
        if cur in pages_seen: log(f"{src['code']}/{src['list']}: page {cur} repeated; stop"); break
        pages_seen.add(cur); got = 0
        for idx, label, size, href in ROW_RX.findall(t):
            title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", label))).strip()
            items.append({"source": src["code"], "list": src["list"], "host": src["host"], "listing_page": cur, "row": int(idx),
                          "title": title, "size_label": html.unescape(size).strip(), "href": html.unescape(href),
                          "url": enc_url(f"https://{src['host']}/", html.unescape(href))}); got += 1
        log(f"{src['code']}/{src['list']} page {cur}/{total}: {got} rows")
        if cur >= total: break
        pager = PAGER_RX.findall(t)
        nxt = next((tg for cls, tg, txt in pager if txt.strip() == str(cur + 1)), None) or \
              next((tg for cls, tg, txt in pager if txt.strip() in ("...", "…") and cls == "nextPreviousButtonCSS" and "ctl01" in tg and tg.endswith(tuple(f"ctl{k:02d}" for k in range(6, 12)))), None)
        if not nxt: log(f"{src['code']}/{src['list']}: no pager link to page {cur + 1}; stop"); break
        data = form_fields(t); data["__EVENTTARGET"] = nxt; data["__EVENTARGUMENT"] = ""
        res = fetch(url, data=data, marker=src["marker"]); n_req += 1
    return items, {"url": url, "pages_seen": sorted(pages_seen), "pages_total": total, "requests": n_req, "rows": len(items)}

# ---------------------------------------------------------------- scope (CoS: أنظمة / تعليمات only)
GENERAL_GOV_RX = re.compile(r"المشتريات\s+الحكومية|المشرتيات\s+الحكومية|التنظيم\s+الإداري\s+لوزارة|التنظيم\s+الاداري\s+لوزارة")
def classify(it: dict):
    """(in_scope, kind, reason). GAM's mixed 'التشريعات' list is classified by title; MoLA items by list membership
    (الانظمة -> نظام; التعليمات -> تعليمات only when the title says so), minus central-government rules."""
    t = norm_text(it["title"]); ext = Path(unquote(urlsplit(it["url"]).path)).suffix.lower()
    if ext != ".pdf": return False, "", f"not a PDF ({ext or 'no extension'})"
    if re.match(r"^(?:ال)?دستور|^قانون|^القانون", t) or "الدستور" in t: return False, "", "law / constitution (قوانين out of scope; national-law corpus)"
    if GENERAL_GOV_RX.search(t): return False, "", "central-government rule (procurement / ministry organisation), not a local regulation"
    if re.search(r"الوثيقة\s+القياسية", t): return False, "", "standard bidding document, not a regulation/instruction"
    if re.search(r"(?:^|\s)(?:دليل|الدليل|آلية|الية|أسس|اسس)(?:\s|$)", t) and not re.search(r"نظام|تعليمات", t):
        return False, "", "guide / mechanism / criteria (دليل / آلية / أسس), not a regulation or instruction"
    if re.search(r"تعليمات", t): return True, "talimat", "title: تعليمات"
    if re.search(r"(?:^|\s)(?:ال)?نظام|أنظمة|انظمة", t): return True, "nizam", "title: نظام"
    if it["source"] == "mola" and it["list"] == "الانظمة": return True, "nizam", "listed under MoLA الانظمة (short title)"
    if it["source"] == "mola" and it["list"].startswith("التعليمات") and re.search(r"البلدي|المجالس|الإدارة المحلية|الادارة المحلية", t):
        return True, "talimat", "listed under MoLA التعليمات (municipal subject, title without the word تعليمات)"
    return False, "", "title is not a نظام / تعليمات"

# ---------------------------------------------------------------- PDF -> textcache (JO: garbled text layers are OCRed)
# Many GAM / MoLA gazette PDFs carry a broken text layer: fonts whose glyph->Unicode map is shifted (pdftotext gives
# 'ٗلٖ ػزيهللا' for 'نحن عبدالله'), kashida stretches extracted as letters ('النظاام', 'ه ضضذا', 'مممم'), dropped
# letters, scrambled digits. Such pages are OCRed (tesseract ara) and the OCR text is used when it scores better.
COMMON_AR = set("من في على أو إلى الى التي الذي هذا هذه أن ان عن ما لا مع المادة النظام الأمانة الامانة المجلس وفقا بموجب "
                "يكون أي اي كل ذلك غير بما لها له عند قبل بعد".split())
JUNK_TOK_RX = re.compile(r"اا|([\u0621-\u064a])\1\1|ضض|`")
def text_quality(t: str):
    """(common-word share, kashida/garble-word share, number of words) of one page of text."""
    t = base.repair_ligatures(norm_text(t or "")); toks = re.findall(r"[\u0621-\u064a`]+", t)
    if not toks: return 0.0, 0.0, 0
    return (sum(1 for w in toks if w in COMMON_AR) / len(toks), sum(1 for w in toks if JUNK_TOK_RX.search(w)) / len(toks), len(toks))
def tl_garbled(t: str) -> bool:
    c, j, n = text_quality(t)
    return n >= 15 and (c < 0.13 or j > 0.01)
def q_score(t: str) -> float:
    c, j, n = text_quality(t); return c - 2 * j if n else -1.0
TEXTCACHE_VERSION_JO = 3   # v3: per-page text-layer quality check; garbled pages OCRed ('ocr_reason', 'quality')
def tc_needs_reocr(tc: dict) -> bool:
    return tc.get("textcache_version", 0) < TEXTCACHE_VERSION_JO and any(p.get("ocr") is None and tl_garbled(p["raw"]) for p in tc["pages"])
def jo_extract(item: dict, body: bytes, r, prev: dict | None = None) -> dict:
    from concurrent.futures import ThreadPoolExecutor
    TMP.mkdir(parents=True, exist_ok=True)
    pdf = TMP / f"{item['key']}.pdf"; pdf.write_bytes(body); sha = hashlib.sha256(body).hexdigest()
    try:
        raw = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, timeout=600).stdout.decode("utf-8", "replace").split("\f")
        if raw and not raw[-1].strip(): raw = raw[:-1]
        info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
        m = re.search(r"^Pages:\s+(\d+)", info, re.M); npages = int(m.group(1)) if m else len(raw)
        raw += [""] * (npages - len(raw))
        mu = base.mupdf_pages(pdf, npages)
        pages = [{"raw": raw[i], "mupdf": mu[i][0], "mupdf_sorted": mu[i][1], "ocr": None} for i in range(npages)]
        empty = [i for i in range(npages) if base.no_text_layer(raw[i])]
        garbled = [i for i in range(npages) if i not in empty and tl_garbled(raw[i])]
        same = prev and prev.get("sha256") == sha and len(prev["pages"]) == npages
        todo = []
        for i in empty + garbled:
            pp = prev["pages"][i] if same else {}
            if pp.get("ocr") is not None: pages[i]["ocr"] = pp["ocr"]
            elif pp.get("ocr_candidate") is not None: pages[i]["ocr_candidate"] = pp["ocr_candidate"]
            else: todo.append(i)
        if todo:
            with ThreadPoolExecutor(base.OCR_WORKERS) as ex:
                for i, txt in zip(todo, ex.map(lambda k: base.ocr_page(pdf, k), todo)):
                    if i in empty: pages[i]["ocr"] = txt
                    else: pages[i]["ocr_candidate"] = txt
        for i in empty:
            pages[i]["ocr_reason"] = "no_text_layer"
        for i in garbled:
            cand = pages[i].pop("ocr_candidate", None)
            if cand is None and pages[i]["ocr"] is not None: cand = pages[i]["ocr"]
            qs_tl, qs_ocr = q_score(raw[i]), q_score(cand or "")
            pages[i]["quality"] = {"text_layer": round(qs_tl, 3), "ocr": round(qs_ocr, 3)}
            if cand is not None and qs_ocr > qs_tl: pages[i]["ocr"] = cand; pages[i]["ocr_reason"] = "text_layer_garbled"
            else: pages[i]["ocr"] = None; pages[i]["ocr_candidate"] = cand; pages[i]["ocr_reason"] = "text_layer_kept (OCR scored lower)"
        meta = {k: v.strip() for k, v in re.findall(r"^(Producer|Creator|CreationDate|ModDate|Title):\s*(.*)$", info, re.M)}
        tc = {"textcache_version": TEXTCACHE_VERSION_JO, "key": item["key"], "url": item["url"], "listing": item,
              "sha256": sha, "bytes": len(body), "http_last_modified": r.headers.get("Last-Modified", ""),
              "content_type": r.headers.get("Content-Type", ""), "pdfinfo": meta,
              "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "ocr_engine": "tesseract -l ara --psm 6 @300dpi gray (pages without a text layer, and garbled text-layer pages when OCR scores better)",
              "pages": pages}
        tmp = base.textcache_path(item["key"]).with_suffix(".tmp"); tmp.write_bytes(gzip.compress(json.dumps(tc, ensure_ascii=False).encode(), 6))
        os.replace(tmp, base.textcache_path(item["key"]))
        n_ocr = sum(1 for p in pages if p.get("ocr") is not None)
        log(f"textcache {item['key'][:12]}: pages={npages} no_text={len(empty)} garbled={len(garbled)} ocr_used={n_ocr} ocr_run={len(todo)} pdf={len(body)} {item['title'][:60]}")
        return tc
    finally:
        pdf.unlink(missing_ok=True)

# ---------------------------------------------------------------- parse
JO_FURN_RX = re.compile(r"^(?:\d{1,5}|عدد\s*(?:خاص\s*)?\d{0,5}.*|العدد\s*\d{0,5}.*|.*الجريدة\s+الرسمية.*|صفحة\s*\d+|رقم\s+الصفحة.*|"
                        r"\d{1,2}/\d{1,2}/(?:19|20)\d{2}|(?:19|20)\d{2}/\d{1,2}/\d{1,2})$")
def strip_furniture(t: str, ocr: bool) -> str:
    """Drop Official Gazette running header/footer lines (page number, issue number, 'الجريدة الرسمية', issue date) in the
    first/last 3 non-empty lines of each page."""
    ls = t.split("\n"); idx = [i for i, l in enumerate(ls) if l.strip()]
    drop = set()
    for i in set(idx[:3] + idx[-3:]):
        l = ls[i].strip()
        if (JO_FURN_RX.match(l) and len(l) < 70) or (ocr and base._junk_line(l)): drop.add(i)
    return "\n".join(l for i, l in enumerate(ls) if i not in drop)
def gazette_info(raw: str) -> dict:
    head = raw[:1500]; out = {}
    m = re.search(r"عدد\s*(?:خاص\s*)?(?:رقم\s*)?(\d{3,5})", head) or re.search(r"العدد\s*(?:رقم\s*)?(\d{3,5})", head)
    if m: out["issue"] = int(m.group(1))
    if "الجريدة الرسمية" in head or m:
        out["name"] = "الجريدة الرسمية (Official Gazette of the Hashemite Kingdom of Jordan)"
    # 'وبناء على ما قرره مجلس الوزراء بتاريخ d' = the Council of Ministers' decision enacting the regulation (not the
    # gazette publication date, which these PDFs do not state in a parseable place)
    c = re.search(r"مجل\S*\s+ال\S*زراء\s+بتار\S*", head)
    if c:
        ds = [d for d in base.dates_in(head) if c.start() <= d[0] <= c.end() + 40]
        if ds: out["cabinet_decision_date"] = ds[0][1]
    return out
def clean_text(pages: list):
    parts, raw, src = [], [], []
    for p in pages:
        t, sc = base.page_text(p); raw.append(t); parts.append(base.fix_bidi(strip_furniture(t, sc == "ocr"))); src.append(sc)
    def tidy(xs):
        t = "\n".join(x.strip("\n") for x in xs); t = re.sub(r"\n{3,}", "\n\n", t)
        return "\n".join(l.strip() for l in t.split("\n")).strip()
    return tidy(parts), tidy(raw), src
ORD_JO = base.ORD_RE
JO_ART_RX = re.compile(r"(?m)^[ \t]*(?:ال)?م\s?ـ*[اأ]\s?ـ*د\s?ـ*[ةه]\s*(?:[-–—]\s*)?(?:رقم\s*)?[\(\[]?\s*[-–—]?\s*"
                       r"([0-9\u0660-\u0669]{1,3}|(?:" + ORD_JO + r")(?:\s+عشر[ةه]?)?|[^\s\u0621-\u064a]{0,3})\s*[\)\]]?\s*(?:مكرر[ةه]?)?")
XREF_AFTER_RX = re.compile(r"^\s*[\)\]]?\s*(?:من|و\s*(?:ال)?ماد|أو|او|في|إلى|الى|بموجب)\b")
def split_articles_jo(text: str):
    """Article headings 'المادة -1' / 'المادة (1)' / 'مادة 1:' at a line start. OCR and some broken text layers misread
    the digits, so articles are numbered by position (1..n); the printed label is kept in 'label'. Lines starting with
    'المادة (n) من ...' are cross-references, not headings."""
    hs = []
    for m in JO_ART_RX.finditer(text):
        lab = m.group(1).strip()
        if not lab and not re.match(r"\s*[-–—:.]", text[m.end():m.end() + 3]): continue
        if XREF_AFTER_RX.match(text[m.end():m.end() + 20]): continue
        hs.append((m.start(), m.end(), lab))
    if len(hs) < 2: return []
    pre = text[:hs[0][0]].strip(); arts = []
    for i, (a, b, lab) in enumerate(hs):
        end = hs[i + 1][0] if i + 1 < len(hs) else len(text)
        body = text[a:end].strip()
        arts.append({"number": str(i + 1), "label": lab, "heading": text[a:b].strip(), "text": body})
    if pre and len(pre) > 0: arts[0]["preamble"] = pre
    return arts
def digits_scrambled(t: str) -> bool:
    """Some text layers map Arabic-Indic digit glyphs to the wrong digits ('لسنة 8112'): any 'لسنة NNNN' outside 1900-2030."""
    ys = [int(y) for y in re.findall(r"(?:لسنة|لعام|سنة)\s*\)?\s*(\d{4})(?!\d)", t)]
    return any(not (1900 <= y <= 2030) for y in ys)
ISSUED_CUE = re.compile(r"صدر\S*\s+(?:في|ب)|حرر\S*\s+(?:في|ب)|تاريخ\s+الإصدار|تاريخ\s+الاصدار")
def parse_doc(tc: dict) -> dict:
    it = tc["listing"]; text, rawtext, src = clean_text(tc["pages"])
    rtl_fixed = False
    if base.reversed_rtl_score(text) > 0.6:
        text = "\n".join(l[::-1] for l in text.split("\n")); rawtext = "\n".join(l[::-1] for l in rawtext.split("\n")); rtl_fixed = True
    title = norm_text(it["title"]).strip()
    # number / year from the listing title first ('لسنه' spelling included); the text head only when the title has no
    # year at all (never a cited law such as the 1955 / 1966 planning laws); OCR digits are not trusted for this
    tnorm = re.sub(r"لسنه", "لسنة", title)
    ny = base.NUMYEAR_RX.search(tnorm)
    y4 = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", tnorm)
    if ny: number, year = ny.group(1), ny.group(2)
    elif y4:
        year = y4.group(1); mn = re.search(r"رقم\s*\(?\s*(\d{1,4})\s*\)?", tnorm); number = mn.group(1) if mn else ""
    else:
        tl_head = "\n".join(base.repair_ligatures(norm_text(p.get("raw") or "")) for p in tc["pages"][:2] if not tl_garbled(p.get("raw") or ""))
        ny = next(iter(base.NUMYEAR_RX.finditer(tl_head[:1500])), None)
        number, year = (ny.group(1), ny.group(2)) if ny else ("", "")
    ty = int(year) if year else None
    ok_y = (lambda iso: ty is None or (ty - 2 <= int(iso[:4]) <= ty + 1))
    ds = [d for d in base.dates_in(text) if ok_y(d[1])]; issued = ""
    for m in ISSUED_CUE.finditer(text):
        nxt = [d for d in ds if m.start() <= d[0] <= m.start() + 120]
        if nxt: issued = nxt[0][1]
    # cabinet decision date: from the PDF text layer of page 1 when its digits are plausible (the text layer keeps correct
    # digits on most kashida-garbled pages; OCR misreads Arabic-Indic digits), else from the body text; both must fall in
    # [year - 2, year + 1] of the regulation's year
    gaz = gazette_info(rawtext); cands = []
    for p in tc["pages"][:1]:
        g1 = gazette_info(base.repair_ligatures(norm_text(p.get("raw") or "")))
        if g1.get("cabinet_decision_date"): cands.append(("text_layer_p1", g1["cabinet_decision_date"]))
    if gaz.get("cabinet_decision_date"): cands.append(("body", gaz["cabinet_decision_date"]))
    good = [c for c in cands if ok_y(c[1])]
    gaz.pop("cabinet_decision_date", None)
    if good: gaz["cabinet_decision_date"], gaz["cabinet_decision_date_from"] = good[0][1], good[0][0]
    elif cands: gaz["cabinet_decision_date_rejected"] = [c[1] for c in cands]
    date_basis = "issuance cue (صدر في / حرر في)" if issued else ""
    if not issued and gaz.get("cabinet_decision_date"): issued = gaz["cabinet_decision_date"]; date_basis = "Council of Ministers decision date (وبناء على ما قرره مجلس الوزراء بتاريخ)"
    if not issued and ty:   # cheap fallback: first plausible full date in the page-1 PDF text layer (OCR digits are not used)
        tl1 = base.repair_ligatures(norm_text(tc["pages"][0].get("raw") or "")) if tc["pages"] else ""
        d1 = [d for d in base.dates_in(tl1) if ok_y(d[1])]
        if d1: issued = d1[0][1]; date_basis = "first plausible date in the page-1 PDF text layer (no enactment cue found)"
    n_ocr = src.count("ocr"); n_pages = len(src)
    if not text or n_ar(text) < 20: status = "empty"
    elif n_ocr == 0: status = "text_layer"
    elif n_ocr == n_pages: status = "ocr"
    else: status = "mixed_text_layer_ocr"
    arts = split_articles_jo(text) if status != "empty" else []
    moved = 0
    if arts and arts[0].get("preamble"):   # keep the enacting formula / title block with article 1 (no text lost)
        arts[0]["text"] = arts[0].pop("preamble") + "\n" + arts[0]["text"]
    return {"key": tc["key"], "title": title, "text": text if status != "empty" else title, "number": number, "year": year,
            "date_issued": issued, "date_basis": date_basis, "date_published": "", "dates_found": [d for _, d, _ in ds][:12],
            "text_status": status, "pages": n_pages, "ocr_pages": [i + 1 for i, s in enumerate(src) if s == "ocr"], "articles": arts,
            "rtl_fixed": rtl_fixed, "ligature_swap_ratio": round(base.swap_ratio(text), 3), "gazette": gaz, "heading_order_fixes": moved,
            "amendment": bool(re.search(r"معدل|تعديل", title)), "digits_caveat": n_ocr > 0 or digits_scrambled(text),
            "digits_scrambled_text_layer": digits_scrambled(text) and n_ocr < n_pages,
            "ocr_reasons": dict(collections.Counter(p.get("ocr_reason", "") for p in tc["pages"] if p.get("ocr_reason")))}

# ---------------------------------------------------------------- overlap with the JO national-law corpus (Hub)
def _shingles(t, n=8):
    w = base.norm_name(t).split()
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}
def hub_overlap(docs):
    """For each doc: normalized-title equality and 8-word shingle containment against every Hub JO law text
    (endomorphosis/ipfs_jordan_laws @ HUB_JO_REV, the same 1,229 instruments as $IPFS_DATASETS_LEGAL_CORPORA_ROOT/jo)."""
    import pyarrow.parquet as pq
    if not HUB_JO_LAWS.exists():
        return {"checked": False, "why": f"{HUB_JO_LAWS} missing"}, {}
    # streaming (row groups / batches of 64 Hub laws) so the shingle sets never sit in RAM together (fleet RSS <= 1 GiB)
    dsh = {d["key"]: {hash(x) for x in _shingles(d["text"])} for _, d in docs}
    dtitle = {d["key"]: base.norm_name(d["title"]) for _, d in docs}
    best = {k: ("", 0) for k in dsh}; tmatch = {k: "" for k in dsh}; n = 0
    pf = pq.ParquetFile(HUB_JO_LAWS)
    for b in pf.iter_batches(batch_size=64, columns=["id", "title", "text"]):
        for r in b.to_pylist():
            n += 1; ht = base.norm_name(r["title"] or ""); hs = {hash(x) for x in _shingles(r["text"] or "")}
            for k, s in dsh.items():
                if ht and ht == dtitle[k]: tmatch[k] = r["id"]
                c = len(s & hs) if s else 0
                if c > best[k][1]: best[k] = (r["id"], c)
            del hs
    res = {}
    for k, s in dsh.items():
        cont = best[k][1] / max(1, len(s))
        res[k] = {"title_match": tmatch[k], "best_hub_id": best[k][0], "containment": round(cont, 3), "overlap": bool(tmatch[k]) or cont >= 0.6}
    return {"checked": True, "hub_repo": HUB_JO_REPO, "hub_revision": HUB_JO_REV, "hub_laws": n,
            "method": "normalized title equality OR >= 60% of the document's 8-word shingles found in one Hub law text"}, res

# ---------------------------------------------------------------- Wikidata (GAM QID check)
def fetch_wikidata():
    cache = json.loads(WD_CACHE.read_text()) if WD_CACHE.exists() else {}
    items = cache.setdefault("items", {})
    if GAM_QID in items and "labels" in items[GAM_QID]: return cache
    s = rg.GuardedSession(); s.min_interval = 1.0
    try:
        r = s.get(f"https://www.wikidata.org/wiki/Special:EntityData/{GAM_QID}.json", headers=UA, timeout=(15, 60))
        ent = next(iter(r.json().get("entities", {}).values()))
        items[GAM_QID] = {"labels": {k: v["value"] for k, v in ent.get("labels", {}).items() if k in ("ar", "en")},
                          "p31": [c["mainsnak"].get("datavalue", {}).get("value", {}).get("id") for c in ent.get("claims", {}).get("P31", [])]}
    except Exception as e:
        items[GAM_QID] = {"err": f"{type(e).__name__}: {e}"}
    cache["source"] = "https://www.wikidata.org/wiki/Special:EntityData/<QID>.json (GAM QID from fleet seed seeds/JO.jsonl)"
    cache["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    WD_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0)); return cache

# ---------------------------------------------------------------- rows / batch
LAW_COLS, ART_COLS = base.LAW_COLS, base.ART_COLS
KIND_SLUG = {"nizam": "nizam", "talimat": "talimat"}
def law_id(d, it):
    return f"jo-{it['source']}-{KIND_SLUG[it['kind']]}-{d['year'] or 'nd'}-{hashlib.sha1(it['url'].encode()).hexdigest()[:6]}"
def build_rows(docs):
    wd = (json.loads(WD_CACHE.read_text()) if WD_CACHE.exists() else {}).get("items", {}).get(GAM_QID, {})
    gam_name = wd.get("labels", {}).get("en", "Greater Amman Municipality")
    laws, arts, munis = [], [], {}
    for tc, d in docs:
        it = tc["listing"]; src = SRC_BY_CODE[it["source"]]; lid = law_id(d, it)
        if it["source"] == "gam": mid, mname, qid = f"JO-{GAM_QID}", gam_name, GAM_QID
        else: mid, mname, qid = "JO-national", "Jordan (national rules for all municipalities, Ministry of Local Administration)", ""
        a = d["articles"]; whole = not a
        if whole: a = [{"number": None, "heading": d["title"], "text": d["text"]}]
        ident = f"{d['number']}/{d['year']}" if d["number"] and d["year"] else ""
        kind_ar = "نظام" if it["kind"] == "nizam" else "تعليمات"
        meta = {"listing_title": it["title"], "listing": it["list"], "listing_page": it["listing_page"], "listing_row": it["row"],
                "listing_size_label": it["size_label"], "scope_reason": it["scope_reason"], "instrument_type_ar": kind_ar,
                "doc_key": d["key"], "pdf_sha256": tc["sha256"], "pdf_bytes": tc["bytes"], "pdf_pages": d["pages"], "ocr_pages": d["ocr_pages"],
                "http_last_modified": tc.get("http_last_modified", ""), "pdf_creation_date": tc.get("pdfinfo", {}).get("CreationDate", ""),
                "pdf_producer": tc.get("pdfinfo", {}).get("Producer", ""), "number": d["number"], "year": d["year"],
                "date_issued": d["date_issued"], "date_basis": d["date_basis"], "date_published": d["date_published"], "gazette": d["gazette"], "dates_found": d["dates_found"],
                "amendment": d["amendment"], "ligature_swap_ratio": d["ligature_swap_ratio"], "heading_order_fixes": d["heading_order_fixes"],
                "rtl_order_fixed": d["rtl_fixed"], "publisher": src["pub_short"], "issuing_scope": "Greater Amman Municipality" if it["source"] == "gam" else "national (all municipalities)",
                "collector": "collect_jo_muni.py", "parser_version": PARSER_VERSION, "text_status": d["text_status"], "whole_text_article": whole,
                "hub_overlap": d.get("hub_overlap", {}), "ocr_reasons": d["ocr_reasons"],
                "digits_caveat": ("digits unreliable (OCR misreads Arabic-Indic digits and/or the PDF text layer maps digit glyphs wrongly): "
                                  "amounts, dates and article numbers must be checked against the PDF" if d["digits_caveat"] else "")}
        laws.append({"id": lid, "title": d["title"], "text": d["text"], "source_url": tc["url"], "source_type": SOURCE_TYPE[it["source"]],
                     "jurisdiction": f"JO/{mid}", "country": "JO", "language": "ar", "eli": None,
                     "date": d["date_published"] or d["date_issued"] or "", "date_issued": d["date_issued"], "retrieved_at": tc["retrieved_at"],
                     "license": LICENSE.format(pub=src["pub"], pub_short=src["pub_short"]), "law_status": "published",
                     "identifier": f"{it['source'].upper()} {kind_ar} {d['key'][:10]}", "official_identifier": ident,
                     "article_count": len(a), "json_path": f"textcache/{d['key']}.json.gz", "metadata_json": json.dumps(meta, ensure_ascii=False),
                     "municipality_id": mid, "municipality_name": mname, "wikidata_qid": qid})
        for j, art in enumerate(a, 1):
            arts.append({"law_id": lid, "id": f"{lid}-a{j:03d}", "title": art["heading"], "text": art["text"], "source_url": tc["url"],
                         "document_number": ident, "article_number": art["number"], "record_type": "whole_text" if whole else "article",
                         "metadata_json": json.dumps({"pdf_pages": d["pages"], "whole_text": whole, "text_status": d["text_status"],
                                                      "printed_label": art.get("label", ""), "article_numbering": "by position (1..n)"}, ensure_ascii=False),
                         "municipality_id": mid, "municipality_name": mname, "wikidata_qid": qid})
        mm = munis.setdefault(mid, {"name": mname, "qid": qid, "wikidata_label_ar": wd.get("labels", {}).get("ar", "") if qid else "",
                                    "note": "GAM QID from fleet seed seeds/JO.jsonl, labels checked via Wikidata EntityData" if qid else
                                            "national MoLA rules: municipality_id 'JO-national', no QID (not a single municipality)", "laws": 0})
        mm["laws"] += 1
    return laws, arts, munis
def qa(laws, arts):
    q = base.qa(laws, arts)
    meta = [json.loads(r["metadata_json"]) for r in laws]
    q.pop("laws_without_municipality", None)
    q["ocr_pages_total"] = sum(len(m["ocr_pages"]) for m in meta); q["pdf_pages_total"] = sum(m["pdf_pages"] for m in meta)
    q["by_source"] = dict(collections.Counter(r["source_type"] for r in laws))
    q["laws_with_digits_caveat"] = sum(1 for m in meta if m["digits_caveat"])
    q["ocr_pages_by_reason"] = dict(sum((collections.Counter(m["ocr_reasons"]) for m in meta), collections.Counter()))
    q["by_instrument_type"] = dict(collections.Counter(m["instrument_type_ar"] for m in meta))
    q["laws_without_qid_note"] = "MoLA national rules carry municipality_id 'JO-national' and no QID by design"
    return q
SCAN_RX = base.SCAN_RX
BUNDLE = [("collect_jo_muni.py", "collect_jo_muni.py"), ("collect_ps_molg.py", "collect_ps_molg.py"), ("robots_guard.py", "robots_guard.py"),
          ("run_jo_muni.sh", "run_jo_muni.sh"), ("README_jo_muni.md", "README.md")]
def stage_code_bundle(root: Path, unit: str):
    sd = root / "scrapers"
    if sd.exists(): shutil.rmtree(sd)
    (sd / "seeds").mkdir(parents=True); (root / "manifests").mkdir(parents=True, exist_ok=True)
    scrubbed = []
    def put(src: Path, rel: str):
        dst = sd / rel; txt = src.read_text("utf-8"); new = txt
        for rx, sub in base._SCRUB: new = rx.sub(sub, new)
        if new != txt: scrubbed.append(rel)
        dst.write_text(new, "utf-8"); shutil.copymode(src, dst)
    for name, rel in BUNDLE: put(SCRIPT_DIR / name, rel)
    req = base.requirements_txt().replace("pyarrow, pymupdf (OCR page rendering)", "pyarrow, pymupdf (OCR page rendering; collect_ps_molg helpers)")
    (sd / "requirements.txt").write_text(req)
    put(SEED, "seeds/JO.jsonl"); put(WD_CACHE, "seeds/jo_wikidata_labels.json")
    if LISTING.exists(): put(LISTING, "seeds/listing.json")
    files = {str(p.relative_to(root)): base.sha_file(p) for p in sorted(sd.rglob("*")) if p.is_file()}
    scan = base.scan_dir(sd)
    man = {"unit": unit, "files": files, "parser_version": PARSER_VERSION, "sensitive_word_scan": scan, "scrubbed_files": scrubbed,
           "python": sys.version.split()[0],
           "seed_sources": {"seeds/JO.jsonl": "fleet municipal seeds seeds/mena/JO.jsonl (GAM QID Q8959166)",
                            "seeds/jo_wikidata_labels.json": "Wikidata EntityData labels for the GAM QID",
                            "seeds/listing.json": "snapshot of the 3 listings with scope decisions (input of the fetch step)"},
           "created": time.strftime("%Y-%m-%d %H:%M:%S %Z")}
    (root / "manifests" / f"{unit}_code.json").write_text(json.dumps(man, ensure_ascii=False, indent=1))
    log(f"code bundle staged in {sd}: {len(files)} files, scan {'clean' if scan['clean'] else 'HITS ' + str(scan['hit_count'])}")
    return man
def write_batch(bno: int, docs: list, notes: dict):
    import pyarrow as pa, pyarrow.parquet as pq
    final = BATCHES / f"batch_{bno:03d}"; marker = STAGE / f"HUB_READY_batch_{bno:03d}"
    marker.unlink(missing_ok=True)
    bdir = BATCHES / f".batch_{bno:03d}.new"
    if bdir.exists(): shutil.rmtree(bdir)
    (bdir / "data").mkdir(parents=True); (bdir / "manifests").mkdir(parents=True)
    laws, arts, munis = build_rows(docs)
    q = qa(laws, arts)
    lt = pa.Table.from_pylist([{k: r[k] for k in LAW_COLS} for r in laws],
                              schema=pa.schema([(k, pa.int64() if k == "article_count" else pa.large_string()) for k in LAW_COLS]))
    at = pa.Table.from_pylist([{k: r[k] for k in ART_COLS} for r in arts], schema=pa.schema([(k, pa.large_string()) for k in ART_COLS]))
    lp, ap = bdir / "data" / f"laws-{bno:05d}.parquet", bdir / "data" / f"articles-{bno:05d}.parquet"
    pq.write_table(lt, lp, compression="zstd"); pq.write_table(at, ap, compression="zstd")
    man = {"batch": bno, "target_repo": HUB_REPO, "country": "JO", "hub_parent_revision": "none (new repository; CoS creates it at upload)",
           "sources": [f"https://{s['host']}{s['path']} ({s['pub_short']})" for s in SOURCES],
           "not_used": "MoLA القوانين page (laws; out of scope per CoS 16:12)",
           "documents_in_batch": len(laws), "laws_rows": lt.num_rows, "articles_rows": at.num_rows,
           "municipalities": munis, "files": {f"data/{p.name}": {"bytes": p.stat().st_size, "sha256": base.sha_file(p)} for p in (lp, ap)},
           "created": time.strftime("%Y-%m-%d %H:%M %Z"), "parser_version": PARSER_VERSION,
           "license_note": "Per-row license field: official Arabic text, attribution to GAM / MoLA; Jordanian copyright law excludes official laws and regulations.",
           "id_scheme": "jo-<gam|mola>-<nizam|talimat>-<year|nd>-<first 6 hex of sha1(source PDF URL)>; articles <law_id>-aNNN",
           "municipality_rule": "GAM items: municipality_id JO-Q8959166 / wikidata_qid Q8959166; MoLA items: municipality_id 'JO-national', no QID",
           "caveats": {
               "ocr": "Most GAM / MoLA gazette PDFs have a garbled text layer (shifted glyph->Unicode font maps, kashida extracted as letters, dropped letters). Every page failing a common-word/garble score was OCRed (tesseract ara, 300 dpi); the OCR text is used when it scores better (qa.ocr_pages_by_reason). OCR letters are good; it is still OCR.",
               "digits_caveat": "qa.laws_with_digits_caveat counts laws whose body digits are unreliable: tesseract ara misreads Arabic-Indic digits, and the remaining text-layer pages of several PDFs map digit glyphs to wrong digits (e.g. 'لسنة 8112'). Amounts, dates and article numbers inside the text must be checked against the PDF (source_url). Per row: metadata_json.digits_caveat.",
               "identifiers": "official_identifier (number/year) comes from the publisher's listing title, not from the OCR text.",
               "dates": "date = Council of Ministers decision date from the page-1 text layer (or another plausible page-1 text-layer date, see metadata_json.date_basis), accepted only within [year-2, year+1]; left empty when no trustworthy digits exist (qa.laws_without_any_date). The year is in metadata_json.year.",
               "articles": "article_number is the position (1..n) because printed digits are unreliable; the printed label is in the article metadata_json.printed_label. Amending regulations can yield a row for a quoted replacement article."},
           "qa": q, **notes}
    (bdir / "manifests" / f"batch{bno}_municipalities.json").write_text(json.dumps(munis, ensure_ascii=False, indent=1))
    (bdir / "manifests" / f"batch{bno}_MANIFEST.json").write_text(json.dumps(man, ensure_ascii=False, indent=1))
    code_man = stage_code_bundle(bdir, f"batch{bno}")
    pack_scan = base.scan_dir(bdir)
    if final.exists(): shutil.rmtree(final)
    os.replace(bdir, final)
    man.update(staged_dir=str(final), code_manifest=f"manifests/batch{bno}_code.json", sensitive_word_scan=pack_scan,
               pack_files={str(p.relative_to(final)): base.sha_file(p) for p in sorted(final.rglob("*")) if p.is_file()})
    bad = q["duplicate_text_groups"] or q["zero_article_laws"] or q["orphan_articles"] or q["duplicate_law_ids"] or q["duplicate_article_ids"] or q["article_count_mismatch"]
    if bad or not (code_man["sensitive_word_scan"]["clean"] and pack_scan["clean"]):
        log(f"BATCH {bno:03d} staged but QA/scan NOT clean; no HUB_READY marker")
        (STAGE / f"HELD_qa_batch_{bno:03d}").write_text(json.dumps(man, ensure_ascii=False, indent=1)); return man, False
    marker.write_text(json.dumps(man, ensure_ascii=False, indent=1))
    log(f"BATCH {bno:03d} HUB-READY: laws={man['laws_rows']} articles={man['articles_rows']} -> {final}")
    return man, True

# ---------------------------------------------------------------- main
START = time.time()
DONE = STAGE / "DONE"
MAX_HOLD_S = int(os.environ.get("MAX_HOLD_S", str(3 * 3600)))
def doc_key(it): return hashlib.sha1(it["url"].encode()).hexdigest()[:32]
def build_and_stage(st, listing):
    inscope = [it for it in listing["items"] if it["in_scope"]]
    docs, seen_sha, dup_pdf, seen_text, dup_text = [], {}, [], {}, []
    content_law, kind_fix = [], []
    for it in inscope:
        tc = base.load_textcache(it["key"])
        if tc is None: continue
        if tc["sha256"] in seen_sha: dup_pdf.append({"key": it["key"], "title": it["title"], "same_pdf_as": seen_sha[tc["sha256"]]}); continue
        seen_sha[tc["sha256"]] = it["key"]; tc["listing"] = it
        d = parse_doc(tc); tk = hashlib.sha256(re.sub(r"\s+", " ", d["text"]).strip().encode()).hexdigest()
        if tk in seen_text:   # same regulation listed twice with different PDF bytes (re-saved file)
            dup_text.append({"key": it["key"], "title": it["title"], "url": tc["url"], "pdf_sha256": tc["sha256"],
                             "same_text_as": seen_text[tk]}); continue
        seen_text[tk] = {"key": it["key"], "title": it["title"], "url": tc["url"]}
        head = re.sub(r"[\u0640]", "", d["text"][:1500])
        if re.search(r"يسمى\s+هذا\s+القانون|يسمى\s+القانون|قانون\s+معدل\s+لقانون", head[:900]) and not re.search(r"يسمى\s+هذا\s+النظام|تسمى\s+هذه\s+التعليمات", head):
            content_law.append({"key": it["key"], "title": it["title"], "url": tc["url"],
                                "reason": "the document is a law (يسمى هذا القانون), listed under MoLA الانظمة; قوانين are out of scope"}); continue
        k2 = "talimat" if re.search(r"تسمى\s+هذه\s+التعليمات", head) else "nizam" if re.search(r"يسمى\s+هذا\s+النظام", head) else it["kind"]
        if k2 != it["kind"]:
            kind_fix.append({"key": it["key"], "title": it["title"], "listed_kind": it["kind"], "content_kind": k2}); tc["listing"] = dict(it, kind=k2)
        docs.append((tc, d))
    ov_meta, ov = hub_overlap(docs)
    excluded_overlap = []
    keep = []
    for tc, d in docs:
        d["hub_overlap"] = ov.get(d["key"], {})
        if d["hub_overlap"].get("overlap"):
            excluded_overlap.append({"title": d["title"], "url": tc["url"], **d["hub_overlap"]}); continue
        keep.append((tc, d))
    missing = [{"key": it["key"], "title": it["title"], "url": it["url"]} for it in inscope if base.load_textcache(it["key"]) is None]
    notes = {"listing": listing["summary"], "items_listed": len(listing["items"]), "items_in_scope": len(inscope),
             "excluded_out_of_scope": [{"source": it["source"], "list": it["list"], "title": it["title"], "reason": it["scope_reason"]}
                                       for it in listing["items"] if not it["in_scope"]],
             "excluded_duplicate_pdf": dup_pdf, "excluded_duplicate_text": dup_text, "excluded_content_is_law": content_law, "instrument_type_from_content": kind_fix, "hub_overlap_check": ov_meta, "excluded_hub_overlap": excluded_overlap,
             "documents_missing_text": missing, "skipped_hosts": listing.get("skipped_hosts", {}),
             "robots": listing.get("robots_notes", ""),
             "known_gaps": [{"list": "MoLA التعليمات (https://www.mola.gov.jo/Ar/List/التعليمات)",
                             "issue": "the document library prints 'صفحة 1 من 2' but renders no pager control; only page 1 (10 rows) was read. "
                                      "The static page /AR/Pages/التعليمات has no PDF links.",
                             "repair_attempt": "2026-10-04 17:58 PT short lane: GET page 1, then one POST-back with the sibling library's page-2 "
                                               "target (pagerList$ctl01$ctl01); the response was HTTP 200 without the ministry's name and without "
                                               "challenge markers, which is the hard-stop rule (rc 7), so it was not retried. Page 2's content is unknown.",
                             "status": "open; needs a CoS decision (e.g. retry with another method, or accept the gap)"}]}
    man, ok = write_batch(1, keep, notes)
    st["batches"]["001"] = {"laws": man["laws_rows"], "articles": man["articles_rows"], "files": man["files"],
                            "status": "hub_ready_held" if ok else "qa_failed", "created": man["created"]}
    save_state(st)
    return ok
AMMAN_JO_CHECK = Path(os.environ.get("JO_AMMAN_CHECK", (str(_LEGAL_WS) + "/muni/jo_dev/amman_jo_robots.json")))
def robots_notes():
    """robots.txt status per host from robots_guard's persisted snapshots (written on every successful robots read)."""
    out = {}
    for h in ("media.ammancity.gov.jo", "www.mola.gov.jo", "www.wikidata.org"):
        snap = rg.load_persisted_snapshot(h)
        if not snap: out[h] = "(no robots snapshot)"; continue
        out[h] = {"robots_url": snap.get("robots_url"), "fetched_at_utc": snap.get("fetched_at"), "status": snap.get("status"),
                  "http_status": snap.get("http_status"), "sha256": snap.get("sha256"),
                  "meaning": "no robots.txt (404) => no restrictions" if snap.get("status") == "missing" else "rules parsed and enforced by robots_guard"}
    chk = json.loads(AMMAN_JO_CHECK.read_text()).get("www.amman.jo", {}) if AMMAN_JO_CHECK.exists() else {}
    out["www.amman.jo"] = {"strict_precheck_2026-10-04_PT": {k: chk.get(k) for k in ("status", "ct", "server", "location", "text")},
                           "result": "HTTP 404 plain '404 not found', no redirect, no challenge, no WAF => no robots rules (allowed)",
                           "used": "no request beyond robots.txt: no listed document points to www.amman.jo (GAM PDFs are on media.ammancity.gov.jo)"}
    return out
def main():
    for d in (TEXTCACHE, TMP, BATCHES): d.mkdir(parents=True, exist_ok=True)
    for p in TMP.glob("*"): p.unlink()
    st = load_state()
    if st.get("done") or DONE.exists(): log("state says done; nothing to do"); return RC_DONE
    log(f"collect_jo_muni slice start pid {os.getpid()} max_hold={MAX_HOLD_S}s")
    base.start_gate()
    from threading import Thread
    Thread(target=base.monitor, daemon=True, name="fleet-monitor").start()
    wd = Thread(target=fetch_wikidata, daemon=True, name="wikidata"); wd.start()
    items, summ = [], {}
    for src in SOURCES:
        its, s = list_source(src); items += its; summ[f"{src['code']}:{src['list']}"] = s
        if ROBOTS_HIT: return RC_STOP
    seen = set(); uniq = []
    for it in items:
        it["key"] = doc_key(it)
        if it["key"] in seen: it["in_scope"], it["kind"], it["scope_reason"] = False, "", "duplicate listing entry (same URL)"
        else:
            seen.add(it["key"]); ok, kind, why = classify(it); it["in_scope"], it["kind"], it["scope_reason"] = ok, kind, why
        uniq.append(it)
    listing = {"items": uniq, "summary": summ, "listed_at": time.strftime("%F %T %Z")}
    LISTING.write_text(json.dumps(listing, ensure_ascii=False, indent=0))
    log(f"listed {len(uniq)} rows; in scope {sum(1 for i in uniq if i['in_scope'])}")
    st["listed"] = len(uniq); st["in_scope"] = sum(1 for i in uniq if i["in_scope"]); save_state(st)
    for it in uniq:
        if not it["in_scope"]: continue
        if time.time() - START > MAX_HOLD_S: log("slice time limit; requeue"); save_state(st); return RC_SLICE
        tc0 = base.load_textcache(it["key"])
        if tc0 is not None and not tc_needs_reocr(tc0): continue
        base.hard_check("fetch")
        res = fetch(it["url"], want="pdf")
        if res is None:
            st["failed"][it["key"]] = {"url": it["url"], "title": it["title"], "why": "robots_blocked" if ROBOTS_HIT else "download_failed"}
            save_state(st)
            if ROBOTS_HIT: return RC_STOP
            continue
        r, body = res
        item = dict(it, position=0)
        tc = jo_extract(item, body, r, prev=tc0)
        if tc0 is not None and tc0.get("sha256") != tc["sha256"]: log(f"note: PDF bytes changed since first fetch: {it['url']}")
        st["fetched"][it["key"]] = {"sha256": tc["sha256"], "pages": len(tc["pages"]), "at": time.strftime("%F %T %Z")}
        st["failed"].pop(it["key"], None); save_state(st)
    wd.join(timeout=120)
    listing["skipped_hosts"] = SKIPPED_HOSTS; listing["robots_notes"] = robots_notes()
    LISTING.write_text(json.dumps(listing, ensure_ascii=False, indent=0))
    build_and_stage(st, listing)
    st["fetch_complete"] = not st["failed"]; save_state(st)
    return RC_SLICE
def build_offline():
    listing = json.loads(LISTING.read_text()); st = load_state()
    listing["robots_notes"] = robots_notes()
    return 0 if build_and_stage(st, listing) else 2
def run():
    try:
        return main()
    except base.HardStop as e:
        st = load_state()
        if e.code == base.RC_PAUSE:
            st.setdefault("pauses", []).append({"slot": base.SLOT_NAME, "why": base.STOP_REQ["why"], "at": time.strftime("%F %T %Z")}); save_state(st); return base.RC_PAUSE
        st.setdefault("errors", []).append({"unit": "slice", "error": f"hard_stop rc={e.code} {base.STOP_REQ['why']}".strip(), "at": time.strftime("%F %T %Z")})
        save_state(st); return e.code
    except Challenge:
        return RC_CHALLENGE

if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--build-offline":
        sys.exit(build_offline())
    sys.exit(run())
