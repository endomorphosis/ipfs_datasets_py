"""Tests for Additional Theorem Provers (Phase 5).

This module tests the integration of Isabelle/HOL, Vampire, and E prover
with the Logic Theorem Optimizer.
"""

import time
from unittest.mock import Mock, patch, MagicMock

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.additional_provers import (
    IsabelleProver,
    VampireProver,
    EProver,
    AdditionalProversRegistry,
    ProverResult,
    ProverType,
    ProofFormat
)


class TestIsabelleProver:
    """Tests for Isabelle/HOL prover integration."""
    
    def test_isabelle_initialization(self):
        """
        GIVEN an Isabelle prover configuration
        WHEN the prover is initialized
        THEN it should have correct settings
        """
        prover = IsabelleProver(
            isabelle_path="test_isabelle",
            enable_cache=True,
            default_timeout=20.0
        )
        
        assert prover.isabelle_path == "test_isabelle"
        assert prover.enable_cache is True
        assert prover.default_timeout == 20.0
        assert isinstance(prover.proof_cache, dict)
    
    @patch('subprocess.run')
    def test_isabelle_prove_success(self, mock_run):
        """
        GIVEN a valid HOL formula
        WHEN prove is called
        THEN it should return a successful result
        """
        # Mock successful Isabelle execution
        mock_run.return_value = Mock(
            returncode=0,
            stdout="No errors\nFinished theory GeneratedProof\nby auto",
            stderr=""
        )
        
        prover = IsabelleProver()
        result = prover.prove("P ∧ Q ⟹ P", timeout=5.0)
        
        assert isinstance(result, ProverResult)
        assert result.prover_name == "isabelle"
        assert result.is_proved is True
        assert result.confidence == 1.0
        assert result.proof_time > 0
        assert result.timeout is False
    
    @patch('subprocess.run')
    def test_isabelle_prove_failure(self, mock_run):
        """
        GIVEN an invalid formula
        WHEN prove is called
        THEN it should return a failed result
        """
        mock_run.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="error: Failed to prove theorem"
        )
        
        prover = IsabelleProver()
        result = prover.prove("P ∧ ¬P", timeout=5.0)
        
        assert result.is_proved is False
        assert result.confidence == 0.0
        assert result.error_message is not None
    
    @patch('subprocess.run')
    def test_isabelle_timeout(self, mock_run):
        """
        GIVEN a complex formula
        WHEN prove times out
        THEN it should return a timeout result
        """
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("isabelle", 5.0)
        
        prover = IsabelleProver()
        result = prover.prove("complex_formula", timeout=5.0)
        
        assert result.is_proved is False
        assert result.timeout is True
        assert "Timeout" in result.error_message
    
    def test_isabelle_theory_generation(self):
        """
        GIVEN a formula
        WHEN theory file is generated
        THEN it should have correct structure
        """
        prover = IsabelleProver()
        theory = prover._generate_theory("P ⟹ P", use_sledgehammer=True)
        
        assert "theory GeneratedProof" in theory
        assert "imports Main" in theory
        assert 'theorem to_prove: "P ⟹ P"' in theory
        assert "sledgehammer" in theory
        assert "by auto" in theory
    
    def test_isabelle_theory_without_sledgehammer(self):
        """
        GIVEN a formula
        WHEN theory generated without Sledgehammer
        THEN it should not include sledgehammer command
        """
        prover = IsabelleProver()
        theory = prover._generate_theory("P ⟹ P", use_sledgehammer=False)
        
        assert "sledgehammer" not in theory
        assert "by auto" in theory
    
    @patch('subprocess.run')
    def test_isabelle_caching(self, mock_run):
        """
        GIVEN a cached proof
        WHEN the same formula is proved again
        THEN it should return cached result
        """
        mock_run.return_value = Mock(
            returncode=0,
            stdout="No errors\nFinished theory",
            stderr=""
        )
        
        prover = IsabelleProver(enable_cache=True)
        
        # First call
        result1 = prover.prove("P ⟹ P", timeout=5.0)
        call_count_after_first = mock_run.call_count
        
        # Second call should use cache
        result2 = prover.prove("P ⟹ P", timeout=5.0)
        
        assert result1.is_proved == result2.is_proved
        # Second call should not trigger subprocess
        assert mock_run.call_count == call_count_after_first


class TestVampireProver:
    """Tests for Vampire automated theorem prover."""
    
    def test_vampire_initialization(self):
        """
        GIVEN a Vampire prover configuration
        WHEN initialized
        THEN it should have correct settings
        """
        prover = VampireProver(
            vampire_path="test_vampire",
            enable_cache=True,
            default_timeout=15.0
        )
        
        assert prover.vampire_path == "test_vampire"
        assert prover.enable_cache is True
        assert prover.default_timeout == 15.0
    
    @patch('subprocess.run')
    def test_vampire_prove_fof_success(self, mock_run):
        """
        GIVEN a TPTP FOF problem
        WHEN prove_fof is called
        THEN it should return successful result
        """
        mock_run.return_value = Mock(
            returncode=0,
            stdout="% Refutation found\n% Proof: ...",
            stderr=""
        )
        
        prover = VampireProver()
        problem = "fof(axiom1, axiom, p(a)).\nfof(goal, conjecture, p(a))."
        result = prover.prove_fof(problem, timeout=10.0)
        
        assert result.prover_name == "vampire"
        assert result.is_proved is True
        assert result.confidence == 1.0
        assert result.proof_certificate is not None
    
    @patch('subprocess.run')
    def test_vampire_prove_fof_failure(self, mock_run):
        """
        GIVEN an unprovable FOF problem
        WHEN prove_fof is called
        THEN it should return failed result
        """
        mock_run.return_value = Mock(
            returncode=1,
            stdout="% SZS status CounterSatisfiable",
            stderr=""
        )
        
        prover = VampireProver()
        problem = "fof(axiom1, axiom, p(a)).\nfof(goal, conjecture, ~p(a))."
        result = prover.prove_fof(problem)
        
        assert result.is_proved is False
        assert result.confidence == 0.0
    
    @patch('subprocess.run')
    def test_vampire_timeout(self, mock_run):
        """
        GIVEN a complex problem
        WHEN Vampire times out
        THEN it should return timeout result
        """
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("vampire", 10.0)
        
        prover = VampireProver()
        result = prover.prove_fof("fof(...)", timeout=10.0)
        
        assert result.is_proved is False
        assert result.timeout is True
    
    def test_vampire_parse_success(self):
        """
        GIVEN successful Vampire output
        WHEN parsed
        THEN it should identify proof
        """
        prover = VampireProver()
        stdout = "% Refutation found\n% Proof:\nstep1\nstep2\n% SZS output end"
        stderr = ""
        
        is_proved, certificate = prover._parse_vampire_output(stdout, stderr)
        
        assert is_proved is True
        assert certificate is not None
        assert "Proof:" in certificate
    
    def test_vampire_parse_failure(self):
        """
        GIVEN failed Vampire output
        WHEN parsed
        THEN it should identify no proof
        """
        prover = VampireProver()
        stdout = "% SZS status CounterSatisfiable"
        stderr = ""
        
        is_proved, certificate = prover._parse_vampire_output(stdout, stderr)
        
        assert is_proved is False
        assert certificate is None
    
    @patch('subprocess.run')
    def test_vampire_caching(self, mock_run):
        """
        GIVEN cached proof
        WHEN same problem proved again
        THEN should use cache
        """
        mock_run.return_value = Mock(
            returncode=0,
            stdout="% Refutation found",
            stderr=""
        )
        
        prover = VampireProver(enable_cache=True)
        problem = "fof(test, axiom, p(a))."
        
        result1 = prover.prove_fof(problem)
        call_count_after_first = mock_run.call_count
        result2 = prover.prove_fof(problem)
        
        assert result1.is_proved == result2.is_proved
        assert mock_run.call_count == call_count_after_first  # No additional calls


class TestEProver:
    """Tests for E equational theorem prover."""
    
    def test_eprover_initialization(self):
        """
        GIVEN E prover configuration
        WHEN initialized
        THEN it should have correct settings
        """
        prover = EProver(
            eprover_path="test_eprover",
            enable_cache=True,
            default_timeout=12.0
        )
        
        assert prover.eprover_path == "test_eprover"
        assert prover.enable_cache is True
        assert prover.default_timeout == 12.0
    
    @patch('subprocess.run')
    def test_eprover_prove_cnf_success(self, mock_run):
        """
        GIVEN a CNF problem
        WHEN prove_cnf is called
        THEN it should return successful result
        """
        mock_run.return_value = Mock(
            returncode=0,
            stdout="# Proof found!\n# Proof object\nstep1\nstep2\n# SZS output end",
            stderr=""
        )
        
        prover = EProver()
        problem = "cnf(a1, axiom, p(a)).\ncnf(goal, negated_conjecture, ~p(a))."
        result = prover.prove_cnf(problem, timeout=10.0)
        
        assert result.prover_name == "e_prover"
        assert result.is_proved is True
        assert result.confidence == 1.0
        assert result.proof_certificate is not None
    
    @patch('subprocess.run')
    def test_eprover_prove_cnf_failure(self, mock_run):
        """
        GIVEN an unprovable CNF problem
        WHEN prove_cnf is called
        THEN it should return failed result
        """
        mock_run.return_value = Mock(
            returncode=1,
            stdout="# SZS status Satisfiable",
            stderr=""
        )
        
        prover = EProver()
        problem = "cnf(a1, axiom, p(a))."
        result = prover.prove_cnf(problem)
        
        assert result.is_proved is False
        assert result.confidence == 0.0
    
    @patch('subprocess.run')
    def test_eprover_timeout(self, mock_run):
        """
        GIVEN a complex problem
        WHEN E prover times out
        THEN it should return timeout result
        """
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("eprover", 10.0)
        
        prover = EProver()
        result = prover.prove_cnf("cnf(...)", timeout=10.0)
        
        assert result.is_proved is False
        assert result.timeout is True
    
    def test_eprover_parse_success(self):
        """
        GIVEN successful E prover output
        WHEN parsed
        THEN it should identify proof
        """
        prover = EProver()
        stdout = "# Proof found!\n# Proof object\nderivation\n# SZS output end"
        stderr = ""
        
        is_proved, certificate = prover._parse_eprover_output(stdout, stderr)
        
        assert is_proved is True
        assert certificate is not None
        assert "Proof object" in certificate
    
    def test_eprover_parse_theorem(self):
        """
        GIVEN E prover theorem output
        WHEN parsed
        THEN it should identify proof
        """
        prover = EProver()
        stdout = "# SZS status Theorem"
        stderr = ""
        
        is_proved, certificate = prover._parse_eprover_output(stdout, stderr)
        
        assert is_proved is True
    
    def test_eprover_parse_unsatisfiable(self):
        """
        GIVEN E prover unsatisfiable output
        WHEN parsed
        THEN it should identify proof
        """
        prover = EProver()
        stdout = "# SZS status Unsatisfiable"
        stderr = ""
        
        is_proved, certificate = prover._parse_eprover_output(stdout, stderr)
        
        assert is_proved is True
    
    @patch('subprocess.run')
    def test_eprover_auto_mode(self, mock_run):
        """
        GIVEN auto mode enabled
        WHEN prove_cnf is called
        THEN it should use auto flag
        """
        mock_run.return_value = Mock(
            returncode=0,
            stdout="# Proof found!",
            stderr=""
        )
        
        prover = EProver()
        prover.prove_cnf("cnf(test, axiom, p(a)).", auto_mode=True)
        
        # Check that --auto flag was used
        call_args = mock_run.call_args[0][0]
        assert "--auto" in call_args
    
    @patch('subprocess.run')
    def test_eprover_caching(self, mock_run):
        """
        GIVEN cached proof
        WHEN same problem proved again
        THEN should use cache
        """
        mock_run.return_value = Mock(
            returncode=0,
            stdout="# Proof found!",
            stderr=""
        )
        
        prover = EProver(enable_cache=True)
        problem = "cnf(test, axiom, p(a))."
        
        result1 = prover.prove_cnf(problem)
        call_count_after_first = mock_run.call_count
        result2 = prover.prove_cnf(problem)
        
        assert result1.is_proved == result2.is_proved
        assert mock_run.call_count == call_count_after_first  # No additional calls


class TestAdditionalProversRegistry:
    """Tests for additional provers registry."""
    
    def test_registry_initialization(self):
        """
        GIVEN a prover registry
        WHEN initialized
        THEN it should check all provers
        """
        registry = AdditionalProversRegistry()
        
        assert isinstance(registry._availability, dict)
        assert "isabelle" in registry._availability
        assert "vampire" in registry._availability
        assert "e_prover" in registry._availability
    
    def test_registry_get_available_provers(self):
        """
        GIVEN a registry
        WHEN get_available_provers is called
        THEN it should return list of available provers
        """
        registry = AdditionalProversRegistry()
        available = registry.get_available_provers()
        
        assert isinstance(available, list)
        # All provers should be checked
        assert len(registry._availability) == 3
    
    def test_registry_is_available(self):
        """
        GIVEN a prover name
        WHEN is_available is called
        THEN it should return availability status
        """
        registry = AdditionalProversRegistry()
        
        # Should not raise error
        result = registry.is_available("isabelle")
        assert isinstance(result, bool)
    
    @patch.object(AdditionalProversRegistry, 'is_available', return_value=True)
    def test_registry_get_prover(self, mock_available):
        """
        GIVEN an available prover
        WHEN get_prover is called
        THEN it should return prover instance
        """
        registry = AdditionalProversRegistry()
        registry._availability["isabelle"] = True
        
        prover = registry.get_prover("isabelle")
        
        assert isinstance(prover, IsabelleProver)
    
    def test_registry_get_prover_unavailable(self):
        """
        GIVEN an unavailable prover
        WHEN get_prover is called
        THEN it should raise ValueError
        """
        registry = AdditionalProversRegistry()
        registry._availability["test_prover"] = False
        
        try:
            registry.get_prover("test_prover")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "not available" in str(e)
    
    def test_registry_get_recommended_prover_hol(self):
        """
        GIVEN HOL problem type
        WHEN get_recommended_prover is called
        THEN it should recommend Isabelle
        """
        registry = AdditionalProversRegistry()
        registry._availability["isabelle"] = True
        
        recommended = registry.get_recommended_prover(ProofFormat.HOL)
        
        assert recommended == "isabelle"
    
    def test_registry_get_recommended_prover_fof(self):
        """
        GIVEN FOF problem type
        WHEN get_recommended_prover is called
        THEN it should recommend Vampire
        """
        registry = AdditionalProversRegistry()
        registry._availability["vampire"] = True
        
        recommended = registry.get_recommended_prover(ProofFormat.FOF)
        
        assert recommended == "vampire"
    
    def test_registry_get_recommended_prover_cnf(self):
        """
        GIVEN CNF problem type
        WHEN get_recommended_prover is called
        THEN it should recommend E prover
        """
        registry = AdditionalProversRegistry()
        registry._availability["e_prover"] = True
        
        recommended = registry.get_recommended_prover(ProofFormat.CNF)
        
        assert recommended == "e_prover"
    
    def test_registry_get_recommended_fallback(self):
        """
        GIVEN unavailable recommended prover
        WHEN get_recommended_prover is called
        THEN it should fallback to available prover
        """
        registry = AdditionalProversRegistry()
        registry._availability["isabelle"] = False
        registry._availability["vampire"] = True
        registry._availability["e_prover"] = False
        
        # Request HOL (recommends Isabelle)
        recommended = registry.get_recommended_prover(ProofFormat.HOL)
        
        # Should fallback to Vampire
        assert recommended == "vampire"
    
    @patch.object(AdditionalProversRegistry, 'is_available', return_value=True)
    def test_registry_caches_prover_instances(self, mock_available):
        """
        GIVEN a prover already created
        WHEN get_prover is called again
        THEN it should return cached instance
        """
        registry = AdditionalProversRegistry()
        registry._availability["vampire"] = True
        
        prover1 = registry.get_prover("vampire")
        prover2 = registry.get_prover("vampire")
        
        # Should be same instance
        assert prover1 is prover2


class TestProverResult:
    """Tests for ProverResult dataclass."""
    
    def test_prover_result_creation(self):
        """
        GIVEN prover result data
        WHEN ProverResult is created
        THEN it should have correct attributes
        """
        result = ProverResult(
            prover_name="test",
            is_proved=True,
            confidence=0.95,
            proof_time=1.5,
            proof_output="output",
            proof_certificate="cert",
            error_message=None,
            timeout=False
        )
        
        assert result.prover_name == "test"
        assert result.is_proved is True
        assert result.confidence == 0.95
        assert result.proof_time == 1.5
        assert result.proof_output == "output"
        assert result.proof_certificate == "cert"
        assert result.error_message is None
        assert result.timeout is False
    
    def test_prover_result_with_error(self):
        """
        GIVEN failed proof
        WHEN ProverResult is created
        THEN it should include error details
        """
        result = ProverResult(
            prover_name="test",
            is_proved=False,
            confidence=0.0,
            proof_time=2.0,
            error_message="Failed to prove",
            timeout=False
        )
        
        assert result.is_proved is False
        assert result.error_message == "Failed to prove"
    
    def test_prover_result_metadata(self):
        """
        GIVEN metadata dict
        WHEN ProverResult is created
        THEN it should store metadata
        """
        metadata = {"strategy": "auto", "depth": 5}
        result = ProverResult(
            prover_name="test",
            is_proved=True,
            confidence=1.0,
            proof_time=1.0,
            metadata=metadata
        )
        
        assert result.metadata == metadata
        assert result.metadata["strategy"] == "auto"


class TestEnums:
    """Tests for enum types."""
    
    def test_prover_type_enum(self):
        """
        GIVEN ProverType enum
        WHEN accessed
        THEN it should have correct values
        """
        assert ProverType.ISABELLE.value == "isabelle"
        assert ProverType.VAMPIRE.value == "vampire"
        assert ProverType.E_PROVER.value == "e_prover"
    
    def test_proof_format_enum(self):
        """
        GIVEN ProofFormat enum
        WHEN accessed
        THEN it should have correct values
        """
        assert ProofFormat.HOL.value == "hol"
        assert ProofFormat.FOF.value == "fof"
        assert ProofFormat.TFF.value == "tff"
        assert ProofFormat.CNF.value == "cnf"
        assert ProofFormat.THF.value == "thf"
