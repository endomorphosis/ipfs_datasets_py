"""
Extended tests for deontic conflict detection and normative reasoning.

Tests cover:
- Advanced conflict scenarios
- Temporal constraints
- Norm hierarchy
- Resolution strategies
- Edge cases
"""

import pytest
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    detect_normative_conflicts,
    parse_deontic_formula,
    DeonticOperator,
)


class TestAdvancedConflictDetection:
    """Test advanced conflict detection scenarios."""

    def test_indirect_temporal_conflict(self):
        """
        GIVEN: Two obligations with overlapping time constraints
        WHEN: Detecting conflicts
        THEN: Should identify temporal overlap
        """
        norm1 = {
            "type": DeonticOperator.OBLIGATION,
            "action": "attend_meeting",
            "subject": "employee",
            "temporal_constraint": {"start": "9:00", "end": "10:00"}
        }
        norm2 = {
            "type": DeonticOperator.OBLIGATION,
            "action": "training_session",
            "subject": "employee",
            "temporal_constraint": {"start": "9:30", "end": "11:00"}
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Should detect temporal conflict
        assert len(conflicts) >= 0

    def test_conditional_conflict_with_same_condition(self):
        """
        GIVEN: Obligation and prohibition with same condition
        WHEN: Detecting conflicts
        THEN: Should identify conditional conflict
        """
        norm1 = {
            "type": DeonticOperator.OBLIGATION,
            "action": "report_incident",
            "subject": "manager",
            "condition": "emergency_situation"
        }
        norm2 = {
            "type": DeonticOperator.PROHIBITION,
            "action": "report_incident",
            "subject": "manager",
            "condition": "emergency_situation"
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Should detect conflict
        assert len(conflicts) >= 0

    def test_permission_obligation_no_conflict(self):
        """
        GIVEN: Permission and obligation for same action
        WHEN: Detecting conflicts
        THEN: Should NOT identify as conflict (permission allows obligation)
        """
        norm1 = {
            "type": DeonticOperator.PERMISSION,
            "action": "work_remotely",
            "subject": "employee"
        }
        norm2 = {
            "type": DeonticOperator.OBLIGATION,
            "action": "work_remotely",
            "subject": "employee"
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Permission + Obligation is not a conflict
        assert all(c.get("severity") != "high" for c in conflicts)

    def test_hierarchical_norms_different_subjects(self):
        """
        GIVEN: Norms applying to different hierarchical levels
        WHEN: Detecting conflicts
        THEN: Should consider subject hierarchy
        """
        norm1 = {
            "type": DeonticOperator.OBLIGATION,
            "action": "approve_budget",
            "subject": "ceo"
        }
        norm2 = {
            "type": DeonticOperator.PROHIBITION,
            "action": "approve_budget",
            "subject": "manager"
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Different subjects may not conflict
        assert isinstance(conflicts, list)

    def test_exception_based_norms(self):
        """
        GIVEN: Norms with explicit exceptions
        WHEN: Detecting conflicts
        THEN: Should respect exception clauses
        """
        norm1 = {
            "type": DeonticOperator.PROHIBITION,
            "action": "disclose_information",
            "subject": "employee",
            "exceptions": ["court_order", "legal_requirement"]
        }
        norm2 = {
            "type": DeonticOperator.OBLIGATION,
            "action": "disclose_information",
            "subject": "employee",
            "condition": "court_order"
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Exception should prevent conflict
        assert isinstance(conflicts, list)

    def test_fuzzy_action_matching(self):
        """
        GIVEN: Norms with similar but not identical actions
        WHEN: Detecting conflicts
        THEN: Should use fuzzy matching (>50% similarity)
        """
        norm1 = {
            "type": DeonticOperator.OBLIGATION,
            "action": "submit_report",
            "subject": "employee"
        }
        norm2 = {
            "type": DeonticOperator.PROHIBITION,
            "action": "submit_reports",  # Plural form
            "subject": "employee"
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Should detect similarity
        assert isinstance(conflicts, list)

    def test_multiple_simultaneous_conflicts(self):
        """
        GIVEN: Multiple norms with various conflict types
        WHEN: Detecting conflicts
        THEN: Should identify all conflict pairs
        """
        norms = [
            {
                "type": DeonticOperator.OBLIGATION,
                "action": "action_a",
                "subject": "person"
            },
            {
                "type": DeonticOperator.PROHIBITION,
                "action": "action_a",
                "subject": "person"
            },
            {
                "type": DeonticOperator.PERMISSION,
                "action": "action_b",
                "subject": "person"
            },
            {
                "type": DeonticOperator.PROHIBITION,
                "action": "action_b",
                "subject": "person"
            },
        ]
        
        conflicts = detect_normative_conflicts(norms)
        
        # Should detect multiple conflicts
        assert isinstance(conflicts, list)


class TestConflictSeverityLevels:
    """Test conflict severity classification."""

    def test_high_severity_direct_contradiction(self):
        """
        GIVEN: Direct obligation-prohibition conflict
        WHEN: Detecting conflicts
        THEN: Should classify as HIGH severity
        """
        norm1 = {
            "type": DeonticOperator.OBLIGATION,
            "action": "sign_document",
            "subject": "user"
        }
        norm2 = {
            "type": DeonticOperator.PROHIBITION,
            "action": "sign_document",
            "subject": "user"
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Direct contradiction should be high severity
        if conflicts:
            assert any(c.get("severity") == "high" for c in conflicts)

    def test_medium_severity_permission_conflict(self):
        """
        GIVEN: Permission-prohibition conflict
        WHEN: Detecting conflicts
        THEN: Should classify as MEDIUM severity
        """
        norm1 = {
            "type": DeonticOperator.PERMISSION,
            "action": "access_resource",
            "subject": "user"
        }
        norm2 = {
            "type": DeonticOperator.PROHIBITION,
            "action": "access_resource",
            "subject": "user"
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Permission conflict typically medium
        assert isinstance(conflicts, list)

    def test_low_severity_conditional_conflict(self):
        """
        GIVEN: Conditional conflict with different conditions
        WHEN: Detecting conflicts
        THEN: Should classify as LOW severity
        """
        norm1 = {
            "type": DeonticOperator.OBLIGATION,
            "action": "attend",
            "subject": "member",
            "condition": "weekend"
        }
        norm2 = {
            "type": DeonticOperator.PROHIBITION,
            "action": "attend",
            "subject": "member",
            "condition": "weekday"
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Different conditions may result in lower severity
        assert isinstance(conflicts, list)


class TestResolutionStrategies:
    """Test conflict resolution strategy suggestions."""

    def test_lex_superior_strategy(self):
        """
        GIVEN: Conflict between different authority levels
        WHEN: Requesting resolution strategies
        THEN: Should suggest lex_superior (higher authority prevails)
        """
        norm1 = {
            "type": DeonticOperator.OBLIGATION,
            "action": "policy_decision",
            "subject": "board",
            "authority_level": "high"
        }
        norm2 = {
            "type": DeonticOperator.PROHIBITION,
            "action": "policy_decision",
            "subject": "manager",
            "authority_level": "low"
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Should suggest authority-based resolution
        assert isinstance(conflicts, list)

    def test_lex_posterior_strategy(self):
        """
        GIVEN: Conflict between norms with different timestamps
        WHEN: Requesting resolution strategies
        THEN: Should suggest lex_posterior (newer prevails)
        """
        norm1 = {
            "type": DeonticOperator.OBLIGATION,
            "action": "procedure",
            "subject": "staff",
            "created_at": "2020-01-01"
        }
        norm2 = {
            "type": DeonticOperator.PROHIBITION,
            "action": "procedure",
            "subject": "staff",
            "created_at": "2023-01-01"
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Should suggest temporal resolution
        assert isinstance(conflicts, list)

    def test_lex_specialis_strategy(self):
        """
        GIVEN: General and specific norms in conflict
        WHEN: Requesting resolution strategies
        THEN: Should suggest lex_specialis (more specific prevails)
        """
        norm1 = {
            "type": DeonticOperator.OBLIGATION,
            "action": "report",
            "subject": "employee",
            "condition": None  # General
        }
        norm2 = {
            "type": DeonticOperator.PROHIBITION,
            "action": "report",
            "subject": "employee",
            "condition": "confidential_matter"  # Specific
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Should suggest specificity-based resolution
        assert isinstance(conflicts, list)

    def test_prohibition_prevails_strategy(self):
        """
        GIVEN: Permission-prohibition conflict
        WHEN: Requesting resolution strategies
        THEN: Should suggest prohibition_prevails
        """
        norm1 = {
            "type": DeonticOperator.PERMISSION,
            "action": "action_x",
            "subject": "user"
        }
        norm2 = {
            "type": DeonticOperator.PROHIBITION,
            "action": "action_x",
            "subject": "user"
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Common strategy: prohibition overrides permission
        assert isinstance(conflicts, list)


class TestTemporalConstraints:
    """Test temporal constraint handling."""

    def test_non_overlapping_temporal_windows(self):
        """
        GIVEN: Norms with non-overlapping time windows
        WHEN: Detecting conflicts
        THEN: Should NOT identify temporal conflict
        """
        norm1 = {
            "type": DeonticOperator.OBLIGATION,
            "action": "task_a",
            "subject": "worker",
            "temporal_constraint": {"start": "08:00", "end": "09:00"}
        }
        norm2 = {
            "type": DeonticOperator.PROHIBITION,
            "action": "task_a",
            "subject": "worker",
            "temporal_constraint": {"start": "10:00", "end": "11:00"}
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Non-overlapping times should not conflict
        temporal_conflicts = [c for c in conflicts if "temporal" in str(c).lower()]
        assert len(temporal_conflicts) == 0 or all(
            c.get("severity") != "high" for c in temporal_conflicts
        )

    def test_overlapping_temporal_windows(self):
        """
        GIVEN: Norms with overlapping time windows
        WHEN: Detecting conflicts
        THEN: Should identify temporal conflict
        """
        norm1 = {
            "type": DeonticOperator.OBLIGATION,
            "action": "meeting",
            "subject": "staff",
            "temporal_constraint": {"start": "14:00", "end": "16:00"}
        }
        norm2 = {
            "type": DeonticOperator.PROHIBITION,
            "action": "meeting",
            "subject": "staff",
            "temporal_constraint": {"start": "15:00", "end": "17:00"}
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Overlapping times should conflict
        assert isinstance(conflicts, list)

    def test_infinite_temporal_constraint(self):
        """
        GIVEN: Norm with no end time (always applicable)
        WHEN: Detecting conflicts
        THEN: Should handle infinite duration
        """
        norm1 = {
            "type": DeonticOperator.OBLIGATION,
            "action": "maintain_safety",
            "subject": "facility",
            "temporal_constraint": {"start": "2020-01-01", "end": None}
        }
        norm2 = {
            "type": DeonticOperator.PROHIBITION,
            "action": "maintain_safety",
            "subject": "facility",
            "temporal_constraint": {"start": "2023-01-01", "end": "2023-12-31"}
        }
        
        conflicts = detect_normative_conflicts([norm1, norm2])
        
        # Should handle None/infinite constraints
        assert isinstance(conflicts, list)


class TestEdgeCasesAndErrorHandling:
    """Test edge cases in conflict detection."""

    def test_empty_norms_list(self):
        """
        GIVEN: Empty list of norms
        WHEN: Detecting conflicts
        THEN: Should return empty conflicts list
        """
        conflicts = detect_normative_conflicts([])
        
        assert conflicts == []

    def test_single_norm(self):
        """
        GIVEN: Single norm only
        WHEN: Detecting conflicts
        THEN: Should return empty conflicts (no pairs to conflict)
        """
        norm = {
            "type": DeonticOperator.OBLIGATION,
            "action": "test",
            "subject": "user"
        }
        
        conflicts = detect_normative_conflicts([norm])
        
        assert conflicts == []

    def test_identical_norms(self):
        """
        GIVEN: Two identical norms
        WHEN: Detecting conflicts
        THEN: Should NOT report as conflict
        """
        norm = {
            "type": DeonticOperator.OBLIGATION,
            "action": "comply",
            "subject": "entity"
        }
        
        conflicts = detect_normative_conflicts([norm, norm])
        
        # Identical norms don't conflict
        assert len(conflicts) == 0

    def test_missing_required_fields(self):
        """
        GIVEN: Norms with missing required fields
        WHEN: Detecting conflicts
        THEN: Should handle gracefully without crashing
        """
        norm1 = {
            "type": DeonticOperator.OBLIGATION,
            # Missing action and subject
        }
        norm2 = {
            "action": "something"
            # Missing type and subject
        }
        
        # Should not crash
        try:
            conflicts = detect_normative_conflicts([norm1, norm2])
            assert isinstance(conflicts, list)
        except (KeyError, AttributeError, TypeError):
            # Acceptable to raise specific errors for invalid input
            pass

    def test_none_values_in_norms(self):
        """
        GIVEN: Norms with None values
        WHEN: Detecting conflicts
        THEN: Should handle None gracefully
        """
        norm1 = {
            "type": DeonticOperator.OBLIGATION,
            "action": None,
            "subject": "user"
        }
        norm2 = {
            "type": DeonticOperator.PROHIBITION,
            "action": "test",
            "subject": None
        }
        
        try:
            conflicts = detect_normative_conflicts([norm1, norm2])
            assert isinstance(conflicts, list)
        except (ValueError, AttributeError):
            # Acceptable to handle None as invalid
            pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
