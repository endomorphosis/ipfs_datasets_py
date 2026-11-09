#!/usr/bin/env python3
"""OCR ZA metro needs_ocr PDFs (no usable text layer). Light-runner gates: start MemAvailable>=3.0GiB held 120s,
hard stop <1.5GiB held 15s, RSS cap 300MB (tree), 10-min requeue, slot flock, disk>=12600MiB, 2 workers.
Output cache/ocr/<ident>.txt + .json {mean_conf,status ok|DEGRADED}. Resumable."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import fcntl, json, os, subprocess, sys, tempfile, time, threading, shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
W = Path(os.environ.get("ZA_WORK", (str(_LEGAL_WS) + "/world_laws/za_metro"))); OUT = W / "cache/ocr"; OUT.mkdir(parents=True, exist_ok=True)
os.environ.pop("TESSDATA_PREFIX", None)  # system tessdata (eng)
ST = W / "status.txt"
def log(m):
    with open(ST, "a") as f: f.write(time.strftime("%Y-%m-%dT%H:%M:%S%z") + " OCR " + m + "\n")
def mem():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable"): return int(l.split()[1]) / 1048576
def tree_rss():
    me = os.getpid(); tot = 0
    out = subprocess.run(["ps", "-e", "-o", "pid=,ppid=,rss="], capture_output=True, text=True).stdout.split("\n")
    rows = [tuple(map(int, l.split())) for l in out if l.strip()]
    kids = {me}; ch = True
    while ch:
        ch = False
        for p, pp, r in rows:
            if pp in kids and p not in kids: kids.add(p); ch = True
    return sum(r for p, pp, r in rows if p in kids) / 1024
def start_gate():
    while True:
        free = shutil.disk_usage((str(_LEGAL_WS))).free / 1048576
        t0 = time.time(); ok = free >= 12600
        while ok and time.time() - t0 < 120:
            if mem() < 3.0: ok = False
            time.sleep(5)
        if ok: return
        log(f"GATE_WAIT mem={mem():.2f}GiB disk={free:.0f}MiB requeue 600s"); time.sleep(600)
STOP = threading.Event(); REASON = []
def monitor():
    low = None
    while not STOP.is_set():
        m = mem()
        if m < 1.5:
            low = low or time.time()
            if time.time() - low >= 15: REASON.append(f"HARD_STOP mem={m:.2f}GiB"); STOP.set()
        else: low = None
        r = tree_rss()
        if r > 300: REASON.append(f"RSS_CAP rss={r:.0f}MB"); STOP.set()
        time.sleep(3)
def ocr_doc(ident):
    pdf = W / "cache/pdf" / f"{ident}.pdf"; texts, confs = [], []
    with tempfile.TemporaryDirectory(dir=(str(_LEGAL_WS))) as td:
        n = int([l for l in subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout.split("\n") if l.startswith("Pages")][0].split()[1])
        for p in range(1, n + 1):
            if STOP.is_set(): return None
            base = f"{td}/p"; subprocess.run(["pdftoppm", "-r", "300", "-gray", "-f", str(p), "-l", str(p), "-png", "-singlefile", str(pdf), base], check=True, timeout=300)
            tsv = subprocess.run(["tesseract", base + ".png", "-", "-l", "eng", "--psm", "6", "tsv"], capture_output=True, text=True, timeout=600,
                                 env={**os.environ, "OMP_THREAD_LIMIT": "1"}).stdout
            lines = {}; 
            for row in tsv.split("\n")[1:]:
                c = row.split("\t")
                if len(c) < 12 or c[0] != "5": continue
                cf = float(c[10]); w = c[11]
                if cf >= 0 and w.strip(): confs.append(cf); lines.setdefault((int(c[2]), int(c[3]), int(c[4])), []).append(w)
            texts.append("\n".join(" ".join(v) for k, v in sorted(lines.items())))
            os.remove(base + ".png")
    mc = sum(confs) / len(confs) if confs else 0.0
    (OUT / f"{ident}.txt").write_text("\f".join(texts))
    meta = {"ident": ident, "pages": n, "words": len(confs), "mean_conf": round(mc, 2), "status": "ok" if mc >= 80 else "DEGRADED", "engine": "tesseract " + subprocess.run(["tesseract", "--version"], capture_output=True, text=True).stdout.split()[1], "lang": "eng", "dpi": 300}
    (OUT / f"{ident}.json").write_text(json.dumps(meta)); log(f"DONE {ident} pages={n} conf={mc:.1f} {meta['status']}"); return meta
def main():
    todo = [json.loads(l)["ident"] for l in open(W / "results.jsonl") if json.loads(l).get("needs_ocr") and json.loads(l).get("status") == 200]
    todo = [i for i in todo if not (OUT / f"{i}.json").exists()]
    while todo:
        start_gate()
        lf = open("/dev/shm/muni_runner.slot3.lock", "w")
        try: fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError: log("SLOT_BUSY requeue 600s"); time.sleep(600); continue
        log(f"START todo={len(todo)} mem={mem():.2f}GiB slot=slot3"); STOP.clear(); REASON.clear()
        th = threading.Thread(target=monitor, daemon=True); th.start()
        with ThreadPoolExecutor(2) as ex: list(ex.map(ocr_doc, todo))
        STOP.set(); fcntl.flock(lf, fcntl.LOCK_UN); lf.close()
        todo = [i for i in todo if not (OUT / f"{i}.json").exists()]
        if REASON:
            log("STOPPED " + REASON[0] + f" remaining={len(todo)}")
            if REASON[0].startswith("RSS_CAP"): sys.exit(3)
            time.sleep(600)
    log("OCR_DONE")
main()
