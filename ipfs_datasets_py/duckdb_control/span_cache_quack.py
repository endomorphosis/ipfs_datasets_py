"""Read federal span gaps through the catalog owner.

The owner process is the only client of the span-cache DuckDB file. This
module serves an allowlisted ListSpanGaps command on a transient loopback
Quack endpoint. Callers never open the catalog file. DuckLake production
activation stays held; the gateway does not load DuckLake or mutate a lake.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import threading
import uuid
from typing import Any, Mapping

from ipfs_datasets_py.duckdb_control.autoencoder_quack import (
    RegistryTransportClient,
    RegistryTransportError,
    _TransientQuackGateway,
)
from ipfs_datasets_py.duckdb_control.autoencoder_quack_wire import (
    SCHEMA,
    QuackWireError,
    _request as encode_request,
    parse_request,
)
from ipfs_datasets_py.ducklake.quack_catalog import (
    assert_no_production_activation,
    owner_extension_load_plan,
    promotion_gate_status,
)


COMMAND = "ListSpanGaps"
GOAL_COMMAND = "UpsertFailureGoals"
_MAX_LIMIT = 32
_REPLY_BUDGET = 100_000


class SpanCacheQuackError(RegistryTransportError):
    """The span owner did not serve a gap page."""


def handoff_paths(cache_path: str | Path) -> tuple[Path, Path]:
    """Endpoint descriptor and bearer token beside the catalog file."""

    base = Path(cache_path)
    return Path(str(base) + ".quack.json"), Path(str(base) + ".quack.token")


def _ducklake_plane() -> dict[str, Any]:
    """DuckDB remains the catalog. DuckLake stays behind the promotion gates."""

    assert_no_production_activation()
    status = promotion_gate_status()
    plan = owner_extension_load_plan()
    return {
        "activation_held": bool(status["activation_held"]),
        "control_plane": "duckdb+quack",
        "explicit_load_order": [str(item) for item in plan["explicit_load_order"]],
        "held_by": [str(item) for item in status["held_by"]],
        "loaded_extensions": ["quack", "httpfs"],
        "production_mutation_enabled": False,
        "quack_is_transport_only": True,
    }


def _page(cache: Any, *, limit: int, after: str) -> dict[str, Any]:
    rows = list(cache.list_gaps(limit=limit, after=after))
    selected: list[dict[str, str]] = []
    skipped = ""
    for row in rows:
        trial = selected + [row]
        body = _body(trial, skipped="")
        if len(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")) <= _REPLY_BUDGET:
            selected = trial
            continue
        if not selected:
            skipped = str(row.get("source_span_id") or "")
        break
    return _body(selected, skipped=skipped)


def _body(rows: list[dict[str, str]], *, skipped: str) -> dict[str, Any]:
    return {
        "admitted": False,
        "control_plane": _ducklake_plane(),
        "formalized": False,
        "gaps": rows,
        "opens_catalog_file": False,
        "skipped_source_span_id": skipped,
        "wrote_compiler": False,
    }


class SpanCacheQuackGateway(_TransientQuackGateway):
    """Owner-side gap server. ``serve`` runs on the catalog thread."""

    def __init__(self) -> None:
        self._requests: queue.Queue[dict[str, Any]] = queue.Queue()
        self._handoff: tuple[Path, Path] | None = None
        super().__init__()

    def _before_start(self) -> None:
        return None

    def dispatch(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        request = parse_request(encode_request(dict(envelope)))
        if request["command"] != COMMAND:
            raise SpanCacheQuackError("command is outside the span cache vocabulary")
        payload = request["payload"]
        if not isinstance(payload, dict) or set(payload) - {"limit", "after"}:
            raise SpanCacheQuackError("payload does not match the closed command schema")
        limit = payload.get("limit", 16)
        after = payload.get("after", "")
        if type(limit) is not int or isinstance(limit, bool) or not 1 <= limit <= _MAX_LIMIT:
            raise SpanCacheQuackError("limit must be 1..32")
        if type(after) is not str or len(after) > 512:
            raise SpanCacheQuackError("after must be a short string")
        item: dict[str, Any] = {
            "after": after,
            "error": None,
            "event": threading.Event(),
            "limit": limit,
            "result": None,
        }
        self._requests.put(item)
        if not item["event"].wait(55):
            raise SpanCacheQuackError("span owner did not answer")
        if item["error"]:
            raise SpanCacheQuackError(str(item["error"]))
        result = item["result"]
        if not isinstance(result, dict):
            raise SpanCacheQuackError("span owner returned no page")
        return result

    def serve(self, cache: Any) -> int:
        """Answer queued reads on the catalog owner thread."""

        served = 0
        while True:
            try:
                item = self._requests.get_nowait()
            except queue.Empty:
                return served
            try:
                item["result"] = _page(cache, limit=int(item["limit"]), after=str(item["after"]))
            except Exception:
                item["error"] = "span owner could not read gaps"
            finally:
                item["event"].set()
            served += 1

    def publish(self, cache_path: str | Path) -> dict[str, str]:
        """Write the loopback endpoint. The token file is not logged."""

        if self._server is None:
            raise SpanCacheQuackError("gateway is not started")
        params = self.connection_parameters()
        endpoint_path, token_path = handoff_paths(cache_path)
        endpoint_path.write_text(
            json.dumps(
                {
                    "admitted": False,
                    "endpoint": params["endpoint"],
                    "formalized": False,
                    "schema": SCHEMA,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        token_path.write_text(params["token"] + "\n", encoding="utf-8")
        os.chmod(token_path, 0o600)
        self._handoff = (endpoint_path, token_path)
        return {"endpoint": params["endpoint"]}

    def close(self) -> None:
        try:
            super().close()
        finally:
            for path in self._handoff or ():
                path.unlink(missing_ok=True)
            self._handoff = None


class SupervisorGoalQuackGateway(_TransientQuackGateway):
    """Owner inbox for supervisor goal upserts. The client does not open the catalog."""

    def __init__(self) -> None:
        self._requests: queue.Queue[dict[str, Any]] = queue.Queue()
        self._handoff: tuple[Path, Path] | None = None
        super().__init__()

    def _before_start(self) -> None:
        return None

    def dispatch(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        request = parse_request(encode_request(dict(envelope)))
        if request["command"] != GOAL_COMMAND:
            raise SpanCacheQuackError("command is outside the supervisor goal vocabulary")
        payload = request["payload"]
        goals = payload.get("goals") if isinstance(payload, dict) else None
        if not isinstance(goals, list) or set(payload) != {"goals"}:
            raise SpanCacheQuackError("payload does not match the closed command schema")
        item: dict[str, Any] = {
            "error": None,
            "event": threading.Event(),
            "goals": goals,
            "result": None,
        }
        self._requests.put(item)
        if not item["event"].wait(55):
            raise SpanCacheQuackError("supervisor owner did not answer")
        if item["error"]:
            raise SpanCacheQuackError(str(item["error"]))
        result = item["result"]
        if not isinstance(result, dict):
            raise SpanCacheQuackError("supervisor owner returned no receipt")
        return result

    def serve(self, apply: Any) -> int:
        """Apply queued goal payloads on the catalog owner thread."""

        served = 0
        while True:
            try:
                item = self._requests.get_nowait()
            except queue.Empty:
                return served
            try:
                item["result"] = apply(item["goals"])
            except Exception as exc:
                item["error"] = "supervisor owner could not upsert goals: " + type(exc).__name__ + ": " + str(exc)[:180]
            finally:
                item["event"].set()
            served += 1

    def publish(self, database_path: str | Path) -> dict[str, str]:
        if self._server is None:
            raise SpanCacheQuackError("gateway is not started")
        params = self.connection_parameters()
        endpoint_path, token_path = handoff_paths(database_path)
        endpoint_path.write_text(
            json.dumps(
                {
                    "admitted": False,
                    "endpoint": params["endpoint"],
                    "formalized": False,
                    "schema": SCHEMA,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        token_path.write_text(params["token"] + "\n", encoding="utf-8")
        os.chmod(token_path, 0o600)
        self._handoff = (endpoint_path, token_path)
        return {"endpoint": params["endpoint"]}

    def close(self) -> None:
        try:
            super().close()
        finally:
            for path in self._handoff or ():
                path.unlink(missing_ok=True)
            self._handoff = None


class SupervisorGoalTransportClient(RegistryTransportClient):
    """Sends class goals to the supervisor owner. It does not open the catalog."""

    @staticmethod
    def _request_envelope(command, payload, operation_id):
        if type(command) is not str or command != GOAL_COMMAND:
            raise SpanCacheQuackError("command is outside the supervisor goal vocabulary")
        try:
            return parse_request(
                encode_request(
                    {
                        "schema": SCHEMA,
                        "request_id": str(uuid.uuid4()),
                        "operation_id": operation_id,
                        "command": command,
                        "payload": payload,
                    }
                )
            )
        except QuackWireError as exc:
            raise SpanCacheQuackError(str(exc)) from exc


class SpanGapTransportClient(RegistryTransportClient):
    """Gap reader. It attaches the Quack endpoint, not the span catalog."""

    @staticmethod
    def _request_envelope(command, payload, operation_id):
        if type(command) is not str or command != COMMAND:
            raise SpanCacheQuackError("command is outside the span cache vocabulary")
        try:
            return parse_request(
                encode_request(
                    {
                        "schema": SCHEMA,
                        "request_id": str(uuid.uuid4()),
                        "operation_id": operation_id,
                        "command": command,
                        "payload": payload,
                    }
                )
            )
        except QuackWireError as exc:
            raise SpanCacheQuackError(str(exc)) from exc


def read_span_gaps(
    cache_path: str | Path,
    *,
    limit: int = 16,
    after: str = "",
    timeout: float = 60,
) -> dict[str, Any]:
    """Read one gap page from the owner. Refuses to open the catalog file."""

    endpoint_path, token_path = handoff_paths(cache_path)
    if not endpoint_path.is_file() or not token_path.is_file():
        raise SpanCacheQuackError(
            "the span catalog owner is not serving the quack control plane; "
            "refusing to open the DuckDB file"
        )
    descriptor = json.loads(endpoint_path.read_text(encoding="utf-8"))
    endpoint = str(descriptor.get("endpoint") or "")
    token = token_path.read_text(encoding="utf-8").strip()
    operation_id = "span-gaps-" + uuid.uuid4().hex
    with SpanGapTransportClient(endpoint, token) as client:
        reply = client.request(
            COMMAND,
            {"after": after, "limit": int(limit)},
            operation_id,
            timeout=timeout,
        )
    if not isinstance(reply, dict):
        raise SpanCacheQuackError("span owner reply was empty")
    reply["admitted"] = False
    reply["formalized"] = False
    reply["opens_catalog_file"] = False
    reply["wrote_compiler"] = False
    return reply
