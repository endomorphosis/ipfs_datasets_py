"""
Tests for Domain Vocabularies (Phase 5 Week 5).

This test module validates domain-specific vocabulary support for CEC,
covering legal, medical, and technical terminology across languages.

Test Coverage:
- Legal vocabulary (3 tests)
- Medical vocabulary (3 tests)
- Technical vocabulary (3 tests)
- Vocabulary manager integration (1 test)

Total: 10 tests
"""

import pytest
from ipfs_datasets_py.logic.CEC.nl.domain_vocabularies.domain_vocab import (
    DomainTerm,
    DomainVocabulary,
    LegalVocabulary,
    MedicalVocabulary,
    TechnicalVocabulary,
    DomainVocabularyManager
)


class TestLegalVocabulary:
    """Test legal domain vocabulary."""
    
    def test_legal_vocabulary_initialization(self):
        """
        GIVEN LegalVocabulary class
        WHEN initializing vocabulary
        THEN should load legal terms
        """
        vocab = LegalVocabulary()
        assert vocab.domain_name == "legal"
        assert len(vocab.terms) > 0
        assert "legal_obligation" in vocab.terms
        assert "duty" in vocab.terms
        assert "right" in vocab.terms
    
    def test_legal_vocabulary_translations(self):
        """
        GIVEN LegalVocabulary with terms
        WHEN getting translations
        THEN should return correct translations for each language
        """
        vocab = LegalVocabulary()
        obligation_term = vocab.get_term("legal_obligation")
        
        assert obligation_term is not None
        assert obligation_term.english == "legal obligation"
        assert obligation_term.spanish == "obligación legal"
        assert obligation_term.french == "obligation légale"
        assert obligation_term.german == "Rechtspflicht"
    
    def test_legal_vocabulary_categories(self):
        """
        GIVEN LegalVocabulary
        WHEN filtering by category
        THEN should return terms in that category
        """
        vocab = LegalVocabulary()
        deontic_terms = vocab.get_all_terms(category="deontic")
        
        assert len(deontic_terms) > 0
        # legal_obligation, duty, and prohibited_act are deontic
        assert any(t.term_id == "legal_obligation" for t in deontic_terms)


class TestMedicalVocabulary:
    """Test medical domain vocabulary."""
    
    def test_medical_vocabulary_initialization(self):
        """
        GIVEN MedicalVocabulary class
        WHEN initializing vocabulary
        THEN should load medical terms
        """
        vocab = MedicalVocabulary()
        assert vocab.domain_name == "medical"
        assert len(vocab.terms) > 0
        assert "informed_consent" in vocab.terms
        assert "medical_duty" in vocab.terms
        assert "patient" in vocab.terms
    
    def test_medical_vocabulary_translations(self):
        """
        GIVEN MedicalVocabulary with terms
        WHEN getting translations
        THEN should return correct translations for each language
        """
        vocab = MedicalVocabulary()
        consent_term = vocab.get_term("informed_consent")
        
        assert consent_term is not None
        assert consent_term.english == "informed consent"
        assert consent_term.spanish == "consentimiento informado"
        assert consent_term.french == "consentement éclairé"
        assert consent_term.german == "Aufgeklärte Einwilligung"
    
    def test_medical_vocabulary_by_language(self):
        """
        GIVEN MedicalVocabulary
        WHEN getting terms by language
        THEN should return dict of translations
        """
        vocab = MedicalVocabulary()
        spanish_terms = vocab.get_terms_by_language("es")
        
        assert len(spanish_terms) > 0
        assert "informed_consent" in spanish_terms
        assert spanish_terms["informed_consent"] == "consentimiento informado"


class TestTechnicalVocabulary:
    """Test technical domain vocabulary."""
    
    def test_technical_vocabulary_initialization(self):
        """
        GIVEN TechnicalVocabulary class
        WHEN initializing vocabulary
        THEN should load technical terms
        """
        vocab = TechnicalVocabulary()
        assert vocab.domain_name == "technical"
        assert len(vocab.terms) > 0
        assert "system_requirement" in vocab.terms
        assert "access_permission" in vocab.terms
        assert "software_agent" in vocab.terms
    
    def test_technical_vocabulary_translations(self):
        """
        GIVEN TechnicalVocabulary with terms
        WHEN getting translations
        THEN should return correct translations for each language
        """
        vocab = TechnicalVocabulary()
        access_term = vocab.get_term("access_permission")
        
        assert access_term is not None
        assert access_term.english == "access permission"
        assert access_term.spanish == "permiso de acceso"
        assert access_term.french == "permission d'accès"
        assert access_term.german == "Zugriffsberechtigung"
    
    def test_technical_vocabulary_categories(self):
        """
        GIVEN TechnicalVocabulary
        WHEN filtering by category
        THEN should return terms in that category
        """
        vocab = TechnicalVocabulary()
        entity_terms = vocab.get_all_terms(category="entity")
        
        assert len(entity_terms) > 0
        assert any(t.term_id == "software_agent" for t in entity_terms)


class TestVocabularyManager:
    """Test domain vocabulary manager."""
    
    def test_vocabulary_manager_integration(self):
        """
        GIVEN DomainVocabularyManager
        WHEN adding multiple vocabularies
        THEN should manage all vocabularies
        """
        manager = DomainVocabularyManager()
        
        # Add vocabularies
        manager.add_vocabulary(LegalVocabulary())
        manager.add_vocabulary(MedicalVocabulary())
        manager.add_vocabulary(TechnicalVocabulary())
        
        # Check domains
        domains = manager.get_all_domains()
        assert len(domains) == 3
        assert "legal" in domains
        assert "medical" in domains
        assert "technical" in domains
        
        # Get vocabulary terms
        legal_terms = manager.get_vocabulary_terms("legal", "en")
        assert len(legal_terms) > 0
        assert "legal_obligation" in legal_terms
        
        medical_terms = manager.get_vocabulary_terms("medical", "fr")
        assert len(medical_terms) > 0
        
        technical_terms = manager.get_vocabulary_terms("technical", "de")
        assert len(technical_terms) > 0
