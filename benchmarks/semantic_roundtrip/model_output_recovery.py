"""Bounded model-output recovery for Leanstral reliability experiments.

This module is deliberately additive.  It does not alter the frozen SRT-014
adapters or their results.  Instead, it provides a strict wrapper for a new
experiment over the same direct and SyMAI routes to the same one-slot
Leanstral service.

The wrapper is fail closed:

* L1 and L2 must be nonempty canonical IR objects;
* T1 is a bounded list of one explicitly polarised realization per input rule;
* an output is never repaired locally, recovered from source, or borrowed from
  another call;
* the promotion default policy permits at most one preregistered retry;
* an optional research policy may declare a larger preregistered retry budget
  without changing the promotion default;
* every provider call records a typed rejection reason from the closed
  taxonomy ``blank | schema | polarity | empty_rules | timeout | other``; and
* every provider call, rejection, retry, and terminal typed failure is retained
  in a source-free receipt, with per-arm ``accept_rate`` and
  ``retry_exhausted_rate`` exposed separately from end-to-end loss.
"""

from __future__ import annotations

import json
import re
import socket
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Final, Protocol

from ipfs_datasets_py.utils.cid_utils import (
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)

from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ContractError,
    FailureReason,
    RealizerRequest,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import (
    CONSTRUCTOR_MAX_TOKENS,
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
    CompletionClient,
    LeanstralMalformedResponseError,
    LeanstralRequestError,
    LeanstralTimeoutError,
    LeanstralUnavailableError,
    _constructor_prompt,
    canonical_ir_schema,
)
from benchmarks.semantic_roundtrip.constructors.symai import (
    SYMAI_ORCHESTRATOR,
    SYMAI_ROUTE,
    SyMAIGenerationSettings,
    SyMAICompletionClient,
    SyMAIMalformedResponseError,
    SyMAIRouteError,
    _complete_symai_json,
)
from benchmarks.semantic_roundtrip.realizers.leanstral import (
    REALIZATION_MAX_LENGTH,
    REALIZER_MAX_TOKENS,
    _realizer_prompt,
)
from benchmarks.semantic_roundtrip_capabilities import (
    LEANSTRAL_BACKEND,
    LEANSTRAL_BACKEND_OWNER,
    LEANSTRAL_CAPACITY,
    LEANSTRAL_PROVIDER,
    SYMAI_MODEL_ALIAS,
    SYMAI_PROVIDER,
    SYMAI_VERSION,
)


BOUNDED_MODEL_OUTPUT_RECOVERY_INTERFACE: Final = (
    "BoundedModelOutputRecovery@1"
)
SYMAI_POLARITY_CONTRACT_INTERFACE: Final = "SyMAIPolarityContract@1"
MODEL_OUTPUT_RECOVERY_SCHEMA_VERSION: Final = (
    "ipfs-datasets.semantic-roundtrip-model-output-recovery.v1"
)
SRT021_REMEDIATION_EVIDENCE_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-srt021-model-remediation-evidence.v1"
)
SRT021_MANIFEST_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "no_eligible_remediation_manifest.json"
)
SRT021_MANIFEST_CID: Final = (
    "baguqeerarr7ebjrzd3argtdekd7er3bqrnvhuzy2ogqzfi7h5nv37dbea52a"
)
SRT021_MANIFEST_GATE_CID: Final = (
    "baguqeera5rgixug7ukbnc6xp7a6a4rggxzxzkscoeihpmifxksi2nkgqoy7a"
)
SRT014_REPORT_CID: Final = (
    "baguqeerakqgerwv6npdlqpgrc3bjzuxqog3hiouey3c4giw5vkdgk2jhfbpq"
)
_SRT014_GATE_CID: Final = (
    "baguqeeraa7vbts26rxvqujbvgvgplq4xrprcebufol5qqmstc6cbrac2rthq"
)
_SRT014_REPORT_RAW_CID: Final = (
    "bafkreih2qqfopijqrvxq6fda63laz5iloh227dw34s6zn7tbyk6dhcbk4e"
)
_SRT014_REPORT_PATH: Final = (
    "docs/performance_snapshots/"
    "2026-07-26_semantic_roundtrip_composition_pilot.json"
)
_SRT021_MANIFEST_RAW_CID: Final = (
    "bafkreiariailns3nlwjvye7ukslov6be52el3khedit3ki2wrt6hhmrjre"
)
_SRT021_MANIFEST_INTERFACE: Final = (
    "SRT014NoEligibleRemediationManifest@1"
)
_SRT021_MANIFEST_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-no-eligible-remediation.v1"
)
_SRT021_MANIFEST_GATE_SCHEMA: Final = (
    "ipfs_datasets_py.benchmarks.semantic_roundtrip."
    "no_eligible_remediation_manifest_gate@1"
)
_SRT021_MODEL_ARM: Final = (
    "model__not_applicable__always_on__symai__leanstral_symai"
)
_SRT021_MODAL_SPACY_ARM: Final = (
    "modal_spacy__no_guidance__no_repair__not_applicable__deterministic"
)
_SRT021_REMEDIATION_TARGETS: Final = (
    "blank_t1",
    "empty_l1",
    "empty_l2",
    "polarity_ambiguous",
    "route_contract_failure",
)
_SRT021_RELEVANT_COORDINATE_KEYS: Final = (
    "construction_contract|0|"
    "modal_spacy__no_guidance__no_repair__not_applicable__deterministic",
    "corp_policy_1|0|"
    "modal_spacy__no_guidance__no_repair__not_applicable__deterministic",
    "exec_order_1|0|"
    "modal_spacy__no_guidance__no_repair__not_applicable__deterministic",
    "legal_doc_1|0|"
    "modal_spacy__no_guidance__no_repair__not_applicable__deterministic",
    "legal_doc_1|0|"
    "model__not_applicable__always_on__symai__leanstral_symai",
    "legal_doc_1|1|"
    "model__not_applicable__always_on__symai__leanstral_symai",
    "legal_doc_1|2|"
    "model__not_applicable__always_on__symai__leanstral_symai",
    "legal_doc_1|3|"
    "model__not_applicable__always_on__symai__leanstral_symai",
    "legal_doc_1|4|"
    "model__not_applicable__always_on__symai__leanstral_symai",
)

DIRECT_ROUTE_ID: Final = "direct_openai_compatible_http"
# The tokenizer is embedded in the exact frozen GGUF.  Binding its observed
# vocabulary metadata avoids pretending that a separate, substitutable
# Hugging Face tokenizer is involved.
LEANSTRAL_TOKENIZER_IDENTITY: Final = (
    f"{LEANSTRAL_MODEL}#embedded-gguf-tokenizer:"
    "vocab_type=2:n_vocab=131072"
)

_POLARITY_LABELS: Final = {
    "O": "obligation",
    "P": "permission",
    "F": "prohibition",
}
_RETRYABLE_REJECTIONS: Final = frozenset(
    {
        "blank_output",
        "empty_output",
        "malformed_output",
        "polarity_ambiguous",
    }
)
_RETRY_SYSTEM_SUFFIX: Final = (
    " This is the sole preregistered correction attempt. Return a fresh object "
    "for the same input and schema; do not quote, recover, or request source "
    "material and do not change route, model, or decoding settings."
)
_RETRY_PROMPT_SUFFIX: Final = (
    "\nPREREGISTERED_RETRY_REASON:{reason}\n"
    "Correct only that contract violation. All original instructions remain "
    "binding."
)


class RecoveryRole(str, Enum):
    """The three model-output positions in a semantic round trip."""

    L1 = "l1"
    T1 = "t1"
    L2 = "l2"


class RecoveryRoute(str, Enum):
    """The two preregistered paths to the one physical Leanstral service."""

    DIRECT = "direct"
    SYMAI = "symai"

    @property
    def route_id(self) -> str:
        return (
            DIRECT_ROUTE_ID
            if self is RecoveryRoute.DIRECT
            else SYMAI_ROUTE
        )


class ModelRejectionReason(str, Enum):
    """Closed taxonomy of typed model-call rejection reasons (EVAL-004)."""

    BLANK = "blank"
    SCHEMA = "schema"
    POLARITY = "polarity"
    EMPTY_RULES = "empty_rules"
    TIMEOUT = "timeout"
    OTHER = "other"


class RecoveryPolicyKind(str, Enum):
    """Promotion default vs optional research recovery policy."""

    PROMOTION = "promotion"
    RESEARCH = "research"


class RecoverySchemaPath(str, Enum):
    """Schema selection for standard recovery vs single-rule research."""

    STANDARD = "standard"
    SINGLE_RULE_RESEARCH = "single_rule_research"


# Fine-grained rejection labels used on receipts map onto the closed taxonomy.
_DETAILED_REJECTION_TAXONOMY: Final[Mapping[str, ModelRejectionReason]] = (
    MappingProxyType(
        {
            "blank_output": ModelRejectionReason.BLANK,
            "empty_output": ModelRejectionReason.EMPTY_RULES,
            "malformed_output": ModelRejectionReason.SCHEMA,
            "polarity_ambiguous": ModelRejectionReason.POLARITY,
            "call_timeout": ModelRejectionReason.TIMEOUT,
            "route_contract_failure": ModelRejectionReason.OTHER,
            "call_exception": ModelRejectionReason.OTHER,
            # Taxonomy members are also valid detailed labels.
            "blank": ModelRejectionReason.BLANK,
            "schema": ModelRejectionReason.SCHEMA,
            "polarity": ModelRejectionReason.POLARITY,
            "empty_rules": ModelRejectionReason.EMPTY_RULES,
            "timeout": ModelRejectionReason.TIMEOUT,
            "other": ModelRejectionReason.OTHER,
        }
    )
)

TYPED_REJECTION_REASONS: Final[frozenset[str]] = frozenset(
    reason.value for reason in ModelRejectionReason
)

_PROMOTION_EXPERIMENT_PREFIX: Final = "srt-023-replacement-"
_RESEARCH_EXPERIMENT_PREFIX: Final = "research-recovery-"
_RESEARCH_MAX_RETRIES_CAP: Final = 8

_STANDARD_SCHEMA_NAMES: Final[Mapping[RecoveryRole, str]] = MappingProxyType(
    {
        RecoveryRole.L1: "srt023_replacement_l1_canonical_ir_v1",
        RecoveryRole.T1: "srt023_replacement_t1_realization_v1",
        RecoveryRole.L2: "srt023_replacement_l2_canonical_ir_v1",
    }
)
_SINGLE_RULE_RESEARCH_SCHEMA_NAMES: Final[Mapping[RecoveryRole, str]] = (
    MappingProxyType(
        {
            RecoveryRole.L1: "research_single_rule_l1_canonical_ir_v1",
            RecoveryRole.T1: "research_single_rule_t1_realization_v1",
            RecoveryRole.L2: "research_single_rule_l2_canonical_ir_v1",
        }
    )
)


def classify_model_rejection(
    rejection: str | None,
) -> ModelRejectionReason | None:
    """Map a detailed call rejection onto the closed EVAL-004 taxonomy."""

    if rejection is None:
        return None
    if not isinstance(rejection, str) or not rejection.strip():
        raise ContractError("rejection must be a nonblank string or None")
    mapped = _DETAILED_REJECTION_TAXONOMY.get(rejection.strip())
    if mapped is not None:
        return mapped
    return ModelRejectionReason.OTHER


def schema_name_for_role(
    role: RecoveryRole,
    *,
    schema_path: RecoverySchemaPath = RecoverySchemaPath.STANDARD,
) -> str:
    """Return the preregistered schema name for one role and schema path."""

    if not isinstance(role, RecoveryRole):
        raise ContractError("role must be a RecoveryRole")
    if not isinstance(schema_path, RecoverySchemaPath):
        raise ContractError("schema_path must be a RecoverySchemaPath")
    if schema_path is RecoverySchemaPath.SINGLE_RULE_RESEARCH:
        return _SINGLE_RULE_RESEARCH_SCHEMA_NAMES[role]
    return _STANDARD_SCHEMA_NAMES[role]


def _require_cid(value: object, *, codec: str, label: str) -> str:
    try:
        return validate_cid(value, codecs=(codec,))
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{label} must be a canonical {codec} CID") from exc


def _coordinate_payload(coordinate_key: str) -> dict[str, object]:
    parts = coordinate_key.split("|")
    if len(parts) != 3 or not parts[0] or not parts[2]:
        raise ContractError("SRT-021 coordinate key is malformed")
    try:
        repeat_index = int(parts[1])
    except ValueError as exc:
        raise ContractError(
            "SRT-021 coordinate repeat index is malformed"
        ) from exc
    if repeat_index < 0 or str(repeat_index) != parts[1]:
        raise ContractError(
            "SRT-021 coordinate repeat index is not canonical"
        )
    return {
        "coordinate_key": coordinate_key,
        "case_id": parts[0],
        "repeat_index": repeat_index,
        "arm_id": parts[2],
        "gate_id": "polarity_preservation",
    }


@dataclass(frozen=True, slots=True)
class SRT021RemediationEvidence:
    """Immutable SRT-021 lineage and the model/polarity failure coordinates."""

    manifest_cid: str
    manifest_gate_cid: str
    report_cid: str
    remediation_targets: tuple[str, ...]
    coordinate_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_cid(
            self.manifest_cid,
            codec="dag-json",
            label="SRT-021 manifest CID",
        )
        _require_cid(
            self.manifest_gate_cid,
            codec="dag-json",
            label="SRT-021 manifest gate CID",
        )
        _require_cid(
            self.report_cid,
            codec="dag-json",
            label="SRT-014 report CID",
        )
        if (
            self.remediation_targets
            != tuple(sorted(set(self.remediation_targets)))
            or self.coordinate_keys
            != tuple(sorted(set(self.coordinate_keys)))
            or not self.remediation_targets
            or not self.coordinate_keys
        ):
            raise ContractError(
                "SRT-021 targets and coordinates must be nonempty, unique, "
                "and canonically sorted"
            )
        for coordinate_key in self.coordinate_keys:
            _coordinate_payload(coordinate_key)

    def _payload(self) -> dict[str, object]:
        return {
            "schema": SRT021_REMEDIATION_EVIDENCE_SCHEMA,
            "manifest": {
                "path": str(SRT021_MANIFEST_RELATIVE_PATH),
                "manifest_cid": self.manifest_cid,
                "manifest_gate_cid": self.manifest_gate_cid,
                "source_report_cid": self.report_cid,
            },
            "remediation_targets": list(self.remediation_targets),
            "coordinates": [
                _coordinate_payload(value) for value in self.coordinate_keys
            ],
        }

    @property
    def evidence_cid(self) -> str:
        return cid_for_dag_json(self._payload())

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "evidence_cid": self.evidence_cid}

    @classmethod
    def validate_dict(cls, value: object) -> str:
        if not isinstance(value, Mapping):
            raise ContractError("SRT-021 evidence must be an object")
        supplied = dict(value)
        evidence_cid = _require_cid(
            supplied.pop("evidence_cid", None),
            codec="dag-json",
            label="SRT-021 evidence CID",
        )
        if cid_for_dag_json(supplied) != evidence_cid:
            raise ContractError("SRT-021 evidence CID does not match payload")
        if dict(value) != FROZEN_SRT021_REMEDIATION_EVIDENCE.to_dict():
            raise ContractError(
                "SRT-021 evidence differs from the frozen remediation lineage"
            )
        return evidence_cid


FROZEN_SRT021_REMEDIATION_EVIDENCE: Final = SRT021RemediationEvidence(
    manifest_cid=SRT021_MANIFEST_CID,
    manifest_gate_cid=SRT021_MANIFEST_GATE_CID,
    report_cid=SRT014_REPORT_CID,
    remediation_targets=_SRT021_REMEDIATION_TARGETS,
    coordinate_keys=_SRT021_RELEVANT_COORDINATE_KEYS,
)


def _manifest_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ContractError(f"SRT-021 {label} must be an object")
    return value


def _extract_srt021_coordinate_keys(
    manifest: Mapping[str, object],
) -> tuple[str, ...]:
    remediation = _manifest_mapping(
        manifest.get("remediation"), "remediation evidence"
    )
    arms = _manifest_mapping(remediation.get("arms"), "arm evidence")

    def polarity_coordinates(arm_id: str) -> tuple[str, ...]:
        arm = _manifest_mapping(
            arms.get(arm_id), f"arm {arm_id!r}"
        )
        if "polarity_preservation" not in arm.get("failed_gate_ids", ()):
            raise ContractError(
                f"SRT-021 arm {arm_id!r} lacks polarity failure evidence"
            )
        samples = _manifest_mapping(
            arm.get("sample_coordinate_keys_by_gate"),
            f"arm {arm_id!r} coordinate evidence",
        ).get("polarity_preservation")
        if (
            not isinstance(samples, list)
            or any(not isinstance(item, str) for item in samples)
        ):
            raise ContractError(
                f"SRT-021 arm {arm_id!r} polarity coordinates are malformed"
            )
        for coordinate_key in samples:
            coordinate = _coordinate_payload(coordinate_key)
            if coordinate["arm_id"] != arm_id:
                raise ContractError(
                    "SRT-021 coordinate does not match its owning arm"
                )
        return tuple(samples)

    model_coordinates = tuple(
        coordinate
        for coordinate in polarity_coordinates(_SRT021_MODEL_ARM)
        if coordinate.startswith("legal_doc_1|")
    )
    modal_coordinates = polarity_coordinates(_SRT021_MODAL_SPACY_ARM)
    observed = tuple(sorted((*model_coordinates, *modal_coordinates)))
    if observed != _SRT021_RELEVANT_COORDINATE_KEYS:
        raise ContractError(
            "SRT-021 legal_doc/model or modal-spaCy polarity coordinates "
            "differ from the frozen evidence"
        )
    return observed


def load_srt021_remediation_evidence(
    repo_root: Path | None = None,
    *,
    manifest: Mapping[str, object] | None = None,
    manifest_gate_cid: str = SRT021_MANIFEST_GATE_CID,
) -> SRT021RemediationEvidence:
    """Load and fail-closed validate the exact checked-in SRT-021 evidence."""

    gate_cid = _require_cid(
        manifest_gate_cid,
        codec="dag-json",
        label="SRT-021 manifest gate CID",
    )
    if gate_cid != SRT021_MANIFEST_GATE_CID:
        raise ContractError("SRT-021 manifest gate CID is not the frozen gate")

    raw: bytes | None = None
    if manifest is None:
        root = (
            Path(__file__).resolve().parents[2]
            if repo_root is None
            else Path(repo_root).resolve()
        )
        path = root / SRT021_MANIFEST_RELATIVE_PATH
        try:
            raw = path.read_bytes()
            decoded = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(
                "SRT-021 remediation manifest is unavailable or malformed"
            ) from exc
        manifest_value = _manifest_mapping(decoded, "manifest")
    else:
        manifest_value = _manifest_mapping(manifest, "manifest")

    expected_keys = {
        "interface",
        "schema_version",
        "status",
        "source",
        "remediation",
        "protocol_immutable",
        "replacement_run_required",
        "srt015_fenced",
        "manifest_cid",
    }
    if set(manifest_value) != expected_keys:
        raise ContractError("SRT-021 remediation manifest fields changed")
    if (
        manifest_value.get("interface") != _SRT021_MANIFEST_INTERFACE
        or manifest_value.get("schema_version") != _SRT021_MANIFEST_SCHEMA
        or manifest_value.get("status") != "frozen_no_eligible"
        or manifest_value.get("protocol_immutable") is not True
        or manifest_value.get("replacement_run_required") is not True
        or manifest_value.get("srt015_fenced") is not True
    ):
        raise ContractError("SRT-021 remediation manifest contract changed")

    supplied_manifest_cid = _require_cid(
        manifest_value.get("manifest_cid"),
        codec="dag-json",
        label="SRT-021 manifest CID",
    )
    cid_payload = dict(manifest_value)
    del cid_payload["manifest_cid"]
    if (
        cid_for_dag_json(cid_payload) != supplied_manifest_cid
        or supplied_manifest_cid != SRT021_MANIFEST_CID
    ):
        raise ContractError(
            "SRT-021 remediation manifest CID or frozen identity changed"
        )

    expected_source = {
        "srt014_report_path": _SRT014_REPORT_PATH,
        "srt014_report_cid": SRT014_REPORT_CID,
        "srt014_report_raw_cid": _SRT014_REPORT_RAW_CID,
        "srt014_gate_cid": _SRT014_GATE_CID,
    }
    source = _manifest_mapping(manifest_value.get("source"), "source lineage")
    if dict(source) != expected_source:
        raise ContractError("SRT-021 source report lineage changed")
    for field, codec in (
        ("srt014_report_cid", "dag-json"),
        ("srt014_report_raw_cid", "raw"),
        ("srt014_gate_cid", "dag-json"),
    ):
        _require_cid(
            source.get(field),
            codec=codec,
            label=f"SRT-021 source {field}",
        )

    remediation = _manifest_mapping(
        manifest_value.get("remediation"), "remediation evidence"
    )
    arms = _manifest_mapping(remediation.get("arms"), "arm evidence")
    if (
        remediation.get("classification")
        != "all_preregistered_arms_failed_selection_eligibility"
        or remediation.get("arm_count") != 30
        or remediation.get("eligible_arm_count") != 0
        or len(arms) != 30
        or sum(
            int(_manifest_mapping(arm, "arm").get("coordinate_count", -1))
            for arm in arms.values()
        )
        != 670
        or remediation.get("terminal_failure_reason_counts")
        != {
            "empty_l2": 85,
            "invalid_output": 5,
            "post_schedule_capability_unavailable": 260,
        }
    ):
        raise ContractError("SRT-021 aggregate remediation evidence changed")
    gate_evidence = _manifest_mapping(
        remediation.get("gate_evidence"), "selection gate evidence"
    )
    if {
        gate: _manifest_mapping(gate_evidence.get(gate), gate).get(
            "failed_coordinate_count"
        )
        for gate in (
            "source_copy_exclusion",
            "polarity_preservation",
            "full_coverage",
        )
    } != {
        "source_copy_exclusion": 271,
        "polarity_preservation": 579,
        "full_coverage": 350,
    }:
        raise ContractError("SRT-021 selection gate evidence changed")
    coordinates = _extract_srt021_coordinate_keys(manifest_value)

    if raw is not None:
        raw_cid = cid_for_bytes(raw)
        if raw_cid != _SRT021_MANIFEST_RAW_CID:
            raise ContractError("SRT-021 manifest raw CID changed")
        gate_payload = {
            "schema": _SRT021_MANIFEST_GATE_SCHEMA,
            "report_path": _SRT014_REPORT_PATH,
            "srt014_gate_cid": _SRT014_GATE_CID,
            "srt014_report_cid": SRT014_REPORT_CID,
            "srt014_report_raw_cid": _SRT014_REPORT_RAW_CID,
            "manifest_path": str(SRT021_MANIFEST_RELATIVE_PATH),
            "manifest_cid": SRT021_MANIFEST_CID,
            "manifest_raw_cid": raw_cid,
            "reason_codes": ["no_eligible_remediation_manifest_valid"],
            "status": "valid",
            "valid": True,
        }
        if cid_for_dag_json(gate_payload) != gate_cid:
            raise ContractError(
                "SRT-021 manifest gate CID does not match repository evidence"
            )

    evidence = SRT021RemediationEvidence(
        manifest_cid=supplied_manifest_cid,
        manifest_gate_cid=gate_cid,
        report_cid=str(source["srt014_report_cid"]),
        remediation_targets=_SRT021_REMEDIATION_TARGETS,
        coordinate_keys=coordinates,
    )
    if evidence != FROZEN_SRT021_REMEDIATION_EVIDENCE:
        raise ContractError("SRT-021 remediation evidence is not frozen")
    return evidence


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    """Outcome-independent retry policy fixed before an experiment starts.

    The promotion default permits at most one retry inside the SRT-023
    replacement namespace.  An optional research policy may declare a larger
    preregistered retry budget without changing that promotion default.
    """

    replacement_experiment_id: str
    max_retries: int = 1
    retryable_rejections: tuple[str, ...] = tuple(
        sorted(_RETRYABLE_REJECTIONS)
    )
    remediation_evidence: SRT021RemediationEvidence = (
        FROZEN_SRT021_REMEDIATION_EVIDENCE
    )
    kind: RecoveryPolicyKind = RecoveryPolicyKind.PROMOTION

    def __post_init__(self) -> None:
        experiment_id = self.replacement_experiment_id
        if (
            not isinstance(experiment_id, str)
            or not experiment_id.strip()
            or len(experiment_id) > 160
        ):
            raise ContractError(
                "replacement_experiment_id must be a bounded nonblank string"
            )
        try:
            kind = RecoveryPolicyKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise ContractError(
                "recovery policy kind must be promotion or research"
            ) from exc
        if (
            isinstance(self.max_retries, bool)
            or not isinstance(self.max_retries, int)
        ):
            raise ContractError("max_retries must be a non-boolean integer")
        retryable = self.retryable_rejections
        if (
            not isinstance(retryable, Sequence)
            or isinstance(retryable, (str, bytes, bytearray))
            or len(set(retryable)) != len(retryable)
            or any(item not in _RETRYABLE_REJECTIONS for item in retryable)
        ):
            raise ContractError(
                "retryable_rejections must be a unique bounded preregistration"
            )
        if kind is RecoveryPolicyKind.PROMOTION:
            if self.max_retries not in {0, 1}:
                raise ContractError(
                    "promotion model-output recovery permits at most one retry"
                )
            if self.max_retries and not experiment_id.strip().startswith(
                _PROMOTION_EXPERIMENT_PREFIX
            ):
                raise ContractError(
                    "a promotion retry is permitted only inside the SRT-023 "
                    "replacement experiment namespace"
                )
        else:
            if (
                self.max_retries < 2
                or self.max_retries > _RESEARCH_MAX_RETRIES_CAP
            ):
                raise ContractError(
                    "research recovery requires a preregistered retry budget "
                    "greater than one and at most "
                    f"{_RESEARCH_MAX_RETRIES_CAP}"
                )
            if not experiment_id.strip().startswith(
                _RESEARCH_EXPERIMENT_PREFIX
            ):
                raise ContractError(
                    "research recovery must use the research-recovery "
                    "experiment namespace"
                )
        object.__setattr__(
            self, "replacement_experiment_id", experiment_id.strip()
        )
        object.__setattr__(self, "retryable_rejections", tuple(retryable))
        object.__setattr__(self, "kind", kind)
        if (
            not isinstance(
                self.remediation_evidence, SRT021RemediationEvidence
            )
            or self.remediation_evidence
            != FROZEN_SRT021_REMEDIATION_EVIDENCE
        ):
            raise ContractError(
                "recovery policy must bind the exact frozen SRT-021 evidence"
            )

    def permits(self, rejection: str) -> bool:
        return (
            self.max_retries > 0
            and rejection in self.retryable_rejections
        )

    @property
    def is_promotion_default(self) -> bool:
        return self.kind is RecoveryPolicyKind.PROMOTION

    @property
    def is_research(self) -> bool:
        return self.kind is RecoveryPolicyKind.RESEARCH

    def _payload(self) -> dict[str, object]:
        return {
            "replacement_experiment_id": self.replacement_experiment_id,
            "kind": self.kind.value,
            "max_attempts": self.max_retries + 1,
            "max_retries": self.max_retries,
            "retryable_rejections": list(self.retryable_rejections),
            "outcome_adaptive_extension_allowed": False,
            "remediation_evidence": self.remediation_evidence.to_dict(),
        }

    @property
    def policy_cid(self) -> str:
        return cid_for_dag_json(self._payload())

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "policy_cid": self.policy_cid}

    @classmethod
    def validate_dict(cls, value: object) -> str:
        if not isinstance(value, Mapping):
            raise ContractError("recovery policy receipt must be an object")
        supplied = dict(value)
        policy_cid = _require_cid(
            supplied.pop("policy_cid", None),
            codec="dag-json",
            label="recovery policy CID",
        )
        if cid_for_dag_json(supplied) != policy_cid:
            raise ContractError("recovery policy CID does not match payload")
        SRT021RemediationEvidence.validate_dict(
            supplied.get("remediation_evidence")
        )
        try:
            kind_value = supplied.get("kind", RecoveryPolicyKind.PROMOTION.value)
            policy = cls(
                replacement_experiment_id=str(
                    supplied["replacement_experiment_id"]
                ),
                max_retries=int(supplied["max_retries"]),
                retryable_rejections=tuple(
                    supplied["retryable_rejections"]  # type: ignore[arg-type]
                ),
                kind=RecoveryPolicyKind(str(kind_value)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("recovery policy payload is malformed") from exc
        if policy.to_dict() != dict(value):
            raise ContractError("recovery policy payload is contradictory")
        return policy_cid


PREREGISTERED_SRT023_POLICY: Final = RecoveryPolicy(
    replacement_experiment_id="srt-023-replacement-model-remediation-v1",
    kind=RecoveryPolicyKind.PROMOTION,
)
# Alias retained for callers that name the promotion default explicitly.
PROMOTION_RECOVERY_POLICY: Final = PREREGISTERED_SRT023_POLICY

PREREGISTERED_RESEARCH_RECOVERY_POLICY: Final = RecoveryPolicy(
    replacement_experiment_id="research-recovery-leanstral-reliability-v1",
    max_retries=3,
    kind=RecoveryPolicyKind.RESEARCH,
)


def _expected_symai_route_receipt(
    *, schema_name: str, max_tokens: int
) -> dict[str, object]:
    """Return the only SyMAI route receipt valid for one physical call."""

    return {
        "role": schema_name,
        "routing": {
            "route": SYMAI_ROUTE,
            "orchestrator": SYMAI_ORCHESTRATOR,
            "orchestrator_version": SYMAI_VERSION,
            "router_provider": SYMAI_PROVIDER,
            "model_alias": SYMAI_MODEL_ALIAS,
            "resolved_provider": LEANSTRAL_PROVIDER,
            "resolved_endpoint": LEANSTRAL_ENDPOINT,
            "resolved_model": LEANSTRAL_MODEL,
            "resolved_backend": LEANSTRAL_BACKEND,
            "shared_capacity": LEANSTRAL_CAPACITY,
        },
        "model_settings": SyMAIGenerationSettings.for_role(
            max_tokens
        ).to_dict(),
        "retry": {
            "policy": "none",
            "attempts": 1,
            "retries": 0,
        },
        "cache": {
            "enabled": False,
            "hit": False,
        },
        "attribution": {
            "independent_model_evidence": False,
            "comparison_scope": "incremental_symai_orchestration_only",
        },
        "canonical_contract_validated": False,
        "ranking_eligible": False,
        "ranking_exclusion_reason": None,
    }


def _validate_call_route_receipt(
    *,
    route: RecoveryRoute,
    outcome: str,
    schema_name: str,
    max_tokens: int,
    route_receipt: object,
) -> None:
    """Enforce direct/SyMAI coupling and the exact pinned router identity."""

    if route is RecoveryRoute.DIRECT:
        if route_receipt is not None:
            raise ContractError(
                "direct model call cannot carry a SyMAI route receipt"
            )
        return
    if outcome == "call_failed":
        if route_receipt is not None:
            raise ContractError(
                "failed SyMAI call cannot claim a completed route receipt"
            )
        return
    if route_receipt is None:
        raise ContractError(
            "accepted or rejected SyMAI call needs a route receipt"
        )
    if not isinstance(route_receipt, Mapping):
        raise ContractError("SyMAI route receipt must be an object")
    observed = _thaw_json(route_receipt)
    expected = _expected_symai_route_receipt(
        schema_name=schema_name,
        max_tokens=max_tokens,
    )
    try:
        exact = (
            observed == expected
            and cid_for_dag_json(observed) == cid_for_dag_json(expected)
        )
    except (TypeError, ValueError) as exc:
        raise ContractError(
            "SyMAI route receipt is not canonical DAG-JSON"
        ) from exc
    if not exact:
        raise ContractError(
            "SyMAI route receipt drifted from the pinned route identity"
        )


@dataclass(frozen=True, slots=True)
class ModelCallReceipt:
    """A source-free record of one physical model call."""

    call_number: int
    serialized_call_ordinal: int
    attempt_kind: str
    role: RecoveryRole
    route: RecoveryRoute
    request_cid: str
    prompt_cid: str
    schema_name: str
    max_tokens: int
    outcome: str
    rejection: str | None = None
    rejection_reason: str | None = None
    failure_reason: FailureReason | None = None
    detail: str | None = None
    symai_route_receipt: Mapping[str, object] | None = None
    receipt_cid: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.call_number) is not int
            or type(self.serialized_call_ordinal) is not int
            or self.call_number < 1
            or self.serialized_call_ordinal < 1
        ):
            raise ContractError("model call ordinals must be positive")
        _require_cid(
            self.request_cid,
            codec="dag-json",
            label="model call request CID",
        )
        _require_cid(
            self.prompt_cid,
            codec="raw",
            label="model call prompt CID",
        )
        if not isinstance(self.role, RecoveryRole) or not isinstance(
            self.route, RecoveryRoute
        ):
            raise ContractError("model call role or route is invalid")
        allowed_schema_names = {
            _STANDARD_SCHEMA_NAMES[self.role],
            _SINGLE_RULE_RESEARCH_SCHEMA_NAMES[self.role],
        }
        expected_max_tokens = (
            REALIZER_MAX_TOKENS
            if self.role is RecoveryRole.T1
            else CONSTRUCTOR_MAX_TOKENS
        )
        if (
            self.schema_name not in allowed_schema_names
            or type(self.max_tokens) is not int
            or self.max_tokens != expected_max_tokens
        ):
            raise ContractError("model call schema or token bound is invalid")
        if self.attempt_kind not in {"initial", "preregistered_retry"}:
            raise ContractError("model call attempt kind is invalid")
        if self.outcome not in {"accepted", "rejected", "call_failed"}:
            raise ContractError("model call outcome is invalid")
        if self.outcome == "accepted" and (
            self.rejection is not None
            or self.rejection_reason is not None
            or self.failure_reason is not None
        ):
            raise ContractError("accepted model call cannot carry a failure")
        if self.outcome != "accepted" and self.failure_reason is None:
            raise ContractError("failed model call needs a typed failure")
        if self.outcome != "accepted" and (
            not isinstance(self.rejection, str)
            or not self.rejection.strip()
        ):
            raise ContractError(
                "failed model call needs a nonblank rejection"
            )
        if self.outcome != "accepted":
            expected_reason = classify_model_rejection(self.rejection)
            assert expected_reason is not None
            if self.rejection_reason is None:
                object.__setattr__(
                    self, "rejection_reason", expected_reason.value
                )
            elif self.rejection_reason != expected_reason.value:
                raise ContractError(
                    "model call rejection_reason does not match taxonomy"
                )
            if self.rejection_reason not in TYPED_REJECTION_REASONS:
                raise ContractError(
                    "model call rejection_reason is outside the closed taxonomy"
                )
        _validate_call_route_receipt(
            route=self.route,
            outcome=self.outcome,
            schema_name=self.schema_name,
            max_tokens=self.max_tokens,
            route_receipt=self.symai_route_receipt,
        )
        if self.symai_route_receipt is not None:
            object.__setattr__(
                self,
                "symai_route_receipt",
                _freeze_json(self.symai_route_receipt),
            )
        expected_cid = cid_for_dag_json(self._payload())
        if self.receipt_cid is None:
            object.__setattr__(self, "receipt_cid", expected_cid)
        elif (
            _require_cid(
                self.receipt_cid,
                codec="dag-json",
                label="model call receipt CID",
            )
            != expected_cid
        ):
            raise ContractError(
                "model call receipt CID does not match payload"
            )

    def _payload(self) -> dict[str, object]:
        return {
            "call_number": self.call_number,
            "serialized_call_ordinal": self.serialized_call_ordinal,
            "attempt_kind": self.attempt_kind,
            "role": self.role.value,
            "route": self.route.value,
            "route_id": self.route.route_id,
            "request_cid": self.request_cid,
            "prompt_cid": self.prompt_cid,
            "schema_name": self.schema_name,
            "max_tokens": self.max_tokens,
            "cache": {
                "prompt_cache_enabled": False,
                "response_cache_enabled": False,
                "cache_hit": False,
                "result_reused": False,
            },
            "outcome": self.outcome,
            "rejection": self.rejection,
            "rejection_reason": self.rejection_reason,
            "failure_reason": (
                None
                if self.failure_reason is None
                else self.failure_reason.value
            ),
            "detail": self.detail,
            "symai_route_receipt": (
                None
                if self.symai_route_receipt is None
                else _thaw_json(self.symai_route_receipt)
            ),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "receipt_cid": self.receipt_cid}

    @classmethod
    def from_dict(cls, value: object) -> ModelCallReceipt:
        """Validate and restore one call receipt without trusting its fields."""

        if not isinstance(value, Mapping):
            raise ContractError("model call receipt must be an object")
        supplied = dict(value)
        if set(supplied) != {
            "call_number",
            "serialized_call_ordinal",
            "attempt_kind",
            "role",
            "route",
            "route_id",
            "request_cid",
            "prompt_cid",
            "schema_name",
            "max_tokens",
            "cache",
            "outcome",
            "rejection",
            "rejection_reason",
            "failure_reason",
            "detail",
            "symai_route_receipt",
            "receipt_cid",
        }:
            raise ContractError("model call receipt fields changed")
        receipt_cid = _require_cid(
            supplied["receipt_cid"],
            codec="dag-json",
            label="model call receipt CID",
        )
        body = dict(supplied)
        del body["receipt_cid"]
        if cid_for_dag_json(body) != receipt_cid:
            raise ContractError(
                "model call receipt CID does not match payload"
            )
        try:
            role = RecoveryRole(supplied["role"])
            route = RecoveryRoute(supplied["route"])
        except (TypeError, ValueError) as exc:
            raise ContractError("model call role or route is invalid") from exc
        if supplied["route_id"] != route.route_id or supplied["cache"] != {
            "prompt_cache_enabled": False,
            "response_cache_enabled": False,
            "cache_hit": False,
            "result_reused": False,
        }:
            raise ContractError("model call route or cache identity changed")
        raw_failure = supplied["failure_reason"]
        try:
            failure_reason = (
                None
                if raw_failure is None
                else FailureReason(raw_failure)
            )
        except (TypeError, ValueError) as exc:
            raise ContractError(
                "model call failure reason is invalid"
            ) from exc
        route_receipt = supplied["symai_route_receipt"]
        if route_receipt is not None and not isinstance(route_receipt, Mapping):
            raise ContractError("SyMAI route receipt must be an object")
        try:
            restored = cls(
                call_number=supplied["call_number"],  # type: ignore[arg-type]
                serialized_call_ordinal=supplied[  # type: ignore[arg-type]
                    "serialized_call_ordinal"
                ],
                attempt_kind=supplied["attempt_kind"],  # type: ignore[arg-type]
                role=role,
                route=route,
                request_cid=supplied["request_cid"],  # type: ignore[arg-type]
                prompt_cid=supplied["prompt_cid"],  # type: ignore[arg-type]
                schema_name=supplied["schema_name"],  # type: ignore[arg-type]
                max_tokens=supplied["max_tokens"],  # type: ignore[arg-type]
                outcome=supplied["outcome"],  # type: ignore[arg-type]
                rejection=supplied["rejection"],  # type: ignore[arg-type]
                rejection_reason=supplied[  # type: ignore[arg-type]
                    "rejection_reason"
                ],
                failure_reason=failure_reason,
                detail=supplied["detail"],  # type: ignore[arg-type]
                symai_route_receipt=route_receipt,
                receipt_cid=receipt_cid,
            )
        except ContractError:
            raise
        except (TypeError, ValueError) as exc:
            raise ContractError("model call receipt is malformed") from exc
        if restored.to_dict() != supplied:
            raise ContractError("model call receipt is contradictory")
        return restored


@dataclass(frozen=True, slots=True)
class ModelOutputRecoveryReceipt:
    """Complete evidence for one recovery invocation."""

    role: RecoveryRole
    route: RecoveryRoute
    request_cid: str
    policy: RecoveryPolicy
    calls: tuple[ModelCallReceipt, ...]
    status: ComponentStatus
    terminal_failure: FailureReason | None
    terminal_rejection: str | None
    receipt_cid: str | None = None

    def __post_init__(self) -> None:
        _require_cid(
            self.request_cid,
            codec="dag-json",
            label="recovery request CID",
        )
        if (
            not isinstance(self.role, RecoveryRole)
            or not isinstance(self.route, RecoveryRoute)
            or not isinstance(self.policy, RecoveryPolicy)
            or not isinstance(self.status, ComponentStatus)
            or self.policy.remediation_evidence
            != FROZEN_SRT021_REMEDIATION_EVIDENCE
        ):
            raise ContractError(
                "recovery receipt identity or remediation evidence is invalid"
            )
        if (
            not isinstance(self.calls, tuple)
            or not self.calls
            or any(
                not isinstance(call, ModelCallReceipt)
                for call in self.calls
            )
        ):
            raise ContractError("a recovery receipt must retain a model call")
        if len(self.calls) > self.policy.max_retries + 1:
            raise ContractError("receipt exceeds the preregistered call bound")
        if any(
            call.call_number != index
            or call.role is not self.role
            or call.route is not self.route
            or call.request_cid != self.request_cid
            for index, call in enumerate(self.calls, start=1)
        ):
            raise ContractError("recovery call lineage is inconsistent")
        if any(
            call.attempt_kind
            != ("initial" if index == 1 else "preregistered_retry")
            for index, call in enumerate(self.calls, start=1)
        ):
            raise ContractError("recovery retry lineage is inconsistent")
        if any(
            later.serialized_call_ordinal
            <= earlier.serialized_call_ordinal
            for earlier, later in zip(
                self.calls, self.calls[1:], strict=False
            )
        ):
            raise ContractError(
                "recovery serialized call order is inconsistent"
            )
        for call in self.calls[:-1]:
            if (
                call.outcome == "accepted"
                or call.rejection is None
                or not self.policy.permits(call.rejection)
            ):
                raise ContractError(
                    "recovery retry transition is not policy-permitted"
                )
        if self.status is ComponentStatus.SUCCESS:
            if (
                self.terminal_failure is not None
                or self.terminal_rejection is not None
                or self.calls[-1].outcome != "accepted"
            ):
                raise ContractError("successful recovery receipt is inconsistent")
        elif (
            self.terminal_failure is None
            or self.calls[-1].outcome == "accepted"
            or self.calls[-1].rejection != self.terminal_rejection
        ):
            raise ContractError("failed recovery receipt is inconsistent")
        elif len(self.calls) == 1:
            if self.terminal_failure is not self.calls[-1].failure_reason:
                raise ContractError(
                    "one-call failure must retain the call failure reason"
                )
        elif self.terminal_failure is not FailureReason.RETRY_EXHAUSTED:
            raise ContractError(
                "exhausted retry must use the retry-exhausted failure reason"
            )
        # Every failed call must carry a taxonomy-class rejection reason.
        for call in self.calls:
            if call.outcome == "accepted":
                continue
            if (
                call.rejection_reason is None
                or call.rejection_reason not in TYPED_REJECTION_REASONS
            ):
                raise ContractError(
                    "failed model call must record a typed rejection reason"
                )
        expected_cid = cid_for_dag_json(self._payload())
        if self.receipt_cid is None:
            object.__setattr__(self, "receipt_cid", expected_cid)
        elif (
            _require_cid(
                self.receipt_cid,
                codec="dag-json",
                label="model-output recovery receipt CID",
            )
            != expected_cid
        ):
            raise ContractError(
                "model-output recovery receipt CID does not match payload"
            )

    @property
    def rejections(self) -> tuple[ModelCallReceipt, ...]:
        return tuple(call for call in self.calls if call.outcome != "accepted")

    @property
    def retries(self) -> int:
        return max(0, len(self.calls) - 1)

    @property
    def terminal_rejection_reason(self) -> str | None:
        mapped = classify_model_rejection(self.terminal_rejection)
        return None if mapped is None else mapped.value

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": MODEL_OUTPUT_RECOVERY_SCHEMA_VERSION,
            "interface": BOUNDED_MODEL_OUTPUT_RECOVERY_INTERFACE,
            "polarity_interface": SYMAI_POLARITY_CONTRACT_INTERFACE,
            "role": self.role.value,
            "identity": {
                "provider": LEANSTRAL_PROVIDER,
                "endpoint": LEANSTRAL_ENDPOINT,
                "backend": LEANSTRAL_BACKEND,
                "backend_owner": LEANSTRAL_BACKEND_OWNER,
                "model": LEANSTRAL_MODEL,
                "tokenizer": LEANSTRAL_TOKENIZER_IDENTITY,
                "route": self.route.value,
                "route_id": self.route.route_id,
                "direct_and_symai_are_independent_models": False,
                "physical_model_slots": LEANSTRAL_CAPACITY,
                "execution": "globally_serialized_one_slot",
            },
            "boundary": {
                "source_withheld": self.role is RecoveryRole.T1,
                "source_recovery_allowed": False,
                "fallback_allowed": False,
                "route_substitution_allowed": False,
                "cross_call_result_reuse_allowed": False,
            },
            "cache": {
                "prompt_cache_enabled": False,
                "response_cache_enabled": False,
                "cache_hit": False,
            },
            "request_cid": self.request_cid,
            "remediation_evidence": (
                self.policy.remediation_evidence.to_dict()
            ),
            "policy": self.policy.to_dict(),
            "calls": [call.to_dict() for call in self.calls],
            "call_count": len(self.calls),
            "rejection_count": len(self.rejections),
            "retry_count": self.retries,
            "status": self.status.value,
            "terminal_failure": (
                None
                if self.terminal_failure is None
                else self.terminal_failure.value
            ),
            "terminal_rejection": self.terminal_rejection,
            "terminal_rejection_reason": self.terminal_rejection_reason,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "receipt_cid": self.receipt_cid}

    @classmethod
    def from_dict(cls, value: object) -> ModelOutputRecoveryReceipt:
        """Fail-closed restore a receipt and verify all content links."""

        if not isinstance(value, Mapping):
            raise ContractError("model-output recovery receipt must be an object")
        supplied = dict(value)
        expected_fields = {
            "schema_version",
            "interface",
            "polarity_interface",
            "role",
            "identity",
            "boundary",
            "cache",
            "request_cid",
            "remediation_evidence",
            "policy",
            "calls",
            "call_count",
            "rejection_count",
            "retry_count",
            "status",
            "terminal_failure",
            "terminal_rejection",
            "terminal_rejection_reason",
            "receipt_cid",
        }
        if set(supplied) != expected_fields:
            raise ContractError("model-output recovery receipt fields changed")
        receipt_cid = _require_cid(
            supplied["receipt_cid"],
            codec="dag-json",
            label="model-output recovery receipt CID",
        )
        body = dict(supplied)
        del body["receipt_cid"]
        if cid_for_dag_json(body) != receipt_cid:
            raise ContractError(
                "model-output recovery receipt CID does not match payload"
            )
        if (
            supplied["schema_version"]
            != MODEL_OUTPUT_RECOVERY_SCHEMA_VERSION
            or supplied["interface"]
            != BOUNDED_MODEL_OUTPUT_RECOVERY_INTERFACE
            or supplied["polarity_interface"]
            != SYMAI_POLARITY_CONTRACT_INTERFACE
        ):
            raise ContractError("model-output recovery interface changed")
        SRT021RemediationEvidence.validate_dict(
            supplied["remediation_evidence"]
        )
        policy_value = supplied["policy"]
        RecoveryPolicy.validate_dict(policy_value)
        if not isinstance(policy_value, Mapping):
            raise ContractError("recovery policy receipt must be an object")
        if (
            type(policy_value.get("max_retries")) is not int
            or not isinstance(
                policy_value.get("replacement_experiment_id"), str
            )
            or not isinstance(
                policy_value.get("retryable_rejections"), list
            )
        ):
            raise ContractError("recovery policy payload is malformed")
        kind_raw = policy_value.get(
            "kind", RecoveryPolicyKind.PROMOTION.value
        )
        try:
            kind = RecoveryPolicyKind(str(kind_raw))
        except (TypeError, ValueError) as exc:
            raise ContractError(
                "recovery policy kind is invalid"
            ) from exc
        policy = RecoveryPolicy(
            replacement_experiment_id=policy_value[
                "replacement_experiment_id"
            ],
            max_retries=policy_value["max_retries"],
            retryable_rejections=tuple(
                policy_value["retryable_rejections"]
            ),
            kind=kind,
        )
        raw_calls = supplied["calls"]
        if not isinstance(raw_calls, list):
            raise ContractError("recovery calls must be an array")
        calls = tuple(ModelCallReceipt.from_dict(call) for call in raw_calls)
        try:
            role = RecoveryRole(supplied["role"])
            route = RecoveryRoute(
                _manifest_mapping(
                    supplied["identity"], "receipt identity"
                ).get("route")
            )
            status = ComponentStatus(supplied["status"])
            raw_failure = supplied["terminal_failure"]
            terminal_failure = (
                None
                if raw_failure is None
                else FailureReason(raw_failure)
            )
        except (TypeError, ValueError) as exc:
            raise ContractError(
                "model-output recovery receipt enums are invalid"
            ) from exc
        try:
            restored = cls(
                role=role,
                route=route,
                request_cid=supplied["request_cid"],  # type: ignore[arg-type]
                policy=policy,
                calls=calls,
                status=status,
                terminal_failure=terminal_failure,
                terminal_rejection=supplied[  # type: ignore[arg-type]
                    "terminal_rejection"
                ],
                receipt_cid=receipt_cid,
            )
        except ContractError:
            raise
        except (TypeError, ValueError) as exc:
            raise ContractError(
                "model-output recovery receipt is malformed"
            ) from exc
        if restored.to_dict() != supplied:
            raise ContractError(
                "model-output recovery receipt is contradictory"
            )
        return restored

    @classmethod
    def validate_dict(cls, value: object) -> str:
        """Validate a serialized receipt and return its canonical CID."""

        restored = cls.from_dict(value)
        assert restored.receipt_cid is not None
        return restored.receipt_cid


@dataclass(frozen=True, slots=True)
class ModelOutputRecoveryResult:
    """Typed value or typed terminal failure from the recovery wrapper."""

    role: RecoveryRole
    status: ComponentStatus
    receipt: ModelOutputRecoveryReceipt
    canonical_ir: CanonicalRuleIR | None = None
    text: str | None = None
    failure_reason: FailureReason | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if self.status is ComponentStatus.SUCCESS:
            expected_ir = self.role in {RecoveryRole.L1, RecoveryRole.L2}
            if expected_ir != (self.canonical_ir is not None):
                raise ContractError("successful recovery value has wrong role")
            if (self.role is RecoveryRole.T1) != (self.text is not None):
                raise ContractError("successful recovery text has wrong role")
            if self.failure_reason is not None:
                raise ContractError("successful recovery cannot carry failure")
        elif self.failure_reason is None:
            raise ContractError("failed recovery result needs typed failure")


@dataclass(frozen=True, slots=True)
class ArmReliabilityMetrics:
    """Per-arm model reliability rates, separate from end-to-end loss.

    ``accept_rate`` is the fraction of recovery invocations that accepted a
    model output under the preregistered policy.  ``retry_exhausted_rate`` is
    the fraction that terminated as ``retry_exhausted``.  Neither field is an
    end-to-end semantic loss and must not be substituted for one.
    """

    arm_id: str
    recovery_invocations: int
    accepted_recoveries: int
    retry_exhausted_recoveries: int
    model_calls: int
    accepted_calls: int
    rejection_reason_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        if not isinstance(self.arm_id, str) or not self.arm_id.strip():
            raise ContractError("arm_id must be a nonblank string")
        for name, value in (
            ("recovery_invocations", self.recovery_invocations),
            ("accepted_recoveries", self.accepted_recoveries),
            ("retry_exhausted_recoveries", self.retry_exhausted_recoveries),
            ("model_calls", self.model_calls),
            ("accepted_calls", self.accepted_calls),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ContractError(f"{name} must be a non-negative integer")
        if self.accepted_recoveries > self.recovery_invocations:
            raise ContractError("accepted_recoveries exceeds invocations")
        if self.retry_exhausted_recoveries > self.recovery_invocations:
            raise ContractError(
                "retry_exhausted_recoveries exceeds invocations"
            )
        if self.accepted_calls > self.model_calls:
            raise ContractError("accepted_calls exceeds model_calls")
        counts = self.rejection_reason_counts
        if not isinstance(counts, Mapping):
            raise ContractError("rejection_reason_counts must be a mapping")
        normalized: dict[str, int] = {}
        for key, value in counts.items():
            if key not in TYPED_REJECTION_REASONS:
                raise ContractError(
                    "rejection_reason_counts keys must use the closed taxonomy"
                )
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ContractError(
                    "rejection_reason_counts values must be non-negative"
                )
            if value:
                normalized[str(key)] = value
        object.__setattr__(self, "arm_id", self.arm_id.strip())
        object.__setattr__(
            self,
            "rejection_reason_counts",
            MappingProxyType(normalized),
        )

    @property
    def accept_rate(self) -> float:
        if self.recovery_invocations == 0:
            return 0.0
        return self.accepted_recoveries / self.recovery_invocations

    @property
    def retry_exhausted_rate(self) -> float:
        if self.recovery_invocations == 0:
            return 0.0
        return self.retry_exhausted_recoveries / self.recovery_invocations

    def to_dict(self) -> dict[str, object]:
        return {
            "arm_id": self.arm_id,
            "accept_rate": self.accept_rate,
            "retry_exhausted_rate": self.retry_exhausted_rate,
            "recovery_invocations": self.recovery_invocations,
            "accepted_recoveries": self.accepted_recoveries,
            "retry_exhausted_recoveries": self.retry_exhausted_recoveries,
            "model_calls": self.model_calls,
            "accepted_calls": self.accepted_calls,
            "rejection_reason_counts": dict(self.rejection_reason_counts),
            # Explicit contract: these rates are not end-to-end loss.
            "separate_from_end_to_end_loss": True,
            "end_to_end_loss": None,
        }


def arm_reliability_metrics(
    arm_id: str,
    receipts: Sequence[ModelOutputRecoveryReceipt | ModelOutputRecoveryResult],
) -> ArmReliabilityMetrics:
    """Aggregate per-arm accept and retry-exhausted rates from recoveries."""

    if not isinstance(receipts, Sequence) or isinstance(
        receipts, (str, bytes, bytearray)
    ):
        raise ContractError("receipts must be a sequence of recovery receipts")
    accepted = 0
    retry_exhausted = 0
    model_calls = 0
    accepted_calls = 0
    reason_counts: Counter[str] = Counter()
    normalized: list[ModelOutputRecoveryReceipt] = []
    for item in receipts:
        if isinstance(item, ModelOutputRecoveryResult):
            normalized.append(item.receipt)
        elif isinstance(item, ModelOutputRecoveryReceipt):
            normalized.append(item)
        else:
            raise ContractError(
                "receipts must contain ModelOutputRecoveryReceipt values"
            )
    for receipt in normalized:
        if receipt.status is ComponentStatus.SUCCESS:
            accepted += 1
        elif receipt.terminal_failure is FailureReason.RETRY_EXHAUSTED:
            retry_exhausted += 1
        for call in receipt.calls:
            model_calls += 1
            if call.outcome == "accepted":
                accepted_calls += 1
            elif call.rejection_reason is not None:
                reason_counts[call.rejection_reason] += 1
    return ArmReliabilityMetrics(
        arm_id=arm_id,
        recovery_invocations=len(normalized),
        accepted_recoveries=accepted,
        retry_exhausted_recoveries=retry_exhausted,
        model_calls=model_calls,
        accepted_calls=accepted_calls,
        rejection_reason_counts=dict(reason_counts),
    )


class _Client(Protocol):
    endpoint: str
    model: str


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw_json(item) for item in value]
    return value


def _freeze_json(value: Mapping[str, object]) -> Mapping[str, object]:
    def freeze(item: object) -> object:
        if isinstance(item, Mapping):
            return MappingProxyType(
                {str(key): freeze(nested) for key, nested in item.items()}
            )
        if isinstance(item, (tuple, list)):
            return tuple(freeze(nested) for nested in item)
        return item

    return freeze(dict(value))  # type: ignore[return-value]


class _OutputRejected(ContractError):
    def __init__(
        self,
        rejection: str,
        failure_reason: FailureReason,
        detail: str,
    ) -> None:
        super().__init__(detail)
        self.rejection = rejection
        self.failure_reason = failure_reason
        self.detail = detail


class SyMAIPolarityContract:
    """Strict, role-aware O/P/F schema and output validator.

    The historical name is retained because the modal-plus-SyMAI path exposed
    the motivating failure.  The same contract is intentionally applied to
    the direct route so orchestration is the only route difference.
    """

    interface: Final = SYMAI_POLARITY_CONTRACT_INTERFACE

    _POSITIVE_OBLIGATION = re.compile(
        r"\b(?:must|shall)(?!\s+not\b)|\b(?:is|are)\s+required\s+to\b",
        re.IGNORECASE,
    )
    _PERMISSION = re.compile(
        r"\bmay(?!\s+not\b)|\b(?:is|are)\s+(?:permitted|allowed)\s+to\b",
        re.IGNORECASE,
    )
    _PROHIBITION = re.compile(
        r"\b(?:must|shall)\s+not\b|"
        r"\b(?:is|are)\s+(?:prohibited|forbidden)\s+from\b",
        re.IGNORECASE,
    )
    _AMBIGUOUS_MAY_NOT = re.compile(r"\bmay\s+not\b", re.IGNORECASE)

    @classmethod
    def instructions(cls, role: RecoveryRole) -> str:
        common = (
            "Polarity is mandatory and exclusive: O means obligation "
            "(must/shall), P means permission (may/is permitted to), and F "
            "means prohibition (must not/shall not/is prohibited from). Never "
            "use 'may not', because it is polarity-ambiguous. Never map one "
            "symbol to another or omit a supplied modality."
        )
        if role is RecoveryRole.T1:
            return (
                common
                + " Return exactly one indexed rule object for each input "
                "rule, repeat its unchanged O/P/F modality and matching "
                "polarity label, and use one explicit matching modal phrase "
                "in that rule's text."
            )
        return (
            common
            + " Every canonical rule must contain exactly one modality symbol "
            "from the enum O, P, F."
        )

    @classmethod
    def canonical_schema(
        cls,
        vocabulary: AllowedAtomVocabulary,
    ) -> dict[str, object]:
        schema = canonical_ir_schema(vocabulary)
        rules = schema["properties"]["rules"]  # type: ignore[index]
        rules["minItems"] = 1  # type: ignore[index]
        return schema

    @classmethod
    def single_rule_research_canonical_schema(
        cls,
        vocabulary: AllowedAtomVocabulary,
    ) -> dict[str, object]:
        """Exactly-one-rule canonical schema for hybrid repair research.

        Promotion recovery continues to use :meth:`canonical_schema`.  Hybrid
        selective-repair experiments may opt into this narrower research path
        without changing the production schema default.
        """

        schema = cls.canonical_schema(vocabulary)
        rules = schema["properties"]["rules"]  # type: ignore[index]
        rules["minItems"] = 1  # type: ignore[index]
        rules["maxItems"] = 1  # type: ignore[index]
        return schema

    @classmethod
    def realization_schema(
        cls,
        canonical_ir: CanonicalRuleIR,
    ) -> dict[str, object]:
        count = len(canonical_ir.rules)
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["rules"],
            "properties": {
                "rules": {
                    "type": "array",
                    "minItems": count,
                    "maxItems": count,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "index",
                            "modality",
                            "polarity",
                            "text",
                        ],
                        "properties": {
                            "index": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": max(0, count - 1),
                            },
                            "modality": {
                                "type": "string",
                                "enum": ["O", "P", "F"],
                            },
                            "polarity": {
                                "type": "string",
                                "enum": [
                                    "obligation",
                                    "permission",
                                    "prohibition",
                                ],
                            },
                            "text": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": REALIZATION_MAX_LENGTH,
                            },
                        },
                    },
                }
            },
        }

    @classmethod
    def single_rule_research_realization_schema(
        cls,
        canonical_ir: CanonicalRuleIR,
    ) -> dict[str, object]:
        """Exactly-one-rule realization schema for hybrid repair research."""

        if len(canonical_ir.rules) != 1:
            raise ContractError(
                "single-rule research realization requires exactly one rule"
            )
        return cls.realization_schema(canonical_ir)

    @classmethod
    def validate_canonical(
        cls,
        candidate: object,
        vocabulary: AllowedAtomVocabulary,
        *,
        role: RecoveryRole,
        expected_ir: CanonicalRuleIR | None = None,
    ) -> CanonicalRuleIR:
        if role not in {RecoveryRole.L1, RecoveryRole.L2}:
            raise ContractError("canonical validation requires L1 or L2")
        try:
            canonical_ir = CanonicalRuleIR.from_dict(candidate, vocabulary)
        except (ContractError, TypeError, ValueError) as exc:
            raise _OutputRejected(
                "malformed_output",
                FailureReason.INVALID_OUTPUT,
                f"{role.value.upper()} is not bounded canonical IR",
            ) from exc
        if canonical_ir.is_empty:
            reason = (
                FailureReason.EMPTY_L1
                if role is RecoveryRole.L1
                else FailureReason.EMPTY_L2
            )
            raise _OutputRejected(
                "empty_output",
                reason,
                f"{role.value.upper()} canonical rules are empty",
            )
        if expected_ir is not None:
            expected = Counter(rule.modality for rule in expected_ir.rules)
            observed = Counter(rule.modality for rule in canonical_ir.rules)
            if observed != expected:
                raise _OutputRejected(
                    "polarity_ambiguous",
                    FailureReason.INVALID_OUTPUT,
                    (
                        f"{role.value.upper()} O/P/F multiplicities do not "
                        "preserve the preregistered input IR"
                    ),
                )
        return canonical_ir

    @classmethod
    def validate_realization(
        cls,
        candidate: object,
        canonical_ir: CanonicalRuleIR,
    ) -> str:
        if not isinstance(candidate, Mapping) or set(candidate) != {"rules"}:
            raise _OutputRejected(
                "malformed_output",
                FailureReason.INVALID_OUTPUT,
                "T1 must contain exactly the rules key",
            )
        raw_rules = candidate["rules"]
        if (
            not isinstance(raw_rules, Sequence)
            or isinstance(raw_rules, (str, bytes, bytearray))
        ):
            raise _OutputRejected(
                "malformed_output",
                FailureReason.INVALID_OUTPUT,
                "T1 rules must be an array",
            )
        if not raw_rules:
            raise _OutputRejected(
                "blank_output",
                FailureReason.BLANK_T1,
                "T1 realization is blank",
            )
        if len(raw_rules) != len(canonical_ir.rules):
            raise _OutputRejected(
                "malformed_output",
                FailureReason.INVALID_OUTPUT,
                "T1 must realize every and only the input rules",
            )

        realized: list[str] = []
        for index, (raw, expected) in enumerate(
            zip(raw_rules, canonical_ir.rules, strict=True)
        ):
            if not isinstance(raw, Mapping) or set(raw) != {
                "index",
                "modality",
                "polarity",
                "text",
            }:
                raise _OutputRejected(
                    "malformed_output",
                    FailureReason.INVALID_OUTPUT,
                    f"T1 rule {index} has malformed fields",
                )
            if type(raw["index"]) is not int or raw["index"] != index:
                raise _OutputRejected(
                    "malformed_output",
                    FailureReason.INVALID_OUTPUT,
                    f"T1 rule {index} has a noncanonical index",
                )
            modality = raw["modality"]
            label = raw["polarity"]
            if (
                modality != expected.modality
                or label != _POLARITY_LABELS[expected.modality]
            ):
                raise _OutputRejected(
                    "polarity_ambiguous",
                    FailureReason.INVALID_OUTPUT,
                    f"T1 rule {index} changed or ambiguously labelled polarity",
                )
            text = raw["text"]
            if not isinstance(text, str):
                raise _OutputRejected(
                    "malformed_output",
                    FailureReason.INVALID_OUTPUT,
                    f"T1 rule {index} text must be a string",
                )
            text = " ".join(text.strip().split())
            if not text:
                raise _OutputRejected(
                    "blank_output",
                    FailureReason.BLANK_T1,
                    f"T1 rule {index} text is blank",
                )
            if len(text) > REALIZATION_MAX_LENGTH:
                raise _OutputRejected(
                    "malformed_output",
                    FailureReason.INVALID_OUTPUT,
                    f"T1 rule {index} exceeds the character bound",
                )
            cls._validate_text_polarity(text, expected.modality, index)
            realized.append(text)
        combined = " ".join(realized)
        if len(combined) > REALIZATION_MAX_LENGTH:
            raise _OutputRejected(
                "malformed_output",
                FailureReason.INVALID_OUTPUT,
                "combined T1 realization exceeds the character bound",
            )
        return combined

    @classmethod
    def _validate_text_polarity(
        cls,
        text: str,
        expected: str,
        index: int,
    ) -> None:
        if cls._AMBIGUOUS_MAY_NOT.search(text):
            raise _OutputRejected(
                "polarity_ambiguous",
                FailureReason.INVALID_OUTPUT,
                f"T1 rule {index} uses ambiguous 'may not' polarity",
            )
        observed = {
            modality
            for modality, pattern in (
                ("O", cls._POSITIVE_OBLIGATION),
                ("P", cls._PERMISSION),
                ("F", cls._PROHIBITION),
            )
            if pattern.search(text)
        }
        if observed != {expected}:
            raise _OutputRejected(
                "polarity_ambiguous",
                FailureReason.INVALID_OUTPUT,
                (
                    f"T1 rule {index} must contain exactly one explicit "
                    f"{expected} polarity construction"
                ),
            )


_SERIALIZATION_LOCK = threading.Lock()
_ORDINAL_LOCK = threading.Lock()
_NEXT_SERIALIZED_CALL = 0


def _next_ordinal() -> int:
    global _NEXT_SERIALIZED_CALL
    with _ORDINAL_LOCK:
        _NEXT_SERIALIZED_CALL += 1
        return _NEXT_SERIALIZED_CALL


class BoundedModelOutputRecovery:
    """Replacement-experiment wrapper around one pinned Leanstral route."""

    interface: Final = BOUNDED_MODEL_OUTPUT_RECOVERY_INTERFACE
    provider_id: Final = "leanstral-local"

    def __init__(
        self,
        client: CompletionClient | SyMAICompletionClient,
        *,
        route: RecoveryRoute | str,
        policy: RecoveryPolicy = PREREGISTERED_SRT023_POLICY,
        schema_path: RecoverySchemaPath | str = RecoverySchemaPath.STANDARD,
    ) -> None:
        if not isinstance(policy, RecoveryPolicy):
            raise TypeError("policy must be RecoveryPolicy")
        try:
            self._route = RecoveryRoute(route)
        except ValueError as exc:
            raise ContractError(
                "route must be exactly direct or symai"
            ) from exc
        try:
            self._schema_path = RecoverySchemaPath(schema_path)
        except ValueError as exc:
            raise ContractError(
                "schema_path must be standard or single_rule_research"
            ) from exc
        observed_evidence = load_srt021_remediation_evidence()
        if policy.remediation_evidence != observed_evidence:
            raise ContractError(
                "recovery policy does not match repository SRT-021 evidence"
            )
        self._validate_client_identity(client)
        self._client = client
        self._policy = policy
        self._last_receipt: ModelOutputRecoveryReceipt | None = None

    @property
    def identity(self) -> str:
        return (
            f"{self.interface}:{self._route.route_id}:"
            f"{LEANSTRAL_ENDPOINT}:{LEANSTRAL_BACKEND}:{LEANSTRAL_MODEL}:"
            f"{LEANSTRAL_TOKENIZER_IDENTITY}:slots={LEANSTRAL_CAPACITY}:"
            "cache=disabled:fallback=forbidden:"
            f"schema_path={self._schema_path.value}:"
            f"policy_kind={self._policy.kind.value}"
        )

    @property
    def route(self) -> RecoveryRoute:
        return self._route

    @property
    def policy(self) -> RecoveryPolicy:
        return self._policy

    @property
    def schema_path(self) -> RecoverySchemaPath:
        return self._schema_path

    @property
    def last_receipt(self) -> ModelOutputRecoveryReceipt | None:
        return self._last_receipt

    def recover_l1(
        self,
        request: ConstructorRequest,
        *,
        expected_ir: CanonicalRuleIR | None = None,
    ) -> ModelOutputRecoveryResult:
        return self.recover(
            RecoveryRole.L1, request, expected_ir=expected_ir
        )

    def recover_t1(
        self,
        request: RealizerRequest,
    ) -> ModelOutputRecoveryResult:
        return self.recover(RecoveryRole.T1, request)

    def recover_l2(
        self,
        request: ConstructorRequest,
        *,
        expected_ir: CanonicalRuleIR | None = None,
    ) -> ModelOutputRecoveryResult:
        return self.recover(
            RecoveryRole.L2, request, expected_ir=expected_ir
        )

    def recover(
        self,
        role: RecoveryRole | str,
        request: ConstructorRequest | RealizerRequest,
        *,
        expected_ir: CanonicalRuleIR | None = None,
    ) -> ModelOutputRecoveryResult:
        """Invoke the fixed route and apply the preregistered recovery policy."""

        try:
            parsed_role = RecoveryRole(role)
        except ValueError as exc:
            raise ContractError("role must be exactly l1, t1, or l2") from exc
        self._validate_request(parsed_role, request, expected_ir)
        system, prompt, schema_name, schema, max_tokens = self._call_contract(
            parsed_role, request
        )
        request_cid = self._request_cid(parsed_role, request)
        calls: list[ModelCallReceipt] = []
        terminal_failure: FailureReason | None = None
        terminal_rejection: str | None = None
        failure_detail: str | None = None

        for call_index in range(1, self._policy.max_retries + 2):
            is_retry = call_index > 1
            call_system = system
            call_prompt = prompt
            if is_retry:
                # The retry uses only the preregistered rejection class.  It
                # never includes rejected output or source-bearing state.
                call_system += _RETRY_SYSTEM_SUFFIX
                call_prompt += _RETRY_PROMPT_SUFFIX.format(
                    reason=terminal_rejection
                )
            try:
                candidate, route_receipt, ordinal = self._invoke(
                    system=call_system,
                    prompt=call_prompt,
                    schema_name=schema_name,
                    schema=schema,
                    max_tokens=max_tokens,
                )
                if parsed_role is RecoveryRole.T1:
                    assert isinstance(request, RealizerRequest)
                    value = SyMAIPolarityContract.validate_realization(
                        candidate, request.canonical_ir
                    )
                else:
                    assert isinstance(request, ConstructorRequest)
                    value = SyMAIPolarityContract.validate_canonical(
                        candidate,
                        request.allowed_atom_vocabulary,
                        role=parsed_role,
                        expected_ir=expected_ir,
                    )
                calls.append(
                    self._call_receipt(
                        call_index=call_index,
                        ordinal=ordinal,
                        role=parsed_role,
                        request_cid=request_cid,
                        prompt=call_prompt,
                        schema_name=schema_name,
                        max_tokens=max_tokens,
                        outcome="accepted",
                        route_receipt=route_receipt,
                    )
                )
                receipt = ModelOutputRecoveryReceipt(
                    role=parsed_role,
                    route=self._route,
                    request_cid=request_cid,
                    policy=self._policy,
                    calls=tuple(calls),
                    status=ComponentStatus.SUCCESS,
                    terminal_failure=None,
                    terminal_rejection=None,
                )
                self._last_receipt = receipt
                if parsed_role is RecoveryRole.T1:
                    assert isinstance(value, str)
                    return ModelOutputRecoveryResult(
                        role=parsed_role,
                        status=ComponentStatus.SUCCESS,
                        text=value,
                        receipt=receipt,
                    )
                assert isinstance(value, CanonicalRuleIR)
                return ModelOutputRecoveryResult(
                    role=parsed_role,
                    status=ComponentStatus.SUCCESS,
                    canonical_ir=value,
                    receipt=receipt,
                )
            except _OutputRejected as exc:
                ordinal = locals().get("ordinal")
                if not isinstance(ordinal, int):
                    raise AssertionError("model rejection has no call ordinal")
                terminal_failure = exc.failure_reason
                terminal_rejection = exc.rejection
                failure_detail = exc.detail
                calls.append(
                    self._call_receipt(
                        call_index=call_index,
                        ordinal=ordinal,
                        role=parsed_role,
                        request_cid=request_cid,
                        prompt=call_prompt,
                        schema_name=schema_name,
                        max_tokens=max_tokens,
                        outcome="rejected",
                        rejection=exc.rejection,
                        failure_reason=exc.failure_reason,
                        detail=exc.detail,
                        route_receipt=locals().get("route_receipt"),
                    )
                )
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                ordinal = getattr(exc, "_srt023_call_ordinal", None)
                if not isinstance(ordinal, int):
                    raise AssertionError("model call failure has no ordinal")
                (
                    terminal_failure,
                    terminal_rejection,
                    failure_detail,
                    retryable,
                ) = self._classify_call_failure(exc)
                calls.append(
                    self._call_receipt(
                        call_index=call_index,
                        ordinal=ordinal,
                        role=parsed_role,
                        request_cid=request_cid,
                        prompt=call_prompt,
                        schema_name=schema_name,
                        max_tokens=max_tokens,
                        outcome="call_failed",
                        rejection=terminal_rejection,
                        failure_reason=terminal_failure,
                        detail=failure_detail,
                    )
                )
                if not retryable:
                    break

            assert terminal_rejection is not None
            if (
                call_index > self._policy.max_retries
                or not self._policy.permits(terminal_rejection)
            ):
                break

        assert terminal_failure is not None
        if len(calls) > 1:
            terminal_failure = FailureReason.RETRY_EXHAUSTED
            failure_detail = (
                "preregistered model-output recovery retry exhausted after "
                f"{terminal_rejection}"
            )
        receipt = ModelOutputRecoveryReceipt(
            role=parsed_role,
            route=self._route,
            request_cid=request_cid,
            policy=self._policy,
            calls=tuple(calls),
            status=ComponentStatus.FAILED,
            terminal_failure=terminal_failure,
            terminal_rejection=terminal_rejection,
        )
        self._last_receipt = receipt
        return ModelOutputRecoveryResult(
            role=parsed_role,
            status=ComponentStatus.FAILED,
            receipt=receipt,
            failure_reason=terminal_failure,
            failure_detail=failure_detail,
        )

    def _invoke(
        self,
        *,
        system: str,
        prompt: str,
        schema_name: str,
        schema: Mapping[str, object],
        max_tokens: int,
    ) -> tuple[Mapping[str, object], Mapping[str, object] | None, int]:
        with _SERIALIZATION_LOCK:
            ordinal = _next_ordinal()
            try:
                if self._route is RecoveryRoute.DIRECT:
                    candidate = self._client.complete_json(  # type: ignore[union-attr]
                        system=system,
                        prompt=prompt,
                        schema_name=schema_name,
                        schema=schema,
                        max_tokens=max_tokens,
                    )
                    if not isinstance(candidate, Mapping):
                        raise LeanstralMalformedResponseError(
                            "direct Leanstral output must be one JSON object"
                        )
                    return candidate, None, ordinal
                candidate, symai_receipt = _complete_symai_json(
                    self._client,  # type: ignore[arg-type]
                    system=system,
                    prompt=prompt,
                    schema_name=schema_name,
                    schema=schema,
                    max_tokens=max_tokens,
                )
                return candidate, symai_receipt.to_dict(), ordinal
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                annotated_exc: BaseException = exc
                try:
                    setattr(annotated_exc, "_srt023_call_ordinal", ordinal)
                except Exception:
                    annotated_exc = RuntimeError(
                        f"model call raised {type(exc).__name__}"
                    )
                    setattr(annotated_exc, "_srt023_call_ordinal", ordinal)
                    annotated_exc.__cause__ = exc
                raise annotated_exc

    def _call_contract(
        self,
        role: RecoveryRole,
        request: ConstructorRequest | RealizerRequest,
    ) -> tuple[
        str,
        str,
        str,
        Mapping[str, object],
        int,
    ]:
        polarity = SyMAIPolarityContract.instructions(role)
        schema_name = schema_name_for_role(
            role, schema_path=self._schema_path
        )
        if role is RecoveryRole.T1:
            assert isinstance(request, RealizerRequest)
            if (
                self._schema_path
                is RecoverySchemaPath.SINGLE_RULE_RESEARCH
                and len(request.canonical_ir.rules) != 1
            ):
                raise ContractError(
                    "single-rule research path requires exactly one input rule"
                )
            system = (
                "You are a source-withheld formal-logic realizer. The supplied "
                "canonical IR is your only semantic authority. Return one "
                "compact JSON object matching the supplied schema. "
                + polarity
            )
            prompt = (
                _realizer_prompt(request)
                + "\nOUTPUT_SHAPE: Return only the indexed rules array "
                "required by the schema; do not add combined text or metadata."
            )
            if self._schema_path is RecoverySchemaPath.SINGLE_RULE_RESEARCH:
                schema = (
                    SyMAIPolarityContract.single_rule_research_realization_schema(
                        request.canonical_ir
                    )
                )
            else:
                schema = SyMAIPolarityContract.realization_schema(
                    request.canonical_ir
                )
            return (
                system,
                prompt,
                schema_name,
                schema,
                REALIZER_MAX_TOKENS,
            )

        assert isinstance(request, ConstructorRequest)
        system = (
            "You are a deterministic legal semantic parser. Return one "
            "compact JSON object matching the supplied schema. Never explain, "
            "add keys, repeat a rule, or claim generated logic is proved. "
            + polarity
        )
        if self._schema_path is RecoverySchemaPath.SINGLE_RULE_RESEARCH:
            schema = SyMAIPolarityContract.single_rule_research_canonical_schema(
                request.allowed_atom_vocabulary
            )
        else:
            schema = SyMAIPolarityContract.canonical_schema(
                request.allowed_atom_vocabulary
            )
        return (
            system,
            _constructor_prompt(request, None),
            schema_name,
            schema,
            CONSTRUCTOR_MAX_TOKENS,
        )

    def _request_cid(
        self,
        role: RecoveryRole,
        request: ConstructorRequest | RealizerRequest,
    ) -> str:
        if role is RecoveryRole.T1:
            assert isinstance(request, RealizerRequest)
            # Address only the exact source-withheld material actually supplied.
            value: object = {
                "role": role.value,
                "canonical_ir": request.canonical_ir.to_dict(),
                "allowed_atom_vocabulary": (
                    request.allowed_atom_vocabulary.to_dict()
                ),
            }
        else:
            assert isinstance(request, ConstructorRequest)
            # Config is intentionally excluded because model prompts never use
            # it; addressing it could retain a hidden source-bearing dependency.
            value = {
                "role": role.value,
                "source_text": request.source_text,
                "allowed_atom_vocabulary": (
                    request.allowed_atom_vocabulary.to_dict()
                ),
            }
        return cid_for_dag_json(value)

    def _call_receipt(
        self,
        *,
        call_index: int,
        ordinal: int,
        role: RecoveryRole,
        request_cid: str,
        prompt: str,
        schema_name: str,
        max_tokens: int,
        outcome: str,
        rejection: str | None = None,
        failure_reason: FailureReason | None = None,
        detail: str | None = None,
        route_receipt: object = None,
    ) -> ModelCallReceipt:
        bounded_route_receipt = (
            route_receipt if isinstance(route_receipt, Mapping) else None
        )
        return ModelCallReceipt(
            call_number=call_index,
            serialized_call_ordinal=ordinal,
            attempt_kind=(
                "initial" if call_index == 1 else "preregistered_retry"
            ),
            role=role,
            route=self._route,
            request_cid=request_cid,
            prompt_cid=cid_for_bytes(prompt.encode("utf-8")),
            schema_name=schema_name,
            max_tokens=max_tokens,
            outcome=outcome,
            rejection=rejection,
            failure_reason=failure_reason,
            detail=None if detail is None else detail[:500],
            symai_route_receipt=bounded_route_receipt,
        )

    def _classify_call_failure(
        self, exc: BaseException
    ) -> tuple[FailureReason, str, str, bool]:
        if isinstance(
            exc, (LeanstralTimeoutError, TimeoutError, socket.timeout)
        ):
            return (
                FailureReason.TIMEOUT,
                "call_timeout",
                "pinned Leanstral call timed out",
                False,
            )
        if isinstance(exc, (SyMAIRouteError, LeanstralUnavailableError)):
            return (
                FailureReason.CAPABILITY_UNAVAILABLE,
                "route_contract_failure",
                "pinned model route was unavailable or drifted",
                False,
            )
        if isinstance(
            exc,
            (
                SyMAIMalformedResponseError,
                LeanstralMalformedResponseError,
                LeanstralRequestError,
                ContractError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ),
        ):
            return (
                FailureReason.INVALID_OUTPUT,
                "malformed_output",
                "model call returned malformed output",
                True,
            )
        return (
            FailureReason.EXCEPTION,
            "call_exception",
            f"pinned model call failed with {type(exc).__name__}",
            False,
        )

    def _validate_client_identity(self, client: _Client) -> None:
        if (
            not hasattr(client, "complete_json")
            or getattr(client, "endpoint", "").rstrip("/")
            != LEANSTRAL_ENDPOINT
            or getattr(client, "model", None) != LEANSTRAL_MODEL
        ):
            raise ContractError(
                "client must bind the exact frozen Leanstral endpoint/model"
            )
        optional_exact = {
            "backend": LEANSTRAL_BACKEND,
            "backend_owner": LEANSTRAL_BACKEND_OWNER,
            "tokenizer": LEANSTRAL_TOKENIZER_IDENTITY,
            "tokenizer_identity": LEANSTRAL_TOKENIZER_IDENTITY,
            "capacity": LEANSTRAL_CAPACITY,
            "parallel_slots": LEANSTRAL_CAPACITY,
        }
        for field, frozen in optional_exact.items():
            if hasattr(client, field) and getattr(client, field) != frozen:
                raise ContractError(
                    f"client {field} drifted from the frozen identity"
                )
        for field in ("cache_enabled", "cache_prompt"):
            if hasattr(client, field) and getattr(client, field) is not False:
                raise ContractError(
                    "client must preserve the disabled-cache identity"
                )
        if hasattr(client, "route"):
            route = getattr(client, "route")
            allowed = {
                self._route.value,
                self._route.route_id,
            }
            if route not in allowed:
                raise ContractError(
                    "client route drifted from the preregistered route"
                )

    def _validate_request(
        self,
        role: RecoveryRole,
        request: ConstructorRequest | RealizerRequest,
        expected_ir: CanonicalRuleIR | None,
    ) -> None:
        if role is RecoveryRole.T1:
            if not isinstance(request, RealizerRequest):
                raise TypeError("T1 recovery requires RealizerRequest")
            if expected_ir is not None:
                raise ContractError(
                    "T1 polarity authority is the request canonical IR"
                )
            if request.canonical_ir.is_empty:
                raise ContractError(
                    "T1 recovery requires nonempty canonical IR"
                )
            return
        if not isinstance(request, ConstructorRequest):
            raise TypeError("L1/L2 recovery requires ConstructorRequest")
        if expected_ir is not None:
            if not isinstance(expected_ir, CanonicalRuleIR):
                raise TypeError("expected_ir must be CanonicalRuleIR")
            expected_ir.validate_vocabulary(
                request.allowed_atom_vocabulary
            )


__all__ = [
    "BOUNDED_MODEL_OUTPUT_RECOVERY_INTERFACE",
    "SYMAI_POLARITY_CONTRACT_INTERFACE",
    "MODEL_OUTPUT_RECOVERY_SCHEMA_VERSION",
    "SRT021_REMEDIATION_EVIDENCE_SCHEMA",
    "SRT021_MANIFEST_RELATIVE_PATH",
    "SRT021_MANIFEST_CID",
    "SRT021_MANIFEST_GATE_CID",
    "SRT014_REPORT_CID",
    "DIRECT_ROUTE_ID",
    "LEANSTRAL_TOKENIZER_IDENTITY",
    "TYPED_REJECTION_REASONS",
    "SRT021RemediationEvidence",
    "FROZEN_SRT021_REMEDIATION_EVIDENCE",
    "load_srt021_remediation_evidence",
    "ModelRejectionReason",
    "RecoveryPolicyKind",
    "RecoverySchemaPath",
    "classify_model_rejection",
    "schema_name_for_role",
    "RecoveryRole",
    "RecoveryRoute",
    "RecoveryPolicy",
    "PREREGISTERED_SRT023_POLICY",
    "PROMOTION_RECOVERY_POLICY",
    "PREREGISTERED_RESEARCH_RECOVERY_POLICY",
    "ModelCallReceipt",
    "ModelOutputRecoveryReceipt",
    "ModelOutputRecoveryResult",
    "ArmReliabilityMetrics",
    "arm_reliability_metrics",
    "SyMAIPolarityContract",
    "BoundedModelOutputRecovery",
]
