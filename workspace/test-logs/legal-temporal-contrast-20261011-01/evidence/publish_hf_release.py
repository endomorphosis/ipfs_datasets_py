"""Append a reviewed prefix using an exact parent; verify immutable downloads."""
from pathlib import Path
import hashlib
import json
import math
import os
import subprocess
import sys
from huggingface_hub import HfApi, CommitOperationAdd

F = Path(__file__).resolve().parent
REPO = "Publicus/legal-ir-autoencoder"
PREFIX = "releases/20261011-temporal-role-contrast-v1"
MAX_PAYLOAD_BYTES = 200_000_000


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result, "duplicate JSON key"
            result[key] = value
        return result
    raw = Path(path).read_bytes()
    assert len(raw) <= MAX_PAYLOAD_BYTES
    def finite_number(raw):
        value = float(raw)
        assert math.isfinite(value), "nonfinite JSON number"
        return value
    return json.loads(raw, object_pairs_hook=unique, parse_float=finite_number,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def pin(path):
    path = Path(path)
    assert path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink()
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def write(name, value):
    with (F / name).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(F, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def identities(info):
    return {item.rfilename: dict(size=item.size, blob_id=item.blob_id, lfs=None if item.lfs is None else
        dict(sha256=item.lfs.sha256, size=item.lfs.size, pointer_size=item.lfs.pointer_size)) for item in info.siblings}


def main():
    review_path = Path(sys.argv[1]).resolve()
    review = read(review_path)
    assert set(review) == {"schema", "passed", "findings", "repository", "release_prefix",
        "expected_parent_revision", "payload_files", "payload_bytes", "artifacts", "scope", "limitations"}
    assert review["passed"] is True and review["findings"] == []
    assert review["schema"] == "temporal-contrast-Hub-publication-independent-review/v1"
    receipt_path = F / "hf-preparation-receipt-v01.json"
    receipt = read(receipt_path)
    assert set(receipt) == {"schema", "repository", "release_prefix", "expected_parent_revision", "upload_root",
        "complete_upload_files", "payload_files", "payload_bytes", "baseline_pin", "result_review", "default_promotion", "additive_only"}
    assert receipt["schema"] == "temporal-contrast-Hub-preparation/v1"
    assert receipt["default_promotion"] is False and receipt["additive_only"] is True
    baseline = read(F / "hf-before-file-identities-v01.json")
    assert receipt["repository"] == baseline["repo"] == REPO and receipt["release_prefix"] == PREFIX
    assert review["repository"] == REPO and review["release_prefix"] == PREFIX
    assert review["expected_parent_revision"] == receipt["expected_parent_revision"] == baseline["revision"]
    entries = receipt["complete_upload_files"]
    root = Path(receipt["upload_root"])
    assert root.is_absolute() and root.resolve() == root and root.is_dir() and not root.is_symlink()
    assert review["payload_files"] == receipt["payload_files"] == len(entries)
    assert type(receipt["payload_files"]) is int and 0 < len(entries) <= 1000
    assert type(receipt["payload_bytes"]) is int and 0 < receipt["payload_bytes"] <= MAX_PAYLOAD_BYTES
    assert review["payload_bytes"] == receipt["payload_bytes"] == sum(value["bytes"] for value in entries.values())
    assert set(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()) == set(entries)
    assert all(not path.is_symlink() for path in root.rglob("*"))
    for path, expected in review["artifacts"].items():
        assert {key: pin(path)[key] for key in ("bytes", "sha256")} == expected
    for path in [Path(__file__), receipt_path, F / "hf-before-file-identities-v01.json", *[root / name for name in entries]]:
        assert review["artifacts"][str(path)] == {key: pin(path)[key] for key in ("bytes", "sha256")}
    for name, expected in entries.items():
        assert set(expected) == {"path", "bytes", "sha256"} and type(expected["bytes"]) is int
        assert name.startswith(PREFIX + "/") and ".." not in Path(name).parts and pin(root / name) == expected
    assert pin(F / "hf-before-file-identities-v01.json") == receipt["baseline_pin"]
    assert pin(F / "result-independent-review-v01.json") == receipt["result_review"]
    payload = {name: (root / name).read_bytes() for name in sorted(entries)}
    assert all(len(raw) == entries[name]["bytes"] and hashlib.sha256(raw).hexdigest() == entries[name]["sha256"]
               for name, raw in payload.items())
    api = HfApi()
    before = api.model_info(REPO, files_metadata=True)
    assert before.sha == baseline["revision"] and identities(before) == baseline["files"]
    assert not any(name.startswith(PREFIX + "/") for name in baseline["files"])
    write("hf-preupload-custody-v01.json", dict(repo=REPO, parent_revision=before.sha,
        old_files=len(baseline["files"]), review=pin(review_path), receipt=pin(receipt_path), additive_only=True))
    # Bytes are immutable in memory: the SDK cannot reread changed path inputs.
    operations = [CommitOperationAdd(path_in_repo=name, path_or_fileobj=payload[name]) for name in sorted(entries)]
    for path, expected in review["artifacts"].items():
        assert {key: pin(path)[key] for key in ("bytes", "sha256")} == expected
    result = api.create_commit(repo_id=REPO, repo_type="model", revision="main", parent_commit=before.sha,
        operations=operations, num_threads=2, commit_message="Archive paired source-only temporal role contrast experiment",
        commit_description="Two fresh-Adam 32-update arms from identical retained weights. Authored engineering diagnostics only; no independent statutory gold or default promotion.")
    revision = result.oid
    write("hf-commit-created-v01.json", dict(repo=REPO, revision=revision, parent_revision=before.sha,
        commit_url=result.commit_url, release_prefix=PREFIX, additions=len(entries), default_promotion=False))
    after = identities(api.model_info(REPO, revision=revision, files_metadata=True))
    write("hf-after-file-identities-v01.json", dict(repo=REPO, revision=revision, files=after))
    # Automatic attribute changes are refused, recorded by the saved commit,
    # and must be reconciled read-only before any further mutation.
    assert all(after.get(name) == value for name, value in baseline["files"].items()), "old Hub identity changed"
    assert set(after) - set(baseline["files"]) == set(entries), "unexpected Hub additions"
    destination = F / "hf-verified-download"
    assert not destination.exists()
    with (F / "hf-download-verification-v01.log").open("x") as output:
        completed = subprocess.run(["hf", "download", REPO, "--revision", revision, "--include", PREFIX + "/*",
            "--local-dir", str(destination), "--max-workers", "2"], stdout=output, stderr=subprocess.STDOUT)
    assert completed.returncode == 0
    downloads = {}
    for name, expected in entries.items():
        actual = pin(destination / name)
        assert {key: actual[key] for key in ("bytes", "sha256")} == {key: expected[key] for key in ("bytes", "sha256")}
        assert pin(root / name) == expected
        downloads[name] = actual
    write("hf-publication-verification-v01.json", dict(schema="temporal-contrast-Hub-verification/v1",
        passed=True, findings=[], repo=REPO, revision=revision, parent_revision=before.sha, commit_url=result.commit_url,
        release_prefix=PREFIX, new_files=len(entries), old_files_preserved=len(baseline["files"]),
        all_old_identities_exact=True, all_downloads_byte_exact=True, downloads=downloads,
        default_promotion=False, semantic_accuracy=None))
    print(json.dumps(dict(status="published_and_verified", revision=revision, new_files=len(entries))))


if __name__ == "__main__":
    main()
