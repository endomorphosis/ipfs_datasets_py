"""Tranche-3 bespoke_other mini-census: shape-guided adapter fits for
the 94 bespoke units (Dairi 1210 first), recording the cluster outcome
per unit to id_campaign_tranche3_clusters.json. Enumeration only —
fits are harvested separately with harvest3.drive3.

Fit order per unit is guided by the tranche-2 census record (link
shapes + markers); the fallback is harvest.generic_probe (all known
routes). Robots-excluded units are not in the bespoke list and are
never touched.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

WS = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
CAMP = WS / "id_campaign"
sys.path.insert(0, str(CAMP))
import harvest as H  # noqa: E402
import harvest3 as H3  # noqa: E402

CLUSTERS_PATH = CAMP / "id_campaign_tranche3_clusters.json"
T2_CLUSTERS = json.loads((CAMP / "id_campaign_tranche2_clusters.json").read_text())
CENSUS = H3.CENSUS
REG = H3.REG

BESPOKE = T2_CLUSTERS["clusters"]["bespoke_other"]
BESPOKE = ["1210"] + [b for b in BESPOKE if b != "1210"]


def guided_adapters(bps):
    rec = CENSUS.get(bps, {})
    shapes = " ".join(rec.get("shapes", []))
    markers = " ".join(rec.get("markers", []))
    out = []
    if "/detail/peraturan/" in shapes:
        out.append("slug_detail_deep")
    if "wp" in markers or "/category/" in shapes:
        out.append("wordpress")
    if "produkHukum" in markers or "/produkHukum" in shapes:
        out.append("produkhukum")
    if "/dokumen/view" in shapes:
        out.append("dokumen_view")
    if "/dih/" in shapes:
        out.append("dih")
    if "/inventarisasi-hukum/" in shapes:
        out.append("inventarisasi")
    if "/dokumen/peraturan-daerah" in shapes:
        out.append("dokumen_view_perda")
    return out


def census_one(bps):
    reg = REG.get(bps, {})
    unit = dict(bps=bps, name=reg.get("name", bps),
                host=reg.get("best_host", ""), adapter="")
    sess = H.PoliteSession()
    base = f'https://{unit["host"]}'
    rec = {"bps": bps, "name": unit["name"], "host": unit["host"],
           "family": None, "adapter": None, "n_candidates": 0, "tried": []}
    try:
        if H.robots_blocked(sess, base, ["/dokumen", "/peraturan", "/produk",
                                         "/category", "/common", "/dih"]):
            rec["family"] = "robots_blocked"
            return rec
        for adapter in guided_adapters(bps):
            rec["tried"].append(adapter)
            try:
                cands = H.ENUMERATORS[adapter](sess, base, dict(unit))
            except Exception as e:
                rec["tried"][-1] = f"{adapter}: {type(e).__name__}"
                continue
            if cands:
                rec.update(family=adapter, adapter=adapter,
                           n_candidates=len(cands))
                return rec
        rec["tried"].append("generic_probe")
        try:
            adapter, cands, census = H.generic_probe(sess, base, dict(unit))
            rec["generic_census"] = census
            if adapter:
                rec.update(family=adapter, adapter=adapter,
                           n_candidates=len(cands))
                return rec
        except Exception as e:
            rec["generic_error"] = repr(e)[:160]
        rec["family"] = "bespoke_unresolved"
        return rec
    except Exception as e:
        rec["family"] = "error"
        rec["error"] = repr(e)[:200]
        return rec


def main():
    only = sys.argv[1].split(",") if len(sys.argv) > 1 else BESPOKE
    done = {}
    if CLUSTERS_PATH.exists():
        done = json.loads(CLUSTERS_PATH.read_text())
    todo = [b for b in only if b not in done]
    print(f"bespoke census: {len(todo)} to probe ({len(done)} done)", flush=True)
    workers = int(os.environ.get("ID_WORKERS", "6"))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for rec in ex.map(census_one, todo):
            done[rec["bps"]] = rec
            CLUSTERS_PATH.write_text(json.dumps(done, indent=1,
                                                ensure_ascii=False))
            print(json.dumps({k: rec.get(k) for k in
                              ("bps", "family", "adapter", "n_candidates")},
                             ensure_ascii=False), flush=True)
    print("bespoke census: done", flush=True)


if __name__ == "__main__":
    main()
