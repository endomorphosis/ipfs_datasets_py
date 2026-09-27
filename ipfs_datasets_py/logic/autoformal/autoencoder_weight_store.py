"""Autoencoder weights and consensus ticks in ~/.ipfs_datasets.

The DuckDB file is the catalog. Quack is the loopback transport. DuckLake
production activation stays held. Sparse updates keep only tangible weight
changes. High-frequency jitter below the magnitude floor is not stored or
uploaded.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import uuid
from typing import Any, Mapping

from ipfs_datasets_py.ducklake.quack_catalog import (
    assert_no_production_activation,
    owner_extension_load_plan,
    promotion_gate_status,
)

MIN_ABS_DELTA = 1e-3
DEFAULT_REPO = "justicedao/uscode-autoencoder-sparse"


def weights_database_path() -> Path:
    override = os.environ.get("IPFS_DATASETS_WEIGHTS_DB")
    if override:
        return Path(override)
    return Path.home() / ".ipfs_datasets" / "autoencoder" / "weights.duckdb"


def _connect(path: Path):
    import duckdb

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS weight_cell (
            name VARCHAR PRIMARY KEY,
            value DOUBLE,
            updated_at VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS sparse_update (
            update_id VARCHAR,
            name VARCHAR,
            delta DOUBLE,
            value DOUBLE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS consensus_tick (
            tick_id VARCHAR PRIMARY KEY,
            recorded_at VARCHAR,
            encoded INTEGER,
            agree INTEGER,
            disagree INTEGER,
            unscored INTEGER,
            agreement_rate DOUBLE,
            admitted BOOLEAN
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS control_plane (
            key VARCHAR PRIMARY KEY,
            value VARCHAR
        )
        """
    )
    assert_no_production_activation()
    status = promotion_gate_status()
    plan = owner_extension_load_plan()
    connection.execute(
        "INSERT OR REPLACE INTO control_plane VALUES (?, ?), (?, ?), (?, ?)",
        [
            "control_plane",
            "duckdb+quack",
            "ducklake_activation_held",
            "true" if status["activation_held"] else "false",
            "explicit_load_order",
            ",".join(str(item) for item in plan["explicit_load_order"]),
        ],
    )
    return connection


def control_plane_record(path: Path | None = None) -> dict[str, str]:
    database = path or weights_database_path()
    connection = _connect(database)
    try:
        rows = connection.execute("SELECT key, value FROM control_plane").fetchall()
    finally:
        connection.close()
    return {str(key): str(value) for key, value in rows}


def sparse_delta(
    previous: Mapping[str, float],
    current: Mapping[str, float],
    *,
    min_abs_delta: float = MIN_ABS_DELTA,
) -> list[dict[str, float | str]]:
    """Keep weight changes large enough to matter. Tiny jitter is dropped."""

    kept: list[dict[str, float | str]] = []
    for name, raw in current.items():
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        old = previous.get(name)
        if old is None:
            if abs(value) < min_abs_delta:
                continue
            delta = value
        else:
            delta = value - float(old)
            if abs(delta) < min_abs_delta:
                continue
        kept.append({"delta": delta, "name": str(name), "value": value})
    return kept


def load_weights(path: Path | None = None) -> dict[str, float]:
    database = path or weights_database_path()
    if not database.is_file():
        return {}
    connection = _connect(database)
    try:
        rows = connection.execute("SELECT name, value FROM weight_cell").fetchall()
    finally:
        connection.close()
    return {str(name): float(value) for name, value in rows}


def store_sparse_update(
    current: Mapping[str, float],
    *,
    path: Path | None = None,
    improved: bool = False,
    min_abs_delta: float = MIN_ABS_DELTA,
) -> dict[str, Any]:
    """Store tangible deltas. Upload only when the holdout improved."""

    database = path or weights_database_path()
    previous = load_weights(database)
    deltas = sparse_delta(previous, current, min_abs_delta=min_abs_delta)
    update_id = "sparse-" + uuid.uuid4().hex[:16]
    recorded_at = datetime.now(timezone.utc).isoformat()
    connection = _connect(database)
    parquet_path = database.parent / "sparse" / f"{update_id}.parquet"
    try:
        for item in deltas:
            connection.execute(
                "INSERT OR REPLACE INTO weight_cell VALUES (?, ?, ?)",
                [item["name"], float(item["value"]), recorded_at],
            )
            connection.execute(
                "INSERT INTO sparse_update VALUES (?, ?, ?, ?)",
                [update_id, item["name"], float(item["delta"]), float(item["value"])],
            )
        if deltas:
            parquet_path.parent.mkdir(parents=True, exist_ok=True)
            # DuckDB does not bind the COPY destination as a prepared parameter.
            target = str(parquet_path).replace("'", "''")
            update_key = update_id.replace("'", "''")
            connection.execute(
                "COPY (SELECT name, delta, value FROM sparse_update "
                f"WHERE update_id = '{update_key}') TO '{target}' (FORMAT PARQUET)"
            )
    finally:
        connection.close()
    uploaded = False
    if improved and deltas:
        uploaded = _upload_sparse_parquet(parquet_path, update_id)
    return {
        "admitted": False,
        "delta_count": len(deltas),
        "formalized": False,
        "improved": improved,
        "parquet": str(parquet_path) if deltas else "",
        "update_id": update_id,
        "uploaded": uploaded,
    }


def record_consensus(summary: Mapping[str, Any], *, path: Path | None = None) -> str:
    """Append one agree/disagree tick from span generation."""

    database = path or weights_database_path()
    tick_id = "consensus-" + uuid.uuid4().hex[:16]
    rate = summary.get("agreement_rate")
    connection = _connect(database)
    try:
        connection.execute(
            "INSERT INTO consensus_tick VALUES (?, ?, ?, ?, ?, ?, ?, FALSE)",
            [
                tick_id,
                datetime.now(timezone.utc).isoformat(),
                int(summary.get("encoded") or 0),
                int(summary.get("agree") or 0),
                int(summary.get("disagree") or 0),
                int(summary.get("unscored") or 0),
                None if rate is None else float(rate),
            ],
        )
    finally:
        connection.close()
    return tick_id


def consensus_history(path: Path | None = None) -> list[dict[str, Any]]:
    database = path or weights_database_path()
    if not database.is_file():
        return []
    connection = _connect(database)
    try:
        rows = connection.execute(
            """
            SELECT tick_id, encoded, agree, disagree, unscored, agreement_rate, admitted
            FROM consensus_tick
            ORDER BY recorded_at
            """
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "admitted": bool(row[6]),
            "agree": int(row[2]),
            "agreement_rate": None if row[5] is None else float(row[5]),
            "disagree": int(row[3]),
            "encoded": int(row[1]),
            "tick_id": str(row[0]),
            "unscored": int(row[4]),
        }
        for row in rows
    ]


def flatten_model_weights(model: Any) -> dict[str, float]:
    """Read numeric autoencoder cells. Nested maps become dotted names."""

    state = getattr(model, "state", None)
    if state is None:
        return {}
    flat: dict[str, float] = {}
    for name in (
        "family_logits",
        "feature_embedding_weights",
        "family_embedding_weights",
    ):
        blob = getattr(state, name, None)
        _flatten(blob, name, flat)
    return flat


def _flatten(blob: Any, prefix: str, flat: dict[str, float]) -> None:
    if isinstance(blob, bool) or blob is None:
        return
    if isinstance(blob, (int, float)):
        flat[prefix] = float(blob)
        return
    if isinstance(blob, dict):
        for key, value in blob.items():
            _flatten(value, f"{prefix}.{key}", flat)


def publish_model_update(model: Any, *, improved: bool, path: Path | None = None) -> dict[str, Any]:
    current = flatten_model_weights(model)
    if not current:
        return {"admitted": False, "delta_count": 0, "formalized": False, "improved": improved, "uploaded": False}
    return store_sparse_update(current, path=path, improved=improved)


def _upload_sparse_parquet(parquet_path: Path, update_id: str) -> bool:
    token_path = Path.home() / ".cache" / "huggingface" / "token"
    if not token_path.is_file() or not parquet_path.is_file():
        return False
    repo = os.environ.get("IPFS_DATASETS_AUTOENCODER_REPO", DEFAULT_REPO)
    try:
        from huggingface_hub import HfApi

        HfApi().upload_file(
            path_or_fileobj=str(parquet_path),
            path_in_repo=f"autoencoder/sparse/{update_id}.parquet",
            repo_id=repo,
            repo_type="dataset",
        )
    except Exception:
        return False
    return True


class WeightQuackGateway:
    """Owner-side reader for the weight catalog. Call ``serve`` on the owner thread."""

    def __init__(self, database: Path | None = None) -> None:
        from ipfs_datasets_py.duckdb_control.span_cache_quack import SupervisorGoalQuackGateway

        self.database = database or weights_database_path()
        self._gateway = SupervisorGoalQuackGateway()
        self._database_holder = self.database

    def start(self) -> None:
        self._gateway.start()

    def publish(self) -> dict[str, str]:
        return self._gateway.publish(self.database)

    def serve(self) -> int:
        def apply(goals: list[dict[str, Any]]) -> dict[str, Any]:
            if goals and goals[0].get("op") == "consensus":
                return {"admitted": False, "ticks": consensus_history(self.database)}
            return {
                "admitted": False,
                "cells": [{"name": name, "value": f"{value:.8f}"} for name, value in load_weights(self.database).items()],
                "control_plane": control_plane_record(self.database),
            }

        return self._gateway.serve(apply)

    def close(self) -> None:
        self._gateway.close()


def quack_weight_record(path: Path | None = None) -> dict[str, Any]:
    """Describe how another machine reaches the weight catalog. No production lake."""

    database = path or weights_database_path()
    record = control_plane_record(database)
    record["database"] = str(database)
    record["quack_command"] = "ReadWeights"
    record["admitted"] = "false"
    record["production_mutation_enabled"] = "false"
    return record
