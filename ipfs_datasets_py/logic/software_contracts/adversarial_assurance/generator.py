"""Deterministic bounded semantic mutation generation (AAE-022).

Interface surface:

* ``generate_mutation_candidates`` — produce ordered ``MutationCandidate@1``
  records from a sealed generation manifest and campaign policy.

Normative properties:

* Identical source root, targets, operators, seed, and policy yield
  byte-identical ordered candidates and candidate identities.
* Global, per-target, and per-operator campaign budgets are hard-enforced
  (generation truncates at bounds; oversize target/operator inputs fail closed).
* Only policy-admitted, deterministic, sandbox/rollback-safe operators that
  support a target may emit candidates.
* Generation is pure: no store I/O, no production worktree mutation, no
  production policy change.

Source rewrites are described as sealed candidate records (transformation
summary, scope, seed/config binding). Disposable apply/execute belongs to
later campaign tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import blake2b
from types import MappingProxyType
from typing import Any, ClassVar, Final, Mapping, Sequence
import re
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    ArtifactProvenance,
    AssuranceArtifactHeader,
    AssuranceBaseError,
    AssuranceTerminalStatus,
    AuthoritySource,
    ExecutionMode,
    GeneratorIdentity,
    VersionBinding,
    reject_private_model_authority_and_host_fallbacks,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.mutation_contracts import (
    MAX_MUTANTS_PER_TARGET,
    MAX_OPERATORS,
    MAX_TARGETS,
    MAX_TOTAL_CANDIDATES,
    CampaignBudget,
    MutationCampaignPolicy,
    MutationCandidate,
    MutationContractError,
    MutationOperatorDefinition,
    MutationTarget,
    SeedConfigBinding,
    assert_budget_admits_counts,
    assert_operator_supports_target,
    verify_operator_identity,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.base import (
    OperatorBaseError,
    OperatorBoundError,
    assert_operator_bounded,
    canonicalize_operator_declaration,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.registry import (
    MutationOperatorRegistry,
    OperatorRegistryError,
)

# ---------------------------------------------------------------------------
# Schema / interface constants
# ---------------------------------------------------------------------------

GENERATE_MUTATION_CANDIDATES_INTERFACE: Final[str] = "generate_mutation_candidates@1"
MUTATION_GENERATION_MANIFEST_INTERFACE: Final[str] = "MutationGenerationManifest@1"
MUTATION_GENERATION_MANIFEST_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-mutation-generation-manifest@1"
)
MUTATION_GENERATION_RESULT_INTERFACE: Final[str] = "MutationGenerationResult@1"
MUTATION_GENERATION_RESULT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-mutation-generation-result@1"
)

GENERATOR_ID: Final[str] = "mutation_campaign"
GENERATOR_VERSION: Final[str] = "1.0.0"
GENERATOR_PRODUCER_ID: Final[str] = "adversarial_assurance"
GENERATOR_PRODUCER_VERSION: Final[str] = "1"
GENERATOR_TOOL_ID: Final[str] = "generate_mutation_candidates.v1"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_PATH_CHARS: Final[int] = 1_024

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_VERSION_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$"
)
_REPOSITORY_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,255}$"
)
_SYMBOL_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+@#$-]{0,511}$"
)


class MutationGenerationError(AssuranceBaseError):
    """Raised when deterministic mutation generation fails closed."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise MutationGenerationError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise MutationGenerationError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise MutationGenerationError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise MutationGenerationError(f"{name} must be a valid CID") from exc


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise MutationGenerationError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _version(value: Any, name: str) -> str:
    text = _text(value, name)
    if _VERSION_RE.fullmatch(text) is None:
        raise MutationGenerationError(
            f"{name} must be a version token matching {_VERSION_RE.pattern}"
        )
    return text


def _repository_id(value: Any, name: str = "repository_id") -> str:
    text = _text(value, name)
    if _REPOSITORY_ID_RE.fullmatch(text) is None:
        raise MutationGenerationError(
            f"{name} must be a repository identity matching "
            f"{_REPOSITORY_ID_RE.pattern}"
        )
    return text


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise MutationGenerationError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str, *, maximum: int | None = None) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise MutationGenerationError(f"{name} must be a nonnegative integer")
    if maximum is not None and value > maximum:
        raise MutationGenerationError(f"{name} exceeds maximum bound")
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


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise MutationGenerationError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    try:
        reject_private_model_authority_and_host_fallbacks(thawed, path=name)
    except AssuranceBaseError as exc:
        raise MutationGenerationError(str(exc)) from exc
    return thawed


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise MutationGenerationError(f"{name} must be a mapping")
    return _freeze_structured(_require_structured(dict(value), name))


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise MutationGenerationError(f"{name} must be a mapping")
    unknown = set(data) - fields
    if unknown:
        raise MutationGenerationError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    return dict(data)


def _normalize_seed_config(
    value: SeedConfigBinding | Mapping[str, Any],
    name: str = "seed_config",
) -> SeedConfigBinding:
    if isinstance(value, SeedConfigBinding):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value or "binding_cid" in value:
                return SeedConfigBinding.from_dict(value)
            return SeedConfigBinding(
                seed=value.get("seed", 0),
                config=value.get("config", {}),
                config_cid=value.get("config_cid"),
            )
        except MutationContractError as exc:
            raise MutationGenerationError(str(exc)) from exc
    raise MutationGenerationError(f"{name} must be SeedConfigBinding or mapping")


def _normalize_policy(
    value: MutationCampaignPolicy | Mapping[str, Any],
    name: str = "mutation_policy",
) -> MutationCampaignPolicy:
    if isinstance(value, MutationCampaignPolicy):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value or "policy_cid" in value:
                return MutationCampaignPolicy.from_dict(value)
            return MutationCampaignPolicy(
                header=value["header"],
                policy_id=value["policy_id"],
                policy_version=value["policy_version"],
                admitted_operator_classes=value["admitted_operator_classes"],
                admitted_risk_classes=value["admitted_risk_classes"],
                budget=value["budget"],
                seed_config=value["seed_config"],
                require_disposable_worktree=value.get(
                    "require_disposable_worktree", True
                ),
                require_network_disabled=value.get("require_network_disabled", True),
                require_rollback=value.get("require_rollback", True),
                require_deterministic_seed=value.get(
                    "require_deterministic_seed", True
                ),
                full_suite_fallback_enabled=value.get(
                    "full_suite_fallback_enabled", True
                ),
                held_out_partition_required=value.get(
                    "held_out_partition_required", True
                ),
                operator_cids=value.get("operator_cids", ()),
                notes=value.get("notes"),
                metadata=value.get("metadata", {}),
            )
        except (MutationContractError, AssuranceBaseError, KeyError, TypeError) as exc:
            raise MutationGenerationError(
                f"{name} is not a sealed MutationCampaignPolicy: {exc}"
            ) from exc
    raise MutationGenerationError(f"{name} must be MutationCampaignPolicy or mapping")


def _normalize_target(
    value: MutationTarget | Mapping[str, Any],
    name: str = "target",
) -> MutationTarget:
    if isinstance(value, MutationTarget):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value or "target_cid" in value:
                return MutationTarget.from_dict(value)
            return MutationTarget(
                target_id=value["target_id"],
                repository_id=value["repository_id"],
                repository_state_cid=value["repository_state_cid"],
                symbol_ids=value.get("symbol_ids", ()),
                artifact_cids=value.get("artifact_cids", ()),
                language=value["language"],
                artifact_type=value["artifact_type"],
                prerequisites=value.get("prerequisites", ()),
                risk_class=value["risk_class"],
                risk_weight_bp=value["risk_weight_bp"],
                capsule_cids=value.get("capsule_cids", ()),
                proof_unit_cids=value.get("proof_unit_cids", ()),
                source_path=value.get("source_path"),
                notes=value.get("notes"),
                metadata=value.get("metadata", {}),
            )
        except (MutationContractError, KeyError, TypeError) as exc:
            raise MutationGenerationError(
                f"{name} is not a sealed MutationTarget: {exc}"
            ) from exc
    raise MutationGenerationError(f"{name} must be MutationTarget or mapping")


def _normalize_operator(
    value: MutationOperatorDefinition | Mapping[str, Any],
    name: str = "operator",
) -> MutationOperatorDefinition:
    if isinstance(value, MutationOperatorDefinition):
        try:
            sealed = canonicalize_operator_declaration(value)
            assert_operator_bounded(sealed)
            verify_operator_identity(sealed)
            return sealed
        except (
            MutationContractError,
            OperatorBaseError,
            OperatorBoundError,
            AssuranceBaseError,
        ) as exc:
            raise MutationGenerationError(
                f"{name} is not a sealed bounded operator: {exc}"
            ) from exc
    if isinstance(value, Mapping):
        try:
            if "schema" in value or "operator_cid" in value:
                sealed = MutationOperatorDefinition.from_dict(value)
            else:
                sealed = MutationOperatorDefinition(**value)  # type: ignore[arg-type]
                sealed = MutationOperatorDefinition.from_dict(sealed.to_dict())
            sealed = canonicalize_operator_declaration(sealed)
            assert_operator_bounded(sealed)
            verify_operator_identity(sealed)
            return sealed
        except (
            MutationContractError,
            OperatorBaseError,
            OperatorBoundError,
            AssuranceBaseError,
            TypeError,
            KeyError,
        ) as exc:
            raise MutationGenerationError(
                f"{name} is not a sealed bounded operator: {exc}"
            ) from exc
    raise MutationGenerationError(
        f"{name} must be MutationOperatorDefinition or mapping"
    )


def _normalize_operators(
    value: (
        Sequence[MutationOperatorDefinition | Mapping[str, Any]]
        | MutationOperatorRegistry
        | Mapping[str, Any]
    ),
    name: str = "operators",
) -> tuple[MutationOperatorDefinition, ...]:
    if isinstance(value, MutationOperatorRegistry):
        return tuple(value.list_operators())
    if isinstance(value, Mapping):
        # Registry dict or single operator declaration.
        if "operators" in value or value.get("interface_id") == (
            "MutationOperatorRegistry@1"
        ):
            try:
                registry = MutationOperatorRegistry.from_dict(value)
            except OperatorRegistryError as exc:
                raise MutationGenerationError(str(exc)) from exc
            return tuple(registry.list_operators())
        return (_normalize_operator(value, name),)
    if not isinstance(value, (list, tuple)):
        raise MutationGenerationError(f"{name} must be a sequence or registry")
    if len(value) > MAX_OPERATORS:
        raise MutationGenerationError(f"{name} exceeds MAX_OPERATORS")
    sealed = tuple(
        _normalize_operator(item, f"{name}[{index}]") for index, item in enumerate(value)
    )
    # Deterministic catalogue order (id, version, cid).
    return tuple(
        sorted(
            sealed,
            key=lambda item: (item.operator_id, item.operator_version, item.operator_cid),
        )
    )


# ---------------------------------------------------------------------------
# Manifest / result models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MutationGenerationManifest:
    """Sealed generation input: source root, targets, operators, and identity pins.

    Interface: ``MutationGenerationManifest@1``

    ``source_root_cid`` is the immutable source-tree root under which candidates
    are generated. Targets must share the same repository identity/state.
    """

    repository_id: str
    repository_state_cid: str
    source_root_cid: str
    targets: Sequence[MutationTarget | Mapping[str, Any]]
    operators: (
        Sequence[MutationOperatorDefinition | Mapping[str, Any]]
        | MutationOperatorRegistry
        | Mapping[str, Any]
    )
    environment_cid: str
    dependency_lock_cid: str
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "repository_id",
            "repository_state_cid",
            "source_root_cid",
            "targets",
            "operators",
            "environment_cid",
            "dependency_lock_cid",
            "notes",
            "metadata",
            "manifest_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "repository_id", _repository_id(self.repository_id, "repository_id")
        )
        object.__setattr__(
            self,
            "repository_state_cid",
            _cid(self.repository_state_cid, "repository_state_cid"),
        )
        object.__setattr__(
            self, "source_root_cid", _cid(self.source_root_cid, "source_root_cid")
        )
        object.__setattr__(
            self, "environment_cid", _cid(self.environment_cid, "environment_cid")
        )
        object.__setattr__(
            self,
            "dependency_lock_cid",
            _cid(self.dependency_lock_cid, "dependency_lock_cid"),
        )

        if not isinstance(self.targets, (list, tuple)):
            raise MutationGenerationError("targets must be a sequence")
        if not self.targets:
            raise MutationGenerationError("targets must not be empty")
        if len(self.targets) > MAX_TARGETS:
            raise MutationGenerationError("targets exceeds MAX_TARGETS")
        sealed_targets = tuple(
            _normalize_target(item, f"targets[{index}]")
            for index, item in enumerate(self.targets)
        )
        target_ids = [item.target_id for item in sealed_targets]
        if len(target_ids) != len(set(target_ids)):
            raise MutationGenerationError("targets target_id values must be unique")
        for target in sealed_targets:
            if target.repository_id != self.repository_id:
                raise MutationGenerationError(
                    "target repository_id must match manifest.repository_id"
                )
            if target.repository_state_cid != self.repository_state_cid:
                raise MutationGenerationError(
                    "target repository_state_cid must match "
                    "manifest.repository_state_cid"
                )
        # Risk-desc then stable id for deterministic campaign order.
        object.__setattr__(
            self,
            "targets",
            tuple(
                sorted(
                    sealed_targets,
                    key=lambda item: (-item.risk_weight_bp, item.target_id),
                )
            ),
        )

        sealed_operators = _normalize_operators(self.operators, "operators")
        if not sealed_operators:
            raise MutationGenerationError("operators must not be empty")
        operator_keys = {
            (item.operator_id, item.operator_version) for item in sealed_operators
        }
        if len(operator_keys) != len(sealed_operators):
            raise MutationGenerationError(
                "operators must be unique by (operator_id, operator_version)"
            )
        object.__setattr__(self, "operators", sealed_operators)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_GENERATION_MANIFEST_SCHEMA,
            "interface_id": MUTATION_GENERATION_MANIFEST_INTERFACE,
            "repository_id": self.repository_id,
            "repository_state_cid": self.repository_state_cid,
            "source_root_cid": self.source_root_cid,
            "targets": [item.identity_payload() for item in self.targets],
            "operators": [item.identity_payload() for item in self.operators],
            "environment_cid": self.environment_cid,
            "dependency_lock_cid": self.dependency_lock_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def manifest_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_GENERATION_MANIFEST_SCHEMA,
            "interface_id": MUTATION_GENERATION_MANIFEST_INTERFACE,
            "repository_id": self.repository_id,
            "repository_state_cid": self.repository_state_cid,
            "source_root_cid": self.source_root_cid,
            "targets": [item.to_dict() for item in self.targets],
            "operators": [item.to_dict() for item in self.operators],
            "environment_cid": self.environment_cid,
            "dependency_lock_cid": self.dependency_lock_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "manifest_cid": self.manifest_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MutationGenerationManifest":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("manifest_cid", None)
        schema = payload.pop("schema", MUTATION_GENERATION_MANIFEST_SCHEMA)
        if schema != MUTATION_GENERATION_MANIFEST_SCHEMA:
            raise MutationGenerationError(
                "unsupported MutationGenerationManifest schema version"
            )
        interface_id = payload.pop(
            "interface_id", MUTATION_GENERATION_MANIFEST_INTERFACE
        )
        if interface_id != MUTATION_GENERATION_MANIFEST_INTERFACE:
            raise MutationGenerationError(
                "unsupported MutationGenerationManifest interface_id"
            )
        result = cls(
            repository_id=payload["repository_id"],
            repository_state_cid=payload["repository_state_cid"],
            source_root_cid=payload["source_root_cid"],
            targets=payload["targets"],
            operators=payload["operators"],
            environment_cid=payload["environment_cid"],
            dependency_lock_cid=payload["dependency_lock_cid"],
            notes=payload.get("notes"),
            metadata=payload.get("metadata") or {},
        )
        if claimed is not None and claimed != result.manifest_cid:
            raise MutationGenerationError(
                "MutationGenerationManifest manifest_cid identity mismatch"
            )
        return result

    @classmethod
    def normalize(
        cls, value: "MutationGenerationManifest | Mapping[str, Any]"
    ) -> "MutationGenerationManifest":
        if isinstance(value, MutationGenerationManifest):
            return value
        if not isinstance(value, Mapping):
            raise MutationGenerationError(
                "manifest must be MutationGenerationManifest or mapping"
            )
        if "schema" in value or "manifest_cid" in value:
            return cls.from_dict(value)
        required = {
            "repository_id",
            "repository_state_cid",
            "source_root_cid",
            "targets",
            "operators",
            "environment_cid",
            "dependency_lock_cid",
        }
        missing = required - set(value)
        if missing:
            raise MutationGenerationError(
                "MutationGenerationManifest missing required fields: "
                f"{', '.join(sorted(missing))}"
            )
        allowed = required | {"notes", "metadata"}
        unknown = set(value) - allowed
        if unknown:
            raise MutationGenerationError(
                "MutationGenerationManifest contains unknown fields: "
                f"{', '.join(sorted(unknown))}"
            )
        return cls(
            repository_id=value["repository_id"],
            repository_state_cid=value["repository_state_cid"],
            source_root_cid=value["source_root_cid"],
            targets=value["targets"],
            operators=value["operators"],
            environment_cid=value["environment_cid"],
            dependency_lock_cid=value["dependency_lock_cid"],
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class MutationGenerationResult:
    """Ordered generation result with budget accounting.

    Interface: ``MutationGenerationResult@1``
    """

    candidates: Sequence[MutationCandidate]
    source_root_cid: str
    policy_cid: str
    seed_config: SeedConfigBinding
    budget: CampaignBudget
    target_count: int
    operator_count: int
    candidate_count: int
    candidates_per_target: Mapping[str, int]
    candidates_per_operator: Mapping[str, int]
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "candidates",
            "source_root_cid",
            "policy_cid",
            "seed_config",
            "budget",
            "target_count",
            "operator_count",
            "candidate_count",
            "candidates_per_target",
            "candidates_per_operator",
            "notes",
            "metadata",
            "result_cid",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.candidates, (list, tuple)):
            raise MutationGenerationError("candidates must be a sequence")
        sealed = tuple(self.candidates)
        for index, item in enumerate(sealed):
            if not isinstance(item, MutationCandidate):
                raise MutationGenerationError(
                    f"candidates[{index}] must be MutationCandidate"
                )
        object.__setattr__(self, "candidates", sealed)
        object.__setattr__(
            self, "source_root_cid", _cid(self.source_root_cid, "source_root_cid")
        )
        object.__setattr__(self, "policy_cid", _cid(self.policy_cid, "policy_cid"))
        object.__setattr__(
            self, "seed_config", _normalize_seed_config(self.seed_config)
        )
        if not isinstance(self.budget, CampaignBudget):
            raise MutationGenerationError("budget must be CampaignBudget")
        object.__setattr__(
            self,
            "target_count",
            _nonneg_int(self.target_count, "target_count", maximum=MAX_TARGETS),
        )
        object.__setattr__(
            self,
            "operator_count",
            _nonneg_int(self.operator_count, "operator_count", maximum=MAX_OPERATORS),
        )
        object.__setattr__(
            self,
            "candidate_count",
            _nonneg_int(
                self.candidate_count, "candidate_count", maximum=MAX_TOTAL_CANDIDATES
            ),
        )
        if self.candidate_count != len(sealed):
            raise MutationGenerationError(
                "candidate_count must equal len(candidates)"
            )
        per_target = {
            _token(key, "candidates_per_target key"): _nonneg_int(
                value, "candidates_per_target value", maximum=MAX_MUTANTS_PER_TARGET
            )
            for key, value in dict(self.candidates_per_target or {}).items()
        }
        per_operator = {
            _token(key, "candidates_per_operator key"): _nonneg_int(
                value, "candidates_per_operator value", maximum=MAX_TOTAL_CANDIDATES
            )
            for key, value in dict(self.candidates_per_operator or {}).items()
        }
        object.__setattr__(
            self, "candidates_per_target", MappingProxyType(dict(sorted(per_target.items())))
        )
        object.__setattr__(
            self,
            "candidates_per_operator",
            MappingProxyType(dict(sorted(per_operator.items()))),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

        # Hard budget enforcement on the sealed result.
        try:
            assert_budget_admits_counts(
                self.budget,
                target_count=self.target_count,
                operator_count=self.operator_count,
                candidate_count=self.candidate_count,
            )
        except MutationContractError as exc:
            raise MutationGenerationError(str(exc)) from exc
        for target_id, count in self.candidates_per_target.items():
            if count > self.budget.max_candidates_per_target:
                raise MutationGenerationError(
                    f"per-target budget exceeded for {target_id}"
                )
        for operator_id, count in self.candidates_per_operator.items():
            if count > self.budget.max_candidates_per_operator:
                raise MutationGenerationError(
                    f"per-operator budget exceeded for {operator_id}"
                )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_GENERATION_RESULT_SCHEMA,
            "interface_id": MUTATION_GENERATION_RESULT_INTERFACE,
            "candidates": [item.identity_payload() for item in self.candidates],
            "source_root_cid": self.source_root_cid,
            "policy_cid": self.policy_cid,
            "seed_config": self.seed_config.identity_payload(),
            "budget": self.budget.identity_payload(),
            "target_count": self.target_count,
            "operator_count": self.operator_count,
            "candidate_count": self.candidate_count,
            "candidates_per_target": dict(self.candidates_per_target),
            "candidates_per_operator": dict(self.candidates_per_operator),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def result_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_GENERATION_RESULT_SCHEMA,
            "interface_id": MUTATION_GENERATION_RESULT_INTERFACE,
            "candidates": [item.to_dict() for item in self.candidates],
            "source_root_cid": self.source_root_cid,
            "policy_cid": self.policy_cid,
            "seed_config": self.seed_config.to_dict(),
            "budget": self.budget.to_dict(),
            "target_count": self.target_count,
            "operator_count": self.operator_count,
            "candidate_count": self.candidate_count,
            "candidates_per_target": dict(self.candidates_per_target),
            "candidates_per_operator": dict(self.candidates_per_operator),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "result_cid": self.result_cid,
        }


# ---------------------------------------------------------------------------
# Deterministic variant planning
# ---------------------------------------------------------------------------


def _scope_symbols(target: MutationTarget) -> tuple[str, ...]:
    symbols = tuple(target.symbol_ids)
    if symbols:
        return symbols
    # Artifact-only targets still need a stable synthetic scope token.
    if target.artifact_cids:
        digest = blake2b(
            f"artifact_scope\0{target.target_id}\0{target.artifact_cids[0]}".encode(
                "utf-8"
            ),
            digest_size=8,
        ).hexdigest()
        return (f"artifact.{digest}",)
    raise MutationGenerationError(
        f"target {target.target_id} has no scope symbols or artifacts"
    )


def _scope_paths(target: MutationTarget) -> tuple[str, ...]:
    if target.source_path:
        return (target.source_path,)
    return ()


def _site_keys(
    target: MutationTarget,
    operator: MutationOperatorDefinition,
) -> tuple[str, ...]:
    """Return deterministic mutation site keys for (target, operator)."""

    symbols = _scope_symbols(target)
    max_sites = min(
        operator.max_mutants_per_target,
        operator.scope_limits.max_symbols,
        MAX_MUTANTS_PER_TARGET,
        max(1, len(symbols)),
    )
    # One site per leading symbol within operator scope, then pad with
    # operator-local synthetic sites when fewer symbols than max mutants.
    sites: list[str] = []
    for index, symbol in enumerate(symbols):
        if len(sites) >= max_sites:
            break
        sites.append(f"sym:{symbol}")
    while len(sites) < max_sites:
        sites.append(f"slot:{len(sites)}")
    return tuple(sites)


def _site_rank(
    seed: int,
    *,
    source_root_cid: str,
    target_id: str,
    operator_id: str,
    operator_version: str,
    site_key: str,
) -> tuple[int, str]:
    digest = blake2b(
        (
            f"mutation_site\0{seed}\0{source_root_cid}\0{target_id}\0"
            f"{operator_id}\0{operator_version}\0{site_key}"
        ).encode("utf-8"),
        digest_size=8,
    ).digest()
    return (int.from_bytes(digest, "big"), site_key)


def _select_sites(
    site_keys: Sequence[str],
    *,
    limit: int,
    seed: int,
    source_root_cid: str,
    target_id: str,
    operator_id: str,
    operator_version: str,
) -> tuple[str, ...]:
    if limit <= 0:
        return ()
    if limit >= len(site_keys):
        # Preserve declaration order when the full site set fits.
        return tuple(site_keys)
    ranked = sorted(
        site_keys,
        key=lambda key: _site_rank(
            seed,
            source_root_cid=source_root_cid,
            target_id=target_id,
            operator_id=operator_id,
            operator_version=operator_version,
            site_key=key,
        ),
    )
    return tuple(ranked[:limit])


def _stable_candidate_id(
    *,
    operator_id: str,
    target_id: str,
    variant_index: int,
    seed: int,
    source_root_cid: str,
    policy_cid: str,
    site_key: str,
) -> str:
    digest = blake2b(
        (
            f"cand\0{source_root_cid}\0{policy_cid}\0{target_id}\0"
            f"{operator_id}\0{seed}\0{variant_index}\0{site_key}"
        ).encode("utf-8"),
        digest_size=8,
    ).hexdigest()
    # Prefer a readable stable prefix; fall back to digest-only when long.
    readable = f"cand_{operator_id}_{target_id}_{variant_index}"
    # Token charset: lowercase alnum + _.:/+-
    sanitized = "".join(
        char if re.match(r"[a-z0-9_.:/+-]", char) else "_"
        for char in readable.lower()
    )
    if not sanitized or not sanitized[0].isalpha():
        sanitized = f"cand_{digest}"
    candidate = f"{sanitized}_{digest[:8]}"
    if len(candidate) > 128:
        candidate = f"cand_{digest}"
    if _TOKEN_RE.fullmatch(candidate) is None:
        candidate = f"cand_{digest}"
    return candidate


def _transformation_summary(
    operator: MutationOperatorDefinition,
    *,
    target: MutationTarget,
    site_key: str,
    variant_index: int,
) -> str:
    symbol = site_key.split(":", 1)[-1] if ":" in site_key else site_key
    path = target.source_path or "unknown_path"
    return (
        f"{operator.syntactic_transformation} at {symbol} "
        f"path={path} variant={variant_index}"
    )


def _candidate_header(
    *,
    manifest: MutationGenerationManifest,
    policy: MutationCampaignPolicy,
    operator: MutationOperatorDefinition,
    target: MutationTarget,
    seed_config: SeedConfigBinding,
) -> AssuranceArtifactHeader:
    generator = GeneratorIdentity(
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        interface_id=GENERATE_MUTATION_CANDIDATES_INTERFACE,
    )
    versions = VersionBinding(
        operator_id=operator.operator_id,
        operator_version=operator.operator_version,
        campaign_policy_id=policy.policy_id,
        campaign_policy_version=policy.policy_version,
        generator=generator,
    )
    input_cids = tuple(
        sorted(
            {
                manifest.source_root_cid,
                manifest.repository_state_cid,
                target.target_cid,
                operator.operator_cid,
                policy.policy_cid,
                seed_config.binding_cid,
            }
        )
    )
    provenance = ArtifactProvenance(
        producer_id=GENERATOR_PRODUCER_ID,
        producer_version=GENERATOR_PRODUCER_VERSION,
        execution_mode=ExecutionMode.LIVE,
        authority_source=AuthoritySource.DETERMINISTIC,
        input_cids=input_cids,
        tool_ids=(GENERATOR_TOOL_ID,),
        policy_cid=policy.policy_cid,
        notes="deterministic bounded semantic mutation generation",
    )
    symbols = _scope_symbols(target)
    # Drop synthetic artifact.* symbols from header target_symbol_ids when
    # the target itself had no real symbols.
    header_symbols = tuple(target.symbol_ids) if target.symbol_ids else ()
    return AssuranceArtifactHeader(
        artifact_kind="mutation_candidate",
        repository_id=manifest.repository_id,
        repository_state_cid=manifest.repository_state_cid,
        target_symbol_ids=header_symbols if header_symbols else symbols[:1],
        target_artifact_cids=tuple(target.artifact_cids),
        capsule_cids=tuple(target.capsule_cids),
        proof_unit_cids=tuple(target.proof_unit_cids),
        environment_cid=manifest.environment_cid,
        dependency_lock_cid=manifest.dependency_lock_cid,
        versions=versions,
        provenance=provenance,
        terminal_status=AssuranceTerminalStatus.COMPLETE,
        receipt_cids=(),
        proof_cids=(),
        metadata={
            "risk_class": target.risk_class,
            "operator_class": operator.operator_class,
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "source_root_cid": manifest.source_root_cid,
        },
    )


def _policy_admits_operator(
    policy: MutationCampaignPolicy,
    operator: MutationOperatorDefinition,
) -> bool:
    if not policy.admits_operator(operator):
        return False
    if policy.operator_cids and operator.operator_cid not in policy.operator_cids:
        return False
    if not operator.deterministic:
        return False
    if policy.require_rollback and not operator.rollback.preserves_production:
        return False
    if policy.require_network_disabled and not operator.required_sandbox.network_disabled:
        return False
    if (
        policy.require_disposable_worktree
        and not operator.required_sandbox.disposable_worktree_required
    ):
        return False
    return True


def _build_candidate(
    *,
    manifest: MutationGenerationManifest,
    policy: MutationCampaignPolicy,
    operator: MutationOperatorDefinition,
    target: MutationTarget,
    seed_config: SeedConfigBinding,
    site_key: str,
    variant_index: int,
) -> MutationCandidate:
    candidate_id = _stable_candidate_id(
        operator_id=operator.operator_id,
        target_id=target.target_id,
        variant_index=variant_index,
        seed=seed_config.seed,
        source_root_cid=manifest.source_root_cid,
        policy_cid=policy.policy_cid,
        site_key=site_key,
    )
    header = _candidate_header(
        manifest=manifest,
        policy=policy,
        operator=operator,
        target=target,
        seed_config=seed_config,
    )
    symbols = _scope_symbols(target)
    # Prefer the site symbol when it is a real target symbol.
    site_symbol = site_key.split(":", 1)[-1] if site_key.startswith("sym:") else None
    if site_symbol and site_symbol in symbols:
        scope_symbols = (site_symbol,)
    elif target.symbol_ids:
        scope_symbols = (target.symbol_ids[0],)
    else:
        scope_symbols = symbols[:1]

    metadata = {
        "variant_index": variant_index,
        "site_key": site_key,
        "operator_class": operator.operator_class,
        "semantic_intent": operator.semantic_intent,
        "syntactic_transformation": operator.syntactic_transformation,
        "manifest_cid": manifest.manifest_cid,
        "policy_cid": policy.policy_cid,
        "seed": seed_config.seed,
        "config_cid": seed_config.config_cid,
        "likely_equivalent_conditions": list(operator.likely_equivalent_conditions),
    }

    try:
        return MutationCandidate(
            header=header,
            candidate_id=candidate_id,
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            operator_cid=operator.operator_cid,
            target_id=target.target_id,
            target_cid=target.target_cid,
            seed_config=seed_config,
            source_root_cid=manifest.source_root_cid,
            repository_state_cid=manifest.repository_state_cid,
            transformation_summary=_transformation_summary(
                operator,
                target=target,
                site_key=site_key,
                variant_index=variant_index,
            ),
            expected_violated_property_classes=tuple(
                operator.expected_violated_property_classes
            ),
            risk_class=operator.risk_class
            if operator.risk_class
            else target.risk_class,
            likely_equivalent=False,
            scope_symbol_ids=scope_symbols,
            scope_paths=_scope_paths(target),
            notes=None,
            metadata=metadata,
        )
    except (MutationContractError, AssuranceBaseError) as exc:
        raise MutationGenerationError(
            f"failed to seal MutationCandidate: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def generate_mutation_candidates(
    manifest: MutationGenerationManifest | Mapping[str, Any],
    mutation_policy: MutationCampaignPolicy | Mapping[str, Any],
    *,
    seed_config: SeedConfigBinding | Mapping[str, Any] | None = None,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    return_result: bool = False,
) -> tuple[MutationCandidate, ...] | MutationGenerationResult:
    """Generate ordered, budget-bounded mutation candidates.

    Interface: ``generate_mutation_candidates@1``

    Given identical ``manifest.source_root_cid``, targets, operators, seed, and
    policy, returns byte-identical ordered candidates (including
    ``candidate_id`` / ``candidate_cid``).

    Budgets enforced (hard):

    * ``budget.max_targets`` / ``budget.max_operators`` on inputs
    * ``budget.max_total_candidates`` global cap
    * ``budget.max_candidates_per_target`` per target
    * ``budget.max_candidates_per_operator`` per operator
    * ``operator.max_mutants_per_target`` per operator-target pair

    Fail-closed when observation inputs are empty, repository identities
    disagree, no operator supports any admitted target, or budgets on
    target/operator counts are already exceeded by the input sets.
    """

    sealed_manifest = MutationGenerationManifest.normalize(manifest)
    sealed_policy = _normalize_policy(mutation_policy)

    if sealed_policy.header.repository_id != sealed_manifest.repository_id:
        raise MutationGenerationError(
            "mutation_policy repository_id must match manifest.repository_id"
        )
    if (
        sealed_policy.header.repository_state_cid
        != sealed_manifest.repository_state_cid
    ):
        raise MutationGenerationError(
            "mutation_policy repository_state_cid must match "
            "manifest.repository_state_cid"
        )

    if seed_config is None:
        active_seed = sealed_policy.seed_config
    else:
        active_seed = _normalize_seed_config(seed_config, "seed_config")
        if sealed_policy.require_deterministic_seed and active_seed.seed < 0:
            raise MutationGenerationError("seed must be nonnegative")

    budget = sealed_policy.budget
    targets = tuple(sealed_manifest.targets)
    operators = tuple(sealed_manifest.operators)

    if len(targets) > budget.max_targets:
        raise MutationGenerationError(
            "target count exceeds campaign budget max_targets"
        )
    if len(operators) > budget.max_operators:
        raise MutationGenerationError(
            "operator count exceeds campaign budget max_operators"
        )

    # Filter to policy-admitted targets and operators (stable order preserved).
    admitted_targets = tuple(
        target for target in targets if sealed_policy.admits_target(target)
    )
    if not admitted_targets:
        raise MutationGenerationError(
            "no targets admitted by mutation_policy.admitted_risk_classes"
        )

    admitted_operators = tuple(
        operator
        for operator in operators
        if _policy_admits_operator(sealed_policy, operator)
    )
    if not admitted_operators:
        raise MutationGenerationError(
            "no operators admitted by mutation_policy "
            "(class/risk/operator_cids/sandbox/rollback filters)"
        )

    candidates: list[MutationCandidate] = []
    per_target: dict[str, int] = {target.target_id: 0 for target in admitted_targets}
    per_operator: dict[str, int] = {
        operator.operator_id: 0 for operator in admitted_operators
    }
    used_operator_ids: set[str] = set()
    used_target_ids: set[str] = set()
    pair_counts: dict[tuple[str, str], int] = {}

    for target in admitted_targets:
        if len(candidates) >= budget.max_total_candidates:
            break
        target_remaining = budget.max_candidates_per_target - per_target[target.target_id]
        if target_remaining <= 0:
            continue

        for operator in admitted_operators:
            if len(candidates) >= budget.max_total_candidates:
                break
            target_remaining = (
                budget.max_candidates_per_target - per_target[target.target_id]
            )
            if target_remaining <= 0:
                break
            operator_remaining = (
                budget.max_candidates_per_operator - per_operator[operator.operator_id]
            )
            if operator_remaining <= 0:
                continue

            if not operator.supports_target(target):
                continue
            try:
                assert_operator_supports_target(operator, target)
            except MutationContractError:
                continue

            pair_key = (target.target_id, operator.operator_id)
            pair_used = pair_counts.get(pair_key, 0)
            pair_remaining = operator.max_mutants_per_target - pair_used
            if pair_remaining <= 0:
                continue

            global_remaining = budget.max_total_candidates - len(candidates)
            limit = min(
                target_remaining,
                operator_remaining,
                pair_remaining,
                global_remaining,
            )
            if limit <= 0:
                continue

            sites = _site_keys(target, operator)
            selected = _select_sites(
                sites,
                limit=limit,
                seed=active_seed.seed,
                source_root_cid=sealed_manifest.source_root_cid,
                target_id=target.target_id,
                operator_id=operator.operator_id,
                operator_version=operator.operator_version,
            )
            for variant_index, site_key in enumerate(selected):
                candidate = _build_candidate(
                    manifest=sealed_manifest,
                    policy=sealed_policy,
                    operator=operator,
                    target=target,
                    seed_config=active_seed,
                    site_key=site_key,
                    variant_index=variant_index,
                )
                candidates.append(candidate)
                per_target[target.target_id] += 1
                per_operator[operator.operator_id] += 1
                pair_counts[pair_key] = pair_counts.get(pair_key, 0) + 1
                used_target_ids.add(target.target_id)
                used_operator_ids.add(operator.operator_id)

    if not candidates:
        raise MutationGenerationError(
            "no mutation candidates generated: no admitted operator supports "
            "any admitted target under current budgets"
        )

    # Drop zero-count accounting entries for unused operators/targets in
    # per-* maps while preserving used counts for budget verification.
    per_target_used = {
        key: value for key, value in sorted(per_target.items()) if value > 0
    }
    per_operator_used = {
        key: value for key, value in sorted(per_operator.items()) if value > 0
    }

    # Final budget gate (global/target/operator counts).
    try:
        assert_budget_admits_counts(
            budget,
            target_count=len(used_target_ids),
            operator_count=len(used_operator_ids),
            candidate_count=len(candidates),
        )
    except MutationContractError as exc:
        raise MutationGenerationError(str(exc)) from exc
    for target_id, count in per_target_used.items():
        if count > budget.max_candidates_per_target:
            raise MutationGenerationError(
                f"per-target budget exceeded for {target_id}"
            )
    for operator_id, count in per_operator_used.items():
        if count > budget.max_candidates_per_operator:
            raise MutationGenerationError(
                f"per-operator budget exceeded for {operator_id}"
            )

    ordered = tuple(candidates)
    result_metadata: dict[str, Any] = {
        "interface_id": GENERATE_MUTATION_CANDIDATES_INTERFACE,
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "manifest_cid": sealed_manifest.manifest_cid,
        "policy_cid": sealed_policy.policy_cid,
        "source_root_cid": sealed_manifest.source_root_cid,
        "seed": active_seed.seed,
        "config_cid": active_seed.config_cid,
    }
    if metadata:
        result_metadata.update(_thaw_structured(_mapping(metadata, "metadata")))

    result = MutationGenerationResult(
        candidates=ordered,
        source_root_cid=sealed_manifest.source_root_cid,
        policy_cid=sealed_policy.policy_cid,
        seed_config=active_seed,
        budget=budget,
        target_count=len(used_target_ids),
        operator_count=len(used_operator_ids),
        candidate_count=len(ordered),
        candidates_per_target=per_target_used,
        candidates_per_operator=per_operator_used,
        notes=_optional_text(notes, "notes") if notes is not None else None,
        metadata=result_metadata,
    )
    return result if return_result else result.candidates


__all__ = [
    "GENERATE_MUTATION_CANDIDATES_INTERFACE",
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "MUTATION_GENERATION_MANIFEST_INTERFACE",
    "MUTATION_GENERATION_MANIFEST_SCHEMA",
    "MUTATION_GENERATION_RESULT_INTERFACE",
    "MUTATION_GENERATION_RESULT_SCHEMA",
    "MutationGenerationError",
    "MutationGenerationManifest",
    "MutationGenerationResult",
    "generate_mutation_candidates",
]
