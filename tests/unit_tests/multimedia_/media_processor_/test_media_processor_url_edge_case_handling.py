#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pytest
import os
from unittest.mock import Mock, patch, MagicMock
from urllib.parse import urlparse
import anyio

# Make sure the input file and documentation file exist.
work_dir = os.path.abspath(os.path.dirname(__file__))
while not os.path.exists(os.path.join(work_dir, "__pyproject.toml")):
    parent = os.path.dirname(work_dir)
    if parent == work_dir:
        break
    work_dir = parent
file_path = os.path.join(work_dir, "ipfs_datasets_py/multimedia/media_processor.py")
md_path = os.path.join(work_dir, "ipfs_datasets_py/multimedia/media_processor_stubs.md")

# Import the MediaProcessor class and its class dependencies
from ipfs_datasets_py.multimedia.media_processor import MediaProcessor, make_media_processor
from ipfs_datasets_py.multimedia.ytdlp_wrapper import YtDlpWrapper
from ipfs_datasets_py.multimedia.ffmpeg_wrapper import FFmpegWrapper


from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

# Test data constants for specific edge cases
TEST_EDGE_CASES = {
    "http_to_https_redirect": "http://example.com/video.mp4",
    "bitly_shortened": "https://bit.ly/3example",
    "tinyurl_shortened": "https://tinyurl.com/example123",
    "query_parameters": "https://youtube.com/watch?v=abc123&t=30s&list=xyz",
    "url_fragments": "https://example.com/video.mp4#t=120",
    "private_content": "https://youtube.com/watch?v=private123",
    "age_restricted": "https://youtube.com/watch?v=restricted456",
    "geo_blocked": "https://example.com/video-us-only.mp4",
    "not_found_404": "https://example.com/deleted-video.mp4",
    "malformed_missing_protocol": "example.com/video.mp4",
    "invalid_domain": "https://invalid..domain.com/video.mp4",
    "non_video_content": "https://example.com/document.pdf",
    "rate_limited": "https://youtube.com/watch?v=rate_limited_url"
}

REQUIRED_ERROR_CLASSIFICATIONS = [
    "REDIRECT", "PRIVATE", "RESTRICTED", "NOT_FOUND", 
    "INVALID_FORMAT", "NOT_VIDEO", "RATE_LIMITED"
]
NUMBER_OF_HOPS = 5
ERROR_MESSAGE_MAX_LENGTH = 200


class TestURLEdgeCaseHandling:
    """Test URL edge case handling with specific, testable scenarios.
    
    NOTE: Class has multiple vague requirements that need clarification:
    1. 90% success ratio is arbitrary without failure tolerance analysis
    2. 200-character error message limit lacks user experience justification
    3. 5-hop redirect limit is arbitrary without performance analysis
    4. 10-second timeout lacks network condition considerations
    5. "Appropriate responses" criteria undefined for success calculation
    """

    @pytest.mark.parametrize("redirect_type,url", [
        ("http_to_https", TEST_EDGE_CASES["http_to_https_redirect"])
    ])
    async def test_redirect_follows_and_succeeds(self, redirect_type, url, successful_processor):
        """
        GIVEN URL that redirects to HTTPS
        WHEN MediaProcessor.download_and_convert processes the URL and succeeds
        THEN expect return dict with status "success"
        """
        # Arrange
        expected_status = "success"
        
        # Act
        result = await successful_processor.download_and_convert(url)
        
        # Assert
        assert result["status"] == expected_status, f"Expected status '{expected_status}' but got '{result['status']}' for {redirect_type}"

    @pytest.mark.parametrize("service_name,url", [
        ("bit.ly", TEST_EDGE_CASES["bitly_shortened"]),
        ("tinyurl", TEST_EDGE_CASES["tinyurl_shortened"])
    ])
    async def test_shortened_url_resolves_to_valid_result(self, service_name, url, successful_processor):
        """
        GIVEN shortened URL from various services
        WHEN MediaProcessor.download_and_convert processes the URL and succeeds
        THEN expect return dict with either status "success"
        """
        # Arrange
        expected_status = "success"
        
        # Act
        result = await successful_processor.download_and_convert(url)
        
        # Assert
        assert result["status"] == expected_status, f"Expected status '{expected_status}' but got '{result['status']}' for {service_name} URL"

    @pytest.mark.parametrize("video_id,expected_difference", [
        ("abc123", "different_video_1"),
        ("def456", "different_video_2"),
        ("xyz789", "different_video_3")
    ])
    async def test_essential_query_parameters_affect_download_result(self, video_id, expected_difference, url_aware_processor):
        """
        GIVEN YouTube URLs with different video IDs 
            (e.g. "https://youtube.com/watch?v=abc123" vs "https://youtube.com/watch?v=def456")
        WHEN MediaProcessor.download_and_convert processes both URLs
        THEN expect different results (different titles, file paths, or error messages)
        """
        # Arrange
        url1 = f"https://youtube.com/watch?v={video_id}"
        url2 = f"https://youtube.com/watch?v=different123"
        
        # Act
        result1 = await url_aware_processor.download_and_convert(url1)
        result2 = await url_aware_processor.download_and_convert(url2)
        
        # Assert
        assert result1 != result2, f"Expected different results for different video IDs but got identical results: '{result1}' vs '{result2}'"

    @pytest.mark.parametrize("base_url,tracking_params", [
        ("https://youtube.com/watch?v=abc123", "utm_source=test"),
        ("https://youtube.com/watch?v=abc123", "utm_campaign=promotion&utm_medium=social"),
        ("https://youtube.com/watch?v=def456", "ref=homepage"),
        ("https://example.com/video.mp4", "tracking_id=12345&source=email")
    ])
    async def test_tracking_parameters_do_not_affect_download_result(self, base_url, tracking_params, successful_processor):
        """
        GIVEN URL with and without tracking parameters
        WHEN MediaProcessor.download_and_convert processes both URLs
        THEN expect return dict to have identical key-value pairs
        """
        # Arrange
        url_without_tracking = base_url
        url_with_tracking = f"{base_url}&{tracking_params}"
        
        # Act
        result_without = await successful_processor.download_and_convert(url_without_tracking)
        result_with = await successful_processor.download_and_convert(url_with_tracking)
        
        # Assert
        assert result_without == result_with, f"Expected identical results but got '{result_without}' vs '{result_with}' for URLs with/without tracking parameters"

    async def test_url_fragments_reflected_in_download_metadata(self, successful_processor):
        """
        GIVEN URL with and without timestamp fragment (e.g. "https://example.com/video.mp4#t=120")
        WHEN MediaProcessor.download_and_convert processes the URL
        THEN expect return dict to have identical key-value pairs
        """
        # Arrange
        url_without_fragment = "https://example.com/video.mp4"
        url_with_fragment = TEST_EDGE_CASES["url_fragments"]
        
        # Act
        result_without = await successful_processor.download_and_convert(url_without_fragment)
        result_with = await successful_processor.download_and_convert(url_with_fragment)
        
        # Assert
        assert result_without == result_with, f"Expected identical results but got '{result_without}' vs '{result_with}' for fragment comparison"

    async def test_private_content_returns_private_error_classification(self, download_failure_processor):
        """
        GIVEN URL returning HTTP 403 Forbidden
        WHEN MediaProcessor.download_and_convert processes the URL
        THEN expect return dict with status "error" and error message indicating private/forbidden content
        """
        # Arrange
        private_url = TEST_EDGE_CASES["private_content"]
        expected_status = "error"
        
        # Act
        result = await download_failure_processor.download_and_convert(private_url)
        
        # Assert
        assert result["status"] == expected_status, f"Expected status '{expected_status}' but got '{result['status']}' for private content URL"

    async def test_age_restricted_content_returns_restricted_error_classification(self, download_failure_processor):
        """
        GIVEN URL returning age verification requirement
        WHEN MediaProcessor.download_and_convert processes the URL
        THEN expect return dict with status "error" and error message indicating age restriction
        """
        # Arrange
        age_restricted_url = TEST_EDGE_CASES["age_restricted"]
        expected_status = "error"
        
        # Act
        result = await download_failure_processor.download_and_convert(age_restricted_url)
        
        # Assert
        assert result["status"] == expected_status, f"Expected status '{expected_status}' but got '{result['status']}' for age restricted content URL"

    async def test_geo_blocked_content_returns_restricted_error_classification(self, download_failure_processor):
        """
        GIVEN URL returning geo-blocking message
        WHEN MediaProcessor.download_and_convert processes the URL
        THEN expect return dict with status "error" and error message indicating geographic restriction
        """
        # Arrange
        geo_blocked_url = TEST_EDGE_CASES["geo_blocked"]
        expected_status = "error"
        
        # Act
        result = await download_failure_processor.download_and_convert(geo_blocked_url)
        
        # Assert
        assert result["status"] == expected_status, f"Expected status '{expected_status}' but got '{result['status']}' for geo-blocked content URL"

    async def test_not_found_404_returns_not_found_error_classification(self, download_failure_processor):
        """
        GIVEN URL returning HTTP 404 Not Found
        WHEN MediaProcessor.download_and_convert processes the URL
        THEN expect return dict with status "error" and error message indicating content not found
        """
        # Arrange
        not_found_url = TEST_EDGE_CASES["not_found_404"]
        expected_status = "error"
        
        # Act
        result = await download_failure_processor.download_and_convert(not_found_url)
        
        # Assert
        assert result["status"] == expected_status, f"Expected status '{expected_status}' but got '{result['status']}' for 404 not found URL"

    @pytest.mark.parametrize("url_type,url", [
        ("missing_protocol", TEST_EDGE_CASES["malformed_missing_protocol"]),
        ("invalid_domain", TEST_EDGE_CASES["invalid_domain"])
    ])
    async def test_malformed_url_missing_protocol_returns_invalid_format(self, url_type, url, download_failure_processor):
        """
        GIVEN malformed URL without protocol or with invalid domain format
        WHEN MediaProcessor.download_and_convert processes the URL
        THEN expect return dict with status "error" and error message indicating invalid URL format
        """
        # Arrange
        expected_status = "error"
        
        # Act
        result = await download_failure_processor.download_and_convert(url)
        
        # Assert
        assert result["status"] == expected_status, f"Expected status '{expected_status}' but got '{result['status']}' for {url_type} malformed URL"


    @pytest.mark.parametrize("domain_type,url", [
        ("double_dot", "https://invalid..domain.com/video.mp4"),
        ("trailing_dot", "https://invalid.domain.com./video.mp4"),
        ("leading_dot", "https://.invalid.domain.com/video.mp4"),
        ("empty_subdomain", "https://.com/video.mp4"),
        ("special_chars", "https://invalid@domain.com/video.mp4"),
        ("spaces", "https://invalid domain.com/video.mp4")
    ])
    async def test_invalid_domain_format_returns_invalid_format(self, domain_type, url, download_failure_processor):
        """
        GIVEN URL with invalid domain format
        WHEN MediaProcessor.download_and_convert processes the URL
        THEN expect return dict with status "error" and error message indicating invalid domain format
        """
        # Arrange
        expected_status = "error"
        
        # Act
        result = await download_failure_processor.download_and_convert(url)
        
        # Assert
        assert result["status"] == expected_status, f"Expected status '{expected_status}' but got '{result['status']}' for {domain_type} domain format"

    @pytest.mark.parametrize("content_type,url", [
        ("pdf", "https://example.com/document.pdf"),
        ("txt", "https://example.com/readme.txt"),
        ("docx", "https://example.com/report.docx"),
        ("jpg", "https://example.com/image.jpg"),
        ("png", "https://example.com/photo.png"),
        ("zip", "https://example.com/archive.zip"),
        ("exe", "https://example.com/installer.exe"),
        ("html", "https://example.com/webpage.html")
    ])
    async def test_non_video_content_returns_not_video_error_classification(self, content_type, url, download_failure_processor):
        """
        GIVEN URL pointing to non-video content (PDF, text, image, etc.)
        WHEN MediaProcessor.download_and_convert processes the URL
        THEN expect return dict with status "error" and error message indicating non-video content
        """
        # Arrange
        expected_status = "error"
        
        # Act
        result = await download_failure_processor.download_and_convert(url)
        
        # Assert
        assert result["status"] == expected_status, f"Expected status '{expected_status}' but got '{result['status']}' for {content_type} non-video content"


    async def test_rate_limited_response_returns_rate_limited_error_classification(self, download_failure_processor):
        """
        GIVEN URL returning HTTP 429 Too Many Requests
        WHEN MediaProcessor.download_and_convert processes the URL
        THEN expect return dict with status "error" and error message indicating rate limiting
        """
        # Arrange
        rate_limited_url = TEST_EDGE_CASES["rate_limited"]
        expected_status = "error"
        
        # Act
        result = await download_failure_processor.download_and_convert(rate_limited_url)
        
        # Assert
        assert result["status"] == expected_status, f"Expected status '{expected_status}' but got '{result['status']}' for rate limited URL"


    async def test_error_message_length_constraint_enforced(self, download_failure_processor):
        """
        GIVEN any URL that produces an error response
        WHEN MediaProcessor.download_and_convert processes the URL
        THEN expect error message in return dict to be ≤ 200 characters
        """
        # Arrange
        test_url = "https://example.com/error"
        
        # Act
        result = await download_failure_processor.download_and_convert(test_url)
        
        # Assert
        error_message = result["error"]
        assert len(error_message) <= ERROR_MESSAGE_MAX_LENGTH, \
            f"Expected error message length ≤ {ERROR_MESSAGE_MAX_LENGTH} characters but got {len(error_message)} characters"


    async def test_redirect_chain_limit_enforced_at_5_hops(self, download_failure_processor):
        """
        GIVEN URL with redirect chain > NUMBER_OF_HOPS hops
        WHEN MediaProcessor.download_and_convert processes the URL that is greater than the allowed hops
        THEN expect return dict with status "error" and error message indicating too many redirects
        """
        # Arrange
        test_url = "https://example.com/too-many-redirects"
        expected_status = "error"
        
        # Act
        result = await download_failure_processor.download_and_convert(test_url)
        
        # Assert
        assert result["status"] == expected_status, \
            f"Expected status '{expected_status}' but got '{result['status']}' for URL with too many redirects"

    async def test_url_resolution_timeout_enforced_at_10_seconds(self, download_failure_processor):
        """
        GIVEN shortened valid url resolution taking >10 seconds
        WHEN MediaProcessor.download_and_convert processes the URL that takes longer than limit
        THEN expect return dict with status "error" and error message indicating timeout exceeded
        """
        # Arrange
        timeout_url = "https://slow.example.com/video.mp4"
        expected_status = "error"
        
        # Act
        result = await download_failure_processor.download_and_convert(timeout_url)
        
        # Assert
        assert result["status"] == expected_status, \
            f"Expected status '{expected_status}' but got '{result['status']}' for URL with timeout"

    async def test_ssl_certificate_errors_handled_gracefully(self, download_failure_processor):
        """
        GIVEN URL with SSL certificate errors
        WHEN MediaProcessor.download_and_convert processes the URL
        THEN expect return dict with status "error" and error message indicating SSL/certificate issues
        """
        # Arrange
        ssl_error_url = "https://expired.badssl.com/video.mp4"
        expected_status = "error"
        
        # Act
        result = await download_failure_processor.download_and_convert(ssl_error_url)
        
        # Assert
        assert result["status"] == expected_status, \
        f"Expected status '{expected_status}' but got '{result['status']}' for SSL certificate error URL"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])