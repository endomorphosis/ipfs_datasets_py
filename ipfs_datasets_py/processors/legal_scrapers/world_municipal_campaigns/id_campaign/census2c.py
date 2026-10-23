"""Tranche-2 census pass 3: two empirical fits the earlier passes missed.

  - dokumen_view family (Yii app, Paser-style): the dedicated listing
    /dokumen/peraturan-daerah (or the mixed /dokumen/peraturan) must
    expose /dokumen/view?id=N detail links -> adapters
    dokumen_view_perda / dokumen_view.
  - dih family (Aceh): /dih/jsondata with the category code parsed from
    the kategori page JS must report recordsFiltered >= 1 -> adapter dih
    (sample title recorded; Aceh 'Qanun' titles are counted separately
    by the enumerator's guard-faithful pre-filter).
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import census2
from census2 import Host

CAMP = census2.CAMP


def view_links(html, url):
    soup = BeautifulSoup(html, "html.parser")
    return {urljoin(url, a["href"]) for a in soup.find_all("a", href=True)
            if re.search(r"/dokumen/view\?id=\d+", a["href"])}


def process(bps, rec):
    base = f"https://{rec['host']}"
    H = Host(base)
    out = dict(rec)
    shapes = rec.get("shapes", [])
    # --- dokumen_view fits (any pool unit: 1-2 requests)
    for path, fam, adp in (("/dokumen/peraturan-daerah", "dokumen_view_perda",
                            "dokumen_view_perda"),
                           ("/dokumen/peraturan", "dokumen_view", "dokumen_view")):
        r = H.fetch(base + path)
        if r is not None and r.status_code == 200:
            vl = view_links(r.text, r.url)
            if vl:
                out.update(family=fam, adapter=adp,
                           fit={"listing": path, "view_links_p1": len(vl)})
                return bps, out
    # --- dih jsondata fit
    if any("/dih" in s for s in shapes):
        r = H.fetch(base + "/dih/kategori/Peraturan%20Daerah")
        if r is not None and r.status_code == 200:
            m = re.search(r'\{display:\s*"Peraturan Daerah[^"]*",\s*value:\s*"(\d+)"\}',
                          r.text)
            kat = m.group(1) if m else "15"
            rr = H.fetch(f"{base}/dih/jsondata?draw=1&start=0&length=3&kat_dok={kat}")
            if rr is not None and rr.status_code == 200:
                try:
                    d = rr.json()
                    total = d.get("recordsFiltered", 0)
                    sample = ""
                    if d.get("data"):
                        tm = re.search(r'class="news-title"[^>]*>(.*?)</a>',
                                       d["data"][0][0], re.S)
                        if tm:
                            sample = re.sub(r"<[^>]+>", " ", tm.group(1)).strip()[:120]
                    if total >= 1:
                        out.update(family="dih", adapter="dih",
                                   fit={"kat_dok": kat, "records_filtered": total,
                                        "sample_title": sample})
                        return bps, out
                    out.setdefault("fit_attempts", {})["dih"] = {"records_filtered": 0}
                except Exception as exc:
                    out.setdefault("fit_attempts", {})["dih"] = {"err": repr(exc)[:80]}
    return bps, out


def main():
    data = json.loads((CAMP / "generic_census_tranche2.json").read_text())
    pool = {b: r for b, r in data.items()
            if r["family"] in ("bespoke_other", "no_listing_found", "wordpress")}
    print(f"pass-3 pool: {len(pool)}", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        for bps, rec in ex.map(lambda kv: process(*kv), pool.items()):
            if rec["family"] != pool[bps]["family"]:
                print(f"{bps} {rec['name'][:26]:26s} -> {rec['family']}", flush=True)
                rec["family_pass2"] = pool[bps]["family"]
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
    print("pass 3 saved")


if __name__ == "__main__":
    main()
