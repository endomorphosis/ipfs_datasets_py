#!/usr/bin/env python3
"""CN prefecture-city 政府规章 from Guangdong gkmlpt platforms (live, robots via rfc9309).
Usage: eap_cn_gkmlpt.py [--limit-cities N] [--limit-docs N] [city,...]
Checkpoint: staging/eap/_eap_work/cn/gkmlpt.done (doc keys committed after the place chunk flush).
Scanned PDFs (no text layer) -> content_complete=false + scanned-PDF manifest, no OCR.
Exit: 0 done, 4 disk<20GB (warn<23GB), 5 RSS>480MB."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, os, re, json, time, hashlib, subprocess, tempfile, datetime, shutil, resource, argparse
import html as H
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/archive/vendor"))
import requests
from archive import StagedWriter
from schema import place_key
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/web")); from rfc9309 import Robots
from bs4 import BeautifulSoup
STAGE = (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/eap"); W = f"{STAGE}/_eap_work"; CW = f"{W}/cn"
MANS = [(_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/out/eap/_scanned_pdfs_manifest.jsonl"), f"{W}/_scanned_pdfs_manifest.jsonl"]
UA = "Mozilla/5.0 (compatible; world-law-research-bot; eap lane)"; DELAY = 3.5  # 2026-11-01: polite 3-5 s spacing, one request at a time
CITIES = {  # name: (qid, host)  -- prefecture-level cities of Guangdong (ours); Q from global_municipalities_candidate.csv
 "Guangzhou": ("Q16572", "www.gz.gov.cn"), "Shenzhen": ("Q15174", "www.sz.gov.cn"), "Zhuhai": ("Q59095", "www.zhuhai.gov.cn"),
 "Shantou": ("Q59100", "www.shantou.gov.cn"), "Foshan": ("Q34412", "www.foshan.gov.cn"), "Shaoguan": ("Q59107", "www.sg.gov.cn"),
 "Heyuan": ("Q59205", "www.heyuan.gov.cn"), "Meizhou": ("Q59184", "www.meizhou.gov.cn"), "Huizhou": ("Q59173", "www.huizhou.gov.cn"),
 "Shanwei": ("Q59189", "www.shanwei.gov.cn"), "Dongguan": ("Q59218", "www.dg.gov.cn"), "Zhongshan": ("Q59223", "www.zs.gov.cn"),
 "Jiangmen": ("Q59132", "www.jiangmen.gov.cn"), "Yangjiang": ("Q59209", "www.yangjiang.gov.cn"), "Zhanjiang": ("Q59144", "www.zhanjiang.gov.cn"),
 "Maoming": ("Q38927", "www.maoming.gov.cn"), "Zhaoqing": ("Q59164", "www.zhaoqing.gov.cn"), "Qingyuan": ("Q59213", "www.gdqy.gov.cn"),
 "Chaozhou": ("Q59227", "www.chaozhou.gov.cn"), "Jieyang": ("Q26323", "www.jieyang.gov.cn"), "Yunfu": ("Q59233", "www.yunfu.gov.cn"),
 # Hainan prefecture-level cities (same gkmlpt platform)
 "Haikou": ("Q189823", "www.haikou.gov.cn"), "Sanya": ("Q319804", "www.sanya.gov.cn"), "Danzhou": ("Q1015132", "www.danzhou.gov.cn"),
 "Sansha": ("Q264818", "www.sansha.gov.cn")}
os.makedirs(CW, exist_ok=True)
S = requests.Session(); S.headers["User-Agent"] = UA
def log(*a): print(time.strftime("%F %T"), *a, flush=True)
def guard():
    if shutil.disk_usage("/workspace").free < 20 * 2**30: log("disk < 20GB; exit 4"); sys.exit(4)
    if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > 480 * 1024: log("RSS > 480MB; exit 5"); sys.exit(5)
LAST = [0.0]
def get(url, **kw):
    w = DELAY - (time.time() - LAST[0])
    if w > 0: time.sleep(w)
    for i in range(3):
        try:
            r = S.get(url, timeout=30, **kw); LAST[0] = time.time(); return r
        except requests.RequestException as e:
            LAST[0] = time.time(); err = e; time.sleep(5 * (i + 1))
    raise err
SCHEME = {}
IGNORED_POL = "live_robots_ignored_user_directive_20261101"
class RobotsIgnored:
    """2026-11-01 user directive (Benjamin): robots.txt is fetched for provenance only, never used to skip/hold.
    can_fetch() always True; is_disallowed() reports what robots.txt would have said."""
    def __init__(self, real, pol): self.real, self.pol = real, pol
    def can_fetch(self, ua, url): return True
    def is_disallowed(self, url): return self.real is None or not self.real.can_fetch(UA, url)
    def policy(self, url):
        return IGNORED_POL if self.is_disallowed(url) else self.pol
    def basis(self, host, url):
        b = f"{SCHEME.get(host,'https')}://{host}/robots.txt"
        if self.is_disallowed(url): b += f" ({'unreachable' if self.real is None else 'disallows this URL'}; ignored per user directive 2026-11-01)"
        return b
def robots_real(host):
    """-> (Robots or None, policy). None = unreachable."""
    r = None
    for sch in ("https", "http"):
        try: r = get(f"{sch}://{host}/robots.txt", allow_redirects=True); SCHEME[host] = sch; break
        except Exception: continue
    if r is None: return None, "robots_unreachable"
    if r.status_code in (404, 410) or (400 <= r.status_code < 500 and r.status_code not in (401, 403, 429)):
        return Robots(allow_all=True), "robots_404_allow_rfc9309"
    if r.status_code >= 500 or r.status_code in (401, 403, 429): return None, "robots_unreachable"
    return Robots(r.text), "robots_allowed_rfc9309"
def robots(host):
    """-> (RobotsIgnored, policy-label). Never None: robots.txt no longer gates fetching (2026-11-01)."""
    real, pol = robots_real(host)
    rb = RobotsIgnored(real, pol)
    return rb, (pol if real is not None else IGNORED_POL)
def pdf_text(body):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(body); f.flush()
        try: return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True, timeout=120).stdout
        except Exception: return ""
def keep_pdf(cc, pid, doc_id, url, body, policy):
    pk = place_key(pid); sha = hashlib.sha256(body).hexdigest()
    d = f"{W}/_pdf/{cc}/{pk}"; os.makedirs(d, exist_ok=True)
    p = f"{d}/{re.sub(r'[:/]', '_', doc_id)}.pdf"
    with open(p + ".tmp", "wb") as f: f.write(body)
    os.rename(p + ".tmp", p)
    rec = {"doc_id": doc_id, "place_key": pk, "country_code": cc, "source_url": url, "local_path": p, "ocr_done": False,
           "source_policy": policy, "law_file": None, "sha256": sha, "bytes": len(body),
           "fetched_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    for m in MANS:
        os.makedirs(os.path.dirname(m), exist_ok=True)
        with open(m, "a") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return p
def find_tree(host):
    r = get(f"{SCHEME.get(host,'https')}://{host}/gkmlpt/policy")
    if r.status_code != 200: r = get(f"{SCHEME.get(host,'https')}://{host}/gkmlpt/index")
    if r.status_code != 200: return None, None
    t = r.content.decode("utf8", "ignore")
    sid = re.search(r"SID:\s*'(\d+)'", t); tm = re.search(r"TREE:\s*(\[.*?\])\s*,\s*\n", t, re.S)
    if not sid or not tm: return None, None
    ids = []
    def walk(n):
        for x in n:
            if (x.get("name") or "").strip() in ("规章", "政府规章", "市政府规章"): ids.append(x["id"])
            walk(x.get("children") or [])
    walk(json.loads(tm.group(1)))
    return sid.group(1), ids
def listing(host, sid, cid):
    out, page = [], 1
    while True:
        r = get(f"{SCHEME.get(host,'https')}://{host}/gkmlpt/api/all/{cid}?page={page}&sid={sid}")
        d = r.json(); a = d.get("articles") or []
        out += a
        if not a or len(out) >= int(d.get("total") or 0): break
        page += 1
    return out, int(d.get("total") or 0)
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cities", nargs="?"); ap.add_argument("--limit-docs", type=int, default=0)
    a = ap.parse_args()
    names = a.cities.split(",") if a.cities else list(CITIES)
    donef = f"{CW}/gkmlpt.done"; done = set(open(donef).read().split()) if os.path.exists(donef) else set()
    stats = json.load(open(f"{CW}/gkmlpt_stats.json")) if os.path.exists(f"{CW}/gkmlpt_stats.json") else {}
    for name in names:
        guard(); q, host = CITIES[name]; pid = f"wd:{q}"
        rb, pol = robots(host)
        st = stats.setdefault(name, {}); st.update(host=host, qid=q, robots=pol)
        if rb.is_disallowed(f"https://{host}/gkmlpt/api/all/1"): st["robots_ignored"] = True; log(name, host, "robots would disallow/unreachable -> ignored per user directive 2026-11-01")
        try: sid, cids = find_tree(host)
        except Exception as e: st["status"] = f"unreachable {type(e).__name__}"; log(name, host, "unreachable", e); continue
        if not sid or not cids: st["status"] = "no gkmlpt 规章 node"; log(name, host, "no gkmlpt/规章"); continue
        arts = []
        for cid in cids:
            try: x, tot = listing(host, sid, cid); arts += x
            except Exception as e: log(name, "listing error", e); st["status"] = "listing_error"; arts = None; break
        if arts is None: continue
        st.update(sid=sid, cids=cids, listed=len(arts)); log(name, host, "sid", sid, "cids", cids, "listed", len(arts))
        w = StagedWriter(STAGE, "CN", pid, batch_prefix="eap-cn-gkmlpt-", chunk=50); pend = []; n = scans = 0
        for art in arts:
            key = f"gkmlpt:{host}:{art['id']}"
            if key in done: continue
            if a.limit_docs and n >= a.limit_docs: break
            guard(); url = art.get("url") or art.get("post_url")
            if not url or not rb.can_fetch(UA, url): continue
            try: r = get(url)
            except Exception as e: log("fetch fail", url, e); continue
            if r.status_code != 200:
                alt = ("https://" + url[7:]) if url.startswith("http://") else ("http://" + url[8:])
                try: r = get(alt)
                except Exception: pass
                if r.status_code != 200: log("http", r.status_code, url); continue
            h = r.content.decode("utf8", "ignore"); s = BeautifulSoup(h, "lxml")
            body = s.select_one(".article-content") or s.select_one(".content")
            text = body.get_text("\n", strip=True) if body else ""
            doc_id = "gkmlpt:" + hashlib.sha1(url.lower().encode()).hexdigest()[:16]
            rec = {"place_id": pid, "qid": q, "country_code": "CN", "doc_id": doc_id, "source_platform": "gkmlpt",
                   "platform": "gkmlpt", "source_url": url, "doc_type": "regulation", "language": "zh",
                   "consolidated": False, "source_official": True, "admin_level": "municipality", "place_name": name,
                   "title_native": (art.get("title") or "")[:300], "number": art.get("document_number") or None,
                   "publisher": art.get("publisher"), "in_force": (False if art.get("is_abolished") or art.get("is_expired") else None),
                   "source_policy": rb.policy(url), "robots_basis": rb.basis(host, url),
                   "retrieved_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "extra_metadata": {"gkmlpt": {"id": art["id"], "sid": sid, "identifier": art.get("identifier"),
                                                 "classify": art.get("classify_main_name")}}}
            if art.get("date"): rec["promulgation_date"] = datetime.datetime.fromtimestamp(art["date"], datetime.UTC).strftime("%F")
            if len(text) >= 200:
                rec.update(content_format="html", html=str(body)[:2_000_000], text=text[:1_000_000], text_source="html")
            else:
                pdfs = [x.get("href") for x in s.select("a[href]") if x.get("href", "").lower().endswith(".pdf")]
                got = False
                for pu in pdfs[:1]:
                    pu = requests.compat.urljoin(url, pu)
                    if not rb.can_fetch(UA, pu): continue
                    try: pr = get(pu)
                    except Exception: continue
                    if pr.status_code == 200 and pr.content[:5] == b"%PDF-":
                        t = pdf_text(pr.content); rec["content_format"] = "pdf_text"; rec["attachment_url"] = pu; got = True
                        if len(t.strip()) < 200:
                            rec.update(content_complete=False, text_source="none", text=t.strip() or "(scanned PDF; no text layer)",
                                       incomplete_reason="scanned PDF, no text layer; OCR deferred to OCR bot")
                            rec["scanned_pdf_local"] = keep_pdf("CN", pid, doc_id, pu, pr.content, pol); scans += 1
                        else: rec.update(text=t[:1_000_000], text_source="pdf_text")
                if not got:
                    rec.update(content_format="html", html=str(body or "")[:2_000_000], text=text or "(empty)", text_source="html",
                               content_complete=False, incomplete_reason="article body short/empty and no text PDF")
            w.add(rec); pend.append(key); n += 1
            if len(pend) >= 50:
                w.flush(); open(donef, "a").write("".join(k + "\n" for k in pend)); done.update(pend); pend = []
        w.flush()
        if pend: open(donef, "a").write("".join(k + "\n" for k in pend)); done.update(pend)
        st.update(staged_total=st.get("staged_total", 0) + n, scans=st.get("scans", 0) + scans, status="ok", updated=time.strftime("%F %T"))
        json.dump(stats, open(f"{CW}/gkmlpt_stats.json.tmp", "w"), ensure_ascii=False, indent=1); os.replace(f"{CW}/gkmlpt_stats.json.tmp", f"{CW}/gkmlpt_stats.json")
        log(name, "staged", n, "scans", scans)
    json.dump(stats, open(f"{CW}/gkmlpt_stats.json.tmp", "w"), ensure_ascii=False, indent=1); os.replace(f"{CW}/gkmlpt_stats.json.tmp", f"{CW}/gkmlpt_stats.json")
    log("DONE")
if __name__ == "__main__": main()
