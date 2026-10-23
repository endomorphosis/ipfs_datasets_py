"""063 Ashburton — one-off recovery of the Alcohol Control Bylaw 2023
from its Wayback snapshot, then the shared deepening build/publish
tail (superset-gated).

Why not nz_tranche2.py deepen063wb: that phase's exact-URL CDX
query (url=<full URL>&filter=statuscode:200) drew HTTP 503 from
archive.org twice, while the same query without the filter and in
host/path form returned the snapshot list (verified manually
2026-10-14). Latest full-PDF snapshot: 20260616160005 (digest
JXNAOQFTMNCAV7S3YRQYPH5UQJN56INA — identical to the 2023/2024
captures, i.e. the final 2023 bylaw). Live route is WAF-blocked at
robots (403 on the deepening re-check), so the archive route is
the documented fallback.
"""
import hashlib
import sys
from pathlib import Path

OUT = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "nz_pilot"
sys.path.insert(0, str(OUT))

import nz_tranche1 as T  # noqa: E402
import nz_tranche2 as T2  # noqa: E402

T.TODAY = "2026-10-14"
CODE = "063"
TS = "20260616160005"


def main():
    tm = T.load_tm()
    gate = T.ArchiveGate(tm)
    rec = T.tm_record(tm, CODE)
    name = T.REG.get(CODE, CODE)
    live_rows_before = rec.get("rows", 0)
    _fm, fentry = T.fetch_entry(CODE)
    files = list(fentry.get("files", []))
    frec = next((f for f in files if f.get("status") != "ok"), None)
    if frec is None:
        print("[063wb2] no failed file — nothing to do", flush=True)
        return
    url = frec["url"]
    final_path = OUT / frec["path"]
    sess = T.make_session()
    ok, errors = T.wb_download(gate, sess,
                               f"https://web.archive.org/web/{TS}id_/{url}",
                               final_path)
    if not ok:
        print(f"[063wb2] snapshot download failed: {errors}", flush=True)
        return
    data = final_path.read_bytes()
    frec.update({"status": "ok", "source": "wayback", "size": len(data),
                 "sha256": hashlib.sha256(data).hexdigest(),
                 "wayback_timestamp": TS, "errors": errors})
    fentry["files"] = files
    T.save_fetch_entry(CODE, fentry)
    print(f"[063wb2] recovered {len(data)}B snapshot {TS}", flush=True)
    ok_files = [f for f in files if f["status"] == "ok"]
    outcome = T2._deepen_build_publish(tm, CODE, name, rec, fentry,
                                       ok_files, 1, live_rows_before)
    print(f"[063wb2] OUTCOME {outcome}", flush=True)


if __name__ == "__main__":
    main()
