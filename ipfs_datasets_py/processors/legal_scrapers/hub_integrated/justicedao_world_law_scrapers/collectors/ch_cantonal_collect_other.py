#!/usr/bin/env python3
"""Collect cantonal law texts from official canton-hosted non-LexWork portals (VD, TI, GE, ZH, JU).
Single process; one worker thread per canton; one request at a time per host, >= DELAY s between requests.
Stops a host after 3 consecutive 403 (BLOCKED_SOURCE). Backs off on 429/5xx (3 retries). Resumable.
Memory guard: stops when MemAvailable <= 3.5 GiB."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import gzip, json, os, re, signal, sys, threading, time, html as H, urllib.parse
from pathlib import Path
import requests
BASE = _CORPORA / "ch_cantonal"
DELAY = float(os.environ.get("CH_DELAY", "1.5"))
MEM_STOP_KB = int(3.5 * 1024 * 1024)
UA = "python-requests (research collection of official cantonal law texts; polite, 1 request at a time per host)"
STOP = False
def _sig(*_):
    global STOP; STOP = True
signal.signal(signal.SIGTERM, _sig)
def mem_kb():
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable"): return int(ln.split()[1])
ST = {}; LOCK = threading.Lock()
class Blocked(Exception): pass
class Fetcher:
    def __init__(self, c):
        self.c = c; self.s = requests.Session(); self.s.headers["User-Agent"] = UA
        self.c403 = {}; self.last = {}
        ST[c] = {"ok": 0, "err": 0, "req": 0, "blocked_hosts": [], "failed": [], "not_found": []}
    def get(self, url, params=None):
        host = urllib.parse.urlsplit(url).netloc
        if host in ST[self.c]["blocked_hosts"]: raise Blocked(host)
        backoff = DELAY
        for attempt in range(4):
            global STOP
            if STOP: raise KeyboardInterrupt
            if mem_kb() <= MEM_STOP_KB:
                print("MEM GUARD: MemAvailable <= 3.5G, stopping", flush=True); STOP = True; raise KeyboardInterrupt
            w = self.last.get(host, 0) + DELAY - time.time()
            if w > 0: time.sleep(w)
            try:
                r = self.s.get(url, params=params, timeout=90); code = r.status_code
            except requests.RequestException:
                r = None; code = -1
            self.last[host] = time.time(); ST[self.c]["req"] += 1
            if code == 200:
                self.c403[host] = 0; return r
            if code == 403:
                self.c403[host] = self.c403.get(host, 0) + 1
                if self.c403[host] >= 3:
                    ST[self.c]["blocked_hosts"].append(host); print(f"{self.c} BLOCKED_SOURCE {host} after 3x403 at {url}", flush=True); raise Blocked(host)
                return None
            if code == 404:
                ST[self.c]["not_found"].append(url); return None
            backoff = min(backoff * 3, 120); time.sleep(backoff)
        ST[self.c]["failed"].append([url, code]); return None
def save(c, key, obj_bytes):
    p = BASE / "raw" / c / key; p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wb") as f: f.write(obj_bytes)
def have(c, key): return (BASE / "raw" / c / key).exists()
def safe(s): return urllib.parse.quote(s, safe="")
def strip(s): return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s))).strip()

def run_VD(F):
    c = "VD"; B = "https://prestations.vd.ch/pub/blv-publication/"
    top = F.get(B + "api/recueil-systematique").json(); acts = []
    for v in top:
        r = F.get(B + "api/recueil-systematique", {"code": v["code"]})
        if not r: continue
        def walk(n):
            if n["typeElement"] == "ACTE" and n["code"].split(".")[0].startswith(v["code"]): acts.append({k: n[k] for k in n if k != "children"})
            for x in n.get("children") or []: walk(x)
        for n in r.json(): walk(n)
    seen = {}; [seen.setdefault(a["code"], a) for a in acts]; acts = list(seen.values())
    (BASE / "index" / "VD.json").write_text(json.dumps(acts, ensure_ascii=False)); ST[c]["index"] = len(acts)
    for a in acts:
        key = safe(a["code"]) + ".json.gz"
        if have(c, key): continue
        r = F.get(B + "api/actes/CONSOLIDE", {"id": a["atelierId"] or a["id"], "cote": a["code"]})
        if not r: ST[c]["err"] += 1; continue
        vers = r.json(); cur = next((x for x in vers if x.get("versionType") == "ACTUELLE"), vers[-1] if vers else None)
        if not cur: ST[c]["err"] += 1; continue
        h = F.get(B + f"api/actes/{cur['htmlId']}/html")
        if not h: ST[c]["err"] += 1; continue
        save(c, key, json.dumps({"meta": a, "version": cur, "html": h.text, "url": B + f"actes/consolide/{a['code']}?id={a['atelierId'] or a['id']}"}, ensure_ascii=False).encode()); ST[c]["ok"] += 1

def run_TI(F):
    c = "TI"; B = "https://www3.ti.ch/CAN/RLeggi/public/index.php/raccolta-leggi/"; acts = {}
    for n in range(1, 40):
        r = F.get(B + f"libro/n/{n}")
        if not r: break
        found = re.findall(r'href="[^"]*legge/num/(\d+)"[^>]*>\s*<div class="printSpace1">\s*<div class="numero">([^<]*)</div><div class="testo">(.*?)</div>', r.text, re.S)
        if not found and n > 1: break
        for num, sn, t in found: acts.setdefault(num, {"num": num, "sn": sn.strip(), "title": strip(t), "volume": n})
    acts = list(acts.values()); (BASE / "index" / "TI.json").write_text(json.dumps(acts, ensure_ascii=False)); ST[c]["index"] = len(acts)
    for a in acts:
        key = a["num"] + ".json.gz"
        if have(c, key): continue
        r = F.get(B + f"legge/num/{a['num']}")
        if not r: ST[c]["err"] += 1; continue
        save(c, key, json.dumps({"meta": a, "html": r.text, "url": B + f"legge/num/{a['num']}"}, ensure_ascii=False).encode()); ST[c]["ok"] += 1

def run_GE(F):
    c = "GE"; T = "https://silgeneve.ch/legis/program/books/rsg/toc.htm"
    r = F.get(T); r.encoding = r.encoding or "windows-1252"; s = r.text
    links = []; 
    for m in re.finditer(r'<a[^>]+href="(htm/rsg_[a-z0-9_]+\.htm)"[^>]*>(.*?)</a>', s, re.S | re.I):
        links.append({"href": m.group(1), "label": strip(m.group(2))})
    seen = {}; [seen.setdefault(l["href"], l) for l in links]; links = list(seen.values())
    (BASE / "index" / "GE.json").write_text(json.dumps(links, ensure_ascii=False)); ST[c]["index"] = len(links)
    for l in links:
        key = l["href"].split("/")[-1] + ".json.gz"
        if have(c, key): continue
        u = urllib.parse.urljoin(T, l["href"]); r = F.get(u)
        if not r: ST[c]["err"] += 1; continue
        txt = r.content.decode("windows-1252", errors="replace") if b"charset=utf-8" not in r.content[:3000].lower() else r.content.decode("utf-8", errors="replace")
        save(c, key, json.dumps({"meta": l, "html": txt, "url": u}, ensure_ascii=False).encode()); ST[c]["ok"] += 1

def run_ZH(F):
    c = "ZH"; W = "https://www.zh.ch"; J = W + "/de/politik-staat/gesetze-beschluesse/gesetzessammlung/_jcr_content/main/lawcollectionsearch_312548694.zhweb-zhlex-ls.zhweb-cache.json"
    acts = {}; capped = []
    for fn in range(1, 15):
        pg = 0
        while True:
            r = F.get(J, {"fileNumber": fn, "page": pg})
            if not r: break
            d = r.json()
            if d.get("moreSearchResultsThanAllowed") and pg == 0: capped.append(fn)
            for x in d["data"]: acts.setdefault(x["referenceNumber"], x)
            pg += 1
            if pg >= d.get("numberOfResultPages", 0): break
    acts = list(acts.values()); (BASE / "index" / "ZH.json").write_text(json.dumps(acts, ensure_ascii=False)); ST[c]["index"] = len(acts); ST[c]["capped_fileNumbers"] = capped
    for a in acts:
        key = safe(a["referenceNumber"]) + ".json.gz"
        if have(c, key): continue
        r = F.get(W + a["link"])
        if not r: ST[c]["err"] += 1; continue
        pdfs = re.findall(r'href="(https://www\.notes\.zh\.ch/appl/zhlex_r\.nsf/OpenAttachment[^"]+\.pdf)"', r.text)
        if not pdfs: ST[c]["err"] += 1; ST[c]["failed"].append([a["link"], "no_pdf"]); continue
        pu = H.unescape(pdfs[0]); mq = re.search(r"docid=([0-9A-F]+)&file=([^&]+\.pdf)", pu)
        if mq: pu = f"https://www.notes.zh.ch/appl/zhlex_r.nsf/WebView/{mq.group(1)}/$File/{mq.group(2)}"
        pdfs[0] = pu
        p = F.get(pu)
        if not p or not p.content.startswith(b"%PDF"): ST[c]["err"] += 1; continue
        pd = BASE / "raw" / c / (safe(a["referenceNumber"]) + ".pdf"); pd.write_bytes(p.content) if pd.parent.exists() else (pd.parent.mkdir(parents=True), pd.write_bytes(p.content))
        save(c, key, json.dumps({"meta": a, "pdf_url": pdfs[0], "all_pdfs": pdfs[:20], "url": W + a["link"]}, ensure_ascii=False).encode()); ST[c]["ok"] += 1

def run_JU(F):
    c = "JU"; W = "https://rsju.jura.ch"
    r = F.get(W + "/Scripts/Modules/Sitemap/Sitemap.aspx?idn=9574")
    idns = sorted(set(re.findall(r'List\.aspx\?idn=(\d+)&(?:amp;)?name=SubCategories', r.text)))
    docs = {}
    for idn in idns:
        start = 0
        while True:
            u = W + f"/Scripts/Modules/CustomView/List.aspx?idn={idn}&name=SubCategories" + (f"&Start={start}" if start else "")
            r = F.get(u)
            if not r: break
            n0 = len(docs)
            for m in re.finditer(r'<a[^>]+href="/fr/viewdocument\.html\?idn=(\d+)&(?:amp;)?id=(\d+)"[^>]*>(.*?)</a>', r.text, re.S):
                if m.group(1) != idn: continue
                t = strip(m.group(3)); mm = re.match(r"([\d.]+)\s+(.*)", t)
                docs.setdefault(m.group(2), {"idn": idn, "id": m.group(2), "sn": mm.group(1) if mm else "", "title": mm.group(2) if mm else t})
            nxt = re.search(rf'List\.aspx\?idn={idn}&(?:amp;)?name=SubCategories&(?:amp;)?Start={start + 1}\b', r.text)
            if nxt and len(docs) > n0: start += 1
            else: break
    docs = list(docs.values()); (BASE / "index" / "JU.json").write_text(json.dumps(docs, ensure_ascii=False)); ST[c]["index"] = len(docs)
    for d in docs:
        key = d["id"] + ".json.gz"
        if have(c, key): continue
        u = W + f"/fr/viewdocument.html?idn={d['idn']}&id={d['id']}&download=1"; r = F.get(u)
        if not r or not r.content.startswith(b"%PDF"): ST[c]["err"] += 1; continue
        (BASE / "raw" / c).mkdir(parents=True, exist_ok=True); (BASE / "raw" / c / (d["id"] + ".pdf")).write_bytes(r.content)
        save(c, key, json.dumps({"meta": d, "pdf_url": u, "url": W + f"/fr/viewdocument.html?idn={d['idn']}&id={d['id']}"}, ensure_ascii=False).encode()); ST[c]["ok"] += 1

def run_AI(F):
    c = "AI"; hst = "https://ai.clex.ch"
    idx = json.load(open(BASE / "index" / "AI.json"))
    L = [x for v in (idx.values() if isinstance(idx, dict) else [idx]) for x in (v if isinstance(v, list) else []) if not x.get("abrogated")]
    seen = {}; [seen.setdefault(x["systematic_number"], x) for x in L]; L = list(seen.values()); ST[c]["index"] = len(L)
    for x in L:
        key = safe(x["systematic_number"]) + ".json.gz"
        if have(c, key): continue
        r = F.get(f"{hst}/api/de/texts_of_law/{safe(x['systematic_number'])}/show_as_json")
        if not r: ST[c]["err"] += 1; continue
        try: r.json()
        except ValueError: ST[c]["err"] += 1; continue
        save(c, key, r.content); ST[c]["ok"] += 1

RUN = {"AI": run_AI, "VD": run_VD, "TI": run_TI, "GE": run_GE, "ZH": run_ZH, "JU": run_JU}
def worker(c):
    F = Fetcher(c)
    try: RUN[c](F); ST[c]["done"] = True
    except Blocked as e: ST[c]["done"] = "BLOCKED"
    except KeyboardInterrupt: ST[c]["done"] = "STOPPED"
    except Exception as e: ST[c]["done"] = f"ERROR {type(e).__name__}: {e}"; print(c, "ERROR", repr(e), flush=True)
def dump():
    with LOCK: (BASE / "collect_other_state.json").write_text(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cantons": ST}, indent=1, ensure_ascii=False))
if __name__ == "__main__":
    cs = sys.argv[1].split(",") if len(sys.argv) > 1 else list(RUN)
    ths = [threading.Thread(target=worker, args=(c,), daemon=True) for c in cs]
    [t.start() for t in ths]; t0 = time.time()
    while any(t.is_alive() for t in ths):
        time.sleep(30); dump()
        print(f"{time.time()-t0:.0f}s mem {mem_kb()//1024} MB " + " ".join(f"{c}:{ST.get(c,{}).get('ok',0)}/{ST.get(c,{}).get('index','?')}" for c in cs), flush=True)
    dump(); print("DONE", json.dumps({c: {k: v for k, v in ST[c].items() if k not in ("failed", "not_found")} for c in cs}), flush=True)
