"""Lease-gated, append-only publication of a packaged IR release.

Autonomous workers stop after a dry-run.  A remote write requires:

* an explicit :class:`PublicationLease` on ``hf-publication:<repo>``;
* a qualified package (P1 configs, cards, P4 evidence, distinct counts);
* human :class:`PublicationApproval` of the exact plan digest; and
* an injected Hugging Face API client.

Partial uploads retry by skipping exact path+digest matches only.  Basename
collisions never skip.  Mismatched remote objects are refused (no overwrite).
Published versions are never deleted; rollback emits a supersession record.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Final

from .ir_release import (
    DEFAULT_IR_DATASET_REPO_ID,
    DEFAULT_POINTER_PATH,
    DEFAULT_RELEASE_PREFIX_TEMPLATE,
    IRPublicationPolicy,
    IRReleasePackage,
    package_ir_release,
    validate_ir_release_package,
)
from .publisher import (
    HuggingFacePublicationError,
    HuggingFaceReleasePublisher,
    PublicationApproval,
    PublicationCommitReceipt,
    PublicationPlan,
    _reject_secrets,
    _write_receipt,
    estimate_publication_cost,
)
from .release import canonical_json_bytes as _canonical_json_bytes


IR_PUBLICATION_RECEIPT_SCHEMA: Final = "ir-hf-publication-receipt/v1"
IR_PUBLICATION_PLAN_SCHEMA: Final = "ir-hf-publication-plan/v1"
IR_REVOCATION_SCHEMA: Final = "IRReleaseRevocation@1"
IR_UPLOAD_ATTEMPT_SCHEMA: Final = "IRPublicationUploadAttempt@1"


class IRPublicationError(HuggingFacePublicationError):
    """Raised when IR publication planning or upload fails closed."""


@dataclass(frozen=True, slots=True)
class PublicationLease:
    """Exclusive ``hf-publication:<repo>`` fence required for remote writes."""

    fence: str
    lease_id: str
    holder: str
    repository_id: str
    generation: int = 1

    def __post_init__(self) -> None:
        fence = str(self.fence or "").strip()
        expected = f"hf-publication:{self.repository_id}"
        if fence != expected:
            raise IRPublicationError(
                f"publication lease fence must be {expected!r}, got {fence!r}"
            )
        if not str(self.lease_id or "").strip():
            raise IRPublicationError("lease_id is required")
        if not str(self.holder or "").strip():
            raise IRPublicationError("lease holder is required")
        if not isinstance(self.generation, int) or isinstance(self.generation, bool):
            raise IRPublicationError("lease generation must be a positive integer")
        if self.generation < 1:
            raise IRPublicationError("lease generation must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "fence": self.fence,
            "generation": self.generation,
            "holder": self.holder,
            "lease_id": self.lease_id,
            "repository_id": self.repository_id,
        }


def ir_publisher(
    policy: IRPublicationPolicy,
    *,
    api: Any | None = None,
    fetch_bytes: Callable[[str, str, str], bytes] | None = None,
) -> HuggingFaceReleasePublisher:
    """Build the existing append-only publisher with IR release defaults."""

    return HuggingFaceReleasePublisher(
        repository_id=policy.repository_id,
        repository_type=policy.repository_type,
        release_prefix_template=policy.release_prefix_template,
        pointer_path=policy.pointer_path,
        api=api,
        fetch_bytes=fetch_bytes,
    )


def _wrap_plan(plan: PublicationPlan, *, policy: IRPublicationPolicy) -> dict[str, Any]:
    payload = plan.to_dict()
    wrapped = {
        "append_only": True,
        "dry_run": True,
        "dry_run_diff_and_cost_receipt": payload,
        "lease_fence": policy.lease_fence,
        "plan_digest": plan.plan_digest,
        "release_id": plan.release_id,
        "release_prefix": plan.release_prefix,
        "remote_write_contacted": False,
        "repository_id": policy.repository_id,
        "schema": IR_PUBLICATION_PLAN_SCHEMA,
        "skipped_exact_matches": list(plan.skipped_exact_matches),
        "upload_bytes": int(plan.cost_receipt.get("upload_bytes", 0)),
        "upload_file_count": len(plan.operations),
    }
    _reject_secrets(wrapped, label="ir_publication_plan")
    return wrapped


def plan_ir_dry_run(
    package: IRReleasePackage,
    *,
    policy: IRPublicationPolicy | None = None,
    existing_remote_paths: Sequence[str] = (),
    existing_remote_digests: Mapping[str, str] | None = None,
    publisher: HuggingFaceReleasePublisher | None = None,
) -> tuple[PublicationPlan, dict[str, Any]]:
    """Deterministic dry-run: operation list, cost, no write-endpoint contact."""

    pub_policy = policy or IRPublicationPolicy(repository_id=package.repository_id)
    if pub_policy.repository_id != package.repository_id:
        raise IRPublicationError("policy repository_id does not match the package")
    validate_ir_release_package(package.output_dir)
    client = publisher or ir_publisher(pub_policy)
    try:
        plan = client.plan_dry_run(
            package.publication_manifest(),
            local_root=package.output_dir,
            existing_remote_paths=existing_remote_paths,
            existing_remote_digests=existing_remote_digests,
        )
    except HuggingFacePublicationError as exc:
        if "at least one add" not in str(exc):
            raise
        raise IRPublicationError("idempotent_already_published") from exc
    if plan.remote_write_contacted:
        raise IRPublicationError("dry-run must not contact a write endpoint")
    return plan, _wrap_plan(plan, policy=pub_policy)


def _require_authority(
    *,
    policy: IRPublicationPolicy,
    approval: PublicationApproval | None,
    lease: PublicationLease | None,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    if policy.require_human_approval and approval is None:
        raise IRPublicationError(
            "human PublicationApproval is required when dry_run is false; "
            "autonomous work stops after a dry run"
        )
    if policy.require_publication_lease and lease is None:
        raise IRPublicationError(
            f"exclusive publication lease {policy.lease_fence!r} is required"
        )
    if lease is not None and lease.repository_id != policy.repository_id:
        raise IRPublicationError("lease repository_id does not match publication policy")
    if lease is not None and lease.fence != policy.lease_fence:
        raise IRPublicationError("lease fence does not match publication policy")


def publish_ir_release(
    package: IRReleasePackage,
    *,
    policy: IRPublicationPolicy | None = None,
    dry_run: bool = True,
    approval: PublicationApproval | None = None,
    lease: PublicationLease | None = None,
    api: Any | None = None,
    existing_remote_paths: Sequence[str] = (),
    existing_remote_digests: Mapping[str, str] | None = None,
    receipt_path: str | Path | None = None,
    remote_objects: Mapping[str, Mapping[str, Any]] | None = None,
    remote_payloads: Mapping[str, bytes] | None = None,
    verified_cache_root: str | Path | None = None,
    fetch_bytes: Callable[[str, str, str], bytes] | None = None,
    commit_message: str = "pgir: append-only immutable IR release",
) -> dict[str, Any]:
    """Plan, and optionally upload, an IR release package.

    Default mode is dry-run only.  The remote revision is captured on upload.
    """

    pub_policy = policy or IRPublicationPolicy(repository_id=package.repository_id)
    _require_authority(policy=pub_policy, approval=approval, lease=lease, dry_run=dry_run)
    publisher = ir_publisher(pub_policy, api=api, fetch_bytes=fetch_bytes)
    try:
        plan, wrapped_plan = plan_ir_dry_run(
            package,
            policy=pub_policy,
            existing_remote_paths=existing_remote_paths,
            existing_remote_digests=existing_remote_digests,
            publisher=publisher,
        )
    except IRPublicationError as exc:
        if str(exc) != "idempotent_already_published":
            raise
        receipt = {
            "append_only": True,
            "approval_record": approval.to_dict() if approval else None,
            "commit_receipt": None,
            "derived_count": package.derived_count,
            "dry_run": False,
            "dry_run_diff_and_cost_receipt": {
                "skipped_exact_matches": sorted((existing_remote_digests or {}).keys()),
                "upload_bytes": 0,
                "upload_file_count": 0,
            },
            "evidence": {
                "cards_complete": True,
                "p1_configs_complete": True,
                "p4_evidence": True,
                "publication_lease": lease is not None,
                "remote_revision_captured": False,
                "source_derived_counts_distinct": True,
            },
            "lease": lease.to_dict() if lease else None,
            "package": {
                "evidence_cid": package.evidence_cid,
                "release_cid": package.release_cid,
                "release_id": package.release_id,
                "release_sha256": package.release_sha256,
            },
            "pinned_redownload_validation": None,
            "post_publication_verification": None,
            "remote_revision": "",
            "remote_write_performed": False,
            "repository_id": pub_policy.repository_id,
            "schema": IR_PUBLICATION_RECEIPT_SCHEMA,
            "source_count": package.source_count,
            "status": "idempotent_already_published",
            "tokens_persisted": False,
        }
        _reject_secrets(receipt, label="ir_publication_receipt")
        if receipt_path is not None:
            _write_receipt(receipt_path, receipt)
        return receipt

    if dry_run:
        receipt = _build_ir_receipt(
            package=package,
            policy=pub_policy,
            plan=plan,
            wrapped_plan=wrapped_plan,
            status="dry_run_only",
        )
        if receipt_path is not None:
            _write_receipt(receipt_path, receipt)
        return receipt

    if not plan.operations:
        # Exact path+digest matches: idempotent no-op commit is refused by the
        # underlying publisher.  Surface a captured "already published" receipt
        # without contacting create_commit.
        receipt = _build_ir_receipt(
            package=package,
            policy=pub_policy,
            plan=plan,
            wrapped_plan=wrapped_plan,
            approval=approval,
            lease=lease,
            status="idempotent_already_published",
        )
        if receipt_path is not None:
            _write_receipt(receipt_path, receipt)
        return receipt

    assert approval is not None  # gated by _require_authority
    try:
        commit = publisher.publish_append_only(
            plan,
            approval=approval,
            local_root=package.output_dir,
            commit_message=commit_message,
        )
    except HuggingFacePublicationError as exc:
        raise IRPublicationError(str(exc)) from exc

    post = publisher.verify_post_publication(
        commit_receipt=commit,
        plan=plan,
        remote_objects=remote_objects
        or {
            item.remote_path: {
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "commit_sha": commit.commit_sha,
            }
            for item in plan.operations
        },
    )
    pinned = None
    if remote_payloads is not None or fetch_bytes is not None or verified_cache_root is not None:
        cache = Path(verified_cache_root) if verified_cache_root is not None else Path(
            package.output_dir
        ).with_name(Path(package.output_dir).name + ".pinned-cache")
        if cache.exists() and any(cache.iterdir()):
            # Retry path: reuse an empty sibling rather than fail a second call.
            cache = cache.with_name(cache.name + f".{commit.commit_sha[:8]}")
        payloads = remote_payloads
        if payloads is None and fetch_bytes is None:
            root = Path(package.output_dir)
            payloads = {
                item.remote_path: root.joinpath(*item.relative_path.split("/")).read_bytes()
                for item in plan.operations
            }
        pinned = publisher.redownload_and_validate_pinned(
            commit_sha=commit.commit_sha,
            plan=plan,
            cache_root=cache,
            remote_payloads=payloads,
        )

    receipt = _build_ir_receipt(
        package=package,
        policy=pub_policy,
        plan=plan,
        wrapped_plan=wrapped_plan,
        commit=commit,
        approval=approval,
        lease=lease,
        post_publication=post.to_dict(),
        pinned_redownload=pinned.to_dict() if pinned is not None else None,
        status="published_pending_promotion",
    )
    if receipt_path is not None:
        _write_receipt(receipt_path, receipt)
    return receipt


def retry_partial_upload(
    package: IRReleasePackage,
    *,
    previous_attempt: Mapping[str, Any],
    approval: PublicationApproval,
    lease: PublicationLease,
    policy: IRPublicationPolicy | None = None,
    api: Any | None = None,
    remote_digests: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Resume a partial upload by skipping exact path+digest matches.

    Already-written objects with a matching digest are treated as complete.
    Objects with a mismatched digest are refused (append-only, no overwrite).
    """

    pub_policy = policy or IRPublicationPolicy(repository_id=package.repository_id)
    attempt = _require_mapping(previous_attempt, "previous upload attempt")
    if attempt.get("schema") not in {IR_UPLOAD_ATTEMPT_SCHEMA, None}:
        if attempt.get("schema") and attempt.get("schema") != IR_UPLOAD_ATTEMPT_SCHEMA:
            raise IRPublicationError("unsupported upload-attempt schema")
    existing = {
        str(path): str(digest)
        for path, digest in (remote_digests or attempt.get("uploaded_digests") or {}).items()
    }
    return publish_ir_release(
        package,
        policy=pub_policy,
        dry_run=False,
        approval=approval,
        lease=lease,
        api=api,
        existing_remote_digests=existing,
    )


def record_revocation_or_supersession(
    *,
    previous_release_id: str,
    previous_commit_sha: str,
    reason: str,
    output_path: str | Path,
    successor_release_id: str = "",
    successor_commit_sha: str = "",
) -> dict[str, Any]:
    """Append a revocation/supersession record.  Never deletes a published version."""

    if not previous_release_id or not previous_commit_sha:
        raise IRPublicationError("revocation requires the previous release id and commit SHA")
    if not reason or not str(reason).strip():
        raise IRPublicationError("revocation reason is required")
    record = {
        "kind": "revocation" if not successor_release_id else "supersession",
        "previous_commit_sha": previous_commit_sha.casefold(),
        "previous_release_id": previous_release_id,
        "previous_release_retained": True,
        "reason": str(reason).strip(),
        "schema": IR_REVOCATION_SCHEMA,
        "successor_commit_sha": successor_commit_sha.casefold() if successor_commit_sha else "",
        "successor_release_id": successor_release_id,
    }
    _reject_secrets(record, label="revocation_record")
    body = _canonical_json_bytes(record)
    record["record_sha256"] = sha256(body).hexdigest()
    _write_receipt(output_path, record)
    return record


def build_upload_attempt(
    *,
    plan: PublicationPlan,
    uploaded_paths: Sequence[str] = (),
    remaining_paths: Sequence[str] | None = None,
    attempt_index: int = 1,
) -> dict[str, Any]:
    """Durable retry state for a partial append-only upload."""

    uploaded = tuple(str(path) for path in uploaded_paths)
    if remaining_paths is None:
        remaining = tuple(
            item.remote_path for item in plan.operations if item.remote_path not in uploaded
        )
    else:
        remaining = tuple(str(path) for path in remaining_paths)
    attempt = {
        "attempt_index": int(attempt_index),
        "plan_digest": plan.plan_digest,
        "release_id": plan.release_id,
        "remaining_paths": list(remaining),
        "schema": IR_UPLOAD_ATTEMPT_SCHEMA,
        "uploaded_digests": {
            item.remote_path: item.sha256
            for item in plan.operations
            if item.remote_path in uploaded
        },
        "uploaded_paths": list(uploaded),
    }
    _reject_secrets(attempt, label="upload_attempt")
    return attempt


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IRPublicationError(f"{label} must be an object")
    return value


def _build_ir_receipt(
    *,
    package: IRReleasePackage,
    policy: IRPublicationPolicy,
    plan: PublicationPlan,
    wrapped_plan: Mapping[str, Any],
    status: str,
    commit: PublicationCommitReceipt | None = None,
    approval: PublicationApproval | None = None,
    lease: PublicationLease | None = None,
    post_publication: Mapping[str, Any] | None = None,
    pinned_redownload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    remote_revision = commit.commit_sha if commit is not None else ""
    receipt = {
        "append_only": True,
        "approval_record": approval.to_dict() if approval else None,
        "commit_receipt": commit.to_dict() if commit else None,
        "derived_count": package.derived_count,
        "dry_run": status == "dry_run_only",
        "dry_run_diff_and_cost_receipt": dict(wrapped_plan),
        "evidence": {
            "cards_complete": True,
            "p1_configs_complete": True,
            "p4_evidence": True,
            "publication_lease": lease is not None,
            "remote_revision_captured": bool(remote_revision),
            "source_derived_counts_distinct": True,
        },
        "lease": lease.to_dict() if lease else None,
        "package": {
            "evidence_cid": package.evidence_cid,
            "release_cid": package.release_cid,
            "release_id": package.release_id,
            "release_sha256": package.release_sha256,
        },
        "pinned_redownload_validation": dict(pinned_redownload) if pinned_redownload else None,
        "post_publication_verification": dict(post_publication) if post_publication else None,
        "remote_revision": remote_revision,
        "remote_write_performed": commit is not None,
        "repository_id": policy.repository_id,
        "schema": IR_PUBLICATION_RECEIPT_SCHEMA,
        "source_count": package.source_count,
        "status": status,
        "tokens_persisted": False,
    }
    _reject_secrets(receipt, label="ir_publication_receipt")
    return receipt


def package_and_publish(
    *,
    output_dir: str | Path,
    inputs: Mapping[str, Any],
    policy: IRPublicationPolicy | Mapping[str, Any] | None = None,
    dry_run: bool = True,
    approval: PublicationApproval | None = None,
    lease: PublicationLease | None = None,
    api: Any | None = None,
    receipt_path: str | Path | None = None,
) -> dict[str, Any]:
    """One-shot local package plus dry-run (or approved append-only upload)."""

    pub_policy = (
        IRPublicationPolicy()
        if policy is None
        else policy
        if isinstance(policy, IRPublicationPolicy)
        else IRPublicationPolicy.from_dict(policy)
    )
    package = package_ir_release(output_dir=output_dir, inputs=inputs, policy=pub_policy)
    return publish_ir_release(
        package,
        policy=pub_policy,
        dry_run=dry_run,
        approval=approval,
        lease=lease,
        api=api,
        receipt_path=receipt_path,
    )


__all__ = [
    "DEFAULT_IR_DATASET_REPO_ID",
    "DEFAULT_POINTER_PATH",
    "DEFAULT_RELEASE_PREFIX_TEMPLATE",
    "IR_PUBLICATION_PLAN_SCHEMA",
    "IR_PUBLICATION_RECEIPT_SCHEMA",
    "IR_REVOCATION_SCHEMA",
    "IR_UPLOAD_ATTEMPT_SCHEMA",
    "IRPublicationError",
    "PublicationLease",
    "build_upload_attempt",
    "estimate_publication_cost",
    "ir_publisher",
    "package_and_publish",
    "plan_ir_dry_run",
    "publish_ir_release",
    "record_revocation_or_supersession",
    "retry_partial_upload",
]
