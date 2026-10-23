"""Tranche-2 census pass 2: empirical fit tests over the pass-1
unclassified pool (bespoke_other / no_listing_found / wordpress /
unreachable_now).

Fit tests (each is page 1 of the real enumeration — classification only
on positive evidence):
  - yii_dokumen: DokumenSearch jenis=PERATURAN DAERAH index (or the
    /dokumen/peraturan-daerah / /dokumen/peraturan card listings) must
    yield >=1 PERATURAN DAERAH-badged .doc-card with a /dokumen/file/ link
    -> adapter jayapura2.
  - dih (Aceh family): /dih/kategori/Peraturan Daerah must list
    /dih/detail/<uuid> links and one sampled detail page must expose a
    PDF via the stock find_pdf_in_detail -> adapter dih.
  - slug_detail (Dairi family): /peraturan listing pages must expose
    /detail/peraturan/peraturan-daerah... links -> adapter slug_detail.
  - unreachable_now units get a fresh pass-1 census first.
"""
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import census2
from census2 import Host, shape_of

CAMP = census2.CAMP
_lock = threading.Lock()
_done = [0]

YII_INDEX = ("/dokumen/index?DokumenSearch%5Btipe_dokumen%5D=1"
             "&DokumenSearch%5Bjenis_peraturan%5D=PERATURAN%20DAERAH&per-page=50")


def perda_cards(html):
    soup = BeautifulSoup(html, "html.parser")
    n, with_file = 0, 0
    for card in soup.select(".doc-card"):
        badge = card.select_one(".doc-badge-type")
        if badge and "PERATURAN DAERAH" in badge.get_text(" ", strip=True).upper():
            n += 1
            if any("/dokumen/file/" in a["href"] for a in card.find_all("a", href=True)):
                with_file += 1
    return n, with_file


def fit_yii(H, base, shapes):
    ev = {}
    r = H.fetch(base + YII_INDEX)
    if r is not None and r.status_code == 200:
        n, wf = perda_cards(r.text)
        ev["index"] = {"cards": n, "with_file": wf}
        if wf >= 1:
            return True, ev
    if any("/dokumen" in s for s in shapes):
        for path in ("/dokumen/peraturan-daerah", "/dokumen/peraturan"):
            r = H.fetch(base + path)
            if r is not None and r.status_code == 200:
                n, wf = perda_cards(r.text)
                # on the dedicated perda path, cards are Perda by route;
                # count any doc-card with a file link as well
                soup = BeautifulSoup(r.text, "html.parser")
                any_file = sum(1 for c in soup.select(".doc-card")
                               if any("/dokumen/file/" in a["href"]
                                      for a in c.find_all("a", href=True)))
                ev[path] = {"perda_cards": n, "perda_with_file": wf,
                            "any_card_with_file": any_file}
                if wf >= 1 or (path.endswith("peraturan-daerah") and any_file >= 1):
                    return True, ev
    return False, ev


def fit_dih(H, base):
    r = H.fetch(base + "/dih/kategori/Peraturan%20Daerah")
    if r is None or r.status_code != 200:
        return False, {"kategori_status": None if r is None else r.status_code}
    soup = BeautifulSoup(r.text, "html.parser")
    dets = sorted({urljoin(r.url, a["href"]) for a in soup.find_all("a", href=True)
                   if re.search(r"/dih/detail/[0-9a-fA-F-]{36}", a["href"])})
    ev = {"detail_links": len(dets)}
    if not dets:
        ev["snippet"] = str(soup)[:1200]
        return False, ev
    r2 = H.fetch(dets[0])
    if r2 is not None and r2.status_code == 200:
        pdf = ""
        for a in BeautifulSoup(r2.text, "html.parser").find_all("a", href=True):
            h = a["href"]
            if re.search(r"\.pdf($|\?)|unduh|download", h, re.I):
                pdf = urljoin(r2.url, h)
                break
        ev["sample_pdf"] = pdf
        ev["detail_text"] = BeautifulSoup(r2.text, "html.parser").get_text(" ", strip=True)[:300]
        return bool(pdf), ev
    return False, ev


def fit_slug(H, base):
    ev = {"pages": []}
    found = 0
    for page in (1, 2, 3):
        url = base + "/peraturan" + ("" if page == 1 else f"?page={page}")
        r = H.fetch(url)
        if r is None or r.status_code != 200:
            ev["pages"].append(None if r is None else r.status_code)
            break
        soup = BeautifulSoup(r.text, "html.parser")
        links = [urljoin(r.url, a["href"]) for a in soup.find_all("a", href=True)
                 if "/detail/peraturan/" in a["href"]]
        pd = [h for h in links if "/detail/peraturan/peraturan-daerah" in h]
        ev["pages"].append({"detail_links": len(set(links)), "perda_links": len(set(pd))})
        found += len(set(pd))
        if not links:
            break
    ev["perda_links_total"] = found
    return found >= 1, ev


def process(bps, rec):
    base = f"https://{rec['host']}"
    out = dict(rec)
    if rec["family"] == "unreachable_now":
        reg = {u["bps"]: u for u in census2.REGISTRY["units"]}
        fresh = census2.census_unit(reg[bps])
        if fresh["family"] != "unreachable_now":
            fresh["pass2_note"] = "re-censused in pass 2"
            return bps, fresh
        out = dict(fresh)
    H = Host(base)
    shapes = out.get("shapes", [])
    # yii fit (all pool units)
    ok, ev = fit_yii(H, base, shapes)
    if ok:
        out.update(family="yii_dokumen", adapter="jayapura2", fit=ev)
        return bps, out
    # dih fit
    if any("/dih" in s for s in shapes):
        ok, ev = fit_dih(H, base)
        if ok:
            out.update(family="dih", adapter="dih", fit=ev)
            return bps, out
        out.setdefault("fit_attempts", {})["dih"] = ev
    # slug fit
    if any("/detail/peraturan/" in s for s in shapes):
        ok, ev = fit_slug(H, base)
        if ok:
            out.update(family="slug_detail", adapter="slug_detail", fit=ev)
            return bps, out
        out.setdefault("fit_attempts", {})["slug"] = ev
    out.setdefault("fit_attempts", {})["yii"] = ev
    with _lock:
        _done[0] += 1
    return bps, out


def main():
    data = json.loads((CAMP / "generic_census_tranche2.json").read_text())
    pool = {b: r for b, r in data.items()
            if r["family"] in ("bespoke_other", "no_listing_found", "wordpress",
                               "unreachable_now")}
    print(f"pass-2 pool: {len(pool)}", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        for bps, rec in ex.map(lambda kv: process(*kv), pool.items()):
            if rec["family"] != pool[bps]["family"]:
                print(f"{bps} {rec['name'][:26]:26s} {pool[bps]['family']} -> "
                      f"{rec['family']}", flush=True)
            rec["family_pass1"] = pool[bps]["family"]
            data[bps] = rec
    (CAMP / "generic_census_tranche2.json").write_text(
        json.dumps(data, indent=1, ensure_ascii=False))
    clusters = {}
    for bps, rec in data.items():
        clusters.setdefault(rec["family"], []).append(bps)
    (CAMP / "id_campaign_tranche2_clusters.json").write_text(json.dumps(
        {"clusters": {k: sorted(v) for k, v in sorted(clusters.items())},
         "counts": {k: len(v) for k, v in sorted(clusters.items())}},
        indent=1, ensure_ascii=False))
    print(json.dumps({k: len(v) for k, v in sorted(clusters.items())}, indent=1))
    print("pass 2 saved")


if __name__ == "__main__":
    main()
