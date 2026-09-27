"""Real local source rows behind metadata-only, scoped control commands.

No listener, network, native worker, model, translation or proof is exercised.
"""
import hashlib
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from ipfs_datasets_py.duckdb_control import source_corpus_catalog as catalog
from ipfs_datasets_py.duckdb_control import source_corpus_control as control
from tests.unit.duckdb_control.test_source_corpus_catalog import (
    _dataset, _package, _row, _version_id, canonical_tree, offline_only,
)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


def _binding(digest="a", language="en"):
    return {"dataset": _dataset(language),
            "package_manifest_artifact": {"sha256": digest * 64, "bytes": 123}}


def _forbidden(*args, **kwargs):
    pytest.fail("descriptor commands must not decode packages or execute heavy work")


def _controller(owner, binding, *, principal="reader", resolver=_forbidden, versions=()):
    return control.SourceCorpusControl(owner,
        control.SourceCorpusScope(principal, bindings=[binding], version_ids=versions),
        package_resolver=resolver)


def _status(client, command="RegisterSourceExport", operation="import", binding=None):
    return client.dispatch(command, operation, binding or client.scope.bindings[0])


@pytest.fixture
def owner(tmp_path):
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as value:
        yield value


def test_scope_snapshots_exact_pairs_and_has_detached_properties():
    first, second = _binding("a"), _binding("b", "es")
    scope = control.SourceCorpusScope("reader", bindings=[first, second],
                                      version_ids=["sha256:" + "c" * 64])
    expected = json.loads(_json(first))
    first["dataset"]["source_language"] = "fr"
    exposed = scope.bindings
    exposed[0]["package_manifest_artifact"]["bytes"] = 1
    assert scope.bindings[0] == expected
    assert scope.readable_version_ids == frozenset({_version_id(expected), _version_id(second),
                                                   "sha256:" + "c" * 64})
    with pytest.raises(AttributeError):
        scope.principal_id = "changed"


@pytest.mark.parametrize("change", [
    "empty", "bad_principal", "many_bindings", "duplicate_binding", "many_versions",
    "duplicate_version", "bad_version", "bool_bytes", "float_bytes", "extra_path", "wrong_profile",
])
def test_scope_rejects_invalid_closed_declarations(change):
    binding = _binding()
    bindings, versions, principal = [binding], [], "reader"
    if change == "empty": bindings = []
    elif change == "bad_principal": principal = "../private path"
    elif change == "many_bindings": bindings = [binding] * 65
    elif change == "duplicate_binding": bindings = [binding, binding]
    elif change == "many_versions": versions = ["sha256:" + "b" * 64] * 65
    elif change == "duplicate_version": versions = ["sha256:" + "b" * 64] * 2
    elif change == "bad_version": versions = ["../../database"]
    elif change == "bool_bytes": binding["package_manifest_artifact"]["bytes"] = True
    elif change == "float_bytes": binding["package_manifest_artifact"]["bytes"] = 123.0
    elif change == "extra_path": binding["package_manifest_artifact"]["path"] = "/private"
    elif change == "wrong_profile": binding["dataset"]["profile"] = "training"
    with pytest.raises(control.SourceCorpusControlError):
        control.SourceCorpusScope(principal, bindings=bindings, version_ids=versions)


def test_reservation_is_metadata_only_and_status_has_unambiguous_ids(owner, monkeypatch):
    binding = _binding()
    client = _controller(owner, binding)
    monkeypatch.setattr(owner, "register_export", _forbidden)
    monkeypatch.setattr(owner, "verify_version", _forbidden)
    before = _status(client, "ResolveSourceExport", binding=binding)
    assert before["result"]["state"] == "unknown"
    pending = _status(client, binding=binding)
    assert pending["operation_id"] == "import"
    assert pending["result"]["state"] == "pending"
    durable = "source-control:" + hashlib.sha256(b"reader").hexdigest() + ":" + hashlib.sha256(b"import").hexdigest()
    assert pending["result"]["operation_id"] == durable
    assert pending["result"]["receipt"] is None
    assert _status(client, binding=binding) == pending
    assert _status(client, "ResolveSourceExport", binding=binding)["result"] == pending["result"]
    assert owner.pending_registrations() == [{"operation_id": durable, "payload": binding}]
    assert list(owner.package_root.iterdir()) == []
    assert pending["admitted"] is pending["formalized"] is False


def test_pairs_cannot_be_crossed_and_principals_have_distinct_operations(owner):
    a, b = _binding(), _binding("b", "es")
    client = control.SourceCorpusControl(owner, control.SourceCorpusScope("one", bindings=[a, b]),
                                         package_resolver=_forbidden)
    crossed = {"dataset": a["dataset"], "package_manifest_artifact": b["package_manifest_artifact"]}
    with pytest.raises(control.SourceCorpusControlError, match="source_binding_out_of_scope"):
        _status(client, binding=crossed)
    first = _status(client, binding=a)
    other = _status(_controller(owner, a, principal="two"), binding=a)
    assert first["result"]["operation_id"] != other["result"]["operation_id"]
    with pytest.raises(control.SourceCorpusControlError, match="catalog_operation_failed"):
        _status(client, binding=b)


@pytest.mark.parametrize("command", ["VerifySourceVersion", "ExecutePending", "ReadRun", "SELECT"])
def test_only_four_remote_commands(owner, command):
    client = _controller(owner, _binding())
    with pytest.raises(control.SourceCorpusControlError, match="unsupported_source_command"):
        client.dispatch(command, "op", {})
    assert owner.pending_registrations() == []


@pytest.mark.parametrize("change", ["foreign", "extra", "bool_cursor", "low_cursor", "bool_limit", "zero", "large"])
def test_rows_requests_are_closed_and_bounded_before_catalog_reads(owner, monkeypatch, change):
    binding = _binding()
    client = _controller(owner, binding)
    monkeypatch.setattr(owner, "read_rows", _forbidden)
    payload = {"version_id": _version_id(binding), "after_ordinal": -1, "limit": 64}
    if change == "foreign": payload["version_id"] = "sha256:" + "f" * 64
    elif change == "extra": payload["sql"] = "SELECT *"
    elif change == "bool_cursor": payload["after_ordinal"] = True
    elif change == "low_cursor": payload["after_ordinal"] = -2
    elif change == "bool_limit": payload["limit"] = True
    elif change == "zero": payload["limit"] = 0
    elif change == "large": payload["limit"] = 65
    with pytest.raises(control.SourceCorpusControlError):
        client.dispatch("ReadSourceRows", "read", payload)


def test_actual_owner_lock_makes_all_commands_and_drains_busy(owner):
    client = _controller(owner, _binding())
    held, release = threading.Event(), threading.Event()
    def hold():
        with owner._lock:
            held.set()
            assert release.wait(10)
    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert held.wait(10)
        for command, payload in [
            ("RegisterSourceExport", _binding()), ("ResolveSourceExport", _binding()),
            ("ReadSourceVersion", {"version_id": _version_id(_binding())}),
            ("ReadSourceRows", {"version_id": _version_id(_binding()), "after_ordinal": -1, "limit": 1}),
        ]:
            response = client.dispatch(command, "busy", payload)
            assert response["status"] == "busy" and response["result"] is None
        assert client.execute_pending()["status"] == "busy"
        assert not release.is_set()
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive()
    assert owner.pending_registrations() == []


def test_real_package_resume_restart_and_path_free_reads(tmp_path):
    package = _package(tmp_path / "original", campaign=True)
    database, owned = tmp_path / "catalog.duckdb", tmp_path / "owned"
    scope = control.SourceCorpusScope("owner", bindings=[package.payload()])
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        client = control.SourceCorpusControl(owner, scope, package_resolver=_forbidden)
        pending = _status(client)
        client.close()
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        client = control.SourceCorpusControl(owner, scope, package_resolver=package.resolve)
        assert _status(client)["result"] == pending["result"]
        drain = client.execute_pending()
        assert drain["status"] == "finished" and len(drain["operations"]) == 1
        operation = drain["operations"][0]
        assert operation["error"] is None and operation["operation"]["state"] == "completed"
        version_id = operation["operation"]["receipt"]["version_id"]
        rows, cursor = [], -1
        while True:
            response = client.dispatch("ReadSourceRows", "rows", {
                "version_id": version_id, "after_ordinal": cursor, "limit": 2})
            assert len(_json(response)) <= control.MAX_RESULT_BYTES
            page = response["result"]
            rows.extend(page["rows"])
            if page["complete"]: break
            cursor = page["next_after_ordinal"]
        assert rows == [{"ordinal": index, **row} for index, row in enumerate(package.expected)]
        view = client.dispatch("ReadSourceVersion", "version", {"version_id": version_id})["result"]
        assert "package_directory" not in view
        assert str(owned) not in _json(view).decode()
        assert view["qualification"]["admitted"] is False
        assert view["qualification"]["formalized"] is False
        assert client.execute_pending()["operations"] == []
        client.close()
    shutil.rmtree(package.original_root)
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        client = control.SourceCorpusControl(owner, scope, package_resolver=_forbidden)
        resolved = _status(client, "ResolveSourceExport")["result"]
        assert resolved == operation["operation"]
        assert resolved["receipt"]["current_availability_verified"] is False
        assert client.execute_pending()["operations"] == []
        client.close()


def test_lost_reserve_and_completion_responses_resolve_without_duplicate_work(tmp_path, monkeypatch):
    package = _package(tmp_path / "original")
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        client = _controller(owner, package.payload(), resolver=package.resolve)
        reserve = owner.reserve_registration
        def lost_reserve(*args, **kwargs):
            reserve(*args, **kwargs)
            raise OSError("lost reply /private/owner/token")
        monkeypatch.setattr(owner, "reserve_registration", lost_reserve)
        with pytest.raises(control.SourceCorpusControlError, match="^catalog_operation_failed$") as error:
            _status(client)
        assert "/private" not in str(error.value)
        assert _status(client, "ResolveSourceExport")["result"]["state"] == "pending"
        register = owner.register_export
        calls = []
        def lost_completion(*args, **kwargs):
            calls.append(args[0])
            register(*args, **kwargs)
            raise OSError("lost completion /private/path")
        monkeypatch.setattr(owner, "register_export", lost_completion)
        result = client.execute_pending()
        assert result["operations"][0]["operation"]["state"] == "completed"
        assert result["operations"][0]["error"] is None
        assert client.execute_pending()["operations"] == []
        assert len(calls) == 1


def test_failed_owner_attempt_stays_pending_and_retries_only_explicitly(tmp_path):
    package = _package(tmp_path / "original")
    calls = []
    def resolver(reference):
        calls.append(reference)
        if len(calls) == 1:
            raise OSError("secret package /private/input")
        return package.resolve(reference)
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        client = _controller(owner, package.payload(), resolver=resolver)
        _status(client)
        failed = client.execute_pending()["operations"][0]
        assert failed["operation"]["state"] == "pending"
        assert failed["error"] == "catalog_operation_failed"
        assert len(calls) == 1
        assert _status(client, "ResolveSourceExport")["result"]["state"] == "pending"
        assert len(calls) == 1
        assert client.execute_pending()["operations"][0]["operation"]["state"] == "completed"
        assert len(calls) == 2


def test_foreign_principal_queue_cannot_starve_scoped_owner(owner, monkeypatch):
    binding = _binding()
    client = _controller(owner, binding)
    for index in range(65):
        owner.reserve_registration("a-foreign-" + str(index), binding)
    for index in range(3):
        _status(client, operation="own-" + str(index))
    attempted = []
    def unavailable(operation, **kwargs):
        attempted.append(operation)
        raise OSError("unavailable /private")
    monkeypatch.setattr(owner, "register_export", unavailable)
    report = client.execute_pending(max_operations=2)
    assert report["scanned_count"] == 3 and report["scan_limit_reached"] is False
    assert len(report["operations"]) == len(attempted) == 2
    assert all(item.startswith("source-control:") for item in attempted)
    assert owner.pending_registrations(64)[0]["operation_id"].startswith("a-foreign-")


def test_narrowed_scope_does_not_adopt_other_binding_pending_work(owner, monkeypatch):
    a, b = _binding(), _binding("b", "es")
    broad = control.SourceCorpusControl(owner, control.SourceCorpusScope("reader", bindings=[a, b]),
                                        package_resolver=_forbidden)
    _status(broad, operation="original-b", binding=b)
    narrow = _controller(owner, a)
    monkeypatch.setattr(owner, "register_export", _forbidden)
    report = narrow.execute_pending()
    assert report["scanned_count"] == 1 and report["operations"] == []


def test_row_budget_covers_unicode_full_envelope_and_does_not_skip(tmp_path):
    package = _package(tmp_path / "original", rows=[_row(i, text="é" * 17000) for i in range(1, 4)])
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        client = _controller(owner, package.payload(), resolver=package.resolve)
        _status(client)
        client.execute_pending()
        version = _version_id(package.payload())
        rows = []
        cursor = -1
        for _ in range(3):
            response = client.dispatch("ReadSourceRows", "o" * 256, {
                "version_id": version, "after_ordinal": cursor, "limit": 64})
            assert len(_json(response)) <= 96 * 1024
            assert response["result"]["row_count"] == 1
            rows.extend(response["result"]["rows"])
            cursor = response["result"]["next_after_ordinal"]
        assert cursor is None
        assert rows == [{"ordinal": i, **row} for i, row in enumerate(package.expected)]


def test_oversized_first_row_has_explicit_sanitized_error(tmp_path):
    package = _package(tmp_path / "original", rows=[_row(1, text="é" * 60000), _row(2)])
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        client = _controller(owner, package.payload(), resolver=package.resolve)
        _status(client)
        client.execute_pending()
        with pytest.raises(control.SourceCorpusControlError, match="^source_row_too_large$"):
            client.dispatch("ReadSourceRows", "read", {
                "version_id": _version_id(package.payload()), "after_ordinal": -1, "limit": 2})


def test_cross_controller_drain_is_busy_and_close_cannot_race_import(tmp_path):
    package = _package(tmp_path / "original")
    entered, release = threading.Event(), threading.Event()
    def resolver(reference):
        entered.set()
        assert release.wait(10)
        return package.resolve(reference)
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        client = _controller(owner, package.payload(), resolver=resolver)
        other = _controller(owner, package.payload(), resolver=_forbidden)
        _status(client)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.execute_pending)
            try:
                assert entered.wait(10)
                assert other.execute_pending()["status"] == "busy"
                assert _status(other, "ResolveSourceExport")["status"] == "busy"
                with pytest.raises(control.SourceCorpusControlError, match="control_busy"):
                    client.close()
            finally:
                release.set()
            assert future.result(timeout=10)["operations"][0]["operation"]["state"] == "completed"
        client.close()
        assert other.execute_pending()["operations"] == []


@pytest.mark.parametrize("bound", [True, 0, 65, 1.5])
def test_owner_drain_bound_is_strict(owner, bound):
    client = _controller(owner, _binding())
    with pytest.raises(control.SourceCorpusControlError, match="invalid_drain_bound"):
        client.execute_pending(bound)
    assert owner.pending_registrations() == []


def test_explicit_read_only_scope_and_closed_pid_guards(owner, monkeypatch):
    version = "sha256:" + "a" * 64
    scope = control.SourceCorpusScope("reader", version_ids=[version])
    client = control.SourceCorpusControl(owner, scope, package_resolver=_forbidden)
    with pytest.raises(control.SourceCorpusControlError, match="source_binding_out_of_scope"):
        _status(client, binding=_binding())
    original_pid = control.os.getpid()
    with monkeypatch.context() as change:
        change.setattr(control.os, "getpid", lambda: original_pid + 1)
        with pytest.raises(control.SourceCorpusControlError, match="control_unavailable"):
            client.dispatch("ReadSourceVersion", "read", {"version_id": version})
    client.close()
    with pytest.raises(control.SourceCorpusControlError, match="control_unavailable"):
        client.dispatch("ReadSourceVersion", "read", {"version_id": version})
    # Controller close leaves its separately owned catalog usable.
    assert owner.pending_registrations() == []
