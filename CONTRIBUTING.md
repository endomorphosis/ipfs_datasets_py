# Contributing to IPFS Datasets Python

Thank you for your interest in contributing to IPFS Datasets Python! This document provides guidelines for contributing to the project.

## Quick Start

1. **Fork the repository** on GitHub
2. **Clone your fork**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/ipfs_datasets_py.git
   cd ipfs_datasets_py
   ```
3. **Install in development mode**:
   ```bash
   pip install -e ".[all]"
   pip install -e ".[test]"
   ```
4. **Create a branch** for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Setup

### Prerequisites

- Python 3.12+
- Git
- IPFS daemon (optional but recommended)

### Installation

```bash
# Install dependencies
python install.py --quick

# Or install specific profiles
python install.py --profile ml
python install.py --profile test

# Check installation
python dependency_health_checker.py check
```

### Running Tests

```bash
# Run all tests
pytest

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
pytest -m "not slow"  # Exclude slow tests

# With coverage
pytest --cov=ipfs_datasets_py --cov-report=html
```

See the [Developer Guide](docs/developer_guide.md) for comprehensive testing information.

## Making Changes

### Code Style

- Follow PEP 8 style guidelines
- Use type hints for all function parameters and return values
- Add docstrings to all public classes and methods
- See [docs/_example_docstring_format.md](docs/archive/deprecated/_example_docstring_format.md) for the standard format

### Testing

- **Write tests** for all new features
- **Update existing tests** when modifying functionality
- Follow the **GIVEN-WHEN-THEN** format
- See [docs/_example_test_format.md](docs/archive/deprecated/_example_test_format.md) for the standard template

### Documentation

- **Update documentation** for any user-facing changes
- Add docstrings following the project standard
- Update relevant guides in `docs/`
- Keep README.md up to date

### Commit Messages

Write clear commit messages:
```
feat: Add new vector store backend for Qdrant

- Implement QdrantVectorStore class
- Add connection pooling
- Update documentation
- Add tests
```

Use conventional commit types:
- `feat:` - New features
- `fix:` - Bug fixes
- `docs:` - Documentation changes
- `test:` - Test updates
- `refactor:` - Code refactoring
- `perf:` - Performance improvements
- `chore:` - Maintenance tasks

## Submitting Changes

### Pull Request Process

1. **Ensure all tests pass**: `pytest`
2. **Run linters**: `flake8 ipfs_datasets_py/` and `mypy ipfs_datasets_py/`
3. **Update documentation** as needed
4. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```
5. **Create a Pull Request** on GitHub with:
   - Clear title describing the change
   - Description of what changed and why
   - Reference any related issues
   - Screenshots for UI changes

### PR Review

- Maintainers will review your PR
- Address any feedback or requested changes
- Keep the PR updated with the main branch
- Once approved, it will be merged

## What to Contribute

### Good First Issues

Look for issues labeled:
- `good first issue` - Great for newcomers
- `help wanted` - Community help needed
- `documentation` - Documentation improvements

### Areas Needing Help

- **Documentation**: Tutorials, guides, examples
- **Testing**: More test coverage
- **Bug fixes**: Check the issue tracker
- **Features**: Propose new features via issues first

## Code of Conduct

### Our Standards

- **Be respectful** and inclusive
- **Be collaborative** and constructive
- **Focus on what's best** for the community
- **Show empathy** towards others

### Unacceptable Behavior

- Harassment or discriminatory language
- Trolling or insulting comments
- Personal or political attacks
- Publishing others' private information

## Getting Help

- **Documentation**: See [docs/](docs/)
- **Questions**: Use GitHub Discussions
- **Bugs**: Create an issue with details
- **Chat**: Join community discussions

## Project Structure

```
ipfs_datasets_py/
├── ipfs_datasets_py/      # Main package
│   ├── embeddings/        # Embedding models
│   ├── rag/               # GraphRAG
│   ├── pdf_processing/    # PDF handling
│   ├── multimedia/        # Media processing
│   ├── mcp_server/        # MCP server (200+ tools)
│   └── ...
├── tests/                 # Test suite
│   ├── unit/             # Unit tests
│   ├── integration/      # Integration tests
│   └── e2e/              # End-to-end tests
├── docs/                  # Documentation
├── scripts/               # Utility scripts
└── examples/              # Example code
```

## Development Guidelines

### Adding New Features

1. **Discuss first**: Create an issue to discuss the feature
2. **Design**: Document the approach
3. **Implement**: Write code with tests
4. **Document**: Update relevant docs
5. **Submit**: Create a pull request

### Bug Fixes

1. **Reproduce**: Create a failing test
2. **Fix**: Make minimal changes to fix the issue
3. **Test**: Ensure tests pass
4. **Document**: Update if needed
5. **Submit**: Create a pull request

### Adding Dependencies

- Check for security vulnerabilities
- Add to `setup.py` in appropriate `extras_require`
- Document why the dependency is needed
- Use version constraints

## Release Process

Maintainers handle releases:
1. Update version in `setup.py`
2. Update `CHANGELOG.md`
3. Create release tag
4. Build and publish to PyPI

## Security

- **Do not commit secrets** or sensitive data
- Use environment variables for configuration
- Report security issues privately to maintainers

## License

By contributing, you agree that your contributions will be licensed under the same license as the project (see [LICENSE](LICENSE)).

## Questions?

- **General Questions**: GitHub Discussions
- **Bug Reports**: GitHub Issues
- **Security Issues**: Email maintainers directly

## Thank You!

Your contributions make this project better for everyone. We appreciate your time and effort! 🎉

---

For more detailed information, see the [Developer Guide](docs/developer_guide.md).
