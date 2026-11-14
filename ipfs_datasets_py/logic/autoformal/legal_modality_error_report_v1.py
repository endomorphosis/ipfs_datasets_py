"""Report modality errors without promoting a failed acceptance.

Presence errors, owner errors, and critical modality reversals stay in
separate lists. A failed acceptance stays failed when the aggregate gain is
positive. The producer packet is written before a separate post-freeze
evaluation packet and receives no evaluation reference. This module does not
train, execute a model, or accept law.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "legal-modality-error-report/v1"
ERROR_KINDS = ("presence", "owner", "critical_modality_reversal")
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


class ModalityErrorReportError(ValueError):
    """An error report merged kinds, cleared a failure, or shared a reference."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ModalityErrorReportError(message)


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ModalityErrorReportError("finite JSON error report required") from error
    _need(len(encoded) <= 1_000_000, "error report byte bound exceeded")
    return encoded + b"\n"


def _root(root: Path) -> Path:
    _need(isinstance(root, Path) and root.is_dir() and not root.is_symlink(), "real report directory required")
    return root


def report_separated_errors(rows: list[dict[str, str]]) -> dict[str, object]:
    """Keep the three error kinds in separate lists."""

    _need(type(rows) is list and 1 <= len(rows) <= 32, "bounded error rows required")
    buckets = {kind: [] for kind in ERROR_KINDS}
    seen: set[str] = set()
    for row in rows:
        _need(type(row) is dict and set(row) == {"id", "kind"}, "closed error row required")
        identifier = row["id"]
        kind = row["kind"]
        _need(
            type(identifier) is str and identifier.strip() == identifier and bool(identifier),
            "closed error row required",
        )
        _need(identifier not in seen, "duplicate error id")
        seen.add(identifier)
        _need(kind in ERROR_KINDS, "error kind is not separate")
        buckets[kind].append(identifier)
    return {
        "schema": SCHEMA,
        "presence_errors": buckets["presence"],
        "owner_errors": buckets["owner"],
        "critical_modality_reversals": buckets["critical_modality_reversal"],
        "presence_owner_reversal_separated": True,
        "authored_fixture_only": True,
        "federal_corpus_scored": False,
        "model_executed": False,
        "training_executed": False,
        "legal_meaning_established": False,
        "legal_acceptance_claimed": False,
        "admitted": False,
        "formalized": False,
    }


def retain_failed_acceptance(
    acceptance_failed: bool,
    aggregate_gain: int,
    *,
    promote_default: bool = False,
    promote_teacher: bool = False,
) -> dict[str, object]:
    """Keep a failed acceptance failed. Promotion is refused."""

    _need(promote_default is False and promote_teacher is False, "automatic default or teacher promotion refused")
    _need(type(acceptance_failed) is bool, "acceptance flag required")
    _need(type(aggregate_gain) is int and aggregate_gain >= 0, "aggregate gain required")
    return {
        "schema": SCHEMA,
        "acceptance_failed": acceptance_failed,
        "aggregate_gain": aggregate_gain,
        "aggregate_gains_clear_failure": False,
        "default_promoted": False,
        "teacher_promoted": False,
        "training_executed": False,
        "legal_acceptance_claimed": False,
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
            raise ModalityErrorReportError("producer packet grants evaluation reference access")
    producer = _packet_rows(producer_rows, frozenset({"id", "observation"}), "producer")
    for row in producer:
        _need(not _FORBIDDEN_PRODUCER_KEYS.intersection(row), "producer packet grants evaluation reference access")
    evaluation = _packet_rows(
        evaluation_rows,
        frozenset({"id", "observation", "evaluation_reference"}),
        "evaluation",
    )
    producer_body = {
        "schema": SCHEMA,
        "owner": PRODUCER_OWNER,
        "rows": producer,
        "evaluation_reference_access": False,
        "training_executed": False,
        "default_promoted": False,
        "teacher_promoted": False,
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
