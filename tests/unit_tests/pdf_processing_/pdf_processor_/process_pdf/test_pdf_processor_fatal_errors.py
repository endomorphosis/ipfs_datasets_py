"""
Test cases for timeout and external service failures in process_pdf method.

This module tests the process_pdf method's handling of timeout scenarios
and external service failures, including IPLD storage and OCR service issues.
Shared terminology: "service failure" refers to external dependency failures
that prevent successful processing.
"""
import asyncio
import pytest
from pathlib import Path
from typing import Any
from unittest.mock import patch, AsyncMock


from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor


@pytest.fixture
def large_pdf_file(tmp_path) -> str:
    """Create a large PDF file that would cause timeout."""
    large_pdf = tmp_path / "large.pdf"
    # Create a larger mock PDF structure
    large_content = b"%PDF-1.4\n" + b"large content " * 10000 + b"\n%%EOF"
    large_pdf.write_bytes(large_content)
    return str(large_pdf)

@pytest.fixture
def expected_timeout_message() -> str:
    """Expected error message for processing timeout."""
    return "Processing exceeded configured timeout limits"

@pytest.fixture
def expected_ipld_failure_message() -> str:
    """Expected error message for IPLD storage failure."""
    return "IPLD storage backend failure"

@pytest.fixture
def expected_ocr_failure_message() -> str:
    """Expected error message for OCR service failure."""
    return "OCR processing stage failed"

@pytest.fixture
def expected_llm_failure_message() -> str:
    """Expected error message for LLM service failure."""
    return "LLM optimization stage failed"

@pytest.fixture
def expected_vector_failure_message() -> str:
    """Expected error message for vector database failure."""
    return "Vector embedding stage failed"

@pytest.fixture
def memory_error_message() -> str:
    """Expected error message for memory allocation failure."""
    return "Processing failed due to insufficient memory"

@pytest.fixture
def graphrag_failure_message() -> str:
    """Expected error message for Graphrag service failure."""
    return "Graphrag service failure"

@pytest.fixture
def knowledge_graph_failure_message() -> str:
    """Expected error message for knowledge graph analysis failure."""
    return "Knowledge graph analysis failure"

@pytest.fixture
def query_failure_message() -> str:
    """Expected error message for query interface setup failure."""
    return "Query interface setup failure"


@pytest.fixture
def expected_error_messages(
        expected_ipld_failure_message,
        expected_ocr_failure_message,
        expected_llm_failure_message,
        expected_vector_failure_message,
        graphrag_failure_message,
        knowledge_graph_failure_message,
        query_failure_message
        ) -> dict[str, str]:
    """Aggregate expected error messages for easy access."""
    return {
        "ipld_failure": expected_ipld_failure_message,
        "ocr_failure": expected_ocr_failure_message,
        "llm_failure": expected_llm_failure_message,
        "vector_failure": expected_vector_failure_message,
        "graphrag_failure": graphrag_failure_message,
        "knowledge_graph_failure": knowledge_graph_failure_message,
        "query_failure": query_failure_message,
    }

@pytest.mark.asyncio
@pytest.mark.parametrize("service_method,exception_type,expected_message", [
    ("_validate_and_analyze_pdf", RuntimeError, "ipld_failure"),
    ("_decompose_pdf", RuntimeError, "ipld_failure"),
    ("_create_ipld_structure", RuntimeError, "ipld_failure"),
    ("_process_ocr", RuntimeError, "ocr_failure"),
    ("_optimize_for_llm", RuntimeError, "llm_failure"),
    ("_integrate_with_graphrag", RuntimeError, "graphrag_failure"),
    ("_analyze_cross_document_relationships", RuntimeError, "knowledge_graph_failure"),
    ("_setup_query_interface", RuntimeError, "query_failure"),
])
class TestProcessPdfTimeoutAndServiceFailures:
    """
    Test timeout and external service failure handling for process_pdf method.

    Tests the process_pdf method's ability to handle processing timeouts
    and various external service failures gracefully with appropriate
    error messages.

    Errors with individual PDF files should not throw fatal errors,
    whereas everything else should.

    Shared terminology:
    - "fatal error": Any part of the pipeline which, if it errors, prevents 
        the pipeline from producing a return with status='success', regardless of 
        the validity of the inputs or files.
    - "service failure": External dependency failure preventing processing
    - "timeout": Processing exceeding configured time limits
    - "runtime error": Critical pipeline stage failure
    """
    async def test_when_service_fails_then_returns_error_status(
        self,
        default_pdf_processor,
        valid_pdf_file,
        valid_metadata,
        expected_error_messages,
        service_method,
        exception_type,
        expected_message
    ):
        """
        GIVEN a service failure occurs
        WHEN process_pdf is called
        THEN returns dict with status='error'
        """
        error_msg = expected_error_messages[expected_message]
        side_effect = exception_type(error_msg)

        with patch.object(default_pdf_processor, service_method, side_effect=side_effect):
            result = await default_pdf_processor.process_pdf(valid_pdf_file, valid_metadata)

        assert result['status'] == 'error', \
            f"Expected status to be 'error' when {service_method} fails, got {result['status']} instead."


    async def test_when_service_fails_then_returns_appropriate_error_message(
        self,
        default_pdf_processor: PDFProcessor,
        valid_pdf_file,
        valid_metadata,
        expected_error_messages,
        service_method,
        exception_type,
        expected_message
    ):
        """
        GIVEN a service failure occurs
        WHEN process_pdf is called
        THEN returns dict with appropriate error message
        """
        error_msg = expected_error_messages[expected_message]
        side_effect = exception_type(error_msg)

        with patch.object(default_pdf_processor, service_method, side_effect=side_effect):
            result = await default_pdf_processor.process_pdf(valid_pdf_file, valid_metadata)

        assert error_msg in result['error'], \
            f"Expected error message to contain '{error_msg}', got '{result['error']}' instead."


@pytest.mark.parametrize("first_service,first_exception,first_message,second_service,second_exception,second_message", [
    ("_validate_and_analyze_pdf", RuntimeError, "ipld_failure", "_process_ocr", RuntimeError, "ocr_failure"),
    ("_process_ocr", RuntimeError, "ocr_failure", "_optimize_for_llm", RuntimeError, "llm_failure"),
    ("_optimize_for_llm", RuntimeError, "llm_failure", "_create_embeddings", RuntimeError, "vector_failure"),
    ("_decompose_pdf", RuntimeError, "ipld_failure", "_create_ipld_structure", RuntimeError, "ipld_failure"),
    ("_process_ocr", RuntimeError, "ocr_failure", "_extract_entities", RuntimeError, "llm_failure"),
])
class TestProcessPdfMultipleServiceFailures:
    """Test handling of multiple service failures in process_pdf method."""
    @pytest.mark.asyncio
    async def test_when_multiple_service_failures_then_returns_error_status(
        self, 
        default_pdf_processor, 
        valid_pdf_file, 
        valid_metadata,
        expected_error_messages,
        first_service,
        first_exception,
        first_message,
        second_service,
        second_exception,
        second_message
    ):
        """
        GIVEN multiple service failures occur
        WHEN process_pdf is called
        THEN returns dict with status='error'
        """
        first_error_msg = expected_error_messages[first_message]
        second_error_msg = expected_error_messages[second_message]
        
        # Mock multiple service failures, first one should be raised
        with patch.object(default_pdf_processor, first_service, side_effect=first_exception(first_error_msg)):
            with patch.object(default_pdf_processor, second_service, side_effect=second_exception(second_error_msg)):
                result = await default_pdf_processor.process_pdf(valid_pdf_file, valid_metadata)

        assert result['status'] == 'error', \
            f"Expected status to be 'error' when multiple service failures occur, got {result['status']} instead."

    @pytest.mark.asyncio
    async def test_when_multiple_service_failures_then_returns_first_failure_message(
        self, 
        default_pdf_processor, 
        valid_pdf_file, 
        valid_metadata,
        expected_error_messages,
        first_service,
        first_exception,
        first_message,
        second_service,
        second_exception,
        second_message
    ):
        """
        GIVEN multiple service failures occur
        WHEN process_pdf is called
        THEN returns dict with message from first failing service
        """
        first_error_msg = expected_error_messages[first_message]
        second_error_msg = expected_error_messages[second_message]

        # Mock multiple service failures, first one should be raised
        with patch.object(default_pdf_processor, first_service, side_effect=first_exception(first_error_msg)):
            with patch.object(default_pdf_processor, second_service, side_effect=second_exception(second_error_msg)):
                result = await default_pdf_processor.process_pdf(valid_pdf_file, valid_metadata)

        assert result['error'] == first_error_msg, \
            f"Expected message to be from first failing service: '{first_error_msg}', got '{result['error']}' instead."
