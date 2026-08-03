#!/usr/bin/env python3
"""Verify JusticeDAO patent/legal publication through the append-only publisher.

Default mode is **dry-run**: build a publication plan and receipt without any
Hub contact, token use, pointer move, or upload.  Repository names remain
configurable.

``--fake-live`` exercises the complete offline gate sequence against an
in-memory fake Hub service:

  dry-run → exact approval → add-only publish → audited-parent race check →
  post-publication verification → pinned re-download → canary → pointer
  promotion → rollback

Pointer promotion is refused until pinned redownload validation succeeds.
This script never imports a live ``HfApi`` client, never reads ``HF_TOKEN``,
and never calls ``upload_file``.
"""

from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.huggingface.publication_profile import (  # noqa: E402
    PATENT_LEGAL_DEFAULT_REPOSITORY_ID,
    PATENT_LEGAL_GOAL_ID,
    PATENT_LEGAL_PLAN_SCHEMA,
    PATENT_LEGAL_RECEIPT_SCHEMA,
    patent_legal_publication_profile,
)
from ipfs_datasets_py.huggingface.publisher import (  # noqa: E402
    HuggingFacePublicationError,
    HuggingFaceReleasePublisher,
    PublicationApproval,
    PublicationCommitReceipt,
    RuntimeReleasePointer,
    publish_huggingface_release,
)

AUDITED_PARENT = "0" * 40
DEFAULT_RELEASE_ID = "patent-public-fixture-v1"
DEFAULT_FIXTURE_MANIFEST = (
    REPOSITORY_ROOT / "tests/fixtures/patent/release/manifest.json"
)

# Deterministic offline payloads bound by the committed fixture digests.
_PAYLOAD_BODIES: dict[str, bytes] = {
    "summary_v1": (
        b'{"schema":"patent-fixture","ok":true,'
        b'"program":"patent-legal-intelligence"}'
    ),
    "parquet_usc_v1": b"PAR1" + b"\x00" * 48 + b"PAR1",
    "parquet_claims_v1": b"PAR1" + b"\x01" * 40 + b"PAR1",
    "policy_v1": (
        b'{"admitted":true,"policy_version":"patent-legal-release-policy/v1"}\n'
    ),
}

_GATE_ORDER: tuple[str, ...] = (
    "dry_run",
    "exact_approval",
    "add_only_publish",
    "audited_parent_race_check",
    "post_publication_verification",
    "pinned_redownload",
    "pointer_blocked_before_pin",
    "canary_promotion",
    "rollback",
)


class PatentHFReleaseVerifyError(RuntimeError):
    """Raised when verification cannot complete fail-closed."""


class FakeHubApi:
    """In-memory Hub stand-in: records calls, never touches the network."""

    def __init__(
        self,
        commit_sha: str = "a" * 40,
        *,
        parent_sha: str = AUDITED_PARENT,
    ) -> None:
        self.commit_sha = commit_sha
        self.head_sha = parent_sha
        self.calls: list[str] = []
        self.create_commit_calls: list[dict[str, Any]] = []
        self.remote_files: dict[str, Path] = {}
        self.read_calls: list[tuple[str, str]] = []

    def repo_info(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append("repo_info")
        self.read_calls.append(("repo_info", str(kwargs.get("revision") or "")))
        return {"sha": self.head_sha}

    def get_paths_info(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append("get_paths_info")
        revision = str(kwargs.get("revision") or "")
        self.read_calls.append(("get_paths_info", revision))
        result: list[dict[str, Any]] = []
        for requested in kwargs.get("paths") or []:
            path = str(requested)
            if path in self.remote_files:
                source = self.remote_files[path]
                body = source.read_bytes()
                result.append(
                    {
                        "path": path,
                        "size": len(body),
                        "lfs": {"sha256": sha256(body).hexdigest(), "size": len(body)},
                    }
                )
            elif any(
                existing.startswith(f"{path}/") for existing in self.remote_files
            ):
                result.append({"path": path, "tree_id": "tree"})
        return result

    def create_commit(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append("create_commit")
        self.create_commit_calls.append(dict(kwargs))
        operations = kwargs.get("operations") or []
        if not operations:
            raise AssertionError("create_commit must receive operations")
        for op in operations:
            path = getattr(op, "path_in_repo", None)
            if path is None and isinstance(op, Mapping):
                path = op.get("path_in_repo")
            source = getattr(op, "path_or_fileobj", None)
            if source is None and isinstance(op, Mapping):
                source = op.get("path_or_fileobj")
            if path and source is not None:
                self.remote_files[str(path)] = Path(str(source))
        self.head_sha = self.commit_sha
        return {"commit_sha": self.commit_sha}

    def upload_file(self, **kwargs: Any) -> None:
        self.calls.append("upload_file")
        raise AssertionError("upload_file must never be used for patent publication")

    def delete_file(self, **kwargs: Any) -> None:
        self.calls.append("delete_file")
        raise AssertionError("delete_file is prohibited under append-only publication")

    def hf_hub_download(self, **kwargs: Any) -> str:
        self.calls.append("hf_hub_download")
        remote_path = str(kwargs["filename"])
        revision = str(kwargs["revision"])
        self.read_calls.append(("hf_hub_download", revision))
        if revision != self.commit_sha:
            raise PatentHFReleaseVerifyError(
                f"fake download pinned to wrong revision: {revision}"
            )
        local_dir = Path(kwargs["local_dir"])
        target = local_dir / remote_path
        target.parent.mkdir(parents=True, exist_ok=True)
        source = self.remote_files[remote_path]
        target.write_bytes(source.read_bytes())
        return str(target)


def fixture_manifest_path() -> Path:
    return DEFAULT_FIXTURE_MANIFEST


def payload_for_recipe(recipe_id: str) -> bytes:
    try:
        return _PAYLOAD_BODIES[recipe_id]
    except KeyError as exc:
        raise PatentHFReleaseVerifyError(
            f"unknown fixture payload recipe: {recipe_id!r}"
        ) from exc


def load_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().resolve()
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise PatentHFReleaseVerifyError(
            f"release manifest must be a regular file: {manifest_path}"
        )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PatentHFReleaseVerifyError(
            f"cannot read release manifest: {manifest_path}: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise PatentHFReleaseVerifyError("release manifest must be a JSON object")
    return normalize_publication_manifest(dict(payload))


def normalize_publication_manifest(
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize builder or publisher manifests for the append-only planner.

    Builder manifests use ``artifacts`` and ``release_root_cid``; the publisher
    expects ``files``/``descriptors`` plus a safe ``release_id``.
    """

    if not isinstance(manifest, Mapping):
        raise PatentHFReleaseVerifyError("manifest must be a mapping")
    body = dict(manifest)

    if not body.get("files") and not body.get("descriptors"):
        artifacts = body.get("artifacts")
        if isinstance(artifacts, list) and artifacts:
            body["descriptors"] = [
                {
                    "path": item.get("relative_path") or item.get("path"),
                    "byte_length": item.get("size_bytes", item.get("byte_length")),
                    "sha256": item.get("sha256"),
                    "content_cid": item.get("content_cid"),
                }
                for item in artifacts
                if isinstance(item, Mapping)
            ]

    release_id = str(body.get("release_id") or "").strip()
    if not release_id:
        root_cid = str(body.get("release_root_cid") or "").strip()
        if root_cid:
            # Content-addressed builder ids become safe release prefixes.
            release_id = f"cid-{root_cid}"
        else:
            release_sha = str(body.get("release_sha256") or "").strip().casefold()
            if len(release_sha) == 64 and all(
                ch in "0123456789abcdef" for ch in release_sha
            ):
                release_id = f"sha256-{release_sha}"
        if release_id:
            body["release_id"] = release_id

    if "uses_hf_api_upload_file" not in body:
        body["uses_hf_api_upload_file"] = False
    if "upload_path" not in body:
        body["upload_path"] = None
    if "remote_writes" not in body:
        body["remote_writes"] = False
    return body


def materialize_release_tree(
    root: str | Path,
    manifest: Mapping[str, Any],
) -> Path:
    """Write fixture or recipe-bound local files for publication planning."""

    target = Path(root).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    recipe_map = manifest.get("payload_recipe") or {}
    if not isinstance(recipe_map, Mapping):
        raise PatentHFReleaseVerifyError("payload_recipe must be a mapping when present")

    files = manifest.get("files") or manifest.get("descriptors") or []
    if not isinstance(files, list) or not files:
        raise PatentHFReleaseVerifyError("manifest has no files/descriptors to materialize")

    for entry in files:
        if not isinstance(entry, Mapping):
            raise PatentHFReleaseVerifyError("manifest file entry must be an object")
        relative = str(
            entry.get("path")
            or entry.get("relative_path")
            or entry.get("remote_path")
            or ""
        ).strip()
        if not relative or relative.startswith("/") or ".." in relative.split("/"):
            raise PatentHFReleaseVerifyError(f"unsafe relative path: {relative!r}")
        expected_sha = str(entry.get("sha256") or "").strip().casefold()
        expected_size = int(entry.get("byte_length", entry.get("size_bytes", -1)))
        recipe_id = str(recipe_map.get(relative) or entry.get("fixture_payload") or "")
        if recipe_id:
            body = payload_for_recipe(recipe_id)
        else:
            # Fall back to deterministic reconstruction for known fixture digests.
            body = _body_for_known_digest(expected_sha)
            if body is None:
                raise PatentHFReleaseVerifyError(
                    f"cannot materialize {relative}: provide payload_recipe or "
                    "stage local_root with matching bytes"
                )
        if expected_size >= 0 and len(body) != expected_size:
            raise PatentHFReleaseVerifyError(
                f"payload size mismatch for {relative}: "
                f"{len(body)} != {expected_size}"
            )
        digest = sha256(body).hexdigest()
        if expected_sha and digest != expected_sha:
            raise PatentHFReleaseVerifyError(
                f"payload digest mismatch for {relative}: {digest} != {expected_sha}"
            )
        out = target.joinpath(*Path(relative).parts)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(body)
    return target


def _body_for_known_digest(digest: str) -> bytes | None:
    for body in _PAYLOAD_BODIES.values():
        if sha256(body).hexdigest() == digest:
            return body
    return None


def build_approval(
    plan: Any,
    *,
    repository_id: str,
    approver: str = "patent-legal-operator",
    approval_id: str = "approval-patent-legal-1",
    max_cost_usd: float = 25.0,
) -> PublicationApproval:
    return PublicationApproval(
        approver=approver,
        plan_digest=plan.plan_digest,
        max_cost_usd=max_cost_usd,
        max_upload_bytes=int(plan.cost_receipt["upload_bytes"]),
        credentials_scope=f"dataset:write:{repository_id}",
        approval_id=approval_id,
    )


def plan_dry_run(
    *,
    manifest: Mapping[str, Any],
    local_root: str | Path,
    repository_id: str = PATENT_LEGAL_DEFAULT_REPOSITORY_ID,
    audited_parent_commit: str = AUDITED_PARENT,
    api: Any | None = None,
) -> tuple[HuggingFaceReleasePublisher, Any, dict[str, Any]]:
    """Default verification path: offline dry-run plan + receipt."""

    profile = patent_legal_publication_profile(repository_id=repository_id)
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=local_root,
        audited_parent_commit=audited_parent_commit,
    )
    receipt = publisher.build_publication_receipt(plan=plan, status="dry_run_only")
    return publisher, plan, receipt


def run_fake_live_verification(
    *,
    manifest: Mapping[str, Any],
    local_root: str | Path,
    repository_id: str = PATENT_LEGAL_DEFAULT_REPOSITORY_ID,
    audited_parent_commit: str = AUDITED_PARENT,
    canary_percent: int = 10,
    commit_sha: str = "b" * 40,
    verified_cache_root: str | Path | None = None,
) -> dict[str, Any]:
    """Exercise every publication gate against a fake Hub (no network/token)."""

    root = Path(local_root).expanduser().resolve()
    if not root.is_dir():
        raise PatentHFReleaseVerifyError(f"local_root is not a directory: {root}")

    gates: dict[str, Any] = {}
    api = FakeHubApi(commit_sha=commit_sha, parent_sha=audited_parent_commit)
    profile = patent_legal_publication_profile(repository_id=repository_id)
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)

    # Gate 1: dry-run (no API contact).
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=audited_parent_commit,
    )
    dry_receipt = publisher.build_publication_receipt(
        plan=plan, status="dry_run_only"
    )
    if dry_receipt["status"] != "dry_run_only":
        raise PatentHFReleaseVerifyError("dry-run receipt status mismatch")
    if dry_receipt["remote_write_performed"] is not False:
        raise PatentHFReleaseVerifyError("dry-run must not record remote writes")
    if api.calls:
        raise PatentHFReleaseVerifyError(
            f"dry-run contacted the API: {api.calls}"
        )
    if plan.schema_version != PATENT_LEGAL_PLAN_SCHEMA:
        raise PatentHFReleaseVerifyError(
            f"unexpected plan schema: {plan.schema_version}"
        )
    if plan.repository_id != repository_id:
        raise PatentHFReleaseVerifyError(
            f"repository_id not configurable: {plan.repository_id}"
        )
    gates["dry_run"] = {
        "ok": True,
        "plan_digest": plan.plan_digest,
        "upload_bytes": plan.cost_receipt["upload_bytes"],
        "operation_count": len(plan.operations),
        "remote_write_contacted": False,
        "api_calls": list(api.calls),
    }

    # Gate 2: exact approval of the plan digest + repository scope.
    approval = build_approval(plan, repository_id=repository_id)
    if approval.plan_digest != plan.plan_digest:
        raise PatentHFReleaseVerifyError("approval plan_digest mismatch")
    expected_scope = f"dataset:write:{repository_id}"
    if approval.credentials_scope != expected_scope:
        raise PatentHFReleaseVerifyError("approval credentials_scope mismatch")
    gates["exact_approval"] = {
        "ok": True,
        "approval_id": approval.approval_id,
        "plan_digest": approval.plan_digest,
        "credentials_scope": approval.credentials_scope,
    }

    # Gate 3: audited-parent race check (fail closed before upload).
    raced = FakeHubApi(commit_sha=commit_sha, parent_sha="9" * 40)
    raced_publisher = HuggingFaceReleasePublisher(profile=profile, api=raced)
    race_blocked = False
    try:
        raced_publisher.publish_append_only(
            plan, approval=approval, local_root=root
        )
    except HuggingFacePublicationError as exc:
        if "advanced after audit" in str(exc):
            race_blocked = True
        else:
            raise
    if not race_blocked or raced.create_commit_calls:
        raise PatentHFReleaseVerifyError(
            "audited-parent race check did not block create_commit"
        )
    gates["audited_parent_race_check"] = {
        "ok": True,
        "blocked_mismatched_parent": True,
        "create_commit_calls": len(raced.create_commit_calls),
    }

    # Gate 4: add-only publish (create_commit only; never upload_file).
    commit = publisher.publish_append_only(
        plan, approval=approval, local_root=root
    )
    if not isinstance(commit, PublicationCommitReceipt):
        raise PatentHFReleaseVerifyError("publish did not return a commit receipt")
    if commit.commit_sha != commit_sha:
        raise PatentHFReleaseVerifyError("unexpected commit sha")
    if commit.parent_commit != audited_parent_commit:
        raise PatentHFReleaseVerifyError("parent_commit not bound to audited parent")
    if "create_commit" not in api.calls:
        raise PatentHFReleaseVerifyError("add-only publish did not call create_commit")
    if "upload_file" in api.calls:
        raise PatentHFReleaseVerifyError("upload_file is prohibited")
    if len(api.create_commit_calls) != 1:
        raise PatentHFReleaseVerifyError("expected exactly one create_commit")
    gates["add_only_publish"] = {
        "ok": True,
        "commit_sha": commit.commit_sha,
        "parent_commit": commit.parent_commit,
        "uploaded_paths": list(commit.uploaded_paths),
        "create_commit_calls": len(api.create_commit_calls),
        "used_upload_file": False,
    }

    # Gate 5: post-publication verification against the returned commit.
    remote_objects = {
        item.remote_path: {
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
            "commit_sha": commit.commit_sha,
        }
        for item in plan.operations
    }
    post = publisher.verify_post_publication(
        commit_receipt=commit,
        plan=plan,
        remote_objects=remote_objects,
    )
    if not post.ok:
        raise PatentHFReleaseVerifyError("post-publication verification failed")
    gates["post_publication_verification"] = {
        "ok": True,
        "verified_file_count": post.verified_file_count,
        "commit_sha": post.commit_sha,
    }

    # Gate 6: pointer promotion must wait for pinned redownload.
    previous = RuntimeReleasePointer(
        repository_id=commit.repository_id,
        release_id="previous-patent-public-v0",
        commit_sha="c" * 40,
        release_prefix=publisher.release_prefix_for("previous-patent-public-v0"),
    )
    pointer_blocked = False
    try:
        publisher.canary_promote_pointer(
            commit_receipt=commit,
            previous=previous,
            canary_percent=canary_percent,
            approval=approval,
        )
    except HuggingFacePublicationError as exc:
        if "pinned redownload" in str(exc):
            pointer_blocked = True
        else:
            raise
    if not pointer_blocked:
        raise PatentHFReleaseVerifyError(
            "pointer promotion must wait for pinned redownload validation"
        )
    gates["pointer_blocked_before_pin"] = {
        "ok": True,
        "blocked_without_pinned_verification": True,
    }

    # Gate 7: pinned redownload validation into an empty cache.
    payloads = {
        item.remote_path: (root / item.relative_path).read_bytes()
        for item in plan.operations
    }
    if verified_cache_root is None:
        cache = root.parent / "verified-empty-cache"
    else:
        cache = Path(verified_cache_root).expanduser().resolve()
    if cache.exists():
        # Require empty; do not wipe operator data.
        if any(cache.iterdir()):
            raise PatentHFReleaseVerifyError(
                f"verified cache must be empty: {cache}"
            )
    else:
        cache.mkdir(parents=True, exist_ok=True)
    pinned = publisher.redownload_and_validate_pinned(
        commit_sha=commit.commit_sha,
        plan=plan,
        cache_root=cache,
        remote_payloads=payloads,
    )
    if not pinned.ok:
        raise PatentHFReleaseVerifyError("pinned redownload validation failed")
    gates["pinned_redownload"] = {
        "ok": True,
        "commit_sha": pinned.commit_sha,
        "revalidated_file_count": pinned.revalidated_file_count,
        "empty_cache_before_fetch": pinned.empty_cache_before_fetch,
    }

    # Gate 8: canary pointer promotion after pinned verification.
    pointer = publisher.canary_promote_pointer(
        commit_receipt=commit,
        previous=previous,
        canary_percent=canary_percent,
        approval=approval,
        pinned_redownload=pinned,
    )
    if pointer.commit_sha != commit.commit_sha:
        raise PatentHFReleaseVerifyError("canary pointer commit mismatch")
    if pointer.canary_percent != canary_percent:
        raise PatentHFReleaseVerifyError("canary_percent not applied")
    if pointer.pointer_path != profile.pointer_path:
        raise PatentHFReleaseVerifyError("unexpected pointer path")
    gates["canary_promotion"] = {
        "ok": True,
        "canary_percent": pointer.canary_percent,
        "commit_sha": pointer.commit_sha,
        "pointer_path": pointer.pointer_path,
        "previous_commit_sha": pointer.previous_commit_sha,
    }

    # Gate 9: rollback retains the failed/candidate release.
    rolled = publisher.rollback_pointer(
        current=pointer, failed_release_retained=True
    )
    if rolled.commit_sha != previous.commit_sha:
        raise PatentHFReleaseVerifyError("rollback did not restore previous commit")
    if rolled.previous_commit_sha != commit.commit_sha:
        raise PatentHFReleaseVerifyError(
            "rollback must retain the failed candidate as previous"
        )
    gates["rollback"] = {
        "ok": True,
        "restored_commit_sha": rolled.commit_sha,
        "retained_failed_commit_sha": rolled.previous_commit_sha,
        "failed_release_retained": True,
    }

    missing = [name for name in _GATE_ORDER if name not in gates or not gates[name].get("ok")]
    if missing:
        raise PatentHFReleaseVerifyError(f"incomplete gate coverage: {missing}")

    receipt = publisher.build_publication_receipt(
        plan=plan,
        commit_receipt=commit,
        post_publication=post,
        pinned_redownload=pinned,
        pointer=pointer,
        approval=approval,
        status="canary_active",
    )
    if receipt["schema_version"] != PATENT_LEGAL_RECEIPT_SCHEMA:
        raise PatentHFReleaseVerifyError(
            f"unexpected receipt schema: {receipt['schema_version']}"
        )

    return {
        "append_only": True,
        "audited_parent_commit": audited_parent_commit,
        "commit_sha": commit.commit_sha,
        "evidence": receipt["evidence"],
        "fake_live": True,
        "gates": gates,
        "gate_order": list(_GATE_ORDER),
        "goal_id": PATENT_LEGAL_GOAL_ID,
        "live_network": False,
        "plan_digest": plan.plan_digest,
        "profile_id": "patent-legal",
        "receipt": receipt,
        "release_id": plan.release_id,
        "release_prefix": plan.release_prefix,
        "remote_write_performed": True,
        "repository_id": repository_id,
        "status": "fake_live_complete",
        "tokens_used": False,
        "uses_hf_api_upload_file": False,
    }


def verify_patent_hf_release(
    *,
    manifest: Mapping[str, Any] | str | Path | None = None,
    local_root: str | Path | None = None,
    repository_id: str = PATENT_LEGAL_DEFAULT_REPOSITORY_ID,
    dry_run: bool = True,
    fake_live: bool = False,
    audited_parent_commit: str = AUDITED_PARENT,
    canary_percent: int = 10,
    receipt_path: str | Path | None = None,
    materialize_if_needed: bool = True,
    verified_cache_root: str | Path | None = None,
    api: Any | None = None,
) -> dict[str, Any]:
    """Library entry point used by the CLI and supervisor integration tests."""

    if fake_live and not dry_run:
        # fake_live implies an offline live simulation; keep dry_run=False for
        # the publish segment but never contact a real network.
        pass
    if fake_live and dry_run is False:
        # Explicit live-without-fake is not supported by this verifier.
        pass

    if manifest is None:
        manifest_obj = load_manifest(fixture_manifest_path())
        manifest_source = str(fixture_manifest_path())
    elif isinstance(manifest, (str, Path)):
        manifest_obj = load_manifest(manifest)
        manifest_source = str(Path(manifest).expanduser().resolve())
    else:
        manifest_obj = normalize_publication_manifest(manifest)
        manifest_source = "<in-memory>"

    root: Path
    if local_root is None:
        # Ephemeral materialization beside the fixture when recipe-bound.
        root = Path.cwd() / ".patent-hf-release-verify-staging"
        if materialize_if_needed:
            materialize_release_tree(root, manifest_obj)
    else:
        root = Path(local_root).expanduser().resolve()
        if materialize_if_needed:
            files_present = all(
                root.joinpath(
                    *Path(
                        str(
                            entry.get("path")
                            or entry.get("relative_path")
                            or ""
                        )
                    ).parts
                ).is_file()
                for entry in (
                    manifest_obj.get("files")
                    or manifest_obj.get("descriptors")
                    or []
                )
                if isinstance(entry, Mapping)
            )
            if not files_present:
                materialize_release_tree(root, manifest_obj)

    if fake_live:
        result = run_fake_live_verification(
            manifest=manifest_obj,
            local_root=root,
            repository_id=repository_id,
            audited_parent_commit=audited_parent_commit,
            canary_percent=canary_percent,
            verified_cache_root=verified_cache_root,
        )
        result["manifest_source"] = manifest_source
        result["local_root"] = root.as_posix()
        if receipt_path is not None:
            _write_json(receipt_path, result)
        return result

    # Default: dry-run only.  Never install a real API client.
    if api is not None:
        # Tests may inject a tracking fake to prove zero contact.
        pass
    publisher, plan, receipt = plan_dry_run(
        manifest=manifest_obj,
        local_root=root,
        repository_id=repository_id,
        audited_parent_commit=audited_parent_commit,
        api=api,
    )
    result = {
        "append_only": True,
        "audited_parent_commit": audited_parent_commit,
        "dry_run": True,
        "evidence": receipt["evidence"],
        "fake_live": False,
        "goal_id": PATENT_LEGAL_GOAL_ID,
        "live_network": False,
        "local_root": root.as_posix(),
        "manifest_source": manifest_source,
        "plan": plan.to_dict(),
        "plan_digest": plan.plan_digest,
        "profile_id": "patent-legal",
        "receipt": receipt,
        "release_id": plan.release_id,
        "release_prefix": plan.release_prefix,
        "remote_write_performed": False,
        "repository_id": repository_id,
        "status": "dry_run_only",
        "tokens_used": False,
        "uses_hf_api_upload_file": False,
    }
    if receipt_path is not None:
        _write_json(receipt_path, result)
    # Silence unused when dry-run only.
    del publisher
    return result


def _write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify JusticeDAO patent HF publication through the append-only "
            "publisher (default: dry-run, no network, no token, no upload)."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help=(
            "Path to a release manifest (builder artifacts or publisher "
            f"files). Default: {DEFAULT_FIXTURE_MANIFEST}"
        ),
    )
    parser.add_argument(
        "--local-root",
        type=Path,
        default=None,
        help="Local release tree root (materialized from fixture when omitted)",
    )
    parser.add_argument(
        "--repository-id",
        default=PATENT_LEGAL_DEFAULT_REPOSITORY_ID,
        help=(
            "Configurable target dataset repository "
            f"(default: {PATENT_LEGAL_DEFAULT_REPOSITORY_ID})"
        ),
    )
    parser.add_argument(
        "--audited-parent-commit",
        default=AUDITED_PARENT,
        help="Audited parent commit SHA bound into the plan digest",
    )
    parser.add_argument(
        "--canary-percent",
        type=int,
        default=10,
        help="Canary percentage for fake-live pointer promotion (1..100)",
    )
    parser.add_argument(
        "--receipt-path",
        type=Path,
        default=None,
        help="Optional path to write the verification receipt JSON",
    )
    parser.add_argument(
        "--fake-live",
        action="store_true",
        help=(
            "Exercise every publication gate against an in-memory fake Hub. "
            "Still performs no real network I/O and requires no token."
        ),
    )
    parser.add_argument(
        "--print-plan",
        action="store_true",
        help="Print the dry-run plan JSON (dry-run mode only)",
    )
    parser.add_argument(
        "--no-materialize",
        action="store_true",
        help="Do not materialize fixture payloads; require an existing local-root",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    # Hard refuse any accidental live/token flags if future wrappers add them.
    for forbidden in ("upload", "push", "token", "hf_token", "live"):
        if getattr(args, forbidden, None):
            parser.error(f"{forbidden} is not supported by this verifier")

    try:
        result = verify_patent_hf_release(
            manifest=args.manifest,
            local_root=args.local_root,
            repository_id=args.repository_id,
            dry_run=not args.fake_live,
            fake_live=bool(args.fake_live),
            audited_parent_commit=args.audited_parent_commit,
            canary_percent=args.canary_percent,
            receipt_path=args.receipt_path,
            materialize_if_needed=not args.no_materialize,
        )
    except (PatentHFReleaseVerifyError, HuggingFacePublicationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - unexpected operator failure
        print(f"ERROR: verification failed: {exc}", file=sys.stderr)
        return 1

    summary: MutableMapping[str, Any] = {
        "status": result["status"],
        "repository_id": result["repository_id"],
        "release_id": result.get("release_id"),
        "plan_digest": result.get("plan_digest"),
        "dry_run": result.get("dry_run", result["status"] == "dry_run_only"),
        "fake_live": result.get("fake_live", False),
        "live_network": result.get("live_network", False),
        "tokens_used": result.get("tokens_used", False),
        "remote_write_performed": result.get("remote_write_performed", False),
        "uses_hf_api_upload_file": False,
        "goal_id": result.get("goal_id"),
    }
    if result.get("fake_live"):
        summary["gates"] = {
            name: {"ok": bool(gate.get("ok"))}
            for name, gate in (result.get("gates") or {}).items()
        }
        summary["commit_sha"] = result.get("commit_sha")
    print(json.dumps(summary, sort_keys=True, indent=2))
    if args.print_plan and not args.fake_live:
        print(json.dumps(result.get("plan") or {}, sort_keys=True, indent=2))
    if result.get("status") == "dry_run_only":
        print(
            "dry-run complete: no remote write, no pointer move, no token used",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
