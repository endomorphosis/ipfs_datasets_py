"""Report training metrics without running training or scoring statutory fidelity.

Ordinary generation, full rules, argument/attachment/modality, and protected
retention stay in separate engineering records. Teacher-forced cross-entropy
and compiler weak-label scores stay separate from reviewed statutory fidelity.
Outputs freeze before those scores are attached. The producer packet is
written before a separate post-freeze evaluation packet and receives no
evaluation reference. This module does not train, unfreeze an encoder, or
accept law.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "legal-training-metric-report/v1"
METRIC_GROUPS = (
    "ordinary_generation",
    "full_rules",
    "argument_attachment_modality",
    "protected_retention",
)
PRODUCER_NAME = "producer-packet.json"
EVALUATION_NAME = "evaluation-packet.json"
PRODUCER_OWNER = "primary-training-inference"
EVALUATION_OWNER = "post-freeze-evaluation"
_FORBIDDEN_PRODUCER_KEYS = frozenset({
    "evaluation_reference",
    "evaluation_gold",
    "gold",
    "reference_text",
    "statutory_fidelity",
})


class TrainingMetricReportError(ValueError):
    """A metric report merged groups, scored early, or shared a reference."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise TrainingMetricReportError(message)


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise TrainingMetricReportError("finite JSON metric report required") from error
    _need(len(encoded) <= 1_000_000, "metric report byte bound exceeded")
    return encoded + b"\n"


def _root(root: Path) -> Path:
    _need(isinstance(root, Path) and root.is_dir() and not root.is_symlink(), "real report directory required")
    return root


def _closed_text(value: object, message: str) -> str:
    _need(type(value) is str and value.strip() == value and bool(value), message)
    return value


def report_metric_groups(rows: list[dict[str, str]]) -> dict[str, object]:
    """Keep the four engineering metric groups in separate lists."""

    _need(type(rows) is list and 1 <= len(rows) <= 32, "bounded metric rows required")
    buckets = {group: [] for group in METRIC_GROUPS}
    seen: set[str] = set()
    for row in rows:
        _need(type(row) is dict and set(row) == {"group", "id"}, "closed metric row required")
        identifier = _closed_text(row["id"], "closed metric row required")
        group = row["group"]
        _need(identifier not in seen, "duplicate metric id")
        seen.add(identifier)
        _need(group in METRIC_GROUPS, "metric group is not reported")
        buckets[group].append(identifier)
    return {
        "schema": SCHEMA,
        "ordinary_generation": buckets["ordinary_generation"],
        "full_rules": buckets["full_rules"],
        "argument_attachment_modality": buckets["argument_attachment_modality"],
        "protected_retention": buckets["protected_retention"],
        "metric_groups_separated": True,
        "authored_fixture_only": True,
        "federal_corpus_scored": False,
        "statutory_fidelity_reviewed": False,
        "model_executed": False,
        "training_executed": False,
        "worker_launched": False,
        "encoder_unfrozen": False,
        "legal_meaning_established": False,
        "legal_acceptance_claimed": False,
        "admitted": False,
        "formalized": False,
    }


def freeze_output(output_id: str, output_text: str) -> dict[str, object]:
    """Seal an output before any engineering score is attached."""

    return {
        "schema": SCHEMA,
        "output_id": _closed_text(output_id, "frozen output required"),
        "output_text": _closed_text(output_text, "frozen output required"),
        "frozen": True,
        "scored": False,
        "statutory_fidelity_reviewed": False,
        "training_executed": False,
        "admitted": False,
        "formalized": False,
    }


def attach_engineering_scores(
    frozen: dict[str, object],
    *,
    teacher_forced_ce: str,
    compiler_weak_label: str,
    statutory_fidelity: str | None = None,
) -> dict[str, object]:
    """Attach engineering scores beside a frozen output, not inside it."""

    _need(statutory_fidelity is None, "statutory fidelity is not an engineering score")
    _need(
        type(frozen) is dict and frozen.get("frozen") is True and frozen.get("scored") is False,
        "outputs must freeze before scoring",
    )
    _closed_text(teacher_forced_ce, "engineering score required")
    _closed_text(compiler_weak_label, "engineering score required")
    output_id = frozen.get("output_id")
    _need(type(output_id) is str and bool(output_id), "frozen output required")
    return {
        "schema": SCHEMA,
        "output_id": output_id,
        "frozen_output_unscored": True,
        "teacher_forced_ce_separate": True,
        "compiler_weak_label_separate": True,
        "engineering_scores_separate": True,
        "engineering_scores_are_statutory_fidelity": False,
        "statutory_fidelity_reviewed": False,
        "training_executed": False,
        "admitted": False,
        "formalized": False,
    }


def materialize_separated_packets(
    root: Path,
    producer_rows: list[dict[str, str]],
    evaluation_rows: list[dict[str, str]],
) -> dict[str, object]:
    """Write the producer packet, then a separate post-freeze evaluation packet."""

    directory = _root(root)
    producer_path = directory / PRODUCER_NAME
    evaluation_path = directory / EVALUATION_NAME
    _need(not producer_path.exists() and not evaluation_path.exists(), "packets already materialized")
    _need(type(producer_rows) is list, "producer rows required")
    for row in producer_rows:
        if type(row) is dict and _FORBIDDEN_PRODUCER_KEYS.intersection(row):
            raise TrainingMetricReportError("producer packet grants evaluation reference access")
    producer = _packet_rows(producer_rows, frozenset({"id", "observation"}), "producer")
    evaluation = _packet_rows(
        evaluation_rows,
        frozenset({"evaluation_reference", "id", "observation"}),
        "evaluation",
    )
    producer_body = {
        "schema": SCHEMA,
        "owner": PRODUCER_OWNER,
        "rows": producer,
        "evaluation_reference_access": False,
        "training_executed": False,
        "encoder_unfrozen": False,
        "worker_launched": False,
    }
    producer_path.write_bytes(_canonical(producer_body))
    _need(producer_path.is_file() and not producer_path.is_symlink(), "producer packet was not written")
    evaluation_body = {
        "schema": SCHEMA,
        "owner": EVALUATION_OWNER,
        "rows": evaluation,
        "frozen_after_producer": True,
        "training_executed": False,
    }
    evaluation_path.write_bytes(_canonical(evaluation_body))
    return {
        "schema": SCHEMA,
        "producer_owner": PRODUCER_OWNER,
        "evaluation_owner": EVALUATION_OWNER,
        "producer_written_before_evaluation": True,
        "separate_packet_owners": PRODUCER_OWNER != EVALUATION_OWNER,
        "producer_evaluation_reference_access": False,
        "training_executed": False,
        "legal_acceptance_claimed": False,
        "admitted": False,
        "formalized": False,
    }


def _packet_rows(rows: object, keys: frozenset[str], label: str) -> list[dict[str, str]]:
    _need(type(rows) is list and 1 <= len(rows) <= 32, label + " rows required")
    sealed: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        _need(type(row) is dict and set(row) == keys, label + " row required")
        sealed_row = {key: row[key] for key in sorted(keys)}
        for value in sealed_row.values():
            _need(type(value) is str and value.strip() == value and bool(value), label + " row required")
        _need(sealed_row["id"] not in seen, "duplicate " + label + " id")
        seen.add(sealed_row["id"])
        sealed.append(sealed_row)
    return sealed
