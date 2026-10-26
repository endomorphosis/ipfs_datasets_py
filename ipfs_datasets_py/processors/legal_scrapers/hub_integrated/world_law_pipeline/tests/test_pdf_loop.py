"""pdf_loop: staging alert on/off, liveness, stale-lock break, watchdog kill+retry, idempotent cycles, hourly
pdf_step skip/restart. Synthetic /tmp data, fake upload child (no network)."""
import fcntl, json, os, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE.parent / "tools"))
import pdf_loop as L  # noqa: E402
import pdf_step as P  # noqa: E402

PY = sys.executable
FAKE = r'''
import sys, os, time
from pathlib import Path
md = Path(sys.argv[1]); mode = sys.argv[2]; cnt = Path(sys.argv[3])
n = int(cnt.read_text()) + 1 if cnt.exists() else 1; cnt.write_text(str(n))
print("fake upload run", n, flush=True)
if mode == "hang" and n == 1:
    time.sleep(600)
for r in sorted(md.glob("batch_*.ready")):
    b = r.name[:-6]
    if not (md / (b + ".pushed")).exists():
        for f in md.parent.glob(b + "_*.pdf"): f.unlink()
        (md / (b + ".pushed")).write_text("{}")
'''


def mk(tmp, nbatches=2, size=1000):
    stage, state = tmp / "staging" / "pdf", tmp / "state"
    md = stage / "_manifest"; md.mkdir(parents=True); state.mkdir()
    for i in range(nbatches):
        b = f"batch_{i:04d}"
        (stage / f"{b}_x.pdf").write_bytes(b"x" * size)
        (md / f"{b}.jsonl").write_text("{}\n"); (md / f"{b}.ready").write_text("")
    return stage, state, md


def args(stage, state, md, cnt, mode="ok", extra=()):
    fake = state.parent / "fake.py"; fake.write_text(FAKE)
    return ["--state", str(state), "--staging", str(stage), "--once", "--poll", "1", "--retries", "1",
            "--upload-cmd", json.dumps([PY, str(fake), str(md), mode, str(cnt)])] + list(extra)


def test_alert_on_off():
    tmp = Path(tempfile.mkdtemp()); stage, state, md = mk(tmp, 1, 5000)
    st = L.staging_status(stage)
    assert st["ready_count"] == 1 and st["oldest_ready_age_min"] is not None
    assert L.update_alert(state, st, alert_gb=1e-6)
    a = json.loads((state / "alerts" / L.ALERT_NAME).read_text())
    assert a["ready_batches"] == ["batch_0000"] and a["staging_bytes"] > 1000 and a["first_seen_at"]
    assert not L.update_alert(state, st, alert_gb=1.0)
    assert not (state / "alerts" / L.ALERT_NAME).exists()


def test_cycle_pushes_and_idempotent():
    tmp = Path(tempfile.mkdtemp()); stage, state, md = mk(tmp, 3); cnt = tmp / "cnt"
    assert L.main(args(stage, state, md, cnt, extra=["--alert-gb", "0.000001"])) == 0
    assert L.ready_batches(stage) == [] and int(cnt.read_text()) == 1
    assert not (state / "alerts" / L.ALERT_NAME).exists()  # cleared once staging shrank below
    s = json.loads((state / "pdf_loop.status.json").read_text())
    assert s["batches_pushed"] == 3 and s["phase"] == "stopped"
    assert L.main(args(stage, state, md, cnt)) == 0  # nothing ready: no child run
    assert int(cnt.read_text()) == 1
    assert not (state / "pdf_loop.pid").exists()


def test_watchdog_kills_and_retries():
    tmp = Path(tempfile.mkdtemp()); stage, state, md = mk(tmp, 2); cnt = tmp / "cnt"
    t0 = time.time()
    L.main(args(stage, state, md, cnt, "hang", ["--stall-min", str(3 / 60)]))
    assert time.time() - t0 < 60
    assert int(cnt.read_text()) == 2 and L.ready_batches(stage) == []
    s = json.loads((state / "pdf_loop.status.json").read_text())
    assert s["last_run"]["killed"] is False and s["batches_pushed"] == 2


def test_stale_lock_broken_fresh_kept():
    tmp = Path(tempfile.mkdtemp()); state = tmp / "state"; state.mkdir()
    assert L.break_stale_upload_lock(state, 60) == "free"
    holder = subprocess.Popen([PY, "-c", (
        "import fcntl,json,os,sys,time;f=open(sys.argv[1],'a+');fcntl.flock(f,fcntl.LOCK_EX);"
        "f.truncate(0);f.write(json.dumps({'pid':os.getpid(),'started_at':sys.argv[2]}));f.flush();time.sleep(300)"),
        str(state / "pdf_upload.lock"), "2020-01-01T00:00:00Z", "upload_pdfs"])
    for _ in range(50):
        if L.upload_lock_holder(state):
            break
        time.sleep(0.1)
    assert L.break_stale_upload_lock(state, 1e12) == "held"  # not old enough
    assert L.break_stale_upload_lock(state, 60) == "broken"
    holder.wait(timeout=40)
    assert L.break_stale_upload_lock(state, 60) == "free"
    # dead holder: kernel flock is released, the stale JSON alone does not block
    (state / "pdf_upload.lock").write_text(json.dumps({"pid": 999999999, "started_at": "2020-01-01T00:00:00Z"}))
    assert L.upload_lock_holder(state) is None


def test_mem_guard_skips():
    tmp = Path(tempfile.mkdtemp()); stage, state, md = mk(tmp, 1); cnt = tmp / "cnt"
    L.main(args(stage, state, md, cnt, extra=["--min-mem-gb", "1e9"]))
    assert not cnt.exists() and L.ready_batches(stage) == ["batch_0000"]


def test_singleton_lock():
    tmp = Path(tempfile.mkdtemp()); stage, state, md = mk(tmp, 1); cnt = tmp / "cnt"
    f = open(state / "pdf_loop.lock", "a+"); fcntl.flock(f, fcntl.LOCK_EX)
    assert L.main(args(stage, state, md, cnt)) == 0 and not cnt.exists()
    f.close()


def test_loop_status_and_pdf_step_restart():
    tmp = Path(tempfile.mkdtemp()); base = tmp; stage, state, md = mk(tmp, 1, 3000)
    assert L.loop_status(state)["alive"] is False
    started = []
    out = P.loop_check(base, state, alert_gb=1e-6, starter=lambda: started.append(1) or 4242)
    assert started and out["restarted_pid"] == 4242 and out["staging_alert"]
    assert (state / "alerts" / L.DEAD_ALERT_NAME).exists() and (state / "alerts" / L.ALERT_NAME).exists()
    # a live loop (real detached process) is detected; pdf_step then does not restart and clears the dead alert
    fake = tmp / "fake.py"; fake.write_text(FAKE)
    pid = L.start_detached(state, PY, ["--staging", str(stage), "--poll", "1", "--upload-cmd",
                                       json.dumps([PY, str(fake), str(md), "ok", str(tmp / "cnt")])])
    try:
        for _ in range(100):
            if L.loop_status(state)["alive"]:
                break
            time.sleep(0.2)
        ls = L.loop_status(state)
        assert ls["alive"] and ls["pid"] == pid, ls
        out = P.loop_check(base, state, alert_gb=1e-6, starter=lambda: started.append(2) or 1)
        assert "restarted_pid" not in out and started == [1]
        assert not (state / "alerts" / L.DEAD_ALERT_NAME).exists()
        for _ in range(100):
            if not L.ready_batches(stage):
                break
            time.sleep(0.2)
        assert L.ready_batches(stage) == []
    finally:
        os.kill(pid, 15)
        for _ in range(50):
            if not L.pid_alive(pid):
                break
            time.sleep(0.2)
    assert not L.pid_alive(pid) and L.loop_status(state)["alive"] is False
    assert "stopping" in (state / "pdf_loop.log").read_text()


def test_timed_commit():
    import upload_pdfs as U

    class Api:
        def create_commit(self, **kw):
            time.sleep(kw.get("sleep", 0)); return "ok"
    assert U.timed_commit(Api(), 5, sleep=0) == "ok"
    try:
        U.timed_commit(Api(), 0.2, sleep=2); raise AssertionError("no timeout")
    except TimeoutError:
        pass


if __name__ == "__main__":
    fails = 0
    for k, fn in list(globals().items()):
        if k.startswith("test_") and callable(fn):
            try:
                fn(); print("ok  ", k)
            except Exception as e:  # noqa: BLE001
                fails += 1; import traceback; traceback.print_exc(); print("FAIL", k, e)
    print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
