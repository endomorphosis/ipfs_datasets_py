"""
Comprehensive tests for audit_logger.py TypedDict contracts.

Tests validate:
1. RoundSummaryDict structure and field types
2. ScoreEvolutionEntryDict structure
3. ActionHistoryEntryDict structure
4. Method return type contracts
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock

from ipfs_datasets_py.optimizers.graphrag.audit_logger import (
    AuditLogger,
    AuditEvent,
    EventType,
    RoundSummaryDict,
    ScoreEvolutionEntryDict,
    ActionHistoryEntryDict,
)


class TestRoundSummaryDictType:
    """Validate RoundSummaryDict structure and field types"""
    
    def test_get_round_summary_returns_round_summary_dict(self):
        """Verify get_round_summary returns RoundSummaryDict"""
        logger = AuditLogger()
        
        # Add a test event
        event = AuditEvent.create(
            event_type=EventType.SCORE_UPDATE,
            round_num=1,
            event_data={'before': {}, 'after': {}, 'delta': {}},
        )
        logger._add_event(event)
        
        result = logger.get_round_summary(1)
        
        assert isinstance(result, dict)
        assert 'round_num' in result
        assert 'event_count' in result
        assert 'events_by_type' in result
    
    def test_round_summary_dict_has_all_required_fields(self):
        """Verify all RoundSummaryDict fields are present"""
        logger = AuditLogger()
        event = AuditEvent.create(
            event_type=EventType.STRATEGY_DECISION,
            round_num=2,
            event_data={'action': 'test'},
        )
        logger._add_event(event)
        
        result = logger.get_round_summary(2)
        
        assert 'round_num' in result
        assert 'event_count' in result
        assert 'events_by_type' in result
        assert 'events' in result
    
    def test_round_summary_dict_round_num_is_correct(self):
        """Verify round_num field matches requested round"""
        logger = AuditLogger()
        event1 = AuditEvent.create(EventType.SCORE_UPDATE, 1, {})
        event2 = AuditEvent.create(EventType.ACTION_APPLY, 2, {})
        logger._add_event(event1)
        logger._add_event(event2)
        
        result = logger.get_round_summary(1)
        
        assert result['round_num'] == 1
        assert result['event_count'] == 1
    
    def test_round_summary_dict_event_count_is_int(self):
        """Verify event_count is integer"""
        logger = AuditLogger()
        event = AuditEvent.create(EventType.SCORE_UPDATE, 1, {})
        logger._add_event(event)
        
        result = logger.get_round_summary(1)
        
        assert isinstance(result['event_count'], int)
        assert result['event_count'] >= 0
    
    def test_round_summary_dict_events_by_type_is_dict(self):
        """Verify events_by_type is dictionary"""
        logger = AuditLogger()
        event1 = AuditEvent.create(EventType.SCORE_UPDATE, 1, {})
        event2 = AuditEvent.create(EventType.STRATEGY_DECISION, 1, {})
        logger._add_event(event1)
        logger._add_event(event2)
        
        result = logger.get_round_summary(1)
        
        assert isinstance(result['events_by_type'], dict)
        assert all(isinstance(k, str) for k in result['events_by_type'].keys())
        assert all(isinstance(v, int) for v in result['events_by_type'].values())
    
    def test_round_summary_dict_events_is_list(self):
        """Verify events field is list of dicts"""
        logger = AuditLogger()
        event = AuditEvent.create(EventType.SCORE_UPDATE, 1, {'data': 'test'})
        logger._add_event(event)
        
        result = logger.get_round_summary(1)
        
        assert isinstance(result['events'], list)
        assert all(isinstance(e, dict) for e in result['events'])


class TestScoreEvolutionEntryDictType:
    """Validate ScoreEvolutionEntryDict structure"""
    
    def test_get_score_evolution_returns_list_of_score_entries(self):
        """Verify get_score_evolution returns list of ScoreEvolutionEntryDict"""
        logger = AuditLogger()
        event = AuditEvent.create(
            event_type=EventType.SCORE_UPDATE,
            round_num=1,
            event_data={
                'before': {'overall': 0.5, 'completeness': 0.6, 'consistency': 0.7, 'clarity': 0.8},
                'after': {'overall': 0.6, 'completeness': 0.65, 'consistency': 0.75, 'clarity': 0.85},
                'delta': {'overall': 0.1, 'completeness': 0.05, 'consistency': 0.05, 'clarity': 0.05},
            },
        )
        logger._add_event(event)
        
        result = logger.get_score_evolution()
        
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(e, dict) for e in result)
    
    def test_score_evolution_entry_has_required_fields(self):
        """Verify ScoreEvolutionEntryDict has all fields"""
        logger = AuditLogger()
        event = AuditEvent.create(
            event_type=EventType.SCORE_UPDATE,
            round_num=1,
            event_data={
                'before': {'overall': 0.5},
                'after': {'overall': 0.6},
                'delta': {'overall': 0.1},
            },
        )
        logger._add_event(event)
        
        result = logger.get_score_evolution()
        
        assert len(result) > 0
        entry = result[0]
        assert 'round' in entry
        assert 'timestamp' in entry
        assert 'score' in entry
        assert 'delta' in entry
    
    def test_score_evolution_entry_round_is_int(self):
        """Verify round field is integer"""
        logger = AuditLogger()
        event = AuditEvent.create(
            event_type=EventType.SCORE_UPDATE,
            round_num=3,
            event_data={
                'before': {},
                'after': {'overall': 0.7},
                'delta': {'overall': 0.0},
            },
        )
        logger._add_event(event)
        
        result = logger.get_score_evolution()
        entry = result[0]
        
        assert isinstance(entry['round'], int)
        assert entry['round'] == 3
    
    def test_score_evolution_entry_timestamp_is_string(self):
        """Verify timestamp field is ISO 8601 string"""
        logger = AuditLogger()
        event = AuditEvent.create(
            event_type=EventType.SCORE_UPDATE,
            round_num=1,
            event_data={'before': {}, 'after': {}, 'delta': {}},
        )
        logger._add_event(event)
        
        result = logger.get_score_evolution()
        entry = result[0]
        
        assert isinstance(entry['timestamp'], str)
        # Should be ISO format (ends with Z)
        assert entry['timestamp'].endswith('Z') or '+' in entry['timestamp']
    
    def test_score_evolution_entry_score_is_dict(self):
        """Verify score field is dictionary of floats"""
        logger = AuditLogger()
        event = AuditEvent.create(
            event_type=EventType.SCORE_UPDATE,
            round_num=1,
            event_data={
                'before': {'overall': 0.5, 'completeness': 0.6},
                'after': {'overall': 0.7, 'completeness': 0.8},
                'delta': {'overall': 0.2, 'completeness': 0.2},
            },
        )
        logger._add_event(event)
        
        result = logger.get_score_evolution()
        entry = result[0]
        
        assert isinstance(entry['score'], dict)
        assert all(isinstance(v, (int, float)) for v in entry['score'].values())
    
    def test_score_evolution_entry_delta_is_dict(self):
        """Verify delta field is dictionary of score changes"""
        logger = AuditLogger()
        event = AuditEvent.create(
            event_type=EventType.SCORE_UPDATE,
            round_num=1,
            event_data={
                'before': {'overall': 0.5},
                'after': {'overall': 0.7},
                'delta': {'overall': 0.2},
            },
        )
        logger._add_event(event)
        
        result = logger.get_score_evolution()
        entry = result[0]
        
        assert isinstance(entry['delta'], dict)
        assert all(isinstance(v, (int, float)) for v in entry['delta'].values())


class TestActionHistoryEntryDictType:
    """Validate ActionHistoryEntryDict structure"""
    
    def test_get_action_history_returns_list_of_action_entries(self):
        """Verify get_action_history returns list of ActionHistoryEntryDict"""
        logger = AuditLogger()
        event = AuditEvent.create(
            event_type=EventType.ACTION_APPLY,
            round_num=1,
            event_data={
                'action_name': 'merge_duplicates',
                'before': {'entity_count': 100, 'relationship_count': 150},
                'after': {'entity_count': 95, 'relationship_count': 145},
                'delta': {'entities': -5, 'relationships': -5},
                'execution_time_ms': 123.45,
            },
        )
        logger._add_event(event)
        
        result = logger.get_action_history()
        
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(e, dict) for e in result)
    
    def test_action_history_entry_has_required_fields(self):
        """Verify ActionHistoryEntryDict has all fields"""
        logger = AuditLogger()
        event = AuditEvent.create(
            event_type=EventType.ACTION_APPLY,
            round_num=1,
            event_data={
                'action_name': 'test_action',
                'delta': {'entities': -1, 'relationships': 0},
                'execution_time_ms': 50.0,
            },
        )
        logger._add_event(event)
        
        result = logger.get_action_history()
        
        assert len(result) > 0
        entry = result[0]
        assert 'round' in entry
        assert 'timestamp' in entry
        assert 'action' in entry
        assert 'delta' in entry
    
    def test_action_history_entry_round_is_int(self):
        """Verify round field is integer"""
        logger = AuditLogger()
        event = AuditEvent.create(
            event_type=EventType.ACTION_APPLY,
            round_num=5,
            event_data={'action_name': 'test', 'delta': {}},
        )
        logger._add_event(event)
        
        result = logger.get_action_history()
        entry = result[0]
        
        assert isinstance(entry['round'], int)
        assert entry['round'] == 5
    
    def test_action_history_entry_action_is_string(self):
        """Verify action field is string"""
        logger = AuditLogger()
        action_name = 'normalize_entities'
        event = AuditEvent.create(
            event_type=EventType.ACTION_APPLY,
            round_num=1,
            event_data={'action_name': action_name, 'delta': {}},
        )
        logger._add_event(event)
        
        result = logger.get_action_history()
        entry = result[0]
        
        assert isinstance(entry['action'], str)
        assert entry['action'] == action_name
    
    def test_action_history_entry_delta_is_dict_with_int(self):
        """Verify delta field contains integer counts"""
        logger = AuditLogger()
        event = AuditEvent.create(
            event_type=EventType.ACTION_APPLY,
            round_num=1,
            event_data={
                'action_name': 'merge',
                'delta': {'entities': -10, 'relationships': -5},
            },
        )
        logger._add_event(event)
        
        result = logger.get_action_history()
        entry = result[0]
        
        assert isinstance(entry['delta'], dict)
        assert all(isinstance(v, int) for v in entry['delta'].values())
    
    def test_action_history_entry_execution_time_optional(self):
        """Verify execution_time_ms is optional"""
        logger = AuditLogger()
        event1 = AuditEvent.create(
            event_type=EventType.ACTION_APPLY,
            round_num=1,
            event_data={
                'action_name': 'action1',
                'delta': {},
                'execution_time_ms': 100.5,
            },
        )
        event2 = AuditEvent.create(
            event_type=EventType.ACTION_APPLY,
            round_num=1,
            event_data={
                'action_name': 'action2',
                'delta': {},
                # No execution_time_ms
            },
        )
        logger._add_event(event1)
        logger._add_event(event2)
        
        result = logger.get_action_history()
        
        # Both entries should be valid
        assert len(result) == 2
        # First entry has execution_time_ms
        assert result[0].get('execution_time_ms') is not None
        # Second entry might not have it
        if 'execution_time_ms' in result[1]:
            assert result[1]['execution_time_ms'] is None or isinstance(result[1]['execution_time_ms'], (int, float))


class TestTypeContractConsistency:
    """Verify type contract consistency"""
    
    def test_multiple_score_evolution_calls_consistent(self):
        """Verify get_score_evolution returns consistent structure"""
        logger = AuditLogger()
        event = AuditEvent.create(
            event_type=EventType.SCORE_UPDATE,
            round_num=1,
            event_data={'before': {}, 'after': {}, 'delta': {}},
        )
        logger._add_event(event)
        
        result1 = logger.get_score_evolution()
        result2 = logger.get_score_evolution()
        
        # Both should be lists with same keys
        assert type(result1) == type(result2)
        if result1:
            assert set(result1[0].keys()) == set(result2[0].keys())
    
    def test_multiple_action_history_calls_consistent(self):
        """Verify get_action_history returns consistent structure"""
        logger = AuditLogger()
        event = AuditEvent.create(
            event_type=EventType.ACTION_APPLY,
            round_num=1,
            event_data={'action_name': 'test', 'delta': {}},
        )
        logger._add_event(event)
        
        result1 = logger.get_action_history()
        result2 = logger.get_action_history()
        
        # Both should be lists with same keys
        assert type(result1) == type(result2)
        if result1:
            assert set(result1[0].keys()) == set(result2[0].keys())


class TestEmptyAuditLogs:
    """Test type contracts with empty audit trails"""
    
    def test_score_evolution_empty(self):
        """Verify get_score_evolution returns empty list when no score events"""
        logger = AuditLogger()
        result = logger.get_score_evolution()
        
        assert isinstance(result, list)
        assert len(result) == 0
    
    def test_action_history_empty(self):
        """Verify get_action_history returns empty list when no action events"""
        logger = AuditLogger()
        result = logger.get_action_history()
        
        assert isinstance(result, list)
        assert len(result) == 0
    
    def test_round_summary_nonexistent_round(self):
        """Verify get_round_summary returns valid structure for nonexistent round"""
        logger = AuditLogger()
        result = logger.get_round_summary(999)
        
        assert isinstance(result, dict)
        assert 'round_num' in result
        assert 'event_count' in result
        assert result['event_count'] == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
