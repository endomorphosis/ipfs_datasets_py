#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py
# Auto-generated on 2025-07-07 02:28:56"
from __future__ import annotations

import anyio
from unittest.mock import MagicMock


import pytest
import os


from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor

# Check if each classes methods are accessible:
assert PDFProcessor.process_pdf
assert PDFProcessor._validate_and_analyze_pdf
assert PDFProcessor._decompose_pdf
assert PDFProcessor._extract_page_content
assert PDFProcessor._create_ipld_structure
assert PDFProcessor._process_ocr
assert PDFProcessor._optimize_for_llm
assert PDFProcessor._extract_entities
assert PDFProcessor._create_embeddings
assert PDFProcessor._integrate_with_graphrag
assert PDFProcessor._analyze_cross_document_relationships
assert PDFProcessor._setup_query_interface
assert PDFProcessor._calculate_file_hash
assert PDFProcessor._extract_native_text
assert PDFProcessor._get_processing_time
assert PDFProcessor._get_quality_scores

# Check if the modules's imports are accessible:
import logging
import hashlib
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from contextlib import nullcontext
import stat

from unittest.mock import AsyncMock, Mock, MagicMock


# Optional deps used by the PDF pipeline. These tests are expected to run in
# minimal environments, so keep imports soft.
try:
    import fitz as pymupdf  # PyMuPDF
except Exception:
    pymupdf = None

try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    from PIL import Image
except Exception:
    Image = None

from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.audit import AuditLogger
from ipfs_datasets_py.monitoring import MonitoringSystem
try:
    from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
except Exception:
    LLMOptimizer = object

try:
    from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator
except Exception:
    GraphRAGIntegrator = object
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



from typing import  Tuple, Generator
from pathlib import Path
import tempfile
from enum import Enum
from dataclasses import dataclass


try:
    try:
        import PIL
    except Exception:
        PIL = None
except Exception:
    PIL = None
try:
    import reportlab
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
except Exception:
    reportlab = None
    canvas = None
    letter = None

try:
    import faker
except Exception:
    faker = None


class _FallbackFaker:
    def seed_instance(self, seed: int) -> None:
        return None

    def name(self) -> str:
        return "Test Author"

try:
    from tests.unit_tests.pdf_processing_.graphrag_integrator_.conftest import (
        real_integrator,
    )
except Exception:
    real_integrator = None

    @pytest.fixture
    def real_integrator():
        return MagicMock(name="real_integrator")

from contextlib import contextmanager


from ipfs_datasets_py.audit import AuditLogger
from ipfs_datasets_py.monitoring import MonitoringSystem
from ipfs_datasets_py.ipld import IPLDStorage
from io import BytesIO

try:
    from reportlab.graphics import renderPM
except Exception:
    renderPM = None


SEED = 420

@pytest.fixture(autouse=True)
def faker_fixed_seed():
    if faker is None:
        fake = _FallbackFaker()
        fake.seed_instance(SEED)
        return fake

    fake = faker.Faker()
    fake.seed_instance(SEED)
    return fake


@pytest.fixture
def test_constants(tmp_path, faker_fixed_seed):
    return {
        "sample_text": "This is a sample text for PDF processing tests.",
        "sample_image_text": "Sample Image",
        "sample_metadata": {
            "author": faker_fixed_seed.name(),
            "title": "Test PDF Document",
            "subject": "PDF Processing Unit Tests",
            "keywords": "pdf, test, unit test"
        },
        "sample_image_path": tmp_path / "test_image.png",
        "sample_pdf_path": tmp_path / "test_document.pdf",
        "page_size": letter,
        "image_paths": {
            "png": tmp_path / "test_image.png"
        },
        "pdf_paths": {
            "valid": tmp_path / "valid.pdf",
            "invalid": tmp_path / "invalid.pdf",
            "encrypted": tmp_path / "encrypted.pdf",
            "corrupted": tmp_path / "corrupted.pdf",
            "no_read_perms": tmp_path / "no_read_perms.pdf",
            "empty": tmp_path / "empty.pdf",
            "unsupported_version": tmp_path / "unsupported_version.pdf",
            "image": tmp_path / "image.pdf",
            "flat": tmp_path / "flat.pdf",
            "scanned": tmp_path / "scanned.pdf",
            "zero_pages": tmp_path / "zero_pages.pdf",
            "fake": tmp_path / "fake.pdf",
            "locked": tmp_path / "locked.pdf",
            "not_a_pdf": tmp_path / "not_a_pdf.txt"
        },
    }

CUSTOM_METADATA = {
    "ligma": "Ligma what?",
    "sugma": 69,
    "sawcon": ["buffa", "deeze", "nutz"]
}

@pytest.fixture
def custom_metadata():
    CUSTOM_METADATA 

INVALID_PATHS = {
    "non_existent": Path("/path/to/non_existent_file.pdf"),
    "directory_instead_of_file": Path("/path/to/directory/"),
    "unsupported_format": Path("/path/to/unsupported_file.txt"),
    "url": Path("http://example.com/document.pdf"),
    "empty_path": Path(""),
    "whitespace_path": Path("   "),
}

@pytest.fixture
def invalid_paths():
    """Fixture providing various invalid file paths."""
    return INVALID_PATHS

# ==========================================
# TEXT CONTENT FIXTURES
# ==========================================


@pytest.fixture
def text_in_the_image():
    """Simple text content for image OCR testing."""
    return "Hello world!"


@pytest.fixture
def text_with_entities_in_image():
    """Text content with named entities for testing entity extraction."""
    lines = (
        "Barack Obama was the 44th President of the United States.",
        "Michelle Obama was the First Lady.",
        "They have two daughters, Malia and Sasha."
    )
    return lines


@pytest.fixture
def expected_text() -> tuple[str, ...]:
    """Expected text content for standard PDF documents."""
    lines = (
        "Hello my baby!",
        "Hello my honey!",
        "Hello my rag-time gal!"
    )
    return lines


@pytest.fixture
def expected_text_zero_entities() -> tuple[str, ...]:
    """Text content with no named entities for testing."""
    lines = (
        "99 bottles of beer on the wall, 99 bottles of beer.",
        "Take one down, pass it around.",
        "98 bottles of beer on the wall.",
    )
    return lines


@pytest.fixture
def expected_text_with_one_entity() -> tuple[str, ...]:
    """Text content with exactly one named entity for testing."""
    lines = (
        "Hitler is a man.",
        "No man can survive falling into lava.",
        "Therefore, Hitler cannot survive falling into lava",
    )
    return lines


@pytest.fixture
def expected_text_with_two_entities() -> tuple[str, ...]:
    """Text content with two named entities for testing."""
    lines = (
        "Socrates is a man.",
        "John Madden is a man.",
        "All men are mortal.",
        "Therefore, Socrates and John Madden are mortal."
    )
    return lines


@pytest.fixture
def expected_text_with_two_entities_with_close_connection() -> tuple[str, ...]:
    """Text content with two closely connected entities for relationship testing."""
    lines = (
        "Franklin Delano Roosevelt was president.",
        "Theodore Roosevelt was a relative of Franklin Delano Roosevelt.",
        "Therefore, Theodore Roosevelt is related to a president."
    )
    return lines


@pytest.fixture
def expected_text_with_two_entities_with_weak_connection() -> tuple[str, ...]:
    """Text content with two weakly connected entities for relationship testing."""
    lines = (
        "Big Floppa is a cat.",
        "The Andromeda galaxy is vast.",
        "Therefore, they are unrelated."
    )
    return lines


@pytest.fixture
def text_fixtures_dict(
    text_in_the_image,
    text_with_entities_in_image,
    expected_text,
    expected_text_zero_entities,
    expected_text_with_one_entity,
    expected_text_with_two_entities,
    expected_text_with_two_entities_with_close_connection,
    expected_text_with_two_entities_with_weak_connection
):
    """Dictionary containing all text fixtures."""
    return {
        "text_in_the_image": text_in_the_image,
        "text_with_entities_in_image": text_with_entities_in_image,
        "expected_text": expected_text,
        "expected_text_zero_entities": expected_text_zero_entities,
        "expected_text_with_one_entity": expected_text_with_one_entity,
        "expected_text_with_two_entities": expected_text_with_two_entities,
        "expected_text_with_two_entities_with_close_connection": expected_text_with_two_entities_with_close_connection,
        "expected_text_with_two_entities_with_weak_connection": expected_text_with_two_entities_with_weak_connection
    }


# ==========================================
# PDF DOCUMENT FIXTURES
# ==========================================


def _make_mock_pdf(c: canvas.Canvas, pdf_elements):
    # Create a simple PDF with test content
    for x, y, text in pdf_elements:
        c.drawString(x, y, text)
    return c


def _make_pdf_image(c: canvas.Canvas, draw_string_args, draw_image_args, draw_image_kwargs):
    c.drawString(*draw_string_args)
    c.drawImage(*draw_image_args, **draw_image_kwargs)
    return c


@contextmanager
def _make_canvas(path: Path, page_size: Tuple[int, int]) -> Generator[canvas.Canvas, None, None]:
    c = None
    try:
        c = canvas.Canvas(str(path), pagesize=page_size)
        yield c
    except Exception as e:
        raise RuntimeError(f"Failed to create canvas: {e}") from e
    finally:
        if c is not None:
            c.save()


## Basic Valid PDF files.

@pytest.fixture
def sample_metadata(test_constants):
    return test_constants["sample_metadata"]

@pytest.fixture
def paths(test_constants):
    return test_constants['pdf_paths']

@pytest.fixture
def pagesize(test_constants):
    return test_constants["page_size"]

@pytest.fixture
def pdf_elements(test_constants, sample_metadata):
    x = 100
    return [
        (x, 700, f"Author: {sample_metadata['author']}"),
        (x, 650, f"Title: {sample_metadata['title']}"),
        (x, 600, f"Subject: {sample_metadata['subject']}"),
        (x, 550, f"Keywords: {sample_metadata['keywords']}"),
        (x, 500, test_constants["sample_text"]),
    ]



def make_pdf_elements(name: str):
    """Fixture factory to create PDF elements based on test constants."""
    @pytest.fixture
    def _pdf_elements(test_constants):
        assert len(test_constants[name]) == 3, "Test constant must have exactly three lines of text."
        x = 100
        first, second, third = test_constants[name]
        return [
            (x, 700, first),
            (x, 650, second),
            (x, 600, third),
        ]
    return _pdf_elements


pdf_file_with_zero_entities = make_pdf_elements("expected_text_zero_entities")
pdf_file_with_one_entity = make_pdf_elements("expected_text_with_one_entity")
pdf_file_with_two_entities = make_pdf_elements("expected_text_with_two_entities")
pdf_file_with_two_entities_with_close_connection = make_pdf_elements("expected_text_with_two_entities_with_close_connection")
pdf_file_with_two_entities_with_weak_connection = make_pdf_elements("expected_text_with_two_entities_with_weak_connection")
pdf_file_with_image = make_pdf_elements("text_in_the_image")
pdf_file_with_entities_in_image = make_pdf_elements("text_with_entities_in_image")
large_pdf_file = make_pdf_elements("expected_text")  # Reuse expected_text for large PDF base content



@pytest.fixture
def image_elements(paths):
    return {
        "draw_string": (100, 750, "Sample Text with Image"),
        "draw_image": {
            "args": (paths["image"], 100, 500),
            "kwargs": {"width": 200, "height": 150}
        }
    }


@pytest.fixture
def mock_pdf_file(paths, pagesize, pdf_elements) -> Path:
    """Create a mock PDF file for testing purposes."""
    path = paths['valid']
    with _make_canvas(path, pagesize) as c:
        _ = _make_mock_pdf(c, pdf_elements)

    return path


@pytest.fixture
def valid_pdf_file(paths, pagesize, pdf_elements) -> Path:
    """Create a valid PDF file for testing purposes."""
    path = paths['valid']
    with _make_canvas(path, pagesize) as c:
        _ = _make_mock_pdf(c, pdf_elements)

    return path




@pytest.fixture
def mock_pdf_file_with_image(pdf_elements, image_elements, paths, pagesize) -> Path:
    """Create a mock PDF file with a text image for testing purposes."""
    # General pdf elements
    path = paths["image"]

    # PDF image elements
    args = image_elements["draw_string"], image_elements["draw_image"]["args"], image_elements["draw_image"]["kwargs"]

    with _make_canvas(path, pagesize) as c:
        c = _make_mock_pdf(c, pdf_elements)
        _ = _make_pdf_image(c, *args)

    return path


@pytest.fixture
def not_a_pdf_file(paths) -> str:
    """Create a text file."""
    fake_pdf = paths['not_a_pdf']
    fake_pdf.write_text("This is not a PDF file, just plain text.")
    return str(fake_pdf)


@pytest.fixture
def fake_pdf_file(paths) -> str:
    """Create text file with PDF extension."""
    fake_pdf = paths['fake']
    fake_pdf.write_text("This is not a PDF file, just plain text with a PDF extension.")
    return str(fake_pdf)


@pytest.fixture
def no_read_permissions_pdf_file(mock_pdf_file, pdf_elements, paths, pagesize) -> Path:
    """Create a PDF file with no read permissions."""
    path = paths['no_read_perms']
    with _make_canvas(path, pagesize) as c:
        _ = _make_mock_pdf(c, pdf_elements)

    # Remove read permissions
    current_mode = mock_pdf_file.stat().st_mode
    mock_pdf_file.chmod(current_mode & ~0o444)  # Remove read permissions for all

    return mock_pdf_file


@pytest.fixture
def locked_pdf_file(paths, pagesize, pdf_elements):
    """Simulate a PDF file locked by another process."""
    path = paths['locked']
    with _make_canvas(path, pagesize) as c:
        _ = _make_mock_pdf(c, pdf_elements)

    # Open the file in write mode to simulate it being locked
    assert os.path.getsize(path) > 0, "File should not be empty"
    print(f"Locked file path: {path}, size: {os.path.getsize(path)} bytes")
    file_handle = None
    try:
        file_handle = open(path, 'a')
        yield path
    except Exception as e:
        raise RuntimeError(f"Failed to lock the file: {e}") from e
    finally:
        if file_handle is not None:
            file_handle.close()



@pytest.fixture
def corrupted_pdf_file(paths, pagesize, pdf_elements) -> Path:
    """Create a corrupted PDF file for testing purposes."""
    path = paths['corrupted']
    with _make_canvas(path, pagesize) as c:
        _ = _make_mock_pdf(c, pdf_elements)

    # Corrupt the PDF by truncating its content
    with open(path, 'r+b') as f:
        f.truncate(10)  # Truncate to 10 bytes to corrupt

    return path


@contextmanager
def _pymupdf_open(path: Path):
    doc = None
    try:
        doc = pymupdf.open(str(path))
        yield doc
    finally:
        if doc is not None:
            doc.close()


@pytest.fixture
def encrypted_pdf_file(paths, pagesize, pdf_elements) -> Path:
    """Create an encrypted PDF file for testing purposes."""
    path = paths["encrypted"]

    # Create the PDF with password protection
    with _make_canvas(path, pagesize) as c:
        _ = _make_mock_pdf(c, pdf_elements)

    with _pymupdf_open(path) as doc:
        # Create a temporary path for the encrypted version
        encrypted_path = path.with_suffix('.encrypted.pdf')

        # Encrypt with standard security - save to a different file first
        doc.save(
            str(encrypted_path),
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw="user123",  # Set user password (for opening)
            owner_pw="owner456",  # Set owner password (for permissions)
            permissions=pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_COPY
        )

    # Move the encrypted file to the expected location
    encrypted_path.rename(path)

    return path


@pytest.fixture
def unsupported_version_pdf_file(paths, pagesize, pdf_elements) -> Path:
    """Create a PDF file with an unsupported PDF version for testing purposes."""
    path = paths["unsupported_version"]
    current_version = b'%PDF-1.3'
    unsupported_version = b'%PDF-9.0'  # Intentionally invalid version

    with _make_canvas(path, pagesize) as c:
        _ = _make_mock_pdf(c, pdf_elements)

    # Modify the PDF header to simulate an unsupported version
    with open(path, 'r+b') as f:
        content = f.read()
        # Replace PDF header with unsupported version
        modified_content = content.replace(current_version, unsupported_version, 1)
        f.seek(0)
        f.write(modified_content)
        f.truncate()
    return path


@pytest.fixture
def empty_pdf_file(paths) -> str:
    """Create empty PDF file."""
    empty_pdf = paths['empty']
    c = canvas.Canvas(str(empty_pdf))
    c.showPage()
    c.save()
    return str(empty_pdf)


@pytest.fixture
def zero_pages_pdf_file(paths) -> str:
    """Create PDF with zero pages."""
    zero_pages_pdf = paths['zero_pages']

    # Create a PDF document but don't add any pages
    c = canvas.Canvas(str(zero_pages_pdf))
    # Add some metadata so that it isn't completely empty.
    c.setAuthor("Test Author")
    # Don't call showPage() or add any content
    c.save()

    return str(zero_pages_pdf)


@pytest.fixture
def flat_pdf_file(valid_pdf_file, paths) -> Path:
    """Create a mock flat PDF file, using the valid_pdf_file as a base."""

    # Open the PDF
    doc = pymupdf.open(str(valid_pdf_file))

    with _pymupdf_open(valid_pdf_file) as doc:

        # Create new PDF
        new_doc = pymupdf.open()

        for page_num in range(len(doc)):
            page = doc[page_num]

            # Render page as image
            mat = pymupdf.Matrix(2.0, 2.0)  # 2x scale for better quality
            pix = page.get_pixmap(matrix=mat)

            # Create new page and insert image
            new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, pixmap=pix)

        # Save flattened PDF
        new_doc.save(str(paths["flat"]))
        new_doc.close()


@pytest.fixture
def no_read_permissions_file(paths, pagesize, pdf_elements) -> str:
    """Create file with no read permissions."""
    path = paths['no_read_perms']

    with _make_canvas(path, pagesize) as c:
        _ = _make_mock_pdf(c, pdf_elements)

    # Remove read permissions
    current_mode = path.stat().st_mode
    path.chmod(current_mode & ~stat.S_IREAD)

    return str(path)


# Error message constants for PDF validation
EXPECTED_PYMUPDF_ERROR_MESSAGE = "pymupdf could not open PDF file" 
# NOTE Pymupdf doesn't have very specific error messages, so we use a general one instead.
EXPECTED_UNSUPPORTED_VERSION_MESSAGE = "PDF File is an unsupported version"
EXPECTED_INVALID_PDF_MESSAGE = "PDF file does not have a '.pdf' extension"
EXPECTED_CORRUPTED_PDF_MESSAGE = "PDF file is corrupted or malformed"
EXPECTED_EMPTY_PDF_MESSAGE = "Cannot open empty file"
EXPECTED_ENCRYPTED_PDF_MESSAGE = "PDF file is encrypted"
EXPECTED_ZERO_PAGES_MESSAGE = "PDF file has zero pages"
EXPECTED_NO_READ_PERMISSIONS_MESSAGE = "Insufficient permissions to read PDF file"


BAD_PDF_FILES = {
    "no_read_permissions_pdf_file": {
        "msg": EXPECTED_NO_READ_PERMISSIONS_MESSAGE
    },
    "corrupted_pdf_file": {
        "msg": EXPECTED_CORRUPTED_PDF_MESSAGE
    },
    "encrypted_pdf_file": {
        "msg": EXPECTED_ENCRYPTED_PDF_MESSAGE
    },
    "empty_pdf_file": {
        "msg": EXPECTED_EMPTY_PDF_MESSAGE
    },
    "unsupported_version_pdf_file": {
        "msg": EXPECTED_UNSUPPORTED_VERSION_MESSAGE
    },
    "not_a_pdf_file": {
        "msg": EXPECTED_INVALID_PDF_MESSAGE
    },
    "zero_pages_pdf_file": {
        "msg": EXPECTED_ZERO_PAGES_MESSAGE
    },
}

def get_error_messages():
    return {
        key: value['msg'] for key, value in BAD_PDF_FILES.items()
    }

@pytest.fixture
def bad_pdf_files(
        no_read_permissions_pdf_file,
        corrupted_pdf_file,
        encrypted_pdf_file,
        empty_pdf_file,
        unsupported_version_pdf_file,
        not_a_pdf_file,
        request
        ):
    """Create various bad PDF files for testing purposes."""
    _bad_pdf_files = {}
    for key in BAD_PDF_FILES.keys():
        try:
            fixture = request.getfixturevalue(key)
        except Exception as e:
            raise RuntimeError(f"Failed to get fixture '{key}': {e}") from e
        _bad_pdf_files[key] = {'file': fixture}
    return _bad_pdf_files



def get_error_messages():
    return {
        key: value['msg'] for key, value in BAD_PDF_FILES.items()
    }








@pytest.fixture
def expected_messages():
    """Fixture providing expected error messages for various invalid PDF scenarios."""
    return get_error_messages()
 


@pytest.fixture
def valid_pdf_document_path(tmp_path):
    path = tmp_path / "valid_pdf_document.pdf"
    return path


@pytest.fixture
def expected_page_count():
    """Number of pages for test PDF documents."""
    return 3


@pytest.fixture
def valid_pdf_document(valid_pdf_document_path, expected_page_count, expected_text):
    """A valid PDF document with the specified number of pages and text content."""
    if canvas is None:
        # Minimal PDF-like structure sufficient for mock-mode parsing in tests.
        pages = b"\n".join([b"/Type /Page" for _ in range(expected_page_count)])
        content = (
            b"%PDF-1.4\n"
            + b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            + b"2 0 obj\n<< /Type /Pages /Count "
            + str(expected_page_count).encode("ascii")
            + b" >>\nendobj\n"
            + pages
            + b"\n%%EOF\n"
        )
        valid_pdf_document_path.write_bytes(content)
        return valid_pdf_document_path

    x = 72  # 72 points = 1 inch margin
    start_at = 750  # Starting y-position for text
    move_down = 20  # Move down 20 points for each line
    c = canvas.Canvas(str(valid_pdf_document_path))

    # Create the specified number of pages
    for page_num in range(expected_page_count):
        y = start_at  
        for line in expected_text:
            c.drawString(x, y, line)  
            y -= move_down
        c.showPage()  # Create new page

    c.save()
    return valid_pdf_document_path


@pytest.fixture
def real_init_params_for_pdf_processor():
    return {
        "ipld_storage": IPLDStorage(),
        "enable_monitoring": True,
        "enable_audit": True,
        "logger": logging.getLogger("pdf_processor_test_logger"),
    }

@pytest.fixture
def real_pdf_processor_defaults():
    """Fixture to provide a real PDFProcessor instance."""
    return PDFProcessor()

@pytest.fixture
def real_pdf_processor_init_params(real_init_params_for_pdf_processor):
    return PDFProcessor(**real_init_params_for_pdf_processor)

@pytest.fixture
def mock_ipld_storage():
    return MagicMock(spec=IPLDStorage)

@pytest.fixture
def real_ipld_storage():
    return IPLDStorage()

@pytest.fixture
def mock_init_params_for_pdf_processor():
    """Fixture to provide mock initialization parameters for PDFProcessor."""
    return {
        "ipld_storage": MagicMock(spec=IPLDStorage),
        "enable_monitoring": True,
        "enable_audit": True,
        "logger": MagicMock(spec=logging.Logger),
    }

@pytest.fixture
def mock_pdf_processor(mock_init_params_for_pdf_processor):
    return PDFProcessor(**mock_init_params_for_pdf_processor)

@pytest.fixture
def default_pdf_processor() -> PDFProcessor:
    return PDFProcessor()

@pytest.fixture
def mock_logger():
    mock_logger = MagicMock(spec=logging.Logger)
    mock_logger.level = logging.DEBUG
    return mock_logger

@pytest.fixture
def real_logger():
    return logging.getLogger("pdf_test_logger")


@pytest.fixture
def mock_pdf_processor(
    mock_ipld_storage,
    mock_audit_logger,
    mock_monitoring_system,
    mock_graphrag_integrator,
    mock_ocr_engine,
    mock_llm_optimizer,
    mock_query_engine
):
    """PDF processor with all dependencies mocked for testing."""
    mock_dict = {
        'storage': mock_ipld_storage,
        'audit_logger': mock_audit_logger,
        'monitoring': mock_monitoring_system,
        'integrator': mock_graphrag_integrator,
        'ocr_engine': mock_ocr_engine,
        'optimizer': mock_llm_optimizer,
        'query_engine': mock_query_engine
    }

    return PDFProcessor(
        enable_monitoring=False,
        enable_audit=False,
        mock_dict=mock_dict
    )





# ==========================================
# CONSTANTS AND TEST DATA
# ==========================================

VALID_METADATA = {
    "source": "test",
    "priority": "high",
    "category": "document"
}

# Helper functions for metadata (not fixtures)
def get_valid_metadata_keys():
    """Helper function to get metadata keys."""
    return list(VALID_METADATA.keys())

def get_valid_metadata_values():
    """Helper function to get metadata values."""
    return list(VALID_METADATA.values())

def get_valid_metadata_keys_values():
    """Helper function to get metadata key-value pairs."""
    return [(key, value) for key, value in VALID_METADATA.items()]


# ==========================================
# BASIC TEST FIXTURES
# ==========================================

@pytest.fixture
def additional_test_constants():
    """Provide additional test constants following example template pattern."""
    return {
        'NONE_VALUE': None,
        'PROCESSING_STATS_KEY_COUNT': 4,
        'TEST_KEY': 'test_key',
        'TEST_VALUE': 'test_value',
    }


@pytest.fixture
def valid_metadata():
    """Provide valid metadata dictionary."""
    return VALID_METADATA


@pytest.fixture
def expected_processing_stats_values():
    """Expected default values for processing_stats dictionary."""
    return {
        "start_time": None,
        "end_time": None,
        "pages_processed": 0,
        "entities_extracted": 0
    }


# ==========================================
# MOCK FIXTURES FOR DEPENDENCIES
# ==========================================


@pytest.fixture
def mock_monitoring_system():
    """Mock monitoring system with public method mocks."""
    mock_monitoring = MagicMock(spec=MonitoringSystem)
    mock_monitoring.monitor_context = MagicMock()
    mock_monitoring.record_metric = Mock()
    mock_monitoring.increment_counter = Mock()
    mock_monitoring.record_histogram = Mock()
    mock_monitoring.start_timer = Mock()
    mock_monitoring.stop_timer = Mock()
    
    return mock_monitoring


@pytest.fixture
def mock_graphrag_integrator():
    """Mock GraphRAG integrator with public method mocks."""

    mock_integrator = MagicMock(spec=GraphRAGIntegrator)
    # Mock public async methods from the stubs
    mock_integrator.integrate_document = AsyncMock(return_value={
        'graph_id': 'test_graph_123',
        'document_id': 'test_doc_456',
        'entities': [],
        'relationships': [],
        'chunks': [],
        'metadata': {},
        'creation_timestamp': '2024-01-01T00:00:00Z',
        'ipld_cid': 'test_cid_789'
    })
    mock_integrator.query_graph = AsyncMock(return_value={
        'query': 'test_query',
        'entities': [],
        'relationships': [],
        'total_matches': 0,
        'extracted_entities': [],
        'timestamp': '2024-01-01T00:00:00Z'
    })
    mock_integrator.get_entity_neighborhood = AsyncMock(return_value={
        'center_entity_id': 'test_entity',
        'depth': 2,
        'nodes': [],
        'edges': [],
        'node_count': 0,
        'edge_count': 0
    })
    
    return mock_integrator


@pytest.fixture
def mock_ocr_engine():
    """Mock OCR engine with public method mocks."""
    mock_ocr = Mock(spec=MultiEngineOCR)
    mock_ocr.process_image = AsyncMock(return_value={
        'text': 'extracted text',
        'confidence': 0.95,
        'coordinates': [],
        'metadata': {}
    })
    mock_ocr.process_images = AsyncMock(return_value=[])
    mock_ocr.get_supported_formats = Mock(return_value=['png', 'jpg', 'pdf'])
    mock_ocr.set_language = Mock()
    mock_ocr.get_engine_status = Mock(return_value={'status': 'ready'})

    return mock_ocr


@pytest.fixture
def mock_llm_optimizer():
    """Mock LLM optimizer with public method mocks."""
    from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_document.llm_document_factory import (
        LLMDocument, LLMDocumentTestDataFactory as Factory
    )
    mock_optimizer = MagicMock(spec=LLMOptimizer)
    mock_llm_document = Factory.create_document_instance()

    # Create a mock LLMDocument return value
    mock_optimizer.optimize_for_llm = AsyncMock(return_value=mock_llm_document)
    mock_optimizer.embedding_model = "test-embedding-model"

    return mock_optimizer


@pytest.fixture
def mock_query_engine():
    """Mock query engine with public method mocks."""
    mock_engine = MagicMock(spec=QueryEngine)
    mock_engine.setup = AsyncMock()
    return mock_engine


@pytest.fixture
def mock_pdf_processor(
    mock_ipld_storage,
    mock_audit_logger,
    mock_monitoring_system,
    mock_graphrag_integrator,
    mock_ocr_engine,
    mock_llm_optimizer,
    mock_query_engine
):
    """PDF processor with all dependencies mocked for testing."""
    mock_dict = {
        'storage': mock_ipld_storage,
        'audit_logger': mock_audit_logger,
        'monitoring': mock_monitoring_system,
        'integrator': mock_graphrag_integrator,
        'ocr_engine': mock_ocr_engine,
        'optimizer': mock_llm_optimizer,
        'query_engine': mock_query_engine
    }
    
    return PDFProcessor(
        enable_monitoring=False,
        enable_audit=False,
        mock_dict=mock_dict
    )


# ==========================================
# CONSTANTS AND TEST DATA
# ==========================================


# Dictionary fixtures
@pytest.fixture
def processor_dict(
        default_pdf_processor,
        real_pdf_processor_init_params,
        mock_pdf_processor,
        ):
    return {
        'default': default_pdf_processor,
        'real_init': real_pdf_processor_init_params,
        'mocked': mock_pdf_processor
    }

def logger_dict(
        mock_logger,
        real_logger
        ):
    return {
        'mock': mock_logger,
        'real': real_logger
    }

def ipld_storage_dict(
        mock_ipld_storage,
        real_ipld_storage
        ):
    return {
        'mock': mock_ipld_storage,
        'real': real_ipld_storage
    }

