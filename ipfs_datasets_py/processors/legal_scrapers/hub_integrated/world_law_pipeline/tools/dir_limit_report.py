"""Report how close each country dir is to HF's 10,000-files-per-directory limit, in both repos, using the
scoped non-recursive listing of world_law/data/<CC>/ and world_law/metadata/<CC>/ (read-only)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_loop as RL
import schema as S
from huggingface_hub import HfApi


def main():
    api, out = HfApi(), {}
    for repo in (S.REPO_ID, S.NATIONAL_REPO_ID):
        ccs = sorted(Path(d).name for d in RL.list_prefix(api, repo, f"{S.ROOT}/data", files_only=False))
        files, failed = RL.scoped_hub_listing(api, repo, ccs)
        c = RL.hub_dir_counts(files)
        out[repo] = {"all": {f"{s}/{cc}": n for (s, cc), n in sorted(c.items())}, "failed": sorted(failed),
                     "near_limit": RL.near_limit_report(c)}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
