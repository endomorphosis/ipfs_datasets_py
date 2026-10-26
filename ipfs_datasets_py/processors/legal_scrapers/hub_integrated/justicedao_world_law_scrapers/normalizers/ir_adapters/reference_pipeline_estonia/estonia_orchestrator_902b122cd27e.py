#!/usr/bin/env python3
"""Estonia RECONFIRM_FINAL orchestrator tip 902b122cd27e (memsafe corpus+encode)."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

TIP_SHORT = "902b122cd27e"
VENV_PY = "/workspace/venv/bin/python"
ROOT = Path("/workspace/do_ir_resume")
CACHE = Path("/workspace/country-laws-ir/cache")
REPORTS = Path("/workspace/country-laws-ir/reports")
CKPT = CACHE / "embeddings" / f"estonia_{TIP_SHORT}.npy"
CORPUS = CACHE / f"estonia_corpus_{TIP_SHORT}.parquet"
SPILL = CACHE / f"estonia_bm25_spill_{TIP_SHORT}"
OUT = Path("/workspace/country-laws-ir/releases/ipfs_estonia_laws_ir")
GDIR = SPILL / "graph_parts"
LOG = REPORTS / f"estonia_orchestrator_{TIP_SHORT}.log"

def emb_done():
    if not (CKPT.is_file() and CKPT.with_suffix(".json").is_file() and CORPUS.is_file()):
        return False
    meta = json.loads(CKPT.with_suffix(".json").read_text())
    return int(meta.get("done") or 0) == int(meta.get("n") or -1) and int(meta.get("n") or 0) > 0

PHASES = [
    ("soft_filter", ROOT / "estonia_soft_filter.py",
     lambda: (CACHE / f"estonia_filtered_{TIP_SHORT}" / "data" / "laws.parquet").is_file()
             and (CACHE / f"estonia_filtered_{TIP_SHORT}" / "pack_meta.json").is_file()),
    ("corpus", ROOT / "estonia_corpus_stream_902b122cd27e.py", lambda: CORPUS.is_file()),
    ("encode", ROOT / "estonia_encode_memsafe_902b122cd27e.py", emb_done),
    ("finish", ROOT / "estonia_finish_from_emb_902b122cd27e.py", lambda: (SPILL / "vectors.pkl").is_file() and (SPILL / "bm25_documents.parquet").is_file()),
    ("graph_parts", ROOT / "estonia_stream_graph_parts_902b122cd27e.py", lambda: GDIR.is_dir() and any(GDIR.glob("edges_*.parquet"))),
    ("package", ROOT / "estonia_package_memsafe_902b122cd27e.py", lambda: (OUT / "manifest.json").is_file()),
    ("upload", ROOT / "estonia_upload.py", lambda: (REPORTS / f"estonia_upload_{TIP_SHORT}.json").is_file()),
    ("smoke", ROOT / "estonia_bm25_smoke.py", lambda: (REPORTS / f"estonia_bm25_smoke_{TIP_SHORT}.json").is_file() and json.loads((REPORTS / f"estonia_bm25_smoke_{TIP_SHORT}.json").read_text()).get("pass")),
    ("report", ROOT / "estonia_write_publish_report.py", lambda: (REPORTS / f"estonia_publish_{TIP_SHORT}.json").is_file()),
]

def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def run_phase(name: str, script: Path) -> int:
    log(f"PHASE_START {name} script={script}")
    env = os.environ.copy()
    env.setdefault("IR_MEM_WARN_GIB", "3.5")
    env.setdefault("IR_MEM_ABORT_GIB", "2.0")
    env.setdefault("IR_RSS_ABORT_GIB", "12.0")
    env.setdefault("IR_MEM_LOG_EVERY", "5000")
    env.setdefault("HF_HOME", "/workspace/country-laws-ir/cache/hf")
    env.setdefault("MALLOC_TRIM_THRESHOLD_", "100000")
    secret = Path(__import__("os").environ.get("HF_TOKEN_FILE", ""))
    if secret.is_file():
        for line in secret.read_text().splitlines():
            if line.startswith("HF_TOKEN=") and "HF_TOKEN" not in env:
                env["HF_TOKEN"] = line.split("=", 1)[1].strip().strip('"').strip("'")
    return subprocess.call([VENV_PY, "-u", str(script)], env=env)

def main() -> int:
    log(f"orchestrator start tip={TIP_SHORT}")
    for name, script, done in PHASES:
        try:
            if done():
                log(f"PHASE_SKIP {name} (artifacts present)")
                continue
        except Exception as e:
            log(f"PHASE_DONE_CHECK_ERR {name}: {e}")
        if not script.is_file():
            log(f"MISSING_SCRIPT {script}")
            return 3
        rc = run_phase(name, script)
        log(f"PHASE_END {name} rc={rc}")
        if rc != 0:
            try:
                if done():
                    log(f"PHASE_WARN {name} rc={rc} but artifacts OK — continue")
                    continue
            except Exception as e:
                log(f"PHASE_DONE_RECHECK_ERR {name}: {e}")
            log(f"PHASE_FAIL {name} rc={rc} — stop")
            return rc
    log("orchestrator SUCCESS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
