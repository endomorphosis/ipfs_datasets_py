"""
IPFS CID-based cache utilities for TDFOL.

This module provides utilities for generating IPFS Content Identifiers (CIDs)
using the multiformats specification for cache keys. This ensures content-addressed,
verifiable, and IPFS-compatible cache key generation.
"""

import json
from typing import Any, Dict

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
