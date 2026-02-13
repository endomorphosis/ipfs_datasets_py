#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for logic common module - error hierarchy.

Tests the standardized error classes and context tracking functionality.
"""

import pytest

try:
    from ipfs_datasets_py.logic.common import (
        LogicError,
        ConversionError,
        ValidationError,
        ProofError,
        TranslationError,
        BridgeError,
        ConfigurationError,
        DeonticError,
        ModalError,
        TemporalError,
    )
    COMMON_AVAILABLE = True
    SKIP_REASON = ""
except ImportError as e:
    COMMON_AVAILABLE = False
    SKIP_REASON = f"Common module not available: {e}"


@pytest.mark.skipif(not COMMON_AVAILABLE, reason=SKIP_REASON)
class TestLogicError:
    """Test LogicError base class."""
    
    def test_logic_error_simple_message(self):
        """
        GIVEN a simple error message
        WHEN LogicError is created
        THEN it should store message correctly
        """
        error = LogicError("Something went wrong")
        
        assert error.message == "Something went wrong"
        assert error.context == {}
        assert str(error) == "Something went wrong"
    
    def test_logic_error_with_context(self):
        """
        GIVEN an error message with context
        WHEN LogicError is created
        THEN it should store message and context
        """
        context = {"module": "test", "line": 42}
        error = LogicError("Failed", context=context)
        
        assert error.message == "Failed"
        assert error.context == context
        assert "module=test" in str(error)
        assert "line=42" in str(error)
    
    def test_logic_error_can_be_raised(self):
        """
        GIVEN a LogicError
        WHEN raised
        THEN it should be catchable as Exception
        """
        with pytest.raises(LogicError) as exc_info:
            raise LogicError("Test error")
        
        assert "Test error" in str(exc_info.value)


@pytest.mark.skipif(not COMMON_AVAILABLE, reason=SKIP_REASON)
class TestSpecificErrors:
    """Test specific error types."""
    
    def test_conversion_error(self):
        """
        GIVEN a ConversionError
        WHEN created
        THEN it should be a LogicError subclass
        """
        error = ConversionError("Conversion failed")
        
        assert isinstance(error, LogicError)
        assert isinstance(error, ConversionError)
        assert error.message == "Conversion failed"
    
    def test_validation_error(self):
        """
        GIVEN a ValidationError
        WHEN created
        THEN it should be a LogicError subclass
        """
        error = ValidationError("Invalid input", {"field": "formula"})
        
        assert isinstance(error, LogicError)
        assert isinstance(error, ValidationError)
        assert error.context["field"] == "formula"
    
    def test_proof_error(self):
        """
        GIVEN a ProofError
        WHEN created
        THEN it should be a LogicError subclass
        """
        error = ProofError("Proof failed")
        
        assert isinstance(error, LogicError)
        assert isinstance(error, ProofError)
    
    def test_translation_error(self):
        """
        GIVEN a TranslationError
        WHEN created
        THEN it should be a LogicError subclass
        """
        error = TranslationError("Translation failed")
        
        assert isinstance(error, LogicError)
        assert isinstance(error, TranslationError)
    
    def test_bridge_error(self):
        """
        GIVEN a BridgeError
        WHEN created
        THEN it should be a LogicError subclass
        """
        error = BridgeError("Bridge unavailable")
        
        assert isinstance(error, LogicError)
        assert isinstance(error, BridgeError)
    
    def test_configuration_error(self):
        """
        GIVEN a ConfigurationError
        WHEN created
        THEN it should be a LogicError subclass
        """
        error = ConfigurationError("Invalid config")
        
        assert isinstance(error, LogicError)
        assert isinstance(error, ConfigurationError)
    
    def test_deontic_error(self):
        """
        GIVEN a DeonticError
        WHEN created
        THEN it should be a LogicError subclass
        """
        error = DeonticError("Deontic logic failed")
        
        assert isinstance(error, LogicError)
        assert isinstance(error, DeonticError)
    
    def test_modal_error(self):
        """
        GIVEN a ModalError
        WHEN created
        THEN it should be a LogicError subclass
        """
        error = ModalError("Modal logic failed")
        
        assert isinstance(error, LogicError)
        assert isinstance(error, ModalError)
    
    def test_temporal_error(self):
        """
        GIVEN a TemporalError
        WHEN created
        THEN it should be a LogicError subclass
        """
        error = TemporalError("Temporal logic failed")
        
        assert isinstance(error, LogicError)
        assert isinstance(error, TemporalError)


@pytest.mark.skipif(not COMMON_AVAILABLE, reason=SKIP_REASON)
class TestErrorContext:
    """Test error context functionality."""
    
    def test_context_in_string_representation(self):
        """
        GIVEN an error with multiple context items
        WHEN converting to string
        THEN all context items should appear
        """
        context = {
            "function": "test_func",
            "line": 123,
            "file": "test.py"
        }
        error = LogicError("Failed", context=context)
        
        error_str = str(error)
        assert "function=test_func" in error_str
        assert "line=123" in error_str
        assert "file=test.py" in error_str
    
    def test_empty_context_shows_message_only(self):
        """
        GIVEN an error without context
        WHEN converting to string
        THEN only message should appear
        """
        error = LogicError("Simple error")
        
        error_str = str(error)
        assert error_str == "Simple error"
        assert "Context:" not in error_str
    
    def test_context_accessible_for_debugging(self):
        """
        GIVEN an error with context
        WHEN accessing context attribute
        THEN context dictionary should be accessible
        """
        context = {"debug": "info", "value": 42}
        error = ConversionError("Failed", context=context)
        
        assert error.context["debug"] == "info"
        assert error.context["value"] == 42


@pytest.mark.skipif(not COMMON_AVAILABLE, reason=SKIP_REASON)
class TestErrorHierarchy:
    """Test error hierarchy relationships."""
    
    def test_all_errors_inherit_from_logic_error(self):
        """
        GIVEN all specific error types
        WHEN checking inheritance
        THEN all should inherit from LogicError
        """
        error_types = [
            ConversionError,
            ValidationError,
            ProofError,
            TranslationError,
            BridgeError,
            ConfigurationError,
            DeonticError,
            ModalError,
            TemporalError,
        ]
        
        for error_type in error_types:
            assert issubclass(error_type, LogicError)
    
    def test_logic_error_inherits_from_exception(self):
        """
        GIVEN LogicError class
        WHEN checking inheritance
        THEN it should inherit from Exception
        """
        assert issubclass(LogicError, Exception)
    
    def test_can_catch_specific_error_types(self):
        """
        GIVEN different error types
        WHEN catching specific types
        THEN correct type should be caught
        """
        # Should catch ConversionError specifically
        with pytest.raises(ConversionError):
            raise ConversionError("test")
        
        # Should catch as LogicError
        with pytest.raises(LogicError):
            raise ConversionError("test")
        
        # Should catch as Exception
        with pytest.raises(Exception):
            raise ConversionError("test")
