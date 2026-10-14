"""Explicit pytest entry for the unchanged native T02 validation policy.

This file is outside the repository's default testpaths. Its one test delegates
to the same closed live checker; it neither supplies a lease nor grants an
admission. A trusted launcher must supply exact manifest/output paths and the
existing native validation lease environment.
"""
from __future__ import annotations

import os

from scripts.ops.legal_ir import check_span_claim_acceptance as checker

MANIFEST_ENV = "IPFS_DATASETS_T02_MANIFEST"
OUTPUT_ENV = "IPFS_DATASETS_T02_OUTPUT"


def test_span_claim_engineering_acceptance():
    manifest, output = os.environ.get(MANIFEST_ENV, ""), os.environ.get(OUTPUT_ENV, "")
    if not manifest.strip() or not output.strip():
        raise AssertionError("explicit T02 manifest and fresh output environment required")
    # Only these two arguments are forwarded. Source, test, lease and policy
    # validation remain inside the existing checker rather than this adapter.
    status = checker.main(["--manifest", manifest, "--output", output])
    if status != 0:
        raise AssertionError("native T02 engineering checker refused")
