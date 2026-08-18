"""R1 deterministic compiler/decompiler baseline (PGIR-023).

Interface: ``IRDeterministicR1Baseline@1``

The runner binds the sealed PGIR-011 corpus identity and PGIR-012 split
identity, measures the PGIR-021 compiler and PGIR-022 decompiler separately,
and writes compact content-addressed evaluation shards.  Hidden tests, the
blind holdout fixture, and learned inference are rejected.  Unmaterialized
source partitions and missing proof obligations are reported with explicit
unsupported/unknown/not-measured statuses rather than invented zeros.

Per-case compiler/decompiler envelopes are not re-emitted.  Artifacts keep
identities, metric cells, compact case summaries, paired trace CIDs, and an
independent deterministic replay receipt.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.semantic_roundtrip.contracts import CanonicalRule, CanonicalRuleIR, ContractError
from benchmarks.semantic_roundtrip.e1_metrics import (
    E1_METRIC_IDS,
    E1_SURFACES,
    IR_DETERMINISTIC_E1_METRICS_INTERFACE,
    IR_DETERMINISTIC_E1_METRICS_SCHEMA,
    METRIC_STATUS_NOT_APPLICABLE,
    METRIC_STATUS_NOT_MEASURED,
    METRIC_STATUS_UNSUPPORTED,
    MetricObservation,
    compare_structural_views,
    e1_metric_catalog,
    expected_grounded_fields,
    measured_mean,
    measured_rate,
    require_complete_e1_surface,
    semantic_ir_cid,
    unmeasured,
)
from benchmarks.semantic_roundtrip.matrix import load_matrix_cases
from ipfs_datasets_py.logic.legal_ir.canonical_compiler import (
    TYPED_DEONTIC_COMPILER_CONFIG_CID,
    TypedDeonticCanonicalCompiler,
    compiler_configuration,
)
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_PARITY_POLICY_CID,
    CanonicalAtomVocabulary,
    CanonicalRoundTripIR,
    DecompilerRequest,
    OperationStatus,
    SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
    SOURCE_WITHHELD_RENDERING_SPEC_CID,
)
from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import (
    SELECTED_REALIZER_INTERFACE,
    SourceWithheldCanonicalDecompiler,
)
from ipfs_datasets_py.logic.legal_ir.canonical_roundtrip import (
    CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID,
    measured_parity_compiler_request,
)


IR_DETERMINISTIC_R1_BASELINE_INTERFACE: Final = "IRDeterministicR1Baseline@1"
IR_DETERMINISTIC_R1_BASELINE_SCHEMA: Final = (
    "ipfs-datasets.ir-learning.evaluations.deterministic.r1-baseline.v1"
)
IR_DETERMINISTIC_RECIPE_INTERFACE: Final = "IRDeterministicBaselineRecipe@1"
IR_DETERMINISTIC_RECIPE_SCHEMA: Final = (
    "ipfs-datasets.ir-learning.evaluations.deterministic.recipe.v1"
)
TASK_ID: Final = "PGIR-023"
EXPERIMENT_ID: Final = "R1"
FAMILY_ID: Final = "deontic"

DATASETS_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR: Final = DATASETS_ROOT / "data/ir_learning/evaluations/deterministic"
CORPUS_ROOT_PATH: Final = DATASETS_ROOT / "data/ir_learning/corpora/corpus_root.json"
SPLIT_ROOT_PATH: Final = DATASETS_ROOT / "data/ir_learning/splits/split_root.json"
SPLIT_MANIFEST_PATH: Final = DATASETS_ROOT / "data/ir_learning/splits/ir_split_manifest.json"
PILOT_CASES_PATH: Final = DATASETS_ROOT / "tests/fixtures/semantic_roundtrip/pilot_cases.json"
REPAIR_DEV_CASES_PATH: Final = (
    DATASETS_ROOT / "tests/fixtures/semantic_roundtrip/repair_dev_cases.json"
)
HOLDOUT_CASES_PATH: Final = DATASETS_ROOT / "tests/fixtures/semantic_roundtrip/holdout_cases.json"

POPULATION_PILOT: Final = "pilot"
POPULATION_REPAIR_DEVELOPMENT: Final = "repair_development"
MEASURED_POPULATIONS: Final = (POPULATION_PILOT, POPULATION_REPAIR_DEVELOPMENT)
EXCLUDED_POPULATIONS: Final = (
    "blind_holdout",
    "holdout_cases",
    "hidden_test",
    "canary",
    "statute_family",
    "jurisdiction",
)

IMPLEMENTATION_PATHS: Final[Mapping[str, str]] = {
    "compiler": "ipfs_datasets_py/logic/legal_ir/canonical_compiler.py",
    "decompiler": "ipfs_datasets_py/logic/legal_ir/canonical_decompiler.py",
    "roundtrip": "ipfs_datasets_py/logic/legal_ir/canonical_roundtrip.py",
    "contracts": "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py",
}

class DeterministicBaselineError(ContractError):
    """Fail-closed error for the R1 deterministic baseline."""


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(encoded + "\n", encoding="utf-8")


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    return value


def _vocab(case: object) -> CanonicalAtomVocabulary:
    allowed = case.allowed_atom_vocabulary
    return CanonicalAtomVocabulary(
        actors=list(allowed.actors),
        actions=list(allowed.actions),
        objects=list(allowed.objects),
        qualifiers=list(allowed.qualifiers),
    )


def _to_benchmark_ir(canonical_ir: CanonicalRoundTripIR) -> CanonicalRuleIR:
    return CanonicalRuleIR.from_dict(canonical_ir.to_dict())


def _identity_cid(payload: Mapping[str, object], *drop: str) -> str:
    identity = {key: value for key, value in payload.items() if key not in drop}
    return cid_for_dag_json(_plain(identity))


def _implementation_raw_cids() -> dict[str, str]:
    cids: dict[str, str] = {}
    for name, relative in IMPLEMENTATION_PATHS.items():
        path = DATASETS_ROOT / relative
        cids[name] = cid_for_bytes(path.read_bytes())
    return cids


def _fixture_raw_cid(path: Path) -> str:
    return cid_for_bytes(path.read_bytes())


def load_bound_identities() -> dict[str, object]:
    """Bind corpus, split, compiler, and decompiler identities without opening hidden labels."""

    if HOLDOUT_CASES_PATH.exists():
        # Presence is recorded; contents are never loaded into the measured set.
        holdout_present = True
    else:
        holdout_present = False

    corpus_root = _load_json(CORPUS_ROOT_PATH)
    split_root = _load_json(SPLIT_ROOT_PATH)
    if not isinstance(corpus_root, Mapping) or not isinstance(split_root, Mapping):
        raise DeterministicBaselineError("corpus/split roots must be objects")

    split_manifest_stat = SPLIT_MANIFEST_PATH.stat()
    identities = {
        "interface": IR_DETERMINISTIC_RECIPE_INTERFACE,
        "task_id": TASK_ID,
        "experiment_id": EXPERIMENT_ID,
        "corpus": {
            "path": str(CORPUS_ROOT_PATH.relative_to(DATASETS_ROOT)),
            "kind": corpus_root.get("kind"),
            "schema_binding": "RESULT(PGIR-011)",
            "manifest_id": corpus_root.get("manifest_id"),
            "manifest_cid": corpus_root.get("manifest_cid"),
            "lineage_graph_cid": corpus_root.get("lineage_graph_cid"),
            "pinset_id": corpus_root.get("pinset_id"),
            "source_count": corpus_root.get("source_count"),
            "derived_count": corpus_root.get("derived_count"),
            "training_admitted_rows": corpus_root.get("training_admitted_rows"),
            "materialized": corpus_root.get("materialized"),
            "root_sha256": _file_sha256(CORPUS_ROOT_PATH),
        },
        "split": {
            "path": str(SPLIT_ROOT_PATH.relative_to(DATASETS_ROOT)),
            "schema_binding": "RESULT(PGIR-012)",
            "kind": split_root.get("kind"),
            "schema": split_root.get("schema"),
            "split_manifest_digest": split_root.get("split_manifest_digest"),
            "split_manifest_sha256": split_root.get("split_manifest_sha256"),
            "hidden_test_commitment": split_root.get("hidden_test_commitment"),
            "leakage_passed": split_root.get("leakage_passed"),
            "holdouts": _plain(split_root.get("holdouts") or {}),
            "manifest_path": str(SPLIT_MANIFEST_PATH.relative_to(DATASETS_ROOT)),
            "manifest_size_bytes": split_manifest_stat.st_size,
            "hidden_labels_opened": False,
            "holdout_fixture_present": holdout_present,
            "holdout_fixture_loaded": False,
            "root_sha256": _file_sha256(SPLIT_ROOT_PATH),
        },
        "compiler": {
            "schema_binding": "RESULT(PGIR-021)",
            "configuration_cid": TYPED_DEONTIC_COMPILER_CONFIG_CID,
            "configuration": compiler_configuration(),
            "learned_stages": [],
        },
        "decompiler": {
            "schema_binding": "RESULT(PGIR-022)",
            "configuration_cid": SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
            "rendering_spec_cid": SOURCE_WITHHELD_RENDERING_SPEC_CID,
            "interface": SELECTED_REALIZER_INTERFACE,
            "source_withheld": True,
            "learned_stages": [],
        },
        "roundtrip": {
            "configuration_cid": CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID,
            "policy_cid": CANONICAL_PARITY_POLICY_CID,
        },
        "implementation_raw_cids": _implementation_raw_cids(),
        "model_checkpoint_identity": "none/deterministic",
    }
    identities["identities_cid"] = _identity_cid(identities, "identities_cid")
    return identities


def _file_sha256(path: Path) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_measured_fixture_cases() -> tuple[dict[str, object], ...]:
    """Load only frozen non-hidden fixture populations."""

    records: list[dict[str, object]] = []
    for population, path in (
        (POPULATION_PILOT, PILOT_CASES_PATH),
        (POPULATION_REPAIR_DEVELOPMENT, REPAIR_DEV_CASES_PATH),
    ):
        raw_cases = _load_json(path)
        if not isinstance(raw_cases, list):
            raise DeterministicBaselineError(f"{path} must be a JSON array")
        matrix_cases = {case.case_id: case for case in load_matrix_cases(path)}
        if set(matrix_cases) != {item["id"] for item in raw_cases}:
            raise DeterministicBaselineError(f"{path.name} matrix/raw case ids drifted")
        for raw in raw_cases:
            case_id = str(raw["id"])
            complexity = raw.get("complexity_tier")
            case_family = raw.get("case_family") or "pilot_control"
            records.append(
                {
                    "case_id": case_id,
                    "population": population,
                    "family": FAMILY_ID,
                    "case_family": str(case_family),
                    "domain": f"complexity_tier_{complexity}",
                    "complexity_tier": complexity,
                    "source_ref": raw.get("source_ref"),
                    "fixture_path": str(path.relative_to(DATASETS_ROOT)),
                    "fixture_cid": _fixture_raw_cid(path),
                    "matrix_case": matrix_cases[case_id],
                }
            )
    return tuple(records)


def _trace_cids(result: object) -> list[str]:
    traces = getattr(result, "component_trace", ()) or ()
    cids: list[str] = []
    for trace in traces:
        payload = trace.to_dict() if hasattr(trace, "to_dict") else dict(trace)
        cids.append(cid_for_dag_json(payload))
    return cids


def _valid_source_span(
    entry: object,
    *,
    source_text: str,
    source_cid: str,
    known_rule_cids: set[str],
) -> bool:
    if entry.source_cid != source_cid:
        return False
    if entry.rule_cid not in known_rule_cids:
        return False
    if entry.start < 0 or entry.end <= entry.start or entry.end > len(source_text):
        return False
    return True


def _source_span_counts(
    compiler_result: object,
    *,
    gold_ir: CanonicalRuleIR,
    source_text: str,
    source_cid: str,
) -> tuple[int, int, dict[str, object]]:
    gold_expected = sum(len(expected_grounded_fields(rule)) for rule in gold_ir.rules)
    if compiler_result.status is not OperationStatus.SUCCESS or compiler_result.canonical_ir is None:
        return 0, gold_expected, {"eligible": False, "reason": "compiler_did_not_produce_ir"}
    known = {rule.rule_cid for rule in compiler_result.canonical_ir.rules}
    grounded_keys = {
        (entry.rule_cid, entry.field_path.rsplit("/", 1)[-1])
        for entry in compiler_result.source_map
        if _valid_source_span(
            entry,
            source_text=source_text,
            source_cid=source_cid,
            known_rule_cids=known,
        )
    }
    expected = 0
    grounded = 0
    for rule in compiler_result.canonical_ir.rules:
        fields = expected_grounded_fields(CanonicalRule.from_dict(rule.to_dict()))
        for field in fields:
            expected += 1
            if (rule.rule_cid, field) in grounded_keys:
                grounded += 1
    detail = {
        "eligible": True,
        "source_map_entries": len(compiler_result.source_map),
        "valid_grounded_fields": grounded,
        "expected_fields": expected,
        "gold_expected_fields": gold_expected,
        "source_map_receipt_cid": (
            None
            if compiler_result.source_map_receipt() is None
            else compiler_result.source_map_receipt()["receipt_cid"]
        ),
    }
    return grounded, expected, detail


def _measure_case(
    record: Mapping[str, object],
    *,
    compiler: TypedDeonticCanonicalCompiler,
    decompiler: SourceWithheldCanonicalDecompiler,
) -> dict[str, object]:
    case = record["matrix_case"]
    vocab = _vocab(case)
    request = measured_parity_compiler_request(
        case.source_text,
        request_id=f"pgir023:{record['population']}:{case.case_id}",
        atom_vocabulary=vocab,
    )
    compile_started = time.perf_counter()
    l1_result = compiler.compile(request)
    compile_elapsed = time.perf_counter() - compile_started
    compiler_success = l1_result.status is OperationStatus.SUCCESS and l1_result.canonical_ir is not None

    l1_ir = _to_benchmark_ir(l1_result.canonical_ir) if compiler_success else None
    compiler_compare = (
        compare_structural_views(case.gold_ir, l1_ir) if l1_ir is not None else None
    )
    span_num, span_den, span_detail = _source_span_counts(
        l1_result,
        gold_ir=case.gold_ir,
        source_text=case.source_text,
        source_cid=request.source_cid,
    )

    decompile_elapsed: float | None = None
    t1_result = None
    l2_result = None
    l2_ir = None
    decompiler_compare = None
    decompiler_success = False
    l2_success = False
    if compiler_success:
        decompile_request = DecompilerRequest(
            canonical_ir=l1_result.canonical_ir,
            request_id=f"pgir023:decompile:{record['population']}:{case.case_id}",
        )
        decompile_started = time.perf_counter()
        t1_result = decompiler.decompile(decompile_request)
        decompile_elapsed = time.perf_counter() - decompile_started
        decompiler_success = (
            t1_result.status is OperationStatus.SUCCESS
            and isinstance(t1_result.text, str)
            and bool(t1_result.text.strip())
        )
        if decompiler_success:
            l2_request = measured_parity_compiler_request(
                t1_result.text,
                request_id=f"pgir023:recompile:{record['population']}:{case.case_id}",
                atom_vocabulary=vocab,
            )
            l2_result = compiler.compile(l2_request)
            l2_success = (
                l2_result.status is OperationStatus.SUCCESS and l2_result.canonical_ir is not None
            )
            if l2_success:
                l2_ir = _to_benchmark_ir(l2_result.canonical_ir)
                decompiler_compare = compare_structural_views(l1_ir, l2_ir)

    replay = _independent_replay(
        request=request,
        l1_result=l1_result,
        t1_result=t1_result,
        decompiler_request_id=(
            None if t1_result is None else f"pgir023:decompile:{record['population']}:{case.case_id}"
        ),
        compiler=compiler,
        decompiler=decompiler,
        compiler_success=compiler_success,
        decompiler_success=decompiler_success,
    )

    return {
        "case_id": case.case_id,
        "case_cid": case.case_cid,
        "population": record["population"],
        "family": record["family"],
        "case_family": record["case_family"],
        "domain": record["domain"],
        "complexity_tier": record["complexity_tier"],
        "source_ref": record["source_ref"],
        "source_cid": request.source_cid,
        "gold_ir_cid": semantic_ir_cid(case.gold_ir),
        "gold_rule_count": len(case.gold_ir.rules),
        "compiler": {
            "status": l1_result.status.value,
            "request_cid": l1_result.request_cid,
            "result_cid": l1_result.result_cid,
            "ir_cid": None if compiler_compare is None else compiler_compare["candidate_cid"],
            "trace_cids": _trace_cids(l1_result),
            "unsupported_count": len(l1_result.unsupported_semantics),
            "unsupported_codes": sorted({item.code for item in l1_result.unsupported_semantics}),
            "error_code": None if l1_result.error is None else l1_result.error.code.value,
            "latency_seconds": compile_elapsed,
            "compare": compiler_compare,
            "source_span": span_detail,
            "source_span_numerator": span_num,
            "source_span_denominator": span_den,
        },
        "decompiler": {
            "status": None if t1_result is None else t1_result.status.value,
            "request_cid": None if t1_result is None else t1_result.request_cid,
            "result_cid": None if t1_result is None else t1_result.result_cid,
            "text_cid": None if t1_result is None else t1_result.text_cid,
            "trace_cids": [] if t1_result is None else _trace_cids(t1_result),
            "recompile_status": None if l2_result is None else l2_result.status.value,
            "recompile_result_cid": None if l2_result is None else l2_result.result_cid,
            "l2_ir_cid": None if decompiler_compare is None else decompiler_compare["candidate_cid"],
            "error_code": (
                None
                if t1_result is None or t1_result.error is None
                else t1_result.error.code.value
            ),
            "latency_seconds": decompile_elapsed,
            "compare": decompiler_compare,
            "success": decompiler_success,
            "type_accepted": l2_success,
        },
        "replay": replay,
    }


def _independent_replay(
    *,
    request: object,
    l1_result: object,
    t1_result: object | None,
    decompiler_request_id: str | None,
    compiler: TypedDeonticCanonicalCompiler,
    decompiler: SourceWithheldCanonicalDecompiler,
    compiler_success: bool,
    decompiler_success: bool,
) -> dict[str, object]:
    replayed_l1 = compiler.compile(request)
    compiler_matched = replayed_l1.result_cid == l1_result.result_cid
    decompiler_matched: bool | None = None
    replayed_t1_cid = None
    if (
        compiler_success
        and decompiler_success
        and t1_result is not None
        and decompiler_request_id is not None
    ):
        replayed_t1 = decompiler.decompile(
            DecompilerRequest(
                canonical_ir=l1_result.canonical_ir,
                request_id=decompiler_request_id,
            )
        )
        replayed_t1_cid = replayed_t1.result_cid
        decompiler_matched = replayed_t1.result_cid == t1_result.result_cid
    return {
        "kind": "independent_deterministic_replay",
        "compiler_matched": compiler_matched,
        "compiler_replay_result_cid": replayed_l1.result_cid,
        "decompiler_matched": decompiler_matched,
        "decompiler_replay_result_cid": replayed_t1_cid,
        "formal_proof_replayed": False,
        "formal_proof_reason": (
            "frozen fixtures carry no independently checkable proof obligations"
        ),
    }


def _bool_rate(
    metric_id: str,
    surface: str,
    flags: Sequence[bool],
    *,
    unit: str = "cases",
    detail: Mapping[str, object] | None = None,
) -> MetricObservation:
    if not flags:
        return unmeasured(
            metric_id,
            surface,
            METRIC_STATUS_NOT_MEASURED,
            "empty_eligible_set",
            unit=unit,
            detail=detail,
        )
    return measured_rate(
        metric_id,
        surface,
        numerator=sum(1 for item in flags if item),
        denominator=len(flags),
        unit=unit,
        detail=detail,
    )


def _aggregate_compiler(cases: Sequence[Mapping[str, object]]) -> tuple[MetricObservation, ...]:
    attempted = list(cases)
    parser_flags = [item["compiler"]["status"] == "success" for item in attempted]
    type_flags = [
        item["compiler"]["status"] == "success" and item["compiler"]["compare"] is not None
        for item in attempted
    ]
    comparable = [item for item in attempted if item["compiler"]["compare"] is not None]
    exact_flags = [bool(item["compiler"]["compare"]["exact"]) for item in comparable]
    canonical_flags = [bool(item["compiler"]["compare"]["canonical"]) for item in comparable]
    ast_flags = [bool(item["compiler"]["compare"]["ast"]) for item in comparable]
    graph_flags = [bool(item["compiler"]["compare"]["graph"]) for item in comparable]
    semantic_values = [
        float(item["compiler"]["compare"]["semantic_score"]) for item in comparable
    ]
    span_num = sum(int(item["compiler"]["source_span_numerator"]) for item in comparable)
    span_den = sum(int(item["compiler"]["source_span_denominator"]) for item in comparable)
    unsupported_counts = [int(item["compiler"]["unsupported_count"]) for item in attempted]
    latencies = [float(item["compiler"]["latency_seconds"]) for item in attempted]
    codes: Counter[str] = Counter()
    for item in attempted:
        codes.update(item["compiler"]["unsupported_codes"])

    observations = [
        _bool_rate("parser_acceptance", "compiler", parser_flags),
        _bool_rate("type_acceptance", "compiler", type_flags),
        _bool_rate("exact", "compiler", exact_flags, detail={"eligible_cases": len(comparable)}),
        _bool_rate(
            "canonical", "compiler", canonical_flags, detail={"eligible_cases": len(comparable)}
        ),
        _bool_rate("ast", "compiler", ast_flags, detail={"eligible_cases": len(comparable)}),
        _bool_rate("graph", "compiler", graph_flags, detail={"eligible_cases": len(comparable)}),
    ]
    if span_den > 0:
        observations.append(
            measured_rate(
                "source_span",
                "compiler",
                numerator=span_num,
                denominator=span_den,
                unit="fields",
                detail={"eligible_cases": len(comparable)},
            )
        )
    else:
        observations.append(
            unmeasured(
                "source_span",
                "compiler",
                METRIC_STATUS_NOT_MEASURED,
                "no_eligible_source_span_fields",
                unit="fields",
            )
        )
    if semantic_values:
        observations.append(
            measured_mean("semantic", "compiler", semantic_values, unit="score")
        )
    else:
        observations.append(
            unmeasured(
                "semantic",
                "compiler",
                METRIC_STATUS_NOT_MEASURED,
                "no_comparable_compiler_ir",
                unit="score",
            )
        )
    observations.append(
        unmeasured(
            "proof",
            "compiler",
            METRIC_STATUS_UNSUPPORTED,
            "frozen fixtures carry no independently checkable proof obligations",
            denominator=len(attempted),
            unit="obligations",
            detail={"independent_deterministic_replay_available": True},
        )
    )
    if unsupported_counts:
        observations.append(
            measured_mean(
                "unsupported",
                "compiler",
                [float(item) for item in unsupported_counts],
                unit="disclosures",
                numerator=sum(unsupported_counts),
                extra_aggregates={"codes": dict(sorted(codes.items()))},
            )
        )
    else:
        observations.append(
            unmeasured(
                "unsupported",
                "compiler",
                METRIC_STATUS_NOT_MEASURED,
                "empty_eligible_set",
                unit="disclosures",
            )
        )
    observations.append(measured_mean("latency", "compiler", latencies, unit="seconds"))
    return require_complete_e1_surface(observations, "compiler")


def _aggregate_decompiler(cases: Sequence[Mapping[str, object]]) -> tuple[MetricObservation, ...]:
    attempted = [item for item in cases if item["compiler"]["status"] == "success"]
    if not attempted:
        return require_complete_e1_surface(
            [
                unmeasured(
                    metric_id,
                    "decompiler",
                    METRIC_STATUS_NOT_MEASURED,
                    "no_successful_compiler_ir_to_decompile",
                    unit=(
                        "seconds"
                        if metric_id == "latency"
                        else "score"
                        if metric_id == "semantic"
                        else "disclosures"
                        if metric_id == "unsupported"
                        else "obligations"
                        if metric_id == "proof"
                        else "fields"
                        if metric_id == "source_span"
                        else "cases"
                    ),
                )
                for metric_id in E1_METRIC_IDS
            ],
            "decompiler",
        )

    parser_flags = [bool(item["decompiler"]["success"]) for item in attempted]
    type_flags = [bool(item["decompiler"]["type_accepted"]) for item in attempted]
    comparable = [item for item in attempted if item["decompiler"]["compare"] is not None]
    exact_flags = [bool(item["decompiler"]["compare"]["exact"]) for item in comparable]
    canonical_flags = [bool(item["decompiler"]["compare"]["canonical"]) for item in comparable]
    ast_flags = [bool(item["decompiler"]["compare"]["ast"]) for item in comparable]
    graph_flags = [bool(item["decompiler"]["compare"]["graph"]) for item in comparable]
    semantic_values = [
        float(item["decompiler"]["compare"]["semantic_score"]) for item in comparable
    ]
    latencies = [
        float(item["decompiler"]["latency_seconds"])
        for item in attempted
        if item["decompiler"]["latency_seconds"] is not None
    ]

    observations = [
        _bool_rate("parser_acceptance", "decompiler", parser_flags),
        _bool_rate("type_acceptance", "decompiler", type_flags),
        _bool_rate("exact", "decompiler", exact_flags, detail={"eligible_cases": len(comparable)}),
        _bool_rate(
            "canonical",
            "decompiler",
            canonical_flags,
            detail={"eligible_cases": len(comparable)},
        ),
        _bool_rate("ast", "decompiler", ast_flags, detail={"eligible_cases": len(comparable)}),
        _bool_rate("graph", "decompiler", graph_flags, detail={"eligible_cases": len(comparable)}),
        unmeasured(
            "source_span",
            "decompiler",
            METRIC_STATUS_NOT_APPLICABLE,
            "source-withheld decompiler has no source-span channel",
            denominator=len(attempted),
            unit="fields",
        ),
    ]
    if semantic_values:
        observations.append(
            measured_mean("semantic", "decompiler", semantic_values, unit="score")
        )
    else:
        observations.append(
            unmeasured(
                "semantic",
                "decompiler",
                METRIC_STATUS_NOT_MEASURED,
                "no_comparable_cycle_ir",
                unit="score",
            )
        )
    observations.append(
        unmeasured(
            "proof",
            "decompiler",
            METRIC_STATUS_UNSUPPORTED,
            "frozen fixtures carry no independently checkable proof obligations",
            denominator=len(attempted),
            unit="obligations",
            detail={"independent_deterministic_replay_available": True},
        )
    )
    observations.append(
        unmeasured(
            "unsupported",
            "decompiler",
            METRIC_STATUS_NOT_APPLICABLE,
            "source-withheld decompiler has no unsupported-construct disclosure channel",
            denominator=len(attempted),
            unit="disclosures",
        )
    )
    if latencies:
        observations.append(measured_mean("latency", "decompiler", latencies, unit="seconds"))
    else:
        observations.append(
            unmeasured(
                "latency",
                "decompiler",
                METRIC_STATUS_NOT_MEASURED,
                "no_timed_decompiler_calls",
                unit="seconds",
            )
        )
    return require_complete_e1_surface(observations, "decompiler")


def _stratum_key(case: Mapping[str, object], dimension: str) -> str:
    if dimension == "population":
        return str(case["population"])
    if dimension == "family":
        return str(case["family"])
    if dimension == "case_family":
        return str(case["case_family"])
    if dimension == "domain":
        return str(case["domain"])
    raise DeterministicBaselineError(f"unknown stratum dimension {dimension!r}")


def _compact_case(case: Mapping[str, object]) -> dict[str, object]:
    compiler = case["compiler"]
    decompiler = case["decompiler"]
    compare = compiler.get("compare") or {}
    cycle = decompiler.get("compare") or {}
    return {
        "case_id": case["case_id"],
        "case_cid": case["case_cid"],
        "population": case["population"],
        "family": case["family"],
        "case_family": case["case_family"],
        "domain": case["domain"],
        "source_cid": case["source_cid"],
        "gold_ir_cid": case["gold_ir_cid"],
        "compiler": {
            "status": compiler["status"],
            "request_cid": compiler["request_cid"],
            "result_cid": compiler["result_cid"],
            "ir_cid": compiler["ir_cid"],
            "trace_cids": compiler["trace_cids"],
            "unsupported_count": compiler["unsupported_count"],
            "latency_seconds": compiler["latency_seconds"],
            "exact": compare.get("exact"),
            "canonical": compare.get("canonical"),
            "ast": compare.get("ast"),
            "graph": compare.get("graph"),
            "semantic_score": compare.get("semantic_score"),
            "source_span_receipt_cid": compiler["source_span"].get("source_map_receipt_cid"),
        },
        "decompiler": {
            "status": decompiler["status"],
            "request_cid": decompiler["request_cid"],
            "result_cid": decompiler["result_cid"],
            "text_cid": decompiler["text_cid"],
            "trace_cids": decompiler["trace_cids"],
            "recompile_result_cid": decompiler["recompile_result_cid"],
            "l2_ir_cid": decompiler["l2_ir_cid"],
            "latency_seconds": decompiler["latency_seconds"],
            "exact": cycle.get("exact"),
            "canonical": cycle.get("canonical"),
            "ast": cycle.get("ast"),
            "graph": cycle.get("graph"),
            "semantic_score": cycle.get("semantic_score"),
        },
        "paired_trace_cids": {
            "compiler": compiler["trace_cids"],
            "decompiler": decompiler["trace_cids"],
        },
        "replay": case["replay"],
    }


def _unmaterialized_partitions(identities: Mapping[str, object]) -> dict[str, object]:
    corpus = identities["corpus"]
    split = identities["split"]
    holdouts = split["holdouts"]
    return {
        "policy": (
            "Hidden, canary, and holdout partitions are never selected. "
            "Unmaterialized non-hidden source rows are not_measured, not zero."
        ),
        "corpus_materialized": corpus["materialized"],
        "training_admitted_rows": corpus["training_admitted_rows"],
        "partitions": {
            "train": {
                "status": METRIC_STATUS_NOT_MEASURED,
                "reason": "corpus_not_materialized",
                "hidden": False,
            },
            "validation": {
                "status": METRIC_STATUS_NOT_MEASURED,
                "reason": "corpus_not_materialized",
                "hidden": False,
            },
            "canary": {
                "status": "excluded",
                "reason": "protected_split_excluded",
                "hidden": False,
            },
            "holdout": {
                "status": "excluded",
                "reason": "hidden_test_selection_prohibited",
                "hidden": True,
            },
            "statute_family": {
                "status": "excluded",
                "reason": "holdout_partition",
                "count": holdouts.get("family", {}).get("count"),
                "hidden": True,
            },
            "jurisdiction": {
                "status": "excluded",
                "reason": "holdout_partition",
                "count": holdouts.get("jurisdiction", {}).get("count"),
                "hidden": True,
            },
        },
        "measured_fixture_populations": list(MEASURED_POPULATIONS),
        "excluded_populations": list(EXCLUDED_POPULATIONS),
    }


def collect_tool_versions(*, elapsed_seconds: float, ru_before: object, ru_after: object) -> dict[str, object]:
    payload = {
        "interface": "IRDeterministicToolVersions@1",
        "python": {
            "version": sys.version,
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "resource": {
            "elapsed_seconds": elapsed_seconds,
            "ru_utime": ru_after.ru_utime - ru_before.ru_utime,
            "ru_stime": ru_after.ru_stime - ru_before.ru_stime,
            "ru_maxrss": ru_after.ru_maxrss,
            "ru_maxrss_unit": "kilobytes_on_linux",
            "ru_inblock": ru_after.ru_inblock - ru_before.ru_inblock,
            "ru_oublock": ru_after.ru_oublock - ru_before.ru_oublock,
            "ru_minflt": ru_after.ru_minflt - ru_before.ru_minflt,
            "ru_majflt": ru_after.ru_majflt - ru_before.ru_majflt,
        },
        "learned_inference": False,
        "network": False,
        "hidden_test_selection": False,
    }
    payload["tool_versions_cid"] = _identity_cid(payload, "tool_versions_cid")
    return payload


def build_recipe(identities: Mapping[str, object]) -> dict[str, object]:
    recipe = {
        "interface": IR_DETERMINISTIC_RECIPE_INTERFACE,
        "schema": IR_DETERMINISTIC_RECIPE_SCHEMA,
        "task_id": TASK_ID,
        "experiment_id": EXPERIMENT_ID,
        "generator": "ipfs_datasets_py/benchmarks/semantic_roundtrip/deterministic_baseline.py",
        "metric_module": "ipfs_datasets_py/benchmarks/semantic_roundtrip/e1_metrics.py",
        "surfaces": list(E1_SURFACES),
        "metrics": list(E1_METRIC_IDS),
        "measured_populations": list(MEASURED_POPULATIONS),
        "excluded_populations": list(EXCLUDED_POPULATIONS),
        "fixture_paths": {
            POPULATION_PILOT: str(PILOT_CASES_PATH.relative_to(DATASETS_ROOT)),
            POPULATION_REPAIR_DEVELOPMENT: str(REPAIR_DEV_CASES_PATH.relative_to(DATASETS_ROOT)),
        },
        "fixture_cids": {
            POPULATION_PILOT: _fixture_raw_cid(PILOT_CASES_PATH),
            POPULATION_REPAIR_DEVELOPMENT: _fixture_raw_cid(REPAIR_DEV_CASES_PATH),
        },
        "identities_cid": identities["identities_cid"],
        "corpus_manifest_cid": identities["corpus"]["manifest_cid"],
        "split_manifest_digest": identities["split"]["split_manifest_digest"],
        "hidden_test_commitment": identities["split"]["hidden_test_commitment"],
        "compiler_configuration_cid": identities["compiler"]["configuration_cid"],
        "decompiler_configuration_cid": identities["decompiler"]["configuration_cid"],
        "roundtrip_configuration_cid": identities["roundtrip"]["configuration_cid"],
        "missing_metric_as_zero": False,
        "learned_inference": False,
        "hidden_test_selection": False,
    }
    recipe["recipe_cid"] = _identity_cid(recipe, "recipe_cid")
    return recipe


def measure_r1_baseline() -> dict[str, object]:
    """Run the deterministic compiler/decompiler measurement."""

    if any(kind in EXCLUDED_POPULATIONS for kind in MEASURED_POPULATIONS):
        raise DeterministicBaselineError("measured populations overlap excluded populations")

    identities = load_bound_identities()
    fixture_cases = load_measured_fixture_cases()
    compiler = TypedDeonticCanonicalCompiler()
    decompiler = SourceWithheldCanonicalDecompiler()
    ru_before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.perf_counter()
    measured_cases = [
        _measure_case(record, compiler=compiler, decompiler=decompiler) for record in fixture_cases
    ]
    elapsed = time.perf_counter() - started
    ru_after = resource.getrusage(resource.RUSAGE_SELF)

    compiler_metrics = _aggregate_compiler(measured_cases)
    decompiler_metrics = _aggregate_decompiler(measured_cases)
    tool_versions = collect_tool_versions(
        elapsed_seconds=elapsed, ru_before=ru_before, ru_after=ru_after
    )
    recipe = build_recipe(identities)

    strata: dict[str, object] = {}
    for dimension in ("population", "family", "case_family", "domain"):
        groups: dict[str, list[Mapping[str, object]]] = {}
        for case in measured_cases:
            groups.setdefault(_stratum_key(case, dimension), []).append(case)
        strata[dimension] = {
            key: {
                "stratum": key,
                "dimension": dimension,
                "case_count": len(group),
                "case_ids": [item["case_id"] for item in group],
                "compiler": [item.to_dict() for item in _aggregate_compiler(group)],
                "decompiler": [item.to_dict() for item in _aggregate_decompiler(group)],
            }
            for key, group in sorted(groups.items())
        }

    replay_ok = all(item["replay"]["compiler_matched"] for item in measured_cases)
    decompiler_replays = [
        item["replay"]["decompiler_matched"]
        for item in measured_cases
        if item["replay"]["decompiler_matched"] is not None
    ]
    strata_payload = {
        "interface": "IRDeterministicR1Strata@1",
        "task_id": TASK_ID,
        "experiment_id": EXPERIMENT_ID,
        "dimensions": ["population", "family", "case_family", "domain"],
        "strata": strata,
        "unmaterialized_and_excluded": _unmaterialized_partitions(identities),
    }
    strata_payload["strata_cid"] = _identity_cid(strata_payload, "strata_cid")

    catalog = {
        "interface": IR_DETERMINISTIC_E1_METRICS_INTERFACE,
        "schema": IR_DETERMINISTIC_E1_METRICS_SCHEMA,
        "metrics": e1_metric_catalog(),
        "surfaces": list(E1_SURFACES),
        "missing_as_zero": False,
    }
    catalog["catalog_cid"] = _identity_cid(catalog, "catalog_cid")

    baseline = {
        "interface": IR_DETERMINISTIC_R1_BASELINE_INTERFACE,
        "schema": IR_DETERMINISTIC_R1_BASELINE_SCHEMA,
        "task_id": TASK_ID,
        "experiment_id": EXPERIMENT_ID,
        "recipe_cid": recipe["recipe_cid"],
        "identities_cid": identities["identities_cid"],
        "catalog_cid": catalog["catalog_cid"],
        "strata_cid": strata_payload["strata_cid"],
        "tool_versions_cid": tool_versions["tool_versions_cid"],
        "corpus_manifest_cid": identities["corpus"]["manifest_cid"],
        "split_manifest_digest": identities["split"]["split_manifest_digest"],
        "hidden_test_commitment": identities["split"]["hidden_test_commitment"],
        "hidden_labels_opened": False,
        "compiler_configuration_cid": TYPED_DEONTIC_COMPILER_CONFIG_CID,
        "decompiler_configuration_cid": SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
        "roundtrip_configuration_cid": CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID,
        "policy_cid": CANONICAL_PARITY_POLICY_CID,
        "implementation_raw_cids": identities["implementation_raw_cids"],
        "case_count": len(measured_cases),
        "populations": {
            population: {
                "case_count": sum(1 for item in measured_cases if item["population"] == population),
                "case_ids": [
                    item["case_id"] for item in measured_cases if item["population"] == population
                ],
            }
            for population in MEASURED_POPULATIONS
        },
        "metrics": {
            "compiler": [item.to_dict() for item in compiler_metrics],
            "decompiler": [item.to_dict() for item in decompiler_metrics],
        },
        "cases": [_compact_case(item) for item in measured_cases],
        "independent_replay": {
            "compiler_all_matched": replay_ok,
            "decompiler_matched_count": sum(1 for item in decompiler_replays if item),
            "decompiler_replay_denominator": len(decompiler_replays),
            "formal_proof_replayed": False,
            "formal_proof_reason": (
                "frozen fixtures carry no independently checkable proof obligations"
            ),
        },
        "learned_inference": False,
        "missing_metric_as_zero": False,
        "hidden_test_selection": False,
    }
    baseline["report_cid"] = _identity_cid(baseline, "report_cid")
    return {
        "recipe": recipe,
        "identities": identities,
        "catalog": catalog,
        "tool_versions": tool_versions,
        "strata": strata_payload,
        "baseline": baseline,
    }


def write_evaluation_artifacts(
    output_dir: str | Path | None = None,
    *,
    bundle: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, str]:
    """Write the compact R1 evaluation shard set."""

    directory = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = dict(bundle) if bundle is not None else measure_r1_baseline()
    mapping = {
        "recipe.json": artifacts["recipe"],
        "identities.json": artifacts["identities"],
        "metric_catalog.json": artifacts["catalog"],
        "tool_versions.json": artifacts["tool_versions"],
        "strata.json": artifacts["strata"],
        "r1_baseline.json": artifacts["baseline"],
    }
    written: dict[str, str] = {}
    for name, payload in mapping.items():
        path = directory / name
        _write_json(path, payload)
        written[name] = str(path.relative_to(DATASETS_ROOT))
    manifest = {
        "interface": "IRDeterministicEvaluationManifest@1",
        "task_id": TASK_ID,
        "experiment_id": EXPERIMENT_ID,
        "files": {
            name: {
                "path": relative,
                "sha256": _file_sha256(directory / name),
                "cid": payload.get(
                    {
                        "recipe.json": "recipe_cid",
                        "identities.json": "identities_cid",
                        "metric_catalog.json": "catalog_cid",
                        "tool_versions.json": "tool_versions_cid",
                        "strata.json": "strata_cid",
                        "r1_baseline.json": "report_cid",
                    }[name]
                ),
            }
            for name, relative, payload in (
                (key, written[key], mapping[key]) for key in mapping
            )
        },
        "report_cid": artifacts["baseline"]["report_cid"],
    }
    manifest["manifest_cid"] = _identity_cid(manifest, "manifest_cid")
    _write_json(directory / "manifest.json", manifest)
    written["manifest.json"] = str((directory / "manifest.json").relative_to(DATASETS_ROOT))
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure the PGIR-023 R1 deterministic baseline")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for compact evaluation artifacts",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    written = write_evaluation_artifacts(args.output_dir)
    sys.stdout.write(json.dumps({"written": written}, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
