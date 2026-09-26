"""Experimental native Quack transport for assigned autoencoder workers.

Each owner-created worker scope has its own transient gateway database,
loopback listener and random token. The private registry is never attached to
the served instance. Quack admits exactly an inbox append, catalog discovery
needed by that append, and the worker's bounded reply query. Owner code alone
dispatches the closed command vocabulary. Importing this module starts nothing.

This is an opt-in prototype, not a production-qualified service. Its receipts
are control records, never Lean admits. Artifact staging remains an owner/data
plane operation; remote requests contain immutable descriptors only.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import platform
import re
import secrets
import socket
import threading
import time
from typing import Any, Mapping
import uuid

from .autoencoder_registry import AutoencoderRegistry, RegistryError
from .capabilities import REQUIRED_DUCKDB_VERSION_TEXT
from .contracts import canonical_json_bytes
from .autoencoder_quack_wire import (
    QuackWireError, parse_request, make_reply, make_unbound_error, decode_reply,
)
from ..ducklake.capabilities import platform_extension_pins


SCHEMA = "ipfs_datasets_py/autoencoder-quack-prototype@1"
MAX_COMMAND_BYTES = 65_536
MAX_REPLY_BYTES = 131_072
MAX_PENDING = 64
WORKER_COMMANDS = frozenset({"ClaimRun", "RenewLease", "ReadRun", "ReadVersion", "CompleteRun"})
OWNED_COMMANDS = frozenset({"SubmitOwnedInvocation", "ReadOwnedInvocation", "ResolveOwnedInvocation"})
COMMANDS = WORKER_COMMANDS | OWNED_COMMANDS
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_CONFIG = {
    "autoinstall_known_extensions": "false",
    "autoload_known_extensions": "false",
    "allow_unsigned_extensions": "false",
    "threads": "2",
}
# Native Quack encodes an appended DataChunk as one NULL in authz SQL.
_APPEND_QUERY = "INSERT INTO main.command_inbox VALUES (NULL)"
_REPLY_QUERY = (
    "SELECT request_id, reply_json FROM command_replies "
    f"ORDER BY sequence DESC LIMIT {MAX_PENDING}"
)
_CATALOG_SCHEMAS = """
SELECT catalog_name, schema_name
FROM information_schema.schemata
WHERE catalog_name NOT IN ('system', 'temp')
ORDER BY ALL
\t"""
_CATALOG_RELATIONS = """
SELECT schema_name, sql, 'table'
FROM duckdb_tables()
UNION ALL
SELECT schema_name, view_name, 'view'
FROM duckdb_views()
\t"""


class RegistryTransportError(RuntimeError):
    """Unavailable native transport, invalid request or denied worker scope."""


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise RegistryTransportError(f"{name} must be a bounded identifier")
    return value


def _literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _connect_native() -> tuple[Any, dict[str, Any]]:
    """Load only the installed, hash-pinned Quack and HTTP artifacts."""
    import duckdb

    if duckdb.__version__ != REQUIRED_DUCKDB_VERSION_TEXT:
        raise RegistryTransportError("DuckDB version does not match the workspace policy")
    machine = {"aarch64": "linux_arm64", "x86_64": "linux_amd64"}.get(platform.machine().lower())
    if machine is None:
        raise RegistryTransportError("platform has no pinned native Quack artifact")
    pins = platform_extension_pins(machine)
    connection = duckdb.connect(":memory:", config=_CONFIG)
    artifacts = {}
    try:
        for name in ("quack", "httpfs"):
            row = connection.execute(
                "SELECT installed, install_path FROM duckdb_extensions() WHERE extension_name=?", [name]
            ).fetchone()
            if not row or not row[0] or not Path(row[1]).is_file():
                raise RegistryTransportError(f"installed {name} artifact is unavailable")
            path = Path(row[1])
            with path.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            if digest != pins[name].bin_sha256:
                raise RegistryTransportError(f"installed {name} artifact differs from the workspace pin")
            connection.execute(f"LOAD {_literal(path)}")
            artifacts[name] = digest
        return connection, {
            "duckdb_version": duckdb.__version__, "platform": machine,
            "extension_sha256": artifacts, "network_install": False,
            "autoload": False, "native_quack": True,
        }
    except BaseException:
        connection.close()
        raise


@dataclass(frozen=True)
class WorkerScope:
    """Owner-issued assignment; a worker cannot change its identity or runs."""

    worker_id: str
    run_ids: frozenset[str]

    def __post_init__(self) -> None:
        _identifier(self.worker_id, "worker_id")
        runs = frozenset(self.run_ids)
        if not 1 <= len(runs) <= MAX_PENDING:
            raise RegistryTransportError("scope requires between 1 and 64 assigned runs")
        for run_id in runs:
            _identifier(run_id, "run_id")
        object.__setattr__(self, "run_ids", runs)


def _envelope(command: str, payload: Mapping[str, Any], operation_id: str) -> dict[str, Any]:
    if command not in COMMANDS:
        raise RegistryTransportError("command is outside the worker vocabulary")
    _identifier(operation_id, "operation_id")
    if not isinstance(payload, Mapping):
        raise RegistryTransportError("payload must be an object")
    envelope = {
        "schema": SCHEMA, "request_id": str(uuid.uuid4()),
        "operation_id": operation_id, "command": command, "payload": dict(payload),
    }
    encoded = canonical_json_bytes(envelope)
    if len(encoded) > MAX_COMMAND_BYTES:
        raise RegistryTransportError("command exceeds 65536 bytes; stage an artifact")
    try:
        return parse_request(encoded)
    except QuackWireError as exc:
        raise RegistryTransportError(str(exc)) from exc


class RegistryQuackGateway:
    """One transient, scoped native endpoint backed by a durable local owner.

    ``enable_prototype=True`` is required explicitly. It does not bypass the
    existing DuckLake production gates or qualify this adapter for deployment.
    A separate gateway per worker isolates reply visibility and bearer scope.
    Mutation replay survives gateway and registry restarts through the owner's
    durable operation log; transport inbox/replies are deliberately disposable.
    """

    def __init__(self, registry: AutoencoderRegistry, scope: WorkerScope, *, enable_prototype: bool = False,
                 owned_control: Any = None) -> None:
        if enable_prototype is not True:
            raise RegistryTransportError("native training transport requires explicit prototype opt-in")
        if not isinstance(registry, AutoencoderRegistry) or not isinstance(scope, WorkerScope):
            raise RegistryTransportError("gateway requires an owner registry and immutable scope")
        if owned_control is not None:
            from .autoencoder_owned_control import OwnedInvocationControl
            if (type(owned_control) is not OwnedInvocationControl or owned_control.registry is not registry
                    or owned_control.worker_id != scope.worker_id or owned_control.run_ids != scope.run_ids):
                raise RegistryTransportError("owned invocation control differs from gateway owner or scope")
        self.registry, self.scope = registry, scope
        self._owned_control = owned_control
        self._server = None
        self._thread = None
        self._stop = threading.Event()
        self._token = secrets.token_urlsafe(32)
        self._endpoint = ""
        self._failure: str | None = None
        self._sequence = 0
        self.capability: dict[str, Any] = {}

    def _run_scope(self, run_id: Any) -> str:
        if run_id not in self.scope.run_ids:
            raise RegistryTransportError("run is outside the assigned worker scope")
        return run_id

    def _worker_mutation_run(self, run_id: Any) -> str:
        """Owner-verified jobs cannot use the generic worker mutation profile."""
        run_id = self._run_scope(run_id)
        specification = self.registry.get_run(run_id)["spec"]
        schema = specification.get("schema")
        if ("job_spec_artifact" in specification or
                isinstance(schema, str) and schema.startswith("autoencoder-daemon-invocation-request-")):
            raise RegistryTransportError("owner-verified run requires the owned invocation control profile")
        return run_id

    @staticmethod
    def _fields(payload: Mapping[str, Any], required: set[str], optional: set[str] | frozenset[str] = frozenset()) -> None:
        if not required.issubset(payload) or set(payload) - required - optional:
            raise RegistryTransportError("payload does not match the closed command schema")

    def _lease(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        lease = payload.get("lease")
        if not isinstance(lease, Mapping) or lease.get("worker_id") != self.scope.worker_id:
            raise RegistryTransportError("lease is outside the assigned worker scope")
        self._worker_mutation_run(lease.get("run_id"))
        return lease

    def dispatch(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        """Trusted owner dispatch; no reflection, arbitrary callbacks or SQL."""
        if not isinstance(envelope, Mapping) or set(envelope) != {
            "schema", "request_id", "operation_id", "command", "payload"
        } or envelope["schema"] != SCHEMA:
            raise RegistryTransportError("invalid request envelope")
        _identifier(envelope["request_id"], "request_id")
        operation_id = _identifier(envelope["operation_id"], "operation_id")
        command, payload = envelope["command"], envelope["payload"]
        if not isinstance(command, str) or command not in COMMANDS or not isinstance(payload, dict):
            raise RegistryTransportError("invalid worker command")
        if len(canonical_json_bytes(envelope)) > MAX_COMMAND_BYTES:
            raise RegistryTransportError("command exceeds 65536 bytes")
        if self._owned_control is not None:
            if command not in OWNED_COMMANDS:
                raise RegistryTransportError("command is outside the owned invocation control profile")
            self._fields(payload, {"run_id", "request_artifact"})
            run_id = self._run_scope(payload["run_id"])
            if command == "SubmitOwnedInvocation":
                return self._owned_control.submit(operation_id, run_id, payload["request_artifact"])
            if command == "ReadOwnedInvocation":
                return self._owned_control.read(run_id, payload["request_artifact"])
            return self._owned_control.resolve(operation_id, run_id, payload["request_artifact"])
        if command not in WORKER_COMMANDS:
            raise RegistryTransportError("command requires the owned invocation control profile")
        # Worker-selected IDs cannot collide with another worker's or an
        # administrative operation. The same ID with a different command or
        # payload still conflicts in the durable registry.
        durable_id = "worker-quack:" + hashlib.sha256(canonical_json_bytes(
            {"worker_id": self.scope.worker_id, "operation_id": operation_id}
        )).hexdigest()
        if command == "ClaimRun":
            self._fields(payload, {"run_id"}, {"lease_seconds"})
            return self.registry.claim_run(
                durable_id, self._worker_mutation_run(payload["run_id"]), self.scope.worker_id,
                lease_seconds=payload.get("lease_seconds", 300),
            )
        if command == "RenewLease":
            self._fields(payload, {"lease"}, {"lease_seconds"})
            return self.registry.renew_lease(
                durable_id, self._lease(payload), lease_seconds=payload.get("lease_seconds", 300)
            )
        if command == "CompleteRun":
            self._fields(payload, {"lease", "artifact", "result"})
            return self.registry.complete_run(
                durable_id, self._lease(payload), payload["artifact"], payload["result"]
            )
        if command == "ReadRun":
            self._fields(payload, {"run_id"})
            run = self.registry.get_run(self._run_scope(payload["run_id"]))
            if run["lease"] and run["lease"]["worker_id"] != self.scope.worker_id:
                raise RegistryTransportError("run has another worker's lease")
            return {"admitted": False, "run": run}
        self._fields(payload, {"version_id"})
        version = self.registry.get_version(_identifier(payload["version_id"], "version_id"))
        assigned_runs = [self.registry.get_run(run_id) for run_id in self.scope.run_ids]
        base_ids = {run["base_version_id"] for run in assigned_runs}
        producer = version["metadata"].get("producer_run")
        if version["version_id"] not in base_ids and producer not in self.scope.run_ids:
            raise RegistryTransportError("version is outside the assigned worker scope")
        return {"admitted": False, "version": version}

    def _pump(self) -> None:
        connection = self._server.cursor()
        try:
            while not self._stop.is_set():
                rows = connection.execute("SELECT slot, envelope_json FROM command_inbox ORDER BY slot").fetchall()
                for slot, encoded in rows:
                    request_id = "invalid-request"
                    envelope = None
                    try:
                        envelope = parse_request(encoded)
                        request_id = envelope["request_id"]
                        result = self.dispatch(envelope)
                        reply = make_reply(envelope, result=result)
                    except (RegistryError, RegistryTransportError, QuackWireError, ValueError, TypeError, KeyError) as exc:
                        # A failed reply can follow a committed mutation. Never
                        # represent it as evidence that an operation did not run.
                        error = str(exc)
                        try:
                            reply = make_reply(envelope, error=error) if envelope is not None else make_unbound_error("invalid request envelope")
                        except QuackWireError:
                            reply = make_reply(envelope, error="owner reply unavailable; resolve the original operation before retrying")
                    except Exception:
                        # An unexpected owner failure is not a receipt of
                        # success. Do not expose private SQL, paths or traces.
                        error = "owner operation failed; retry the same operation ID and payload"
                        reply = make_reply(envelope, error=error) if envelope is not None else make_unbound_error(error)
                    encoded_reply = canonical_json_bytes(reply).decode()
                    self._sequence += 1
                    connection.execute("BEGIN")
                    try:
                        connection.execute("INSERT OR REPLACE INTO command_replies VALUES (?, ?, ?)",
                                           [request_id, encoded_reply, self._sequence])
                        connection.execute("DELETE FROM command_inbox WHERE slot=? AND envelope_json=?", [slot, encoded])
                        connection.execute(
                            "DELETE FROM command_replies WHERE request_id NOT IN "
                            f"(SELECT request_id FROM command_replies ORDER BY sequence DESC LIMIT {MAX_PENDING})"
                        )
                        connection.execute("COMMIT")
                    except BaseException:
                        connection.execute("ROLLBACK")
                        raise
                self._stop.wait(0.01)
        except Exception:
            self._failure = "gateway owner pump failed; retry through a new gateway"
        finally:
            connection.close()

    def start(self) -> "RegistryQuackGateway":
        if self._server is not None:
            raise RegistryTransportError("gateway is already started")
        for run_id in self.scope.run_ids:
            self.registry.get_run(run_id)
        server, capability = _connect_native()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        self._endpoint = f"quack:127.0.0.1:{port}"
        started = False
        try:
            server.execute(
                "CREATE TABLE command_inbox (slot INTEGER PRIMARY KEY "
                f"CHECK (slot BETWEEN 1 AND {MAX_PENDING}), envelope_json VARCHAR NOT NULL "
                f"CHECK (octet_length(encode(envelope_json)) BETWEEN 1 AND {MAX_COMMAND_BYTES}))"
            )
            server.execute("CREATE TABLE command_replies (request_id VARCHAR PRIMARY KEY, reply_json VARCHAR, sequence BIGINT)")
            permitted = (_APPEND_QUERY, _REPLY_QUERY, _CATALOG_SCHEMAS, _CATALOG_RELATIONS)
            comparisons = " OR ".join("query = " + _literal(query) for query in permitted)
            server.execute("CREATE MACRO training_gateway_authz(sid, query) AS "
                           f"(sid IS NOT NULL AND query IS NOT NULL AND ({comparisons}))")
            server.execute("SET GLOBAL quack_authentication_function = 'quack_check_token'")
            server.execute("SET GLOBAL quack_authorization_function = 'training_gateway_authz'")
            server.execute("CALL quack_serve(?, token := ?, disable_ssl := true)",
                           [self._endpoint, self._token]).fetchall()
            started = True
            self._server, self.capability = server, capability
            self._stop.clear()
            self._failure = None
            self._thread = threading.Thread(target=self._pump, name="autoencoder-quack-owner", daemon=True)
            self._thread.start()
            return self
        except BaseException:
            if started:
                server.execute("CALL quack_stop(?)", [self._endpoint]).fetchall()
            server.close()
            self._server = None
            raise

    def connection_parameters(self) -> dict[str, str]:
        """Private worker handoff; contains a bearer token and must not be logged."""
        if self._server is None:
            raise RegistryTransportError("gateway is not started")
        return {"endpoint": self._endpoint, "token": self._token}

    def status(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "prototype": True, "runtime_qualified": False,
                "admitted": False, "started": self._server is not None,
                "authorization": "owner_issued_worker_scope_bearer",
                "production_activation": False,
                "command_profile": "owned_invocation" if self._owned_control is not None else "generic_worker",
                "execution_in_gateway_pump": False,
                "worker_id": self.scope.worker_id, "run_ids": sorted(self.scope.run_ids),
                "private_registry_served": False, "transient_gateway_database": True,
                "failure": self._failure, "capability": self.capability}

    def close(self) -> None:
        if self._server is None:
            return
        self._stop.set()
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            raise RegistryTransportError("owner pump did not stop; close owner only after it finishes")
        try:
            self._server.execute("CALL quack_stop(?)", [self._endpoint]).fetchall()
        finally:
            self._server.close()
            self._server = None

    def __enter__(self) -> "RegistryQuackGateway":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.close()


class RegistryTransportClient:
    """Synchronous bounded commands over native Quack; no registry file access."""

    def __init__(self, endpoint: str, token: str) -> None:
        if not re.fullmatch(r"quack:127\.0\.0\.1:[1-9][0-9]{0,4}", endpoint):
            raise RegistryTransportError("prototype endpoint must be explicit IPv4 loopback")
        if not isinstance(token, str) or not 24 <= len(token) <= 256:
            raise RegistryTransportError("invalid gateway token")
        self._connection, self.capability = _connect_native()
        self._endpoint, self._token = endpoint, token
        self._lock = threading.Lock()
        self._closed = False
        try:
            self._connection.execute(
                f"ATTACH {_literal(endpoint)} AS training_gateway (TOKEN {_literal(token)})"
            )
        except Exception as exc:
            self._connection.close()
            raise RegistryTransportError(str(exc).replace(token, "<redacted>")) from None

    def request(self, command: str, payload: Mapping[str, Any], operation_id: str, *, timeout: float = 10) -> dict[str, Any]:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
            raise RegistryTransportError("timeout must be within (0, 60] seconds")
        envelope = _envelope(command, payload, operation_id)
        with self._lock:
            if self._closed:
                raise RegistryTransportError("client is closed")
            try:
                self._connection.execute(
                    "INSERT INTO training_gateway.main.command_inbox VALUES (?, ?)",
                    [1, canonical_json_bytes(envelope).decode()],
                ).fetchall()
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    rows = self._connection.execute(
                        "SELECT * FROM quack_query(?, ?, token := ?, disable_ssl := true)",
                        [self._endpoint, _REPLY_QUERY, self._token],
                    ).fetchall()
                    for request_id, encoded in rows:
                        if request_id == envelope["request_id"]:
                            return decode_reply(encoded, envelope)
                    time.sleep(0.01)
            except Exception as exc:
                raise RegistryTransportError(str(exc).replace(self._token, "<redacted>")) from None
            raise RegistryTransportError("reply timed out; retry the same operation ID and payload")

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> "RegistryTransportClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
