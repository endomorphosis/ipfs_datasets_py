"""Publish a reviewed additive prefix with parent binding and immutable readback."""
from hashlib import sha1, sha256
from pathlib import Path
import argparse
import json
from io import BytesIO
import os
import urllib.request

F = Path(__file__).resolve().parent
REPO = "Publicus/legal-ir-autoencoder"
PREFIX = "releases/20261011-retained-raw384-pointer-v1"
STATE = {"stage": "preparation", "parent_commit": None, "confirmed_commit_oid": None,
         "remote_mutation_attempted": False}


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def pin(path):
    path = Path(path)
    assert path.is_file() and not path.is_symlink()
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def request(url, cap):
    with urllib.request.urlopen(url, timeout=60) as response:
        raw = response.read(cap + 1)
    assert len(raw) <= cap
    return raw


def inventory(revision=None):
    route = "" if revision is None else "/revision/" + revision
    value = json.loads(request("https://huggingface.co/api/models/" + REPO + route + "?blobs=true", 8 * 1024**2))
    assert value["private"] is False
    rows = {item["rfilename"]: {key: item.get(key) for key in ("size", "blobId", "lfs")}
            for item in value["siblings"]}
    return value["sha"], rows


def main(review_path):
    review_path = Path(review_path)
    review_pin = pin(review_path)
    review = json.loads(review_path.read_bytes())
    assert review["passed"] is True and review["findings"] == []
    root = F / "hub-release"
    files = sorted(path for path in root.rglob("*") if path.is_file())
    assert all(not path.is_symlink() for path in root.rglob("*"))
    local = {str(path.relative_to(root)): pin(path) for path in files}
    assert review["release_files"] == local
    captured = {}
    for relative, reference in local.items():
        raw = Path(reference["path"]).read_bytes()
        assert len(raw) == reference["bytes"] and sha256(raw).hexdigest() == reference["sha256"]
        captured[relative] = raw
    assert sum(len(raw) for raw in captured.values()) <= 32 * 1024**2
    assert all(pin(reference["path"]) == reference for reference in local.values())
    STATE["stage"] = "parent_inventory"
    previous, old = inventory()
    STATE["parent_commit"] = previous
    assert not any(path == PREFIX or path.startswith(PREFIX + "/") for path in old)
    before = {"repository": REPO, "revision": previous, "prefix": PREFIX, "files": old,
              "review_pin": review_pin, "release_files": local}
    save(F / "hub-before-publication.json", before)
    proposal = {"repository": REPO, "parent_commit": previous, "prefix": PREFIX,
                "review_pin": review_pin, "release_files": local, "captured_verified_bytes": True}
    save(F / "hub-publication-proposal.json", proposal)
    from huggingface_hub import HfApi, CommitOperationAdd
    operations = [CommitOperationAdd(path_in_repo=PREFIX + "/" + relative,
                                    path_or_fileobj=BytesIO(raw)) for relative, raw in captured.items()]
    STATE.update(stage="create_commit", remote_mutation_attempted=True)
    result = HfApi().create_commit(repo_id=REPO, repo_type="model", revision="main",
        parent_commit=previous, operations=operations, num_threads=1,
        commit_message="Preserve retained raw384 and source-only pointer decoder checkpoints",
        commit_description="Unchanged selected October2 checkpoints and October11 frozen source-copy diagnostics. Zero new training updates; no semantic, proof, or default promotion.")
    STATE.update(stage="immutable_inventory_readback", confirmed_commit_oid=result.oid)
    revision, current = inventory(result.oid)
    assert revision == result.oid and all(current.get(path) == identity for path, identity in old.items())
    assert len(current) == len(old) + len(files)
    checks = {}
    for relative, reference in local.items():
        STATE.update(stage="immutable_byte_readback", file=relative)
        remote = PREFIX + "/" + relative
        raw = request("https://huggingface.co/" + REPO + "/resolve/" + revision + "/" + remote,
                      reference["bytes"])
        assert len(raw) == reference["bytes"] and sha256(raw).hexdigest() == reference["sha256"]
        assert pin(reference["path"]) == reference
        checks[remote] = {"bytes": len(raw), "sha256": sha256(raw).hexdigest(),
            "git_blob_sha1": sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
            "downloaded_bytes_verified": True}
    assert pin(review_path) == review_pin
    receipt = {"schema": "retained-pointer-hub-publication-receipt/v1", "repository": REPO,
        "previous_revision": previous, "revision": revision, "prefix": PREFIX,
        "url": "https://huggingface.co/" + REPO + "/tree/" + revision + "/" + PREFIX,
        "prior_file_count": len(old), "prior_file_identities_preserved": True,
        "preservation_scope": "All previous path/size/Gitblob/LFS metadata identities at immutable revisions.",
        "new_file_count": len(files), "current_file_count": len(current), "checks": checks,
        "review_pin": review_pin, "all_new_file_downloads_byte_verified": True,
        "downloaded_numerical_replay": False, "local_frozen_replay_precedes_publication": True,
        "new_optimizer_updates": 0, "qualified": False, "admitted": False,
        "proof_authority": False, "default_promotion": False}
    STATE["stage"] = "durable_completion_receipt"
    save(F / "hub-publication-receipt.json", receipt)
    print(json.dumps({key: receipt[key] for key in ("revision", "new_file_count", "current_file_count",
                                                  "all_new_file_downloads_byte_verified", "url")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True)
    args = parser.parse_args()
    try:
        main(args.review)
    except Exception as error:
        save(F / "hub-publication-failure.json", {**STATE, "repository": REPO, "prefix": PREFIX,
            "error_type": type(error).__name__, "automatic_retry_performed": False,
            "remote_outcome_uncertain": STATE["remote_mutation_attempted"] and STATE["confirmed_commit_oid"] is None,
            "reconciliation_required_before_retry": True})
        raise
