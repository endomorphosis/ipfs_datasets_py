#!/usr/bin/env python3
"""Publish the Austria OCR-completion merge to HF — SUPERSEDE in place.

Same auth/verify pattern as publish_at_pilot.py, but the five affected
Gemeinde parquets (rows added by OCR) overwrite their remote copies
(Spain Murcia corrected-gate precedent: supersede in place, never a
second copy). Also uploads the matching validation sidecars and the
updated coverage_report.md (this program's own file). Dellach (20302)
is untouched. Verifies by re-downloading every superseded parquet and
re-running the world_municipal gates + row-count comparison.
"""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TQDM_DISABLE"] = "1"

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py"))
from dynamic_credentials import dynamic_credential_entry  # noqa: E402
from huggingface_hub import HfApi, hf_hub_download  # noqa: E402
from ipfs_datasets_py.processors.legal_scrapers.world_municipal import (  # noqa: E402
    parquet_io,
    schema as wm_schema,
)

REPO = "endomorphosis/ipfs_austria_municipal_laws"
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
WORK = HERE / "ocr_work"
REGISTRY = {r["gkz"]: r["name"] for r in json.loads(
    (HERE / "raw" / "statistik_at_carinthia.json").read_text(encoding="utf-8"))}


def main():
    summary = {s["gkz"]: s for s in json.loads(
        (WORK / "ocr_summary.json").read_text(encoding="utf-8"))}
    changed = [g for g, s in sorted(summary.items()) if s["rows_added"] > 0]
    if not changed:
        print("no GKZ with added rows — nothing to publish")
        return 0
    print("superseding:", {g: (summary[g]["rows_before"], summary[g]["rows_after"])
                           for g in changed})
    entry = dynamic_credential_entry("custom.huggingface")
    auth = entry.get("surrogate") if isinstance(entry, dict) else None
    if not auth:
        raise RuntimeError("no surrogate from dynamic_credential_entry")
    api = HfApi(token=auth)
    info = api.dataset_info(REPO, files_metadata=True)
    before_files = {f.rfilename: f.size for f in (info.siblings or [])}
    print(f"remote before: {len(before_files)} files")

    uploads = []
    for g in changed:
        uploads.append((OUT / f"{g}_html.parquet", f"data/{g}_html.parquet"))
        uploads.append((OUT / f"{g}_validation.json", f"data/{g}_validation.json"))
    uploads.append((OUT / "coverage_report.md", "coverage_report.md"))
    for local, remote in uploads:
        api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                        repo_id=REPO, repo_type="dataset",
                        commit_message=f"AT OCR completion: supersede {remote}")
        print(f"uploaded {remote} ({local.stat().st_size} B)", flush=True)

    info = api.dataset_info(REPO, files_metadata=True)
    after_files = {f.rfilename: f.size for f in (info.siblings or [])}
    problems = []
    if len(after_files) != len(before_files):
        problems.append(f"remote file count changed {len(before_files)} -> "
                        f"{len(after_files)} (supersede must not add files)")
    for local, remote in uploads:
        if after_files.get(remote) != local.stat().st_size:
            problems.append(f"size mismatch {remote}: remote "
                            f"{after_files.get(remote)} vs local {local.stat().st_size}")
    verify = {}
    for g in changed:
        p = hf_hub_download(REPO, f"data/{g}_html.parquet", repo_type="dataset",
                            token=auth, force_download=True)
        t = parquet_io.read_html_parquet(p)
        errs = wm_schema.validate_table(t, jurisdiction_id=g,
                                        jurisdiction_name=REGISTRY[g], country="AT")
        verify[g] = {"remote_rows": t.num_rows,
                     "expected_rows": summary[g]["rows_after"], "errors": errs}
        print("verify", g, verify[g], flush=True)
        if errs or t.num_rows != summary[g]["rows_after"]:
            problems.append(f"{g}: remote verify failed {verify[g]}")
    print("remote file count:", len(after_files))
    print("PROBLEMS:", problems if problems else "none")
    (WORK / "publish_verify.json").write_text(json.dumps(
        {"verify": verify, "problems": problems,
         "remote_files": len(after_files)}, indent=1), encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
