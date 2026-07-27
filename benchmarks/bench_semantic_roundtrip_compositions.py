#!/usr/bin/env python3
"""Run the fair eight-cell semantic round-trip composition matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.logic_pipeline.content_addressing import (  # noqa: E402
    canonical_dag_json_bytes,
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import (  # noqa: E402
    LeanstralClient,
)
from benchmarks.semantic_roundtrip.matrix import (  # noqa: E402
    default_matrix,
    load_matrix_cases,
)
from benchmarks.semantic_roundtrip_capabilities import (  # noqa: E402
    SPACY_MODEL,
)
from benchmarks.semantic_roundtrip.canonical_decision import (  # noqa: E402
    CanonicalDecisionValidationError,
    validate_canonical_decision_file,
)


DEFAULT_FIXTURE = (
    REPO_ROOT / "tests/fixtures/semantic_roundtrip/pilot_cases.json"
)
REPORT_INTERFACE = "SemanticRoundTripCompositionDecision@1"
REPORT_SCHEMA_VERSION = (
    "ipfs-datasets.semantic-roundtrip-composition-pilot.v1"
)


class ReportValidationError(ValueError):
    """Raised when a frozen composition report is incomplete or inconsistent."""


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReportValidationError(f"{path} must be an object")
    return value


def _list(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReportValidationError(f"{path} must be an array")
    return value


def _require(
    condition: object,
    message: str,
) -> None:
    if not condition:
        raise ReportValidationError(message)


def _fixture_identity(
    fixture_path: Path,
) -> tuple[list[str], str]:
    try:
        raw = fixture_path.read_bytes()
        fixture = json.loads(raw)
    except OSError as exc:
        raise ReportValidationError(
            f"cannot read pilot fixture {fixture_path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ReportValidationError(
            f"pilot fixture is not valid JSON: {exc}"
        ) from exc
    rows = _list(fixture, "pilot fixture")
    case_ids: list[str] = []
    for index, row in enumerate(rows):
        case = _mapping(row, f"pilot fixture[{index}]")
        case_id = case.get("case_id", case.get("id"))
        _require(
            isinstance(case_id, str) and bool(case_id),
            f"pilot fixture[{index}].case_id must be a nonempty string",
        )
        case_ids.append(case_id)
    _require(
        len(case_ids) == len(set(case_ids)),
        "pilot fixture case IDs must be unique",
    )
    return case_ids, hashlib.sha256(raw).hexdigest()


def _record_key(
    record: Mapping[str, Any],
    *,
    path: str,
) -> tuple[str, int, str]:
    case_id = record.get("case_id")
    repeat_index = record.get("repeat_index")
    arm_id = record.get("arm_id", record.get("cell_id"))
    _require(
        isinstance(case_id, str) and bool(case_id),
        f"{path}.case_id must be a nonempty string",
    )
    _require(
        isinstance(repeat_index, int)
        and not isinstance(repeat_index, bool)
        and repeat_index >= 0,
        f"{path}.repeat_index must be a nonnegative integer",
    )
    _require(
        isinstance(arm_id, str) and bool(arm_id),
        f"{path}.arm_id must be a nonempty string",
    )
    status = record.get("status")
    _require(
        status in {"success", "failed"},
        f"{path}.status must be terminal (success or failed)",
    )
    losses = _mapping(record.get("losses"), f"{path}.losses")
    for name in ("forward", "cycle", "end_to_end", "primary"):
        value = losses.get(name)
        _require(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and 0.0 <= float(value) <= 1.0,
            f"{path}.losses.{name} must be finite and in [0, 1]",
        )
    _require(
        float(losses["primary"]) == float(losses["end_to_end"]),
        f"{path}.losses.primary must equal end_to_end",
    )
    if status == "failed":
        _require(
            all(
                float(losses[name]) == 1.0
                for name in ("forward", "cycle", "end_to_end", "primary")
            ),
            f"{path} terminal failure losses must all equal one",
        )
    gates = _mapping(record.get("gates"), f"{path}.gates")
    for name in (
        "source_copy_exclusion",
        "polarity_preservation",
        "full_coverage",
        "selection_eligible",
    ):
        _require(
            isinstance(gates.get(name), bool),
            f"{path}.gates.{name} must be boolean",
        )
    _require(
        gates["selection_eligible"]
        == all(
            bool(gates[name])
            for name in (
                "source_copy_exclusion",
                "polarity_preservation",
                "full_coverage",
            )
        ),
        f"{path}.gates.selection_eligible is inconsistent",
    )
    _mapping(record.get("cost"), f"{path}.cost")
    for cid_field in (
        "candidate_cid",
        "coordinate_record_cid",
        "extended_record_cid",
    ):
        value = record.get(cid_field)
        if value is not None:
            try:
                validate_cid(value)
            except (TypeError, ValueError) as exc:
                raise ReportValidationError(
                    f"{path}.{cid_field} is not a canonical CID: {exc}"
                ) from exc
    return case_id, repeat_index, arm_id


def _validate_arm_summaries(
    statistics: Mapping[str, Any],
    *,
    case_ids: list[str],
    deterministic_ids: list[str],
    model_ids: list[str],
    minimum_model_repeats: int,
    records: list[Mapping[str, Any]],
) -> dict[str, dict[str, object]]:
    summaries = _mapping(
        statistics.get("arm_summaries"),
        "$.statistics.arm_summaries",
    )
    expected_ids = set(deterministic_ids) | set(model_ids)
    _require(
        set(summaries) == expected_ids,
        "$.statistics.arm_summaries must cover exactly every "
        "preregistered arm",
    )
    records_by_arm: dict[str, list[Mapping[str, Any]]] = {
        arm_id: [] for arm_id in expected_ids
    }
    for record in records:
        records_by_arm[str(record.get("arm_id", record.get("cell_id")))].append(
            record
        )
    recomputed: dict[str, dict[str, object]] = {}
    for arm_id in sorted(expected_ids):
        path = f"$.statistics.arm_summaries[{arm_id!r}]"
        summary = _mapping(summaries[arm_id], path)
        repeat_count = (
            1 if arm_id in deterministic_ids else minimum_model_repeats
        )
        scheduled = len(case_ids) * repeat_count
        _require(
            summary.get("scheduled_coordinate_count") == scheduled,
            f"{path}.scheduled_coordinate_count must be {scheduled}",
        )
        _require(
            summary.get("observed_coordinate_count") == scheduled,
            f"{path}.observed_coordinate_count must be {scheduled}",
        )
        _require(
            summary.get("missing_coordinate_count") == 0,
            f"{path}.missing_coordinate_count must be zero",
        )
        _require(
            summary.get("repeat_count_per_case") == repeat_count,
            f"{path}.repeat_count_per_case must be {repeat_count}",
        )
        _require(
            summary.get("execution_status") == "complete",
            f"{path}.execution_status must be complete",
        )
        per_case = _mapping(summary.get("per_case"), f"{path}.per_case")
        _require(
            set(per_case) == set(case_ids),
            f"{path}.per_case must cover every unchanged pilot case",
        )
        arm_records = records_by_arm[arm_id]
        case_means: dict[str, dict[str, float]] = {}
        case_eligibility: dict[str, bool] = {}
        for case_id in case_ids:
            case_path = f"{path}.per_case[{case_id!r}]"
            case_summary = _mapping(per_case[case_id], case_path)
            case_records = sorted(
                (
                    record
                    for record in arm_records
                    if record.get("case_id") == case_id
                ),
                key=lambda record: int(record.get("repeat_index", -1)),
            )
            _require(
                [record.get("repeat_index") for record in case_records]
                == list(range(repeat_count)),
                f"{case_path} records must cover every repeat exactly once",
            )
            _require(
                case_summary.get("scheduled_repeat_count") == repeat_count,
                f"{case_path}.scheduled_repeat_count must be {repeat_count}",
            )
            _require(
                case_summary.get("observed_terminal_repeat_count")
                == repeat_count,
                f"{case_path}.observed_terminal_repeat_count must be "
                f"{repeat_count}",
            )
            case_losses = _mapping(
                case_summary.get("losses"),
                f"{case_path}.losses",
            )
            computed_losses: dict[str, float] = {}
            for loss_name in ("forward", "cycle", "end_to_end"):
                computed = round(
                    math.fsum(
                        float(
                            _mapping(
                                record.get("losses"),
                                f"{case_path} record losses",
                            )[loss_name]
                        )
                        for record in case_records
                    )
                    / repeat_count,
                    12,
                )
                reported = case_losses.get(loss_name)
                _require(
                    isinstance(reported, (int, float))
                    and not isinstance(reported, bool)
                    and math.isfinite(float(reported))
                    and float(reported) == computed,
                    f"{case_path}.losses.{loss_name} differs from records",
                )
                computed_losses[loss_name] = computed
            all_repeats_eligible = all(
                bool(
                    _mapping(
                        record.get("gates"),
                        f"{case_path} record gates",
                    ).get("selection_eligible")
                )
                for record in case_records
            )
            _require(
                case_summary.get("all_repeats_selection_eligible")
                is all_repeats_eligible,
                f"{case_path}.all_repeats_selection_eligible differs "
                "from records",
            )
            case_means[case_id] = computed_losses
            case_eligibility[case_id] = all_repeats_eligible
        _mapping(summary.get("cost"), f"{path}.cost")
        aggregate = _mapping(summary.get("aggregate"), f"{path}.aggregate")
        aggregate_means: dict[str, float] = {}
        for loss_name in ("forward", "cycle", "end_to_end"):
            loss = _mapping(
                aggregate.get(loss_name),
                f"{path}.aggregate.{loss_name}",
            )
            computed = round(
                math.fsum(
                    case_means[case_id][loss_name] for case_id in case_ids
                )
                / len(case_ids),
                12,
            )
            _require(
                isinstance(loss.get("mean"), (int, float))
                and not isinstance(loss.get("mean"), bool)
                and math.isfinite(float(loss["mean"]))
                and float(loss["mean"]) == computed,
                f"{path}.aggregate.{loss_name}.mean differs from records",
            )
            aggregate_means[loss_name] = computed
            uncertainty = _mapping(
                loss.get("uncertainty"),
                f"{path}.aggregate.{loss_name}.uncertainty",
            )
            for field in ("method", "low", "high"):
                _require(
                    uncertainty.get(field) is not None,
                    f"{path}.aggregate.{loss_name}.uncertainty.{field} "
                    "must be reported",
                )
        all_cases_eligible = all(case_eligibility.values())
        _require(
            summary.get("all_cases_selection_eligible")
            is all_cases_eligible,
            f"{path}.all_cases_selection_eligible differs from records",
        )
        recomputed[arm_id] = {
            "aggregate": aggregate_means,
            "selection_eligible": all_cases_eligible,
        }
    return recomputed


def _validate_selection(
    selection: Mapping[str, Any],
    *,
    arm_ids: list[str],
    recomputed_summaries: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Recompute the complete selection decision from terminal records."""

    eligible = [
        arm_id
        for arm_id in arm_ids
        if recomputed_summaries[arm_id]["selection_eligible"] is True
    ]
    ranked = sorted(
        eligible,
        key=lambda arm_id: (
            float(
                _mapping(
                    recomputed_summaries[arm_id].get("aggregate"),
                    f"recomputed summary {arm_id!r}",
                )["end_to_end"]
            ),
            arm_id,
        ),
    )
    co_winners: list[str] = []
    if ranked:
        best_loss = float(
            _mapping(
                recomputed_summaries[ranked[0]].get("aggregate"),
                f"recomputed summary {ranked[0]!r}",
            )["end_to_end"]
        )
        co_winners = [
            arm_id
            for arm_id in ranked
            if float(
                _mapping(
                    recomputed_summaries[arm_id].get("aggregate"),
                    f"recomputed summary {arm_id!r}",
                )["end_to_end"]
            )
            == best_loss
        ]
    else:
        best_loss = None

    expected_outcome = (
        "selected"
        if len(co_winners) == 1
        else "exact_tie"
        if len(co_winners) > 1
        else "no_eligible_composition"
    )
    _require(
        selection.get("outcome") == expected_outcome,
        "$.selection.outcome differs from recomputed selection evidence",
    )
    reported_eligible = _list(
        selection.get("eligible_arm_ids"),
        "$.selection.eligible_arm_ids",
    )
    _require(
        reported_eligible == eligible,
        "$.selection.eligible_arm_ids differs from terminal gates",
    )
    reported_ranked = _list(
        selection.get("ranked_eligible_arm_ids"),
        "$.selection.ranked_eligible_arm_ids",
    )
    _require(
        reported_ranked == ranked,
        "$.selection.ranked_eligible_arm_ids differs from recomputed loss order",
    )
    reported_co_winners = _list(
        selection.get("co_winner_arm_ids"),
        "$.selection.co_winner_arm_ids",
    )
    _require(
        reported_co_winners == co_winners,
        "$.selection.co_winner_arm_ids differs from exact minimum-loss set",
    )
    _require(
        len(reported_co_winners) == len(set(reported_co_winners)),
        "$.selection.co_winner_arm_ids must be unique",
    )
    _require(
        selection.get("tie") is (len(co_winners) > 1),
        "$.selection.tie differs from recomputed co-winner cardinality",
    )
    _require(
        selection.get("production_promotion_allowed") is False,
        "$.selection.production_promotion_allowed must be false",
    )
    _require(
        selection.get("selection_metric")
        == "lowest per-case-first macro mean end-to-end loss",
        "$.selection.selection_metric differs from the frozen protocol",
    )
    reasons = _list(selection.get("reasons"), "$.selection.reasons")
    _require(
        bool(reasons)
        and all(
            isinstance(reason, str) and bool(reason.strip())
            for reason in reasons
        ),
        "$.selection.reasons must contain explicit nonblank reasons",
    )

    winner = selection.get("winner")
    if expected_outcome == "selected":
        winner_map = _mapping(winner, "$.selection.winner")
        _require(
            winner_map.get("arm_id") == co_winners[0],
            "$.selection.winner.arm_id differs from the unique minimum",
        )
        _require(
            isinstance(winner_map.get("mean_end_to_end_loss"), (int, float))
            and not isinstance(winner_map.get("mean_end_to_end_loss"), bool)
            and float(winner_map["mean_end_to_end_loss"]) == best_loss,
            "$.selection.winner.mean_end_to_end_loss differs from records",
        )
    else:
        _require(
            winner is None,
            "$.selection.winner must be null without a unique minimum",
        )

    return {
        "outcome": expected_outcome,
        "eligible_arm_ids": eligible,
        "co_winner_arm_ids": co_winners,
        "winner_arm_id": co_winners[0] if len(co_winners) == 1 else None,
        "bounded_tie": 1 < len(co_winners) <= len(arm_ids),
    }


def validate_composition_report(
    value: object,
    *,
    fixture_path: Path = DEFAULT_FIXTURE,
) -> dict[str, object]:
    """Validate the complete, preregistered SRT-014 decision artifact.

    Failed coordinates remain valid terminal evidence, but missing coordinates
    do not.  This distinction prevents a fail-closed loss placeholder from
    being mistaken for an executed five-repeat model result.
    """

    report = _mapping(value, "$")
    _require(
        report.get("interface") == REPORT_INTERFACE,
        f"$.interface must be {REPORT_INTERFACE}",
    )
    _require(
        report.get("schema_version") == REPORT_SCHEMA_VERSION,
        f"$.schema_version must be {REPORT_SCHEMA_VERSION}",
    )
    report_cid = report.get("report_cid")
    try:
        validate_cid(report_cid, codecs=("dag-json",))
    except (TypeError, ValueError) as exc:
        raise ReportValidationError(
            f"$.report_cid is not a canonical DAG-JSON CID: {exc}"
        ) from exc
    cid_payload = dict(report)
    del cid_payload["report_cid"]
    _require(
        cid_for_dag_json(cid_payload) == report_cid,
        "$.report_cid does not match the canonical report payload",
    )

    fixture_case_ids, fixture_sha256 = _fixture_identity(fixture_path)
    inputs = _mapping(report.get("inputs"), "$.inputs")
    fixture = _mapping(inputs.get("fixture"), "$.inputs.fixture")
    _require(
        fixture.get("unchanged") is True,
        "$.inputs.fixture.unchanged must be true",
    )
    _require(
        fixture.get("case_count") == len(fixture_case_ids),
        "$.inputs.fixture.case_count does not match the pilot fixture",
    )
    _require(
        fixture.get("case_ids") == fixture_case_ids,
        "$.inputs.fixture.case_ids do not match the pilot fixture",
    )
    _require(
        fixture.get("sha256") == fixture_sha256,
        "$.inputs.fixture.sha256 does not match the pilot fixture",
    )

    preregistration = _mapping(
        report.get("preregistration"),
        "$.preregistration",
    )
    deterministic_ids = _list(
        preregistration.get("deterministic_cell_ids"),
        "$.preregistration.deterministic_cell_ids",
    )
    model_ids = _list(
        preregistration.get("model_backed_cell_ids"),
        "$.preregistration.model_backed_cell_ids",
    )
    _require(
        len(deterministic_ids) == 4
        and len(set(deterministic_ids)) == 4
        and all(isinstance(item, str) for item in deterministic_ids),
        "exactly four unique deterministic cell IDs are required",
    )
    _require(
        len(model_ids) == 26
        and len(set(model_ids)) == 26
        and all(isinstance(item, str) for item in model_ids),
        "exactly 26 unique model-backed cell IDs are required",
    )
    _require(
        set(deterministic_ids).isdisjoint(model_ids),
        "deterministic and model-backed cell IDs must be disjoint",
    )
    _require(
        preregistration.get("planned_cell_count") == 30,
        "$.preregistration.planned_cell_count must be 30",
    )
    _require(
        preregistration.get("deterministic_repeats") == 1,
        "$.preregistration.deterministic_repeats must be one",
    )
    minimum_model_repeats = preregistration.get(
        "minimum_uncached_model_repeats"
    )
    _require(
        isinstance(minimum_model_repeats, int)
        and not isinstance(minimum_model_repeats, bool)
        and minimum_model_repeats >= 5,
        "at least five uncached model repeats are required",
    )
    schedule = _mapping(
        preregistration.get("model_schedule"),
        "$.preregistration.model_schedule",
    )
    schedule_payload = dict(schedule)
    supplied_schedule_cid = preregistration.get("model_schedule_cid")
    try:
        validate_cid(supplied_schedule_cid, codecs=("dag-json",))
    except (TypeError, ValueError) as exc:
        raise ReportValidationError(
            "$.preregistration.model_schedule_cid is invalid: "
            f"{exc}"
        ) from exc
    _require(
        cid_for_dag_json(schedule_payload) == supplied_schedule_cid,
        "$.preregistration.model_schedule_cid does not match the schedule",
    )
    _require(
        schedule.get("case_ids") == fixture_case_ids,
        "$.preregistration.model_schedule.case_ids must match the fixture",
    )
    _require(
        schedule.get("repeat_count") == minimum_model_repeats,
        "$.preregistration.model_schedule.repeat_count is inconsistent",
    )
    schedule_arms = schedule.get("model_arm_ids", schedule.get("arm_ids"))
    _require(
        set(_list(schedule_arms, "model schedule arm IDs"))
        == set(model_ids),
        "model schedule arms must equal the preregistered model-backed arms",
    )
    blocks = _list(
        schedule.get("blocks"),
        "$.preregistration.model_schedule.blocks",
    )
    _require(
        len(blocks) == len(fixture_case_ids) * minimum_model_repeats,
        "model schedule must contain one block per case and repeat",
    )
    scheduled_model: dict[
        tuple[str, int, str],
        tuple[str, str],
    ] = {}
    namespaces: list[str] = []
    for index, raw_block in enumerate(blocks):
        path = f"$.preregistration.model_schedule.blocks[{index}]"
        block = _mapping(raw_block, path)
        case_id = block.get("case_id")
        repeat_index = block.get("repeat_index")
        _require(
            case_id in fixture_case_ids,
            f"{path}.case_id is not in the fixture",
        )
        _require(
            isinstance(repeat_index, int)
            and not isinstance(repeat_index, bool)
            and 0 <= repeat_index < minimum_model_repeats,
            f"{path}.repeat_index is outside the preregistered range",
        )
        arm_order = _list(block.get("arm_order"), f"{path}.arm_order")
        _require(
            len(arm_order) == len(model_ids)
            and set(arm_order) == set(model_ids),
            f"{path}.arm_order must contain every model arm exactly once",
        )
        coordinates = _list(
            block.get("coordinates"),
            f"{path}.coordinates",
        )
        _require(
            len(coordinates) == len(model_ids),
            f"{path}.coordinates must contain every model arm",
        )
        coordinate_arms: list[str] = []
        for coordinate_index, raw_coordinate in enumerate(coordinates):
            coordinate_path = f"{path}.coordinates[{coordinate_index}]"
            coordinate = _mapping(raw_coordinate, coordinate_path)
            arm_id = coordinate.get("arm_id")
            cache_mode = coordinate.get("cache_mode")
            namespace = coordinate.get("cache_namespace")
            _require(
                arm_id in model_ids,
                f"{coordinate_path}.arm_id is not preregistered",
            )
            _require(
                cache_mode == "uncached",
                f"{coordinate_path}.cache_mode must be uncached",
            )
            _require(
                isinstance(namespace, str) and bool(namespace),
                f"{coordinate_path}.cache_namespace must be nonempty",
            )
            key = (case_id, repeat_index, arm_id)
            _require(
                key not in scheduled_model,
                f"duplicate scheduled model coordinate {key!r}",
            )
            scheduled_model[key] = (cache_mode, namespace)
            namespaces.append(namespace)
            coordinate_arms.append(arm_id)
        _require(
            coordinate_arms == arm_order,
            f"{path}.coordinates must preserve arm_order",
        )
    _require(
        len(namespaces) == len(set(namespaces)),
        "every model coordinate must use a unique uncached namespace",
    )

    execution = _mapping(report.get("execution"), "$.execution")
    expected_deterministic_count = (
        len(fixture_case_ids) * len(deterministic_ids)
    )
    expected_model_count = len(scheduled_model)
    expected_total = expected_deterministic_count + expected_model_count
    _require(
        execution.get("status") == "complete",
        "$.execution.status must be complete",
    )
    _require(
        execution.get("scheduled_coordinate_count") == expected_total,
        "$.execution.scheduled_coordinate_count is inconsistent",
    )
    _require(
        execution.get("observed_terminal_coordinate_count")
        == expected_total,
        "all scheduled coordinates must have terminal observations",
    )
    _require(
        execution.get("missing_coordinate_count") == 0,
        "$.execution.missing_coordinate_count must be zero",
    )
    deterministic = _mapping(
        execution.get("deterministic"),
        "$.execution.deterministic",
    )
    model_backed = _mapping(
        execution.get("model_backed"),
        "$.execution.model_backed",
    )
    deterministic_records = _list(
        deterministic.get("records"),
        "$.execution.deterministic.records",
    )
    model_records = _list(
        model_backed.get("records"),
        "$.execution.model_backed.records",
    )
    _require(
        len(deterministic_records) == expected_deterministic_count,
        "deterministic record count is incomplete",
    )
    _require(
        len(model_records) == expected_model_count,
        "model-backed record count is incomplete",
    )
    deterministic_keys: list[tuple[str, int, str]] = []
    for index, raw_record in enumerate(deterministic_records):
        path = f"$.execution.deterministic.records[{index}]"
        record = _mapping(raw_record, path)
        key = _record_key(record, path=path)
        _require(
            key[0] in fixture_case_ids
            and key[1] == 0
            and key[2] in deterministic_ids,
            f"{path} is not a preregistered deterministic coordinate",
        )
        deterministic_keys.append(key)
    expected_deterministic_keys = {
        (case_id, 0, arm_id)
        for case_id in fixture_case_ids
        for arm_id in deterministic_ids
    }
    _require(
        set(deterministic_keys) == expected_deterministic_keys
        and len(deterministic_keys) == len(set(deterministic_keys)),
        "deterministic records must cover each case/arm exactly once",
    )
    model_keys: list[tuple[str, int, str]] = []
    observed_namespaces: list[str] = []
    for index, raw_record in enumerate(model_records):
        path = f"$.execution.model_backed.records[{index}]"
        record = _mapping(raw_record, path)
        key = _record_key(record, path=path)
        _require(
            key in scheduled_model,
            f"{path} is not a scheduled model coordinate",
        )
        cache_mode, namespace = scheduled_model[key]
        _require(
            record.get("cache_mode") == cache_mode,
            f"{path}.cache_mode differs from the frozen schedule",
        )
        _require(
            record.get("cache_namespace") == namespace,
            f"{path}.cache_namespace differs from the frozen schedule",
        )
        model_keys.append(key)
        observed_namespaces.append(namespace)
    _require(
        Counter(model_keys) == Counter(scheduled_model.keys()),
        "model records must cover each frozen coordinate exactly once",
    )
    _require(
        len(observed_namespaces) == len(set(observed_namespaces)),
        "observed model cache namespaces must be unique",
    )

    recomputed_summaries = _validate_arm_summaries(
        _mapping(report.get("statistics"), "$.statistics"),
        case_ids=fixture_case_ids,
        deterministic_ids=deterministic_ids,
        model_ids=model_ids,
        minimum_model_repeats=minimum_model_repeats,
        records=[
            *(
                _mapping(
                    record,
                    f"$.execution.deterministic.records[{index}]",
                )
                for index, record in enumerate(deterministic_records)
            ),
            *(
                _mapping(
                    record,
                    f"$.execution.model_backed.records[{index}]",
                )
                for index, record in enumerate(model_records)
            ),
        ],
    )
    acceptance = _mapping(report.get("acceptance"), "$.acceptance")
    for flag in (
        "all_deterministic_cells_once",
        "all_model_backed_cells_five_uncached_repeats",
        "unchanged_pilot_cases_scored",
        "source_copy_gate_enforced",
        "polarity_gate_enforced",
        "full_coverage_gate_enforced",
        "per_case_and_aggregate_losses_reported",
        "uncertainty_reported",
        "costs_reported_with_missingness",
    ):
        _require(
            acceptance.get(flag) is True,
            f"$.acceptance.{flag} must be true",
        )
    _require(
        acceptance.get("winner_manufactured") is False,
        "$.acceptance.winner_manufactured must be false",
    )
    selection = _mapping(report.get("selection"), "$.selection")
    selection_result = _validate_selection(
        selection,
        arm_ids=[*deterministic_ids, *model_ids],
        recomputed_summaries=recomputed_summaries,
    )
    return {
        "status": "valid",
        "report_cid": report_cid,
        "case_count": len(fixture_case_ids),
        "cell_count": len(deterministic_ids) + len(model_ids),
        "terminal_coordinate_count": expected_total,
        "model_repeat_count": minimum_model_repeats,
        "selection_outcome": selection_result["outcome"],
        "eligible_arm_ids": selection_result["eligible_arm_ids"],
        "co_winner_arm_ids": selection_result["co_winner_arm_ids"],
        "winner_arm_id": selection_result["winner_arm_id"],
        "bounded_tie": selection_result["bounded_tie"],
    }


def validate_report_file(
    report_path: Path,
    *,
    fixture_path: Path = DEFAULT_FIXTURE,
) -> dict[str, object]:
    try:
        value = json.loads(report_path.read_bytes())
    except OSError as exc:
        raise ReportValidationError(
            f"cannot read report {report_path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ReportValidationError(
            f"report is not valid JSON: {exc}"
        ) from exc
    return validate_composition_report(value, fixture_path=fixture_path)


def _load_spacy_pipeline() -> object | None:
    """Load the declared model once; adapters report absence as a failure."""

    try:
        import spacy

        return spacy.load(SPACY_MODEL)
    except (ImportError, OSError, RuntimeError):
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run typed, modal-spaCy, direct Leanstral, and spaCy-Leanstral "
            "constructors against deterministic and Leanstral realizers."
        )
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="JSON case fixture (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write canonical JSON to this path instead of stdout",
    )
    validation = parser.add_mutually_exclusive_group()
    validation.add_argument(
        "--validate-report",
        type=Path,
        help=(
            "validate a complete frozen SRT-014 decision report and exit "
            "without running model inference"
        ),
    )
    validation.add_argument(
        "--validate-canonical-decision",
        type=Path,
        help=(
            "validate the source-bound SRT-019 canonical compiler decision "
            "and exit without running model inference"
        ),
    )
    return parser


def run(fixture: Path) -> dict[str, object]:
    cases = load_matrix_cases(fixture)
    client = LeanstralClient()
    matrix = default_matrix(
        leanstral_client=client,
        spacy_pipeline=_load_spacy_pipeline(),
    )
    return matrix.run(cases).to_dict()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.validate_report is not None:
        try:
            result = validate_report_file(
                args.validate_report,
                fixture_path=args.fixture,
            )
        except ReportValidationError as exc:
            print(
                json.dumps(
                    {
                        "status": "invalid",
                        "report": str(args.validate_report),
                        "error": str(exc),
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.validate_canonical_decision is not None:
        try:
            result = validate_canonical_decision_file(
                args.validate_canonical_decision,
                repo_root=REPO_ROOT,
                composition_validator=lambda value: validate_composition_report(
                    value,
                    fixture_path=args.fixture,
                ),
            )
        except CanonicalDecisionValidationError as exc:
            print(
                json.dumps(
                    {
                        "status": "invalid",
                        "decision": str(args.validate_canonical_decision),
                        "error": str(exc),
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0
    report = run(args.fixture)
    raw = canonical_dag_json_bytes(report) + b"\n"
    if args.output is None:
        sys.stdout.buffer.write(raw)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(raw)
        print(
            json.dumps(
                {
                    "status": "success",
                    "output": str(args.output),
                    "run_cid": report["run_cid"],
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
