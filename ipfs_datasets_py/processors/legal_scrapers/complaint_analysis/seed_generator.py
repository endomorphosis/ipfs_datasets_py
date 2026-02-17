"""
Seed Generator

Automatically generates seed complaints from complaint_analysis type definitions,
keywords, and legal patterns. This replaces hardcoded seeds with data-driven generation.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from .keywords import get_type_specific_keywords
from .legal_patterns import get_legal_terms
from .complaint_types import get_registered_types

logger = logging.getLogger(__name__)


@dataclass
class SeedComplaintTemplate:
    """Template for generating seed complaints from complaint_analysis data."""
    id: str
    type: str
    category: str
    description: str
    key_facts_template: Dict[str, Any]
    required_fields: List[str]
    optional_fields: List[str]
    keywords: List[str] = field(default_factory=list)
    legal_patterns: List[str] = field(default_factory=list)
    
    def instantiate(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a concrete complaint from this template.
        
        Args:
            values: Values to fill in the template
            
        Returns:
            Instantiated complaint data
        """
        # Check required fields
        missing = [f for f in self.required_fields if f not in values]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")
        
        # Merge template with values
        key_facts = self.key_facts_template.copy()
        key_facts.update(values)
        
        return {
            'template_id': self.id,
            'type': self.type,
            'category': self.category,
            'description': self.description,
            'key_facts': key_facts,
            'keywords': self.keywords,
            'legal_patterns': self.legal_patterns
        }


class SeedGenerator:
    """
    Generates seed complaints from complaint_analysis type definitions.
    
    This class bridges the complaint_analysis module with the adversarial
    testing framework by converting type definitions into seed templates.
    """
    
    def __init__(self):
        """Initialize the seed generator."""
        self.templates: Dict[str, SeedComplaintTemplate] = {}
        self._generate_templates()
    
    def _generate_templates(self):
        """Generate templates from registered complaint types."""
        registered_types = get_registered_types()
        
        for complaint_type in registered_types:
            self._generate_template_for_type(complaint_type)
    
    def _generate_template_for_type(self, complaint_type: str):
        """
        Generate a template for a specific complaint type.
        
        Args:
            complaint_type: The complaint type (e.g., 'housing', 'employment')
        """
        # Get keywords and legal patterns for this type
        keywords = get_type_specific_keywords('complaint', complaint_type)
        legal_terms = get_legal_terms(complaint_type)
        
        # Map complaint type to category
        category_map = {
            'housing': 'housing',
            'employment': 'employment',
            'civil_rights': 'civil_rights',
            'consumer': 'consumer',
            'healthcare': 'healthcare',
            'free_speech': 'civil_rights',
            'immigration': 'immigration',
            'family_law': 'family_law',
            'criminal_defense': 'criminal',
            'tax_law': 'tax',
            'intellectual_property': 'intellectual_property',
            'environmental_law': 'environmental',
            'dei': 'employment'
        }
        
        category = category_map.get(complaint_type, 'general')
        
        # Define type-specific templates
        if complaint_type == 'housing':
            self._create_housing_templates(keywords, legal_terms)
        elif complaint_type == 'employment':
            self._create_employment_templates(keywords, legal_terms)
        elif complaint_type == 'civil_rights':
            self._create_civil_rights_templates(keywords, legal_terms)
        elif complaint_type == 'consumer':
            self._create_consumer_templates(keywords, legal_terms)
        elif complaint_type == 'healthcare':
            self._create_healthcare_templates(keywords, legal_terms)
        elif complaint_type == 'free_speech':
            self._create_free_speech_templates(keywords, legal_terms)
        elif complaint_type == 'immigration':
            self._create_immigration_templates(keywords, legal_terms)
        elif complaint_type == 'family_law':
            self._create_family_law_templates(keywords, legal_terms)
        elif complaint_type == 'criminal_defense':
            self._create_criminal_defense_templates(keywords, legal_terms)
        elif complaint_type == 'tax_law':
            self._create_tax_law_templates(keywords, legal_terms)
        elif complaint_type == 'intellectual_property':
            self._create_ip_templates(keywords, legal_terms)
        elif complaint_type == 'environmental_law':
            self._create_environmental_templates(keywords, legal_terms)
        else:
            # Generic template
            self._create_generic_template(complaint_type, category, keywords, legal_terms)
    
    def _create_housing_templates(self, keywords: List[str], legal_terms: List[str]):
        """Create housing-specific templates."""
        # Discrimination template
        template = SeedComplaintTemplate(
            id='housing_discrimination_1',
            type='housing_discrimination',
            category='housing',
            description='Housing discrimination based on protected class',
            key_facts_template={
                'landlord_name': None,
                'property_address': None,
                'protected_class': None,
                'discriminatory_action': None,
                'date_of_incident': None,
                'witnesses': [],
                'prior_complaints': []
            },
            required_fields=['landlord_name', 'protected_class', 'discriminatory_action'],
            optional_fields=['property_address', 'date_of_incident', 'witnesses', 'prior_complaints'],
            keywords=keywords,
            legal_patterns=legal_terms
        )
        self.templates[template.id] = template
        
        # Eviction template
        template = SeedComplaintTemplate(
            id='housing_eviction_1',
            type='unlawful_eviction',
            category='housing',
            description='Unlawful or retaliatory eviction',
            key_facts_template={
                'landlord_name': None,
                'property_address': None,
                'eviction_reason': None,
                'notice_date': None,
                'lease_terms': None,
                'rent_payment_status': None
            },
            required_fields=['landlord_name', 'eviction_reason'],
            optional_fields=['property_address', 'notice_date', 'lease_terms', 'rent_payment_status'],
            keywords=keywords,
            legal_patterns=legal_terms
        )
        self.templates[template.id] = template
    
    def _create_employment_templates(self, keywords: List[str], legal_terms: List[str]):
        """Create employment-specific templates."""
        # Discrimination template
        template = SeedComplaintTemplate(
            id='employment_discrimination_1',
            type='employment_discrimination',
            category='employment',
            description='Workplace discrimination based on protected class',
            key_facts_template={
                'employer_name': None,
                'position': None,
                'protected_class': None,
                'discriminatory_action': None,
                'date_of_incident': None,
                'witnesses': [],
                'hr_complaints': []
            },
            required_fields=['employer_name', 'position', 'protected_class', 'discriminatory_action'],
            optional_fields=['date_of_incident', 'witnesses', 'hr_complaints'],
            keywords=keywords,
            legal_patterns=legal_terms
        )
        self.templates[template.id] = template
        
        # Wrongful termination template
        template = SeedComplaintTemplate(
            id='employment_termination_1',
            type='wrongful_termination',
            category='employment',
            description='Wrongful termination from employment',
            key_facts_template={
                'employer_name': None,
                'position': None,
                'termination_date': None,
                'termination_reason': None,
                'years_employed': None,
                'performance_reviews': []
            },
            required_fields=['employer_name', 'position', 'termination_date'],
            optional_fields=['termination_reason', 'years_employed', 'performance_reviews'],
            keywords=keywords,
            legal_patterns=legal_terms
        )
        self.templates[template.id] = template
    
    def _create_civil_rights_templates(self, keywords: List[str], legal_terms: List[str]):
        """Create civil rights-specific templates."""
        template = SeedComplaintTemplate(
            id='civil_rights_violation_1',
            type='civil_rights_violation',
            category='civil_rights',
            description='Civil rights violation by government or institution',
            key_facts_template={
                'violating_party': None,
                'type_of_violation': None,
                'protected_right': None,
                'date_of_incident': None,
                'damages': None
            },
            required_fields=['violating_party', 'type_of_violation', 'protected_right'],
            optional_fields=['date_of_incident', 'damages'],
            keywords=keywords,
            legal_patterns=legal_terms
        )
        self.templates[template.id] = template
    
    def _create_consumer_templates(self, keywords: List[str], legal_terms: List[str]):
        """Create consumer-specific templates."""
        template = SeedComplaintTemplate(
            id='consumer_fraud_1',
            type='consumer_fraud',
            category='consumer',
            description='Consumer fraud or deceptive practices',
            key_facts_template={
                'business_name': None,
                'product_or_service': None,
                'fraud_type': None,
                'amount_lost': None,
                'date_of_purchase': None,
                'attempts_to_resolve': []
            },
            required_fields=['business_name', 'product_or_service', 'fraud_type'],
            optional_fields=['amount_lost', 'date_of_purchase', 'attempts_to_resolve'],
            keywords=keywords,
            legal_patterns=legal_terms
        )
        self.templates[template.id] = template
    
    def _create_healthcare_templates(self, keywords: List[str], legal_terms: List[str]):
        """Create healthcare-specific templates."""
        template = SeedComplaintTemplate(
            id='healthcare_malpractice_1',
            type='medical_malpractice',
            category='healthcare',
            description='Medical malpractice or negligence',
            key_facts_template={
                'healthcare_provider': None,
                'facility_name': None,
                'type_of_negligence': None,
                'date_of_incident': None,
                'injuries_sustained': None,
                'medical_records': []
            },
            required_fields=['healthcare_provider', 'type_of_negligence'],
            optional_fields=['facility_name', 'date_of_incident', 'injuries_sustained', 'medical_records'],
            keywords=keywords,
            legal_patterns=legal_terms
        )
        self.templates[template.id] = template
    
    def _create_free_speech_templates(self, keywords: List[str], legal_terms: List[str]):
        """Create free speech-specific templates."""
        template = SeedComplaintTemplate(
            id='free_speech_censorship_1',
            type='censorship',
            category='civil_rights',
            description='Censorship or suppression of speech',
            key_facts_template={
                'censoring_party': None,
                'platform_or_venue': None,
                'content_censored': None,
                'date_of_censorship': None,
                'reason_given': None
            },
            required_fields=['censoring_party', 'content_censored'],
            optional_fields=['platform_or_venue', 'date_of_censorship', 'reason_given'],
            keywords=keywords,
            legal_patterns=legal_terms
        )
        self.templates[template.id] = template
    
    def _create_immigration_templates(self, keywords: List[str], legal_terms: List[str]):
        """Create immigration-specific templates."""
        template = SeedComplaintTemplate(
            id='immigration_violation_1',
            type='immigration_violation',
            category='immigration',
            description='Immigration process violation or discrimination',
            key_facts_template={
                'government_agency': None,
                'violation_type': None,
                'date_of_incident': None,
                'immigration_status': None,
                'relief_sought': None
            },
            required_fields=['government_agency', 'violation_type'],
            optional_fields=['date_of_incident', 'immigration_status', 'relief_sought'],
            keywords=keywords,
            legal_patterns=legal_terms
        )
        self.templates[template.id] = template
    
    def _create_family_law_templates(self, keywords: List[str], legal_terms: List[str]):
        """Create family law-specific templates."""
        template = SeedComplaintTemplate(
            id='family_law_custody_1',
            type='custody_dispute',
            category='family_law',
            description='Child custody or support dispute',
            key_facts_template={
                'other_party': None,
                'children': [],
                'custody_arrangement': None,
                'issue_description': None,
                'prior_orders': []
            },
            required_fields=['other_party', 'issue_description'],
            optional_fields=['children', 'custody_arrangement', 'prior_orders'],
            keywords=keywords,
            legal_patterns=legal_terms
        )
        self.templates[template.id] = template
    
    def _create_criminal_defense_templates(self, keywords: List[str], legal_terms: List[str]):
        """Create criminal defense-specific templates."""
        template = SeedComplaintTemplate(
            id='criminal_defense_violation_1',
            type='rights_violation',
            category='criminal',
            description='Criminal rights violation during arrest or prosecution',
            key_facts_template={
                'law_enforcement_agency': None,
                'violation_type': None,
                'date_of_arrest': None,
                'charges': [],
                'evidence_issues': []
            },
            required_fields=['law_enforcement_agency', 'violation_type'],
            optional_fields=['date_of_arrest', 'charges', 'evidence_issues'],
            keywords=keywords,
            legal_patterns=legal_terms
        )
        self.templates[template.id] = template
    
    def _create_tax_law_templates(self, keywords: List[str], legal_terms: List[str]):
        """Create tax law-specific templates."""
        template = SeedComplaintTemplate(
            id='tax_dispute_1',
            type='tax_dispute',
            category='tax',
            description='Tax assessment or collection dispute',
            key_facts_template={
                'tax_authority': None,
                'tax_year': None,
                'dispute_type': None,
                'amount_in_dispute': None,
                'prior_appeals': []
            },
            required_fields=['tax_authority', 'dispute_type'],
            optional_fields=['tax_year', 'amount_in_dispute', 'prior_appeals'],
            keywords=keywords,
            legal_patterns=legal_terms
        )
        self.templates[template.id] = template
    
    def _create_ip_templates(self, keywords: List[str], legal_terms: List[str]):
        """Create intellectual property-specific templates."""
        template = SeedComplaintTemplate(
            id='ip_infringement_1',
            type='ip_infringement',
            category='intellectual_property',
            description='Intellectual property infringement',
            key_facts_template={
                'infringing_party': None,
                'ip_type': None,
                'registration_number': None,
                'date_of_infringement': None,
                'damages_estimate': None
            },
            required_fields=['infringing_party', 'ip_type'],
            optional_fields=['registration_number', 'date_of_infringement', 'damages_estimate'],
            keywords=keywords,
            legal_patterns=legal_terms
        )
        self.templates[template.id] = template
    
    def _create_environmental_templates(self, keywords: List[str], legal_terms: List[str]):
        """Create environmental law-specific templates."""
        template = SeedComplaintTemplate(
            id='environmental_violation_1',
            type='environmental_violation',
            category='environmental',
            description='Environmental law violation',
            key_facts_template={
                'violating_party': None,
                'violation_type': None,
                'location': None,
                'date_discovered': None,
                'environmental_impact': None
            },
            required_fields=['violating_party', 'violation_type'],
            optional_fields=['location', 'date_discovered', 'environmental_impact'],
            keywords=keywords,
            legal_patterns=legal_terms
        )
        self.templates[template.id] = template
    
    def _create_generic_template(self, complaint_type: str, category: str, 
                                 keywords: List[str], legal_terms: List[str]):
        """Create a generic template for unspecified types."""
        template = SeedComplaintTemplate(
            id=f'{complaint_type}_generic_1',
            type=complaint_type,
            category=category,
            description=f'Generic {complaint_type} complaint',
            key_facts_template={
                'party_name': None,
                'issue_description': None,
                'date_of_incident': None,
                'damages': None
            },
            required_fields=['party_name', 'issue_description'],
            optional_fields=['date_of_incident', 'damages'],
            keywords=keywords,
            legal_patterns=legal_terms
        )
        self.templates[template.id] = template
    
    def get_template(self, template_id: str) -> Optional[SeedComplaintTemplate]:
        """Get a template by ID."""
        return self.templates.get(template_id)
    
    def list_templates(self, category: Optional[str] = None, 
                      complaint_type: Optional[str] = None) -> List[SeedComplaintTemplate]:
        """
        List templates, optionally filtered by category or type.
        
        Args:
            category: Optional category filter
            complaint_type: Optional complaint type filter
            
        Returns:
            List of matching templates
        """
        templates = list(self.templates.values())
        
        if category:
            templates = [t for t in templates if t.category == category]
        
        if complaint_type:
            templates = [t for t in templates if t.type == complaint_type]
        
        return templates
    
    def generate_seed(self, template_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a seed complaint from a template.
        
        Args:
            template_id: ID of template to use
            values: Values to fill in the template
            
        Returns:
            Instantiated seed complaint
        """
        template = self.get_template(template_id)
        if not template:
            raise KeyError(f"Template not found: {template_id}")
        
        return template.instantiate(values)
