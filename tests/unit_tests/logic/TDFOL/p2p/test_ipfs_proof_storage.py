"""
Tests for TDFOL IPFS Proof Storage Module

Tests for IPFSProofStorage: init, store_proof, retrieve_proof,
retrieve_with_metadata, list_cached_proofs, clear_cache, unpin_proof,
_serialize_proof_result, _deserialize_proof_result, get_default_proof_storage.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

import ipfs_datasets_py.logic.TDFOL.p2p.ipfs_proof_storage as mod
from ipfs_datasets_py.logic.TDFOL.p2p.ipfs_proof_storage import (
    IPFSProofStorage,
    get_default_proof_storage,
    IPFS_AVAILABLE,
    TDFOL_AVAILABLE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeProofResult:
    """Minimal proof result object for serialization tests."""
    proved = True
    status = "proved"
    proof_steps = None
    countermodel = None
    time_ms = 42


class FakeProofResultWithSteps:
    proved = True
    status = "proved"
    time_ms = 10
    countermodel = None

    @property
    def proof_steps(self):
        step = MagicMock()
        step.formula = MagicMock()
        step.formula.__str__ = lambda _: "P(x)"
        step.rule = "modus ponens"
        step.premises = ["hyp1"]
        return [step]


class FakeProofResultWithCountermodel:
    proved = False
    status = "disproved"
    proof_steps = None
    time_ms = 5

    @property
    def countermodel(self):
        return object()  # non-None truthy countermodel


def _make_storage_json(formula="P", proved=True):
    return json.dumps({
        "formula": formula,
        "proof_result": {
            "status": "proved" if proved else "disproved",
            "proved": proved,
            "proof_steps": [],
            "time_ms": 0,
            "countermodel": None,
        },
        "metadata": {"info": "test"},
        "version": "1.0",
    }).encode()


def _make_mock_backend(cid="QmTestCID123", cat_return=None):
    backend = MagicMock()
    backend.add_bytes.return_value = cid
    backend.cat.return_value = cat_return or _make_storage_json()
    backend.unpin.return_value = None
    return backend


# ---------------------------------------------------------------------------
# Tests: __init__
# ---------------------------------------------------------------------------

class TestIPFSProofStorageInit:
    """Test IPFSProofStorage initialization."""

    def test_init_ipfs_not_available(self):
        """GIVEN IPFS_AVAILABLE is False THEN storage.available is False."""
        with patch.object(mod, "IPFS_AVAILABLE", False):
            storage = IPFSProofStorage()
        assert storage.available is False
        assert storage.backend is None

    def test_init_with_explicit_backend(self):
        """GIVEN IPFS available and explicit backend THEN storage.available is True."""
        backend = _make_mock_backend()
        with patch.object(mod, "IPFS_AVAILABLE", True):
            storage = IPFSProofStorage(backend=backend)
        assert storage.available is True
        assert storage.backend is backend
        assert storage._pinned_cids == []

    def test_init_no_backend_resolves_to_none(self):
        """GIVEN IPFS available but get_backend returns None THEN storage.available is False."""
        with patch.object(mod, "IPFS_AVAILABLE", True), \
             patch.object(mod, "get_backend", return_value=None):
            storage = IPFSProofStorage()
        assert storage.available is False

    def test_init_get_backend_called_when_no_explicit(self):
        """GIVEN no backend arg WHEN IPFS available THEN get_backend is called."""
        fake_backend = _make_mock_backend()
        with patch.object(mod, "IPFS_AVAILABLE", True), \
             patch.object(mod, "get_backend", return_value=fake_backend) as mock_gb:
            storage = IPFSProofStorage()
        mock_gb.assert_called_once()
        assert storage.available is True


# ---------------------------------------------------------------------------
# Tests: store_proof
# ---------------------------------------------------------------------------

class TestStoreProof:
    """Test store_proof method."""

    def _make_available_storage(self, cid="QmTestCID123"):
        backend = _make_mock_backend(cid=cid)
        with patch.object(mod, "IPFS_AVAILABLE", True):
            storage = IPFSProofStorage(backend=backend)
        return storage, backend

    def test_store_proof_returns_none_when_not_available(self):
        """GIVEN storage not available THEN store_proof returns None."""
        with patch.object(mod, "IPFS_AVAILABLE", False):
            storage = IPFSProofStorage()
        result = storage.store_proof("P", FakeProofResult())
        assert result is None

    def test_store_proof_success(self):
        """GIVEN available backend THEN store_proof returns CID."""
        storage, backend = self._make_available_storage(cid="QmABC")
        result = storage.store_proof("P", FakeProofResult())
        assert result == "QmABC"

    def test_store_proof_tracks_pinned_cid(self):
        """GIVEN a successful store THEN CID is tracked in _pinned_cids."""
        storage, _ = self._make_available_storage(cid="QmXYZ")
        storage.store_proof("P", FakeProofResult())
        assert "QmXYZ" in storage._pinned_cids

    def test_store_proof_does_not_duplicate_cid(self):
        """GIVEN same CID returned twice THEN _pinned_cids has it once."""
        storage, backend = self._make_available_storage(cid="QmSame")
        storage.store_proof("P", FakeProofResult())
        storage.store_proof("Q", FakeProofResult())
        assert storage._pinned_cids.count("QmSame") == 1

    def test_store_proof_with_metadata(self):
        """GIVEN metadata dict THEN backend receives JSON with metadata."""
        storage, backend = self._make_available_storage()
        storage.store_proof("P", FakeProofResult(), metadata={"source": "test"})
        call_args = backend.add_bytes.call_args
        payload = json.loads(call_args[0][0].decode())
        assert payload["metadata"]["source"] == "test"

    def test_store_proof_backend_exception_returns_none(self):
        """GIVEN backend raises exception THEN store_proof returns None."""
        storage, backend = self._make_available_storage()
        backend.add_bytes.side_effect = RuntimeError("network error")
        result = storage.store_proof("P", FakeProofResult())
        assert result is None

    def test_store_proof_with_proof_steps(self):
        """GIVEN proof result with steps THEN steps are serialised."""
        storage, backend = self._make_available_storage()
        result_cid = storage.store_proof("P", FakeProofResultWithSteps())
        assert result_cid is not None
        payload = json.loads(backend.add_bytes.call_args[0][0].decode())
        steps = payload["proof_result"]["proof_steps"]
        assert len(steps) == 1
        assert steps[0]["formula"] == "P(x)"
        assert steps[0]["rule"] == "modus ponens"
        assert steps[0]["premises"] == ["hyp1"]

    def test_store_proof_with_countermodel(self):
        """GIVEN proof result with countermodel THEN countermodel is stored as str."""
        storage, backend = self._make_available_storage()
        storage.store_proof("P", FakeProofResultWithCountermodel())
        payload = json.loads(backend.add_bytes.call_args[0][0].decode())
        assert payload["proof_result"]["countermodel"] is not None


# ---------------------------------------------------------------------------
# Tests: retrieve_proof
# ---------------------------------------------------------------------------

class TestRetrieveProof:
    """Test retrieve_proof method."""

    def _make_available_storage(self):
        backend = _make_mock_backend()
        with patch.object(mod, "IPFS_AVAILABLE", True):
            storage = IPFSProofStorage(backend=backend)
        return storage, backend

    def test_retrieve_proof_returns_none_when_not_available(self):
        with patch.object(mod, "IPFS_AVAILABLE", False):
            storage = IPFSProofStorage()
        assert storage.retrieve_proof("QmXXX") is None

    def test_retrieve_proof_success(self):
        """GIVEN valid JSON in backend THEN returns ProofResult proxy."""
        storage, backend = self._make_available_storage()
        backend.cat.return_value = _make_storage_json("P", proved=True)
        result = storage.retrieve_proof("QmABC")
        assert result is not None
        assert result.proved is True

    def test_retrieve_proof_disproved(self):
        """GIVEN proved=False JSON THEN result.proved is False."""
        storage, backend = self._make_available_storage()
        backend.cat.return_value = _make_storage_json("Q", proved=False)
        result = storage.retrieve_proof("QmDEF")
        assert result.proved is False

    def test_retrieve_proof_backend_exception_returns_none(self):
        """GIVEN backend raises exception THEN returns None."""
        storage, backend = self._make_available_storage()
        backend.cat.side_effect = RuntimeError("IPFS error")
        assert storage.retrieve_proof("QmERR") is None


# ---------------------------------------------------------------------------
# Tests: retrieve_with_metadata
# ---------------------------------------------------------------------------

class TestRetrieveWithMetadata:
    """Test retrieve_with_metadata method."""

    def _make_available_storage(self):
        backend = _make_mock_backend()
        with patch.object(mod, "IPFS_AVAILABLE", True):
            storage = IPFSProofStorage(backend=backend)
        return storage, backend

    def test_returns_none_when_not_available(self):
        with patch.object(mod, "IPFS_AVAILABLE", False):
            storage = IPFSProofStorage()
        assert storage.retrieve_with_metadata("QmX") is None

    def test_returns_full_storage_object(self):
        """GIVEN valid JSON THEN returns dict with formula + proof_result + metadata."""
        storage, backend = self._make_available_storage()
        backend.cat.return_value = _make_storage_json("P")
        result = storage.retrieve_with_metadata("QmABC")
        assert result is not None
        assert result["formula"] == "P"
        assert result["metadata"] == {"info": "test"}
        assert result["proof_result"] is not None

    def test_exception_returns_none(self):
        storage, backend = self._make_available_storage()
        backend.cat.side_effect = RuntimeError("err")
        assert storage.retrieve_with_metadata("QmX") is None


# ---------------------------------------------------------------------------
# Tests: list_cached_proofs
# ---------------------------------------------------------------------------

class TestListCachedProofs:
    """Test list_cached_proofs method."""

    def test_returns_empty_list_initially(self):
        with patch.object(mod, "IPFS_AVAILABLE", True):
            storage = IPFSProofStorage(backend=_make_mock_backend())
        assert storage.list_cached_proofs() == []

    def test_returns_copy_after_storing(self):
        backend = _make_mock_backend(cid="QmA")
        with patch.object(mod, "IPFS_AVAILABLE", True):
            storage = IPFSProofStorage(backend=backend)
        storage.store_proof("P", FakeProofResult())
        cids = storage.list_cached_proofs()
        assert "QmA" in cids
        # Modifying the returned list does not affect internal state
        cids.append("QmFake")
        assert "QmFake" not in storage._pinned_cids


# ---------------------------------------------------------------------------
# Tests: clear_cache
# ---------------------------------------------------------------------------

class TestClearCache:
    """Test clear_cache method."""

    def test_clear_cache_returns_zero_when_not_available(self):
        with patch.object(mod, "IPFS_AVAILABLE", False):
            storage = IPFSProofStorage()
        assert storage.clear_cache() == 0

    def test_clear_cache_unpins_all_proofs(self):
        backend = _make_mock_backend(cid="QmA")
        backend2 = _make_mock_backend(cid="QmB")
        with patch.object(mod, "IPFS_AVAILABLE", True):
            storage = IPFSProofStorage(backend=backend)
        storage.store_proof("P", FakeProofResult())
        # Manually add a second CID
        storage._pinned_cids.append("QmB")

        count = storage.clear_cache()
        assert count == 2
        assert storage._pinned_cids == []
        assert backend.unpin.call_count == 2

    def test_clear_cache_handles_unpin_failure(self):
        """GIVEN unpin raises THEN clears still proceeds for others."""
        backend = _make_mock_backend(cid="QmA")
        with patch.object(mod, "IPFS_AVAILABLE", True):
            storage = IPFSProofStorage(backend=backend)
        storage._pinned_cids = ["QmA", "QmB"]
        backend.unpin.side_effect = [RuntimeError("fail"), None]
        count = storage.clear_cache()
        assert count == 1  # Only QmB succeeded
        assert storage._pinned_cids == []


# ---------------------------------------------------------------------------
# Tests: unpin_proof
# ---------------------------------------------------------------------------

class TestUnpinProof:
    """Test unpin_proof method."""

    def test_returns_false_when_not_available(self):
        with patch.object(mod, "IPFS_AVAILABLE", False):
            storage = IPFSProofStorage()
        assert storage.unpin_proof("QmX") is False

    def test_unpin_success(self):
        backend = _make_mock_backend()
        with patch.object(mod, "IPFS_AVAILABLE", True):
            storage = IPFSProofStorage(backend=backend)
        storage._pinned_cids = ["QmA"]
        result = storage.unpin_proof("QmA")
        assert result is True
        assert "QmA" not in storage._pinned_cids

    def test_unpin_removes_from_pinned_cids(self):
        backend = _make_mock_backend()
        with patch.object(mod, "IPFS_AVAILABLE", True):
            storage = IPFSProofStorage(backend=backend)
        storage._pinned_cids = ["QmA", "QmB"]
        storage.unpin_proof("QmA")
        assert "QmA" not in storage._pinned_cids
        assert "QmB" in storage._pinned_cids

    def test_unpin_cid_not_in_pinned_still_succeeds(self):
        """GIVEN CID not tracked locally THEN unpin still calls backend."""
        backend = _make_mock_backend()
        with patch.object(mod, "IPFS_AVAILABLE", True):
            storage = IPFSProofStorage(backend=backend)
        result = storage.unpin_proof("QmNotTracked")
        assert result is True
        backend.unpin.assert_called_once_with("QmNotTracked")

    def test_unpin_backend_exception_returns_false(self):
        backend = _make_mock_backend()
        with patch.object(mod, "IPFS_AVAILABLE", True):
            storage = IPFSProofStorage(backend=backend)
        backend.unpin.side_effect = RuntimeError("error")
        result = storage.unpin_proof("QmA")
        assert result is False


# ---------------------------------------------------------------------------
# Tests: _serialize_proof_result
# ---------------------------------------------------------------------------

class TestSerializeProofResult:
    """Test _serialize_proof_result method."""

    def _make_storage(self):
        with patch.object(mod, "IPFS_AVAILABLE", False):
            return IPFSProofStorage()

    def test_basic_serialization(self):
        storage = self._make_storage()
        result = storage._serialize_proof_result(FakeProofResult())
        assert result["proved"] is True
        assert result["status"] == "proved"
        assert result["time_ms"] == 42
        assert result["proof_steps"] == []
        assert result["countermodel"] is None

    def test_serialization_with_steps(self):
        storage = self._make_storage()
        result = storage._serialize_proof_result(FakeProofResultWithSteps())
        assert len(result["proof_steps"]) == 1
        step = result["proof_steps"][0]
        assert step["formula"] == "P(x)"
        assert step["rule"] == "modus ponens"

    def test_serialization_with_countermodel(self):
        storage = self._make_storage()
        result = storage._serialize_proof_result(FakeProofResultWithCountermodel())
        assert result["countermodel"] is not None
        assert isinstance(result["countermodel"], str)

    def test_serialization_missing_time_ms(self):
        """GIVEN no time_ms attribute THEN defaults to 0."""
        class NoTimeMsResult:
            proved = False
            status = "unknown"
            proof_steps = None
            countermodel = None
        storage = self._make_storage()
        result = storage._serialize_proof_result(NoTimeMsResult())
        assert result["time_ms"] == 0


# ---------------------------------------------------------------------------
# Tests: _deserialize_proof_result
# ---------------------------------------------------------------------------

class TestDeserializeProofResult:
    """Test _deserialize_proof_result method."""

    def _make_storage(self):
        with patch.object(mod, "IPFS_AVAILABLE", False):
            return IPFSProofStorage()

    def test_deserialize_with_tdfol_available(self):
        """GIVEN TDFOL_AVAILABLE and valid proof data THEN returns proxy object."""
        storage = self._make_storage()
        data = {"status": "unknown", "proved": False, "proof_steps": [], "time_ms": 5, "countermodel": None}
        result = storage._deserialize_proof_result(data)
        assert result is not None
        assert result.proved is False

    def test_deserialize_without_tdfol(self):
        """GIVEN TDFOL not available THEN returns ProofResultProxy."""
        storage = self._make_storage()
        with patch.object(mod, "TDFOL_AVAILABLE", False), \
             patch.object(mod, "ProofResult", None):
            data = {"status": "unknown", "proved": True}
            result = storage._deserialize_proof_result(data)
        assert result is not None
        assert result.proved is True

    def test_deserialize_invalid_status(self):
        """GIVEN invalid status string THEN falls back gracefully."""
        storage = self._make_storage()
        data = {"status": "INVALID_STATUS_XYZ", "proved": False, "proof_steps": [], "time_ms": 0, "countermodel": None}
        result = storage._deserialize_proof_result(data)
        assert result is not None


# ---------------------------------------------------------------------------
# Tests: get_default_proof_storage
# ---------------------------------------------------------------------------

class TestGetDefaultProofStorage:
    """Test singleton get_default_proof_storage function."""

    def test_returns_ipfs_proof_storage_instance(self):
        """GIVEN call to get_default THEN returns IPFSProofStorage."""
        # Reset singleton
        mod._default_storage = None
        storage = get_default_proof_storage()
        assert isinstance(storage, IPFSProofStorage)

    def test_returns_same_instance_on_second_call(self):
        """GIVEN singleton pattern THEN same instance returned."""
        mod._default_storage = None
        s1 = get_default_proof_storage()
        s2 = get_default_proof_storage()
        assert s1 is s2

    def test_uses_existing_instance(self):
        """GIVEN existing _default_storage THEN uses it."""
        fake_storage = MagicMock(spec=IPFSProofStorage)
        mod._default_storage = fake_storage
        result = get_default_proof_storage()
        assert result is fake_storage
        # Clean up
        mod._default_storage = None
