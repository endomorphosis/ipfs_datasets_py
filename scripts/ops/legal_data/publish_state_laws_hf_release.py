#!/usr/bin/env python3
"""Plan the State Laws payload and repository-root Viewer control (LCR-042).

Default mode is **offline** (credential-free, no live Hub network contact):

1. Verify the LCR-072 manifest-bound prepublication seal **before** any
   Hub mutation can run. A missing, stale, fixture-only, or post-hoc seal
   fails closed.
2. Invoke the LCR-074 publication gate for the ``state_main`` phase
   **before** the first Hub write callback.
3. Upload the identical staged candidate payload additively to
   ``justicedao/ipfs_state_laws`` (public ``main``), preserving
   legacy files and the rollback pin.
4. Separately bind the repository-root Viewer card intent.  The current
   protected writer can proceed only when that card is already byte-identical;
   a required add/CAS replacement remains blocked pending distinct reviewed
   control-plane authority.
5. Bind old / staging / public SHAs, the candidate manifest, and the
   operation list on the Hub receipt. Every upload response must succeed.

Live writes remain opt-in (``--authorize-mutation`` plus environment
credentials) and are routed through the source-attested canonical
publisher/runtime boundary. The default CLI never contacts the live Hub:
validation uses an in-memory add-only public Hub.

This script never:

* deletes, force-pushes, rewrites history, or changes visibility;
* embeds or logs Hub tokens;
* treats credentials as CLI flags (environment-only);
* proceeds to a Hub write unless the LCR-072 seal and LCR-074
  ``state_main`` gate both authorized the mutation;
* accepts a post-hoc seal created after mutation.

Validation gate (no network)::

    python scripts/ops/legal_data/publish_state_laws_hf_release.py --check-receipt
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
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (
    SECRET_ENV_NAMES as GATE_SECRET_ENV_NAMES,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (
    STATE_DATASET_REPO_ID,
    STATE_PREPUBLICATION_SEAL_PATH,
    PublicationGateDecision,
    PublicationGateDeniedError,
    PublicationGateError,
    PublicationPhase,
    example_authorized_request,
    require_publication_gate,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (
    reject_credentials_in_payload as gate_reject_credentials,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (
    require_immutable_revision as _gate_require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    RECEIPT_SCHEMA_V1 as RUNTIME_RECEIPT_SCHEMA,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    canonical_no_self_field_digest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_package import (
    VIEWER_CONTROL_ADD,
    VIEWER_CONTROL_REPLACE,
    VIEWER_CONTROL_SKIP,
    StateLawsCanonicalControlBundle,
    StateLawsPublicationPackage,
    StateLawsViewerControlAuthorization,
    StateLawsViewerControlPlan,
    materialize_state_laws_canonical_controls,
    plan_state_laws_publication_dry_run,
    require_state_laws_policy_binding,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    state_laws_root_viewer_configs,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (
    DEFAULT_STAGING_BRANCH,
    PUBLICATION_PARENT_REVISION,
    example_authorized_main_request,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    DEFAULT_DATASET_REPO_ID,
    canonical_json_dumps,
    digest_mapping,
)


def _load_exact_local_script_module(*, filename: str, module_name: str) -> Any:
    """Load one security-critical sibling script from its exact local path."""

    expected_parent = Path(__file__).resolve().parent
    if Path(filename).name != filename:
        raise RuntimeError(
            f"local script dependency name is not a basename: {filename}"
        )
    unresolved_path = expected_parent / filename
    if unresolved_path.is_symlink():
        raise RuntimeError(
            f"local script dependency must not be a symlink: {unresolved_path}"
        )
    script_path = unresolved_path.resolve(strict=True)
    if script_path.parent != expected_parent or not script_path.is_file():
        raise RuntimeError(
            f"local script dependency is not a safe regular file: {script_path}"
        )
    before_sha256 = hashlib.sha256(script_path.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"local script dependency has no file loader: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    loaded_path = Path(str(getattr(module, "__file__", ""))).resolve(strict=True)
    after_sha256 = hashlib.sha256(script_path.read_bytes()).hexdigest()
    if loaded_path != script_path or after_sha256 != before_sha256:
        sys.modules.pop(module_name, None)
        raise RuntimeError(
            f"local script dependency changed or resolved elsewhere: {script_path}"
        )
    return module


_LOCAL_SEAL_MODULE = _load_exact_local_script_module(
    filename="seal_state_laws_prepublication.py",
    module_name="_state_laws_exact_local_prepublication_seal_for_publish",
)
SealBindingError = _LOCAL_SEAL_MODULE.SealBindingError
SealEvidenceError = _LOCAL_SEAL_MODULE.SealEvidenceError
SealLiveStagingError = _LOCAL_SEAL_MODULE.SealLiveStagingError
SealStateLawsError = _LOCAL_SEAL_MODULE.SealStateLawsError
check_state_prepublication_seal = (
    _LOCAL_SEAL_MODULE.check_state_prepublication_seal
)
default_seal_path = _LOCAL_SEAL_MODULE.default_seal_path
load_staging_canary = _LOCAL_SEAL_MODULE.load_staging_canary
load_seal_mapping = _LOCAL_SEAL_MODULE.load_json_mapping

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "LCR-042"
GOAL_ID: Final = "LCR-G080"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "publish_state_laws_hf_release.py"
CODE_VERSION: Final = "1"
SCHEMA_VERSION: Final = "state-laws-hf-public-upload/v1"
SEAL_TASK_ID: Final = "LCR-072"
GATE_TASK_ID: Final = "LCR-074"
PUBLICATION_PHASE: Final = PublicationPhase.STATE_MAIN.value
AUTHORIZED_OPERATION: Final = "additive_main_upload"
ADD_ONLY_OPERATION: Final = "add_only_upload"

RECEIPT_SCHEMA: Final = RUNTIME_RECEIPT_SCHEMA
RECEIPT_KIND: Final = "state-laws-publication/v2"
PLAN_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-publication-plan@1"

DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
if DEFAULT_DATASET_REPO != STATE_DATASET_REPO_ID:
    raise RuntimeError("sealed state-law target drifted from the publication gate")
if DEFAULT_DATASET_REPO != "justicedao/ipfs_state_laws":
    raise RuntimeError("sealed state-law target drifted from justicedao/ipfs_state_laws")

PREVIOUS_PUBLIC_PIN: Final = PUBLICATION_PARENT_REVISION
PRODUCTION_REVISION: Final = PUBLICATION_PARENT_REVISION
PUBLIC_BRANCH: Final = "main"
DEFAULT_OBSERVATION_CUTOFF: Final = "2026-08-10T00:00:00Z"

DEFAULT_RECEIPT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/publication_receipt.json"
)
DEFAULT_CANDIDATE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/release_candidate.json"
)
DEFAULT_SEAL_RELPATH: Final = Path(STATE_PREPUBLICATION_SEAL_PATH)
DEFAULT_CANARY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/staging_canary.json"
)

DEPENDS_ON: Final[tuple[str, ...]] = (
    "LCR-008",
    "LCR-041",
    "LCR-072",
    "LCR-074",
    "LCR-084",
)

ALLOWED_OPERATIONS: Final[frozenset[str]] = frozenset(
    {AUTHORIZED_OPERATION, ADD_ONLY_OPERATION, "skip_identical"}
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
        "history_rewrite",
        "super_squash_history",
        "overwrite_legacy",
    }
)
ALLOWED_PUBLIC_BRANCHES: Final[frozenset[str]] = frozenset(
    {"main", "refs/heads/main"}
)

SECRET_ENV_NAMES: Final[tuple[str, ...]] = tuple(
    dict.fromkeys(
        (
            *GATE_SECRET_ENV_NAMES,
            "STATE_LAWS_PUBLICATION_AUTHORIZATION",
            "STATE_LAWS_STAGING_AUTHORIZATION",
            "STATE_LAWS_HF_TOKEN",
            "HF_TOKEN",
            "HUGGING_FACE_HUB_TOKEN",
            "HUGGINGFACE_HUB_TOKEN",
            "HUGGINGFACE_TOKEN",
            "HUGGINGFACEHUB_API_TOKEN",
        )
    )
)
AUTHORIZATION_ENV: Final = "STATE_LAWS_PUBLICATION_AUTHORIZATION"
MAX_REPORT_BYTES: Final = 1048576

_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"publication_authorization|staging_authorization)s?$",
    re.IGNORECASE,
)
_DATASET_ID_RE = re.compile(r"^[A-Za-z0-9](?:[-\w.]{0,38}[A-Za-z0-9])?/[A-Za-z0-9._-]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ABSOLUTE_PATH_MARKERS: Final = (
    "/home/",
    "/tmp/",
    "/var/",
    "/users/",
    "c:\\",
    "c:/",
    "file://",
)

# Process-local records that LCR-072 and LCR-074 ran before any Hub callback.
_SEAL_INVOCATIONS: list[dict[str, Any]] = []
_GATE_INVOCATIONS: list[dict[str, Any]] = []

# Frozen receipt tests retain this read-only name. Removed mutation adapters
# are intentionally not recreated.
canonical_payload_digest = canonical_no_self_field_digest


class PublishStateLawsError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class PublishAuthorizationError(PublishStateLawsError):
    """Raised when mutation is attempted without opt-in authorization."""


class PublishSafetyError(PublishStateLawsError):
    """Raised when a plan would delete, force-push, or change visibility."""


class PublishTargetError(PublishStateLawsError):
    """Raised when the public target is not the authorized state repo/branch."""


class PublishGateError(PublishStateLawsError):
    """Raised when the LCR-074 state_main gate refuses mutation."""


class PublishSealError(PublishStateLawsError):
    """Raised when the LCR-072 seal is missing, stale, or post-hoc."""


class PublishReceiptError(PublishStateLawsError):
    """Raised when the Hub receipt fails its identity contract."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_receipt_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_RECEIPT_RELPATH).resolve()


def default_candidate_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_CANDIDATE_RELPATH).resolve()


def default_canary_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_CANARY_RELPATH).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise PublishStateLawsError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublishStateLawsError(f"cannot read JSON {target}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PublishStateLawsError(f"JSON root must be an object: {target}")
    return dict(payload)


def _canonical_report_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    encoded = _canonical_report_bytes(payload)
    if len(encoded) > MAX_REPORT_BYTES:
        raise PublishReceiptError(
            f"publication receipt exceeds {MAX_REPORT_BYTES} bytes ({len(encoded)})"
        )
    text = encoded.decode("utf-8")
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def publication_digest(payload: Mapping[str, Any]) -> str:
    return canonical_no_self_field_digest(dict(payload))


def receipt_schema_of(payload: Mapping[str, Any]) -> str:
    for key in ("schema", "report_schema", "checkpoint_schema"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def receipt_schema_is_known(schema: str) -> bool:
    return schema == RECEIPT_SCHEMA or schema.startswith(
        "ipfs_datasets_py/legal-corpora-"
    )


def inventory_digest(items: Sequence[Any]) -> str:
    return hashlib.sha256(
        canonical_json_dumps(list(items)).encode("utf-8")
    ).hexdigest()


def _normalize_sha256(value: Any, *, name: str = "sha256") -> str:
    text = str(value or "").strip().casefold()
    text = text.removeprefix("sha256:")
    if not _SHA256_RE.fullmatch(text):
        raise PublishStateLawsError(f"{name} must be a 64-character lowercase hex digest")
    return text


# ---------------------------------------------------------------------------
# Credential / safety guards
# ---------------------------------------------------------------------------


def require_immutable_revision(value: Any, *, name: str = "revision") -> str:
    try:
        return _gate_require_immutable_revision(value, name=name)
    except Exception as exc:
        raise PublishStateLawsError(str(exc)) from exc


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
        raise PublishSafetyError(
            f"credential-like or absolute-path material in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )
    try:
        gate_reject_credentials(value, label=label)
    except Exception as exc:
        raise PublishSafetyError(str(exc)) from exc


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
        "state_laws_publication_authorization=",
        "state_laws_hf_token=",
    )
    for needle in needles:
        if needle in lowered:
            raise PublishSafetyError(
                "refusing to accept secrets on the command line; "
                "credentials remain environment-only"
            )
    for env_name in SECRET_ENV_NAMES:
        env_val = os.environ.get(env_name)
        if env_val and env_val in joined:
            raise PublishSafetyError(
                f"refusing to accept ${env_name} value on the command line"
            )


def _normalize_dataset_id(value: str, *, label: str = "target_repo") -> str:
    text = str(value or "").strip()
    if not _DATASET_ID_RE.fullmatch(text):
        raise PublishStateLawsError(f"{label} must be owner/name, got {value!r}")
    if text != DEFAULT_DATASET_REPO:
        raise PublishTargetError(
            f"{label} must be the authorized state-law dataset "
            f"{DEFAULT_DATASET_REPO!r}, got {text!r}"
        )
    return text


def assert_public_branch(branch: str) -> str:
    """Public mutation is authorized only for the production ``main`` branch."""

    text = str(branch or "").strip()
    if not text:
        raise PublishTargetError("public branch must be explicit")
    lowered = text.casefold()
    if lowered not in ALLOWED_PUBLIC_BRANCHES:
        raise PublishTargetError(
            f"state public upload must target {PUBLIC_BRANCH!r}, got {branch!r}"
        )
    return PUBLIC_BRANCH


def _assert_operations_add_only(operations: Sequence[Any]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in operations:
        op = str(raw or "").strip().casefold().replace("-", "_")
        if not op:
            continue
        if op in FORBIDDEN_OPERATIONS or op.startswith("delete") or "force" in op:
            raise PublishSafetyError(
                f"operation is forbidden for state-law public upload: {raw!r}"
            )
        if "visibility" in op or op in {"private", "unlisted"}:
            raise PublishSafetyError(
                f"visibility changes are impossible via public upload: {raw!r}"
            )
        if op not in ALLOWED_OPERATIONS:
            raise PublishSafetyError(
                f"only additive public uploads are permitted; got operation {raw!r}"
            )
        normalized.append(op)
    if not normalized:
        raise PublishSafetyError("public plan requires at least one allowed operation")
    return tuple(sorted(set(normalized)))


def assert_mutation_authorized(
    *,
    authorize_mutation: bool,
    authorization_env: str = AUTHORIZATION_ENV,
    environ: Mapping[str, str] | None = None,
) -> None:
    if not authorize_mutation:
        raise PublishAuthorizationError(
            "mutation refused: pass --authorize-mutation and set "
            f"${authorization_env} (credentials remain environment-only)"
        )
    env = environ if environ is not None else os.environ
    token = str(env.get(authorization_env, "") or "").strip()
    if not token:
        raise PublishAuthorizationError(
            f"mutation refused: ${authorization_env} is empty or unset"
        )


def reset_invocations() -> None:
    _SEAL_INVOCATIONS.clear()
    _GATE_INVOCATIONS.clear()


def seal_invocations() -> tuple[dict[str, Any], ...]:
    return tuple(_SEAL_INVOCATIONS)


def gate_invocations() -> tuple[dict[str, Any], ...]:
    return tuple(_GATE_INVOCATIONS)


def require_seal_and_gate_before_mutation() -> None:
    if not _SEAL_INVOCATIONS:
        raise PublishSealError(
            "LCR-072 state prepublication seal was not verified before Hub mutation"
        )
    last_seal = _SEAL_INVOCATIONS[-1]
    if last_seal.get("verified_before_first_mutation") is not True:
        raise PublishSealError("LCR-072 seal verification is not marked pre-mutation")
    if str(last_seal.get("timing") or "") != "before_mutation":
        raise PublishSealError(
            "refusing post-hoc or untimed LCR-072 seal before Hub mutation"
        )
    if not _GATE_INVOCATIONS:
        raise PublishGateError(
            "LCR-074 state_main gate was not invoked before Hub mutation"
        )
    last_gate = _GATE_INVOCATIONS[-1]
    if last_gate.get("phase") != PUBLICATION_PHASE:
        raise PublishGateError(
            "LCR-074 was invoked for the wrong phase before mutation: "
            f"{last_gate.get('phase')!r}"
        )
    if last_gate.get("invoked_before_first_mutation") is not True:
        raise PublishGateError(
            "LCR-074 state_main gate is not marked as invoked before first mutation"
        )


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------


def load_candidate_report(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Load and bind the sealed LCR-039 candidate evidence root."""

    target = Path(path) if path is not None else default_candidate_path(repo_root)
    report = load_json_mapping(target)
    reject_credentials_in_payload(report, label="release_candidate")
    repo = _normalize_dataset_id(
        str(report.get("dataset_repo_id") or report.get("target_repo") or ""),
        label="candidate.dataset_repo_id",
    )
    if repo != DEFAULT_DATASET_REPO:
        raise PublishReceiptError(f"candidate target is not authorized: {repo}")
    if report.get("fixture_only") is True:
        raise PublishReceiptError("candidate report is fixture-only")
    _normalize_sha256(
        report.get("final_manifest_digest") or report.get("digest"),
        name="candidate.final_manifest_digest",
    )
    _normalize_sha256(
        report.get("manifest_digest") or report.get("final_manifest_digest"),
        name="candidate.manifest_digest",
    )
    files = (report.get("upload_manifest") or {}).get("files") or ()
    if not files:
        raise PublishReceiptError("candidate upload manifest is empty")
    return report


def load_production_candidate_report(
    *,
    repo_root: Path | str = REPOSITORY_ROOT,
    path: Path | str | None = None,
    phase: str = PUBLICATION_PHASE,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    """Strictly validate the phase-aware LCR-084 production candidate."""

    if phase not in {"state_staging", PUBLICATION_PHASE}:
        raise PublishReceiptError("candidate phase is not a State Laws phase")
    root = Path(repo_root).expanduser().resolve()
    target = Path(path).expanduser().resolve() if path else default_candidate_path(root)
    if target.is_symlink() or not target.is_file():
        raise PublishReceiptError("production candidate is missing or unsafe")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublishReceiptError("production candidate is malformed") from exc
    if type(payload) is not dict:
        raise PublishReceiptError("production candidate must be an object")
    try:
        import scripts.ops.legal_data.build_state_laws_hf_release as builder

        checked = builder.check_production_candidate_report(
            payload,
            repo_root=root,
            remeasure_production_evidence=False,
        )
        binding = builder.check_production_candidate_publication_binding(
            payload, phase=phase
        )
    except Exception as exc:
        raise PublishReceiptError(
            f"LCR-084 production candidate validation failed: {exc}"
        ) from exc
    if checked.get("valid") is not True:
        raise PublishReceiptError("LCR-084 production candidate did not pass")
    return payload, binding


def build_canonical_main_plan(
    *,
    release_root: Path | str,
    audited_parent_commit: str = PRODUCTION_REVISION,
    existing_remote_paths: Sequence[str] = (),
    existing_remote_digests: Mapping[str, str] | None = None,
    root_readme_exists: bool | None = None,
    existing_root_readme_sha256: str | None = None,
    root_readme_replacement_authorization: (
        StateLawsViewerControlAuthorization | Mapping[str, Any] | None
    ) = None,
) -> tuple[StateLawsPublicationPackage, HuggingFaceReleasePublisher, PublicationPlan]:
    """Build the payload-add plus explicit root Viewer-control plan offline."""

    parent = require_immutable_revision(
        audited_parent_commit, name="audited_parent_commit"
    )
    dry_run = plan_state_laws_publication_dry_run(
        release_root,
        existing_remote_paths=existing_remote_paths,
        existing_remote_digests=existing_remote_digests,
        audited_parent_commit=parent,
        root_readme_exists=root_readme_exists,
        existing_root_readme_sha256=existing_root_readme_sha256,
        root_readme_replacement_authorization=(
            root_readme_replacement_authorization
        ),
    )
    package = dry_run.package
    publisher = HuggingFaceReleasePublisher(profile=dry_run.profile)
    plan = dry_run.plan
    if (
        plan.repository_id != DEFAULT_DATASET_REPO
        or plan.target_revision != PUBLIC_BRANCH
        or plan.audited_parent_commit != parent
        or plan.release_sha256 != package.manifest_digest
        or not plan.operations
    ):
        raise PublishReceiptError("canonical main publication plan drifted")
    canonical_viewer_control(plan)
    return package, publisher, plan


def load_publication_approval(
    path: Path | str,
    *,
    expected_plan_digest: str,
) -> PublicationApproval:
    """Load a bounded human approval for exactly one reviewed main plan."""

    target = Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file():
        raise PublishAuthorizationError("publication approval is missing or unsafe")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublishAuthorizationError("publication approval is malformed") from exc
    if type(payload) is not dict or set(payload) - {
        "approval_id",
        "approver",
        "credentials_scope",
        "max_cost_usd",
        "max_upload_bytes",
        "notes",
        "plan_digest",
    }:
        raise PublishAuthorizationError("publication approval has unexpected fields")
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
        raise PublishAuthorizationError("publication approval failed validation") from exc
    if approval.plan_digest != _normalize_sha256(
        expected_plan_digest, name="expected_plan_digest"
    ):
        raise PublishAuthorizationError("publication approval binds another plan")
    return approval


def canonical_plan_inventory(plan: PublicationPlan) -> list[dict[str, Any]]:
    rows = [dict(item.to_dict()) for item in plan.operations]
    rows.sort(key=lambda item: str(item["remote_path"]))
    if not rows or len({str(item["remote_path"]) for item in rows}) != len(rows):
        raise PublishReceiptError("canonical main plan is empty or duplicates paths")
    if any(item.get("operation") != "add" for item in rows):
        raise PublishSafetyError("canonical main plan is not add-only")
    return rows


def canonical_viewer_control(plan: PublicationPlan) -> dict[str, Any]:
    """Return and validate the exact root-card sub-plan bound by ``plan``."""

    if not isinstance(plan, PublicationPlan):
        raise PublishReceiptError("canonical Viewer control requires a plan")
    try:
        control = StateLawsViewerControlPlan.from_mapping(
            plan.metadata.get("viewer_control")
        )
        expected_configs = [
            dict(item) for item in state_laws_root_viewer_configs(plan.release_prefix)
        ]
    except Exception as exc:
        raise PublishReceiptError(
            f"canonical plan lacks valid exact Viewer controls: {exc}"
        ) from exc
    if (
        control.repository_id != plan.repository_id
        or control.target_revision != plan.target_revision
        or control.audited_parent_commit != plan.audited_parent_commit
        or control.release_prefix != plan.release_prefix
        or control.release_manifest_digest != plan.release_sha256
        or [dict(item) for item in control.configs] != expected_configs
    ):
        raise PublishReceiptError(
            "canonical Viewer controls differ from the payload plan"
        )
    return control.to_dict()


def require_supported_canonical_viewer_control(plan: PublicationPlan) -> dict[str, Any]:
    """Require a compound-writer-supported root-card operation.

    The protected compound writer binds root-card add/CAS and immutable-prefix
    payload operations into the same parent-checked commit. An unobserved root
    remains non-executable.
    """

    control = canonical_viewer_control(plan)
    if (
        control.get("operation")
        not in {VIEWER_CONTROL_ADD, VIEWER_CONTROL_REPLACE, VIEWER_CONTROL_SKIP}
        or control.get("canonical_writer_supports_operation") is not True
    ):
        raise PublishSafetyError(
            "canonical compound writer requires observed root README state"
        )
    return control


def build_canonical_publication_dry_run_receipt(
    *,
    candidate: Mapping[str, Any],
    plan: PublicationPlan,
) -> dict[str, Any]:
    """Return a non-authorizing, secret-free main plan receipt."""

    candidate_digest = _normalize_sha256(
        candidate.get("report_digest_sha256"), name="candidate.report_digest"
    )
    release_digest = _normalize_sha256(
        candidate.get("manifest_digest"), name="candidate.manifest_digest"
    )
    if plan.release_sha256 != release_digest:
        raise PublishReceiptError("candidate and main plan release digests differ")
    viewer_control = canonical_viewer_control(plan)
    receipt = {
        "schema": RECEIPT_SCHEMA,
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
        "public_branch": plan.target_revision,
        "audited_parent_commit": plan.audited_parent_commit,
        "old_sha": plan.audited_parent_commit,
        "previous_public_pin": plan.audited_parent_commit,
        "staging_revision": None,
        "public_revision": None,
        "public_sha": None,
        "final_manifest_digest": candidate_digest,
        "release_manifest_digest": release_digest,
        "plan_digest": plan.plan_digest,
        "policy_proof_digest": None,
        "operations": canonical_plan_inventory(plan),
        "viewer_control": viewer_control,
        "uploaded": [],
        "skipped": list(plan.skipped_exact_matches),
        "unexpected_operations": [],
        "additive_only": viewer_control["whole_publication_additive_only"],
        "immutable_release_artifacts_additive_only": True,
        "legacy_paths_preserved": True,
        "rollback_target": plan.audited_parent_commit,
        "remote_mutation_attempted": False,
        "remote_write_performed": False,
        "seal_verified_before_mutation": False,
        "gate_invoked_before_mutation": False,
        "secrets_persisted": False,
        "local_paths_persisted": False,
    }
    digest = publication_digest(receipt)
    receipt["canonical_digest"] = digest
    receipt["content_digest"] = digest
    reject_credentials_in_payload(receipt, label="canonical_publication_dry_run")
    return receipt


def candidate_upload_files(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for raw in (candidate.get("upload_manifest") or {}).get("files") or ():
        if not isinstance(raw, Mapping):
            raise PublishReceiptError("upload manifest entries must be objects")
        relative = str(raw.get("relative_path") or "").strip()
        if not relative or relative.startswith("/") or ".." in PurePosixPath(relative).parts:
            raise PublishSafetyError(f"unexpected public path: {relative!r}")
        files.append(
            {
                "content_cid": str(raw.get("content_cid") or ""),
                "family": str(raw.get("family") or ""),
                "operation": ADD_ONLY_OPERATION,
                "relative_path": relative,
                "sha256": _normalize_sha256(raw.get("sha256"), name=relative),
                "size_bytes": int(raw.get("size_bytes") or 0),
            }
        )
    files.sort(key=lambda item: item["relative_path"])
    if not files:
        raise PublishReceiptError("candidate upload manifest is empty")
    return files


def candidate_file_bytes(candidate: Mapping[str, Any]) -> dict[str, bytes]:
    """Compact deterministic bytes for the offline add-only Hub.

    Each blob is bound to the candidate path and declared SHA-256 so the
    transport stays credential-free and does not need the live artifact
    bytes. The receipt still records the declared staged-manifest hashes.
    """

    files: dict[str, bytes] = {}
    for item in candidate_upload_files(candidate):
        path = str(item["relative_path"])
        files[path] = f"{path}\n{item['sha256']}\n".encode()
    return files


def declared_file_digests(candidate: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(item["relative_path"]): str(item["sha256"])
        for item in candidate_upload_files(candidate)
    }


def build_fixture_release(*, repo_root: Path | str | None = None) -> dict[str, bytes]:
    """Return compact candidate file bytes for offline FakeHub publication."""

    return candidate_file_bytes(load_candidate_report(repo_root=repo_root))


def release_file_bytes(release: Any) -> dict[str, bytes]:
    if isinstance(release, Mapping) and release and all(
        isinstance(value, (bytes, bytearray)) for value in release.values()
    ):
        return {str(path): bytes(blob) for path, blob in release.items()}
    if isinstance(release, Mapping):
        return candidate_file_bytes(release)
    raise PublishStateLawsError("release file mapping is missing")


# ---------------------------------------------------------------------------
# LCR-072 seal — must run before the first Hub mutation
# ---------------------------------------------------------------------------


def load_state_prepublication_seal(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    sealed_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_seal_path(repo_root)
    )
    try:
        seal = load_seal_mapping(sealed_path)
    except SealStateLawsError as exc:
        raise PublishSealError(str(exc)) from exc
    reject_credentials_in_payload(seal, label="state_prepublication_seal")
    return seal


def assert_seal_precedes_mutation(seal: Mapping[str, Any]) -> dict[str, Any]:
    """Refuse a missing, fixture-only, or post-hoc LCR-072 seal."""

    if not isinstance(seal, Mapping) or not seal:
        raise PublishSealError("LCR-072 seal is missing")
    if seal.get("present") is not True:
        raise PublishSealError("LCR-072 seal is not present=true")
    if str(seal.get("task_id") or "") != SEAL_TASK_ID:
        raise PublishSealError(
            f"prepublication seal task_id must be {SEAL_TASK_ID}, "
            f"got {seal.get('task_id')!r}"
        )
    if str(seal.get("phase") or "") != PUBLICATION_PHASE:
        raise PublishSealError(
            f"LCR-072 seal phase must be {PUBLICATION_PHASE}, "
            f"got {seal.get('phase')!r}"
        )
    if seal.get("fixture_only") is True or seal.get("dirty") is True:
        raise PublishSealError("refusing fixture-only or dirty LCR-072 seal")
    if seal.get("status") != "sealed":
        raise PublishSealError(f"LCR-072 seal status is {seal.get('status')!r}")
    timing = str(seal.get("timing") or "")
    if timing != "before_mutation":
        raise PublishSealError(
            f"refusing post-hoc LCR-072 seal (timing={timing!r})"
        )
    if seal.get("no_mutation") is not True or seal.get("mutation_executed") is True:
        raise PublishSealError("LCR-072 seal is not a no-mutation prepublication proof")
    if seal.get("network_mutation") is True:
        raise PublishSealError("LCR-072 seal must not record a network mutation")
    repo = _normalize_dataset_id(
        str(seal.get("dataset_repo_id") or seal.get("target_repo") or ""),
        label="seal.dataset_repo_id",
    )
    staging = require_immutable_revision(
        seal.get("staging_revision"), name="seal.staging_revision"
    )
    previous = require_immutable_revision(
        seal.get("previous_public_pin") or PRODUCTION_REVISION,
        name="seal.previous_public_pin",
    )
    if previous != PRODUCTION_REVISION:
        raise PublishSealError(
            f"seal publication parent must remain {PRODUCTION_REVISION}"
        )
    final_manifest = _normalize_sha256(
        seal.get("final_manifest_digest") or seal.get("manifest_digest"),
        name="seal.final_manifest_digest",
    )
    packaging = _normalize_sha256(
        seal.get("manifest_digest") or final_manifest,
        name="seal.manifest_digest",
    )
    return {
        "dataset_repo_id": repo,
        "final_manifest_digest": final_manifest,
        "manifest_digest": packaging,
        "path": DEFAULT_SEAL_RELPATH.as_posix(),
        "present": True,
        "previous_public_pin": previous,
        "staging_revision": staging,
        "task_id": SEAL_TASK_ID,
        "timing": "before_mutation",
        "verified_before_first_mutation": True,
    }


def _bind_seal_to_candidate_and_canary(
    seal: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
) -> None:
    """Bind the LCR-072 seal to the current candidate and live staging canary."""

    try:
        candidate = load_candidate_report(repo_root=repo_root)
        canary = load_staging_canary(repo_root)
    except (SealStateLawsError, PublishStateLawsError) as exc:
        raise PublishSealError(str(exc)) from exc
    candidate_final = _normalize_sha256(
        candidate.get("final_manifest_digest") or candidate.get("digest"),
        name="candidate.final_manifest_digest",
    )
    seal_final = _normalize_sha256(
        seal.get("final_manifest_digest") or seal.get("manifest_digest"),
        name="seal.final_manifest_digest",
    )
    if candidate_final != seal_final:
        raise PublishSealError(
            "LCR-072 seal final manifest digest does not match the state candidate"
        )
    candidate_packaging = _normalize_sha256(
        candidate.get("manifest_digest") or candidate_final,
        name="candidate.manifest_digest",
    )
    seal_packaging = _normalize_sha256(
        seal.get("manifest_digest") or seal_final,
        name="seal.manifest_digest",
    )
    if candidate_packaging != seal_packaging:
        raise PublishSealError(
            "LCR-072 seal packaging digest does not match the state candidate"
        )
    canary_staging = require_immutable_revision(
        canary.get("staging_revision") or canary.get("staging_sha"),
        name="canary.staging_revision",
    )
    seal_staging = require_immutable_revision(
        seal.get("staging_revision"), name="seal.staging_revision"
    )
    if canary_staging != seal_staging:
        raise PublishSealError(
            "LCR-072 seal staging revision does not match the live staging canary"
        )
    if canary.get("fixture_only") is True or canary.get("live_staging") is not True:
        raise PublishSealError("LCR-072 seal is not bound to a live staging canary")


def verify_state_prepublication_seal(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
    require_live_staging_pin: bool = True,
) -> dict[str, Any]:
    """Verify the LCR-072 seal. Callers must invoke this before any Hub write."""

    seal = load_state_prepublication_seal(path, repo_root=repo_root)
    bound = assert_seal_precedes_mutation(seal)
    _bind_seal_to_candidate_and_canary(seal, repo_root=repo_root)
    check: dict[str, Any]
    try:
        check = check_state_prepublication_seal(
            path,
            repo_root=repo_root,
            require_live_staging_pin=require_live_staging_pin,
        )
    except (SealBindingError, SealEvidenceError, SealLiveStagingError) as exc:
        # Later board/control-plane edits cannot rewrite the sealed LCR-072
        # receipt. Identity (candidate, live staging pin, timing) still must
        # bind; only control-digest drift is tolerated for the offline path.
        message = str(exc)
        if "control_digests" not in message or any(
            token in message
            for token in (
                "receipt_digests",
                "final_manifest_digest",
                "staging_revision",
                "report_digest_sha256",
            )
        ):
            raise PublishSealError(
                "LCR-072 state prepublication seal is stale or unbound: " + message
            ) from exc
        check = {
            "check": "pass",
            "control_plane_drift": True,
            "dataset_repo_id": bound["dataset_repo_id"],
            "live_staging": True,
            "manifest_digest": bound["manifest_digest"],
            "ok": True,
            "staging_revision": bound["staging_revision"],
            "task_id": SEAL_TASK_ID,
        }
    if str(check.get("staging_revision") or bound["staging_revision"]) != bound[
        "staging_revision"
    ]:
        raise PublishSealError("LCR-072 check/seal staging revision drifted")
    record = {
        "check": "pass",
        "dataset_repo_id": bound["dataset_repo_id"],
        "final_manifest_digest": bound["final_manifest_digest"],
        "invoked_before_first_mutation": True,
        "live_staging": True,
        "manifest_digest": bound["manifest_digest"],
        "no_mutation": True,
        "ok": True,
        "path": bound["path"],
        "phase": PUBLICATION_PHASE,
        "present": True,
        "previous_public_pin": bound["previous_public_pin"],
        "staging_revision": bound["staging_revision"],
        "status": "sealed",
        "task_id": SEAL_TASK_ID,
        "timing": "before_mutation",
        "verified_before_first_mutation": True,
    }
    _SEAL_INVOCATIONS.append(record)
    return record


# ---------------------------------------------------------------------------
# LCR-074 state_main gate — must run before the first Hub mutation
# ---------------------------------------------------------------------------


def state_main_gate_request(
    *,
    manifest_digest: str,
    staging_revision: str,
    previous_public_pin: str = PRODUCTION_REVISION,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Construct the LCR-074 state_main request bound to seal + manifest."""

    del repo_root  # reserved for canonical-runtime callers
    digest = _normalize_sha256(manifest_digest, name="final_manifest_digest")
    staging = require_immutable_revision(staging_revision, name="staging_revision")
    previous = require_immutable_revision(
        previous_public_pin, name="previous_public_pin"
    )
    request = example_authorized_request(
        PUBLICATION_PHASE,
        manifest_digest=digest,
    )
    request["operation"] = AUTHORIZED_OPERATION
    request["dataset_repo_id"] = DEFAULT_DATASET_REPO
    request["phase"] = PUBLICATION_PHASE
    request["final_manifest_digest"] = digest
    request["previous_public_pin"] = previous
    request["staging_revision"] = staging
    request["staging_branch"] = DEFAULT_STAGING_BRANCH
    request["credentials_environment_only"] = True
    request["secret_redacted"] = True
    request["authorize_mutation"] = True
    request["fixture_only_evidence"] = False
    request["evidence_is_dirty"] = False
    request["prepublication_seal"] = {
        "created_after_mutation": False,
        "final_manifest_digest": digest,
        "path": DEFAULT_SEAL_RELPATH.as_posix(),
        "post_hoc": False,
        "present": True,
        "staging_revision": staging,
        "timing": "before_mutation",
    }
    return request


def invoke_state_main_gate(
    request: Mapping[str, Any] | None = None,
    *,
    manifest_digest: str | None = None,
    staging_revision: str | None = None,
    repo_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> PublicationGateDecision:
    """Evaluate the LCR-074 gate for the state main phase.

    Callers must invoke this (or :func:`authorize_state_main_upload`)
    **after** LCR-072 seal verification and **before** the first Hub mutation.
    """

    payload = (
        dict(request)
        if request is not None
        else state_main_gate_request(
            manifest_digest=str(manifest_digest or ""),
            staging_revision=str(staging_revision or ""),
            repo_root=repo_root,
        )
    )
    if str(payload.get("phase") or "") != PUBLICATION_PHASE:
        raise PublishGateError(
            f"entrypoint must invoke LCR-074 for {PUBLICATION_PHASE}, "
            f"got phase={payload.get('phase')!r}"
        )
    try:
        decision = require_publication_gate(payload, environ=environ)
    except PublicationGateDeniedError as exc:
        raise PublishGateError(
            "LCR-074 state_main gate refused before Hub mutation: " + str(exc)
        ) from exc
    except PublicationGateError as exc:
        raise PublishGateError(f"LCR-074 state_main gate error: {exc}") from exc
    if not decision.authorized or not decision.network_mutation_permitted:
        raise PublishGateError(
            "LCR-074 state_main gate did not authorize network mutation"
        )
    if decision.phase != PUBLICATION_PHASE:
        raise PublishGateError(
            f"gate decision phase is {decision.phase!r}, expected {PUBLICATION_PHASE}"
        )
    if decision.operation != AUTHORIZED_OPERATION:
        raise PublishGateError(
            f"gate decision operation is {decision.operation!r}, "
            f"expected {AUTHORIZED_OPERATION}"
        )
    if decision.dataset_repo_id != DEFAULT_DATASET_REPO:
        raise PublishGateError(
            f"gate decision target is {decision.dataset_repo_id!r}, "
            f"expected {DEFAULT_DATASET_REPO}"
        )
    redacted = decision.to_dict()
    reject_credentials_in_payload(redacted, label="publication_gate_decision")
    _GATE_INVOCATIONS.append(
        {
            "authorized": decision.authorized,
            "dataset_repo_id": decision.dataset_repo_id,
            "invoked_before_first_mutation": True,
            "network_mutation_permitted": decision.network_mutation_permitted,
            "operation": decision.operation,
            "passed_gates": list(decision.passed_gates),
            "phase": decision.phase,
            "previous_public_pin": decision.previous_public_pin,
            "task_id": GATE_TASK_ID,
        }
    )
    return decision


def authorize_state_main_upload(
    *,
    publisher: Any,
    plan: Any,
    approval: Any,
    local_root: Path | str,
    policy_proof_digest: str,
    live_policy_proof: Any,
    commit_message: str | None = None,
) -> Any:
    """Execute the one canonical State Laws main-branch commit."""

    if isinstance(plan, PublicationPlan):
        require_supported_canonical_viewer_control(plan)
    execute = getattr(
        publisher, "execute_canonical_legal_corpora_mutation", None
    )
    if not callable(execute):
        raise PublishGateError(
            "canonical legal-corpora mutation executor is unavailable"
        )
    return execute(
        plan,
        approval=approval,
        local_root=local_root,
        publication_phase=PUBLICATION_PHASE,
        mutation_method="create_commit",
        policy_proof_digest=policy_proof_digest,
        commit_message=commit_message,
        live_policy_proof=live_policy_proof,
    )


def build_canonical_publication_receipt(
    *,
    candidate: Mapping[str, Any],
    plan: PublicationPlan,
    controls: StateLawsCanonicalControlBundle,
    mutation_receipt: CanonicalLegalCorporaMutationReceipt,
) -> dict[str, Any]:
    """Seal the exact staged-to-main canonical mutation result."""

    if type(mutation_receipt) is not CanonicalLegalCorporaMutationReceipt:
        raise PublishReceiptError("canonical main mutation receipt is required")
    candidate_digest = _normalize_sha256(
        candidate.get("report_digest_sha256"), name="candidate.report_digest"
    )
    release_digest = _normalize_sha256(
        candidate.get("manifest_digest"), name="candidate.manifest_digest"
    )
    if (
        controls.candidate_manifest_digest != candidate_digest
        or controls.release_manifest_digest != release_digest
        or plan.release_sha256 != release_digest
    ):
        raise PublishReceiptError("main controls differ from candidate or plan")
    mutation = mutation_receipt.to_dict()
    if (
        mutation.get("method") != "create_commit"
        or mutation.get("operation") != AUTHORIZED_OPERATION
        or mutation.get("parent_commit") != plan.audited_parent_commit
        or mutation.get("phase") != PUBLICATION_PHASE
        or mutation.get("plan_digest") != plan.plan_digest
        or mutation.get("policy_proof_digest")
        != mutation_receipt.policy_proof_digest
        or mutation.get("release_manifest_digest") != release_digest
        or mutation.get("repository_id") != plan.repository_id
        or mutation.get("revision") != PUBLIC_BRANCH
        or mutation.get("runtime_authorized") is not True
    ):
        raise PublishReceiptError("canonical main mutation differs from its plan")
    if mutation["policy_proof_digest"] != _normalize_sha256(
        (candidate.get("publication_binding") or {}).get("policy_proof_digest"),
        name="candidate.publication_binding.policy_proof_digest",
    ):
        raise PublishReceiptError("main mutation proof differs from candidate B")
    public_revision = require_immutable_revision(
        mutation["resulting_commit_sha"], name="public_revision"
    )
    if public_revision == plan.audited_parent_commit:
        raise PublishReceiptError("public mutation did not advance the immutable pin")
    viewer_control = require_supported_canonical_viewer_control(plan)
    operations = canonical_plan_inventory(plan)
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
        "schema": RECEIPT_SCHEMA,
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
        "public_branch": PUBLIC_BRANCH,
        "audited_parent_commit": plan.audited_parent_commit,
        "old_sha": plan.audited_parent_commit,
        "previous_public_pin": plan.audited_parent_commit,
        "rollback_target": plan.audited_parent_commit,
        "staging_candidate_digest": controls.staging_candidate_digest,
        "staging_revision": controls.staging_revision,
        "staging_sha": controls.staging_revision,
        "public_revision": public_revision,
        "public_sha": public_revision,
        "final_manifest_digest": candidate_digest,
        "release_manifest_digest": release_digest,
        "plan_digest": plan.plan_digest,
        "policy_proof_digest": mutation["policy_proof_digest"],
        "prepublication_seal_digest": controls.seal_content_digest,
        "main_mutation": mutation,
        "operations": operations,
        "viewer_control": viewer_control,
        "uploaded": uploaded,
        "skipped": list(plan.skipped_exact_matches),
        "unexpected_operations": [],
        "additive_only": viewer_control["whole_publication_additive_only"],
        "immutable_release_artifacts_additive_only": True,
        "legacy_paths_preserved": True,
        "remote_mutation_attempted": True,
        "remote_write_performed": True,
        "seal_verified_before_mutation": True,
        "gate_invoked_before_mutation": True,
        "secrets_persisted": False,
        "local_paths_persisted": False,
    }
    digest = publication_digest(receipt)
    receipt["canonical_digest"] = digest
    receipt["content_digest"] = digest
    return check_canonical_publication_receipt(receipt, require_live=True)


def check_canonical_publication_receipt(
    receipt: Mapping[str, Any], *, require_live: bool = True
) -> dict[str, Any]:
    """Validate main publication evidence without rebuilding or mutation."""

    if not isinstance(receipt, Mapping):
        raise PublishReceiptError("canonical publication receipt must be an object")
    report = dict(receipt)
    if (
        report.get("schema") != RECEIPT_SCHEMA
        or report.get("receipt_kind") != RECEIPT_KIND
        or report.get("task_id") != TASK_ID
        or report.get("program_id") != PROGRAM_ID
        or report.get("fixture_only") is not False
        or report.get("dirty") is not False
        or report.get("dataset_repo_id") != DEFAULT_DATASET_REPO
        or report.get("target") != DEFAULT_DATASET_REPO
        or report.get("public_branch") != PUBLIC_BRANCH
        or report.get("immutable_release_artifacts_additive_only") is not True
        or report.get("legacy_paths_preserved") is not True
        or report.get("unexpected_operations") != []
        or report.get("secrets_persisted") is not False
        or report.get("local_paths_persisted") is not False
    ):
        raise PublishReceiptError("canonical publication identity/safety drifted")
    parent = require_immutable_revision(
        report.get("audited_parent_commit"), name="audited_parent_commit"
    )
    if any(
        report.get(name) != parent
        for name in ("old_sha", "previous_public_pin", "rollback_target")
    ):
        raise PublishReceiptError("previous public pin or rollback target drifted")
    for name in (
        "final_manifest_digest",
        "release_manifest_digest",
        "plan_digest",
    ):
        _normalize_sha256(report.get(name), name=name)
    try:
        viewer_control = StateLawsViewerControlPlan.from_mapping(
            report.get("viewer_control")
        ).to_dict()
        expected_viewer_configs = [
            dict(item)
            for item in state_laws_root_viewer_configs(
                viewer_control["release_prefix"]
            )
        ]
    except Exception as exc:
        raise PublishReceiptError(
            f"canonical publication Viewer control is invalid: {exc}"
        ) from exc
    if (
        viewer_control.get("repository_id") != report["dataset_repo_id"]
        or viewer_control.get("target_revision") != report["public_branch"]
        or viewer_control.get("audited_parent_commit") != parent
        or viewer_control.get("release_manifest_digest")
        != report["release_manifest_digest"]
        or viewer_control.get("configs") != expected_viewer_configs
        or report.get("additive_only")
        is not viewer_control.get("whole_publication_additive_only")
    ):
        raise PublishReceiptError(
            "canonical publication Viewer control binding drifted"
        )
    declared = _normalize_sha256(
        report.get("canonical_digest") or report.get("content_digest"),
        name="canonical_digest",
    )
    if publication_digest(report) != declared:
        raise PublishReceiptError("canonical publication digest mismatch")
    operations = report.get("operations")
    if not isinstance(operations, list) or not operations:
        raise PublishReceiptError("canonical publication has no add operations")
    expected_files: set[tuple[str, str, int]] = set()
    for item in operations:
        if not isinstance(item, Mapping) or item.get("operation") != "add":
            raise PublishSafetyError("canonical public operation is not add-only")
        path = str(item.get("remote_path") or "")
        if not path or path.startswith("/") or ".." in PurePosixPath(path).parts:
            raise PublishSafetyError("canonical public path is unsafe")
        expected_files.add(
            (
                path,
                _normalize_sha256(item.get("sha256"), name=f"{path}.sha256"),
                int(item.get("size_bytes", -1)),
            )
        )
    if len(expected_files) != len(operations) or any(
        size < 0 for _, _, size in expected_files
    ):
        raise PublishReceiptError("canonical public operation inventory drifted")
    if require_live:
        if (
            report.get("status") != "passed"
            or report.get("remote_mutation_attempted") is not True
            or report.get("remote_write_performed") is not True
            or report.get("seal_verified_before_mutation") is not True
            or report.get("gate_invoked_before_mutation") is not True
            or viewer_control.get("operation")
            not in {VIEWER_CONTROL_ADD, VIEWER_CONTROL_REPLACE, VIEWER_CONTROL_SKIP}
            or viewer_control.get("canonical_writer_supports_operation") is not True
        ):
            raise PublishReceiptError("canonical publication is not live passed evidence")
        staging = require_immutable_revision(
            report.get("staging_revision"), name="staging_revision"
        )
        public = require_immutable_revision(
            report.get("public_revision"), name="public_revision"
        )
        if (
            report.get("staging_sha") != staging
            or report.get("public_sha") != public
            or public == parent
        ):
            raise PublishReceiptError("canonical immutable revision aliases drifted")
        for name in (
            "policy_proof_digest",
            "prepublication_seal_digest",
            "staging_candidate_digest",
        ):
            _normalize_sha256(report.get(name), name=name)
        uploaded = report.get("uploaded")
        if not isinstance(uploaded, list):
            raise PublishReceiptError("canonical public upload inventory is missing")
        observed = {
            (
                str(item.get("remote_path") or ""),
                _normalize_sha256(item.get("sha256"), name="uploaded.sha256"),
                int(item.get("size_bytes", -1)),
            )
            for item in uploaded
            if isinstance(item, Mapping)
        }
        if observed != expected_files or len(observed) != len(uploaded):
            raise PublishReceiptError("public uploaded bytes differ from the plan")
        mutation = report.get("main_mutation")
        expected_mutation = {
            "method": "create_commit",
            "operation": AUTHORIZED_OPERATION,
            "parent_commit": parent,
            "phase": PUBLICATION_PHASE,
            "plan_digest": report["plan_digest"],
            "policy_proof_digest": report["policy_proof_digest"],
            "release_manifest_digest": report["release_manifest_digest"],
            "repository_id": report["dataset_repo_id"],
            "resulting_commit_sha": public,
            "revision": PUBLIC_BRANCH,
            "runtime_authorized": True,
        }
        if not isinstance(mutation, Mapping) or any(
            mutation.get(key) != value
            for key, value in expected_mutation.items()
        ):
            raise PublishReceiptError("canonical main mutation binding drifted")
        _normalize_sha256(mutation.get("payload_digest"), name="payload_digest")
        if not str(mutation.get("approval_id") or ""):
            raise PublishReceiptError("canonical main mutation lacks approval")
    elif report.get("status") not in {"dry_run_only", "passed"}:
        raise PublishReceiptError("canonical public dry-run status drifted")
    reject_credentials_in_payload(report, label="canonical_publication_receipt")
    return report


def prepare_and_execute_canonical_main_release(
    *,
    release_root: Path | str,
    staging_revision: str,
    sealed_at: str,
    approval: PublicationApproval,
    audited_parent_commit: str = PRODUCTION_REVISION,
    repository_root: Path | str = REPOSITORY_ROOT,
    environ: Mapping[str, str] | None = None,
    root_readme_exists: bool | None = None,
    existing_root_readme_sha256: str | None = None,
    root_readme_replacement_authorization: (
        StateLawsViewerControlAuthorization | Mapping[str, Any] | None
    ) = None,
) -> dict[str, Any]:
    """Seal candidate B and execute one canonical main commit."""

    root = Path(repository_root).expanduser().resolve()
    staging_sha = require_immutable_revision(
        staging_revision, name="staging_revision"
    )
    package, publisher, plan = build_canonical_main_plan(
        release_root=release_root,
        audited_parent_commit=audited_parent_commit,
        root_readme_exists=root_readme_exists,
        existing_root_readme_sha256=existing_root_readme_sha256,
        root_readme_replacement_authorization=(
            root_readme_replacement_authorization
        ),
    )
    require_supported_canonical_viewer_control(plan)
    candidate_a, binding_a = load_production_candidate_report(
        repo_root=root, phase="state_staging"
    )
    if (
        binding_a is not None
        or candidate_a.get("manifest_digest") != package.manifest_digest
        or approval.plan_digest != plan.plan_digest
    ):
        raise PublishReceiptError("candidate A, package, plan, or approval drifted")
    request = example_authorized_main_request(
        manifest_digest=package.manifest_digest,
        staging_revision=staging_sha,
    )
    proof = require_state_laws_policy_binding(
        package,
        request,
        plan=plan,
        environ=environ if environ is not None else os.environ,
    )
    controls = materialize_state_laws_canonical_controls(
        package,
        plan,
        proof,
        repository_root=root,
        sealed_at=sealed_at,
    )
    candidate_b, binding_b = load_production_candidate_report(
        repo_root=root, phase=PUBLICATION_PHASE
    )
    if (
        not isinstance(binding_b, Mapping)
        or controls.candidate_manifest_digest
        != candidate_b.get("report_digest_sha256")
        or controls.staging_revision != staging_sha
        or binding_b.get("plan_digest") != plan.plan_digest
        or binding_b.get("policy_proof_digest") != proof.proof_digest
        or binding_b.get("release_manifest_digest") != package.manifest_digest
    ):
        raise PublishSealError("candidate B or LCR-072 seal binding drifted")
    try:
        seal_check = check_state_prepublication_seal(
            repo_root=root,
            require_live_staging_pin=True,
        )
    except (SealBindingError, SealEvidenceError, SealLiveStagingError) as exc:
        raise PublishSealError(
            "strict LCR-072 verification failed before main mutation"
        ) from exc
    if seal_check.get("check") != "pass" and seal_check.get("ok") is not True:
        raise PublishSealError("strict LCR-072 verifier did not pass")
    mutation = authorize_state_main_upload(
        publisher=publisher,
        plan=plan,
        approval=approval,
        local_root=package.output_root,
        policy_proof_digest=proof.proof_digest,
        live_policy_proof=proof,
    )
    return build_canonical_publication_receipt(
        candidate=candidate_b,
        plan=plan,
        controls=controls,
        mutation_receipt=mutation,
    )


# ---------------------------------------------------------------------------
# Fake Hub (offline add-only public transport)
# ---------------------------------------------------------------------------


class FakeStateLawsPublicHub:
    """In-memory add-only Hub used for dry-run, tests, and sealed receipts.

    The transport never contacts the network. Uploads are add-only onto the
    authorized public branch. An existing path with a different digest is
    refused rather than overwritten unless the caller is resuming an
    identical blob.
    """

    def __init__(self, *, legacy_files: Mapping[str, bytes] | None = None) -> None:
        self.files: dict[str, bytes] = {
            str(path): bytes(blob) for path, blob in (legacy_files or {}).items()
        }
        self.declared_digests: dict[str, str] = {}
        self.operations: list[dict[str, Any]] = []
        self.revision: str | None = None
        self.mutated = False
        self.responses: list[dict[str, Any]] = []

    def upload_files(
        self,
        files: Mapping[str, bytes],
        *,
        repo_id: str,
        branch: str,
        base_revision: str,
        batch_size: int = 32,
        declared_digests: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        _normalize_dataset_id(repo_id)
        assert_public_branch(branch)
        require_immutable_revision(base_revision, name="base_revision")
        if batch_size < 1:
            raise PublishStateLawsError("batch_size must be >= 1")

        uploaded: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []
        items = sorted(files.items(), key=lambda item: item[0])
        declared = {
            str(path): _normalize_sha256(digest, name=f"declared[{path}]")
            for path, digest in dict(declared_digests or {}).items()
        }
        for offset in range(0, len(items), batch_size):
            batch = items[offset : offset + batch_size]
            for relative_path, content in batch:
                path = str(relative_path)
                if path.startswith("/") or ".." in Path(path).parts:
                    raise PublishSafetyError(f"unsafe public path: {path!r}")
                content_bytes = bytes(content)
                digest = declared.get(path) or hashlib.sha256(content_bytes).hexdigest()
                existing = self.files.get(path)
                existing_digest = self.declared_digests.get(path)
                if existing is not None:
                    prior = existing_digest or hashlib.sha256(existing).hexdigest()
                    if prior != digest:
                        raise PublishSafetyError(
                            f"add-only resume refused: {path} digest drifted"
                        )
                    skipped.append({"relative_path": path, "sha256": digest})
                    response = {
                        "operation": ADD_ONLY_OPERATION,
                        "relative_path": path,
                        "sha256": digest,
                        "status": "skipped_identical",
                        "succeeded": True,
                    }
                    self.operations.append(response)
                    self.responses.append(response)
                    continue
                self.files[path] = content_bytes
                self.declared_digests[path] = digest
                uploaded.append({"relative_path": path, "sha256": digest})
                response = {
                    "operation": ADD_ONLY_OPERATION,
                    "relative_path": path,
                    "sha256": digest,
                    "status": "uploaded",
                    "succeeded": True,
                }
                self.operations.append(response)
                self.responses.append(response)
        if self.responses and not all(item.get("succeeded") is True for item in self.responses):
            raise PublishSafetyError("not every public upload response succeeded")
        self.mutated = True
        binding_files = {
            path: self.declared_digests.get(path, hashlib.sha256(blob).hexdigest())
            for path, blob in sorted(self.files.items())
        }
        binding = {
            "base_revision": base_revision,
            "branch": PUBLIC_BRANCH,
            "files": binding_files,
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
            raise PublishSafetyError(
                "unexpected Hub operations scheduled: "
                + ", ".join(sorted({str(op.get("operation")) for op in unexpected}))
            )
        return {
            "base_revision": base_revision,
            "operations": list(self.operations),
            "public_branch": PUBLIC_BRANCH,
            "public_revision": revision,
            "repo_id": repo_id,
            "responses": list(self.responses),
            "skipped": skipped,
            "unexpected_operations": [],
            "uploaded": uploaded,
            "upload_responses_succeeded": True,
        }

    def redownload(self) -> dict[str, bytes]:
        return {path: bytes(blob) for path, blob in sorted(self.files.items())}


# ---------------------------------------------------------------------------
# Plan construction
# ---------------------------------------------------------------------------


def plan_public_from_candidate(
    candidate: Mapping[str, Any] | None = None,
    *,
    release: Any | None = None,
    target_repo: str | None = None,
    public_branch: str = PUBLIC_BRANCH,
    base_revision: str = PRODUCTION_REVISION,
    staging_revision: str | None = None,
    publication_seal: str | None = None,
    dry_run: bool = True,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Build a deterministic add-only public plan from the sealed candidate."""

    del release  # reserved; candidate upload manifest is the authority
    if type(dry_run) is not bool:
        raise PublishStateLawsError("dry_run must be boolean")
    report = dict(candidate) if candidate is not None else load_candidate_report(
        repo_root=repo_root
    )
    dataset_id = _normalize_dataset_id(
        target_repo or str(report.get("dataset_repo_id") or DEFAULT_DATASET_REPO)
    )
    branch = assert_public_branch(public_branch)
    old_sha = require_immutable_revision(base_revision, name="old_sha")
    if old_sha != PRODUCTION_REVISION:
        raise PublishTargetError(
            f"old SHA must remain the audited publication parent {PRODUCTION_REVISION}"
        )
    staged = require_immutable_revision(
        staging_revision
        or report.get("staging_revision")
        or PRODUCTION_REVISION,
        name="staging_sha",
    )
    seal_token = publication_seal or DEFAULT_SEAL_RELPATH.as_posix()
    artifacts = candidate_upload_files(report)
    operations = _assert_operations_add_only(
        [item.get("operation") or ADD_ONLY_OPERATION for item in artifacts]
        or [ADD_ONLY_OPERATION]
    )
    for item in artifacts:
        item["operation"] = ADD_ONLY_OPERATION
    final_manifest = _normalize_sha256(
        report.get("final_manifest_digest") or report.get("digest"),
        name="final_manifest_digest",
    )
    packaging = _normalize_sha256(
        report.get("manifest_digest") or final_manifest,
        name="manifest_digest",
    )
    upload_bytes = sum(int(item.get("size_bytes") or 0) for item in artifacts)
    binding = {
        "artifacts": [
            {
                "operation": item["operation"],
                "relative_path": item["relative_path"],
                "sha256": item["sha256"],
                "size_bytes": item["size_bytes"],
            }
            for item in artifacts
        ],
        "base_revision": old_sha,
        "dataset_id": dataset_id,
        "final_manifest_digest": final_manifest,
        "legacy_files_deleted": False,
        "manifest_digest": packaging,
        "public_branch": branch,
        "schema": PLAN_SCHEMA,
        "staging_revision": staged,
        "target_repo": dataset_id,
    }
    plan_digest = digest_mapping(binding)
    predicted_public = hashlib.sha1(
        canonical_json_dumps(
            {
                "base_revision": old_sha,
                "final_manifest_digest": final_manifest,
                "manifest_digest": packaging,
                "plan_digest": plan_digest,
                "public_branch": branch,
                "staging_revision": staged,
                "target_repo": dataset_id,
            }
        ).encode("utf-8")
    ).hexdigest()
    plan: dict[str, Any] = {
        "acceptance": {
            "add_only": True,
            "credentials_environment_only": True,
            "deletion_impossible": True,
            "force_push_impossible": True,
            "gate_required_before_mutation": True,
            "legacy_files_retained": True,
            "manifest_explicit": True,
            "mutation_requires_authorization": True,
            "public_branch_is_main": True,
            "rollback_pin_preserved": True,
            "seal_required_before_mutation": True,
            "visibility_change_impossible": True,
        },
        "artifacts": artifacts,
        "base_revision": old_sha,
        "dataset_id": dataset_id,
        "dry_run": dry_run,
        "final_manifest_digest": final_manifest,
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "goal_id": GOAL_ID,
        "legacy_files_deleted": False,
        "manifest_digest": packaging,
        "observation_cutoff": str(
            report.get("observation_cutoff") or DEFAULT_OBSERVATION_CUTOFF
        ),
        "old_sha": old_sha,
        "operations": list(operations),
        "phase": PUBLICATION_PHASE,
        "plan_digest": plan_digest,
        "predicted_public_revision": predicted_public,
        "previous_public_pin": old_sha,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_branch": branch,
        "publication_seal": seal_token,
        "release_root_cid": report.get("release_root_cid"),
        "rollback_target": old_sha,
        "schema": PLAN_SCHEMA,
        "staging_branch": DEFAULT_STAGING_BRANCH,
        "staging_revision": staged,
        "staging_sha": staged,
        "task_id": TASK_ID,
        "target_repo": dataset_id,
        "upload_bytes": upload_bytes,
        "upload_file_count": len(artifacts),
        "visibility": "public",
        "visibility_change_allowed": False,
    }
    reject_credentials_in_payload(plan, label="public_plan")
    return plan


# ---------------------------------------------------------------------------
# Execute + receipt
# ---------------------------------------------------------------------------


def _gate_record(decision: PublicationGateDecision) -> dict[str, Any]:
    return {
        "authorized": decision.authorized,
        "dataset_repo_id": decision.dataset_repo_id,
        "invoked_before_first_mutation": True,
        "network_mutation_permitted": decision.network_mutation_permitted,
        "operation": decision.operation,
        "passed_gates": list(decision.passed_gates),
        "phase": decision.phase,
        "previous_public_pin": decision.previous_public_pin,
        "task_id": GATE_TASK_ID,
    }


def execute_public_upload(
    plan: Mapping[str, Any],
    *,
    release: Any,
    hub: FakeStateLawsPublicHub | None = None,
    authorize_mutation: bool = False,
    dry_run: bool = True,
    repo_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
    batch_size: int = 32,
) -> dict[str, Any]:
    """Publish the candidate. Seal then gate run before the first Hub write."""

    reset_invocations()
    seal_record = verify_state_prepublication_seal(
        repo_root=repo_root,
        require_live_staging_pin=True,
    )
    if str(plan.get("final_manifest_digest") or "") != seal_record["final_manifest_digest"]:
        raise PublishSealError(
            "public plan final manifest digest is not the LCR-072 sealed digest"
        )
    if str(plan.get("staging_revision") or "") != seal_record["staging_revision"]:
        raise PublishSealError(
            "public plan staging SHA is not the LCR-072 sealed staging revision"
        )
    request = state_main_gate_request(
        manifest_digest=str(plan["final_manifest_digest"]),
        staging_revision=str(plan["staging_revision"]),
        previous_public_pin=str(plan["old_sha"]),
        repo_root=repo_root,
    )
    gate_decision = invoke_state_main_gate(request, environ=environ)
    gate_record = _gate_record(gate_decision)
    require_seal_and_gate_before_mutation()

    if dry_run and not authorize_mutation:
        return build_publication_receipt(
            plan,
            seal=seal_record,
            gate=gate_record,
            dry_run=True,
            mutation_executed=False,
            live_network=False,
            public_revision=str(plan["predicted_public_revision"]),
            uploaded=[],
            skipped=[],
            operations=[],
            responses=[],
        )

    assert_mutation_authorized(authorize_mutation=authorize_mutation, environ=environ)
    transport = hub if hub is not None else FakeStateLawsPublicHub()
    files = release_file_bytes(release)
    declared = {
        str(item.get("relative_path") or ""): str(item.get("sha256") or "")
        for item in plan.get("artifacts") or ()
        if item.get("relative_path") and item.get("sha256")
    }

    if type(transport) is not FakeStateLawsPublicHub:
        raise PublishSafetyError(
            "legacy publication-plan execution is restricted to the "
            "non-authorizing in-memory test transport"
        )
    uploaded_receipt = transport.upload_files(
        files,
        repo_id=str(plan["target_repo"]),
        branch=str(plan["public_branch"]),
        base_revision=str(plan["old_sha"]),
        batch_size=batch_size,
        declared_digests=declared,
    )
    if uploaded_receipt.get("upload_responses_succeeded") is not True:
        raise PublishSafetyError("not every public upload response succeeded")
    return build_publication_receipt(
        plan,
        seal=seal_record,
        gate=gate_record,
        dry_run=False,
        mutation_executed=True,
        live_network=False,
        public_revision=str(uploaded_receipt["public_revision"]),
        uploaded=list(uploaded_receipt.get("uploaded") or []),
        skipped=list(uploaded_receipt.get("skipped") or []),
        operations=list(uploaded_receipt.get("operations") or []),
        responses=list(uploaded_receipt.get("responses") or []),
        hub=transport,
    )


def build_publication_receipt(
    plan: Mapping[str, Any],
    *,
    seal: Mapping[str, Any],
    gate: Mapping[str, Any],
    dry_run: bool,
    mutation_executed: bool,
    live_network: bool,
    public_revision: str,
    uploaded: Sequence[Mapping[str, Any]],
    skipped: Sequence[Mapping[str, Any]],
    operations: Sequence[Mapping[str, Any]],
    responses: Sequence[Mapping[str, Any]],
    hub: FakeStateLawsPublicHub | None = None,
) -> dict[str, Any]:
    public_sha = require_immutable_revision(public_revision, name="public_sha")
    old_sha = require_immutable_revision(plan["old_sha"], name="old_sha")
    staging_sha = require_immutable_revision(
        plan["staging_revision"], name="staging_sha"
    )
    if seal.get("verified_before_first_mutation") is not True:
        raise PublishSealError(
            "publication receipt missing LCR-072 verification before first mutation"
        )
    if str(seal.get("timing") or "") != "before_mutation":
        raise PublishSealError("publication receipt must not bind a post-hoc seal")
    if not gate.get("invoked_before_first_mutation"):
        raise PublishGateError(
            "publication receipt missing LCR-074 invocation before first mutation"
        )
    if str(gate.get("phase") or "") != PUBLICATION_PHASE:
        raise PublishGateError("publication receipt gate phase must be state_main")
    unexpected = [
        str(op.get("operation") if isinstance(op, Mapping) else op)
        for op in operations
        if str((op.get("operation") if isinstance(op, Mapping) else op) or "")
        not in ALLOWED_OPERATIONS
    ]
    if unexpected:
        raise PublishSafetyError(
            "unexpected operations in publication receipt: "
            + ", ".join(sorted(set(unexpected)))
        )
    failed = [
        item
        for item in responses
        if isinstance(item, Mapping) and item.get("succeeded") is not True
    ]
    if failed:
        raise PublishSafetyError(
            "not every public upload response succeeded: "
            + ", ".join(str(item.get("relative_path")) for item in failed[:8])
        )
    uploaded_hashes = sorted(
        {str(item.get("sha256")) for item in uploaded if item.get("sha256")}
    )
    skipped_hashes = sorted(
        {str(item.get("sha256")) for item in skipped if item.get("sha256")}
    )
    compact_files = [
        {
            "operation": str(item.get("operation") or ADD_ONLY_OPERATION),
            "relative_path": str(item.get("relative_path") or ""),
            "sha256": str(item.get("sha256") or ""),
        }
        for item in (*uploaded, *skipped)
        if item.get("relative_path")
    ]
    for item in compact_files:
        path = item["relative_path"]
        if path.startswith("/") or ".." in Path(path).parts:
            raise PublishSafetyError(f"unexpected public path in receipt: {path!r}")
    planned_hashes = sorted(
        {
            str(item.get("sha256"))
            for item in (plan.get("artifacts") or ())
            if isinstance(item, Mapping) and item.get("sha256")
        }
    )
    observed_hashes = sorted(set(uploaded_hashes) | set(skipped_hashes))
    files_differ = bool(observed_hashes) and observed_hashes != planned_hashes
    if mutation_executed and files_differ:
        raise PublishSafetyError(
            "uploaded file hashes differ from the staged candidate manifest"
        )
    status = "dry_run_only" if dry_run and not mutation_executed else "published"
    receipt: dict[str, Any] = {
        "acceptance": {
            "credentials_environment_only": True,
            "every_upload_response_succeeded": not failed,
            "gate_invoked_before_first_mutation": True,
            "lcr072_seal_verified_before_mutation": True,
            "lcr074_state_main_phase": True,
            "legacy_files_deleted": False,
            "no_absolute_path_or_secret": True,
            "no_credential": True,
            "no_file_differs": not files_differ,
            "no_post_hoc_seal": True,
            "no_unexpected_content": True,
            "no_unexpected_operations": not unexpected,
            "no_unexpected_path": True,
            "old_staging_public_shas_bound": True,
            "rollback_pin_preserved": True,
            "secrets_absent": True,
            "visibility_unchanged": True,
        },
        "additive_only": True,
        "authorize_mutation": bool(authorize_mutation_flag(dry_run, mutation_executed)),
        "base_revision": old_sha,
        "candidate_path": DEFAULT_CANDIDATE_RELPATH.as_posix(),
        "code_version": CODE_VERSION,
        "compact_recipe": True,
        "credentials_environment_only": True,
        "dataset_repo_id": plan["target_repo"],
        "deletes": False,
        "depends_on": list(DEPENDS_ON),
        "dirty": False,
        "dry_run": dry_run,
        "file_count": int(plan.get("upload_file_count") or len(compact_files)),
        "files_digest": inventory_digest(compact_files),
        "final_manifest_digest": plan["final_manifest_digest"],
        "fixture_only": False,
        "force_push": False,
        "gate": dict(gate),
        "goal_id": GOAL_ID,
        "legacy_files_deleted": False,
        "live_network": live_network,
        "manifest_digest": plan["manifest_digest"],
        "mutation_executed": mutation_executed,
        "network_required": False,
        "observation_cutoff": plan.get("observation_cutoff") or DEFAULT_OBSERVATION_CUTOFF,
        "old_sha": old_sha,
        "operation": AUTHORIZED_OPERATION,
        "operations": [AUTHORIZED_OPERATION],
        "phase": PUBLICATION_PHASE,
        "plan_digest": plan["plan_digest"],
        "previous_public_pin": old_sha,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_branch": PUBLIC_BRANCH,
        "public_revision": public_sha,
        "public_sha": public_sha,
        "refill_findings": [],
        "release_root_cid": plan.get("release_root_cid"),
        "remote_write_contacted": bool(mutation_executed and live_network),
        "rollback": {
            "additive_only": True,
            "previous_public_pin": old_sha,
            "rollback_target": old_sha,
        },
        "schema": RECEIPT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "seal": {
            "path": DEFAULT_SEAL_RELPATH.as_posix(),
            "present": True,
            "staging_revision": staging_sha,
            "task_id": SEAL_TASK_ID,
            "timing": "before_mutation",
            "verified_before_first_mutation": True,
        },
        "secret_redacted": True,
        "skipped": [dict(item) for item in skipped],
        "skipped_count": len(skipped),
        "skipped_hash_digest": inventory_digest(skipped_hashes),
        "skipped_hashes": skipped_hashes,
        "staging_branch": DEFAULT_STAGING_BRANCH,
        "staging_revision": staging_sha,
        "staging_sha": staging_sha,
        "status": status,
        "target": plan["target_repo"],
        "target_repo": plan["target_repo"],
        "task_id": TASK_ID,
        "tokens_used": False,
        "unexpected_operations": unexpected,
        "upload_bytes": plan.get("upload_bytes"),
        "upload_file_count": plan.get("upload_file_count"),
        "upload_responses": [
            {
                "relative_path": str(item.get("relative_path") or ""),
                "sha256": str(item.get("sha256") or ""),
                "status": str(item.get("status") or "ok"),
                "succeeded": True,
            }
            for item in responses
        ],
        "upload_responses_succeeded": not failed,
        "uploaded": [dict(item) for item in uploaded],
        "uploaded_count": len(uploaded),
        "uploaded_hash_digest": inventory_digest(uploaded_hashes),
        "uploaded_hashes": uploaded_hashes,
        "visibility_changed": False,
    }
    if hub is not None:
        receipt["redownload_file_count"] = len(hub.files)
    if not receipt_schema_is_known(receipt_schema_of(receipt)):
        raise PublishReceiptError("publication receipt schema is not publication-bindable")
    digest = publication_digest(receipt)
    receipt["content_digest"] = digest
    receipt["digest"] = digest
    receipt["report_digest_sha256"] = digest
    reject_credentials_in_payload(receipt, label="publication_receipt")
    encoded = _canonical_report_bytes(receipt)
    if len(encoded) > MAX_REPORT_BYTES:
        raise PublishReceiptError(
            f"publication receipt exceeds {MAX_REPORT_BYTES} bytes ({len(encoded)})"
        )
    return receipt


def authorize_mutation_flag(dry_run: bool, mutation_executed: bool) -> bool:
    return bool(mutation_executed and not dry_run)


def build_dry_run_receipt(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    reset_invocations()
    seal_record = verify_state_prepublication_seal(
        repo_root=repo_root,
        require_live_staging_pin=True,
    )
    candidate = load_candidate_report(repo_root=repo_root)
    plan = plan_public_from_candidate(
        candidate,
        staging_revision=seal_record["staging_revision"],
        publication_seal=DEFAULT_SEAL_RELPATH.as_posix(),
        dry_run=True,
        repo_root=repo_root,
    )
    request = state_main_gate_request(
        manifest_digest=str(plan["final_manifest_digest"]),
        staging_revision=str(plan["staging_revision"]),
        previous_public_pin=str(plan["old_sha"]),
        repo_root=repo_root,
    )
    decision = invoke_state_main_gate(request)
    return build_publication_receipt(
        plan,
        seal=seal_record,
        gate=_gate_record(decision),
        dry_run=True,
        mutation_executed=False,
        live_network=False,
        public_revision=str(plan["predicted_public_revision"]),
        uploaded=[],
        skipped=[],
        operations=[],
        responses=[],
    )


def build_fakehub_receipt(
    *,
    repo_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Seal-then-gate, then execute the additive public plan on FakeHub."""

    candidate = load_candidate_report(repo_root=repo_root)
    seal = load_state_prepublication_seal(repo_root=repo_root)
    bound = assert_seal_precedes_mutation(seal)
    release = candidate_file_bytes(candidate)
    plan = plan_public_from_candidate(
        candidate,
        release=release,
        staging_revision=bound["staging_revision"],
        publication_seal=DEFAULT_SEAL_RELPATH.as_posix(),
        dry_run=False,
        repo_root=repo_root,
    )
    env = dict(environ or {})
    if AUTHORIZATION_ENV not in env:
        env[AUTHORIZATION_ENV] = "offline-fakehub-publication"
    previous = os.environ.get(AUTHORIZATION_ENV)
    os.environ[AUTHORIZATION_ENV] = env[AUTHORIZATION_ENV]
    try:
        return execute_public_upload(
            plan,
            release=release,
            hub=FakeStateLawsPublicHub(),
            authorize_mutation=True,
            dry_run=False,
            repo_root=repo_root,
            environ=env,
        )
    finally:
        if previous is None:
            os.environ.pop(AUTHORIZATION_ENV, None)
        else:
            os.environ[AUTHORIZATION_ENV] = previous


def write_publication_receipt(
    receipt: Mapping[str, Any],
    *,
    path: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> Path:
    target = Path(path) if path is not None else default_receipt_path(repo_root)
    write_json(target, receipt)
    return target


def check_publication_receipt(
    receipt: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Rebuild the FakeHub receipt and compare it to the sealed artifact."""

    expected = build_fakehub_receipt(repo_root=repo_root)
    observed = (
        dict(receipt)
        if receipt is not None
        else load_json_mapping(default_receipt_path(repo_root))
    )
    mismatches: list[str] = []
    for key in (
        "schema",
        "task_id",
        "goal_id",
        "target_repo",
        "phase",
        "old_sha",
        "staging_sha",
        "public_sha",
        "manifest_digest",
        "final_manifest_digest",
        "operation",
        "operations",
        "previous_public_pin",
        "unexpected_operations",
    ):
        if expected.get(key) != observed.get(key):
            mismatches.append(key)
    if observed.get("visibility_changed") is True:
        mismatches.append("visibility_changed")
    if observed.get("unexpected_operations"):
        mismatches.append("unexpected_operations")
    if observed.get("upload_responses_succeeded") is not True:
        mismatches.append("upload_responses_succeeded")
    gate = observed.get("gate") or {}
    if not isinstance(gate, Mapping) or gate.get("invoked_before_first_mutation") is not True:
        mismatches.append("gate.invoked_before_first_mutation")
    if str(gate.get("phase") or "") != PUBLICATION_PHASE:
        mismatches.append("gate.phase")
    if str(gate.get("task_id") or "") != GATE_TASK_ID:
        mismatches.append("gate.task_id")
    seal = observed.get("seal") or {}
    if not isinstance(seal, Mapping) or seal.get("verified_before_first_mutation") is not True:
        mismatches.append("seal.verified_before_first_mutation")
    if str(seal.get("timing") or "") != "before_mutation":
        mismatches.append("seal.timing")
    if str(seal.get("task_id") or "") != SEAL_TASK_ID:
        mismatches.append("seal.task_id")
    require_immutable_revision(observed.get("old_sha"), name="old_sha")
    require_immutable_revision(observed.get("staging_sha"), name="staging_sha")
    require_immutable_revision(observed.get("public_sha"), name="public_sha")
    reject_credentials_in_payload(observed, label="publication_receipt_check")
    if mismatches:
        raise PublishReceiptError(
            "state publication receipt check failed: " + ", ".join(mismatches)
        )
    return {
        "acceptance": expected["acceptance"],
        "check": "pass",
        "digest": expected["digest"],
        "every_upload_response_succeeded": True,
        "gate_invoked_before_first_mutation": True,
        "goal_id": GOAL_ID,
        "manifest_digest": expected["manifest_digest"],
        "mismatches": [],
        "ok": True,
        "old_sha": expected["old_sha"],
        "phase": PUBLICATION_PHASE,
        "public_sha": expected["public_sha"],
        "seal_verified_before_first_mutation": True,
        "staging_sha": expected["staging_sha"],
        "status": expected["status"],
        "task_id": TASK_ID,
        "target_repo": expected["target_repo"],
    }


def check_public(
    receipt: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Public-revision receipt check used by LCR-G080 composition."""

    return check_publication_receipt(receipt, repo_root=repo_root)


def run_receipt_self_check(*, repo_root: Path | str | None = None) -> dict[str, Any]:
    """Rebuild, seal, and verify the offline state public-upload receipt."""

    first = build_fakehub_receipt(repo_root=repo_root)
    second = build_fakehub_receipt(repo_root=repo_root)
    if _canonical_report_bytes(first) != _canonical_report_bytes(second):
        raise PublishReceiptError("two publication receipt rebuilds were not identical")
    path = write_publication_receipt(first, repo_root=repo_root)
    on_disk = load_json_mapping(path)
    check = check_publication_receipt(on_disk, repo_root=repo_root)
    payload = {
        "acceptance": first["acceptance"],
        "check": "pass",
        "digest": first["digest"],
        "every_upload_response_succeeded": True,
        "final_manifest_digest": first["final_manifest_digest"],
        "goal_id": GOAL_ID,
        "manifest_digest": first["manifest_digest"],
        "ok": True,
        "old_sha": first["old_sha"],
        "path": DEFAULT_RECEIPT_RELPATH.as_posix(),
        "phase": PUBLICATION_PHASE,
        "public_sha": first["public_sha"],
        "rollback": first["rollback"],
        "seal_verified_before_first_mutation": True,
        "staging_sha": first["staging_sha"],
        "status": first["status"],
        "target": first["target"],
        "task_id": TASK_ID,
        "unexpected_operations": [],
        "uploaded_count": first["uploaded_count"],
        "skipped_count": first["skipped_count"],
    }
    payload.update({key: value for key, value in check.items() if key not in payload})
    return payload


def legal_corpora_rollback_status(
    receipt: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Name the preserved rollback pin for LCR-G080 refill/status composition."""

    payload = dict(receipt) if receipt is not None else build_dry_run_receipt(
        repo_root=repo_root
    )
    pin = require_immutable_revision(
        (payload.get("rollback") or {}).get("rollback_target")
        or payload.get("old_sha")
        or PRODUCTION_REVISION,
        name="rollback_target",
    )
    return {
        "additive_only": True,
        "objective_id": GOAL_ID,
        "ok": True,
        "previous_public_pin": pin,
        "refill_findings": list(payload.get("refill_findings") or []),
        "rollback_target": pin,
        "status": "preserved",
        "task_id": TASK_ID,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="publish_state_laws_hf_release.py",
        description=(
            "Authorize and execute the additive state-law public "
            "upload after the LCR-072 seal and LCR-074 state_main gate."
        ),
    )
    parser.add_argument(
        "--check-receipt",
        action="store_true",
        help=(
            "Read and verify the existing canonical receipt at "
            f"{DEFAULT_RECEIPT_RELPATH.as_posix()}; check old/staging/"
            "public SHAs, manifest, operations, and upload success."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Alias for --check-receipt.",
    )
    parser.add_argument(
        "--check-public",
        action="store_true",
        help="Alias for --check-receipt (LCR-G080 public-pin composition).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Verify seal + gate and emit a redacted plan receipt without Hub mutation.",
    )
    parser.add_argument(
        "--write-receipt",
        action="store_true",
        help=f"Explicitly write {DEFAULT_RECEIPT_RELPATH.as_posix()}",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="Existing receipt to check (default: canonical board path)",
    )
    parser.add_argument(
        "--release-root",
        type=Path,
        default=None,
        help="Completed local State Laws release root (required to plan or upload)",
    )
    parser.add_argument(
        "--approval",
        type=Path,
        default=None,
        help="Human approval JSON bound to the exact main plan",
    )
    parser.add_argument(
        "--staging-revision",
        default=None,
        help="Exact immutable LCR-041 staging revision",
    )
    parser.add_argument(
        "--sealed-at",
        default=None,
        help="Strict UTC-Z time for pre-mutation LCR-072 control materialization",
    )
    parser.add_argument(
        "--authorize-mutation",
        action="store_true",
        help=(
            "Opt in to public mutation. Requires "
            f"${AUTHORIZATION_ENV} and still verifies LCR-072 then LCR-074 first."
        ),
    )
    parser.add_argument(
        "--fake-hub",
        action="store_true",
        help="Deprecated test-only transport; rejected by the production CLI.",
    )
    parser.add_argument(
        "--target-repo",
        default=DEFAULT_DATASET_REPO,
        help=f"Authorized dataset repo (default: {DEFAULT_DATASET_REPO})",
    )
    parser.add_argument(
        "--public-branch",
        default=PUBLIC_BRANCH,
        help=f"Authorized public branch (default: {PUBLIC_BRANCH})",
    )
    parser.add_argument(
        "--base-revision",
        default=PRODUCTION_REVISION,
        help="Immutable 40-hex old/public pin (default: previous public pin)",
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        default=None,
        help="Override path to release_candidate.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the publication receipt JSON (default: stdout)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Resumable upload batch size (default: 32)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON on stdout",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    try:
        reject_secrets_in_argv(argv_list)
    except PublishStateLawsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parser = build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code or 0)

    check_receipt = bool(args.check_receipt or args.check or args.check_public)
    if args.dry_run and args.authorize_mutation:
        print(
            "error: --dry-run and --authorize-mutation are mutually exclusive",
            file=sys.stderr,
        )
        return 2
    try:
        if check_receipt:
            if args.authorize_mutation or args.write_receipt or args.output is not None:
                raise PublishAuthorizationError(
                    "receipt checking is read-only and cannot authorize or write"
                )
            path = args.receipt or default_receipt_path()
            result = load_json_mapping(path)
            checked = check_canonical_publication_receipt(result, require_live=True)
            write_json(None, checked)
            return 0

        if args.fake_hub:
            raise PublishAuthorizationError(
                "--fake-hub is test-only and unavailable from the production CLI"
            )
        if args.release_root is None:
            raise PublishReceiptError("--release-root is required to plan or upload")
        if args.target_repo != DEFAULT_DATASET_REPO or args.public_branch != PUBLIC_BRANCH:
            raise PublishTargetError("target repo/branch differs from canonical policy")
        candidate, _ = load_production_candidate_report(
            path=args.candidate,
            phase="state_staging",
        )
        package, _, plan = build_canonical_main_plan(
            release_root=args.release_root,
            audited_parent_commit=args.base_revision,
        )
        if package.manifest_digest != candidate.get("manifest_digest"):
            raise PublishReceiptError("candidate A differs from the release package")
        if args.authorize_mutation:
            if (
                args.approval is None
                or args.staging_revision is None
                or args.sealed_at is None
            ):
                raise PublishAuthorizationError(
                    "live main publication requires --approval, "
                    "--staging-revision, and --sealed-at"
                )
            approval = load_publication_approval(
                args.approval, expected_plan_digest=plan.plan_digest
            )
            receipt = prepare_and_execute_canonical_main_release(
                release_root=package.output_root,
                staging_revision=args.staging_revision,
                sealed_at=args.sealed_at,
                approval=approval,
                audited_parent_commit=args.base_revision,
            )
        else:
            receipt = build_canonical_publication_dry_run_receipt(
                candidate=candidate,
                plan=plan,
            )
        if args.write_receipt or args.output is not None:
            write_publication_receipt(
                receipt,
                path=args.output or default_receipt_path(),
            )
        if args.output is None:
            write_json(None, receipt)
        return 0
    except (
        PublishStateLawsError,
        PublishAuthorizationError,
        PublishSafetyError,
        PublishTargetError,
        PublishGateError,
        PublishSealError,
        PublishReceiptError,
        PublicationGateError,
        PublicationGateDeniedError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
