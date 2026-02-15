"""Auto-registration of processor adapters.

This module provides automatic registration of all available processor adapters
into the global processor registry. It handles optional dependencies gracefully.

Usage:
    from ipfs_datasets_py.processors.adapters import register_all_adapters
    
    # Register all available adapters
    register_all_adapters()
    
    # Or with custom registry
    from ipfs_datasets_py.processors.core import ProcessorRegistry
    registry = ProcessorRegistry()
    register_all_adapters(registry=registry)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def register_all_adapters(registry: Optional['ProcessorRegistry'] = None):
    """
    Register all available processor adapters.
    
    This function attempts to register all known adapters. If an adapter
    fails to load (e.g., due to missing dependencies), it logs a warning
    and continues with other adapters.
    
    Args:
        registry: Optional ProcessorRegistry to register adapters into.
                 If None, uses the global registry.
    
    Returns:
        Number of successfully registered adapters
    
    Example:
        >>> from ipfs_datasets_py.processors.adapters import register_all_adapters
        >>> count = register_all_adapters()
        >>> print(f"Registered {count} adapters")
    """
    if registry is None:
        from ..core import get_global_registry
        registry = get_global_registry()
    
    registered_count = 0
    adapters_to_register = [
        # (name, priority, module_path, class_name)
        ("IPFSProcessor", 20, ".ipfs_adapter", "IPFSProcessorAdapter"),
        ("BatchProcessor", 15, ".batch_adapter", "BatchProcessorAdapter"),
        ("SpecializedScraper", 12, ".specialized_scraper_adapter", "SpecializedScraperAdapter"),
        ("PDFProcessor", 10, ".pdf_adapter", "PDFProcessorAdapter"),
        ("GraphRAGProcessor", 10, ".graphrag_adapter", "GraphRAGProcessorAdapter"),
        ("MultimediaProcessor", 10, ".multimedia_adapter", "MultimediaProcessorAdapter"),
        ("WebArchiveProcessor", 8, ".web_archive_adapter", "WebArchiveProcessorAdapter"),
        ("FileConverterProcessor", 5, ".file_converter_adapter", "FileConverterProcessorAdapter"),
    ]
    
    for name, priority, module_path, class_name in adapters_to_register:
        try:
            # Dynamic import of adapter
            module = __import__(
                f"ipfs_datasets_py.processors.adapters{module_path}",
                fromlist=[class_name]
            )
            adapter_class = getattr(module, class_name)
            
            # Instantiate and register
            adapter = adapter_class()
            registry.register(
                processor=adapter,
                priority=priority,
                name=name
            )
            
            registered_count += 1
            logger.info(f"✓ Registered {name} (priority={priority})")
            
        except ImportError as e:
            logger.warning(
                f"Could not load {name}: {e}. "
                f"This adapter will not be available."
            )
        except Exception as e:
            logger.error(
                f"Failed to register {name}: {e}",
                exc_info=True
            )
    
    logger.info(
        f"Adapter registration complete: {registered_count}/{len(adapters_to_register)} "
        f"adapters registered"
    )
    
    return registered_count


def is_registered(adapter_name: str, registry: Optional['ProcessorRegistry'] = None) -> bool:
    """
    Check if a specific adapter is registered.
    
    Args:
        adapter_name: Name of the adapter to check
        registry: Optional registry to check. If None, uses global registry.
    
    Returns:
        True if adapter is registered, False otherwise
    
    Example:
        >>> from ipfs_datasets_py.processors.adapters import is_registered
        >>> if is_registered("PDFProcessor"):
        ...     print("PDF processing available")
    """
    if registry is None:
        from ..core import get_global_registry
        registry = get_global_registry()
    
    # Check if adapter exists in registry
    try:
        processors = registry.get_capabilities()
        return any(p.get("name") == adapter_name for p in processors.get("enabled", []))
    except Exception:
        return False


def get_available_adapters(registry: Optional['ProcessorRegistry'] = None) -> list:
    """
    Get list of all available (registered) adapters.
    
    Args:
        registry: Optional registry to query. If None, uses global registry.
    
    Returns:
        List of dictionaries with adapter information (name, priority, formats)
    
    Example:
        >>> from ipfs_datasets_py.processors.adapters import get_available_adapters
        >>> adapters = get_available_adapters()
        >>> for adapter in adapters:
        ...     print(f"{adapter['name']}: {adapter['formats']}")
    """
    if registry is None:
        from ..core import get_global_registry
        registry = get_global_registry()
    
    try:
        caps = registry.get_capabilities()
        return caps.get("enabled", [])
    except Exception as e:
        logger.error(f"Failed to get available adapters: {e}")
        return []


# Auto-register adapters on module import (optional)
# Uncomment the following line to enable auto-registration:
# register_all_adapters()
