from setuptools import setup, find_packages
from setuptools.command.develop import develop as _develop
from setuptools.command.install import install as _install
import os
import sys
import platform
import shutil
import subprocess

try:
    from wheel.bdist_wheel import bdist_wheel as _bdist_wheel
except Exception:  # pragma: no cover - wheel is part of build-system.requires.
    _bdist_wheel = None

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
    local_markers = (
        os.path.join(local_path, "setup.py"),
        os.path.join(local_path, "pyproject.toml"),
        os.path.join(local_path, ".git"),
    )
    if os.path.isdir(local_path) and any(os.path.exists(marker) for marker in local_markers):
        # `file:` URL must be absolute for reliability.
        return f"ipfs_kit_py[api,ipld,ai_ml] @ file://{os.path.abspath(local_path)}"

    return "ipfs_kit_py[api,ipld,ai_ml] @ git+https://github.com/endomorphosis/ipfs_kit_py.git@main"


ipfs_kit_dependency = _ipfs_kit_dependency()


def _ipfs_accelerate_dependency() -> str:
    """Prefer the vendored ipfs_accelerate_py checkout when present."""

    local_path = os.path.join(os.path.dirname(__file__), "ipfs_accelerate_py")
    local_markers = (
        os.path.join(local_path, "setup.py"),
        os.path.join(local_path, "pyproject.toml"),
        os.path.join(local_path, ".git"),
    )
    if os.path.isdir(local_path) and any(os.path.exists(marker) for marker in local_markers):
        return f"ipfs_accelerate_py @ file://{os.path.abspath(local_path)}"

    return "ipfs_accelerate_py @ git+https://github.com/endomorphosis/ipfs_accelerate_py.git@main"


ipfs_accelerate_dependency = _ipfs_accelerate_dependency()


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


def _maybe_build_groth16_backend() -> None:
    """Best-effort build/setup for the bundled Rust Groth16 backend.

    Controlled via env var:
    - IPFS_DATASETS_PY_AUTO_GROTH16_BUILD (default: 1)
    """

    if not _env_truthy("IPFS_DATASETS_PY_AUTO_GROTH16_BUILD", "1"):
        return
    backend_dir = os.path.join(os.path.dirname(__file__), "ipfs_datasets_py", "processors", "groth16_backend")
    platform_name = f"{platform.system().lower()}-{'aarch64' if platform.machine().lower() in {'aarch64', 'arm64'} else 'x86_64' if platform.machine().lower() in {'x86_64', 'amd64'} else platform.machine().lower()}"
    bundled_binary = os.path.join(backend_dir, "bin", platform_name, "groth16")
    if os.path.exists(bundled_binary):
        os.chmod(bundled_binary, os.stat(bundled_binary).st_mode | 0o755)
        return
    if shutil.which("cargo") is None:
        print(
            "Groth16 backend auto-build skipped: Rust/Cargo is not installed. "
            "Install Rust with rustup, then run "
            "ipfs_datasets_py/processors/groth16_backend/build.sh.",
            file=sys.stderr,
        )
        return

    build_script = os.path.join(backend_dir, "build.sh")
    if not os.path.exists(build_script):
        return

    try:
        subprocess.run([build_script], cwd=backend_dir, check=True, timeout=900)
    except Exception as exc:
        print(
            f"Groth16 backend auto-build failed: {exc}. "
            "The Python package is installed, but real ZKP proofs require the "
            "bundled Rust backend to build successfully.",
            file=sys.stderr,
        )


class _PostInstall(_install):
    def run(self):  # type: ignore[override]
        super().run()
        _maybe_download_nltk_data()
        _maybe_build_groth16_backend()


class _PostDevelop(_develop):
    def run(self):  # type: ignore[override]
        super().run()
        _maybe_download_nltk_data()
        _maybe_build_groth16_backend()


if _bdist_wheel is not None:
    class _PlatformWheel(_bdist_wheel):
        def finalize_options(self):  # type: ignore[override]
            super().finalize_options()
            self.root_is_pure = False
else:
    _PlatformWheel = None


_cmdclass = {
    "install": _PostInstall,
    "develop": _PostDevelop,
}
if _PlatformWheel is not None:
    _cmdclass["bdist_wheel"] = _PlatformWheel


setup(
    name="ipfs_datasets_py",
    version='0.2.0',
    packages=find_packages(
        exclude=[
            "ipfs_kit_py*",
            "ipfs_accelerate_py*",
            "ipfs_datasets_py.multimedia.convert_to_txt_based_on_mime_type.test*",
            "ipfs_datasets_py.processors.multimedia.convert_to_txt_based_on_mime_type.test*",
        ]
    ),
    package_data={
        "ipfs_datasets_py": [
            "py.typed",
            "processors/groth16_backend/Cargo.toml",
            "processors/groth16_backend/Cargo.lock",
            "processors/groth16_backend/build.sh",
            "processors/groth16_backend/bin/*/groth16",
            "processors/groth16_backend/artifacts/v*/proving_key.bin",
            "processors/groth16_backend/artifacts/v*/verifying_key.bin",
            "processors/groth16_backend/src/*.rs",
            "processors/groth16_backend/schemas/*.json",
            "processors/groth16_backend/contracts/*.sol",
        ],
    },
    include_package_data=True,
    py_modules=["ipfs_datasets_cli"],
    install_requires=[
        # Core dependencies - all from GitHub main branches
        'orbitdb_kit_py',
        # ipfs_kit_py from GitHub main branch
        ipfs_kit_dependency,
        ipfs_accelerate_dependency,
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
        "jsonschema>=4.0.0",
        "cffi>=1.16.0",

        # IPLD components (always available)
        "libipld>=3.3.2",
        "ipld-car>=0.0.1",
        "ipld-dag-pb>=0.0.1",
        "dag-cbor>=0.3.3",

        # Caching for CLI tools
        "cachetools>=5.3.0",

        # IPFS integration
        # Note: 0.8.0 stable not available yet, using 0.8.0a2 or fallback to 0.7.0
        "ipfshttpclient>=0.7.0",

        # libp2p crypto/pubsub dependencies (avoid runtime warnings)
        "libp2p @ git+https://github.com/libp2p/py-libp2p.git@main",
        "pymultihash>=0.8.2",
        "protobuf>=3.20.0",
        "eth-hash>=0.3.2",
        "eth-keys>=0.5.0",

        # IPLD components
        "multiformats>=0.3.0",

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
        "ddgs>=9.11.2",
        "google-api-python-client>=2.192.0",
        "cloudscraper>=1.2.71",
        "cfscrape>=2.1.1; python_version < '3.12'",
        
        # CLI framework
        'click>=8.0.0',

        # Error reporting API (Flask endpoints)
        'Flask>=3.1.1',
        # Default OCR engine (Surya; skip Windows / Python 3.14+)
        'surya-ocr>=0.14.6; platform_system!="Windows" and python_version < "3.14"',
        # PDF / RTF runtime dependencies used by default processors
        'nltk>=3.8.1',
        'pdfplumber>=0.11.7',
        'pymupdf>=1.26.3',
        'pillow>=10.2.0,<11.0.0',
        'PyPDF2>=3.0.0',
        'pypdf>=5.0.0',
        'pytesseract>=0.3.13',
        'striprtf>=0.0.29',
        'tiktoken>=0.6.0',
        'pysbd',
        'markitdown>=0.1.0',
        'python-docx>=1.1.2',
        # Keep OpenCV on the NumPy 1.x-compatible line used by the rest of this package.
        'opencv-python>=4.8.1.78,<4.12.0',
        # SymbolicAI is imported as `symai`; keep it in base installs so the
        # logic/proof stack does not silently drop to fallback mode.
        'symbolicai>=1.14.0,<2.0.0',
    ],
    extras_require={
        # Logic integration / legal reasoning
        # SymbolicAI is imported as `symai` but distributed on PyPI as `symbolicai`.
        'logic': [
            'nltk>=3.8.1',
            'symbolicai>=1.14.0,<2.0.0',
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
            'PyPDF2>=3.0.0',
            'pypdf>=5.0.0',
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
            'striprtf>=0.0.29',
        ],
        'file_conversion_full': [
            # All file conversion backends with full format support
            'markitdown>=0.1.0',
            'aiohttp>=3.8.0',
            'playwright>=1.40.0',
            'striprtf>=0.0.29',
            # Additional format support
            'pytesseract>=0.3.10',  # OCR for images
            'python-docx>=0.8.11',  # Word documents
            'openpyxl>=3.0.0',      # Excel files
            'PyPDF2>=3.0.0',        # PDF processing
            'pypdf>=5.0.0',
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
            'selenium>=4.15.0,<4.16.0',
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
            'symbolicai>=1.14.0,<2.0.0',
            # ZKP Groth16 FFI wrapper
            'jsonschema>=4.0.0',
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
            'PyPDF2>=3.0.0',
            'pypdf>=5.0.0',
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
            'striprtf>=0.0.29',
            # Scraping
            'beautifulsoup4>=4.12.0',
            'selenium>=4.15.0,<4.16.0',
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
    cmdclass=_cmdclass,
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
