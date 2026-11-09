"""Private staging ownership at the three production IPFS router call sites.

The native test launcher selects the reviewed router source before pytest starts.
These tests use the ordinary production import and small private filesystem
fixtures. Provider doubles never contact IPFS, subprocesses, or the network.
"""

import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import ModuleType, SimpleNamespace

import pytest

from ipfs_datasets_py import ipfs_backend_router as router


PAYLOAD = b"small private source bytes\x00\xff"
CID = "bafy-private-staging-observation"
SITES = ("accelerate", "kubo", "kit")


@pytest.fixture
def staging(monkeypatch, tmp_path):
    original_named = tempfile.NamedTemporaryFile
    original_unlink = os.unlink
    state = SimpleNamespace(paths=[], handles=[], real_unlink=original_unlink)

    def named(*args, **kwargs):
        assert kwargs.get("delete") is False
        kwargs["dir"] = tmp_path
        handle = original_named(*args, **kwargs)
        state.paths.append(Path(handle.name))
        state.handles.append(handle)
        return handle

    monkeypatch.setattr(router.tempfile, "NamedTemporaryFile", named)

    def unexpected_subprocess(*args, **kwargs):
        raise AssertionError("a private router staging test must not run a subprocess")

    monkeypatch.setattr(router.subprocess, "run", unexpected_subprocess)
    yield state
    # Fault-injection cases deliberately deny cleanup. Remove only their own
    # private fixture paths with the unpatched standard-library function.
    for path in state.paths:
        try:
            original_unlink(path)
        except FileNotFoundError:
            pass


@pytest.fixture
def operation(monkeypatch, staging):
    def make(site, *, callback=None, pin=True, kit_method="ipfs_add", codec="raw"):
        calls = []

        def consume(path):
            path = Path(path)
            assert path.is_file()
            assert path.read_bytes() == PAYLOAD
            calls.append({"path": path})
            return CID if callback is None else callback(path)

        if site == "accelerate":
            monkeypatch.setenv("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE", "1")

            class Handler:
                def __init__(self, cache_dir=None):
                    self.cache_dir = cache_dir

                def add_file(self, path, *, pin):
                    result = consume(path)
                    calls[-1]["kwargs"] = {"pin": pin}
                    return result

            fake = SimpleNamespace(FilesystemHandler=Handler)
            real_import = router.importlib.import_module

            def import_module(name, *args, **kwargs):
                if name == "ipfs_accelerate_py.datasets_integration.filesystem":
                    return fake
                return real_import(name, *args, **kwargs)

            # Scope this double to the router, not Python's shared importlib.
            monkeypatch.setattr(router, "importlib", SimpleNamespace(import_module=import_module))
            backend = router._get_accelerate_backend()
            assert backend is not None
            invoke = lambda: backend.add_bytes(PAYLOAD, pin=pin)
        elif site == "kubo":
            backend = router.KuboCLIBackend(cmd="private-never-executed-ipfs")

            def run(args, *, input_bytes=None):
                assert input_bytes is None
                result = consume(args[-1])
                calls[-1]["args"] = list(args)
                return (result + "\n").encode()

            monkeypatch.setattr(backend, "_run", run)
            invoke = lambda: backend.block_put(PAYLOAD, codec=codec)
        else:
            assert site == "kit"
            monkeypatch.setenv("IPFS_DATASETS_PY_ENABLE_IPFS_KIT", "1")
            monkeypatch.setenv("IPFS_KIT_DISABLE", "0")

            def add(argument, **kwargs):
                if kit_method in ("ipfs_add_bytes", "add_content", "add_bytes"):
                    assert argument == PAYLOAD
                    path = staging.paths[-1]
                else:
                    path = argument
                result = consume(path)
                calls[-1]["kwargs"] = kwargs
                return {"Hash": result} if result is not None else {"success": False, "error": "provider refused"}

            kit = SimpleNamespace(**{kit_method: add})

            class Deps:
                def get_cached(self, key):
                    assert key == "ipfs_kit_py::kit_instance"
                    return kit

            parent = ModuleType("ipfs_kit_py")
            parent.__path__ = []
            child = ModuleType("ipfs_kit_py.ipfs_kit")

            def unexpected_factory(**kwargs):
                raise AssertionError("the explicitly injected cached private kit must be reused")

            child.ipfs_kit = unexpected_factory
            monkeypatch.setitem(sys.modules, "ipfs_kit_py", parent)
            monkeypatch.setitem(sys.modules, "ipfs_kit_py.ipfs_kit", child)
            monkeypatch.setattr(router, "get_default_router_deps", lambda: Deps())
            backend = router._get_ipfs_kit_backend()
            assert backend is not None
            invoke = lambda: backend.add_bytes(PAYLOAD, pin=pin)
        return SimpleNamespace(invoke=invoke, backend=backend, calls=calls)

    return make


@pytest.mark.parametrize("pin", [False, True])
def test_accelerate_returns_provider_cid_and_preserves_pin(operation, staging, pin):
    op = operation("accelerate", pin=pin)
    assert op.invoke() == CID
    assert op.calls[0]["kwargs"] == {"pin": pin}
    assert staging.handles[0].closed
    assert not staging.paths[0].exists()


@pytest.mark.parametrize("pin", [False, True])
def test_accelerate_fallback_retains_cached_bytes_and_old_result(operation, staging, tmp_path, pin):
    retained = tmp_path / "retained-fallback"

    def copy_fallback(path):
        shutil.copy2(path, retained)
        return None

    op = operation("accelerate", callback=copy_fallback, pin=pin)
    assert op.invoke() == "Qm" + hashlib.sha256(PAYLOAD).hexdigest()[:44]
    assert op.calls[0]["kwargs"] == {"pin": pin}
    assert retained.read_bytes() == PAYLOAD
    assert not staging.paths[0].exists()


@pytest.mark.parametrize("site", SITES)
@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_provider_exception_identity_survives_and_stage_is_removed(operation, staging, site, error_type):
    primary = error_type("original private provider failure")

    def fail(path):
        raise primary

    op = operation(site, callback=fail)
    with pytest.raises(error_type) as caught:
        op.invoke()
    assert caught.value is primary
    assert staging.handles[0].closed
    assert not staging.paths[0].exists()


@pytest.mark.parametrize("site", SITES)
def test_provider_already_removed_stage_is_tolerated(operation, staging, site):
    def removed(path):
        staging.real_unlink(path)
        return CID

    assert operation(site, callback=removed).invoke() == CID
    assert staging.handles[0].closed
    assert not staging.paths[0].exists()


@pytest.mark.parametrize("site", SITES)
def test_cleanup_happens_after_handle_close_and_only_for_owned_path(monkeypatch, operation, staging, site):
    observed = []

    def unlink(path, *args, **kwargs):
        path = Path(path)
        if path in staging.paths:
            assert staging.handles[staging.paths.index(path)].closed
            observed.append(path)
        return staging.real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(router.os, "unlink", unlink)
    assert operation(site).invoke() == CID
    assert observed == staging.paths


@pytest.mark.parametrize("site", SITES)
def test_cleanup_error_preserves_primary_exception_with_note(monkeypatch, operation, staging, site):
    primary = RuntimeError("provider failure has priority")
    cleanup = PermissionError("private staging unlink denied")

    def fail(path):
        raise primary

    def unlink(path, *args, **kwargs):
        if Path(path) in staging.paths:
            assert staging.handles[staging.paths.index(Path(path))].closed
            raise cleanup
        return staging.real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(router.os, "unlink", unlink)
    with pytest.raises(RuntimeError) as caught:
        operation(site, callback=fail).invoke()
    assert caught.value is primary
    assert any("staging cleanup failed" in note and str(cleanup) in note for note in primary.__notes__)
    assert staging.paths[0].exists()


@pytest.mark.parametrize("site", SITES)
def test_successful_provider_does_not_hide_cleanup_failure(monkeypatch, operation, staging, site):
    cleanup = PermissionError("private success-path unlink denied")

    def unlink(path, *args, **kwargs):
        if Path(path) in staging.paths:
            assert staging.handles[staging.paths.index(Path(path))].closed
            raise cleanup
        return staging.real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(router.os, "unlink", unlink)
    with pytest.raises(PermissionError) as caught:
        operation(site).invoke()
    assert caught.value is cleanup
    assert staging.paths[0].exists()


@pytest.mark.parametrize("codec", ["raw", "dag-cbor"])
def test_kubo_preserves_codec_flags_and_return_decoding(operation, staging, codec):
    op = operation("kubo", codec=codec)
    assert op.invoke() == CID
    assert op.calls[0]["args"] == ["block", "put", "--cid-version", "1", "--format", codec, str(staging.paths[0])]
    assert not staging.paths[0].exists()


@pytest.mark.parametrize("message", ["unknown option: cid-version", "flag provided but not defined: cid-version"])
def test_kubo_minimal_retry_reuses_live_stage_then_removes_it(monkeypatch, operation, staging, message):
    op = operation("kubo", codec="raw")
    invocations = []

    def run(args, *, input_bytes=None):
        assert input_bytes is None
        assert Path(args[-1]).read_bytes() == PAYLOAD
        invocations.append(list(args))
        if len(invocations) == 1:
            raise RuntimeError(message)
        return (CID + "\n").encode()

    monkeypatch.setattr(op.backend, "_run", run)
    assert op.invoke() == CID
    stage = str(staging.paths[0])
    assert invocations == [["block", "put", "--cid-version", "1", "--format", "raw", stage], ["block", "put", "--format", "raw", stage]]
    assert len(staging.paths) == 1
    assert not staging.paths[0].exists()


@pytest.mark.parametrize("pin", [False, True])
@pytest.mark.parametrize("method", ["ipfs_add", "ipfs_add_path", "ipfs_add_bytes", "add_content", "add_bytes", "add_file"])
def test_kit_add_variants_preserve_supported_arguments(operation, staging, method, pin):
    op = operation("kit", kit_method=method, pin=pin)
    assert op.invoke() == CID
    expected = {} if method == "ipfs_add_bytes" else {"pin": pin}
    if method == "ipfs_add":
        expected["recursive"] = False
    assert op.calls[0]["kwargs"] == expected
    assert staging.handles[0].closed
    assert not staging.paths[0].exists()


def test_kit_unpinned_error_retains_existing_simulated_result(operation, staging):
    op = operation("kit", callback=lambda path: None, pin=False)
    assert op.invoke() == "Qm" + hashlib.sha256(PAYLOAD).hexdigest()[:44]
    assert not staging.paths[0].exists()


def test_kit_pinned_error_retains_existing_failure(operation, staging):
    op = operation("kit", callback=lambda path: None, pin=True)
    with pytest.raises(RuntimeError, match="provider refused"):
        op.invoke()
    assert staging.handles[0].closed
    assert not staging.paths[0].exists()
