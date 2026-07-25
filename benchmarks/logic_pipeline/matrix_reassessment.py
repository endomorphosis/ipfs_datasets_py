"""Source-bound pilot/development execution for the HSSL reassessment.

The aggregate in this module is deliberately narrower than the generic
ablation runner: it accepts one frozen, run-bound capability freeze, parses
only the unsealed pilot and development corpus records, and publishes one
strict receipt over the complete 560-coordinate matrix.  The published
``reassessment-v2`` evidence remains validation-only.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Final, Mapping, Sequence

from . import DEFAULT_BENCHMARK_ROOT
from .ablation import (
    ABLATION_RESULT_SCHEMA,
    AblationPlan,
    AblationRunResult,
    AblationValidationError,
    ResourceLimits,
    build_ablation_plan,
    execute_ablation,
    validate_ablation_evidence,
)
from .capabilities import (
    CapabilityContractError,
    ResourceLeaseReceipt,
)
from .capability_reprobe import (
    LiveCapabilityReprobe,
    REASSESSMENT_RUN_ID,
    validate_frozen_capability_reprobe,
)
from .reassessment_namespace import (
    PUBLISHED_REASSESSMENT_RUN_ID,
    ReassessmentNamespaceError,
    ReassessmentRunLayout,
    reject_published_write_targets,
    require_fresh_reassessment_run,
)
from .cases import (
    DEFAULT_CORPUS_PATH,
    DEFAULT_MANIFEST_PATH,
    FROZEN_CORPUS_MANIFEST_SHA256,
    FROZEN_SPLIT_SHA256,
    BenchmarkCase,
    CorpusContractError,
    ExpectedClass,
    Split,
    corpus_manifest_sha256,
    load_unsealed_pilot_development,
)
from .contracts import (
    DEFAULT_PROTOCOL_SHA256,
    CacheMode,
    CaseResultRecord,
    OutcomeStatus,
    StageName,
    canonical_json,
)
from .runtime import (
    LEANSTRAL_MEASURED_MAX_NEW_TOKENS,
    RuntimeBackendHandlers,
    build_live_runtime,
)
from .variants import (
    ALL_VARIANT_IDS,
    VARIANT_REGISTRY_SHA256,
    get_variant_definition,
)


MATRIX_INDEX_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.reassessment-matrix.v1"
)
MATRIX_SNAPSHOT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.reassessment-matrix-snapshot.v1"
)
RESOURCE_LEDGER_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.matrix-resource-ledger.v1"
)
MATRIX_SEED: Final = 2737
EXPECTED_CASES_PER_SPLIT: Final = 10
EXPECTED_COORDINATE_COUNT: Final = 560
DEFAULT_MATRIX_ROOT: Final = Path(
    ReassessmentRunLayout.for_run(REASSESSMENT_RUN_ID).matrix_root
)
DEFAULT_MATRIX_INDEX: Final = Path(
    ReassessmentRunLayout.for_run(REASSESSMENT_RUN_ID).matrix_index
)
DEFAULT_MATRIX_SNAPSHOT: Final = Path(
    ReassessmentRunLayout.for_run(REASSESSMENT_RUN_ID).matrix_snapshot
)
FROZEN_SELECTION_PATH: Final = Path(
    "workspace/benchmarks/hammer-symai-spacy-leanstral/results/"
    "pilot-shortlist-v1.json"
)
FROZEN_SELECTION_BYTES_SHA256: Final = (
    "0e702d4e19dbc242b445f4f6ef91647506ee4c0174072318098a6f6be2173e45"
)
FROZEN_SELECTION_SHA256S: Final = MappingProxyType(
    {
        "freeze": (
            "1349e8ed8cdc20bcfc6de4b6eba83f41a9188702a95c28a7ec3566127d24b007"
        ),
        "prompts": (
            "7f3140b13261feb8d6eb22a3df60c3b7656649306d1a683b91979922655c369b"
        ),
        "policies": (
            "528ed32632e523e0c0c79abb0459bdba8f6c68bafda5609db04ec35dc5b771e0"
        ),
        "resource_policy": (
            "66bd17812fee1b8d5a59b31ded57552c44c161fbda8fa8b82d4ab1f1f712bdfb"
        ),
        "thresholds": (
            "17f2bc866988a7fd5101a6ce6b905beff5f010c17195289078cd81077df0d424"
        ),
    }
)
REQUIRED_COMMAND: Final = (
    "python -m benchmarks.logic_pipeline.runtime execute "
    "--splits pilot,development --cache-mode both --validate-complete"
)
_MATRIX_SPLITS: Final = (Split.PILOT, Split.DEVELOPMENT)
_MATRIX_CACHE_MODES: Final = (CacheMode.COLD, CacheMode.WARM)


class MatrixReassessmentError(ValueError):
    """Raised when execution or persisted matrix evidence is incomplete."""


def HSSLEV1305A27() -> str:
    """Return the AST-verifiable unchanged-matrix evidence receipt."""

    return (
        "complete unchanged pilot and development matrix with counterbalanced "
        "cold and warm execution, durable stage leases, and sealed holdout"
    )


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise MatrixReassessmentError(f"{field} must be an object")
    return value


def _exact(
    value: Mapping[str, object], expected: set[str], field: str
) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing or unknown:
        raise MatrixReassessmentError(
            f"{field} fields changed: missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )


def _read_canonical(path: Path, field: str) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise MatrixReassessmentError(f"cannot read {field}: {path}") from exc
    if not text.endswith("\n"):
        raise MatrixReassessmentError(f"{field} is not canonical newline JSON")
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except (json.JSONDecodeError, ValueError) as exc:
        raise MatrixReassessmentError(f"{field} is not strict JSON") from exc
    if canonical_json(value) + "\n" != text:
        raise MatrixReassessmentError(f"{field} is not canonical JSON")
    return value


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _write_once(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    raw = (canonical_json(value) + "\n").encode("utf-8")
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise MatrixReassessmentError(
            f"refusing to overwrite immutable matrix evidence: {path}"
        ) from exc


def _index_path(output_root: Path) -> Path:
    return output_root.parent / DEFAULT_MATRIX_INDEX.name


def _relative_to_index(path: Path, index_path: Path) -> str:
    try:
        return path.resolve().relative_to(index_path.parent.resolve()).as_posix()
    except ValueError as exc:
        raise MatrixReassessmentError(
            f"matrix artifact is outside its result namespace: {path}"
        ) from exc


def _sealed_non_holdout_cases(
    *,
    corpus_path: str | Path = DEFAULT_CORPUS_PATH,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> tuple[object, tuple[BenchmarkCase, ...]]:
    """Load the shared pre-authorization pilot/development corpus boundary."""

    try:
        manifest, cases = load_unsealed_pilot_development(
            corpus_path=corpus_path,
            manifest_path=manifest_path,
        )
    except CorpusContractError as exc:
        raise MatrixReassessmentError(
            "frozen unsealed corpus prefix is invalid"
        ) from exc
    if (
        manifest.split_counts.get(Split.PILOT.value)
        != EXPECTED_CASES_PER_SPLIT
        or manifest.split_counts.get(Split.DEVELOPMENT.value)
        != EXPECTED_CASES_PER_SPLIT
        or len(cases) != 2 * EXPECTED_CASES_PER_SPLIT
    ):
        raise MatrixReassessmentError("frozen reviewed split cardinality drifted")
    return manifest, cases


def _normalize_splits(splits: Sequence[Split]) -> tuple[Split, ...]:
    value = tuple(splits)
    if value != _MATRIX_SPLITS:
        raise MatrixReassessmentError(
            "reassessment execution requires exactly pilot,development"
        )
    return value


def _normalize_modes(modes: Sequence[CacheMode]) -> tuple[CacheMode, ...]:
    value = tuple(modes)
    if value != _MATRIX_CACHE_MODES:
        raise MatrixReassessmentError(
            "reassessment execution requires exactly cold,warm"
        )
    return value


def _validate_counterbalance(plan: AblationPlan) -> None:
    if tuple(plan.variant_ids) != tuple(ALL_VARIANT_IDS):
        raise MatrixReassessmentError("matrix arm registry is incomplete")
    position_counts = {
        mode: {
            variant: [0] * len(ALL_VARIANT_IDS)
            for variant in ALL_VARIANT_IDS
        }
        for mode in _MATRIX_CACHE_MODES
    }
    for block in plan.blocks:
        first = block[0]
        for position, job in enumerate(block):
            position_counts[first.cache_mode][job.variant_id][position] += 1
    for mode, by_variant in position_counts.items():
        if any(max(counts) - min(counts) > 1 for counts in by_variant.values()):
            raise MatrixReassessmentError(
                f"{plan.split.value}/{mode.value} arm order is not counterbalanced"
            )


def build_reassessment_plans(
    frozen_reprobe: LiveCapabilityReprobe,
    *,
    run_id: str | None = None,
    splits: Sequence[Split] = _MATRIX_SPLITS,
    cache_modes: Sequence[CacheMode] = _MATRIX_CACHE_MODES,
    seed: int = MATRIX_SEED,
    limits: ResourceLimits = ResourceLimits(),
) -> tuple[AblationPlan, ...]:
    """Build the exact unchanged pilot/development schedule."""

    if not isinstance(frozen_reprobe, LiveCapabilityReprobe):
        raise MatrixReassessmentError("frozen_reprobe is invalid")
    selected_run_id = (
        frozen_reprobe.inventory.run_id if run_id is None else run_id
    )
    try:
        ReassessmentRunLayout.for_run(selected_run_id)
    except ValueError as exc:
        raise MatrixReassessmentError("matrix run_id is invalid") from exc
    if frozen_reprobe.inventory.run_id != selected_run_id:
        raise MatrixReassessmentError("capability run identity drifted")
    selected_splits = _normalize_splits(splits)
    selected_modes = _normalize_modes(cache_modes)
    manifest, cases = _sealed_non_holdout_cases()
    plans = tuple(
        build_ablation_plan(
            selected_run_id,
            tuple(case for case in cases if case.split is split),
            case_manifest_sha256=corpus_manifest_sha256(manifest),
            split=split,
            seed=seed,
            variant_ids=ALL_VARIANT_IDS,
            cache_modes=selected_modes,
            limits=limits,
            environment_sha256=frozen_reprobe.inventory.sha256,
        )
        for split in selected_splits
    )
    if sum(len(plan.jobs) for plan in plans) != EXPECTED_COORDINATE_COUNT:
        raise MatrixReassessmentError("matrix plan is not exactly 560 coordinates")
    for plan in plans:
        _validate_counterbalance(plan)
    return plans


def _ledger_path(split_root: Path) -> Path:
    return split_root / "state" / "resource-leases.json"


def _invoked_stage_owners(
    run: AblationRunResult,
) -> tuple[tuple[str, str, str], ...]:
    owners: list[tuple[str, str, str]] = []
    for job, result in zip(run.plan.jobs, run.results, strict=True):
        for stage in result.stages:
            identity = stage.provenance.effective_identity
            if identity.get("graph_invoked") is True:
                owners.append(
                    (
                        f"lease-{job.ordinal}-{stage.stage.value}",
                        job.job_id,
                        stage.stage.value,
                    )
                )
    return tuple(owners)


def _receipt_binding(
    run: AblationRunResult,
    receipt: ResourceLeaseReceipt,
) -> dict[str, object]:
    prefix, separator, suffix = receipt.owner_id.partition("-")
    ordinal_text, stage_separator, stage_text = suffix.partition("-")
    if (
        prefix != "lease"
        or not separator
        or not stage_separator
        or not ordinal_text.isdigit()
    ):
        raise MatrixReassessmentError(
            "resource lease owner is not schedule-bound"
        )
    ordinal = int(ordinal_text)
    if ordinal >= len(run.plan.jobs) or str(ordinal) != ordinal_text:
        raise MatrixReassessmentError(
            "resource lease owner has an invalid job ordinal"
        )
    try:
        stage = StageName(stage_text)
    except ValueError as exc:
        raise MatrixReassessmentError(
            "resource lease owner has an invalid stage"
        ) from exc
    job = run.plan.jobs[ordinal]
    if stage not in get_variant_definition(job.variant_id).stages:
        raise MatrixReassessmentError(
            "resource lease stage is outside the scheduled route"
        )
    return {
        "owner_id": receipt.owner_id,
        "job_id": job.job_id,
        "stage": stage.value,
        "receipt_sha256": _sha(receipt.to_dict()),
    }


def _build_ledger(
    run: AblationRunResult,
) -> dict[str, object]:
    receipts = tuple(run.resource_receipts)
    by_owner = {receipt.owner_id: receipt for receipt in receipts}
    if len(by_owner) != len(receipts):
        raise MatrixReassessmentError("resource lease owner ids are duplicated")
    graph_invoked = _invoked_stage_owners(run)
    if not {owner for owner, _, _ in graph_invoked}.issubset(by_owner):
        raise MatrixReassessmentError(
            "resource lease receipts do not cover every invoked stage"
        )
    bindings = [_receipt_binding(run, receipt) for receipt in receipts]
    without_digest = {
        "schema": RESOURCE_LEDGER_SCHEMA,
        "run_id": run.plan.run_id,
        "split": run.plan.split.value,
        "plan_sha256": run.plan.digest,
        "invoked_stage_count": len(receipts),
        "completed_graph_stage_count": len(graph_invoked),
        "receipt_count": len(receipts),
        "bindings": bindings,
        "receipts": [receipt.to_dict() for receipt in receipts],
    }
    return {**without_digest, "ledger_sha256": _sha(without_digest)}


def _validate_ledger(
    value: object,
    run: AblationRunResult,
) -> Mapping[str, object]:
    data = _mapping(value, "resource ledger")
    _exact(
        data,
        {
            "schema",
            "run_id",
            "split",
            "plan_sha256",
            "invoked_stage_count",
            "completed_graph_stage_count",
            "receipt_count",
            "bindings",
            "receipts",
            "ledger_sha256",
        },
        "resource ledger",
    )
    if (
        data["schema"] != RESOURCE_LEDGER_SCHEMA
        or data["run_id"] != run.plan.run_id
        or data["split"] != run.plan.split.value
        or data["plan_sha256"] != run.plan.digest
    ):
        raise MatrixReassessmentError("resource ledger identity drifted")
    raw_receipts = data["receipts"]
    raw_bindings = data["bindings"]
    if not isinstance(raw_receipts, list) or not isinstance(raw_bindings, list):
        raise MatrixReassessmentError("resource ledger arrays are invalid")
    try:
        receipts = tuple(
            ResourceLeaseReceipt.from_dict(item) for item in raw_receipts
        )
    except (CapabilityContractError, TypeError, ValueError) as exc:
        raise MatrixReassessmentError("resource receipt is invalid") from exc
    by_owner = {receipt.owner_id: receipt for receipt in receipts}
    graph_invoked = _invoked_stage_owners(run)
    expected_bindings = [
        _receipt_binding(run, receipt) for receipt in receipts
    ]
    if (
        len(by_owner) != len(receipts)
        or not {
            owner for owner, _, _ in graph_invoked
        }.issubset(by_owner)
        or raw_bindings != expected_bindings
        or data["receipt_count"] != len(receipts)
        or data["invoked_stage_count"] != len(receipts)
        or data["completed_graph_stage_count"] != len(graph_invoked)
    ):
        raise MatrixReassessmentError("resource ledger coverage drifted")
    without_digest = {key: data[key] for key in data if key != "ledger_sha256"}
    if data["ledger_sha256"] != _sha(without_digest):
        raise MatrixReassessmentError("resource ledger digest changed")
    return MappingProxyType(dict(data))


def _result_path(split_root: Path, plan: AblationPlan, ordinal: int) -> Path:
    job = plan.jobs[ordinal]
    return (
        split_root
        / "results"
        / plan.split.value
        / job.cache_mode.value
        / job.variant_id
        / f"{job.case.case_id}.json"
    )


def _kernel_receipt_valid(record: CaseResultRecord) -> tuple[int, int]:
    invoked = 0
    accepted = 0
    for stage in record.stages:
        if stage.stage is not StageName.KERNEL:
            continue
        if stage.provenance.effective_identity.get("graph_invoked") is not True:
            continue
        invoked += 1
        data = _mapping(stage.data, "native kernel receipt")
        if (
            data.get("schema")
            != "ipfs-datasets.logic-pipeline-benchmark.native-kernel-receipt.v1"
            or data.get("independent") is not True
            or type(data.get("accepted")) is not bool
        ):
            raise MatrixReassessmentError(
                "invoked kernel lacks an independent terminal receipt"
            )
        if stage.kernel_accepted:
            if (
                data.get("accepted") is not True
                or not stage.kernel_receipt_sha256
                or data.get("receipt_sha256") != stage.kernel_receipt_sha256
            ):
                raise MatrixReassessmentError("kernel authority receipt drifted")
            accepted += 1
    return invoked, accepted


def _split_summary(
    *,
    run: AblationRunResult,
    split_root: Path,
    index_path: Path,
    ledger_path: Path,
    ledger: Mapping[str, object],
) -> dict[str, object]:
    statuses: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    kernel_invoked = 0
    kernel_accepted = 0
    invalid_control_coordinates = 0
    invalid_verified = 0
    refs: list[dict[str, object]] = []
    for ordinal, (job, result) in enumerate(
        zip(run.plan.jobs, run.results, strict=True)
    ):
        if result.status not in set(OutcomeStatus):
            raise MatrixReassessmentError("case result is not terminal")
        statuses[result.status.value] += 1
        for stage in result.stages:
            if stage.failure_code is not None:
                failures[stage.failure_code.value] += 1
            if not stage.provenance.requested_identity:
                raise MatrixReassessmentError("stage requested identity is empty")
            if not stage.provenance.effective_identity:
                raise MatrixReassessmentError("stage effective identity is empty")
        invoked, accepted = _kernel_receipt_valid(result)
        kernel_invoked += invoked
        kernel_accepted += accepted
        expected_class = job.case.input_data.get("expected_class")
        if expected_class == ExpectedClass.UNSUPPORTED.value:
            invalid_control_coordinates += 1
        if (
            expected_class == ExpectedClass.UNSUPPORTED.value
            and result.status is OutcomeStatus.VERIFIED
        ):
            invalid_verified += 1
        if job.variant_id == "S1" and result.status is OutcomeStatus.VERIFIED:
            raise MatrixReassessmentError("S1 diagnostic claimed verification")
        path = _result_path(split_root, run.plan, ordinal)
        raw = path.read_bytes()
        refs.append(
            {
                "ordinal": ordinal,
                "case_id": job.case.case_id,
                "variant_id": job.variant_id,
                "cache_mode": job.cache_mode.value,
                "expected_class": expected_class,
                "path": _relative_to_index(path, index_path),
                "bytes_sha256": _sha_bytes(raw),
                "case_result_sha256": result.digest,
                "status": result.status.value,
                "stage_count": len(result.stages),
                "invoked_stage_count": sum(
                    stage.provenance.effective_identity.get("graph_invoked") is True
                    for stage in result.stages
                ),
            }
        )
    if invalid_verified:
        raise MatrixReassessmentError(
            "invalid controls have kernel-verified false positives"
        )
    plan_path = split_root / "state" / "ablation-plan.json"
    return {
        "split": run.plan.split.value,
        "split_sha256": FROZEN_SPLIT_SHA256[run.plan.split],
        "root": _relative_to_index(split_root, index_path),
        "seed": run.plan.seed,
        "case_count": len(run.plan.case_ids),
        "coordinate_count": len(run.results),
        "plan": {
            "path": _relative_to_index(plan_path, index_path),
            "bytes_sha256": _sha_bytes(plan_path.read_bytes()),
            "semantic_sha256": run.plan.digest,
        },
        "resource_ledger": {
            "path": _relative_to_index(ledger_path, index_path),
            "bytes_sha256": _sha_bytes(ledger_path.read_bytes()),
            "semantic_sha256": ledger["ledger_sha256"],
        },
        "invoked_stage_count": ledger["invoked_stage_count"],
        "resource_lease_count": ledger["receipt_count"],
        "status_counts": dict(sorted(statuses.items())),
        "failure_counts": dict(sorted(failures.items())),
        "kernel_invoked_count": kernel_invoked,
        "kernel_accepted_count": kernel_accepted,
        "invalid_control_coordinate_count": invalid_control_coordinates,
        "invalid_control_verified_count": invalid_verified,
        "results": refs,
    }


def _selection_inputs(
    repository: Path, frozen: LiveCapabilityReprobe
) -> dict[str, object]:
    source_path = repository / FROZEN_SELECTION_PATH
    raw = source_path.read_bytes()
    if _sha_bytes(raw) != FROZEN_SELECTION_BYTES_SHA256:
        raise MatrixReassessmentError(
            "frozen pilot/development selection input bytes changed"
        )
    source = _mapping(
        _read_canonical(source_path, "frozen selection input"),
        "frozen selection input",
    )
    deep_freeze = _mapping(source.get("deep_freeze"), "selection deep freeze")
    observed = {
        "freeze": deep_freeze.get("freeze_sha256"),
        "prompts": _mapping(
            deep_freeze.get("prompts"), "frozen prompts"
        ).get("sha256"),
        "policies": _mapping(
            deep_freeze.get("policies"), "frozen policies"
        ).get("sha256"),
        "resource_policy": _mapping(
            deep_freeze.get("resource_policy"), "frozen resource policy"
        ).get("sha256"),
        "thresholds": _mapping(
            deep_freeze.get("thresholds"), "frozen thresholds"
        ).get("sha256"),
    }
    if (
        observed != dict(FROZEN_SELECTION_SHA256S)
        or deep_freeze.get("frozen") is not True
        or deep_freeze.get("tuning_permitted") is not False
    ):
        raise MatrixReassessmentError(
            "frozen pilot/development selection contract changed"
        )
    return {
        "splits": [split.value for split in _MATRIX_SPLITS],
        "cache_modes": [mode.value for mode in _MATRIX_CACHE_MODES],
        "variant_ids": list(ALL_VARIANT_IDS),
        "source": {
            "path": FROZEN_SELECTION_PATH.as_posix(),
            "bytes_sha256": FROZEN_SELECTION_BYTES_SHA256,
            "semantic_sha256": FROZEN_SELECTION_SHA256S["freeze"],
        },
        "prompts_sha256": FROZEN_SELECTION_SHA256S["prompts"],
        "policies_sha256": FROZEN_SELECTION_SHA256S["policies"],
        "resource_policy_sha256": FROZEN_SELECTION_SHA256S[
            "resource_policy"
        ],
        "thresholds_sha256": FROZEN_SELECTION_SHA256S["thresholds"],
        "repaired_model_identities_sha256": frozen.inventory.sha256,
        "prompts_frozen": True,
        "policies_frozen": True,
        "model_identities_frozen": True,
        "thresholds_frozen": True,
        "selection_inputs_changed": False,
        "tuning_permitted": False,
    }


def _build_index(
    frozen: LiveCapabilityReprobe,
    summaries: Sequence[Mapping[str, object]],
    repository: Path,
) -> dict[str, object]:
    totals = {
        "case_count": sum(int(item["case_count"]) for item in summaries),
        "coordinate_count": sum(
            int(item["coordinate_count"]) for item in summaries
        ),
        "kernel_invoked_count": sum(
            int(item["kernel_invoked_count"]) for item in summaries
        ),
        "kernel_accepted_count": sum(
            int(item["kernel_accepted_count"]) for item in summaries
        ),
        "invoked_stage_count": sum(
            int(item["invoked_stage_count"]) for item in summaries
        ),
        "resource_lease_count": sum(
            int(item["resource_lease_count"]) for item in summaries
        ),
        "invalid_control_verified_count": sum(
            int(item["invalid_control_verified_count"]) for item in summaries
        ),
        "invalid_control_coordinate_count": sum(
            int(item["invalid_control_coordinate_count"]) for item in summaries
        ),
    }
    without_digest = {
        "schema": MATRIX_INDEX_SCHEMA,
        "evidence": "HSSLEV1305A27",
        "run_id": frozen.inventory.run_id,
        "status": "complete",
        "frozen": True,
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "variant_registry_sha256": VARIANT_REGISTRY_SHA256,
        "corpus_manifest_sha256": FROZEN_CORPUS_MANIFEST_SHA256,
        "environment_sha256": frozen.inventory.sha256,
        "capability_freeze_sha256": _sha(
            {
                "inventory_sha256": frozen.inventory.sha256,
                "source_binding": dict(frozen.source_binding),
                "receipts": {
                    name: receipt["receipt_sha256"]
                    for name, receipt in sorted(frozen.receipts.items())
                },
            }
        ),
        "source_binding": dict(frozen.source_binding),
        "selection_inputs": _selection_inputs(repository, frozen),
        "split_runs": [dict(item) for item in summaries],
        "totals": totals,
        "safety": {
            "holdout_accessed": False,
            "holdout_case_count": 0,
            "holdout_coordinate_count": 0,
            "fallback_used": False,
            "capability_missingness_synthesized_as_efficacy": False,
            "production_routing_changed": False,
            "invalid_control_verified_count": totals[
                "invalid_control_verified_count"
            ],
            "invalid_control_coordinate_count": totals[
                "invalid_control_coordinate_count"
            ],
        },
    }
    if (
        totals["case_count"] != 20
        or totals["coordinate_count"] != 560
        or totals["invalid_control_coordinate_count"] != 56
        or totals["invalid_control_verified_count"] != 0
    ):
        raise MatrixReassessmentError("aggregate matrix total is incomplete")
    return {**without_digest, "artifact_sha256": _sha(without_digest)}


def _rooted(repository: Path, path: Path) -> Path:
    return path if path.is_absolute() else repository / path


def _assert_no_symlink_chain(root: Path, target: Path, field: str) -> None:
    logical_root = root.absolute()
    logical_target = target.absolute()
    try:
        relative = logical_target.relative_to(logical_root)
    except ValueError as exc:
        raise MatrixReassessmentError(f"{field} escaped its reference root") from exc
    current = logical_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise MatrixReassessmentError(f"{field} must not use a symlink")


def _snapshot_artifact_reference(
    index_path: Path,
    *,
    repository: Path,
    run_id: str,
    benchmark_root: str | Path,
) -> str:
    layout = ReassessmentRunLayout.for_run(
        run_id,
        benchmark_root=benchmark_root,
    )
    root = (
        repository
        if run_id == PUBLISHED_REASSESSMENT_RUN_ID
        else _rooted(repository, layout.run_paths.run_root)
    )
    target = _rooted(repository, index_path)
    _assert_no_symlink_chain(root, target, "matrix snapshot artifact")
    try:
        relative = target.resolve(strict=True).relative_to(
            root.resolve(strict=True)
        )
    except (OSError, ValueError) as exc:
        raise MatrixReassessmentError(
            "matrix snapshot artifact is outside its canonical reference root"
        ) from exc
    reference = relative.as_posix()
    if (
        not reference
        or reference == "."
        or Path(reference).is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise MatrixReassessmentError(
            "matrix snapshot artifact path is not canonical"
        )
    return reference


def _snapshot_capture_date(run_id: str, value: object | None = None) -> str:
    if run_id == PUBLISHED_REASSESSMENT_RUN_ID:
        if value not in {None, "2026-07-24"}:
            raise MatrixReassessmentError(
                "published matrix snapshot capture date changed"
            )
        return "2026-07-24"
    captured_on = (
        datetime.now(timezone.utc).date().isoformat()
        if value is None
        else value
    )
    if not isinstance(captured_on, str):
        raise MatrixReassessmentError(
            "fresh matrix snapshot capture date is invalid"
        )
    try:
        captured = date.fromisoformat(captured_on)
    except ValueError as exc:
        raise MatrixReassessmentError(
            "fresh matrix snapshot capture date is invalid"
        ) from exc
    if (
        captured_on != captured.isoformat()
        or captured > datetime.now(timezone.utc).date()
    ):
        raise MatrixReassessmentError(
            "fresh matrix snapshot capture date is invalid"
        )
    return captured_on


def _snapshot(
    index: Mapping[str, object],
    index_path: Path,
    *,
    repository: Path,
    benchmark_root: str | Path,
    captured_on: object | None = None,
) -> dict[str, object]:
    source = _mapping(index["source_binding"], "source binding")
    run_id = str(index["run_id"])
    return {
        "benchmark_script": REQUIRED_COMMAND,
        "captured_on": _snapshot_capture_date(run_id, captured_on),
        "notes": [
            "This snapshot contains the unchanged A0-A12 and S1 pilot/development matrix.",
            "Cold and warm routes are isolated and counterbalanced; failures remain typed evidence.",
            "No holdout semantic record was read and no production route was changed.",
        ],
        "results": {
            "schema": MATRIX_SNAPSHOT_SCHEMA,
            "evidence": "HSSLEV1305A27",
            "run_id": index["run_id"],
            "status": "complete",
            "frozen": True,
            "artifact": {
                "path": _snapshot_artifact_reference(
                    index_path,
                    repository=repository,
                    run_id=run_id,
                    benchmark_root=benchmark_root,
                ),
                "bytes_sha256": _sha_bytes(
                    _rooted(repository, index_path).read_bytes()
                ),
                "semantic_sha256": index["artifact_sha256"],
            },
            "scope": {
                "splits": ["pilot", "development"],
                "variant_ids": list(ALL_VARIANT_IDS),
                "cache_modes": ["cold", "warm"],
            },
            "completeness": dict(
                _mapping(index["totals"], "matrix totals")
            ),
            "safety": dict(_mapping(index["safety"], "matrix safety")),
            "source_binding": dict(source),
        },
    }


def _validate_index_payload(
    value: object,
    *,
    frozen: LiveCapabilityReprobe,
    repository: Path,
    index_path: Path,
    output_root: Path,
    expected_run_id: str,
) -> Mapping[str, object]:
    data = _mapping(value, "matrix index")
    _exact(
        data,
        {
            "schema",
            "evidence",
            "run_id",
            "status",
            "frozen",
            "protocol_sha256",
            "variant_registry_sha256",
            "corpus_manifest_sha256",
            "environment_sha256",
            "capability_freeze_sha256",
            "source_binding",
            "selection_inputs",
            "split_runs",
            "totals",
            "safety",
            "artifact_sha256",
        },
        "matrix index",
    )
    if (
        data["schema"] != MATRIX_INDEX_SCHEMA
        or data["evidence"] != "HSSLEV1305A27"
        or data["run_id"] != expected_run_id
        or data["status"] != "complete"
        or data["frozen"] is not True
        or data["protocol_sha256"] != DEFAULT_PROTOCOL_SHA256
        or data["variant_registry_sha256"] != VARIANT_REGISTRY_SHA256
        or data["corpus_manifest_sha256"] != FROZEN_CORPUS_MANIFEST_SHA256
        or data["environment_sha256"] != frozen.inventory.sha256
        or data["source_binding"] != dict(frozen.source_binding)
        or data["selection_inputs"] != _selection_inputs(repository, frozen)
    ):
        raise MatrixReassessmentError("matrix frozen identity drifted")
    without_digest = {key: data[key] for key in data if key != "artifact_sha256"}
    if data["artifact_sha256"] != _sha(without_digest):
        raise MatrixReassessmentError("matrix artifact digest changed")
    raw_runs = data["split_runs"]
    if not isinstance(raw_runs, list) or len(raw_runs) != 2:
        raise MatrixReassessmentError("matrix split run set is incomplete")

    plans = build_reassessment_plans(frozen, run_id=expected_run_id)
    summaries: list[Mapping[str, object]] = []
    for raw, plan in zip(raw_runs, plans, strict=True):
        split_root = output_root / plan.split.value
        try:
            run = validate_ablation_evidence(plan, output_root=split_root)
        except AblationValidationError as exc:
            raise MatrixReassessmentError(
                f"{plan.split.value} ablation evidence is invalid: {exc}"
            ) from exc
        ledger_path = _ledger_path(split_root)
        ledger = _validate_ledger(
            _read_canonical(ledger_path, "resource ledger"), run
        )
        summary = _split_summary(
            run=run,
            split_root=split_root,
            index_path=index_path,
            ledger_path=ledger_path,
            ledger=ledger,
        )
        if raw != summary:
            raise MatrixReassessmentError(
                f"{plan.split.value} matrix summary changed"
            )
        summaries.append(summary)
    expected = _build_index(frozen, summaries, repository)
    if data != expected:
        raise MatrixReassessmentError("matrix aggregate recomputation changed")
    return MappingProxyType(dict(data))


def validate_reassessment_matrix(
    *,
    repository_root: str | Path = ".",
    run_id: str = REASSESSMENT_RUN_ID,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    receipt_directory: str | Path | None = None,
    baseline_manifest: str | Path | None = None,
    output_root: str | Path | None = None,
    snapshot_path: str | Path | None = None,
    frozen_reprobe: LiveCapabilityReprobe | None = None,
) -> Mapping[str, object]:
    """Read-only, strict validation of the complete persisted matrix."""

    repository = Path(repository_root).resolve()
    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ValueError as exc:
        raise MatrixReassessmentError("matrix run_id is invalid") from exc
    root = Path(layout.matrix_root if output_root is None else output_root)
    snapshot = Path(
        layout.matrix_snapshot if snapshot_path is None else snapshot_path
    )
    index_path = _index_path(root)
    try:
        frozen = frozen_reprobe or validate_frozen_capability_reprobe(
            repository_root=repository,
            expected_run_id=run_id,
            benchmark_root=benchmark_root,
            baseline_manifest=baseline_manifest,
            receipt_directory=receipt_directory,
        )
        if frozen.inventory.run_id != run_id:
            raise MatrixReassessmentError("capability run identity drifted")
        index = _validate_index_payload(
            _read_canonical(index_path, "matrix index"),
            frozen=frozen,
            repository=repository,
            index_path=index_path,
            output_root=root,
            expected_run_id=run_id,
        )
        actual_snapshot = _read_canonical(snapshot, "matrix snapshot")
        actual_snapshot_mapping = _mapping(
            actual_snapshot,
            "matrix snapshot",
        )
        expected_snapshot = _snapshot(
            index,
            index_path,
            repository=repository,
            benchmark_root=benchmark_root,
            captured_on=actual_snapshot_mapping.get("captured_on"),
        )
        if actual_snapshot != expected_snapshot:
            raise MatrixReassessmentError("public matrix snapshot changed")
    except (CapabilityContractError, CorpusContractError) as exc:
        raise MatrixReassessmentError("matrix prerequisite is invalid") from exc
    return index


def execute_reassessment_matrix(
    frozen_reprobe: LiveCapabilityReprobe | None = None,
    *,
    repository_root: str | Path = ".",
    run_id: str | None = None,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    receipt_directory: str | Path | None = None,
    baseline_manifest: str | Path | None = None,
    output_root: str | Path | None = None,
    snapshot_path: str | Path | None = None,
    splits: Sequence[Split] = _MATRIX_SPLITS,
    cache_modes: Sequence[CacheMode] = _MATRIX_CACHE_MODES,
    seed: int = MATRIX_SEED,
    handlers: RuntimeBackendHandlers | None = None,
    resume: bool = True,
) -> Mapping[str, object]:
    """Execute once or strictly resume the unchanged complete matrix."""

    if type(resume) is not bool:
        raise MatrixReassessmentError("resume must be a boolean")
    repository = Path(repository_root).resolve()
    selected_run_id = (
        frozen_reprobe.inventory.run_id
        if run_id is None and frozen_reprobe is not None
        else run_id
    )
    if selected_run_id is None:
        raise MatrixReassessmentError(
            "fresh matrix execution requires an explicit run_id"
        )
    try:
        layout = require_fresh_reassessment_run(
            selected_run_id,
            benchmark_root=benchmark_root,
        )
    except ReassessmentNamespaceError as exc:
        raise MatrixReassessmentError(str(exc)) from exc
    if (
        frozen_reprobe is not None
        and frozen_reprobe.inventory.run_id != selected_run_id
    ):
        raise MatrixReassessmentError("capability run identity drifted")
    root = Path(layout.matrix_root if output_root is None else output_root)
    snapshot = Path(
        layout.matrix_snapshot if snapshot_path is None else snapshot_path
    )
    index_path = _index_path(root)
    try:
        reject_published_write_targets(
            repository_root=repository,
            run_id=selected_run_id,
            targets=(root, index_path, snapshot),
            benchmark_root=benchmark_root,
        )
    except ReassessmentNamespaceError as exc:
        raise MatrixReassessmentError(str(exc)) from exc
    if index_path.exists():
        if not resume:
            raise MatrixReassessmentError("matrix evidence already exists")
        return validate_reassessment_matrix(
            repository_root=repository,
            run_id=selected_run_id,
            benchmark_root=benchmark_root,
            receipt_directory=receipt_directory,
            baseline_manifest=baseline_manifest,
            output_root=root,
            snapshot_path=snapshot,
            frozen_reprobe=frozen_reprobe,
        )
    frozen = frozen_reprobe or validate_frozen_capability_reprobe(
        repository_root=repository,
        expected_run_id=selected_run_id,
        benchmark_root=benchmark_root,
        baseline_manifest=baseline_manifest,
        receipt_directory=receipt_directory,
    )
    plans = build_reassessment_plans(
        frozen,
        run_id=selected_run_id,
        splits=splits,
        cache_modes=cache_modes,
        seed=seed,
    )
    live = build_live_runtime(
        frozen.inventory,
        handlers or RuntimeBackendHandlers(),
        state_directory=root / "processes",
        leanstral_timeout_seconds=plans[0].limits.case_timeout_seconds,
        leanstral_max_new_tokens=LEANSTRAL_MEASURED_MAX_NEW_TOKENS,
    )
    summaries: list[Mapping[str, object]] = []
    try:
        for plan in plans:
            split_root = root / plan.split.value
            ledger_path = _ledger_path(split_root)
            if split_root.exists():
                if not ledger_path.is_file():
                    raise MatrixReassessmentError(
                        f"{plan.split.value} has partial evidence without a "
                        "completed resource ledger; use a fresh split namespace"
                    )
                validated_run = validate_ablation_evidence(
                    plan, output_root=split_root
                )
                ledger = _validate_ledger(
                    _read_canonical(ledger_path, "resource ledger"),
                    validated_run,
                )
                summaries.append(
                    _split_summary(
                        run=validated_run,
                        split_root=split_root,
                        index_path=index_path,
                        ledger_path=ledger_path,
                        ledger=ledger,
                    )
                )
                continue
            run = execute_ablation(
                plan,
                live.adapters,
                output_root=split_root,
                resume=False,
            )
            if not run.complete:
                raise MatrixReassessmentError(
                    f"{plan.split.value} execution is incomplete"
                )
            ledger_value = _build_ledger(run)
            _write_once(ledger_path, ledger_value)
            validated_run = validate_ablation_evidence(
                plan, output_root=split_root
            )
            ledger = _validate_ledger(ledger_value, validated_run)
            summaries.append(
                _split_summary(
                    run=validated_run,
                    split_root=split_root,
                    index_path=index_path,
                    ledger_path=ledger_path,
                    ledger=ledger,
                )
            )
    finally:
        live.close()
    index = _build_index(frozen, summaries, repository)
    _write_once(index_path, index)
    _write_once(
        snapshot,
        _snapshot(
            index,
            index_path,
            repository=repository,
            benchmark_root=benchmark_root,
        ),
    )
    return validate_reassessment_matrix(
        repository_root=repository,
        run_id=selected_run_id,
        benchmark_root=benchmark_root,
        receipt_directory=receipt_directory,
        baseline_manifest=baseline_manifest,
        output_root=root,
        snapshot_path=snapshot,
        frozen_reprobe=frozen,
    )


__all__ = [
    "DEFAULT_MATRIX_INDEX",
    "DEFAULT_MATRIX_ROOT",
    "DEFAULT_MATRIX_SNAPSHOT",
    "EXPECTED_COORDINATE_COUNT",
    "FROZEN_SELECTION_BYTES_SHA256",
    "FROZEN_SELECTION_PATH",
    "FROZEN_SELECTION_SHA256S",
    "HSSLEV1305A27",
    "MATRIX_INDEX_SCHEMA",
    "MATRIX_SEED",
    "MATRIX_SNAPSHOT_SCHEMA",
    "MatrixReassessmentError",
    "build_reassessment_plans",
    "execute_reassessment_matrix",
    "validate_reassessment_matrix",
]
