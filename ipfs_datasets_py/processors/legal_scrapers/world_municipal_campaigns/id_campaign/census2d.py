"""Tranche-2 census pass 4 (DIH only): classify the Aceh-family units
with the /dih/jsondata fit, using the polite session (long timeouts,
one retry) instead of the rapid-census fetcher that timed out on these
slow hosts."""
import importlib.util
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CAMP = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "id_campaign"
spec = importlib.util.spec_from_file_location(
    "id_pilot_build",
    str(CAMP.parent / "id_pilot" / "id_pilot_build.py"))
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def process(bps, rec):
    base = f"https://{rec['host']}"
    sess = pilot.PoliteSession()
    out = dict(rec)
    try:
        r = sess.get(base + "/dih/kategori/Peraturan%20Daerah", timeout=120)
        if r.status_code != 200:
            out.setdefault("fit_attempts", {})["dih_json"] = {"kategori_status": r.status_code}
            return bps, out
        m = re.search(r'\{display:\s*"Peraturan Daerah[^"]*",\s*value:\s*"(\d+)"\}', r.text)
        kat = m.group(1) if m else "15"
        rr = sess.get(f"{base}/dih/jsondata?draw=1&start=0&length=3&kat_dok={kat}",
                      timeout=120)
        d = rr.json()
        total = d.get("recordsFiltered", 0)
        sample = ""
        if d.get("data"):
            tm = re.search(r'class="news-title"[^>]*>(.*?)</a>', d["data"][0][0], re.S)
            if tm:
                sample = re.sub(r"<[^>]+>", " ", tm.group(1)).strip()[:120]
        if total >= 1:
            out.update(family="dih", adapter="dih",
                       fit={"kat_dok": kat, "records_filtered": total,
                            "sample_title": sample})
        else:
            out.setdefault("fit_attempts", {})["dih_json"] = {"records_filtered": 0}
    except Exception as exc:
        out.setdefault("fit_attempts", {})["dih_json"] = {"err": repr(exc)[:120]}
    return bps, out


def main():
    data = json.loads((CAMP / "generic_census_tranche2.json").read_text())
    pool = {b: r for b, r in data.items()
            if r["family"] == "bespoke_other"
            and any("/dih" in s for s in r.get("shapes", []))}
    print(f"dih pool: {len(pool)}", flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        for bps, rec in ex.map(lambda kv: process(*kv), pool.items()):
            print(bps, rec["name"][:26], "->", rec["family"],
                  rec.get("fit", {}).get("records_filtered", ""), flush=True)
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
    print("pass 4 saved")


if __name__ == "__main__":
    main()
