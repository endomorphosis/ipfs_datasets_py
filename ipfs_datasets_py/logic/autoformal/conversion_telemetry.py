"""Telemetry for converting span-cache rows into formal logic.

Scores, errors, and the hyperparameters that produced them are one parquet
export. The export is not a legal admit, does not replace the sealed span
cache, and does not write JSONL.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .span_agreement import (
    FAMILY_CROSS_ENTROPY_LIMIT,
    INITIAL_LEARNING_RATE,
    MAX_COMPRESSION_LOSS,
    MAX_LEARNING_RATE,
    MAX_RECONSTRUCTION_LOSS,
    MIN_COSINE_SIMILARITY,
    MIN_LEARNING_RATE,
    RESULT_CROSS_ENTROPY_LIMIT,
    VIEW_CROSS_ENTROPY_LIMIT,
)
from .span_evidence import DEFAULT_REPOSITORY_ID, SpanEvidenceError


TELEMETRY_SCHEMA = "uscode-autoformal-conversion-telemetry/v1"
TELEMETRY_REPO_PATH = "autoformal/uscode/conversion-telemetry.parquet"
_FORBIDDEN_NAMES = {"resume-checkpoint.parquet", "sealed-spans.parquet"}
_METRIC_COLUMNS = (
    "cosine_similarity",
    "cross_entropy_loss",
    "embedding_cosine_loss",
    "embedding_cosine_similarity",
    "family_cross_entropy_loss",
    "formula_cross_entropy_loss",
    "ir_compression_loss",
    "ir_compression_ratio",
    "reconstruction_loss",
    "round_trip_cross_entropy_loss",
    "view_cross_entropy_loss",
)
TELEMETRY_COLUMNS = (
    "schema_version",
    "record_kind",
    "repository_id",
    "source_span_id",
    "source_sha256",
    "legal_id",
    "status",
    "agrees",
    "admitted",
    "formalized",
    "wrote_compiler",
    "compiler_status",
    "compiler_reason",
    "repair_error",
    "lake_ok",
    "lake_disposition",
    "train",
    *_METRIC_COLUMNS,
    "learning_rate",
    "epochs",
    "rounds",
    "seed",
    "hyperparameters_json",
    "history_json",
    "error_json",
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def default_hyperparameters(**overrides: Any) -> dict[str, Any]:
    """The training gates and step schedule used to judge a conversion.

    Callers may override a key. Unknown keys are refused so a receipt cannot
    smuggle an authority flag.
    """

    values: dict[str, Any] = {
        "bridge_names": ["modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec"],
        "epochs": 1,
        "family_cross_entropy_limit": FAMILY_CROSS_ENTROPY_LIMIT,
        "holdout_fraction": 0.25,
        "learning_rate_decay": 0.5,
        "learning_rate_growth": 1.1,
        "learning_rate_initial": INITIAL_LEARNING_RATE,
        "learning_rate_max": MAX_LEARNING_RATE,
        "learning_rate_min": MIN_LEARNING_RATE,
        "max_ir_compression_loss": MAX_COMPRESSION_LOSS,
        "max_reconstruction_loss": MAX_RECONSTRUCTION_LOSS,
        "min_cosine_similarity": MIN_COSINE_SIMILARITY,
        "projection_max_update_families": 4,
        "result_cross_entropy_limit": RESULT_CROSS_ENTROPY_LIMIT,
        "rounds": 0,
        "seed": 0,
        "temperature": 0,
        "training_bridges": ["modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec"],
        "training_families": ["fol", "deontic", "tfol", "tdfol", "cec", "frame_logic"],
        "view_cross_entropy_limit": VIEW_CROSS_ENTROPY_LIMIT,
    }
    unknown = sorted(set(overrides) - set(values))
    if unknown:
        raise SpanEvidenceError("unknown telemetry hyperparameter: " + ", ".join(unknown))
    for key, value in overrides.items():
        values[key] = value
    return values


def _history(training: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for item in list((training or {}).get("history") or [])[:16]:
        if not isinstance(item, Mapping):
            continue
        scores = item.get("scores") if isinstance(item.get("scores"), Mapping) else {}
        threshold = item.get("threshold") if isinstance(item.get("threshold"), Mapping) else {}
        steps.append(
            {
                "below_threshold": [str(name) for name in item.get("below_threshold") or []][:8],
                "cosine_similarity": _number(scores.get("cosine_similarity")),
                "cross_entropy_loss": _number(scores.get("cross_entropy_loss")),
                "learning_rate": _number(item.get("learning_rate")),
                "movement": str(item.get("movement") or ""),
                "reconstruction_loss": _number(scores.get("reconstruction_loss")),
                "threshold_cosine_similarity": _number(threshold.get("cosine_similarity")),
                "threshold_cross_entropy_loss": _number(threshold.get("cross_entropy_loss")),
                "threshold_reconstruction_loss": _number(threshold.get("reconstruction_loss")),
            }
        )
    return steps


def _mean(values: Sequence[float | None]) -> float | None:
    numbers = [value for value in values if value is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def conversion_telemetry_rows(
    evidence_rows: Sequence[Mapping[str, Any]],
    *,
    hyperparameters: Mapping[str, Any] | None = None,
    training: Mapping[str, Any] | None = None,
    repository_id: str = DEFAULT_REPOSITORY_ID,
) -> list[dict[str, Any]]:
    """One span row plus one run row. Null scores stay null."""

    params = default_hyperparameters(**dict(hyperparameters or {}))
    if isinstance(training, Mapping):
        if training.get("seed") is not None:
            params["seed"] = int(training.get("seed") or 0)
        params["rounds"] = int(training.get("rounds") or 0)
    history = _history(training)
    rate = _number(history[-1]["learning_rate"]) if history else _number(params["learning_rate_initial"])
    params_json = _json(params)
    history_json = _json(history)
    rows: list[dict[str, Any]] = []
    for item in evidence_rows:
        if not isinstance(item, Mapping):
            continue
        error = {
            "compiler_fields": str(item.get("compiler_fields_json") or ""),
            "compiler_reason": str(item.get("compiler_reason") or "")[:240],
            "lake_disposition": str(item.get("lake_disposition") or ""),
            "repair_error": str(item.get("repair_error") or "")[:240],
            "repair_fix": str(item.get("repair_fix") or "")[:240],
        }
        row = {
            "admitted": False,
            "agrees": item.get("agrees") is True,
            "compiler_reason": error["compiler_reason"],
            "compiler_status": str(item.get("compiler_status") or ""),
            "epochs": int(params["epochs"]),
            "error_json": _json(error),
            "formalized": False,
            "history_json": history_json,
            "hyperparameters_json": params_json,
            "lake_disposition": error["lake_disposition"],
            "lake_ok": item.get("lake_ok") is True if item.get("lake_ok") is not None else None,
            "learning_rate": rate,
            "legal_id": str(item.get("legal_id") or ""),
            "record_kind": "span",
            "repair_error": error["repair_error"],
            "repository_id": repository_id,
            "rounds": int(params["rounds"]),
            "schema_version": TELEMETRY_SCHEMA,
            "seed": int(params["seed"]),
            "source_sha256": str(item.get("source_sha256") or ""),
            "source_span_id": str(item.get("source_span_id") or ""),
            "status": str(item.get("status") or ""),
            "train": item.get("train") is True,
            "wrote_compiler": False,
        }
        for name in _METRIC_COLUMNS:
            row[name] = _number(item.get(name))
        rows.append(row)
    summary: dict[str, Any] = {
        "admitted": False,
        "agrees": bool(rows) and all(row["agrees"] for row in rows),
        "compiler_reason": "",
        "compiler_status": "",
        "epochs": int(params["epochs"]),
        "error_json": _json(
            {
                "gap_count": sum(1 for row in rows if row["status"] == "gap"),
                "span_count": len(rows),
            }
        ),
        "formalized": False,
        "history_json": history_json,
        "hyperparameters_json": params_json,
        "lake_disposition": "",
        "lake_ok": None,
        "learning_rate": rate,
        "legal_id": "",
        "record_kind": "run",
        "repair_error": "",
        "repository_id": repository_id,
        "rounds": int(params["rounds"]),
        "schema_version": TELEMETRY_SCHEMA,
        "seed": int(params["seed"]),
        "source_sha256": "",
        "source_span_id": "",
        "status": "run",
        "train": any(row["train"] for row in rows),
        "wrote_compiler": False,
    }
    for name in _METRIC_COLUMNS:
        summary[name] = _mean([row[name] for row in rows])
    rows.append(summary)
    return rows


def telemetry_schema():
    import pyarrow as pa

    floats = set(_METRIC_COLUMNS) | {"learning_rate"}
    bools = {"admitted", "agrees", "formalized", "train", "wrote_compiler"}
    ints = {"epochs", "rounds", "seed"}
    fields = []
    for name in TELEMETRY_COLUMNS:
        if name in floats:
            fields.append(pa.field(name, pa.float64()))
        elif name == "lake_ok":
            fields.append(pa.field(name, pa.bool_()))
        elif name in bools:
            fields.append(pa.field(name, pa.bool_()))
        elif name in ints:
            fields.append(pa.field(name, pa.int32()))
        else:
            fields.append(pa.field(name, pa.string()))
    return pa.schema(fields)


def write_conversion_telemetry(
    rows: Sequence[Mapping[str, Any]],
    path: str | Path,
) -> dict[str, Any]:
    """Write conversion telemetry. Refuses the sealed span cache and resume checkpoint."""

    import pyarrow as pa
    import pyarrow.parquet as pq

    destination = Path(path)
    if destination.name in _FORBIDDEN_NAMES:
        raise SpanEvidenceError("conversion telemetry must not replace " + destination.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    projected = [dict(row) for row in rows]
    missing = [name for name in TELEMETRY_COLUMNS if projected and name not in projected[0]]
    if missing:
        raise SpanEvidenceError("telemetry row is missing " + ", ".join(missing))
    table = pa.Table.from_pylist(projected, schema=telemetry_schema()) if projected else pa.Table.from_pylist(
        [], schema=telemetry_schema()
    )
    pq.write_table(table, destination)
    payload = destination.read_bytes()
    return {
        "admitted": False,
        "bytes": len(payload),
        "formalized": False,
        "jsonl_written": False,
        "path": str(destination),
        "row_count": table.num_rows,
        "schema_version": TELEMETRY_SCHEMA,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def publish_conversion_telemetry(
    path: str | Path,
    *,
    upload: bool = False,
    repository_id: str = DEFAULT_REPOSITORY_ID,
    path_in_repo: str = TELEMETRY_REPO_PATH,
    api: Any | None = None,
) -> dict[str, Any]:
    """Upload telemetry to the span-cache dataset. Dry-run does not contact Hugging Face."""

    source = Path(path)
    if Path(path_in_repo).name in _FORBIDDEN_NAMES or source.name in _FORBIDDEN_NAMES:
        raise SpanEvidenceError("conversion telemetry must not replace the sealed span cache")
    receipt = {
        "admitted": False,
        "dry_run": not upload,
        "formalized": False,
        "jsonl_written": False,
        "path_in_repo": path_in_repo,
        "repository_id": repository_id,
        "uploaded": False,
    }
    if not upload:
        return receipt
    if api is None:
        from huggingface_hub import HfApi

        api = HfApi()
    api.create_repo(repository_id, repo_type="dataset", exist_ok=True)
    commit = api.upload_file(
        path_or_fileobj=str(source),
        path_in_repo=path_in_repo,
        repo_id=repository_id,
        repo_type="dataset",
        commit_message="autoformal conversion telemetry",
    )
    receipt["uploaded"] = True
    receipt["dry_run"] = False
    receipt["commit"] = str(getattr(commit, "commit_url", "") or getattr(commit, "oid", "") or "")
    return receipt
