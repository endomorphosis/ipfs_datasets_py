# GitHub Copilot Instructions for IPFS Datasets Python

Welcome! This repository is the **IPFS Datasets Python** project - a production-ready decentralized AI data platform combining mathematical theorem proving, AI-powered document processing, multimedia handling, and knowledge graph intelligence.

## 🎯 Project Overview

**IPFS Datasets Python** is a comprehensive platform that includes:
- Mathematical theorem proving (converting legal text to verified formal logic)
- GraphRAG document intelligence with 182+ production tests
- Universal media processing (download from 1000+ platforms with FFmpeg)
- Knowledge graph intelligence with semantic search
- Decentralized IPFS-native storage
- Full MCP server with 200+ integrated tools

## 🏗️ Repository Structure

### Core Directories

```
ipfs_datasets_py/
├── analytics/          # Analytics and monitoring tools
├── audit/              # Security and audit functionality
├── config/             # Configuration management
├── embeddings/         # Embedding models and vector operations
├── ipfs_embeddings_py/ # Core IPFS embedding functionality
├── ipld/               # IPLD (InterPlanetary Linked Data) support
├── llm/                # Large language model integration
├── logic_integration/  # Formal logic and theorem proving
├── mcp_server/         # Model Context Protocol server (200+ tools)
├── mcp_tools/          # MCP tool implementations
├── ml/                 # Machine learning utilities
├── multimedia/         # Media processing (FFmpeg, yt-dlp)
├── optimizers/         # Performance optimization
├── pdf_processing/     # PDF processing and analysis
├── rag/                # Retrieval-Augmented Generation
├── search/             # Search functionality
├── scripts/            # Utility scripts and demos
└── tests/              # Test suite (182+ tests)
```

## 🔧 Development Setup

### Python Version
- **Required:** Python 3.10+
- The project uses modern Python features and type hints

### Installation

```bash
# Quick setup
python install.py --quick                    # Core dependencies
python install.py --profile ml               # ML features
python dependency_health_checker.py check    # Verify installation

# Full installation with extras
pip install -e ".[all]"  # All optional dependencies
pip install -e ".[test]" # Testing dependencies only
```

### Key Dependencies

- **IPFS/Decentralized:** `ipfs_kit_py`, `ipfshttpclient`, `multiformats`, `ipld-car`
- **ML/AI:** `transformers`, `torch`, `numpy`, `datasets`
- **Data Processing:** `pandas`, `duckdb`, `pyarrow`, `fsspec`
- **Testing:** `pytest`, `pytest-cov`, `pytest-parallel`, `pytest-xdist`, `pytest-timeout`
- **Code Quality:** `mypy`, `flake8`, `coverage`

## 🧪 Testing

### Running Tests

```bash
# Run all tests
pytest

# Run specific test categories
pytest tests/unit/           # Unit tests
pytest tests/integration/    # Integration tests
pytest -m "not slow"         # Exclude slow tests
pytest -m gpu                # GPU tests only

# With coverage
pytest --cov=ipfs_datasets_py --cov-report=html

# Parallel execution
pytest -n auto               # Auto-detect CPU count
pytest -n 5                  # Use 5 workers
```

### Test Structure

Tests follow the **GIVEN-WHEN-THEN** format. See `docs/_example_test_format.md` for the standard template.

### Test Markers

- `@pytest.mark.gpu` - Requires GPU (CUDA)
- `@pytest.mark.slow` - Slow running test
- `@pytest.mark.multi_gpu` - Requires 2+ GPUs
- `@pytest.mark.integration` - Integration test
- `@pytest.mark.unit` - Unit test

## 🏗️ Building and Linting

### Code Quality

```bash
# Type checking
mypy ipfs_datasets_py/

# Linting
flake8 ipfs_datasets_py/

# Coverage
coverage run -m pytest
coverage report
coverage html  # Generate HTML report
```

### Package Building

```bash
# Build package
python setup.py sdist bdist_wheel

# Install locally in development mode
pip install -e .
```

## 📝 Coding Standards

### Documentation

- **All public classes, functions, and methods MUST have comprehensive docstrings**
- See `docs/_example_docstring_format.md` for the standard format
- Include type hints for all function parameters and return values
- Document exceptions that may be raised

### Code Style

- Follow PEP 8 style guidelines
- Use type hints consistently
- Keep functions focused and single-purpose
- Add comments only when necessary to explain complex logic
- Match the existing comment style in each file

### File Organization

- New functionality should go in the appropriate subdirectory
- Each module should have a clear, single responsibility
- Keep imports organized (stdlib, third-party, local)

## 🔄 CI/CD and Workflows

### GitHub Actions Workflows

The repository has an **Auto-Healing System** for workflow failures:

1. Workflow failures are automatically detected
2. Root cause analysis runs
3. Fixes are proposed with confidence scores
4. PRs are created automatically
5. Review and merge when ready

### Key Workflows

- **docker-build-test.yml** - Docker image building and testing
- **graphrag-production-ci.yml** - GraphRAG production tests
- **mcp-integration-tests.yml** - MCP integration tests
- **pdf_processing_ci.yml** - PDF processing pipeline
- **gpu-tests.yml** - GPU-specific tests
- **copilot-agent-autofix.yml** - Auto-healing with Copilot Agent

See `.github/workflows/README.md` for complete documentation.

## 🤖 Working with CLAUDE.md

This repository uses `CLAUDE.md` for coordinating work across multiple AI agents:

- **Do not modify** `CLAUDE.md` unless specifically working on worker coordination
- **Read** `CLAUDE.md` to understand current work assignments and avoid conflicts
- **Workers 61-75** are assigned to test specific directories
- **Worker 131** is working on comprehensive test coverage (HIGH PRIORITY)
- **Workers 76-85** handle adhoc tool development

### Important Rules from CLAUDE.md

1. Only work in your designated directory
2. Document all actions in the appropriate CHANGELOG.md and TODO.md
3. Never create files unless absolutely necessary
4. Always prefer editing existing files to creating new ones
5. Never proactively create documentation files unless explicitly requested

## 📋 Common Tasks

### Adding a New Feature

1. Identify the appropriate directory (e.g., `embeddings/`, `mcp_tools/`)
2. Check existing code in that directory for patterns
3. Write tests first (TDD approach preferred)
4. Implement the feature
5. Update documentation if directly related
6. Run tests and linting
7. Update CHANGELOG.md in the relevant directory

### Fixing a Bug

1. Write a test that reproduces the bug
2. Fix the bug with minimal changes
3. Verify all existing tests still pass
4. Update CHANGELOG.md if significant

### Adding Dependencies

1. Check for security vulnerabilities first
2. Add to `setup.py` in the appropriate `extras_require` section
3. Add to `requirements.txt` with version constraints
4. Document why the dependency is needed

## 🔒 Security Guidelines

- **Never commit secrets** to source code
- Use environment variables for sensitive configuration
- Run security scans before finalizing changes
- Be cautious with file system operations
- Validate all external inputs
- Use the `gh-advisory-database` tool for dependency checking

## 🎨 Special Features

### MCP Server

The project includes a comprehensive Model Context Protocol server with 200+ tools:

```bash
# Start MCP server
python -m ipfs_datasets_py.mcp_server
```

### CLI Tools

Multiple CLI interfaces available:

```bash
# Basic CLI
./ipfs-datasets info status
./ipfs-datasets dataset load squad

# Enhanced CLI (access to ALL 100+ tools)
python enhanced_cli.py --list-categories
python enhanced_cli.py dataset_tools load_dataset --source squad
```

### Theorem Proving

Complete pipeline from website text to verified formal logic:

```bash
python scripts/demo/demonstrate_complete_pipeline.py --install-all
python scripts/demo/demonstrate_complete_pipeline.py --url "https://legal-site.com"
```

### GraphRAG PDF Processing

AI-powered PDF processing with knowledge graphs:

```bash
python scripts/demo/demonstrate_graphrag_pdf.py --create-sample --test-queries
```

## 📚 Additional Documentation

- **README.md** - Project overview and quick start
- **CLAUDE.md** - AI worker coordination and job assignments
- **.github/workflows/README.md** - Workflow documentation
- **docs/** - Additional documentation and guides

## 🚫 What NOT to Do

1. Do **not** remove or modify working files unless absolutely necessary
2. Do **not** fix unrelated bugs or broken tests
3. Do **not** create markdown files for planning or notes (work in memory instead)
4. Do **not** modify the `.github/agents/` directory
5. Do **not** use `git reset` or `git rebase` (force push not available)
6. Do **not** commit build artifacts or dependencies (use `.gitignore`)

## ✅ Best Practices

1. **Make minimal changes** - change as few lines as possible to achieve the goal
2. **Test iteratively** - run tests after each significant change
3. **Use existing patterns** - follow the coding style and patterns already in the codebase
4. **Document as you go** - update relevant documentation with your changes
5. **Validate security** - ensure changes don't introduce vulnerabilities
6. **Review before committing** - double-check that changes are minimal and correct

## 🆘 Getting Help

- Check existing tests for usage examples
- Review similar functionality in the codebase
- Consult the comprehensive documentation in `docs/`
- Look at recent PRs for examples of good changes
- Read the workflow documentation for CI/CD issues

---

**Remember:** This is a production-ready platform with 182+ tests. Make surgical, precise changes and always validate that existing functionality continues to work.
