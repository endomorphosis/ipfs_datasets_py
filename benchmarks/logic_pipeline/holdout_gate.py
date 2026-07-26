"""Fail-closed paired holdout evaluation and sealing boundary.

HSSL-G090 is downstream of the pilot/shortlist phase gate.  This module makes
that dependency executable: it will only admit holdout measurements when the
source gate has a completed, frozen, non-empty shortlist and explicitly
authorizes access.  The checked-in pilot evidence is incomplete and has an
empty shortlist, so the canonical HSSL-G090 artifact is a blocked, unopened
seal.  It proves that no baseline-only run, tuning, metric, receipt, or replay
claim was invented after the prerequisite failed.

The seal still binds the complete future evaluation contract: the immutable
holdout manifest, identical A0/candidate pairing, balanced order, cold/warm
separation, frozen resource budgets, kernel-only success authority, and replay
requirements.  A structurally valid seal is not a successful efficacy result.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
from typing import Final, Mapping

from benchmarks.logic_pipeline import BENCHMARK_ID
from benchmarks.logic_pipeline.cases import (
    FROZEN_CORPUS_MANIFEST_SHA256,
    FROZEN_SPLIT_SHA256,
    corpus_manifest_sha256,
    load_manifest,
)
from benchmarks.logic_pipeline.contracts import (
    DEFAULT_PROTOCOL_SHA256,
    Split,
    canonical_json,
)
from benchmarks.logic_pipeline.pilot_gate import (
    DEFAULT_PILOT_GATE_PATH,
    PILOT_GATE_SCHEMA,
    load_pilot_gate_report,
)


HOLDOUT_GATE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.paired-holdout-gate.v1"
)
HOLDOUT_EVALUATION_CONTRACT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.holdout-evaluation-contract.v1"
)
HOLDOUT_METRICS_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.holdout-metric-domains.v1"
)
HOLDOUT_GATE_RUN_ID: Final = "holdout-evaluation-v1"
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_HOLDOUT_GATE_PATH: Final = Path(
    "workspace/benchmarks/hammer-symai-spacy-leanstral/results/"
    "holdout-evaluation-v1.json"
)
PILOT_SOURCE_PATH: Final = DEFAULT_PILOT_GATE_PATH
ALLOWED_SOURCE_PATHS: Final = frozenset({PILOT_SOURCE_PATH.as_posix()})
CACHE_MODES: Final = ("cold", "warm")
METRIC_DOMAINS: Final = ("safety", "quality", "latency", "resource", "routing")
_MAX_REPORT_BYTES: Final = 8 * 1024 * 1024
_REPORT_FIELDS: Final = {
    "schema",
    "evidence",
    "benchmark_id",
    "run_id",
    "source_binding",
    "prerequisite",
    "holdout_manifest",
    "evaluation_contract",
    "candidate_eligibility",
    "access",
    "outcomes",
    "replay",
    "metrics",
    "decision",
    "artifact_sha256",
}


class HoldoutGateError(ValueError):
    """Raised when holdout evidence violates the frozen phase boundary."""


def HSSLEV0909F29() -> str:
    """Return AST-verifiable evidence for the paired holdout phase gate."""

    return (
        "untouched paired holdout seal with prerequisite authorization, "
        "balanced ordering, strict budgets, kernel receipts, and replay"
    )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise HoldoutGateError(f"{field} must be an object with string keys")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise HoldoutGateError(f"{field} must be an array")
    return value


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise HoldoutGateError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> object:
    raise HoldoutGateError(f"non-finite JSON number is forbidden: {token}")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _artifact_digest(value: Mapping[str, object]) -> str:
    return _sha256_json(
        {key: item for key, item in value.items() if key != "artifact_sha256"}
    )


def _resolve_repository_root(repository_root: str | Path) -> Path:
    root = Path(repository_root)
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise HoldoutGateError(f"repository root is unavailable: {root}") from exc
    if not resolved.is_dir():
        raise HoldoutGateError(
            f"repository root is not a directory: {resolved}"
        )
    return resolved


def _resolve_source(repository_root: Path) -> Path:
    raw = PILOT_SOURCE_PATH.as_posix()
    pure = PurePosixPath(raw)
    if (
        raw not in ALLOWED_SOURCE_PATHS
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise HoldoutGateError(f"source path is not allowlisted: {raw!r}")
    candidate = repository_root.joinpath(*pure.parts)
    try:
        resolved = candidate.resolve(strict=True)
        root = repository_root.resolve(strict=True)
        resolved.relative_to(root)
        source_stat = candidate.lstat()
    except (OSError, ValueError) as exc:
        raise HoldoutGateError("pilot source is unavailable or escaped root") from exc
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(
        source_stat.st_mode
    ):
        raise HoldoutGateError(
            "pilot source must be a regular non-symlink file"
        )
    if source_stat.st_size <= 0 or source_stat.st_size > _MAX_REPORT_BYTES:
        raise HoldoutGateError("pilot source size is outside the safe bound")
    return resolved


def _metric_domains() -> dict[str, object]:
    """Return explicit null metrics without converting missing work to zero."""

    values: dict[str, dict[str, object]] = {
        "safety": {
            "invalid_control_kernel_false_positive_count": None,
            "invalid_control_kernel_false_positive_rate": None,
            "a0_solved_regression_rate": None,
            "unexplained_a0_regressions": None,
        },
        "quality": {
            "kernel_verified_completion_rate": None,
            "paired_verified_delta_vs_a0": None,
            "hard_case_verified_gain": None,
            "normalized_ir_exact_match_rate": None,
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
    domains = [
        {
            "domain": domain,
            "measurement_status": "not_observed",
            "complete": False,
            "values": values[domain],
            "reason": (
                "holdout access was not authorized; null is retained instead "
                "of synthesizing a measurement"
            ),
        }
        for domain in METRIC_DOMAINS
    ]
    return {
        "schema": HOLDOUT_METRICS_SCHEMA,
        "required_domains": list(METRIC_DOMAINS),
        "domains": domains,
        "measured_domain_count": 0,
        "complete": False,
        "status": "not_applicable_before_authorization",
        "cold_warm_collapsed": False,
    }


def _derive_report(repository_root: Path) -> dict[str, object]:
    """Derive the unopened seal solely from allowlisted frozen evidence."""

    source_path = _resolve_source(repository_root)
    try:
        pilot = load_pilot_gate_report(
            source_path, repository_root=repository_root
        )
    except ValueError as exc:
        raise HoldoutGateError("pilot prerequisite failed validation") from exc

    shortlist = _mapping(pilot["shortlist"], "pilot shortlist")
    pilot_holdout = _mapping(pilot["holdout"], "pilot holdout")
    pilot_decision = _mapping(pilot["decision"], "pilot decision")
    deep_freeze = _mapping(pilot["deep_freeze"], "pilot deep freeze")
    source_bytes = source_path.read_bytes()

    selected = _array(
        shortlist["selected_variant_ids"],
        "pilot shortlist selected_variant_ids",
    )
    authorized = pilot_holdout["authorized"] is True
    completed = pilot_decision["status"] == "complete"
    if authorized or completed or selected:
        raise HoldoutGateError(
            "canonical blocked seal requires the current incomplete, empty, "
            "unauthorized pilot prerequisite"
        )
    if (
        pilot_holdout["status"] != "unopened"
        or pilot_holdout["outcomes_inspected"] is not False
        or _array(pilot_holdout["access_log_ids"], "access_log_ids")
    ):
        raise HoldoutGateError(
            "blocked holdout seal requires an unopened prerequisite"
        )

    corpus_manifest = load_manifest()
    corpus_manifest_digest = corpus_manifest_sha256(corpus_manifest)
    holdout_cases = tuple(
        item
        for item in corpus_manifest.cases
        if item.split is Split.HOLDOUT
    )
    if (
        corpus_manifest_digest != FROZEN_CORPUS_MANIFEST_SHA256
        or len(holdout_cases) != 10
    ):
        raise HoldoutGateError("frozen holdout manifest identity changed")

    resource_policy = _mapping(
        deep_freeze["resource_policy"], "resource_policy"
    )
    thresholds = _mapping(deep_freeze["thresholds"], "thresholds")
    candidate_eligibility = [
        {
            "variant_id": item["variant_id"],
            "configuration_sha256": item["configuration_sha256"],
            "status": "ineligible_before_holdout",
            "selection_eligible": False,
            "scheduled": False,
            "reasons": item["reasons"],
        }
        for item in _array(
            pilot["variant_dispositions"], "variant_dispositions"
        )
        if isinstance(item, Mapping)
    ]

    report: dict[str, object] = {
        "schema": HOLDOUT_GATE_SCHEMA,
        "evidence": HSSLEV0909F29(),
        "benchmark_id": BENCHMARK_ID,
        "run_id": HOLDOUT_GATE_RUN_ID,
        "source_binding": {
            "kind": "pilot_shortlist_gate",
            "path": PILOT_SOURCE_PATH.as_posix(),
            "schema": PILOT_GATE_SCHEMA,
            "content_sha256": _sha256_bytes(source_bytes),
            "semantic_sha256": pilot["artifact_sha256"],
        },
        "prerequisite": {
            "goal_id": "HSSL-G080",
            "required_status": "complete",
            "observed_status": pilot_decision["status"],
            "shortlist_frozen": shortlist["frozen"],
            "selected_variant_ids": selected,
            "holdout_authorized": authorized,
            "satisfied": False,
            "failure_kind": "incomplete_empty_shortlist",
            "failure_reason": (
                "the frozen pilot gate has no efficacy observations, selected "
                "candidate, or authorization for holdout access"
            ),
        },
        "holdout_manifest": {
            "corpus_manifest_sha256": corpus_manifest_digest,
            "split": "holdout",
            "split_sha256": FROZEN_SPLIT_SHA256[Split.HOLDOUT],
            "case_ids": [item.case_id for item in holdout_cases],
            "case_sha256s": [item.case_sha256 for item in holdout_cases],
            "source_sha256s": [item.source_sha256 for item in holdout_cases],
            "case_count": len(holdout_cases),
            "semantic_targets_inspected_by_gate": False,
            "outcomes_inspected_by_gate": False,
        },
        "evaluation_contract": {
            "schema": HOLDOUT_EVALUATION_CONTRACT_SCHEMA,
            "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
            "baseline_variant_id": "A0",
            "candidate_variant_ids": selected,
            "evaluation_variant_ids": [],
            "cache_modes": list(CACHE_MODES),
            "identical_case_manifest_required": True,
            "identical_manifest_sha256": FROZEN_SPLIT_SHA256[Split.HOLDOUT],
            "pair_key_dimensions": [
                "case_id",
                "cache_mode",
                "corpus_manifest_sha256",
                "holdout_split_sha256",
            ],
            "expected_pair_count": 0,
            "balanced_order": {
                "required": True,
                "method": "case-cache parity crossover",
                "rule": (
                    "for each candidate and cache mode, alternate A0-first and "
                    "candidate-first by frozen case ordinal; invert warm order"
                ),
                "scheduled_coordinates": [],
                "status": "not_scheduled_before_authorization",
            },
            "strict_budgets": {
                "required": True,
                "resource_policy_sha256": resource_policy["sha256"],
                "resource_policy": resource_policy["values"],
                "execution_claimed": False,
            },
            "thresholds_sha256": thresholds["sha256"],
            "kernel_success_authority": "independent_native_kernel",
            "success_receipt_required": True,
            "fresh_worktree_replay_required": True,
            "sampled_failure_replay_required": True,
            "tuning_after_first_access_forbidden": True,
            "shadow_only": True,
            "production_promotion_authorized": False,
        },
        "candidate_eligibility": candidate_eligibility,
        "access": {
            "status": "unopened",
            "authorized": False,
            "access_log_ids": [],
            "audit_receipts": [],
            "first_access_recorded": False,
            "outcomes_inspected": False,
            "tuning_after_access": False,
            "cache_namespaces_opened": [],
        },
        "outcomes": {
            "status": "not_run",
            "scheduled_pair_count": 0,
            "observed_pair_count": 0,
            "capability_ineligible_candidate_count": len(
                candidate_eligibility
            ),
            "case_results": [],
            "baseline_only_execution_forbidden": True,
            "missingness_converted_to_failure_or_zero": False,
            "kernel_verified_success_count": 0,
            "efficacy_claimed": False,
        },
        "replay": {
            "status": "not_applicable_no_execution",
            "success_receipt_count": 0,
            "required_success_replay_count": 0,
            "completed_success_replay_count": 0,
            "sampled_failure_receipt_count": 0,
            "completed_failure_replay_count": 0,
            "all_observed_successes_replayed": True,
            "replay_claimed": False,
            "fresh_worktree_receipts": [],
        },
        "metrics": _metric_domains(),
        "decision": {
            "status": "blocked",
            "structurally_valid": True,
            "efficacy_status": "not_evaluated",
            "seal_status": "sealed_unopened",
            "holdout_untouched": True,
            "paired_evaluation_complete": False,
            "safety_decision": "not_evaluated",
            "production_promotion_authorized": False,
            "reason": (
                "HSSL-G080 did not authorize holdout access; the only valid "
                "HSSL-G090 result is an unopened seal with null metrics"
            ),
            "required_follow_up": [
                "restore every pinned runtime capability without changing the "
                "frozen protocol or selection inputs",
                "replay pilot and development with complete receipts",
                "obtain a complete gate with a non-empty frozen shortlist and "
                "explicit holdout authorization",
                "then execute A0 and each shortlisted arm as balanced pairs "
                "without tuning",
            ],
        },
        "artifact_sha256": "",
    }
    report["artifact_sha256"] = _artifact_digest(report)
    return report


def build_holdout_gate_report(
    *, repository_root: str | Path = REPOSITORY_ROOT
) -> dict[str, object]:
    """Build the deterministic HSSL-G090 seal from frozen source evidence."""

    return _derive_report(_resolve_repository_root(repository_root))


def validate_holdout_gate_report(
    value: object, *, repository_root: str | Path = REPOSITORY_ROOT
) -> dict[str, object]:
    """Recompute the complete seal and reject stale or invented evidence."""

    data = _mapping(value, "holdout gate report")
    actual_fields = set(data)
    if actual_fields != _REPORT_FIELDS:
        raise HoldoutGateError(
            "holdout gate report keys changed; "
            f"missing={sorted(_REPORT_FIELDS - actual_fields)}, "
            f"unknown={sorted(actual_fields - _REPORT_FIELDS)}"
        )
    if data["schema"] != HOLDOUT_GATE_SCHEMA:
        raise HoldoutGateError("unsupported holdout gate schema")
    if data["evidence"] != HSSLEV0909F29():
        raise HoldoutGateError("holdout gate evidence marker changed")
    if data["benchmark_id"] != BENCHMARK_ID:
        raise HoldoutGateError("benchmark identity changed")
    if data["run_id"] != HOLDOUT_GATE_RUN_ID:
        raise HoldoutGateError("holdout gate run identity changed")
    if data["artifact_sha256"] != _artifact_digest(data):
        raise HoldoutGateError("holdout gate artifact digest changed")
    expected = _derive_report(_resolve_repository_root(repository_root))
    if dict(data) != expected:
        raise HoldoutGateError(
            "holdout gate differs from recomputed allowlisted source evidence"
        )
    return dict(data)


def _result_path(path: str | Path, repository_root: Path) -> Path:
    result = Path(path)
    return result if result.is_absolute() else repository_root / result


def load_holdout_gate_report(
    path: str | Path = DEFAULT_HOLDOUT_GATE_PATH,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
) -> dict[str, object]:
    """Load canonical newline JSON and revalidate every source binding."""

    root = _resolve_repository_root(repository_root)
    report_path = _result_path(path, root)
    try:
        file_stat = report_path.lstat()
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(
            file_stat.st_mode
        ):
            raise HoldoutGateError(
                "holdout gate path must be a regular non-symlink file"
            )
        if file_stat.st_size <= 0 or file_stat.st_size > _MAX_REPORT_BYTES:
            raise HoldoutGateError(
                "holdout gate file size is outside the safe bound"
            )
        raw = report_path.read_bytes()
        text = raw.decode("utf-8")
    except HoldoutGateError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise HoldoutGateError(
            f"cannot read holdout gate: {report_path}"
        ) from exc
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise HoldoutGateError(
            "holdout gate is not canonical newline JSON"
        )
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, HoldoutGateError) as exc:
        raise HoldoutGateError("holdout gate is not strict JSON") from exc
    try:
        expected_bytes = (canonical_json(value) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HoldoutGateError(
            "holdout gate is not canonically serializable"
        ) from exc
    if raw != expected_bytes:
        raise HoldoutGateError("holdout gate is not canonical JSON")
    return validate_holdout_gate_report(value, repository_root=root)


def write_holdout_gate_report(
    report: object | None = None,
    path: str | Path = DEFAULT_HOLDOUT_GATE_PATH,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    overwrite: bool = False,
) -> Path:
    """Write a canonical holdout seal atomically."""

    root = _resolve_repository_root(repository_root)
    value = (
        build_holdout_gate_report(repository_root=root)
        if report is None
        else validate_holdout_gate_report(report, repository_root=root)
    )
    destination = _result_path(path, root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = (canonical_json(value) + "\n").encode("utf-8")
    if not overwrite:
        try:
            descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644,
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise HoldoutGateError(
                f"refusing to overwrite existing holdout gate: {destination}"
            ) from exc
        except OSError as exc:
            raise HoldoutGateError(
                f"cannot write holdout gate: {destination}"
            ) from exc
        return destination

    if destination.is_symlink():
        raise HoldoutGateError("refusing to overwrite a symlink")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    except OSError as exc:
        raise HoldoutGateError(
            f"cannot write holdout gate: {destination}"
        ) from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass
    return destination


def holdout_gate_summary(
    report: object, *, repository_root: str | Path = REPOSITORY_ROOT
) -> dict[str, object]:
    """Return the stable CLI receipt for a revalidated holdout seal."""

    value = validate_holdout_gate_report(
        report, repository_root=repository_root
    )
    decision = _mapping(value["decision"], "decision")
    prerequisite = _mapping(value["prerequisite"], "prerequisite")
    access = _mapping(value["access"], "access")
    outcomes = _mapping(value["outcomes"], "outcomes")
    metrics = _mapping(value["metrics"], "metrics")
    return {
        "section": "holdout",
        "status": decision["status"],
        "structurally_valid": decision["structurally_valid"],
        "artifact_sha256": value["artifact_sha256"],
        "prerequisite_satisfied": prerequisite["satisfied"],
        "holdout_untouched": decision["holdout_untouched"],
        "holdout_access_authorized": access["authorized"],
        "access_log_ids": access["access_log_ids"],
        "selected_variant_ids": prerequisite["selected_variant_ids"],
        "scheduled_pair_count": outcomes["scheduled_pair_count"],
        "observed_pair_count": outcomes["observed_pair_count"],
        "metrics_complete": metrics["complete"],
        "efficacy_claimed": outcomes["efficacy_claimed"],
        "production_promotion_authorized": decision[
            "production_promotion_authorized"
        ],
    }


__all__ = [
    "ALLOWED_SOURCE_PATHS",
    "CACHE_MODES",
    "DEFAULT_HOLDOUT_GATE_PATH",
    "HOLDOUT_EVALUATION_CONTRACT_SCHEMA",
    "HOLDOUT_GATE_RUN_ID",
    "HOLDOUT_GATE_SCHEMA",
    "HOLDOUT_METRICS_SCHEMA",
    "HSSLEV0909F29",
    "HoldoutGateError",
    "METRIC_DOMAINS",
    "PILOT_SOURCE_PATH",
    "build_holdout_gate_report",
    "holdout_gate_summary",
    "load_holdout_gate_report",
    "validate_holdout_gate_report",
    "write_holdout_gate_report",
]
