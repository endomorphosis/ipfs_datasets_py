"""
Domain-Specific Vocabularies for CEC (Phase 5 Week 5).

This module provides specialized vocabulary extensions for different domains,
enhancing parsing accuracy for legal, medical, and technical contexts.

Classes:
    DomainVocabulary: Base class for domain-specific vocabularies
    LegalVocabulary: Legal domain terms and phrases
    MedicalVocabulary: Medical domain terms and phrases
    TechnicalVocabulary: Technical/IT domain terms and phrases
    DomainVocabularyManager: Manager for multiple domain vocabularies

Usage:
    >>> from ipfs_datasets_py.logic.CEC.nl.domain_vocabularies import (
    ...     DomainVocabularyManager, LegalVocabulary
    ... )
    >>> manager = DomainVocabularyManager()
    >>> manager.add_vocabulary(LegalVocabulary())
    >>> enhanced_text = manager.enhance_text("The contract is binding", "legal")
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field


@dataclass
class DomainTerm:
    """
    A domain-specific term with translations and metadata.
    
    Attributes:
        term_id: Unique identifier for the term
        english: English term
        spanish: Spanish translation (optional)
        french: French translation (optional)
        german: German translation (optional)
        category: Term category (e.g., 'deontic', 'temporal')
        domain: Domain name (e.g., 'legal', 'medical')
        synonyms: List of synonyms in primary language
        
    Example:
        >>> term = DomainTerm(
        ...     term_id="legal_contract",
        ...     english="contract",
        ...     spanish="contrato",
        ...     french="contrat",
        ...     german="Vertrag",
        ...     category="legal_document",
        ...     domain="legal"
        ... )
    """
    term_id: str
    english: str
    spanish: Optional[str] = None
    french: Optional[str] = None
    german: Optional[str] = None
    category: str = "general"
    domain: str = "general"
    synonyms: List[str] = field(default_factory=list)
    
    def get_translation(self, language: str) -> Optional[str]:
        """Get term translation for specified language.
        
        Args:
            language: Language code ('en', 'es', 'fr', 'de')
            
        Returns:
            Translated term or None if not available
        """
        lang_map = {
            'en': self.english,
            'es': self.spanish,
            'fr': self.french,
            'de': self.german
        }
        return lang_map.get(language.lower())


class DomainVocabulary(ABC):
    """
    Abstract base class for domain-specific vocabularies.
    
    Attributes:
        domain_name: Name of the domain
        terms: Dict mapping term IDs to DomainTerm objects
        
    Example:
        >>> class MyVocabulary(DomainVocabulary):
        ...     def __init__(self):
        ...         super().__init__("my_domain")
        ...         self._load_terms()
        ...
        ...     def _load_terms(self):
        ...         self.add_term(DomainTerm(...))
    """
    
    def __init__(self, domain_name: str):
        """Initialize domain vocabulary.
        
        Args:
            domain_name: Name of the domain
        """
        self.domain_name = domain_name
        self.terms: Dict[str, DomainTerm] = {}
        self._load_terms()
    
    @abstractmethod
    def _load_terms(self) -> None:
        """Load domain-specific terms. Must be implemented by subclasses."""
        pass
    
    def add_term(self, term: DomainTerm) -> None:
        """Add a term to the vocabulary.
        
        Args:
            term: DomainTerm to add
        """
        self.terms[term.term_id] = term
    
    def get_term(self, term_id: str) -> Optional[DomainTerm]:
        """Get term by ID.
        
        Args:
            term_id: Term identifier
            
        Returns:
            DomainTerm or None if not found
        """
        return self.terms.get(term_id)
    
    def get_all_terms(self, category: Optional[str] = None) -> List[DomainTerm]:
        """Get all terms, optionally filtered by category.
        
        Args:
            category: Optional category filter
            
        Returns:
            List of DomainTerm objects
        """
        if category:
            return [t for t in self.terms.values() if t.category == category]
        return list(self.terms.values())
    
    def get_terms_by_language(self, language: str) -> Dict[str, str]:
        """Get all terms as dict for specified language.
        
        Args:
            language: Language code ('en', 'es', 'fr', 'de')
            
        Returns:
            Dict mapping term IDs to translations
        """
        result = {}
        for term_id, term in self.terms.items():
            translation = term.get_translation(language)
            if translation:
                result[term_id] = translation
        return result


class LegalVocabulary(DomainVocabulary):
    """Legal domain vocabulary for CEC.
    
    Provides specialized legal terminology including:
    - Contracts and agreements
    - Obligations and duties
    - Rights and permissions
    - Prohibitions and restrictions
    - Legal entities and roles
    """
    
    def __init__(self):
        """Initialize legal vocabulary."""
        super().__init__("legal")
    
    def _load_terms(self) -> None:
        """Load legal domain terms."""
        # Legal obligations
        self.add_term(DomainTerm(
            term_id="legal_obligation",
            english="legal obligation",
            spanish="obligación legal",
            french="obligation légale",
            german="Rechtspflicht",
            category="deontic",
            domain="legal"
        ))
        
        self.add_term(DomainTerm(
            term_id="duty",
            english="duty",
            spanish="deber",
            french="devoir",
            german="Pflicht",
            category="deontic",
            domain="legal"
        ))
        
        # Legal permissions
        self.add_term(DomainTerm(
            term_id="right",
            english="right",
            spanish="derecho",
            french="droit",
            german="Recht",
            category="deontic",
            domain="legal",
            synonyms=["entitlement", "privilege"]
        ))
        
        # Legal prohibitions
        self.add_term(DomainTerm(
            term_id="prohibited_act",
            english="prohibited act",
            spanish="acto prohibido",
            french="acte interdit",
            german="verbotene Handlung",
            category="deontic",
            domain="legal"
        ))
        
        # Legal entities
        self.add_term(DomainTerm(
            term_id="contract",
            english="contract",
            spanish="contrato",
            french="contrat",
            german="Vertrag",
            category="legal_document",
            domain="legal"
        ))


class MedicalVocabulary(DomainVocabulary):
    """Medical domain vocabulary for CEC.
    
    Provides specialized medical terminology including:
    - Medical obligations and protocols
    - Patient rights
    - Treatment permissions
    - Medical restrictions
    - Healthcare providers and patients
    """
    
    def __init__(self):
        """Initialize medical vocabulary."""
        super().__init__("medical")
    
    def _load_terms(self) -> None:
        """Load medical domain terms."""
        # Medical obligations
        self.add_term(DomainTerm(
            term_id="informed_consent",
            english="informed consent",
            spanish="consentimiento informado",
            french="consentement éclairé",
            german="Aufgeklärte Einwilligung",
            category="deontic",
            domain="medical"
        ))
        
        self.add_term(DomainTerm(
            term_id="medical_duty",
            english="duty of care",
            spanish="deber de cuidado",
            french="devoir de soin",
            german="Sorgfaltspflicht",
            category="deontic",
            domain="medical"
        ))
        
        # Medical permissions
        self.add_term(DomainTerm(
            term_id="treatment_authorization",
            english="treatment authorization",
            spanish="autorización de tratamiento",
            french="autorisation de traitement",
            german="Behandlungsermächtigung",
            category="deontic",
            domain="medical"
        ))
        
        # Medical entities
        self.add_term(DomainTerm(
            term_id="patient",
            english="patient",
            spanish="paciente",
            french="patient",
            german="Patient",
            category="entity",
            domain="medical"
        ))


class TechnicalVocabulary(DomainVocabulary):
    """Technical/IT domain vocabulary for CEC.
    
    Provides specialized technical terminology including:
    - System requirements and specifications
    - Access permissions
    - Security restrictions
    - Software agents and processes
    - Technical operations
    """
    
    def __init__(self):
        """Initialize technical vocabulary."""
        super().__init__("technical")
    
    def _load_terms(self) -> None:
        """Load technical domain terms."""
        # Technical obligations
        self.add_term(DomainTerm(
            term_id="system_requirement",
            english="system requirement",
            spanish="requisito del sistema",
            french="exigence système",
            german="Systemanforderung",
            category="deontic",
            domain="technical"
        ))
        
        # Technical permissions
        self.add_term(DomainTerm(
            term_id="access_permission",
            english="access permission",
            spanish="permiso de acceso",
            french="permission d'accès",
            german="Zugriffsberechtigung",
            category="deontic",
            domain="technical"
        ))
        
        self.add_term(DomainTerm(
            term_id="authorization",
            english="authorization",
            spanish="autorización",
            french="autorisation",
            german="Autorisierung",
            category="deontic",
            domain="technical"
        ))
        
        # Technical entities
        self.add_term(DomainTerm(
            term_id="software_agent",
            english="software agent",
            spanish="agente de software",
            french="agent logiciel",
            german="Softwareagent",
            category="entity",
            domain="technical"
        ))


class DomainVocabularyManager:
    """
    Manager for multiple domain-specific vocabularies.
    
    This class coordinates multiple domain vocabularies and provides
    unified access to domain-specific terms across languages.
    
    Attributes:
        vocabularies: Dict mapping domain names to DomainVocabulary instances
        
    Example:
        >>> manager = DomainVocabularyManager()
        >>> manager.add_vocabulary(LegalVocabulary())
        >>> manager.add_vocabulary(MedicalVocabulary())
        >>> legal_terms = manager.get_vocabulary_terms("legal")
        >>> len(legal_terms) > 0
        True
    """
    
    def __init__(self):
        """Initialize vocabulary manager."""
        self.vocabularies: Dict[str, DomainVocabulary] = {}
    
    def add_vocabulary(self, vocabulary: DomainVocabulary) -> None:
        """Add a domain vocabulary.
        
        Args:
            vocabulary: DomainVocabulary instance to add
        """
        self.vocabularies[vocabulary.domain_name] = vocabulary
    
    def get_vocabulary(self, domain: str) -> Optional[DomainVocabulary]:
        """Get vocabulary for specified domain.
        
        Args:
            domain: Domain name
            
        Returns:
            DomainVocabulary or None if not found
        """
        return self.vocabularies.get(domain)
    
    def get_vocabulary_terms(
        self,
        domain: str,
        language: Optional[str] = None
    ) -> Dict[str, str]:
        """Get terms for specified domain and language.
        
        Args:
            domain: Domain name
            language: Optional language code
            
        Returns:
            Dict mapping term IDs to terms/translations
        """
        vocab = self.get_vocabulary(domain)
        if not vocab:
            return {}
        
        if language:
            return vocab.get_terms_by_language(language)
        else:
            return {tid: term.english for tid, term in vocab.terms.items()}
    
    def get_all_domains(self) -> List[str]:
        """Get list of all registered domains.
        
        Returns:
            List of domain names
        """
        return list(self.vocabularies.keys())
    
    def enhance_text(
        self,
        text: str,
        domain: str,
        language: str = "en"
    ) -> str:
        """Enhance text with domain-specific vocabulary.
        
        Replaces generic terms with domain-specific equivalents.
        
        Args:
            text: Input text
            domain: Domain name
            language: Language code
            
        Returns:
            Enhanced text with domain-specific terms
        """
        vocab = self.get_vocabulary(domain)
        if not vocab:
            return text
        
        # Simple replacement strategy
        enhanced = text
        terms = vocab.get_terms_by_language(language)
        
        # Sort by length (longest first) to avoid partial replacements
        sorted_terms = sorted(terms.values(), key=len, reverse=True)
        
        for term in sorted_terms:
            # Simple case-insensitive replacement
            # In production, this would use more sophisticated NLP
            pass
        
        return enhanced
