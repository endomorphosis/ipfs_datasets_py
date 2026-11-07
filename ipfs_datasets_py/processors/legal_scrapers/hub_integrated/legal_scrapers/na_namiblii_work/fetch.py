#!/workspace/hf-venv/bin/python
"""NA NamibLII archive fetcher: Wayback id_ snapshots (<=1 req/s, sequential, backoff), archived source.pdf fallback,
then Common Crawl index + ranged WARC fallback via common_crawl_helper. Checkpoint: results.jsonl. Never touches live namiblii.org."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, re, sys, time, shutil, hashlib, requests
sys.path.insert(0, str(_SCRAPERS))
W = str(_SCRAPERS) + "/na_namiblii_work"; RAW = W + "/raw"; os.makedirs(RAW, exist_ok=True)
UA = "EndomorphosisLegalTranslation/1.0 (archive research; owner benjamin barber)"
S = requests.Session(); S.headers["User-Agent"] = UA
def log(*a): print(time.strftime("%F %T"), *a, flush=True)
def guard():
    while True:
        free = shutil.disk_usage("/").free / 2**30
        mem = int(re.search(r"MemAvailable:\s+(\d+)", open("/proc/meminfo").read()).group(1)) / 2**20
        if free >= 22 and mem >= 4.5: return
        log(f"PAUSE disk={free:.1f}G mem={mem:.1f}G (need 22G/4.5G); recheck in 180s"); time.sleep(180)
last = [0.0]; BLK = [0]
def get(url):
    for i in range(7):
        guard(); dt = time.time() - last[0]
        if dt < 1.1: time.sleep(1.1 - dt)
        last[0] = time.time()
        try: r = S.get(url, timeout=90)  # TLS verification always on
        except requests.RequestException as e: log("ERR", e); time.sleep(2 ** i * 2); continue
        if r.status_code == 429 or r.status_code >= 500: log("BACKOFF", r.status_code, url); time.sleep(2 ** i * 5); continue
        if r.status_code == 403 or b"challenges.cloudflare" in r.content[:3000]:
            BLK[0] += 1; log("BLOCKED?", r.status_code, url)
            if BLK[0] >= 5: log("STOP: archive.org blocking/challenging"); open(W + "/BLOCKED", "w").write(url); sys.exit(3)
            return None
        BLK[0] = 0; return r
    return None
def akn_text(html):
    from bs4 import BeautifulSoup
    s = BeautifulSoup(html, "lxml"); doc = s.select_one(".akn-akomaNtoso") or s.select_one("la-akoma-ntoso") or s.select_one("#document-content")
    t = s.select_one("h1") or s.title; title = t.get_text(" ", strip=True) if t else ""
    if not doc: return title, "", []
    secs = []
    for sec in doc.select(".akn-section"):
        h = sec.find(re.compile("^h[1-6]$"))
        secs.append({"num": sec.get("data-eid") or sec.get("id") or "", "heading": h.get_text(" ", strip=True) if h else "", "text": sec.get_text("\n", strip=True)})
    return title, doc.get_text("\n", strip=True), secs
def pdf_text(b):
    import fitz
    try: return "\n".join(p.get_text() for p in fitz.open(stream=b, filetype="pdf"))
    except Exception: return ""
def save(k, title, text, secs):
    h = hashlib.sha1(k.encode()).hexdigest()[:16]; json.dump({"title": title, "text": text, "sections": secs}, open(f"{RAW}/{h}.json", "w")); return h
if __name__ == "__main__":
    inv = json.load(open(W + "/wb_inventory.json")); done = {}
    if os.path.exists(W + "/results.jsonl"):
        for l in open(W + "/results.jsonl"): d = json.loads(l); done[d["key"]] = d
    out = open(W + "/results.jsonl", "a"); log("start", len(inv), "done", len(done))
    for k, v in inv.items():
        if k in done: continue
        ts, url = v.get("html") or v["src"]; rec = {"key": k, "orig_url": url, "source": "wayback", "ts": ts}
        title, text, secs = "", "", []
        if "html" in v:
            r = get(f"https://web.archive.org/web/{ts}id_/{url}")
            if r is not None and r.ok: title, text, secs = akn_text(r.text)
        if len(text) < 300 and "src" in v:
            sts, surl = v["src"]; r2 = get(f"https://web.archive.org/web/{sts}id_/{surl}")
            if r2 is not None and r2.ok and r2.content[:4] == b"%PDF":
                t2 = pdf_text(r2.content)
                if len(t2) > len(text): text, secs = t2, []; rec.update(pdf=surl, pdf_ts=sts)
        rec.update(title=title, chars=len(text))
        if text: rec["raw"] = save(k, title, text, secs)
        out.write(json.dumps(rec) + "\n"); out.flush(); done[k] = rec
        if len(done) % 100 == 0: log("progress", len(done), "/", len(inv))
    log("WAYBACK DONE", len(done))
    nrm = lambda u: re.sub(r"^http:", "https:", u.split("?")[0].rstrip("/"))
    miss = {nrm(done[k]["orig_url"]): k for k in done if not done[k].get("raw") or done[k]["chars"] < 300}
    if miss and not os.path.exists(W + "/CC_DONE"):
        import common_crawl_helper as cc
        guard(); ptrs = cc.find_pointers("namiblii.org", cc.spread_collections(8), status="200", mime_regex="html|pdf", max_records=20000)
        hits = [p for p in ptrs if nrm(p["url"]) in miss]; log("CC pointers", len(ptrs), "matching missing", len(hits))
        for p in hits:
            guard()
            try: recs = cc.fetch_records([p])
            except Exception as e: log("CC ERR", e); continue
            for rr in recs:
                body = rr.get("body") or b""; k = miss[nrm(p["url"])]
                if isinstance(body, str): body = body.encode()
                title, text, secs = akn_text(body) if b"<html" in body[:3000].lower() else ("", pdf_text(body), [])
                if len(text) >= 300:
                    out.write(json.dumps({**done[k], "source": "commoncrawl", "ts": p.get("timestamp"), "cc_collection": p.get("collection"),
                        "raw": save(k, title, text, secs), "chars": len(text), "title": title or done[k].get("title")}) + "\n"); out.flush()
        open(W + "/CC_DONE", "w").write("ok")
    log("ALL FETCH DONE"); open(W + "/FETCH_DONE", "w").write("ok")
