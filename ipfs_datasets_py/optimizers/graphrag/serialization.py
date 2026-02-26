"""Serialization helpers for GraphRAG query optimizer state.

This module was extracted from the unified query optimizer so learning-state
save/load behavior is shared and independently testable. It complements the
split query layout alongside ``query_planner.py``, ``learning_adapter.py``,
and ``traversal_heuristics.py``.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path as _Path
from typing import Any, Callable, Dict, Optional, Tuple

from ipfs_datasets_py.optimizers.common.path_validator import (
    validate_input_path,
    validate_output_path,
)


def resolve_learning_state_filepath(
    filepath: Optional[str],
    metrics_dir: Optional[str],
) -> Optional[str]:
    """Resolve default learning-state path when not explicitly provided."""
    if filepath is not None:
        return filepath
    if metrics_dir:
        return os.path.join(metrics_dir, "learning_state.json")
    return None


def build_learning_state(
    learning_enabled: bool,
    learning_cycle: int,
    learning_parameters: Dict[str, Any],
    traversal_stats: Dict[str, Any],
    entity_importance_cache: Dict[str, Any],
) -> Dict[str, Any]:
    """Build serializable learning state payload."""
    return {
        "learning_enabled": learning_enabled,
        "learning_cycle": learning_cycle,
        "learning_parameters": learning_parameters,
        "traversal_stats": traversal_stats,
        "entity_importance_cache": entity_importance_cache,
        "timestamp": datetime.datetime.now().isoformat(),
    }


def save_learning_state_payload(
    filepath: str,
    state: Dict[str, Any],
    numpy_json_serializable: Callable[[Any], Any],
    safe_error_text: Callable[[Exception], str],
    metrics_collector: Any = None,
) -> Optional[str]:
    """Save learning state with graceful fallback when serialization fails."""
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

    try:
        serializable_state = numpy_json_serializable(state)
        
        # Validate output path
        base_dir = _Path(filepath).parent if _Path(filepath).is_absolute() else None
        safe_filepath = validate_output_path(filepath, allow_overwrite=True, base_dir=base_dir)
        
        with open(safe_filepath, "w", encoding="utf-8") as f:
            json.dump(serializable_state, f, indent=2)
        return filepath
    except (TypeError, ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
        error_message = (
            "Error serializing learning state to JSON: "
            f"{safe_error_text(error)}"
        )

        fallback_state = {
            "error": error_message,
            "timestamp": datetime.datetime.now().isoformat(),
            "partial_state": True,
            "learning_enabled": state.get("learning_enabled", False),
            "learning_cycle": state.get("learning_cycle", 0),
            "learning_cycles_completed": state.get("learning_cycle", 0),
        }

        try:
            # Validate output path
            base_dir = _Path(filepath).parent if _Path(filepath).is_absolute() else None
            safe_filepath = validate_output_path(filepath, allow_overwrite=True, base_dir=base_dir)
            
            with open(safe_filepath, "w", encoding="utf-8") as f:
                json.dump(fallback_state, f, indent=2)
            return filepath
        except (TypeError, ValueError, RuntimeError, OSError):
            if metrics_collector is not None:
                metrics_collector.record_additional_metric(
                    name="serialization_error",
                    value=f"Failed to save learning state: {error_message}",
                    category="error",
                )
            return None


def load_learning_state_payload(
    filepath: str,
    safe_error_text: Callable[[Exception], str],
    logger: Any = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Load learning state payload from disk."""
    if not os.path.exists(filepath):
        return False, {}

    try:
        # Validate input path
        base_dir = _Path(filepath).parent if _Path(filepath).is_absolute() else None
        safe_filepath = validate_input_path(filepath, must_exist=True, base_dir=base_dir)
        
        with open(safe_filepath, "r", encoding="utf-8") as f:
            state = json.load(f)
        return True, state
    except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError, AttributeError) as error:
        if logger is not None:
            logger.error(
                f"Error loading learning state: {safe_error_text(error)}"
            )
        return False, {}