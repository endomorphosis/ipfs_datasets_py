"""Rights-admitted execution-trace corpus (ExecutionTraceCorpus@1 / SAWM-023).

Datasets owns corpus admission and split semantics.  This leaf materializes
first-party hermetic, synthetic, adversarial, and observed trace *recipes*
into rights/privacy/lineage admitted rows bound to an exact tree, then
places related families into six disjoint partitions.

Normative rules:

* Every admitted row is rights-admitted, privacy-admitted, and exact-tree
  bound.  Unknown-rights, hidden tests, private reasoning, credentials,
  unadmitted production, tenant-private, private-witness, and arbitrary
  transcript sources fail closed.
* Related families (family, task, function, failure, mutant, proof,
  procedure) cannot leak across partitions.
* Model nominations are never labels.  Ground truth is static, runtime,
  proof, test, human, or mechanical-counterexample evidence only.
* An absent or empty corpus returns ``training_unavailable`` without
  blocking contracts or deterministic baselines.
* Importing this module performs no I/O, network, installer, subprocess,
  database, repository scan, watcher, or model load.

This module does not promote accelerator checkpoints, choose kit storage,
or publish raw private traces.
"""

from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable

from ipfs_datasets_py.logic.software_contracts.content import (
    StructuredIdentityError,
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
    validate_cid,
    validate_structured_value,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

EXECUTION_TRACE_CORPUS_INTERFACE: Final[str] = "ExecutionTraceCorpus@1"
PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE: Final[str] = "ProgramTraceCorpusManifest@1"
PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE: Final[str] = "ProgramTraceSplitManifest@1"
PROGRAM_TRACE_ADMISSION_INTERFACE: Final[str] = "ProgramTraceAdmission@1"
PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE: Final[str] = "ProgramTraceLeakageAudit@1"

EXECUTION_TRACE_CORPUS_SCHEMA: Final[str] = "sawm/trace-corpus@1"
PROGRAM_TRACE_CORPUS_MANIFEST_SCHEMA: Final[str] = (
    "ipfs-datasets.proof-corpus.program-trace-corpus-manifest@1"
)
PROGRAM_TRACE_SPLIT_MANIFEST_SCHEMA: Final[str] = (
    "ipfs-datasets.proof-corpus.program-trace-split-manifest@1"
)
PROGRAM_TRACE_ADMISSION_SCHEMA: Final[str] = (
    "ipfs-datasets.proof-corpus.program-trace-admission@1"
)
PROGRAM_TRACE_LEAKAGE_AUDIT_SCHEMA: Final[str] = (
    "ipfs-datasets.proof-corpus.program-trace-leakage-audit@1"
)
PROGRAM_TRACE_ROW_SCHEMA: Final[str] = (
    "ipfs-datasets.proof-corpus.program-trace-row@1"
)
PROGRAM_TRACE_LINEAGE_SCHEMA: Final[str] = (
    "ipfs-datasets.proof-corpus.program-trace-lineage@1"
)
PROGRAM_TRACE_ROW_TRACE_SCHEMA: Final[str] = (
    "ipfs-datasets.proof-corpus.program-trace-row-trace@1"
)

CORPUS_ADMISSION_EVIDENCE: Final[str] = "sawm/corpus-admission@1"
SPLIT_LEAKAGE_EVIDENCE: Final[str] = "sawm/split-leakage@1"

TRAINING_UNAVAILABLE: Final[str] = "training_unavailable"
CORPUS_ADMITTED: Final[str] = "admitted"
DEFAULT_CORPUS_ID: Final[str] = "program-world-trace-corpus-v1"
DEFAULT_TASK_ID: Final[str] = "SAWM-023"
ADMITTED_LANGUAGE: Final[str] = "python"

MAX_TEXT_CHARS: Final[int] = 1_024
MAX_LABEL_CHARS: Final[int] = 256
MAX_ROWS: Final[int] = 10_000
MAX_REASON_CODES: Final[int] = 64
MAX_FINDINGS: Final[int] = 256
MAX_METADATA_BYTES: Final[int] = 16_384
MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1

IMPORT_NETWORK_PERFORMED: Final[bool] = False
IMPORT_SOCKET_PERFORMED: Final[bool] = False
IMPORT_INSTALLER_PERFORMED: Final[bool] = False
IMPORT_SUBPROCESS_PERFORMED: Final[bool] = False
IMPORT_DATABASE_PERFORMED: Final[bool] = False
IMPORT_REPO_SCAN_PERFORMED: Final[bool] = False
IMPORT_WATCHER_PERFORMED: Final[bool] = False
IMPORT_MODEL_LOAD_PERFORMED: Final[bool] = False
IMPORT_SIDE_EFFECTS_PERFORMED: Final[bool] = False

GROUPING_KEYS: Final[tuple[str, ...]] = (
    "repository",
    "commit",
    "task",
    "function",
    "failure",
    "mutant",
    "proof",
    "procedure",
)
REQUIRED_GROUPING_KEYS: Final[tuple[str, ...]] = (
    "repository",
    "commit",
    "task",
    "function",
)
LEAKAGE_GROUPING_KEYS: Final[tuple[str, ...]] = (
    "family_id",
    "task",
    "function",
    "failure",
    "mutant",
    "proof",
    "procedure",
)

PARTITIONS: Final[tuple[str, ...]] = (
    "training",
    "development",
    "held_out",
    "adversarial",
    "cross_repository",
    "ood",
)
DEVELOPMENT_PARTITIONS: Final[frozenset[str]] = frozenset(
    {"training", "development"}
)
EVALUATION_PARTITIONS: Final[frozenset[str]] = frozenset(
    {"held_out", "adversarial", "cross_repository", "ood"}
)
INTRA_REPOSITORY_PARTITIONS: Final[frozenset[str]] = frozenset(
    {"training", "development", "held_out"}
)


class ProgramTraceCorpusError(ValueError):
    """Raised when a program-trace corpus payload is malformed."""


class ProgramTraceCorpusIntegrityError(ProgramTraceCorpusError):
    """Raised when admitted rows fail lineage, identity, or leakage integrity."""


class ProgramTraceCorpusLeakageError(ProgramTraceCorpusIntegrityError):
    """Raised when related families leak across partitions."""


class TracePartition(str, Enum):
    TRAINING = "training"
    DEVELOPMENT = "development"
    HELD_OUT = "held_out"
    ADVERSARIAL = "adversarial"
    CROSS_REPOSITORY = "cross_repository"
    OOD = "ood"


class TraceSourceClass(str, Enum):
    FIRST_PARTY_HERMETIC = "first_party_hermetic"
    INSTRUMENTED_TEST = "instrumented_test"
    ADMITTED_STATIC_EDGE = "admitted_static_edge"
    ADMITTED_DYNAMIC_EDGE = "admitted_dynamic_edge"
    SYNTHETIC_PROGRAM = "synthetic_program"
    ADVERSARIAL_MUTANT = "adversarial_mutant"
    MECHANICAL_COUNTEREXAMPLE = "mechanical_counterexample"
    ADMITTED_PUBLIC = "admitted_public"
    RIGHTS_CLEARED_REVIEW = "rights_cleared_review"
    OBSERVED = "observed"


class TraceRightsClass(str, Enum):
    FIRST_PARTY_HERMETIC = "first_party_hermetic"
    INSTRUMENTED_TEST = "instrumented_test"
    ADMITTED_STATIC_EDGE = "admitted_static_edge"
    ADMITTED_DYNAMIC_EDGE = "admitted_dynamic_edge"
    SYNTHETIC_PROGRAM = "synthetic_program"
    ADVERSARIAL_MUTANT = "adversarial_mutant"
    MECHANICAL_COUNTEREXAMPLE = "mechanical_counterexample"
    ADMITTED_PUBLIC = "admitted_public"
    RIGHTS_CLEARED_REVIEW = "rights_cleared_review"


class ForbiddenRightsClass(str, Enum):
    PRIVATE_CHAIN_OF_THOUGHT = "private_chain_of_thought"
    CREDENTIALS = "credentials"
    HIDDEN_TEST = "hidden_test"
    UNADMITTED_PRODUCTION = "unadmitted_production"
    TENANT_PRIVATE = "tenant_private"
    PRIVATE_WITNESS = "private_witness"
    ARBITRARY_TRANSCRIPT = "arbitrary_transcript"
    UNKNOWN_RIGHTS = "unknown_rights"


class TracePrivacyClass(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    PRIVATE = "private"


class LabelAuthority(str, Enum):
    STATIC = "static"
    RUNTIME = "runtime"
    PROOF = "proof"
    TEST = "test"
    HUMAN = "human"
    MECHANICAL_COUNTEREXAMPLE = "mechanical_counterexample"


class QueryFamily(str, Enum):
    NEXT_CALL = "next_call"
    NEXT_EVENT = "next_event"
    INVERSE_TRACE = "inverse_trace"
    REPAIR = "repair"


class AdmissionVerdict(str, Enum):
    ADMITTED = "admitted"
    REJECTED = "rejected"
    TRAINING_UNAVAILABLE = "training_unavailable"


class SplitRole(str, Enum):
    DEVELOPMENT = "development"
    EVALUATION = "evaluation"


class CorpusAvailability(str, Enum):
    ADMITTED = "admitted"
    TRAINING_UNAVAILABLE = "training_unavailable"


ADMITTED_SOURCE_CLASSES: Final[frozenset[str]] = frozenset(
    item.value for item in TraceSourceClass
)
ADMITTED_RIGHTS_CLASSES: Final[frozenset[str]] = frozenset(
    item.value for item in TraceRightsClass
)
FORBIDDEN_RIGHTS_CLASSES: Final[frozenset[str]] = frozenset(
    item.value for item in ForbiddenRightsClass
)
ADMITTED_PRIVACY_CLASSES: Final[frozenset[str]] = frozenset(
    {TracePrivacyClass.PUBLIC.value, TracePrivacyClass.INTERNAL.value}
)
FORBIDDEN_PRIVACY_CLASSES: Final[frozenset[str]] = frozenset(
    {TracePrivacyClass.RESTRICTED.value, TracePrivacyClass.PRIVATE.value}
)
LABEL_AUTHORITIES: Final[frozenset[str]] = frozenset(
    item.value for item in LabelAuthority
)
MODEL_NOMINATION_AUTHORITIES: Final[frozenset[str]] = frozenset(
    {
        "model",
        "model_nomination",
        "llm",
        "prediction",
        "specialist",
        "learned",
        "neural",
    }
)
QUERY_FAMILIES: Final[frozenset[str]] = frozenset(item.value for item in QueryFamily)
PARTITION_VALUES: Final[frozenset[str]] = frozenset(PARTITIONS)

SECRET_FIELD_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "chain_of_thought",
        "cookie",
        "credential",
        "credentials",
        "hidden_cot",
        "hidden_test",
        "hidden_tests",
        "password",
        "private_key",
        "private_reasoning",
        "private_witness",
        "refresh_token",
        "secret",
        "session_token",
        "tenant_secret",
    }
)
FORBIDDEN_CONTENT_MARKERS: Final[frozenset[str]] = SECRET_FIELD_MARKERS | frozenset(
    {
        "arbitrary_transcript",
        "hidden_witness",
        "private_chain_of_thought",
        "raw_private_trace",
        "tenant_private",
        "unadmitted_production",
        "unknown_rights",
    }
)

_ROW_IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "schema",
    "row_id",
    "partition",
    "source_class",
    "rights_class",
    "privacy_class",
    "language",
    "family_id",
    "repository",
    "commit",
    "task",
    "function",
    "failure",
    "mutant",
    "proof",
    "procedure",
    "tree_cid",
    "source_cid",
    "environment_binding_cid",
    "execution_trace_cid",
    "label_authority",
    "label",
    "query_family",
    "rights_admitted",
    "privacy_admitted",
    "exact_tree_bound",
)

_OPTIONAL_RECIPE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "commit",
        "environment_binding_cid",
        "environment_id",
        "execution_trace_cid",
        "execution_trace_id",
        "failure",
        "grouping",
        "label",
        "model_nomination",
        "mutant",
        "procedure",
        "proof",
        "query_family",
        "source_cid",
        "source_id",
        "tree_cid",
        "tree_id",
    }
)
_REQUIRED_RECIPE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "family_id",
        "grouping",
        "label_authority",
        "language",
        "partition",
        "privacy_class",
        "rights_class",
        "row_id",
        "source_class",
    }
)


def default_program_trace_corpus_path() -> Path:
    """Return the compact default recipe fixture path (may be absent)."""

    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "program_world_trace_corpus.json"
    )


def _text(value: Any, name: str, *, empty: bool = False, maximum: int = MAX_TEXT_CHARS) -> str:
    if type(value) is not str or (not empty and not value):
        raise ProgramTraceCorpusError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise ProgramTraceCorpusError(f"{name} must be trimmed NFC text")
    if len(value) > maximum or any(not char.isprintable() for char in value):
        raise ProgramTraceCorpusError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str, *, maximum: int = MAX_TEXT_CHARS) -> str:
    if value in (None, ""):
        return ""
    return _text(value, name, maximum=maximum)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    if isinstance(value, enum_type):
        return value.value
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise ProgramTraceCorpusError(f"{name} has unsupported value {value!r}") from exc


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ProgramTraceCorpusError(f"{name} must be a boolean")
    return value


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise ProgramTraceCorpusError(f"{name} must be a valid CID") from exc


def _label_cid(label: str) -> str:
    return cid_for_bytes(f"sawm-023:{label}".encode("utf-8"))


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProgramTraceCorpusError(f"{name} must be a mapping")
    return value


def _reject_forbidden_content(value: Any, name: str) -> None:
    if isinstance(value, Mapping):
        forbidden = set(value) & FORBIDDEN_CONTENT_MARKERS
        if forbidden:
            raise ProgramTraceCorpusError(
                f"{name} rejects forbidden fields {sorted(forbidden)}"
            )
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in SECRET_FIELD_MARKERS):
                raise ProgramTraceCorpusError(
                    f"{name} rejects secret or private field {key!r}"
                )
            _reject_forbidden_content(item, f"{name}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_forbidden_content(item, f"{name}[{index}]")


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ProgramTraceCorpusError(f"{name} must be a mapping")
    extra = set(data) - fields
    if extra:
        secrets = extra & SECRET_FIELD_MARKERS
        if secrets:
            raise ProgramTraceCorpusError(
                f"{name} rejects secret fields {sorted(secrets)}"
            )
        raise ProgramTraceCorpusError(f"{name} rejects unknown fields {sorted(extra)}")
    _reject_forbidden_content(data, name)
    return dict(data)


def _unique_texts(values: Iterable[Any], name: str) -> tuple[str, ...]:
    items = tuple(_text(value, name) for value in values)
    if len(items) != len(set(items)):
        raise ProgramTraceCorpusError(f"{name} must not contain duplicates")
    return items


def _reason_codes(values: Iterable[str]) -> tuple[str, ...]:
    codes: list[str] = []
    seen: set[str] = set()
    for value in values:
        code = _text(value, "reason_code", maximum=MAX_LABEL_CHARS)
        if code in seen:
            continue
        seen.add(code)
        codes.append(code)
        if len(codes) > MAX_REASON_CODES:
            raise ProgramTraceCorpusError("reason_codes exceeds its bound")
    return tuple(codes)


def corpus_cid_for(payload: Mapping[str, Any]) -> str:
    """Return the structured CID of one canonical corpus payload."""

    try:
        validate_structured_value(payload)
    except (StructuredIdentityError, TypeError, ValueError) as exc:
        raise ProgramTraceCorpusError("corpus payload must be strict DAG-JSON") from exc
    encoded = canonical_dag_json_bytes(payload)
    if len(encoded) > MAX_METADATA_BYTES * 64:
        raise ProgramTraceCorpusError("corpus payload exceeds its byte bound")
    return cid_for_structured(payload)


def _grouping_from_recipe(data: Mapping[str, Any]) -> dict[str, str]:
    grouping = data.get("grouping", data)
    mapping = _as_mapping(grouping, "grouping")
    extra = set(mapping) - set(GROUPING_KEYS)
    if extra:
        raise ProgramTraceCorpusError(f"grouping rejects unknown fields {sorted(extra)}")
    values = {
        key: _optional_text(mapping.get(key, data.get(key, "")), key)
        for key in GROUPING_KEYS
    }
    missing = [key for key in REQUIRED_GROUPING_KEYS if not values[key]]
    if missing:
        raise ProgramTraceCorpusError(
            f"grouping missing required keys {missing}"
        )
    return values


def _scan_policy_reasons(data: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    try:
        _reject_forbidden_content(data, "row")
    except ProgramTraceCorpusError:
        reasons.append("forbidden_private_content")

    rights = str(data.get("rights_class") or "")
    source = str(data.get("source_class") or "")
    privacy = str(data.get("privacy_class") or "")
    authority = str(data.get("label_authority") or data.get("ground_truth_source") or "")
    language = str(data.get("language") or "")

    if rights in FORBIDDEN_RIGHTS_CLASSES or source in FORBIDDEN_RIGHTS_CLASSES:
        reasons.append("forbidden_rights_class")
    if rights == ForbiddenRightsClass.UNKNOWN_RIGHTS.value or source == "unknown_rights":
        reasons.append("unknown_rights")
    if rights == ForbiddenRightsClass.HIDDEN_TEST.value or source in {
        "hidden_test",
        "hidden_tests",
    }:
        reasons.append("hidden_test")
    if rights == ForbiddenRightsClass.PRIVATE_CHAIN_OF_THOUGHT.value or source in {
        "private_chain_of_thought",
        "private_reasoning",
    }:
        reasons.append("private_reasoning")
    if rights == ForbiddenRightsClass.UNADMITTED_PRODUCTION.value or source in {
        "unadmitted_production",
        "production_trace",
    }:
        reasons.append("unadmitted_source")
    if rights == ForbiddenRightsClass.TENANT_PRIVATE.value or privacy == "tenant":
        reasons.append("tenant_private")
    if rights == ForbiddenRightsClass.PRIVATE_WITNESS.value:
        reasons.append("private_witness")
    if rights == ForbiddenRightsClass.ARBITRARY_TRANSCRIPT.value or source in {
        "arbitrary_transcript",
        "transcript",
    }:
        reasons.append("arbitrary_transcript")
    if rights == ForbiddenRightsClass.CREDENTIALS.value:
        reasons.append("credentials")
    if rights not in ADMITTED_RIGHTS_CLASSES:
        reasons.append("rights_not_admitted")
    if source not in ADMITTED_SOURCE_CLASSES:
        reasons.append("source_not_admitted")
    if privacy not in ADMITTED_PRIVACY_CLASSES:
        reasons.append("privacy_not_admitted")
    if language and language != ADMITTED_LANGUAGE:
        reasons.append("language_unavailable")
    if authority in MODEL_NOMINATION_AUTHORITIES:
        reasons.append("model_nomination_label")
    label = data.get("label")
    nomination = data.get("model_nomination")
    if nomination not in (None, "") and label == nomination:
        reasons.append("model_nomination_label")
    if not data.get("tree_cid") and not data.get("tree_id"):
        reasons.append("missing_exact_tree_binding")
    if data.get("hidden_test") is True or data.get("hidden_tests") is True:
        reasons.append("hidden_test")
    return list(dict.fromkeys(reasons))


def _normalized_row_payload(data: Mapping[str, Any]) -> dict[str, Any]:
    grouping = _grouping_from_recipe(data)
    tree_cid = data.get("tree_cid")
    if tree_cid in (None, ""):
        tree_cid = _label_cid(_text(data.get("tree_id"), "tree_id"))
    else:
        tree_cid = _cid(tree_cid, "tree_cid")
    source_cid = data.get("source_cid")
    if source_cid in (None, ""):
        source_label = _optional_text(data.get("source_id"), "source_id") or grouping["function"]
        source_cid = _label_cid(f"source:{source_label}")
    else:
        source_cid = _cid(source_cid, "source_cid")
    environment_cid = data.get("environment_binding_cid")
    if environment_cid in (None, ""):
        environment_label = (
            _optional_text(data.get("environment_id"), "environment_id")
            or "python-3.12"
        )
        environment_cid = _label_cid(f"env:{environment_label}")
    else:
        environment_cid = _cid(environment_cid, "environment_binding_cid")
    row_id = _text(data.get("row_id"), "row_id", maximum=MAX_LABEL_CHARS)
    partition = _enum(data.get("partition"), TracePartition, "partition")
    query_family = _enum(
        data.get("query_family") or QueryFamily.NEXT_CALL.value,
        QueryFamily,
        "query_family",
    )
    trace_identity = {
        "schema": PROGRAM_TRACE_ROW_TRACE_SCHEMA,
        "row_id": row_id,
        "tree_cid": tree_cid,
        "source_cid": source_cid,
        "environment_binding_cid": environment_cid,
        "query_family": query_family,
        "family_id": _text(data.get("family_id"), "family_id"),
    }
    execution_trace_cid = cid_for_structured(trace_identity)
    claimed_trace = data.get("execution_trace_cid")
    if claimed_trace not in (None, ""):
        claimed = _cid(claimed_trace, "execution_trace_cid")
        if claimed != execution_trace_cid:
            raise ProgramTraceCorpusIntegrityError(
                "execution_trace_cid does not match the exact-tree recipe identity"
            )
    label = _text(
        data.get("label") or grouping["function"],
        "label",
        maximum=MAX_LABEL_CHARS,
    )
    payload = {
        "schema": PROGRAM_TRACE_ROW_SCHEMA,
        "row_id": row_id,
        "partition": partition,
        "source_class": _enum(data.get("source_class"), TraceSourceClass, "source_class"),
        "rights_class": _enum(data.get("rights_class"), TraceRightsClass, "rights_class"),
        "privacy_class": _enum(data.get("privacy_class"), TracePrivacyClass, "privacy_class"),
        "language": _text(data.get("language") or ADMITTED_LANGUAGE, "language"),
        "family_id": _text(data.get("family_id"), "family_id"),
        "repository": grouping["repository"],
        "commit": grouping["commit"],
        "task": grouping["task"],
        "function": grouping["function"],
        "failure": grouping["failure"],
        "mutant": grouping["mutant"],
        "proof": grouping["proof"],
        "procedure": grouping["procedure"],
        "tree_cid": tree_cid,
        "source_cid": source_cid,
        "environment_binding_cid": environment_cid,
        "execution_trace_cid": execution_trace_cid,
        "label_authority": _enum(
            data.get("label_authority"), LabelAuthority, "label_authority"
        ),
        "label": label,
        "query_family": query_family,
        "rights_admitted": True,
        "privacy_admitted": True,
        "exact_tree_bound": True,
    }
    if payload["language"] != ADMITTED_LANGUAGE:
        raise ProgramTraceCorpusError("language is typed unavailable in this corpus")
    if payload["privacy_class"] not in ADMITTED_PRIVACY_CLASSES:
        raise ProgramTraceCorpusError("privacy_class is not corpus-admitted")
    if payload["label_authority"] in MODEL_NOMINATION_AUTHORITIES:
        raise ProgramTraceCorpusError("model nominations are never labels")
    return payload


def _lineage_for(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": PROGRAM_TRACE_LINEAGE_SCHEMA,
        "row_id": row["row_id"],
        "rights_class": row["rights_class"],
        "source_class": row["source_class"],
        "privacy_class": row["privacy_class"],
        "tree_cid": row["tree_cid"],
        "source_cid": row["source_cid"],
        "environment_binding_cid": row["environment_binding_cid"],
        "execution_trace_cid": row["execution_trace_cid"],
        "repository": row["repository"],
        "commit": row["commit"],
        "family_id": row["family_id"],
        "label_authority": row["label_authority"],
        "model_nomination_is_label": False,
    }


def _recipe_field_reasons(data: Mapping[str, Any]) -> list[str]:
    allowed = _REQUIRED_RECIPE_FIELDS | _OPTIONAL_RECIPE_FIELDS | set(GROUPING_KEYS)
    extra = set(data) - allowed
    reasons: list[str] = []
    if extra & FORBIDDEN_CONTENT_MARKERS or extra & SECRET_FIELD_MARKERS:
        reasons.append("forbidden_private_content")
    unknown = extra - FORBIDDEN_CONTENT_MARKERS - SECRET_FIELD_MARKERS - {"hidden_test", "hidden_tests"}
    if unknown:
        reasons.append("unknown_fields")
    missing = [name for name in sorted(_REQUIRED_RECIPE_FIELDS) if name not in data]
    if missing:
        reasons.append("missing_required_fields")
    return reasons


@dataclass(frozen=True, slots=True)
class ProgramTraceAdmission:
    """Per-row rights, privacy, lineage, and exact-tree admission receipt."""

    verdict: AdmissionVerdict | str
    reason_codes: Sequence[str] = ()
    row_id: str = ""
    tree_cid: str = ""
    source_cid: str = ""
    privacy_class: str = ""
    rights_class: str = ""
    source_class: str = ""
    label_authority: str = ""
    family_id: str = ""
    partition: str = ""
    exact_tree_bound: bool = False
    rights_admitted: bool = False
    privacy_admitted: bool = False
    model_nomination_is_label: bool = False
    lineage: Mapping[str, Any] = MappingProxyType({})
    row: Mapping[str, Any] | None = None

    SCHEMA: ClassVar[str] = PROGRAM_TRACE_ADMISSION_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_TRACE_ADMISSION_INTERFACE
    CID_FIELD: ClassVar[str] = "admission_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "verdict",
            "reason_codes",
            "row_id",
            "tree_cid",
            "source_cid",
            "privacy_class",
            "rights_class",
            "source_class",
            "label_authority",
            "family_id",
            "partition",
            "exact_tree_bound",
            "rights_admitted",
            "privacy_admitted",
            "model_nomination_is_label",
            "lineage",
            "row",
            "admission_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "verdict", _enum(self.verdict, AdmissionVerdict, "verdict")
        )
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))
        object.__setattr__(
            self, "row_id", _optional_text(self.row_id, "row_id", maximum=MAX_LABEL_CHARS)
        )
        object.__setattr__(
            self, "tree_cid", _optional_text(self.tree_cid, "tree_cid")
        )
        if self.tree_cid:
            object.__setattr__(self, "tree_cid", _cid(self.tree_cid, "tree_cid"))
        object.__setattr__(
            self, "source_cid", _optional_text(self.source_cid, "source_cid")
        )
        if self.source_cid:
            object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self, "privacy_class", _optional_text(self.privacy_class, "privacy_class")
        )
        object.__setattr__(
            self, "rights_class", _optional_text(self.rights_class, "rights_class")
        )
        object.__setattr__(
            self, "source_class", _optional_text(self.source_class, "source_class")
        )
        object.__setattr__(
            self,
            "label_authority",
            _optional_text(self.label_authority, "label_authority"),
        )
        object.__setattr__(self, "family_id", _optional_text(self.family_id, "family_id"))
        object.__setattr__(self, "partition", _optional_text(self.partition, "partition"))
        object.__setattr__(
            self, "exact_tree_bound", _bool(self.exact_tree_bound, "exact_tree_bound")
        )
        object.__setattr__(
            self, "rights_admitted", _bool(self.rights_admitted, "rights_admitted")
        )
        object.__setattr__(
            self, "privacy_admitted", _bool(self.privacy_admitted, "privacy_admitted")
        )
        object.__setattr__(
            self,
            "model_nomination_is_label",
            _bool(self.model_nomination_is_label, "model_nomination_is_label"),
        )
        lineage = dict(self.lineage or {})
        _reject_forbidden_content(lineage, "lineage")
        object.__setattr__(self, "lineage", MappingProxyType(lineage))
        if self.row is None:
            object.__setattr__(self, "row", None)
        else:
            row = dict(_as_mapping(self.row, "row"))
            _reject_forbidden_content(row, "row")
            object.__setattr__(self, "row", MappingProxyType(row))
        if self.verdict == AdmissionVerdict.ADMITTED.value:
            if not (
                self.rights_admitted
                and self.privacy_admitted
                and self.exact_tree_bound
                and self.tree_cid
                and not self.model_nomination_is_label
            ):
                raise ProgramTraceCorpusIntegrityError(
                    "admitted rows must be rights/privacy admitted, exact-tree bound, "
                    "and free of model-nomination labels"
                )
            if self.row is None:
                raise ProgramTraceCorpusIntegrityError("admitted rows require a normalized row")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "verdict": self.verdict,
            "reason_codes": list(self.reason_codes),
            "row_id": self.row_id,
            "tree_cid": self.tree_cid,
            "source_cid": self.source_cid,
            "privacy_class": self.privacy_class,
            "rights_class": self.rights_class,
            "source_class": self.source_class,
            "label_authority": self.label_authority,
            "family_id": self.family_id,
            "partition": self.partition,
            "exact_tree_bound": self.exact_tree_bound,
            "rights_admitted": self.rights_admitted,
            "privacy_admitted": self.privacy_admitted,
            "model_nomination_is_label": self.model_nomination_is_label,
            "lineage": dict(self.lineage),
            "row": None if self.row is None else dict(self.row),
        }

    @property
    def admission_cid(self) -> str:
        return corpus_cid_for(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["admission_cid"] = self.admission_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramTraceAdmission":
        payload = _closed(data, cls._FIELDS, "ProgramTraceAdmission")
        claimed = payload.pop("admission_cid", None)
        payload.pop("schema", None)
        record = cls(**payload)
        if claimed:
            decode_and_recompute_structured(claimed, record.identity_payload())
        return record


@dataclass(frozen=True, slots=True)
class ProgramTraceSplitManifest:
    """One disjoint partition of admitted trace rows."""

    partition: TracePartition | str
    row_ids: Sequence[str] = ()
    family_ids: Sequence[str] = ()
    grouping_values: Mapping[str, Sequence[str]] = MappingProxyType({})
    role: SplitRole | str = SplitRole.DEVELOPMENT

    SCHEMA: ClassVar[str] = PROGRAM_TRACE_SPLIT_MANIFEST_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE
    CID_FIELD: ClassVar[str] = "split_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "partition",
            "row_ids",
            "family_ids",
            "grouping_values",
            "role",
            "split_cid",
        }
    )

    def __post_init__(self) -> None:
        partition = _enum(self.partition, TracePartition, "partition")
        object.__setattr__(self, "partition", partition)
        object.__setattr__(self, "row_ids", _unique_texts(self.row_ids, "row_id"))
        object.__setattr__(self, "family_ids", _unique_texts(self.family_ids, "family_id"))
        role = _enum(
            self.role
            or (
                SplitRole.DEVELOPMENT.value
                if partition in DEVELOPMENT_PARTITIONS
                else SplitRole.EVALUATION.value
            ),
            SplitRole,
            "role",
        )
        expected = (
            SplitRole.DEVELOPMENT.value
            if partition in DEVELOPMENT_PARTITIONS
            else SplitRole.EVALUATION.value
        )
        if role != expected:
            raise ProgramTraceCorpusError(
                f"partition {partition} must have role {expected}"
            )
        object.__setattr__(self, "role", role)
        grouping = _as_mapping(self.grouping_values, "grouping_values")
        extra = set(grouping) - set(GROUPING_KEYS)
        if extra:
            raise ProgramTraceCorpusError(
                f"grouping_values rejects unknown fields {sorted(extra)}"
            )
        frozen = {
            key: _unique_texts(grouping.get(key, ()), key) for key in GROUPING_KEYS
        }
        object.__setattr__(self, "grouping_values", MappingProxyType(frozen))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "partition": self.partition,
            "row_ids": list(self.row_ids),
            "family_ids": list(self.family_ids),
            "grouping_values": {
                key: list(values) for key, values in self.grouping_values.items()
            },
            "role": self.role,
        }

    @property
    def split_cid(self) -> str:
        return corpus_cid_for(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["split_cid"] = self.split_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramTraceSplitManifest":
        payload = _closed(data, cls._FIELDS, "ProgramTraceSplitManifest")
        claimed = payload.pop("split_cid", None)
        payload.pop("schema", None)
        record = cls(**payload)
        if claimed:
            decode_and_recompute_structured(claimed, record.identity_payload())
        return record


@dataclass(frozen=True, slots=True)
class ProgramTraceLeakageAudit:
    """Family/grouping partition fence over admitted rows."""

    passed: bool
    row_count: int = 0
    partition_count: int = 0
    leaked_families: Sequence[str] = ()
    leaked_keys: Sequence[str] = ()
    findings: Sequence[str] = ()
    family_partitions: Mapping[str, str] = MappingProxyType({})

    SCHEMA: ClassVar[str] = PROGRAM_TRACE_LEAKAGE_AUDIT_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE
    CID_FIELD: ClassVar[str] = "audit_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "passed",
            "row_count",
            "partition_count",
            "leaked_families",
            "leaked_keys",
            "findings",
            "family_partitions",
            "audit_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "passed", _bool(self.passed, "passed"))
        if type(self.row_count) is not int or isinstance(self.row_count, bool) or self.row_count < 0:
            raise ProgramTraceCorpusError("row_count must be a nonnegative integer")
        if self.row_count > MAX_SAFE_INTEGER:
            raise ProgramTraceCorpusError("row_count exceeds the safe JSON integer range")
        if (
            type(self.partition_count) is not int
            or isinstance(self.partition_count, bool)
            or self.partition_count < 0
        ):
            raise ProgramTraceCorpusError("partition_count must be a nonnegative integer")
        object.__setattr__(
            self, "leaked_families", _unique_texts(self.leaked_families, "leaked_family")
        )
        object.__setattr__(
            self, "leaked_keys", _unique_texts(self.leaked_keys, "leaked_key")
        )
        object.__setattr__(self, "findings", _unique_texts(self.findings, "finding"))
        if len(self.findings) > MAX_FINDINGS:
            raise ProgramTraceCorpusError("findings exceeds its bound")
        partitions = {
            _text(key, "family_id"): _enum(value, TracePartition, "partition")
            for key, value in dict(self.family_partitions).items()
        }
        object.__setattr__(self, "family_partitions", MappingProxyType(partitions))
        if self.passed and (self.leaked_families or self.leaked_keys or self.findings):
            raise ProgramTraceCorpusIntegrityError(
                "a passing leakage audit cannot record leaked families"
            )
        if not self.passed and not (self.leaked_families or self.leaked_keys or self.findings):
            raise ProgramTraceCorpusIntegrityError(
                "a failing leakage audit must record findings"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "passed": self.passed,
            "row_count": self.row_count,
            "partition_count": self.partition_count,
            "leaked_families": list(self.leaked_families),
            "leaked_keys": list(self.leaked_keys),
            "findings": list(self.findings),
            "family_partitions": dict(self.family_partitions),
        }

    @property
    def audit_cid(self) -> str:
        return corpus_cid_for(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["audit_cid"] = self.audit_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramTraceLeakageAudit":
        payload = _closed(data, cls._FIELDS, "ProgramTraceLeakageAudit")
        claimed = payload.pop("audit_cid", None)
        payload.pop("schema", None)
        record = cls(**payload)
        if claimed:
            decode_and_recompute_structured(claimed, record.identity_payload())
        return record


@dataclass(frozen=True, slots=True)
class ProgramTraceCorpusManifest:
    """Admitted execution-trace corpus or typed training_unavailable terminal."""

    availability: CorpusAvailability | str
    rows: Sequence[Mapping[str, Any]] = ()
    splits: Mapping[str, ProgramTraceSplitManifest] = MappingProxyType({})
    leakage_audit: ProgramTraceLeakageAudit | None = None
    admissions: Sequence[ProgramTraceAdmission] = ()
    corpus_id: str = DEFAULT_CORPUS_ID
    task_id: str = DEFAULT_TASK_ID
    language: str = ADMITTED_LANGUAGE
    reason_codes: Sequence[str] = ()
    contracts_unblocked: bool = True
    baselines_unblocked: bool = True

    SCHEMA: ClassVar[str] = PROGRAM_TRACE_CORPUS_MANIFEST_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE
    CID_FIELD: ClassVar[str] = "corpus_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "availability",
            "rows",
            "splits",
            "leakage_audit",
            "admissions",
            "corpus_id",
            "task_id",
            "language",
            "reason_codes",
            "contracts_unblocked",
            "baselines_unblocked",
            "corpus_cid",
        }
    )

    def __post_init__(self) -> None:
        availability = _enum(self.availability, CorpusAvailability, "availability")
        object.__setattr__(self, "availability", availability)
        object.__setattr__(
            self, "corpus_id", _text(self.corpus_id, "corpus_id", maximum=MAX_LABEL_CHARS)
        )
        object.__setattr__(
            self, "task_id", _text(self.task_id, "task_id", maximum=MAX_LABEL_CHARS)
        )
        object.__setattr__(self, "language", _text(self.language, "language"))
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))
        object.__setattr__(
            self,
            "contracts_unblocked",
            _bool(self.contracts_unblocked, "contracts_unblocked"),
        )
        object.__setattr__(
            self,
            "baselines_unblocked",
            _bool(self.baselines_unblocked, "baselines_unblocked"),
        )
        if not self.contracts_unblocked or not self.baselines_unblocked:
            raise ProgramTraceCorpusError(
                "absent or admitted corpora must not block contracts or baselines"
            )
        rows = tuple(
            MappingProxyType(dict(_as_mapping(row, "row"))) for row in self.rows
        )
        if len(rows) > MAX_ROWS:
            raise ProgramTraceCorpusError("rows exceeds its bound")
        object.__setattr__(self, "rows", rows)
        splits_raw = dict(self.splits or {})
        splits: dict[str, ProgramTraceSplitManifest] = {}
        for name in PARTITIONS:
            item = splits_raw.get(name)
            if item is None:
                splits[name] = ProgramTraceSplitManifest(
                    partition=name,
                    role=(
                        SplitRole.DEVELOPMENT
                        if name in DEVELOPMENT_PARTITIONS
                        else SplitRole.EVALUATION
                    ),
                )
                continue
            if isinstance(item, ProgramTraceSplitManifest):
                split = item
            else:
                split = ProgramTraceSplitManifest.from_dict(_as_mapping(item, "split"))
            if split.partition != name:
                raise ProgramTraceCorpusError(
                    f"split key {name!r} does not match partition {split.partition!r}"
                )
            splits[name] = split
        extra = set(splits_raw) - PARTITION_VALUES
        if extra:
            raise ProgramTraceCorpusError(f"splits rejects unknown partitions {sorted(extra)}")
        object.__setattr__(self, "splits", MappingProxyType(splits))
        admissions = tuple(self.admissions)
        for admission in admissions:
            if not isinstance(admission, ProgramTraceAdmission):
                raise ProgramTraceCorpusError("admissions must be ProgramTraceAdmission records")
        object.__setattr__(self, "admissions", admissions)
        audit = self.leakage_audit
        if audit is None:
            audit = ProgramTraceLeakageAudit(
                passed=True,
                row_count=len(rows),
                partition_count=len(PARTITIONS),
            )
        elif not isinstance(audit, ProgramTraceLeakageAudit):
            audit = ProgramTraceLeakageAudit.from_dict(_as_mapping(audit, "leakage_audit"))
        object.__setattr__(self, "leakage_audit", audit)
        if availability == CorpusAvailability.ADMITTED.value:
            if not rows:
                raise ProgramTraceCorpusIntegrityError(
                    "an admitted corpus requires at least one rights-admitted row"
                )
            if not audit.passed:
                raise ProgramTraceCorpusLeakageError(
                    "an admitted corpus cannot leak related families across partitions"
                )
        if availability == CorpusAvailability.TRAINING_UNAVAILABLE.value:
            if rows:
                raise ProgramTraceCorpusIntegrityError(
                    "training_unavailable corpora cannot carry admitted training rows"
                )
            if TRAINING_UNAVAILABLE not in self.reason_codes:
                object.__setattr__(
                    self,
                    "reason_codes",
                    _reason_codes([*self.reason_codes, TRAINING_UNAVAILABLE]),
                )

    @property
    def training_unavailable(self) -> bool:
        return self.availability == CorpusAvailability.TRAINING_UNAVAILABLE.value

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "availability": self.availability,
            "rows": [dict(row) for row in self.rows],
            "splits": {name: split.to_dict() for name, split in self.splits.items()},
            "leakage_audit": None if self.leakage_audit is None else self.leakage_audit.to_dict(),
            "admissions": [item.to_dict() for item in self.admissions],
            "corpus_id": self.corpus_id,
            "task_id": self.task_id,
            "language": self.language,
            "reason_codes": list(self.reason_codes),
            "contracts_unblocked": self.contracts_unblocked,
            "baselines_unblocked": self.baselines_unblocked,
        }

    @property
    def corpus_cid(self) -> str:
        return corpus_cid_for(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["interface"] = self.INTERFACE
        value["evidence"] = [CORPUS_ADMISSION_EVIDENCE, SPLIT_LEAKAGE_EVIDENCE]
        value["corpus_cid"] = self.corpus_cid
        value["training_unavailable"] = self.training_unavailable
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramTraceCorpusManifest":
        allowed = cls._FIELDS | frozenset(
            {"interface", "evidence", "training_unavailable"}
        )
        payload = _closed(data, allowed, "ProgramTraceCorpusManifest")
        claimed = payload.pop("corpus_cid", None)
        payload.pop("schema", None)
        payload.pop("interface", None)
        payload.pop("evidence", None)
        payload.pop("training_unavailable", None)
        splits = payload.get("splits") or {}
        payload["splits"] = {
            name: (
                item
                if isinstance(item, ProgramTraceSplitManifest)
                else ProgramTraceSplitManifest.from_dict(item)
            )
            for name, item in dict(splits).items()
        }
        audit = payload.get("leakage_audit")
        if isinstance(audit, Mapping):
            payload["leakage_audit"] = ProgramTraceLeakageAudit.from_dict(audit)
        admissions = payload.get("admissions") or ()
        payload["admissions"] = tuple(
            item
            if isinstance(item, ProgramTraceAdmission)
            else ProgramTraceAdmission.from_dict(item)
            for item in admissions
        )
        record = cls(**payload)
        if claimed:
            decode_and_recompute_structured(claimed, record.identity_payload())
        return record


def admit_program_trace_row(row: Mapping[str, Any] | None) -> ProgramTraceAdmission:
    """Admit one recipe row or return a typed rejection / training_unavailable."""

    if row is None:
        return ProgramTraceAdmission(
            verdict=AdmissionVerdict.TRAINING_UNAVAILABLE,
            reason_codes=(TRAINING_UNAVAILABLE, "absent_row"),
        )
    data = _as_mapping(row, "row")
    reasons = [*_recipe_field_reasons(data), *_scan_policy_reasons(data)]
    row_id = _optional_text(data.get("row_id"), "row_id", maximum=MAX_LABEL_CHARS)
    nomination_is_label = "model_nomination_label" in reasons
    if reasons:
        rights_admitted = "rights_not_admitted" not in reasons and "forbidden_rights_class" not in reasons and "unknown_rights" not in reasons
        privacy_admitted = "privacy_not_admitted" not in reasons
        exact_tree = "missing_exact_tree_binding" not in reasons
        return ProgramTraceAdmission(
            verdict=AdmissionVerdict.REJECTED,
            reason_codes=reasons,
            row_id=row_id,
            privacy_class=_optional_text(data.get("privacy_class"), "privacy_class"),
            rights_class=_optional_text(data.get("rights_class"), "rights_class"),
            source_class=_optional_text(data.get("source_class"), "source_class"),
            label_authority=_optional_text(
                data.get("label_authority"), "label_authority"
            ),
            family_id=_optional_text(data.get("family_id"), "family_id"),
            partition=_optional_text(data.get("partition"), "partition"),
            exact_tree_bound=exact_tree and bool(data.get("tree_cid") or data.get("tree_id")),
            rights_admitted=rights_admitted and data.get("rights_class") in ADMITTED_RIGHTS_CLASSES,
            privacy_admitted=privacy_admitted and data.get("privacy_class") in ADMITTED_PRIVACY_CLASSES,
            model_nomination_is_label=nomination_is_label,
        )
    try:
        payload = _normalized_row_payload(data)
    except ProgramTraceCorpusError as exc:
        return ProgramTraceAdmission(
            verdict=AdmissionVerdict.REJECTED,
            reason_codes=("normalization_failed",),
            row_id=row_id,
            model_nomination_is_label=nomination_is_label,
            lineage=MappingProxyType({"error": str(exc)[:MAX_LABEL_CHARS]}),
        )
    return ProgramTraceAdmission(
        verdict=AdmissionVerdict.ADMITTED,
        reason_codes=("rights_admitted", "privacy_admitted", "exact_tree_bound"),
        row_id=payload["row_id"],
        tree_cid=payload["tree_cid"],
        source_cid=payload["source_cid"],
        privacy_class=payload["privacy_class"],
        rights_class=payload["rights_class"],
        source_class=payload["source_class"],
        label_authority=payload["label_authority"],
        family_id=payload["family_id"],
        partition=payload["partition"],
        exact_tree_bound=True,
        rights_admitted=True,
        privacy_admitted=True,
        model_nomination_is_label=False,
        lineage=_lineage_for(payload),
        row=payload,
    )


def _row_views(rows: Sequence[Any]) -> list[Mapping[str, Any]]:
    views: list[Mapping[str, Any]] = []
    for item in rows:
        if isinstance(item, ProgramTraceAdmission):
            if item.row is None:
                continue
            views.append(item.row)
            continue
        if isinstance(item, Mapping) and item.get("row") and isinstance(item["row"], Mapping):
            views.append(item["row"])
            continue
        if isinstance(item, Mapping) and "partition" in item and "family_id" in item:
            if item.get("schema") == PROGRAM_TRACE_ROW_SCHEMA:
                views.append(item)
                continue
            admission = admit_program_trace_row(item)
            if admission.verdict != AdmissionVerdict.ADMITTED.value or admission.row is None:
                raise ProgramTraceCorpusError(
                    f"row {item.get('row_id')!r} is not rights/privacy admitted"
                )
            views.append(admission.row)
            continue
        raise ProgramTraceCorpusError("leakage audit requires admitted rows")
    return views


def audit_program_trace_leakage(
    rows: Sequence[Any] | ProgramTraceCorpusManifest | None,
) -> ProgramTraceLeakageAudit:
    """Fail closed when related families occupy more than one partition."""

    if rows is None:
        return ProgramTraceLeakageAudit(passed=True, row_count=0, partition_count=len(PARTITIONS))
    if isinstance(rows, ProgramTraceCorpusManifest):
        material = list(rows.rows)
    else:
        material = list(rows)
    views = _row_views(material)
    findings: list[str] = []
    leaked_families: set[str] = set()
    leaked_keys: set[str] = set()
    family_partitions: dict[str, str] = {}
    key_partitions: dict[tuple[str, str], set[str]] = defaultdict(set)
    seen_ids: set[str] = set()
    partitions_used: set[str] = set()
    intra_repos: set[str] = set()
    cross_repos: set[str] = set()

    for row in views:
        row_id = _text(row.get("row_id"), "row_id", maximum=MAX_LABEL_CHARS)
        if row_id in seen_ids:
            findings.append(f"duplicate_row:{row_id}")
            continue
        seen_ids.add(row_id)
        partition = _enum(row.get("partition"), TracePartition, "partition")
        partitions_used.add(partition)
        family_id = _text(row.get("family_id"), "family_id")
        previous = family_partitions.get(family_id)
        if previous is None:
            family_partitions[family_id] = partition
        elif previous != partition:
            leaked_families.add(family_id)
            leaked_keys.add("family_id")
            findings.append(f"family_leak:{family_id}:{previous}->{partition}")
        repository = _optional_text(row.get("repository"), "repository")
        if partition in INTRA_REPOSITORY_PARTITIONS and repository:
            intra_repos.add(repository)
        if partition == TracePartition.CROSS_REPOSITORY.value and repository:
            cross_repos.add(repository)
        for key in LEAKAGE_GROUPING_KEYS:
            value = _optional_text(row.get(key), key)
            if not value:
                continue
            key_partitions[(key, value)].add(partition)

    for (key, value), parts in sorted(key_partitions.items()):
        if len(parts) > 1:
            leaked_keys.add(key)
            if key == "family_id":
                leaked_families.add(value)
            findings.append(
                f"grouping_leak:{key}:{value}:{','.join(sorted(parts))}"
            )

    overlap = intra_repos & cross_repos
    if overlap:
        leaked_keys.add("repository")
        findings.append(
            "cross_repository_leak:" + ",".join(sorted(overlap))
        )

    findings = list(dict.fromkeys(findings))
    passed = not findings
    return ProgramTraceLeakageAudit(
        passed=passed,
        row_count=len(views),
        partition_count=len(PARTITIONS),
        leaked_families=tuple(sorted(leaked_families)),
        leaked_keys=tuple(sorted(leaked_keys)),
        findings=tuple(findings),
        family_partitions=family_partitions,
    )


def _empty_splits() -> dict[str, ProgramTraceSplitManifest]:
    return {
        name: ProgramTraceSplitManifest(
            partition=name,
            role=(
                SplitRole.DEVELOPMENT
                if name in DEVELOPMENT_PARTITIONS
                else SplitRole.EVALUATION
            ),
        )
        for name in PARTITIONS
    }


def _splits_for(rows: Sequence[Mapping[str, Any]]) -> dict[str, ProgramTraceSplitManifest]:
    grouped: dict[str, list[Mapping[str, Any]]] = {name: [] for name in PARTITIONS}
    for row in rows:
        grouped[str(row["partition"])].append(row)
    splits: dict[str, ProgramTraceSplitManifest] = {}
    for name, members in grouped.items():
        grouping_values = {
            key: tuple(
                sorted({str(row[key]) for row in members if str(row.get(key) or "")})
            )
            for key in GROUPING_KEYS
        }
        splits[name] = ProgramTraceSplitManifest(
            partition=name,
            row_ids=tuple(row["row_id"] for row in members),
            family_ids=tuple(
                dict.fromkeys(row["family_id"] for row in members)
            ),
            grouping_values=grouping_values,
            role=(
                SplitRole.DEVELOPMENT
                if name in DEVELOPMENT_PARTITIONS
                else SplitRole.EVALUATION
            ),
        )
    return splits


def _unavailable_manifest(*, reason_codes: Sequence[str]) -> ProgramTraceCorpusManifest:
    return ProgramTraceCorpusManifest(
        availability=CorpusAvailability.TRAINING_UNAVAILABLE,
        rows=(),
        splits=_empty_splits(),
        leakage_audit=ProgramTraceLeakageAudit(
            passed=True,
            row_count=0,
            partition_count=len(PARTITIONS),
        ),
        admissions=(),
        reason_codes=tuple(reason_codes),
        contracts_unblocked=True,
        baselines_unblocked=True,
    )


def _load_fixture_mapping(source: Path) -> Mapping[str, Any] | None:
    if not source.is_file():
        return None
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProgramTraceCorpusError(f"corpus fixture is malformed: {source}") from exc
    if not isinstance(payload, Mapping):
        raise ProgramTraceCorpusError("corpus fixture must be a mapping")
    return payload


def load_program_trace_corpus_fixture(
    source: Path | str | None = None,
) -> Mapping[str, Any] | None:
    """Load the compact recipe fixture, or None when the corpus is absent."""

    path = default_program_trace_corpus_path() if source is None else Path(source)
    return _load_fixture_mapping(path)


def _rows_from_source(
    source: Mapping[str, Any] | Sequence[Mapping[str, Any]] | Path | str | None,
) -> tuple[list[Mapping[str, Any]], list[str], bool]:
    if source is None:
        payload = load_program_trace_corpus_fixture()
        if payload is None:
            return [], [TRAINING_UNAVAILABLE, "absent_corpus"], True
        source = payload
    if isinstance(source, (str, Path)):
        payload = load_program_trace_corpus_fixture(source)
        if payload is None:
            return [], [TRAINING_UNAVAILABLE, "absent_corpus"], True
        source = payload
    if isinstance(source, Mapping):
        if source.get("availability") == TRAINING_UNAVAILABLE and not source.get("rows"):
            return [], [TRAINING_UNAVAILABLE, "declared_unavailable"], True
        if "row_id" in source and "partition" in source and "rows" not in source:
            return [source], [], False
        rows = source.get("rows", source.get("cases"))
        if rows is None:
            return [], [TRAINING_UNAVAILABLE, "absent_rows"], True
        if isinstance(rows, Mapping):
            raise ProgramTraceCorpusError("rows must be a sequence")
        return list(rows), [], False
    if isinstance(source, Sequence) and not isinstance(source, (str, bytes, bytearray)):
        return list(source), [], False
    raise ProgramTraceCorpusError("corpus source is not a mapping, sequence, or path")


def build_program_trace_corpus(
    source: Mapping[str, Any] | Sequence[Mapping[str, Any]] | Path | str | None = None,
) -> ProgramTraceCorpusManifest:
    """Materialize an admitted corpus, or return training_unavailable.

    Contracts and deterministic baselines remain unblocked in every case.
    Related-family leakage among otherwise-admitted rows fails closed.
    """

    recipes, unavailable_reasons, unavailable = _rows_from_source(source)
    if unavailable:
        return _unavailable_manifest(reason_codes=unavailable_reasons)
    if not recipes:
        return _unavailable_manifest(reason_codes=(TRAINING_UNAVAILABLE, "empty_corpus"))

    admissions: list[ProgramTraceAdmission] = []
    admitted_rows: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for recipe in recipes:
        admission = admit_program_trace_row(_as_mapping(recipe, "row"))
        if admission.verdict != AdmissionVerdict.ADMITTED.value or admission.row is None:
            codes = ",".join(admission.reason_codes) or "rejected"
            raise ProgramTraceCorpusIntegrityError(
                f"row {admission.row_id or '<unknown>'} is not corpus-admitted ({codes})"
            )
        if admission.row_id in seen:
            raise ProgramTraceCorpusIntegrityError(
                f"duplicate row_id {admission.row_id!r}"
            )
        seen.add(admission.row_id)
        admissions.append(admission)
        admitted_rows.append(dict(admission.row))

    if not admitted_rows:
        return _unavailable_manifest(reason_codes=(TRAINING_UNAVAILABLE, "no_admitted_rows"))

    audit = audit_program_trace_leakage(admitted_rows)
    if not audit.passed:
        detail = "; ".join(audit.findings[:8]) or "related family leakage"
        raise ProgramTraceCorpusLeakageError(
            f"related families cannot leak across partitions ({detail})"
        )

    return ProgramTraceCorpusManifest(
        availability=CorpusAvailability.ADMITTED,
        rows=admitted_rows,
        splits=_splits_for(admitted_rows),
        leakage_audit=audit,
        admissions=tuple(admissions),
        reason_codes=("corpus_admitted",),
        contracts_unblocked=True,
        baselines_unblocked=True,
    )


__all__ = [
    "ADMITTED_LANGUAGE",
    "ADMITTED_PRIVACY_CLASSES",
    "ADMITTED_RIGHTS_CLASSES",
    "ADMITTED_SOURCE_CLASSES",
    "AdmissionVerdict",
    "CORPUS_ADMITTED",
    "CORPUS_ADMISSION_EVIDENCE",
    "CorpusAvailability",
    "DEVELOPMENT_PARTITIONS",
    "EVALUATION_PARTITIONS",
    "EXECUTION_TRACE_CORPUS_INTERFACE",
    "EXECUTION_TRACE_CORPUS_SCHEMA",
    "ForbiddenRightsClass",
    "GROUPING_KEYS",
    "IMPORT_DATABASE_PERFORMED",
    "IMPORT_INSTALLER_PERFORMED",
    "IMPORT_MODEL_LOAD_PERFORMED",
    "IMPORT_NETWORK_PERFORMED",
    "IMPORT_REPO_SCAN_PERFORMED",
    "IMPORT_SIDE_EFFECTS_PERFORMED",
    "IMPORT_SOCKET_PERFORMED",
    "IMPORT_SUBPROCESS_PERFORMED",
    "IMPORT_WATCHER_PERFORMED",
    "LABEL_AUTHORITIES",
    "LEAKAGE_GROUPING_KEYS",
    "LabelAuthority",
    "PARTITIONS",
    "PROGRAM_TRACE_ADMISSION_INTERFACE",
    "PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE",
    "PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE",
    "PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE",
    "ProgramTraceAdmission",
    "ProgramTraceCorpusError",
    "ProgramTraceCorpusIntegrityError",
    "ProgramTraceCorpusLeakageError",
    "ProgramTraceCorpusManifest",
    "ProgramTraceLeakageAudit",
    "ProgramTraceSplitManifest",
    "QUERY_FAMILIES",
    "QueryFamily",
    "SPLIT_LEAKAGE_EVIDENCE",
    "SplitRole",
    "TRAINING_UNAVAILABLE",
    "TracePartition",
    "TracePrivacyClass",
    "TraceRightsClass",
    "TraceSourceClass",
    "admit_program_trace_row",
    "audit_program_trace_leakage",
    "build_program_trace_corpus",
    "corpus_cid_for",
    "default_program_trace_corpus_path",
    "load_program_trace_corpus_fixture",
]
