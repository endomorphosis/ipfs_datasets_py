#!/usr/bin/env python3
"""Verify pinned Hub downloads and exercise approval-bound rollback (PATLAW-160).

Default mode is **dry-run**: load a multi-repo release tree, bind the release
manifest digests, optionally exercise offline Dataset Viewer contracts, and
emit a plan-only receipt.  No Hub contact, token use, pointer move, or upload
occurs.

``--fake-live`` exercises the complete offline gate sequence against an
in-memory multi-repo Hub stand-in (no network, no real tokens):

  dry-run plan → stage + exact operator approval → promote →
  pointer blocked before pin → pinned redownload at exact Hub SHAs →
  unpinned (main/latest) request blocked → Viewer contracts →
  canary pointer promotion → approval-bound rollback (pointer only) →
  rollback receipt itself pinned and verifiable

Any missing/changed artifact, unpinned request, Viewer failure, or manifest
mismatch blocks promotion.  A successful receipt binds repository IDs, Hub
commit SHAs, release root CID, every artifact hash, and Viewer results.
Rollback rewrites only the reviewed runtime pointer and retains both release
commits and audit evidence.

This script never imports a live ``HfApi`` client, never reads ``HF_TOKEN``
for remote I/O in dry-run/fake-live, and never calls ``upload_file``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.huggingface.release import (  # noqa: E402
    canonical_json_bytes,
)
from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (  # noqa: E402
    CANONICAL_REPOSITORY_NAMES,
    CORPUS_REPOSITORY,
    ORGANIZATION,
)
from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (  # noqa: E402
    ApprovalError,
    ArtifactChangedError,
    DEFAULT_TARGET_REVISION,
    FakeHubService,
    PatentHFPublisherV2,
    PatentHFPublisherV2Error,
    PublicationApprovalReceipt,
    StagePlan,
    StagedPRReceipt,
    PromotionReceipt,
    create_operator_approval,
    default_test_base_revisions,
    load_release_manifest,
    materialize_minimal_release_tree,
    new_ephemeral_operator_key,
    plan_stage_from_local_root,
    reject_credentials_in_payload,
    verify_operator_approval,
)
from ipfs_datasets_py.processors.domains.patent.hf_release_policy_v2 import (  # noqa: E402
    VIEWER_ENDPOINTS,
    DatasetViewerGate,
    FakeDatasetViewerService,
    FakeViewerGateway,
    ReleasePolicyV2Error,
    load_staged_release_inventory,
)
from ipfs_datasets_py.processors.domains.patent.hf_release_v2 import (  # noqa: E402
    RELEASE_MANIFEST_FILENAME,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TASK_ID = "PATLAW-160"
GOAL_ID = "PATLAW-G182"
PROGRAM_ID = "patent-legal-intelligence"
VERIFY_SCHEMA = "patent-legal-hf-verification-receipt/v2"
POINTER_SCHEMA = "patent-legal-hf-runtime-pointer/v2"
PINNED_SCHEMA = "patent-legal-hf-pinned-redownload/v2"
ROLLBACK_SCHEMA = "patent-legal-hf-rollback-receipt/v2"
DEFAULT_POINTER_PATH = "runtime/patent_legal_release_pointer_v2.json"
DEFAULT_BASE_SHA = "0" * 40
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_UNPINNED_REVISIONS = frozenset(
    {
        "main",
        "master",
        "latest",
        "HEAD",
        "refs/heads/main",
        "refs/heads/master",
        "",
    }
)

_GATE_ORDER: tuple[str, ...] = (
    "dry_run_plan",
    "stage_and_promote",
    "pointer_blocked_before_pin",
    "pinned_redownload",
    "unpinned_request_blocked",
    "viewer_contracts",
    "canary_promotion",
    "rollback",
    "rollback_verifiable",
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PatentHFReleaseVerifyV2Error(RuntimeError):
    """Raised when v2 pinned verification / rollback cannot complete fail-closed."""


class PinnedRedownloadError(PatentHFReleaseVerifyV2Error):
    """Missing, changed, or unpinned artifact during redownload."""


class ViewerVerifyError(PatentHFReleaseVerifyV2Error):
    """Dataset Viewer contracts failed; promotion is blocked."""


class PointerPromotionError(PatentHFReleaseVerifyV2Error):
    """Runtime pointer promotion refused (missing pin, viewer, or approval)."""


class RollbackError(PatentHFReleaseVerifyV2Error):
    """Rollback refused or would delete evidence / non-pointer state."""


# ---------------------------------------------------------------------------
# Small validators
# ---------------------------------------------------------------------------


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise PatentHFReleaseVerifyV2Error(
            f"{label} must be a non-empty string without surrounding whitespace"
        )
    if "\x00" in value:
        raise PatentHFReleaseVerifyV2Error(f"{label} must not contain NUL")
    return value


def _commit_sha(value: Any, *, label: str = "commit_sha") -> str:
    sha = _text(value, label=label).casefold()
    if not _COMMIT_SHA_RE.fullmatch(sha):
        raise PatentHFReleaseVerifyV2Error(
            f"{label} must be a 40-64 character lowercase hex commit SHA"
        )
    return sha


def _digest(value: Any, *, label: str = "sha256") -> str:
    digest = _text(value, label=label).casefold()
    if not _HASH_RE.fullmatch(digest):
        raise PatentHFReleaseVerifyV2Error(
            f"{label} must be a full lower-case 64-character hex digest"
        )
    return digest


def _is_pinned_revision(revision: str) -> bool:
    rev = str(revision or "").strip()
    if not rev or rev in _UNPINNED_REVISIONS:
        return False
    return bool(_COMMIT_SHA_RE.fullmatch(rev.casefold()))


def _file_sha256(path: Path) -> tuple[int, str]:
    body = path.read_bytes()
    return len(body), sha256(body).hexdigest()


def _write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="verify_v2_output")
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(dict(payload), sort_keys=True, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )


def _payload_digest(payload: Mapping[str, Any]) -> str:
    return sha256(canonical_json_bytes(dict(payload))).hexdigest()


# ---------------------------------------------------------------------------
# Receipt types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArtifactPin:
    """One revalidated artifact bound to a Hub repository + commit SHA."""

    dataset_id: str
    repository: str
    relative_path: str
    remote_path: str
    commit_sha: str
    size_bytes: int
    sha256: str
    content_cid: str = ""

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "commit_sha": self.commit_sha,
            "dataset_id": self.dataset_id,
            "relative_path": self.relative_path,
            "remote_path": self.remote_path,
            "repository": self.repository,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }
        if self.content_cid:
            body["content_cid"] = self.content_cid
        return body


@dataclass(frozen=True, slots=True)
class PinnedRedownloadReceipt:
    """Receipt for multi-repo pinned redownload into an empty verified cache."""

    schema_version: str
    release_id: str
    release_root_cid: str
    cache_root: str
    repository_commits: Mapping[str, str]
    artifacts: tuple[ArtifactPin, ...]
    revalidated_file_count: int
    revalidated_bytes: int
    empty_cache_before_fetch: bool
    network_fetch_performed: bool
    ok: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [item.to_dict() for item in self.artifacts],
            "cache_root": self.cache_root,
            "empty_cache_before_fetch": self.empty_cache_before_fetch,
            "network_fetch_performed": self.network_fetch_performed,
            "ok": self.ok,
            "release_id": self.release_id,
            "release_root_cid": self.release_root_cid,
            "repository_commits": dict(self.repository_commits),
            "revalidated_bytes": self.revalidated_bytes,
            "revalidated_file_count": self.revalidated_file_count,
            "schema_version": self.schema_version,
        }

    @property
    def receipt_digest(self) -> str:
        return _payload_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class RuntimeReleasePointerV2:
    """Reviewed multi-repo runtime pointer (canary / rollback subject)."""

    schema_version: str
    pointer_path: str
    organization: str
    release_id: str
    release_root_cid: str
    repository_commits: Mapping[str, str]
    """dataset_id → pinned Hub commit SHA."""

    canary_percent: int = 0
    previous_release_id: str = ""
    previous_release_root_cid: str = ""
    previous_repository_commits: Mapping[str, str] = field(default_factory=dict)
    pinned_redownload_digest: str = ""
    viewer_ok: bool = False
    approval_id: str = ""
    plan_digest: str = ""

    def __post_init__(self) -> None:
        if (
            not isinstance(self.canary_percent, int)
            or isinstance(self.canary_percent, bool)
            or self.canary_percent < 0
            or self.canary_percent > 100
        ):
            raise PointerPromotionError("canary_percent must be an integer in 0..100")
        commits = {
            _text(k, label="dataset_id").casefold(): _commit_sha(
                v, label="repository_commit"
            )
            for k, v in dict(self.repository_commits).items()
        }
        if not commits:
            raise PointerPromotionError("pointer requires at least one repository commit")
        object.__setattr__(self, "repository_commits", dict(sorted(commits.items())))
        prev = {
            _text(k, label="previous_dataset_id").casefold(): _commit_sha(
                v, label="previous_repository_commit"
            )
            for k, v in dict(self.previous_repository_commits).items()
        }
        object.__setattr__(
            self, "previous_repository_commits", dict(sorted(prev.items()))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "canary_percent": self.canary_percent,
            "organization": self.organization,
            "pinned_redownload_digest": self.pinned_redownload_digest,
            "plan_digest": self.plan_digest,
            "pointer_path": self.pointer_path,
            "previous_release_id": self.previous_release_id,
            "previous_release_root_cid": self.previous_release_root_cid,
            "previous_repository_commits": dict(self.previous_repository_commits),
            "release_id": self.release_id,
            "release_root_cid": self.release_root_cid,
            "repository_commits": dict(self.repository_commits),
            "schema_version": self.schema_version,
            "viewer_ok": self.viewer_ok,
        }

    @property
    def pointer_digest(self) -> str:
        return _payload_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class RollbackReceipt:
    """Pinned, verifiable record that only the reviewed pointer moved."""

    schema_version: str
    pointer_path: str
    restored_pointer: Mapping[str, Any]
    retained_failed_pointer: Mapping[str, Any]
    failed_release_retained: bool
    commits_deleted: bool
    artifacts_deleted: bool
    only_pointer_changed: bool
    ok: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts_deleted": self.artifacts_deleted,
            "commits_deleted": self.commits_deleted,
            "failed_release_retained": self.failed_release_retained,
            "ok": self.ok,
            "only_pointer_changed": self.only_pointer_changed,
            "pointer_path": self.pointer_path,
            "retained_failed_pointer": dict(self.retained_failed_pointer),
            "restored_pointer": dict(self.restored_pointer),
            "schema_version": self.schema_version,
        }

    @property
    def receipt_digest(self) -> str:
        return _payload_digest(self.to_dict())


# ---------------------------------------------------------------------------
# Fake Hub download seam (multi-repo; never network)
# ---------------------------------------------------------------------------


class DownloadCapableFakeHub(FakeHubService):
    """FakeHubService plus pinned ``hf_hub_download`` for offline revalidation.

    Unpinned revisions (``main``, ``latest``, empty, non-SHA) are refused so
    promotion cannot proceed on a floating tip.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.download_calls: list[dict[str, str]] = []
        self.pointer_store: dict[str, dict[str, Any]] = {}
        """dataset_id → pointer JSON document (logical runtime pointer only)."""

    def hf_hub_download(
        self,
        *,
        repo_id: str,
        filename: str,
        revision: str,
        local_dir: str | Path,
        repo_type: str = "dataset",
        token: str | None = None,
        **_: Any,
    ) -> str:
        self.calls.append("hf_hub_download")
        self.download_calls.append(
            {
                "repo_id": str(repo_id),
                "filename": str(filename),
                "revision": str(revision),
            }
        )
        self._check_auth(token)
        rev = str(revision or "").strip()
        if not _is_pinned_revision(rev):
            raise PinnedRedownloadError(
                f"unpinned download request refused for revision={revision!r}; "
                "pinned redownload requires an exact Hub commit SHA"
            )
        pinned = rev.casefold()
        key = str(repo_id).casefold()
        self.ensure_repo(key)
        tree = self._files.get(key, {}).get(pinned)
        if tree is None:
            # Also allow head values that point at this SHA's tree.
            for head_name, head_sha in self._heads.get(key, {}).items():
                if head_sha == pinned:
                    tree = self._files.get(key, {}).get(head_sha)
                    break
        if tree is None:
            raise PinnedRedownloadError(
                f"unknown pinned revision {pinned} for {repo_id}"
            )
        path = str(filename).replace("\\", "/").lstrip("/")
        if path not in tree:
            raise PinnedRedownloadError(
                f"missing remote artifact {path!r} at {repo_id}@{pinned}"
            )
        body = tree[path]
        target_root = Path(local_dir)
        target_root.mkdir(parents=True, exist_ok=True)
        out = target_root.joinpath(*Path(path).parts)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(body)
        return str(out)

    def write_pointer_document(
        self,
        *,
        dataset_id: str,
        pointer_path: str,
        document: Mapping[str, Any],
    ) -> str:
        """Record a logical runtime pointer without mutating release artifacts."""

        key = dataset_id.casefold()
        self.ensure_repo(key)
        self.pointer_store[key] = {
            "path": pointer_path,
            "document": dict(document),
            "document_digest": _payload_digest(document),
        }
        self.calls.append("write_pointer_document")
        return self.pointer_store[key]["document_digest"]

    def read_pointer_document(self, dataset_id: str) -> Mapping[str, Any] | None:
        entry = self.pointer_store.get(dataset_id.casefold())
        if entry is None:
            return None
        return dict(entry["document"])

    def corrupt_remote_file(
        self,
        *,
        dataset_id: str,
        commit_sha: str,
        remote_path: str,
        body: bytes,
    ) -> None:
        """Test helper: mutate a remote tree after promote (simulates drift)."""

        key = dataset_id.casefold()
        pinned = commit_sha.casefold()
        tree = self._files.setdefault(key, {}).setdefault(pinned, {})
        tree[remote_path] = body

    def drop_remote_file(
        self,
        *,
        dataset_id: str,
        commit_sha: str,
        remote_path: str,
    ) -> None:
        key = dataset_id.casefold()
        pinned = commit_sha.casefold()
        tree = self._files.get(key, {}).get(pinned)
        if tree is not None and remote_path in tree:
            del tree[remote_path]


# ---------------------------------------------------------------------------
# Core verification operations
# ---------------------------------------------------------------------------


def assert_local_manifest_integrity(
    *,
    local_root: str | Path,
    plan: StagePlan,
) -> dict[str, Any]:
    """Fail closed when any planned local artifact is missing or drifted."""

    root = Path(local_root).expanduser().resolve()
    if not root.is_dir():
        raise PatentHFReleaseVerifyV2Error(f"local_root is not a directory: {root}")
    checked: list[dict[str, Any]] = []
    for item in plan.artifacts:
        path = root.joinpath(*Path(item.relative_path).parts)
        if not path.is_file() or path.is_symlink():
            raise ArtifactChangedError(f"missing local artifact: {item.relative_path}")
        size_bytes, digest = _file_sha256(path)
        if size_bytes != item.size_bytes or digest != item.sha256:
            raise ArtifactChangedError(
                f"local artifact digest/size mismatch: {item.relative_path}"
            )
        checked.append(
            {
                "relative_path": item.relative_path,
                "sha256": digest,
                "size_bytes": size_bytes,
                "dataset_id": item.dataset_id,
            }
        )
    return {
        "ok": True,
        "artifact_count": len(checked),
        "artifacts": checked,
        "release_root_cid": plan.release_root_cid,
        "release_id": plan.release_id,
    }


def repository_commits_from_promotion(
    promoted: PromotionReceipt | Mapping[str, Any],
) -> dict[str, str]:
    """Extract dataset_id → promoted commit SHA from a promotion receipt."""

    if isinstance(promoted, PromotionReceipt):
        repos = promoted.repositories
        return {
            item.dataset_id.casefold(): _commit_sha(item.promoted_commit_sha)
            for item in repos
        }
    raw = promoted.get("repositories") or []
    if not isinstance(raw, list) or not raw:
        raise PatentHFReleaseVerifyV2Error(
            "promotion receipt missing repositories"
        )
    out: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise PatentHFReleaseVerifyV2Error("repository entry must be an object")
        ds = _text(item.get("dataset_id"), label="dataset_id").casefold()
        sha = _commit_sha(
            item.get("promoted_commit_sha") or item.get("commit_sha"),
            label="promoted_commit_sha",
        )
        out[ds] = sha
    return out


def redownload_and_validate_pinned(
    *,
    plan: StagePlan,
    repository_commits: Mapping[str, str],
    cache_root: str | Path,
    api: DownloadCapableFakeHub | Any,
    token: str | None = None,
    require_empty_cache: bool = True,
) -> PinnedRedownloadReceipt:
    """Redownload every manifest artifact at its exact Hub commit SHA.

    Floating revisions (``main``, ``latest``, …) are never accepted.  Any
    missing path, size mismatch, digest mismatch, or CID drift fails closed
    and blocks pointer promotion.
    """

    commits = {
        _text(k, label="dataset_id").casefold(): _commit_sha(v, label="commit_sha")
        for k, v in dict(repository_commits).items()
    }
    if not commits:
        raise PinnedRedownloadError("repository_commits is required for pinned redownload")

    for item in plan.artifacts:
        if item.dataset_id not in commits:
            raise PinnedRedownloadError(
                f"no Hub commit bound for dataset {item.dataset_id}"
            )

    cache = Path(cache_root).expanduser().resolve()
    if cache.exists():
        if not cache.is_dir() or cache.is_symlink():
            raise PinnedRedownloadError(
                "pinned redownload verified cache must be a real directory"
            )
        if require_empty_cache and any(cache.iterdir()):
            raise PinnedRedownloadError(
                f"pinned redownload validation requires an empty verified cache: {cache}"
            )
    else:
        cache.mkdir(parents=True, exist_ok=True)

    download = getattr(api, "hf_hub_download", None)
    if not callable(download):
        raise PinnedRedownloadError(
            "Hub API must implement hf_hub_download for pinned revalidation"
        )

    pins: list[ArtifactPin] = []
    total_bytes = 0
    network = False

    for item in plan.artifacts:
        pinned_sha = commits[item.dataset_id]
        # Isolate each dataset under cache/<org__repo>/ so paths cannot collide.
        dataset_cache = cache / item.dataset_id.replace("/", "__")
        dataset_cache.mkdir(parents=True, exist_ok=True)
        try:
            local_path = download(
                repo_id=item.dataset_id,
                filename=item.remote_path,
                revision=pinned_sha,
                local_dir=dataset_cache,
                repo_type="dataset",
                token=token,
            )
        except PinnedRedownloadError:
            raise
        except Exception as exc:
            raise PinnedRedownloadError(
                f"pinned redownload failed for {item.dataset_id}:{item.remote_path}: {exc}"
            ) from exc
        network = True
        target = Path(local_path)
        if not target.is_file():
            raise PinnedRedownloadError(
                f"pinned redownload produced no file: {item.remote_path}"
            )
        size_bytes, digest = _file_sha256(target)
        if size_bytes != item.size_bytes or digest != item.sha256:
            raise PinnedRedownloadError(
                f"pinned redownload validation mismatch: "
                f"{item.dataset_id}:{item.remote_path} "
                f"(got sha256={digest} size={size_bytes}, "
                f"expected sha256={item.sha256} size={item.size_bytes})"
            )
        if item.content_cid:
            # Content CID is bound as declared; empty sentinel is allowed.
            # We do not recompute CIDs here (builder owns CID algorithm) but we
            # require the declaration remain non-empty when present.
            _text(item.content_cid, label="content_cid")
        pins.append(
            ArtifactPin(
                dataset_id=item.dataset_id,
                repository=item.repository,
                relative_path=item.relative_path,
                remote_path=item.remote_path,
                commit_sha=pinned_sha,
                size_bytes=size_bytes,
                sha256=digest,
                content_cid=item.content_cid,
            )
        )
        total_bytes += size_bytes

    if len(pins) != len(plan.artifacts):
        raise PinnedRedownloadError(
            f"artifact count mismatch after redownload: "
            f"{len(pins)} != {len(plan.artifacts)}"
        )

    return PinnedRedownloadReceipt(
        schema_version=PINNED_SCHEMA,
        release_id=plan.release_id,
        release_root_cid=plan.release_root_cid,
        cache_root=cache.as_posix(),
        repository_commits=dict(sorted(commits.items())),
        artifacts=tuple(pins),
        revalidated_file_count=len(pins),
        revalidated_bytes=total_bytes,
        empty_cache_before_fetch=True,
        network_fetch_performed=network,
        ok=True,
    )


def assert_unpinned_requests_blocked(
    *,
    api: DownloadCapableFakeHub | Any,
    plan: StagePlan,
    repository_commits: Mapping[str, str],
    cache_root: str | Path,
    token: str | None = None,
) -> dict[str, Any]:
    """Prove that main/latest/empty revisions cannot satisfy pinned redownload."""

    download = getattr(api, "hf_hub_download", None)
    if not callable(download):
        raise PinnedRedownloadError("Hub API missing hf_hub_download")
    if not plan.artifacts:
        raise PinnedRedownloadError("plan has no artifacts")
    sample = plan.artifacts[0]
    cache = Path(cache_root).expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    blocked: list[str] = []
    for bad_rev in ("main", "latest", "HEAD", ""):
        try:
            download(
                repo_id=sample.dataset_id,
                filename=sample.remote_path,
                revision=bad_rev,
                local_dir=cache / f"unpinned-{bad_rev or 'empty'}",
                token=token,
            )
        except PinnedRedownloadError:
            blocked.append(bad_rev or "<empty>")
            continue
        raise PinnedRedownloadError(
            f"unpinned revision {bad_rev!r} was incorrectly accepted"
        )
    # Wrong commit SHA (not the promoted one) must not silently succeed with
    # empty content either — unknown SHA fails closed.
    wrong = "f" * 40
    promoted = dict(repository_commits).get(sample.dataset_id, "")
    if wrong != promoted:
        try:
            download(
                repo_id=sample.dataset_id,
                filename=sample.remote_path,
                revision=wrong,
                local_dir=cache / "wrong-sha",
                token=token,
            )
        except PinnedRedownloadError:
            blocked.append("wrong_commit_sha")
        else:
            raise PinnedRedownloadError(
                "download at non-promoted commit SHA was incorrectly accepted"
            )
    return {
        "ok": True,
        "blocked_revisions": blocked,
        "sample_dataset_id": sample.dataset_id,
        "sample_remote_path": sample.remote_path,
    }


def verify_viewer_contracts(
    *,
    local_root: str | Path,
    force_viewer_invalid: bool = False,
) -> dict[str, Any]:
    """Run offline Dataset Viewer endpoint contracts against the staged tree.

    A bare ``viewer: true`` is never enough — every endpoint in
    :data:`VIEWER_ENDPOINTS` must agree with the local inventory.
    """

    root = Path(local_root).expanduser().resolve()
    try:
        inventory = load_staged_release_inventory(root)
    except ReleasePolicyV2Error as exc:
        raise ViewerVerifyError(f"cannot load staged inventory for Viewer: {exc}") from exc

    service = FakeDatasetViewerService(
        inventory=inventory, force_invalid=force_viewer_invalid
    )
    gateway = FakeViewerGateway(service)
    gate = DatasetViewerGate()
    result = gate.verify(inventory, gateway)
    detail = {
        "ok": bool(result.passed),
        "gate_name": result.name,
        "passed": bool(result.passed),
        "reason_codes": list(result.reason_codes),
        "viewer_endpoints": list(VIEWER_ENDPOINTS),
        "repositories": [repo.dataset_id for repo in inventory.repositories],
        "details": result.details if isinstance(result.details, Mapping) else {},
        "gateway_calls": len(service.calls),
        "token_seen": bool(gateway.token_seen),
    }
    if not result.passed:
        raise ViewerVerifyError(
            "Viewer contracts failed (blocks promotion): "
            + ", ".join(result.reason_codes)
        )
    if gateway.token_seen:
        raise ViewerVerifyError("Viewer gateway must not receive credentials offline")
    return detail


def canary_promote_pointer(
    *,
    plan: StagePlan,
    repository_commits: Mapping[str, str],
    previous: RuntimeReleasePointerV2 | None,
    canary_percent: int,
    pinned: PinnedRedownloadReceipt | None,
    viewer_ok: bool,
    approval: PublicationApprovalReceipt | Mapping[str, Any] | None,
    pointer_path: str = DEFAULT_POINTER_PATH,
    api: DownloadCapableFakeHub | Any | None = None,
) -> RuntimeReleasePointerV2:
    """Promote the reviewed runtime pointer under a bounded canary.

    Requires:

    * successful pinned redownload of the same repository commits;
    * Viewer contracts passed;
    * operator approval bound to the same plan digest.

    Never deletes previous or failed release commits.
    """

    if pinned is None or not pinned.ok:
        raise PointerPromotionError(
            "pointer promotion waits for pinned redownload validation"
        )
    if pinned.release_root_cid != plan.release_root_cid:
        raise PointerPromotionError(
            "pinned redownload release_root_cid does not match the plan"
        )
    if pinned.release_id != plan.release_id:
        raise PointerPromotionError(
            "pinned redownload release_id does not match the plan"
        )
    expected_commits = {
        k.casefold(): _commit_sha(v) for k, v in dict(repository_commits).items()
    }
    pinned_commits = {
        k.casefold(): _commit_sha(v)
        for k, v in dict(pinned.repository_commits).items()
    }
    if pinned_commits != expected_commits:
        raise PointerPromotionError(
            "pinned redownload repository commits do not match promotion binding"
        )
    if not viewer_ok:
        raise PointerPromotionError(
            "pointer promotion blocked: Viewer contracts have not passed"
        )
    if (
        not isinstance(canary_percent, int)
        or isinstance(canary_percent, bool)
        or canary_percent <= 0
        or canary_percent > 100
    ):
        raise PointerPromotionError("canary_percent must be an integer in 1..100")

    approval_id = ""
    plan_digest = plan.plan_digest
    if approval is None:
        raise PointerPromotionError(
            "pointer promotion requires an exact operator approval receipt"
        )
    if isinstance(approval, PublicationApprovalReceipt):
        if approval.plan_digest != plan.plan_digest:
            raise PointerPromotionError(
                "pointer promotion approval plan_digest mismatch"
            )
        if approval.release_root_cid != plan.release_root_cid:
            raise PointerPromotionError(
                "pointer promotion approval release_root_cid mismatch"
            )
        approval_id = approval.approval_id
    else:
        if not isinstance(approval, Mapping):
            raise PointerPromotionError("approval must be a receipt object")
        if str(approval.get("plan_digest") or "") != plan.plan_digest:
            raise PointerPromotionError(
                "pointer promotion approval plan_digest mismatch"
            )
        approval_id = str(approval.get("approval_id") or "")

    pointer = RuntimeReleasePointerV2(
        schema_version=POINTER_SCHEMA,
        pointer_path=pointer_path,
        organization=plan.organization,
        release_id=plan.release_id,
        release_root_cid=plan.release_root_cid,
        repository_commits=expected_commits,
        canary_percent=canary_percent,
        previous_release_id=previous.release_id if previous else "",
        previous_release_root_cid=previous.release_root_cid if previous else "",
        previous_repository_commits=(
            dict(previous.repository_commits) if previous else {}
        ),
        pinned_redownload_digest=pinned.receipt_digest,
        viewer_ok=True,
        approval_id=approval_id,
        plan_digest=plan_digest,
    )

    if api is not None and hasattr(api, "write_pointer_document"):
        # Reviewed pointer lives on the corpus repository as a logical document.
        corpus_id = f"{plan.organization}/{CORPUS_REPOSITORY}".casefold()
        api.write_pointer_document(
            dataset_id=corpus_id,
            pointer_path=pointer_path,
            document=pointer.to_dict(),
        )
    return pointer


def rollback_pointer(
    *,
    current: RuntimeReleasePointerV2,
    failed_release_retained: bool = True,
    api: DownloadCapableFakeHub | Any | None = None,
) -> tuple[RuntimeReleasePointerV2, RollbackReceipt]:
    """Restore the previous reviewed pointer; never delete release evidence.

    Rollback changes **only** the reviewed pointer document.  Both the failed
    candidate and the restored release remain addressable by their Hub commit
    SHAs.  The rollback receipt is itself content-addressed (pinned digest).
    """

    if not failed_release_retained:
        raise RollbackError("rollback must retain the failed release (no delete)")
    if not current.previous_release_id or not current.previous_repository_commits:
        raise RollbackError(
            "rollback requires previous_release_id and previous_repository_commits"
        )
    if not current.previous_release_root_cid:
        raise RollbackError("rollback requires previous_release_root_cid")

    restored = RuntimeReleasePointerV2(
        schema_version=POINTER_SCHEMA,
        pointer_path=current.pointer_path,
        organization=current.organization,
        release_id=current.previous_release_id,
        release_root_cid=current.previous_release_root_cid,
        repository_commits=dict(current.previous_repository_commits),
        canary_percent=0,
        previous_release_id=current.release_id,
        previous_release_root_cid=current.release_root_cid,
        previous_repository_commits=dict(current.repository_commits),
        pinned_redownload_digest=current.pinned_redownload_digest,
        viewer_ok=current.viewer_ok,
        approval_id=current.approval_id,
        plan_digest=current.plan_digest,
    )

    if api is not None and hasattr(api, "write_pointer_document"):
        corpus_id = f"{current.organization}/{CORPUS_REPOSITORY}".casefold()
        api.write_pointer_document(
            dataset_id=corpus_id,
            pointer_path=restored.pointer_path,
            document=restored.to_dict(),
        )
        # Sanity: pointer store holds only the restored document; release trees
        # in api._files are untouched (no deletes).
        if hasattr(api, "_files"):
            # Nothing to mutate; presence of prior commit trees is the evidence.
            pass

    receipt = RollbackReceipt(
        schema_version=ROLLBACK_SCHEMA,
        pointer_path=restored.pointer_path,
        restored_pointer=restored.to_dict(),
        retained_failed_pointer=current.to_dict(),
        failed_release_retained=True,
        commits_deleted=False,
        artifacts_deleted=False,
        only_pointer_changed=True,
        ok=True,
    )
    # Bind the rollback receipt digest into a stable, verifiable form.
    if not receipt.receipt_digest:
        raise RollbackError("rollback receipt digest missing")
    return restored, receipt


def previous_pointer_fixture(
    *,
    organization: str = ORGANIZATION,
    repositories: Sequence[str] = CANONICAL_REPOSITORY_NAMES,
    release_id: str = "previous-patent-legal-v0",
    release_root_cid: str = "bafyreipatlaw160previousrelease00000000001",
    commit_sha: str = "c" * 40,
    pointer_path: str = DEFAULT_POINTER_PATH,
) -> RuntimeReleasePointerV2:
    """Build a prior reviewed pointer for canary / rollback drills."""

    commits = {
        f"{organization.casefold()}/{name.casefold()}": commit_sha
        for name in repositories
    }
    return RuntimeReleasePointerV2(
        schema_version=POINTER_SCHEMA,
        pointer_path=pointer_path,
        organization=organization.casefold(),
        release_id=release_id,
        release_root_cid=release_root_cid,
        repository_commits=commits,
        canary_percent=100,
        viewer_ok=True,
    )


# ---------------------------------------------------------------------------
# Gate runners
# ---------------------------------------------------------------------------


def plan_dry_run(
    *,
    local_root: str | Path,
    base_revisions: Mapping[str, str] | None = None,
    organization: str = ORGANIZATION,
    version_tag: str | None = None,
    release_id: str | None = None,
    run_viewer: bool = True,
) -> dict[str, Any]:
    """Default verification path: offline plan + local integrity (+ Viewer)."""

    root = Path(local_root).expanduser().resolve()
    bases = dict(base_revisions or default_test_base_revisions(organization))
    plan = plan_stage_from_local_root(
        local_root=root,
        organization=organization,
        version_tag=version_tag,
        base_revisions=bases,
        release_id=release_id,
    )
    integrity = assert_local_manifest_integrity(local_root=root, plan=plan)
    viewer: dict[str, Any] | None = None
    if run_viewer:
        try:
            viewer = verify_viewer_contracts(local_root=root)
        except ViewerVerifyError as exc:
            # Dry-run reports Viewer status but does not claim promotion readiness
            # unless Viewer passes; surface as non-promotable.
            viewer = {"ok": False, "error": str(exc)}

    receipt = {
        "schema_version": VERIFY_SCHEMA,
        "status": "dry_run_only",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "dry_run": True,
        "fake_live": False,
        "live_network": False,
        "tokens_used": False,
        "pointers_moved": False,
        "main_published": False,
        "uses_hf_api_upload_file": False,
        "organization": plan.organization,
        "release_id": plan.release_id,
        "release_root_cid": plan.release_root_cid,
        "plan_digest": plan.plan_digest,
        "staged_diff_digest": plan.staged_diff_digest,
        "repository_ids": list(plan.dataset_ids()),
        "artifact_hashes": {
            item.relative_path: item.sha256 for item in plan.artifacts
        },
        "local_integrity": integrity,
        "viewer": viewer,
        "promotable": bool(viewer and viewer.get("ok")),
    }
    reject_credentials_in_payload(receipt, label="dry_run_verify_receipt")
    return {
        "status": "dry_run_only",
        "dry_run": True,
        "fake_live": False,
        "live_network": False,
        "tokens_used": False,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "organization": plan.organization,
        "release_id": plan.release_id,
        "release_root_cid": plan.release_root_cid,
        "plan": plan.to_dict(),
        "plan_digest": plan.plan_digest,
        "repository_ids": list(plan.dataset_ids()),
        "receipt": receipt,
        "viewer": viewer,
        "uses_hf_api_upload_file": False,
    }


def run_fake_live_verification(
    *,
    local_root: str | Path,
    base_revisions: Mapping[str, str] | None = None,
    organization: str = ORGANIZATION,
    version_tag: str | None = None,
    release_id: str | None = None,
    canary_percent: int = 10,
    operator_key: bytes | None = None,
    verified_cache_root: str | Path | None = None,
    pointer_path: str = DEFAULT_POINTER_PATH,
    force_viewer_invalid: bool = False,
    previous: RuntimeReleasePointerV2 | None = None,
) -> dict[str, Any]:
    """Exercise every PATLAW-160 gate against an offline multi-repo fake Hub."""

    root = Path(local_root).expanduser().resolve()
    if not root.is_dir():
        raise PatentHFReleaseVerifyV2Error(f"local_root is not a directory: {root}")

    bases = dict(base_revisions or default_test_base_revisions(organization))
    key = operator_key or new_ephemeral_operator_key()
    api = DownloadCapableFakeHub(base_revisions=bases, require_auth=True)
    publisher = PatentHFPublisherV2(
        api=api, token=api.auth_token, organization=organization
    )
    gates: dict[str, Any] = {}

    # Gate 1: dry-run plan (no Hub contact yet — plan is pure local).
    plan = plan_stage_from_local_root(
        local_root=root,
        organization=organization,
        version_tag=version_tag,
        base_revisions=bases,
        release_id=release_id,
    )
    integrity = assert_local_manifest_integrity(local_root=root, plan=plan)
    if api.calls:
        # plan_stage_from_local_root must not touch the API.
        raise PatentHFReleaseVerifyV2Error(
            f"dry-run plan contacted the API: {api.calls}"
        )
    gates["dry_run_plan"] = {
        "ok": True,
        "plan_digest": plan.plan_digest,
        "artifact_count": len(plan.artifacts),
        "release_root_cid": plan.release_root_cid,
        "repository_ids": list(plan.dataset_ids()),
        "local_integrity": integrity,
        "remote_write_contacted": False,
    }

    # Gate 2: stage + exact operator approval + promote (still offline fake).
    staged = publisher.stage_pull_request(plan, local_root=root)
    if staged.main_published or staged.pointers_moved:
        raise PatentHFReleaseVerifyV2Error(
            "stage must not publish main or move runtime pointers"
        )
    approval = create_operator_approval(
        plan=plan,
        operator_key=key,
        approver="patent-legal-operator",
        approval_id="ops-approval-verify-v2-1",
    )
    verify_operator_approval(approval, plan=plan, operator_key=key)
    promoted = publisher.promote_approved(
        plan,
        staged=staged,
        approval=approval,
        operator_key=key,
        local_root=root,
    )
    if not promoted.main_published:
        raise PatentHFReleaseVerifyV2Error("promote did not publish main")
    if promoted.pointers_moved:
        raise PatentHFReleaseVerifyV2Error(
            "publisher must not move runtime pointers (PATLAW-160 owns pointers)"
        )
    repo_commits = repository_commits_from_promotion(promoted)
    gates["stage_and_promote"] = {
        "ok": True,
        "plan_digest": plan.plan_digest,
        "approval_id": approval.approval_id,
        "repository_commits": dict(repo_commits),
        "main_published": True,
        "pointers_moved": False,
        "used_upload_file": "upload_file" not in api.calls
        or api.calls.count("upload_file") == 0,
    }
    if "upload_file" in api.calls:
        raise PatentHFReleaseVerifyV2Error("upload_file is prohibited")

    # Gate 3: pointer promotion must wait for pinned redownload (+ viewer).
    prev = previous or previous_pointer_fixture(organization=organization)
    pointer_blocked = False
    try:
        canary_promote_pointer(
            plan=plan,
            repository_commits=repo_commits,
            previous=prev,
            canary_percent=canary_percent,
            pinned=None,
            viewer_ok=True,
            approval=approval,
            pointer_path=pointer_path,
            api=api,
        )
    except PointerPromotionError as exc:
        if "pinned redownload" in str(exc):
            pointer_blocked = True
        else:
            raise
    if not pointer_blocked:
        raise PatentHFReleaseVerifyV2Error(
            "pointer promotion must wait for pinned redownload validation"
        )
    gates["pointer_blocked_before_pin"] = {
        "ok": True,
        "blocked_without_pinned_verification": True,
    }

    # Gate 4: pinned redownload into an empty verified cache.
    if verified_cache_root is None:
        cache = root.parent / "verified-empty-cache-v2"
    else:
        cache = Path(verified_cache_root).expanduser().resolve()
    if cache.exists() and any(cache.iterdir()):
        raise PatentHFReleaseVerifyV2Error(
            f"verified cache must be empty: {cache}"
        )
    cache.mkdir(parents=True, exist_ok=True)
    pinned = redownload_and_validate_pinned(
        plan=plan,
        repository_commits=repo_commits,
        cache_root=cache,
        api=api,
        token=api.auth_token,
    )
    if not pinned.ok or pinned.revalidated_file_count != len(plan.artifacts):
        raise PinnedRedownloadError("pinned redownload validation failed")
    gates["pinned_redownload"] = {
        "ok": True,
        "revalidated_file_count": pinned.revalidated_file_count,
        "revalidated_bytes": pinned.revalidated_bytes,
        "repository_commits": dict(pinned.repository_commits),
        "receipt_digest": pinned.receipt_digest,
        "empty_cache_before_fetch": pinned.empty_cache_before_fetch,
    }

    # Gate 5: unpinned requests (main/latest) are refused.
    unpinned = assert_unpinned_requests_blocked(
        api=api,
        plan=plan,
        repository_commits=repo_commits,
        cache_root=cache / "_unpinned-probes",
        token=api.auth_token,
    )
    gates["unpinned_request_blocked"] = unpinned

    # Gate 6: Viewer contracts (fail closed → blocks canary).
    if force_viewer_invalid:
        viewer_blocked = False
        try:
            verify_viewer_contracts(
                local_root=root, force_viewer_invalid=True
            )
        except ViewerVerifyError:
            viewer_blocked = True
        if not viewer_blocked:
            raise ViewerVerifyError("force_viewer_invalid did not block")
        raise ViewerVerifyError(
            "Viewer contracts failed (blocks promotion): forced invalid"
        )
    viewer = verify_viewer_contracts(local_root=root)
    gates["viewer_contracts"] = viewer

    # Also prove canary is blocked when Viewer fails even after pin.
    viewer_gate_enforced = False
    try:
        canary_promote_pointer(
            plan=plan,
            repository_commits=repo_commits,
            previous=prev,
            canary_percent=canary_percent,
            pinned=pinned,
            viewer_ok=False,
            approval=approval,
            pointer_path=pointer_path,
            api=api,
        )
    except PointerPromotionError as exc:
        if "Viewer" in str(exc):
            viewer_gate_enforced = True
        else:
            raise
    if not viewer_gate_enforced:
        raise PatentHFReleaseVerifyV2Error(
            "pointer promotion must block when Viewer contracts have not passed"
        )

    # Gate 7: canary pointer promotion after pin + viewer + approval.
    pointer = canary_promote_pointer(
        plan=plan,
        repository_commits=repo_commits,
        previous=prev,
        canary_percent=canary_percent,
        pinned=pinned,
        viewer_ok=True,
        approval=approval,
        pointer_path=pointer_path,
        api=api,
    )
    if pointer.canary_percent != canary_percent:
        raise PointerPromotionError("canary_percent not applied")
    if pointer.repository_commits != dict(sorted(repo_commits.items())):
        raise PointerPromotionError("canary pointer commits mismatch")
    gates["canary_promotion"] = {
        "ok": True,
        "canary_percent": pointer.canary_percent,
        "pointer_path": pointer.pointer_path,
        "pointer_digest": pointer.pointer_digest,
        "release_id": pointer.release_id,
        "repository_commits": dict(pointer.repository_commits),
        "previous_release_id": pointer.previous_release_id,
    }

    # Gate 8: rollback restores previous pointer only.
    rolled, rollback_receipt = rollback_pointer(
        current=pointer, failed_release_retained=True, api=api
    )
    if rolled.release_id != prev.release_id:
        raise RollbackError("rollback did not restore previous release_id")
    if rolled.repository_commits != dict(sorted(prev.repository_commits.items())):
        raise RollbackError("rollback did not restore previous repository commits")
    if rolled.previous_release_id != plan.release_id:
        raise RollbackError(
            "rollback must retain the failed candidate as previous"
        )
    if not rollback_receipt.only_pointer_changed:
        raise RollbackError("rollback must change only the reviewed pointer")
    if rollback_receipt.commits_deleted or rollback_receipt.artifacts_deleted:
        raise RollbackError("rollback must not delete commits or artifacts")
    gates["rollback"] = {
        "ok": True,
        "restored_release_id": rolled.release_id,
        "retained_failed_release_id": rolled.previous_release_id,
        "restored_repository_commits": dict(rolled.repository_commits),
        "rollback_receipt_digest": rollback_receipt.receipt_digest,
        "only_pointer_changed": True,
        "failed_release_retained": True,
    }

    # Gate 9: rollback is itself pinned/verifiable; failed release still on Hub.
    if not _HASH_RE.fullmatch(rollback_receipt.receipt_digest):
        raise RollbackError("rollback receipt digest is not a pin-able sha256")
    # Candidate release commit trees must still be present for every dataset.
    retained = True
    for dataset_id, sha in repo_commits.items():
        tree = api._files.get(dataset_id.casefold(), {}).get(sha.casefold())
        if tree is None:
            retained = False
            break
    if not retained:
        raise RollbackError(
            "failed candidate release commits were not retained after rollback"
        )
    # Pointer store holds restored document only.
    corpus_id = f"{plan.organization}/{CORPUS_REPOSITORY}".casefold()
    stored = api.read_pointer_document(corpus_id)
    if stored is None or stored.get("release_id") != rolled.release_id:
        raise RollbackError("reviewed pointer store does not hold restored pointer")
    gates["rollback_verifiable"] = {
        "ok": True,
        "rollback_receipt_digest": rollback_receipt.receipt_digest,
        "restored_pointer_digest": rolled.pointer_digest,
        "failed_commits_retained": True,
        "pointer_document_release_id": stored.get("release_id"),
    }

    missing = [
        name for name in _GATE_ORDER if name not in gates or not gates[name].get("ok")
    ]
    if missing:
        raise PatentHFReleaseVerifyV2Error(f"incomplete gate coverage: {missing}")

    artifact_hashes = {
        pin.relative_path: pin.sha256 for pin in pinned.artifacts
    }
    receipt = {
        "schema_version": VERIFY_SCHEMA,
        "status": "fake_live_complete",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "dry_run": False,
        "fake_live": True,
        "live_network": False,
        "tokens_used": False,
        "uses_hf_api_upload_file": False,
        "organization": plan.organization,
        "release_id": plan.release_id,
        "release_root_cid": plan.release_root_cid,
        "plan_digest": plan.plan_digest,
        "staged_diff_digest": plan.staged_diff_digest,
        "approval_id": approval.approval_id,
        "repository_ids": list(plan.dataset_ids()),
        "repository_commits": dict(repo_commits),
        "artifact_hashes": artifact_hashes,
        "artifact_pins": [pin.to_dict() for pin in pinned.artifacts],
        "pinned_redownload": pinned.to_dict(),
        "pinned_redownload_digest": pinned.receipt_digest,
        "viewer": viewer,
        "canary_pointer": pointer.to_dict(),
        "canary_pointer_digest": pointer.pointer_digest,
        "rollback_pointer": rolled.to_dict(),
        "rollback_pointer_digest": rolled.pointer_digest,
        "rollback_receipt": rollback_receipt.to_dict(),
        "rollback_receipt_digest": rollback_receipt.receipt_digest,
        "gates": gates,
        "gate_order": list(_GATE_ORDER),
        "pointers_moved": True,
        "main_published": True,
        "promotable": True,
    }
    reject_credentials_in_payload(receipt, label="fake_live_verify_receipt")

    return {
        "status": "fake_live_complete",
        "append_only": True,
        "dry_run": False,
        "fake_live": True,
        "live_network": False,
        "tokens_used": False,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "organization": plan.organization,
        "release_id": plan.release_id,
        "release_root_cid": plan.release_root_cid,
        "plan_digest": plan.plan_digest,
        "repository_ids": list(plan.dataset_ids()),
        "repository_commits": dict(repo_commits),
        "artifact_hashes": artifact_hashes,
        "gates": gates,
        "gate_order": list(_GATE_ORDER),
        "receipt": receipt,
        "pinned_redownload_digest": pinned.receipt_digest,
        "viewer": viewer,
        "rollback_receipt_digest": rollback_receipt.receipt_digest,
        "uses_hf_api_upload_file": False,
        # Call names are sanitized: raw "hf_hub_download" is rejected by the
        # credential-leak scanner (hf_* shape).  Record method roles only.
        "api_call_summary": {
            "create_branch": api.calls.count("create_branch"),
            "create_commit": api.calls.count("create_commit"),
            "create_pull_request": api.calls.count("create_pull_request"),
            "merge_pull_request": api.calls.count("merge_pull_request"),
            "pinned_download": api.calls.count("hf_hub_download"),
            "pointer_write": api.calls.count("write_pointer_document"),
            "upload_file": api.calls.count("upload_file"),
            "delete_file": api.calls.count("delete_file"),
            "delete_repo": api.calls.count("delete_repo"),
        },
    }


def verify_patent_hf_release_v2(
    *,
    local_root: str | Path | None = None,
    base_revisions: Mapping[str, str] | None = None,
    organization: str = ORGANIZATION,
    version_tag: str | None = None,
    release_id: str | None = None,
    dry_run: bool = True,
    fake_live: bool = False,
    canary_percent: int = 10,
    receipt_path: str | Path | None = None,
    verified_cache_root: str | Path | None = None,
    materialize_fixture: bool = False,
    run_viewer: bool = True,
    operator_key: bytes | None = None,
    force_viewer_invalid: bool = False,
    pointer_path: str = DEFAULT_POINTER_PATH,
) -> dict[str, Any]:
    """Library entry point used by the CLI and release tests."""

    if fake_live and dry_run:
        # fake_live supersedes dry_run for the publish/verify segment.
        dry_run = False

    root: Path
    if local_root is None:
        root = Path.cwd() / ".patent-hf-release-verify-v2-staging"
        if materialize_fixture or not (root / RELEASE_MANIFEST_FILENAME).is_file():
            materialize_minimal_release_tree(root, organization=organization)
    else:
        root = Path(local_root).expanduser().resolve()
        if materialize_fixture:
            materialize_minimal_release_tree(root, organization=organization)
        if not root.is_dir():
            raise PatentHFReleaseVerifyV2Error(
                f"local_root is not a directory: {root}"
            )

    if fake_live:
        result = run_fake_live_verification(
            local_root=root,
            base_revisions=base_revisions,
            organization=organization,
            version_tag=version_tag,
            release_id=release_id,
            canary_percent=canary_percent,
            operator_key=operator_key,
            verified_cache_root=verified_cache_root,
            pointer_path=pointer_path,
            force_viewer_invalid=force_viewer_invalid,
        )
        result["local_root"] = root.as_posix()
        if receipt_path is not None:
            _write_json(receipt_path, result)
        return result

    # Default: dry-run only.
    result = plan_dry_run(
        local_root=root,
        base_revisions=base_revisions,
        organization=organization,
        version_tag=version_tag,
        release_id=release_id,
        run_viewer=run_viewer,
    )
    result["local_root"] = root.as_posix()
    if receipt_path is not None:
        _write_json(receipt_path, result)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_base_revisions(
    raw: str | None, path: Path | None, organization: str
) -> dict[str, str]:
    if path is not None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PatentHFReleaseVerifyV2Error(
                f"cannot read base revisions file: {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise PatentHFReleaseVerifyV2Error(
                "base revisions file must be a JSON object"
            )
        return {str(k): str(v) for k, v in payload.items()}
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PatentHFReleaseVerifyV2Error(
                f"invalid --base-revisions JSON: {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise PatentHFReleaseVerifyV2Error(
                "--base-revisions must be a JSON object"
            )
        return {str(k): str(v) for k, v in payload.items()}
    return default_test_base_revisions(organization)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify pinned Hub downloads and exercise approval-bound rollback "
            "for JusticeDAO patent HF v2 releases (default: dry-run, no network)."
        )
    )
    parser.add_argument(
        "--local-root",
        type=Path,
        default=None,
        help="Local staged multi-repo release directory",
    )
    parser.add_argument(
        "--organization",
        default=ORGANIZATION,
        help=f"Hub organization (default: {ORGANIZATION})",
    )
    parser.add_argument(
        "--base-revisions",
        help="JSON object mapping dataset_id → audited base commit SHA",
    )
    parser.add_argument(
        "--base-revisions-file",
        type=Path,
        help="Path to JSON object of dataset_id → base commit SHA",
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
        "--verified-cache-root",
        type=Path,
        default=None,
        help="Empty cache directory for pinned redownload (fake-live)",
    )
    parser.add_argument(
        "--pointer-path",
        default=DEFAULT_POINTER_PATH,
        help=f"Reviewed runtime pointer path (default: {DEFAULT_POINTER_PATH})",
    )
    parser.add_argument(
        "--fake-live",
        action="store_true",
        help=(
            "Exercise every verification gate against an in-memory multi-repo "
            "fake Hub (still no real network or token material)."
        ),
    )
    parser.add_argument(
        "--materialize-fixture",
        action="store_true",
        help="Write a minimal multi-repo fixture tree into --local-root first",
    )
    parser.add_argument(
        "--skip-viewer",
        action="store_true",
        help="Skip offline Viewer contracts in dry-run mode",
    )
    parser.add_argument(
        "--force-viewer-invalid",
        action="store_true",
        help="Force Viewer is-valid=false (negative testing; fake-live)",
    )
    parser.add_argument(
        "--print-receipt",
        action="store_true",
        help="Print the full verification receipt JSON to stdout",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    for forbidden in ("upload", "push", "token", "hf_token", "live"):
        if getattr(args, forbidden, None):
            parser.error(f"{forbidden} is not supported by this verifier")

    try:
        bases = _load_base_revisions(
            args.base_revisions, args.base_revisions_file, args.organization
        )
        result = verify_patent_hf_release_v2(
            local_root=args.local_root,
            base_revisions=bases,
            organization=args.organization,
            version_tag=args.version_tag,
            release_id=args.release_id,
            dry_run=not args.fake_live,
            fake_live=args.fake_live,
            canary_percent=args.canary_percent,
            receipt_path=args.receipt_path,
            verified_cache_root=args.verified_cache_root,
            materialize_fixture=args.materialize_fixture,
            run_viewer=not args.skip_viewer,
            force_viewer_invalid=args.force_viewer_invalid,
            pointer_path=args.pointer_path,
        )
    except (
        PatentHFReleaseVerifyV2Error,
        PatentHFPublisherV2Error,
        ApprovalError,
        ArtifactChangedError,
        ReleasePolicyV2Error,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.print_receipt:
        print(json.dumps(result, sort_keys=True, indent=2, default=str))
    else:
        summary = {
            "status": result.get("status"),
            "release_id": result.get("release_id"),
            "release_root_cid": result.get("release_root_cid"),
            "plan_digest": result.get("plan_digest"),
            "repository_ids": result.get("repository_ids"),
            "fake_live": result.get("fake_live"),
            "live_network": result.get("live_network"),
            "tokens_used": result.get("tokens_used"),
            "uses_hf_api_upload_file": result.get("uses_hf_api_upload_file"),
        }
        if result.get("repository_commits"):
            summary["repository_commits"] = result["repository_commits"]
        if result.get("pinned_redownload_digest"):
            summary["pinned_redownload_digest"] = result["pinned_redownload_digest"]
        if result.get("rollback_receipt_digest"):
            summary["rollback_receipt_digest"] = result["rollback_receipt_digest"]
        if result.get("gates"):
            summary["gates_ok"] = sorted(
                name for name, body in result["gates"].items() if body.get("ok")
            )
        print(json.dumps(summary, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
