#!/usr/bin/env python3
"""Publish wave-8 national-law parquets to Hugging Face (endomorphosis/<repo>),
using the stored dynamic credential surrogate (connector: custom.huggingface,
host: huggingface.co only) — same pattern as the wave-6/7 publish script.

For each repo passed on argv (repo=expected_rows pairs):
 1. Record current remote row count (fresh download).
 2. Upload the 3 staged files from ../staging/<repo>/ as one commit.
 3. Re-download remote parquet; verify row count == staged, ids unique, 0 empty texts.
Stops entirely on first failure. Credential never printed/persisted; only the
hsurr:* surrogate is used, and only against huggingface.co.
Progress -> ../stats/publish_progress.json
"""
import io, json, os, sys, urllib.request, urllib.error

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dynamic_credentials import add_surrogate_to_request, dynamic_credential_entry
from common13 import WAVE13

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
CONNECTOR = "custom.huggingface"
HOST = "huggingface.co"
STAGING_ROOT = os.path.join(WAVE13, "staging")
PROGRESS_PATH = os.path.join(WAVE13, "stats", "publish_progress.json")
COMMIT_MESSAGE = "Wave 13 thin-country backfill: additive merge (+new instruments)"

def redact(msg):
    if "hsurr:" in msg:
        idx = msg.index("hsurr:")
        msg = msg[:idx] + "hsurr:*[redacted]*" + msg[idx + 60:]
    return msg

def download_remote_parquet(repo_id):
    import pyarrow.parquet as pq
    url = f"https://{HOST}/datasets/{repo_id}/resolve/main/data/laws.parquet"
    req = urllib.request.Request(url)
    add_surrogate_to_request(req, CONNECTOR, allowed_hosts=[HOST])
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            blob = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return pq.read_table(io.BytesIO(blob))

def validate_table(table, expected_rows):
    n = table.num_rows
    if n != expected_rows:
        return False, f"row_count={n} expected={expected_rows}"
    ids = table.column("id").to_pylist()
    if len(set(ids)) != len(ids):
        return False, f"duplicate ids: {len(ids) - len(set(ids))} dupes"
    texts = table.column("text").to_pylist()
    empty = sum(1 for t in texts if t is None or not str(t).strip())
    if empty:
        return False, f"empty texts: {empty}"
    return True, f"rows={n} ids_unique={len(set(ids))} empty_texts=0"

def main():
    import pyarrow.parquet as pq
    repos = {}
    for a in sys.argv[1:]:
        repo, _, rows = a.partition("=")
        repos[repo] = int(rows)
    progress = {"repos": {}, "stopped_early": False, "stop_reason": None}
    def save():
        json.dump(progress, open(PROGRESS_PATH, "w"), indent=2)
    print("== Phase 0: local staged validation ==", flush=True)
    for repo, expected in repos.items():
        p = os.path.join(STAGING_ROOT, repo, "data", "laws.parquet")
        if not os.path.isfile(p):
            print(f"FATAL: staged parquet missing: {p}"); return 2
        ok, detail = validate_table(pq.read_table(p), expected)
        print(f"  {repo}: local {detail} ok={ok}", flush=True)
        if not ok:
            print("FATAL: local validation failed; aborting before any upload."); return 2
    entry = dynamic_credential_entry(CONNECTOR)
    token = entry.get("hsurr") or entry.get("surrogate") or entry.get("token")
    # NOTE: wave-6/7 script used its own accessor; follow it exactly below if this fails.
    if not token:
        raise RuntimeError("no surrogate from dynamic_credential_entry")
    from huggingface_hub import HfApi
    api = HfApi(token=token)
    for repo, expected in repos.items():
        repo_id = f"endomorphosis/{repo}"
        rec = {"expected_rows": expected}
        progress["repos"][repo] = rec
        print(f"\n== {repo_id} ==", flush=True)
        try:
            before = download_remote_parquet(repo_id)
            rec["before_rows"] = None if before is None else before.num_rows
            print(f"  before_rows: {rec['before_rows']}", flush=True)
            info = api.upload_folder(folder_path=os.path.join(STAGING_ROOT, repo),
                                     repo_id=repo_id, repo_type="dataset",
                                     commit_message=COMMIT_MESSAGE)
            rec["commit_oid"] = getattr(info, "oid", None) or getattr(info, "commit_oid", None)
            print(f"  upload commit: {rec['commit_oid']}", flush=True)
            after = download_remote_parquet(repo_id)
            if after is None:
                rec["verify"] = "FAIL: remote parquet 404 after upload"
                progress["stopped_early"] = True; progress["stop_reason"] = f"{repo}: missing after upload"
                save(); print("  VERIFY FAIL. STOPPING."); return 1
            ok, detail = validate_table(after, expected)
            rec["after_rows"] = after.num_rows
            rec["verify"] = ("OK: " if ok else "FAIL: ") + detail
            print(f"  verify: {rec['verify']}", flush=True)
            save()
            if not ok:
                progress["stopped_early"] = True; progress["stop_reason"] = f"{repo}: verify failed ({detail})"
                save(); print("  STOPPING entirely."); return 1
        except Exception as e:
            msg = redact(f"{type(e).__name__}: {e}")
            rec["error"] = msg; progress["stopped_early"] = True
            progress["stop_reason"] = f"{repo}: {msg}"; save()
            print(f"  ERROR: {msg}\n  STOPPING entirely."); return 1
    save()
    print("\nALL REPOS PUBLISHED AND VERIFIED.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
