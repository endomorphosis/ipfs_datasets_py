"""Tests for statement validation result serialization."""

from __future__ import annotations

import json

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.unified_optimizer import (
    StatementValidationResult,
)


def test_statement_validation_result_to_dict_is_json_serializable() -> None:
    result = StatementValidationResult(
        all_valid=False,
        provers_used=["z3"],
        errors=["Statement 1 failed verification"],
        details={"statements": [{"index": 1, "overall_valid": False}]},
    )

    payload = result.to_dict()
    assert payload["all_valid"] is False
    assert payload["provers_used"] == ["z3"]
    assert payload["errors"] == ["Statement 1 failed verification"]
    assert payload["details"]["statements"][0]["index"] == 1

    # Must be safely JSON-serializable for logging/transport.
    json.dumps(payload)
