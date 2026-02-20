"""Software Engineering Theorems for Temporal Deontic Logic (thin MCP wrapper).

Business logic (``SOFTWARE_THEOREMS`` dict, ``list_software_theorems``,
``validate_against_theorem``, ``_evaluate_condition``, ``apply_theorem_actions``) lives in:
    ipfs_datasets_py.processors.development.software_theorems_engine
"""

import logging
from typing import Any, Dict, Optional

from ipfs_datasets_py.processors.development.software_theorems_engine import (  # noqa: F401
    SOFTWARE_THEOREMS,
    _evaluate_condition,
    list_software_theorems,
    validate_against_theorem,
    apply_theorem_actions,
)

logger = logging.getLogger(__name__)
