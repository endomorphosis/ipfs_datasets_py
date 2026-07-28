"""Deterministic planning for Abby voice TTS repair queues.

The regeneration queue is an input artifact, not an execution contract.  This
module validates each queue row, performs the final punctuation-safe spoken
text normalization, preserves superseded audio lineage, and emits the
package-owned :class:`~ipfs_datasets_py.voice.workset.VoiceAudioWorkset`
consumed by ``ipfs_accelerate_py``.

No network client is imported and no job is submitted here.  That separation
keeps planning reproducible and makes a 12-row canary byte-for-byte identical
across local, supervisor, and Hugging Face execution environments.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from .normalize import canonical_json, normalize_indextts_spoken_text, record_sha256
from .schema import ABBY_VOICE_RESPONSE_V2, AbbyVoiceResponse, sha256_text
from .workset import VoiceAudioWorkset

ABBY_VOICE_REGENERATION_QUEUE_SCHEMA_VERSION = "abby_voice_regeneration_queue_v1"
ABBY_VOICE_REGENERATION_PLAN_SCHEMA_VERSION = "abby_voice_regeneration_plan_v1"
ABBY_VOICE_REGENERATION_POLICY_ID = "abby-voice-tts-repair-v1"

_SPACE_RE = re.compile(r"\s+")
_DASH_RE = re.compile(r"[-\u058a\u05be\u1400\u1806\u2010-\u2015\u2e17\u2e1a\u2e3a-\u2e3b\u2e40\u301c\u3030\u30a0\ufe31-\ufe32\ufe58\ufe63\uff0d]")
_PAREN_RE = re.compile(r"[()]")
_RAW_DIGIT_RE = re.compile(r"\d")
_NEGATIVE_RE = re.compile(r"(?i)\bnegative\b")
_CORRUPTED_DIRECTION_CONTRACTION_RE = re.compile(
    r"\b(?P<stem>that|it|she|he|there|what|who)[\u2019']South\b",
    flags=re.IGNORECASE,
)
_DIRECTION_VARIANT_RE = re.compile(
    r"(?i)\b(?:"
    r"(?P<ne>N(?:orth)?[-\s]?(?:E|East))|"
    r"(?P<nw>N(?:orth)?[-\s]?(?:W|West))|"
    r"(?P<se>S(?:outh)?[-\s]?(?:E|East))|"
    r"(?P<sw>S(?:outh)?[-\s]?(?:W|West))"
    r")\b"
)

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


class AbbyVoiceRegenerationError(ValueError):
    """A regeneration queue or plan failed a deterministic safety gate."""


def _canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}:sha256:{sha256(_canonical_bytes(value)).hexdigest()}"


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise AbbyVoiceRegenerationError(f"{field_name} must be a string")
    text = _SPACE_RE.sub(" ", unicodedata.normalize("NFKC", value)).strip()
    if not text:
        raise AbbyVoiceRegenerationError(f"{field_name} must not be empty")
    return text


def _required_id(value: Any, *, field_name: str) -> str:
    text = _required_text(value, field_name=field_name)
    if any(character.isspace() for character in text):
        raise AbbyVoiceRegenerationError(
            f"{field_name} must be a stable identity without whitespace"
        )
    return text


def _relative_audio_path(value: Any) -> str:
    text = _required_text(value, field_name="selectedDatasetAudioPath")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or "\\" in text:
        raise AbbyVoiceRegenerationError(
            "selectedDatasetAudioPath must be a safe relative dataset path"
        )
    return path.as_posix()


def _repair_contraction(match: re.Match[str]) -> str:
    stem = match.group("stem")
    suffix = "\u2019s"
    return f"{stem}{suffix}"


def _digits_to_words(match: re.Match[str]) -> str:
    return " ".join(_DIGIT_WORDS[digit] for digit in match.group(0))


def _expand_direction_variant(match: re.Match[str]) -> str:
    for name, value in (
        ("ne", "Northeast"),
        ("nw", "Northwest"),
        ("se", "Southeast"),
        ("sw", "Southwest"),
    ):
        if match.group(name):
            return value
    return match.group(0)


def normalize_regeneration_spoken_text(text: str) -> str:
    """Return a fail-closed TTS representation for one repair queue row.

    Queue inputs have already passed the general IndexTTS normalizer, but
    recovered artifacts revealed residual mixed forms such as ``S-East``,
    ``8-zero``, ``J-8``, and a historical direction-expansion corruption such
    as ``that’South``.  Dashes are punctuation, not spoken semantics, so the
    repair policy removes every dash.  Raw digits are rendered digit-by-digit, which is intentional for
    phone numbers, ZIP codes, addresses, extensions, and unit identifiers.
    """

    spoken = normalize_indextts_spoken_text(_required_text(text, field_name="text"))
    spoken = _CORRUPTED_DIRECTION_CONTRACTION_RE.sub(_repair_contraction, spoken)
    spoken = _DIRECTION_VARIANT_RE.sub(_expand_direction_variant, spoken)
    spoken = re.sub(r"\d+", _digits_to_words, spoken)
    spoken = _PAREN_RE.sub(", ", spoken)
    spoken = _DASH_RE.sub(" ", spoken)
    spoken = re.sub(r"\s+([,.;:!?])", r"\1", spoken)
    spoken = re.sub(r"([,.;:!?])(?:\s*[,.;:!?])+", r"\1", spoken)
    spoken = _SPACE_RE.sub(" ", spoken).strip(" \t\r\n;,")

    risks = regeneration_text_risks(spoken)
    if risks:
        raise AbbyVoiceRegenerationError(
            "regeneration text retained unsafe TTS tokens: " + ", ".join(risks)
        )
    return spoken


def regeneration_text_risks(text: str) -> tuple[str, ...]:
    """Return stable reason codes for punctuation unsafe at TTS time."""

    value = str(text or "")
    risks: list[str] = []
    if _NEGATIVE_RE.search(value):
        risks.append("literal_negative")
    if _PAREN_RE.search(value):
        risks.append("parenthetical_punctuation")
    if _DASH_RE.search(value):
        risks.append("dash_punctuation")
    if _RAW_DIGIT_RE.search(value):
        risks.append("raw_digit")
    return tuple(risks)


@dataclass(frozen=True, slots=True)
class AbbyVoiceRegenerationItem:
    """One validated supersession request from the repair queue."""

    superseded_audio_id: str
    response_id: str
    selected_dataset_audio_path: str
    selected_text: str
    queue_repair_text: str
    spoken_text: str
    risk_reasons: tuple[str, ...] = ()
    recommendation: str = "regenerate_from_normalized_text"
    source_record_sha256: str = ""
    text_sha256: str = ""
    regeneration_id: str = ""

    def __post_init__(self) -> None:
        superseded_audio_id = _required_id(
            self.superseded_audio_id, field_name="superseded_audio_id"
        )
        response_id = _required_id(self.response_id, field_name="response_id")
        selected_path = _relative_audio_path(self.selected_dataset_audio_path)
        selected_text = _required_text(self.selected_text, field_name="selected_text")
        queue_text = _required_text(
            self.queue_repair_text, field_name="queue_repair_text"
        )
        spoken_text = normalize_regeneration_spoken_text(self.spoken_text)
        reasons = tuple(
            sorted(
                {
                    _required_id(reason, field_name="risk_reason")
                    for reason in self.risk_reasons
                }
            )
        )
        recommendation = _required_id(
            self.recommendation, field_name="recommendation"
        )
        source_digest = str(self.source_record_sha256 or "")
        if not re.fullmatch(r"[0-9a-f]{64}", source_digest):
            raise AbbyVoiceRegenerationError(
                "source_record_sha256 must be a full lowercase SHA-256"
            )
        text_digest = sha256_text(spoken_text)
        if self.text_sha256 and self.text_sha256 != text_digest:
            raise AbbyVoiceRegenerationError(
                "text_sha256 does not match normalized spoken_text"
            )

        object.__setattr__(self, "superseded_audio_id", superseded_audio_id)
        object.__setattr__(self, "response_id", response_id)
        object.__setattr__(self, "selected_dataset_audio_path", selected_path)
        object.__setattr__(self, "selected_text", selected_text)
        object.__setattr__(self, "queue_repair_text", queue_text)
        object.__setattr__(self, "spoken_text", spoken_text)
        object.__setattr__(self, "risk_reasons", reasons)
        object.__setattr__(self, "recommendation", recommendation)
        object.__setattr__(self, "text_sha256", text_digest)

        computed = _stable_id("abby-voice-regeneration", self.identity_dict())
        if self.regeneration_id and self.regeneration_id != computed:
            raise AbbyVoiceRegenerationError(
                "regeneration_id does not match deterministic content"
            )
        object.__setattr__(self, "regeneration_id", computed)

    @classmethod
    def from_mapping(
        cls, record: Mapping[str, Any]
    ) -> "AbbyVoiceRegenerationItem":
        if not isinstance(record, Mapping):
            raise AbbyVoiceRegenerationError(
                "regeneration queue row must be a mapping"
            )
        queue_text = _required_text(
            record.get("normalizedRepairText"),
            field_name="normalizedRepairText",
        )
        raw_reasons = record.get("riskReasons") or ()
        if isinstance(raw_reasons, str):
            raw_reasons = (raw_reasons,)
        if not isinstance(raw_reasons, Sequence):
            raise AbbyVoiceRegenerationError("riskReasons must be a sequence")
        return cls(
            superseded_audio_id=str(record.get("audioId") or ""),
            response_id=str(record.get("responseId") or ""),
            selected_dataset_audio_path=str(
                record.get("selectedDatasetAudioPath") or ""
            ),
            selected_text=str(record.get("selectedText") or queue_text),
            queue_repair_text=queue_text,
            spoken_text=queue_text,
            risk_reasons=tuple(str(reason) for reason in raw_reasons),
            recommendation=str(
                record.get("recommendation")
                or "regenerate_from_normalized_text"
            ),
            source_record_sha256=record_sha256(record),
        )

    def identity_dict(self) -> dict[str, Any]:
        return {
            "queue_repair_text": self.queue_repair_text,
            "recommendation": self.recommendation,
            "response_id": self.response_id,
            "risk_reasons": list(self.risk_reasons),
            "selected_dataset_audio_path": self.selected_dataset_audio_path,
            "selected_text": self.selected_text,
            "source_record_sha256": self.source_record_sha256,
            "spoken_text": self.spoken_text,
            "superseded_audio_id": self.superseded_audio_id,
            "text_sha256": self.text_sha256,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_dict()
        payload["regeneration_id"] = self.regeneration_id
        return payload


@dataclass(frozen=True, slots=True)
class AbbyVoiceRegenerationPlan:
    """Deterministic queue plan with a package-owned voice workset projection."""

    items: tuple[AbbyVoiceRegenerationItem, ...]
    policy_id: str = ABBY_VOICE_REGENERATION_POLICY_ID
    schema_version: str = ABBY_VOICE_REGENERATION_PLAN_SCHEMA_VERSION
    source_manifest_id: str = ""
    plan_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        items = tuple(
            sorted(self.items, key=lambda item: (item.response_id, item.superseded_audio_id))
        )
        if not items:
            raise AbbyVoiceRegenerationError(
                "regeneration plan requires at least one item"
            )
        if any(not isinstance(item, AbbyVoiceRegenerationItem) for item in items):
            raise AbbyVoiceRegenerationError(
                "regeneration plan items must be AbbyVoiceRegenerationItem"
            )
        for field_name, values in (
            ("response_id", [item.response_id for item in items]),
            (
                "superseded_audio_id",
                [item.superseded_audio_id for item in items],
            ),
            ("regeneration_id", [item.regeneration_id for item in items]),
        ):
            if len(values) != len(set(values)):
                raise AbbyVoiceRegenerationError(
                    f"regeneration plan has duplicate {field_name}"
                )
        policy_id = _required_id(self.policy_id, field_name="policy_id")
        if self.schema_version != ABBY_VOICE_REGENERATION_PLAN_SCHEMA_VERSION:
            raise AbbyVoiceRegenerationError(
                f"unsupported regeneration plan schema: {self.schema_version}"
            )
        computed_source = _stable_id(
            "abby-voice-regeneration-source",
            [item.source_record_sha256 for item in items],
        )
        if self.source_manifest_id and self.source_manifest_id != computed_source:
            raise AbbyVoiceRegenerationError(
                "source_manifest_id does not match queue content"
            )
        metadata = dict(self.metadata)

        object.__setattr__(self, "items", items)
        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(self, "source_manifest_id", computed_source)
        object.__setattr__(self, "metadata", metadata)

        computed_plan = _stable_id("abby-voice-regeneration-plan", self.identity_dict())
        if self.plan_id and self.plan_id != computed_plan:
            raise AbbyVoiceRegenerationError(
                "plan_id does not match deterministic content"
            )
        object.__setattr__(self, "plan_id", computed_plan)

    @classmethod
    def from_records(
        cls,
        records: Iterable[Mapping[str, Any]],
        *,
        limit: int | None = None,
        policy_id: str = ABBY_VOICE_REGENERATION_POLICY_ID,
        metadata: Mapping[str, Any] | None = None,
    ) -> "AbbyVoiceRegenerationPlan":
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0
        ):
            raise AbbyVoiceRegenerationError("limit must be a positive integer")
        parsed = sorted(
            (AbbyVoiceRegenerationItem.from_mapping(record) for record in records),
            key=lambda item: (item.response_id, item.superseded_audio_id),
        )
        if limit is not None:
            parsed = parsed[:limit]
        return cls(
            items=tuple(parsed),
            policy_id=policy_id,
            metadata=dict(metadata or {}),
        )

    def canary(self, size: int = 12) -> "AbbyVoiceRegenerationPlan":
        """Select a stable hash-distributed canary rather than queue-head rows."""

        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise AbbyVoiceRegenerationError("canary size must be positive")
        selected = sorted(
            self.items,
            key=lambda item: (
                sha256(item.regeneration_id.encode("utf-8")).hexdigest(),
                item.regeneration_id,
            ),
        )[:size]
        return AbbyVoiceRegenerationPlan(
            items=tuple(selected),
            policy_id=self.policy_id,
            metadata={**dict(self.metadata), "canary_size": len(selected)},
        )

    def to_voice_workset(self) -> VoiceAudioWorkset:
        responses = tuple(
            AbbyVoiceResponse(
                response_id=item.response_id,
                text=item.selected_text,
                spoken_text=item.spoken_text,
                locale="en-US",
                route_labels=("tts-regeneration",),
                safety_labels=item.risk_reasons,
            )
            for item in self.items
        )
        return VoiceAudioWorkset.build(
            responses=responses,
            source_manifest_id=self.source_manifest_id,
            policy_id=self.policy_id,
        )

    @property
    def supersession_map(self) -> tuple[dict[str, str], ...]:
        """Return old-audio to regeneration bindings; new audio IDs follow validation."""

        return tuple(
            {
                "regeneration_id": item.regeneration_id,
                "response_id": item.response_id,
                "superseded_audio_id": item.superseded_audio_id,
                "target_text_sha256": item.text_sha256,
            }
            for item in self.items
        )

    def identity_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "metadata": dict(self.metadata),
            "policy_id": self.policy_id,
            "schema_version": self.schema_version,
            "source_manifest_id": self.source_manifest_id,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_dict()
        payload["item_count"] = len(self.items)
        payload["plan_id"] = self.plan_id
        payload["supersession_map"] = list(self.supersession_map)
        return payload

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())


def read_regeneration_queue(
    path: str | Path,
    *,
    limit: int | None = None,
    policy_id: str = ABBY_VOICE_REGENERATION_POLICY_ID,
) -> AbbyVoiceRegenerationPlan:
    """Read JSONL queue rows and return a deterministic regeneration plan."""

    queue_path = Path(path).expanduser().resolve()
    records: list[Mapping[str, Any]] = []
    try:
        with queue_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise AbbyVoiceRegenerationError(
                        f"invalid JSON on queue line {line_number}: {exc.msg}"
                    ) from exc
                if not isinstance(record, Mapping):
                    raise AbbyVoiceRegenerationError(
                        f"queue line {line_number} must be a JSON object"
                    )
                records.append(record)
    except OSError as exc:
        raise AbbyVoiceRegenerationError(
            f"cannot read regeneration queue: {queue_path}"
        ) from exc
    return AbbyVoiceRegenerationPlan.from_records(
        records,
        limit=limit,
        policy_id=policy_id,
        metadata={
            "queue_schema_version": ABBY_VOICE_REGENERATION_QUEUE_SCHEMA_VERSION,
        },
    )


__all__ = [
    "ABBY_VOICE_REGENERATION_PLAN_SCHEMA_VERSION",
    "ABBY_VOICE_REGENERATION_POLICY_ID",
    "ABBY_VOICE_REGENERATION_QUEUE_SCHEMA_VERSION",
    "AbbyVoiceRegenerationError",
    "AbbyVoiceRegenerationItem",
    "AbbyVoiceRegenerationPlan",
    "normalize_regeneration_spoken_text",
    "read_regeneration_queue",
    "regeneration_text_risks",
]
