#!/usr/bin/env python3
"""Publish the Canada platform census into endomorphosis/ipfs_canada_municipal_laws.

Uploads registry/ca_platform_census_2026-10-12.jsonl and appends a census
APPENDIX to coverage_report.md (remote text fetched, appendix appended,
re-uploaded; pilot text untouched). No README/parquet writes. Verifies by
fresh listing afterwards.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json
import os
import sys

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

REPO = "endomorphosis/ipfs_canada_municipal_laws"
BASE = os.path.expanduser(
    "~/workspace/goals/world-municipal-law-coverage/hidden_files/ca_census")
CENSUS = os.path.join(BASE, "ca_platform_census_2026-10-12.jsonl")
STATS = os.path.join(BASE, "census_stats.json")


def get_hf():
    sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
    from dynamic_credentials import dynamic_credential_entry
    entry = dynamic_credential_entry("custom.huggingface")
    token = entry["surrogate"]
    if not token:
        raise SystemExit("vault credential custom.huggingface unavailable")
    from huggingface_hub import HfApi
    return HfApi(token=token)


def main():
    stats = json.load(open(STATS))
    api = get_hf()
    files_before = sorted(api.list_repo_files(REPO, repo_type="dataset"))
    print(f"files before: {len(files_before)}")

    api.upload_file(path_or_fileobj=CENSUS,
                    path_in_repo="registry/ca_platform_census_2026-10-12.jsonl",
                    repo_id=REPO, repo_type="dataset",
                    commit_message="Canada platform census 2026-10-12: per-CSD platform / by-law route / robots classification (3,489 SGC municipal CSDs)")
    print("uploaded census jsonl")

    # coverage_report.md appendix
    from huggingface_hub import hf_hub_download
    local = hf_hub_download(REPO, "coverage_report.md", repo_type="dataset")
    text = open(local, encoding="utf-8").read()
    if "Platform census appendix" in text:
        print("appendix already present; skipping coverage_report.md update")
    else:
        fam_lines = "\n".join(
            f"| {f['family']} | {f['total']} | {f['reachable']} |"
            for f in stats["families_ranked"][:15])
        appendix = f"""

---

## APPENDIX — Platform census, 2026-10-12 (added 2026-10-13)

Light-touch census of all 3,489 municipal-government CSDs (SGC 2021):
robots.txt + homepage + at most one by-law index page per site; no by-law
documents fetched. Full per-town results:
`registry/ca_platform_census_2026-10-12.jsonl`.

- Municipal website resolved: {stats['resolved']} / {stats['total_csds']} ({stats['resolved']/stats['total_csds']:.0%})
- Sites classified (platform + by-law route + robots posture): {stats['census_status'].get('classified', 0)}
- Reachable for harvest (by-law route found, robots-allowed, not walled): {stats['reachable_towns']}

| Platform family | Towns | Reachable |
|---|---|---|
{fam_lines}

CivicWeb (iCompass) towns remain EXCLUDED (platform robots wildcard
Disallow: /); eScribe document endpoints are Cloudflare-walled from this
egress; both are recorded in the census, not harvested. Tranche-1 scoping by
template family is in the census report.

Caveats: classification covered a priority subset of resolved sites
(largest municipalities first); the platform field records the dominant
detected signature, and for towns whose homepage links a documents vendor
(eScribe/CivicWeb) it records that vendor even where an own-site by-law
library also exists (pilot ground truth: Surrey, Halifax) — reachable
counts treat that vendor group conservatively. Resolution is a lower
bound: this egress stalled intermittently throughout the census window,
so `no_site_found` includes towns whose sites exist but did not answer
in-window.
"""
        with open("/tmp/coverage_report_appended.md", "w", encoding="utf-8") as fh:
            fh.write(text + appendix)
        api.upload_file(path_or_fileobj="/tmp/coverage_report_appended.md",
                        path_in_repo="coverage_report.md",
                        repo_id=REPO, repo_type="dataset",
                        commit_message="coverage_report: append platform census appendix (2026-10-12 census)")
        print("appended census appendix to coverage_report.md")

    files_after = sorted(api.list_repo_files(REPO, repo_type="dataset"))
    print(f"files after: {len(files_after)}")
    new = [f for f in files_after if f not in files_before]
    print("new files:", new)
    assert "registry/ca_platform_census_2026-10-12.jsonl" in files_after
    print("REMOTE VERIFY OK")


if __name__ == "__main__":
    main()
