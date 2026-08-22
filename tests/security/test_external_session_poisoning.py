"""EAAEF-122: imported session poisoning fails closed."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.security.external_session_poisoning import (
    SessionPoisoningError,
    inspect_imported_session,
)


def test_clean_session_is_admitted() -> None:
    verdict = inspect_imported_session(
        {
            "repository_id": "repo:demo",
            "patch_repository_id": "repo:demo",
            "receipt_nonce": "nonce-1",
        }
    )
    assert verdict["admitted"] is True
    assert verdict["executed_imported_script"] is False


@pytest.mark.parametrize(
    "payload,code",
    [
        ({"fabricated_test": True}, "fabricated_test"),
        ({"fabricated_tool": True}, "fabricated_tool"),
        ({"stale_file": True}, "stale_file"),
        ({"repository_id": "repo:a", "patch_repository_id": "repo:b"}, "cross_repo_patch"),
        ({"replayed_receipt": True}, "replayed_receipt"),
        ({"false_approval": True}, "false_approval"),
        ({"secret_exfiltration": True, "contains_secret": True}, "secret_exfiltration"),
        ({"policy_manipulation": True}, "policy_manipulation"),
    ],
)
def test_poisoned_sessions_fail_closed(payload: dict, code: str) -> None:
    with pytest.raises(SessionPoisoningError) as exc:
        inspect_imported_session(payload)
    assert exc.value.reason_code == code


def test_imported_scripts_are_never_executed() -> None:
    with pytest.raises(SessionPoisoningError, match="never executed"):
        inspect_imported_session({"execute_imported_script": True})
