"""Tests for Ontology Evolution.

This module contains comprehensive tests for the real-time ontology evolution
system that learns from new statements and adapts dynamically.
"""

import json
import tempfile
import os
from unittest.mock import Mock
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.ontology_evolution import (
    OntologyEvolution,
    UpdateStrategy,
    EvolutionEvent,
    OntologyVersion,
    EvolutionMetrics,
    UpdateCandidate,
)


class TestUpdateStrategy:
    """Tests for UpdateStrategy enum."""
    
    def test_update_strategy_values(self):
        """
        GIVEN the UpdateStrategy enum
        WHEN accessing strategy values
        THEN all expected strategies should be available
        """
        assert UpdateStrategy.CONSERVATIVE.value == "conservative"
        assert UpdateStrategy.MODERATE.value == "moderate"
        assert UpdateStrategy.AGGRESSIVE.value == "aggressive"
        assert UpdateStrategy.MANUAL.value == "manual"


class TestEvolutionEvent:
    """Tests for EvolutionEvent enum."""
    
    def test_evolution_event_values(self):
        """
        GIVEN the EvolutionEvent enum
        WHEN accessing event values
        THEN all expected events should be available
        """
        assert EvolutionEvent.TERM_ADDED.value == "term_added"
        assert EvolutionEvent.TERM_REMOVED.value == "term_removed"
        assert EvolutionEvent.RELATION_ADDED.value == "relation_added"
        assert EvolutionEvent.RELATION_REMOVED.value == "relation_removed"


class TestOntologyVersion:
    """Tests for OntologyVersion dataclass."""
    
    def test_ontology_version_creation(self):
        """
        GIVEN version data
        WHEN creating OntologyVersion
        THEN version should have correct attributes and computed hash
        """
        ontology = {'terms': ['Employee', 'Manager']}
        changes = [(EvolutionEvent.TERM_ADDED, 'Manager')]
        
        version = OntologyVersion(
            version=1,
            timestamp=1234567890.0,
            ontology=ontology,
            changes=changes
        )
        
        assert version.version == 1
        assert version.timestamp == 1234567890.0
        assert version.ontology == ontology
        assert len(version.changes) == 1
        assert version.hash != ""  # Hash should be computed
    
    def test_ontology_version_hash_consistency(self):
        """
        GIVEN same ontology data
        WHEN creating two versions
        THEN hashes should be identical
        """
        ontology = {'terms': ['Employee']}
        
        v1 = OntologyVersion(version=1, timestamp=1.0, ontology=ontology, changes=[])
        v2 = OntologyVersion(version=2, timestamp=2.0, ontology=ontology, changes=[])
        
        assert v1.hash == v2.hash  # Same ontology, same hash


class TestEvolutionMetrics:
    """Tests for EvolutionMetrics dataclass."""
    
    def test_evolution_metrics_creation(self):
        """
        GIVEN metrics data
        WHEN creating EvolutionMetrics
        THEN metrics should have correct default values
        """
        metrics = EvolutionMetrics()
        
        assert metrics.total_updates == 0
        assert metrics.terms_added == 0
        assert metrics.rollbacks == 0
        assert metrics.stability_score == 1.0


class TestUpdateCandidate:
    """Tests for UpdateCandidate dataclass."""
    
    def test_update_candidate_creation(self):
        """
        GIVEN candidate data
        WHEN creating UpdateCandidate
        THEN candidate should have correct attributes
        """
        candidate = UpdateCandidate(
            event_type=EvolutionEvent.TERM_ADDED,
            item="NewTerm",
            confidence=0.85,
            evidence=["Appears 10 times"],
            source="frequency_analysis"
        )
        
        assert candidate.event_type == EvolutionEvent.TERM_ADDED
        assert candidate.item == "NewTerm"
        assert candidate.confidence == 0.85
        assert len(candidate.evidence) == 1


class TestOntologyEvolution:
    """Tests for OntologyEvolution."""
    
    def test_init_default_params(self):
        """
        GIVEN default parameters
        WHEN initializing OntologyEvolution
        THEN evolution manager should be initialized with defaults
        """
        evolution = OntologyEvolution()
        
        assert evolution.strategy == UpdateStrategy.MODERATE
        assert evolution.enable_versioning is True
        assert evolution.max_versions == 100
        assert evolution.confidence_threshold == 0.7
        assert len(evolution.current_ontology) > 0
    
    def test_init_with_base_ontology(self):
        """
        GIVEN a base ontology
        WHEN initializing OntologyEvolution
        THEN base ontology should be used
        """
        base = {
            'terms': ['Employee', 'Manager'],
            'relations': ['reports_to'],
            'types': ['Agent']
        }
        
        evolution = OntologyEvolution(base_ontology=base)
        
        assert evolution.current_ontology['terms'] == ['Employee', 'Manager']
        assert evolution.current_ontology['relations'] == ['reports_to']
    
    def test_init_creates_initial_version(self):
        """
        GIVEN versioning enabled
        WHEN initializing OntologyEvolution
        THEN initial version should be saved
        """
        evolution = OntologyEvolution(enable_versioning=True)
        
        assert len(evolution.versions) == 1
        assert evolution.current_version == 1
        assert evolution.versions[0].version == 0
    
    def test_extract_terms_from_formula(self):
        """
        GIVEN a logical formula
        WHEN extracting terms
        THEN predicates and constants should be extracted
        """
        evolution = OntologyEvolution()
        
        formula = "∀x (Employee(x) → Has(x, Training))"
        terms = evolution._extract_terms(formula)
        
        assert 'Employee' in terms
        assert 'Has' in terms
        assert 'Training' in terms
    
    def test_learn_from_statements_single(self):
        """
        GIVEN a single statement
        WHEN learning from it
        THEN term frequencies should be updated
        """
        evolution = OntologyEvolution()
        
        # Create mock statement
        stmt = Mock()
        stmt.formula = "Employee(x)"
        stmt.relations = []
        
        evolution.learn_from_statements([stmt])
        
        assert evolution.term_frequency['Employee'] == 1
    
    def test_learn_from_statements_multiple(self):
        """
        GIVEN multiple statements
        WHEN learning from them
        THEN update candidates should be generated
        """
        evolution = OntologyEvolution()
        
        statements = []
        for _ in range(15):  # Enough to generate confident candidates
            stmt = Mock()
            stmt.formula = "NewTerm(x)"
            stmt.relations = []
            statements.append(stmt)
        
        candidates_generated = evolution.learn_from_statements(statements)
        
        assert candidates_generated > 0
        assert evolution.term_frequency['NewTerm'] == 15
    
    def test_learn_from_statements_cooccurrence(self):
        """
        GIVEN statements with co-occurring terms
        WHEN learning from them
        THEN co-occurrence should be tracked
        """
        evolution = OntologyEvolution()
        
        statements = []
        for _ in range(5):
            stmt = Mock()
            stmt.formula = "Employee(x) Manager(y)"
            stmt.relations = []
            statements.append(stmt)
        
        evolution.learn_from_statements(statements)
        
        # Check co-occurrence
        pair = tuple(sorted(['Employee', 'Manager']))
        assert evolution.cooccurrence[pair] == 5
    
    def test_get_update_candidates_no_filter(self):
        """
        GIVEN update candidates exist
        WHEN getting candidates without filters
        THEN all candidates should be returned
        """
        evolution = OntologyEvolution()
        
        # Add some candidates
        evolution.update_candidates = [
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term1", 0.8),
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term2", 0.6),
            UpdateCandidate(EvolutionEvent.RELATION_ADDED, "Rel1", 0.9)
        ]
        
        candidates = evolution.get_update_candidates()
        
        assert len(candidates) == 3
    
    def test_get_update_candidates_confidence_filter(self):
        """
        GIVEN update candidates with varying confidence
        WHEN filtering by minimum confidence
        THEN only high-confidence candidates should be returned
        """
        evolution = OntologyEvolution()
        
        evolution.update_candidates = [
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term1", 0.9),
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term2", 0.6),
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term3", 0.85)
        ]
        
        candidates = evolution.get_update_candidates(min_confidence=0.8)
        
        assert len(candidates) == 2
        assert all(c.confidence >= 0.8 for c in candidates)
    
    def test_get_update_candidates_event_type_filter(self):
        """
        GIVEN mixed update candidates
        WHEN filtering by event type
        THEN only matching candidates should be returned
        """
        evolution = OntologyEvolution()
        
        evolution.update_candidates = [
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term1", 0.9),
            UpdateCandidate(EvolutionEvent.RELATION_ADDED, "Rel1", 0.8),
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term2", 0.85)
        ]
        
        candidates = evolution.get_update_candidates(
            event_type=EvolutionEvent.TERM_ADDED
        )
        
        assert len(candidates) == 2
        assert all(c.event_type == EvolutionEvent.TERM_ADDED for c in candidates)
    
    def test_validate_update_valid_term(self):
        """
        GIVEN a valid term update
        WHEN validating
        THEN validation should pass
        """
        evolution = OntologyEvolution()
        
        candidate = UpdateCandidate(
            EvolutionEvent.TERM_ADDED,
            "ValidTerm",
            0.9
        )
        
        assert evolution._validate_update(candidate) is True
    
    def test_validate_update_invalid_term(self):
        """
        GIVEN an invalid term update
        WHEN validating
        THEN validation should fail
        """
        evolution = OntologyEvolution()
        
        candidate = UpdateCandidate(
            EvolutionEvent.TERM_ADDED,
            "123Invalid",  # Starts with number
            0.9
        )
        
        assert evolution._validate_update(candidate) is False
    
    def test_apply_updates_conservative_strategy(self):
        """
        GIVEN CONSERVATIVE strategy
        WHEN applying updates
        THEN only high-confidence updates should be applied
        """
        evolution = OntologyEvolution(strategy=UpdateStrategy.CONSERVATIVE)
        
        candidates = [
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "HighConf", 0.95),
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "MedConf", 0.8),
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "LowConf", 0.6)
        ]
        
        applied = evolution.apply_updates(candidates)
        
        # Only >= 0.9 should be applied
        assert applied == 1
        assert 'HighConf' in evolution.current_ontology['terms']
        assert 'MedConf' not in evolution.current_ontology['terms']
    
    def test_apply_updates_moderate_strategy(self):
        """
        GIVEN MODERATE strategy
        WHEN applying updates
        THEN medium and high confidence updates should be applied
        """
        evolution = OntologyEvolution(strategy=UpdateStrategy.MODERATE)
        
        candidates = [
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "HighConf", 0.9),
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "MedConf", 0.75),
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "LowConf", 0.6)
        ]
        
        applied = evolution.apply_updates(candidates)
        
        # >= 0.7 should be applied
        assert applied == 2
        assert 'HighConf' in evolution.current_ontology['terms']
        assert 'MedConf' in evolution.current_ontology['terms']
    
    def test_apply_updates_aggressive_strategy(self):
        """
        GIVEN AGGRESSIVE strategy
        WHEN applying updates
        THEN all valid updates should be applied
        """
        evolution = OntologyEvolution(strategy=UpdateStrategy.AGGRESSIVE)
        
        candidates = [
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "HighConf", 0.9),
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "MedConf", 0.7),
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "LowConf", 0.5)
        ]
        
        applied = evolution.apply_updates(candidates)
        
        # All should be applied
        assert applied == 3
    
    def test_apply_updates_manual_strategy(self):
        """
        GIVEN MANUAL strategy
        WHEN applying updates
        THEN no updates should be auto-applied
        """
        evolution = OntologyEvolution(strategy=UpdateStrategy.MANUAL)
        
        candidates = [
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term1", 0.95)
        ]
        
        applied = evolution.apply_updates(candidates)
        
        assert applied == 0
    
    def test_apply_updates_creates_version(self):
        """
        GIVEN versioning enabled
        WHEN applying updates
        THEN new version should be created
        """
        evolution = OntologyEvolution(enable_versioning=True)
        initial_versions = len(evolution.versions)
        
        candidates = [
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "NewTerm", 0.9)
        ]
        
        evolution.apply_updates(candidates)
        
        assert len(evolution.versions) == initial_versions + 1
    
    def test_apply_updates_updates_metrics(self):
        """
        GIVEN metrics tracking
        WHEN applying updates
        THEN metrics should be updated
        """
        evolution = OntologyEvolution()
        
        candidates = [
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term1", 0.9),
            UpdateCandidate(EvolutionEvent.RELATION_ADDED, "Rel1", 0.85)
        ]
        
        evolution.apply_updates(candidates)
        
        metrics = evolution.get_metrics()
        assert metrics.total_updates == 2
        assert metrics.terms_added == 1
        assert metrics.relations_added == 1
    
    def test_apply_single_update_term(self):
        """
        GIVEN a term addition candidate
        WHEN applying single update
        THEN term should be added to ontology
        """
        evolution = OntologyEvolution()
        
        candidate = UpdateCandidate(
            EvolutionEvent.TERM_ADDED,
            "NewTerm",
            0.9
        )
        
        result = evolution._apply_single_update(candidate)
        
        assert result is True
        assert 'NewTerm' in evolution.current_ontology['terms']
    
    def test_apply_single_update_relation(self):
        """
        GIVEN a relation addition candidate
        WHEN applying single update
        THEN relation should be added to ontology
        """
        evolution = OntologyEvolution()
        
        candidate = UpdateCandidate(
            EvolutionEvent.RELATION_ADDED,
            {'name': 'works_for', 'from': 'Employee', 'to': 'Company'},
            0.9
        )
        
        result = evolution._apply_single_update(candidate)
        
        assert result is True
        assert 'works_for' in evolution.current_ontology['relations']
    
    def test_rollback_to_version_success(self):
        """
        GIVEN version history exists
        WHEN rolling back to previous version
        THEN ontology should be restored
        """
        evolution = OntologyEvolution()
        
        # Apply some updates to create versions
        candidates = [
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term1", 0.9),
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term2", 0.9)
        ]
        evolution.apply_updates(candidates)
        
        # Get version before second term
        target_version = evolution.versions[-2].version
        
        # Rollback
        success = evolution.rollback_to_version(target_version)
        
        assert success is True
        assert 'Term2' not in evolution.current_ontology.get('terms', [])
    
    def test_rollback_to_version_not_found(self):
        """
        GIVEN version doesn't exist
        WHEN rolling back
        THEN rollback should fail
        """
        evolution = OntologyEvolution()
        
        success = evolution.rollback_to_version(999)
        
        assert success is False
    
    def test_rollback_updates_metrics(self):
        """
        GIVEN a rollback is performed
        WHEN checking metrics
        THEN rollback count should be incremented
        """
        evolution = OntologyEvolution()
        
        # Create a version to rollback to
        candidates = [UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term1", 0.9)]
        evolution.apply_updates(candidates)
        
        initial_rollbacks = evolution.metrics.rollbacks
        
        evolution.rollback_to_version(evolution.versions[0].version)
        
        assert evolution.metrics.rollbacks == initial_rollbacks + 1
    
    def test_get_version_history(self):
        """
        GIVEN version history exists
        WHEN getting history
        THEN summary of all versions should be returned
        """
        evolution = OntologyEvolution()
        
        # Create some versions
        candidates = [
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term1", 0.9)
        ]
        evolution.apply_updates(candidates)
        
        history = evolution.get_version_history()
        
        assert len(history) == len(evolution.versions)
        assert all('version' in h for h in history)
        assert all('timestamp' in h for h in history)
    
    def test_get_metrics(self):
        """
        GIVEN evolution activity
        WHEN getting metrics
        THEN current metrics should be returned with stability
        """
        evolution = OntologyEvolution()
        
        # Perform some updates
        candidates = [
            UpdateCandidate(EvolutionEvent.TERM_ADDED, f"Term{i}", 0.9)
            for i in range(5)
        ]
        evolution.apply_updates(candidates)
        
        metrics = evolution.get_metrics()
        
        assert metrics.total_updates == 5
        assert metrics.terms_added == 5
        assert metrics.current_version == evolution.current_version
        assert 0.0 <= metrics.stability_score <= 1.0
    
    def test_export_ontology(self):
        """
        GIVEN current ontology
        WHEN exporting to file
        THEN file should be created with valid JSON
        """
        evolution = OntologyEvolution()
        evolution.current_ontology['terms'].append('TestTerm')
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            filepath = f.name
        
        try:
            evolution.export_ontology(filepath)
            
            assert os.path.exists(filepath)
            
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            assert 'TestTerm' in data.get('terms', [])
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_export_version_history(self):
        """
        GIVEN version history
        WHEN exporting to file
        THEN file should contain all versions
        """
        evolution = OntologyEvolution()
        
        # Create some versions
        candidates = [UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term1", 0.9)]
        evolution.apply_updates(candidates)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            filepath = f.name
        
        try:
            evolution.export_version_history(filepath)
            
            assert os.path.exists(filepath)
            
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            assert len(data) == len(evolution.versions)
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_get_statistics(self):
        """
        GIVEN evolution state
        WHEN getting statistics
        THEN comprehensive stats should be returned
        """
        evolution = OntologyEvolution()
        
        # Add some activity
        candidates = [
            UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term1", 0.9),
            UpdateCandidate(EvolutionEvent.RELATION_ADDED, "Rel1", 0.85)
        ]
        evolution.apply_updates(candidates)
        
        stats = evolution.get_statistics()
        
        assert 'current_version' in stats
        assert 'total_versions' in stats
        assert 'terms_count' in stats
        assert 'relations_count' in stats
        assert 'strategy' in stats
        assert 'metrics' in stats
        assert stats['terms_count'] >= 1
    
    def test_max_versions_pruning(self):
        """
        GIVEN max_versions limit
        WHEN exceeding the limit
        THEN old versions should be pruned
        """
        evolution = OntologyEvolution(max_versions=3)
        
        # Create more versions than max
        for i in range(5):
            candidates = [UpdateCandidate(EvolutionEvent.TERM_ADDED, f"Term{i}", 0.9)]
            evolution.apply_updates(candidates)
        
        # Should only keep last 3 versions
        assert len(evolution.versions) <= 3
    
    def test_disabled_versioning(self):
        """
        GIVEN versioning disabled
        WHEN applying updates
        THEN no versions should be saved
        """
        evolution = OntologyEvolution(enable_versioning=False)
        
        candidates = [UpdateCandidate(EvolutionEvent.TERM_ADDED, "Term1", 0.9)]
        evolution.apply_updates(candidates)
        
        # No versions should be saved (except maybe initial)
        assert len(evolution.versions) == 0
