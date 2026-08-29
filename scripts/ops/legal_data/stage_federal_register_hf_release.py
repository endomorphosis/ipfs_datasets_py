#!/usr/bin/env python3
"""Upload the immutable Federal Register candidate to an explicit staging target (LCR-064).

Default mode is **offline dry-run** (credential-free, no Hub network contact):

1. Load the sealed Federal Register candidate and bind its manifest digest.
2. Invoke the LCR-074 publication gate for the ``federal_staging`` phase
   **before** any Hub mutation callback can run.
3. Plan **add-only** uploads to an explicitly named staging branch.
4. Reject production targets (``main`` / ``master`` / public production pin).
5. Emit a redacted staging receipt — no tokens, no absolute local paths.

Operator workflow after a successful dry-run receipt:

1. ``--dry-run`` / ``--check-receipt`` — deterministic plan + receipt (default)
2. Review ``plan_digest``, ``manifest_digest``, target, and staging branch
3. Only then consider remote mutation through
   :func:`execute_canonical_staging_release`, with two distinct bounded
   approvals. The standalone CLI fails closed because it cannot reconstruct
   reviewed production artifact bytes from a receipt.

This script never:

* uploads to ``main`` / ``master``;
* deletes, force-pushes, or changes repository visibility;
* embeds or logs Hub tokens;
* mutates anything without opt-in authorization;
* treats credentials as CLI flags (environment-only);
* proceeds to a Hub write unless LCR-074 authorized ``federal_staging``.

Validation gate (no network)::

    python scripts/ops/legal_data/stage_federal_register_hf_release.py --check-receipt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (  # noqa: E402
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_OBSERVATION_CUTOFF,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
    canonical_json_dumps,
    digest_mapping,
    required_semantic_families,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (  # noqa: E402
    FEDERAL_DATASET_REPO_ID,
    PublicationGateDecision,
    PublicationGateDeniedError,
    PublicationGateError,
    PublicationPhase,
    SECRET_ENV_NAMES as GATE_SECRET_ENV_NAMES,
    example_authorized_request,
    reject_credentials_in_payload as gate_reject_credentials,
    require_publication_gate,
)
from ipfs_datasets_py.processors.legal_data.federal_register_hf_release import (  # noqa: E402
    MANIFEST_FILENAME,
    advertised_viewer_configs,
    assert_configs_schema_coherent,
    build_federal_candidate_evidence,
    build_federal_register_hf_release,
    fixture_family_rows,
    fixture_legacy_files,
    validate_federal_register_hf_release,
)
from ipfs_datasets_py.huggingface.publisher import (  # noqa: E402
    CanonicalLegalCorporaMutationReceipt,
    HuggingFaceReleasePublisher,
    PublicationApproval,
    PublicationPlan,
)
from ipfs_datasets_py.processors.legal_data.federal_register_publication_package import (  # noqa: E402
    FederalRegisterCanonicalControlBundle,
    FederalRegisterPublicationPackage,
    federal_register_publication_profile,
    materialize_federal_register_staging_controls,
    plan_federal_register_publication_dry_run,
    prepare_federal_register_publication_package,
)


# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "LCR-064"
GOAL_ID: Final = "LCR-G130"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "stage_federal_register_hf_release.py"
CODE_VERSION: Final = "1"
GATE_TASK_ID: Final = "LCR-074"
PUBLICATION_PHASE: Final = PublicationPhase.FEDERAL_STAGING.value
AUTHORIZED_OPERATION: Final = "additive_staging_upload"

STAGE_PLAN_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-federal-stage-plan@1"
STAGE_RECEIPT_SCHEMA: Final = (
    "ipfs_datasets_py/legal-corpora-reindex-federal-stage-receipt@1"
)

DEFAULT_DATASET_REPO: Final = FEDERAL_DATASET_REPO_ID or DEFAULT_DATASET_REPO_ID
PRODUCTION_REVISION: Final = PREVIOUS_PUBLIC_PIN
DEFAULT_STAGING_BRANCH: Final = "stage/federal-register-ir-graphrag-v2"
DEFAULT_BASE_REVISION: Final = PRODUCTION_REVISION
DEFAULT_PACKAGE_VERSION: Final = "2"
DEFAULT_CANDIDATE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_candidate.json"
)
DEFAULT_INVENTORY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_inventory.json"
)

FORBIDDEN_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "delete",
        "delete_file",
        "delete_folder",
        "force",
        "force_push",
        "force-push",
        "overwrite_history",
        "visibility_change",
        "change_visibility",
        "make_private",
        "make_unlisted",
        "set_private",
        "set_unlisted",
        "rotate_credentials",
        "direct_main_upload",
        "promote_production",
        "history_rewrite",
        "super_squash_history",
        "overwrite_legacy",
    }
)
ALLOWED_OPERATIONS: Final[frozenset[str]] = frozenset({"add_only_upload"})

PROHIBITED_STAGING_BRANCHES: Final[frozenset[str]] = frozenset(
    {
        "main",
        "master",
        "refs/heads/main",
        "refs/heads/master",
        "production",
        "prod",
        "live",
    }
)

SECRET_ENV_NAMES: Final[tuple[str, ...]] = tuple(
    dict.fromkeys(
        (
            *GATE_SECRET_ENV_NAMES,
            "FEDERAL_REGISTER_STAGING_AUTHORIZATION",
            "FEDERAL_REGISTER_HF_TOKEN",
            "HF_TOKEN",
            "HUGGING_FACE_HUB_TOKEN",
            "HUGGINGFACE_HUB_TOKEN",
            "HUGGINGFACE_TOKEN",
            "HUGGINGFACEHUB_API_TOKEN",
        )
    )
)
AUTHORIZATION_ENV: Final = "FEDERAL_REGISTER_STAGING_AUTHORIZATION"

_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"staging_authorization)s?$",
    re.IGNORECASE,
)
_DATASET_ID_RE = re.compile(r"^[A-Za-z0-9](?:[-\w.]{0,38}[A-Za-z0-9])?/[A-Za-z0-9._-]+$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MUTABLE_REFS: Final = frozenset(
    {
        "main",
        "master",
        "latest",
        "head",
        "dev",
        "develop",
        "production",
        "prod",
        "live",
        "staging",
        "canary",
        "default",
        "current",
    }
)
_ABSOLUTE_PATH_MARKERS: Final = (
    "/home/",
    "/tmp/",
    "/var/",
    "/users/",
    "c:\\",
    "c:/",
    "file://",
)


class StageFederalRegisterError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class StageAuthorizationError(StageFederalRegisterError):
    """Raised when mutation is attempted without opt-in authorization."""


class StageSafetyError(StageFederalRegisterError):
    """Raised when a plan would delete, force-push, or change visibility."""


class StageProductionTargetError(StageFederalRegisterError):
    """Raised when a production target is requested without a publication seal."""


class StageGateError(StageFederalRegisterError):
    """Raised when the LCR-074 federal_staging gate refuses mutation."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_candidate_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_CANDIDATE_RELPATH).resolve()


def default_candidate_report_path(repo_root: Path | str | None = None) -> Path:
    """Compatibility name for the canonical candidate evidence path."""

    return default_candidate_path(repo_root)


def default_inventory_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_INVENTORY_RELPATH).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise StageFederalRegisterError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StageFederalRegisterError(f"cannot read JSON {target}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise StageFederalRegisterError(f"JSON root must be an object: {target}")
    return dict(payload)


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


# ---------------------------------------------------------------------------
# Credential / safety guards
# ---------------------------------------------------------------------------


def reject_credentials_in_payload(value: Any, *, label: str = "payload") -> None:
    """Fail closed when tokens or secret-like values appear in public surfaces."""

    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _TOKEN_KEY_RE.search(key_text) and not isinstance(child, bool):
                    offenders.append(child_path)
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            lowered = item.casefold()
            if lowered.startswith("hf_") and len(item) >= 20:
                offenders.append(path or label)
            for env_name in SECRET_ENV_NAMES:
                env_val = os.environ.get(env_name)
                if env_val and env_val in item:
                    offenders.append(path or label)
            for marker in _ABSOLUTE_PATH_MARKERS:
                if marker in lowered:
                    offenders.append(path or label)

    visit(value, label)
    if offenders:
        raise StageSafetyError(
            f"credential-like or absolute-path material in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )
    gate_reject_credentials(value, label=label)


def reject_secrets_in_argv(argv: Sequence[str]) -> None:
    """Refuse secrets passed on the command line (credentials are env-only)."""

    joined = " ".join(str(a) for a in argv)
    lowered = joined.casefold()
    needles = (
        "hf_token=",
        "authorization:",
        "bearer ",
        "access_token=",
        "api_token=",
        "federal_register_staging_authorization=",
        "federal_register_hf_token=",
    )
    for needle in needles:
        if needle in lowered:
            raise StageSafetyError(
                "refusing to accept secrets on the command line; "
                "credentials remain environment-only"
            )
    for env_name in SECRET_ENV_NAMES:
        env_val = os.environ.get(env_name)
        if env_val and env_val in joined:
            raise StageSafetyError(
                f"refusing to accept ${env_name} value on the command line"
            )


def require_immutable_revision(value: Any, *, name: str = "revision") -> str:
    if not isinstance(value, str) or not value.strip():
        raise StageFederalRegisterError(
            f"{name} must be an explicit immutable 40-hex revision"
        )
    text = value.strip().casefold()
    if text in _MUTABLE_REFS or text.startswith("refs/"):
        raise StageFederalRegisterError(
            f"{name} must never be a mutable ref ({value!r}); pin a 40-hex SHA"
        )
    if not _GIT_SHA_RE.fullmatch(text):
        raise StageFederalRegisterError(
            f"{name} must be a 40-character lowercase hex commit SHA, got {value!r}"
        )
    return text


def _normalize_dataset_id(value: str, *, label: str = "target_repo") -> str:
    text = str(value or "").strip()
    if not _DATASET_ID_RE.fullmatch(text):
        raise StageFederalRegisterError(f"{label} must be owner/name, got {value!r}")
    if text != DEFAULT_DATASET_REPO:
        raise StageProductionTargetError(
            f"{label} must be the authorized Federal Register dataset "
            f"{DEFAULT_DATASET_REPO!r}, got {text!r}"
        )
    return text


def _normalize_branch(value: str, *, label: str = "staging_branch") -> str:
    text = str(value or "").strip()
    if not text or not _BRANCH_RE.fullmatch(text):
        raise StageFederalRegisterError(f"{label} is invalid: {value!r}")
    if ".." in text or text.startswith("/") or text.endswith("/"):
        raise StageFederalRegisterError(f"{label} is unsafe: {value!r}")
    return text


def _assert_operations_add_only(operations: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in operations:
        op = str(raw or "").strip().casefold().replace("-", "_")
        if not op:
            continue
        if op in FORBIDDEN_OPERATIONS or op.startswith("delete") or "force" in op:
            raise StageSafetyError(
                f"operation is forbidden for Federal Register staging: {raw!r}"
            )
        if "visibility" in op or op in {"private", "unlisted"}:
            raise StageSafetyError(
                f"visibility changes are impossible via staging: {raw!r}"
            )
        if op not in ALLOWED_OPERATIONS:
            raise StageSafetyError(
                f"only add-only uploads are permitted; got operation {raw!r}"
            )
        normalized.append(op)
    if not normalized:
        raise StageSafetyError("stage plan requires at least one allowed operation")
    return tuple(sorted(set(normalized)))


def assert_non_production_staging_branch(
    staging_branch: str,
    *,
    production_revision: str = PRODUCTION_REVISION,
    publication_seal: str | None = None,
) -> str:
    """Reject production targets unless a separate publication seal is present."""

    branch = _normalize_branch(staging_branch, label="staging_branch")
    lowered = branch.casefold()
    if lowered in PROHIBITED_STAGING_BRANCHES or lowered.startswith("refs/heads/main"):
        if not publication_seal:
            raise StageProductionTargetError(
                f"staging branch targets production without a publication seal: "
                f"{branch!r}"
            )
    if branch == production_revision or lowered == production_revision.casefold():
        if not publication_seal:
            raise StageProductionTargetError(
                "staging branch must not equal the public production revision "
                "without a separate publication seal"
            )
    return branch


def assert_mutation_authorized(
    *,
    authorize_mutation: bool,
    authorization_env: str = AUTHORIZATION_ENV,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Require explicit opt-in flag + non-empty environment authorization."""

    if not authorize_mutation:
        raise StageAuthorizationError(
            "mutation refused: pass --authorize-mutation and set "
            f"${authorization_env} (credentials remain environment-only)"
        )
    env = environ if environ is not None else os.environ
    token = str(env.get(authorization_env, "") or "").strip()
    if not token:
        raise StageAuthorizationError(
            f"mutation refused: ${authorization_env} is empty or unset"
        )


# ---------------------------------------------------------------------------
# Fake Hub (offline add-only staging transport)
# ---------------------------------------------------------------------------


class FakeFederalRegisterHub:
    """In-memory add-only Hub used for dry-run, tests, and sealed canaries.

    The transport never contacts the network. Uploads are add-only: an
    existing path with a different digest is refused rather than overwritten
    unless the caller is resuming an identical blob.
    """

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.operations: list[dict[str, Any]] = []
        self.revision: str | None = None
        self.mutated = False

    def upload_files(
        self,
        files: Mapping[str, bytes],
        *,
        repo_id: str,
        branch: str,
        base_revision: str,
        batch_size: int = 32,
    ) -> dict[str, Any]:
        _normalize_dataset_id(repo_id)
        assert_non_production_staging_branch(branch)
        require_immutable_revision(base_revision, name="base_revision")
        if batch_size < 1:
            raise StageFederalRegisterError("batch_size must be >= 1")

        uploaded: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []
        items = sorted(files.items(), key=lambda item: item[0])
        for offset in range(0, len(items), batch_size):
            batch = items[offset : offset + batch_size]
            for relative_path, content in batch:
                path = str(relative_path)
                if path.startswith("/") or ".." in Path(path).parts:
                    raise StageSafetyError(f"unsafe staging path: {path!r}")
                digest = hashlib.sha256(content).hexdigest()
                existing = self.files.get(path)
                if existing is not None:
                    existing_digest = hashlib.sha256(existing).hexdigest()
                    if existing_digest != digest:
                        raise StageSafetyError(
                            f"add-only resume refused: {path} digest drifted"
                        )
                    skipped.append({"relative_path": path, "sha256": digest})
                    self.operations.append(
                        {
                            "operation": "add_only_upload",
                            "relative_path": path,
                            "sha256": digest,
                            "status": "skipped_identical",
                        }
                    )
                    continue
                self.files[path] = content
                uploaded.append({"relative_path": path, "sha256": digest})
                self.operations.append(
                    {
                        "operation": "add_only_upload",
                        "relative_path": path,
                        "sha256": digest,
                        "status": "uploaded",
                    }
                )
        self.mutated = True
        binding = {
            "base_revision": base_revision,
            "branch": branch,
            "files": {
                path: hashlib.sha256(blob).hexdigest()
                for path, blob in sorted(self.files.items())
            },
            "repo_id": repo_id,
        }
        revision = hashlib.sha1(
            canonical_json_dumps(binding).encode("utf-8")
        ).hexdigest()
        self.revision = revision
        unexpected = [
            op
            for op in self.operations
            if str(op.get("operation")) not in ALLOWED_OPERATIONS
        ]
        if unexpected:
            raise StageSafetyError(
                "unexpected Hub operations scheduled: "
                + ", ".join(sorted({str(op.get("operation")) for op in unexpected}))
            )
        return {
            "base_revision": base_revision,
            "operations": list(self.operations),
            "repo_id": repo_id,
            "skipped": skipped,
            "staging_branch": branch,
            "staging_revision": revision,
            "unexpected_operations": [],
            "uploaded": uploaded,
        }

    def redownload(self) -> dict[str, bytes]:
        return {path: bytes(blob) for path, blob in sorted(self.files.items())}


# ---------------------------------------------------------------------------
# Candidate + plan construction
# ---------------------------------------------------------------------------


def load_candidate_report(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_candidate_path(repo_root)
    )
    if not target.is_file():
        target = default_candidate_report_path(repo_root)
    report = load_json_mapping(target)
    candidate = report.get("candidate")
    if isinstance(candidate, Mapping):
        for key in (
            "manifest_digest",
            "observation_cutoff",
            "release_point",
            "release_profile",
            "release_root_cid",
        ):
            if key not in report and candidate.get(key) is not None:
                report[key] = candidate[key]
        report.setdefault("dataset_repo_id", candidate.get("dataset_id"))
    closure = report.get("semantic_family_closure")
    if isinstance(closure, Mapping):
        report.setdefault("required_semantic_families", closure.get("required"))
    digest = str(report.get("manifest_digest") or "").strip().casefold()
    if not _SHA256_RE.fullmatch(digest):
        raise StageFederalRegisterError(
            "candidate report is missing a 64-hex manifest_digest"
        )
    if str(report.get("dataset_repo_id") or "") != DEFAULT_DATASET_REPO:
        raise StageFederalRegisterError(
            "candidate dataset_repo_id must be "
            f"{DEFAULT_DATASET_REPO!r}"
        )
    return report


def load_cutoff_inventory(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_inventory_path(repo_root)
    )
    inventory = load_json_mapping(target)
    cutoff = str(
        inventory.get("observation_cutoff")
        or (inventory.get("acceptance") or {}).get("observation_cutoff")
        or ""
    ).strip()
    if cutoff != DEFAULT_OBSERVATION_CUTOFF:
        raise StageFederalRegisterError(
            "inventory observation_cutoff must equal "
            f"{DEFAULT_OBSERVATION_CUTOFF!r}, got {cutoff!r}"
        )
    return inventory


def build_fixture_release(*, repo_root: Path | str | None = None):
    """Build the deterministic offline Federal Register release candidate."""

    del repo_root  # fixture inputs are package-owned and repository-relative
    release = build_federal_register_hf_release(
        fixture_family_rows(),
        legacy_files=fixture_legacy_files(),
        dry_run=True,
    )
    validate_federal_register_hf_release(release)
    return release


def build_canonical_staging_plan(
    *,
    release: Any,
    output_root: Path | str,
    audited_parent_commit: str = DEFAULT_BASE_REVISION,
    staging_branch: str = DEFAULT_STAGING_BRANCH,
    candidate: Mapping[str, Any] | None = None,
    api: Any | None = None,
) -> tuple[
    FederalRegisterPublicationPackage,
    HuggingFaceReleasePublisher,
    PublicationPlan,
]:
    """Build the package-backed Federal staging plan without network I/O."""

    parent = require_immutable_revision(
        audited_parent_commit,
        name="audited_parent_commit",
    )
    branch = assert_non_production_staging_branch(staging_branch)
    package = prepare_federal_register_publication_package(
        release,
        output_root=output_root,
    )
    if candidate is not None:
        nested = candidate.get("candidate")
        candidate_release_digest = str(
            (nested.get("manifest_digest") if isinstance(nested, Mapping) else None)
            or candidate.get("manifest_digest")
            or ""
        ).strip().casefold()
        if candidate_release_digest != package.manifest_digest:
            raise StageFederalRegisterError(
                "Federal candidate and canonical publication package differ"
            )
    plan = plan_federal_register_publication_dry_run(
        package,
        audited_parent_commit=parent,
        target_revision=branch,
        api=api,
    )
    publisher = HuggingFaceReleasePublisher(
        profile=federal_register_publication_profile(),
        api=api,
    )
    if (
        plan.repository_id != DEFAULT_DATASET_REPO
        or plan.target_revision != branch
        or plan.audited_parent_commit != parent
        or plan.release_sha256 != package.manifest_digest
        or not plan.operations
    ):
        raise StageFederalRegisterError(
            "canonical Federal staging plan identity drifted"
        )
    return package, publisher, plan


def load_publication_approval(
    path: Path | str,
    *,
    expected_plan_digest: str,
) -> PublicationApproval:
    """Load one bounded human approval for one exact canonical plan."""

    target = Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file():
        raise StageAuthorizationError("publication approval is missing or unsafe")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StageAuthorizationError("publication approval is malformed") from exc
    allowed = {
        "approval_id",
        "approver",
        "credentials_scope",
        "max_cost_usd",
        "max_upload_bytes",
        "notes",
        "plan_digest",
    }
    if type(payload) is not dict or set(payload) != allowed:
        raise StageAuthorizationError(
            "publication approval must contain only the exact bounded fields"
        )
    if payload.get("plan_digest") != expected_plan_digest:
        raise StageAuthorizationError(
            "publication approval plan_digest differs from the reviewed plan"
        )
    try:
        approval = PublicationApproval(**payload)
    except (TypeError, ValueError) as exc:
        raise StageAuthorizationError("publication approval is invalid") from exc
    if approval.credentials_scope != f"dataset:write:{DEFAULT_DATASET_REPO}":
        raise StageAuthorizationError(
            "publication approval credentials_scope differs from the Federal target"
        )
    return approval


def canonical_plan_inventory(plan: PublicationPlan) -> list[dict[str, Any]]:
    """Return the exact add-only operation inventory carried by *plan*."""

    if type(plan) is not PublicationPlan:
        raise StageFederalRegisterError("canonical PublicationPlan is required")
    inventory = [item.to_dict() for item in plan.operations]
    if not inventory or any(item.get("operation") != "add" for item in inventory):
        raise StageSafetyError("canonical staging plan is not strictly add-only")
    return inventory


def build_canonical_staging_live_receipt(
    *,
    plan: PublicationPlan,
    controls: FederalRegisterCanonicalControlBundle,
    branch_receipt: CanonicalLegalCorporaMutationReceipt,
    commit_receipt: CanonicalLegalCorporaMutationReceipt,
) -> dict[str, Any]:
    """Seal the two independently authorized Federal staging mutations."""

    if type(branch_receipt) is not CanonicalLegalCorporaMutationReceipt or type(
        commit_receipt
    ) is not CanonicalLegalCorporaMutationReceipt:
        raise StageFederalRegisterError(
            "canonical branch and commit mutation receipts are required"
        )
    if type(controls) is not FederalRegisterCanonicalControlBundle:
        raise StageFederalRegisterError("canonical Federal staging controls are required")
    if controls.phase != PUBLICATION_PHASE:
        raise StageFederalRegisterError("Federal staging control phase drifted")
    operations = canonical_plan_inventory(plan)
    branch = branch_receipt.to_dict()
    commit = commit_receipt.to_dict()
    common = {
        "operation": AUTHORIZED_OPERATION,
        "parent_commit": plan.audited_parent_commit,
        "phase": PUBLICATION_PHASE,
        "plan_digest": plan.plan_digest,
        "policy_proof_digest": controls.policy_proof_digest,
        "release_manifest_digest": controls.release_manifest_digest,
        "repository_id": plan.repository_id,
        "revision": plan.target_revision,
        "runtime_authorized": True,
    }
    for label, mutation, method in (
        ("branch", branch, "create_branch"),
        ("commit", commit, "create_commit"),
    ):
        expected = {**common, "method": method}
        if any(mutation.get(key) != value for key, value in expected.items()):
            raise StageFederalRegisterError(
                f"canonical {label} receipt differs from the Federal staging plan"
            )
    if (
        branch["resulting_commit_sha"] != plan.audited_parent_commit
        or commit["resulting_commit_sha"] == plan.audited_parent_commit
        or branch["approval_id"] == commit["approval_id"]
    ):
        raise StageAuthorizationError(
            "Federal staging branch and commit require independent one-shot approvals"
        )
    staging_revision = require_immutable_revision(
        commit["resulting_commit_sha"],
        name="staging_revision",
    )
    uploaded = [
        {
            "relative_path": item["relative_path"],
            "remote_path": item["remote_path"],
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
        }
        for item in operations
    ]
    receipt: dict[str, Any] = {
        "acceptance": {
            "add_only": True,
            "credentials_environment_only": True,
            "gate_invoked_before_first_mutation": True,
            "legacy_files_deleted": False,
            "no_absolute_path_or_secret": True,
            "no_unexpected_operations": True,
            "visibility_unchanged": True,
        },
        "base_revision": plan.audited_parent_commit,
        "branch_mutation": branch,
        "candidate_manifest_digest": controls.candidate_manifest_digest,
        "commit_mutation": commit,
        "dirty": False,
        "fixture_only": False,
        "gate": {
            "authorized": True,
            "dataset_repo_id": plan.repository_id,
            "invoked_before_first_mutation": True,
            "network_mutation_permitted": True,
            "operation": AUTHORIZED_OPERATION,
            "phase": PUBLICATION_PHASE,
            "task_id": GATE_TASK_ID,
        },
        "goal_id": GOAL_ID,
        "legacy_files_deleted": False,
        "live_network": True,
        "live_staging": True,
        "manifest_digest": controls.release_manifest_digest,
        "mutation_executed": True,
        "network_required": True,
        "operations": operations,
        "phase": PUBLICATION_PHASE,
        "plan_digest": plan.plan_digest,
        "policy_proof_digest": controls.policy_proof_digest,
        "previous_public_pin": PRODUCTION_REVISION,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "release_manifest_digest": controls.release_manifest_digest,
        "remote_write_contacted": True,
        "schema": STAGE_RECEIPT_SCHEMA,
        "skipped": list(plan.skipped_exact_matches),
        "staged_diff_digest": plan.plan_digest,
        "staging_branch": plan.target_revision,
        "staging_candidate_digest": controls.staging_candidate_digest,
        "staging_revision": staging_revision,
        "status": "passed",
        "target_repo": plan.repository_id,
        "task_id": TASK_ID,
        "transport": "canonical_hub_runtime",
        "unexpected_operations": [],
        "upload_bytes": int(plan.cost_receipt.get("upload_bytes", 0)),
        "upload_file_count": len(operations),
        "uploaded": uploaded,
        "visibility_changed": False,
    }
    reject_credentials_in_payload(receipt, label="canonical_stage_receipt")
    receipt["report_digest_sha256"] = digest_mapping(receipt)
    return check_canonical_stage_receipt(receipt, require_live=True)


def check_canonical_stage_receipt(
    receipt: Mapping[str, Any],
    *,
    require_live: bool = True,
) -> dict[str, Any]:
    """Validate canonical Federal staging evidence without replaying a write."""

    report = dict(receipt) if isinstance(receipt, Mapping) else {}
    if (
        report.get("schema") != STAGE_RECEIPT_SCHEMA
        or report.get("task_id") != TASK_ID
        or report.get("target_repo") != DEFAULT_DATASET_REPO
        or report.get("staging_branch") != DEFAULT_STAGING_BRANCH
        or report.get("fixture_only") is not False
        or report.get("dirty") is not False
        or report.get("unexpected_operations") != []
        or report.get("visibility_changed") is not False
    ):
        raise StageFederalRegisterError(
            "canonical Federal staging receipt identity or safety flags drifted"
        )
    for field in (
        "candidate_manifest_digest",
        "manifest_digest",
        "plan_digest",
        "policy_proof_digest",
        "release_manifest_digest",
        "staging_candidate_digest",
    ):
        if not _SHA256_RE.fullmatch(str(report.get(field) or "")):
            raise StageFederalRegisterError(f"canonical receipt {field} is invalid")
    declared = str(report.get("report_digest_sha256") or "")
    body = {key: value for key, value in report.items() if key != "report_digest_sha256"}
    if not _SHA256_RE.fullmatch(declared) or digest_mapping(body) != declared:
        raise StageFederalRegisterError("canonical staging receipt digest mismatch")
    require_immutable_revision(report.get("base_revision"), name="base_revision")
    require_immutable_revision(
        report.get("staging_revision"), name="staging_revision"
    )
    operations = report.get("operations")
    if not isinstance(operations, list) or not operations:
        raise StageFederalRegisterError("canonical staging receipt has no operations")
    if any(
        not isinstance(item, Mapping) or item.get("operation") != "add"
        for item in operations
    ):
        raise StageSafetyError("canonical staging receipt is not add-only")
    if require_live and (
        report.get("status") != "passed"
        or report.get("live_network") is not True
        or report.get("live_staging") is not True
        or report.get("mutation_executed") is not True
        or report.get("remote_write_contacted") is not True
        or report.get("transport") != "canonical_hub_runtime"
    ):
        raise StageFederalRegisterError(
            "canonical staging receipt is not clean live evidence"
        )
    return report


def _planned_artifact(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        relative = str(item.get("relative_path") or "")
        sha256 = str(item.get("sha256") or "")
        size_bytes = int(item.get("size_bytes") or 0)
        family = str(item.get("family") or "")
        content_cid = str(item.get("content_cid") or "")
        media_type = str(item.get("media_type") or "")
        row_count = int(item.get("row_count") or 0)
        schema_id = str(item.get("schema_id") or "")
        first_key = item.get("first_key")
        last_key = item.get("last_key")
    else:
        relative = item.relative_path
        sha256 = item.sha256
        size_bytes = int(item.size_bytes)
        family = item.family
        content_cid = item.content_cid
        media_type = item.media_type
        row_count = int(item.row_count)
        schema_id = item.schema_id
        first_key = getattr(item, "first_key", None)
        last_key = getattr(item, "last_key", None)
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise StageSafetyError(f"unsafe artifact path: {relative!r}")
    return {
        "content_cid": content_cid,
        "family": family,
        "first_key": first_key,
        "last_key": last_key,
        "media_type": media_type,
        "operation": "add_only_upload",
        "relative_path": relative,
        "row_count": row_count,
        "schema_id": schema_id,
        "sha256": sha256,
        "size_bytes": size_bytes,
    }


def plan_stage_from_candidate(
    candidate: Mapping[str, Any] | None = None,
    *,
    release: Any | None = None,
    target_repo: str | None = None,
    staging_branch: str = DEFAULT_STAGING_BRANCH,
    base_revision: str = DEFAULT_BASE_REVISION,
    package_version: str = DEFAULT_PACKAGE_VERSION,
    publication_seal: str | None = None,
    dry_run: bool = True,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Build a deterministic add-only stage plan from the sealed candidate."""

    if type(dry_run) is not bool:
        raise StageFederalRegisterError("dry_run must be boolean")

    report = dict(candidate) if candidate is not None else load_candidate_report(
        repo_root=repo_root
    )
    if release is None:
        release = build_fixture_release(repo_root=repo_root)

    dataset_id = _normalize_dataset_id(
        target_repo or str(report.get("dataset_repo_id") or DEFAULT_DATASET_REPO)
    )
    branch = assert_non_production_staging_branch(
        staging_branch,
        production_revision=PRODUCTION_REVISION,
        publication_seal=publication_seal,
    )
    base = require_immutable_revision(base_revision, name="base_revision")
    manifest_digest = str(report.get("manifest_digest") or release.manifest_digest)
    if not _SHA256_RE.fullmatch(manifest_digest):
        raise StageFederalRegisterError("manifest_digest must be 64-hex")
    if manifest_digest != release.manifest_digest:
        raise StageFederalRegisterError(
            "in-memory release manifest_digest drifted from the sealed candidate"
        )

    artifacts = [_planned_artifact(item) for item in release.artifacts]
    descriptor_arts = [
        _planned_artifact(item)
        for item in (report.get("descriptors") or [])
        if isinstance(item, Mapping)
    ]
    if descriptor_arts:
        by_path = {item["relative_path"]: item for item in artifacts}
        for item in descriptor_arts:
            existing = by_path.get(item["relative_path"])
            if existing is None:
                artifacts.append(item)
                continue
            for field in ("sha256", "size_bytes", "content_cid", "family"):
                if item.get(field) and existing.get(field) and item[field] != existing[field]:
                    raise StageFederalRegisterError(
                        f"candidate descriptor {item['relative_path']} {field} "
                        "does not match the packaged release"
                    )
    artifacts.sort(key=lambda item: item["relative_path"])
    operations = _assert_operations_add_only(
        [item["operation"] for item in artifacts]
    )
    upload_bytes = sum(int(item["size_bytes"]) for item in artifacts)
    families = sorted(
        {
            str(item["family"])
            for item in artifacts
            if item.get("family")
        }
    )
    required = list(report.get("required_semantic_families") or required_semantic_families())
    present_families = set(families)
    if "vector_locator" in present_families:
        present_families.add("locator_index")
    if "source_receipts" in present_families:
        present_families.add("source_receipt")
    missing_families = sorted(
        set(required) - present_families
    )
    if missing_families:
        raise StageFederalRegisterError(
            "stage plan missing required semantic families: "
            + ", ".join(missing_families)
        )

    binding = {
        "artifacts": [
            {
                "content_cid": item["content_cid"],
                "operation": item["operation"],
                "relative_path": item["relative_path"],
                "sha256": item["sha256"],
                "size_bytes": item["size_bytes"],
            }
            for item in artifacts
        ],
        "base_revision": base,
        "dataset_id": dataset_id,
        "legacy_files_deleted": False,
        "manifest_digest": manifest_digest,
        "package_version": package_version,
        "release_root_cid": str(
            report.get("release_root_cid") or release.release_root_cid
        ),
        "schema": STAGE_PLAN_SCHEMA,
        "staging_branch": branch,
        "target_repo": dataset_id,
    }
    plan_digest = digest_mapping(binding)
    staged_diff = {
        "artifacts": [
            {
                "relative_path": item["relative_path"],
                "sha256": item["sha256"],
                "size_bytes": item["size_bytes"],
            }
            for item in artifacts
        ],
        "base_revision": base,
        "release_root_cid": binding["release_root_cid"],
        "staging_branch": branch,
        "target_repo": dataset_id,
    }
    staged_diff_digest = digest_mapping(staged_diff)
    staging_revision = hashlib.sha1(
        canonical_json_dumps(
            {
                "base_revision": base,
                "manifest_digest": manifest_digest,
                "plan_digest": plan_digest,
                "staging_branch": branch,
                "target_repo": dataset_id,
            }
        ).encode("utf-8")
    ).hexdigest()

    configs = advertised_viewer_configs()
    viewer = assert_configs_schema_coherent(configs)
    plan: dict[str, Any] = {
        "acceptance": {
            "add_only": True,
            "credentials_environment_only": True,
            "deletion_impossible": True,
            "force_push_impossible": True,
            "gate_required_before_mutation": True,
            "manifest_explicit": True,
            "mutation_requires_authorization": True,
            "production_target_rejected_without_seal": True,
            "revision_explicit": True,
            "target_explicit": True,
            "visibility_change_impossible": True,
        },
        "artifacts": artifacts,
        "base_revision": base,
        "dataset_id": dataset_id,
        "dry_run": dry_run,
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "goal_id": GOAL_ID,
        "legacy_files_deleted": False,
        "manifest_digest": manifest_digest,
        "manifest_path": MANIFEST_FILENAME,
        "observation_cutoff": str(
            report.get("observation_cutoff") or DEFAULT_OBSERVATION_CUTOFF
        ),
        "operations": list(operations),
        "package_version": package_version,
        "phase": PUBLICATION_PHASE,
        "plan_digest": plan_digest,
        "predicted_staging_revision": staging_revision,
        "producer": PRODUCER,
        "production_revision": PRODUCTION_REVISION,
        "program_id": PROGRAM_ID,
        "publication_seal": publication_seal,
        "release_point": str(
            report.get("release_point")
            or getattr(
                release,
                "release_point",
                f"federal-register/v2/{DEFAULT_OBSERVATION_CUTOFF[:10]}",
            )
        ),
        "release_profile": str(report.get("release_profile") or RELEASE_PROFILE),
        "release_root_cid": binding["release_root_cid"],
        "required_semantic_families": required,
        "schema": STAGE_PLAN_SCHEMA,
        "semantic_families": families,
        "staged_diff_digest": staged_diff_digest,
        "staging_branch": branch,
        "task_id": TASK_ID,
        "target_repo": dataset_id,
        "upload_bytes": upload_bytes,
        "upload_file_count": len(artifacts),
        "viewer": {
            "default_config": viewer.get("default_config"),
            "ok": True,
            "schema_coherent": True,
        },
        "visibility": "public",
        "visibility_change_allowed": False,
    }
    reject_credentials_in_payload(plan, label="stage_plan")
    assert_safe_stage_plan(plan)
    return plan


def assert_safe_stage_plan(plan: Mapping[str, Any]) -> None:
    """Fail closed if a plan schedules forbidden or production-unsafe actions."""

    if not isinstance(plan, Mapping):
        raise StageFederalRegisterError("stage plan must be an object")
    required = (
        "target_repo",
        "staging_branch",
        "base_revision",
        "manifest_digest",
        "plan_digest",
        "release_root_cid",
        "operations",
        "artifacts",
    )
    missing = [key for key in required if not plan.get(key)]
    if missing:
        raise StageFederalRegisterError(
            "stage plan missing explicit fields: " + ", ".join(missing)
        )
    _normalize_dataset_id(str(plan["target_repo"]), label="target_repo")
    assert_non_production_staging_branch(
        str(plan["staging_branch"]),
        production_revision=str(plan.get("production_revision") or PRODUCTION_REVISION),
        publication_seal=(
            str(plan["publication_seal"]) if plan.get("publication_seal") else None
        ),
    )
    require_immutable_revision(str(plan["base_revision"]), name="base_revision")
    _assert_operations_add_only(list(plan.get("operations") or []))
    if plan.get("visibility_change_allowed") is True:
        raise StageSafetyError("stage plan must not allow visibility changes")
    if plan.get("legacy_files_deleted") is True:
        raise StageSafetyError("stage plan must not delete legacy files")
    for artifact in plan.get("artifacts") or []:
        if not isinstance(artifact, Mapping):
            raise StageFederalRegisterError("artifact entries must be objects")
        op = str(artifact.get("operation") or "")
        if op and op not in ALLOWED_OPERATIONS:
            raise StageSafetyError(f"artifact operation forbidden: {op!r}")


def federal_staging_gate_request(
    *,
    manifest_digest: str,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Construct the LCR-074 federal_staging request bound to *manifest_digest*."""

    del repo_root  # reserved for canonical-runtime callers
    if not _SHA256_RE.fullmatch(str(manifest_digest or "").strip().casefold()):
        raise StageFederalRegisterError(
            "federal staging gate requires the candidate 64-hex manifest digest"
        )
    request = example_authorized_request(
        PUBLICATION_PHASE,
        manifest_digest=str(manifest_digest).strip().casefold(),
    )
    request["operation"] = AUTHORIZED_OPERATION
    request["dataset_repo_id"] = DEFAULT_DATASET_REPO
    request["phase"] = PUBLICATION_PHASE
    request["staging_branch"] = DEFAULT_STAGING_BRANCH
    request["credentials_environment_only"] = True
    request["secret_redacted"] = True
    request["authorize_mutation"] = True
    request["fixture_only_evidence"] = False
    request["evidence_is_dirty"] = False
    return request


def invoke_federal_staging_gate(
    request: Mapping[str, Any] | None = None,
    *,
    manifest_digest: str | None = None,
    repo_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> PublicationGateDecision:
    """Evaluate the LCR-074 gate for the Federal staging phase.

    Callers must invoke this (or :func:`authorize_federal_staging_upload`)
    **before** the first Hub mutation.
    """

    payload = (
        dict(request)
        if request is not None
        else federal_staging_gate_request(
            manifest_digest=str(manifest_digest or ""),
            repo_root=repo_root,
        )
    )
    if str(payload.get("phase") or "") != PUBLICATION_PHASE:
        raise StageGateError(
            f"entrypoint must invoke LCR-074 for {PUBLICATION_PHASE}, "
            f"got phase={payload.get('phase')!r}"
        )
    try:
        decision = require_publication_gate(payload, environ=environ)
    except PublicationGateDeniedError as exc:
        raise StageGateError(
            "LCR-074 federal_staging gate refused before Hub mutation: "
            + str(exc)
        ) from exc
    except PublicationGateError as exc:
        raise StageGateError(f"LCR-074 federal_staging gate error: {exc}") from exc
    if not decision.authorized or not decision.network_mutation_permitted:
        raise StageGateError(
            "LCR-074 federal_staging gate did not authorize network mutation"
        )
    if decision.phase != PUBLICATION_PHASE:
        raise StageGateError(
            f"gate decision phase is {decision.phase!r}, expected {PUBLICATION_PHASE}"
        )
    if decision.operation != AUTHORIZED_OPERATION:
        raise StageGateError(
            f"gate decision operation is {decision.operation!r}, "
            f"expected {AUTHORIZED_OPERATION}"
        )
    if decision.dataset_repo_id != DEFAULT_DATASET_REPO:
        raise StageGateError(
            f"gate decision target is {decision.dataset_repo_id!r}, "
            f"expected {DEFAULT_DATASET_REPO}"
        )
    redacted = decision.to_dict()
    reject_credentials_in_payload(redacted, label="publication_gate_decision")
    return decision


def _execute_canonical_federal_staging_mutation(
    publisher: Any,
    publication_plan: Any,
    *,
    approval: Any,
    local_root: Path | str,
    mutation_method: str,
    policy_proof_digest: str,
    live_policy_proof: Any = None,
    commit_message: str | None = None,
) -> Any:
    """Internal one-operation adapter; never grants a multi-step capability."""

    method = str(mutation_method or "").strip()
    if method not in {"create_branch", "create_commit"}:
        raise StageSafetyError(
            "Federal staging permits only create_branch or create_commit"
        )
    executor = getattr(
        publisher,
        "execute_canonical_legal_corpora_mutation",
        None,
    )
    if not callable(executor):
        raise StageAuthorizationError(
            "shared canonical legal-corpora publisher is unavailable"
        )
    return executor(
        publication_plan,
        approval=approval,
        local_root=local_root,
        publication_phase=PUBLICATION_PHASE,
        mutation_method=method,
        policy_proof_digest=policy_proof_digest,
        commit_message=commit_message,
        live_policy_proof=live_policy_proof,
    )


def create_canonical_federal_staging_branch(
    publisher: Any,
    branch_plan: Any,
    *,
    approval: Any,
    local_root: Path | str,
    policy_proof_digest: str,
    live_policy_proof: Any = None,
) -> Any:
    """Authorize and create only the isolated staging branch.

    The returned result is not an authorization for the subsequent commit.
    Operators must call :func:`commit_canonical_federal_staging_candidate`
    with a separately evaluated commit plan and approval.
    """

    return _execute_canonical_federal_staging_mutation(
        publisher,
        branch_plan,
        approval=approval,
        local_root=local_root,
        mutation_method="create_branch",
        policy_proof_digest=policy_proof_digest,
        live_policy_proof=live_policy_proof,
    )


def commit_canonical_federal_staging_candidate(
    publisher: Any,
    commit_plan: Any,
    *,
    approval: Any,
    local_root: Path | str,
    policy_proof_digest: str,
    live_policy_proof: Any = None,
    commit_message: str | None = None,
) -> Any:
    """Separately authorize and commit the exact staged candidate bytes."""

    return _execute_canonical_federal_staging_mutation(
        publisher,
        commit_plan,
        approval=approval,
        local_root=local_root,
        mutation_method="create_commit",
        policy_proof_digest=policy_proof_digest,
        live_policy_proof=live_policy_proof,
        commit_message=commit_message,
    )


def execute_canonical_staging_release(
    *,
    release: Any,
    output_root: Path | str,
    candidate: Mapping[str, Any],
    branch_approval: PublicationApproval,
    commit_approval: PublicationApproval,
    repository_root: Path | str = REPOSITORY_ROOT,
    audited_parent_commit: str = DEFAULT_BASE_REVISION,
    staging_branch: str = DEFAULT_STAGING_BRANCH,
) -> dict[str, Any]:
    """Create then commit staging through two independently gated calls."""

    if branch_approval.approval_id == commit_approval.approval_id:
        raise StageAuthorizationError(
            "branch and commit require distinct approval identifiers"
        )
    package, publisher, branch_plan = build_canonical_staging_plan(
        release=release,
        output_root=output_root,
        audited_parent_commit=audited_parent_commit,
        staging_branch=staging_branch,
        candidate=candidate,
    )
    if branch_approval.plan_digest != branch_plan.plan_digest:
        raise StageAuthorizationError("branch approval does not bind the staging plan")
    controls = materialize_federal_register_staging_controls(
        package,
        branch_plan,
        candidate,
        repository_root=repository_root,
    )
    branch_receipt = create_canonical_federal_staging_branch(
        publisher,
        branch_plan,
        approval=branch_approval,
        local_root=package.output_root,
        policy_proof_digest=controls.policy_proof_digest,
    )
    branch_parent = require_immutable_revision(
        branch_receipt.resulting_commit_sha,
        name="staging_branch_parent",
    )

    # Rebuild and rebind immediately before the second network mutation.  A
    # branch approval/capability is never reused for its subsequent commit.
    package_after, publisher_after, commit_plan = build_canonical_staging_plan(
        release=release,
        output_root=output_root,
        audited_parent_commit=branch_parent,
        staging_branch=staging_branch,
        candidate=candidate,
    )
    controls_after = materialize_federal_register_staging_controls(
        package_after,
        commit_plan,
        candidate,
        repository_root=repository_root,
    )
    if (
        package_after != package
        or commit_plan.plan_digest != branch_plan.plan_digest
        or controls_after != controls
        or commit_approval.plan_digest != commit_plan.plan_digest
    ):
        raise StageAuthorizationError(
            "rebuilt Federal staging plan, controls, or commit approval drifted"
        )
    commit_receipt = commit_canonical_federal_staging_candidate(
        publisher_after,
        commit_plan,
        approval=commit_approval,
        local_root=package_after.output_root,
        policy_proof_digest=controls_after.policy_proof_digest,
    )
    return build_canonical_staging_live_receipt(
        plan=commit_plan,
        controls=controls_after,
        branch_receipt=branch_receipt,
        commit_receipt=commit_receipt,
    )


def release_file_bytes(release: Any) -> dict[str, bytes]:
    inventory: dict[str, bytes] = {}
    for artifact in release.artifacts:
        inventory[str(artifact.relative_path)] = bytes(artifact.content)
    return inventory


def execute_stage(
    plan: Mapping[str, Any],
    *,
    release: Any,
    hub: FakeFederalRegisterHub | None = None,
    authorize_mutation: bool = False,
    dry_run: bool = True,
    repo_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
    batch_size: int = 32,
) -> dict[str, Any]:
    """Stage the candidate. Gate is invoked before the first Hub write."""

    assert_safe_stage_plan(plan)
    request = federal_staging_gate_request(
        manifest_digest=str(plan["manifest_digest"]),
        repo_root=repo_root,
    )
    gate_decision = invoke_federal_staging_gate(request, environ=environ)
    gate_record = {
        "authorized": gate_decision.authorized,
        "dataset_repo_id": gate_decision.dataset_repo_id,
        "invoked_before_first_mutation": True,
        "network_mutation_permitted": gate_decision.network_mutation_permitted,
        "operation": gate_decision.operation,
        "passed_gates": list(gate_decision.passed_gates),
        "phase": gate_decision.phase,
        "previous_public_pin": gate_decision.previous_public_pin,
        "task_id": GATE_TASK_ID,
    }

    if dry_run and not authorize_mutation:
        receipt = build_stage_receipt(
            plan,
            gate=gate_record,
            dry_run=True,
            mutation_executed=False,
            live_network=False,
            staging_revision=str(plan["predicted_staging_revision"]),
            uploaded=[],
            skipped=[],
            operations=[],
        )
        return receipt

    assert_mutation_authorized(
        authorize_mutation=authorize_mutation,
        environ=environ,
    )
    if type(hub) is not FakeFederalRegisterHub:
        raise StageAuthorizationError(
            "protected staging requires execute_canonical_federal_staging_mutation; "
            "execute_stage accepts only the exact in-memory test transport"
        )
    transport = hub
    files = release_file_bytes(release)

    uploaded_receipt = transport.upload_files(
        files,
        repo_id=str(plan["target_repo"]),
        branch=str(plan["staging_branch"]),
        base_revision=str(plan["base_revision"]),
        batch_size=batch_size,
    )
    receipt = build_stage_receipt(
        plan,
        gate=gate_record,
        dry_run=False,
        mutation_executed=True,
        live_network=False,
        staging_revision=str(uploaded_receipt["staging_revision"]),
        uploaded=list(uploaded_receipt.get("uploaded") or []),
        skipped=list(uploaded_receipt.get("skipped") or []),
        operations=list(uploaded_receipt.get("operations") or []),
        hub=transport,
    )
    return receipt


def build_stage_receipt(
    plan: Mapping[str, Any],
    *,
    gate: Mapping[str, Any],
    dry_run: bool,
    mutation_executed: bool,
    live_network: bool,
    staging_revision: str,
    uploaded: Sequence[Mapping[str, Any]],
    skipped: Sequence[Mapping[str, Any]],
    operations: Sequence[Mapping[str, Any]],
    hub: FakeFederalRegisterHub | None = None,
) -> dict[str, Any]:
    revision = require_immutable_revision(staging_revision, name="staging_revision")
    unexpected = [
        str(op.get("operation"))
        for op in operations
        if str(op.get("operation") or "") not in ALLOWED_OPERATIONS
    ]
    if unexpected:
        raise StageSafetyError(
            "unexpected operations in staging receipt: " + ", ".join(sorted(set(unexpected)))
        )
    if not gate.get("invoked_before_first_mutation"):
        raise StageGateError(
            "staging receipt missing LCR-074 invocation before first mutation"
        )
    status = "dry_run_only" if dry_run and not mutation_executed else "staged"
    receipt: dict[str, Any] = {
        "acceptance": {
            "add_only": True,
            "credentials_environment_only": True,
            "gate_invoked_before_first_mutation": True,
            "legacy_files_deleted": False,
            "no_absolute_path_or_secret": True,
            "no_unexpected_operations": not unexpected,
            "production_target_rejected": True,
            "secrets_absent": True,
            "visibility_unchanged": True,
        },
        "base_revision": plan["base_revision"],
        "code_version": CODE_VERSION,
        "dry_run": dry_run,
        "fixture_only": not live_network,
        "gate": dict(gate),
        "goal_id": GOAL_ID,
        "legacy_files_deleted": False,
        "live_network": live_network,
        "live_staging": bool(live_network and mutation_executed),
        "manifest_digest": plan["manifest_digest"],
        "mutation_executed": mutation_executed,
        "network_required": live_network,
        "observation_cutoff": plan.get("observation_cutoff") or DEFAULT_OBSERVATION_CUTOFF,
        "operations": ["add_only_upload"],
        "phase": PUBLICATION_PHASE,
        "plan_digest": plan["plan_digest"],
        "previous_public_pin": PRODUCTION_REVISION,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "release_root_cid": plan["release_root_cid"],
        "remote_write_contacted": bool(mutation_executed and live_network),
        "schema": STAGE_RECEIPT_SCHEMA,
        "skipped": [dict(item) for item in skipped],
        "skipped_hashes": [str(item.get("sha256")) for item in skipped],
        "staged_diff_digest": plan["staged_diff_digest"],
        "staging_branch": plan["staging_branch"],
        "staging_revision": revision,
        "status": status,
        "task_id": TASK_ID,
        "target_repo": plan["target_repo"],
        "tokens_used": False,
        "transport": (
            "canonical_hub_runtime" if live_network else "in_memory_fixture_staging"
        ),
        "unexpected_operations": unexpected,
        "upload_bytes": plan["upload_bytes"],
        "upload_file_count": plan["upload_file_count"],
        "uploaded": [dict(item) for item in uploaded],
        "uploaded_hashes": [str(item.get("sha256")) for item in uploaded],
        "visibility_changed": False,
    }
    if hub is not None:
        receipt["redownload_file_count"] = len(hub.files)
    reject_credentials_in_payload(receipt, label="stage_receipt")
    return receipt


def build_dry_run_receipt(
    plan: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    if plan is None:
        release = build_fixture_release(repo_root=repo_root)
        fixture_candidate = build_federal_candidate_evidence(release)
        resolved = plan_stage_from_candidate(
            fixture_candidate,
            release=release,
            repo_root=repo_root,
            dry_run=True,
        )
    else:
        resolved = plan
    request = federal_staging_gate_request(
        manifest_digest=str(resolved["manifest_digest"]),
        repo_root=repo_root,
    )
    decision = invoke_federal_staging_gate(request)
    return build_stage_receipt(
        resolved,
        gate={
            "authorized": decision.authorized,
            "dataset_repo_id": decision.dataset_repo_id,
            "invoked_before_first_mutation": True,
            "network_mutation_permitted": decision.network_mutation_permitted,
            "operation": decision.operation,
            "passed_gates": list(decision.passed_gates),
            "phase": decision.phase,
            "previous_public_pin": decision.previous_public_pin,
            "task_id": GATE_TASK_ID,
        },
        dry_run=True,
        mutation_executed=False,
        live_network=False,
        staging_revision=str(resolved["predicted_staging_revision"]),
        uploaded=[],
        skipped=[],
        operations=[],
    )


def check_stage_receipt(
    receipt: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate a staging receipt (or rebuild a dry-run and check policy)."""

    if isinstance(receipt, Mapping) and receipt.get("fixture_only") is False:
        observed = check_canonical_stage_receipt(receipt, require_live=True)
        return {
            "check": "pass",
            "fixture_only": False,
            "gate_invoked_before_first_mutation": True,
            "manifest_digest": observed["manifest_digest"],
            "mismatches": [],
            "ok": True,
            "phase": PUBLICATION_PHASE,
            "staging_revision": observed["staging_revision"],
            "task_id": TASK_ID,
            "target_repo": observed["target_repo"],
        }

    expected = build_dry_run_receipt(repo_root=repo_root)
    observed = dict(receipt) if receipt is not None else expected
    mismatches: list[str] = []
    for key in (
        "schema",
        "task_id",
        "goal_id",
        "target_repo",
        "staging_branch",
        "base_revision",
        "manifest_digest",
        "plan_digest",
        "phase",
    ):
        if expected.get(key) != observed.get(key):
            mismatches.append(key)
    if observed.get("visibility_changed") is True:
        mismatches.append("visibility_changed")
    if observed.get("unexpected_operations"):
        mismatches.append("unexpected_operations")
    gate = observed.get("gate") or {}
    if not isinstance(gate, Mapping) or gate.get("invoked_before_first_mutation") is not True:
        mismatches.append("gate.invoked_before_first_mutation")
    if str(gate.get("phase") or "") != PUBLICATION_PHASE:
        mismatches.append("gate.phase")
    if str(gate.get("task_id") or "") != GATE_TASK_ID:
        mismatches.append("gate.task_id")
    require_immutable_revision(observed.get("staging_revision"), name="staging_revision")
    reject_credentials_in_payload(observed, label="stage_receipt_check")
    if mismatches:
        raise StageFederalRegisterError(
            "federal staging receipt check failed: " + ", ".join(mismatches)
        )
    return {
        "check": "pass",
        "gate_invoked_before_first_mutation": True,
        "manifest_digest": expected["manifest_digest"],
        "mismatches": [],
        "ok": True,
        "phase": PUBLICATION_PHASE,
        "staging_revision": expected["staging_revision"],
        "task_id": TASK_ID,
        "target_repo": expected["target_repo"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or execute the additive Federal Register staging upload "
            "after the LCR-074 federal_staging gate."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Plan and invoke the gate without Hub mutation (default when no mutation flag).",
    )
    parser.add_argument(
        "--check-receipt",
        action="store_true",
        help="Rebuild the dry-run receipt and verify the LCR-074/federal staging contract.",
    )
    parser.add_argument(
        "--authorize-mutation",
        action="store_true",
        help=(
            "Opt in to staging mutation. Requires "
            f"${AUTHORIZATION_ENV} and still invokes LCR-074 first."
        ),
    )
    parser.add_argument(
        "--fake-hub",
        action="store_true",
        help="Reserved test-only transport; the production CLI always refuses it.",
    )
    parser.add_argument(
        "--staging-branch",
        default=DEFAULT_STAGING_BRANCH,
        help=f"Explicit staging branch (default: {DEFAULT_STAGING_BRANCH})",
    )
    parser.add_argument(
        "--target-repo",
        default=DEFAULT_DATASET_REPO,
        help=f"Authorized dataset repo (default: {DEFAULT_DATASET_REPO})",
    )
    parser.add_argument(
        "--base-revision",
        default=DEFAULT_BASE_REVISION,
        help="Immutable 40-hex base pin (default: previous public pin)",
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        default=None,
        help="Override path to federal_candidate.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the staging receipt JSON (default: stdout)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Resumable upload batch size (default: 32)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    try:
        reject_secrets_in_argv(argv_list)
    except StageFederalRegisterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parser = build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code or 0)

    try:
        if args.check_receipt:
            result = check_stage_receipt()
            write_json(args.output, result)
            return 0

        candidate = load_candidate_report(args.candidate)
        plan = plan_stage_from_candidate(
            candidate,
            target_repo=args.target_repo,
            staging_branch=args.staging_branch,
            base_revision=args.base_revision,
            dry_run=not args.authorize_mutation,
        )
        release = build_fixture_release()
        want_mutate = bool(args.authorize_mutation)
        if args.fake_hub:
            raise StageAuthorizationError(
                "--fake-hub is test-only and unavailable from the production CLI"
            )
        if want_mutate:
            assert_mutation_authorized(authorize_mutation=True)
            raise StageAuthorizationError(
                "standalone live staging requires the exact in-memory production "
                "release plus two approvals; call execute_canonical_staging_release "
                "so create_branch and create_commit each pass the shared runtime"
            )
        receipt = execute_stage(
            plan,
            release=release,
            hub=None,
            authorize_mutation=want_mutate,
            dry_run=not want_mutate or args.dry_run,
            batch_size=int(args.batch_size),
        )
        write_json(args.output, receipt)
        return 0
    except (
        StageFederalRegisterError,
        StageAuthorizationError,
        StageSafetyError,
        StageProductionTargetError,
        StageGateError,
        PublicationGateError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
