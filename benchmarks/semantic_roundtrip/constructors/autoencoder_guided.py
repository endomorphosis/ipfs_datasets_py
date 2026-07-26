"""Scoreable, paired autoencoder-guidance constructor composition.

The frozen modal autoencoder is an advisor, not an independent text-to-IR
model.  This adapter therefore runs a declared deterministic canonical
constructor first and exposes two paired interventions:

``no_guidance``
    Return the deterministic constructor's canonical L1 unchanged.

``guidance``
    Apply a reviewed causal adapter to L1 using only the frozen
    sample-memory-free stable-feature export.

The repository currently has a reviewed stable-feature export, but no
reviewed adapter from that export to :class:`CanonicalRuleIR`.  In that
default configuration the guidance arm fails closed with an explicit
``unsupported composition`` capability outcome.  It is never relabelled as a
text-to-IR model and an unchanged post-compiler annotation is never scored as
guidance.

Attribution records are deliberately out-of-band from
:class:`ConstructorResult`.  The common realizers receive only canonical L1,
the closed vocabulary, and their own public configuration.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Final, Protocol, runtime_checkable

from benchmarks.semantic_roundtrip.contracts import (
    LIST_FIELDS,
    RULE_FIELDS,
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
    RoundTripConstructor,
)
from benchmarks.semantic_roundtrip.metrics import (
    maximum_weight_assignment,
    rule_similarity,
)
from benchmarks.semantic_roundtrip.realizers.deterministic import (
    CANONICAL_DETERMINISTIC_REALIZER_INTERFACE,
)
from benchmarks.semantic_roundtrip.realizers.leanstral import (
    LEANSTRAL_CANONICAL_REALIZER_INTERFACE,
)
from benchmarks.semantic_roundtrip_capabilities import (
    AUTOENCODER_DECLARED_ARCHITECTURE,
    AUTOENCODER_EFFECTIVE_ARCHITECTURE,
    AUTOENCODER_STATE_CID,
    AUTOENCODER_STATE_RELATIVE_PATH,
    AUTOENCODER_STATE_SCHEMA,
    AUTOENCODER_STATE_SHA256,
    MAX_AUTOENCODER_STATE_BYTES,
    REPO_ROOT,
)


AUTOENCODER_GUIDED_CANONICAL_CONSTRUCTOR_INTERFACE: Final = (
    "AutoencoderGuidedCanonicalConstructor@1"
)
PINNED_AUTOENCODER_STATE_CID: Final = AUTOENCODER_STATE_CID
PINNED_AUTOENCODER_STATE_SHA256: Final = AUTOENCODER_STATE_SHA256
PINNED_AUTOENCODER_STATE_SCHEMA: Final = AUTOENCODER_STATE_SCHEMA
PINNED_AUTOENCODER_DECLARED_ARCHITECTURE: Final = (
    AUTOENCODER_DECLARED_ARCHITECTURE
)
PINNED_AUTOENCODER_EFFECTIVE_ARCHITECTURE: Final = (
    AUTOENCODER_EFFECTIVE_ARCHITECTURE
)
DEFAULT_AUTOENCODER_STATE_PATH: Final = (
    REPO_ROOT / AUTOENCODER_STATE_RELATIVE_PATH
)
COMMON_REALIZER_IDENTITIES: Final = (
    CANONICAL_DETERMINISTIC_REALIZER_INTERFACE,
    LEANSTRAL_CANONICAL_REALIZER_INTERFACE,
)

_FORBIDDEN_REQUEST_CONFIG_MARKERS: Final = (
    "sample_memory",
    "sample_specific_memory",
    "target_embedding",
    "target_vector",
)
_FORBIDDEN_GUIDANCE_KEYS: Final = frozenset(
    {
        "decoded_embedding",
        "decoded_embeddings",
        "embedding_vector",
        "family_logits",
        "legal_ir_target_view_distribution",
        "sample_id",
        "sample_ids",
        "target_embedding",
        "target_embeddings",
        "target_vector",
        "target_vectors",
    }
)
_FORBIDDEN_FEATURE_MARKERS: Final = (
    "sample-memory",
    "sample_memory",
    "target-embedding",
    "target_embedding",
)


class AutoencoderGuidanceArm(str, Enum):
    """The outcome-independent paired intervention assignment."""

    GUIDANCE = "guidance"
    NO_GUIDANCE = "no_guidance"


class AutoencoderCompositionStatus(str, Enum):
    """Whether and how frozen guidance could affect canonical L1."""

    NO_GUIDANCE = "no_guidance"
    APPLIED = "applied"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CanonicalFieldChange:
    """One exact canonical field difference caused by the guidance arm."""

    canonical_field: str
    before: object
    after: object
    baseline_rule_index: int | None
    guided_rule_index: int | None

    def __post_init__(self) -> None:
        if self.canonical_field not in RULE_FIELDS:
            raise ContractError(
                f"unknown canonical field: {self.canonical_field!r}"
            )
        for name in ("baseline_rule_index", "guided_rule_index"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ContractError(
                    f"{name} must be a nonnegative integer or null"
                )

    @property
    def field(self) -> str:
        """Compatibility alias for the canonical field name."""

        return self.canonical_field

    @property
    def path(self) -> str:
        """Return a stable human-readable field path."""

        if self.baseline_rule_index is None:
            return f"rules[+{self.guided_rule_index}].{self.canonical_field}"
        if self.guided_rule_index is None:
            return f"rules[-{self.baseline_rule_index}].{self.canonical_field}"
        return (
            f"rules[{self.baseline_rule_index}"
            f"->{self.guided_rule_index}].{self.canonical_field}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "after": _json_value(self.after),
            "baseline_rule_index": self.baseline_rule_index,
            "before": _json_value(self.before),
            "canonical_field": self.canonical_field,
            "guided_rule_index": self.guided_rule_index,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class FrozenAutoencoderGuidance:
    """Sanitized stable guidance passed across the causal-adapter boundary."""

    state_cid: str
    state_sha256: str
    state_schema: str
    declared_architecture: str
    effective_architecture: str
    stable_export: Mapping[str, object]
    sample_memory_used: bool = False
    target_embedding_selection_used: bool = False

    def __post_init__(self) -> None:
        expected = {
            "state_cid": PINNED_AUTOENCODER_STATE_CID,
            "state_sha256": PINNED_AUTOENCODER_STATE_SHA256,
            "state_schema": PINNED_AUTOENCODER_STATE_SCHEMA,
            "declared_architecture": (
                PINNED_AUTOENCODER_DECLARED_ARCHITECTURE
            ),
            "effective_architecture": (
                PINNED_AUTOENCODER_EFFECTIVE_ARCHITECTURE
            ),
        }
        for field, pinned in expected.items():
            if getattr(self, field) != pinned:
                raise ContractError(
                    f"{field} differs from the frozen autoencoder identity"
                )
        if self.sample_memory_used:
            raise ContractError("sample-memory guidance is forbidden")
        if self.target_embedding_selection_used:
            raise ContractError("target-embedding selection is forbidden")
        if not isinstance(self.stable_export, Mapping):
            raise ContractError("stable_export must be an object")
        detached = _json_value(self.stable_export)
        if not isinstance(detached, dict):
            raise ContractError("stable_export must be an object")
        _validate_stable_export(detached)
        object.__setattr__(self, "stable_export", _freeze_json(detached))

    @property
    def export_id(self) -> str:
        return str(self.stable_export.get("export_id") or "")


@dataclass(frozen=True, slots=True)
class CausalGuidanceApplication:
    """Result of a declared stable-guidance-to-canonical-L1 adapter."""

    composition_supported: bool
    canonical_ir: CanonicalRuleIR | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.composition_supported, bool):
            raise ContractError("composition_supported must be a boolean")
        if self.composition_supported:
            if not isinstance(self.canonical_ir, CanonicalRuleIR):
                raise ContractError(
                    "supported guidance requires a CanonicalRuleIR"
                )
            if self.detail is not None:
                raise ContractError(
                    "supported guidance cannot carry failure detail"
                )
        elif self.canonical_ir is not None:
            raise ContractError(
                "unsupported guidance cannot return canonical IR"
            )
        if self.detail is not None and not self.detail.strip():
            raise ContractError("guidance detail must be nonblank")

    @classmethod
    def supported(
        cls, canonical_ir: CanonicalRuleIR
    ) -> "CausalGuidanceApplication":
        return cls(True, canonical_ir=canonical_ir)

    @classmethod
    def unsupported(cls, detail: str) -> "CausalGuidanceApplication":
        return cls(False, detail=detail)


@runtime_checkable
class CanonicalGuidanceApplicator(Protocol):
    """Narrow causal boundary that cannot inspect source or target embeddings."""

    def __call__(
        self,
        baseline_ir: CanonicalRuleIR,
        allowed_atom_vocabulary: AllowedAtomVocabulary,
        guidance: FrozenAutoencoderGuidance,
    ) -> CausalGuidanceApplication | CanonicalRuleIR | None:
        """Return a guided L1, or explicitly report unsupported composition."""


@dataclass(frozen=True, slots=True)
class AutoencoderGuidanceDiagnostics:
    """Out-of-band attribution receipt for one constructor invocation."""

    arm: AutoencoderGuidanceArm
    composition_status: AutoencoderCompositionStatus
    base_constructor_identity: str
    state_cid: str = PINNED_AUTOENCODER_STATE_CID
    state_sha256: str = PINNED_AUTOENCODER_STATE_SHA256
    declared_architecture: str = PINNED_AUTOENCODER_DECLARED_ARCHITECTURE
    effective_architecture: str = PINNED_AUTOENCODER_EFFECTIVE_ARCHITECTURE
    common_realizer_identities: tuple[str, ...] = COMMON_REALIZER_IDENTITIES
    sample_memory_used: bool = False
    target_embedding_selection_used: bool = False
    field_changes: tuple[CanonicalFieldChange, ...] = ()
    guidance_export_id: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.arm, AutoencoderGuidanceArm):
            raise ContractError("guidance arm is invalid")
        if not isinstance(
            self.composition_status, AutoencoderCompositionStatus
        ):
            raise ContractError("composition status is invalid")
        if (
            not isinstance(self.base_constructor_identity, str)
            or not self.base_constructor_identity.strip()
        ):
            raise ContractError("base constructor identity must be nonblank")
        if self.state_cid != PINNED_AUTOENCODER_STATE_CID:
            raise ContractError("diagnostic state CID differs from the pin")
        if self.state_sha256 != PINNED_AUTOENCODER_STATE_SHA256:
            raise ContractError("diagnostic state digest differs from the pin")
        if (
            self.declared_architecture
            != PINNED_AUTOENCODER_DECLARED_ARCHITECTURE
            or self.effective_architecture
            != PINNED_AUTOENCODER_EFFECTIVE_ARCHITECTURE
        ):
            raise ContractError(
                "diagnostic architecture differs from the pin"
            )
        if tuple(self.common_realizer_identities) != COMMON_REALIZER_IDENTITIES:
            raise ContractError(
                "guidance arms must use the frozen common realizers"
            )
        if self.sample_memory_used:
            raise ContractError("sample-memory guidance is forbidden")
        if self.target_embedding_selection_used:
            raise ContractError("target-embedding selection is forbidden")
        if not isinstance(self.field_changes, tuple) or not all(
            isinstance(change, CanonicalFieldChange)
            for change in self.field_changes
        ):
            raise ContractError(
                "field_changes must contain CanonicalFieldChange records"
            )
        if (
            self.arm is AutoencoderGuidanceArm.NO_GUIDANCE
            and (
                self.composition_status
                not in {
                    AutoencoderCompositionStatus.NO_GUIDANCE,
                    AutoencoderCompositionStatus.FAILED,
                }
                or self.field_changes
            )
        ):
            raise ContractError(
                "no-guidance attribution cannot contain guidance changes"
            )
        if (
            self.composition_status is AutoencoderCompositionStatus.APPLIED
            and self.arm is not AutoencoderGuidanceArm.GUIDANCE
        ):
            raise ContractError("only the guidance arm may apply guidance")
        if self.detail is not None and not self.detail.strip():
            raise ContractError("diagnostic detail must be nonblank")

    @property
    def composition_supported(self) -> bool:
        return self.composition_status in {
            AutoencoderCompositionStatus.NO_GUIDANCE,
            AutoencoderCompositionStatus.APPLIED,
        }

    @property
    def canonical_l1_changed(self) -> bool:
        return bool(self.field_changes)

    @property
    def changed_fields(self) -> tuple[str, ...]:
        changed = {item.canonical_field for item in self.field_changes}
        return tuple(field for field in RULE_FIELDS if field in changed)

    @property
    def changed_field_paths(self) -> tuple[str, ...]:
        return tuple(change.path for change in self.field_changes)

    def to_dict(self) -> dict[str, object]:
        return {
            "arm": self.arm.value,
            "base_constructor_identity": self.base_constructor_identity,
            "canonical_l1_changed": self.canonical_l1_changed,
            "changed_field_paths": list(self.changed_field_paths),
            "changed_fields": list(self.changed_fields),
            "common_realizer_identities": list(
                self.common_realizer_identities
            ),
            "composition_status": self.composition_status.value,
            "composition_supported": self.composition_supported,
            "declared_architecture": self.declared_architecture,
            "detail": self.detail,
            "effective_architecture": self.effective_architecture,
            "field_changes": [
                change.to_dict() for change in self.field_changes
            ],
            "guidance_export_id": self.guidance_export_id,
            "sample_memory_used": False,
            "state_cid": self.state_cid,
            "state_sha256": self.state_sha256,
            "target_embedding_selection_used": False,
        }


@dataclass(frozen=True, slots=True)
class AutoencoderGuidedConstruction:
    """Constructor result paired with its non-realizer attribution receipt."""

    result: ConstructorResult
    diagnostics: AutoencoderGuidanceDiagnostics

    def __post_init__(self) -> None:
        if not isinstance(self.result, ConstructorResult):
            raise ContractError("result must be a ConstructorResult")
        if not isinstance(
            self.diagnostics, AutoencoderGuidanceDiagnostics
        ):
            raise ContractError(
                "diagnostics must be AutoencoderGuidanceDiagnostics"
            )

    @property
    def attribution(self) -> AutoencoderGuidanceDiagnostics:
        return self.diagnostics

    @property
    def attribution_receipt(self) -> dict[str, object]:
        return self.diagnostics.to_dict()


GuidanceLoader = Callable[[Path], FrozenAutoencoderGuidance]


def _normalize_key(value: object) -> str:
    text = str(value).strip()
    result: list[str] = []
    for index, character in enumerate(text):
        if (
            index
            and character.isupper()
            and text[index - 1].isalnum()
            and text[index - 1].islower()
        ):
            result.append("_")
        result.append(character.lower() if character.isalnum() else "_")
    return "_".join(part for part in "".join(result).split("_") if part)


def _json_value(value: object) -> object:
    """Return a detached finite JSON value."""

    try:
        encoded = json.dumps(
            _thaw_json(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return json.loads(encoded)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractError("value must contain only finite JSON data") from exc


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    if isinstance(value, list):
        return [_thaw_json(item) for item in value]
    return value


def _validate_stable_export(
    value: object, path: str = "stable_export"
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _normalize_key(key)
            if normalized in _FORBIDDEN_GUIDANCE_KEYS:
                raise ContractError(
                    f"guidance may not contain {path}.{key}"
                )
            if normalized == "sample_memory_included" and item is not False:
                raise ContractError("sample-memory guidance is forbidden")
            _validate_stable_export(item, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            _validate_stable_export(item, f"{path}[{index}]")
        return
    if isinstance(value, str):
        normalized = value.lower()
        # ``excluded_categories`` is allowed to name what it excludes.
        if ".excluded_categories" not in path and any(
            marker in normalized for marker in _FORBIDDEN_FEATURE_MARKERS
        ):
            raise ContractError(
                f"guidance contains a forbidden feature at {path}"
            )


def _config_forbidden_path(value: object, path: str = "config") -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _normalize_key(key)
            if any(
                marker in normalized
                for marker in _FORBIDDEN_REQUEST_CONFIG_MARKERS
            ):
                return f"{path}.{key}"
            nested = _config_forbidden_path(item, f"{path}.{key}")
            if nested:
                return nested
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            nested = _config_forbidden_path(item, f"{path}[{index}]")
            if nested:
                return nested
    elif isinstance(value, str):
        normalized = _normalize_key(value)
        if any(
            marker in normalized
            for marker in _FORBIDDEN_REQUEST_CONFIG_MARKERS
        ):
            return path
    return None


def _read_pinned_state(path: Path) -> bytes:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ContractError("frozen autoencoder state is not a regular file")
        if before.st_size > MAX_AUTOENCODER_STATE_BYTES:
            raise ContractError("frozen autoencoder state exceeds its size bound")
        chunks: list[bytes] = []
        remaining = MAX_AUTOENCODER_STATE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(raw) != before.st_size
            or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
        ):
            raise ContractError(
                "frozen autoencoder state changed during its read"
            )
        return raw
    finally:
        os.close(descriptor)


def load_frozen_autoencoder_guidance(
    path: Path = DEFAULT_AUTOENCODER_STATE_PATH,
) -> FrozenAutoencoderGuidance:
    """Load the exact state read-only and export only stable global features."""

    raw = _read_pinned_state(Path(path))
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PINNED_AUTOENCODER_STATE_SHA256:
        raise ContractError(
            "autoencoder state SHA-256 differs from the frozen identity"
        )
    try:
        from benchmarks.logic_pipeline.content_addressing import cid_for_bytes

        cid = cid_for_bytes(raw)
    except ImportError as exc:
        raise ContractError(
            "CID implementation is unavailable for state verification"
        ) from exc
    if cid != PINNED_AUTOENCODER_STATE_CID:
        raise ContractError(
            "autoencoder state CID differs from the frozen identity"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ContractError("autoencoder state must be a JSON object")
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
            modal_autoencoder,
        )

        state = modal_autoencoder.ModalAutoencoderTrainingState.from_dict(
            payload
        )
        if (
            state.architecture_version
            != PINNED_AUTOENCODER_EFFECTIVE_ARCHITECTURE
        ):
            raise ContractError(
                "loaded autoencoder architecture differs from the pin"
            )
        revision = state.state_revision
        exported = modal_autoencoder.AdaptiveModalAutoencoder(
            state=state
        ).export_stable_legal_ir_features(())
        if state.state_revision != revision:
            raise ContractError(
                "stable autoencoder export attempted to mutate frozen state"
            )
        stable_export = exported.to_dict()
    except ContractError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        AttributeError,
        ImportError,
    ) as exc:
        raise ContractError(
            f"frozen autoencoder state load failed: {type(exc).__name__}"
        ) from exc

    return FrozenAutoencoderGuidance(
        state_cid=cid,
        state_sha256=digest,
        state_schema=PINNED_AUTOENCODER_STATE_SCHEMA,
        declared_architecture=PINNED_AUTOENCODER_DECLARED_ARCHITECTURE,
        effective_architecture=state.architecture_version,
        stable_export=stable_export,
    )


def _field_value(rule: CanonicalRule, field: str) -> object:
    value = getattr(rule, field)
    return list(value) if field in LIST_FIELDS else value


def canonical_field_changes(
    baseline: CanonicalRuleIR,
    guided: CanonicalRuleIR,
) -> tuple[CanonicalFieldChange, ...]:
    """Return an exact, assignment-aware canonical field mutation receipt."""

    if not isinstance(baseline, CanonicalRuleIR) or not isinstance(
        guided, CanonicalRuleIR
    ):
        raise ContractError("field diff inputs must be CanonicalRuleIR")
    left, right = list(baseline.rules), list(guided.rules)
    weights = [
        [rule_similarity(left_rule, right_rule) for right_rule in right]
        for left_rule in left
    ]
    pairs = maximum_weight_assignment(weights)
    matched_left = {left_index for left_index, _ in pairs}
    matched_right = {right_index for _, right_index in pairs}
    changes: list[CanonicalFieldChange] = []
    for left_index, right_index in pairs:
        left_rule, right_rule = left[left_index], right[right_index]
        for field in RULE_FIELDS:
            before = _field_value(left_rule, field)
            after = _field_value(right_rule, field)
            if before != after:
                changes.append(
                    CanonicalFieldChange(
                        canonical_field=field,
                        before=before,
                        after=after,
                        baseline_rule_index=left_index,
                        guided_rule_index=right_index,
                    )
                )
    for left_index in sorted(set(range(len(left))) - matched_left):
        for field in RULE_FIELDS:
            changes.append(
                CanonicalFieldChange(
                    canonical_field=field,
                    before=_field_value(left[left_index], field),
                    after=None,
                    baseline_rule_index=left_index,
                    guided_rule_index=None,
                )
            )
    for right_index in sorted(set(range(len(right))) - matched_right):
        for field in RULE_FIELDS:
            changes.append(
                CanonicalFieldChange(
                    canonical_field=field,
                    before=None,
                    after=_field_value(right[right_index], field),
                    baseline_rule_index=None,
                    guided_rule_index=right_index,
                )
            )
    field_order = {field: index for index, field in enumerate(RULE_FIELDS)}
    return tuple(
        sorted(
            changes,
            key=lambda item: (
                item.baseline_rule_index
                if item.baseline_rule_index is not None
                else len(left),
                item.guided_rule_index
                if item.guided_rule_index is not None
                else len(right),
                field_order[item.canonical_field],
            ),
        )
    )


def _failure(reason: FailureReason, detail: str) -> ConstructorResult:
    return ConstructorResult(
        ComponentStatus.FAILED,
        failure_reason=reason,
        failure_detail=detail[:1000],
    )


class AutoencoderGuidedCanonicalConstructor:
    """Paired wrapper over one declared deterministic canonical constructor."""

    interface: Final = AUTOENCODER_GUIDED_CANONICAL_CONSTRUCTOR_INTERFACE

    def __init__(
        self,
        base_constructor: RoundTripConstructor | None = None,
        *,
        arm: AutoencoderGuidanceArm | str = (
            AutoencoderGuidanceArm.GUIDANCE
        ),
        guidance_applicator: CanonicalGuidanceApplicator | None = None,
        guidance_loader: GuidanceLoader = load_frozen_autoencoder_guidance,
        state_path: Path = DEFAULT_AUTOENCODER_STATE_PATH,
    ) -> None:
        if base_constructor is None:
            from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
                TypedDeonticCanonicalConstructor,
            )

            base_constructor = TypedDeonticCanonicalConstructor()
        if not isinstance(base_constructor, RoundTripConstructor):
            raise ContractError(
                "base_constructor must implement RoundTripConstructor"
            )
        try:
            resolved_arm = AutoencoderGuidanceArm(arm)
        except ValueError as exc:
            raise ContractError(
                f"unsupported autoencoder guidance arm: {arm!r}"
            ) from exc
        if guidance_applicator is not None and not callable(
            guidance_applicator
        ):
            raise ContractError("guidance_applicator must be callable")
        if not callable(guidance_loader):
            raise ContractError("guidance_loader must be callable")
        self._base_constructor = base_constructor
        self._arm = resolved_arm
        self._guidance_applicator = guidance_applicator
        self._guidance_loader = guidance_loader
        self._state_path = Path(state_path)
        self._loaded_guidance: FrozenAutoencoderGuidance | None = None

    @property
    def arm(self) -> AutoencoderGuidanceArm:
        return self._arm

    @property
    def base_constructor(self) -> RoundTripConstructor:
        return self._base_constructor

    @property
    def compatible_realizer_identities(self) -> tuple[str, ...]:
        """Both paired arms cross with this exact common realizer set."""

        return COMMON_REALIZER_IDENTITIES

    @property
    def identity(self) -> str:
        return (
            f"{self.interface}:{self._arm.value}:"
            f"{self._base_constructor.identity}:"
            f"{PINNED_AUTOENCODER_STATE_CID}:"
            f"{PINNED_AUTOENCODER_EFFECTIVE_ARCHITECTURE}"
        )

    def _diagnostics(
        self,
        status: AutoencoderCompositionStatus,
        *,
        changes: tuple[CanonicalFieldChange, ...] = (),
        guidance: FrozenAutoencoderGuidance | None = None,
        detail: str | None = None,
    ) -> AutoencoderGuidanceDiagnostics:
        return AutoencoderGuidanceDiagnostics(
            arm=self._arm,
            composition_status=status,
            base_constructor_identity=self._base_constructor.identity,
            field_changes=changes,
            guidance_export_id=(
                guidance.export_id if guidance is not None else None
            ),
            detail=detail,
        )

    def _guidance(self) -> FrozenAutoencoderGuidance:
        if self._loaded_guidance is None:
            loaded = self._guidance_loader(self._state_path)
            if not isinstance(loaded, FrozenAutoencoderGuidance):
                raise ContractError(
                    "guidance_loader must return FrozenAutoencoderGuidance"
                )
            self._loaded_guidance = loaded
        return self._loaded_guidance

    def construct_with_diagnostics(
        self, request: ConstructorRequest
    ) -> AutoencoderGuidedConstruction:
        """Run the assigned arm and retain attribution outside canonical L1."""

        if not isinstance(request, ConstructorRequest):
            detail = "request must be ConstructorRequest"
            return AutoencoderGuidedConstruction(
                _failure(FailureReason.INVALID_OUTPUT, detail),
                self._diagnostics(
                    AutoencoderCompositionStatus.FAILED, detail=detail
                ),
            )
        forbidden = _config_forbidden_path(request.config)
        if forbidden:
            detail = (
                f"{forbidden} is forbidden: sample-memory and "
                "target-embedding selection are not benchmark inputs"
            )
            return AutoencoderGuidedConstruction(
                _failure(FailureReason.INVALID_OUTPUT, detail),
                self._diagnostics(
                    AutoencoderCompositionStatus.FAILED, detail=detail
                ),
            )

        try:
            baseline = self._base_constructor.construct(request)
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            detail = (
                "base constructor raised "
                f"{type(exc).__name__} before the guidance intervention"
            )
            return AutoencoderGuidedConstruction(
                _failure(FailureReason.EXCEPTION, detail),
                self._diagnostics(
                    AutoencoderCompositionStatus.FAILED, detail=detail
                ),
            )
        if not isinstance(baseline, ConstructorResult):
            detail = "base constructor returned a non-ConstructorResult"
            return AutoencoderGuidedConstruction(
                _failure(FailureReason.INVALID_OUTPUT, detail),
                self._diagnostics(
                    AutoencoderCompositionStatus.FAILED, detail=detail
                ),
            )
        if baseline.status is ComponentStatus.FAILED:
            detail = (
                "base constructor failed before the guidance intervention"
            )
            return AutoencoderGuidedConstruction(
                baseline,
                self._diagnostics(
                    AutoencoderCompositionStatus.FAILED, detail=detail
                ),
            )
        assert baseline.canonical_ir is not None

        if self._arm is AutoencoderGuidanceArm.NO_GUIDANCE:
            return AutoencoderGuidedConstruction(
                baseline,
                self._diagnostics(
                    AutoencoderCompositionStatus.NO_GUIDANCE
                ),
            )

        if self._guidance_applicator is None:
            detail = (
                "unsupported composition: the reviewed autoencoder export is "
                "a post-compiler advisor and no reviewed causal adapter can "
                "affect canonical L1"
            )
            return AutoencoderGuidedConstruction(
                _failure(FailureReason.CAPABILITY_UNAVAILABLE, detail),
                self._diagnostics(
                    AutoencoderCompositionStatus.UNSUPPORTED,
                    detail=detail,
                ),
            )

        try:
            guidance = self._guidance()
        except (
            ContractError,
            OSError,
            ImportError,
            PermissionError,
        ) as exc:
            detail = (
                "frozen autoencoder guidance unavailable: "
                f"{type(exc).__name__}"
            )
            return AutoencoderGuidedConstruction(
                _failure(FailureReason.CAPABILITY_UNAVAILABLE, detail),
                self._diagnostics(
                    AutoencoderCompositionStatus.FAILED, detail=detail
                ),
            )

        try:
            raw_application = self._guidance_applicator(
                baseline.canonical_ir,
                request.allowed_atom_vocabulary,
                guidance,
            )
            if isinstance(raw_application, CanonicalRuleIR):
                application = CausalGuidanceApplication.supported(
                    raw_application
                )
            elif raw_application is None:
                application = CausalGuidanceApplication.unsupported(
                    "causal guidance applicator returned no canonical L1"
                )
            elif isinstance(raw_application, CausalGuidanceApplication):
                application = raw_application
            else:
                raise ContractError(
                    "guidance applicator returned an unsupported value"
                )
            if not application.composition_supported:
                detail = (
                    "unsupported composition: "
                    + (
                        application.detail
                        or "guidance cannot causally affect canonical L1"
                    )
                )
                return AutoencoderGuidedConstruction(
                    _failure(
                        FailureReason.CAPABILITY_UNAVAILABLE, detail
                    ),
                    self._diagnostics(
                        AutoencoderCompositionStatus.UNSUPPORTED,
                        guidance=guidance,
                        detail=detail,
                    ),
                )
            assert application.canonical_ir is not None
            application.canonical_ir.validate_vocabulary(
                request.allowed_atom_vocabulary
            )
            if application.canonical_ir.is_empty:
                detail = "guidance applicator produced empty canonical L1"
                return AutoencoderGuidedConstruction(
                    _failure(FailureReason.EMPTY_L1, detail),
                    self._diagnostics(
                        AutoencoderCompositionStatus.FAILED,
                        guidance=guidance,
                        detail=detail,
                    ),
                )
            changes = canonical_field_changes(
                baseline.canonical_ir, application.canonical_ir
            )
        except ContractError as exc:
            detail = f"autoencoder guidance rejected: {exc}"
            return AutoencoderGuidedConstruction(
                _failure(FailureReason.INVALID_OUTPUT, detail),
                self._diagnostics(
                    AutoencoderCompositionStatus.FAILED, detail=detail
                ),
            )
        except Exception as exc:
            detail = (
                "autoencoder guidance raised "
                f"{type(exc).__name__}"
            )
            return AutoencoderGuidedConstruction(
                _failure(FailureReason.EXCEPTION, detail),
                self._diagnostics(
                    AutoencoderCompositionStatus.FAILED, detail=detail
                ),
            )

        return AutoencoderGuidedConstruction(
            ConstructorResult(
                ComponentStatus.SUCCESS,
                canonical_ir=application.canonical_ir,
            ),
            self._diagnostics(
                AutoencoderCompositionStatus.APPLIED,
                changes=changes,
                guidance=guidance,
            ),
        )

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        """Return only the canonical constructor contract result."""

        return self.construct_with_diagnostics(request).result


@dataclass(frozen=True, slots=True)
class AutoencoderGuidancePair:
    """The paired arms and the exact common realizer cross-product."""

    guidance: AutoencoderGuidedCanonicalConstructor
    no_guidance: AutoencoderGuidedCanonicalConstructor
    common_realizer_identities: tuple[str, ...] = COMMON_REALIZER_IDENTITIES

    def __post_init__(self) -> None:
        if (
            self.guidance.arm is not AutoencoderGuidanceArm.GUIDANCE
            or self.no_guidance.arm
            is not AutoencoderGuidanceArm.NO_GUIDANCE
        ):
            raise ContractError("autoencoder guidance pair has wrong arms")
        if (
            self.guidance.base_constructor
            is not self.no_guidance.base_constructor
        ):
            raise ContractError(
                "paired arms must share the same base constructor instance"
            )
        if tuple(self.common_realizer_identities) != COMMON_REALIZER_IDENTITIES:
            raise ContractError(
                "paired arms must use the frozen common realizers"
            )
        if (
            self.guidance.compatible_realizer_identities
            != self.no_guidance.compatible_realizer_identities
            or self.guidance.compatible_realizer_identities
            != self.common_realizer_identities
        ):
            raise ContractError(
                "paired arms expose different realizer inventories"
            )

    @property
    def arms(
        self,
    ) -> tuple[
        AutoencoderGuidedCanonicalConstructor,
        AutoencoderGuidedCanonicalConstructor,
    ]:
        return (self.guidance, self.no_guidance)


def make_autoencoder_guidance_pair(
    base_constructor: RoundTripConstructor | None = None,
    *,
    guidance_applicator: CanonicalGuidanceApplicator | None = None,
    guidance_loader: GuidanceLoader = load_frozen_autoencoder_guidance,
    state_path: Path = DEFAULT_AUTOENCODER_STATE_PATH,
) -> AutoencoderGuidancePair:
    """Create guidance/no-guidance arms over one shared base constructor."""

    if base_constructor is None:
        from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
            TypedDeonticCanonicalConstructor,
        )

        base_constructor = TypedDeonticCanonicalConstructor()
    guidance = AutoencoderGuidedCanonicalConstructor(
        base_constructor,
        arm=AutoencoderGuidanceArm.GUIDANCE,
        guidance_applicator=guidance_applicator,
        guidance_loader=guidance_loader,
        state_path=state_path,
    )
    no_guidance = AutoencoderGuidedCanonicalConstructor(
        base_constructor,
        arm=AutoencoderGuidanceArm.NO_GUIDANCE,
        guidance_applicator=None,
        guidance_loader=guidance_loader,
        state_path=state_path,
    )
    return AutoencoderGuidancePair(guidance, no_guidance)


# Discoverable aliases for runner code that uses "create" or "paired arms".
create_autoencoder_guidance_pair = make_autoencoder_guidance_pair
paired_autoencoder_guidance_arms = make_autoencoder_guidance_pair
AutoencoderGuidedConstructor = AutoencoderGuidedCanonicalConstructor


assert isinstance(
    AutoencoderGuidedCanonicalConstructor(
        arm=AutoencoderGuidanceArm.NO_GUIDANCE
    ),
    RoundTripConstructor,
)


__all__ = [
    "AUTOENCODER_GUIDED_CANONICAL_CONSTRUCTOR_INTERFACE",
    "COMMON_REALIZER_IDENTITIES",
    "DEFAULT_AUTOENCODER_STATE_PATH",
    "PINNED_AUTOENCODER_DECLARED_ARCHITECTURE",
    "PINNED_AUTOENCODER_EFFECTIVE_ARCHITECTURE",
    "PINNED_AUTOENCODER_STATE_CID",
    "PINNED_AUTOENCODER_STATE_SCHEMA",
    "PINNED_AUTOENCODER_STATE_SHA256",
    "AutoencoderCompositionStatus",
    "AutoencoderGuidanceArm",
    "AutoencoderGuidanceDiagnostics",
    "AutoencoderGuidancePair",
    "AutoencoderGuidedCanonicalConstructor",
    "AutoencoderGuidedConstruction",
    "AutoencoderGuidedConstructor",
    "CanonicalFieldChange",
    "CanonicalGuidanceApplicator",
    "CausalGuidanceApplication",
    "FrozenAutoencoderGuidance",
    "canonical_field_changes",
    "create_autoencoder_guidance_pair",
    "load_frozen_autoencoder_guidance",
    "make_autoencoder_guidance_pair",
    "paired_autoencoder_guidance_arms",
]
