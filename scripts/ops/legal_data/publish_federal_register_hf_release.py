#!/usr/bin/env python3
"""Authorize and execute the additive Federal Register public upload (LCR-065).

Default mode is **offline** (credential-free, no live Hub network contact):

1. Verify the LCR-073 manifest-bound prepublication seal **before** any
   Hub mutation can run. A missing, stale, fixture-only, or post-hoc seal
   fails closed.
2. Invoke the LCR-074 publication gate for the ``federal_main`` phase
   **before** the first Hub write callback.
3. Upload the identical staged candidate additively to
   ``justicedao/ipfs_federal_register`` (public ``main``), preserving
   legacy files and the rollback pin.
4. Bind old / staging / public SHAs, the candidate manifest, and the
   operation list on the Hub receipt. Every upload response must succeed.

Live writes remain opt-in (``--authorize-mutation`` plus environment
credentials) are routed through the shared canonical publisher/runtime.
The default CLI never contacts the live
Hub: validation uses an in-memory add-only public Hub.

This script never:

* deletes, force-pushes, rewrites history, or changes visibility;
* embeds or logs Hub tokens;
* treats credentials as CLI flags (environment-only);
* proceeds to a Hub write unless the LCR-073 seal and LCR-074
  ``federal_main`` gate both authorized the mutation;
* accepts a post-hoc seal created after mutation.

Validation gate (no network)::

    python scripts/ops/legal_data/publish_federal_register_hf_release.py --check-receipt
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
from typing import Any, Final, Optional

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (  # noqa: E402
    DEFAULT_OBSERVATION_CUTOFF,
    PREVIOUS_PUBLIC_PIN,
    canonical_json_dumps,
    digest_mapping,
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
    materialize_federal_register_main_controls,
    plan_federal_register_publication_dry_run,
    prepare_federal_register_publication_package,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (  # noqa: E402
    FEDERAL_DATASET_REPO_ID,
    FEDERAL_PREPUBLICATION_SEAL_PATH,
    PublicationGateDecision,
    PublicationGateDeniedError,
    PublicationGateError,
    PublicationPhase,
    SECRET_ENV_NAMES as GATE_SECRET_ENV_NAMES,
    example_authorized_request,
    reject_credentials_in_payload as gate_reject_credentials,
    require_publication_gate,
)
from scripts.ops.legal_data.seal_federal_register_prepublication import (  # noqa: E402
    PrepublicationSealError,
    SealBindingError,
    check_federal_prepublication_seal,
    default_seal_path,
    load_json_mapping as load_seal_mapping,
    load_staging_canary,
)
from scripts.ops.legal_data.stage_federal_register_hf_release import (  # noqa: E402
    build_fixture_release,
    canonical_plan_inventory,
    load_candidate_report,
    load_publication_approval,
    plan_stage_from_candidate,
    reject_credentials_in_payload as stage_reject_credentials,
    reject_secrets_in_argv as stage_reject_secrets_in_argv,
    release_file_bytes,
    require_immutable_revision as _stage_require_immutable_revision,
)


# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "LCR-065"
GOAL_ID: Final = "LCR-G140"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "publish_federal_register_hf_release.py"
CODE_VERSION: Final = "1"
SCHEMA_VERSION: Final = "federal-register-hf-public-upload/v1"
SEAL_TASK_ID: Final = "LCR-073"
GATE_TASK_ID: Final = "LCR-074"
PUBLICATION_PHASE: Final = PublicationPhase.FEDERAL_MAIN.value
AUTHORIZED_OPERATION: Final = "additive_main_upload"
ADD_ONLY_OPERATION: Final = "add_only_upload"

RECEIPT_SCHEMA: Final = (
    "ipfs_datasets_py/legal-corpora-reindex-federal-publication-receipt@1"
)
PLAN_SCHEMA: Final = (
    "ipfs_datasets_py/legal-corpora-reindex-federal-publication-plan@1"
)

DEFAULT_DATASET_REPO: Final = FEDERAL_DATASET_REPO_ID
if DEFAULT_DATASET_REPO != "justicedao/ipfs_federal_register":
    raise RuntimeError("sealed Federal Register target drifted from the publication gate")

PRODUCTION_REVISION: Final = PREVIOUS_PUBLIC_PIN
PUBLIC_BRANCH: Final = "main"
DEFAULT_STAGING_BRANCH: Final = "stage/federal-register-ir-graphrag-v2"
DEFAULT_PACKAGE_VERSION: Final = "2"

DEFAULT_RECEIPT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_publication_receipt.json"
)
DEFAULT_CANDIDATE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_candidate.json"
)
DEFAULT_SEAL_RELPATH: Final = Path(FEDERAL_PREPUBLICATION_SEAL_PATH)
DEFAULT_CANARY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_staging_canary.json"
)

DEPENDS_ON: Final[tuple[str, ...]] = ("LCR-064", "LCR-073", "LCR-074", "LCR-084")

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
            "FEDERAL_REGISTER_PUBLICATION_AUTHORIZATION",
            "FEDERAL_REGISTER_HF_TOKEN",
            "HF_TOKEN",
            "HUGGING_FACE_HUB_TOKEN",
            "HUGGINGFACE_HUB_TOKEN",
            "HUGGINGFACE_TOKEN",
            "HUGGINGFACEHUB_API_TOKEN",
        )
    )
)
AUTHORIZATION_ENV: Final = "FEDERAL_REGISTER_PUBLICATION_AUTHORIZATION"
MAX_REPORT_BYTES: Final = 1048576

_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"publication_authorization|staging_authorization)s?$",
    re.IGNORECASE,
)
_DATASET_ID_RE = re.compile(r"^[A-Za-z0-9](?:[-\w.]{0,38}[A-Za-z0-9])?/[A-Za-z0-9._-]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ABSOLUTE_PATH_MARKERS: Final = (
    "/home/",
    "/tmp/",
    "/var/",
    "/users/",
    "c:\\",
    "c:/",
    "file://",
)

# Process-local records that LCR-073 and LCR-074 ran before any Hub callback.
_SEAL_INVOCATIONS: list[dict[str, Any]] = []
_GATE_INVOCATIONS: list[dict[str, Any]] = []


class PublishFederalRegisterError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class PublishAuthorizationError(PublishFederalRegisterError):
    """Raised when mutation is attempted without opt-in authorization."""


class PublishSafetyError(PublishFederalRegisterError):
    """Raised when a plan would delete, force-push, or change visibility."""


class PublishTargetError(PublishFederalRegisterError):
    """Raised when the public target is not the authorized Federal repo/branch."""


class PublishGateError(PublishFederalRegisterError):
    """Raised when the LCR-074 federal_main gate refuses mutation."""


class PublishSealError(PublishFederalRegisterError):
    """Raised when the LCR-073 seal is missing, stale, or post-hoc."""


class PublishReceiptError(PublishFederalRegisterError):
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
        raise PublishFederalRegisterError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublishFederalRegisterError(f"cannot read JSON {target}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PublishFederalRegisterError(f"JSON root must be an object: {target}")
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
    body = {
        key: value
        for key, value in dict(payload).items()
        if key not in {"content_digest", "digest", "report_digest_sha256"}
    }
    return hashlib.sha256(canonical_json_dumps(body).encode("utf-8")).hexdigest()


def inventory_digest(items: Sequence[Any]) -> str:
    return hashlib.sha256(
        canonical_json_dumps(list(items)).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# Credential / safety guards
# ---------------------------------------------------------------------------


def require_immutable_revision(value: Any, *, name: str = "revision") -> str:
    try:
        return _stage_require_immutable_revision(value, name=name)
    except Exception as exc:
        raise PublishFederalRegisterError(str(exc)) from exc


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
        stage_reject_credentials(value, label=label)
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
        "federal_register_publication_authorization=",
        "federal_register_hf_token=",
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
    try:
        stage_reject_secrets_in_argv(argv)
    except Exception as exc:
        raise PublishSafetyError(str(exc)) from exc


def _normalize_dataset_id(value: str, *, label: str = "target_repo") -> str:
    text = str(value or "").strip()
    if not _DATASET_ID_RE.fullmatch(text):
        raise PublishFederalRegisterError(f"{label} must be owner/name, got {value!r}")
    if text != DEFAULT_DATASET_REPO:
        raise PublishTargetError(
            f"{label} must be the authorized Federal Register dataset "
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
            f"Federal public upload must target {PUBLIC_BRANCH!r}, got {branch!r}"
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
                f"operation is forbidden for Federal Register public upload: {raw!r}"
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
            "LCR-073 federal prepublication seal was not verified before Hub mutation"
        )
    last_seal = _SEAL_INVOCATIONS[-1]
    if last_seal.get("verified_before_first_mutation") is not True:
        raise PublishSealError("LCR-073 seal verification is not marked pre-mutation")
    if str(last_seal.get("timing") or "") != "before_mutation":
        raise PublishSealError(
            "refusing post-hoc or untimed LCR-073 seal before Hub mutation"
        )
    if not _GATE_INVOCATIONS:
        raise PublishGateError(
            "LCR-074 federal_main gate was not invoked before Hub mutation"
        )
    last_gate = _GATE_INVOCATIONS[-1]
    if last_gate.get("phase") != PUBLICATION_PHASE:
        raise PublishGateError(
            "LCR-074 was invoked for the wrong phase before mutation: "
            f"{last_gate.get('phase')!r}"
        )
    if last_gate.get("invoked_before_first_mutation") is not True:
        raise PublishGateError(
            "LCR-074 federal_main gate is not marked as invoked before first mutation"
        )


# ---------------------------------------------------------------------------
# LCR-073 seal — must run before the first Hub mutation
# ---------------------------------------------------------------------------


def load_federal_prepublication_seal(
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
    except PrepublicationSealError as exc:
        raise PublishSealError(f"LCR-073 seal is unavailable: {exc}") from exc
    reject_credentials_in_payload(seal, label="federal_prepublication_seal")
    return seal


def assert_seal_precedes_mutation(seal: Mapping[str, Any]) -> dict[str, Any]:
    """Refuse a missing, fixture-only, or post-hoc LCR-073 seal."""

    if not isinstance(seal, Mapping) or not seal:
        raise PublishSealError("LCR-073 seal is missing")
    if seal.get("present") is not True:
        raise PublishSealError("LCR-073 seal is not present=true")
    if str(seal.get("task_id") or "") != SEAL_TASK_ID:
        raise PublishSealError(
            f"prepublication seal task_id must be {SEAL_TASK_ID}, "
            f"got {seal.get('task_id')!r}"
        )
    if str(seal.get("phase") or "") != PUBLICATION_PHASE:
        raise PublishSealError(
            f"LCR-073 seal phase must be {PUBLICATION_PHASE}, "
            f"got {seal.get('phase')!r}"
        )
    if seal.get("fixture_only") is True or seal.get("dirty") is True:
        raise PublishSealError("refusing fixture-only or dirty LCR-073 seal")
    if seal.get("status") != "sealed":
        raise PublishSealError(f"LCR-073 seal status is {seal.get('status')!r}")
    timing = str(seal.get("timing") or "")
    if timing != "before_mutation":
        raise PublishSealError(
            f"refusing post-hoc LCR-073 seal (timing={timing!r})"
        )
    if seal.get("no_mutation") is not True or seal.get("mutation_executed") is True:
        raise PublishSealError("LCR-073 seal is not a no-mutation prepublication proof")
    if seal.get("network_mutation") is True:
        raise PublishSealError("LCR-073 seal must not record a network mutation")
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
            f"seal previous public pin must remain {PRODUCTION_REVISION}"
        )
    manifest = str(
        seal.get("final_manifest_digest") or seal.get("manifest_digest") or ""
    ).strip().casefold()
    if not _SHA256_RE.fullmatch(manifest):
        raise PublishSealError("LCR-073 seal is missing a 64-hex manifest digest")
    return {
        "dataset_repo_id": repo,
        "final_manifest_digest": manifest,
        "manifest_digest": manifest,
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
    """Bind the LCR-073 seal to the current candidate and live staging canary."""

    candidate = load_candidate_report(repo_root=repo_root)
    canary = load_staging_canary(repo_root)
    candidate_digest = str(
        candidate.get("final_manifest_digest") or candidate.get("manifest_digest") or ""
    ).strip().casefold()
    seal_digest = str(
        seal.get("final_manifest_digest") or seal.get("manifest_digest") or ""
    ).strip().casefold()
    if candidate_digest != seal_digest:
        raise PublishSealError(
            "LCR-073 seal manifest digest does not match the Federal candidate"
        )
    canary_staging = require_immutable_revision(
        canary.get("staging_revision"), name="canary.staging_revision"
    )
    seal_staging = require_immutable_revision(
        seal.get("staging_revision"), name="seal.staging_revision"
    )
    if canary_staging != seal_staging:
        raise PublishSealError(
            "LCR-073 seal staging revision does not match the live staging canary"
        )
    if canary.get("fixture_only") is True or canary.get("live_staging") is not True:
        raise PublishSealError("LCR-073 seal is not bound to a live staging canary")


def verify_federal_prepublication_seal(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
    require_live_staging_pin: bool = True,
) -> dict[str, Any]:
    """Verify the LCR-073 seal. Callers must invoke this before any Hub write."""

    seal = load_federal_prepublication_seal(path, repo_root=repo_root)
    bound = assert_seal_precedes_mutation(seal)
    try:
        check = check_federal_prepublication_seal(
            path,
            repo_root=repo_root,
            require_live_staging_pin=require_live_staging_pin,
        )
    except SealBindingError as exc:
        raise PublishSealError(
            "LCR-073 federal prepublication seal is stale or unbound: " + str(exc)
        ) from exc
    if str(check.get("manifest_digest") or bound["final_manifest_digest"]) != bound[
        "final_manifest_digest"
    ]:
        raise PublishSealError("LCR-073 check/seal manifest digest drifted")
    if str(check.get("staging_revision") or bound["staging_revision"]) != bound[
        "staging_revision"
    ]:
        raise PublishSealError("LCR-073 check/seal staging revision drifted")
    record = {
        "check": "pass",
        "dataset_repo_id": bound["dataset_repo_id"],
        "final_manifest_digest": bound["final_manifest_digest"],
        "invoked_before_first_mutation": True,
        "live_staging": True,
        "no_mutation": True,
        "ok": True,
        "path": bound["path"],
        "phase": PUBLICATION_PHASE,
        "plan_digest": check["plan_digest"],
        "policy_proof_digest": check["policy_proof_digest"],
        "present": True,
        "previous_public_pin": bound["previous_public_pin"],
        "release_manifest_digest": check["release_manifest_digest"],
        "staging_revision": bound["staging_revision"],
        "status": "sealed",
        "task_id": SEAL_TASK_ID,
        "timing": "before_mutation",
        "verified_before_first_mutation": True,
    }
    _SEAL_INVOCATIONS.append(record)
    return record


# ---------------------------------------------------------------------------
# LCR-074 federal_main gate — must run before the first Hub mutation
# ---------------------------------------------------------------------------


def federal_main_gate_request(
    *,
    manifest_digest: str,
    staging_revision: str,
    previous_public_pin: str = PRODUCTION_REVISION,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Construct the LCR-074 federal_main request bound to seal + manifest."""

    del repo_root  # reserved for canonical-runtime callers
    digest = str(manifest_digest or "").strip().casefold()
    if not _SHA256_RE.fullmatch(digest):
        raise PublishFederalRegisterError(
            "federal main gate requires the candidate 64-hex manifest digest"
        )
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


def invoke_federal_main_gate(
    request: Mapping[str, Any] | None = None,
    *,
    manifest_digest: str | None = None,
    staging_revision: str | None = None,
    repo_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> PublicationGateDecision:
    """Evaluate the LCR-074 gate for the Federal main phase.

    Callers must invoke this (or :func:`authorize_federal_main_upload`)
    **after** LCR-073 seal verification and **before** the first Hub mutation.
    """

    payload = (
        dict(request)
        if request is not None
        else federal_main_gate_request(
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
            "LCR-074 federal_main gate refused before Hub mutation: " + str(exc)
        ) from exc
    except PublicationGateError as exc:
        raise PublishGateError(f"LCR-074 federal_main gate error: {exc}") from exc
    if not decision.authorized or not decision.network_mutation_permitted:
        raise PublishGateError(
            "LCR-074 federal_main gate did not authorize network mutation"
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


# ---------------------------------------------------------------------------
# Fake Hub (offline add-only public transport)
# ---------------------------------------------------------------------------


class FakeFederalRegisterPublicHub:
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
    ) -> dict[str, Any]:
        _normalize_dataset_id(repo_id)
        assert_public_branch(branch)
        require_immutable_revision(base_revision, name="base_revision")
        if batch_size < 1:
            raise PublishFederalRegisterError("batch_size must be >= 1")

        uploaded: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []
        items = sorted(files.items(), key=lambda item: item[0])
        for offset in range(0, len(items), batch_size):
            batch = items[offset : offset + batch_size]
            for relative_path, content in batch:
                path = str(relative_path)
                if path.startswith("/") or ".." in Path(path).parts:
                    raise PublishSafetyError(f"unsafe public path: {path!r}")
                digest = hashlib.sha256(content).hexdigest()
                existing = self.files.get(path)
                if existing is not None:
                    existing_digest = hashlib.sha256(existing).hexdigest()
                    if existing_digest != digest:
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
                self.files[path] = content
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
        binding = {
            "base_revision": base_revision,
            "branch": PUBLIC_BRANCH,
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


def build_canonical_main_plan(
    *,
    release: Any,
    output_root: Path | str,
    audited_parent_commit: str = PRODUCTION_REVISION,
    candidate: Mapping[str, Any] | None = None,
    api: Any | None = None,
) -> tuple[
    FederalRegisterPublicationPackage,
    HuggingFaceReleasePublisher,
    PublicationPlan,
]:
    """Build the exact package-backed Federal main plan without network I/O."""

    parent = require_immutable_revision(
        audited_parent_commit,
        name="audited_parent_commit",
    )
    if parent != PRODUCTION_REVISION:
        raise PublishTargetError(
            "Federal main plan must retain the sealed previous public parent"
        )
    package = prepare_federal_register_publication_package(
        release,
        output_root=output_root,
    )
    if candidate is not None:
        nested = candidate.get("candidate")
        release_digest = str(
            (nested.get("manifest_digest") if isinstance(nested, Mapping) else None)
            or candidate.get("manifest_digest")
            or ""
        ).strip().casefold()
        if release_digest != package.manifest_digest:
            raise PublishReceiptError(
                "Federal candidate and canonical main package differ"
            )
    plan = plan_federal_register_publication_dry_run(
        package,
        audited_parent_commit=parent,
        target_revision=PUBLIC_BRANCH,
        api=api,
    )
    publisher = HuggingFaceReleasePublisher(
        profile=federal_register_publication_profile(),
        api=api,
    )
    if (
        plan.repository_id != DEFAULT_DATASET_REPO
        or plan.target_revision != PUBLIC_BRANCH
        or plan.audited_parent_commit != parent
        or plan.release_sha256 != package.manifest_digest
        or not plan.operations
    ):
        raise PublishReceiptError("canonical Federal main plan identity drifted")
    return package, publisher, plan


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

    if type(dry_run) is not bool:
        raise PublishFederalRegisterError("dry_run must be boolean")
    report = dict(candidate) if candidate is not None else load_candidate_report(
        repo_root=repo_root
    )
    if release is None:
        release = build_fixture_release(repo_root=repo_root)
    dataset_id = _normalize_dataset_id(
        target_repo or str(report.get("dataset_repo_id") or DEFAULT_DATASET_REPO)
    )
    branch = assert_public_branch(public_branch)
    old_sha = require_immutable_revision(base_revision, name="old_sha")
    if old_sha != PRODUCTION_REVISION:
        raise PublishTargetError(
            f"old SHA must remain the sealed previous public pin {PRODUCTION_REVISION}"
        )
    staged = require_immutable_revision(
        staging_revision
        or report.get("staging_revision")
        or PRODUCTION_REVISION,
        name="staging_sha",
    )
    seal_token = publication_seal or DEFAULT_SEAL_RELPATH.as_posix()
    staged_plan = plan_stage_from_candidate(
        report,
        release=release,
        target_repo=dataset_id,
        staging_branch=DEFAULT_STAGING_BRANCH,
        base_revision=old_sha,
        package_version=DEFAULT_PACKAGE_VERSION,
        publication_seal=seal_token,
        dry_run=dry_run,
        repo_root=repo_root,
    )
    artifacts = list(staged_plan["artifacts"])
    operations = _assert_operations_add_only(
        [item.get("operation") or ADD_ONLY_OPERATION for item in artifacts]
        or [ADD_ONLY_OPERATION]
    )
    for item in artifacts:
        path = str(item.get("relative_path") or "")
        if not path or path.startswith("/") or ".." in Path(path).parts:
            raise PublishSafetyError(f"unexpected public path: {path!r}")
        item["operation"] = ADD_ONLY_OPERATION
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
        "legacy_files_deleted": False,
        "manifest_digest": staged_plan["manifest_digest"],
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
                "manifest_digest": staged_plan["manifest_digest"],
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
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "goal_id": GOAL_ID,
        "legacy_files_deleted": False,
        "manifest_digest": staged_plan["manifest_digest"],
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
        "release_root_cid": staged_plan["release_root_cid"],
        "rollback_target": old_sha,
        "schema": PLAN_SCHEMA,
        "staging_branch": DEFAULT_STAGING_BRANCH,
        "staging_revision": staged,
        "staging_sha": staged,
        "task_id": TASK_ID,
        "target_repo": dataset_id,
        "upload_bytes": staged_plan["upload_bytes"],
        "upload_file_count": staged_plan["upload_file_count"],
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
    hub: FakeFederalRegisterPublicHub | None = None,
    authorize_mutation: bool = False,
    dry_run: bool = True,
    repo_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
    batch_size: int = 32,
) -> dict[str, Any]:
    """Publish the candidate. Seal then gate run before the first Hub write."""

    reset_invocations()
    seal_record = verify_federal_prepublication_seal(
        repo_root=repo_root,
        require_live_staging_pin=True,
    )
    if str(plan.get("manifest_digest") or "") != seal_record["final_manifest_digest"]:
        raise PublishSealError(
            "public plan manifest digest is not the LCR-073 sealed digest"
        )
    if str(plan.get("staging_revision") or "") != seal_record["staging_revision"]:
        raise PublishSealError(
            "public plan staging SHA is not the LCR-073 sealed staging revision"
        )
    request = federal_main_gate_request(
        manifest_digest=str(plan["manifest_digest"]),
        staging_revision=str(plan["staging_revision"]),
        previous_public_pin=str(plan["old_sha"]),
        repo_root=repo_root,
    )
    gate_decision = invoke_federal_main_gate(request, environ=environ)
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
    if type(hub) is not FakeFederalRegisterPublicHub:
        raise PublishAuthorizationError(
            "protected publication requires execute_canonical_federal_publication; "
            "execute_public_upload accepts only the exact in-memory test transport"
        )
    transport = hub
    files = release_file_bytes(release)

    uploaded_receipt = transport.upload_files(
        files,
        repo_id=str(plan["target_repo"]),
        branch=str(plan["public_branch"]),
        base_revision=str(plan["old_sha"]),
        batch_size=batch_size,
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
    hub: FakeFederalRegisterPublicHub | None = None,
) -> dict[str, Any]:
    public_sha = require_immutable_revision(public_revision, name="public_sha")
    old_sha = require_immutable_revision(plan["old_sha"], name="old_sha")
    staging_sha = require_immutable_revision(
        plan["staging_revision"], name="staging_sha"
    )
    if seal.get("verified_before_first_mutation") is not True:
        raise PublishSealError(
            "publication receipt missing LCR-073 verification before first mutation"
        )
    if str(seal.get("timing") or "") != "before_mutation":
        raise PublishSealError("publication receipt must not bind a post-hoc seal")
    if not gate.get("invoked_before_first_mutation"):
        raise PublishGateError(
            "publication receipt missing LCR-074 invocation before first mutation"
        )
    if str(gate.get("phase") or "") != PUBLICATION_PHASE:
        raise PublishGateError("publication receipt gate phase must be federal_main")
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
    if dry_run and not mutation_executed:
        status = "dry_run_only"
    elif live_network:
        status = "published"
    else:
        status = "fixture_published"
    receipt: dict[str, Any] = {
        "acceptance": {
            "credentials_environment_only": True,
            "every_upload_response_succeeded": not failed,
            "gate_invoked_before_first_mutation": True,
            "lcr073_seal_verified_before_mutation": True,
            "lcr074_federal_main_phase": True,
            "legacy_files_deleted": False,
            "no_absolute_path_or_secret": True,
            "no_credential": True,
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
        "final_manifest_digest": plan["manifest_digest"],
        "fixture_only": not live_network,
        "force_push": False,
        "gate": dict(gate),
        "goal_id": GOAL_ID,
        "legacy_files_deleted": False,
        "live_network": live_network,
        "live_publication": bool(live_network and mutation_executed),
        "manifest_digest": plan["manifest_digest"],
        "mutation_executed": mutation_executed,
        "network_required": live_network,
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
        "transport": (
            "canonical_hub_runtime" if live_network else "in_memory_fixture_public"
        ),
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
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise PublishReceiptError("publication receipt schema is not publication-bindable")
    digest = publication_digest(receipt)
    receipt["content_digest"] = digest
    receipt["digest"] = digest
    receipt["report_digest_sha256"] = digest
    reject_credentials_in_payload(receipt, label="federal_publication_receipt")
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
    seal_record = verify_federal_prepublication_seal(
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
    request = federal_main_gate_request(
        manifest_digest=str(plan["manifest_digest"]),
        staging_revision=str(plan["staging_revision"]),
        previous_public_pin=str(plan["old_sha"]),
        repo_root=repo_root,
    )
    decision = invoke_federal_main_gate(request)
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
    seal = load_federal_prepublication_seal(repo_root=repo_root)
    bound = assert_seal_precedes_mutation(seal)
    release = build_fixture_release(repo_root=repo_root)
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
            hub=FakeFederalRegisterPublicHub(),
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
    if receipt.get("fixture_only") is True and target.resolve() == default_receipt_path(
        repo_root
    ):
        raise PublishReceiptError(
            "refusing to replace canonical publication evidence with a fixture receipt"
        )
    write_json(target, receipt)
    return target


def check_publication_receipt(
    receipt: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
    require_live: bool = True,
) -> dict[str, Any]:
    """Validate the sealed receipt without replaying a protected write."""

    observed = (
        dict(receipt)
        if receipt is not None
        else load_json_mapping(default_receipt_path(repo_root))
    )
    mismatches: list[str] = []
    expected_scalars = {
        "schema": RECEIPT_SCHEMA,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "target_repo": DEFAULT_DATASET_REPO,
        "phase": PUBLICATION_PHASE,
        "operation": AUTHORIZED_OPERATION,
        "public_branch": PUBLIC_BRANCH,
        "previous_public_pin": PRODUCTION_REVISION,
    }
    for key, expected in expected_scalars.items():
        if observed.get(key) != expected:
            mismatches.append(key)
    if list(observed.get("operations") or []) != [AUTHORIZED_OPERATION]:
        mismatches.append("operations")
    if observed.get("visibility_changed") is True:
        mismatches.append("visibility_changed")
    if observed.get("legacy_files_deleted") is True:
        mismatches.append("legacy_files_deleted")
    if observed.get("deletes") is True or observed.get("force_push") is True:
        mismatches.append("destructive_operation")
    if observed.get("unexpected_operations"):
        mismatches.append("unexpected_operations")
    if observed.get("upload_responses_succeeded") is not True:
        mismatches.append("upload_responses_succeeded")
    responses = list(observed.get("upload_responses") or [])
    if not responses:
        mismatches.append("upload_responses")
    for item in responses:
        if not isinstance(item, Mapping) or item.get("succeeded") is not True:
            mismatches.append("upload_responses.succeeded")
            continue
        path = str(item.get("relative_path") or "")
        digest = str(item.get("sha256") or "")
        if not path or path.startswith("/") or ".." in Path(path).parts:
            mismatches.append("upload_responses.relative_path")
        if not _SHA256_RE.fullmatch(digest):
            mismatches.append("upload_responses.sha256")
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
    old_sha = require_immutable_revision(observed.get("old_sha"), name="old_sha")
    staging_sha = require_immutable_revision(
        observed.get("staging_sha"), name="staging_sha"
    )
    public_sha = require_immutable_revision(
        observed.get("public_sha"), name="public_sha"
    )
    if old_sha != PRODUCTION_REVISION:
        mismatches.append("old_sha")
    if public_sha in {old_sha, staging_sha}:
        mismatches.append("public_sha")
    if str(observed.get("public_revision") or "") != public_sha:
        mismatches.append("public_revision")
    manifest_digest = str(observed.get("manifest_digest") or "")
    if not _SHA256_RE.fullmatch(manifest_digest):
        mismatches.append("manifest_digest")
    if str(observed.get("final_manifest_digest") or "") != manifest_digest:
        mismatches.append("final_manifest_digest")
    recorded_digest = str(observed.get("content_digest") or "")
    if not _SHA256_RE.fullmatch(recorded_digest):
        mismatches.append("content_digest")
    elif publication_digest(observed) != recorded_digest:
        mismatches.append("content_digest")
    for key in ("digest", "report_digest_sha256"):
        if str(observed.get(key) or "") != recorded_digest:
            mismatches.append(key)

    if require_live:
        if observed.get("fixture_only") is not False:
            mismatches.append("fixture_only")
        if observed.get("live_network") is not True:
            mismatches.append("live_network")
        if observed.get("live_publication") is not True:
            mismatches.append("live_publication")
        if observed.get("mutation_executed") is not True:
            mismatches.append("mutation_executed")
        if observed.get("remote_write_contacted") is not True:
            mismatches.append("remote_write_contacted")
        if observed.get("status") != "published":
            mismatches.append("status")
        if str(observed.get("transport") or "") != "canonical_hub_runtime":
            mismatches.append("transport")
        candidate = load_candidate_report(repo_root=repo_root)
        if str(candidate.get("manifest_digest") or "") != manifest_digest:
            mismatches.append("candidate.manifest_digest")
        candidate_manifest_digest = str(
            observed.get("candidate_manifest_digest") or ""
        )
        if (
            not _SHA256_RE.fullmatch(candidate_manifest_digest)
            or str(candidate.get("content_digest") or "")
            != candidate_manifest_digest
        ):
            mismatches.append("candidate.content_digest")
        seal_record = verify_federal_prepublication_seal(
            repo_root=repo_root,
            require_live_staging_pin=True,
        )
        if seal_record["final_manifest_digest"] != candidate_manifest_digest:
            mismatches.append("seal.final_manifest_digest")
        if seal_record.get("release_manifest_digest") != manifest_digest:
            mismatches.append("seal.release_manifest_digest")
        if seal_record.get("plan_digest") != observed.get("plan_digest"):
            mismatches.append("seal.plan_digest")
        if seal_record.get("policy_proof_digest") != observed.get(
            "policy_proof_digest"
        ):
            mismatches.append("seal.policy_proof_digest")
        if seal_record["staging_revision"] != staging_sha:
            mismatches.append("seal.staging_revision")
    reject_credentials_in_payload(observed, label="publication_receipt_check")
    if mismatches:
        raise PublishReceiptError(
            "federal publication receipt check failed: "
            + ", ".join(sorted(set(mismatches)))
        )
    return {
        "acceptance": dict(observed.get("acceptance") or {}),
        "check": "pass",
        "digest": recorded_digest,
        "every_upload_response_succeeded": True,
        "gate_invoked_before_first_mutation": True,
        "goal_id": GOAL_ID,
        "manifest_digest": manifest_digest,
        "mismatches": [],
        "ok": True,
        "old_sha": old_sha,
        "phase": PUBLICATION_PHASE,
        "public_sha": public_sha,
        "require_live": require_live,
        "seal_verified_before_first_mutation": True,
        "staging_sha": staging_sha,
        "status": observed.get("status"),
        "task_id": TASK_ID,
        "target_repo": DEFAULT_DATASET_REPO,
    }


def check_public(
    receipt: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Public-revision receipt check used by LCR-G140 composition."""

    return check_publication_receipt(receipt, repo_root=repo_root)


def run_receipt_self_check(*, repo_root: Path | str | None = None) -> dict[str, Any]:
    """Read and validate the live receipt; never create evidence during check."""

    result = check_publication_receipt(repo_root=repo_root, require_live=True)
    result["path"] = DEFAULT_RECEIPT_RELPATH.as_posix()
    return result


def execute_canonical_federal_publication(
    publisher: Any,
    publication_plan: Any,
    *,
    approval: Any,
    local_root: Path | str,
    policy_proof_digest: str,
    live_policy_proof: Any = None,
    commit_message: str | None = None,
) -> Any:
    """Execute the one protected Federal main commit via shared authority."""

    executor = getattr(
        publisher,
        "execute_canonical_legal_corpora_mutation",
        None,
    )
    if not callable(executor):
        raise PublishAuthorizationError(
            "shared canonical legal-corpora publisher is unavailable"
        )
    return executor(
        publication_plan,
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
    plan: PublicationPlan,
    controls: FederalRegisterCanonicalControlBundle,
    mutation_receipt: CanonicalLegalCorporaMutationReceipt,
) -> dict[str, Any]:
    """Build the live LCR-065 receipt from one exact runtime mutation."""

    if type(plan) is not PublicationPlan:
        raise PublishReceiptError("canonical PublicationPlan is required")
    if type(controls) is not FederalRegisterCanonicalControlBundle:
        raise PublishReceiptError("canonical Federal main controls are required")
    if type(mutation_receipt) is not CanonicalLegalCorporaMutationReceipt:
        raise PublishReceiptError("canonical Federal main mutation receipt is required")
    mutation = mutation_receipt.to_dict()
    if (
        mutation.get("method") != "create_commit"
        or mutation.get("operation") != AUTHORIZED_OPERATION
        or mutation.get("parent_commit") != plan.audited_parent_commit
        or mutation.get("phase") != PUBLICATION_PHASE
        or mutation.get("plan_digest") != plan.plan_digest
        or mutation.get("policy_proof_digest") != controls.policy_proof_digest
        or mutation.get("release_manifest_digest")
        != controls.release_manifest_digest
        or mutation.get("repository_id") != plan.repository_id
        or mutation.get("revision") != PUBLIC_BRANCH
        or mutation.get("runtime_authorized") is not True
    ):
        raise PublishReceiptError(
            "canonical Federal main receipt differs from the plan and controls"
        )
    if (
        controls.phase != PUBLICATION_PHASE
        or controls.plan_digest != plan.plan_digest
        or controls.release_manifest_digest != plan.release_sha256
        or controls.staging_revision == ""
    ):
        raise PublishReceiptError("canonical Federal main controls drifted")
    old_sha = require_immutable_revision(
        plan.audited_parent_commit,
        name="old_sha",
    )
    staging_sha = require_immutable_revision(
        controls.staging_revision,
        name="staging_sha",
    )
    public_sha = require_immutable_revision(
        mutation["resulting_commit_sha"],
        name="public_sha",
    )
    if old_sha != PRODUCTION_REVISION or public_sha in {old_sha, staging_sha}:
        raise PublishReceiptError(
            "canonical public SHA must be new and preserve both rollback pins"
        )
    operations = canonical_plan_inventory(plan)
    upload_responses = [
        {
            "relative_path": item["relative_path"],
            "remote_path": item["remote_path"],
            "sha256": item["sha256"],
            "status": "ok",
            "succeeded": True,
        }
        for item in operations
    ]
    compact_files = [
        {
            "operation": ADD_ONLY_OPERATION,
            "relative_path": item["relative_path"],
            "sha256": item["sha256"],
        }
        for item in operations
    ]
    receipt: dict[str, Any] = {
        "acceptance": {
            "credentials_environment_only": True,
            "every_upload_response_succeeded": True,
            "gate_invoked_before_first_mutation": True,
            "lcr073_seal_verified_before_mutation": True,
            "lcr074_federal_main_phase": True,
            "legacy_files_deleted": False,
            "no_absolute_path_or_secret": True,
            "no_post_hoc_seal": True,
            "no_unexpected_content": True,
            "no_unexpected_operations": True,
            "no_unexpected_path": True,
            "old_staging_public_shas_bound": True,
            "rollback_pin_preserved": True,
            "secrets_absent": True,
            "visibility_unchanged": True,
        },
        "additive_only": True,
        "authorize_mutation": True,
        "base_revision": old_sha,
        "candidate_manifest_digest": controls.candidate_manifest_digest,
        "candidate_path": controls.candidate_path,
        "code_version": CODE_VERSION,
        "compact_recipe": True,
        "credentials_environment_only": True,
        "dataset_repo_id": plan.repository_id,
        "deletes": False,
        "depends_on": list(DEPENDS_ON),
        "dirty": False,
        "dry_run": False,
        "file_count": len(operations),
        "files_digest": inventory_digest(compact_files),
        "final_manifest_digest": controls.release_manifest_digest,
        "fixture_only": False,
        "force_push": False,
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
        "live_publication": True,
        "manifest_digest": controls.release_manifest_digest,
        "mutation_executed": True,
        "mutation_receipt": mutation,
        "network_required": True,
        "old_sha": old_sha,
        "operation": AUTHORIZED_OPERATION,
        "operations": [AUTHORIZED_OPERATION],
        "phase": PUBLICATION_PHASE,
        "plan_digest": plan.plan_digest,
        "policy_proof_digest": controls.policy_proof_digest,
        "previous_public_pin": old_sha,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_branch": PUBLIC_BRANCH,
        "public_revision": public_sha,
        "public_sha": public_sha,
        "refill_findings": [],
        "release_manifest_digest": controls.release_manifest_digest,
        "remote_write_contacted": True,
        "rollback": {
            "additive_only": True,
            "previous_public_pin": old_sha,
            "rollback_target": old_sha,
        },
        "schema": RECEIPT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "seal": {
            "content_digest": controls.seal_content_digest,
            "path": controls.seal_path,
            "present": True,
            "staging_revision": staging_sha,
            "task_id": SEAL_TASK_ID,
            "timing": "before_mutation",
            "verified_before_first_mutation": True,
        },
        "secret_redacted": True,
        "skipped": list(plan.skipped_exact_matches),
        "skipped_count": len(plan.skipped_exact_matches),
        "staging_branch": DEFAULT_STAGING_BRANCH,
        "staging_candidate_digest": controls.staging_candidate_digest,
        "staging_revision": staging_sha,
        "staging_sha": staging_sha,
        "status": "published",
        "target": plan.repository_id,
        "target_repo": plan.repository_id,
        "task_id": TASK_ID,
        "tokens_used": False,
        "transport": "canonical_hub_runtime",
        "unexpected_operations": [],
        "upload_bytes": int(plan.cost_receipt.get("upload_bytes", 0)),
        "upload_file_count": len(operations),
        "upload_responses": upload_responses,
        "upload_responses_succeeded": True,
        "uploaded": compact_files,
        "uploaded_count": len(compact_files),
        "visibility_changed": False,
    }
    digest = publication_digest(receipt)
    receipt["content_digest"] = digest
    receipt["digest"] = digest
    receipt["report_digest_sha256"] = digest
    reject_credentials_in_payload(receipt, label="canonical_publication_receipt")
    return receipt


def execute_canonical_main_release(
    *,
    release: Any,
    output_root: Path | str,
    approval: PublicationApproval,
    staging_revision: str,
    sealed_at: str,
    repository_root: Path | str = REPOSITORY_ROOT,
    audited_parent_commit: str = PRODUCTION_REVISION,
) -> dict[str, Any]:
    """Materialize candidate B/seal, then execute one canonical main commit."""

    root = Path(repository_root).expanduser().resolve()
    candidate = load_candidate_report(repo_root=root)
    package, publisher, plan = build_canonical_main_plan(
        release=release,
        output_root=output_root,
        audited_parent_commit=audited_parent_commit,
        candidate=candidate,
    )
    if approval.plan_digest != plan.plan_digest:
        raise PublishAuthorizationError("approval does not bind the Federal main plan")
    controls = materialize_federal_register_main_controls(
        package,
        plan,
        repository_root=root,
        staging_revision=staging_revision,
        sealed_at=sealed_at,
    )
    seal_check = verify_federal_prepublication_seal(
        repo_root=root,
        require_live_staging_pin=True,
    )
    if (
        seal_check.get("final_manifest_digest")
        != controls.candidate_manifest_digest
        or seal_check.get("release_manifest_digest")
        != controls.release_manifest_digest
        or seal_check.get("plan_digest") != controls.plan_digest
        or seal_check.get("policy_proof_digest") != controls.policy_proof_digest
        or seal_check.get("staging_revision") != controls.staging_revision
    ):
        raise PublishSealError("strict LCR-073 Federal control binding drifted")
    mutation = execute_canonical_federal_publication(
        publisher,
        plan,
        approval=approval,
        local_root=package.output_root,
        policy_proof_digest=controls.policy_proof_digest,
    )
    return build_canonical_publication_receipt(
        plan=plan,
        controls=controls,
        mutation_receipt=mutation,
    )


def legal_corpora_rollback_status(
    receipt: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Name the preserved rollback pin for LCR-G140 refill/status composition."""

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
        prog="publish_federal_register_hf_release.py",
        description=(
            "Authorize and execute the additive Federal Register public "
            "upload after the LCR-073 seal and LCR-074 federal_main gate."
        ),
    )
    parser.add_argument(
        "--check-receipt",
        action="store_true",
        help=(
            "Read and verify the existing live receipt at "
            f"{DEFAULT_RECEIPT_RELPATH.as_posix()}; never replay a write."
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
        help="Alias for --check-receipt (LCR-G140 public-pin composition).",
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
        help=f"Write {DEFAULT_RECEIPT_RELPATH.as_posix()}",
    )
    parser.add_argument(
        "--authorize-mutation",
        action="store_true",
        help=(
            "Opt in to public mutation. Requires "
            f"${AUTHORIZATION_ENV} and still verifies LCR-073 then LCR-074 first."
        ),
    )
    parser.add_argument(
        "--fake-hub",
        action="store_true",
        help="Reserved test-only transport; the production CLI always refuses it.",
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
        help="Override path to federal_candidate.json",
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
    except PublishFederalRegisterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parser = build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code or 0)

    check_receipt = bool(args.check_receipt or args.check or args.check_public)
    try:
        if check_receipt:
            result = run_receipt_self_check()
            if args.check_public:
                public = check_public(repo_root=None)
                result["check_public"] = public.get("check")
                result["rollback"] = legal_corpora_rollback_status().get("rollback_target")
            write_json(args.output, result)
            return 0 if result.get("check") == "pass" else 1

        if args.fake_hub:
            raise PublishAuthorizationError(
                "--fake-hub is test-only and unavailable from the production CLI"
            )
        candidate = load_candidate_report(args.candidate)
        seal_record = verify_federal_prepublication_seal(require_live_staging_pin=True)
        plan = plan_public_from_candidate(
            candidate,
            target_repo=args.target_repo,
            public_branch=args.public_branch,
            base_revision=args.base_revision,
            staging_revision=seal_record["staging_revision"],
            publication_seal=DEFAULT_SEAL_RELPATH.as_posix(),
            dry_run=not args.authorize_mutation,
        )
        release = build_fixture_release()
        want_mutate = bool(args.authorize_mutation)
        if want_mutate:
            assert_mutation_authorized(authorize_mutation=True)
            raise PublishAuthorizationError(
                "standalone live publication requires the exact in-memory "
                "production release, approval, staging pin, and seal time; call "
                "execute_canonical_main_release so the commit passes the shared runtime"
            )
        receipt = execute_public_upload(
            plan,
            release=release,
            hub=None,
            authorize_mutation=want_mutate,
            dry_run=not want_mutate or args.dry_run,
            batch_size=int(args.batch_size),
        )
        if args.write_receipt or args.output is not None:
            write_publication_receipt(receipt, path=args.output)
        write_json(args.output if not args.write_receipt else None, receipt)
        return 0
    except (
        PublishFederalRegisterError,
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
