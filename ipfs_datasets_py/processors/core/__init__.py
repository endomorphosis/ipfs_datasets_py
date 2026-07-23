"""Core infrastructure for the processors system.

This package re-exports the core protocol, detection, registry, and universal
processing interfaces used by the refactored processors stack.

Current layout notes:
- ``protocol.py`` defines the shared processor protocol and result types.
- ``input_detector.py`` contains the core-native detector utilities re-exported
  from this package.
- ``registry.py`` provides the newer consolidated registry surface re-exported
  here.
- ``processor_registry.py`` also remains in the tree and is still imported by
  some infrastructure/core modules.
- ``universal_processor.py`` provides the async core universal processor.

At the repository root, ``ipfs_datasets_py.processors`` still also exposes
root-level compatibility modules such as ``input_detection.py`` and
``universal_processor.py``.
"""

from .protocol import (
    ProcessorProtocol,
    ProcessingContext,
    ProcessingResult,
    InputType,
    Processor,
    is_processor,
)
from .input_detector import (
    InputDetector,
    detect_input,
    detect_format,
)
from .registry import (
    ProcessorRegistry,
    ProcessorEntry,
    get_global_registry,
)
from .universal_processor import (
    UniversalProcessor,
    get_universal_processor,
    process,
    process_batch,
)

__all__ = [
    'ProcessorProtocol',
    'Processor',
    'ProcessingContext',
    'ProcessingResult',
    'InputType',
    'is_processor',
    'InputDetector',
    'detect_input',
    'detect_format',
    'ProcessorRegistry',
    'ProcessorEntry',
    'get_global_registry',
    'UniversalProcessor',
    'get_universal_processor',
    'process',
    'process_batch',
]
