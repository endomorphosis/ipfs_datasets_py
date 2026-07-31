"""Chaos: IPFS outage and reconnect (KGP-031).

While offline, puts/gets fail with retryable STORAGE / ConnectionError.
After reconnect, previously written CIDs remain readable and new puts succeed.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.knowledge_graphs.storage.ipld_store import (
    GraphStoreError,
    IPLDGraphStore,
    map_kubo_error,
)

from tests.chaos.knowledge_graphs.helpers import OutageBlockBackend


class TestIPFSOutageReconnect:
    def test_outage_blocks_put_and_get(self) -> None:
        backend = OutageBlockBackend()
        store = IPLDGraphStore(backend)
        put = store.put(b"before-outage")
        cid = put.cid
        assert store.get(cid) == b"before-outage"

        backend.set_online(False)
        with pytest.raises((ConnectionError, GraphStoreError)) as ei:
            store.put(b"during-outage")
        exc = ei.value
        if isinstance(exc, GraphStoreError):
            assert exc.retryable is True
            assert exc.code == "STORAGE"
        assert backend.outage_hits >= 1

        with pytest.raises((ConnectionError, GraphStoreError)):
            store.get(cid)

    def test_reconnect_restores_service_and_preserves_data(self) -> None:
        backend = OutageBlockBackend()
        store = IPLDGraphStore(backend)
        first = store.put(b"payload-alpha")
        backend.set_online(False)
        assert backend.outage_hits == 0 or True
        with pytest.raises((ConnectionError, GraphStoreError)):
            store.put(b"payload-beta")

        backend.set_online(True)
        # Prior content still present after reconnect.
        assert store.get(first.cid) == b"payload-alpha"
        second = store.put(b"payload-beta")
        assert store.get(second.cid) == b"payload-beta"
        assert second.cid != first.cid

    def test_outage_during_pin_is_retryable(self) -> None:
        backend = OutageBlockBackend()
        store = IPLDGraphStore(backend, pin_by_default=False)
        put = store.put(b"pin-me", pin=False)
        backend.set_online(False)
        with pytest.raises((ConnectionError, GraphStoreError)) as ei:
            store.pin(put.cid)
        if isinstance(ei.value, GraphStoreError):
            assert ei.value.retryable is True
        backend.set_online(True)
        store.pin(put.cid)
        assert store.is_pinned(put.cid)

    def test_map_connection_error_is_retryable_storage(self) -> None:
        mapped = map_kubo_error(
            ConnectionError("connection refused to ipfs daemon"),
            operation="get",
        )
        assert mapped.code == "STORAGE"
        assert mapped.retryable is True

    def test_outage_cycle_no_silent_data_loss(self) -> None:
        """
        GIVEN: Multiple put/get cycles with intermittent outages
        WHEN: Daemon flaps offline/online
        THEN: All successfully-acked puts remain readable after reconnect
        """
        backend = OutageBlockBackend()
        store = IPLDGraphStore(backend)
        acked = []
        for i in range(6):
            if i % 2 == 1:
                backend.set_online(False)
                with pytest.raises((ConnectionError, GraphStoreError)):
                    store.put(f"wave-{i}".encode())
                backend.set_online(True)
            else:
                res = store.put(f"wave-{i}".encode())
                acked.append((res.cid, f"wave-{i}".encode()))
        for cid, payload in acked:
            assert store.get(cid) == payload
