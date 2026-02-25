"""Tests for deprecated export version-gate behavior in logic_theorem_optimizer."""

from __future__ import annotations

import pytest

import ipfs_datasets_py.optimizers.logic_theorem_optimizer as lto


@pytest.mark.parametrize(
    ("symbol", "version", "should_raise"),
    [
        ("TheoremSession", "0.3.9", False),
        ("TheoremSession", "0.4.0", True),
        ("SessionConfig", "0.3.1", False),
        ("SessionConfig", "0.4.0", True),
        ("SessionResult", "0.3.5", False),
        ("SessionResult", "0.4.0", True),
        ("LogicExtractor", "0.3.2", False),
        ("LogicExtractor", "0.4.0", True),
    ],
)
def test_enforce_export_version_gate(symbol: str, version: str, should_raise: bool) -> None:
    if should_raise:
        with pytest.raises(ImportError):
            lto._enforce_export_version_gate(symbol, current_version=version)
    else:
        lto._enforce_export_version_gate(symbol, current_version=version)


def test_getattr_blocks_deprecated_exports_at_removal_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lto, "__version__", "0.4.0")

    with pytest.raises(ImportError):
        getattr(lto, "TheoremSession")

    with pytest.raises(ImportError):
        getattr(lto, "LogicExtractor")


def test_getattr_allows_deprecated_exports_before_removal_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lto, "__version__", "0.3.9")

    theorem_session = getattr(lto, "TheoremSession")
    logic_extractor = getattr(lto, "LogicExtractor")

    assert theorem_session.__name__ == "TheoremSession"
    assert logic_extractor.__name__ == "LogicExtractor"
