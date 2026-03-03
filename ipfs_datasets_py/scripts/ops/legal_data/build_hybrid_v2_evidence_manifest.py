"""WS12-07: Unified Release Evidence Pack v2 - Evidence Manifest Builder.

Builds a deterministic evidence manifest that hashes all required WS12
artifacts and produces a bundle description for release sign-off.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

EVIDENCE_MANIFEST_VERSION = "2.0"

# Required WS12 artifacts (relative to repo root)
REQUIRED_ARTIFACTS = [
    "ipfs_datasets_py/processors/legal_data/reasoner/policy_pack.py",
    "ipfs_datasets_py/processors/legal_data/reasoner/policy_resolver.py",
    "ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py",
    "ipfs_datasets_py/tests/reasoner/fixtures/jurisdiction_replay_matrix_v1.json",
    "ipfs_datasets_py/scripts/ops/legal_data/build_hybrid_legal_conflict_triage.py",
    "ipfs_datasets_py/scripts/ops/legal_data/benchmark_hybrid_v2_reasoner.py",
    "ipfs_datasets_py/scripts/ops/legal_data/assert_hybrid_v2_perf_budgets.py",
    "ipfs_datasets_py/tests/reasoner/test_policy_pack_schema.py",
    "ipfs_datasets_py/tests/reasoner/test_policy_resolver_determinism.py",
    "ipfs_datasets_py/tests/reasoner/test_hybrid_v2_jurisdiction_matrix.py",
    "ipfs_datasets_py/tests/reasoner/test_hybrid_v2_conflict_reason_codes.py",
    "ipfs_datasets_py/tests/reasoner/test_conflict_triage_report_builder.py",
    "ipfs_datasets_py/tests/reasoner/test_perf_budget_sentinel.py",
]


def _resolve_repo_root(repo_root: Optional[str]) -> Path:
    if repo_root is not None:
        return Path(repo_root)
    # Walk up from this file's location to find the repo root
    # File is at: scripts/ops/legal_data/ -> parents[3] = repo root
    return Path(__file__).resolve().parents[3]


def compute_artifact_hash(path: str) -> Optional[str]:
    """Compute sha256 hash of file at given path. Returns None if file not found."""
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def build_evidence_manifest(repo_root: Optional[str] = None) -> Dict[str, Any]:
    """Build manifest dict with artifact presence + hashes.

    Returns:
        {
            "manifest_version": EVIDENCE_MANIFEST_VERSION,
            "artifacts": {name: {"present": bool, "sha256": str | None}},
            "missing_artifacts": [str],
            "all_present": bool,
        }
    """
    root = _resolve_repo_root(repo_root)
    artifacts: Dict[str, Dict[str, Any]] = {}
    missing: List[str] = []

    for rel_path in REQUIRED_ARTIFACTS:
        full_path = root / rel_path
        digest = compute_artifact_hash(str(full_path))
        present = digest is not None
        artifacts[rel_path] = {"present": present, "sha256": digest}
        if not present:
            missing.append(rel_path)

    return {
        "manifest_version": EVIDENCE_MANIFEST_VERSION,
        "artifacts": artifacts,
        "missing_artifacts": missing,
        "all_present": len(missing) == 0,
    }


def validate_evidence_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Validate manifest - check that all required artifacts are present.

    Returns:
        {
            "valid": bool,
            "missing": [str],
            "present_count": int,
            "total_count": int,
        }
    Does NOT raise on missing artifacts - caller decides how to handle.
    """
    artifacts = manifest.get("artifacts", {})
    missing = [name for name, info in artifacts.items() if not info.get("present", False)]
    total = len(artifacts)
    present_count = total - len(missing)
    return {
        "valid": len(missing) == 0,
        "missing": missing,
        "present_count": present_count,
        "total_count": total,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build WS12 release evidence manifest")
    parser.add_argument("--repo-root", default=None, help="Path to repository root")
    parser.add_argument("--output", default=None, help="Write manifest JSON to this file")
    args = parser.parse_args()

    manifest = build_evidence_manifest(repo_root=args.repo_root)
    result = validate_evidence_manifest(manifest)

    print(json.dumps(manifest, indent=2))
    print()
    print(f"Present: {result['present_count']}/{result['total_count']}")
    if result["missing"]:
        print("MISSING:")
        for m in result["missing"]:
            print(f"  - {m}")
        print("Evidence manifest INVALID.")
        sys.exit(1)
    else:
        print("All artifacts present. Evidence manifest VALID.")

    if args.output:
        Path(args.output).write_text(json.dumps(manifest, indent=2))
        print(f"Manifest written to {args.output}")


if __name__ == "__main__":
    main()
