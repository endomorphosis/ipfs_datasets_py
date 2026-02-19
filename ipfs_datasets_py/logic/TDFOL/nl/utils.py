"""
Utilities for TDFOL natural language processing.

This module consolidates:
- IPFS CID-based cache utilities (previously cache_utils.py)
- spaCy utilities and import handling (previously spacy_utils.py)
"""

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Section 1: IPFS CID Cache Utilities
# =============================================================================

try:
    from multiformats import CID, multihash
    MULTIFORMATS_AVAILABLE = True
except ImportError:
    MULTIFORMATS_AVAILABLE = False
    CID = None
    multihash = None


def create_cache_cid(data: Dict[str, Any]) -> str:
    """
    Create IPFS CID for cache key using multiformats.
    
    This function generates a deterministic Content Identifier (CID) from a dictionary
    of cache parameters. The CID is:
    - Content-addressed: Same inputs always produce the same CID
    - IPFS-native: Can be used to store/retrieve from IPFS networks
    - Verifiable: CID contains hash algorithm metadata
    - Future-proof: Supports schema versioning
    
    Args:
        data: Dictionary containing cache parameters (e.g., text, provider, prompt_hash)
    
    Returns:
        CIDv1 string in base32 encoding (starts with 'bafk')
    
    Raises:
        ImportError: If multiformats library is not available
        ValueError: If data cannot be serialized to JSON
    
    Example:
        >>> data = {"text": "hello", "provider": "openai", "prompt_hash": "abc123"}
        >>> cid = create_cache_cid(data)
        >>> print(cid)
        bafkreigaknpexyvxt76zgkitavbwx6ejgfheup5oybpm77f3pxzrvwpfli
        
        >>> # Same input produces same CID
        >>> cid2 = create_cache_cid(data)
        >>> assert cid == cid2
    """
    if not MULTIFORMATS_AVAILABLE:
        raise ImportError(
            "multiformats library not available. Install with: pip install py-multiformats-cid"
        )
    
    try:
        # Serialize to canonical JSON bytes (deterministic)
        json_bytes = json.dumps(
            data,
            sort_keys=True,  # Ensure consistent key ordering
            separators=(",", ":"),  # Compact format
            ensure_ascii=False
        ).encode("utf-8")
    except (TypeError, ValueError) as e:
        raise ValueError(f"Failed to serialize data to JSON: {e}") from e
    
    # Generate SHA2-256 multihash
    mh = multihash.digest(json_bytes, "sha2-256")
    
    # Create CIDv1 with base32 encoding, raw codec
    cid = CID("base32", 1, "raw", mh)
    
    return str(cid)


def validate_cid(cid_str: str) -> bool:
    """
    Validate that a string is a valid IPFS CID.
    
    Args:
        cid_str: String to validate
    
    Returns:
        True if valid CID, False otherwise
    
    Example:
        >>> cid = "bafkreigaknpexyvxt76zgkitavbwx6ejgfheup5oybpm77f3pxzrvwpfli"
        >>> assert validate_cid(cid) == True
        >>> assert validate_cid("not_a_cid") == False
    """
    if not MULTIFORMATS_AVAILABLE:
        return False
    
    try:
        CID.decode(cid_str)
        return True
    except Exception:
        return False


def parse_cid(cid_str: str) -> Dict[str, Any]:
    """
    Parse CID and extract metadata.
    
    Args:
        cid_str: CID string to parse
    
    Returns:
        Dictionary with version, codec, and hash information
    
    Raises:
        ValueError: If CID string is invalid
    
    Example:
        >>> cid = "bafkreigaknpexyvxt76zgkitavbwx6ejgfheup5oybpm77f3pxzrvwpfli"
        >>> info = parse_cid(cid)
        >>> print(info["version"])
        1
        >>> print(info["codec"])
        'raw'
    """
    if not MULTIFORMATS_AVAILABLE:
        raise ImportError("multiformats library not available")
    
    try:
        cid = CID.decode(cid_str)
        
        # Extract codec name (it's a Multicodec object)
        codec_name = cid.codec.name if hasattr(cid.codec, 'name') else str(cid.codec)
        
        # Extract hash function info
        hashfun_name = cid.hashfun.name if hasattr(cid.hashfun, 'name') else str(cid.hashfun)
        
        return {
            "version": cid.version,
            "codec": codec_name,
            "hashfun": {
                "name": hashfun_name,
                "digest": cid.digest.hex()
            }
        }
    except Exception as e:
        raise ValueError(f"Invalid CID: {e}") from e


# =============================================================================
# Section 2: spaCy Utilities
# =============================================================================

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


# =============================================================================
# Section 3: Public API Exports
# =============================================================================

__all__ = [
    # IPFS CID utilities
    'MULTIFORMATS_AVAILABLE',
    'create_cache_cid',
    'validate_cid',
    'parse_cid',
    
    # spaCy utilities
    'HAVE_SPACY',
    'spacy',
    'Doc',
    'Token',
    'Span',
    'Matcher',
    'require_spacy',
    'load_spacy_model',
]
