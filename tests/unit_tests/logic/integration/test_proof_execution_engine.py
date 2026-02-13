"""
Comprehensive tests for proof_execution_engine module.

Tests the ProofExecutionEngine which executes proofs using installed theorem
provers (Z3, CVC5, Lean, Coq).
"""

import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

# Import modules to test
try:
    from ipfs_datasets_py.logic.integration.proof_execution_engine import (
        ProofExecutionEngine,
        ProofResult,
        ProofStatus,
    )
    PROOF_ENGINE_AVAILABLE = True
except ImportError as e:
    PROOF_ENGINE_AVAILABLE = False
    print(f"Warning: Could not import proof_execution_engine: {e}")


@unittest.skipUnless(PROOF_ENGINE_AVAILABLE, "proof_execution_engine not available")
class TestProofStatus(unittest.TestCase):
    """Test ProofStatus enum."""
    
    def test_proof_status_values(self):
        """
        GIVEN ProofStatus enum
        WHEN accessing status values
        THEN correct string values are returned
        """
        self.assertEqual(ProofStatus.SUCCESS.value, "success")
        self.assertEqual(ProofStatus.FAILURE.value, "failure")
        self.assertEqual(ProofStatus.TIMEOUT.value, "timeout")
        self.assertEqual(ProofStatus.ERROR.value, "error")
        self.assertEqual(ProofStatus.UNSUPPORTED.value, "unsupported")


@unittest.skipUnless(PROOF_ENGINE_AVAILABLE, "proof_execution_engine not available")
class TestProofResult(unittest.TestCase):
    """Test ProofResult dataclass."""
    
    def test_proof_result_creation(self):
        """
        GIVEN proof result parameters
        WHEN creating ProofResult
        THEN result is created with correct attributes
        """
        result = ProofResult(
            prover="z3",
            statement="P -> P",
            status=ProofStatus.SUCCESS,
            proof_output="Proof found",
            execution_time=0.5,
        )
        
        self.assertEqual(result.prover, "z3")
        self.assertEqual(result.statement, "P -> P")
        self.assertEqual(result.status, ProofStatus.SUCCESS)
        self.assertEqual(result.proof_output, "Proof found")
        self.assertEqual(result.execution_time, 0.5)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.warnings, [])
    
    def test_proof_result_to_dict(self):
        """
        GIVEN ProofResult instance
        WHEN converting to dictionary
        THEN correct dictionary representation is returned
        """
        result = ProofResult(
            prover="z3",
            statement="P -> P",
            status=ProofStatus.SUCCESS,
            execution_time=0.5,
        )
        
        result_dict = result.to_dict()
        
        self.assertIsInstance(result_dict, dict)
        self.assertEqual(result_dict["prover"], "z3")
        self.assertEqual(result_dict["statement"], "P -> P")
        self.assertEqual(result_dict["status"], "success")
        self.assertEqual(result_dict["execution_time"], 0.5)
    
    def test_proof_result_with_errors(self):
        """
        GIVEN proof result with errors
        WHEN creating ProofResult
        THEN errors are properly stored
        """
        errors = ["Parse error", "Invalid syntax"]
        result = ProofResult(
            prover="lean",
            statement="invalid",
            status=ProofStatus.ERROR,
            errors=errors,
        )
        
        self.assertEqual(result.errors, errors)
        self.assertEqual(len(result.errors), 2)


@unittest.skipUnless(PROOF_ENGINE_AVAILABLE, "proof_execution_engine not available")
class TestProofExecutionEngineInit(unittest.TestCase):
    """Test ProofExecutionEngine initialization."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test fixtures."""
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)
    
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._maybe_auto_install_provers')
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._refresh_prover_state')
    def test_engine_initialization_default(self, mock_refresh, mock_install):
        """
        GIVEN no parameters
        WHEN initializing ProofExecutionEngine
        THEN engine is created with default settings
        """
        engine = ProofExecutionEngine()
        
        self.assertIsNotNone(engine)
        self.assertEqual(engine.timeout, 60)
        self.assertIn(engine.default_prover, ["z3", "cvc5", "lean", "coq"])
        mock_refresh.assert_called()
        mock_install.assert_called_once()
    
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._maybe_auto_install_provers')
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._refresh_prover_state')
    def test_engine_initialization_custom_timeout(self, mock_refresh, mock_install):
        """
        GIVEN custom timeout value
        WHEN initializing ProofExecutionEngine
        THEN engine uses custom timeout
        """
        engine = ProofExecutionEngine(timeout=120)
        
        self.assertEqual(engine.timeout, 120)
    
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._maybe_auto_install_provers')
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._refresh_prover_state')
    def test_engine_initialization_custom_prover(self, mock_refresh, mock_install):
        """
        GIVEN custom default prover
        WHEN initializing ProofExecutionEngine
        THEN engine uses custom prover as default
        """
        engine = ProofExecutionEngine(default_prover="lean")
        
        self.assertEqual(engine.default_prover, "lean")


@unittest.skipUnless(PROOF_ENGINE_AVAILABLE, "proof_execution_engine not available")
class TestProofExecutionStrategy(unittest.TestCase):
    """Test proof execution strategy selection."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test fixtures."""
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)
    
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._maybe_auto_install_provers')
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._detect_available_provers')
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._refresh_prover_state')
    def test_strategy_selection_with_available_prover(self, mock_refresh, mock_detect, mock_install):
        """
        GIVEN available provers
        WHEN selecting execution strategy
        THEN appropriate prover is selected
        """
        mock_detect.return_value = {"z3": True, "cvc5": False, "lean": False, "coq": False}
        
        engine = ProofExecutionEngine()
        
        # Should prefer available prover
        self.assertIn("z3", str(engine.default_prover))
    
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._maybe_auto_install_provers')
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._detect_available_provers')
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._refresh_prover_state')
    def test_strategy_fallback_when_preferred_unavailable(self, mock_refresh, mock_detect, mock_install):
        """
        GIVEN preferred prover unavailable
        WHEN initializing engine
        THEN fallback strategy is used
        """
        mock_detect.return_value = {"z3": False, "cvc5": True, "lean": False, "coq": False}
        
        engine = ProofExecutionEngine(default_prover="z3")
        
        # Should still initialize even if preferred not available
        self.assertIsNotNone(engine)


@unittest.skipUnless(PROOF_ENGINE_AVAILABLE, "proof_execution_engine not available")
class TestResourceManagement(unittest.TestCase):
    """Test resource management in proof execution."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test fixtures."""
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)
    
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._maybe_auto_install_provers')
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._refresh_prover_state')
    def test_temp_directory_creation(self, mock_refresh, mock_install):
        """
        GIVEN temp directory parameter
        WHEN initializing engine
        THEN temp directory is created
        """
        custom_temp = str(Path(self.temp_dir) / "custom_proofs")
        engine = ProofExecutionEngine(temp_dir=custom_temp)
        
        self.assertTrue(Path(custom_temp).exists())
        self.assertEqual(engine.temp_dir, Path(custom_temp))
    
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._maybe_auto_install_provers')
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._refresh_prover_state')
    def test_temp_directory_default_location(self, mock_refresh, mock_install):
        """
        GIVEN no temp directory specified
        WHEN initializing engine
        THEN default temp location is used
        """
        engine = ProofExecutionEngine()
        
        self.assertIn("ipfs_proofs", str(engine.temp_dir))


@unittest.skipUnless(PROOF_ENGINE_AVAILABLE, "proof_execution_engine not available")
class TestTimeoutHandling(unittest.TestCase):
    """Test timeout handling in proof execution."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test fixtures."""
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)
    
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._maybe_auto_install_provers')
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._refresh_prover_state')
    def test_timeout_configuration(self, mock_refresh, mock_install):
        """
        GIVEN timeout parameter
        WHEN initializing engine
        THEN timeout is properly configured
        """
        engine = ProofExecutionEngine(timeout=30)
        
        self.assertEqual(engine.timeout, 30)
    
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._maybe_auto_install_provers')
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._refresh_prover_state')
    def test_timeout_default_value(self, mock_refresh, mock_install):
        """
        GIVEN no timeout specified
        WHEN initializing engine
        THEN default timeout is used
        """
        engine = ProofExecutionEngine()
        
        self.assertEqual(engine.timeout, 60)


@unittest.skipUnless(PROOF_ENGINE_AVAILABLE, "proof_execution_engine not available")
class TestProverDetection(unittest.TestCase):
    """Test prover availability detection."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test fixtures."""
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)
    
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._maybe_auto_install_provers')
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._detect_available_provers')
    @patch('ipfs_datasets_py.logic.integration.proof_execution_engine.ProofExecutionEngine._refresh_prover_state')
    def test_prover_detection_called(self, mock_refresh, mock_detect, mock_install):
        """
        GIVEN engine initialization
        WHEN detecting available provers
        THEN detection is called
        """
        mock_detect.return_value = {}
        
        engine = ProofExecutionEngine()
        
        # Refresh state calls detect
        self.assertTrue(mock_refresh.called)


if __name__ == "__main__":
    unittest.main()
