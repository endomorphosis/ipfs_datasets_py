#!/usr/bin/env python3
"""Stage / approve / promote JusticeDAO patent HF v2 releases.

Default mode is **dry-run** (PATLAW-168 / PATLAW-159):

1. Verify the local release **manifest** against on-disk digests.
2. Run public-release **DLP / rights** gates and **Dataset Viewer** contracts
   offline (credential-free; no Hub network contact).
3. Build a multi-repo stage plan with plan/staged-diff digests.
4. Emit a staging receipt for human approval — without uploading to ``main``
   or mutating remote default branches.

Operator workflow after a successful dry-run receipt:

1. ``--mode dry-run``  — plan + gate verification only (default)
2. ``--mode stage``    — authenticated add-only branch + PR (requires HF_TOKEN)
3. ``--mode sign``     — create operator approval from an external key file
4. ``--mode promote``  — merge staged PRs after verifying operator approval

This script never:

* uploads directly to ``main`` / ``master``;
* embeds or logs Hub tokens;
* moves runtime release pointers (see verify_patent_hf_release_v2 / PATLAW-160);
* self-approves without an external operator key file;
* mutates remote default branches during dry-run.

``--fake-service`` exercises the offline stage/promote path for supervisor tests.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Final, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (  # noqa: E402
    ORGANIZATION,
)
from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (  # noqa: E402
    ApprovalError,
    ArtifactChangedError,
    AuthError,
    BaseRevisionError,
    ConflictError,
    DEFAULT_TARGET_REVISION,
    FakeHubService,
    PartialUploadError,
    PatentHFPublisherV2,
    PatentHFPublisherV2Error,
    create_operator_approval,
    load_release_manifest,
    materialize_minimal_release_tree,
    plan_stage_from_local_root,
    reject_credentials_in_payload,
    resolve_hub_token,
)
from ipfs_datasets_py.processors.domains.patent.hf_release_policy_v2 import (  # noqa: E402
    DEFAULT_MAX_SOURCE_AGE_DAYS,
    RELEASE_POLICY_V2_SHA256,
    RELEASE_POLICY_V2_VERSION,
    VIEWER_ENDPOINTS,
    AdmissionRejectedError,
    CredentialPrematureError,
    FakeDatasetViewerService,
    FakeViewerGateway,
    PatentHFReleasePolicyV2,
    ReleasePolicyV2Error,
    assert_credentials_unresolved,
    load_staged_release_inventory,
)
from ipfs_datasets_py.processors.domains.patent.hf_release_v2 import (  # noqa: E402
    RELEASE_MANIFEST_FILENAME,
)


# ---------------------------------------------------------------------------
# Identity / schema (PATLAW-168 post-completion hub dry-run)
# ---------------------------------------------------------------------------

TASK_ID: Final = "PATLAW-168"
GOAL_ID: Final = "PATLAW-G202"
PROGRAM_ID: Final = "patent-legal-intelligence"
DRY_RUN_RECEIPT_SCHEMA: Final = "patent-legal-hf-dry-run-staging-receipt/v1"
EXPECTED_GATE_NAMES: Final[tuple[str, ...]] = (
    "cards_configs",
    "parquet",
    "rights_dlp",
    "orphans",
    "count_parity",
    "stale_sources",
    "dataset_viewer",
)
PROHIBITED_DEFAULT_BRANCHES: Final[frozenset[str]] = frozenset(
    {"main", "master", "refs/heads/main", "refs/heads/master"}
)


class StagePatentHFReleaseError(RuntimeError):
    """CLI-level failure (fail-closed)."""


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StagePatentHFReleaseError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise StagePatentHFReleaseError(f"JSON root must be an object: {path}")
    return dict(payload)


def _load_base_revisions(raw: str | None, path: Path | None) -> dict[str, str]:
    if path is not None:
        data = _load_json_object(path)
        return {str(k): str(v) for k, v in data.items()}
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StagePatentHFReleaseError(
                f"invalid --base-revisions JSON: {exc}"
            ) from exc
        if not isinstance(data, Mapping):
            raise StagePatentHFReleaseError("--base-revisions must be a JSON object")
        return {str(k): str(v) for k, v in data.items()}
    raise StagePatentHFReleaseError(
        "base revisions are required (--base-revisions or --base-revisions-file)"
    )


def _load_operator_key(path: Path | None, env_name: str = "PATENT_HF_OPERATOR_APPROVAL_KEY") -> bytes:
    if path is not None:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise StagePatentHFReleaseError(
                f"cannot read operator key file: {path}: {exc}"
            ) from exc
        return raw.strip()
    env_val = os.environ.get(env_name, "").strip()
    if env_val:
        return env_val.encode("utf-8")
    raise StagePatentHFReleaseError(
        f"operator key required via --operator-key-file or ${env_name}"
    )


def _write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def verify_manifest_integrity(
    local_root: str | Path,
    *,
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify release-manifest.json exists and every listed artifact matches disk.

    Digest/size mismatches fail closed. This is the local half of publication
    planning and does not contact the Hub.
    """

    root = Path(local_root).expanduser().resolve()
    if not root.is_dir():
        raise StagePatentHFReleaseError(f"local_root is not a directory: {root}")

    if manifest is None:
        manifest_path = root / RELEASE_MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise StagePatentHFReleaseError(
                f"missing {RELEASE_MANIFEST_FILENAME} under {root}"
            )
        manifest = load_release_manifest(manifest_path)
    else:
        manifest = dict(manifest)

    # plan_stage_from_local_root re-hashes every listed artifact; use a
    # throwaway base-revision map only when callers want a pure integrity check
    # without a stage plan. Prefer calling through run_dry_run for receipts.
    artifacts = manifest.get("artifacts") or manifest.get("files") or []
    if not isinstance(artifacts, list) or not artifacts:
        raise StagePatentHFReleaseError(
            "manifest must declare a non-empty artifacts/files list"
        )

    checked: list[dict[str, Any]] = []
    from hashlib import sha256 as _sha256

    for index, item in enumerate(artifacts):
        if not isinstance(item, Mapping):
            raise StagePatentHFReleaseError(f"artifacts[{index}] must be an object")
        rel = str(item.get("relative_path") or item.get("path") or "").strip()
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            raise StagePatentHFReleaseError(
                f"artifacts[{index}] has unsafe relative_path: {rel!r}"
            )
        path = root.joinpath(*Path(rel).parts)
        if not path.is_file() or path.is_symlink():
            raise StagePatentHFReleaseError(
                f"manifest artifact missing or not a regular file: {rel}"
            )
        body = path.read_bytes()
        digest = _sha256(body).hexdigest()
        expected = str(item.get("sha256") or "").strip().casefold()
        if expected and digest != expected:
            raise StagePatentHFReleaseError(
                f"manifest digest mismatch for {rel}: disk={digest} manifest={expected}"
            )
        expected_size = item.get("size_bytes")
        if expected_size is not None and int(expected_size) != len(body):
            raise StagePatentHFReleaseError(
                f"manifest size mismatch for {rel}: disk={len(body)} "
                f"manifest={expected_size}"
            )
        checked.append(
            {
                "relative_path": rel,
                "sha256": digest,
                "size_bytes": len(body),
                "repository": item.get("repository"),
            }
        )

    release_root_cid = str(manifest.get("release_root_cid") or "").strip()
    version_tag = str(manifest.get("version_tag") or "").strip()
    organization = str(manifest.get("organization") or ORGANIZATION).strip()
    repositories = manifest.get("repositories") or []
    repo_ids: list[str] = []
    if isinstance(repositories, list):
        for entry in repositories:
            if isinstance(entry, Mapping):
                dataset_id = entry.get("dataset_id") or entry.get("id")
                if dataset_id:
                    repo_ids.append(str(dataset_id))
                elif entry.get("repository"):
                    repo_ids.append(f"{organization}/{entry['repository']}")
            elif isinstance(entry, str):
                repo_ids.append(
                    entry if "/" in entry else f"{organization}/{entry}"
                )

    payload = {
        "artifact_count": len(checked),
        "artifacts": checked,
        "manifest_path": str(root / RELEASE_MANIFEST_FILENAME),
        "organization": organization,
        "release_root_cid": release_root_cid or None,
        "repository_ids": sorted(set(repo_ids)),
        "schema_version": str(manifest.get("schema_version") or ""),
        "status": "manifest_verified",
        "version_tag": version_tag or None,
        "verified": True,
    }
    reject_credentials_in_payload(payload, label="manifest_verification")
    return payload


def run_admission_gates(
    local_root: str | Path,
    *,
    as_of: str = "2026-08-01",
    max_source_age_days: int = DEFAULT_MAX_SOURCE_AGE_DAYS,
    run_viewer_gate: bool = True,
    force_viewer_invalid: bool = False,
    require_admitted: bool = False,
) -> dict[str, Any]:
    """Run DLP / rights / Dataset Viewer admission gates offline.

    Credentials must remain unresolved. No Hub network contact. A bare
    ``viewer: true`` HTTP response is never sufficient — every Viewer
    endpoint is checked against the staged inventory via the fake gateway.
    """

    root = Path(local_root).expanduser().resolve()
    if not root.is_dir():
        raise StagePatentHFReleaseError(f"local_root is not a directory: {root}")

    try:
        assert_credentials_unresolved()
    except CredentialPrematureError as exc:
        raise StagePatentHFReleaseError(str(exc)) from exc

    try:
        inventory = load_staged_release_inventory(root)
    except ReleasePolicyV2Error as exc:
        raise StagePatentHFReleaseError(f"cannot load staged inventory: {exc}") from exc

    viewer_gateway = None
    if run_viewer_gate:
        service = FakeDatasetViewerService(
            inventory=inventory, force_invalid=force_viewer_invalid
        )
        viewer_gateway = FakeViewerGateway(service)

    policy = PatentHFReleasePolicyV2(
        as_of=as_of, max_source_age_days=max_source_age_days
    )
    try:
        decision = policy.admit_public_release(
            inventory=inventory,
            viewer_gateway=viewer_gateway,
            run_viewer_gate=run_viewer_gate,
        )
    except (ReleasePolicyV2Error, CredentialPrematureError) as exc:
        raise StagePatentHFReleaseError(str(exc)) from exc

    gate_results = [item.to_dict() for item in decision.gate_results]
    gate_names = [item["name"] for item in gate_results]
    viewer_gate = next(
        (g for g in gate_results if g.get("name") == "dataset_viewer"), None
    )
    rights_gate = next(
        (g for g in gate_results if g.get("name") == "rights_dlp"), None
    )

    payload: dict[str, Any] = {
        "admitted": decision.admitted,
        "credentials_resolved": decision.credentials_resolved,
        "expected_gate_names": list(EXPECTED_GATE_NAMES),
        "expected_policy_sha256": RELEASE_POLICY_V2_SHA256,
        "expected_policy_version": RELEASE_POLICY_V2_VERSION,
        "finding_count": len(decision.findings),
        "findings": [item.to_dict() for item in decision.findings],
        "gate_names": gate_names,
        "gate_results": gate_results,
        "policy_sha256": decision.policy_sha256,
        "policy_version": decision.policy_version,
        "reason_codes": list(decision.reason_codes),
        "rights_dlp_passed": bool(rights_gate and rights_gate.get("passed")),
        "viewer_contracts_passed": bool(
            viewer_gate and viewer_gate.get("passed")
        )
        if run_viewer_gate
        else None,
        "viewer_endpoints_checked": list(VIEWER_ENDPOINTS)
        if run_viewer_gate
        else [],
    }
    if decision.policy_sha256 != RELEASE_POLICY_V2_SHA256:
        payload["reason_codes"] = sorted(
            set(payload["reason_codes"]) | {"policy.drift"}
        )
        payload["admitted"] = False

    if require_admitted and not payload["admitted"]:
        raise AdmissionRejectedError(
            "public release rejected before credentials: "
            + ", ".join(payload["reason_codes"])
        )
    reject_credentials_in_payload(payload, label="admission_gates")
    return payload


def run_dry_run(
    *,
    local_root: Path,
    manifest: Mapping[str, Any] | None,
    organization: str,
    base_revisions: Mapping[str, str],
    branch_name: str | None,
    target_revision: str,
    version_tag: str | None,
    release_id: str | None,
    verify_gates: bool = True,
    require_admitted: bool = False,
    as_of: str = "2026-08-01",
    max_source_age_days: int = DEFAULT_MAX_SOURCE_AGE_DAYS,
    force_viewer_invalid: bool = False,
) -> dict[str, Any]:
    """Dry-run staging verification: manifests + DLP/rights + viewer + plan.

    Never contacts the Hub, never reads tokens for upload, never mutates
    remote default branches. Produces a content-addressed staging receipt for
    human approval (PATLAW-168).
    """

    root = Path(local_root).expanduser().resolve()

    # 1. Explicit manifest integrity (digests/sizes on disk).
    manifest_report = verify_manifest_integrity(root, manifest=manifest)

    # 2. Stage plan (re-validates digests; binds base revisions; no Hub).
    plan = plan_stage_from_local_root(
        local_root=root,
        manifest=manifest,
        organization=organization,
        version_tag=version_tag,
        base_revisions=base_revisions,
        branch_name=branch_name,
        target_revision=target_revision,
        release_id=release_id,
    )

    if plan.branch_name.casefold() in PROHIBITED_DEFAULT_BRANCHES:
        raise StagePatentHFReleaseError(
            f"stage branch must not target a default branch: {plan.branch_name}"
        )

    # 3. DLP / rights / Viewer admission (optional skip for pure plan drills).
    admission: dict[str, Any] | None = None
    if verify_gates:
        admission = run_admission_gates(
            root,
            as_of=as_of,
            max_source_age_days=max_source_age_days,
            run_viewer_gate=True,
            force_viewer_invalid=force_viewer_invalid,
            require_admitted=require_admitted,
        )

    plan_payload = plan.to_dict()
    admitted = bool(admission and admission.get("admitted"))
    verification_status = (
        "verified"
        if (admission is None or admitted)
        else "rejected"
    )
    if admission is None:
        verification_status = "plan_only"

    payload: dict[str, Any] = {
        **plan_payload,
        # Backward-compatible dry-run status (PATLAW-159 CLI contract).
        "status": "dry_run_only",
        "verification_status": verification_status,
        "receipt_schema": DRY_RUN_RECEIPT_SCHEMA,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "live_network": False,
        "tokens_used": False,
        "main_published": False,
        "pointers_moved": False,
        "remote_write_contacted": False,
        "remote_default_branches_mutated": False,
        "uses_hf_api_upload_file": False,
        "authenticated_upload": False,
        "dry_run": True,
        "manifest_verified": True,
        "manifest_verification": {
            "artifact_count": manifest_report["artifact_count"],
            "organization": manifest_report["organization"],
            "release_root_cid": manifest_report["release_root_cid"],
            "repository_ids": manifest_report["repository_ids"],
            "schema_version": manifest_report["schema_version"],
            "status": manifest_report["status"],
            "verified": True,
            "version_tag": manifest_report["version_tag"],
        },
        "gates_run": verify_gates,
        "admitted": admitted if verify_gates else None,
        "dlp_rights_gates": admission,
        "viewer_contracts": {
            "passed": admission.get("viewer_contracts_passed")
            if admission
            else None,
            "endpoints_checked": (
                list(admission.get("viewer_endpoints_checked") or [])
                if admission
                else []
            ),
            "gate": next(
                (
                    g
                    for g in (admission or {}).get("gate_results") or []
                    if g.get("name") == "dataset_viewer"
                ),
                None,
            ),
        }
        if verify_gates
        else None,
        "human_approval_required": True,
        "next_operator_actions": [
            "Review plan_digest and staged_diff_digest",
            "Review DLP/rights and viewer gate results",
            "Only then run --mode stage with an operator-held Hub token",
            "Never auto-promote main without --mode sign + --mode promote",
        ],
        "repository_ids": sorted(set(plan.dataset_ids())),
    }
    reject_credentials_in_payload(payload, label="dry_run_receipt")
    return payload


def run_stage(
    *,
    local_root: Path,
    manifest: Mapping[str, Any] | None,
    organization: str,
    base_revisions: Mapping[str, str],
    branch_name: str | None,
    target_revision: str,
    version_tag: str | None,
    release_id: str | None,
    fake_service: bool,
    token_env: str,
    create_pr: bool,
) -> dict[str, Any]:
    plan = plan_stage_from_local_root(
        local_root=local_root,
        manifest=manifest,
        organization=organization,
        version_tag=version_tag,
        base_revisions=base_revisions,
        branch_name=branch_name,
        target_revision=target_revision,
        release_id=release_id,
    )
    if fake_service:
        api = FakeHubService(base_revisions=base_revisions, require_auth=True)
        token = api.auth_token
    else:
        env_token = os.environ.get(token_env) or None
        token = resolve_hub_token(token=env_token, allow_missing=False)
        # Live clients are never constructed here — operators inject via tests
        # or a future thin adapter.  Fail closed without --fake-service unless
        # an explicit injection path is provided.
        raise StagePatentHFReleaseError(
            "live Hub stage requires an injected API client; use --fake-service "
            "for offline verification, or call PatentHFPublisherV2 from an "
            "operator-controlled process with an authenticated HfApi"
        )

    publisher = PatentHFPublisherV2(
        api=api, token=token, organization=organization
    )
    staged = publisher.stage_pull_request(
        plan, local_root=local_root, create_pr=create_pr
    )
    payload = staged.to_dict()
    payload["plan"] = plan.to_dict()
    payload["live_network"] = not fake_service
    payload["tokens_used"] = False  # token never recorded
    payload["fake_service"] = fake_service
    reject_credentials_in_payload(payload, label="stage_receipt")
    return payload


def run_sign(
    *,
    local_root: Path,
    manifest: Mapping[str, Any] | None,
    organization: str,
    base_revisions: Mapping[str, str],
    branch_name: str | None,
    target_revision: str,
    version_tag: str | None,
    release_id: str | None,
    operator_key: bytes,
    approver: str,
    approval_id: str,
) -> dict[str, Any]:
    plan = plan_stage_from_local_root(
        local_root=local_root,
        manifest=manifest,
        organization=organization,
        version_tag=version_tag,
        base_revisions=base_revisions,
        branch_name=branch_name,
        target_revision=target_revision,
        release_id=release_id,
    )
    approval = create_operator_approval(
        plan=plan,
        operator_key=operator_key,
        approver=approver,
        approval_id=approval_id,
    )
    payload = approval.to_dict()
    payload["plan_digest_bound"] = plan.plan_digest
    payload["staged_diff_digest_bound"] = plan.staged_diff_digest
    reject_credentials_in_payload(payload, label="approval_out")
    return payload


def run_promote(
    *,
    local_root: Path,
    manifest: Mapping[str, Any] | None,
    organization: str,
    base_revisions: Mapping[str, str],
    branch_name: str | None,
    target_revision: str,
    version_tag: str | None,
    release_id: str | None,
    approval_file: Path,
    staged_receipt_file: Path,
    operator_key: bytes,
    fake_service: bool,
    token_env: str,
) -> dict[str, Any]:
    plan = plan_stage_from_local_root(
        local_root=local_root,
        manifest=manifest,
        organization=organization,
        version_tag=version_tag,
        base_revisions=base_revisions,
        branch_name=branch_name,
        target_revision=target_revision,
        release_id=release_id,
    )
    approval_payload = _load_json_object(approval_file)
    staged_payload = _load_json_object(staged_receipt_file)

    # Rebuild staged receipt from file.
    from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (
        RepositoryStageResult,
        StagedPRReceipt,
    )

    repos = tuple(
        RepositoryStageResult(
            dataset_id=str(item["dataset_id"]),
            base_commit=str(item["base_commit"]),
            branch_name=str(item["branch_name"]),
            staged_commit_sha=str(item["staged_commit_sha"]),
            uploaded_paths=tuple(item.get("uploaded_paths") or ()),
            upload_bytes=int(item.get("upload_bytes") or 0),
            pull_request_number=(
                int(item["pull_request_number"])
                if item.get("pull_request_number") is not None
                else None
            ),
        )
        for item in staged_payload.get("repositories") or ()
    )
    staged = StagedPRReceipt(
        schema_version=str(staged_payload.get("schema_version") or ""),
        organization=str(staged_payload["organization"]),
        version_tag=str(staged_payload["version_tag"]),
        release_root_cid=str(staged_payload["release_root_cid"]),
        release_id=str(staged_payload["release_id"]),
        plan_digest=str(staged_payload["plan_digest"]),
        staged_diff_digest=str(staged_payload["staged_diff_digest"]),
        branch_name=str(staged_payload["branch_name"]),
        repositories=repos,
        status=str(staged_payload.get("status") or "staged_pending_approval"),
        main_published=False,
        pointers_moved=False,
        credentials_scope=str(staged_payload.get("credentials_scope") or ""),
        token_material_present=False,
    )

    if fake_service:
        # Rebuild service state by re-staging (deterministic fake path).
        api = FakeHubService(base_revisions=base_revisions, require_auth=True)
        token = api.auth_token
        publisher = PatentHFPublisherV2(
            api=api, token=token, organization=organization
        )
        # Re-stage so PR numbers exist in the fake service, then promote using
        # the freshly staged receipt (digests must still match the plan).
        restaged = publisher.stage_pull_request(plan, local_root=local_root)
        if restaged.plan_digest != staged.plan_digest:
            raise StagePatentHFReleaseError(
                "restaged plan_digest diverged from staged receipt"
            )
        promotion = publisher.promote_approved(
            plan,
            staged=restaged,
            approval=approval_payload,
            operator_key=operator_key,
            local_root=local_root,
        )
    else:
        raise StagePatentHFReleaseError(
            "live Hub promote requires an injected API client; use --fake-service "
            "for offline verification"
        )

    payload = promotion.to_dict()
    payload["live_network"] = not fake_service
    payload["tokens_used"] = False
    payload["fake_service"] = fake_service
    payload["pointers_moved"] = False
    reject_credentials_in_payload(payload, label="promote_receipt")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run Hub staging verification (manifests, DLP/rights, viewer) "
            "and optional stage/sign/promote for patent-legal HF v2 releases. "
            "Default mode never uploads to main or mutates remote default branches."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("dry-run", "stage", "sign", "promote"),
        default="dry-run",
        help="Workflow mode (default: dry-run; no Hub contact)",
    )
    parser.add_argument(
        "--local-root",
        type=Path,
        help="Local staged release directory containing release-manifest.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Optional explicit path to release-manifest.json",
    )
    parser.add_argument(
        "--organization",
        default=ORGANIZATION,
        help=f"Hub organization (default: {ORGANIZATION})",
    )
    parser.add_argument(
        "--base-revisions",
        help='JSON object mapping dataset_id → audited base commit SHA',
    )
    parser.add_argument(
        "--base-revisions-file",
        type=Path,
        help="Path to JSON object of dataset_id → base commit SHA",
    )
    parser.add_argument(
        "--branch-name",
        help="Stage branch name (default: stage/patent-legal/<release_id>)",
    )
    parser.add_argument(
        "--target-revision",
        default=DEFAULT_TARGET_REVISION,
        help="Promotion target revision (default: main)",
    )
    parser.add_argument(
        "--version-tag",
        help="Override version tag from the manifest",
    )
    parser.add_argument(
        "--release-id",
        help="Override release id",
    )
    parser.add_argument(
        "--receipt-out",
        type=Path,
        help="Write plan/stage/promote receipt JSON to this path",
    )
    parser.add_argument(
        "--approval-out",
        type=Path,
        help="Write operator approval JSON (sign mode)",
    )
    parser.add_argument(
        "--approval-file",
        type=Path,
        help="Operator approval JSON to consume (promote mode)",
    )
    parser.add_argument(
        "--staged-receipt-file",
        type=Path,
        help="Staged PR receipt JSON from stage mode (promote mode)",
    )
    parser.add_argument(
        "--operator-key-file",
        type=Path,
        help="External operator HMAC key file (sign/promote); never a Hub token",
    )
    parser.add_argument(
        "--approver",
        default="patent-legal-operator",
        help="Approver identity recorded on the approval receipt",
    )
    parser.add_argument(
        "--approval-id",
        default="operator-approval-1",
        help="Stable approval id",
    )
    parser.add_argument(
        "--token-env",
        default="HF_TOKEN",
        help="Environment variable holding the Hub token for stage/promote",
    )
    parser.add_argument(
        "--fake-service",
        action="store_true",
        help="Use in-memory FakeHubService (no network; supervisor-safe)",
    )
    parser.add_argument(
        "--materialize-fixture",
        type=Path,
        help="Write a minimal multi-repo fixture tree to this path and exit",
    )
    parser.add_argument(
        "--no-create-pr",
        action="store_true",
        help="Stage branches/commits without opening pull requests",
    )
    # PATLAW-168 dry-run gate controls
    parser.add_argument(
        "--skip-admission-gates",
        action="store_true",
        help="Skip DLP/rights/viewer gates (plan + manifest only; not recommended)",
    )
    parser.add_argument(
        "--require-admitted",
        action="store_true",
        help="Exit non-zero when DLP/rights/viewer admission is refused",
    )
    parser.add_argument(
        "--as-of",
        default="2026-08-01",
        help="Reference date for mandatory source freshness (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--max-source-age-days",
        type=int,
        default=DEFAULT_MAX_SOURCE_AGE_DAYS,
        help=f"Maximum age of mandatory sources (default {DEFAULT_MAX_SOURCE_AGE_DAYS})",
    )
    parser.add_argument(
        "--force-viewer-invalid",
        action="store_true",
        help="Force fake Viewer is-valid=false (negative testing)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.materialize_fixture is not None:
        manifest = materialize_minimal_release_tree(args.materialize_fixture)
        _write_json(args.receipt_out, {
            "status": "fixture_materialized",
            "root": str(args.materialize_fixture),
            "artifact_count": len(manifest.get("artifacts") or ()),
            "release_root_cid": manifest.get("release_root_cid"),
        })
        return 0

    if args.local_root is None:
        parser.error("--local-root is required unless --materialize-fixture is set")

    local_root = args.local_root.expanduser().resolve()
    manifest = None
    if args.manifest is not None:
        manifest = load_release_manifest(args.manifest)

    try:
        if args.mode == "dry-run":
            bases = _load_base_revisions(args.base_revisions, args.base_revisions_file)
            payload = run_dry_run(
                local_root=local_root,
                manifest=manifest,
                organization=args.organization,
                base_revisions=bases,
                branch_name=args.branch_name,
                target_revision=args.target_revision,
                version_tag=args.version_tag,
                release_id=args.release_id,
                verify_gates=not args.skip_admission_gates,
                require_admitted=bool(args.require_admitted),
                as_of=args.as_of,
                max_source_age_days=args.max_source_age_days,
                force_viewer_invalid=bool(args.force_viewer_invalid),
            )
            _write_json(args.receipt_out, payload)
            if args.require_admitted and payload.get("gates_run") and not payload.get(
                "admitted"
            ):
                return 1
            return 0

        if args.mode == "stage":
            bases = _load_base_revisions(args.base_revisions, args.base_revisions_file)
            payload = run_stage(
                local_root=local_root,
                manifest=manifest,
                organization=args.organization,
                base_revisions=bases,
                branch_name=args.branch_name,
                target_revision=args.target_revision,
                version_tag=args.version_tag,
                release_id=args.release_id,
                fake_service=bool(args.fake_service),
                token_env=args.token_env,
                create_pr=not args.no_create_pr,
            )
            _write_json(args.receipt_out, payload)
            return 0

        if args.mode == "sign":
            bases = _load_base_revisions(args.base_revisions, args.base_revisions_file)
            key = _load_operator_key(args.operator_key_file)
            payload = run_sign(
                local_root=local_root,
                manifest=manifest,
                organization=args.organization,
                base_revisions=bases,
                branch_name=args.branch_name,
                target_revision=args.target_revision,
                version_tag=args.version_tag,
                release_id=args.release_id,
                operator_key=key,
                approver=args.approver,
                approval_id=args.approval_id,
            )
            out = args.approval_out or args.receipt_out
            _write_json(out, payload)
            return 0

        if args.mode == "promote":
            if args.approval_file is None or args.staged_receipt_file is None:
                parser.error(
                    "promote requires --approval-file and --staged-receipt-file"
                )
            bases = _load_base_revisions(args.base_revisions, args.base_revisions_file)
            key = _load_operator_key(args.operator_key_file)
            payload = run_promote(
                local_root=local_root,
                manifest=manifest,
                organization=args.organization,
                base_revisions=bases,
                branch_name=args.branch_name,
                target_revision=args.target_revision,
                version_tag=args.version_tag,
                release_id=args.release_id,
                approval_file=args.approval_file,
                staged_receipt_file=args.staged_receipt_file,
                operator_key=key,
                fake_service=bool(args.fake_service),
                token_env=args.token_env,
            )
            _write_json(args.receipt_out, payload)
            return 0

        parser.error(f"unknown mode: {args.mode}")
        return 2
    except AdmissionRejectedError as exc:
        sys.stderr.write(f"rejected: {exc}\n")
        return 1
    except (
        StagePatentHFReleaseError,
        PatentHFPublisherV2Error,
        ApprovalError,
        ArtifactChangedError,
        AuthError,
        BaseRevisionError,
        ConflictError,
        PartialUploadError,
        CredentialPrematureError,
        ReleasePolicyV2Error,
    ) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
