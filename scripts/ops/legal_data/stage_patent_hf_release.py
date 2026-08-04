#!/usr/bin/env python3
"""Stage / approve / promote JusticeDAO patent HF v2 releases (PATLAW-159).

Default mode is **dry-run**: build a multi-repo stage plan from a local release
tree, print digests, and exit without Hub contact or token use.

Operator workflow:

1. ``--mode dry-run``  — plan only (default)
2. ``--mode stage``    — authenticated add-only branch + PR (requires HF_TOKEN)
3. ``--mode sign``     — create operator approval from an external key file
4. ``--mode promote``  — merge staged PRs after verifying operator approval

This script never:

* uploads directly to ``main``;
* embeds or logs Hub tokens;
* moves runtime release pointers (see verify_patent_hf_release_v2 / PATLAW-160);
* self-approves without an external operator key file.

``--fake-service`` exercises the full offline path for supervisor tests.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stage an authenticated Hub PR for patent-legal HF v2 releases, "
            "require exact operator approval, and promote only when approved."
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
    return parser


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
    payload = plan.to_dict()
    payload["status"] = "dry_run_only"
    payload["live_network"] = False
    payload["tokens_used"] = False
    payload["main_published"] = False
    payload["pointers_moved"] = False
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
            )
            _write_json(args.receipt_out, payload)
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
    except (
        StagePatentHFReleaseError,
        PatentHFPublisherV2Error,
        ApprovalError,
        ArtifactChangedError,
        AuthError,
        BaseRevisionError,
        ConflictError,
        PartialUploadError,
    ) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
