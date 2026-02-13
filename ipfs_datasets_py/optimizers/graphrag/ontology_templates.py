"""
Ontology Templates for Domain-Specific Generation.

This module provides seed ontology templates for different domains, enabling
bootstrapped ontology generation with domain-specific entity types, relationship
types, and structural patterns.

Key Features:
    - Domain-specific ontology templates
    - Entity and relationship type libraries
    - Template instantiation from parameters
    - Template merging and extension
    - Example ontologies for each domain

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag import (
    ...     OntologyTemplateLibrary,
    ...     OntologyTemplate
    ... )
    >>> 
    >>> library = OntologyTemplateLibrary()
    >>> template = library.get_template('legal')
    >>> 
    >>> ontology = library.generate_from_template(
    ...     'legal',
    ...     parties=['Alice', 'Bob'],
    ...     obligations=['pay $100']
    ... )

References:
    - complaint-generator seed_complaints.py: Template patterns
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class OntologyTemplate:
    """
    Template for domain-specific ontology generation.
    
    Defines the structure and common patterns for a particular domain,
    including entity types, relationship types, and required/optional
    properties.
    
    Attributes:
        domain: Domain name (e.g., 'legal', 'medical', 'scientific')
        description: Human-readable description of the template
        entity_types: List of common entity types in this domain
        relationship_types: List of common relationship types
        required_properties: Properties required for each entity type
        optional_properties: Optional properties for each entity type
        examples: Example ontologies following this template
        metadata: Additional template metadata
        
    Example:
        >>> template = OntologyTemplate(
        ...     domain='legal',
        ...     description='Legal contract ontology',
        ...     entity_types=['Party', 'Obligation', 'Permission'],
        ...     relationship_types=['obligates', 'permits', 'prohibits']
        ... )
    """
    
    domain: str
    description: str
    entity_types: List[str]
    relationship_types: List[str]
    required_properties: Dict[str, List[str]] = field(default_factory=dict)
    optional_properties: Dict[str, List[str]] = field(default_factory=dict)
    examples: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_entity_types(self) -> Set[str]:
        """Get set of all entity types in template."""
        return set(self.entity_types)
    
    def get_relationship_types(self) -> Set[str]:
        """Get set of all relationship types in template."""
        return set(self.relationship_types)
    
    def validate_ontology(self, ontology: Dict[str, Any]) -> bool:
        """
        Validate that an ontology conforms to this template.
        
        Args:
            ontology: Ontology to validate
            
        Returns:
            True if ontology conforms to template
        """
        # Check that all entities have valid types
        entity_types = self.get_entity_types()
        for entity in ontology.get('entities', []):
            if entity.get('type') not in entity_types:
                logger.warning(
                    f"Entity type '{entity.get('type')}' not in template"
                )
                return False
        
        # Check that all relationships have valid types
        relationship_types = self.get_relationship_types()
        for relationship in ontology.get('relationships', []):
            if relationship.get('type') not in relationship_types:
                logger.warning(
                    f"Relationship type '{relationship.get('type')}' not in template"
                )
                return False
        
        return True


class OntologyTemplateLibrary:
    """
    Repository of domain-specific ontology templates.
    
    Provides access to pre-defined templates for common domains and supports
    generating base ontologies from templates with specific parameters.
    
    Example:
        >>> library = OntologyTemplateLibrary()
        >>> 
        >>> # Get template
        >>> legal_template = library.get_template('legal')
        >>> print(f"Entity types: {legal_template.entity_types}")
        >>> 
        >>> # Generate ontology from template
        >>> ontology = library.generate_from_template(
        ...     'legal',
        ...     parties=['Alice', 'Bob'],
        ...     contract_type='sale'
        ... )
        >>> 
        >>> # List available domains
        >>> domains = library.list_domains()
        >>> print(f"Available: {domains}")
    """
    
    def __init__(self):
        """Initialize the template library with default templates."""
        self._templates: Dict[str, OntologyTemplate] = {}
        self._initialize_default_templates()
        logger.info(f"Initialized OntologyTemplateLibrary with {len(self._templates)} templates")
    
    def _initialize_default_templates(self):
        """Create default templates for common domains."""
        # Legal domain template
        self._templates['legal'] = OntologyTemplate(
            domain='legal',
            description='Legal contract and agreement ontology',
            entity_types=[
                'Party',
                'Person',
                'Organization',
                'Obligation',
                'Permission',
                'Prohibition',
                'Condition',
                'Temporal',
                'Asset',
                'Payment',
            ],
            relationship_types=[
                'obligates',
                'permits',
                'prohibits',
                'owns',
                'pays',
                'receives',
                'transfers',
                'conditions_on',
                'before',
                'after',
                'during',
            ],
            required_properties={
                'Party': ['name', 'role'],
                'Obligation': ['description', 'subject'],
                'Permission': ['description', 'subject'],
                'Temporal': ['type', 'value'],
            },
            optional_properties={
                'Party': ['address', 'contact', 'type'],
                'Obligation': ['deadline', 'penalty'],
                'Permission': ['conditions', 'limitations'],
                'Asset': ['value', 'description'],
            },
            metadata={
                'version': '1.0',
                'use_cases': ['contracts', 'agreements', 'regulations'],
            }
        )
        
        # Medical domain template
        self._templates['medical'] = OntologyTemplate(
            domain='medical',
            description='Clinical and medical ontology',
            entity_types=[
                'Patient',
                'Provider',
                'Diagnosis',
                'Treatment',
                'Medication',
                'Procedure',
                'Symptom',
                'Observation',
                'LabTest',
                'Facility',
            ],
            relationship_types=[
                'diagnosed_with',
                'treated_with',
                'prescribed',
                'performs',
                'exhibits',
                'indicates',
                'contraindicated_for',
                'treats',
                'causes',
                'prevents',
            ],
            required_properties={
                'Patient': ['id', 'demographics'],
                'Diagnosis': ['code', 'description'],
                'Medication': ['name', 'dosage'],
                'Procedure': ['name', 'type'],
            },
            optional_properties={
                'Patient': ['age', 'gender', 'history'],
                'Diagnosis': ['severity', 'onset_date', 'status'],
                'Medication': ['frequency', 'route', 'duration'],
                'Observation': ['value', 'unit', 'timestamp'],
            },
            metadata={
                'version': '1.0',
                'use_cases': ['EHR', 'clinical_notes', 'medical_research'],
                'standards': ['ICD-10', 'SNOMED', 'LOINC'],
            }
        )
        
        # Scientific domain template
        self._templates['scientific'] = OntologyTemplate(
            domain='scientific',
            description='Scientific research and experimentation ontology',
            entity_types=[
                'Researcher',
                'Entity',
                'Process',
                'Measurement',
                'Hypothesis',
                'Experiment',
                'Observation',
                'Material',
                'Method',
                'Result',
            ],
            relationship_types=[
                'investigates',
                'produces',
                'measures',
                'uses',
                'tests',
                'supports',
                'refutes',
                'causes',
                'correlates_with',
                'derives_from',
            ],
            required_properties={
                'Entity': ['name', 'type'],
                'Measurement': ['value', 'unit'],
                'Hypothesis': ['description'],
                'Experiment': ['description', 'method'],
            },
            optional_properties={
                'Entity': ['properties', 'classification'],
                'Measurement': ['uncertainty', 'conditions', 'timestamp'],
                'Hypothesis': ['status', 'evidence'],
                'Experiment': ['results', 'conclusions', 'limitations'],
            },
            metadata={
                'version': '1.0',
                'use_cases': ['research_papers', 'lab_notes', 'experiments'],
            }
        )
        
        # General domain template (fallback)
        self._templates['general'] = OntologyTemplate(
            domain='general',
            description='General-purpose ontology template',
            entity_types=[
                'Entity',
                'Agent',
                'Object',
                'Event',
                'Concept',
                'Attribute',
            ],
            relationship_types=[
                'related_to',
                'part_of',
                'instance_of',
                'has_property',
                'causes',
                'precedes',
                'follows',
            ],
            required_properties={
                'Entity': ['name', 'type'],
            },
            optional_properties={
                'Entity': ['description', 'properties'],
                'Event': ['timestamp', 'location'],
                'Agent': ['role', 'capabilities'],
            },
            metadata={
                'version': '1.0',
                'use_cases': ['general_knowledge', 'unspecified_domain'],
            }
        )
    
    def get_template(self, domain: str) -> OntologyTemplate:
        """
        Get ontology template for a specific domain.
        
        Args:
            domain: Domain name (e.g., 'legal', 'medical', 'scientific')
            
        Returns:
            OntologyTemplate for the domain
            
        Raises:
            KeyError: If domain not found
            
        Example:
            >>> library = OntologyTemplateLibrary()
            >>> template = library.get_template('legal')
            >>> print(f"Entity types: {len(template.entity_types)}")
        """
        if domain not in self._templates:
            logger.warning(f"Domain '{domain}' not found, using general template")
            return self._templates['general']
        
        return self._templates[domain]
    
    def generate_from_template(
        self,
        domain: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate base ontology from template with provided parameters.
        
        Creates a skeletal ontology structure based on the template and
        populated with provided parameters.
        
        Args:
            domain: Domain name
            **kwargs: Parameters for template instantiation
            
        Returns:
            Base ontology dictionary
            
        Example:
            >>> ontology = library.generate_from_template(
            ...     'legal',
            ...     parties=['Alice', 'Bob'],
            ...     obligations=['pay', 'deliver']
            ... )
            >>> print(f"Entities: {len(ontology['entities'])}")
        """
        logger.info(f"Generating ontology from template: {domain}")
        
        template = self.get_template(domain)
        
        # Create base ontology structure
        ontology = {
            'domain': domain,
            'template_version': template.metadata.get('version', '1.0'),
            'entities': [],
            'relationships': [],
            'metadata': {
                'generated_from_template': True,
                'template_domain': domain,
                'parameters': kwargs,
            }
        }
        
        # Generate entities from parameters
        entity_id_counter = 0
        
        # Example: if 'parties' parameter provided
        if 'parties' in kwargs:
            for party in kwargs['parties']:
                entity_id_counter += 1
                ontology['entities'].append({
                    'id': f'entity_{entity_id_counter}',
                    'type': 'Party',
                    'text': party,
                    'properties': {'name': party, 'role': 'party'},
                    'confidence': 1.0,
                })
        
        # Example: if 'obligations' parameter provided
        if 'obligations' in kwargs:
            for obligation in kwargs['obligations']:
                entity_id_counter += 1
                ontology['entities'].append({
                    'id': f'entity_{entity_id_counter}',
                    'type': 'Obligation',
                    'text': obligation,
                    'properties': {'description': obligation},
                    'confidence': 1.0,
                })
        
        logger.info(f"Generated ontology with {len(ontology['entities'])} entities")
        
        return ontology
    
    def add_template(self, template: OntologyTemplate):
        """
        Add a new template to the library.
        
        Args:
            template: OntologyTemplate to add
            
        Example:
            >>> custom_template = OntologyTemplate(
            ...     domain='finance',
            ...     description='Financial ontology',
            ...     entity_types=['Account', 'Transaction'],
            ...     relationship_types=['transfers_to']
            ... )
            >>> library.add_template(custom_template)
        """
        self._templates[template.domain] = template
        logger.info(f"Added template for domain: {template.domain}")
    
    def list_domains(self) -> List[str]:
        """
        List all available domain templates.
        
        Returns:
            List of domain names
            
        Example:
            >>> domains = library.list_domains()
            >>> print(f"Available domains: {', '.join(domains)}")
        """
        return list(self._templates.keys())
    
    def merge_templates(
        self,
        domain1: str,
        domain2: str,
        new_domain: str
    ) -> OntologyTemplate:
        """
        Merge two templates to create a hybrid template.
        
        Combines entity types, relationship types, and properties from
        two existing templates.
        
        Args:
            domain1: First domain to merge
            domain2: Second domain to merge
            new_domain: Name for the merged template
            
        Returns:
            New merged OntologyTemplate
            
        Example:
            >>> merged = library.merge_templates('legal', 'medical', 'legal_medical')
            >>> library.add_template(merged)
        """
        logger.info(f"Merging templates: {domain1} + {domain2} -> {new_domain}")
        
        template1 = self.get_template(domain1)
        template2 = self.get_template(domain2)
        
        # Merge entity types
        entity_types = list(set(template1.entity_types + template2.entity_types))
        
        # Merge relationship types
        relationship_types = list(set(template1.relationship_types + template2.relationship_types))
        
        # Merge properties
        required_properties = {**template1.required_properties, **template2.required_properties}
        optional_properties = {**template1.optional_properties, **template2.optional_properties}
        
        merged_template = OntologyTemplate(
            domain=new_domain,
            description=f"Merged template from {domain1} and {domain2}",
            entity_types=entity_types,
            relationship_types=relationship_types,
            required_properties=required_properties,
            optional_properties=optional_properties,
            metadata={
                'merged_from': [domain1, domain2],
                'version': '1.0',
            }
        )
        
        return merged_template


# Export public API
__all__ = [
    'OntologyTemplate',
    'OntologyTemplateLibrary',
]
