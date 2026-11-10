"""batch_alloc: atomic collision-safe batch numbering; stale .pushed detection + supersede; pdf_loop/upload_pdfs
treat collided batches as ready; flag_collisions alert. Synthetic /tmp data, no network."""
import json, os, sys, tempfile, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE.parent / "tools"))
import batch_alloc as BA  # noqa: E402
import pdf_loop as L  # noqa: E402
import upload_pdfs as U  # noqa: E402


def t_max_counts_all_suffixes():
    with tempfile.TemporaryDirectory() as d:
        md = Path(d)
        (md / "batch_0007.pushed").write_text("{}")
        (md / "batch_0003.jsonl").write_text("")
        (md / "batch_0009.retry.json").write_text("{}")
        (md / "batch_0010.jsonl.tmp").write_text("")
        assert BA.max_on_disk(md) == 10
        assert BA.write_batch(md, [{"a": 1}]) == 11
        assert BA.max_on_disk(Path(d) / "nope", floor=272) == 272
        assert BA.write_batch(md, [{"a": 1}], floor=272) == 273


def t_write_is_complete_and_exclusive():
    with tempfile.TemporaryDirectory() as d:
        md = Path(d)
        n = BA.write_batch(md, [{"x": i} for i in range(3)])
        assert (md / f"batch_{n:04d}.ready").exists() and not (md / f"batch_{n:04d}.jsonl.tmp").exists()
        assert BA.manifest_row_count(md / f"batch_{n:04d}.jsonl") == 3


def t_concurrent_writers_never_collide():
    with tempfile.TemporaryDirectory() as d:
        md = Path(d); got = []; lk = threading.Lock()
        def w(k):
            for j in range(10):
                n = BA.write_batch(md, [{"k": k, "j": j}])
                with lk: got.append(n)
        ts = [threading.Thread(target=w, args=(k,)) for k in range(8)]
        [t.start() for t in ts]; [t.join() for t in ts]
        assert len(got) == 80 and len(set(got)) == 80
        assert sum(BA.manifest_row_count(p) for p in md.glob("batch_*.jsonl")) == 80


def t_seal_never_overwrites_foreign_writer():
    with tempfile.TemporaryDirectory() as d:
        md = Path(d)
        n, tmp, f = BA.open_new_batch(md)
        f.write('{"mine": 1}\n'); f.close()
        (md / f"batch_{n:04d}.jsonl").write_text('{"foreign": 1}\n')   # a writer ignoring the lock
        (md / f"batch_{n:04d}.ready").write_text("")
        n2 = BA.seal_batch(md, n, tmp)
        assert n2 != n and "foreign" in (md / f"batch_{n:04d}.jsonl").read_text()
        assert "mine" in (md / f"batch_{n2:04d}.jsonl").read_text() and (md / f"batch_{n2:04d}.ready").exists()
        assert not list(md.glob("*.tmp"))


def _pushed(md, b, records, age):
    p = md / f"{b}.pushed"; p.write_text(json.dumps({"batch": b, "records": records}))
    t = time.time() - age; os.utime(p, (t, t))


def t_stale_detection_and_supersede():
    with tempfile.TemporaryDirectory() as d:
        stage = Path(d) / "pdf"; md = stage / "_manifest"; md.mkdir(parents=True)
        for b in ("batch_0001", "batch_0002", "batch_0003", "batch_0004"):
            (md / f"{b}.jsonl").write_text('{"a":1}\n{"a":2}\n'); (md / f"{b}.ready").write_text("")
        _pushed(md, "batch_0001", 2, 0)        # consistent
        _pushed(md, "batch_0002", 2, 3600)     # manifest rewritten an hour after push (collision)
        _pushed(md, "batch_0003", 5, -10)      # count mismatch
        _pushed(md, "batch_0004", 2, 5)        # rewritten within grace (migration) -> fine
        st = BA.stale_batches(md)
        assert set(st) == {"batch_0002", "batch_0003"}, st
        assert any("newer_than_pushed" in w for w in st["batch_0002"])
        assert st["batch_0003"] == ["pushed_records_5!=manifest_rows_2"]
        assert L.ready_batches(stage) == ["batch_0002", "batch_0003"]
        assert U.ready_batches(stage) == ["batch_0002", "batch_0003"]
        dst = BA.supersede_pushed(md, "batch_0002")
        assert dst.exists() and dst.parent.name == "_superseded" and not (md / "batch_0002.pushed").exists()
        assert (md / "batch_0002.jsonl").exists()          # nothing deleted
        _pushed(md, "batch_0002", 2, -1)                    # re-push writes a fresh .pushed -> consistent
        assert "batch_0002" not in BA.stale_batches(md)


def t_flag_collisions_alert():
    with tempfile.TemporaryDirectory() as d:
        stage = Path(d) / "pdf"; md = stage / "_manifest"; md.mkdir(parents=True); state = Path(d) / "state"; state.mkdir()
        assert L.flag_collisions(state, stage) == {} and not (state / "alerts" / L.COLLISION_ALERT_NAME).exists()
        (md / "batch_0001.jsonl").write_text('{"a":1}\n'); (md / "batch_0001.ready").write_text("")
        _pushed(md, "batch_0001", 3, 0)
        bad = L.flag_collisions(state, stage)
        assert "batch_0001" in bad
        a = json.loads((state / "alerts" / L.COLLISION_ALERT_NAME).read_text())
        assert "batch_0001" in a["batches"] and (state / "pdf_batch_collisions.jsonl").exists()
        assert (md / "batch_0001.jsonl").exists() and (md / "batch_0001.pushed").exists()


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("t_"):
            f(); print("ok", k)
    print("ALL OK")
