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
import hashlib
import json
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
    BenchmarkCase,
    CorpusContractError,
    Split,
    case_sha256,
    load_unsealed_pilot_development,
)
from .contracts import (
    DEFAULT_PROTOCOL_SHA256,
    CaseResultRecord,
    OutcomeStatus,
    ProtocolContractError,
    StageName,
    StageRecord,
    StageStatus,
    canonical_json,
)
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


@dataclass(frozen=True, slots=True)
class SemanticReassessmentEvidence:
    """In-memory receipt set and measured report before immutable persistence."""

    receipts: tuple[Mapping[str, object], ...]
    observations: tuple[Mapping[str, object], ...]
    report: Mapping[str, object]


def _plain(value: object) -> object:
    """Thaw contract-owned immutable containers into canonical JSON data."""

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


def _stage_invoked(stage: StageRecord) -> bool:
    value = stage.provenance.effective_identity.get("graph_invoked")
    if type(value) is not bool:
        raise SemanticReassessmentError(
            f"{stage.stage.value} stage lacks an explicit graph_invoked receipt"
        )
    return value


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
        payload = _mapping(
            selected_stage.data,
            f"{selected_stage.stage.value} semantic payload",
        )
        projection = _structured_projection(selected_stage, payload)
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
        ),
        "total_wall_time_ms": round(
            sum(stage.telemetry.wall_time_ms for stage in stages), 6
        ),
        "model_calls": sum(stage.telemetry.model_calls for stage in stages),
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
    matrix_value, matrix_raw = _read_canonical(
        matrix_index, "matrix index"
    )
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
    "SEMANTIC_RECEIPT_INDEX_SCHEMA",
    "SEMANTIC_VALIDATOR_RECEIPT_SCHEMA",
    "SemanticReassessmentError",
    "SemanticReassessmentEvidence",
    "build_semantic_reassessment",
    "evaluate_frontend_case_results",
    "execute_semantic_reassessment",
    "validate_semantic_reassessment",
    "validate_semantic_reassessment_from_matrix",
]
