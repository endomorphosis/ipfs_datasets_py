"""Regression tests for PATLAW board policy validation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_VALIDATOR_PATH = _REPO_ROOT / "scripts" / "validate_patent_legal_intelligence_board.py"


def _load_validator_module():
    spec = importlib.util.spec_from_file_location(
        "patent_legal_intelligence_validator_under_test",
        _VALIDATOR_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = _load_validator_module()


def test_task_provider_role_cannot_bypass_program_grok_primary_policy() -> None:
    cards = validator._parse_cards(
        "## PATLAW-120 example\n- Provider role: codex-implement\n",
        validator.TASK_HEADER,
    )

    assert validator._task_provider_overrides(cards[0].fields) == ["provider role"]


def test_ordinary_task_metadata_has_no_provider_override() -> None:
    cards = validator._parse_cards(
        "## PATLAW-120 example\n- Resource class: cpu-small\n",
        validator.TASK_HEADER,
    )

    assert validator._task_provider_overrides(cards[0].fields) == []
