"""Fail-closed staged and public mutation gate (LCR-074).

Reusable preflight every staging/main uploader must invoke **before** its
first network mutation against the authorized legal-corpora targets:

* ``justicedao/ipfs_state_laws``
* ``justicedao/ipfs_federal_register``

Design invariants
-----------------
* **Phase-specific contracts**: ``state_staging``, ``state_main``,
  ``federal_staging``, and ``federal_main`` each bind their own required
  task ancestor closure, receipt set, target, and operation. Registry lists
  are informational and never authorize a mutation.
* **Staging vs main seals**: staging requires its complete candidate /
  live-evidence receipt set but **must not** require the post-canary main
  prepublication seal. Main requires that seal and refuses absent, future,
  or post-hoc seals.
* **Generated-work guard**: any nonterminal task numbered ``LCR-077`` or
  later whose goal-parent lineage intersects the phase's goal roots blocks
  that phase; unknown or unscoped generated lineage blocks every phase.
* **No network I/O**: this module never contacts the Hub and never invokes
  an upload callback unless every gate has passed.
* **Secret safety**: credentials remain environment-only; secrets never
  enter decisions, receipts, or argv surfaces managed here.
* **Additive only**: delete, force-push, history rewrite, and visibility
  changes are structurally forbidden.

Upload implementations (LCR-040/042/064/065+) must call
:func:`evaluate_publication_gate` / :func:`require_publication_gate` or
:func:`authorize_and_mutate` before any Hub write.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Mapping,
    Optional,
    Sequence,
    TypeVar,
    Union,
)

# ---------------------------------------------------------------------------
# Schema / task identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "legal-corpora-publication-gate-v1"
GATE_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-publication-gate@1"
TASK_ID: Final = "LCR-074"
GOAL_ID: Final = "LCR-G080"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "legal_corpora_publication_gate.py"

STATE_DATASET_REPO_ID: Final = "justicedao/ipfs_state_laws"
FEDERAL_DATASET_REPO_ID: Final = "justicedao/ipfs_federal_register"
AUTHORIZED_DATASET_REPO_IDS: Final = frozenset(
    {STATE_DATASET_REPO_ID, FEDERAL_DATASET_REPO_ID}
)

STATE_PREVIOUS_PUBLIC_PIN: Final = "42f0546acc7c6cd55627eaf51fb820d5613b9021"
FEDERAL_PREVIOUS_PUBLIC_PIN: Final = "720668ae016cc400916dda884c9005e03618edfa"
BASELINE_REVISIONS: Final = MappingProxyType(
    {
        STATE_DATASET_REPO_ID: STATE_PREVIOUS_PUBLIC_PIN,
        FEDERAL_DATASET_REPO_ID: FEDERAL_PREVIOUS_PUBLIC_PIN,
    }
)

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
        "rotate_credentials",
    }
)

GENERATED_WORK_TASK_NUMBER_FLOOR: Final = 77
TERMINAL_TASK_STATUSES: Final = frozenset({"completed"})
NONTERMINAL_TASK_STATUSES: Final = frozenset(
    {"todo", "in_progress", "blocked", "waiting", "ready", "parked", "failed"}
)

DEFAULT_FIXTURE_RELATIVE_PATH: Final = Path(
    "tests/fixtures/legal_ir/legal_corpora_publication_gate.json"
)
DEFAULT_RELEASE_POLICY_RELATIVE_PATH: Final = Path(
    "data/agent_supervisor/legal_corpora_reindex/bundles/release_policy.json"
)

SECRET_ENV_NAMES: Final = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "STATE_LAWS_HF_TOKEN",
    "FEDERAL_REGISTER_HF_TOKEN",
    "STATE_LAWS_PUBLICATION_AUTHORIZATION",
)

CREDENTIALS_SCOPE_PREFIX: Final = "dataset:write:"

# Phase-local seal receipt paths (main-only).
STATE_PREPUBLICATION_SEAL_PATH: Final = (
    "docs/reports/legal_corpora_reindex/state_prepublication_seal.json"
)
FEDERAL_PREPUBLICATION_SEAL_PATH: Final = (
    "docs/reports/legal_corpora_reindex/federal_prepublication_seal.json"
)
MAIN_SEAL_PATHS: Final = frozenset(
    {STATE_PREPUBLICATION_SEAL_PATH, FEDERAL_PREPUBLICATION_SEAL_PATH}
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
T = TypeVar("T")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TASK_ID_RE = re.compile(r"^LCR-(\d{3,})$")
_GOAL_ID_RE = re.compile(r"^LCR-G(\d{3,})$")
_DATASET_ID_RE = re.compile(
    r"^[A-Za-z0-9](?:[\w.-]{0,37}[A-Za-z0-9])?/"
    r"[A-Za-z0-9](?:[\w.-]{0,99}[A-Za-z0-9])?$"
)
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


class PublicationGateError(ValueError):
    """Base error for publication-gate failures."""

    code: str = "publication_gate_error"


class PhaseContractError(PublicationGateError):
    """Raised when the phase contract is missing or malformed."""

    code = "phase_contract_error"


class TaskAncestryError(PublicationGateError):
    """Raised when required tasks or ancestor closure are incomplete."""

    code = "task_ancestry_error"


class GeneratedWorkGuardError(PublicationGateError):
    """Raised when nonterminal generated refill work blocks the phase."""

    code = "generated_work_guard_error"


class ReceiptEvidenceError(PublicationGateError):
    """Raised when phase receipts are missing, fixture-only, or dirty."""

    code = "receipt_evidence_error"


class DigestDriftError(PublicationGateError):
    """Raised when receipt digests or statuses drift from expectations."""

    code = "digest_drift_error"


class PrepublicationSealError(PublicationGateError):
    """Raised when main-only seal evidence is absent/future/post-hoc."""

    code = "prepublication_seal_error"


class StagingSealSubstitutionError(PublicationGateError):
    """Raised when staging substitutes a later main seal for phase evidence."""

    code = "staging_seal_substitution_error"


class OperationForbiddenError(PublicationGateError):
    """Raised when the requested operation is not additive/authorized."""

    code = "operation_forbidden_error"


class TargetUnauthorizedError(PublicationGateError):
    """Raised when the dataset target is outside the sealed authorization."""

    code = "target_unauthorized_error"


class CredentialMismatchError(PublicationGateError):
    """Raised when credential scope/identity does not match the target."""

    code = "credential_mismatch_error"


class DirtyEvidenceError(PublicationGateError):
    """Raised when evidence surfaces are dirty or unsealed."""

    code = "dirty_evidence_error"


class PublicationGateDeniedError(PublicationGateError):
    """Raised when :func:`require_publication_gate` fails closed."""

    code = "publication_gate_denied"

    def __init__(
        self,
        message: str,
        *,
        reason_codes: Sequence[str] = (),
        decision: Optional["PublicationGateDecision"] = None,
    ) -> None:
        super().__init__(message)
        self.reason_codes = tuple(reason_codes)
        self.decision = decision


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PublicationPhase(str, Enum):
    """Phase-specific publication contracts."""

    STATE_STAGING = "state_staging"
    STATE_MAIN = "state_main"
    FEDERAL_STAGING = "federal_staging"
    FEDERAL_MAIN = "federal_main"

    @classmethod
    def coerce(cls, value: Any) -> "PublicationPhase":
        if isinstance(value, PublicationPhase):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "state_stage": cls.STATE_STAGING,
            "state_staging_upload": cls.STATE_STAGING,
            "state_public": cls.STATE_MAIN,
            "state_main_upload": cls.STATE_MAIN,
            "federal_stage": cls.FEDERAL_STAGING,
            "federal_staging_upload": cls.FEDERAL_STAGING,
            "federal_public": cls.FEDERAL_MAIN,
            "federal_main_upload": cls.FEDERAL_MAIN,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise PhaseContractError(f"unknown publication phase: {value!r}")


class PublicationOperation(str, Enum):
    """Authorized additive operations only."""

    ADDITIVE_STAGING_UPLOAD = "additive_staging_upload"
    ADDITIVE_MAIN_UPLOAD = "additive_main_upload"

    @classmethod
    def coerce(cls, value: Any) -> "PublicationOperation":
        if isinstance(value, PublicationOperation):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        if text in FORBIDDEN_OPERATIONS or text.startswith("delete") or "force" in text:
            raise OperationForbiddenError(
                f"operation is forbidden for legal-corpora publication: {value!r}"
            )
        if "visibility" in text or ("history" in text and "rewrite" in text):
            raise OperationForbiddenError(
                f"operation is forbidden for legal-corpora publication: {value!r}"
            )
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
# Sealed phase contracts (mirror release_policy.prepublication_evidence_contract)
# ---------------------------------------------------------------------------


def _phase_contract(
    *,
    dataset_repo_id: str,
    authorized_operation: str,
    required_task_ids: Sequence[str],
    required_receipts: Sequence[str],
    prepublication_seal_required: bool,
    generated_work_goal_roots: Sequence[str],
    previous_public_pin: str,
    seal_receipt_path: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "dataset_repo_id": dataset_repo_id,
        "authorized_operation": authorized_operation,
        "required_task_ids": list(required_task_ids),
        "required_receipts": list(required_receipts),
        "prepublication_seal_required": prepublication_seal_required,
        "generated_work_goal_roots": list(generated_work_goal_roots),
        "previous_public_pin": previous_public_pin,
        "seal_receipt_path": seal_receipt_path,
    }


PHASE_REQUIREMENTS: Final[Mapping[str, Mapping[str, Any]]] = MappingProxyType(
    {
        PublicationPhase.STATE_STAGING.value: _phase_contract(
            dataset_repo_id=STATE_DATASET_REPO_ID,
            authorized_operation="additive_staging_upload",
            required_task_ids=(
                "LCR-039",
                "LCR-070",
                "LCR-074",
                "LCR-079",
                "LCR-084",
            ),
            required_receipts=(
                "docs/reports/legal_corpora_reindex/live_baseline_provenance_receipt.json",
                "docs/reports/legal_corpora_reindex/full_scrape_acceptance.json",
                "docs/reports/legal_corpora_reindex/local_e2e.json",
                "docs/reports/legal_corpora_reindex/release_candidate.json",
                "docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json",
            ),
            prepublication_seal_required=False,
            generated_work_goal_roots=(
                "LCR-G010",
                "LCR-G020",
                "LCR-G030",
                "LCR-G040",
                "LCR-G050",
                "LCR-G060",
                "LCR-G070",
                "LCR-G080",
            ),
            previous_public_pin=STATE_PREVIOUS_PUBLIC_PIN,
            seal_receipt_path=None,
        ),
        PublicationPhase.STATE_MAIN.value: _phase_contract(
            dataset_repo_id=STATE_DATASET_REPO_ID,
            authorized_operation="additive_main_upload",
            required_task_ids=(
                "LCR-041",
                "LCR-070",
                "LCR-072",
                "LCR-074",
                "LCR-079",
                "LCR-084",
            ),
            required_receipts=(
                "docs/reports/legal_corpora_reindex/live_baseline_provenance_receipt.json",
                "docs/reports/legal_corpora_reindex/full_scrape_acceptance.json",
                "docs/reports/legal_corpora_reindex/local_e2e.json",
                "docs/reports/legal_corpora_reindex/release_candidate.json",
                "docs/reports/legal_corpora_reindex/staging_upload.json",
                "docs/reports/legal_corpora_reindex/staging_canary.json",
                "docs/reports/legal_corpora_reindex/state_prepublication_seal.json",
                "docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json",
            ),
            prepublication_seal_required=True,
            generated_work_goal_roots=(
                "LCR-G010",
                "LCR-G020",
                "LCR-G030",
                "LCR-G040",
                "LCR-G050",
                "LCR-G060",
                "LCR-G070",
                "LCR-G080",
            ),
            previous_public_pin=STATE_PREVIOUS_PUBLIC_PIN,
            seal_receipt_path=STATE_PREPUBLICATION_SEAL_PATH,
        ),
        PublicationPhase.FEDERAL_STAGING.value: _phase_contract(
            dataset_repo_id=FEDERAL_DATASET_REPO_ID,
            authorized_operation="additive_staging_upload",
            required_task_ids=(
                "LCR-063",
                "LCR-070",
                "LCR-071",
                "LCR-074",
                "LCR-075",
                "LCR-076",
                "LCR-079",
                "LCR-084",
            ),
            required_receipts=(
                "docs/reports/legal_corpora_reindex/live_baseline_provenance_receipt.json",
                "docs/reports/legal_corpora_reindex/federal_inventory.json",
                "docs/reports/legal_corpora_reindex/federal_fulltext_coverage.json",
                "docs/reports/legal_corpora_reindex/federal_candidate.json",
                "docs/reports/legal_corpora_reindex/federal_evaluation.json",
                "docs/reports/legal_corpora_reindex/federal_full_live_acceptance.json",
                "docs/reports/legal_corpora_reindex/federal_adjacency_reconciliation.json",
                "docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json",
            ),
            prepublication_seal_required=False,
            generated_work_goal_roots=(
                "LCR-G010",
                "LCR-G080",
                "LCR-G100",
                "LCR-G110",
                "LCR-G120",
                "LCR-G130",
            ),
            previous_public_pin=FEDERAL_PREVIOUS_PUBLIC_PIN,
            seal_receipt_path=None,
        ),
        PublicationPhase.FEDERAL_MAIN.value: _phase_contract(
            dataset_repo_id=FEDERAL_DATASET_REPO_ID,
            authorized_operation="additive_main_upload",
            required_task_ids=(
                "LCR-064",
                "LCR-070",
                "LCR-071",
                "LCR-073",
                "LCR-074",
                "LCR-075",
                "LCR-076",
                "LCR-079",
                "LCR-084",
            ),
            required_receipts=(
                "docs/reports/legal_corpora_reindex/live_baseline_provenance_receipt.json",
                "docs/reports/legal_corpora_reindex/federal_inventory.json",
                "docs/reports/legal_corpora_reindex/federal_fulltext_coverage.json",
                "docs/reports/legal_corpora_reindex/federal_candidate.json",
                "docs/reports/legal_corpora_reindex/federal_evaluation.json",
                "docs/reports/legal_corpora_reindex/federal_full_live_acceptance.json",
                "docs/reports/legal_corpora_reindex/federal_adjacency_reconciliation.json",
                "docs/reports/legal_corpora_reindex/federal_staging_canary.json",
                "docs/reports/legal_corpora_reindex/federal_prepublication_seal.json",
                "docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json",
            ),
            prepublication_seal_required=True,
            generated_work_goal_roots=(
                "LCR-G010",
                "LCR-G080",
                "LCR-G100",
                "LCR-G110",
                "LCR-G120",
                "LCR-G130",
                "LCR-G140",
            ),
            previous_public_pin=FEDERAL_PREVIOUS_PUBLIC_PIN,
            seal_receipt_path=FEDERAL_PREPUBLICATION_SEAL_PATH,
        ),
    }
)

GENERATED_WORK_GUARD: Final[Mapping[str, Any]] = MappingProxyType(
    {
        "task_number_floor": GENERATED_WORK_TASK_NUMBER_FLOOR,
        "terminal_statuses": sorted(TERMINAL_TASK_STATUSES),
        "scope_rule": "task_goal_parent_lineage_intersects_phase_goal_roots",
        "deny_nonterminal_matching_generated_work": True,
        "unscoped_or_unknown_goal_lineage_denies_every_phase": True,
        "review_only_or_unschedulable_exemption_allowed": False,
    }
)


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def repository_root() -> Path:
    """Return the repository root that contains ``tests/fixtures``."""

    return Path(__file__).resolve().parents[3]


def default_fixture_path() -> Path:
    return repository_root() / DEFAULT_FIXTURE_RELATIVE_PATH


def default_release_policy_path() -> Path:
    return repository_root() / DEFAULT_RELEASE_POLICY_RELATIVE_PATH


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublicationGateError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise PublicationGateError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise PublicationGateError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise PublicationGateError(f"{name} must be a boolean")
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
        raise DigestDriftError(
            f"{name} must be a 64-character lowercase hex digest"
        )
    return text


def require_immutable_revision(value: Any, *, name: str = "revision") -> str:
    text = _require_non_empty_str(value, name, maximum=128).casefold()
    if _MUTABLE_REVISION_RE.fullmatch(text):
        raise DigestDriftError(
            f"{name} must be an immutable commit SHA, not a mutable pin "
            f"({value!r})"
        )
    if not _GIT_SHA_RE.fullmatch(text):
        raise DigestDriftError(
            f"{name} must be a 40-character lowercase hex commit SHA, got {value!r}"
        )
    return text


def normalize_operation(value: Any) -> str:
    return PublicationOperation.coerce(value).value


def task_number(task_id: str) -> int:
    match = _TASK_ID_RE.fullmatch(str(task_id or "").strip())
    if not match:
        raise PublicationGateError(f"invalid task id: {task_id!r}")
    return int(match.group(1))


def credentials_scope_for(dataset_repo_id: str) -> str:
    repo = normalize_dataset_repo_id(dataset_repo_id)
    return f"{CREDENTIALS_SCOPE_PREFIX}{repo}"


def phase_requirements(
    phase: PublicationPhase | str | None = None,
) -> Mapping[str, Any]:
    """Return sealed phase requirements (all phases or one)."""

    if phase is None:
        return PHASE_REQUIREMENTS
    key = PublicationPhase.coerce(phase).value
    contract = PHASE_REQUIREMENTS.get(key)
    if contract is None:
        raise PhaseContractError(f"no phase contract for {key!r}")
    return contract


def prepublication_seal_required(phase: PublicationPhase | str) -> bool:
    contract = phase_requirements(phase)
    return bool(contract["prepublication_seal_required"])


def digest_mapping(value: Mapping[str, Any]) -> str:
    """Stable content digest for a JSON-like mapping."""

    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# Secret redaction (local; does not depend on LCR-008 module internals)
# ---------------------------------------------------------------------------


def reject_credentials_in_payload(
    value: Any,
    *,
    label: str = "payload",
    environ: Optional[Mapping[str, str]] = None,
) -> None:
    """Fail closed when tokens or credential-like values appear."""

    env = environ if environ is not None else {}
    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _TOKEN_KEY_RE.search(key_text) and not isinstance(child, bool):
                    if key_text.casefold() in {
                        "credentials_scope",
                        "credentials_environment_only",
                        "secret_redaction_required",
                        "secret_redacted",
                        "authorization_status",
                        "authorization_receipt_id",
                        "mutation_requires_authorization",
                        "credential_identity",
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
        raise CredentialMismatchError(
            f"credential-like material in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


# ---------------------------------------------------------------------------
# Goal lineage / ancestry
# ---------------------------------------------------------------------------


def goal_parent_lineage_intersects(
    goal_id: str,
    roots: Iterable[str],
    goal_parents: Mapping[str, Iterable[str]],
) -> bool:
    """Return True when *goal_id* or any ancestor is in *roots*."""

    wanted = {str(root) for root in roots}
    if not goal_id:
        return False
    pending = [str(goal_id)]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        if current in wanted:
            return True
        parents = goal_parents.get(current, ())
        pending.extend(str(parent) for parent in parents)
    return False


def collect_task_ancestor_closure(
    task_ids: Iterable[str],
    task_dependencies: Mapping[str, Iterable[str]],
) -> tuple[str, ...]:
    """Return the transitive dependency closure of *task_ids* (sorted)."""

    pending = [str(task_id) for task_id in task_ids]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        deps = task_dependencies.get(current, ())
        pending.extend(str(dep) for dep in deps)
    return tuple(sorted(seen))


def find_incomplete_tasks(
    required_task_ids: Iterable[str],
    task_statuses: Mapping[str, Any],
    *,
    task_dependencies: Optional[Mapping[str, Iterable[str]]] = None,
    require_ancestor_closure: bool = True,
) -> tuple[str, ...]:
    """Return incomplete required tasks (and optional ancestor closure)."""

    required = [str(task_id) for task_id in required_task_ids]
    if require_ancestor_closure and task_dependencies is not None:
        required = list(
            collect_task_ancestor_closure(required, task_dependencies)
        )
    incomplete: list[str] = []
    for task_id in sorted(set(required)):
        status = str(task_statuses.get(task_id, "") or "").strip().lower()
        if status not in TERMINAL_TASK_STATUSES:
            incomplete.append(task_id)
    return tuple(incomplete)


def find_publication_blocking_generated_work(
    *,
    phase: PublicationPhase | str,
    task_statuses: Mapping[str, Any],
    task_goal_ids: Mapping[str, str],
    goal_parents: Mapping[str, Iterable[str]],
    task_number_floor: int = GENERATED_WORK_TASK_NUMBER_FLOOR,
    review_only_tasks: Optional[Iterable[str]] = None,
    unschedulable_tasks: Optional[Iterable[str]] = None,
) -> tuple[str, ...]:
    """Return nonterminal generated tasks that block *phase*.

    Unknown or unscoped goal lineage denies every phase (caller applies the
    same blocker set to all phases when this helper is used per-phase with the
    unscoped-match rule).
    """

    contract = phase_requirements(phase)
    roots = tuple(contract["generated_work_goal_roots"])
    all_roots = {
        root
        for phase_contract in PHASE_REQUIREMENTS.values()
        for root in phase_contract["generated_work_goal_roots"]
    }
    exempt = set(review_only_tasks or ()) | set(unschedulable_tasks or ())
    # Exemptions are intentionally ignored: policy forbids them.
    _ = exempt

    blockers: list[str] = []
    for raw_task_id, raw_status in task_statuses.items():
        task_id = str(raw_task_id)
        try:
            number = task_number(task_id)
        except PublicationGateError:
            continue
        if number < task_number_floor:
            continue
        status = str(raw_status or "").strip().lower()
        if status in TERMINAL_TASK_STATUSES:
            continue
        goal_id = str(task_goal_ids.get(task_id, "") or "")
        if not goal_id:
            # Unknown lineage denies every phase.
            blockers.append(task_id)
            continue
        in_phase = goal_parent_lineage_intersects(goal_id, roots, goal_parents)
        known_scope = goal_parent_lineage_intersects(
            goal_id, all_roots, goal_parents
        )
        if in_phase or not known_scope:
            blockers.append(task_id)
    return tuple(sorted(set(blockers)))


# ---------------------------------------------------------------------------
# Request / decision models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PublicationGateRequest:
    """Inputs evaluated before any live Hub mutation.

    Callers supply phase, target, operation, taskboard snapshot, receipt
    evidence, seal timing, and credential identity. Credentials themselves
    never appear on this object.
    """

    phase: str
    operation: str
    dataset_repo_id: str
    final_manifest_digest: str
    previous_public_pin: str
    task_statuses: Mapping[str, str] = field(default_factory=dict)
    task_dependencies: Mapping[str, Sequence[str]] = field(default_factory=dict)
    task_goal_ids: Mapping[str, str] = field(default_factory=dict)
    goal_parents: Mapping[str, Sequence[str]] = field(default_factory=dict)
    receipts: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    expected_receipt_digests: Mapping[str, str] = field(default_factory=dict)
    staging_revision: Optional[str] = None
    staging_branch: Optional[str] = None
    current_commit: Optional[str] = None
    prepublication_seal: Optional[Mapping[str, Any]] = None
    credentials_environment_only: bool = True
    credentials_scope: Optional[str] = None
    credential_identity: Optional[str] = None
    secret_redacted: bool = True
    authorize_mutation: bool = False
    evidence_is_dirty: bool = False
    fixture_only_evidence: bool = False
    payload: Mapping[str, Any] = field(default_factory=dict)
    argv: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        phase = PublicationPhase.coerce(self.phase)
        object.__setattr__(self, "phase", phase.value)
        op = normalize_operation(self.operation)
        object.__setattr__(self, "operation", op)
        object.__setattr__(
            self,
            "dataset_repo_id",
            normalize_dataset_repo_id(self.dataset_repo_id),
        )
        object.__setattr__(
            self,
            "final_manifest_digest",
            normalize_sha256(
                self.final_manifest_digest, name="final_manifest_digest"
            ),
        )
        object.__setattr__(
            self,
            "previous_public_pin",
            require_immutable_revision(
                self.previous_public_pin, name="previous_public_pin"
            ),
        )
        object.__setattr__(
            self,
            "credentials_environment_only",
            _require_bool(
                self.credentials_environment_only, "credentials_environment_only"
            ),
        )
        object.__setattr__(
            self, "secret_redacted", _require_bool(self.secret_redacted, "secret_redacted")
        )
        object.__setattr__(
            self,
            "authorize_mutation",
            _require_bool(self.authorize_mutation, "authorize_mutation"),
        )
        object.__setattr__(
            self,
            "evidence_is_dirty",
            _require_bool(self.evidence_is_dirty, "evidence_is_dirty"),
        )
        object.__setattr__(
            self,
            "fixture_only_evidence",
            _require_bool(self.fixture_only_evidence, "fixture_only_evidence"),
        )
        if self.staging_revision is not None:
            object.__setattr__(
                self,
                "staging_revision",
                require_immutable_revision(
                    self.staging_revision, name="staging_revision"
                ),
            )
        if self.current_commit is not None:
            object.__setattr__(
                self,
                "current_commit",
                require_immutable_revision(
                    self.current_commit, name="current_commit"
                ),
            )
        if self.staging_branch is not None:
            object.__setattr__(
                self,
                "staging_branch",
                _require_non_empty_str(self.staging_branch, "staging_branch"),
            )
        if self.credentials_scope is not None:
            object.__setattr__(
                self,
                "credentials_scope",
                _require_non_empty_str(self.credentials_scope, "credentials_scope"),
            )
        if self.credential_identity is not None:
            object.__setattr__(
                self,
                "credential_identity",
                _require_non_empty_str(
                    self.credential_identity, "credential_identity"
                ),
            )
        object.__setattr__(
            self,
            "task_statuses",
            MappingProxyType(
                {str(k): str(v) for k, v in dict(self.task_statuses).items()}
            ),
        )
        object.__setattr__(
            self,
            "task_dependencies",
            MappingProxyType(
                {
                    str(k): tuple(str(d) for d in v)
                    for k, v in dict(self.task_dependencies).items()
                }
            ),
        )
        object.__setattr__(
            self,
            "task_goal_ids",
            MappingProxyType(
                {str(k): str(v) for k, v in dict(self.task_goal_ids).items()}
            ),
        )
        object.__setattr__(
            self,
            "goal_parents",
            MappingProxyType(
                {
                    str(k): tuple(str(p) for p in v)
                    for k, v in dict(self.goal_parents).items()
                }
            ),
        )
        object.__setattr__(
            self,
            "receipts",
            MappingProxyType(
                {
                    str(k): MappingProxyType(dict(v)) if isinstance(v, Mapping) else {}
                    for k, v in dict(self.receipts).items()
                }
            ),
        )
        object.__setattr__(
            self,
            "expected_receipt_digests",
            MappingProxyType(
                {
                    str(k): normalize_sha256(v, name=f"expected_receipt_digests[{k}]")
                    for k, v in dict(self.expected_receipt_digests).items()
                }
            ),
        )
        if self.prepublication_seal is not None:
            if not isinstance(self.prepublication_seal, Mapping):
                raise PrepublicationSealError("prepublication_seal must be a mapping")
            object.__setattr__(
                self,
                "prepublication_seal",
                MappingProxyType(dict(self.prepublication_seal)),
            )
        if not isinstance(self.payload, Mapping):
            raise PublicationGateError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "argv", tuple(str(a) for a in self.argv))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PublicationGateRequest":
        if not isinstance(value, Mapping):
            raise PublicationGateError("publication gate request must be a mapping")
        return cls(
            phase=value.get("phase", ""),
            operation=value.get("operation", ""),
            dataset_repo_id=value.get("dataset_repo_id", ""),
            final_manifest_digest=value.get("final_manifest_digest", ""),
            previous_public_pin=value.get("previous_public_pin", ""),
            task_statuses=value.get("task_statuses") or {},
            task_dependencies=value.get("task_dependencies") or {},
            task_goal_ids=value.get("task_goal_ids") or {},
            goal_parents=value.get("goal_parents") or {},
            receipts=value.get("receipts") or {},
            expected_receipt_digests=value.get("expected_receipt_digests") or {},
            staging_revision=value.get("staging_revision"),
            staging_branch=value.get("staging_branch"),
            current_commit=value.get("current_commit"),
            prepublication_seal=value.get("prepublication_seal"),
            credentials_environment_only=value.get(
                "credentials_environment_only", True
            ),
            credentials_scope=value.get("credentials_scope"),
            credential_identity=value.get("credential_identity"),
            secret_redacted=value.get("secret_redacted", True),
            authorize_mutation=value.get("authorize_mutation", False),
            evidence_is_dirty=value.get("evidence_is_dirty", False),
            fixture_only_evidence=value.get("fixture_only_evidence", False),
            payload=value.get("payload") or {},
            argv=tuple(value.get("argv") or ()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorize_mutation": self.authorize_mutation,
            "argv": list(self.argv),
            "credential_identity": self.credential_identity,
            "credentials_environment_only": self.credentials_environment_only,
            "credentials_scope": self.credentials_scope,
            "current_commit": self.current_commit,
            "dataset_repo_id": self.dataset_repo_id,
            "evidence_is_dirty": self.evidence_is_dirty,
            "expected_receipt_digests": dict(self.expected_receipt_digests),
            "final_manifest_digest": self.final_manifest_digest,
            "fixture_only_evidence": self.fixture_only_evidence,
            "goal_parents": {k: list(v) for k, v in self.goal_parents.items()},
            "operation": self.operation,
            "payload": dict(self.payload),
            "phase": self.phase,
            "prepublication_seal": (
                dict(self.prepublication_seal)
                if self.prepublication_seal is not None
                else None
            ),
            "previous_public_pin": self.previous_public_pin,
            "receipts": {k: dict(v) for k, v in self.receipts.items()},
            "secret_redacted": self.secret_redacted,
            "staging_branch": self.staging_branch,
            "staging_revision": self.staging_revision,
            "task_dependencies": {
                k: list(v) for k, v in self.task_dependencies.items()
            },
            "task_goal_ids": dict(self.task_goal_ids),
            "task_statuses": dict(self.task_statuses),
        }


@dataclass(frozen=True, slots=True)
class PublicationGateDecision:
    """Fail-closed decision for a publication-gate request."""

    authorized: bool
    phase: str
    operation: str
    dataset_repo_id: str
    final_manifest_digest: str
    reason_codes: tuple[str, ...]
    passed_gates: tuple[str, ...]
    required_gates: tuple[str, ...]
    previous_public_pin: str = ""
    message: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)
    network_mutation_permitted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "authorized", _require_bool(self.authorized, "authorized")
        )
        object.__setattr__(
            self,
            "network_mutation_permitted",
            _require_bool(
                self.network_mutation_permitted, "network_mutation_permitted"
            ),
        )
        if self.authorized and not self.network_mutation_permitted:
            object.__setattr__(self, "network_mutation_permitted", True)
        if not self.authorized:
            object.__setattr__(self, "network_mutation_permitted", False)
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "passed_gates", tuple(self.passed_gates))
        object.__setattr__(self, "required_gates", tuple(self.required_gates))
        if not isinstance(self.details, Mapping):
            raise PublicationGateError("details must be a mapping")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorized": self.authorized,
            "dataset_repo_id": self.dataset_repo_id,
            "details": dict(self.details),
            "final_manifest_digest": self.final_manifest_digest,
            "message": self.message,
            "network_mutation_permitted": self.network_mutation_permitted,
            "operation": self.operation,
            "passed_gates": list(self.passed_gates),
            "phase": self.phase,
            "previous_public_pin": self.previous_public_pin,
            "reason_codes": list(self.reason_codes),
            "required_gates": list(self.required_gates),
            "schema": GATE_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
        }

    def require_authorized(self) -> "PublicationGateDecision":
        if not self.authorized:
            raise PublicationGateDeniedError(
                self.message
                or (
                    "publication gate denied: "
                    + ", ".join(self.reason_codes or ("policy.denied",))
                ),
                reason_codes=self.reason_codes,
                decision=self,
            )
        return self


REQUIRED_PUBLICATION_GATES: Final = (
    "phase_target_operation",
    "task_ancestor_closure",
    "generated_work_guard",
    "receipt_evidence",
    "digest_status_binding",
    "prepublication_seal",
    "credential_identity",
    "evidence_cleanliness",
)


# ---------------------------------------------------------------------------
# Gate evaluators
# ---------------------------------------------------------------------------


def check_phase_target_operation(request: PublicationGateRequest) -> None:
    phase = PublicationPhase.coerce(request.phase)
    contract = phase_requirements(phase)
    if request.dataset_repo_id != contract["dataset_repo_id"]:
        raise TargetUnauthorizedError(
            f"phase {phase.value} requires dataset_repo_id="
            f"{contract['dataset_repo_id']!r}, got {request.dataset_repo_id!r}"
        )
    if request.dataset_repo_id not in AUTHORIZED_DATASET_REPO_IDS:
        raise TargetUnauthorizedError(
            f"dataset target {request.dataset_repo_id!r} is not authorized"
        )
    if request.operation != contract["authorized_operation"]:
        raise OperationForbiddenError(
            f"phase {phase.value} requires operation="
            f"{contract['authorized_operation']!r}, got {request.operation!r}"
        )
    if request.operation not in AUTHORIZED_OPERATIONS:
        raise OperationForbiddenError(
            f"operation {request.operation!r} is not authorized"
        )
    expected_pin = contract["previous_public_pin"]
    if request.previous_public_pin != expected_pin:
        raise DigestDriftError(
            f"previous_public_pin must remain {expected_pin!r}, "
            f"got {request.previous_public_pin!r}"
        )
    if not request.authorize_mutation:
        raise OperationForbiddenError(
            "authorize_mutation must be true before any network mutation"
        )


def check_task_ancestor_closure(request: PublicationGateRequest) -> None:
    contract = phase_requirements(request.phase)
    incomplete = find_incomplete_tasks(
        contract["required_task_ids"],
        request.task_statuses,
        task_dependencies=request.task_dependencies,
        require_ancestor_closure=True,
    )
    if incomplete:
        raise TaskAncestryError(
            "required tasks or ancestor closure incomplete: "
            + ", ".join(incomplete)
        )


def check_generated_work_guard(request: PublicationGateRequest) -> None:
    blockers = find_publication_blocking_generated_work(
        phase=request.phase,
        task_statuses=request.task_statuses,
        task_goal_ids=request.task_goal_ids,
        goal_parents=request.goal_parents,
    )
    if blockers:
        raise GeneratedWorkGuardError(
            "nonterminal generated work blocks publication: "
            + ", ".join(blockers)
        )


def check_receipt_evidence(request: PublicationGateRequest) -> None:
    if request.fixture_only_evidence:
        raise ReceiptEvidenceError(
            "fixture-only evidence is not allowed for live mutation"
        )
    contract = phase_requirements(request.phase)
    required = list(contract["required_receipts"])
    missing: list[str] = []
    fixture_hits: list[str] = []
    dirty_hits: list[str] = []
    for path in required:
        receipt = request.receipts.get(path)
        if not isinstance(receipt, Mapping) or not receipt:
            missing.append(path)
            continue
        if receipt.get("fixture_only") is True or receipt.get("fixture_only_evidence") is True:
            fixture_hits.append(path)
        if receipt.get("dirty") is True or receipt.get("evidence_is_dirty") is True:
            dirty_hits.append(path)
        status = str(receipt.get("status") or "").strip().lower()
        if status and status not in {"passed", "completed", "sealed", "accepted", "ok"}:
            dirty_hits.append(path)
    if missing:
        raise ReceiptEvidenceError(
            "missing phase receipts: " + ", ".join(missing)
        )
    if fixture_hits:
        raise ReceiptEvidenceError(
            "fixture-only receipts refuse live mutation: "
            + ", ".join(sorted(set(fixture_hits)))
        )
    if dirty_hits:
        raise DirtyEvidenceError(
            "dirty or non-passing receipts refuse live mutation: "
            + ", ".join(sorted(set(dirty_hits)))
        )

    # Staging must not substitute a later main seal for phase evidence.
    phase = PublicationPhase.coerce(request.phase)
    if not contract["prepublication_seal_required"]:
        for seal_path in MAIN_SEAL_PATHS:
            if seal_path in required:
                # Contract itself must not require main seals for staging.
                raise StagingSealSubstitutionError(
                    f"staging phase contract must not require main seal {seal_path}"
                )
            # If caller injects a main seal path as a substitute for required
            # phase evidence (using it as the only "authorization" surface),
            # refuse when required receipts are empty but a seal is present.
            seal_receipt = request.receipts.get(seal_path)
            if isinstance(seal_receipt, Mapping) and seal_receipt.get(
                "substitutes_for_phase_evidence"
            ):
                raise StagingSealSubstitutionError(
                    f"staging gate refuses main seal substitution via {seal_path}"
                )
        # Also refuse when prepublication_seal is supplied as phase evidence.
        if request.prepublication_seal is not None:
            seal = request.prepublication_seal
            if seal.get("substitutes_for_phase_evidence") is True:
                raise StagingSealSubstitutionError(
                    "staging gate refuses prepublication seal as phase evidence"
                )
            if seal.get("required_for_staging") is True:
                raise StagingSealSubstitutionError(
                    "staging does not require and must not demand the main seal"
                )


def check_digest_status_binding(request: PublicationGateRequest) -> None:
    contract = phase_requirements(request.phase)
    drifts: list[str] = []
    for path in contract["required_receipts"]:
        receipt = request.receipts.get(path) or {}
        actual = receipt.get("content_digest") or receipt.get("digest")
        expected = request.expected_receipt_digests.get(path)
        if expected is None:
            # When expected digests are provided for some paths, all required
            # receipts must be bound; when none are provided, require each
            # receipt to carry its own digest for live binding.
            if request.expected_receipt_digests:
                drifts.append(f"{path}:missing_expected_digest")
                continue
            if not actual:
                drifts.append(f"{path}:missing_content_digest")
                continue
            try:
                normalize_sha256(actual, name=f"{path}.content_digest")
            except DigestDriftError:
                drifts.append(f"{path}:invalid_content_digest")
            continue
        if not actual:
            drifts.append(f"{path}:missing_content_digest")
            continue
        try:
            actual_norm = normalize_sha256(actual, name=f"{path}.content_digest")
            expected_norm = normalize_sha256(expected, name=f"{path}.expected")
        except DigestDriftError:
            drifts.append(f"{path}:invalid_digest")
            continue
        if actual_norm != expected_norm:
            drifts.append(f"{path}:digest_mismatch")
        declared_status = str(receipt.get("status") or "").strip().lower()
        expected_status = str(
            receipt.get("expected_status") or "passed"
        ).strip().lower()
        if declared_status and declared_status != expected_status and expected_status in {
            "passed",
            "completed",
            "sealed",
            "accepted",
            "ok",
        }:
            # Status drift only when receipt also declares an expected status.
            if "expected_status" in receipt and declared_status != expected_status:
                drifts.append(f"{path}:status_drift")
    if drifts:
        raise DigestDriftError(
            "receipt digest/status drift: " + ", ".join(drifts)
        )

    # Manifest binding when receipts declare a final_manifest_digest.
    for path, receipt in request.receipts.items():
        if not isinstance(receipt, Mapping):
            continue
        bound = receipt.get("final_manifest_digest") or receipt.get("manifest_digest")
        if bound is None:
            continue
        try:
            bound_norm = normalize_sha256(bound, name=f"{path}.manifest")
        except DigestDriftError as exc:
            raise DigestDriftError(str(exc)) from exc
        if bound_norm != request.final_manifest_digest:
            raise DigestDriftError(
                f"receipt {path} manifest digest {bound_norm!r} drifts from "
                f"final_manifest_digest {request.final_manifest_digest!r}"
            )


def check_prepublication_seal(request: PublicationGateRequest) -> None:
    contract = phase_requirements(request.phase)
    required = bool(contract["prepublication_seal_required"])
    seal_path = contract.get("seal_receipt_path")

    if not required:
        # Staging: seal is not required. Still refuse future/post-hoc seals
        # that claim to authorize the staging mutation.
        if request.prepublication_seal is not None:
            seal = request.prepublication_seal
            timing = str(seal.get("timing") or seal.get("seal_timing") or "").lower()
            if timing in {"future", "post_hoc", "post-hoc", "after_mutation"}:
                raise PrepublicationSealError(
                    "staging refuses future/post-hoc prepublication seal timing"
                )
        return

    # Main: seal must be present, prior to mutation, and bound to the manifest.
    seal = request.prepublication_seal
    if seal is None:
        # Fall back to the seal receipt surface.
        if not seal_path or seal_path not in request.receipts:
            raise PrepublicationSealError(
                "main mutation requires a prepublication seal before mutation"
            )
        seal = dict(request.receipts[seal_path])
        seal.setdefault("path", seal_path)

    if not isinstance(seal, Mapping):
        raise PrepublicationSealError("prepublication seal must be a mapping")

    present = seal.get("present")
    if present is False:
        raise PrepublicationSealError("prepublication seal is absent")

    timing = str(
        seal.get("timing") or seal.get("seal_timing") or "before_mutation"
    ).strip().lower().replace("-", "_")
    if timing in {"absent", "missing"}:
        raise PrepublicationSealError("prepublication seal is absent")
    if timing in {"future", "after_mutation", "post_hoc", "posthoc"}:
        raise PrepublicationSealError(
            f"main mutation refuses {timing} prepublication seal"
        )
    if timing not in {"before_mutation", "pre_mutation", "sealed", "prior", "ok", ""}:
        # Unknown timing fails closed when seal is required.
        if timing:
            raise PrepublicationSealError(
                f"unrecognized prepublication seal timing: {timing!r}"
            )

    if seal.get("created_after_mutation") is True or seal.get("post_hoc") is True:
        raise PrepublicationSealError(
            "main mutation refuses post-hoc prepublication seal"
        )
    if seal.get("future") is True or seal.get("sealed_in_future") is True:
        raise PrepublicationSealError(
            "main mutation refuses future-dated prepublication seal"
        )

    bound_manifest = seal.get("final_manifest_digest") or seal.get("manifest_digest")
    if bound_manifest is not None:
        bound_norm = normalize_sha256(bound_manifest, name="seal.manifest")
        if bound_norm != request.final_manifest_digest:
            raise PrepublicationSealError(
                "prepublication seal manifest digest drifts from final_manifest_digest"
            )

    if seal_path:
        seal_receipt = request.receipts.get(seal_path)
        if not isinstance(seal_receipt, Mapping) or not seal_receipt:
            raise PrepublicationSealError(
                f"main mutation requires seal receipt at {seal_path}"
            )

    # Main also requires staging pin evidence for the canary path.
    phase = PublicationPhase.coerce(request.phase)
    if phase in {PublicationPhase.STATE_MAIN, PublicationPhase.FEDERAL_MAIN}:
        if not request.staging_revision:
            raise PrepublicationSealError(
                "main mutation requires immutable staging_revision from canary"
            )


def check_credential_identity(request: PublicationGateRequest) -> None:
    if not request.secret_redacted:
        raise CredentialMismatchError("secret_redacted must be true")
    if not request.credentials_environment_only:
        raise CredentialMismatchError("credentials must be environment-only")
    expected_scope = credentials_scope_for(request.dataset_repo_id)
    if request.credentials_scope is None:
        raise CredentialMismatchError(
            "credentials_scope is required and must match the dataset target"
        )
    if request.credentials_scope != expected_scope:
        raise CredentialMismatchError(
            f"credentials_scope {request.credentials_scope!r} does not match "
            f"target scope {expected_scope!r}"
        )
    if request.credential_identity is not None:
        identity = request.credential_identity.strip()
        if not identity:
            raise CredentialMismatchError("credential_identity must be non-empty")
        # Identity must name the same dataset target.
        if request.dataset_repo_id not in identity and expected_scope not in identity:
            raise CredentialMismatchError(
                "credential_identity does not match the authorized dataset target"
            )
    reject_credentials_in_payload(
        request.payload, label="gate_request.payload"
    )
    reject_credentials_in_payload(request.to_dict(), label="gate_request")


def check_evidence_cleanliness(request: PublicationGateRequest) -> None:
    if request.evidence_is_dirty:
        raise DirtyEvidenceError("evidence surface is dirty; refuse mutation")
    if request.fixture_only_evidence:
        raise DirtyEvidenceError(
            "fixture-only evidence is dirty for live mutation purposes"
        )


# ---------------------------------------------------------------------------
# Public evaluation API
# ---------------------------------------------------------------------------


def evaluate_publication_gate(
    request: PublicationGateRequest | Mapping[str, Any],
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> PublicationGateDecision:
    """Evaluate whether a staged/public mutation is authorized.

    Fail-closed: any missing gate produces ``authorized=False`` with explicit
    reason codes. Does not perform network I/O and never returns secrets.
    """

    _ = environ  # reserved for future secret-env binding; values never logged
    reasons: list[str] = []
    passed: list[str] = []
    details: dict[str, Any] = {
        "task_id": TASK_ID,
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "generated_work_guard": dict(GENERATED_WORK_GUARD),
    }

    try:
        req = (
            request
            if isinstance(request, PublicationGateRequest)
            else PublicationGateRequest.from_mapping(request)
        )
    except PublicationGateError as exc:
        raw_phase = "unknown"
        raw_op = "unknown"
        raw_repo = STATE_DATASET_REPO_ID
        raw_digest = "0" * 64
        raw_pin = STATE_PREVIOUS_PUBLIC_PIN
        if isinstance(request, Mapping):
            raw_phase = str(request.get("phase") or "unknown")
            raw_op = str(request.get("operation") or "unknown")
            raw_repo = str(request.get("dataset_repo_id") or STATE_DATASET_REPO_ID)
            try:
                raw_digest = normalize_sha256(
                    str(request.get("final_manifest_digest") or "0" * 64),
                    name="final_manifest_digest",
                )
            except PublicationGateError:
                raw_digest = "0" * 64
            try:
                raw_pin = require_immutable_revision(
                    str(request.get("previous_public_pin") or STATE_PREVIOUS_PUBLIC_PIN),
                    name="previous_public_pin",
                )
            except PublicationGateError:
                raw_pin = STATE_PREVIOUS_PUBLIC_PIN
        try:
            safe_repo = normalize_dataset_repo_id(raw_repo)
        except PublicationGateError:
            safe_repo = STATE_DATASET_REPO_ID
        return PublicationGateDecision(
            authorized=False,
            phase=raw_phase,
            operation=raw_op,
            dataset_repo_id=safe_repo,
            final_manifest_digest=raw_digest,
            previous_public_pin=raw_pin,
            reason_codes=(f"request.invalid:{exc.code}",),
            passed_gates=(),
            required_gates=REQUIRED_PUBLICATION_GATES,
            message=str(exc),
            details={"error": str(exc)},
            network_mutation_permitted=False,
        )

    gate_checks: tuple[tuple[str, Callable[[PublicationGateRequest], None]], ...] = (
        ("phase_target_operation", check_phase_target_operation),
        ("task_ancestor_closure", check_task_ancestor_closure),
        ("generated_work_guard", check_generated_work_guard),
        ("receipt_evidence", check_receipt_evidence),
        ("digest_status_binding", check_digest_status_binding),
        ("prepublication_seal", check_prepublication_seal),
        ("credential_identity", check_credential_identity),
        ("evidence_cleanliness", check_evidence_cleanliness),
    )

    for gate_name, checker in gate_checks:
        try:
            checker(req)
            passed.append(gate_name)
        except PublicationGateError as exc:
            reasons.append(f"gate.{gate_name}:{exc.code}")
            details[f"{gate_name}_error"] = str(exc)

    authorized = not reasons and set(passed) >= set(REQUIRED_PUBLICATION_GATES)
    if authorized:
        message = (
            f"publication gate authorized for {req.operation} on "
            f"{req.dataset_repo_id} (phase={req.phase}, "
            f"manifest={req.final_manifest_digest[:12]}…)"
        )
    else:
        message = (
            "publication gate refused before network mutation: "
            + "; ".join(reasons[:10])
        )

    details["passed_gate_count"] = len(passed)
    details["required_gate_count"] = len(REQUIRED_PUBLICATION_GATES)
    details["prepublication_seal_required"] = prepublication_seal_required(req.phase)
    details["required_task_ids"] = list(
        phase_requirements(req.phase)["required_task_ids"]
    )
    details["required_receipts"] = list(
        phase_requirements(req.phase)["required_receipts"]
    )
    details["staging_revision"] = req.staging_revision
    details["current_commit"] = req.current_commit

    decision = PublicationGateDecision(
        authorized=authorized,
        phase=req.phase,
        operation=req.operation,
        dataset_repo_id=req.dataset_repo_id,
        final_manifest_digest=req.final_manifest_digest,
        previous_public_pin=req.previous_public_pin,
        reason_codes=tuple(reasons),
        passed_gates=tuple(passed),
        required_gates=REQUIRED_PUBLICATION_GATES,
        message=message,
        details=details,
        network_mutation_permitted=authorized,
    )
    reject_credentials_in_payload(decision.to_dict(), label="publication_gate_decision")
    return decision


def require_publication_gate(
    request: PublicationGateRequest | Mapping[str, Any],
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> PublicationGateDecision:
    """Evaluate and raise :class:`PublicationGateDeniedError` when denied."""

    decision = evaluate_publication_gate(request, environ=environ)
    return decision.require_authorized()


def authorize_and_mutate(
    request: PublicationGateRequest | Mapping[str, Any],
    upload_callback: Callable[[PublicationGateDecision], T],
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> T:
    """Run *upload_callback* only after the gate authorizes the mutation.

    On every denial path the callback is never invoked and
    :class:`PublicationGateDeniedError` is raised. This is the preferred
    entrypoint for staging/main uploaders (LCR-040/042/064/065).
    """

    decision = require_publication_gate(request, environ=environ)
    if not decision.network_mutation_permitted:
        raise PublicationGateDeniedError(
            "network mutation not permitted",
            reason_codes=decision.reason_codes or ("network_mutation.denied",),
            decision=decision,
        )
    return upload_callback(decision)


# ---------------------------------------------------------------------------
# Fixture / example builders
# ---------------------------------------------------------------------------


def _stable_digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _completed_statuses_for_phase(
    phase: str,
    *,
    extra_completed: Optional[Iterable[str]] = None,
    dependencies: Optional[Mapping[str, Sequence[str]]] = None,
) -> dict[str, str]:
    contract = phase_requirements(phase)
    required = list(contract["required_task_ids"])
    deps = dict(dependencies or {})
    # Ensure every required task has a dependency map entry.
    for task_id in required:
        deps.setdefault(task_id, ())
    closure = collect_task_ancestor_closure(required, deps)
    statuses = {task_id: "completed" for task_id in closure}
    for task_id in extra_completed or ():
        statuses[str(task_id)] = "completed"
    return statuses


def _receipts_for_phase(
    phase: str,
    *,
    manifest_digest: str,
    fixture_only: bool = False,
    dirty: bool = False,
    status: str = "passed",
) -> dict[str, dict[str, Any]]:
    contract = phase_requirements(phase)
    receipts: dict[str, dict[str, Any]] = {}
    for path in contract["required_receipts"]:
        receipts[path] = {
            "path": path,
            "status": status,
            "content_digest": _stable_digest(f"{phase}:{path}:{manifest_digest}"),
            "final_manifest_digest": manifest_digest,
            "fixture_only": fixture_only,
            "dirty": dirty,
        }
    return receipts


def _expected_digests_from_receipts(
    receipts: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    expected: dict[str, str] = {}
    for path, receipt in receipts.items():
        digest = receipt.get("content_digest") or receipt.get("digest")
        if digest:
            expected[path] = str(digest)
    return expected


def example_authorized_request(
    phase: PublicationPhase | str,
    *,
    manifest_digest: Optional[str] = None,
    include_generated_completed: bool = True,
) -> dict[str, Any]:
    """Return a minimal mapping that passes the gate for *phase*."""

    phase_key = PublicationPhase.coerce(phase).value
    contract = phase_requirements(phase_key)
    digest = manifest_digest or _stable_digest(f"manifest:{phase_key}")
    staging_sha = _stable_digest(f"staging:{phase_key}")[:40]
    commit_sha = _stable_digest(f"commit:{phase_key}")[:40]

    # Minimal dependency map: required tasks depend on nothing extra.
    task_dependencies = {
        task_id: () for task_id in contract["required_task_ids"]
    }
    # Add a couple of sealed ancestors for realism.
    for task_id in contract["required_task_ids"]:
        task_dependencies[task_id] = ("LCR-008",)
    task_dependencies["LCR-008"] = ()

    task_statuses = _completed_statuses_for_phase(
        phase_key, dependencies=task_dependencies
    )
    if include_generated_completed:
        # A completed generated task must not block.
        task_statuses["LCR-080"] = "completed"

    task_goal_ids = {
        task_id: contract["generated_work_goal_roots"][0]
        for task_id in task_statuses
    }
    task_goal_ids["LCR-080"] = contract["generated_work_goal_roots"][-1]

    goal_parents = {
        root: ("LCR-G000",) for root in contract["generated_work_goal_roots"]
    }
    goal_parents["LCR-G000"] = ()

    receipts = _receipts_for_phase(phase_key, manifest_digest=digest)
    expected = _expected_digests_from_receipts(receipts)

    seal: Optional[dict[str, Any]] = None
    if contract["prepublication_seal_required"]:
        seal = {
            "present": True,
            "timing": "before_mutation",
            "final_manifest_digest": digest,
            "path": contract["seal_receipt_path"],
            "staging_revision": staging_sha,
        }

    payload: dict[str, Any] = {
        "phase": phase_key,
        "operation": contract["authorized_operation"],
        "dataset_repo_id": contract["dataset_repo_id"],
        "final_manifest_digest": digest,
        "previous_public_pin": contract["previous_public_pin"],
        "task_statuses": task_statuses,
        "task_dependencies": {
            k: list(v) for k, v in task_dependencies.items()
        },
        "task_goal_ids": task_goal_ids,
        "goal_parents": {k: list(v) for k, v in goal_parents.items()},
        "receipts": receipts,
        "expected_receipt_digests": expected,
        "credentials_environment_only": True,
        "credentials_scope": credentials_scope_for(contract["dataset_repo_id"]),
        "credential_identity": f"env:{contract['dataset_repo_id']}",
        "secret_redacted": True,
        "authorize_mutation": True,
        "evidence_is_dirty": False,
        "fixture_only_evidence": False,
        "current_commit": commit_sha,
        "payload": {
            "release_mode": "additive",
            "credentials_environment_only": True,
            "secret_redacted": True,
        },
        "argv": [
            "publish-legal-corpora",
            "--phase",
            phase_key,
            "--authorize-mutation",
        ],
    }
    if phase_key.endswith("_main"):
        payload["staging_revision"] = staging_sha
        payload["staging_branch"] = f"stage/{phase_key}"
        payload["prepublication_seal"] = seal
    elif phase_key.endswith("_staging"):
        payload["staging_branch"] = f"stage/{phase_key}"
        # Explicitly omit prepublication_seal — staging must not require it.
    return payload


def sealed_gate_fixture_payload(*, include_examples: bool = True) -> dict[str, Any]:
    """Return the canonical compact fixture recipe for LCR-074 tests.

    When *include_examples* is false, happy-path envelopes are omitted so the
    on-disk fixture stays a compact recipe; tests materialize examples via
    :func:`example_authorized_request`.
    """

    phases = {
        phase: dict(contract) for phase, contract in PHASE_REQUIREMENTS.items()
    }
    # Compact denial recipes: mutators applied to a base phase example.
    denial_cases = [
        {
            "id": "incomplete_required_task",
            "phase": "state_staging",
            "mutator": {"task_statuses.LCR-039": "todo"},
            "reason_fragment": "task_ancestor_closure",
        },
        {
            "id": "incomplete_ancestor",
            "phase": "state_staging",
            "mutator": {"task_statuses.LCR-008": "todo"},
            "reason_fragment": "task_ancestor_closure",
        },
        {
            "id": "nonterminal_generated_work",
            "phase": "state_main",
            "mutator": {
                "task_statuses.LCR-080": "todo",
                "task_goal_ids.LCR-080": "LCR-G080",
            },
            "reason_fragment": "generated_work_guard",
        },
        {
            "id": "unscoped_generated_lineage",
            "phase": "federal_staging",
            "mutator": {
                "task_statuses.LCR-099": "in_progress",
                "task_goal_ids.LCR-099": "LCR-G999",
                "goal_parents.LCR-G999": [],
            },
            "reason_fragment": "generated_work_guard",
        },
        {
            "id": "fixture_only_evidence",
            "phase": "state_staging",
            "mutator": {"fixture_only_evidence": True},
            "reason_fragment": "receipt_evidence",
        },
        {
            "id": "fixture_only_receipt",
            "phase": "federal_main",
            "mutator": {
                "receipts": {
                    "docs/reports/legal_corpora_reindex/federal_prepublication_seal.json": {
                        "fixture_only": True
                    }
                }
            },
            "reason_fragment": "receipt_evidence",
        },
        {
            "id": "digest_drift",
            "phase": "state_main",
            "mutator": {
                "expected_receipt_digests": {
                    "docs/reports/legal_corpora_reindex/staging_canary.json": (
                        "0" * 64
                    )
                }
            },
            "reason_fragment": "digest_status_binding",
        },
        {
            "id": "wrong_repo",
            "phase": "state_staging",
            "mutator": {"dataset_repo_id": "justicedao/ipfs_federal_register"},
            "reason_fragment": "phase_target_operation",
        },
        {
            "id": "wrong_operation_for_phase",
            "phase": "state_staging",
            "mutator": {"operation": "additive_main_upload"},
            "reason_fragment": "phase_target_operation",
        },
        {
            "id": "main_seal_absent",
            "phase": "state_main",
            "mutator": {
                "prepublication_seal": {"present": False, "timing": "absent"}
            },
            "reason_fragment": "prepublication_seal",
        },
        {
            "id": "main_seal_future",
            "phase": "federal_main",
            "mutator": {
                "prepublication_seal.timing": "future",
                "prepublication_seal.future": True,
            },
            "reason_fragment": "prepublication_seal",
        },
        {
            "id": "main_seal_post_hoc",
            "phase": "state_main",
            "mutator": {
                "prepublication_seal.timing": "post_hoc",
                "prepublication_seal.post_hoc": True,
                "prepublication_seal.created_after_mutation": True,
            },
            "reason_fragment": "prepublication_seal",
        },
        {
            "id": "staging_seal_substitution",
            "phase": "state_staging",
            "mutator": {
                "prepublication_seal": {
                    "present": True,
                    "timing": "before_mutation",
                    "substitutes_for_phase_evidence": True,
                    "required_for_staging": True,
                }
            },
            "reason_fragment": "receipt_evidence",
        },
        {
            "id": "forbidden_delete",
            "phase": "state_staging",
            "mutator": {"operation": "delete"},
            "reason_fragment": "request.invalid",
        },
        {
            "id": "forbidden_force_push",
            "phase": "federal_main",
            "mutator": {"operation": "force_push"},
            "reason_fragment": "request.invalid",
        },
        {
            "id": "forbidden_history_rewrite",
            "phase": "state_main",
            "mutator": {"operation": "history_rewrite"},
            "reason_fragment": "request.invalid",
        },
        {
            "id": "forbidden_visibility_change",
            "phase": "federal_staging",
            "mutator": {"operation": "visibility_change"},
            "reason_fragment": "request.invalid",
        },
        {
            "id": "dirty_evidence",
            "phase": "federal_staging",
            "mutator": {"evidence_is_dirty": True},
            "reason_fragment": "evidence_cleanliness",
        },
        {
            "id": "credential_mismatch",
            "phase": "state_staging",
            "mutator": {
                "credentials_scope": "dataset:write:justicedao/ipfs_federal_register"
            },
            "reason_fragment": "credential_identity",
        },
        {
            "id": "authorize_mutation_false",
            "phase": "state_staging",
            "mutator": {"authorize_mutation": False},
            "reason_fragment": "phase_target_operation",
        },
    ]

    payload: dict[str, Any] = {
        "schema": GATE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "fixture_id": "legal-corpora-publication-gate-v1",
        "notes": (
            "Compact recipe for the fail-closed staged/public mutation gate. "
            "Happy-path examples and denial mutators materialize full request "
            "envelopes at test time; bulk golden dumps are intentionally avoided. "
            "Staging does not require the post-canary main seal. Upload callbacks "
            "must never run on any denial path."
        ),
        "authorized_dataset_repo_ids": sorted(AUTHORIZED_DATASET_REPO_IDS),
        "baseline_revisions": dict(BASELINE_REVISIONS),
        "authorized_operations": sorted(AUTHORIZED_OPERATIONS),
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "generated_work_guard": dict(GENERATED_WORK_GUARD),
        "required_gates": list(REQUIRED_PUBLICATION_GATES),
        "phase_requirements": phases,
        "prepublication_seal_must_precede_main_mutation": True,
        "prepublication_seal_is_not_required_for_staging": True,
        "uploader_must_invoke_gate_before_first_network_mutation": True,
        "denial_cases": denial_cases,
        "example_builder": "example_authorized_request",
        "payload": {
            "credentials_environment_only": True,
            "secret_redacted": True,
            "mutation_requires_authorization": True,
        },
    }
    if include_examples:
        payload["examples"] = {
            phase: example_authorized_request(phase) for phase in PHASE_REQUIREMENTS
        }
    return payload


@lru_cache(maxsize=1)
def load_gate_fixture(
    path: Optional[PathLike] = None,
) -> Mapping[str, Any]:
    """Load and validate the sealed gate fixture."""

    fixture_path = Path(path) if path is not None else default_fixture_path()
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise PublicationGateError("gate fixture must be a JSON object")
    if raw.get("schema") != GATE_SCHEMA:
        raise PublicationGateError(
            f"gate fixture schema must be {GATE_SCHEMA!r}"
        )
    if raw.get("task_id") != TASK_ID:
        raise PublicationGateError(f"gate fixture task_id must be {TASK_ID!r}")
    reject_credentials_in_payload(raw, label="gate_fixture")
    return MappingProxyType(dict(raw))


def clear_gate_fixture_cache() -> None:
    load_gate_fixture.cache_clear()


def _deep_merge(dst: dict[str, Any], src: Mapping[str, Any]) -> dict[str, Any]:
    """Merge *src* into *dst* in place; nested mappings merge, leaves replace."""

    for key, value in src.items():
        key_text = str(key)
        if (
            key_text in dst
            and isinstance(dst[key_text], dict)
            and isinstance(value, Mapping)
        ):
            _deep_merge(dst[key_text], value)
        else:
            dst[key_text] = (
                json.loads(json.dumps(value))
                if isinstance(value, (Mapping, list))
                else value
            )
    return dst


def apply_denial_mutator(
    base: Mapping[str, Any],
    mutator: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply mutator entries onto a deep copy of *base*.

    Supports:
    * nested mapping merges (preferred for receipt paths with ``/`` and ``.``);
    * dotted paths for simple top-level fields (``task_statuses.LCR-039``).
    """

    result: dict[str, Any] = json.loads(json.dumps(base))
    for key, value in mutator.items():
        key_text = str(key)
        if isinstance(value, Mapping) and "." not in key_text:
            if key_text not in result or not isinstance(result[key_text], dict):
                result[key_text] = {}
            if isinstance(result[key_text], dict):
                _deep_merge(result[key_text], value)
            continue
        if isinstance(value, Mapping) and key_text in result and isinstance(
            result[key_text], dict
        ):
            _deep_merge(result[key_text], value)
            continue
        parts = key_text.split(".")
        cursor: Any = result
        for part in parts[:-1]:
            if part not in cursor or not isinstance(cursor[part], dict):
                cursor[part] = {}
            cursor = cursor[part]
        cursor[parts[-1]] = value
    return result


__all__ = [
    "AUTHORIZED_DATASET_REPO_IDS",
    "AUTHORIZED_OPERATIONS",
    "BASELINE_REVISIONS",
    "CREDENTIALS_SCOPE_PREFIX",
    "CredentialMismatchError",
    "DEFAULT_FIXTURE_RELATIVE_PATH",
    "DigestDriftError",
    "DirtyEvidenceError",
    "FEDERAL_DATASET_REPO_ID",
    "FEDERAL_PREVIOUS_PUBLIC_PIN",
    "FORBIDDEN_OPERATIONS",
    "GATE_SCHEMA",
    "GENERATED_WORK_GUARD",
    "GENERATED_WORK_TASK_NUMBER_FLOOR",
    "GOAL_ID",
    "GeneratedWorkGuardError",
    "OperationForbiddenError",
    "PHASE_REQUIREMENTS",
    "PROGRAM_ID",
    "PRODUCER",
    "PhaseContractError",
    "PrepublicationSealError",
    "PublicationGateDecision",
    "PublicationGateDeniedError",
    "PublicationGateError",
    "PublicationGateRequest",
    "PublicationOperation",
    "PublicationPhase",
    "REQUIRED_PUBLICATION_GATES",
    "ReceiptEvidenceError",
    "SCHEMA_VERSION",
    "SECRET_ENV_NAMES",
    "STATE_DATASET_REPO_ID",
    "STATE_PREVIOUS_PUBLIC_PIN",
    "StagingSealSubstitutionError",
    "TASK_ID",
    "TargetUnauthorizedError",
    "TaskAncestryError",
    "apply_denial_mutator",
    "authorize_and_mutate",
    "check_credential_identity",
    "check_digest_status_binding",
    "check_evidence_cleanliness",
    "check_generated_work_guard",
    "check_phase_target_operation",
    "check_prepublication_seal",
    "check_receipt_evidence",
    "check_task_ancestor_closure",
    "clear_gate_fixture_cache",
    "collect_task_ancestor_closure",
    "credentials_scope_for",
    "default_fixture_path",
    "default_release_policy_path",
    "digest_mapping",
    "evaluate_publication_gate",
    "example_authorized_request",
    "find_incomplete_tasks",
    "find_publication_blocking_generated_work",
    "goal_parent_lineage_intersects",
    "load_gate_fixture",
    "normalize_dataset_repo_id",
    "normalize_operation",
    "normalize_sha256",
    "phase_requirements",
    "prepublication_seal_required",
    "reject_credentials_in_payload",
    "repository_root",
    "require_immutable_revision",
    "require_publication_gate",
    "sealed_gate_fixture_payload",
    "task_number",
]
