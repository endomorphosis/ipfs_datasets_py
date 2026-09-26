"""Strict fake-wire tests; no native extensions, listeners or worker execution."""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control import autoencoder_quack_wire as wire


def envelope():
    return {"schema": wire.SCHEMA, "request_id": "request-1", "operation_id": "operation-1",
            "command": "ClaimRun", "payload": {"run_id": "run-1", "lease_seconds": 300}}


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def nested(levels):
    value = 0
    for _ in range(levels):
        value = [value]
    return value


@pytest.mark.parametrize("text", [False, True])
def test_request_reply_exact_roundtrip_detaches_and_preserves_numeric_types(text):
    request = envelope()
    request["payload"].update(text="é/法律", ordered=[2, 1, 2], integer=1, floating=1.0, zero=-0.0)
    raw = encode(request)
    assert wire.parse_request(raw.decode() if text else raw) == request
    result = {"schema": "registry-fixture", "operation_id": "scoped-id", "command": "ClaimRun",
              "admitted": False, "lease": {"owner_generation": 1, "expires_at": 3.0},
              "opaque_status": "future_owned_control_status"}
    reply = wire.make_reply(request, result=result)
    expected_digest = hashlib.sha256(encode(request)).hexdigest()
    assert reply["request_digest"] == expected_digest
    assert reply["request_id"] == request["request_id"]
    assert reply["admitted"] is reply["runtime_qualified"] is False
    result["lease"]["owner_generation"] = 999
    restored = wire.decode_reply(encode(reply).decode() if text else encode(reply), request)
    assert restored["lease"]["owner_generation"] == 1
    from ipfs_datasets_py.duckdb_control.contracts import canonical_json_bytes
    assert hashlib.sha256(canonical_json_bytes(request)).hexdigest() == expected_digest


@pytest.mark.parametrize("raw", [b"", b"[]", b"null", b"{} trailing", b"\xff",
    b'{"duplicate":1,"duplicate":2}', b'{"payload":{"x":0,"x":1}}',
    b'{"number":NaN}', b'{"number":Infinity}', b'{"number":-Infinity}',
    b'{"number":1e9999}', b'{"surrogate":"\\ud800"}', b'{"x":' + b'[' * 1100 + b'0' + b']' * 1100 + b'}'])
def test_invalid_json_is_rejected_without_echoing_wire_contents(raw):
    with pytest.raises(wire.QuackWireError) as caught:
        wire.parse_request(raw)
    assert repr(raw) not in str(caught.value)


@pytest.mark.parametrize("field,value", [("schema", "other"), ("schema", True), ("request_id", ""),
    ("request_id", "x" * 257), ("operation_id", 1), ("command", []), ("payload", []), ("extra", None)])
def test_request_envelope_fields_are_closed_and_typed(field, value):
    request = envelope()
    request[field] = value
    with pytest.raises(wire.QuackWireError):
        wire.parse_request(encode(request))


def test_wire_leaves_command_vocabulary_to_gateway():
    request = envelope()
    request["command"] = "AValidFutureIdentifier"
    assert wire.parse_request(encode(request))["command"] == request["command"]


def test_request_exact_byte_and_depth_limits_and_unicode_bytes():
    request = envelope()
    request["payload"] = {"pad": ""}
    request["payload"]["pad"] = "x" * (wire.MAX_COMMAND_BYTES - len(encode(request)))
    assert len(encode(request)) == wire.MAX_COMMAND_BYTES
    assert wire.parse_request(encode(request)) == request
    with pytest.raises(wire.QuackWireError, match="bound"):
        wire.parse_request(encode(request) + b" ")
    request["payload"]["pad"] = "é" * len(request["payload"]["pad"])
    assert len(encode(request).decode()) <= wire.MAX_COMMAND_BYTES
    with pytest.raises(wire.QuackWireError, match="bound"):
        wire.parse_request(encode(request).decode())
    request = envelope()
    request["payload"] = {"nested": nested(30)}  # leaf depth32, root depth0
    assert wire.parse_request(encode(request)) == request
    request["payload"] = {"nested": nested(31)}
    with pytest.raises(wire.QuackWireError, match="depth"):
        wire.parse_request(encode(request))


@pytest.mark.parametrize("change", ["request_id", "operation_id", "command", "payload", "integer_to_float", "signed_zero"])
def test_reply_digest_binds_every_request_field_and_numeric_representation(change):
    request = envelope()
    request["payload"]["zero"] = 0.0
    reply = wire.make_reply(request, result={"unchanged": True})
    expected = copy.deepcopy(request)
    if change in {"request_id", "operation_id", "command"}:
        expected[change] += "-other"
    elif change == "integer_to_float":
        expected["payload"]["lease_seconds"] = 300.0
    elif change == "signed_zero":
        expected["payload"]["zero"] = -0.0
    else:
        expected["payload"]["run_id"] = "run-other"
    with pytest.raises(wire.QuackWireError, match="binding"):
        wire.decode_reply(encode(reply), expected)


@pytest.mark.parametrize("field,value", [("schema", "other"), ("ok", 1), ("ok", "true"),
    ("admitted", 0), ("admitted", True), ("runtime_qualified", 0), ("runtime_qualified", True),
    ("request_digest", None), ("request_digest", "A" * 64), ("result", []), ("extra", False), ("error", "contradiction")])
def test_reply_schema_flags_and_result_are_strict(field, value):
    request = envelope()
    reply = wire.make_reply(request, result={})
    reply[field] = value
    with pytest.raises(wire.QuackWireError):
        wire.decode_reply(encode(reply), request)


def test_bound_error_preserves_diagnostic_without_claiming_no_commit_and_unbound_rejected():
    request = envelope()
    reply = wire.make_reply(request, error="owner response lost; resolve exact operation")
    assert set(reply) == {"schema", "ok", "admitted", "runtime_qualified", "request_id", "request_digest", "error"}
    assert reply["ok"] is False
    with pytest.raises(wire.QuackWireError, match="resolve exact operation"):
        wire.decode_reply(encode(reply), request)
    request["request_id"] = "invalid-request"
    unbound = wire.make_unbound_error("invalid request envelope")
    assert unbound["request_digest"] is None
    with pytest.raises(wire.QuackWireError, match="binding"):
        wire.decode_reply(encode(unbound), request)
    legacy = {"schema": wire.SCHEMA, "ok": True, "admitted": False, "runtime_qualified": False, "result": {}}
    with pytest.raises(wire.QuackWireError, match="closed"):
        wire.decode_reply(encode(legacy), request)


@pytest.mark.parametrize("kwargs", [{}, {"result": {}, "error": "both"}, {"result": []}, {"error": ""}, {"error": 1}])
def test_make_reply_requires_exactly_one_typed_outcome(kwargs):
    with pytest.raises(wire.QuackWireError):
        wire.make_reply(envelope(), **kwargs)


def test_direct_objects_are_bounded_without_running_custom_serializers():
    class Hostile:
        def to_dict(self):
            pytest.fail("custom serializers must not execute")
        def __eq__(self, other):
            pytest.fail("custom schema comparisons must not execute")
    request = envelope()
    request["schema"] = Hostile()
    with pytest.raises(wire.QuackWireError, match="envelope"):
        wire.make_reply(request, result={})
    with pytest.raises(wire.QuackWireError, match="native JSON"):
        wire.make_reply(envelope(), result={"hostile": Hostile()})
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(wire.QuackWireError, match="depth"):
        wire.make_reply(envelope(), result={"cyclic": cyclic})
    with pytest.raises(wire.QuackWireError, match="bound"):
        wire.make_reply(envelope(), result={"wide": ["x" * 65536] * 20})


def test_reply_exact_byte_limit_depth_duplicate_and_nonfinite_rejection():
    request = envelope()
    reply = wire.make_reply(request, result={"pad": ""})
    reply["result"]["pad"] = "x" * (wire.MAX_REPLY_BYTES - len(encode(reply)))
    assert len(encode(reply)) == wire.MAX_REPLY_BYTES
    assert wire.decode_reply(encode(reply), request) == reply["result"]
    with pytest.raises(wire.QuackWireError, match="bound"):
        wire.decode_reply(encode(reply) + b" ", request)
    with pytest.raises(wire.QuackWireError, match="bound"):
        wire.make_reply(request, result={"pad": "x" * wire.MAX_REPLY_BYTES})
    with pytest.raises(wire.QuackWireError, match="depth"):
        wire.make_reply(request, result={"nested": nested(31)})
    ordinary = encode(wire.make_reply(request, result={}))
    with pytest.raises(wire.QuackWireError, match="duplicate"):
        wire.decode_reply(ordinary.replace(b'"ok":true', b'"ok":false,"ok":true'), request)
    with pytest.raises(wire.QuackWireError, match="non-finite"):
        wire.decode_reply(ordinary.replace(b'"result":{}', b'"result":{"loss":NaN}'), request)


@pytest.mark.parametrize("substitution", [False, True])
def test_actual_client_request_uses_strict_decoder_with_fake_connection(substitution):
    from ipfs_datasets_py.duckdb_control.autoencoder_quack import RegistryTransportClient, RegistryTransportError
    class Connection:
        def execute(self, sql, parameters):
            if sql.startswith("INSERT"):
                self.request = json.loads(parameters[1])
                self.rows = []
            else:
                bound = copy.deepcopy(self.request)
                if substitution:
                    bound["operation_id"] = "another-operation"
                reply = wire.make_reply(bound, result={"fixture": True, "value": [1, -0.0]})
                self.rows = [(self.request["request_id"], encode(reply).decode())]
            return self
        def fetchall(self):
            return self.rows
    client = RegistryTransportClient.__new__(RegistryTransportClient)
    client._connection = Connection()
    client._lock, client._closed = threading.Lock(), False
    client._endpoint, client._token = "fixture-no-listener", "fixture-no-credentials"
    if substitution:
        with pytest.raises(RegistryTransportError, match="binding"):
            client.request("ReadRun", {"run_id": "run-1"}, "read", timeout=0.1)
    else:
        assert client.request("ReadRun", {"run_id": "run-1"}, "read", timeout=0.1) == {"fixture": True, "value": [1, -0.0]}


@pytest.mark.parametrize("mode", ["success", "error", "oversized_error", "oversized_result", "malformed"])
def test_actual_pump_binding_and_error_fallback_with_fake_database(mode):
    from ipfs_datasets_py.duckdb_control.autoencoder_quack import RegistryQuackGateway
    request = envelope()
    encoded = encode(request).decode() if mode != "malformed" else '{"duplicate":1,"duplicate":2}'
    stop = threading.Event()
    saved = []
    class Connection:
        closed = False
        def execute(self, sql, parameters=None):
            self.rows = [(1, encoded)] if sql.startswith("SELECT slot") else []
            if sql.startswith("INSERT OR REPLACE"):
                saved.append(parameters)
            if sql == "COMMIT":
                stop.set()
            return self
        def fetchall(self):
            return self.rows
        def close(self):
            self.closed = True
    connection = Connection()
    gateway = RegistryQuackGateway.__new__(RegistryQuackGateway)
    gateway._server = SimpleNamespace(cursor=lambda: connection)
    gateway._stop, gateway._sequence, gateway._failure = stop, 0, None
    def dispatch(_request):
        if mode == "malformed":
            pytest.fail("malformed request must not reach dispatch")
        if mode in {"error", "oversized_error"}:
            raise ValueError("owner error" if mode == "error" else "x" * wire.MAX_REPLY_BYTES)
        return {"fixture": True} if mode == "success" else {"oversized": "x" * wire.MAX_REPLY_BYTES}
    gateway.dispatch = dispatch
    gateway._pump()
    assert gateway._failure is None and connection.closed and len(saved) == 1
    request_id, raw, sequence = saved[0]
    assert sequence == 1 and len(raw.encode()) <= wire.MAX_REPLY_BYTES
    if mode == "success":
        assert wire.decode_reply(raw, request) == {"fixture": True}
    else:
        with pytest.raises(wire.QuackWireError):
            wire.decode_reply(raw, request)
        if mode == "malformed":
            assert request_id == "invalid-request" and json.loads(raw)["request_digest"] is None
        else:
            assert request_id == request["request_id"] and json.loads(raw)["request_digest"] == hashlib.sha256(encode(request)).hexdigest()
            if mode == "oversized_error":
                assert "resolve the original operation" in json.loads(raw)["error"]
