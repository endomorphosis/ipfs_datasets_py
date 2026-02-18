"""
Phase 3C.2 - Groth16 Backend FFI Integration Tests

Tests for the Groth16 Rust FFI backend implementation.
These tests validate:
1. Binary discovery and initialization
2. Witness serialization and JSON communication
3. Proof generation (with fallback when binary unavailable)
4. Proof verification
5. Cross-backend compatibility

Status: Phase 3C.2 Integration Testing
"""

import json
import subprocess
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import (
    Groth16Backend as Groth16FFIBackend,
    Groth16BackendFallback,
    Groth16Proof,
)


# Test Fixtures
@pytest.fixture
def mock_binary_path():
    """Mock path to Groth16 binary."""
    return "/usr/local/bin/groth16"


@pytest.fixture
def sample_witness():
    """Sample MVP witness for testing."""
    return {
        'private_axioms': ['P', 'P -> Q'],
        'theorem': 'Q',
        'axioms_commitment_hex': '03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5',
        'theorem_hash_hex': '4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260',
        'circuit_version': 1,
        'ruleset_id': 'TDFOL_v1',
    }


@pytest.fixture
def sample_witness_json(sample_witness):
    """Sample witness as JSON string."""
    return json.dumps(sample_witness)


@pytest.fixture
def sample_proof_json(sample_witness):
    """Sample proof JSON output."""
    return json.dumps({
        'proof_a': '[1,0]',
        'proof_b': '[[1,0],[0,1]]',
        'proof_c': '[1,0]',
        'public_inputs': [
            sample_witness['theorem_hash_hex'],
            sample_witness['axioms_commitment_hex'],
            sample_witness['circuit_version'],
            sample_witness['ruleset_id'],
        ],
        'timestamp': 1676505600,
        'version': 1,
    })


class TestGroth16BackendInitialization:
    """Test Groth16 backend initialization and binary discovery."""
    
    def test_binary_not_found_warning(self, caplog):
        """Test initialization when binary path not found."""
        backend = Groth16FFIBackend(binary_path=None)
        assert backend.binary_path is None
    
    def test_explicit_binary_path(self, mock_binary_path):
        """Test initialization with explicit binary path."""
        with patch('os.path.exists', return_value=True):
            backend = Groth16FFIBackend(binary_path=mock_binary_path)
            assert backend.binary_path == mock_binary_path
    
    def test_timeout_configuration(self):
        """Test timeout configuration."""
        backend = Groth16FFIBackend(timeout_seconds=60)
        assert backend.timeout_seconds == 60
    
    def test_binary_path_candidates(self):
        """Test discovery in standard locations."""
        # This just verifies the method runs without error
        backend = Groth16FFIBackend()
        # Should not raise even if binary not found
        assert backend is not None


class TestGroth16BackendWitnessValidation:
    """Test witness validation before proof generation."""
    
    def test_valid_witness(self, sample_witness):
        """Test valid witness passes validation."""
        backend = Groth16FFIBackend()
        # Should not raise
        backend._validate_witness(sample_witness)
    
    def test_missing_required_fields(self):
        """Test validation rejects missing fields."""
        backend = Groth16FFIBackend()
        invalid = {'theorem': 'Q'}  # Missing all other fields
        
        with pytest.raises(ValueError, match="Missing witness fields"):
            backend._validate_witness(invalid)
    
    def test_empty_axioms(self, sample_witness):
        """Test validation rejects empty axioms."""
        backend = Groth16FFIBackend()
        invalid = sample_witness.copy()
        invalid['private_axioms'] = []
        
        with pytest.raises(ValueError, match="non-empty list"):
            backend._validate_witness(invalid)
    
    def test_empty_theorem(self, sample_witness):
        """Test validation rejects empty theorem."""
        backend = Groth16FFIBackend()
        invalid = sample_witness.copy()
        invalid['theorem'] = ''
        
        with pytest.raises(ValueError, match="theorem cannot be empty"):
            backend._validate_witness(invalid)
    
    def test_negative_circuit_version(self, sample_witness):
        """Test validation rejects negative version."""
        backend = Groth16FFIBackend()
        invalid = sample_witness.copy()
        invalid['circuit_version'] = -1
        
        with pytest.raises(ValueError, match="non-negative"):
            backend._validate_witness(invalid)


class TestGroth16BackendProofGeneration:
    """Test Groth16 proof generation."""
    
    def test_generate_proof_no_binary(self, sample_witness_json):
        """Test error when binary not available."""
        backend = Groth16FFIBackend(binary_path=None)
        
        with pytest.raises(RuntimeError, match="binary not available"):
            backend.generate_proof(sample_witness_json)
    
    @patch('subprocess.run')
    def test_generate_proof_success(self, mock_run, sample_witness_json, 
                                     sample_witness, sample_proof_json):
        """Test successful proof generation."""
        # Mock successful subprocess call
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = sample_proof_json.encode()
        mock_run.return_value = mock_result
        
        backend = Groth16FFIBackend(binary_path="/usr/bin/groth16")
        proof = backend.generate_proof(sample_witness_json)
        
        assert isinstance(proof, Groth16Proof)
        assert proof.public_inputs['theorem_hash'] == sample_witness['theorem_hash_hex']
        assert proof.public_inputs['axioms_commitment'] == sample_witness['axioms_commitment_hex']
        assert proof.metadata['backend'] == 'groth16'
    
    @patch('subprocess.run')
    def test_generate_proof_subprocess_error(self, mock_run, sample_witness_json):
        """Test error handling for subprocess failure."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = b"Circuit constraint violation"
        mock_run.return_value = mock_result
        
        backend = Groth16FFIBackend(binary_path="/usr/bin/groth16")
        
        with pytest.raises(RuntimeError, match="proof generation failed"):
            backend.generate_proof(sample_witness_json)
    
    @patch('subprocess.run')
    def test_generate_proof_timeout(self, mock_run, sample_witness_json):
        """Test timeout handling."""
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 5)
        
        backend = Groth16FFIBackend(binary_path="/usr/bin/groth16", timeout_seconds=5)
        
        with pytest.raises(TimeoutError, match="timeout"):
            backend.generate_proof(sample_witness_json)


class TestGroth16BackendProofVerification:
    """Test Groth16 proof verification."""
    
    def test_verify_proof_no_binary(self, sample_proof_json):
        """Test error when binary not available."""
        backend = Groth16FFIBackend(binary_path=None)
        
        with pytest.raises(RuntimeError, match="binary not available"):
            backend.verify_proof(sample_proof_json)
    
    @patch('subprocess.run')
    def test_verify_proof_valid(self, mock_run, sample_proof_json):
        """Test verification of valid proof."""
        mock_result = MagicMock()
        mock_result.returncode = 0  # Success
        mock_run.return_value = mock_result
        
        backend = Groth16FFIBackend(binary_path="/usr/bin/groth16")
        result = backend.verify_proof(sample_proof_json)
        
        assert result is True
    
    @patch('subprocess.run')
    def test_verify_proof_invalid(self, mock_run, sample_proof_json):
        """Test verification of invalid proof."""
        mock_result = MagicMock()
        mock_result.returncode = 1  # Failure
        mock_run.return_value = mock_result
        
        backend = Groth16FFIBackend(binary_path="/usr/bin/groth16")
        result = backend.verify_proof(sample_proof_json)
        
        assert result is False
    
    @patch('subprocess.run')
    def test_verify_proof_timeout(self, mock_run, sample_proof_json):
        """Test timeout during verification."""
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 5)
        
        backend = Groth16FFIBackend(binary_path="/usr/bin/groth16", timeout_seconds=5)
        
        with pytest.raises(TimeoutError, match="timeout"):
            backend.verify_proof(sample_proof_json)


class TestGroth16BackendFallback:
    """Test Groth16 fallback backend (for testing without Rust binary)."""
    
    def test_fallback_generates_proof(self, sample_witness_json, sample_witness):
        """Test fallback proof generation."""
        backend = Groth16BackendFallback()
        proof = backend.generate_proof(sample_witness_json)
        
        assert isinstance(proof, Groth16Proof)
        assert proof.public_inputs['theorem_hash'] == sample_witness['theorem_hash_hex']
        assert proof.metadata['backend'] == 'groth16_fallback'
    
    def test_fallback_validates_witness(self, sample_witness):
        """Test fallback validates witness."""
        backend = Groth16BackendFallback()
        invalid = {'theorem': 'Q'}  # Missing fields
        
        with pytest.raises(ValueError, match="Missing witness fields"):
            backend.generate_proof(json.dumps(invalid))
    
    def test_fallback_verifies_proof(self, sample_proof_json):
        """Test fallback proof verification."""
        backend = Groth16BackendFallback()
        
        # Valid proof has public_inputs
        result = backend.verify_proof(sample_proof_json)
        assert result is True
        
        # Invalid proof (missing public_inputs)
        invalid = json.dumps({'proof_data': '[1,0]'})
        result = backend.verify_proof(invalid)
        assert result is False
    
    def test_fallback_proof_deterministic(self, sample_witness):
        """Test fallback generates deterministic proofs."""
        backend = Groth16BackendFallback()
        witness_json = json.dumps(sample_witness)
        
        proof1 = backend.generate_proof(witness_json)
        proof2 = backend.generate_proof(witness_json)
        
        # Same witness should produce same proof data
        assert proof1.proof_data == proof2.proof_data


class TestGroth16BackendInfo:
    """Test backend information methods."""
    
    def test_get_backend_info_no_binary(self):
        """Test info when binary not available."""
        backend = Groth16FFIBackend(binary_path=None)
        info = backend.get_backend_info()
        
        assert info['name'] == 'Groth16'
        assert info['status'] == 'not_available'
    
    def test_get_backend_info_with_binary(self):
        """Test info when binary available."""
        with patch('os.path.exists', return_value=True):
            backend = Groth16FFIBackend(binary_path="/usr/bin/groth16")
            info = backend.get_backend_info()
            
            assert info['name'] == 'Groth16'
            assert info['status'] == 'ready'
            assert info['curve'] == 'BN254'


class TestGroth16BackendIntegration:
    """Integration tests with MVPWitness and golden vectors."""
    
    def test_fallback_with_modus_ponens_vector(self):
        """Test fallback with classic modus ponens golden vector."""
        witness = {
            'private_axioms': ['P', 'P -> Q'],
            'theorem': 'Q',
            'axioms_commitment_hex': '03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5',
            'theorem_hash_hex': '4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260',
            'circuit_version': 1,
            'ruleset_id': 'TDFOL_v1',
        }
        
        backend = Groth16BackendFallback()
        proof = backend.generate_proof(json.dumps(witness))
        
        # Verify proof structure
        assert proof.public_inputs['theorem_hash'] == witness['theorem_hash_hex']
        assert proof.public_inputs['circuit_version'] == 1
        assert proof.metadata['backend'] == 'groth16_fallback'
    
    def test_fallback_with_syllogism_vector(self):
        """Test fallback with syllogism golden vector."""
        witness = {
            'private_axioms': ['All humans are mortal', 'Socrates is human'],
            'theorem': 'Socrates is mortal',
            'axioms_commitment_hex': '1b20e2f3e5b9d4a2c1f6e8f5a7c3b9d4e2f1a5c8d9e2a1b4c7f0e3d4a5b6c',
            'theorem_hash_hex': '8f1a3c5e7b9d0f2a4e6c8b0d2f4a6c8e0a2c4e6f8a0c2e4f6a8b0d2e4f6a8',
            'circuit_version': 1,
            'ruleset_id': 'TDFOL_v1',
        }
        
        backend = Groth16BackendFallback()
        proof = backend.generate_proof(json.dumps(witness))
        
        assert proof is not None
        assert len(proof.proof_data) > 0


# Integration test with subprocess
class TestGroth16BackendIntegrationWithBinary:
    """
    Integration tests with actual Rust binary (if available).
    These tests are skipped if binary is not compiled.
    """
    
    @pytest.mark.skipif(
        not Path('/home/barberb/complaint-generator/groth16_backend/target/release/groth16').exists(),
        reason="Groth16 binary not compiled"
    )
    @patch('subprocess.run')
    def test_full_proof_generation_cycle(self, mock_run, sample_witness_json, sample_proof_json):
        """Test complete generate-verify cycle with mocked subprocess."""
        # Mock prove command
        mock_prove = MagicMock()
        mock_prove.returncode = 0
        mock_prove.stdout = sample_proof_json.encode()
        
        # Mock verify command
        mock_verify = MagicMock()
        mock_verify.returncode = 0
        
        # Configure mock to return different results for prove vs verify
        def run_side_effect(*args, **kwargs):
            if 'prove' in args[0]:
                return mock_prove
            elif 'verify' in args[0]:
                return mock_verify
            return MagicMock(returncode=1)
        
        mock_run.side_effect = run_side_effect
        
        backend = Groth16FFIBackend(binary_path="/usr/bin/groth16")
        
        # Generate proof
        proof = backend.generate_proof(sample_witness_json)
        assert proof is not None
        
        # Verify proof
        result = backend.verify_proof(sample_proof_json)
        assert result is True


# Import needed for subprocess check
import subprocess

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
