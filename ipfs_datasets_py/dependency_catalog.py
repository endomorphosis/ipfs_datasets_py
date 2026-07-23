"""Declarative metadata for Python dependencies that may be loaded lazily.

The catalog maps import names to distribution names.  Packaging still owns
environment creation through ``setup.py``, ``pyproject.toml``, and the
requirements files; this metadata lets a running feature request the same
dependency without guessing that, for example, ``fitz`` is distributed as
``pymupdf``.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class DependencySpec:
    """A supported lazy Python dependency."""

    import_name: str
    distribution: str
    requirements: tuple[str, ...]
    components: tuple[str, ...] = ()
    import_aliases: tuple[str, ...] = ()
    system_dependencies: tuple[str, ...] = ()
    companions: tuple[str, ...] = ()


def canonical_distribution_name(value: str) -> str:
    """Return a PEP 503-style name from a distribution or requirement string."""

    candidate = str(value or "").strip()
    if " @ " in candidate:
        candidate = candidate.split(" @ ", 1)[0].strip()
    candidate = re.split(r"[\s\[<>=!~;]", candidate, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", candidate).lower()


_NUMPY_REQUIREMENT = (
    "numpy>=2.0.0"
    if sys.version_info >= (3, 14)
    else "numpy>=1.26.4,<=2.1.3"
)
_PYARROW_REQUIREMENTS = (
    ()
    if sys.version_info >= (3, 14)
    else ("pyarrow>=23.0.1,<26.0.0",)
)
_SURYA_REQUIREMENTS = (
    ()
    if sys.version_info >= (3, 14) or sys.platform == "win32"
    else ("surya-ocr>=0.14.0",)
)
_FAISS_REQUIREMENT = (
    "faiss-cpu>=1.7.0" if sys.platform == "win32" else "faiss-cpu>=1.8.0"
)
_MAGIC_REQUIREMENT = (
    "python-magic-bin>=0.4.14"
    if sys.platform == "win32"
    else "python-magic>=0.4.27"
)


DEPENDENCY_SPECS: tuple[DependencySpec, ...] = (
    # Core/data dependencies.
    DependencySpec("numpy", "numpy", (_NUMPY_REQUIREMENT,), ("core", "ml", "graphrag")),
    DependencySpec("pandas", "pandas", ("pandas>=1.5.0,<3.0.0",), ("core", "graphrag")),
    DependencySpec("requests", "requests", ("requests>=2.25.0,<3.0.0",), ("core", "web")),
    DependencySpec("duckdb", "duckdb", ("duckdb>=1.3.2",), ("core",)),
    DependencySpec("pyarrow", "pyarrow", _PYARROW_REQUIREMENTS, ("core", "graphrag")),
    DependencySpec("datasets", "datasets", ("datasets>=4.0.0,<5.0.0",), ("graphrag",)),
    DependencySpec("multiformats", "multiformats", ("multiformats>=0.3.0",), ("ipld",)),
    DependencySpec("libipld", "libipld", ("libipld>=3.3.2",), ("ipld",)),
    DependencySpec("ipld_car", "ipld-car", ("ipld-car>=0.0.1",), ("ipld",)),
    DependencySpec("ipld_dag_pb", "ipld-dag-pb", ("ipld-dag-pb>=0.0.1",), ("ipld",)),
    DependencySpec("dag_cbor", "dag-cbor", ("dag-cbor>=0.3.3",), ("ipld",)),
    DependencySpec("aiosqlite", "aiosqlite", ("aiosqlite>=0.17.0",), ("core",)),
    # ML, vectors, and knowledge graphs.
    DependencySpec(
        "torch",
        "torch",
        ("torch>=2.13.0,<3.0.0", "torch-cpu>=2.13.0,<3.0.0"),
        ("ml", "graphrag"),
    ),
    DependencySpec(
        "transformers",
        "transformers",
        ("transformers>=4.46.0,<5.0.0",),
        ("ml", "graphrag"),
    ),
    DependencySpec(
        "sentence_transformers",
        "sentence-transformers",
        ("sentence-transformers>=3.0.0,<6.0.0",),
        ("ml", "vectors", "graphrag"),
    ),
    DependencySpec(
        "faiss",
        "faiss-cpu",
        (_FAISS_REQUIREMENT, "faiss>=1.7.4"),
        ("vectors", "graphrag"),
    ),
    DependencySpec(
        "qdrant_client",
        "qdrant-client",
        ("qdrant-client>=1.0.0",),
        ("vectors", "graphrag"),
    ),
    DependencySpec(
        "elasticsearch",
        "elasticsearch",
        ("elasticsearch>=8.0.0,<9.0.0",),
        ("vectors", "graphrag"),
    ),
    DependencySpec("scipy", "scipy", ("scipy>=1.7.0,<2.0.0",), ("graphrag",)),
    DependencySpec(
        "sklearn",
        "scikit-learn",
        ("scikit-learn>=1.3.0,<2.0.0",),
        ("vectors", "graphrag"),
    ),
    DependencySpec("networkx", "networkx", ("networkx>=3.0.0,<4.0.0",), ("graphrag",)),
    DependencySpec("spacy", "spacy", ("spacy>=3.0.0,<4.0.0",), ("graphrag",)),
    # PDF, OCR, file conversion, and media.
    DependencySpec(
        "fitz",
        "pymupdf",
        ("pymupdf>=1.26.3,<2.0.0", "PyMuPDF>=1.26.3,<2.0.0"),
        ("pdf", "graphrag"),
        ("pymupdf",),
        ("poppler",),
    ),
    DependencySpec("pdfplumber", "pdfplumber", ("pdfplumber>=0.11.7,<1.0.0",), ("pdf", "graphrag")),
    DependencySpec(
        "pytesseract",
        "pytesseract",
        ("pytesseract>=0.3.13,<1.0.0",),
        ("pdf", "ocr", "graphrag"),
        system_dependencies=("tesseract",),
    ),
    DependencySpec("PIL", "pillow", ("pillow>=12.2.0,<13.0.0",), ("pdf", "multimedia", "graphrag")),
    DependencySpec(
        "cv2",
        "opencv-python",
        (
            "opencv-python>=4.8.1.78,<4.12.0",
            "opencv-contrib-python>=4.8.1.78,<4.12.0",
        ),
        ("ocr", "logic", "symai_router"),
    ),
    DependencySpec("easyocr", "easyocr", ("easyocr>=1.6.0",), ("ocr",)),
    DependencySpec("surya", "surya-ocr", _SURYA_REQUIREMENTS, ("ocr",)),
    DependencySpec("docx", "python-docx", ("python-docx>=1.1.2",), ("file_conversion",)),
    DependencySpec("openpyxl", "openpyxl", ("openpyxl>=3.0.0",), ("file_conversion",)),
    DependencySpec("markitdown", "markitdown", ("markitdown>=0.1.0",), ("file_conversion",)),
    DependencySpec("ffmpeg", "ffmpeg-python", ("ffmpeg-python>=0.2.0",), ("multimedia",)),
    DependencySpec("moviepy", "moviepy", ("moviepy>=1.0.0",), ("multimedia",)),
    DependencySpec(
        "imageio_ffmpeg",
        "imageio-ffmpeg",
        ("imageio-ffmpeg>=0.6.0",),
        ("multimedia",),
    ),
    # NLP and model APIs.
    DependencySpec("nltk", "nltk", ("nltk>=3.8.1,<4.0.0",), ("graphrag",)),
    DependencySpec("openai", "openai", ("openai>=1.97.1,<2.0.0",), ("graphrag",)),
    DependencySpec("anthropic", "anthropic", ("anthropic>=0.20.0,<1.0.0",), ("graphrag",)),
    DependencySpec("tiktoken", "tiktoken", ("tiktoken>=0.6.0",), ("pdf", "graphrag")),
    # Web/API dependencies.
    DependencySpec("fastapi", "fastapi", ("fastapi>=0.100.0,<1.0.0",), ("api",)),
    DependencySpec("uvicorn", "uvicorn", ("uvicorn>=0.23.0,<1.0.0",), ("api",)),
    DependencySpec("flask", "flask", ("flask>=3.1.1,<4.0.0",), ("api",)),
    DependencySpec("jinja2", "jinja2", ("jinja2>=3.1.0",), ("api",)),
    DependencySpec("aiohttp", "aiohttp", ("aiohttp>=3.8.0",), ("web", "file_conversion")),
    DependencySpec("bs4", "beautifulsoup4", ("beautifulsoup4>=4.12.0,<5.0.0",), ("web",)),
    DependencySpec(
        "newspaper",
        "newspaper3k",
        ("newspaper3k>=0.2.8,<1.0.0",),
        ("web",),
        companions=("lxml_html_clean",),
    ),
    DependencySpec(
        "readability",
        "readability-lxml",
        ("readability-lxml>=0.8.0,<1.0.0",),
        ("web",),
        companions=("lxml_html_clean",),
    ),
    DependencySpec(
        "lxml_html_clean",
        "lxml_html_clean",
        ("lxml_html_clean>=0.4.0",),
        ("web",),
    ),
    DependencySpec("selenium", "selenium", ("selenium>=4.15.0,<4.16.0",), ("web",)),
    # Logic and theorem-prover Python bindings. Native binaries use the
    # dedicated, checksum-aware prover installer.
    DependencySpec(
        "z3",
        "z3-solver",
        ("z3-solver>=4.12.0,<5.0.0",),
        ("z3", "smt_solvers"),
        system_dependencies=("z3",),
    ),
    DependencySpec(
        "cvc5",
        "cvc5",
        ("cvc5>=1.0.0,<2.0.0",),
        ("cvc5", "smt_solvers"),
        system_dependencies=("cvc5",),
    ),
    DependencySpec("pysmt", "pysmt", ("pysmt>=0.9.5,<1.0.0",), ("smt_solvers",)),
    DependencySpec("mathsat", "mathsat", ("mathsat>=5.6.0",)),
    DependencySpec("beartype", "beartype", ("beartype>=0.15.0,<1.0.0",), ("logic",)),
    DependencySpec(
        "symai",
        "symbolicai",
        ("symbolicai>=1.14.0,<2.0.0",),
        ("logic", "symai_router"),
    ),
    DependencySpec("pydantic", "pydantic", ("pydantic>=2.0.0,<3.0.0",), ("core", "graphrag")),
    DependencySpec("jsonschema", "jsonschema", ("jsonschema>=4.0.0,<5.0.0",), ("logic",)),
    # Common utilities and development dependencies.
    DependencySpec("yaml", "PyYAML", ("PyYAML>=6.0.0,<7.0.0",), ("core",)),
    DependencySpec("tqdm", "tqdm", ("tqdm>=4.60.0,<5.0.0",), ("core",)),
    DependencySpec("psutil", "psutil", ("psutil>=5.9.0",), ("core",)),
    DependencySpec("chardet", "chardet", ("chardet>=5.0.0,<6.0.0",), ("lazy",)),
    DependencySpec("llama_cpp", "llama-cpp-python", ("llama-cpp-python",), ("lazy",)),
    DependencySpec("playsound3", "playsound3", ("playsound3",), ("lazy",)),
    DependencySpec("pydub", "pydub", ("pydub>=0.25.0",), ("lazy",)),
    DependencySpec("pymediainfo", "pymediainfo", ("pymediainfo",), ("lazy",)),
    DependencySpec("PyPDF2", "PyPDF2", ("PyPDF2>=3.0.0",), ("pdf", "lazy")),
    DependencySpec("pydocx", "pydocx", ("pydocx",), ("lazy",)),
    DependencySpec("rouge", "rouge", ("rouge",), ("lazy",)),
    DependencySpec("whisper", "openai-whisper", ("openai-whisper",), ("lazy",)),
    DependencySpec("xformers", "xformers", ("xformers",), ("lazy",)),
    DependencySpec("torch_directml", "torch-directml", ("torch-directml",), ("lazy",)),
    DependencySpec(
        "intel_extension_for_pytorch",
        "intel-extension-for-pytorch",
        ("intel-extension-for-pytorch",),
        ("lazy",),
    ),
    DependencySpec("rasterio", "rasterio", ("rasterio",), ("lazy",)),
    DependencySpec("geopandas", "geopandas", ("geopandas",), ("lazy",)),
    DependencySpec("requests_cache", "requests-cache", ("requests-cache>=1.2.0",), ("lazy",)),
    DependencySpec("httpx", "httpx", ("httpx>=0.27.0",), ("lazy",)),
    DependencySpec("httpx_cache", "httpx-cache", ("httpx-cache",), ("lazy",)),
    DependencySpec("aiohttp_cache", "aiohttp-cache", ("aiohttp-cache",), ("lazy",)),
    DependencySpec("ipfshttpclient", "ipfshttpclient", ("ipfshttpclient>=0.7.0",), ("lazy",)),
    DependencySpec("magic", "python-magic", (_MAGIC_REQUIREMENT,), ("lazy",)),
    DependencySpec("lxml", "lxml", ("lxml>=5.0.0",), ("lazy",)),
    DependencySpec("reportlab", "reportlab", ("reportlab>=4.0.0,<5.0.0",), ("test",)),
    DependencySpec("pytest", "pytest", ("pytest>=9.0.3,<10.0.0",), ("test",)),
    DependencySpec("pytest_asyncio", "pytest-asyncio", ("pytest-asyncio>=0.21.0",), ("test",)),
    DependencySpec("pytest_cov", "pytest-cov", ("pytest-cov>=4.1.0",), ("test",)),
    DependencySpec("pytest_timeout", "pytest-timeout", ("pytest-timeout>=2.0.2",), ("test",)),
    DependencySpec("xdist", "pytest-xdist", ("pytest-xdist>=3.8.0",), ("test",)),
    DependencySpec("pytest_benchmark", "pytest-benchmark", ("pytest-benchmark>=4.0.0",), ("test",)),
    DependencySpec("pytest_mock", "pytest-mock", ("pytest-mock>=3.12.0",), ("test",)),
    DependencySpec("hypothesis", "hypothesis", ("hypothesis>=6.0.0",), ("test",)),
    DependencySpec("anyio", "anyio", ("anyio>=4.0.0,<5.0.0",), ("test",)),
    DependencySpec("coverage", "coverage", ("coverage>=7.0.0,<8.0.0",), ("test",)),
    DependencySpec("faker", "Faker", ("Faker>=37.0.0",), ("test",)),
    DependencySpec(
        "copilot",
        "github-copilot-sdk",
        ("github-copilot-sdk>=0.1.0",),
        ("symai_router",),
    ),
)


_BY_IMPORT: dict[str, DependencySpec] = {}
_BY_DISTRIBUTION: dict[str, DependencySpec] = {}
for _dependency in DEPENDENCY_SPECS:
    for _import_name in (_dependency.import_name, *_dependency.import_aliases):
        _BY_IMPORT[_import_name] = _dependency
        _BY_IMPORT[_import_name.lower()] = _dependency
    _BY_DISTRIBUTION[canonical_distribution_name(_dependency.distribution)] = _dependency


COMPONENT_MODULES: dict[str, tuple[str, ...]] = {
    "graphrag": (
        "numpy",
        "pandas",
        "torch",
        "transformers",
        "sentence_transformers",
        "datasets",
        "fitz",
        "pdfplumber",
        "pytesseract",
        "PIL",
        "cv2",
        "easyocr",
        "surya",
        "nltk",
        "faiss",
        "qdrant_client",
        "elasticsearch",
        "scipy",
        "sklearn",
        "networkx",
        "openai",
        "pyarrow",
        "pydantic",
    ),
    "pdf": ("fitz", "pdfplumber", "pytesseract", "PIL"),
    "ocr": ("cv2", "easyocr", "pytesseract", "surya"),
    "ml": ("numpy", "torch", "transformers", "sentence_transformers"),
    "vectors": ("faiss", "qdrant_client", "elasticsearch"),
    "ipld": ("libipld", "ipld_car", "ipld_dag_pb", "dag_cbor", "multiformats"),
    "z3": ("z3",),
    "cvc5": ("cvc5",),
    "smt_solvers": ("z3", "cvc5", "pysmt"),
    "logic": ("cv2", "symai"),
    "symbolicai": ("cv2", "symai"),
    "web": ("requests", "bs4", "newspaper", "readability"),
    "test": (
        "pytest",
        "pytest_asyncio",
        "pytest_cov",
        "pytest_timeout",
        "xdist",
        "pytest_benchmark",
        "pytest_mock",
        "hypothesis",
    ),
    "symai_router": ("cv2", "symai", "copilot"),
    "lazy": (
        "chardet",
        "llama_cpp",
        "playsound3",
        "pydub",
        "pymediainfo",
        "pydocx",
        "rouge",
        "whisper",
        "xformers",
        "torch_directml",
        "intel_extension_for_pytorch",
        "rasterio",
        "geopandas",
        "requests_cache",
        "httpx",
        "httpx_cache",
        "aiohttp_cache",
        "magic",
        "lxml",
    ),
}


def dependency_for_import(import_name: str) -> DependencySpec | None:
    """Resolve a module, including a dotted module, to its lazy-install spec."""

    candidate = str(import_name or "").strip()
    if not candidate:
        return None
    return (
        _BY_IMPORT.get(candidate)
        or _BY_IMPORT.get(candidate.lower())
        or _BY_IMPORT.get(candidate.split(".", 1)[0])
        or _BY_IMPORT.get(candidate.split(".", 1)[0].lower())
    )


def dependency_for_distribution(value: str) -> DependencySpec | None:
    """Resolve a distribution or requirement string to its catalog entry."""

    return _BY_DISTRIBUTION.get(canonical_distribution_name(value))


def dependencies_for_component(component: str) -> tuple[DependencySpec, ...]:
    """Return installable dependencies for a named feature component."""

    dependencies: list[DependencySpec] = []
    for import_name in COMPONENT_MODULES.get(component, ()):
        dependency = dependency_for_import(import_name)
        if dependency is not None and dependency.requirements:
            dependencies.append(dependency)
    return tuple(dependencies)


def package_candidates() -> dict[str, list[str]]:
    """Return installer-compatible distribution-to-requirement candidates."""

    return {
        dependency.distribution: list(dependency.requirements)
        for dependency in DEPENDENCY_SPECS
    }


def companion_packages() -> dict[str, list[str]]:
    """Return installer-compatible companion dependency metadata."""

    return {
        dependency.distribution: list(dependency.companions)
        for dependency in DEPENDENCY_SPECS
        if dependency.companions
    }


def iter_distributions() -> Iterable[str]:
    """Yield every supported distribution name once."""

    yield from _BY_DISTRIBUTION
