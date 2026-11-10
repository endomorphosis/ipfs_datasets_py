#!/usr/bin/env python3
"""asia_latam archive queue (2026-10-30, OOM pressure): ONE archive job at a time instead of four parallel breaker
loops. Cycles ID -> JP -> BORM -> sites/ES chain; each turn = one pass of the job (resumes from its own done.tsv /
deferred_wayback.tsv checkpoint), capped at SLICE minutes (clean stop via <job>/_STOP). Exit 75 = deferred: the item
is skipped until the not_before it reported ($ARCH_NEXT_FILE), min 60 s. Exit 0 without a slice stop = finished.
Before each launch waits for the box-wide Wayback breaker (wb_wait.py). Stdlib only (small RSS).
Stop: touch _archive_work/_STOP_queue (the running job is stopped cleanly first). State: _archive_work/_queue_state.json"""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import fcntl, json, os, subprocess, sys, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam/_archive_work"))
LOGD = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam/_logs/archive"))
PY = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/venv/bin/python")
QSTOP, STATE = WORK / "_STOP_queue", WORK / "_queue_state.json"
SLICE = int(os.environ.get("ARCH_QUEUE_SLICE_MIN", "45")) * 60
# (name, job dirs whose _STOP stops it, argv, chain group: only the first unfinished step of a group is eligible)
ITEMS = [
    ("id_bpk", ["ID_bpk_kabkota"], ["id_bpk.py", "--no-cc"], None),
    ("jp_arch", ["JP_reiki_archive"], ["jp_arch.py", "--flush-secs", "1800"], None),
    ("borm_arch", ["ES_borm_archive"], ["borm_arch.py", "--cc"], None),
    ("w3f_sites_auza", ["SITES_archive_au", "SITES_archive_za"], ["sites_arch.py", "--targets", "au,za"], "w3f"),
    ("w3f_sede300", ["ES_sede_archive"], ["sede_arch.py", "--max-hosts", "300"], "w3f"),
    ("w3f_es1500", ["ES_bop_archive"], ["es_arch.py", "--max-fetch", "1500"], "w3f"),
    ("w3f_es_robots", ["ES_bop_archive", "ES_bop_archive_robots"], ["es_arch.py", "--set", "robots", "--max-kb", "3000"], "w3f"),
    ("w3f_es_rest", ["ES_bop_archive"], ["es_arch.py"], "w3f"),
    ("w3f_sede_rest", ["ES_sede_archive"], ["sede_arch.py"], "w3f"),
]


def log(m):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {m}", flush=True)


def save(st):
    t = STATE.with_suffix(".tmp"); t.write_text(json.dumps(st, indent=1)); os.replace(t, STATE)


def main():
    lk = open(WORK / "_queue.lock", "w")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("arch_queue already running")
    lk.write(str(os.getpid())); lk.flush()
    QSTOP.unlink(missing_ok=True)
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    if "w3f_done_upto" not in st:   # worker3f had already passed... nothing: it was on its first step (sites au,za)
        st["w3f_done_upto"] = 0
    env = dict(os.environ, ARCHIVE_LANE="asia_latam", MALLOC_ARENA_MAX="2", PYTHONUNBUFFERED="1")
    turn = st.get("turn", 0)
    while not QSTOP.exists():
        now = time.time()
        elig = []
        first_w3f = next((it for it in ITEMS if it[3] == "w3f" and not st.get(it[0], {}).get("finished")), None)
        for it in ITEMS:
            s = st.setdefault(it[0], {})
            if s.get("finished") or (it[3] == "w3f" and it is not first_w3f):
                continue
            elig.append(it)
        if not elig:
            log("all items finished"); break
        ready = [it for it in elig if st[it[0]].get("not_before", 0) <= now]
        if not ready:
            nb = min(st[it[0]].get("not_before", 0) for it in elig)
            wait = max(60, nb - now)
            log(f"all items deferred -> sleeping {int(wait)}s")
            end = now + wait
            while time.time() < end and not QSTOP.exists():
                time.sleep(10)
            continue
        # round-robin from the last position
        order = [it for it in ITEMS if it in ready]
        it = min(order, key=lambda x: (ITEMS.index(x) - turn) % len(ITEMS))
        turn = (ITEMS.index(it) + 1) % len(ITEMS); st["turn"] = turn
        name, dirs, argv, _ = it
        stops = [str(WORK / d / "_STOP") for d in dirs]
        w = subprocess.run([PY, "-u", "wb_wait.py", str(QSTOP)], cwd=HERE, env=env)
        if w.returncode == 3 or QSTOP.exists():
            break
        nf = WORK / f"_queue_next_{name}"
        nf.unlink(missing_ok=True)
        lf = LOGD / f"{name}_{datetime.now():%Y%m%d_%H%M}.log"
        log(f"start {name} (slice {SLICE//60} min) log={lf.name}")
        t0 = time.time()
        with open(lf, "a") as fh:
            p = subprocess.Popen(["nice", "-n", "10", PY, "-u", *argv], cwd=HERE, env=dict(env, ARCH_NEXT_FILE=str(nf)),
                                 stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            st[name]["pid"] = p.pid; save(st)
            sliced = False
            while p.poll() is None:
                if not sliced and (time.time() - t0 > SLICE or QSTOP.exists()):
                    sliced = True
                    for s in stops:
                        Path(s).touch()
                    log(f"{name}: {'queue stop' if QSTOP.exists() else 'slice over'} -> _STOP")
                time.sleep(5)
        rc = p.returncode
        s = st[name]; s.update(last_rc=rc, last_end=time.time(), last_secs=int(time.time() - t0))
        if rc == 75:
            try:
                nb = float(nf.read_text() or 0)
            except (OSError, ValueError):
                nb = 0
            s["not_before"] = max(nb, time.time() + 60)
            log(f"{name}: rc=75 deferred -> not before {datetime.fromtimestamp(s['not_before']):%H:%M:%S}")
        elif rc == 0 and not sliced:
            s["finished"] = True; log(f"{name}: finished (rc 0)")
        elif rc == 0:
            s["not_before"] = 0; log(f"{name}: sliced at a clean point")
        else:
            s["not_before"] = time.time() + 600; log(f"{name}: rc={rc} -> retry in 10 min")
        nf.unlink(missing_ok=True)
        save(st)
    log("queue stop")


if __name__ == "__main__":
    main()
