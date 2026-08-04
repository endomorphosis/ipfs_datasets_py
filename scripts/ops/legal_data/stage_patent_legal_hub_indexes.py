#!/usr/bin/env python3
"""Stage authenticated Hub PR for corpus / BM25 / vector / graph artifacts.

PATLAW-176: fail-closed staging of multi-artifact hub index packages produced
by PATLAW-174 and admitted by PATLAW-175.

Default mode is **dry-run** (credential-free, no live Hub contact):

1. Load a staged hub index package directory (or materialize the default
   multi-family fixture).
2. Optionally require a PATLAW-175 admission receipt that binds
   ``package_root_cid``.
3. Project package artifacts into a publisher-compatible release manifest
   enumerating corpus / BM25 / vector / knowledge-graph files.
4. Build an add-only stage plan with plan / staged-diff digests.
5. Emit a staging receipt for exact human operator approval — without
   uploading to ``main`` or mutating remote default branches.

Operator workflow after a successful dry-run receipt:

1. ``--mode dry-run``  — plan + package/admission verification only (default)
2. ``--mode stage``    — authenticated add-only branch + PR (``--fake-service``
   for CI; live Hub requires an operator-injected API client)
3. ``--mode sign``     — create operator approval from an external key file
4. ``--mode promote``  — merge staged PRs after verifying operator approval

This script never:

* uploads directly to ``main`` / ``master``;
* embeds or logs Hub tokens;
* moves runtime release pointers (see PATLAW-177 / PATLAW-160);
* self-approves without an external operator key file;
* contacts the live Hub on the default dry-run path.

``--fake-service`` exercises the offline stage/promote path for supervisor tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Final, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (  # noqa: E402
    BM25_REPOSITORY,
    CANONICAL_REPOSITORY_NAMES,
    CORPUS_REPOSITORY,
    KNOWLEDGE_GRAPH_REPOSITORY,
    ORGANIZATION,
    VECTORS_REPOSITORY,
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
    default_test_base_revisions,
    plan_stage_from_local_root,
    reject_credentials_in_payload,
    resolve_hub_token,
)
from ipfs_datasets_py.processors.domains.patent.hf_release_v2 import (  # noqa: E402
    RELEASE_MANIFEST_FILENAME,
)
from ipfs_datasets_py.processors.domains.patent.hub_index_package import (  # noqa: E402
    ARTIFACTS_INVENTORY_FILENAME,
    INDEX_FAMILIES,
    MANIFEST_FILENAME,
    PACKAGE_ROOT_FILENAME,
    RECEIPT_FILENAME,
    ROLE_TO_REPOSITORY,
    HubIndexPackageError,
    load_package_manifest,
    package_patent_legal_hub_indexes,
)


# ---------------------------------------------------------------------------
# Identity / schema pins (PATLAW-176)
# ---------------------------------------------------------------------------

TASK_ID: Final = "PATLAW-176"
GOAL_ID: Final = "PATLAW-G212"
PROGRAM_ID: Final = "patent-legal-intelligence-v1"
STAGE_RECEIPT_SCHEMA: Final = "patent-legal-hub-index-stage-receipt/v1"
DRY_RUN_RECEIPT_SCHEMA: Final = "patent-legal-hub-index-dry-run-staging-receipt/v1"
PRODUCER: Final = "producer:hub-index-stage"
CONFIG_ID: Final = "config:hub-index-stage/v1"
CODE_VERSION: Final = "1.0.0"

ADMISSION_RECEIPT_FILENAME: Final = "hub-index-admission-receipt.json"
ADMISSION_RECEIPT_SCHEMA: Final = "patent-legal-hub-index-admission-receipt/v1"

PROHIBITED_DEFAULT_BRANCHES: Final[frozenset[str]] = frozenset(
    {"main", "master", "refs/heads/main", "refs/heads/master"}
)

# Package-level support files published to the corpus repository as pins.
_PACKAGE_SUPPORT_FILES: Final[tuple[str, ...]] = (
    MANIFEST_FILENAME,
    PACKAGE_ROOT_FILENAME,
    RECEIPT_FILENAME,
    ARTIFACTS_INVENTORY_FILENAME,
    "layout-bundle.json",
)

_ROLE_BY_REPO: Final[Mapping[str, str]] = {
    CORPUS_REPOSITORY: "corpus",
    VECTORS_REPOSITORY: "vectors",
    BM25_REPOSITORY: "bm25",
    KNOWLEDGE_GRAPH_REPOSITORY: "knowledge_graph",
}

_INDEX_PREFIX_TO_REPO: Final[tuple[tuple[str, str], ...]] = (
    ("indexes/corpus/", CORPUS_REPOSITORY),
    ("indexes/bm25/", BM25_REPOSITORY),
    ("indexes/vectors/", VECTORS_REPOSITORY),
    ("indexes/knowledge_graph/", KNOWLEDGE_GRAPH_REPOSITORY),
)

_HF_TOKEN_VALUE_RE = re.compile(r"(?i)\bhf_[A-Za-z0-9]{20,}\b")
_HF_TOKEN_ASSIGN_RE = re.compile(
    r'(?i)(?:"|\b)(?:HF_TOKEN|HUGGING_FACE_HUB_TOKEN|HUGGINGFACE_HUB_TOKEN|'
    r'HUGGINGFACE_TOKEN)(?:"|\b)\s*[:=]\s*"[^"]{8,}"'
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StageHubIndexError(RuntimeError):
    """CLI-level failure for hub index staging (fail-closed)."""

    code: str = "hub_index_stage_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class AdmissionRequiredError(StageHubIndexError):
    """Raised when a valid admission receipt is required but missing/invalid."""

    code = "admission_required"


class AdmissionMismatchError(StageHubIndexError):
    """Raised when an admission receipt does not bind the package root."""

    code = "admission_mismatch"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StageHubIndexError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise StageHubIndexError(f"JSON root must be an object: {path}")
    return dict(payload)


def _write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    _reject_secrets_in_payload(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _reject_secrets_in_payload(payload: Any, *, label: str) -> None:
    """Fail closed if receipts embed Hub-token shaped secrets."""
    blob = json.dumps(payload, sort_keys=True, default=str)
    if _HF_TOKEN_VALUE_RE.search(blob) or _HF_TOKEN_ASSIGN_RE.search(blob):
        raise StageHubIndexError(
            f"{label} embeds credential-shaped material (refusing receipt)"
        )


def _sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _file_sha256(path: Path) -> tuple[int, str]:
    body = path.read_bytes()
    return len(body), _sha256_bytes(body)


def _load_base_revisions(raw: str | None, path: Path | None) -> dict[str, str]:
    if path is not None:
        data = _load_json_object(path)
        return {str(k): str(v) for k, v in data.items()}
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StageHubIndexError(f"invalid --base-revisions JSON: {exc}") from exc
        if not isinstance(data, Mapping):
            raise StageHubIndexError("--base-revisions must be a JSON object")
        return {str(k): str(v) for k, v in data.items()}
    raise StageHubIndexError(
        "base revisions are required (--base-revisions or --base-revisions-file)"
    )


def _load_operator_key(
    path: Path | None, env_name: str = "PATENT_HF_OPERATOR_APPROVAL_KEY"
) -> bytes:
    if path is not None:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise StageHubIndexError(
                f"cannot read operator key file: {path}: {exc}"
            ) from exc
        return raw.strip()
    env_val = os.environ.get(env_name, "").strip()
    if env_val:
        return env_val.encode("utf-8")
    raise StageHubIndexError(
        f"operator key required via --operator-key-file or ${env_name}"
    )


def _dataset_id(organization: str, repository: str) -> str:
    return f"{organization.casefold()}/{repository.casefold()}"


def _repository_for_artifact(
    relative_path: str,
    *,
    role: str | None = None,
    repository_hint: str | None = None,
) -> str:
    """Map a package-relative path to a canonical Hub repository name."""
    path = relative_path.strip().replace("\\", "/").lstrip("./")
    if repository_hint:
        return str(repository_hint).casefold()
    if path.startswith("repos/"):
        rest = path[len("repos/") :]
        repo = rest.split("/", 1)[0].casefold()
        if repo in CANONICAL_REPOSITORY_NAMES:
            return repo
        raise StageHubIndexError(f"unknown repository in path: {path}")
    for prefix, repo in _INDEX_PREFIX_TO_REPO:
        if path.startswith(prefix) or path == prefix.rstrip("/"):
            return repo
    if role:
        mapped = ROLE_TO_REPOSITORY.get(str(role).casefold())
        if mapped:
            return mapped
    # Package support pins and layout bundle go to the corpus repository.
    return CORPUS_REPOSITORY


def resolve_package_dir(
    *,
    package_dir: str | Path | None = None,
    default_fixture: bool = False,
    stage_dir: str | Path | None = None,
    organization: str = ORGANIZATION,
) -> Path:
    """Return a staged hub index package directory (existing or freshly built)."""
    if package_dir is not None and default_fixture:
        raise StageHubIndexError(
            "provide either package_dir or default_fixture, not both"
        )
    if package_dir is None and not default_fixture:
        raise StageHubIndexError("provide --package-dir or --default-fixture")

    if package_dir is not None:
        root = Path(package_dir).expanduser().resolve()
        if not root.is_dir():
            raise StageHubIndexError(f"package_dir is not a directory: {root}")
        manifest_path = root / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise StageHubIndexError(f"missing package manifest: {manifest_path}")
        return root

    out = (
        Path(stage_dir).expanduser().resolve()
        if stage_dir is not None
        else Path(tempfile.mkdtemp(prefix="hub-index-stage-"))
    )
    if out.exists() and any(out.iterdir()):
        raise StageHubIndexError(
            f"stage_dir is not empty: {out} (refusing partial stage)"
        )
    try:
        package_patent_legal_hub_indexes(
            default_fixture=True,
            organization=organization,
            stage=True,
            output_dir=out,
        )
    except Exception as exc:
        raise StageHubIndexError(
            f"failed to materialize default hub index package: {exc}"
        ) from exc
    return out


def load_package_context(package_dir: str | Path) -> dict[str, Any]:
    """Load package manifest, inventory, and on-disk pins."""
    root = Path(package_dir).expanduser().resolve()
    if not root.is_dir():
        raise StageHubIndexError(f"package_dir is not a directory: {root}")

    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise StageHubIndexError(f"missing package manifest: {manifest_path}")

    try:
        manifest = load_package_manifest(manifest_path)
    except (HubIndexPackageError, ValueError, TypeError) as exc:
        raise StageHubIndexError(f"invalid package manifest: {exc}") from exc

    package_root_path = root / PACKAGE_ROOT_FILENAME
    package_root = (
        _load_json_object(package_root_path) if package_root_path.is_file() else {}
    )
    inventory_path = root / ARTIFACTS_INVENTORY_FILENAME
    artifacts_inventory = (
        _load_json_object(inventory_path) if inventory_path.is_file() else {}
    )
    package_receipt_path = root / RECEIPT_FILENAME
    package_receipt = (
        _load_json_object(package_receipt_path)
        if package_receipt_path.is_file()
        else {}
    )

    # Fail closed: three index families + corpus must be present on disk.
    present = set(manifest.index_families_present)
    missing = [name for name in INDEX_FAMILIES if name not in present]
    if missing:
        raise StageHubIndexError(
            "package missing required index families: " + ", ".join(missing)
        )
    for family in ("corpus", *INDEX_FAMILIES):
        if not (root / "indexes" / family).is_dir():
            raise StageHubIndexError(f"missing index tree: indexes/{family}")
    for repo in CANONICAL_REPOSITORY_NAMES:
        if not (root / "repos" / repo).is_dir():
            raise StageHubIndexError(f"missing repository layout tree: repos/{repo}")

    if package_root:
        pin = str(package_root.get("package_root_cid") or "")
        if pin and pin != manifest.package_root_cid:
            raise StageHubIndexError(
                "package-root.json package_root_cid does not match manifest"
            )

    return {
        "artifacts_inventory": artifacts_inventory,
        "manifest": manifest,
        "package_dir": root,
        "package_receipt": package_receipt,
        "package_root": package_root,
    }


def verify_admission_receipt(
    receipt: Mapping[str, Any] | Path | None,
    *,
    package_root_cid: str,
    require: bool = True,
) -> dict[str, Any] | None:
    """Validate an admission receipt binds the package root and was admitted.

    Returns the receipt dict when present and valid. When ``require`` is False
    and no receipt is supplied, returns None. Fail-closed on mismatches.
    """
    if receipt is None:
        if require:
            raise AdmissionRequiredError(
                "admission receipt required (--admission-receipt or "
                "hub-index-admission-receipt.json under package dir)"
            )
        return None

    if isinstance(receipt, (str, Path)):
        path = Path(receipt)
        if not path.is_file():
            if require:
                raise AdmissionRequiredError(f"admission receipt not found: {path}")
            return None
        payload = _load_json_object(path)
    else:
        payload = dict(receipt)

    bound = str(payload.get("package_root_cid") or "").strip()
    if not bound:
        raise AdmissionMismatchError(
            "admission receipt missing package_root_cid"
        )
    if bound != package_root_cid:
        raise AdmissionMismatchError(
            f"admission receipt package_root_cid {bound!r} does not match "
            f"package {package_root_cid!r}"
        )
    if payload.get("admitted") is not True:
        raise AdmissionRequiredError(
            "admission receipt is not admitted=true; refuse to stage "
            f"(reason_codes={payload.get('reason_codes')!r})"
        )
    # Soft schema pin — do not fail if older receipts omit schema string.
    schema = str(payload.get("schema_version") or payload.get("receipt_schema") or "")
    if schema and schema != ADMISSION_RECEIPT_SCHEMA:
        # Allow only the known admission schema; reject foreign receipts.
        if "admission" not in schema.casefold():
            raise AdmissionMismatchError(
                f"unexpected admission receipt schema: {schema!r}"
            )
    _reject_secrets_in_payload(payload, label="admission_receipt")
    return payload


def build_release_manifest_from_package(
    package_dir: str | Path,
    *,
    organization: str | None = None,
    include_package_support: bool = True,
) -> dict[str, Any]:
    """Project a staged hub index package into a publisher release manifest.

    Only files present on disk with matching digests are listed. Index family
    artifacts are bound to their canonical Hub repositories so stage plans
    enumerate corpus / BM25 / vector / graph projections separately.
    """
    ctx = load_package_context(package_dir)
    root: Path = ctx["package_dir"]
    manifest = ctx["manifest"]
    org = (organization or str(manifest.organization) or ORGANIZATION).casefold()

    descriptors: list[Mapping[str, Any]] = []
    inventory = ctx.get("artifacts_inventory") or {}
    inv_arts = inventory.get("artifacts") if isinstance(inventory, Mapping) else None
    if isinstance(inv_arts, list) and inv_arts:
        descriptors.extend(item for item in inv_arts if isinstance(item, Mapping))
    else:
        for item in getattr(manifest, "artifact_descriptors", ()) or ():
            if isinstance(item, Mapping):
                descriptors.append(item)
            elif hasattr(item, "descriptor"):
                descriptors.append(item.descriptor())

    if not descriptors:
        # Fallback: walk repos/ and indexes/ trees.
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(root).as_posix()
            if rel in {MANIFEST_FILENAME, PACKAGE_ROOT_FILENAME, RECEIPT_FILENAME}:
                continue
            if rel.startswith("repos/") or rel.startswith("indexes/"):
                size, digest = _file_sha256(path)
                descriptors.append(
                    {
                        "relative_path": rel,
                        "sha256": digest,
                        "size_bytes": size,
                        "content_cid": f"bafkrei{digest[:32]}",
                    }
                )

    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    family_counts: dict[str, int] = {
        "corpus": 0,
        "bm25": 0,
        "vectors": 0,
        "knowledge_graph": 0,
    }

    for index, item in enumerate(descriptors):
        rel = str(
            item.get("relative_path") or item.get("path") or item.get("local_path") or ""
        ).strip().replace("\\", "/")
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            raise StageHubIndexError(
                f"artifact[{index}] has unsafe relative_path: {rel!r}"
            )
        if rel in seen:
            continue
        path = root.joinpath(*Path(rel).parts)
        if not path.is_file() or path.is_symlink():
            raise StageHubIndexError(
                f"package artifact missing or not a regular file: {rel}"
            )
        size, digest = _file_sha256(path)
        expected = str(item.get("sha256") or "").strip().casefold()
        if expected and digest != expected:
            raise StageHubIndexError(
                f"artifact digest mismatch for {rel}: disk={digest} manifest={expected}"
            )
        expected_size = item.get("size_bytes")
        if expected_size is not None and int(expected_size) != size:
            raise StageHubIndexError(
                f"artifact size mismatch for {rel}: disk={size} manifest={expected_size}"
            )
        role = str(item.get("role") or item.get("family") or "").strip() or None
        repo = _repository_for_artifact(
            rel,
            role=role,
            repository_hint=(
                str(item["repository"]) if item.get("repository") else None
            ),
        )
        family = _ROLE_BY_REPO.get(repo, role or "corpus")
        if family in family_counts:
            family_counts[family] = family_counts[family] + 1
        content_cid = str(item.get("content_cid") or f"bafkrei{digest[:32]}")
        artifacts.append(
            {
                "relative_path": rel,
                "sha256": digest,
                "size_bytes": size,
                "content_cid": content_cid,
                "repository": repo,
                "role": family,
                "family": family,
                "dataset_id": _dataset_id(org, repo),
            }
        )
        seen.add(rel)

    if include_package_support:
        for name in _PACKAGE_SUPPORT_FILES:
            if name in seen:
                continue
            path = root / name
            if not path.is_file():
                continue
            size, digest = _file_sha256(path)
            artifacts.append(
                {
                    "relative_path": name,
                    "sha256": digest,
                    "size_bytes": size,
                    "content_cid": f"bafkrei{digest[:32]}",
                    "repository": CORPUS_REPOSITORY,
                    "role": "corpus",
                    "family": "corpus",
                    "dataset_id": _dataset_id(org, CORPUS_REPOSITORY),
                }
            )
            seen.add(name)
            family_counts["corpus"] = family_counts["corpus"] + 1

    if not artifacts:
        raise StageHubIndexError("no publishable artifacts found in package")

    # Every projection family must contribute at least one artifact.
    for family in ("corpus", *INDEX_FAMILIES):
        if family_counts.get(family, 0) < 1:
            raise StageHubIndexError(
                f"stage plan missing artifacts for projection family {family!r}"
            )

    package_root_cid = str(manifest.package_root_cid)
    version_tag = str(manifest.version_tag)
    repositories = [
        {
            "dataset_id": _dataset_id(org, repo),
            "repository": repo,
            "role": _ROLE_BY_REPO[repo],
        }
        for repo in CANONICAL_REPOSITORY_NAMES
    ]

    release_manifest: dict[str, Any] = {
        "artifacts": sorted(artifacts, key=lambda a: a["relative_path"]),
        "bm25_root_cid": str(manifest.bm25_root_cid),
        "corpus_root_cid": str(manifest.corpus_root_cid),
        "dry_run": True,
        "graph_root_cid": str(manifest.graph_root_cid),
        "index_families_present": list(INDEX_FAMILIES),
        "organization": org,
        "package_digest_sha256": str(manifest.package_digest_sha256),
        "package_root_cid": package_root_cid,
        "partition": "public",
        "program_id": PROGRAM_ID,
        "projection_artifact_counts": dict(family_counts),
        "release_id": f"hub-index-{version_tag}-{package_root_cid[:16]}",
        "release_root_cid": package_root_cid,
        "repositories": repositories,
        "schema_version": "patent-legal-hub-index-release/v1",
        "source_package_schema": str(manifest.schema_version),
        "task_id": TASK_ID,
        "upload_path": None,
        "uses_hf_api_upload_file": False,
        "vector_root_cid": str(manifest.vector_root_cid),
        "version_tag": version_tag,
    }
    reject_credentials_in_payload(release_manifest, label="release_manifest")
    return release_manifest


def write_release_manifest(
    package_dir: str | Path,
    *,
    organization: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Build and optionally write ``release-manifest.json`` under the package."""
    root = Path(package_dir).expanduser().resolve()
    release_manifest = build_release_manifest_from_package(
        root, organization=organization
    )
    out = path or (root / RELEASE_MANIFEST_FILENAME)
    text = json.dumps(release_manifest, indent=2, sort_keys=True, ensure_ascii=False)
    # Canonical compact form for digests matches publisher helpers when needed;
    # on-disk pretty print is operator-friendly and planner re-hashes local files.
    out.write_text(text + "\n", encoding="utf-8")
    return release_manifest


# ---------------------------------------------------------------------------
# Workflow modes
# ---------------------------------------------------------------------------


def run_dry_run(
    *,
    package_dir: Path,
    organization: str,
    base_revisions: Mapping[str, str],
    branch_name: str | None,
    target_revision: str,
    version_tag: str | None,
    release_id: str | None,
    admission_receipt: Mapping[str, Any] | Path | None = None,
    require_admission: bool = False,
    write_manifest: bool = True,
) -> dict[str, Any]:
    """Dry-run staging: package integrity + release plan, no Hub contact."""
    ctx = load_package_context(package_dir)
    root: Path = ctx["package_dir"]
    pkg_manifest = ctx["manifest"]
    package_root_cid = str(pkg_manifest.package_root_cid)

    admission = verify_admission_receipt(
        admission_receipt,
        package_root_cid=package_root_cid,
        require=require_admission,
    )

    release_manifest = build_release_manifest_from_package(
        root, organization=organization
    )
    if write_manifest:
        (root / RELEASE_MANIFEST_FILENAME).write_text(
            json.dumps(release_manifest, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

    plan = plan_stage_from_local_root(
        local_root=root,
        manifest=release_manifest,
        organization=organization,
        version_tag=version_tag or str(pkg_manifest.version_tag),
        base_revisions=base_revisions,
        branch_name=branch_name,
        target_revision=target_revision,
        release_id=release_id or str(release_manifest.get("release_id")),
    )
    if plan.branch_name.casefold() in PROHIBITED_DEFAULT_BRANCHES:
        raise StageHubIndexError(
            f"stage branch must not target a default branch: {plan.branch_name}"
        )

    plan_payload = plan.to_dict()
    repo_ids = sorted(set(plan.dataset_ids()))
    payload: dict[str, Any] = {
        **plan_payload,
        "status": "dry_run_only",
        "receipt_schema": DRY_RUN_RECEIPT_SCHEMA,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "config_id": CONFIG_ID,
        "code_version": CODE_VERSION,
        "live_network": False,
        "tokens_used": False,
        "main_published": False,
        "pointers_moved": False,
        "remote_write_contacted": False,
        "remote_default_branches_mutated": False,
        "uses_hf_api_upload_file": False,
        "authenticated_upload": False,
        "dry_run": True,
        "package_root_cid": package_root_cid,
        "package_digest_sha256": str(pkg_manifest.package_digest_sha256),
        "corpus_root_cid": str(pkg_manifest.corpus_root_cid),
        "bm25_root_cid": str(pkg_manifest.bm25_root_cid),
        "vector_root_cid": str(pkg_manifest.vector_root_cid),
        "graph_root_cid": str(pkg_manifest.graph_root_cid),
        "index_families_present": list(INDEX_FAMILIES),
        "projection_artifact_counts": dict(
            release_manifest.get("projection_artifact_counts") or {}
        ),
        "repository_ids": repo_ids,
        "human_approval_required": True,
        "admission_bound": admission is not None,
        "admission": (
            {
                "admitted": True,
                "package_root_cid": package_root_cid,
                "schema_version": str(
                    admission.get("schema_version")
                    or admission.get("receipt_schema")
                    or ADMISSION_RECEIPT_SCHEMA
                ),
                "task_id": admission.get("task_id"),
            }
            if admission
            else None
        ),
        "next_operator_actions": [
            "Review plan_digest and staged_diff_digest",
            "Confirm package_root_cid and projection artifact counts",
            "Only then run --mode stage with an operator-held Hub token "
            "(or --fake-service for offline drills)",
            "Never auto-promote main without --mode sign + --mode promote",
        ],
    }
    reject_credentials_in_payload(payload, label="dry_run_receipt")
    _reject_secrets_in_payload(payload, label="dry_run_receipt")
    return payload


def _build_plan(
    *,
    package_dir: Path,
    organization: str,
    base_revisions: Mapping[str, str],
    branch_name: str | None,
    target_revision: str,
    version_tag: str | None,
    release_id: str | None,
    write_manifest: bool = True,
) -> tuple[Any, dict[str, Any], Path]:
    ctx = load_package_context(package_dir)
    root: Path = ctx["package_dir"]
    pkg_manifest = ctx["manifest"]
    release_manifest = build_release_manifest_from_package(
        root, organization=organization
    )
    if write_manifest:
        (root / RELEASE_MANIFEST_FILENAME).write_text(
            json.dumps(release_manifest, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
    plan = plan_stage_from_local_root(
        local_root=root,
        manifest=release_manifest,
        organization=organization,
        version_tag=version_tag or str(pkg_manifest.version_tag),
        base_revisions=base_revisions,
        branch_name=branch_name,
        target_revision=target_revision,
        release_id=release_id or str(release_manifest.get("release_id")),
    )
    if plan.branch_name.casefold() in PROHIBITED_DEFAULT_BRANCHES:
        raise StageHubIndexError(
            f"stage branch must not target a default branch: {plan.branch_name}"
        )
    return plan, release_manifest, root


def run_stage(
    *,
    package_dir: Path,
    organization: str,
    base_revisions: Mapping[str, str],
    branch_name: str | None,
    target_revision: str,
    version_tag: str | None,
    release_id: str | None,
    fake_service: bool,
    token_env: str,
    create_pr: bool,
    admission_receipt: Mapping[str, Any] | Path | None = None,
    require_admission: bool = False,
) -> dict[str, Any]:
    """Stage add-only Hub branches/PRs for hub index package artifacts."""
    ctx = load_package_context(package_dir)
    package_root_cid = str(ctx["manifest"].package_root_cid)
    verify_admission_receipt(
        admission_receipt,
        package_root_cid=package_root_cid,
        require=require_admission,
    )

    plan, release_manifest, root = _build_plan(
        package_dir=package_dir,
        organization=organization,
        base_revisions=base_revisions,
        branch_name=branch_name,
        target_revision=target_revision,
        version_tag=version_tag,
        release_id=release_id,
    )

    if fake_service:
        api = FakeHubService(base_revisions=base_revisions, require_auth=True)
        token = api.auth_token
    else:
        env_token = os.environ.get(token_env) or None
        token = resolve_hub_token(token=env_token, allow_missing=False)
        # Live clients are never constructed here — operators inject via an
        # operator-controlled process. Fail closed without --fake-service.
        raise StageHubIndexError(
            "live Hub stage requires an injected API client; use --fake-service "
            "for offline verification, or call PatentHFPublisherV2 from an "
            "operator-controlled process with an authenticated HfApi"
        )

    publisher = PatentHFPublisherV2(
        api=api, token=token, organization=organization
    )
    staged = publisher.stage_pull_request(
        plan, local_root=root, create_pr=create_pr
    )
    payload = staged.to_dict()
    payload["plan"] = plan.to_dict()
    payload["receipt_schema"] = STAGE_RECEIPT_SCHEMA
    payload["task_id"] = TASK_ID
    payload["goal_id"] = GOAL_ID
    payload["program_id"] = PROGRAM_ID
    payload["package_root_cid"] = package_root_cid
    payload["package_digest_sha256"] = str(ctx["manifest"].package_digest_sha256)
    payload["corpus_root_cid"] = str(ctx["manifest"].corpus_root_cid)
    payload["bm25_root_cid"] = str(ctx["manifest"].bm25_root_cid)
    payload["vector_root_cid"] = str(ctx["manifest"].vector_root_cid)
    payload["graph_root_cid"] = str(ctx["manifest"].graph_root_cid)
    payload["index_families_present"] = list(INDEX_FAMILIES)
    payload["projection_artifact_counts"] = dict(
        release_manifest.get("projection_artifact_counts") or {}
    )
    payload["live_network"] = not fake_service
    payload["tokens_used"] = False
    payload["fake_service"] = fake_service
    payload["main_published"] = False
    payload["pointers_moved"] = False
    payload["human_approval_required"] = True
    reject_credentials_in_payload(payload, label="stage_receipt")
    _reject_secrets_in_payload(payload, label="stage_receipt")
    return payload


def run_sign(
    *,
    package_dir: Path,
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
    plan, _release_manifest, _root = _build_plan(
        package_dir=package_dir,
        organization=organization,
        base_revisions=base_revisions,
        branch_name=branch_name,
        target_revision=target_revision,
        version_tag=version_tag,
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
    payload["task_id"] = TASK_ID
    payload["goal_id"] = GOAL_ID
    payload["package_root_cid"] = plan.release_root_cid
    reject_credentials_in_payload(payload, label="approval_out")
    _reject_secrets_in_payload(payload, label="approval_out")
    return payload


def run_promote(
    *,
    package_dir: Path,
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
    plan, release_manifest, root = _build_plan(
        package_dir=package_dir,
        organization=organization,
        base_revisions=base_revisions,
        branch_name=branch_name,
        target_revision=target_revision,
        version_tag=version_tag,
        release_id=release_id,
    )
    approval_payload = _load_json_object(approval_file)
    staged_payload = _load_json_object(staged_receipt_file)

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
        api = FakeHubService(base_revisions=base_revisions, require_auth=True)
        token = api.auth_token
        publisher = PatentHFPublisherV2(
            api=api, token=token, organization=organization
        )
        restaged = publisher.stage_pull_request(plan, local_root=root)
        if restaged.plan_digest != staged.plan_digest:
            raise StageHubIndexError(
                "restaged plan_digest diverged from staged receipt"
            )
        promotion = publisher.promote_approved(
            plan,
            staged=restaged,
            approval=approval_payload,
            operator_key=operator_key,
            local_root=root,
        )
    else:
        # token resolved only to prove operator intent; still fail closed.
        _ = resolve_hub_token(
            token=os.environ.get(token_env) or None, allow_missing=False
        )
        raise StageHubIndexError(
            "live Hub promote requires an injected API client; use --fake-service "
            "for offline verification"
        )

    payload = promotion.to_dict()
    payload["task_id"] = TASK_ID
    payload["goal_id"] = GOAL_ID
    payload["program_id"] = PROGRAM_ID
    payload["package_root_cid"] = plan.release_root_cid
    payload["index_families_present"] = list(INDEX_FAMILIES)
    payload["projection_artifact_counts"] = dict(
        release_manifest.get("projection_artifact_counts") or {}
    )
    payload["live_network"] = not fake_service
    payload["tokens_used"] = False
    payload["fake_service"] = fake_service
    payload["pointers_moved"] = False
    reject_credentials_in_payload(payload, label="promote_receipt")
    _reject_secrets_in_payload(payload, label="promote_receipt")
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stage authenticated Hub PR for corpus/BM25/vector/graph hub index "
            f"packages ({TASK_ID}). Default mode is dry-run (no Hub contact)."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("dry-run", "stage", "sign", "promote"),
        default="dry-run",
        help="Workflow mode (default: dry-run; no Hub contact)",
    )
    src = parser.add_mutually_exclusive_group()
    src.add_argument(
        "--package-dir",
        type=Path,
        help="Staged hub index package directory (PATLAW-174 output)",
    )
    src.add_argument(
        "--default-fixture",
        action="store_true",
        help="Materialize the built-in multi-family package fixture then stage",
    )
    parser.add_argument(
        "--stage-dir",
        type=Path,
        help="Staging directory for --default-fixture",
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
        help="Override version tag from the package manifest",
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
        "--no-create-pr",
        action="store_true",
        help="Stage branches/commits without opening pull requests",
    )
    parser.add_argument(
        "--admission-receipt",
        type=Path,
        help=(
            "PATLAW-175 admission receipt JSON binding package_root_cid "
            f"(default: <package-dir>/{ADMISSION_RECEIPT_FILENAME} when present)"
        ),
    )
    parser.add_argument(
        "--require-admission",
        action="store_true",
        help="Fail closed unless a valid admitted receipt binds the package root",
    )
    parser.add_argument(
        "--list-index-families",
        action="store_true",
        help="Print required index family names and exit",
    )
    parser.add_argument(
        "--write-release-manifest-only",
        action="store_true",
        help="Write release-manifest.json from the package and exit",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.list_index_families:
        for name in INDEX_FAMILIES:
            print(name)
        return 0

    try:
        package_dir = resolve_package_dir(
            package_dir=args.package_dir,
            default_fixture=bool(args.default_fixture),
            stage_dir=args.stage_dir,
            organization=args.organization,
        )

        if args.write_release_manifest_only:
            release_manifest = write_release_manifest(
                package_dir, organization=args.organization
            )
            _write_json(
                args.receipt_out,
                {
                    "status": "release_manifest_written",
                    "package_dir": str(package_dir),
                    "package_root_cid": release_manifest.get("package_root_cid"),
                    "artifact_count": len(release_manifest.get("artifacts") or ()),
                    "projection_artifact_counts": release_manifest.get(
                        "projection_artifact_counts"
                    ),
                    "task_id": TASK_ID,
                },
            )
            return 0

        # Resolve optional admission receipt path (explicit or co-located).
        admission_path: Path | None = args.admission_receipt
        if admission_path is None:
            colocated = package_dir / ADMISSION_RECEIPT_FILENAME
            if colocated.is_file():
                admission_path = colocated

        bases_needed = args.mode in {"dry-run", "stage", "sign", "promote"}
        bases: dict[str, str] = {}
        if bases_needed:
            if args.base_revisions is None and args.base_revisions_file is None:
                # Allow tests/operators to omit bases only when using
                # --default-fixture dry-run with implicit zero SHAs via
                # --base-revisions-file; otherwise fail closed.
                raise StageHubIndexError(
                    "base revisions are required "
                    "(--base-revisions or --base-revisions-file)"
                )
            bases = _load_base_revisions(args.base_revisions, args.base_revisions_file)

        if args.mode == "dry-run":
            payload = run_dry_run(
                package_dir=package_dir,
                organization=args.organization,
                base_revisions=bases,
                branch_name=args.branch_name,
                target_revision=args.target_revision,
                version_tag=args.version_tag,
                release_id=args.release_id,
                admission_receipt=admission_path,
                require_admission=bool(args.require_admission),
            )
            _write_json(args.receipt_out, payload)
            return 0

        if args.mode == "stage":
            payload = run_stage(
                package_dir=package_dir,
                organization=args.organization,
                base_revisions=bases,
                branch_name=args.branch_name,
                target_revision=args.target_revision,
                version_tag=args.version_tag,
                release_id=args.release_id,
                fake_service=bool(args.fake_service),
                token_env=args.token_env,
                create_pr=not args.no_create_pr,
                admission_receipt=admission_path,
                require_admission=bool(args.require_admission),
            )
            _write_json(args.receipt_out, payload)
            return 0

        if args.mode == "sign":
            key = _load_operator_key(args.operator_key_file)
            payload = run_sign(
                package_dir=package_dir,
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
            key = _load_operator_key(args.operator_key_file)
            payload = run_promote(
                package_dir=package_dir,
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
        StageHubIndexError,
        AdmissionRequiredError,
        AdmissionMismatchError,
        PatentHFPublisherV2Error,
        ApprovalError,
        ArtifactChangedError,
        AuthError,
        BaseRevisionError,
        ConflictError,
        PartialUploadError,
        HubIndexPackageError,
    ) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
