#!/usr/bin/env python3
"""CN city 政府规章 / 地方性法规 from per-city official listing pages (live; robots via rfc9309).
Config: SITES in cn_sites.json next to this file: {key: {qid, name, host, lists:[url,...], link: regex, pages: N, doc_type}}
 lists may contain {n} for pagination (n=1..pages; page 0 = url with '{n}' part removed via 'first').
Checkpoint: staging/eap/_eap_work/cn/cityrules.done (keys committed after flush). Held sites logged in cityrules_stats.json.
Exit: 4 disk<20GB (warn<23GB), 5 RSS>480MB."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, os, re, json, time, hashlib, datetime, argparse
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/eap"))
import eap_cn_gkmlpt as G   # shared helpers: get, robots, guard, pdf_text, keep_pdf, log, STAGE, CW
from archive import StagedWriter
from bs4 import BeautifulSoup
import requests
HERE = os.path.dirname(os.path.abspath(__file__))
SEL = [".gknbxq_detail", ".zfxxgk_content", ".trs_editor_view", ".TRS_UEDITOR", ".TRS_Editor", "#zoom", "#Zoom", ".article-content", ".view", "#content", ".content", ".article", ".zw", ".main-txt", "#UCAP-CONTENT", ".pages_content", "article"]
def best_body(s):
    best, bl = None, 0
    for sel in SEL:
        for e in s.select(sel)[:3]:
            t = e.get_text("\n", strip=True)
            if len(t) > bl and len(t) < 600_000: best, bl = e, len(t)
    if bl < 200:  # fallback: densest div (text minus link text)
        for e in s.find_all(["div", "td", "section"]):
            tl = len(e.get_text(strip=True)); ll = sum(len(a.get_text(strip=True)) for a in e.find_all("a"))
            sc = tl - 3 * ll
            if sc > bl and tl < 600_000: best, bl = e, sc
    return best
def list_links(cfg, rb):
    out, seen = [], set()
    rx = re.compile(cfg["link"])
    for lu in cfg["lists"]:
        urls = [lu.replace("{n}", "")] if "{n}" not in lu else [cfg.get("first", lu.replace("_{n}", ""))] + [lu.format(n=i) for i in range(cfg.get("start", 1), cfg.get("pages", 1))]
        for u in urls:
            if not rb.can_fetch(G.UA, u): continue
            try: r = G.get(u)
            except Exception as e: G.log("list fail", u, e); break
            if r.status_code != 200: break
            h = r.content.decode(r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding, "ignore")
            new = 0
            for m in rx.finditer(h):
                lk = requests.compat.urljoin(u, H_un(m.group(1)))
                if lk not in seen: seen.add(lk); out.append(lk); new += 1
            if new == 0 and "{n}" in lu: break
    return out
def H_un(x): import html; return html.unescape(x)
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("sites", nargs="?"); ap.add_argument("--limit-docs", type=int, default=0); a = ap.parse_args()
    SITES = json.load(open(f"{HERE}/cn_sites.json"))
    keys = a.sites.split(",") if a.sites else list(SITES)
    donef = f"{G.CW}/cityrules.done"; done = set(open(donef).read().split()) if os.path.exists(donef) else set()
    sf = f"{G.CW}/cityrules_stats.json"; stats = json.load(open(sf)) if os.path.exists(sf) else {}
    def save():
        json.dump(stats, open(sf + ".tmp", "w"), ensure_ascii=False, indent=1); os.replace(sf + ".tmp", sf)
    for k in keys:
        G.guard(); cfg = SITES[k]; host = cfg["host"]; pid = f"wd:{cfg['qid']}"
        st = stats.setdefault(k, {}); rb, pol = G.robots(host); st.update(host=host, qid=cfg["qid"], robots=pol)
        if rb.real is None: st["robots_ignored"] = True; G.log(k, "robots unreachable -> ignored per user directive 2026-11-01")
        links = list_links(cfg, rb); st["listed"] = len(links); G.log(k, "listed", len(links))
        if not links: st["status"] = "no_links"; save(); continue
        w = StagedWriter(G.STAGE, "CN", pid, batch_prefix=f"eap-cn-{k}-", chunk=50); pend = []; n = 0
        for url in links:
            key = f"city2:{k}:{url}"
            if key in done: continue
            if a.limit_docs and n >= a.limit_docs: break
            if not rb.can_fetch(G.UA, url): continue
            G.guard()
            try: r = G.get(url)
            except Exception as e: G.log("fetch fail", url, e); continue
            if r.status_code != 200: G.log("http", r.status_code, url); continue
            enc = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else r.apparent_encoding
            h = r.content.decode(enc or "utf8", "ignore"); s = BeautifulSoup(h, "lxml")
            body = best_body(s); text = body.get_text("\n", strip=True) if body else ""
            mt = s.find("meta", attrs={"name": "ArticleTitle"})
            t = s.find("title")
            title = (mt.get("content") or "").strip() if mt and mt.get("content") else None
            if not title: title = re.split(r"[_|]", re.sub(r"\s+", "", t.get_text()))[0] if t else url
            if 0: title = re.split(r"\s*[-_|]\s*[^-_|]*(?:网站|政府网|门户)[^-_|]*$", (t.get_text(strip=True) if t else url))[0][:300]
            num = re.search(r"([^\s\d（(日年月，,、]{0,8}政府令\s*第\s*\d+\s*号)", text[:600])
            doc_id = f"cn{k}:" + hashlib.sha1(url.lower().encode()).hexdigest()[:16]
            rec = {"place_id": pid, "qid": cfg["qid"], "country_code": "CN", "doc_id": doc_id, "source_platform": f"cn_city_{k}",
                   "platform": f"cn_city_{k}", "source_url": url, "doc_type": cfg.get("doc_type", "regulation"), "language": "zh",
                   "consolidated": False, "source_official": True, "admin_level": "municipality", "place_name": cfg["name"],
                   "title_native": title, "source_policy": rb.policy(url), "robots_basis": rb.basis(host, url),
                   "retrieved_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
            if num: rec["number"] = num.group(1)
            if len(text) >= 200: rec.update(content_format="html", html=str(body)[:2_000_000], text=text[:1_000_000], text_source="html")
            else:
                got = False
                for x in s.select("a[href]"):
                    pu = requests.compat.urljoin(url, x.get("href", ""))
                    if not pu.lower().endswith(".pdf") or not rb.can_fetch(G.UA, pu): continue
                    try: pr = G.get(pu)
                    except Exception: break
                    if pr.status_code == 200 and pr.content[:5] == b"%PDF-":
                        tx = G.pdf_text(pr.content); rec["content_format"] = "pdf_text"; rec["attachment_url"] = pu; got = True
                        if len(tx.strip()) < 200:
                            rec.update(content_complete=False, text_source="none", text=tx.strip() or "(scanned PDF; no text layer)",
                                       incomplete_reason="scanned PDF, no text layer; OCR deferred to OCR bot")
                            rec["scanned_pdf_local"] = G.keep_pdf("CN", pid, doc_id, pu, pr.content, pol)
                        else: rec.update(text=tx[:1_000_000], text_source="pdf_text")
                    break
                if not got:
                    rec.update(content_format="html", html=str(body or "")[:2_000_000], text=text or "(empty)", text_source="html",
                               content_complete=False, incomplete_reason="body short/empty and no text PDF")
            w.add(rec); pend.append(key); n += 1
            if len(pend) >= 50: w.flush(); open(donef, "a").write("".join(x + "\n" for x in pend)); done.update(pend); pend = []
        w.flush()
        if pend: open(donef, "a").write("".join(x + "\n" for x in pend)); done.update(pend)
        st.update(status="ok", staged_total=st.get("staged_total", 0) + n, updated=time.strftime("%F %T")); save(); G.log(k, "staged", n)
    save(); G.log("DONE")
if __name__ == "__main__": main()
