# TDFOL Documentation Quick Reference

## 🚀 Quick Start

### View Documentation Locally

```bash
cd docs/tdfol
make html
python -m http.server 8000 --directory _build/html
# Open http://localhost:8000 in browser
```

### Rebuild Documentation

```bash
cd docs/tdfol
make clean
make html
```

## 📚 Key Documentation Sections

### For New Users
1. **Getting Started** → `tutorials/getting_started.rst`
2. **Quick Start** → `tutorials/quick_start.rst`
3. **Formula Syntax** → `tutorials/formula_syntax.rst`
4. **Basic Examples** → `examples/basic_examples.rst`

### For Developers
1. **API Reference** → `api/` directory
2. **Core Module** → `api/core.rst`
3. **Prover Module** → `api/prover.rst`
4. **Architecture** → `architecture/overview.rst`

### For Advanced Users
1. **Optimization** → `api/optimization.rst`
2. **Modal Tableaux** → `api/modal_tableaux.rst`
3. **ZKP Integration** → `api/zkp_integration.rst`
4. **Visualization** → `api/visualization.rst`

## 🔍 Navigation Tips

### Search
- Use the search box in the top-left corner
- Searches across all documentation
- Includes API references and examples

### Index
- Click "Index" in the footer
- Alphabetical listing of all symbols
- Direct links to definitions

### Module Index
- Click "Module Index" in the footer
- Lists all Python modules
- Quick access to module documentation

## 📝 File Locations

```
docs/tdfol/
├── index.rst              # Main entry point
├── api/                   # API reference
│   ├── core.rst          # tdfol_core.py
│   ├── prover.rst        # tdfol_prover.py
│   ├── parser.rst        # tdfol_parser.py
│   └── ...               # 11 API files total
├── tutorials/            # Step-by-step guides
├── examples/             # Code examples
└── architecture/         # System architecture

_build/html/              # Generated HTML
├── index.html           # Entry point
├── api/                 # API docs
├── tutorials/           # Tutorial pages
└── ...
```

## 🛠️ Common Tasks

### Add New API Documentation
1. Create `.rst` file in `api/` directory
2. Add `.. automodule::` directive
3. Add to `index.rst` toctree
4. Run `make html`

### Add New Tutorial
1. Create `.rst` file in `tutorials/` directory
2. Write content in reStructuredText
3. Add to `index.rst` toctree
4. Run `make html`

### Add New Example
1. Create `.rst` file in `examples/` directory
2. Add code blocks with examples
3. Add to `index.rst` toctree
4. Run `make html`

## 🎨 Formatting Guide

### Code Blocks
```rst
.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import TDFOLProver
    prover = TDFOLProver(kb)
```

### Cross-References
```rst
See :ref:`api-core` for more details.
See :py:class:`TDFOLProver` for API.
```

### Headings
```rst
Main Heading
============

Subheading
----------

Sub-subheading
^^^^^^^^^^^^^^
```

## 📊 Documentation Statistics

- **HTML Pages**: 59
- **API Reference Docs**: 11
- **Tutorial Guides**: 12
- **Example Collections**: 8
- **Architecture Docs**: 5
- **Total Files**: 40+
- **Code Examples**: 50+

## 🔗 Related Files

- **Sphinx Config**: `conf.py`
- **Build File**: `Makefile`
- **Requirements**: `requirements-docs.txt`
- **README**: `README.md`
- **Completion Report**: `TASK_12.3_COMPLETE.md`

## 💡 Tips

1. **Auto-rebuild**: Use `make livehtml` for automatic rebuilds
2. **Check warnings**: Review build warnings for issues
3. **Test examples**: Ensure code examples are up-to-date
4. **Update index**: Keep `index.rst` synchronized with structure
5. **Version control**: Commit documentation with code changes

## 🐛 Troubleshooting

### Build Fails
```bash
# Check Python version (3.12+ required)
python --version

# Reinstall dependencies
pip install -r requirements-docs.txt

# Clean and rebuild
make clean
make html
```

### Missing Modules
```bash
# Install TDFOL package
cd ../..
pip install -e .
```

### Warnings
- Most warnings are from stub pages (expected)
- Check undefined label warnings
- Verify cross-references exist

## 📞 Support

- **GitHub Issues**: https://github.com/ipfs-datasets/ipfs_datasets_py/issues
- **Documentation**: https://ipfs-datasets.readthedocs.io/
- **Project README**: ../../README.md

---

**Last Updated**: 2024-02-18  
**Version**: 1.0.0
