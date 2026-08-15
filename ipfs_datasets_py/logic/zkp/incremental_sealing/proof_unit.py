"""Closed immutable ProofUnit@1 schema (IPS-006).

Every normative field is present.  Non-applicable values use one typed
absence.  Canonical identity excludes secrets and wall-clock timestamps.
A required simulated unit, or a non-pass terminal status, cannot satisfy
production seal policy.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from .evidence import (
    EvidenceClass,
    EvidenceClassError,
    ProofMode,
    ProofTerminalStatus,
    ProofUnitKind,
    SealStatus,
    assert_production_seal_allowed,
    parse_proof_mode,
    parse_proof_unit_kind,
    parse_seal_status,
    parse_terminal_status,
    status_satisfies_class,
)

PROOF_UNIT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/logic/zkp/incremental_sealing/proof-unit@1"
)
EVIDENCE_SUBSET: Final[str] = "ips/proof-unit@1"
TYPED_ABSENCE: Final[str] = "typed_absence"
ABSENCE_TOKEN: Final[str] = "n/a"
MAX_IDENTIFIER_BYTES: Final[int] = 512
MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1
SECRET_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "private_key",
        "proving_key_bytes",
        "witness",
        "secret",
        "password",
        "created_at",
        "timestamp",
        "wall_clock",
    }
)

REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "proof_unit_id",
    "proof_unit_kind",
    "repository_id",
    "source_root_cid",
    "repository_state_cid",
    "source_closure_schema_version",
    "source_artifact_cids",
    "source_symbol_ids",
    "test_ids",
    "property_id",
    "statement_cid",
    "public_input_cid",
    "private_input_commitment",
    "dependency_unit_ids",
    "dependency_unit_roots",
    "environment_cid",
    "dependency_lock_cid",
    "tool_or_prover_id",
    "tool_or_prover_version",
    "circuit_id",
    "circuit_version",
    "proving_key_id",
    "verification_key_id",
    "configuration_cid",
    "fixture_cids",
    "network_policy_cid",
    "test_selector_cid",
    "policy_cid",
    "canonicalization_version",
    "dependency_graph_schema_version",
    "proof_system_id",
    "evidence_class",
    "proof_schema_version",
    "required_for_seal",
    "risk_class",
    "proof_mode",
    "terminal_status",
    "proof_object_cid",
    "receipt_cid",
    "logical_epoch",
)


class ProofUnitError(EvidenceClassError):
    """ProofUnit@1 contract violation."""


def _is_absence(value: Any) -> bool:
    return value == ABSENCE_TOKEN


def _require_text(value: Any, field: str, *, allow_absence: bool = True) -> str:
    if allow_absence and _is_absence(value):
        return ABSENCE_TOKEN
    if not isinstance(value, str) or not value.strip():
        raise ProofUnitError(f"{field} must be a non-empty string or {ABSENCE_TOKEN}")
    text = value.strip()
    if len(text.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise ProofUnitError(f"{field} exceeds {MAX_IDENTIFIER_BYTES} bytes")
    return text


def _require_tuple(value: Any, field: str) -> tuple[str, ...]:
    if _is_absence(value):
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ProofUnitError(f"{field} must be a sequence or {ABSENCE_TOKEN}")
    items = tuple(_require_text(item, field, allow_absence=False) for item in value)
    if list(items) != sorted(items):
        raise ProofUnitError(f"{field} must be canonically sorted")
    if len(set(items)) != len(items):
        raise ProofUnitError(f"{field} must not contain duplicates")
    return items


def _require_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise ProofUnitError(f"{field} must be a boolean")
    return value


def _require_epoch(value: Any) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise ProofUnitError("logical_epoch must be a finite int")
    if value < 0 or value > MAX_SAFE_INTEGER:
        raise ProofUnitError("logical_epoch is nonfinite or out of bounds")
    return value


def _parse_evidence_class(value: Any) -> EvidenceClass:
    if isinstance(value, EvidenceClass):
        return value
    if not isinstance(value, str):
        raise ProofUnitError("evidence_class must be a closed class name")
    try:
        return EvidenceClass(value)
    except ValueError as exc:
        raise ProofUnitError(f"unknown evidence_class {value!r}") from exc


@dataclass(frozen=True, slots=True)
class ProofUnit:
    """Immutable ProofUnit@1.  All required fields exist on every instance."""

    proof_unit_id: str
    proof_unit_kind: ProofUnitKind
    repository_id: str
    source_root_cid: str
    repository_state_cid: str
    source_closure_schema_version: str
    source_artifact_cids: tuple[str, ...]
    source_symbol_ids: tuple[str, ...]
    test_ids: tuple[str, ...]
    property_id: str
    statement_cid: str
    public_input_cid: str
    private_input_commitment: str
    dependency_unit_ids: tuple[str, ...]
    dependency_unit_roots: tuple[str, ...]
    environment_cid: str
    dependency_lock_cid: str
    tool_or_prover_id: str
    tool_or_prover_version: str
    circuit_id: str
    circuit_version: str
    proving_key_id: str
    verification_key_id: str
    configuration_cid: str
    fixture_cids: tuple[str, ...]
    network_policy_cid: str
    test_selector_cid: str
    policy_cid: str
    canonicalization_version: str
    dependency_graph_schema_version: str
    proof_system_id: str
    evidence_class: EvidenceClass
    proof_schema_version: str
    required_for_seal: bool
    risk_class: str
    proof_mode: ProofMode
    terminal_status: ProofTerminalStatus
    proof_object_cid: str
    receipt_cid: str
    logical_epoch: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "proof_unit_id", _require_text(self.proof_unit_id, "proof_unit_id", allow_absence=False)
        )
        object.__setattr__(
            self, "repository_id", _require_text(self.repository_id, "repository_id", allow_absence=False)
        )
        object.__setattr__(
            self, "source_root_cid", _require_text(self.source_root_cid, "source_root_cid", allow_absence=False)
        )
        object.__setattr__(
            self,
            "repository_state_cid",
            _require_text(self.repository_state_cid, "repository_state_cid", allow_absence=False),
        )
        if self.source_root_cid == self.repository_state_cid:
            raise ProofUnitError(
                "source_root_cid is the unit source-closure root, not repository_state_cid"
            )
        if self.required_for_seal and self.proof_mode is ProofMode.SIMULATED:
            if self.terminal_status is not ProofTerminalStatus.SIMULATED:
                raise ProofUnitError(
                    "required simulated units cannot satisfy production"
                )
        if self.required_for_seal and self.terminal_status in {
            ProofTerminalStatus.FAILED,
            ProofTerminalStatus.PROOF_FAILED,
            ProofTerminalStatus.INVALID,
            ProofTerminalStatus.STALE,
        }:
            raise ProofUnitError("required non-pass units cannot satisfy production")

    def satisfies_production(self) -> bool:
        if self.proof_mode is ProofMode.SIMULATED:
            return False
        if not self.required_for_seal:
            return False
        return status_satisfies_class(self.terminal_status, self.evidence_class)

    def to_canonical(self) -> dict[str, Any]:
        def _seq(values: tuple[str, ...]) -> list[str] | str:
            return list(values) if values else ABSENCE_TOKEN

        return {
            "schema": PROOF_UNIT_SCHEMA,
            "proof_schema_version": self.proof_schema_version,
            "proof_unit_id": self.proof_unit_id,
            "proof_unit_kind": self.proof_unit_kind.value,
            "repository_id": self.repository_id,
            "source_root_cid": self.source_root_cid,
            "repository_state_cid": self.repository_state_cid,
            "source_closure_schema_version": self.source_closure_schema_version,
            "source_artifact_cids": _seq(self.source_artifact_cids),
            "source_symbol_ids": _seq(self.source_symbol_ids),
            "test_ids": _seq(self.test_ids),
            "property_id": self.property_id,
            "statement_cid": self.statement_cid,
            "public_input_cid": self.public_input_cid,
            "private_input_commitment": self.private_input_commitment,
            "dependency_unit_ids": _seq(self.dependency_unit_ids),
            "dependency_unit_roots": _seq(self.dependency_unit_roots),
            "environment_cid": self.environment_cid,
            "dependency_lock_cid": self.dependency_lock_cid,
            "tool_or_prover_id": self.tool_or_prover_id,
            "tool_or_prover_version": self.tool_or_prover_version,
            "circuit_id": self.circuit_id,
            "circuit_version": self.circuit_version,
            "proving_key_id": self.proving_key_id,
            "verification_key_id": self.verification_key_id,
            "configuration_cid": self.configuration_cid,
            "fixture_cids": _seq(self.fixture_cids),
            "network_policy_cid": self.network_policy_cid,
            "test_selector_cid": self.test_selector_cid,
            "policy_cid": self.policy_cid,
            "canonicalization_version": self.canonicalization_version,
            "dependency_graph_schema_version": self.dependency_graph_schema_version,
            "proof_system_id": self.proof_system_id,
            "evidence_class": self.evidence_class.value,
            "required_for_seal": self.required_for_seal,
            "risk_class": self.risk_class,
            "proof_mode": self.proof_mode.value,
            "terminal_status": self.terminal_status.value,
            "proof_object_cid": self.proof_object_cid,
            "receipt_cid": self.receipt_cid,
            "logical_epoch": self.logical_epoch,
            "typed_absence": TYPED_ABSENCE,
        }

    def to_canonical_json(self) -> str:
        payload = self.to_canonical()
        forbidden = set(payload) & SECRET_FIELD_NAMES
        if forbidden:
            raise ProofUnitError(f"canonical identity leaked secrets {sorted(forbidden)}")
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> ProofUnit:
        if not isinstance(payload, Mapping):
            raise ProofUnitError("ProofUnit payload must be a mapping")
        missing = [field for field in REQUIRED_FIELDS if field not in payload]
        if missing:
            raise ProofUnitError(f"ProofUnit missing required fields: {missing}")
        leaked = set(payload) & SECRET_FIELD_NAMES
        if leaked:
            raise ProofUnitError(f"secret or timestamp fields are forbidden: {sorted(leaked)}")
        for key, value in payload.items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ProofUnitError(f"{key} is nonfinite")
        return cls(
            proof_unit_id=str(payload["proof_unit_id"]),
            proof_unit_kind=parse_proof_unit_kind(payload["proof_unit_kind"]),
            repository_id=str(payload["repository_id"]),
            source_root_cid=str(payload["source_root_cid"]),
            repository_state_cid=str(payload["repository_state_cid"]),
            source_closure_schema_version=_require_text(
                payload["source_closure_schema_version"],
                "source_closure_schema_version",
            ),
            source_artifact_cids=_require_tuple(payload["source_artifact_cids"], "source_artifact_cids"),
            source_symbol_ids=_require_tuple(payload["source_symbol_ids"], "source_symbol_ids"),
            test_ids=_require_tuple(payload["test_ids"], "test_ids"),
            property_id=_require_text(payload["property_id"], "property_id"),
            statement_cid=_require_text(payload["statement_cid"], "statement_cid"),
            public_input_cid=_require_text(payload["public_input_cid"], "public_input_cid"),
            private_input_commitment=_require_text(
                payload["private_input_commitment"], "private_input_commitment"
            ),
            dependency_unit_ids=_require_tuple(
                payload["dependency_unit_ids"], "dependency_unit_ids"
            ),
            dependency_unit_roots=_require_tuple(
                payload["dependency_unit_roots"], "dependency_unit_roots"
            ),
            environment_cid=_require_text(payload["environment_cid"], "environment_cid"),
            dependency_lock_cid=_require_text(
                payload["dependency_lock_cid"], "dependency_lock_cid"
            ),
            tool_or_prover_id=_require_text(payload["tool_or_prover_id"], "tool_or_prover_id"),
            tool_or_prover_version=_require_text(
                payload["tool_or_prover_version"], "tool_or_prover_version"
            ),
            circuit_id=_require_text(payload["circuit_id"], "circuit_id"),
            circuit_version=_require_text(payload["circuit_version"], "circuit_version"),
            proving_key_id=_require_text(payload["proving_key_id"], "proving_key_id"),
            verification_key_id=_require_text(
                payload["verification_key_id"], "verification_key_id"
            ),
            configuration_cid=_require_text(
                payload["configuration_cid"], "configuration_cid"
            ),
            fixture_cids=_require_tuple(payload["fixture_cids"], "fixture_cids"),
            network_policy_cid=_require_text(
                payload["network_policy_cid"], "network_policy_cid"
            ),
            test_selector_cid=_require_text(
                payload["test_selector_cid"], "test_selector_cid"
            ),
            policy_cid=_require_text(payload["policy_cid"], "policy_cid"),
            canonicalization_version=_require_text(
                payload["canonicalization_version"], "canonicalization_version"
            ),
            dependency_graph_schema_version=_require_text(
                payload["dependency_graph_schema_version"],
                "dependency_graph_schema_version",
            ),
            proof_system_id=_require_text(payload["proof_system_id"], "proof_system_id"),
            evidence_class=_parse_evidence_class(payload["evidence_class"]),
            proof_schema_version=_require_text(
                payload["proof_schema_version"], "proof_schema_version", allow_absence=False
            ),
            required_for_seal=_require_bool(payload["required_for_seal"], "required_for_seal"),
            risk_class=_require_text(payload["risk_class"], "risk_class"),
            proof_mode=parse_proof_mode(payload["proof_mode"]),
            terminal_status=parse_terminal_status(payload["terminal_status"]),
            proof_object_cid=_require_text(payload["proof_object_cid"], "proof_object_cid"),
            receipt_cid=_require_text(payload["receipt_cid"], "receipt_cid"),
            logical_epoch=_require_epoch(payload["logical_epoch"]),
        )


def sample_production_unit() -> ProofUnit:
    """Minimal valid production-capable unit for tests and fixtures."""

    return ProofUnit.from_canonical(
        {
            "proof_unit_id": "unit/direct-1",
            "proof_unit_kind": ProofUnitKind.DIRECT_ZK_COMPUTATION.value,
            "repository_id": "repo/datasets",
            "source_root_cid": "sha256:" + ("11" * 32),
            "repository_state_cid": "sha256:" + ("22" * 32),
            "source_closure_schema_version": "source-closure@1",
            "source_artifact_cids": ["sha256:" + ("33" * 32)],
            "source_symbol_ids": ["mod:fn"],
            "test_ids": ABSENCE_TOKEN,
            "property_id": "prop/output",
            "statement_cid": "sha256:" + ("44" * 32),
            "public_input_cid": "sha256:" + ("55" * 32),
            "private_input_commitment": "sha256:" + ("66" * 32),
            "dependency_unit_ids": ABSENCE_TOKEN,
            "dependency_unit_roots": ABSENCE_TOKEN,
            "environment_cid": "sha256:" + ("77" * 32),
            "dependency_lock_cid": "sha256:" + ("88" * 32),
            "tool_or_prover_id": "groth16",
            "tool_or_prover_version": "1",
            "circuit_id": "direct@v1",
            "circuit_version": "1",
            "proving_key_id": ABSENCE_TOKEN,
            "verification_key_id": "vk/1",
            "configuration_cid": "sha256:" + ("99" * 32),
            "fixture_cids": ABSENCE_TOKEN,
            "network_policy_cid": ABSENCE_TOKEN,
            "test_selector_cid": ABSENCE_TOKEN,
            "policy_cid": "sha256:" + ("aa" * 32),
            "canonicalization_version": "canon@1",
            "dependency_graph_schema_version": "graph@1",
            "proof_system_id": "groth16",
            "evidence_class": EvidenceClass.DIRECT_EXECUTION_PROOF.value,
            "proof_schema_version": "1",
            "required_for_seal": True,
            "risk_class": "high",
            "proof_mode": ProofMode.DIRECT_EXECUTION_PROOF.value,
            "terminal_status": ProofTerminalStatus.PROVED.value,
            "proof_object_cid": "sha256:" + ("bb" * 32),
            "receipt_cid": "sha256:" + ("cc" * 32),
            "logical_epoch": 1,
        }
    )


def assert_unit_production_policy(unit: ProofUnit, seal_status: SealStatus) -> None:
    assert_production_seal_allowed(unit.proof_mode, seal_status)
    if unit.required_for_seal and not unit.satisfies_production():
        raise ProofUnitError("required simulated/non-pass units cannot satisfy production")
