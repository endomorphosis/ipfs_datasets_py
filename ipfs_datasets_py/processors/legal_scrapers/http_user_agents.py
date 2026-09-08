"""Canonical HTTP User-Agent strings for official legal fetches.

This module is the only source of fetch User-Agent literals. Callers must
import these constants (or the helpers below) rather than copying the
strings. Curl probes use ``curl_user_agent_args`` / ``CURLRC_USER_AGENT_LINE``.
"""

from __future__ import annotations

from collections.abc import Sequence

DEFAULT_USER_AGENT = "OpenAI File Downloader, XaiImageApiFetch/1.0"
PAYWALL_RETRY_USER_AGENT = (
    "Claude-User (claude-code/2.1.247; +https://support.claude.com/en/)"
)
PAYWALL_RETRY_USER_AGENT_SECONDARY = (
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
    "ChatGPT-User/1.0; +https://openai.com/bot"
)
USER_AGENT_RETRY_SEQUENCE: tuple[str, ...] = (
    DEFAULT_USER_AGENT,
    PAYWALL_RETRY_USER_AGENT,
    PAYWALL_RETRY_USER_AGENT_SECONDARY,
)
CURLRC_USER_AGENT_LINE = f'user-agent = "{DEFAULT_USER_AGENT}"'

_PAYWALL_MARKERS: tuple[str, ...] = (
    "access denied",
    "paywall",
    "subscribe to continue",
    "sign in to continue",
    "signin.lexisnexis.com",
    "fortiweb",
    "cookiesrequired",
    "enable javascript and cookies",
    "just a moment",
    "captcha",
    "confirm you are human",
    "robot validation",
)


def curl_user_agent_args(user_agent: str | None = None) -> tuple[str, str]:
    """Return ``curl -A <agent>`` as an argv pair."""

    return ("-A", str(user_agent or DEFAULT_USER_AGENT))


def user_agent_retry_sequence(
    preferred: str | None = None,
) -> tuple[str, ...]:
    """Return the ordered User-Agent attempts, default first.

    An explicit *preferred* agent is tried first when it is not already the
    default, then the canonical retry sequence with duplicates removed.
    """

    ordered: list[str] = []
    preferred_text = str(preferred or "").strip()
    if preferred_text and preferred_text != DEFAULT_USER_AGENT:
        ordered.append(preferred_text)
    for agent in USER_AGENT_RETRY_SEQUENCE:
        if agent not in ordered:
            ordered.append(agent)
    return tuple(ordered)


def looks_paywalled_or_empty(
    payload: bytes | None,
    *,
    status_code: int | None = None,
) -> bool:
    """Return whether a response is empty or a paywall/access shell."""

    status = int(status_code or 0)
    if status in {401, 403, 407}:
        return True
    body = bytes(payload or b"")
    if len(body) < 32:
        return True
    sample = body[:12_000].decode("utf-8", errors="replace").casefold()
    return any(marker in sample for marker in _PAYWALL_MARKERS)


def curlrc_text() -> str:
    """Return a curlrc fragment whose only User-Agent is the default."""

    return CURLRC_USER_AGENT_LINE + "\n"


def headers_with_user_agent(
    headers: Sequence[tuple[str, str]] | dict[str, str] | None,
    user_agent: str,
) -> dict[str, str]:
    """Copy *headers* and set User-Agent, preserving an existing key's case."""

    merged = {
        str(key): str(value)
        for key, value in dict(headers or {}).items()
        if str(key).strip()
    }
    ua_key = next(
        (key for key in merged if key.lower() == "user-agent"),
        "User-Agent",
    )
    merged[ua_key] = str(user_agent)
    return merged
