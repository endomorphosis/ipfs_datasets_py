"""Pick up to N harvest tenants from the census records.

Reads tenant_census.jsonl directly (the registry JSON is only written
when the census run completes). A pick must be: status verified, a
municipality or ward (not prefecture — tranche 1 scope is municipal),
on the d1-law system (the adapter the builders already run), with an
enumerated corpus count, not one of the five pilot cities, and not a
JIS already in the build manifest. Smallest corpora first (they finish
inside a supervision window). Writes tranche1_endpoints.json.
"""
import json
import sys
from pathlib import Path


# Generated campaign files live outside the installed package; the mapping is
# legal_scrapers/user_data_paths.py (IPFS_DATASETS_LEGAL_WORK_ROOT).
import importlib.util as _udp_util
from pathlib import Path as _udp_Path
_udp_spec = _udp_util.spec_from_file_location(
    "_legal_scrapers_user_data_paths",
    next(p for p in _udp_Path(__file__).resolve().parents if p.name == "legal_scrapers") / "user_data_paths.py",
)
_udp = _udp_util.module_from_spec(_udp_spec)
_udp_spec.loader.exec_module(_udp)
_campaign_data_file = _udp.work_mirror_path
def _campaign_source_path(path):
    return _udp.source_path_for_mirror(path, __file__)


OUT = _campaign_data_file(__file__).parent.parent
DONE_CODES = {"40130", "20201", "03201", "07201", "43100"}


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    rows = [json.loads(l) for l in
            (OUT / "tenant_census.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    man = {}
    mp = OUT / "tranche1_manifest.json"
    if mp.exists():
        man = json.loads(mp.read_text(encoding="utf-8")).get("municipalities", {})
    cands = []
    for r in rows:
        if r.get("status") != "verified":
            continue
        if r.get("kind") not in ("municipality", "ward"):
            continue
        if r.get("system") != "d1law":
            continue
        if not r.get("corpus_docs"):
            continue
        jis = r.get("jis")
        if jis in DONE_CODES or jis in man:
            continue
        cands.append(r)
    cands.sort(key=lambda r: r["corpus_docs"])
    picks = cands[:n]
    print(f"{len(cands)} eligible tenants; picks:")
    for r in picks:
        print(f"  {r['jis']} {r.get('registry_name')} "
              f"corpus={r['corpus_docs']} {r['endpoint']}")
    ep_path = OUT / "tranche1_endpoints.json"
    eps = (json.loads(ep_path.read_text(encoding="utf-8"))
           if ep_path.exists() else {})
    for r in picks:
        eps[r["jis"]] = r["endpoint"]
    ep_path.write_text(json.dumps(eps, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    print(f"tranche1_endpoints.json now has {len(eps)} entries")


if __name__ == "__main__":
    main()
