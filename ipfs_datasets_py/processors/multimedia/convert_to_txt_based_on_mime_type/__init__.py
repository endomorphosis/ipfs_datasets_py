"""
DEPRECATED: This conversion system has been superseded.

Use ipfs_datasets_py.processors.file_converter instead.

This module will be removed in version 3.0.0.
See PROCESSORS_REFACTORING_PLAN_2026_02_16.md for migration guide.
"""
import warnings

warnings.warn(
    "multimedia.convert_to_txt_based_on_mime_type is deprecated. "
    "Use ipfs_datasets_py.processors.file_converter.FileConverter instead. "
    "This module will be removed in v3.0.0",
    DeprecationWarning,
    stacklevel=2
)