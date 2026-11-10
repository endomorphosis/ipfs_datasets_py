#!/usr/bin/env python3
"""Generalised copy of /workspace/municipal_law/upload_and_cleanup.py (plan §1.2.3 / §4.2).

--repo / --root parameters; file stems are place_keys (== gnis for US).
  --root american_law : original flat layout american_law/data/{gnis}_*.parquet (+ citation)
  --root world_law    : world_law/data/{CC}/{place_key}_html.parquet + world_law/metadata/{CC}/{place_key}.json
Defaults target the NEW dataset. Local files are deleted after upload only with --cleanup.
For staged world data prefer run_loop.py (it also validates and writes manifests/places.parquet).
"""
from __future__ import annotations
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import HfApi


def ensure_zstd(path: Path) -> None:
    meta = pq.ParquetFile(path).metadata
    comps = {meta.row_group(i).column(j).compression
             for i in range(meta.num_row_groups) for j in range(meta.row_group(i).num_columns)}
    if comps <= {"ZSTD"}:
        return
    table = pq.read_table(path)
    tmp = path.with_suffix(".parquet.tmp")
    pq.write_table(table, str(tmp), compression="zstd")
    tmp.replace(path)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="endomorphosis/world_municipal_law")
    ap.add_argument("--root", default="world_law", choices=["world_law", "american_law"])
    ap.add_argument("--out", default=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cleanup", action="store_true", help="delete local copies after upload (original behaviour)")
    args = ap.parse_args(argv)
    if args.repo == "endomorphosis/american_municipal_law" and args.root != "american_law":
        raise SystemExit("refusing: world_law root into american_municipal_law")

    out = Path(args.out)
    api = HfApi()
    hub = set(api.list_repo_files(args.repo, repo_type="dataset"))
    hub_keys = {f.rsplit("/", 1)[-1].replace("_html.parquet", "") if args.root == "american_law"
                else "/".join(f.split("/")[-2:]).replace("_html.parquet", "")
                for f in hub if f.endswith("_html.parquet")}

    files = []  # (key, [(local, path_in_repo)])
    if args.root == "american_law":
        data = out / "american_law" / "data"
        for html in sorted(data.glob("*_html.parquet")):
            k = html.name.replace("_html.parquet", "")
            cite, meta = data / f"{k}_citation.parquet", data / "metadata" / f"{k}.json"
            if k in hub_keys or not (cite.exists() and meta.exists()):
                continue
            files.append((k, [(html, f"american_law/data/{html.name}"), (cite, f"american_law/data/{cite.name}"),
                              (meta, f"american_law/metadata/{meta.name}")]))
    else:
        data = out / "world_law" / "data"
        for html in sorted(data.glob("*/*_html.parquet")):
            cc, k = html.parent.name, html.name.replace("_html.parquet", "")
            meta = out / "world_law" / "metadata" / cc / f"{k}.json"
            if f"{cc}/{k}" in hub_keys or not meta.exists():
                continue
            files.append((f"{cc}/{k}", [(html, f"world_law/data/{cc}/{html.name}"),
                                        (meta, f"world_law/metadata/{cc}/{meta.name}")]))
    print("new_to_upload", len(files))
    if not files or args.dry_run:
        for k, fl in files[:20]:
            print(" ", k, [p for _, p in fl])
        return

    stage = out / "_upload_stage"
    if stage.exists():
        shutil.rmtree(stage)
    manifest = []
    for k, fl in files:
        for local, pir in fl:
            if local.suffix == ".parquet":
                ensure_zstd(local)
            dst = stage / pir
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local, dst)
        html_local = fl[0][0]
        manifest.append({"place_key": k.split("/")[-1], "path_in_repo": fl[0][1],
                         "rows": pq.ParquetFile(html_local).metadata.num_rows,
                         "sha256": sha256(html_local), "bytes": html_local.stat().st_size})
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    man_dir = stage / args.root / ("manifests" if args.root == "world_law" else "")
    man_dir.mkdir(parents=True, exist_ok=True)
    with (man_dir / f"drop_incr_{ts}_manifest.jsonl").open("w") as f:
        for row in manifest:
            f.write(json.dumps(row) + "\n")
    commit = api.upload_folder(folder_path=str(stage / args.root), path_in_repo=args.root,
                               repo_id=args.repo, repo_type="dataset",
                               commit_message=f"Incremental upload: {len(files)} jurisdictions (ZSTD)")
    print("commit", commit)
    if args.cleanup:
        for _, fl in files:
            for local, _ in fl:
                local.unlink(missing_ok=True)
    shutil.rmtree(stage)


if __name__ == "__main__":
    main()
