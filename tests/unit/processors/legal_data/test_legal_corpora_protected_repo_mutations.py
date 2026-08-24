"""Protected-repository mutation guard tests (LCR-084)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.huggingface.protected_repo_guard import (
    PROTECTED_REPOS,
    ProtectedRepoGuardError,
    guarded_write,
    is_protected_repo,
    require_unprotected_or_runtime,
)


def test_protected_repo_literals_are_exact() -> None:
    assert "justicedao/ipfs_state_laws" in PROTECTED_REPOS
    assert "justicedao/ipfs_federal_register" in PROTECTED_REPOS
    assert is_protected_repo("justicedao/ipfs_state_laws")
    assert not is_protected_repo("justicedao/other")


def test_unprotected_write_is_allowed() -> None:
    require_unprotected_or_runtime("justicedao/other", method="upload_file")
    assert guarded_write("justicedao/other", "upload_file", lambda: 7) == 7


def test_protected_write_without_runtime_fails_closed() -> None:
    with pytest.raises(ProtectedRepoGuardError):
        require_unprotected_or_runtime(
            "justicedao/ipfs_state_laws",
            method="create_commit",
            runtime_authorized=False,
        )
    called = {"n": 0}

    def _cb() -> None:
        called["n"] += 1

    with pytest.raises(ProtectedRepoGuardError):
        guarded_write("justicedao/ipfs_federal_register", "upload_file", _cb)
    assert called["n"] == 0


def test_protected_write_with_runtime_authorization_invokes_callback() -> None:
    assert (
        guarded_write(
            "justicedao/ipfs_state_laws",
            "create_commit",
            lambda: "ok",
            runtime_authorized=True,
        )
        == "ok"
    )
