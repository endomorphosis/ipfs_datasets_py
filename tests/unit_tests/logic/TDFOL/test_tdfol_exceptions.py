"""
Tests for TDFOL custom exception hierarchy.

This test suite validates the custom exception classes defined in
ipfs_datasets_py.logic.TDFOL.exceptions, including:
- Proper exception inheritance
- Context information preservation
- Error message formatting
- ZKP integration errors
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.exceptions import (
    TDFOLError,
    ParseError,
    ProofError,
    ProofTimeoutError,
    ProofNotFoundError,
    ZKPProofError,
    ConversionError,
    InferenceError,
    NLProcessingError,
    PatternMatchError,
    CacheError,
)


class TestTDFOLError:
    """Tests for base TDFOLError exception."""
    
    def test_basic_error(self):
        """GIVEN a basic TDFOLError
        WHEN initialized with message
        THEN it should contain the message
        """
        error = TDFOLError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert error.message == "Something went wrong"
        assert error.suggestion is None
        assert error.context == {}
    
    def test_error_with_suggestion(self):
        """GIVEN a TDFOLError with suggestion
        WHEN initialized
        THEN it should include the suggestion in string representation
        """
        error = TDFOLError("Error occurred", suggestion="Try this fix")
        assert "Error occurred" in str(error)
        assert "Suggestion: Try this fix" in str(error)
        assert error.suggestion == "Try this fix"
    
    def test_error_with_context(self):
        """GIVEN a TDFOLError with context
        WHEN initialized
        THEN it should preserve context information
        """
        context = {'formula': 'P(x)', 'axioms': ['A', 'B']}
        error = TDFOLError("Error", context=context)
        assert error.context == context
        assert error.context['formula'] == 'P(x)'


class TestParseError:
    """Tests for ParseError exception."""
    
    def test_basic_parse_error(self):
        """GIVEN a ParseError
        WHEN initialized with position info
        THEN it should format the error with line and column
        """
        error = ParseError(
            message="Unexpected token",
            position=42,
            line=3,
            column=15
        )
        assert "line 3, column 15" in str(error)
        assert error.position == 42
        assert error.line == 3
        assert error.column == 15
    
    def test_parse_error_with_token(self):
        """GIVEN a ParseError with token info
        WHEN initialized
        THEN it should include token in message
        """
        error = ParseError(
            message="Unexpected token",
            position=10,
            line=1,
            column=11,
            token="}"
        )
        assert "token: '}'" in str(error)
        assert error.token == "}"
    
    def test_parse_error_with_input(self):
        """GIVEN a ParseError with input text
        WHEN initialized
        THEN it should preserve input text in context
        """
        input_text = "forall x. P(x) }"
        error = ParseError(
            message="Unexpected token",
            position=15,
            line=1,
            column=16,
            input_text=input_text
        )
        assert error.context['input_text'] == input_text
        assert error.input_text == input_text


class TestProofError:
    """Tests for ProofError exception."""
    
    def test_basic_proof_error(self):
        """GIVEN a ProofError
        WHEN initialized
        THEN it should contain basic error info
        """
        error = ProofError("Failed to prove formula")
        assert "Failed to prove formula" in str(error)
    
    def test_proof_error_with_method(self):
        """GIVEN a ProofError with method
        WHEN initialized
        THEN it should include method in message
        """
        error = ProofError(
            message="Proof failed",
            method="forward_chaining"
        )
        assert "method: forward_chaining" in str(error)
        assert error.method == "forward_chaining"
    
    def test_proof_error_with_reason(self):
        """GIVEN a ProofError with reason
        WHEN initialized
        THEN it should include reason in message
        """
        error = ProofError(
            message="Proof failed",
            reason="No applicable inference rules"
        )
        assert "Reason: No applicable inference rules" in str(error)
        assert error.reason == "No applicable inference rules"
    
    def test_proof_error_with_formula(self):
        """GIVEN a ProofError with formula
        WHEN initialized
        THEN it should preserve formula in context
        """
        formula = "P(x) -> Q(x)"
        error = ProofError(
            message="Proof failed",
            formula=formula
        )
        assert error.formula == formula
        assert error.context['formula'] == formula


class TestProofTimeoutError:
    """Tests for ProofTimeoutError exception."""
    
    def test_timeout_error(self):
        """GIVEN a ProofTimeoutError
        WHEN initialized with timeout info
        THEN it should format timeout message correctly
        """
        error = ProofTimeoutError(
            message="Proof exceeded timeout",
            timeout=60.0,
            elapsed=60.5,
            iterations=150
        )
        assert "60.50s > 60.00s timeout" in str(error)
        assert "150 iterations" in str(error)
        assert error.timeout == 60.0
        assert error.elapsed == 60.5
        assert error.iterations == 150
    
    def test_timeout_inherits_from_proof_error(self):
        """GIVEN a ProofTimeoutError
        WHEN checked for inheritance
        THEN it should be a ProofError and TDFOLError
        """
        error = ProofTimeoutError("Timeout", timeout=10.0, elapsed=10.1)
        assert isinstance(error, ProofError)
        assert isinstance(error, TDFOLError)
    
    def test_timeout_has_default_suggestion(self):
        """GIVEN a ProofTimeoutError without suggestion
        WHEN initialized
        THEN it should have a default suggestion
        """
        error = ProofTimeoutError("Timeout", timeout=10.0, elapsed=10.1)
        assert error.suggestion is not None
        assert "timeout" in error.suggestion.lower() or "simplify" in error.suggestion.lower()


class TestProofNotFoundError:
    """Tests for ProofNotFoundError exception."""
    
    def test_not_found_error(self):
        """GIVEN a ProofNotFoundError
        WHEN initialized with attempt count
        THEN it should format message with attempts
        """
        error = ProofNotFoundError(
            message="No proof found",
            attempts=25
        )
        assert "25 attempts" in str(error)
        assert error.attempts == 25
    
    def test_not_found_has_default_suggestion(self):
        """GIVEN a ProofNotFoundError without suggestion
        WHEN initialized
        THEN it should have a default suggestion
        """
        error = ProofNotFoundError("No proof found", attempts=10)
        assert error.suggestion is not None
        assert "axiom" in error.suggestion.lower() or "formula" in error.suggestion.lower()


class TestZKPProofError:
    """Tests for ZKPProofError exception."""
    
    def test_zkp_error_basic(self):
        """GIVEN a ZKPProofError
        WHEN initialized with ZKP info
        THEN it should format ZKP-specific message
        """
        error = ZKPProofError(
            message="ZKP proof generation failed",
            backend="simulated",
            security_level=128,
            operation="prove"
        )
        assert "simulated" in str(error)
        assert "128-bit" in str(error)
        assert "prove" in str(error)
        assert error.backend == "simulated"
        assert error.security_level == 128
        assert error.operation == "prove"
    
    def test_zkp_error_inherits_from_proof_error(self):
        """GIVEN a ZKPProofError
        WHEN checked for inheritance
        THEN it should be a ProofError and TDFOLError
        """
        error = ZKPProofError(
            message="ZKP failed",
            backend="groth16",
            security_level=256,
            operation="verify"
        )
        assert isinstance(error, ProofError)
        assert isinstance(error, TDFOLError)
    
    def test_zkp_error_verify_operation(self):
        """GIVEN a ZKPProofError for verification
        WHEN initialized with operation="verify"
        THEN it should indicate verification failure
        """
        error = ZKPProofError(
            message="Verification failed",
            backend="groth16",
            security_level=256,
            operation="verify"
        )
        assert "verify" in str(error)
        assert error.operation == "verify"
    
    def test_zkp_error_context(self):
        """GIVEN a ZKPProofError
        WHEN initialized
        THEN it should preserve ZKP-specific context
        """
        error = ZKPProofError(
            message="ZKP failed",
            backend="simulated",
            security_level=128,
            operation="prove"
        )
        assert error.context['backend'] == "simulated"
        assert error.context['security_level'] == 128
        assert error.context['operation'] == "prove"
    
    def test_zkp_error_fallback_pattern(self):
        """GIVEN a ZKPProofError in hybrid proving mode
        WHEN caught in try-except
        THEN applications can fall back to standard proving
        
        This test validates the integration pattern for hybrid
        proving (ZKP + standard).
        """
        # Simulate hybrid proving pattern
        def hybrid_prove(theorem, private_axioms=None):
            """Try ZKP first, fall back to standard proving."""
            if private_axioms:
                try:
                    # Would call ZKP prover here
                    raise ZKPProofError(
                        message="ZKP failed",
                        backend="simulated",
                        security_level=128,
                        operation="prove"
                    )
                except ZKPProofError:
                    # Fall back to standard proving (no privacy)
                    return {"method": "standard", "proved": True}
            else:
                return {"method": "standard", "proved": True}
        
        # Test fallback
        result = hybrid_prove("theorem", private_axioms=["secret"])
        assert result["method"] == "standard"
        assert result["proved"] is True


class TestConversionError:
    """Tests for ConversionError exception."""
    
    def test_conversion_error(self):
        """GIVEN a ConversionError
        WHEN initialized with format info
        THEN it should format conversion message
        """
        error = ConversionError(
            message="Cannot convert nested temporal operators",
            source_format="TDFOL",
            target_format="FOL"
        )
        assert "TDFOL → FOL" in str(error)
        assert error.source_format == "TDFOL"
        assert error.target_format == "FOL"
    
    def test_conversion_error_with_formula(self):
        """GIVEN a ConversionError with formula
        WHEN initialized
        THEN it should preserve formula in context
        """
        formula = "O(□(P(x)))"
        error = ConversionError(
            message="Conversion failed",
            source_format="TDFOL",
            target_format="FOL",
            formula=formula
        )
        assert error.formula == formula
        assert error.context['formula'] == formula


class TestInferenceError:
    """Tests for InferenceError exception."""
    
    def test_inference_error(self):
        """GIVEN an InferenceError
        WHEN initialized with rule name
        THEN it should format rule-specific message
        """
        error = InferenceError(
            message="Modus ponens requires implication",
            rule_name="modus_ponens"
        )
        assert "rule: modus_ponens" in str(error)
        assert error.rule_name == "modus_ponens"
    
    def test_inference_error_with_premises(self):
        """GIVEN an InferenceError with premises
        WHEN initialized
        THEN it should preserve premises in context
        """
        premises = ["P", "P -> Q"]
        error = InferenceError(
            message="Rule application failed",
            rule_name="modus_ponens",
            premises=premises
        )
        assert error.premises == premises
        assert len(error.context['premises']) == 2


class TestNLProcessingError:
    """Tests for NLProcessingError exception."""
    
    def test_nl_processing_error(self):
        """GIVEN an NLProcessingError
        WHEN initialized with stage info
        THEN it should format stage-specific message
        """
        error = NLProcessingError(
            message="Failed to extract entities",
            stage="preprocessing"
        )
        assert "stage: preprocessing" in str(error)
        assert error.stage == "preprocessing"
    
    def test_nl_processing_error_with_input(self):
        """GIVEN an NLProcessingError with input text
        WHEN initialized
        THEN it should preserve input text
        """
        input_text = "ambiguous sentence"
        error = NLProcessingError(
            message="Processing failed",
            stage="preprocessing",
            input_text=input_text
        )
        assert error.input_text == input_text
        assert error.context['input_text'] == input_text


class TestPatternMatchError:
    """Tests for PatternMatchError exception."""
    
    def test_pattern_match_error(self):
        """GIVEN a PatternMatchError
        WHEN initialized with match info
        THEN it should format pattern-specific message
        """
        error = PatternMatchError(
            message="No patterns matched",
            patterns_tried=45,
            best_match_confidence=0.35
        )
        assert "45 patterns" in str(error)
        assert "0.35" in str(error)
        assert error.patterns_tried == 45
        assert error.best_match_confidence == 0.35
    
    def test_pattern_match_inherits_from_nl_error(self):
        """GIVEN a PatternMatchError
        WHEN checked for inheritance
        THEN it should be an NLProcessingError
        """
        error = PatternMatchError("No match", patterns_tried=10)
        assert isinstance(error, NLProcessingError)
        assert isinstance(error, TDFOLError)
    
    def test_pattern_match_has_default_suggestion(self):
        """GIVEN a PatternMatchError without suggestion
        WHEN initialized
        THEN it should have a default suggestion
        """
        error = PatternMatchError("No match", patterns_tried=45)
        assert error.suggestion is not None
        assert "rephras" in error.suggestion.lower() or "structure" in error.suggestion.lower()


class TestCacheError:
    """Tests for CacheError exception."""
    
    def test_cache_error(self):
        """GIVEN a CacheError
        WHEN initialized with operation info
        THEN it should format cache-specific message
        """
        error = CacheError(
            message="Failed to serialize proof",
            operation="set"
        )
        assert "operation: set" in str(error)
        assert error.operation == "set"
    
    def test_cache_error_with_key(self):
        """GIVEN a CacheError with cache key
        WHEN initialized
        THEN it should include truncated key in message
        """
        cache_key = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
        error = CacheError(
            message="Cache operation failed",
            operation="get",
            cache_key=cache_key
        )
        assert "key:" in str(error)
        assert cache_key[:16] in str(error)
        assert error.cache_key == cache_key


class TestExceptionHierarchy:
    """Tests for exception hierarchy and inheritance."""
    
    def test_all_inherit_from_tdfol_error(self):
        """GIVEN all TDFOL exception classes
        WHEN checked for inheritance
        THEN they should all inherit from TDFOLError
        """
        exceptions = [
            ParseError("msg", 0, 1, 1),
            ProofError("msg"),
            ProofTimeoutError("msg", timeout=10, elapsed=11),
            ProofNotFoundError("msg"),
            ZKPProofError("msg", backend="sim", security_level=128, operation="prove"),
            ConversionError("msg", "A", "B"),
            InferenceError("msg", "rule"),
            NLProcessingError("msg", "stage"),
            PatternMatchError("msg"),
            CacheError("msg", "op"),
        ]
        
        for exc in exceptions:
            assert isinstance(exc, TDFOLError)
            assert isinstance(exc, Exception)
    
    def test_can_catch_all_tdfol_errors(self):
        """GIVEN various TDFOL exceptions
        WHEN caught with TDFOLError base class
        THEN all should be caught
        """
        caught = []
        
        try:
            raise ParseError("parse error", 0, 1, 1)
        except TDFOLError as e:
            caught.append(type(e))
        
        try:
            raise ZKPProofError("zkp error", backend="sim", security_level=128, operation="prove")
        except TDFOLError as e:
            caught.append(type(e))
        
        try:
            raise CacheError("cache error", "get")
        except TDFOLError as e:
            caught.append(type(e))
        
        assert ParseError in caught
        assert ZKPProofError in caught
        assert CacheError in caught
    
    def test_specific_exception_can_be_caught_separately(self):
        """GIVEN a specific exception type
        WHEN caught with specific handler
        THEN it should be caught before base handler
        """
        caught_specific = False
        caught_base = False
        
        try:
            raise ZKPProofError("zkp error", backend="sim", security_level=128, operation="prove")
        except ZKPProofError:
            caught_specific = True
        except TDFOLError:
            caught_base = True
        
        assert caught_specific is True
        assert caught_base is False


class TestExceptionIntegration:
    """Tests for exception integration patterns."""
    
    def test_zkp_integration_pattern(self):
        """GIVEN a ZKP-enabled prover
        WHEN ZKP fails
        THEN application can catch ZKPProofError and handle gracefully
        
        This test validates the integration pattern described in the
        exceptions module docstring.
        """
        def prove_with_zkp_fallback(theorem, private_axioms=None):
            """Prove theorem with ZKP if private axioms provided."""
            if private_axioms:
                try:
                    # Simulate ZKP proving
                    raise ZKPProofError(
                        message="ZKP backend unavailable",
                        backend="groth16",
                        security_level=256,
                        operation="prove",
                        reason="Groth16 not installed"
                    )
                except ZKPProofError as e:
                    # Log ZKP failure
                    print(f"ZKP failed: {e.message}")
                    print(f"Backend: {e.backend}")
                    print(f"Falling back to standard proving")
                    # Fall back to standard (non-private) proving
                    return {"method": "standard", "private": False}
            else:
                return {"method": "standard", "private": False}
        
        # Test pattern
        result = prove_with_zkp_fallback("theorem", private_axioms=["secret"])
        assert result["method"] == "standard"
        assert result["private"] is False
    
    def test_cache_error_retry_pattern(self):
        """GIVEN a cache operation
        WHEN CacheError occurs
        THEN application can retry or continue without cache
        """
        def get_cached_proof(formula, use_cache=True):
            """Get cached proof with error handling."""
            if use_cache:
                try:
                    # Simulate cache failure
                    raise CacheError(
                        message="Cache corrupted",
                        operation="get",
                        cache_key="bafybeig..."
                    )
                except CacheError as e:
                    print(f"Cache failed ({e.operation}): {e.message}")
                    # Continue without cache
                    return None
            return None
        
        # Test pattern
        result = get_cached_proof("P(x)", use_cache=True)
        assert result is None  # No cache hit, but no crash


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
