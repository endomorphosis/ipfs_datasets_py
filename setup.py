from setuptools import setup, find_packages
import sys
import platform

# Platform detection for conditional dependencies
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'
IS_MACOS = platform.system() == 'Darwin'
IS_64BIT = sys.maxsize > 2**32

setup(
    name="ipfs_datasets_py",
    version='0.2.0',
    packages=find_packages(),
    py_modules=["ipfs_datasets_cli"],
    install_requires=[
        # Core dependencies
        'orbitdb_kit_py',
        # Install ipfs_kit_py from known_good branch (PyPI package is broken)
        'ipfs_kit_py @ git+https://github.com/endomorphosis/ipfs_kit_py.git@known_good',
        'ipfs_model_manager_py',
        'ipfs_faiss_py',
        'transformers',
        'numpy',
        'urllib3',
        'requests',
        'boto3',
        'ipfsspec',
        "duckdb",
        "pyarrow>=10.0.0",
        "fsspec",
        "datasets>=2.10.0",

        # Caching for CLI tools
        "cachetools>=5.3.0",

        # IPFS integration
        # Note: 0.8.0 stable not available yet, using 0.8.0a2 or fallback to 0.7.0
        "ipfshttpclient>=0.7.0",

        # IPLD components
        "multiformats>=0.2.1",

        # Data provenance components
        "networkx>=2.8.0",
        "matplotlib>=3.5.0",
    ],
    extras_require={
        # Optional but recommended dependencies
        'ipld': [
            'ipld-car>=0.0.1',  # Only 0.0.1 available on PyPI
            'ipld-dag-pb>=0.0.1',  # Only 0.0.1 available on PyPI
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
        'test': [
            'pytest>=7.3.1',
            'pytest-cov>=4.1.0',
            'pytest-asyncio>=0.21.0',
            'pytest-timeout>=2.0.2',
            'pytest-xdist>=3.8.0',
            'pytest-parallel>=0.1.1',
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
            'pillow>=10.0.0',
            'moviepy',
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
        'all': [
            # Combine all non-platform-specific extras
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
            # Testing
            'pytest>=7.3.1',
            'pytest-cov>=4.1.0',
            'pytest-asyncio>=0.21.0',
            'pytest-timeout>=2.0.2',
            'pytest-xdist>=3.8.0',
            'pytest-parallel>=0.1.1',
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
    python_requires='>=3.12',
    description="IPFS Datasets - A unified interface for data processing and distribution across decentralized networks",
    long_description=open("README.md", encoding='utf-8').read(),
    long_description_content_type="text/markdown",
    author="IPFS Datasets Contributors",
    entry_points={
        'console_scripts': [
            'ipfs-datasets=ipfs_datasets_cli:cli_main',
            'ipfs-datasets-cli=ipfs_datasets_cli:cli_main',
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
