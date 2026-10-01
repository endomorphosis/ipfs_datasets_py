"""Verified linguistic feature codec from the legacy runtime revision."""
from pathlib import Path
import hashlib
import json

MANIFEST_SHA256 = "f44966d10d21f6f97ef89d967f411f5d86fe7195a0aa212269e3c785e27ddfa3"


def verify_snapshot():
    directory = Path(__file__).parent
    raw = (directory / "MANIFEST.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError("legacy linguistic manifest SHA256 mismatch")
    manifest = json.loads(raw)
    raw_codec = (directory / "spacy_modal_codec.py").read_bytes()
    if hashlib.sha256(raw_codec).hexdigest() != manifest["vendored_sha256"]:
        raise ValueError("legacy linguistic codec SHA256 mismatch")
    return manifest


MANIFEST = verify_snapshot()
