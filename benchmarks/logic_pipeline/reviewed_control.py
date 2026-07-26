"""Independent reviewed-control safety authority for HSSL-G236.

The control classification and runtime outcome are deliberately separate
inputs.  A control is authoritative only when a CID-addressed entry is joined
to its exact external review attestation and frozen non-holdout rescue/source
manifests.  Runtime success is recomputed only from the terminal independent
native-kernel receipt in a fully replayed :class:`CausalRuntimeEvidenceV2`.

This module performs no filesystem I/O and never accepts an ``invalid_control``
boolean from a runtime or metric caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final, Mapping, Self, Sequence

from .adversarial import ControlKind
from .causal_ablation import CausalRescueManifestV2
from .causal_runtime import (
    CausalRuntimeEvidenceV2,
    validate_causal_runtime_evidence_v2,
)
from .content_addressing import (
    cid_for_dag_json,
    validate_cid,
)
from .contracts import (
    CacheMode,
    ProtocolContractError,
    Split,
    StageName,
    validate_native_kernel_stage_receipt,
)


REVIEWED_CONTROL_CLASSIFICATION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "reviewed-invalid-control-classification.v2"
)
REVIEWED_CONTROL_ATTESTATION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "reviewed-control-attestation.v2"
)
REVIEWED_CONTROL_ENTRY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.reviewed-control-entry.v2"
)
REVIEWED_CONTROL_INDEX_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.reviewed-control-index.v2"
)
REVIEWED_CONTROL_SAFETY_GATE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "reviewed-control-safety-gate.v2"
)
REVIEWED_CONTROL_COORDINATE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "reviewed-control-runtime-coordinate.v2"
)
REVIEWED_CONTROL_RUNTIME_SET_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "reviewed-control-runtime-set.v2"
)
REVIEWED_CONTROL_POLICY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "reviewed-control-safety-policy.v2"
)
REVIEWED_CONTROL_REVIEW_PROTOCOL_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "independent-control-review-protocol.v2"
)

G236_REQUIRED_VARIANT_IDS: Final = tuple(
    f"A{index}" for index in range(13)
)
G236_REQUIRED_CACHE_MODES: Final = (
    CacheMode.COLD,
    CacheMode.WARM,
)
_CONTROL_CLASSIFICATION: Final = "invalid_control"


class ReviewedControlSafetyError(ValueError):
    """Raised when reviewed-control authority is malformed or self-asserted."""


def HSSLEV2367D38() -> str:
    """Return AST-verifiable evidence for the bounded G236 safety lane."""

    return (
        "CID-addressed independently reviewed non-holdout controls with "
        "exact full-runtime joins and fatal terminal native-kernel authority"
    )


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ReviewedControlSafetyError(
                "reviewed-control DAG-JSON objects require string keys"
            )
        return {
            str(key): _plain(member)
            for key, member in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_plain(member) for member in value]
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise ReviewedControlSafetyError(
        "reviewed-control value is not DAG-JSON: "
        f"{type(value).__name__}"
    )


def _freeze(value: object) -> object:
    plain = _plain(value)
    if isinstance(plain, dict):
        return MappingProxyType(
            {
                key: _freeze(member)
                for key, member in plain.items()
            }
        )
    if isinstance(plain, list):
        return tuple(_freeze(member) for member in plain)
    return plain


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ReviewedControlSafetyError(f"{field} must be an object")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ReviewedControlSafetyError(f"{field} must be an array")
    return value


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    if set(value) != expected:
        raise ReviewedControlSafetyError(
            f"{field} fields changed: "
            f"missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def _safe_id(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or not value[0].isalnum()
        or any(
            not (character.isalnum() or character in "._-")
            for character in value
        )
        or value in {".", ".."}
    ):
        raise ReviewedControlSafetyError(
            f"{field} must be a safe 1-128 character identifier"
        )
    return value


def _cid(
    value: object,
    field: str,
    *,
    codecs: tuple[str, ...] = ("dag-json",),
) -> str:
    try:
        return validate_cid(value, codecs=codecs)
    except (TypeError, ValueError) as exc:
        raise ReviewedControlSafetyError(
            f"{field} must be a canonical CIDv1/base32/sha2-256 value"
        ) from exc


def _control_kind(value: object) -> ControlKind:
    if not isinstance(value, ControlKind):
        raise ReviewedControlSafetyError(
            "control_kind must be a typed frozen ControlKind"
        )
    return value


def reviewed_control_policy_v2() -> dict[str, object]:
    """Return the frozen fatal safety policy for all reviewed controls."""

    return {
        "schema": REVIEWED_CONTROL_POLICY_SCHEMA_V2,
        "classification": _CONTROL_CLASSIFICATION,
        "control_kinds": [kind.value for kind in ControlKind],
        "required_variant_ids": list(G236_REQUIRED_VARIANT_IDS),
        "required_cache_modes": [
            mode.value for mode in G236_REQUIRED_CACHE_MODES
        ],
        "runtime_evidence_schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "causal-runtime-evidence.v2"
        ),
        "success_authority": "terminal_independent_native_kernel",
        "maximum_native_kernel_acceptances": 0,
        "fully_observed_population_required": True,
        "caller_asserted_classifications_forbidden": True,
        "holdout_included": False,
    }


REVIEWED_CONTROL_POLICY_V2_CID: Final = cid_for_dag_json(
    reviewed_control_policy_v2()
)


def reviewed_control_review_protocol_v2() -> dict[str, object]:
    """Return the frozen external-review identity and timing policy."""

    return {
        "schema": REVIEWED_CONTROL_REVIEW_PROTOCOL_SCHEMA_V2,
        "classification": _CONTROL_CLASSIFICATION,
        "review_authority_must_differ_from_execution_authority": True,
        "review_basis_cid_required": True,
        "classification_must_precede_runtime_execution": True,
        "source_and_rescue_manifest_binding_required": True,
        "self_attested_runtime_classification_forbidden": True,
        "holdout_included": False,
    }


REVIEWED_CONTROL_REVIEW_PROTOCOL_V2_CID: Final = cid_for_dag_json(
    reviewed_control_review_protocol_v2()
)


def _classification_payload(
    *,
    case_id: str,
    split: Split,
    source_cid: str,
    control_kind: ControlKind,
    source_manifest_cid: str,
    rescue_manifest_cid: str,
    control_policy_cid: str,
) -> dict[str, object]:
    return {
        "schema": REVIEWED_CONTROL_CLASSIFICATION_SCHEMA_V2,
        "case_id": case_id,
        "split": split.value,
        "source_cid": source_cid,
        "classification": _CONTROL_CLASSIFICATION,
        "control_kind": control_kind.value,
        "control_policy_cid": control_policy_cid,
        "source_manifest_cid": source_manifest_cid,
        "rescue_manifest_cid": rescue_manifest_cid,
        "holdout_included": False,
    }


@dataclass(frozen=True, slots=True)
class ReviewedControlAttestationV2:
    """External independent review of one exact control classification."""

    case_id: str
    split: Split
    source_cid: str
    control_kind: ControlKind
    source_manifest_cid: str
    rescue_manifest_cid: str
    review_authority_cid: str
    execution_authority_cid: str
    review_basis_cid: str
    control_policy_cid: str = REVIEWED_CONTROL_POLICY_V2_CID
    review_protocol_cid: str = (
        REVIEWED_CONTROL_REVIEW_PROTOCOL_V2_CID
    )
    classification: str = _CONTROL_CLASSIFICATION
    holdout_included: bool = False
    schema: str = REVIEWED_CONTROL_ATTESTATION_SCHEMA_V2

    def __post_init__(self) -> None:
        if self.schema != REVIEWED_CONTROL_ATTESTATION_SCHEMA_V2:
            raise ReviewedControlSafetyError(
                "unsupported reviewed-control attestation schema"
            )
        object.__setattr__(
            self,
            "case_id",
            _safe_id(self.case_id, "case_id"),
        )
        if self.split not in {Split.PILOT, Split.DEVELOPMENT}:
            raise ReviewedControlSafetyError(
                "reviewed controls must be pilot/development only"
            )
        object.__setattr__(
            self,
            "source_cid",
            _cid(self.source_cid, "source_cid", codecs=("raw",)),
        )
        object.__setattr__(
            self,
            "control_kind",
            _control_kind(self.control_kind),
        )
        for field in (
            "source_manifest_cid",
            "rescue_manifest_cid",
            "review_authority_cid",
            "execution_authority_cid",
            "review_basis_cid",
            "control_policy_cid",
            "review_protocol_cid",
        ):
            object.__setattr__(
                self,
                field,
                _cid(getattr(self, field), field),
            )
        if (
            self.control_policy_cid != REVIEWED_CONTROL_POLICY_V2_CID
            or self.review_protocol_cid
            != REVIEWED_CONTROL_REVIEW_PROTOCOL_V2_CID
            or self.classification != _CONTROL_CLASSIFICATION
            or self.holdout_included is not False
        ):
            raise ReviewedControlSafetyError(
                "reviewed-control attestation policy drifted"
            )
        if self.review_authority_cid == self.execution_authority_cid:
            raise ReviewedControlSafetyError(
                "control review authority must be independent from execution"
            )

    @property
    def classification_payload(self) -> dict[str, object]:
        return _classification_payload(
            case_id=self.case_id,
            split=self.split,
            source_cid=self.source_cid,
            control_kind=self.control_kind,
            source_manifest_cid=self.source_manifest_cid,
            rescue_manifest_cid=self.rescue_manifest_cid,
            control_policy_cid=self.control_policy_cid,
        )

    @property
    def classification_cid(self) -> str:
        return cid_for_dag_json(self.classification_payload)

    def identity_payload(self) -> dict[str, object]:
        return {
            **self.classification_payload,
            "schema": self.schema,
            "classification_schema": (
                REVIEWED_CONTROL_CLASSIFICATION_SCHEMA_V2
            ),
            "classification_cid": self.classification_cid,
            "review_protocol_cid": self.review_protocol_cid,
            "review_authority_cid": self.review_authority_cid,
            "execution_authority_cid": self.execution_authority_cid,
            "review_basis_cid": self.review_basis_cid,
        }

    @property
    def attestation_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "attestation_cid": self.attestation_cid,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "reviewed-control attestation")
        expected = {
            "schema",
            "classification_schema",
            "case_id",
            "split",
            "source_cid",
            "classification",
            "control_kind",
            "control_policy_cid",
            "source_manifest_cid",
            "rescue_manifest_cid",
            "holdout_included",
            "classification_cid",
            "review_protocol_cid",
            "review_authority_cid",
            "execution_authority_cid",
            "review_basis_cid",
            "attestation_cid",
        }
        _exact(data, expected, "reviewed-control attestation")
        try:
            split = Split(data["split"])
            kind = ControlKind(data["control_kind"])
        except (TypeError, ValueError) as exc:
            raise ReviewedControlSafetyError(
                "reviewed-control attestation classification is unsupported"
            ) from exc
        result = cls(
            schema=data["schema"],  # type: ignore[arg-type]
            case_id=data["case_id"],  # type: ignore[arg-type]
            split=split,
            source_cid=data["source_cid"],  # type: ignore[arg-type]
            control_kind=kind,
            source_manifest_cid=data[
                "source_manifest_cid"
            ],  # type: ignore[arg-type]
            rescue_manifest_cid=data[
                "rescue_manifest_cid"
            ],  # type: ignore[arg-type]
            review_authority_cid=data[
                "review_authority_cid"
            ],  # type: ignore[arg-type]
            execution_authority_cid=data[
                "execution_authority_cid"
            ],  # type: ignore[arg-type]
            review_basis_cid=data[
                "review_basis_cid"
            ],  # type: ignore[arg-type]
            control_policy_cid=data[
                "control_policy_cid"
            ],  # type: ignore[arg-type]
            review_protocol_cid=data[
                "review_protocol_cid"
            ],  # type: ignore[arg-type]
            classification=data["classification"],  # type: ignore[arg-type]
            holdout_included=data[
                "holdout_included"
            ],  # type: ignore[arg-type]
        )
        if (
            data["classification_schema"]
            != REVIEWED_CONTROL_CLASSIFICATION_SCHEMA_V2
            or data["classification_cid"] != result.classification_cid
            or data["attestation_cid"] != result.attestation_cid
        ):
            raise ReviewedControlSafetyError(
                "reviewed-control attestation CID or classification changed"
            )
        return result


@dataclass(frozen=True, slots=True)
class ReviewedControlEntryV2:
    """One CID-addressed, attested, non-holdout control case."""

    case_id: str
    split: Split
    source_cid: str
    control_kind: ControlKind
    review_attestation_cid: str
    source_manifest_cid: str
    rescue_manifest_cid: str
    control_policy_cid: str = REVIEWED_CONTROL_POLICY_V2_CID
    classification: str = _CONTROL_CLASSIFICATION
    holdout_included: bool = False
    schema: str = REVIEWED_CONTROL_ENTRY_SCHEMA_V2

    def __post_init__(self) -> None:
        if self.schema != REVIEWED_CONTROL_ENTRY_SCHEMA_V2:
            raise ReviewedControlSafetyError(
                "unsupported reviewed-control entry schema"
            )
        object.__setattr__(
            self,
            "case_id",
            _safe_id(self.case_id, "case_id"),
        )
        if self.split not in {Split.PILOT, Split.DEVELOPMENT}:
            raise ReviewedControlSafetyError(
                "reviewed controls must be pilot/development only"
            )
        object.__setattr__(
            self,
            "source_cid",
            _cid(self.source_cid, "source_cid", codecs=("raw",)),
        )
        object.__setattr__(
            self,
            "control_kind",
            _control_kind(self.control_kind),
        )
        for field in (
            "review_attestation_cid",
            "source_manifest_cid",
            "rescue_manifest_cid",
            "control_policy_cid",
        ):
            object.__setattr__(
                self,
                field,
                _cid(getattr(self, field), field),
            )
        if (
            self.control_policy_cid != REVIEWED_CONTROL_POLICY_V2_CID
            or self.classification != _CONTROL_CLASSIFICATION
            or self.holdout_included is not False
        ):
            raise ReviewedControlSafetyError(
                "reviewed-control entry policy drifted"
            )

    @property
    def classification_payload(self) -> dict[str, object]:
        return _classification_payload(
            case_id=self.case_id,
            split=self.split,
            source_cid=self.source_cid,
            control_kind=self.control_kind,
            source_manifest_cid=self.source_manifest_cid,
            rescue_manifest_cid=self.rescue_manifest_cid,
            control_policy_cid=self.control_policy_cid,
        )

    @property
    def classification_cid(self) -> str:
        return cid_for_dag_json(self.classification_payload)

    def identity_payload(self) -> dict[str, object]:
        return {
            **self.classification_payload,
            "schema": self.schema,
            "classification_schema": (
                REVIEWED_CONTROL_CLASSIFICATION_SCHEMA_V2
            ),
            "classification_cid": self.classification_cid,
            "review_attestation_cid": self.review_attestation_cid,
        }

    @property
    def entry_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "entry_cid": self.entry_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "reviewed-control entry")
        expected = {
            "schema",
            "classification_schema",
            "case_id",
            "split",
            "source_cid",
            "classification",
            "control_kind",
            "control_policy_cid",
            "review_attestation_cid",
            "source_manifest_cid",
            "rescue_manifest_cid",
            "holdout_included",
            "classification_cid",
            "entry_cid",
        }
        _exact(data, expected, "reviewed-control entry")
        try:
            split = Split(data["split"])
            kind = ControlKind(data["control_kind"])
        except (TypeError, ValueError) as exc:
            raise ReviewedControlSafetyError(
                "reviewed-control entry classification is unsupported"
            ) from exc
        result = cls(
            schema=data["schema"],  # type: ignore[arg-type]
            case_id=data["case_id"],  # type: ignore[arg-type]
            split=split,
            source_cid=data["source_cid"],  # type: ignore[arg-type]
            control_kind=kind,
            review_attestation_cid=data[
                "review_attestation_cid"
            ],  # type: ignore[arg-type]
            source_manifest_cid=data[
                "source_manifest_cid"
            ],  # type: ignore[arg-type]
            rescue_manifest_cid=data[
                "rescue_manifest_cid"
            ],  # type: ignore[arg-type]
            control_policy_cid=data[
                "control_policy_cid"
            ],  # type: ignore[arg-type]
            classification=data["classification"],  # type: ignore[arg-type]
            holdout_included=data[
                "holdout_included"
            ],  # type: ignore[arg-type]
        )
        if (
            data["classification_schema"]
            != REVIEWED_CONTROL_CLASSIFICATION_SCHEMA_V2
            or data["classification_cid"] != result.classification_cid
            or data["entry_cid"] != result.entry_cid
        ):
            raise ReviewedControlSafetyError(
                "reviewed-control entry CID or classification changed"
            )
        return result


def _entry_key(entry: ReviewedControlEntryV2) -> tuple[str, str]:
    return entry.split.value, entry.case_id


@dataclass(frozen=True, slots=True)
class ReviewedControlIndexV2:
    """Frozen control population and its exact independent attestations."""

    review_authority_cid: str
    execution_authority_cid: str
    entries: tuple[ReviewedControlEntryV2, ...]
    attestations: tuple[ReviewedControlAttestationV2, ...]
    control_policy_cid: str = REVIEWED_CONTROL_POLICY_V2_CID
    review_protocol_cid: str = (
        REVIEWED_CONTROL_REVIEW_PROTOCOL_V2_CID
    )
    frozen: bool = True
    holdout_included: bool = False
    schema: str = REVIEWED_CONTROL_INDEX_SCHEMA_V2

    def __post_init__(self) -> None:
        if self.schema != REVIEWED_CONTROL_INDEX_SCHEMA_V2:
            raise ReviewedControlSafetyError(
                "unsupported reviewed-control index schema"
            )
        for field in (
            "review_authority_cid",
            "execution_authority_cid",
            "control_policy_cid",
            "review_protocol_cid",
        ):
            object.__setattr__(
                self,
                field,
                _cid(getattr(self, field), field),
            )
        if (
            self.review_authority_cid == self.execution_authority_cid
            or self.control_policy_cid != REVIEWED_CONTROL_POLICY_V2_CID
            or self.review_protocol_cid
            != REVIEWED_CONTROL_REVIEW_PROTOCOL_V2_CID
            or self.frozen is not True
            or self.holdout_included is not False
        ):
            raise ReviewedControlSafetyError(
                "reviewed-control index authority or policy drifted"
            )
        entries = tuple(self.entries)
        if (
            not entries
            or any(
                not isinstance(item, ReviewedControlEntryV2)
                for item in entries
            )
        ):
            raise ReviewedControlSafetyError(
                "reviewed-control index requires a nonempty typed population"
            )
        entries = tuple(
            ReviewedControlEntryV2.from_dict(item.to_dict())
            for item in entries
        )
        keys = tuple(_entry_key(item) for item in entries)
        source_keys = tuple(
            (item.split.value, item.source_cid) for item in entries
        )
        if (
            keys != tuple(sorted(keys))
            or len(keys) != len(set(keys))
            or len(source_keys) != len(set(source_keys))
            or len({item.entry_cid for item in entries}) != len(entries)
        ):
            raise ReviewedControlSafetyError(
                "reviewed-control entries must be sorted, unique cases and "
                "unique split/source classifications"
            )
        attestations = tuple(self.attestations)
        if (
            any(
                not isinstance(item, ReviewedControlAttestationV2)
                for item in attestations
            )
            or not attestations
        ):
            raise ReviewedControlSafetyError(
                "reviewed-control index requires typed attestations"
            )
        attestations = tuple(
            ReviewedControlAttestationV2.from_dict(item.to_dict())
            for item in attestations
        )
        attestation_cids = tuple(
            item.attestation_cid for item in attestations
        )
        if (
            attestation_cids != tuple(sorted(attestation_cids))
            or len(attestation_cids) != len(set(attestation_cids))
            or len(
                {item.classification_cid for item in attestations}
            )
            != len(attestations)
        ):
            raise ReviewedControlSafetyError(
                "reviewed-control attestations must be sorted and unique"
            )
        by_cid = {
            item.attestation_cid: item for item in attestations
        }
        if set(by_cid) != {
            item.review_attestation_cid for item in entries
        }:
            raise ReviewedControlSafetyError(
                "every reviewed control requires exactly one attestation"
            )
        for entry in entries:
            attestation = by_cid[entry.review_attestation_cid]
            if (
                attestation.classification_cid
                != entry.classification_cid
                or attestation.review_authority_cid
                != self.review_authority_cid
                or attestation.execution_authority_cid
                != self.execution_authority_cid
                or attestation.control_policy_cid
                != self.control_policy_cid
                or attestation.review_protocol_cid
                != self.review_protocol_cid
                or attestation.source_manifest_cid
                != entry.source_manifest_cid
                or attestation.rescue_manifest_cid
                != entry.rescue_manifest_cid
            ):
                raise ReviewedControlSafetyError(
                    "reviewed-control entry has a forged or stale attestation"
                )
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "attestations", attestations)

    @property
    def source_manifest_cids(self) -> tuple[str, ...]:
        return tuple(
            sorted({item.source_manifest_cid for item in self.entries})
        )

    @property
    def rescue_manifest_cids(self) -> tuple[str, ...]:
        return tuple(
            sorted({item.rescue_manifest_cid for item in self.entries})
        )

    @property
    def required_coordinate_count(self) -> int:
        return (
            len(self.entries)
            * len(G236_REQUIRED_VARIANT_IDS)
            * len(G236_REQUIRED_CACHE_MODES)
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "control_policy_cid": self.control_policy_cid,
            "review_protocol_cid": self.review_protocol_cid,
            "review_authority_cid": self.review_authority_cid,
            "execution_authority_cid": self.execution_authority_cid,
            "required_variant_ids": list(G236_REQUIRED_VARIANT_IDS),
            "required_cache_modes": [
                mode.value for mode in G236_REQUIRED_CACHE_MODES
            ],
            "source_manifest_cids": list(self.source_manifest_cids),
            "rescue_manifest_cids": list(self.rescue_manifest_cids),
            "entry_count": len(self.entries),
            "required_coordinate_count": self.required_coordinate_count,
            "entries": [item.to_dict() for item in self.entries],
            "attestations": [
                item.to_dict() for item in self.attestations
            ],
            "frozen": self.frozen,
            "holdout_included": self.holdout_included,
        }

    @property
    def index_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "index_cid": self.index_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "reviewed-control index")
        expected = {
            "schema",
            "control_policy_cid",
            "review_protocol_cid",
            "review_authority_cid",
            "execution_authority_cid",
            "required_variant_ids",
            "required_cache_modes",
            "source_manifest_cids",
            "rescue_manifest_cids",
            "entry_count",
            "required_coordinate_count",
            "entries",
            "attestations",
            "frozen",
            "holdout_included",
            "index_cid",
        }
        _exact(data, expected, "reviewed-control index")
        entries = _array(data["entries"], "reviewed-control entries")
        attestations = _array(
            data["attestations"],
            "reviewed-control attestations",
        )
        result = cls(
            schema=data["schema"],  # type: ignore[arg-type]
            control_policy_cid=data[
                "control_policy_cid"
            ],  # type: ignore[arg-type]
            review_protocol_cid=data[
                "review_protocol_cid"
            ],  # type: ignore[arg-type]
            review_authority_cid=data[
                "review_authority_cid"
            ],  # type: ignore[arg-type]
            execution_authority_cid=data[
                "execution_authority_cid"
            ],  # type: ignore[arg-type]
            entries=tuple(
                ReviewedControlEntryV2.from_dict(item)
                for item in entries
            ),
            attestations=tuple(
                ReviewedControlAttestationV2.from_dict(item)
                for item in attestations
            ),
            frozen=data["frozen"],  # type: ignore[arg-type]
            holdout_included=data[
                "holdout_included"
            ],  # type: ignore[arg-type]
        )
        if _plain(data) != result.to_dict():
            raise ReviewedControlSafetyError(
                "reviewed-control index derived fields or CID changed"
            )
        return result


def build_reviewed_control_index_v2(
    *,
    review_authority_cid: str,
    execution_authority_cid: str,
    entries: Sequence[ReviewedControlEntryV2],
    attestations: Sequence[ReviewedControlAttestationV2],
) -> ReviewedControlIndexV2:
    """Build a canonical index from externally reviewed typed records."""

    if isinstance(entries, (str, bytes)) or isinstance(
        attestations, (str, bytes)
    ):
        raise ReviewedControlSafetyError(
            "reviewed-control entries and attestations must be sequences"
        )
    try:
        ordered_entries = tuple(sorted(entries, key=_entry_key))
        ordered_attestations = tuple(
            sorted(attestations, key=lambda item: item.attestation_cid)
        )
    except (AttributeError, TypeError) as exc:
        raise ReviewedControlSafetyError(
            "reviewed-control index cannot accept caller classification claims"
        ) from exc
    return ReviewedControlIndexV2(
        review_authority_cid=review_authority_cid,
        execution_authority_cid=execution_authority_cid,
        entries=ordered_entries,
        attestations=ordered_attestations,
    )


def _required_coordinate_payload(
    entry: ReviewedControlEntryV2,
    variant_id: str,
    cache_mode: CacheMode,
) -> dict[str, object]:
    return {
        "schema": REVIEWED_CONTROL_COORDINATE_SCHEMA_V2,
        "control_policy_cid": REVIEWED_CONTROL_POLICY_V2_CID,
        "control_entry_cid": entry.entry_cid,
        "classification_cid": entry.classification_cid,
        "case_id": entry.case_id,
        "split": entry.split.value,
        "source_cid": entry.source_cid,
        "variant_id": variant_id,
        "cache_mode": cache_mode.value,
        "source_manifest_cid": entry.source_manifest_cid,
        "rescue_manifest_cid": entry.rescue_manifest_cid,
        "holdout_included": False,
    }


def _required_coordinates(
    index: ReviewedControlIndexV2,
) -> dict[
    tuple[str, str, str, str],
    tuple[ReviewedControlEntryV2, str, dict[str, object]],
]:
    result: dict[
        tuple[str, str, str, str],
        tuple[ReviewedControlEntryV2, str, dict[str, object]],
    ] = {}
    for entry in index.entries:
        for variant_id in G236_REQUIRED_VARIANT_IDS:
            for cache_mode in G236_REQUIRED_CACHE_MODES:
                payload = _required_coordinate_payload(
                    entry,
                    variant_id,
                    cache_mode,
                )
                key = (
                    entry.split.value,
                    entry.case_id,
                    variant_id,
                    cache_mode.value,
                )
                result[key] = (
                    entry,
                    cid_for_dag_json(payload),
                    payload,
                )
    return result


def _runtime_coordinate(
    evidence: CausalRuntimeEvidenceV2,
) -> tuple[str, str, str, str]:
    result = evidence.case_result
    return (
        result.split.value,
        result.case_id,
        result.variant_id,
        result.cache_mode.value,
    )


def _replay_index(value: object) -> ReviewedControlIndexV2:
    if not isinstance(value, ReviewedControlIndexV2):
        raise ReviewedControlSafetyError(
            "G236 requires a typed independently reviewed control index; "
            "caller-asserted classifications are forbidden"
        )
    return ReviewedControlIndexV2.from_dict(value.to_dict())


def build_reviewed_control_safety_gate_v2(
    control_index: ReviewedControlIndexV2,
    rescue_manifests: Sequence[CausalRescueManifestV2],
    runtime_evidence: Sequence[CausalRuntimeEvidenceV2],
) -> Mapping[str, object]:
    """Recompute the fatal invalid-control gate from exact native receipts."""

    index = _replay_index(control_index)
    issues: set[str] = set()

    try:
        raw_manifests = tuple(rescue_manifests)
    except TypeError:
        raw_manifests = ()
        issues.add("rescue_manifest_set_not_a_sequence")
    manifests: list[CausalRescueManifestV2] = []
    for value in raw_manifests:
        if not isinstance(value, CausalRescueManifestV2):
            issues.add("rescue_manifest_failed_typed_replay")
            continue
        try:
            manifests.append(
                CausalRescueManifestV2.from_dict(value.to_dict())
            )
        except (TypeError, ValueError, KeyError):
            issues.add("rescue_manifest_failed_typed_replay")
    manifest_cids = tuple(item.manifest_cid for item in manifests)
    if len(manifest_cids) != len(set(manifest_cids)):
        issues.add("duplicate_rescue_manifest")
    presented_rescue_manifest_cids = tuple(sorted(set(manifest_cids)))
    presented_source_manifest_cids = tuple(
        sorted({item.source_manifest_cid for item in manifests})
    )
    if set(presented_rescue_manifest_cids) != set(
        index.rescue_manifest_cids
    ) or set(presented_source_manifest_cids) != set(
        index.source_manifest_cids
    ):
        issues.add("control_manifest_set_mismatch")
    manifests_by_cid = {
        item.manifest_cid: item for item in manifests
    }
    manifest_cases: dict[
        tuple[str, str], tuple[CausalRescueManifestV2, object]
    ] = {}
    for entry in index.entries:
        manifest = manifests_by_cid.get(entry.rescue_manifest_cid)
        case = (
            None
            if manifest is None
            else next(
                (
                    item
                    for item in manifest.cases
                    if item.case_id == entry.case_id
                ),
                None,
            )
        )
        if (
            manifest is None
            or case is None
            or manifest.source_manifest_cid
            != entry.source_manifest_cid
            or case.split is not entry.split
            or case.source_cid != entry.source_cid
        ):
            issues.add("control_index_manifest_binding_mismatch")
            continue
        manifest_cases[(entry.split.value, entry.case_id)] = (
            manifest,
            case,
        )

    required = _required_coordinates(index)
    required_coordinate_cids = tuple(
        sorted(value[1] for value in required.values())
    )
    evidence_by_coordinate: dict[
        tuple[str, str, str, str],
        list[CausalRuntimeEvidenceV2],
    ] = {}
    replayed_receipt_cids: list[str] = []
    unexpected_receipt_cids: set[str] = set()
    try:
        raw_runtime = tuple(runtime_evidence)
    except TypeError:
        raw_runtime = ()
        issues.add("runtime_evidence_set_not_a_sequence")
    for value in raw_runtime:
        if not isinstance(value, CausalRuntimeEvidenceV2):
            issues.add("runtime_evidence_not_full_typed_receipt")
            continue
        try:
            replayed = validate_causal_runtime_evidence_v2(
                value.to_dict()
            )
        except (TypeError, ValueError, KeyError):
            issues.add("runtime_evidence_failed_typed_replay")
            continue
        replayed_receipt_cids.append(replayed.receipt_cid)
        coordinate = _runtime_coordinate(replayed)
        evidence_by_coordinate.setdefault(coordinate, []).append(replayed)
        if coordinate not in required:
            unexpected_receipt_cids.add(replayed.receipt_cid)
            issues.add("runtime_coordinate_has_no_reviewed_classification")
    if len(replayed_receipt_cids) != len(set(replayed_receipt_cids)):
        issues.add("duplicate_runtime_evidence_receipt")
    if any(
        len(values) != 1 for values in evidence_by_coordinate.values()
    ):
        issues.add("duplicate_runtime_coordinate")

    observations_by_coordinate_cid: dict[
        str, Mapping[str, object]
    ] = {}
    accepted_runtime_receipt_cids: set[str] = set()
    missing_coordinate_cids: set[str] = set()
    observed_run_ids: set[str] = set()
    for key, (entry, coordinate_cid, _payload) in required.items():
        values = evidence_by_coordinate.get(key, [])
        if not values:
            missing_coordinate_cids.add(coordinate_cid)
            continue
        for evidence in values:
            manifest_case = manifest_cases.get(
                (entry.split.value, entry.case_id)
            )
            result = evidence.case_result
            if manifest_case is None:
                issues.add("runtime_control_manifest_binding_mismatch")
                continue
            manifest, raw_case = manifest_case
            case = raw_case
            if (
                evidence.compiler_exposure.source_cid
                != entry.source_cid
                or result.case_id != entry.case_id
                or result.split is not entry.split
                or result.variant_id != key[2]
                or result.cache_mode.value != key[3]
                or result.case_manifest_sha256
                != manifest.case_manifest_sha256
                or _plain(evidence.proof_context)
                != _plain(case.proof_context)
            ):
                issues.add("runtime_control_source_binding_mismatch")
                continue
            observed_run_ids.add(result.run_id)
            terminal = result.stages[-1]
            if (
                terminal.stage is not StageName.KERNEL
                or terminal.provenance.effective_identity.get(
                    "graph_invoked"
                )
                is not True
            ):
                issues.add("terminal_native_kernel_receipt_missing")
                continue
            try:
                accepted = validate_native_kernel_stage_receipt(
                    terminal
                )
            except (ProtocolContractError, TypeError, ValueError):
                issues.add("terminal_native_kernel_receipt_invalid")
                continue
            native_receipt_cid = cid_for_dag_json(_plain(terminal.data))
            observation = {
                "coordinate_cid": coordinate_cid,
                "control_entry_cid": entry.entry_cid,
                "classification_cid": entry.classification_cid,
                "runtime_evidence_cid": evidence.receipt_cid,
                "terminal_native_kernel_receipt_cid": (
                    native_receipt_cid
                ),
                "terminal_native_kernel_accepted": accepted,
            }
            previous = observations_by_coordinate_cid.setdefault(
                coordinate_cid,
                MappingProxyType(observation),
            )
            if _plain(previous) != observation:
                issues.add("duplicate_runtime_coordinate")
            if accepted:
                accepted_runtime_receipt_cids.add(
                    evidence.receipt_cid
                )
    if len(observed_run_ids) > 1:
        issues.add("runtime_run_identity_mismatch")
    observed_coordinate_cids = set(observations_by_coordinate_cid)
    missing_coordinate_cids.update(
        set(required_coordinate_cids) - observed_coordinate_cids
    )
    if missing_coordinate_cids:
        issues.add("required_runtime_coordinate_missing")
    if (
        not index.entries
        or not required_coordinate_cids
        or len(observed_coordinate_cids)
        != len(required_coordinate_cids)
    ):
        issues.add("invalid_control_population_not_fully_observed")

    fatal = bool(accepted_runtime_receipt_cids)
    if fatal:
        issues.add("invalid_control_terminal_native_kernel_acceptance")
    incomplete_issues = issues - {
        "invalid_control_terminal_native_kernel_acceptance"
    }
    complete = not incomplete_issues
    passed = complete and not fatal
    status = "failed" if fatal else ("passed" if passed else "incomplete")
    observations = tuple(
        _plain(observations_by_coordinate_cid[cid])
        for cid in sorted(observations_by_coordinate_cid)
    )
    runtime_set_body = {
        "schema": REVIEWED_CONTROL_RUNTIME_SET_SCHEMA_V2,
        "control_index_cid": index.index_cid,
        "runtime_evidence_cids": sorted(replayed_receipt_cids),
    }
    body = {
        "schema": REVIEWED_CONTROL_SAFETY_GATE_SCHEMA_V2,
        "control_policy_cid": REVIEWED_CONTROL_POLICY_V2_CID,
        "review_protocol_cid": (
            REVIEWED_CONTROL_REVIEW_PROTOCOL_V2_CID
        ),
        "control_index_cid": index.index_cid,
        "review_authority_cid": index.review_authority_cid,
        "execution_authority_cid": index.execution_authority_cid,
        "source_manifest_cids": list(index.source_manifest_cids),
        "rescue_manifest_cids": list(index.rescue_manifest_cids),
        "presented_source_manifest_cids": list(
            presented_source_manifest_cids
        ),
        "presented_rescue_manifest_cids": list(
            presented_rescue_manifest_cids
        ),
        "runtime_evidence_set_cid": cid_for_dag_json(runtime_set_body),
        "required_coordinate_count": len(required_coordinate_cids),
        "required_coordinate_cids": list(required_coordinate_cids),
        "observed_coordinate_count": len(observations),
        "observations": list(observations),
        "missing_coordinate_cids": sorted(missing_coordinate_cids),
        "unexpected_runtime_evidence_cids": sorted(
            unexpected_receipt_cids
        ),
        "invalid_control_case_count": len(index.entries),
        "invalid_control_population_nonempty": bool(index.entries),
        "fully_observed": complete,
        "terminal_independent_native_kernel_acceptance_count": len(
            accepted_runtime_receipt_cids
        ),
        "accepted_runtime_evidence_cids": sorted(
            accepted_runtime_receipt_cids
        ),
        "failure_codes": sorted(issues),
        "complete": complete,
        "passed": passed,
        "fatal": fatal,
        "status": status,
        "holdout_included": False,
    }
    receipt = {
        **body,
        "receipt_cid": cid_for_dag_json(body),
    }
    frozen = _freeze(receipt)
    assert isinstance(frozen, Mapping)
    return frozen


def validate_reviewed_control_safety_gate_v2(
    value: object,
    control_index: ReviewedControlIndexV2,
    rescue_manifests: Sequence[CausalRescueManifestV2],
    runtime_evidence: Sequence[CausalRuntimeEvidenceV2],
) -> Mapping[str, object]:
    """Source-recompute a G236 gate and reject all caller-derived fields."""

    data = _mapping(value, "reviewed-control safety gate")
    expected = set(
        build_reviewed_control_safety_gate_v2(
            control_index,
            rescue_manifests,
            runtime_evidence,
        )
    )
    _exact(data, expected, "reviewed-control safety gate")
    rebuilt = build_reviewed_control_safety_gate_v2(
        control_index,
        rescue_manifests,
        runtime_evidence,
    )
    if _plain(data) != _plain(rebuilt):
        raise ReviewedControlSafetyError(
            "reviewed-control safety gate contains caller-asserted fields"
        )
    body = {
        key: _plain(member)
        for key, member in data.items()
        if key != "receipt_cid"
    }
    if data["receipt_cid"] != cid_for_dag_json(body):
        raise ReviewedControlSafetyError(
            "reviewed-control safety gate receipt CID changed"
        )
    return rebuilt


__all__ = [
    "G236_REQUIRED_CACHE_MODES",
    "G236_REQUIRED_VARIANT_IDS",
    "HSSLEV2367D38",
    "REVIEWED_CONTROL_ATTESTATION_SCHEMA_V2",
    "REVIEWED_CONTROL_CLASSIFICATION_SCHEMA_V2",
    "REVIEWED_CONTROL_ENTRY_SCHEMA_V2",
    "REVIEWED_CONTROL_INDEX_SCHEMA_V2",
    "REVIEWED_CONTROL_POLICY_V2_CID",
    "REVIEWED_CONTROL_REVIEW_PROTOCOL_V2_CID",
    "REVIEWED_CONTROL_SAFETY_GATE_SCHEMA_V2",
    "ReviewedControlAttestationV2",
    "ReviewedControlEntryV2",
    "ReviewedControlIndexV2",
    "ReviewedControlSafetyError",
    "build_reviewed_control_index_v2",
    "build_reviewed_control_safety_gate_v2",
    "reviewed_control_policy_v2",
    "reviewed_control_review_protocol_v2",
    "validate_reviewed_control_safety_gate_v2",
]
