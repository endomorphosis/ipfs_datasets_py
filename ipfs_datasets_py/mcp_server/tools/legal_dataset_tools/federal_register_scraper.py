"""
Federal Register Scraper MCP Tool

MCP tool wrapper for the Federal Register scraper.
The core implementation is in ipfs_datasets_py.processors.legal_scrapers.federal_register_scraper
"""

from importlib import import_module

_FEDERAL_REGISTER_MODULE_PATHS = (
    "ipfs_datasets_py.processors.legal_scrapers.federal_register_scraper",
    "ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.federal_register_scraper",
)

_federal_register_module = None
_last_error = None
for _module_path in _FEDERAL_REGISTER_MODULE_PATHS:
    try:
        _federal_register_module = import_module(_module_path)
        break
    except (ImportError, ModuleNotFoundError) as exc:
        _last_error = exc

if _federal_register_module is None:
    raise ModuleNotFoundError("Unable to import Federal Register scraper module") from _last_error

_exported_names = getattr(_federal_register_module, "__all__", None)
if _exported_names is None:
    _exported_names = [name for name in dir(_federal_register_module) if not name.startswith("_")]

for _name in _exported_names:
    globals()[_name] = getattr(_federal_register_module, _name)

__all__ = list(_exported_names)
