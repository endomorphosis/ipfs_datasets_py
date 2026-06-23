from __future__ import annotations

import ctypes
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.zkp import ZKPError
from ipfs_datasets_py.logic.zkp.backends import clear_backend_cache, get_backend, list_backends
from ipfs_datasets_py.logic.zkp.backends import provekit_ffi
from ipfs_datasets_py.logic.zkp.backends.provekit_ffi import (
    PKBuf,
    PK_INPUT_FORMAT_JSON,
    PK_INPUT_FORMAT_TOML,
    PK_INVALID_INPUT,
    PK_PROOF_ERROR,
    PK_SUCCESS,
    PK_WITNESS_READ_ERROR,
    ProveKitFFI,
    ProveKitFFIError,
    ProveKitProverHandle,
    ProveKitVerifierHandle,
    discover_provekit_ffi_library,
)


class RecordingLock:
    def __init__(self) -> None:
        self.depth = 0
        self.entries = 0

    def __enter__(self) -> "RecordingLock":
        self.depth += 1
        self.entries += 1
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.depth -= 1


class FakeCFunction:
    def __init__(self, name, func, lock: RecordingLock | None = None) -> None:
        self.name = name
        self.func = func
        self.lock = lock
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        if self.lock is not None:
            assert self.lock.depth > 0, f"{self.name} called outside process-local lock"
        self.calls.append(args)
        return self.func(*args)


class FakeProveKitLibrary:
    def __init__(self, lock: RecordingLock | None = None) -> None:
        self.prover_value = 0xA11CE
        self.verifier_value = 0xB0B
        self.proof_bytes = b"\x00provekit-proof\xff"
        self.last_error = b""
        self.verify_status = PK_SUCCESS
        self.prove_toml_status = PK_SUCCESS
        self.prove_inputs_status = PK_SUCCESS
        self.failure_allocates_buffer = False
        self.buffers = []
        self.freed_buffer_lengths = []
        self.freed_provers = []
        self.freed_verifiers = []
        self.memory_config = None
        self.prove_inputs_record = None
        self.verify_record = None

        self.pk_init = FakeCFunction("pk_init", self._pk_init, lock)
        self.pk_configure_memory = FakeCFunction(
            "pk_configure_memory",
            self._pk_configure_memory,
            lock,
        )
        self.pk_load_prover = FakeCFunction("pk_load_prover", self._pk_load_prover, lock)
        self.pk_load_verifier = FakeCFunction("pk_load_verifier", self._pk_load_verifier, lock)
        self.pk_prove_inputs = FakeCFunction("pk_prove_inputs", self._pk_prove_inputs, lock)
        self.pk_prove_toml = FakeCFunction("pk_prove_toml", self._pk_prove_toml, lock)
        self.pk_verify = FakeCFunction("pk_verify", self._pk_verify, lock)
        self.pk_get_last_error = FakeCFunction(
            "pk_get_last_error",
            self._pk_get_last_error,
            lock,
        )
        self.pk_free_buf = FakeCFunction("pk_free_buf", self._pk_free_buf, lock)
        self.pk_free_prover = FakeCFunction("pk_free_prover", self._pk_free_prover, lock)
        self.pk_free_verifier = FakeCFunction("pk_free_verifier", self._pk_free_verifier, lock)

    def _pk_init(self):
        return PK_SUCCESS

    def _pk_configure_memory(self, ram_limit, use_file_backed, swap_file_path):
        self.memory_config = (
            int(ram_limit.value),
            bool(use_file_backed.value),
            os.fsdecode(swap_file_path) if swap_file_path else None,
        )
        return PK_SUCCESS

    def _pk_load_prover(self, path, out):
        assert path.endswith(b".pkp")
        out._obj.value = self.prover_value
        return PK_SUCCESS

    def _pk_load_verifier(self, path, out):
        assert path.endswith(b".pkv")
        out._obj.value = self.verifier_value
        return PK_SUCCESS

    def _pk_prove_inputs(self, prover, inputs, input_format, out):
        self.prove_inputs_record = (
            prover.value,
            bytes(inputs),
            int(input_format.value),
        )
        if self.prove_inputs_status != PK_SUCCESS:
            if self.failure_allocates_buffer:
                self._write_buf(out, b"partial")
            return self.prove_inputs_status
        self._write_buf(out, self.proof_bytes)
        return PK_SUCCESS

    def _pk_prove_toml(self, prover, toml_path, out):
        if self.prove_toml_status != PK_SUCCESS:
            if self.failure_allocates_buffer:
                self._write_buf(out, b"partial")
            return self.prove_toml_status
        self._write_buf(out, self.proof_bytes)
        return PK_SUCCESS

    def _pk_verify(self, verifier, proof_ptr, proof_len):
        self.verify_record = (
            verifier.value,
            ctypes.string_at(proof_ptr, int(proof_len.value)),
            int(proof_len.value),
        )
        return self.verify_status

    def _pk_get_last_error(self, out):
        self._write_buf(out, self.last_error)
        self.last_error = b""
        return PK_SUCCESS

    def _pk_free_buf(self, buf_ref):
        buf = buf_ref._obj
        self.freed_buffer_lengths.append(int(buf.len))
        buf.ptr = ctypes.POINTER(ctypes.c_uint8)()
        buf.len = 0
        buf.cap = 0

    def _pk_free_prover(self, prover):
        self.freed_provers.append(prover.value)

    def _pk_free_verifier(self, verifier):
        self.freed_verifiers.append(verifier.value)

    def _write_buf(self, out, data: bytes) -> None:
        array_type = ctypes.c_uint8 * len(data)
        array = array_type(*data)
        self.buffers.append(array)
        buf = out._obj
        buf.ptr = ctypes.cast(array, ctypes.POINTER(ctypes.c_uint8))
        buf.len = len(data)
        buf.cap = len(data)


def test_ctypes_prototypes_cover_required_provekit_ffi_symbols():
    fake = FakeProveKitLibrary()

    ProveKitFFI(library=fake)

    assert fake.pk_init.argtypes == []
    assert fake.pk_init.restype is ctypes.c_int
    assert fake.pk_configure_memory.argtypes == [
        ctypes.c_size_t,
        ctypes.c_bool,
        ctypes.c_char_p,
    ]
    assert fake.pk_load_prover.argtypes == [
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    assert fake.pk_load_verifier.argtypes == [
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    assert fake.pk_prove_inputs.argtypes == [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.POINTER(PKBuf),
    ]
    assert fake.pk_prove_toml.argtypes == [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.POINTER(PKBuf),
    ]
    assert fake.pk_verify.argtypes == [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_size_t,
    ]
    assert fake.pk_get_last_error.argtypes == [ctypes.POINTER(PKBuf)]
    assert fake.pk_free_buf.argtypes == [ctypes.POINTER(PKBuf)]


def test_memory_configuration_and_init_are_serialized_by_process_lock(monkeypatch, tmp_path):
    lock = RecordingLock()
    fake = FakeProveKitLibrary(lock)
    monkeypatch.setattr(provekit_ffi, "_FFI_LOCK", lock)
    ffi = ProveKitFFI(library=fake)

    ffi.configure_memory(
        32 * 1024 * 1024,
        use_file_backed=True,
        swap_file_path=tmp_path,
    )
    ffi.init()

    assert fake.memory_config == (32 * 1024 * 1024, True, str(tmp_path))
    assert fake.pk_configure_memory.calls
    assert fake.pk_init.calls
    assert lock.entries >= 2

    with pytest.raises(ZKPError, match="before pk_init"):
        ffi.configure_memory(64 * 1024 * 1024)


def test_loads_and_frees_prover_and_verifier_handles():
    fake = FakeProveKitLibrary()
    ffi = ProveKitFFI(library=fake)

    prover = ffi.load_prover("/keys/circuit.pkp")
    verifier = ffi.load_verifier("/keys/circuit.pkv")

    assert prover.handle.value == fake.prover_value
    assert verifier.handle.value == fake.verifier_value

    prover.close()
    prover.close()
    verifier.close()

    assert fake.freed_provers == [fake.prover_value]
    assert fake.freed_verifiers == [fake.verifier_value]


def test_prove_inputs_returns_binary_proof_and_always_frees_buffer():
    fake = FakeProveKitLibrary()
    ffi = ProveKitFFI(library=fake, auto_init=True)
    prover = ProveKitProverHandle(ffi, ctypes.c_void_p(fake.prover_value))

    proof = ffi.prove_inputs(
        prover,
        '{"secret":"do-not-log","public":"ok"}',
        input_format="json",
    )

    assert proof == fake.proof_bytes
    assert fake.prove_inputs_record == (
        fake.prover_value,
        b'{"secret":"do-not-log","public":"ok"}',
        PK_INPUT_FORMAT_JSON,
    )
    assert fake.freed_buffer_lengths == [len(fake.proof_bytes)]


def test_prove_inputs_accepts_toml_format_constant():
    fake = FakeProveKitLibrary()
    ffi = ProveKitFFI(library=fake, auto_init=True)
    prover = ProveKitProverHandle(ffi, ctypes.c_void_p(fake.prover_value))

    ffi.prove_inputs(prover, 'x = "5"\n', input_format=PK_INPUT_FORMAT_TOML)

    assert fake.prove_inputs_record[2] == PK_INPUT_FORMAT_TOML


def test_prove_toml_failure_retrieves_sanitized_error_and_cleans_buffers(tmp_path):
    fake = FakeProveKitLibrary()
    fake.prove_toml_status = PK_WITNESS_READ_ERROR
    fake.failure_allocates_buffer = True
    secret_toml = tmp_path / "private" / "Prover.toml"
    fake.last_error = f"could not parse {secret_toml}".encode("utf-8")
    ffi = ProveKitFFI(library=fake, auto_init=True)
    prover = ProveKitProverHandle(ffi, ctypes.c_void_p(fake.prover_value))

    with pytest.raises(ProveKitFFIError) as exc:
        ffi.prove_toml(prover, secret_toml)

    error = str(exc.value)
    assert "PK_WITNESS_READ_ERROR" in error
    assert str(secret_toml) not in error
    assert "<redacted:provekit-ffi-sensitive>" in error
    assert fake.pk_get_last_error.calls
    assert fake.freed_buffer_lengths == [len(b"partial"), len(f"could not parse {secret_toml}".encode("utf-8"))]


def test_verify_maps_invalid_proofs_to_false_and_other_errors_to_exception():
    fake = FakeProveKitLibrary()
    ffi = ProveKitFFI(library=fake, auto_init=True)
    verifier = ProveKitVerifierHandle(ffi, ctypes.c_void_p(fake.verifier_value))

    fake.verify_status = PK_SUCCESS
    assert ffi.verify(verifier, b"proof") is True
    assert fake.verify_record == (fake.verifier_value, b"proof", 5)

    fake.verify_status = PK_PROOF_ERROR
    fake.last_error = b"invalid proof"
    assert ffi.verify(verifier, b"bad proof") is False
    assert fake.pk_get_last_error.calls

    fake.verify_status = PK_INVALID_INPUT
    fake.last_error = b"bad verifier"
    with pytest.raises(ProveKitFFIError, match="PK_INVALID_INPUT"):
        ffi.verify(verifier, b"proof")


def test_library_discovery_is_fail_closed_for_invalid_explicit_path(tmp_path):
    missing = tmp_path / "missing" / "libprovekit_ffi.so"

    with pytest.raises(ZKPError, match="does not exist"):
        discover_provekit_ffi_library(
            env={"IPFS_DATASETS_PROVEKIT_FFI_LIBRARY": str(missing)},
            search_path=False,
        )

    assert (
        discover_provekit_ffi_library(
            env={},
            package_dir=tmp_path,
            search_path=False,
        )
        is None
    )


def test_cli_backend_remains_default_for_production_provekit_path():
    clear_backend_cache()

    backend = get_backend("provekit")
    metadata = list_backends()["provekit"]

    assert backend.__class__.__name__ == "ProveKitBackend"
    assert metadata["module"] == "provekit"
    assert metadata["class_name"] == "ProveKitBackend"
    assert metadata["module"] != "provekit_ffi"
