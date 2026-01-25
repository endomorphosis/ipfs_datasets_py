
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

try:
    import PIL
except Exception:
    PIL = None


from ipfs_datasets_py.pdf_processing import PDFProcessor
from ipfs_datasets_py.ipld import IPLDStorage


from ipfs_datasets_py.audit import AuditLogger
from ipfs_datasets_py.monitoring import MonitoringSystem
try:
    from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
except Exception:
    LLMOptimizer = object
from ipfs_datasets_py.monitoring import MonitoringConfig, MetricsConfig
try:
    from ipfs_datasets_py.pdf_processing.ocr_engine import MultiEngineOCR
except Exception:
    MultiEngineOCR = object

try:
    from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
except Exception:
    LLMDocument = object
    LLMChunk = dict

try:
    from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
except Exception:
    QueryEngine = object

try:
    from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator
except Exception:
    GraphRAGIntegrator = object



@pytest.fixture
def test_constants():
    """Provide common test constants following example template pattern."""
    return {
        'PDF_PROCESSOR_CLASS': PDFProcessor,
        'NONE_VALUE': None,
        'NONE_TYPE': type(None),
        'IPLD_STORAGE_CLASS': IPLDStorage,
        'MONITORING_SYSTEM_CLASS': MonitoringSystem,
        'AUDIT_LOGGER_CLASS': AuditLogger,
        'LOGGER_CLASS': logging.Logger,
        'DICT_CLASS': dict,
        'TEST_KEY': 'test_key',
        'TEST_VALUE': 'test_value',
    }


@pytest.fixture
def expected_processing_stats_values():
    """Provide expected processing stats keys and their types."""
    return {
        "start_time": None,
        "end_time": None,
        "pages_processed": 0,
        "entities_extracted": 0,
    }


@pytest.fixture
def mock_ipld_storage():
    """Create a mock IPLDStorage instance for testing."""
    return MagicMock(spec=IPLDStorage)


# Mock IPLD storage fixture
@pytest.fixture
def real_ipld_storage():
    """Create a mock IPLDStorage instance for testing."""
    return IPLDStorage()


@pytest.fixture
def mock_logger():
    return MagicMock(spec_set=logging.Logger)


@pytest.fixture
def real_logger():
    """Logger that saves to a log file in 'logs' folder in the current working directory."""
    
    # Create logs directory if it doesn't exist
    logs_dir = Path.cwd() / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Create logger
    logger = logging.getLogger("vertical_slice_logger")
    logger.setLevel(logging.DEBUG)

    # Remove existing handlers to avoid duplicates
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create file handler
    log_file = logs_dir / "test_pdf_processor.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)

    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')
    file_handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(file_handler)

    return logger


@pytest.fixture
def default_logger():
    return logging.getLogger("pdf_processor")


@pytest.fixture
def default_pdf_processor_parameters(default_logger):
    # NOTE These are exact copies of the default arguments for PDFProcessor.__init__()
    return {
        "storage": None,
        "enable_monitoring": False,
        "enable_audit": True,
        "logger": default_logger
    }


@pytest.fixture
def default_pdf_processor() -> PDFProcessor:
    """Default instance of PDF processor. No mocking, no patching, all real."""
    return PDFProcessor()


@pytest.fixture
def pdf_processor_with_custom_storage(real_ipld_storage):
    """Create PDFProcessor with custom storage."""
    return PDFProcessor(storage=real_ipld_storage)


@pytest.fixture
def pdf_process_with_debug_logger(real_logger):
    """Create PDFProcessor with a real logger that logs to file."""
    return PDFProcessor(logger=real_logger)


def _make_processor(**kwargs):
    """Factory function to create PDFProcessor fixtures with custom parameters."""
    @pytest.fixture
    def _processor():
        return PDFProcessor(**kwargs)
    return _processor


pdf_processor_with_monitoring_enabled = _make_processor(enable_monitoring=True)
pdf_processor_with_monitoring_disabled = _make_processor(enable_monitoring=False)
pdf_processor_with_audit_enabled = _make_processor(enable_audit=True)
pdf_processor_with_audit_disabled = _make_processor(enable_audit=False)
pdf_processor_with_all_options_enabled = _make_processor(enable_monitoring=True, enable_audit=True)
pdf_processor_with_all_options_disabled = _make_processor(enable_monitoring=False, enable_audit=False)


@pytest.fixture
def processors(
    default_pdf_processor,
    pdf_processor_with_custom_storage,
    pdf_process_with_debug_logger,
    pdf_processor_with_monitoring_enabled,
    pdf_processor_with_monitoring_disabled,
    pdf_processor_with_audit_enabled,
    pdf_processor_with_audit_disabled,
    pdf_processor_with_all_options_enabled,
    pdf_processor_with_all_options_disabled
):
    return {
        "default": default_pdf_processor,
        "custom_storage": pdf_processor_with_custom_storage,
        "debug_logger": pdf_process_with_debug_logger,
        "monitoring_enabled": pdf_processor_with_monitoring_enabled,
        "monitoring_disabled": pdf_processor_with_monitoring_disabled,
        "audit_enabled": pdf_processor_with_audit_enabled,
        "audit_disabled": pdf_processor_with_audit_disabled,
        "all_options_enabled": pdf_processor_with_all_options_enabled,
        "all_options_disabled": pdf_processor_with_all_options_disabled
    }
