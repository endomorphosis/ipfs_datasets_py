"""Rights-admitted execution-trace corpus (SAWM-023).

Datasets owns corpus admission, split, lineage, and leakage semantics.
This leaf does not promote accelerator checkpoints, decide kit storage, or
publish raw private trace bodies.  Importing it never opens a network,
socket, installer, subprocess, database, watcher, model, or repository scan.

An absent or too-small corpus returns ``training_unavailable`` without
blocking contracts or deterministic baselines.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
    validate_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    FORBIDDEN_FIELD_MARKERS,
    SECRET_FIELD_MARKERS,
    PrivacyClass,
)


PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE: Final[str] = "ProgramTraceCorpusManifest@1"
PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE: Final[str] = "ProgramTraceSplitManifest@1"
PROGRAM_TRACE_ADMISSION_INTERFACE: Final[str] = "ProgramTraceAdmission@1"
PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE: Final[str] = "ProgramTraceLeakageAudit@1"

PROGRAM_TRACE_CORPUS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-trace-corpus@1"
)
PROGRAM_TRACE_SPLIT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-trace-split@1"
)
PROGRAM_TRACE_ADMISSION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-trace-admission@1"
)
PROGRAM_TRACE_LEAKAGE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-trace-leakage-audit@1"
)
PROGRAM_TRACE_ROW_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-trace-row@1"
)
PROGRAM_TRACE_PUBLIC_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.program-trace-public-identity@1"
)

ADMITTED_LANGUAGE: Final[str] = "python"
MAX_TEXT_CHARS: Final[int] = 1024
MIN_PROMOTION_ROWS: Final[int] = 64
NONE_GROUP: Final[str] = "none"
DEFAULT_FIXTURE_RELPATH: Final[str] = "tests/fixtures/program_world_trace_corpus.json"
TRAINING_UNAVAILABLE: Final[str] = "training_unavailable"

IMPORT_NETWORK_PERFORMED: Final[bool] = False
IMPORT_SOCKET_PERFORMED: Final[bool] = False
IMPORT_INSTALLER_PERFORMED: Final[bool] = False
IMPORT_SUBPROCESS_PERFORMED: Final[bool] = False
IMPORT_DATABASE_PERFORMED: Final[bool] = False
IMPORT_REPO_SCAN_PERFORMED: Final[bool] = False
IMPORT_WATCHER_PERFORMED: Final[bool] = False
IMPORT_MODEL_LOAD_PERFORMED: Final[bool] = False
IMPORT_SIDE_EFFECTS_PERFORMED: Final[bool] = False

PARTITIONS: Final[tuple[str, ...]] = (
    "training",
    "development",
    "held_out",
    "adversarial",
    "cross_repository",
    "ood",
)
ORIGINS: Final[frozenset[str]] = frozenset(
    {"hermetic", "synthetic", "adversarial", "observed"}
)
GROUP_KINDS: Final[tuple[str, ...]] = (
    "repository",
    "commit",
    "task",
    "function",
    "failure",
    "mutant",
    "proof",
    "procedure",
)
LEAKAGE_GROUP_KINDS: Final[tuple[str, ...]] = (
    "function",
    "failure",
    "mutant",
    "proof",
    "procedure",
)
ADMITTED_RIGHTS: Final[frozenset[str]] = frozenset(
    {"first-party-admitted", "synthetic-admitted", "public-rights-cleared"}
)
ADMITTED_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "first-party-hermetic",
        "synthetic-generator",
        "adversarial-mutant",
        "observed-admitted",
    }
)
ADMITTED_LABEL_KINDS: Final[frozenset[str]] = frozenset(
    {
        "observed_event_sequence",
        "observed_exception",
        "synthetic_event_sequence",
        "adversarial_mutant_sequence",
    }
)
ADMITTED_PRIVACY: Final[frozenset[str]] = frozenset(
    {PrivacyClass.PUBLIC.value, PrivacyClass.INTERNAL.value}
)
EXCLUDED_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "secret",
        "hidden-test",
        "private-reasoning",
        "unadmitted-source",
        "unadmitted-production",
        "unknown-rights",
        "tenant-private",
        "private-witness",
        "chain-of-thought",
    }
)
MODEL_NOMINATION_LABELS: Final[frozenset[str]] = frozenset(
    {
        "model_nomination",
        "predicted_label",
        "predicted_next_call",
        "embedding_label",
        "retrieval_nomination",
    }
)
_EXCLUSION_FRAGMENTS: Final[tuple[str, ...]] = (
    "chain_of_thought",
    "chain-of-thought",
    "hidden_test",
    "hidden-test",
    "private_reasoning",
    "private-reasoning",
    "raw_bodies",
    "raw_trace",
)


class ProgramTraceCorpusError(ValueError):
    """Raised when a program-trace corpus payload is malformed."""


class ProgramTracePartition(str, Enum):
    TRAINING = "training"
    DEVELOPMENT = "development"
    HELD_OUT = "held_out"
    ADVERSARIAL = "adversarial"
    CROSS_REPOSITORY = "cross_repository"
    OOD = "ood"


class ProgramTraceOrigin(str, Enum):
    HERMETIC = "hermetic"
    SYNTHETIC = "synthetic"
    ADVERSARIAL = "adversarial"
    OBSERVED = "observed"


def _nfc(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise ProgramTraceCorpusError(f"{label} must be a nonempty string")
    text = unicodedata.normalize("NFC", value)
    if text != text.strip() or len(text) > MAX_TEXT_CHARS:
        raise ProgramTraceCorpusError(f"{label} must be trimmed NFC text")
    return text


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ProgramTraceCorpusError(f"{label} must be a boolean")
    return value


def _optional_cid(value: object, label: str) -> str | None:
    if value is None or value == "":
        return None
    try:
        return validate_cid(value)
    except Exception as error:
        raise ProgramTraceCorpusError(f"{label} must be a valid CID") from error


def _cid_or_bind(value: object, identity: str, label: str) -> str:
    if value in (None, ""):
        return cid_for_bytes(identity.encode("utf-8"))
    found = _optional_cid(value, label)
    if found is None:
        return cid_for_bytes(identity.encode("utf-8"))
    return found


def _kinds(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if type(value) is str:
        return (_nfc(value, label),)
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        raise ProgramTraceCorpusError(f"{label} must be a string sequence")
    items = [_nfc(item, f"{label} item") for item in value]
    return tuple(items)


def _groups(value: object) -> dict[str, str]:
    raw = {} if value is None else dict(value)
    if not isinstance(raw, Mapping):
        raise ProgramTraceCorpusError("groups must be a string mapping")
    out: dict[str, str] = {}
    for kind in GROUP_KINDS:
        item = raw.get(kind, NONE_GROUP)
        out[kind] = _nfc(item if item not in (None, "") else NONE_GROUP, f"groups.{kind}")
    extra = set(raw) - set(GROUP_KINDS)
    if extra:
        raise ProgramTraceCorpusError(f"groups has unsupported keys: {sorted(extra)}")
    return out


def _partition(value: object) -> str:
    text = _nfc(value, "partition").replace("-", "_").lower()
    if text == "ood":
        return ProgramTracePartition.OOD.value
    try:
        return ProgramTracePartition(text).value
    except ValueError as error:
        raise ProgramTraceCorpusError("partition is not one of the six disjoint splits") from error


def _origin(value: object) -> str:
    text = _nfc(value, "origin")
    if text not in ORIGINS:
        raise ProgramTraceCorpusError("origin must be hermetic, synthetic, adversarial, or observed")
    return text


def _walk_keys(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is str:
                found.append(key)
            found.extend(_walk_keys(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            found.extend(_walk_keys(item))
    return found


def _secret_or_forbidden(keys: Iterable[str]) -> tuple[str, ...]:
    hits: list[str] = []
    for key in keys:
        lowered = key.lower()
        if key in SECRET_FIELD_MARKERS or lowered in SECRET_FIELD_MARKERS:
            hits.append(key)
            continue
        if key in FORBIDDEN_FIELD_MARKERS or lowered in FORBIDDEN_FIELD_MARKERS:
            hits.append(key)
            continue
        if any(marker in lowered for marker in SECRET_FIELD_MARKERS):
            hits.append(key)
    return tuple(sorted(set(hits)))


def _exclusion_hit(text: str) -> str | None:
    lowered = text.lower()
    for fragment in _EXCLUSION_FRAGMENTS:
        if fragment in lowered:
            return fragment
    if lowered in EXCLUDED_SOURCE_KINDS:
        return lowered
    if lowered in MODEL_NOMINATION_LABELS:
        return lowered
    return None


def default_fixture_path() -> Path:
    return Path(__file__).resolve().parents[3] / DEFAULT_FIXTURE_RELPATH


def load_program_trace_fixture(path: Path | str | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_fixture_path()
    if not target.is_file():
        return {
            "schema": PROGRAM_TRACE_CORPUS_SCHEMA,
            "language": ADMITTED_LANGUAGE,
            "tree_identity": "absent",
            "rows": [],
            "exclusions": [],
            "absent": True,
        }
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ProgramTraceCorpusError("fixture must be a JSON object")
    return dict(payload)


def _row_from_trace_object(row: object, overrides: Mapping[str, Any]) -> dict[str, Any]:
    public_trace = getattr(row, "public_trace", None)
    events = tuple(getattr(row, "events", ()))
    payload = {
        "row_id": overrides.get("row_id"),
        "origin": overrides.get("origin", "hermetic"),
        "partition": overrides.get("partition"),
        "groups": overrides.get("groups"),
        "rights": overrides.get("rights", "first-party-admitted"),
        "privacy_class": str(
            getattr(public_trace, "privacy_class", overrides.get("privacy_class", "public"))
        ),
        "source_kind": overrides.get("source_kind", "first-party-hermetic"),
        "event_kinds": [
            str(getattr(event, "event_kind", event)) for event in events
        ],
        "label_kind": overrides.get("label_kind", "observed_event_sequence"),
        "language": str(getattr(public_trace, "language", ADMITTED_LANGUAGE)),
        "tree_cid": getattr(row, "tree_cid", None),
        "source_cid": getattr(row, "source_cid", None),
        "public_trace_cid": getattr(public_trace, "execution_trace_cid", None),
        "includes_raw_bodies": bool(getattr(public_trace, "includes_raw_bodies", False)),
        "negative": False,
    }
    for key, item in overrides.items():
        if item is not None:
            payload[key] = item
    return payload


def _as_mapping(row: object, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    extra = dict(overrides or {})
    if isinstance(row, Mapping):
        payload = dict(row)
        payload.update({key: item for key, item in extra.items() if item is not None})
        return payload
    if hasattr(row, "public_trace") and hasattr(row, "tree_cid"):
        return _row_from_trace_object(row, extra)
    raise ProgramTraceCorpusError("row must be a mapping or a public hermetic trace record")


@dataclass(frozen=True, slots=True)
class ProgramTraceAdmission:
    """Typed rights/privacy/lineage decision for one candidate row."""

    admitted: bool
    reason: str
    row_id: str
    rights_status: str
    privacy_status: str
    lineage_status: str
    tree_cid: str | None = None
    public_trace_cid: str | None = None
    training_unavailable: bool = False
    excluded: tuple[str, ...] = ()

    SCHEMA: ClassVar[str] = PROGRAM_TRACE_ADMISSION_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_TRACE_ADMISSION_INTERFACE

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "admitted": self.admitted,
            "excluded": list(self.excluded),
            "lineage_status": self.lineage_status,
            "privacy_status": self.privacy_status,
            "public_trace_cid": self.public_trace_cid,
            "reason": self.reason,
            "rights_status": self.rights_status,
            "row_id": self.row_id,
            "training_unavailable": self.training_unavailable,
            "tree_cid": self.tree_cid,
        }

    @property
    def program_trace_admission_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["program_trace_admission_cid"] = self.program_trace_admission_cid
        return payload


@dataclass(frozen=True, slots=True)
class ProgramTraceRow:
    """Exact-tree bound public corpus row.  Never carries raw private bodies."""

    row_id: str
    origin: str
    partition: str
    groups: Mapping[str, str]
    rights: str
    privacy_class: str
    source_kind: str
    event_kinds: tuple[str, ...]
    label_kind: str
    tree_cid: str
    source_cid: str
    public_trace_cid: str
    language: str = ADMITTED_LANGUAGE
    includes_raw_bodies: bool = False
    checkpoint_lineage_cid: str | None = None

    SCHEMA: ClassVar[str] = PROGRAM_TRACE_ROW_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "groups", MappingProxyType(dict(self.groups)))
        object.__setattr__(self, "event_kinds", tuple(self.event_kinds))
        if self.includes_raw_bodies:
            raise ProgramTraceCorpusError("raw private trace bodies never enter corpus rows")
        if self.language != ADMITTED_LANGUAGE:
            raise ProgramTraceCorpusError("initial corpus admits Python only")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "checkpoint_lineage_cid": self.checkpoint_lineage_cid,
            "event_kinds": list(self.event_kinds),
            "groups": dict(self.groups),
            "includes_raw_bodies": False,
            "label_kind": self.label_kind,
            "language": self.language,
            "origin": self.origin,
            "partition": self.partition,
            "privacy_class": self.privacy_class,
            "public_trace_cid": self.public_trace_cid,
            "rights": self.rights,
            "row_id": self.row_id,
            "source_cid": self.source_cid,
            "source_kind": self.source_kind,
            "tree_cid": self.tree_cid,
        }

    @property
    def row_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["row_cid"] = self.row_cid
        return payload


@dataclass(frozen=True, slots=True)
class ProgramTraceSplitManifest:
    """One of the six disjoint partition manifests."""

    partition: str
    row_cids: tuple[str, ...]
    row_ids: tuple[str, ...]

    SCHEMA: ClassVar[str] = PROGRAM_TRACE_SPLIT_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "partition": self.partition,
            "row_cids": list(self.row_cids),
            "row_ids": list(self.row_ids),
        }

    @property
    def split_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["split_cid"] = self.split_cid
        return payload


@dataclass(frozen=True, slots=True)
class ProgramTraceLeakageAudit:
    """Deterministic grouping/leakage receipt over admitted rows."""

    passed: bool
    violations: tuple[str, ...]
    families_checked: tuple[str, ...]
    partition_counts: Mapping[str, int]
    secret_exclusions: tuple[str, ...]
    hidden_test_exclusions: tuple[str, ...]
    private_reasoning_exclusions: tuple[str, ...]
    unadmitted_source_exclusions: tuple[str, ...]

    SCHEMA: ClassVar[str] = PROGRAM_TRACE_LEAKAGE_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "families_checked": list(self.families_checked),
            "hidden_test_exclusions": list(self.hidden_test_exclusions),
            "partition_counts": dict(self.partition_counts),
            "passed": self.passed,
            "private_reasoning_exclusions": list(self.private_reasoning_exclusions),
            "secret_exclusions": list(self.secret_exclusions),
            "unadmitted_source_exclusions": list(self.unadmitted_source_exclusions),
            "violations": list(self.violations),
        }

    @property
    def leakage_audit_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["leakage_audit_cid"] = self.leakage_audit_cid
        return payload


@dataclass(frozen=True, slots=True)
class ProgramTraceCorpusManifest:
    """Admitted first-party corpus with six disjoint splits."""

    language: str
    tree_cid: str
    rows: tuple[ProgramTraceRow, ...]
    splits: tuple[ProgramTraceSplitManifest, ...]
    leakage_audit: ProgramTraceLeakageAudit
    excluded: tuple[ProgramTraceAdmission, ...]
    training_unavailable: bool
    learned_path_status: str
    contracts_unblocked: bool
    baselines_unblocked: bool
    checkpoint_lineage_present: bool
    absent_source: bool = False

    SCHEMA: ClassVar[str] = PROGRAM_TRACE_CORPUS_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "absent_source": self.absent_source,
            "baselines_unblocked": self.baselines_unblocked,
            "checkpoint_lineage_present": self.checkpoint_lineage_present,
            "contracts_unblocked": self.contracts_unblocked,
            "language": self.language,
            "learned_path_status": self.learned_path_status,
            "leakage_audit_cid": self.leakage_audit.leakage_audit_cid,
            "row_cids": [row.row_cid for row in self.rows],
            "split_cids": [item.split_cid for item in self.splits],
            "training_unavailable": self.training_unavailable,
            "tree_cid": self.tree_cid,
        }

    @property
    def corpus_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["corpus_cid"] = self.corpus_cid
        payload["excluded"] = [item.to_dict() for item in self.excluded]
        payload["leakage_audit"] = self.leakage_audit.to_dict()
        payload["rows"] = [row.to_dict() for row in self.rows]
        payload["splits"] = [item.to_dict() for item in self.splits]
        return payload

    def split(self, partition: str) -> ProgramTraceSplitManifest:
        wanted = _partition(partition)
        for item in self.splits:
            if item.partition == wanted:
                return item
        raise ProgramTraceCorpusError(f"missing split manifest for {wanted}")


def _reject(
    row_id: str,
    reason: str,
    *,
    rights_status: str = "rejected",
    privacy_status: str = "rejected",
    lineage_status: str = "rejected",
    excluded: tuple[str, ...] = (),
    tree_cid: str | None = None,
    public_trace_cid: str | None = None,
) -> ProgramTraceAdmission:
    return ProgramTraceAdmission(
        admitted=False,
        reason=reason,
        row_id=row_id or "unknown",
        rights_status=rights_status,
        privacy_status=privacy_status,
        lineage_status=lineage_status,
        tree_cid=tree_cid,
        public_trace_cid=public_trace_cid,
        training_unavailable=False,
        excluded=excluded,
    )


def admit_program_trace_row(
    row: Mapping[str, Any] | object,
    *,
    row_id: str | None = None,
    partition: str | None = None,
    groups: Mapping[str, str] | None = None,
    origin: str | None = None,
    rights: str | None = None,
    source_kind: str | None = None,
    label_kind: str | None = None,
    tree_identity: str = "sawm-023-program-world-trace-corpus-v1",
) -> ProgramTraceAdmission:
    """Admit one public trace row or return a typed exclusion."""

    payload = _as_mapping(
        row,
        {
            "row_id": row_id,
            "partition": partition,
            "groups": groups,
            "origin": origin,
            "rights": rights,
            "source_kind": source_kind,
            "label_kind": label_kind,
        },
    )
    row_id = str(payload.get("row_id") or "")
    secret_hits = _secret_or_forbidden(_walk_keys(payload))
    if secret_hits:
        return _reject(row_id, "secret_or_forbidden_field", excluded=("secret_field",))
    for item in payload.values():
        if type(item) is str:
            hit = _exclusion_hit(item)
            if hit is not None and item in EXCLUDED_SOURCE_KINDS.union(MODEL_NOMINATION_LABELS):
                return _reject(row_id, "excluded_payload_marker", excluded=(hit,))
    try:
        row_id = _nfc(payload.get("row_id"), "row_id")
        origin_value = _origin(payload.get("origin"))
        partition_value = _partition(payload.get("partition"))
        group_map = _groups(payload.get("groups"))
        rights_value = _nfc(payload.get("rights"), "rights")
        privacy = _nfc(payload.get("privacy_class", PrivacyClass.PUBLIC.value), "privacy_class")
        source = _nfc(payload.get("source_kind"), "source_kind")
        label = _nfc(payload.get("label_kind"), "label_kind")
        language = _nfc(payload.get("language", ADMITTED_LANGUAGE), "language")
        includes_raw = _bool(payload.get("includes_raw_bodies", False), "includes_raw_bodies")
        event_kinds = _kinds(payload.get("event_kinds"), "event_kinds")
    except ProgramTraceCorpusError as error:
        return _reject(row_id, str(error), excluded=("malformed",))
    if includes_raw:
        return _reject(row_id, "raw_private_trace_body", privacy_status="private")
    if language != ADMITTED_LANGUAGE:
        return _reject(row_id, "unsupported_language", excluded=(language,))
    if source in EXCLUDED_SOURCE_KINDS or _exclusion_hit(source):
        return _reject(
            row_id,
            "unadmitted_or_excluded_source",
            lineage_status="excluded",
            excluded=(source,),
        )
    if rights_value not in ADMITTED_RIGHTS:
        return _reject(row_id, "rights_not_admitted", rights_status="unadmitted")
    if privacy not in ADMITTED_PRIVACY:
        return _reject(row_id, "privacy_not_admitted", privacy_status=privacy)
    if source not in ADMITTED_SOURCE_KINDS:
        return _reject(row_id, "source_kind_not_admitted", lineage_status=source)
    if label in MODEL_NOMINATION_LABELS:
        return _reject(row_id, "model_nomination_is_not_a_label", excluded=(label,))
    if label not in ADMITTED_LABEL_KINDS:
        return _reject(row_id, "label_kind_not_observed", excluded=(label,))
    if not event_kinds:
        return _reject(row_id, "event_kinds_required")
    if _bool(payload.get("negative", False), "negative"):
        return _reject(row_id, "negative_example_excluded")
    tree_cid = _cid_or_bind(
        payload.get("tree_cid"),
        f"{tree_identity}:{group_map['repository']}:{group_map['commit']}",
        "tree_cid",
    )
    source_cid = _cid_or_bind(
        payload.get("source_cid"),
        f"source:{source}:{group_map['function']}:{row_id}",
        "source_cid",
    )
    public_trace_cid = payload.get("public_trace_cid")
    if public_trace_cid in (None, ""):
        public_trace_cid = cid_for_structured(
            {
                "schema": PROGRAM_TRACE_PUBLIC_IDENTITY_SCHEMA,
                "event_kinds": list(event_kinds),
                "row_id": row_id,
                "source_cid": source_cid,
                "tree_cid": tree_cid,
            }
        )
    else:
        public_trace_cid = _optional_cid(public_trace_cid, "public_trace_cid")
    row_obj = ProgramTraceRow(
        row_id=row_id,
        origin=origin_value,
        partition=partition_value,
        groups=group_map,
        rights=rights_value,
        privacy_class=privacy,
        source_kind=source,
        event_kinds=event_kinds,
        label_kind=label,
        tree_cid=tree_cid,
        source_cid=source_cid,
        public_trace_cid=str(public_trace_cid),
        language=language,
        includes_raw_bodies=False,
        checkpoint_lineage_cid=_optional_cid(
            payload.get("checkpoint_lineage_cid"), "checkpoint_lineage_cid"
        ),
    )
    return ProgramTraceAdmission(
        admitted=True,
        reason="admitted",
        row_id=row_id,
        rights_status=rights_value,
        privacy_status=privacy,
        lineage_status=source,
        tree_cid=row_obj.tree_cid,
        public_trace_cid=row_obj.public_trace_cid,
        excluded=(),
    )


def _materialize_row(
    payload: Mapping[str, Any],
    *,
    tree_identity: str,
) -> tuple[ProgramTraceAdmission, ProgramTraceRow | None]:
    admission = admit_program_trace_row(payload, tree_identity=tree_identity)
    if not admission.admitted:
        return admission, None
    group_map = _groups(payload.get("groups"))
    event_kinds = _kinds(payload.get("event_kinds"), "event_kinds")
    tree_cid = admission.tree_cid or _cid_or_bind(
        payload.get("tree_cid"),
        f"{tree_identity}:{group_map['repository']}:{group_map['commit']}",
        "tree_cid",
    )
    source_cid = _cid_or_bind(
        payload.get("source_cid"),
        f"source:{payload.get('source_kind')}:{group_map['function']}:{admission.row_id}",
        "source_cid",
    )
    public_trace_cid = admission.public_trace_cid or cid_for_structured(
        {
            "schema": PROGRAM_TRACE_PUBLIC_IDENTITY_SCHEMA,
            "event_kinds": list(event_kinds),
            "row_id": admission.row_id,
            "source_cid": source_cid,
            "tree_cid": tree_cid,
        }
    )
    row = ProgramTraceRow(
        row_id=admission.row_id,
        origin=_origin(payload.get("origin")),
        partition=_partition(payload.get("partition")),
        groups=group_map,
        rights=_nfc(payload.get("rights"), "rights"),
        privacy_class=_nfc(payload.get("privacy_class", "public"), "privacy_class"),
        source_kind=_nfc(payload.get("source_kind"), "source_kind"),
        event_kinds=event_kinds,
        label_kind=_nfc(payload.get("label_kind"), "label_kind"),
        tree_cid=tree_cid,
        source_cid=source_cid,
        public_trace_cid=public_trace_cid,
        checkpoint_lineage_cid=_optional_cid(
            payload.get("checkpoint_lineage_cid"), "checkpoint_lineage_cid"
        ),
    )
    return admission, row


def audit_program_trace_leakage(
    rows: Sequence[ProgramTraceRow | Mapping[str, Any]],
    *,
    excluded: Sequence[ProgramTraceAdmission] = (),
) -> ProgramTraceLeakageAudit:
    """Fail closed if related families leak across the six partitions."""

    materialized: list[ProgramTraceRow] = []
    for item in rows:
        if isinstance(item, ProgramTraceRow):
            materialized.append(item)
            continue
        admission, row = _materialize_row(item, tree_identity="leakage-audit")
        if row is None:
            raise ProgramTraceCorpusError(f"leakage audit cannot include rejected row {admission.row_id}")
        materialized.append(row)
    violations: list[str] = []
    counts = {name: 0 for name in PARTITIONS}
    seen_ids: dict[str, str] = {}
    seen_traces: dict[str, str] = {}
    families: dict[tuple[str, str], str] = {}
    training_repos: set[str] = set()
    for row in materialized:
        counts[row.partition] = counts.get(row.partition, 0) + 1
        if row.row_id in seen_ids and seen_ids[row.row_id] != row.partition:
            violations.append(f"row_id:{row.row_id}")
        seen_ids[row.row_id] = row.partition
        if row.public_trace_cid in seen_traces and seen_traces[row.public_trace_cid] != row.partition:
            violations.append(f"public_trace_cid:{row.row_id}")
        seen_traces[row.public_trace_cid] = row.partition
        if row.partition == ProgramTracePartition.TRAINING.value:
            training_repos.add(row.groups["repository"])
        for kind in LEAKAGE_GROUP_KINDS:
            value = row.groups[kind]
            if value == NONE_GROUP:
                continue
            key = (kind, value)
            prior = families.get(key)
            if prior is None:
                families[key] = row.partition
            elif prior != row.partition:
                violations.append(f"{kind}:{value}")
    for row in materialized:
        if (
            row.partition == ProgramTracePartition.CROSS_REPOSITORY.value
            and row.groups["repository"] in training_repos
        ):
            violations.append(f"repository:{row.groups['repository']}")
    def _haystack(item: ProgramTraceAdmission) -> str:
        return " ".join(
            (item.reason, item.row_id, item.rights_status, item.lineage_status, *item.excluded)
        ).lower()

    secrets = tuple(
        item.row_id
        for item in excluded
        if "secret" in _haystack(item) or "password" in _haystack(item) or "forbidden" in _haystack(item)
    )
    hidden = tuple(item.row_id for item in excluded if "hidden" in _haystack(item))
    private = tuple(
        item.row_id for item in excluded if "private" in _haystack(item) or "reasoning" in _haystack(item)
    )
    unadmitted = tuple(
        item.row_id
        for item in excluded
        if "unadmitted" in _haystack(item)
        or "rights" in _haystack(item)
        or "unknown" in _haystack(item)
    )
    unique = tuple(sorted(set(violations)))
    return ProgramTraceLeakageAudit(
        passed=not unique,
        violations=unique,
        families_checked=LEAKAGE_GROUP_KINDS,
        partition_counts=MappingProxyType(counts),
        secret_exclusions=secrets,
        hidden_test_exclusions=hidden,
        private_reasoning_exclusions=private,
        unadmitted_source_exclusions=unadmitted,
    )


def _splits_for(rows: Sequence[ProgramTraceRow]) -> tuple[ProgramTraceSplitManifest, ...]:
    grouped: dict[str, list[ProgramTraceRow]] = {name: [] for name in PARTITIONS}
    for row in rows:
        grouped[row.partition].append(row)
    manifests: list[ProgramTraceSplitManifest] = []
    for name in PARTITIONS:
        items = sorted(grouped[name], key=lambda row: row.row_id)
        manifests.append(
            ProgramTraceSplitManifest(
                partition=name,
                row_cids=tuple(row.row_cid for row in items),
                row_ids=tuple(row.row_id for row in items),
            )
        )
    return tuple(manifests)


def build_program_trace_corpus(
    source: Path | str | Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    *,
    require_leakage_pass: bool = True,
) -> ProgramTraceCorpusManifest:
    """Materialize the admitted corpus, or return training_unavailable."""

    absent = False
    tree_identity = "sawm-023-program-world-trace-corpus-v1"
    rows_in: list[Mapping[str, Any]] = []
    exclusions_in: list[Mapping[str, Any]] = []
    if source is None or isinstance(source, (str, Path)):
        fixture = load_program_trace_fixture(source if source is not None else None)
        absent = bool(fixture.get("absent"))
        tree_identity = str(fixture.get("tree_identity") or tree_identity)
        rows_in = list(fixture.get("rows") or [])
        exclusions_in = list(fixture.get("exclusions") or [])
    elif isinstance(source, Mapping) and "rows" in source:
        tree_identity = str(source.get("tree_identity") or tree_identity)
        rows_in = list(source.get("rows") or [])
        exclusions_in = list(source.get("exclusions") or [])
        absent = bool(source.get("absent"))
    elif isinstance(source, Sequence) and not isinstance(source, (str, bytes, bytearray)):
        rows_in = list(source)
    else:
        raise ProgramTraceCorpusError("unsupported corpus source")

    admitted_rows: list[ProgramTraceRow] = []
    excluded: list[ProgramTraceAdmission] = []
    for payload in rows_in:
        admission, row = _materialize_row(payload, tree_identity=tree_identity)
        if row is None:
            excluded.append(admission)
            continue
        admitted_rows.append(row)
    for payload in exclusions_in:
        admission = admit_program_trace_row(payload, tree_identity=tree_identity)
        if admission.admitted:
            raise ProgramTraceCorpusError(
                f"exclusion {admission.row_id} must not be admitted"
            )
        excluded.append(admission)

    ordered = tuple(sorted(admitted_rows, key=lambda row: row.row_id))
    audit = audit_program_trace_leakage(ordered, excluded=excluded)
    if require_leakage_pass and ordered and not audit.passed:
        raise ProgramTraceCorpusError(
            "related families cannot leak across partitions: " + ",".join(audit.violations)
        )
    checkpoint = any(row.checkpoint_lineage_cid for row in ordered)
    training_count = sum(
        1 for row in ordered if row.partition == ProgramTracePartition.TRAINING.value
    )
    too_small = training_count < MIN_PROMOTION_ROWS
    unavailable = absent or not ordered or too_small or not checkpoint
    tree_cid = cid_for_bytes(tree_identity.encode("utf-8"))
    if ordered:
        tree_cid = ordered[0].tree_cid
    return ProgramTraceCorpusManifest(
        language=ADMITTED_LANGUAGE,
        tree_cid=tree_cid,
        rows=ordered,
        splits=_splits_for(ordered),
        leakage_audit=audit,
        excluded=tuple(excluded),
        training_unavailable=unavailable,
        learned_path_status=TRAINING_UNAVAILABLE if unavailable else "admitted",
        contracts_unblocked=True,
        baselines_unblocked=True,
        checkpoint_lineage_present=checkpoint,
        absent_source=absent,
    )


__all__ = [
    "ADMITTED_LANGUAGE",
    "IMPORT_DATABASE_PERFORMED",
    "IMPORT_INSTALLER_PERFORMED",
    "IMPORT_MODEL_LOAD_PERFORMED",
    "IMPORT_NETWORK_PERFORMED",
    "IMPORT_REPO_SCAN_PERFORMED",
    "IMPORT_SIDE_EFFECTS_PERFORMED",
    "IMPORT_SOCKET_PERFORMED",
    "IMPORT_SUBPROCESS_PERFORMED",
    "IMPORT_WATCHER_PERFORMED",
    "MIN_PROMOTION_ROWS",
    "PARTITIONS",
    "PROGRAM_TRACE_ADMISSION_INTERFACE",
    "PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE",
    "PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE",
    "PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE",
    "TRAINING_UNAVAILABLE",
    "ProgramTraceAdmission",
    "ProgramTraceCorpusError",
    "ProgramTraceCorpusManifest",
    "ProgramTraceLeakageAudit",
    "ProgramTraceOrigin",
    "ProgramTracePartition",
    "ProgramTraceRow",
    "ProgramTraceSplitManifest",
    "admit_program_trace_row",
    "audit_program_trace_leakage",
    "build_program_trace_corpus",
    "default_fixture_path",
    "load_program_trace_fixture",
]
