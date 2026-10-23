#!/usr/bin/env python3
"""Standalone remote verification for the DE pilot seed: fresh token,
file inventory + sizes vs local, re-download all parquets, count rows,
re-validate tables."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
sys.path.insert(0, "/home/hatch/workspace/ipfs_datasets_py")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402
from huggingface_hub import HfApi, hf_hub_download  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from ipfs_datasets_py.processors.legal_scrapers.world_municipal import (  # noqa: E402
    schema as wm,
)

REPO = "endomorphosis/ipfs_germany_municipal_laws"
HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"
OUT = HERE / "out"
NAMES = {"01051011": "Brunsbüttel, Stadt", "01051044": "Heide, Stadt",
         "05554004": "Ahaus, Stadt", "05554012": "Borken, Stadt"}


def main():
    entry = dynamic_credential_entry("custom.huggingface")
    token = entry.get("surrogate")
    api = HfApi(token=token)
    info = api.dataset_info(REPO, files_metadata=True)
    remote = {f.rfilename: f.size for f in (info.siblings or [])}
    print(f"remote files: {len(remote)}")
    expected = {}
    for ags in NAMES:
        expected[f"data/{ags}_html.parquet"] = (DATA / f"{ags}_html.parquet").stat().st_size
        expected[f"data/{ags}_validation.json"] = (DATA / f"{ags}_validation.json").stat().st_size
    expected["data/jurisdictions.jsonl"] = (DATA / "jurisdictions.jsonl").stat().st_size
    expected["coverage_report.md"] = (OUT / "coverage_report.md").stat().st_size
    expected["README.md"] = (OUT / "README.md").stat().st_size
    for s in sorted((HERE / "scripts").glob("*.py")):
        expected[f"scrapers/{s.name}"] = s.stat().st_size
    problems = []
    for path, size in sorted(expected.items()):
        if path not in remote:
            problems.append(f"missing: {path}")
        elif remote[path] != size:
            problems.append(f"size mismatch: {path} remote={remote[path]} local={size}")
    extra = set(remote) - set(expected)
    print("remote-only files (e.g. .gitattributes):", sorted(extra))
    summary = {s["ags"]: s for s in json.loads((OUT / "pilot_summary.json").read_text())}
    total = 0
    for ags, name in NAMES.items():
        p = hf_hub_download(REPO, f"data/{ags}_html.parquet", repo_type="dataset",
                            token=token, force_download=True)
        t = pq.read_table(p)
        errs = wm.validate_table(t, jurisdiction_id=ags, jurisdiction_name=name, country="DE")
        total += t.num_rows
        ok = t.num_rows == summary[ags]["rows"] and not errs
        print(f"{ags}: remote rows={t.num_rows} expected={summary[ags]['rows']} valid={not errs} {'OK' if ok else 'PROBLEM ' + str(errs)}")
        if not ok:
            problems.append(f"{ags} row/valid mismatch")
    print("remote total rows:", total)
    print("PROBLEMS:", problems if problems else "none")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
