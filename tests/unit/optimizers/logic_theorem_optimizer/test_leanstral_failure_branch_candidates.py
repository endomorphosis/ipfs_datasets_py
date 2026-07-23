"""Validation-path coverage for the strict failure-branch candidate boundary.

The dependency's full suite lives under ``tests/unit/logic/modal``.  This file
keeps the optimizer validation path named by PORTAL-LIR-HAMMER-125 executable
and exercises the safety properties on which the re-audit depends.
"""

from __future__ import annotations

import runpy
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
DEPENDENCY_TEST = (
    REPO_ROOT
    / "tests"
    / "unit"
    / "logic"
    / "modal"
    / "test_leanstral_failure_branch_candidates.py"
)
_DEPENDENCY = runpy.run_path(str(DEPENDENCY_TEST))


def test_reaudit_dependency_accepts_only_typed_failed_branch_candidate() -> None:
    _DEPENDENCY["test_strict_sanitizer_accepts_typed_failed_branch_candidate"]()


def test_reaudit_dependency_rejects_source_copy_and_markdown_proof_text() -> None:
    _DEPENDENCY[
        "test_strict_sanitizer_rejects_full_source_copy_even_when_metadata_claims_safe"
    ]()
    _DEPENDENCY[
        "test_strict_sanitizer_rejects_successful_obligation_and_markdown_wrapper"
    ]()
    _DEPENDENCY["test_strict_sanitizer_rejects_duplicate_json_keys"]()
