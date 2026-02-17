"""
Common utilities and patterns for the logic module.

This package provides shared utilities that are used across multiple logic
submodules to reduce code duplication and standardize common patterns.

Created during Phase 2 - Quality Improvements.
Enhanced during Phase 4 - Cache Unification.
"""

from .errors import (
    LogicError,
    ConversionError,
    ValidationError,
    ProofError,
    TranslationError,
    BridgeError,
    ConfigurationError,
    DeonticError,
    ModalError,
    TemporalError,
)

from .converters import (
    LogicConverter,
    ChainedConverter,
    ConversionResult,
    ConversionStatus,
    ValidationResult,
)

from .utility_monitor import (
    UtilityMonitor,
    track_performance,
    with_caching,
    get_global_stats,
    clear_global_cache,
    reset_global_stats,
)

from .bounded_cache import BoundedCache

from .proof_cache import (
    ProofCache,
    CachedProofResult,
    get_global_cache,
)

from .feature_detection import (
    FeatureDetector,
    warn_optional_imports_enabled,
    minimal_imports_enabled,
    optional_import_notice,
    clear_feature_detection_cache,
    is_module_available,
    require_module,
    import_optional_module,
)

__all__ = [
    # Error classes
    "LogicError",
    "ConversionError",
    "ValidationError",
    "ProofError",
    "TranslationError",
    "BridgeError",
    "ConfigurationError",
    "DeonticError",
    "ModalError",
    "TemporalError",
    # Converter classes
    "LogicConverter",
    "ChainedConverter",
    "ConversionResult",
    "ConversionStatus",
    "ValidationResult",
    # Utility monitoring
    "UtilityMonitor",
    "track_performance",
    "with_caching",
    "get_global_stats",
    "clear_global_cache",
    "reset_global_stats",
    # Caching
    "BoundedCache",
    "ProofCache",
    "CachedProofResult",
    "get_global_cache",
    # Feature detection
    "FeatureDetector",
    "warn_optional_imports_enabled",
    "minimal_imports_enabled",
    "optional_import_notice",
    "clear_feature_detection_cache",
    "is_module_available",
    "require_module",
    "import_optional_module",
]
