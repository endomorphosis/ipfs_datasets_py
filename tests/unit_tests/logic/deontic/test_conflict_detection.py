"""Comprehensive tests for deontic conflict detection.

This test module validates the conflict detection functionality
in the deontic_parser module, covering all conflict types:
- Direct conflicts (O∧F)
- Permission conflicts (P∧F)
- Temporal conflicts
- Conditional conflicts
"""

import pytest
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    detect_normative_conflicts,
)


class TestDirectConflicts:
    """Test direct conflicts between obligations and prohibitions."""
    
    def test_obligation_prohibition_conflict(self):
        """
        GIVEN: An obligation and prohibition for the same action
        WHEN: Conflict detection is performed
        THEN: A direct conflict should be detected
        """
        elements = [
            {
                "norm_type": "obligation",
                "deontic_operator": "O",
                "action": "file taxes",
                "subject": "citizens",
                "conditions": [],
                "temporal_constraints": [],
                "exceptions": []
            },
            {
                "norm_type": "prohibition",
                "deontic_operator": "F",
                "action": "file taxes",
                "subject": "citizens",
                "conditions": [],
                "temporal_constraints": [],
                "exceptions": []
            }
        ]
        
        conflicts = detect_normative_conflicts(elements)
        
        assert len(conflicts) == 1
        assert conflicts[0]["type"] == "direct_conflict"
        assert conflicts[0]["severity"] == "high"
        assert "lex_superior" in conflicts[0]["resolution_strategies"]
    
    def test_no_conflict_different_actions(self):
        """
        GIVEN: An obligation and prohibition for different actions
        WHEN: Conflict detection is performed
        THEN: No conflict should be detected
        """
        elements = [
            {
                "norm_type": "obligation",
                "action": "file taxes",
                "subject": "citizens",
                "conditions": [],
                "temporal_constraints": [],
                "exceptions": []
            },
            {
                "norm_type": "prohibition",
                "action": "commit fraud",
                "subject": "citizens",
                "conditions": [],
                "temporal_constraints": [],
                "exceptions": []
            }
        ]
        
        conflicts = detect_normative_conflicts(elements)
        
        assert len(conflicts) == 0


class TestPermissionConflicts:
    """Test conflicts between permissions and prohibitions."""
    
    def test_permission_prohibition_conflict(self):
        """
        GIVEN: A permission and prohibition for the same action
        WHEN: Conflict detection is performed
        THEN: A permission conflict should be detected
        """
        elements = [
            {
                "norm_type": "permission",
                "deontic_operator": "P",
                "action": "park here",
                "subject": "visitors",
                "conditions": [],
                "temporal_constraints": [],
                "exceptions": []
            },
            {
                "norm_type": "prohibition",
                "deontic_operator": "F",
                "action": "park here",
                "subject": "visitors",
                "conditions": [],
                "temporal_constraints": [],
                "exceptions": []
            }
        ]
        
        conflicts = detect_normative_conflicts(elements)
        
        assert len(conflicts) == 1
        assert conflicts[0]["type"] == "permission_conflict"
        assert conflicts[0]["severity"] == "medium"


class TestTemporalConflicts:
    """Test conflicts with temporal constraints."""
    
    def test_temporal_obligation_prohibition_conflict(self):
        """
        GIVEN: An obligation and prohibition with overlapping time periods
        WHEN: Conflict detection is performed
        THEN: A temporal conflict should be detected
        """
        elements = [
            {
                "norm_type": "obligation",
                "action": "submit report",
                "subject": "employees",
                "conditions": [],
                "temporal_constraints": ["by March 15"],
                "exceptions": []
            },
            {
                "norm_type": "prohibition",
                "action": "submit report",
                "subject": "employees",
                "conditions": [],
                "temporal_constraints": ["during March"],
                "exceptions": []
            }
        ]
        
        conflicts = detect_normative_conflicts(elements)
        
        assert len(conflicts) == 1
        assert conflicts[0]["type"] == "temporal_conflict"
        assert conflicts[0]["severity"] == "medium"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_empty_elements_list(self):
        """
        GIVEN: An empty list of normative elements
        WHEN: Conflict detection is performed
        THEN: No conflicts should be detected
        """
        elements = []
        conflicts = detect_normative_conflicts(elements)
        assert len(conflicts) == 0
    
    def test_missing_action_field(self):
        """
        GIVEN: Normative elements with missing action fields
        WHEN: Conflict detection is performed
        THEN: No conflicts should be detected (gracefully handled)
        """
        elements = [
            {
                "norm_type": "obligation",
                "subject": "citizens",
                "conditions": [],
                "temporal_constraints": [],
                "exceptions": []
            },
            {
                "norm_type": "prohibition",
                "subject": "citizens",
                "conditions": [],
                "temporal_constraints": [],
                "exceptions": []
            }
        ]
        conflicts = detect_normative_conflicts(elements)
        assert len(conflicts) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
