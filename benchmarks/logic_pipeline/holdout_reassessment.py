"""Source-bound HSSL reassessment holdout decision.

HSSL-G150 may open the reviewed holdout only after the exact HSSL-G140
decision has frozen a non-empty shortlist and explicitly authorized access.
The checked-in HSSL-G140 decision is source-valid but unauthorized, so this
module publishes the only truthful downstream result: a content-addressed,
sealed-unopened holdout receipt.  It binds the future paired execution
contract without loading reviewed holdout semantics, creating an execution
namespace, constructing a run plan, or invoking a backend.
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
from .ablation import AblationPlan, AblationRunResult
from .cases import (
    DEFAULT_MANIFEST_PATH,
    FROZEN_CORPUS_MANIFEST_SHA256,
    FROZEN_SPLIT_SHA256,
    corpus_manifest_sha256,
    load_manifest,
)
from .contracts import (
    CaseResultRecord,
    OutcomeStatus,
    Split,
    StageName,
    canonical_json,
)
from .holdout_execution import (
    AuthorizedHoldoutRun,
    HoldoutExecutionError,
    HoldoutExecutionReceipt,
    PilotAuthorizationReceipt,
)
from .pilot_reassessment import (
    DEFAULT_PILOT_REASSESSMENT_PATH,
    PILOT_REASSESSMENT_SCHEMA,
    PilotReassessmentError,
    load_pilot_reassessment_report,
)
from .reassessment_namespace import (
    PUBLISHED_REASSESSMENT_RUN_ID,
    ReassessmentNamespaceError,
    ReassessmentRunLayout,
    reject_published_write_targets,
)
HOLDOUT_REASSESSMENT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.reassessment-holdout.v1"
)
HOLDOUT_REASSESSMENT_SNAPSHOT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "reassessment-holdout-snapshot.v1"
)
HOLDOUT_REASSESSMENT_RUN_ID: Final = "holdout-reassessment-v2"
_PUBLISHED_LAYOUT: Final = ReassessmentRunLayout.for_run(
    PUBLISHED_REASSESSMENT_RUN_ID
)
DEFAULT_HOLDOUT_REASSESSMENT_PATH: Final = _PUBLISHED_LAYOUT.holdout_report
DEFAULT_HOLDOUT_REASSESSMENT_SNAPSHOT: Final = _PUBLISHED_LAYOUT.holdout_snapshot
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
VALIDATION_COMMAND: Final = (
    "python benchmarks/logic_pipeline/report.py --gate holdout "
    "--artifact workspace/benchmarks/hammer-symai-spacy-leanstral/"
    "reassessment-v2/results/holdout-evaluation-v2.json"
)
CACHE_MODES: Final = ("cold", "warm")
METRIC_DOMAINS: Final = (
    "safety",
    "quality",
    "latency",
    "resource",
    "routing",
)
# An authorized four-arm shortlist yields 100 holdout coordinates, and the
# source-bound report retains results both as execution evidence and outcomes.
_MAX_ARTIFACT_BYTES: Final = 128 * 1024 * 1024


class HoldoutReassessmentError(ValueError):
    """Raised when HSSL-G150 evidence is stale, invented, or noncanonical."""


def _holdout_run_id(run_id: str) -> str:
    return (
        HOLDOUT_REASSESSMENT_RUN_ID
        if run_id == PUBLISHED_REASSESSMENT_RUN_ID
        else run_id
    )


def HSSLEV1507C49() -> str:
    """Return the AST-verifiable HSSL-G150 holdout evidence statement."""

    return (
        "exact HSSL-G140-authorized A0 and shortlist paired holdout boundary "
        "with source-first access audit, identical frozen manifests, "
        "counterbalanced cold and warm execution, native-kernel authority, "
        "terminal pair accounting, no tuning or substitution, and a "
        "zero-activity sealed result when authorization is absent"
    )


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise HoldoutReassessmentError(f"{field} must be an object")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise HoldoutReassessmentError(f"{field} must be an array")
    return value


def _resolve_root(repository_root: str | Path) -> Path:
    try:
        root = Path(repository_root).resolve(strict=True)
    except OSError as exc:
        raise HoldoutReassessmentError(
            "repository root is unavailable"
        ) from exc
    if not root.is_dir():
        raise HoldoutReassessmentError(
            "repository root is not a directory"
        )
    return root


def _rooted(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise HoldoutReassessmentError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_nonfinite(token: str) -> object:
    raise HoldoutReassessmentError(
        f"non-finite JSON number is forbidden: {token}"
    )


def _read_canonical(path: Path, field: str) -> tuple[object, bytes]:
    try:
        file_stat = path.lstat()
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(
            file_stat.st_mode
        ):
            raise HoldoutReassessmentError(
                f"{field} must be a regular non-symlink file"
            )
        if file_stat.st_size <= 0 or file_stat.st_size > _MAX_ARTIFACT_BYTES:
            raise HoldoutReassessmentError(
                f"{field} size is outside the safe bound"
            )
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except HoldoutReassessmentError:
        raise
    except (OSError, UnicodeError) as exc:
        raise HoldoutReassessmentError(
            f"cannot read {field}: {path}"
        ) from exc
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise HoldoutReassessmentError(
            f"{field} is not canonical newline JSON"
        )
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, HoldoutReassessmentError) as exc:
        raise HoldoutReassessmentError(
            f"{field} is not strict JSON"
        ) from exc
    try:
        expected = (canonical_json(value) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HoldoutReassessmentError(
            f"{field} is not canonically serializable"
        ) from exc
    if raw != expected:
        raise HoldoutReassessmentError(f"{field} is not canonical JSON")
    return value, raw


def _null_metrics() -> dict[str, object]:
    values: dict[str, dict[str, object]] = {
        "safety": {
            "invalid_control_kernel_false_positive_count": None,
            "a0_solved_regression_rate": None,
            "unexplained_a0_regressions": None,
        },
        "quality": {
            "kernel_verified_completion_rate": None,
            "paired_verified_delta_vs_a0": None,
            "semantic_equivalence_acceptance_rate": None,
        },
        "latency": {
            "p95_latency_seconds": None,
            "paired_p95_delta_vs_a0": None,
        },
        "resource": {
            "peak_rss_bytes": None,
            "model_call_count": None,
            "accelerator_minutes": None,
        },
        "routing": {
            "unnecessary_call_rate": None,
            "escalation_precision": None,
            "unique_kernel_verified_wins": None,
        },
    }
    reason = (
        "HSSL-G140 did not authorize holdout access; null is retained rather "
        "than converting unobserved efficacy or cost into zero"
    )
    return {
        "required_domains": list(METRIC_DOMAINS),
        "domains": [
            {
                "domain": domain,
                "status": "not_observed",
                "complete": False,
                "values": values[domain],
                "reason": reason,
            }
            for domain in METRIC_DOMAINS
        ],
        "measured_domain_count": 0,
        "complete": False,
        "status": "not_applicable_before_authorization",
        "cold_warm_collapsed": False,
        "missingness_synthesized_as_zero": False,
    }


def _authorization_audit(
    *,
    pilot: Mapping[str, object],
    pilot_bytes_sha256: str,
) -> dict[str, object]:
    shortlist = _mapping(pilot["shortlist"], "pilot.shortlist")
    holdout = _mapping(pilot["holdout"], "pilot.holdout")
    decision = _mapping(pilot["decision"], "pilot.decision")
    deep_freeze = _mapping(pilot["deep_freeze"], "pilot.deep_freeze")
    payload: dict[str, object] = {
        "source_artifact_sha256": pilot["artifact_sha256"],
        "source_bytes_sha256": pilot_bytes_sha256,
        "source_freeze_sha256": deep_freeze["freeze_sha256"],
        "checks": {
            "source_revalidated": True,
            "shortlist_frozen": shortlist["frozen"],
            "shortlist_nonempty": bool(shortlist["selected_variant_ids"]),
            "candidate_count_within_limit": (
                1 <= int(shortlist["selected_count"]) <= 4
            ),
            "decision_complete": decision["status"] == "complete",
            "holdout_explicitly_authorized": holdout["authorized"] is True,
            "holdout_previously_unopened": (
                holdout["outcomes_inspected"] is False
            ),
            "tuning_forbidden": deep_freeze["tuning_permitted"] is False,
        },
        "satisfied": False,
        "rejection_stage": "before_holdout_activity",
        "reviewed_holdout_inputs_loaded": False,
        "holdout_semantics_inspected": False,
        "execution_namespace_created": False,
        "execution_write_count": 0,
        "backend_call_count": 0,
        "audit_sha256": "",
    }
    checks = _mapping(payload["checks"], "authorization audit checks")
    payload["satisfied"] = all(item is True for item in checks.values())
    payload["rejection_stage"] = (
        None if payload["satisfied"] else "before_holdout_activity"
    )
    payload["audit_sha256"] = _sha(
        {key: item for key, item in payload.items() if key != "audit_sha256"}
    )
    return payload


def _authorization_from_pilot(
    pilot: Mapping[str, object], *, run_id: str
) -> PilotAuthorizationReceipt:
    shortlist = _mapping(pilot["shortlist"], "pilot.shortlist")
    holdout = _mapping(pilot["holdout"], "pilot.holdout")
    decision = _mapping(pilot["decision"], "pilot.decision")
    deep_freeze = _mapping(pilot["deep_freeze"], "pilot.deep_freeze")
    inputs = _mapping(deep_freeze["inputs"], "pilot.deep_freeze.inputs")
    selected = _array(
        shortlist["selected_variant_ids"],
        "pilot.shortlist.selected_variant_ids",
    )
    if (
        pilot.get("run_id") != run_id
        or decision.get("status") != "complete"
        or shortlist.get("frozen") is not True
        or not selected
        or holdout.get("authorized") is not True
        or holdout.get("outcomes_inspected") is not False
        or deep_freeze.get("tuning_permitted") is not False
    ):
        raise HoldoutReassessmentError(
            "pilot did not satisfy the holdout authorization boundary"
        )
    source = _mapping(inputs["source"], "pilot.deep_freeze.inputs.source")
    prompts = _mapping(inputs["prompts"], "pilot.deep_freeze.inputs.prompts")
    policies = _mapping(inputs["policies"], "pilot.deep_freeze.inputs.policies")
    models = _mapping(
        inputs["model_identities"],
        "pilot.deep_freeze.inputs.model_identities",
    )
    environment = (
        models
        if run_id == PUBLISHED_REASSESSMENT_RUN_ID
        else _mapping(
            inputs.get("environment"),
            "pilot.deep_freeze.inputs.environment",
        )
    )
    thresholds = _mapping(
        inputs["thresholds"],
        "pilot.deep_freeze.inputs.thresholds",
    )
    try:
        return PilotAuthorizationReceipt.create(
            authorization_id=f"hssl-{_sha(run_id)[:24]}",
            pilot_run_id=run_id,
            pilot_gate_sha256=str(pilot["artifact_sha256"]),
            source_commit=str(source["commit"]),
            environment_sha256=str(environment["sha256"]),
            corpus_manifest_sha256=FROZEN_CORPUS_MANIFEST_SHA256,
            holdout_split_sha256=FROZEN_SPLIT_SHA256[Split.HOLDOUT],
            shortlist_variant_ids=[str(item) for item in selected],
            prompts_sha256=str(prompts["sha256"]),
            policy_sha256=str(policies["sha256"]),
            model_identities_sha256=str(models["sha256"]),
            thresholds_sha256=str(thresholds["sha256"]),
            protocol_sha256=str(pilot["protocol_sha256"]),
        )
    except (HoldoutExecutionError, TypeError, ValueError) as exc:
        raise HoldoutReassessmentError(
            "pilot authorization could not be projected into the execution "
            "boundary"
        ) from exc


def build_holdout_authorization(
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    run_id: str,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> PilotAuthorizationReceipt:
    """Create the execution handoff only after source-valid pilot authorization.

    This function does not load the reviewed corpus or create an execution
    namespace.  A caller may load the holdout only after it returns.
    """

    root = _resolve_root(repository_root)
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
        pilot = load_pilot_reassessment_report(
            _rooted(root, layout.pilot_report),
            repository_root=root,
            run_id=run_id,
            benchmark_root=benchmark_root,
        )
    except (ValueError, PilotReassessmentError) as exc:
        raise HoldoutReassessmentError(
            "HSSL-G140 prerequisite failed source validation"
        ) from exc
    return _authorization_from_pilot(pilot, run_id=run_id)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)], 6)


def _build_authorized_holdout_report(
    *,
    pilot: Mapping[str, object],
    pilot_bytes: bytes,
    layout: ReassessmentRunLayout,
    audit: Mapping[str, object],
    authorized_run: AuthorizedHoldoutRun,
    holdout_manifest: tuple[object, ...],
) -> dict[str, object]:
    """Project an authenticated execution into the persisted G150 report."""

    try:
        authorization = _authorization_from_pilot(
            pilot,
            run_id=layout.run_id,
        )
        receipt = HoldoutExecutionReceipt.from_dict(
            authorized_run.receipt.to_dict()
        )
    except (AttributeError, HoldoutExecutionError, TypeError, ValueError) as exc:
        raise HoldoutReassessmentError(
            "authorized holdout execution evidence is invalid"
        ) from exc
    execution = authorized_run.execution
    if not isinstance(execution, AblationRunResult):
        raise HoldoutReassessmentError(
            "authorized holdout execution result is invalid"
        )
    plan = execution.plan
    results = tuple(execution.results)
    shortlist = _mapping(pilot["shortlist"], "pilot.shortlist")
    selected = tuple(
        str(item)
        for item in _array(
            shortlist["selected_variant_ids"],
            "pilot.shortlist.selected_variant_ids",
        )
    )
    deep_freeze = _mapping(pilot["deep_freeze"], "pilot.deep_freeze")
    freeze_inputs = _mapping(deep_freeze["inputs"], "deep_freeze.inputs")
    manifest_by_id = {
        str(getattr(item, "case_id")): item for item in holdout_manifest
    }
    expected_cases = tuple(str(getattr(item, "case_id")) for item in holdout_manifest)
    expected_coordinates = (
        len(expected_cases) * len(CACHE_MODES) * (1 + len(selected))
    )
    expected_job_ids = tuple(job.job_id for job in plan.jobs)
    expected_namespaces = tuple(
        contract.cache_namespace for contract in plan.run_contracts
    )
    if (
        audit.get("satisfied") is not True
        or receipt.authorization_sha256 != authorization.authorization_sha256
        or receipt.pilot_gate_sha256 != pilot["artifact_sha256"]
        or receipt.source_commit != authorization.source_commit
        or receipt.environment_sha256 != authorization.environment_sha256
        or receipt.plan_sha256 != plan.digest
        or receipt.result_sha256s != tuple(item.digest for item in results)
        or receipt.run_id != plan.run_id
        or plan.run_id != layout.run_id
        or plan.protocol_sha256 != authorization.protocol_sha256
        or plan.case_manifest_sha256
        != authorization.corpus_manifest_sha256
        or plan.environment_sha256 != authorization.environment_sha256
        or plan.split is not Split.HOLDOUT
        or plan.variant_ids != ("A0", *selected)
        or tuple(item.value for item in plan.cache_modes) != CACHE_MODES
        or plan.case_ids != expected_cases
        or execution.contracts != plan.run_contracts
        or execution.executed_job_ids != expected_job_ids
        or execution.resumed_job_ids
        or receipt.executed_job_ids != expected_job_ids
        or receipt.cache_namespaces != expected_namespaces
        or len(receipt.access_audit_sha256s) != len(plan.run_contracts)
        or not execution.complete
        or not receipt.complete
        or len(results) != expected_coordinates
        or any(
            item.run_id != plan.run_id
            or item.protocol_sha256 != plan.protocol_sha256
            or item.case_manifest_sha256 != plan.case_manifest_sha256
            or item.split is not Split.HOLDOUT
            or any(
                stage.provenance.environment_sha256
                != authorization.environment_sha256
                for stage in item.stages
            )
            for item in results
        )
        or any(
            job.case_sha256
            != getattr(manifest_by_id.get(job.case_id), "case_sha256", None)
            or hashlib.sha256(
                str(_mapping(job.input_data, "holdout input")["text"]).encode(
                    "utf-8"
                )
            ).hexdigest()
            != getattr(manifest_by_id.get(job.case_id), "source_sha256", None)
            for job in plan.jobs
        )
    ):
        raise HoldoutReassessmentError(
            "authorized execution differs from the frozen pilot handoff"
        )

    by_coordinate = {
        (item.case_id, item.cache_mode.value, item.variant_id): item
        for item in results
    }
    if len(by_coordinate) != len(results):
        raise HoldoutReassessmentError(
            "authorized execution contains duplicate coordinates"
        )
    expected_keys = {
        (case_id, mode, variant)
        for case_id in expected_cases
        for mode in CACHE_MODES
        for variant in ("A0", *selected)
    }
    if set(by_coordinate) != expected_keys:
        raise HoldoutReassessmentError(
            "authorized execution is not the complete paired holdout"
        )

    paired_deltas: list[int] = []
    baseline_regressions = 0
    unique_wins = 0
    for case_id in expected_cases:
        for mode in CACHE_MODES:
            baseline = by_coordinate[(case_id, mode, "A0")]
            for variant_id in selected:
                candidate = by_coordinate[(case_id, mode, variant_id)]
                paired_deltas.append(
                    int(candidate.kernel_accepted)
                    - int(baseline.kernel_accepted)
                )
                baseline_regressions += (
                    baseline.kernel_accepted
                    and not candidate.kernel_accepted
                )
                unique_wins += (
                    candidate.kernel_accepted
                    and not baseline.kernel_accepted
                )
    candidate_results = [
        item for item in results if item.variant_id in selected
    ]
    candidate_verified = sum(
        item.kernel_accepted for item in candidate_results
    )
    baseline_results = [
        item for item in results if item.variant_id == "A0"
    ]
    baseline_verified = sum(item.kernel_accepted for item in baseline_results)
    invalid_case_ids = {
        job.case_id
        for job in plan.jobs
        if _mapping(job.input_data, "holdout case input").get(
            "expected_class"
        )
        in {"disproved", "unsupported"}
    }
    invalid_false_positives = sum(
        item.kernel_accepted and item.case_id in invalid_case_ids
        for item in results
    )
    latencies = [
        sum(stage.telemetry.wall_time_ms for stage in item.stages)
        for item in candidate_results
    ]
    peak_memory = max(
        (
            stage.telemetry.peak_memory_bytes
            for item in results
            for stage in item.stages
        ),
        default=0,
    )
    model_calls = sum(
        stage.telemetry.model_calls
        for item in results
        for stage in item.stages
    )
    backend_calls = sum(
        stage.stage is not StageName.KERNEL
        for item in results
        for stage in item.stages
    )
    observed_pairs = 10 * len(CACHE_MODES) * len(selected)
    explicit_failures = sum(
        item.status
        in {
            OutcomeStatus.UNAVAILABLE,
            OutcomeStatus.INFRASTRUCTURE_FAILURE,
            OutcomeStatus.REJECTED,
        }
        for item in candidate_results
    )
    semantic_reason = (
        "no independently reviewed holdout semantic-equivalence receipt was "
        "supplied; proof outcomes cannot substitute for semantic quality"
    )
    metrics = {
        "required_domains": list(METRIC_DOMAINS),
        "domains": [
            {
                "domain": "safety",
                "status": "measured",
                "complete": True,
                "values": {
                    "invalid_control_kernel_false_positive_count": (
                        invalid_false_positives
                    ),
                    "a0_solved_regression_rate": (
                        None
                        if baseline_verified == 0
                        else baseline_regressions
                        / (baseline_verified * len(selected))
                    ),
                    "unexplained_a0_regressions": baseline_regressions,
                },
                "reason": None,
            },
            {
                "domain": "quality",
                "status": "incomplete",
                "complete": False,
                "values": {
                    "kernel_verified_completion_rate": (
                        candidate_verified / len(candidate_results)
                    ),
                    "paired_verified_delta_vs_a0": (
                        sum(paired_deltas) / len(paired_deltas)
                    ),
                    "semantic_equivalence_acceptance_rate": None,
                },
                "reason": semantic_reason,
            },
            {
                "domain": "latency",
                "status": "incomplete",
                "complete": False,
                "values": {
                    "p95_latency_seconds": (
                        None if not latencies else _p95(latencies) / 1000
                    ),
                    "paired_p95_delta_vs_a0": None,
                },
                "reason": (
                    "paired p95 delta requires per-arm aggregation in the "
                    "statistics publication"
                ),
            },
            {
                "domain": "resource",
                "status": "incomplete",
                "complete": False,
                "values": {
                    "peak_rss_bytes": peak_memory,
                    "model_call_count": model_calls,
                    "accelerator_minutes": None,
                },
                "reason": (
                    "accelerator-minute telemetry is not present in the "
                    "execution receipt"
                ),
            },
            {
                "domain": "routing",
                "status": "incomplete",
                "complete": False,
                "values": {
                    "unnecessary_call_rate": None,
                    "escalation_precision": None,
                    "unique_kernel_verified_wins": unique_wins,
                },
                "reason": (
                    "routing usefulness requires reviewed per-call attribution"
                ),
            },
        ],
        "measured_domain_count": 1,
        "complete": False,
        "status": "incomplete_measured_evidence",
        "cold_warm_collapsed": False,
        "missingness_synthesized_as_zero": False,
    }
    contract = {
        "baseline_variant_id": "A0",
        "candidate_variant_ids": list(selected),
        "evaluation_variant_ids": ["A0", *selected],
        "configuration_sha256s": dict(
            authorization.configuration_sha256s
        ),
        "cache_modes": list(CACHE_MODES),
        "cache_namespaces_isolated": True,
        "identical_case_and_source_manifest_required": True,
        "manifest_sha256": FROZEN_SPLIT_SHA256[Split.HOLDOUT],
        "pair_key_dimensions": [
            "case_id",
            "source_sha256",
            "cache_mode",
            "candidate_variant_id",
        ],
        "expected_pair_count": observed_pairs,
        "balanced_order": {
            "required": True,
            "method": "case-cache parity crossover",
            "rule": (
                "alternate A0-first and candidate-first by frozen case "
                "ordinal and invert the leading arm for warm cache pairs"
            ),
            "scheduled_coordinates": [
                {
                    "ordinal": job.ordinal,
                    "case_id": job.case_id,
                    "cache_mode": job.cache_mode.value,
                    "variant_id": job.variant_id,
                    "job_id": job.job_id,
                }
                for job in plan.jobs
            ],
            "status": "executed",
        },
        "source_commit": authorization.source_commit,
        "environment_sha256": authorization.environment_sha256,
        "protocol_sha256": pilot["protocol_sha256"],
        "registry_sha256": pilot["registry_sha256"],
        "prompts_sha256": authorization.prompts_sha256,
        "policies_sha256": authorization.policy_sha256,
        "model_identities_sha256": authorization.model_identities_sha256,
        "resource_policy_sha256": _mapping(
            freeze_inputs["resource_policy"],
            "deep_freeze.inputs.resource_policy",
        )["sha256"],
        "thresholds_sha256": authorization.thresholds_sha256,
        "source_freeze_sha256": deep_freeze["freeze_sha256"],
        "access_audit_required_before_activity": True,
        "one_access_audit_per_run_contract": True,
        "native_kernel_only_success": True,
        "every_scheduled_pair_terminal": True,
        "baseline_only_execution_forbidden": True,
        "arm_substitution_forbidden": True,
        "fallback_forbidden": True,
        "resume_forbidden": True,
        "tuning_after_first_access_forbidden": True,
        "production_promotion_authorized": False,
    }
    executed_audit: dict[str, object] = {
        **dict(audit),
        "reviewed_holdout_inputs_loaded": True,
        "holdout_semantics_inspected": True,
        "execution_namespace_created": True,
        "execution_write_count": len(results) + 3,
        "backend_call_count": backend_calls,
        "audit_sha256": "",
    }
    executed_audit["audit_sha256"] = _sha(
        {
            key: item
            for key, item in executed_audit.items()
            if key != "audit_sha256"
        }
    )
    report: dict[str, object] = {
        "schema": HOLDOUT_REASSESSMENT_SCHEMA,
        "evidence": "HSSLEV1507C49",
        "evidence_statement": HSSLEV1507C49(),
        "benchmark_id": BENCHMARK_ID,
        "run_id": _holdout_run_id(layout.run_id),
        "status": "incomplete",
        "source_binding": {
            "kind": "hssl_g140_pilot_authorization",
            "path": layout.pilot_report.as_posix(),
            "schema": PILOT_REASSESSMENT_SCHEMA,
            "bytes_sha256": _sha_bytes(pilot_bytes),
            "semantic_sha256": pilot["artifact_sha256"],
            "deep_freeze_sha256": deep_freeze["freeze_sha256"],
            "source_validated": True,
        },
        "prerequisite": {
            "goal_id": "HSSL-G140",
            "required_status": "complete",
            "observed_status": "complete",
            "shortlist_frozen": True,
            "selected_variant_ids": list(selected),
            "selected_count": len(selected),
            "holdout_authorized": True,
            "authorization_sha256": authorization.authorization_sha256,
            "satisfied": True,
            "failure_kind": None,
            "failure_reason": None,
        },
        "authorization_audit": executed_audit,
        "holdout_manifest": {
            "corpus_manifest_sha256": FROZEN_CORPUS_MANIFEST_SHA256,
            "split": "holdout",
            "split_sha256": FROZEN_SPLIT_SHA256[Split.HOLDOUT],
            "case_count": len(expected_cases),
            "case_ids": list(expected_cases),
            "case_sha256s": [
                getattr(manifest_by_id[case_id], "case_sha256")
                for case_id in expected_cases
            ],
            "source_sha256s": [
                getattr(manifest_by_id[case_id], "source_sha256")
                for case_id in expected_cases
            ],
            "reviewed_inputs_loaded": True,
            "semantic_targets_inspected": True,
            "outcomes_inspected": True,
        },
        "frozen_execution_contract": contract,
        "candidate_dispositions": [
            {
                "variant_id": item["variant_id"],
                "configuration_sha256": item["configuration_sha256"],
                "eligible": item["eligible"],
                "scheduled": item["variant_id"] in selected,
                "ineligibility_reasons": item["ineligibility_reasons"],
            }
            for item in _array(
                pilot["candidate_evidence"],
                "pilot.candidate_evidence",
            )
        ],
        "execution_evidence": {
            "authorization": authorization.to_dict(),
            "plan": plan.to_dict(),
            "receipt": receipt.to_dict(),
            "case_results": [item.to_dict() for item in results],
        },
        "access": {
            "status": "executed",
            "authorized": True,
            "access_audit_count": len(receipt.access_audit_sha256s),
            "access_audit_sha256s": list(
                receipt.access_audit_sha256s
            ),
            "first_access_recorded": True,
            "cache_namespaces_opened": list(receipt.cache_namespaces),
            "execution_namespace_created": True,
            "execution_write_count": len(results) + 3,
            "backend_call_count": backend_calls,
            "outcomes_inspected": True,
            "tuning_after_access": False,
        },
        "outcomes": {
            "status": "complete",
            "scheduled_pair_count": observed_pairs,
            "observed_pair_count": observed_pairs,
            "terminal_pair_count": observed_pairs,
            "explicit_failure_pair_count": explicit_failures,
            "case_results": [item.to_dict() for item in results],
            "kernel_verified_success_count": candidate_verified,
            "efficacy_claimed": True,
            "missingness_converted_to_failure_or_zero": False,
        },
        "metrics": metrics,
        "decision": {
            "status": "incomplete",
            "structurally_valid": True,
            "seal_status": "opened_executed",
            "holdout_untouched": False,
            "paired_evaluation_complete": True,
            "efficacy_status": "measured",
            "production_promotion_authorized": False,
            "reason": (
                "paired holdout execution completed, but independent semantic, "
                "accelerator, and routing receipts remain incomplete"
            ),
        },
        "remediation": [
            {
                "priority": 1,
                "scope": list(selected),
                "action": (
                    "attach source-bound independent holdout semantic, "
                    "accelerator-resource, and per-call routing receipts"
                ),
                "rerun_required": False,
            }
        ],
        "artifact_sha256": "",
    }
    report["artifact_sha256"] = _sha(
        {key: value for key, value in report.items() if key != "artifact_sha256"}
    )
    return report


def build_holdout_reassessment_report(
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    run_id: str = PUBLISHED_REASSESSMENT_RUN_ID,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    authorized_run: AuthorizedHoldoutRun | None = None,
) -> dict[str, object]:
    """Revalidate HSSL-G140 and derive the HSSL-G150 phase result.

    The current source is intentionally handled before any holdout execution
    API is imported or called.  If the checked source later authorizes access,
    this persisted-result builder fails closed until an actual
    :mod:`holdout_execution` receipt is supplied and validated.
    """

    root = _resolve_root(repository_root)
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ValueError as exc:
        raise HoldoutReassessmentError("reassessment run_id is invalid") from exc
    pilot_path = _rooted(root, layout.pilot_report)
    try:
        pilot = load_pilot_reassessment_report(
            pilot_path,
            repository_root=root,
            run_id=run_id,
            benchmark_root=benchmark_root,
        )
    except PilotReassessmentError as exc:
        raise HoldoutReassessmentError(
            "HSSL-G140 prerequisite failed source validation"
        ) from exc
    pilot_value, pilot_bytes = _read_canonical(
        pilot_path,
        "pilot reassessment artifact",
    )
    if pilot_value != pilot:
        raise HoldoutReassessmentError(
            "validated pilot differs from its canonical artifact"
        )
    shortlist = _mapping(pilot["shortlist"], "pilot.shortlist")
    holdout = _mapping(pilot["holdout"], "pilot.holdout")
    decision = _mapping(pilot["decision"], "pilot.decision")
    deep_freeze = _mapping(pilot["deep_freeze"], "pilot.deep_freeze")
    selected = _array(
        shortlist["selected_variant_ids"],
        "pilot.shortlist.selected_variant_ids",
    )
    audit = _authorization_audit(
        pilot=pilot, pilot_bytes_sha256=_sha_bytes(pilot_bytes)
    )
    # This is public manifest metadata only: identities and content digests,
    # never reviewed source text, semantic targets, or proof obligations.
    manifest = load_manifest(root / DEFAULT_MANIFEST_PATH)
    holdout_cases = tuple(
        item for item in manifest.cases if item.split is Split.HOLDOUT
    )
    if (
        corpus_manifest_sha256(manifest) != FROZEN_CORPUS_MANIFEST_SHA256
        or len(holdout_cases) != 10
    ):
        raise HoldoutReassessmentError(
            "frozen public holdout manifest identity changed"
        )
    if audit["satisfied"] is True:
        if authorized_run is None:
            raise HoldoutReassessmentError(
                "authorized HSSL-G140 evidence requires a real holdout "
                "execution receipt; refusing to synthesize an executed result"
            )
        return _build_authorized_holdout_report(
            pilot=pilot,
            pilot_bytes=pilot_bytes,
            layout=layout,
            audit=audit,
            authorized_run=authorized_run,
            holdout_manifest=holdout_cases,
        )
    if authorized_run is not None:
        raise HoldoutReassessmentError(
            "holdout execution evidence was supplied without authorization"
        )
    if (
        decision["status"] != "incomplete"
        or selected
        or shortlist["frozen"] is not True
        or holdout["authorized"] is not False
        or holdout["status"] != "sealed"
        or holdout["outcomes_inspected"] is not False
    ):
        raise HoldoutReassessmentError(
            "unauthorized prerequisite is not the exact frozen sealed state"
        )

    # Read only the public frozen manifest metadata.  Reviewed case inputs and
    # semantic targets remain sealed.
    freeze_inputs = _mapping(deep_freeze["inputs"], "deep_freeze.inputs")
    contract: dict[str, object] = {
        "baseline_variant_id": "A0",
        "candidate_variant_ids": selected,
        "evaluation_variant_ids": [],
        "configuration_sha256s": {},
        "cache_modes": list(CACHE_MODES),
        "cache_namespaces_isolated": True,
        "identical_case_and_source_manifest_required": True,
        "manifest_sha256": FROZEN_SPLIT_SHA256[Split.HOLDOUT],
        "pair_key_dimensions": [
            "case_id",
            "source_sha256",
            "cache_mode",
            "candidate_variant_id",
        ],
        "expected_pair_count": len(holdout_cases)
        * len(CACHE_MODES)
        * len(selected),
        "balanced_order": {
            "required": True,
            "method": "case-cache parity crossover",
            "rule": (
                "alternate A0-first and candidate-first by frozen case "
                "ordinal and invert the leading arm for warm cache pairs"
            ),
            "scheduled_coordinates": [],
            "status": "not_scheduled_before_authorization",
        },
        "source_commit": _mapping(
            freeze_inputs["source"], "deep_freeze.inputs.source"
        )["commit"],
        **(
            {}
            if run_id == PUBLISHED_REASSESSMENT_RUN_ID
            else {
                "environment_sha256": _mapping(
                    freeze_inputs["environment"],
                    "deep_freeze.inputs.environment",
                )["sha256"]
            }
        ),
        "protocol_sha256": pilot["protocol_sha256"],
        "registry_sha256": pilot["registry_sha256"],
        "prompts_sha256": _mapping(
            freeze_inputs["prompts"], "deep_freeze.inputs.prompts"
        )["sha256"],
        "policies_sha256": _mapping(
            freeze_inputs["policies"], "deep_freeze.inputs.policies"
        )["sha256"],
        "model_identities_sha256": _mapping(
            freeze_inputs["model_identities"],
            "deep_freeze.inputs.model_identities",
        )["sha256"],
        "resource_policy_sha256": _mapping(
            freeze_inputs["resource_policy"],
            "deep_freeze.inputs.resource_policy",
        )["sha256"],
        "thresholds_sha256": _mapping(
            freeze_inputs["thresholds"], "deep_freeze.inputs.thresholds"
        )["sha256"],
        "source_freeze_sha256": deep_freeze["freeze_sha256"],
        "access_audit_required_before_activity": True,
        "one_access_audit_per_run_contract": True,
        "native_kernel_only_success": True,
        "every_scheduled_pair_terminal": True,
        "baseline_only_execution_forbidden": True,
        "arm_substitution_forbidden": True,
        "fallback_forbidden": True,
        "resume_forbidden": True,
        "tuning_after_first_access_forbidden": True,
        "production_promotion_authorized": False,
    }
    candidate_dispositions: list[dict[str, object]] = []
    for raw_candidate in _array(
        pilot["candidate_evidence"], "pilot.candidate_evidence"
    ):
        item = _mapping(raw_candidate, "pilot.candidate_evidence[]")
        candidate_dispositions.append(
            {
                "variant_id": item["variant_id"],
                "configuration_sha256": item["configuration_sha256"],
                "eligible": item["eligible"],
                "scheduled": False,
                "ineligibility_reasons": item["ineligibility_reasons"],
            }
        )
    report: dict[str, object] = {
        "schema": HOLDOUT_REASSESSMENT_SCHEMA,
        "evidence": "HSSLEV1507C49",
        "evidence_statement": HSSLEV1507C49(),
        "benchmark_id": BENCHMARK_ID,
        "run_id": _holdout_run_id(run_id),
        "status": "blocked",
        "source_binding": {
            "kind": "hssl_g140_pilot_authorization",
            "path": layout.pilot_report.as_posix(),
            "schema": PILOT_REASSESSMENT_SCHEMA,
            "bytes_sha256": _sha_bytes(pilot_bytes),
            "semantic_sha256": pilot["artifact_sha256"],
            "deep_freeze_sha256": deep_freeze["freeze_sha256"],
            "source_validated": True,
        },
        "prerequisite": {
            "goal_id": "HSSL-G140",
            "required_status": "complete",
            "observed_status": decision["status"],
            "shortlist_frozen": shortlist["frozen"],
            "selected_variant_ids": selected,
            "selected_count": shortlist["selected_count"],
            "holdout_authorized": holdout["authorized"],
            "authorization_sha256": holdout["authorization_sha256"],
            "satisfied": False,
            "failure_kind": "frozen_empty_unauthorized_shortlist",
            "failure_reason": (
                "the source-valid HSSL-G140 decision measured zero proof "
                "efficacy, lacked independent semantic-quality evidence, "
                "froze an empty shortlist, and kept holdout sealed"
            ),
        },
        "authorization_audit": audit,
        "holdout_manifest": {
            "corpus_manifest_sha256": FROZEN_CORPUS_MANIFEST_SHA256,
            "split": "holdout",
            "split_sha256": FROZEN_SPLIT_SHA256[Split.HOLDOUT],
            "case_count": len(holdout_cases),
            "case_ids": [item.case_id for item in holdout_cases],
            "case_sha256s": [item.case_sha256 for item in holdout_cases],
            "source_sha256s": [item.source_sha256 for item in holdout_cases],
            "reviewed_inputs_loaded": False,
            "semantic_targets_inspected": False,
            "outcomes_inspected": False,
        },
        "frozen_execution_contract": contract,
        "candidate_dispositions": candidate_dispositions,
        "access": {
            "status": "unopened",
            "authorized": False,
            "access_audit_count": 0,
            "access_audit_sha256s": [],
            "first_access_recorded": False,
            "cache_namespaces_opened": [],
            "execution_namespace_created": False,
            "execution_write_count": 0,
            "backend_call_count": 0,
            "outcomes_inspected": False,
            "tuning_after_access": False,
        },
        "outcomes": {
            "status": "not_run",
            "scheduled_pair_count": 0,
            "observed_pair_count": 0,
            "terminal_pair_count": 0,
            "explicit_failure_pair_count": 0,
            "case_results": [],
            "kernel_verified_success_count": 0,
            "efficacy_claimed": False,
            "missingness_converted_to_failure_or_zero": False,
        },
        "metrics": _null_metrics(),
        "decision": {
            "status": "blocked",
            "structurally_valid": True,
            "seal_status": "sealed_unopened",
            "holdout_untouched": True,
            "paired_evaluation_complete": False,
            "efficacy_status": "not_evaluated",
            "production_promotion_authorized": False,
            "reason": (
                "HSSL-G140 did not explicitly authorize access; HSSL-G150 "
                "stopped before holdout activity and retained null metrics"
            ),
        },
        "remediation": pilot["remediation"],
        "artifact_sha256": "",
    }
    report["artifact_sha256"] = _sha(
        {key: value for key, value in report.items() if key != "artifact_sha256"}
    )
    return report


def validate_holdout_reassessment_report(
    value: object,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    run_id: str = PUBLISHED_REASSESSMENT_RUN_ID,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> dict[str, object]:
    """Recompute the complete report from HSSL-G140 and reject invention."""

    data = dict(_mapping(value, "holdout reassessment report"))
    if data.get("schema") != HOLDOUT_REASSESSMENT_SCHEMA:
        raise HoldoutReassessmentError(
            "unsupported holdout reassessment schema"
        )
    if data.get("evidence") != "HSSLEV1507C49":
        raise HoldoutReassessmentError(
            "holdout reassessment evidence marker changed"
        )
    if data.get("evidence_statement") != HSSLEV1507C49():
        raise HoldoutReassessmentError(
            "holdout reassessment evidence statement changed"
        )
    if data.get("artifact_sha256") != _sha(
        {key: item for key, item in data.items() if key != "artifact_sha256"}
    ):
        raise HoldoutReassessmentError(
            "holdout reassessment digest changed"
        )
    if data.get("status") != "blocked":
        evidence = _mapping(
            data.get("execution_evidence"),
            "holdout execution evidence",
        )
        try:
            authorization = PilotAuthorizationReceipt.from_dict(
                evidence["authorization"]
            )
            plan = AblationPlan.from_dict(evidence["plan"])
            receipt = HoldoutExecutionReceipt.from_dict(evidence["receipt"])
            raw_results = _array(
                evidence["case_results"],
                "holdout execution case_results",
            )
            results = tuple(
                CaseResultRecord.from_dict(item) for item in raw_results
            )
            if authorization.authorization_sha256 != receipt.authorization_sha256:
                raise HoldoutReassessmentError(
                    "execution authorization and receipt differ"
                )
            execution = AblationRunResult(
                plan=plan,
                contracts=plan.run_contracts,
                results=results,
                executed_job_ids=receipt.executed_job_ids,
                resumed_job_ids=(),
                output_root=Path("."),
            )
            authorized = AuthorizedHoldoutRun(execution, receipt)
        except HoldoutReassessmentError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise HoldoutReassessmentError(
                "authorized holdout evidence failed strict validation"
            ) from exc
        expected = build_holdout_reassessment_report(
            repository_root=repository_root,
            run_id=run_id,
            benchmark_root=benchmark_root,
            authorized_run=authorized,
        )
        if data != expected:
            raise HoldoutReassessmentError(
                "holdout reassessment differs from recomputed execution "
                "evidence"
            )
        return data
    expected = build_holdout_reassessment_report(
        repository_root=repository_root,
        run_id=run_id,
        benchmark_root=benchmark_root,
    )
    if data != expected:
        raise HoldoutReassessmentError(
            "holdout reassessment differs from recomputed source evidence"
        )
    return data


def _snapshot(
    report: Mapping[str, object],
    artifact_path: Path,
    *,
    artifact_reference: Path,
    source_run_id: str,
) -> dict[str, object]:
    decision = _mapping(report["decision"], "decision")
    prerequisite = _mapping(report["prerequisite"], "prerequisite")
    access = _mapping(report["access"], "access")
    outcomes = _mapping(report["outcomes"], "outcomes")
    return {
        "benchmark_script": (
            VALIDATION_COMMAND
            if source_run_id == PUBLISHED_REASSESSMENT_RUN_ID
            else (
                "python benchmarks/logic_pipeline/report.py --gate holdout "
                f"--run-id {source_run_id} --artifact "
                f"{artifact_reference.as_posix()}"
            )
        ),
        "captured_on": "2026-07-24",
        "notes": (
            [
                (
                    "The exact HSSL-G140 decision was source-revalidated "
                    "before the HSSL-G150 access decision."
                ),
                (
                    "HSSL-G140 froze an empty shortlist and did not authorize "
                    "holdout, so no reviewed inputs, writes, or backends opened."
                ),
                (
                    "Unobserved holdout efficacy and cost remain null; this "
                    "sealed receipt is not an efficacy result."
                ),
            ]
            if source_run_id == PUBLISHED_REASSESSMENT_RUN_ID
            else [
                (
                    "The run-scoped HSSL-G140 decision was source-revalidated "
                    "before any HSSL-G150 activity."
                ),
                (
                    "Holdout activity is reported exactly as authorized and "
                    "receipt-bound; missing metric domains remain typed null."
                ),
                (
                    "Benchmark evidence never authorizes production promotion."
                ),
            ]
        ),
        "results": {
            "schema": HOLDOUT_REASSESSMENT_SNAPSHOT_SCHEMA,
            "evidence": "HSSLEV1507C49",
            "run_id": report["run_id"],
            "status": report["status"],
            "artifact": {
                "path": artifact_reference.as_posix(),
                "bytes_sha256": _sha_bytes(artifact_path.read_bytes()),
                "semantic_sha256": report["artifact_sha256"],
            },
            "source": report["source_binding"],
            "prerequisite_satisfied": prerequisite["satisfied"],
            "selected_variant_ids": prerequisite["selected_variant_ids"],
            "holdout_authorized": prerequisite["holdout_authorized"],
            "seal_status": decision["seal_status"],
            "holdout_untouched": decision["holdout_untouched"],
            "activity": {
                "scheduled_pair_count": outcomes["scheduled_pair_count"],
                "observed_pair_count": outcomes["observed_pair_count"],
                "execution_write_count": access["execution_write_count"],
                "backend_call_count": access["backend_call_count"],
            },
            "metrics_complete": _mapping(
                report["metrics"], "metrics"
            )["complete"],
            "production_promotion_authorized": decision[
                "production_promotion_authorized"
            ],
            "remediation": report["remediation"],
        },
    }


def load_holdout_reassessment_report(
    path: str | Path | None = None,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    run_id: str = PUBLISHED_REASSESSMENT_RUN_ID,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    snapshot_path: str | Path | None = None,
    validate_snapshot: bool = True,
) -> dict[str, object]:
    """Load canonical HSSL-G150 evidence and recompute its source graph."""

    root = _resolve_root(repository_root)
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ValueError as exc:
        raise HoldoutReassessmentError("reassessment run_id is invalid") from exc
    artifact_reference = Path(layout.holdout_report if path is None else path)
    artifact_path = _rooted(root, artifact_reference)
    value, _ = _read_canonical(
        artifact_path, "holdout reassessment artifact"
    )
    report = validate_holdout_reassessment_report(
        value,
        repository_root=root,
        run_id=run_id,
        benchmark_root=benchmark_root,
    )
    if validate_snapshot:
        selected_snapshot = Path(
            layout.holdout_snapshot
            if snapshot_path is None
            else snapshot_path
        )
        snapshot, _ = _read_canonical(
            _rooted(root, selected_snapshot),
            "holdout reassessment snapshot",
        )
        if snapshot != _snapshot(
            report,
            artifact_path,
            artifact_reference=(
                layout.holdout_report
                if run_id == PUBLISHED_REASSESSMENT_RUN_ID
                else artifact_reference
            ),
            source_run_id=run_id,
        ):
            raise HoldoutReassessmentError(
                "holdout reassessment snapshot differs from the artifact"
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
            raise HoldoutReassessmentError(
                f"refusing to overwrite immutable evidence: {path}"
            ) from exc
    if path.is_symlink():
        raise HoldoutReassessmentError("refusing to overwrite a symlink")
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
        raise HoldoutReassessmentError(
            f"cannot write evidence: {path}"
        ) from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass


def write_holdout_reassessment_report(
    path: str | Path | None = None,
    *,
    run_id: str,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    snapshot_path: str | Path | None = None,
    repository_root: str | Path = REPOSITORY_ROOT,
    authorized_run: AuthorizedHoldoutRun | None = None,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    """Build and atomically publish the canonical artifact and snapshot."""

    root = _resolve_root(repository_root)
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
        artifact_reference = Path(
            layout.holdout_report if path is None else path
        )
        snapshot_reference = Path(
            layout.holdout_snapshot
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
        raise HoldoutReassessmentError(str(exc)) from exc
    artifact = _rooted(root, artifact_reference)
    public_snapshot = _rooted(root, snapshot_reference)
    report = build_holdout_reassessment_report(
        repository_root=root,
        run_id=run_id,
        benchmark_root=benchmark_root,
        authorized_run=authorized_run,
    )
    _atomic_write(
        artifact,
        (canonical_json(report) + "\n").encode("utf-8"),
        overwrite=overwrite,
    )
    snapshot = _snapshot(
        report,
        artifact,
        artifact_reference=artifact_reference,
        source_run_id=run_id,
    )
    _atomic_write(
        public_snapshot,
        (canonical_json(snapshot) + "\n").encode("utf-8"),
        overwrite=overwrite,
    )
    return artifact, public_snapshot


def holdout_reassessment_summary(report: object) -> dict[str, object]:
    """Return the stable CLI summary for source-revalidated HSSL-G150."""

    value = _mapping(report, "holdout reassessment report")
    decision = _mapping(value["decision"], "decision")
    prerequisite = _mapping(value["prerequisite"], "prerequisite")
    access = _mapping(value["access"], "access")
    outcomes = _mapping(value["outcomes"], "outcomes")
    metrics = _mapping(value["metrics"], "metrics")
    return {
        "section": "holdout",
        "schema": value["schema"],
        "status": decision["status"],
        "structurally_valid": decision["structurally_valid"],
        "artifact_sha256": value["artifact_sha256"],
        "prerequisite_satisfied": prerequisite["satisfied"],
        "selected_variant_ids": prerequisite["selected_variant_ids"],
        "holdout_access_authorized": access["authorized"],
        "holdout_untouched": decision["holdout_untouched"],
        "seal_status": decision["seal_status"],
        "scheduled_pair_count": outcomes["scheduled_pair_count"],
        "observed_pair_count": outcomes["observed_pair_count"],
        "execution_write_count": access["execution_write_count"],
        "backend_call_count": access["backend_call_count"],
        "metrics_complete": metrics["complete"],
        "efficacy_claimed": outcomes["efficacy_claimed"],
        "production_promotion_authorized": decision[
            "production_promotion_authorized"
        ],
    }


__all__ = [
    "CACHE_MODES",
    "DEFAULT_HOLDOUT_REASSESSMENT_PATH",
    "DEFAULT_HOLDOUT_REASSESSMENT_SNAPSHOT",
    "HOLDOUT_REASSESSMENT_RUN_ID",
    "HOLDOUT_REASSESSMENT_SCHEMA",
    "HOLDOUT_REASSESSMENT_SNAPSHOT_SCHEMA",
    "HSSLEV1507C49",
    "HoldoutReassessmentError",
    "METRIC_DOMAINS",
    "build_holdout_authorization",
    "build_holdout_reassessment_report",
    "holdout_reassessment_summary",
    "load_holdout_reassessment_report",
    "validate_holdout_reassessment_report",
    "write_holdout_reassessment_report",
]
