"""Source-bound pilot/development execution for the HSSL reassessment.

The aggregate in this module is deliberately narrower than the generic
ablation runner: it accepts only the frozen ``reassessment-v2`` capability
freeze, parses only the unsealed pilot and development corpus records, and
publishes one strict receipt over the complete 560-coordinate matrix.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Final, Mapping, Sequence

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
    DEFAULT_RECEIPT_DIRECTORY,
    LiveCapabilityReprobe,
    REASSESSMENT_RUN_ID,
    validate_frozen_capability_reprobe,
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
    case_sha256,
    corpus_manifest_sha256,
    load_manifest,
)
from .contracts import (
    DEFAULT_PROTOCOL_SHA256,
    CacheMode,
    CaseResultRecord,
    OutcomeStatus,
    StageName,
    canonical_json,
)
from .runtime import RuntimeBackendHandlers, build_live_runtime
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
    "workspace/benchmarks/hammer-symai-spacy-leanstral/"
    "reassessment-v2/results/matrix"
)
DEFAULT_MATRIX_INDEX: Final = Path(
    "workspace/benchmarks/hammer-symai-spacy-leanstral/"
    "reassessment-v2/results/matrix-execution-v2.json"
)
DEFAULT_MATRIX_SNAPSHOT: Final = Path(
    "docs/performance_snapshots/2026-07-24_hssl_reassessment_matrix.json"
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
    """Load exactly the first twenty manifest-bound, unsealed corpus records.

    The frozen manifest exposes holdout identifiers and digests, but not
    semantic targets.  Reading stops after the declared pilot/development
    count, so no holdout JSON object is read or deserialized.
    """

    manifest = load_manifest(manifest_path)
    if (
        corpus_manifest_sha256(manifest) != FROZEN_CORPUS_MANIFEST_SHA256
        or manifest.split_counts.get(Split.PILOT.value)
        != EXPECTED_CASES_PER_SPLIT
        or manifest.split_counts.get(Split.DEVELOPMENT.value)
        != EXPECTED_CASES_PER_SPLIT
        or manifest.split_counts.get(Split.HOLDOUT.value)
        != EXPECTED_CASES_PER_SPLIT
    ):
        raise MatrixReassessmentError("frozen reviewed manifest identity drifted")
    selected_count = 2 * EXPECTED_CASES_PER_SPLIT
    expected_entries = manifest.cases[:selected_count]
    if (
        tuple(entry.ordinal for entry in expected_entries)
        != tuple(range(selected_count))
        or {entry.split for entry in expected_entries} != set(_MATRIX_SPLITS)
        or any(
            entry.split is Split.HOLDOUT
            for entry in expected_entries
        )
        or any(
            entry.split is not Split.HOLDOUT
            for entry in manifest.cases[selected_count:]
        )
    ):
        raise MatrixReassessmentError("manifest split seal or ordering drifted")

    cases: list[BenchmarkCase] = []
    try:
        # Unbuffered binary IO ensures this boundary requests only the twenty
        # unsealed newline records, rather than prefetching the holdout tail.
        with Path(corpus_path).open("rb", buffering=0) as handle:
            for ordinal, entry in enumerate(expected_entries):
                raw = handle.readline()
                if not raw.endswith(b"\n") or not raw.strip():
                    raise MatrixReassessmentError(
                        f"unsealed corpus line {ordinal + 1} is incomplete"
                    )
                try:
                    text = raw[:-1].decode("utf-8")
                    value = json.loads(
                        text, object_pairs_hook=_reject_duplicate_pairs
                    )
                    case = BenchmarkCase.from_dict(value)
                except (
                    UnicodeError,
                    json.JSONDecodeError,
                    ValueError,
                    CorpusContractError,
                ) as exc:
                    raise MatrixReassessmentError(
                        f"unsealed corpus line {ordinal + 1} is invalid"
                    ) from exc
                if canonical_json(case.to_dict()) != text:
                    raise MatrixReassessmentError(
                        f"unsealed corpus line {ordinal + 1} is not canonical"
                    )
                if (
                    case.case_id != entry.case_id
                    or case.split is not entry.split
                    or case.stratum != entry.stratum
                    or case.source_sha256 != entry.source_sha256
                    or case_sha256(case) != entry.case_sha256
                ):
                    raise MatrixReassessmentError(
                        f"unsealed corpus line {ordinal + 1} drifted"
                    )
                cases.append(case)
    except OSError as exc:
        raise MatrixReassessmentError("cannot open unsealed corpus prefix") from exc
    return manifest, tuple(cases)


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
    splits: Sequence[Split] = _MATRIX_SPLITS,
    cache_modes: Sequence[CacheMode] = _MATRIX_CACHE_MODES,
    seed: int = MATRIX_SEED,
    limits: ResourceLimits = ResourceLimits(),
) -> tuple[AblationPlan, ...]:
    """Build the exact unchanged pilot/development schedule."""

    if not isinstance(frozen_reprobe, LiveCapabilityReprobe):
        raise MatrixReassessmentError("frozen_reprobe is invalid")
    if frozen_reprobe.inventory.run_id != REASSESSMENT_RUN_ID:
        raise MatrixReassessmentError("capability run identity drifted")
    selected_splits = _normalize_splits(splits)
    selected_modes = _normalize_modes(cache_modes)
    manifest, cases = _sealed_non_holdout_cases()
    plans = tuple(
        build_ablation_plan(
            REASSESSMENT_RUN_ID,
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
        "invalid_control_verified_count": invalid_verified,
        "results": refs,
    }


def _selection_inputs() -> dict[str, object]:
    return {
        "splits": [split.value for split in _MATRIX_SPLITS],
        "cache_modes": [mode.value for mode in _MATRIX_CACHE_MODES],
        "variant_ids": list(ALL_VARIANT_IDS),
        "prompts_frozen": True,
        "policies_frozen": True,
        "model_identities_frozen": True,
        "thresholds_frozen": True,
        "selection_inputs_changed": False,
        "tuning_permitted": True,
    }


def _build_index(
    frozen: LiveCapabilityReprobe,
    summaries: Sequence[Mapping[str, object]],
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
    }
    without_digest = {
        "schema": MATRIX_INDEX_SCHEMA,
        "evidence": "HSSLEV1305A27",
        "run_id": REASSESSMENT_RUN_ID,
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
        "selection_inputs": _selection_inputs(),
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
        },
    }
    if totals["case_count"] != 20 or totals["coordinate_count"] != 560:
        raise MatrixReassessmentError("aggregate matrix total is incomplete")
    return {**without_digest, "artifact_sha256": _sha(without_digest)}


def _snapshot(index: Mapping[str, object], index_path: Path) -> dict[str, object]:
    source = _mapping(index["source_binding"], "source binding")
    return {
        "benchmark_script": REQUIRED_COMMAND,
        "captured_on": "2026-07-24",
        "notes": [
            "This snapshot contains the unchanged A0-A12 and S1 pilot/development matrix.",
            "Cold and warm routes are isolated and counterbalanced; failures remain typed evidence.",
            "No holdout semantic record was read and no production route was changed.",
        ],
        "results": {
            "schema": MATRIX_SNAPSHOT_SCHEMA,
            "evidence": "HSSLEV1305A27",
            "run_id": REASSESSMENT_RUN_ID,
            "status": "complete",
            "frozen": True,
            "artifact": {
                "path": index_path.as_posix(),
                "bytes_sha256": _sha_bytes(index_path.read_bytes()),
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
    index_path: Path,
    output_root: Path,
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
        or data["run_id"] != REASSESSMENT_RUN_ID
        or data["status"] != "complete"
        or data["frozen"] is not True
        or data["protocol_sha256"] != DEFAULT_PROTOCOL_SHA256
        or data["variant_registry_sha256"] != VARIANT_REGISTRY_SHA256
        or data["corpus_manifest_sha256"] != FROZEN_CORPUS_MANIFEST_SHA256
        or data["environment_sha256"] != frozen.inventory.sha256
        or data["source_binding"] != dict(frozen.source_binding)
        or data["selection_inputs"] != _selection_inputs()
    ):
        raise MatrixReassessmentError("matrix frozen identity drifted")
    without_digest = {key: data[key] for key in data if key != "artifact_sha256"}
    if data["artifact_sha256"] != _sha(without_digest):
        raise MatrixReassessmentError("matrix artifact digest changed")
    raw_runs = data["split_runs"]
    if not isinstance(raw_runs, list) or len(raw_runs) != 2:
        raise MatrixReassessmentError("matrix split run set is incomplete")

    plans = build_reassessment_plans(frozen)
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
    expected = _build_index(frozen, summaries)
    if data != expected:
        raise MatrixReassessmentError("matrix aggregate recomputation changed")
    return MappingProxyType(dict(data))


def validate_reassessment_matrix(
    *,
    repository_root: str | Path = ".",
    output_root: str | Path = DEFAULT_MATRIX_ROOT,
    snapshot_path: str | Path = DEFAULT_MATRIX_SNAPSHOT,
) -> Mapping[str, object]:
    """Read-only, strict validation of the complete persisted matrix."""

    repository = Path(repository_root).resolve()
    root = Path(output_root)
    index_path = _index_path(root)
    try:
        frozen = validate_frozen_capability_reprobe(
            repository_root=repository,
            receipt_directory=repository / DEFAULT_RECEIPT_DIRECTORY,
        )
        index = _validate_index_payload(
            _read_canonical(index_path, "matrix index"),
            frozen=frozen,
            index_path=index_path,
            output_root=root,
        )
        expected_snapshot = _snapshot(index, index_path)
        if _read_canonical(Path(snapshot_path), "matrix snapshot") != expected_snapshot:
            raise MatrixReassessmentError("public matrix snapshot changed")
    except (CapabilityContractError, CorpusContractError) as exc:
        raise MatrixReassessmentError("matrix prerequisite is invalid") from exc
    return index


def execute_reassessment_matrix(
    frozen_reprobe: LiveCapabilityReprobe | None = None,
    *,
    repository_root: str | Path = ".",
    output_root: str | Path = DEFAULT_MATRIX_ROOT,
    snapshot_path: str | Path = DEFAULT_MATRIX_SNAPSHOT,
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
    root = Path(output_root)
    index_path = _index_path(root)
    if index_path.exists():
        if not resume:
            raise MatrixReassessmentError("matrix evidence already exists")
        return validate_reassessment_matrix(
            repository_root=repository,
            output_root=root,
            snapshot_path=snapshot_path,
        )
    if root.exists():
        raise MatrixReassessmentError(
            "partial matrix namespace exists without an aggregate receipt; "
            "use a fresh run namespace"
        )
    frozen = frozen_reprobe or validate_frozen_capability_reprobe(
        repository_root=repository,
        receipt_directory=repository / DEFAULT_RECEIPT_DIRECTORY,
    )
    plans = build_reassessment_plans(
        frozen,
        splits=splits,
        cache_modes=cache_modes,
        seed=seed,
    )
    live = build_live_runtime(
        frozen.inventory,
        handlers or RuntimeBackendHandlers(),
        state_directory=root / "processes",
    )
    summaries: list[Mapping[str, object]] = []
    try:
        for plan in plans:
            split_root = root / plan.split.value
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
            ledger_path = _ledger_path(split_root)
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
    index = _build_index(frozen, summaries)
    _write_once(index_path, index)
    _write_once(Path(snapshot_path), _snapshot(index, index_path))
    return validate_reassessment_matrix(
        repository_root=repository,
        output_root=root,
        snapshot_path=snapshot_path,
    )


__all__ = [
    "DEFAULT_MATRIX_INDEX",
    "DEFAULT_MATRIX_ROOT",
    "DEFAULT_MATRIX_SNAPSHOT",
    "EXPECTED_COORDINATE_COUNT",
    "HSSLEV1305A27",
    "MATRIX_INDEX_SCHEMA",
    "MATRIX_SEED",
    "MATRIX_SNAPSHOT_SCHEMA",
    "MatrixReassessmentError",
    "build_reassessment_plans",
    "execute_reassessment_matrix",
    "validate_reassessment_matrix",
]
