#!/usr/bin/env python3
"""Record submitted source reviews and disputes without granting qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-bundle", type=Path, required=True)
    parser.add_argument("--expected-bundle-sha256", required=True)
    parser.add_argument("--submission", nargs=2, action="append", metavar=("PATH", "SHA256"), required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    if args.output_directory.exists() or args.output_directory.is_symlink():
        parser.error("output directory already exists; choose fresh review evidence")
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_review_admission as owner

    expected_owner = REPOSITORY_ROOT/"ipfs_datasets_py/logic/formalization/autoencoder/alignment_review_admission.py"
    if Path(owner.__file__).resolve() != expected_owner:
        parser.error("review admission import comes from another checkout")
    source_paths = [Path(__file__).resolve(), expected_owner]
    sources = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in source_paths]
    try:
        bundle = owner.read_alignment_review_file(args.review_bundle, expected_sha256=args.expected_bundle_sha256)
        payloads = [owner.read_alignment_review_file(path, expected_sha256=sha) for path,sha in args.submission]
        receipt = owner.admit_alignment_reviews(bundle, payloads)
        for binding in sources:
            if hashlib.sha256(Path(binding["path"]).read_bytes()).hexdigest() != binding["sha256"]:
                raise ValueError("review admission source changed during execution")
        artifact = {"schema": "alignment-review-admission-artifact/v1", "receipt": receipt,
                    "source_bindings": sources, "bundle_binding": {"path":str(args.review_bundle), "sha256":args.expected_bundle_sha256},
                    "submission_bindings": [{"path":path,"sha256":sha} for path,sha in args.submission],
                    "qualified": False, "complete_dependency_manifest": False}
        raw = json.dumps(artifact,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False).encode()+b"\n"
        args.output_directory.mkdir(parents=True,exist_ok=False)
        destination = args.output_directory/"review_admission.json"
        with destination.open("xb") as stream:
            stream.write(raw)
    except (ValueError, OSError) as error:
        print(json.dumps({"status":"failed","reason":str(error),"qualified":False}),file=sys.stderr)
        return 2
    print(json.dumps({"receipt":str(destination),"status":receipt["status"],"qualified":False},indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
