"""Additive Hugging Face publication and credential-safety policy (LCR-008).

Owns the fail-closed authorization and transaction policy for live mutations
against ``justicedao/ipfs_state_laws``. Upload implementations (LCR-040+)
must invoke :func:`evaluate_live_mutation` / :func:`require_live_mutation`
before any Hub write.

Design invariants
-----------------
* **Staging-first**: public (main) uploads require a passed staging canary
  bound to the same final manifest digest and an immutable staging SHA.
* **Exact-51 coverage**: subset or superset jurisdiction sets refuse mutation.
* **Final manifest authorization**: live mutation is bound to an explicit
  final (or candidate) manifest digest recorded in the authorization surface.
* **Secret redaction**: credentials never appear in argv, plans, receipts,
  logs, or authorization records; tokens are environment-only.
* **Additive only**: deletion, force-push, history rewrite, and visibility
  changes are structurally forbidden.
* **Rollback pin**: the previous public pin
  ``42f0546acc7c6cd55627eaf51fb820d5613b9021`` must be preserved.

This module performs no network I/O and never reads credential values for
any purpose other than redaction/leak detection.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Optional, Sequence, Union

# ---------------------------------------------------------------------------
# Schema / task identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "state-laws-publication-policy-v1"
AUTHORIZATION_SCHEMA: Final = (
    "ipfs_datasets_py/state-laws-publication-authorization@1"
)
TASK_ID: Final = "LCR-008"
GOAL_ID: Final = "LCR-G010"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "state_laws_publication_policy.py"

DEFAULT_DATASET_REPO_ID: Final = "justicedao/ipfs_state_laws"
PREVIOUS_PUBLIC_PIN: Final = "42f0546acc7c6cd55627eaf51fb820d5613b9021"
AUTHORIZED_ON: Final = "2026-08-10"
AUTHORIZATION_STATUS: Final = "recorded"
RELEASE_MODE: Final = "additive"

EXPECTED_JURISDICTION_COUNT: Final = 51

# Exact jurisdiction set: 50 postal state codes + DC (no extras, no omissions).
CANONICAL_JURISDICTIONS: Final = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "DC",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
    }
)

# Relative to repository root (parents[3] of this file).
DEFAULT_AUTHORIZATION_FIXTURE_RELATIVE_PATH: Final = Path(
    "tests/fixtures/legal_ir/state_laws_publication_authorization.json"
)

# Credential environment names (values never enter receipts/plans).
SECRET_ENV_NAMES: Final = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "STATE_LAWS_HF_TOKEN",
    "STATE_LAWS_PUBLICATION_AUTHORIZATION",
)

CREDENTIALS_SCOPE_PREFIX: Final = "dataset:write:"
DEFAULT_CREDENTIALS_SCOPE: Final = f"{CREDENTIALS_SCOPE_PREFIX}{DEFAULT_DATASET_REPO_ID}"
DEFAULT_STAGING_BRANCH: Final = "stage/state-laws-sparse-graphrag-v2"

AUTHORIZED_OPERATIONS: Final = frozenset(
    {
        "additive_staging_upload",
        "additive_main_upload",
    }
)

FORBIDDEN_OPERATIONS: Final = frozenset(
    {
        "delete",
        "delete_file",
        "delete_folder",
        "deletefile",
        "deletefolder",
        "force_push",
        "force-push",
        "history_rewrite",
        "history-rewrite",
        "super_squash_history",
        "visibility_change",
        "visibility-change",
        "overwrite_legacy",
        "overwrite-legacy",
        "move",
        "copy",
        "rewrite_main",
        "rewrite-main",
        "destructive_upload",
        "replace_all",
        "truncate",
    }
)

PROHIBITED_STAGING_BRANCHES: Final = frozenset(
    {
        "main",
        "master",
        "production",
        "prod",
        "public",
        "refs/heads/main",
        "refs/heads/master",
    }
)

REQUIRED_LIVE_MUTATION_GATES: Final = (
    "exact_51_coverage",
    "final_manifest_authorization",
    "staging_canary",
    "secret_redaction",
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DATASET_ID_RE = re.compile(r"^[A-Za-z0-9](?:[\w.-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9](?:[\w.-]{0,99}[A-Za-z0-9])?$")
_POSTAL_CODE_RE = re.compile(r"^[A-Z]{2}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")
_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key)s?$",
    re.IGNORECASE,
)
_MUTABLE_REVISION_RE = re.compile(
    r"^(?:latest|main|master|head|tip|trunk|default|current|live|prod|"
    r"production|staging|dev|develop|development|nightly|canary|"
    r"origin/.*|refs/.*)$",
    re.IGNORECASE,
)
_REDACTION_PLACEHOLDER: Final = "[REDACTED]"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StateLawsPublicationPolicyError(ValueError):
    """Base error for state-law publication policy failures."""

    code: str = "state_laws_publication_policy_error"


class AuthorizationRecordError(StateLawsPublicationPolicyError):
    """Raised when the sealed authorization record is missing or invalid."""

    code = "authorization_record_error"


class JurisdictionCoverageError(StateLawsPublicationPolicyError):
    """Raised when coverage is not exactly the sealed 51-jurisdiction set."""

    code = "jurisdiction_coverage_error"


class ManifestAuthorizationError(StateLawsPublicationPolicyError):
    """Raised when final-manifest authorization is missing or mismatched."""

    code = "manifest_authorization_error"


class StagingCanaryError(StateLawsPublicationPolicyError):
    """Raised when staging-canary evidence is incomplete or failed."""

    code = "staging_canary_error"


class SecretRedactionError(StateLawsPublicationPolicyError):
    """Raised when credentials/secrets appear in policy surfaces."""

    code = "secret_redaction_error"


class CredentialPolicyError(StateLawsPublicationPolicyError):
    """Raised when credentials are not environment-only."""

    code = "credential_policy_error"


class OperationForbiddenError(StateLawsPublicationPolicyError):
    """Raised when a mutation operation is not additive/authorized."""

    code = "operation_forbidden_error"


class TargetUnauthorizedError(StateLawsPublicationPolicyError):
    """Raised when the dataset target is outside the sealed authorization."""

    code = "target_unauthorized_error"


class StagingFirstError(StateLawsPublicationPolicyError):
    """Raised when a main mutation is attempted without staging-first order."""

    code = "staging_first_error"


class RollbackPinError(StateLawsPublicationPolicyError):
    """Raised when the previous public pin is not preserved."""

    code = "rollback_pin_error"


class LiveMutationDeniedError(StateLawsPublicationPolicyError):
    """Raised when :func:`require_live_mutation` fails closed."""

    code = "live_mutation_denied"

    def __init__(
        self,
        message: str,
        *,
        reason_codes: Sequence[str] = (),
        decision: Optional["PublicationDecision"] = None,
    ) -> None:
        super().__init__(message)
        self.reason_codes = tuple(reason_codes)
        self.decision = decision


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MutationPhase(str, Enum):
    """Publication phase for a live Hub mutation."""

    STAGING = "staging"
    MAIN = "main"

    @classmethod
    def coerce(cls, value: Any) -> "MutationPhase":
        if isinstance(value, MutationPhase):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "stage": cls.STAGING,
            "additive_staging_upload": cls.STAGING,
            "staging_upload": cls.STAGING,
            "public": cls.MAIN,
            "production": cls.MAIN,
            "additive_main_upload": cls.MAIN,
            "main_upload": cls.MAIN,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise StateLawsPublicationPolicyError(f"unknown mutation phase: {value!r}")


class PublicationOperation(str, Enum):
    """Authorized additive operations only."""

    ADDITIVE_STAGING_UPLOAD = "additive_staging_upload"
    ADDITIVE_MAIN_UPLOAD = "additive_main_upload"

    @classmethod
    def coerce(cls, value: Any) -> "PublicationOperation":
        if isinstance(value, PublicationOperation):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "staging": cls.ADDITIVE_STAGING_UPLOAD,
            "stage": cls.ADDITIVE_STAGING_UPLOAD,
            "staging_upload": cls.ADDITIVE_STAGING_UPLOAD,
            "main": cls.ADDITIVE_MAIN_UPLOAD,
            "public": cls.ADDITIVE_MAIN_UPLOAD,
            "main_upload": cls.ADDITIVE_MAIN_UPLOAD,
            "public_upload": cls.ADDITIVE_MAIN_UPLOAD,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise OperationForbiddenError(f"unknown publication operation: {value!r}")


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateLawsPublicationPolicyError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise StateLawsPublicationPolicyError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise StateLawsPublicationPolicyError(
            f"{name} exceeds maximum length {maximum}"
        )
    return text


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise StateLawsPublicationPolicyError(f"{name} must be a boolean")
    return value


def normalize_dataset_repo_id(value: Any, *, name: str = "dataset_repo_id") -> str:
    text = _require_non_empty_str(value, name, maximum=200)
    if not _DATASET_ID_RE.fullmatch(text):
        raise TargetUnauthorizedError(
            f"{name} must look like org/name, got {value!r}"
        )
    return text


def normalize_sha256(value: Any, *, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name, maximum=80).casefold()
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if not _SHA256_RE.fullmatch(text):
        raise ManifestAuthorizationError(
            f"{name} must be a 64-character lowercase hex digest"
        )
    return text


def require_immutable_revision(value: Any, *, name: str = "revision") -> str:
    text = _require_non_empty_str(value, name, maximum=128).casefold()
    if _MUTABLE_REVISION_RE.fullmatch(text):
        raise StagingCanaryError(
            f"{name} must be an immutable commit SHA, not a mutable pin "
            f"({value!r})"
        )
    if not _GIT_SHA_RE.fullmatch(text):
        raise StagingCanaryError(
            f"{name} must be a 40-character lowercase hex commit SHA, got {value!r}"
        )
    return text


def is_immutable_revision(value: Any) -> bool:
    try:
        require_immutable_revision(value)
        return True
    except StateLawsPublicationPolicyError:
        return False


def normalize_postal_code(value: Any, *, name: str = "postal_code") -> str:
    text = _require_non_empty_str(value, name, maximum=8).upper()
    if not _POSTAL_CODE_RE.fullmatch(text):
        raise JurisdictionCoverageError(
            f"{name}={text!r} is not a two-letter postal code"
        )
    if text not in CANONICAL_JURISDICTIONS:
        raise JurisdictionCoverageError(
            f"{name}={text!r} is not in the exact 51-jurisdiction set"
        )
    return text


def validate_exact_51_coverage(
    codes: Iterable[Any],
    *,
    name: str = "jurisdictions",
) -> tuple[str, ...]:
    """Require the exact 51-jurisdiction set (no missing, no extra, no dupes)."""

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in codes:
        code = normalize_postal_code(raw, name=name)
        if code in seen:
            raise JurisdictionCoverageError(
                f"{name} contains duplicate postal code {code!r}"
            )
        seen.add(code)
        normalized.append(code)
    actual = frozenset(normalized)
    if actual != CANONICAL_JURISDICTIONS:
        missing = sorted(CANONICAL_JURISDICTIONS - actual)
        extra = sorted(actual - CANONICAL_JURISDICTIONS)
        raise JurisdictionCoverageError(
            f"{name} must equal the exact 51-jurisdiction set; "
            f"missing={missing!r} extra={extra!r}"
        )
    if len(normalized) != EXPECTED_JURISDICTION_COUNT:
        raise JurisdictionCoverageError(
            f"{name} must contain exactly {EXPECTED_JURISDICTION_COUNT} unique "
            f"codes, got {len(normalized)}"
        )
    return tuple(sorted(normalized))


def normalize_operation(value: Any) -> str:
    op = PublicationOperation.coerce(value)
    return op.value


def normalize_operations(values: Iterable[Any]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in values:
        text = str(raw or "").strip().casefold().replace("-", "_")
        if not text:
            continue
        if text in FORBIDDEN_OPERATIONS or text.startswith("delete") or "force" in text:
            raise OperationForbiddenError(
                f"operation is forbidden for state-law publication: {raw!r}"
            )
        if "visibility" in text or "history" in text and "rewrite" in text:
            raise OperationForbiddenError(
                f"operation is forbidden for state-law publication: {raw!r}"
            )
        op = normalize_operation(text)
        if op not in AUTHORIZED_OPERATIONS:
            raise OperationForbiddenError(
                f"operation is not authorized: {raw!r}; allowed="
                f"{sorted(AUTHORIZED_OPERATIONS)!r}"
            )
        normalized.append(op)
    if not normalized:
        raise OperationForbiddenError(
            "at least one authorized additive operation is required"
        )
    return tuple(sorted(set(normalized)))


def normalize_staging_branch(value: Any, *, name: str = "staging_branch") -> str:
    text = _require_non_empty_str(value, name, maximum=220)
    if not _BRANCH_RE.fullmatch(text):
        raise StagingCanaryError(f"{name} is invalid: {value!r}")
    if ".." in text or text.startswith("/") or text.endswith("/"):
        raise StagingCanaryError(f"{name} is unsafe: {value!r}")
    lowered = text.casefold()
    if lowered in PROHIBITED_STAGING_BRANCHES or lowered.startswith("refs/heads/main"):
        raise StagingCanaryError(
            f"{name} must not target a production branch: {value!r}"
        )
    return text


def repository_root() -> Path:
    """Return the repository root that contains ``tests/fixtures``."""

    return Path(__file__).resolve().parents[3]


def default_authorization_fixture_path() -> Path:
    """Return the default path of the sealed publication-authorization fixture."""

    return repository_root() / DEFAULT_AUTHORIZATION_FIXTURE_RELATIVE_PATH


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------


def reject_credentials_in_payload(
    value: Any,
    *,
    label: str = "payload",
    environ: Optional[Mapping[str, str]] = None,
) -> None:
    """Fail closed when tokens, secrets, or credential-like values appear.

    Boolean policy flags (e.g. ``mutation_requires_authorization: true``) are
    allowed even when the key name matches a credential-like pattern; only
    non-boolean values under those keys are treated as secret material.
    """

    env = environ if environ is not None else os.environ
    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _TOKEN_KEY_RE.search(key_text) and not isinstance(child, bool):
                    # Explicit non-secret meta flags.
                    if key_text.casefold() in {
                        "credentials_scope",
                        "credentials_environment_only",
                        "secret_redaction_required",
                        "secret_redacted",
                        "authorization_status",
                        "authorization_receipt_id",
                        "authorization_recorded_on",
                        "mutation_requires_authorization",
                        "publication_authorization_required",
                    }:
                        visit(child, child_path)
                        continue
                    offenders.append(child_path)
                    continue
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            lowered = item.casefold()
            if lowered.startswith("hf_") and len(item) >= 20:
                offenders.append(path or label)
            if "bearer " in lowered:
                offenders.append(path or label)
            for env_name in SECRET_ENV_NAMES:
                env_val = env.get(env_name)
                if env_val and env_val in item:
                    offenders.append(path or label)

    visit(value, label)
    if offenders:
        raise SecretRedactionError(
            f"credential-like material in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_secrets_in_argv(
    argv: Sequence[str],
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> None:
    """Refuse secrets passed on the command line (credentials are env-only)."""

    env = environ if environ is not None else os.environ
    joined = " ".join(str(a) for a in argv)
    lowered = joined.casefold()
    needles = (
        "hf_token=",
        "authorization:",
        "bearer ",
        "access_token=",
        "api_token=",
        "hugging_face_hub_token=",
        "state_laws_hf_token=",
    )
    for needle in needles:
        if needle in lowered:
            raise CredentialPolicyError(
                "refusing to accept secrets on the command line; "
                "credentials remain environment-only"
            )
    for env_name in SECRET_ENV_NAMES:
        env_val = env.get(env_name)
        if env_val and env_val in joined:
            raise CredentialPolicyError(
                f"refusing to accept ${env_name} value on the command line"
            )


def redact_secrets(
    value: Any,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> Any:
    """Return a deep-copied structure with credential-like values redacted."""

    env = environ if environ is not None else os.environ
    secret_values = {
        str(env[name])
        for name in SECRET_ENV_NAMES
        if env.get(name)
    }

    def visit(item: Any) -> Any:
        if isinstance(item, Mapping):
            out: dict[str, Any] = {}
            for key, child in item.items():
                key_text = str(key)
                if (
                    _TOKEN_KEY_RE.search(key_text)
                    and not isinstance(child, bool)
                    and key_text.casefold()
                    not in {
                        "credentials_scope",
                        "credentials_environment_only",
                        "secret_redaction_required",
                        "secret_redacted",
                        "authorization_status",
                        "authorization_receipt_id",
                        "authorization_recorded_on",
                        "mutation_requires_authorization",
                        "publication_authorization_required",
                    }
                ):
                    out[key_text] = _REDACTION_PLACEHOLDER
                else:
                    out[key_text] = visit(child)
            return out
        if isinstance(item, list):
            return [visit(child) for child in item]
        if isinstance(item, tuple):
            return tuple(visit(child) for child in item)
        if isinstance(item, str):
            text = item
            for secret in secret_values:
                if secret and secret in text:
                    text = text.replace(secret, _REDACTION_PLACEHOLDER)
            lowered = text.casefold()
            if lowered.startswith("hf_") and len(text) >= 20:
                return _REDACTION_PLACEHOLDER
            if "bearer " in lowered:
                return _REDACTION_PLACEHOLDER
            return text
        return item

    return visit(value)


def assert_environment_only_credentials(
    *,
    credentials_present_in_payload: bool = False,
    credentials_present_in_argv: bool = False,
    credentials_scope: Any = DEFAULT_CREDENTIALS_SCOPE,
    environ: Optional[Mapping[str, str]] = None,
    require_token_present: bool = False,
) -> str:
    """Validate credential policy; never returns token values."""

    if credentials_present_in_payload:
        raise CredentialPolicyError(
            "credentials must never appear in plans, receipts, or payloads"
        )
    if credentials_present_in_argv:
        raise CredentialPolicyError(
            "credentials must never appear on the command line; "
            "use environment variables only"
        )
    scope = _require_non_empty_str(credentials_scope, "credentials_scope", maximum=300)
    expected = DEFAULT_CREDENTIALS_SCOPE
    if scope != expected:
        raise CredentialPolicyError(
            f"credentials_scope must be {expected!r}, got {scope!r}"
        )
    env = environ if environ is not None else os.environ
    if require_token_present:
        token_found = any(bool(str(env.get(name) or "").strip()) for name in SECRET_ENV_NAMES)
        if not token_found:
            raise CredentialPolicyError(
                "mutation refused: no environment credential is set "
                f"(expected one of {list(SECRET_ENV_NAMES)!r}); "
                "missing credentials park publication without false completion"
            )
    return scope


# ---------------------------------------------------------------------------
# Authorization record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PublicationAuthorization:
    """Sealed operator authorization for additive state-law Hub publication."""

    schema: str
    schema_version: str
    task_id: str
    goal_id: str
    program_id: str
    status: str
    recorded_on: str
    dataset_repo_id: str
    authorized_operations: tuple[str, ...]
    previous_public_pin: str
    release_mode: str
    credentials_environment_only: bool
    secret_redaction_required: bool
    staging_first_required: bool
    exact_51_coverage_required: bool
    final_manifest_authorization_required: bool
    staging_canary_required: bool
    immutable_redownload_required: bool
    rollback_pin_must_be_preserved: bool
    deletion_allowed: bool
    force_push_allowed: bool
    history_rewrite_allowed: bool
    visibility_change_allowed: bool
    alternate_dataset_targets_allowed: bool
    required_gates: tuple[str, ...]
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema", _require_non_empty_str(self.schema, "schema")
        )
        if self.schema != AUTHORIZATION_SCHEMA:
            raise AuthorizationRecordError(
                f"authorization schema must be {AUTHORIZATION_SCHEMA!r}, "
                f"got {self.schema!r}"
            )
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )
        if self.schema_version != SCHEMA_VERSION:
            raise AuthorizationRecordError(
                f"authorization schema_version must be {SCHEMA_VERSION!r}, "
                f"got {self.schema_version!r}"
            )
        object.__setattr__(
            self, "task_id", _require_non_empty_str(self.task_id, "task_id")
        )
        if self.task_id != TASK_ID:
            raise AuthorizationRecordError(
                f"authorization task_id must be {TASK_ID!r}, got {self.task_id!r}"
            )
        object.__setattr__(
            self, "goal_id", _require_non_empty_str(self.goal_id, "goal_id")
        )
        object.__setattr__(
            self,
            "program_id",
            _require_non_empty_str(self.program_id, "program_id"),
        )
        object.__setattr__(
            self, "status", _require_non_empty_str(self.status, "status").lower()
        )
        if self.status != AUTHORIZATION_STATUS:
            raise AuthorizationRecordError(
                f"authorization status must be {AUTHORIZATION_STATUS!r}, "
                f"got {self.status!r}"
            )
        object.__setattr__(
            self,
            "recorded_on",
            _require_non_empty_str(self.recorded_on, "recorded_on"),
        )
        if self.recorded_on != AUTHORIZED_ON:
            raise AuthorizationRecordError(
                f"authorization recorded_on must be {AUTHORIZED_ON!r}, "
                f"got {self.recorded_on!r}"
            )
        repo = normalize_dataset_repo_id(self.dataset_repo_id)
        if repo != DEFAULT_DATASET_REPO_ID:
            raise AuthorizationRecordError(
                f"authorization dataset_repo_id must be "
                f"{DEFAULT_DATASET_REPO_ID!r}, got {repo!r}"
            )
        object.__setattr__(self, "dataset_repo_id", repo)
        ops = normalize_operations(self.authorized_operations)
        if frozenset(ops) != AUTHORIZED_OPERATIONS:
            raise AuthorizationRecordError(
                "authorization authorized_operations must equal "
                f"{sorted(AUTHORIZED_OPERATIONS)!r}, got {list(ops)!r}"
            )
        object.__setattr__(self, "authorized_operations", ops)
        pin = require_immutable_revision(
            self.previous_public_pin, name="previous_public_pin"
        )
        if pin != PREVIOUS_PUBLIC_PIN:
            raise AuthorizationRecordError(
                f"previous_public_pin must be {PREVIOUS_PUBLIC_PIN!r}, got {pin!r}"
            )
        object.__setattr__(self, "previous_public_pin", pin)
        mode = _require_non_empty_str(self.release_mode, "release_mode").lower()
        if mode != RELEASE_MODE:
            raise AuthorizationRecordError(
                f"release_mode must be {RELEASE_MODE!r}, got {mode!r}"
            )
        object.__setattr__(self, "release_mode", mode)

        for flag_name, expected in (
            ("credentials_environment_only", True),
            ("secret_redaction_required", True),
            ("staging_first_required", True),
            ("exact_51_coverage_required", True),
            ("final_manifest_authorization_required", True),
            ("staging_canary_required", True),
            ("immutable_redownload_required", True),
            ("rollback_pin_must_be_preserved", True),
            ("deletion_allowed", False),
            ("force_push_allowed", False),
            ("history_rewrite_allowed", False),
            ("visibility_change_allowed", False),
            ("alternate_dataset_targets_allowed", False),
        ):
            actual = _require_bool(getattr(self, flag_name), flag_name)
            if actual is not expected:
                raise AuthorizationRecordError(
                    f"authorization {flag_name} must be {expected!r}, got {actual!r}"
                )

        gates = tuple(
            _require_non_empty_str(g, "required_gates[]") for g in self.required_gates
        )
        if tuple(gates) != REQUIRED_LIVE_MUTATION_GATES:
            raise AuthorizationRecordError(
                "authorization required_gates must equal "
                f"{list(REQUIRED_LIVE_MUTATION_GATES)!r}, got {list(gates)!r}"
            )
        object.__setattr__(self, "required_gates", gates)
        if not isinstance(self.payload, Mapping):
            raise AuthorizationRecordError("payload must be a mapping")
        reject_credentials_in_payload(self.payload, label="authorization.payload")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "alternate_dataset_targets_allowed": self.alternate_dataset_targets_allowed,
            "authorized_operations": list(self.authorized_operations),
            "credentials_environment_only": self.credentials_environment_only,
            "dataset_repo_id": self.dataset_repo_id,
            "deletion_allowed": self.deletion_allowed,
            "exact_51_coverage_required": self.exact_51_coverage_required,
            "final_manifest_authorization_required": (
                self.final_manifest_authorization_required
            ),
            "force_push_allowed": self.force_push_allowed,
            "goal_id": self.goal_id,
            "history_rewrite_allowed": self.history_rewrite_allowed,
            "immutable_redownload_required": self.immutable_redownload_required,
            "payload": dict(self.payload),
            "previous_public_pin": self.previous_public_pin,
            "program_id": self.program_id,
            "recorded_on": self.recorded_on,
            "release_mode": self.release_mode,
            "required_gates": list(self.required_gates),
            "rollback_pin_must_be_preserved": self.rollback_pin_must_be_preserved,
            "schema": self.schema,
            "schema_version": self.schema_version,
            "secret_redaction_required": self.secret_redaction_required,
            "staging_canary_required": self.staging_canary_required,
            "staging_first_required": self.staging_first_required,
            "status": self.status,
            "task_id": self.task_id,
            "visibility_change_allowed": self.visibility_change_allowed,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PublicationAuthorization":
        if not isinstance(value, Mapping):
            raise AuthorizationRecordError("authorization record must be a mapping")
        reject_credentials_in_payload(value, label="authorization_record")
        auth = value.get("publication_authorization")
        body: Mapping[str, Any]
        if isinstance(auth, Mapping):
            body = {**value, **auth}
        else:
            body = value
        ops = body.get("authorized_operations") or body.get("authorized_operations", ())
        if "authorized_dataset_repo_ids" in body and "dataset_repo_id" not in body:
            repos = body.get("authorized_dataset_repo_ids") or []
            if not isinstance(repos, Sequence) or not repos:
                raise AuthorizationRecordError(
                    "authorized_dataset_repo_ids must be a non-empty sequence"
                )
            dataset_repo_id = repos[0]
        else:
            dataset_repo_id = body.get("dataset_repo_id", DEFAULT_DATASET_REPO_ID)
        gates = body.get("required_gates") or list(REQUIRED_LIVE_MUTATION_GATES)
        return cls(
            schema=body.get("schema", AUTHORIZATION_SCHEMA),
            schema_version=body.get("schema_version", SCHEMA_VERSION),
            task_id=body.get("task_id", TASK_ID),
            goal_id=body.get("goal_id", GOAL_ID),
            program_id=body.get("program_id", PROGRAM_ID),
            status=body.get("status", AUTHORIZATION_STATUS),
            recorded_on=body.get("recorded_on", AUTHORIZED_ON),
            dataset_repo_id=dataset_repo_id,
            authorized_operations=tuple(ops),
            previous_public_pin=body.get(
                "previous_public_pin", PREVIOUS_PUBLIC_PIN
            ),
            release_mode=body.get("release_mode", RELEASE_MODE),
            credentials_environment_only=body.get(
                "credentials_environment_only", True
            ),
            secret_redaction_required=body.get("secret_redaction_required", True),
            staging_first_required=body.get("staging_first_required", True),
            exact_51_coverage_required=body.get("exact_51_coverage_required", True),
            final_manifest_authorization_required=body.get(
                "final_manifest_authorization_required", True
            ),
            staging_canary_required=body.get("staging_canary_required", True),
            immutable_redownload_required=body.get(
                "immutable_redownload_required", True
            ),
            rollback_pin_must_be_preserved=body.get(
                "rollback_pin_must_be_preserved", True
            ),
            deletion_allowed=body.get("deletion_allowed", False),
            force_push_allowed=body.get("force_push_allowed", False),
            history_rewrite_allowed=body.get("history_rewrite_allowed", False),
            visibility_change_allowed=body.get("visibility_change_allowed", False),
            alternate_dataset_targets_allowed=body.get(
                "alternate_dataset_targets_allowed", False
            ),
            required_gates=tuple(gates),
            payload=body.get("payload") or {},
        )


def load_publication_authorization(
    path: Optional[PathLike] = None,
) -> PublicationAuthorization:
    """Load and validate the sealed publication-authorization fixture."""

    target = Path(path) if path is not None else default_authorization_fixture_path()
    if not target.is_file():
        raise AuthorizationRecordError(
            f"publication authorization fixture not found: {target}"
        )
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuthorizationRecordError(
            f"publication authorization fixture is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise AuthorizationRecordError(
            "publication authorization fixture root must be a mapping"
        )
    return PublicationAuthorization.from_mapping(payload)


@lru_cache(maxsize=1)
def get_publication_authorization() -> PublicationAuthorization:
    """Return the cached sealed authorization record."""

    return load_publication_authorization()


def clear_authorization_cache() -> None:
    """Clear the cached authorization record (for tests)."""

    get_publication_authorization.cache_clear()


# ---------------------------------------------------------------------------
# Mutation request / decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiveMutationRequest:
    """Inputs evaluated before any live Hub mutation.

    Callers must supply coverage, final-manifest identity, staging-canary
    evidence (phase-appropriate), and secret-redaction proof. Credentials
    themselves never appear on this object.
    """

    operation: str
    dataset_repo_id: str
    jurisdictions: tuple[str, ...]
    final_manifest_digest: str
    previous_public_pin: str
    secret_redacted: bool
    credentials_environment_only: bool
    credentials_scope: str = DEFAULT_CREDENTIALS_SCOPE
    phase: Optional[str] = None
    staging_branch: Optional[str] = None
    staging_revision: Optional[str] = None
    staging_canary_passed: bool = False
    staging_redownload_verified: bool = False
    staging_canary_manifest_digest: Optional[str] = None
    immutable_redownload_required: bool = True
    authorization_receipt_id: Optional[str] = None
    authorize_mutation: bool = False
    payload: Mapping[str, Any] = field(default_factory=dict)
    argv: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        op = normalize_operation(self.operation)
        object.__setattr__(self, "operation", op)
        if self.phase is None:
            phase = (
                MutationPhase.STAGING
                if op == PublicationOperation.ADDITIVE_STAGING_UPLOAD.value
                else MutationPhase.MAIN
            )
        else:
            phase = MutationPhase.coerce(self.phase)
        # Operation/phase coherence.
        if (
            op == PublicationOperation.ADDITIVE_STAGING_UPLOAD.value
            and phase is not MutationPhase.STAGING
        ):
            raise StagingFirstError(
                "additive_staging_upload requires phase=staging"
            )
        if (
            op == PublicationOperation.ADDITIVE_MAIN_UPLOAD.value
            and phase is not MutationPhase.MAIN
        ):
            raise StagingFirstError(
                "additive_main_upload requires phase=main"
            )
        object.__setattr__(self, "phase", phase.value)
        object.__setattr__(
            self,
            "dataset_repo_id",
            normalize_dataset_repo_id(self.dataset_repo_id),
        )
        object.__setattr__(
            self,
            "jurisdictions",
            validate_exact_51_coverage(self.jurisdictions),
        )
        object.__setattr__(
            self,
            "final_manifest_digest",
            normalize_sha256(self.final_manifest_digest, name="final_manifest_digest"),
        )
        object.__setattr__(
            self,
            "previous_public_pin",
            require_immutable_revision(
                self.previous_public_pin, name="previous_public_pin"
            ),
        )
        object.__setattr__(
            self, "secret_redacted", _require_bool(self.secret_redacted, "secret_redacted")
        )
        object.__setattr__(
            self,
            "credentials_environment_only",
            _require_bool(
                self.credentials_environment_only, "credentials_environment_only"
            ),
        )
        object.__setattr__(
            self,
            "credentials_scope",
            _require_non_empty_str(self.credentials_scope, "credentials_scope"),
        )
        object.__setattr__(
            self,
            "staging_canary_passed",
            _require_bool(self.staging_canary_passed, "staging_canary_passed"),
        )
        object.__setattr__(
            self,
            "staging_redownload_verified",
            _require_bool(
                self.staging_redownload_verified, "staging_redownload_verified"
            ),
        )
        object.__setattr__(
            self,
            "immutable_redownload_required",
            _require_bool(
                self.immutable_redownload_required, "immutable_redownload_required"
            ),
        )
        object.__setattr__(
            self,
            "authorize_mutation",
            _require_bool(self.authorize_mutation, "authorize_mutation"),
        )
        if self.staging_branch is not None:
            object.__setattr__(
                self,
                "staging_branch",
                normalize_staging_branch(self.staging_branch),
            )
        if self.staging_revision is not None:
            object.__setattr__(
                self,
                "staging_revision",
                require_immutable_revision(
                    self.staging_revision, name="staging_revision"
                ),
            )
        if self.staging_canary_manifest_digest is not None:
            object.__setattr__(
                self,
                "staging_canary_manifest_digest",
                normalize_sha256(
                    self.staging_canary_manifest_digest,
                    name="staging_canary_manifest_digest",
                ),
            )
        if self.authorization_receipt_id is not None:
            object.__setattr__(
                self,
                "authorization_receipt_id",
                _require_non_empty_str(
                    self.authorization_receipt_id, "authorization_receipt_id"
                ),
            )
        if not isinstance(self.payload, Mapping):
            raise StateLawsPublicationPolicyError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "argv", tuple(str(a) for a in self.argv))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LiveMutationRequest":
        if not isinstance(value, Mapping):
            raise StateLawsPublicationPolicyError(
                "live mutation request must be a mapping"
            )
        jurisdictions = value.get("jurisdictions") or value.get("jurisdiction_codes")
        if jurisdictions is None:
            jurisdictions = ()
        return cls(
            operation=value.get("operation", ""),
            dataset_repo_id=value.get(
                "dataset_repo_id", DEFAULT_DATASET_REPO_ID
            ),
            jurisdictions=tuple(jurisdictions),
            final_manifest_digest=value.get("final_manifest_digest", ""),
            previous_public_pin=value.get(
                "previous_public_pin", PREVIOUS_PUBLIC_PIN
            ),
            secret_redacted=value.get("secret_redacted", False),
            credentials_environment_only=value.get(
                "credentials_environment_only", False
            ),
            credentials_scope=value.get(
                "credentials_scope", DEFAULT_CREDENTIALS_SCOPE
            ),
            phase=value.get("phase"),
            staging_branch=value.get("staging_branch"),
            staging_revision=value.get("staging_revision"),
            staging_canary_passed=value.get("staging_canary_passed", False),
            staging_redownload_verified=value.get(
                "staging_redownload_verified", False
            ),
            staging_canary_manifest_digest=value.get(
                "staging_canary_manifest_digest"
            ),
            immutable_redownload_required=value.get(
                "immutable_redownload_required", True
            ),
            authorization_receipt_id=value.get("authorization_receipt_id"),
            authorize_mutation=value.get("authorize_mutation", False),
            payload=value.get("payload") or {},
            argv=tuple(value.get("argv") or ()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_receipt_id": self.authorization_receipt_id,
            "authorize_mutation": self.authorize_mutation,
            "argv": list(self.argv),
            "credentials_environment_only": self.credentials_environment_only,
            "credentials_scope": self.credentials_scope,
            "dataset_repo_id": self.dataset_repo_id,
            "final_manifest_digest": self.final_manifest_digest,
            "immutable_redownload_required": self.immutable_redownload_required,
            "jurisdictions": list(self.jurisdictions),
            "operation": self.operation,
            "payload": dict(self.payload),
            "phase": self.phase,
            "previous_public_pin": self.previous_public_pin,
            "secret_redacted": self.secret_redacted,
            "staging_branch": self.staging_branch,
            "staging_canary_manifest_digest": self.staging_canary_manifest_digest,
            "staging_canary_passed": self.staging_canary_passed,
            "staging_redownload_verified": self.staging_redownload_verified,
            "staging_revision": self.staging_revision,
        }


@dataclass(frozen=True, slots=True)
class PublicationDecision:
    """Fail-closed decision for a live mutation request."""

    authorized: bool
    operation: str
    phase: str
    dataset_repo_id: str
    final_manifest_digest: str
    reason_codes: tuple[str, ...]
    passed_gates: tuple[str, ...]
    required_gates: tuple[str, ...] = REQUIRED_LIVE_MUTATION_GATES
    previous_public_pin: str = PREVIOUS_PUBLIC_PIN
    message: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "authorized", _require_bool(self.authorized, "authorized")
        )
        object.__setattr__(
            self, "operation", _require_non_empty_str(self.operation, "operation")
        )
        object.__setattr__(
            self, "phase", _require_non_empty_str(self.phase, "phase")
        )
        object.__setattr__(
            self,
            "dataset_repo_id",
            normalize_dataset_repo_id(self.dataset_repo_id),
        )
        object.__setattr__(
            self,
            "final_manifest_digest",
            normalize_sha256(self.final_manifest_digest, name="final_manifest_digest")
            if self.final_manifest_digest
            else "",
        )
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "passed_gates", tuple(self.passed_gates))
        object.__setattr__(self, "required_gates", tuple(self.required_gates))
        if not isinstance(self.details, Mapping):
            raise StateLawsPublicationPolicyError("details must be a mapping")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorized": self.authorized,
            "dataset_repo_id": self.dataset_repo_id,
            "details": dict(self.details),
            "final_manifest_digest": self.final_manifest_digest,
            "message": self.message,
            "operation": self.operation,
            "passed_gates": list(self.passed_gates),
            "phase": self.phase,
            "previous_public_pin": self.previous_public_pin,
            "reason_codes": list(self.reason_codes),
            "required_gates": list(self.required_gates),
        }

    def require_authorized(self) -> "PublicationDecision":
        if not self.authorized:
            raise LiveMutationDeniedError(
                self.message
                or (
                    "live mutation denied: "
                    + ", ".join(self.reason_codes or ("policy.denied",))
                ),
                reason_codes=self.reason_codes,
                decision=self,
            )
        return self


# ---------------------------------------------------------------------------
# Gate evaluators
# ---------------------------------------------------------------------------


def assert_target_authorized(
    dataset_repo_id: Any,
    *,
    authorization: Optional[PublicationAuthorization] = None,
) -> str:
    repo = normalize_dataset_repo_id(dataset_repo_id)
    auth = authorization or get_publication_authorization()
    if repo != auth.dataset_repo_id or repo != DEFAULT_DATASET_REPO_ID:
        raise TargetUnauthorizedError(
            f"dataset target {repo!r} is not authorized; only "
            f"{DEFAULT_DATASET_REPO_ID!r} is permitted"
        )
    if auth.alternate_dataset_targets_allowed:
        raise AuthorizationRecordError(
            "authorization must not allow alternate dataset targets"
        )
    return repo


def assert_operation_authorized(
    operation: Any,
    *,
    authorization: Optional[PublicationAuthorization] = None,
) -> str:
    op = normalize_operation(operation)
    auth = authorization or get_publication_authorization()
    if op not in auth.authorized_operations:
        raise OperationForbiddenError(
            f"operation {op!r} is not in authorized_operations "
            f"{list(auth.authorized_operations)!r}"
        )
    if auth.deletion_allowed or auth.force_push_allowed:
        raise AuthorizationRecordError(
            "authorization must not allow deletion or force-push"
        )
    if auth.history_rewrite_allowed or auth.visibility_change_allowed:
        raise AuthorizationRecordError(
            "authorization must not allow history rewrite or visibility change"
        )
    return op


def assert_rollback_pin_preserved(
    previous_public_pin: Any,
    *,
    authorization: Optional[PublicationAuthorization] = None,
) -> str:
    pin = require_immutable_revision(
        previous_public_pin, name="previous_public_pin"
    )
    auth = authorization or get_publication_authorization()
    if pin != auth.previous_public_pin or pin != PREVIOUS_PUBLIC_PIN:
        raise RollbackPinError(
            f"previous_public_pin must remain {PREVIOUS_PUBLIC_PIN!r}, got {pin!r}"
        )
    if not auth.rollback_pin_must_be_preserved:
        raise AuthorizationRecordError(
            "authorization must require rollback pin preservation"
        )
    return pin


def check_exact_51_coverage(request: LiveMutationRequest) -> None:
    validate_exact_51_coverage(request.jurisdictions)


def check_final_manifest_authorization(request: LiveMutationRequest) -> None:
    digest = normalize_sha256(
        request.final_manifest_digest, name="final_manifest_digest"
    )
    if not digest:
        raise ManifestAuthorizationError("final_manifest_digest is required")
    if not request.authorize_mutation:
        raise ManifestAuthorizationError(
            "final manifest authorization refused: authorize_mutation must be true"
        )
    if not request.authorization_receipt_id:
        raise ManifestAuthorizationError(
            "final manifest authorization requires authorization_receipt_id "
            "bound to the exact final manifest"
        )


def check_staging_canary(
    request: LiveMutationRequest,
    *,
    authorization: Optional[PublicationAuthorization] = None,
) -> None:
    auth = authorization or get_publication_authorization()
    if not auth.staging_canary_required:
        raise AuthorizationRecordError(
            "authorization must require staging canary for live mutation"
        )
    if not request.immutable_redownload_required:
        raise StagingCanaryError(
            "staging canary requires immutable_redownload_required=true"
        )
    phase = MutationPhase.coerce(request.phase)

    if phase is MutationPhase.STAGING:
        if not request.staging_branch:
            raise StagingCanaryError(
                "staging upload requires an explicit non-production staging_branch"
            )
        normalize_staging_branch(request.staging_branch)
        # Staging phase binds the post-upload canary contract without requiring
        # a prior canary pass (that would make the first upload impossible).
        return

    # MAIN phase: staging-first + completed canary on the same manifest.
    if not auth.staging_first_required:
        raise AuthorizationRecordError(
            "authorization must require staging-first mutation"
        )
    if not request.staging_canary_passed:
        raise StagingFirstError(
            "main upload refused: staging canary has not passed"
        )
    if not request.staging_revision:
        raise StagingCanaryError(
            "main upload requires immutable staging_revision from the canary"
        )
    require_immutable_revision(request.staging_revision, name="staging_revision")
    if not request.staging_redownload_verified:
        raise StagingCanaryError(
            "main upload requires staging_redownload_verified=true "
            "(immutable redownload canary)"
        )
    if not request.staging_canary_manifest_digest:
        raise StagingCanaryError(
            "main upload requires staging_canary_manifest_digest bound to the "
            "final manifest"
        )
    if request.staging_canary_manifest_digest != request.final_manifest_digest:
        raise StagingCanaryError(
            "staging canary manifest digest must equal final_manifest_digest; "
            f"canary={request.staging_canary_manifest_digest!r} "
            f"final={request.final_manifest_digest!r}"
        )
    if not request.staging_branch:
        raise StagingCanaryError(
            "main upload must record the explicit staging_branch used for canary"
        )


def check_secret_redaction(
    request: LiveMutationRequest,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> None:
    if not request.secret_redacted:
        raise SecretRedactionError(
            "secret-redaction check failed: secret_redacted must be true"
        )
    if not request.credentials_environment_only:
        raise CredentialPolicyError(
            "credentials must be environment-only"
        )
    reject_credentials_in_payload(
        request.payload, label="mutation_request.payload", environ=environ
    )
    reject_credentials_in_payload(
        request.to_dict(), label="mutation_request", environ=environ
    )
    if request.argv:
        reject_secrets_in_argv(request.argv, environ=environ)
    assert_environment_only_credentials(
        credentials_present_in_payload=False,
        credentials_present_in_argv=False,
        credentials_scope=request.credentials_scope,
        environ=environ,
        require_token_present=False,
    )


# ---------------------------------------------------------------------------
# Public evaluation API
# ---------------------------------------------------------------------------


def evaluate_live_mutation(
    request: LiveMutationRequest | Mapping[str, Any],
    *,
    authorization: Optional[PublicationAuthorization] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> PublicationDecision:
    """Evaluate whether a live Hub mutation is authorized.

    Fail-closed: any missing gate produces ``authorized=False`` with explicit
    reason codes. Does not perform network I/O and never returns secrets.
    """

    auth = authorization or get_publication_authorization()
    reasons: list[str] = []
    passed: list[str] = []
    details: dict[str, Any] = {
        "task_id": TASK_ID,
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
    }

    try:
        req = (
            request
            if isinstance(request, LiveMutationRequest)
            else LiveMutationRequest.from_mapping(request)
        )
    except StateLawsPublicationPolicyError as exc:
        raw_op = "unknown"
        raw_phase = "unknown"
        raw_repo = DEFAULT_DATASET_REPO_ID
        raw_digest = "0" * 64
        if isinstance(request, Mapping):
            raw_op = str(request.get("operation") or "unknown")
            raw_phase = str(request.get("phase") or "unknown")
            raw_repo = str(request.get("dataset_repo_id") or DEFAULT_DATASET_REPO_ID)
            candidate = str(request.get("final_manifest_digest") or "")
            try:
                raw_digest = normalize_sha256(candidate, name="final_manifest_digest")
            except StateLawsPublicationPolicyError:
                raw_digest = "0" * 64
        try:
            safe_repo = normalize_dataset_repo_id(raw_repo)
        except StateLawsPublicationPolicyError:
            safe_repo = DEFAULT_DATASET_REPO_ID
        # Map construction-time failures onto the four mandatory gate labels so
        # callers can always attribute a refusal to the acceptance criteria.
        gate_hints: list[str] = [f"request.invalid:{exc.code}"]
        if isinstance(exc, JurisdictionCoverageError):
            gate_hints.append("gate.exact_51_coverage:jurisdiction_coverage_error")
        elif isinstance(exc, ManifestAuthorizationError):
            gate_hints.append(
                "gate.final_manifest_authorization:manifest_authorization_error"
            )
        elif isinstance(exc, (StagingCanaryError, StagingFirstError)):
            gate_hints.append(f"gate.staging_canary:{exc.code}")
        elif isinstance(exc, (SecretRedactionError, CredentialPolicyError)):
            gate_hints.append(f"gate.secret_redaction:{exc.code}")
        elif isinstance(exc, OperationForbiddenError):
            gate_hints.append(f"operation.{exc.code}")
        elif isinstance(exc, TargetUnauthorizedError):
            gate_hints.append(f"target.{exc.code}")
        elif isinstance(exc, RollbackPinError):
            gate_hints.append(f"rollback.{exc.code}")
        return PublicationDecision(
            authorized=False,
            operation=raw_op or "unknown",
            phase=raw_phase or "unknown",
            dataset_repo_id=safe_repo,
            final_manifest_digest=raw_digest,
            reason_codes=tuple(gate_hints),
            passed_gates=(),
            message=str(exc),
            details={"error": str(exc)},
        )

    operation = req.operation
    phase = req.phase or "unknown"
    dataset_repo_id = req.dataset_repo_id
    final_manifest_digest = req.final_manifest_digest

    # Target + operation + rollback pin (structural).
    try:
        assert_target_authorized(dataset_repo_id, authorization=auth)
    except StateLawsPublicationPolicyError as exc:
        reasons.append(f"target.{exc.code}")
        details["target_error"] = str(exc)

    try:
        assert_operation_authorized(operation, authorization=auth)
    except StateLawsPublicationPolicyError as exc:
        reasons.append(f"operation.{exc.code}")
        details["operation_error"] = str(exc)

    try:
        assert_rollback_pin_preserved(
            req.previous_public_pin, authorization=auth
        )
    except StateLawsPublicationPolicyError as exc:
        reasons.append(f"rollback.{exc.code}")
        details["rollback_error"] = str(exc)

    # Gate 1: exact-51 coverage
    try:
        check_exact_51_coverage(req)
        passed.append("exact_51_coverage")
    except StateLawsPublicationPolicyError as exc:
        reasons.append(f"gate.exact_51_coverage:{exc.code}")
        details["exact_51_coverage_error"] = str(exc)

    # Gate 2: final manifest authorization
    try:
        check_final_manifest_authorization(req)
        passed.append("final_manifest_authorization")
    except StateLawsPublicationPolicyError as exc:
        reasons.append(f"gate.final_manifest_authorization:{exc.code}")
        details["final_manifest_authorization_error"] = str(exc)

    # Gate 3: staging canary (phase-aware; always required in the policy set)
    try:
        check_staging_canary(req, authorization=auth)
        passed.append("staging_canary")
    except StateLawsPublicationPolicyError as exc:
        reasons.append(f"gate.staging_canary:{exc.code}")
        details["staging_canary_error"] = str(exc)

    # Gate 4: secret redaction
    try:
        check_secret_redaction(req, environ=environ)
        passed.append("secret_redaction")
    except StateLawsPublicationPolicyError as exc:
        reasons.append(f"gate.secret_redaction:{exc.code}")
        details["secret_redaction_error"] = str(exc)

    authorized = not reasons and set(passed) >= set(REQUIRED_LIVE_MUTATION_GATES)
    if authorized:
        message = (
            f"live mutation authorized for {operation} on {dataset_repo_id} "
            f"(phase={phase}, manifest={final_manifest_digest[:12]}…)"
        )
    else:
        message = (
            "live mutation refused before Hub write: "
            + "; ".join(reasons[:8])
        )

    details["passed_gate_count"] = len(passed)
    details["required_gate_count"] = len(REQUIRED_LIVE_MUTATION_GATES)
    details["staging_branch"] = req.staging_branch
    details["staging_revision"] = req.staging_revision
    details["authorization_receipt_id"] = req.authorization_receipt_id

    # Decision payload must itself be secret-clean.
    decision = PublicationDecision(
        authorized=authorized,
        operation=operation,
        phase=phase,
        dataset_repo_id=dataset_repo_id,
        final_manifest_digest=final_manifest_digest,
        reason_codes=tuple(reasons),
        passed_gates=tuple(passed),
        required_gates=REQUIRED_LIVE_MUTATION_GATES,
        previous_public_pin=req.previous_public_pin,
        message=message,
        details=details,
    )
    reject_credentials_in_payload(decision.to_dict(), label="publication_decision")
    return decision


def require_live_mutation(
    request: LiveMutationRequest | Mapping[str, Any],
    *,
    authorization: Optional[PublicationAuthorization] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> PublicationDecision:
    """Evaluate and raise :class:`LiveMutationDeniedError` when denied."""

    decision = evaluate_live_mutation(
        request, authorization=authorization, environ=environ
    )
    return decision.require_authorized()


def example_authorized_staging_request(
    *,
    manifest_digest: Optional[str] = None,
) -> dict[str, Any]:
    """Return a minimal mapping that passes staging live-mutation gates."""

    digest = manifest_digest or ("a" * 64)
    return {
        "operation": PublicationOperation.ADDITIVE_STAGING_UPLOAD.value,
        "phase": MutationPhase.STAGING.value,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "jurisdictions": sorted(CANONICAL_JURISDICTIONS),
        "final_manifest_digest": digest,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "secret_redacted": True,
        "credentials_environment_only": True,
        "credentials_scope": DEFAULT_CREDENTIALS_SCOPE,
        "staging_branch": DEFAULT_STAGING_BRANCH,
        "immutable_redownload_required": True,
        "authorization_receipt_id": "auth-state-laws-staging-001",
        "authorize_mutation": True,
        "payload": {
            "release_mode": RELEASE_MODE,
            "credentials_environment_only": True,
            "secret_redacted": True,
        },
        "argv": ["publish-state-laws", "--phase", "staging", "--dry-run"],
    }


def example_authorized_main_request(
    *,
    manifest_digest: Optional[str] = None,
    staging_revision: Optional[str] = None,
) -> dict[str, Any]:
    """Return a minimal mapping that passes main live-mutation gates."""

    digest = manifest_digest or ("b" * 64)
    staging_sha = staging_revision or ("c" * 40)
    return {
        "operation": PublicationOperation.ADDITIVE_MAIN_UPLOAD.value,
        "phase": MutationPhase.MAIN.value,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "jurisdictions": sorted(CANONICAL_JURISDICTIONS),
        "final_manifest_digest": digest,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "secret_redacted": True,
        "credentials_environment_only": True,
        "credentials_scope": DEFAULT_CREDENTIALS_SCOPE,
        "staging_branch": DEFAULT_STAGING_BRANCH,
        "staging_revision": staging_sha,
        "staging_canary_passed": True,
        "staging_redownload_verified": True,
        "staging_canary_manifest_digest": digest,
        "immutable_redownload_required": True,
        "authorization_receipt_id": "auth-state-laws-main-001",
        "authorize_mutation": True,
        "payload": {
            "release_mode": RELEASE_MODE,
            "credentials_environment_only": True,
            "secret_redacted": True,
        },
        "argv": ["publish-state-laws", "--phase", "main"],
    }


def sealed_authorization_fixture_payload() -> dict[str, Any]:
    """Return the canonical sealed authorization fixture body."""

    return {
        "schema": AUTHORIZATION_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "fixture_id": "state-laws-publication-authorization-v1",
        "notes": (
            "Sealed 2026-08-10 operator authorization for additive updates of "
            "justicedao/ipfs_state_laws only. Live mutation is refused until "
            "exact-51 coverage, final manifest authorization, staging canary, "
            "and secret-redaction checks all pass. Credentials are "
            "environment-only and never enter argv, plans, receipts, or Git."
        ),
        "status": AUTHORIZATION_STATUS,
        "recorded_on": AUTHORIZED_ON,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "authorized_dataset_repo_ids": [DEFAULT_DATASET_REPO_ID],
        "authorized_operations": sorted(AUTHORIZED_OPERATIONS),
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "release_mode": RELEASE_MODE,
        "credentials_environment_only": True,
        "credentials_scope": DEFAULT_CREDENTIALS_SCOPE,
        "secret_redaction_required": True,
        "staging_first_required": True,
        "exact_51_coverage_required": True,
        "final_manifest_authorization_required": True,
        "staging_canary_required": True,
        "immutable_redownload_required": True,
        "rollback_pin_must_be_preserved": True,
        "deletion_allowed": False,
        "force_push_allowed": False,
        "history_rewrite_allowed": False,
        "visibility_change_allowed": False,
        "alternate_dataset_targets_allowed": False,
        "required_gates": list(REQUIRED_LIVE_MUTATION_GATES),
        "default_staging_branch": DEFAULT_STAGING_BRANCH,
        "jurisdiction_contract": {
            "required_count": EXPECTED_JURISDICTION_COUNT,
            "required_codes": sorted(CANONICAL_JURISDICTIONS),
            "extra_codes_allowed": False,
            "subset_rejection_required": True,
        },
        "live_publication": {
            "staging_target_must_be_explicit": True,
            "staging_redownload_canary_required": True,
            "staging_and_main_manifest_identity_required": True,
            "public_immutable_redownload_canary_required": True,
            "rollback_rehearsal_required": True,
            "previous_public_pin_must_be_preserved": True,
            "legacy_artifact_deletion_allowed": False,
        },
        "credential_policy": {
            "environment_only": True,
            "secret_env_names": list(SECRET_ENV_NAMES),
            "argv_secrets_forbidden": True,
            "receipt_secrets_forbidden": True,
            "missing_credentials_park_publication_only": True,
        },
        "payload": {
            "authorization_source": "2026-08-10 operator request",
            "mutation_requires_authorization": True,
            "credentials_environment_only": True,
            "secret_redacted": True,
        },
    }


__all__ = [
    "AUTHORIZATION_SCHEMA",
    "AUTHORIZED_ON",
    "AUTHORIZED_OPERATIONS",
    "AUTHORIZATION_STATUS",
    "AuthorizationRecordError",
    "CANONICAL_JURISDICTIONS",
    "CREDENTIALS_SCOPE_PREFIX",
    "CredentialPolicyError",
    "DEFAULT_CREDENTIALS_SCOPE",
    "DEFAULT_DATASET_REPO_ID",
    "DEFAULT_STAGING_BRANCH",
    "EXPECTED_JURISDICTION_COUNT",
    "FORBIDDEN_OPERATIONS",
    "GOAL_ID",
    "JurisdictionCoverageError",
    "LiveMutationDeniedError",
    "LiveMutationRequest",
    "ManifestAuthorizationError",
    "MutationPhase",
    "OperationForbiddenError",
    "PREVIOUS_PUBLIC_PIN",
    "PROGRAM_ID",
    "PRODUCER",
    "PublicationAuthorization",
    "PublicationDecision",
    "PublicationOperation",
    "REQUIRED_LIVE_MUTATION_GATES",
    "RELEASE_MODE",
    "RollbackPinError",
    "SCHEMA_VERSION",
    "SECRET_ENV_NAMES",
    "SecretRedactionError",
    "StagingCanaryError",
    "StagingFirstError",
    "StateLawsPublicationPolicyError",
    "TASK_ID",
    "TargetUnauthorizedError",
    "assert_environment_only_credentials",
    "assert_operation_authorized",
    "assert_rollback_pin_preserved",
    "assert_target_authorized",
    "check_exact_51_coverage",
    "check_final_manifest_authorization",
    "check_secret_redaction",
    "check_staging_canary",
    "clear_authorization_cache",
    "default_authorization_fixture_path",
    "evaluate_live_mutation",
    "example_authorized_main_request",
    "example_authorized_staging_request",
    "get_publication_authorization",
    "is_immutable_revision",
    "load_publication_authorization",
    "normalize_dataset_repo_id",
    "normalize_operation",
    "normalize_operations",
    "normalize_postal_code",
    "normalize_sha256",
    "normalize_staging_branch",
    "redact_secrets",
    "reject_credentials_in_payload",
    "reject_secrets_in_argv",
    "repository_root",
    "require_immutable_revision",
    "require_live_mutation",
    "sealed_authorization_fixture_payload",
    "validate_exact_51_coverage",
]
