from setuptools import setup, find_packages
from setuptools.command.develop import develop as _develop
from setuptools.command.install import install as _install
import os
import sys
import platform

# Platform detection for conditional dependencies
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'
IS_MACOS = platform.system() == 'Darwin'
IS_64BIT = sys.maxsize > 2**32

def _ipfs_kit_dependency() -> str:
    """Prefer the vendored submodule checkout when present.

    This keeps `pip install -e .` fast and reproducible (no nested git+submodule
    fetches) while still allowing installs from source tarballs or non-vendored
    contexts.
    """

    local_path = os.path.join(os.path.dirname(__file__), "ipfs_kit_py")
    if os.path.isdir(local_path):
        # `file:` URL must be absolute for reliability.
        return f"ipfs_kit_py @ file://{os.path.abspath(local_path)}"

    return "ipfs_kit_py @ git+https://github.com/endomorphosis/ipfs_kit_py.git@main"


ipfs_kit_dependency = _ipfs_kit_dependency()


def _env_truthy(name: str, default: str = "1") -> bool:
    value = os.environ.get(name, default)
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def _maybe_download_nltk_data() -> None:
    """Best-effort NLTK data download during install.

    Controlled via env var:
    - IPFS_DATASETS_PY_AUTO_NLTK_DOWNLOAD (default: 1)
    """

    if not _env_truthy("IPFS_DATASETS_PY_AUTO_NLTK_DOWNLOAD", "1"):
        return

    try:
        import nltk  # type: ignore
    except Exception:
        return

    # If the user specified NLTK_DATA, prefer its first entry as download target.
    download_dir = os.environ.get("IPFS_DATASETS_PY_NLTK_DOWNLOAD_DIR")
    if not download_dir:
        nltk_data = os.environ.get("NLTK_DATA")
        if nltk_data:
            download_dir = nltk_data.split(os.pathsep)[0]

    quiet = _env_truthy("IPFS_DATASETS_PY_NLTK_DOWNLOAD_QUIET", "1")

    resources = [
        ("tokenizers/punkt", "punkt"),
        ("taggers/averaged_perceptron_tagger", "averaged_perceptron_tagger"),
        ("chunkers/maxent_ne_chunker", "maxent_ne_chunker"),
        ("corpora/words", "words"),
    ]

    for find_path, package_id in resources:
        try:
            nltk.data.find(find_path)
            continue
        except Exception:
            pass

        try:
            nltk.download(package_id, download_dir=download_dir, quiet=bool(quiet))
        except Exception:
            # Best-effort only; don't fail installs.
            continue


class _PostInstall(_install):
    def run(self):  # type: ignore[override]
        super().run()
        _maybe_download_nltk_data()


class _PostDevelop(_develop):
    def run(self):  # type: ignore[override]
        super().run()
        _maybe_download_nltk_data()

setup(
    name="ipfs_datasets_py",
    version='0.2.0',
    packages=find_packages(),
    py_modules=["ipfs_datasets_cli"],
    install_requires=[
        # Core dependencies - all from GitHub main branches
        'orbitdb_kit_py',
        # ipfs_kit_py from GitHub main branch
        ipfs_kit_dependency,
        'ipfs_model_manager_py',
        'ipfs_faiss_py',
        'transformers',
        "numpy>=1.21.0,<2.0.0; python_version < '3.14'",
        "numpy>=2.0.0; python_version >= '3.14'",
        'urllib3',
        'requests',
        'boto3',
        'ipfsspec<0.6.0',
        "duckdb",
        "aiosqlite>=0.17.0",  # Async SQLite for metadata/auth
        "pyarrow>=10.0.0; python_version < '3.14'",
        "fsspec>=2023.1.0,<=2024.6.1",
        "datasets>=2.10.0,<3.0.0",
        "huggingface-hub>=0.34.0,<1.0.0",
        "jsonpatch>=1.33",

        # IPLD components (always available)
        "ipld-car>=0.0.1",
        "ipld-dag-pb>=0.0.1",
        "dag-cbor>=0.3.3",

        # Caching for CLI tools
        "cachetools>=5.3.0",

        # IPFS integration
        # Note: 0.8.0 stable not available yet, using 0.8.0a2 or fallback to 0.7.0
        "ipfshttpclient>=0.7.0",

        # libp2p crypto/pubsub dependencies (avoid runtime warnings)
        "protobuf>=3.20.0",
        "eth-hash>=0.3.2",
        "eth-keys>=0.5.0",

        # IPLD components
        "multiformats>=0.2.1",

        # Data provenance components
        "networkx>=2.8.0",
        "matplotlib>=3.5.0",
        
        # Async compatibility (anyio for trio/asyncio interop)
        "anyio>=4.0.0",
        "trio>=0.27.0",
        'pydantic-settings>=2.0.0',

        # Core utilities imported by default modules
        "PyJWT>=2.8.0,<3.0.0",
        "beautifulsoup4>=4.12.0,<5.0.0",
        
        # CLI framework
        'click>=8.0.0',

        # Error reporting API (Flask endpoints)
        'Flask>=3.1.1',
        # Default OCR engine (Surya; skip Windows / Python 3.14+)
        'surya-ocr>=0.14.6; platform_system!="Windows" and python_version < "3.14"',
    ],
    extras_require={
        # Logic integration / legal reasoning
        # SymbolicAI is imported as `symai` but distributed on PyPI as `symbolicai`.
        'logic': [
            'nltk>=3.8.1',
            'symbolicai>=0.13.1',
        ],
        # API server extras for the logic module (FastAPI + uvicorn for api_server.py)
        'logic-api': [
            'fastapi>=0.100.0',
            'uvicorn>=0.23.0',
        ],
        # Knowledge graphs - entity extraction and graph database
        'knowledge_graphs': [
            'spacy>=3.0.0',
            # After installing spacy, download the NLP model:
            #   python -m spacy download en_core_web_sm
            'transformers>=4.30.0',    # Optional: transformer-based NER/relation extraction
            'openai>=1.0.0',           # Optional: LLM-enhanced cross-document reasoning
            'anthropic>=0.20.0',       # Optional: Anthropic LLM for reasoning
            'networkx>=2.8.0',         # Required for lineage graph analytics
            'scipy>=1.7.0',            # Required for kamada_kawai_layout (hierarchical viz)
            'matplotlib>=3.5.0',       # Required for render_networkx visualization
            'plotly>=5.9.0',           # Required for render_plotly interactive visualization
            'rdflib>=6.0.0',           # Required for RDF export (export_to_rdf)
        ],
        # Optional but recommended dependencies
        'ipld': [
            'libipld>=3.3.2',       # Rust-backed DAG-CBOR + CAR decode (primary)
            'ipld-car>=0.0.1',      # Pure-Python CAR encode+decode (required for save)
            'ipld-dag-pb>=0.0.1',   # DAG-PB codec (optional, for IPFS file-system nodes)
            'dag-cbor>=0.3.3',      # DAG-CBOR codec (required by ipld-car)
            'multiformats>=0.3.0',  # CID + multihash (required for CAR save path)
        ],
        'web_archive': [
            'archivenow==2020.7.18.12.19.44',
            'ipwb>=0.2021.12.16',
            'beautifulsoup4>=4.11.1',
            'warcio>=1.7.4',
        ],
        'security': [
            'cryptography>=41.0.0',
            'keyring>=24.0.0',
        ],
        'audit': [
            'elasticsearch>=8.0.0',
            'cryptography>=41.0.0',
        ],
        'provenance': [
            'plotly>=5.9.0',
            'dash>=2.6.0',
            'dash-cytoscape>=0.2.0',
        ],
        'alerts': [
            'discord.py>=2.0.0',
            'aiohttp>=3.8.0',
            'PyYAML>=6.0',
        ],
        'p2p': [
            # libp2p networking for distributed inference / cache sharing.
            # Keep this as an extra because py-libp2p is typically installed from git.
            'libp2p @ git+https://github.com/libp2p/py-libp2p.git@main',
            'pymultihash>=0.8.2',
        ],
        'email': [
            # Email processing - all stdlib except optional HTML parsing
            'beautifulsoup4>=4.12.0',  # For HTML email parsing (optional)
        ],
        'test': [
            'pytest>=7.3.1',
            'pytest-cov>=4.1.0',
            'pytest-asyncio>=0.21.0',
            'pytest-trio>=0.8.0',
            'pytest-timeout>=2.0.2',
            'pytest-xdist>=3.8.0',
            'pytest-parallel>=0.1.1',
            'pytest-benchmark>=4.0.0',
            'pytest-mock>=3.12.0',  # mocker fixture for knowledge_graphs and other unit tests
            'hypothesis>=6.0.0',
        ],

        # ZKP Groth16 (Rust FFI wrapper)
        # Note: the Rust binary itself is not a Python dependency.
        'groth16': [
            'jsonschema>=4.0.0',
        ],

        # PDF processing dependencies
        'pdf': [
            'pdfplumber>=0.11.7',  # Primary PDF tool (works on all platforms)
            'pymupdf>=1.26.3',  # Alternative PDF tool (may have DLL issues on Windows)
            'pytesseract>=0.3.13',  # OCR (requires system tesseract)
            'tiktoken>=0.6.0',
            'pysbd',
        ],
        # Multimedia processing
        'multimedia': [
            'yt-dlp>=2024.0.0',
            'ffmpeg-python>=0.2.0',
            'pillow>=10.0.0,<12.0.0',
            'moviepy',
        ],
        # File conversion (Phase 1: Import & Wrap external libraries)
        'file_conversion': [
            # MarkItDown backend (recommended)
            'markitdown>=0.1.0',
            'aiohttp>=3.8.0',
            'playwright>=1.40.0',
        ],
        'file_conversion_full': [
            # All file conversion backends with full format support
            'markitdown>=0.1.0',
            'aiohttp>=3.8.0',
            'playwright>=1.40.0',
            # Additional format support
            'pytesseract>=0.3.10',  # OCR for images
            'python-docx>=0.8.11',  # Word documents
            'openpyxl>=3.0.0',      # Excel files
            'PyPDF2>=3.0.0',        # PDF processing
            'python-pptx>=0.6.21',  # PowerPoint files
            'beautifulsoup4>=4.11.0',  # HTML parsing
        ],
        # Machine Learning extras
        'ml': [
            'torch>=2.0.0',
            'llama-index>=0.13.5',
            'openai>=1.0.0',
        ] + (['surya-ocr>=0.14.0'] if (IS_LINUX or IS_MACOS) else []),  # May have issues on Windows
        # Vector stores
        'vectors': [
            'faiss-cpu>=1.7.0' if IS_WINDOWS else 'faiss-cpu>=1.8.0',  # Windows may need older version
            'qdrant-client>=1.0.0',
            'elasticsearch>=8.0.0',
        ],
        # Web scraping
        'scraping': [
            'beautifulsoup4>=4.12.0',
            'selenium>=4.15.0',
            'scrapy>=2.11.0',
            'autoscraper>=1.1.14',
            'cdx-toolkit>=0.9.37',
            'wayback>=0.4.5',
            'internetarchive>=5.5.0',
        ],
        # API and web services
        'api': [
            'fastapi>=0.100.0',
            'uvicorn>=0.23.0',
            'flask>=3.0.0',
            'mcp>=1.2.0',  # Model Context Protocol
        ],
        # Development tools
        'dev': [
            'mypy>=1.0.0',
            'flake8>=6.0.0',
            'coverage>=7.0.0',
            'Faker>=37.0.0',
            'reportlab>=4.0.0',
            'pyfakefs',
        ],
        # Windows-specific dependencies
        'windows': [
            'pywin32>=305;platform_system=="Windows"',
            'python-magic-bin>=0.4.14;platform_system=="Windows"',  # Windows binary version
        ] if IS_WINDOWS else [],
        # Linux-specific dependencies  
        'linux': [
            'python-magic>=0.4.27;platform_system=="Linux"',
        ] if IS_LINUX else [],
        # macOS-specific
        'macos': [
            'python-magic>=0.4.27;platform_system=="Darwin"',
        ] if IS_MACOS else [],
        'legal': [
            # 'scrape_the_law_mk3 @ file:./ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/scrape_the_law_mk3',
        ],
        # Accelerate integration - distributed AI compute
        'accelerate': [
            # Install from GitHub main branch
            'ipfs_accelerate_py @ git+https://github.com/endomorphosis/ipfs_accelerate_py.git@main',
            'sentence-transformers',
            'torch>=2.0.0',
            'transformers>=4.46.0',
        ],
        'all': [
            # Combine all non-platform-specific extras
            # Logic
            'nltk>=3.8.1',
            'symbolicai>=0.13.1',
            # IPLD
            'ipld-car>=0.0.1',
            'ipld-dag-pb>=0.0.1',
            # Web archive
            'archivenow==2020.7.18.12.19.44',
            'ipwb>=0.2021.12.16',
            'warcio>=1.7.4',
            # Security/Audit
            'cryptography>=41.0.0',
            'keyring>=24.0.0',
            # Provenance
            'plotly>=5.9.0',
            'dash>=2.6.0',
            'dash-cytoscape>=0.2.0',
            # Alerts
            'discord.py>=2.0.0',
            'aiohttp>=3.8.0',
            'PyYAML>=6.0',
            # Email
            'beautifulsoup4>=4.12.0',
            # Testing
            'pytest>=7.3.1',
            'pytest-cov>=4.1.0',
            'pytest-asyncio>=0.21.0',
            'pytest-timeout>=2.0.2',
            'pytest-xdist>=3.8.0',
            'pytest-parallel>=0.1.1',
            'pytest-benchmark>=4.0.0',
            # PDF
            'pdfplumber>=0.11.7',
            'pymupdf>=1.26.3',
            'pytesseract>=0.3.13',
            'tiktoken>=0.6.0',
            'pysbd',
            # Multimedia
            'yt-dlp>=2024.0.0',
            'ffmpeg-python>=0.2.0',
            'pillow>=10.0.0',
            'moviepy',
            # File conversion
            'markitdown>=0.1.0',
            'aiohttp>=3.8.0',
            # Scraping
            'beautifulsoup4>=4.12.0',
            'selenium>=4.15.0',
            'scrapy>=2.11.0',
            'autoscraper>=1.1.14',
            'cdx-toolkit>=0.9.37',
            'wayback>=0.4.5',
            'internetarchive>=5.5.0',
            # API
            'fastapi>=0.100.0',
            'uvicorn>=0.23.0',
            'flask>=3.0.0',
            'mcp>=1.2.0',
            # Vectors (conditional)
            'faiss-cpu>=1.7.0' if IS_WINDOWS else 'faiss-cpu>=1.8.0',
            'qdrant-client>=1.0.0',
            'elasticsearch>=8.0.0',
            # Platform-specific magic (added via platform extras)
            # Use pip install -e ".[all,windows]" or ".[all,linux]" for platform-specific
            # Note: ML extras (torch, llama-index) not included in 'all' due to size
            # Install separately with pip install -e ".[ml]"
        ],
    },
    cmdclass={
        "install": _PostInstall,
        "develop": _PostDevelop,
    },
    python_requires='>=3.12',
    description="IPFS Datasets - A unified interface for data processing and distribution across decentralized networks",
    long_description=open("README.md", encoding='utf-8').read(),
    long_description_content_type="text/markdown",
    author="IPFS Datasets Contributors",
    entry_points={
        'console_scripts': [
            'ipfs-datasets=ipfs_datasets_cli:cli_main',
            'ipfs-datasets-cli=ipfs_datasets_cli:cli_main',
            # File converter CLI (Phase 6.4)
            'file-converter=ipfs_datasets_py.processors.file_converter.cli:main',
            'fc=ipfs_datasets_py.processors.file_converter.cli:main',
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: System :: Distributed Computing",
    ],
)
