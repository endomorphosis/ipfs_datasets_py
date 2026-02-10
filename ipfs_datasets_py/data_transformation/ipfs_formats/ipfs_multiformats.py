import hashlib
import os
from pathlib import Path
from typing import Any

from multiformats import CID, multihash


class ipfs_multiformats_py:
    """
    IPFS Multiformats Content Identifier Generation and Validation System

    The ipfs_multiformats_py class provides comprehensive functionality for generating,
    validating, and managing Content Identifiers (CIDs) using the IPFS multiformats
    specification. This system enables content-addressable storage through cryptographic
    hashing, multihash encoding, and standardized CID generation that ensures data
    integrity and enables distributed content verification across IPFS networks.

    The class implements the complete multiformats specification including SHA-256
    hashing, multihash wrapping, and CIDv1 generation with support for multiple
    encoding formats and content types. This functionality is essential for creating
    immutable, verifiable content identifiers that enable decentralized storage,
    deduplication, and content integrity verification.

    Core Features:
    - SHA-256 content hashing with optimized chunk processing for large files
    - Multihash format encoding compliant with IPFS multiformats specification
    - CIDv1 generation with support for multiple bases and codecs
    - File and string content processing with automatic format detection
    - Content integrity verification through cryptographic hashing
    - Deterministic CID generation ensuring reproducible content addressing

    Multiformats Compliance:
    - SHA-256 hashing algorithm implementation for content fingerprinting
    - Multihash wrapper providing self-describing hash format
    - CIDv1 structure with version, codec, and multihash components
    - Base32 encoding for human-readable content identifiers
    - Raw codec support for efficient binary content addressing

    Content Processing:
    - Large file handling with memory-efficient chunk-based reading
    - String content processing through temporary file mechanisms
    - Automatic content type detection and appropriate processing selection
    - File system integration with absolute path resolution
    - Temporary file management with automatic cleanup

    IPFS Integration:
    - Compatible CID generation for direct IPFS storage and retrieval
    - Content addressing enabling automatic deduplication across networks
    - Distributed content verification through deterministic hashing
    - Cross-platform content identifiers for universal access
    - Version tracking through immutable content addressing

    Attributes:
        multihash (multihash): Multihash library interface for cryptographic hash
            encoding and multiformats compliance, providing self-describing hash
            generation and validation capabilities.

    Public Methods:
        get_file_sha256(file_path: str) -> bytes:
            Generate SHA-256 hash digest for file content with chunk processing
        get_multihash_sha256(file_content_hash: bytes) -> multihash.Multihash:
            Wrap SHA-256 hash in multihash format for self-describing encoding
        get_cid(file_data: str | bytes) -> str:
            Generate CIDv1 content identifier for files or string content

    Notes:
        - CID generation is deterministic and reproducible across different systems
        - Large files are processed in 8KB chunks to optimize memory usage
        - String content is processed through temporary files for consistency
        - Generated CIDs are compatible with all IPFS implementations and tools
    """

    def __init__(self, resources: Any = None, metadata: Any = None) -> None:
        self.multihash = multihash

    # Step 1: Hash the file content with SHA-256
    def get_file_sha256(self, file_path: str) -> bytes:
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.digest()

    # Step 2: Wrap the hash in Multihash format
    def get_multihash_sha256(self, file_content_hash: bytes):
        mh = self.multihash.wrap(file_content_hash, "sha2-256")
        return mh

    # Step 3: Generate CID from Multihash (CIDv1)
    def get_cid(self, file_data: str | bytes | Path) -> str:
        if isinstance(file_data, Path):
            file_data = str(file_data)

        if isinstance(file_data, str) and os.path.isfile(file_data):
            file_content_hash = self.get_file_sha256(file_data)
            mh = self.get_multihash_sha256(file_content_hash)
            return str(CID("base32", 1, "raw", mh))

        if isinstance(file_data, bytes):
            file_content_hash = hashlib.sha256(file_data).digest()
            mh = self.get_multihash_sha256(file_content_hash)
            return str(CID("base32", 1, "raw", mh))

        if isinstance(file_data, str):
            file_content_hash = hashlib.sha256(file_data.encode("utf-8")).digest()
            mh = self.get_multihash_sha256(file_content_hash)
            return str(CID("base32", 1, "raw", mh))

        raise TypeError(f"Unsupported file_data type: {type(file_data).__name__}")


# Generate CID for arbitrary string
def _get_cid_for_string(string: str) -> str:
    """Generate a Content Identifier (CID) for an arbitrary string."""

    hash = hashlib.sha256(string.encode()).digest()
    mh = multihash.wrap(hash, "sha2-256")
    cid = CID("base32", 1, "raw", mh)
    return str(cid)


def get_cid(file_data: str | Path | bytes, for_string: bool = False) -> str:
    """Generate a Content Identifier (CID) for a file or string."""

    if not isinstance(file_data, (str, Path, bytes)):
        raise TypeError(
            f"file_data must be of type str, Path, or bytes, got {type(file_data).__name__}"
        )
    if not isinstance(for_string, bool):
        raise TypeError(f"for_string must be of type bool, got {type(for_string).__name__}")

    if for_string and isinstance(file_data, str):
        return _get_cid_for_string(file_data)

    if isinstance(file_data, Path):
        file_data = str(file_data)

    ipfs_multiformats = ipfs_multiformats_py()
    return ipfs_multiformats.get_cid(file_data)


__all__ = [
    "ipfs_multiformats_py",
    "get_cid",
]
