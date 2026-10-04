"""
US Code Scraper MCP Tool

MCP tool wrapper for the US Code scraper.
The core implementation is in ipfs_datasets_py.processors.legal_scrapers.us_code_scraper
"""

from importlib import import_module

_US_CODE_MODULE_PATHS = (
    "ipfs_datasets_py.processors.legal_scrapers.us_code_scraper",
    "ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.us_code_scraper",
)

_us_code_module = None
_last_error = None
for _module_path in _US_CODE_MODULE_PATHS:
    try:
        _us_code_module = import_module(_module_path)
        break
    except (ImportError, ModuleNotFoundError) as exc:
        _last_error = exc

if _us_code_module is None:
    raise ModuleNotFoundError("Unable to import US Code scraper module") from _last_error

_exported_names = getattr(_us_code_module, "__all__", None)
if _exported_names is None:
    _exported_names = [name for name in dir(_us_code_module) if not name.startswith("_")]

for _name in _exported_names:
    globals()[_name] = getattr(_us_code_module, _name)

__all__ = list(_exported_names)
