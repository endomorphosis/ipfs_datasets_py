"""Redaction and size bounds for Xaman payload content.

Mirrors XRPL memo privacy: free-form instruction text and nested request
bodies are omitted by default. Callers must supply an explicit policy with
the applicable redaction flag disabled to retain bounded content. Digests
remain so integrity can be checked without retaining unconstrained content.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from ..errors import InvalidRequestError


DEFAULT_MAX_INSTRUCTION_BYTES = 1024
DEFAULT_MAX_REQUEST_SUMMARY_KEYS = 32
DEFAULT_MAX_STRING_FIELD_BYTES = 512

# Keys that must never appear in exported request summaries.
_SECRET_KEY_FRAGMENTS = frozenset(
    {
        "secret",
        "seed",
        "mnemonic",
        "private",
        "privkey",
        "privatekey",
        "password",
        "passphrase",
        "apikey",
        "api_key",
        "api-key",
        "authorization",
        "bearer",
        "token_secret",
        "signing",
        "hex",
    }
)

# Safe subset of txjson / request fields retained in summaries.
_SAFE_REQUEST_KEYS = frozenset(
    {
        "TransactionType",
        "Account",
        "Destination",
        "DestinationTag",
        "Amount",
        "Fee",
        "Sequence",
        "Flags",
        "SendMax",
        "DeliverMax",
        "InvoiceID",
        "Memos",
    }
)


@dataclass(frozen=True, slots=True)
class PayloadPrivacyPolicy:
    """Bounds and redaction controls for Xaman payload content.

    Retention is opt-in. Callers may explicitly disable either redaction flag
    to retain only the corresponding bounded content.
    """

    max_instruction_bytes: int = DEFAULT_MAX_INSTRUCTION_BYTES
    max_request_summary_keys: int = DEFAULT_MAX_REQUEST_SUMMARY_KEYS
    max_string_field_bytes: int = DEFAULT_MAX_STRING_FIELD_BYTES
    redact_instruction: bool = True
    redact_request_body: bool = True
    omit_secret_keys: bool = True

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_instruction_bytes, bool)
            or not isinstance(self.max_instruction_bytes, int)
            or self.max_instruction_bytes <= 0
        ):
            raise InvalidRequestError("max_instruction_bytes must be a positive integer")
        if (
            isinstance(self.max_request_summary_keys, bool)
            or not isinstance(self.max_request_summary_keys, int)
            or self.max_request_summary_keys <= 0
        ):
            raise InvalidRequestError(
                "max_request_summary_keys must be a positive integer"
            )
        if (
            isinstance(self.max_string_field_bytes, bool)
            or not isinstance(self.max_string_field_bytes, int)
            or self.max_string_field_bytes <= 0
        ):
            raise InvalidRequestError(
                "max_string_field_bytes must be a positive integer"
            )

    def apply_instruction(self, text: str | None) -> dict[str, Any]:
        """Return bounded/redacted instruction fields."""

        if text is None:
            return {
                "custom_instruction": None,
                "custom_instruction_redacted": False,
                "custom_instruction_truncated": False,
                "original_instruction_bytes": None,
            }
        if not isinstance(text, str):
            text = str(text)
        original_bytes = len(text.encode("utf-8"))
        truncated = False
        redacted = False
        value: str | None = text
        if original_bytes > self.max_instruction_bytes:
            encoded = text.encode("utf-8")[: self.max_instruction_bytes]
            value = encoded.decode("utf-8", errors="ignore")
            truncated = True
        if self.redact_instruction and value is not None:
            value = None
            redacted = True
        return {
            "custom_instruction": value,
            "custom_instruction_redacted": redacted,
            "custom_instruction_truncated": truncated,
            "original_instruction_bytes": original_bytes,
        }

    def summarize_request(self, request: Mapping[str, Any] | None) -> dict[str, Any]:
        """Project a safe, size-bounded request summary from txjson/body."""

        if not request or not isinstance(request, Mapping):
            return {}
        if self.redact_request_body:
            return {"_redacted": True, "key_count": len(request)}

        out: dict[str, Any] = {}
        for key, value in list(request.items())[: self.max_request_summary_keys]:
            key_text = str(key)
            if self.omit_secret_keys and _is_secret_key(key_text):
                continue
            if key_text not in _SAFE_REQUEST_KEYS and not key_text[0:1].isupper():
                # Skip free-form / unknown keys unless XRPL-style PascalCase.
                continue
            out[key_text] = self._bound_value(value)
            if key_text == "Memos":
                # Memos: presence + digest only under this policy surface.
                out[key_text] = self._memo_projection(value)
        return out

    def content_digest(self, *parts: object) -> str:
        """Stable SHA-256 digest over canonical JSON of content parts."""

        payload = json.dumps(
            list(parts),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
            allow_nan=False,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def _bound_value(self, value: Any) -> Any:
        if isinstance(value, str):
            encoded = value.encode("utf-8")
            if len(encoded) > self.max_string_field_bytes:
                clipped = encoded[: self.max_string_field_bytes]
                return clipped.decode("utf-8", errors="ignore")
            return value
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, Mapping):
            nested: dict[str, Any] = {}
            for key, item in list(value.items())[: self.max_request_summary_keys]:
                key_text = str(key)
                if self.omit_secret_keys and _is_secret_key(key_text):
                    continue
                nested[key_text] = self._bound_value(item)
            return nested
        if isinstance(value, (list, tuple)):
            return [self._bound_value(item) for item in list(value)[:16]]
        return str(value)[: self.max_string_field_bytes]

    def _memo_projection(self, value: Any) -> Any:
        if not isinstance(value, (list, tuple)):
            return {"present": bool(value)}
        digests: list[str] = []
        for item in list(value)[:8]:
            digests.append(self.content_digest(item))
        return {"present": True, "count": len(value), "memo_digests": digests}


def _is_secret_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "").replace("_", "")
    for fragment in _SECRET_KEY_FRAGMENTS:
        frag = fragment.replace("-", "").replace("_", "")
        if frag and frag in normalized:
            return True
    return False


__all__ = [
    "DEFAULT_MAX_INSTRUCTION_BYTES",
    "DEFAULT_MAX_REQUEST_SUMMARY_KEYS",
    "DEFAULT_MAX_STRING_FIELD_BYTES",
    "PayloadPrivacyPolicy",
]
