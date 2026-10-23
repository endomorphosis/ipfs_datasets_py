#!/usr/bin/env python3
"""CH cantonal: collect current texts of law from canton-hosted official LexWork portals (one process).

Per canton: GET /api/<lang>/texts_of_law/lightweight_index (done beforehand -> index/<C>.json), then for each
non-abrogated text GET /api/<lang>/texts_of_law/<systematic_number>/show_as_json (official JSON incl. structure).
One worker thread per canton host (single process), one request at a time per host, >= DELAY s between requests to the same host, back off on 429/5xx,
stop a host after 3 consecutive 403 (BLOCKED_SOURCE). Plain default python-requests UA identifying itself; no tricks.
Raw JSON saved gzip'd under raw/<C>/; resumable. TERM self at MemAvailable <= 3.5 GiB.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import gzip, json, os, signal, sys, threading, time, urllib.parse, collections
from pathlib import Path
import requests

BASE = _CORPORA / "ch_cantonal"
HOSTS = {"BE": ("www.belex.sites.be.ch", "de"), "LU": ("srl.lu.ch", "de"), "UR": ("rechtsbuch.ur.ch", "de"),
         "OW": ("gdb.ow.ch", "de"), "NW": ("gesetze.nw.ch", "de"), "GL": ("gesetze.gl.ch", "de"), "ZG": ("bgs.zg.ch", "de"),
         "FR": ("bdlf.fr.ch", "fr"), "SO": ("bgs.so.ch", "de"), "BS": ("www.gesetzessammlung.bs.ch", "de"),
         "BL": ("bl.clex.ch", "de"), "SH": ("rechtsbuch.sh.ch", "de"), "AR": ("ar.clex.ch", "de"),
         "SG": ("www.gesetzessammlung.sg.ch", "de"), "GR": ("www.gr-lex.gr.ch", "de"), "AG": ("gesetzessammlungen.ag.ch", "de"),
         "TG": ("www.rechtsbuch.tg.ch", "de"), "VS": ("lex.vs.ch", "fr")}
DELAY = float(os.environ.get("CH_DELAY", "1.5"))
MAX_PER_CANTON = int(os.environ.get("CH_MAX_PER_CANTON", "100000"))
MEM_STOP_KB = int(3.5 * 1024 * 1024)
STATE = BASE / "collect_state.json"
STOP = False


def _sig(*_):
    global STOP
    STOP = True


signal.signal(signal.SIGTERM, _sig)


def mem_kb():
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable:"):
            return int(ln.split()[1])
    return 0


MEM_MIN = [mem_kb()]


def watchdog():
    while not STOP:
        m = mem_kb(); MEM_MIN[0] = min(MEM_MIN[0], m)
        if m <= MEM_STOP_KB:
            print(f"MEM GUARD {m} kB <= 3.5G -> TERM self (no restart)", flush=True)
            os.kill(os.getpid(), signal.SIGTERM); return
        time.sleep(2)


def main():
    threading.Thread(target=watchdog, daemon=True).start()
    only = set(sys.argv[1].split(",")) if len(sys.argv) > 1 else set(HOSTS)
    q = {}; st = {}
    for c, (h, lang) in HOSTS.items():
        if c not in only:
            continue
        idx = json.load(open(BASE / "index" / f"{c}.json"))
        items = [x for v in idx.values() for x in v if not x.get("abrogated")]
        (BASE / "raw" / c).mkdir(parents=True, exist_ok=True)
        todo = [x for x in items if not (BASE / "raw" / c / (urllib.parse.quote(x["systematic_number"], safe="") + ".json.gz")).exists()]
        q[c] = collections.deque(todo[:MAX_PER_CANTON])
        st[c] = {"host": h, "index": len(items), "todo": len(q[c]), "ok": 0, "err": 0, "c403": 0, "blocked": False, "last_status": None}
    lock = threading.Lock(); cnt = [0]; t0 = time.time()

    def worker(c):
        s = requests.Session(); s.headers["User-Agent"] = "python-requests (research collection of official cantonal law texts; polite, 1 request at a time per host)"
        h, lang = HOSTS[c]; backoff = DELAY
        while not STOP and q[c] and not st[c]["blocked"]:
            x = q[c][0]; sn = x["systematic_number"]
            url = f"https://{h}/api/{lang}/texts_of_law/{urllib.parse.quote(sn, safe='')}/show_as_json"
            try:
                r = s.get(url, timeout=90); code = r.status_code
            except requests.RequestException:
                code = -1
            st[c]["last_status"] = code
            with lock:
                cnt[0] += 1; n = cnt[0]
            if code == 200:
                try:
                    r.json()
                    with gzip.open(BASE / "raw" / c / (urllib.parse.quote(sn, safe="") + ".json.gz"), "wb") as f:
                        f.write(r.content)
                    st[c]["ok"] += 1
                except ValueError:
                    st[c]["err"] += 1
                q[c].popleft(); st[c]["c403"] = 0; backoff = DELAY; time.sleep(DELAY)
            elif code == 403:
                st[c]["c403"] += 1; st[c]["err"] += 1
                if st[c]["c403"] >= 3:
                    st[c]["blocked"] = True; print(f"{c} BLOCKED_SOURCE after 3x403 at {sn}", flush=True); break
                time.sleep(10)
            elif code == 404:
                st[c]["err"] += 1; st[c].setdefault("not_found", []).append(sn); q[c].popleft(); time.sleep(DELAY)
            else:  # 429 / 5xx / network: back off, retry up to 3 times then skip
                x["_retry"] = x.get("_retry", 0) + 1; backoff = min(backoff * 3, 120)
                if x["_retry"] > 3:
                    st[c]["err"] += 1; st[c].setdefault("failed", []).append([sn, code]); q[c].popleft()
                time.sleep(backoff)
            if n % 300 == 0:
                el = time.time() - t0; left = sum(len(q[k]) for k in q if not st[k]["blocked"])
                print(f"{n} req {el:.0f}s ~{n/el:.1f} rps, left {left}, mem {mem_kb()//1024} MB", flush=True)
                with lock:
                    STATE.write_text(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cantons": st, "mem_min_kB": MEM_MIN[0]}, indent=1))

    ths = [threading.Thread(target=worker, args=(c,), daemon=True) for c in q]
    for t in ths:
        t.start()
    for t in ths:
        while t.is_alive():
            t.join(timeout=1)
    n = cnt[0]
    STATE.write_text(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "stopped": STOP, "cantons": st, "requests": n, "mem_min_kB": MEM_MIN[0]}, indent=1))
    print("DONE" if not STOP else "STOPPED", json.dumps({c: {k: v for k, v in d.items() if k in ("index", "ok", "err", "blocked")} for c, d in st.items()}), flush=True)


if __name__ == "__main__":
    main()
