"""Exception-path tests for agentic.github_api_unified."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.agentic.github_api_unified import UnifiedGitHubAPICache


def test_context_exit_swallows_typed_save_metrics_error(monkeypatch):
    cache = UnifiedGitHubAPICache()

    def _raise_oserror(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(cache, "save_metrics", _raise_oserror)
    assert cache.__exit__(None, None, None) is False


def test_context_exit_propagates_base_exception(monkeypatch):
    cache = UnifiedGitHubAPICache()

    def _raise_interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt("stop")

    monkeypatch.setattr(cache, "save_metrics", _raise_interrupt)
    with pytest.raises(KeyboardInterrupt):
        cache.__exit__(None, None, None)
