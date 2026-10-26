#!/usr/bin/env python3
"""Smoke-test every national collector (copied from ipfs_datasets_py, unmodified).

Each collector runs as a subprocess with:
  IPFS_DATASETS_LEGAL_CORPORA_ROOT=/workspace/world_law/staging/national/<CC>
  MAX_NEW=3 MAX_SECONDS=75, hard wall timeout (default 120s).
Results appended to _logs/smoke/results.jsonl (resumable: done CCs skipped).
No HF uploads: HF_TOKEN_PATH points at /dev/null, HF_HUB_OFFLINE=1.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, re, signal, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHARED = HERE / "shared"
STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national"))
LOGS = STAGE / "_logs" / "smoke"
RES = LOGS / "results.jsonl"
PY = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/venv/bin/python")
TIMEOUT = int(os.environ.get("SMOKE_TIMEOUT", "120"))
CONC = int(os.environ.get("SMOKE_CONC", "10"))

def count_docs(root: Path):
    n_inst = 0; n_idx = 0; nbytes = 0
    for p in root.rglob("*"):
        if not p.is_file(): continue
        if p.parent.name in ("instruments", "laws", "records") and p.suffix == ".json":
            n_inst += 1; nbytes += p.stat().st_size
        elif p.name == "index.jsonl":
            try: n_idx += sum(1 for _ in p.open(errors="ignore"))
            except Exception: pass
    return max(n_inst, n_idx), n_inst, n_idx, nbytes

def classify(rc, timed_out, docs, log):
    low = log.lower()
    if docs > 0: return "works"
    if re.search(r"api[_ ]key|login required|token-gated|requires? (an )?(api )?key", low) and "never invent" not in low[:0]:
        if "api_key" in low or "api key" in low: return "blocked"
    if re.search(r"\b(403|401)\b|forbidden|cloudflare|access denied|captcha", low): return "blocked"
    if re.search(r"traceback|error|exception", low) and not timed_out: return "broken"
    if timed_out and re.search(r"catalog|discover|queue|listing|page=|found \d+|total=", low):
        return "works-discovery-only"
    if timed_out: return "slow-no-docs-in-window"
    if rc == 0: return "ran-0-new-docs"
    return "broken"

def run(entry):
    cc = entry["country_code"]; coll = entry["collector"]
    root = STAGE / "_work" / cc
    root.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({
        "IPFS_DATASETS_LEGAL_CORPORA_ROOT": str(root),
        "IPFS_DATASETS_LEGAL_COLLECTORS_ROOT": str(HERE),
        "HF_TOKEN_PATH": "/dev/null", "HF_HUB_OFFLINE": "1", "HF_TOKEN": "",
        "MAX_NEW": "3", "MAX_SECONDS": "75", "PYTHONUNBUFFERED": "1",
    })
    logf = LOGS / f"{cc}.log"
    t0 = time.time(); timed_out = False
    with open(logf, "w") as lf:
        p = subprocess.Popen([PY, str(SHARED / coll)], cwd=str(root), env=env,
                             stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            rc = p.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(p.pid, signal.SIGTERM)
            try: rc = p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL); rc = p.wait()
    dt = round(time.time() - t0, 1)
    docs, n_inst, n_idx, nbytes = count_docs(root)
    # collector-internal logs too
    txt = logf.read_text(errors="ignore")
    for lp in root.rglob("*.log"):
        try: txt += "\n" + lp.read_text(errors="ignore")[-20000:]
        except Exception: pass
    status = classify(rc, timed_out, docs, txt)
    em = subprocess.run([PY, str(HERE / "emit_staged.py"), cc], capture_output=True, text=True)
    emitted = sum(int(m) for m in re.findall(r" wrote \S+ (\d+) docs", em.stdout))
    errs = [l.strip()[:200] for l in txt.splitlines() if re.search(r"Error|error|Traceback|HTTP [45]\d\d|\b40[13]\b|\b429\b|timed out", l)]
    rec = dict(cc=cc, collector=coll, slug=entry["slug"], status=status, rc=rc, timed_out=timed_out,
               seconds=dt, docs=docs, emitted=emitted, instruments=n_inst, index_lines=n_idx, bytes=nbytes,
               err_sample=errs[-3:], last_lines=[l[:200] for l in txt.strip().splitlines()[-3:]])
    with open(RES, "a") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(cc, status, docs, dt, flush=True)
    return rec

def main():
    entries = [e for e in json.load(open(HERE / "snapshot_catalog.json"))["entries"] if not e.get("alias_of")]
    only = sys.argv[1:]
    if only: entries = [e for e in entries if e["country_code"] in only]
    done = set()
    if RES.exists():
        done = {json.loads(l)["cc"] for l in RES.open() if l.strip()}
    todo = [e for e in entries if e["country_code"] not in done]
    print(f"todo={len(todo)} done={len(done)}", flush=True)
    with ThreadPoolExecutor(CONC) as ex:
        list(ex.map(run, todo))

if __name__ == "__main__":
    main()
