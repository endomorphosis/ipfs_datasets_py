"""Fail-closed authorized execution for the frozen paired holdout.

The generic ablation executor deliberately refuses ``Split.HOLDOUT``.  This
module is the only supported bridge across that boundary.  It validates a
content-addressed, source-bound pilot authorization and every per-contract
holdout access audit before it creates a file or invokes an adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

from .ablation import (
    AblationPlan,
    AblationRunResult,
    ResourceLimits,
    _execute_ablation,
    build_ablation_plan,
)
from .capabilities import ResourceScheduler
from .cases import (
    HoldoutAccessAudit,
    ReplacementHoldoutSeal,
    ReviewedCorpus,
    build_split_integrity_manifest,
    replacement_holdout_ledger_authority_cid,
    validate_holdout_access_log,
    validate_replacement_holdout_external_path,
)
from .content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)
from .contracts import (
    DEFAULT_PROTOCOL_SHA256,
    CacheMode,
    Split,
    canonical_json,
)
from .variants import VARIANT_REGISTRY, get_variant_definition


PILOT_AUTHORIZATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.pilot-holdout-authorization.v1"
)
HOLDOUT_EXECUTION_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.authorized-holdout-execution.v1"
)
HOLDOUT_AUTHORIZATION_FILE: Final = "holdout-authorization.json"
HOLDOUT_EXECUTION_RECEIPT_FILE: Final = "holdout-execution-receipt.json"
HOLDOUT_ACCESS_AUDITS_FILE: Final = "holdout-access-audits.json"
MAX_SHORTLIST_SIZE: Final = 4
G230_REPLACEMENT_HOLDOUT_AUTHORIZATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g230-replacement-holdout-authorization.v2"
)
REPLACEMENT_HOLDOUT_ACCESS_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "replacement-holdout-access-receipt.v2"
)
REPLACEMENT_HOLDOUT_ACCESS_LEDGER_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "replacement-holdout-access-ledger.v2"
)
REPLACEMENT_HOLDOUT_AUTHORIZED_PROTOCOL_KEYS: Final = frozenset(
    {"causal_proof", "holdout_execution", "semantic"}
)
REPLACEMENT_HOLDOUT_ACCESS_EVENTS: Final = frozenset(
    {
        "access_granted",
        "custody_integrity_failure",
        "custody_release_failed",
        "manifest_released",
        "premature_access",
    }
)
_SAFE_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_DIGEST: Final = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT: Final = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")


class HoldoutExecutionError(ValueError):
    """Raised before an unauthorized or drifted holdout can execute."""


def HSSLEV1167A17() -> str:
    """Return AST-verifiable evidence for authorized holdout and replay."""

    return (
        "source-bound fail-closed holdout authorization and fresh detached "
        "replay orchestration with isolated run, process, and cache namespaces"
    )


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise HoldoutExecutionError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _commit(value: object, field: str) -> str:
    if not isinstance(value, str) or not _COMMIT.fullmatch(value):
        raise HoldoutExecutionError(
            f"{field} must be a full lowercase Git commit id"
        )
    return value


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise HoldoutExecutionError(f"{field} must be a safe nonempty identifier")
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise HoldoutExecutionError(f"{field} must be an object with string keys")
    return value


def _exact(
    value: Mapping[str, object], expected: set[str], field: str
) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise HoldoutExecutionError(
            f"{field} fields changed (missing={missing}, extra={extra})"
        )


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _cid(
    value: object,
    field: str,
    *,
    codecs: tuple[str, ...],
) -> str:
    try:
        return validate_cid(value, codecs=codecs)
    except (TypeError, ValueError) as exc:
        raise HoldoutExecutionError(
            f"{field} must be a canonical CIDv1/base32/sha2-256 "
            f"using one of {codecs!r}"
        ) from exc


def _authorization_payload(
    *,
    schema: str,
    authorization_id: str,
    pilot_run_id: str,
    pilot_gate_sha256: str,
    source_commit: str,
    environment_sha256: str,
    protocol_sha256: str,
    corpus_manifest_sha256: str,
    holdout_split_sha256: str,
    shortlist_variant_ids: tuple[str, ...],
    configuration_sha256s: Mapping[str, str],
    prompts_sha256: str,
    policy_sha256: str,
    model_identities_sha256: str,
    thresholds_sha256: str,
    passed: bool,
    shortlist_frozen: bool,
    holdout_authorized: bool,
    outcomes_inspected: bool,
    tuning_permitted: bool,
) -> dict[str, object]:
    return {
        "schema": schema,
        "authorization_id": authorization_id,
        "pilot_run_id": pilot_run_id,
        "pilot_gate_sha256": pilot_gate_sha256,
        "source_commit": source_commit,
        "environment_sha256": environment_sha256,
        "protocol_sha256": protocol_sha256,
        "corpus_manifest_sha256": corpus_manifest_sha256,
        "holdout_split_sha256": holdout_split_sha256,
        "shortlist_variant_ids": list(shortlist_variant_ids),
        "configuration_sha256s": dict(configuration_sha256s),
        "prompts_sha256": prompts_sha256,
        "policy_sha256": policy_sha256,
        "model_identities_sha256": model_identities_sha256,
        "thresholds_sha256": thresholds_sha256,
        "passed": passed,
        "shortlist_frozen": shortlist_frozen,
        "holdout_authorized": holdout_authorized,
        "outcomes_inspected": outcomes_inspected,
        "tuning_permitted": tuning_permitted,
    }


@dataclass(frozen=True, slots=True)
class PilotAuthorizationReceipt:
    """Immutable handoff from a completed source-bound pilot gate."""

    schema: str
    authorization_id: str
    pilot_run_id: str
    pilot_gate_sha256: str
    source_commit: str
    environment_sha256: str
    protocol_sha256: str
    corpus_manifest_sha256: str
    holdout_split_sha256: str
    shortlist_variant_ids: tuple[str, ...]
    configuration_sha256s: Mapping[str, str]
    prompts_sha256: str
    policy_sha256: str
    model_identities_sha256: str
    thresholds_sha256: str
    passed: bool
    shortlist_frozen: bool
    holdout_authorized: bool
    outcomes_inspected: bool
    tuning_permitted: bool
    authorization_sha256: str

    def __post_init__(self) -> None:
        if self.schema != PILOT_AUTHORIZATION_SCHEMA:
            raise HoldoutExecutionError("unsupported pilot authorization schema")
        _safe_id(self.authorization_id, "authorization_id")
        _safe_id(self.pilot_run_id, "pilot_run_id")
        _digest(self.pilot_gate_sha256, "pilot_gate_sha256")
        _commit(self.source_commit, "source_commit")
        for name in (
            "environment_sha256",
            "protocol_sha256",
            "corpus_manifest_sha256",
            "holdout_split_sha256",
            "prompts_sha256",
            "policy_sha256",
            "model_identities_sha256",
            "thresholds_sha256",
            "authorization_sha256",
        ):
            _digest(getattr(self, name), name)
        if self.protocol_sha256 != DEFAULT_PROTOCOL_SHA256:
            raise HoldoutExecutionError(
                "authorization does not bind frozen protocol revision 1"
            )
        shortlist = tuple(self.shortlist_variant_ids)
        if (
            not shortlist
            or len(shortlist) > MAX_SHORTLIST_SIZE
            or len(shortlist) != len(set(shortlist))
            or any(
                item not in VARIANT_REGISTRY or item in {"A0", "S1"}
                for item in shortlist
            )
        ):
            raise HoldoutExecutionError(
                "shortlist must contain one to four distinct candidate arms"
            )
        object.__setattr__(self, "shortlist_variant_ids", shortlist)
        configurations = _mapping(
            self.configuration_sha256s, "configuration_sha256s"
        )
        expected_variants = {"A0", *shortlist}
        if set(configurations) != expected_variants:
            raise HoldoutExecutionError(
                "authorization configurations must exactly cover A0 and shortlist"
            )
        normalized: dict[str, str] = {}
        for variant_id, value in configurations.items():
            digest = _digest(value, f"configuration_sha256s.{variant_id}")
            if digest != get_variant_definition(variant_id).digest:
                raise HoldoutExecutionError(
                    f"frozen configuration drifted for {variant_id}"
                )
            normalized[variant_id] = digest
        object.__setattr__(
            self,
            "configuration_sha256s",
            MappingProxyType(dict(sorted(normalized.items()))),
        )
        for name, expected in (
            ("passed", True),
            ("shortlist_frozen", True),
            ("holdout_authorized", True),
            ("outcomes_inspected", False),
            ("tuning_permitted", False),
        ):
            if getattr(self, name) is not expected:
                raise HoldoutExecutionError(
                    f"pilot authorization requires {name}={expected!r}"
                )
        if self.authorization_sha256 != _sha(self.identity_payload()):
            raise HoldoutExecutionError(
                "authorization_sha256 does not match authorization content"
            )

    def identity_payload(self) -> dict[str, object]:
        return _authorization_payload(
            schema=self.schema,
            authorization_id=self.authorization_id,
            pilot_run_id=self.pilot_run_id,
            pilot_gate_sha256=self.pilot_gate_sha256,
            source_commit=self.source_commit,
            environment_sha256=self.environment_sha256,
            protocol_sha256=self.protocol_sha256,
            corpus_manifest_sha256=self.corpus_manifest_sha256,
            holdout_split_sha256=self.holdout_split_sha256,
            shortlist_variant_ids=self.shortlist_variant_ids,
            configuration_sha256s=self.configuration_sha256s,
            prompts_sha256=self.prompts_sha256,
            policy_sha256=self.policy_sha256,
            model_identities_sha256=self.model_identities_sha256,
            thresholds_sha256=self.thresholds_sha256,
            passed=self.passed,
            shortlist_frozen=self.shortlist_frozen,
            holdout_authorized=self.holdout_authorized,
            outcomes_inspected=self.outcomes_inspected,
            tuning_permitted=self.tuning_permitted,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "authorization_sha256": self.authorization_sha256,
        }

    @classmethod
    def create(
        cls,
        *,
        authorization_id: str,
        pilot_run_id: str,
        pilot_gate_sha256: str,
        source_commit: str,
        environment_sha256: str,
        corpus_manifest_sha256: str,
        holdout_split_sha256: str,
        shortlist_variant_ids: Sequence[str],
        prompts_sha256: str,
        policy_sha256: str,
        model_identities_sha256: str,
        thresholds_sha256: str,
        protocol_sha256: str = DEFAULT_PROTOCOL_SHA256,
    ) -> "PilotAuthorizationReceipt":
        """Create the strict handoff after an upstream pilot validator passes."""

        shortlist = tuple(shortlist_variant_ids)
        configurations = {
            variant_id: get_variant_definition(variant_id).digest
            for variant_id in ("A0", *shortlist)
            if variant_id in VARIANT_REGISTRY
        }
        payload = _authorization_payload(
            schema=PILOT_AUTHORIZATION_SCHEMA,
            authorization_id=authorization_id,
            pilot_run_id=pilot_run_id,
            pilot_gate_sha256=pilot_gate_sha256,
            source_commit=source_commit,
            environment_sha256=environment_sha256,
            protocol_sha256=protocol_sha256,
            corpus_manifest_sha256=corpus_manifest_sha256,
            holdout_split_sha256=holdout_split_sha256,
            shortlist_variant_ids=shortlist,
            configuration_sha256s=configurations,
            prompts_sha256=prompts_sha256,
            policy_sha256=policy_sha256,
            model_identities_sha256=model_identities_sha256,
            thresholds_sha256=thresholds_sha256,
            passed=True,
            shortlist_frozen=True,
            holdout_authorized=True,
            outcomes_inspected=False,
            tuning_permitted=False,
        )
        return cls(
            **payload,  # type: ignore[arg-type]
            authorization_sha256=_sha(payload),
        )

    @classmethod
    def from_dict(cls, value: object) -> "PilotAuthorizationReceipt":
        data = _mapping(value, "pilot authorization")
        _exact(data, set(cls.__dataclass_fields__), "pilot authorization")
        shortlist = data["shortlist_variant_ids"]
        if not isinstance(shortlist, list):
            raise HoldoutExecutionError("shortlist_variant_ids must be an array")
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            authorization_id=data["authorization_id"],  # type: ignore[arg-type]
            pilot_run_id=data["pilot_run_id"],  # type: ignore[arg-type]
            pilot_gate_sha256=data["pilot_gate_sha256"],  # type: ignore[arg-type]
            source_commit=data["source_commit"],  # type: ignore[arg-type]
            environment_sha256=data["environment_sha256"],  # type: ignore[arg-type]
            protocol_sha256=data["protocol_sha256"],  # type: ignore[arg-type]
            corpus_manifest_sha256=data["corpus_manifest_sha256"],  # type: ignore[arg-type]
            holdout_split_sha256=data["holdout_split_sha256"],  # type: ignore[arg-type]
            shortlist_variant_ids=tuple(shortlist),  # type: ignore[arg-type]
            configuration_sha256s=_mapping(
                data["configuration_sha256s"], "configuration_sha256s"
            ),  # type: ignore[arg-type]
            prompts_sha256=data["prompts_sha256"],  # type: ignore[arg-type]
            policy_sha256=data["policy_sha256"],  # type: ignore[arg-type]
            model_identities_sha256=data["model_identities_sha256"],  # type: ignore[arg-type]
            thresholds_sha256=data["thresholds_sha256"],  # type: ignore[arg-type]
            passed=data["passed"],  # type: ignore[arg-type]
            shortlist_frozen=data["shortlist_frozen"],  # type: ignore[arg-type]
            holdout_authorized=data["holdout_authorized"],  # type: ignore[arg-type]
            outcomes_inspected=data["outcomes_inspected"],  # type: ignore[arg-type]
            tuning_permitted=data["tuning_permitted"],  # type: ignore[arg-type]
            authorization_sha256=data["authorization_sha256"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class G230ReplacementHoldoutAuthorization:
    """Fail-closed HSSL-G230 handoff for one exact replacement seal.

    The content address proves identity, not authority.  The external
    custodian remains the trust root and must independently allow this exact
    ``authorization_cid`` before releasing bytes.  There is intentionally no
    convenience constructor that turns local benchmark state into an
    authorization.
    """

    schema: str
    goal_id: str
    pilot_artifact_cid: str
    seal_contract_cid: str
    sealed_manifest_cid: str
    protocol_cids: Mapping[str, str]
    source_commit: str
    authorized_variant_ids: tuple[str, ...]
    cache_modes: tuple[str, ...]
    passed: bool
    complete: bool
    shortlist_frozen: bool
    holdout_authorized: bool
    outcomes_inspected: bool
    tuning_permitted: bool
    authorization_cid: str

    def __post_init__(self) -> None:
        if self.schema != G230_REPLACEMENT_HOLDOUT_AUTHORIZATION_SCHEMA:
            raise HoldoutExecutionError(
                "unsupported G230 replacement-holdout authorization schema"
            )
        if self.goal_id != "HSSL-G230":
            raise HoldoutExecutionError(
                "replacement-holdout authorization must come from HSSL-G230"
            )
        object.__setattr__(
            self,
            "pilot_artifact_cid",
            _cid(
                self.pilot_artifact_cid,
                "pilot_artifact_cid",
                codecs=("dag-json",),
            ),
        )
        object.__setattr__(
            self,
            "seal_contract_cid",
            _cid(
                self.seal_contract_cid,
                "seal_contract_cid",
                codecs=("dag-json",),
            ),
        )
        object.__setattr__(
            self,
            "sealed_manifest_cid",
            _cid(
                self.sealed_manifest_cid,
                "sealed_manifest_cid",
                codecs=("raw",),
            ),
        )
        protocols = _mapping(self.protocol_cids, "protocol_cids")
        if set(protocols) != REPLACEMENT_HOLDOUT_AUTHORIZED_PROTOCOL_KEYS:
            raise HoldoutExecutionError(
                "G230 authorization protocol identities must exactly bind "
                f"{sorted(REPLACEMENT_HOLDOUT_AUTHORIZED_PROTOCOL_KEYS)!r}"
            )
        normalized_protocols = {
            key: _cid(
                protocols[key],
                f"protocol_cids.{key}",
                codecs=("dag-json",),
            )
            for key in sorted(protocols)
        }
        object.__setattr__(
            self,
            "protocol_cids",
            MappingProxyType(normalized_protocols),
        )
        object.__setattr__(
            self,
            "source_commit",
            _commit(self.source_commit, "source_commit"),
        )

        variants = tuple(
            _safe_id(value, "authorized_variant_ids[]")
            for value in self.authorized_variant_ids
        )
        candidates = variants[1:] if variants else ()
        if (
            not variants
            or variants[0] != "A0"
            or not candidates
            or len(candidates) > MAX_SHORTLIST_SIZE
            or len(variants) != len(set(variants))
            or any(
                variant_id not in VARIANT_REGISTRY
                or variant_id in {"A0", "S1"}
                for variant_id in candidates
            )
        ):
            raise HoldoutExecutionError(
                "G230 authorization must contain A0 followed by one to four "
                "distinct registered candidate arms"
            )
        object.__setattr__(self, "authorized_variant_ids", variants)
        cache_modes = tuple(self.cache_modes)
        if cache_modes != ("cold", "warm"):
            raise HoldoutExecutionError(
                "G230 authorization must preserve exact cold/warm pairing"
            )
        object.__setattr__(self, "cache_modes", cache_modes)
        for name, expected in (
            ("passed", True),
            ("complete", True),
            ("shortlist_frozen", True),
            ("holdout_authorized", True),
            ("outcomes_inspected", False),
            ("tuning_permitted", False),
        ):
            if getattr(self, name) is not expected:
                raise HoldoutExecutionError(
                    f"G230 authorization requires {name}={expected!r}"
                )
        object.__setattr__(
            self,
            "authorization_cid",
            _cid(
                self.authorization_cid,
                "authorization_cid",
                codecs=("dag-json",),
            ),
        )
        if self.authorization_cid != cid_for_dag_json(
            self.identity_payload()
        ):
            raise HoldoutExecutionError(
                "authorization_cid does not match G230 authorization content"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal_id": self.goal_id,
            "pilot_artifact_cid": self.pilot_artifact_cid,
            "seal_contract_cid": self.seal_contract_cid,
            "sealed_manifest_cid": self.sealed_manifest_cid,
            "protocol_cids": dict(self.protocol_cids),
            "source_commit": self.source_commit,
            "authorized_variant_ids": list(self.authorized_variant_ids),
            "cache_modes": list(self.cache_modes),
            "passed": self.passed,
            "complete": self.complete,
            "shortlist_frozen": self.shortlist_frozen,
            "holdout_authorized": self.holdout_authorized,
            "outcomes_inspected": self.outcomes_inspected,
            "tuning_permitted": self.tuning_permitted,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "authorization_cid": self.authorization_cid,
        }

    def validate_against(self, seal: ReplacementHoldoutSeal) -> None:
        if not isinstance(seal, ReplacementHoldoutSeal):
            raise HoldoutExecutionError(
                "G230 authorization requires a replacement holdout seal"
            )
        if (
            self.seal_contract_cid != seal.seal_contract_cid
            or self.sealed_manifest_cid != seal.sealed_manifest_cid
            or any(
                self.protocol_cids[key] != seal.protocol_cids[key]
                for key in REPLACEMENT_HOLDOUT_AUTHORIZED_PROTOCOL_KEYS
            )
        ):
            raise HoldoutExecutionError(
                "G230 authorization does not bind the exact replacement seal "
                "and frozen protocols"
            )

    @classmethod
    def from_dict(cls, value: object) -> "G230ReplacementHoldoutAuthorization":
        data = _mapping(value, "G230 replacement-holdout authorization")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G230 replacement-holdout authorization",
        )
        variants = data["authorized_variant_ids"]
        cache_modes = data["cache_modes"]
        if not isinstance(variants, list) or not isinstance(cache_modes, list):
            raise HoldoutExecutionError(
                "G230 authorized variants and cache modes must be arrays"
            )
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            goal_id=data["goal_id"],  # type: ignore[arg-type]
            pilot_artifact_cid=data["pilot_artifact_cid"],  # type: ignore[arg-type]
            seal_contract_cid=data["seal_contract_cid"],  # type: ignore[arg-type]
            sealed_manifest_cid=data["sealed_manifest_cid"],  # type: ignore[arg-type]
            protocol_cids=_mapping(
                data["protocol_cids"], "protocol_cids"
            ),  # type: ignore[arg-type]
            source_commit=data["source_commit"],  # type: ignore[arg-type]
            authorized_variant_ids=tuple(variants),  # type: ignore[arg-type]
            cache_modes=tuple(cache_modes),  # type: ignore[arg-type]
            passed=data["passed"],  # type: ignore[arg-type]
            complete=data["complete"],  # type: ignore[arg-type]
            shortlist_frozen=data["shortlist_frozen"],  # type: ignore[arg-type]
            holdout_authorized=data["holdout_authorized"],  # type: ignore[arg-type]
            outcomes_inspected=data["outcomes_inspected"],  # type: ignore[arg-type]
            tuning_permitted=data["tuning_permitted"],  # type: ignore[arg-type]
            authorization_cid=data["authorization_cid"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class ReplacementHoldoutAccessReceipt:
    """One CID-addressed event in the append-only replacement access chain."""

    schema: str
    sequence: int
    previous_receipt_cid: str | None
    event: str
    seal_contract_cid: str
    sealed_manifest_cid: str
    authorization_cid: str | None
    pilot_artifact_cid: str | None
    purpose: str
    executor_id: str
    access_authorized: bool
    manifest_released: bool
    invalidates_seal: bool
    receipt_cid: str

    def __post_init__(self) -> None:
        if self.schema != REPLACEMENT_HOLDOUT_ACCESS_RECEIPT_SCHEMA:
            raise HoldoutExecutionError(
                "unsupported replacement-holdout access receipt schema"
            )
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise HoldoutExecutionError(
                "replacement access sequence must be a nonnegative integer"
            )
        if self.sequence == 0:
            if self.previous_receipt_cid is not None:
                raise HoldoutExecutionError(
                    "genesis replacement access receipt cannot have a parent"
                )
        else:
            object.__setattr__(
                self,
                "previous_receipt_cid",
                _cid(
                    self.previous_receipt_cid,
                    "previous_receipt_cid",
                    codecs=("dag-json",),
                ),
            )
        if self.event not in REPLACEMENT_HOLDOUT_ACCESS_EVENTS:
            raise HoldoutExecutionError(
                "unsupported replacement-holdout access event"
            )
        object.__setattr__(
            self,
            "seal_contract_cid",
            _cid(
                self.seal_contract_cid,
                "seal_contract_cid",
                codecs=("dag-json",),
            ),
        )
        object.__setattr__(
            self,
            "sealed_manifest_cid",
            _cid(
                self.sealed_manifest_cid,
                "sealed_manifest_cid",
                codecs=("raw",),
            ),
        )
        if (self.authorization_cid is None) != (
            self.pilot_artifact_cid is None
        ):
            raise HoldoutExecutionError(
                "authorization and pilot CIDs must be both present or absent"
            )
        if self.authorization_cid is not None:
            object.__setattr__(
                self,
                "authorization_cid",
                _cid(
                    self.authorization_cid,
                    "authorization_cid",
                    codecs=("dag-json",),
                ),
            )
            object.__setattr__(
                self,
                "pilot_artifact_cid",
                _cid(
                    self.pilot_artifact_cid,
                    "pilot_artifact_cid",
                    codecs=("dag-json",),
                ),
            )
        if self.purpose not in {"evaluation", "replay"}:
            raise HoldoutExecutionError(
                "replacement holdout purpose must be evaluation or replay"
            )
        _safe_id(self.executor_id, "executor_id")
        expected_flags = {
            "access_granted": (True, False, False),
            "custody_integrity_failure": (True, True, True),
            "custody_release_failed": (True, False, False),
            "manifest_released": (True, True, False),
            "premature_access": (False, False, True),
        }[self.event]
        actual_flags = (
            self.access_authorized,
            self.manifest_released,
            self.invalidates_seal,
        )
        if (
            any(type(value) is not bool for value in actual_flags)
            or actual_flags != expected_flags
            or (
                self.event != "premature_access"
                and self.authorization_cid is None
            )
        ):
            raise HoldoutExecutionError(
                "replacement access event flags are inconsistent"
            )
        object.__setattr__(
            self,
            "receipt_cid",
            _cid(
                self.receipt_cid,
                "receipt_cid",
                codecs=("dag-json",),
            ),
        )
        if self.receipt_cid != cid_for_dag_json(self.identity_payload()):
            raise HoldoutExecutionError(
                "receipt_cid does not match replacement access event"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "sequence": self.sequence,
            "previous_receipt_cid": self.previous_receipt_cid,
            "event": self.event,
            "seal_contract_cid": self.seal_contract_cid,
            "sealed_manifest_cid": self.sealed_manifest_cid,
            "authorization_cid": self.authorization_cid,
            "pilot_artifact_cid": self.pilot_artifact_cid,
            "purpose": self.purpose,
            "executor_id": self.executor_id,
            "access_authorized": self.access_authorized,
            "manifest_released": self.manifest_released,
            "invalidates_seal": self.invalidates_seal,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_cid": self.receipt_cid}

    @classmethod
    def from_dict(cls, value: object) -> "ReplacementHoldoutAccessReceipt":
        data = _mapping(value, "replacement-holdout access receipt")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "replacement-holdout access receipt",
        )
        return cls(
            **{
                name: data[name]
                for name in cls.__dataclass_fields__
            }  # type: ignore[arg-type]
        )


class ReplacementHoldoutCustodian(Protocol):
    """External trust boundary that alone can release sealed bytes."""

    def release_sealed_manifest(
        self,
        sealed_manifest_path: Path,
        *,
        seal_contract_cid: str,
        authorization_cid: str,
        access_grant_receipt_cid: str,
    ) -> bytes:
        """Release opaque bytes only after validating the exact grant."""

        ...


@dataclass(frozen=True, slots=True)
class AuthorizedReplacementHoldoutPayload:
    """Opaque post-authorization bytes and the receipts that bind release."""

    sealed_manifest_bytes: bytes = field(repr=False)
    grant_receipt: ReplacementHoldoutAccessReceipt
    release_receipt: ReplacementHoldoutAccessReceipt

    def __post_init__(self) -> None:
        if (
            not isinstance(self.sealed_manifest_bytes, bytes)
            or not self.sealed_manifest_bytes
        ):
            raise HoldoutExecutionError(
                "authorized replacement payload must contain opaque bytes"
            )
        if (
            not isinstance(
                self.grant_receipt, ReplacementHoldoutAccessReceipt
            )
            or self.grant_receipt.event != "access_granted"
            or not isinstance(
                self.release_receipt, ReplacementHoldoutAccessReceipt
            )
            or self.release_receipt.event != "manifest_released"
            or self.release_receipt.previous_receipt_cid
            != self.grant_receipt.receipt_cid
        ):
            raise HoldoutExecutionError(
                "authorized replacement payload requires a linked grant and "
                "release receipt"
            )


def _strict_ledger_json(text: str) -> object:
    def reject_duplicates(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise HoldoutExecutionError(
                    f"duplicate access-ledger JSON key: {key}"
                )
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=reject_duplicates)
    except HoldoutExecutionError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise HoldoutExecutionError(
            "replacement access ledger contains invalid JSON"
        ) from exc


def _parse_replacement_access_ledger(
    raw: bytes,
    *,
    allow_pending_grant: bool = False,
) -> tuple[ReplacementHoldoutAccessReceipt, ...]:
    if not raw:
        return ()
    records: list[ReplacementHoldoutAccessReceipt] = []
    for line_number, line in enumerate(raw.splitlines(keepends=True), start=1):
        if not line.endswith(b"\n") or line == b"\n":
            raise HoldoutExecutionError(
                "replacement access ledger must contain complete JSONL records"
            )
        try:
            text = line[:-1].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HoldoutExecutionError(
                "replacement access ledger must be UTF-8"
            ) from exc
        value = _mapping(
            _strict_ledger_json(text),
            f"replacement access ledger line {line_number}",
        )
        _exact(
            value,
            {"schema", "receipt"},
            f"replacement access ledger line {line_number}",
        )
        if value["schema"] != REPLACEMENT_HOLDOUT_ACCESS_LEDGER_SCHEMA:
            raise HoldoutExecutionError(
                "replacement access ledger schema changed"
            )
        receipt = ReplacementHoldoutAccessReceipt.from_dict(value["receipt"])
        wrapper = {
            "schema": REPLACEMENT_HOLDOUT_ACCESS_LEDGER_SCHEMA,
            "receipt": receipt.to_dict(),
        }
        if canonical_dag_json_bytes(wrapper) != line[:-1]:
            raise HoldoutExecutionError(
                "replacement access ledger record is not canonical DAG-JSON"
            )
        records.append(receipt)

    receipt_cids = tuple(item.receipt_cid for item in records)
    if len(receipt_cids) != len(set(receipt_cids)):
        raise HoldoutExecutionError(
            "replacement access ledger contains duplicate receipt CIDs"
        )
    invalidated = False
    for sequence, receipt in enumerate(records):
        expected_previous = (
            None if sequence == 0 else records[sequence - 1].receipt_cid
        )
        if (
            receipt.sequence != sequence
            or receipt.previous_receipt_cid != expected_previous
        ):
            raise HoldoutExecutionError(
                "replacement access ledger chain is broken"
            )
        if sequence and (
            receipt.seal_contract_cid
            != records[0].seal_contract_cid
            or receipt.sealed_manifest_cid
            != records[0].sealed_manifest_cid
        ):
            raise HoldoutExecutionError(
                "replacement access ledger mixes distinct seals"
            )
        if invalidated and receipt.event != "premature_access":
            raise HoldoutExecutionError(
                "replacement seal was used after permanent invalidation"
            )
        if (
            sequence
            and records[sequence - 1].event == "access_granted"
            and receipt.event
            not in {
                "custody_integrity_failure",
                "custody_release_failed",
                "manifest_released",
            }
        ):
            raise HoldoutExecutionError(
                "unresolved access grant is not followed by its custody "
                "outcome"
            )
        if receipt.event in {
            "custody_integrity_failure",
            "custody_release_failed",
            "manifest_released",
        }:
            if sequence == 0:
                raise HoldoutExecutionError(
                    "custody outcome has no preceding access grant"
                )
            grant = records[sequence - 1]
            if (
                grant.event != "access_granted"
                or grant.authorization_cid != receipt.authorization_cid
                or grant.pilot_artifact_cid != receipt.pilot_artifact_cid
                or grant.purpose != receipt.purpose
                or grant.executor_id != receipt.executor_id
            ):
                raise HoldoutExecutionError(
                    "custody outcome is not linked to its access grant"
                )
        invalidated = invalidated or receipt.invalidates_seal
    if (
        records
        and records[-1].event == "access_granted"
        and not allow_pending_grant
    ):
        raise HoldoutExecutionError(
            "replacement access ledger ends in an unresolved access grant; "
            "the seal is fail-closed"
        )
    return tuple(records)


def load_replacement_holdout_access_receipts(
    ledger_path: str | Path,
    *,
    allow_pending_grant: bool = False,
    seal: ReplacementHoldoutSeal | None = None,
) -> tuple[ReplacementHoldoutAccessReceipt, ...]:
    """Read and validate receipt metadata; no holdout bytes are touched.

    ``allow_pending_grant`` is a narrow metadata-only view for the external
    custodian to verify the durable grant immediately before release.  Normal
    replay and startup callers must retain the default, which treats a grant
    without its linked custody outcome as a fail-closed terminal state.
    """

    path = Path(ledger_path)
    if not isinstance(allow_pending_grant, bool):
        raise HoldoutExecutionError(
            "allow_pending_grant must be boolean"
        )
    if not path.is_absolute():
        raise HoldoutExecutionError(
            "replacement access ledger path must be absolute"
        )
    if seal is not None:
        try:
            canonical_seal = ReplacementHoldoutSeal.from_dict(seal.to_dict())
            expected_authority_cid = (
                replacement_holdout_ledger_authority_cid(
                    canonical_seal.sealed_manifest_cid,
                    path,
                )
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise HoldoutExecutionError(
                "replacement access ledger seal authority is invalid"
            ) from exc
        if (
            canonical_seal.access_ledger_authority_cid
            != expected_authority_cid
        ):
            raise HoldoutExecutionError(
                "replacement access ledger path does not match the "
                "seal-bound ledger authority"
            )
    if not path.exists():
        return ()
    if path.is_symlink() or not path.is_file():
        raise HoldoutExecutionError(
            "replacement access ledger must be a regular non-symlink file"
        )
    try:
        metadata = path.stat()
        if metadata.st_nlink != 1 or metadata.st_mode & 0o077:
            raise HoldoutExecutionError(
                "replacement access ledger must be private and have no "
                "hard-link aliases"
            )
        raw = path.read_bytes()
    except OSError as exc:
        raise HoldoutExecutionError(
            "replacement access ledger cannot be read"
        ) from exc
    return _parse_replacement_access_ledger(
        raw,
        allow_pending_grant=allow_pending_grant,
    )


def _append_replacement_access_event(
    ledger_path: str | Path,
    seal: ReplacementHoldoutSeal,
    *,
    event: str,
    authorization: G230ReplacementHoldoutAuthorization | None,
    purpose: str,
    executor_id: str,
) -> ReplacementHoldoutAccessReceipt:
    path = Path(ledger_path)
    if not path.is_absolute():
        raise HoldoutExecutionError(
            "replacement access ledger path must be absolute"
        )
    try:
        expected_authority_cid = replacement_holdout_ledger_authority_cid(
            seal.sealed_manifest_cid,
            path,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise HoldoutExecutionError(
            "replacement access ledger authority is invalid"
        ) from exc
    if seal.access_ledger_authority_cid != expected_authority_cid:
        raise HoldoutExecutionError(
            "replacement access ledger path does not match the seal-bound "
            "ledger authority"
        )
    if path.is_symlink():
        raise HoldoutExecutionError(
            "replacement access ledger must not be a symbolic link"
        )
    if any(parent.is_symlink() for parent in path.parents):
        raise HoldoutExecutionError(
            "replacement access ledger path must not traverse symbolic links"
        )
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(parent.is_symlink() for parent in path.parents):
        raise HoldoutExecutionError(
            "replacement access ledger path became a symbolic-link traversal"
        )
    ledger_existed = path.exists()
    flags = os.O_APPEND | os.O_CREAT | os.O_RDWR
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise HoldoutExecutionError(
            "replacement access ledger cannot be opened append-only"
        ) from exc
    try:
        with os.fdopen(descriptor, "r+b", closefd=True) as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            metadata = os.fstat(handle.fileno())
            if metadata.st_nlink != 1 or metadata.st_mode & 0o077:
                raise HoldoutExecutionError(
                    "replacement access ledger must be private and have no "
                    "hard-link aliases"
                )
            handle.seek(0)
            records = _parse_replacement_access_ledger(
                handle.read(),
                allow_pending_grant=True,
            )
            if (
                event != "premature_access"
                and any(item.invalidates_seal for item in records)
            ):
                raise HoldoutExecutionError(
                    "replacement holdout seal is permanently invalidated"
                )
            if records and (
                records[0].seal_contract_cid != seal.seal_contract_cid
                or records[0].sealed_manifest_cid
                != seal.sealed_manifest_cid
            ):
                raise HoldoutExecutionError(
                    "replacement access ledger is bound to another seal"
                )
            custody_outcomes = {
                "custody_integrity_failure",
                "custody_release_failed",
                "manifest_released",
            }
            pending_grant = (
                records[-1]
                if records and records[-1].event == "access_granted"
                else None
            )
            if pending_grant is not None:
                if event not in custody_outcomes:
                    raise HoldoutExecutionError(
                        "replacement access ledger has an unresolved access "
                        "grant; a new access attempt is forbidden"
                    )
                authorization_cid = (
                    None
                    if authorization is None
                    else authorization.authorization_cid
                )
                pilot_artifact_cid = (
                    None
                    if authorization is None
                    else authorization.pilot_artifact_cid
                )
                if (
                    pending_grant.authorization_cid != authorization_cid
                    or pending_grant.pilot_artifact_cid
                    != pilot_artifact_cid
                    or pending_grant.purpose != purpose
                    or pending_grant.executor_id != executor_id
                ):
                    raise HoldoutExecutionError(
                        "custody outcome does not match the unresolved access "
                        "grant"
                    )
            elif event in custody_outcomes:
                raise HoldoutExecutionError(
                    "custody outcome requires an unresolved access grant"
                )
            sequence = len(records)
            previous = records[-1].receipt_cid if records else None
            flag_values = {
                "access_granted": (True, False, False),
                "custody_integrity_failure": (True, True, True),
                "custody_release_failed": (True, False, False),
                "manifest_released": (True, True, False),
                "premature_access": (False, False, True),
            }
            try:
                access_authorized, manifest_released, invalidates_seal = (
                    flag_values[event]
                )
            except KeyError as exc:
                raise HoldoutExecutionError(
                    "unsupported replacement access event"
                ) from exc
            payload = {
                "schema": REPLACEMENT_HOLDOUT_ACCESS_RECEIPT_SCHEMA,
                "sequence": sequence,
                "previous_receipt_cid": previous,
                "event": event,
                "seal_contract_cid": seal.seal_contract_cid,
                "sealed_manifest_cid": seal.sealed_manifest_cid,
                "authorization_cid": (
                    None
                    if authorization is None
                    else authorization.authorization_cid
                ),
                "pilot_artifact_cid": (
                    None
                    if authorization is None
                    else authorization.pilot_artifact_cid
                ),
                "purpose": purpose,
                "executor_id": executor_id,
                "access_authorized": access_authorized,
                "manifest_released": manifest_released,
                "invalidates_seal": invalidates_seal,
            }
            receipt = ReplacementHoldoutAccessReceipt(
                **payload,  # type: ignore[arg-type]
                receipt_cid=cid_for_dag_json(payload),
            )
            wrapper = {
                "schema": REPLACEMENT_HOLDOUT_ACCESS_LEDGER_SCHEMA,
                "receipt": receipt.to_dict(),
            }
            handle.seek(0, os.SEEK_END)
            handle.write(canonical_dag_json_bytes(wrapper) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
            if not ledger_existed:
                directory_flags = os.O_RDONLY | getattr(
                    os, "O_DIRECTORY", 0
                )
                directory_flags |= getattr(os, "O_CLOEXEC", 0)
                directory_descriptor = os.open(
                    path.parent,
                    directory_flags,
                )
                try:
                    os.fsync(directory_descriptor)
                finally:
                    os.close(directory_descriptor)
            return receipt
    except HoldoutExecutionError:
        raise
    except OSError as exc:
        raise HoldoutExecutionError(
            "replacement access receipt could not be durably appended"
        ) from exc


def load_authorized_replacement_holdout(
    seal: ReplacementHoldoutSeal,
    authorization: G230ReplacementHoldoutAuthorization | None,
    *,
    sealed_manifest_path: str | Path,
    tuning_worktree: str | Path,
    access_ledger_path: str | Path,
    executor_id: str,
    custodian: ReplacementHoldoutCustodian,
    purpose: str = "evaluation",
) -> AuthorizedReplacementHoldoutPayload:
    """Release an opaque replacement manifest only across every G220 gate.

    Authorization and grant metadata are appended before calling the external
    custodian.  Missing, legacy, malformed, stale, or seal-mismatched
    authorization is a premature access and permanently invalidates the seal.
    This function never parses or summarizes the returned opaque block.
    """

    try:
        canonical_seal = ReplacementHoldoutSeal.from_dict(seal.to_dict())
    except (AttributeError, TypeError, ValueError) as exc:
        raise HoldoutExecutionError(
            "replacement holdout seal metadata is invalid"
        ) from exc
    _safe_id(executor_id, "executor_id")
    if purpose not in {"evaluation", "replay"}:
        raise HoldoutExecutionError(
            "replacement holdout purpose must be evaluation or replay"
        )

    canonical_authorization: G230ReplacementHoldoutAuthorization | None = None
    try:
        if not isinstance(
            authorization, G230ReplacementHoldoutAuthorization
        ):
            raise HoldoutExecutionError(
                "exact HSSL-G230 authorization is required"
            )
        canonical_authorization = (
            G230ReplacementHoldoutAuthorization.from_dict(
                authorization.to_dict()
            )
        )
        canonical_authorization.validate_against(canonical_seal)
    except (AttributeError, TypeError, ValueError) as exc:
        _append_replacement_access_event(
            access_ledger_path,
            canonical_seal,
            event="premature_access",
            authorization=canonical_authorization,
            purpose=purpose,
            executor_id=executor_id,
        )
        raise HoldoutExecutionError(
            "premature replacement-holdout access permanently invalidated "
            "the seal"
        ) from exc

    try:
        external_path = validate_replacement_holdout_external_path(
            sealed_manifest_path,
            tuning_worktree=tuning_worktree,
        )
    except (TypeError, ValueError) as exc:
        _append_replacement_access_event(
            access_ledger_path,
            canonical_seal,
            event="premature_access",
            authorization=canonical_authorization,
            purpose=purpose,
            executor_id=executor_id,
        )
        raise HoldoutExecutionError(
            "unsafe replacement-holdout path permanently invalidated the seal"
        ) from exc

    grant = _append_replacement_access_event(
        access_ledger_path,
        canonical_seal,
        event="access_granted",
        authorization=canonical_authorization,
        purpose=purpose,
        executor_id=executor_id,
    )
    try:
        release = custodian.release_sealed_manifest
        opaque_bytes = release(
            external_path,
            seal_contract_cid=canonical_seal.seal_contract_cid,
            authorization_cid=canonical_authorization.authorization_cid,
            access_grant_receipt_cid=grant.receipt_cid,
        )
    except Exception as exc:
        _append_replacement_access_event(
            access_ledger_path,
            canonical_seal,
            event="custody_release_failed",
            authorization=canonical_authorization,
            purpose=purpose,
            executor_id=executor_id,
        )
        raise HoldoutExecutionError(
            "external replacement-holdout custodian denied release"
        ) from exc
    if (
        not isinstance(opaque_bytes, bytes)
        or not opaque_bytes
        or cid_for_bytes(opaque_bytes, codec="raw")
        != canonical_seal.sealed_manifest_cid
    ):
        _append_replacement_access_event(
            access_ledger_path,
            canonical_seal,
            event="custody_integrity_failure",
            authorization=canonical_authorization,
            purpose=purpose,
            executor_id=executor_id,
        )
        raise HoldoutExecutionError(
            "custodian returned a block outside the sealed CID; the "
            "replacement seal is invalidated"
        )
    released = _append_replacement_access_event(
        access_ledger_path,
        canonical_seal,
        event="manifest_released",
        authorization=canonical_authorization,
        purpose=purpose,
        executor_id=executor_id,
    )
    return AuthorizedReplacementHoldoutPayload(
        sealed_manifest_bytes=opaque_bytes,
        grant_receipt=grant,
        release_receipt=released,
    )


def build_authorized_holdout_plan(
    authorization: PilotAuthorizationReceipt,
    corpus: ReviewedCorpus,
    *,
    run_id: str,
    seed: int,
    access_ledger_id: str,
    limits: ResourceLimits = ResourceLimits(),
) -> AblationPlan:
    """Build the exact A0/shortlist cold/warm holdout schedule."""

    if not isinstance(authorization, PilotAuthorizationReceipt):
        raise HoldoutExecutionError(
            "authorization must be a PilotAuthorizationReceipt"
        )
    if not isinstance(corpus, ReviewedCorpus):
        raise HoldoutExecutionError("corpus must be a ReviewedCorpus")
    _safe_id(access_ledger_id, "access_ledger_id")
    integrity = build_split_integrity_manifest(corpus)
    if (
        corpus.manifest_sha256 != authorization.corpus_manifest_sha256
        or integrity.holdout.split_sha256
        != authorization.holdout_split_sha256
    ):
        raise HoldoutExecutionError(
            "authorization corpus or holdout split identity is stale"
        )
    positions = {case.case_id: case for case in corpus.cases}
    holdout_cases = tuple(
        positions[case_id] for case_id in integrity.holdout.case_ids
    )
    return build_ablation_plan(
        run_id,
        holdout_cases,
        case_manifest_sha256=corpus.manifest_sha256,
        split=Split.HOLDOUT,
        seed=seed,
        variant_ids=("A0", *authorization.shortlist_variant_ids),
        cache_modes=(CacheMode.COLD, CacheMode.WARM),
        limits=limits,
        environment_sha256=authorization.environment_sha256,
        holdout_access_log_id=access_ledger_id,
    )


def build_holdout_access_audits(
    authorization: PilotAuthorizationReceipt,
    corpus: ReviewedCorpus,
    plan: AblationPlan,
    *,
    prompt_examples: Mapping[str, str],
    purpose: str = "evaluation",
) -> tuple[HoldoutAccessAudit, ...]:
    """Build one ordered, unique, no-tuning audit per run contract."""

    audits = tuple(
        HoldoutAccessAudit.from_run_contract(
            corpus,
            contract,
            prompts_sha256=authorization.prompts_sha256,
            policy_sha256=authorization.policy_sha256,
            model_identities_sha256=authorization.model_identities_sha256,
            thresholds_sha256=authorization.thresholds_sha256,
            prompt_examples=prompt_examples,
            sequence=sequence,
            purpose=purpose,
        )
        for sequence, contract in enumerate(plan.run_contracts)
    )
    validate_holdout_access_log(corpus, audits)
    return audits


def validate_holdout_access_audits(
    authorization: PilotAuthorizationReceipt,
    corpus: ReviewedCorpus,
    plan: AblationPlan,
    access_audits: Sequence[HoldoutAccessAudit],
    *,
    purpose: str = "evaluation",
) -> tuple[HoldoutAccessAudit, ...]:
    """Revalidate canonical audits against corpus, plan, and frozen inputs."""

    try:
        authorization = PilotAuthorizationReceipt.from_dict(
            authorization.to_dict()
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise HoldoutExecutionError("pilot authorization is invalid") from exc
    if not isinstance(corpus, ReviewedCorpus):
        raise HoldoutExecutionError("corpus must be a ReviewedCorpus")
    if not isinstance(plan, AblationPlan) or plan.split is not Split.HOLDOUT:
        raise HoldoutExecutionError(
            "access-audit validation requires a holdout plan"
        )
    integrity = build_split_integrity_manifest(corpus)
    if (
        corpus.manifest_sha256 != authorization.corpus_manifest_sha256
        or integrity.holdout.split_sha256
        != authorization.holdout_split_sha256
        or plan.case_manifest_sha256 != corpus.manifest_sha256
        or plan.protocol_sha256 != authorization.protocol_sha256
        or plan.environment_sha256 != authorization.environment_sha256
        or plan.case_ids != integrity.holdout.case_ids
        or plan.variant_ids
        != ("A0", *authorization.shortlist_variant_ids)
        or plan.cache_modes != (CacheMode.COLD, CacheMode.WARM)
        or plan.holdout_access_log_id is None
    ):
        raise HoldoutExecutionError(
            "access audits do not bind the authorized holdout plan"
        )
    contracts = plan.run_contracts
    try:
        audits = tuple(
            HoldoutAccessAudit.from_dict(item.to_dict())
            for item in access_audits
        )
        validate_holdout_access_log(corpus, audits)
    except (AttributeError, TypeError, ValueError) as exc:
        raise HoldoutExecutionError(
            "holdout access audit log is invalid"
        ) from exc
    if len(audits) != len(contracts):
        raise HoldoutExecutionError(
            "one holdout access audit is required per run contract"
        )
    for sequence, (contract, audit) in enumerate(
        zip(contracts, audits, strict=True)
    ):
        expected_run_digest = _sha(contract.to_dict())
        if (
            audit.sequence != sequence
            or audit.purpose != purpose
            or audit.audit_id != contract.holdout_access_log_id
            or audit.run_contract_sha256 != expected_run_digest
            or audit.run_id != contract.run_id
            or audit.protocol_sha256 != contract.protocol_sha256
            or audit.variant_id != contract.requested_variant_id
            or audit.cache_namespace != contract.cache_namespace
            or audit.cache_mode != contract.cache_mode.value
            or audit.configuration_sha256 != contract.configuration_sha256
            or audit.configuration_sha256
            != authorization.configuration_sha256s[
                contract.requested_variant_id
            ]
            or audit.prompts_sha256 != authorization.prompts_sha256
            or audit.policy_sha256 != authorization.policy_sha256
            or audit.model_identities_sha256
            != authorization.model_identities_sha256
            or audit.thresholds_sha256 != authorization.thresholds_sha256
            or audit.accessed_case_ids != integrity.holdout.case_ids
            or audit.tuning_permitted is not False
        ):
            raise HoldoutExecutionError(
                "holdout access audit differs from its frozen run contract"
            )
    return audits


def _validate_execution_boundary(
    authorization: PilotAuthorizationReceipt,
    corpus: ReviewedCorpus,
    plan: AblationPlan,
    access_audits: Sequence[HoldoutAccessAudit],
    *,
    source_commit: str,
    environment_sha256: str,
    output_root: str | Path,
    purpose: str,
) -> tuple[HoldoutAccessAudit, ...]:
    """Validate the complete boundary without causing filesystem side effects."""

    try:
        authorization = PilotAuthorizationReceipt.from_dict(
            authorization.to_dict()
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise HoldoutExecutionError("pilot authorization is invalid") from exc
    if not isinstance(corpus, ReviewedCorpus):
        raise HoldoutExecutionError("corpus must be a ReviewedCorpus")
    if not isinstance(plan, AblationPlan):
        raise HoldoutExecutionError("plan must be an AblationPlan")
    if plan.split is not Split.HOLDOUT:
        raise HoldoutExecutionError("authorized execution requires a holdout plan")
    if (
        _commit(source_commit, "source_commit") != authorization.source_commit
        or _digest(environment_sha256, "environment_sha256")
        != authorization.environment_sha256
        or plan.environment_sha256 != authorization.environment_sha256
        or plan.protocol_sha256 != authorization.protocol_sha256
        or plan.case_manifest_sha256 != authorization.corpus_manifest_sha256
    ):
        raise HoldoutExecutionError(
            "source, environment, protocol, or corpus identity drifted"
        )
    integrity = build_split_integrity_manifest(corpus)
    if (
        corpus.manifest_sha256 != authorization.corpus_manifest_sha256
        or integrity.holdout.split_sha256
        != authorization.holdout_split_sha256
        or plan.case_ids != integrity.holdout.case_ids
    ):
        raise HoldoutExecutionError(
            "plan does not use the complete frozen holdout manifest in order"
        )
    if plan.variant_ids != ("A0", *authorization.shortlist_variant_ids):
        raise HoldoutExecutionError(
            "plan must schedule only A0 and the exact frozen shortlist"
        )
    if plan.cache_modes != (CacheMode.COLD, CacheMode.WARM):
        raise HoldoutExecutionError(
            "holdout must keep complete, separate cold and warm pairs"
        )
    if plan.holdout_access_log_id is None:
        raise HoldoutExecutionError("holdout plan has no access ledger identity")

    audits = validate_holdout_access_audits(
        authorization,
        corpus,
        plan,
        access_audits,
        purpose=purpose,
    )

    root = Path(output_root)
    if isinstance(output_root, str) and not output_root.strip():
        raise HoldoutExecutionError("output_root must not be empty")
    if root.exists() or root.is_symlink():
        raise HoldoutExecutionError(
            "holdout output namespace must be fresh; resume is forbidden"
        )
    return audits


@dataclass(frozen=True, slots=True)
class HoldoutExecutionReceipt:
    """Content-addressed completion receipt for one authorized holdout run."""

    schema: str
    evidence: str
    run_id: str
    source_commit: str
    environment_sha256: str
    authorization_sha256: str
    pilot_gate_sha256: str
    plan_sha256: str
    access_audit_sha256s: tuple[str, ...]
    result_sha256s: tuple[str, ...]
    cache_namespaces: tuple[str, ...]
    executed_job_ids: tuple[str, ...]
    complete: bool
    receipt_sha256: str

    def __post_init__(self) -> None:
        if self.schema != HOLDOUT_EXECUTION_RECEIPT_SCHEMA:
            raise HoldoutExecutionError("unsupported holdout execution receipt")
        if self.evidence != HSSLEV1167A17():
            raise HoldoutExecutionError("holdout evidence marker changed")
        _safe_id(self.run_id, "run_id")
        _commit(self.source_commit, "source_commit")
        for name in (
            "environment_sha256",
            "authorization_sha256",
            "pilot_gate_sha256",
            "plan_sha256",
            "receipt_sha256",
        ):
            _digest(getattr(self, name), name)
        for name in ("access_audit_sha256s", "result_sha256s"):
            values = tuple(getattr(self, name))
            if not values or any(
                not isinstance(value, str) or not _DIGEST.fullmatch(value)
                for value in values
            ):
                raise HoldoutExecutionError(f"{name} must contain SHA-256 digests")
            object.__setattr__(self, name, values)
        namespaces = tuple(self.cache_namespaces)
        jobs = tuple(self.executed_job_ids)
        if (
            not namespaces
            or len(namespaces) != len(set(namespaces))
            or not jobs
            or len(jobs) != len(set(jobs))
        ):
            raise HoldoutExecutionError(
                "execution receipt requires distinct cache and job identities"
            )
        object.__setattr__(self, "cache_namespaces", namespaces)
        object.__setattr__(self, "executed_job_ids", jobs)
        if self.complete is not True:
            raise HoldoutExecutionError("holdout execution receipt must be complete")
        if self.receipt_sha256 != _sha(self.identity_payload()):
            raise HoldoutExecutionError("holdout receipt digest changed")

    def identity_payload(self) -> dict[str, object]:
        return {
            name: (
                list(getattr(self, name))
                if name
                in {
                    "access_audit_sha256s",
                    "result_sha256s",
                    "cache_namespaces",
                    "executed_job_ids",
                }
                else getattr(self, name)
            )
            for name in self.__dataclass_fields__
            if name != "receipt_sha256"
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_sha256": self.receipt_sha256}

    @classmethod
    def from_dict(cls, value: object) -> "HoldoutExecutionReceipt":
        data = _mapping(value, "holdout execution receipt")
        _exact(data, set(cls.__dataclass_fields__), "holdout execution receipt")
        for name in (
            "access_audit_sha256s",
            "result_sha256s",
            "cache_namespaces",
            "executed_job_ids",
        ):
            if not isinstance(data[name], list):
                raise HoldoutExecutionError(f"{name} must be an array")
        return cls(
            **{
                name: (
                    tuple(data[name]) if isinstance(data[name], list) else data[name]
                )
                for name in cls.__dataclass_fields__
            }  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class AuthorizedHoldoutRun:
    """Execution result paired with its immutable authorization receipt."""

    execution: AblationRunResult
    receipt: HoldoutExecutionReceipt
    access_audits: tuple[HoldoutAccessAudit, ...]

    def __post_init__(self) -> None:
        audits = tuple(self.access_audits)
        if not audits or any(
            not isinstance(item, HoldoutAccessAudit) for item in audits
        ):
            raise HoldoutExecutionError(
                "authorized holdout run requires canonical access audits"
            )
        if not isinstance(self.receipt, HoldoutExecutionReceipt):
            raise HoldoutExecutionError(
                "authorized holdout run requires an execution receipt"
            )
        if tuple(
            item.audit_sha256 for item in audits
        ) != self.receipt.access_audit_sha256s:
            raise HoldoutExecutionError(
                "authorized holdout receipt does not bind its access audits"
            )
        object.__setattr__(self, "access_audits", audits)


def _write_once(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(value))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise HoldoutExecutionError(
            f"refusing to overwrite immutable holdout record: {path}"
        ) from exc


def execute_authorized_holdout(
    authorization: PilotAuthorizationReceipt,
    corpus: ReviewedCorpus,
    plan: AblationPlan,
    access_audits: Sequence[HoldoutAccessAudit],
    adapters: Mapping[object, object],
    *,
    source_commit: str,
    environment_sha256: str,
    output_root: str | Path,
    resource_scheduler: ResourceScheduler | None = None,
) -> AuthorizedHoldoutRun:
    """Validate every gate and audit, then execute once in a fresh namespace."""

    if not isinstance(adapters, Mapping):
        raise HoldoutExecutionError("adapters must be a mapping")
    if resource_scheduler is not None and not isinstance(
        resource_scheduler, ResourceScheduler
    ):
        raise HoldoutExecutionError(
            "resource_scheduler must be a ResourceScheduler"
        )
    audits = _validate_execution_boundary(
        authorization,
        corpus,
        plan,
        access_audits,
        source_commit=source_commit,
        environment_sha256=environment_sha256,
        output_root=output_root,
        purpose="evaluation",
    )
    root = Path(output_root)
    authorization_record = {
        "schema": PILOT_AUTHORIZATION_SCHEMA,
        "evidence": HSSLEV1167A17(),
        "authorization": authorization.to_dict(),
        "plan_sha256": plan.digest,
        "access_audit_sha256s": [item.audit_sha256 for item in audits],
        "source_commit": source_commit,
        "environment_sha256": environment_sha256,
        "resume_permitted": False,
    }
    _write_once(
        root / "state" / HOLDOUT_AUTHORIZATION_FILE,
        authorization_record,
    )
    _write_once(
        root / "state" / HOLDOUT_ACCESS_AUDITS_FILE,
        {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark."
                "holdout-access-ledger.v1"
            ),
            "evidence": HSSLEV1167A17(),
            "run_id": plan.run_id,
            "plan_sha256": plan.digest,
            "authorization_sha256": authorization.authorization_sha256,
            "audits": [item.to_dict() for item in audits],
        },
    )
    execution = _execute_ablation(
        plan,
        adapters,
        output_root=root,
        resume=False,
        resource_scheduler=resource_scheduler,
        authorized_holdout=True,
    )
    payload = {
        "schema": HOLDOUT_EXECUTION_RECEIPT_SCHEMA,
        "evidence": HSSLEV1167A17(),
        "run_id": plan.run_id,
        "source_commit": source_commit,
        "environment_sha256": environment_sha256,
        "authorization_sha256": authorization.authorization_sha256,
        "pilot_gate_sha256": authorization.pilot_gate_sha256,
        "plan_sha256": plan.digest,
        "access_audit_sha256s": tuple(
            item.audit_sha256 for item in audits
        ),
        "result_sha256s": tuple(item.digest for item in execution.results),
        "cache_namespaces": tuple(
            contract.cache_namespace for contract in execution.contracts
        ),
        "executed_job_ids": execution.executed_job_ids,
        "complete": execution.complete,
    }
    receipt = HoldoutExecutionReceipt(
        **payload,  # type: ignore[arg-type]
        receipt_sha256=_sha(
            {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in payload.items()
            }
        ),
    )
    _write_once(
        root / "receipts" / HOLDOUT_EXECUTION_RECEIPT_FILE,
        receipt.to_dict(),
    )
    return AuthorizedHoldoutRun(execution, receipt, audits)


__all__ = [
    "G230_REPLACEMENT_HOLDOUT_AUTHORIZATION_SCHEMA",
    "HOLDOUT_ACCESS_AUDITS_FILE",
    "HOLDOUT_AUTHORIZATION_FILE",
    "HOLDOUT_EXECUTION_RECEIPT_FILE",
    "HOLDOUT_EXECUTION_RECEIPT_SCHEMA",
    "MAX_SHORTLIST_SIZE",
    "PILOT_AUTHORIZATION_SCHEMA",
    "REPLACEMENT_HOLDOUT_ACCESS_EVENTS",
    "REPLACEMENT_HOLDOUT_ACCESS_LEDGER_SCHEMA",
    "REPLACEMENT_HOLDOUT_ACCESS_RECEIPT_SCHEMA",
    "REPLACEMENT_HOLDOUT_AUTHORIZED_PROTOCOL_KEYS",
    "AuthorizedReplacementHoldoutPayload",
    "AuthorizedHoldoutRun",
    "G230ReplacementHoldoutAuthorization",
    "HSSLEV1167A17",
    "HoldoutExecutionError",
    "HoldoutExecutionReceipt",
    "PilotAuthorizationReceipt",
    "ReplacementHoldoutAccessReceipt",
    "ReplacementHoldoutCustodian",
    "build_authorized_holdout_plan",
    "build_holdout_access_audits",
    "execute_authorized_holdout",
    "load_authorized_replacement_holdout",
    "load_replacement_holdout_access_receipts",
    "validate_holdout_access_audits",
]
