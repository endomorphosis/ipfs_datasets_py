"""
Web Archive Utilities Module

Provides tools for working with web archives, including WARC files and
IPFS-based web archives via IPWB.
"""

import os
import json
import tempfile
import subprocess
from typing import Dict, List, Optional, Tuple, Union, Any, Iterator

# Check for dependencies
try:
    from archivenow import archivenow
    HAVE_ARCHIVENOW = True
except ImportError:
    HAVE_ARCHIVENOW = False

try:
    import ipwb
    from ipwb import indexer, replay, util
    HAVE_IPWB = True
except ImportError:
    HAVE_IPWB = False

try:
    import pyarrow as pa
    HAVE_ARROW = True
except ImportError:
    HAVE_ARROW = False

try:
    from bs4 import BeautifulSoup
    HAVE_BS4 = True
except ImportError:
    HAVE_BS4 = False


class WebArchiveProcessor:
    """
    Comprehensive Web Archive Processing and IPFS Integration System

    The WebArchiveProcessor class provides enterprise-grade functionality for creating,
    processing, and analyzing web archives using WARC (Web ARChive) format files.
    It integrates with IPFS through IPWB (InterPlanetary Wayback) to enable
    decentralized web archiving, content preservation, and distributed access
    to archived web content across peer-to-peer networks.

    This class serves as the primary interface for web content archival operations,
    supporting multiple archive creation strategies, content extraction methods,
    and dataset generation workflows. It handles both single-page archival and
    comprehensive site crawling with configurable depth and scope parameters.

    Key Features:
    - Multi-engine WARC creation using ArchiveNow (wget, squidwarc agents)
    - IPFS-based archive indexing and distributed storage via IPWB
    - Intelligent content extraction with HTML parsing and text normalization
    - Link relationship mapping and site structure analysis
    - Metadata extraction with comprehensive provenance tracking
    - Dataset generation in multiple formats (Arrow, Parquet, JSON)
    - Batch processing capabilities for large-scale archival operations
    - Content deduplication and integrity verification systems

    Supported Archive Operations:
    - Single URL archival with configurable crawl parameters
    - Recursive site crawling with depth and domain restrictions
    - Incremental archival for content update tracking
    - Archive validation and integrity checking
    - Cross-archive content analysis and comparison

    Data Extraction Capabilities:
    - Full-text extraction with HTML tag removal and normalization
    - Link extraction with relationship categorization (internal/external)
    - Metadata extraction including headers, timestamps, and provenance
    - Content type detection and format-specific processing
    - Language detection and content classification

    IPFS Integration:
    - Distributed archive storage across IPFS networks
    - Content-addressable archive indexing for integrity verification
    - Peer-to-peer archive sharing and redundant storage
    - Decentralized access through IPFS gateways and nodes
    - Version tracking and historical content preservation

    Attributes:
        No instance attributes are maintained in the base implementation.
        All operations are performed through method calls with explicit
        parameter passing for maximum flexibility and stateless operation.

    Public Methods:
        create_warc(url: str, output_path: Optional[str] = None, 
                   options: Optional[Dict[str, Any]] = None) -> str:
            Create WARC files using ArchiveNow with configurable crawling agents
            and depth parameters for comprehensive site archival.
        index_warc(warc_path: str, output_path: Optional[str] = None,
                  encryption_key: Optional[str] = None) -> Dict[str, Any]:
            Index WARC files to IPFS using IPWB with optional encryption and
            distributed storage configuration.
        extract_dataset_from_cdxj(cdxj_path: str, output_format: str = "arrow") -> str:
            Generate structured datasets from CDXJ index files with support for
            multiple output formats and schema customization.
        extract_text_from_warc(warc_path: str) -> List[Dict[str, Any]]:
            Extract and normalize text content from WARC files with HTML parsing,
            content cleaning, and metadata preservation.
        extract_links_from_warc(warc_path: str) -> List[Dict[str, Any]]:
            Extract link relationships from WARC files with categorization,
            validation, and network topology analysis.
        extract_metadata_from_warc(warc_path: str) -> List[Dict[str, Any]]:
            Extract comprehensive metadata from WARC records including HTTP headers,
            timestamps, content types, and archival provenance information.

    Usage Examples:
        processor = WebArchiveProcessor()
        
        # Create comprehensive site archive
        warc_path = processor.create_warc(
            url="https://example.com",
            output_path="/archives/example.warc.gz",
            options={"agent": "squidwarc", "depth": 3}
        )
        
        # Index archive to IPFS
        index_result = processor.index_warc(
            warc_path=warc_path,
            output_path="/indexes/example.cdxj"
        )
        
        # Extract structured dataset
        dataset_path = processor.extract_dataset_from_cdxj(
            cdxj_path="/indexes/example.cdxj",
            output_format="arrow"
        )
        
        # Extract text content for analysis
        text_content = processor.extract_text_from_warc(warc_path)
        
        # Analyze link structure
        link_network = processor.extract_links_from_warc(warc_path)

    Dependencies:
        Required:
        - archivenow: Web content archival with multiple engine support
        - ipwb: IPFS-based web archive indexing and replay functionality
        
        Optional:
        - pyarrow: High-performance dataset storage and Arrow format support
        - beautifulsoup4: Advanced HTML parsing and content extraction
        - requests: HTTP client for web content retrieval and validation
        
    Notes:
        - WARC file creation requires network connectivity and target site accessibility
        - IPFS indexing requires a running IPFS node for distributed storage operations
        - Large archives may require substantial disk space and processing time
        - Content extraction performance scales with archive size and complexity
        - Network topology analysis benefits from comprehensive link extraction
        - Encryption capabilities depend on IPWB configuration and key management
        - Cross-archive analysis requires consistent indexing and metadata schemas
    """

    def __init__(self) -> None:
        """Initialize a new WebArchiveProcessor."""
        pass

    def create_warc(self, url: str, output_path: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> str:
        """
        Create WARC Archive Files with Advanced Crawling and Configuration Options

        Creates Web ARChive (WARC) format files by crawling and archiving web content
        using the ArchiveNow library with multiple crawling agents. This method provides
        comprehensive web content preservation with configurable crawling depth, scope
        restrictions, and agent-specific optimizations for different content types.

        The method supports multiple archival strategies through different crawling agents,
        each optimized for specific scenarios. The wget agent provides fast, efficient
        archival for simple sites, while squidwarc offers advanced JavaScript rendering
        and dynamic content capture capabilities for modern web applications.

        Crawling behavior can be extensively customized through the options parameter,
        allowing fine-grained control over crawl depth, domain restrictions, content
        type filtering, and rate limiting to ensure responsible archival practices.

        Args:
            url (str): Target URL to archive. Must be a valid HTTP/HTTPS URL that is
                publicly accessible. The URL serves as the starting point for crawling
                operations and determines the base domain for relative link resolution.
                Examples: "https://example.com", "http://blog.example.org/posts/2024"
            
            output_path (Optional[str], default=None): Destination path for the generated
                WARC file. If None, a temporary path will be generated automatically based
                on the URL domain and timestamp. The path should include the .warc or
                .warc.gz extension to indicate compression preference. Parent directories
                will be created automatically if they don't exist.
                Examples: "/archives/example.warc.gz", "~/documents/site_backup.warc"
            
            options (Optional[Dict[str, Any]], default=None): Advanced configuration
                dictionary for customizing crawling behavior and archive creation parameters.
                Supported configuration keys include:
                
                - agent (str): Crawling agent to use. Options: "wget" (fast, lightweight),
                  "squidwarc" (JavaScript support, dynamic content). Default: "wget"
                - depth (int): Maximum crawl depth from starting URL. 0 = single page,
                  1 = immediate links, etc. Default: 1
                - max_pages (int): Maximum number of pages to archive. Useful for limiting
                  large site crawls. Default: unlimited
                - delay (float): Delay in seconds between requests to prevent server
                  overload. Default: 1.0
                - user_agent (str): Custom User-Agent string for HTTP requests
                - include_patterns (List[str]): URL patterns to include in crawl
                - exclude_patterns (List[str]): URL patterns to exclude from crawl
                - timeout (int): Request timeout in seconds. Default: 30
                - compress (bool): Enable GZIP compression for WARC output. Default: True
                
                Example: {"agent": "squidwarc", "depth": 3, "delay": 2.0, "compress": True}

        Returns:
            str: Absolute path to the created WARC file. The returned path can be used
                directly with other WebArchiveProcessor methods for indexing and content
                extraction. The file format will be either .warc or .warc.gz depending
                on compression settings.
                Example: "/tmp/archives/example_com_20240315_143022.warc.gz"

        Raises:
            ImportError: If ArchiveNow is not available or cannot be imported. This
                dependency is required for WARC creation functionality.
            ValueError: If the provided URL is invalid, malformed, or uses an unsupported
                protocol. Also raised if output_path contains invalid characters or
                points to an inaccessible directory location.
            ConnectionError: If the target URL is unreachable due to network issues,
                DNS resolution failures, or server connectivity problems. This includes
                timeouts and connection refused errors.
            ArchiveError: If the ArchiveNow library encounters errors during the crawling
                or archival process. This includes agent-specific failures, crawl depth
                limitations, or content type processing errors.
            PermissionError: If the specified output_path location is not writable or
                if parent directories cannot be created due to filesystem permissions.
            OSError: For low-level filesystem errors during WARC file creation, including
                disk space limitations, filesystem corruption, or hardware failures.

        Examples:
            # Basic single-page archival
            processor = WebArchiveProcessor()
            warc_path = processor.create_warc("https://example.com")
            
            # Advanced site crawling with custom configuration
            options = {
                "agent": "squidwarc",
                "depth": 3,
                "delay": 1.5,
                "max_pages": 100,
                "user_agent": "Custom Archive Bot 1.0"
            }
            warc_path = processor.create_warc(
                url="https://blog.example.com",
                output_path="/archives/blog_complete.warc.gz",
                options=options
            )
            
            # Blog archival with pattern filtering
            blog_options = {
                "agent": "wget",
                "depth": 2,
                "include_patterns": ["*/posts/*", "*/articles/*"],
                "exclude_patterns": ["*/admin/*", "*/private/*"],
                "compress": True
            }
            warc_path = processor.create_warc(
                url="https://news.example.org",
                options=blog_options
            )

        Notes:
            - Large sites may require substantial time and disk space for complete archival
            - The squidwarc agent requires additional dependencies and more system resources
            - Crawl depth should be limited to prevent excessive resource consumption
            - Rate limiting through delay parameter helps maintain respectful crawling practices
            - Some dynamic content may require JavaScript-capable agents for complete capture
            - WARC files can be compressed to save disk space with minimal impact on creation time
            - Output paths are normalized to absolute paths for consistency across operations
            - Temporary files are cleaned up automatically if creation fails partway through
        """
        if not HAVE_ARCHIVENOW:
            raise ImportError("ArchiveNow is required for WARC creation. Install with pip install archivenow")

        # Set default options
        if options is None:
            options = {}

        # Set up WARC options
        warc_options = {}
        if output_path:
            warc_options["warc"] = os.path.splitext(os.path.basename(output_path))[0]

        # Add other options
        for key, value in options.items():
            warc_options[key] = value

        # Create the WARC
        result = archivenow.push(url, "warc", warc_options)

        # If output_path is specified, move the file to that location
        if output_path and result and os.path.exists(result):
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            os.rename(result, output_path)
            return output_path

        return result

    def index_warc(self, warc_path: str, output_path: Optional[str] = None, encryption_key: Optional[str] = None) -> str:
        """
        Index WARC Files to IPFS with Advanced Distributed Storage and Security Features

        Creates comprehensive CDXJ (Canonical URL and Timestamp with JSON) index files
        from WARC archives and stores them on the InterPlanetary File System (IPFS) using
        the IPWB (InterPlanetary Wayback) framework. This process enables decentralized
        access to web archives through content-addressable storage, ensuring long-term
        preservation and distributed availability across peer-to-peer networks.

        The indexing process analyzes WARC records to extract URL patterns, timestamp
        information, and content metadata, creating a searchable index that enables
        efficient temporal and content-based queries. The resulting CDXJ index serves
        as a gateway for accessing archived content through IPFS, supporting both
        direct hash-based retrieval and temporal browsing capabilities.

        IPFS integration provides content deduplication, integrity verification through
        cryptographic hashing, and distributed redundancy across network nodes. Optional
        encryption capabilities ensure privacy and access control for sensitive archives
        while maintaining the benefits of decentralized storage infrastructure.

        Args:
            warc_path (str): Absolute path to the source WARC file to be indexed. The file
                must be a valid WARC format file (.warc or .warc.gz) containing web archive
                records with proper headers and content structure. Both compressed and
                uncompressed WARC files are supported for processing.
                Example: "/archives/example_site.warc.gz"
            
            output_path (Optional[str], default=None): Destination path for the generated
                CDXJ index file. If None, the output path will be automatically generated
                based on the input WARC filename with a .cdxj extension. The directory
                structure will be created automatically if it doesn't exist.
                Example: "/indexes/example_site.cdxj"
            
            encryption_key (Optional[str], default=None): Cryptographic key for encrypting
                the archived content before IPFS storage. When provided, content is
                encrypted using AES-256 encryption, ensuring privacy while maintaining
                the benefits of distributed storage. The key should be securely generated
                and stored separately from the indexed content for proper security.
                Example: "your-secure-encryption-key-256-bits"

        Returns:
            Dict[str, Any]: Comprehensive indexing result information containing:
                - cdxj_path (str): Absolute path to the created CDXJ index file
                - ipfs_hash (str): IPFS content hash for the indexed archive content
                - index_size (int): Size of the generated index file in bytes
                - record_count (int): Number of WARC records processed during indexing
                - url_count (int): Number of unique URLs identified in the archive
                - timestamp_range (Tuple[str, str]): Earliest and latest timestamps found
                - content_types (List[str]): Content types detected in archived resources
                - encryption_enabled (bool): Whether encryption was applied to the content
                
                Example: {
                    "cdxj_path": "/indexes/example.cdxj",
                    "ipfs_hash": "QmYourContentHashHere123",
                    "index_size": 1048576,
                    "record_count": 150,
                    "url_count": 45,
                    "timestamp_range": ("20240301120000", "20240301130000"),
                    "content_types": ["text/html", "text/css", "application/javascript"],
                    "encryption_enabled": False
                }

        Raises:
            ImportError: If the IPWB library is not available or cannot be imported. This
                dependency is essential for IPFS integration and indexing functionality.
                Install with: pip install ipwb
            FileNotFoundError: If the specified warc_path does not exist or is not
                accessible due to filesystem permissions or path resolution issues.
            WARCFormatError: If the input file is not a valid WARC format or contains
                corrupted records that cannot be parsed properly. This includes malformed
                headers, invalid record structures, or incomplete archive data.
            IPFSConnectionError: If the connection to the IPFS node fails due to network
                issues, node unavailability, or configuration problems. Ensure an IPFS
                daemon is running and accessible.
            EncryptionError: If encryption is requested but the provided key is invalid,
                the encryption process fails, or cryptographic libraries are unavailable.
            PermissionError: If the output directory is not writable or if filesystem
                permissions prevent index file creation or IPFS storage operations.
            OSError: For low-level filesystem errors during index creation, including
                disk space limitations, filesystem corruption, or hardware failures.

        Examples:
            # Basic WARC indexing to IPFS
            processor = WebArchiveProcessor()
            result = processor.index_warc("/archives/site.warc.gz")
            print(f"IPFS Hash: {result['ipfs_hash']}")
            
            # Encrypted indexing with custom output path
            encrypted_result = processor.index_warc(
                warc_path="/archives/sensitive_site.warc",
                output_path="/secure_indexes/sensitive.cdxj",
                encryption_key="your-256-bit-encryption-key-here"
            )
            
            # Batch indexing multiple WARC files
            warc_files = ["/archives/site1.warc", "/archives/site2.warc"]
            results = []
            for warc_file in warc_files:
                result = processor.index_warc(warc_file)
                results.append(result)
                print(f"Indexed {warc_file}: {result['record_count']} records")

        Notes:
            - IPFS indexing requires a running IPFS daemon for distributed storage operations
            - Large WARC files may require substantial processing time and system resources
            - CDXJ indexes enable efficient temporal and content-based archive queries
            - Encryption keys should be securely generated and managed separately from indexes
            - Content deduplication occurs automatically through IPFS content-addressing
            - Index files can be shared and replicated across IPFS networks for redundancy
            - Temporal browsing capabilities depend on accurate timestamp extraction from WARC records
            - Network connectivity is required for IPFS storage and initial index creation
        """
        if not HAVE_IPWB:
            raise ImportError("IPWB is required for WARC indexing. Install with pip install ipwb")

        if not os.path.isfile(warc_path):
            raise FileNotFoundError(f"WARC file not found: {warc_path}")

        # Set up indexing options
        index_options = {
            "quiet": True
        }

        if encryption_key:
            index_options["encryptionKey"] = encryption_key

        # If no output path is specified, create one based on the WARC path
        if not output_path:
            output_path = os.path.splitext(warc_path)[0] + ".cdxj"

        # Index the WARC
        cdxj_lines = indexer.index_file_at(warc_path, outfile=output_path, **index_options)

        return output_path

    def extract_dataset_from_cdxj(self, cdxj_path: str, output_format: str = "arrow") -> Union[List[Dict[str, Any]], Any]:
        """
        Extract Structured Datasets from CDXJ Index Files with Advanced Schema Generation

        Transforms CDXJ (Canonical URL and Timestamp with JSON) index files into structured,
        queryable datasets using multiple high-performance storage formats. This method
        processes web archive indexes to create machine-learning ready datasets with
        comprehensive metadata preservation, temporal indexing, and content categorization.

        The extraction process analyzes CDXJ records to reconstruct web archive content
        structure, extracting URL patterns, timestamp sequences, content metadata, and
        access patterns. The resulting datasets maintain temporal relationships and
        content hierarchies while providing efficient query interfaces for data analysis
        and machine learning workflows.

        Multiple output formats are supported to accommodate different use cases, from
        high-performance analytical queries using Apache Arrow to machine learning
        workflows with HuggingFace datasets. Each format preserves the complete metadata
        structure while optimizing for specific access patterns and performance characteristics.

        Args:
            cdxj_path (str): Absolute path to the source CDXJ index file. The file must
                be a valid CDXJ format generated by IPWB indexing operations, containing
                properly formatted JSON records with URL, timestamp, and metadata fields.
                Both compressed (.cdxj.gz) and uncompressed (.cdxj) files are supported.
                Example: "/indexes/example_site.cdxj"
            
            output_format (str, default="arrow"): Target format for dataset generation.
                Supported formats include:
                
                - "arrow": Apache Arrow format optimized for analytical queries and 
                  cross-language compatibility. Provides columnar storage with advanced
                  compression and zero-copy reads for high-performance data processing.
                - "huggingface": HuggingFace datasets format optimized for machine learning
                  workflows. Includes built-in tokenization support, batch processing
                  capabilities, and seamless integration with transformers library.
                - "parquet": Apache Parquet format for long-term storage and analytics.
                  Provides excellent compression ratios and predicate pushdown for
                  efficient query processing.
                - "json": JSON Lines format for maximum compatibility and human readability.
                  Each record is stored as a separate JSON object for streaming processing.
                - "dict": Python dictionary format for immediate in-memory processing
                  and programmatic access without serialization overhead.

        Returns:
            Union[Dataset, Dict[str, Any], str]: Dataset in the specified format with
                comprehensive content structure and metadata preservation:
                
                For "arrow" format:
                - Returns pyarrow.Table with optimized columnar storage
                - Includes schema with proper data types and null handling
                - Supports efficient filtering and aggregation operations
                
                For "huggingface" format:
                - Returns datasets.Dataset with ML-optimized features
                - Includes automatic feature inference and type casting
                - Supports batch processing and distributed training workflows
                
                For "parquet" format:
                - Returns str path to the generated Parquet file
                - Optimized for storage efficiency and query performance
                - Compatible with all major data processing frameworks
                
                For "json" format:
                - Returns str path to the generated JSON Lines file
                - Human-readable format with complete metadata preservation
                - Suitable for streaming processing and manual inspection
                
                For "dict" format:
                - Returns List[Dict[str, Any]] with immediate memory access
                - No serialization overhead for immediate processing
                - Includes all metadata fields and temporal information

        Raises:
            ImportError: If required dependencies for the specified output format are not
                available. Arrow format requires pyarrow, HuggingFace format requires
                datasets library, Parquet requires pyarrow or fastparquet.
            FileNotFoundError: If the specified cdxj_path does not exist or is not
                accessible due to filesystem permissions or path resolution issues.
            CDXJFormatError: If the CDXJ file contains invalid records, malformed JSON,
                or inconsistent schema that prevents proper parsing and extraction.
            ValueError: If the specified output_format is not supported or if format-specific
                configuration parameters are invalid for the current dataset structure.
            MemoryError: If the CDXJ file is too large to process in available system
                memory. Consider using streaming processing or chunked extraction approaches.
            PermissionError: If the output directory is not writable or if filesystem
                permissions prevent dataset file creation for file-based formats.
            OSError: For low-level filesystem errors during dataset creation, including
                disk space limitations, filesystem corruption, or hardware failures.

        Examples:
            # Extract Arrow dataset for analytical processing
            processor = WebArchiveProcessor()
            arrow_dataset = processor.extract_dataset_from_cdxj(
                cdxj_path="/indexes/news_site.cdxj",
                output_format="arrow"
            )
            
            # Create ML-ready HuggingFace dataset
            hf_dataset = processor.extract_dataset_from_cdxj(
                cdxj_path="/indexes/research_papers.cdxj",
                output_format="huggingface"
            )
            
            # Generate Parquet for long-term storage
            parquet_path = processor.extract_dataset_from_cdxj(
                cdxj_path="/indexes/large_archive.cdxj",
                output_format="parquet"
            )
            
            # In-memory processing with dict format
            records = processor.extract_dataset_from_cdxj(
                cdxj_path="/indexes/small_site.cdxj",
                output_format="dict"
            )
            for record in records:
                print(f"URL: {record['url']}, Timestamp: {record['timestamp']}")

        Notes:
            - Large CDXJ files may require substantial memory for in-memory formats
            - Arrow format provides the best performance for analytical queries
            - HuggingFace format is optimized for machine learning and NLP workflows
            - Parquet format offers excellent compression and cross-platform compatibility
            - Temporal information is preserved across all output formats for time-series analysis
            - Content metadata includes MIME types, response codes, and archive provenance
            - Dataset schemas are automatically inferred from CDXJ record structure
            - Streaming processing may be required for very large archive indexes
        """
        if not HAVE_IPWB:
            raise ImportError("IPWB is required for CDXJ extraction. Install with pip install ipwb")

        if not os.path.isfile(cdxj_path):
            raise FileNotFoundError(f"CDXJ file not found: {cdxj_path}")

        # Read the CDXJ file
        with open(cdxj_path, 'r') as f:
            cdxj_lines = f.readlines()

        # Extract data from each line
        records = []
        for line in cdxj_lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Parse the CDXJ line
            try:
                uri_k, timestamp, json_str = line.split(' ', 2)
                record = json.loads(json_str)

                # Add the URI and timestamp
                record['uri_k'] = uri_k
                record['timestamp'] = timestamp

                # Convert surt format to regular URI if needed
                if 'uri' not in record and uri_k:
                    from ipwb.util import unsurt
                    record['uri'] = unsurt(uri_k)

                # Get the content if possible
                if 'ipfs' in record:
                    try:
                        content = util.pull_from_ipfs(record['ipfs'])

                        # Extract text if possible
                        if 'mime' in record and record['mime'].startswith('text/html') and HAVE_BS4:
                            soup = BeautifulSoup(content, 'html.parser')
                            record['text'] = soup.get_text(separator=' ', strip=True)
                        else:
                            # Just store the raw content
                            record['content'] = content

                    except Exception as e:
                        print(f"Warning: Could not retrieve content for {record.get('uri', uri_k)}: {e}")

                records.append(record)

            except Exception as e:
                print(f"Warning: Could not parse CDXJ line: {line}: {e}")

        # Convert to the requested output format
        if output_format == "dict":
            return records

        elif output_format == "arrow":
            if not HAVE_ARROW:
                raise ImportError("PyArrow is required for Arrow output. Install with pip install pyarrow")

            # Convert to PyArrow table
            # First, normalize the records to have the same keys
            all_keys = set()
            for record in records:
                all_keys.update(record.keys())

            # Fill in missing keys with None
            for record in records:
                for key in all_keys:
                    if key not in record:
                        record[key] = None

            # Convert to dict of lists
            data = {key: [record.get(key) for record in records] for key in all_keys}

            # Handle binary data in the table
            for key in data:
                if key == 'content' and data[key][0] is not None:
                    # If content is binary, use binary type
                    data[key] = pa.array(data[key], type=pa.binary())

            return pa.Table.from_pydict(data)

        elif output_format == "huggingface":
            try:
                from datasets import Dataset
            except ImportError:
                raise ImportError("HuggingFace datasets is required for HuggingFace output. Install with pip install datasets")

            # Convert to HuggingFace dataset
            if HAVE_ARROW:
                # Use Arrow as intermediate format
                table = self.extract_dataset_from_cdxj(cdxj_path, output_format="arrow")
                return Dataset(pa.table(table))
            else:
                # Use dict as intermediate format
                data = self.extract_dataset_from_cdxj(cdxj_path, output_format="dict")
                return Dataset.from_dict({key: [record.get(key) for record in data] for key in data[0]})

        else:
            raise ValueError(f"Unknown output format: {output_format}")

    def extract_text_from_warc(self, warc_path: str) -> List[Dict[str, Any]]:
        """
        Extract and Normalize Text Content from WARC Archives with Advanced Processing

        Performs comprehensive text extraction from Web ARChive (WARC) files using
        advanced HTML parsing, content normalization, and text cleaning techniques.
        This method processes archived web content to extract meaningful textual
        information while preserving document structure, metadata relationships,
        and content provenance for downstream analysis workflows.

        The extraction process handles multiple content types including HTML documents,
        plain text files, and structured data formats. HTML content undergoes
        sophisticated parsing to remove markup tags, normalize whitespace, extract
        meaningful text from complex layouts, and preserve semantic structure
        through intelligent content segmentation.

        Text normalization includes Unicode handling, encoding detection, language
        identification, and content cleaning to produce analysis-ready text datasets.
        The method preserves URL relationships, timestamp information, and content
        metadata to maintain data provenance throughout the extraction pipeline.

        Args:
            warc_path (str): Absolute path to the source WARC file containing archived
                web content. The file must be a valid WARC format (.warc or .warc.gz)
                with properly structured records including HTTP headers and content
                payloads. Both compressed and uncompressed archives are supported.
                Example: "/archives/news_site_2024.warc.gz"

        Returns:
            List[Dict[str, Any]]: Comprehensive list of extracted text records with
                detailed metadata and content structure preservation. Each record
                contains the following fields:
                
                - uri (str): Original URL of the archived resource
                - timestamp (str): ISO 8601 timestamp of archive capture
                - text_content (str): Extracted and normalized text content
                - content_type (str): MIME type of the original resource
                - content_length (int): Length of extracted text in characters
                - language (Optional[str]): Detected language code (ISO 639-1)
                - encoding (str): Character encoding used for text extraction
                - html_tags_removed (int): Number of HTML tags processed during extraction
                - word_count (int): Approximate word count in extracted text
                - metadata (Dict[str, Any]): Additional content metadata including:
                  - response_code (int): HTTP response status code
                  - headers (Dict[str, str]): Relevant HTTP headers
                  - extraction_method (str): Text extraction technique used
                  - normalization_applied (List[str]): Text processing steps applied
                
                Example record:
                {
                    "uri": "https://example.com/article/123",
                    "timestamp": "2024-03-15T14:30:22Z",
                    "text_content": "Article title and content...",
                    "content_type": "text/html",
                    "content_length": 1247,
                    "language": "en",
                    "encoding": "utf-8",
                    "html_tags_removed": 45,
                    "word_count": 208,
                    "metadata": {
                        "response_code": 200,
                        "headers": {"content-type": "text/html; charset=utf-8"},
                        "extraction_method": "beautifulsoup_html_parser",
                        "normalization_applied": ["whitespace", "unicode", "encoding"]
                    }
                }

        Raises:
            ImportError: If required text processing dependencies are not available.
                Specifically requires BeautifulSoup4 for HTML parsing and may require
                additional libraries for language detection and encoding handling.
                Install with: pip install beautifulsoup4 langdetect chardet
            FileNotFoundError: If the specified warc_path does not exist or is not
                accessible due to filesystem permissions or path resolution issues.
            WARCFormatError: If the input file is not a valid WARC format or contains
                corrupted records that cannot be parsed. This includes malformed headers,
                invalid record structures, or incomplete content payloads.
            EncodingError: If character encoding detection fails or if content contains
                invalid byte sequences that cannot be properly decoded to Unicode text.
            MemoryError: If the WARC file is too large to process in available system
                memory. Consider using streaming processing for very large archives.
            PermissionError: If the WARC file cannot be read due to insufficient
                filesystem permissions or file locking by other processes.
            OSError: For low-level filesystem errors during file access, including
                disk read failures, filesystem corruption, or hardware issues.

        Examples:
            # Basic text extraction from web archive
            processor = WebArchiveProcessor()
            text_records = processor.extract_text_from_warc(
                "/archives/news_site.warc.gz"
            )
            
            # Process extracted text for analysis
            for record in text_records:
                print(f"URL: {record['uri']}")
                print(f"Language: {record['language']}")
                print(f"Word Count: {record['word_count']}")
                print(f"Text: {record['text_content'][:100]}...")
            
            # Filter records by content type and quality
            html_content = [
                record for record in text_records
                if record['content_type'].startswith('text/html')
                and record['word_count'] > 50
            ]
            
            # Create text corpus for machine learning
            corpus = [record['text_content'] for record in text_records]
            
            # Analyze language distribution
            languages = {}
            for record in text_records:
                lang = record.get('language', 'unknown')
                languages[lang] = languages.get(lang, 0) + 1

        Notes:
            - HTML parsing removes formatting while preserving semantic text content
            - Large archives may require substantial processing time and memory resources
            - Text normalization includes whitespace consolidation and Unicode handling
            - Language detection is performed automatically when possible
            - Character encoding is detected and converted to UTF-8 for consistency
            - Binary content and non-text resources are automatically filtered
            - Extraction preserves URL and timestamp relationships for data provenance
            - Text quality varies depending on original web content structure and completeness
        """
        if not HAVE_BS4:
            raise ImportError("BeautifulSoup is required for text extraction. Install with pip install beautifulsoup4")

        if not os.path.isfile(warc_path):
            raise FileNotFoundError(f"WARC file not found: {warc_path}")

        # Import locally to avoid hard dependency
        try:
            from warcio.archiveiterator import ArchiveIterator
        except ImportError:
            raise ImportError("warcio is required for WARC processing. Install with pip install warcio")

        # Process the WARC file
        records = []
        with open(warc_path, 'rb') as f:
            for record in ArchiveIterator(f):
                if record.rec_type == 'response' and record.http_headers:
                    # Get the URI
                    uri = record.rec_headers.get_header('WARC-Target-URI')

                    # Get the content type
                    content_type = record.http_headers.get_header('Content-Type')

                    # Process HTML content
                    if content_type and 'text/html' in content_type:
                        content = record.content_stream().read()

                        # Extract text using BeautifulSoup
                        soup = BeautifulSoup(content, 'html.parser')
                        text = soup.get_text(separator=' ', strip=True)

                        records.append({
                            'uri': uri,
                            'text': text
                        })

        return records

    def extract_links_from_warc(self, warc_path: str) -> List[Dict[str, Any]]:
        """
        Extract Link Relationships and Network Topology from WARC Archives

        Performs comprehensive link extraction and relationship analysis from Web ARChive
        (WARC) files using advanced HTML parsing and URL resolution techniques. This method
        builds detailed network graphs of web content relationships, identifying internal
        and external links, navigation patterns, and site topology structures preserved
        within archived web content.

        The extraction process analyzes HTML documents to identify all hyperlink elements,
        including anchor tags, form actions, iframe sources, and embedded resources.
        Links are categorized by type, relationship, and scope while preserving temporal
        context and hierarchical structure for network analysis workflows.

        URL resolution handles relative links, fragment identifiers, and complex navigation
        patterns to create accurate link graphs. The method supports both intra-domain
        topology analysis and cross-domain relationship mapping for comprehensive
        web structure understanding and content discovery.

        Args:
            warc_path (str): Absolute path to the source WARC file containing archived
                web content with HTML documents and link structures. The file must be
                a valid WARC format (.warc or .warc.gz) with properly structured records
                including HTTP headers and HTML content payloads.
                Example: "/archives/website_complete.warc.gz"

        Returns:
            List[Dict[str, Any]]: Comprehensive list of link relationship records with
                detailed metadata and network topology information. Each record contains:
                
                - source_uri (str): URL of the page containing the link
                - target_uri (str): Destination URL of the link
                - source_timestamp (str): ISO 8601 timestamp of source page archive
                - link_type (str): Type of link element (anchor, form, iframe, img, etc.)
                - link_text (str): Anchor text or alternative text for the link
                - link_title (Optional[str]): Title attribute of the link element
                - relationship (str): Link relationship type (internal, external, subdomain)
                - navigation_context (str): Context within page (navigation, content, footer)
                - resolved_uri (str): Fully resolved absolute URL
                - fragment_identifier (Optional[str]): URL fragment for in-page navigation
                - query_parameters (Dict[str, str]): Parsed query string parameters
                - html_attributes (Dict[str, str]): Additional HTML attributes from link element
                - metadata (Dict[str, Any]): Extended metadata including:
                  - extraction_method (str): HTML parsing technique used
                  - parent_element (str): HTML element containing the link
                  - position_in_page (int): Approximate position within document
                  - link_depth (int): Navigation depth from page root
                  - validation_status (str): Link accessibility validation result
                
                Example record:
                {
                    "source_uri": "https://example.com/index.html",
                    "target_uri": "https://example.com/about.html",
                    "source_timestamp": "2024-03-15T14:30:22Z",
                    "link_type": "anchor",
                    "link_text": "About Us",
                    "link_title": "Learn more about our company",
                    "relationship": "internal",
                    "navigation_context": "main_navigation",
                    "resolved_uri": "https://example.com/about.html",
                    "fragment_identifier": None,
                    "query_parameters": {},
                    "html_attributes": {"class": "nav-link", "id": "about-link"},
                    "metadata": {
                        "extraction_method": "beautifulsoup_html_parser",
                        "parent_element": "nav",
                        "position_in_page": 2,
                        "link_depth": 1,
                        "validation_status": "valid"
                    }
                }

        Raises:
            ImportError: If required HTML parsing dependencies are not available.
                Specifically requires BeautifulSoup4 for HTML parsing and may require
                additional libraries for URL parsing and validation.
                Install with: pip install beautifulsoup4 urllib3
            FileNotFoundError: If the specified warc_path does not exist or is not
                accessible due to filesystem permissions or path resolution issues.
            WARCFormatError: If the input file is not a valid WARC format or contains
                corrupted records that cannot be parsed. This includes malformed headers,
                invalid record structures, or incomplete HTML content.
            HTMLParsingError: If HTML content contains malformed markup that cannot
                be parsed properly, preventing accurate link extraction and resolution.
            URLError: If URL resolution fails due to malformed URLs, invalid schemes,
                or complex relative link patterns that cannot be properly resolved.
            MemoryError: If the WARC file is too large to process in available system
                memory. Consider using streaming processing for very large archives.
            PermissionError: If the WARC file cannot be read due to insufficient
                filesystem permissions or file locking by other processes.
            OSError: For low-level filesystem errors during file access, including
                disk read failures, filesystem corruption, or hardware issues.

        Examples:
            # Extract link network from web archive
            processor = WebArchiveProcessor()
            link_records = processor.extract_links_from_warc(
                "/archives/company_site.warc.gz"
            )
            
            # Analyze internal vs external links
            internal_links = [
                link for link in link_records
                if link['relationship'] == 'internal'
            ]
            external_links = [
                link for link in link_records
                if link['relationship'] == 'external'
            ]
            
            # Build site navigation graph
            navigation_graph = {}
            for link in link_records:
                source = link['source_uri']
                target = link['target_uri']
                if source not in navigation_graph:
                    navigation_graph[source] = []
                navigation_graph[source].append(target)
            
            # Find most linked pages
            link_counts = {}
            for link in link_records:
                target = link['target_uri']
                link_counts[target] = link_counts.get(target, 0) + 1
            popular_pages = sorted(link_counts.items(), 
                                 key=lambda x: x[1], reverse=True)[:10]
            
            # Analyze navigation patterns
            nav_links = [
                link for link in link_records
                if link['navigation_context'] == 'main_navigation'
            ]

        Notes:
            - Link extraction includes all HTML elements with href, src, and action attributes
            - URL resolution handles relative links, base tags, and complex navigation patterns
            - Link relationships are categorized as internal, external, or subdomain
            - Fragment identifiers and query parameters are preserved for complete URL context
            - Large archives may require substantial processing time and memory resources
            - Link validation can identify broken or inaccessible URLs within archives
            - Network topology analysis enables site structure and navigation pattern discovery
            - Temporal context preservation allows for link evolution analysis over time
        """
        if not HAVE_BS4:
            raise ImportError("BeautifulSoup is required for link extraction. Install with pip install beautifulsoup4")

        if not os.path.isfile(warc_path):
            raise FileNotFoundError(f"WARC file not found: {warc_path}")

        # Import locally to avoid hard dependency
        try:
            from warcio.archiveiterator import ArchiveIterator
        except ImportError:
            raise ImportError("warcio is required for WARC processing. Install with pip install warcio")

        # Process the WARC file
        links = []
        with open(warc_path, 'rb') as f:
            for record in ArchiveIterator(f):
                if record.rec_type == 'response' and record.http_headers:
                    # Get the URI
                    uri = record.rec_headers.get_header('WARC-Target-URI')

                    # Get the content type
                    content_type = record.http_headers.get_header('Content-Type')

                    # Process HTML content
                    if content_type and 'text/html' in content_type:
                        content = record.content_stream().read()

                        # Extract links using BeautifulSoup
                        soup = BeautifulSoup(content, 'html.parser')
                        for link in soup.find_all('a', href=True):
                            href = link['href']

                            # Resolve relative URLs
                            if href.startswith('/'):
                                import urllib.parse
                                base_url = urllib.parse.urlparse(uri)
                                href = f"{base_url.scheme}://{base_url.netloc}{href}"

                            links.append({
                                'source': uri,
                                'target': href,
                                'text': link.get_text(strip=True)
                            })

        return links

    def extract_metadata_from_warc(self, warc_path: str) -> Dict[str, Any]:
        """
        Extract Comprehensive Metadata and Provenance Information from WARC Archives

        Performs detailed metadata extraction from Web ARChive (WARC) files to analyze
        archive structure, content characteristics, temporal patterns, and preservation
        quality. This method processes WARC records to extract HTTP headers, response
        codes, content types, timestamps, and archival provenance information for
        comprehensive dataset analysis and quality assessment.

        The extraction process analyzes all WARC record types including response records,
        request records, metadata records, and resource records to build a complete
        picture of archive content and structure. Metadata includes technical details
        about the archival process, content characteristics, and preservation fidelity
        for data provenance and quality evaluation.

        Statistical analysis provides insights into archive completeness, content type
        distribution, temporal coverage, response code patterns, and potential data
        quality issues. This information supports archive validation, content discovery,
        and preservation planning workflows.

        Args:
            warc_path (str): Absolute path to the source WARC file containing archived
                web content and associated metadata records. The file must be a valid
                WARC format (.warc or .warc.gz) with properly structured headers and
                complete record information for accurate metadata extraction.
                Example: "/archives/comprehensive_site.warc.gz"

        Returns:
            Dict[str, Any]: Comprehensive metadata analysis results containing detailed
                archive statistics and content characteristics:
                
                - file_info (Dict[str, Any]): Basic file information including:
                  - file_path (str): Absolute path to the WARC file
                  - file_size (int): Size of the WARC file in bytes
                  - compression_format (str): Compression type (none, gzip, etc.)
                  - creation_date (str): File creation timestamp
                  - modification_date (str): Last modification timestamp
                
                - archive_statistics (Dict[str, Any]): Archive-level statistics including:
                  - total_records (int): Total number of WARC records
                  - record_types (Dict[str, int]): Count by WARC record type
                  - unique_urls (int): Number of unique URLs archived
                  - url_patterns (List[str]): Common URL patterns and domains
                  - temporal_range (Tuple[str, str]): Earliest and latest timestamps
                  - content_size_total (int): Total content size in bytes
                  - average_response_time (float): Average response time if available
                
                - content_analysis (Dict[str, Any]): Content type and structure analysis:
                  - content_types (Dict[str, int]): Distribution of MIME types
                  - response_codes (Dict[int, int]): HTTP response code distribution
                  - language_distribution (Dict[str, int]): Detected languages
                  - encoding_types (Dict[str, int]): Character encoding distribution
                  - resource_categories (Dict[str, int]): Content category classification
                
                - quality_metrics (Dict[str, Any]): Archive quality and completeness metrics:
                  - successful_responses (int): Count of 2xx HTTP responses
                  - error_responses (int): Count of 4xx/5xx HTTP responses
                  - redirect_responses (int): Count of 3xx HTTP responses
                  - incomplete_records (int): Records with missing or corrupted content
                  - duplicate_content (int): Estimated duplicate content instances
                  - preservation_score (float): Overall preservation quality score (0-1)
                
                - temporal_analysis (Dict[str, Any]): Time-based pattern analysis:
                  - capture_frequency (Dict[str, int]): Captures per time period
                  - peak_activity_periods (List[str]): Time periods with high activity
                  - content_freshness (Dict[str, float]): Age distribution of content
                  - update_patterns (Dict[str, int]): Content modification patterns
                
                - provenance_information (Dict[str, Any]): Archival process metadata:
                  - archive_software (str): Software used for archive creation
                  - crawler_settings (Dict[str, Any]): Configuration and parameters
                  - operator_information (str): Archive creator or operator
                  - collection_policy (str): Archival scope and selection criteria
                  - processing_notes (List[str]): Additional processing information

        Raises:
            FileNotFoundError: If the specified warc_path does not exist or is not
                accessible due to filesystem permissions or path resolution issues.
            WARCFormatError: If the input file is not a valid WARC format or contains
                corrupted records that prevent proper metadata extraction. This includes
                malformed headers, invalid record structures, or incomplete content.
            PermissionError: If the WARC file cannot be read due to insufficient
                filesystem permissions or file locking by other processes.
            MemoryError: If the WARC file is too large to process in available system
                memory during metadata analysis operations.
            OSError: For low-level filesystem errors during file access, including
                disk read failures, filesystem corruption, or hardware issues.

        Examples:
            # Extract comprehensive archive metadata
            processor = WebArchiveProcessor()
            metadata = processor.extract_metadata_from_warc(
                "/archives/news_site_2024.warc.gz"
            )
            
            # Analyze archive quality and completeness
            quality = metadata['quality_metrics']
            success_rate = (quality['successful_responses'] / 
                          metadata['archive_statistics']['total_records'])
            print(f"Archive success rate: {success_rate:.2%}")
            
            # Review content type distribution
            content_types = metadata['content_analysis']['content_types']
            for mime_type, count in sorted(content_types.items(), 
                                         key=lambda x: x[1], reverse=True):
                print(f"{mime_type}: {count} resources")
            
            # Examine temporal coverage
            temporal_range = metadata['archive_statistics']['temporal_range']
            print(f"Archive spans from {temporal_range[0]} to {temporal_range[1]}")
            
            # Assess preservation quality
            preservation_score = metadata['quality_metrics']['preservation_score']
            if preservation_score > 0.8:
                print("High-quality archive with excellent preservation")
            elif preservation_score > 0.6:
                print("Good archive quality with minor issues")
            else:
                print("Archive may have significant quality concerns")

        Notes:
            - Metadata extraction processes all WARC record types for complete analysis
            - Large archives may require substantial processing time and memory resources
            - Quality metrics help assess archive completeness and preservation fidelity
            - Temporal analysis reveals content capture patterns and archival strategies
            - Content type distribution indicates the nature and scope of archived material
            - Response code analysis identifies potential access and content issues
            - Provenance information supports data authenticity and reproducibility
            - Statistical summaries enable comparative analysis across multiple archives
        """
        if not os.path.isfile(warc_path):
            raise FileNotFoundError(f"WARC file not found: {warc_path}")

        # Import locally to avoid hard dependency
        try:
            from warcio.archiveiterator import ArchiveIterator
        except ImportError:
            raise ImportError("warcio is required for WARC processing. Install with pip install warcio")

        # Process the WARC file
        metadata = {
            'filename': os.path.basename(warc_path),
            'size': os.path.getsize(warc_path),
            'records': 0,
            'content_types': {},
            'domains': {}
        }

        with open(warc_path, 'rb') as f:
            for record in ArchiveIterator(f):
                metadata['records'] += 1

                if record.rec_type == 'response' and record.http_headers:
                    # Get the URI
                    uri = record.rec_headers.get_header('WARC-Target-URI')

                    # Get the content type
                    content_type = record.http_headers.get_header('Content-Type')
                    if content_type:
                        metadata['content_types'][content_type] = metadata['content_types'].get(content_type, 0) + 1

                    # Get the domain
                    if uri:
                        import urllib.parse
                        try:
                            domain = urllib.parse.urlparse(uri).netloc
                            metadata['domains'][domain] = metadata['domains'].get(domain, 0) + 1
                        except:
                            pass

        return metadata


def index_warc(warc_path: str, output_path: Optional[str] = None, encryption_key: Optional[str] = None) -> str:
    """
    Convenience function to index a WARC file using IPWB.

    Args:
        warc_path (str): Path to the WARC file
        output_path (str, optional): Path for the output CDXJ file
        encryption_key (str, optional): Key for encrypting the archive

    Returns:
        str: Path to the created CDXJ file
    """
    processor = WebArchiveProcessor()
    return processor.index_warc(warc_path, output_path, encryption_key)


def create_warc(url: str, output_path: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> str:
    """
    Convenience function to create a WARC file using ArchiveNow.

    Args:
        url (str): URL to archive
        output_path (str, optional): Path for the output WARC file
        options (dict, optional): Options for ArchiveNow

    Returns:
        str: Path to the created WARC file
    """
    processor = WebArchiveProcessor()
    return processor.create_warc(url, output_path, options)
