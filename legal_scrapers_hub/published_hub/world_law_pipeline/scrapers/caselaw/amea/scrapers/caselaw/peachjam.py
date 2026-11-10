#!/usr/bin/env python3
"""Peachjam (AfricanLII) judgment scraper -> world_caselaw schema v1.0 jsonl.
Live mode (sites without bot challenge) or --wayback mode (Wayback CDX + id_ snapshots).
Resumable: state/<src>_done.txt holds fetched canonical URLs. 1 connection, polite delay."""
import argparse, json, os, re, subprocess, sys, time, html as H, datetime, urllib.parse, shutil
import requests
UA = "world_caselaw-bot/0.1 (legal research dataset; contact via huggingface.co/endomorphosis)"
BASE = "/workspace/world_caselaw"; AMEA = BASE + "/amea"
S = requests.Session(); S.headers["User-Agent"] = UA

def log(*a): print(datetime.datetime.now().isoformat(timespec="seconds"), *a, flush=True)

def get(url, delay, tries=4):
    for i in range(tries):
        time.sleep(delay)
        try:
            r = S.get(url, timeout=60)
            if r.status_code == 200: return r
            if r.status_code in (404, 410): return None
            log("HTTP", r.status_code, url)
        except Exception as e: log("ERR", e, url)
        time.sleep(delay * (2 ** i))
    return None

def footprint():
    import glob
    tot = 0
    for root, _, fs in os.walk(AMEA):
        for f in fs:
            try: tot += os.path.getsize(os.path.join(root, f))
            except OSError: pass
    for f in glob.glob(BASE + "/data/*/amea-*"):
        try: tot += os.path.getsize(f)
        except OSError: pass
    return tot

def wait_for_space(cap=2e9):
    while shutil.disk_usage("/workspace").free < 20e9 or footprint() > cap:
        log(f"pause: free={shutil.disk_usage('/workspace').free/1e9:.1f}GB footprint={footprint()/1e9:.2f}GB (cap 2GB); waiting for upload"); time.sleep(300)

def disk_ok():
    wait_for_space(); return
    free = shutil.disk_usage("/workspace").free / 1e9
    while free < 20:
        log(f"disk low {free:.1f}GB, pausing"); time.sleep(600)
        free = shutil.disk_usage("/workspace").free / 1e9

def clean(s): return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s))).strip()

def meta(h):
    d = {}
    for m in re.finditer(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", h, re.S):
        k = clean(m.group(1)); v = m.group(2)
        if k == "Judges": d[k] = [clean(x) for x in re.findall(r"<a[^>]*>(.*?)</a>", v, re.S)] or [clean(x) for x in clean(v).split(",")]
        else: d.setdefault(k, clean(re.sub(r"<(script|button)[^>]*>.*?</\1>", "", v, flags=re.S)).split("  ")[0].strip())
    return d

def body_text(h):
    m = re.search(r'<div[^>]*class="[^"]*content-and-enrichments__inner[^"]*"[^>]*>(.*)', h, re.S) or re.search(r'<div[^>]*class="document-content__inner[^"]*"[^>]*>(.*)', h, re.S)
    if not m: return None
    t = m.group(1)
    t = re.split(r'<div[^>]*class="[^"]*(?:document-content__offcanvas|modal)', t)[0]
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", t, flags=re.S)
    t = re.sub(r"</(p|div|h\d|li|tr|br)>|<br\s*/?>", "\n", t)
    t = H.unescape(re.sub(r"<[^>]+>", "", t))
    t = "\n".join(l.strip() for l in t.splitlines() if l.strip())
    return t if len(t) > 200 else None

def pdf_text(url, delay):
    r = get(url, delay)
    if not r or not r.content.startswith(b"%PDF"): return None
    p = subprocess.run(["pdftotext", "-layout", "-", "-"], input=r.content, capture_output=True)
    t = p.stdout.decode("utf8", "replace").strip()
    if not t:  # scanned PDF: record URL for a later OCR pass (PDFs not kept locally; 2 GB cap)
        with open(AMEA + "/state/ocr_todo.tsv", "a") as f: f.write(f"{len(r.content)}\t{url}\n")
    return t or None

class CourtMap:
    def __init__(self, cc):
        self.rows = []
        p = f"/workspace/world_courts/data/{cc}/{cc}_courthouses.jsonl"
        if os.path.exists(p):
            self.rows = [json.loads(l) for l in open(p) if l.strip()]
        self.missing = {}
    def lookup(self, name, cc, src_url):
        n = (name or "").lower()
        bodies = [r for r in self.rows if r.get("record_type") == "court_body"]
        for r in bodies:
            if r["name"].lower() == n: return r["court_id"]
        rules = [("supreme", "supreme"), ("appeal", "appeal"), ("high court", "high"), ("magistrat", "lower"), ("district", "lower"), ("constitutional", "constitutional"), ("industrial", "industrial"), ("labour", "labour")]
        for kw, key in rules:
            if kw in n:
                for r in bodies:
                    if key in r["court_id"]: return r["court_id"]
        if name and name not in self.missing:
            self.missing[name] = {"name": name, "country": cc, "official_url": src_url}
        return None
    def dump_missing(self):
        p = AMEA + "/missing_courts.jsonl"
        have = set()
        if os.path.exists(p): have = {(j["name"], j["country"]) for j in map(json.loads, open(p))}
        with open(p, "a") as f:
            for v in self.missing.values():
                if (v["name"], v["country"]) not in have: f.write(json.dumps(v) + "\n")

def canon_url_host(u): return u

def parse_date(s):
    try: return datetime.datetime.strptime(s, "%d %B %Y").date().isoformat()
    except Exception: return None

def build_row(url, h, cc, src, cmap, policy, license_, delay, fetch_url):
    m = meta(h)
    title = (re.findall(r"<title>(.*?)</title>", h, re.S) or [""])[0]
    title = clean(title).rsplit(" – ", 1)[0]
    text = body_text(h)
    if text and "Loading PDF" in text[:300]: text = None
    pl = re.findall(r'href="(/akn/[^"]*/source\.pdf)"', h)
    if not text and pl:
        host = re.match(r"https://[^/]+", canon_url_host(url)).group(0)
        purl = host + pl[0]
        if "web.archive.org" in fetch_url: purl = "https://web.archive.org/web/2026id_/" + purl
        text = pdf_text(purl, delay)
    court = m.get("Court")
    parties = None
    pm = re.match(r"(.+?) \(", title)
    if pm and " v " in pm.group(1): parties = [p.strip() for p in pm.group(1).split(" v ", 1)]
    return {
        "id": f"{src}:{url.split('/akn/')[-1]}", "court": court, "court_id": cmap.lookup(court, cc, url.split('/akn/')[0]),
        "jurisdiction_cc": cc, "place_id": None, "decision_date": parse_date(m.get("Judgment date", "")),
        "case_number": m.get("Case number"), "parties": parties, "judges": m.get("Judges"),
        "citation": m.get("Media Neutral Citation") or m.get("Citation"), "text": text, "source_url": fetch_url,
        "license": license_, "site_policy": policy, "language": (m.get("Language") or "").lower()[:2] or None,
        "title": title, "source": src, "retrieved_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "x_akn_frbr_uri": "/akn/" + url.split("/akn/")[-1], "x_text_status": "ok" if text else "no-text-on-source",
    }

def live_urls(site, delay):
    r = get(f"https://{site}/judgments/", delay)
    courts = sorted(set(re.findall(r'href="/judgments/([A-Za-z]+)/"', r.text))) if r else []
    courts = [c for c in courts if c not in ("all", "courts")]
    for c in courts:
        page = 1; seen = set()
        while True:
            r = get(f"https://{site}/judgments/{c}/?page={page}", delay)
            if not r: break
            links = [l for l in dict.fromkeys(re.findall(r'href="(/akn/[^"#?]*judgment/[^"#?]+)"', r.text)) if l not in seen]
            if not links: break
            seen.update(links)
            for l in links: yield f"https://{site}{l}", f"https://{site}{l}"
            page += 1

def wayback_urls(site, delay):
    cache = f"{AMEA}/state/cdx_{site}.tsv"
    if not os.path.exists(cache):
        base = f"https://web.archive.org/cdx/search/cdx?url={site}/akn/&matchType=prefix&filter=statuscode:200&collapse=urlkey&fl=original,timestamp"
        r = None
        for _w in range(24):
            r = get(base.split("&filter")[0] + "&showNumPages=true", delay)
            if r is not None and r.text.strip().isdigit(): break
            log("cdx unavailable, waiting 10 min"); time.sleep(600)
        if r is None or not r.text.strip().isdigit(): raise SystemExit("CDX unavailable")
        pages = int(r.text.strip()) if r and r.text.strip().isdigit() else 1
        lines = []
        for pg in range(pages):
            r = None
            for _w in range(24):
                r = get(f"{base}&page={pg}", max(delay, 3))
                if r is not None: break
                log("cdx unavailable, waiting 10 min"); time.sleep(600)
            if r is None: log("cdx page failed", pg); continue
            lines += [l for l in r.text.splitlines() if "/judgment/" in l]
            log("cdx page", pg + 1, "/", pages, len(lines))
        open(cache + ".tmp", "w").write("\n".join(lines)); os.replace(cache + ".tmp", cache)
    for l in open(cache):
        parts = l.split()
        if len(parts) != 2: continue
        orig, ts = parts
        u = orig.split("?")[0].split("#")[0]
        if "/judgment/" not in u or re.search(r"/(source|source\.pdf|media/.*)$", u): continue
        u = re.sub(r"^http://", "https://", u).replace(":80/", "/")
        yield u, f"https://web.archive.org/web/{ts}id_/{orig}"

def next_part(src, d):
    import glob
    pf = f"/workspace/world_caselaw/amea/state/{src}_part.txt"
    n = int(open(pf).read()) if os.path.exists(pf) else 0
    loc = [int(re.search(r"_part(\d+)", f).group(1)) + 1 for f in glob.glob(f"{d}/{src}_part*.jsonl")]
    return max([n] + loc)

def save_part(src, n):
    open(f"/workspace/world_caselaw/amea/state/{src}_part.txt", "w").write(str(n))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True); ap.add_argument("--cc", required=True); ap.add_argument("--src", required=True)
    ap.add_argument("--delay", type=float, default=5); ap.add_argument("--wayback", action="store_true")
    ap.add_argument("--policy", default="robots-allowed;ai-train=no;search=yes;ai-input=no")
    ap.add_argument("--license", default="unknown"); ap.add_argument("--shard-rows", type=int, default=500); ap.add_argument("--max", type=int, default=0)
    a = ap.parse_args()
    if a.wayback: a.policy += ";archive-used"
    os.makedirs(f"{BASE}/data/{a.cc}", exist_ok=True)
    statef = f"{AMEA}/state/{a.src}_done.txt"
    done = set(open(statef).read().split()) if os.path.exists(statef) else set()
    part = next_part(a.src, f"{BASE}/data/{a.cc}")
    cmap = CourtMap(a.cc); buf = []; n = 0
    def flush():
        nonlocal buf, part
        if not buf: return
        p = f"{BASE}/data/{a.cc}/{a.src}_part{part:04d}.jsonl"
        with open(p + ".tmp", "w") as f:
            for r in buf: f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.rename(p + ".tmp", p)
        with open(statef, "a") as f: f.write("\n".join(r["x_akn_frbr_uri"] for r in buf) + "\n")
        done.update(r["x_akn_frbr_uri"] for r in buf)
        log("wrote", p, len(buf)); part += 1; save_part(a.src, part); buf = []; cmap.dump_missing()
    gen = wayback_urls(a.site, a.delay) if a.wayback else live_urls(a.site, a.delay)
    seen = set()
    for canon, fetch in gen:
        key = "/akn/" + canon.split("/akn/")[-1]
        if key in done or key in seen: continue
        seen.add(key); disk_ok()
        r = get(fetch, a.delay)
        if not r: continue
        try:
            row = build_row(canon, r.text, a.cc, a.src, cmap, a.policy, a.license, a.delay, fetch)
        except Exception as e: log("parse fail", canon, e); continue
        buf.append(row); n += 1
        if n % 25 == 0: log('progress', n, canon)
        if len(buf) >= a.shard_rows: flush()
        if a.max and n >= a.max: break
    flush(); log("finished", n)

if __name__ == "__main__": main()
