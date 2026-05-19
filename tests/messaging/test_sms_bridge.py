from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

from fastapi.testclient import TestClient

from ipfs_datasets_py.messaging import sms_bridge
from ipfs_datasets_py.messaging.sms_bridge import (
    MockVoiceReplyProvider,
    RemoteVoiceProxyProvider,
    SmsBridgeStore,
    VoiceAssistantProfile,
    VoiceCallSessionRecord,
    VoiceReplyResult,
    build_call_provider,
    build_email_provider,
    build_parser,
    build_sms_provider,
    build_voice_reply_provider,
    create_sms_bridge_app,
)


class StubProvider:
    provider_name = "stub"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_sms(
        self,
        *,
        to_phone: str,
        message: str,
        from_phone: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "to_phone": to_phone,
                "message": message,
                "from_phone": from_phone,
                "metadata": dict(metadata or {}),
            }
        )
        return {
            "provider": self.provider_name,
            "provider_status": "queued",
            "provider_message_id": "SM-outbound-1",
        }


class StubForwarder:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def forward(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        self.payloads.append(normalized)
        return {"accepted": True}


class StubCallProvider:
    provider_name = "stub-call"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_call(
        self,
        *,
        to_phone: str,
        script: str,
        from_phone: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "to_phone": to_phone,
                "script": script,
                "from_phone": from_phone,
                "metadata": dict(metadata or {}),
            }
        )
        return {
            "provider": self.provider_name,
            "provider_status": "queued",
            "provider_call_id": "CA-outbound-1",
        }


class StubEmailProvider:
    provider_name = "stub-email"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append(
            {
                "to_email": to_email,
                "subject": subject,
                "body": body,
                "from_email": from_email,
                "attachment_base64": attachment_base64,
                "attachment_filename": attachment_filename,
                "attachment_mime_type": attachment_mime_type,
                "metadata": dict(metadata or {}),
            }
        )
        return {
            "provider": self.provider_name,
            "provider_status": "queued",
            "provider_message_id": "EM-outbound-1",
        }


class StubVoiceReplyProvider:
    provider_name = "stub-voice-proxy"

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def generate_reply(self, *, transcript: str, session, turns) -> VoiceReplyResult:  # type: ignore[no-untyped-def]
        self.requests.append(
            {
                "transcript": transcript,
                "session_id": session.session_id,
                "turn_count": len(turns),
            }
        )
        return VoiceReplyResult(
            provider=self.provider_name,
            model_name="stub-voice-model",
            text="I can help you find shelter tonight.",
            audio_bytes=b"RIFFstubWAVE",
            mime_type="audio/wav",
            metadata={"latency": {"total_ms": 7}},
        )


def _client(
    tmp_path: Path,
) -> tuple[TestClient, SmsBridgeStore, StubProvider, StubForwarder, StubCallProvider, StubEmailProvider, StubVoiceReplyProvider]:
    store = SmsBridgeStore(str(tmp_path / "sms_bridge.duckdb"))
    provider = StubProvider()
    forwarder = StubForwarder()
    call_provider = StubCallProvider()
    email_provider = StubEmailProvider()
    voice_reply_provider = StubVoiceReplyProvider()
    app = create_sms_bridge_app(
        repository=store,
        provider=provider,
        email_provider=email_provider,
        inbound_forwarder=forwarder,
        call_provider=call_provider,
        voice_reply_provider=voice_reply_provider,
        public_base_url="https://211-ai.com/messaging",
    )
    return TestClient(app, raise_server_exceptions=False), store, provider, forwarder, call_provider, email_provider, voice_reply_provider


def test_sms_bridge_records_outbound_and_twilio_inbound(tmp_path: Path) -> None:
    client, store, provider, forwarder, _, _, _ = _client(tmp_path)

    outbound_response = client.post(
        "/messages/sms/outbound",
        json={
            "to_phone": "503-555-0199",
            "message": "Shelter check-in reminder",
            "wallet_id": "wallet-123",
            "external_reference": "sms-notification-1",
            "metadata": {"case_id": "case-7"},
        },
    )
    assert outbound_response.status_code == 200, outbound_response.text
    outbound_body = outbound_response.json()
    assert outbound_body["provider"] == "stub"
    assert outbound_body["provider_message_id"] == "SM-outbound-1"
    assert outbound_body["message"]["direction"] == "outbound"
    assert outbound_body["message"]["to_phone"] == "+15035550199"
    assert provider.calls == [
        {
            "to_phone": "503-555-0199",
            "message": "Shelter check-in reminder",
            "from_phone": "",
            "metadata": {"case_id": "case-7"},
        }
    ]

    inbound_response = client.post(
        "/providers/twilio/inbound",
        data={
            "AccountSid": "AC123",
            "Body": "I need a bed tonight",
            "From": "+15035550199",
            "MessageSid": "SM-inbound-1",
            "NumMedia": "0",
            "To": "+15035550100",
        },
    )
    assert inbound_response.status_code == 200, inbound_response.text
    assert inbound_response.headers["content-type"].startswith("application/xml")
    assert "<Message>" in inbound_response.text
    assert "this is Abby from 211 AI" in inbound_response.text

    listed_messages = store.list_messages(limit=10)
    assert len(listed_messages) == 3
    inbound_message = next(message for message in listed_messages if message.direction == "inbound")
    assert inbound_message.provider == "twilio"
    assert inbound_message.provider_message_id == "SM-inbound-1"
    assert inbound_message.from_phone == "+15035550199"
    assert inbound_message.message == "I need a bed tonight"
    assert inbound_message.wallet_id == "wallet-123"
    assert inbound_message.external_reference == "sms-notification-1"
    reply_message = next(
        message
        for message in listed_messages
        if message.direction == "outbound" and message.provider == "twilio-twiml"
    )
    assert reply_message.to_phone == "+15035550199"
    assert reply_message.from_phone == "+15035550100"
    assert reply_message.wallet_id == "wallet-123"
    assert reply_message.metadata["reply_to_provider_message_id"] == "SM-inbound-1"
    assert forwarder.payloads[0]["direction"] == "inbound"
    assert forwarder.payloads[0]["provider_message_id"] == "SM-inbound-1"
    assert forwarder.payloads[0]["wallet_id"] == "wallet-123"
    assert forwarder.payloads[0]["external_reference"] == "sms-notification-1"

    filtered_response = client.get("/messages/sms", params={"direction": "inbound", "limit": 10})
    assert filtered_response.status_code == 200, filtered_response.text
    assert filtered_response.json()["count"] == 1


def test_sms_bridge_updates_twilio_delivery_status(tmp_path: Path) -> None:
    client, _, _, _, _, _, _ = _client(tmp_path)

    outbound_response = client.post(
        "/messages/sms/outbound",
        json={
            "to_phone": "+15035550100",
            "message": "Status callback test",
        },
    )
    assert outbound_response.status_code == 200, outbound_response.text

    status_response = client.post(
        "/providers/twilio/status",
        data={
            "MessageSid": "SM-outbound-1",
            "MessageStatus": "delivered",
        },
    )
    assert status_response.status_code == 200, status_response.text
    status_body = status_response.json()
    assert status_body["updated"] is True
    assert status_body["message"]["status"] == "delivered"

    listed_response = client.get("/messages/sms", params={"status": "delivered", "limit": 10})
    assert listed_response.status_code == 200, listed_response.text
    assert listed_response.json()["count"] == 1


def test_sms_bridge_records_outbound_call_and_twilio_voice_status(tmp_path: Path) -> None:
    client, store, _, _, call_provider, _, _ = _client(tmp_path)

    outbound_response = client.post(
        "/messages/calls/outbound",
        json={
            "to_phone": "503-555-0101",
            "script": "This is a check-in call from 211 AI.",
            "wallet_id": "wallet-voice-1",
            "metadata": {"case_id": "case-voice-7"},
        },
    )
    assert outbound_response.status_code == 200, outbound_response.text
    outbound_body = outbound_response.json()
    assert outbound_body["provider"] == "stub-call"
    assert outbound_body["provider_call_id"] == "CA-outbound-1"
    assert outbound_body["provider_message_id"] == "CA-outbound-1"
    assert outbound_body["call"]["to_phone"] == "+15035550101"
    assert call_provider.calls == [
        {
            "to_phone": "503-555-0101",
            "script": "This is a check-in call from 211 AI.",
            "from_phone": "",
            "metadata": {"case_id": "case-voice-7"},
        }
    ]

    status_response = client.post(
        "/providers/twilio/voice/status",
        data={
            "CallSid": "CA-outbound-1",
            "CallStatus": "completed",
            "CallDuration": "14",
            "To": "+15035550101",
            "From": "+15035550100",
        },
    )
    assert status_response.status_code == 200, status_response.text
    status_body = status_response.json()
    assert status_body["updated"] is True
    assert status_body["call"]["status"] == "completed"

    calls = store.list_calls(limit=10)
    assert len(calls) == 1
    assert calls[0].provider_call_id == "CA-outbound-1"
    assert calls[0].status == "completed"
    assert calls[0].metadata["call_duration"] == "14"

    listed_response = client.get("/messages/calls", params={"status": "completed", "limit": 10})
    assert listed_response.status_code == 200, listed_response.text
    assert listed_response.json()["count"] == 1


def test_voice_gateway_accepts_inbound_call_and_serves_generated_audio(tmp_path: Path) -> None:
    client, _, _, _, _, _, voice_reply_provider = _client(tmp_path)

    inbound_response = client.post(
        "/providers/twilio/voice/inbound",
        data={
            "CallSid": "CA-inbound-voice-1",
            "From": "+15035550199",
            "To": "+15035550100",
        },
    )
    assert inbound_response.status_code == 200, inbound_response.text
    inbound_xml = inbound_response.text
    assert "https://211-ai.com/messaging/providers/twilio/voice/assistant-turn" in inbound_xml
    assert 'timeout="3"' in inbound_xml
    assert 'speechTimeout="1"' in inbound_xml
    session_match = re.search(r"session_id=([^&\"]+)", inbound_xml)
    assert session_match, inbound_xml
    session_id = session_match.group(1)

    turn_response = client.post(
        f"/providers/twilio/voice/assistant-turn?session_id={session_id}",
        data={
            "CallSid": "CA-inbound-voice-1",
            "SpeechResult": "I need a shelter bed tonight",
            "Confidence": "0.91",
        },
    )
    assert turn_response.status_code == 200, turn_response.text
    turn_xml = turn_response.text
    assert voice_reply_provider.requests == [
        {
            "transcript": "I need a shelter bed tonight",
            "session_id": session_id,
            "turn_count": 1,
        }
    ]
    media_match = re.search(r"https://211-ai\.com/messaging(/voice/media/[^<]+)", turn_xml)
    assert media_match, turn_xml

    media_response = client.get(media_match.group(1))
    assert media_response.status_code == 200, media_response.text
    assert media_response.headers["content-type"].startswith("audio/wav")
    assert media_response.content == b"RIFFstubWAVE"

    session_response = client.get(f"/voice/sessions/{session_id}")
    assert session_response.status_code == 200, session_response.text
    session_body = session_response.json()
    assert session_body["session"]["provider_call_id"] == "CA-inbound-voice-1"
    assert session_body["turn_count"] == 2
    assert session_body["turns"][0]["role"] == "caller"
    assert session_body["turns"][1]["role"] == "assistant"
    assert session_body["turns"][1]["audio_asset_id"]
    assert session_body["turns"][1]["metadata"]["latency"]["total_ms"] >= 0
    assert session_body["turns"][1]["metadata"]["provider_latency"]["total_ms"] >= 0

    status_response = client.post(
        "/providers/twilio/voice/status",
        data={
            "CallSid": "CA-inbound-voice-1",
            "CallStatus": "completed",
            "CallDuration": "32",
        },
    )
    assert status_response.status_code == 200, status_response.text
    status_body = status_response.json()
    assert status_body["updated"] is True
    assert status_body["voice_session_updated"] is True
    assert status_body["voice_session"]["status"] == "completed"


def test_voice_gateway_can_return_openai_realtime_media_stream_twiml(tmp_path: Path) -> None:
    client, _, _, _, _, _, _ = _client(tmp_path)

    response = client.post(
        "/providers/twilio/voice/openai-realtime/inbound",
        data={
            "CallSid": "CA-openai-realtime-1",
            "From": "+15035550199",
            "To": "+15035550100",
        },
    )

    assert response.status_code == 200, response.text
    xml = response.text
    assert "<Connect><Stream" in xml
    assert "wss://211-ai.com/messaging/providers/twilio/voice/openai-realtime-stream" in xml
    assert "session_id=" in xml
    assert 'name="assistant" value="Abby"' in xml


def test_openai_realtime_session_update_uses_twilio_audio_formats(monkeypatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_OPENAI_REALTIME_MODEL", "gpt-realtime")
    monkeypatch.setenv("IPFS_DATASETS_OPENAI_REALTIME_VOICE", "cedar")

    event = sms_bridge._openai_session_update_event(VoiceAssistantProfile(assistant_name="Abby"))

    assert event["type"] == "session.update"
    session = event["session"]
    assert session["model"] == "gpt-realtime"
    assert session["output_modalities"] == ["audio"]
    assert session["audio"]["input"]["format"] == {"type": "audio/pcmu"}
    assert session["audio"]["output"]["format"] == {"type": "audio/pcmu"}
    assert session["audio"]["output"]["voice"] == "cedar"
    assert session["audio"]["input"]["turn_detection"]["type"] == "server_vad"


def test_mock_browser_voice_proxy_routes_return_text_payloads(tmp_path: Path) -> None:
    store = SmsBridgeStore(str(tmp_path / "mock_voice_proxy.duckdb"))
    app = create_sms_bridge_app(
        repository=store,
        voice_reply_provider=MockVoiceReplyProvider(
            assistant_profile=VoiceAssistantProfile(assistant_name="Abby", service_name="211 AI")
        ),
        public_base_url="https://211-ai.com/messaging",
    )
    client = TestClient(app, raise_server_exceptions=False)

    tts_response = client.post(
        "/voice/tts",
        data={"text": "Neighborhood Pantry can help with food today."},
    )
    assert tts_response.status_code == 200, tts_response.text
    assert tts_response.json() == {
        "provider": "mock-voice-proxy",
        "model": "mock-voice",
        "text": "Neighborhood Pantry can help with food today.",
    }

    infer_response = client.post(
        "/voice/infer",
        data={
            "text": "Where can I find shelter tonight?",
            "userPrompt": "Where can I find shelter tonight?",
            "fallbackText": "I can help you find shelter tonight.",
        },
        files={"audio": ("input.wav", b"RIFFmockWAVE", "audio/wav")},
    )
    assert infer_response.status_code == 200, infer_response.text
    infer_body = infer_response.json()
    assert infer_body["provider"] == "mock-voice-proxy"
    assert infer_body["model"] == "mock-voice"
    assert "Where can I find shelter tonight?" in infer_body["text"]


def test_remote_voice_proxy_resolves_relative_urls(monkeypatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_VOICE_REPLY_PROVIDER_KIND", "remote-proxy")
    monkeypatch.setenv("IPFS_DATASETS_VOICE_PROXY_BASE_URL", "http://wallet-api:8000")
    monkeypatch.setenv("IPFS_DATASETS_VOICE_PROXY_INFER_URL", "/voice/indextts/infer")
    monkeypatch.setenv("IPFS_DATASETS_VOICE_PROXY_TTS_URL", "/voice/indextts/tts")

    provider = build_voice_reply_provider()

    assert provider is not None
    assert getattr(provider, "infer_url") == "http://wallet-api:8000/voice/indextts/infer"
    assert getattr(provider, "tts_url") == "http://wallet-api:8000/voice/indextts/tts"


def test_remote_voice_proxy_uses_configured_tts_reference_instead_of_silent_upload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_request(url, *, body, headers, timeout_seconds):
        captured["body"] = body
        payload = {
            "text": "I can help with food support.",
            "audioBase64": base64.b64encode(b"RIFFstubWAVE").decode("ascii"),
            "mimeType": "audio/wav",
            "model": "IndexTTS",
            "latency": {"total_ms": 5},
        }
        return 200, json.dumps(payload).encode("utf-8"), "application/json"

    monkeypatch.setattr("ipfs_datasets_py.messaging.sms_bridge._perform_request_raw", fake_request)
    provider = RemoteVoiceProxyProvider(infer_url="http://wallet-api:8000/voice/indextts/infer")

    reply = provider.generate_reply(
        transcript="I need food help",
        session=VoiceCallSessionRecord(
            session_id="session-1",
            provider="twilio",
            provider_call_id="call-1",
            status="active",
            from_phone="+15035550199",
            to_phone="+15035550100",
            assistant_name="Abby",
            service_name="211 AI",
            greeting="Hello",
        ),
        turns=[],
    )

    assert reply.audio_bytes == b"RIFFstubWAVE"
    assert b'name="audio"; filename="input.wav"' not in captured["body"]


def test_browser_voice_proxy_routes_are_unavailable_without_mock_provider(tmp_path: Path) -> None:
    client, _, _, _, _, _, _ = _client(tmp_path)

    tts_response = client.post("/voice/tts", data={"text": "hello"})
    assert tts_response.status_code == 503, tts_response.text

    infer_response = client.post(
        "/voice/infer",
        data={"text": "hello"},
        files={"audio": ("input.wav", b"RIFFmockWAVE", "audio/wav")},
    )
    assert infer_response.status_code == 503, infer_response.text


def test_email_bridge_records_outbound_email(tmp_path: Path) -> None:
    client, store, _, _, _, email_provider, _ = _client(tmp_path)

    attachment_payload = base64.b64encode(b'{"bundle":true}').decode("ascii")
    outbound_response = client.post(
        "/messages/email/outbound",
        json={
            "to_email": "missing@police.portlandoregon.gov",
            "subject": "Missing person report dead drop bundle",
            "body": "Please review attached wallet bundle.",
            "from_email": "abby@example.org",
            "wallet_id": "wallet-dead-drop-1",
            "attachment_base64": attachment_payload,
            "attachment_filename": "dead-drop.json",
            "attachment_mime_type": "application/json",
            "metadata": {"case_id": "case-email-7"},
        },
    )

    assert outbound_response.status_code == 200, outbound_response.text
    outbound_body = outbound_response.json()
    assert outbound_body["provider"] == "stub-email"
    assert outbound_body["provider_message_id"] == "EM-outbound-1"
    assert email_provider.calls == [
        {
            "to_email": "missing@police.portlandoregon.gov",
            "subject": "Missing person report dead drop bundle",
            "body": "Please review attached wallet bundle.",
            "from_email": "abby@example.org",
            "attachment_base64": attachment_payload,
            "attachment_filename": "dead-drop.json",
            "attachment_mime_type": "application/json",
            "metadata": {"case_id": "case-email-7"},
        }
    ]

    messages = store.list_email_messages(limit=10)
    assert len(messages) == 1
    assert messages[0].provider_message_id == "EM-outbound-1"
    assert messages[0].to_email == "missing@police.portlandoregon.gov"
    assert messages[0].subject == "Missing person report dead drop bundle"
    assert messages[0].metadata["attachment_filename"] == "dead-drop.json"
    assert messages[0].metadata["attachment_bytes"] == len(b'{"bundle":true}')

    listed_response = client.get("/messages/email", params={"status": "queued", "limit": 10})
    assert listed_response.status_code == 200, listed_response.text
    assert listed_response.json()["count"] == 1


def test_bridge_builders_support_mock_providers_without_external_credentials() -> None:
    parsed = build_parser().parse_args(["--provider", "mock", "--call-provider", "mock", "--voice-provider", "mock"])
    assert parsed.provider == "mock"
    assert parsed.call_provider == "mock"
    assert parsed.voice_provider == "mock"

    sms_provider = build_sms_provider(provider_kind="mock", from_phone="+15035550100")
    assert sms_provider is not None
    sms_delivery = sms_provider.send_sms(to_phone="+15035550199", message="Mock SMS", metadata={"case_id": "case-1"})
    assert sms_delivery["provider"] == "mock"
    assert sms_delivery["provider_message_id"].startswith("mock-sms-")

    email_provider = build_email_provider(provider_kind="mock", from_email="abby@example.org")
    assert email_provider is not None
    email_delivery = email_provider.send_email(
        to_email="person@example.org",
        subject="Mock email",
        body="Development mode",
        metadata={"case_id": "case-2"},
    )
    assert email_delivery["provider"] == "mock"
    assert email_delivery["provider_message_id"].startswith("mock-email-")

    call_provider = build_call_provider(provider_kind="mock", from_phone="+15035550100")
    assert call_provider is not None
    call_delivery = call_provider.send_call(
        to_phone="+15035550199",
        script="Mock call",
        metadata={"case_id": "case-3"},
    )
    assert call_delivery["provider"] == "mock"
    assert call_delivery["provider_call_id"].startswith("mock-call-")

    voice_provider = build_voice_reply_provider(
        provider_kind="mock",
        mock_reply_text="Local mock voice reply",
        assistant_profile=VoiceAssistantProfile(assistant_name="Abby"),
    )
    assert voice_provider is not None
    reply = voice_provider.generate_reply(
        transcript="I need help tonight",
        session=VoiceCallSessionRecord(
            session_id="session-1",
            provider="mock",
            provider_call_id="call-1",
            status="active",
            from_phone="+15035550199",
            to_phone="+15035550100",
            assistant_name="Abby",
            service_name="211 AI",
            greeting="Hello",
        ),
        turns=[],
    )
    assert reply.provider == "mock-voice"
    assert reply.model_name == "mock-voice"
    assert reply.text == "Local mock voice reply"
