#!/usr/bin/env python3
"""Hourly PDF step (run right after `run_loop.py --once`):

  1. tools/upload_pdfs.py: push every ready staging/pdf/ batch to endomorphosis/world_law_scanned_pdfs
     (+ manifest refresh: law_repo/law_path of docs whose text row got published since);
  2. pdf_ref backfill: rebuild up to --backfill-places queued places (state/pdf_backfill_pending.txt) through
     run_loop.py --once --rebuild-places-file (run_loop takes state/run_loop.lock itself and commits in its usual
     moderate chunks; no staged files are consumed: --bot __pdf_backfill__). A place leaves the queue once its
     local metadata shows schema 1.2.0 written after this step started; the rest stay queued for the next hour.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
sys.path.insert(0, str(PIPE))
sys.path.insert(0, str(HERE))
import schema as S  # noqa: E402
import upload_pdfs as U  # noqa: E402
import pdf_loop as L  # noqa: E402

BASE = Path(os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law"))


def _meta_path(base: Path, entry: str) -> Path:
    cc, pk = entry.split("/", 1)  # queue entries are CC/place_key
    out = base / ("out_national" if S.is_national_key(pk) else "out")
    return out / S.metadata_path(cc, pk)


def rebuilt(base: Path, pk: str, since: float) -> bool:
    try:
        p = _meta_path(base, pk)
        return p.exists() and p.stat().st_mtime >= since and json.loads(p.read_text()).get(
            "schema_version") == S.SCHEMA_VERSION
    except Exception:  # noqa: BLE001
        return False


def loop_check(base: Path, state: Path, alert_gb: float = 6.0, restart: bool = True, python: str = sys.executable,
               starter=None) -> dict:
    """Staging alert (same file as pdf_loop) + pdf_loop liveness; restarts a dead loop (state/alerts/pdf_loop_dead.json
    records the death until the new loop clears it)."""
    st = L.staging_status(base / "staging" / "pdf")
    alerting = L.update_alert(state, st, alert_gb, source="pdf_step")
    ls = L.loop_status(state)
    out = {"staging_gb": st["staging_gb"], "ready_count": st["ready_count"],
           "oldest_ready_age_min": st["oldest_ready_age_min"], "staging_alert": alerting, "loop": ls}
    dp = state / "alerts" / L.DEAD_ALERT_NAME
    if ls["alive"] and dp.exists():
        dp.unlink()  # the previous hour's restart worked
    if not ls["alive"]:
        dead = {"at": L.utc_now(), "loop": ls, "staging": st}
        if restart:
            pid = (starter or (lambda: L.start_detached(state, python)))()
            time.sleep(0 if starter else 5)
            out["restarted_pid"] = pid
            dead["restarted_pid"] = pid
        L.atomic_write(state / "alerts" / L.DEAD_ALERT_NAME, json.dumps(dead, indent=1) + "\n")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=str(BASE))
    ap.add_argument("--state", default=str(BASE / "state"))
    ap.add_argument("--backfill-places", type=int, default=300, help="places rebuilt per hour (0 = no backfill)")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--alert-gb", type=float, default=6.0)
    ap.add_argument("--no-loop-restart", action="store_true", help="only report a dead pdf_loop")
    a = ap.parse_args(argv)
    base, state = Path(a.base), Path(a.state)
    t0 = time.time()
    check = loop_check(base, state, a.alert_gb, restart=not a.no_loop_restart, python=a.python)
    print("pdf_step_check " + json.dumps(check), flush=True)
    if a.no_upload:
        pass
    elif check["loop"]["alive"] or check.get("restarted_pid"):
        print("pdf_step: pdf_loop is alive; hourly upload skipped (the loop uploads)", flush=True)
    else:  # loop down and not restartable: fall back to the old hourly upload (shares state/pdf_upload.lock)
        U.main(["--base", str(base), "--state", str(state), "--refresh-manifest"])
    q = state / "pdf_backfill_pending.txt"
    pending = [k for k in (q.read_text().split() if q.exists() else []) if k]
    if not pending or a.backfill_places <= 0:
        print(json.dumps({"backfill_pending": len(pending), "backfill_run": 0}))
        return 0
    todo = pending[: a.backfill_places]
    lst = state / "pdf_backfill_current.txt"
    lst.write_text("".join(k + "\n" for k in todo))
    cmd = [a.python, str(PIPE / "run_loop.py"), "--once", "--bot", "__pdf_backfill__",
           "--rebuild-places-file", str(lst)]
    print("pdf_step: " + " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=str(PIPE))
    done = {k for k in todo if rebuilt(base, k, t0)}
    rest = [k for k in pending if k not in done]
    tmp = q.with_name("." + q.name + ".tmp")
    tmp.write_text("".join(k + "\n" for k in rest))
    tmp.replace(q)
    with open(state / "pdf_backfill_done.txt", "a") as f:
        f.write("".join(k + "\n" for k in sorted(done)))
    print(json.dumps({"run_loop_rc": rc, "backfill_run": len(todo), "backfill_done": len(done),
                      "backfill_pending": len(rest)}))
    return 0 if rc == 0 else rc


if __name__ == "__main__":
    sys.exit(main())
