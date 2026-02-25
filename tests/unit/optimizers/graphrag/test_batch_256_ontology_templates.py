"""Batch 256: Ontology Templates Comprehensive Test Suite.

Comprehensive testing of OntologyTemplate and OntologyTemplateLibrary for
domain-specific ontology generation with entity/relationship type management,
template validation, generation, merging, and library management.

Test Categories:
- OntologyTemplate creation and validation
- Entity and relationship type management
- OntologyTemplateLibrary initialization
- Template retrieval (legal/medical/scientific/general)
- Ontology generation from templates
- Custom template addition
- Domain listing
- Template merging
"""

import pytest
from typing import Dict, Any, List, Set

from ipfs_datasets_py.optimizers.graphrag.ontology_templates import (
    OntologyTemplate,
    OntologyTemplateLibrary,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def simple_template():
    """Create a simple ontology template."""
    return OntologyTemplate(
        domain='test',
        description='Test template',
        entity_types=['Person', 'Organization'],
        relationship_types=['works_for', 'manages'],
    )


@pytest.fixture
def complex_template():
    """Create a complex ontology template with properties."""
    return OntologyTemplate(
        domain='business',
        description='Business ontology',
        entity_types=['Company', 'Employee', 'Product'],
        relationship_types=['employs', 'produces', 'sells'],
        required_properties={
            'Company': ['name', 'industry'],
            'Employee': ['name', 'role'],
        },
        optional_properties={
            'Company': ['revenue', 'founded'],
            'Employee': ['salary', 'department'],
        },
        metadata={'version': '2.0', 'author': 'test'}
    )


@pytest.fixture
def library():
    """Create a fresh OntologyTemplateLibrary."""
    return OntologyTemplateLibrary()


@pytest.fixture
def valid_legal_ontology():
    """Create a valid legal ontology."""
    return {
        'entities': [
            {'type': 'Party', 'text': 'Alice'},
            {'type': 'Obligation', 'text': 'pay $100'},
        ],
        'relationships': [
            {'type': 'obligates', 'source': 'entity_1', 'target': 'entity_2'}
        ]
    }


@pytest.fixture
def invalid_ontology():
    """Create an ontology with invalid types."""
    return {
        'entities': [
            {'type': 'UnknownType', 'text': 'Something'},
        ],
        'relationships': []
    }


# ============================================================================
# OntologyTemplate Tests
# ============================================================================

class TestOntologyTemplateInitialization:
    """Test OntologyTemplate initialization."""
    
    def test_simple_initialization(self, simple_template):
        """OntologyTemplate initializes with basic fields."""
        assert simple_template.domain == 'test'
        assert simple_template.description == 'Test template'
        assert len(simple_template.entity_types) == 2
        assert len(simple_template.relationship_types) == 2
    
    def test_initialization_with_properties(self, complex_template):
        """OntologyTemplate initializes with required/optional properties."""
        assert 'Company' in complex_template.required_properties
        assert 'Employee' in complex_template.optional_properties
        assert complex_template.required_properties['Company'] == ['name', 'industry']
    
    def test_initialization_with_metadata(self, complex_template):
        """OntologyTemplate initializes with metadata."""
        assert complex_template.metadata['version'] == '2.0'
        assert complex_template.metadata['author'] == 'test'


class TestGetEntityTypes:
    """Test get_entity_types() method."""
    
    def test_returns_set(self, simple_template):
        """get_entity_types returns Set."""
        result = simple_template.get_entity_types()
        
        assert isinstance(result, set)
    
    def test_contains_all_types(self, simple_template):
        """get_entity_types returns all entity types."""
        result = simple_template.get_entity_types()
        
        assert 'Person' in result
        assert 'Organization' in result
        assert len(result) == 2


class TestGetRelationshipTypes:
    """Test get_relationship_types() method."""
    
    def test_returns_set(self, simple_template):
        """get_relationship_types returns Set."""
        result = simple_template.get_relationship_types()
        
        assert isinstance(result, set)
    
    def test_contains_all_types(self, simple_template):
        """get_relationship_types returns all relationship types."""
        result = simple_template.get_relationship_types()
        
        assert 'works_for' in result
        assert 'manages' in result
        assert len(result) == 2


class TestValidateOntology:
    """Test validate_ontology() method."""
    
    def test_valid_ontology_returns_true(self, library, valid_legal_ontology):
        """validate_ontology returns True for valid ontology."""
        template = library.get_template('legal')
        
        result = template.validate_ontology(valid_legal_ontology)
        
        assert result is True
    
    def test_invalid_entity_type_returns_false(self, simple_template, invalid_ontology):
        """validate_ontology returns False for invalid entity types."""
        result = simple_template.validate_ontology(invalid_ontology)
        
        assert result is False
    
    def test_invalid_relationship_type_returns_false(self, simple_template):
        """validate_ontology returns False for invalid relationship types."""
        ontology = {
            'entities': [{'type': 'Person', 'text': 'Alice'}],
            'relationships': [{'type': 'unknown_rel', 'source': 'e1', 'target': 'e2'}]
        }
        
        result = simple_template.validate_ontology(ontology)
        
        assert result is False


# ============================================================================
# OntologyTemplateLibrary Initialization Tests
# ============================================================================

class TestLibraryInitialization:
    """Test OntologyTemplateLibrary initialization."""
    
    def test_initializes_with_default_templates(self, library):
        """Library initializes with default templates."""
        domains = library.list_domains()
        
        assert 'legal' in domains
        assert 'medical' in domains
        assert 'scientific' in domains
        assert 'general' in domains
    
    def test_has_at_least_4_templates(self, library):
        """Library has at least 4 default templates."""
        domains = library.list_domains()
        
        assert len(domains) >= 4


# ============================================================================
# Template Retrieval Tests
# ============================================================================

class TestGetTemplate:
    """Test get_template() method."""
    
    def test_get_legal_template(self, library):
        """get_template retrieves legal template."""
        template = library.get_template('legal')
        
        assert template.domain == 'legal'
        assert 'Party' in template.entity_types
        assert 'obligates' in template.relationship_types
    
    def test_get_medical_template(self, library):
        """get_template retrieves medical template."""
        template = library.get_template('medical')
        
        assert template.domain == 'medical'
        assert 'Patient' in template.entity_types
        assert 'diagnosed_with' in template.relationship_types
    
    def test_get_scientific_template(self, library):
        """get_template retrieves scientific template."""
        template = library.get_template('scientific')
        
        assert template.domain == 'scientific'
        assert 'Researcher' in template.entity_types
        assert 'investigates' in template.relationship_types
    
    def test_get_general_template(self, library):
        """get_template retrieves general template."""
        template = library.get_template('general')
        
        assert template.domain == 'general'
        assert 'Entity' in template.entity_types
        assert 'related_to' in template.relationship_types
    
    def test_unknown_domain_returns_general(self, library):
        """get_template returns general for unknown domain."""
        template = library.get_template('unknown_domain')
        
        assert template.domain == 'general'


# ============================================================================
# Ontology Generation Tests
# ============================================================================

class TestGenerateFromTemplate:
    """Test generate_from_template() method."""
    
    def test_generates_dict(self, library):
        """generate_from_template returns dictionary."""
        result = library.generate_from_template('legal')
        
        assert isinstance(result, dict)
        assert 'entities' in result
        assert 'relationships' in result
    
    def test_generates_with_parties(self, library):
        """generate_from_template creates entities from parties parameter."""
        result = library.generate_from_template(
            'legal',
            parties=['Alice', 'Bob', 'Charlie']
        )
        
        # Should create 3 Party entities
        parties = [e for e in result['entities'] if e['type'] == 'Party']
        assert len(parties) == 3
        assert parties[0]['text'] == 'Alice'
        assert parties[1]['text'] == 'Bob'
    
    def test_generates_with_obligations(self, library):
        """generate_from_template creates entities from obligations parameter."""
        result = library.generate_from_template(
            'legal',
            obligations=['pay $100', 'deliver goods']
        )
        
        # Should create 2 Obligation entities
        obligations = [e for e in result['entities'] if e['type'] == 'Obligation']
        assert len(obligations) == 2
        assert obligations[0]['text'] == 'pay $100'
    
    def test_generates_with_mixed_parameters(self, library):
        """generate_from_template handles multiple parameters."""
        result = library.generate_from_template(
            'legal',
            parties=['Alice', 'Bob'],
            obligations=['pay']
        )
        
        # Should create 2 parties + 1 obligation = 3 entities
        assert len(result['entities']) == 3
    
    def test_generated_ontology_has_metadata(self, library):
        """generate_from_template includes metadata."""
        result = library.generate_from_template('legal', parties=['Alice'])
        
        assert result['metadata']['generated_from_template'] is True
        assert result['metadata']['template_domain'] == 'legal'
        assert 'parameters' in result['metadata']
    
    def test_generated_entities_have_ids(self, library):
        """generate_from_template assigns entity IDs."""
        result = library.generate_from_template('legal', parties=['Alice', 'Bob'])
        
        # Check all entities have IDs
        for entity in result['entities']:
            assert 'id' in entity
            assert entity['id'].startswith('entity_')
    
    def test_generated_entities_have_confidence(self, library):
        """generate_from_template assigns confidence scores."""
        result = library.generate_from_template('legal', parties=['Alice'])
        
        for entity in result['entities']:
            assert 'confidence' in entity
            assert entity['confidence'] == 1.0


# ============================================================================
# Template Addition Tests
# ============================================================================

class TestAddTemplate:
    """Test add_template() method."""
    
    def test_add_custom_template(self, library, simple_template):
        """add_template adds custom template to library."""
        library.add_template(simple_template)
        
        domains = library.list_domains()
        assert 'test' in domains
    
    def test_retrieve_added_template(self, library, simple_template):
        """Can retrieve added template via get_template."""
        library.add_template(simple_template)
        
        retrieved = library.get_template('test')
        
        assert retrieved.domain == 'test'
        assert retrieved.description == 'Test template'
    
    def test_add_overwrites_existing(self, library, simple_template):
        """add_template overwrites existing domain."""
        # Get original legal template
        original = library.get_template('legal')
        original_entity_count = len(original.entity_types)
        
        # Overwrite with custom template
        custom = OntologyTemplate(
            domain='legal',
            description='Custom legal',
            entity_types=['Contract'],
            relationship_types=['signs']
        )
        library.add_template(custom)
        
        # Retrieved template should be the custom one
        retrieved = library.get_template('legal')
        assert len(retrieved.entity_types) == 1
        assert 'Contract' in retrieved.entity_types


# ============================================================================
# Domain Listing Tests
# ============================================================================

class TestListDomains:
    """Test list_domains() method."""
    
    def test_returns_list(self, library):
        """list_domains returns list."""
        result = library.list_domains()
        
        assert isinstance(result, list)
    
    def test_includes_default_domains(self, library):
        """list_domains includes all default domains."""
        domains = library.list_domains()
        
        assert 'legal' in domains
        assert 'medical' in domains
        assert 'scientific' in domains
        assert 'general' in domains
    
    def test_includes_added_template(self, library, simple_template):
        """list_domains includes newly added templates."""
        initial_count = len(library.list_domains())
        
        library.add_template(simple_template)
        
        domains = library.list_domains()
        assert len(domains) == initial_count + 1
        assert 'test' in domains


# ============================================================================
# Template Merging Tests
# ============================================================================

class TestMergeTemplates:
    """Test merge_templates() method."""
    
    def test_merge_returns_ontology_template(self, library):
        """merge_templates returns OntologyTemplate."""
        result = library.merge_templates('legal', 'medical', 'legal_medical')
        
        assert isinstance(result, OntologyTemplate)
        assert result.domain == 'legal_medical'
    
    def test_merged_entity_types(self, library):
        """merge_templates combines entity types."""
        result = library.merge_templates('legal', 'medical', 'legal_medical')
        
        # Should have entity types from both
        entity_types = result.entity_types
        assert 'Party' in entity_types  # from legal
        assert 'Patient' in entity_types  # from medical
    
    def test_merged_relationship_types(self, library):
        """merge_templates combines relationship types."""
        result = library.merge_templates('legal', 'medical', 'legal_medical')
        
        # Should have relationship types from both
        rel_types = result.relationship_types
        assert 'obligates' in rel_types  # from legal
        assert 'diagnosed_with' in rel_types  # from medical
    
    def test_merged_removes_duplicates(self, library):
        """merge_templates removes duplicate types."""
        # Add templates with overlapping types
        template1 = OntologyTemplate(
            domain='test1',
            description='Test 1',
            entity_types=['Person', 'Organization'],
            relationship_types=['works_for']
        )
        template2 = OntologyTemplate(
            domain='test2',
            description='Test 2',
            entity_types=['Person', 'Product'],
            relationship_types=['works_for']
        )
        
        library.add_template(template1)
        library.add_template(template2)
        
        result = library.merge_templates('test1', 'test2', 'merged')
        
        # 'Person' and 'works_for' should appear only once
        entity_count = result.entity_types.count('Person')
        rel_count = result.relationship_types.count('works_for')
        
        assert entity_count == 1
        assert rel_count == 1
    
    def test_merged_metadata(self, library):
        """merge_templates includes merge metadata."""
        result = library.merge_templates('legal', 'medical', 'hybrid')
        
        assert 'merged_from' in result.metadata
        assert result.metadata['merged_from'] == ['legal', 'medical']
    
    def test_merged_can_be_added_to_library(self, library):
        """Merged template can be added back to library."""
        merged = library.merge_templates('legal', 'medical', 'legal_medical')
        library.add_template(merged)
        
        domains = library.list_domains()
        assert 'legal_medical' in domains
        
        # Can retrieve it
        retrieved = library.get_template('legal_medical')
        assert retrieved.domain == 'legal_medical'


# ============================================================================
# Integration Tests
# ============================================================================

class TestOntologyTemplateIntegration:
    """Integration tests for complete workflows."""
    
    def test_create_custom_and_generate(self, library):
        """Create custom template and generate ontology from it."""
        # Create custom template
        custom = OntologyTemplate(
            domain='finance',
            description='Financial ontology',
            entity_types=['Account', 'Transaction', 'Customer'],
            relationship_types=['transfers_to', 'owns'],
        )
        library.add_template(custom)
        
        # Generate ontology (even without special parameters)
        ontology = library.generate_from_template('finance')
        
        assert ontology['domain'] == 'finance'
        assert ontology['metadata']['generated_from_template'] is True
    
    def test_merge_and_validate(self, library):
        """Merge templates and validate generated ontology."""
        # Merge legal and medical
        merged = library.merge_templates('legal', 'medical', 'legal_medical')
        library.add_template(merged)
        
        # Generate ontology with mixed parameters
        ontology = library.generate_from_template(
            'legal_medical',
            parties=['Dr. Smith', 'Hospital Inc.'],
        )
        
        # Validate against merged template
        result = merged.validate_ontology(ontology)
        
        assert result is True
    
    def test_full_workflow(self, library):
        """Complete workflow: list, get, generate, validate."""
        # List domains
        domains = library.list_domains()
        assert 'legal' in domains
        
        # Get template
        template = library.get_template('legal')
        assert 'Party' in template.entity_types
        
        # Generate ontology
        ontology = library.generate_from_template(
            'legal',
            parties=['Alice', 'Bob'],
            obligations=['pay $100']
        )
        assert len(ontology['entities']) == 3
        
        # Validate
        is_valid = template.validate_ontology(ontology)
        assert is_valid is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
