"""Deterministic seed helpers for optimizer reproducibility."""

from __future__ import annotations

import random
from typing import Any, Dict, Optional


def apply_deterministic_seed(seed: Optional[int]) -> Dict[str, Any]:
    """Apply deterministic seeding for supported RNG backends.

    Args:
        seed: Integer seed value. If ``None``, no changes are applied.

    Returns:
        Dict with status flags describing which RNGs were seeded.
    """
    result: Dict[str, Any] = {"seed": seed, "python_random": False, "numpy_random": False}
    if seed is None:
        return result

    random.seed(seed)
    result["python_random"] = True

    try:
        import numpy as np  # type: ignore

        np.random.seed(seed)
        result["numpy_random"] = True
    except Exception:
        # NumPy is optional in many environments.
        pass

    return result

