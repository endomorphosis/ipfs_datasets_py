import hashlib
from multiformats import CID, multihash
import tempfile
import os
import sys
from typing import Any, Union


from pathlib import Path


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

    Usage Examples:
        # Initialize multiformats processor
        resources = {"ipfs_gateway": "http://localhost:8080"}
        metadata = {"version": "1.0"}
        formatter = ipfs_multiformats_py(resources, metadata)
        
        # Generate CID for file content
        file_cid = formatter.get_cid("/path/to/document.pdf")
        print(f"File CID: {file_cid}")
        
        # Generate CID for string content
        text_content = "Hello, IPFS world!"
        text_cid = formatter.get_cid(text_content)
        print(f"Text CID: {text_cid}")
        
        # Direct hash operations for advanced use cases
        file_hash = formatter.get_file_sha256("/path/to/data.json")
        multihash_obj = formatter.get_multihash_sha256(file_hash)
        
        # Batch CID generation for multiple files
        file_paths = ["/data/file1.txt", "/data/file2.csv", "/data/file3.json"]
        cids = [formatter.get_cid(path) for path in file_paths]

    Dependencies:
        Required:
        - hashlib: Python standard library for SHA-256 cryptographic hashing
        - multiformats: IPFS multiformats library for CID and multihash operations
        - tempfile: Temporary file management for string content processing
        - os: File system operations and path management

    Notes:
        - CID generation is deterministic and reproducible across different systems
        - Large files are processed in 8KB chunks to optimize memory usage
        - String content is processed through temporary files for consistency
        - Generated CIDs are compatible with all IPFS implementations and tools
        - Content addressing enables automatic deduplication and integrity verification
        - Temporary files are automatically cleaned up after processing
        - File paths are resolved to absolute paths for consistent processing
        - Base32 encoding provides human-readable content identifiers
    """
    def __init__(self, resources: Any, metadata: Any) -> None:
        """
        Initialize IPFS Multiformats Content Identifier Generation System

        Establishes a new ipfs_multiformats_py instance with comprehensive CID
        generation capabilities and multiformats compliance for IPFS content
        addressing. This initialization configures the multihash interface and
        prepares all necessary components for deterministic content identifier
        generation across distributed networks.

        Args:
            resources (Any): Resource configuration containing system settings
                and external service connections. While not directly used in
                the current implementation, this parameter maintains interface
                consistency with other IPFS dataset components and enables
                future extensibility for advanced features such as:
                - IPFS node configurations for direct content validation
                - Performance optimization settings for large file processing
                - Custom hashing algorithm configurations and extensions
                - Network timeouts and retry policies for distributed operations
                
            metadata (Any): Operational metadata containing version information,
                processing configurations, and compatibility settings. Similar
                to resources, this parameter ensures interface consistency and
                supports future enhancements including:
                - CID format version preferences and compatibility requirements
                - Content type specific processing configurations
                - Validation rules and quality control parameters
                - Provenance tracking and lineage management settings

        Attributes Initialized:
            multihash (multihash): Multihash library interface providing self-describing
                cryptographic hash generation and validation capabilities compliant
                with IPFS multiformats specification. This interface enables SHA-256
                hash wrapping and multihash format encoding for content addressing.

        Examples:
            # Basic initialization for CID generation
            resources = {"ipfs_gateway": "http://localhost:8080"}
            metadata = {"version": "1.0", "format": "raw"}
            formatter = ipfs_multiformats_py(resources, metadata)
            
            # Development configuration with debugging enabled
            dev_resources = {
                "ipfs_gateway": "http://localhost:8080",
                "debug_mode": True
            }
            dev_metadata = {
                "version": "1.0",
                "environment": "development"
            }
            dev_formatter = ipfs_multiformats_py(dev_resources, dev_metadata)

        Notes:
            - Initialization prepares multihash interface for immediate CID generation
            - Resource and metadata parameters maintain interface consistency
            - Multihash library provides IPFS-compatible content addressing
            - No network connectivity required for CID generation operations
            - Generated CIDs are deterministic and reproducible across systems
        """
        self.multihash = multihash

    # Step 1: Hash the file content with SHA-256
    def get_file_sha256(self, file_path: str) -> str:
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.digest()

    # Step 2: Wrap the hash in Multihash format
    def get_multihash_sha256(self, file_content_hash: str) -> str:
        mh = self.multihash.wrap(file_content_hash, 'sha2-256')
        return mh

    # Step 3: Generate CID from Multihash (CIDv1)
    def get_cid(self, file_data: str | bytes) -> str:
        if os.path.isfile(file_data) == True:
            absolute_path = os.path.abspath(file_data)
            file_content_hash = self.get_file_sha256(file_data)
            mh = self.get_multihash_sha256(file_content_hash)
            cid = CID('base32', 1, 'raw', mh)
        else:
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
                filename = f.name
                with open(filename, 'w') as f_new:
                    f_new.write(file_data)
                file_content_hash = self.get_file_sha256(filename)
                mh = self.get_multihash_sha256(file_content_hash)
                cid = CID('base32', 1, 'raw', mh)
                os.remove(filename)
        return str(cid)


# Generate CID for arbitrary string
def _get_cid_for_string(string: str) -> str:
    """
    Generate a Content Identifier (CID) for a given string using SHA-256 hashing and multihash encoding.

    Args:
        string (str): The input string for which the CID is to be generated.

    Returns:
        str: The generated CID in base32 format.

    Note:
        - This function uses the SHA-256 hashing algorithm to hash the input string.
        - The resulting hash is wrapped using the multihash library with the 'sha2-256' code.
        - The CID is constructed using the base32 encoding, version 1, and the 'raw' codec.
    """
    hash = hashlib.sha256(string.encode()).digest()
    mh = multihash.wrap(hash, 'sha2-256')
    cid = CID('base32', 1, 'raw', mh)
    return str(cid)


def get_cid(file_data: str | Path | bytes, for_string: bool = False) -> str:
    """
    Generate a Content Identifier (CID) for the given file or string.

    For file paths, it directly calculates the CID. For strings, calculates the CID from a temporary file.

    Args:
        file_data (str | Path | bytes): The file path or string data to generate a CID for.
        for_string (bool): Flag to indicate if the input is an arbitrary string 
            (as opposed to a Path or the string of a path). Defaults to False.

    Returns:
        str: The generated CID as a string.
    """
    if not isinstance(file_data, (str, Path, bytes)):
        raise TypeError(f"file_data must be of type str, Path, or bytes, got {type(file_data).__name__}")
    if not isinstance(for_string, bool):
        raise TypeError(f"for_string must be of type bool, got {type(for_string).__name__}")

    if for_string and isinstance(file_data, str):
        return _get_cid_for_string(file_data)

    if isinstance(file_data, Path):
       file_data = str(file_data)

    ipfs_multiformats = ipfs_multiformats_py(None, None)
    return ipfs_multiformats.get_cid(file_data)
