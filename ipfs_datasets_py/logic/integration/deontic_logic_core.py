"""Backward-compatible deontic logic core exports.

New code should import from `ipfs_datasets_py.logic.integration.converters.deontic_logic_core`.
"""

from .converters.deontic_logic_core import *  # noqa: F403
from ..types.deontic_types import DeonticOperator as DeonticOperator  # noqa: F401,E402
