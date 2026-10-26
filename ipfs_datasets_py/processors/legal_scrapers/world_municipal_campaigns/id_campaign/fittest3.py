"""Tranche-3 family fit-test: run a named enumerator against a BPS list
and report candidate counts + samples. Read-only (enumeration only)."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CAMP = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "id_campaign"
sys.path.insert(0, str(CAMP))
import harvest as H  # noqa: E402
import harvest3  # noqa: E402  (registers the new enumerators)

REG = harvest3.REG


def fit(bps, adapter):
    reg = REG.get(bps, {})
    unit = dict(bps=bps, name=reg.get("name", bps),
                host=reg.get("best_host", ""), adapter=adapter)
    sess = H.PoliteSession()
    base = f'https://{unit["host"]}'
    try:
        cands = H.ENUMERATORS[adapter](sess, base, unit)
        sample = [(c.get("tahun"), c.get("nomor"), (c.get("title") or "")[:60],
                   c.get("detail_url", "")[:90]) for c in list(cands.values())[:3]]
        return bps, dict(adapter=adapter, n=len(cands), sample=sample,
                         host=unit["host"])
    except Exception as e:
        return bps, dict(adapter=adapter, error=repr(e)[:200], host=unit["host"])


if __name__ == "__main__":
    adapter = sys.argv[1]
    bps_list = sys.argv[2].split(",")
    with ThreadPoolExecutor(max_workers=4) as ex:
        for bps, res in ex.map(lambda b: fit(b, adapter), bps_list):
            print(bps, json.dumps(res, ensure_ascii=False), flush=True)
