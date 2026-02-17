"""
Multi-Language Support MCP Tool.

This tool exposes the MultiLanguageSupport system which provides language
detection, translation, cross-language search, and legal term mappings for
international legal research.

Core implementation: ipfs_datasets_py.processors.legal_scrapers.multilanguage_support
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


async def detect_query_language(
    query: str,
    return_probabilities: bool = False
) -> Dict[str, Any]:
    """
    Detect the language of a legal search query.
    
    This is a thin wrapper around MultiLanguageSupport.detect_language().
    All business logic is in ipfs_datasets_py.processors.legal_scrapers.multilanguage_support
    
    Supported languages: English (en), German (de), French (fr), Spanish (es), Italian (it)
    
    Args:
        query: Text query to analyze
        return_probabilities: Return probability distribution for all languages (default: False)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - detected_language: ISO 639-1 language code (e.g., "en", "de", "fr")
        - confidence: Detection confidence score (0.0-1.0)
        - probabilities: Language probability distribution (if return_probabilities=True)
        - query: Original query text
    
    Example:
        >>> result = await detect_query_language("Was sind die EPA-Vorschriften?")
        >>> print(f"Language: {result['detected_language']}")  # "de"
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import MultiLanguageSupport
        
        if not query or not isinstance(query, str):
            return {
                "status": "error",
                "message": "Query must be a non-empty string"
            }
        
        ml_support = MultiLanguageSupport()
        
        # Detect language
        if return_probabilities:
            lang_info = ml_support.detect_language_with_probabilities(query)
            return {
                "status": "success",
                "detected_language": lang_info["language"],
                "confidence": lang_info["confidence"],
                "probabilities": lang_info["probabilities"],
                "query": query,
                "mcp_tool": "detect_query_language"
            }
        else:
            detected_lang = ml_support.detect_language(query)
            return {
                "status": "success",
                "detected_language": detected_lang,
                "confidence": 0.95,  # Default confidence
                "query": query,
                "mcp_tool": "detect_query_language"
            }
        
    except ImportError as e:
        logger.error(f"Import error in detect_query_language: {e}")
        return {
            "status": "error",
            "message": f"Required module not found: {str(e)}. Install with: pip install ipfs-datasets-py[legal]"
        }
    except Exception as e:
        logger.error(f"Error in detect_query_language MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "query": query
        }


async def translate_legal_query(
    query: str,
    target_language: str,
    source_language: Optional[str] = None,
    preserve_legal_terms: bool = True
) -> Dict[str, Any]:
    """
    Translate a legal search query to another language.
    
    This is a thin wrapper around MultiLanguageSupport.translate_query().
    All business logic is in ipfs_datasets_py.processors.legal_scrapers.multilanguage_support
    
    Features:
    - Automatic source language detection if not provided
    - Preservation of legal terms where appropriate
    - Language-specific legal term mappings
    
    Args:
        query: Text query to translate
        target_language: Target language code (en, de, fr, es, it)
        source_language: Source language code (auto-detected if not provided)
        preserve_legal_terms: Preserve legal terms in original language (default: True)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - original_query: Original query text
        - translated_query: Translated query text
        - source_language: Source language detected/specified
        - target_language: Target language
        - preserved_terms: Legal terms preserved (if preserve_legal_terms=True)
    
    Example:
        >>> result = await translate_legal_query(
        ...     query="EPA water regulations",
        ...     target_language="de"
        ... )
        >>> print(result['translated_query'])  # "EPA Wasservorschriften"
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import MultiLanguageSupport
        
        if not query or not isinstance(query, str):
            return {
                "status": "error",
                "message": "Query must be a non-empty string"
            }
        
        valid_languages = ["en", "de", "fr", "es", "it"]
        if target_language not in valid_languages:
            return {
                "status": "error",
                "message": f"target_language must be one of: {valid_languages}"
            }
        
        if source_language and source_language not in valid_languages:
            return {
                "status": "error",
                "message": f"source_language must be one of: {valid_languages}"
            }
        
        ml_support = MultiLanguageSupport()
        
        # Translate query
        translation_result = ml_support.translate_query(
            query=query,
            target_lang=target_language,
            source_lang=source_language,
            preserve_legal_terms=preserve_legal_terms
        )
        
        return {
            "status": "success",
            "original_query": query,
            "translated_query": translation_result["translated_text"],
            "source_language": translation_result["source_lang"],
            "target_language": translation_result["target_lang"],
            "confidence": translation_result.get("confidence", 1.0),
            "preserved_terms": translation_result.get("preserved_terms", []),
            "mcp_tool": "translate_legal_query"
        }
        
    except ImportError as e:
        logger.error(f"Import error in translate_legal_query: {e}")
        return {
            "status": "error",
            "message": f"Required module not found: {str(e)}. Install with: pip install ipfs-datasets-py[legal] langdetect deep-translator"
        }
    except Exception as e:
        logger.error(f"Error in translate_legal_query MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "query": query
        }


async def cross_language_legal_search(
    query: str,
    languages: List[str],
    max_results_per_language: int = 10,
    translate_results: bool = False,
    target_language: Optional[str] = None
) -> Dict[str, Any]:
    """
    Search for legal content across multiple languages.
    
    This is a thin wrapper around MultiLanguageSupport.cross_language_search().
    All business logic is in ipfs_datasets_py.processors.legal_scrapers.multilanguage_support
    
    Features:
    - Search in multiple languages simultaneously
    - Automatic query translation for each language
    - Result aggregation across languages
    - Optional translation of results back to target language
    
    Args:
        query: Search query (in any supported language)
        languages: List of languages to search in (e.g., ["en", "de", "fr"])
        max_results_per_language: Maximum results per language (default: 10)
        translate_results: Translate results to target language (default: False)
        target_language: Target language for result translation (default: query language)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - original_query: Original query text
        - query_language: Detected query language
        - results_by_language: Results grouped by language
        - total_results: Total number of results across all languages
        - languages_searched: Languages that were searched
        - translated_queries: Query translations for each language
    
    Example:
        >>> results = await cross_language_legal_search(
        ...     query="water pollution regulations",
        ...     languages=["en", "de", "fr"],
        ...     max_results_per_language=5
        ... )
        >>> print(f"Found {results['total_results']} results in {len(results['languages_searched'])} languages")
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import MultiLanguageSupport
        
        if not query or not isinstance(query, str):
            return {
                "status": "error",
                "message": "Query must be a non-empty string"
            }
        
        if not languages or not isinstance(languages, list):
            return {
                "status": "error",
                "message": "Languages must be a non-empty list"
            }
        
        valid_languages = ["en", "de", "fr", "es", "it"]
        for lang in languages:
            if lang not in valid_languages:
                return {
                    "status": "error",
                    "message": f"Invalid language '{lang}'. Must be one of: {valid_languages}"
                }
        
        if max_results_per_language < 1 or max_results_per_language > 100:
            return {
                "status": "error",
                "message": "max_results_per_language must be between 1 and 100"
            }
        
        if target_language and target_language not in valid_languages:
            return {
                "status": "error",
                "message": f"target_language must be one of: {valid_languages}"
            }
        
        ml_support = MultiLanguageSupport()
        
        # Detect query language
        query_language = ml_support.detect_language(query)
        
        # Perform cross-language search
        search_results = ml_support.cross_language_search(
            query=query,
            languages=languages,
            max_results_per_lang=max_results_per_language,
            translate_results=translate_results,
            target_lang=target_language or query_language
        )
        
        # Calculate statistics
        total_results = sum(len(results) for results in search_results["results_by_language"].values())
        
        return {
            "status": "success",
            "original_query": query,
            "query_language": query_language,
            "results_by_language": search_results["results_by_language"],
            "total_results": total_results,
            "languages_searched": search_results["languages_searched"],
            "translated_queries": search_results["translated_queries"],
            "translate_results": translate_results,
            "target_language": target_language or query_language,
            "mcp_tool": "cross_language_legal_search"
        }
        
    except ImportError as e:
        logger.error(f"Import error in cross_language_legal_search: {e}")
        return {
            "status": "error",
            "message": f"Required module not found: {str(e)}. Install with: pip install ipfs-datasets-py[legal] langdetect deep-translator"
        }
    except Exception as e:
        logger.error(f"Error in cross_language_legal_search MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "query": query
        }


async def get_legal_term_translations(
    term: str,
    source_language: str = "en",
    target_languages: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Get translations of legal terms across multiple languages.
    
    Args:
        term: Legal term to translate (e.g., "regulation", "statute", "court")
        source_language: Source language of the term (default: "en")
        target_languages: Target languages (default: all supported languages)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - term: Original term
        - source_language: Source language
        - translations: Dictionary mapping language codes to translated terms
        - legal_context: Legal context information for the term
    
    Example:
        >>> result = await get_legal_term_translations("regulation", "en", ["de", "fr"])
        >>> print(result['translations'])  # {"de": "Verordnung", "fr": "règlement"}
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import MultiLanguageSupport
        
        if not term or not isinstance(term, str):
            return {
                "status": "error",
                "message": "Term must be a non-empty string"
            }
        
        valid_languages = ["en", "de", "fr", "es", "it"]
        if source_language not in valid_languages:
            return {
                "status": "error",
                "message": f"source_language must be one of: {valid_languages}"
            }
        
        if target_languages:
            for lang in target_languages:
                if lang not in valid_languages:
                    return {
                        "status": "error",
                        "message": f"Invalid language '{lang}'. Must be one of: {valid_languages}"
                    }
        else:
            target_languages = [lang for lang in valid_languages if lang != source_language]
        
        ml_support = MultiLanguageSupport()
        
        # Get translations
        translations = ml_support.get_legal_term_translations(
            term=term,
            source_lang=source_language,
            target_langs=target_languages
        )
        
        return {
            "status": "success",
            "term": term,
            "source_language": source_language,
            "translations": translations,
            "target_languages": target_languages,
            "message": f"Retrieved translations for '{term}' in {len(translations)} languages"
        }
        
    except Exception as e:
        logger.error(f"Error in get_legal_term_translations: {e}")
        return {
            "status": "error",
            "message": str(e),
            "term": term
        }
