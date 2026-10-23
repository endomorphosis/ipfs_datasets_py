"""Fit test: try each in-scope unit's canonical template enumeration (bounded).
Outputs fittest.json with per-unit verdicts + discovered structure."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, re, time
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
BASE_DIR = "/home/hatch/workspace/goals/world-municipal-law-coverage/hidden_files"
REG = json.load(open(f"{BASE_DIR}/id_jdih_registry_2026-10-12.json"))
PUBLISHED = {"3273", "3374", "3507", "3578"}
units = [u for u in REG["units"]
         if u.get("template") in ("semarang", "surabaya", "jdihn", "malang")
         and u["bps"] not in PUBLISHED]
# Kab. Bandung: registry host collides with Kota Bandung; use its own portal
EXTRA = {"3204": "jdih.bandungkab.go.id"}

def sess():
    s = requests.Session(); s.headers.update(UA); return s

def fit_semarang(s, base):
    r = s.get(base + "/dokumen?tipe_dokumen=1", timeout=90)
    if r.status_code != 200:
        return {"ok": False, "why": f"dokumen list HTTP {r.status_code}"}
    pdfs = [a["href"] for a in BeautifulSoup(r.text, "html.parser")
            .find_all("a", href=re.compile(r"\.pdf$"))]
    perda = [p for p in pdfs if "perda" in p.rsplit("/", 1)[-1].lower()]
    return {"ok": bool(perda), "pdf_links": len(pdfs), "perda_pdf_links": len(perda),
            "sample": perda[:2]}

def fit_surabaya(s, base):
    out = {}
    r = s.get(base + "/peraturan?searchJenisPerda=1", timeout=90)
    out["search_status"] = r.status_code
    pairs = re.findall(r'href="(https?://[^"]*/peraturan/(\d+))"[^>]*>([^<]*)</a>', r.text)
    perda = [p for p in pairs if re.search(r"PERDA|Peraturan Daerah", p[2], re.I)]
    out["search_perda_links"] = len(perda)
    out["search_total_links"] = len(pairs)
    out["sample"] = [p[0] for p in perda[:2]]
    if perda:
        r2 = s.get(base + "/peraturan?searchJenisPerda=1&page=2", timeout=90)
        ids2 = set(re.findall(r"/peraturan/(\d+)", r2.text))
        ids1 = set(p[1] for p in pairs)
        out["page2_new_ids"] = len(ids2 - ids1)
    return {"ok": bool(perda), **out}

def fit_jdihn(s, base):
    r = s.get(base + "/home/produk-hukum/peraturan-perundang-undangan-daerah", timeout=90)
    if r.status_code != 200:
        return {"ok": False, "why": f"list HTTP {r.status_code}"}
    det = re.findall(r'href="https://[^"]*peraturan-perundang-undangan-daerah/\d+"', r.text)
    return {"ok": bool(det), "detail_links": len(det)}

def fit_malang(s, base):
    r = s.get(base + "/prokum?kategori=Peraturan%20Daerah", timeout=90)
    if r.status_code != 200:
        return {"ok": False, "why": f"prokum HTTP {r.status_code}"}
    det = re.findall(r'href="https?://[^"]*/prokum/peraturan-daerah-(\d+)-(\d{4})"', r.text)
    return {"ok": bool(det), "detail_links": len(det), "sample": det[:2]}

FIT = {"semarang": fit_semarang, "surabaya": fit_surabaya,
       "jdihn": fit_jdihn, "malang": fit_malang}

def discover(s, base):
    """Homepage link scan for hosts failing the fit test."""
    try:
        r = s.get(base + "/", timeout=90)
        soup = BeautifulSoup(r.text, "html.parser")
        hits = []
        for a in soup.find_all("a", href=True):
            h = a["href"]
            t = a.get_text(" ", strip=True)
            if re.search(r"peraturan daerah|dokumen|produk-hukum|prokum|inventarisasi",
                         h + " " + t, re.I):
                hits.append((h[:130], t[:50]))
        return {"status": r.status_code, "links": hits[:12]}
    except Exception as e:
        return {"error": repr(e)}

results = {}
for u in units:
    bps = u["bps"]
    host = EXTRA.get(bps, u["best_host"])
    base = f"https://{host}"
    s = sess()
    rec = {"bps": bps, "name": u["name"], "registry_host": u["best_host"],
           "host": host, "template_label": u["template"]}
    try:
        rec["fit"] = FIT[u["template"]](s, base)
    except Exception as e:
        rec["fit"] = {"ok": False, "why": f"exc {e!r}"}
    if not rec["fit"].get("ok"):
        rec["discovery"] = discover(s, base)
    results[bps] = rec
    print(bps, u["name"], u["template"], "->", rec["fit"], flush=True)
    time.sleep(1)

json.dump(results, open(f"{BASE_DIR}/id_campaign/fittest.json", "w"), indent=1,
          ensure_ascii=False)
print("saved fittest.json")
