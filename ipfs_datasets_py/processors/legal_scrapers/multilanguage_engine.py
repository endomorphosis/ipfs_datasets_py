"""
Multi-language legal support canonical engine module.

Standalone async functions for multi-language legal operations.
All business logic delegates to the canonical ``MultiLanguageSupport``
class in :mod:`ipfs_datasets_py.processors.legal_scrapers.multilanguage_support`.

Public API
----------
detect_query_language(query, ...)
translate_legal_query(query, target_language, ...)
cross_language_legal_search(query, languages, ...)
get_legal_term_translations(term, ...)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_VALID_LANGUAGES = ["en", "de", "fr", "es", "it"]


def _err(msg: str, **kw) -> Dict[str, Any]:
    return {"status": "error", "message": msg, **kw}


async def detect_query_language(
    query: str,
    return_probabilities: bool = False,
) -> Dict[str, Any]:
    """Detect the language of a legal search query.

    Parameters
    ----------
    query:
        Text query to analyse.
    return_probabilities:
        Return probability distribution for all languages.

    Returns
    -------
    dict
        ``detected_language``, ``confidence``, optionally ``probabilities``.
    """
    if not query or not isinstance(query, str):
        return _err("Query must be a non-empty string")

    try:
        from ipfs_datasets_py.processors.legal_scrapers import MultiLanguageSupport

        ml = MultiLanguageSupport()
        lang = ml.detect_language(query)

        result: Dict[str, Any] = {
            "status":            "success",
            "detected_language": lang,
            "confidence":        1.0,
            "query":             query,
        }

        if return_probabilities and hasattr(ml, "detect_language_with_probabilities"):
            info = ml.detect_language_with_probabilities(query)
            result["probabilities"] = info.get("probabilities", {})

        return result

    except ImportError as exc:
        return _err(f"Required module not found: {exc}. Install with: pip install langdetect")
    except Exception as exc:
        logger.error("Error in detect_query_language: %s", exc)
        return _err(str(exc), query=query)


async def translate_legal_query(
    query: str,
    target_language: str,
    source_language: Optional[str] = None,
    preserve_legal_terms: bool = True,
) -> Dict[str, Any]:
    """Translate a legal search query to another language.

    Parameters
    ----------
    query:
        Text query to translate.
    target_language:
        Target language ISO code (``en``, ``de``, ``fr``, ``es``, ``it``).
    source_language:
        Source language code (auto-detected if not provided).
    preserve_legal_terms:
        Preserve legal terms in original language.

    Returns
    -------
    dict
        ``original_query``, ``translated_query``, ``source_language``,
        ``target_language``, ``confidence``, ``preserved_terms``.
    """
    if not query or not isinstance(query, str):
        return _err("Query must be a non-empty string")
    if target_language not in _VALID_LANGUAGES:
        return _err(f"target_language must be one of: {_VALID_LANGUAGES}")
    if source_language and source_language not in _VALID_LANGUAGES:
        return _err(f"source_language must be one of: {_VALID_LANGUAGES}")

    try:
        from ipfs_datasets_py.processors.legal_scrapers import MultiLanguageSupport

        ml = MultiLanguageSupport()
        tr = ml.translate_query(
            query=query,
            target_lang=target_language,
            source_lang=source_language,
        )

        return {
            "status":           "success",
            "original_query":   query,
            "translated_query": tr.translated_text,
            "source_language":  tr.source_lang,
            "target_language":  tr.target_lang,
            "confidence":       getattr(tr, "confidence", 1.0),
            "preserved_terms":  getattr(tr, "preserved_terms", []),
        }

    except ImportError as exc:
        return _err(
            f"Required module not found: {exc}. "
            "Install with: pip install langdetect deep-translator"
        )
    except Exception as exc:
        logger.error("Error in translate_legal_query: %s", exc)
        return _err(str(exc), query=query)


async def cross_language_legal_search(
    query: str,
    languages: List[str],
    max_results_per_language: int = 10,
    translate_results: bool = False,
    target_language: Optional[str] = None,
) -> Dict[str, Any]:
    """Search for legal content across multiple languages simultaneously.

    Parameters
    ----------
    query:
        Search query (in any supported language).
    languages:
        Languages to search in, e.g. ``["en", "de", "fr"]``.
    max_results_per_language:
        Maximum results per language (1–100).
    translate_results:
        Translate results back to *target_language*.
    target_language:
        Target language for result translation.

    Returns
    -------
    dict
        ``original_query``, ``query_language``, ``results_by_language``,
        ``total_results``, ``languages_searched``.
    """
    if not query or not isinstance(query, str):
        return _err("Query must be a non-empty string")
    if not languages or not isinstance(languages, list):
        return _err("Languages must be a non-empty list")
    for lang in languages:
        if lang not in _VALID_LANGUAGES:
            return _err(f"Invalid language '{lang}'. Must be one of: {_VALID_LANGUAGES}")
    if not 1 <= max_results_per_language <= 100:
        return _err("max_results_per_language must be between 1 and 100")
    if target_language and target_language not in _VALID_LANGUAGES:
        return _err(f"target_language must be one of: {_VALID_LANGUAGES}")

    try:
        from ipfs_datasets_py.processors.legal_scrapers import MultiLanguageSupport

        ml = MultiLanguageSupport()
        query_language = ml.detect_language(query)

        search_result = ml.cross_language_search(
            query=query,
            languages=languages,
            max_results_per_lang=max_results_per_language,
            translate_results=translate_results,
            target_lang=target_language or query_language,
        )

        results_by_lang = search_result.get("results_by_language", {})
        total_results   = sum(len(v) for v in results_by_lang.values())

        return {
            "status":                "success",
            "original_query":        query,
            "query_language":        query_language,
            "results_by_language":   results_by_lang,
            "total_results":         total_results,
            "languages_searched":    languages,
            "translated_queries":    search_result.get("translated_queries", {}),
        }

    except ImportError as exc:
        return _err(f"Required module not found: {exc}.")
    except Exception as exc:
        logger.error("Error in cross_language_legal_search: %s", exc)
        return _err(str(exc), query=query)


async def get_legal_term_translations(
    term: str,
    source_language: str = "en",
    target_languages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Get legal term translations across supported languages.

    Parameters
    ----------
    term:
        Legal term to translate.
    source_language:
        Source language code (default: ``"en"``).
    target_languages:
        Target language codes (default: all supported except *source_language*).

    Returns
    -------
    dict
        ``original_term``, ``translations`` (dict mapping language → translation),
        ``source_language``.
    """
    if not term or not isinstance(term, str):
        return _err("Term must be a non-empty string")
    if source_language not in _VALID_LANGUAGES:
        return _err(f"source_language must be one of: {_VALID_LANGUAGES}")
    if target_languages is None:
        target_languages = [l for l in _VALID_LANGUAGES if l != source_language]
    for lang in target_languages:
        if lang not in _VALID_LANGUAGES:
            return _err(f"Invalid target language '{lang}'. Must be one of: {_VALID_LANGUAGES}")

    try:
        from ipfs_datasets_py.processors.legal_scrapers import MultiLanguageSupport

        ml = MultiLanguageSupport()
        translations: Dict[str, str] = {}

        for target_lang in target_languages:
            tr = ml.translate_query(
                query=term,
                target_lang=target_lang,
                source_lang=source_language,
            )
            translations[target_lang] = tr.translated_text

        return {
            "status":          "success",
            "original_term":   term,
            "source_language": source_language,
            "translations":    translations,
        }

    except ImportError as exc:
        return _err(f"Required module not found: {exc}.")
    except Exception as exc:
        logger.error("Error in get_legal_term_translations: %s", exc)
        return _err(str(exc), term=term)
