"""Immutable modality boundaries for reusable autoencoder infrastructure.

These contracts are declarations, never execution, qualification or admission.
The existing legal worker and its wire identities are deliberately unchanged.
An adapter is trusted local code registered for an exact contract; dataset
metadata never selects Python modules, providers, solvers or remote commands.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ...logic.families.models import EvidenceAuthority, EvidenceKind
from ...logic.families.namespaces import BASELINE_NAMESPACES, NamespaceKind
from ...logic.families.profile_catalog_v3 import DEFAULT_PROFILE_CATALOG_V3
from ...logic.families.profiles import COMPOSITION_REQUIRED_FAMILY_IDS, default_composition_map
from ...logic.families.registry import DEFAULT_REGISTRY
from ...logic.ir_core.identity import canonical_identity

SCHEMA = "autoencoder-modality-contract/v1"
MANIFEST_SCHEMA = "autoencoder-modality-variant/v1"
MAX_CONTRACT_BYTES = 32 * 1024
CAPABILITIES = frozenset({"prepare_targets", "validate_targets", "train", "evaluate",
                          "sparse_replay", "materialize_weights", "publish", "qualify"})
_TOKEN = re.compile(r"[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]*\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class ModalityContractError(ValueError):
    """Malformed modality identity, incompatible artifacts or missing runtime."""


def _require(value: Any, message: str) -> None:
    if not value:
        raise ModalityContractError(message)


def _text(value: Any, name: str) -> str:
    _require(type(value) is str and 0 < len(value) <= 512 and value.strip() == value
             and not any(ord(char) < 32 for char in value), name + " must be bounded text")
    return value


def _token(value: Any, name: str) -> str:
    _text(value, name)
    _require(_TOKEN.fullmatch(value), name + " must be a canonical identifier")
    return value


def _identifier(value: Any, name: str) -> str:
    """Retain native versioned IDs without treating them as import/file paths."""
    _text(value, name)
    _require(_IDENTIFIER.fullmatch(value) and ".." not in value
             and all(part not in {"", ".", ".."} for part in value.split("/")),
             name + " must be a bounded native identifier without path traversal")
    return value


def _sha(value: Any, name: str) -> str:
    _require(type(value) is str and _SHA.fullmatch(value), name + " must be lowercase SHA-256")
    return value


def _closed(value: Any, expected: set[str], name: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == expected, name + " fields differ")
    return dict(value)


def _tuple(value: Any, name: str, *, maximum: int = 64) -> tuple:
    _require(type(value) in (list, tuple) and len(value) <= maximum, name + " must be a bounded array")
    return tuple(value)


def _identity(value: Any, domain: str = "autoencoder.modality"):
    return canonical_identity(value, domain=domain, schema_version=SCHEMA)


@dataclass(frozen=True, slots=True)
class ImplementationIdentity:
    """Declared implementation/version and verified-source or contract digest.

    The caller establishes the digest's provenance. This data object does not
    attest that an installed callable was built from the supplied source.
    """
    identifier: str
    version: str
    sha256: str

    def __post_init__(self):
        _identifier(self.identifier, "implementation.identifier")
        _text(self.version, "implementation.version")
        _sha(self.sha256, "implementation.sha256")

    def to_dict(self):
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @classmethod
    def from_dict(cls, value):
        return cls(**_closed(value, {field.name for field in fields(cls)}, "implementation"))


@dataclass(frozen=True, slots=True)
class EmbeddingIdentity:
    """Exact local embedding production identity; dimension is insufficient."""
    model_id: str
    revision: str
    dimension: int
    provenance_sha256: str

    def __post_init__(self):
        _text(self.model_id, "embedding.model_id")
        _text(self.revision, "embedding.revision")
        _require(self.revision.lower() not in {"main", "master", "latest"}, "embedding revision must be immutable")
        _require(type(self.dimension) is int and 1 <= self.dimension <= 1_000_000,
                 "embedding dimension must be a positive bounded integer")
        _sha(self.provenance_sha256, "embedding.provenance_sha256")

    def to_dict(self):
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @classmethod
    def from_dict(cls, value):
        return cls(**_closed(value, {field.name for field in fields(cls)}, "embedding"))


@dataclass(frozen=True, slots=True)
class ProjectionSpec:
    """A named projection with typed taxonomy roles and explicit composition.

    Canonical catalog membership is vocabulary, not provider executability.
    ``composition_id`` is mandatory for tdfol/dcec; it does not make their
    components interchangeable with other projected families.
    """
    projection_id: str
    family_id: str
    target_schema: str
    profile_id: str | None = None
    property_ids: tuple[str, ...] = ()
    view_role: str = "normalized"
    required: bool = True
    composition_id: str | None = None
    native_profile_id: str | None = None
    native_view_role: str | None = None

    def __post_init__(self):
        _identifier(self.projection_id, "projection_id")
        _token(self.family_id, "family_id")
        _text(self.target_schema, "target_schema")
        _require(self.family_id in DEFAULT_REGISTRY.families, "unknown canonical family: " + self.family_id)
        _require(type(self.required) is bool, "projection.required must be boolean")
        for name in ("native_profile_id", "native_view_role"):
            if getattr(self, name) is not None:
                _identifier(getattr(self, name), name)
        properties = _tuple(self.property_ids, "property_ids")
        _require(all(type(value) is str for value in properties) and len(set(properties)) == len(properties),
                 "property_ids must be unique strings")
        object.__setattr__(self, "property_ids", tuple(sorted(properties)))
        self._catalog_binding()  # Validate roles, profile/family joins and composition immediately.

    def _catalog_binding(self):
        family = DEFAULT_REGISTRY.families[self.family_id]
        try:
            view = BASELINE_NAMESPACES.get(NamespaceKind.VIEW, self.view_role).to_dict()
            properties = [BASELINE_NAMESPACES.get(NamespaceKind.PROPERTY, value).to_dict()
                          for value in self.property_ids]
            composition = None
            if self.composition_id is not None:
                _token(self.composition_id, "composition_id")
                composition = default_composition_map().get(self.composition_id)
                _require(composition is not None and composition.composition_id == self.composition_id
                         and composition.family_id == self.family_id, "composition does not belong to projected family")
            _require(self.family_id not in COMPOSITION_REQUIRED_FAMILY_IDS or composition is not None,
                     "projected family requires explicit composition_id")
            profile = None
            if self.profile_id is not None:
                _token(self.profile_id, "profile_id")
                if self.profile_id in DEFAULT_PROFILE_CATALOG_V3:
                    entry = DEFAULT_PROFILE_CATALOG_V3.get(self.profile_id)
                    _require(entry.family_id == self.family_id, "profile belongs to another family")
                    profile = entry.to_dict()
                elif composition is not None and composition.profile.profile_id == self.profile_id:
                    profile = composition.profile.to_dict()
                else:
                    # Namespace-only profiles establish a name, not executable semantics.
                    profile = BASELINE_NAMESPACES.get(NamespaceKind.PROFILE, self.profile_id).to_dict()
                    # Explicitly bind the established baseline namespace relations.
                    families = {"hyperltl": {"hyperproperty"}, "s4": {"modal"}, "s5": {"modal"},
                                "secpal": {"authorization"}, "tla_plus": {"transition_system", "temporal"},
                                "qf_bv": {"first_order", "program"}, "temporal_first_order": {"temporal"}}
                    _require(self.family_id in families.get(self.profile_id, set()), "profile/family join is undeclared")
                    if self.profile_id == "temporal_first_order":
                        _require(composition is not None and set(composition.component_family_ids) == {"temporal", "first_order"},
                                 "temporal first-order profile requires its explicit composition")
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ModalityContractError):
                raise
            raise ModalityContractError("unknown or invalid projection taxonomy role") from exc
        return {"family_sha256": _identity(family.to_dict(), "autoencoder.modality.family").hexdigest,
                "profile_sha256": None if profile is None else _identity(profile).hexdigest,
                "property_sha256": [_identity(value).hexdigest for value in properties],
                "view_sha256": _identity(view).hexdigest,
                "composition": None if composition is None else composition.to_dict()}

    def to_dict(self):
        return {"projection_id": self.projection_id, "family_id": self.family_id,
                "target_schema": self.target_schema, "profile_id": self.profile_id,
                "property_ids": list(self.property_ids), "view_role": self.view_role,
                "required": self.required, "composition_id": self.composition_id,
                "native_profile_id": self.native_profile_id, "native_view_role": self.native_view_role,
                "catalog_binding": self._catalog_binding()}

    @classmethod
    def from_dict(cls, value):
        data = _closed(value, {field.name for field in fields(cls)} | {"catalog_binding"}, "projection")
        binding = data.pop("catalog_binding")
        result = cls(**data)
        _require(binding == result._catalog_binding(), "projection catalog binding changed")
        return result


@dataclass(frozen=True, slots=True)
class ValidatorRequirement:
    """Required evidence authority, not a statement that evidence exists."""
    validator_id: str
    authority: str
    evidence_kind: str
    projection_ids: tuple[str, ...] = ()
    required: bool = True

    def __post_init__(self):
        _identifier(self.validator_id, "validator_id")
        _require(type(self.authority) is str and self.authority in {item.value for item in EvidenceAuthority},
                 "unknown validator authority")
        _require(type(self.evidence_kind) is str and self.evidence_kind in {item.value for item in EvidenceKind},
                 "unknown validator evidence kind")
        _require(type(self.required) is bool, "validator.required must be boolean")
        projections = _tuple(self.projection_ids, "validator.projection_ids")
        for value in projections:
            _identifier(value, "validator.projection_id")
        _require(len(set(projections)) == len(projections), "duplicate validator projection")
        object.__setattr__(self, "projection_ids", tuple(sorted(projections)))

    def to_dict(self):
        return {"validator_id": self.validator_id, "authority": self.authority,
                "evidence_kind": self.evidence_kind, "projection_ids": list(self.projection_ids),
                "required": self.required}

    @classmethod
    def from_dict(cls, value):
        return cls(**_closed(value, {field.name for field in fields(cls)}, "validator"))


@dataclass(frozen=True, slots=True)
class ModalityContract:
    domain: str
    ir_schema: str
    source_language: str
    input_schema: str
    embedding: EmbeddingIdentity
    projections: tuple[ProjectionSpec, ...]
    target_codec: ImplementationIdentity
    state_codec: ImplementationIdentity
    optimizer: ImplementationIdentity
    objective_id: str
    objective_sha256: str
    validators: tuple[ValidatorRequirement, ...]
    adapter: ImplementationIdentity
    training_purpose: str = "feature_pretraining"

    def __post_init__(self):
        _token(self.domain, "domain")
        for name in ("ir_schema", "source_language", "input_schema", "objective_id"):
            _text(getattr(self, name), name)
        _sha(self.objective_sha256, "objective_sha256")
        _require(type(self.embedding) is EmbeddingIdentity, "typed embedding identity required")
        for name in ("target_codec", "state_codec", "optimizer", "adapter"):
            _require(type(getattr(self, name)) is ImplementationIdentity, "typed " + name + " identity required")
        _require(self.training_purpose == "feature_pretraining", "modality contracts currently support feature_pretraining only")
        projections = _tuple(self.projections, "projections")
        _require(projections and all(type(item) is ProjectionSpec for item in projections), "typed projections required")
        projection_ids = {item.projection_id for item in projections}
        _require(len(projection_ids) == len(projections), "duplicate projection id")
        _require(any(item.required for item in projections), "at least one required projection is necessary")
        validators = _tuple(self.validators, "validators")
        _require(validators and all(type(item) is ValidatorRequirement for item in validators), "typed validator requirements necessary")
        _require(len({item.validator_id for item in validators}) == len(validators), "duplicate validator id")
        for item in validators:
            _require(set(item.projection_ids) <= projection_ids, "validator refers to undeclared projection")
        _require(any(item.required for item in validators), "at least one required validator is necessary")
        object.__setattr__(self, "projections", tuple(sorted(projections, key=lambda item: item.projection_id)))
        object.__setattr__(self, "validators", tuple(sorted(validators, key=lambda item: item.validator_id)))
        _require(len(self.identity.canonical_bytes) <= MAX_CONTRACT_BYTES, "modality contract exceeds byte bound")

    def to_dict(self):
        return {"schema": SCHEMA, "domain": self.domain, "ir_schema": self.ir_schema,
                "source_language": self.source_language, "input_schema": self.input_schema,
                "embedding": self.embedding.to_dict(), "projections": [item.to_dict() for item in self.projections],
                "target_codec": self.target_codec.to_dict(), "state_codec": self.state_codec.to_dict(),
                "optimizer": self.optimizer.to_dict(), "objective_id": self.objective_id,
                "objective_sha256": self.objective_sha256,
                "validators": [item.to_dict() for item in self.validators], "adapter": self.adapter.to_dict(),
                "training_purpose": self.training_purpose}

    @classmethod
    def from_dict(cls, value):
        data = _closed(value, {field.name for field in fields(cls)} | {"schema"}, "modality contract")
        _require(data.pop("schema") == SCHEMA, "unsupported modality contract schema")
        data["embedding"] = EmbeddingIdentity.from_dict(data["embedding"])
        for name in ("target_codec", "state_codec", "optimizer", "adapter"):
            data[name] = ImplementationIdentity.from_dict(data[name])
        data["projections"] = tuple(ProjectionSpec.from_dict(item) for item in _tuple(data["projections"], "projections"))
        data["validators"] = tuple(ValidatorRequirement.from_dict(item) for item in _tuple(data["validators"], "validators"))
        return cls(**data)

    @property
    def identity(self):
        return _identity(self.to_dict())

    @property
    def sha256(self) -> str:
        return self.identity.hexdigest

    @property
    def digest(self) -> str:
        return self.sha256

    @property
    def variant_id(self) -> str:
        return "modality-" + self.sha256

    @property
    def publication_namespace(self) -> str:
        # A declaration for a future explicit transport. Existing legal HF v1
        # does not accept or silently adopt this namespace.
        return "autoencoders/" + self.domain + "/feature-pretraining/" + self.sha256

    def model_variant_metadata(self):
        """Existing registry field shape, not permission to use the legal worker."""
        return {"source_language": self.source_language, "target_formal_language": self.ir_schema,
                "jurisdiction": self.domain, "model_variant": self.variant_id}

    def registry_manifest(self):
        return {"schema": MANIFEST_SCHEMA, **self.model_variant_metadata(),
                "modality_contract": self.to_dict(), "modality_contract_sha256": self.sha256,
                "training_purpose": self.training_purpose, "publication_namespace": self.publication_namespace,
                "qualified": False, "admitted": False, "formalized": False,
                "promotion_performed": False}


def require_compatible_contracts(expected: ModalityContract, actual: ModalityContract) -> None:
    """Reject cross-domain/representation reuse even when vector shapes match."""
    _require(type(expected) is ModalityContract and type(actual) is ModalityContract, "typed modality contracts required")
    if expected.sha256 != actual.sha256:
        left, right = expected.to_dict(), actual.to_dict()
        differences = sorted(key for key in left if left[key] != right[key])
        raise ModalityContractError("incompatible modality contracts: " + ", ".join(differences))


@dataclass(frozen=True, slots=True)
class AdapterRegistration:
    contract_sha256: str
    implementation: ImplementationIdentity
    capabilities: tuple[str, ...]
    adapter: Any


class ModalityAdapterRegistry:
    """Explicit trusted-local capability dispatch; never imports metadata paths.

    Registration does not attest source provenance, qualify a model, or confer
    evidence authority. Those checks remain the worker and modality validators'
    responsibility. One adapter is registered per exact immutable contract.
    """
    def __init__(self):
        self._entries: dict[str, AdapterRegistration] = {}

    def register(self, contract: ModalityContract, adapter: Any, *, capabilities: Sequence[str]):
        _require(type(contract) is ModalityContract, "typed modality contract required")
        names = _tuple(capabilities, "capabilities")
        _require(names and all(type(name) is str and name in CAPABILITIES for name in names)
                 and len(set(names)) == len(names), "unknown or duplicate adapter capability")
        for name in names:
            _require(callable(getattr(adapter, name, None)), "adapter lacks callable capability: " + name)
        _require(contract.sha256 not in self._entries, "adapter contract is already registered")
        registration = AdapterRegistration(contract.sha256, contract.adapter, tuple(sorted(names)), adapter)
        self._entries[contract.sha256] = registration
        return registration

    def resolve(self, contract: ModalityContract, *, required_capabilities: Sequence[str] = ()):
        _require(type(contract) is ModalityContract, "typed modality contract required")
        names = _tuple(required_capabilities, "required_capabilities")
        _require(all(type(name) is str and name in CAPABILITIES for name in names)
                 and len(set(names)) == len(names), "unknown or duplicate required capability")
        registration = self._entries.get(contract.sha256)
        _require(registration is not None, "no local adapter registered for exact modality contract")
        _require(set(names) <= set(registration.capabilities), "registered adapter lacks required capabilities")
        return registration.adapter

    @property
    def registrations(self):
        return MappingProxyType(dict(self._entries))


__all__ = ["SCHEMA", "MANIFEST_SCHEMA", "CAPABILITIES", "ModalityContractError",
           "ImplementationIdentity", "EmbeddingIdentity", "ProjectionSpec", "ValidatorRequirement",
           "ModalityContract", "require_compatible_contracts", "AdapterRegistration", "ModalityAdapterRegistry"]
