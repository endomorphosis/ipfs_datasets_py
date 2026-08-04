#!/usr/bin/env python3
"""Verify pinned Hub redownload of corpus / BM25 / vector / graph artifacts.

PATLAW-177: fail-closed multi-projection verification for hub index packages
produced by PATLAW-174, admitted by PATLAW-175, and staged by PATLAW-176.

Default mode is **dry-run** (credential-free, no live Hub contact):

1. Load a staged hub index package directory (or materialize the default
   multi-family fixture).
2. Project package artifacts into a multi-repo release manifest enumerating
   corpus / BM25 / vector / knowledge-graph files.
3. Assert local package integrity (every planned artifact present and digest
   matches).
4. Emit a multi-projection verification plan receipt binding repository IDs,
   package root CID, and every artifact digest by projection.

``--fake-service`` / ``--fake-live`` exercises the complete offline gate
sequence against an in-memory multi-repo Hub stand-in (no network, no real
tokens):

  dry-run plan → stage + exact operator approval → promote →
  pinned redownload at exact Hub SHAs → unpinned (main/latest) blocked →
  multi-projection coverage receipt

Any missing/changed artifact, unpinned request, or manifest mismatch blocks.
A successful receipt binds repository IDs, revision SHAs, package root CID,
and every artifact digest grouped by projection family.

This script never imports a live ``HfApi`` client on the default path, never
reads ``HF_TOKEN`` for remote I/O in dry-run/fake modes, never selects
``main`` / ``latest`` as a verification revision, and never calls
``upload_file``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.huggingface.release import (  # noqa: E402
    canonical_json_bytes,
)
from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (  # noqa: E402
    BM25_REPOSITORY,
    CANONICAL_REPOSITORY_NAMES,
    CORPUS_REPOSITORY,
    KNOWLEDGE_GRAPH_REPOSITORY,
    ORGANIZATION,
    VECTORS_REPOSITORY,
)
from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (  # noqa: E402
    ArtifactChangedError,
    DEFAULT_TARGET_REVISION,
    FakeHubService,
    PatentHFPublisherV2,
    PatentHFPublisherV2Error,
    PromotionReceipt,
    StagePlan,
    create_operator_approval,
    default_test_base_revisions,
    new_ephemeral_operator_key,
    plan_stage_from_local_root,
    reject_credentials_in_payload,
    verify_operator_approval,
)
from ipfs_datasets_py.processors.domains.patent.hub_index_package import (  # noqa: E402
    INDEX_FAMILIES,
    MANIFEST_FILENAME,
)


# ---------------------------------------------------------------------------
# Identity / schema pins (PATLAW-177)
# ---------------------------------------------------------------------------

TASK_ID: Final = "PATLAW-177"
GOAL_ID: Final = "PATLAW-G213"
PROGRAM_ID: Final = "patent-legal-intelligence-v1"
VERIFY_SCHEMA: Final = "patent-legal-hub-index-verification-receipt/v1"
PINNED_SCHEMA: Final = "patent-legal-hub-index-pinned-redownload/v1"
PRODUCER: Final = "producer:hub-index-verify"
CONFIG_ID: Final = "config:hub-index-verify/v1"
CODE_VERSION: Final = "1.0.0"

PROJECTION_FAMILIES: Final[tuple[str, ...]] = (
    "corpus",
    "bm25",
    "vectors",
    "knowledge_graph",
)

_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_UNPINNED_REVISIONS: Final[frozenset[str]] = frozenset(
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

_GATE_ORDER: Final[tuple[str, ...]] = (
    "dry_run_plan",
    "stage_and_promote",
    "pinned_redownload",
    "unpinned_request_blocked",
    "projection_coverage",
)

_ROLE_BY_REPO: Final[Mapping[str, str]] = {
    CORPUS_REPOSITORY: "corpus",
    VECTORS_REPOSITORY: "vectors",
    BM25_REPOSITORY: "bm25",
    KNOWLEDGE_GRAPH_REPOSITORY: "knowledge_graph",
}

_HF_TOKEN_VALUE_RE = re.compile(r"(?i)\bhf_[A-Za-z0-9]{20,}\b")
_HF_TOKEN_ASSIGN_RE = re.compile(
    r'(?i)(?:"|\b)(?:HF_TOKEN|HUGGING_FACE_HUB_TOKEN|HUGGINGFACE_HUB_TOKEN|'
    r'HUGGINGFACE_TOKEN)(?:"|\b)\s*[:=]\s*"[^"]{8,}"'
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HubIndexVerifyError(RuntimeError):
    """CLI-level failure for hub index pinned verification (fail-closed)."""

    code: str = "hub_index_verify_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class PinnedRedownloadError(HubIndexVerifyError):
    """Missing, changed, or unpinned artifact during redownload."""

    code = "pinned_redownload_error"


class ManifestMismatchError(HubIndexVerifyError):
    """Local package / release manifest integrity failure."""

    code = "manifest_mismatch"


class LiveNetworkRefusedError(HubIndexVerifyError):
    """Live Hub contact refused without explicit operator mode."""

    code = "live_network_refused"


# ---------------------------------------------------------------------------
# Small validators / helpers
# ---------------------------------------------------------------------------


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise HubIndexVerifyError(
            f"{label} must be a non-empty string without surrounding whitespace"
        )
    if "\x00" in value:
        raise HubIndexVerifyError(f"{label} must not contain NUL")
    return value


def _commit_sha(value: Any, *, label: str = "commit_sha") -> str:
    sha = _text(value, label=label).casefold()
    if not _COMMIT_SHA_RE.fullmatch(sha):
        raise HubIndexVerifyError(
            f"{label} must be a 40-64 character lowercase hex commit SHA"
        )
    return sha


def _digest(value: Any, *, label: str = "sha256") -> str:
    digest = _text(value, label=label).casefold()
    if not _HASH_RE.fullmatch(digest):
        raise HubIndexVerifyError(
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


def _payload_digest(payload: Mapping[str, Any]) -> str:
    return sha256(canonical_json_bytes(dict(payload))).hexdigest()


def _reject_secrets_in_payload(payload: Any, *, label: str) -> None:
    reject_credentials_in_payload(payload, label=label)
    text = json.dumps(payload, sort_keys=True, default=str)
    if _HF_TOKEN_VALUE_RE.search(text) or _HF_TOKEN_ASSIGN_RE.search(text):
        raise HubIndexVerifyError(f"{label} embeds Hub credential material")
    lowered = text.casefold()
    if "bearer " in lowered or "password=" in lowered:
        raise HubIndexVerifyError(f"{label} embeds credential material")


def _write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    _reject_secrets_in_payload(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HubIndexVerifyError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise HubIndexVerifyError(f"JSON root must be an object: {path}")
    return dict(payload)


def _load_base_revisions(raw: str | None, path: Path | None) -> dict[str, str]:
    if raw and path:
        raise HubIndexVerifyError("provide either --base-revisions or --base-revisions-file")
    if path is not None:
        payload = _load_json_object(path)
    elif raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HubIndexVerifyError(f"invalid --base-revisions JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise HubIndexVerifyError("--base-revisions must be a JSON object")
        payload = dict(payload)
    else:
        return default_test_base_revisions()
    out: dict[str, str] = {}
    for key, value in payload.items():
        ds = _text(key, label="dataset_id").casefold()
        out[ds] = _commit_sha(value, label=f"base_revision[{ds}]")
    if not out:
        raise HubIndexVerifyError("base revisions map is empty")
    return out


def _load_stage_module() -> ModuleType:
    """Load PATLAW-176 stage helpers for package → release-manifest projection."""

    stage_path = REPOSITORY_ROOT / "scripts/ops/legal_data/stage_patent_legal_hub_indexes.py"
    if not stage_path.is_file():
        raise HubIndexVerifyError(
            f"PATLAW-176 stage script required but missing: {stage_path}"
        )
    name = "stage_patent_legal_hub_indexes_for_verify"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, stage_path)
    if spec is None or spec.loader is None:
        raise HubIndexVerifyError(f"cannot load stage module from {stage_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _family_for_artifact(
    *,
    repository: str,
    role: str | None = None,
    relative_path: str = "",
) -> str:
    repo = str(repository or "").casefold()
    if repo in _ROLE_BY_REPO:
        return _ROLE_BY_REPO[repo]
    if role and str(role).casefold() in PROJECTION_FAMILIES:
        return str(role).casefold()
    path = relative_path.replace("\\", "/").lstrip("./")
    for family in PROJECTION_FAMILIES:
        if path.startswith(f"indexes/{family}/"):
            return family
    return "corpus"


# ---------------------------------------------------------------------------
# Receipt types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArtifactPin:
    """One revalidated artifact bound to a Hub repository + commit SHA."""

    dataset_id: str
    repository: str
    family: str
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
            "family": self.family,
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
    """Receipt for multi-projection pinned redownload into an empty cache."""

    schema_version: str
    package_root_cid: str
    release_id: str
    release_root_cid: str
    cache_root: str
    repository_commits: Mapping[str, str]
    artifacts: tuple[ArtifactPin, ...]
    projection_digests: Mapping[str, Mapping[str, str]]
    projection_artifact_counts: Mapping[str, int]
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
            "package_root_cid": self.package_root_cid,
            "projection_artifact_counts": dict(self.projection_artifact_counts),
            "projection_digests": {
                family: dict(digests)
                for family, digests in self.projection_digests.items()
            },
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


# ---------------------------------------------------------------------------
# Fake Hub download seam (multi-repo; never network)
# ---------------------------------------------------------------------------


class DownloadCapableFakeHub(FakeHubService):
    """FakeHubService plus pinned ``hf_hub_download`` for offline revalidation.

    Unpinned revisions (``main``, ``latest``, empty, non-SHA) are refused so
    verification cannot succeed on a floating tip.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.download_calls: list[dict[str, str]] = []

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
        raise ManifestMismatchError(f"local_root is not a directory: {root}")
    checked: list[dict[str, Any]] = []
    by_family: dict[str, int] = {family: 0 for family in PROJECTION_FAMILIES}
    for item in plan.artifacts:
        path = root.joinpath(*Path(item.relative_path).parts)
        if not path.is_file() or path.is_symlink():
            raise ArtifactChangedError(f"missing local artifact: {item.relative_path}")
        size_bytes, digest = _file_sha256(path)
        if size_bytes != item.size_bytes or digest != item.sha256:
            raise ArtifactChangedError(
                f"local artifact digest/size mismatch: {item.relative_path}"
            )
        family = _family_for_artifact(
            repository=item.repository,
            role=getattr(item, "role", None),
            relative_path=item.relative_path,
        )
        if family in by_family:
            by_family[family] += 1
        checked.append(
            {
                "relative_path": item.relative_path,
                "sha256": digest,
                "size_bytes": size_bytes,
                "dataset_id": item.dataset_id,
                "family": family,
            }
        )
    for family in PROJECTION_FAMILIES:
        if by_family.get(family, 0) < 1:
            raise ManifestMismatchError(
                f"local plan missing projection family {family!r}"
            )
    return {
        "ok": True,
        "artifact_count": len(checked),
        "artifacts": checked,
        "projection_artifact_counts": dict(by_family),
        "release_root_cid": plan.release_root_cid,
        "release_id": plan.release_id,
    }


def repository_commits_from_promotion(
    promoted: PromotionReceipt | Mapping[str, Any],
) -> dict[str, str]:
    """Extract dataset_id → promoted commit SHA from a promotion receipt."""

    if isinstance(promoted, PromotionReceipt):
        return {
            item.dataset_id.casefold(): _commit_sha(item.promoted_commit_sha)
            for item in promoted.repositories
        }
    raw = promoted.get("repositories") or []
    if not isinstance(raw, list) or not raw:
        raise HubIndexVerifyError("promotion receipt missing repositories")
    out: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise HubIndexVerifyError("repository entry must be an object")
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
    package_root_cid: str | None = None,
) -> PinnedRedownloadReceipt:
    """Redownload every manifest artifact at its exact Hub commit SHA.

    Floating revisions (``main``, ``latest``, …) are never accepted.  Any
    missing path, size mismatch, digest mismatch, or incomplete projection
    coverage fails closed.
    """

    commits = {
        _text(k, label="dataset_id").casefold(): _commit_sha(v, label="commit_sha")
        for k, v in dict(repository_commits).items()
    }
    if not commits:
        raise PinnedRedownloadError(
            "repository_commits is required for pinned redownload"
        )

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
    projection_digests: dict[str, dict[str, str]] = {
        family: {} for family in PROJECTION_FAMILIES
    }
    family_counts: dict[str, int] = {family: 0 for family in PROJECTION_FAMILIES}

    for item in plan.artifacts:
        pinned_sha = commits[item.dataset_id]
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
            _text(item.content_cid, label="content_cid")
        family = _family_for_artifact(
            repository=item.repository,
            role=getattr(item, "role", None),
            relative_path=item.relative_path,
        )
        if family not in projection_digests:
            projection_digests[family] = {}
            family_counts[family] = 0
        projection_digests[family][item.relative_path] = digest
        family_counts[family] = family_counts.get(family, 0) + 1
        pins.append(
            ArtifactPin(
                dataset_id=item.dataset_id,
                repository=item.repository,
                family=family,
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

    for family in PROJECTION_FAMILIES:
        if family_counts.get(family, 0) < 1:
            raise PinnedRedownloadError(
                f"pinned redownload missing projection family {family!r}"
            )

    root_cid = package_root_cid or plan.release_root_cid
    return PinnedRedownloadReceipt(
        schema_version=PINNED_SCHEMA,
        package_root_cid=str(root_cid),
        release_id=plan.release_id,
        release_root_cid=plan.release_root_cid,
        cache_root=cache.as_posix(),
        repository_commits=dict(sorted(commits.items())),
        artifacts=tuple(pins),
        projection_digests={
            family: dict(sorted(digests.items()))
            for family, digests in sorted(projection_digests.items())
        },
        projection_artifact_counts=dict(sorted(family_counts.items())),
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


def assert_projection_coverage(
    *,
    pinned: PinnedRedownloadReceipt,
    plan: StagePlan,
) -> dict[str, Any]:
    """Ensure every required projection family has verified digests."""

    counts = dict(pinned.projection_artifact_counts)
    for family in PROJECTION_FAMILIES:
        if counts.get(family, 0) < 1:
            raise PinnedRedownloadError(
                f"projection coverage missing family {family!r}"
            )
    repo_ids = sorted({pin.dataset_id for pin in pinned.artifacts})
    expected = sorted(plan.dataset_ids())
    if set(repo_ids) != set(expected):
        raise PinnedRedownloadError(
            f"repository coverage mismatch: got {repo_ids}, expected {expected}"
        )
    for pin in pinned.artifacts:
        if pin.commit_sha != pinned.repository_commits.get(pin.dataset_id):
            raise PinnedRedownloadError(
                f"artifact pin commit mismatch for {pin.relative_path}"
            )
        family_digests = pinned.projection_digests.get(pin.family) or {}
        if family_digests.get(pin.relative_path) != pin.sha256:
            raise PinnedRedownloadError(
                f"projection digest map mismatch for {pin.relative_path}"
            )
    return {
        "ok": True,
        "projection_families": list(PROJECTION_FAMILIES),
        "projection_artifact_counts": counts,
        "repository_ids": repo_ids,
        "repository_commits": dict(pinned.repository_commits),
        "artifact_count": pinned.revalidated_file_count,
    }


# ---------------------------------------------------------------------------
# Workflow modes
# ---------------------------------------------------------------------------


def build_plan_from_package(
    *,
    package_dir: str | Path,
    organization: str = ORGANIZATION,
    base_revisions: Mapping[str, str] | None = None,
    version_tag: str | None = None,
    release_id: str | None = None,
    branch_name: str | None = None,
    target_revision: str = DEFAULT_TARGET_REVISION,
) -> tuple[StagePlan, dict[str, Any], dict[str, Any]]:
    """Project a hub index package into a stage plan + release manifest."""

    stage = _load_stage_module()
    root = Path(package_dir).expanduser().resolve()
    if not root.is_dir():
        raise HubIndexVerifyError(f"package_dir is not a directory: {root}")
    if not (root / MANIFEST_FILENAME).is_file():
        raise HubIndexVerifyError(f"missing package manifest: {root / MANIFEST_FILENAME}")

    release_manifest = stage.build_release_manifest_from_package(
        root, organization=organization
    )
    bases = dict(base_revisions or default_test_base_revisions(organization))
    plan = plan_stage_from_local_root(
        local_root=root,
        manifest=release_manifest,
        organization=organization,
        version_tag=version_tag or str(release_manifest.get("version_tag") or ""),
        base_revisions=bases,
        branch_name=branch_name,
        target_revision=target_revision,
        release_id=release_id or str(release_manifest.get("release_id") or ""),
    )
    return plan, release_manifest, bases


def plan_dry_run(
    *,
    package_dir: str | Path,
    organization: str = ORGANIZATION,
    base_revisions: Mapping[str, str] | None = None,
    version_tag: str | None = None,
    release_id: str | None = None,
) -> dict[str, Any]:
    """Dry-run: multi-projection plan + local integrity, no Hub contact."""

    plan, release_manifest, bases = build_plan_from_package(
        package_dir=package_dir,
        organization=organization,
        base_revisions=base_revisions,
        version_tag=version_tag,
        release_id=release_id,
    )
    integrity = assert_local_manifest_integrity(local_root=package_dir, plan=plan)

    artifact_hashes = {
        item.relative_path: item.sha256 for item in plan.artifacts
    }
    projection_digests: dict[str, dict[str, str]] = {
        family: {} for family in PROJECTION_FAMILIES
    }
    for item in plan.artifacts:
        family = _family_for_artifact(
            repository=item.repository,
            role=getattr(item, "role", None),
            relative_path=item.relative_path,
        )
        projection_digests.setdefault(family, {})[item.relative_path] = item.sha256

    package_root_cid = str(
        release_manifest.get("package_root_cid") or plan.release_root_cid
    )
    receipt = {
        "schema_version": VERIFY_SCHEMA,
        "status": "dry_run_only",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "config_id": CONFIG_ID,
        "code_version": CODE_VERSION,
        "dry_run": True,
        "fake_live": False,
        "live_network": False,
        "tokens_used": False,
        "uses_hf_api_upload_file": False,
        "organization": plan.organization,
        "package_root_cid": package_root_cid,
        "release_id": plan.release_id,
        "release_root_cid": plan.release_root_cid,
        "plan_digest": plan.plan_digest,
        "staged_diff_digest": plan.staged_diff_digest,
        "repository_ids": list(plan.dataset_ids()),
        "repository_commits": {
            ds: bases[ds] for ds in plan.dataset_ids() if ds in bases
        },
        "base_revisions": dict(sorted(bases.items())),
        "index_families_present": list(INDEX_FAMILIES),
        "projection_families": list(PROJECTION_FAMILIES),
        "projection_artifact_counts": dict(
            integrity.get("projection_artifact_counts")
            or release_manifest.get("projection_artifact_counts")
            or {}
        ),
        "projection_digests": {
            family: dict(sorted(digests.items()))
            for family, digests in sorted(projection_digests.items())
        },
        "artifact_hashes": dict(sorted(artifact_hashes.items())),
        "artifact_count": len(plan.artifacts),
        "main_published": False,
        "pointers_moved": False,
        "promotable": False,
        "local_integrity": integrity,
        "gates": {
            "dry_run_plan": {
                "ok": True,
                "plan_digest": plan.plan_digest,
                "artifact_count": len(plan.artifacts),
                "release_root_cid": plan.release_root_cid,
                "package_root_cid": package_root_cid,
                "repository_ids": list(plan.dataset_ids()),
                "projection_artifact_counts": integrity.get(
                    "projection_artifact_counts"
                ),
                "remote_write_contacted": False,
            }
        },
        "gate_order": list(_GATE_ORDER),
        "operator_next_steps": [
            "Review package_root_cid and projection artifact counts",
            "Run --fake-service to exercise pinned redownload offline",
            "Live Hub verification remains operator-invoked only",
            "Unpinned main/latest selection is forbidden",
        ],
    }
    _reject_secrets_in_payload(receipt, label="dry_run_verify_receipt")
    return {
        "status": "dry_run_only",
        "append_only": True,
        "dry_run": True,
        "fake_live": False,
        "live_network": False,
        "tokens_used": False,
        "uses_hf_api_upload_file": False,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "organization": plan.organization,
        "package_root_cid": package_root_cid,
        "release_id": plan.release_id,
        "release_root_cid": plan.release_root_cid,
        "plan_digest": plan.plan_digest,
        "repository_ids": list(plan.dataset_ids()),
        "projection_artifact_counts": receipt["projection_artifact_counts"],
        "projection_digests": receipt["projection_digests"],
        "artifact_hashes": receipt["artifact_hashes"],
        "gates": receipt["gates"],
        "gate_order": list(_GATE_ORDER),
        "receipt": receipt,
    }


def run_fake_live_verification(
    *,
    package_dir: str | Path,
    base_revisions: Mapping[str, str] | None = None,
    organization: str = ORGANIZATION,
    version_tag: str | None = None,
    release_id: str | None = None,
    operator_key: bytes | None = None,
    verified_cache_root: str | Path | None = None,
) -> dict[str, Any]:
    """Exercise every PATLAW-177 gate against an offline multi-repo fake Hub."""

    root = Path(package_dir).expanduser().resolve()
    if not root.is_dir():
        raise HubIndexVerifyError(f"package_dir is not a directory: {root}")

    plan, release_manifest, bases = build_plan_from_package(
        package_dir=root,
        organization=organization,
        base_revisions=base_revisions,
        version_tag=version_tag,
        release_id=release_id,
    )
    package_root_cid = str(
        release_manifest.get("package_root_cid") or plan.release_root_cid
    )
    key = operator_key or new_ephemeral_operator_key()
    api = DownloadCapableFakeHub(base_revisions=bases, require_auth=True)
    publisher = PatentHFPublisherV2(
        api=api, token=api.auth_token, organization=organization
    )
    gates: dict[str, Any] = {}

    # Gate 1: dry-run plan (no Hub contact yet).
    integrity = assert_local_manifest_integrity(local_root=root, plan=plan)
    if api.calls:
        raise HubIndexVerifyError(f"dry-run plan contacted the API: {api.calls}")
    gates["dry_run_plan"] = {
        "ok": True,
        "plan_digest": plan.plan_digest,
        "artifact_count": len(plan.artifacts),
        "release_root_cid": plan.release_root_cid,
        "package_root_cid": package_root_cid,
        "repository_ids": list(plan.dataset_ids()),
        "local_integrity": integrity,
        "remote_write_contacted": False,
    }

    # Gate 2: stage + exact operator approval + promote (offline fake).
    staged = publisher.stage_pull_request(plan, local_root=root)
    if staged.main_published or staged.pointers_moved:
        raise HubIndexVerifyError(
            "stage must not publish main or move runtime pointers"
        )
    approval = create_operator_approval(
        plan=plan,
        operator_key=key,
        approver="patent-legal-operator",
        approval_id="ops-approval-hub-index-verify-1",
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
        raise HubIndexVerifyError("promote did not publish main")
    if promoted.pointers_moved:
        raise HubIndexVerifyError(
            "publisher must not move runtime pointers (owned by later tasks)"
        )
    repo_commits = repository_commits_from_promotion(promoted)
    gates["stage_and_promote"] = {
        "ok": True,
        "plan_digest": plan.plan_digest,
        "approval_id": approval.approval_id,
        "repository_commits": dict(repo_commits),
        "main_published": True,
        "pointers_moved": False,
        "used_upload_file": api.calls.count("upload_file") == 0,
    }
    if "upload_file" in api.calls:
        raise HubIndexVerifyError("upload_file is prohibited")

    # Gate 3: pinned redownload into an empty verified cache.
    if verified_cache_root is None:
        cache = root.parent / "verified-empty-cache-hub-index"
    else:
        cache = Path(verified_cache_root).expanduser().resolve()
    if cache.exists() and any(cache.iterdir()):
        raise HubIndexVerifyError(f"verified cache must be empty: {cache}")
    cache.mkdir(parents=True, exist_ok=True)
    pinned = redownload_and_validate_pinned(
        plan=plan,
        repository_commits=repo_commits,
        cache_root=cache,
        api=api,
        token=api.auth_token,
        package_root_cid=package_root_cid,
    )
    if not pinned.ok or pinned.revalidated_file_count != len(plan.artifacts):
        raise PinnedRedownloadError("pinned redownload validation failed")
    gates["pinned_redownload"] = {
        "ok": True,
        "revalidated_file_count": pinned.revalidated_file_count,
        "revalidated_bytes": pinned.revalidated_bytes,
        "repository_commits": dict(pinned.repository_commits),
        "projection_artifact_counts": dict(pinned.projection_artifact_counts),
        "receipt_digest": pinned.receipt_digest,
        "empty_cache_before_fetch": pinned.empty_cache_before_fetch,
    }

    # Gate 4: unpinned requests (main/latest) are refused.
    unpinned = assert_unpinned_requests_blocked(
        api=api,
        plan=plan,
        repository_commits=repo_commits,
        cache_root=cache / "_unpinned-probes",
        token=api.auth_token,
    )
    gates["unpinned_request_blocked"] = unpinned

    # Gate 5: multi-projection coverage receipt.
    coverage = assert_projection_coverage(pinned=pinned, plan=plan)
    gates["projection_coverage"] = coverage

    missing = [
        name for name in _GATE_ORDER if name not in gates or not gates[name].get("ok")
    ]
    if missing:
        raise HubIndexVerifyError(f"incomplete gate coverage: {missing}")

    artifact_hashes = {pin.relative_path: pin.sha256 for pin in pinned.artifacts}
    receipt = {
        "schema_version": VERIFY_SCHEMA,
        "status": "fake_live_complete",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "config_id": CONFIG_ID,
        "code_version": CODE_VERSION,
        "dry_run": False,
        "fake_live": True,
        "live_network": False,
        "tokens_used": False,
        "uses_hf_api_upload_file": False,
        "organization": plan.organization,
        "package_root_cid": package_root_cid,
        "release_id": plan.release_id,
        "release_root_cid": plan.release_root_cid,
        "plan_digest": plan.plan_digest,
        "staged_diff_digest": plan.staged_diff_digest,
        "approval_id": approval.approval_id,
        "repository_ids": list(plan.dataset_ids()),
        "repository_commits": dict(repo_commits),
        "index_families_present": list(INDEX_FAMILIES),
        "projection_families": list(PROJECTION_FAMILIES),
        "projection_artifact_counts": dict(pinned.projection_artifact_counts),
        "projection_digests": {
            family: dict(digests)
            for family, digests in pinned.projection_digests.items()
        },
        "artifact_hashes": artifact_hashes,
        "artifact_pins": [pin.to_dict() for pin in pinned.artifacts],
        "pinned_redownload": pinned.to_dict(),
        "pinned_redownload_digest": pinned.receipt_digest,
        "gates": gates,
        "gate_order": list(_GATE_ORDER),
        "pointers_moved": False,
        "main_published": True,
        "promotable": True,
    }
    _reject_secrets_in_payload(receipt, label="fake_live_verify_receipt")

    return {
        "status": "fake_live_complete",
        "append_only": True,
        "dry_run": False,
        "fake_live": True,
        "live_network": False,
        "tokens_used": False,
        "uses_hf_api_upload_file": False,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "organization": plan.organization,
        "package_root_cid": package_root_cid,
        "release_id": plan.release_id,
        "release_root_cid": plan.release_root_cid,
        "plan_digest": plan.plan_digest,
        "repository_ids": list(plan.dataset_ids()),
        "repository_commits": dict(repo_commits),
        "projection_artifact_counts": dict(pinned.projection_artifact_counts),
        "projection_digests": {
            family: dict(digests)
            for family, digests in pinned.projection_digests.items()
        },
        "artifact_hashes": artifact_hashes,
        "gates": gates,
        "gate_order": list(_GATE_ORDER),
        "receipt": receipt,
        "pinned_redownload_digest": pinned.receipt_digest,
        "api_call_summary": {
            "create_branch": api.calls.count("create_branch"),
            "create_commit": api.calls.count("create_commit"),
            "create_pull_request": api.calls.count("create_pull_request"),
            "merge_pull_request": api.calls.count("merge_pull_request"),
            "pinned_download": api.calls.count("hf_hub_download"),
            "upload_file": api.calls.count("upload_file"),
            "delete_file": api.calls.count("delete_file"),
            "delete_repo": api.calls.count("delete_repo"),
        },
    }


def verify_patent_legal_hub_indexes(
    *,
    package_dir: str | Path | None = None,
    default_fixture: bool = False,
    stage_dir: str | Path | None = None,
    base_revisions: Mapping[str, str] | None = None,
    organization: str = ORGANIZATION,
    version_tag: str | None = None,
    release_id: str | None = None,
    dry_run: bool = True,
    fake_live: bool = False,
    live: bool = False,
    receipt_path: str | Path | None = None,
    verified_cache_root: str | Path | None = None,
    operator_key: bytes | None = None,
) -> dict[str, Any]:
    """Library entry point used by the CLI and release tests."""

    if live:
        raise LiveNetworkRefusedError(
            "live Hub verification requires an operator-injected API client; "
            "use --fake-service for CI or inject a reviewed client in an "
            "operator-controlled process (this CLI refuses implicit live contact)"
        )

    if fake_live and dry_run:
        dry_run = False

    stage = _load_stage_module()
    if package_dir is not None:
        root = stage.resolve_package_dir(
            package_dir=package_dir,
            default_fixture=False,
            organization=organization,
        )
    else:
        # Default fixture when no package dir is supplied (CLI convenience / tests).
        fixture_stage = (
            Path(stage_dir).expanduser().resolve()
            if stage_dir is not None
            else Path(tempfile.mkdtemp(prefix="hub-index-verify-"))
        )
        root = stage.resolve_package_dir(
            package_dir=None,
            default_fixture=True,
            stage_dir=fixture_stage,
            organization=organization,
        )

    if fake_live:
        result = run_fake_live_verification(
            package_dir=root,
            base_revisions=base_revisions,
            organization=organization,
            version_tag=version_tag,
            release_id=release_id,
            operator_key=operator_key,
            verified_cache_root=verified_cache_root,
        )
    else:
        result = plan_dry_run(
            package_dir=root,
            organization=organization,
            base_revisions=base_revisions,
            version_tag=version_tag,
            release_id=release_id,
        )

    if receipt_path is not None:
        _write_json(Path(receipt_path), result.get("receipt") or result)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            f"Verify pinned Hub redownload of corpus/BM25/vector/graph hub index "
            f"artifacts ({TASK_ID}). Default mode is dry-run (no Hub contact)."
        )
    )
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument(
        "--package-dir",
        type=Path,
        default=None,
        help="Staged hub index package directory (PATLAW-174)",
    )
    input_group.add_argument(
        "--default-fixture",
        action="store_true",
        help="Materialize the built-in multi-family package then verify",
    )
    parser.add_argument(
        "--stage-dir",
        type=Path,
        default=None,
        help="Staging directory for --default-fixture",
    )
    parser.add_argument(
        "--organization",
        default=ORGANIZATION,
        help=f"Lowercase Hub organization (default: {ORGANIZATION})",
    )
    parser.add_argument(
        "--base-revisions-file",
        type=Path,
        default=None,
        help="Dataset id → audited base commit SHA JSON map",
    )
    parser.add_argument(
        "--base-revisions",
        default=None,
        help="Inline base revision map JSON",
    )
    parser.add_argument(
        "--version-tag",
        default=None,
        help="Optional layout/release version tag override",
    )
    parser.add_argument(
        "--release-id",
        default=None,
        help="Optional release id override",
    )
    parser.add_argument(
        "--receipt-out",
        type=Path,
        default=None,
        help="Write verification receipt JSON",
    )
    parser.add_argument(
        "--verified-cache-root",
        type=Path,
        default=None,
        help="Empty cache directory for pinned redownload (fake-live)",
    )
    parser.add_argument(
        "--fake-service",
        "--fake-live",
        dest="fake_live",
        action="store_true",
        help="Use in-memory FakeHubService (no network; supervisor-safe)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Operator-only live Hub mode (this CLI refuses implicit live contact; "
            "inject a reviewed API client instead)"
        ),
    )
    parser.add_argument(
        "--list-projection-families",
        action="store_true",
        help="Print required projection family names and exit",
    )
    parser.add_argument(
        "--list-index-families",
        action="store_true",
        help="Print required index family names and exit",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]
    if "--list-projection-families" in raw and not any(
        flag in raw
        for flag in ("--package-dir", "--default-fixture", "--fake-service", "--fake-live")
    ):
        for name in PROJECTION_FAMILIES:
            print(name)
        return 0
    if "--list-index-families" in raw and not any(
        flag in raw
        for flag in ("--package-dir", "--default-fixture", "--fake-service", "--fake-live")
    ):
        for name in INDEX_FAMILIES:
            print(name)
        return 0

    parser = _parser()
    args = parser.parse_args(argv)

    if args.list_projection_families:
        for name in PROJECTION_FAMILIES:
            print(name)
        return 0
    if args.list_index_families:
        for name in INDEX_FAMILIES:
            print(name)
        return 0

    try:
        bases = _load_base_revisions(args.base_revisions, args.base_revisions_file)
        result = verify_patent_legal_hub_indexes(
            package_dir=args.package_dir,
            default_fixture=bool(args.default_fixture),
            stage_dir=args.stage_dir,
            base_revisions=bases,
            organization=str(args.organization).casefold(),
            version_tag=args.version_tag,
            release_id=args.release_id,
            dry_run=not bool(args.fake_live),
            fake_live=bool(args.fake_live),
            live=bool(args.live),
            receipt_path=args.receipt_out,
            verified_cache_root=args.verified_cache_root,
        )
    except (
        HubIndexVerifyError,
        ArtifactChangedError,
        PatentHFPublisherV2Error,
        ValueError,
        TypeError,
        OSError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    summary = {
        "task_id": result.get("task_id"),
        "goal_id": result.get("goal_id"),
        "status": result.get("status"),
        "dry_run": result.get("dry_run"),
        "fake_live": result.get("fake_live"),
        "live_network": result.get("live_network"),
        "package_root_cid": result.get("package_root_cid"),
        "release_root_cid": result.get("release_root_cid"),
        "plan_digest": result.get("plan_digest"),
        "repository_ids": result.get("repository_ids"),
        "projection_artifact_counts": result.get("projection_artifact_counts"),
    }
    if result.get("repository_commits"):
        summary["repository_commits"] = result["repository_commits"]
    if result.get("pinned_redownload_digest"):
        summary["pinned_redownload_digest"] = result["pinned_redownload_digest"]
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
