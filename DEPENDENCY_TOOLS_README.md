# IPFS Datasets Dependency Management Tools

This suite provides comprehensive dependency management for the IPFS Datasets Python project, preventing dependency-related errors and ensuring smooth CLI operation.

## 🚀 Quick Start

### Option 1: One-command Setup
```bash
python install.py --quick
```

### Option 2: Interactive Setup Wizard
```bash
python install.py
```

### Option 3: Specific Profile
```bash
python install.py --profile cli
```

## 🛠️ Available Tools

### 1. `install.py` - Unified Installer
**Main entry point for all dependency management**

```bash
# Interactive wizard
python install.py

# Quick setup (core dependencies)
python install.py --quick

# Install specific profile
python install.py --profile ml

# Health check
python install.py --health

# Show current status
python install.py --status
```

Available profiles: `minimal`, `cli`, `pdf`, `ml`, `vectors`, `web`, `media`, `api`, `dev`, `full`

### 2. `dependency_manager.py` - Advanced Management
**Comprehensive dependency analysis and management**

```bash
# Analyze all dependencies in codebase
python dependency_manager.py analyze

# Interactive setup with recommendations
python dependency_manager.py setup

# Install specific profile
python dependency_manager.py install --profile pdf

# Validate all dependencies
python dependency_manager.py validate

# Generate detailed report
python dependency_manager.py report --output deps.json
```

### 3. `dependency_health_checker.py` - Health Monitoring
**Monitor dependency health and CLI functionality**

```bash
# Quick health check
python dependency_health_checker.py check

# Continuous monitoring (every 5 minutes)
python dependency_health_checker.py monitor --interval 300

# Generate health report
python dependency_health_checker.py report --output health.json
```

### 4. `quick_setup.py` - Fast Core Setup
**Install core dependencies quickly**

```bash
python quick_setup.py
```

Installs essential packages for basic CLI functionality.

### 5. `install_deps.py` - Profile Installer
**Auto-generated script for specific profiles**

```bash
# Generated after running quick_setup.py
python install_deps.py cli      # CLI tools
python install_deps.py pdf      # PDF processing
python install_deps.py ml       # Machine learning
python install_deps.py web      # Web scraping
```

## 📊 Installation Profiles

### `minimal` - Basic functionality
- `requests`, `pyyaml`, `tqdm`, `psutil`, `jsonschema`

### `cli` - CLI tools functionality
- Basic + `numpy`, `pandas`, `pydantic`, `pyarrow`

### `pdf` - PDF processing capabilities
- CLI + `pymupdf`, `pdfplumber`, `pytesseract`, `pillow`, `opencv-python`, `networkx`

### `ml` - Machine learning and AI
- `numpy`, `torch`, `transformers`, `sentence-transformers`, `datasets`, `scipy`, `scikit-learn`, `nltk`

### `vectors` - Vector storage and search
- `numpy`, `faiss-cpu`, `qdrant-client`, `elasticsearch`, `sentence-transformers`

### `web` - Web scraping and archiving
- `requests`, `beautifulsoup4`, `aiohttp`, `newspaper3k`, `cdx-toolkit`, `wayback`, `selenium`

### `media` - Media processing
- `ffmpeg-python`, `moviepy`, `pillow`, `opencv-python`, `yt-dlp`

### `api` - FastAPI web services
- `fastapi`, `uvicorn`, `pydantic`, `python-multipart`, `PyJWT`

### `dev` - Development and testing
- `pytest`, `pytest-cov`, `coverage`, `mypy`, `flake8`, `black`

### `full` - Everything
- All profiles combined

## 🔧 Environment Variables

Set these to control dependency installation behavior:

```bash
# Enable automatic dependency installation
export IPFS_DATASETS_AUTO_INSTALL=true

# Enable verbose installation output
export IPFS_INSTALL_VERBOSE=true
```

## 🏥 Health Monitoring

### Health Status Levels:
- **✅ Healthy**: All critical dependencies available, CLI tests pass
- **⚠️ Degraded**: Some optional dependencies missing, non-critical issues
- **🚨 Critical**: Missing critical dependencies or CLI tests failing

### Critical Dependencies:
- `numpy`, `pandas`, `requests`, `yaml`, `tqdm`, `psutil`

### CLI Functionality Tests:
- Basic CLI help and commands
- Enhanced CLI functionality
- Tool listing and categorization

## 📈 Usage Examples

### Scenario 1: New Installation
```bash
# Start with quick setup
python install.py --quick

# Check health
python dependency_health_checker.py check

# Install additional features as needed
python install.py --profile pdf
```

### Scenario 2: Troubleshooting Issues
```bash
# Check what's missing
python dependency_manager.py analyze

# Get health status
python dependency_health_checker.py check

# Fix issues interactively
python dependency_manager.py setup
```

### Scenario 3: Production Deployment
```bash
# Install full profile
python install.py --profile full

# Validate everything works
python dependency_manager.py validate

# Monitor health
python dependency_health_checker.py monitor --interval 600
```

### Scenario 4: Continuous Integration
```bash
# Install minimal dependencies
python install.py --profile minimal

# Run health check (exit code 0 = success)
python dependency_health_checker.py check --quiet

# Test CLI functionality
python comprehensive_cli_test.py
```

## 🐛 Troubleshooting

### Common Issues:

**1. Import errors when running CLI tools**
```bash
# Solution: Install missing dependencies
python install.py --quick
```

**2. CLI tools are slow to start**
```bash
# Solution: Check for slow imports
python dependency_health_checker.py check
```

**3. Specific tool categories not working**
```bash
# Solution: Install profile for that category
python install.py --profile pdf  # for PDF tools
python install.py --profile ml   # for ML tools
```

**4. Auto-installation not working**
```bash
# Solution: Enable auto-installation
export IPFS_DATASETS_AUTO_INSTALL=true
python install.py --enable-auto-install
```

### Debug Information:
- Run any tool with `--verbose` for detailed output
- Check `dependency_report.json` for comprehensive analysis
- Monitor `health_report_*.json` files for ongoing issues

## 🔗 Integration with CLI Tools

After installing dependencies, test CLI functionality:

```bash
# Test basic CLI
python ipfs_datasets_cli.py --help
python ipfs_datasets_cli.py info status

# Test enhanced CLI
python enhanced_cli.py --list-categories
python enhanced_cli.py dataset_tools load_dataset --help

# Run comprehensive tests
python comprehensive_cli_test.py
```

## 🎯 Best Practices

1. **Start with quick setup** for basic functionality
2. **Use profiles** to install only what you need
3. **Monitor health** regularly in production
4. **Enable auto-install** for development environments
5. **Check health before** deploying or running critical tasks
6. **Use the unified installer** (`install.py`) as your main entry point

## 📚 Additional Resources

- See `CLI_README.md` for CLI tool documentation
- Check `comprehensive_cli_test.py` for testing examples
- Review `auto_installer.py` for advanced installation options
- Examine generated `dependency_report.json` for detailed analysis

---

**Need help?** Run `python install.py` for the interactive wizard or `python dependency_health_checker.py check` to diagnose issues.