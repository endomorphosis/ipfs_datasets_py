"""Complete ProofCacheKey@1 construction and identity (IPS-008).

Datasets semantic authority for the exact reuse key.  Every normative
statement, source, dependency, environment, lock, fixture, tool, circuit,
key, config, network, schema, canonicalization, selector, and policy field
is mandatory.  Non-applicable values use one typed absence; secrets and
wall-clock metadata are forbidden.

Rules:

* changing any required key field changes the content-addressed key CID;
* missing fields, duplicate sequence entries, non-canonical order, unknown
  closed enums, and secret/nondeterministic fields fail closed;
* transitively incomplete dependency roots fail closed (never narrow reuse);
* imports have no side effects (CID minting reuses identity helpers lazily).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from .evidence import (
    EvidenceClass,
    EvidenceClassError,
    ProofMode,
    ProofUnitKind,
    parse_proof_mode,
    parse_proof_unit_kind,
)
from .identity import (
    ABSENCE_TOKEN,
    CANONICALIZATION_VERSION,
    SECRET_AND_NONDETERMINISTIC_FIELDS,
    IdentityError,
    canonical_cid,
    validate_profile_cid,
)

CACHE_KEY_SUBSET: Final[str] = "ips/cache-key@1"
CACHE_KEY_VECTORS_SUBSET: Final[str] = "ips/cache-key-vectors@1"
CACHE_KEY_NAMESPACE: Final[str] = (
    "ipfs_datasets_py/logic/zkp/incremental_sealing/cache_key"
)
SCHEMA_MAJOR: Final[int] = 1
PROOF_CACHE_KEY_SCHEMA: Final[str] = f"{CACHE_KEY_NAMESPACE}@1"
PROOF_SCHEMA_VERSION: Final[str] = str(SCHEMA_MAJOR)
TYPED_ABSENCE: Final[str] = "typed_absence"
MAX_IDENTIFIER_BYTES: Final[int] = 512

# Normative fields from ProofCacheKey@1 plus source/schema bindings required by
# the conflict policy (target-file equality alone is never sufficient).
REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "statement_cid",
    "public_input_cid",
    "private_input_commitment",
    "source_root_cid",
    "source_artifact_cids",
    "source_closure_schema_version",
    "dependency_unit_roots",
    "dependency_roots_complete",
    "dependency_graph_schema_version",
    "environment_cid",
    "dependency_lock_cid",
    "fixture_cids",
    "tool_or_prover_id",
    "tool_or_prover_version",
    "proof_system_id",
    "evidence_class",
    "proof_unit_kind",
    "proof_mode",
    "circuit_id",
    "circuit_version",
    "proving_key_id",
    "verification_key_id",
    "configuration_cid",
    "network_policy_cid",
    "proof_schema_version",
    "canonicalization_version",
    "test_selector_cid",
    "policy_cid",
)

# Fields whose values must be profile CIDs or typed absence.
_CID_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "statement_cid",
        "public_input_cid",
        "private_input_commitment",
        "source_root_cid",
        "environment_cid",
        "dependency_lock_cid",
        "configuration_cid",
        "network_policy_cid",
        "test_selector_cid",
        "policy_cid",
    }
)

# Non-CID identifier fields (tool, circuit, key IDs, schema versions).
_TEXT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "tool_or_prover_id",
        "tool_or_prover_version",
        "proof_system_id",
        "circuit_id",
        "circuit_version",
        "proving_key_id",
        "verification_key_id",
        "source_closure_schema_version",
        "dependency_graph_schema_version",
        "proof_schema_version",
        "canonicalization_version",
    }
)

# Sequence fields that must be sorted unique CIDs (or typed absence).
_CID_SEQUENCE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "source_artifact_cids",
        "dependency_unit_roots",
        "fixture_cids",
    }
)


class CacheKeyError(ValueError):
    """ProofCacheKey@1 contract violation."""


def _is_absence(value: Any) -> bool:
    return value == ABSENCE_TOKEN


def _require_text(value: Any, field: str, *, allow_absence: bool = False) -> str:
    if allow_absence and _is_absence(value):
        return ABSENCE_TOKEN
    if not isinstance(value, str) or not value.strip():
        raise CacheKeyError(f"{field} must be a non-empty string or {ABSENCE_TOKEN}")
    text = value.strip()
    if text != value:
        raise CacheKeyError(f"{field} must not have surrounding whitespace")
    if len(text.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise CacheKeyError(f"{field} exceeds {MAX_IDENTIFIER_BYTES} bytes")
    return text


def _require_cid(value: Any, field: str, *, allow_absence: bool = False) -> str:
    if allow_absence and _is_absence(value):
        return ABSENCE_TOKEN
    text = _require_text(value, field, allow_absence=False)
    try:
        return validate_profile_cid(text, domain="any")
    except IdentityError as exc:
        raise CacheKeyError(f"{field}: {exc}") from exc


def _require_sorted_unique_cids(
    value: Any, field: str, *, allow_absence: bool = True
) -> tuple[str, ...]:
    if allow_absence and _is_absence(value):
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CacheKeyError(f"{field} must be a sequence or {ABSENCE_TOKEN}")
    items = tuple(
        _require_cid(item, field, allow_absence=False) for item in value
    )
    if list(items) != sorted(items):
        raise CacheKeyError(f"{field} must be canonically sorted")
    if len(set(items)) != len(items):
        raise CacheKeyError(f"{field} must not contain duplicates")
    return items


def _require_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise CacheKeyError(f"{field} must be a boolean")
    return value


def _parse_evidence_class(value: Any) -> EvidenceClass:
    if isinstance(value, EvidenceClass):
        return value
    if not isinstance(value, str):
        raise CacheKeyError("evidence_class must be a closed class name")
    try:
        return EvidenceClass(value)
    except ValueError as exc:
        raise CacheKeyError(f"unknown evidence_class {value!r}") from exc


def _reject_secret_fields(payload: Mapping[str, Any]) -> None:
    leaked = set(payload) & SECRET_AND_NONDETERMINISTIC_FIELDS
    if leaked:
        raise CacheKeyError(
            f"secret or nondeterministic fields are forbidden: {sorted(leaked)}"
        )


def _seq_canonical(values: tuple[str, ...]) -> list[str] | str:
    return list(values) if values else ABSENCE_TOKEN


@dataclass(frozen=True, slots=True)
class ProofCacheKey:
    """Immutable complete cache key for one proof-unit execution identity.

    Binds every input capable of changing reuse eligibility.  Incomplete
    dependency-root closures never admit reuse.
    """

    statement_cid: str
    public_input_cid: str
    private_input_commitment: str
    source_root_cid: str
    source_artifact_cids: tuple[str, ...]
    source_closure_schema_version: str
    dependency_unit_roots: tuple[str, ...]
    dependency_roots_complete: bool
    dependency_graph_schema_version: str
    environment_cid: str
    dependency_lock_cid: str
    fixture_cids: tuple[str, ...]
    tool_or_prover_id: str
    tool_or_prover_version: str
    proof_system_id: str
    evidence_class: EvidenceClass
    proof_unit_kind: ProofUnitKind
    proof_mode: ProofMode
    circuit_id: str
    circuit_version: str
    proving_key_id: str
    verification_key_id: str
    configuration_cid: str
    network_policy_cid: str
    proof_schema_version: str
    canonicalization_version: str
    test_selector_cid: str
    policy_cid: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "statement_cid",
            _require_cid(self.statement_cid, "statement_cid"),
        )
        object.__setattr__(
            self,
            "public_input_cid",
            _require_cid(self.public_input_cid, "public_input_cid"),
        )
        object.__setattr__(
            self,
            "private_input_commitment",
            _require_cid(
                self.private_input_commitment,
                "private_input_commitment",
                allow_absence=True,
            ),
        )
        object.__setattr__(
            self,
            "source_root_cid",
            _require_cid(self.source_root_cid, "source_root_cid"),
        )
        object.__setattr__(
            self,
            "source_artifact_cids",
            _require_sorted_unique_cids(
                self.source_artifact_cids, "source_artifact_cids"
            ),
        )
        object.__setattr__(
            self,
            "source_closure_schema_version",
            _require_text(
                self.source_closure_schema_version,
                "source_closure_schema_version",
            ),
        )
        object.__setattr__(
            self,
            "dependency_unit_roots",
            _require_sorted_unique_cids(
                self.dependency_unit_roots, "dependency_unit_roots"
            ),
        )
        object.__setattr__(
            self,
            "dependency_roots_complete",
            _require_bool(
                self.dependency_roots_complete, "dependency_roots_complete"
            ),
        )
        if not self.dependency_roots_complete:
            raise CacheKeyError(
                "transitively incomplete dependency roots fail closed"
            )
        object.__setattr__(
            self,
            "dependency_graph_schema_version",
            _require_text(
                self.dependency_graph_schema_version,
                "dependency_graph_schema_version",
            ),
        )
        object.__setattr__(
            self,
            "environment_cid",
            _require_cid(self.environment_cid, "environment_cid"),
        )
        object.__setattr__(
            self,
            "dependency_lock_cid",
            _require_cid(self.dependency_lock_cid, "dependency_lock_cid"),
        )
        object.__setattr__(
            self,
            "fixture_cids",
            _require_sorted_unique_cids(self.fixture_cids, "fixture_cids"),
        )
        object.__setattr__(
            self,
            "tool_or_prover_id",
            _require_text(self.tool_or_prover_id, "tool_or_prover_id"),
        )
        object.__setattr__(
            self,
            "tool_or_prover_version",
            _require_text(self.tool_or_prover_version, "tool_or_prover_version"),
        )
        object.__setattr__(
            self,
            "proof_system_id",
            _require_text(self.proof_system_id, "proof_system_id"),
        )
        try:
            evidence = _parse_evidence_class(self.evidence_class)
            kind = parse_proof_unit_kind(self.proof_unit_kind)
            mode = parse_proof_mode(self.proof_mode)
        except (CacheKeyError, EvidenceClassError) as exc:
            raise CacheKeyError(str(exc)) from exc
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "proof_unit_kind", kind)
        object.__setattr__(self, "proof_mode", mode)
        object.__setattr__(
            self,
            "circuit_id",
            _require_text(self.circuit_id, "circuit_id", allow_absence=True),
        )
        object.__setattr__(
            self,
            "circuit_version",
            _require_text(
                self.circuit_version, "circuit_version", allow_absence=True
            ),
        )
        object.__setattr__(
            self,
            "proving_key_id",
            _require_text(
                self.proving_key_id, "proving_key_id", allow_absence=True
            ),
        )
        object.__setattr__(
            self,
            "verification_key_id",
            _require_text(
                self.verification_key_id,
                "verification_key_id",
                allow_absence=False,
            ),
        )
        object.__setattr__(
            self,
            "configuration_cid",
            _require_cid(self.configuration_cid, "configuration_cid"),
        )
        object.__setattr__(
            self,
            "network_policy_cid",
            _require_cid(
                self.network_policy_cid,
                "network_policy_cid",
                allow_absence=True,
            ),
        )
        object.__setattr__(
            self,
            "proof_schema_version",
            _require_text(
                self.proof_schema_version,
                "proof_schema_version",
                allow_absence=False,
            ),
        )
        object.__setattr__(
            self,
            "canonicalization_version",
            _require_text(
                self.canonicalization_version, "canonicalization_version"
            ),
        )
        object.__setattr__(
            self,
            "test_selector_cid",
            _require_cid(
                self.test_selector_cid,
                "test_selector_cid",
                allow_absence=True,
            ),
        )
        object.__setattr__(
            self,
            "policy_cid",
            _require_cid(self.policy_cid, "policy_cid"),
        )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": PROOF_CACHE_KEY_SCHEMA,
            "cache_key_subset": CACHE_KEY_SUBSET,
            "statement_cid": self.statement_cid,
            "public_input_cid": self.public_input_cid,
            "private_input_commitment": self.private_input_commitment,
            "source_root_cid": self.source_root_cid,
            "source_artifact_cids": _seq_canonical(self.source_artifact_cids),
            "source_closure_schema_version": self.source_closure_schema_version,
            "dependency_unit_roots": _seq_canonical(self.dependency_unit_roots),
            "dependency_roots_complete": self.dependency_roots_complete,
            "dependency_graph_schema_version": self.dependency_graph_schema_version,
            "environment_cid": self.environment_cid,
            "dependency_lock_cid": self.dependency_lock_cid,
            "fixture_cids": _seq_canonical(self.fixture_cids),
            "tool_or_prover_id": self.tool_or_prover_id,
            "tool_or_prover_version": self.tool_or_prover_version,
            "proof_system_id": self.proof_system_id,
            "evidence_class": self.evidence_class.value,
            "proof_unit_kind": self.proof_unit_kind.value,
            "proof_mode": self.proof_mode.value,
            "circuit_id": self.circuit_id,
            "circuit_version": self.circuit_version,
            "proving_key_id": self.proving_key_id,
            "verification_key_id": self.verification_key_id,
            "configuration_cid": self.configuration_cid,
            "network_policy_cid": self.network_policy_cid,
            "proof_schema_version": self.proof_schema_version,
            "canonicalization_version": self.canonicalization_version,
            "test_selector_cid": self.test_selector_cid,
            "policy_cid": self.policy_cid,
            "typed_absence": TYPED_ABSENCE,
        }

    def to_canonical_json(self) -> str:
        payload = self.to_canonical()
        _reject_secret_fields(payload)
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def key_cid(self) -> str:
        """Content-addressed identity of the complete cache key."""

        return canonical_cid(self.to_canonical())

    # Compatibility spellings used by adjacent cache adapters.
    @property
    def digest(self) -> str:
        return self.key_cid()

    @property
    def cache_key(self) -> str:
        return self.key_cid()

    @property
    def key_id(self) -> str:
        return self.key_cid()

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> ProofCacheKey:
        if not isinstance(payload, Mapping):
            raise CacheKeyError("ProofCacheKey payload must be a mapping")
        _reject_secret_fields(payload)
        missing = [field for field in REQUIRED_FIELDS if field not in payload]
        if missing:
            raise CacheKeyError(
                f"ProofCacheKey missing required fields: {missing}"
            )
        allowed_meta = {
            "schema",
            "cache_key_subset",
            "typed_absence",
            "identity_schema_version",
        }
        unknown = sorted(
            set(payload) - set(REQUIRED_FIELDS) - allowed_meta
        )
        if unknown:
            raise CacheKeyError(f"unknown ProofCacheKey fields: {unknown}")
        schema = payload.get("schema")
        if schema is not None and schema != PROOF_CACHE_KEY_SCHEMA:
            raise CacheKeyError(
                f"unsupported ProofCacheKey schema {schema!r}; "
                f"expected {PROOF_CACHE_KEY_SCHEMA}"
            )
        return cls(
            statement_cid=payload["statement_cid"],
            public_input_cid=payload["public_input_cid"],
            private_input_commitment=payload["private_input_commitment"],
            source_root_cid=payload["source_root_cid"],
            source_artifact_cids=payload["source_artifact_cids"],
            source_closure_schema_version=payload[
                "source_closure_schema_version"
            ],
            dependency_unit_roots=payload["dependency_unit_roots"],
            dependency_roots_complete=payload["dependency_roots_complete"],
            dependency_graph_schema_version=payload[
                "dependency_graph_schema_version"
            ],
            environment_cid=payload["environment_cid"],
            dependency_lock_cid=payload["dependency_lock_cid"],
            fixture_cids=payload["fixture_cids"],
            tool_or_prover_id=payload["tool_or_prover_id"],
            tool_or_prover_version=payload["tool_or_prover_version"],
            proof_system_id=payload["proof_system_id"],
            evidence_class=payload["evidence_class"],
            proof_unit_kind=payload["proof_unit_kind"],
            proof_mode=payload["proof_mode"],
            circuit_id=payload["circuit_id"],
            circuit_version=payload["circuit_version"],
            proving_key_id=payload["proving_key_id"],
            verification_key_id=payload["verification_key_id"],
            configuration_cid=payload["configuration_cid"],
            network_policy_cid=payload["network_policy_cid"],
            proof_schema_version=payload["proof_schema_version"],
            canonicalization_version=payload["canonicalization_version"],
            test_selector_cid=payload["test_selector_cid"],
            policy_cid=payload["policy_cid"],
        )


def build_proof_cache_key(**values: Any) -> ProofCacheKey:
    """Construct a ProofCacheKey from keyword fields or a canonical mapping.

    Accepts either flat keyword arguments matching :data:`REQUIRED_FIELDS` or a
    single ``payload=`` / ``canonical=`` mapping.  Non-ambiguous aliases are
    normalized; conflicting aliases fail closed.
    """

    aliases = {
        "unit_kind": "proof_unit_kind",
        "kind": "proof_unit_kind",
        "mode": "proof_mode",
        "tool_id": "tool_or_prover_id",
        "tool_version": "tool_or_prover_version",
        "prover_id": "tool_or_prover_id",
        "prover_version": "tool_or_prover_version",
        "vk_id": "verification_key_id",
        "pk_id": "proving_key_id",
        "roots": "dependency_unit_roots",
        "dependency_roots": "dependency_unit_roots",
        "roots_complete": "dependency_roots_complete",
        "fixtures": "fixture_cids",
        "source_artifacts": "source_artifact_cids",
        "source_cids": "source_artifact_cids",
        "lock_cid": "dependency_lock_cid",
        "env_cid": "environment_cid",
        "canon_version": "canonicalization_version",
        "graph_schema_version": "dependency_graph_schema_version",
        "selector_cid": "test_selector_cid",
    }
    if "payload" in values and "canonical" in values:
        raise CacheKeyError("payload and canonical disagree as dual sources")
    if "payload" in values or "canonical" in values:
        if len(values) != 1:
            raise CacheKeyError(
                "payload/canonical must be the sole constructor argument"
            )
        mapping = values.get("payload", values.get("canonical"))
        if not isinstance(mapping, Mapping):
            raise CacheKeyError("payload/canonical must be a mapping")
        return ProofCacheKey.from_canonical(mapping)

    normalized = dict(values)
    for alias, canonical in aliases.items():
        if alias not in normalized:
            continue
        if canonical in normalized and normalized[canonical] != normalized[alias]:
            raise CacheKeyError(f"{alias} and {canonical} disagree")
        normalized[canonical] = normalized.pop(alias)
    unknown = sorted(set(normalized) - set(REQUIRED_FIELDS))
    if unknown:
        raise CacheKeyError(f"unknown ProofCacheKey fields: {unknown}")
    missing = [field for field in REQUIRED_FIELDS if field not in normalized]
    if missing:
        raise CacheKeyError(f"ProofCacheKey missing required fields: {missing}")
    return ProofCacheKey(**normalized)


def compute_proof_cache_key(**values: Any) -> ProofCacheKey:
    """IPS-017 public alias for :func:`build_proof_cache_key`."""

    return build_proof_cache_key(**values)


def sample_proof_cache_key(**overrides: Any) -> ProofCacheKey:
    """Minimal valid complete key for tests and hermetic vectors."""

    def _cid(label: str) -> str:
        return canonical_cid({"ips_cache_key_sample": label, "v": SCHEMA_MAJOR})

    payload: dict[str, Any] = {
        "statement_cid": _cid("statement"),
        "public_input_cid": _cid("public-input"),
        "private_input_commitment": _cid("private-commitment"),
        "source_root_cid": _cid("source-root"),
        "source_artifact_cids": sorted(
            [_cid("artifact-a"), _cid("artifact-b")]
        ),
        "source_closure_schema_version": "source-closure@1",
        "dependency_unit_roots": sorted([_cid("dep-root-a")]),
        "dependency_roots_complete": True,
        "dependency_graph_schema_version": "graph@1",
        "environment_cid": _cid("environment"),
        "dependency_lock_cid": _cid("lock"),
        "fixture_cids": sorted([_cid("fixture-a")]),
        "tool_or_prover_id": "groth16",
        "tool_or_prover_version": "1",
        "proof_system_id": "groth16",
        "evidence_class": EvidenceClass.DIRECT_EXECUTION_PROOF.value,
        "proof_unit_kind": ProofUnitKind.DIRECT_ZK_COMPUTATION.value,
        "proof_mode": ProofMode.DIRECT_EXECUTION_PROOF.value,
        "circuit_id": "direct@v1",
        "circuit_version": "1",
        "proving_key_id": ABSENCE_TOKEN,
        "verification_key_id": "vk/1",
        "configuration_cid": _cid("config"),
        "network_policy_cid": ABSENCE_TOKEN,
        "proof_schema_version": PROOF_SCHEMA_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "test_selector_cid": ABSENCE_TOKEN,
        "policy_cid": _cid("policy"),
    }
    payload.update(overrides)
    return ProofCacheKey.from_canonical(payload)


def _mutation_value(field: str, base: ProofCacheKey) -> Any:
    """Return a single-field mutation that must change the key CID."""

    def _cid(label: str) -> str:
        return canonical_cid(
            {"ips_cache_key_mutation": label, "field": field, "v": SCHEMA_MAJOR}
        )

    if field in _CID_SEQUENCE_FIELDS:
        current = getattr(base, field)
        extra = _cid(f"{field}-extra")
        return sorted(list(current) + [extra])
    if field in _CID_FIELDS:
        return _cid(field)
    if field == "dependency_roots_complete":
        # Incomplete roots fail closed; mutation vectors use a different complete
        # roots set instead (handled by callers that skip this field).
        return True
    if field == "evidence_class":
        return EvidenceClass.INTEGRITY_COMMITMENT.value
    if field == "proof_unit_kind":
        return ProofUnitKind.FORMAL_OBLIGATION.value
    if field == "proof_mode":
        return ProofMode.THEOREM_CERTIFICATE.value
    if field in _TEXT_FIELDS:
        current = getattr(base, field)
        if current == ABSENCE_TOKEN:
            return f"mutated-{field}"
        return f"{current}/mutated"
    raise CacheKeyError(f"no mutation defined for {field}")


def known_vectors() -> dict[str, Any]:
    """Versioned known cache-key vectors and single-field mutation set."""

    base = sample_proof_cache_key()
    base_cid = base.key_cid()
    mutations: dict[str, Any] = {}
    for field in REQUIRED_FIELDS:
        if field == "dependency_roots_complete":
            # Completeness is boolean True-only; incompleteness fails closed.
            continue
        mutated_payload = base.to_canonical()
        mutated_payload[field] = _mutation_value(field, base)
        mutated = ProofCacheKey.from_canonical(mutated_payload)
        mutated_cid = mutated.key_cid()
        if mutated_cid == base_cid:
            raise CacheKeyError(
                f"single-field mutation of {field} did not change key CID"
            )
        mutations[field] = {
            "field": field,
            "base_key_cid": base_cid,
            "mutated_key_cid": mutated_cid,
        }

    incomplete_payload = base.to_canonical()
    incomplete_payload["dependency_roots_complete"] = False

    return {
        "schema": f"{CACHE_KEY_NAMESPACE}/known-vectors@{SCHEMA_MAJOR}",
        "cache_key_subset": CACHE_KEY_SUBSET,
        "cache_key_vectors_subset": CACHE_KEY_VECTORS_SUBSET,
        "proof_cache_key_schema": PROOF_CACHE_KEY_SCHEMA,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "required_fields": list(REQUIRED_FIELDS),
        "base": {
            "payload": base.to_canonical(),
            "key_cid": base_cid,
        },
        "single_field_mutations": mutations,
        "fail_closed": {
            "incomplete_roots_payload": incomplete_payload,
            "duplicate_source_artifacts": {
                **base.to_canonical(),
                "source_artifact_cids": [
                    base.source_artifact_cids[0],
                    base.source_artifact_cids[0],
                ],
            },
            "unsorted_dependency_roots": {
                **base.to_canonical(),
                "dependency_unit_roots": _unsorted_cid_pair(),
            },
        },
    }


def _unsorted_cid_pair() -> list[str]:
    left = canonical_cid({"ips_cache_key_sort": "left", "v": SCHEMA_MAJOR})
    right = canonical_cid({"ips_cache_key_sort": "right", "v": SCHEMA_MAJOR})
    ordered = sorted([left, right])
    return [ordered[1], ordered[0]]


__all__ = (
    "ABSENCE_TOKEN",
    "CACHE_KEY_SUBSET",
    "CACHE_KEY_VECTORS_SUBSET",
    "CANONICALIZATION_VERSION",
    "PROOF_CACHE_KEY_SCHEMA",
    "PROOF_SCHEMA_VERSION",
    "REQUIRED_FIELDS",
    "TYPED_ABSENCE",
    "CacheKeyError",
    "ProofCacheKey",
    "build_proof_cache_key",
    "compute_proof_cache_key",
    "known_vectors",
    "sample_proof_cache_key",
)
