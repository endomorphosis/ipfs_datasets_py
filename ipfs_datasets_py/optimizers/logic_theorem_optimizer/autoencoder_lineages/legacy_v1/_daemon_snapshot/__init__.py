"""Hash-verified September 17 deterministic modal/BM25/F-logic snapshot."""
from pathlib import Path
import hashlib
import json

MANIFEST_SHA256 = 'd354fd562b722bf66ac52563aff379253517fbc25bd487898ef5b292b0389cc0'

def verify_snapshot():
    directory = Path(__file__).resolve().parent
    root = next(p for p in directory.parents if (p / "ipfs_datasets_py/logic/autoformal/tree_pin.py").is_file())
    raw = (directory / "MANIFEST.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError("historical daemon manifest digest mismatch")
    manifest = json.loads(raw)
    for item in manifest["files"]:
        if hashlib.sha256((directory / item["vendored_path"]).read_bytes()).hexdigest() != item["vendored_sha256"]:
            raise ValueError("historical daemon source digest mismatch: " + item["vendored_path"])
    for item in manifest["shared_dependencies"]:
        if hashlib.sha256((root / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("historical daemon shared dependency changed: " + item["path"])
    return manifest

MANIFEST = verify_snapshot()
