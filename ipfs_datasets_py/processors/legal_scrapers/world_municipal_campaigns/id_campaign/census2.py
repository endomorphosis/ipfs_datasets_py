"""Tranche-2 generic-bucket census: per-host link-shape census over the
174 generic_jdih units, clustered into harvestable families.

Polite by construction: <=5 requests per host, 1.5s+ spacing per host,
single attempt per page (timeouts are census data, not failures to hide).
Output: generic_census_tranche2.json + id_campaign_tranche2_clusters.json
"""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

WS = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
CAMP = WS / "id_campaign"
REGISTRY = json.loads((WS / "id_jdih_registry_2026-10-12.json").read_text())
PUBLISHED = {"3273", "3578", "3374", "3507", "3518", "3401", "6108", "3521",
             "6103", "7372", "3504", "3602", "3311"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
TIMEOUT = 40

_lock = threading.Lock()
_done = [0]


def shape_of(url):
    p = urlparse(url)
    path = re.sub(r"\d+", "#", p.path)
    keys = sorted(kv.split("=")[0] for kv in p.query.split("&") if kv)
    return path + (("?" + "&".join(keys)) if keys else "")


class Host:
    def __init__(self, base):
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.base = base
        self.last = 0.0
        self.pages = []       # {url, status, len, err}
        self.hrefs = []       # absolute hrefs across fetched pages
        self.html_blobs = []

    def fetch(self, url):
        wait = 1.5 - (time.monotonic() - self.last)
        if self.last and wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        try:
            r = self.s.get(url, timeout=TIMEOUT)
            self.pages.append({"url": url, "status": r.status_code,
                               "len": len(r.content)})
            if r.status_code == 200 and "html" in r.headers.get("Content-Type", "html"):
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    self.hrefs.append(urljoin(url, a["href"]))
                self.html_blobs.append(r.text[:200000])
            return r
        except Exception as exc:
            self.pages.append({"url": url, "status": None,
                               "err": f"{type(exc).__name__}"})
            return None


LISTY = re.compile(r"peraturan|perda|dokumen|produk|prokum|inventarisasi|"
                   r"kategori|pencarian|hukum|monografi", re.I)


def census_unit(u):
    bps, host = u["bps"], u["best_host"]
    base = f"https://{host}"
    H = Host(base)
    home = H.fetch(base + "/")
    rec = {"bps": bps, "name": u["name"], "host": host}
    if home is not None and home.status_code == 200:
        final_host = urlparse(home.url).netloc
        if final_host and final_host != host:
            rec["redirected_to"] = final_host
    # candidate listing links from the homepage link set
    cands, seen_shapes = [], set()
    for h in H.hrefs:
        p = urlparse(h)
        if p.netloc and p.netloc != urlparse(urljoin(base, h)).netloc:
            pass
        if not LISTY.search(h):
            continue
        if re.search(r"\.(pdf|jpg|png|zip)$", p.path, re.I):
            continue
        sh = shape_of(h)
        if sh in seen_shapes or h.rstrip("/") == base:
            continue
        seen_shapes.add(sh)
        cands.append(h)
    # prefer links that smell most like a Perda listing
    def score(h):
        low = h.lower()
        s = 0
        for kw, w in (("peraturan-daerah", 5), ("perda", 4), ("tipe_dokumen", 4),
                      ("kategori", 3), ("dokumen", 2), ("peraturan", 2),
                      ("prokum", 2), ("inventarisasi", 2)):
            if kw in low:
                s += w
        return -s
    cands.sort(key=score)
    fetched_listings = []
    for h in cands[:3]:
        if H.fetch(h) is not None:
            fetched_listings.append(h)
    if not cands:
        for guess in ("/dokumen?tipe_dokumen=1", "/peraturan/jenis/perda/"):
            if H.fetch(base + guess) is not None:
                fetched_listings.append(base + guess)
    rec["pages"] = H.pages
    rec["fetched_listings"] = fetched_listings

    hrefs = H.hrefs + [p["url"] for p in H.pages]
    low = [h.lower() for h in hrefs]
    shapes = sorted({shape_of(h) for h in hrefs if h.startswith("http")})
    pdfs = [h for h in hrefs if h.lower().split("?")[0].endswith(".pdf")]
    rec["n_links"] = len(hrefs)
    rec["n_pdf_links"] = len(pdfs)
    rec["pdf_samples"] = pdfs[:3]
    rec["shapes"] = shapes[:30]
    blob = "\n".join(H.html_blobs).lower()

    def any_re(pat):
        return any(re.search(pat, h) for h in low)

    M = {
        "common_pdf": any_re(r"/common/dokumen/[^/]*\.pdf"),
        "dokumen_tipe": any_re(r"/dokumen\?[^#]*tipe_dokumen"),
        "dokumen_perda": any_re(r"/dokumen/perda\b"),
        "dokumen_view": "/dokumen/view" in " ".join(low),
        "inventarisasi": "/inventarisasi-hukum/" in " ".join(low),
        "unduh_permalink": any_re(r"/peraturan/\d{4}perda\d+"),
        "unduh_path": "/unduh/" in " ".join(low),
        "prokum_detail": any_re(r"/prokum/peraturan-daerah-\d+-\d{4}"),
        "prokum_getfile": "get_file" in " ".join(low) or "/prokum/detail" in " ".join(low),
        "prokum": "/prokum" in " ".join(low),
        "jdihn_list": "/home/produk-hukum/peraturan-perundang-undangan-daerah" in " ".join(low),
        "home_kategori": "/home/kategori/peraturan-daerah" in " ".join(low),
        "produkHukum": "/produkhukum" in " ".join(low),
        "pencarian_jenis": any_re(r"/pencarian\?[^#]*jenis"),
        "produk_detail": "/produk/detail" in " ".join(low),
        "peraturan_daftar": "/peraturan/daftar" in " ".join(low),
        "peraturan_download": "/peraturan/download/" in " ".join(low),
        "peraturan_num_detail": any_re(r"/peraturan/\d+($|[?#])"),
        "dokumen_php": "dokumen.php" in " ".join(low),
        "unduh_ajax": "action=get_file" in blob,
        "wp": ("/wp-content/" in blob or "/wp-json/" in blob
               or "/category/" in " ".join(low)),
        "spa": (('id="app"' in blob or "__nuxt" in blob or 'id="root"' in blob)
                and len(H.hrefs) < 10),
    }
    rec["markers"] = [k for k, v in M.items() if v]

    ok_pages = [p for p in H.pages if p.get("status") == 200]
    family, adapter, listing = "unknown", None, None
    if not ok_pages:
        family = "unreachable_now"
    elif M["unduh_permalink"] or (M["unduh_path"] and M["unduh_ajax"]):
        family, adapter = "permalink_unduh", "kapuashulu"
    elif M["common_pdf"] or M["dokumen_perda"] or M["dokumen_tipe"]:
        family, adapter = "common_dokumen", "common_dokumen"
        for p in H.pages:
            u2 = p["url"]
            if re.search(r"/dokumen(/perda|/peraturan)?\?", u2) or u2.endswith("/dokumen/perda"):
                listing = urlparse(u2).path + ("?" + urlparse(u2).query if urlparse(u2).query else "")
        listing = listing or "/dokumen?tipe_dokumen=1"
    elif M["inventarisasi"]:
        family, adapter = "inventarisasi", "inventarisasi"
    elif M["dokumen_view"]:
        family, adapter = "dokumen_view", "dokumen_view"
    elif M["jdihn_list"]:
        family, adapter = "jdihn_list", "jdihn_list"
    elif M["prokum_detail"]:
        family, adapter = "prokum_list", "prokum_list"
    elif M["prokum_getfile"]:
        family, adapter = "prokum_nganjuk", "nganjuk"
    elif M["produkHukum"]:
        family, adapter = "produkhukum", "banjarmasin"
    elif M["home_kategori"]:
        family, adapter = "home_kategori", "lomboktengah"
    elif M["produk_detail"]:
        family, adapter = "produk_detail", "sukoharjo"
    elif M["pencarian_jenis"]:
        family, adapter = "pencarian", "kulonprogo"
    elif M["peraturan_daftar"]:
        family, adapter = "peraturan_daftar", "aru"
    elif M["dokumen_php"]:
        family, adapter = "dokumen_php", "waykanan"
    elif M["peraturan_download"]:
        family, adapter = "peraturan_download", "ngawi"
    elif M["peraturan_num_detail"]:
        family, adapter = "laravel_peraturan", "tulungagung"
    elif M["prokum"]:
        family, adapter = "prokum_other", "nganjuk"
    elif M["wp"]:
        family = "wordpress"
        if any("/category/semua-peraturan/peraturan_daerah" in h for h in low):
            adapter = "parepare"
    elif M["spa"]:
        family = "spa_shell"
    elif any(LISTY.search(h) for h in hrefs):
        family = "bespoke_other"
    else:
        family = "no_listing_found"
    rec["family"], rec["adapter"], rec["listing_path"] = family, adapter, listing
    with _lock:
        _done[0] += 1
        print(f"[{_done[0]}] {bps} {u['name'][:28]:28s} -> {family}"
              f" pdf={rec['n_pdf_links']} pages={len(H.pages)}", flush=True)
    return rec


def main():
    units = [u for u in REGISTRY["units"]
             if u["template"] == "generic_jdih"
             and u["status"] in ("verified_jdih", "verified_harvested")
             and u["bps"] not in PUBLISHED]
    print(f"census over {len(units)} generic units", flush=True)
    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for rec in ex.map(census_unit, units):
            out[rec["bps"]] = rec
    (CAMP / "generic_census_tranche2.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False))
    clusters = {}
    for bps, rec in out.items():
        clusters.setdefault(rec["family"], []).append(bps)
    (CAMP / "id_campaign_tranche2_clusters.json").write_text(json.dumps(
        {"clusters": {k: sorted(v) for k, v in sorted(clusters.items())},
         "counts": {k: len(v) for k, v in sorted(clusters.items())}},
        indent=1, ensure_ascii=False))
    print(json.dumps({k: len(v) for k, v in sorted(clusters.items())}, indent=1))
    print("saved generic_census_tranche2.json + clusters")


if __name__ == "__main__":
    main()
