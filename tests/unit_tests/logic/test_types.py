"""
Tests for logic/types module

These tests validate that the types module correctly re-exports types
from their original locations and maintains backward compatibility.
"""

import pytest
from typing import get_type_hints


class TestTypesModuleImports:
    """Test that all types can be imported from the types module."""
    
    def test_import_all_deontic_types(self):
        """GIVEN the types module
        WHEN importing deontic types
        THEN all expected types are available
        """
        from ipfs_datasets_py.logic.types import (
            DeonticOperator,
            DeonticFormula,
            DeonticRuleSet,
            LegalAgent,
            LegalContext,
            TemporalCondition,
            TemporalOperator,
        )
        
        # Verify types are not None
        assert DeonticOperator is not None
        assert DeonticFormula is not None
        assert DeonticRuleSet is not None
        assert LegalAgent is not None
        assert LegalContext is not None
        assert TemporalCondition is not None
        assert TemporalOperator is not None
    
    def test_import_all_proof_types(self):
        """GIVEN the types module
        WHEN importing proof types
        THEN all expected types are available
        """
        from ipfs_datasets_py.logic.types import (
            ProofStatus,
            ProofResult,
            ProofStep,
        )
        
        # Verify types are not None
        assert ProofStatus is not None
        assert ProofResult is not None
        assert ProofStep is not None
    
    def test_import_all_translation_types(self):
        """GIVEN the types module
        WHEN importing translation types
        THEN all expected types are available
        """
        from ipfs_datasets_py.logic.types import (
            LogicTranslationTarget,
            TranslationResult,
            AbstractLogicFormula,
        )
        
        # Verify types are not None
        assert LogicTranslationTarget is not None
        assert TranslationResult is not None
        assert AbstractLogicFormula is not None
    
    def test_types_module_all_attribute(self):
        """GIVEN the types module
        WHEN accessing __all__
        THEN it contains all expected type names
        """
        import ipfs_datasets_py.logic.types as types_module
        
        expected_types = {
            # Deontic types
            "DeonticOperator",
            "DeonticFormula",
            "DeonticRuleSet",
            "LegalAgent",
            "LegalContext",
            "TemporalCondition",
            "TemporalOperator",
            # Proof types
            "ProofStatus",
            "ProofResult",
            "ProofStep",
            # Translation types
            "LogicTranslationTarget",
            "TranslationResult",
            "AbstractLogicFormula",
        }
        
        assert hasattr(types_module, '__all__')
        # types may export more than the minimum compatibility surface
        assert expected_types.issubset(set(types_module.__all__))


class TestBackwardCompatibility:
    """Test that types are still available from original locations."""
    
    def test_deontic_types_from_original_location(self):
        """GIVEN deontic types
        WHEN importing from original location
        THEN types are still available (backward compatibility)
        """
        from ipfs_datasets_py.logic.integration.deontic_logic_core import (
            DeonticOperator,
            DeonticFormula,
        )
        
        assert DeonticOperator is not None
        assert DeonticFormula is not None
    
    def test_proof_types_from_original_location(self):
        """GIVEN proof types
        WHEN importing from original location
        THEN types are still available (backward compatibility)
        """
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import (
            ProofStatus,
            ProofResult,
        )
        
        assert ProofStatus is not None
        assert ProofResult is not None
    
    def test_translation_types_from_original_location(self):
        """GIVEN translation types
        WHEN importing from original location
        THEN types are still available (backward compatibility)
        """
        from ipfs_datasets_py.logic.integration.logic_translation_core import (
            LogicTranslationTarget,
            TranslationResult,
        )
        
        assert LogicTranslationTarget is not None
        assert TranslationResult is not None


class TestTypeIdentity:
    """Test that types from both locations are identical."""
    
    def test_deontic_operator_identity(self):
        """GIVEN DeonticOperator from both locations
        WHEN comparing them
        THEN they are the same object
        """
        from ipfs_datasets_py.logic.types import DeonticOperator as TypesDeonticOp
        from ipfs_datasets_py.logic.integration.deontic_logic_core import DeonticOperator as OriginalDeonticOp
        
        assert TypesDeonticOp is OriginalDeonticOp
    
    def test_proof_result_identity(self):
        """GIVEN ProofResult from both locations
        WHEN comparing them
        THEN they are the same object
        """
        from ipfs_datasets_py.logic.types import ProofResult as TypesProofResult
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult as OriginalProofResult
        
        assert TypesProofResult is OriginalProofResult
    
    def test_translation_result_identity(self):
        """GIVEN TranslationResult from both locations
        WHEN comparing them
        THEN they are the same object
        """
        from ipfs_datasets_py.logic.types import TranslationResult as TypesTransResult
        from ipfs_datasets_py.logic.integration.logic_translation_core import TranslationResult as OriginalTransResult
        
        assert TypesTransResult is OriginalTransResult


class TestDeonticTypes:
    """Test deontic types module specifically."""
    
    def test_deontic_types_module_all(self):
        """GIVEN deontic_types module
        WHEN accessing __all__
        THEN it contains expected types
        """
        from ipfs_datasets_py.logic.types import deontic_types
        
        expected = [
            "DeonticOperator",
            "DeonticFormula",
            "DeonticRuleSet",
            "LegalAgent",
            "LegalContext",
            "TemporalCondition",
            "TemporalOperator",
        ]
        
        assert hasattr(deontic_types, '__all__')
        assert deontic_types.__all__ == expected
    
    def test_deontic_types_docstring(self):
        """GIVEN deontic_types module
        WHEN accessing docstring
        THEN it explains backward compatibility
        """
        from ipfs_datasets_py.logic.types import deontic_types
        
        assert deontic_types.__doc__ is not None
        assert "backward-compatible" in deontic_types.__doc__.lower()


class TestProofTypes:
    """Test proof types module specifically."""
    
    def test_proof_types_module_all(self):
        """GIVEN proof_types module
        WHEN accessing __all__
        THEN it contains expected types
        """
        from ipfs_datasets_py.logic.types import proof_types
        
        expected = [
            "ProofStatus",
            "ProofResult",
            "ProofStep",
        ]
        
        assert hasattr(proof_types, '__all__')
        assert proof_types.__all__ == expected
    
    def test_proof_types_docstring(self):
        """GIVEN proof_types module
        WHEN accessing docstring
        THEN it explains backward compatibility
        """
        from ipfs_datasets_py.logic.types import proof_types
        
        assert proof_types.__doc__ is not None
        assert "backward-compatible" in proof_types.__doc__.lower()


class TestTranslationTypes:
    """Test translation types module specifically."""
    
    def test_translation_types_module_all(self):
        """GIVEN translation_types module
        WHEN accessing __all__
        THEN it contains expected types
        """
        from ipfs_datasets_py.logic.types import translation_types
        
        expected = [
            "LogicTranslationTarget",
            "TranslationResult",
            "AbstractLogicFormula",
        ]
        
        assert hasattr(translation_types, '__all__')
        assert translation_types.__all__ == expected
    
    def test_translation_types_docstring(self):
        """GIVEN translation_types module
        WHEN accessing docstring
        THEN it explains backward compatibility
        """
        from ipfs_datasets_py.logic.types import translation_types
        
        assert translation_types.__doc__ is not None
        assert "backward-compatible" in translation_types.__doc__.lower()


class TestTypeUsage:
    """Test that types can be used as expected."""
    
    def test_can_use_deontic_operator_enum(self):
        """GIVEN DeonticOperator enum
        WHEN accessing values
        THEN expected values are present
        """
        from ipfs_datasets_py.logic.types import DeonticOperator
        
        # DeonticOperator should be an Enum with obligation/permission/prohibition
        assert hasattr(DeonticOperator, '__members__')
        # Should have common deontic operators
        members = list(DeonticOperator.__members__.keys())
        assert len(members) > 0  # Has at least some members
    
    def test_can_check_translation_target_enum(self):
        """GIVEN LogicTranslationTarget enum
        WHEN accessing values
        THEN expected targets are present
        """
        from ipfs_datasets_py.logic.types import LogicTranslationTarget
        
        # Should be an Enum with theorem prover targets
        assert hasattr(LogicTranslationTarget, '__members__')
        members = list(LogicTranslationTarget.__members__.keys())
        assert len(members) > 0  # Has theorem prover targets
    
    def test_proof_status_is_enum(self):
        """GIVEN ProofStatus
        WHEN checking type
        THEN it is an Enum
        """
        from ipfs_datasets_py.logic.types import ProofStatus
        from enum import Enum
        
        # ProofStatus should be an Enum
        assert issubclass(ProofStatus, Enum)


class TestCircularDependencyResolution:
    """Test that the types module prevents circular dependencies."""
    
    def test_types_module_import_succeeds(self):
        """GIVEN the types module
        WHEN importing it
        THEN no circular dependency errors occur
        """
        # This test simply ensures the import succeeds
        import ipfs_datasets_py.logic.types
        
        assert ipfs_datasets_py.logic.types is not None
    
    def test_can_import_types_before_tools(self):
        """GIVEN a fresh import context
        WHEN importing types before tools
        THEN no errors occur
        """
        # This would fail if there were circular dependencies
        from ipfs_datasets_py.logic.types import DeonticOperator
        from ipfs_datasets_py.logic.integration.deontic_logic_core import DeonticFormula
        
        assert DeonticOperator is not None
        assert DeonticFormula is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
