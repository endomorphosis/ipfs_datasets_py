#!/usr/bin/env python3
"""Canonical operator bridge for the Federal Register production release.

This module makes the already protected LCR-064/LCR-065 runtimes reachable
from one explicit operator API.  It intentionally has no live-mutation CLI:
an exact in-memory :class:`FederalRegisterHuggingFaceRelease`, a canonical
non-fixture candidate, and bounded ``PublicationApproval`` objects cannot be
reconstructed safely from legacy path flags.

The read-only ``--check`` command only reports the local contract.  Network
work is possible solely through the four functions below, each of which
delegates to the shared canonical publisher/canary/seal implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.huggingface.publisher import PublicationApproval  # noqa: E402
from ipfs_datasets_py.huggingface.release import canonical_json_bytes  # noqa: E402
from ipfs_datasets_py.processors.legal_data.federal_register_hf_release import (  # noqa: E402
    FIRST_FEDERAL_REGISTER_PACKAGE_ID,
    FederalRegisterHFReleaseError,
    FederalRegisterHuggingFaceRelease,
    validate_canonical_federal_candidate_evidence,
    validate_federal_register_hf_release,
)
from scripts.ops.legal_data.canary_federal_register_hf_release import (  # noqa: E402
    run_remote_canary,
)
from scripts.ops.legal_data.publish_federal_register_hf_release import (  # noqa: E402
    PRODUCTION_REVISION,
    build_canonical_main_plan,
    execute_canonical_main_release,
)
from scripts.ops.legal_data.seal_federal_register_prepublication import (  # noqa: E402
    generate_federal_prepublication_seal,
)
from scripts.ops.legal_data.stage_federal_register_hf_release import (  # noqa: E402
    execute_canonical_staging_release,
)

SCHEMA: Final = "ipfs_datasets_py/federal-register-production-operator@1"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
TASK_IDS: Final = ("LCR-064", "LCR-073", "LCR-065")
CANONICAL_CANDIDATE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_candidate.json"
)


class FederalRegisterProductionOperatorError(RuntimeError):
    """Fail-closed operator-path error raised before canonical delegation."""


def _candidate_digest(payload: Mapping[str, Any]) -> str:
    body = dict(payload)
    body.pop("content_digest", None)
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def require_production_release_candidate(
    *,
    release: FederalRegisterHuggingFaceRelease,
    candidate: Mapping[str, Any],
) -> None:
    """Bind one canonical non-fixture candidate to exact in-memory bytes."""

    if type(release) is not FederalRegisterHuggingFaceRelease:
        raise FederalRegisterProductionOperatorError(
            "operator path requires an exact in-memory Federal production release"
        )
    validation = validate_federal_register_hf_release(release)
    if validation.get("valid") is not True:
        raise FederalRegisterProductionOperatorError(
            "in-memory Federal production release did not validate"
        )
    if not isinstance(candidate, Mapping):
        raise FederalRegisterProductionOperatorError(
            "canonical Federal production candidate is required"
        )
    try:
        validate_canonical_federal_candidate_evidence(candidate)
    except FederalRegisterHFReleaseError as exc:
        raise FederalRegisterProductionOperatorError(
            "canonical Federal production candidate validation failed: " + str(exc)
        ) from exc
    nested = candidate.get("candidate")
    declared = str(candidate.get("content_digest") or "").strip().casefold()
    descriptors = candidate.get("descriptors")
    if (
        candidate.get("schema")
        != "ipfs_datasets_py/legal-corpora-reindex-federal-candidate@1"
        or candidate.get("fixture_only") is not False
        or candidate.get("mode") not in {"live", "live_official", "production"}
        or candidate.get("authorizing_for_publication") is not False
        or candidate.get("authorizing_hub_upload") is not False
        or candidate.get("hub_upload") is not False
        or candidate.get("first_package_id")
        != FIRST_FEDERAL_REGISTER_PACKAGE_ID
        or not isinstance(nested, Mapping)
        or nested.get("manifest_digest") != release.manifest_digest
        or nested.get("release_root_cid") != release.release_root_cid
        or len(declared) != 64
        or _candidate_digest(candidate) != declared
        or not isinstance(descriptors, Sequence)
        or isinstance(descriptors, (str, bytes))
    ):
        raise FederalRegisterProductionOperatorError(
            "Federal candidate is fixture, unsafe, stale, or release-unbound"
        )
    expected_descriptors = [item.descriptor_dict() for item in release.artifacts]
    observed_paths: set[str] = set()
    for item in descriptors:
        if not isinstance(item, Mapping):
            raise FederalRegisterProductionOperatorError(
                "Federal candidate descriptor entries must be objects"
            )
        path = str(item.get("relative_path") or "")
        if not path or path.startswith("/") or ".." in Path(path).parts:
            raise FederalRegisterProductionOperatorError(
                "Federal candidate descriptor path is unsafe"
            )
        if path in observed_paths:
            raise FederalRegisterProductionOperatorError(
                "Federal candidate descriptor paths are not unique"
            )
        observed_paths.add(path)
    if canonical_json_bytes(list(descriptors)) != canonical_json_bytes(
        expected_descriptors
    ):
        raise FederalRegisterProductionOperatorError(
            "Federal candidate descriptors differ from exact release bytes"
        )
    manifest = release.manifest_dict()
    expected_nested = {
        "build_config_cid": release.build_config_cid,
        "dataset_id": release.dataset_id,
        "default_config": manifest.get("default_config"),
        "manifest_digest": release.manifest_digest,
        "observation_cutoff": release.observation_cutoff,
        "official_document_count": int(
            (manifest.get("corpus") or {}).get("row_count") or 0
        ),
        "package_version": release.package_version,
        "release_profile": release.release_profile,
        "release_root_cid": release.release_root_cid,
        "source_revision": release.source_revision,
        "vector_space_id": release.vector_space_id,
    }
    if (
        any(nested.get(key) != value for key, value in expected_nested.items())
        or candidate.get("configs")
        != [configuration.config_name for configuration in release.configs]
        or canonical_json_bytes(candidate.get("semantic_family_closure"))
        != canonical_json_bytes(manifest.get("semantic_family_closure"))
    ):
        raise FederalRegisterProductionOperatorError(
            "Federal candidate metadata differs from exact release bytes"
        )
    rights = candidate.get("source_rights")
    if (
        not isinstance(rights, Mapping)
        or rights.get("receipt_digest") != release.source_rights_receipt_digest
    ):
        raise FederalRegisterProductionOperatorError(
            "Federal candidate source-rights digest differs from release bytes"
        )


def execute_federal_staging_operator_path(
    *,
    release: FederalRegisterHuggingFaceRelease,
    candidate: Mapping[str, Any],
    output_root: Path | str,
    branch_approval: PublicationApproval,
    commit_approval: PublicationApproval,
    repository_root: Path | str = REPOSITORY_ROOT,
    audited_parent_commit: str = PRODUCTION_REVISION,
) -> dict[str, Any]:
    """Execute the separately approved branch/create-commit staging path."""

    require_production_release_candidate(release=release, candidate=candidate)
    if type(branch_approval) is not PublicationApproval or type(
        commit_approval
    ) is not PublicationApproval:
        raise FederalRegisterProductionOperatorError(
            "Federal staging requires two exact PublicationApproval objects"
        )
    if branch_approval.approval_id == commit_approval.approval_id:
        raise FederalRegisterProductionOperatorError(
            "Federal branch and commit approvals must be independent"
        )
    return execute_canonical_staging_release(
        release=release,
        output_root=output_root,
        candidate=candidate,
        branch_approval=branch_approval,
        commit_approval=commit_approval,
        repository_root=repository_root,
        audited_parent_commit=audited_parent_commit,
    )


def execute_federal_staging_canary_operator_path(
    *,
    release: FederalRegisterHuggingFaceRelease,
    candidate: Mapping[str, Any],
    staging_receipt: Mapping[str, Any],
    remote_descriptors: Sequence[Mapping[str, Any]],
    fetch_file: Callable[[str, str, str], bytes],
    inventory: Mapping[str, Any],
    fulltext: Mapping[str, Any],
    repository_root: Path | str = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Run the immutable read-only staging canary with injected Hub reads."""

    require_production_release_candidate(release=release, candidate=candidate)
    if not isinstance(staging_receipt, Mapping):
        raise FederalRegisterProductionOperatorError(
            "sealed live staging receipt is required"
        )
    revision = str(staging_receipt.get("staging_revision") or "")
    repo_id = str(staging_receipt.get("target_repo") or "")
    descriptors = [item.descriptor_dict() for item in release.artifacts]
    return run_remote_canary(
        repo_id=repo_id,
        revision=revision,
        staging_receipt=staging_receipt,
        candidate=candidate,
        artifact_descriptors=descriptors,
        remote_descriptors=remote_descriptors,
        fetch_file=fetch_file,
        inventory=inventory,
        fulltext=fulltext,
        repo_root=repository_root,
    )


def generate_federal_main_seal_operator_path(
    *,
    release: FederalRegisterHuggingFaceRelease,
    candidate: Mapping[str, Any],
    output_root: Path | str,
    main_approval: PublicationApproval,
    staging_revision: str,
    sealed_at: str,
    repository_root: Path | str = REPOSITORY_ROOT,
    audited_parent_commit: str = PRODUCTION_REVISION,
) -> dict[str, Any]:
    """Generate and check LCR-073 without performing the main mutation."""

    require_production_release_candidate(release=release, candidate=candidate)
    if type(main_approval) is not PublicationApproval:
        raise FederalRegisterProductionOperatorError(
            "Federal main seal requires an exact PublicationApproval"
        )
    package, _publisher, plan = build_canonical_main_plan(
        release=release,
        output_root=output_root,
        audited_parent_commit=audited_parent_commit,
        candidate=candidate,
    )
    if main_approval.plan_digest != plan.plan_digest:
        raise FederalRegisterProductionOperatorError(
            "Federal main approval does not bind the reviewed plan"
        )
    controls, checked = generate_federal_prepublication_seal(
        package=package,
        plan=plan,
        staging_revision=staging_revision,
        sealed_at=sealed_at,
        repository_root=repository_root,
        no_mutate=True,
    )
    return {"check": checked, "controls": controls.to_dict()}


def execute_federal_main_operator_path(
    *,
    release: FederalRegisterHuggingFaceRelease,
    candidate: Mapping[str, Any],
    output_root: Path | str,
    main_approval: PublicationApproval,
    staging_revision: str,
    sealed_at: str,
    repository_root: Path | str = REPOSITORY_ROOT,
    audited_parent_commit: str = PRODUCTION_REVISION,
) -> dict[str, Any]:
    """Execute the exact sealed Federal main commit through canonical runtime."""

    require_production_release_candidate(release=release, candidate=candidate)
    if type(main_approval) is not PublicationApproval:
        raise FederalRegisterProductionOperatorError(
            "Federal main publication requires an exact PublicationApproval"
        )
    root = Path(repository_root).expanduser().resolve()
    candidate_path = root / CANONICAL_CANDIDATE_RELPATH
    if not candidate_path.is_file():
        raise FederalRegisterProductionOperatorError(
            "canonical Federal candidate file is missing"
        )
    try:
        canonical_candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FederalRegisterProductionOperatorError(
            "canonical Federal candidate file is malformed"
        ) from exc
    if canonical_json_bytes(canonical_candidate) != canonical_json_bytes(dict(candidate)):
        raise FederalRegisterProductionOperatorError(
            "in-memory Federal candidate differs from canonical controls"
        )
    return execute_canonical_main_release(
        release=release,
        output_root=output_root,
        approval=main_approval,
        staging_revision=staging_revision,
        sealed_at=sealed_at,
        repository_root=root,
        audited_parent_commit=audited_parent_commit,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect the injection-only Federal production operator bridge"
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.check:
        sys.stderr.write(
            "run_federal_register_production_release: FAILED: --check is required; "
            "live mutation is available only through the in-memory operator API\n"
        )
        return 2
    payload = {
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "cli_live_mutation": False,
        "in_memory_candidate_required": True,
        "network_contacted": False,
        "ok": True,
        "program_id": PROGRAM_ID,
        "schema": SCHEMA,
        "separate_staging_approvals_required": True,
        "task_ids": list(TASK_IDS),
    }
    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "run_federal_register_production_release: PASS "
            "cli_live_mutation=false in_memory_candidate_required=true\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
