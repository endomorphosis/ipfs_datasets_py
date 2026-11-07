#!/usr/bin/env python3
"""Lightweight lane supervisor (asia_latam). Stdlib only, ~15 MB.

* Adopts already-running jobs by cmdline signature; launches nothing while a job is alive.
* When a job is gone: relaunch from its own checkpoint (every job here is resumable) through sv_wrap.sh,
  which records the exit code in _state/supervisor/<job>.exit. exit 0 => job finished, never relaunched.
  Exit != 0 / killed (OOM = 137/-9) => relaunch with backoff, max MAX_PER_HOUR per job, and only when
  MemAvailable >= MIN_AVAIL_MB (otherwise wait - relaunching into an OOM storm just feeds the killer).
* Every 5 min appends a memory-trend row to _logs/mem_trend.csv (box MemAvailable, lane RSS, top consumers).
* Kernel OOM kills seen in dmesg are appended to _logs/oom_events.log (dmesg ring buffer wraps quickly).
Jobs: common/supervisor_jobs.json  [{"name","cwd","cmd":[...],"sig":"substring of cmdline","log":"prefix"}]
Round-robin (2026-10-30, OOM pressure): jobs with "rr": true run ONE at a time, each for a slice, then are stopped
cleanly and the next resumes from checkpoint (rr_tick).
Stop: touch _state/supervisor/STOP  (or kill the supervisor; children are setsid and keep running).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, re, subprocess, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/asia_latam"))
SV = STAGE / "_state" / "supervisor"; LOGS = STAGE / "_logs"
JOBS = HERE / "supervisor_jobs.json"; WRAP = HERE / "sv_wrap.sh"
MAX_PER_HOUR, MIN_AVAIL_MB, POLL = 4, 900, 60
RR_SLICE_MIN = int(os.environ.get("SV_RR_SLICE_MIN", "60"))   # round-robin slice for jobs with "rr": true
RR_GRACE_S = 180                                               # SIGINT -> SIGTERM after this


EXTRA_STOP_MB, EXTRA_RESUME_MB = 2048, 3072   # lane "b" (one extra gazette worker, 2026-11-03): stop below / relaunch above


def rr_tick(jobs, st, ps, lane="a"):
    """Round-robin for memory-heavy jobs ("rr": true): exactly ONE runs at a time, for its slice ("slice_min",
    default RR_SLICE_MIN) or until it exits; then it is stopped cleanly (SIGINT, so finally/flush run; SIGTERM after
    RR_GRACE_S - checkpoints are written atomically, so at most the unflushed tail is redone) and the next job
    resumes from its own checkpoint. exit 0 = finished (dropped from the rotation)."""
    import signal
    # lane "b": ONE extra concurrent worker over the jobs marked "rr_extra" (ES BOP / MX gazettes). Each lane ignores the
    # job the other lane is running (never two copies of one job); lane b is memory-guarded (EXTRA_STOP/RESUME_MB).
    other = st.get("_rr_b" if lane == "a" else "_rr", {}).get("cur")
    rr = [j for j in jobs if j.get("rr") and not j.get("disabled") and (lane == "a" or j.get("rr_extra"))
          and j["name"] != other
          and st.setdefault(j["name"], {"restarts": [], "status": "running"})["status"] not in ("finished", "disabled")]
    R = st.setdefault("_rr" if lane == "a" else "_rr_b", {"cur": None, "started": 0, "stopping": 0})
    if lane == "b" and R.get("cur") and not any(j["name"] == R["cur"] for j in rr):
        R.update(cur=None, stopping=0)
    if not rr:
        return
    if lane == "b":
        ma = mem_avail()
        cur_alive = R["cur"] and any(alive(j, ps) for j in rr if j["name"] == R["cur"])
        if cur_alive and ma < EXTRA_STOP_MB and not R["stopping"]:
            R["stopping"] = time.time(); R["mem_paused"] = True
            for j in rr:
                if j["name"] == R["cur"]:
                    for p in alive(j, ps):
                        try:
                            os.kill(p[0], signal.SIGINT)
                        except OSError:
                            pass
            log(f"rr[b]: MemAvailable={ma}MB < {EXTRA_STOP_MB} -> {R['cur']} stopped (SIGINT, resumes from checkpoint later)")
            return
        if not cur_alive and ma < EXTRA_RESUME_MB:
            if not R.get("mem_paused"):
                R["mem_paused"] = True; log(f"rr[b]: paused, MemAvailable={ma}MB < {EXTRA_RESUME_MB}")
            if R["cur"]:
                R.update(cur=None, stopping=0)
            return
        if not cur_alive and R.get("mem_paused"):
            R["mem_paused"] = False; log(f"rr[b]: MemAvailable={ma}MB >= {EXTRA_RESUME_MB} -> resuming")
    alive_rr = {j["name"]: alive(j, ps) for j in rr}
    running = [n for n, a in alive_rr.items() if a]
    # more than one alive (adopted at start): keep the current one (or the first), stop the others cleanly
    keep = R["cur"] if R["cur"] in running else (running[0] if running else None)
    for n in running:
        if n != keep:
            for p in alive_rr[n]:
                try:
                    os.kill(p[0], signal.SIGINT)
                except OSError:
                    pass
            log(f"rr{'' if lane == 'a' else '[b]'}: {n} stopped (SIGINT) - only one heavy job at a time")
    if keep and R["cur"] != keep:
        R.update(cur=keep, started=time.time(), stopping=0); log(f"rr{'' if lane == 'a' else '[b]'}: adopted {keep} as current")
    cur = R["cur"]
    if cur in running:
        job = next(j for j in rr if j["name"] == cur)
        sl = job.get("slice_min", RR_SLICE_MIN) * 60
        if not R["stopping"] and time.time() - R["started"] >= sl:
            R["stopping"] = time.time()
            for p in alive_rr[cur]:
                try:
                    os.kill(p[0], signal.SIGINT)
                except OSError:
                    pass
            log(f"rr{'' if lane == 'a' else '[b]'}: {cur} slice over ({sl//60} min) -> SIGINT")
        elif R["stopping"] and time.time() - R["stopping"] > RR_GRACE_S:
            for p in alive_rr[cur]:
                try:
                    os.kill(p[0], signal.SIGTERM)
                except OSError:
                    pass
            log(f"rr{'' if lane == 'a' else '[b]'}: {cur} still alive after {RR_GRACE_S}s -> SIGTERM")
            R["stopping"] = time.time() + 3600   # don't repeat every poll
        return
    if len(running) > 1 or (running and running[0] != cur):
        return   # wait for the extra ones to exit
    # nothing heavy running -> record the previous job's exit, pick the next one
    if cur:
        ef = SV / f"{cur}.exit"
        code = ef.read_text().strip() if ef.exists() else None
        cj = next((j for j in rr if j["name"] == cur), {})
        if code == "0" and not R["stopping"] and cj.get("rr_repeat_hours"):
            st[cur]["next_due"] = time.time() + cj["rr_repeat_hours"] * 3600
            log(f"rr{'' if lane == 'a' else '[b]'}: {cur} pass done (exit 0) -> next due in {cj['rr_repeat_hours']} h")
        elif code == "0" and not R["stopping"]:
            st[cur]["status"] = "finished"; log(f"rr{'' if lane == 'a' else '[b]'}: {cur} finished (exit 0) -> out of the rotation")
        else:
            log(f"rr{'' if lane == 'a' else '[b]'}: {cur} ended (exit={code}{', slice stop' if R['stopping'] else ''})")
    names = [j["name"] for j in rr if st[j["name"]]["status"] not in ("finished", "disabled")
             and st[j["name"]].get("next_due", 0) <= time.time()]
    if not names:
        R.update(cur=None); return
    nxt = names[(names.index(cur) + 1) % len(names)] if cur in names else names[0]
    ma = mem_avail()
    if ma < MIN_AVAIL_MB:
        log(f"rr{'' if lane == 'a' else '[b]'}: next={nxt} waits, MemAvailable={ma}MB < {MIN_AVAIL_MB}"); R.update(cur=None, stopping=0); return
    job = next(j for j in rr if j["name"] == nxt)
    ef = SV / f"{nxt}.exit"
    if ef.exists():
        ef.unlink()
    lf = launch(job)
    R.update(cur=nxt, started=time.time(), stopping=0)
    log(f"rr{'' if lane == 'a' else '[b]'}: {nxt} started from checkpoint (slice {job.get('slice_min', RR_SLICE_MIN)} min), log={lf.name}")
LANE = (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/asia_latam")


def log(msg):
    with open(LOGS / "supervisor.log", "a") as fh:
        fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def procs():
    out = []
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            cmd = open(f"/proc/{p}/cmdline", "rb").read().replace(b"\0", b" ").decode("utf8", "ignore").strip()
            if not cmd:
                continue
            rss = 0
            for ln in open(f"/proc/{p}/status"):
                if ln.startswith("VmRSS:"):
                    rss = int(ln.split()[1]) // 1024
            cwd = os.readlink(f"/proc/{p}/cwd")
            out.append((int(p), cmd, rss, cwd))
        except (OSError, ValueError):
            pass
    return out


def mem_avail():
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable:"):
            return int(ln.split()[1]) // 1024
    return 0


def alive(job, ps):
    return [p for p in ps if job["sig"] in p[1] and p[3].startswith(job["cwd"]) and "sv_wrap.sh" not in p[1]
            and "supervisor.py" not in p[1]]


def launch(job):
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    lf = LOGS / f"{job['name']}_{ts}.log"  # per-job name: avoids interleaving when several jobs relaunch in the same minute
    env = dict(os.environ, MALLOC_ARENA_MAX="2", PYTHONUNBUFFERED="1")
    subprocess.Popen(["setsid", "nohup", "bash", str(WRAP), str(SV / f"{job['name']}.exit"), str(lf), *job["cmd"]],
                     cwd=job["cwd"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return lf


def oom_scan(seen):
    try:
        out = subprocess.run(["dmesg"], capture_output=True, text=True, timeout=20).stdout
    except Exception:  # noqa: BLE001
        return
    up = float(open("/proc/uptime").read().split()[0]); now = time.time()
    for m in re.finditer(r"\[\s*([\d.]+)\] Out of memory: Killed process (\d+) \(([^)]+)\) .*?anon-rss:(\d+)kB", out):
        key = m.group(1)
        if key in seen:
            continue
        seen.add(key)
        when = datetime.fromtimestamp(now - (up - float(m.group(1))))
        with open(LOGS / "oom_events.log", "a") as fh:
            fh.write(f"{when:%Y-%m-%d %H:%M:%S} killed pid={m.group(2)} name={m.group(3)} anon_rss_mb={int(m.group(4))//1024}\n")


def main():
    SV.mkdir(parents=True, exist_ok=True)
    st_p = SV / "state.json"
    st = json.loads(st_p.read_text()) if st_p.exists() else {}
    seen, last_mem = set(st.get("oom_seen", [])), 0
    log(f"supervisor start pid={os.getpid()}")
    while not (SV / "STOP").exists():
        jobs = json.loads(JOBS.read_text())
        ps = procs()
        rr_tick(jobs, st, ps)
        rr_tick(jobs, st, procs(), lane="b")
        for job in jobs:
            js = st.setdefault(job["name"], {"restarts": [], "status": "running"})
            if js["status"] in ("finished", "disabled") or job.get("disabled") or job.get("rr"):
                continue
            a = alive(job, ps)
            if a:
                js["pid"] = a[0][0]; js.pop("gone_since", None)
                continue
            ef = SV / f"{job['name']}.exit"
            code = ef.read_text().strip() if ef.exists() else None
            if code == "0":
                js["status"] = "finished"; log(f"{job['name']} finished (exit 0)"); continue
            js.setdefault("gone_since", time.time())
            js["restarts"] = [t for t in js["restarts"] if time.time() - t < 3600]
            if len(js["restarts"]) >= MAX_PER_HOUR:
                continue
            if js["restarts"] and time.time() - js["restarts"][-1] < 120 * len(js["restarts"]):
                continue
            ma = mem_avail()
            if ma < MIN_AVAIL_MB:
                log(f"{job['name']} down (exit={code}) but MemAvailable={ma}MB < {MIN_AVAIL_MB} -> wait"); continue
            if ef.exists():
                ef.unlink()
            lf = launch(job); js["restarts"].append(time.time())
            log(f"{job['name']} was down (last pid={js.get('pid')} exit={code}) -> relaunched from checkpoint, log={lf.name}")
        if time.time() - last_mem >= 300:
            last_mem = time.time(); oom_scan(seen)
            lane = [p for p in ps if p[3].startswith(LANE)]
            top = sorted(ps, key=lambda p: -p[2])[:5]
            new = not (LOGS / "mem_trend.csv").exists()
            with open(LOGS / "mem_trend.csv", "a") as fh:
                if new:
                    fh.write("time,mem_available_mb,lane_rss_mb,lane_procs,top5\n")
                fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S},{mem_avail()},{sum(p[2] for p in lane)},{len(lane)},"
                         f"\"{'; '.join(f'{p[2]}MB {p[1][:50]}' for p in top)}\"\n")
        st["oom_seen"] = sorted(seen)[-200:]
        t = SV / ".state.tmp"; t.write_text(json.dumps(st)); os.replace(t, st_p)
        time.sleep(POLL)
    log("supervisor stop (STOP file)")


if __name__ == "__main__":
    main()
