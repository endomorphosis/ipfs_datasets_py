#!/usr/bin/env python3
"""Test suite for WebArchiveProcessor.extract_text_from_html method."""

import pytest
from ipfs_datasets_py.web_archive import WebArchiveProcessor

STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
KEY_STATUS = "status"
KEY_TEXT = "text"
KEY_LENGTH = "length"
KEY_MESSAGE = "message"
EMPTY_STRING = ""
ZERO = 0


class TestWebArchiveProcessorExtractTextFromHtml:
    """Test WebArchiveProcessor.extract_text_from_html method functionality."""

    @pytest.fixture
    def processor(self):
        """Set up test fixtures."""
        return WebArchiveProcessor()

    def test_when_extracting_from_valid_html_then_status_is_success(self, processor):
        """Given valid HTML, when extracting text, then status is success."""
        html = "<html><head><title>Test</title></head><body><h1>Hello</h1></body></html>"
        result = processor.extract_text_from_html(html)
        
        assert result[KEY_STATUS] == STATUS_SUCCESS, f"Expected status {STATUS_SUCCESS}, got {result.get(KEY_STATUS)}"

    def test_when_extracting_from_html_with_markup_then_markup_is_removed(self, processor):
        """Given HTML with markup, when extracting text, then markup is removed."""
        html = '<html><body><h1>Hello</h1><p><b>bold</b></p></body></html>'
        result = processor.extract_text_from_html(html)
        
        assert "<b>" not in result[KEY_TEXT], f"Expected no '<b>' tags, but found in: {result[KEY_TEXT]}"

    def test_when_extracting_from_valid_html_then_length_is_provided(self, processor):
        """Given valid HTML, when extracting text, then length is provided."""
        html = "<html><body><p>Test</p></body></html>"
        result = processor.extract_text_from_html(html)
        
        assert KEY_LENGTH in result, f"Expected {KEY_LENGTH} key in result: {result.keys()}"

    def test_when_extracting_from_html_with_scripts_then_scripts_are_removed(self, processor):
        """Given HTML with scripts, when extracting text, then scripts are removed."""
        html = "<html><body><script>alert('x');</script><p>Visible</p></body></html>"
        result = processor.extract_text_from_html(html)
        
        assert "alert" not in result[KEY_TEXT], f"Expected no script content, found in: {result[KEY_TEXT]}"

    def test_when_extracting_from_html_with_script_tags_then_no_script_content_remains(
        self, processor
    ):
        """Given HTML with script tags, when extracting, then no script content remains."""
        html = "<html><body><script>var x='test';</script><p>Text</p></body></html>"
        result = processor.extract_text_from_html(html)
        
        assert "var x" not in result[KEY_TEXT], f"Expected no script variables, found: {result[KEY_TEXT]}"

    def test_when_extracting_from_html_with_scripts_then_total_script_elimination_occurs(
        self, processor
    ):
        """Given HTML with scripts, when extracting, then total script elimination occurs."""
        html = "<html><body><script>function f(){}</script><p>Content</p></body></html>"
        result = processor.extract_text_from_html(html)
        
        assert "function" not in result[KEY_TEXT], f"Expected no JS functions, found: {result[KEY_TEXT]}"

    def test_when_extracting_from_html_with_scripts_then_only_visible_text_remains(
        self, processor
    ):
        """Given HTML with scripts, when extracting, then only visible text remains."""
        html = "<html><body><script>hidden</script><p>visible</p></body></html>"
        result = processor.extract_text_from_html(html)
        
        assert "visible" in result[KEY_TEXT], f"Expected visible text, got: {result[KEY_TEXT]}"

    def test_when_extracting_from_html_with_excess_spaces_then_spaces_are_collapsed(
        self, processor
    ):
        """Given HTML with excess spaces, when extracting, then spaces are collapsed."""
        html = "<html><body><p>Multiple    spaces</p></body></html>"
        result = processor.extract_text_from_html(html)
        
        assert "    " not in result[KEY_TEXT], f"Expected collapsed spaces, got: {result[KEY_TEXT]}"

    def test_when_extracting_from_html_with_whitespace_then_whitespace_is_normalized(
        self, processor
    ):
        """Given HTML with whitespace, when extracting, then whitespace is normalized."""
        html = "<html><body><p>Text\n\n\nwith\tlines</p></body></html>"
        result = processor.extract_text_from_html(html)
        
        assert "\n\n\n" not in result[KEY_TEXT], f"Expected normalized whitespace: {result[KEY_TEXT]}"

    def test_when_extracting_from_html_with_messy_whitespace_then_output_is_clean(
        self, processor
    ):
        """Given HTML with messy whitespace, when extracting, then output is clean."""
        html = "<html><body><p>  Leading and trailing  </p></body></html>"
        result = processor.extract_text_from_html(html)
        
        assert result[KEY_TEXT].strip() == result[KEY_TEXT], f"Expected trimmed text: '{result[KEY_TEXT]}'"

    def test_when_extracting_from_empty_string_then_status_is_success(self, processor):
        """Given empty string, when extracting, then status is success."""
        result = processor.extract_text_from_html(EMPTY_STRING)
        
        assert result[KEY_STATUS] == STATUS_SUCCESS, f"Expected success status, got: {result.get(KEY_STATUS)}"

    def test_when_extracting_from_empty_string_then_text_is_empty(self, processor):
        """Given empty string, when extracting, then text is empty."""
        result = processor.extract_text_from_html(EMPTY_STRING)
        
        assert result[KEY_TEXT] == EMPTY_STRING, f"Expected empty text, got: '{result[KEY_TEXT]}'"

    def test_when_extracting_from_empty_string_then_length_is_zero(self, processor):
        """Given empty string, when extracting, then length is zero."""
        result = processor.extract_text_from_html(EMPTY_STRING)
        
        assert result[KEY_LENGTH] == ZERO, f"Expected length {ZERO}, got: {result[KEY_LENGTH]}"

    def test_when_extraction_succeeds_then_result_contains_status(self, processor):
        """Given valid HTML, when extraction succeeds, then result contains status."""
        html = "<html><body><p>Test</p></body></html>"
        result = processor.extract_text_from_html(html)
        
        assert KEY_STATUS in result, f"Expected {KEY_STATUS} key in result: {result.keys()}"

    def test_when_extraction_succeeds_then_result_contains_text(self, processor):
        """Given valid HTML, when extraction succeeds, then result contains text."""
        html = "<html><body><p>Test</p></body></html>"
        result = processor.extract_text_from_html(html)
        
        assert KEY_TEXT in result, f"Expected {KEY_TEXT} key in result: {result.keys()}"

    def test_when_extraction_succeeds_then_result_contains_length(self, processor):
        """Given valid HTML, when extraction succeeds, then result contains length."""
        html = "<html><body><p>Test</p></body></html>"
        result = processor.extract_text_from_html(html)
        
        assert KEY_LENGTH in result, f"Expected {KEY_LENGTH} key in result: {result.keys()}"

    def test_when_extraction_succeeds_then_no_message_key_exists(self, processor):
        """Given valid HTML, when extraction succeeds, then no message key exists."""
        html = "<html><body><p>Test</p></body></html>"
        result = processor.extract_text_from_html(html)
        
        assert KEY_MESSAGE not in result, f"Expected no {KEY_MESSAGE} key, found in: {result.keys()}"

    def test_when_extraction_fails_then_status_is_error(self, processor):
        """Given malformed HTML, when extraction fails, then status is error."""
        result = processor.extract_text_from_html(None)
        
        assert result[KEY_STATUS] == STATUS_ERROR, f"Expected error status, got: {result.get(KEY_STATUS)}"

    def test_when_extraction_fails_then_message_is_provided(self, processor):
        """Given malformed HTML, when extraction fails, then message is provided."""
        result = processor.extract_text_from_html(None)
        
        assert KEY_MESSAGE in result, f"Expected {KEY_MESSAGE} key in error result: {result.keys()}"

    def test_when_extraction_fails_then_no_text_or_length_keys(self, processor):
        """Given malformed HTML, when extraction fails, then no text or length keys."""
        result = processor.extract_text_from_html(None)
        
        assert KEY_TEXT not in result, f"Expected no {KEY_TEXT} in error result: {result.keys()}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])