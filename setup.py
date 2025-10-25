from setuptools import setup, find_packages

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
        'test': [
            'pytest>=7.3.1',
            'pytest-cov>=4.1.0',
        ],
        'legal': [
            # 'scrape_the_law_mk3 @ file:./ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/scrape_the_law_mk3',
        ],
        'all': [
            'ipld-car>=0.0.1',  # Only 0.0.1 available on PyPI
            'ipld-dag-pb>=0.0.1',  # Only 0.0.1 available on PyPI
            'archivenow==2020.7.18.12.19.44',
            'ipwb>=0.2021.12.16',
            'beautifulsoup4>=4.11.1',
            'warcio>=1.7.4',
            'cryptography>=41.0.0',
            'keyring>=24.0.0',
            'elasticsearch>=8.0.0',
            'plotly>=5.9.0',
            'dash>=2.6.0',
            'dash-cytoscape>=0.2.0',
            'pytest>=7.3.1',
            'pytest-cov>=4.1.0',
            # 'scrape_the_law_mk3 @ file:./ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/scrape_the_law_mk3',
        ],
    },
    python_requires='>=3.10',
    description="IPFS Datasets - A unified interface for data processing and distribution across decentralized networks",
    long_description=open("README.md").read(),
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
