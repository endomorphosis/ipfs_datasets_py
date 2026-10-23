"""Canada tranche 1, Wave A — per-town driver.

Why this exists (documented in the wave report): the single-process
builder degrades after a heavy harvest — its robots.txt fetches start
timing out at 45 s x 2 for town after town, while a fresh process
with the identical session/UA fetches the same hosts in 2-5 s, and
curl likewise. Restarting the builder restored normal behaviour
immediately (Clermont: 530 rows). The fix used here needs no adapter
change: run the existing builder as a FRESH process per town
(--only <sgc>); state.json checkpointing makes the sequence a clean
resume. Towns already `done` are skipped (the builder also skips
them). `failed_transient` towns are included — each gets a fresh
process and a fresh robots pass.

Usage: ca_wavea_driver.py [--sweep N]   (log: logs/driver.log)
Per-town guard: 90 min wall; on timeout the town is left in whatever
state the builder last checkpointed and the driver moves on.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

WAVEA = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/ca_wavea"
PY = str(Path.home() / "workspace/venvs/scraping/bin/python")
BUILDER = str(WAVEA / "scripts" / "ca_wavea_build.py")
LOG = WAVEA / "logs" / "driver.log"
PER_TOWN_TIMEOUT = 90 * 60


def dlog(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def scope_sgcs():
    sys.path.insert(0, str(WAVEA / "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("ca_wavea_build", BUILDER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return [t["sgc"] for t in m.load_scope()]


def state():
    p = WAVEA / "state" / "state.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"towns": {}}


def main():
    sweep = 1
    if "--sweep" in sys.argv:
        sweep = int(sys.argv[sys.argv.index("--sweep") + 1])
    sgcs = scope_sgcs()
    dlog(f"driver start (sweep {sweep}): scope {len(sgcs)} towns")
    for sgc in sgcs:
        st = state()
        t = st["towns"].get(sgc, {})
        if t.get("status") == "done":
            continue
        dlog(f"--- town {sgc} (prev status: {t.get('status', 'unattempted')})")
        t0 = time.time()
        try:
            r = subprocess.run([PY, BUILDER, "--only", sgc],
                               capture_output=True, text=True,
                               timeout=PER_TOWN_TIMEOUT)
            tail = (r.stdout or "").strip().splitlines()[-2:]
            dlog(f"    exit {r.returncode} in {(time.time()-t0)/60:.1f} min; " + " | ".join(tail))
            if r.returncode != 0 and r.stderr:
                dlog("    stderr tail: " + " | ".join(r.stderr.strip().splitlines()[-2:]))
        except subprocess.TimeoutExpired:
            dlog(f"    TIMEOUT after {PER_TOWN_TIMEOUT//60} min — moving on")
        time.sleep(5)
    st = state()
    done = [k for k, v in st["towns"].items() if v.get("status") == "done"]
    rows = sum(v.get("rows", 0) for v in st["towns"].values() if v.get("status") == "done")
    dlog(f"driver sweep {sweep} complete: {len(done)} towns done, {rows} wave-A rows")


if __name__ == "__main__":
    main()
