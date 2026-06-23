"""ctypes prototype wrapper for the ProveKit native FFI.

This module is intentionally not registered as the production ProveKit backend.
The CLI-backed ``backends.provekit`` path remains the default production
integration while this wrapper proves out the native ABI surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import ctypes
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_bool,
    c_char_p,
    c_int,
    c_size_t,
    c_uint8,
    c_void_p,
)
import ctypes.util
import os
from pathlib import Path
import threading
from typing import Any, Iterable, Mapping, Optional

from .. import ZKPError


PK_SUCCESS = 0
PK_INVALID_INPUT = 1
PK_SCHEME_READ_ERROR = 2
PK_WITNESS_READ_ERROR = 3
PK_PROOF_ERROR = 4
PK_SERIALIZATION_ERROR = 5
PK_UTF8_ERROR = 6
PK_FILE_WRITE_ERROR = 7
PK_COMPILATION_ERROR = 8

PK_INPUT_FORMAT_JSON = 0
PK_INPUT_FORMAT_TOML = 1

PROVEKIT_FFI_LIBRARY_ENV_VARS = (
    "IPFS_DATASETS_PROVEKIT_FFI_LIBRARY",
    "IPFS_DATASETS_PROVEKIT_FFI",
    "PROVEKIT_FFI_LIBRARY",
    "PROVEKIT_FFI",
)
PROVEKIT_FFI_HOME_ENV_VARS = (
    "IPFS_DATASETS_PROVEKIT_FFI_HOME",
    "PROVEKIT_FFI_HOME",
)

_STATUS_NAMES = {
    PK_SUCCESS: "PK_SUCCESS",
    PK_INVALID_INPUT: "PK_INVALID_INPUT",
    PK_SCHEME_READ_ERROR: "PK_SCHEME_READ_ERROR",
    PK_WITNESS_READ_ERROR: "PK_WITNESS_READ_ERROR",
    PK_PROOF_ERROR: "PK_PROOF_ERROR",
    PK_SERIALIZATION_ERROR: "PK_SERIALIZATION_ERROR",
    PK_UTF8_ERROR: "PK_UTF8_ERROR",
    PK_FILE_WRITE_ERROR: "PK_FILE_WRITE_ERROR",
    PK_COMPILATION_ERROR: "PK_COMPILATION_ERROR",
}

_FFI_LOCK = threading.RLock()


class PKBuf(Structure):
    """Buffer returned by ProveKit FFI calls.

    The v1 ProveKit header includes ``cap`` so Rust can reconstruct and free the
    allocation correctly.
    """

    _fields_ = [
        ("ptr", POINTER(c_uint8)),
        ("len", c_size_t),
        ("cap", c_size_t),
    ]


class ProveKitFFIError(ZKPError):
    """Raised when a native ProveKit FFI call fails."""

    def __init__(self, operation: str, status_code: int, message: str = "") -> None:
        self.operation = operation
        self.status_code = int(status_code)
        self.status_name = _STATUS_NAMES.get(self.status_code, "PK_UNKNOWN")
        detail = f"ProveKit FFI {operation} failed with {self.status_name} ({self.status_code})"
        if message:
            detail = f"{detail}: {message}"
        super().__init__(detail)


def discover_provekit_ffi_library(
    *,
    env: Optional[Mapping[str, str]] = None,
    package_dir: Optional[str | os.PathLike[str]] = None,
    search_path: bool = True,
) -> Optional[Path]:
    """Discover a ProveKit FFI dynamic library without loading it.

    Explicit environment paths fail closed when missing. Packaged and system
    lookup candidates return ``None`` when unavailable.
    """

    env_map = os.environ if env is None else env

    for var_name in PROVEKIT_FFI_LIBRARY_ENV_VARS:
        raw = str(env_map.get(var_name) or "").strip()
        if raw:
            return _require_library_file(Path(raw), source=var_name)

    names = _library_names()
    for var_name in PROVEKIT_FFI_HOME_ENV_VARS:
        raw = str(env_map.get(var_name) or "").strip()
        if not raw:
            continue
        root = Path(raw)
        candidates = tuple(root / "lib" / name for name in names) + tuple(
            root / "target" / "release" / name for name in names
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        tried = ", ".join(str(path) for path in candidates)
        raise ZKPError(
            f"{var_name} is set, but no ProveKit FFI library was found. Tried: {tried}"
        )

    package_root = Path(package_dir) if package_dir is not None else Path(__file__).resolve().parent
    for candidate in tuple(package_root / "ffi" / name for name in names) + tuple(
        package_root / "bin" / name for name in names
    ):
        if candidate.is_file():
            return candidate

    if search_path:
        found = ctypes.util.find_library("provekit_ffi")
        if found:
            return Path(found)

    return None


@dataclass
class ProveKitProverHandle:
    """Owned ProveKit prover handle."""

    ffi: "ProveKitFFI"
    handle: c_void_p
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self.ffi.free_prover(self)
        self._closed = True

    def __enter__(self) -> "ProveKitProverHandle":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


@dataclass
class ProveKitVerifierHandle:
    """Owned ProveKit verifier handle."""

    ffi: "ProveKitFFI"
    handle: c_void_p
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self.ffi.free_verifier(self)
        self._closed = True

    def __enter__(self) -> "ProveKitVerifierHandle":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


@dataclass
class ProveKitFFI:
    """Locked ctypes facade for ``provekit-ffi``.

    ``library`` exists for unit tests and embedders that already loaded a CDLL.
    Passing neither ``library`` nor ``library_path`` triggers discovery but does
    not mutate backend selection or invoke the ProveKit CLI.
    """

    library_path: Optional[str | os.PathLike[str]] = None
    library: Any = None
    auto_init: bool = False
    _initialized: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.library is None:
            path = Path(self.library_path) if self.library_path is not None else discover_provekit_ffi_library()
            if path is None:
                raise ZKPError(
                    "ProveKit FFI library not found. Set "
                    "IPFS_DATASETS_PROVEKIT_FFI_LIBRARY or keep using the "
                    "CLI-backed ProveKit backend."
                )
            if self.library_path is not None and not path.is_file():
                raise ZKPError(f"Configured ProveKit FFI library does not exist: {path}")
            self.library_path = str(path)
            self.library = ctypes.CDLL(str(path))

        self._configure_prototypes()
        if self.auto_init:
            self.init()

    def init(self) -> None:
        """Call ``pk_init`` once for this wrapper instance."""

        if self._initialized:
            return
        with _FFI_LOCK:
            if self._initialized:
                return
            self._check_status(int(self.library.pk_init()), "pk_init")
            self._initialized = True

    def configure_memory(
        self,
        ram_limit_bytes: int,
        *,
        use_file_backed: bool = False,
        swap_file_path: Optional[str | os.PathLike[str]] = None,
    ) -> None:
        """Call ``pk_configure_memory`` before initialization."""

        if self._initialized:
            raise ZKPError("ProveKit FFI memory must be configured before pk_init")
        if not isinstance(ram_limit_bytes, int) or ram_limit_bytes <= 0:
            raise ValueError("ram_limit_bytes must be a positive integer")

        swap_path = _encode_path(swap_file_path) if swap_file_path is not None else None
        with _FFI_LOCK:
            self._check_status(
                int(
                    self.library.pk_configure_memory(
                        c_size_t(ram_limit_bytes),
                        c_bool(bool(use_file_backed)),
                        swap_path,
                    )
                ),
                "pk_configure_memory",
                sensitive_values=(str(swap_file_path),) if swap_file_path is not None else (),
            )

    def load_prover(self, path: str | os.PathLike[str]) -> ProveKitProverHandle:
        """Load a ``.pkp`` prover key with ``pk_load_prover``."""

        self.init()
        out = c_void_p()
        encoded = _encode_path(path)
        with _FFI_LOCK:
            self._check_status(
                int(self.library.pk_load_prover(encoded, byref(out))),
                "pk_load_prover",
                sensitive_values=(str(path),),
            )
        return ProveKitProverHandle(self, _require_handle(out, "pk_load_prover"))

    def load_verifier(self, path: str | os.PathLike[str]) -> ProveKitVerifierHandle:
        """Load a ``.pkv`` verifier key with ``pk_load_verifier``."""

        self.init()
        out = c_void_p()
        encoded = _encode_path(path)
        with _FFI_LOCK:
            self._check_status(
                int(self.library.pk_load_verifier(encoded, byref(out))),
                "pk_load_verifier",
                sensitive_values=(str(path),),
            )
        return ProveKitVerifierHandle(self, _require_handle(out, "pk_load_verifier"))

    def prove_toml(
        self,
        prover: ProveKitProverHandle | c_void_p,
        toml_path: str | os.PathLike[str],
    ) -> bytes:
        """Generate proof bytes from a TOML witness path with ``pk_prove_toml``."""

        self.init()
        out = PKBuf()
        encoded = _encode_path(toml_path)
        sensitive_values = (str(toml_path),)
        with _FFI_LOCK:
            status = int(
                self.library.pk_prove_toml(
                    _handle_value(prover, "prover"),
                    encoded,
                    byref(out),
                )
            )
            if status != PK_SUCCESS:
                self._free_buf_if_allocated(out)
                self._raise_status("pk_prove_toml", status, sensitive_values=sensitive_values)
            return self._read_and_free_buf(out)

    def prove_inputs(
        self,
        prover: ProveKitProverHandle | c_void_p,
        inputs: str | bytes,
        *,
        input_format: str | int = "json",
    ) -> bytes:
        """Generate proof bytes from in-memory JSON or TOML inputs."""

        self.init()
        encoded = _encode_text(inputs)
        fmt = _input_format_value(input_format)
        out = PKBuf()
        sensitive_values = (_decode_for_sanitize(encoded),)
        with _FFI_LOCK:
            status = int(
                self.library.pk_prove_inputs(
                    _handle_value(prover, "prover"),
                    encoded,
                    c_int(fmt),
                    byref(out),
                )
            )
            if status != PK_SUCCESS:
                self._free_buf_if_allocated(out)
                self._raise_status("pk_prove_inputs", status, sensitive_values=sensitive_values)
            return self._read_and_free_buf(out)

    def verify(self, verifier: ProveKitVerifierHandle | c_void_p, proof: bytes | bytearray | memoryview) -> bool:
        """Verify proof bytes with ``pk_verify``.

        Returns ``False`` for invalid proofs. Other native failures raise
        ``ProveKitFFIError``.
        """

        self.init()
        proof_bytes = bytes(proof)
        if not proof_bytes:
            return False

        proof_buf = (c_uint8 * len(proof_bytes)).from_buffer_copy(proof_bytes)
        with _FFI_LOCK:
            status = int(
                self.library.pk_verify(
                    _handle_value(verifier, "verifier"),
                    proof_buf,
                    c_size_t(len(proof_bytes)),
                )
            )
            if status == PK_SUCCESS:
                return True
            if status == PK_PROOF_ERROR:
                self.get_last_error()
                return False
            self._raise_status("pk_verify", status)
        return False

    def get_last_error(self, *, sensitive_values: Iterable[str] = ()) -> str:
        """Return and clear the last native error string."""

        out = PKBuf()
        with _FFI_LOCK:
            status = int(self.library.pk_get_last_error(byref(out)))
            if status != PK_SUCCESS:
                self._free_buf_if_allocated(out)
                return ""
            raw = self._read_and_free_buf(out)
        text = raw.decode("utf-8", errors="replace")
        return _sanitize_text(text, sensitive_values)

    def free_prover(self, prover: ProveKitProverHandle | c_void_p) -> None:
        """Free an owned prover handle with ``pk_free_prover``."""

        with _FFI_LOCK:
            self.library.pk_free_prover(_handle_value(prover, "prover"))

    def free_verifier(self, verifier: ProveKitVerifierHandle | c_void_p) -> None:
        """Free an owned verifier handle with ``pk_free_verifier``."""

        with _FFI_LOCK:
            self.library.pk_free_verifier(_handle_value(verifier, "verifier"))

    def free_buf(self, buf: PKBuf) -> None:
        """Free a native buffer with ``pk_free_buf``."""

        with _FFI_LOCK:
            self._free_buf_if_allocated(buf)

    def _configure_prototypes(self) -> None:
        lib = self.library

        lib.pk_init.argtypes = []
        lib.pk_init.restype = c_int

        lib.pk_configure_memory.argtypes = [c_size_t, c_bool, c_char_p]
        lib.pk_configure_memory.restype = c_int

        lib.pk_load_prover.argtypes = [c_char_p, POINTER(c_void_p)]
        lib.pk_load_prover.restype = c_int

        lib.pk_load_verifier.argtypes = [c_char_p, POINTER(c_void_p)]
        lib.pk_load_verifier.restype = c_int

        lib.pk_prove_inputs.argtypes = [c_void_p, c_char_p, c_int, POINTER(PKBuf)]
        lib.pk_prove_inputs.restype = c_int

        lib.pk_prove_toml.argtypes = [c_void_p, c_char_p, POINTER(PKBuf)]
        lib.pk_prove_toml.restype = c_int

        lib.pk_verify.argtypes = [c_void_p, POINTER(c_uint8), c_size_t]
        lib.pk_verify.restype = c_int

        lib.pk_get_last_error.argtypes = [POINTER(PKBuf)]
        lib.pk_get_last_error.restype = c_int

        lib.pk_free_buf.argtypes = [POINTER(PKBuf)]
        lib.pk_free_buf.restype = None

        lib.pk_free_prover.argtypes = [c_void_p]
        lib.pk_free_prover.restype = None

        lib.pk_free_verifier.argtypes = [c_void_p]
        lib.pk_free_verifier.restype = None

    def _check_status(
        self,
        status: int,
        operation: str,
        *,
        sensitive_values: Iterable[str] = (),
    ) -> None:
        if status == PK_SUCCESS:
            return
        self._raise_status(operation, status, sensitive_values=sensitive_values)

    def _raise_status(
        self,
        operation: str,
        status: int,
        *,
        sensitive_values: Iterable[str] = (),
    ) -> None:
        message = self.get_last_error(sensitive_values=sensitive_values)
        raise ProveKitFFIError(operation, status, message)

    def _read_and_free_buf(self, buf: PKBuf) -> bytes:
        try:
            if not bool(buf.ptr) or int(buf.len) <= 0:
                return b""
            return ctypes.string_at(buf.ptr, int(buf.len))
        finally:
            self._free_buf_if_allocated(buf)

    def _free_buf_if_allocated(self, buf: PKBuf) -> None:
        if bool(buf.ptr):
            self.library.pk_free_buf(byref(buf))


def _library_names() -> tuple[str, ...]:
    if os.name == "nt":
        return ("provekit_ffi.dll",)
    if os.uname().sysname.lower() == "darwin":
        return ("libprovekit_ffi.dylib", "libprovekit_ffi.a")
    return ("libprovekit_ffi.so", "libprovekit_ffi.a")


def _require_library_file(path: Path, *, source: str) -> Path:
    if path.is_file():
        return path
    raise ZKPError(f"Configured ProveKit FFI library from {source} does not exist: {path}")


def _encode_path(path: str | os.PathLike[str] | None) -> bytes | None:
    if path is None:
        return None
    return os.fsencode(Path(path))


def _encode_text(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise TypeError("inputs must be str or bytes")


def _decode_for_sanitize(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _sanitize_text(value: str, sensitive_values: Iterable[str]) -> str:
    sanitized = str(value)
    for sensitive in sorted({str(v) for v in sensitive_values if str(v)}, key=len, reverse=True):
        sanitized = sanitized.replace(sensitive, "<redacted:provekit-ffi-sensitive>")
    return sanitized


def _input_format_value(input_format: str | int) -> int:
    if isinstance(input_format, int):
        if input_format in {PK_INPUT_FORMAT_JSON, PK_INPUT_FORMAT_TOML}:
            return input_format
        raise ValueError("input_format integer must be PK_INPUT_FORMAT_JSON or PK_INPUT_FORMAT_TOML")

    normalized = str(input_format).strip().lower()
    if normalized == "json":
        return PK_INPUT_FORMAT_JSON
    if normalized == "toml":
        return PK_INPUT_FORMAT_TOML
    raise ValueError("input_format must be 'json', 'toml', PK_INPUT_FORMAT_JSON, or PK_INPUT_FORMAT_TOML")


def _handle_value(
    handle: ProveKitProverHandle | ProveKitVerifierHandle | c_void_p,
    label: str,
) -> c_void_p:
    raw = handle.handle if isinstance(handle, (ProveKitProverHandle, ProveKitVerifierHandle)) else handle
    if not isinstance(raw, c_void_p):
        raise TypeError(f"{label} handle must be a ctypes.c_void_p or ProveKit handle")
    return _require_handle(raw, label)


def _require_handle(handle: c_void_p, label: str) -> c_void_p:
    if not bool(handle.value):
        raise ProveKitFFIError(label, PK_INVALID_INPUT, "native handle was null")
    return handle


__all__ = [
    "PKBuf",
    "PK_SUCCESS",
    "PK_INVALID_INPUT",
    "PK_SCHEME_READ_ERROR",
    "PK_WITNESS_READ_ERROR",
    "PK_PROOF_ERROR",
    "PK_SERIALIZATION_ERROR",
    "PK_UTF8_ERROR",
    "PK_FILE_WRITE_ERROR",
    "PK_COMPILATION_ERROR",
    "PK_INPUT_FORMAT_JSON",
    "PK_INPUT_FORMAT_TOML",
    "ProveKitFFI",
    "ProveKitFFIError",
    "ProveKitProverHandle",
    "ProveKitVerifierHandle",
    "discover_provekit_ffi_library",
]
