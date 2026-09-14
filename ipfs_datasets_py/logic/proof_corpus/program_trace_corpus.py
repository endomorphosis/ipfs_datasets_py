"""Rights-admitted execution-trace corpus (ExecutionTraceCorpus@1 / SAWM-023).

Datasets owns corpus admission and split semantics.  This leaf materializes
first-party hermetic, synthetic, adversarial, and observed trace records with
repository/commit/task/function/failure/mutant/proof/procedure grouping and
six disjoint partitions.

Fail-closed rules:

* Every admitted row is rights/privacy reviewed and bound to an exact tree
  CID (no mutable ``latest`` alias).
* Related families cannot leak across partitions.
* Model nominations are never labels; ground truth is static, runtime, proof,
  test, human, or negative evidence.
* Secrets, credentials, hidden tests, private reasoning, unadmitted sources,
  tenant-private data, and unknown-rights material are excluded.
* An absent corpus returns ``training_unavailable`` without blocking
  contracts or deterministic baselines.

This module does not promote accelerator checkpoints, decide kit storage, or
publish raw private traces.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from ..ir_core.identity import cid_v1_from_digest


EXECUTION_TRACE_CORPUS_INTERFACE: Final = "ExecutionTraceCorpus@1"
PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE: Final = "ProgramTraceCorpusManifest@1"
PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE: Final = "ProgramTraceSplitManifest@1"
PROGRAM_TRACE_ADMISSION_INTERFACE: Final = "ProgramTraceAdmission@1"
PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE: Final = "ProgramTraceLeakageAudit@1"

PROGRAM_TRACE_CORPUS_SCHEMA_VERSION: Final = "program-trace-corpus/v1"
PROGRAM_TRACE_SPLIT_SCHEMA_VERSION: Final = "program-trace-split/v1"
PROGRAM_TRACE_ADMISSION_SCHEMA_VERSION: Final = "program-trace-admission/v1"
PROGRAM_TRACE_LEAKAGE_AUDIT_SCHEMA_VERSION: Final = "program-trace-leakage-audit/v1"
PROGRAM_TRACE_ROW_SCHEMA_VERSION: Final = "program-trace-row/v1"
PROGRAM_TRACE_RECIPE_SCHEMA_VERSION: Final = "program-world-trace-corpus-recipe/v1"

TRAINING_UNAVAILABLE: Final = "training_unavailable"

DEFAULT_CORPUS_ID: Final = "program-world-trace-corpus-v1"
DEFAULT_LANGUAGE: Final = "python"
MAX_TEXT_CHARS: Final = 512
MAX_ROWS: Final = 4_096
MAX_EVENT_KINDS: Final = 32
MAX_LABELS: Final = 16

_IDENTIFIER_RE: Final = re.compile(r"^[a-z][a-z0-9_]*(?:-[a-z0-9_]+)*$")
_TASK_ID_RE: Final = re.compile(
    r"^(?:[a-z][a-z0-9_]*(?:-[a-z0-9_]+)*|[A-Z]{2,12}-[0-9]{3,4})$"
)
_CID_RE: Final = re.compile(r"^b[a-z2-7]{10,200}$")
IMPORT_NETWORK_PERFORMED: Final[bool] = False
IMPORT_SOCKET_PERFORMED: Final[bool] = False
IMPORT_MODEL_LOAD_PERFORMED: Final[bool] = False
IMPORT_SIDE_EFFECTS_PERFORMED: Final[bool] = False
_MUTABLE_LATEST_RE: Final = re.compile(
    r"(^|[./_-])latest($|[./_-])", re.IGNORECASE
)

PROGRAM_TRACE_PARTITIONS: Final[tuple[str, ...]] = (
    "training",
    "development",
    "held_out",
    "adversarial",
    "cross_repository",
    "ood",
)
PROGRAM_TRACE_PARTITION_SET: Final[frozenset[str]] = frozenset(
    PROGRAM_TRACE_PARTITIONS
)

ADMITTED_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "first_party_hermetic",
        "instrumented_test",
        "admitted_static_edge",
        "admitted_dynamic_edge",
        "synthetic_program",
        "adversarial_mutant",
        "mechanical_counterexample",
        "admitted_public",
        "rights_cleared_review",
    }
)
FORBIDDEN_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "private_chain_of_thought",
        "credential",
        "hidden_test",
        "unadmitted_production",
        "tenant_private",
        "private_witness",
        "arbitrary_transcript",
        "unknown_rights",
        "secret",
        "model_nomination",
    }
)
ADMITTED_RIGHTS_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "first_party_hermetic",
        "synthetic_generated",
        "adversarial_generated",
        "observed_first_party",
        "admitted_public",
        "rights_cleared_review",
    }
)
ADMITTED_PRIVACY_CLASSES: Final[frozenset[str]] = frozenset({"public"})
FORBIDDEN_PRIVACY_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "private",
        "restricted",
        "tenant_private",
        "unknown",
    }
)
GROUND_TRUTH_KINDS: Final[frozenset[str]] = frozenset(
    {
        "static",
        "runtime",
        "proof",
        "test",
        "human",
        "negative",
    }
)
FORBIDDEN_LABEL_KINDS: Final[frozenset[str]] = frozenset(
    {
        "model_nomination",
        "model_prediction",
        "model_label",
        "learned",
        "nomination",
    }
)
ALLOWED_LABEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "expected_event_kind",
        "expected_outcome",
        "expected_symbol",
        "exception_type",
        "polarity",
        "proof_status",
        "test_status",
    }
)
POLARITY_VALUES: Final[frozenset[str]] = frozenset({"positive", "negative"})
ADMITTED_LANGUAGES: Final[frozenset[str]] = frozenset({"python"})
RELATED_GROUPING_AXES: Final[tuple[str, ...]] = (
    "family_id",
    "task_id",
    "function_id",
    "failure_id",
    "mutant_id",
    "proof_id",
    "procedure_id",
)
GROUPING_AXES: Final[tuple[str, ...]] = (
    "repository_id",
    "commit_id",
    *RELATED_GROUPING_AXES,
)
ADMITTED_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "call",
        "return",
        "line",
        "assign",
        "raise",
        "catch",
        "handler",
        "yield",
        "await",
        "branch",
        "enter",
        "exit",
        "external",
        "observe",
        "unavailable",
    }
)

_SECRET_KEY_FRAGMENTS: Final[tuple[str, ...]] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "privatekey",
    "credential",
    "authorization",
    "bearer",
    "session",
    "cookie",
    "witness",
    "signing_key",
)
_FORBIDDEN_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "chain_of_thought",
        "cookie",
        "credential",
        "hidden_test",
        "hidden_tests",
        "model_label",
        "model_nomination",
        "model_output",
        "model_prediction",
        "password",
        "predicted_label",
        "private_formula",
        "private_key",
        "private_reasoning",
        "raw_body",
        "raw_trace",
        "secret",
        "tenant_private",
        "token",
        "witness",
    }
)
_PRIVATE_REASONING_FRAGMENTS: Final[tuple[str, ...]] = (
    "chain-of-thought",
    "chain_of_thought",
    "private reasoning",
    "private_reasoning",
    "hidden test",
    "hidden_test",
)

_ROW_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "commit_id",
        "content_cid",
        "content_digest",
        "environment_binding_cid",
        "event_kinds",
        "failure_id",
        "family_id",
        "function_id",
        "ground_truth_kind",
        "interface",
        "labels",
        "language",
        "lineage",
        "mutant_id",
        "partition",
        "polarity",
        "privacy_class",
        "procedure_id",
        "proof_id",
        "repository_id",
        "rights_class",
        "row_id",
        "schema_version",
        "source_cid",
        "source_kind",
        "task_id",
        "trace_cid",
        "tree_cid",
    }
)
_ADMISSION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "content_cid",
        "content_digest",
        "exact_tree_bound",
        "interface",
        "labels_are_ground_truth",
        "privacy_admitted",
        "reasons",
        "rights_admitted",
        "row_id",
        "schema_version",
        "source_lineage_bound",
        "status",
    }
)
_SPLIT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "content_cid",
        "content_digest",
        "disjoint",
        "interface",
        "partition_family_ids",
        "partition_row_ids",
        "partitions",
        "schema_version",
    }
)
_LEAKAGE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "content_cid",
        "content_digest",
        "cross_repository_overlap",
        "disjoint",
        "interface",
        "leaked_families",
        "leaked_grouping",
        "mode",
        "partition_row_counts",
        "rules",
        "schema_version",
        "status",
    }
)
_MANIFEST_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "baselines_available",
        "contracts_available",
        "content_cid",
        "content_digest",
        "corpus_id",
        "interface",
        "language",
        "leakage_audit",
        "limitations",
        "reason",
        "row_count",
        "rows",
        "schema_version",
        "splits",
        "status",
        "task_id",
        "training_available",
        "training_status",
    }
)

LEAKAGE_RULES: Final[tuple[str, ...]] = (
    "entire_family_in_single_partition",
    "no_cross_partition_related_grouping",
    "cross_repository_repository_fence",
    "trace_identity_unique_to_partition",
)


class ProgramTraceCorpusError(ValueError):
    """Raised when a program-trace corpus contract is malformed."""


class ProgramTraceAdmissionError(ProgramTraceCorpusError):
    """Raised when a row cannot be rights/privacy/tree admitted."""


class ProgramTraceLeakageError(ProgramTraceCorpusError):
    """Raised when related families leak across partitions."""


class ProgramTracePartition(str, Enum):
    """Closed six-partition split vocabulary."""

    TRAINING = "training"
    DEVELOPMENT = "development"
    HELD_OUT = "held_out"
    ADVERSARIAL = "adversarial"
    CROSS_REPOSITORY = "cross_repository"
    OOD = "ood"


class ProgramTraceAdmissionStatus(str, Enum):
    """Closed admission outcome vocabulary."""

    ADMITTED = "admitted"
    REJECTED = "rejected"


class ProgramTraceCorpusStatus(str, Enum):
    """Closed corpus training-availability vocabulary."""

    ADMITTED = "admitted"
    TRAINING_UNAVAILABLE = TRAINING_UNAVAILABLE


class ProgramTraceLeakageStatus(str, Enum):
    """Closed leakage-audit outcome vocabulary."""

    PASS = "pass"
    FAIL = "fail"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _cid_for(value: Any) -> str:
    return cid_v1_from_digest(hashlib.sha256(_canonical_bytes(value)).digest())


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProgramTraceCorpusError(f"{label} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProgramTraceCorpusError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProgramTraceCorpusError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if len(value) > MAX_TEXT_CHARS or "\x00" in value:
        raise ProgramTraceCorpusError(f"{field_name} must be bounded text")
    return value


def _optional_text(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_text(value, field_name)


def _require_identifier(value: Any, field_name: str) -> str:
    text = _require_text(value, field_name)
    if not _IDENTIFIER_RE.fullmatch(text):
        raise ProgramTraceCorpusError(
            f"{field_name} must be a lowercase hyphenated identifier"
        )
    return text


def _optional_identifier(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_identifier(value, field_name)


def _require_task_id(value: Any, field_name: str = "task_id") -> str:
    text = _require_text(value, field_name)
    if not _TASK_ID_RE.fullmatch(text):
        raise ProgramTraceCorpusError(
            f"{field_name} must be a lowercase identifier or SAWM-style task id"
        )
    return text


def _require_cid(value: Any, field_name: str) -> str:
    cid = _require_text(value, field_name)
    if not _CID_RE.fullmatch(cid):
        raise ProgramTraceCorpusError(
            f"{field_name} must be a CIDv1 base32 string"
        )
    if _MUTABLE_LATEST_RE.search(cid):
        raise ProgramTraceCorpusError(
            f"{field_name} cannot bind a mutable latest alias"
        )
    return cid


def _parse_enum(value: Any, enum_cls: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise ProgramTraceCorpusError(
            f"{field_name} must be one of: {allowed}"
        ) from exc


def _closed_value(value: Any, allowed: frozenset[str], field_name: str) -> str:
    text = _require_identifier(value, field_name)
    if text not in allowed:
        raise ProgramTraceCorpusError(
            f"{field_name} must be one of: {', '.join(sorted(allowed))}"
        )
    return text


def _unique_texts(values: Any, field_name: str) -> tuple[str, ...]:
    if values in (None, (), []):
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        raise ProgramTraceCorpusError(
            f"{field_name} must be a sequence of strings"
        )
    try:
        items = tuple(_require_text(item, field_name) for item in values)
    except TypeError as exc:
        raise ProgramTraceCorpusError(
            f"{field_name} must be a sequence of strings"
        ) from exc
    if len(items) != len(set(items)):
        raise ProgramTraceCorpusError(f"{field_name} values must be unique")
    return items


def _event_kinds(values: Any) -> tuple[str, ...]:
    items = _unique_texts(values, "event_kinds")
    if len(items) > MAX_EVENT_KINDS:
        raise ProgramTraceCorpusError("event_kinds exceeds the bounded maximum")
    unknown = [item for item in items if item not in ADMITTED_EVENT_KINDS]
    if unknown:
        raise ProgramTraceCorpusError(
            f"unsupported event_kinds: {', '.join(unknown)}"
        )
    return items


def _string_map(value: Any, field_name: str) -> Mapping[str, str]:
    if value in (None, {}):
        return MappingProxyType({})
    mapping = _as_mapping(value, field_name)
    if len(mapping) > MAX_LABELS:
        raise ProgramTraceCorpusError(f"{field_name} exceeds the bounded maximum")
    normalized: dict[str, str] = {}
    for key, item in mapping.items():
        key_text = _require_identifier(key, f"{field_name} key")
        normalized[key_text] = _require_text(item, f"{field_name}.{key_text}")
    return MappingProxyType(normalized)


def _contains_secret_key(key: str) -> bool:
    folded = key.casefold().replace("-", "_")
    if folded in _FORBIDDEN_PAYLOAD_KEYS:
        return True
    return any(fragment in folded for fragment in _SECRET_KEY_FRAGMENTS)


def _contains_private_reasoning(text: str) -> bool:
    folded = text.casefold().replace("-", "_")
    return any(fragment.replace("-", "_") in folded for fragment in _PRIVATE_REASONING_FRAGMENTS)


def _scan_forbidden_payload(value: Any, *, path: str = "$") -> tuple[str, ...]:
    reasons: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            child = f"{path}.{key_text}"
            if _contains_secret_key(key_text):
                if "hidden_test" in key_text.casefold().replace("-", "_"):
                    reasons.append("hidden_test")
                elif "chain_of_thought" in key_text.casefold().replace(
                    "-", "_"
                ) or "private_reasoning" in key_text.casefold().replace("-", "_"):
                    reasons.append("private_reasoning")
                elif "model_nomination" in key_text.casefold().replace(
                    "-", "_"
                ) or "model_label" in key_text.casefold().replace("-", "_"):
                    reasons.append("model_nomination_label")
                elif "tenant_private" in key_text.casefold().replace("-", "_"):
                    reasons.append("tenant_private")
                else:
                    reasons.append("secret_material")
            reasons.extend(_scan_forbidden_payload(item, path=child))
        return tuple(dict.fromkeys(reasons))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            reasons.extend(_scan_forbidden_payload(item, path=f"{path}[{index}]"))
        return tuple(dict.fromkeys(reasons))
    if isinstance(value, str):
        folded = value.casefold()
        if _contains_private_reasoning(value):
            reasons.append("private_reasoning")
        if "hidden_test" in folded.replace("-", "_") or "hidden test" in folded:
            reasons.append("hidden_test")
        if any(
            marker in folded
            for marker in ("api_key=", "password=", "bearer ", "secret=")
        ):
            reasons.append("secret_material")
    return tuple(dict.fromkeys(reasons))


def default_program_trace_corpus_fixture_path() -> Path:
    """Return the in-tree compact recipe fixture path."""

    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "program_world_trace_corpus.json"
    )


def _derived_cid(*parts: str) -> str:
    return _cid_for({"schema": PROGRAM_TRACE_ROW_SCHEMA_VERSION, "parts": list(parts)})


def expand_program_trace_recipe(
    recipe: Mapping[str, Any],
    *,
    defaults: Mapping[str, Any] | None = None,
    corpus_id: str = DEFAULT_CORPUS_ID,
) -> dict[str, Any]:
    """Expand a compact recipe into a row mapping with exact tree identity."""

    mapping = _as_mapping(recipe, "recipe")
    base = dict(defaults or {})
    unknown_default_keys = sorted(
        set(base)
        - (
            _ROW_FIELDS
            | {
                "environment_seed",
                "source_seed",
                "trace_seed",
                "tree_seed",
            }
        )
    )
    if unknown_default_keys:
        raise ProgramTraceCorpusError(
            "unknown recipe default field(s): " + ", ".join(unknown_default_keys)
        )
    merged = {**base, **dict(mapping)}
    row_id = _require_identifier(merged.get("row_id"), "row_id")
    repository_id = _require_identifier(
        merged.get("repository_id", "ipfs_datasets_py"), "repository_id"
    )
    commit_id = _require_identifier(
        merged.get("commit_id", "sawm-023-fixture"), "commit_id"
    )
    tree_seed = _optional_text(merged.get("tree_seed"), "tree_seed") or (
        f"{corpus_id}:{repository_id}:{commit_id}"
    )
    source_seed = _optional_text(merged.get("source_seed"), "source_seed") or (
        f"{row_id}:source"
    )
    environment_seed = _optional_text(
        merged.get("environment_seed"), "environment_seed"
    ) or "python-hermetic-env"
    trace_seed = _optional_text(merged.get("trace_seed"), "trace_seed") or (
        f"{row_id}:trace"
    )
    tree_cid = (
        merged["tree_cid"]
        if "tree_cid" in merged
        else _derived_cid("tree", tree_seed)
    )
    source_cid = (
        merged["source_cid"]
        if "source_cid" in merged
        else _derived_cid("source", source_seed)
    )
    environment_binding_cid = (
        merged["environment_binding_cid"]
        if "environment_binding_cid" in merged
        else _derived_cid("environment", environment_seed)
    )
    event_kinds = list(merged.get("event_kinds") or ("call", "return"))
    trace_cid = (
        merged["trace_cid"]
        if "trace_cid" in merged
        else _derived_cid("trace", trace_seed, *event_kinds)
    )
    family_id = merged.get("family_id") or f"fam-{row_id}"
    function_id = merged.get("function_id") or f"fn-{row_id}"
    labels = dict(merged.get("labels") or {})
    polarity = merged.get("polarity") or "positive"
    labels.setdefault("polarity", polarity)
    lineage = {
        "commit_id": commit_id,
        "function_id": function_id,
        "repository_id": repository_id,
        "source_kind": str(merged.get("source_kind") or "first_party_hermetic"),
    }
    task_id = merged.get("task_id") or ""
    if task_id:
        lineage["task_id"] = task_id
    if isinstance(tree_cid, str) and tree_cid:
        lineage["tree_cid"] = tree_cid
    return {
        "row_id": row_id,
        "partition": merged.get("partition"),
        "source_kind": merged.get("source_kind", "first_party_hermetic"),
        "rights_class": merged.get("rights_class", "first_party_hermetic"),
        "privacy_class": merged.get("privacy_class", "public"),
        "language": merged.get("language", DEFAULT_LANGUAGE),
        "repository_id": repository_id,
        "commit_id": commit_id,
        "tree_cid": tree_cid,
        "source_cid": source_cid,
        "environment_binding_cid": environment_binding_cid,
        "trace_cid": trace_cid,
        "family_id": family_id,
        "task_id": merged.get("task_id") or "",
        "function_id": function_id,
        "failure_id": merged.get("failure_id") or "",
        "mutant_id": merged.get("mutant_id") or "",
        "proof_id": merged.get("proof_id") or "",
        "procedure_id": merged.get("procedure_id") or "",
        "ground_truth_kind": merged.get("ground_truth_kind", "runtime"),
        "polarity": polarity,
        "event_kinds": event_kinds,
        "labels": labels,
        "lineage": lineage,
    }


@dataclass(frozen=True, slots=True)
class ProgramTraceAdmission:
    """Rights, privacy, lineage, and label-authority receipt for one row."""

    row_id: str
    status: ProgramTraceAdmissionStatus | str
    reasons: tuple[str, ...] = ()
    rights_admitted: bool = False
    privacy_admitted: bool = False
    exact_tree_bound: bool = False
    source_lineage_bound: bool = False
    labels_are_ground_truth: bool = False
    schema_version: str = PROGRAM_TRACE_ADMISSION_SCHEMA_VERSION
    interface: str = PROGRAM_TRACE_ADMISSION_INTERFACE
    content_digest: str = ""
    content_cid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "row_id", _require_identifier(self.row_id, "row_id"))
        object.__setattr__(
            self,
            "status",
            _parse_enum(self.status, ProgramTraceAdmissionStatus, "status"),
        )
        object.__setattr__(self, "reasons", _unique_texts(self.reasons, "reasons"))
        for flag_name in (
            "rights_admitted",
            "privacy_admitted",
            "exact_tree_bound",
            "source_lineage_bound",
            "labels_are_ground_truth",
        ):
            flag = getattr(self, flag_name)
            if type(flag) is not bool:
                raise ProgramTraceCorpusError(f"{flag_name} must be a boolean")
        if self.schema_version != PROGRAM_TRACE_ADMISSION_SCHEMA_VERSION:
            raise ProgramTraceCorpusError("unsupported admission schema")
        if self.interface != PROGRAM_TRACE_ADMISSION_INTERFACE:
            raise ProgramTraceCorpusError("unsupported admission interface")
        admitted = self.status is ProgramTraceAdmissionStatus.ADMITTED
        if admitted:
            if self.reasons:
                raise ProgramTraceCorpusError(
                    "admitted rows cannot carry rejection reasons"
                )
            if not (
                self.rights_admitted
                and self.privacy_admitted
                and self.exact_tree_bound
                and self.source_lineage_bound
                and self.labels_are_ground_truth
            ):
                raise ProgramTraceCorpusError(
                    "admitted rows require rights, privacy, tree, lineage, "
                    "and ground-truth label bindings"
                )
        elif not self.reasons:
            raise ProgramTraceCorpusError("rejected rows require reasons")
        payload = self.identity_payload()
        digest = _sha256_digest(_canonical_bytes(payload))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if self.content_digest and self.content_digest != digest:
            raise ProgramTraceCorpusError("admission content_digest drifted")
        if self.content_cid and self.content_cid != cid:
            raise ProgramTraceCorpusError("admission content_cid drifted")
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "content_cid", cid)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "exact_tree_bound": self.exact_tree_bound,
            "interface": self.interface,
            "labels_are_ground_truth": self.labels_are_ground_truth,
            "privacy_admitted": self.privacy_admitted,
            "reasons": list(self.reasons),
            "rights_admitted": self.rights_admitted,
            "row_id": self.row_id,
            "schema_version": self.schema_version,
            "source_lineage_bound": self.source_lineage_bound,
            "status": str(self.status.value if isinstance(self.status, Enum) else self.status),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProgramTraceAdmission":
        mapping = _as_mapping(value, "admission")
        _reject_unknown(mapping, _ADMISSION_FIELDS, "admission")
        return cls(
            row_id=mapping["row_id"],
            status=mapping["status"],
            reasons=tuple(mapping.get("reasons") or ()),
            rights_admitted=bool(mapping.get("rights_admitted", False)),
            privacy_admitted=bool(mapping.get("privacy_admitted", False)),
            exact_tree_bound=bool(mapping.get("exact_tree_bound", False)),
            source_lineage_bound=bool(mapping.get("source_lineage_bound", False)),
            labels_are_ground_truth=bool(
                mapping.get("labels_are_ground_truth", False)
            ),
            schema_version=mapping.get(
                "schema_version", PROGRAM_TRACE_ADMISSION_SCHEMA_VERSION
            ),
            interface=mapping.get("interface", PROGRAM_TRACE_ADMISSION_INTERFACE),
            content_digest=mapping.get("content_digest", ""),
            content_cid=mapping.get("content_cid", ""),
        )


@dataclass(frozen=True, slots=True)
class ProgramTraceRow:
    """One rights-admitted, exact-tree-bound execution-trace corpus row."""

    row_id: str
    partition: ProgramTracePartition | str
    source_kind: str
    rights_class: str
    privacy_class: str
    language: str
    repository_id: str
    commit_id: str
    tree_cid: str
    source_cid: str
    environment_binding_cid: str
    trace_cid: str
    family_id: str
    function_id: str
    ground_truth_kind: str
    task_id: str = ""
    failure_id: str = ""
    mutant_id: str = ""
    proof_id: str = ""
    procedure_id: str = ""
    polarity: str = "positive"
    event_kinds: tuple[str, ...] = ()
    labels: Mapping[str, str] = field(default_factory=dict)
    lineage: Mapping[str, str] = field(default_factory=dict)
    schema_version: str = PROGRAM_TRACE_ROW_SCHEMA_VERSION
    interface: str = EXECUTION_TRACE_CORPUS_INTERFACE
    content_digest: str = ""
    content_cid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "row_id", _require_identifier(self.row_id, "row_id"))
        object.__setattr__(
            self,
            "partition",
            _parse_enum(self.partition, ProgramTracePartition, "partition"),
        )
        object.__setattr__(
            self, "source_kind", _closed_value(self.source_kind, ADMITTED_SOURCE_KINDS, "source_kind")
        )
        object.__setattr__(
            self,
            "rights_class",
            _closed_value(self.rights_class, ADMITTED_RIGHTS_CLASSES, "rights_class"),
        )
        object.__setattr__(
            self,
            "privacy_class",
            _closed_value(
                self.privacy_class, ADMITTED_PRIVACY_CLASSES, "privacy_class"
            ),
        )
        object.__setattr__(
            self,
            "language",
            _closed_value(self.language, ADMITTED_LANGUAGES, "language"),
        )
        object.__setattr__(
            self,
            "repository_id",
            _require_identifier(self.repository_id, "repository_id"),
        )
        object.__setattr__(
            self, "commit_id", _require_identifier(self.commit_id, "commit_id")
        )
        object.__setattr__(self, "tree_cid", _require_cid(self.tree_cid, "tree_cid"))
        object.__setattr__(
            self, "source_cid", _require_cid(self.source_cid, "source_cid")
        )
        object.__setattr__(
            self,
            "environment_binding_cid",
            _require_cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(
            self, "trace_cid", _require_cid(self.trace_cid, "trace_cid")
        )
        object.__setattr__(
            self, "family_id", _require_identifier(self.family_id, "family_id")
        )
        object.__setattr__(
            self, "function_id", _require_identifier(self.function_id, "function_id")
        )
        object.__setattr__(
            self,
            "ground_truth_kind",
            _closed_value(
                self.ground_truth_kind, GROUND_TRUTH_KINDS, "ground_truth_kind"
            ),
        )
        object.__setattr__(
            self, "task_id", _optional_identifier(self.task_id, "task_id")
        )
        object.__setattr__(
            self, "failure_id", _optional_identifier(self.failure_id, "failure_id")
        )
        object.__setattr__(
            self, "mutant_id", _optional_identifier(self.mutant_id, "mutant_id")
        )
        object.__setattr__(
            self, "proof_id", _optional_identifier(self.proof_id, "proof_id")
        )
        object.__setattr__(
            self,
            "procedure_id",
            _optional_identifier(self.procedure_id, "procedure_id"),
        )
        object.__setattr__(
            self, "polarity", _closed_value(self.polarity, POLARITY_VALUES, "polarity")
        )
        object.__setattr__(self, "event_kinds", _event_kinds(self.event_kinds))
        labels = _string_map(self.labels, "labels")
        unknown_labels = sorted(set(labels) - ALLOWED_LABEL_KEYS)
        if unknown_labels:
            raise ProgramTraceCorpusError(
                "unknown label key(s): " + ", ".join(unknown_labels)
            )
        if any(key in FORBIDDEN_LABEL_KINDS for key in labels):
            raise ProgramTraceCorpusError("model nominations are never labels")
        object.__setattr__(self, "labels", labels)
        lineage = _string_map(self.lineage, "lineage")
        object.__setattr__(self, "lineage", lineage)
        if self.schema_version != PROGRAM_TRACE_ROW_SCHEMA_VERSION:
            raise ProgramTraceCorpusError("unsupported program-trace row schema")
        if self.interface != EXECUTION_TRACE_CORPUS_INTERFACE:
            raise ProgramTraceCorpusError("unsupported program-trace row interface")
        payload = self.identity_payload()
        forbidden = _scan_forbidden_payload(payload)
        if forbidden:
            raise ProgramTraceAdmissionError(
                "row payload contains excluded material: " + ", ".join(forbidden)
            )
        digest = _sha256_digest(_canonical_bytes(payload))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if self.content_digest and self.content_digest != digest:
            raise ProgramTraceCorpusError("row content_digest drifted")
        if self.content_cid and self.content_cid != cid:
            raise ProgramTraceCorpusError("row content_cid drifted")
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "content_cid", cid)

    @property
    def partition_value(self) -> str:
        partition = self.partition
        return partition.value if isinstance(partition, Enum) else str(partition)

    def grouping_values(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                "commit_id": self.commit_id,
                "failure_id": self.failure_id,
                "family_id": self.family_id,
                "function_id": self.function_id,
                "mutant_id": self.mutant_id,
                "procedure_id": self.procedure_id,
                "proof_id": self.proof_id,
                "repository_id": self.repository_id,
                "task_id": self.task_id,
            }
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "commit_id": self.commit_id,
            "environment_binding_cid": self.environment_binding_cid,
            "event_kinds": list(self.event_kinds),
            "failure_id": self.failure_id,
            "family_id": self.family_id,
            "function_id": self.function_id,
            "ground_truth_kind": self.ground_truth_kind,
            "interface": self.interface,
            "labels": dict(self.labels),
            "language": self.language,
            "lineage": dict(self.lineage),
            "mutant_id": self.mutant_id,
            "partition": self.partition_value,
            "polarity": self.polarity,
            "privacy_class": self.privacy_class,
            "procedure_id": self.procedure_id,
            "proof_id": self.proof_id,
            "repository_id": self.repository_id,
            "rights_class": self.rights_class,
            "row_id": self.row_id,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "source_kind": self.source_kind,
            "task_id": self.task_id,
            "trace_cid": self.trace_cid,
            "tree_cid": self.tree_cid,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProgramTraceRow":
        mapping = _as_mapping(value, "row")
        _reject_unknown(mapping, _ROW_FIELDS, "row")
        return cls(
            row_id=mapping["row_id"],
            partition=mapping["partition"],
            source_kind=mapping["source_kind"],
            rights_class=mapping["rights_class"],
            privacy_class=mapping["privacy_class"],
            language=mapping.get("language", DEFAULT_LANGUAGE),
            repository_id=mapping["repository_id"],
            commit_id=mapping["commit_id"],
            tree_cid=mapping["tree_cid"],
            source_cid=mapping["source_cid"],
            environment_binding_cid=mapping["environment_binding_cid"],
            trace_cid=mapping["trace_cid"],
            family_id=mapping["family_id"],
            function_id=mapping["function_id"],
            ground_truth_kind=mapping["ground_truth_kind"],
            task_id=mapping.get("task_id", ""),
            failure_id=mapping.get("failure_id", ""),
            mutant_id=mapping.get("mutant_id", ""),
            proof_id=mapping.get("proof_id", ""),
            procedure_id=mapping.get("procedure_id", ""),
            polarity=mapping.get("polarity", "positive"),
            event_kinds=tuple(mapping.get("event_kinds") or ()),
            labels=mapping.get("labels") or {},
            lineage=mapping.get("lineage") or {},
            schema_version=mapping.get(
                "schema_version", PROGRAM_TRACE_ROW_SCHEMA_VERSION
            ),
            interface=mapping.get("interface", EXECUTION_TRACE_CORPUS_INTERFACE),
            content_digest=mapping.get("content_digest", ""),
            content_cid=mapping.get("content_cid", ""),
        )


def _collect_admission_reasons(payload: Mapping[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    reasons.extend(_scan_forbidden_payload(payload))
    source_kind = str(payload.get("source_kind") or "")
    rights_class = str(payload.get("rights_class") or "")
    privacy_class = str(payload.get("privacy_class") or "")
    language = str(payload.get("language") or "")
    partition = str(payload.get("partition") or "")
    ground_truth_kind = str(payload.get("ground_truth_kind") or "")
    tree_cid = payload.get("tree_cid")
    repository_id = payload.get("repository_id")
    commit_id = payload.get("commit_id")
    family_id = payload.get("family_id")
    labels = payload.get("labels") if isinstance(payload.get("labels"), Mapping) else {}

    if source_kind in FORBIDDEN_SOURCE_KINDS:
        if source_kind in {"hidden_test"}:
            reasons.append("hidden_test")
        elif source_kind in {"private_chain_of_thought", "private_witness"}:
            reasons.append("private_reasoning")
        elif source_kind in {"unadmitted_production", "arbitrary_transcript"}:
            reasons.append("unadmitted_source")
        elif source_kind in {"tenant_private"}:
            reasons.append("tenant_private")
        elif source_kind in {"credential", "secret"}:
            reasons.append("secret_material")
        elif source_kind in {"unknown_rights"}:
            reasons.append("unknown_rights")
        elif source_kind in {"model_nomination"}:
            reasons.append("model_nomination_label")
        else:
            reasons.append("forbidden_source")
    elif source_kind not in ADMITTED_SOURCE_KINDS:
        reasons.append("forbidden_source")

    if rights_class not in ADMITTED_RIGHTS_CLASSES:
        reasons.append("unknown_rights")
    if privacy_class in FORBIDDEN_PRIVACY_CLASSES or privacy_class not in ADMITTED_PRIVACY_CLASSES:
        reasons.append("privacy_not_admitted")
    if language and language not in ADMITTED_LANGUAGES:
        reasons.append("unsupported_language")
    if not partition or partition not in PROGRAM_TRACE_PARTITION_SET:
        reasons.append("unknown_partition")
    if ground_truth_kind in FORBIDDEN_LABEL_KINDS:
        reasons.append("model_nomination_label")
    elif ground_truth_kind not in GROUND_TRUTH_KINDS:
        reasons.append("model_nomination_label")
    if not isinstance(tree_cid, str) or not tree_cid.strip():
        reasons.append("missing_tree_cid")
    elif not _CID_RE.fullmatch(tree_cid) or _MUTABLE_LATEST_RE.search(tree_cid):
        reasons.append("invalid_tree_cid")
    if not isinstance(repository_id, str) or not repository_id.strip():
        reasons.append("missing_lineage")
    if not isinstance(commit_id, str) or not commit_id.strip():
        reasons.append("missing_lineage")
    if not isinstance(family_id, str) or not family_id.strip():
        reasons.append("missing_family")
    if any(
        str(key) in FORBIDDEN_LABEL_KINDS or str(key) not in ALLOWED_LABEL_KEYS
        for key in labels
    ):
        reasons.append("model_nomination_label")
    includes_raw = payload.get("includes_raw_bodies")
    if includes_raw is True:
        reasons.append("raw_trace_body")
    return tuple(dict.fromkeys(reasons))


def admit_program_trace_row(
    row: Mapping[str, Any] | ProgramTraceRow,
    *,
    raise_on_reject: bool = False,
) -> tuple[ProgramTraceAdmission, ProgramTraceRow | None]:
    """Admit one trace row or return a typed rejection receipt."""

    if isinstance(row, ProgramTraceRow):
        payload = row.to_dict()
    else:
        payload = dict(_as_mapping(row, "row"))
    row_id_value = payload.get("row_id") or "unidentified-row"
    try:
        row_id = _require_identifier(row_id_value, "row_id")
    except ProgramTraceCorpusError:
        row_id = "unidentified-row"
        reasons = ("missing_lineage", *_collect_admission_reasons(payload))
        admission = ProgramTraceAdmission(
            row_id=row_id,
            status=ProgramTraceAdmissionStatus.REJECTED,
            reasons=tuple(dict.fromkeys(reasons)),
        )
        if raise_on_reject:
            raise ProgramTraceAdmissionError(
                f"row {row_id} rejected: {', '.join(admission.reasons)}"
            )
        return admission, None

    reasons = _collect_admission_reasons(payload)
    if reasons:
        admission = ProgramTraceAdmission(
            row_id=row_id,
            status=ProgramTraceAdmissionStatus.REJECTED,
            reasons=reasons,
            rights_admitted="unknown_rights" not in reasons,
            privacy_admitted="privacy_not_admitted" not in reasons,
            exact_tree_bound=not (
                "missing_tree_cid" in reasons or "invalid_tree_cid" in reasons
            ),
            source_lineage_bound="missing_lineage" not in reasons,
            labels_are_ground_truth="model_nomination_label" not in reasons,
        )
        if raise_on_reject:
            raise ProgramTraceAdmissionError(
                f"row {row_id} rejected: {', '.join(reasons)}"
            )
        return admission, None

    try:
        admitted_row = (
            row if isinstance(row, ProgramTraceRow) else ProgramTraceRow.from_dict(payload)
        )
    except (ProgramTraceCorpusError, KeyError, TypeError) as exc:
        admission = ProgramTraceAdmission(
            row_id=row_id,
            status=ProgramTraceAdmissionStatus.REJECTED,
            reasons=("unadmitted_source",),
        )
        if raise_on_reject:
            raise ProgramTraceAdmissionError(
                f"row {row_id} rejected: unadmitted_source"
            ) from exc
        return admission, None

    admission = ProgramTraceAdmission(
        row_id=admitted_row.row_id,
        status=ProgramTraceAdmissionStatus.ADMITTED,
        rights_admitted=True,
        privacy_admitted=True,
        exact_tree_bound=True,
        source_lineage_bound=True,
        labels_are_ground_truth=True,
    )
    return admission, admitted_row


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self._parent.setdefault(item, item)

    def find(self, item: str) -> str:
        parent = self._parent.setdefault(item, item)
        if parent != item:
            parent = self.find(parent)
            self._parent[item] = parent
        return parent

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self._parent[right_root] = left_root


def _related_key(axis: str, value: str) -> str:
    return f"{axis}:{value}"


def audit_program_trace_leakage(
    rows: Sequence[ProgramTraceRow | Mapping[str, Any]],
) -> "ProgramTraceLeakageAudit":
    """Audit that related families occupy exactly one partition."""

    admitted: list[ProgramTraceRow] = []
    for row in rows:
        if isinstance(row, ProgramTraceRow):
            admitted.append(row)
            continue
        _, parsed = admit_program_trace_row(row, raise_on_reject=True)
        if parsed is None:
            raise ProgramTraceLeakageError("leakage audit requires admitted rows")
        admitted.append(parsed)

    counts = {name: 0 for name in PROGRAM_TRACE_PARTITIONS}
    families: dict[str, set[str]] = {}
    grouping: dict[str, set[str]] = {}
    repositories: dict[str, set[str]] = {}
    traces: dict[str, set[str]] = {}
    union = _UnionFind()
    axis_members: dict[str, list[str]] = {}

    for row in admitted:
        partition = row.partition_value
        counts[partition] = counts.get(partition, 0) + 1
        families.setdefault(row.family_id, set()).add(partition)
        traces.setdefault(row.trace_cid, set()).add(partition)
        repositories.setdefault(row.repository_id, set()).add(partition)
        union.add(row.row_id)
        for axis in RELATED_GROUPING_AXES:
            value = str(row.grouping_values().get(axis) or "")
            if not value:
                continue
            grouping.setdefault(_related_key(axis, value), set()).add(partition)
            axis_members.setdefault(_related_key(axis, value), []).append(row.row_id)

    for members in axis_members.values():
        first = members[0]
        for item in members[1:]:
            union.union(first, item)

    component_partitions: dict[str, set[str]] = {}
    for row in admitted:
        component_partitions.setdefault(union.find(row.row_id), set()).add(
            row.partition_value
        )

    leaked_families = tuple(
        sorted(family_id for family_id, parts in families.items() if len(parts) > 1)
    )
    leaked_grouping = tuple(
        sorted(key for key, parts in grouping.items() if len(parts) > 1)
    )
    leaked_traces = tuple(
        sorted(trace_cid for trace_cid, parts in traces.items() if len(parts) > 1)
    )
    leaked_components = tuple(
        sorted(
            component
            for component, parts in component_partitions.items()
            if len(parts) > 1
        )
    )
    cross_repository_overlap = tuple(
        sorted(
            repository_id
            for repository_id, parts in repositories.items()
            if "cross_repository" in parts and len(parts) > 1
        )
    )
    leaked = bool(
        leaked_families
        or leaked_grouping
        or leaked_traces
        or leaked_components
        or cross_repository_overlap
    )
    return ProgramTraceLeakageAudit(
        status=(
            ProgramTraceLeakageStatus.FAIL if leaked else ProgramTraceLeakageStatus.PASS
        ),
        disjoint=not leaked,
        leaked_families=leaked_families,
        leaked_grouping=leaked_grouping + leaked_traces,
        cross_repository_overlap=cross_repository_overlap,
        partition_row_counts=counts,
    )


@dataclass(frozen=True, slots=True)
class ProgramTraceLeakageAudit:
    """Content-addressed related-family partition fence receipt."""

    status: ProgramTraceLeakageStatus | str
    disjoint: bool
    leaked_families: tuple[str, ...] = ()
    leaked_grouping: tuple[str, ...] = ()
    cross_repository_overlap: tuple[str, ...] = ()
    partition_row_counts: Mapping[str, int] = field(default_factory=dict)
    mode: str = "related_family_partition_fence"
    rules: tuple[str, ...] = LEAKAGE_RULES
    schema_version: str = PROGRAM_TRACE_LEAKAGE_AUDIT_SCHEMA_VERSION
    interface: str = PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE
    content_digest: str = ""
    content_cid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _parse_enum(self.status, ProgramTraceLeakageStatus, "status"),
        )
        if type(self.disjoint) is not bool:
            raise ProgramTraceCorpusError("disjoint must be a boolean")
        object.__setattr__(
            self, "leaked_families", _unique_texts(self.leaked_families, "leaked_families")
        )
        object.__setattr__(
            self, "leaked_grouping", _unique_texts(self.leaked_grouping, "leaked_grouping")
        )
        object.__setattr__(
            self,
            "cross_repository_overlap",
            _unique_texts(self.cross_repository_overlap, "cross_repository_overlap"),
        )
        counts_mapping = _as_mapping(self.partition_row_counts, "partition_row_counts")
        counts: dict[str, int] = {}
        for name in PROGRAM_TRACE_PARTITIONS:
            raw = counts_mapping.get(name, 0)
            if type(raw) is not int or isinstance(raw, bool) or raw < 0:
                raise ProgramTraceCorpusError(
                    "partition_row_counts values must be non-negative integers"
                )
            counts[name] = raw
        extra = sorted(set(counts_mapping) - PROGRAM_TRACE_PARTITION_SET)
        if extra:
            raise ProgramTraceCorpusError(
                "unknown partition_row_counts key(s): " + ", ".join(extra)
            )
        object.__setattr__(self, "partition_row_counts", MappingProxyType(counts))
        object.__setattr__(self, "mode", _require_identifier(self.mode, "mode"))
        object.__setattr__(self, "rules", _unique_texts(self.rules, "rules"))
        if self.schema_version != PROGRAM_TRACE_LEAKAGE_AUDIT_SCHEMA_VERSION:
            raise ProgramTraceCorpusError("unsupported leakage-audit schema")
        if self.interface != PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE:
            raise ProgramTraceCorpusError("unsupported leakage-audit interface")
        leaked = bool(
            self.leaked_families
            or self.leaked_grouping
            or self.cross_repository_overlap
        )
        passing = self.status is ProgramTraceLeakageStatus.PASS
        if passing and (leaked or not self.disjoint):
            raise ProgramTraceCorpusError("passing leakage audits must be disjoint")
        if not passing and self.disjoint:
            raise ProgramTraceCorpusError("failed leakage audits cannot claim disjoint splits")
        payload = self.identity_payload()
        digest = _sha256_digest(_canonical_bytes(payload))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if self.content_digest and self.content_digest != digest:
            raise ProgramTraceCorpusError("leakage-audit content_digest drifted")
        if self.content_cid and self.content_cid != cid:
            raise ProgramTraceCorpusError("leakage-audit content_cid drifted")
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "content_cid", cid)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "cross_repository_overlap": list(self.cross_repository_overlap),
            "disjoint": self.disjoint,
            "interface": self.interface,
            "leaked_families": list(self.leaked_families),
            "leaked_grouping": list(self.leaked_grouping),
            "mode": self.mode,
            "partition_row_counts": dict(self.partition_row_counts),
            "rules": list(self.rules),
            "schema_version": self.schema_version,
            "status": str(self.status.value if isinstance(self.status, Enum) else self.status),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProgramTraceLeakageAudit":
        mapping = _as_mapping(value, "leakage_audit")
        _reject_unknown(mapping, _LEAKAGE_FIELDS, "leakage_audit")
        return cls(
            status=mapping["status"],
            disjoint=bool(mapping["disjoint"]),
            leaked_families=tuple(mapping.get("leaked_families") or ()),
            leaked_grouping=tuple(mapping.get("leaked_grouping") or ()),
            cross_repository_overlap=tuple(
                mapping.get("cross_repository_overlap") or ()
            ),
            partition_row_counts=mapping.get("partition_row_counts") or {},
            mode=mapping.get("mode", "related_family_partition_fence"),
            rules=tuple(mapping.get("rules") or LEAKAGE_RULES),
            schema_version=mapping.get(
                "schema_version", PROGRAM_TRACE_LEAKAGE_AUDIT_SCHEMA_VERSION
            ),
            interface=mapping.get("interface", PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE),
            content_digest=mapping.get("content_digest", ""),
            content_cid=mapping.get("content_cid", ""),
        )


@dataclass(frozen=True, slots=True)
class ProgramTraceSplitManifest:
    """Six disjoint partition assignments for an admitted corpus."""

    partitions: tuple[str, ...] = PROGRAM_TRACE_PARTITIONS
    partition_row_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    partition_family_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    disjoint: bool = True
    schema_version: str = PROGRAM_TRACE_SPLIT_SCHEMA_VERSION
    interface: str = PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE
    content_digest: str = ""
    content_cid: str = ""

    def __post_init__(self) -> None:
        partitions = _unique_texts(self.partitions, "partitions")
        if tuple(partitions) != PROGRAM_TRACE_PARTITIONS:
            raise ProgramTraceCorpusError(
                "splits must declare the six closed partitions in canonical order"
            )
        object.__setattr__(self, "partitions", partitions)
        row_map = _as_mapping(self.partition_row_ids, "partition_row_ids")
        family_map = _as_mapping(self.partition_family_ids, "partition_family_ids")
        normalized_rows: dict[str, tuple[str, ...]] = {}
        normalized_families: dict[str, tuple[str, ...]] = {}
        seen_rows: set[str] = set()
        for name in PROGRAM_TRACE_PARTITIONS:
            row_ids = tuple(
                sorted(_unique_texts(row_map.get(name, ()), f"partition_row_ids.{name}"))
            )
            overlap = seen_rows.intersection(row_ids)
            if overlap:
                raise ProgramTraceCorpusError(
                    "row identifiers cannot appear in multiple partitions: "
                    + ", ".join(sorted(overlap))
                )
            seen_rows.update(row_ids)
            normalized_rows[name] = row_ids
            normalized_families[name] = tuple(
                sorted(
                    _unique_texts(
                        family_map.get(name, ()), f"partition_family_ids.{name}"
                    )
                )
            )
        extra_rows = sorted(set(row_map) - PROGRAM_TRACE_PARTITION_SET)
        extra_families = sorted(set(family_map) - PROGRAM_TRACE_PARTITION_SET)
        if extra_rows or extra_families:
            raise ProgramTraceCorpusError(
                "unknown split partition key(s): "
                + ", ".join(extra_rows + extra_families)
            )
        object.__setattr__(self, "partition_row_ids", MappingProxyType(normalized_rows))
        object.__setattr__(
            self, "partition_family_ids", MappingProxyType(normalized_families)
        )
        if type(self.disjoint) is not bool:
            raise ProgramTraceCorpusError("disjoint must be a boolean")
        if self.schema_version != PROGRAM_TRACE_SPLIT_SCHEMA_VERSION:
            raise ProgramTraceCorpusError("unsupported split schema")
        if self.interface != PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE:
            raise ProgramTraceCorpusError("unsupported split interface")
        payload = self.identity_payload()
        digest = _sha256_digest(_canonical_bytes(payload))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if self.content_digest and self.content_digest != digest:
            raise ProgramTraceCorpusError("split content_digest drifted")
        if self.content_cid and self.content_cid != cid:
            raise ProgramTraceCorpusError("split content_cid drifted")
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "content_cid", cid)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "disjoint": self.disjoint,
            "interface": self.interface,
            "partition_family_ids": {
                name: list(values)
                for name, values in self.partition_family_ids.items()
            },
            "partition_row_ids": {
                name: list(values) for name, values in self.partition_row_ids.items()
            },
            "partitions": list(self.partitions),
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProgramTraceSplitManifest":
        mapping = _as_mapping(value, "splits")
        _reject_unknown(mapping, _SPLIT_FIELDS, "splits")
        return cls(
            partitions=tuple(mapping.get("partitions") or PROGRAM_TRACE_PARTITIONS),
            partition_row_ids=mapping.get("partition_row_ids") or {},
            partition_family_ids=mapping.get("partition_family_ids") or {},
            disjoint=bool(mapping.get("disjoint", True)),
            schema_version=mapping.get(
                "schema_version", PROGRAM_TRACE_SPLIT_SCHEMA_VERSION
            ),
            interface=mapping.get("interface", PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE),
            content_digest=mapping.get("content_digest", ""),
            content_cid=mapping.get("content_cid", ""),
        )


def _empty_split_manifest() -> ProgramTraceSplitManifest:
    return ProgramTraceSplitManifest(
        partition_row_ids={name: () for name in PROGRAM_TRACE_PARTITIONS},
        partition_family_ids={name: () for name in PROGRAM_TRACE_PARTITIONS},
        disjoint=True,
    )


def _empty_leakage_audit() -> ProgramTraceLeakageAudit:
    return ProgramTraceLeakageAudit(
        status=ProgramTraceLeakageStatus.PASS,
        disjoint=True,
        partition_row_counts={name: 0 for name in PROGRAM_TRACE_PARTITIONS},
    )


def _split_from_rows(rows: Sequence[ProgramTraceRow]) -> ProgramTraceSplitManifest:
    row_ids: dict[str, list[str]] = {name: [] for name in PROGRAM_TRACE_PARTITIONS}
    family_ids: dict[str, set[str]] = {name: set() for name in PROGRAM_TRACE_PARTITIONS}
    for row in rows:
        partition = row.partition_value
        row_ids[partition].append(row.row_id)
        family_ids[partition].add(row.family_id)
    return ProgramTraceSplitManifest(
        partition_row_ids={name: tuple(values) for name, values in row_ids.items()},
        partition_family_ids={
            name: tuple(sorted(values)) for name, values in family_ids.items()
        },
        disjoint=True,
    )


@dataclass(frozen=True, slots=True)
class ProgramTraceCorpusManifest:
    """Admitted execution-trace corpus or typed training_unavailable terminal."""

    corpus_id: str = DEFAULT_CORPUS_ID
    status: ProgramTraceCorpusStatus | str = ProgramTraceCorpusStatus.TRAINING_UNAVAILABLE
    rows: tuple[ProgramTraceRow, ...] = ()
    splits: ProgramTraceSplitManifest | None = None
    leakage_audit: ProgramTraceLeakageAudit | None = None
    language: str = DEFAULT_LANGUAGE
    task_id: str = "SAWM-023"
    training_available: bool = False
    contracts_available: bool = True
    baselines_available: bool = True
    reason: str = "absent_corpus"
    limitations: tuple[str, ...] = (
        "python_only",
        "may_be_too_small_for_learned_promotion",
    )
    schema_version: str = PROGRAM_TRACE_CORPUS_SCHEMA_VERSION
    interface: str = PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE
    content_digest: str = ""
    content_cid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "corpus_id", _require_identifier(self.corpus_id, "corpus_id")
        )
        object.__setattr__(
            self,
            "status",
            _parse_enum(self.status, ProgramTraceCorpusStatus, "status"),
        )
        object.__setattr__(
            self, "language", _closed_value(self.language, ADMITTED_LANGUAGES, "language")
        )
        object.__setattr__(self, "task_id", _require_task_id(self.task_id, "task_id"))
        for flag_name in (
            "training_available",
            "contracts_available",
            "baselines_available",
        ):
            flag = getattr(self, flag_name)
            if type(flag) is not bool:
                raise ProgramTraceCorpusError(f"{flag_name} must be a boolean")
        if self.contracts_available is not True or self.baselines_available is not True:
            raise ProgramTraceCorpusError(
                "absent or admitted corpora must not block contracts or baselines"
            )
        object.__setattr__(self, "reason", _require_identifier(self.reason, "reason"))
        object.__setattr__(
            self, "limitations", _unique_texts(self.limitations, "limitations")
        )
        if self.schema_version != PROGRAM_TRACE_CORPUS_SCHEMA_VERSION:
            raise ProgramTraceCorpusError("unsupported corpus schema")
        if self.interface != PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE:
            raise ProgramTraceCorpusError("unsupported corpus interface")
        normalized_rows = tuple(self.rows)
        if any(not isinstance(row, ProgramTraceRow) for row in normalized_rows):
            raise ProgramTraceCorpusError("rows must be ProgramTraceRow values")
        object.__setattr__(self, "rows", normalized_rows)
        splits = self.splits if self.splits is not None else _empty_split_manifest()
        if not isinstance(splits, ProgramTraceSplitManifest):
            raise ProgramTraceCorpusError("splits must be a ProgramTraceSplitManifest")
        leakage = (
            self.leakage_audit if self.leakage_audit is not None else _empty_leakage_audit()
        )
        if not isinstance(leakage, ProgramTraceLeakageAudit):
            raise ProgramTraceCorpusError(
                "leakage_audit must be a ProgramTraceLeakageAudit"
            )
        object.__setattr__(self, "splits", splits)
        object.__setattr__(self, "leakage_audit", leakage)
        admitted = self.status is ProgramTraceCorpusStatus.ADMITTED
        if admitted:
            if not self.rows:
                raise ProgramTraceCorpusError("admitted corpora require rows")
            if not self.training_available:
                raise ProgramTraceCorpusError(
                    "admitted corpora must report training_available"
                )
            if self.reason != "admitted_corpus":
                raise ProgramTraceCorpusError(
                    "admitted corpora must use reason admitted_corpus"
                )
            if leakage.status is not ProgramTraceLeakageStatus.PASS or not leakage.disjoint:
                raise ProgramTraceLeakageError(
                    "admitted corpora cannot leak related families across partitions"
                )
        else:
            if self.rows:
                raise ProgramTraceCorpusError(
                    "training_unavailable corpora cannot carry admitted rows"
                )
            if self.training_available:
                raise ProgramTraceCorpusError(
                    "training_unavailable cannot claim training_available"
                )
            if self.reason == "admitted_corpus":
                raise ProgramTraceCorpusError(
                    "training_unavailable cannot use reason admitted_corpus"
                )
        payload = self.identity_payload()
        digest = _sha256_digest(_canonical_bytes(payload))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if self.content_digest and self.content_digest != digest:
            raise ProgramTraceCorpusError("corpus content_digest drifted")
        if self.content_cid and self.content_cid != cid:
            raise ProgramTraceCorpusError("corpus content_cid drifted")
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "content_cid", cid)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def training_status(self) -> str:
        return str(self.status.value if isinstance(self.status, Enum) else self.status)

    def identity_payload(self) -> dict[str, Any]:
        assert self.splits is not None
        assert self.leakage_audit is not None
        return {
            "baselines_available": self.baselines_available,
            "contracts_available": self.contracts_available,
            "corpus_id": self.corpus_id,
            "interface": self.interface,
            "language": self.language,
            "leakage_audit": self.leakage_audit.to_dict(),
            "limitations": list(self.limitations),
            "reason": self.reason,
            "row_count": self.row_count,
            "rows": [row.to_dict() for row in self.rows],
            "schema_version": self.schema_version,
            "splits": self.splits.to_dict(),
            "status": self.training_status,
            "task_id": self.task_id,
            "training_available": self.training_available,
            "training_status": self.training_status,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProgramTraceCorpusManifest":
        mapping = _as_mapping(value, "corpus")
        _reject_unknown(mapping, _MANIFEST_FIELDS, "corpus")
        rows = tuple(
            ProgramTraceRow.from_dict(item) for item in (mapping.get("rows") or ())
        )
        splits_value = mapping.get("splits")
        leakage_value = mapping.get("leakage_audit")
        return cls(
            corpus_id=mapping.get("corpus_id", DEFAULT_CORPUS_ID),
            status=mapping.get("status", TRAINING_UNAVAILABLE),
            rows=rows,
            splits=(
                ProgramTraceSplitManifest.from_dict(splits_value)
                if isinstance(splits_value, Mapping)
                else None
            ),
            leakage_audit=(
                ProgramTraceLeakageAudit.from_dict(leakage_value)
                if isinstance(leakage_value, Mapping)
                else None
            ),
            language=mapping.get("language", DEFAULT_LANGUAGE),
            task_id=mapping.get("task_id", "SAWM-023"),
            training_available=bool(mapping.get("training_available", False)),
            contracts_available=bool(mapping.get("contracts_available", True)),
            baselines_available=bool(mapping.get("baselines_available", True)),
            reason=mapping.get("reason", "absent_corpus"),
            limitations=tuple(mapping.get("limitations") or ()),
            schema_version=mapping.get(
                "schema_version", PROGRAM_TRACE_CORPUS_SCHEMA_VERSION
            ),
            interface=mapping.get(
                "interface", PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE
            ),
            content_digest=mapping.get("content_digest", ""),
            content_cid=mapping.get("content_cid", ""),
        )


def training_unavailable_program_trace_corpus(
    *,
    corpus_id: str = DEFAULT_CORPUS_ID,
    reason: str = "absent_corpus",
    task_id: str = "SAWM-023",
) -> ProgramTraceCorpusManifest:
    """Return the typed training-only terminal that leaves contracts unblocked."""

    return ProgramTraceCorpusManifest(
        corpus_id=corpus_id,
        status=ProgramTraceCorpusStatus.TRAINING_UNAVAILABLE,
        reason=reason,
        task_id=task_id,
        training_available=False,
        contracts_available=True,
        baselines_available=True,
    )


def _load_mapping(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _as_mapping(payload, "fixture")


def _rows_from_source(
    source: Mapping[str, Any] | Sequence[Any],
) -> list[dict[str, Any]]:
    if isinstance(source, Mapping) and "recipes" in source:
        schema = source.get("schema")
        if schema not in (None, PROGRAM_TRACE_RECIPE_SCHEMA_VERSION):
            raise ProgramTraceCorpusError("unsupported program-trace recipe schema")
        defaults = source.get("defaults") or {}
        if defaults is not None:
            defaults = _as_mapping(defaults, "defaults")
        corpus_id = str(source.get("corpus_id") or DEFAULT_CORPUS_ID)
        recipes = source.get("recipes")
        if not isinstance(recipes, Sequence) or isinstance(recipes, (str, bytes, bytearray)):
            raise ProgramTraceCorpusError("recipes must be a sequence of mappings")
        return [
            expand_program_trace_recipe(
                _as_mapping(recipe, "recipe"),
                defaults=defaults,
                corpus_id=corpus_id,
            )
            for recipe in recipes
        ]
    if isinstance(source, Mapping) and "rows" in source:
        rows = source.get("rows")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            raise ProgramTraceCorpusError("rows must be a sequence of mappings")
        return [dict(_as_mapping(row, "row")) for row in rows]
    if isinstance(source, Sequence) and not isinstance(source, (str, bytes, bytearray)):
        return [
            dict(item.to_dict()) if isinstance(item, ProgramTraceRow) else dict(_as_mapping(item, "row"))
            for item in source
        ]
    raise ProgramTraceCorpusError("corpus source must be recipes, rows, or a row sequence")


def build_program_trace_corpus(
    source: Mapping[str, Any] | Sequence[Any] | Path | str | None = None,
    *,
    path: str | Path | None = None,
    allow_empty: bool = True,
) -> ProgramTraceCorpusManifest:
    """Build an admitted corpus or return training_unavailable for an absent set."""

    fixture_path: Path | None = None
    payload: Mapping[str, Any] | Sequence[Any] | None = source
    if path is not None:
        fixture_path = Path(path)
    elif isinstance(source, (str, Path)):
        fixture_path = Path(source)
        payload = None
    elif source is None:
        fixture_path = default_program_trace_corpus_fixture_path()

    corpus_id = DEFAULT_CORPUS_ID
    task_id = "SAWM-023"
    if fixture_path is not None:
        if not fixture_path.is_file():
            if allow_empty:
                return training_unavailable_program_trace_corpus(reason="absent_corpus")
            raise ProgramTraceCorpusError(f"corpus fixture is absent: {fixture_path}")
        loaded = _load_mapping(fixture_path)
        payload = loaded
        corpus_id = str(loaded.get("corpus_id") or corpus_id)
        task_id = str(loaded.get("task_id") or task_id)

    if payload is None:
        return training_unavailable_program_trace_corpus(reason="absent_corpus")

    if isinstance(payload, Mapping):
        corpus_id = str(payload.get("corpus_id") or corpus_id)
        task_id = str(payload.get("task_id") or task_id)

    row_payloads = _rows_from_source(payload)
    if not row_payloads:
        return training_unavailable_program_trace_corpus(
            corpus_id=corpus_id, task_id=task_id, reason="absent_corpus"
        )
    if len(row_payloads) > MAX_ROWS:
        raise ProgramTraceCorpusError("corpus exceeds the bounded row maximum")

    admitted_rows: list[ProgramTraceRow] = []
    seen_ids: set[str] = set()
    for item in row_payloads:
        admission, row = admit_program_trace_row(item)
        if row is None:
            raise ProgramTraceAdmissionError(
                f"row {admission.row_id} rejected: {', '.join(admission.reasons)}"
            )
        if row.row_id in seen_ids:
            raise ProgramTraceCorpusError(f"duplicate row_id: {row.row_id}")
        seen_ids.add(row.row_id)
        admitted_rows.append(row)

    leakage = audit_program_trace_leakage(admitted_rows)
    if leakage.status is ProgramTraceLeakageStatus.FAIL:
        details = ", ".join(
            (
                *leakage.leaked_families,
                *leakage.leaked_grouping,
                *leakage.cross_repository_overlap,
            )
        )
        raise ProgramTraceLeakageError(
            "related families leak across partitions: " + details
        )
    splits = _split_from_rows(admitted_rows)
    ordered = tuple(sorted(admitted_rows, key=lambda row: row.row_id))
    return ProgramTraceCorpusManifest(
        corpus_id=_require_identifier(corpus_id, "corpus_id"),
        status=ProgramTraceCorpusStatus.ADMITTED,
        rows=ordered,
        splits=splits,
        leakage_audit=leakage,
        task_id=_require_task_id(task_id, "task_id"),
        training_available=True,
        contracts_available=True,
        baselines_available=True,
        reason="admitted_corpus",
    )


def load_program_trace_reject_recipes(
    path: str | Path | None = None,
) -> tuple[dict[str, Any], ...]:
    """Load compact negative recipes that must remain excluded."""

    fixture_path = Path(path) if path is not None else default_program_trace_corpus_fixture_path()
    if not fixture_path.is_file():
        return ()
    payload = _load_mapping(fixture_path)
    defaults = payload.get("defaults") or {}
    recipes = payload.get("reject_recipes") or ()
    if not isinstance(recipes, Sequence) or isinstance(recipes, (str, bytes, bytearray)):
        raise ProgramTraceCorpusError("reject_recipes must be a sequence of mappings")
    corpus_id = str(payload.get("corpus_id") or DEFAULT_CORPUS_ID)
    expanded: list[dict[str, Any]] = []
    for recipe in recipes:
        mapping = dict(_as_mapping(recipe, "reject_recipe"))
        expect = mapping.pop("expect", "reject")
        expect_reasons = tuple(mapping.pop("expect_reasons", ()) or ())
        row = expand_program_trace_recipe(
            mapping,
            defaults=_as_mapping(defaults, "defaults") if defaults else {},
            corpus_id=corpus_id,
        )
        row["expect"] = expect
        row["expect_reasons"] = list(expect_reasons)
        expanded.append(row)
    return tuple(expanded)


__all__ = [
    "ADMITTED_SOURCE_KINDS",
    "EXECUTION_TRACE_CORPUS_INTERFACE",
    "GROUND_TRUTH_KINDS",
    "PROGRAM_TRACE_ADMISSION_INTERFACE",
    "PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE",
    "PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE",
    "PROGRAM_TRACE_PARTITIONS",
    "PROGRAM_TRACE_RECIPE_SCHEMA_VERSION",
    "PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE",
    "TRAINING_UNAVAILABLE",
    "ProgramTraceAdmission",
    "ProgramTraceAdmissionError",
    "ProgramTraceAdmissionStatus",
    "ProgramTraceCorpusError",
    "ProgramTraceCorpusManifest",
    "ProgramTraceCorpusStatus",
    "ProgramTraceLeakageAudit",
    "ProgramTraceLeakageError",
    "ProgramTraceLeakageStatus",
    "ProgramTracePartition",
    "ProgramTraceRow",
    "ProgramTraceSplitManifest",
    "admit_program_trace_row",
    "audit_program_trace_leakage",
    "build_program_trace_corpus",
    "default_program_trace_corpus_fixture_path",
    "expand_program_trace_recipe",
    "load_program_trace_reject_recipes",
    "training_unavailable_program_trace_corpus",
]
