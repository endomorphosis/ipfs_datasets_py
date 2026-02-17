"""
Decision Tree Generator

Generates decision trees from complaint type definitions to guide
question generation during the denoising phase.
"""

import logging
import json
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field, asdict
from pathlib import Path
from .keywords import get_type_specific_keywords
from .complaint_types import get_registered_types

logger = logging.getLogger(__name__)


@dataclass
class QuestionNode:
    """A node in the decision tree representing a question."""
    id: str
    question: str
    field_name: str
    required: bool = True
    depends_on: List[str] = field(default_factory=list)
    follow_ups: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class DecisionTree:
    """Decision tree for a complaint type."""
    complaint_type: str
    category: str
    description: str
    root_questions: List[str]  # IDs of root questions
    questions: Dict[str, QuestionNode]  # ID -> QuestionNode
    required_fields: Set[str]
    optional_fields: Set[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'complaint_type': self.complaint_type,
            'category': self.category,
            'description': self.description,
            'root_questions': self.root_questions,
            'questions': {qid: q.to_dict() for qid, q in self.questions.items()},
            'required_fields': list(self.required_fields),
            'optional_fields': list(self.optional_fields)
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DecisionTree':
        """Create from dictionary."""
        questions = {
            qid: QuestionNode(**q) 
            for qid, q in data['questions'].items()
        }
        return cls(
            complaint_type=data['complaint_type'],
            category=data['category'],
            description=data['description'],
            root_questions=data['root_questions'],
            questions=questions,
            required_fields=set(data['required_fields']),
            optional_fields=set(data['optional_fields'])
        )
    
    def get_next_questions(self, answered_fields: Set[str]) -> List[QuestionNode]:
        """
        Get next questions to ask based on what's been answered.
        
        Args:
            answered_fields: Set of field names that have been answered
            
        Returns:
            List of question nodes that should be asked next
        """
        candidates = []
        
        for qid, question in self.questions.items():
            # Skip if already answered
            if question.field_name in answered_fields:
                continue
            
            # Check dependencies
            if question.depends_on:
                if not all(dep in answered_fields for dep in question.depends_on):
                    continue
            
            candidates.append(question)
        
        # Prioritize required questions
        required = [q for q in candidates if q.required]
        if required:
            return required
        
        return candidates


class DecisionTreeGenerator:
    """
    Generates decision trees from complaint type definitions.
    
    Decision trees guide the mediator in asking questions during
    the denoising phase by providing a structured sequence of
    questions based on the complaint type.
    """
    
    def __init__(self, output_dir: Optional[str] = None):
        """
        Initialize the decision tree generator.
        
        Args:
            output_dir: Optional directory to save generated trees
        """
        self.trees: Dict[str, DecisionTree] = {}
        self.output_dir = output_dir
        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    def generate_all_trees(self):
        """Generate decision trees for all registered complaint types."""
        registered_types = get_registered_types()
        
        for complaint_type in registered_types:
            logger.info(f"Generating decision tree for: {complaint_type}")
            tree = self.generate_tree(complaint_type)
            self.trees[complaint_type] = tree
            
            # Save to file if output directory specified
            if self.output_dir:
                self.save_tree(tree, complaint_type)
    
    def generate_tree(self, complaint_type: str) -> DecisionTree:
        """
        Generate a decision tree for a specific complaint type.
        
        Args:
            complaint_type: The complaint type
            
        Returns:
            Generated decision tree
        """
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
        
        # Get keywords for context
        keywords = get_type_specific_keywords('complaint', complaint_type)
        
        # Generate type-specific tree
        if complaint_type == 'housing':
            return self._generate_housing_tree(keywords)
        elif complaint_type == 'employment':
            return self._generate_employment_tree(keywords)
        elif complaint_type == 'civil_rights':
            return self._generate_civil_rights_tree(keywords)
        elif complaint_type == 'consumer':
            return self._generate_consumer_tree(keywords)
        elif complaint_type == 'healthcare':
            return self._generate_healthcare_tree(keywords)
        elif complaint_type == 'free_speech':
            return self._generate_free_speech_tree(keywords)
        elif complaint_type == 'immigration':
            return self._generate_immigration_tree(keywords)
        elif complaint_type == 'family_law':
            return self._generate_family_law_tree(keywords)
        elif complaint_type == 'criminal_defense':
            return self._generate_criminal_defense_tree(keywords)
        elif complaint_type == 'tax_law':
            return self._generate_tax_law_tree(keywords)
        elif complaint_type == 'intellectual_property':
            return self._generate_ip_tree(keywords)
        elif complaint_type == 'environmental_law':
            return self._generate_environmental_tree(keywords)
        else:
            return self._generate_generic_tree(complaint_type, category, keywords)
    
    def _generate_housing_tree(self, keywords: List[str]) -> DecisionTree:
        """Generate decision tree for housing complaints."""
        questions = {
            'q1': QuestionNode(
                id='q1',
                question='Who is the landlord or property owner?',
                field_name='landlord_name',
                required=True,
                keywords=['landlord', 'owner', 'property manager']
            ),
            'q2': QuestionNode(
                id='q2',
                question='What is the address of the property?',
                field_name='property_address',
                required=True,
                keywords=['address', 'property', 'location']
            ),
            'q3': QuestionNode(
                id='q3',
                question='What type of issue are you experiencing?',
                field_name='issue_type',
                required=True,
                keywords=['discrimination', 'eviction', 'harassment', 'repair']
            ),
            'q4': QuestionNode(
                id='q4',
                question='Can you describe the specific incident or action that occurred?',
                field_name='incident_description',
                required=True,
                depends_on=['issue_type'],
                keywords=keywords
            ),
            'q5': QuestionNode(
                id='q5',
                question='When did this incident occur?',
                field_name='date_of_incident',
                required=True,
                depends_on=['incident_description']
            ),
            'q6': QuestionNode(
                id='q6',
                question='Were there any witnesses to this incident?',
                field_name='witnesses',
                required=False,
                depends_on=['incident_description']
            ),
            'q7': QuestionNode(
                id='q7',
                question='Have you filed any prior complaints about this issue?',
                field_name='prior_complaints',
                required=False,
                depends_on=['incident_description']
            ),
            'q8': QuestionNode(
                id='q8',
                question='If this involves discrimination, what protected class are you a member of?',
                field_name='protected_class',
                required=False,
                depends_on=['issue_type'],
                keywords=['race', 'gender', 'disability', 'religion']
            )
        }
        
        return DecisionTree(
            complaint_type='housing',
            category='housing',
            description='Decision tree for housing complaints',
            root_questions=['q1', 'q2', 'q3'],
            questions=questions,
            required_fields={'landlord_name', 'property_address', 'issue_type', 'incident_description', 'date_of_incident'},
            optional_fields={'witnesses', 'prior_complaints', 'protected_class'}
        )
    
    def _generate_employment_tree(self, keywords: List[str]) -> DecisionTree:
        """Generate decision tree for employment complaints."""
        questions = {
            'q1': QuestionNode(
                id='q1',
                question='What is the name of your employer?',
                field_name='employer_name',
                required=True
            ),
            'q2': QuestionNode(
                id='q2',
                question='What was/is your position or job title?',
                field_name='position',
                required=True
            ),
            'q3': QuestionNode(
                id='q3',
                question='What type of employment issue are you experiencing?',
                field_name='issue_type',
                required=True,
                keywords=['discrimination', 'termination', 'harassment', 'wage']
            ),
            'q4': QuestionNode(
                id='q4',
                question='Can you describe what happened in detail?',
                field_name='incident_description',
                required=True,
                depends_on=['issue_type']
            ),
            'q5': QuestionNode(
                id='q5',
                question='When did this occur?',
                field_name='date_of_incident',
                required=True,
                depends_on=['incident_description']
            ),
            'q6': QuestionNode(
                id='q6',
                question='Did you report this to HR or management?',
                field_name='hr_complaints',
                required=False,
                depends_on=['incident_description']
            ),
            'q7': QuestionNode(
                id='q7',
                question='Were there any witnesses?',
                field_name='witnesses',
                required=False,
                depends_on=['incident_description']
            ),
            'q8': QuestionNode(
                id='q8',
                question='If this involves discrimination, what protected class are you a member of?',
                field_name='protected_class',
                required=False,
                depends_on=['issue_type'],
                keywords=['race', 'age', 'gender', 'disability', 'religion']
            ),
            'q9': QuestionNode(
                id='q9',
                question='How long were you employed there?',
                field_name='years_employed',
                required=False,
                depends_on=['employer_name']
            )
        }
        
        return DecisionTree(
            complaint_type='employment',
            category='employment',
            description='Decision tree for employment complaints',
            root_questions=['q1', 'q2', 'q3'],
            questions=questions,
            required_fields={'employer_name', 'position', 'issue_type', 'incident_description', 'date_of_incident'},
            optional_fields={'hr_complaints', 'witnesses', 'protected_class', 'years_employed'}
        )
    
    def _generate_civil_rights_tree(self, keywords: List[str]) -> DecisionTree:
        """Generate decision tree for civil rights complaints."""
        questions = {
            'q1': QuestionNode(
                id='q1',
                question='Who violated your civil rights?',
                field_name='violating_party',
                required=True,
                keywords=['police', 'government', 'official', 'agency']
            ),
            'q2': QuestionNode(
                id='q2',
                question='What right was violated?',
                field_name='protected_right',
                required=True,
                keywords=['speech', 'assembly', 'religion', 'privacy', 'due process']
            ),
            'q3': QuestionNode(
                id='q3',
                question='What type of violation occurred?',
                field_name='violation_type',
                required=True,
                depends_on=['protected_right']
            ),
            'q4': QuestionNode(
                id='q4',
                question='Please describe the incident in detail.',
                field_name='incident_description',
                required=True,
                depends_on=['violation_type']
            ),
            'q5': QuestionNode(
                id='q5',
                question='When did this occur?',
                field_name='date_of_incident',
                required=True,
                depends_on=['incident_description']
            ),
            'q6': QuestionNode(
                id='q6',
                question='What damages did you suffer?',
                field_name='damages',
                required=False,
                depends_on=['incident_description']
            )
        }
        
        return DecisionTree(
            complaint_type='civil_rights',
            category='civil_rights',
            description='Decision tree for civil rights complaints',
            root_questions=['q1', 'q2', 'q3'],
            questions=questions,
            required_fields={'violating_party', 'protected_right', 'violation_type', 'incident_description', 'date_of_incident'},
            optional_fields={'damages'}
        )
    
    def _generate_consumer_tree(self, keywords: List[str]) -> DecisionTree:
        """Generate decision tree for consumer complaints."""
        questions = {
            'q1': QuestionNode(
                id='q1',
                question='What is the name of the business?',
                field_name='business_name',
                required=True
            ),
            'q2': QuestionNode(
                id='q2',
                question='What product or service did you purchase?',
                field_name='product_or_service',
                required=True
            ),
            'q3': QuestionNode(
                id='q3',
                question='What type of problem occurred?',
                field_name='fraud_type',
                required=True,
                keywords=['fraud', 'misrepresentation', 'defective', 'breach']
            ),
            'q4': QuestionNode(
                id='q4',
                question='Please describe the issue in detail.',
                field_name='issue_description',
                required=True,
                depends_on=['fraud_type']
            ),
            'q5': QuestionNode(
                id='q5',
                question='When did you make the purchase?',
                field_name='date_of_purchase',
                required=True
            ),
            'q6': QuestionNode(
                id='q6',
                question='How much money did you lose?',
                field_name='amount_lost',
                required=False,
                depends_on=['issue_description']
            ),
            'q7': QuestionNode(
                id='q7',
                question='Have you tried to resolve this with the business?',
                field_name='attempts_to_resolve',
                required=False,
                depends_on=['issue_description']
            )
        }
        
        return DecisionTree(
            complaint_type='consumer',
            category='consumer',
            description='Decision tree for consumer complaints',
            root_questions=['q1', 'q2', 'q3'],
            questions=questions,
            required_fields={'business_name', 'product_or_service', 'fraud_type', 'issue_description', 'date_of_purchase'},
            optional_fields={'amount_lost', 'attempts_to_resolve'}
        )
    
    def _generate_healthcare_tree(self, keywords: List[str]) -> DecisionTree:
        """Generate decision tree for healthcare complaints."""
        questions = {
            'q1': QuestionNode(
                id='q1',
                question='Who was the healthcare provider?',
                field_name='healthcare_provider',
                required=True
            ),
            'q2': QuestionNode(
                id='q2',
                question='What facility did this occur at?',
                field_name='facility_name',
                required=False
            ),
            'q3': QuestionNode(
                id='q3',
                question='What type of negligence or malpractice occurred?',
                field_name='type_of_negligence',
                required=True,
                keywords=['misdiagnosis', 'surgical error', 'medication error']
            ),
            'q4': QuestionNode(
                id='q4',
                question='Please describe what happened.',
                field_name='incident_description',
                required=True,
                depends_on=['type_of_negligence']
            ),
            'q5': QuestionNode(
                id='q5',
                question='When did this occur?',
                field_name='date_of_incident',
                required=True
            ),
            'q6': QuestionNode(
                id='q6',
                question='What injuries or harm resulted?',
                field_name='injuries_sustained',
                required=False,
                depends_on=['incident_description']
            )
        }
        
        return DecisionTree(
            complaint_type='healthcare',
            category='healthcare',
            description='Decision tree for healthcare complaints',
            root_questions=['q1', 'q3'],
            questions=questions,
            required_fields={'healthcare_provider', 'type_of_negligence', 'incident_description', 'date_of_incident'},
            optional_fields={'facility_name', 'injuries_sustained'}
        )
    
    def _generate_free_speech_tree(self, keywords: List[str]) -> DecisionTree:
        """Generate decision tree for free speech complaints."""
        questions = {
            'q1': QuestionNode(
                id='q1',
                question='Who censored or suppressed your speech?',
                field_name='censoring_party',
                required=True,
                keywords=['platform', 'government', 'school', 'employer']
            ),
            'q2': QuestionNode(
                id='q2',
                question='What platform or venue was involved?',
                field_name='platform_or_venue',
                required=False
            ),
            'q3': QuestionNode(
                id='q3',
                question='What content was censored?',
                field_name='content_censored',
                required=True
            ),
            'q4': QuestionNode(
                id='q4',
                question='When did the censorship occur?',
                field_name='date_of_censorship',
                required=True
            ),
            'q5': QuestionNode(
                id='q5',
                question='What reason was given for the censorship, if any?',
                field_name='reason_given',
                required=False,
                depends_on=['date_of_censorship']
            )
        }
        
        return DecisionTree(
            complaint_type='free_speech',
            category='civil_rights',
            description='Decision tree for free speech complaints',
            root_questions=['q1', 'q3'],
            questions=questions,
            required_fields={'censoring_party', 'content_censored', 'date_of_censorship'},
            optional_fields={'platform_or_venue', 'reason_given'}
        )
    
    def _generate_immigration_tree(self, keywords: List[str]) -> DecisionTree:
        """Generate decision tree for immigration complaints."""
        questions = {
            'q1': QuestionNode(
                id='q1',
                question='Which government agency is involved?',
                field_name='government_agency',
                required=True,
                keywords=['uscis', 'ice', 'cbp', 'immigration']
            ),
            'q2': QuestionNode(
                id='q2',
                question='What type of violation occurred?',
                field_name='violation_type',
                required=True
            ),
            'q3': QuestionNode(
                id='q3',
                question='What is your current immigration status?',
                field_name='immigration_status',
                required=False
            ),
            'q4': QuestionNode(
                id='q4',
                question='When did this occur?',
                field_name='date_of_incident',
                required=True
            ),
            'q5': QuestionNode(
                id='q5',
                question='What relief or remedy are you seeking?',
                field_name='relief_sought',
                required=False
            )
        }
        
        return DecisionTree(
            complaint_type='immigration',
            category='immigration',
            description='Decision tree for immigration complaints',
            root_questions=['q1', 'q2'],
            questions=questions,
            required_fields={'government_agency', 'violation_type', 'date_of_incident'},
            optional_fields={'immigration_status', 'relief_sought'}
        )
    
    def _generate_family_law_tree(self, keywords: List[str]) -> DecisionTree:
        """Generate decision tree for family law complaints."""
        questions = {
            'q1': QuestionNode(
                id='q1',
                question='Who is the other party involved?',
                field_name='other_party',
                required=True
            ),
            'q2': QuestionNode(
                id='q2',
                question='What is the nature of the issue?',
                field_name='issue_description',
                required=True,
                keywords=['custody', 'support', 'visitation', 'divorce']
            ),
            'q3': QuestionNode(
                id='q3',
                question='If children are involved, please list their names and ages.',
                field_name='children',
                required=False,
                depends_on=['issue_description']
            ),
            'q4': QuestionNode(
                id='q4',
                question='What is the current custody or support arrangement?',
                field_name='custody_arrangement',
                required=False,
                depends_on=['children']
            ),
            'q5': QuestionNode(
                id='q5',
                question='Are there any prior court orders in this matter?',
                field_name='prior_orders',
                required=False
            )
        }
        
        return DecisionTree(
            complaint_type='family_law',
            category='family_law',
            description='Decision tree for family law complaints',
            root_questions=['q1', 'q2'],
            questions=questions,
            required_fields={'other_party', 'issue_description'},
            optional_fields={'children', 'custody_arrangement', 'prior_orders'}
        )
    
    def _generate_criminal_defense_tree(self, keywords: List[str]) -> DecisionTree:
        """Generate decision tree for criminal defense complaints."""
        questions = {
            'q1': QuestionNode(
                id='q1',
                question='Which law enforcement agency was involved?',
                field_name='law_enforcement_agency',
                required=True
            ),
            'q2': QuestionNode(
                id='q2',
                question='What type of rights violation occurred?',
                field_name='violation_type',
                required=True,
                keywords=['search', 'seizure', 'miranda', 'counsel']
            ),
            'q3': QuestionNode(
                id='q3',
                question='When were you arrested?',
                field_name='date_of_arrest',
                required=False
            ),
            'q4': QuestionNode(
                id='q4',
                question='What charges were filed?',
                field_name='charges',
                required=False
            ),
            'q5': QuestionNode(
                id='q5',
                question='Are there any issues with evidence?',
                field_name='evidence_issues',
                required=False,
                depends_on=['violation_type']
            )
        }
        
        return DecisionTree(
            complaint_type='criminal_defense',
            category='criminal',
            description='Decision tree for criminal defense complaints',
            root_questions=['q1', 'q2'],
            questions=questions,
            required_fields={'law_enforcement_agency', 'violation_type'},
            optional_fields={'date_of_arrest', 'charges', 'evidence_issues'}
        )
    
    def _generate_tax_law_tree(self, keywords: List[str]) -> DecisionTree:
        """Generate decision tree for tax law complaints."""
        questions = {
            'q1': QuestionNode(
                id='q1',
                question='Which tax authority is involved?',
                field_name='tax_authority',
                required=True,
                keywords=['irs', 'state', 'local']
            ),
            'q2': QuestionNode(
                id='q2',
                question='What type of dispute is this?',
                field_name='dispute_type',
                required=True,
                keywords=['assessment', 'collection', 'refund', 'audit']
            ),
            'q3': QuestionNode(
                id='q3',
                question='What tax year is involved?',
                field_name='tax_year',
                required=False
            ),
            'q4': QuestionNode(
                id='q4',
                question='What is the amount in dispute?',
                field_name='amount_in_dispute',
                required=False
            ),
            'q5': QuestionNode(
                id='q5',
                question='Have you filed any prior appeals?',
                field_name='prior_appeals',
                required=False
            )
        }
        
        return DecisionTree(
            complaint_type='tax_law',
            category='tax',
            description='Decision tree for tax law complaints',
            root_questions=['q1', 'q2'],
            questions=questions,
            required_fields={'tax_authority', 'dispute_type'},
            optional_fields={'tax_year', 'amount_in_dispute', 'prior_appeals'}
        )
    
    def _generate_ip_tree(self, keywords: List[str]) -> DecisionTree:
        """Generate decision tree for intellectual property complaints."""
        questions = {
            'q1': QuestionNode(
                id='q1',
                question='Who is infringing on your intellectual property?',
                field_name='infringing_party',
                required=True
            ),
            'q2': QuestionNode(
                id='q2',
                question='What type of IP is involved?',
                field_name='ip_type',
                required=True,
                keywords=['patent', 'trademark', 'copyright', 'trade secret']
            ),
            'q3': QuestionNode(
                id='q3',
                question='What is the registration number, if applicable?',
                field_name='registration_number',
                required=False,
                depends_on=['ip_type']
            ),
            'q4': QuestionNode(
                id='q4',
                question='When did you discover the infringement?',
                field_name='date_of_infringement',
                required=True
            ),
            'q5': QuestionNode(
                id='q5',
                question='What are your estimated damages?',
                field_name='damages_estimate',
                required=False
            )
        }
        
        return DecisionTree(
            complaint_type='intellectual_property',
            category='intellectual_property',
            description='Decision tree for intellectual property complaints',
            root_questions=['q1', 'q2'],
            questions=questions,
            required_fields={'infringing_party', 'ip_type', 'date_of_infringement'},
            optional_fields={'registration_number', 'damages_estimate'}
        )
    
    def _generate_environmental_tree(self, keywords: List[str]) -> DecisionTree:
        """Generate decision tree for environmental law complaints."""
        questions = {
            'q1': QuestionNode(
                id='q1',
                question='Who is violating environmental law?',
                field_name='violating_party',
                required=True
            ),
            'q2': QuestionNode(
                id='q2',
                question='What type of violation is occurring?',
                field_name='violation_type',
                required=True,
                keywords=['pollution', 'contamination', 'hazardous waste']
            ),
            'q3': QuestionNode(
                id='q3',
                question='Where is the violation occurring?',
                field_name='location',
                required=False
            ),
            'q4': QuestionNode(
                id='q4',
                question='When did you discover the violation?',
                field_name='date_discovered',
                required=True
            ),
            'q5': QuestionNode(
                id='q5',
                question='What is the environmental impact?',
                field_name='environmental_impact',
                required=False,
                depends_on=['violation_type']
            )
        }
        
        return DecisionTree(
            complaint_type='environmental_law',
            category='environmental',
            description='Decision tree for environmental law complaints',
            root_questions=['q1', 'q2'],
            questions=questions,
            required_fields={'violating_party', 'violation_type', 'date_discovered'},
            optional_fields={'location', 'environmental_impact'}
        )
    
    def _generate_generic_tree(self, complaint_type: str, category: str, keywords: List[str]) -> DecisionTree:
        """Generate a generic decision tree."""
        questions = {
            'q1': QuestionNode(
                id='q1',
                question='Who is the other party involved?',
                field_name='party_name',
                required=True
            ),
            'q2': QuestionNode(
                id='q2',
                question='Please describe the issue.',
                field_name='issue_description',
                required=True
            ),
            'q3': QuestionNode(
                id='q3',
                question='When did this occur?',
                field_name='date_of_incident',
                required=True
            ),
            'q4': QuestionNode(
                id='q4',
                question='What damages did you suffer?',
                field_name='damages',
                required=False
            )
        }
        
        return DecisionTree(
            complaint_type=complaint_type,
            category=category,
            description=f'Generic decision tree for {complaint_type} complaints',
            root_questions=['q1', 'q2'],
            questions=questions,
            required_fields={'party_name', 'issue_description', 'date_of_incident'},
            optional_fields={'damages'}
        )
    
    def save_tree(self, tree: DecisionTree, complaint_type: str):
        """
        Save a decision tree to a JSON file.
        
        Args:
            tree: The decision tree to save
            complaint_type: The complaint type
        """
        if not self.output_dir:
            raise ValueError("No output directory specified")
        
        output_path = Path(self.output_dir) / f"{complaint_type}_tree.json"
        with open(output_path, 'w') as f:
            json.dump(tree.to_dict(), f, indent=2)
        
        logger.info(f"Saved decision tree to: {output_path}")
    
    def load_tree(self, complaint_type: str) -> DecisionTree:
        """
        Load a decision tree from a JSON file.
        
        Args:
            complaint_type: The complaint type
            
        Returns:
            Loaded decision tree
        """
        if not self.output_dir:
            raise ValueError("No output directory specified")
        
        input_path = Path(self.output_dir) / f"{complaint_type}_tree.json"
        with open(input_path, 'r') as f:
            data = json.load(f)
        
        return DecisionTree.from_dict(data)
    
    def get_tree(self, complaint_type: str) -> Optional[DecisionTree]:
        """Get a decision tree by complaint type."""
        return self.trees.get(complaint_type)
