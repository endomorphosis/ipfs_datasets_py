#!~/.ipfs_datasets/world_law/.venv_afme/bin/python
"""afme stager: validate out/afme/raw/<CC>/*.jsonl against schema.py; stage a file to staging/afme/<CC>/ only
when it has 0 bad rows (atomic .tmp -> fsync -> rename; staged files are never rewritten).
Writes staging/afme/_logs/staged_<UTC>.json: {"cc", "files": [...], "rows", "bad", "skipped": [...]}.
Raw files are never deleted; a staged raw file is recorded in out/afme/done/staged_<CC>.tsv so it is not restaged.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import argparse, json, os
import afme_common as C
from schema import validate_file, place_key


def run(ccs, dry=False):
    for cc in ccs:
        cc = cc.upper()
        src = C.RAW / cc
        done = C.load_done("staged", cc)
        man = {"cc": cc, "files": [], "rows": 0, "bad": 0, "skipped": [], "at": C.utc_iso(), "lane": C.ARCHIVE_LANE}
        for f in sorted(src.glob("*.jsonl")) if src.exists() else []:
            if f.name in done:
                continue
            C.disk_check(); C.mem_check()
            pk = f.name.split(".", 1)[0]
            res = validate_file(f, expect_place_key=pk)
            if not res["ok"]:
                man["bad"] += res["bad_rows"]
                man["skipped"].append({"file": f.name, "rows": res["rows"], "bad": res["bad_rows"],
                                       "errors": [list(e) for e in res["errors"][:5]], "file_errors": res["file_errors"]})
                C.log(f"{cc} NOT staged {f.name}: {res['bad_rows']}/{res['rows']} bad")
                continue
            dst_dir = C.STAGE / cc
            final = dst_dir / f.name
            if final.exists():
                man["skipped"].append({"file": f.name, "reason": "already_in_staging"}); continue
            if not dry:
                dst_dir.mkdir(parents=True, exist_ok=True)
                tmp = final.with_name(final.name + ".tmp")
                with f.open("rb") as i, tmp.open("wb") as o:
                    for chunk in iter(lambda: i.read(1 << 20), b""):
                        o.write(chunk)
                    o.flush(); os.fsync(o.fileno())
                os.rename(tmp, final)
                C.mark_done("staged", cc, f.name, "ok", str(final))
            man["files"].append(str(final)); man["rows"] += res["rows"]
        if not dry and (man["files"] or man["skipped"]):
            C.LOGS.mkdir(parents=True, exist_ok=True)
            mp = C.LOGS / f"staged_{C.utc_ts()}_{cc}.json"
            mp.write_text(json.dumps(man, ensure_ascii=False, indent=1))
            C.log(f"{cc}: staged {len(man['files'])} files, {man['rows']} rows, bad {man['bad']} -> {mp}")
        else:
            C.log(f"{cc}: nothing to stage (dry={dry}) files={len(man['files'])} bad={man['bad']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cc", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(a.cc, a.dry_run)
