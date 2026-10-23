#!/usr/bin/env python3
"""Persistent waiter for national archive targets with Wayback-deferred items (deferred_wayback.tsv).

Loop: wait until the box-wide Wayback breaker has been CLOSED for STABLE_SECS (default 15 min) in a row
(closed-since = breaker closed_at; any reopen resets it), then run targets that still have deferred items
one at a time (run_archive.py T --deferred-only under prlimit --as 600 MiB, nice 10, ARCHIVE_LANE=national).
If the breaker reopens, stop launching and wait again. Exit when every deferred_wayback.tsv is empty.
Never probes: it only reads breaker_status(); probing stays with the breaker (<= 1 per 30 min box-wide).
Single instance (flock on wayback_resume_loop.lock); stateless/resumable (state = the tsv files).

2026-10-18 (throttle deferral in the shared fetcher): 429/5xx no longer open the breaker; they set a box-wide
per-host cool-down (archive/deferral.py) and runners requeue items and exit 75 after a deferral streak. So before
each launch this loop also waits until web.archive.org is out of its cool-down (not_before), and it reruns a full
pass (without --deferred-only) for targets whose runner left <TARGET>/resume_full.flag. SIGTERM: forwards SIGTERM
to the running child (which checkpoints: flush + done.tsv + deferred list), waits for it, then exits.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import fcntl, json, logging, os, signal, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from archive import ratelimit as rl  # noqa: E402
from archive import deferral  # noqa: E402
from specs import SPECS  # noqa: E402

WORK = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national/_archive_work"))
L = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national/_logs/archive"))
PY = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/venv/bin/python")
STABLE = float(os.environ.get("STABLE_SECS", 900)); POLL = float(os.environ.get("POLL_SECS", 60))
AS = os.environ.get("AS", "629145600"); MIN_FREE_MB = int(os.environ.get("MIN_FREE_MB", 1500))
LOCK = L / "wayback_resume_loop.lock"; PIDF = L / "wayback_resume_loop.pid"; STATE = L / "wayback_resume_loop.state.json"
log = logging.getLogger("wb_resume_loop")
WB_HOST = "web.archive.org"
COOL_PAD = float(os.environ.get("COOL_PAD_SECS", 15))   # start a little after not_before
_STOP = False
_CHILD = None
_NOT_DUE_LOGGED = {}
NOT_DUE_MAX = float(os.environ.get("NOT_DUE_MAX_SECS", 3600))   # re-check at least hourly (breaker / new flags)


def _on_term(*_):
    global _STOP
    _STOP = True
    if _CHILD is not None and _CHILD.poll() is None:
        log.info("SIGTERM: stopping child pid %d at a checkpoint", _CHILD.pid)
        _CHILD.send_signal(signal.SIGTERM)


def full_flags():
    """Targets whose last full run was cut short by throttling (resume_full.flag)."""
    return {p.parent.name for p in WORK.glob("*/resume_full.flag")}


def cooldown_left():
    return deferral.host_cooldown(WB_HOST)


def wait_cooldown():
    """Sleep out web.archive.org's box-wide cool-down (respects not_before). False if stopped."""
    left = cooldown_left()
    if left <= 0:
        return True
    log.info("%s cooling down %.0fs (not_before %s); waiting before launching", WB_HOST, left,
             time.strftime("%T", time.localtime(time.time() + left)))
    while not _STOP and (left := cooldown_left()) > 0:
        save_state(phase="cooldown", host=WB_HOST, cooldown_left=round(left))
        time.sleep(min(left + COOL_PAD, POLL))
    return not _STOP


def due_info(t):
    """(deferred keys, keys due now, earliest future not_before or None) for target t, from the LAST
    deferred_wayback.tsv line per key (column 4 = not_before epoch; missing/0 = due now)."""
    p = WORK / t / "deferred_wayback.tsv"
    last = {}
    if p.exists():
        with p.open() as f:
            for l in f:
                parts = l.rstrip("\n").split("\t")
                if parts[0]:
                    try:
                        last[parts[0]] = float(parts[3]) if len(parts) >= 4 and parts[3] else 0.0
                    except ValueError:
                        last[parts[0]] = 0.0
    now = time.time()
    fut = [nb for nb in last.values() if nb > now]
    return len(last), len(last) - len(fut), (min(fut) if fut else None)


def sleep_until(t_wake, phase, **kw):
    """Sleep (in POLL chunks, so SIGTERM is honoured) until t_wake. False if stopped."""
    while not _STOP and (left := t_wake - time.time()) > 0:
        save_state(phase=phase, wake=time.strftime("%T", time.localtime(t_wake)), **kw)
        time.sleep(min(left, POLL))
    return not _STOP


def deferred_counts():
    out = {}
    for p in sorted(WORK.glob("*/deferred_wayback.tsv")):
        t = p.parent.name
        keys = {l.split("\t", 1)[0] for l in p.open() if l.strip()}
        if keys:
            out[t] = len(keys)
    return out


def closed_for():
    b = rl.breaker_status()
    if b.get("state") == "open":
        return None, b
    since = max(float(b.get("closed_at") or 0), float(b.get("opened_at") or 0))
    return time.time() - since, b


def mem_ok():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable"):
            return int(l.split()[1]) // 1024 >= MIN_FREE_MB
    return True


def save_state(**kw):
    kw["pid"] = os.getpid(); kw["t"] = time.strftime("%F %T")
    STATE.write_text(json.dumps(kw, indent=1))


def main():
    global _CHILD
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    lf = open(LOCK, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info("another wayback_resume_loop holds %s; exiting", LOCK); return 0
    PIDF.write_text(str(os.getpid()))
    env = dict(os.environ, PYTHONUNBUFFERED="1", ARCHIVE_LANE="national", MALLOC_ARENA_MAX="2")
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    log.info("start pid %d stable=%.0fs poll=%.0fs (waits out %s cool-down)", os.getpid(), STABLE, POLL, WB_HOST)
    last_wait_log = 0
    while True:
        if _STOP:
            log.info("stopped (SIGTERM)"); save_state(phase="stopped"); return 0
        dc = deferred_counts()
        for t in full_flags():
            dc.setdefault(t, 0)
        dc = {t: n for t, n in dc.items() if t in SPECS and not SPECS[t].get("disabled")}
        if not dc:
            log.info("DONE: no deferred_wayback items left in any national target"); save_state(phase="done")
            return 0
        cf, b = closed_for()
        if cf is not None and cf >= STABLE and cooldown_left() > 0:
            if not wait_cooldown():
                continue
            cf, b = closed_for()
        if cf is None or cf < STABLE:
            save_state(phase="waiting", breaker=b.get("state"), closed_for=cf, deferred=dc)
            if time.time() - last_wait_log > 900:
                log.info("waiting: breaker %s%s; deferred %s (total %d)", b.get("state"),
                         f" closed {cf/60:.1f} min" if cf is not None else f", next probe in {b.get('next_probe_in', 0)/60:.0f} min",
                         dc, sum(dc.values()))
                last_wait_log = time.time()
            time.sleep(POLL); continue
        log.info("breaker closed %.1f min (>= %.0f): running %d targets: %s", cf / 60, STABLE / 60, len(dc), dc)
        flags = full_flags()
        launched, not_due = 0, []
        for t in sorted(dc, key=dc.get):
            if _STOP:
                break
            if not wait_cooldown():
                break
            cf, b = closed_for()
            if cf is None:
                log.warning("breaker reopened; stop launching, back to waiting"); break
            while not mem_ok() and not _STOP:
                time.sleep(30)
            if _STOP:
                break
            full = t in flags
            if not full:
                tot, due, nxt = due_info(t)
                if due == 0 and nxt is not None:
                    # every deferred item of t has a future not_before: don't launch a runner just to skip them
                    not_due.append(nxt)
                    if _NOT_DUE_LOGGED.get(t) != round(nxt):
                        log.info("target %s: %d deferred, none due before %s; not launching", t, tot,
                                 time.strftime("%T", time.localtime(nxt)))
                        _NOT_DUE_LOGGED[t] = round(nxt)
                    continue
            launched += 1
            save_state(phase="running", target=t, mode="full" if full else "deferred-only", deferred=dc)
            cmd = ["prlimit", f"--as={AS}", "nice", "-n", "10", PY, "run_archive.py", t, "--chunk", "200"]
            if not full:
                cmd.insert(cmd.index(t) + 1, "--deferred-only")
            with open(L / f"deferred_{t}.log", "a") as lg:
                _CHILD = subprocess.Popen(cmd, cwd=HERE, env=env, stdout=lg, stderr=lg)
                while True:
                    try:
                        rc = _CHILD.wait(); break
                    except InterruptedError:
                        continue
                _CHILD = None
            left = deferred_counts().get(t, 0)
            log.info("target %s (%s) rc=%d deferred %d -> %d%s", t, "full" if full else "deferred-only", rc,
                     dc[t], left, "; host cooling down" if cooldown_left() > 0 else "")
        last_wait_log = 0
        if not launched and not_due and not _STOP:
            # nothing due anywhere: sleep until the earliest not_before (at least POLL, at most NOT_DUE_MAX)
            wake = min(max(min(not_due) + COOL_PAD, time.time() + POLL), time.time() + NOT_DUE_MAX)
            log.info("no deferred item due in any target; sleeping until %s", time.strftime("%T", time.localtime(wake)))
            sleep_until(wake, "not_due", deferred=dc)
            continue
        time.sleep(POLL)


if __name__ == "__main__":
    sys.exit(main())
