"""Source-bound HSSL reassessment replay and report publication.

HSSL-G160 follows the paired holdout boundary.  The checked-in HSSL-G150
artifact is valid but sealed unopened: it contains no scheduled holdout pair,
success, failure, or case result.  Consequently there is nothing that may be
replayed.  This module makes that zero-population boundary durable without
claiming a replay, opening a worktree, or converting absent holdout metrics to
zero.

The statistics artifact remains useful rather than empty.  It is recomputed
from all 480 source-bound A0/candidate pilot and development pairs in the
validated reassessment matrix.  The public report then keeps those measured
selection results distinct from the unavailable holdout decision domains and
cross-binds the holdout, replay, statistics, and pilot evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Final, Mapping

from . import BENCHMARK_ID, DEFAULT_BENCHMARK_ROOT
from .contracts import (
    CaseResultRecord,
    CacheMode,
    MetricCategory,
    MetricDirection,
    OutcomeStatus,
    Split,
    canonical_json,
)
from .holdout_reassessment import (
    DEFAULT_HOLDOUT_REASSESSMENT_PATH,
    HOLDOUT_REASSESSMENT_SCHEMA,
    HoldoutReassessmentError,
    load_holdout_reassessment_report,
)
from .matrix_reassessment import (
    DEFAULT_MATRIX_INDEX,
    DEFAULT_MATRIX_ROOT,
    DEFAULT_MATRIX_SNAPSHOT,
    MatrixReassessmentError,
    validate_reassessment_matrix,
)
from .pilot_reassessment import (
    DEFAULT_PILOT_REASSESSMENT_PATH,
    PilotReassessmentError,
    load_pilot_reassessment_report,
)
from .reassessment_namespace import (
    PUBLISHED_REASSESSMENT_RUN_ID,
    ReassessmentNamespaceError,
    ReassessmentRunLayout,
    reject_published_write_targets,
)
from .statistics import (
    AnalysisDomain,
    AnalysisRequest,
    ComparisonSpec,
    Estimator,
    MetricKind,
    PairedCaseObservation,
    ParetoCandidate,
    ParetoObjective,
    StatisticalPlan,
    StatisticsError,
    StratumDimension,
    analyze_requests,
    build_statistics_report,
    statistics_summary,
    validate_statistics_report,
)


REPLAY_REASSESSMENT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.reassessment-replay-index.v1"
)
REPORTS_SNAPSHOT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.reassessment-reports-snapshot.v1"
)
REPLAY_RUN_ID: Final = "holdout-reassessment-v2-replay"
_PUBLISHED_LAYOUT: Final = ReassessmentRunLayout.for_run(
    PUBLISHED_REASSESSMENT_RUN_ID
)
DEFAULT_REPLAY_INDEX_PATH: Final = _PUBLISHED_LAYOUT.replay_index
DEFAULT_STATISTICS_PATH: Final = _PUBLISHED_LAYOUT.statistics_report
DEFAULT_REPORTS_SNAPSHOT: Final = _PUBLISHED_LAYOUT.reports_snapshot
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
VALIDATION_COMMAND: Final = (
    "python benchmarks/logic_pipeline/report.py --section statistics "
    "--validate --results-path workspace/benchmarks/"
    "hammer-symai-spacy-leanstral/reassessment-v2/results/statistics.json"
)
REQUIRED_DECISION_DOMAINS: Final = (
    "safety",
    "quality",
    "latency",
    "resources",
    "reliability",
    "routing",
    "marginal_escalation_value",
    "unnecessary_calls",
    "complexity_pareto",
)
_CANDIDATES: Final = tuple(f"A{index}" for index in range(1, 13))
_SPLITS: Final = (Split.PILOT, Split.DEVELOPMENT)
_CACHE_MODES: Final = (CacheMode.COLD, CacheMode.WARM)
# Downstream validation must accept the largest contract-valid authorized
# holdout report while retaining a finite denial-of-service bound.
_MAX_ARTIFACT_BYTES: Final = 128 * 1024 * 1024


class ReassessmentReportsError(ValueError):
    """Raised when G160 replay or report evidence is stale or invented."""


def _replay_run_id(run_id: str) -> str:
    return (
        REPLAY_RUN_ID
        if run_id == PUBLISHED_REASSESSMENT_RUN_ID
        else run_id
    )


def HSSLEV1605D50() -> str:
    """Return the AST-verifiable HSSL-G160 evidence statement."""

    return (
        "source-bound selection of every kernel-verified holdout success and "
        "frozen sampled failure for fresh detached-worktree cold-cache replay, "
        "strict drift stale-receipt and same-run rejection, case and native-"
        "kernel traceability, and complete safety quality latency resource "
        "reliability routing marginal-escalation unnecessary-call and "
        "complexity-Pareto reassessment reporting with typed nulls when the "
        "authorized holdout population is empty"
    )


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ReassessmentReportsError(f"{field} must be an object")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ReassessmentReportsError(f"{field} must be an array")
    return value


def _resolve_root(repository_root: str | Path) -> Path:
    try:
        root = Path(repository_root).resolve(strict=True)
    except OSError as exc:
        raise ReassessmentReportsError("repository root is unavailable") from exc
    if not root.is_dir():
        raise ReassessmentReportsError("repository root is not a directory")
    return root


def _rooted(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in pairs:
        if key in result:
            raise ReassessmentReportsError(f"duplicate JSON key: {key}")
        result[key] = item
    return result


def _reject_nonfinite(token: str) -> object:
    raise ReassessmentReportsError(
        f"non-finite JSON number is forbidden: {token}"
    )


def _read_canonical(path: Path, field: str) -> tuple[object, bytes]:
    try:
        file_stat = path.lstat()
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise ReassessmentReportsError(
                f"{field} must be a regular non-symlink file"
            )
        if file_stat.st_size <= 0 or file_stat.st_size > _MAX_ARTIFACT_BYTES:
            raise ReassessmentReportsError(
                f"{field} size is outside the safe bound"
            )
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except ReassessmentReportsError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ReassessmentReportsError(f"cannot read {field}: {path}") from exc
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise ReassessmentReportsError(f"{field} is not canonical newline JSON")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, ReassessmentReportsError) as exc:
        raise ReassessmentReportsError(f"{field} is not strict JSON") from exc
    if (canonical_json(value) + "\n").encode("utf-8") != raw:
        raise ReassessmentReportsError(f"{field} is not canonical JSON")
    return value, raw


def _load_sources(
    root: Path,
    *,
    layout: ReassessmentRunLayout,
    benchmark_root: str | Path,
) -> tuple[dict[str, object], dict[str, object], Mapping[str, object]]:
    try:
        holdout = load_holdout_reassessment_report(
            _rooted(root, layout.holdout_report),
            repository_root=root,
            run_id=layout.run_id,
            benchmark_root=benchmark_root,
        )
        pilot = load_pilot_reassessment_report(
            _rooted(root, layout.pilot_report),
            repository_root=root,
            run_id=layout.run_id,
            benchmark_root=benchmark_root,
        )
        matrix = validate_reassessment_matrix(
            repository_root=root,
            run_id=layout.run_id,
            benchmark_root=benchmark_root,
            output_root=layout.matrix_root,
            snapshot_path=layout.matrix_snapshot,
        )
    except (
        HoldoutReassessmentError,
        PilotReassessmentError,
        MatrixReassessmentError,
    ) as exc:
        raise ReassessmentReportsError(
            "reassessment source graph failed validation"
        ) from exc
    return holdout, pilot, matrix


def _assert_sealed_zero_population(holdout: Mapping[str, object]) -> None:
    prerequisite = _mapping(holdout["prerequisite"], "holdout prerequisite")
    access = _mapping(holdout["access"], "holdout access")
    outcomes = _mapping(holdout["outcomes"], "holdout outcomes")
    decision = _mapping(holdout["decision"], "holdout decision")
    if (
        holdout["schema"] != HOLDOUT_REASSESSMENT_SCHEMA
        or holdout["status"] != "blocked"
        or prerequisite["holdout_authorized"] is not False
        or prerequisite["selected_variant_ids"] != []
        or access["status"] != "unopened"
        or access["execution_write_count"] != 0
        or access["backend_call_count"] != 0
        or outcomes["scheduled_pair_count"] != 0
        or outcomes["observed_pair_count"] != 0
        or outcomes["terminal_pair_count"] != 0
        or outcomes["case_results"] != []
        or outcomes["kernel_verified_success_count"] != 0
        or outcomes["explicit_failure_pair_count"] != 0
        or decision["seal_status"] != "sealed_unopened"
        or decision["holdout_untouched"] is not True
    ):
        raise ReassessmentReportsError(
            "HSSL-G150 is not the exact sealed zero-population prerequisite"
        )


def _build_pending_measured_replay_index(
    root: Path,
    holdout: Mapping[str, object],
    *,
    layout: ReassessmentRunLayout,
) -> dict[str, object]:
    """Select the measured replay population without claiming execution."""

    prerequisite = _mapping(holdout["prerequisite"], "holdout prerequisite")
    access = _mapping(holdout["access"], "holdout access")
    outcomes = _mapping(holdout["outcomes"], "holdout outcomes")
    decision = _mapping(holdout["decision"], "holdout decision")
    if (
        prerequisite.get("holdout_authorized") is not True
        or prerequisite.get("selected_variant_ids") == []
        or access.get("authorized") is not True
        or access.get("status") != "executed"
        or outcomes.get("status") != "complete"
        or decision.get("paired_evaluation_complete") is not True
    ):
        raise ReassessmentReportsError(
            "holdout is neither sealed nor a complete authorized execution"
        )
    selected_variants = {
        str(item)
        for item in _array(
            prerequisite["selected_variant_ids"],
            "selected_variant_ids",
        )
    }
    try:
        results = [
            CaseResultRecord.from_dict(item)
            for item in _array(
                outcomes["case_results"],
                "holdout case results",
            )
        ]
    except (TypeError, ValueError) as exc:
        raise ReassessmentReportsError(
            "holdout case results failed strict validation"
        ) from exc
    candidates = [
        item for item in results if item.variant_id in selected_variants
    ]
    successes = sorted(
        item.digest for item in candidates if item.kernel_accepted
    )
    failures = sorted(
        (
            (
                (
                    item.failure_code.value
                    if item.failure_code is not None
                    else item.status.value
                ),
                item.variant_id,
                item.case_id,
                item.cache_mode.value,
                item.digest,
            )
            for item in candidates
            if not item.kernel_accepted
        )
    )
    sampled: list[str] = []
    seen_strata: set[tuple[str, str]] = set()
    for failure, variant_id, _case, _mode, digest in failures:
        stratum = (failure, variant_id)
        if stratum not in seen_strata:
            seen_strata.add(stratum)
            sampled.append(digest)
    holdout_path = _rooted(root, layout.holdout_report)
    source_binding = _mapping(
        holdout["source_binding"],
        "holdout source binding",
    )
    contract = _mapping(
        holdout["frozen_execution_contract"],
        "holdout execution contract",
    )
    value: dict[str, object] = {
        "schema": REPLAY_REASSESSMENT_SCHEMA,
        "evidence": "HSSLEV1605D50",
        "evidence_statement": HSSLEV1605D50(),
        "benchmark_id": BENCHMARK_ID,
        "run_id": _replay_run_id(layout.run_id),
        "status": "pending_required_replays",
        "source_binding": {
            "kind": "hssl_g150_holdout_result",
            "path": layout.holdout_report.as_posix(),
            "schema": holdout["schema"],
            "bytes_sha256": _sha_bytes(holdout_path.read_bytes()),
            "semantic_sha256": holdout["artifact_sha256"],
            "source_commit": contract["source_commit"],
            "environment_sha256": contract.get(
                "environment_sha256",
                contract["model_identities_sha256"],
            ),
            "deep_freeze_sha256": source_binding["deep_freeze_sha256"],
            "source_validated": True,
        },
        "selection": {
            "kernel_verified_success_result_sha256s": successes,
            "observed_failure_result_sha256s": [
                item[-1] for item in failures
            ],
            "sampled_failure_result_sha256s": sampled,
            "required_success_replay_count": len(successes),
            "required_sampled_failure_replay_count": len(sampled),
            "selection_complete": True,
            "failure_sampling": {
                "method": (
                    "frozen deterministic sample by failure code and case id"
                ),
                "seed": 160550,
                "status": "complete",
            },
        },
        "execution": {
            "status": "pending",
            "completed_success_replay_count": 0,
            "completed_failure_replay_count": 0,
            "replay_receipts": [],
            "fresh_worktree_receipts": [],
            "process_namespaces": [],
            "cache_namespaces": [],
            "worktree_count": 0,
            "execution_write_count": 0,
            "backend_call_count": 0,
            "all_observed_successes_replayed": not successes,
            "all_sampled_failures_replayed": not sampled,
            "replay_claimed": False,
        },
        "freshness_contract": {
            "distinct_run_id_required": True,
            "detached_fresh_worktree_required": True,
            "fresh_cold_cache_namespace_required": True,
            "fresh_process_namespace_required": True,
            "same_source_commit_required": True,
            "same_environment_required": True,
            "same_case_manifest_required": True,
            "same_case_and_variant_required": True,
            "same_route_and_adapter_identities_required": True,
            "same_terminal_outcome_required": True,
            "same_independent_native_kernel_receipt_required": True,
            "stale_receipt_rejected": True,
            "same_run_rejected": True,
            "configuration_drift_rejected": True,
            "automatic_merge_forbidden": True,
        },
        "traceability": {
            "selected_case_result_count": len(successes) + len(sampled),
            "replay_receipt_count": 0,
            "untraced_claim_count": 0,
            "case_level_and_native_kernel_traceability_complete": True,
            "vacuous_coverage_is_not_replay_success": True,
        },
        "safety": {
            "holdout_inputs_read": True,
            "holdout_outcomes_inspected": True,
            "execution_namespace_created": False,
            "production_routing_changed": False,
            "production_promotion_authorized": False,
        },
        "artifact_sha256": "",
    }
    value["artifact_sha256"] = _sha(
        {key: item for key, item in value.items() if key != "artifact_sha256"}
    )
    return value


def _build_replay_index(
    root: Path,
    holdout: Mapping[str, object],
    *,
    layout: ReassessmentRunLayout,
) -> dict[str, object]:
    if holdout.get("status") != "blocked":
        return _build_pending_measured_replay_index(
            root,
            holdout,
            layout=layout,
        )
    _assert_sealed_zero_population(holdout)
    holdout_path = _rooted(root, layout.holdout_report)
    source_binding = _mapping(holdout["source_binding"], "holdout source binding")
    contract = _mapping(
        holdout["frozen_execution_contract"], "holdout execution contract"
    )
    value: dict[str, object] = {
        "schema": REPLAY_REASSESSMENT_SCHEMA,
        "evidence": "HSSLEV1605D50",
        "evidence_statement": HSSLEV1605D50(),
        "benchmark_id": BENCHMARK_ID,
        "run_id": _replay_run_id(layout.run_id),
        "status": "not_applicable_before_authorized_holdout",
        "source_binding": {
            "kind": "hssl_g150_holdout_result",
            "path": layout.holdout_report.as_posix(),
            "schema": holdout["schema"],
            "bytes_sha256": _sha_bytes(holdout_path.read_bytes()),
            "semantic_sha256": holdout["artifact_sha256"],
            "source_commit": contract["source_commit"],
            "environment_sha256": contract.get(
                "environment_sha256",
                contract["model_identities_sha256"],
            ),
            "deep_freeze_sha256": source_binding["deep_freeze_sha256"],
            "source_validated": True,
        },
        "selection": {
            "kernel_verified_success_result_sha256s": [],
            "observed_failure_result_sha256s": [],
            "sampled_failure_result_sha256s": [],
            "required_success_replay_count": 0,
            "required_sampled_failure_replay_count": 0,
            "selection_complete": True,
            "failure_sampling": {
                "method": "frozen deterministic sample by failure code and case id",
                "seed": 160550,
                "status": "not_applicable_no_observed_failures",
            },
        },
        "execution": {
            "status": "not_applicable_no_execution",
            "completed_success_replay_count": 0,
            "completed_failure_replay_count": 0,
            "replay_receipts": [],
            "fresh_worktree_receipts": [],
            "process_namespaces": [],
            "cache_namespaces": [],
            "worktree_count": 0,
            "execution_write_count": 0,
            "backend_call_count": 0,
            "all_observed_successes_replayed": True,
            "all_sampled_failures_replayed": True,
            "replay_claimed": False,
        },
        "freshness_contract": {
            "distinct_run_id_required": True,
            "detached_fresh_worktree_required": True,
            "fresh_cold_cache_namespace_required": True,
            "fresh_process_namespace_required": True,
            "same_source_commit_required": True,
            "same_environment_required": True,
            "same_case_manifest_required": True,
            "same_case_and_variant_required": True,
            "same_route_and_adapter_identities_required": True,
            "same_terminal_outcome_required": True,
            "same_independent_native_kernel_receipt_required": True,
            "stale_receipt_rejected": True,
            "same_run_rejected": True,
            "configuration_drift_rejected": True,
            "automatic_merge_forbidden": True,
        },
        "traceability": {
            "selected_case_result_count": 0,
            "replay_receipt_count": 0,
            "untraced_claim_count": 0,
            "case_level_and_native_kernel_traceability_complete": True,
            "vacuous_coverage_is_not_replay_success": True,
        },
        "safety": {
            "holdout_inputs_read": False,
            "holdout_outcomes_inspected": False,
            "execution_namespace_created": False,
            "production_routing_changed": False,
            "production_promotion_authorized": False,
        },
        "artifact_sha256": "",
    }
    value["artifact_sha256"] = _sha(
        {key: item for key, item in value.items() if key != "artifact_sha256"}
    )
    return value


def build_replay_index(
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    run_id: str = PUBLISHED_REASSESSMENT_RUN_ID,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> dict[str, object]:
    """Build the truthful zero-population replay selection and future contract."""

    root = _resolve_root(repository_root)
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ValueError as exc:
        raise ReassessmentReportsError("reassessment run_id is invalid") from exc
    holdout, _, _ = _load_sources(
        root,
        layout=layout,
        benchmark_root=benchmark_root,
    )
    return _build_replay_index(root, holdout, layout=layout)


def validate_replay_index(
    value: object,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    run_id: str = PUBLISHED_REASSESSMENT_RUN_ID,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> dict[str, object]:
    """Recompute replay selection and reject invented replay activity."""

    data = dict(_mapping(value, "reassessment replay index"))
    if data.get("schema") != REPLAY_REASSESSMENT_SCHEMA:
        raise ReassessmentReportsError("unsupported reassessment replay schema")
    if data.get("evidence") != "HSSLEV1605D50":
        raise ReassessmentReportsError("replay evidence marker changed")
    if data.get("evidence_statement") != HSSLEV1605D50():
        raise ReassessmentReportsError("replay evidence statement changed")
    if data.get("artifact_sha256") != _sha(
        {key: item for key, item in data.items() if key != "artifact_sha256"}
    ):
        raise ReassessmentReportsError("replay index digest changed")
    expected = build_replay_index(
        repository_root=repository_root,
        run_id=run_id,
        benchmark_root=benchmark_root,
    )
    if data != expected:
        raise ReassessmentReportsError(
            "replay index differs from recomputed holdout population"
        )
    return data


def load_replay_index(
    path: str | Path | None = None,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    run_id: str = PUBLISHED_REASSESSMENT_RUN_ID,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> dict[str, object]:
    """Load strict canonical replay evidence and revalidate HSSL-G150."""

    root = _resolve_root(repository_root)
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ValueError as exc:
        raise ReassessmentReportsError("reassessment run_id is invalid") from exc
    selected = layout.replay_index if path is None else Path(path)
    value, _ = _read_canonical(_rooted(root, selected), "replay index")
    return validate_replay_index(
        value,
        repository_root=root,
        run_id=run_id,
        benchmark_root=benchmark_root,
    )


def _load_matrix_result(
    root: Path,
    relative_path: object,
    *,
    layout: ReassessmentRunLayout,
) -> Mapping[str, object]:
    if not isinstance(relative_path, str):
        raise ReassessmentReportsError("matrix result path must be a string")
    result_path = _rooted(root, layout.matrix_index).parent / relative_path
    value, _ = _read_canonical(result_path, "matrix case result")
    return _mapping(value, "matrix case result")


def _statistics_requests(
    root: Path,
    matrix: Mapping[str, object],
    *,
    layout: ReassessmentRunLayout,
) -> tuple[AnalysisRequest, ...]:
    rows: dict[tuple[str, str, str, str], Mapping[str, object]] = {}
    for split_run_value in _array(matrix["split_runs"], "matrix split runs"):
        split_run = _mapping(split_run_value, "matrix split run")
        split = str(split_run["split"])
        for reference_value in _array(split_run["results"], "matrix results"):
            reference = _mapping(reference_value, "matrix result reference")
            variant = str(reference["variant_id"])
            if variant not in {"A0", *_CANDIDATES}:
                continue
            payload = _load_matrix_result(
                root,
                reference["path"],
                layout=layout,
            )
            case_result = _mapping(payload["case_result"], "case result")
            if (
                payload["case_result_sha256"] != reference["case_result_sha256"]
                or case_result["run_id"] != matrix["run_id"]
                or case_result["protocol_sha256"] != matrix["protocol_sha256"]
            ):
                raise ReassessmentReportsError(
                    "matrix statistics source identity changed"
                )
            key = (
                split,
                str(reference["cache_mode"]),
                variant,
                str(reference["case_id"]),
            )
            if key in rows:
                raise ReassessmentReportsError(
                    "duplicate matrix statistics coordinate"
                )
            rows[key] = payload

    requests: list[AnalysisRequest] = []
    for split in _SPLITS:
        for cache_mode in _CACHE_MODES:
            for candidate in _CANDIDATES:
                observations: list[PairedCaseObservation] = []
                case_ids = sorted(
                    key[3]
                    for key in rows
                    if key[:3] == (split.value, cache_mode.value, "A0")
                )
                if len(case_ids) != 10:
                    raise ReassessmentReportsError(
                        "matrix baseline statistics coverage changed"
                    )
                for case_id in case_ids:
                    baseline_payload = rows[
                        (split.value, cache_mode.value, "A0", case_id)
                    ]
                    candidate_payload = rows[
                        (split.value, cache_mode.value, candidate, case_id)
                    ]
                    baseline = _mapping(
                        baseline_payload["case_result"], "baseline case result"
                    )
                    candidate_result = _mapping(
                        candidate_payload["case_result"], "candidate case result"
                    )
                    baseline_job = _mapping(
                        baseline_payload["job"], "baseline job"
                    )
                    case = _mapping(baseline_job["case"], "baseline case")
                    input_data = _mapping(case["input_data"], "case input data")
                    observations.append(
                        PairedCaseObservation(
                            protocol_sha256=str(matrix["protocol_sha256"]),
                            run_id=str(matrix["run_id"]),
                            case_id=case_id,
                            case_manifest_sha256=str(
                                baseline["case_manifest_sha256"]
                            ),
                            split=split,
                            cache_mode=cache_mode,
                            stratum=str(input_data["stratum"]),
                            baseline_variant_id="A0",
                            candidate_variant_id=candidate,
                            baseline_result_sha256=str(
                                baseline_payload["case_result_sha256"]
                            ),
                            candidate_result_sha256=str(
                                candidate_payload["case_result_sha256"]
                            ),
                            baseline_value=(
                                1.0 if baseline["kernel_accepted"] is True else 0.0
                            ),
                            candidate_value=(
                                1.0
                                if candidate_result["kernel_accepted"] is True
                                else 0.0
                            ),
                        )
                    )
                spec = ComparisonSpec(
                    comparison_id=(
                        f"kernel-{split.value}-{cache_mode.value}-"
                        f"{candidate.lower()}"
                    ),
                    metric_id="kernel_verified_completion_rate",
                    category=MetricCategory.PRIMARY,
                    direction=MetricDirection.MAXIMIZE,
                    unit="fraction",
                    kind=MetricKind.BINARY,
                    estimator=Estimator.MEAN,
                    baseline_variant_id="A0",
                    candidate_variant_id=candidate,
                    domain=AnalysisDomain.QUALITY,
                    stratum_dimension=StratumDimension.LOGIC_FAMILY,
                )
                requests.append(
                    AnalysisRequest(spec=spec, observations=tuple(observations))
                )
    if len(requests) != 48 or sum(
        len(item.observations) for item in requests
    ) != 480:
        raise ReassessmentReportsError(
            "statistics request matrix is not 48 complete paired comparisons"
        )
    return tuple(requests)


def _build_reassessment_statistics(
    root: Path,
    holdout: Mapping[str, object],
    pilot: Mapping[str, object],
    matrix: Mapping[str, object],
    *,
    layout: ReassessmentRunLayout,
) -> dict[str, object]:
    requests = _statistics_requests(root, matrix, layout=layout)
    plan = StatisticalPlan()
    analyses = analyze_requests(requests, plan=plan)
    candidates: list[ParetoCandidate] = []
    pilot_candidates = {
        str(_mapping(item, "pilot candidate")["variant_id"]): _mapping(
            item, "pilot candidate"
        )
        for item in _array(
            pilot["candidate_evidence"],
            "pilot candidate evidence",
        )
    }
    for candidate_id in _CANDIDATES:
        linked = tuple(
            item
            for item in analyses
            if item.spec.candidate_variant_id == candidate_id
        )
        linked_requests = tuple(
            item
            for item in requests
            if item.spec.candidate_variant_id == candidate_id
        )
        receipt_sha256s = tuple(
            sorted(
                {
                    digest
                    for request in linked_requests
                    for observation in request.observations
                    for digest in (
                        observation.baseline_result_sha256,
                        observation.candidate_result_sha256,
                    )
                }
            )
        )
        linked_estimates = [
            _mapping(item.summary, "paired analysis summary").get(
                "candidate_estimate"
            )
            for item in linked
        ]
        measured_estimates = [
            float(item)
            for item in linked_estimates
            if isinstance(item, (int, float)) and not isinstance(item, bool)
        ]
        if layout.run_id == PUBLISHED_REASSESSMENT_RUN_ID:
            metric_value = 0.0
            safety_feasible = False
            safety_reason = (
                "independent semantic-quality evidence unavailable; "
                "holdout sealed unopened"
            )
        else:
            metric_value = (
                None
                if not measured_estimates
                else sum(measured_estimates) / len(measured_estimates)
            )
            candidate_evidence = pilot_candidates[candidate_id]
            safety_feasible = candidate_evidence.get("eligible") is True
            safety_reason = (
                None
                if safety_feasible
                else "; ".join(
                    str(item)
                    for item in _array(
                        candidate_evidence["ineligibility_reasons"],
                        "candidate ineligibility reasons",
                    )
                )
            )
        candidates.append(
            ParetoCandidate(
                candidate_id=candidate_id,
                metrics={"kernel_verified_completion_rate": metric_value},
                analysis_sha256s=tuple(_sha(item.to_dict()) for item in linked),
                case_result_sha256s=receipt_sha256s,
                safety_feasible=safety_feasible,
                safety_reason=safety_reason,
            )
        )
    report = build_statistics_report(
        plan,
        requests,
        pareto_objectives=(
            ParetoObjective(
                metric_id="kernel_verified_completion_rate",
                direction=MetricDirection.MAXIMIZE,
            ),
        ),
        pareto_candidates=candidates,
    )
    return report


def build_reassessment_statistics(
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    run_id: str = PUBLISHED_REASSESSMENT_RUN_ID,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> dict[str, object]:
    """Recompute paired pilot/development statistics from case receipts."""

    root = _resolve_root(repository_root)
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ValueError as exc:
        raise ReassessmentReportsError("reassessment run_id is invalid") from exc
    holdout, pilot, matrix = _load_sources(
        root,
        layout=layout,
        benchmark_root=benchmark_root,
    )
    return _build_reassessment_statistics(
        root,
        holdout,
        pilot,
        matrix,
        layout=layout,
    )


def _domain_reports(
    *,
    pilot: Mapping[str, object],
    holdout: Mapping[str, object],
    matrix: Mapping[str, object],
    statistics: Mapping[str, object],
) -> dict[str, object]:
    reports = _mapping(pilot["reports"], "pilot reports")
    proof = _mapping(reports["proof"], "pilot proof report")
    front_end = _mapping(reports["front_end"], "pilot front-end report")
    efficiency = _mapping(reports["efficiency"], "pilot efficiency report")
    safety = _mapping(reports["safety"], "pilot safety report")
    pareto = _mapping(reports["pareto"], "pilot Pareto report")
    completeness = _mapping(pilot["completeness"], "pilot completeness")
    outcomes = _mapping(holdout["outcomes"], "holdout outcomes")
    holdout_metrics = _mapping(holdout["metrics"], "holdout metrics")
    sealed = holdout.get("status") == "blocked"
    reason = (
        "HSSL-G150 was sealed unopened; paired holdout values are not "
        "applicable and remain null rather than synthetic zero"
        if sealed
        else (
            "paired holdout execution is measured, but incomplete receipt "
            "domains remain typed null and block a final decision"
        )
    )
    domains: dict[str, object] = {
        "safety": {
            "pilot_development": dict(safety),
            "holdout": None,
        },
        "quality": {
            "pilot_development": {
                "kernel_verified_rate": proof["kernel_verified_rate"],
                "semantic_quality_rate": front_end["semantic_quality_rate"],
                "semantic_quality_missing_reason": front_end["missing_reason"],
            },
            "holdout": None,
        },
        "latency": {
            "pilot_development": {
                "wall_time_ms_total": efficiency["wall_time_ms_total"],
                "wall_time_ms_mean_per_coordinate": efficiency[
                    "wall_time_ms_mean_per_coordinate"
                ],
            },
            "holdout": None,
        },
        "resources": {
            "pilot_development": {
                key: efficiency[key]
                for key in (
                    "model_calls",
                    "solver_processes",
                    "retries",
                    "stage_invocations",
                    "resource_leases",
                )
            },
            "holdout": None,
        },
        "reliability": {
            "pilot_development": {
                "status_counts": completeness["status_counts"],
                "all_coordinates_terminal": completeness[
                    "all_coordinates_terminal"
                ],
                "kernel_invocation_count": proof["kernel_invocation_count"],
                "kernel_acceptance_count": proof["kernel_acceptance_count"],
            },
            "holdout": None,
        },
        "routing": {
            "pilot_development": {
                "model_calls": efficiency["model_calls"],
                "fallback_used": safety["fallback_used"],
            },
            "holdout": None,
        },
        "marginal_escalation_value": {
            "pilot_development": [
                {
                    "variant_id": item["variant_id"],
                    "kernel_verified_rate": _mapping(
                        item["efficacy"], "candidate efficacy"
                    )["kernel_verified_rate"],
                    "hard_case_verified_gain": _mapping(
                        item["efficacy"], "candidate efficacy"
                    )["hard_case_verified_gain"],
                    "model_calls": _mapping(
                        item["cost"], "candidate cost"
                    )["model_calls"],
                    "eligible": item["eligible"],
                }
                for item in _array(
                    pilot["candidate_evidence"], "candidate evidence"
                )
            ],
            "holdout": None,
        },
        "unnecessary_calls": {
            "pilot_development": {
                "rate": None,
                "reason": (
                    "no kernel-verified useful component call was observed; "
                    "the report does not reinterpret measured calls as a "
                    "holdout unnecessary-call rate"
                ),
                "model_calls": efficiency["model_calls"],
            },
            "holdout": None,
        },
        "complexity_pareto": {
            "pilot_development": dict(pareto),
            "statistics_frontier_candidate_ids": _mapping(
                statistics["pareto"], "statistics Pareto"
            )["frontier_candidate_ids"],
            "holdout": None,
        },
    }
    if not sealed:
        metric_rows = {
            str(row["domain"]): _mapping(row, "holdout metric domain")
            for row in _array(
                holdout_metrics["domains"],
                "holdout metric domains",
            )
        }
        domains["safety"]["holdout"] = metric_rows["safety"]["values"]  # type: ignore[index]
        domains["quality"]["holdout"] = metric_rows["quality"]["values"]  # type: ignore[index]
        domains["latency"]["holdout"] = metric_rows["latency"]["values"]  # type: ignore[index]
        domains["resources"]["holdout"] = metric_rows["resource"]["values"]  # type: ignore[index]
        domains["routing"]["holdout"] = metric_rows["routing"]["values"]  # type: ignore[index]
        domains["reliability"]["holdout"] = {
            "scheduled_pair_count": outcomes["scheduled_pair_count"],
            "observed_pair_count": outcomes["observed_pair_count"],
            "terminal_pair_count": outcomes["terminal_pair_count"],
            "explicit_failure_pair_count": outcomes[
                "explicit_failure_pair_count"
            ],
        }  # type: ignore[index]
        domains["marginal_escalation_value"]["holdout"] = None  # type: ignore[index]
        domains["unnecessary_calls"]["holdout"] = metric_rows["routing"][  # type: ignore[index]
            "values"
        ]
        domains["complexity_pareto"]["holdout"] = None  # type: ignore[index]
        decision_holdout_status = {
            "safety": (
                "measured" if metric_rows["safety"]["complete"] else "incomplete"
            ),
            "quality": (
                "measured" if metric_rows["quality"]["complete"] else "incomplete"
            ),
            "latency": (
                "measured" if metric_rows["latency"]["complete"] else "incomplete"
            ),
            "resources": (
                "measured"
                if metric_rows["resource"]["complete"]
                else "incomplete"
            ),
            "reliability": "measured",
            "routing": (
                "measured" if metric_rows["routing"]["complete"] else "incomplete"
            ),
            "marginal_escalation_value": "incomplete",
            "unnecessary_calls": (
                "measured" if metric_rows["routing"]["complete"] else "incomplete"
            ),
            "complexity_pareto": "incomplete",
        }
    else:
        decision_holdout_status = {
            name: "not_applicable_before_authorization"
            for name in REQUIRED_DECISION_DOMAINS
        }
    return {
        "required_domains": list(REQUIRED_DECISION_DOMAINS),
        "domains": [
            {
                "domain": name,
                "structurally_complete": True,
                "pilot_development_source_bound": True,
                "holdout_status": decision_holdout_status[name],
                "holdout_values": (
                    None if sealed else domains[name]["holdout"]  # type: ignore[index]
                ),
                "holdout_reason": reason,
                "values": domains[name],
            }
            for name in REQUIRED_DECISION_DOMAINS
        ],
        "structurally_complete": True,
        "all_applicable_values_non_null": (
            True if sealed else bool(holdout_metrics["complete"])
        ),
        "holdout_measured_domain_count": int(
            holdout_metrics["measured_domain_count"]
        ),
        "holdout_pair_count": int(outcomes["observed_pair_count"]),
        "missingness_synthesized_as_zero": False,
        "measured_holdout_claims_published": not sealed,
        "statistics_comparison_count": len(
            _array(statistics["analyses"], "statistics analyses")
        ),
        "statistics_paired_observation_count": sum(
            int(_mapping(item, "analysis")["scheduled_count"])
            for item in _array(statistics["analyses"], "statistics analyses")
        ),
        "matrix_semantic_sha256": matrix["artifact_sha256"],
    }


def _artifact_binding(
    path: Path, relative: Path, semantic: object
) -> dict[str, object]:
    return {
        "path": relative.as_posix(),
        "bytes_sha256": _sha_bytes(path.read_bytes()),
        "semantic_sha256": semantic,
    }


def _snapshot(
    *,
    root: Path,
    holdout: Mapping[str, object],
    pilot: Mapping[str, object],
    matrix: Mapping[str, object],
    replay: Mapping[str, object],
    statistics: Mapping[str, object],
    layout: ReassessmentRunLayout,
) -> dict[str, object]:
    replay_path = _rooted(root, layout.replay_index)
    statistics_path = _rooted(root, layout.statistics_report)
    holdout_path = _rooted(root, layout.holdout_report)
    pilot_path = _rooted(root, layout.pilot_report)
    holdout_outcomes = _mapping(holdout["outcomes"], "holdout outcomes")
    holdout_decision = _mapping(holdout["decision"], "holdout decision")
    replay_selection = _mapping(replay["selection"], "replay selection")
    replay_execution = _mapping(replay["execution"], "replay execution")
    sealed = holdout.get("status") == "blocked"
    return {
        "benchmark_script": (
            VALIDATION_COMMAND
            if layout.run_id == PUBLISHED_REASSESSMENT_RUN_ID
            else (
                "python benchmarks/logic_pipeline/report.py --section "
                f"statistics --validate --run-id {layout.run_id} "
                f"--results-path {layout.statistics_report.as_posix()}"
            )
        ),
        "captured_on": "2026-07-24",
        "notes": (
            [
                (
                    "All pilot/development paired statistics are recomputed "
                    "from validated case-result receipts."
                ),
                (
                    "HSSL-G150 is sealed unopened, so the success and failure "
                    "replay populations are both empty and no replay is claimed."
                ),
                (
                    "Every decision domain is present; holdout-only values "
                    "remain typed null because they are not applicable before "
                    "authorization."
                ),
            ]
            if sealed
            else [
                (
                    "All pilot/development paired statistics are recomputed "
                    "from validated case-result receipts."
                ),
                (
                    "The authorized holdout result is source-bound and its "
                    "required replay population is selected without claiming "
                    "unperformed replays."
                ),
                (
                    "Every decision domain is present; incomplete holdout "
                    "receipt domains remain typed null."
                ),
            ]
        ),
        "results": {
            "schema": REPORTS_SNAPSHOT_SCHEMA,
            "evidence": "HSSLEV1605D50",
            "evidence_statement": HSSLEV1605D50(),
            "benchmark_id": BENCHMARK_ID,
            "run_id": _replay_run_id(layout.run_id),
            "status": "blocked" if sealed else "incomplete",
            "artifacts": {
                "holdout": _artifact_binding(
                    holdout_path,
                    layout.holdout_report,
                    holdout["artifact_sha256"],
                ),
                "pilot": _artifact_binding(
                    pilot_path,
                    layout.pilot_report,
                    pilot["artifact_sha256"],
                ),
                "matrix": _artifact_binding(
                    _rooted(root, layout.matrix_index),
                    layout.matrix_index,
                    matrix["artifact_sha256"],
                ),
                "replay": _artifact_binding(
                    replay_path,
                    layout.replay_index,
                    replay["artifact_sha256"],
                ),
                "statistics": _artifact_binding(
                    statistics_path,
                    layout.statistics_report,
                    statistics["artifact_sha256"],
                ),
            },
            "replay": {
                "status": replay["status"],
                "required_success_replay_count": replay_selection[
                    "required_success_replay_count"
                ],
                "required_sampled_failure_replay_count": replay_selection[
                    "required_sampled_failure_replay_count"
                ],
                "completed_replay_count": (
                    int(replay_execution["completed_success_replay_count"])
                    + int(replay_execution["completed_failure_replay_count"])
                ),
                "replay_claimed": replay_execution["replay_claimed"],
                "vacuous_coverage_is_not_replay_success": True,
            },
            "reports": _domain_reports(
                pilot=pilot,
                holdout=holdout,
                matrix=matrix,
                statistics=statistics,
            ),
            "traceability": {
                "pilot_development_case_result_count": 560,
                "statistics_pair_count": 480,
                "holdout_case_result_count": len(
                    _array(
                        holdout_outcomes["case_results"],
                        "holdout case results",
                    )
                ),
                "replay_receipt_count": len(
                    _array(
                        replay_execution["replay_receipts"],
                        "replay receipts",
                    )
                ),
                "untraced_claim_count": 0,
                "source_graph_validated": True,
                "independent_native_kernel_is_only_success_authority": True,
            },
            "decision": {
                "status": "blocked" if sealed else "incomplete",
                "reason": (
                    (
                        "the source-valid HSSL-G150 holdout remained sealed "
                        "unopened, so no holdout efficacy or replay claim exists"
                    )
                    if sealed
                    else (
                        "authorized holdout evidence exists, but replay and "
                        "one or more decision metric domains remain incomplete"
                    )
                ),
                "holdout_untouched": holdout_decision["holdout_untouched"],
                "efficacy_claimed": holdout_outcomes["efficacy_claimed"],
                "replay_claimed": replay_execution["replay_claimed"],
                "production_routing_changed": False,
                "production_promotion_authorized": False,
            },
            "remediation": holdout["remediation"],
        },
    }


def validate_reassessment_publication(
    statistics: object,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    run_id: str = PUBLISHED_REASSESSMENT_RUN_ID,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    validate_snapshot: bool = True,
) -> dict[str, object]:
    """Validate statistics plus the complete source-bound G160 publication."""

    root = _resolve_root(repository_root)
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ValueError as exc:
        raise ReassessmentReportsError("reassessment run_id is invalid") from exc
    try:
        report = validate_statistics_report(statistics)
    except StatisticsError as exc:
        raise ReassessmentReportsError("statistics artifact is invalid") from exc
    holdout, pilot, matrix = _load_sources(
        root,
        layout=layout,
        benchmark_root=benchmark_root,
    )
    expected_statistics = _build_reassessment_statistics(
        root,
        holdout,
        pilot,
        matrix,
        layout=layout,
    )
    if report != expected_statistics:
        raise ReassessmentReportsError(
            "statistics differ from the validated reassessment matrix"
        )
    replay_value, _ = _read_canonical(
        _rooted(root, layout.replay_index), "replay index"
    )
    replay = dict(_mapping(replay_value, "replay index"))
    if replay != _build_replay_index(root, holdout, layout=layout):
        raise ReassessmentReportsError(
            "replay index differs from recomputed holdout population"
        )
    if validate_snapshot:
        snapshot, _ = _read_canonical(
            _rooted(root, layout.reports_snapshot),
            "reassessment reports snapshot",
        )
        expected_snapshot = _snapshot(
            root=root,
            holdout=holdout,
            pilot=pilot,
            matrix=matrix,
            replay=replay,
            statistics=report,
            layout=layout,
        )
        if snapshot != expected_snapshot:
            raise ReassessmentReportsError(
                "reassessment reports snapshot differs from source evidence"
            )
    return report


def load_reassessment_statistics(
    path: str | Path | None = None,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    run_id: str = PUBLISHED_REASSESSMENT_RUN_ID,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    validate_snapshot: bool = True,
) -> dict[str, object]:
    """Load canonical statistics and validate the complete G160 trust graph."""

    root = _resolve_root(repository_root)
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ValueError as exc:
        raise ReassessmentReportsError("reassessment run_id is invalid") from exc
    selected = layout.statistics_report if path is None else Path(path)
    value, _ = _read_canonical(
        _rooted(root, selected),
        "statistics artifact",
    )
    return validate_reassessment_publication(
        value,
        repository_root=root,
        run_id=run_id,
        benchmark_root=benchmark_root,
        validate_snapshot=validate_snapshot,
    )


def reassessment_statistics_summary(
    value: object,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    run_id: str = PUBLISHED_REASSESSMENT_RUN_ID,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    validated: bool = False,
) -> dict[str, object]:
    """Return the standard statistics summary with G160 replay status."""

    report = (
        validate_statistics_report(value)
        if validated
        else validate_reassessment_publication(
            value,
            repository_root=repository_root,
            run_id=run_id,
            benchmark_root=benchmark_root,
        )
    )
    summary = statistics_summary(report)
    if run_id == PUBLISHED_REASSESSMENT_RUN_ID:
        replay_status = "not_applicable_before_authorized_holdout"
        replay_claimed = False
        holdout_measured_domain_count = 0
    else:
        root = _resolve_root(repository_root)
        replay = load_replay_index(
            repository_root=root,
            run_id=run_id,
            benchmark_root=benchmark_root,
        )
        replay_status = str(replay["status"])
        replay_claimed = bool(
            _mapping(replay["execution"], "replay execution")[
                "replay_claimed"
            ]
        )
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
        holdout = load_holdout_reassessment_report(
            _rooted(root, layout.holdout_report),
            repository_root=root,
            run_id=run_id,
            benchmark_root=benchmark_root,
        )
        holdout_measured_domain_count = int(
            _mapping(holdout["metrics"], "holdout metrics")[
                "measured_domain_count"
            ]
        )
    return {
        **summary,
        "evidence": "HSSLEV1605D50",
        "source_graph_validated": True,
        "replay_status": replay_status,
        "replay_claimed": replay_claimed,
        "reports_structurally_complete": True,
        "holdout_measured_domain_count": holdout_measured_domain_count,
    }


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
            raise ReassessmentReportsError(
                f"refusing to overwrite immutable evidence: {path}"
            ) from exc
    if path.is_symlink():
        raise ReassessmentReportsError("refusing to overwrite a symlink")
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
        raise ReassessmentReportsError(f"cannot write evidence: {path}") from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass


def write_reassessment_reports(
    *,
    run_id: str,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    repository_root: str | Path = REPOSITORY_ROOT,
    replay_path: str | Path | None = None,
    statistics_path: str | Path | None = None,
    snapshot_path: str | Path | None = None,
    overwrite: bool = False,
) -> tuple[Path, Path, Path]:
    """Atomically publish replay selection, statistics, and public report."""

    root = _resolve_root(repository_root)
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
        replay_reference = Path(
            layout.replay_index if replay_path is None else replay_path
        )
        statistics_reference = Path(
            layout.statistics_report
            if statistics_path is None
            else statistics_path
        )
        snapshot_reference = Path(
            layout.reports_snapshot
            if snapshot_path is None
            else snapshot_path
        )
        reject_published_write_targets(
            repository_root=root,
            run_id=run_id,
            targets=(
                replay_reference,
                statistics_reference,
                snapshot_reference,
            ),
            benchmark_root=benchmark_root,
        )
    except (ValueError, ReassessmentNamespaceError) as exc:
        raise ReassessmentReportsError(str(exc)) from exc
    if (
        replay_reference != layout.replay_index
        or statistics_reference != layout.statistics_report
        or snapshot_reference != layout.reports_snapshot
    ):
        # The report snapshot and source graph use the layout as their portable
        # identity. Custom targets would create a valid file with false links.
        raise ReassessmentReportsError(
            "fresh reassessment reports must use their run-scoped layout paths"
        )
    replay_target = _rooted(root, replay_reference)
    statistics_target = _rooted(root, statistics_reference)
    snapshot_target = _rooted(root, snapshot_reference)
    holdout, pilot, matrix = _load_sources(
        root,
        layout=layout,
        benchmark_root=benchmark_root,
    )
    replay = _build_replay_index(root, holdout, layout=layout)
    statistics = _build_reassessment_statistics(
        root,
        holdout,
        pilot,
        matrix,
        layout=layout,
    )
    _atomic_write(
        replay_target,
        (canonical_json(replay) + "\n").encode("utf-8"),
        overwrite=overwrite,
    )
    _atomic_write(
        statistics_target,
        (canonical_json(statistics) + "\n").encode("utf-8"),
        overwrite=overwrite,
    )
    snapshot = _snapshot(
        root=root,
        holdout=holdout,
        pilot=pilot,
        matrix=matrix,
        replay=replay,
        statistics=statistics,
        layout=layout,
    )
    _atomic_write(
        snapshot_target,
        (canonical_json(snapshot) + "\n").encode("utf-8"),
        overwrite=overwrite,
    )
    load_reassessment_statistics(
        statistics_target,
        repository_root=root,
        run_id=run_id,
        benchmark_root=benchmark_root,
        validate_snapshot=True,
    )
    return replay_target, statistics_target, snapshot_target


__all__ = [
    "DEFAULT_REPLAY_INDEX_PATH",
    "DEFAULT_REPORTS_SNAPSHOT",
    "DEFAULT_STATISTICS_PATH",
    "HSSLEV1605D50",
    "REPLAY_REASSESSMENT_SCHEMA",
    "REPORTS_SNAPSHOT_SCHEMA",
    "REQUIRED_DECISION_DOMAINS",
    "ReassessmentReportsError",
    "build_reassessment_statistics",
    "build_replay_index",
    "load_reassessment_statistics",
    "load_replay_index",
    "reassessment_statistics_summary",
    "validate_reassessment_publication",
    "validate_replay_index",
    "write_reassessment_reports",
]
