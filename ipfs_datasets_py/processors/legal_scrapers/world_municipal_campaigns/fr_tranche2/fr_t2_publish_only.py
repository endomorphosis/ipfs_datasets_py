"""France tranche 2 — publish-only recovery.

The full merge+publish process was SIGKILLed (memory spike on the
shared 7 GB box) after writing the validated local parquet +
sidecar but before build_docs/uploads. This script performs ONLY
the remaining steps from the merge's own stats file: build_docs,
upload (parquet, sidecar, coverage, README, tranche-2 scripts),
remote re-download verification. Idempotent; safe to re-run.
"""
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/workflow-skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

HF = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
spec = importlib.util.spec_from_file_location(
    "mp", str(HF / "fr_tranche2" / "scripts" / "fr_t2_merge_publish.py"))
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)
B, OUT, DATA, CODE, REPO_ID = mp.B, mp.OUT, mp.DATA, mp.CODE, mp.REPO_ID
name = mp.name


def main():
    from huggingface_hub import HfApi, hf_hub_download
    stats = json.loads((OUT / "besancon_t2_build_result.json").read_text(encoding="utf-8"))
    assert stats["valid"] and stats["rows"] > 0
    assert (DATA / f"{CODE}_html.parquet").exists()
    mp.build_docs(stats)
    print("docs built", flush=True)
    entry = dynamic_credential_entry("custom.huggingface")
    api = HfApi(token=entry["surrogate"])
    api.create_repo(REPO_ID, repo_type="dataset", exist_ok=True)
    uploads = [
        (DATA / f"{CODE}_html.parquet", f"{CODE}_html.parquet"),
        (DATA / f"{CODE}_validation.json", f"{CODE}_validation.json"),
        (DATA / "coverage_report.md", "coverage_report.md"),
        (DATA / "README.md", "README.md"),
    ]
    scripts_dir = OUT / "scripts"
    for fn in sorted(os.listdir(scripts_dir)):
        if fn.endswith(".py"):
            uploads.append((scripts_dir / fn, f"scrapers/{fn}"))
    for local, repo_path in uploads:
        if not local.exists():
            raise SystemExit(f"missing local file: {local}")
    for local, repo_path in uploads:
        api.upload_file(path_or_fileobj=str(local), path_in_repo=repo_path,
                        repo_id=REPO_ID, repo_type="dataset",
                        commit_message=f"FR tranche 2: {repo_path}")
        print("uploaded", repo_path, flush=True)

    print("--- remote verification ---", flush=True)
    tmp = OUT / "scratch" / "verify"
    tmp.mkdir(parents=True, exist_ok=True)
    p = hf_hub_download(REPO_ID, f"{CODE}_html.parquet", repo_type="dataset",
                        local_dir=str(tmp))
    t = B.read_html_parquet(Path(p))
    errs = B.validate_table(t, jurisdiction_id=CODE, jurisdiction_name=name, country="FR")
    print("remote rows:", t.num_rows, "valid:", not errs, errs, flush=True)
    assert t.num_rows == stats["rows"] and not errs
    from collections import Counter
    print("remote rows by document_type:",
          dict(Counter(t.column("document_type").to_pylist())), flush=True)
    remote = {f.rfilename for f in api.list_repo_tree(REPO_ID, repo_type="dataset", recursive=True)
              if getattr(f, "rfilename", None)}
    print("remote files:", sorted(remote), flush=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print("PUBLISH + VERIFY DONE", flush=True)


if __name__ == "__main__":
    main()
