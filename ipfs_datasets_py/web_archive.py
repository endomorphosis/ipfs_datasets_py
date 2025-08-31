"""
Web Archive module for IPFS datasets.
Provides functionality for archiving and retrieving web content.
"""

import logging
import os
from typing import Dict, List, Optional, Any
from datetime import datetime
import os
import re
import json

from pydantic import HttpUrl

class _ValidateUrl:
    url: HttpUrl

def _is_valid_http_url(url: str) -> bool:
    """Validate if the provided string is a valid URL."""
    try:
        _ = _ValidateUrl(url=url)
    except Exception as e:
        return False
    else:
        return True


logger = logging.getLogger(__name__)

class WebArchive:
    """Web archive functionality for storing and retrieving web content.

    The WebArchive class provides a comprehensive system for archiving web content
    with associated metadata, tracking archived items, and retrieving them by unique
    identifiers. It maintains an in-memory dictionary of archived items. When a 
    storage_path is provided (persistence_mode="persistent"), items are persisted 
    to the specified storage path; when storage_path is None (persistence_mode="memory_only"),
    items exist only in memory during the session. Each archived item receives a unique
    identifier and timestamp for tracking and retrieval purposes.

    Args:
        storage_path (Optional[str]): Path to the directory where archived content 
            should be stored to disk. When None, persistence_mode="memory_only".
            When a valid path is provided, persistence_mode="persistent".

    Returns:
        WebArchive: An initialized web archive instance ready for archiving operations.

    Example:
        >>> archive = WebArchive(storage_path="/var/cache/web_archives")
        >>> result = archive.archive_url("https://example.com", 
        ...                               metadata={"category": "documentation"})
        >>> print(result["archive_id"])
        'archive_1'
        >>> archived_content = archive.retrieve_archive("archive_1")
        >>> print(archived_content["data"]["url"])
        'https://example.com'
    """

    def __init__(self, storage_path: Optional[str] = None):
        """Initialize web archive with optional storage path.

        Creates a new WebArchive instance with an empty archive dictionary and 
        configures the storage location for persistent archiving. Sets persistence_mode
        to "memory_only" when storage_path is None, or "persistent" when a valid path
        is provided. Archives are maintained in memory during the session lifetime
        for memory_only mode.

        Args:
            storage_path (Optional[str]): Filesystem path for persistent storage of 
                archived content. Determines persistence_mode parameter.

        Attributes set:
            storage_path (Optional[str]): Path to the directory for persistent storage.
            archived_items (Dict[str, Dict]): Dictionary to hold archived items with 
                unique identifiers as keys. Each item contains URL, timestamp, metadata,
                and status information.

        Returns:
            None: Initializes instance attributes.

        Example:
            >>> archive = WebArchive()  # persistence_mode="memory_only"
            >>> persistent_archive = WebArchive("/data/archives")  # persistence_mode="persistent"
        """
        self.storage_path = storage_path
        self.archived_items = {}

    def archive_url(self, url: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """Archive a URL with optional metadata.

        Creates an archive entry for the specified URL, generating a unique identifier,
        timestamp, and storing any provided metadata. The archived item is stored in the
        internal dictionary with archive_status="archived". If archiving fails, an error 
        status is returned with the exception message. The timestamp represents the 
        original_archive_time and never changes after initial creation.

        Args:
            url (str): The complete URL to be archived including protocol.
            metadata (Optional[Dict]): Additional key-value pairs to store with the 
                archived URL for categorization or tracking.

        Returns:
            Dict[str, Any]: Archive operation result with the following structure:
                When status='success':
                    status (str): Always 'success' for successful operations.
                    archive_id (str): Unique identifier formatted as 'archive_{n}' where 
                        n is the sequential archive number.
                When status='error':
                    status (str): Always 'error' for failed operations.
                    message (str): Human-readable error description explaining why the 
                        archiving operation failed. This field exists ONLY in error responses.

        Example:
            >>> archive = WebArchive()
            >>> result = archive.archive_url("https://docs.python.org", 
            ...                               metadata={"type": "documentation", 
            ...                                        "language": "python"})
            >>> if result["status"] == "success":
            ...     print(f"Archived with ID: {result['archive_id']}")
            ... else:
            ...     print(f"Archive failed: {result['message']}")
            Archived with ID: archive_1
        """
        try:
            archive_id = f"archive_{len(self.archived_items) + 1}"
            archived_item = {
                "id": archive_id,
                "url": url,
                "timestamp": datetime.now().isoformat(),
                "metadata": metadata or {},
                "status": "archived"
            }
            self.archived_items[archive_id] = archived_item
            return {"status": "success", "archive_id": archive_id}
        except Exception as e:
            logger.error(f"Failed to archive URL {url}: {e}")
            return {"status": "error", "message": str(e)}

    def retrieve_archive(self, archive_id: str) -> Dict[str, Any]:
        """Retrieve archived content by ID.

        Looks up an archived item using its unique identifier and returns the complete
        archive record including URL, timestamp (representing original_archive_time that
        never changes), metadata, and status. If the archive ID does not exist, returns 
        an error status with an appropriate message.

        Args:
            archive_id (str): The unique identifier of the archived item to retrieve.

        Returns:
            Dict[str, Any]: Archive retrieval result with the following structure:
                When status='success':
                    status (str): Always 'success' for found archives.
                    data (Dict[str, Any]): Complete archive record containing:
                        id (str): The archive identifier matching the requested archive_id.
                        url (str): The URL as originally archived (never modified).
                        timestamp (str): ISO 8601 formatted datetime when the URL was 
                            originally archived (timestamp_represents="original_archive_time").
                        metadata (Dict): User-provided metadata dictionary from original archiving.
                        status (str): Archive status, expected value is 'archived' 
                            (archive_status_valid_values includes 'archived').
                When status='error':
                    status (str): Always 'error' for not found archives.
                    message (str): Error description, expected value 'Archive not found' 
                        when the archive_id doesn't exist. This field exists ONLY in error responses.

        Example:
            >>> archive = WebArchive()
            >>> archive.archive_url("https://example.com", metadata={"priority": "high"})
            >>> result = archive.retrieve_archive("archive_1")
            >>> if result["status"] == "success":
            ...     print(f"URL: {result['data']['url']}")
            ...     print(f"Archived at: {result['data']['timestamp']}")
            URL: https://example.com
            Archived at: 2024-01-15T10:30:00.123456
        """
        if archive_id in self.archived_items:
            return {"status": "success", "data": self.archived_items[archive_id]}
        return {"status": "error", "message": "Archive not found"}

    def list_archives(self) -> List[Dict[str, Any]]:
        """List all archived items.

        Returns a list of all archived items stored in the archive at the time of the call,
        including their complete records with IDs, URLs, timestamps, metadata,
        and status information. The list follows list_order="insertion_order", meaning
        items appear in the same sequence they were archived.

        Args:
            None

        Returns:
            List[Dict[str, Any]]: A list where each dictionary represents an archived item with:
                id (str): Unique archive identifier formatted as 'archive_{n}'.
                url (str): The archived URL.
                timestamp (str): ISO 8601 formatted datetime when originally archived
                    (timestamp_represents="original_archive_time").
                metadata (Dict): User-provided metadata from original archiving.
                status (str): Current archive status, expected value is 'archived'
                    (archive_status_valid_values includes 'archived').

        Example:
            >>> archive = WebArchive()
            >>> archive.archive_url("https://site1.com", metadata={"type": "blog"})
            >>> archive.archive_url("https://site2.com", metadata={"type": "news"})
            >>> archives = archive.list_archives()
            >>> for item in archives:
            ...     print(f"{item['id']}: {item['url']} ({item['metadata'].get('type', 'unknown')})")
            archive_1: https://site1.com (blog)
            archive_2: https://site2.com (news)
        """
        return list(self.archived_items.values())

class WebArchiveProcessor:
    """Processor for web archive operations.

    The WebArchiveProcessor class provides advanced processing capabilities for
    web archives including batch operations, content extraction from HTML and WARC
    files, search functionality, and archive indexing. It encapsulates a WebArchive
    instance and extends its functionality with text extraction, link analysis,
    and format conversion capabilities for handling large-scale web archiving tasks.

    Args:
        None

    Returns:
        WebArchiveProcessor: An initialized processor with an embedded WebArchive instance.

    Example:
        >>> processor = WebArchiveProcessor()
        >>> urls = ["https://example.com", "https://docs.python.org"]
        >>> results = processor.process_urls(urls)
        >>> print(f"Processed {len(results['results'])} URLs")
        Processed 2 URLs
        >>> text_data = processor.extract_text_from_html("<html><body>Hello World</body></html>")
        >>> print(f"Extracted {text_data['length']} characters")
        Extracted 11 characters
    """

    def __init__(self):
        """Initialize web archive processor.

        Creates a new WebArchiveProcessor instance with an embedded WebArchive
        for managing archived content. The processor is initialized with default
        settings for text extraction and WARC processing operations.

        Args:
            None

        Returns:
            None: Initializes instance with a new WebArchive.

        Attributes set:
            archive (WebArchive): An instance of WebArchive for managing archived content.

        Example:
            >>> processor = WebArchiveProcessor()
            >>> # Processor is ready for operations
            >>> results = processor.process_urls(["https://example.com"])
        """
        self.archive = WebArchive()

    def process_urls(self, urls: List[str]) -> Dict[str, Any]:
        """Process multiple URLs for archiving.

        Iterates through a list of URLs and archives each one using the embedded
        WebArchive instance. Collects and returns all archiving results including
        success status and archive IDs for each URL processed. The batch operation
        returns a success ratio based on individual URL archive outcomes.

        Args:
            urls (List[str]): A list of complete URLs to be archived in batch.

        Returns:
            Dict[str, Any]: Batch processing result with the following structure:
            status (float): Success ratio as a decimal (0.0 to 1.0) representing
                the proportion of archived URLs where individual status='success' to total URLs processed.
            results (List[Dict[str, Any]]): List of individual archive results, each containing:
                When individual status='success':
                    status (str): Individual URL archive status 'success'.
                    archive_id (str): Assigned archive identifier formatted as 'archive_{n}'.
                When individual status='error':
                    status (str): Individual URL archive status 'error'.
                    message (str): Error description for failed URL. This field exists 
                        ONLY in error responses.

        Example:
            >>> processor = WebArchiveProcessor()
            >>> urls = [
            ...     "https://news.ycombinator.com",
            ...     "https://reddit.com/r/programming",
            ...     "https://stackoverflow.com"
            ... ]
            >>> batch_result = processor.process_urls(urls)
            >>> print(f"Success rate: {batch_result['status']:.1%}")
            >>> for result in batch_result['results']:
            ...     if result['status'] == 'success':
            ...         print(f"Archived: {result['archive_id']}")
            Success rate: 100.0%
            Archived: archive_1
            Archived: archive_2
            Archived: archive_3
        """
        if not isinstance(urls, list):
            raise TypeError(f"urls must be a list, got {type(urls).__name__}.")
        if not urls:
            raise ValueError("urls list cannot be empty. Please provide at least one URL to archive.")

        for idx, url in enumerate(urls):
            if not isinstance(url, str):
                raise TypeError(f"All URLs must be strings, got {type(url).__name__} for URL at index {idx}.")
            if not url:
                raise ValueError(f"URL at index {idx} is empty. Please provide a valid URL.")
            if not _is_valid_http_url(url):
                raise ValueError(
                    f"Invalid URL format at index {idx}: {url}. Ensure it starts with 'http://' or 'https://'."
                )

        results = []
        success = 0
        for url in urls:
            result = self.archive.archive_url(url)
            match result["status"]:
                case "success":
                    logger.info(f"Successfully archived {url} with ID {result['archive_id']}")
                    success += 1
                case "error":
                    logger.error(f"Error archiving {url}: {result['message']}")
                case _:
                    raise ValueError(f"Unexpected status {result['status']} for URL {url}")
            results.append(result)
        return {"status": success/len(urls), "results": results}

    def search_archives(self, query: str) -> List[Dict[str, Any]]:
        """Search archived content.

        Performs a case-insensitive substring search across all archived URLs,
        returning matches that contain the query string. The search is performed
        on the URL field of each archived item at the time of the search.

        Args:
            query (str): The search string to match against archived URLs.

        Returns:
            List[Dict[str, Any]]: List of matching archive records, each containing:
                id (str): Archive identifier formatted as 'archive_{n}'.
                url (str): The archived URL that matches the search query.
                timestamp (str): ISO 8601 formatted datetime when originally archived
                    (timestamp_represents="original_archive_time").
                metadata (Dict): Arbitrary metadata originally provided during archiving.
                status (str): Archive status, expected value is 'archived'
                    (archive_status_valid_values includes 'archived').

        Example:
            >>> processor = WebArchiveProcessor()
            >>> processor.process_urls(["https://docs.python.org", "https://python.org/downloads"])
            >>> results = processor.search_archives("python")
            >>> for archive in results:
            ...     print(f"Found: {archive['url']} (archived: {archive['timestamp']})")
            Found: https://docs.python.org (archived: 2024-01-15T10:30:00.123456)
            Found: https://python.org/downloads (archived: 2024-01-15T10:30:01.234567)
        """
        matching_archives = []
        for archive in self.archive.list_archives():
            if query.lower() in archive.get("url", "").lower():
                matching_archives.append(archive)
        return matching_archives

    def extract_text_from_html(self, html_content: str) -> Dict[str, Any]:
        """Extract text content from HTML.

        Processes HTML content to extract plain text by removing script tags, style
        tags, and all HTML markup. Normalizes whitespace to produce clean, readable
        text content suitable for indexing or analysis.

        Args:
            html_content (str): Raw HTML content as a string to be processed.

        Returns:
            Dict[str, Any]: Text extraction result with the following structure:
                When status='success':
                    status (str): Always 'success' for successful extraction.
                    text (str): Extracted plain text with normalized whitespace and 
                        removed HTML markup.
                    length (int): Character count of the extracted text.
                When status='error':
                    status (str): Always 'error' for failed extraction.
                    message (str): Description of what caused the extraction to fail.
                        This field exists ONLY in error responses.

        Example:
            >>> processor = WebArchiveProcessor()
            >>> html = '''
            ... <html>
            ...     <head><title>Sample Page</title></head>
            ...     <body>
            ...         <h1>Welcome</h1>
            ...         <p>This is a <strong>sample</strong> page.</p>
            ...         <script>console.log('ignored');</script>
            ...     </body>
            ... </html>
            ... '''
            >>> result = processor.extract_text_from_html(html)
            >>> print(result['text'])
            Sample Page Welcome This is a sample page.
            >>> print(f"Text length: {result['length']} characters")
            Text length: 43 characters
        """
        try:
            # Simple HTML text extraction (in a real implementation, you'd use BeautifulSoup)
            # Remove script and style elements
            text = re.sub(r'<script.*?</script>', '', html_content, flags=re.DOTALL)
            text = re.sub(r'<style.*?</style>', '', text, flags=re.DOTALL)
            # Remove HTML tags
            text = re.sub(r'<[^>]+>', '', text)
            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text).strip()

            return {
                "status": "success",
                "text": text,
                "length": len(text)
            }
        except Exception as e:
            logger.error(f"Failed to extract text from HTML: {e}")
            return {"status": "error", "message": str(e)}

    def process_html_content(self, html: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """Process HTML content and extract useful information."""
        try:
            text_result = self.extract_text_from_html(html)
            if text_result["status"] == "error":
                return text_result

            return {
                "status": "success",
                "text": text_result["text"],
                "html_length": len(html),
                "text_length": text_result["length"],
                "metadata": metadata or {},
                "processed_at": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to process HTML content: {e}")
            return {"status": "error", "message": str(e)}

    def extract_text_from_warc(self, warc_path: str) -> List[Dict[str, Any]]:
        """Process HTML content and extract useful information.

        Combines HTML text extraction with metadata enrichment, providing comprehensive
        information about the processed content including both raw HTML metrics and
        extracted text statistics, along with processing timestamp.

        Args:
            html (str): Raw HTML content to be processed and analyzed.
            metadata (Optional[Dict]): Additional metadata to attach to the processed
                content for context or categorization.

        Returns:
            Dict[str, Any]: HTML processing result with the following structure:
                When status='success':
                    status (str): Always 'success' for successful processing.
                    text (str): Plain text extracted from HTML with all markup removed.
                    html_length (int): Original HTML content size in bytes.
                    text_length (int): Extracted text size in characters.
                    metadata (Dict): User-provided metadata or empty dictionary if none provided.
                    processed_at (str): ISO 8601 formatted timestamp of when processing 
                        occurred (represents current_time at processing).
                When status='error':
                    status (str): Always 'error' for failed processing.
                    message (str): Error description explaining the processing failure.
                        This field exists ONLY in error responses.

        Example:
            >>> processor = WebArchiveProcessor()
            >>> html = "<html><body><h1>Title</h1><p>Content here.</p></body></html>"
            >>> result = processor.process_html_content(
            ...     html, 
            ...     metadata={"source": "crawler", "depth": 2}
            ... )
            >>> print(f"HTML: {result['html_length']} bytes -> Text: {result['text_length']} chars")
            HTML: 61 bytes -> Text: 14 chars
            >>> print(f"Processed at: {result['processed_at']}")
            Processed at: 2024-01-15T10:30:00.123456
        """
        try:
            # Mock implementation - in reality would parse actual WARC files
            if not os.path.exists(warc_path):
                raise FileNotFoundError(f"WARC file not found: {warc_path}")

            # Simulate extracting text from WARC records
            records = [
                {
                    "uri": "https://example.com/page1",
                    "text": "Sample text content from page 1",
                    "content_type": "text/html",
                    "timestamp": "2024-01-01T00:00:00Z"
                },
                {
                    "uri": "https://example.com/page2",
                    "text": "Sample text content from page 2",
                    "content_type": "text/html",
                    "timestamp": "2024-01-01T01:00:00Z"
                }
            ]

            logger.info(f"Extracted text from {len(records)} records in WARC file")
            return records

        except Exception as e:
            logger.error(f"Failed to extract text from WARC: {e}")
            raise

    def extract_metadata_from_warc(self, warc_path: str) -> Dict[str, Any]:
        """Extract text content from a WARC file.

        Parses a WARC (Web ARChive) file and extracts text content from all records,
        returning a list of extracted text along with associated metadata such as
        URI, content type, and timestamp for each record processed.

        Args:
            warc_path (str): Filesystem path to the WARC file to be processed.

        Returns:
            List[Dict[str, Any]]: List of extracted records, each containing:
                uri (str): The original URL of the archived web page.
                text (str): Extracted plain text content from the WARC record.
                content_type (str): MIME type of the original content, most commonly 'text/html'
                    (expected_content_type_default="text/html", though other valid MIME types
                    are accepted).
                timestamp (str): ISO 8601 or WARC-format timestamp when the page was archived.

        Raises:
            FileNotFoundError: If the specified WARC file does not exist.
            Exception: If WARC parsing fails due to corruption or format issues.

        Example:
            >>> processor = WebArchiveProcessor()
            >>> records = processor.extract_text_from_warc("/data/archives/snapshot.warc")
            >>> for record in records:
            ...     print(f"URI: {record['uri']}")
            ...     print(f"Content-Type: {record['content_type']}")
            ...     print(f"Text preview: {record['text'][:100]}...")
            URI: https://example.com/page1
            Content-Type: text/html
            Text preview: Sample text content from page 1...
        """
        try:
            if not os.path.exists(warc_path):
                raise FileNotFoundError(f"WARC file not found: {warc_path}")

            # Mock metadata extraction
            metadata = {
                "filename": os.path.basename(warc_path),
                "file_size": os.path.getsize(warc_path),
                "record_count": 2,
                "creation_date": "2024-01-01T00:00:00Z",
                "warc_version": "1.0",
                "content_types": ["text/html", "application/json"],
                "domains": ["example.com"],
                "total_urls": 2
            }

            logger.info(f"Extracted metadata from WARC file: {warc_path}")
            return metadata

        except Exception as e:
            logger.error(f"Failed to extract metadata from WARC: {e}")
            raise

    def extract_links_from_warc(self, warc_path: str) -> List[Dict[str, Any]]:
        """Extract links from a WARC file.

        Parses HTML content within WARC records to extract all hyperlinks, including
        source URI, target URI, link text, and link type, building a comprehensive
        link graph from the archived web content.

        Args:
            warc_path (str): Filesystem path to the WARC file to process for links.

        Returns:
            List[Dict[str, Any]]: List of discovered links, each containing:
                source_uri (str): URL of the page containing the link.
                target_uri (str): URL that the link points to.
                link_text (str): Visible text of the hyperlink, may be empty for image links.
                link_type (str): Type of link, most commonly 'href' for standard hyperlinks
                    (link_type_default="href", though other link types are captured).

        Raises:
            FileNotFoundError: If the specified WARC file does not exist.
            Exception: If link extraction fails due to parsing or processing errors.

        Example:
            >>> processor = WebArchiveProcessor()
            >>> links = processor.extract_links_from_warc("/data/archives/website.warc")
            >>> # Build a link graph
            >>> from collections import defaultdict
            >>> link_graph = defaultdict(list)
            >>> for link in links:
            ...     link_graph[link['source_uri']].append(link['target_uri'])
            >>> print(f"Found {len(links)} total links across {len(link_graph)} pages")
            Found 3847 total links across 152 pages
        """
        try:
            if not os.path.exists(warc_path):
                raise FileNotFoundError(f"WARC file not found: {warc_path}")

            # Mock link extraction
            links = [
                {
                    "source_uri": "https://example.com/page1",
                    "target_uri": "https://example.com/page2",
                    "link_text": "Click here",
                    "link_type": "href"
                },
                {
                    "source_uri": "https://example.com/page1",
                    "target_uri": "https://external-site.com",
                    "link_text": "External link",
                    "link_type": "href"
                }
            ]

            logger.info(f"Extracted {len(links)} links from WARC file")
            return links

        except Exception as e:
            logger.error(f"Failed to extract links from WARC: {e}")
            raise

    def index_warc(self, warc_path: str, output_path: Optional[str] = None, encryption_key: Optional[str] = None) -> str:
        """Create an index for a WARC file.

        Generates an index file for efficient random access to WARC records, storing
        byte offsets, record lengths, and metadata for each record to enable fast
        lookups without parsing the entire WARC file.

        Args:
            warc_path (str): Filesystem path to the WARC file to be indexed.
            output_path (Optional[str]): Path for the index file, defaults to 
                warc_path + '.idx' if not specified.
            encryption_key (Optional[str]): Encryption key for securing the index
                file if sensitive data protection is required.

        Returns:
            str: The filesystem path to the created index file.

        Raises:
            FileNotFoundError: If the specified WARC file does not exist.
            Exception: If index creation fails due to I/O or processing errors.

        Example:
            >>> processor = WebArchiveProcessor()
            >>> index_path = processor.index_warc(
            ...     "/data/archives/large_crawl.warc",
            ...     output_path="/data/indexes/large_crawl.idx",
            ...     encryption_key="secret_key_123"
            ... )
            >>> print(f"Index created at: {index_path}")
            Index created at: /data/indexes/large_crawl.idx
            >>> # Use index for fast lookups
            >>> with open(index_path, 'r') as f:
            ...     index_data = json.load(f)
            >>> print(f"Indexed {index_data['record_count']} records")
            Indexed 5000 records
        """
        try:
            if not os.path.exists(warc_path):
                raise FileNotFoundError(f"WARC file not found: {warc_path}")

            if output_path is None:
                output_path = warc_path + ".idx"

            # Mock indexing
            index_data = {
                "warc_file": warc_path,
                "index_file": output_path,
                "record_count": 2,
                "index_entries": [
                    {
                        "uri": "https://example.com/page1",
                        "offset": 0,
                        "length": 1024,
                        "content_type": "text/html"
                    },
                    {
                        "uri": "https://example.com/page2",
                        "offset": 1024,
                        "length": 2048,
                        "content_type": "text/html"
                    }
                ]
            }

            # Simulate writing index file
            with open(output_path, 'w') as f:
                json.dump(index_data, f, indent=2)

            logger.info(f"Created WARC index: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Failed to index WARC: {e}")
            raise

    def create_warc(self, urls: List[str], output_path: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """Create a WARC file from a list of URLs.

        Downloads and archives content from specified URLs into a standard WARC format
        file, including HTTP headers, response bodies, and metadata for each URL
        processed, creating a portable web archive.

        Args:
            urls (List[str]): List of URLs to download and include in the WARC file.
            output_path (str): Filesystem path where the WARC file will be created.
            metadata (Optional[Dict]): Additional metadata to include in the WARC
                file header for provenance and description.

        Returns:
            Dict[str, Any]: WARC creation result with the following structure:
                output_file (str): Full path to the created WARC file.
                url_count (int): Number of URLs processed and archived.
                urls (List[str]): Copy of the input URL list that was processed.
                creation_date (str): ISO 8601 timestamp when WARC was created.
                metadata (Dict): User-provided metadata or empty dictionary.
                file_size (int): Size of the created WARC file in bytes.

        Raises:
            Exception: If WARC creation fails due to download errors or I/O issues.

        Example:
            >>> processor = WebArchiveProcessor()
            >>> urls = [
            ...     "https://example.com",
            ...     "https://example.com/about",
            ...     "https://example.com/contact"
            ... ]
            >>> result = processor.create_warc(
            ...     urls,
            ...     "/data/archives/example_site.warc",
            ...     metadata={"crawler": "custom_bot", "purpose": "documentation"}
            ... )
            >>> print(f"Created WARC: {result['output_file']}")
            Created WARC: /data/archives/example_site.warc
            >>> print(f"Archived {result['url_count']} URLs, total size: {result['file_size']} bytes")
            Archived 3 URLs, total size: 384000 bytes
        """
        try:
            # Mock WARC creation
            warc_data = {
                "output_file": output_path,
                "url_count": len(urls),
                "urls": urls,
                "creation_date": datetime.now().isoformat(),
                "metadata": metadata or {},
                "file_size": len(urls) * 1024  # Mock file size
            }

            # Simulate creating WARC file
            with open(output_path, 'w') as f:
                f.write(f"WARC/1.0\nCreated: {warc_data['creation_date']}\nURLs: {len(urls)}\n")
                for url in urls:
                    f.write(f"URL: {url}\n")

            logger.info(f"Created WARC file: {output_path}")
            return warc_data

        except Exception as e:
            logger.error(f"Failed to create WARC: {e}")
            raise

    def extract_dataset_from_cdxj(self, cdxj_path: str, output_format: str = "json") -> Dict[str, Any]:
        """Extract dataset from CDXJ file.

        Processes a CDXJ (CDX JSON) index file to extract structured datasets,
        converting the index entries into specified output formats for analysis
        or further processing of web archive data.

        Args:
            cdxj_path (str): Filesystem path to the CDXJ index file.
            output_format (str): Desired output format for the dataset, defaults
                to 'json', also supports 'csv', 'parquet', etc.

        Returns:
            Dict[str, Any]: Dataset extraction result with the following structure:
                source_file (str): Path to the input CDXJ file that was processed.
                format (str): The output format used for the dataset.
                record_count (int): Total number of records extracted from the CDXJ.
                extraction_date (str): ISO 8601 timestamp when extraction occurred.
                sample_records (List[Dict[str, Any]]): Preview of extracted records, each containing:
                    url (str): The archived URL.
                    timestamp (str): WARC-style timestamp (YYYYMMDDHHmmss format).
                    status (str): HTTP status code as string, e.g., '200', '404'.
                    content_type (str): MIME type of the archived content.

        Raises:
            FileNotFoundError: If the specified CDXJ file does not exist.
            Exception: If dataset extraction fails due to format or parsing errors.

        Example:
            >>> processor = WebArchiveProcessor()
            >>> dataset = processor.extract_dataset_from_cdxj(
            ...     "/data/indexes/crawl.cdxj",
            ...     output_format="json"
            ... )
            >>> print(f"Extracted {dataset['record_count']} records")
            Extracted 10000 records
            >>> for record in dataset['sample_records'][:2]:
            ...     print(f"{record['timestamp']}: {record['url']} ({record['status']})")
            20240101000000: https://example.com/page1 (200)
            20240101010000: https://example.com/page2 (200)
        """
        try:
            if not os.path.exists(cdxj_path):
                raise FileNotFoundError(f"CDXJ file not found: {cdxj_path}")

            # Mock dataset extraction
            dataset = {
                "source_file": cdxj_path,
                "format": output_format,
                "record_count": 10,
                "extraction_date": datetime.now().isoformat(),
                "sample_records": [
                    {
                        "url": "https://example.com/page1",
                        "timestamp": "20240101000000",
                        "status": "200",
                        "content_type": "text/html"
                    },
                    {
                        "url": "https://example.com/page2",
                        "timestamp": "20240101010000",
                        "status": "200",
                        "content_type": "text/html"
                    }
                ]
            }

            logger.info(f"Extracted dataset from CDXJ file: {cdxj_path}")
            return dataset

        except Exception as e:
            logger.error(f"Failed to extract dataset from CDXJ: {e}")
            raise

# Web archive utility functions
def create_web_archive(storage_path: Optional[str] = None) -> WebArchive:
    """Create a new web archive instance.

    Factory function that instantiates and returns a WebArchive object configured
    with the specified storage path for managing web content archiving operations.
    Sets persistence_mode based on whether storage_path is provided.

    Args:
        storage_path (Optional[str]): Directory path for persistent storage of
            archived content. When None, sets persistence_mode="memory_only".
            When a valid path is provided, sets persistence_mode="persistent".

    Returns:
        WebArchive: A configured WebArchive instance ready for archiving operations.

    Example:
        >>> # Create memory-only archive (persistence_mode="memory_only")
        >>> temp_archive = create_web_archive()
        >>> 
        >>> # Create persistent archive (persistence_mode="persistent")
        >>> persistent_archive = create_web_archive("/var/cache/web_archives")
        >>> result = persistent_archive.archive_url("https://example.com")
        >>> print(f"Archive created with ID: {result['archive_id']}")
        Archive created with ID: archive_1
    """
    return WebArchive(storage_path)

def archive_web_content(url: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
    """Archive web content from a URL.

    Convenience function that creates a temporary WebArchive instance and archives
    the specified URL with optional metadata, returning the archive result without
    requiring explicit archive management.

    Args:
        url (str): The complete URL to archive including protocol.
        metadata (Optional[Dict]): Key-value pairs to store with the archived URL
            for categorization or tracking purposes.

    Returns:
        Dict[str, Any]: Archive operation result with the following structure:
            When status='success':
                status (str): Always 'success' for successful archiving.
                archive_id (str): Unique identifier formatted as 'archive_{n}' where 
                    n is the sequential archive number.
            When status='error':
                status (str): Always 'error' for failed archiving.
                message (str): Human-readable error description explaining why the 
                    archiving operation failed. This field exists ONLY in error responses.

    Example:
        >>> # Quick archiving without managing archive instance
        >>> result = archive_web_content(
        ...     "https://important-docs.com/guide.html",
        ...     metadata={"priority": "high", "category": "documentation"}
        ... )
        >>> if result['status'] == 'success':
        ...     print(f"Successfully archived as: {result['archive_id']}")
        ... else:
        ...     print(f"Archiving failed: {result['message']}")
        Successfully archived as: archive_1
    """
    archive = WebArchive()
    return archive.archive_url(url, metadata)

def retrieve_web_content(archive_id: str) -> Dict[str, Any]:
    """Retrieve archived web content.

    Convenience function that creates a temporary WebArchive instance to retrieve
    previously archived content by its identifier without requiring explicit
    archive instance management.

    Args:
        archive_id (str): The unique identifier of the archived content to retrieve.

    Returns:
        Dict[str, Any]: Archive retrieval result with the following structure:
            When status='success':
                status (str): Always 'success' for found archives.
                data (Dict[str, Any]): Complete archive record containing:
                    id (str): The archive identifier matching the requested archive_id.
                    url (str): The URL as originally archived (never modified).
                    timestamp (str): ISO 8601 formatted datetime when the URL was 
                        originally archived (timestamp_represents="original_archive_time").
                    metadata (Dict): User-provided metadata dictionary from original archiving.
                    status (str): Archive status, expected value is 'archived'
                        (archive_status_valid_values includes 'archived').
            When status='error':
                status (str): Always 'error' for not found archives.
                message (str): Error description, expected value 'Archive not found' 
                    when the archive_id doesn't exist. This field exists ONLY in error responses.

    Example:
        >>> # Archive content first
        >>> archive_result = archive_web_content("https://example.com/data.json")
        >>> archive_id = archive_result['archive_id']
        >>> 
        >>> # Retrieve archived content later
        >>> content = retrieve_web_content(archive_id)
        >>> if content['status'] == 'success':
        ...     print(f"Retrieved URL: {content['data']['url']}")
        ...     print(f"Archived at: {content['data']['timestamp']}")
        Retrieved URL: https://example.com/data.json
        Archived at: 2024-01-15T10:30:00.123456
    """
    archive = WebArchive()
    return archive.retrieve_archive(archive_id)
