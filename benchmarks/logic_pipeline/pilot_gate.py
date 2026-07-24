"""Canonical pilot completion and shortlist-freeze evidence.

This module is the trust boundary for HSSL-G080.  It does not rank incomplete
arms or turn capability-preflight records into efficacy measurements.  The
gate reloads and revalidates the frozen A0 manifest and the front-end and proof
reports, normalizes their pilot evidence into one complete matrix, and binds
the resulting empty shortlist to the preregistered protocol.

The current checked-in source reports are capability preflights.  Consequently
the structurally complete gate is intentionally ``incomplete`` for efficacy,
the nonbaseline shortlist is empty, and holdout access is not authorized.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
from typing import Final, Mapping, Sequence

from benchmarks.logic_pipeline import BENCHMARK_ID
from benchmarks.logic_pipeline.contracts import (
    DEFAULT_PROTOCOL,
    DEFAULT_PROTOCOL_SHA256,
    canonical_json,
)
from benchmarks.logic_pipeline.variants import (
    ALL_VARIANT_IDS,
    VARIANT_REGISTRY,
    VARIANT_REGISTRY_SHA256,
)


PILOT_GATE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.pilot-shortlist-gate.v1"
)
PILOT_SHORTLIST_SCHEMA: Final = PILOT_GATE_SCHEMA
PILOT_OUTCOME_CELL_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.pilot-outcome-cell.v1"
)
PILOT_FREEZE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.pilot-deep-freeze.v1"
)
PILOT_GATE_RUN_ID: Final = "pilot-shortlist-v1"
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_PILOT_GATE_PATH: Final = Path(
    "workspace/benchmarks/hammer-symai-spacy-leanstral/results/"
    "pilot-shortlist-v1.json"
)
DEFAULT_PILOT_SHORTLIST_PATH: Final = DEFAULT_PILOT_GATE_PATH
FRONTEND_SOURCE_PATH: Final = Path(
    "workspace/benchmarks/hammer-symai-spacy-leanstral/results/"
    "frontend-overlap-v1.json"
)
PROOF_SOURCE_PATH: Final = Path(
    "workspace/benchmarks/hammer-symai-spacy-leanstral/results/"
    "proof-overlap-ordering-v1.json"
)
BASELINE_SOURCE_PATH: Final = Path(
    "workspace/benchmarks/hammer-symai-spacy-leanstral/a0-baseline-v1/"
    "state/baseline-manifest.json"
)
ALLOWED_SOURCE_PATHS: Final = frozenset(
    {
        FRONTEND_SOURCE_PATH.as_posix(),
        PROOF_SOURCE_PATH.as_posix(),
        BASELINE_SOURCE_PATH.as_posix(),
    }
)
PILOT_CASE_IDS: Final = tuple(f"pilot-p{index:02d}" for index in range(1, 11))
CACHE_MODES: Final = ("cold", "warm")
NONBASELINE_CANDIDATE_IDS: Final = tuple(
    variant_id for variant_id in ALL_VARIANT_IDS if variant_id not in {"A0", "S1"}
)
OVERLAP_VARIANT_IDS: Final = ("A4", "A7", "A8")
INVALID_CONTROL_EXPECTED_CLASSES: Final = frozenset({"unsupported"})
_MAX_REPORT_BYTES: Final = 32 * 1024 * 1024
_REPORT_FIELDS: Final = {
    "schema",
    "evidence",
    "benchmark_id",
    "run_id",
    "source_bindings",
    "normalization",
    "capability_diagnoses",
    "outcome_ledger",
    "safety",
    "variant_dispositions",
    "shortlist",
    "holdout",
    "deep_freeze",
    "decision",
    "artifact_sha256",
}


class PilotGateError(ValueError):
    """Raised when pilot evidence cannot support the frozen gate."""


def HSSLEV0801D68() -> str:
    """Return AST-verifiable evidence for pilot completion and shortlist freeze."""

    return (
        "complete pilot outcome ledger, capability diagnosis, "
        "and deeply frozen nonbaseline shortlist"
    )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise PilotGateError(f"{field} must be an object with string keys")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise PilotGateError(f"{field} must be an array")
    return value


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PilotGateError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> object:
    raise PilotGateError(f"non-finite JSON number is forbidden: {token}")


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
        raise PilotGateError(f"repository root is unavailable: {root}") from exc
    if not resolved.is_dir():
        raise PilotGateError(f"repository root is not a directory: {resolved}")
    return resolved


def _resolve_allowlisted_source(
    repository_root: Path, relative_path: str | Path
) -> Path:
    raw = Path(relative_path).as_posix()
    pure = PurePosixPath(raw)
    if (
        raw not in ALLOWED_SOURCE_PATHS
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise PilotGateError(f"source path is not allowlisted: {raw!r}")
    candidate = repository_root.joinpath(*pure.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repository_root)
        mode = resolved.stat().st_mode
    except (OSError, ValueError) as exc:
        raise PilotGateError(f"allowlisted source is unavailable: {raw}") from exc
    if not stat.S_ISREG(mode):
        raise PilotGateError(f"allowlisted source is not a regular file: {raw}")
    return resolved


def _content_digest(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise PilotGateError(f"cannot hash source artifact: {path}") from exc


def _load_portable_frozen_baseline(
    path: Path, repository_root: Path
) -> tuple[dict[str, object], str]:
    """Validate the exact A0 snapshot while tolerating later outer gitlinks.

    ``runner.load_baseline_manifest`` additionally compares historic A0
    submodule gitlinks with the ambient checkout.  Benchmark worktrees
    intentionally advance the outer ``ipfs_accelerate_py`` gitlink, so that
    environmental check can fail even when the content-addressed snapshot is
    exact.  This fallback never compares ambient gitlinks.  It requires the
    canonical payload to equal the runner's immutable semantic digest and then
    independently verifies the identities consumed by this gate, including
    the pinned A0 route files and run contracts.
    """

    from benchmarks.logic_pipeline.runner import (
        BASELINE_ID,
        BASELINE_MANIFEST_SCHEMA,
        FROZEN_BASELINE_MANIFEST_SHA256,
        SOURCE_SNAPSHOT_FILES,
    )

    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PilotGateError("cannot read frozen A0 manifest") from exc
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise PilotGateError("frozen A0 manifest is not canonical newline JSON")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, PilotGateError) as exc:
        raise PilotGateError("frozen A0 manifest is not strict JSON") from exc
    baseline = dict(_mapping(value, "baseline manifest"))
    if raw != (canonical_json(baseline) + "\n").encode("utf-8"):
        raise PilotGateError("frozen A0 manifest is not canonical JSON")
    semantic_sha256 = _sha256_json(baseline)
    if semantic_sha256 != FROZEN_BASELINE_MANIFEST_SHA256:
        raise PilotGateError("frozen A0 manifest differs from its code pin")
    required = {
        "schema",
        "benchmark_id",
        "baseline_id",
        "evidence",
        "frozen",
        "source",
        "protocol",
        "corpus",
        "configuration",
        "capability_snapshot",
        "run_contracts",
        "telemetry_contract",
        "execution_contract",
        "safety",
    }
    if set(baseline) != required:
        raise PilotGateError("frozen A0 manifest top-level contract changed")
    if (
        baseline["schema"] != BASELINE_MANIFEST_SCHEMA
        or baseline["benchmark_id"] != BENCHMARK_ID
        or baseline["baseline_id"] != BASELINE_ID
        or baseline["frozen"] is not True
    ):
        raise PilotGateError("frozen A0 manifest identity changed")
    protocol = _mapping(baseline["protocol"], "baseline.protocol")
    if (
        set(protocol) != {"protocol_id", "sha256"}
        or protocol["protocol_id"] != DEFAULT_PROTOCOL.protocol_id
        or protocol["sha256"] != DEFAULT_PROTOCOL_SHA256
    ):
        raise PilotGateError("frozen A0 protocol binding changed")
    configuration = _mapping(
        baseline["configuration"], "baseline.configuration"
    )
    if (
        configuration.get("requested_variant_id") != "A0"
        or configuration.get("effective_variant_id") != "A0"
    ):
        raise PilotGateError("frozen baseline is not requested/effective A0")

    source = _mapping(baseline["source"], "baseline.source")
    if set(source) != {"repository_commit", "submodules", "files"}:
        raise PilotGateError("frozen A0 source contract changed")
    files = [
        _mapping(item, "baseline.source.files[]")
        for item in _array(source["files"], "baseline.source.files")
    ]
    if tuple(str(item.get("path")) for item in files) != SOURCE_SNAPSHOT_FILES:
        raise PilotGateError("frozen A0 route-file scope changed")
    for item in files:
        if set(item) != {"path", "sha256"}:
            raise PilotGateError("frozen A0 source-file record changed")
        source_path = repository_root / str(item["path"])
        try:
            actual_sha256 = _sha256_bytes(source_path.read_bytes())
        except OSError as exc:
            raise PilotGateError(
                f"cannot read frozen A0 route file: {item['path']}"
            ) from exc
        if actual_sha256 != item["sha256"]:
            raise PilotGateError(
                f"frozen A0 route file drifted: {item['path']}"
            )

    contracts = [
        _mapping(item, "baseline.run_contracts[]")
        for item in _array(baseline["run_contracts"], "baseline.run_contracts")
    ]
    if [item.get("cache_mode") for item in contracts] != ["cold", "warm"]:
        raise PilotGateError("frozen A0 cache-mode contract changed")
    for contract in contracts:
        if (
            contract.get("run_id") != "a0-baseline-v1"
            or contract.get("protocol_sha256") != DEFAULT_PROTOCOL_SHA256
            or contract.get("requested_variant_id") != "A0"
            or contract.get("effective_variant_id") != "A0"
            or contract.get("split") != "pilot"
            or contract.get("holdout_access_log_id") is not None
            or contract.get("prompts_frozen") is not True
            or contract.get("policy_frozen") is not True
            or contract.get("model_identities_frozen") is not True
            or contract.get("thresholds_frozen") is not True
            or contract.get("tuning_permitted") is not False
        ):
            raise PilotGateError("frozen A0 run contract changed")
    corpus = _mapping(baseline["corpus"], "baseline.corpus")
    if (
        corpus.get("split") != "pilot"
        or not isinstance(corpus.get("manifest_sha256"), str)
        or not isinstance(corpus.get("split_sha256"), str)
        or len(_array(corpus.get("cases"), "baseline.corpus.cases")) != 10
    ):
        raise PilotGateError("frozen A0 corpus binding changed")
    if _mapping(baseline["safety"], "baseline.safety") != {
        "shadow_only": True,
        "network_enabled": False,
        "model_calls_enabled": False,
        "auto_merge": False,
        "production_routing_changes": False,
    }:
        raise PilotGateError("frozen A0 safety boundary changed")
    return baseline, semantic_sha256


def _load_sources(
    repository_root: Path,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    list[dict[str, object]],
]:
    # Imports are deliberately local so report.py can dispatch this module
    # without creating a module-import cycle.
    from benchmarks.logic_pipeline.frontend_report import load_frontend_report
    from benchmarks.logic_pipeline.report import load_proof_report
    from benchmarks.logic_pipeline.runner import (
        BaselineValidationError,
        load_baseline_manifest,
    )

    frontend_path = _resolve_allowlisted_source(
        repository_root, FRONTEND_SOURCE_PATH
    )
    proof_path = _resolve_allowlisted_source(repository_root, PROOF_SOURCE_PATH)
    baseline_path = _resolve_allowlisted_source(
        repository_root, BASELINE_SOURCE_PATH
    )
    try:
        frontend = load_frontend_report(frontend_path)
        proof = load_proof_report(proof_path)
    except (OSError, TypeError, ValueError) as exc:
        raise PilotGateError("a pilot source artifact failed revalidation") from exc
    try:
        baseline_manifest = load_baseline_manifest(baseline_path)
    except BaselineValidationError as exc:
        if str(exc) != "recorded submodule gitlinks drifted":
            raise PilotGateError(
                "the frozen A0 manifest failed revalidation"
            ) from exc
        baseline, baseline_semantic_sha256 = _load_portable_frozen_baseline(
            baseline_path, repository_root
        )
    else:
        baseline = baseline_manifest.to_dict()
        baseline_semantic_sha256 = baseline_manifest.digest
    bindings = [
        {
            "kind": "frontend_overlap_report",
            "path": FRONTEND_SOURCE_PATH.as_posix(),
            "schema": frontend["schema"],
            "content_sha256": _content_digest(frontend_path),
            "semantic_sha256": frontend["artifact_sha256"],
        },
        {
            "kind": "proof_overlap_report",
            "path": PROOF_SOURCE_PATH.as_posix(),
            "schema": proof["schema"],
            "content_sha256": _content_digest(proof_path),
            "semantic_sha256": proof["artifact_sha256"],
        },
        {
            "kind": "frozen_a0_manifest",
            "path": BASELINE_SOURCE_PATH.as_posix(),
            "schema": baseline["schema"],
            "content_sha256": _content_digest(baseline_path),
            "semantic_sha256": baseline_semantic_sha256,
        },
    ]
    return frontend, proof, baseline, bindings


def _observation_index(
    report: Mapping[str, object],
    *,
    include_split: bool,
) -> dict[tuple[str, str, str], Mapping[str, object]]:
    result: dict[tuple[str, str, str], Mapping[str, object]] = {}
    for raw in _array(report["observations"], "observations"):
        row = _mapping(raw, "observation")
        if include_split and row["split"] != "pilot":
            continue
        coordinate = (
            str(row["variant_id"]),
            str(row["cache_mode"]),
            str(row["case_id"]),
        )
        if coordinate in result:
            raise PilotGateError(f"duplicate source coordinate: {coordinate!r}")
        result[coordinate] = row
    return result


def _source_receipt(row: Mapping[str, object]) -> str:
    value = row.get("source_receipt_sha256")
    if not isinstance(value, str):
        raise PilotGateError("source observation has no receipt digest")
    return value


def _frontend_semantic(row: Mapping[str, object] | None) -> bool | None:
    if row is None:
        return None
    status = row["status"]
    if status == "semantically_incorrect":
        return False
    if status != "semantically_correct":
        return None
    return bool(
        row["normalized_ir_exact_match"]
        or row["deterministic_semantic_equivalence"]
    )


def _proof_verified(row: Mapping[str, object] | None) -> bool | None:
    if row is None:
        return None
    status = row["status"]
    if status == "verified":
        if (
            row["kernel_accepted"] is not True
            or row["verification_authority"] != "native_kernel"
            or not isinstance(row["kernel_receipt_sha256"], str)
        ):
            raise PilotGateError(
                "a verified proof observation is not native-kernel bound"
            )
        return True
    if status in {"not_verified", "rejected"}:
        return False
    return None


def _available_frontend(row: Mapping[str, object]) -> bool:
    return row["status"] not in {"unavailable", "infrastructure_failure"}


def _available_proof(row: Mapping[str, object]) -> bool:
    return row["status"] not in {
        "unavailable",
        "excluded",
        "infrastructure_failure",
    }


def _missing_reasons(
    frontend: Mapping[str, object] | None,
    proof: Mapping[str, object] | None,
    *,
    synthetic_exclusion: bool,
) -> list[str]:
    reasons: list[str] = []
    for row in (frontend, proof):
        if row is None:
            continue
        value = row.get("missing_reason")
        if isinstance(value, str) and value and value not in reasons:
            reasons.append(value)
    if synthetic_exclusion:
        reasons.append(
            "case is outside the frozen proof-eligible scope; no proof "
            "efficacy observation was synthesized"
        )
    return reasons


def _cell_status(
    frontend: Mapping[str, object] | None,
    proof: Mapping[str, object] | None,
    *,
    synthetic_exclusion: bool,
) -> str:
    if synthetic_exclusion:
        return "excluded_nonproof"
    statuses = {
        str(row["status"]) for row in (frontend, proof) if row is not None
    }
    if "infrastructure_failure" in statuses:
        return "infrastructure_failure"
    if statuses & {"unavailable", "excluded"}:
        return "unavailable"
    if statuses:
        return "observed"
    raise PilotGateError("normalization produced an evidence-free cell")


def _normalize_ledger(
    frontend: Mapping[str, object],
    proof: Mapping[str, object],
    baseline: Mapping[str, object],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    front_index = _observation_index(frontend, include_split=True)
    proof_index = _observation_index(proof, include_split=False)
    frontend_variants = tuple(
        str(item)
        for item in _array(frontend["variant_ids"], "frontend.variant_ids")
    )
    proof_variants = tuple(
        str(item)
        for item in (
            *_array(
                proof["primary_variant_ids"], "proof.primary_variant_ids"
            ),
            *_array(
                proof["diagnostic_variant_ids"],
                "proof.diagnostic_variant_ids",
            ),
        )
    )
    proof_eligible = tuple(
        str(item)
        for item in _array(
            proof["eligible_case_ids"], "proof.eligible_case_ids"
        )
    )
    proof_excluded = tuple(
        str(item)
        for item in _array(
            proof["excluded_case_ids"], "proof.excluded_case_ids"
        )
    )
    if set(proof_eligible) & set(proof_excluded):
        raise PilotGateError("proof eligible and excluded case scopes overlap")
    # The report validator freezes each list; this additionally proves that
    # together they cover the complete pilot ledger without unknown cases.
    if (
        len(proof_eligible) + len(proof_excluded) != len(PILOT_CASE_IDS)
        or set((*proof_eligible, *proof_excluded)) != set(PILOT_CASE_IDS)
    ):
        raise PilotGateError("proof scopes do not partition all pilot cases")

    baseline_corpus = _mapping(baseline["corpus"], "baseline.corpus")
    baseline_cases = [
        _mapping(item, "baseline.corpus.cases[]")
        for item in _array(baseline_corpus["cases"], "baseline.corpus.cases")
    ]
    baseline_ids = tuple(str(item["case_id"]) for item in baseline_cases)
    front_case_ids = _mapping(
        frontend["case_ids_by_split"], "frontend.case_ids_by_split"
    )
    if (
        baseline_ids != PILOT_CASE_IDS
        or tuple(front_case_ids["pilot"]) != PILOT_CASE_IDS  # type: ignore[arg-type]
        or set((*proof_eligible, *proof_excluded)) != set(PILOT_CASE_IDS)
    ):
        raise PilotGateError("source artifacts disagree on pilot case identity")
    if (
        frontend["protocol_sha256"] != DEFAULT_PROTOCOL_SHA256
        or proof["protocol_sha256"] != DEFAULT_PROTOCOL_SHA256
        or _mapping(baseline["protocol"], "baseline.protocol")["sha256"]
        != DEFAULT_PROTOCOL_SHA256
    ):
        raise PilotGateError("source artifacts disagree on protocol identity")
    if (
        frontend["registry_sha256"] != VARIANT_REGISTRY_SHA256
        or proof["registry_sha256"] != VARIANT_REGISTRY_SHA256
    ):
        raise PilotGateError("source artifacts disagree on registry identity")
    corpus_sha = baseline_corpus["manifest_sha256"]
    if (
        frontend["corpus_manifest_sha256"] != corpus_sha
        or proof["corpus_manifest_sha256"] != corpus_sha
    ):
        raise PilotGateError("source artifacts disagree on corpus identity")

    strata = _mapping(frontend["stratum_by_case"], "frontend.stratum_by_case")
    expected_classes: dict[str, str] = {}
    for case_id in PILOT_CASE_IDS:
        candidates = {
            str(row["expected_class"])
            for row in front_index.values()
            if row["case_id"] == case_id
        }
        if len(candidates) != 1:
            raise PilotGateError(
                f"front-end evidence does not fix expected class for {case_id}"
            )
        expected_classes[case_id] = candidates.pop()

    ledger: list[dict[str, object]] = []
    kind_counts = {
        "frontend_only": 0,
        "proof_only": 0,
        "frontend_and_proof": 0,
        "excluded_nonproof": 0,
    }
    for variant_id in ALL_VARIANT_IDS:
        for cache_mode in CACHE_MODES:
            for case_id in PILOT_CASE_IDS:
                coordinate = (variant_id, cache_mode, case_id)
                front = front_index.get(coordinate)
                proof_row = proof_index.get(coordinate)
                is_proof_variant = variant_id in proof_variants
                excluded_from_proof = (
                    is_proof_variant and case_id in proof_excluded
                )
                synthetic_exclusion = (
                    front is None
                    and proof_row is None
                    and excluded_from_proof
                )
                if front is None and proof_row is None and not synthetic_exclusion:
                    raise PilotGateError(
                        f"pilot evidence is incomplete at {coordinate!r}"
                    )
                if front is not None and variant_id not in frontend_variants:
                    raise PilotGateError("unexpected front-end variant coordinate")
                if proof_row is not None and (
                    variant_id not in proof_variants
                    or case_id not in proof_eligible
                ):
                    raise PilotGateError("unexpected proof variant/case coordinate")
                if front is not None and proof_row is not None:
                    if variant_id not in OVERLAP_VARIANT_IDS:
                        raise PilotGateError("unregistered source-report overlap")
                    if _available_frontend(front) != _available_proof(proof_row):
                        raise PilotGateError(
                            f"overlap availability disagrees at {coordinate!r}"
                        )
                    observation_kind = "frontend_and_proof"
                elif front is not None:
                    observation_kind = "frontend_only"
                elif proof_row is not None:
                    observation_kind = "proof_only"
                else:
                    observation_kind = "excluded_nonproof"
                kind_counts[observation_kind] += 1

                semantic_success = _frontend_semantic(front)
                kernel_verified = _proof_verified(proof_row)
                expected_class = expected_classes[case_id]
                is_invalid_control = (
                    expected_class in INVALID_CONTROL_EXPECTED_CLASSES
                )
                invalid_false_positive = (
                    kernel_verified
                    if is_invalid_control and kernel_verified is not None
                    else None
                )
                source_rows = [
                    ("frontend", front),
                    ("proof", proof_row),
                ]
                source_observations = [
                    {
                        "source": source,
                        "observation_sha256": _sha256_json(row),
                        "source_receipt_sha256": _source_receipt(row),
                        "status": row["status"],
                    }
                    for source, row in source_rows
                    if row is not None
                ]
                ledger.append(
                    {
                        "schema": PILOT_OUTCOME_CELL_SCHEMA,
                        "variant_id": variant_id,
                        "cache_mode": cache_mode,
                        "case_id": case_id,
                        "stratum": strata[case_id],
                        "expected_class": expected_class,
                        "observation_kind": observation_kind,
                        "evidence_status": _cell_status(
                            front,
                            proof_row,
                            synthetic_exclusion=synthetic_exclusion,
                        ),
                        "proof_scope": (
                            "excluded_nonproof"
                            if excluded_from_proof
                            else (
                                "eligible"
                                if is_proof_variant
                                else "not_applicable"
                            )
                        ),
                        "source_observations": source_observations,
                        "semantic_success": semantic_success,
                        "kernel_verified": kernel_verified,
                        "invalid_control": is_invalid_control,
                        "invalid_control_kernel_false_positive": (
                            invalid_false_positive
                        ),
                        "efficacy_observed": (
                            semantic_success is not None
                            or kernel_verified is not None
                        ),
                        "missing_reasons": _missing_reasons(
                            front,
                            proof_row,
                            synthetic_exclusion=synthetic_exclusion,
                        ),
                    }
                )
    expected_count = len(ALL_VARIANT_IDS) * len(CACHE_MODES) * len(PILOT_CASE_IDS)
    if len(ledger) != expected_count or expected_count != 280:
        raise PilotGateError("normalized pilot ledger is not exactly 280 cells")
    expected_kind_counts = {
        "frontend_only": 78,
        "proof_only": 112,
        "frontend_and_proof": 42,
        "excluded_nonproof": 48,
    }
    if kind_counts != expected_kind_counts:
        raise PilotGateError(
            f"source normalization shape changed: {kind_counts!r}"
        )
    normalization = {
        "variant_ids": list(ALL_VARIANT_IDS),
        "candidate_variant_ids": list(NONBASELINE_CANDIDATE_IDS),
        "cache_modes": list(CACHE_MODES),
        "pilot_case_ids": list(PILOT_CASE_IDS),
        "proof_eligible_case_ids": list(proof_eligible),
        "proof_excluded_case_ids": list(proof_excluded),
        "overlap_variant_ids": list(OVERLAP_VARIANT_IDS),
        "expected_cell_count": 280,
        "observed_cell_count": len(ledger),
        "observation_kind_counts": kind_counts,
        "canonical_order": ["variant_id", "cache_mode", "case_id"],
    }
    return ledger, normalization


def _capability_diagnoses(
    frontend: Mapping[str, object], proof: Mapping[str, object]
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for source, report in (("frontend", frontend), ("proof", proof)):
        capabilities = _mapping(report["capabilities"], f"{source}.capabilities")
        for capability in sorted(capabilities):
            row = _mapping(
                capabilities[capability],
                f"{source}.capabilities.{capability}",
            )
            result.append(
                {
                    "source": source,
                    "capability": capability,
                    "status": row["status"],
                    "reason": row["reason"],
                    "blocks_complete_efficacy": row["status"] != "available",
                }
            )
    return result


def _variant_dispositions(
    ledger: Sequence[Mapping[str, object]],
    frontend: Mapping[str, object],
) -> list[dict[str, object]]:
    development_rows = [
        _mapping(item, "frontend.observation")
        for item in _array(frontend["observations"], "frontend.observations")
        if _mapping(item, "frontend.observation")["split"] == "development"
    ]
    result: list[dict[str, object]] = []
    for variant_id in NONBASELINE_CANDIDATE_IDS:
        rows = [row for row in ledger if row["variant_id"] == variant_id]
        development = [
            row for row in development_rows if row["variant_id"] == variant_id
        ]
        pilot_efficacy_count = sum(bool(row["efficacy_observed"]) for row in rows)
        development_efficacy_count = sum(
            _frontend_semantic(row) is not None for row in development
        )
        reasons: list[str] = []
        if pilot_efficacy_count == 0:
            reasons.append("no_pilot_efficacy_observed")
        if development_efficacy_count == 0:
            reasons.append("no_development_efficacy_observed")
        if any(row["evidence_status"] == "infrastructure_failure" for row in rows):
            reasons.append("infrastructure_failure_retained")
        if not reasons:
            # Selection needs a preregistered complete pilot/development metric
            # basis.  This module deliberately has no post-hoc rank/truncate
            # path for a set that exceeds the frozen maximum.
            reasons.append("complete_preregistered_selection_basis_unavailable")
        result.append(
            {
                "variant_id": variant_id,
                "configuration_sha256": VARIANT_REGISTRY[variant_id].digest,
                "pilot_cell_count": len(rows),
                "pilot_efficacy_observation_count": pilot_efficacy_count,
                "development_observation_count": len(development),
                "development_efficacy_observation_count": (
                    development_efficacy_count
                ),
                "proof_excluded_cell_count": sum(
                    row["proof_scope"] == "excluded_nonproof" for row in rows
                ),
                "infrastructure_failure_count": sum(
                    row["evidence_status"] == "infrastructure_failure"
                    for row in rows
                ),
                "kernel_verified_count": sum(
                    row["kernel_verified"] is True for row in rows
                ),
                "semantic_success_count": sum(
                    row["semantic_success"] is True for row in rows
                ),
                "efficacy_rates": {
                    "kernel_verified_rate": None,
                    "semantic_success_rate": None,
                    "paired_delta_vs_a0": None,
                },
                "selection_eligible": False,
                "disposition": "not_selected",
                "reasons": reasons,
            }
        )
    return result


def _deep_freeze(
    frontend: Mapping[str, object],
    proof: Mapping[str, object],
    baseline: Mapping[str, object],
    bindings: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    variant_configurations = [
        {
            "variant_id": variant_id,
            "configuration_sha256": VARIANT_REGISTRY[variant_id].digest,
            "configuration": VARIANT_REGISTRY[variant_id].to_dict(),
        }
        for variant_id in ALL_VARIANT_IDS
    ]
    policies = [
        {
            "variant_id": variant_id,
            "symai_policy": VARIANT_REGISTRY[variant_id].symai_policy.value,
            "hammer_policy": VARIANT_REGISTRY[variant_id].hammer_policy.value,
            "leanstral_policy": (
                VARIANT_REGISTRY[variant_id].leanstral_policy.value
            ),
            "proof_order": [
                stage.value
                for stage in VARIANT_REGISTRY[variant_id].proof_order
            ],
            "premise_ranking": (
                VARIANT_REGISTRY[variant_id].premise_ranking.value
            ),
        }
        for variant_id in ALL_VARIANT_IDS
    ]
    from benchmarks.logic_pipeline import adapters as adapter_contracts
    from benchmarks.logic_pipeline.capabilities import ResourcePolicy
    from benchmarks.logic_pipeline.contracts import CacheMode, CacheScope, Split

    adapter_path = Path(adapter_contracts.__file__).resolve()
    try:
        adapter_source_sha256 = _sha256_bytes(adapter_path.read_bytes())
    except OSError as exc:
        raise PilotGateError("cannot bind adapter prompt contracts") from exc
    leanstral_config = adapter_contracts.LeanstralAdapterConfig()
    prompt_contract_body = {
        "adapter_module": "benchmarks.logic_pipeline.adapters",
        "adapter_source_sha256": adapter_source_sha256,
        "symai": {
            "schema": adapter_contracts.SYMAI_PROMPT_SCHEMA,
            "builder": "benchmarks.logic_pipeline.adapters._symai_prompt",
            "task": "semantic_interpretation",
            "output_contract_keys": sorted(
                {
                    "candidate_ir",
                    "normalized_predicates",
                    "quantifiers",
                    "entities",
                    "ambiguity_flags",
                    "confidence",
                    "validation_errors",
                }
            ),
            "authority_claims_forbidden": True,
            "max_text_bytes": adapter_contracts.SYMAI_MAX_TEXT_BYTES,
            "max_raw_output_bytes": (
                adapter_contracts.SYMAI_MAX_RAW_OUTPUT_BYTES
            ),
            "max_candidate_bytes": (
                adapter_contracts.SYMAI_MAX_CANDIDATE_BYTES
            ),
            "max_retries": adapter_contracts.SYMAI_MAX_RETRIES,
        },
        "leanstral": {
            "draft_schema": adapter_contracts.LEANSTRAL_DRAFT_SCHEMA,
            "input_builder": (
                "benchmarks.logic_pipeline.adapters._leanstral_input"
            ),
            "draft_validator": (
                "benchmarks.logic_pipeline.adapters."
                "_validate_leanstral_draft"
            ),
            "one_fixed_obligation_per_request": True,
            "unverified_model_draft_only": True,
            "forbidden_constructs_fail_closed": True,
            "max_context_bytes": leanstral_config.max_context_bytes,
            "max_draft_bytes": leanstral_config.max_draft_bytes,
            "max_repair_attempts": leanstral_config.max_repair_attempts,
            "model_resource_class": leanstral_config.model_resource_class,
            "kernel_resource_class": leanstral_config.kernel_resource_class,
        },
    }
    model_identity_body = {
        "status": "incomplete",
        "baseline_requested_and_effective": _mapping(
            baseline["configuration"], "baseline.configuration"
        ),
        "frontend_capabilities": frontend["capabilities"],
        "proof_capabilities": proof["capabilities"],
    }
    total_model_calls = sum(
        int(_mapping(item, "frontend.observation")["model_calls"])
        for item in _array(frontend["observations"], "frontend.observations")
    ) + sum(
        int(_mapping(item, "proof.observation")["model_calls"])
        for item in _array(proof["observations"], "proof.observations")
    )
    if total_model_calls != 0:
        raise PilotGateError(
            "model calls are present but prompt identities are not exposed "
            "by the source-report contract"
        )
    prompt_body = {
        "status": "unmaterialized_no_model_execution",
        "materialized_prompt_sha256s": [],
        "observed_model_call_count": 0,
        "contracts": prompt_contract_body,
        "contracts_sha256": _sha256_json(prompt_contract_body),
        "reason": (
            "capability preflight performed no model execution; no prompt "
            "content or efficacy is inferred"
        ),
    }
    cache_namespaces = [
        CacheScope(
            PILOT_GATE_RUN_ID,
            DEFAULT_PROTOCOL_SHA256,
            variant_id,
            split,
            mode,
        ).namespace
        for split in (Split.PILOT, Split.DEVELOPMENT)
        for variant_id in ALL_VARIANT_IDS
        for mode in (CacheMode.COLD, CacheMode.WARM)
    ]
    baseline_contracts = [
        _mapping(item, "baseline.run_contracts[]")
        for item in _array(baseline["run_contracts"], "baseline.run_contracts")
    ]
    cache_policy_body = {
        "schema": "ipfs-datasets.logic-pipeline-benchmark.cache-policy.v1",
        "namespace_dimensions": [
            "run_id",
            "protocol_sha256",
            "variant_id",
            "split",
            "cache_mode",
        ],
        "cold_warm_results_separate": True,
        "cross_variant_reuse_forbidden": True,
        "selection_splits": ["pilot", "development"],
        "reserved_unopened_namespaces": cache_namespaces,
        "frozen_a0_namespaces": [
            contract["cache_namespace"] for contract in baseline_contracts
        ],
        "execution_claimed_for_reserved_namespaces": False,
    }
    resource_policy_values = ResourcePolicy().to_dict()
    resource_policy_body = {
        "values": resource_policy_values,
        "resource_lanes": [
            "cpu",
            "model",
            "solver",
            "kernel",
            "validation",
        ],
        "model_and_kernel_lanes_distinct": True,
        "shared_model_identity_required": True,
        "execution_claimed": False,
    }
    thresholds = DEFAULT_PROTOCOL.thresholds.to_dict()
    source_semantic_bindings = [
        {
            "kind": item["kind"],
            "path": item["path"],
            "semantic_sha256": item["semantic_sha256"],
        }
        for item in bindings
    ]
    return {
        "schema": PILOT_FREEZE_SCHEMA,
        "frozen": True,
        "tuning_permitted": False,
        "protocol": {
            "sha256": DEFAULT_PROTOCOL_SHA256,
            "snapshot": DEFAULT_PROTOCOL.to_dict(),
        },
        "registry": {
            "sha256": VARIANT_REGISTRY_SHA256,
            "variant_configurations": variant_configurations,
        },
        "prompts": {
            "frozen": True,
            **prompt_body,
            "sha256": _sha256_json(prompt_body),
        },
        "cache_policy": {
            "frozen": True,
            **cache_policy_body,
            "sha256": _sha256_json(cache_policy_body),
        },
        "resource_policy": {
            "frozen": True,
            **resource_policy_body,
            "sha256": _sha256_json(resource_policy_body),
        },
        "policies": {
            "frozen": True,
            "values": policies,
            "sha256": _sha256_json(policies),
        },
        "model_identities": {
            "frozen": True,
            **model_identity_body,
            "sha256": _sha256_json(model_identity_body),
        },
        "thresholds": {
            "frozen": True,
            "values": thresholds,
            "sha256": _sha256_json(thresholds),
        },
        "source_semantic_bindings": source_semantic_bindings,
        "selection_basis": {
            "allowed_splits": ["pilot", "development"],
            "holdout_outcomes_permitted": False,
            "post_freeze_reranking_permitted": False,
            "arbitrary_ranking_or_truncation_permitted": False,
        },
        "freeze_sha256": _sha256_json(
            {
                "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
                "registry_sha256": VARIANT_REGISTRY_SHA256,
                "variant_configuration_sha256s": [
                    item["configuration_sha256"]
                    for item in variant_configurations
                ],
                "prompt_sha256": _sha256_json(prompt_body),
                "cache_policy_sha256": _sha256_json(cache_policy_body),
                "resource_policy_sha256": _sha256_json(
                    resource_policy_body
                ),
                "policy_sha256": _sha256_json(policies),
                "model_identity_sha256": _sha256_json(model_identity_body),
                "threshold_sha256": _sha256_json(thresholds),
                "sources": source_semantic_bindings,
            }
        ),
    }


def _derive_report(repository_root: Path) -> dict[str, object]:
    frontend, proof, baseline, bindings = _load_sources(repository_root)
    ledger, normalization = _normalize_ledger(frontend, proof, baseline)
    capabilities = _capability_diagnoses(frontend, proof)
    dispositions = _variant_dispositions(ledger, frontend)

    control_rows = [row for row in ledger if row["invalid_control"] is True]
    observed_control_rows = [
        row
        for row in control_rows
        if row["invalid_control_kernel_false_positive"] is not None
    ]
    false_positive_count = sum(
        row["invalid_control_kernel_false_positive"] is True
        for row in observed_control_rows
    )
    if false_positive_count > DEFAULT_PROTOCOL.thresholds.invalid_control_verified_max:
        raise PilotGateError("a kernel-verified invalid control is a fatal incident")
    efficacy_observation_count = sum(
        bool(row["efficacy_observed"]) for row in ledger
    )
    infrastructure_failure_count = sum(
        row["evidence_status"] == "infrastructure_failure" for row in ledger
    )
    safety = {
        "invalid_control_case_ids": sorted(
            {str(row["case_id"]) for row in control_rows}
        ),
        "invalid_control_cell_count": len(control_rows),
        "observed_invalid_control_cell_count": len(observed_control_rows),
        "kernel_verified_invalid_control_false_positive_count": (
            false_positive_count
        ),
        "kernel_verified_invalid_control_false_positive_rate": (
            false_positive_count / len(observed_control_rows)
            if observed_control_rows
            else None
        ),
        "threshold": DEFAULT_PROTOCOL.thresholds.invalid_control_verified_max,
        "fatal_safety_incident": false_positive_count > 0,
        "efficacy_observation_count": efficacy_observation_count,
        "infrastructure_failure_count": infrastructure_failure_count,
        "absence_is_not_negative_efficacy": True,
    }
    shortlist = {
        "status": "incomplete",
        "frozen": True,
        "freeze_kind": "empty_due_to_unavailable_evidence",
        "candidate_max": DEFAULT_PROTOCOL.thresholds.shortlist_candidate_max,
        "selected_variant_ids": [],
        "selected_count": 0,
        "nonbaseline_only": True,
        "diagnostic_arms_excluded": ["S1"],
        "baseline_arms_excluded": ["A0"],
        "selection_splits": ["pilot", "development"],
        "ranking_applied": False,
        "truncation_applied": False,
        "reason": (
            "capability-preflight evidence contains no observed efficacy; "
            "no arm may be ranked or selected"
        ),
    }
    holdout = {
        "status": "unopened",
        "authorized": False,
        "outcomes_inspected": False,
        "access_log_ids": [],
        "selection_used_holdout": False,
        "tuning_after_access": False,
        "reason": "an incomplete empty shortlist cannot authorize holdout access",
    }
    deep_freeze = _deep_freeze(frontend, proof, baseline, bindings)
    report: dict[str, object] = {
        "schema": PILOT_GATE_SCHEMA,
        "evidence": HSSLEV0801D68(),
        "benchmark_id": BENCHMARK_ID,
        "run_id": PILOT_GATE_RUN_ID,
        "source_bindings": bindings,
        "normalization": normalization,
        "capability_diagnoses": capabilities,
        "outcome_ledger": ledger,
        "safety": safety,
        "variant_dispositions": dispositions,
        "shortlist": shortlist,
        "holdout": holdout,
        "deep_freeze": deep_freeze,
        "decision": {
            "status": "incomplete",
            "structurally_valid": True,
            "pilot_protocol_status": "capability_preflight_complete",
            "efficacy_status": "unavailable",
            "shortlist_status": "frozen_empty",
            "holdout_authorized": False,
            "production_promotion_authorized": False,
            "reason": (
                "pilot and development source matrices are structurally "
                "validated, but required efficacy was unavailable"
            ),
        },
        "artifact_sha256": "",
    }
    report["artifact_sha256"] = _artifact_digest(report)
    return report


def build_pilot_gate_report(
    *, repository_root: str | Path = REPOSITORY_ROOT
) -> dict[str, object]:
    """Build the deterministic HSSL-G080 gate from allowlisted source evidence."""

    root = _resolve_repository_root(repository_root)
    return _derive_report(root)


def build_pilot_shortlist_report(
    *, repository_root: str | Path = REPOSITORY_ROOT
) -> dict[str, object]:
    """Compatibility name for :func:`build_pilot_gate_report`."""

    return build_pilot_gate_report(repository_root=repository_root)


def create_pilot_shortlist_report(
    *, repository_root: str | Path = REPOSITORY_ROOT
) -> dict[str, object]:
    """Create the current deterministic gate from its frozen sources."""

    return build_pilot_gate_report(repository_root=repository_root)


def validate_pilot_gate_report(
    value: object, *, repository_root: str | Path = REPOSITORY_ROOT
) -> dict[str, object]:
    """Recompute the complete gate and reject stale or invented evidence."""

    data = _mapping(value, "pilot gate report")
    actual_fields = set(data)
    if actual_fields != _REPORT_FIELDS:
        raise PilotGateError(
            "pilot gate report keys changed; "
            f"missing={sorted(_REPORT_FIELDS - actual_fields)}, "
            f"unknown={sorted(actual_fields - _REPORT_FIELDS)}"
        )
    if data["schema"] != PILOT_GATE_SCHEMA:
        raise PilotGateError("unsupported pilot gate schema")
    if data["evidence"] != HSSLEV0801D68():
        raise PilotGateError("pilot gate evidence marker changed")
    if data["benchmark_id"] != BENCHMARK_ID:
        raise PilotGateError("benchmark identity changed")
    if data["run_id"] != PILOT_GATE_RUN_ID:
        raise PilotGateError("pilot gate run identity changed")
    if data["artifact_sha256"] != _artifact_digest(data):
        raise PilotGateError("pilot gate artifact digest changed")
    root = _resolve_repository_root(repository_root)
    expected = _derive_report(root)
    if dict(data) != expected:
        raise PilotGateError(
            "pilot gate differs from recomputed allowlisted source evidence"
        )
    return dict(data)


def validate_pilot_shortlist_report(
    value: object, *, repository_root: str | Path = REPOSITORY_ROOT
) -> dict[str, object]:
    """Compatibility name for :func:`validate_pilot_gate_report`."""

    return validate_pilot_gate_report(value, repository_root=repository_root)


def canonical_pilot_shortlist_json(
    report: object, *, repository_root: str | Path = REPOSITORY_ROOT
) -> str:
    """Return canonical JSON only after full source-backed revalidation."""

    value = validate_pilot_gate_report(
        report, repository_root=repository_root
    )
    return canonical_json(value)


def _result_path(path: str | Path, repository_root: Path) -> Path:
    result = Path(path)
    if not result.is_absolute():
        result = repository_root / result
    return result


def load_pilot_gate_report(
    path: str | Path = DEFAULT_PILOT_GATE_PATH,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
) -> dict[str, object]:
    """Load strict canonical newline JSON and revalidate every source binding."""

    root = _resolve_repository_root(repository_root)
    report_path = _result_path(path, root)
    try:
        file_stat = report_path.lstat()
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise PilotGateError("pilot gate path must be a regular non-symlink file")
        if file_stat.st_size <= 0 or file_stat.st_size > _MAX_REPORT_BYTES:
            raise PilotGateError("pilot gate file size is outside the safe bound")
        raw = report_path.read_bytes()
        text = raw.decode("utf-8")
    except PilotGateError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise PilotGateError(f"cannot read pilot gate: {report_path}") from exc
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise PilotGateError("pilot gate is not canonical newline JSON")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, PilotGateError) as exc:
        raise PilotGateError("pilot gate is not strict JSON") from exc
    try:
        expected_bytes = (canonical_json(value) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PilotGateError("pilot gate is not canonically serializable") from exc
    if raw != expected_bytes:
        raise PilotGateError("pilot gate is not canonical JSON")
    return validate_pilot_gate_report(value, repository_root=root)


def load_pilot_shortlist_report(
    path: str | Path = DEFAULT_PILOT_GATE_PATH,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
) -> dict[str, object]:
    """Compatibility name for :func:`load_pilot_gate_report`."""

    return load_pilot_gate_report(path, repository_root=repository_root)


def write_pilot_gate_report(
    report: object | None = None,
    path: str | Path = DEFAULT_PILOT_GATE_PATH,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    overwrite: bool = False,
) -> Path:
    """Write a canonical report atomically, refusing replacement by default."""

    root = _resolve_repository_root(repository_root)
    value = (
        build_pilot_gate_report(repository_root=root)
        if report is None
        else validate_pilot_gate_report(report, repository_root=root)
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
            raise PilotGateError(
                f"refusing to overwrite existing pilot gate: {destination}"
            ) from exc
        except OSError as exc:
            raise PilotGateError(
                f"cannot write pilot gate: {destination}"
            ) from exc
        return destination

    if destination.is_symlink():
        raise PilotGateError("refusing to overwrite a symlink")
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
        raise PilotGateError(f"cannot write pilot gate: {destination}") from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass
    return destination


def write_pilot_shortlist_report(
    report: object | None = None,
    path: str | Path = DEFAULT_PILOT_GATE_PATH,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
    overwrite: bool = False,
) -> Path:
    """Compatibility name for :func:`write_pilot_gate_report`."""

    return write_pilot_gate_report(
        report,
        path,
        repository_root=repository_root,
        overwrite=overwrite,
    )


def pilot_gate_summary(
    report: object, *, repository_root: str | Path = REPOSITORY_ROOT
) -> dict[str, object]:
    """Return the stable CLI receipt for a fully revalidated gate."""

    value = validate_pilot_gate_report(
        report, repository_root=repository_root
    )
    decision = _mapping(value["decision"], "decision")
    normalization = _mapping(value["normalization"], "normalization")
    shortlist = _mapping(value["shortlist"], "shortlist")
    holdout = _mapping(value["holdout"], "holdout")
    safety = _mapping(value["safety"], "safety")
    return {
        "section": "pilot-shortlist",
        "status": decision["status"],
        "structurally_valid": decision["structurally_valid"],
        "artifact_sha256": value["artifact_sha256"],
        "outcome_cell_count": normalization["observed_cell_count"],
        "pilot_case_count": len(
            _array(normalization["pilot_case_ids"], "pilot_case_ids")
        ),
        "variant_count": len(
            _array(normalization["variant_ids"], "variant_ids")
        ),
        "efficacy_observation_count": safety["efficacy_observation_count"],
        "kernel_verified_invalid_control_false_positive_count": safety[
            "kernel_verified_invalid_control_false_positive_count"
        ],
        "kernel_verified_invalid_control_false_positive_rate": safety[
            "kernel_verified_invalid_control_false_positive_rate"
        ],
        "selected_variant_ids": shortlist["selected_variant_ids"],
        "shortlist_frozen": shortlist["frozen"],
        "holdout_authorized": holdout["authorized"],
        "missingness_retained": True,
    }


def pilot_shortlist_summary(
    report: object, *, repository_root: str | Path = REPOSITORY_ROOT
) -> dict[str, object]:
    """Compatibility name for :func:`pilot_gate_summary`."""

    return pilot_gate_summary(report, repository_root=repository_root)


__all__ = [
    "ALLOWED_SOURCE_PATHS",
    "BASELINE_SOURCE_PATH",
    "CACHE_MODES",
    "DEFAULT_PILOT_GATE_PATH",
    "DEFAULT_PILOT_SHORTLIST_PATH",
    "FRONTEND_SOURCE_PATH",
    "HSSLEV0801D68",
    "NONBASELINE_CANDIDATE_IDS",
    "OVERLAP_VARIANT_IDS",
    "PILOT_CASE_IDS",
    "PILOT_FREEZE_SCHEMA",
    "PILOT_GATE_RUN_ID",
    "PILOT_GATE_SCHEMA",
    "PILOT_OUTCOME_CELL_SCHEMA",
    "PILOT_SHORTLIST_SCHEMA",
    "PROOF_SOURCE_PATH",
    "PilotGateError",
    "build_pilot_gate_report",
    "build_pilot_shortlist_report",
    "canonical_pilot_shortlist_json",
    "create_pilot_shortlist_report",
    "load_pilot_gate_report",
    "load_pilot_shortlist_report",
    "pilot_gate_summary",
    "pilot_shortlist_summary",
    "validate_pilot_gate_report",
    "validate_pilot_shortlist_report",
    "write_pilot_gate_report",
    "write_pilot_shortlist_report",
]
