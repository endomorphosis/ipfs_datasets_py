

"""
Comprehensive test fixtures for Web Archive module testing.

This conftest.py file provides reusable fixtures for testing the WebArchive
and WebArchiveProcessor classes. Fixtures are designed following pytest best
practices with clear naming, proper scoping, and comprehensive test data.
"""

# Try to import the file under test's dependencies to ensure they are available.
try:
    import logging
    import os
    import tempfile
    import json
    from typing import Dict, List, Optional, Any
    from datetime import datetime
    from pathlib import Path
    from decimal import Decimal

    from pydantic import HttpUrl

except ImportError as e:
    raise ImportError(f"Required module not found: {e.name}.")

from ipfs_datasets_py.web_archive import (
    WebArchive, 
    WebArchiveProcessor, 
    create_web_archive,
    archive_web_content,
    retrieve_web_content,
)

# Verify module interfaces are available
assert WebArchive.archive_url
assert WebArchive.list_archives
assert WebArchive.mro
assert WebArchive.retrieve_archive

assert WebArchiveProcessor.create_warc
assert WebArchiveProcessor.extract_dataset_from_cdxj
assert WebArchiveProcessor.extract_links_from_warc
assert WebArchiveProcessor.mro
assert WebArchiveProcessor.extract_metadata_from_warc
assert WebArchiveProcessor.extract_text_from_html
assert WebArchiveProcessor.extract_text_from_warc
assert WebArchiveProcessor.index_warc
assert WebArchiveProcessor.process_html_content
assert WebArchiveProcessor.process_urls
assert WebArchiveProcessor.search_archives

import pytest


# Test Constants
@pytest.fixture
def test_constants():
    """Provide common test constants for web archive testing."""
    return {
        # Valid URLs for testing
        'VALID_URL': "https://example.com",
        'ANOTHER_VALID_URL': "https://docs.python.org",
        'VALID_HTTPS_URL': "https://www.github.com",
        'VALID_HTTP_URL': "http://example.org",
        'SUBDOMAIN_URL': "https://api.example.com/v1/data",
        'PATH_URL': "https://example.com/docs/guide.html",
        'QUERY_URL': "https://example.com/search?q=test",
        'FRAGMENT_URL': "https://example.com/page#section1",
        
        # Invalid URLs for testing
        'INVALID_URL': "not-a-url",
        'INVALID_PROTOCOL': "ftp://example.com",
        'MALFORMED_URL': "https://",
        'EMPTY_URL': "",
        'NONE_URL': None,
        
        # Storage paths
        'VALID_STORAGE_PATH': "/tmp/web_archives",
        'ANOTHER_STORAGE_PATH': "/var/cache/archives",
        'RELATIVE_PATH': "./archives",
        'EMPTY_PATH': "",
        'NONE_PATH': None,
        
        # Archive IDs
        'VALID_ARCHIVE_ID': "archive_1",
        'ANOTHER_ARCHIVE_ID': "archive_2",
        'NONEXISTENT_ARCHIVE_ID': "archive_999",
        'INVALID_ARCHIVE_ID': "invalid_id",
        'EMPTY_ARCHIVE_ID': "",
        
        # Metadata
        'BASIC_METADATA': {"category": "documentation"},
        'COMPLEX_METADATA': {
            "category": "documentation",
            "priority": "high", 
            "tags": ["python", "tutorial"],
            "created_by": "test_user"
        },
        'EMPTY_METADATA': {},
        'NONE_METADATA': None,
        
        # HTML content
        'SIMPLE_HTML': "<html><body><h1>Title</h1><p>Content</p></body></html>",
        'COMPLEX_HTML': """
        <html>
            <head><title>Test Page</title></head>
            <body>
                <h1>Main Title</h1>
                <p>Paragraph with <strong>bold</strong> text.</p>
                <div>
                    <a href="https://example.com">Link</a>
                    <img src="image.jpg" alt="Image">
                </div>
                <script>console.log('ignored');</script>
                <style>body { color: red; }</style>
            </body>
        </html>
        """,
        'HTML_WITH_SCRIPTS': """
        <html><body>
            <script>alert('remove me');</script>
            <p>Keep this text</p>
            <style>p { color: blue; }</style>
        </body></html>
        """,
        'EMPTY_HTML': "",
        'MALFORMED_HTML': "<html><body><p>Unclosed paragraph",
        
        # File paths
        'VALID_WARC_PATH': "/tmp/test.warc",
        'VALID_CDXJ_PATH': "/tmp/test.cdxj", 
        'NONEXISTENT_FILE_PATH': "/tmp/nonexistent.warc",
        'VALID_INDEX_PATH': "/tmp/test.idx",
        
        # Misc constants
        'SEARCH_QUERY': "python",
        'ANOTHER_SEARCH_QUERY': "documentation",
        'EMPTY_SEARCH_QUERY': "",
        'OUTPUT_FORMAT_JSON': "json",
        'OUTPUT_FORMAT_CSV': "csv",
        'ENCRYPTION_KEY': "secret_key_123",
    }


# Basic Archive Fixtures
@pytest.fixture
def archive() -> WebArchive:
    """Create a basic WebArchive instance for testing."""
    return WebArchive()


@pytest.fixture
def archive_with_storage_path(test_constants, tmp_path) -> WebArchive:
    """Create a WebArchive instance with a temporary storage path."""
    storage_path = str(tmp_path / "web_archives")
    return WebArchive(storage_path=storage_path)


@pytest.fixture
def archive_with_one_item(archive, test_constants) -> WebArchive:
    """Create a WebArchive instance with one archived item."""
    archive.archive_url(test_constants['VALID_URL'], test_constants['BASIC_METADATA'])
    return archive


@pytest.fixture
def archive_with_two_items(archive_with_one_item, test_constants) -> WebArchive:
    """Create a WebArchive instance with two archived items."""
    archive_with_one_item.archive_url(test_constants['ANOTHER_VALID_URL'], test_constants['COMPLEX_METADATA'])
    return archive_with_one_item


@pytest.fixture
def archive_with_multiple_items(archive, test_constants) -> WebArchive:
    """Create a WebArchive instance with multiple archived items for comprehensive testing."""
    # Archive several different types of URLs
    archive.archive_url(test_constants['VALID_URL'], test_constants['BASIC_METADATA'])
    archive.archive_url(test_constants['ANOTHER_VALID_URL'], test_constants['COMPLEX_METADATA'])
    archive.archive_url(test_constants['SUBDOMAIN_URL'], {"category": "api"})
    archive.archive_url(test_constants['PATH_URL'], {"category": "documentation", "type": "guide"})
    return archive


# Processor Fixtures
@pytest.fixture
def processor() -> WebArchiveProcessor:
    """Create a basic WebArchiveProcessor instance for testing."""
    return WebArchiveProcessor()


@pytest.fixture
def processor_with_archives(processor, test_constants) -> WebArchiveProcessor:
    """Create a WebArchiveProcessor with some archived content."""
    processor.process_urls([
        test_constants['VALID_URL'],
        test_constants['ANOTHER_VALID_URL']
    ])
    return processor


@pytest.fixture
def processor_with_storage_path(test_constants, tmp_path) -> WebArchiveProcessor:
    """Create a WebArchiveProcessor with persistent storage."""
    storage_path = str(tmp_path / "web_archives")
    processor = WebArchiveProcessor()
    # Replace the default archive with one that has storage
    processor.archive = WebArchive(storage_path=storage_path)
    return processor


# File and Path Fixtures
@pytest.fixture
def temp_warc_file(tmp_path, test_constants) -> str:
    """Create a temporary WARC file for testing."""
    warc_path = tmp_path / "test.warc"
    warc_content = f"""WARC/1.0
WARC-Type: response
WARC-Target-URI: {test_constants['VALID_URL']}
WARC-Date: 2024-01-01T00:00:00Z
Content-Length: 100

HTTP/1.1 200 OK
Content-Type: text/html

<html><body>Test content</body></html>
"""
    warc_path.write_text(warc_content)
    return str(warc_path)


@pytest.fixture
def temp_cdxj_file(tmp_path, test_constants) -> str:
    """Create a temporary CDXJ file for testing."""
    cdxj_path = tmp_path / "test.cdxj"
    cdxj_content = f"""com,example)/ 20240101000000 {{"url": "{test_constants['VALID_URL']}", "mime": "text/html", "status": "200"}}
org,python,docs)/ 20240101010000 {{"url": "{test_constants['ANOTHER_VALID_URL']}", "mime": "text/html", "status": "200"}}
"""
    cdxj_path.write_text(cdxj_content)
    return str(cdxj_path)


@pytest.fixture
def temp_output_directory(tmp_path) -> str:
    """Create a temporary directory for output files."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return str(output_dir)


# URL List Fixtures
@pytest.fixture
def valid_url_list(test_constants) -> List[str]:
    """Provide a list of valid URLs for batch testing."""
    return [
        test_constants['VALID_URL'],
        test_constants['ANOTHER_VALID_URL'],
        test_constants['VALID_HTTPS_URL']
    ]


@pytest.fixture
def mixed_url_list(test_constants) -> List[str]:
    """Provide a list mixing valid and invalid URLs for error testing."""
    return [
        test_constants['VALID_URL'],
        test_constants['INVALID_URL'],
        test_constants['ANOTHER_VALID_URL']
    ]


@pytest.fixture
def empty_url_list() -> List[str]:
    """Provide an empty URL list for edge case testing."""
    return []


# HTML Content Fixtures
@pytest.fixture
def sample_html_files(tmp_path, test_constants) -> Dict[str, str]:
    """Create sample HTML files for testing."""
    html_files = {}
    
    # Simple HTML file
    simple_file = tmp_path / "simple.html"
    simple_file.write_text(test_constants['SIMPLE_HTML'])
    html_files['simple'] = str(simple_file)
    
    # Complex HTML file
    complex_file = tmp_path / "complex.html"
    complex_file.write_text(test_constants['COMPLEX_HTML'])
    html_files['complex'] = str(complex_file)
    
    # HTML with scripts
    scripts_file = tmp_path / "with_scripts.html"
    scripts_file.write_text(test_constants['HTML_WITH_SCRIPTS'])
    html_files['with_scripts'] = str(scripts_file)
    
    return html_files


# Mock Data Fixtures
@pytest.fixture
def mock_warc_records() -> List[Dict[str, Any]]:
    """Provide mock WARC record data for testing."""
    return [
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


@pytest.fixture
def mock_warc_metadata() -> Dict[str, Any]:
    """Provide mock WARC metadata for testing."""
    return {
        "filename": "test.warc",
        "file_size": 1024,
        "record_count": 2,
        "creation_date": "2024-01-01T00:00:00Z",
        "warc_version": "1.0",
        "content_types": ["text/html", "application/json"],
        "domains": ["example.com"],
        "total_urls": 2
    }


@pytest.fixture
def mock_link_data() -> List[Dict[str, Any]]:
    """Provide mock link extraction data for testing."""
    return [
        {
            "source_uri": "https://example.com/page1",
            "target_uri": "https://example.com/page2",
            "link_text": "Next page",
            "link_type": "href"
        },
        {
            "source_uri": "https://example.com/page1",
            "target_uri": "https://external-site.com",
            "link_text": "External link",
            "link_type": "href"
        }
    ]


# Error Testing Fixtures
@pytest.fixture
def invalid_inputs() -> Dict[str, Any]:
    """Provide various invalid inputs for error testing."""
    return {
        'non_string_url': 123,
        'none_url': None,
        'empty_url': "",
        'non_dict_metadata': "not_a_dict",
        'non_string_archive_id': 456,
        'non_list_urls': "not_a_list",
        'non_string_html': 789,
    }


# Parameterized Data Fixtures
@pytest.fixture
def url_validation_test_cases(test_constants) -> List[tuple]:
    """Provide test cases for URL validation testing."""
    return [
        # (url, expected_valid, description)
        (test_constants['VALID_URL'], True, "standard https url"),
        (test_constants['VALID_HTTP_URL'], True, "standard http url"),
        (test_constants['SUBDOMAIN_URL'], True, "url with subdomain"),
        (test_constants['PATH_URL'], True, "url with path"),
        (test_constants['QUERY_URL'], True, "url with query parameters"),
        (test_constants['FRAGMENT_URL'], True, "url with fragment"),
        (test_constants['INVALID_URL'], False, "invalid url format"),
        (test_constants['INVALID_PROTOCOL'], False, "unsupported protocol"),
        (test_constants['MALFORMED_URL'], False, "malformed url"),
        (test_constants['EMPTY_URL'], False, "empty url"),
    ]


@pytest.fixture
def metadata_test_cases(test_constants) -> List[tuple]:
    """Provide test cases for metadata testing."""
    return [
        # (metadata, description)
        (test_constants['BASIC_METADATA'], "basic metadata dict"),
        (test_constants['COMPLEX_METADATA'], "complex metadata with multiple types"),
        (test_constants['EMPTY_METADATA'], "empty metadata dict"),
        (test_constants['NONE_METADATA'], "none metadata"),
    ]


@pytest.fixture
def html_extraction_test_cases(test_constants) -> List[tuple]:
    """Provide test cases for HTML text extraction testing."""
    return [
        # (html_content, expected_contains, description)
        (test_constants['SIMPLE_HTML'], "Title Content", "simple html extraction"),
        (test_constants['HTML_WITH_SCRIPTS'], "Keep this text", "html with scripts removed"),
        (test_constants['COMPLEX_HTML'], "Main Title", "complex html structure"),
        (test_constants['EMPTY_HTML'], "", "empty html content"),
    ]
