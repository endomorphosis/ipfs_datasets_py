"""
spaCy utilities for TDFOL natural language processing.

This module provides centralized spaCy import handling and utilities
to eliminate code duplication across NL processing modules.

The spaCy library is an optional dependency. If not installed, this
module provides graceful fallbacks and clear error messages.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Try to import spaCy - it's an optional dependency
try:
    import spacy
    from spacy.tokens import Doc, Token, Span
    from spacy.matcher import Matcher
    HAVE_SPACY = True
except ImportError:
    spacy = None  # type: ignore
    Doc = None  # type: ignore
    Token = None  # type: ignore
    Span = None  # type: ignore
    Matcher = None  # type: ignore
    HAVE_SPACY = False
    logger.warning(
        "spaCy not available. NL processing will be limited. "
        "Install with: pip install spacy && python -m spacy download en_core_web_sm"
    )


def require_spacy() -> None:
    """
    Raise ImportError if spaCy is not available.
    
    This function should be called at the start of operations that
    require spaCy to provide a clear error message.
    
    Raises:
        ImportError: If spaCy is not installed
    
    Example:
        >>> require_spacy()
        >>> nlp = spacy.load("en_core_web_sm")
    """
    if not HAVE_SPACY:
        raise ImportError(
            "spaCy is required for natural language processing. "
            "Install with: pip install spacy && "
            "python -m spacy download en_core_web_sm"
        )


def load_spacy_model(model_name: str = "en_core_web_sm") -> Any:
    """
    Load a spaCy language model with error handling.
    
    Args:
        model_name: Name of spaCy model (default: "en_core_web_sm")
    
    Returns:
        Loaded spaCy language model
    
    Raises:
        ImportError: If spaCy is not installed
        OSError: If model is not downloaded
    
    Example:
        >>> nlp = load_spacy_model("en_core_web_sm")
        >>> doc = nlp("All contractors must pay taxes")
    """
    require_spacy()
    
    try:
        return spacy.load(model_name)
    except OSError:
        logger.error(
            f"spaCy model '{model_name}' not found. "
            f"Download with: python -m spacy download {model_name}"
        )
        raise


__all__ = [
    'HAVE_SPACY',
    'spacy',
    'Doc',
    'Token',
    'Span',
    'Matcher',
    'require_spacy',
    'load_spacy_model',
]
