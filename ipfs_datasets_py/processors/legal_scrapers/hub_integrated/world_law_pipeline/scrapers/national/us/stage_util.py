"""Shared part-file writer: .tmp -> fsync -> validate -> rename. Final files are never touched again."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, json, shutil, time
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/common"))
from schema import place_key, validate_record
STAGE = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national")
MIN_FREE = 35 * 2**30
def utcstamp(): return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
def now_iso(): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
def check_space():
    if shutil.disk_usage("/workspace").free < MIN_FREE:
        print("FREE SPACE < 35GB, stopping", flush=True); sys.exit(3)
def write_part(cc, place_id, tag, recs, log=print):
    """tag must contain a UTC stamp + part no; returns (path, n_ok)."""
    d = os.path.join(STAGE, cc); os.makedirs(d, exist_ok=True)
    pk = place_key(place_id)
    final = os.path.join(d, f"{pk}.{tag}.jsonl"); tmp = final + ".tmp"
    assert not os.path.exists(final), final
    with open(tmp, "w", encoding="utf-8") as f:
        for r in recs: f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())
    v = {"rows": 0, "bad_rows": 0, "errors": []}
    with open(tmp, encoding="utf-8") as f:
        for i, line in enumerate(f):
            r = json.loads(line); v["rows"] += 1
            e = validate_record(r)
            if place_key(r.get("place_id")) != pk: e = e + ["place_key_mismatch"]
            if e: v["bad_rows"] += 1; v["errors"].append((i, e))
    if v["bad_rows"]:
        log(f"VALIDATION FAIL {tmp}: {v['bad_rows']} bad {v['errors'][:3]}")
        os.rename(tmp, os.path.join(d, f"_bad.{pk}.{tag}.jsonl"))
        return None, 0
    os.rename(tmp, final)
    fd = os.open(d, os.O_RDONLY); os.fsync(fd); os.close(fd)
    log(f"wrote {final} rows={v['rows']} bytes={os.path.getsize(final)}")
    return final, v["rows"]
