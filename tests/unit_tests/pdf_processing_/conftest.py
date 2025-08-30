
import logging
import inspect
import os
from pathlib import Path
import stat


import pytest


from ipfs_datasets_py.pdf_processing import (
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


import reportlab
import PIL
from reportlab.pdfgen import canvas


import pytest
from pathlib import Path
from reportlab.pdfgen import canvas


VALID_METADATA = {
    "source": "test",
    "priority": "high",
    "category": "document"
}


@pytest.fixture
def valid_metadata():
    return VALID_METADATA

def get_valid_metadata_keys():
    # Duplicate the fixture data structure
    return list(VALID_METADATA.keys())


def get_valid_metadata_values():
    # Duplicate the fixture data structure
    return list(VALID_METADATA.values())


def get_valid_metadata_keys_values():
    # Duplicate the fixture data structure
    return [(key, value) for key, value in VALID_METADATA.items()]



@pytest.fixture
def text_in_the_image():
    return "Hello world!"


def  text_with_entities_in_image():
    lines = (
        "Barack Obama was the 44th President of the United States.",
        "Michelle Obama was the First Lady.",
        "They have two daughters, Malia and Sasha."
    )
    return lines


@pytest.fixture
def valid_pdf_document_path(tmp_path):
    path = tmp_path / "valid_pdf_document.pdf"
    return path


@pytest.fixture
def expected_page_count():
    return 3  # Simple integer instead of a function


@pytest.fixture
def expected_status_success():
    return "success"


@pytest.fixture
def expected_status_error():
    return "error"


@pytest.fixture
def expected_text() -> tuple[str, ...]:
    lines = (
        "Hello my baby!",
        "Hello my honey!",
        "Hello my rag-time gal!"
    )
    return lines


@pytest.fixture
def expected_text_zero_entities() -> tuple[str, ...]:
    lines = (
        "99 bottles of beer on the wall, 99 bottles of beer.",
        "Take one down, pass it around.",
        "98 bottles of beer on the wall.",
    )
    return lines


@pytest.fixture
def expected_text_with_one_entity() -> tuple[str, ...]:
    lines = (
        "Hitler is a man.",
        "No man can survive falling into lava.",
        "Therefore, Hitler cannot survive falling into lava",
    )
    return lines


@pytest.fixture
def expected_text_with_two_entities() -> tuple[str, ...]:
    lines = (
        "Socrates is a man.",
        "John Madden is a man.",
        "All men are mortal.",
        "Therefore, Socrates and John Madden are mortal."
    )
    return lines


@pytest.fixture  # Added missing decorator
def expected_text_with_two_entities_with_close_connection() -> tuple[str, ...]:
    lines = (
        "Franklin Delano Roosevelt was president.",
        "Theodore Roosevelt was a relative of Franklin Delano Roosevelt.",
        "Therefore, Theodore Roosevelt is related to a president."
    )
    return lines


@pytest.fixture  # Added missing decorator
def expected_text_with_two_entities_with_weak_connection() -> tuple[str, ...]:
    lines = (
        "Big Floppa is a cat.",
        "The Andromeda galaxy is vast.",
        "Therefore, they are unrelated."
    )
    return lines


@pytest.fixture
def valid_pdf_document(valid_pdf_document_path, expected_page_count, expected_text):
    """
    Creates a valid PDF document with the specified number of pages and text content.
    
    Args:
        valid_pdf_document_path: Path where the PDF should be created
        expected_page_count: Number of pages to create (now an integer)
        expected_text: Tuple of text lines to add to each page
        
    Returns:
        Path: Path to the created PDF document
    """
    c = canvas.Canvas(str(valid_pdf_document_path))
    
    # Create the specified number of pages
    for page_num in range(expected_page_count):
        y = 750  # Starting y-position for text
        for line in expected_text:
            c.drawString(72, y, line)  # 72 points = 1 inch margin
            y -= 20  # Move down 20 points for next line
        c.showPage()  # Create new page
    
    c.save()
    return valid_pdf_document_path



@pytest.fixture
def no_read_permissions_file(tmp_path) -> str:
    """Create file with no read permissions."""
    test_file = tmp_path / "no_read_perms.pdf"
    test_file.write_text("test content")
    
    # Remove read permissions
    current_mode = test_file.stat().st_mode
    test_file.chmod(current_mode & ~stat.S_IREAD)
    
    return test_file


@pytest.fixture
def default_ipld_storage():
    return IPLDStorage()


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
def pdf_processor_enable_monitoring_is_true():
    return PDFProcessor(enable_monitoring=True)

@pytest.fixture
def pdf_processor_enable_monitoring_is_false():
    return PDFProcessor(enable_monitoring=False)

@pytest.fixture
def default_pdf_processor() -> PDFProcessor:
    """Default instance of PDF processor. No mocking, no patching, all real."""
    return PDFProcessor()

@pytest.fixture
def file_logger():
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
def pdf_process_with_debug_logger(file_logger):
    return PDFProcessor(logger=file_logger)
