"""
Tests for ZKP backend selection and gating (Phase A).

These tests ensure that:
1. Backend selection works correctly
2. Backends fail gracefully with helpful error messages
3. Import statements remain quiet (no heavy deps imported)
4. Default backend is always available
"""

import pytest
from ipfs_datasets_py.logic.zkp.backends import (
    get_backend,
    list_backends,
    backend_is_available,
    clear_backend_cache,
    ZKBackend,
)
from ipfs_datasets_py.logic.zkp import ZKPError


class TestBackendSelection:
    """Test backend selection mechanism."""
    
    def test_default_backend_is_simulated(self):
        """Default backend (no args) should be simulated."""
        backend = get_backend()
        assert backend.backend_id == "simulated"
    
    def test_explicit_simulated_backend(self):
        """Explicitly selecting 'simulated' backend works."""
        backend = get_backend("simulated")
        assert backend.backend_id == "simulated"
    
    def test_simulated_backend_aliases(self):
        """Backend aliases ('sim', '', etc.) map to simulated."""
        for alias in ["sim", "", "SIMULATED", "Sim"]:
            backend = get_backend(alias)
            assert backend.backend_id == "simulated"
    
    def test_backend_caching(self):
        """Same backend requested twice should return cached instance."""
        backend1 = get_backend("simulated")
        backend2 = get_backend("simulated")
        assert backend1 is backend2  # Same object
    
    def test_unknown_backend_rejected(self):
        """Selecting unknown backend should raise ZKPError."""
        with pytest.raises(ZKPError, match="Unknown ZKP backend"):
            get_backend("unknown_backend_xyz")
    
    def test_backend_metadata_available(self):
        """Backend metadata should be discoverable."""
        metadata = list_backends()
        assert "simulated" in metadata
        assert "groth16" in metadata
        assert "description" in metadata["simulated"]


class TestSimulatedBackendAvailability:
    """Test that simulated backend is always available."""
    
    def test_simulated_always_available(self):
        """Simulated backend should never fail."""
        backend = get_backend("simulated")
        assert backend is not None
        assert backend_is_available("simulated") is True
    
    def test_simulated_backend_works(self):
        """Simulated backend should execute basic operations."""
        backend = get_backend("simulated")
        
        # Should be able to generate proof
        proof = backend.generate_proof(
            theorem="P",
            private_axioms=["P"],
            metadata={}
        )
        assert proof is not None
        
        # Should be able to verify proof
        result = backend.verify_proof(proof)
        assert isinstance(result, bool)


class TestGroth16BackendGating:
    """Test Groth16 backend gating (Phase A)."""
    
    def test_groth16_fails_without_deps(self, monkeypatch):
        """Groth16 backend should fail with clear message if deps missing."""
        # Note: This test is approximate. In a full test we'd mock the import
        # to simulate missing dependencies.
        
        # Try to get groth16 backend
        # It should either:
        # 1. Succeed (if py_ecc is installed)
        # 2. Fail with ZKPError mentioning py_ecc (if missing)
        
        try:
            backend = get_backend("groth16")
            # If we reach here, py_ecc is installed
            # The backend exists but may not be fully implemented
            assert backend.backend_id == "groth16"
        except ZKPError as e:
            # Error should mention py_ecc requirement
            assert "py_ecc" in str(e).lower() or "not yet implemented" in str(e).lower()
    
    def test_groth16_fails_closed_with_message(self):
        """Groth16 backend operations should fail closed with helpful message."""
        try:
            backend = get_backend("groth16")
            # If backend loaded, try to generate proof
            with pytest.raises(ZKPError):
                backend.generate_proof(
                    theorem="P",
                    private_axioms=["P"],
                    metadata={}
                )
        except ZKPError as e:
            # If backend selection fails, message should be helpful
            error_msg = str(e).lower()
            assert any(x in error_msg for x in [
                "groth16",
                "not implemented",
                "py_ecc",
                "phase",
            ])


class TestBackendProtocol:
    """Test that backends implement the protocol correctly."""
    
    def test_simulated_backend_implements_protocol(self):
        """Simulated backend should implement ZKBackend protocol."""
        backend = get_backend("simulated")
        assert isinstance(backend, ZKBackend)
    
    def test_backend_has_required_methods(self):
        """Backend should have required methods."""
        backend = get_backend("simulated")
        
        # Should have these methods
        assert hasattr(backend, "generate_proof")
        assert hasattr(backend, "verify_proof")
        assert hasattr(backend, "backend_id")
        
        # Should be callable
        assert callable(backend.generate_proof)
        assert callable(backend.verify_proof)


class TestImportQuietness:
    """Test that backend module imports don't emit warnings or load heavy deps."""
    
    def test_import_backends_quiet(self):
        """Importing backends module should not emit warnings."""
        import subprocess
        import sys
        import os
        
        # Set PYTHONPATH to include ipfs_datasets_py directory
        env = os.environ.copy()
        ipfs_py_path = "/home/barberb/complaint-generator/ipfs_datasets_py"
        env["PYTHONPATH"] = ipfs_py_path
        
        result = subprocess.run(
            [sys.executable, "-c",
             "import warnings; "
             "warnings.simplefilter('error'); "  # Turn warnings into errors
             "import ipfs_datasets_py.logic.zkp.backends; "
             "print('OK')"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        
        # Should succeed (no warnings)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "OK" in result.stdout
    
    def test_py_ecc_not_imported_on_backends_import(self):
        """py_ecc should not be imported when importing backends."""
        import subprocess
        import sys
        import os
        
        # Set PYTHONPATH to include ipfs_datasets_py directory
        env = os.environ.copy()
        ipfs_py_path = "/home/barberb/complaint-generator/ipfs_datasets_py"
        env["PYTHONPATH"] = ipfs_py_path
        
        code = """
import sys
import ipfs_datasets_py.logic.zkp.backends
# If py_ecc is imported, it should be in sys.modules
has_py_ecc = 'py_ecc' in sys.modules
print('py_ecc_imported=' + str(has_py_ecc))
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "py_ecc_imported=False" in result.stdout


class TestBackendCacheManagement:
    """Test backend cache clearing (for testing)."""
    
    def test_clear_backend_cache(self):
        """Cache clearing should work for testing."""
        backend1 = get_backend("simulated")
        clear_backend_cache()
        backend2 = get_backend("simulated")
        
        # Should be different objects after cache clear
        assert backend1 is not backend2
    
    def test_cache_populated_after_get(self):
        """Cache should be populated after backend retrieval."""
        clear_backend_cache()
        get_backend("simulated")
        
        # Getting again should return the same cached instance
        backend1 = get_backend("simulated")
        backend2 = get_backend("simulated")
        assert backend1 is backend2


class TestBackendAvailabilityCheck:
    """Test backend availability checking."""
    
    def test_simulated_available(self):
        """Simulated backend should always be available."""
        assert backend_is_available("simulated") is True
    
    def test_available_returns_bool(self):
        """availability check should return boolean."""
        result = backend_is_available("simulated")
        assert isinstance(result, bool)
    
    def test_unknown_backend_not_available(self):
        """Unknown backend should report as unavailable."""
        assert backend_is_available("xyz_unknown_backend") is False


class TestBackendMetadata:
    """Test backend metadata discovery."""
    
    def test_metadata_has_required_fields(self):
        """Backend metadata should have expected fields."""
        metadata = list_backends()
        
        for backend_id, backend_meta in metadata.items():
            assert "description" in backend_meta
            assert "curve" in backend_meta or "module" in backend_meta
    
    def test_metadata_matches_backends(self):
        """Metadata should only describe registered backends."""
        metadata = list_backends()
        
        # All backends in metadata should be loadable (or documented as not-yet-implemented)
        for backend_id in metadata.keys():
            # Either backend is available or error message explains why
            try:
                get_backend(backend_id)
            except ZKPError as e:
                # Error should be informative
                assert len(str(e)) > 0
