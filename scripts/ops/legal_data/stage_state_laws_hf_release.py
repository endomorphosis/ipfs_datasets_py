#!/usr/bin/env python3
"""Upload the state-law candidate additively to an explicit staging revision (LCR-040).

Default mode is **offline dry-run** (credential-free, no Hub network contact):

1. Load the sealed LCR-039 candidate and bind its manifest digest.
2. Invoke the LCR-074 publication gate for ``state_staging`` **before** any
   Hub mutation is possible.
3. Plan additive, resumable uploads to an explicit non-production staging
   branch forked from the previous public pin.
4. Emit a redacted staging receipt naming the target, base pin, staging SHA,
   manifest digest, uploaded/skipped hashes, and zero unexpected operations.

Live Hub mutation remains opt-in (``--authorize-mutation`` plus environment
credentials) and still cannot delete, force-push, rewrite history, or change
visibility. Every live write is routed through the source-attested canonical
publisher/runtime boundary.

Offline acceptance self-check::

    python scripts/ops/legal_data/stage_state_laws_hf_release.py --check-receipt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.huggingface.publisher import (
    CanonicalLegalCorporaMutationReceipt,
    HuggingFaceReleasePublisher,
    PublicationApproval,
    PublicationPlan,
    canonical_legal_corpora_policy_proof_digest,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (
    STATE_DATASET_REPO_ID,
    PublicationGateDecision,
    PublicationGateDeniedError,
    PublicationGateError,
    evaluate_publication_gate,
    example_authorized_request,
    require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    RECEIPT_SCHEMA_V1,
    canonical_no_self_field_digest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    StateLawsHFReleaseSafetyError,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    _assert_no_secrets_or_absolute_paths as _scan_for_secrets_or_absolute_paths,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_package import (
    StateLawsPublicationPackage,
    StateLawsStagingControlBundle,
    materialize_state_laws_staging_controls,
    plan_state_laws_staging_publication_dry_run,
    prepare_state_laws_publication_package,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (
    DEFAULT_STAGING_BRANCH,
    PROHIBITED_STAGING_BRANCHES,
    evaluate_live_mutation,
    example_authorized_staging_request,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (
    FORBIDDEN_OPERATIONS as POLICY_FORBIDDEN_OPERATIONS,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    DEFAULT_DATASET_REPO_ID,
    PREVIOUS_PUBLIC_PIN,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "LCR-040"
GOAL_ID: Final = "LCR-G070"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "stage_state_laws_hf_release.py"
CODE_VERSION: Final = "1"
SCHEMA_VERSION: Final = "state-laws-hf-staging-upload/v1"
REPORT_SCHEMA: Final = RECEIPT_SCHEMA_V1
RECEIPT_KIND: Final = "state-laws-staging-upload/v2"
PUBLICATION_PHASE: Final = "state_staging"
AUTHORIZED_OPERATION: Final = "additive_staging_upload"
GATE_TASK_ID: Final = "LCR-074"

DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/staging_upload.json"
)
DEFAULT_CANDIDATE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/release_candidate.json"
)

DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
DEFAULT_BASE_PIN: Final = PREVIOUS_PUBLIC_PIN
DEFAULT_OBSERVATION_TIME: Final = "2026-08-10T12:00:00Z"
AUTHORIZATION_ENV: Final = "STATE_LAWS_STAGING_AUTHORIZATION"
MAX_REPORT_BYTES: Final = 1048576

ALLOWED_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        AUTHORIZED_OPERATION,
        "add_only_upload",
        "skip_identical",
    }
)
FORBIDDEN_OPERATIONS: Final[frozenset[str]] = frozenset(
    set(POLICY_FORBIDDEN_OPERATIONS)
    | {
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
        "direct_main_upload",
        "promote_production",
        "history_rewrite",
        "super_squash_history",
    }
)

SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "STATE_LAWS_HF_TOKEN",
    AUTHORIZATION_ENV,
    "STATE_LAWS_PUBLICATION_AUTHORIZATION",
)

_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"staging_authorization)s?$",
    re.IGNORECASE,
)
_DATASET_ID_RE = re.compile(
    r"^[A-Za-z0-9](?:[-\w.]{0,38}[A-Za-z0-9])?/[A-Za-z0-9._-]+$"
)
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class StageStateLawsError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class StageAuthorizationError(StageStateLawsError):
    """Raised when mutation is attempted without opt-in authorization."""


class StageSafetyError(StageStateLawsError):
    """Raised when a plan would delete, force-push, or change visibility."""


class StageProductionTargetError(StageStateLawsError):
    """Raised when a production target is requested without a publication seal."""


class StageGateError(StageStateLawsError):
    """Raised when the LCR-074 state-staging gate refuses the mutation."""


class StageReceiptError(StageStateLawsError):
    """Raised when the sealed staging receipt does not match the rebuilt plan."""


# Process-local record that the LCR-074 gate ran before any Hub callback.
_GATE_INVOCATIONS: list[dict[str, Any]] = []

# Frozen receipt tests retain this read-only name. Removed mutation adapters
# are intentionally not recreated.
canonical_payload_digest = canonical_no_self_field_digest


# ---------------------------------------------------------------------------
# Paths / encoding
# ---------------------------------------------------------------------------


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return root / DEFAULT_REPORT_RELPATH


def default_candidate_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return root / DEFAULT_CANDIDATE_RELPATH


def _canonical_report_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def inventory_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def publication_digest(payload: Mapping[str, Any]) -> str:
    """Bind the receipt the same way the publication runtime hashes evidence."""

    return canonical_no_self_field_digest(payload)


def receipt_schema_of(payload: Mapping[str, Any]) -> str:
    """Return a producer schema without granting it mutation authority."""

    for key in ("schema", "report_schema", "checkpoint_schema"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def receipt_schema_is_known(schema: str) -> bool:
    """Recognize this lane's read-only receipt namespace."""

    return schema == REPORT_SCHEMA or schema.startswith(
        "ipfs_datasets_py/legal-corpora-"
    )


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


def reject_credentials_in_payload(value: Any, *, label: str = "payload") -> None:
    """Fail closed when tokens, secrets, or credential-like keys appear."""

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

    visit(value, label)
    if offenders:
        raise StageSafetyError(
            f"credential-like material in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_secrets_in_argv(argv: Sequence[str]) -> None:
    """Refuse secrets passed on the command line (credentials are env-only)."""

    joined = " ".join(str(item) for item in argv)
    lowered = joined.casefold()
    needles = (
        "hf_token=",
        "authorization:",
        "bearer ",
        "access_token=",
        "api_token=",
        "state_laws_staging_authorization=",
        "state_laws_hf_token=",
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


def assert_no_secrets_or_absolute_paths(
    payload: Any, *, label: str = "staging-upload"
) -> None:
    reject_credentials_in_payload(payload, label=label)
    try:
        _scan_for_secrets_or_absolute_paths(payload, label=label)
    except StateLawsHFReleaseSafetyError as exc:
        raise StageSafetyError(str(exc)) from exc


def normalize_dataset_id(value: str, *, label: str = "target") -> str:
    text = str(value or "").strip()
    if not _DATASET_ID_RE.fullmatch(text):
        raise StageSafetyError(f"{label} must be owner/name, got {value!r}")
    if text != STATE_DATASET_REPO_ID:
        raise StageProductionTargetError(
            f"{label} is not the authorized state-laws dataset: {text!r}"
        )
    return text


def normalize_staging_branch(value: str, *, label: str = "staging_branch") -> str:
    text = str(value or "").strip()
    if not text or not _BRANCH_RE.fullmatch(text):
        raise StageSafetyError(f"{label} is invalid: {value!r}")
    if ".." in text or text.startswith("/") or text.endswith("/"):
        raise StageSafetyError(f"{label} is unsafe: {value!r}")
    lowered = text.casefold()
    if lowered in PROHIBITED_STAGING_BRANCHES or lowered.startswith("refs/heads/main"):
        raise StageProductionTargetError(
            f"staging branch targets production: {text!r}"
        )
    if text == DEFAULT_BASE_PIN or lowered == DEFAULT_BASE_PIN.casefold():
        raise StageProductionTargetError(
            "staging branch must not equal the previous public pin"
        )
    return text


def normalize_sha256(value: Any, *, name: str = "sha256") -> str:
    text = str(value or "").strip().casefold()
    text = text.removeprefix("sha256:")
    if not _SHA256_RE.fullmatch(text):
        raise StageReceiptError(f"{name} must be a 64-character lowercase hex digest")
    return text


def assert_operations_additive(operations: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    unexpected: list[str] = []
    for raw in operations:
        op = str(raw or "").strip().casefold().replace("-", "_")
        if not op:
            continue
        if op in FORBIDDEN_OPERATIONS or op.startswith("delete") or "force" in op:
            raise StageSafetyError(
                f"operation is forbidden for state-laws staging: {raw!r}"
            )
        if "visibility" in op or "history" in op:
            raise StageSafetyError(
                f"visibility/history mutations are impossible via staging: {raw!r}"
            )
        if op not in ALLOWED_OPERATIONS:
            unexpected.append(op)
            continue
        normalized.append(op)
    if unexpected:
        raise StageSafetyError(
            "unexpected staging operations: " + ", ".join(sorted(set(unexpected)))
        )
    if AUTHORIZED_OPERATION not in normalized and "add_only_upload" not in normalized:
        raise StageSafetyError("stage plan requires an additive upload operation")
    return tuple(sorted(set(normalized)))


def assert_mutation_authorized(
    *,
    authorize_mutation: bool,
    authorization_env: str = AUTHORIZATION_ENV,
    environ: Mapping[str, str] | None = None,
) -> None:
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
# Candidate + plan
# ---------------------------------------------------------------------------


def load_candidate_report(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Load and bind the sealed LCR-039 candidate evidence root."""

    target = Path(path) if path is not None else default_candidate_path(repo_root)
    if not target.is_file():
        raise StageReceiptError(f"sealed candidate report is missing: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StageReceiptError(f"cannot read candidate report: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise StageReceiptError("candidate report must be a JSON object")
    report = dict(payload)
    schema = receipt_schema_of(report)
    if not schema or not receipt_schema_is_known(schema):
        raise StageReceiptError(
            f"candidate report has unknown schema: {schema or '<missing>'}"
        )
    computed = publication_digest(report)
    declared = str(
        report.get("digest")
        or report.get("content_digest")
        or report.get("report_digest_sha256")
        or ""
    )
    if not declared or normalize_sha256(declared, name="candidate.digest") != computed:
        raise StageReceiptError(
            "candidate report digest is not the canonical payload hash"
        )
    bound = str(report.get("final_manifest_digest") or "")
    if normalize_sha256(bound, name="candidate.final_manifest_digest") != computed:
        raise StageReceiptError(
            "candidate final_manifest_digest does not bind the report digest"
        )
    repo = normalize_dataset_id(
        str(report.get("dataset_repo_id") or ""), label="candidate.dataset_repo_id"
    )
    if repo != DEFAULT_DATASET_REPO:
        raise StageReceiptError(f"candidate target is not authorized: {repo}")
    files = list((report.get("upload_manifest") or {}).get("files") or ())
    if not files:
        raise StageReceiptError("candidate upload manifest is empty")
    return report


def candidate_upload_files(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for raw in (candidate.get("upload_manifest") or {}).get("files") or ():
        if not isinstance(raw, Mapping):
            raise StageReceiptError("upload manifest entries must be objects")
        relative = str(raw.get("relative_path") or "").strip()
        if not relative or relative.startswith("/") or ".." in PurePosixPath(relative).parts:
            raise StageSafetyError(f"upload path is not relative: {relative!r}")
        files.append(
            {
                "content_cid": str(raw.get("content_cid") or ""),
                "family": str(raw.get("family") or ""),
                "relative_path": relative,
                "sha256": normalize_sha256(raw.get("sha256"), name=relative),
                "size_bytes": int(raw.get("size_bytes") or 0),
            }
        )
    files.sort(key=lambda item: item["relative_path"])
    return files


def load_production_candidate_report(
    *,
    repo_root: Path | str = REPOSITORY_ROOT,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Strictly validate the current LCR-084 candidate-A control receipt."""

    root = Path(repo_root).expanduser().resolve()
    target = Path(path) if path is not None else root / DEFAULT_CANDIDATE_RELPATH
    if target.is_symlink() or not target.is_file():
        raise StageReceiptError("production candidate is missing or unsafe")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StageReceiptError("production candidate is malformed") from exc
    if type(payload) is not dict:
        raise StageReceiptError("production candidate must be an object")
    try:
        from scripts.ops.legal_data import build_state_laws_hf_release as builder

        checked = builder.check_production_candidate_report(
            payload,
            repo_root=root,
            remeasure_production_evidence=False,
        )
        binding = builder.check_production_candidate_publication_binding(
            payload, phase=PUBLICATION_PHASE
        )
    except Exception as exc:
        raise StageReceiptError(
            f"LCR-084 candidate-A validation failed: {exc}"
        ) from exc
    if checked.get("valid") is not True or binding is not None:
        raise StageReceiptError("LCR-084 staging candidate is not exact candidate A")
    return payload


def build_canonical_staging_plan(
    *,
    release_root: Path | str,
    candidate: Mapping[str, Any],
    audited_parent_commit: str,
    staging_branch: str = DEFAULT_STAGING_BRANCH,
    existing_remote_paths: Sequence[str] = (),
    existing_remote_digests: Mapping[str, str] | None = None,
) -> tuple[StateLawsPublicationPackage, HuggingFaceReleasePublisher, PublicationPlan]:
    """Build the exact package-backed staging plan without network contact."""

    branch = normalize_staging_branch(staging_branch)
    parent = require_immutable_revision(
        audited_parent_commit, name="audited_parent_commit"
    )
    package = prepare_state_laws_publication_package(release_root)
    release_digest = normalize_sha256(
        candidate.get("manifest_digest"), name="candidate.manifest_digest"
    )
    if package.manifest_digest != release_digest:
        raise StageReceiptError(
            "LCR-084 candidate and publication package manifest differ"
        )
    dry_run = plan_state_laws_staging_publication_dry_run(
        package.output_root,
        staging_branch=branch,
        existing_remote_paths=existing_remote_paths,
        existing_remote_digests=existing_remote_digests,
        audited_parent_commit=parent,
    )
    publisher = HuggingFaceReleasePublisher(profile=dry_run.profile)
    plan = dry_run.plan
    if (
        plan.repository_id != DEFAULT_DATASET_REPO
        or plan.release_sha256 != package.manifest_digest
        or plan.target_revision != branch
        or plan.audited_parent_commit != parent
    ):
        raise StageReceiptError("canonical staging plan identity drifted")
    return package, publisher, plan


def load_publication_approval(
    path: Path | str,
    *,
    expected_plan_digest: str,
) -> PublicationApproval:
    """Load one human approval without ever accepting credentials on argv."""

    target = Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file():
        raise StageAuthorizationError("publication approval is missing or unsafe")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StageAuthorizationError("publication approval is malformed") from exc
    if type(payload) is not dict:
        raise StageAuthorizationError("publication approval must be an object")
    allowed = {
        "approval_id",
        "approver",
        "credentials_scope",
        "max_cost_usd",
        "max_upload_bytes",
        "notes",
        "plan_digest",
    }
    if set(payload) - allowed:
        raise StageAuthorizationError("publication approval has unexpected fields")
    try:
        approval = PublicationApproval(
            approver=payload["approver"],
            plan_digest=payload["plan_digest"],
            max_cost_usd=payload["max_cost_usd"],
            max_upload_bytes=payload["max_upload_bytes"],
            credentials_scope=payload["credentials_scope"],
            approval_id=payload["approval_id"],
            notes=payload.get("notes", ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StageAuthorizationError("publication approval failed validation") from exc
    if approval.plan_digest != normalize_sha256(
        expected_plan_digest, name="expected_plan_digest"
    ):
        raise StageAuthorizationError("publication approval binds another plan")
    return approval


def staging_policy_proof_digest(
    *, candidate: Mapping[str, Any], plan: PublicationPlan
) -> str:
    """Build the non-authorizing exact candidate/phase/plan binding."""

    return canonical_legal_corpora_policy_proof_digest(
        phase=PUBLICATION_PHASE,
        candidate_manifest_digest=normalize_sha256(
            candidate.get("report_digest_sha256"),
            name="candidate.report_digest_sha256",
        ),
        plan=plan,
    )


def canonical_plan_inventory(plan: PublicationPlan) -> list[dict[str, Any]]:
    rows = [dict(item.to_dict()) for item in plan.operations]
    rows.sort(key=lambda item: str(item["remote_path"]))
    if not rows or len({str(item["remote_path"]) for item in rows}) != len(rows):
        raise StageReceiptError("canonical staging plan is empty or duplicates paths")
    if any(item.get("operation") != "add" for item in rows):
        raise StageSafetyError("canonical staging plan is not add-only")
    return rows


def build_canonical_staging_dry_run_receipt(
    *,
    candidate: Mapping[str, Any],
    plan: PublicationPlan,
) -> dict[str, Any]:
    """Return a secret/path-free non-authorizing receipt for plan review."""

    candidate_digest = normalize_sha256(
        candidate.get("report_digest_sha256"), name="candidate.report_digest"
    )
    release_digest = normalize_sha256(
        candidate.get("manifest_digest"), name="candidate.manifest_digest"
    )
    if plan.release_sha256 != release_digest:
        raise StageReceiptError("staging plan does not bind the candidate release")
    operations = canonical_plan_inventory(plan)
    proof_digest = staging_policy_proof_digest(candidate=candidate, plan=plan)
    receipt = {
        "schema": REPORT_SCHEMA,
        "receipt_kind": RECEIPT_KIND,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "status": "dry_run_only",
        "fixture_only": False,
        "dirty": False,
        "dataset_repo_id": plan.repository_id,
        "target": plan.repository_id,
        "staging_branch": plan.target_revision,
        "audited_parent_commit": plan.audited_parent_commit,
        "base_pin": plan.audited_parent_commit,
        "staging_revision": None,
        "staging_sha": None,
        "final_manifest_digest": candidate_digest,
        "release_manifest_digest": release_digest,
        "plan_digest": plan.plan_digest,
        "policy_proof_digest": proof_digest,
        "operations": operations,
        "uploaded": [],
        "skipped": list(plan.skipped_exact_matches),
        "unexpected_operations": [],
        "remote_mutation_attempted": False,
        "remote_write_performed": False,
        "gate_invoked_before_mutation": False,
        "secrets_persisted": False,
        "local_paths_persisted": False,
    }
    digest = publication_digest(receipt)
    receipt["canonical_digest"] = digest
    receipt["content_digest"] = digest
    reject_credentials_in_payload(receipt, label="canonical_staging_dry_run")
    assert_no_secrets_or_absolute_paths(receipt, label="canonical_staging_dry_run")
    return receipt


def build_canonical_staging_live_receipt(
    *,
    candidate: Mapping[str, Any],
    plan: PublicationPlan,
    control_bundle: StateLawsStagingControlBundle,
    branch_receipt: CanonicalLegalCorporaMutationReceipt,
    commit_receipt: CanonicalLegalCorporaMutationReceipt,
) -> dict[str, Any]:
    """Seal the two independently authorized staging mutations."""

    if type(branch_receipt) is not CanonicalLegalCorporaMutationReceipt or type(
        commit_receipt
    ) is not CanonicalLegalCorporaMutationReceipt:
        raise StageReceiptError("canonical staging mutation receipts are required")
    operations = canonical_plan_inventory(plan)
    candidate_digest = normalize_sha256(
        candidate.get("report_digest_sha256"), name="candidate.report_digest"
    )
    release_digest = normalize_sha256(
        candidate.get("manifest_digest"), name="candidate.manifest_digest"
    )
    proof_digest = normalize_sha256(
        control_bundle.policy_proof_digest, name="policy_proof_digest"
    )
    if (
        control_bundle.candidate_manifest_digest != candidate_digest
        or control_bundle.release_manifest_digest != release_digest
        or control_bundle.plan_digest != plan.plan_digest
        or control_bundle.staging_branch != plan.target_revision
    ):
        raise StageReceiptError("staging controls differ from the exact plan")
    branch = branch_receipt.to_dict()
    commit = commit_receipt.to_dict()
    common = {
        "phase": PUBLICATION_PHASE,
        "operation": AUTHORIZED_OPERATION,
        "repository_id": plan.repository_id,
        "revision": plan.target_revision,
        "parent_commit": plan.audited_parent_commit,
        "plan_digest": plan.plan_digest,
        "release_manifest_digest": release_digest,
        "policy_proof_digest": proof_digest,
        "runtime_authorized": True,
    }
    for label, observed, method in (
        ("branch", branch, "create_branch"),
        ("commit", commit, "create_commit"),
    ):
        expected = dict(common)
        expected["method"] = method
        if any(observed.get(key) != value for key, value in expected.items()):
            raise StageReceiptError(
                f"canonical {label} receipt differs from the staging plan"
            )
    if (
        branch["resulting_commit_sha"] != plan.audited_parent_commit
        or commit["resulting_commit_sha"] == plan.audited_parent_commit
        or branch["approval_id"] == commit["approval_id"]
    ):
        raise StageReceiptError(
            "staging branch and commit must be distinct one-shot authorizations"
        )
    staging_revision = require_immutable_revision(
        commit["resulting_commit_sha"], name="staging_revision"
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
    receipt = {
        "schema": REPORT_SCHEMA,
        "receipt_kind": RECEIPT_KIND,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "status": "passed",
        "fixture_only": False,
        "dirty": False,
        "dataset_repo_id": plan.repository_id,
        "target": plan.repository_id,
        "staging_branch": plan.target_revision,
        "audited_parent_commit": plan.audited_parent_commit,
        "base_pin": plan.audited_parent_commit,
        "staging_revision": staging_revision,
        "staging_sha": staging_revision,
        "final_manifest_digest": candidate_digest,
        "release_manifest_digest": release_digest,
        "plan_digest": plan.plan_digest,
        "policy_proof_digest": proof_digest,
        "branch_mutation": branch,
        "commit_mutation": commit,
        "operations": operations,
        "uploaded": uploaded,
        "skipped": list(plan.skipped_exact_matches),
        "unexpected_operations": [],
        "remote_mutation_attempted": True,
        "remote_write_performed": True,
        "gate_invoked_before_mutation": True,
        "secrets_persisted": False,
        "local_paths_persisted": False,
    }
    digest = publication_digest(receipt)
    receipt["canonical_digest"] = digest
    receipt["content_digest"] = digest
    return check_canonical_staging_receipt(receipt, require_live=True)


def execute_canonical_staging_release(
    *,
    release_root: Path | str,
    candidate: Mapping[str, Any],
    audited_parent_commit: str,
    staging_branch: str,
    branch_approval: PublicationApproval,
    commit_approval: PublicationApproval,
    repository_root: Path | str = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Create the staging branch and commit via two one-shot runtime calls."""

    package, publisher, first_plan = build_canonical_staging_plan(
        release_root=release_root,
        candidate=candidate,
        audited_parent_commit=audited_parent_commit,
        staging_branch=staging_branch,
    )
    if branch_approval.plan_digest != first_plan.plan_digest:
        raise StageAuthorizationError("branch approval does not bind the first plan")
    controls = materialize_state_laws_staging_controls(
        package,
        first_plan,
        repository_root=repository_root,
    )
    branch_result = execute_staging_mutation(
        publisher=publisher,
        plan=first_plan,
        approval=branch_approval,
        local_root=package.output_root,
        mutation_method="create_branch",
        policy_proof_digest=controls.policy_proof_digest,
    )
    branch_parent = require_immutable_revision(
        branch_result.resulting_commit_sha, name="staging_branch_parent"
    )
    package_after, publisher_after, commit_plan = build_canonical_staging_plan(
        release_root=release_root,
        candidate=candidate,
        audited_parent_commit=branch_parent,
        staging_branch=staging_branch,
    )
    controls_after = materialize_state_laws_staging_controls(
        package_after,
        commit_plan,
        repository_root=repository_root,
    )
    if (
        package_after != package
        or commit_plan.plan_digest != first_plan.plan_digest
        or controls_after != controls
        or commit_approval.plan_digest != commit_plan.plan_digest
        or branch_approval.approval_id == commit_approval.approval_id
    ):
        raise StageAuthorizationError(
            "rebuilt staging plan or independent commit approval drifted"
        )
    commit_result = execute_staging_mutation(
        publisher=publisher_after,
        plan=commit_plan,
        approval=commit_approval,
        local_root=package_after.output_root,
        mutation_method="create_commit",
        policy_proof_digest=controls_after.policy_proof_digest,
    )
    return build_canonical_staging_live_receipt(
        candidate=candidate,
        plan=commit_plan,
        control_bundle=controls_after,
        branch_receipt=branch_result,
        commit_receipt=commit_result,
    )


def check_canonical_staging_receipt(
    receipt: Mapping[str, Any], *, require_live: bool = True
) -> dict[str, Any]:
    """Verify generic staging evidence without rebuilding or mutating it."""

    if not isinstance(receipt, Mapping):
        raise StageReceiptError("canonical staging receipt must be an object")
    report = dict(receipt)
    if (
        report.get("schema") != REPORT_SCHEMA
        or report.get("receipt_kind") != RECEIPT_KIND
        or report.get("task_id") != TASK_ID
        or report.get("program_id") != PROGRAM_ID
        or report.get("fixture_only") is not False
        or report.get("dirty") is not False
        or report.get("dataset_repo_id") != DEFAULT_DATASET_REPO
        or report.get("target") != DEFAULT_DATASET_REPO
        or report.get("unexpected_operations") != []
        or report.get("secrets_persisted") is not False
        or report.get("local_paths_persisted") is not False
    ):
        raise StageReceiptError("canonical staging identity/safety flags drifted")
    normalize_staging_branch(str(report.get("staging_branch") or ""))
    require_immutable_revision(
        report.get("audited_parent_commit"), name="audited_parent_commit"
    )
    if report.get("base_pin") != report.get("audited_parent_commit"):
        raise StageReceiptError("canonical staging base pin drifted")
    for field in (
        "final_manifest_digest",
        "release_manifest_digest",
        "plan_digest",
        "policy_proof_digest",
    ):
        normalize_sha256(report.get(field), name=field)
    declared = normalize_sha256(
        report.get("canonical_digest") or report.get("content_digest"),
        name="canonical_digest",
    )
    if publication_digest(report) != declared:
        raise StageReceiptError("canonical staging receipt digest mismatch")
    operations = report.get("operations")
    if not isinstance(operations, list) or not operations:
        raise StageReceiptError("canonical staging receipt has no operations")
    expected: set[tuple[str, str, int]] = set()
    for item in operations:
        if not isinstance(item, Mapping) or item.get("operation") != "add":
            raise StageSafetyError("canonical staging operation is not an add")
        path = str(item.get("remote_path") or "")
        if not path or path.startswith("/") or ".." in PurePosixPath(path).parts:
            raise StageSafetyError("canonical staging remote path is unsafe")
        expected.add(
            (
                path,
                normalize_sha256(item.get("sha256"), name=f"{path}.sha256"),
                int(item.get("size_bytes", -1)),
            )
        )
    if len(expected) != len(operations) or any(size < 0 for _, _, size in expected):
        raise StageReceiptError("canonical staging operation inventory is invalid")
    if require_live:
        if (
            report.get("status") != "passed"
            or report.get("remote_mutation_attempted") is not True
            or report.get("remote_write_performed") is not True
            or report.get("gate_invoked_before_mutation") is not True
        ):
            raise StageReceiptError("canonical staging receipt is not live passed evidence")
        require_immutable_revision(
            report.get("staging_revision"), name="staging_revision"
        )
        if report.get("staging_sha") != report.get("staging_revision"):
            raise StageReceiptError("canonical staging SHA aliases drifted")
        uploaded = report.get("uploaded")
        if not isinstance(uploaded, list):
            raise StageReceiptError("canonical staging receipt lacks uploaded files")
        observed = {
            (
                str(item.get("remote_path") or ""),
                normalize_sha256(item.get("sha256"), name="uploaded.sha256"),
                int(item.get("size_bytes", -1)),
            )
            for item in uploaded
            if isinstance(item, Mapping)
        }
        if observed != expected or len(observed) != len(uploaded):
            raise StageReceiptError("canonical staging upload differs from its plan")
        branch = report.get("branch_mutation")
        commit = report.get("commit_mutation")
        if not isinstance(branch, Mapping) or not isinstance(commit, Mapping):
            raise StageReceiptError("canonical staging mutation receipts are missing")
        common = {
            "operation": AUTHORIZED_OPERATION,
            "parent_commit": report["audited_parent_commit"],
            "phase": PUBLICATION_PHASE,
            "plan_digest": report["plan_digest"],
            "policy_proof_digest": report["policy_proof_digest"],
            "release_manifest_digest": report["release_manifest_digest"],
            "repository_id": report["dataset_repo_id"],
            "revision": report["staging_branch"],
            "runtime_authorized": True,
        }
        for label, mutation, method in (
            ("branch", branch, "create_branch"),
            ("commit", commit, "create_commit"),
        ):
            expected_mutation = dict(common)
            expected_mutation["method"] = method
            if any(
                mutation.get(key) != value
                for key, value in expected_mutation.items()
            ):
                raise StageReceiptError(
                    f"canonical {label} mutation binding drifted"
                )
            normalize_sha256(
                mutation.get("payload_digest"),
                name=f"{label}.payload_digest",
            )
        if (
            branch.get("resulting_commit_sha") != report["audited_parent_commit"]
            or commit.get("resulting_commit_sha") != report["staging_revision"]
            or not str(branch.get("approval_id") or "")
            or not str(commit.get("approval_id") or "")
            or branch.get("approval_id") == commit.get("approval_id")
        ):
            raise StageReceiptError(
                "canonical staging mutations are not independent and ordered"
            )
    elif report.get("status") not in {"dry_run_only", "passed"}:
        raise StageReceiptError("canonical staging dry-run status drifted")
    reject_credentials_in_payload(report, label="canonical_staging_receipt")
    assert_no_secrets_or_absolute_paths(report, label="canonical_staging_receipt")
    return report


def classify_upload_files(
    files: Sequence[Mapping[str, Any]],
    *,
    remote_inventory: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split candidate files into uploaded vs already-present skipped hashes."""

    remote = {
        str(path): normalize_sha256(digest, name=f"remote[{path}]")
        for path, digest in dict(remote_inventory or {}).items()
    }
    uploaded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in files:
        entry = dict(item)
        path = str(entry["relative_path"])
        digest = str(entry["sha256"])
        if remote.get(path) == digest:
            entry["operation"] = "skip_identical"
            skipped.append(entry)
        else:
            entry["operation"] = AUTHORIZED_OPERATION
            uploaded.append(entry)
    return uploaded, skipped


def planned_staging_sha(
    *,
    target: str,
    staging_branch: str,
    base_pin: str,
    manifest_digest: str,
    uploaded_hashes: Sequence[str],
    skipped_hashes: Sequence[str],
) -> str:
    """Derive a deterministic 40-hex identity for the planned staging revision."""

    payload = {
        "base_pin": base_pin,
        "manifest_digest": manifest_digest,
        "skipped_hashes": list(skipped_hashes),
        "staging_branch": staging_branch,
        "target": target,
        "task_id": TASK_ID,
        "uploaded_hashes": list(uploaded_hashes),
    }
    digest = hashlib.sha1(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()
    return require_immutable_revision(digest, name="staging_sha")


def compact_gate_decision(decision: PublicationGateDecision) -> dict[str, Any]:
    return {
        "authorized": bool(decision.authorized),
        "dataset_repo_id": decision.dataset_repo_id,
        "invoked_before_mutation": True,
        "network_mutation_permitted": bool(decision.network_mutation_permitted),
        "operation": decision.operation,
        "passed_gates": list(decision.passed_gates),
        "phase": decision.phase,
        "previous_public_pin": decision.previous_public_pin,
        "reason_codes": list(decision.reason_codes),
        "required_gates": list(decision.required_gates),
        "task_id": GATE_TASK_ID,
    }


# ---------------------------------------------------------------------------
# LCR-074 gate — must run before the first Hub mutation
# ---------------------------------------------------------------------------


def reset_gate_invocations() -> None:
    _GATE_INVOCATIONS.clear()


def gate_invocations() -> tuple[dict[str, Any], ...]:
    return tuple(_GATE_INVOCATIONS)


def build_state_staging_gate_request(
    *,
    manifest_digest: str,
    staging_branch: str = DEFAULT_STAGING_BRANCH,
    authorize_mutation: bool = False,
) -> dict[str, Any]:
    """Construct the offline LCR-074 request bound to the candidate digest."""

    request = example_authorized_request(
        PUBLICATION_PHASE, manifest_digest=manifest_digest
    )
    request["phase"] = PUBLICATION_PHASE
    request["operation"] = AUTHORIZED_OPERATION
    request["dataset_repo_id"] = DEFAULT_DATASET_REPO
    request["final_manifest_digest"] = manifest_digest
    request["previous_public_pin"] = DEFAULT_BASE_PIN
    request["staging_branch"] = staging_branch
    # The gate request always asks "would this mutation be authorized?"
    # Dry-run still evaluates the full LCR-074 contract; it just never writes.
    request["authorize_mutation"] = True
    request["credentials_environment_only"] = True
    request["secret_redacted"] = True
    return request


def invoke_state_staging_gate(
    request: Mapping[str, Any] | None = None,
    *,
    manifest_digest: str | None = None,
    staging_branch: str = DEFAULT_STAGING_BRANCH,
    authorize_mutation: bool = False,
    environ: Mapping[str, str] | None = None,
) -> PublicationGateDecision:
    """Invoke the LCR-074 gate for the state staging phase.

    This is the required preflight. Callers must invoke it before any Hub
    write callback. The invocation is recorded so tests can prove order.
    """

    payload = dict(
        request
        if request is not None
        else build_state_staging_gate_request(
            manifest_digest=manifest_digest or ("0" * 64),
            staging_branch=staging_branch,
            authorize_mutation=authorize_mutation,
        )
    )
    payload.setdefault("phase", PUBLICATION_PHASE)
    payload.setdefault("operation", AUTHORIZED_OPERATION)
    payload.setdefault("dataset_repo_id", DEFAULT_DATASET_REPO)
    if payload.get("phase") != PUBLICATION_PHASE:
        raise StageGateError(
            f"entrypoint must invoke LCR-074 for {PUBLICATION_PHASE}, "
            f"got {payload.get('phase')!r}"
        )
    decision = evaluate_publication_gate(payload, environ=environ)
    record = {
        "authorized": bool(decision.authorized),
        "invoked_before_mutation": True,
        "operation": decision.operation,
        "phase": decision.phase,
        "task_id": GATE_TASK_ID,
    }
    _GATE_INVOCATIONS.append(record)
    return decision


def require_gate_invoked_before_mutation() -> None:
    if not _GATE_INVOCATIONS:
        raise StageGateError(
            "LCR-074 state_staging gate was not invoked before Hub mutation"
        )
    last = _GATE_INVOCATIONS[-1]
    if last.get("phase") != PUBLICATION_PHASE:
        raise StageGateError(
            "LCR-074 was invoked for the wrong phase before mutation: "
            f"{last.get('phase')!r}"
        )


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def build_staging_receipt(
    *,
    repo_root: Path | str | None = None,
    candidate: Mapping[str, Any] | None = None,
    remote_inventory: Mapping[str, str] | None = None,
    staging_branch: str = DEFAULT_STAGING_BRANCH,
    target: str = DEFAULT_DATASET_REPO,
    base_pin: str = DEFAULT_BASE_PIN,
    dry_run: bool = True,
    authorize_mutation: bool = False,
    gate_request: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    staging_sha: str | None = None,
    mutation_executed: bool = False,
    unexpected_operations: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build the sealed additive staging-upload receipt.

    The LCR-074 gate is invoked here, before any mutation field is recorded
    and before a live upload callback may run.
    """

    reset_gate_invocations()
    report = dict(candidate) if candidate is not None else load_candidate_report(
        repo_root=repo_root
    )
    target_repo = normalize_dataset_id(target)
    branch = normalize_staging_branch(staging_branch)
    pin = require_immutable_revision(base_pin, name="base_pin")
    if pin != DEFAULT_BASE_PIN:
        raise StageSafetyError(
            f"base pin must remain the sealed previous public pin {DEFAULT_BASE_PIN}"
        )

    candidate_digest = normalize_sha256(
        report.get("final_manifest_digest") or report.get("digest"),
        name="final_manifest_digest",
    )
    packaging_digest = normalize_sha256(
        report.get("manifest_digest") or candidate_digest,
        name="manifest_digest",
    )
    files = candidate_upload_files(report)
    uploaded, skipped = classify_upload_files(files, remote_inventory=remote_inventory)
    uploaded_hashes = sorted({item["sha256"] for item in uploaded})
    skipped_hashes = sorted({item["sha256"] for item in skipped})
    operations = assert_operations_additive(
        [item["operation"] for item in uploaded + skipped] or [AUTHORIZED_OPERATION]
    )
    unexpected = list(unexpected_operations or ())
    if unexpected:
        raise StageSafetyError(
            "unexpected operations are forbidden: " + ", ".join(unexpected)
        )

    decision = invoke_state_staging_gate(
        gate_request,
        manifest_digest=candidate_digest,
        staging_branch=branch,
        authorize_mutation=authorize_mutation,
        environ=environ,
    )
    policy_request = example_authorized_staging_request(manifest_digest=candidate_digest)
    policy_request["staging_branch"] = branch
    policy_request["previous_public_pin"] = pin
    policy_request["authorize_mutation"] = True
    policy_decision = evaluate_live_mutation(policy_request, environ=environ)

    planned_sha = staging_sha or planned_staging_sha(
        target=target_repo,
        staging_branch=branch,
        base_pin=pin,
        manifest_digest=candidate_digest,
        uploaded_hashes=uploaded_hashes,
        skipped_hashes=skipped_hashes,
    )
    planned_sha = require_immutable_revision(planned_sha, name="staging_sha")

    compact_files = [
        {
            "operation": item["operation"],
            "relative_path": item["relative_path"],
            "sha256": item["sha256"],
        }
        for item in (*uploaded, *skipped)
    ]
    receipt: dict[str, Any] = {
        "acceptance": {
            "base_pin_named": True,
            "credentials_environment_only": True,
            "gate_invoked_before_mutation": True,
            "lcr074_state_staging_phase": True,
            "manifest_digest_named": True,
            "no_absolute_path_or_secret": True,
            "staging_sha_named": True,
            "target_named": True,
            "unexpected_operations_zero": True,
            "uploaded_and_skipped_hashes_named": True,
        },
        "additive_only": True,
        "authorize_mutation": bool(authorize_mutation and not dry_run),
        "base_pin": pin,
        "base_revision": pin,
        "candidate_path": DEFAULT_CANDIDATE_RELPATH.as_posix(),
        "candidate_task_id": "LCR-039",
        "code_version": CODE_VERSION,
        "compact_recipe": True,
        "credentials_environment_only": True,
        "dataset_repo_id": target_repo,
        "depends_on": ["LCR-008", "LCR-039", "LCR-070", "LCR-074", "LCR-084"],
        "deletes": False,
        "dirty": False,
        "dry_run": bool(dry_run),
        "file_count": len(files),
        "files_digest": inventory_digest(compact_files),
        "fixture_only": False,
        "force_push": False,
        "goal_id": GOAL_ID,
        "legacy_files_deleted": False,
        "live_network": bool(mutation_executed),
        "multipart_plan": dict(report.get("multipart_plan") or {}),
        "mutation_executed": bool(mutation_executed),
        "network_required": False,
        "observation_time": DEFAULT_OBSERVATION_TIME,
        "operation": AUTHORIZED_OPERATION,
        "operations": list(operations),
        "packaging_manifest_digest": packaging_digest,
        "phase": PUBLICATION_PHASE,
        "previous_public_pin": pin,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "publication_gate": compact_gate_decision(decision),
        "publication_policy": {
            "authorized": bool(policy_decision.authorized),
            "operation": policy_decision.operation,
            "passed_gates": list(policy_decision.passed_gates),
            "phase": policy_decision.phase,
            "task_id": "LCR-008",
        },
        "remote_write_contacted": bool(mutation_executed),
        "report_schema": REPORT_SCHEMA,
        "rollback": {
            "additive_only": True,
            "previous_public_pin": pin,
            "rollback_target": pin,
        },
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "secret_redacted": True,
        "skipped_count": len(skipped),
        "skipped_hash_digest": inventory_digest(skipped_hashes),
        "skipped_hashes": skipped_hashes,
        "staging_branch": branch,
        "staging_revision": planned_sha,
        "staging_sha": planned_sha,
        "status": "sealed" if dry_run else "uploaded",
        "target": target_repo,
        "target_repo": target_repo,
        "task_id": TASK_ID,
        "tokens_used": False,
        "unexpected_operations": [],
        "uploaded_count": len(uploaded),
        "uploaded_hash_digest": inventory_digest(uploaded_hashes),
        "uploaded_hashes": uploaded_hashes,
        "uploads": bool(mutation_executed),
        "visibility_change": False,
        "visibility_changed": False,
    }
    receipt["final_manifest_digest"] = candidate_digest
    receipt["manifest_digest"] = packaging_digest
    digest = publication_digest(receipt)
    receipt["content_digest"] = digest
    receipt["digest"] = digest
    receipt["report_digest_sha256"] = digest
    encoded = _canonical_report_bytes(receipt)
    if len(encoded) > MAX_REPORT_BYTES:
        raise StageReceiptError(
            f"staging receipt exceeds {MAX_REPORT_BYTES} bytes ({len(encoded)})"
        )
    assert_no_secrets_or_absolute_paths(receipt, label="staging-upload")
    if not receipt_schema_is_known(receipt_schema_of(receipt)):
        raise StageReceiptError("staging receipt schema is not publication-bindable")
    return receipt


def write_staging_receipt(
    receipt: Mapping[str, Any],
    *,
    path: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> Path:
    target = Path(path) if path is not None else default_report_path(repo_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_report_bytes(receipt)
    if len(encoded) > MAX_REPORT_BYTES:
        raise StageReceiptError(
            f"staging receipt exceeds {MAX_REPORT_BYTES} bytes ({len(encoded)})"
        )
    assert_no_secrets_or_absolute_paths(receipt, label="staging-upload")
    temporary = target.with_name(f".{target.name}.partial")
    temporary.write_bytes(encoded)
    temporary.replace(target)
    return target


def check_staging_receipt(
    receipt: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Rebuild the dry-run receipt and compare it to the sealed artifact."""

    expected = build_staging_receipt(repo_root=repo_root, dry_run=True)
    observed = (
        dict(receipt)
        if receipt is not None
        else json.loads(default_report_path(repo_root).read_text(encoding="utf-8"))
    )
    mismatches: list[str] = []
    if _canonical_report_bytes(expected) != _canonical_report_bytes(observed):
        for key in (
            "acceptance",
            "base_pin",
            "dataset_repo_id",
            "final_manifest_digest",
            "manifest_digest",
            "operation",
            "operations",
            "phase",
            "previous_public_pin",
            "skipped_hashes",
            "staging_branch",
            "staging_revision",
            "staging_sha",
            "status",
            "target",
            "task_id",
            "unexpected_operations",
            "uploaded_hashes",
        ):
            if expected.get(key) != observed.get(key):
                mismatches.append(key)
        if not mismatches:
            mismatches.append("canonical_bytes")
    acceptance = expected.get("acceptance") or {}
    failed = [name for name, ok in acceptance.items() if ok is not True]
    if failed:
        mismatches.extend(f"acceptance.{name}" for name in failed)
    if observed.get("unexpected_operations") not in ([], None):
        mismatches.append("unexpected_operations")
    if publication_digest(observed) != str(observed.get("digest") or ""):
        mismatches.append("publication_digest")
    if not gate_invocations():
        mismatches.append("gate_invoked_before_mutation")
    if mismatches:
        raise StageReceiptError(
            "state-laws staging receipt check failed: " + ", ".join(mismatches)
        )
    return {
        "acceptance": acceptance,
        "base_pin": expected["base_pin"],
        "check": "pass",
        "digest": expected["digest"],
        "final_manifest_digest": expected["final_manifest_digest"],
        "goal_id": GOAL_ID,
        "manifest_digest": expected["manifest_digest"],
        "ok": True,
        "staging_sha": expected["staging_sha"],
        "target": expected["target"],
        "task_id": TASK_ID,
        "unexpected_operations": [],
        "uploaded_count": expected["uploaded_count"],
        "skipped_count": expected["skipped_count"],
    }


def run_receipt_self_check(*, repo_root: Path | str | None = None) -> dict[str, Any]:
    """Rebuild, seal, and verify the offline staging receipt."""

    first = build_staging_receipt(repo_root=repo_root, dry_run=True)
    second = build_staging_receipt(repo_root=repo_root, dry_run=True)
    if _canonical_report_bytes(first) != _canonical_report_bytes(second):
        raise StageReceiptError("two staging receipt rebuilds were not identical")
    path = write_staging_receipt(first, repo_root=repo_root)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    check = check_staging_receipt(on_disk, repo_root=repo_root)
    payload = {
        "acceptance": first["acceptance"],
        "base_pin": first["base_pin"],
        "check": "pass",
        "digest": first["digest"],
        "final_manifest_digest": first["final_manifest_digest"],
        "goal_id": GOAL_ID,
        "manifest_digest": first["manifest_digest"],
        "ok": True,
        "staging_sha": first["staging_sha"],
        "target": first["target"],
        "task_id": TASK_ID,
        "two_build_identical": True,
        "uploaded_count": first["uploaded_count"],
        "skipped_count": first["skipped_count"],
        "unexpected_operations": [],
    }
    payload.update({key: value for key, value in check.items() if key not in payload})
    return payload


# ---------------------------------------------------------------------------
# Live mutation (opt-in; still gate-first)
# ---------------------------------------------------------------------------


def execute_staging_mutation(
    *,
    publisher: Any,
    plan: Any,
    approval: Any,
    local_root: Path | str,
    mutation_method: str,
    policy_proof_digest: str,
    commit_message: str | None = None,
) -> Any:
    """Execute exactly one source-attested staging mutation.

    Branch creation and the subsequent commit must call this function
    separately.  The canonical publisher/runtime reopens LCR-074 evidence
    immediately before each one-shot protected write.
    """

    if mutation_method not in {"create_branch", "create_commit"}:
        raise StageSafetyError("staging permits only create_branch/create_commit")
    execute = getattr(
        publisher, "execute_canonical_legal_corpora_mutation", None
    )
    if not callable(execute):
        raise StageGateError(
            "canonical legal-corpora mutation executor is unavailable"
        )
    return execute(
        plan,
        approval=approval,
        local_root=local_root,
        publication_phase=PUBLICATION_PHASE,
        mutation_method=mutation_method,
        policy_proof_digest=policy_proof_digest,
        commit_message=commit_message,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stage_state_laws_hf_release.py",
        description=(
            "Upload the exact state-law candidate additively to an explicit "
            "staging revision (LCR-040). Invokes the LCR-074 state_staging "
            "gate before any Hub mutation. Default mode is dry-run."
        ),
    )
    parser.add_argument(
        "--check-receipt",
        action="store_true",
        help=(
            "Read and verify the existing canonical staging receipt at "
            f"{DEFAULT_REPORT_RELPATH.as_posix()}; verify target, base pin, "
            "staging SHA, manifest digest, uploaded/skipped hashes, zero "
            "unexpected operations, and no secret/local-path leakage."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Alias for --check-receipt.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan and emit a redacted receipt without remote mutation (default).",
    )
    parser.add_argument(
        "--write-receipt",
        action="store_true",
        help=f"Explicitly write {DEFAULT_REPORT_RELPATH.as_posix()}",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="Existing receipt to validate (default: canonical board path)",
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        default=None,
        help="Canonical LCR-084 candidate-A receipt",
    )
    parser.add_argument(
        "--release-root",
        type=Path,
        default=None,
        help="Completed local State Laws release root (required to plan or upload)",
    )
    parser.add_argument(
        "--branch-approval",
        type=Path,
        default=None,
        help="Human approval JSON for the one-shot branch creation",
    )
    parser.add_argument(
        "--commit-approval",
        type=Path,
        default=None,
        help="Distinct human approval JSON for the one-shot staging commit",
    )
    parser.add_argument(
        "--target-repo",
        default=DEFAULT_DATASET_REPO,
        help=f"Explicit Hub dataset id (default: {DEFAULT_DATASET_REPO})",
    )
    parser.add_argument(
        "--staging-branch",
        default=DEFAULT_STAGING_BRANCH,
        help=f"Explicit non-production staging branch (default: {DEFAULT_STAGING_BRANCH})",
    )
    parser.add_argument(
        "--base-revision",
        default=DEFAULT_BASE_PIN,
        help=f"Immutable base pin (default: {DEFAULT_BASE_PIN})",
    )
    parser.add_argument(
        "--authorize-mutation",
        action="store_true",
        help=(
            "Opt-in remote mutation; also requires "
            f"${AUTHORIZATION_ENV}. Still cannot delete/force/visibility-change."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the receipt JSON (default: stdout unless sealing).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON on stdout",
    )
    return parser


def _emit(payload: Mapping[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
        )
        return
    if payload.get("check") == "pass" or payload.get("status") == "passed":
        print(f"check: pass ({payload.get('task_id')})")
        for name, ok in sorted((payload.get("acceptance") or {}).items()):
            print(f"  {name}: {'ok' if ok else 'FAIL'}")
        print(f"target: {payload.get('target') or payload.get('dataset_repo_id')}")
        print(f"base_pin: {payload.get('base_pin') or payload.get('audited_parent_commit')}")
        print(f"staging_sha: {payload.get('staging_sha') or payload.get('staging_revision')}")
        print(f"manifest_digest: {payload.get('release_manifest_digest') or payload.get('manifest_digest')}")
        return
    print(f"task_id: {payload.get('task_id')}")
    print(f"target: {payload.get('target')}")
    print(f"staging_sha: {payload.get('staging_sha')}")
    print(f"manifest_digest: {payload.get('manifest_digest')}")


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    try:
        reject_secrets_in_argv(argv_list)
    except StageSafetyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parser = build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code or 0)

    check_receipt = bool(args.check_receipt or args.check)
    if args.dry_run and args.authorize_mutation:
        print(
            "error: --dry-run and --authorize-mutation are mutually exclusive",
            file=sys.stderr,
        )
        return 2
    dry_run = not args.authorize_mutation

    try:
        if check_receipt:
            if args.authorize_mutation or args.write_receipt:
                raise StageAuthorizationError(
                    "receipt checking is read-only and cannot authorize or write"
                )
            path = args.receipt or default_report_path()
            if path.is_symlink() or not path.is_file():
                raise StageReceiptError(f"staging receipt is missing: {path}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            checked = check_canonical_staging_receipt(payload, require_live=True)
            _emit(checked, as_json=args.json)
            return 0

        if args.release_root is None:
            raise StageReceiptError("--release-root is required to plan or upload")
        candidate = load_production_candidate_report(path=args.candidate)
        package, publisher, plan = build_canonical_staging_plan(
            release_root=args.release_root,
            candidate=candidate,
            audited_parent_commit=args.base_revision,
            staging_branch=args.staging_branch,
        )
        if publisher.repository_id != args.target_repo:
            raise StageProductionTargetError("--target-repo differs from canonical plan")
        if dry_run:
            receipt = build_canonical_staging_dry_run_receipt(
                candidate=candidate,
                plan=plan,
            )
        else:
            if args.branch_approval is None or args.commit_approval is None:
                raise StageAuthorizationError(
                    "live staging requires --branch-approval and --commit-approval"
                )
            branch_approval = load_publication_approval(
                args.branch_approval, expected_plan_digest=plan.plan_digest
            )
            commit_approval = load_publication_approval(
                args.commit_approval, expected_plan_digest=plan.plan_digest
            )
            receipt = execute_canonical_staging_release(
                release_root=package.output_root,
                candidate=candidate,
                audited_parent_commit=args.base_revision,
                staging_branch=args.staging_branch,
                branch_approval=branch_approval,
                commit_approval=commit_approval,
            )

        if args.write_receipt or args.output is not None:
            write_staging_receipt(
                receipt,
                path=args.output or default_report_path(),
            )
        if args.json or args.output is None:
            _emit(receipt, as_json=args.json)
    except (
        StageStateLawsError,
        PublicationGateError,
        PublicationGateDeniedError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
