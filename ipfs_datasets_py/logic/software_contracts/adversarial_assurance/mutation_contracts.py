"""Operator, target, candidate, policy, and campaign-plan mutation models (AAE-008).

Defines closed, versioned durable models for mutation operator declarations,
targets, candidates, campaign policies, and campaign plans.

Authority rules (normative):

* Canonical bytes / CIDv1 come only from ``software_contracts.content``.
* Records are recursively immutable, closed to unknown fields, and restricted
  to strict DAG-JSON types admitted by content identity (no floats, no host
  objects, no repr fallbacks).
* Stored CIDs are verified by decode-and-recompute, never trusted alone.
* Every operator declaration binds ID/version, supported languages/artifact
  types, target prerequisites, semantic intent, expected violated property
  classes, risk class, likely-equivalent conditions, syntactic transformation,
  scope limits, rollback, required sandbox, and maximum mutants per target.
* Candidates and plans bind deterministic seed/config identity; generation
  with identical source, target, operator, seed, and config must be
  byte-for-byte deterministic.
* Campaign budgets are hard-bounded (global, per-target, per-operator).
* Unknown enums / statuses fail closed.
* Private material, model-written authority, and host fallbacks are rejected.
* Operators that lack rollback or sandbox isolation are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
import re
import unicodedata
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceArtifactHeader,
    AssuranceBaseError,
    reject_private_model_authority_and_host_fallbacks,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

MUTATION_OPERATOR_DEFINITION_INTERFACE: Final[str] = "MutationOperatorDefinition@1"
MUTATION_OPERATOR_DEFINITION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-mutation-operator@1"
)
MUTATION_TARGET_INTERFACE: Final[str] = "MutationTarget@1"
MUTATION_TARGET_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-mutation-target@1"
)
MUTATION_CANDIDATE_INTERFACE: Final[str] = "MutationCandidate@1"
MUTATION_CANDIDATE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-mutation-candidate@1"
)
MUTATION_CAMPAIGN_POLICY_INTERFACE: Final[str] = "MutationCampaignPolicy@1"
MUTATION_CAMPAIGN_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-mutation-campaign-policy@1"
)
MUTATION_CAMPAIGN_PLAN_INTERFACE: Final[str] = "MutationCampaignPlan@1"
MUTATION_CAMPAIGN_PLAN_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-mutation-campaign-plan@1"
)
SEED_CONFIG_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-seed-config-binding@1"
)
ROLLBACK_DECLARATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-rollback-declaration@1"
)
SANDBOX_REQUIREMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-sandbox-requirement@1"
)
SCOPE_LIMITS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-scope-limits@1"
)
CAMPAIGN_BUDGET_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-campaign-budget@1"
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CID_LIST: Final[int] = 4_096
MAX_ID_LIST: Final[int] = 4_096
MAX_TOKEN_LIST: Final[int] = 256
MAX_PREREQUISITES: Final[int] = 64
MAX_PROPERTY_CLASSES: Final[int] = 64
MAX_LANGUAGES: Final[int] = 32
MAX_ARTIFACT_TYPES: Final[int] = 32
MAX_EQUIVALENCE_CONDITIONS: Final[int] = 64
MAX_SCOPE_ITEMS: Final[int] = 1_024
MAX_MUTANTS_PER_TARGET: Final[int] = 256
MAX_TOTAL_CANDIDATES: Final[int] = 4_096
MAX_TARGETS: Final[int] = 1_024
MAX_OPERATORS: Final[int] = 256
MAX_SEED: Final[int] = 2**63 - 1
MAX_EXECUTION_SECONDS: Final[int] = 7 * 24 * 3_600
MAX_WORKTREES: Final[int] = 256
MAX_PATH_CHARS: Final[int] = 1_024
MAX_RISK_WEIGHT_BP: Final[int] = 10_000
MAX_REVISION: Final[int] = 2**63 - 1

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_VERSION_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$"
)
_SYMBOL_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+@#$-]{0,511}$"
)
_REPOSITORY_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,255}$"
)
# Relative repo paths only — no absolute roots, no parent traversal.
_REPO_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:[A-Za-z0-9_./@+-][A-Za-z0-9_./@+-]{0,1022})$"
)


class MutationContractError(AssuranceBaseError):
    """Raised when a mutation contract record is malformed or unsafe."""


# ---------------------------------------------------------------------------
# Closed enumerations
# ---------------------------------------------------------------------------


class OperatorClass(str, Enum):
    """The eleven required deterministic mutation operator classes."""

    CONTROL_FLOW = "control_flow"
    DATA_SCHEMA = "data_schema"
    INTERFACE_CONTRACT = "interface_contract"
    SIDE_EFFECT = "side_effect"
    ERROR_RETRY = "error_retry"
    AUTHORIZATION_POLICY = "authorization_policy"
    STATE_DISTRIBUTED = "state_distributed"
    STORAGE_DURABILITY = "storage_durability"
    TEST_PROOF = "test_proof"
    SEMANTIC_COMPRESSION = "semantic_compression"
    GUI_ACTION_BINDING = "gui_action_binding"


class MutationRiskClass(str, Enum):
    """Closed risk classes used for target weighting and campaign admission."""

    CRITICAL_SECURITY = "critical_security"
    AUTHORIZATION = "authorization"
    DURABILITY = "durability"
    FINANCIAL_LEGAL = "financial_legal"
    DISTRIBUTED_TRANSITION = "distributed_transition"
    PROOF_RECEIPT_TRUST = "proof_receipt_trust"
    CRITICAL_INVARIANT = "critical_invariant"
    HIGH = "high"
    MEDIUM = "medium"
    LOCAL_BUG = "local_bug"
    LOW = "low"


class RollbackStrategy(str, Enum):
    """Closed strategies that restore pre-mutation state without production impact."""

    WORKTREE_DISCARD = "worktree_discard"
    REVERSE_PATCH = "reverse_patch"
    SNAPSHOT_RESTORE = "snapshot_restore"


class SandboxMode(str, Enum):
    """Closed isolation modes for mutant application and execution."""

    DISPOSABLE_WORKTREE = "disposable_worktree"
    NETWORK_DISABLED = "network_disabled"
    FAKES_ONLY = "fakes_only"
    FULL_ISOLATION = "full_isolation"


class PropertyClass(str, Enum):
    """Closed classes of properties a mutant is expected to violate."""

    CONTROL_INVARIANT = "control_invariant"
    DATA_INTEGRITY = "data_integrity"
    SCHEMA_CONTRACT = "schema_contract"
    INTERFACE_CONTRACT = "interface_contract"
    SIDE_EFFECT_OBLIGATION = "side_effect_obligation"
    ERROR_HANDLING = "error_handling"
    RETRY_BUDGET = "retry_budget"
    AUTHORIZATION = "authorization"
    POLICY_CONSTRAINT = "policy_constraint"
    STATE_TRANSITION = "state_transition"
    DURABILITY = "durability"
    STORAGE_INTEGRITY = "storage_integrity"
    TEST_ADEQUACY = "test_adequacy"
    PROOF_ADEQUACY = "proof_adequacy"
    RECEIPT_AUTHENTICITY = "receipt_authenticity"
    CAPSULE_COMPLETENESS = "capsule_completeness"
    GUI_ACTION_BINDING = "gui_action_binding"
    IDEMPOTENCY = "idempotency"
    COMPENSATION = "compensation"
    CANCELLATION = "cancellation"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise MutationContractError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise MutationContractError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise MutationContractError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise MutationContractError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise MutationContractError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise MutationContractError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _version(value: Any, name: str) -> str:
    text = _text(value, name)
    if _VERSION_RE.fullmatch(text) is None:
        raise MutationContractError(
            f"{name} must be a version token matching {_VERSION_RE.pattern}"
        )
    return text


def _symbol_id(value: Any, name: str) -> str:
    text = _text(value, name)
    if _SYMBOL_ID_RE.fullmatch(text) is None:
        raise MutationContractError(
            f"{name} must be a symbol identity matching {_SYMBOL_ID_RE.pattern}"
        )
    return text


def _repository_id(value: Any, name: str = "repository_id") -> str:
    text = _text(value, name)
    if _REPOSITORY_ID_RE.fullmatch(text) is None:
        raise MutationContractError(
            f"{name} must be a repository identity matching "
            f"{_REPOSITORY_ID_RE.pattern}"
        )
    return text


def _repo_path(value: Any, name: str) -> str:
    text = _text(value, name)
    if len(text) > MAX_PATH_CHARS:
        raise MutationContractError(f"{name} exceeds maximum path length")
    if text.startswith("/") or text.startswith("\\"):
        raise MutationContractError(f"{name} rejects absolute paths")
    if ".." in text.split("/"):
        raise MutationContractError(f"{name} rejects parent-directory traversal")
    if _REPO_PATH_RE.fullmatch(text) is None:
        raise MutationContractError(f"{name} must be a relative repository path")
    return text


def _optional_repo_path(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _repo_path(value, name)


def _nonneg_int(value: Any, name: str, *, maximum: int = MAX_REVISION) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise MutationContractError(f"{name} must be a nonnegative integer")
    if value > maximum:
        raise MutationContractError(f"{name} exceeds maximum")
    return value


def _pos_int(value: Any, name: str, *, maximum: int = MAX_REVISION) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1:
        raise MutationContractError(f"{name} must be a positive integer")
    if value > maximum:
        raise MutationContractError(f"{name} exceeds maximum")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise MutationContractError(f"{name} must be a boolean")
    return value


def _basis_points(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise MutationContractError(
            f"{name} must be an integer basis-point weight in "
            f"[0, {MAX_RISK_WEIGHT_BP}]"
        )
    if value < 0 or value > MAX_RISK_WEIGHT_BP:
        raise MutationContractError(
            f"{name} must be an integer basis-point weight in "
            f"[0, {MAX_RISK_WEIGHT_BP}]"
        )
    return value


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_structured(item) for item in value]
    return value


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise MutationContractError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise MutationContractError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise MutationContractError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    try:
        reject_private_model_authority_and_host_fallbacks(thawed, path=name)
    except AssuranceBaseError as exc:
        raise MutationContractError(str(exc)) from exc
    return thawed


def _mapping(value: Any, name: str, *, frozen: bool = True) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MutationContractError(f"{name} must be a mapping")
    result = _require_structured(dict(value), name)
    return _freeze_structured(result) if frozen else result


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise MutationContractError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise MutationContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise MutationContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_TOKEN_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise MutationContractError(f"{name} must be a list")
    ordered = tuple(sorted(_token(value, name) for value in values))
    if len(ordered) > maximum:
        raise MutationContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise MutationContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_symbol_ids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise MutationContractError(f"{name} must be a list")
    ordered = tuple(sorted(_symbol_id(value, name) for value in values))
    if len(ordered) > MAX_ID_LIST:
        raise MutationContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise MutationContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_paths(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise MutationContractError(f"{name} must be a list")
    ordered = tuple(sorted(_repo_path(value, name) for value in values))
    if len(ordered) > MAX_SCOPE_ITEMS:
        raise MutationContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise MutationContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_enums(
    values: Iterable[Any],
    enum_type: type[Enum],
    name: str,
    *,
    maximum: int = MAX_TOKEN_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise MutationContractError(f"{name} must be a list")
    ordered = tuple(sorted(_enum(value, enum_type, name) for value in values))
    if len(ordered) > maximum:
        raise MutationContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise MutationContractError(f"{name} must not contain duplicates")
    return ordered


def _header(value: Any, name: str = "header") -> AssuranceArtifactHeader:
    if isinstance(value, AssuranceArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return AssuranceArtifactHeader.from_dict(value)
        except AssuranceBaseError as exc:
            raise MutationContractError(str(exc)) from exc
    raise MutationContractError(f"{name} must be AssuranceArtifactHeader or mapping")


# ---------------------------------------------------------------------------
# Nested declarations: seed/config, rollback, sandbox, scope, budget
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SeedConfigBinding:
    """Deterministic seed and config identity for generation and planning.

    ``config_cid`` must equal the content identity of ``config``. Identical
    source state, target, operator, seed, and config must yield identical
    candidates.
    """

    seed: int
    config: Mapping[str, Any]
    config_cid: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "seed",
            "config",
            "config_cid",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "seed", _nonneg_int(self.seed, "seed", maximum=MAX_SEED)
        )
        config = _mapping(self.config, "config")
        object.__setattr__(self, "config", config)
        recomputed = cid_for_structured(_thaw_structured(config))
        if self.config_cid is None:
            object.__setattr__(self, "config_cid", recomputed)
        else:
            claimed = _cid(self.config_cid, "config_cid")
            if claimed != recomputed:
                raise MutationContractError(
                    "config_cid identity mismatch with recomputed config identity"
                )
            object.__setattr__(self, "config_cid", claimed)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SEED_CONFIG_BINDING_SCHEMA,
            "seed": self.seed,
            "config": _thaw_structured(self.config),
            "config_cid": self.config_cid,
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["binding_cid"] = self.binding_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SeedConfigBinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != SEED_CONFIG_BINDING_SCHEMA:
            raise MutationContractError(
                "unsupported SeedConfigBinding schema version"
            )
        result = cls(
            seed=payload["seed"],
            config=payload["config"],
            config_cid=payload["config_cid"],
        )
        if claimed != result.binding_cid:
            raise MutationContractError(
                "SeedConfigBinding binding_cid identity mismatch"
            )
        return result


def _normalize_seed_config(
    value: SeedConfigBinding | Mapping[str, Any],
    name: str = "seed_config",
) -> SeedConfigBinding:
    if isinstance(value, SeedConfigBinding):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "binding_cid" in value:
            return SeedConfigBinding.from_dict(value)
        return SeedConfigBinding(
            seed=value.get("seed", 0),
            config=value.get("config", {}),
            config_cid=value.get("config_cid"),
        )
    raise MutationContractError(f"{name} must be SeedConfigBinding or mapping")


@dataclass(frozen=True, slots=True)
class RollbackDeclaration:
    """Rollback contract: production is never a mutation target or residual."""

    strategy: RollbackStrategy | str
    requires_clean_worktree: bool
    preserves_production: bool

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "strategy",
            "requires_clean_worktree",
            "preserves_production",
            "rollback_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "strategy", _enum(self.strategy, RollbackStrategy, "strategy")
        )
        object.__setattr__(
            self,
            "requires_clean_worktree",
            _bool(self.requires_clean_worktree, "requires_clean_worktree"),
        )
        preserves = _bool(self.preserves_production, "preserves_production")
        if not preserves:
            raise MutationContractError(
                "rollback must preserve production; production worktrees/branches "
                "cannot be mutation targets"
            )
        object.__setattr__(self, "preserves_production", preserves)
        if not self.requires_clean_worktree:
            raise MutationContractError(
                "rollback requires_clean_worktree must be true"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ROLLBACK_DECLARATION_SCHEMA,
            "strategy": self.strategy,
            "requires_clean_worktree": self.requires_clean_worktree,
            "preserves_production": self.preserves_production,
        }

    @property
    def rollback_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["rollback_cid"] = self.rollback_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RollbackDeclaration":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("rollback_cid")
        if payload.pop("schema") != ROLLBACK_DECLARATION_SCHEMA:
            raise MutationContractError(
                "unsupported RollbackDeclaration schema version"
            )
        result = cls(
            strategy=payload["strategy"],
            requires_clean_worktree=payload["requires_clean_worktree"],
            preserves_production=payload["preserves_production"],
        )
        if claimed != result.rollback_cid:
            raise MutationContractError(
                "RollbackDeclaration rollback_cid identity mismatch"
            )
        return result


def _normalize_rollback(
    value: RollbackDeclaration | Mapping[str, Any],
    name: str = "rollback",
) -> RollbackDeclaration:
    if isinstance(value, RollbackDeclaration):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "rollback_cid" in value:
            return RollbackDeclaration.from_dict(value)
        return RollbackDeclaration(
            strategy=value.get("strategy", RollbackStrategy.WORKTREE_DISCARD),
            requires_clean_worktree=value.get("requires_clean_worktree", True),
            preserves_production=value.get("preserves_production", True),
        )
    raise MutationContractError(f"{name} must be RollbackDeclaration or mapping")


@dataclass(frozen=True, slots=True)
class SandboxRequirement:
    """Required isolation for applying and executing a mutant."""

    mode: SandboxMode | str
    network_disabled: bool
    production_credentials_forbidden: bool
    disposable_worktree_required: bool

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "mode",
            "network_disabled",
            "production_credentials_forbidden",
            "disposable_worktree_required",
            "sandbox_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _enum(self.mode, SandboxMode, "mode"))
        network = _bool(self.network_disabled, "network_disabled")
        if not network:
            raise MutationContractError(
                "required_sandbox.network_disabled must be true"
            )
        object.__setattr__(self, "network_disabled", network)
        no_creds = _bool(
            self.production_credentials_forbidden,
            "production_credentials_forbidden",
        )
        if not no_creds:
            raise MutationContractError(
                "required_sandbox.production_credentials_forbidden must be true"
            )
        object.__setattr__(self, "production_credentials_forbidden", no_creds)
        disposable = _bool(
            self.disposable_worktree_required, "disposable_worktree_required"
        )
        if not disposable:
            raise MutationContractError(
                "required_sandbox.disposable_worktree_required must be true"
            )
        object.__setattr__(self, "disposable_worktree_required", disposable)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SANDBOX_REQUIREMENT_SCHEMA,
            "mode": self.mode,
            "network_disabled": self.network_disabled,
            "production_credentials_forbidden": self.production_credentials_forbidden,
            "disposable_worktree_required": self.disposable_worktree_required,
        }

    @property
    def sandbox_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["sandbox_cid"] = self.sandbox_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SandboxRequirement":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("sandbox_cid")
        if payload.pop("schema") != SANDBOX_REQUIREMENT_SCHEMA:
            raise MutationContractError(
                "unsupported SandboxRequirement schema version"
            )
        result = cls(
            mode=payload["mode"],
            network_disabled=payload["network_disabled"],
            production_credentials_forbidden=payload[
                "production_credentials_forbidden"
            ],
            disposable_worktree_required=payload["disposable_worktree_required"],
        )
        if claimed != result.sandbox_cid:
            raise MutationContractError(
                "SandboxRequirement sandbox_cid identity mismatch"
            )
        return result


def _normalize_sandbox(
    value: SandboxRequirement | Mapping[str, Any],
    name: str = "required_sandbox",
) -> SandboxRequirement:
    if isinstance(value, SandboxRequirement):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "sandbox_cid" in value:
            return SandboxRequirement.from_dict(value)
        return SandboxRequirement(
            mode=value.get("mode", SandboxMode.DISPOSABLE_WORKTREE),
            network_disabled=value.get("network_disabled", True),
            production_credentials_forbidden=value.get(
                "production_credentials_forbidden", True
            ),
            disposable_worktree_required=value.get(
                "disposable_worktree_required", True
            ),
        )
    raise MutationContractError(f"{name} must be SandboxRequirement or mapping")


@dataclass(frozen=True, slots=True)
class ScopeLimits:
    """Hard scope bounds for one operator or candidate application."""

    max_files: int
    max_symbols: int
    max_span_lines: int
    allow_cross_module: bool
    allow_verifier_mutation: bool

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "max_files",
            "max_symbols",
            "max_span_lines",
            "allow_cross_module",
            "allow_verifier_mutation",
            "scope_limits_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_files",
            _pos_int(self.max_files, "max_files", maximum=MAX_SCOPE_ITEMS),
        )
        object.__setattr__(
            self,
            "max_symbols",
            _pos_int(self.max_symbols, "max_symbols", maximum=MAX_SCOPE_ITEMS),
        )
        object.__setattr__(
            self,
            "max_span_lines",
            _pos_int(self.max_span_lines, "max_span_lines", maximum=1_000_000),
        )
        object.__setattr__(
            self,
            "allow_cross_module",
            _bool(self.allow_cross_module, "allow_cross_module"),
        )
        allow_verifier = _bool(
            self.allow_verifier_mutation, "allow_verifier_mutation"
        )
        if allow_verifier:
            raise MutationContractError(
                "scope_limits.allow_verifier_mutation must be false; "
                "verifier/policy/key/oracle mutation requires separate fixtures"
            )
        object.__setattr__(self, "allow_verifier_mutation", allow_verifier)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SCOPE_LIMITS_SCHEMA,
            "max_files": self.max_files,
            "max_symbols": self.max_symbols,
            "max_span_lines": self.max_span_lines,
            "allow_cross_module": self.allow_cross_module,
            "allow_verifier_mutation": self.allow_verifier_mutation,
        }

    @property
    def scope_limits_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["scope_limits_cid"] = self.scope_limits_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScopeLimits":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("scope_limits_cid")
        if payload.pop("schema") != SCOPE_LIMITS_SCHEMA:
            raise MutationContractError("unsupported ScopeLimits schema version")
        result = cls(
            max_files=payload["max_files"],
            max_symbols=payload["max_symbols"],
            max_span_lines=payload["max_span_lines"],
            allow_cross_module=payload["allow_cross_module"],
            allow_verifier_mutation=payload["allow_verifier_mutation"],
        )
        if claimed != result.scope_limits_cid:
            raise MutationContractError(
                "ScopeLimits scope_limits_cid identity mismatch"
            )
        return result


def _normalize_scope_limits(
    value: ScopeLimits | Mapping[str, Any],
    name: str = "scope_limits",
) -> ScopeLimits:
    if isinstance(value, ScopeLimits):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "scope_limits_cid" in value:
            return ScopeLimits.from_dict(value)
        return ScopeLimits(
            max_files=value.get("max_files", 1),
            max_symbols=value.get("max_symbols", 1),
            max_span_lines=value.get("max_span_lines", 64),
            allow_cross_module=value.get("allow_cross_module", False),
            allow_verifier_mutation=value.get("allow_verifier_mutation", False),
        )
    raise MutationContractError(f"{name} must be ScopeLimits or mapping")


@dataclass(frozen=True, slots=True)
class CampaignBudget:
    """Hard campaign resource bounds (global, per-target, per-operator)."""

    max_total_candidates: int
    max_candidates_per_target: int
    max_candidates_per_operator: int
    max_targets: int
    max_operators: int
    max_execution_seconds: int
    max_worktrees: int

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "max_total_candidates",
            "max_candidates_per_target",
            "max_candidates_per_operator",
            "max_targets",
            "max_operators",
            "max_execution_seconds",
            "max_worktrees",
            "budget_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_total_candidates",
            _pos_int(
                self.max_total_candidates,
                "max_total_candidates",
                maximum=MAX_TOTAL_CANDIDATES,
            ),
        )
        object.__setattr__(
            self,
            "max_candidates_per_target",
            _pos_int(
                self.max_candidates_per_target,
                "max_candidates_per_target",
                maximum=MAX_MUTANTS_PER_TARGET,
            ),
        )
        object.__setattr__(
            self,
            "max_candidates_per_operator",
            _pos_int(
                self.max_candidates_per_operator,
                "max_candidates_per_operator",
                maximum=MAX_TOTAL_CANDIDATES,
            ),
        )
        object.__setattr__(
            self,
            "max_targets",
            _pos_int(self.max_targets, "max_targets", maximum=MAX_TARGETS),
        )
        object.__setattr__(
            self,
            "max_operators",
            _pos_int(self.max_operators, "max_operators", maximum=MAX_OPERATORS),
        )
        object.__setattr__(
            self,
            "max_execution_seconds",
            _pos_int(
                self.max_execution_seconds,
                "max_execution_seconds",
                maximum=MAX_EXECUTION_SECONDS,
            ),
        )
        object.__setattr__(
            self,
            "max_worktrees",
            _pos_int(self.max_worktrees, "max_worktrees", maximum=MAX_WORKTREES),
        )
        if self.max_candidates_per_target > self.max_total_candidates:
            raise MutationContractError(
                "max_candidates_per_target cannot exceed max_total_candidates"
            )
        if self.max_candidates_per_operator > self.max_total_candidates:
            raise MutationContractError(
                "max_candidates_per_operator cannot exceed max_total_candidates"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CAMPAIGN_BUDGET_SCHEMA,
            "max_total_candidates": self.max_total_candidates,
            "max_candidates_per_target": self.max_candidates_per_target,
            "max_candidates_per_operator": self.max_candidates_per_operator,
            "max_targets": self.max_targets,
            "max_operators": self.max_operators,
            "max_execution_seconds": self.max_execution_seconds,
            "max_worktrees": self.max_worktrees,
        }

    @property
    def budget_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["budget_cid"] = self.budget_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CampaignBudget":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("budget_cid")
        if payload.pop("schema") != CAMPAIGN_BUDGET_SCHEMA:
            raise MutationContractError("unsupported CampaignBudget schema version")
        result = cls(
            max_total_candidates=payload["max_total_candidates"],
            max_candidates_per_target=payload["max_candidates_per_target"],
            max_candidates_per_operator=payload["max_candidates_per_operator"],
            max_targets=payload["max_targets"],
            max_operators=payload["max_operators"],
            max_execution_seconds=payload["max_execution_seconds"],
            max_worktrees=payload["max_worktrees"],
        )
        if claimed != result.budget_cid:
            raise MutationContractError(
                "CampaignBudget budget_cid identity mismatch"
            )
        return result


def _normalize_budget(
    value: CampaignBudget | Mapping[str, Any],
    name: str = "budget",
) -> CampaignBudget:
    if isinstance(value, CampaignBudget):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "budget_cid" in value:
            return CampaignBudget.from_dict(value)
        return CampaignBudget(
            max_total_candidates=value.get("max_total_candidates", 64),
            max_candidates_per_target=value.get("max_candidates_per_target", 8),
            max_candidates_per_operator=value.get("max_candidates_per_operator", 16),
            max_targets=value.get("max_targets", 32),
            max_operators=value.get("max_operators", 16),
            max_execution_seconds=value.get("max_execution_seconds", 3_600),
            max_worktrees=value.get("max_worktrees", 8),
        )
    raise MutationContractError(f"{name} must be CampaignBudget or mapping")


# ---------------------------------------------------------------------------
# MutationOperatorDefinition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MutationOperatorDefinition:
    """Closed declaration for one deterministic, bounded mutation operator.

    Interface: ``MutationOperatorDefinition@1``

    Declares every field required by the plan: ID/version, supported language
    or artifact types, target prerequisites, semantic intent, expected violated
    property classes, risk class, likely-equivalent conditions, syntactic
    transformation, scope limits, rollback, required sandbox, and maximum
    mutants per target.
    """

    operator_id: str
    operator_version: str
    operator_class: OperatorClass | str
    supported_languages: Sequence[str]
    supported_artifact_types: Sequence[str]
    target_prerequisites: Sequence[str]
    semantic_intent: str
    expected_violated_property_classes: Sequence[PropertyClass | str]
    risk_class: MutationRiskClass | str
    likely_equivalent_conditions: Sequence[str]
    syntactic_transformation: str
    scope_limits: ScopeLimits
    rollback: RollbackDeclaration
    required_sandbox: SandboxRequirement
    max_mutants_per_target: int
    deterministic: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "operator_id",
            "operator_version",
            "operator_class",
            "supported_languages",
            "supported_artifact_types",
            "target_prerequisites",
            "semantic_intent",
            "expected_violated_property_classes",
            "risk_class",
            "likely_equivalent_conditions",
            "syntactic_transformation",
            "scope_limits",
            "rollback",
            "required_sandbox",
            "max_mutants_per_target",
            "deterministic",
            "notes",
            "metadata",
            "operator_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "operator_id", _token(self.operator_id, "operator_id"))
        object.__setattr__(
            self,
            "operator_version",
            _version(self.operator_version, "operator_version"),
        )
        object.__setattr__(
            self,
            "operator_class",
            _enum(self.operator_class, OperatorClass, "operator_class"),
        )
        languages = _unique_sorted_tokens(
            list(self.supported_languages),
            "supported_languages",
            maximum=MAX_LANGUAGES,
        )
        if not languages:
            raise MutationContractError("supported_languages must not be empty")
        object.__setattr__(self, "supported_languages", languages)
        artifact_types = _unique_sorted_tokens(
            list(self.supported_artifact_types),
            "supported_artifact_types",
            maximum=MAX_ARTIFACT_TYPES,
        )
        if not artifact_types:
            raise MutationContractError(
                "supported_artifact_types must not be empty"
            )
        object.__setattr__(self, "supported_artifact_types", artifact_types)
        object.__setattr__(
            self,
            "target_prerequisites",
            _unique_sorted_tokens(
                list(self.target_prerequisites),
                "target_prerequisites",
                maximum=MAX_PREREQUISITES,
            ),
        )
        object.__setattr__(
            self, "semantic_intent", _text(self.semantic_intent, "semantic_intent")
        )
        properties = _unique_sorted_enums(
            list(self.expected_violated_property_classes),
            PropertyClass,
            "expected_violated_property_classes",
            maximum=MAX_PROPERTY_CLASSES,
        )
        if not properties:
            raise MutationContractError(
                "expected_violated_property_classes must not be empty"
            )
        object.__setattr__(self, "expected_violated_property_classes", properties)
        object.__setattr__(
            self,
            "risk_class",
            _enum(self.risk_class, MutationRiskClass, "risk_class"),
        )
        object.__setattr__(
            self,
            "likely_equivalent_conditions",
            _unique_sorted_tokens(
                list(self.likely_equivalent_conditions),
                "likely_equivalent_conditions",
                maximum=MAX_EQUIVALENCE_CONDITIONS,
            ),
        )
        object.__setattr__(
            self,
            "syntactic_transformation",
            _text(self.syntactic_transformation, "syntactic_transformation"),
        )
        object.__setattr__(
            self, "scope_limits", _normalize_scope_limits(self.scope_limits)
        )
        object.__setattr__(self, "rollback", _normalize_rollback(self.rollback))
        object.__setattr__(
            self, "required_sandbox", _normalize_sandbox(self.required_sandbox)
        )
        object.__setattr__(
            self,
            "max_mutants_per_target",
            _pos_int(
                self.max_mutants_per_target,
                "max_mutants_per_target",
                maximum=MAX_MUTANTS_PER_TARGET,
            ),
        )
        deterministic = _bool(self.deterministic, "deterministic")
        if not deterministic:
            raise MutationContractError(
                "operator deterministic must be true; generation must be "
                "byte-for-byte deterministic given seed and config"
            )
        object.__setattr__(self, "deterministic", deterministic)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_OPERATOR_DEFINITION_SCHEMA,
            "interface_id": MUTATION_OPERATOR_DEFINITION_INTERFACE,
            "operator_id": self.operator_id,
            "operator_version": self.operator_version,
            "operator_class": self.operator_class,
            "supported_languages": list(self.supported_languages),
            "supported_artifact_types": list(self.supported_artifact_types),
            "target_prerequisites": list(self.target_prerequisites),
            "semantic_intent": self.semantic_intent,
            "expected_violated_property_classes": list(
                self.expected_violated_property_classes
            ),
            "risk_class": self.risk_class,
            "likely_equivalent_conditions": list(self.likely_equivalent_conditions),
            "syntactic_transformation": self.syntactic_transformation,
            "scope_limits": self.scope_limits.identity_payload(),
            "rollback": self.rollback.identity_payload(),
            "required_sandbox": self.required_sandbox.identity_payload(),
            "max_mutants_per_target": self.max_mutants_per_target,
            "deterministic": self.deterministic,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def operator_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_OPERATOR_DEFINITION_SCHEMA,
            "interface_id": MUTATION_OPERATOR_DEFINITION_INTERFACE,
            "operator_id": self.operator_id,
            "operator_version": self.operator_version,
            "operator_class": self.operator_class,
            "supported_languages": list(self.supported_languages),
            "supported_artifact_types": list(self.supported_artifact_types),
            "target_prerequisites": list(self.target_prerequisites),
            "semantic_intent": self.semantic_intent,
            "expected_violated_property_classes": list(
                self.expected_violated_property_classes
            ),
            "risk_class": self.risk_class,
            "likely_equivalent_conditions": list(self.likely_equivalent_conditions),
            "syntactic_transformation": self.syntactic_transformation,
            "scope_limits": self.scope_limits.to_dict(),
            "rollback": self.rollback.to_dict(),
            "required_sandbox": self.required_sandbox.to_dict(),
            "max_mutants_per_target": self.max_mutants_per_target,
            "deterministic": self.deterministic,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "operator_cid": self.operator_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MutationOperatorDefinition":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("operator_cid")
        if payload.pop("schema") != MUTATION_OPERATOR_DEFINITION_SCHEMA:
            raise MutationContractError(
                "unsupported MutationOperatorDefinition schema version"
            )
        if payload.pop("interface_id") != MUTATION_OPERATOR_DEFINITION_INTERFACE:
            raise MutationContractError(
                "unsupported MutationOperatorDefinition interface_id"
            )
        result = cls(
            operator_id=payload["operator_id"],
            operator_version=payload["operator_version"],
            operator_class=payload["operator_class"],
            supported_languages=payload["supported_languages"],
            supported_artifact_types=payload["supported_artifact_types"],
            target_prerequisites=payload["target_prerequisites"],
            semantic_intent=payload["semantic_intent"],
            expected_violated_property_classes=payload[
                "expected_violated_property_classes"
            ],
            risk_class=payload["risk_class"],
            likely_equivalent_conditions=payload["likely_equivalent_conditions"],
            syntactic_transformation=payload["syntactic_transformation"],
            scope_limits=payload["scope_limits"],
            rollback=payload["rollback"],
            required_sandbox=payload["required_sandbox"],
            max_mutants_per_target=payload["max_mutants_per_target"],
            deterministic=payload["deterministic"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.operator_cid:
            raise MutationContractError(
                "MutationOperatorDefinition operator_cid identity mismatch"
            )
        return result

    def supports_target(self, target: "MutationTarget") -> bool:
        """Return True when language, artifact type, and prerequisites match."""

        if target.language not in self.supported_languages:
            return False
        if target.artifact_type not in self.supported_artifact_types:
            return False
        required = set(self.target_prerequisites)
        available = set(target.prerequisites)
        return required.issubset(available)


# ---------------------------------------------------------------------------
# MutationTarget
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MutationTarget:
    """Risk-selected mutation subject with prerequisites and identity bindings."""

    target_id: str
    repository_id: str
    repository_state_cid: str
    symbol_ids: Sequence[str]
    artifact_cids: Sequence[str]
    language: str
    artifact_type: str
    prerequisites: Sequence[str]
    risk_class: MutationRiskClass | str
    risk_weight_bp: int
    capsule_cids: Sequence[str] = ()
    proof_unit_cids: Sequence[str] = ()
    source_path: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "target_id",
            "repository_id",
            "repository_state_cid",
            "symbol_ids",
            "artifact_cids",
            "language",
            "artifact_type",
            "prerequisites",
            "risk_class",
            "risk_weight_bp",
            "capsule_cids",
            "proof_unit_cids",
            "source_path",
            "notes",
            "metadata",
            "target_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_id", _token(self.target_id, "target_id"))
        object.__setattr__(
            self, "repository_id", _repository_id(self.repository_id, "repository_id")
        )
        object.__setattr__(
            self,
            "repository_state_cid",
            _cid(self.repository_state_cid, "repository_state_cid"),
        )
        symbols = _unique_sorted_symbol_ids(list(self.symbol_ids), "symbol_ids")
        artifacts = _unique_sorted_cids(list(self.artifact_cids), "artifact_cids")
        if not symbols and not artifacts:
            raise MutationContractError(
                "MutationTarget requires at least one symbol_id or artifact_cid"
            )
        object.__setattr__(self, "symbol_ids", symbols)
        object.__setattr__(self, "artifact_cids", artifacts)
        object.__setattr__(self, "language", _token(self.language, "language"))
        object.__setattr__(
            self, "artifact_type", _token(self.artifact_type, "artifact_type")
        )
        object.__setattr__(
            self,
            "prerequisites",
            _unique_sorted_tokens(
                list(self.prerequisites),
                "prerequisites",
                maximum=MAX_PREREQUISITES,
            ),
        )
        object.__setattr__(
            self,
            "risk_class",
            _enum(self.risk_class, MutationRiskClass, "risk_class"),
        )
        object.__setattr__(
            self, "risk_weight_bp", _basis_points(self.risk_weight_bp, "risk_weight_bp")
        )
        object.__setattr__(
            self,
            "capsule_cids",
            _unique_sorted_cids(list(self.capsule_cids), "capsule_cids"),
        )
        object.__setattr__(
            self,
            "proof_unit_cids",
            _unique_sorted_cids(list(self.proof_unit_cids), "proof_unit_cids"),
        )
        object.__setattr__(
            self, "source_path", _optional_repo_path(self.source_path, "source_path")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_TARGET_SCHEMA,
            "interface_id": MUTATION_TARGET_INTERFACE,
            "target_id": self.target_id,
            "repository_id": self.repository_id,
            "repository_state_cid": self.repository_state_cid,
            "symbol_ids": list(self.symbol_ids),
            "artifact_cids": list(self.artifact_cids),
            "language": self.language,
            "artifact_type": self.artifact_type,
            "prerequisites": list(self.prerequisites),
            "risk_class": self.risk_class,
            "risk_weight_bp": self.risk_weight_bp,
            "capsule_cids": list(self.capsule_cids),
            "proof_unit_cids": list(self.proof_unit_cids),
            "source_path": self.source_path,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def target_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_TARGET_SCHEMA,
            "interface_id": MUTATION_TARGET_INTERFACE,
            "target_id": self.target_id,
            "repository_id": self.repository_id,
            "repository_state_cid": self.repository_state_cid,
            "symbol_ids": list(self.symbol_ids),
            "artifact_cids": list(self.artifact_cids),
            "language": self.language,
            "artifact_type": self.artifact_type,
            "prerequisites": list(self.prerequisites),
            "risk_class": self.risk_class,
            "risk_weight_bp": self.risk_weight_bp,
            "capsule_cids": list(self.capsule_cids),
            "proof_unit_cids": list(self.proof_unit_cids),
            "source_path": self.source_path,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "target_cid": self.target_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MutationTarget":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("target_cid")
        if payload.pop("schema") != MUTATION_TARGET_SCHEMA:
            raise MutationContractError(
                "unsupported MutationTarget schema version"
            )
        if payload.pop("interface_id") != MUTATION_TARGET_INTERFACE:
            raise MutationContractError(
                "unsupported MutationTarget interface_id"
            )
        result = cls(
            target_id=payload["target_id"],
            repository_id=payload["repository_id"],
            repository_state_cid=payload["repository_state_cid"],
            symbol_ids=payload["symbol_ids"],
            artifact_cids=payload["artifact_cids"],
            language=payload["language"],
            artifact_type=payload["artifact_type"],
            prerequisites=payload["prerequisites"],
            risk_class=payload["risk_class"],
            risk_weight_bp=payload["risk_weight_bp"],
            capsule_cids=payload["capsule_cids"],
            proof_unit_cids=payload["proof_unit_cids"],
            source_path=payload["source_path"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.target_cid:
            raise MutationContractError(
                "MutationTarget target_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# MutationCandidate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MutationCandidate:
    """Immutable admitted mutant candidate with deterministic seed/config binding."""

    header: AssuranceArtifactHeader
    candidate_id: str
    operator_id: str
    operator_version: str
    operator_cid: str
    target_id: str
    target_cid: str
    seed_config: SeedConfigBinding
    source_root_cid: str
    repository_state_cid: str
    transformation_summary: str
    expected_violated_property_classes: Sequence[PropertyClass | str]
    risk_class: MutationRiskClass | str
    likely_equivalent: bool
    scope_symbol_ids: Sequence[str]
    scope_paths: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "candidate_id",
            "operator_id",
            "operator_version",
            "operator_cid",
            "target_id",
            "target_cid",
            "seed_config",
            "source_root_cid",
            "repository_state_cid",
            "transformation_summary",
            "expected_violated_property_classes",
            "risk_class",
            "likely_equivalent",
            "scope_symbol_ids",
            "scope_paths",
            "notes",
            "metadata",
            "candidate_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "mutation_candidate":
            raise MutationContractError(
                "header.artifact_kind must be mutation_candidate"
            )
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        object.__setattr__(self, "operator_id", _token(self.operator_id, "operator_id"))
        object.__setattr__(
            self,
            "operator_version",
            _version(self.operator_version, "operator_version"),
        )
        object.__setattr__(self, "operator_cid", _cid(self.operator_cid, "operator_cid"))
        object.__setattr__(self, "target_id", _token(self.target_id, "target_id"))
        object.__setattr__(self, "target_cid", _cid(self.target_cid, "target_cid"))
        object.__setattr__(
            self, "seed_config", _normalize_seed_config(self.seed_config)
        )
        object.__setattr__(
            self, "source_root_cid", _cid(self.source_root_cid, "source_root_cid")
        )
        object.__setattr__(
            self,
            "repository_state_cid",
            _cid(self.repository_state_cid, "repository_state_cid"),
        )
        if self.repository_state_cid != self.header.repository_state_cid:
            raise MutationContractError(
                "candidate repository_state_cid must match header.repository_state_cid"
            )
        object.__setattr__(
            self,
            "transformation_summary",
            _text(self.transformation_summary, "transformation_summary"),
        )
        properties = _unique_sorted_enums(
            list(self.expected_violated_property_classes),
            PropertyClass,
            "expected_violated_property_classes",
            maximum=MAX_PROPERTY_CLASSES,
        )
        if not properties:
            raise MutationContractError(
                "expected_violated_property_classes must not be empty"
            )
        object.__setattr__(self, "expected_violated_property_classes", properties)
        object.__setattr__(
            self,
            "risk_class",
            _enum(self.risk_class, MutationRiskClass, "risk_class"),
        )
        object.__setattr__(
            self, "likely_equivalent", _bool(self.likely_equivalent, "likely_equivalent")
        )
        symbols = _unique_sorted_symbol_ids(
            list(self.scope_symbol_ids), "scope_symbol_ids"
        )
        if not symbols:
            raise MutationContractError("scope_symbol_ids must not be empty")
        object.__setattr__(self, "scope_symbol_ids", symbols)
        object.__setattr__(
            self, "scope_paths", _unique_sorted_paths(list(self.scope_paths), "scope_paths")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_CANDIDATE_SCHEMA,
            "interface_id": MUTATION_CANDIDATE_INTERFACE,
            "header": self.header.identity_payload(),
            "candidate_id": self.candidate_id,
            "operator_id": self.operator_id,
            "operator_version": self.operator_version,
            "operator_cid": self.operator_cid,
            "target_id": self.target_id,
            "target_cid": self.target_cid,
            "seed_config": self.seed_config.identity_payload(),
            "source_root_cid": self.source_root_cid,
            "repository_state_cid": self.repository_state_cid,
            "transformation_summary": self.transformation_summary,
            "expected_violated_property_classes": list(
                self.expected_violated_property_classes
            ),
            "risk_class": self.risk_class,
            "likely_equivalent": self.likely_equivalent,
            "scope_symbol_ids": list(self.scope_symbol_ids),
            "scope_paths": list(self.scope_paths),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def candidate_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_CANDIDATE_SCHEMA,
            "interface_id": MUTATION_CANDIDATE_INTERFACE,
            "header": self.header.to_dict(),
            "candidate_id": self.candidate_id,
            "operator_id": self.operator_id,
            "operator_version": self.operator_version,
            "operator_cid": self.operator_cid,
            "target_id": self.target_id,
            "target_cid": self.target_cid,
            "seed_config": self.seed_config.to_dict(),
            "source_root_cid": self.source_root_cid,
            "repository_state_cid": self.repository_state_cid,
            "transformation_summary": self.transformation_summary,
            "expected_violated_property_classes": list(
                self.expected_violated_property_classes
            ),
            "risk_class": self.risk_class,
            "likely_equivalent": self.likely_equivalent,
            "scope_symbol_ids": list(self.scope_symbol_ids),
            "scope_paths": list(self.scope_paths),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "candidate_cid": self.candidate_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MutationCandidate":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("candidate_cid")
        if payload.pop("schema") != MUTATION_CANDIDATE_SCHEMA:
            raise MutationContractError(
                "unsupported MutationCandidate schema version"
            )
        if payload.pop("interface_id") != MUTATION_CANDIDATE_INTERFACE:
            raise MutationContractError(
                "unsupported MutationCandidate interface_id"
            )
        result = cls(
            header=payload["header"],
            candidate_id=payload["candidate_id"],
            operator_id=payload["operator_id"],
            operator_version=payload["operator_version"],
            operator_cid=payload["operator_cid"],
            target_id=payload["target_id"],
            target_cid=payload["target_cid"],
            seed_config=payload["seed_config"],
            source_root_cid=payload["source_root_cid"],
            repository_state_cid=payload["repository_state_cid"],
            transformation_summary=payload["transformation_summary"],
            expected_violated_property_classes=payload[
                "expected_violated_property_classes"
            ],
            risk_class=payload["risk_class"],
            likely_equivalent=payload["likely_equivalent"],
            scope_symbol_ids=payload["scope_symbol_ids"],
            scope_paths=payload["scope_paths"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.candidate_cid:
            raise MutationContractError(
                "MutationCandidate candidate_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# MutationCampaignPolicy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MutationCampaignPolicy:
    """Campaign policy: admitted classes, budgets, sandbox/rollback/seed rules."""

    header: AssuranceArtifactHeader
    policy_id: str
    policy_version: str
    admitted_operator_classes: Sequence[OperatorClass | str]
    admitted_risk_classes: Sequence[MutationRiskClass | str]
    budget: CampaignBudget
    seed_config: SeedConfigBinding
    require_disposable_worktree: bool = True
    require_network_disabled: bool = True
    require_rollback: bool = True
    require_deterministic_seed: bool = True
    full_suite_fallback_enabled: bool = True
    held_out_partition_required: bool = True
    operator_cids: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "policy_id",
            "policy_version",
            "admitted_operator_classes",
            "admitted_risk_classes",
            "budget",
            "seed_config",
            "require_disposable_worktree",
            "require_network_disabled",
            "require_rollback",
            "require_deterministic_seed",
            "full_suite_fallback_enabled",
            "held_out_partition_required",
            "operator_cids",
            "notes",
            "metadata",
            "policy_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "mutation_campaign_policy":
            raise MutationContractError(
                "header.artifact_kind must be mutation_campaign_policy"
            )
        object.__setattr__(self, "policy_id", _token(self.policy_id, "policy_id"))
        object.__setattr__(
            self, "policy_version", _version(self.policy_version, "policy_version")
        )
        classes = _unique_sorted_enums(
            list(self.admitted_operator_classes),
            OperatorClass,
            "admitted_operator_classes",
            maximum=len(OperatorClass),
        )
        if not classes:
            raise MutationContractError(
                "admitted_operator_classes must not be empty"
            )
        object.__setattr__(self, "admitted_operator_classes", classes)
        risks = _unique_sorted_enums(
            list(self.admitted_risk_classes),
            MutationRiskClass,
            "admitted_risk_classes",
            maximum=len(MutationRiskClass),
        )
        if not risks:
            raise MutationContractError("admitted_risk_classes must not be empty")
        object.__setattr__(self, "admitted_risk_classes", risks)
        object.__setattr__(self, "budget", _normalize_budget(self.budget))
        object.__setattr__(
            self, "seed_config", _normalize_seed_config(self.seed_config)
        )
        for flag_name in (
            "require_disposable_worktree",
            "require_network_disabled",
            "require_rollback",
            "require_deterministic_seed",
            "full_suite_fallback_enabled",
            "held_out_partition_required",
        ):
            flag = _bool(getattr(self, flag_name), flag_name)
            if not flag:
                raise MutationContractError(f"{flag_name} must be true")
            object.__setattr__(self, flag_name, flag)
        operators = _unique_sorted_cids(list(self.operator_cids), "operator_cids")
        if len(operators) > self.budget.max_operators:
            raise MutationContractError(
                "operator_cids exceeds campaign budget max_operators"
            )
        object.__setattr__(self, "operator_cids", operators)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_CAMPAIGN_POLICY_SCHEMA,
            "interface_id": MUTATION_CAMPAIGN_POLICY_INTERFACE,
            "header": self.header.identity_payload(),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "admitted_operator_classes": list(self.admitted_operator_classes),
            "admitted_risk_classes": list(self.admitted_risk_classes),
            "budget": self.budget.identity_payload(),
            "seed_config": self.seed_config.identity_payload(),
            "require_disposable_worktree": self.require_disposable_worktree,
            "require_network_disabled": self.require_network_disabled,
            "require_rollback": self.require_rollback,
            "require_deterministic_seed": self.require_deterministic_seed,
            "full_suite_fallback_enabled": self.full_suite_fallback_enabled,
            "held_out_partition_required": self.held_out_partition_required,
            "operator_cids": list(self.operator_cids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def policy_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_CAMPAIGN_POLICY_SCHEMA,
            "interface_id": MUTATION_CAMPAIGN_POLICY_INTERFACE,
            "header": self.header.to_dict(),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "admitted_operator_classes": list(self.admitted_operator_classes),
            "admitted_risk_classes": list(self.admitted_risk_classes),
            "budget": self.budget.to_dict(),
            "seed_config": self.seed_config.to_dict(),
            "require_disposable_worktree": self.require_disposable_worktree,
            "require_network_disabled": self.require_network_disabled,
            "require_rollback": self.require_rollback,
            "require_deterministic_seed": self.require_deterministic_seed,
            "full_suite_fallback_enabled": self.full_suite_fallback_enabled,
            "held_out_partition_required": self.held_out_partition_required,
            "operator_cids": list(self.operator_cids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "policy_cid": self.policy_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MutationCampaignPolicy":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("policy_cid")
        if payload.pop("schema") != MUTATION_CAMPAIGN_POLICY_SCHEMA:
            raise MutationContractError(
                "unsupported MutationCampaignPolicy schema version"
            )
        if payload.pop("interface_id") != MUTATION_CAMPAIGN_POLICY_INTERFACE:
            raise MutationContractError(
                "unsupported MutationCampaignPolicy interface_id"
            )
        result = cls(
            header=payload["header"],
            policy_id=payload["policy_id"],
            policy_version=payload["policy_version"],
            admitted_operator_classes=payload["admitted_operator_classes"],
            admitted_risk_classes=payload["admitted_risk_classes"],
            budget=payload["budget"],
            seed_config=payload["seed_config"],
            require_disposable_worktree=payload["require_disposable_worktree"],
            require_network_disabled=payload["require_network_disabled"],
            require_rollback=payload["require_rollback"],
            require_deterministic_seed=payload["require_deterministic_seed"],
            full_suite_fallback_enabled=payload["full_suite_fallback_enabled"],
            held_out_partition_required=payload["held_out_partition_required"],
            operator_cids=payload["operator_cids"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.policy_cid:
            raise MutationContractError(
                "MutationCampaignPolicy policy_cid identity mismatch"
            )
        return result

    def admits_operator(self, operator: MutationOperatorDefinition) -> bool:
        """Return True when the operator class and risk are policy-admitted."""

        return (
            operator.operator_class in self.admitted_operator_classes
            and operator.risk_class in self.admitted_risk_classes
            and operator.deterministic
            and operator.max_mutants_per_target
            <= self.budget.max_candidates_per_operator
        )

    def admits_target(self, target: MutationTarget) -> bool:
        """Return True when the target risk class is policy-admitted."""

        return target.risk_class in self.admitted_risk_classes


# ---------------------------------------------------------------------------
# MutationCampaignPlan
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MutationCampaignPlan:
    """Concrete campaign plan bound to policy, budget, seed/config, and targets."""

    header: AssuranceArtifactHeader
    plan_id: str
    policy_id: str
    policy_version: str
    policy_cid: str
    repository_id: str
    repository_state_cid: str
    baseline_receipt_cid: str
    seed_config: SeedConfigBinding
    budget: CampaignBudget
    target_cids: Sequence[str]
    operator_cids: Sequence[str]
    candidate_cids: Sequence[str]
    admitted_risk_classes: Sequence[MutationRiskClass | str]
    require_sandbox: bool = True
    require_rollback: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "plan_id",
            "policy_id",
            "policy_version",
            "policy_cid",
            "repository_id",
            "repository_state_cid",
            "baseline_receipt_cid",
            "seed_config",
            "budget",
            "target_cids",
            "operator_cids",
            "candidate_cids",
            "admitted_risk_classes",
            "require_sandbox",
            "require_rollback",
            "notes",
            "metadata",
            "plan_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "mutation_campaign_plan":
            raise MutationContractError(
                "header.artifact_kind must be mutation_campaign_plan"
            )
        object.__setattr__(self, "plan_id", _token(self.plan_id, "plan_id"))
        object.__setattr__(self, "policy_id", _token(self.policy_id, "policy_id"))
        object.__setattr__(
            self, "policy_version", _version(self.policy_version, "policy_version")
        )
        object.__setattr__(self, "policy_cid", _cid(self.policy_cid, "policy_cid"))
        object.__setattr__(
            self, "repository_id", _repository_id(self.repository_id, "repository_id")
        )
        if self.repository_id != self.header.repository_id:
            raise MutationContractError(
                "plan repository_id must match header.repository_id"
            )
        object.__setattr__(
            self,
            "repository_state_cid",
            _cid(self.repository_state_cid, "repository_state_cid"),
        )
        if self.repository_state_cid != self.header.repository_state_cid:
            raise MutationContractError(
                "plan repository_state_cid must match header.repository_state_cid"
            )
        object.__setattr__(
            self,
            "baseline_receipt_cid",
            _cid(self.baseline_receipt_cid, "baseline_receipt_cid"),
        )
        object.__setattr__(
            self, "seed_config", _normalize_seed_config(self.seed_config)
        )
        budget = _normalize_budget(self.budget)
        object.__setattr__(self, "budget", budget)
        targets = _unique_sorted_cids(list(self.target_cids), "target_cids")
        if not targets:
            raise MutationContractError("target_cids must not be empty")
        if len(targets) > budget.max_targets:
            raise MutationContractError(
                "target_cids exceeds campaign budget max_targets"
            )
        object.__setattr__(self, "target_cids", targets)
        operators = _unique_sorted_cids(list(self.operator_cids), "operator_cids")
        if not operators:
            raise MutationContractError("operator_cids must not be empty")
        if len(operators) > budget.max_operators:
            raise MutationContractError(
                "operator_cids exceeds campaign budget max_operators"
            )
        object.__setattr__(self, "operator_cids", operators)
        candidates = _unique_sorted_cids(list(self.candidate_cids), "candidate_cids")
        if len(candidates) > budget.max_total_candidates:
            raise MutationContractError(
                "candidate_cids exceeds campaign budget max_total_candidates"
            )
        object.__setattr__(self, "candidate_cids", candidates)
        risks = _unique_sorted_enums(
            list(self.admitted_risk_classes),
            MutationRiskClass,
            "admitted_risk_classes",
            maximum=len(MutationRiskClass),
        )
        if not risks:
            raise MutationContractError("admitted_risk_classes must not be empty")
        object.__setattr__(self, "admitted_risk_classes", risks)
        for flag_name in ("require_sandbox", "require_rollback"):
            flag = _bool(getattr(self, flag_name), flag_name)
            if not flag:
                raise MutationContractError(f"{flag_name} must be true")
            object.__setattr__(self, flag_name, flag)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_CAMPAIGN_PLAN_SCHEMA,
            "interface_id": MUTATION_CAMPAIGN_PLAN_INTERFACE,
            "header": self.header.identity_payload(),
            "plan_id": self.plan_id,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_cid": self.policy_cid,
            "repository_id": self.repository_id,
            "repository_state_cid": self.repository_state_cid,
            "baseline_receipt_cid": self.baseline_receipt_cid,
            "seed_config": self.seed_config.identity_payload(),
            "budget": self.budget.identity_payload(),
            "target_cids": list(self.target_cids),
            "operator_cids": list(self.operator_cids),
            "candidate_cids": list(self.candidate_cids),
            "admitted_risk_classes": list(self.admitted_risk_classes),
            "require_sandbox": self.require_sandbox,
            "require_rollback": self.require_rollback,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def plan_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_CAMPAIGN_PLAN_SCHEMA,
            "interface_id": MUTATION_CAMPAIGN_PLAN_INTERFACE,
            "header": self.header.to_dict(),
            "plan_id": self.plan_id,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_cid": self.policy_cid,
            "repository_id": self.repository_id,
            "repository_state_cid": self.repository_state_cid,
            "baseline_receipt_cid": self.baseline_receipt_cid,
            "seed_config": self.seed_config.to_dict(),
            "budget": self.budget.to_dict(),
            "target_cids": list(self.target_cids),
            "operator_cids": list(self.operator_cids),
            "candidate_cids": list(self.candidate_cids),
            "admitted_risk_classes": list(self.admitted_risk_classes),
            "require_sandbox": self.require_sandbox,
            "require_rollback": self.require_rollback,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "plan_cid": self.plan_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MutationCampaignPlan":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("plan_cid")
        if payload.pop("schema") != MUTATION_CAMPAIGN_PLAN_SCHEMA:
            raise MutationContractError(
                "unsupported MutationCampaignPlan schema version"
            )
        if payload.pop("interface_id") != MUTATION_CAMPAIGN_PLAN_INTERFACE:
            raise MutationContractError(
                "unsupported MutationCampaignPlan interface_id"
            )
        result = cls(
            header=payload["header"],
            plan_id=payload["plan_id"],
            policy_id=payload["policy_id"],
            policy_version=payload["policy_version"],
            policy_cid=payload["policy_cid"],
            repository_id=payload["repository_id"],
            repository_state_cid=payload["repository_state_cid"],
            baseline_receipt_cid=payload["baseline_receipt_cid"],
            seed_config=payload["seed_config"],
            budget=payload["budget"],
            target_cids=payload["target_cids"],
            operator_cids=payload["operator_cids"],
            candidate_cids=payload["candidate_cids"],
            admitted_risk_classes=payload["admitted_risk_classes"],
            require_sandbox=payload["require_sandbox"],
            require_rollback=payload["require_rollback"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.plan_cid:
            raise MutationContractError(
                "MutationCampaignPlan plan_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# Vocabulary / verification helpers
# ---------------------------------------------------------------------------


def operator_classes() -> tuple[str, ...]:
    """Return the closed operator-class vocabulary in declaration order."""

    return tuple(item.value for item in OperatorClass)


def mutation_risk_classes() -> tuple[str, ...]:
    """Return the closed mutation risk-class vocabulary in declaration order."""

    return tuple(item.value for item in MutationRiskClass)


def property_classes() -> tuple[str, ...]:
    """Return the closed property-class vocabulary in declaration order."""

    return tuple(item.value for item in PropertyClass)


def rollback_strategies() -> tuple[str, ...]:
    """Return the closed rollback-strategy vocabulary in declaration order."""

    return tuple(item.value for item in RollbackStrategy)


def sandbox_modes() -> tuple[str, ...]:
    """Return the closed sandbox-mode vocabulary in declaration order."""

    return tuple(item.value for item in SandboxMode)


def verify_operator_identity(
    operator: MutationOperatorDefinition | Mapping[str, Any],
) -> str:
    """Recompute and return the operator CID; raise on forged input."""

    if isinstance(operator, MutationOperatorDefinition):
        sealed = operator
    elif isinstance(operator, Mapping):
        sealed = MutationOperatorDefinition.from_dict(operator)
    else:
        raise MutationContractError(
            "operator must be MutationOperatorDefinition or mapping"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.operator_cid:
        raise MutationContractError(
            "operator_cid identity mismatch with recomputed identity"
        )
    return recomputed


def assert_operator_supports_target(
    operator: MutationOperatorDefinition,
    target: MutationTarget,
) -> None:
    """Fail closed when target language, type, or prerequisites are unsupported."""

    if not operator.supports_target(target):
        raise MutationContractError(
            "operator does not support target language, artifact type, or prerequisites"
        )


def assert_budget_admits_counts(
    budget: CampaignBudget,
    *,
    target_count: int,
    operator_count: int,
    candidate_count: int,
) -> None:
    """Fail closed when planned counts exceed the campaign budget."""

    if type(target_count) is not int or isinstance(target_count, bool) or target_count < 0:
        raise MutationContractError("target_count must be a nonnegative integer")
    if (
        type(operator_count) is not int
        or isinstance(operator_count, bool)
        or operator_count < 0
    ):
        raise MutationContractError("operator_count must be a nonnegative integer")
    if (
        type(candidate_count) is not int
        or isinstance(candidate_count, bool)
        or candidate_count < 0
    ):
        raise MutationContractError("candidate_count must be a nonnegative integer")
    if target_count > budget.max_targets:
        raise MutationContractError("target_count exceeds campaign budget max_targets")
    if operator_count > budget.max_operators:
        raise MutationContractError(
            "operator_count exceeds campaign budget max_operators"
        )
    if candidate_count > budget.max_total_candidates:
        raise MutationContractError(
            "candidate_count exceeds campaign budget max_total_candidates"
        )


__all__ = [
    "CAMPAIGN_BUDGET_SCHEMA",
    "MUTATION_CAMPAIGN_PLAN_INTERFACE",
    "MUTATION_CAMPAIGN_PLAN_SCHEMA",
    "MUTATION_CAMPAIGN_POLICY_INTERFACE",
    "MUTATION_CAMPAIGN_POLICY_SCHEMA",
    "MUTATION_CANDIDATE_INTERFACE",
    "MUTATION_CANDIDATE_SCHEMA",
    "MUTATION_OPERATOR_DEFINITION_INTERFACE",
    "MUTATION_OPERATOR_DEFINITION_SCHEMA",
    "MUTATION_TARGET_INTERFACE",
    "MUTATION_TARGET_SCHEMA",
    "ROLLBACK_DECLARATION_SCHEMA",
    "SANDBOX_REQUIREMENT_SCHEMA",
    "SCOPE_LIMITS_SCHEMA",
    "SEED_CONFIG_BINDING_SCHEMA",
    "CampaignBudget",
    "MAX_MUTANTS_PER_TARGET",
    "MAX_OPERATORS",
    "MAX_TARGETS",
    "MAX_TOTAL_CANDIDATES",
    "MutationCampaignPlan",
    "MutationCampaignPolicy",
    "MutationCandidate",
    "MutationContractError",
    "MutationOperatorDefinition",
    "MutationRiskClass",
    "MutationTarget",
    "OperatorClass",
    "PropertyClass",
    "RollbackDeclaration",
    "RollbackStrategy",
    "SandboxMode",
    "SandboxRequirement",
    "ScopeLimits",
    "SeedConfigBinding",
    "assert_budget_admits_counts",
    "assert_operator_supports_target",
    "mutation_risk_classes",
    "operator_classes",
    "property_classes",
    "rollback_strategies",
    "sandbox_modes",
    "verify_operator_identity",
]
