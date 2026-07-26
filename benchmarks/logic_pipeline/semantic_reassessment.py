"""Independent semantic validation for fresh unsealed reassessment matrices.

This module is intentionally downstream of execution.  It never invokes an
adapter, model, solver, or kernel.  It first validates already-materialized
case results, then loads the reviewed pilot/development prefix through the
unsealed corpus boundary and compares structured front-end payloads with the
reviewed semantic targets.  Ground-truth labels therefore enter only this
post-execution validator.

Every coordinate produces a content-addressed receipt, including unavailable
coordinates.  The receipt index and measured front-end report are write-once
run artifacts.  The published reassessment namespace and the sealed holdout
are never valid inputs or output targets.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Final, Mapping, Sequence
import unicodedata

from . import DEFAULT_BENCHMARK_ROOT
from .capabilities import CapabilityKind, CapabilityStatus
from .capability_reprobe import (
    CapabilityFreezeError,
    LiveCapabilityReprobe,
    validate_frozen_capability_reprobe,
)
from .cases import (
    DEFAULT_CORPUS_PATH,
    DEFAULT_MANIFEST_PATH,
    FROZEN_CORPUS_MANIFEST_SHA256,
    FROZEN_SPLIT_SHA256,
    SPLIT_MANIFEST_SCHEMA,
    BenchmarkCase,
    CorpusContractError,
    Split,
    case_sha256,
    load_unsealed_pilot_development,
    normalized_source_sha256,
)
from .cache_measurement import extract_symai_cache_setup_telemetry
from .contracts import (
    DEFAULT_PROTOCOL_SHA256,
    SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2,
    SEMANTIC_CALIBRATION_CASES_PER_PRODUCER_V2,
    SEMANTIC_CALIBRATION_CASE_COUNT_V2,
    SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2,
    SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID,
    SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID,
    SEMANTIC_FAILURE_CODES_V2,
    SEMANTIC_FAILURE_SCHEMA_V2,
    SEMANTIC_FORBIDDEN_PRODUCER_INPUT_FIELDS_V2,
    SEMANTIC_PRODUCER_IDS_V2,
    SEMANTIC_PRODUCER_REGISTRY_V2_CID,
    SEMANTIC_PROJECTION_CLASSES_V2,
    SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2,
    SEMANTIC_PROTOCOL_V2_CID,
    SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID,
    SEMANTIC_WILSON_CONFIDENCE_MILLIONTHS_V2,
    SEMANTIC_WILSON_LOWER_BOUND_MIN_MILLIONTHS_V2,
    CaseResultRecord,
    OutcomeStatus,
    ProtocolContractError,
    SemanticProjection,
    StageName,
    StageRecord,
    StageStatus,
    canonical_json,
    normalize_semantic_term,
    semantic_calibration_route_manifest_v2,
)
from .content_addressing import cid_for_bytes, cid_for_dag_json, validate_cid
from .frontend_report import (
    CACHE_MODES,
    EXPECTED_CLASSES,
    FRONTEND_VARIANT_IDS,
    SPLITS,
    FrontendReportError,
    build_frontend_report,
    load_frontend_report,
)
from .matrix_reassessment import (
    MATRIX_INDEX_SCHEMA,
    MatrixReassessmentError,
    validate_reassessment_matrix,
)
from .metrics import MetricsContractError, validate_kernel_bound_result
from .reassessment_namespace import (
    ReassessmentNamespaceError,
    ReassessmentRunLayout,
    reject_published_write_targets,
    require_fresh_reassessment_run,
)
from .variants import VARIANT_REGISTRY, VARIANT_REGISTRY_SHA256


SEMANTIC_VALIDATOR_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-validator-receipt.v1"
)
SEMANTIC_RECEIPT_INDEX_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-validator-index.v1"
)
SEMANTIC_VALIDATOR_RECEIPT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-validator-receipt.v2"
)
SEMANTIC_CALIBRATION_REPORT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-calibration-report.v2"
)
SEMANTIC_CALIBRATION_COORDINATE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-calibration-coordinate.v2"
)
SEMANTIC_TARGET_MANIFEST_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-target-manifest.v2"
)
EXPECTED_SEMANTIC_COORDINATE_COUNT: Final = 240
_COMPILER_EVIDENCE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.compiler-output.v1"
)
_SPACY_EVIDENCE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.spacy-evidence.v1"
)
_SYMAI_EVIDENCE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.symai-evidence.v1"
)
_SYMAI_POLICY_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.policy-decision.v1"
)
_COMPILER_EVIDENCE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.compiler-output.v2"
)
_COMPILER_CID_ONLY_MODAL_IR_FIELDS_V2: Final = frozenset(
    {
        "document_id",
        "normalized_text_cid",
        "formulas_cid",
        "source",
        "version",
        "projection",
    }
)
_SPACY_EVIDENCE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.spacy-evidence.v2"
)
_SYMAI_EVIDENCE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.symai-evidence.v2"
)
_SEMANTIC_FIELDS_V2: Final = (
    "logic_family",
    "target",
    "class",
    "predicates",
    "entities",
)
_SEMANTIC_VACUOUS_TERMS_V2: Final = frozenset(
    {"", "none", "null", "unknown", "unspecified"}
)
_SEMANTIC_WILSON_Z_95_V2: Final = 1.959963984540054
_SEMANTIC_LOGIC_ALIASES_V2: Final[Mapping[str, str]] = {
    "first_order": "fol",
    "first_order_logic": "fol",
    "fol": "fol",
    "deontic": "deontic",
    "deontic_logic": "deontic",
    "temporal": "temporal",
    "temporal_logic": "temporal",
}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
# The measured report embeds all 240 bounded CaseResult values.  The protocol
# permits up to 512 KiB per result, so retain a finite aggregate ceiling that
# does not reject a contract-valid complete report.
_MAX_ARTIFACT_BYTES: Final = 128 * 1024 * 1024
_LOGIC_ALIASES: Final[Mapping[str, str]] = {
    "fol": "fol",
    "first_order": "fol",
    "first_order_logic": "fol",
    "deontic": "deontic",
    "modal_deontic": "deontic",
    "temporal": "temporal",
    "temporal_logic": "temporal",
    "epistemic": "epistemic",
    "epistemic_logic": "epistemic",
    "lean": "lean4",
    "lean4": "lean4",
}
_LOGIC_KEYS: Final = frozenset(
    {"logic", "logic_type", "logic_family", "formalism", "kind"}
)
_TARGET_KEYS: Final = frozenset(
    {"target", "semantic_target", "conclusion", "result"}
)
_PREDICATE_KEYS: Final = frozenset(
    {
        "predicate",
        "predicates",
        "normalized_predicate",
        "normalized_predicates",
        "relation",
        "relations",
        "action",
        "actions",
    }
)
_ENTITY_KEYS: Final = frozenset(
    {
        "entity",
        "entities",
        "actor",
        "actors",
        "subject",
        "subjects",
        "object",
        "objects",
    }
)
_CLASS_KEYS: Final = frozenset(
    {"predicted_class", "classification", "semantic_class", "class"}
)
_FRONTEND_STAGES: Final = (
    StageName.COMPILER,
    StageName.SPACY,
    StageName.SYMAI,
)


class SemanticReassessmentError(ValueError):
    """Raised when semantic evidence is incomplete, unbound, or mutable."""


class _SemanticSchemaIncompatible(SemanticReassessmentError):
    """Internal typed missingness for a valid but unscoreable producer shape."""


@dataclass(frozen=True, slots=True)
class SemanticReassessmentEvidence:
    """In-memory receipt set and measured report before immutable persistence."""

    receipts: tuple[Mapping[str, object], ...]
    observations: tuple[Mapping[str, object], ...]
    report: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class SemanticCalibrationTargetV2:
    """One injected reviewed target at the post-execution trust boundary.

    The target deliberately has the same five semantic fields as
    :class:`SemanticProjection`.  It does not contain a proof obligation,
    kernel result, negative-control label, or producer input.  Callers may
    construct these values from an already-authorized unsealed loader, but
    this module never opens a corpus while evaluating revision 2.
    """

    case_id: str
    source_text: str
    logic_family: str
    target: str
    semantic_class: str
    predicates: tuple[str, ...]
    entities: tuple[str, ...]

    def __post_init__(self) -> None:
        _safe_id(self.case_id, "semantic target case_id")
        if (
            not isinstance(self.source_text, str)
            or not self.source_text.strip()
            or len(self.source_text.encode("utf-8")) > 8 * 1024
        ):
            raise SemanticReassessmentError(
                "semantic target source_text must be nonempty and bounded"
            )
        logic = _normalize_logic_v2(self.logic_family)
        target = normalize_semantic_term(self.target)
        semantic_class = normalize_semantic_term(self.semantic_class)
        if not logic or not target:
            raise SemanticReassessmentError(
                "semantic target logic_family and target must be normalized"
            )
        if semantic_class not in SEMANTIC_PROJECTION_CLASSES_V2:
            raise SemanticReassessmentError(
                "semantic target class is unsupported"
            )
        object.__setattr__(self, "logic_family", logic)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "semantic_class", semantic_class)
        for field in ("predicates", "entities"):
            values = getattr(self, field)
            if not isinstance(values, tuple):
                raise SemanticReassessmentError(
                    f"semantic target {field} must be a tuple"
                )
            normalized = tuple(
                sorted(
                    {
                        term
                        for value in values
                        if (term := normalize_semantic_term(value))
                    }
                )
            )
            if len(normalized) > 24:
                raise SemanticReassessmentError(
                    f"semantic target {field} exceeds the bounded field size"
                )
            object.__setattr__(self, field, normalized)

    @property
    def source_cid(self) -> str:
        return cid_for_bytes(self.source_text.encode("utf-8"))

    def semantic_fields(self) -> dict[str, object]:
        return {
            "logic_family": self.logic_family,
            "target": self.target,
            "class": self.semantic_class,
            "predicates": list(self.predicates),
            "entities": list(self.entities),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "source_text": self.source_text,
            **self.semantic_fields(),
        }

    @classmethod
    def from_dict(cls, value: object) -> "SemanticCalibrationTargetV2":
        data = _mapping(value, "semantic calibration target")
        _exact(
            data,
            {
                "case_id",
                "source_text",
                "logic_family",
                "target",
                "class",
                "predicates",
                "entities",
            },
            "semantic calibration target",
        )
        predicates = data["predicates"]
        entities = data["entities"]
        string_fields = (
            "case_id",
            "source_text",
            "logic_family",
            "target",
            "class",
        )
        if any(not isinstance(data[field], str) for field in string_fields):
            raise SemanticReassessmentError(
                "semantic calibration target scalar fields must be strings"
            )
        if (
            not isinstance(predicates, list)
            or not isinstance(entities, list)
            or any(not isinstance(item, str) for item in predicates)
            or any(not isinstance(item, str) for item in entities)
        ):
            raise SemanticReassessmentError(
                "semantic calibration target terms must be arrays"
            )
        return cls(
            case_id=data["case_id"],
            source_text=data["source_text"],
            logic_family=data["logic_family"],
            target=data["target"],
            semantic_class=data["class"],
            predicates=tuple(predicates),
            entities=tuple(entities),
        )

    @classmethod
    def from_benchmark_case(
        cls, case: BenchmarkCase
    ) -> "SemanticCalibrationTargetV2":
        """Project one already-loaded unsealed case into the v2 score shape."""

        if not isinstance(case, BenchmarkCase):
            raise SemanticReassessmentError(
                "semantic target requires a BenchmarkCase"
            )
        expected_ir = _mapping(case.expected_ir, "case.expected_ir")
        logic = expected_ir.get("logic")
        target = expected_ir.get("target")
        if not isinstance(logic, str) or not isinstance(target, str):
            raise SemanticReassessmentError(
                "reviewed expected_ir lacks logic or target"
            )
        return cls(
            case_id=case.case_id,
            source_text=case.source_text,
            logic_family=logic,
            target=target,
            semantic_class=case.expected_class.value,
            predicates=tuple(case.required_predicates),
            entities=tuple(case.required_entities),
        )


@dataclass(frozen=True, slots=True)
class SemanticCalibrationGraphBindingV2:
    """Source binding minted only after strict semantic-ablation validation."""

    plan_cid: str
    plan_sha256: str
    case_result_cid: str
    case_result_sha256: str
    run_id: str
    variant_id: str
    split: str
    cache_mode: str
    environment_sha256: str
    case_manifest_sha256: str
    producer_registry_cid: str
    calibration_route_manifest_cid: str
    calibration_metric_spec_cid: str
    reviewed_target_source_cid: str
    reviewed_target_manifest_cid: str
    proof_stages_suppressed: bool

    def __post_init__(self) -> None:
        _v2_cid(
            self.plan_cid,
            "semantic graph binding plan_cid",
            codecs=("dag-json",),
        )
        _v2_cid(
            self.case_result_cid,
            "semantic graph binding case_result_cid",
            codecs=("dag-json",),
        )
        # These SHA-256 values are retained only as compatibility joins to
        # immutable revision-1 envelopes.  New graph identities above are
        # CIDs computed from the canonical DAG-JSON values, never from a hex
        # digest string.
        for field in (
            "plan_sha256",
            "case_result_sha256",
            "environment_sha256",
            "case_manifest_sha256",
        ):
            _digest(getattr(self, field), f"semantic graph binding {field}")
        _safe_id(self.run_id, "semantic graph binding run_id")
        _safe_id(self.variant_id, "semantic graph binding variant_id")
        if self.split not in {"pilot", "development"}:
            raise SemanticReassessmentError(
                "semantic graph binding must be unsealed"
            )
        if self.cache_mode not in {"cold", "warm"}:
            raise SemanticReassessmentError(
                "semantic graph binding cache mode is invalid"
            )
        if (
            _v2_cid(
                self.producer_registry_cid,
                "semantic graph binding producer_registry_cid",
                codecs=("dag-json",),
            )
            != SEMANTIC_PRODUCER_REGISTRY_V2_CID
        ):
            raise SemanticReassessmentError(
                "semantic graph binding producer registry drifted"
            )
        for field, expected in (
            (
                "calibration_route_manifest_cid",
                SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID,
            ),
            (
                "calibration_metric_spec_cid",
                SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID,
            ),
            (
                "reviewed_target_source_cid",
                SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID,
            ),
        ):
            if (
                _v2_cid(
                    getattr(self, field),
                    f"semantic graph binding {field}",
                    codecs=("dag-json",),
                )
                != expected
            ):
                raise SemanticReassessmentError(
                    f"semantic graph binding {field} drifted"
                )
        _v2_cid(
            self.reviewed_target_manifest_cid,
            "semantic graph binding reviewed_target_manifest_cid",
            codecs=("dag-json",),
        )
        if self.proof_stages_suppressed is not True:
            raise SemanticReassessmentError(
                "semantic graph binding did not suppress proof stages"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class SemanticCalibrationCoordinateV2:
    """A dedicated source-only producer calibration coordinate."""

    case_id: str
    producer_id: str
    stages: tuple[StageRecord, ...]
    graph_binding: SemanticCalibrationGraphBindingV2 | None = None

    def __post_init__(self) -> None:
        _safe_id(self.case_id, "semantic coordinate case_id")
        if self.producer_id not in SEMANTIC_PRODUCER_IDS_V2:
            raise SemanticReassessmentError(
                "semantic coordinate producer is not registered"
            )
        if (
            not isinstance(self.stages, tuple)
            or not self.stages
            or not all(isinstance(stage, StageRecord) for stage in self.stages)
        ):
            raise SemanticReassessmentError(
                "semantic coordinate stages must be a nonempty StageRecord tuple"
            )
        frontends = [
            stage.stage
            for stage in self.stages
            if stage.stage in _FRONTEND_STAGES
        ]
        if not frontends:
            raise SemanticReassessmentError(
                "semantic coordinate contains no front-end stage"
            )
        if len(frontends) != len(set(frontends)):
            raise SemanticReassessmentError(
                "semantic coordinate contains duplicate front-end stages"
            )
        order = {stage: index for index, stage in enumerate(_FRONTEND_STAGES)}
        if frontends != sorted(frontends, key=order.__getitem__):
            raise SemanticReassessmentError(
                "semantic coordinate front-end stages are out of order"
            )
        if self.graph_binding is not None:
            if not isinstance(
                self.graph_binding,
                SemanticCalibrationGraphBindingV2,
            ):
                raise SemanticReassessmentError(
                    "semantic coordinate graph binding is invalid"
                )
            binding = self.graph_binding
            if any(
                (
                    stage.run_id != binding.run_id
                    or stage.case_id != self.case_id
                    or stage.variant_id != binding.variant_id
                    or stage.split.value != binding.split
                    or stage.cache_mode.value != binding.cache_mode
                    or stage.case_manifest_sha256
                    != binding.case_manifest_sha256
                    or stage.provenance.environment_sha256
                    != binding.environment_sha256
                )
                for stage in self.stages
            ):
                raise SemanticReassessmentError(
                    "semantic coordinate stages differ from their validated "
                    "ablation graph binding"
                )

    @classmethod
    def from_dict(cls, value: object) -> "SemanticCalibrationCoordinateV2":
        data = _mapping(value, "semantic calibration coordinate")
        _exact(
            data,
            {"case_id", "producer_id", "stages", "graph_binding"},
            "semantic calibration coordinate",
        )
        stages = data["stages"]
        if not isinstance(stages, list):
            raise SemanticReassessmentError(
                "semantic calibration coordinate stages must be an array"
            )
        try:
            parsed = tuple(
                stage
                if isinstance(stage, StageRecord)
                else StageRecord.from_dict(stage)
                for stage in stages
            )
        except (ProtocolContractError, TypeError, ValueError) as exc:
            raise SemanticReassessmentError(
                "semantic calibration coordinate stage is invalid"
            ) from exc
        if (
            not isinstance(data["case_id"], str)
            or not isinstance(data["producer_id"], str)
        ):
            raise SemanticReassessmentError(
                "semantic calibration coordinate ids must be strings"
            )
        return cls(
            case_id=data["case_id"],
            producer_id=data["producer_id"],
            stages=parsed,
            graph_binding=(
                None
                if data["graph_binding"] is None
                else SemanticCalibrationGraphBindingV2(
                    **_mapping(
                        data["graph_binding"],
                        "semantic calibration coordinate graph_binding",
                    )
                )
            ),
        )


def _plain(value: object) -> object:
    """Thaw contract-owned immutable containers into canonical JSON data."""

    if isinstance(value, Enum):
        return _plain(value.value)
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_plain(item) for item in value]
    return value


def _sha(value: object) -> str:
    return hashlib.sha256(
        canonical_json(_plain(value)).encode("utf-8")
    ).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise SemanticReassessmentError(f"{field} must be an object")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise SemanticReassessmentError(f"{field} must be an array")
    return value


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    if set(value) != expected:
        raise SemanticReassessmentError(
            f"{field} fields changed; missing={sorted(expected - set(value))}, "
            f"unknown={sorted(set(value) - expected)}"
        )


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise SemanticReassessmentError(
            f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _safe_id(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not _SAFE_ID.fullmatch(value)
        or value in {".", ".."}
    ):
        raise SemanticReassessmentError(f"{field} must be a safe identifier")
    return value


def _strict_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SemanticReassessmentError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> object:
    raise SemanticReassessmentError(
        f"non-finite JSON number is forbidden: {token}"
    )


def _read_canonical(path: Path, field: str) -> tuple[object, bytes]:
    try:
        file_stat = path.lstat()
        if (
            stat.S_ISLNK(file_stat.st_mode)
            or not stat.S_ISREG(file_stat.st_mode)
        ):
            raise SemanticReassessmentError(
                f"{field} must be a regular non-symlink file"
            )
        if not 0 < file_stat.st_size <= _MAX_ARTIFACT_BYTES:
            raise SemanticReassessmentError(
                f"{field} size is outside the safe bound"
            )
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except SemanticReassessmentError:
        raise
    except (OSError, UnicodeError) as exc:
        raise SemanticReassessmentError(f"cannot read {field}: {path}") from exc
    if not text.endswith("\n"):
        raise SemanticReassessmentError(
            f"{field} is not canonical newline JSON"
        )
    try:
        value = json.loads(
            text,
            object_pairs_hook=_strict_pairs,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise SemanticReassessmentError(f"{field} is not strict JSON") from exc
    if canonical_json(value) + "\n" != text:
        raise SemanticReassessmentError(f"{field} is not canonical JSON")
    return value, raw


def _write_once(path: Path, value: object) -> bytes:
    raw = (canonical_json(value) + "\n").encode("utf-8")
    if not 0 < len(raw) <= _MAX_ARTIFACT_BYTES:
        raise SemanticReassessmentError(
            f"semantic artifact size is outside the safe bound: {path}"
        )
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise SemanticReassessmentError(
            f"refusing to overwrite immutable semantic evidence: {path}"
        ) from exc
    return raw


def _rooted(repository: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repository / path


def _relative_reference(value: object, field: str) -> PurePosixPath:
    """Parse one canonical, host-independent artifact reference."""

    if not isinstance(value, str) or not value or "\\" in value:
        raise SemanticReassessmentError(
            f"{field} must be a canonical relative POSIX path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise SemanticReassessmentError(
            f"{field} must be a canonical relative POSIX path"
        )
    return path


def _assert_no_symlink_chain(root: Path, target: Path, field: str) -> None:
    """Reject redirection at the run root or any selected descendant."""

    logical_root = root.absolute()
    logical_target = target.absolute()
    for ancestor in reversed((logical_root, *logical_root.parents)):
        if ancestor.is_symlink():
            raise SemanticReassessmentError(
                f"{field} reference root must not use a symlink"
            )
    try:
        relative = logical_target.relative_to(logical_root)
    except ValueError as exc:
        raise SemanticReassessmentError(
            f"{field} escaped its run namespace"
        ) from exc
    current = logical_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise SemanticReassessmentError(f"{field} must not use a symlink")


def _relative(path: Path, index_path: Path) -> str:
    run_root = index_path.parent.parent
    _assert_no_symlink_chain(run_root, path, "semantic artifact")
    try:
        reference = path.resolve(strict=False).relative_to(
            run_root.resolve(strict=False)
        ).as_posix()
    except ValueError as exc:
        raise SemanticReassessmentError(
            f"semantic artifact is outside its run namespace: {path}"
        ) from exc
    _relative_reference(reference, "semantic artifact")
    return reference


def _normalize_term(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "_".join(
        "".join(
            character if character.isalnum() else " "
            for character in normalized
        ).split()
    )


def _normalize_logic_v2(value: object) -> str:
    normalized = normalize_semantic_term(value)
    return _SEMANTIC_LOGIC_ALIASES_V2.get(normalized, normalized)


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        normalized = _normalize_term(value)
        return () if not normalized else (normalized,)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(
            normalized
            for item in value
            if (normalized := _normalize_term(item))
        )
    return ()


def _named_values(
    value: object,
    keys: frozenset[str],
    *,
    depth: int = 0,
) -> tuple[str, ...]:
    if depth > 8:
        raise SemanticReassessmentError(
            "semantic candidate exceeds maximum traversal depth"
        )
    result: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = _normalize_term(raw_key)
            if key in keys:
                result.extend(_strings(item))
            if isinstance(item, (Mapping, list, tuple)):
                result.extend(_named_values(item, keys, depth=depth + 1))
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for item in value:
            if isinstance(item, (Mapping, list, tuple)):
                result.extend(_named_values(item, keys, depth=depth + 1))
    return tuple(result)


def _token_terms(tokens: object) -> frozenset[str]:
    if not isinstance(tokens, Sequence) or isinstance(
        tokens, (str, bytes, bytearray)
    ):
        return frozenset()
    primary: list[str] = []
    terms: set[str] = set()
    for raw in tokens:
        if not isinstance(raw, Mapping):
            continue
        values = [
            _normalize_term(raw.get(name))
            for name in ("lower", "text", "lemma")
        ]
        values = [value for value in values if value]
        if not values:
            continue
        primary.append(values[0])
        terms.update(values)
    for width in (2, 3):
        terms.update(
            "_".join(primary[offset : offset + width])
            for offset in range(len(primary) - width + 1)
        )
    return frozenset(terms)


def _logic_values(values: Sequence[str]) -> frozenset[str]:
    return frozenset(
        normalized
        for value in values
        if (normalized := _LOGIC_ALIASES.get(_normalize_term(value)))
    )


def _structured_projection(
    stage: StageRecord,
    payload: Mapping[str, object],
) -> dict[str, object]:
    predicates: set[str] = set()
    entities: set[str] = set()
    logics: set[str] = set()
    targets: set[str] = set()
    classes: set[str] = set()
    ambiguity_flags: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()

    if stage.stage is StageName.SYMAI:
        if payload.get("schema") != _SYMAI_EVIDENCE_SCHEMA:
            raise SemanticReassessmentError(
                "successful SyMAI semantic payload used an unsupported schema"
            )
        candidate = _mapping(
            payload.get("candidate_ir"), "symai.candidate_ir"
        )
        candidate_digest = _sha(candidate)
        if payload.get("candidate_ir_sha256") != candidate_digest:
            raise SemanticReassessmentError(
                "SyMAI candidate digest is missing or mismatched"
            )
        predicates.update(
            _strings(payload.get("normalized_predicates"))
        )
        entities.update(_strings(payload.get("entities")))
        ambiguity_flags = _strings(payload.get("ambiguity_flags"))
        validation_errors = _strings(payload.get("validation_errors"))
        predicates.update(_named_values(candidate, _PREDICATE_KEYS))
        entities.update(_named_values(candidate, _ENTITY_KEYS))
        logics.update(_logic_values(_named_values(candidate, _LOGIC_KEYS)))
        targets.update(_named_values(candidate, _TARGET_KEYS))
        classes.update(_named_values(candidate, _CLASS_KEYS))
    elif stage.stage is StageName.SPACY:
        if payload.get("schema") != _SPACY_EVIDENCE_SCHEMA:
            raise SemanticReassessmentError(
                "successful spaCy semantic payload used an unsupported schema"
            )
        modal_ir = _mapping(payload.get("modal_ir"), "spacy.modal_ir")
        token_terms = _token_terms(payload.get("tokens"))
        predicates.update(token_terms)
        entities.update(token_terms)
        predicates.update(_named_values(modal_ir, _PREDICATE_KEYS))
        entities.update(_named_values(modal_ir, _ENTITY_KEYS))
        logics.update(_logic_values(_named_values(modal_ir, _LOGIC_KEYS)))
        targets.update(_named_values(modal_ir, _TARGET_KEYS))
        for raw in payload.get("semantic_roles", ()):
            if isinstance(raw, Mapping):
                predicates.update(_strings(raw.get("predicate")))
        for raw in payload.get("entities", ()):
            if isinstance(raw, Mapping):
                entities.update(_strings(raw.get("text")))
        for raw in payload.get("modal_cues", ()):
            if isinstance(raw, Mapping):
                logics.update(
                    _logic_values(
                        tuple(
                            value
                            for name in ("family", "system", "label")
                            for value in _strings(raw.get(name))
                        )
                    )
                )
        classes.update(_named_values(modal_ir, _CLASS_KEYS))
    elif stage.stage is StageName.COMPILER:
        if payload.get("schema") != _COMPILER_EVIDENCE_SCHEMA:
            raise SemanticReassessmentError(
                "successful compiler semantic payload used an unsupported schema"
            )
        modal_ir = _mapping(payload.get("modal_ir"), "compiler.modal_ir")
        # This digest deliberately binds the compiler's complete modal IR;
        # ``modal_ir`` is only its bounded durable projection.
        _digest(payload.get("modal_ir_sha256"), "compiler.modal_ir_sha256")
        predicates.update(_named_values(modal_ir, _PREDICATE_KEYS))
        entities.update(_named_values(modal_ir, _ENTITY_KEYS))
        logics.update(_logic_values(_named_values(modal_ir, _LOGIC_KEYS)))
        targets.update(_named_values(modal_ir, _TARGET_KEYS))
        classes.update(_named_values(modal_ir, _CLASS_KEYS))
    else:  # pragma: no cover - guarded by callers
        raise SemanticReassessmentError("non-front-end semantic source selected")

    return {
        "observed_logics": sorted(logics),
        "observed_targets": sorted(targets),
        "observed_predicates": sorted(predicates),
        "observed_entities": sorted(entities),
        "explicit_classes": sorted(
            value for value in classes if value in EXPECTED_CLASSES
        ),
        "ambiguity_flags": sorted(set(ambiguity_flags)),
        "validation_errors": sorted(set(validation_errors)),
    }


def validate_normalized_semantic_stage_contract(
    stage: StageRecord,
) -> dict[str, object]:
    """Return a scoreable normalized projection or fail closed.

    A successful front-end payload is not automatically calibrated to the
    semantic scorer.  In particular, a producer-specific IR can be
    well-formed while exposing neither of the normalized observations needed
    for a source-bound comparison.  Minting a quality receipt in that state
    would turn a contract mismatch into a false measurement.

    This boundary is deliberately label-blind: it accepts only the already
    materialized stage record and never receives a benchmark case, expected
    class, expected IR, proof obligation, or negative-control label.  It
    requires explicit normalized logic and target observations from the
    selected, graph-invoked producer.  Missing observations make the
    coordinate unscorable and abort semantic reassessment rather than
    assigning zero quality.
    """

    if not isinstance(stage, StageRecord):
        raise SemanticReassessmentError(
            "semantic contract calibration requires a StageRecord"
        )
    if stage.stage not in _FRONTEND_STAGES:
        raise SemanticReassessmentError(
            "semantic contract calibration requires a front-end stage"
        )
    if stage.status is not StageStatus.SUCCESS:
        raise SemanticReassessmentError(
            "semantic contract calibration requires a successful stage"
        )
    if not _stage_invoked(stage):
        raise SemanticReassessmentError(
            "semantic contract calibration requires a graph-invoked stage"
        )
    payload = _mapping(
        stage.data,
        f"{stage.stage.value} semantic payload",
    )
    projection = _structured_projection(stage, payload)
    missing = [
        field
        for field in ("observed_logics", "observed_targets")
        if not projection[field]
    ]
    if missing:
        raise SemanticReassessmentError(
            "semantic producer/scorer contract is uncalibrated for "
            f"{stage.stage.value}: selected live payload exposes no "
            f"normalized {', '.join(missing)}; semantic-quality receipt "
            "cannot be minted"
        )
    return projection


def validate_label_blind_semantic_input_binding(
    stage: StageRecord,
    case: BenchmarkCase,
) -> str:
    """Require the selected producer to bind the canonical source-only input.

    The reviewed case is available only inside this downstream validator.  It
    is used here solely to reconstruct ``{"text": source_text}``; no expected
    class, expected IR, proof obligation, negative control, predicate, or
    entity label participates in the producer-input digest.

    A digest mismatch cannot reveal which extra field entered the producer
    envelope, so it fails closed instead of attempting to infer that the
    producer ignored any reviewed labels it may have received.
    """

    if not isinstance(stage, StageRecord):
        raise SemanticReassessmentError(
            "semantic input binding requires a StageRecord"
        )
    if not isinstance(case, BenchmarkCase):
        raise SemanticReassessmentError(
            "semantic input binding requires a reviewed BenchmarkCase"
        )
    if stage.stage not in _FRONTEND_STAGES:
        raise SemanticReassessmentError(
            "semantic input binding requires a front-end stage"
        )
    if stage.status is not StageStatus.SUCCESS or not _stage_invoked(stage):
        raise SemanticReassessmentError(
            "semantic input binding requires a successful graph-invoked stage"
        )
    expected_input_sha256 = _sha({"text": case.source_text})
    if stage.provenance.input_sha256 != expected_input_sha256:
        raise SemanticReassessmentError(
            "semantic producer input is not bound to the canonical "
            f"label-blind source-only envelope for {stage.stage.value}; "
            "semantic-quality receipt cannot be minted"
        )
    return expected_input_sha256


def _stage_invoked(stage: StageRecord) -> bool:
    value = stage.provenance.effective_identity.get("graph_invoked")
    if type(value) is not bool:
        raise SemanticReassessmentError(
            f"{stage.stage.value} stage lacks an explicit graph_invoked receipt"
        )
    return value


def _v2_cid(
    value: object,
    field: str,
    *,
    codecs: tuple[str, ...] = ("raw", "dag-json"),
) -> str:
    try:
        return validate_cid(value, codecs=codecs)
    except (TypeError, ValueError) as exc:
        raise SemanticReassessmentError(
            f"{field} is not a canonical revision-2 CID"
        ) from exc


def _contains_forbidden_semantic_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in SEMANTIC_FORBIDDEN_PRODUCER_INPUT_FIELDS_V2:
                return True
            if _contains_forbidden_semantic_key(item):
                return True
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return any(_contains_forbidden_semantic_key(item) for item in value)
    return False


def validate_source_only_semantic_input_v2(
    stage: StageRecord,
    source_text: str,
) -> dict[str, str]:
    """Validate the exact source-only input receipt of one invoked producer.

    ``StageProvenance`` remains a revision-1 envelope and therefore retains
    its frozen SHA-256 input field.  Revision 2 uses that legacy field only to
    prove the exact ``{"text": source_text}`` envelope, then independently
    binds the raw UTF-8 source CID in both requested and effective identities.
    New semantic artifact identities are CIDs.
    """

    if not isinstance(stage, StageRecord):
        raise SemanticReassessmentError(
            "source-only semantic validation requires a StageRecord"
        )
    if stage.stage not in _FRONTEND_STAGES or not _stage_invoked(stage):
        raise SemanticReassessmentError(
            "source-only semantic validation requires an invoked front-end"
        )
    if stage.adapter_version != "2":
        raise SemanticReassessmentError(
            f"invoked {stage.stage.value} does not bind semantic adapter "
            "version 2"
        )
    if not isinstance(source_text, str) or not source_text.strip():
        raise SemanticReassessmentError(
            "source-only semantic validation requires nonempty source text"
        )
    expected_input_sha256 = _sha({"text": source_text})
    expected_source_cid = cid_for_bytes(source_text.encode("utf-8"))
    if stage.provenance.input_sha256 != expected_input_sha256:
        raise SemanticReassessmentError(
            f"invoked {stage.stage.value} input is not the exact canonical "
            "source-only envelope"
        )
    for name, identity in (
        ("requested_identity", stage.provenance.requested_identity),
        ("effective_identity", stage.provenance.effective_identity),
    ):
        if (
            name == "effective_identity"
            and identity.get("graph_invoked") is not True
        ):
            raise SemanticReassessmentError(
                f"invoked {stage.stage.value} {name} does not bind "
                "graph_invoked=true"
            )
        if (
            name == "requested_identity"
            and "graph_invoked" in identity
            and identity.get("graph_invoked") is not True
        ):
            raise SemanticReassessmentError(
                f"invoked {stage.stage.value} requested_identity contains "
                "a conflicting graph intent"
            )
        if _contains_forbidden_semantic_key(identity):
            raise SemanticReassessmentError(
                f"invoked {stage.stage.value} {name} contains an evaluator "
                "or proof field"
            )
        protocol_cid = _v2_cid(
            identity.get("semantic_protocol_cid"),
            f"{stage.stage.value}.{name}.semantic_protocol_cid",
            codecs=("dag-json",),
        )
        source_cid = _v2_cid(
            identity.get("source_cid"),
            f"{stage.stage.value}.{name}.source_cid",
            codecs=("raw",),
        )
        if protocol_cid != SEMANTIC_PROTOCOL_V2_CID:
            raise SemanticReassessmentError(
                f"invoked {stage.stage.value} semantic protocol CID drifted"
            )
        if source_cid != expected_source_cid:
            raise SemanticReassessmentError(
                f"invoked {stage.stage.value} source CID is not bound to "
                "the reviewed source bytes"
            )
        if (
            "proof_context_cid" not in identity
            or identity.get("proof_context_cid") is not None
        ):
            raise SemanticReassessmentError(
                f"invoked {stage.stage.value} does not prove the G200 proof "
                "boundary remained closed"
            )
    if stage.stage is StageName.SPACY:
        requested_mode = stage.provenance.requested_identity.get("mode")
        effective_mode = stage.provenance.effective_identity.get("mode")
        if (
            requested_mode not in {
                "full_model",
                "regex_legal",
                "blank_model",
            }
            or effective_mode != requested_mode
        ):
            raise SemanticReassessmentError(
                "invoked spaCy requested/effective mode identity mismatched"
            )
    return {
        "input_sha256": expected_input_sha256,
        "source_cid": expected_source_cid,
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
    }


def _expected_stage_for_producer_v2(producer_id: str) -> StageName:
    if producer_id == "compiler":
        return StageName.COMPILER
    if producer_id == "symai":
        return StageName.SYMAI
    if producer_id.startswith("spacy_"):
        return StageName.SPACY
    raise SemanticReassessmentError(
        "semantic calibration producer is not registered"
    )


def _validate_stage_producer_identity_v2(
    stage: StageRecord,
    producer_id: str,
) -> None:
    expected_stage = _expected_stage_for_producer_v2(producer_id)
    if stage.stage is not expected_stage:
        raise _SemanticSchemaIncompatible(
            f"producer {producer_id} terminated at {stage.stage.value}"
        )
    if stage.stage is not StageName.SPACY:
        return
    mode = stage.provenance.effective_identity.get("mode")
    expected_mode = {
        "spacy_full_model": "full_model",
        "spacy_regex_legal": "regex_legal",
        "spacy_blank_model": "blank_model",
    }[producer_id]
    if mode != expected_mode:
        raise _SemanticSchemaIncompatible(
            f"spaCy producer identity does not bind mode {expected_mode}"
        )


def _validate_compiler_retained_modal_ir_v2(
    modal_ir: Mapping[str, object],
) -> None:
    """Validate the exact identity-only shape used after ModalIR truncation."""

    identity_fields = {
        "normalized_text_cid",
        "formulas_cid",
    }
    if not (
        "projection" in modal_ir
        or identity_fields.intersection(modal_ir)
    ):
        return
    if modal_ir.get("projection") != "cid_only":
        raise SemanticReassessmentError(
            "compiler retained ModalIR CID-only projection marker is invalid"
        )
    _exact(
        modal_ir,
        set(_COMPILER_CID_ONLY_MODAL_IR_FIELDS_V2),
        "compiler retained ModalIR CID-only projection",
    )
    for field in sorted(identity_fields):
        _v2_cid(
            modal_ir.get(field),
            f"compiler.modal_ir.{field}",
            codecs=("dag-json",),
        )


def _parse_semantic_projection_v2(
    stage: StageRecord,
    source_text: str,
) -> SemanticProjection | None:
    """Parse and cross-bind one producer projection and its retained evidence."""

    payload = _mapping(
        stage.data, f"{stage.stage.value} semantic-v2 payload"
    )
    raw_projection = payload.get("semantic_projection")
    if raw_projection is None:
        return None
    try:
        # StageRecord deeply freezes arrays as tuples.  Recreate its exact
        # canonical wire value before invoking the strict projection parser,
        # which correctly requires JSON arrays.
        projection = SemanticProjection.from_dict(_plain(raw_projection))
    except (ProtocolContractError, TypeError, ValueError) as exc:
        raise SemanticReassessmentError(
            f"{stage.stage.value} semantic projection failed strict parsing"
        ) from exc
    if projection.semantic_protocol_cid != SEMANTIC_PROTOCOL_V2_CID:
        raise SemanticReassessmentError(
            f"{stage.stage.value} semantic protocol CID drifted"
        )
    expected_source_cid = cid_for_bytes(source_text.encode("utf-8"))
    if projection.source_cid != expected_source_cid:
        raise SemanticReassessmentError(
            f"{stage.stage.value} projection source CID mismatched"
        )

    outer_protocol = _v2_cid(
        payload.get("semantic_protocol_cid"),
        f"{stage.stage.value}.semantic_protocol_cid",
        codecs=("dag-json",),
    )
    if outer_protocol != projection.semantic_protocol_cid:
        raise SemanticReassessmentError(
            f"{stage.stage.value} projection protocol binding mismatched"
        )

    if stage.stage is StageName.COMPILER:
        if payload.get("schema") != _COMPILER_EVIDENCE_SCHEMA_V2:
            raise _SemanticSchemaIncompatible(
                "compiler did not emit compiler-output.v2"
            )
        if projection.producer_id != "compiler":
            raise SemanticReassessmentError(
                "compiler projection used the wrong producer identity"
            )
        modal_ir = _mapping(payload.get("modal_ir"), "compiler.modal_ir")
        _validate_compiler_retained_modal_ir_v2(modal_ir)
        retained_evidence_cid = cid_for_dag_json(_plain(modal_ir))
        full_evidence_cid = _v2_cid(
            payload.get("modal_ir_cid"),
            "compiler.modal_ir_cid",
            codecs=("dag-json",),
        )
        if (
            _v2_cid(
                payload.get("retained_modal_ir_cid"),
                "compiler.retained_modal_ir_cid",
                codecs=("dag-json",),
            )
            != retained_evidence_cid
            or projection.evidence_cid != full_evidence_cid
        ):
            raise SemanticReassessmentError(
                "compiler full or retained ModalIR CID binding mismatched"
            )
        if payload.get("source_cid") != expected_source_cid:
            raise SemanticReassessmentError(
                "compiler outer source CID mismatched"
            )
    elif stage.stage is StageName.SPACY:
        if payload.get("schema") != _SPACY_EVIDENCE_SCHEMA_V2:
            raise _SemanticSchemaIncompatible(
                "spaCy did not emit spacy-evidence.v2"
            )
        expected_producer = {
            "full_model": "spacy_full_model",
            "regex_legal": "spacy_regex_legal",
            "blank_model": "spacy_blank_model",
        }.get(stage.provenance.effective_identity.get("mode"))
        if projection.producer_id != expected_producer:
            raise SemanticReassessmentError(
                "spaCy projection producer differs from its exact mode "
                "identity"
            )
        document = _mapping(payload.get("document"), "spacy.document")
        if document.get("source_cid") != expected_source_cid:
            raise SemanticReassessmentError(
                "spaCy document source CID mismatched"
            )
        modal_ir = _mapping(payload.get("modal_ir"), "spacy.modal_ir")
        evidence_cid = cid_for_dag_json(_plain(modal_ir))
        if (
            _v2_cid(
                payload.get("modal_ir_cid"),
                "spacy.modal_ir_cid",
                codecs=("dag-json",),
            )
            != evidence_cid
            or projection.evidence_cid != evidence_cid
        ):
            raise SemanticReassessmentError(
                "spaCy retained evidence CID mismatched its projection"
            )
    elif stage.stage is StageName.SYMAI:
        if payload.get("schema") != _SYMAI_EVIDENCE_SCHEMA_V2:
            raise _SemanticSchemaIncompatible(
                "SyMAI did not emit symai-evidence.v2"
            )
        if projection.producer_id != "symai":
            raise SemanticReassessmentError(
                "SyMAI projection used the wrong producer identity"
            )
        if payload.get("source_cid") != expected_source_cid:
            raise SemanticReassessmentError(
                "SyMAI outer source CID mismatched"
            )
        raw_output = payload.get("raw_output")
        if not isinstance(raw_output, str):
            raise SemanticReassessmentError(
                "SyMAI retained raw response bytes are unavailable"
            )
        raw_output_cid = cid_for_bytes(raw_output.encode("utf-8"))
        if (
            _v2_cid(
                payload.get("raw_output_cid"),
                "symai.raw_output_cid",
                codecs=("raw",),
            )
            != raw_output_cid
        ):
            raise SemanticReassessmentError(
                "SyMAI raw response CID mismatched"
            )
        response = _mapping(
            _plain(payload.get("validated_response")),
            "symai.validated_response",
        )
        response_cid = cid_for_dag_json(_plain(response))
        if (
            _v2_cid(
                payload.get("validated_response_cid"),
                "symai.validated_response_cid",
                codecs=("dag-json",),
            )
            != response_cid
            or projection.evidence_cid != response_cid
        ):
            raise SemanticReassessmentError(
                "SyMAI validated-response CID mismatched its projection"
            )
        response_semantics = {
            "logic_family": _normalize_logic_v2(
                response.get("logic_family")
            ),
            "target": normalize_semantic_term(response.get("target")),
            "class": normalize_semantic_term(response.get("class")),
            "predicates": sorted(
                {
                    value
                    for item in _array(
                        response.get("predicates"),
                        "symai.validated_response.predicates",
                    )
                    if (value := normalize_semantic_term(item))
                }
            ),
            "entities": sorted(
                {
                    value
                    for item in _array(
                        response.get("entities"),
                        "symai.validated_response.entities",
                    )
                    if (value := normalize_semantic_term(item))
                }
            ),
        }
        if response_semantics != {
            "logic_family": projection.logic_family,
            "target": projection.target,
            "class": projection.semantic_class,
            "predicates": list(projection.predicates),
            "entities": list(projection.entities),
        }:
            raise SemanticReassessmentError(
                "SyMAI projection differs from its validated response"
            )
        response_completeness = _mapping(
            response.get("completeness"),
            "symai.validated_response.completeness",
        )
        response_ambiguity = tuple(
            sorted(
                {
                    value
                    for item in _array(
                        response.get("ambiguity_flags"),
                        "symai.validated_response.ambiguity_flags",
                    )
                    if (value := normalize_semantic_term(item))
                }
            )
        )
        response_errors = tuple(
            sorted(
                {
                    value
                    for item in _array(
                        response.get("validation_errors"),
                        "symai.validated_response.validation_errors",
                    )
                    if (value := normalize_semantic_term(item))
                }
            )
        )
        if (
            set(response_completeness)
            != set(SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2)
            or any(
                type(response_completeness[field]) is not bool
                for field in SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2
            )
            or dict(response_completeness) != dict(projection.completeness)
            or response_ambiguity != projection.ambiguity_flags
            or response_errors != projection.validation_errors
            or response.get("confidence_millionths")
            != projection.confidence_millionths
        ):
            raise SemanticReassessmentError(
                "SyMAI projection metadata differs from its validated response"
            )
    else:  # pragma: no cover - guarded by caller
        raise SemanticReassessmentError(
            "semantic-v2 projection came from a non-front-end stage"
        )
    return projection


def _validate_semantic_failure_v2(
    stage: StageRecord,
    source_text: str,
) -> str:
    payload = _mapping(
        stage.data, f"{stage.stage.value} semantic failure payload"
    )
    raw_receipt = (
        payload
        if payload.get("schema") == SEMANTIC_FAILURE_SCHEMA_V2
        else payload.get("semantic_failure")
    )
    if raw_receipt is None:
        raise _SemanticSchemaIncompatible(
            f"{stage.stage.value} failure lacks a semantic-v2 failure receipt"
        )
    receipt = _mapping(raw_receipt, "semantic failure receipt")
    _exact(
        receipt,
        {
            "schema",
            "semantic_protocol_cid",
            "stage",
            "failure_subcode",
            "source_cid",
            "proof_context_cid",
            "evidence",
            "receipt_cid",
        },
        "semantic failure receipt",
    )
    if receipt.get("schema") != SEMANTIC_FAILURE_SCHEMA_V2:
        raise SemanticReassessmentError(
            "semantic failure receipt schema drifted"
        )
    body = {
        key: _plain(value)
        for key, value in receipt.items()
        if key != "receipt_cid"
    }
    if (
        _v2_cid(
            receipt.get("receipt_cid"),
            "semantic_failure.receipt_cid",
            codecs=("dag-json",),
        )
        != cid_for_dag_json(body)
    ):
        raise SemanticReassessmentError(
            "semantic failure receipt CID mismatched"
        )
    if (
        receipt.get("semantic_protocol_cid") != SEMANTIC_PROTOCOL_V2_CID
        or receipt.get("stage") != stage.stage.value
        or receipt.get("source_cid")
        != cid_for_bytes(source_text.encode("utf-8"))
    ):
        raise SemanticReassessmentError(
            "semantic failure receipt source or protocol binding mismatched"
        )
    if receipt.get("proof_context_cid") is not None:
        raise SemanticReassessmentError(
            "semantic front-end failure crossed the G200 proof boundary"
        )
    subcode = receipt.get("failure_subcode")
    if subcode not in SEMANTIC_FAILURE_CODES_V2:
        raise SemanticReassessmentError(
            "semantic failure receipt subcode is unsupported"
        )
    if payload is not receipt and stage.stage is StageName.SYMAI:
        raw_output = payload.get("raw_output")
        raw_output_cid = payload.get("raw_output_cid")
        raw_output_bytes = payload.get("raw_output_bytes")
        retained_exactly = payload.get("raw_output_retained_exactly")
        if type(retained_exactly) is not bool:
            raise SemanticReassessmentError(
                "SyMAI failure lacks an exact raw-response retention receipt"
            )
        if retained_exactly:
            if (
                not isinstance(raw_output, str)
                or isinstance(raw_output_bytes, bool)
                or not isinstance(raw_output_bytes, int)
                or raw_output_bytes != len(raw_output.encode("utf-8"))
                or _v2_cid(
                    raw_output_cid,
                    "symai.failure.raw_output_cid",
                    codecs=("raw",),
                )
                != cid_for_bytes(raw_output.encode("utf-8"))
            ):
                raise SemanticReassessmentError(
                    "SyMAI retained failure response does not match its "
                    "CID/byte receipt"
                )
        else:
            if raw_output is not None:
                raise SemanticReassessmentError(
                    "SyMAI failure marked unretained but carried response text"
                )
            if raw_output_cid is None or raw_output_bytes is None:
                if raw_output_cid is not None or raw_output_bytes is not None:
                    raise SemanticReassessmentError(
                        "SyMAI failure raw CID and byte count must be null "
                        "together"
                    )
            elif (
                isinstance(raw_output_bytes, bool)
                or not isinstance(raw_output_bytes, int)
                or raw_output_bytes <= 0
            ):
                raise SemanticReassessmentError(
                    "SyMAI unretained response byte count is invalid"
                )
            else:
                _v2_cid(
                    raw_output_cid,
                    "symai.failure.raw_output_cid",
                    codecs=("raw",),
                )
        evidence = _mapping(
            receipt.get("evidence"),
            "symai.failure.semantic_failure.evidence",
        )
        _exact(
            evidence,
            {"raw_output_cid", "raw_output_bytes"},
            "symai.failure.semantic_failure.evidence",
        )
        if (
            evidence.get("raw_output_cid") != raw_output_cid
            or evidence.get("raw_output_bytes") != raw_output_bytes
        ):
            raise SemanticReassessmentError(
                "SyMAI failure receipt differs from its raw CID/byte binding"
            )
    return str(subcode)


def validate_semantic_frontend_stage_v2(
    stage: StageRecord,
    source_text: str,
) -> SemanticProjection | None:
    """Validate one complete source-only v2 producer stage before persistence."""

    validate_source_only_semantic_input_v2(stage, source_text)
    projection = _parse_semantic_projection_v2(stage, source_text)
    if stage.status is StageStatus.SUCCESS:
        if projection is None:
            raise SemanticReassessmentError(
                f"successful {stage.stage.value} omitted semantic projection"
            )
        return projection
    _validate_semantic_failure_v2(stage, source_text)
    return projection


def _projection_field_representation_v2(
    projection: SemanticProjection | None,
) -> dict[str, bool]:
    if projection is None:
        return {field: False for field in _SEMANTIC_FIELDS_V2}
    return {
        field: bool(projection.completeness[field])
        for field in _SEMANTIC_FIELDS_V2
    }


def _semantic_field_matches_v2(
    target: SemanticCalibrationTargetV2,
    projection: SemanticProjection,
) -> dict[str, bool]:
    """Compare normalized values with the same semantic field shape."""

    return {
        "logic_family": projection.logic_family == target.logic_family,
        "target": projection.target == target.target,
        "class": projection.semantic_class == target.semantic_class,
        "predicates": projection.predicates == target.predicates,
        "entities": projection.entities == target.entities,
    }


def _semantic_evidence_verification_v2(
    stage: StageRecord | None,
    projection: SemanticProjection | None,
) -> dict[str, object]:
    if stage is None or projection is None:
        return {
            "projection_cids_recomputed": projection is not None,
            "projection_evidence_cid_recomputed": False,
            "retained_evidence_cid_recomputed": False,
            "full_evidence_cid_status": "unavailable",
        }
    payload = _mapping(
        stage.data, f"{stage.stage.value} semantic-v2 payload"
    )
    if stage.stage is StageName.COMPILER:
        retained_cid = cid_for_dag_json(
            _plain(_mapping(payload.get("modal_ir"), "compiler.modal_ir"))
        )
        full_cid = payload.get("modal_ir_cid")
        retained_bound = (
            payload.get("retained_modal_ir_cid") == retained_cid
        )
        full_recomputed = full_cid == retained_cid
        return {
            "projection_cids_recomputed": True,
            "projection_evidence_cid_recomputed": full_recomputed,
            "retained_evidence_cid_recomputed": retained_bound,
            "full_evidence_cid_status": (
                "recomputed_from_identical_retained_block"
                if full_recomputed
                else "producer_attested_full_block_not_retained"
            ),
        }
    return {
        "projection_cids_recomputed": True,
        "projection_evidence_cid_recomputed": True,
        "retained_evidence_cid_recomputed": True,
        "full_evidence_cid_status": "recomputed_from_retained_block",
    }


def _semantic_projection_nonvacuous_v2(
    projection: SemanticProjection | None,
) -> bool:
    if projection is None:
        return False
    return bool(
        projection.logic_family not in _SEMANTIC_VACUOUS_TERMS_V2
        and projection.target not in _SEMANTIC_VACUOUS_TERMS_V2
        and projection.predicates
        and projection.target in projection.predicates
    )


def _semantic_coordinate_cost_v2(
    stages: Sequence[StageRecord],
) -> Mapping[str, object]:
    """Return CID-bound telemetry/resource cost for the selected route prefix."""

    selected = tuple(stages)
    invoked = tuple(stage for stage in selected if _stage_invoked(stage))
    body: dict[str, object] = {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "semantic-coordinate-cost.v2"
        ),
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "selected_stage_count": len(selected),
        "invoked_stage_count": len(invoked),
        "selected_stages": [stage.stage.value for stage in selected],
        "invoked_stages": [stage.stage.value for stage in invoked],
        "wall_time_ms": sum(
            float(stage.telemetry.wall_time_ms) for stage in invoked
        ),
        "cpu_time_ms": sum(
            float(stage.telemetry.cpu_time_ms) for stage in invoked
        ),
        "peak_memory_bytes": max(
            (
                int(stage.telemetry.peak_memory_bytes)
                for stage in invoked
            ),
            default=0,
        ),
        "model_calls": sum(
            int(stage.telemetry.model_calls) for stage in invoked
        ),
        "cache_hits": sum(
            int(stage.telemetry.cache_hits) for stage in invoked
        ),
        "cache_misses": sum(
            int(stage.telemetry.cache_misses) for stage in invoked
        ),
        "retries": sum(
            int(stage.telemetry.retries) for stage in invoked
        ),
        "bytes_in": sum(
            int(stage.telemetry.bytes_in) for stage in invoked
        ),
        "bytes_out": sum(
            int(stage.telemetry.bytes_out) for stage in invoked
        ),
        "resource_lanes": sorted(
            {
                stage.telemetry.resource_lane.value
                for stage in invoked
            }
        ),
    }
    return {**body, "cost_receipt_cid": cid_for_dag_json(body)}


def _semantic_coordinate_receipt_v2(
    *,
    coordinate: SemanticCalibrationCoordinateV2,
    target: SemanticCalibrationTargetV2,
    terminal: StageRecord | None,
    projection: SemanticProjection | None,
    status: str,
    quality_millionths: int | None,
    field_matches: Mapping[str, bool | None],
    field_represented: Mapping[str, bool],
    failure_subcode: str | None,
    validation_error_precedence_applied: bool,
    validated_ablation_graph: bool,
    schema_detail: str | None = None,
) -> dict[str, object]:
    expected = target.semantic_fields()
    observed = (
        None
        if projection is None
        else {
            "logic_family": projection.logic_family,
            "target": projection.target,
            "class": projection.semantic_class,
            "predicates": list(projection.predicates),
            "entities": list(projection.entities),
        }
    )
    evidence_verification = _semantic_evidence_verification_v2(
        terminal,
        projection,
    )
    # A compiler projection may describe a full ModalIR block larger than the
    # bounded inline projection retained in the CaseResult.  Until that full
    # block is independently persisted as an immutable CID-addressed sidecar,
    # its producer-attested CID is useful provenance but not evaluator
    # authority.  Typed failures without a projection remain measurable.
    evidence_authoritative = not (
        terminal is not None
        and terminal.stage is StageName.COMPILER
        and projection is not None
        and evidence_verification.get(
            "projection_evidence_cid_recomputed"
        )
        is not True
    )
    body: dict[str, object] = {
        "schema": SEMANTIC_VALIDATOR_RECEIPT_SCHEMA_V2,
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "coordinate": {
            "schema": SEMANTIC_CALIBRATION_COORDINATE_SCHEMA_V2,
            "case_id": coordinate.case_id,
            "producer_id": coordinate.producer_id,
        },
        "source_cid": target.source_cid,
        "validated_ablation_graph": (
            None
            if coordinate.graph_binding is None
            else coordinate.graph_binding.to_dict()
        ),
        "eligible_for_complete_calibration": (
            validated_ablation_graph
            and coordinate.graph_binding is not None
            and evidence_authoritative
        ),
        "terminal_stage": (
            None if terminal is None else terminal.stage.value
        ),
        "terminal_stage_cid": (
            None
            if terminal is None
            else cid_for_dag_json(_plain(terminal.to_dict()))
        ),
        # Compatibility join to the revision-1 StageRecord envelope.
        "terminal_stage_sha256": (
            None if terminal is None else terminal.digest
        ),
        "terminal_stage_failed": (
            None if terminal is None else terminal.status is not StageStatus.SUCCESS
        ),
        "fallback_to_earlier_producer": False,
        "status": status,
        "quality_millionths": quality_millionths,
        "expected_semantics": expected,
        "observed_semantics": observed,
        "field_matches": dict(field_matches),
        "field_represented": dict(field_represented),
        "projection_cid": (
            None if projection is None else projection.projection_cid
        ),
        "projection_available": projection is not None,
        "projection_nonvacuous": _semantic_projection_nonvacuous_v2(
            projection
        ),
        "projection_scoreable": (
            False if projection is None else projection.scoreable
        ),
        "semantic_content_cid": (
            None if projection is None else projection.semantic_content_cid
        ),
        "evidence_cid": (
            None if projection is None else projection.evidence_cid
        ),
        "evidence_verification": evidence_verification,
        "semantic_evidence_authoritative_for_calibration": (
            evidence_authoritative
        ),
        "cost": _semantic_coordinate_cost_v2(coordinate.stages),
        "failure_subcode": failure_subcode,
        "schema_detail": schema_detail,
        "validation_error_precedence_applied": (
            validation_error_precedence_applied
        ),
        "raw_evidence_cid_compared_to_reviewed_ir": False,
        "authoritative_for_proof": False,
        "holdout_accessed": False,
    }
    return {**body, "receipt_cid": cid_for_dag_json(body)}


def _evaluate_semantic_calibration_coordinate_v2(
    target: SemanticCalibrationTargetV2 | Mapping[str, object],
    coordinate: SemanticCalibrationCoordinateV2 | Mapping[str, object],
    *,
    validated_ablation_graph: bool,
) -> Mapping[str, object]:
    """Evaluate one injected source-only coordinate without adapter fallback."""

    reviewed = (
        target
        if isinstance(target, SemanticCalibrationTargetV2)
        else SemanticCalibrationTargetV2.from_dict(target)
    )
    measured = (
        coordinate
        if isinstance(coordinate, SemanticCalibrationCoordinateV2)
        else SemanticCalibrationCoordinateV2.from_dict(coordinate)
    )
    if measured.case_id != reviewed.case_id:
        raise SemanticReassessmentError(
            "semantic coordinate case differs from its reviewed target"
        )
    if validated_ablation_graph and measured.graph_binding is None:
        raise SemanticReassessmentError(
            "authoritative semantic calibration coordinate lacks its "
            "internally derived ablation graph binding"
        )
    frontends = tuple(
        stage
        for stage in measured.stages
        if stage.stage in _FRONTEND_STAGES
    )
    if any(stage.case_id != reviewed.case_id for stage in frontends):
        raise SemanticReassessmentError(
            "semantic stage case differs from its calibration coordinate"
        )
    invoked = tuple(stage for stage in frontends if _stage_invoked(stage))
    for stage in invoked:
        validate_source_only_semantic_input_v2(
            stage,
            reviewed.source_text,
        )

    if not invoked:
        return _semantic_coordinate_receipt_v2(
            coordinate=measured,
            target=reviewed,
            terminal=None,
            projection=None,
            status="semantic_schema_incompatible",
            quality_millionths=None,
            field_matches={field: None for field in _SEMANTIC_FIELDS_V2},
            field_represented={
                field: False for field in _SEMANTIC_FIELDS_V2
            },
            failure_subcode="semantic_schema_incompatible",
            validation_error_precedence_applied=False,
            validated_ablation_graph=validated_ablation_graph,
            schema_detail="coordinate did not invoke a semantic producer",
        )

    terminal = invoked[-1]
    try:
        _validate_stage_producer_identity_v2(
            terminal,
            measured.producer_id,
        )
    except _SemanticSchemaIncompatible as exc:
        return _semantic_coordinate_receipt_v2(
            coordinate=measured,
            target=reviewed,
            terminal=terminal,
            projection=None,
            status="semantic_schema_incompatible",
            quality_millionths=None,
            field_matches={field: None for field in _SEMANTIC_FIELDS_V2},
            field_represented={
                field: False for field in _SEMANTIC_FIELDS_V2
            },
            failure_subcode="semantic_schema_incompatible",
            validation_error_precedence_applied=False,
            validated_ablation_graph=validated_ablation_graph,
            schema_detail=str(exc),
        )

    # Every successful invoked producer must have a well-bound v2 projection,
    # even when a later producer is the route's terminal semantic source.
    parsed: dict[StageName, SemanticProjection] = {}
    try:
        for stage in invoked:
            if stage.status is StageStatus.SUCCESS:
                projection = _parse_semantic_projection_v2(
                    stage,
                    reviewed.source_text,
                )
                if projection is None:
                    raise _SemanticSchemaIncompatible(
                        f"successful {stage.stage.value} stage omitted its "
                        "semantic projection"
                    )
                parsed[stage.stage] = projection
    except _SemanticSchemaIncompatible as exc:
        return _semantic_coordinate_receipt_v2(
            coordinate=measured,
            target=reviewed,
            terminal=terminal,
            projection=None,
            status="semantic_schema_incompatible",
            quality_millionths=None,
            field_matches={field: None for field in _SEMANTIC_FIELDS_V2},
            field_represented={
                field: False for field in _SEMANTIC_FIELDS_V2
            },
            failure_subcode="semantic_schema_incompatible",
            validation_error_precedence_applied=False,
            validated_ablation_graph=validated_ablation_graph,
            schema_detail=str(exc),
        )

    if terminal.status is not StageStatus.SUCCESS:
        projection: SemanticProjection | None = None
        try:
            projection = _parse_semantic_projection_v2(
                terminal,
                reviewed.source_text,
            )
            subcode = _validate_semantic_failure_v2(
                terminal,
                reviewed.source_text,
            )
        except _SemanticSchemaIncompatible as exc:
            return _semantic_coordinate_receipt_v2(
                coordinate=measured,
                target=reviewed,
                terminal=terminal,
                projection=None,
                status="semantic_schema_incompatible",
                quality_millionths=None,
                field_matches={
                    field: None for field in _SEMANTIC_FIELDS_V2
                },
                field_represented={
                    field: False for field in _SEMANTIC_FIELDS_V2
                },
                failure_subcode="semantic_schema_incompatible",
                validation_error_precedence_applied=False,
                validated_ablation_graph=validated_ablation_graph,
                schema_detail=str(exc),
            )
        if subcode == "semantic_schema_incompatible":
            quality: int | None = None
            status = "semantic_schema_incompatible"
        else:
            quality = 0
            status = subcode
        represented = _projection_field_representation_v2(projection)
        return _semantic_coordinate_receipt_v2(
            coordinate=measured,
            target=reviewed,
            terminal=terminal,
            projection=projection,
            status=status,
            quality_millionths=quality,
            field_matches={field: False for field in _SEMANTIC_FIELDS_V2},
            field_represented=represented,
            failure_subcode=subcode,
            validation_error_precedence_applied=(
                subcode == "semantic_validation_failed"
            ),
            validated_ablation_graph=validated_ablation_graph,
        )

    projection = parsed[terminal.stage]
    if projection.producer_id != measured.producer_id:
        raise SemanticReassessmentError(
            "terminal projection producer identity mismatched its coordinate"
        )
    evidence_verification = _semantic_evidence_verification_v2(
        terminal,
        projection,
    )
    if (
        terminal.stage is StageName.COMPILER
        and evidence_verification.get(
            "projection_evidence_cid_recomputed"
        )
        is not True
    ):
        return _semantic_coordinate_receipt_v2(
            coordinate=measured,
            target=reviewed,
            terminal=terminal,
            projection=projection,
            status="semantic_schema_incompatible",
            quality_millionths=None,
            field_matches={
                field: None for field in _SEMANTIC_FIELDS_V2
            },
            field_represented=_projection_field_representation_v2(
                projection
            ),
            failure_subcode="semantic_schema_incompatible",
            validation_error_precedence_applied=False,
            validated_ablation_graph=validated_ablation_graph,
            schema_detail=(
                "compiler full ModalIR CID is only producer-attested; an "
                "immutable CID-addressed full-block sidecar is required "
                "before this coordinate can be authoritative"
            ),
        )
    represented = _projection_field_representation_v2(projection)
    matches = _semantic_field_matches_v2(reviewed, projection)
    if projection.validation_errors:
        status = "semantic_validation_failed"
        quality = 0
        # An invalid semantic response cannot become "ambiguous" merely
        # because it also carried ambiguity flags.
        matches = {**matches, "class": False}
        precedence = True
    elif not projection.scoreable:
        status = "semantic_projection_incomplete"
        quality = 0
        precedence = False
    else:
        correct = all(matches.values())
        status = (
            "semantically_correct"
            if correct
            else "semantically_incorrect"
        )
        quality = 1_000_000 if correct else 0
        precedence = False
    return _semantic_coordinate_receipt_v2(
        coordinate=measured,
        target=reviewed,
        terminal=terminal,
        projection=projection,
        status=status,
        quality_millionths=quality,
        field_matches=matches,
        field_represented=represented,
        failure_subcode=(
            None
            if status in {"semantically_correct", "semantically_incorrect"}
            else status
        ),
        validation_error_precedence_applied=precedence,
        validated_ablation_graph=validated_ablation_graph,
    )


def evaluate_semantic_calibration_coordinate_v2(
    target: SemanticCalibrationTargetV2 | Mapping[str, object],
    coordinate: SemanticCalibrationCoordinateV2 | Mapping[str, object],
) -> Mapping[str, object]:
    """Evaluate a synthetic coordinate without granting graph authority."""

    return _evaluate_semantic_calibration_coordinate_v2(
        target,
        coordinate,
        validated_ablation_graph=False,
    )


def _wilson_lower_bound_millionths_v2(
    successes: int,
    observations: int,
) -> int | None:
    """Return the floor of the preregistered two-sided 95% Wilson lower bound."""

    if (
        isinstance(successes, bool)
        or isinstance(observations, bool)
        or not isinstance(successes, int)
        or not isinstance(observations, int)
        or observations <= 0
        or not 0 <= successes <= observations
    ):
        return None
    proportion = successes / observations
    z = _SEMANTIC_WILSON_Z_95_V2
    z_squared = z * z
    denominator = 1.0 + z_squared / observations
    center = proportion + z_squared / (2.0 * observations)
    margin = z * math.sqrt(
        proportion * (1.0 - proportion) / observations
        + z_squared / (4.0 * observations * observations)
    )
    lower = max(0.0, (center - margin) / denominator)
    return math.floor(lower * 1_000_000)


def _evaluate_semantic_calibration_v2(
    *,
    targets: Sequence[
        SemanticCalibrationTargetV2 | Mapping[str, object]
    ],
    coordinates: Sequence[
        SemanticCalibrationCoordinateV2 | Mapping[str, object]
    ],
    validated_ablation_graph: bool,
    reviewed_target_manifest: Mapping[str, object] | None,
) -> Mapping[str, object]:
    """Build a fail-closed producer/field calibration report.

    A missing or schema-incompatible coordinate produces ``quality_rate=None``.
    A complete set of representable, fully scored but all-wrong projections
    produces the materially different measured value ``quality_rate=0.0``.
    Relative producer selection is not attempted until the complete evidence
    also passes the preregistered non-vacuous absolute quality condition.
    HSSL-G200 never authorizes holdout access, even after calibration passes.
    """

    if isinstance(targets, (str, bytes, bytearray, Mapping)):
        raise SemanticReassessmentError("semantic targets must be a sequence")
    if isinstance(coordinates, (str, bytes, bytearray, Mapping)):
        raise SemanticReassessmentError(
            "semantic coordinates must be a sequence"
        )
    parsed_targets = tuple(
        target
        if isinstance(target, SemanticCalibrationTargetV2)
        else SemanticCalibrationTargetV2.from_dict(target)
        for target in targets
    )
    if not parsed_targets:
        raise SemanticReassessmentError(
            "semantic calibration requires at least one injected target"
        )
    catalog = {target.case_id: target for target in parsed_targets}
    if len(catalog) != len(parsed_targets):
        raise SemanticReassessmentError(
            "semantic calibration targets contain duplicate case ids"
        )
    parsed_coordinates = tuple(
        coordinate
        if isinstance(coordinate, SemanticCalibrationCoordinateV2)
        else SemanticCalibrationCoordinateV2.from_dict(coordinate)
        for coordinate in coordinates
    )
    by_key: dict[
        tuple[str, str], SemanticCalibrationCoordinateV2
    ] = {}
    extras: list[dict[str, str]] = []
    for coordinate in parsed_coordinates:
        key = (coordinate.case_id, coordinate.producer_id)
        if key in by_key:
            raise SemanticReassessmentError(
                "semantic calibration contains duplicate coordinates"
            )
        if coordinate.case_id not in catalog:
            extras.append(
                {
                    "case_id": coordinate.case_id,
                    "producer_id": coordinate.producer_id,
                }
            )
        else:
            by_key[key] = coordinate
    expected = tuple(
        (case_id, producer_id)
        for case_id in sorted(catalog)
        for producer_id in SEMANTIC_PRODUCER_IDS_V2
    )
    missing = [
        {"case_id": case_id, "producer_id": producer_id}
        for case_id, producer_id in expected
        if (case_id, producer_id) not in by_key
    ]
    observations: list[Mapping[str, object]] = []
    for key in expected:
        coordinate = by_key.get(key)
        if coordinate is None:
            continue
        observations.append(
            _evaluate_semantic_calibration_coordinate_v2(
                catalog[key[0]],
                coordinate,
                validated_ablation_graph=validated_ablation_graph,
            )
        )

    field_counts = {
        producer_id: {field: 0 for field in _SEMANTIC_FIELDS_V2}
        for producer_id in SEMANTIC_PRODUCER_IDS_V2
    }
    field_correct_counts = {
        producer_id: {field: 0 for field in _SEMANTIC_FIELDS_V2}
        for producer_id in SEMANTIC_PRODUCER_IDS_V2
    }
    producer_quality: dict[str, list[int]] = {
        producer_id: [] for producer_id in SEMANTIC_PRODUCER_IDS_V2
    }
    producer_observations: dict[str, list[Mapping[str, object]]] = {
        producer_id: [] for producer_id in SEMANTIC_PRODUCER_IDS_V2
    }
    producer_costs: dict[str, list[Mapping[str, object]]] = {
        producer_id: [] for producer_id in SEMANTIC_PRODUCER_IDS_V2
    }
    incompatible: list[dict[str, str]] = []
    for observation in observations:
        coordinate = _mapping(
            observation.get("coordinate"),
            "semantic observation coordinate",
        )
        producer_id = str(coordinate["producer_id"])
        producer_observations[producer_id].append(observation)
        represented = _mapping(
            observation.get("field_represented"),
            "semantic observation field representation",
        )
        matches = _mapping(
            observation.get("field_matches"),
            "semantic observation field correctness",
        )
        for field in _SEMANTIC_FIELDS_V2:
            if represented.get(field) is True:
                field_counts[producer_id][field] += 1
            if matches.get(field) is True:
                field_correct_counts[producer_id][field] += 1
        producer_costs[producer_id].append(
            _mapping(
                observation.get("cost"),
                "semantic observation cost",
            )
        )
        quality = observation.get("quality_millionths")
        if isinstance(quality, int) and not isinstance(quality, bool):
            producer_quality[producer_id].append(quality)
        if (
            observation.get("status") == "semantic_schema_incompatible"
            or quality is None
        ):
            incompatible.append(
                {
                    "case_id": str(coordinate["case_id"]),
                    "producer_id": producer_id,
                }
            )

    observed_case_count = len(parsed_targets)
    case_population_complete = (
        observed_case_count == SEMANTIC_CALIBRATION_CASE_COUNT_V2
    )
    expected_per_field = SEMANTIC_CALIBRATION_CASES_PER_PRODUCER_V2
    coordinate_coverage_complete = bool(
        case_population_complete
        and not missing
        and not extras
        and len(expected) == SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2
        and len(observations)
        == SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2
    )
    field_coverage_complete = all(
        field_counts[producer_id][field] == expected_per_field
        for producer_id in SEMANTIC_PRODUCER_IDS_V2
        for field in _SEMANTIC_FIELDS_V2
    )
    quality_coordinate_complete = all(
        len(producer_quality[producer_id]) == expected_per_field
        for producer_id in SEMANTIC_PRODUCER_IDS_V2
    )
    score_shape_complete = bool(
        coordinate_coverage_complete
        and field_coverage_complete
        and quality_coordinate_complete
        and not incompatible
    )
    target_manifest_cid: str | None = None
    if reviewed_target_manifest is not None:
        manifest = _mapping(
            reviewed_target_manifest,
            "reviewed semantic target manifest",
        )
        raw_manifest_cid = manifest.get("target_manifest_cid")
        target_manifest_cid = _v2_cid(
            raw_manifest_cid,
            "reviewed semantic target manifest CID",
            codecs=("dag-json",),
        )
        manifest_body = {
            key: _plain(value)
            for key, value in manifest.items()
            if key != "target_manifest_cid"
        }
        if (
            manifest.get("schema") != SEMANTIC_TARGET_MANIFEST_SCHEMA_V2
            or cid_for_dag_json(manifest_body) != target_manifest_cid
        ):
            raise SemanticReassessmentError(
                "reviewed semantic target manifest CID mismatched"
            )
    graph_manifest_bound = bool(
        target_manifest_cid is not None
        and all(
            isinstance(observation.get("validated_ablation_graph"), Mapping)
            and observation["validated_ablation_graph"].get(
                "reviewed_target_manifest_cid"
            )
            == target_manifest_cid
            for observation in observations
        )
    )
    graph_coverage_complete = bool(
        len(observations) == SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2
        and all(
            observation.get("eligible_for_complete_calibration") is True
            for observation in observations
        )
        and graph_manifest_bound
    )
    schema_compatible = bool(
        score_shape_complete and graph_coverage_complete
    )
    all_quality = [
        quality
        for producer_id in SEMANTIC_PRODUCER_IDS_V2
        for quality in producer_quality[producer_id]
    ]
    coordinate_quality_millionths = (
        None
        if not score_shape_complete
        else sum(all_quality) // len(all_quality)
    )
    quality_millionths = (
        None
        if not schema_compatible
        else coordinate_quality_millionths
    )
    producer_metrics: dict[str, dict[str, object]] = {}
    for producer_id in SEMANTIC_PRODUCER_IDS_V2:
        values = producer_quality[producer_id]
        producer_rows = producer_observations[producer_id]
        measured_complete = bool(
            len(values) == expected_per_field
            and len(producer_rows) == expected_per_field
            and all(
                observation.get("status")
                != "semantic_schema_incompatible"
                for observation in producer_rows
            )
        )
        producer_graph_complete = bool(
            len(producer_rows) == expected_per_field
            and all(
                observation.get("eligible_for_complete_calibration")
                is True
                for observation in producer_rows
            )
        )
        available_count = sum(
            observation.get("projection_available") is True
            for observation in producer_rows
        )
        nonvacuous_count = sum(
            observation.get("projection_nonvacuous") is True
            for observation in producer_rows
        )
        scoreable_count = sum(
            observation.get("projection_scoreable") is True
            for observation in producer_rows
        )
        exact_successes = sum(value == 1_000_000 for value in values)
        diagnostic_value = (
            None
            if not measured_complete
            else sum(values) // len(values)
        )
        value = (
            diagnostic_value
            if measured_complete and producer_graph_complete
            else None
        )
        wilson_lower = (
            None
            if not measured_complete
            else _wilson_lower_bound_millionths_v2(
                exact_successes,
                len(values),
            )
        )
        field_correctness = {
            field: {
                "correct_count": field_correct_counts[producer_id][field],
                "expected_count": expected_per_field,
                "accuracy_millionths": (
                    None
                    if not measured_complete
                    else (
                        field_correct_counts[producer_id][field]
                        * 1_000_000
                        // expected_per_field
                    )
                ),
            }
            for field in _SEMANTIC_FIELDS_V2
        }
        costs = producer_costs[producer_id]
        cost_totals = {
            field: sum(
                float(cost[field])
                if field in {"wall_time_ms", "cpu_time_ms"}
                else int(cost[field])
                for cost in costs
            )
            for field in (
                "wall_time_ms",
                "cpu_time_ms",
                "model_calls",
                "cache_hits",
                "cache_misses",
                "retries",
                "bytes_in",
                "bytes_out",
            )
        }
        cost_summary: dict[str, object] = {
            "coordinate_count": len(costs),
            "telemetry_complete": len(costs) == expected_per_field,
            "wall_time_ms_total": cost_totals["wall_time_ms"],
            "cpu_time_ms_total": cost_totals["cpu_time_ms"],
            "peak_memory_bytes_max": max(
                (int(cost["peak_memory_bytes"]) for cost in costs),
                default=0,
            ),
            "model_calls_total": cost_totals["model_calls"],
            "cache_hits_total": cost_totals["cache_hits"],
            "cache_misses_total": cost_totals["cache_misses"],
            "retries_total": cost_totals["retries"],
            "bytes_in_total": cost_totals["bytes_in"],
            "bytes_out_total": cost_totals["bytes_out"],
            "coordinate_cost_receipt_cids": [
                cost["cost_receipt_cid"] for cost in costs
            ],
        }
        quality_threshold_passed = bool(
            value is not None
            and value >= SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2
        )
        wilson_threshold_passed = bool(
            wilson_lower is not None
            and wilson_lower
            > SEMANTIC_WILSON_LOWER_BOUND_MIN_MILLIONTHS_V2
        )
        availability_passed = (
            available_count == expected_per_field
            and nonvacuous_count == expected_per_field
        )
        eligible = bool(
            measured_complete
            and producer_graph_complete
            and availability_passed
            and quality_threshold_passed
            and wilson_threshold_passed
        )
        producer_metrics[producer_id] = {
            "coordinate_count": len(values),
            "expected_coordinate_count": expected_per_field,
            "semantic_quality_millionths": value,
            "semantic_quality_rate": (
                None if value is None else value / 1_000_000
            ),
            "diagnostic_semantic_quality_millionths": diagnostic_value,
            "exact_five_field_success_count": exact_successes,
            "wilson_lower_bound_millionths": wilson_lower,
            "wilson_confidence_millionths": (
                SEMANTIC_WILSON_CONFIDENCE_MILLIONTHS_V2
            ),
            "field_correctness": field_correctness,
            "all_fields_represented": all(
                field_counts[producer_id][field] == expected_per_field
                for field in _SEMANTIC_FIELDS_V2
            ),
            "availability": {
                "projection_available_count": available_count,
                "projection_nonvacuous_count": nonvacuous_count,
                "projection_scoreable_count": scoreable_count,
                "expected_count": expected_per_field,
                "all_outputs_available_and_nonvacuous": (
                    availability_passed
                ),
            },
            "cost": cost_summary,
            "absolute_eligibility": {
                "measured_non_schema_incompatible_20_of_20": (
                    measured_complete
                ),
                "validated_graph_20_of_20": producer_graph_complete,
                "all_outputs_available_and_nonvacuous": (
                    availability_passed
                ),
                "quality_minimum_passed": quality_threshold_passed,
                "wilson_lower_bound_strictly_above_minimum": (
                    wilson_threshold_passed
                ),
                "eligible": eligible,
            },
        }
    eligible_producers = sorted(
        producer_id
        for producer_id in SEMANTIC_PRODUCER_IDS_V2
        if producer_metrics[producer_id]["absolute_eligibility"][
            "eligible"
        ]
        is True
    )
    absolute_gate = bool(schema_compatible and eligible_producers)
    selected_producers: list[str] = []
    relative_selection_applied = False
    if absolute_gate:
        identified = {
            producer_id: int(
                producer_metrics[producer_id][
                    "semantic_quality_millionths"
                ]
            )
            for producer_id in eligible_producers
            if producer_metrics[producer_id][
                "semantic_quality_millionths"
            ]
            is not None
        }
        best = max(identified.values())
        selected_producers = sorted(
            producer_id
            for producer_id, value in identified.items()
            if value == best and value > 0
        )
        relative_selection_applied = True

    body: dict[str, object] = {
        "schema": SEMANTIC_CALIBRATION_REPORT_SCHEMA_V2,
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "calibration_route_manifest_cid": (
            SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID
        ),
        "calibration_metric_spec_cid": (
            SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID
        ),
        "reviewed_target_source_cid": (
            SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID
        ),
        "reviewed_target_manifest": (
            None
            if reviewed_target_manifest is None
            else _plain(reviewed_target_manifest)
        ),
        "reviewed_target_manifest_cid": target_manifest_cid,
        "measurement_attribution": {
            "unit": "integrated_frontend_stage_prefix",
            "quality": (
                "terminal_projection_with_required_upstream_dependencies"
            ),
            "cost": "complete_selected_stage_prefix",
            "standalone_producer_claims_permitted": False,
        },
        "status": (
            "complete"
            if schema_compatible
            else (
                "synthetic_or_unvalidated_graph"
                if score_shape_complete
                else "semantic_schema_incompatible"
            )
        ),
        "scope": {
            "injected_unsealed_cases_only": True,
            "holdout_case_count": 0,
            "case_ids": sorted(catalog),
            "producer_ids": list(SEMANTIC_PRODUCER_IDS_V2),
            "semantic_fields": list(_SEMANTIC_FIELDS_V2),
            "expected_case_count": SEMANTIC_CALIBRATION_CASE_COUNT_V2,
            "observed_case_count": observed_case_count,
            "expected_coordinate_count": (
                SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2
            ),
            "observed_coordinate_count": len(observations),
        },
        "coverage": {
            "case_population_complete": case_population_complete,
            "missing_case_count": max(
                0,
                SEMANTIC_CALIBRATION_CASE_COUNT_V2
                - observed_case_count,
            ),
            "extra_case_count": max(
                0,
                observed_case_count
                - SEMANTIC_CALIBRATION_CASE_COUNT_V2,
            ),
            "coordinate_coverage_complete": coordinate_coverage_complete,
            "validated_ablation_graph_coverage_complete": (
                graph_coverage_complete
            ),
            "field_coverage_complete": field_coverage_complete,
            "quality_coordinate_complete": quality_coordinate_complete,
            "missing_coordinates": missing,
            "extra_coordinates": extras,
            "schema_incompatible_coordinates": incompatible,
            "field_coordinate_counts": field_counts,
            "field_correct_counts": field_correct_counts,
            "expected_count_per_producer_field": expected_per_field,
        },
        "quality": {
            "identified": schema_compatible,
            "semantic_quality_millionths": quality_millionths,
            "semantic_quality_rate": (
                None
                if quality_millionths is None
                else quality_millionths / 1_000_000
            ),
            "diagnostic_coordinate_quality_millionths": (
                coordinate_quality_millionths
            ),
            "diagnostic_coordinate_quality_rate": (
                None
                if coordinate_quality_millionths is None
                else coordinate_quality_millionths / 1_000_000
            ),
            "all_wrong_is_measured_zero": quality_millionths == 0,
            "schema_incompatible_is_null": not score_shape_complete,
            "unvalidated_graph_is_null": (
                score_shape_complete and not graph_coverage_complete
            ),
            "producer_metrics": producer_metrics,
        },
        "absolute_quality_gate": {
            "minimum_millionths": (
                SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2
            ),
            "exact_five_field_quality_minimum_millionths": (
                SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2
            ),
            "required_coordinate_count_per_producer": (
                SEMANTIC_CALIBRATION_CASES_PER_PRODUCER_V2
            ),
            "requires_every_output_available_and_nonvacuous": True,
            "confidence_interval_method": "wilson_score_two_sided",
            "confidence_millionths": (
                SEMANTIC_WILSON_CONFIDENCE_MILLIONTHS_V2
            ),
            "wilson_lower_bound_minimum_millionths": (
                SEMANTIC_WILSON_LOWER_BOUND_MIN_MILLIONTHS_V2
            ),
            "wilson_comparison": "strictly_greater_than",
            "eligible_producer_ids": eligible_producers,
            "passed": absolute_gate,
        },
        "relative_selection": {
            "permitted": absolute_gate,
            "applied": relative_selection_applied,
            "selected_producer_ids": selected_producers,
        },
        "shortlist": {
            "frozen": True,
            "kind": "g200_calibration_only",
            "selected_variant_ids": [],
            "reason": (
                "HSSL-G200 cannot authorize an experimental-arm shortlist"
                if absolute_gate
                else (
                    "semantic calibration did not pass complete non-vacuous "
                    "quality"
                )
            ),
        },
        "holdout_authorized": False,
        "production_promotion_authorized": False,
        "observations": observations,
    }
    return {**body, "artifact_cid": cid_for_dag_json(body)}


def evaluate_semantic_calibration_v2(
    *,
    targets: Sequence[
        SemanticCalibrationTargetV2 | Mapping[str, object]
    ],
    coordinates: Sequence[
        SemanticCalibrationCoordinateV2 | Mapping[str, object]
    ],
) -> Mapping[str, object]:
    """Evaluate synthetic/injected coordinates without graph authority.

    This public low-level API is useful for projection contract calibration,
    but it can never mark a report complete or open a selection gate.  Use
    :func:`evaluate_semantic_ablation_calibration_v2` for source-validated
    persisted evidence.
    """

    return _evaluate_semantic_calibration_v2(
        targets=targets,
        coordinates=coordinates,
        validated_ablation_graph=False,
        reviewed_target_manifest=None,
    )


def _reviewed_split_identity_v2(
    cases: Sequence[BenchmarkCase],
    *,
    split: Split,
    case_manifest_sha256: str,
) -> Mapping[str, object]:
    """Recompute one legacy frozen split identity from reviewed case values.

    The revision-1 SHA-256 fields remain here solely because they are the
    existing corpus trust root.  The new semantic target manifest containing
    these verified identities is itself addressed with a DAG-JSON CID.
    """

    ordered = tuple(cases)
    if (
        len(ordered) != 10
        or any(case.split is not split for case in ordered)
    ):
        raise SemanticReassessmentError(
            f"reviewed {split.value} target population must contain exactly "
            "ten cases in frozen order"
        )
    payload: dict[str, object] = {
        "schema": SPLIT_MANIFEST_SCHEMA,
        "corpus_manifest_sha256": case_manifest_sha256,
        "split": split.value,
        "case_ids": [case.case_id for case in ordered],
        "case_sha256s": [case_sha256(case) for case in ordered],
        "source_sha256s": [case.source_sha256 for case in ordered],
        "normalized_source_sha256s": [
            normalized_source_sha256(case.source_text)
            for case in ordered
        ],
    }
    split_sha256 = hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()
    if split_sha256 != FROZEN_SPLIT_SHA256[split]:
        raise SemanticReassessmentError(
            f"reviewed {split.value} target cases do not match the frozen "
            "split identity"
        )
    return {
        **payload,
        "split_manifest_cid": cid_for_dag_json(payload),
        # Frozen-v1 compatibility root used to authenticate this exact block.
        "split_sha256": split_sha256,
    }


def _reviewed_semantic_targets_v2(
    reviewed_cases: Sequence[BenchmarkCase],
    *,
    case_manifest_sha256: str,
    ordered_case_ids_by_split: Mapping[Split, Sequence[str]],
) -> tuple[
    tuple[SemanticCalibrationTargetV2, ...],
    Mapping[str, object],
]:
    if isinstance(
        reviewed_cases, (str, bytes, bytearray, Mapping)
    ) or any(not isinstance(case, BenchmarkCase) for case in reviewed_cases):
        raise SemanticReassessmentError(
            "authoritative semantic calibration requires reviewed "
            "BenchmarkCase values"
        )
    cases = tuple(reviewed_cases)
    if (
        len(cases) != SEMANTIC_CALIBRATION_CASE_COUNT_V2
        or len({case.case_id for case in cases}) != len(cases)
        or sum(case.split is Split.PILOT for case in cases) != 10
        or sum(case.split is Split.DEVELOPMENT for case in cases) != 10
        or any(case.split is Split.HOLDOUT for case in cases)
    ):
        raise SemanticReassessmentError(
            "reviewed semantic target population must be exactly ten pilot "
            "and ten development cases"
        )
    _digest(case_manifest_sha256, "reviewed target case_manifest_sha256")
    if case_manifest_sha256 != FROZEN_CORPUS_MANIFEST_SHA256:
        raise SemanticReassessmentError(
            "reviewed semantic targets must bind the frozen corpus manifest"
        )
    if set(ordered_case_ids_by_split) != {
        Split.PILOT,
        Split.DEVELOPMENT,
    }:
        raise SemanticReassessmentError(
            "reviewed semantic target ordering must bind pilot and "
            "development splits"
        )
    by_id = {case.case_id: case for case in cases}
    ordered_splits: dict[Split, tuple[BenchmarkCase, ...]] = {}
    split_identities: dict[str, Mapping[str, object]] = {}
    for split in (Split.PILOT, Split.DEVELOPMENT):
        raw_ids = ordered_case_ids_by_split[split]
        if isinstance(raw_ids, (str, bytes, bytearray, Mapping)):
            raise SemanticReassessmentError(
                "reviewed semantic split case ids must be a sequence"
            )
        case_ids = tuple(raw_ids)
        if (
            len(case_ids) != 10
            or len(set(case_ids)) != len(case_ids)
            or any(not isinstance(case_id, str) for case_id in case_ids)
            or set(case_ids)
            != {
                case.case_id
                for case in cases
                if case.split is split
            }
        ):
            raise SemanticReassessmentError(
                f"reviewed {split.value} case ordering differs from the "
                "validated graph population"
            )
        ordered = tuple(by_id[case_id] for case_id in case_ids)
        ordered_splits[split] = ordered
        split_identities[split.value] = _reviewed_split_identity_v2(
            ordered,
            split=split,
            case_manifest_sha256=case_manifest_sha256,
        )
    ordered_cases = tuple(
        case
        for split in (Split.PILOT, Split.DEVELOPMENT)
        for case in ordered_splits[split]
    )
    targets = tuple(
        SemanticCalibrationTargetV2.from_benchmark_case(case)
        for case in ordered_cases
    )
    entries = []
    for case, target in sorted(
        zip(ordered_cases, targets, strict=True),
        key=lambda pair: pair[0].case_id,
    ):
        review = case.review.to_dict()
        entries.append(
            {
                "case_id": case.case_id,
                "split": case.split.value,
                "reviewed_case_cid": cid_for_dag_json(case.to_dict()),
                # Frozen-v1 compatibility join.
                "reviewed_case_sha256": case_sha256(case),
                "source_cid": target.source_cid,
                "expected_semantics": target.semantic_fields(),
                "review_attestation_cid": cid_for_dag_json(review),
            }
        )
    body: dict[str, object] = {
        "schema": SEMANTIC_TARGET_MANIFEST_SCHEMA_V2,
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "producer_registry_cid": SEMANTIC_PRODUCER_REGISTRY_V2_CID,
        "reviewed_target_source_cid": (
            SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID
        ),
        "case_manifest_sha256": case_manifest_sha256,
        "reviewed_split_identities": split_identities,
        "case_count": SEMANTIC_CALIBRATION_CASE_COUNT_V2,
        "splits": {"pilot": 10, "development": 10, "holdout": 0},
        "cases": entries,
        "ground_truth_phase": "post_execution_reviewed_validation",
        "holdout_accessed": False,
    }
    return targets, {
        **body,
        "target_manifest_cid": cid_for_dag_json(body),
    }


def evaluate_semantic_ablation_calibration_v2(
    *,
    reviewed_cases: Sequence[BenchmarkCase],
    evidence_sources: Sequence[tuple[object, str | Path]],
) -> Mapping[str, object]:
    """Calibrate only coordinates resolved from validated persisted graphs.

    Each evidence source is an ``(AblationPlan, output_root)`` pair.  This
    function reparses it through ``validate_semantic_ablation_evidence``;
    callers cannot promote the synthetic stage-chain API to complete
    calibration.  The producer route, cold-cache policy, and exact selected
    stage prefix are derived exclusively from the CID-bound preregistration;
    callers cannot choose a favorable variant or cache after observing
    results.  Pilot and development must contribute ten distinct cases each,
    while all proof stages remain suppressed by the semantic execution
    profile.
    """

    from .ablation import (
        AblationPlan,
        AblationValidationError,
        validate_semantic_ablation_evidence,
    )

    if isinstance(evidence_sources, (str, bytes, bytearray, Mapping)):
        raise SemanticReassessmentError(
            "semantic evidence_sources must be a sequence"
        )
    validated: list[tuple[object, object]] = []
    for source in evidence_sources:
        if (
            not isinstance(source, tuple)
            or len(source) != 2
            or not isinstance(source[0], AblationPlan)
        ):
            raise SemanticReassessmentError(
                "semantic evidence source must pair AblationPlan and root"
            )
        plan, output_root = source
        try:
            run = validate_semantic_ablation_evidence(
                plan,
                output_root=output_root,
            )
        except (AblationValidationError, OSError, TypeError, ValueError) as exc:
            raise SemanticReassessmentError(
                "semantic ablation evidence failed source validation"
            ) from exc
        if not run.complete:
            raise SemanticReassessmentError(
                "semantic ablation evidence is not a complete graph"
            )
        validated.append((plan, run))
    if not validated:
        raise SemanticReassessmentError(
            "semantic calibration requires validated ablation evidence"
        )
    plans = [pair[0] for pair in validated]
    if (
        {plan.split for plan in plans}
        != {Split.PILOT, Split.DEVELOPMENT}
        or any(len(plan.case_ids) != 10 for plan in plans)
        or len(plans) != 2
    ):
        raise SemanticReassessmentError(
            "semantic calibration requires exactly ten pilot and ten "
            "development cases"
        )
    common = {
        (
            plan.run_id,
            plan.case_manifest_sha256,
            plan.environment_sha256,
            plan.registry_sha256,
            plan.variant_ids,
            plan.cache_modes,
        )
        for plan in plans
    }
    if len(common) != 1:
        raise SemanticReassessmentError(
            "semantic calibration split graphs do not share one frozen "
            "run/environment/manifest/registry/matrix identity"
        )

    case_manifest_sha256s = {
        plan.case_manifest_sha256 for plan in plans
    }
    if len(case_manifest_sha256s) != 1:
        raise SemanticReassessmentError(
            "semantic calibration plans disagree on reviewed manifest"
        )
    reviewed_case_values = tuple(reviewed_cases)
    ordered_case_ids_by_split = {
        plan.split: plan.case_ids for plan in plans
    }
    parsed_targets, target_manifest = _reviewed_semantic_targets_v2(
        reviewed_case_values,
        case_manifest_sha256=next(iter(case_manifest_sha256s)),
        ordered_case_ids_by_split=ordered_case_ids_by_split,
    )
    catalog = {target.case_id: target for target in parsed_targets}
    reviewed_by_id = {
        case.case_id: case for case in reviewed_case_values
    }
    planned_case_ids = {
        case_id for plan in plans for case_id in plan.case_ids
    }
    if (
        len(parsed_targets) != SEMANTIC_CALIBRATION_CASE_COUNT_V2
        or len(catalog) != len(parsed_targets)
        or set(catalog) != planned_case_ids
        or any(
            reviewed_by_id[case_id].split is not plan.split
            for plan in plans
            for case_id in plan.case_ids
        )
    ):
        raise SemanticReassessmentError(
            "semantic calibration targets differ from the exact validated "
            "pilot/development population"
        )

    graph_index: dict[
        tuple[str, str, str], tuple[object, object, object]
    ] = {}
    for plan, run in validated:
        for job, result in zip(plan.jobs, run.results, strict=True):
            key = (
                job.case.case_id,
                job.variant_id,
                job.cache_mode.value,
            )
            if key in graph_index:
                raise SemanticReassessmentError(
                    "semantic ablation graphs contain duplicate job identities"
                )
            graph_index[key] = (plan, job, result)

    route_manifest = semantic_calibration_route_manifest_v2()
    if (
        cid_for_dag_json(route_manifest)
        != SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID
    ):
        raise SemanticReassessmentError(
            "semantic calibration route manifest CID drifted"
        )
    raw_routes = route_manifest.get("routes")
    if not isinstance(raw_routes, list):
        raise SemanticReassessmentError(
            "semantic calibration route manifest routes are invalid"
        )
    routes: dict[str, Mapping[str, object]] = {}
    for raw_route in raw_routes:
        route = _mapping(raw_route, "semantic calibration route")
        _exact(
            route,
            {
                "producer_id",
                "variant_id",
                "selected_stage",
                "stage_prefix",
            },
            "semantic calibration route",
        )
        producer_id = route.get("producer_id")
        if (
            not isinstance(producer_id, str)
            or producer_id in routes
        ):
            raise SemanticReassessmentError(
                "semantic calibration route producer identity is invalid"
            )
        routes[producer_id] = route
    if (
        set(routes) != set(SEMANTIC_PRODUCER_IDS_V2)
        or route_manifest.get("cache_mode") != "cold"
        or route_manifest.get("coordinate_count")
        != SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2
        or route_manifest.get("cases_per_producer")
        != SEMANTIC_CALIBRATION_CASES_PER_PRODUCER_V2
        or route_manifest.get("post_hoc_route_or_cache_selection")
        is not False
        or route_manifest.get("measurement_unit")
        != "integrated_frontend_stage_prefix"
        or route_manifest.get("quality_attribution")
        != "terminal_projection_with_required_upstream_dependencies"
        or route_manifest.get("cost_attribution")
        != "complete_selected_stage_prefix"
        or route_manifest.get("standalone_producer_claims_permitted")
        is not False
    ):
        raise SemanticReassessmentError(
            "semantic calibration route manifest policy drifted"
        )
    required_variants = {
        str(route["variant_id"]) for route in routes.values()
    }
    if any(
        not required_variants.issubset(plan.variant_ids)
        or "cold" not in {mode.value for mode in plan.cache_modes}
        for plan in plans
    ):
        raise SemanticReassessmentError(
            "validated ablation matrix omits a preregistered semantic route "
            "or the frozen cold-cache coordinate"
        )

    expected_selectors = {
        (case_id, producer_id)
        for case_id in catalog
        for producer_id in SEMANTIC_PRODUCER_IDS_V2
    }
    if len(expected_selectors) != SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2:
        raise SemanticReassessmentError(
            "semantic calibration scope is not the complete frozen "
            "100-coordinate producer grid"
        )

    coordinates: list[SemanticCalibrationCoordinateV2] = []
    for case_id, producer_id in sorted(expected_selectors):
        route = routes[producer_id]
        graph_key = (
            case_id,
            str(route["variant_id"]),
            "cold",
        )
        graph = graph_index.get(graph_key)
        if graph is None:
            raise SemanticReassessmentError(
                "preregistered semantic coordinate did not resolve in a "
                "validated ablation graph"
            )
        plan, job, result = graph
        raw_prefix = route.get("stage_prefix")
        if (
            not isinstance(raw_prefix, list)
            or not raw_prefix
            or any(not isinstance(value, str) for value in raw_prefix)
        ):
            raise SemanticReassessmentError(
                "preregistered semantic route stage prefix is invalid"
            )
        prefix = tuple(raw_prefix)
        selected_stages = tuple(result.stages[: len(prefix)])
        if (
            tuple(stage.stage.value for stage in selected_stages) != prefix
            or selected_stages[-1].stage.value
            != route.get("selected_stage")
        ):
            raise SemanticReassessmentError(
                "validated result does not contain the exact preregistered "
                "semantic stage prefix"
            )
        target = catalog[case_id]
        if (
            not isinstance(job.case.input_data, Mapping)
            or set(job.case.input_data) != {"text"}
            or job.case.input_data.get("text") != target.source_text
        ):
            raise SemanticReassessmentError(
                "semantic target source differs from its validated scheduled "
                "source-only input"
            )
        proof_stages = {
            StageName.HAMMER,
            StageName.LEANSTRAL,
            StageName.KERNEL,
        }
        if any(
            _stage_invoked(stage)
            for stage in result.stages
            if stage.stage in proof_stages
        ):
            raise SemanticReassessmentError(
                "semantic calibration graph invoked a proof stage before G210"
            )
        coordinates.append(
            SemanticCalibrationCoordinateV2(
                case_id=case_id,
                producer_id=producer_id,
                stages=selected_stages,
                graph_binding=SemanticCalibrationGraphBindingV2(
                    plan_cid=cid_for_dag_json(_plain(plan.to_dict())),
                    plan_sha256=plan.digest,
                    case_result_cid=cid_for_dag_json(
                        _plain(result.to_dict())
                    ),
                    case_result_sha256=result.digest,
                    run_id=result.run_id,
                    variant_id=result.variant_id,
                    split=result.split.value,
                    cache_mode=result.cache_mode.value,
                    environment_sha256=plan.environment_sha256,
                    case_manifest_sha256=result.case_manifest_sha256,
                    producer_registry_cid=(
                        SEMANTIC_PRODUCER_REGISTRY_V2_CID
                    ),
                    calibration_route_manifest_cid=(
                        SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID
                    ),
                    calibration_metric_spec_cid=(
                        SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID
                    ),
                    reviewed_target_source_cid=(
                        SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID
                    ),
                    reviewed_target_manifest_cid=str(
                        target_manifest["target_manifest_cid"]
                    ),
                    proof_stages_suppressed=True,
                ),
            )
        )
    return _evaluate_semantic_calibration_v2(
        targets=parsed_targets,
        coordinates=coordinates,
        validated_ablation_graph=True,
        reviewed_target_manifest=target_manifest,
    )


def _validate_frontend_stage_payloads(result: CaseResultRecord) -> None:
    """Validate every materialized front-end payload, not only the winner."""

    for stage in result.stages:
        if stage.stage not in _FRONTEND_STAGES:
            continue
        invoked = _stage_invoked(stage)
        if not invoked and stage.telemetry.model_calls:
            raise SemanticReassessmentError(
                f"non-invoked {stage.stage.value} stage recorded model calls"
            )
        if stage.status is not StageStatus.SUCCESS:
            continue
        payload = _mapping(
            stage.data, f"{stage.stage.value} stage data"
        )
        if not invoked:
            if not (
                stage.stage is StageName.SYMAI
                and payload.get("schema") == _SYMAI_POLICY_SCHEMA
                and payload.get("stage") == StageName.SYMAI.value
                and payload.get("invoked") is False
                and isinstance(payload.get("reason"), str)
                and bool(str(payload["reason"]).strip())
            ):
                raise SemanticReassessmentError(
                    "non-invoked front-end stage lacks a typed suppression "
                    "receipt"
                )
            continue
        _structured_projection(stage, payload)


def _semantic_stage_state(
    result: CaseResultRecord,
) -> tuple[StageRecord | None, bool, str | None]:
    """Return the selected successful source and terminal front-end failure."""

    by_stage = {stage.stage: stage for stage in result.stages}
    terminal_failure: str | None = None
    for name in reversed(_FRONTEND_STAGES):
        stage = by_stage.get(name)
        if stage is None or not _stage_invoked(stage):
            continue
        if stage.status is StageStatus.SUCCESS:
            data = _mapping(stage.data, f"{name.value} stage data")
            if (
                name is StageName.SYMAI
                and data.get("schema") == _SYMAI_POLICY_SCHEMA
                and data.get("invoked") is False
            ):
                continue
            return stage, terminal_failure is not None, terminal_failure
        if stage.status in {StageStatus.FAILED, StageStatus.SKIPPED}:
            terminal_failure = (
                f"{name.value} stage did not produce successful semantic output"
            )
            continue
        if stage.status is StageStatus.UNAVAILABLE:
            terminal_failure = f"{name.value} semantic capability was unavailable"
            continue
    return None, terminal_failure is not None, terminal_failure


def _frontend_signature(
    result: CaseResultRecord,
) -> tuple[str | None, StageRecord | None]:
    """Reproduce the exact stage-bound signature accepted by frontend_report."""

    for stage in reversed(result.stages):
        if stage.stage not in _FRONTEND_STAGES:
            continue
        data = stage.data
        if not isinstance(data, Mapping):
            continue
        if stage.stage is StageName.SYMAI:
            candidate = data.get("candidate_ir")
            if isinstance(candidate, Mapping) and candidate:
                return _sha(candidate), stage
        elif stage.stage is StageName.SPACY:
            modal_ir = data.get("modal_ir")
            if isinstance(modal_ir, Mapping) and modal_ir:
                return _sha(modal_ir), stage
        elif stage.stage is StageName.COMPILER:
            digest = data.get("modal_ir_sha256")
            if isinstance(digest, str) and _SHA256.fullmatch(digest):
                return digest, stage
    return None, None


def _predicted_class(
    projection: Mapping[str, object],
    *,
    semantic_stage_failed: bool,
) -> str:
    if semantic_stage_failed:
        return "unsupported"
    explicit = projection["explicit_classes"]
    if isinstance(explicit, list) and len(explicit) == 1:
        return str(explicit[0])
    ambiguity = projection["ambiguity_flags"]
    if isinstance(ambiguity, list) and ambiguity:
        return "ambiguous"
    errors = projection["validation_errors"]
    if isinstance(errors, list) and errors:
        return "unsupported"
    targets = projection["observed_targets"]
    if isinstance(targets, list) and any(
        target in {"counterexample", "false", "negated"}
        for target in targets
    ):
        return "disproved"
    if any(
        projection[name]
        for name in (
            "observed_logics",
            "observed_targets",
            "observed_predicates",
            "observed_entities",
        )
    ):
        return "proved"
    return "unsupported"


def _stage_bindings(result: CaseResultRecord) -> list[dict[str, object]]:
    return [
        {
            "stage": stage.stage.value,
            "stage_sha256": stage.digest,
            "status": stage.status.value,
            "output_sha256": stage.output_sha256,
            "graph_invoked": _stage_invoked(stage),
            "payload_sha256": _sha(stage.to_dict()["data"]),
        }
        for stage in result.stages
        if stage.stage in _FRONTEND_STAGES
    ]


def _ground_truth_binding(case: BenchmarkCase) -> dict[str, object]:
    payload = {
        "expected_class": case.expected_class.value,
        "expected_ir": dict(case.expected_ir),
        "required_predicates": list(case.required_predicates),
        "required_entities": list(case.required_entities),
        "proof_obligation": (
            None
            if case.proof_obligation is None
            else dict(case.proof_obligation)
        ),
        "review_sha256": _sha(case.review.to_dict()),
    }
    return {
        "case_sha256": case_sha256(case),
        "source_sha256": case.source_sha256,
        "ground_truth_sha256": _sha(payload),
        **payload,
    }


def _validate_result(
    value: CaseResultRecord | Mapping[str, object],
    *,
    run_id: str,
) -> CaseResultRecord:
    try:
        result = (
            value
            if isinstance(value, CaseResultRecord)
            else CaseResultRecord.from_dict(value)
        )
        # Reparse even typed values so the caller cannot rely on mutable nested
        # containers that differ from the canonical wire representation.
        result = CaseResultRecord.from_dict(result.to_dict())
        validate_kernel_bound_result(result)
    except (
        MetricsContractError,
        ProtocolContractError,
        TypeError,
        ValueError,
    ) as exc:
        raise SemanticReassessmentError(
            "case result failed strict source validation"
        ) from exc
    if result.run_id != run_id:
        raise SemanticReassessmentError(
            "case result run id differs from semantic reassessment"
        )
    if result.protocol_sha256 != DEFAULT_PROTOCOL_SHA256:
        raise SemanticReassessmentError("case result protocol identity drifted")
    if result.case_manifest_sha256 != FROZEN_CORPUS_MANIFEST_SHA256:
        raise SemanticReassessmentError(
            "case result corpus manifest identity drifted"
        )
    if result.variant_id not in FRONTEND_VARIANT_IDS:
        raise SemanticReassessmentError(
            "case result is outside the front-end variant scope"
        )
    if result.split.value not in SPLITS:
        raise SemanticReassessmentError(
            "case result is outside the unsealed split scope"
        )
    if result.cache_mode.value not in CACHE_MODES:
        raise SemanticReassessmentError(
            "case result cache mode is outside the frozen scope"
        )
    return result


def _catalog(
    *,
    corpus_path: str | Path,
    manifest_path: str | Path,
) -> tuple[dict[str, BenchmarkCase], dict[str, tuple[str, ...]]]:
    try:
        manifest, cases = load_unsealed_pilot_development(
            corpus_path=corpus_path,
            manifest_path=manifest_path,
        )
    except CorpusContractError as exc:
        raise SemanticReassessmentError(
            "unsealed reviewed corpus failed validation"
        ) from exc
    if (
        manifest.case_count != 30
        or len(cases) != 20
        or any(case.split is Split.HOLDOUT for case in cases)
    ):
        raise SemanticReassessmentError(
            "semantic reassessment scope is not exactly pilot/development"
        )
    catalog = {case.case_id: case for case in cases}
    by_split = {
        split: tuple(
            case.case_id for case in cases if case.split.value == split
        )
        for split in SPLITS
    }
    if any(len(by_split[split]) != 10 for split in SPLITS):
        raise SemanticReassessmentError(
            "unsealed semantic case membership is incomplete"
        )
    return catalog, by_split


def _expected_coordinates(
    by_split: Mapping[str, Sequence[str]],
) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (split, mode, variant, case_id)
        for split in SPLITS
        for mode in CACHE_MODES
        for variant in FRONTEND_VARIANT_IDS
        for case_id in by_split[split]
    )


def _evaluate_coordinate(
    result: CaseResultRecord,
    case: BenchmarkCase,
    *,
    matrix_artifact_sha256: str,
) -> tuple[dict[str, object], dict[str, object]]:
    _validate_frontend_stage_payloads(result)
    missing_status = {
        OutcomeStatus.UNAVAILABLE: "unavailable",
        OutcomeStatus.INFRASTRUCTURE_FAILURE: "infrastructure_failure",
    }.get(result.status)
    selected_stage, semantic_failed, semantic_failure = _semantic_stage_state(
        result
    )
    signature, signature_stage = _frontend_signature(result)
    ground_truth = _ground_truth_binding(case)
    projection: dict[str, object] | None = None
    predicted: str | None = None
    exact_match: bool | None = None
    equivalent: bool | None = None
    ambiguity_correct: bool | None = None
    fail_closed_correct: bool | None = None
    missing_reason: str | None = None

    if missing_status is not None:
        status = missing_status
        missing_reason = (
            result.failure_detail
            or (
                None
                if result.failure_code is None
                else result.failure_code.value
            )
            or "front-end result is unavailable"
        )
        signature = None
        signature_stage = None
    else:
        if result.status is OutcomeStatus.EXCLUDED:
            raise SemanticReassessmentError(
                "excluded case result cannot enter semantic reassessment"
            )
        if selected_stage is None or signature is None or signature_stage is None:
            raise SemanticReassessmentError(
                "frontend schema cannot truthfully represent stage-level "
                "semantic missingness for a non-unavailable case result: "
                f"{result.split.value}/{result.cache_mode.value}/"
                f"{result.variant_id}/{result.case_id}"
            )
        if signature_stage.digest != selected_stage.digest:
            raise SemanticReassessmentError(
                "semantic signature is not bound to the selected successful "
                "front-end stage"
            )
        validate_label_blind_semantic_input_binding(
            selected_stage,
            case,
        )
        projection = validate_normalized_semantic_stage_contract(
            selected_stage
        )
        predicted = _predicted_class(
            projection,
            semantic_stage_failed=semantic_failed,
        )
        expected_ir_sha256 = _sha(dict(case.expected_ir))
        exact_match = signature == expected_ir_sha256
        expected_logic = _normalize_term(case.expected_ir.get("logic"))
        expected_target = _normalize_term(case.expected_ir.get("target"))
        observed_logics = set(projection["observed_logics"])
        observed_targets = set(projection["observed_targets"])
        observed_predicates = set(projection["observed_predicates"])
        observed_entities = set(projection["observed_entities"])
        required_predicates = {
            _normalize_term(value) for value in case.required_predicates
        }
        required_entities = {
            _normalize_term(value) for value in case.required_entities
        }
        missing_predicates = sorted(required_predicates - observed_predicates)
        missing_entities = sorted(required_entities - observed_entities)
        logic_match = expected_logic in observed_logics
        target_match = expected_target in observed_targets
        classification_match = predicted == case.expected_class.value
        equivalent = bool(
            not semantic_failed
            and logic_match
            and target_match
            and not missing_predicates
            and not missing_entities
            and classification_match
        )
        ambiguity_correct = (
            classification_match
            if case.expected_class.value == "ambiguous"
            else None
        )
        fail_closed_correct = (
            classification_match
            if case.expected_class.value in {"disproved", "unsupported"}
            else None
        )
        status = (
            "semantically_correct"
            if exact_match or equivalent
            else "semantically_incorrect"
        )
        projection = {
            **projection,
            "expected_logic": expected_logic,
            "logic_match": logic_match,
            "expected_target": expected_target,
            "target_match": target_match,
            "required_predicates": sorted(required_predicates),
            "missing_predicates": missing_predicates,
            "required_entities": sorted(required_entities),
            "missing_entities": missing_entities,
            "expected_class": case.expected_class.value,
            "classification_match": classification_match,
        }

    coordinate = {
        "split": result.split.value,
        "cache_mode": result.cache_mode.value,
        "variant_id": result.variant_id,
        "case_id": result.case_id,
    }
    receipt_without_digest: dict[str, object] = {
        "schema": SEMANTIC_VALIDATOR_RECEIPT_SCHEMA,
        "run_id": result.run_id,
        "protocol_sha256": result.protocol_sha256,
        "variant_registry_sha256": VARIANT_REGISTRY_SHA256,
        "corpus_manifest_sha256": FROZEN_CORPUS_MANIFEST_SHA256,
        "split_sha256": FROZEN_SPLIT_SHA256[result.split],
        "matrix_artifact_sha256": matrix_artifact_sha256,
        "coordinate": coordinate,
        "case_result_sha256": result.digest,
        "front_end_stage_bindings": _stage_bindings(result),
        "semantic_source": {
            "selected_stage": (
                None if selected_stage is None else selected_stage.stage.value
            ),
            "selected_stage_sha256": (
                None if selected_stage is None else selected_stage.digest
            ),
            "signature_stage": (
                None if signature_stage is None else signature_stage.stage.value
            ),
            "signature_stage_sha256": (
                None if signature_stage is None else signature_stage.digest
            ),
            "semantic_signature_sha256": signature,
            "terminal_semantic_stage_failed": semantic_failed,
            "failure_detail": semantic_failure,
        },
        "ground_truth": ground_truth,
        "evaluation": {
            "status": status,
            "normalized_ir_exact_match": exact_match,
            "deterministic_semantic_equivalence": equivalent,
            "predicted_class": predicted,
            "ambiguity_classification_correct": ambiguity_correct,
            "fail_closed_classification_correct": fail_closed_correct,
            "structured_coverage": projection,
            "missing_reason": missing_reason,
        },
        "evaluation_boundary": {
            "phase": "post_execution_semantic_validation",
            "case_result_preexisting": True,
            "validator_invoked_adapter_or_model": False,
            "ground_truth_fields_bound": [
                "expected_class",
                "expected_ir",
                "required_predicates",
                "required_entities",
                "proof_obligation",
                "review",
            ],
            "scoring_fields_consumed": [
                "expected_class",
                "expected_ir",
                "required_predicates",
                "required_entities",
            ],
        },
        "authoritative_for_proof": False,
        "holdout_accessed": False,
    }
    receipt = {
        **receipt_without_digest,
        "receipt_sha256": _sha(receipt_without_digest),
    }
    stages = tuple(result.stages)
    by_stage = {stage.stage: stage for stage in stages}
    spacy_stage = by_stage.get(StageName.SPACY)
    symai_stage = by_stage.get(StageName.SYMAI)
    symai_setup = (
        None
        if symai_stage is None
        else extract_symai_cache_setup_telemetry(symai_stage)
    )
    setup_model_calls = (
        0 if symai_setup is None else symai_setup.model_calls
    )
    setup_wall_time_ms = (
        0.0 if symai_setup is None else symai_setup.wall_time_ms
    )
    observation = {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark.frontend-observation.v1"
        ),
        "case_id": result.case_id,
        "split": result.split.value,
        "stratum": case.stratum,
        "expected_class": case.expected_class.value,
        "cache_mode": result.cache_mode.value,
        "variant_id": result.variant_id,
        "spacy_mode": VARIANT_REGISTRY[result.variant_id].spacy_mode.value,
        "symai_policy": VARIANT_REGISTRY[result.variant_id].symai_policy.value,
        "status": status,
        "source_receipt_sha256": result.digest,
        "case_result": result.to_dict(),
        "semantic_signature_sha256": signature,
        "normalized_ir_exact_match": exact_match,
        "deterministic_semantic_equivalence": equivalent,
        "semantic_validator_receipt_sha256": receipt["receipt_sha256"],
        "predicted_class": predicted,
        "ambiguity_classification_correct": ambiguity_correct,
        "fail_closed_classification_correct": fail_closed_correct,
        "spacy_invoked": (
            False if spacy_stage is None else _stage_invoked(spacy_stage)
        ),
        "symai_invoked": (
            False if symai_stage is None else _stage_invoked(symai_stage)
        ),
        "symai_model_calls": sum(
            stage.telemetry.model_calls
            for stage in stages
            if stage.stage is StageName.SYMAI
        )
        + setup_model_calls,
        "total_wall_time_ms": round(
            sum(stage.telemetry.wall_time_ms for stage in stages)
            + setup_wall_time_ms,
            6,
        ),
        "model_calls": (
            sum(stage.telemetry.model_calls for stage in stages)
            + setup_model_calls
        ),
        "missing_reason": missing_reason,
    }
    return receipt, observation


def evaluate_frontend_case_results(
    *,
    run_id: str,
    capabilities: Mapping[str, object],
    case_results: Sequence[CaseResultRecord | Mapping[str, object]],
    matrix_artifact_sha256: str,
    corpus_path: str | Path = DEFAULT_CORPUS_PATH,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> SemanticReassessmentEvidence:
    """Evaluate exactly 240 unsealed front-end coordinates in canonical order."""

    _safe_id(run_id, "run_id")
    matrix_digest = _digest(
        matrix_artifact_sha256, "matrix_artifact_sha256"
    )
    if isinstance(case_results, (str, bytes, bytearray, Mapping)):
        raise SemanticReassessmentError(
            "case_results must be a sequence of case results"
        )
    catalog, by_split = _catalog(
        corpus_path=corpus_path,
        manifest_path=manifest_path,
    )
    try:
        results = [
            _validate_result(value, run_id=run_id) for value in case_results
        ]
    except TypeError as exc:
        raise SemanticReassessmentError(
            "case_results must be a sequence of case results"
        ) from exc
    coordinates = [
        (
            result.split.value,
            result.cache_mode.value,
            result.variant_id,
            result.case_id,
        )
        for result in results
    ]
    expected = _expected_coordinates(by_split)
    if len(coordinates) != len(set(coordinates)):
        raise SemanticReassessmentError(
            "semantic reassessment contains duplicate coordinates"
        )
    if set(coordinates) != set(expected):
        raise SemanticReassessmentError(
            "semantic reassessment is not the complete 240-coordinate set; "
            f"missing={sorted(set(expected) - set(coordinates))}, "
            f"extra={sorted(set(coordinates) - set(expected))}"
        )
    by_coordinate = dict(zip(coordinates, results, strict=True))
    receipts: list[Mapping[str, object]] = []
    observations: list[Mapping[str, object]] = []
    for coordinate in expected:
        result = by_coordinate[coordinate]
        case = catalog[result.case_id]
        if result.split is not case.split:
            raise SemanticReassessmentError(
                "case result split differs from reviewed corpus"
            )
        receipt, observation = _evaluate_coordinate(
            result,
            case,
            matrix_artifact_sha256=matrix_digest,
        )
        receipts.append(receipt)
        observations.append(observation)
    try:
        report = build_frontend_report(
            run_id,
            capabilities,
            observations,
        )
    except FrontendReportError as exc:
        raise SemanticReassessmentError(
            "measured front-end report rejected semantic receipts"
        ) from exc
    return SemanticReassessmentEvidence(
        receipts=tuple(receipts),
        observations=tuple(observations),
        report=report,
    )


def _receipt_path(
    directory: Path,
    receipt: Mapping[str, object],
) -> Path:
    coordinate = _mapping(receipt["coordinate"], "receipt.coordinate")
    return (
        directory
        / str(coordinate["split"])
        / str(coordinate["cache_mode"])
        / str(coordinate["variant_id"])
        / f"{coordinate['case_id']}.json"
    )


def _matrix_binding(value: Mapping[str, object]) -> dict[str, object]:
    data = _mapping(value, "matrix_binding")
    _exact(
        data,
        {"path", "bytes_sha256", "artifact_sha256"},
        "matrix_binding",
    )
    path = _relative_reference(
        data["path"],
        "matrix_binding.path",
    ).as_posix()
    if not path.startswith("results/"):
        raise SemanticReassessmentError(
            "matrix_binding.path must remain inside the run results namespace"
        )
    return {
        "path": path,
        "bytes_sha256": _digest(
            data["bytes_sha256"], "matrix_binding.bytes_sha256"
        ),
        "artifact_sha256": _digest(
            data["artifact_sha256"], "matrix_binding.artifact_sha256"
        ),
    }


def _build_index(
    *,
    run_id: str,
    matrix_binding: Mapping[str, object],
    report_path: Path,
    report_raw: bytes,
    report: Mapping[str, object],
    receipt_directory: Path,
    receipt_raw: Sequence[bytes],
    receipts: Sequence[Mapping[str, object]],
    index_path: Path,
) -> dict[str, object]:
    refs = []
    status_counts: dict[str, int] = {}
    for ordinal, (receipt, raw) in enumerate(
        zip(receipts, receipt_raw, strict=True)
    ):
        coordinate = dict(
            _mapping(receipt["coordinate"], "receipt.coordinate")
        )
        evaluation = _mapping(receipt["evaluation"], "receipt.evaluation")
        status = str(evaluation["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        path = _receipt_path(receipt_directory, receipt)
        refs.append(
            {
                "ordinal": ordinal,
                **coordinate,
                "path": _relative(path, index_path),
                "bytes_sha256": _sha_bytes(raw),
                "receipt_sha256": receipt["receipt_sha256"],
                "case_result_sha256": receipt["case_result_sha256"],
                "status": status,
            }
        )
    without_digest = {
        "schema": SEMANTIC_RECEIPT_INDEX_SCHEMA,
        "run_id": run_id,
        "status": "complete",
        "frozen": True,
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "variant_registry_sha256": VARIANT_REGISTRY_SHA256,
        "corpus_manifest_sha256": FROZEN_CORPUS_MANIFEST_SHA256,
        "split_sha256": {
            split: FROZEN_SPLIT_SHA256[Split(split)] for split in SPLITS
        },
        "matrix": dict(matrix_binding),
        "scope": {
            "splits": list(SPLITS),
            "cache_modes": list(CACHE_MODES),
            "variant_ids": list(FRONTEND_VARIANT_IDS),
            "case_count": 20,
            "coordinate_count": len(receipts),
        },
        "receipt_directory": _relative(receipt_directory, index_path),
        "receipts": refs,
        "status_counts": dict(sorted(status_counts.items())),
        "frontend_report": {
            "path": _relative(report_path, index_path),
            "bytes_sha256": _sha_bytes(report_raw),
            "artifact_sha256": report["artifact_sha256"],
        },
        "evaluation_boundary": {
            "ground_truth_phase": "post_execution_semantic_validation",
            "validator_invoked_adapter_or_model": False,
            "holdout_accessed": False,
            "holdout_case_count": 0,
            "holdout_coordinate_count": 0,
        },
    }
    if len(receipts) != EXPECTED_SEMANTIC_COORDINATE_COUNT:
        raise SemanticReassessmentError(
            "semantic receipt index is incomplete"
        )
    return {**without_digest, "artifact_sha256": _sha(without_digest)}


def build_semantic_reassessment(
    *,
    run_id: str,
    capabilities: Mapping[str, object],
    case_results: Sequence[CaseResultRecord | Mapping[str, object]],
    matrix_binding: Mapping[str, object],
    repository_root: str | Path = ".",
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    corpus_path: str | Path = DEFAULT_CORPUS_PATH,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> Mapping[str, object]:
    """Write one immutable semantic receipt set, index, and measured report."""

    repository = Path(repository_root).resolve()
    try:
        layout = require_fresh_reassessment_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ReassessmentNamespaceError as exc:
        raise SemanticReassessmentError(str(exc)) from exc
    binding = _matrix_binding(matrix_binding)
    evidence = evaluate_frontend_case_results(
        run_id=run_id,
        capabilities=capabilities,
        case_results=case_results,
        matrix_artifact_sha256=str(binding["artifact_sha256"]),
        corpus_path=corpus_path,
        manifest_path=manifest_path,
    )
    receipt_directory = _rooted(
        repository, layout.frontend_receipt_directory
    )
    index_path = _rooted(repository, layout.frontend_receipt_index)
    report_path = _rooted(repository, layout.frontend_report)
    targets = [receipt_directory, index_path, report_path]
    run_root = _rooted(repository, layout.run_paths.run_root)
    for target in targets:
        _assert_no_symlink_chain(
            run_root,
            target,
            "semantic reassessment output",
        )
    try:
        reject_published_write_targets(
            repository_root=repository,
            run_id=run_id,
            targets=targets,
            benchmark_root=benchmark_root,
        )
    except ReassessmentNamespaceError as exc:
        raise SemanticReassessmentError(str(exc)) from exc
    if any(path.exists() for path in targets):
        raise SemanticReassessmentError(
            "semantic reassessment output namespace already exists"
        )

    receipt_raw = [
        _write_once(_receipt_path(receipt_directory, receipt), receipt)
        for receipt in evidence.receipts
    ]
    report_raw = _write_once(report_path, evidence.report)
    index = _build_index(
        run_id=run_id,
        matrix_binding=binding,
        report_path=report_path,
        report_raw=report_raw,
        report=evidence.report,
        receipt_directory=receipt_directory,
        receipt_raw=receipt_raw,
        receipts=evidence.receipts,
        index_path=index_path,
    )
    _write_once(index_path, index)
    return validate_semantic_reassessment(
        run_id=run_id,
        capabilities=capabilities,
        case_results=case_results,
        matrix_binding=binding,
        repository_root=repository,
        benchmark_root=benchmark_root,
        corpus_path=corpus_path,
        manifest_path=manifest_path,
    )


def validate_semantic_reassessment(
    *,
    run_id: str,
    capabilities: Mapping[str, object],
    case_results: Sequence[CaseResultRecord | Mapping[str, object]],
    matrix_binding: Mapping[str, object],
    repository_root: str | Path = ".",
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    corpus_path: str | Path = DEFAULT_CORPUS_PATH,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> Mapping[str, object]:
    """Read and recompute a persisted semantic reassessment without mutation."""

    repository = Path(repository_root).resolve()
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ValueError as exc:
        raise SemanticReassessmentError("semantic run_id is invalid") from exc
    binding = _matrix_binding(matrix_binding)
    evidence = evaluate_frontend_case_results(
        run_id=run_id,
        capabilities=capabilities,
        case_results=case_results,
        matrix_artifact_sha256=str(binding["artifact_sha256"]),
        corpus_path=corpus_path,
        manifest_path=manifest_path,
    )
    receipt_directory = _rooted(
        repository, layout.frontend_receipt_directory
    )
    index_path = _rooted(repository, layout.frontend_receipt_index)
    report_path = _rooted(repository, layout.frontend_report)
    run_root = _rooted(repository, layout.run_paths.run_root)
    for target in (receipt_directory, index_path, report_path):
        _assert_no_symlink_chain(
            run_root,
            target,
            "semantic reassessment artifact",
        )

    receipt_raw: list[bytes] = []
    for expected in evidence.receipts:
        value, raw = _read_canonical(
            _receipt_path(receipt_directory, expected),
            "semantic validator receipt",
        )
        if value != expected:
            raise SemanticReassessmentError(
                "semantic validator receipt changed"
            )
        receipt_raw.append(raw)
    report_value, report_raw = _read_canonical(
        report_path, "front-end semantic report"
    )
    try:
        report = load_frontend_report(report_path)
    except FrontendReportError as exc:
        raise SemanticReassessmentError(
            "front-end semantic report failed validation"
        ) from exc
    if report_value != report or report != evidence.report:
        raise SemanticReassessmentError(
            "front-end semantic report changed"
        )
    expected_index = _build_index(
        run_id=run_id,
        matrix_binding=binding,
        report_path=report_path,
        report_raw=report_raw,
        report=report,
        receipt_directory=receipt_directory,
        receipt_raw=receipt_raw,
        receipts=evidence.receipts,
        index_path=index_path,
    )
    index_value, _raw = _read_canonical(
        index_path, "semantic receipt index"
    )
    if index_value != expected_index:
        raise SemanticReassessmentError(
            "semantic receipt index changed"
        )
    return expected_index


def _safe_matrix_result_path(
    *,
    repository: Path,
    index_path: Path,
    relative_path: object,
) -> Path:
    if not isinstance(relative_path, str):
        raise SemanticReassessmentError(
            "matrix result path must be a string"
        )
    pure = PurePosixPath(relative_path)
    if (
        pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative_path
        or "\\" in relative_path
        or not relative_path.startswith("matrix/")
    ):
        raise SemanticReassessmentError(
            "matrix result path escaped its namespace"
        )
    result_root = index_path.parent
    candidate = result_root.joinpath(*pure.parts)
    _assert_no_symlink_chain(
        result_root,
        candidate,
        "matrix result",
    )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(result_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise SemanticReassessmentError(
            f"matrix result path is unavailable: {relative_path}"
        ) from exc
    return resolved


def _load_matrix_frontend_results(
    *,
    repository: Path,
    index_path: Path,
    matrix: Mapping[str, object],
) -> tuple[CaseResultRecord, ...]:
    results: list[CaseResultRecord] = []
    seen: set[tuple[str, str, str, str]] = set()
    for raw_split in _array(matrix.get("split_runs"), "matrix.split_runs"):
        split = _mapping(raw_split, "matrix.split_runs[]")
        for raw_ref in _array(split.get("results"), "matrix.results"):
            ref = _mapping(raw_ref, "matrix.results[]")
            if ref.get("variant_id") not in FRONTEND_VARIANT_IDS:
                continue
            path = _safe_matrix_result_path(
                repository=repository,
                index_path=index_path,
                relative_path=ref.get("path"),
            )
            outer, raw = _read_canonical(path, "matrix case result")
            record = _mapping(outer, "matrix case result")
            try:
                result = CaseResultRecord.from_dict(record.get("case_result"))
            except (TypeError, ValueError) as exc:
                raise SemanticReassessmentError(
                    "matrix case result failed validation"
                ) from exc
            if (
                _sha_bytes(raw) != ref.get("bytes_sha256")
                or result.digest != ref.get("case_result_sha256")
                or result.case_id != ref.get("case_id")
                or result.variant_id != ref.get("variant_id")
                or result.cache_mode.value != ref.get("cache_mode")
                or result.split.value != split.get("split")
            ):
                raise SemanticReassessmentError(
                    "matrix result differs from its validated index"
                )
            coordinate = (
                result.split.value,
                result.cache_mode.value,
                result.variant_id,
                result.case_id,
            )
            if coordinate in seen:
                raise SemanticReassessmentError(
                    "matrix contains duplicate front-end coordinates"
                )
            seen.add(coordinate)
            results.append(result)
    if len(results) != EXPECTED_SEMANTIC_COORDINATE_COUNT:
        raise SemanticReassessmentError(
            "validated matrix front-end subset is incomplete"
        )
    return tuple(results)


def _frontend_capabilities(
    frozen: LiveCapabilityReprobe,
) -> dict[str, object]:
    by_kind = frozen.inventory.by_kind

    def record(kind: CapabilityKind) -> dict[str, str]:
        value = by_kind[kind]
        return {
            "status": value.status.value,
            "reason": (
                ""
                if value.status is CapabilityStatus.AVAILABLE
                else str(value.reason or "capability is not available")
            ),
        }

    return {
        "current_modal_codec": {"status": "available", "reason": ""},
        "spacy_full_model": record(CapabilityKind.SPACY_PIPELINE),
        "regex_legal_parser": {"status": "available", "reason": ""},
        "spacy_blank_model": {"status": "available", "reason": ""},
        "symai": record(CapabilityKind.SYMAI),
        "llm_router": record(CapabilityKind.LLM_ROUTER),
    }


def _validated_matrix_inputs(
    *,
    repository: Path,
    run_id: str,
    benchmark_root: str | Path,
) -> tuple[
    LiveCapabilityReprobe,
    Mapping[str, object],
    tuple[CaseResultRecord, ...],
    dict[str, object],
]:
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ValueError as exc:
        raise SemanticReassessmentError(
            "semantic reassessment run_id is invalid"
        ) from exc
    baseline = _rooted(repository, layout.baseline_manifest)
    receipts = _rooted(repository, layout.receipt_directory)
    matrix_root = _rooted(repository, layout.matrix_root)
    matrix_snapshot = _rooted(repository, layout.matrix_snapshot)
    matrix_index = _rooted(repository, layout.matrix_index)
    run_root = _rooted(repository, layout.run_paths.run_root)
    _assert_no_symlink_chain(run_root, matrix_index, "matrix index")
    matrix_value, matrix_raw = _read_canonical(
        matrix_index, "matrix index"
    )
    matrix_header = _mapping(matrix_value, "matrix index")
    if matrix_header.get("schema") == MATRIX_INDEX_SCHEMA:
        raise SemanticReassessmentError(
            "reassessment-matrix.v1 is revision-1 diagnostic evidence and "
            "cannot mint semantic-v2 quality receipts; operators must use "
            "the G201 source-only semantic-v2 execution path"
        )
    try:
        frozen = validate_frozen_capability_reprobe(
            repository_root=repository,
            expected_run_id=run_id,
            benchmark_root=benchmark_root,
            baseline_manifest=baseline,
            receipt_directory=receipts,
        )
        matrix = validate_reassessment_matrix(
            repository_root=repository,
            run_id=run_id,
            benchmark_root=benchmark_root,
            receipt_directory=receipts,
            baseline_manifest=baseline,
            output_root=matrix_root,
            snapshot_path=matrix_snapshot,
            frozen_reprobe=frozen,
        )
    except (
        CapabilityFreezeError,
        MatrixReassessmentError,
        ReassessmentNamespaceError,
    ) as exc:
        raise SemanticReassessmentError(
            "semantic reassessment matrix prerequisite is invalid"
        ) from exc
    if matrix_value != matrix:
        raise SemanticReassessmentError(
            "validated matrix differs from its index"
        )
    results = _load_matrix_frontend_results(
        repository=repository,
        index_path=matrix_index,
        matrix=matrix,
    )
    binding = {
        "path": _relative(
            matrix_index,
            _rooted(repository, layout.frontend_receipt_index),
        ),
        "bytes_sha256": _sha_bytes(matrix_raw),
        "artifact_sha256": matrix["artifact_sha256"],
    }
    return frozen, matrix, results, binding


def execute_semantic_reassessment(
    *,
    repository_root: str | Path = ".",
    run_id: str,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> Mapping[str, object]:
    """Validate, but never execute, the matrix and publish semantic receipts."""

    repository = Path(repository_root).resolve()
    try:
        require_fresh_reassessment_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ReassessmentNamespaceError as exc:
        raise SemanticReassessmentError(str(exc)) from exc
    frozen, _matrix, results, binding = _validated_matrix_inputs(
        repository=repository,
        run_id=run_id,
        benchmark_root=benchmark_root,
    )
    return build_semantic_reassessment(
        run_id=run_id,
        capabilities=_frontend_capabilities(frozen),
        case_results=results,
        matrix_binding=binding,
        repository_root=repository,
        benchmark_root=benchmark_root,
    )


def validate_semantic_reassessment_from_matrix(
    *,
    repository_root: str | Path = ".",
    run_id: str,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> Mapping[str, object]:
    """Validate persisted receipts against the complete validated matrix."""

    repository = Path(repository_root).resolve()
    frozen, _matrix, results, binding = _validated_matrix_inputs(
        repository=repository,
        run_id=run_id,
        benchmark_root=benchmark_root,
    )
    return validate_semantic_reassessment(
        run_id=run_id,
        capabilities=_frontend_capabilities(frozen),
        case_results=results,
        matrix_binding=binding,
        repository_root=repository,
        benchmark_root=benchmark_root,
    )


__all__ = [
    "EXPECTED_SEMANTIC_COORDINATE_COUNT",
    "SEMANTIC_CALIBRATION_COORDINATE_SCHEMA_V2",
    "SEMANTIC_CALIBRATION_REPORT_SCHEMA_V2",
    "SEMANTIC_RECEIPT_INDEX_SCHEMA",
    "SEMANTIC_TARGET_MANIFEST_SCHEMA_V2",
    "SEMANTIC_VALIDATOR_RECEIPT_SCHEMA",
    "SEMANTIC_VALIDATOR_RECEIPT_SCHEMA_V2",
    "SemanticCalibrationCoordinateV2",
    "SemanticCalibrationGraphBindingV2",
    "SemanticCalibrationTargetV2",
    "SemanticReassessmentError",
    "SemanticReassessmentEvidence",
    "build_semantic_reassessment",
    "evaluate_semantic_ablation_calibration_v2",
    "evaluate_semantic_calibration_coordinate_v2",
    "evaluate_semantic_calibration_v2",
    "evaluate_frontend_case_results",
    "execute_semantic_reassessment",
    "validate_label_blind_semantic_input_binding",
    "validate_semantic_reassessment",
    "validate_semantic_reassessment_from_matrix",
    "validate_normalized_semantic_stage_contract",
    "validate_semantic_frontend_stage_v2",
    "validate_source_only_semantic_input_v2",
]
