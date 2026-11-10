"""Post-pass cleanup for the Aceh Qanun run:
1. Drop aceh-state entries whose staged parquet carries resolver-junk
   titles ('Status Berlaku ...' metadata strings) — those units were
   harvested by the pre-title_locked code and must be re-run.
2. Drop entries that failed purely on transport (ReadTimeout /
   connection errors) so a retry sweep re-attempts them.
Prints what it dropped. Staged parquets of dropped units are removed
so a stale file can never be published."""
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq


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


C = _campaign_data_file(__file__).parent
STATE = C / "id_campaign_tranche3_aceh_state.json"
STAGE = C / "staging"

s = json.load(open(STATE))
dropped = []
for bps, v in list(s.items()):
    reason = None
    if v.get("status") == "staged":
        p = STAGE / f"{bps}_html.parquet"
        if p.exists():
            titles = set(pq.read_table(p, columns=["title"])
                         .column("title").to_pylist())
            if any("Status Berlaku" in (t or "") for t in titles):
                reason = "junk resolver titles (pre-title_locked code)"
    elif v.get("status") == "failed":
        errs = " ".join(v.get("errors") or [])
        if "ReadTimeout" in errs or "ConnectionError" in errs \
                or "ProxyError" in errs or "ConnectTimeout" in errs:
            reason = "transport failure (retry)"
    if reason:
        dropped.append((bps, v.get("status"), reason))
        del s[bps]
        pq_file = STAGE / f"{bps}_html.parquet"
        if pq_file.exists():
            pq_file.unlink()
json.dump(s, open(STATE, "w"), ensure_ascii=False, indent=1)
print(f"kept {len(s)} entries; dropped {len(dropped)}:")
for d in dropped:
    print(" ", d)
