
import logging
import inspect
import os
from pathlib import Path

import pytest


from ipfs_datasets_py.pdf_processing import (
import asyncio
    PDFProcessor,
    
    # OCR engines
    MultiEngineOCR,
    SuryaOCR, 
    TesseractOCR,
    EasyOCR,
    
    # LLM optimization
    LLMOptimizer,
    LLMDocument,
    LLMChunk,
    
    # GraphRAG integration
    GraphRAGIntegrator,
    KnowledgeGraph,
    Entity,
    Relationship,
    
    # Query engine
    QueryEngine,
    QueryResult,
    QueryResponse,
    
    # Batch processing
    BatchProcessor,
    ProcessingJob,
    BatchStatus
)

from ipfs_datasets_py.audit import AuditLogger
from ipfs_datasets_py.monitoring import MonitoringSystem
from ipfs_datasets_py.ipld import IPLDStorage


import tests.unit_tests.pdf_processing_.conftest as conftest



import reportlab
import PIL
from reportlab.pdfgen import canvas



import pytest
from pathlib import Path
from reportlab.pdfgen import canvas




class TestPdfProcessorVerticalSlice:
    """Test an end-to-end PDF conversion."""

    @pytest.mark.asyncio
    async def test_when_process_pdf_called_then_output_is_dict(self, default_pdf_processor, valid_pdf_document):
        """
        GIVEN a default PDFProcessor instance
        WHEN the process_pdf method is called with a valid PDF document
        EXPECT the results to be a dictionary.
        NOTE: This also tests if the function runs without throwing fatal errors when given valid content.
        """
        results = await default_pdf_processor.process_pdf(valid_pdf_document)

        assert isinstance(results, dict), \
            "Expected the result to be a dictionary, got {type(results).__name__} instead."

    @pytest.mark.parametrize(
        "key",
        [
            "status",
            "document_id", 
            "ipld_cid",
            "entities_count",
            "relationships_count", 
            "cross_doc_relations",
            "processing_metadata"
        ]
    )
    @pytest.mark.asyncio
    async def test_when_process_pdf_called_then_expected_keys_are_present(
        self, default_pdf_processor, valid_pdf_document, key):
        """
        GIVEN a default PDFProcessor instance
        WHEN the process_pdf method is called with a valid PDF document
        EXPECT all expected keys to be present in the results dictionary
        """
        results = await default_pdf_processor.process_pdf(valid_pdf_document)
        
        assert key in results, f"Expected key '{key}' not present in output dictionary."

    @pytest.mark.parametrize(
        "key,expected_type",
        [
            ("status", str),
            ("document_id", str),
            ("ipld_cid", str),
            ("entities_count", int),
            ("relationships_count", int),
            ("cross_doc_relations", int),
            ("processing_metadata", dict)
        ]
    )
    @pytest.mark.asyncio
    async def test_when_process_pdf_called_then_all_values_are_expected_type(
            self, default_pdf_processor, valid_pdf_document, key, expected_type):
        """
        GIVEN a default PDFProcessor instance
        WHEN the process_pdf method is called with a valid PDF document
        EXPECT all values in the results dictionary have the expected type
        """
        results = await default_pdf_processor.process_pdf(valid_pdf_document)
        print(results)

        value = results[key]

        assert isinstance(value, expected_type), \
            f"Expected value for key '{key}' to be type {expected_type.__name__}, " \
            f"got {type(value).__name__} instead."


    @pytest.mark.parametrize(
        "key_to_string_value", ["status", "document_id", "ipld_cid"]
    )
    @pytest.mark.asyncio
    async def test_when_process_pdf_called_then_all_string_values_are_not_empty(
            self, default_pdf_processor, valid_pdf_document, key_to_string_value
    ):
        """
        GIVEN a default PDFProcessor instance
        WHEN the process_pdf method is called with a valid PDF document
        EXPECT all string values in the results dictionary to not be empty after stripping.
        """
        results = await default_pdf_processor.process_pdf(valid_pdf_document)

        string = results[key_to_string_value].strip()

        assert string != "", \
        f"Expected '{key_to_string_value}' to be a non-empty string."

    @pytest.mark.asyncio
    async def test_when_process_pdf_called_with_valid_pdf_then_status_is_success(
        self, pdf_process_with_debug_logger, valid_pdf_document, expected_status_success
    ):
        """
        GIVEN a default PDFProcessor instance
        WHEN the process_pdf method is called with a valid PDF document
        EXPECT the value of 'status' key in the dictionary to be 'success'
        """
        results = await pdf_process_with_debug_logger.process_pdf(valid_pdf_document)

        status = results["status"]
        assert status == expected_status_success, \
            f"Expected status to be 'success', got {status} instead."


    @pytest.mark.parametrize(
        "key_to_int_value", ["entities_count", "relationships_count", "cross_doc_relations"]
    )
    @pytest.mark.asyncio
    async def test_when_process_pdf_called_then_all_int_values_are_non_negative(
            self, default_pdf_processor, valid_pdf_document, key_to_int_value):
        """
        GIVEN a default PDFProcessor instance
        WHEN the process_pdf method is called with a valid PDF document
        EXPECT all integer values in the results dictionary to be non-negative
        """
        results = await default_pdf_processor.process_pdf(valid_pdf_document)

        integer = results[key_to_int_value]

        assert integer >= 0, f"Expected '{key_to_int_value}' to be non-negative, got {integer}."


class TestPdfProcessorVerticalSliceProcessingMetadata:
    """Test to see if the processing_metadata dictionary possess the following attributes:
    - Correct keys
    - Correct value types
    - Sensible values 
    """
    @pytest.mark.parametrize(
        "metadata_key", ["pipeline_version", "processing_time", "quality_scores", "stages_completed"]
    )
    @pytest.mark.asyncio
    async def test_when_process_pdf_called_then_processing_metadata_has_expected_keys(
            self, default_pdf_processor, valid_pdf_document, metadata_key):
        """
        GIVEN a default PDFProcessor instance
        WHEN the process_pdf method is called with a valid PDF document
        EXPECT processing_metadata dictionary to contain all expected keys
        """
        results = await default_pdf_processor.process_pdf(valid_pdf_document)
        print(results)
        
        processing_metadata = results["processing_metadata"]
        
        assert metadata_key in processing_metadata, \
            f"Expected key '{metadata_key}' not present in processing_metadata dictionary."


    @pytest.mark.parametrize(
        "metadata_key,expected_type",
        [
            ("pipeline_version", str),
            ("processing_time", float),
            ("quality_scores", dict),
            ("stages_completed", list)
        ]
    )
    @pytest.mark.asyncio
    async def test_when_process_pdf_called_then_processing_metadata_values_have_expected_types(
            self, default_pdf_processor, valid_pdf_document, metadata_key, expected_type):
        """
        GIVEN a default PDFProcessor instance
        WHEN the process_pdf method is called with a valid PDF document
        EXPECT processing_metadata values to have the expected types
        """
        results = await default_pdf_processor.process_pdf(valid_pdf_document)

        value = results["processing_metadata"][metadata_key]

        assert isinstance(value, expected_type), \
            f"Expected value for key '{metadata_key}' to be type {expected_type.__name__}, " \
            f"got {type(value).__name__} instead."


    @pytest.mark.asyncio
    async def test_when_process_pdf_called_then_processing_metadata_key_pipeline_version_is_not_empty(
            self, default_pdf_processor, valid_pdf_document):
        """
        GIVEN a default PDFProcessor instance
        WHEN the process_pdf method is called with a valid PDF document
        EXPECT processing_metadata key 'pipeline_version' to be a non-empty string
        """
        results = await default_pdf_processor.process_pdf(valid_pdf_document)
        print(results)

        value = results["processing_metadata"]["pipeline_version"]

        assert value != "", "Expected 'pipeline_version' to be a non-empty string."


    @pytest.mark.parametrize(
        "key_to_numeric_value",
        ["processing_time"]
    )
    @pytest.mark.asyncio
    async def test_when_process_pdf_called_then_processing_metadata_numeric_values_are_positive(
            self, default_pdf_processor, valid_pdf_document, key_to_numeric_value):
        """
        GIVEN a default PDFProcessor instance
        WHEN the process_pdf method is called with a valid PDF document
        EXPECT processing_metadata keys that contain numeric values are positive.
        """
        results = await default_pdf_processor.process_pdf(valid_pdf_document)

        value = results["processing_metadata"][key_to_numeric_value]

        assert value > 0, f"Expected '{key_to_numeric_value}' to be positive, got {value} instead."


    @pytest.mark.parametrize(
        "key_to_numeric_value",
        ["processing_time"]
    )
    @pytest.mark.asyncio
    async def test_when_process_pdf_called_then_processing_metadata_numeric_values_are_positive(
            self, default_pdf_processor, valid_pdf_document, key_to_numeric_value):
        """
        GIVEN a default PDFProcessor instance
        WHEN the process_pdf method is called with a valid PDF document
        EXPECT processing_metadata keys that contain numeric values are positive.
        """
        results = await default_pdf_processor.process_pdf(valid_pdf_document)

        value = results["processing_metadata"][key_to_numeric_value]

        assert value > 0, f"Expected 'processing_time' to be positive, got {value} instead."




class TestPdfProcessorInit:

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"enable_monitoring": False},
            {"enable_monitoring": True},
            {"enable_audit": True},
            {"enable_audit": False},
        ]
    )
    def test_when_init_called_with_simple_parameters_then_return_is_pdf_processor_instance(self, kwargs):
        """Test PDFProcessor initialization with simple parameter combinations."""
        processor = PDFProcessor(**kwargs)
        assert isinstance(processor, PDFProcessor)

    def test_when_init_called_with_default_parameters_then_return_is_pdf_processor_instance(
        self, default_pdf_processor_parameters
    ):
        """Test PDFProcessor initialization with default parameters."""
        processor = PDFProcessor(**default_pdf_processor_parameters)
        assert isinstance(processor, PDFProcessor)

    def test_when_init_called_with_ipld_storage_then_return_is_pdf_processor_instance(
        self, default_ipld_storage
    ):
        """Test PDFProcessor initialization with IPLD storage."""
        processor = PDFProcessor(storage=default_ipld_storage)
        assert isinstance(processor, PDFProcessor)

    def test_when_init_called_with_custom_logger_then_return_is_pdf_processor_instance(
        self, default_logger
    ):
        """Test PDFProcessor initialization with custom logger."""
        processor = PDFProcessor(logger=default_logger)
        assert isinstance(processor, PDFProcessor)



class TestPdfProcessorHasRightPublicAttributes:

    @pytest.mark.parametrize(
        "attribute",
        [
            "storage",
            "audit_logger", 
            "monitoring",
            "query_engine",
            "pipeline_version",
            "logger",
            "integrator",
            "ocr_engine",
            "optimizer"
        ]
    )
    def test_pdf_processor_attribute_existence(self, default_pdf_processor, attribute):
        """
        GIVEN a PDFProcessor instance
        WHEN the instance is checked for the existence of a public attribute
        THEN expect the instance to possess that attribute.
        """
        assert hasattr(default_pdf_processor, attribute), \
            f"PDFProcessor instance did not have expected attribute '{attribute}'."

    @pytest.mark.parametrize(
        "attribute,expected_type",
        [
            ("storage", IPLDStorage),
            ("audit_logger", AuditLogger), 
            ("pipeline_version", str),
            ("logger", logging.Logger),
            ("integrator", GraphRAGIntegrator),
            ("ocr_engine", MultiEngineOCR),
            ("optimizer", LLMOptimizer)
        ]
    )
    def test_pdf_processor_attribute_type(self, default_pdf_processor, attribute, expected_type):
        """
        GIVEN a PDFProcessor instance
        WHEN the instance is checked for the type of a public attribute
        THEN expect the attribute to be of the correct type.
        """
        attr = getattr(default_pdf_processor, attribute)
        assert isinstance(attr, expected_type), \
            f"Expected attribute '{attribute}' to be of type {expected_type.__name__}, " \
            f"got {type(attr).__name__} instead."


    # def test_pdf_processor_monitor_monitor_attribute_type_is_monitoring_system_when_monitoring_is_enable(
    #     self, pdf_processor_enable_monitoring_is_true):
    #     """
    #     GIVEN a PDFProcessor instance with monitoring enabled
    #     WHEN the instance is checked for the type of the monitoring attribute
    #     THEN expect the monitoring attribute to be of type MonitoringSystem.
    #     """
    #     attr = getattr(pdf_processor_enable_monitoring_is_true, "monitoring")
    #     assert isinstance(attr, MonitoringSystem), \
    #         f"Expected attribute 'monitoring' to be of type MonitoringSystem, " \
    #         f"got {type(attr).__name__} instead."


    @pytest.mark.parametrize(
        "attribute",
        ["monitoring","query_engine",]
    )
    def test_pdf_processor_attribute_type_is_none(
        self, default_pdf_processor, attribute):
        """
        GIVEN a PDFProcessor instance
        WHEN the instance is checked for the type of attributes that should be NoneType
        THEN expect the attribute to be NoneType.
        """
        attr = getattr(default_pdf_processor, attribute)
        assert attr is None, \
            f"Expected attribute 'monitoring' to be of type MonitoringSystem, " \
            f"got {type(attr).__name__} instead."


@pytest.mark.parametrize(
    "method", ["process_pdf",]
)
class TestPdfProcessorHasRightPublicMethods:

    def test_pdf_processor_method_existence(self, default_pdf_processor, method):
        """
        GIVEN a PDFProcessor instance
        WHEN the instance is checked for the existence of a public method
        THEN expect the instance to possess that method.
        """
        assert hasattr(default_pdf_processor, method), \
            f"PDFProcessor instance did not have expected method '{method}'."

    def test_pdf_processor_method_is_instance_method(self, default_pdf_processor, method):
        """
        GIVEN a PDFProcessor instance
        WHEN a public method of the processor is checked.
        THEN expect
        """
        method_obj = getattr(default_pdf_processor, method)

        assert inspect.ismethod(method_obj), \
            f"Expected inspect.ismethod to be True for method '{method}', got False instead."

    def test_pdf_processor_method_is_coroutine(self, default_pdf_processor, method):
        """
        GIVEN a PDFProcessor instance
        WHEN a public method is checked to be a coroutine
        THEN expect the method to be a coroutine function.
        """
        method_obj = getattr(default_pdf_processor, method)

        assert inspect.iscoroutinefunction(method_obj) == True, \
            f"Expected inspect.iscoroutinefunction to return True for method '{method}', got False instead."



@pytest.fixture
def expected_valid_metadata_keys(valid_metadata):
    return list(valid_metadata["processing_metadata"].keys())

@pytest.fixture
def expected_valid_metadata_values(valid_metadata):
    return list(valid_metadata["processing_metadata"].values())


class TestPdfProcessorHappyPathValidMetadata:


    @pytest.mark.asyncio
    async def test_when_empty_dict_metadata_provided_then_status_is_success(
        self, 
        pdf_process_with_debug_logger, 
        valid_pdf_document,
        expected_status_success
    ):
        """
        GIVEN empty dict as metadata
        WHEN process_pdf is called
        THEN expect result status to be 'success'
        """
        empty_metadata = {}

        result = await pdf_process_with_debug_logger.process_pdf(valid_pdf_document, empty_metadata)

        assert result['status'] == expected_status_success


    @pytest.mark.asyncio
    async def test_when_valid_metadata_provided_then_status_is_success(
        self, 
        pdf_process_with_debug_logger, 
        valid_pdf_document,
        valid_metadata,
        expected_status_success
    ):
        """
        GIVEN metadata dict with valid metadata
        WHEN process_pdf is called
        THEN expect result status to be 'success'
        """
        result = await pdf_process_with_debug_logger.process_pdf(valid_pdf_document, valid_metadata)

        assert result['status'] == expected_status_success

    @pytest.mark.parametrize(
        "valid_key",
        [key for key in conftest.get_valid_metadata_keys()]
    )
    @pytest.mark.asyncio
    async def test_when_valid_metadata_provided_then_metadata_keys_in_result(
        self, 
        pdf_process_with_debug_logger, 
        valid_pdf_document,
        valid_metadata,
        valid_key,
    ):
        """
        GIVEN metadata dict with valid metadata
        WHEN process_pdf is called
        THEN expect all metadata keys to be present in the result under 'processing_metadata'
        """
        result = await pdf_process_with_debug_logger.process_pdf(valid_pdf_document, valid_metadata)

        result_metadata = result['processing_metadata']

        assert valid_key in result_metadata, f"'{valid_key}' key not in {result_metadata}"

    @pytest.mark.parametrize(
        "valid_key,valid_value",
        [(tup[0], tup[1]) for tup in conftest.get_valid_metadata_keys_values()]
    )
    @pytest.mark.asyncio
    async def test_when_valid_metadata_provided_then_metadata_values_in_result(
        self, 
        pdf_process_with_debug_logger, 
        valid_pdf_document,
        valid_metadata,
        valid_key,
        valid_value
    ):
        """
        GIVEN metadata dict with valid metadata
        WHEN process_pdf is called
        THEN expect all metadata values to be present in the result under 'processing_metadata'
        """
        result = await pdf_process_with_debug_logger.process_pdf(valid_pdf_document, valid_metadata)

        result_value = result['processing_metadata'][valid_key]

        assert valid_value == result_value, \
            f"'{valid_key}' value for key {valid_key} does not match processing_metadata value {result_value}"