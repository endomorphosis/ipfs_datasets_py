"""DuckDB-backed SMS bridge for ipfs_datasets_py.

The bridge is intentionally provider-agnostic. Google Voice does not expose a
stable supported SMS/SIP automation API for production use, so this module
targets supported provider surfaces such as Twilio or an internal webhook
adapter instead.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import os
import re
import smtplib
import uuid
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

try:
    from fastapi import FastAPI, HTTPException, Query, Request
    from fastapi.responses import Response
except Exception:  # pragma: no cover - optional dependency
    FastAPI = None  # type: ignore[assignment]
    HTTPException = None  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    Request = None  # type: ignore[assignment]
    Response = None  # type: ignore[assignment]

from pydantic import BaseModel, Field

try:
    import uvicorn
except Exception:  # pragma: no cover - optional dependency
    uvicorn = None  # type: ignore[assignment]


_PHONE_DIGITS_RE = re.compile(r"\D")
_TWILIO_EMPTY_RESPONSE = b'<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
_DEFAULT_VOICE_GREETING = "Hi, this is Abby voice with 211 AI. Tell me what you need help with after the tone."
_DEFAULT_VOICE_NO_SPEECH_PROMPT = "I didn't catch that. Please tell me what you need help with."
_DEFAULT_VOICE_FOLLOW_UP = "What else can I help with today?"
_DEFAULT_VOICE_FAREWELL = "Thanks for calling 211 AI. Goodbye."
_DEFAULT_VOICE_UNAVAILABLE_PROMPT = "I'm sorry, the AI voice service is unavailable right now. Please try again later or use the website chat."
_VOICE_HANGUP_PATTERNS = re.compile(r"\b(?:bye|goodbye|that is all|hang up|stop now|end call|no thanks)\b", re.IGNORECASE)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _model_dump(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return dict(model.model_dump())
    return dict(model.dict())


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), sort_keys=True)


def _coerce_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if metadata is None:
        return {}
    return dict(metadata)


def _first_non_empty(*values: str | None) -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


def normalize_phone_number(phone: str, *, field_name: str = "phone") -> str:
    raw = str(phone or "").strip()
    if not raw:
        raise ValueError(f"{field_name} is required")
    digits = _PHONE_DIGITS_RE.sub("", raw)
    if len(digits) < 10:
        raise ValueError(f"{field_name} must include at least 10 digits")
    if len(digits) == 10:
        digits = f"1{digits}"
    return f"+{digits}"


def normalize_email_address(email: str, *, field_name: str = "email") -> str:
    normalized = str(email or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise ValueError(f"{field_name} must be a valid email address")
    return normalized


def default_sms_bridge_db_path() -> str:
    return os.environ.get(
        "IPFS_DATASETS_SMS_BRIDGE_DB_PATH",
        os.path.join(os.path.expanduser("~"), ".cache", "ipfs_datasets_py", "sms_bridge.duckdb"),
    )


def _perform_request(
    url: str,
    *,
    body: bytes,
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> tuple[int, str, str]:
    status_code, raw, content_type = _perform_request_raw(
        url,
        body=body,
        headers=headers,
        timeout_seconds=timeout_seconds,
    )
    return status_code, raw.decode("utf-8", errors="replace"), content_type


def _perform_request_raw(
    url: str,
    *,
    body: bytes,
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> tuple[int, bytes, str]:
    request = urllib_request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(getattr(response, "status", getattr(response, "code", 200)))
            content_type = str(getattr(response, "headers", {}).get("content-type", ""))
            raw = response.read()
            return status_code, raw, content_type
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail or exc.reason}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"failed to reach {url}: {exc.reason}") from exc


def _parse_response_payload(raw: str, content_type: str) -> dict[str, Any]:
    if not raw:
        return {}
    if "json" not in content_type.lower() and not raw.lstrip().startswith("{"):
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("provider response must be a JSON object")
    return parsed


def _first_string(payload: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _default_voice_media_root() -> str:
    return os.environ.get(
        "IPFS_DATASETS_VOICE_MEDIA_ROOT",
        os.path.join(os.path.dirname(default_sms_bridge_db_path()), "voice_media"),
    )


def _create_silent_wav_bytes(duration_ms: int = 240, sample_rate: int = 16000) -> bytes:
    sample_count = max(1, round((sample_rate * duration_ms) / 1000))
    frames = b"\x00\x00" * sample_count
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frames)
    return buffer.getvalue()


def _encode_multipart_form(
    *,
    fields: Mapping[str, str],
    files: Sequence[tuple[str, str, str, bytes]],
) -> tuple[bytes, str]:
    boundary = f"----ipfsdatasets{uuid.uuid4().hex}"
    body = bytearray()

    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")

    for field_name, filename, content_type, content in files:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("utf-8")
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body.extend(content)
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _resolve_public_base_url(request: Request, configured_base_url: str) -> str:
    normalized = str(configured_base_url or "").strip().rstrip("/")
    if normalized:
        return normalized
    forwarded_proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{forwarded_proto}://{forwarded_host}".rstrip("/")


def _join_public_url(base_url: str, path: str) -> str:
    normalized_base = str(base_url or "").rstrip("/")
    normalized_path = "/" + str(path or "").lstrip("/")
    return f"{normalized_base}{normalized_path}"


def _append_url_path(base_url: str | None, suffix: str) -> str:
    normalized_base = str(base_url or "").strip().rstrip("/")
    normalized_suffix = str(suffix or "").strip().lstrip("/")
    if not normalized_base or not normalized_suffix:
        return ""
    return f"{normalized_base}/{normalized_suffix}"


def _xml_text(value: str) -> str:
    return html.escape(str(value or ""), quote=True)


def _twiml_response(*nodes: str) -> str:
    return "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response>" + "".join(nodes) + "</Response>"


def _twiml_say(text: str) -> str:
    return f"<Say>{_xml_text(text)}</Say>"


def _twiml_play(url: str) -> str:
    return f"<Play>{_xml_text(url)}</Play>"


def _twiml_gather(*, action_url: str, prompt_text: str, language: str = "en-US") -> str:
    return (
        f'<Gather input="speech" action="{_xml_text(action_url)}" method="POST" '
        f'actionOnEmptyResult="true" timeout="6" speechTimeout="auto" language="{_xml_text(language)}">'
        f"{_twiml_say(prompt_text)}"
        "</Gather>"
    )


def _normalize_turn_text(value: str, *, max_length: int = 480) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    return normalized[:max_length]


def _should_hangup_from_text(value: str) -> bool:
    return bool(_VOICE_HANGUP_PATTERNS.search(str(value or "")))


@dataclass(frozen=True)
class SmsMessageRecord:
    message_id: str
    direction: str
    provider: str
    status: str
    provider_message_id: str = ""
    to_phone: str = ""
    from_phone: str = ""
    message: str = ""
    wallet_id: str = ""
    external_reference: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "direction": self.direction,
            "provider": self.provider,
            "status": self.status,
            "provider_message_id": self.provider_message_id,
            "to_phone": self.to_phone,
            "from_phone": self.from_phone,
            "message": self.message,
            "wallet_id": self.wallet_id,
            "external_reference": self.external_reference,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Sequence[Any]) -> "SmsMessageRecord":
        (
            message_id,
            direction,
            provider,
            provider_message_id,
            status,
            to_phone,
            from_phone,
            message_text,
            wallet_id,
            external_reference,
            metadata_json,
            created_at,
            updated_at,
        ) = row
        metadata: dict[str, Any] = {}
        if isinstance(metadata_json, str) and metadata_json:
            parsed = json.loads(metadata_json)
            if isinstance(parsed, dict):
                metadata = parsed
        return cls(
            message_id=str(message_id),
            direction=str(direction),
            provider=str(provider),
            provider_message_id=str(provider_message_id or ""),
            status=str(status),
            to_phone=str(to_phone or ""),
            from_phone=str(from_phone or ""),
            message=str(message_text or ""),
            wallet_id=str(wallet_id or ""),
            external_reference=str(external_reference or ""),
            metadata=metadata,
            created_at=str(created_at or ""),
            updated_at=str(updated_at or ""),
        )


@dataclass(frozen=True)
class EmailDeliveryRecord:
    email_id: str
    provider: str
    status: str
    provider_message_id: str = ""
    to_email: str = ""
    from_email: str = ""
    subject: str = ""
    body: str = ""
    wallet_id: str = ""
    external_reference: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "email_id": self.email_id,
            "provider": self.provider,
            "status": self.status,
            "provider_message_id": self.provider_message_id,
            "to_email": self.to_email,
            "from_email": self.from_email,
            "subject": self.subject,
            "body": self.body,
            "wallet_id": self.wallet_id,
            "external_reference": self.external_reference,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Sequence[Any]) -> "EmailDeliveryRecord":
        (
            email_id,
            provider,
            provider_message_id,
            status,
            to_email,
            from_email,
            subject,
            body,
            wallet_id,
            external_reference,
            metadata_json,
            created_at,
            updated_at,
        ) = row
        metadata: dict[str, Any] = {}
        if isinstance(metadata_json, str) and metadata_json:
            parsed = json.loads(metadata_json)
            if isinstance(parsed, dict):
                metadata = parsed
        return cls(
            email_id=str(email_id),
            provider=str(provider),
            provider_message_id=str(provider_message_id or ""),
            status=str(status),
            to_email=str(to_email or ""),
            from_email=str(from_email or ""),
            subject=str(subject or ""),
            body=str(body or ""),
            wallet_id=str(wallet_id or ""),
            external_reference=str(external_reference or ""),
            metadata=metadata,
            created_at=str(created_at or ""),
            updated_at=str(updated_at or ""),
        )


@dataclass(frozen=True)
class PhoneCallRecord:
    call_id: str
    provider: str
    status: str
    provider_call_id: str = ""
    to_phone: str = ""
    from_phone: str = ""
    script: str = ""
    wallet_id: str = ""
    external_reference: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "provider": self.provider,
            "status": self.status,
            "provider_call_id": self.provider_call_id,
            "to_phone": self.to_phone,
            "from_phone": self.from_phone,
            "script": self.script,
            "wallet_id": self.wallet_id,
            "external_reference": self.external_reference,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Sequence[Any]) -> "PhoneCallRecord":
        (
            call_id,
            provider,
            provider_call_id,
            status,
            to_phone,
            from_phone,
            script,
            wallet_id,
            external_reference,
            metadata_json,
            created_at,
            updated_at,
        ) = row
        metadata: dict[str, Any] = {}
        if isinstance(metadata_json, str) and metadata_json:
            parsed = json.loads(metadata_json)
            if isinstance(parsed, dict):
                metadata = parsed
        return cls(
            call_id=str(call_id),
            provider=str(provider),
            provider_call_id=str(provider_call_id or ""),
            status=str(status),
            to_phone=str(to_phone or ""),
            from_phone=str(from_phone or ""),
            script=str(script or ""),
            wallet_id=str(wallet_id or ""),
            external_reference=str(external_reference or ""),
            metadata=metadata,
            created_at=str(created_at or ""),
            updated_at=str(updated_at or ""),
        )


@dataclass(frozen=True)
class VoiceCallSessionRecord:
    session_id: str
    provider: str
    provider_call_id: str
    status: str
    from_phone: str = ""
    to_phone: str = ""
    assistant_name: str = ""
    service_name: str = ""
    greeting: str = ""
    last_user_text: str = ""
    last_assistant_text: str = ""
    turn_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "provider": self.provider,
            "provider_call_id": self.provider_call_id,
            "status": self.status,
            "from_phone": self.from_phone,
            "to_phone": self.to_phone,
            "assistant_name": self.assistant_name,
            "service_name": self.service_name,
            "greeting": self.greeting,
            "last_user_text": self.last_user_text,
            "last_assistant_text": self.last_assistant_text,
            "turn_count": self.turn_count,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Sequence[Any]) -> "VoiceCallSessionRecord":
        (
            session_id,
            provider,
            provider_call_id,
            status,
            from_phone,
            to_phone,
            assistant_name,
            service_name,
            greeting,
            last_user_text,
            last_assistant_text,
            turn_count,
            metadata_json,
            created_at,
            updated_at,
        ) = row
        metadata: dict[str, Any] = {}
        if isinstance(metadata_json, str) and metadata_json:
            parsed = json.loads(metadata_json)
            if isinstance(parsed, dict):
                metadata = parsed
        return cls(
            session_id=str(session_id),
            provider=str(provider),
            provider_call_id=str(provider_call_id or ""),
            status=str(status),
            from_phone=str(from_phone or ""),
            to_phone=str(to_phone or ""),
            assistant_name=str(assistant_name or ""),
            service_name=str(service_name or ""),
            greeting=str(greeting or ""),
            last_user_text=str(last_user_text or ""),
            last_assistant_text=str(last_assistant_text or ""),
            turn_count=int(turn_count or 0),
            metadata=metadata,
            created_at=str(created_at or ""),
            updated_at=str(updated_at or ""),
        )


@dataclass(frozen=True)
class VoiceCallTurnRecord:
    turn_id: str
    session_id: str
    role: str
    text: str
    audio_asset_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "role": self.role,
            "text": self.text,
            "audio_asset_id": self.audio_asset_id,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: Sequence[Any]) -> "VoiceCallTurnRecord":
        turn_id, session_id, role, text, audio_asset_id, metadata_json, created_at = row
        metadata: dict[str, Any] = {}
        if isinstance(metadata_json, str) and metadata_json:
            parsed = json.loads(metadata_json)
            if isinstance(parsed, dict):
                metadata = parsed
        return cls(
            turn_id=str(turn_id),
            session_id=str(session_id),
            role=str(role),
            text=str(text or ""),
            audio_asset_id=str(audio_asset_id or ""),
            metadata=metadata,
            created_at=str(created_at or ""),
        )


@dataclass(frozen=True)
class VoiceAssistantProfile:
    assistant_name: str = "Abby"
    service_name: str = "211 AI"
    greeting: str = _DEFAULT_VOICE_GREETING
    no_speech_prompt: str = _DEFAULT_VOICE_NO_SPEECH_PROMPT
    follow_up_prompt: str = _DEFAULT_VOICE_FOLLOW_UP
    farewell: str = _DEFAULT_VOICE_FAREWELL
    unavailable_prompt: str = _DEFAULT_VOICE_UNAVAILABLE_PROMPT
    website_url: str = "https://211-ai.com"
    system_prompt_append: str = ""
    max_turns: int = 8

    def build_reply_prompt(
        self,
        *,
        transcript: str,
        session: VoiceCallSessionRecord,
        turns: Sequence[VoiceCallTurnRecord],
    ) -> dict[str, str]:
        normalized_transcript = _normalize_turn_text(transcript, max_length=480) or "The caller asked for help."
        recent_turns = [turn for turn in turns if turn.role in {"caller", "assistant"}][-6:]
        history_lines = []
        for turn in recent_turns:
            prefix = "Caller" if turn.role == "caller" else "Assistant"
            history_lines.append(f"{prefix}: {_normalize_turn_text(turn.text, max_length=280)}")
        history_block = "\n".join(history_lines) if history_lines else "Caller has just joined the call."
        system_lines = [
            f"You are {self.assistant_name}, a helpful and empathetic voice assistant for {self.service_name}.",
            "Help callers navigate shelter, food, health, benefits, crisis support, transportation, and other 211-style social services.",
            "Answer in natural spoken language and keep each response concise, specific, and under 70 words unless the caller explicitly asks for more detail.",
            "Do not read URLs, JSON, raw identifiers, citation IDs, or internal metadata aloud.",
            "Ask one short clarifying question when the caller's need is ambiguous or missing location, timing, or household details.",
            "If the service is uncertain, say what you need to know next instead of inventing facts.",
            f"Website reference: {self.website_url}",
        ]
        if self.system_prompt_append.strip():
            system_lines.append(self.system_prompt_append.strip())
        system_lines.extend(["Conversation so far:", history_block])
        system_prompt = "\n".join(system_lines)
        user_prompt = normalized_transcript
        full_prompt = "\n\n".join([system_prompt, f"Caller request: {normalized_transcript}"])
        fallback_text = (
            f"{self.assistant_name} here. I heard: {normalized_transcript}. "
            "I can help with shelter, food, health, benefits, and other local services."
        )
        return {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "full_prompt": full_prompt,
            "fallback_text": fallback_text,
        }


@dataclass(frozen=True)
class VoiceReplyResult:
    provider: str
    model_name: str
    text: str = ""
    audio_bytes: bytes = b""
    mime_type: str = ""


class SmsBridgeStore:
    """Short-lived DuckDB repository for outbound telephony records."""

    def __init__(self, path: str | None = None):
        self.path = path or default_sms_bridge_db_path()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._init_db()

    def _connect(self):
        try:
            import duckdb  # type: ignore
        except Exception as exc:  # pragma: no cover - import failure
            raise RuntimeError("duckdb is required for the SMS bridge") from exc
        return duckdb.connect(self.path)

    def _init_db(self) -> None:
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sms_messages (
                    message_id VARCHAR PRIMARY KEY,
                    direction VARCHAR NOT NULL,
                    provider VARCHAR NOT NULL,
                    provider_message_id VARCHAR,
                    status VARCHAR NOT NULL,
                    to_phone VARCHAR,
                    from_phone VARCHAR,
                    message_text VARCHAR NOT NULL,
                    wallet_id VARCHAR,
                    external_reference VARCHAR,
                    metadata_json VARCHAR NOT NULL,
                    created_at VARCHAR NOT NULL,
                    updated_at VARCHAR NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_sms_messages_direction_status ON sms_messages(direction, status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_sms_messages_created_at ON sms_messages(created_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_sms_messages_provider_message_id ON sms_messages(provider_message_id)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS email_messages (
                    email_id VARCHAR PRIMARY KEY,
                    provider VARCHAR NOT NULL,
                    provider_message_id VARCHAR,
                    status VARCHAR NOT NULL,
                    to_email VARCHAR NOT NULL,
                    from_email VARCHAR,
                    subject VARCHAR NOT NULL,
                    body VARCHAR NOT NULL,
                    wallet_id VARCHAR,
                    external_reference VARCHAR,
                    metadata_json VARCHAR NOT NULL,
                    created_at VARCHAR NOT NULL,
                    updated_at VARCHAR NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_email_messages_status ON email_messages(status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_email_messages_provider_message_id ON email_messages(provider_message_id)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS phone_calls (
                    call_id VARCHAR PRIMARY KEY,
                    provider VARCHAR NOT NULL,
                    provider_call_id VARCHAR,
                    status VARCHAR NOT NULL,
                    to_phone VARCHAR NOT NULL,
                    from_phone VARCHAR,
                    script VARCHAR NOT NULL,
                    wallet_id VARCHAR,
                    external_reference VARCHAR,
                    metadata_json VARCHAR NOT NULL,
                    created_at VARCHAR NOT NULL,
                    updated_at VARCHAR NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_phone_calls_status ON phone_calls(status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_phone_calls_provider_call_id ON phone_calls(provider_call_id)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_call_sessions (
                    session_id VARCHAR PRIMARY KEY,
                    provider VARCHAR NOT NULL,
                    provider_call_id VARCHAR,
                    status VARCHAR NOT NULL,
                    from_phone VARCHAR,
                    to_phone VARCHAR,
                    assistant_name VARCHAR,
                    service_name VARCHAR,
                    greeting VARCHAR,
                    last_user_text VARCHAR,
                    last_assistant_text VARCHAR,
                    turn_count INTEGER NOT NULL,
                    metadata_json VARCHAR NOT NULL,
                    created_at VARCHAR NOT NULL,
                    updated_at VARCHAR NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_voice_call_sessions_provider_call_id ON voice_call_sessions(provider_call_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_voice_call_sessions_status ON voice_call_sessions(status)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_call_turns (
                    turn_id VARCHAR PRIMARY KEY,
                    session_id VARCHAR NOT NULL,
                    role VARCHAR NOT NULL,
                    text VARCHAR NOT NULL,
                    audio_asset_id VARCHAR,
                    metadata_json VARCHAR NOT NULL,
                    created_at VARCHAR NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_voice_call_turns_session_created ON voice_call_turns(session_id, created_at)"
            )
        finally:
            connection.close()

    def _insert_message(
        self,
        *,
        direction: str,
        provider: str,
        status: str,
        to_phone: str,
        from_phone: str,
        message: str,
        provider_message_id: str = "",
        wallet_id: str = "",
        external_reference: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> SmsMessageRecord:
        normalized_message = str(message or "")
        if not normalized_message.strip():
            raise ValueError("message is required")
        timestamp = _utcnow_iso()
        record = SmsMessageRecord(
            message_id=f"sms-{uuid.uuid4().hex}",
            direction=str(direction),
            provider=str(provider or "unknown"),
            status=str(status or "queued"),
            provider_message_id=str(provider_message_id or ""),
            to_phone=str(to_phone or ""),
            from_phone=str(from_phone or ""),
            message=normalized_message,
            wallet_id=str(wallet_id or ""),
            external_reference=str(external_reference or ""),
            metadata=_coerce_metadata(metadata),
            created_at=timestamp,
            updated_at=timestamp,
        )

        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO sms_messages(
                    message_id,
                    direction,
                    provider,
                    provider_message_id,
                    status,
                    to_phone,
                    from_phone,
                    message_text,
                    wallet_id,
                    external_reference,
                    metadata_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.message_id,
                    record.direction,
                    record.provider,
                    record.provider_message_id,
                    record.status,
                    record.to_phone,
                    record.from_phone,
                    record.message,
                    record.wallet_id,
                    record.external_reference,
                    _json_dumps(record.metadata),
                    record.created_at,
                    record.updated_at,
                ),
            )
        finally:
            connection.close()
        return record

    def record_outbound(
        self,
        *,
        provider: str,
        status: str,
        to_phone: str,
        message: str,
        provider_message_id: str = "",
        from_phone: str = "",
        wallet_id: str = "",
        external_reference: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> SmsMessageRecord:
        normalized_to_phone = normalize_phone_number(to_phone, field_name="to_phone")
        normalized_from_phone = normalize_phone_number(from_phone, field_name="from_phone") if from_phone else ""
        return self._insert_message(
            direction="outbound",
            provider=provider,
            status=status,
            to_phone=normalized_to_phone,
            from_phone=normalized_from_phone,
            message=message,
            provider_message_id=provider_message_id,
            wallet_id=wallet_id,
            external_reference=external_reference,
            metadata=metadata,
        )

    def record_inbound(
        self,
        *,
        provider: str,
        from_phone: str,
        message: str,
        to_phone: str = "",
        provider_message_id: str = "",
        wallet_id: str = "",
        external_reference: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> SmsMessageRecord:
        normalized_from_phone = normalize_phone_number(from_phone, field_name="from_phone")
        normalized_to_phone = normalize_phone_number(to_phone, field_name="to_phone") if to_phone else ""
        resolved_wallet_id = str(wallet_id or "").strip()
        resolved_external_reference = str(external_reference or "").strip()
        resolved_metadata = _coerce_metadata(metadata)

        if not resolved_wallet_id or not resolved_external_reference:
            correlated_outbound = self.find_recent_outbound_for_reply(
                reply_from_phone=normalized_from_phone,
                service_phone=normalized_to_phone,
            )
            if correlated_outbound is not None:
                resolved_wallet_id = resolved_wallet_id or correlated_outbound.wallet_id
                resolved_external_reference = resolved_external_reference or correlated_outbound.external_reference
                if correlated_outbound.message_id and "reply_to_message_id" not in resolved_metadata:
                    resolved_metadata["reply_to_message_id"] = correlated_outbound.message_id
                if (
                    correlated_outbound.provider_message_id
                    and "reply_to_provider_message_id" not in resolved_metadata
                ):
                    resolved_metadata["reply_to_provider_message_id"] = correlated_outbound.provider_message_id
        return self._insert_message(
            direction="inbound",
            provider=provider,
            status="received",
            to_phone=normalized_to_phone,
            from_phone=normalized_from_phone,
            message=message,
            provider_message_id=provider_message_id,
            wallet_id=resolved_wallet_id,
            external_reference=resolved_external_reference,
            metadata=resolved_metadata,
        )

    def find_recent_outbound_for_reply(
        self,
        *,
        reply_from_phone: str,
        service_phone: str = "",
    ) -> SmsMessageRecord | None:
        normalized_reply_phone = normalize_phone_number(reply_from_phone, field_name="from_phone")
        normalized_service_phone = normalize_phone_number(service_phone, field_name="to_phone") if service_phone else ""
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT message_id, direction, provider, provider_message_id, status, to_phone, from_phone,
                       message_text, wallet_id, external_reference, metadata_json, created_at, updated_at
                FROM sms_messages
                WHERE direction = 'outbound' AND to_phone = ? AND wallet_id <> ''
                ORDER BY updated_at DESC, created_at DESC, message_id DESC
                LIMIT 25
                """,
                (normalized_reply_phone,),
            ).fetchall()
        finally:
            connection.close()

        first_match: SmsMessageRecord | None = None
        blank_from_phone_match: SmsMessageRecord | None = None
        for row in rows:
            record = SmsMessageRecord.from_row(row)
            if first_match is None:
                first_match = record
            if normalized_service_phone and record.from_phone == normalized_service_phone:
                return record
            if not record.from_phone and blank_from_phone_match is None:
                blank_from_phone_match = record
        return blank_from_phone_match or first_match

    def update_status_by_provider_message_id(
        self,
        *,
        provider_message_id: str,
        status: str,
        metadata_update: Mapping[str, Any] | None = None,
    ) -> SmsMessageRecord | None:
        normalized_provider_message_id = str(provider_message_id or "").strip()
        if not normalized_provider_message_id:
            raise ValueError("provider_message_id is required")
        normalized_status = str(status or "").strip()
        if not normalized_status:
            raise ValueError("status is required")

        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT
                    message_id,
                    direction,
                    provider,
                    provider_message_id,
                    status,
                    to_phone,
                    from_phone,
                    message_text,
                    wallet_id,
                    external_reference,
                    metadata_json,
                    created_at,
                    updated_at
                FROM sms_messages
                WHERE provider_message_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (normalized_provider_message_id,),
            ).fetchone()
            if row is None:
                return None

            current_record = SmsMessageRecord.from_row(row)
            merged_metadata = dict(current_record.metadata)
            merged_metadata.update(_coerce_metadata(metadata_update))
            updated_at = _utcnow_iso()
            connection.execute(
                """
                UPDATE sms_messages
                SET status = ?, metadata_json = ?, updated_at = ?
                WHERE message_id = ?
                """,
                (
                    normalized_status,
                    _json_dumps(merged_metadata),
                    updated_at,
                    current_record.message_id,
                ),
            )
            return SmsMessageRecord(
                message_id=current_record.message_id,
                direction=current_record.direction,
                provider=current_record.provider,
                status=normalized_status,
                provider_message_id=current_record.provider_message_id,
                to_phone=current_record.to_phone,
                from_phone=current_record.from_phone,
                message=current_record.message,
                wallet_id=current_record.wallet_id,
                external_reference=current_record.external_reference,
                metadata=merged_metadata,
                created_at=current_record.created_at,
                updated_at=updated_at,
            )
        finally:
            connection.close()

    def list_messages(
        self,
        *,
        limit: int = 100,
        direction: str = "",
        provider: str = "",
        status: str = "",
        phone: str = "",
    ) -> list[SmsMessageRecord]:
        normalized_limit = max(1, min(int(limit), 500))
        filters: list[str] = []
        params: list[Any] = []
        if direction:
            filters.append("direction = ?")
            params.append(str(direction))
        if provider:
            filters.append("provider = ?")
            params.append(str(provider))
        if status:
            filters.append("status = ?")
            params.append(str(status))
        if phone:
            normalized_phone = normalize_phone_number(phone, field_name="phone")
            filters.append("(to_phone = ? OR from_phone = ?)")
            params.extend([normalized_phone, normalized_phone])

        sql = (
            "SELECT "
            "message_id, direction, provider, provider_message_id, status, to_phone, from_phone, "
            "message_text, wallet_id, external_reference, metadata_json, created_at, updated_at "
            "FROM sms_messages"
        )
        if filters:
            sql = f"{sql} WHERE {' AND '.join(filters)}"
        sql = f"{sql} ORDER BY created_at DESC, message_id DESC LIMIT ?"
        params.append(normalized_limit)

        connection = self._connect()
        try:
            rows = connection.execute(sql, tuple(params)).fetchall()
        finally:
            connection.close()
        return [SmsMessageRecord.from_row(row) for row in rows]

    def record_outbound_email(
        self,
        *,
        provider: str,
        status: str,
        to_email: str,
        subject: str,
        body: str,
        provider_message_id: str = "",
        from_email: str = "",
        wallet_id: str = "",
        external_reference: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> EmailDeliveryRecord:
        normalized_to_email = normalize_email_address(to_email, field_name="to_email")
        normalized_from_email = normalize_email_address(from_email, field_name="from_email") if from_email else ""
        normalized_subject = str(subject or "").strip()
        normalized_body = str(body or "")
        if not normalized_subject:
            raise ValueError("subject is required")
        if not normalized_body.strip():
            raise ValueError("body is required")
        timestamp = _utcnow_iso()
        record = EmailDeliveryRecord(
            email_id=f"email-{uuid.uuid4().hex}",
            provider=str(provider or "unknown"),
            provider_message_id=str(provider_message_id or ""),
            status=str(status or "queued"),
            to_email=normalized_to_email,
            from_email=normalized_from_email,
            subject=normalized_subject,
            body=normalized_body,
            wallet_id=str(wallet_id or ""),
            external_reference=str(external_reference or ""),
            metadata=_coerce_metadata(metadata),
            created_at=timestamp,
            updated_at=timestamp,
        )

        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO email_messages(
                    email_id,
                    provider,
                    provider_message_id,
                    status,
                    to_email,
                    from_email,
                    subject,
                    body,
                    wallet_id,
                    external_reference,
                    metadata_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.email_id,
                    record.provider,
                    record.provider_message_id,
                    record.status,
                    record.to_email,
                    record.from_email,
                    record.subject,
                    record.body,
                    record.wallet_id,
                    record.external_reference,
                    _json_dumps(record.metadata),
                    record.created_at,
                    record.updated_at,
                ),
            )
        finally:
            connection.close()
        return record

    def list_email_messages(
        self,
        *,
        limit: int = 100,
        provider: str = "",
        status: str = "",
        to_email: str = "",
    ) -> list[EmailDeliveryRecord]:
        normalized_limit = max(1, min(int(limit), 500))
        filters: list[str] = []
        params: list[Any] = []
        if provider:
            filters.append("provider = ?")
            params.append(str(provider))
        if status:
            filters.append("status = ?")
            params.append(str(status))
        if to_email:
            filters.append("to_email = ?")
            params.append(normalize_email_address(to_email, field_name="to_email"))

        sql = (
            "SELECT "
            "email_id, provider, provider_message_id, status, to_email, from_email, subject, body, "
            "wallet_id, external_reference, metadata_json, created_at, updated_at "
            "FROM email_messages"
        )
        if filters:
            sql = f"{sql} WHERE {' AND '.join(filters)}"
        sql = f"{sql} ORDER BY created_at DESC, email_id DESC LIMIT ?"
        params.append(normalized_limit)

        connection = self._connect()
        try:
            rows = connection.execute(sql, tuple(params)).fetchall()
        finally:
            connection.close()
        return [EmailDeliveryRecord.from_row(row) for row in rows]

    def _insert_call(
        self,
        *,
        provider: str,
        status: str,
        to_phone: str,
        script: str,
        provider_call_id: str = "",
        from_phone: str = "",
        wallet_id: str = "",
        external_reference: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> PhoneCallRecord:
        normalized_script = str(script or "")
        if not normalized_script.strip():
            raise ValueError("script is required")
        timestamp = _utcnow_iso()
        record = PhoneCallRecord(
            call_id=f"call-{uuid.uuid4().hex}",
            provider=str(provider or "unknown"),
            provider_call_id=str(provider_call_id or ""),
            status=str(status or "queued"),
            to_phone=str(to_phone or ""),
            from_phone=str(from_phone or ""),
            script=normalized_script,
            wallet_id=str(wallet_id or ""),
            external_reference=str(external_reference or ""),
            metadata=_coerce_metadata(metadata),
            created_at=timestamp,
            updated_at=timestamp,
        )

        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO phone_calls(
                    call_id,
                    provider,
                    provider_call_id,
                    status,
                    to_phone,
                    from_phone,
                    script,
                    wallet_id,
                    external_reference,
                    metadata_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.call_id,
                    record.provider,
                    record.provider_call_id,
                    record.status,
                    record.to_phone,
                    record.from_phone,
                    record.script,
                    record.wallet_id,
                    record.external_reference,
                    _json_dumps(record.metadata),
                    record.created_at,
                    record.updated_at,
                ),
            )
        finally:
            connection.close()
        return record

    def record_outbound_call(
        self,
        *,
        provider: str,
        status: str,
        to_phone: str,
        script: str,
        provider_call_id: str = "",
        from_phone: str = "",
        wallet_id: str = "",
        external_reference: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> PhoneCallRecord:
        normalized_to_phone = normalize_phone_number(to_phone, field_name="to_phone")
        normalized_from_phone = normalize_phone_number(from_phone, field_name="from_phone") if from_phone else ""
        return self._insert_call(
            provider=provider,
            status=status,
            to_phone=normalized_to_phone,
            from_phone=normalized_from_phone,
            script=script,
            provider_call_id=provider_call_id,
            wallet_id=wallet_id,
            external_reference=external_reference,
            metadata=metadata,
        )

    def update_call_status_by_provider_call_id(
        self,
        *,
        provider_call_id: str,
        status: str,
        metadata_update: Mapping[str, Any] | None = None,
    ) -> PhoneCallRecord | None:
        normalized_provider_call_id = str(provider_call_id or "").strip()
        if not normalized_provider_call_id:
            raise ValueError("provider_call_id is required")
        normalized_status = str(status or "").strip()
        if not normalized_status:
            raise ValueError("status is required")

        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT
                    call_id,
                    provider,
                    provider_call_id,
                    status,
                    to_phone,
                    from_phone,
                    script,
                    wallet_id,
                    external_reference,
                    metadata_json,
                    created_at,
                    updated_at
                FROM phone_calls
                WHERE provider_call_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (normalized_provider_call_id,),
            ).fetchone()
            if row is None:
                return None

            current_record = PhoneCallRecord.from_row(row)
            merged_metadata = dict(current_record.metadata)
            merged_metadata.update(_coerce_metadata(metadata_update))
            updated_at = _utcnow_iso()
            connection.execute(
                """
                UPDATE phone_calls
                SET status = ?, metadata_json = ?, updated_at = ?
                WHERE call_id = ?
                """,
                (
                    normalized_status,
                    _json_dumps(merged_metadata),
                    updated_at,
                    current_record.call_id,
                ),
            )
            return PhoneCallRecord(
                call_id=current_record.call_id,
                provider=current_record.provider,
                provider_call_id=current_record.provider_call_id,
                status=normalized_status,
                to_phone=current_record.to_phone,
                from_phone=current_record.from_phone,
                script=current_record.script,
                wallet_id=current_record.wallet_id,
                external_reference=current_record.external_reference,
                metadata=merged_metadata,
                created_at=current_record.created_at,
                updated_at=updated_at,
            )
        finally:
            connection.close()

    def list_calls(
        self,
        *,
        limit: int = 100,
        provider: str = "",
        status: str = "",
        phone: str = "",
    ) -> list[PhoneCallRecord]:
        normalized_limit = max(1, min(int(limit), 500))
        filters: list[str] = []
        params: list[Any] = []
        if provider:
            filters.append("provider = ?")
            params.append(str(provider))
        if status:
            filters.append("status = ?")
            params.append(str(status))
        if phone:
            normalized_phone = normalize_phone_number(phone, field_name="phone")
            filters.append("(to_phone = ? OR from_phone = ?)")
            params.extend([normalized_phone, normalized_phone])

        sql = (
            "SELECT "
            "call_id, provider, provider_call_id, status, to_phone, from_phone, script, "
            "wallet_id, external_reference, metadata_json, created_at, updated_at "
            "FROM phone_calls"
        )
        if filters:
            sql = f"{sql} WHERE {' AND '.join(filters)}"
        sql = f"{sql} ORDER BY created_at DESC, call_id DESC LIMIT ?"
        params.append(normalized_limit)

        connection = self._connect()
        try:
            rows = connection.execute(sql, tuple(params)).fetchall()
        finally:
            connection.close()
        return [PhoneCallRecord.from_row(row) for row in rows]

    def create_voice_session(
        self,
        *,
        provider: str,
        provider_call_id: str,
        from_phone: str,
        to_phone: str,
        assistant_name: str,
        service_name: str,
        greeting: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> VoiceCallSessionRecord:
        normalized_from_phone = normalize_phone_number(from_phone, field_name="from_phone") if from_phone else ""
        normalized_to_phone = normalize_phone_number(to_phone, field_name="to_phone") if to_phone else ""
        timestamp = _utcnow_iso()
        record = VoiceCallSessionRecord(
            session_id=f"voice-{uuid.uuid4().hex}",
            provider=str(provider or "unknown"),
            provider_call_id=str(provider_call_id or ""),
            status="active",
            from_phone=normalized_from_phone,
            to_phone=normalized_to_phone,
            assistant_name=str(assistant_name or ""),
            service_name=str(service_name or ""),
            greeting=str(greeting or ""),
            last_user_text="",
            last_assistant_text="",
            turn_count=0,
            metadata=_coerce_metadata(metadata),
            created_at=timestamp,
            updated_at=timestamp,
        )
        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO voice_call_sessions(
                    session_id,
                    provider,
                    provider_call_id,
                    status,
                    from_phone,
                    to_phone,
                    assistant_name,
                    service_name,
                    greeting,
                    last_user_text,
                    last_assistant_text,
                    turn_count,
                    metadata_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.session_id,
                    record.provider,
                    record.provider_call_id,
                    record.status,
                    record.from_phone,
                    record.to_phone,
                    record.assistant_name,
                    record.service_name,
                    record.greeting,
                    record.last_user_text,
                    record.last_assistant_text,
                    record.turn_count,
                    _json_dumps(record.metadata),
                    record.created_at,
                    record.updated_at,
                ),
            )
        finally:
            connection.close()
        return record

    def get_voice_session(self, session_id: str) -> VoiceCallSessionRecord | None:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return None
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT
                    session_id,
                    provider,
                    provider_call_id,
                    status,
                    from_phone,
                    to_phone,
                    assistant_name,
                    service_name,
                    greeting,
                    last_user_text,
                    last_assistant_text,
                    turn_count,
                    metadata_json,
                    created_at,
                    updated_at
                FROM voice_call_sessions
                WHERE session_id = ?
                LIMIT 1
                """,
                (normalized_session_id,),
            ).fetchone()
        finally:
            connection.close()
        return VoiceCallSessionRecord.from_row(row) if row is not None else None

    def get_voice_session_by_provider_call_id(self, provider_call_id: str) -> VoiceCallSessionRecord | None:
        normalized_provider_call_id = str(provider_call_id or "").strip()
        if not normalized_provider_call_id:
            return None
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT
                    session_id,
                    provider,
                    provider_call_id,
                    status,
                    from_phone,
                    to_phone,
                    assistant_name,
                    service_name,
                    greeting,
                    last_user_text,
                    last_assistant_text,
                    turn_count,
                    metadata_json,
                    created_at,
                    updated_at
                FROM voice_call_sessions
                WHERE provider_call_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (normalized_provider_call_id,),
            ).fetchone()
        finally:
            connection.close()
        return VoiceCallSessionRecord.from_row(row) if row is not None else None

    def append_voice_turn(
        self,
        session_id: str,
        *,
        role: str,
        text: str,
        audio_asset_id: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> VoiceCallTurnRecord:
        current_session = self.get_voice_session(session_id)
        if current_session is None:
            raise ValueError("voice session not found")
        normalized_text = _normalize_turn_text(text, max_length=1200)
        if not normalized_text:
            raise ValueError("text is required")
        timestamp = _utcnow_iso()
        record = VoiceCallTurnRecord(
            turn_id=f"voice-turn-{uuid.uuid4().hex}",
            session_id=current_session.session_id,
            role=str(role or "assistant"),
            text=normalized_text,
            audio_asset_id=str(audio_asset_id or ""),
            metadata=_coerce_metadata(metadata),
            created_at=timestamp,
        )
        turn_count = int(current_session.turn_count or 0)
        if record.role in {"caller", "assistant"}:
            turn_count += 1
        last_user_text = current_session.last_user_text
        last_assistant_text = current_session.last_assistant_text
        if record.role == "caller":
            last_user_text = record.text
        elif record.role == "assistant":
            last_assistant_text = record.text

        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO voice_call_turns(turn_id, session_id, role, text, audio_asset_id, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.turn_id,
                    record.session_id,
                    record.role,
                    record.text,
                    record.audio_asset_id,
                    _json_dumps(record.metadata),
                    record.created_at,
                ),
            )
            connection.execute(
                """
                UPDATE voice_call_sessions
                SET last_user_text = ?, last_assistant_text = ?, turn_count = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    last_user_text,
                    last_assistant_text,
                    turn_count,
                    timestamp,
                    current_session.session_id,
                ),
            )
        finally:
            connection.close()
        return record

    def list_voice_turns(self, session_id: str) -> list[VoiceCallTurnRecord]:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return []
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT turn_id, session_id, role, text, audio_asset_id, metadata_json, created_at
                FROM voice_call_turns
                WHERE session_id = ?
                ORDER BY created_at ASC, turn_id ASC
                """,
                (normalized_session_id,),
            ).fetchall()
        finally:
            connection.close()
        return [VoiceCallTurnRecord.from_row(row) for row in rows]

    def update_voice_session_status(
        self,
        session_id: str,
        *,
        status: str,
        metadata_update: Mapping[str, Any] | None = None,
    ) -> VoiceCallSessionRecord | None:
        current_session = self.get_voice_session(session_id)
        if current_session is None:
            return None
        normalized_status = str(status or "").strip()
        if not normalized_status:
            raise ValueError("status is required")
        updated_at = _utcnow_iso()
        merged_metadata = dict(current_session.metadata)
        merged_metadata.update(_coerce_metadata(metadata_update))
        connection = self._connect()
        try:
            connection.execute(
                """
                UPDATE voice_call_sessions
                SET status = ?, metadata_json = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (normalized_status, _json_dumps(merged_metadata), updated_at, current_session.session_id),
            )
        finally:
            connection.close()
        return VoiceCallSessionRecord(
            session_id=current_session.session_id,
            provider=current_session.provider,
            provider_call_id=current_session.provider_call_id,
            status=normalized_status,
            from_phone=current_session.from_phone,
            to_phone=current_session.to_phone,
            assistant_name=current_session.assistant_name,
            service_name=current_session.service_name,
            greeting=current_session.greeting,
            last_user_text=current_session.last_user_text,
            last_assistant_text=current_session.last_assistant_text,
            turn_count=current_session.turn_count,
            metadata=merged_metadata,
            created_at=current_session.created_at,
            updated_at=updated_at,
        )

    def update_voice_session_status_by_provider_call_id(
        self,
        *,
        provider_call_id: str,
        status: str,
        metadata_update: Mapping[str, Any] | None = None,
    ) -> VoiceCallSessionRecord | None:
        current_session = self.get_voice_session_by_provider_call_id(provider_call_id)
        if current_session is None:
            return None
        return self.update_voice_session_status(
            current_session.session_id,
            status=status,
            metadata_update=metadata_update,
        )


class SmsDeliveryProvider(Protocol):
    provider_name: str

    def send_sms(
        self,
        *,
        to_phone: str,
        message: str,
        from_phone: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class EmailDeliveryProvider(Protocol):
    provider_name: str

    def send_email(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        from_email: str = "",
        attachment_base64: str = "",
        attachment_filename: str = "",
        attachment_mime_type: str = "application/octet-stream",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class CallDeliveryProvider(Protocol):
    provider_name: str

    def send_call(
        self,
        *,
        to_phone: str,
        script: str,
        from_phone: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class VoiceReplyProvider(Protocol):
    provider_name: str

    def generate_reply(
        self,
        *,
        transcript: str,
        session: VoiceCallSessionRecord,
        turns: Sequence[VoiceCallTurnRecord],
    ) -> VoiceReplyResult: ...


class MockSmsProvider:
    """Deterministic local SMS provider for development without external APIs."""

    provider_name = "mock"

    def __init__(self, *, from_phone: str = "", provider_name: str = "mock"):
        self.from_phone = normalize_phone_number(from_phone, field_name="from_phone") if from_phone else ""
        self.provider_name = str(provider_name or "mock")

    def send_sms(
        self,
        *,
        to_phone: str,
        message: str,
        from_phone: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalize_phone_number(to_phone, field_name="to_phone")
        resolved_message = str(message or "")
        if not resolved_message.strip():
            raise ValueError("message is required")
        if from_phone:
            normalize_phone_number(from_phone, field_name="from_phone")
        _coerce_metadata(metadata)
        return {
            "provider": self.provider_name,
            "provider_status": "queued",
            "provider_message_id": f"mock-sms-{uuid.uuid4().hex}",
        }


class MockEmailProvider:
    """Deterministic local email provider for development without SMTP or webhooks."""

    provider_name = "mock"

    def __init__(self, *, from_email: str = "", provider_name: str = "mock"):
        self.from_email = normalize_email_address(from_email, field_name="from_email") if from_email else ""
        self.provider_name = str(provider_name or "mock")

    def send_email(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        from_email: str = "",
        attachment_base64: str = "",
        attachment_filename: str = "",
        attachment_mime_type: str = "application/octet-stream",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalize_email_address(to_email, field_name="to_email")
        if from_email:
            normalize_email_address(from_email, field_name="from_email")
        if not str(subject or "").strip():
            raise ValueError("subject is required")
        if not str(body or "").strip():
            raise ValueError("body is required")
        if attachment_base64:
            base64.b64decode(str(attachment_base64).split(",")[-1], validate=True)
        str(attachment_filename or "").strip()
        str(attachment_mime_type or "application/octet-stream").strip()
        _coerce_metadata(metadata)
        return {
            "provider": self.provider_name,
            "provider_status": "queued",
            "provider_message_id": f"mock-email-{uuid.uuid4().hex}",
        }


class MockCallProvider:
    """Deterministic local call provider for development without telephony APIs."""

    provider_name = "mock"

    def __init__(self, *, from_phone: str = "", provider_name: str = "mock"):
        self.from_phone = normalize_phone_number(from_phone, field_name="from_phone") if from_phone else ""
        self.provider_name = str(provider_name or "mock")

    def send_call(
        self,
        *,
        to_phone: str,
        script: str,
        from_phone: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalize_phone_number(to_phone, field_name="to_phone")
        resolved_script = str(script or "")
        if not resolved_script.strip():
            raise ValueError("script is required")
        if from_phone:
            normalize_phone_number(from_phone, field_name="from_phone")
        _coerce_metadata(metadata)
        return {
            "provider": self.provider_name,
            "provider_status": "queued",
            "provider_call_id": f"mock-call-{uuid.uuid4().hex}",
        }


class MockVoiceReplyProvider:
    """Deterministic local voice reply provider for development without model APIs."""

    provider_name = "mock-voice"

    def __init__(
        self,
        *,
        reply_text: str = "",
        assistant_profile: VoiceAssistantProfile | None = None,
        provider_name: str = "mock-voice",
    ):
        self.provider_name = str(provider_name or "mock-voice")
        self.reply_text = str(reply_text or "").strip()
        self.assistant_profile = assistant_profile or VoiceAssistantProfile()

    def generate_reply(
        self,
        *,
        transcript: str,
        session: VoiceCallSessionRecord,
        turns: Sequence[VoiceCallTurnRecord],
    ) -> VoiceReplyResult:
        normalized_transcript = _normalize_turn_text(transcript, max_length=120)
        prompt_text = self.reply_text or (
            f"This is a local mock reply from {self.assistant_profile.assistant_name}. "
            f"I heard: {normalized_transcript or 'silence'}. "
            "Configure a real voice backend when provider credentials are ready."
        )
        return VoiceReplyResult(
            provider=self.provider_name,
            model_name=self.provider_name,
            text=prompt_text,
        )


class WebhookSmsProvider:
    """POST JSON to an outbound SMS worker or provider-specific adapter."""

    provider_name = "webhook"

    def __init__(
        self,
        *,
        webhook_url: str,
        bearer_token: str = "",
        header_name: str = "",
        header_value: str = "",
        timeout_seconds: float = 15.0,
        provider_name: str = "webhook",
    ):
        self.webhook_url = str(webhook_url or "").strip()
        if not self.webhook_url:
            raise ValueError("webhook_url is required")
        self.bearer_token = str(bearer_token or "").strip()
        self.header_name = str(header_name or "").strip()
        self.header_value = str(header_value or "").strip()
        if self.header_name and not self.header_value:
            raise ValueError("header_value is required when header_name is set")
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.provider_name = str(provider_name or "webhook")

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.bearer_token:
            headers["authorization"] = f"Bearer {self.bearer_token}"
        if self.header_name:
            headers[self.header_name] = self.header_value
        return headers

    def send_sms(
        self,
        *,
        to_phone: str,
        message: str,
        from_phone: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "to_phone": normalize_phone_number(to_phone, field_name="to_phone"),
            "message": str(message or ""),
        }
        if from_phone:
            payload["from_phone"] = normalize_phone_number(from_phone, field_name="from_phone")
        if metadata:
            payload["metadata"] = _coerce_metadata(metadata)

        status_code, raw, content_type = _perform_request(
            self.webhook_url,
            body=json.dumps(payload, sort_keys=True).encode("utf-8"),
            headers=self._headers(),
            timeout_seconds=self.timeout_seconds,
        )
        response_payload = _parse_response_payload(raw, content_type)
        provider_message_id = str(
            response_payload.get("message_id")
            or response_payload.get("provider_message_id")
            or response_payload.get("sid")
            or response_payload.get("id")
            or ""
        )
        return {
            "provider": str(response_payload.get("provider") or self.provider_name),
            "provider_status": str(response_payload.get("status") or status_code),
            "provider_message_id": provider_message_id,
        }


class WebhookEmailProvider:
    """POST JSON to an outbound email worker or provider-specific adapter."""

    provider_name = "webhook"

    def __init__(
        self,
        *,
        webhook_url: str,
        bearer_token: str = "",
        header_name: str = "",
        header_value: str = "",
        timeout_seconds: float = 20.0,
        provider_name: str = "webhook",
    ):
        self.webhook_url = str(webhook_url or "").strip()
        if not self.webhook_url:
            raise ValueError("webhook_url is required")
        self.bearer_token = str(bearer_token or "").strip()
        self.header_name = str(header_name or "").strip()
        self.header_value = str(header_value or "").strip()
        if self.header_name and not self.header_value:
            raise ValueError("header_value is required when header_name is set")
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.provider_name = str(provider_name or "webhook")

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.bearer_token:
            headers["authorization"] = f"Bearer {self.bearer_token}"
        if self.header_name:
            headers[self.header_name] = self.header_value
        return headers

    def send_email(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        from_email: str = "",
        attachment_base64: str = "",
        attachment_filename: str = "",
        attachment_mime_type: str = "application/octet-stream",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "to_email": normalize_email_address(to_email, field_name="to_email"),
            "subject": str(subject or "").strip(),
            "body": str(body or ""),
        }
        if not payload["subject"]:
            raise ValueError("subject is required")
        if not payload["body"].strip():
            raise ValueError("body is required")
        if from_email:
            payload["from_email"] = normalize_email_address(from_email, field_name="from_email")
        if attachment_base64:
            payload["attachment_base64"] = str(attachment_base64)
            payload["attachment_filename"] = str(attachment_filename or "attachment.bin")
            payload["attachment_mime_type"] = str(attachment_mime_type or "application/octet-stream")
        if metadata:
            payload["metadata"] = _coerce_metadata(metadata)

        status_code, raw, content_type = _perform_request(
            self.webhook_url,
            body=json.dumps(payload, sort_keys=True).encode("utf-8"),
            headers=self._headers(),
            timeout_seconds=self.timeout_seconds,
        )
        response_payload = _parse_response_payload(raw, content_type)
        provider_message_id = str(
            response_payload.get("provider_message_id")
            or response_payload.get("message_id")
            or response_payload.get("email_id")
            or response_payload.get("id")
            or ""
        )
        return {
            "provider": str(response_payload.get("provider") or self.provider_name),
            "provider_status": str(response_payload.get("status") or status_code),
            "provider_message_id": provider_message_id,
        }


class SmtpEmailProvider:
    provider_name = "smtp"

    def __init__(
        self,
        *,
        smtp_host: str,
        smtp_port: int = 587,
        smtp_use_ssl: bool = False,
        smtp_starttls: bool = True,
        smtp_username: str = "",
        smtp_password: str = "",
        from_email: str = "",
        timeout_seconds: float = 20.0,
    ):
        self.smtp_host = str(smtp_host or "").strip()
        if not self.smtp_host:
            raise ValueError("smtp_host is required")
        self.smtp_port = int(smtp_port)
        self.smtp_use_ssl = bool(smtp_use_ssl)
        self.smtp_starttls = bool(smtp_starttls)
        self.smtp_username = str(smtp_username or "").strip()
        self.smtp_password = str(smtp_password or "")
        self.from_email = normalize_email_address(from_email, field_name="from_email") if from_email else ""
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def send_email(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        from_email: str = "",
        attachment_base64: str = "",
        attachment_filename: str = "",
        attachment_mime_type: str = "application/octet-stream",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        del metadata
        normalized_to_email = normalize_email_address(to_email, field_name="to_email")
        normalized_from_email = normalize_email_address(from_email, field_name="from_email") if from_email else self.from_email
        if not normalized_from_email:
            raise ValueError("from_email is required")
        normalized_subject = str(subject or "").strip()
        normalized_body = str(body or "")
        if not normalized_subject:
            raise ValueError("subject is required")
        if not normalized_body.strip():
            raise ValueError("body is required")

        message = EmailMessage()
        message["From"] = normalized_from_email
        message["To"] = normalized_to_email
        message["Subject"] = normalized_subject
        sender_domain = normalized_from_email.rsplit("@", 1)[-1].strip() if "@" in normalized_from_email else ""
        message["Message-Id"] = make_msgid(domain=sender_domain or None)
        message.set_content(normalized_body)
        if attachment_base64:
            attachment_bytes = base64.b64decode(str(attachment_base64))
            mime_type = str(attachment_mime_type or "application/octet-stream").strip().lower()
            maintype, _, subtype = mime_type.partition("/")
            if not maintype or not subtype:
                maintype, subtype = "application", "octet-stream"
            message.add_attachment(
                attachment_bytes,
                maintype=maintype,
                subtype=subtype,
                filename=str(attachment_filename or "attachment.bin"),
            )

        smtp_factory = smtplib.SMTP_SSL if self.smtp_use_ssl else smtplib.SMTP
        with smtp_factory(self.smtp_host, self.smtp_port, timeout=self.timeout_seconds) as smtp:
            if not self.smtp_use_ssl and self.smtp_starttls:
                smtp.starttls()
            if self.smtp_username:
                smtp.login(self.smtp_username, self.smtp_password)
            rejected = smtp.send_message(message)
        if rejected:
            raise RuntimeError(f"email delivery rejected recipients: {sorted(rejected)}")
        return {
            "provider": self.provider_name,
            "provider_status": "sent",
            "provider_message_id": str(message.get("Message-Id") or ""),
        }


class TwilioSmsProvider:
    """Outbound adapter for the supported Twilio REST API."""

    provider_name = "twilio"

    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        from_phone: str = "",
        messaging_service_sid: str = "",
        status_callback_url: str = "",
        timeout_seconds: float = 15.0,
    ):
        self.account_sid = str(account_sid or "").strip()
        self.auth_token = str(auth_token or "").strip()
        if not self.account_sid or not self.auth_token:
            raise ValueError("Twilio account_sid and auth_token are required")
        self.from_phone = normalize_phone_number(from_phone, field_name="from_phone") if from_phone else ""
        self.messaging_service_sid = str(messaging_service_sid or "").strip()
        self.status_callback_url = str(status_callback_url or "").strip()
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def send_sms(
        self,
        *,
        to_phone: str,
        message: str,
        from_phone: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_to_phone = normalize_phone_number(to_phone, field_name="to_phone")
        normalized_message = str(message or "")
        if not normalized_message.strip():
            raise ValueError("message is required")

        resolved_from_phone = normalize_phone_number(from_phone, field_name="from_phone") if from_phone else self.from_phone
        form_payload = {
            "To": normalized_to_phone,
            "Body": normalized_message,
        }
        if self.messaging_service_sid:
            form_payload["MessagingServiceSid"] = self.messaging_service_sid
        elif resolved_from_phone:
            form_payload["From"] = resolved_from_phone
        else:
            raise ValueError("Twilio requires from_phone or messaging_service_sid")
        if self.status_callback_url:
            form_payload["StatusCallback"] = self.status_callback_url
        if metadata:
            for key, value in _coerce_metadata(metadata).items():
                if value is None:
                    continue
                form_payload[f"Metadata[{key}]"] = str(value)

        credentials = f"{self.account_sid}:{self.auth_token}".encode("utf-8")
        headers = {
            "authorization": f"Basic {base64.b64encode(credentials).decode('ascii')}",
            "content-type": "application/x-www-form-urlencoded",
        }
        endpoint = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        status_code, raw, content_type = _perform_request(
            endpoint,
            body=urllib_parse.urlencode(form_payload).encode("utf-8"),
            headers=headers,
            timeout_seconds=self.timeout_seconds,
        )
        response_payload = _parse_response_payload(raw, content_type)
        return {
            "provider": self.provider_name,
            "provider_status": str(response_payload.get("status") or status_code),
            "provider_message_id": str(response_payload.get("sid") or response_payload.get("message_id") or ""),
        }


class WebhookEventForwarder:
    """Forward normalized inbound events to another HTTP endpoint."""

    def __init__(
        self,
        *,
        webhook_url: str,
        bearer_token: str = "",
        header_name: str = "",
        header_value: str = "",
        timeout_seconds: float = 15.0,
    ):
        self.webhook_url = str(webhook_url or "").strip()
        if not self.webhook_url:
            raise ValueError("webhook_url is required")
        self.bearer_token = str(bearer_token or "").strip()
        self.header_name = str(header_name or "").strip()
        self.header_value = str(header_value or "").strip()
        if self.header_name and not self.header_value:
            raise ValueError("header_value is required when header_name is set")
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.bearer_token:
            headers["authorization"] = f"Bearer {self.bearer_token}"
        if self.header_name:
            headers[self.header_name] = self.header_value
        return headers

    def forward(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        status_code, raw, content_type = _perform_request(
            self.webhook_url,
            body=json.dumps(dict(payload), sort_keys=True).encode("utf-8"),
            headers=self._headers(),
            timeout_seconds=self.timeout_seconds,
        )
        result: dict[str, Any] = {"status_code": status_code}
        response_payload = _parse_response_payload(raw, content_type)
        if response_payload:
            result["response"] = response_payload
        return result


class WebhookCallProvider:
    """POST JSON to an outbound phone-call worker or provider-specific adapter."""

    provider_name = "webhook"

    def __init__(
        self,
        *,
        webhook_url: str,
        bearer_token: str = "",
        header_name: str = "",
        header_value: str = "",
        timeout_seconds: float = 20.0,
        provider_name: str = "webhook",
    ):
        self.webhook_url = str(webhook_url or "").strip()
        if not self.webhook_url:
            raise ValueError("webhook_url is required")
        self.bearer_token = str(bearer_token or "").strip()
        self.header_name = str(header_name or "").strip()
        self.header_value = str(header_value or "").strip()
        if self.header_name and not self.header_value:
            raise ValueError("header_value is required when header_name is set")
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.provider_name = str(provider_name or "webhook")

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.bearer_token:
            headers["authorization"] = f"Bearer {self.bearer_token}"
        if self.header_name:
            headers[self.header_name] = self.header_value
        return headers

    def send_call(
        self,
        *,
        to_phone: str,
        script: str,
        from_phone: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "to_phone": normalize_phone_number(to_phone, field_name="to_phone"),
            "script": str(script or ""),
        }
        if not payload["script"].strip():
            raise ValueError("script is required")
        if from_phone:
            payload["from_phone"] = normalize_phone_number(from_phone, field_name="from_phone")
        if metadata:
            payload["metadata"] = _coerce_metadata(metadata)

        status_code, raw, content_type = _perform_request(
            self.webhook_url,
            body=json.dumps(payload, sort_keys=True).encode("utf-8"),
            headers=self._headers(),
            timeout_seconds=self.timeout_seconds,
        )
        response_payload = _parse_response_payload(raw, content_type)
        provider_call_id = str(
            response_payload.get("call_id")
            or response_payload.get("provider_call_id")
            or response_payload.get("provider_message_id")
            or response_payload.get("sid")
            or response_payload.get("id")
            or ""
        )
        return {
            "provider": str(response_payload.get("provider") or self.provider_name),
            "provider_status": str(response_payload.get("status") or status_code),
            "provider_call_id": provider_call_id,
        }


class TwilioCallProvider:
    """Outbound adapter for the supported Twilio Voice REST API."""

    provider_name = "twilio"

    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        from_phone: str,
        status_callback_url: str = "",
        timeout_seconds: float = 20.0,
    ):
        self.account_sid = str(account_sid or "").strip()
        self.auth_token = str(auth_token or "").strip()
        if not self.account_sid or not self.auth_token:
            raise ValueError("Twilio account_sid and auth_token are required")
        self.from_phone = normalize_phone_number(from_phone, field_name="from_phone")
        self.status_callback_url = str(status_callback_url or "").strip()
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def send_call(
        self,
        *,
        to_phone: str,
        script: str,
        from_phone: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_to_phone = normalize_phone_number(to_phone, field_name="to_phone")
        normalized_script = str(script or "")
        if not normalized_script.strip():
            raise ValueError("script is required")

        resolved_from_phone = normalize_phone_number(from_phone, field_name="from_phone") if from_phone else self.from_phone
        form_payload = {
            "To": normalized_to_phone,
            "From": resolved_from_phone,
            "Twiml": f"<Response><Say>{normalized_script}</Say></Response>",
        }
        if self.status_callback_url:
            form_payload["StatusCallback"] = self.status_callback_url
            form_payload["StatusCallbackMethod"] = "POST"
        if metadata:
            for key, value in _coerce_metadata(metadata).items():
                if value is None:
                    continue
                form_payload[f"Metadata[{key}]"] = str(value)

        credentials = f"{self.account_sid}:{self.auth_token}".encode("utf-8")
        headers = {
            "authorization": f"Basic {base64.b64encode(credentials).decode('ascii')}",
            "content-type": "application/x-www-form-urlencoded",
        }
        endpoint = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Calls.json"
        status_code, raw, content_type = _perform_request(
            endpoint,
            body=urllib_parse.urlencode(form_payload).encode("utf-8"),
            headers=headers,
            timeout_seconds=self.timeout_seconds,
        )
        response_payload = _parse_response_payload(raw, content_type)
        return {
            "provider": self.provider_name,
            "provider_status": str(response_payload.get("status") or status_code),
            "provider_call_id": str(response_payload.get("sid") or response_payload.get("call_id") or ""),
        }


class VoiceMediaAssetStore:
    def __init__(self, root_path: str | None = None):
        self.root_path = Path(root_path or _default_voice_media_root())
        self.root_path.mkdir(parents=True, exist_ok=True)

    def save(self, *, content: bytes, mime_type: str) -> dict[str, str]:
        asset_id = f"voice-media-{uuid.uuid4().hex}"
        normalized_mime_type = str(mime_type or "audio/wav").strip().lower() or "audio/wav"
        suffix = ".wav"
        if normalized_mime_type == "audio/mpeg":
            suffix = ".mp3"
        elif normalized_mime_type in {"audio/ogg", "application/ogg"}:
            suffix = ".ogg"
        asset_path = self.root_path / f"{asset_id}{suffix}"
        meta_path = self.root_path / f"{asset_id}.json"
        asset_path.write_bytes(content)
        meta_path.write_text(
            json.dumps({"mime_type": normalized_mime_type, "filename": asset_path.name}, sort_keys=True),
            encoding="utf-8",
        )
        return {
            "asset_id": asset_id,
            "mime_type": normalized_mime_type,
            "path": str(asset_path),
            "filename": asset_path.name,
        }

    def load(self, asset_id: str) -> tuple[bytes, str] | None:
        normalized_asset_id = str(asset_id or "").strip()
        if not normalized_asset_id:
            return None
        meta_path = self.root_path / f"{normalized_asset_id}.json"
        if not meta_path.exists():
            return None
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        filename = str(metadata.get("filename") or "").strip()
        mime_type = str(metadata.get("mime_type") or "audio/wav").strip()
        if not filename:
            return None
        asset_path = self.root_path / filename
        if not asset_path.exists():
            return None
        return asset_path.read_bytes(), mime_type


class RemoteVoiceProxyProvider:
    provider_name = "remote-voice-proxy"

    def __init__(
        self,
        *,
        infer_url: str,
        tts_url: str = "",
        timeout_seconds: float = 45.0,
        assistant_profile: VoiceAssistantProfile | None = None,
    ):
        self.infer_url = str(infer_url or "").strip()
        self.tts_url = str(tts_url or "").strip()
        if not self.infer_url:
            raise ValueError("infer_url is required")
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.assistant_profile = assistant_profile or VoiceAssistantProfile()

    def generate_reply(
        self,
        *,
        transcript: str,
        session: VoiceCallSessionRecord,
        turns: Sequence[VoiceCallTurnRecord],
    ) -> VoiceReplyResult:
        prompt = self.assistant_profile.build_reply_prompt(transcript=transcript, session=session, turns=turns)
        body, content_type = _encode_multipart_form(
            fields={
                "mode": "voice-reply",
                "text": prompt["full_prompt"],
                "systemPrompt": prompt["system_prompt"],
                "system_prompt": prompt["system_prompt"],
                "userPrompt": prompt["user_prompt"],
                "user_prompt": prompt["user_prompt"],
                "fallbackText": prompt["fallback_text"],
                "fallback_text": prompt["fallback_text"],
            },
            files=[("audio", "input.wav", "audio/wav", _create_silent_wav_bytes())],
        )
        _, raw_bytes, response_content_type = _perform_request_raw(
            self.infer_url,
            body=body,
            headers={
                "accept": "audio/wav, audio/*, application/json",
                "content-type": content_type,
            },
            timeout_seconds=self.timeout_seconds,
        )
        if response_content_type.lower().startswith("audio/"):
            return VoiceReplyResult(
                provider=self.provider_name,
                model_name=self.provider_name,
                text=prompt["fallback_text"],
                audio_bytes=raw_bytes,
                mime_type=response_content_type or "audio/wav",
            )

        payload = _parse_response_payload(raw_bytes.decode("utf-8", errors="replace"), response_content_type)
        audio_base64 = _first_string(payload, ["audioBase64", "audio_base64", "audio", "wavBase64", "wav_base64"])
        generated_text = _first_string(payload, ["text", "outputText", "output_text"])
        model_name = _first_string(payload, ["model", "modelName", "model_name"]) or self.provider_name
        if audio_base64:
            mime_type = _first_string(payload, ["mimeType", "mime_type"]) or "audio/wav"
            return VoiceReplyResult(
                provider=self.provider_name,
                model_name=model_name,
                text=generated_text or prompt["fallback_text"],
                audio_bytes=base64.b64decode(audio_base64.split(",")[-1]),
                mime_type=mime_type,
            )
        if generated_text and self.tts_url:
            _, tts_audio, tts_content_type = _perform_request_raw(
                self.tts_url,
                body=urllib_parse.urlencode({"text": generated_text}).encode("utf-8"),
                headers={
                    "accept": "audio/wav, audio/*, application/json",
                    "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
                },
                timeout_seconds=self.timeout_seconds,
            )
            if tts_content_type.lower().startswith("audio/"):
                return VoiceReplyResult(
                    provider=self.provider_name,
                    model_name=model_name,
                    text=generated_text,
                    audio_bytes=tts_audio,
                    mime_type=tts_content_type or "audio/wav",
                )
        if generated_text:
            return VoiceReplyResult(provider=self.provider_name, model_name=model_name, text=generated_text)
        raise RuntimeError("voice proxy returned neither audio nor text")


class OutboundSmsRequest(BaseModel):
    to_phone: str
    message: str
    from_phone: str = ""
    wallet_id: str = ""
    external_reference: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class OutboundEmailRequest(BaseModel):
    to_email: str
    subject: str
    body: str
    from_email: str = ""
    wallet_id: str = ""
    external_reference: str = ""
    attachment_base64: str = ""
    attachment_filename: str = ""
    attachment_mime_type: str = "application/octet-stream"
    metadata: dict[str, Any] = Field(default_factory=dict)


class InboundSmsWebhookRequest(BaseModel):
    from_phone: str
    message: str
    to_phone: str = ""
    provider: str = "webhook"
    provider_message_id: str = ""
    external_reference: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class OutboundCallRequest(BaseModel):
    to_phone: str
    script: str
    from_phone: str = ""
    wallet_id: str = ""
    external_reference: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_email_provider(
    *,
    provider_kind: str | None = None,
    webhook_url: str | None = None,
    bearer_token: str | None = None,
    header_name: str | None = None,
    header_value: str | None = None,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    smtp_use_ssl: bool | None = None,
    smtp_starttls: bool | None = None,
    smtp_username: str | None = None,
    smtp_password: str | None = None,
    from_email: str | None = None,
    timeout_seconds: float | None = None,
) -> EmailDeliveryProvider | None:
    resolved_webhook_url = _first_non_empty(webhook_url, os.getenv("IPFS_DATASETS_EMAIL_PROVIDER_WEBHOOK_URL"))
    resolved_smtp_host = _first_non_empty(
        smtp_host,
        os.getenv("IPFS_DATASETS_EMAIL_SMTP_HOST"),
        os.getenv("WALLET_DEAD_DROP_SMTP_HOST"),
    )
    resolved_kind = _first_non_empty(provider_kind, os.getenv("IPFS_DATASETS_EMAIL_PROVIDER_KIND"))
    if not resolved_kind:
        if resolved_webhook_url:
            resolved_kind = "webhook"
        elif resolved_smtp_host:
            resolved_kind = "smtp"
        else:
            return None

    resolved_timeout = timeout_seconds
    if resolved_timeout is None:
        resolved_timeout = float(_first_non_empty(os.getenv("IPFS_DATASETS_EMAIL_PROVIDER_TIMEOUT_SECONDS"), "20"))

    normalized_kind = resolved_kind.lower()
    if normalized_kind == "mock":
        return MockEmailProvider(
            from_email=_first_non_empty(
                from_email,
                os.getenv("IPFS_DATASETS_EMAIL_FROM_EMAIL"),
                os.getenv("WALLET_DEAD_DROP_FROM_EMAIL"),
                "no-reply@211-ai.org",
            )
        )
    if normalized_kind == "webhook":
        return WebhookEmailProvider(
            webhook_url=resolved_webhook_url,
            bearer_token=_first_non_empty(bearer_token, os.getenv("IPFS_DATASETS_EMAIL_PROVIDER_BEARER_TOKEN")),
            header_name=_first_non_empty(header_name, os.getenv("IPFS_DATASETS_EMAIL_PROVIDER_HTTP_HEADER_NAME")),
            header_value=_first_non_empty(header_value, os.getenv("IPFS_DATASETS_EMAIL_PROVIDER_HTTP_HEADER_VALUE")),
            timeout_seconds=resolved_timeout,
        )
    if normalized_kind == "smtp":
        resolved_smtp_port = smtp_port
        if resolved_smtp_port is None:
            resolved_smtp_port = int(
                _first_non_empty(
                    os.getenv("IPFS_DATASETS_EMAIL_SMTP_PORT"),
                    os.getenv("WALLET_DEAD_DROP_SMTP_PORT"),
                    "587",
                )
            )
        resolved_smtp_use_ssl = smtp_use_ssl
        if resolved_smtp_use_ssl is None:
            resolved_smtp_use_ssl = _truthy(
                _first_non_empty(
                    os.getenv("IPFS_DATASETS_EMAIL_SMTP_USE_SSL"),
                    os.getenv("WALLET_DEAD_DROP_SMTP_USE_SSL"),
                )
            )
        resolved_smtp_starttls = smtp_starttls
        if resolved_smtp_starttls is None:
            resolved_smtp_starttls = _truthy(
                _first_non_empty(
                    os.getenv("IPFS_DATASETS_EMAIL_SMTP_STARTTLS"),
                    os.getenv("WALLET_DEAD_DROP_SMTP_STARTTLS"),
                    "true",
                )
            )
        return SmtpEmailProvider(
            smtp_host=resolved_smtp_host,
            smtp_port=resolved_smtp_port,
            smtp_use_ssl=resolved_smtp_use_ssl,
            smtp_starttls=resolved_smtp_starttls,
            smtp_username=_first_non_empty(
                smtp_username,
                os.getenv("IPFS_DATASETS_EMAIL_SMTP_USERNAME"),
                os.getenv("WALLET_DEAD_DROP_SMTP_USERNAME"),
            ),
            smtp_password=_first_non_empty(
                smtp_password,
                os.getenv("IPFS_DATASETS_EMAIL_SMTP_PASSWORD"),
                os.getenv("WALLET_DEAD_DROP_SMTP_PASSWORD"),
            ),
            from_email=_first_non_empty(
                from_email,
                os.getenv("IPFS_DATASETS_EMAIL_FROM_EMAIL"),
                os.getenv("WALLET_DEAD_DROP_FROM_EMAIL"),
                "no-reply@211-ai.org",
            ),
            timeout_seconds=resolved_timeout,
        )
    raise ValueError(f"unsupported email provider kind: {resolved_kind}")


def build_sms_provider(
    *,
    provider_kind: str | None = None,
    webhook_url: str | None = None,
    bearer_token: str | None = None,
    header_name: str | None = None,
    header_value: str | None = None,
    account_sid: str | None = None,
    auth_token: str | None = None,
    from_phone: str | None = None,
    messaging_service_sid: str | None = None,
    status_callback_url: str | None = None,
    timeout_seconds: float | None = None,
) -> SmsDeliveryProvider | None:
    resolved_webhook_url = _first_non_empty(webhook_url, os.getenv("IPFS_DATASETS_SMS_PROVIDER_WEBHOOK_URL"))
    resolved_account_sid = _first_non_empty(account_sid, os.getenv("IPFS_DATASETS_SMS_TWILIO_ACCOUNT_SID"))
    resolved_auth_token = _first_non_empty(auth_token, os.getenv("IPFS_DATASETS_SMS_TWILIO_AUTH_TOKEN"))
    resolved_kind = _first_non_empty(provider_kind, os.getenv("IPFS_DATASETS_SMS_PROVIDER_KIND"))
    if not resolved_kind:
        if resolved_webhook_url:
            resolved_kind = "webhook"
        elif resolved_account_sid and resolved_auth_token:
            resolved_kind = "twilio"
        else:
            return None

    resolved_timeout = timeout_seconds
    if resolved_timeout is None:
        resolved_timeout = float(_first_non_empty(os.getenv("IPFS_DATASETS_SMS_PROVIDER_TIMEOUT_SECONDS"), "15"))

    normalized_kind = resolved_kind.lower()
    if normalized_kind == "mock":
        return MockSmsProvider(
            from_phone=_first_non_empty(from_phone, os.getenv("IPFS_DATASETS_SMS_TWILIO_FROM_PHONE")),
        )
    if normalized_kind == "webhook":
        return WebhookSmsProvider(
            webhook_url=resolved_webhook_url,
            bearer_token=_first_non_empty(bearer_token, os.getenv("IPFS_DATASETS_SMS_PROVIDER_BEARER_TOKEN")),
            header_name=_first_non_empty(header_name, os.getenv("IPFS_DATASETS_SMS_PROVIDER_HTTP_HEADER_NAME")),
            header_value=_first_non_empty(header_value, os.getenv("IPFS_DATASETS_SMS_PROVIDER_HTTP_HEADER_VALUE")),
            timeout_seconds=resolved_timeout,
        )
    if normalized_kind == "twilio":
        return TwilioSmsProvider(
            account_sid=resolved_account_sid,
            auth_token=resolved_auth_token,
            from_phone=_first_non_empty(from_phone, os.getenv("IPFS_DATASETS_SMS_TWILIO_FROM_PHONE")),
            messaging_service_sid=_first_non_empty(
                messaging_service_sid,
                os.getenv("IPFS_DATASETS_SMS_TWILIO_MESSAGING_SERVICE_SID"),
            ),
            status_callback_url=_first_non_empty(
                status_callback_url,
                os.getenv("IPFS_DATASETS_SMS_TWILIO_STATUS_CALLBACK_URL"),
            ),
            timeout_seconds=resolved_timeout,
        )
    raise ValueError(f"unsupported SMS provider kind: {resolved_kind}")


def build_inbound_forwarder(
    *,
    webhook_url: str | None = None,
    bearer_token: str | None = None,
    header_name: str | None = None,
    header_value: str | None = None,
    timeout_seconds: float | None = None,
) -> WebhookEventForwarder | None:
    resolved_webhook_url = _first_non_empty(webhook_url, os.getenv("IPFS_DATASETS_SMS_INBOUND_FORWARD_URL"))
    if not resolved_webhook_url:
        return None
    resolved_timeout = timeout_seconds
    if resolved_timeout is None:
        resolved_timeout = float(_first_non_empty(os.getenv("IPFS_DATASETS_SMS_INBOUND_FORWARD_TIMEOUT_SECONDS"), "15"))
    return WebhookEventForwarder(
        webhook_url=resolved_webhook_url,
        bearer_token=_first_non_empty(bearer_token, os.getenv("IPFS_DATASETS_SMS_INBOUND_FORWARD_BEARER_TOKEN")),
        header_name=_first_non_empty(header_name, os.getenv("IPFS_DATASETS_SMS_INBOUND_FORWARD_HTTP_HEADER_NAME")),
        header_value=_first_non_empty(header_value, os.getenv("IPFS_DATASETS_SMS_INBOUND_FORWARD_HTTP_HEADER_VALUE")),
        timeout_seconds=resolved_timeout,
    )


def build_call_provider(
    *,
    provider_kind: str | None = None,
    webhook_url: str | None = None,
    bearer_token: str | None = None,
    header_name: str | None = None,
    header_value: str | None = None,
    account_sid: str | None = None,
    auth_token: str | None = None,
    from_phone: str | None = None,
    status_callback_url: str | None = None,
    timeout_seconds: float | None = None,
) -> CallDeliveryProvider | None:
    resolved_webhook_url = _first_non_empty(webhook_url, os.getenv("IPFS_DATASETS_CALL_PROVIDER_WEBHOOK_URL"))
    resolved_account_sid = _first_non_empty(account_sid, os.getenv("IPFS_DATASETS_CALL_TWILIO_ACCOUNT_SID"))
    resolved_auth_token = _first_non_empty(auth_token, os.getenv("IPFS_DATASETS_CALL_TWILIO_AUTH_TOKEN"))
    resolved_kind = _first_non_empty(provider_kind, os.getenv("IPFS_DATASETS_CALL_PROVIDER_KIND"))
    if not resolved_kind:
        if resolved_webhook_url:
            resolved_kind = "webhook"
        elif resolved_account_sid and resolved_auth_token:
            resolved_kind = "twilio"
        else:
            return None

    resolved_timeout = timeout_seconds
    if resolved_timeout is None:
        resolved_timeout = float(_first_non_empty(os.getenv("IPFS_DATASETS_CALL_PROVIDER_TIMEOUT_SECONDS"), "20"))

    normalized_kind = resolved_kind.lower()
    if normalized_kind == "mock":
        return MockCallProvider(
            from_phone=_first_non_empty(from_phone, os.getenv("IPFS_DATASETS_CALL_TWILIO_FROM_PHONE")),
        )
    if normalized_kind == "webhook":
        return WebhookCallProvider(
            webhook_url=resolved_webhook_url,
            bearer_token=_first_non_empty(bearer_token, os.getenv("IPFS_DATASETS_CALL_PROVIDER_BEARER_TOKEN")),
            header_name=_first_non_empty(header_name, os.getenv("IPFS_DATASETS_CALL_PROVIDER_HTTP_HEADER_NAME")),
            header_value=_first_non_empty(header_value, os.getenv("IPFS_DATASETS_CALL_PROVIDER_HTTP_HEADER_VALUE")),
            timeout_seconds=resolved_timeout,
        )
    if normalized_kind == "twilio":
        return TwilioCallProvider(
            account_sid=resolved_account_sid,
            auth_token=resolved_auth_token,
            from_phone=_first_non_empty(from_phone, os.getenv("IPFS_DATASETS_CALL_TWILIO_FROM_PHONE")),
            status_callback_url=_first_non_empty(
                status_callback_url,
                os.getenv("IPFS_DATASETS_CALL_TWILIO_STATUS_CALLBACK_URL"),
            ),
            timeout_seconds=resolved_timeout,
        )
    raise ValueError(f"unsupported call provider kind: {resolved_kind}")


def build_voice_assistant_profile(
    *,
    assistant_name: str | None = None,
    service_name: str | None = None,
    greeting: str | None = None,
    no_speech_prompt: str | None = None,
    follow_up_prompt: str | None = None,
    farewell: str | None = None,
    unavailable_prompt: str | None = None,
    website_url: str | None = None,
    system_prompt_append: str | None = None,
    max_turns: int | None = None,
) -> VoiceAssistantProfile:
    resolved_max_turns = max_turns
    if resolved_max_turns is None:
        resolved_max_turns = int(_first_non_empty(os.getenv("IPFS_DATASETS_VOICE_MAX_TURNS"), "8"))
    return VoiceAssistantProfile(
        assistant_name=_first_non_empty(assistant_name, os.getenv("IPFS_DATASETS_VOICE_AGENT_NAME")) or "Abby",
        service_name=_first_non_empty(service_name, os.getenv("IPFS_DATASETS_VOICE_SERVICE_NAME")) or "211 AI",
        greeting=_first_non_empty(greeting, os.getenv("IPFS_DATASETS_VOICE_GREETING")) or _DEFAULT_VOICE_GREETING,
        no_speech_prompt=_first_non_empty(no_speech_prompt, os.getenv("IPFS_DATASETS_VOICE_NO_SPEECH_PROMPT"))
        or _DEFAULT_VOICE_NO_SPEECH_PROMPT,
        follow_up_prompt=_first_non_empty(follow_up_prompt, os.getenv("IPFS_DATASETS_VOICE_FOLLOW_UP_PROMPT"))
        or _DEFAULT_VOICE_FOLLOW_UP,
        farewell=_first_non_empty(farewell, os.getenv("IPFS_DATASETS_VOICE_FAREWELL")) or _DEFAULT_VOICE_FAREWELL,
        unavailable_prompt=_first_non_empty(
            unavailable_prompt,
            os.getenv("IPFS_DATASETS_VOICE_UNAVAILABLE_PROMPT"),
        )
        or _DEFAULT_VOICE_UNAVAILABLE_PROMPT,
        website_url=_first_non_empty(website_url, os.getenv("IPFS_DATASETS_VOICE_WEBSITE_URL")) or "https://211-ai.com",
        system_prompt_append=_first_non_empty(
            system_prompt_append,
            os.getenv("IPFS_DATASETS_VOICE_SYSTEM_PROMPT_APPEND"),
        ),
        max_turns=max(1, int(resolved_max_turns)),
    )


def build_voice_reply_provider(
    *,
    provider_kind: str | None = None,
    base_url: str | None = None,
    infer_url: str | None = None,
    tts_url: str | None = None,
    timeout_seconds: float | None = None,
    mock_reply_text: str | None = None,
    assistant_profile: VoiceAssistantProfile | None = None,
) -> VoiceReplyProvider | None:
    resolved_kind = _first_non_empty(provider_kind, os.getenv("IPFS_DATASETS_VOICE_REPLY_PROVIDER_KIND"))
    resolved_base_url = _first_non_empty(base_url, os.getenv("IPFS_DATASETS_VOICE_PROXY_BASE_URL"))
    resolved_infer_url = _first_non_empty(
        infer_url,
        os.getenv("IPFS_DATASETS_VOICE_PROXY_INFER_URL"),
        _append_url_path(resolved_base_url, "infer"),
    )
    resolved_profile = assistant_profile or build_voice_assistant_profile()
    if resolved_kind and resolved_kind.lower() == "mock":
        return MockVoiceReplyProvider(
            reply_text=_first_non_empty(mock_reply_text, os.getenv("IPFS_DATASETS_VOICE_MOCK_REPLY_TEXT")),
            assistant_profile=resolved_profile,
        )
    if not resolved_infer_url:
        return None
    resolved_timeout = timeout_seconds
    if resolved_timeout is None:
        resolved_timeout = float(_first_non_empty(os.getenv("IPFS_DATASETS_VOICE_PROXY_TIMEOUT_SECONDS"), "45"))
    return RemoteVoiceProxyProvider(
        infer_url=resolved_infer_url,
        tts_url=_first_non_empty(
            tts_url,
            os.getenv("IPFS_DATASETS_VOICE_PROXY_TTS_URL"),
            _append_url_path(resolved_base_url, "tts"),
        ),
        timeout_seconds=resolved_timeout,
        assistant_profile=resolved_profile,
    )


def _parse_form_body(body: bytes) -> dict[str, str]:
    parsed = urllib_parse.parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


async def _parse_request_form(request: Request) -> dict[str, str]:
    try:
        form = await request.form()
    except Exception:
        return _parse_form_body(await request.body())

    normalized: dict[str, str] = {}
    for key, value in form.multi_items():
        if hasattr(value, "filename"):
            continue
        normalized[str(key)] = str(value)
    return normalized


def _forward_inbound_message(
    forwarder: WebhookEventForwarder | None,
    record: SmsMessageRecord,
) -> dict[str, Any] | None:
    if forwarder is None:
        return None
    return forwarder.forward(record.to_dict())


def create_sms_bridge_app(
    *,
    repository: SmsBridgeStore | None = None,
    provider: SmsDeliveryProvider | None = None,
    email_provider: EmailDeliveryProvider | None = None,
    inbound_forwarder: WebhookEventForwarder | None = None,
    call_provider: CallDeliveryProvider | None = None,
    voice_reply_provider: VoiceReplyProvider | None = None,
    voice_media_store: VoiceMediaAssetStore | None = None,
    voice_profile: VoiceAssistantProfile | None = None,
    public_base_url: str = "",
):
    if FastAPI is None or HTTPException is None or Request is None or Response is None:  # pragma: no cover
        raise RuntimeError("FastAPI is required to create the SMS bridge app")

    sms_store = repository or SmsBridgeStore()
    delivery_provider = provider if provider is not None else build_sms_provider()
    outbound_email_provider = email_provider if email_provider is not None else build_email_provider()
    forwarder = inbound_forwarder if inbound_forwarder is not None else build_inbound_forwarder()
    outbound_call_provider = call_provider if call_provider is not None else build_call_provider()
    resolved_voice_profile = voice_profile or build_voice_assistant_profile()
    resolved_voice_reply_provider = (
        voice_reply_provider
        if voice_reply_provider is not None
        else build_voice_reply_provider(assistant_profile=resolved_voice_profile)
    )
    media_store = voice_media_store or VoiceMediaAssetStore()
    configured_public_base_url = str(public_base_url or os.getenv("IPFS_DATASETS_VOICE_PUBLIC_BASE_URL") or "").strip()

    app = FastAPI(title="IPFS Datasets Messaging Bridge", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "provider": getattr(delivery_provider, "provider_name", "") or "",
            "provider_configured": delivery_provider is not None,
            "email_provider": getattr(outbound_email_provider, "provider_name", "") or "",
            "email_provider_configured": outbound_email_provider is not None,
            "call_provider": getattr(outbound_call_provider, "provider_name", "") or "",
            "call_provider_configured": outbound_call_provider is not None,
            "voice_reply_provider": getattr(resolved_voice_reply_provider, "provider_name", "") or "",
            "voice_reply_provider_configured": resolved_voice_reply_provider is not None,
            "inbound_forwarding_configured": forwarder is not None,
            "db_path": sms_store.path,
        }

    @app.post("/messages/email/outbound")
    def send_outbound_email(request: OutboundEmailRequest) -> dict[str, Any]:
        payload = _model_dump(request)
        attachment_metadata: dict[str, Any] = {}
        if payload.get("attachment_filename"):
            attachment_metadata["attachment_filename"] = str(payload.get("attachment_filename") or "")
        if payload.get("attachment_mime_type"):
            attachment_metadata["attachment_mime_type"] = str(payload.get("attachment_mime_type") or "")
        if payload.get("attachment_base64"):
            try:
                attachment_metadata["attachment_bytes"] = len(base64.b64decode(str(payload.get("attachment_base64") or "")))
            except Exception:
                attachment_metadata["attachment_invalid_base64"] = True
        record_metadata = {**dict(payload.get("metadata") or {}), **attachment_metadata}
        if outbound_email_provider is None:
            failed_record = sms_store.record_outbound_email(
                provider="unconfigured",
                status="failed",
                to_email=payload["to_email"],
                subject=payload["subject"],
                body=payload["body"],
                from_email=payload.get("from_email", ""),
                wallet_id=payload.get("wallet_id", ""),
                external_reference=payload.get("external_reference", ""),
                metadata={**record_metadata, "error": "Email provider not configured"},
            )
            raise HTTPException(
                status_code=503,
                detail={"message": "Email provider not configured", "record": failed_record.to_dict()},
            )
        try:
            delivery = outbound_email_provider.send_email(
                to_email=payload["to_email"],
                subject=payload["subject"],
                body=payload["body"],
                from_email=payload.get("from_email", ""),
                attachment_base64=payload.get("attachment_base64", ""),
                attachment_filename=payload.get("attachment_filename", ""),
                attachment_mime_type=payload.get("attachment_mime_type", "application/octet-stream"),
                metadata=payload.get("metadata") or {},
            )
            record = sms_store.record_outbound_email(
                provider=str(delivery.get("provider") or getattr(outbound_email_provider, "provider_name", "unknown")),
                status=str(delivery.get("provider_status") or "sent"),
                provider_message_id=str(delivery.get("provider_message_id") or ""),
                to_email=payload["to_email"],
                subject=payload["subject"],
                body=payload["body"],
                from_email=payload.get("from_email", ""),
                wallet_id=payload.get("wallet_id", ""),
                external_reference=payload.get("external_reference", ""),
                metadata=record_metadata,
            )
            return {
                "status": "ok",
                "email": record.to_dict(),
                "provider_message_id": str(delivery.get("provider_message_id") or ""),
                **delivery,
            }
        except ValueError as exc:
            failed_record = sms_store.record_outbound_email(
                provider=getattr(outbound_email_provider, "provider_name", "unknown"),
                status="failed",
                to_email=payload["to_email"],
                subject=payload["subject"],
                body=payload["body"],
                from_email=payload.get("from_email", ""),
                wallet_id=payload.get("wallet_id", ""),
                external_reference=payload.get("external_reference", ""),
                metadata={**record_metadata, "error": str(exc)},
            )
            raise HTTPException(status_code=400, detail={"message": str(exc), "record": failed_record.to_dict()}) from exc
        except RuntimeError as exc:
            failed_record = sms_store.record_outbound_email(
                provider=getattr(outbound_email_provider, "provider_name", "unknown"),
                status="failed",
                to_email=payload["to_email"],
                subject=payload["subject"],
                body=payload["body"],
                from_email=payload.get("from_email", ""),
                wallet_id=payload.get("wallet_id", ""),
                external_reference=payload.get("external_reference", ""),
                metadata={**record_metadata, "error": str(exc)},
            )
            raise HTTPException(status_code=502, detail={"message": str(exc), "record": failed_record.to_dict()}) from exc

    @app.get("/messages/email")
    def list_email_messages(
        limit: int = Query(default=100, ge=1, le=500),
        provider: str = "",
        status: str = "",
        to_email: str = "",
    ) -> dict[str, Any]:
        try:
            messages = sms_store.list_email_messages(limit=limit, provider=provider, status=status, to_email=to_email)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"count": len(messages), "messages": [message.to_dict() for message in messages]}

    @app.post("/messages/sms/outbound")
    def send_outbound_sms(request: OutboundSmsRequest) -> dict[str, Any]:
        payload = _model_dump(request)
        if delivery_provider is None:
            failed_record = sms_store.record_outbound(
                provider="unconfigured",
                status="failed",
                to_phone=payload["to_phone"],
                message=payload["message"],
                from_phone=payload.get("from_phone", ""),
                wallet_id=payload.get("wallet_id", ""),
                external_reference=payload.get("external_reference", ""),
                metadata={**dict(payload.get("metadata") or {}), "error": "SMS provider not configured"},
            )
            raise HTTPException(
                status_code=503,
                detail={"message": "SMS provider not configured", "record": failed_record.to_dict()},
            )
        try:
            delivery = delivery_provider.send_sms(
                to_phone=payload["to_phone"],
                message=payload["message"],
                from_phone=payload.get("from_phone", ""),
                metadata=payload.get("metadata") or {},
            )
            record = sms_store.record_outbound(
                provider=str(delivery.get("provider") or getattr(delivery_provider, "provider_name", "unknown")),
                status=str(delivery.get("provider_status") or "sent"),
                provider_message_id=str(delivery.get("provider_message_id") or ""),
                to_phone=payload["to_phone"],
                message=payload["message"],
                from_phone=payload.get("from_phone", ""),
                wallet_id=payload.get("wallet_id", ""),
                external_reference=payload.get("external_reference", ""),
                metadata=payload.get("metadata") or {},
            )
            return {
                "status": "ok",
                "message": record.to_dict(),
                **delivery,
            }
        except ValueError as exc:
            failed_record = sms_store.record_outbound(
                provider=getattr(delivery_provider, "provider_name", "unknown"),
                status="failed",
                to_phone=payload["to_phone"],
                message=payload["message"],
                from_phone=payload.get("from_phone", ""),
                wallet_id=payload.get("wallet_id", ""),
                external_reference=payload.get("external_reference", ""),
                metadata={**dict(payload.get("metadata") or {}), "error": str(exc)},
            )
            raise HTTPException(status_code=400, detail={"message": str(exc), "record": failed_record.to_dict()}) from exc
        except RuntimeError as exc:
            failed_record = sms_store.record_outbound(
                provider=getattr(delivery_provider, "provider_name", "unknown"),
                status="failed",
                to_phone=payload["to_phone"],
                message=payload["message"],
                from_phone=payload.get("from_phone", ""),
                wallet_id=payload.get("wallet_id", ""),
                external_reference=payload.get("external_reference", ""),
                metadata={**dict(payload.get("metadata") or {}), "error": str(exc)},
            )
            raise HTTPException(status_code=502, detail={"message": str(exc), "record": failed_record.to_dict()}) from exc

    @app.get("/messages/sms")
    def list_sms_messages(
        limit: int = Query(default=100, ge=1, le=500),
        direction: str = "",
        provider: str = "",
        status: str = "",
        phone: str = "",
    ) -> dict[str, Any]:
        try:
            messages = sms_store.list_messages(
                limit=limit,
                direction=direction,
                provider=provider,
                status=status,
                phone=phone,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"count": len(messages), "messages": [message.to_dict() for message in messages]}

    @app.post("/messages/calls/outbound")
    def send_outbound_call(request: OutboundCallRequest) -> dict[str, Any]:
        payload = _model_dump(request)
        if outbound_call_provider is None:
            failed_record = sms_store.record_outbound_call(
                provider="unconfigured",
                status="failed",
                to_phone=payload["to_phone"],
                script=payload["script"],
                from_phone=payload.get("from_phone", ""),
                wallet_id=payload.get("wallet_id", ""),
                external_reference=payload.get("external_reference", ""),
                metadata={**dict(payload.get("metadata") or {}), "error": "Call provider not configured"},
            )
            raise HTTPException(
                status_code=503,
                detail={"message": "Call provider not configured", "record": failed_record.to_dict()},
            )
        try:
            delivery = outbound_call_provider.send_call(
                to_phone=payload["to_phone"],
                script=payload["script"],
                from_phone=payload.get("from_phone", ""),
                metadata=payload.get("metadata") or {},
            )
            provider_call_id = str(delivery.get("provider_call_id") or delivery.get("provider_message_id") or "")
            record = sms_store.record_outbound_call(
                provider=str(delivery.get("provider") or getattr(outbound_call_provider, "provider_name", "unknown")),
                status=str(delivery.get("provider_status") or "queued"),
                provider_call_id=provider_call_id,
                to_phone=payload["to_phone"],
                script=payload["script"],
                from_phone=payload.get("from_phone", ""),
                wallet_id=payload.get("wallet_id", ""),
                external_reference=payload.get("external_reference", ""),
                metadata=payload.get("metadata") or {},
            )
            return {
                "status": "ok",
                "call": record.to_dict(),
                "provider_message_id": provider_call_id,
                "provider_call_id": provider_call_id,
                **delivery,
            }
        except ValueError as exc:
            failed_record = sms_store.record_outbound_call(
                provider=getattr(outbound_call_provider, "provider_name", "unknown"),
                status="failed",
                to_phone=payload["to_phone"],
                script=payload["script"],
                from_phone=payload.get("from_phone", ""),
                wallet_id=payload.get("wallet_id", ""),
                external_reference=payload.get("external_reference", ""),
                metadata={**dict(payload.get("metadata") or {}), "error": str(exc)},
            )
            raise HTTPException(status_code=400, detail={"message": str(exc), "record": failed_record.to_dict()}) from exc
        except RuntimeError as exc:
            failed_record = sms_store.record_outbound_call(
                provider=getattr(outbound_call_provider, "provider_name", "unknown"),
                status="failed",
                to_phone=payload["to_phone"],
                script=payload["script"],
                from_phone=payload.get("from_phone", ""),
                wallet_id=payload.get("wallet_id", ""),
                external_reference=payload.get("external_reference", ""),
                metadata={**dict(payload.get("metadata") or {}), "error": str(exc)},
            )
            raise HTTPException(status_code=502, detail={"message": str(exc), "record": failed_record.to_dict()}) from exc

    @app.get("/messages/calls")
    def list_phone_calls(
        limit: int = Query(default=100, ge=1, le=500),
        provider: str = "",
        status: str = "",
        phone: str = "",
    ) -> dict[str, Any]:
        try:
            calls = sms_store.list_calls(limit=limit, provider=provider, status=status, phone=phone)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"count": len(calls), "calls": [call.to_dict() for call in calls]}

    @app.post("/providers/webhook/inbound")
    def receive_webhook_inbound_sms(request: InboundSmsWebhookRequest) -> dict[str, Any]:
        payload = _model_dump(request)
        try:
            record = sms_store.record_inbound(
                provider=str(payload.get("provider") or "webhook"),
                from_phone=payload["from_phone"],
                to_phone=payload.get("to_phone", ""),
                message=payload["message"],
                provider_message_id=payload.get("provider_message_id", ""),
                external_reference=payload.get("external_reference", ""),
                metadata=payload.get("metadata") or {},
            )
            forward_result = _forward_inbound_message(forwarder, record)
            response = {"status": "ok", "message": record.to_dict()}
            if forward_result is not None:
                response["forward_result"] = forward_result
            return response
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/providers/twilio/inbound")
    async def receive_twilio_inbound_sms(request: Request) -> Response:
        form = _parse_form_body(await request.body())
        metadata = {
            "account_sid": str(form.get("AccountSid") or ""),
            "num_media": str(form.get("NumMedia") or "0"),
            "sms_status": str(form.get("SmsStatus") or "received"),
        }
        record = sms_store.record_inbound(
            provider="twilio",
            from_phone=str(form.get("From") or ""),
            to_phone=str(form.get("To") or ""),
            message=str(form.get("Body") or ""),
            provider_message_id=str(form.get("MessageSid") or form.get("SmsSid") or ""),
            metadata=metadata,
        )
        _forward_inbound_message(forwarder, record)
        return Response(content=_TWILIO_EMPTY_RESPONSE, media_type="application/xml")

    @app.post("/providers/twilio/status")
    async def receive_twilio_status_callback(request: Request) -> dict[str, Any]:
        form = _parse_form_body(await request.body())
        try:
            updated = sms_store.update_status_by_provider_message_id(
                provider_message_id=str(form.get("MessageSid") or form.get("SmsSid") or ""),
                status=str(form.get("MessageStatus") or form.get("SmsStatus") or ""),
                metadata_update={
                    "error_code": str(form.get("ErrorCode") or ""),
                    "error_message": str(form.get("ErrorMessage") or ""),
                    "raw_status": str(form.get("SmsStatus") or form.get("MessageStatus") or ""),
                },
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "status": "ok",
            "updated": updated is not None,
            "message": updated.to_dict() if updated is not None else None,
        }

    @app.post("/providers/twilio/voice/status")
    async def receive_twilio_voice_status_callback(request: Request) -> dict[str, Any]:
        form = _parse_form_body(await request.body())
        metadata_update = {
            "account_sid": str(form.get("AccountSid") or ""),
            "call_duration": str(form.get("CallDuration") or ""),
            "answered_by": str(form.get("AnsweredBy") or ""),
            "direction": str(form.get("Direction") or ""),
            "to": str(form.get("To") or ""),
            "from": str(form.get("From") or ""),
        }
        try:
            updated = sms_store.update_call_status_by_provider_call_id(
                provider_call_id=str(form.get("CallSid") or ""),
                status=str(form.get("CallStatus") or ""),
                metadata_update=metadata_update,
            )
            voice_session = sms_store.update_voice_session_status_by_provider_call_id(
                provider_call_id=str(form.get("CallSid") or ""),
                status=str(form.get("CallStatus") or ""),
                metadata_update=metadata_update,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "status": "ok",
            "updated": updated is not None or voice_session is not None,
            "call": updated.to_dict() if updated is not None else None,
            "voice_session": voice_session.to_dict() if voice_session is not None else None,
            "voice_session_updated": voice_session is not None,
        }

    async def _create_or_load_voice_session(request: Request, *, provider_name: str, entrypoint: str) -> tuple[VoiceCallSessionRecord, str]:
        form = _parse_form_body(await request.body())
        provider_call_id = str(form.get("CallSid") or form.get("call_sid") or "").strip()
        session = sms_store.get_voice_session_by_provider_call_id(provider_call_id) if provider_call_id else None
        if session is None:
            session = sms_store.create_voice_session(
                provider=provider_name,
                provider_call_id=provider_call_id,
                from_phone=str(form.get("From") or ""),
                to_phone=str(form.get("To") or ""),
                assistant_name=resolved_voice_profile.assistant_name,
                service_name=resolved_voice_profile.service_name,
                greeting=resolved_voice_profile.greeting,
                metadata={
                    "entrypoint": entrypoint,
                    "account_sid": str(form.get("AccountSid") or ""),
                },
            )
        return session, _resolve_public_base_url(request, configured_public_base_url)

    def _voice_turn_action_url(public_base: str, session_id: str) -> str:
        return _join_public_url(
            public_base,
            f"/providers/twilio/voice/assistant-turn?{urllib_parse.urlencode({'session_id': session_id})}",
        )

    def _voice_media_url(public_base: str, asset_id: str) -> str:
        return _join_public_url(public_base, f"/voice/media/{asset_id}")

    def _mock_voice_proxy_enabled() -> bool:
        return str(getattr(resolved_voice_reply_provider, "provider_name", "") or "").strip() == "mock-voice"

    def _mock_voice_proxy_session() -> VoiceCallSessionRecord:
        timestamp = _utcnow_iso()
        return VoiceCallSessionRecord(
            session_id="voice-proxy-mock-session",
            provider="mock-voice-proxy",
            provider_call_id="",
            status="active",
            assistant_name=resolved_voice_profile.assistant_name,
            service_name=resolved_voice_profile.service_name,
            greeting=resolved_voice_profile.greeting,
            metadata={"entrypoint": "browser-voice-proxy"},
            created_at=timestamp,
            updated_at=timestamp,
        )

    @app.post("/voice/tts")
    async def mock_voice_tts(request: Request) -> dict[str, Any]:
        if not _mock_voice_proxy_enabled():
            raise HTTPException(status_code=503, detail="mock browser voice proxy is not enabled")
        form = await _parse_request_form(request)
        text = _normalize_turn_text(str(form.get("text") or ""), max_length=480)
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        return {
            "provider": "mock-voice-proxy",
            "model": getattr(resolved_voice_reply_provider, "provider_name", "mock-voice"),
            "text": text,
        }

    @app.post("/voice/infer")
    async def mock_voice_infer(request: Request) -> dict[str, Any]:
        if not _mock_voice_proxy_enabled() or resolved_voice_reply_provider is None:
            raise HTTPException(status_code=503, detail="mock browser voice proxy is not enabled")
        form = await _parse_request_form(request)
        transcript = _normalize_turn_text(
            _first_non_empty(
                str(form.get("userPrompt") or ""),
                str(form.get("user_prompt") or ""),
                str(form.get("text") or ""),
                str(form.get("fallbackText") or ""),
                str(form.get("fallback_text") or ""),
            ),
            max_length=480,
        )
        if not transcript:
            raise HTTPException(status_code=400, detail="text is required")
        reply = resolved_voice_reply_provider.generate_reply(
            transcript=transcript,
            session=_mock_voice_proxy_session(),
            turns=[],
        )
        if not reply.text:
            raise HTTPException(status_code=502, detail="mock voice provider returned no text")
        return {
            "provider": "mock-voice-proxy",
            "model": reply.model_name or getattr(resolved_voice_reply_provider, "provider_name", "mock-voice"),
            "text": reply.text,
        }

    @app.post("/providers/twilio/voice/inbound")
    async def receive_twilio_voice_inbound(request: Request) -> Response:
        session, public_base = await _create_or_load_voice_session(request, provider_name="twilio", entrypoint="voice")
        xml = _twiml_response(
            _twiml_gather(
                action_url=_voice_turn_action_url(public_base, session.session_id),
                prompt_text=session.greeting,
            )
        )
        return Response(content=xml, media_type="application/xml")

    @app.post("/providers/twilio/sip/inbound")
    async def receive_twilio_sip_inbound(request: Request) -> Response:
        session, public_base = await _create_or_load_voice_session(request, provider_name="twilio-sip", entrypoint="sip")
        xml = _twiml_response(
            _twiml_gather(
                action_url=_voice_turn_action_url(public_base, session.session_id),
                prompt_text=session.greeting,
            )
        )
        return Response(content=xml, media_type="application/xml")

    @app.post("/providers/twilio/voice/assistant-turn")
    async def receive_twilio_voice_assistant_turn(request: Request, session_id: str) -> Response:
        session = sms_store.get_voice_session(session_id)
        if session is None:
            xml = _twiml_response(_twiml_say("This call session is no longer available."), "<Hangup/>")
            return Response(content=xml, media_type="application/xml", status_code=404)

        form = _parse_form_body(await request.body())
        transcript = _normalize_turn_text(str(form.get("SpeechResult") or form.get("speech_result") or ""), max_length=480)
        public_base = _resolve_public_base_url(request, configured_public_base_url)
        action_url = _voice_turn_action_url(public_base, session.session_id)
        if not transcript:
            xml = _twiml_response(_twiml_gather(action_url=action_url, prompt_text=resolved_voice_profile.no_speech_prompt))
            return Response(content=xml, media_type="application/xml")

        sms_store.append_voice_turn(
            session.session_id,
            role="caller",
            text=transcript,
            metadata={
                "confidence": str(form.get("Confidence") or ""),
                "provider_call_id": str(form.get("CallSid") or ""),
            },
        )
        turns = sms_store.list_voice_turns(session.session_id)

        if _should_hangup_from_text(transcript) or len(turns) >= max(1, resolved_voice_profile.max_turns * 2):
            sms_store.append_voice_turn(session.session_id, role="assistant", text=resolved_voice_profile.farewell)
            sms_store.update_voice_session_status(session.session_id, status="completed")
            xml = _twiml_response(_twiml_say(resolved_voice_profile.farewell), "<Hangup/>")
            return Response(content=xml, media_type="application/xml")

        if resolved_voice_reply_provider is None:
            sms_store.append_voice_turn(session.session_id, role="assistant", text=resolved_voice_profile.unavailable_prompt)
            xml = _twiml_response(_twiml_say(resolved_voice_profile.unavailable_prompt), "<Hangup/>")
            return Response(content=xml, media_type="application/xml")

        try:
            reply = resolved_voice_reply_provider.generate_reply(transcript=transcript, session=session, turns=turns)
        except Exception:
            sms_store.append_voice_turn(session.session_id, role="assistant", text=resolved_voice_profile.unavailable_prompt)
            xml = _twiml_response(_twiml_say(resolved_voice_profile.unavailable_prompt), "<Hangup/>")
            return Response(content=xml, media_type="application/xml")

        twiml_nodes: list[str] = []
        asset_id = ""
        if reply.audio_bytes:
            saved_asset = media_store.save(content=reply.audio_bytes, mime_type=reply.mime_type or "audio/wav")
            asset_id = saved_asset["asset_id"]
            twiml_nodes.append(_twiml_play(_voice_media_url(public_base, asset_id)))
        elif reply.text:
            twiml_nodes.append(_twiml_say(reply.text))
        else:
            twiml_nodes.append(_twiml_say(resolved_voice_profile.unavailable_prompt))

        sms_store.append_voice_turn(
            session.session_id,
            role="assistant",
            text=reply.text or resolved_voice_profile.follow_up_prompt,
            audio_asset_id=asset_id,
            metadata={"provider": reply.provider, "model_name": reply.model_name},
        )
        twiml_nodes.append(_twiml_gather(action_url=action_url, prompt_text=resolved_voice_profile.follow_up_prompt))
        xml = _twiml_response(*twiml_nodes)
        return Response(content=xml, media_type="application/xml")

    @app.get("/voice/media/{asset_id}")
    def get_voice_media(asset_id: str) -> Response:
        payload = media_store.load(asset_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="voice media asset not found")
        content, mime_type = payload
        return Response(content=content, media_type=mime_type)

    @app.get("/voice/sessions/{session_id}")
    def get_voice_session(session_id: str) -> dict[str, Any]:
        session = sms_store.get_voice_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="voice session not found")
        turns = sms_store.list_voice_turns(session_id)
        return {
            "session": session.to_dict(),
            "assistant_profile": {
                "assistant_name": resolved_voice_profile.assistant_name,
                "service_name": resolved_voice_profile.service_name,
                "website_url": resolved_voice_profile.website_url,
                "max_turns": resolved_voice_profile.max_turns,
            },
            "turn_count": len(turns),
            "turns": [turn.to_dict() for turn in turns],
        }

    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ipfs-datasets-sms-bridge")
    parser.add_argument("--db-path", default=default_sms_bridge_db_path())
    parser.add_argument("--host", default=os.getenv("IPFS_DATASETS_SMS_BRIDGE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("IPFS_DATASETS_SMS_BRIDGE_PORT", "8061")))
    parser.add_argument("--reload", action="store_true", default=_truthy(os.getenv("IPFS_DATASETS_SMS_BRIDGE_RELOAD")))
    parser.add_argument("--provider", choices=["mock", "webhook", "twilio"], default=os.getenv("IPFS_DATASETS_SMS_PROVIDER_KIND"))
    parser.add_argument("--provider-webhook-url", default=os.getenv("IPFS_DATASETS_SMS_PROVIDER_WEBHOOK_URL", ""))
    parser.add_argument("--provider-bearer-token", default=os.getenv("IPFS_DATASETS_SMS_PROVIDER_BEARER_TOKEN", ""))
    parser.add_argument("--provider-header-name", default=os.getenv("IPFS_DATASETS_SMS_PROVIDER_HTTP_HEADER_NAME", ""))
    parser.add_argument("--provider-header-value", default=os.getenv("IPFS_DATASETS_SMS_PROVIDER_HTTP_HEADER_VALUE", ""))
    parser.add_argument("--provider-timeout-seconds", type=float, default=float(os.getenv("IPFS_DATASETS_SMS_PROVIDER_TIMEOUT_SECONDS", "15")))
    parser.add_argument("--twilio-account-sid", default=os.getenv("IPFS_DATASETS_SMS_TWILIO_ACCOUNT_SID", ""))
    parser.add_argument("--twilio-auth-token", default=os.getenv("IPFS_DATASETS_SMS_TWILIO_AUTH_TOKEN", ""))
    parser.add_argument("--twilio-from-phone", default=os.getenv("IPFS_DATASETS_SMS_TWILIO_FROM_PHONE", ""))
    parser.add_argument("--twilio-messaging-service-sid", default=os.getenv("IPFS_DATASETS_SMS_TWILIO_MESSAGING_SERVICE_SID", ""))
    parser.add_argument("--twilio-status-callback-url", default=os.getenv("IPFS_DATASETS_SMS_TWILIO_STATUS_CALLBACK_URL", ""))
    parser.add_argument("--call-provider", choices=["mock", "webhook", "twilio"], default=os.getenv("IPFS_DATASETS_CALL_PROVIDER_KIND"))
    parser.add_argument("--call-provider-webhook-url", default=os.getenv("IPFS_DATASETS_CALL_PROVIDER_WEBHOOK_URL", ""))
    parser.add_argument("--call-provider-bearer-token", default=os.getenv("IPFS_DATASETS_CALL_PROVIDER_BEARER_TOKEN", ""))
    parser.add_argument("--call-provider-header-name", default=os.getenv("IPFS_DATASETS_CALL_PROVIDER_HTTP_HEADER_NAME", ""))
    parser.add_argument("--call-provider-header-value", default=os.getenv("IPFS_DATASETS_CALL_PROVIDER_HTTP_HEADER_VALUE", ""))
    parser.add_argument("--call-provider-timeout-seconds", type=float, default=float(os.getenv("IPFS_DATASETS_CALL_PROVIDER_TIMEOUT_SECONDS", "20")))
    parser.add_argument("--call-twilio-account-sid", default=os.getenv("IPFS_DATASETS_CALL_TWILIO_ACCOUNT_SID", ""))
    parser.add_argument("--call-twilio-auth-token", default=os.getenv("IPFS_DATASETS_CALL_TWILIO_AUTH_TOKEN", ""))
    parser.add_argument("--call-twilio-from-phone", default=os.getenv("IPFS_DATASETS_CALL_TWILIO_FROM_PHONE", ""))
    parser.add_argument("--call-twilio-status-callback-url", default=os.getenv("IPFS_DATASETS_CALL_TWILIO_STATUS_CALLBACK_URL", ""))
    parser.add_argument("--voice-public-base-url", default=os.getenv("IPFS_DATASETS_VOICE_PUBLIC_BASE_URL", ""))
    parser.add_argument("--voice-provider", choices=["mock", "remote-proxy"], default=os.getenv("IPFS_DATASETS_VOICE_REPLY_PROVIDER_KIND"))
    parser.add_argument("--voice-proxy-base-url", default=os.getenv("IPFS_DATASETS_VOICE_PROXY_BASE_URL", ""))
    parser.add_argument("--voice-proxy-infer-url", default=os.getenv("IPFS_DATASETS_VOICE_PROXY_INFER_URL", ""))
    parser.add_argument("--voice-proxy-tts-url", default=os.getenv("IPFS_DATASETS_VOICE_PROXY_TTS_URL", ""))
    parser.add_argument("--voice-proxy-timeout-seconds", type=float, default=float(os.getenv("IPFS_DATASETS_VOICE_PROXY_TIMEOUT_SECONDS", "45")))
    parser.add_argument("--voice-mock-reply-text", default=os.getenv("IPFS_DATASETS_VOICE_MOCK_REPLY_TEXT", ""))
    parser.add_argument("--voice-agent-name", default=os.getenv("IPFS_DATASETS_VOICE_AGENT_NAME", "Abby"))
    parser.add_argument("--voice-service-name", default=os.getenv("IPFS_DATASETS_VOICE_SERVICE_NAME", "211 AI"))
    parser.add_argument("--voice-greeting", default=os.getenv("IPFS_DATASETS_VOICE_GREETING", _DEFAULT_VOICE_GREETING))
    parser.add_argument("--voice-no-speech-prompt", default=os.getenv("IPFS_DATASETS_VOICE_NO_SPEECH_PROMPT", _DEFAULT_VOICE_NO_SPEECH_PROMPT))
    parser.add_argument("--voice-follow-up-prompt", default=os.getenv("IPFS_DATASETS_VOICE_FOLLOW_UP_PROMPT", _DEFAULT_VOICE_FOLLOW_UP))
    parser.add_argument("--voice-farewell", default=os.getenv("IPFS_DATASETS_VOICE_FAREWELL", _DEFAULT_VOICE_FAREWELL))
    parser.add_argument("--voice-unavailable-prompt", default=os.getenv("IPFS_DATASETS_VOICE_UNAVAILABLE_PROMPT", _DEFAULT_VOICE_UNAVAILABLE_PROMPT))
    parser.add_argument("--voice-website-url", default=os.getenv("IPFS_DATASETS_VOICE_WEBSITE_URL", "https://211-ai.com"))
    parser.add_argument("--voice-system-prompt-append", default=os.getenv("IPFS_DATASETS_VOICE_SYSTEM_PROMPT_APPEND", ""))
    parser.add_argument("--voice-max-turns", type=int, default=int(os.getenv("IPFS_DATASETS_VOICE_MAX_TURNS", "8")))
    parser.add_argument("--inbound-forward-url", default=os.getenv("IPFS_DATASETS_SMS_INBOUND_FORWARD_URL", ""))
    parser.add_argument("--inbound-forward-bearer-token", default=os.getenv("IPFS_DATASETS_SMS_INBOUND_FORWARD_BEARER_TOKEN", ""))
    parser.add_argument("--inbound-forward-header-name", default=os.getenv("IPFS_DATASETS_SMS_INBOUND_FORWARD_HTTP_HEADER_NAME", ""))
    parser.add_argument("--inbound-forward-header-value", default=os.getenv("IPFS_DATASETS_SMS_INBOUND_FORWARD_HTTP_HEADER_VALUE", ""))
    parser.add_argument("--inbound-forward-timeout-seconds", type=float, default=float(os.getenv("IPFS_DATASETS_SMS_INBOUND_FORWARD_TIMEOUT_SECONDS", "15")))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if uvicorn is None:  # pragma: no cover - optional dependency
        raise RuntimeError("uvicorn is required to run the SMS bridge")

    parser = build_parser()
    args = parser.parse_args(argv)

    provider = build_sms_provider(
        provider_kind=args.provider,
        webhook_url=args.provider_webhook_url,
        bearer_token=args.provider_bearer_token,
        header_name=args.provider_header_name,
        header_value=args.provider_header_value,
        account_sid=args.twilio_account_sid,
        auth_token=args.twilio_auth_token,
        from_phone=args.twilio_from_phone,
        messaging_service_sid=args.twilio_messaging_service_sid,
        status_callback_url=args.twilio_status_callback_url,
        timeout_seconds=args.provider_timeout_seconds,
    )
    call_provider = build_call_provider(
        provider_kind=args.call_provider,
        webhook_url=args.call_provider_webhook_url,
        bearer_token=args.call_provider_bearer_token,
        header_name=args.call_provider_header_name,
        header_value=args.call_provider_header_value,
        account_sid=args.call_twilio_account_sid,
        auth_token=args.call_twilio_auth_token,
        from_phone=args.call_twilio_from_phone,
        status_callback_url=args.call_twilio_status_callback_url,
        timeout_seconds=args.call_provider_timeout_seconds,
    )
    voice_profile = build_voice_assistant_profile(
        assistant_name=args.voice_agent_name,
        service_name=args.voice_service_name,
        greeting=args.voice_greeting,
        no_speech_prompt=args.voice_no_speech_prompt,
        follow_up_prompt=args.voice_follow_up_prompt,
        farewell=args.voice_farewell,
        unavailable_prompt=args.voice_unavailable_prompt,
        website_url=args.voice_website_url,
        system_prompt_append=args.voice_system_prompt_append,
        max_turns=args.voice_max_turns,
    )
    voice_reply_provider = build_voice_reply_provider(
        provider_kind=args.voice_provider,
        base_url=args.voice_proxy_base_url,
        infer_url=args.voice_proxy_infer_url,
        tts_url=args.voice_proxy_tts_url,
        timeout_seconds=args.voice_proxy_timeout_seconds,
        mock_reply_text=args.voice_mock_reply_text,
        assistant_profile=voice_profile,
    )
    forwarder = build_inbound_forwarder(
        webhook_url=args.inbound_forward_url,
        bearer_token=args.inbound_forward_bearer_token,
        header_name=args.inbound_forward_header_name,
        header_value=args.inbound_forward_header_value,
        timeout_seconds=args.inbound_forward_timeout_seconds,
    )
    app = create_sms_bridge_app(
        repository=SmsBridgeStore(args.db_path),
        provider=provider,
        inbound_forwarder=forwarder,
        call_provider=call_provider,
        voice_reply_provider=voice_reply_provider,
        voice_profile=voice_profile,
        public_base_url=args.voice_public_base_url,
    )
    uvicorn.run(app, host=args.host, port=args.port, reload=bool(args.reload))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())