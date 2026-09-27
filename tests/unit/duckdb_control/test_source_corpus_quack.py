"""Source gateway dispatch and request binding through an injected transport."""
import json
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control import autoencoder_quack as transport
from ipfs_datasets_py.duckdb_control import autoencoder_quack_wire as wire
from ipfs_datasets_py.duckdb_control.source_corpus_catalog import SourceCorpusCatalog
from ipfs_datasets_py.duckdb_control.source_corpus_control import SourceCorpusControl, SourceCorpusScope
from ipfs_datasets_py.duckdb_control.source_corpus_quack import (
    SourceCorpusQuackGateway, SourceCorpusTransportClient,
)
from tests.unit.duckdb_control.test_source_corpus_catalog import _package, offline_only, canonical_tree


def _request(command, payload, operation="op"):
    return SourceCorpusTransportClient._request_envelope(command, payload, operation)


def test_source_profile_requires_opt_in_and_preserves_training_vocabulary(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "_connect_native", lambda: pytest.fail("native listener started"))
    package = _package(tmp_path / "source")
    with SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        scope = SourceCorpusScope("source-reader", bindings=(package.payload(),))
        control = SourceCorpusControl(owner, scope, package_resolver=package.resolve)
        with pytest.raises(transport.RegistryTransportError, match="opt-in"):
            SourceCorpusQuackGateway(control)
        gateway = SourceCorpusQuackGateway(control, enable_prototype=True)
        pending = gateway.dispatch(_request("RegisterSourceExport", package.payload()))
        assert pending["result"]["state"] == "pending"
        assert gateway.dispatch(_request("ResolveSourceExport", package.payload())) == {
            **pending, "command": "ResolveSourceExport"}
        status = gateway.status()
        assert status["command_profile"] == "source_corpus"
        assert status["principal_id"] == "source-reader"
        for key in ("started", "runtime_qualified", "production_activation", "admitted", "formalized",
                    "private_catalog_served", "package_execution_in_gateway_pump"):
            assert status[key] is False
        assert "run_ids" not in status
        with pytest.raises(transport.RegistryTransportError, match="worker vocabulary"):
            transport._envelope("RegisterSourceExport", package.payload(), "op")
        request = transport._envelope("ReadRun", {"run_id": "fake"}, "op")
        with pytest.raises(transport.RegistryTransportError, match="source corpus vocabulary"):
            gateway.dispatch(request)
        assert list(owner.package_root.iterdir()) == []
        gateway.close()


@pytest.mark.parametrize("substitution", [False, True])
def test_source_client_reuses_exact_reply_binding_without_connecting(substitution):
    class Connection:
        def execute(self, sql, parameters):
            if sql.startswith("INSERT"):
                self.request = json.loads(parameters[1])
                self.rows = []
            else:
                bound = dict(self.request)
                if substitution:
                    bound["command"] = "ReadSourceRows"
                reply = wire.make_reply(bound, result={"pending": True, "admitted": False})
                self.rows = [(self.request["request_id"], json.dumps(reply))]
            return self
        def fetchall(self):
            return self.rows

    client = SourceCorpusTransportClient.__new__(SourceCorpusTransportClient)
    client._connection, client._lock, client._closed = Connection(), threading.Lock(), False
    client._endpoint, client._token = "injected-no-listener", "injected-no-token"
    if substitution:
        with pytest.raises(transport.RegistryTransportError, match="binding"):
            client.request("ReadSourceVersion", {"version_id": "sha256:" + "a" * 64}, "read", timeout=0.1)
    else:
        assert client.request("ReadSourceVersion", {"version_id": "sha256:" + "a" * 64}, "read", timeout=0.1) == {
            "pending": True, "admitted": False}
    assert client._connection.request["command"] == "ReadSourceVersion"


@pytest.mark.parametrize("failure", [ValueError, TypeError, KeyError, RuntimeError])
def test_source_pump_redacts_owner_paths_in_bound_error(failure):
    request = _request("ReadSourceVersion", {"version_id": "sha256:" + "a" * 64})
    saved, stop = [], threading.Event()

    class Connection:
        def execute(self, sql, parameters=None):
            self.rows = [(1, json.dumps(request))] if sql.startswith("SELECT slot") else []
            if sql.startswith("INSERT OR REPLACE"):
                saved.append(parameters)
            if sql == "COMMIT":
                stop.set()
            return self
        def fetchall(self):
            return self.rows
        def close(self):
            pass

    gateway = SourceCorpusQuackGateway.__new__(SourceCorpusQuackGateway)
    gateway._server = SimpleNamespace(cursor=Connection)
    gateway._stop, gateway._sequence, gateway._failure = stop, 0, None
    def fail(request):
        raise failure("private SQL /home/owner/source.duckdb and bearer secret")
    gateway.dispatch = fail
    gateway._pump()
    assert gateway._failure is None and len(saved) == 1
    raw = saved[0][1]
    assert all(value not in raw for value in ("/home/owner", "bearer secret", "private SQL"))
    assert json.loads(raw)["request_digest"] is not None
    with pytest.raises(wire.QuackWireError):
        wire.decode_reply(raw, request)


@pytest.mark.parametrize("command", ["VerifySourceVersion", "ClaimRun", "execute_pending", "SELECT 1"])
def test_source_client_vocabulary_excludes_owner_execution(command):
    with pytest.raises(transport.RegistryTransportError, match="vocabulary"):
        _request(command, {})


@pytest.mark.parametrize("payload", [{"oversized": "x" * 65536}, {"nonfinite": float("nan")}, {"opaque": object()}])
def test_source_client_envelope_uses_strict_bounded_native_json(payload):
    with pytest.raises(transport.RegistryTransportError):
        _request("ReadSourceVersion", payload)
