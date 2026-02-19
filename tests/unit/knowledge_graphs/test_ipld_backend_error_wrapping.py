import pytest

from ipfs_datasets_py.knowledge_graphs.exceptions import DeserializationError, SerializationError
from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import IPLDBackend


class _DummyBackend:
    def __init__(self, payload: bytes):
        self._payload = payload

    def block_get(self, cid: str) -> bytes:
        return self._payload


def _backend_with_dummy(payload: bytes) -> IPLDBackend:
    backend = IPLDBackend.__new__(IPLDBackend)
    backend._backend = _DummyBackend(payload)
    backend._cache = None
    backend._get_backend = lambda: backend._backend  # type: ignore[method-assign]
    backend.pin_by_default = False
    backend.database = "test"
    backend._namespace = "kg:db:test:"
    return backend


def test_retrieve_json_wraps_invalid_utf8() -> None:
    backend = _backend_with_dummy(b"\xff\xff")

    with pytest.raises(DeserializationError):
        backend.retrieve_json("bafy-invalid")


def test_retrieve_json_wraps_invalid_json() -> None:
    backend = _backend_with_dummy(b"{")

    with pytest.raises(DeserializationError):
        backend.retrieve_json("bafy-invalid")


def test_store_wraps_unsupported_type_as_serialization_error() -> None:
    backend = _backend_with_dummy(b"{}");

    class _Nope:
        pass

    with pytest.raises(SerializationError):
        backend.store(_Nope())
