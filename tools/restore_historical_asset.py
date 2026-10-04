"""Restore a pinned historical asset published outside GitHub's exhausted LFS quota."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from huggingface_hub import hf_hub_download


def restore(reference_path: Path, destination: Path | None = None) -> Path:
    reference = json.loads(reference_path.read_text())
    if reference.get("schema") != "huggingface-historical-git-asset@1":
        raise ValueError("Not a historical asset reference")
    revision = reference["revision"]
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("An immutable revision is required")
    cached = Path(hf_hub_download(reference["repo_id"], reference["filename"], revision=revision))
    digest = hashlib.sha256()
    with cached.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if cached.stat().st_size != reference["size_bytes"] or digest.hexdigest() != reference["sha256"]:
        raise ValueError("Downloaded bytes do not match the recorded checkpoint")
    target = destination or reference_path
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".asset-restore-")
    try:
        with os.fdopen(fd, "wb") as output, cached.open("rb") as source:
            shutil.copyfileobj(source, output)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(restore(args.reference, args.output))
