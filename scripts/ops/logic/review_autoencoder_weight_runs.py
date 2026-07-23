#!/usr/bin/env python3
"""Review historical legal-IR autoencoder states, scores, and reusable features.

The autoencoder state is intentionally persisted as JSON maps so that failed
daemon runs can be inspected after the fact.  This utility turns those artifacts
into an operational manifest:

* poor or incomplete runs are marked deprecated;
* strong runs are ranked as canonical warm-start candidates;
* repeated high-magnitude feature/logit keys are extracted as reusable signal;
* optional canonical averaged state can be written from the selected sources.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SENTINEL_ABS = 1.0e11
DEFAULT_OUTPUT_DIR = Path("workspace/autoencoder-weight-review")
DEFAULT_CANONICAL_STATE_NAME = "legal-ir-autoencoder-canonical.state.json"
DEFAULT_CANONICAL_SOURCE_STATUSES = (
    "canonical_primary",
    "canonical_support",
    "reference_only",
)
CANONICAL_SOURCE_STATUS_WEIGHTS = {
    "canonical_primary": 1.0,
    "canonical_support": 0.70,
    "reference_only": 0.25,
}

METRIC_KEYS = (
    "best_validation_ce",
    "best_validation_cosine",
    "best_validation_ir_ce",
    "best_validation_ir_cosine",
    "best_validation_ir_guided_ce",
    "best_validation_ir_guided_cosine",
    "best_validation_ir_source_decompiled_text_embedding_cosine_loss",
    "best_validation_ir_source_decompiled_text_token_loss",
    "best_validation_learned_ir_view_ce",
    "best_validation_learned_ir_view_cosine",
    "best_validation_learned_ir_family_ce_excess",
    "best_validation_learned_ir_worst_family_ce_excess",
    "best_validation_learned_ir_worst_family_cosine_gap",
    "latest_compiler_ir_ce",
    "latest_compiler_ir_cosine",
    "latest_learned_ir_view_cosine",
    "latest_source_decompiled_text_embedding_cosine_loss",
    "train_ce_improved_cycles",
    "train_cosine_improved_cycles",
    "validation_ce_improved_cycles",
    "validation_cosine_improved_cycles",
    "compiler_ir_validation_ce_improved_cycles",
    "compiler_ir_validation_cosine_improved_cycles",
    "compiler_guidance_improved_cycles",
)

GENERALIZABLE_STATE_MAPS = (
    "compiler_quality_embedding_weights",
    "compiler_quality_family_logits",
    "logic_signature_embedding_weights",
    "logic_signature_family_logits",
    "logic_signature_legal_ir_view_logits",
    "round_trip_signal_embedding_weights",
    "round_trip_signal_family_logits",
    "round_trip_signal_legal_ir_view_logits",
    "decompiler_plan_embedding_weights",
    "decompiler_plan_family_logits",
    "decompiler_plan_legal_ir_view_logits",
    "predicate_argument_embedding_weights",
    "predicate_argument_family_logits",
    "predicate_argument_legal_ir_view_logits",
    "feature_embedding_weights",
    "feature_family_logits",
    "feature_legal_ir_view_logits",
    "family_embedding_weights",
    "family_legal_ir_view_embedding_weights",
    "family_legal_ir_view_family_logits",
    "family_semantic_slot_embedding_weights",
    "family_semantic_slot_legal_ir_view_embedding_weights",
    "family_semantic_slot_legal_ir_view_logits",
    "legal_ir_view_embedding_weights",
    "legal_ir_view_family_logits",
    "legal_ir_view_logits",
    "semantic_slot_embedding_weights",
    "semantic_slot_family_logits",
    "semantic_slot_legal_ir_view_embedding_weights",
    "semantic_slot_legal_ir_view_family_logits",
    "semantic_slot_legal_ir_view_logits",
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _finite_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    if not math.isfinite(result) or abs(result) >= SENTINEL_ABS:
        return math.nan
    return result


def _is_finite(value: Any) -> bool:
    return math.isfinite(_finite_float(value))


def _bounded_metric(value: Any, *, minimum: float = -1.0, maximum: float = 1.0) -> float:
    number = _finite_float(value)
    if not math.isfinite(number):
        return math.nan
    return max(minimum, min(maximum, number))


def _score_run(row: Mapping[str, Any]) -> float:
    cycles = _finite_float(row.get("cycles"))
    if not math.isfinite(cycles) or cycles <= 0:
        return -999.0

    validation_ce = _finite_float(row.get("best_validation_ce"))
    ir_ce = _finite_float(row.get("best_validation_ir_ce"))
    ir_guided_ce = _finite_float(row.get("best_validation_ir_guided_ce"))
    if math.isfinite(ir_guided_ce):
        ir_ce = min(ir_ce, ir_guided_ce) if math.isfinite(ir_ce) else ir_guided_ce

    ir_cosine = max(
        _bounded_metric(row.get("best_validation_ir_cosine")),
        _bounded_metric(row.get("best_validation_ir_guided_cosine")),
    )
    learned_ce = _finite_float(row.get("best_validation_learned_ir_view_ce"))
    learned_cosine = _bounded_metric(row.get("best_validation_learned_ir_view_cosine"))
    source_text_loss = _finite_float(
        row.get("best_validation_ir_source_decompiled_text_embedding_cosine_loss")
    )

    score = min(cycles, 100.0) / 100.0 * 5.0
    if math.isfinite(validation_ce):
        score += max(0.0, 3.0 - validation_ce) / 3.0 * 18.0
    if math.isfinite(ir_ce):
        score += max(0.0, 2.2 - ir_ce) / 2.2 * 18.0
        score += max(0.0, 0.25 - ir_ce) / 0.25 * 12.0
    if math.isfinite(ir_cosine):
        score += ir_cosine * 22.0
    if math.isfinite(learned_ce):
        score += max(0.0, 3.0 - learned_ce) / 3.0 * 12.0
    if math.isfinite(learned_cosine):
        score += learned_cosine * 16.0
    if math.isfinite(source_text_loss):
        score += max(0.0, 0.2 - source_text_loss) / 0.2 * 7.0
    return round(score, 6)


def _classify_run(row: Mapping[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    cycles = int(_finite_float(row.get("cycles")) or 0)
    score = _finite_float(row.get("score"))
    ir_cosine = max(
        _bounded_metric(row.get("best_validation_ir_cosine")),
        _bounded_metric(row.get("best_validation_ir_guided_cosine")),
    )
    ir_ce = _finite_float(row.get("best_validation_ir_ce"))
    learned_cosine = _bounded_metric(row.get("best_validation_learned_ir_view_cosine"))
    learned_ce = _finite_float(row.get("best_validation_learned_ir_view_ce"))

    state_path = row.get("state_path")
    if state_path and not Path(str(state_path)).exists():
        reasons.append("missing_state_file")
    if cycles <= 0:
        reasons.append("no_completed_training_cycles")
        return "deprecated", reasons
    if not math.isfinite(ir_cosine) or ir_cosine < 0.0:
        reasons.append("compiler_ir_metrics_unset_or_negative")
    if not math.isfinite(ir_ce):
        reasons.append("compiler_ir_cross_entropy_unset")
    if not math.isfinite(learned_cosine) or not math.isfinite(learned_ce):
        reasons.append("learned_legal_ir_view_metrics_unset")
    if cycles < 3:
        reasons.append("too_few_cycles_for_canonical_weight_source")

    if reasons and ("compiler_ir_metrics_unset_or_negative" in reasons or cycles < 3):
        return "deprecated", reasons
    if math.isfinite(score) and score >= 70.0 and cycles >= 10:
        return "canonical_primary", reasons
    if math.isfinite(score) and score >= 57.0 and cycles >= 10:
        return "canonical_support", reasons
    if math.isfinite(score) and score >= 45.0:
        return "reference_only", reasons
    if math.isfinite(score) and score >= 25.0:
        return "archive_reference", reasons
    reasons.append("weak_multiobjective_score")
    return "deprecated", reasons


def _run_rows(test_log_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for summary_path in sorted(test_log_dir.glob("*autoencoder.summary")):
        if "-codex-autoencoder" in summary_path.name:
            continue
        summary = _load_json(summary_path)
        if not summary:
            continue
        row: dict[str, Any] = {
            "run_id": summary.get("run_id") or summary_path.name.removesuffix(".summary"),
            "summary_path": str(summary_path),
            "state_path": summary.get("state_path"),
            "queue_path": summary.get("queue_path"),
            "cycles": summary.get("cycles"),
            "elapsed_seconds": summary.get("elapsed_seconds"),
            "finished_at": summary.get("finished_at"),
            "architecture": summary.get("autoencoder_architecture_version", "legacy_unknown"),
            "state_schema": summary.get("autoencoder_state_schema_version"),
            "metric_schema": summary.get("metric_schema_version"),
            "backend": summary.get("autoencoder_compute_backend"),
            "device": summary.get("autoencoder_compute_device"),
            "cosine_reconstruction_weight": summary.get(
                "autoencoder_cosine_reconstruction_weight"
            ),
            "bridge_loss_adapters": summary.get("bridge_loss_adapters", []),
            "validation_mode": summary.get("validation_mode"),
        }
        for key in METRIC_KEYS:
            row[key] = summary.get(key)
        row["score"] = _score_run(row)
        status, reasons = _classify_run(row)
        row["status"] = status
        row["deprecated"] = status == "deprecated"
        row["deprecation_reasons"] = reasons
        rows.append(row)
    rows.sort(key=lambda item: (_finite_float(item.get("score")), int(item.get("cycles") or 0)), reverse=True)
    return rows


def _source_path(row: Mapping[str, Any]) -> Path:
    return Path(str(row.get("state_path") or ""))


def _source_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    statuses: Iterable[str],
    limit: int,
) -> list[Mapping[str, Any]]:
    selected: list[Mapping[str, Any]] = []
    allowed = set(statuses)
    for row in rows:
        if row.get("status") not in allowed:
            continue
        path = _source_path(row)
        if path.exists():
            selected.append(row)
        if limit > 0 and len(selected) >= limit:
            break
    return selected


def _source_paths(rows: Iterable[Mapping[str, Any]], limit: int) -> list[Path]:
    return [
        _source_path(row)
        for row in _source_rows(
            rows,
            statuses=("canonical_primary", "canonical_support"),
            limit=limit,
        )
    ]


def _source_weight(row: Mapping[str, Any]) -> float:
    """Return a conservative merge weight for one historical run."""
    status_weight = CANONICAL_SOURCE_STATUS_WEIGHTS.get(str(row.get("status")), 0.0)
    score = _finite_float(row.get("score"))
    cycles = _finite_float(row.get("cycles"))
    score_factor = 1.0
    if math.isfinite(score):
        score_factor = max(0.25, min(1.25, score / 70.0))
    cycle_factor = 1.0
    if math.isfinite(cycles):
        cycle_factor = max(0.35, min(1.0, math.log1p(max(0.0, cycles)) / math.log1p(100.0)))
    return round(status_weight * score_factor * cycle_factor, 9)


def _value_score(value: Any) -> float:
    if isinstance(value, Mapping):
        total = 0.0
        for item in value.values():
            number = _finite_float(item)
            if math.isfinite(number):
                total += number * number
        return math.sqrt(total)
    if isinstance(value, list):
        total = 0.0
        for item in value:
            number = _finite_float(item)
            if math.isfinite(number):
                total += number * number
        return math.sqrt(total)
    number = _finite_float(value)
    return abs(number) if math.isfinite(number) else 0.0


def _feature_group(feature_key: str) -> str:
    key = str(feature_key)
    if "||" in key:
        key = key.split("||", 1)[0]
    if ":" in key:
        return key.split(":", 1)[0]
    if "|" in key:
        return key.split("|", 1)[0]
    return key


def _top_map_entries(
    mapping: Mapping[str, Any],
    *,
    per_map_limit: int,
) -> list[tuple[float, str]]:
    scored = ((_value_score(value), str(key)) for key, value in mapping.items())
    return [
        (score, key)
        for score, key in heapq.nlargest(per_map_limit, scored, key=lambda item: item[0])
        if score > 0.0
    ]


def _consensus_features(
    source_rows: Iterable[Mapping[str, Any]],
    *,
    per_map_limit: int,
    output_limit: int,
) -> dict[str, Any]:
    consensus: dict[str, dict[str, Any]] = {}
    map_entry_counts: Counter[str] = Counter()
    feature_group_counts: Counter[str] = Counter()
    source_count = 0
    source_summaries: list[dict[str, Any]] = []

    for row in source_rows:
        state_path = _source_path(row)
        state = _load_json(state_path)
        if not state:
            continue
        source_count += 1
        run_id = state_path.name.removesuffix(".state.json")
        summary: dict[str, Any] = {
            "run_id": run_id,
            "state_path": str(state_path),
            "status": row.get("status"),
            "score": row.get("score"),
            "merge_weight": _source_weight(row),
            "map_entry_counts": {},
        }
        for map_name in GENERALIZABLE_STATE_MAPS:
            mapping = state.get(map_name)
            if not isinstance(mapping, Mapping):
                continue
            summary["map_entry_counts"][map_name] = len(mapping)
            map_entry_counts[map_name] += len(mapping)
            for score, feature_key in _top_map_entries(mapping, per_map_limit=per_map_limit):
                consensus_key = f"{map_name}:{feature_key}"
                item = consensus.setdefault(
                    consensus_key,
                    {
                        "map": map_name,
                        "feature": feature_key,
                        "feature_group": _feature_group(feature_key),
                        "appearance_count": 0,
                        "score_sum": 0.0,
                        "score_max": 0.0,
                        "source_run_ids": [],
                    },
                )
                item["appearance_count"] += 1
                item["score_sum"] += score
                item["score_max"] = max(float(item["score_max"]), score)
                item["source_run_ids"].append(run_id)
                feature_group_counts[f"{map_name}:{item['feature_group']}"] += 1
        source_summaries.append(summary)

    features = sorted(
        consensus.values(),
        key=lambda item: (
            int(item["appearance_count"]),
            float(item["score_sum"]),
            float(item["score_max"]),
            str(item["map"]),
            str(item["feature"]),
        ),
        reverse=True,
    )
    for item in features:
        item["score_sum"] = round(float(item["score_sum"]), 9)
        item["score_max"] = round(float(item["score_max"]), 9)
        item["source_run_ids"] = sorted(set(item["source_run_ids"]))

    return {
        "source_count": source_count,
        "source_summaries": source_summaries,
        "average_map_entry_counts": {
            key: round(value / source_count, 3)
            for key, value in sorted(map_entry_counts.items())
            if source_count
        },
        "top_feature_groups": [
            {"feature_group": key, "count": value}
            for key, value in feature_group_counts.most_common(80)
        ],
        "consensus_features": features[:output_limit],
        "repeat_consensus_features": [
            item for item in features if int(item["appearance_count"]) >= 2
        ][:output_limit],
    }


def _load_distillation(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else {}


def _route_consensus(test_log_dir: Path, rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    selected_run_ids = {
        str(row.get("run_id"))
        for row in rows
        if row.get("status") in {"canonical_primary", "canonical_support", "reference_only"}
    }
    scope_counts: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    target_counts: Counter[str] = Counter()
    gap_counts: Counter[str] = Counter()
    surface_counts: Counter[str] = Counter()

    for run_id in selected_run_ids:
        path = test_log_dir / f"{run_id}.compiler-guidance-distillation.json"
        payload = _load_distillation(path)
        if not payload:
            continue
        scope_hints = payload.get("scope_hints")
        if isinstance(scope_hints, Mapping):
            scope_counts.update(
                {
                    str(key): int(value)
                    for key, value in dict(scope_hints.get("scope_counts") or {}).items()
                    if isinstance(value, int)
                }
            )
            target_counts.update(
                {
                    str(key): int(value)
                    for key, value in dict(scope_hints.get("target_component_counts") or {}).items()
                    if isinstance(value, int)
                }
            )
        for item in payload.get("top_todo_routes") or []:
            if isinstance(item, Mapping):
                route = item.get("route") or item.get("name") or item.get("target")
                count = int(item.get("count") or item.get("weight") or 1)
                if route:
                    route_counts[str(route)] += count
        for item in payload.get("top_legal_ir_view_gaps") or []:
            if isinstance(item, Mapping):
                name = item.get("view") or item.get("name") or item.get("target")
                if name:
                    gap_counts[str(name)] += 1
        for item in payload.get("top_surface_features") or []:
            if isinstance(item, Mapping):
                name = item.get("feature") or item.get("name") or item.get("key")
                if name:
                    surface_counts[str(name)] += 1

    return {
        "scope_counts": dict(scope_counts.most_common()),
        "target_component_counts": dict(target_counts.most_common()),
        "todo_route_counts": dict(route_counts.most_common()),
        "legal_ir_view_gap_counts": dict(gap_counts.most_common()),
        "surface_feature_counts": dict(surface_counts.most_common(80)),
    }


def _write_canonical_state(
    source_rows: list[Mapping[str, Any]],
    output_path: Path,
    *,
    merge_mode: str,
) -> dict[str, Any]:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
        ModalAutoencoderTrainingState,
    )

    source_records: list[dict[str, Any]] = []
    loaded: list[ModalAutoencoderTrainingState] = []
    weighted = ModalAutoencoderTrainingState()
    total_weight = 0.0
    for row in source_rows:
        path = _source_path(row)
        state = ModalAutoencoderTrainingState.load_json(path).generalizable_copy()
        loaded.append(state)
        weight = _source_weight(row)
        if merge_mode == "weighted_union" and weight > 0.0:
            total_weight += weight
            weighted.merge_generalizable_from(state, scale=weight)
        source_records.append(
            {
                "run_id": row.get("run_id"),
                "status": row.get("status"),
                "score": row.get("score"),
                "cycles": row.get("cycles"),
                "architecture": row.get("architecture"),
                "state_schema": row.get("state_schema"),
                "metric_schema": row.get("metric_schema"),
                "backend": row.get("backend"),
                "path": str(path),
                "merge_weight": weight,
            }
        )

    if merge_mode == "weighted_union":
        averaged = ModalAutoencoderTrainingState()
        if total_weight > 0.0:
            averaged.merge_generalizable_from(weighted, scale=1.0 / total_weight)
    else:
        averaged = ModalAutoencoderTrainingState.average_generalizable(loaded)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    averaged.save_json(output_path)
    return {
        "path": str(output_path),
        "source_count": len(loaded),
        "source_paths": [record["path"] for record in source_records],
        "source_records": source_records,
        "merge_mode": merge_mode,
        "total_merge_weight": round(total_weight, 9),
        "compatibility_adapter": (
            "ModalAutoencoderTrainingState.load_json(path).generalizable_copy()"
        ),
        "generalizable_entry_count": averaged.generalizable_entry_count(),
        "size_bytes": output_path.stat().st_size,
    }


def _markdown_report(report: Mapping[str, Any]) -> str:
    rows = list(report["runs"])
    eligible_sources = [
        row
        for row in rows
        if row["status"] in set(report.get("canonical_source_statuses", ()))
    ]
    selected_source_paths = {str(path) for path in report.get("canonical_source_state_paths", [])}
    deprecated = [row for row in rows if row["deprecated"]]

    lines = [
        "# Legal IR Autoencoder Weight Review",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Recommendation",
        "",
    ]
    if report.get("canonical_state"):
        lines.append(
            f"Use `{report['canonical_state']['path']}` as the canonical warm-start state."
        )
    else:
        lines.append("Use the selected canonical source states as warm-start inputs.")
    lines.extend(
        [
            "",
            f"Selected `{len(selected_source_paths)}` of `{len(eligible_sources)}` eligible good states for consensus extraction and canonical averaging.",
            "",
            "The generic validation cosine is not enough to choose weights here; several",
            "runs reached perfect generic validation cosine while compiler-IR metrics were",
            "negative or unset.  The ranking below favors validation CE, compiler IR CE/cosine,",
            "learned LegalIR-view CE/cosine, source/decompiled embedding loss, and completed cycles.",
            "",
            "## Canonical Sources",
            "",
            "| rank | selected | weight | status | score | cycles | backend | val CE | compiler IR CE | compiler IR cosine | learned view CE | learned view cosine | run |",
            "| ---: | --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for index, row in enumerate(eligible_sources, 1):
        selected = "yes" if str(row.get("state_path") or "") in selected_source_paths else "no"
        lines.append(
            "| {rank} | {selected} | {weight:.3f} | {status} | {score:.2f} | {cycles} | {backend} | {val_ce} | {ir_ce} | {ir_cos} | {learned_ce} | {learned_cos} | `{run}` |".format(
                rank=index,
                selected=selected,
                weight=_source_weight(row) if selected == "yes" else 0.0,
                status=row["status"],
                score=float(row["score"]),
                cycles=row.get("cycles"),
                backend=row.get("backend") or "",
                val_ce=_fmt(row.get("best_validation_ce")),
                ir_ce=_fmt(row.get("best_validation_ir_ce")),
                ir_cos=_fmt(row.get("best_validation_ir_cosine")),
                learned_ce=_fmt(row.get("best_validation_learned_ir_view_ce")),
                learned_cos=_fmt(row.get("best_validation_learned_ir_view_cosine")),
                run=row["run_id"],
            )
        )

    lines.extend(["", "## Deprecated Or Non-Canonical Runs", ""])
    lines.append("| status | score | cycles | reason | run |")
    lines.append("| --- | ---: | ---: | --- | --- |")
    for row in deprecated:
        lines.append(
            "| deprecated | {score:.2f} | {cycles} | {reason} | `{run}` |".format(
                score=float(row["score"]),
                cycles=row.get("cycles"),
                reason=", ".join(row.get("deprecation_reasons") or []),
                run=row["run_id"],
            )
        )

    lines.extend(["", "## Shared Feature Signals", ""])
    for item in report["feature_consensus"].get("repeat_consensus_features", [])[:30]:
        lines.append(
            "- `{map}:{feature}` appeared in {count} canonical sources; aggregate score `{score}`.".format(
                map=item["map"],
                feature=item["feature"],
                count=item["appearance_count"],
                score=item["score_sum"],
            )
        )

    lines.extend(["", "## Route Consensus", ""])
    route_consensus = report.get("route_consensus", {})
    for scope, count in list((route_consensus.get("scope_counts") or {}).items())[:12]:
        lines.append(f"- `{scope}`: {count}")

    lines.extend(["", "## Files", ""])
    lines.append(f"- JSON report: `{report['json_report_path']}`")
    lines.append(f"- Deprecation manifest: `{report['deprecation_manifest_path']}`")
    lines.append(f"- Canonical feature manifest: `{report['canonical_manifest_path']}`")
    return "\n".join(lines) + "\n"


def _fmt(value: Any) -> str:
    number = _finite_float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.6g}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--canonical-source-limit",
        type=int,
        default=0,
        help="Maximum good runs to include; 0 means include all eligible good runs.",
    )
    parser.add_argument(
        "--canonical-source-status",
        action="append",
        choices=(
            "canonical_primary",
            "canonical_support",
            "reference_only",
            "archive_reference",
        ),
        default=[],
        help="Status to include in canonical extraction; repeatable.",
    )
    parser.add_argument(
        "--canonical-merge-mode",
        choices=("weighted_union", "equal_average"),
        default="weighted_union",
        help="How to combine compatible historical feature-level states.",
    )
    parser.add_argument("--per-map-feature-limit", type=int, default=250)
    parser.add_argument("--consensus-feature-limit", type=int, default=250)
    parser.add_argument("--write-canonical-state", action="store_true")
    parser.add_argument(
        "--canonical-state-path",
        type=Path,
        default=Path("workspace/todo-queues") / DEFAULT_CANONICAL_STATE_NAME,
    )
    args = parser.parse_args()

    test_log_dir = args.workspace / "test-logs"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = _run_rows(test_log_dir)
    source_statuses = tuple(args.canonical_source_status or DEFAULT_CANONICAL_SOURCE_STATUSES)
    source_rows = _source_rows(
        rows,
        statuses=source_statuses,
        limit=max(0, int(args.canonical_source_limit)),
    )
    source_paths = [_source_path(row) for row in source_rows]
    feature_consensus = _consensus_features(
        source_rows,
        per_map_limit=max(1, args.per_map_feature_limit),
        output_limit=max(1, args.consensus_feature_limit),
    )
    route_consensus = _route_consensus(test_log_dir, rows)

    canonical_state: dict[str, Any] | None = None
    if args.write_canonical_state and source_paths:
        canonical_state = _write_canonical_state(
            source_rows,
            args.canonical_state_path,
            merge_mode=args.canonical_merge_mode,
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_report_path = args.output_dir / "autoencoder_weight_review.latest.json"
    deprecation_manifest_path = args.output_dir / "autoencoder_weight_deprecations.latest.json"
    canonical_manifest_path = args.output_dir / "canonical_autoencoder_features.latest.json"
    markdown_path = args.output_dir / "autoencoder_weight_review.latest.md"

    report: dict[str, Any] = {
        "generated_at": generated_at,
        "policy": {
            "score_name": "multiobjective_validation_compiler_ir_learned_ir_score",
            "canonical_merge_mode": args.canonical_merge_mode,
            "canonical_source_statuses": list(source_statuses),
            "canonical_source_status_weights": CANONICAL_SOURCE_STATUS_WEIGHTS,
            "canonical_primary_min_score": 70.0,
            "canonical_support_min_score": 57.0,
            "deprecated_conditions": [
                "no_completed_training_cycles",
                "compiler_ir_metrics_unset_or_negative",
                "too_few_cycles_for_canonical_weight_source",
                "weak_multiobjective_score",
            ],
        },
        "runs": rows,
        "canonical_source_statuses": list(source_statuses),
        "canonical_source_records": [
            {
                "run_id": row.get("run_id"),
                "status": row.get("status"),
                "score": row.get("score"),
                "cycles": row.get("cycles"),
                "state_path": row.get("state_path"),
                "merge_weight": _source_weight(row),
            }
            for row in source_rows
        ],
        "canonical_source_state_paths": [str(path) for path in source_paths],
        "canonical_state": canonical_state,
        "feature_consensus": feature_consensus,
        "route_consensus": route_consensus,
        "json_report_path": str(json_report_path),
        "deprecation_manifest_path": str(deprecation_manifest_path),
        "canonical_manifest_path": str(canonical_manifest_path),
    }
    deprecation_manifest = {
        "generated_at": generated_at,
        "canonical_replacement_state": canonical_state,
        "canonical_source_statuses": list(source_statuses),
        "canonical_source_state_paths": [str(path) for path in source_paths],
        "runs": [
            {
                "run_id": row["run_id"],
                "status": row["status"],
                "deprecated": row["deprecated"],
                "deprecation_reasons": row.get("deprecation_reasons", []),
                "score": row["score"],
                "cycles": row.get("cycles"),
                "state_path": row.get("state_path"),
                "summary_path": row.get("summary_path"),
            }
            for row in rows
        ],
    }
    canonical_manifest = {
        "generated_at": generated_at,
        "canonical_source_statuses": list(source_statuses),
        "canonical_merge_mode": args.canonical_merge_mode,
        "canonical_source_state_paths": [str(path) for path in source_paths],
        "canonical_source_records": report["canonical_source_records"],
        "canonical_state": canonical_state,
        "feature_consensus": feature_consensus,
        "route_consensus": route_consensus,
    }

    json_report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    deprecation_manifest_path.write_text(
        json.dumps(deprecation_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    canonical_manifest_path.write_text(
        json.dumps(canonical_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")

    print(f"runs={len(rows)}")
    print(f"canonical_sources={len(source_paths)}")
    print(f"deprecated={sum(1 for row in rows if row['deprecated'])}")
    if canonical_state:
        print(f"canonical_state={canonical_state['path']}")
        print(f"canonical_state_size_bytes={canonical_state['size_bytes']}")
    print(f"json_report={json_report_path}")
    print(f"deprecation_manifest={deprecation_manifest_path}")
    print(f"canonical_manifest={canonical_manifest_path}")
    print(f"markdown_report={markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
