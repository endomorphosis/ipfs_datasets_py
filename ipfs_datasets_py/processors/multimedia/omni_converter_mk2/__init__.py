"""
DEPRECATED: This conversion system has been superseded.

Use ipfs_datasets_py.processors.file_converter instead.

This module will be removed in version 3.0.0.
See PROCESSORS_REFACTORING_PLAN_2026_02_16.md for migration guide.
"""
import warnings

warnings.warn(
    "multimedia.omni_converter_mk2 is deprecated. "
    "Use ipfs_datasets_py.processors.file_converter.FileConverter instead. "
    "This module will be removed in v3.0.0",
    DeprecationWarning,
    stacklevel=2
)

import sys
import os

this_dir = os.path.dirname(__file__)
sys.path.append(os.path.abspath(os.path.join(this_dir, 'utils')))