"""Generic: fetch a list of official PDF URLs (robots-checked, ~1 req / 2 s), pdftotext (tesseract OCR fallback),
stage as one national place. usage: collect_pdf_list.py CC items.json platform lang doc_type batchtag
items.json: list of {"url","title"?,"doc_type"?} or plain URL strings. Resumable ckpt in staging/national/CC/_ckpt_<tag>/."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, os, re, json, time, hashlib, subprocess, tempfile, glob, requests
from urllib.parse import unquote
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/us")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/common"))
from stage_util import write_part, utcstamp, now_iso, check_space
import robots
def log(*a): print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)
CC, ITEMS, PLAT, LANG, DT, TAG = sys.argv[1:7]
CK = f"/workspace/world_law/staging/national/{CC}/_ckpt_{TAG}"; os.makedirs(CK, exist_ok=True)
S = requests.Session(); S.headers["User-Agent"] = robots.UA
def pdf_text(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush()
        t = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout
        if len(t.strip()) >= 200: return t, None
        subprocess.run(["pdftoppm", "-r", "200", "-l", "40", "-png", f.name, f.name + "p"], capture_output=True)
        ps = sorted(glob.glob(f.name + "p*.png")); lg = "msa+eng" if LANG == "ms" else "eng"
        t2 = "\n".join(subprocess.run(["tesseract", p, "-", "-l", lg], capture_output=True, text=True).stdout for p in ps)
        for p in ps: os.remove(p)
        return (t2, "tesseract-" + lg) if len(t2.strip()) > len(t.strip()) else (t, None)
def main():
    items = [x if isinstance(x, dict) else {"url": x} for x in json.load(open(ITEMS))]
    seen = set(); items = [x for x in items if not (x["url"] in seen or seen.add(x["url"]))]
    pf = f"{CK}/parts.jsonl"; done = {json.loads(l)["url"] for l in open(pf)} if os.path.exists(pf) else set()
    log("items", len(items), "done", len(done))
    for it in items:
        u = it["url"]
        if u in done: continue
        rb, info = robots.robots_for(u); res = {"url": u, "robots": info.get("rule"), "at": now_iso()}
        if not robots.allowed(u): log("ROBOTS DISALLOW", u, info); res["status"] = "robots_disallow"
        else:
            b = None
            for i in range(4):
                try:
                    r = S.get(u, timeout=120); time.sleep(2)
                    if r.status_code == 200: b = r.content; break
                    log("http", r.status_code, u)
                    if r.status_code < 500: break
                except Exception as e: log("err", u, e)
                time.sleep(20 * 2 ** i)
            if b and b[:5] == b"%PDF-":
                t, ocr = pdf_text(b); res.update(status="ok", text=t, ocr=ocr, sha256=hashlib.sha256(b).hexdigest(), size=len(b))
            else: res["status"] = "fetch_fail" if not b else "not_pdf"
        with open(pf, "a") as f: f.write(json.dumps(res, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())
        log(res["status"], len(res.get("text", "")), u)
    meta = {x["url"]: x for x in items}; recs = []
    for l in open(pf):
        p = json.loads(l)
        if p["status"] != "ok" or p["url"] not in meta: continue
        it = meta[p["url"]]; fn = unquote(p["url"].rsplit("/", 1)[-1])
        title = it.get("title") or re.sub(r"[-_]+", " ", fn[:-4]).strip()
        r = {"place_id": f"iso:{CC}", "country_code": CC, "doc_id": f"{PLAT}:" + hashlib.sha1(p["url"].encode()).hexdigest()[:16],
             "source_platform": PLAT, "source_url": p["url"], "doc_type": it.get("doc_type") or DT, "language": LANG,
             "title_native": title, "html_title": title, "text": p["text"], "consolidated": bool(it.get("consolidated", False)),
             "content_format": "pdf_text", "in_force": None, "retrieved_at": p["at"],
             "extra_metadata": {"file_name": fn, "pdf_sha256": p["sha256"], "pdf_bytes": p["size"], "robots": p["robots"], "ocr": p.get("ocr")}}
        if it.get("number"): r["number"] = it["number"]
        y = re.search(r"\b(1[89]\d\d|20\d\d)\b", title)
        if y: r["adopted_date"] = y[0]
        if len(p["text"].strip()) < 200: r["content_complete"] = False
        recs.append(r)
    if not recs: log("nothing to stage"); return
    check_space(); log(write_part(CC, f"iso:{CC}", f"{TAG}{utcstamp()}p0001", recs, log))
if __name__ == "__main__": main()
