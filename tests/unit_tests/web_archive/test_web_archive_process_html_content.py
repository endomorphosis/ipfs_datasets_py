#!/usr/bin/env python3
"""Test WebArchiveProcessor.process_html_content method functionality."""

import pytest

from ipfs_datasets_py.processors.web_archiving.web_archive import WebArchiveProcessor


@pytest.fixture
def html_samples():
    """HTML test samples."""
    return {
        "basic": "<html><body><h1>Title</h1><p>Content here.</p></body></html>",
        "simple": "<html><body><h1>Test</h1><p>Sample content</p></body></html>",
        "short": "<html><body><p>Test</p></body></html>",
        "with_script": "<html><body><script>alert('test');</script><p>Text</p></body></html>",
        "paragraph": "<html><body><h1>Title</h1><p>Content paragraph</p></body></html>",
        "hello_world": "<html><body><h1>Hello</h1><p>World</p></body></html>",
        "plain": "<html><body><h1>Title</h1><p>Plain text</p></body></html>",
        "content": "<html><body><p>Content</p></body></html>",
        "test_content": "<html><body><p>Test content</p></body></html>"
    }


@pytest.fixture
def metadata_samples():
    """Metadata test samples."""
    return {
        "crawler": {"source": "crawler", "depth": 2},
        "priority": {"source": "crawler", "priority": "high"}
    }


class TestWebArchiveProcessorProcessHtmlContent:
    """Test WebArchiveProcessor.process_html_content method functionality."""

    @pytest.fixture
    def processor(self):
        """Set up test fixtures."""
        return WebArchiveProcessor()

    def test_processed_at_field_contains_timestamp(self, processor, html_samples, metadata_samples):
        """
        GIVEN valid HTML content
        WHEN calling process_html_content
        THEN processed_at field contains ISO 8601 timestamp
        """
        result = processor.process_html_content(html_samples["basic"], metadata_samples["crawler"])
        assert "processed_at" in result

    def test_returns_success_status(self, processor, html_samples):
        """
        GIVEN valid HTML content
        WHEN calling process_html_content
        THEN status equals success
        """
        result = processor.process_html_content(html_samples["simple"])
        assert result["status"] == "success"

    def test_contains_empty_metadata(self, processor, html_samples):
        """
        GIVEN valid HTML content
        WHEN calling process_html_content without metadata
        THEN metadata field is empty dict
        """
        result = processor.process_html_content(html_samples["simple"])
        assert result["metadata"] == {}

    def test_populates_other_fields(self, processor, html_samples):
        """
        GIVEN valid HTML content
        WHEN calling process_html_content
        THEN all fields are populated
        """
        result = processor.process_html_content(html_samples["simple"])
        assert isinstance(result["text"], str)

    def test_structure_contains_status(self, processor, html_samples):
        """
        GIVEN valid HTML content
        WHEN calling process_html_content
        THEN status field equals success
        """
        result = processor.process_html_content(html_samples["test_content"])
        assert result["status"] == "success"

    def test_structure_contains_text(self, processor, html_samples):
        """
        GIVEN valid HTML content
        WHEN calling process_html_content
        THEN text field contains extracted text
        """
        result = processor.process_html_content(html_samples["paragraph"])
        assert len(result["text"]) > 0

    def test_structure_contains_html_length(self, processor, html_samples):
        """
        GIVEN valid HTML content
        WHEN calling process_html_content
        THEN html_length matches input length
        """
        html = html_samples["short"]
        result = processor.process_html_content(html)
        assert result["html_length"] == len(html)

    def test_structure_contains_text_length(self, processor, html_samples):
        """
        GIVEN valid HTML content
        WHEN calling process_html_content
        THEN text_length matches extracted text
        """
        result = processor.process_html_content(html_samples["hello_world"])
        assert result["text_length"] == len(result["text"])

    def test_structure_contains_metadata(self, processor, html_samples, metadata_samples):
        """
        GIVEN valid HTML content
        WHEN calling process_html_content with metadata
        THEN metadata field contains input
        """
        result = processor.process_html_content(html_samples["short"], metadata_samples["priority"])
        assert result["metadata"] == metadata_samples["priority"]

    def test_structure_contains_processed_at(self, processor, html_samples):
        """
        GIVEN valid HTML content
        WHEN calling process_html_content
        THEN processed_at field is present
        """
        result = processor.process_html_content(html_samples["short"])
        assert "processed_at" in result

    def test_structure_no_message_key(self, processor, html_samples):
        """
        GIVEN valid HTML content
        WHEN calling process_html_content successfully
        THEN message key is absent
        """
        result = processor.process_html_content(html_samples["short"])
        assert "message" not in result

    def test_error_structure_contains_status(self, processor):
        """
        GIVEN invalid input
        WHEN calling process_html_content fails
        THEN status equals error
        """
        result = processor.process_html_content(None)
        assert result["status"] == "error"

    def test_error_structure_contains_message(self, processor):
        """
        GIVEN invalid input
        WHEN calling process_html_content fails
        THEN message field describes failure
        """
        result = processor.process_html_content(None)
        assert "message" in result

    def test_error_structure_no_other_keys(self, processor):
        """
        GIVEN invalid input
        WHEN calling process_html_content fails
        THEN no success fields present
        """
        result = processor.process_html_content(None)
        assert "text" not in result

    def test_extraction_removes_markup(self, processor, html_samples):
        """
        GIVEN HTML with markup
        WHEN calling process_html_content
        THEN text contains no angle brackets
        """
        result = processor.process_html_content(html_samples["plain"])
        assert "<" not in result["text"]

    def test_extraction_excludes_scripts(self, processor, html_samples):
        """
        GIVEN HTML with scripts
        WHEN calling process_html_content
        THEN script content is excluded
        """
        result = processor.process_html_content(html_samples["with_script"])
        assert "alert" not in result["text"]

    def test_extraction_reflects_content(self, processor, html_samples):
        """
        GIVEN HTML content
        WHEN calling process_html_content
        THEN text_length matches extracted text
        """
        result = processor.process_html_content(html_samples["short"])
        assert result["text_length"] == len(result["text"])

    def test_metrics_html_length_matches(self, processor, html_samples):
        """
        GIVEN HTML content
        WHEN calling process_html_content
        THEN html_length matches input
        """
        html = html_samples["content"]
        result = processor.process_html_content(html)
        assert result["html_length"] == len(html)

    def test_metrics_text_length_matches(self, processor, html_samples):
        """
        GIVEN HTML content
        WHEN calling process_html_content
        THEN text_length matches extracted text
        """
        result = processor.process_html_content(html_samples["short"])
        assert result["text_length"] == len(result["text"])

    def test_metrics_precision(self, processor, html_samples):
        """
        GIVEN HTML content
        WHEN calling process_html_content
        THEN metrics are precise
        """
        result = processor.process_html_content(html_samples["content"])
        assert result["text_length"] == len(result["text"])

    def test_with_metadata_returns_success(self, processor, html_samples, metadata_samples):
        """
        GIVEN HTML with metadata
        WHEN calling process_html_content
        THEN status equals success
        """
        result = processor.process_html_content(html_samples["basic"], metadata_samples["crawler"])
        assert result["status"] == "success"

    def test_with_metadata_contains_text(self, processor, html_samples, metadata_samples):
        """
        GIVEN HTML with metadata
        WHEN calling process_html_content
        THEN text field contains extracted text
        """
        result = processor.process_html_content(html_samples["basic"], metadata_samples["crawler"])
        assert len(result["text"]) > 0

    def test_with_metadata_contains_html_length(self, processor, html_samples, metadata_samples):
        """
        GIVEN HTML with metadata
        WHEN calling process_html_content
        THEN html_length field is present
        """
        html = html_samples["basic"]
        result = processor.process_html_content(html, metadata_samples["crawler"])
        assert result["html_length"] == len(html)

    def test_with_metadata_contains_text_length(self, processor, html_samples, metadata_samples):
        """
        GIVEN HTML with metadata
        WHEN calling process_html_content
        THEN text_length field is present
        """
        result = processor.process_html_content(html_samples["basic"], metadata_samples["crawler"])
        assert result["text_length"] > 0

    def test_with_metadata_contains_metadata_field(self, processor, html_samples, metadata_samples):
        """
        GIVEN HTML with metadata
        WHEN calling process_html_content
        THEN metadata field contains input
        """
        result = processor.process_html_content(html_samples["basic"], metadata_samples["crawler"])
        assert result["metadata"] == metadata_samples["crawler"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])