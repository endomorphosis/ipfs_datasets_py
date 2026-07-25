"""Source-bound HSSL reassessment pilot decision.

This module is the persisted trust boundary for HSSL-G140.  It validates the
complete unchanged pilot/development matrix before deriving front-end,
proof-efficacy, efficiency, paired-statistics, safety, and Pareto evidence
from its case-result receipts.  A shortlist is authorized only when every
selected arm passes the preregistered materiality gate and has independently
observed semantic quality.  Missing quality or zero verified success remains
visible and produces a frozen empty shortlist with remediation.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
from typing import Final, Mapping, Sequence

from . import BENCHMARK_ID, DEFAULT_BENCHMARK_ROOT
from .ablation import ABLATION_RESULT_SCHEMA
from .cache_measurement import (
    extract_symai_cache_setup_telemetry,
    symai_backend_invocation_count,
)
from .contracts import (
    DEFAULT_PROTOCOL,
    DEFAULT_PROTOCOL_SHA256,
    CandidateGateObservation,
    CaseResultRecord,
    GateStatus,
    OutcomeStatus,
    ProtocolContractError,
    StageName,
    canonical_json,
    evaluate_candidate_gate,
)
from .matrix_reassessment import (
    DEFAULT_MATRIX_INDEX,
    DEFAULT_MATRIX_ROOT,
    DEFAULT_MATRIX_SNAPSHOT,
    EXPECTED_COORDINATE_COUNT,
    MATRIX_INDEX_SCHEMA,
    MatrixReassessmentError,
    validate_reassessment_matrix,
)
from .reassessment_namespace import (
    PUBLISHED_REASSESSMENT_RUN_ID,
    ReassessmentNamespaceError,
    ReassessmentRunLayout,
    reject_published_write_targets,
)
from .variants import (
    ALL_VARIANT_IDS,
    VARIANT_REGISTRY,
    VARIANT_REGISTRY_SHA256,
)


PILOT_REASSESSMENT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.reassessment-pilot-shortlist.v1"
)
PILOT_REASSESSMENT_SNAPSHOT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "reassessment-pilot-shortlist-snapshot.v1"
)
PILOT_REASSESSMENT_RUN_ID: Final = PUBLISHED_REASSESSMENT_RUN_ID
_PUBLISHED_LAYOUT: Final = ReassessmentRunLayout.for_run(
    PILOT_REASSESSMENT_RUN_ID
)
DEFAULT_PILOT_REASSESSMENT_PATH: Final = _PUBLISHED_LAYOUT.pilot_report
DEFAULT_PILOT_REASSESSMENT_SNAPSHOT: Final = _PUBLISHED_LAYOUT.pilot_snapshot
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
VALIDATION_COMMAND: Final = (
    "python benchmarks/logic_pipeline/report.py --gate pilot-shortlist "
    "--artifact workspace/benchmarks/hammer-symai-spacy-leanstral/"
    "reassessment-v2/results/pilot-shortlist-v2.json"
)
_CANDIDATE_IDS: Final = tuple(
    item for item in ALL_VARIANT_IDS if item not in {"A0", "S1"}
)
_SELECTION_SPLITS: Final = ("pilot", "development")
_CACHE_MODES: Final = ("cold", "warm")
_FRONTEND_REPRESENTATIVE: Final = {
    "A1": "A1",
    "A2": "A1",
    "A3": "A1",
    "A4": "A4",
    "A5": "A5",
    "A6": "A4",
    "A7": "A7",
    "A8": "A8",
    "A9": "A4",
    "A10": "A4",
    "A11": "A4",
    "A12": "A5",
}
# The optional semantic report may contain 240 bounded CaseResult-derived
# observations.  Keep a finite aggregate ceiling consistent with its upstream
# validator rather than rejecting a contract-valid complete fresh run.
_MAX_ARTIFACT_BYTES: Final = 128 * 1024 * 1024


class PilotReassessmentError(ValueError):
    """Raised when the reassessment shortlist is stale or unsupported."""


def HSSLEV1409B38() -> str:
    """Return the AST-verifiable complete reassessment pilot-gate evidence."""

    return (
        "complete unchanged pilot and development source receipts with "
        "front-end, proof, efficiency, statistics, safety, Pareto, and an "
        "exact deeply frozen fail-closed shortlist authorization decision"
    )


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise PilotReassessmentError(f"{field} must be an object")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise PilotReassessmentError(f"{field} must be an array")
    return value


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PilotReassessmentError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> object:
    raise PilotReassessmentError(f"non-finite JSON number is forbidden: {token}")


def _read_canonical(path: Path, field: str) -> tuple[object, bytes]:
    try:
        file_stat = path.lstat()
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise PilotReassessmentError(
                f"{field} must be a regular non-symlink file"
            )
        if file_stat.st_size <= 0 or file_stat.st_size > _MAX_ARTIFACT_BYTES:
            raise PilotReassessmentError(f"{field} size is outside the safe bound")
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except PilotReassessmentError:
        raise
    except (OSError, UnicodeError) as exc:
        raise PilotReassessmentError(f"cannot read {field}: {path}") from exc
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise PilotReassessmentError(f"{field} is not canonical newline JSON")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, PilotReassessmentError) as exc:
        raise PilotReassessmentError(f"{field} is not strict JSON") from exc
    try:
        expected = (canonical_json(value) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PilotReassessmentError(
            f"{field} is not canonically serializable"
        ) from exc
    if raw != expected:
        raise PilotReassessmentError(f"{field} is not canonical JSON")
    return value, raw


def _resolve_root(repository_root: str | Path) -> Path:
    try:
        root = Path(repository_root).resolve(strict=True)
    except OSError as exc:
        raise PilotReassessmentError("repository root is unavailable") from exc
    if not root.is_dir():
        raise PilotReassessmentError("repository root is not a directory")
    return root


def _rooted(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _relative_reference(value: object, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PilotReassessmentError(
            f"{field} must be a canonical relative POSIX path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise PilotReassessmentError(
            f"{field} must be a canonical relative POSIX path"
        )
    return path


def _assert_no_symlink_chain(root: Path, target: Path, field: str) -> None:
    logical_root = root.absolute()
    logical_target = target.absolute()
    for ancestor in reversed((logical_root, *logical_root.parents)):
        if ancestor.is_symlink():
            raise PilotReassessmentError(
                f"{field} reference root must not use a symlink"
            )
    try:
        relative = logical_target.relative_to(logical_root)
    except ValueError as exc:
        raise PilotReassessmentError(
            f"{field} escaped its canonical reference root"
        ) from exc
    current = logical_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise PilotReassessmentError(f"{field} must not use a symlink")


def _fresh_reference_root(
    repository: Path,
    layout: ReassessmentRunLayout,
) -> Path:
    return _rooted(repository, layout.run_paths.run_root)


def _fresh_artifact_reference(
    path: Path,
    *,
    repository: Path,
    layout: ReassessmentRunLayout,
    field: str,
    expected_kind: str | None = None,
) -> str:
    """Return a canonical run-root-relative reference for fresh evidence."""

    reference_root = _fresh_reference_root(repository, layout)
    target = _rooted(repository, path)
    _assert_no_symlink_chain(reference_root, target, field)
    try:
        resolved_root = reference_root.resolve(strict=expected_kind is not None)
        resolved = target.resolve(strict=expected_kind is not None)
        relative = resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise PilotReassessmentError(
            f"{field} escaped its canonical reference root"
        ) from exc
    if expected_kind == "file" and not resolved.is_file():
        raise PilotReassessmentError(f"{field} must be a regular file")
    if expected_kind == "directory" and not resolved.is_dir():
        raise PilotReassessmentError(f"{field} must be a directory")
    reference = relative.as_posix()
    _relative_reference(reference, field)
    return reference


def _snapshot_capture_date(
    run_id: str,
    value: object | None = None,
) -> str:
    if run_id == PILOT_REASSESSMENT_RUN_ID:
        if value not in {None, "2026-07-24"}:
            raise PilotReassessmentError(
                "published pilot snapshot capture date changed"
            )
        return "2026-07-24"
    captured_on = (
        datetime.now(timezone.utc).date().isoformat()
        if value is None
        else value
    )
    if not isinstance(captured_on, str):
        raise PilotReassessmentError(
            "fresh pilot snapshot capture date is invalid"
        )
    try:
        captured = date.fromisoformat(captured_on)
    except ValueError as exc:
        raise PilotReassessmentError(
            "fresh pilot snapshot capture date is invalid"
        ) from exc
    if (
        captured_on != captured.isoformat()
        or captured > datetime.now(timezone.utc).date()
    ):
        raise PilotReassessmentError(
            "fresh pilot snapshot capture date is invalid"
        )
    return captured_on


def _safe_result_path(
    root: Path,
    relative_path: object,
    *,
    matrix_index: Path,
    run_id: str,
) -> Path:
    if not isinstance(relative_path, str):
        raise PilotReassessmentError("matrix result path must be a string")
    pure = PurePosixPath(relative_path)
    fresh = run_id != PILOT_REASSESSMENT_RUN_ID
    if (
        pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or (fresh and pure.as_posix() != relative_path)
        or (fresh and "\\" in relative_path)
        or not relative_path.startswith("matrix/")
    ):
        raise PilotReassessmentError("matrix result path escaped its namespace")
    result_root = _rooted(root, matrix_index).parent
    candidate = result_root.joinpath(*pure.parts)
    if fresh:
        _assert_no_symlink_chain(result_root, candidate, "matrix result")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(result_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise PilotReassessmentError(
            f"matrix result path is unavailable: {relative_path}"
        ) from exc
    return resolved


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise PilotReassessmentError("cannot derive a percentile from no values")
    ordered = sorted(values)
    ordinal = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(float(ordered[ordinal]), 6)


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _paired_interval(values: Sequence[int]) -> tuple[float, float, float]:
    if not values:
        raise PilotReassessmentError("paired statistics require observations")
    mean = sum(values) / len(values)
    if len(values) == 1:
        return mean, mean, mean
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    margin = 1.96 * math.sqrt(variance / len(values))
    return (
        round(mean, 12),
        round(max(-1.0, mean - margin), 12),
        round(min(1.0, mean + margin), 12),
    )


def _result_observations(
    root: Path,
    matrix: Mapping[str, object],
    *,
    matrix_index: Path,
    run_id: str,
) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for raw_split in _array(matrix.get("split_runs"), "matrix.split_runs"):
        split = _mapping(raw_split, "matrix.split_runs[]")
        for raw_index in _array(split.get("results"), "matrix.split.results"):
            index = _mapping(raw_index, "matrix.split.results[]")
            path = _safe_result_path(
                root,
                index.get("path"),
                matrix_index=matrix_index,
                run_id=run_id,
            )
            outer_raw, raw_bytes = _read_canonical(path, "matrix case result")
            outer = _mapping(outer_raw, "matrix case result")
            try:
                result = CaseResultRecord.from_dict(outer.get("case_result"))
            except (TypeError, ValueError) as exc:
                raise PilotReassessmentError(
                    f"case result failed validation: {path}"
                ) from exc
            if (
                result.digest != index.get("case_result_sha256")
                or _sha_bytes(raw_bytes) != index.get("bytes_sha256")
                or result.case_id != index.get("case_id")
                or result.variant_id != index.get("variant_id")
                or result.split.value != split.get("split")
                or result.cache_mode.value != index.get("cache_mode")
                or result.status.value != index.get("status")
            ):
                raise PilotReassessmentError(
                    "case result differs from its validated matrix index"
                )
            key = (
                result.split.value,
                result.cache_mode.value,
                result.case_id,
                result.variant_id,
            )
            if key in seen:
                raise PilotReassessmentError("matrix coordinate is duplicated")
            seen.add(key)
            stages = tuple(result.stages)
            current_envelope = (
                outer.get("schema") == ABLATION_RESULT_SCHEMA
            )
            cache_setups = tuple(
                setup
                for stage in stages
                if (
                    setup := extract_symai_cache_setup_telemetry(stage)
                )
                is not None
            )
            invoked_stages = (
                tuple(
                    stage
                    for stage in stages
                    if stage.provenance.effective_identity.get(
                        "graph_invoked"
                    )
                    is True
                )
                if current_envelope
                else stages
            )
            cache_setup_wall_time_ms = sum(
                item.wall_time_ms for item in cache_setups
            )
            cache_setup_model_calls = sum(
                item.model_calls for item in cache_setups
            )
            cache_setup_retries = sum(
                item.retries for item in cache_setups
            )
            wall_time_ms = round(
                sum(item.telemetry.wall_time_ms for item in stages)
                + cache_setup_wall_time_ms,
                6,
            )
            model_calls = (
                sum(item.telemetry.model_calls for item in stages)
                + cache_setup_model_calls
            )
            retries = (
                sum(item.telemetry.retries for item in stages)
                + cache_setup_retries
            )
            proof_processes = sum(
                item.stage in {StageName.HAMMER, StageName.LEANSTRAL}
                for item in invoked_stages
            )
            if current_envelope:
                try:
                    stage_invocations = sum(
                        (
                            symai_backend_invocation_count(item)
                            if item.stage is StageName.SYMAI
                            else int(
                                item.provenance.effective_identity.get(
                                    "graph_invoked"
                                )
                                is True
                            )
                        )
                        for item in stages
                    )
                except ProtocolContractError as exc:
                    raise PilotReassessmentError(
                        "SyMAI backend invocation accounting is invalid"
                    ) from exc
            else:
                stage_invocations = (
                    len(invoked_stages) + len(cache_setups)
                )
            input_data = _mapping(
                _mapping(
                    _mapping(outer.get("job"), "job").get("case"), "job.case"
                ).get("input_data"),
                "job.case.input_data",
            )
            observations.append(
                {
                    "split": result.split.value,
                    "cache_mode": result.cache_mode.value,
                    "case_id": result.case_id,
                    "variant_id": result.variant_id,
                    "expected_class": index.get("expected_class"),
                    "difficulty": input_data.get("difficulty"),
                    "status": result.status.value,
                    "failure_code": (
                        None
                        if result.failure_code is None
                        else result.failure_code.value
                    ),
                    "verified": result.status is OutcomeStatus.VERIFIED,
                    "kernel_accepted": result.kernel_accepted,
                    "recovered_failure_codes": [
                        code.value for code in result.recovered_failure_codes
                    ],
                    "wall_time_ms": wall_time_ms,
                    "model_calls": model_calls,
                    "retries": retries,
                    "cache_setup_count": len(cache_setups),
                    "cache_setup_wall_time_ms": round(
                        cache_setup_wall_time_ms, 6
                    ),
                    "cache_setup_model_calls": cache_setup_model_calls,
                    "cache_setup_retries": cache_setup_retries,
                    "solver_processes": proof_processes,
                    "stage_invocations": stage_invocations,
                    "graph_stage_invocations": len(invoked_stages),
                    "peak_memory_bytes": max(
                        (
                            *(
                                item.telemetry.peak_memory_bytes
                                for item in stages
                            ),
                            *(
                                item.peak_memory_bytes
                                for item in cache_setups
                            ),
                        ),
                        default=0,
                    ),
                    "frontend_stage_invocations": sum(
                        item.stage
                        in {StageName.COMPILER, StageName.SPACY, StageName.SYMAI}
                        for item in invoked_stages
                    ),
                    "proof_stage_invocations": sum(
                        item.stage
                        in {
                            StageName.HAMMER,
                            StageName.LEANSTRAL,
                            StageName.KERNEL,
                        }
                        for item in invoked_stages
                    ),
                    "case_result_sha256": result.digest,
                }
            )
    if len(observations) != EXPECTED_COORDINATE_COUNT:
        raise PilotReassessmentError("matrix observation set is incomplete")
    expected = {
        (split, cache, case_id, variant)
        for split in _SELECTION_SPLITS
        for cache in _CACHE_MODES
        for case_id in {
            str(item["case_id"])
            for item in observations
            if item["split"] == split
        }
        for variant in ALL_VARIANT_IDS
    }
    if seen != expected:
        raise PilotReassessmentError("matrix coordinate identities are incomplete")
    return observations


def _semantic_quality_evidence(
    root: Path,
    *,
    layout: ReassessmentRunLayout,
    benchmark_root: str | Path,
    matrix_observations: Sequence[Mapping[str, object]],
) -> tuple[
    dict[str, Mapping[str, object]] | None,
    dict[str, object] | None,
]:
    """Load optional semantic evidence only through its immutable receipt graph."""

    report_path = _rooted(root, layout.frontend_report)
    index_path = _rooted(root, layout.frontend_receipt_index)
    receipt_directory = _rooted(root, layout.frontend_receipt_directory)
    semantic_targets = (
        report_path,
        index_path,
        receipt_directory,
    )
    if layout.run_id != PILOT_REASSESSMENT_RUN_ID:
        reference_root = _fresh_reference_root(root, layout)
        for target in semantic_targets:
            _assert_no_symlink_chain(
                reference_root,
                target,
                "front-end semantic artifact",
            )
    if not any(path.exists() for path in semantic_targets):
        return None, None
    try:
        from .frontend_report import (
            FRONTEND_REPORT_SCHEMA,
            FrontendReportError,
            load_frontend_report,
        )
        from .semantic_reassessment import (
            SEMANTIC_RECEIPT_INDEX_SCHEMA,
            SemanticReassessmentError,
            validate_semantic_reassessment_from_matrix,
        )

        index = validate_semantic_reassessment_from_matrix(
            repository_root=root,
            run_id=layout.run_id,
            benchmark_root=benchmark_root,
        )
        index_value, index_raw = _read_canonical(
            index_path,
            "semantic receipt index",
        )
        raw_value, report_raw = _read_canonical(
            report_path,
            "front-end semantic report",
        )
        report = load_frontend_report(report_path)
    except (
        FrontendReportError,
        PilotReassessmentError,
        SemanticReassessmentError,
    ) as exc:
        raise PilotReassessmentError(
            "front-end semantic receipt graph failed source validation"
        ) from exc
    if (
        index != index_value
        or index.get("schema") != SEMANTIC_RECEIPT_INDEX_SCHEMA
        or index.get("run_id") != layout.run_id
        or report != raw_value
        or report.get("schema") != FRONTEND_REPORT_SCHEMA
        or report.get("run_id") != layout.run_id
        or report.get("protocol_sha256") != DEFAULT_PROTOCOL_SHA256
        or report.get("registry_sha256") != VARIANT_REGISTRY_SHA256
    ):
        raise PilotReassessmentError(
            "front-end semantic report identity differs from this run"
        )

    matrix_receipts = {
        (
            str(item["split"]),
            str(item["cache_mode"]),
            str(item["variant_id"]),
            str(item["case_id"]),
        ): str(item["case_result_sha256"])
        for item in matrix_observations
    }
    rows_by_variant: dict[str, list[Mapping[str, object]]] = {}
    for raw_row in _array(report.get("observations"), "frontend.observations"):
        row = _mapping(raw_row, "frontend.observations[]")
        coordinate = (
            str(row["split"]),
            str(row["cache_mode"]),
            str(row["variant_id"]),
            str(row["case_id"]),
        )
        if (
            coordinate not in matrix_receipts
            or row.get("source_receipt_sha256")
            != matrix_receipts[coordinate]
        ):
            raise PilotReassessmentError(
                "front-end semantic receipt is not bound to the matrix"
            )
        rows_by_variant.setdefault(str(row["variant_id"]), []).append(row)

    quality: dict[str, Mapping[str, object]] = {}
    for variant_id, representative in _FRONTEND_REPRESENTATIVE.items():
        rows = rows_by_variant.get(representative, [])
        measured = [
            row
            for row in rows
            if row.get("status")
            not in {"unavailable", "infrastructure_failure"}
        ]
        receipts = [
            str(row["semantic_validator_receipt_sha256"])
            for row in measured
            if isinstance(row.get("semantic_validator_receipt_sha256"), str)
        ]
        successes = sum(
            bool(row.get("normalized_ir_exact_match"))
            or bool(row.get("deterministic_semantic_equivalence"))
            for row in measured
        )
        complete = len(rows) == 40 and len(measured) == 40 and len(receipts) == 40
        quality[variant_id] = {
            "representative_variant_id": representative,
            "observation_count": len(measured),
            "rate": _rate(successes, len(measured)),
            "complete": complete,
            "validator_receipt_set_sha256": (
                _sha(sorted(receipts)) if receipts else None
            ),
        }
    all_rows = [
        row for rows in rows_by_variant.values() for row in rows
    ]
    all_measured = [
        row
        for row in all_rows
        if row.get("status")
        not in {"unavailable", "infrastructure_failure"}
    ]
    all_successes = sum(
        bool(row.get("normalized_ir_exact_match"))
        or bool(row.get("deterministic_semantic_equivalence"))
        for row in all_measured
    )
    receipt_references = [
        dict(
            _mapping(
                item,
                "semantic receipt index.receipts[]",
            )
        )
        for item in _array(
            index.get("receipts"),
            "semantic receipt index.receipts",
        )
    ]
    if layout.run_id == PILOT_REASSESSMENT_RUN_ID:
        report_reference = layout.frontend_report.as_posix()
        index_reference = layout.frontend_receipt_index.as_posix()
        directory_reference = layout.frontend_receipt_directory.as_posix()
    else:
        report_reference = _fresh_artifact_reference(
            report_path,
            repository=root,
            layout=layout,
            field="front-end semantic report",
            expected_kind="file",
        )
        index_reference = _fresh_artifact_reference(
            index_path,
            repository=root,
            layout=layout,
            field="semantic receipt index",
            expected_kind="file",
        )
        directory_reference = _fresh_artifact_reference(
            receipt_directory,
            repository=root,
            layout=layout,
            field="semantic receipt directory",
            expected_kind="directory",
        )
    return quality, {
        "kind": "independent_frontend_semantic_receipt_graph",
        "path": report_reference,
        "schema": FRONTEND_REPORT_SCHEMA,
        "bytes_sha256": _sha_bytes(report_raw),
        "semantic_sha256": report["artifact_sha256"],
        "receipt_index": {
            "path": index_reference,
            "schema": SEMANTIC_RECEIPT_INDEX_SCHEMA,
            "bytes_sha256": _sha_bytes(index_raw),
            "artifact_sha256": index["artifact_sha256"],
        },
        "receipt_directory": directory_reference,
        "receipt_reference_count": len(receipt_references),
        "receipt_reference_set_sha256": _sha(
            sorted(_sha(item) for item in receipt_references)
        ),
        "receipt_references": receipt_references,
        "run_id": layout.run_id,
        "source_validated": True,
        "semantic_quality_observation_count": len(all_measured),
        "semantic_quality_rate": _rate(all_successes, len(all_measured)),
    }


def _candidate_metrics(
    observations: Sequence[Mapping[str, object]],
    *,
    semantic_quality: Mapping[str, Mapping[str, object]] | None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    by_variant = {
        variant_id: [
            item for item in observations if item["variant_id"] == variant_id
        ]
        for variant_id in ALL_VARIANT_IDS
    }
    baseline = {
        (str(item["split"]), str(item["cache_mode"]), str(item["case_id"])): item
        for item in by_variant["A0"]
    }
    baseline_latencies = [float(item["wall_time_ms"]) for item in baseline.values()]
    baseline_p95 = _percentile(baseline_latencies, 0.95)
    baseline_model_calls = sum(int(item["model_calls"]) for item in baseline.values())
    baseline_cache_setup_count = sum(
        int(item["cache_setup_count"]) for item in baseline.values()
    )
    baseline_cache_setup_wall_time_ms = sum(
        float(item["cache_setup_wall_time_ms"])
        for item in baseline.values()
    )
    baseline_cache_setup_model_calls = sum(
        int(item["cache_setup_model_calls"])
        for item in baseline.values()
    )
    baseline_verified = sum(bool(item["verified"]) for item in baseline.values())
    complete_quality_rates = [
        float(item["rate"])
        for item in (semantic_quality or {}).values()
        if item.get("complete") is True and item.get("rate") is not None
    ]
    best_quality_rate = (
        max(complete_quality_rates) if complete_quality_rates else None
    )

    candidates: list[dict[str, object]] = []
    for variant_id in _CANDIDATE_IDS:
        rows = by_variant[variant_id]
        if len(rows) != 40:
            raise PilotReassessmentError(
                f"{variant_id} does not have 40 paired observations"
            )
        status_counts = Counter(str(item["status"]) for item in rows)
        failure_counts = Counter(
            str(item["failure_code"])
            for item in rows
            if item["failure_code"] is not None
        )
        recovered_failure_counts = Counter(
            str(code)
            for item in rows
            for code in item["recovered_failure_codes"]
        )
        verified = sum(bool(item["verified"]) for item in rows)
        hard_rows = [item for item in rows if item["difficulty"] == "hard"]
        paired_values: list[int] = []
        baseline_regressions = 0
        receipt_pairs: list[dict[str, str]] = []
        for row in rows:
            key = (
                str(row["split"]),
                str(row["cache_mode"]),
                str(row["case_id"]),
            )
            base = baseline.get(key)
            if base is None:
                raise PilotReassessmentError(
                    f"{variant_id} has an unpaired coordinate"
                )
            paired_values.append(
                int(bool(row["verified"])) - int(bool(base["verified"]))
            )
            baseline_regressions += bool(base["verified"]) and not bool(
                row["verified"]
            )
            receipt_pairs.append(
                {
                    "baseline": str(base["case_result_sha256"]),
                    "candidate": str(row["case_result_sha256"]),
                }
            )
        paired_mean, paired_low, paired_high = _paired_interval(paired_values)
        latencies = [float(item["wall_time_ms"]) for item in rows]
        p95 = _percentile(latencies, 0.95)
        total_model_calls = sum(int(item["model_calls"]) for item in rows)
        cache_setup_count = sum(
            int(item["cache_setup_count"]) for item in rows
        )
        cache_setup_wall_time_ms = sum(
            float(item["cache_setup_wall_time_ms"]) for item in rows
        )
        cache_setup_model_calls = sum(
            int(item["cache_setup_model_calls"]) for item in rows
        )
        cache_setup_retries = sum(
            int(item["cache_setup_retries"]) for item in rows
        )
        latency_reduction = (
            0.0
            if baseline_p95 == 0 and p95 == 0
            else -1.0
            if baseline_p95 == 0
            else max(-1.0, min(1.0, (baseline_p95 - p95) / baseline_p95))
        )
        model_reduction = (
            0.0
            if baseline_model_calls == 0 and total_model_calls == 0
            else -1.0
            if baseline_model_calls == 0
            else max(
                -1.0,
                min(
                    1.0,
                    (baseline_model_calls - total_model_calls)
                    / baseline_model_calls,
                ),
            )
        )
        hard_verified = sum(bool(item["verified"]) for item in hard_rows)
        baseline_hard = [
            baseline[
                (
                    str(item["split"]),
                    str(item["cache_mode"]),
                    str(item["case_id"]),
                )
            ]
            for item in hard_rows
        ]
        baseline_hard_verified = sum(
            bool(item["verified"]) for item in baseline_hard
        )
        hard_gain = (
            0.0
            if not hard_rows
            else (hard_verified - baseline_hard_verified) / len(hard_rows)
        )
        quality = (
            None
            if semantic_quality is None
            else semantic_quality.get(variant_id)
        )
        quality_complete = quality is not None and quality.get("complete") is True
        quality_rate = (
            float(quality["rate"])
            if quality_complete and quality.get("rate") is not None
            else None
        )
        quality_count = (
            int(quality["observation_count"])
            if quality is not None
            else 0
        )
        quality_gap = (
            0.0
            if semantic_quality is None
            else 1.0
            if quality_rate is None or best_quality_rate is None
            else max(0.0, min(1.0, best_quality_rate - quality_rate))
        )
        observation = CandidateGateObservation(
            invalid_control_verified_count=0,
            paired_interval_low=paired_low,
            hard_case_verified_gain=hard_gain,
            quality_gap_from_best=quality_gap,
            p95_latency_reduction=latency_reduction,
            model_usage_reduction=model_reduction,
            baseline_solved_regression_rate=(
                0.0
                if baseline_verified == 0
                else baseline_regressions / baseline_verified
            ),
            unexplained_baseline_regressions=baseline_regressions,
            all_successes_kernel_bound_and_replayable=all(
                not bool(item["verified"]) or bool(item["kernel_accepted"])
                for item in rows
            ),
            infrastructure_failure_count=status_counts[
                OutcomeStatus.INFRASTRUCTURE_FAILURE.value
            ],
        )
        gate = evaluate_candidate_gate(observation, protocol=DEFAULT_PROTOCOL)
        reasons = list(gate.reasons)
        if verified == 0:
            reasons.append("no kernel-verified candidate success")
        if not quality_complete:
            reasons.append("independent semantic-quality evidence unavailable")
        elif quality_rate is None or quality_rate <= 0.0:
            # Upstream calibration rejects incompatible producer contracts.
            # Even after that check, a relative near-best comparison is
            # vacuous when every measured front end has zero validated
            # successes. Receipt completeness alone cannot create eligibility.
            reasons.append(
                "no independently validated semantic-quality success"
            )
        eligible = gate.status is GateStatus.PASSED and not reasons
        candidates.append(
            {
                "variant_id": variant_id,
                "configuration_sha256": VARIANT_REGISTRY[variant_id].digest,
                "receipt_count": len(rows),
                "receipt_set_sha256": _sha(
                    sorted(str(item["case_result_sha256"]) for item in rows)
                ),
                "status_counts": dict(sorted(status_counts.items())),
                "failure_counts": dict(sorted(failure_counts.items())),
                **(
                    {}
                    if not recovered_failure_counts
                    else {
                        "recovered_failure_count": sum(
                            recovered_failure_counts.values()
                        ),
                        "recovered_failure_counts": dict(
                            sorted(recovered_failure_counts.items())
                        ),
                    }
                ),
                "efficacy": {
                    "measured_count": len(rows),
                    "kernel_verified_count": verified,
                    "kernel_verified_rate": _rate(verified, len(rows)),
                    "hard_case_count": len(hard_rows),
                    "hard_case_verified_gain": hard_gain,
                    "semantic_quality_observation_count": quality_count,
                    "semantic_quality_rate": quality_rate,
                    "semantic_quality_missing_reason": (
                        None
                        if quality_complete
                        else (
                            "matrix execution has no independent reviewed "
                            "semantic-validator receipt"
                        )
                    ),
                    **(
                        {}
                        if semantic_quality is None
                        else {
                            "semantic_quality_representative_variant_id": (
                                _FRONTEND_REPRESENTATIVE[variant_id]
                            ),
                            "semantic_validator_receipt_set_sha256": (
                                None
                                if quality is None
                                else quality.get(
                                    "validator_receipt_set_sha256"
                                )
                            ),
                        }
                    ),
                },
                "cost": {
                    "coordinate_count": len(rows),
                    "wall_time_ms_total": round(sum(latencies), 6),
                    "wall_time_ms_mean_per_coordinate": round(
                        sum(latencies) / len(rows), 6
                    ),
                    "wall_time_ms_p95_per_coordinate": p95,
                    "model_calls": total_model_calls,
                    "solver_processes": sum(
                        int(item["solver_processes"]) for item in rows
                    ),
                    "retries": sum(int(item["retries"]) for item in rows),
                    "stage_invocations": sum(
                        int(item["stage_invocations"]) for item in rows
                    ),
                    "peak_memory_bytes_max": max(
                        int(item["peak_memory_bytes"]) for item in rows
                    ),
                    "latency_reduction_vs_a0": latency_reduction,
                    "model_usage_reduction_vs_a0": model_reduction,
                    **(
                        {}
                        if not cache_setup_count
                        else {
                            "cache_setup_invocations": cache_setup_count,
                            "cache_setup_wall_time_ms_total": round(
                                cache_setup_wall_time_ms, 6
                            ),
                            "cache_setup_model_calls": (
                                cache_setup_model_calls
                            ),
                            "cache_setup_retries": cache_setup_retries,
                            "graph_stage_invocations": sum(
                                int(item["graph_stage_invocations"])
                                for item in rows
                            ),
                            "measured_wall_time_ms_total": round(
                                sum(latencies)
                                - cache_setup_wall_time_ms,
                                6,
                            ),
                            "measured_model_calls": (
                                total_model_calls
                                - cache_setup_model_calls
                            ),
                        }
                    ),
                },
                "statistics": {
                    "paired_count": len(paired_values),
                    "paired_verified_delta_mean": paired_mean,
                    "paired_verified_delta_interval_95": [
                        paired_low,
                        paired_high,
                    ],
                    "baseline_solved_count": baseline_verified,
                    "baseline_solved_regression_count": baseline_regressions,
                    "baseline_solved_regression_rate": (
                        None
                        if baseline_verified == 0
                        else baseline_regressions / baseline_verified
                    ),
                    "receipt_pairs_sha256": _sha(receipt_pairs),
                },
                "complexity": {
                    "registered_stage_count": len(
                        VARIANT_REGISTRY[variant_id].stages
                    ),
                    "registered_stages": [
                        item.value for item in VARIANT_REGISTRY[variant_id].stages
                    ],
                },
                "materiality_gate": {
                    "status": gate.status.value,
                    "inputs": {
                        name: getattr(observation, name)
                        for name in observation.__dataclass_fields__
                    },
                    "reasons": list(gate.reasons),
                },
                "eligible": eligible,
                "ineligibility_reasons": list(dict.fromkeys(reasons)),
            }
        )
    baseline_summary = {
        "variant_id": "A0",
        "receipt_count": len(baseline),
        "kernel_verified_count": baseline_verified,
        "kernel_verified_rate": _rate(baseline_verified, len(baseline)),
        "wall_time_ms_total": round(sum(baseline_latencies), 6),
        "wall_time_ms_mean_per_coordinate": round(
            sum(baseline_latencies) / len(baseline_latencies), 6
        ),
        "wall_time_ms_p95_per_coordinate": baseline_p95,
        "model_calls": baseline_model_calls,
        "receipt_set_sha256": _sha(
            sorted(str(item["case_result_sha256"]) for item in baseline.values())
        ),
    }
    if baseline_cache_setup_count:
        baseline_summary.update(
            {
                "cache_setup_invocations": baseline_cache_setup_count,
                "cache_setup_wall_time_ms_total": round(
                    baseline_cache_setup_wall_time_ms, 6
                ),
                "cache_setup_model_calls": (
                    baseline_cache_setup_model_calls
                ),
                "measured_wall_time_ms_total": round(
                    sum(baseline_latencies)
                    - baseline_cache_setup_wall_time_ms,
                    6,
                ),
                "measured_model_calls": (
                    baseline_model_calls
                    - baseline_cache_setup_model_calls
                ),
            }
        )
    baseline_recovered_failures = Counter(
        str(code)
        for item in baseline.values()
        for code in item["recovered_failure_codes"]
    )
    if baseline_recovered_failures:
        baseline_summary["recovered_failure_count"] = sum(
            baseline_recovered_failures.values()
        )
        baseline_summary["recovered_failure_counts"] = dict(
            sorted(baseline_recovered_failures.items())
        )
    return candidates, baseline_summary


def _candidate_failure_total(candidate: Mapping[str, object]) -> int:
    """Return unresolved plus kernel-recovered reliability failures."""

    unresolved = _mapping(candidate["failure_counts"], "failures")
    recovered = _mapping(
        candidate.get("recovered_failure_counts", {}),
        "recovered failures",
    )
    return sum(int(value) for value in unresolved.values()) + sum(
        int(value) for value in recovered.values()
    )


def _dominates(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    left_efficacy = _mapping(left["efficacy"], "candidate.efficacy")
    right_efficacy = _mapping(right["efficacy"], "candidate.efficacy")
    left_cost = _mapping(left["cost"], "candidate.cost")
    right_cost = _mapping(right["cost"], "candidate.cost")
    comparisons = (
        float(left_efficacy["kernel_verified_rate"])
        >= float(right_efficacy["kernel_verified_rate"]),
        float(left_cost["wall_time_ms_p95_per_coordinate"])
        <= float(right_cost["wall_time_ms_p95_per_coordinate"]),
        int(left_cost["model_calls"]) <= int(right_cost["model_calls"]),
        int(left_cost["solver_processes"]) <= int(right_cost["solver_processes"]),
        int(left_cost["stage_invocations"]) <= int(right_cost["stage_invocations"]),
        _candidate_failure_total(left) <= _candidate_failure_total(right),
    )
    strict = (
        float(left_efficacy["kernel_verified_rate"])
        > float(right_efficacy["kernel_verified_rate"])
        or float(left_cost["wall_time_ms_p95_per_coordinate"])
        < float(right_cost["wall_time_ms_p95_per_coordinate"])
        or int(left_cost["model_calls"]) < int(right_cost["model_calls"])
        or int(left_cost["solver_processes"]) < int(right_cost["solver_processes"])
        or int(left_cost["stage_invocations"]) < int(right_cost["stage_invocations"])
        or _candidate_failure_total(left) < _candidate_failure_total(right)
    )
    return all(comparisons) and strict


def _pareto(candidates: Sequence[Mapping[str, object]]) -> dict[str, object]:
    observed_frontier = sorted(
        str(candidate["variant_id"])
        for candidate in candidates
        if not any(
            other["variant_id"] != candidate["variant_id"]
            and _dominates(other, candidate)
            for other in candidates
        )
    )
    eligible = [item for item in candidates if item["eligible"] is True]
    frontier = sorted(
        str(candidate["variant_id"])
        for candidate in eligible
        if not any(
            other["variant_id"] != candidate["variant_id"]
            and _dominates(other, candidate)
            for other in eligible
        )
    )
    return {
        "objectives": [
            {"metric": "kernel_verified_rate", "direction": "maximize"},
            {
                "metric": "wall_time_ms_p95_per_coordinate",
                "direction": "minimize",
            },
            {"metric": "model_calls", "direction": "minimize"},
            {"metric": "solver_processes", "direction": "minimize"},
            {"metric": "stage_invocations", "direction": "minimize"},
            {"metric": "typed_failure_count", "direction": "minimize"},
        ],
        "candidate_ids": list(_CANDIDATE_IDS),
        "observed_nondominated_candidate_ids": observed_frontier,
        "eligible_candidate_ids": sorted(
            str(item["variant_id"]) for item in eligible
        ),
        "eligible_nondominated_candidate_ids": frontier,
        "safety_is_a_hard_constraint": True,
        "semantic_quality_is_a_hard_constraint": True,
        "ranking_applied": False,
        "truncation_applied": False,
    }


def _freeze_inputs(
    matrix: Mapping[str, object], *, run_id: str
) -> dict[str, object]:
    selection = _mapping(matrix["selection_inputs"], "matrix.selection_inputs")
    source = _mapping(matrix["source_binding"], "matrix.source_binding")
    snapshots: dict[str, object] = {
        "prompts": {
            "frozen": selection["prompts_frozen"],
            "sha256": selection["prompts_sha256"],
        },
        "policies": {
            "frozen": selection["policies_frozen"],
            "sha256": selection["policies_sha256"],
        },
        "model_identities": {
            "frozen": selection["model_identities_frozen"],
            "sha256": selection["repaired_model_identities_sha256"],
        },
        "cache_policy": {
            "frozen": True,
            "isolated_by_run_variant_split_and_mode": True,
            "cache_modes": list(_CACHE_MODES),
            "run_id": run_id,
        },
        "resource_policy": {
            "frozen": True,
            "sha256": selection["resource_policy_sha256"],
        },
        "thresholds": {
            "frozen": selection["thresholds_frozen"],
            "sha256": selection["thresholds_sha256"],
            "protocol": DEFAULT_PROTOCOL.thresholds.to_dict(),
        },
        "source": {
            "frozen": True,
            "commit": source["source_commit"],
            "recursive_gitlinks_sha256": source["recursive_gitlinks_sha256"],
            "worktree_receipt_sha256": source["worktree_receipt_sha256"],
        },
    }
    if run_id != PUBLISHED_REASSESSMENT_RUN_ID:
        snapshots["environment"] = {
            "frozen": True,
            "sha256": matrix["environment_sha256"],
        }
    return {
        kind: {**_mapping(value, f"freeze.{kind}"), "binding_sha256": _sha(value)}
        for kind, value in snapshots.items()
    }


def build_pilot_reassessment_report(
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    run_id: str = PILOT_REASSESSMENT_RUN_ID,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> dict[str, object]:
    """Recompute the HSSL-G140 decision from the complete persisted matrix."""

    root = _resolve_root(repository_root)
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ValueError as exc:
        raise PilotReassessmentError("reassessment run_id is invalid") from exc
    try:
        matrix = validate_reassessment_matrix(
            repository_root=root,
            run_id=run_id,
            benchmark_root=benchmark_root,
            output_root=layout.matrix_root,
            snapshot_path=layout.matrix_snapshot,
        )
    except MatrixReassessmentError as exc:
        raise PilotReassessmentError(
            "reassessment matrix failed source validation"
        ) from exc
    observations = _result_observations(
        root,
        matrix,
        matrix_index=layout.matrix_index,
        run_id=run_id,
    )
    semantic_quality, semantic_source_binding = _semantic_quality_evidence(
        root,
        layout=layout,
        benchmark_root=benchmark_root,
        matrix_observations=observations,
    )
    candidates, baseline = _candidate_metrics(
        observations,
        semantic_quality=semantic_quality,
    )
    pareto = _pareto(candidates)
    selected = list(pareto["eligible_nondominated_candidate_ids"])
    if len(selected) > DEFAULT_PROTOCOL.thresholds.shortlist_candidate_max:
        selected = []
        over_limit = True
    else:
        over_limit = False

    matrix_path = _rooted(root, layout.matrix_index)
    _, matrix_bytes = _read_canonical(matrix_path, "matrix index")
    totals = _mapping(matrix["totals"], "matrix.totals")
    safety_source = _mapping(matrix["safety"], "matrix.safety")
    status_counts = Counter(str(item["status"]) for item in observations)
    frontend_stage_count = sum(
        int(item["frontend_stage_invocations"]) for item in observations
    )
    proof_stage_count = sum(
        int(item["proof_stage_invocations"]) for item in observations
    )
    measured_efficacy = [
        item
        for item in observations
        if item["status"]
        not in {
            OutcomeStatus.UNAVAILABLE.value,
            OutcomeStatus.INFRASTRUCTURE_FAILURE.value,
            OutcomeStatus.EXCLUDED.value,
        }
    ]
    verified = sum(bool(item["verified"]) for item in measured_efficacy)
    semantic_complete = (
        semantic_quality is not None
        and bool(semantic_quality)
        and all(
            item.get("complete") is True
            for item in semantic_quality.values()
        )
    )
    model_calls = sum(int(item["model_calls"]) for item in observations)
    retries = sum(int(item["retries"]) for item in observations)
    cache_setup_count = sum(
        int(item["cache_setup_count"]) for item in observations
    )
    cache_setup_wall_time_ms = sum(
        float(item["cache_setup_wall_time_ms"])
        for item in observations
    )
    cache_setup_model_calls = sum(
        int(item["cache_setup_model_calls"])
        for item in observations
    )
    cache_setup_retries = sum(
        int(item["cache_setup_retries"]) for item in observations
    )
    solver_processes = sum(int(item["solver_processes"]) for item in observations)
    wall_time_ms = sum(float(item["wall_time_ms"]) for item in observations)
    recovered_failure_counts = Counter(
        str(code)
        for item in observations
        for code in item["recovered_failure_codes"]
    )
    freeze_inputs = _freeze_inputs(matrix, run_id=run_id)

    eligible = (
        bool(selected)
        and not over_limit
        and int(safety_source["invalid_control_verified_count"]) == 0
    )
    status = "complete" if eligible else "incomplete"
    remediation: list[dict[str, object]] = []
    if not eligible:
        candidate_by_id = {
            str(item["variant_id"]): item for item in candidates
        }

        def has_unresolved_failure(
            variant_ids: Sequence[str], prefix: str
        ) -> bool:
            return any(
                any(
                    str(code).startswith(prefix) and int(count) > 0
                    for code, count in _mapping(
                        candidate_by_id[variant_id]["failure_counts"],
                        f"{variant_id}.failure_counts",
                    ).items()
                )
                for variant_id in variant_ids
            )

        if verified == 0:
            remediation.append(
                {
                    "priority": 1,
                    "scope": ["A1", "A2"],
                    "action": (
                        "repair reviewed-obligation and proof-candidate "
                        "generation until the independent kernel can observe "
                        "eligible successes"
                    ),
                    "rerun_required": True,
                }
            )
        if has_unresolved_failure(("A3",), "leanstral_"):
            remediation.append(
                {
                    "priority": 2,
                    "scope": ["A3"],
                    "action": (
                        "supply the frozen nonempty Leanstral prompt and "
                        "context capsule at the registered fallback boundary"
                    ),
                    "rerun_required": True,
                }
            )
        if has_unresolved_failure(_CANDIDATE_IDS[3:], "symai_"):
            remediation.append(
                {
                    "priority": 3,
                    "scope": list(_CANDIDATE_IDS[3:]),
                    "action": (
                        "repair the frozen SyMAI router invocation without arm "
                        "substitution, fallback, or selection-input changes"
                    ),
                    "rerun_required": True,
                }
            )
        zero_quality_candidates: list[str] = []
        if not semantic_complete:
            remediation.append(
                {
                    "priority": 4,
                    "scope": list(_CANDIDATE_IDS),
                    "action": (
                        "publish independently reviewed semantic-quality "
                        "receipts and rerun this exact source-bound gate"
                    ),
                    "rerun_required": True,
                }
            )
        else:
            zero_quality_candidates = [
                variant_id
                for variant_id in _CANDIDATE_IDS
                if (
                    semantic_quality[variant_id].get("rate") is None
                    or float(semantic_quality[variant_id]["rate"]) <= 0.0
                )
            ]
        if zero_quality_candidates:
            remediation.append(
                {
                    "priority": 4,
                    "scope": zero_quality_candidates,
                    "action": (
                        "repair front-end semantic reconstruction until "
                        "independently reviewed receipts record nonzero "
                        "semantic correctness without using reviewed proof "
                        "obligations as front-end input"
                    ),
                    "rerun_required": True,
                }
            )
    matrix_reference = (
        layout.matrix_index.as_posix()
        if run_id == PILOT_REASSESSMENT_RUN_ID
        else _fresh_artifact_reference(
            matrix_path,
            repository=root,
            layout=layout,
            field="pilot matrix source",
            expected_kind="file",
        )
    )
    source_binding = {
        "kind": "complete_reassessment_matrix",
        "path": matrix_reference,
        "schema": MATRIX_INDEX_SCHEMA,
        "bytes_sha256": _sha_bytes(matrix_bytes),
        "semantic_sha256": matrix["artifact_sha256"],
        "source_validated": True,
        "case_result_receipt_count": len(observations),
        "case_result_receipt_set_sha256": _sha(
            sorted(str(item["case_result_sha256"]) for item in observations)
        ),
    }
    deep_freeze: dict[str, object] = {
        "frozen": True,
        "tuning_permitted": False,
        "selection_splits": list(_SELECTION_SPLITS),
        "holdout_outcomes_permitted": False,
        "post_freeze_ranking_permitted": False,
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "registry_sha256": VARIANT_REGISTRY_SHA256,
        "inputs": freeze_inputs,
        "source_binding_sha256": _sha(source_binding),
        **(
            {}
            if semantic_source_binding is None
            else {
                "semantic_source_binding_sha256": _sha(
                    semantic_source_binding
                )
            }
        ),
        "selected_configurations": [
            {
                "variant_id": variant_id,
                "configuration_sha256": VARIANT_REGISTRY[variant_id].digest,
            }
            for variant_id in selected
        ],
        "freeze_sha256": "",
    }
    deep_freeze["freeze_sha256"] = _sha(
        {
            key: value
            for key, value in deep_freeze.items()
            if key != "freeze_sha256"
        }
    )
    report: dict[str, object] = {
        "schema": PILOT_REASSESSMENT_SCHEMA,
        "evidence": "HSSLEV1409B38",
        "evidence_statement": HSSLEV1409B38(),
        "benchmark_id": BENCHMARK_ID,
        "run_id": run_id,
        "status": status,
        "frozen": True,
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "registry_sha256": VARIANT_REGISTRY_SHA256,
        "source_binding": source_binding,
        **(
            {}
            if semantic_source_binding is None
            else {"semantic_source_binding": semantic_source_binding}
        ),
        "completeness": {
            "source_validated": True,
            "matrix_status": matrix["status"],
            "coordinate_count": len(observations),
            "expected_coordinate_count": EXPECTED_COORDINATE_COUNT,
            "case_count": totals["case_count"],
            "variant_ids": list(ALL_VARIANT_IDS),
            "splits": list(_SELECTION_SPLITS),
            "cache_modes": list(_CACHE_MODES),
            "status_counts": dict(sorted(status_counts.items())),
            "all_coordinates_terminal": len(observations)
            == EXPECTED_COORDINATE_COUNT,
            "typed_missingness_retained": True,
        },
        "reports": {
            "front_end": {
                "source_receipt_count": len(observations),
                "stage_invocation_count": frontend_stage_count,
                "model_calls": model_calls,
                **(
                    {}
                    if not cache_setup_count
                    else {
                        "cache_setup_invocations": cache_setup_count,
                        "cache_setup_model_calls": (
                            cache_setup_model_calls
                        ),
                    }
                ),
                "semantic_quality_observation_count": (
                    0
                    if semantic_source_binding is None
                    else semantic_source_binding[
                        "semantic_quality_observation_count"
                    ]
                ),
                "semantic_quality_rate": (
                    None
                    if semantic_source_binding is None
                    else semantic_source_binding["semantic_quality_rate"]
                ),
                "missing_reason": (
                    (
                        "no independent reviewed semantic-validator receipt "
                        "was published by the unchanged matrix"
                    )
                    if semantic_source_binding is None
                    else None
                ),
            },
            "proof": {
                "efficacy_observation_count": len(measured_efficacy),
                "kernel_verified_count": verified,
                "kernel_verified_rate": _rate(
                    verified, len(measured_efficacy)
                ),
                "proof_stage_invocation_count": proof_stage_count,
                "kernel_invocation_count": totals["kernel_invoked_count"],
                "kernel_acceptance_count": totals["kernel_accepted_count"],
                **(
                    {}
                    if not recovered_failure_counts
                    else {
                        "recovered_failure_count": sum(
                            recovered_failure_counts.values()
                        ),
                        "recovered_failure_counts": dict(
                            sorted(recovered_failure_counts.items())
                        ),
                        "reliability_status": "degraded_recovered",
                    }
                ),
            },
            "efficiency": {
                "coordinate_count": len(observations),
                "wall_time_ms_total": round(wall_time_ms, 6),
                "wall_time_ms_mean_per_coordinate": round(
                    wall_time_ms / len(observations), 6
                ),
                "model_calls": model_calls,
                "solver_processes": solver_processes,
                "retries": retries,
                "stage_invocations": (
                    sum(
                        int(item["stage_invocations"])
                        for item in observations
                    )
                    if cache_setup_count
                    else totals["invoked_stage_count"]
                ),
                "resource_leases": totals["resource_lease_count"],
                "missingness_synthesized_as_zero_cost": False,
                **(
                    {}
                    if not cache_setup_count
                    else {
                        "cache_setup_invocations": cache_setup_count,
                        "cache_setup_wall_time_ms_total": round(
                            cache_setup_wall_time_ms, 6
                        ),
                        "cache_setup_model_calls": (
                            cache_setup_model_calls
                        ),
                        "cache_setup_retries": cache_setup_retries,
                        "graph_stage_invocations": sum(
                            int(item["graph_stage_invocations"])
                            for item in observations
                        ),
                        "measured_wall_time_ms_total": round(
                            wall_time_ms - cache_setup_wall_time_ms,
                            6,
                        ),
                        "measured_model_calls": (
                            model_calls - cache_setup_model_calls
                        ),
                        "measured_retries": (
                            retries - cache_setup_retries
                        ),
                    }
                ),
            },
            "statistics": {
                "baseline": baseline,
                "candidate_count": len(candidates),
                "paired_observations_per_candidate": 40,
                "confidence_level": DEFAULT_PROTOCOL.thresholds.confidence_level,
                "all_candidate_pairs_source_bound": True,
            },
            "safety": {
                "invalid_control_coordinate_count": safety_source[
                    "invalid_control_coordinate_count"
                ],
                "kernel_verified_invalid_control_false_positive_count": (
                    safety_source["invalid_control_verified_count"]
                ),
                "kernel_verified_invalid_control_false_positive_rate": _rate(
                    int(safety_source["invalid_control_verified_count"]),
                    int(safety_source["invalid_control_coordinate_count"]),
                ),
                "fatal_safety_incident": int(
                    safety_source["invalid_control_verified_count"]
                )
                > DEFAULT_PROTOCOL.thresholds.invalid_control_verified_max,
                "holdout_accessed": safety_source["holdout_accessed"],
                "fallback_used": safety_source["fallback_used"],
                "production_routing_changed": safety_source[
                    "production_routing_changed"
                ],
            },
            "pareto": pareto,
        },
        "candidate_evidence": candidates,
        "shortlist": {
            "status": status,
            "frozen": True,
            "freeze_kind": (
                "exact_nondominated_shortlist"
                if eligible
                else "empty_due_to_no_eligible_candidate"
            ),
            "candidate_max": DEFAULT_PROTOCOL.thresholds.shortlist_candidate_max,
            "selected_variant_ids": selected if eligible else [],
            "selected_count": len(selected) if eligible else 0,
            "nonbaseline_only": True,
            "diagnostic_arms_excluded": ["S1"],
            "baseline_arms_excluded": ["A0"],
            "ranking_applied": False,
            "truncation_applied": False,
            "reason": (
                "complete eligible nondominated frontier frozen"
                if eligible
                else (
                    (
                        "the complete matrix has measured zero proof efficacy "
                        "and no independent semantic-quality evidence; no arm "
                        "passes"
                    )
                    if verified == 0 and semantic_source_binding is None
                    else "no candidate passed every frozen eligibility gate"
                )
            ),
        },
        "holdout": {
            "status": "authorized_unopened" if eligible else "sealed",
            "authorized": eligible,
            "authorization_sha256": None,
            "outcomes_inspected": False,
            "selection_used_holdout": False,
            "tuning_after_access": False,
            "reason": (
                "exact frozen shortlist authorizes paired holdout execution"
                if eligible
                else "no eligible candidate exists; holdout remains sealed"
            ),
        },
        "remediation": remediation,
        "deep_freeze": deep_freeze,
        "decision": {
            "status": status,
            "structurally_valid": True,
            "matrix_complete": True,
            "efficacy_status": (
                "measured_zero" if verified == 0 else "measured_nonzero"
            ),
            "semantic_quality_status": (
                "unavailable"
                if semantic_source_binding is None
                else (
                    "complete"
                    if semantic_complete
                    else "incomplete"
                )
            ),
            "shortlist_status": (
                "frozen_nonempty" if eligible else "frozen_empty"
            ),
            "holdout_authorized": eligible,
            "production_promotion_authorized": False,
            "reason": (
                "source-bound eligible shortlist passed"
                if eligible
                else "no candidate passed every frozen eligibility gate"
            ),
        },
        "artifact_sha256": "",
    }
    if eligible:
        holdout = _mapping(report["holdout"], "holdout")
        holdout["authorization_sha256"] = _sha(
            {
                "run_id": run_id,
                "selected_variant_ids": selected,
                "freeze_sha256": deep_freeze["freeze_sha256"],
                "matrix_sha256": matrix["artifact_sha256"],
            }
        )
    report["artifact_sha256"] = _sha(
        {key: value for key, value in report.items() if key != "artifact_sha256"}
    )
    return report


def validate_pilot_reassessment_report(
    value: object,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    run_id: str = PILOT_REASSESSMENT_RUN_ID,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> dict[str, object]:
    """Reject any artifact that differs from source receipt recomputation."""

    data = dict(_mapping(value, "pilot reassessment report"))
    if data.get("schema") != PILOT_REASSESSMENT_SCHEMA:
        raise PilotReassessmentError("unsupported pilot reassessment schema")
    if data.get("evidence") != "HSSLEV1409B38":
        raise PilotReassessmentError("pilot reassessment evidence marker changed")
    if data.get("evidence_statement") != HSSLEV1409B38():
        raise PilotReassessmentError("pilot reassessment evidence statement changed")
    if data.get("artifact_sha256") != _sha(
        {key: item for key, item in data.items() if key != "artifact_sha256"}
    ):
        raise PilotReassessmentError("pilot reassessment digest changed")
    expected = build_pilot_reassessment_report(
        repository_root=repository_root,
        run_id=run_id,
        benchmark_root=benchmark_root,
    )
    if data != expected:
        raise PilotReassessmentError(
            "pilot reassessment differs from recomputed source evidence"
        )
    return data


def _snapshot(
    report: Mapping[str, object],
    artifact: Path,
    *,
    repository: Path,
    benchmark_root: str | Path,
    captured_on: object | None = None,
) -> dict[str, object]:
    shortlist = _mapping(report["shortlist"], "shortlist")
    decision = _mapping(report["decision"], "decision")
    safety = _mapping(
        _mapping(report["reports"], "reports")["safety"], "reports.safety"
    )
    run_id = str(report["run_id"])
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ValueError as exc:
        raise PilotReassessmentError(
            "pilot snapshot run_id is invalid"
        ) from exc
    artifact_reference = (
        DEFAULT_PILOT_REASSESSMENT_PATH.as_posix()
        if run_id == PILOT_REASSESSMENT_RUN_ID
        else _fresh_artifact_reference(
            artifact,
            repository=repository,
            layout=layout,
            field="pilot snapshot artifact",
            expected_kind="file",
        )
    )
    if run_id == PILOT_REASSESSMENT_RUN_ID:
        notes = [
            "The complete unchanged pilot/development matrix was source-validated.",
            (
                "Zero kernel acceptances are measured efficacy, not missing "
                "or positive evidence."
            ),
            (
                "No eligible arm passed; the shortlist is frozen empty and "
                "holdout remains sealed."
            ),
        ]
    else:
        selected_count = int(shortlist["selected_count"])
        holdout_authorized = bool(decision["holdout_authorized"])
        notes = [
            "The complete unchanged pilot/development matrix was source-validated.",
            (
                "Kernel efficacy and semantic quality remain measured receipt "
                "evidence; missingness is not treated as success."
            ),
            (
                (
                    f"The frozen shortlist contains {selected_count} eligible "
                    f"arm{'s' if selected_count != 1 else ''}; "
                )
                if selected_count
                else "The frozen shortlist contains no eligible arm; "
            )
            + (
                "paired holdout execution is authorized."
                if holdout_authorized
                else "holdout remains sealed."
            ),
        ]
    return {
        "benchmark_script": (
            VALIDATION_COMMAND
            if run_id == PILOT_REASSESSMENT_RUN_ID
            else (
                "python benchmarks/logic_pipeline/report.py --gate "
                f"pilot-shortlist --run-id {run_id} --artifact "
                f"{artifact_reference}"
            )
        ),
        "captured_on": _snapshot_capture_date(run_id, captured_on),
        "notes": notes,
        "results": {
            "schema": PILOT_REASSESSMENT_SNAPSHOT_SCHEMA,
            "evidence": "HSSLEV1409B38",
            "run_id": run_id,
            "status": report["status"],
            "artifact": {
                "path": artifact_reference,
                "bytes_sha256": _sha_bytes(artifact.read_bytes()),
                "semantic_sha256": report["artifact_sha256"],
            },
            "matrix": dict(_mapping(report["source_binding"], "source_binding")),
            "shortlist": {
                "frozen": shortlist["frozen"],
                "selected_variant_ids": shortlist["selected_variant_ids"],
                "selected_count": shortlist["selected_count"],
                "reason": shortlist["reason"],
            },
            "holdout_authorized": decision["holdout_authorized"],
            "production_promotion_authorized": decision[
                "production_promotion_authorized"
            ],
            "safety": dict(safety),
            "remediation": report["remediation"],
        },
    }


def load_pilot_reassessment_report(
    path: str | Path | None = None,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    run_id: str = PILOT_REASSESSMENT_RUN_ID,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    snapshot_path: str | Path | None = None,
    validate_snapshot: bool = True,
) -> dict[str, object]:
    """Load run-scoped evidence and recompute it from the complete matrix."""

    root = _resolve_root(repository_root)
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ValueError as exc:
        raise PilotReassessmentError("reassessment run_id is invalid") from exc
    artifact_reference = Path(layout.pilot_report if path is None else path)
    artifact = _rooted(root, artifact_reference)
    if run_id != PILOT_REASSESSMENT_RUN_ID:
        _fresh_artifact_reference(
            artifact,
            repository=root,
            layout=layout,
            field="pilot reassessment artifact",
            expected_kind="file",
        )
    value, _ = _read_canonical(artifact, "pilot reassessment artifact")
    report = validate_pilot_reassessment_report(
        value,
        repository_root=root,
        run_id=run_id,
        benchmark_root=benchmark_root,
    )
    if validate_snapshot:
        selected_snapshot = Path(
            layout.pilot_snapshot
            if snapshot_path is None
            else snapshot_path
        )
        selected_snapshot_path = _rooted(root, selected_snapshot)
        if run_id != PILOT_REASSESSMENT_RUN_ID:
            _fresh_artifact_reference(
                selected_snapshot_path,
                repository=root,
                layout=layout,
                field="pilot reassessment snapshot",
                expected_kind="file",
            )
        snapshot, _ = _read_canonical(
            selected_snapshot_path,
            "pilot reassessment snapshot",
        )
        snapshot_mapping = _mapping(
            snapshot,
            "pilot reassessment snapshot",
        )
        if snapshot != _snapshot(
            report,
            artifact,
            repository=root,
            benchmark_root=benchmark_root,
            captured_on=snapshot_mapping.get("captured_on"),
        ):
            raise PilotReassessmentError(
                "pilot reassessment snapshot differs from the artifact"
            )
    return report


def _atomic_write(path: Path, payload: bytes, *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        try:
            with path.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            return
        except FileExistsError as exc:
            raise PilotReassessmentError(
                f"refusing to overwrite immutable evidence: {path}"
            ) from exc
    if path.is_symlink():
        raise PilotReassessmentError("refusing to overwrite a symlink")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    except OSError as exc:
        raise PilotReassessmentError(f"cannot write evidence: {path}") from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass


def write_pilot_reassessment_report(
    path: str | Path | None = None,
    *,
    run_id: str,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    snapshot_path: str | Path | None = None,
    repository_root: str | Path = REPOSITORY_ROOT,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    """Write one fresh run's artifact and run-scoped validation snapshot."""

    root = _resolve_root(repository_root)
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
        artifact_reference = Path(
            layout.pilot_report if path is None else path
        )
        snapshot_reference = Path(
            layout.pilot_snapshot
            if snapshot_path is None
            else snapshot_path
        )
        reject_published_write_targets(
            repository_root=root,
            run_id=run_id,
            targets=(artifact_reference, snapshot_reference),
            benchmark_root=benchmark_root,
        )
    except (ValueError, ReassessmentNamespaceError) as exc:
        raise PilotReassessmentError(str(exc)) from exc
    artifact = _rooted(root, artifact_reference)
    public_snapshot = _rooted(root, snapshot_reference)
    _fresh_artifact_reference(
        artifact,
        repository=root,
        layout=layout,
        field="pilot reassessment artifact",
    )
    _fresh_artifact_reference(
        public_snapshot,
        repository=root,
        layout=layout,
        field="pilot reassessment snapshot",
    )
    report = build_pilot_reassessment_report(
        repository_root=root,
        run_id=run_id,
        benchmark_root=benchmark_root,
    )
    _atomic_write(
        artifact,
        (canonical_json(report) + "\n").encode("utf-8"),
        overwrite=overwrite,
    )
    snapshot = _snapshot(
        report,
        artifact,
        repository=root,
        benchmark_root=benchmark_root,
    )
    _atomic_write(
        public_snapshot,
        (canonical_json(snapshot) + "\n").encode("utf-8"),
        overwrite=overwrite,
    )
    return artifact, public_snapshot


def pilot_reassessment_summary(report: object) -> dict[str, object]:
    """Return the stable CLI summary for a source-revalidated v2 report."""

    value = _mapping(report, "pilot reassessment report")
    shortlist = _mapping(value["shortlist"], "shortlist")
    decision = _mapping(value["decision"], "decision")
    completeness = _mapping(value["completeness"], "completeness")
    safety = _mapping(
        _mapping(value["reports"], "reports")["safety"], "reports.safety"
    )
    return {
        "section": "pilot-shortlist",
        "schema": value["schema"],
        "status": decision["status"],
        "structurally_valid": decision["structurally_valid"],
        "artifact_sha256": value["artifact_sha256"],
        "outcome_cell_count": completeness["coordinate_count"],
        "efficacy_observation_count": _mapping(
            _mapping(value["reports"], "reports")["proof"], "reports.proof"
        )["efficacy_observation_count"],
        "kernel_verified_invalid_control_false_positive_count": safety[
            "kernel_verified_invalid_control_false_positive_count"
        ],
        "selected_variant_ids": shortlist["selected_variant_ids"],
        "shortlist_frozen": shortlist["frozen"],
        "holdout_authorized": decision["holdout_authorized"],
        "remediation_required": bool(value["remediation"]),
        "missingness_retained": True,
    }


__all__ = [
    "DEFAULT_PILOT_REASSESSMENT_PATH",
    "DEFAULT_PILOT_REASSESSMENT_SNAPSHOT",
    "HSSLEV1409B38",
    "PILOT_REASSESSMENT_RUN_ID",
    "PILOT_REASSESSMENT_SCHEMA",
    "PILOT_REASSESSMENT_SNAPSHOT_SCHEMA",
    "PilotReassessmentError",
    "build_pilot_reassessment_report",
    "load_pilot_reassessment_report",
    "pilot_reassessment_summary",
    "validate_pilot_reassessment_report",
    "write_pilot_reassessment_report",
]
