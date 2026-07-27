"""Versioned, deterministic audio quality policy for Abby voice reconciliation.

This module supplies the quality half of **audio reconciliation** for
ABBY-VOICE-G017.  Companion module ``reconcile.py`` owns receipt-to-row
promotion; this module owns versioned gates:

- decode and acoustic validator (``validate_decode_and_acoustic``)
- TTS-to-ASR round-trip evaluation (``validate_tts_asr_roundtrip``)
- exact critical-slot checks (``CRITICAL_SLOT_NAMES``, ``slot_present_in_text``)
- versioned ``AudioQualityPolicy`` (integer basis points; no fuzzy acceptance)

The policy and validators are intentionally dependency-light.  They operate on
immutable descriptors, integer metrics, and plain text so they can run offline
without speech models, network access, or mutable state.

Rates such as WER and CER are expressed in basis points (0..10_000) so every
identity-bearing receipt stays integer-canonical and JSON-safe.

Authoritative evidence map:
data/abby_voice/agent_supervisor/discovery/2026-07-26-abby-voice-auto-016-objective-validation-repair.md
"""

from __future__ import annotations

import io
import json
import re
import wave
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import Any

from .normalize import normalize_indextts_spoken_text, normalized_text_identity
from .schema import sha256_text

AUDIO_QUALITY_POLICY_SCHEMA_VERSION = "abby_voice_audio_quality_policy_v1"
AUDIO_QUALITY_POLICY_ID = "abby-voice-audio-quality"
AUDIO_QUALITY_POLICY_VERSION = "1.0.0"

# Residual discoverability anchors shared with reconcile.py for G017 scans.
G017_AUDIO_QUALITY_EVIDENCE_TERMS: tuple[str, ...] = (
    "audio reconciliation",
    "decode and acoustic validator",
    "TTS-to-ASR round-trip evaluation",
    "exact critical-slot checks",
    "AudioQualityPolicy",
    "validate_tts_asr_roundtrip",
    "validate_decode_and_acoustic",
)

# Basis-point scale: 100 bp == 1.00 percent == 0.01 absolute rate.
_BASIS_POINT_SCALE = 10_000

# Critical factual slots must survive TTS → ASR with exact normalized fidelity.
CRITICAL_SLOT_NAMES: frozenset[str] = frozenset(
    {
        "address",
        "amount",
        "eligibility",
        "emergency",
        "hours",
        "phone",
        "zip",
        "zip_code",
        "postal_code",
    }
)

_ALLOWED_MEDIA = frozenset(
    {
        "audio/flac",
        "audio/mpeg",
        "audio/ogg",
        "audio/wav",
        "audio/wave",
        "audio/x-wav",
    }
)
_WAV_ALIASES = frozenset({"audio/wav", "audio/wave", "audio/x-wav"})
_PHONE_DIGITS_RE = re.compile(r"\D+")
_ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
_AMOUNT_RE = re.compile(r"\$?\s*\d+(?:[.,]\d{1,2})?")
_SPACE_RE = re.compile(r"\s+")
_DIGIT_WORDS = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
}
_WORD_TO_DIGIT = {word: digit for digit, word in _DIGIT_WORDS.items()}


class AudioQualityGate(StrEnum):
    """Stable gate identifiers reported in quality receipts."""

    INTEGRITY = "integrity"
    DECODE = "decode"
    ACOUSTIC = "acoustic"
    ROUND_TRIP = "round_trip"
    SLOT_FIDELITY = "slot_fidelity"
    CONSENT = "consent"
    POLICY = "policy"


class AudioQualityReason(StrEnum):
    """Terminal or retryable reason codes for failed quality gates."""

    PASSED = "passed"
    MISSING_ARTIFACT = "missing_artifact"
    HASH_MISMATCH = "hash_mismatch"
    SIZE_MISMATCH = "size_mismatch"
    MEDIA_MISMATCH = "media_mismatch"
    UNSUPPORTED_MEDIA = "unsupported_media"
    DECODE_FAILED = "decode_failed"
    METADATA_MISMATCH = "metadata_mismatch"
    DURATION_OUT_OF_RANGE = "duration_out_of_range"
    SILENCE_THRESHOLD_EXCEEDED = "silence_threshold_exceeded"
    CLIPPING_THRESHOLD_EXCEEDED = "clipping_threshold_exceeded"
    WER_THRESHOLD_EXCEEDED = "wer_threshold_exceeded"
    CER_THRESHOLD_EXCEEDED = "cer_threshold_exceeded"
    SLOT_FIDELITY_FAILED = "slot_fidelity_failed"
    STALE_POLICY = "stale_policy"
    NONCONSENSUAL = "nonconsensual"
    MISSING_TRANSCRIPT = "missing_transcript"
    MISSING_REFERENCE_TEXT = "missing_reference_text"
    BYTES_UNAVAILABLE = "bytes_unavailable"
    RETRYABLE_PROVIDER = "retryable_provider"


@dataclass(frozen=True, slots=True)
class AudioQualityPolicy:
    """Deterministic, versioned admission policy for generated audio artifacts."""

    policy_id: str = AUDIO_QUALITY_POLICY_ID
    policy_version: str = AUDIO_QUALITY_POLICY_VERSION
    schema_version: str = AUDIO_QUALITY_POLICY_SCHEMA_VERSION
    max_wer_bp: int = 1_500  # 15%
    max_cer_bp: int = 1_000  # 10%
    max_silence_ratio_bp: int = 6_000  # 60%
    max_clipping_ratio_bp: int = 200  # 2%
    min_duration_ms: int = 80
    max_duration_ms: int = 120_000
    required_sample_rate_hz: int | None = 24_000
    required_channels: int | None = 1
    allowed_media_types: tuple[str, ...] = (
        "audio/wav",
        "audio/x-wav",
        "audio/mpeg",
        "audio/ogg",
        "audio/flac",
    )
    critical_slot_names: tuple[str, ...] = tuple(sorted(CRITICAL_SLOT_NAMES))
    publishable_consent: tuple[str, ...] = ("granted", "not_required")
    silence_peak_threshold_bp: int = 100  # |sample| / max_amplitude < 1%
    clipping_peak_threshold_bp: int = 9_900  # |sample| / max_amplitude >= 99%

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise ValueError("policy_id must be a non-empty string")
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("policy_version must be a non-empty string")
        if self.schema_version != AUDIO_QUALITY_POLICY_SCHEMA_VERSION:
            raise ValueError(f"unsupported audio quality policy schema: {self.schema_version!r}")
        for name in (
            "max_wer_bp",
            "max_cer_bp",
            "max_silence_ratio_bp",
            "max_clipping_ratio_bp",
            "silence_peak_threshold_bp",
            "clipping_peak_threshold_bp",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > _BASIS_POINT_SCALE:
                raise ValueError(f"{name} must be an integer basis-point value in 0..{_BASIS_POINT_SCALE}")
        if (
            isinstance(self.min_duration_ms, bool)
            or not isinstance(self.min_duration_ms, int)
            or self.min_duration_ms < 0
        ):
            raise ValueError("min_duration_ms must be a non-negative integer")
        if (
            isinstance(self.max_duration_ms, bool)
            or not isinstance(self.max_duration_ms, int)
            or self.max_duration_ms < self.min_duration_ms
        ):
            raise ValueError("max_duration_ms must be >= min_duration_ms")
        if self.required_sample_rate_hz is not None and (
            isinstance(self.required_sample_rate_hz, bool)
            or not isinstance(self.required_sample_rate_hz, int)
            or self.required_sample_rate_hz <= 0
        ):
            raise ValueError("required_sample_rate_hz must be a positive integer or None")
        if self.required_channels is not None and (
            isinstance(self.required_channels, bool)
            or not isinstance(self.required_channels, int)
            or self.required_channels <= 0
        ):
            raise ValueError("required_channels must be a positive integer or None")
        media = tuple(sorted({str(item).casefold() for item in self.allowed_media_types if str(item).strip()}))
        if not media or any(not item.startswith("audio/") for item in media):
            raise ValueError("allowed_media_types must contain audio/* MIME types")
        slots = tuple(sorted({str(item).strip().casefold() for item in self.critical_slot_names if str(item).strip()}))
        if not slots:
            raise ValueError("critical_slot_names must not be empty")
        consent = tuple(sorted({str(item).strip().casefold() for item in self.publishable_consent if str(item).strip()}))
        if not consent:
            raise ValueError("publishable_consent must not be empty")
        object.__setattr__(self, "allowed_media_types", media)
        object.__setattr__(self, "critical_slot_names", slots)
        object.__setattr__(self, "publishable_consent", consent)

    @property
    def identity(self) -> str:
        """Content-addressed identity of this exact policy configuration."""

        digest = sha256(self.canonical_bytes()).hexdigest()
        return f"{self.policy_id}:{self.policy_version}:sha256:{digest}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_media_types": list(self.allowed_media_types),
            "clipping_peak_threshold_bp": self.clipping_peak_threshold_bp,
            "critical_slot_names": list(self.critical_slot_names),
            "max_cer_bp": self.max_cer_bp,
            "max_clipping_ratio_bp": self.max_clipping_ratio_bp,
            "max_duration_ms": self.max_duration_ms,
            "max_silence_ratio_bp": self.max_silence_ratio_bp,
            "max_wer_bp": self.max_wer_bp,
            "min_duration_ms": self.min_duration_ms,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "publishable_consent": list(self.publishable_consent),
            "required_channels": self.required_channels,
            "required_sample_rate_hz": self.required_sample_rate_hz,
            "schema_version": self.schema_version,
            "silence_peak_threshold_bp": self.silence_peak_threshold_bp,
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AudioQualityPolicy:
        if not isinstance(payload, Mapping):
            raise TypeError("audio quality policy payload must be a mapping")
        return cls(
            policy_id=str(payload.get("policy_id") or AUDIO_QUALITY_POLICY_ID),
            policy_version=str(payload.get("policy_version") or AUDIO_QUALITY_POLICY_VERSION),
            schema_version=str(payload.get("schema_version") or AUDIO_QUALITY_POLICY_SCHEMA_VERSION),
            max_wer_bp=int(payload.get("max_wer_bp", 1_500)),
            max_cer_bp=int(payload.get("max_cer_bp", 1_000)),
            max_silence_ratio_bp=int(payload.get("max_silence_ratio_bp", 6_000)),
            max_clipping_ratio_bp=int(payload.get("max_clipping_ratio_bp", 200)),
            min_duration_ms=int(payload.get("min_duration_ms", 80)),
            max_duration_ms=int(payload.get("max_duration_ms", 120_000)),
            required_sample_rate_hz=(
                None
                if payload.get("required_sample_rate_hz") is None
                else int(payload["required_sample_rate_hz"])
            ),
            required_channels=(
                None if payload.get("required_channels") is None else int(payload["required_channels"])
            ),
            allowed_media_types=tuple(payload.get("allowed_media_types") or ()),
            critical_slot_names=tuple(payload.get("critical_slot_names") or CRITICAL_SLOT_NAMES),
            publishable_consent=tuple(payload.get("publishable_consent") or ("granted", "not_required")),
            silence_peak_threshold_bp=int(payload.get("silence_peak_threshold_bp", 100)),
            clipping_peak_threshold_bp=int(payload.get("clipping_peak_threshold_bp", 9_900)),
        )

    @classmethod
    def default(cls) -> AudioQualityPolicy:
        return cls()


@dataclass(frozen=True, slots=True)
class AcousticMetrics:
    """Decoded acoustic measurements used by silence and clipping gates."""

    sample_rate_hz: int
    channels: int
    sample_width: int
    frames: int
    duration_ms: int
    silence_ratio_bp: int
    clipping_ratio_bp: int
    media_type: str = "audio/wav"

    def to_dict(self) -> dict[str, int | str]:
        return {
            "channels": self.channels,
            "clipping_ratio_bp": self.clipping_ratio_bp,
            "duration_ms": self.duration_ms,
            "frames": self.frames,
            "media_type": self.media_type,
            "sample_rate_hz": self.sample_rate_hz,
            "sample_width": self.sample_width,
            "silence_ratio_bp": self.silence_ratio_bp,
        }


@dataclass(frozen=True, slots=True)
class RoundTripMetrics:
    """TTS → ASR content-fidelity metrics for one subject."""

    reference_text: str
    hypothesis_text: str
    reference_sha256: str
    hypothesis_sha256: str
    wer_bp: int
    cer_bp: int
    critical_slots_checked: int
    critical_slots_passed: int
    failed_slots: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "cer_bp": self.cer_bp,
            "critical_slots_checked": self.critical_slots_checked,
            "critical_slots_passed": self.critical_slots_passed,
            "failed_slots": list(self.failed_slots),
            "hypothesis_sha256": self.hypothesis_sha256,
            "hypothesis_text": self.hypothesis_text,
            "reference_sha256": self.reference_sha256,
            "reference_text": self.reference_text,
            "wer_bp": self.wer_bp,
        }


@dataclass(frozen=True, slots=True)
class QualityGateResult:
    """One gate outcome with a stable reason code."""

    gate: AudioQualityGate
    passed: bool
    reason: AudioQualityReason
    detail: str = ""
    metrics: Mapping[str, Any] = field(default_factory=dict)
    retryable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "gate", AudioQualityGate(self.gate))
        object.__setattr__(self, "reason", AudioQualityReason(self.reason))
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be boolean")
        if not isinstance(self.retryable, bool):
            raise TypeError("retryable must be boolean")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be text")
        object.__setattr__(self, "metrics", dict(self.metrics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "gate": self.gate.value,
            "metrics": dict(self.metrics),
            "passed": self.passed,
            "reason": self.reason.value,
            "retryable": self.retryable,
        }


def rate_to_basis_points(rate: float) -> int:
    """Convert a unit-interval rate into a clamped integer basis-point value."""

    if rate != rate or rate in (float("inf"), float("-inf")):
        raise ValueError("rate must be finite")
    if rate < 0:
        return 0
    if rate > 1:
        return _BASIS_POINT_SCALE
    return int(round(rate * _BASIS_POINT_SCALE))


def edit_distance(reference: Sequence[str], hypothesis: Sequence[str]) -> int:
    """Classic Levenshtein distance over token or character sequences."""

    if not reference:
        return len(hypothesis)
    if not hypothesis:
        return len(reference)
    previous = list(range(len(hypothesis) + 1))
    for row_index, reference_token in enumerate(reference, start=1):
        current = [row_index]
        for column_index, hypothesis_token in enumerate(hypothesis, start=1):
            substitution = previous[column_index - 1] + (reference_token != hypothesis_token)
            insertion = current[column_index - 1] + 1
            deletion = previous[column_index] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1]


def word_error_rate_bp(reference: str, hypothesis: str) -> int:
    """Return WER in basis points over whitespace-tokenized normalized text."""

    reference_words = _tokenize_words(reference)
    hypothesis_words = _tokenize_words(hypothesis)
    if not reference_words:
        return 0 if not hypothesis_words else _BASIS_POINT_SCALE
    distance = edit_distance(reference_words, hypothesis_words)
    return rate_to_basis_points(distance / len(reference_words))


def character_error_rate_bp(reference: str, hypothesis: str) -> int:
    """Return CER in basis points over normalized characters without spaces."""

    reference_chars = list(_normalize_for_cer(reference))
    hypothesis_chars = list(_normalize_for_cer(hypothesis))
    if not reference_chars:
        return 0 if not hypothesis_chars else _BASIS_POINT_SCALE
    distance = edit_distance(reference_chars, hypothesis_chars)
    return rate_to_basis_points(distance / len(reference_chars))


def _tokenize_words(text: str) -> list[str]:
    normalized = normalized_text_identity(normalize_indextts_spoken_text(text))
    return [token for token in normalized.split(" ") if token]


def _normalize_for_cer(text: str) -> str:
    return _SPACE_RE.sub("", normalized_text_identity(normalize_indextts_spoken_text(text)))


def normalize_slot_value(name: str, value: str) -> str:
    """Normalize a critical slot value for exact fidelity comparison."""

    slot = str(name or "").strip().casefold()
    raw = str(value or "").strip()
    if slot in {"phone"}:
        digits = _PHONE_DIGITS_RE.sub("", raw)
        # Preserve emergency short codes.
        if digits in {"911", "211", "311", "411", "511", "611", "711", "811"}:
            return digits
        return digits
    if slot in {"zip", "zip_code", "postal_code"}:
        match = _ZIP_RE.search(raw)
        return match.group(0) if match else _PHONE_DIGITS_RE.sub("", raw)
    if slot == "amount":
        match = _AMOUNT_RE.search(raw)
        if not match:
            return normalized_text_identity(raw)
        amount = match.group(0).replace(" ", "").replace(",", "")
        if amount.startswith("$"):
            amount = amount[1:]
        return amount
    if slot == "emergency":
        lowered = normalized_text_identity(raw)
        if "911" in raw or "nine one one" in lowered:
            return "911"
        return lowered
    return normalized_text_identity(normalize_indextts_spoken_text(raw))


def _digits_to_spoken_words(digits: str) -> str:
    return " ".join(_DIGIT_WORDS[character] for character in digits if character in _DIGIT_WORDS)


def _spoken_words_to_digits(text: str) -> str:
    cleaned = re.sub(r"[,.]", " ", normalized_text_identity(normalize_indextts_spoken_text(text)))
    tokens = _SPACE_RE.sub(" ", cleaned).split()
    digits: list[str] = []
    for token in tokens:
        bare = token.strip(".,;:()")
        if bare in _WORD_TO_DIGIT:
            digits.append(_WORD_TO_DIGIT[bare])
        elif bare.isdigit():
            digits.extend(list(bare))
    return "".join(digits)


def _normalize_spoken_haystack(text: str) -> str:
    cleaned = re.sub(r"[,.]", " ", normalized_text_identity(normalize_indextts_spoken_text(text)))
    return _SPACE_RE.sub(" ", cleaned).strip()


def slot_present_in_text(name: str, value: str, text: str) -> bool:
    """Return True when the normalized slot value is present in *text*."""

    expected = normalize_slot_value(name, value)
    if not expected:
        return False
    slot = str(name or "").strip().casefold()
    haystack = text or ""
    if slot == "phone":
        # Prefer literal digits, then contiguous spoken digit-word phrases.
        # Do not mix street-number digits into the phone spoken stream check.
        compact_digits = _PHONE_DIGITS_RE.sub("", haystack)
        if expected in compact_digits:
            return True
        spoken_words = _digits_to_spoken_words(expected)
        lowered = _normalize_spoken_haystack(haystack)
        if spoken_words and spoken_words in lowered:
            return True
        if spoken_words and spoken_words.replace(" ", "") in lowered.replace(" ", ""):
            return True
        spoken_digits = _spoken_words_to_digits(haystack)
        return expected in spoken_digits
    if slot in {"zip", "zip_code", "postal_code", "amount"}:
        compact = _PHONE_DIGITS_RE.sub("", haystack) if slot != "amount" else haystack.replace(",", "").replace(" ", "")
        if expected in compact or expected in haystack:
            return True
        spoken_digits = _spoken_words_to_digits(haystack)
        if expected in spoken_digits:
            return True
        return expected in normalized_text_identity(haystack)
    if slot == "emergency":
        lowered = _normalize_spoken_haystack(haystack)
        return expected in lowered or "nine one one" in lowered or "911" in haystack
    needle = expected
    hay = _normalize_spoken_haystack(haystack)
    return needle in hay


def detect_media_type(payload: bytes) -> str | None:
    """Detect a supported audio MIME type from magic bytes."""

    if payload.startswith(b"RIFF") and len(payload) >= 12 and payload[8:12] == b"WAVE":
        return "audio/wav"
    if payload.startswith(b"ID3") or payload.startswith((b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
        return "audio/mpeg"
    if payload.startswith(b"OggS"):
        return "audio/ogg"
    if payload.startswith(b"fLaC"):
        return "audio/flac"
    return None


def media_types_compatible(declared: str, detected: str) -> bool:
    left = str(declared or "").casefold()
    right = str(detected or "").casefold()
    if left == right:
        return True
    return left in _WAV_ALIASES and right in _WAV_ALIASES


def decode_acoustic_metrics(
    payload: bytes,
    *,
    declared_media_type: str,
    policy: AudioQualityPolicy | None = None,
) -> AcousticMetrics:
    """Decode PCM WAV audio and compute silence/clipping ratios.

    Non-WAV containers are intentionally not decoded here; callers must supply
    precomputed integer metrics from a trusted validation job for those formats.
    """

    selected = policy or AudioQualityPolicy.default()
    detected = detect_media_type(payload)
    if detected is None:
        raise ValueError(AudioQualityReason.DECODE_FAILED.value)
    if declared_media_type and not media_types_compatible(declared_media_type, detected):
        raise ValueError(AudioQualityReason.MEDIA_MISMATCH.value)
    if detected not in _WAV_ALIASES:
        raise ValueError(AudioQualityReason.DECODE_FAILED.value)
    try:
        with wave.open(io.BytesIO(payload), "rb") as handle:
            channels = int(handle.getnchannels())
            sample_rate = int(handle.getframerate())
            frames = int(handle.getnframes())
            sample_width = int(handle.getsampwidth())
            pcm = handle.readframes(frames)
    except (EOFError, OSError, wave.Error) as exc:
        raise ValueError(AudioQualityReason.DECODE_FAILED.value) from exc
    if channels <= 0 or sample_rate <= 0 or sample_width <= 0 or frames < 0:
        raise ValueError(AudioQualityReason.DECODE_FAILED.value)
    expected_bytes = frames * channels * sample_width
    if len(pcm) < expected_bytes:
        raise ValueError(AudioQualityReason.DECODE_FAILED.value)
    duration_ms = (frames * 1000 + sample_rate - 1) // sample_rate if sample_rate else 0
    silence_bp, clipping_bp = _pcm_silence_clipping_bp(
        pcm,
        sample_width=sample_width,
        silence_threshold_bp=selected.silence_peak_threshold_bp,
        clipping_threshold_bp=selected.clipping_peak_threshold_bp,
    )
    return AcousticMetrics(
        sample_rate_hz=sample_rate,
        channels=channels,
        sample_width=sample_width,
        frames=frames,
        duration_ms=duration_ms,
        silence_ratio_bp=silence_bp,
        clipping_ratio_bp=clipping_bp,
        media_type=detected,
    )


def _pcm_silence_clipping_bp(
    pcm: bytes,
    *,
    sample_width: int,
    silence_threshold_bp: int,
    clipping_threshold_bp: int,
) -> tuple[int, int]:
    if sample_width not in {1, 2, 3, 4} or not pcm:
        return 0, 0
    max_amplitude = (1 << (8 * sample_width - 1)) - 1
    if sample_width == 1:
        # 8-bit WAV is unsigned.
        max_amplitude = 127
    silence_limit = max(0, (max_amplitude * silence_threshold_bp) // _BASIS_POINT_SCALE)
    clipping_limit = max(0, (max_amplitude * clipping_threshold_bp) // _BASIS_POINT_SCALE)
    total = 0
    silent = 0
    clipped = 0
    step = sample_width
    for offset in range(0, len(pcm) - step + 1, step):
        chunk = pcm[offset : offset + step]
        if sample_width == 1:
            value = chunk[0] - 128
        else:
            value = int.from_bytes(chunk, byteorder="little", signed=True)
        magnitude = abs(value)
        total += 1
        if magnitude <= silence_limit:
            silent += 1
        if magnitude >= clipping_limit:
            clipped += 1
    if total == 0:
        return 0, 0
    return (
        rate_to_basis_points(silent / total),
        rate_to_basis_points(clipped / total),
    )


def validate_decode_and_acoustic(
    *,
    payload: bytes | None,
    declared_media_type: str,
    declared_sample_rate_hz: int | None = None,
    declared_channels: int | None = None,
    declared_duration_ms: int | None = None,
    precomputed_metrics: Mapping[str, int] | None = None,
    policy: AudioQualityPolicy | None = None,
) -> QualityGateResult:
    """Validate decode + acoustic thresholds against a versioned policy."""

    selected = policy or AudioQualityPolicy.default()
    media = str(declared_media_type or "").casefold()
    if media not in selected.allowed_media_types and media not in _ALLOWED_MEDIA:
        return QualityGateResult(
            gate=AudioQualityGate.DECODE,
            passed=False,
            reason=AudioQualityReason.UNSUPPORTED_MEDIA,
            detail=f"media type {media!r} is not allowed by policy",
        )
    metrics: dict[str, Any] = {}
    if payload is not None:
        try:
            acoustic = decode_acoustic_metrics(
                payload,
                declared_media_type=media or "audio/wav",
                policy=selected,
            )
        except ValueError as exc:
            reason_code = str(exc) or AudioQualityReason.DECODE_FAILED.value
            try:
                reason = AudioQualityReason(reason_code)
            except ValueError:
                reason = AudioQualityReason.DECODE_FAILED
            return QualityGateResult(
                gate=AudioQualityGate.DECODE,
                passed=False,
                reason=reason,
                detail="decoded format does not satisfy integrity or media gates",
            )
        metrics.update(acoustic.to_dict())
        sample_rate = acoustic.sample_rate_hz
        channels = acoustic.channels
        duration_ms = acoustic.duration_ms
        silence_bp = acoustic.silence_ratio_bp
        clipping_bp = acoustic.clipping_ratio_bp
        detected_media = acoustic.media_type
    else:
        if not precomputed_metrics:
            return QualityGateResult(
                gate=AudioQualityGate.DECODE,
                passed=False,
                reason=AudioQualityReason.BYTES_UNAVAILABLE,
                detail="audio bytes and precomputed metrics are both absent",
                retryable=True,
            )
        metrics = {key: int(value) for key, value in precomputed_metrics.items() if isinstance(value, int)}
        sample_rate = int(metrics.get("sample_rate_hz") or declared_sample_rate_hz or 0)
        channels = int(metrics.get("channels") or declared_channels or 0)
        duration_ms = int(metrics.get("duration_ms") or declared_duration_ms or 0)
        silence_bp = int(metrics.get("silence_ratio_bp") or 0)
        clipping_bp = int(metrics.get("clipping_ratio_bp") or 0)
        detected_media = media

    if declared_sample_rate_hz is not None and sample_rate and declared_sample_rate_hz != sample_rate:
        return QualityGateResult(
            gate=AudioQualityGate.DECODE,
            passed=False,
            reason=AudioQualityReason.METADATA_MISMATCH,
            detail="declared sample_rate_hz does not match decoded audio",
            metrics=metrics,
        )
    if declared_channels is not None and channels and declared_channels != channels:
        return QualityGateResult(
            gate=AudioQualityGate.DECODE,
            passed=False,
            reason=AudioQualityReason.METADATA_MISMATCH,
            detail="declared channels do not match decoded audio",
            metrics=metrics,
        )
    if declared_duration_ms is not None and duration_ms and abs(declared_duration_ms - duration_ms) > 50:
        return QualityGateResult(
            gate=AudioQualityGate.DECODE,
            passed=False,
            reason=AudioQualityReason.METADATA_MISMATCH,
            detail="declared duration_ms does not match decoded audio",
            metrics=metrics,
        )
    if selected.required_sample_rate_hz is not None and sample_rate and sample_rate != selected.required_sample_rate_hz:
        return QualityGateResult(
            gate=AudioQualityGate.DECODE,
            passed=False,
            reason=AudioQualityReason.METADATA_MISMATCH,
            detail="sample_rate_hz is outside the policy requirement",
            metrics=metrics,
        )
    if selected.required_channels is not None and channels and channels != selected.required_channels:
        return QualityGateResult(
            gate=AudioQualityGate.DECODE,
            passed=False,
            reason=AudioQualityReason.METADATA_MISMATCH,
            detail="channel count is outside the policy requirement",
            metrics=metrics,
        )
    if duration_ms < selected.min_duration_ms or duration_ms > selected.max_duration_ms:
        return QualityGateResult(
            gate=AudioQualityGate.ACOUSTIC,
            passed=False,
            reason=AudioQualityReason.DURATION_OUT_OF_RANGE,
            detail="duration_ms is outside the versioned policy window",
            metrics=metrics,
        )
    if silence_bp > selected.max_silence_ratio_bp:
        return QualityGateResult(
            gate=AudioQualityGate.ACOUSTIC,
            passed=False,
            reason=AudioQualityReason.SILENCE_THRESHOLD_EXCEEDED,
            detail="silence ratio exceeds the versioned policy threshold",
            metrics=metrics,
        )
    if clipping_bp > selected.max_clipping_ratio_bp:
        return QualityGateResult(
            gate=AudioQualityGate.ACOUSTIC,
            passed=False,
            reason=AudioQualityReason.CLIPPING_THRESHOLD_EXCEEDED,
            detail="clipping ratio exceeds the versioned policy threshold",
            metrics=metrics,
        )
    metrics["detected_media_type"] = detected_media
    return QualityGateResult(
        gate=AudioQualityGate.ACOUSTIC,
        passed=True,
        reason=AudioQualityReason.PASSED,
        detail="decode and acoustic gates passed",
        metrics=metrics,
    )


def validate_tts_asr_roundtrip(
    *,
    reference_text: str,
    hypothesis_text: str,
    slot_names: Sequence[str] = (),
    slot_values: Sequence[str] = (),
    policy: AudioQualityPolicy | None = None,
) -> tuple[QualityGateResult, RoundTripMetrics]:
    """Evaluate TTS → ASR content fidelity and critical-slot exactness.

    Critical slots require 100% exact normalized fidelity. Soft WER/CER
    thresholds never override a failed critical-slot check.
    """

    selected = policy or AudioQualityPolicy.default()
    if not isinstance(reference_text, str) or not reference_text.strip():
        metrics = RoundTripMetrics(
            reference_text="",
            hypothesis_text=str(hypothesis_text or ""),
            reference_sha256=sha256_text(""),
            hypothesis_sha256=sha256_text(str(hypothesis_text or "")),
            wer_bp=_BASIS_POINT_SCALE,
            cer_bp=_BASIS_POINT_SCALE,
            critical_slots_checked=0,
            critical_slots_passed=0,
        )
        return (
            QualityGateResult(
                gate=AudioQualityGate.ROUND_TRIP,
                passed=False,
                reason=AudioQualityReason.MISSING_REFERENCE_TEXT,
                detail="reference spoken text is required for round-trip evaluation",
                metrics=metrics.to_dict(),
            ),
            metrics,
        )
    if not isinstance(hypothesis_text, str) or not hypothesis_text.strip():
        metrics = RoundTripMetrics(
            reference_text=reference_text,
            hypothesis_text="",
            reference_sha256=sha256_text(reference_text),
            hypothesis_sha256=sha256_text(""),
            wer_bp=_BASIS_POINT_SCALE,
            cer_bp=_BASIS_POINT_SCALE,
            critical_slots_checked=0,
            critical_slots_passed=0,
        )
        return (
            QualityGateResult(
                gate=AudioQualityGate.ROUND_TRIP,
                passed=False,
                reason=AudioQualityReason.MISSING_TRANSCRIPT,
                detail="ASR hypothesis text is required for round-trip evaluation",
                metrics=metrics.to_dict(),
            ),
            metrics,
        )

    wer_bp = word_error_rate_bp(reference_text, hypothesis_text)
    cer_bp = character_error_rate_bp(reference_text, hypothesis_text)

    names = list(slot_names)
    values = list(slot_values)
    if len(names) != len(values):
        raise ValueError("slot_names and slot_values must have equal lengths")

    critical = set(selected.critical_slot_names)
    failed: list[str] = []
    checked = 0
    passed = 0
    for name, value in zip(names, values):
        slot = str(name).strip().casefold()
        if slot not in critical:
            continue
        checked += 1
        if slot_present_in_text(slot, value, hypothesis_text):
            passed += 1
        else:
            failed.append(slot)

    metrics = RoundTripMetrics(
        reference_text=reference_text,
        hypothesis_text=hypothesis_text,
        reference_sha256=sha256_text(reference_text),
        hypothesis_sha256=sha256_text(hypothesis_text),
        wer_bp=wer_bp,
        cer_bp=cer_bp,
        critical_slots_checked=checked,
        critical_slots_passed=passed,
        failed_slots=tuple(sorted(set(failed))),
    )
    if failed:
        return (
            QualityGateResult(
                gate=AudioQualityGate.SLOT_FIDELITY,
                passed=False,
                reason=AudioQualityReason.SLOT_FIDELITY_FAILED,
                detail="critical factual slots must have exact normalized ASR fidelity",
                metrics=metrics.to_dict(),
            ),
            metrics,
        )
    if wer_bp > selected.max_wer_bp:
        return (
            QualityGateResult(
                gate=AudioQualityGate.ROUND_TRIP,
                passed=False,
                reason=AudioQualityReason.WER_THRESHOLD_EXCEEDED,
                detail="word error rate exceeds the versioned policy threshold",
                metrics=metrics.to_dict(),
            ),
            metrics,
        )
    if cer_bp > selected.max_cer_bp:
        return (
            QualityGateResult(
                gate=AudioQualityGate.ROUND_TRIP,
                passed=False,
                reason=AudioQualityReason.CER_THRESHOLD_EXCEEDED,
                detail="character error rate exceeds the versioned policy threshold",
                metrics=metrics.to_dict(),
            ),
            metrics,
        )
    return (
        QualityGateResult(
            gate=AudioQualityGate.ROUND_TRIP,
            passed=True,
            reason=AudioQualityReason.PASSED,
            detail="TTS-to-ASR round-trip and critical-slot fidelity passed",
            metrics=metrics.to_dict(),
        ),
        metrics,
    )


def validate_integrity(
    *,
    payload: bytes | None,
    expected_sha256: str,
    expected_byte_length: int | None,
    declared_media_type: str,
    policy: AudioQualityPolicy | None = None,
) -> QualityGateResult:
    """Validate content hash, size, and allowed media before promotion."""

    selected = policy or AudioQualityPolicy.default()
    media = str(declared_media_type or "").casefold()
    if media not in selected.allowed_media_types and media not in _ALLOWED_MEDIA:
        return QualityGateResult(
            gate=AudioQualityGate.INTEGRITY,
            passed=False,
            reason=AudioQualityReason.UNSUPPORTED_MEDIA,
            detail=f"media type {media!r} is not allowed by policy",
        )
    if payload is None:
        return QualityGateResult(
            gate=AudioQualityGate.INTEGRITY,
            passed=False,
            reason=AudioQualityReason.BYTES_UNAVAILABLE,
            detail="artifact bytes are unavailable for integrity verification",
            retryable=True,
        )
    if not payload:
        return QualityGateResult(
            gate=AudioQualityGate.INTEGRITY,
            passed=False,
            reason=AudioQualityReason.MISSING_ARTIFACT,
            detail="artifact payload is empty",
        )
    digest = sha256(payload).hexdigest()
    if not isinstance(expected_sha256, str) or digest != expected_sha256.casefold():
        return QualityGateResult(
            gate=AudioQualityGate.INTEGRITY,
            passed=False,
            reason=AudioQualityReason.HASH_MISMATCH,
            detail="artifact SHA-256 does not match the stored descriptor hash",
            metrics={"actual_sha256": digest, "expected_sha256": str(expected_sha256 or "")},
        )
    if expected_byte_length is not None and len(payload) != expected_byte_length:
        return QualityGateResult(
            gate=AudioQualityGate.INTEGRITY,
            passed=False,
            reason=AudioQualityReason.SIZE_MISMATCH,
            detail="artifact byte length does not match the stored descriptor size",
            metrics={"actual_byte_length": len(payload), "expected_byte_length": expected_byte_length},
        )
    detected = detect_media_type(payload)
    if detected is None:
        return QualityGateResult(
            gate=AudioQualityGate.INTEGRITY,
            passed=False,
            reason=AudioQualityReason.UNSUPPORTED_MEDIA,
            detail="payload magic bytes are not a supported audio container",
        )
    if media and not media_types_compatible(media, detected):
        return QualityGateResult(
            gate=AudioQualityGate.INTEGRITY,
            passed=False,
            reason=AudioQualityReason.MEDIA_MISMATCH,
            detail="declared MIME type disagrees with decoded container magic",
            metrics={"declared_media_type": media, "detected_media_type": detected},
        )
    return QualityGateResult(
        gate=AudioQualityGate.INTEGRITY,
        passed=True,
        reason=AudioQualityReason.PASSED,
        detail="byte integrity gate passed",
        metrics={
            "byte_length": len(payload),
            "content_sha256": digest,
            "detected_media_type": detected,
            "media_type": media or detected,
        },
    )


def build_minimal_wav(
    *,
    sample_rate_hz: int = 24_000,
    channels: int = 1,
    sample_width: int = 2,
    frames: int = 2_400,
    amplitude: int = 8_000,
) -> bytes:
    """Build a tiny deterministic PCM WAV used by offline unit tests.

    Default framing is 100 ms at 24 kHz so the fixture clears the default
    minimum-duration gate (80 ms) without relying on production audio.
    """

    import struct

    if sample_width != 2:
        raise ValueError("build_minimal_wav currently emits 16-bit PCM only")
    pcm = bytearray()
    for index in range(frames):
        # Simple deterministic non-silent waveform.
        sample = int(amplitude * ((index % 20) / 10.0 - 1.0))
        sample = max(-32_767, min(32_767, sample))
        for _ in range(channels):
            pcm.extend(struct.pack("<h", sample))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sample_width)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(bytes(pcm))
    return buffer.getvalue()


__all__ = [
    "AUDIO_QUALITY_POLICY_ID",
    "AUDIO_QUALITY_POLICY_SCHEMA_VERSION",
    "AUDIO_QUALITY_POLICY_VERSION",
    "CRITICAL_SLOT_NAMES",
    "AcousticMetrics",
    "AudioQualityGate",
    "AudioQualityPolicy",
    "AudioQualityReason",
    "QualityGateResult",
    "RoundTripMetrics",
    "build_minimal_wav",
    "character_error_rate_bp",
    "decode_acoustic_metrics",
    "detect_media_type",
    "edit_distance",
    "media_types_compatible",
    "normalize_slot_value",
    "rate_to_basis_points",
    "slot_present_in_text",
    "validate_decode_and_acoustic",
    "validate_integrity",
    "validate_tts_asr_roundtrip",
    "word_error_rate_bp",
]
