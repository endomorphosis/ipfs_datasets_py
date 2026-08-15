"""Speech and microphone intent normalization (UIR-051).

SpeechInputAdapter@1 converts injected ASR transcript/intent candidates into
canonical interaction events. Raw microphone PCM, continuous audio streams,
and model weights remain outside UIIR.

Never decides policy or authorization. Low-confidence or multi-target high-risk
commands require clarification. Transcripts cannot inject instructions or
grants. Wake/recording consent and purpose must be explicit. Cancel/confirm
utterances map to the same EventKind values as other modalities.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ...schema import UIIRValidationError
from ..events import (
    CanonicalInteractionEvent,
    EventKind,
    EventProvenance,
    validate_event,
)

SPEECH_ADAPTER_ID: Final = "runtime.input.speech@1"
SPEECH_INPUT_ADAPTER_INTERFACE: Final = "SpeechInputAdapter@1"
CAPABILITY_SPEECH: Final = "speech"
CAPABILITY_MICROPHONE: Final = "microphone"

# Default confidence below which clarification is required.
DEFAULT_CONFIDENCE_FLOOR: Final = 0.55

# Utterance tokens that map to shared modality actions (cancel/confirm).
_CANCEL_TOKENS: Final = frozenset(
    {
        "cancel",
        "abort",
        "stop",
        "nevermind",
        "never mind",
        "dismiss",
    }
)
_CONFIRM_TOKENS: Final = frozenset(
    {
        "confirm",
        "yes",
        "ok",
        "okay",
        "approve",
        "accept",
        "proceed",
    }
)

_FORBIDDEN_TRANSCRIPT_MARKERS: Final = (
    "ignore previous",
    "system:",
    "authority:",
    "grant:",
    "<|",
    "[[",
    "BEGIN INSTRUCTION",
)

_FORBIDDEN_RAW_KEYS: Final = frozenset(
    {
        "pcm",
        "raw_audio",
        "audio_bytes",
        "waveform",
        "microphone_pcm",
        "authorization",
        "authority",
        "grant",
        "password",
        "secret",
        "token",
        "private_key",
    }
)


@dataclass(frozen=True, slots=True)
class SpeechCandidate:
    """One ASR/intent candidate; never authority by itself."""

    text: str
    confidence: float
    language: str = "und"
    intent_id: str = ""
    target_component_ids: tuple[str, ...] = ()
    risk_hint: str = "low"  # low | medium | high | critical


@dataclass(frozen=True, slots=True)
class SpeechNormalizationResult:
    """Normalized speech intake result."""

    event: CanonicalInteractionEvent | None
    requires_clarification: bool
    clarification_reason: str = ""
    alternatives: tuple[SpeechCandidate, ...] = ()
    adapter_id: str = SPEECH_ADAPTER_ID
    interface: str = SPEECH_INPUT_ADAPTER_INTERFACE


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _reject_instruction_injection(text: str) -> None:
    lowered = text.lower()
    for marker in _FORBIDDEN_TRANSCRIPT_MARKERS:
        if marker.lower() in lowered:
            raise UIIRValidationError(
                f"Speech transcript must not inject instructions or grants "
                f"(marker {marker!r})"
            )


def _parse_candidates(raw: Mapping[str, Any]) -> tuple[SpeechCandidate, ...]:
    items = raw.get("candidates") or raw.get("alternatives") or ()
    if not items and (raw.get("text") or raw.get("transcript")):
        items = (
            {
                "text": raw.get("text") or raw.get("transcript"),
                "confidence": raw.get("confidence", 1.0),
                "language": raw.get("language", "und"),
                "intent_id": raw.get("intent_id", ""),
                "target_component_ids": raw.get("target_component_ids")
                or (
                    (raw.get("target_component_id"),)
                    if raw.get("target_component_id")
                    else ()
                ),
                "risk_hint": raw.get("risk_hint", "low"),
            },
        )
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise UIIRValidationError("speech candidates must be a sequence")

    out: list[SpeechCandidate] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise UIIRValidationError("each speech candidate must be a mapping")
        text = str(item.get("text") or item.get("transcript") or "").strip()
        if not text:
            raise UIIRValidationError("speech candidate text must not be empty")
        _reject_instruction_injection(text)
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError) as exc:
            raise UIIRValidationError("speech confidence must be a number") from exc
        if not (0.0 <= confidence <= 1.0):
            raise UIIRValidationError("speech confidence must be in [0, 1]")
        targets_raw = item.get("target_component_ids") or ()
        if item.get("target_component_id") and not targets_raw:
            targets_raw = (item.get("target_component_id"),)
        if not isinstance(targets_raw, Sequence) or isinstance(targets_raw, (str, bytes)):
            raise UIIRValidationError("target_component_ids must be a sequence")
        targets = tuple(str(t).strip() for t in targets_raw if str(t).strip())
        risk = str(item.get("risk_hint") or "low").strip().lower()
        if risk not in {"low", "medium", "high", "critical"}:
            raise UIIRValidationError(f"Unsupported risk_hint {risk!r}")
        out.append(
            SpeechCandidate(
                text=text,
                confidence=confidence,
                language=str(item.get("language") or "und").strip() or "und",
                intent_id=str(item.get("intent_id") or "").strip(),
                target_component_ids=targets,
                risk_hint=risk,
            )
        )
    if not out:
        raise UIIRValidationError("speech input requires at least one candidate")
    # Rank by confidence descending for deterministic primary selection.
    return tuple(sorted(out, key=lambda c: (-c.confidence, c.text)))


def _kind_for_candidate(candidate: SpeechCandidate) -> EventKind:
    token = _normalize_text(candidate.text)
    if token in _CANCEL_TOKENS or token.startswith("cancel "):
        return EventKind.CANCEL
    if token in _CONFIRM_TOKENS:
        return EventKind.CONFIRM
    if candidate.intent_id in {"cancel", "abort"}:
        return EventKind.CANCEL
    if candidate.intent_id in {"confirm", "approve"}:
        return EventKind.CONFIRM
    if candidate.intent_id in {"navigate", "go"}:
        return EventKind.NAVIGATE
    if candidate.intent_id in {"select", "choose"}:
        return EventKind.SELECT
    if candidate.intent_id in {"input", "dictate", "type"}:
        return EventKind.INPUT_VALUE
    return EventKind.ACTIVATE


def _redact_payload(raw: Mapping[str, Any], candidates: Sequence[SpeechCandidate]) -> Mapping[str, Any]:
    lowered = {str(k).lower() for k in raw}
    bad = lowered & _FORBIDDEN_RAW_KEYS
    if bad:
        raise UIIRValidationError(
            "speech raw payload contains forbidden audio/secret keys: "
            + ", ".join(sorted(bad))
        )
    safe: dict[str, Any] = {
        "language": candidates[0].language if candidates else "und",
        "wake_word": bool(raw.get("wake_word") or raw.get("wake_detected")),
        "purpose": str(raw.get("purpose") or raw.get("recording_purpose") or ""),
        "freshness_ms": int(raw.get("freshness_ms") or raw.get("age_ms") or 0),
        "audio_evidence_ref": str(
            raw.get("audio_evidence_ref") or raw.get("redacted_audio_ref") or ""
        ),
        "candidate_count": len(candidates),
        "primary_text": candidates[0].text if candidates else "",
        "primary_confidence": candidates[0].confidence if candidates else 0.0,
        "alternatives": [
            {
                "text": c.text,
                "confidence": c.confidence,
                "language": c.language,
                "intent_id": c.intent_id,
                "risk_hint": c.risk_hint,
            }
            for c in candidates[:5]
        ],
    }
    # Explicitly never include raw audio.
    return MappingProxyType(safe)


def normalize_speech_input(
    raw: Mapping[str, Any],
    *,
    event_id: str,
    target_component_id: str = "",
    timestamp_ms: int,
    sequence: int = 0,
    provenance: EventProvenance = EventProvenance.HUMAN,
    consent_ok: bool | None = None,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> SpeechNormalizationResult:
    """Normalize injected ASR candidates into a canonical event or clarification.

    Parameters
    ----------
    raw:
        Injected speech intake mapping. Must not contain raw PCM/audio bytes.
    consent_ok:
        Explicit recording/wake consent. If None, read from raw
        (``consent_ok`` / ``recording_consent`` / ``wake_consent``).
    """

    if not isinstance(raw, Mapping):
        raise UIIRValidationError("speech input raw must be a mapping")
    if not event_id.strip():
        raise UIIRValidationError("event_id must not be empty")
    if timestamp_ms < 0:
        raise UIIRValidationError("timestamp_ms must be non-negative")

    if consent_ok is None:
        consent_ok = bool(
            raw.get("consent_ok")
            if "consent_ok" in raw
            else raw.get("recording_consent")
            if "recording_consent" in raw
            else raw.get("wake_consent")
        )
    if not consent_ok:
        raise UIIRValidationError(
            "Speech/microphone events require explicit wake/recording consent"
        )

    purpose = str(raw.get("purpose") or raw.get("recording_purpose") or "").strip()
    if not purpose:
        raise UIIRValidationError(
            "Speech input requires explicit purpose for recording/wake consent"
        )

    candidates = _parse_candidates(raw)
    primary = candidates[0]
    payload = _redact_payload(raw, candidates)

    multi_target = len(primary.target_component_ids) > 1
    high_risk = primary.risk_hint in {"high", "critical"}
    low_conf = primary.confidence < confidence_floor

    if low_conf or (multi_target and high_risk):
        reason_parts: list[str] = []
        if low_conf:
            reason_parts.append(
                f"low_confidence:{primary.confidence:.2f}<{confidence_floor:.2f}"
            )
        if multi_target and high_risk:
            reason_parts.append(
                f"multi_target_high_risk:targets={len(primary.target_component_ids)}"
            )
        return SpeechNormalizationResult(
            event=None,
            requires_clarification=True,
            clarification_reason=";".join(reason_parts),
            alternatives=candidates,
        )

    resolved_target = (
        target_component_id.strip()
        or (primary.target_component_ids[0] if primary.target_component_ids else "")
    )
    if not resolved_target:
        return SpeechNormalizationResult(
            event=None,
            requires_clarification=True,
            clarification_reason="missing_target_component",
            alternatives=candidates,
        )

    kind = _kind_for_candidate(primary)
    event = CanonicalInteractionEvent(
        event_id=event_id,
        kind=kind,
        target_component_id=resolved_target,
        timestamp_ms=timestamp_ms,
        provenance=provenance,
        capability_id=CAPABILITY_SPEECH,
        consent_ok=True,
        sequence=sequence,
        confidence=primary.confidence,
        raw_payload=payload,
        source_adapter=SPEECH_ADAPTER_ID,
    )
    return SpeechNormalizationResult(
        event=validate_event(event),
        requires_clarification=False,
        alternatives=candidates[1:],
    )


__all__ = [
    "CAPABILITY_MICROPHONE",
    "CAPABILITY_SPEECH",
    "DEFAULT_CONFIDENCE_FLOOR",
    "SPEECH_ADAPTER_ID",
    "SPEECH_INPUT_ADAPTER_INTERFACE",
    "SpeechCandidate",
    "SpeechNormalizationResult",
    "normalize_speech_input",
]
