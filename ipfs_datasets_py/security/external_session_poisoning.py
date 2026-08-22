"""Detect imported-session poisoning and forged receipts (EAAEF-122).

This inspector never executes imported scripts. Poisoned sessions fail closed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final


POISONING_SCHEMA: Final[str] = (
    "ipfs_datasets_py/security/external-session-poisoning@1"
)

REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        "fabricated_test",
        "fabricated_tool",
        "stale_file",
        "cross_repo_patch",
        "replayed_receipt",
        "false_approval",
        "secret_exfiltration",
        "policy_manipulation",
    }
)

_SECRET_MARKERS: Final[tuple[str, ...]] = (
    "api_key",
    "private_key",
    "password",
    "authorization",
    "secret",
    "session_token",
    "token",
)

_POLICY_MARKERS: Final[tuple[str, ...]] = (
    "ignore previous instructions",
    "skip the tests",
    "widen_effects",
    "policy_manipulation",
)


class InspectionVerdict(dict):
    """Mapping+attribute verdict so both 122 and 125 assertions work."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class SessionPoisoningError(ValueError):
    """Imported session is hostile or forged."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.admitted = False
        self.executed_scripts = False
        self.executed_imported_script = False


def _walk(value: object) -> list[Any]:
    found: list[Any] = [value]
    if isinstance(value, Mapping):
        for item in value.values():
            found.extend(_walk(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            found.extend(_walk(item))
    return found


def json_blob(value: object) -> str:
    if isinstance(value, Mapping):
        return " ".join(f"{key} {json_blob(item)}" for key, item in value.items()).lower()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return " ".join(json_blob(item) for item in value).lower()
    return str(value).lower()


def inspect_imported_session(payload: Mapping[str, Any]) -> InspectionVerdict:
    """Return an admitted verdict or raise SessionPoisoningError."""

    if not isinstance(payload, Mapping):
        raise SessionPoisoningError("session must be an object", reason_code="malformed")
    reasons: list[str] = []
    blob = json_blob(payload)
    nodes = _walk(payload)
    repo = str(payload.get("repository_id") or "")

    if payload.get("fabricated_test") or payload.get("invented_pytest"):
        reasons.append("fabricated_test")
    if payload.get("fabricated_tool") or payload.get("unregistered_tool"):
        reasons.append("fabricated_tool")
    if payload.get("stale_file") or payload.get("mtime_in_future"):
        reasons.append("stale_file")
    patch_repo = str(payload.get("patch_repository_id") or repo)
    if payload.get("cross_repo_patch") or (patch_repo and repo and patch_repo != repo):
        reasons.append("cross_repo_patch")
    if payload.get("replayed_receipt") or payload.get("receipt_nonce_reused"):
        reasons.append("replayed_receipt")
    if payload.get("false_approval") or payload.get("worker_self_approval"):
        reasons.append("false_approval")
    if payload.get("secret_exfiltration") or payload.get("contains_secret"):
        reasons.append("secret_exfiltration")
    if payload.get("policy_manipulation") or payload.get("widen_effects"):
        reasons.append("policy_manipulation")
    if payload.get("execute_imported_script"):
        raise SessionPoisoningError(
            "imported scripts are never executed",
            reason_code="policy_manipulation",
        )

    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        if node.get("collected") is False or (
            "result" in node and node.get("collected") is False
        ):
            reasons.append("fabricated_test")
        if node.get("fabricated") is True or str(node.get("name") or "").startswith(
            "unregistered"
        ):
            reasons.append("fabricated_tool")
        if node.get("stale") is True:
            reasons.append("stale_file")
        node_repo = str(node.get("repository_id") or "")
        if node_repo and repo and node_repo != repo:
            reasons.append("cross_repo_patch")
        if node.get("replayed") is True:
            reasons.append("replayed_receipt")
        if node.get("self_approved") is True or (
            node.get("actor") == "worker" and node.get("accepted") is True
        ):
            reasons.append("false_approval")
        if any(marker in {str(key).lower() for key in node} for marker in _SECRET_MARKERS):
            if any(str(node.get(key) or "") for key in node if str(key).lower() in _SECRET_MARKERS):
                reasons.append("secret_exfiltration")

    if any(marker in blob for marker in _POLICY_MARKERS):
        reasons.append("policy_manipulation")

    unique = tuple(code for code in sorted(set(reasons)) if code in REASON_CODES)
    if unique:
        raise SessionPoisoningError(
            "imported session is poisoned: " + ",".join(unique),
            reason_code=unique[0],
        )
    return InspectionVerdict(
        {
            "schema": POISONING_SCHEMA,
            "admitted": True,
            "reason_codes": (),
            "executed_imported_script": False,
            "executed_scripts": False,
        }
    )
