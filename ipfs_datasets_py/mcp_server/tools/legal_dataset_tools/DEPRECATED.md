# DEPRECATED

This directory contains deprecated MCP server tool implementations.

## Migration Status

The following scrapers have been migrated to `ipfs_datasets_py/legal_scrapers/`:

- **municipal_laws_scraper.py** → `ipfs_datasets_py/legal_scrapers/scrapers/municipal.py`
- **federal_register_scraper.py** → `ipfs_datasets_py/legal_scrapers/scrapers/federal_register.py`
- **state_laws_scraper.py** → `ipfs_datasets_py/legal_scrapers/scrapers/state_laws.py`
- **recap_archive_scraper.py** → `ipfs_datasets_py/legal_scrapers/core/recap.py`
- **us_code_scraper.py** → `ipfs_datasets_py/legal_scrapers/scrapers/us_code.py`
- **state_scrapers/** → `ipfs_datasets_py/legal_scrapers/scrapers/states/`
- **unified_legal_scraper.py** → Replaced by `ipfs_datasets_py/legal_scrapers/core/base_scraper.py`
- **scraper_adapter.py** → Functionality merged into unified scraper

## New Architecture

All legal scrapers now use the unified scraper architecture:

1. **Core scrapers**: `ipfs_datasets_py/legal_scrapers/core/`
2. **Specialized scrapers**: `ipfs_datasets_py/legal_scrapers/scrapers/`
3. **MCP tools interface**: `ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/mcp_tools.py`
4. **CLI interface**: `ipfs_datasets_py/legal_scrapers/cli/legal_cli.py`

## Files to Keep

The following files provide the MCP server interface and utilities:

- `mcp_tools.py` - MCP server tool interface (calls package imports)
- `export_utils.py` - Export utilities (may need migration)
- `citation_extraction.py` - Citation utilities (may need migration)
- `ipfs_storage_integration.py` - IPFS storage (may need migration)
- Test files for validation

## Municipal Law Database Scrapers

The `municipal_law_database_scrapers/` directory contains specialized scrapers that may need review and potential migration to the unified architecture.
