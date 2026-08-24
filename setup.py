import gzip
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

from setuptools import find_namespace_packages, setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.develop import develop as _develop
from setuptools.command.egg_info import egg_info as _egg_info
from setuptools.command.install import install as _install
from setuptools.command.sdist import sdist as _sdist

try:
    from wheel.bdist_wheel import bdist_wheel as _bdist_wheel
except Exception:  # pragma: no cover - wheel is part of build-system.requires.
    _bdist_wheel = None

# Platform detection for conditional dependencies
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'
IS_MACOS = platform.system() == 'Darwin'
IS_64BIT = sys.maxsize > 2**32

def _env_truthy(name: str, default: str = "1") -> bool:
    value = os.environ.get(name, default)
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def _env_explicitly_enabled(name: str) -> bool:
    """Return true only for an affirmative operator opt-in value."""

    value = os.environ.get(name, "")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _maybe_download_nltk_data() -> None:
    """Best-effort NLTK data download during install.

    Disabled by default.  Legacy setup.py install/develop callers must opt in
    with IPFS_DATASETS_PY_AUTO_NLTK_DOWNLOAD=1 (or true/yes/on).
    """

    if not _env_explicitly_enabled("IPFS_DATASETS_PY_AUTO_NLTK_DOWNLOAD"):
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

    Disabled by default.  Legacy setup.py install/develop callers must opt in
    with IPFS_DATASETS_PY_AUTO_GROTH16_BUILD=1 (or true/yes/on).
    """

    if not _env_explicitly_enabled("IPFS_DATASETS_PY_AUTO_GROTH16_BUILD"):
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


def _normalize_wheel_staging_modes(root: Path) -> None:
    """Make wheel member modes independent of the checkout/build umask."""

    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            source_mode = stat.S_IMODE(path.stat().st_mode)
            path.chmod(0o755 if source_mode & 0o111 else 0o644)


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


class _BuildPyWithFormalVerificationAssets(_build_py):
    """Include the independent Runtime MTL source in wheels.

    The managed Runtime MTL installer builds the reviewed TypeScript package
    on first explicit use.  That source lives outside the Python package in a
    source checkout, so ordinary ``build_py`` would silently omit it from a
    wheel.  Copy only the locked build inputs into a package-owned vendor
    directory; ``node_modules`` and generated ``dist`` output are never
    shipped.
    """

    def run(self):  # type: ignore[override]
        super().run()
        project_root = Path(__file__).resolve().parent
        source_root = project_root / "typescript" / "logic-runtime-mtl"
        if not source_root.is_dir():
            raise RuntimeError(
                "missing reviewed Runtime MTL package source: "
                f"{source_root}; cannot build a complete verification wheel"
            )
        destination = (
            Path(self.build_lib)
            / "ipfs_datasets_py"
            / "_vendor"
            / "logic-runtime-mtl"
        )
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(
            source_root,
            destination,
            ignore=shutil.ignore_patterns("node_modules", "dist", ".git"),
        )


class _BuildTreeEggInfo(_egg_info):
    """Keep generated package metadata out of the tracked source directory."""

    def finalize_options(self):  # type: ignore[override]
        if self.egg_base is None:
            egg_base = Path(__file__).resolve().parent / "build" / "egg-info"
            egg_base.mkdir(parents=True, exist_ok=True)
            self.egg_base = str(egg_base)
        # The repository historically tracks a source-tree egg-info directory.
        # It is stale build output, not an input to immutable package artifacts.
        self.ignore_egg_info_in_manifest = True
        super().finalize_options()


class _ReproducibleSdist(_sdist):
    """Normalize tar and gzip metadata when a source epoch is declared."""

    def make_archive(  # type: ignore[override]
        self,
        base_name,
        format,
        root_dir=None,
        base_dir=None,
        owner=None,
        group=None,
    ):
        raw_epoch = os.environ.get("SOURCE_DATE_EPOCH")
        if format != "gztar" or raw_epoch is None or base_dir is None:
            return super().make_archive(
                base_name,
                format,
                root_dir=root_dir,
                base_dir=base_dir,
                owner=owner,
                group=group,
            )

        epoch = int(raw_epoch)
        source_root = Path(root_dir or os.curdir) / base_dir
        output = Path(f"{base_name}.tar.gz")
        output.parent.mkdir(parents=True, exist_ok=True)
        members = [source_root, *sorted(source_root.rglob("*"))]
        with output.open("wb") as raw_stream:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=raw_stream,
                mtime=epoch,
            ) as gzip_stream:
                with tarfile.open(
                    fileobj=gzip_stream,
                    mode="w",
                    format=tarfile.PAX_FORMAT,
                    dereference=False,
                ) as archive:
                    for path in members:
                        relative = path.relative_to(source_root)
                        archive_name = Path(base_dir) / relative
                        info = archive.gettarinfo(
                            str(path), arcname=archive_name.as_posix()
                        )
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        info.mtime = epoch
                        info.pax_headers = {}
                        if info.isdir():
                            info.mode = 0o755
                        elif info.isfile():
                            info.mode = 0o755 if info.mode & 0o111 else 0o644
                        if info.isfile():
                            with path.open("rb") as member_stream:
                                archive.addfile(info, member_stream)
                        else:
                            archive.addfile(info)
        return str(output)


if _bdist_wheel is not None:
    class _PlatformWheel(_bdist_wheel):
        def finalize_options(self):  # type: ignore[override]
            super().finalize_options()
            self.root_is_pure = False

        def write_wheelfile(self, *args, **kwargs):  # type: ignore[override]
            super().write_wheelfile(*args, **kwargs)
            # ``WheelFile.write`` preserves the staging file's permission
            # bits.  Git only records the executable bit, so otherwise an
            # operator's checkout/build umask changes otherwise-identical
            # wheel bytes.  This hook runs after dist-info is materialized and
            # immediately before the staging tree is archived.
            _normalize_wheel_staging_modes(Path(self.bdist_dir))
else:
    _PlatformWheel = None


_cmdclass = {
    "install": _PostInstall,
    "develop": _PostDevelop,
    "build_py": _BuildPyWithFormalVerificationAssets,
    "egg_info": _BuildTreeEggInfo,
    "sdist": _ReproducibleSdist,
}
if _PlatformWheel is not None:
    _cmdclass["bdist_wheel"] = _PlatformWheel


setup(
    name="ipfs_datasets_py",
    version='0.2.0',
    # Formal-verification backends intentionally use PEP 420 namespace
    # directories.  Classical find_packages() omits them from wheels.
    packages=find_namespace_packages(
        include=["ipfs_datasets_py", "ipfs_datasets_py.*"],
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
            "processors/provekit_backend/README.md",
            "processors/provekit_backend/build.sh",
            "logic/zkp/provekit/circuits/*/Nargo.toml",
            "logic/zkp/provekit/circuits/*/src/*.nr",
            "logic/legal_ir/schemas/*.json",
            "logic/software_contracts/semantic_state/schemas/*.json",
        ],
    },
    include_package_data=True,
    py_modules=["ipfs_datasets_cli"],
    # The installed proof-context core is stdlib-only.  Existing optional
    # feature groups remain declared in ``extras_require`` / pyproject.toml;
    # none may cause an implicit sibling checkout, VCS fetch, or heavy install.
    install_requires=[],
    extras_require={
        # Logic integration / legal reasoning
        # SymbolicAI is imported as `symai` but distributed on PyPI as `symbolicai`.
        'logic': [
            'nltk>=3.8.1',
            'symbolicai>=1.14.0,<2.0.0',
        ],
        # Python bindings for theorem-prover integrations. Apalache, Tamarin,
        # Maude, Lean, Rocq, and ProVerif are installed lazily and user-locally
        # only when their execution path is requested. Native installers are
        # available through `ipfs-datasets-install-provers` and never run as a
        # side effect of pip installation. The optional ErgoAI Java API Eclipse
        # Temurin JDK is a reviewed external lazy dependency (temurin-jdk) and
        # is never a mandatory pip package.
        'theorem-provers': [
            'z3-solver>=4.12.0,<5.0.0',
            'cvc5==1.3.3',
            'pysmt>=0.9.5,<1.0.0',
            'beartype>=0.15.0,<1.0.0',
            'jsonschema>=4.0.0,<5.0.0',
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
            'seaborn>=0.12.0',         # Required for optimizer/dashboard statistical visualization
            'plotly>=5.9.0',           # Required for render_plotly interactive visualization
            'rdflib>=6.0.0',           # Required for RDF export (export_to_rdf)
            'neo4j>=5.20.0',           # Required for Neo4j knowledge graph export/import
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
            'newspaper3k>=0.2.8,<1.0.0',
            'readability-lxml>=0.8.0,<1.0.0',
            'lxml_html_clean>=0.4.0',
            'warcio>=1.7.4',
        ],
        'legal_netherlands': [
            'pyarrow>=23.0.1,<26.0.0',
            'huggingface-hub>=0.34.0',
            'datasets>=2.10.0',
            'faiss-cpu>=1.7.0' if IS_WINDOWS else 'faiss-cpu>=1.8.0',
            'scikit-learn>=1.3.0,<2.0.0',
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
            'libp2p>=0.2.0,<1.0.0',
            'protobuf>=5.27.0',
            'pymultihash>=0.8.2',
            'dnspython>=2.2.1',
        ],
        'email': [
            # Email processing - all stdlib except optional HTML parsing
            'beautifulsoup4>=4.12.0',  # For HTML email parsing (optional)
        ],
        'test': [
            'pytest>=9.0.3,<10.0.0',
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

        # Multi-chain wallet processors (WALPROC-G050 / WALPROC-010).
        # Shared kernel and chain ingestion use raw REST/JSON-RPC. Chain SDKs
        # are not selected: SDK convenience is not sufficient justification
        # for a mandatory dependency. Full rationale, license/SBOM notes, and
        # the coincurve/pycryptodome vs eth-hash/eth-keys decision live in
        # docs/dependencies/WALLET_PROCESSOR_DEPENDENCIES.md.
        'wallets': [
            # Shared processor kernel: stdlib + base package only.
        ],
        'wallets-worldcoin': [
            # Keccak via eth-hash pycryptodome backend; RP signing via eth-keys.
            'eth-hash[pycryptodome]>=0.3.2,<1.0.0',
            'eth-keys>=0.5.0,<1.0.0',
        ],
        'wallets-ethereum': [
            # Raw JSON-RPC only; web3.py not required.
        ],
        'wallets-xrpl': [
            # Raw REST/JSON-RPC only; xrpl-py not required.
        ],
        'wallets-xaman': [
            # Composes XRPL; Xaman payloads over raw HTTP; no xumm-sdk.
        ],
        'wallets-bitcoin': [
            # Raw REST/JSON-RPC only; python-bitcoinlib / bitcoinlib not required.
        ],
        'wallets-solana': [
            # Raw JSON-RPC only; solana / solders SDKs not required.
        ],
        'wallets-all': [
            'eth-hash[pycryptodome]>=0.3.2,<1.0.0',
            'eth-keys>=0.5.0,<1.0.0',
        ],

        # ZKP Groth16 (Rust FFI wrapper)
        # Note: the Rust binary itself is not a Python dependency.
        'groth16': [
            'jsonschema>=4.0.0',
        ],
        'provekit': [
            # ProveKit itself is an operator-provided CLI. The Python extra
            # only installs lightweight validation helpers and package assets.
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
            'imageio-ffmpeg>=0.6.0',
            'pillow>=12.2.0,<13.0.0',
            'moviepy',
        ],
        'ocr': [
            'easyocr>=1.6.0',
            'opencv-python>=4.8.1.78,<4.12.0',
            'pytesseract>=0.3.13',
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
            'torch>=2.13.0,<3.0.0',
            'llama-index>=0.13.5',
            'openai>=1.0.0',
        ],
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
        'symai_router': [
            'opencv-python>=4.8.1.78,<4.12.0',
            'symbolicai>=1.14.0,<2.0.0',
            'github-copilot-sdk>=0.1.0',
        ],
        # Dependencies exposed by the shared on-demand dependency proxy. This
        # extra is the eager equivalent of first-use lazy installation.
        'lazy': [
            'z3-solver>=4.12.0,<5.0.0',
            'cvc5==1.3.3',
            'pysmt>=0.9.5,<1.0.0',
            'beartype>=0.15.0,<1.0.0',
            'jsonschema>=4.0.0,<5.0.0',
            'chardet>=5.0.0,<6.0.0',
            'llama-cpp-python',
            'playsound3',
            'pydub>=0.25.0',
            'pymediainfo',
            'pydocx',
            'rouge',
            'openai-whisper',
            'xformers; platform_system!="Darwin"',
            'torch-directml; platform_system=="Windows"',
            'intel-extension-for-pytorch; platform_system=="Linux" and platform_machine=="x86_64"',
            'rasterio',
            'geopandas',
            'requests-cache>=1.2.0',
            'httpx>=0.27.0',
            'httpx-cache',
            'aiohttp-cache',
            'python-magic>=0.4.27; platform_system!="Windows"',
            'python-magic-bin>=0.4.14; platform_system=="Windows"',
            'lxml>=5.0.0',
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
            # Legal integrations are published dependencies; no local paths.
        ],
        # Accelerate integration - distributed AI compute
        'accelerate': [
            'ipfs_accelerate_py>=0.1.0,<1.0.0',
            'sentence-transformers',
            'torch>=2.13.0,<3.0.0',
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
            'pytest>=9.0.3,<10.0.0',
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
            'pillow>=12.2.0,<13.0.0',
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
            'semantic-index=ipfs_datasets_py.cli.semantic_index_cli:main',
            'ipfs-datasets=ipfs_datasets_cli:cli_main',
            'ipfs-datasets-cli=ipfs_datasets_cli:cli_main',
            'netherlands-laws=ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.cli:main',
            'ipfs-netherlands-laws=ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.cli:main',
            'ipfs-datasets-sms-bridge=ipfs_datasets_py.messaging.sms_bridge:main',
            'ipfs-datasets-install-provers=ipfs_datasets_py.logic.integration.bridges.prover_installer:main',
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
