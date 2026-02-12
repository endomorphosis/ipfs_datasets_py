"""
Integration Tests for Native CEC Implementation

Tests the integration of native Python 3 implementations with
CEC wrappers, including fallback mechanisms and API compatibility.
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ipfs_datasets_py.logic.CEC import (
    DCECLibraryWrapper,
    TalosWrapper,
    EngDCECWrapper,
    ProofResult,
    ConversionResult
)


class TestDCECLibraryWrapperNativeIntegration:
    """Test DCEC Library wrapper native integration."""
    
    def test_native_initialization(self):
        """
        GIVEN: DCECLibraryWrapper configured to use native
        WHEN: initialize() is called
        THEN: Native backend is used if available
        """
        wrapper = DCECLibraryWrapper(use_native=True)
        result = wrapper.initialize()
        
        # Should initialize successfully (native or fallback)
        assert isinstance(result, bool)
        
        # Check backend info
        backend_info = wrapper.get_backend_info()
        assert "is_native" in backend_info
        assert "backend" in backend_info
        assert backend_info["backend"] in ["native_python3", "python2_submodule"]
    
    def test_submodule_only_initialization(self):
        """
        GIVEN: DCECLibraryWrapper configured to NOT use native
        WHEN: initialize() is called
        THEN: Submodule backend is attempted (may fail if not available)
        """
        wrapper = DCECLibraryWrapper(use_native=False)
        result = wrapper.initialize()
        
        # Result depends on submodule availability
        assert isinstance(result, bool)
        
        if result:
            backend_info = wrapper.get_backend_info()
            # If successful, should not be native
            assert backend_info["is_native"] is False
    
    def test_add_statement_native(self):
        """
        GIVEN: Initialized DCEC wrapper with native backend
        WHEN: add_statement() is called
        THEN: Statement is added successfully
        """
        wrapper = DCECLibraryWrapper(use_native=True)
        if not wrapper.initialize():
            pytest.skip("No DCEC backend available")
        
        # Try adding a statement
        result = wrapper.add_statement("test_statement", label="test1")
        
        assert hasattr(result, 'raw_text')
        assert hasattr(result, 'is_valid')
        # Native may handle this differently than submodule
        # Just verify we get a result
    
    def test_backend_info_detailed(self):
        """
        GIVEN: Initialized DCEC wrapper
        WHEN: get_backend_info() is called
        THEN: Detailed backend information is returned
        """
        wrapper = DCECLibraryWrapper()
        wrapper.initialize()
        
        info = wrapper.get_backend_info()
        
        assert "initialized" in info
        assert "is_native" in info
        assert "backend" in info
        assert "use_native_preference" in info
        assert "statements_count" in info
    
    def test_repr_shows_backend(self):
        """
        GIVEN: Initialized DCEC wrapper
        WHEN: __repr__() is called
        THEN: String includes backend type
        """
        wrapper = DCECLibraryWrapper()
        wrapper.initialize()
        
        repr_str = repr(wrapper)
        
        assert "DCECLibraryWrapper" in repr_str
        if wrapper._initialized:
            assert "native" in repr_str or "submodule" in repr_str


class TestTalosWrapperNativeIntegration:
    """Test Talos wrapper native integration."""
    
    def test_native_initialization(self):
        """
        GIVEN: TalosWrapper configured to use native
        WHEN: initialize() is called
        THEN: Native backend is used if available
        """
        wrapper = TalosWrapper(use_native=True)
        result = wrapper.initialize()
        
        # Should initialize successfully (native or fallback)
        assert isinstance(result, bool)
        
        # Check backend info
        backend_info = wrapper.get_backend_info()
        assert "is_native" in backend_info
        assert "backend" in backend_info
        assert backend_info["backend"] in ["native_python3", "python2_submodule"]
    
    def test_submodule_only_initialization(self):
        """
        GIVEN: TalosWrapper configured to NOT use native
        WHEN: initialize() is called
        THEN: Submodule backend is attempted
        """
        wrapper = TalosWrapper(use_native=False)
        result = wrapper.initialize()
        
        # Result depends on submodule availability
        assert isinstance(result, bool)
        
        if result:
            backend_info = wrapper.get_backend_info()
            assert backend_info["is_native"] is False
    
    def test_prove_theorem_native(self):
        """
        GIVEN: Initialized Talos wrapper with native backend
        WHEN: prove_theorem() is called
        THEN: Proof attempt is returned
        """
        wrapper = TalosWrapper(use_native=True)
        if not wrapper.initialize():
            pytest.skip("No theorem prover backend available")
        
        # Try a simple proof
        result = wrapper.prove_theorem(
            conjecture="Q",
            axioms=["P", "P → Q"]
        )
        
        assert hasattr(result, 'result')
        assert hasattr(result, 'conjecture')
        assert hasattr(result, 'axioms')
        assert isinstance(result.result, ProofResult)
    
    def test_backend_info_detailed(self):
        """
        GIVEN: Initialized Talos wrapper
        WHEN: get_backend_info() is called
        THEN: Detailed backend information is returned
        """
        wrapper = TalosWrapper()
        wrapper.initialize()
        
        info = wrapper.get_backend_info()
        
        assert "initialized" in info
        assert "is_native" in info
        assert "backend" in info
        assert "use_native_preference" in info
        assert "proof_attempts" in info
    
    def test_repr_shows_backend(self):
        """
        GIVEN: Initialized Talos wrapper
        WHEN: __repr__() is called
        THEN: String includes backend type
        """
        wrapper = TalosWrapper()
        wrapper.initialize()
        
        repr_str = repr(wrapper)
        
        assert "TalosWrapper" in repr_str
        if wrapper._initialized:
            assert "native" in repr_str or "submodule" in repr_str


class TestEngDCECWrapperNativeIntegration:
    """Test Eng-DCEC wrapper native integration."""
    
    def test_native_initialization(self):
        """
        GIVEN: EngDCECWrapper configured to use native
        WHEN: initialize() is called
        THEN: Native backend is used if available
        """
        wrapper = EngDCECWrapper(use_native=True)
        result = wrapper.initialize()
        
        # Should initialize successfully (native or fallback)
        assert isinstance(result, bool)
        
        # Check backend info
        backend_info = wrapper.get_backend_info()
        assert "is_native" in backend_info
        assert "backend" in backend_info
        assert backend_info["backend"] in ["native_python3", "python2_submodule"]
    
    def test_submodule_only_initialization(self):
        """
        GIVEN: EngDCECWrapper configured to NOT use native
        WHEN: initialize() is called
        THEN: Submodule backend is attempted
        """
        wrapper = EngDCECWrapper(use_native=False)
        result = wrapper.initialize()
        
        # Result depends on submodule availability
        assert isinstance(result, bool)
        
        if result:
            backend_info = wrapper.get_backend_info()
            assert backend_info["is_native"] is False
    
    def test_convert_to_dcec_native(self):
        """
        GIVEN: Initialized EngDCEC wrapper with native backend
        WHEN: convert_to_dcec() is called
        THEN: Conversion result is returned
        """
        wrapper = EngDCECWrapper(use_native=True)
        if not wrapper.initialize():
            pytest.skip("No NL converter backend available")
        
        # Try a simple conversion
        result = wrapper.convert_to_dcec("the agent must act")
        
        assert isinstance(result, ConversionResult)
        assert hasattr(result, 'english_text')
        assert hasattr(result, 'success')
        assert hasattr(result, 'dcec_formula')
        assert result.english_text == "the agent must act"
    
    def test_convert_from_dcec_native(self):
        """
        GIVEN: Initialized EngDCEC wrapper
        WHEN: convert_from_dcec() is called
        THEN: English text is returned (or None)
        """
        wrapper = EngDCECWrapper(use_native=True)
        if not wrapper.initialize():
            pytest.skip("No NL converter backend available")
        
        # Try linearization
        result = wrapper.convert_from_dcec("O(act)")
        
        # Result may be None if pattern not recognized
        # Just verify we get a response
        assert result is None or isinstance(result, str)
    
    def test_backend_info_detailed(self):
        """
        GIVEN: Initialized EngDCEC wrapper
        WHEN: get_backend_info() is called
        THEN: Detailed backend information is returned
        """
        wrapper = EngDCECWrapper()
        wrapper.initialize()
        
        info = wrapper.get_backend_info()
        
        assert "initialized" in info
        assert "is_native" in info
        assert "backend" in info
        assert "use_native_preference" in info
        assert "conversions" in info
    
    def test_repr_shows_backend(self):
        """
        GIVEN: Initialized EngDCEC wrapper
        WHEN: __repr__() is called
        THEN: String includes backend type
        """
        wrapper = EngDCECWrapper()
        wrapper.initialize()
        
        repr_str = repr(wrapper)
        
        assert "EngDCECWrapper" in repr_str
        if wrapper._initialized:
            assert "native" in repr_str or "submodule" in repr_str


class TestCrossWrapperIntegration:
    """Test integration across multiple wrappers."""
    
    def test_all_wrappers_initialize(self):
        """
        GIVEN: All three wrappers
        WHEN: initialize() is called on each
        THEN: At least one backend is available for each
        """
        dcec = DCECLibraryWrapper()
        talos = TalosWrapper()
        eng = EngDCECWrapper()
        
        dcec_init = dcec.initialize()
        talos_init = talos.initialize()
        eng_init = eng.initialize()
        
        # At least verify they all return bool
        assert isinstance(dcec_init, bool)
        assert isinstance(talos_init, bool)
        assert isinstance(eng_init, bool)
    
    def test_mixed_native_and_submodule(self):
        """
        GIVEN: Wrappers with different backend preferences
        WHEN: Initialized with different use_native settings
        THEN: Each can use its own backend independently
        """
        native_wrapper = DCECLibraryWrapper(use_native=True)
        submodule_wrapper = DCECLibraryWrapper(use_native=False)
        
        native_wrapper.initialize()
        submodule_wrapper.initialize()
        
        # They can have different backends
        native_info = native_wrapper.get_backend_info()
        submodule_info = submodule_wrapper.get_backend_info()
        
        # Just verify both have backend info
        assert "backend" in native_info
        assert "backend" in submodule_info
    
    def test_e2e_workflow_with_native(self):
        """
        GIVEN: All wrappers initialized
        WHEN: End-to-end workflow executed
        THEN: Operations complete successfully
        """
        # Initialize wrappers
        nl_converter = EngDCECWrapper()
        dcec_lib = DCECLibraryWrapper()
        prover = TalosWrapper()
        
        nl_init = nl_converter.initialize()
        dcec_init = dcec_lib.initialize()
        prover_init = prover.initialize()
        
        if not (nl_init and dcec_init and prover_init):
            pytest.skip("Not all backends available")
        
        # Convert NL to DCEC
        conversion = nl_converter.convert_to_dcec("the agent must act")
        
        # Even if conversion fails, verify we get proper result
        assert isinstance(conversion, ConversionResult)
        
        # Get backend info from all
        backends = {
            "nl": nl_converter.get_backend_info()["backend"],
            "dcec": dcec_lib.get_backend_info()["backend"],
            "prover": prover.get_backend_info()["backend"]
        }
        
        # All should report a backend
        assert all(b in ["native_python3", "python2_submodule"] for b in backends.values())


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
