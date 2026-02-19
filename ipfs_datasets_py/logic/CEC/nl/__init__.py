"""
Multi-Language Natural Language Processing for CEC.

This package provides natural language parsing support for multiple languages
including English, Spanish, French, and German with domain-specific vocabularies.

Components:
- LanguageDetector: Automatic language detection
- BaseParser: Common parsing interface
- SpanishParser: Spanish language support
- FrenchParser: French language support
- GermanParser: German language support
- Domain Vocabularies: Legal, medical, and technical terminology

Usage:
    from ipfs_datasets_py.logic.CEC.nl import LanguageDetector, get_parser
    
    detector = LanguageDetector()
    language = detector.detect("Esta es una obligación legal")
    parser = get_parser(language)
    result = parser.parse("Esta es una obligación legal")
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .language_detector import LanguageDetector, Language
    from .base_parser import BaseParser

__all__ = [
    'LanguageDetector',
    'Language',
    'BaseParser',
]
