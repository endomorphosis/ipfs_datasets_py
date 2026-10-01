"""Shared deterministic source screening for autoencoder consumers.

Extracted without changing the supervisor screening predicates.
"""
from __future__ import annotations
import re
from pathlib import PurePosixPath
from typing import Final

_SECRET_PATTERNS: Final[tuple[re.Pattern[bytes], ...]] = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
    re.compile(
        rb"(?i)\b(?:api[_-]?key|password|private[_-]?key|secret|token)"
        rb"\s*[:=]\s*[\"'][^\"'\r\n]{12,}[\"']"
    ),
)

_CREDENTIAL_FILENAMES: Final[frozenset[str]] = frozenset(
    {
        ".env",
        ".netrc",
        "_netrc",
        "credentials",
        "credentials.json",
        "credentials.yaml",
        "credentials.yml",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
    }
)

_CREDENTIAL_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".der", ".jks", ".key", ".keystore", ".p12", ".pem", ".pfx", ".pkcs12"}
)

class SourceScreeningError(RuntimeError):
    """Fail-closed rejection for an unsafe or incomplete analysis factory run."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "planning_analysis_factory_error",
    ) -> None:
        super().__init__(message)
        self.reason_code = str(reason_code or "planning_analysis_factory_error")

class SourceSecretError(SourceScreeningError):
    def __init__(self, message: str) -> None:
        super().__init__(message, reason_code="secret_material")

def _contains_secret(payload: bytes) -> bool:
    return any(pattern.search(payload) for pattern in _SECRET_PATTERNS)

def _credential_path_reason(path: str) -> str:
    pure = PurePosixPath(path)
    name = pure.name.casefold()
    if name in _CREDENTIAL_FILENAMES or pure.suffix.casefold() in _CREDENTIAL_SUFFIXES:
        return "credential_path"
    if name.startswith(".env"):
        return "credential_path"
    return ""

# Compatibility names for existing consumers.
PlanningAnalysisFactoryError = SourceScreeningError
PlanningAnalysisSecretError = SourceSecretError
