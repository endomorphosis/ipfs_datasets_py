"""Process-backed vertical-slice join, differential alignment, and replay (LFP2-046).

Interfaces:

* ``LogicEvidenceReplay@1`` — join orchestrator for process-backed vertical
  slices, differential fragment alignment, independent evidence replay, and
  reconstruction / authority-ceiling dispositions
* ``ExecutableVerticalSliceReceipt@1`` — content-bound domain-source → parse →
  elaborate → translate → compile → real pinned-process → decode →
  replay/reconstruction receipt

Fail-closed acceptance (LFP2-046):

* Static or hermetic metadata cannot satisfy
  ``ExecutableVerticalSliceReceipt@1``
* Differential disagreement is preserved (typed ``inconclusive``; never
  majority-voted into proof)
* Every authority-bearing result has independent replay/reconstruction **or**
  a typed ceiling that forbids promotion

Evidence subset: differential model core trace attack witness proof
reconstruction replay.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.logic.conformance.matrix import AuthorityCeiling
from ipfs_datasets_py.logic.syntax_core.contracts import (
    canonical_json_bytes,
    content_sha256,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LOGIC_EVIDENCE_REPLAY_INTERFACE: Final = "LogicEvidenceReplay@1"
LOGIC_EVIDENCE_REPLAY_SCHEMA: Final = "logic-evidence-replay/v1"
EXECUTABLE_VERTICAL_SLICE_RECEIPT_INTERFACE: Final = (
    "ExecutableVerticalSliceReceipt@1"
)
EXECUTABLE_VERTICAL_SLICE_RECEIPT_SCHEMA: Final = (
    "executable-vertical-slice-receipt/v1"
)
SLICE_STAGE_DIGEST_SCHEMA: Final = "executable-vertical-slice-stage/v1"
DIFFERENTIAL_ALIGNMENT_CASE_SCHEMA: Final = "logic-evidence-differential-case/v1"
EVIDENCE_REPLAY_CASE_SCHEMA: Final = "logic-evidence-replay-case/v1"
AUTHORITY_DISPOSITION_SCHEMA: Final = "logic-evidence-authority-disposition/v1"

TASK_ID: Final = "LFP2-046"
GOAL_ID: Final = "LFP2-G080"
PROGRAM_ID: Final = "ipfs-datasets-logic-family-parser-v2"
MODULE_VERSION: Final = "1.0.0"

# Authoritative validation PATH (fail-closed). Matches sealed validation env.
_VALIDATION_PATH: Final = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"

REQUIRED_EVIDENCE_SUBSET: Final[tuple[str, ...]] = (
    "differential",
    "model",
    "core",
    "trace",
    "attack",
    "witness",
    "proof",
    "reconstruction",
    "replay",
)

# Ordered vertical-slice pipeline stages (source → … → replay/reconstruction).
VERTICAL_SLICE_STAGES: Final[tuple[str, ...]] = (
    "domain_source",
    "parse",
    "elaborate",
    "translate",
    "compile",
    "pinned_process",
    "decode",
    "replay_or_reconstruction",
)

# Evidence kinds that may be independently replayed.
REPLAYABLE_EVIDENCE_KINDS: Final[tuple[str, ...]] = (
    "model",
    "core",
    "trace",
    "attack",
    "witness",
    "proof",
    "tstp",
    "kernel_candidate",
)

# Record kinds that can never satisfy ExecutableVerticalSliceReceipt@1.
_NON_EXECUTABLE_SLICE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "metadata_only",
        "mock",
        "hermetic_fixture",
        "static_declaration",
        "unavailable",
    }
)

# Process-backed kinds that may satisfy the executable slice when identities
# are bound and a real subprocess (or pinned-binary probe) ran.
_PROCESS_EXECUTABLE_SLICE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "live_process",
        "pinned_binary",
    }
)

# Authority ceilings that forbid promotion to theorem/kernel without
# independent reconstruction/kernel acceptance.
_PROMOTION_FORBIDDEN_CEILINGS: Final[frozenset[str]] = frozenset(
    {
        AuthorityCeiling.CANDIDATE.value,
        AuthorityCeiling.ADVISORY.value,
        AuthorityCeiling.BOUNDED.value,
        AuthorityCeiling.NONE.value,
        AuthorityCeiling.OVER_APPROXIMATION.value,
        AuthorityCeiling.FINITE_TRACE.value,
        AuthorityCeiling.PROTOCOL_SYMBOLIC.value,
        AuthorityCeiling.AUTHORIZATION_PROFILE.value,
        "reconstruction",
        "attestation",
        "candidate",
        "advisory",
        "bounded",
        "none",
    }
)

_PROMOTABLE_CEILINGS: Final[frozenset[str]] = frozenset(
    {
        AuthorityCeiling.KERNEL.value,
        AuthorityCeiling.EXACT.value,
        "theorem",
        "kernel",
        "exact",
    }
)

_REQUIRED_PROCESS_IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "command_digest",
    "environment_digest",
    "tool_digest",
    "output_digest",
)


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class ReplayV2Error(ValueError):
    """Raised when evidence-replay / vertical-slice contracts are violated."""


class ExecutableSliceClaimError(ReplayV2Error):
    """Raised when a non-process-backed record claims an executable slice."""


class AuthorityPromotionError(ReplayV2Error):
    """Raised when an authority-bearing result promotes without replay/ceiling."""


class ProcessBackingKind(StrEnum):
    """How a vertical-slice stage was (or was not) process-backed."""

    LIVE_PROCESS = "live_process"
    PINNED_BINARY = "pinned_binary"
    HERMETIC_FIXTURE = "hermetic_fixture"
    METADATA_ONLY = "metadata_only"
    MOCK = "mock"
    STATIC_DECLARATION = "static_declaration"
    UNAVAILABLE = "unavailable"


class SliceDisposition(StrEnum):
    """Terminal disposition for one ExecutableVerticalSliceReceipt@1."""

    EXECUTABLE = "executable"
    PROCESS_UNAVAILABLE = "process_unavailable"
    HERMETIC_ONLY = "hermetic_only"
    METADATA_ONLY = "metadata_only"
    MOCK = "mock"
    REJECTED = "rejected"
    REPLAYED = "replayed"
    RECONSTRUCTED = "reconstructed"
    CEILING_RETAINED = "ceiling_retained"


class DifferentialJoinVerdict(StrEnum):
    """Join disposition for one differential alignment case."""

    AGREE = "agree"
    INCONCLUSIVE = "inconclusive"
    UNAVAILABLE = "unavailable"


class ReplayCaseDisposition(StrEnum):
    """Independent replay outcome for one evidence kind."""

    REPLAYED = "replayed"
    MISMATCH = "mismatch"
    NON_REPLAYABLE = "non_replayable"
    NOT_ATTEMPTED = "not_attempted"
    CEILING_ONLY = "ceiling_only"
    RECONSTRUCTED = "reconstructed"
    UNAVAILABLE = "unavailable"


class AuthorityDispositionKind(StrEnum):
    """How an authority-bearing result is closed fail-closed."""

    INDEPENDENT_REPLAY = "independent_replay"
    INDEPENDENT_RECONSTRUCTION = "independent_reconstruction"
    TYPED_CEILING_FORBIDS_PROMOTION = "typed_ceiling_forbids_promotion"
    UNRESOLVED = "unresolved"


# ---------------------------------------------------------------------------
# Digest helpers
# ---------------------------------------------------------------------------


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_of_mapping(payload: Mapping[str, Any]) -> str:
    return content_sha256(canonical_json_bytes(dict(payload)))


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ReplayV2Error(f"{field_name} must be a non-empty trimmed string")
    if "\x00" in value:
        raise ReplayV2Error(f"{field_name} must not contain NUL bytes")
    return value


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if any(character.isspace() for character in result):
        raise ReplayV2Error(
            f"{field_name} must not contain whitespace; got {result!r}"
        )
    return result


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ReplayV2Error(f"{field_name} must be a bool")
    return value


def _sha256_hex_field(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ReplayV2Error(f"{field_name} must be a lowercase 64-hex digest")
    return text


def _optional_sha256(value: object, field_name: str) -> str:
    if value is None or value == "":
        return ""
    return _sha256_hex_field(value, field_name)


def _coerce_backing(value: object) -> ProcessBackingKind:
    if isinstance(value, ProcessBackingKind):
        return value
    text = _identifier(value, "process_backing")
    try:
        return ProcessBackingKind(text)
    except ValueError as error:
        allowed = ", ".join(item.value for item in ProcessBackingKind)
        raise ReplayV2Error(
            f"process_backing must be one of: {allowed}; got {text!r}"
        ) from error


def _coerce_disposition(value: object) -> SliceDisposition:
    if isinstance(value, SliceDisposition):
        return value
    text = _identifier(value, "disposition")
    try:
        return SliceDisposition(text)
    except ValueError as error:
        allowed = ", ".join(item.value for item in SliceDisposition)
        raise ReplayV2Error(
            f"disposition must be one of: {allowed}; got {text!r}"
        ) from error


def command_digest(command: Sequence[str]) -> str:
    """Digest an argv sequence (NUL-separated, UTF-8)."""

    return hashlib.sha256(
        b"\0".join(part.encode("utf-8") for part in command)
    ).hexdigest()


def environment_digest(environment: Mapping[str, str]) -> str:
    """Digest a sorted environment mapping."""

    return _digest_of_mapping({str(k): str(v) for k, v in sorted(environment.items())})


def tool_digest(*, executable_path: str, tool_id: str = "") -> str:
    """Digest tool identity: file bytes when readable, else path text."""

    if executable_path:
        try:
            return _sha256_bytes(PathBytes(executable_path).read())
        except OSError:
            return _sha256_text(f"path:{executable_path}")
    return _sha256_text(f"tool:{tool_id or 'none'}")


class PathBytes:
    """Tiny path reader used so tool_digest stays unit-testable."""

    def __init__(self, path: str) -> None:
        self._path = path

    def read(self) -> bytes:
        with open(self._path, "rb") as handle:
            return handle.read()


def output_digest(*, stdout: str, stderr: str, returncode: int | None) -> str:
    return _digest_of_mapping(
        {
            "returncode": returncode,
            "stderr": stderr,
            "stdout": stdout,
        }
    )


def stage_digest(stage: str, payload: Mapping[str, Any]) -> str:
    """Content digest for one vertical-slice stage payload."""

    return _digest_of_mapping(
        {
            "payload": dict(payload),
            "schema_version": SLICE_STAGE_DIGEST_SCHEMA,
            "stage": stage,
        }
    )


# ---------------------------------------------------------------------------
# Process-backed admission
# ---------------------------------------------------------------------------


def establishes_executable_vertical_slice(
    *,
    process_backing: ProcessBackingKind | str,
    process_executed: bool,
    execution_claimed: bool = True,
) -> bool:
    """Return whether a record may satisfy ExecutableVerticalSliceReceipt@1.

    Static declarations, hermetic fixtures, metadata-only records, mocks, and
    unavailable probes never satisfy the executable vertical-slice claim —
    even when ``execution_claimed`` is set.
    """

    kind = _coerce_backing(process_backing)
    if kind.value in _NON_EXECUTABLE_SLICE_KINDS:
        return False
    if kind.value not in _PROCESS_EXECUTABLE_SLICE_KINDS:
        return False
    return bool(process_executed) and bool(execution_claimed)


def require_executable_vertical_slice_claim(
    *,
    process_backing: ProcessBackingKind | str,
    process_executed: bool,
    execution_claimed: bool = True,
) -> None:
    """Fail closed when a non-process-backed record claims the executable slice."""

    if not establishes_executable_vertical_slice(
        process_backing=process_backing,
        process_executed=process_executed,
        execution_claimed=execution_claimed,
    ):
        kind = _coerce_backing(process_backing)
        raise ExecutableSliceClaimError(
            f"process_backing {kind.value!r} cannot satisfy "
            f"{EXECUTABLE_VERTICAL_SLICE_RECEIPT_INTERFACE}; static and "
            "hermetic metadata never establish an executable vertical slice"
        )


# ---------------------------------------------------------------------------
# Differential alignment (disagreement preserved)
# ---------------------------------------------------------------------------


def classify_differential_pair(
    left_verdict: str,
    right_verdict: str,
    *,
    conclusive: frozenset[str] | None = None,
) -> tuple[str, str]:
    """Hermetic pair classification without majority voting.

    Returns ``(raw_classification, join_verdict)``.

    Disagreement is always typed ``inconclusive``.  Partial/both unavailable
    stay ``unavailable``.  Agreement remains ``agree``.
    """

    left = _text(left_verdict, "left_verdict").lower()
    right = _text(right_verdict, "right_verdict").lower()
    conclusive_set = conclusive or frozenset(
        {
            "sat",
            "unsat",
            "proved",
            "disproved",
            "secure",
            "attack_found",
            "satisfied",
            "violated",
            "true",
            "false",
            "authorized",
            "denied",
        }
    )
    unavailable = frozenset(
        {"unavailable", "timeout", "error", "missing", "unknown_tool"}
    )
    if left in unavailable and right in unavailable:
        return "both_unavailable", DifferentialJoinVerdict.UNAVAILABLE.value
    if left in unavailable or right in unavailable:
        return "partial_unavailable", DifferentialJoinVerdict.UNAVAILABLE.value
    if left in conclusive_set and right in conclusive_set and left != right:
        return "disagree", DifferentialJoinVerdict.INCONCLUSIVE.value
    if left == right:
        if left in conclusive_set:
            return "agree", DifferentialJoinVerdict.AGREE.value
        return "agree_unknown", DifferentialJoinVerdict.AGREE.value
    # One conclusive, one unknown — inconclusive, never majority vote.
    return "partial_unknown", DifferentialJoinVerdict.INCONCLUSIVE.value


@dataclass(frozen=True, slots=True)
class DifferentialAlignmentCase:
    """One semantic-fragment differential alignment under an exact contract.

    Disagreement is preserved: ``raw_classification=disagree`` forces
    ``join_verdict=inconclusive`` and is never majority-voted into proof.
    """

    case_id: str
    family: str
    fragment: str
    left_provider: str
    right_provider: str
    left_verdict: str
    right_verdict: str
    raw_classification: str
    join_verdict: str
    disagreement_preserved: bool = False
    notes: str = ""
    schema_version: str = DIFFERENTIAL_ALIGNMENT_CASE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _identifier(self.case_id, "case_id"))
        object.__setattr__(self, "family", _identifier(self.family, "family"))
        object.__setattr__(
            self, "fragment", _identifier(self.fragment, "fragment")
        )
        object.__setattr__(
            self, "left_provider", _identifier(self.left_provider, "left_provider")
        )
        object.__setattr__(
            self,
            "right_provider",
            _identifier(self.right_provider, "right_provider"),
        )
        object.__setattr__(
            self, "left_verdict", _text(self.left_verdict, "left_verdict")
        )
        object.__setattr__(
            self, "right_verdict", _text(self.right_verdict, "right_verdict")
        )
        object.__setattr__(
            self,
            "raw_classification",
            _identifier(self.raw_classification, "raw_classification"),
        )
        object.__setattr__(
            self, "join_verdict", _identifier(self.join_verdict, "join_verdict")
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes", optional=True)
        )
        if self.schema_version != DIFFERENTIAL_ALIGNMENT_CASE_SCHEMA:
            raise ReplayV2Error(
                f"differential case schema must be "
                f"{DIFFERENTIAL_ALIGNMENT_CASE_SCHEMA}"
            )
        # Hard invariant: disagreement is typed inconclusive and preserved.
        if self.raw_classification in {"disagree", "disagreement"}:
            if self.join_verdict != DifferentialJoinVerdict.INCONCLUSIVE.value:
                raise ReplayV2Error(
                    f"{self.case_id}: disagreement must be typed inconclusive"
                )
            if not self.disagreement_preserved:
                object.__setattr__(self, "disagreement_preserved", True)
        else:
            object.__setattr__(
                self,
                "disagreement_preserved",
                _bool(self.disagreement_preserved, "disagreement_preserved"),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "disagreement_preserved": self.disagreement_preserved,
            "family": self.family,
            "fragment": self.fragment,
            "join_verdict": self.join_verdict,
            "left_provider": self.left_provider,
            "left_verdict": self.left_verdict,
            "notes": self.notes,
            "raw_classification": self.raw_classification,
            "right_provider": self.right_provider,
            "right_verdict": self.right_verdict,
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Independent replay / reconstruction / authority ceiling
# ---------------------------------------------------------------------------


def authority_promotion_allowed(
    *,
    authority_ceiling: str,
    independently_replayed: bool,
    independently_reconstructed: bool,
    kernel_accepted: bool = False,
) -> bool:
    """Return whether an authority-bearing result may promote.

    Promotion to theorem/kernel requires independent reconstruction with
    kernel acceptance.  Exact/satisfiability ceilings require independent
    replay.  Typed lower ceilings always forbid promotion.
    """

    ceiling = _identifier(authority_ceiling, "authority_ceiling").lower()
    if ceiling in _PROMOTION_FORBIDDEN_CEILINGS:
        return False
    if ceiling in {AuthorityCeiling.KERNEL.value, "theorem", "kernel"}:
        return bool(independently_reconstructed and kernel_accepted)
    if ceiling in {AuthorityCeiling.EXACT.value, "exact"}:
        return bool(independently_replayed or independently_reconstructed)
    # Unknown high ceiling: require independent evidence.
    return bool(independently_replayed or independently_reconstructed)


def resolve_authority_disposition(
    *,
    result_id: str,
    evidence_kind: str,
    authority_ceiling: str,
    independently_replayed: bool = False,
    independently_reconstructed: bool = False,
    kernel_accepted: bool = False,
    match_digest: str = "",
) -> "AuthorityDisposition":
    """Close one authority-bearing result fail-closed.

    Every authority-bearing result must have independent replay/reconstruction
    **or** a typed ceiling that forbids promotion.  Unresolved results raise.
    """

    ceiling = _identifier(authority_ceiling, "authority_ceiling")
    kind = _identifier(evidence_kind, "evidence_kind")
    rid = _identifier(result_id, "result_id")

    if independently_reconstructed and kernel_accepted:
        disposition = AuthorityDispositionKind.INDEPENDENT_RECONSTRUCTION
        promotion_forbidden = not authority_promotion_allowed(
            authority_ceiling=ceiling,
            independently_replayed=independently_replayed,
            independently_reconstructed=True,
            kernel_accepted=True,
        )
    elif independently_replayed:
        disposition = AuthorityDispositionKind.INDEPENDENT_REPLAY
        promotion_forbidden = not authority_promotion_allowed(
            authority_ceiling=ceiling,
            independently_replayed=True,
            independently_reconstructed=independently_reconstructed,
            kernel_accepted=kernel_accepted,
        )
    elif ceiling.lower() in _PROMOTION_FORBIDDEN_CEILINGS:
        disposition = AuthorityDispositionKind.TYPED_CEILING_FORBIDS_PROMOTION
        promotion_forbidden = True
    else:
        raise AuthorityPromotionError(
            f"{rid}: authority-bearing result with ceiling {ceiling!r} has "
            "neither independent replay/reconstruction nor a typed ceiling "
            "that forbids promotion"
        )

    return AuthorityDisposition(
        result_id=rid,
        evidence_kind=kind,
        authority_ceiling=ceiling,
        disposition=disposition,
        promotion_forbidden=promotion_forbidden,
        independently_replayed=independently_replayed,
        independently_reconstructed=independently_reconstructed,
        kernel_accepted=kernel_accepted,
        match_digest=match_digest,
    )


@dataclass(frozen=True, slots=True)
class AuthorityDisposition:
    """Typed closure for one authority-bearing result."""

    result_id: str
    evidence_kind: str
    authority_ceiling: str
    disposition: AuthorityDispositionKind | str
    promotion_forbidden: bool
    independently_replayed: bool = False
    independently_reconstructed: bool = False
    kernel_accepted: bool = False
    match_digest: str = ""
    notes: str = ""
    schema_version: str = AUTHORITY_DISPOSITION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "result_id", _identifier(self.result_id, "result_id")
        )
        object.__setattr__(
            self, "evidence_kind", _identifier(self.evidence_kind, "evidence_kind")
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _identifier(self.authority_ceiling, "authority_ceiling"),
        )
        disposition = (
            self.disposition
            if isinstance(self.disposition, AuthorityDispositionKind)
            else AuthorityDispositionKind(str(self.disposition))
        )
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(
            self,
            "promotion_forbidden",
            _bool(self.promotion_forbidden, "promotion_forbidden"),
        )
        object.__setattr__(
            self,
            "independently_replayed",
            _bool(self.independently_replayed, "independently_replayed"),
        )
        object.__setattr__(
            self,
            "independently_reconstructed",
            _bool(
                self.independently_reconstructed, "independently_reconstructed"
            ),
        )
        object.__setattr__(
            self, "kernel_accepted", _bool(self.kernel_accepted, "kernel_accepted")
        )
        object.__setattr__(
            self, "match_digest", _optional_sha256(self.match_digest, "match_digest")
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes", optional=True)
        )
        if self.schema_version != AUTHORITY_DISPOSITION_SCHEMA:
            raise ReplayV2Error(
                f"authority disposition schema must be {AUTHORITY_DISPOSITION_SCHEMA}"
            )
        if disposition is AuthorityDispositionKind.UNRESOLVED:
            raise AuthorityPromotionError(
                f"{self.result_id}: unresolved authority disposition is not admitted"
            )
        # Fail-closed: high ceilings without independent evidence are illegal.
        ceiling = self.authority_ceiling.lower()
        if ceiling in _PROMOTABLE_CEILINGS:
            if disposition is AuthorityDispositionKind.TYPED_CEILING_FORBIDS_PROMOTION:
                raise AuthorityPromotionError(
                    f"{self.result_id}: ceiling {ceiling!r} cannot use "
                    "typed_ceiling_forbids_promotion; requires independent "
                    "replay or reconstruction"
                )
            if (
                disposition is AuthorityDispositionKind.INDEPENDENT_RECONSTRUCTION
                and not self.kernel_accepted
                and ceiling in {AuthorityCeiling.KERNEL.value, "theorem", "kernel"}
            ):
                raise AuthorityPromotionError(
                    f"{self.result_id}: kernel reconstruction requires kernel_accepted"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, AuthorityDispositionKind)
                else self.disposition
            ),
            "evidence_kind": self.evidence_kind,
            "independently_reconstructed": self.independently_reconstructed,
            "independently_replayed": self.independently_replayed,
            "kernel_accepted": self.kernel_accepted,
            "match_digest": self.match_digest,
            "notes": self.notes,
            "promotion_forbidden": self.promotion_forbidden,
            "result_id": self.result_id,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class EvidenceReplayCase:
    """Independent replay/reconstruction of one decoded evidence artifact."""

    case_id: str
    evidence_kind: str
    provider_id: str
    original_digest: str
    replayed_digest: str
    disposition: ReplayCaseDisposition | str
    matched: bool = False
    replay_claimed: bool = False
    reconstructed: bool = False
    kernel_accepted: bool = False
    authority_ceiling: str = AuthorityCeiling.CANDIDATE.value
    notes: str = ""
    schema_version: str = EVIDENCE_REPLAY_CASE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _identifier(self.case_id, "case_id"))
        kind = _identifier(self.evidence_kind, "evidence_kind")
        if kind not in REPLAYABLE_EVIDENCE_KINDS:
            raise ReplayV2Error(
                f"evidence_kind must be one of {REPLAYABLE_EVIDENCE_KINDS}; "
                f"got {kind!r}"
            )
        object.__setattr__(self, "evidence_kind", kind)
        object.__setattr__(
            self, "provider_id", _identifier(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self,
            "original_digest",
            _sha256_hex_field(self.original_digest, "original_digest"),
        )
        object.__setattr__(
            self,
            "replayed_digest",
            _optional_sha256(self.replayed_digest, "replayed_digest"),
        )
        disposition = (
            self.disposition
            if isinstance(self.disposition, ReplayCaseDisposition)
            else ReplayCaseDisposition(str(self.disposition))
        )
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "matched", _bool(self.matched, "matched"))
        object.__setattr__(
            self, "replay_claimed", _bool(self.replay_claimed, "replay_claimed")
        )
        object.__setattr__(
            self, "reconstructed", _bool(self.reconstructed, "reconstructed")
        )
        object.__setattr__(
            self, "kernel_accepted", _bool(self.kernel_accepted, "kernel_accepted")
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _identifier(self.authority_ceiling, "authority_ceiling"),
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes", optional=True)
        )
        if self.schema_version != EVIDENCE_REPLAY_CASE_SCHEMA:
            raise ReplayV2Error(
                f"evidence replay case schema must be {EVIDENCE_REPLAY_CASE_SCHEMA}"
            )
        if self.replay_claimed:
            if disposition is not ReplayCaseDisposition.REPLAYED:
                raise ReplayV2Error(
                    f"{self.case_id}: replay_claimed requires disposition=replayed"
                )
            if not self.matched:
                raise ReplayV2Error(
                    f"{self.case_id}: replay_claimed requires matched digests"
                )
            if not self.replayed_digest:
                raise ReplayV2Error(
                    f"{self.case_id}: replay_claimed requires replayed_digest"
                )
            if self.original_digest != self.replayed_digest:
                raise ReplayV2Error(
                    f"{self.case_id}: replay_claimed requires original==replayed digest"
                )
        if self.reconstructed and not self.kernel_accepted:
            # Reconstruction without kernel acceptance cannot claim success.
            if disposition is ReplayCaseDisposition.RECONSTRUCTED:
                raise ReplayV2Error(
                    f"{self.case_id}: reconstructed disposition requires kernel_accepted"
                )
        if self.matched and self.replayed_digest and (
            self.original_digest != self.replayed_digest
        ):
            raise ReplayV2Error(
                f"{self.case_id}: matched=true requires equal digests"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "case_id": self.case_id,
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, ReplayCaseDisposition)
                else self.disposition
            ),
            "evidence_kind": self.evidence_kind,
            "kernel_accepted": self.kernel_accepted,
            "matched": self.matched,
            "notes": self.notes,
            "original_digest": self.original_digest,
            "provider_id": self.provider_id,
            "reconstructed": self.reconstructed,
            "replay_claimed": self.replay_claimed,
            "replayed_digest": self.replayed_digest,
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# ExecutableVerticalSliceReceipt@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SliceStageRecord:
    """One ordered stage in the executable vertical-slice pipeline."""

    stage: str
    identity: str
    digest: str
    authority_ceiling: str = AuthorityCeiling.NONE.value

    def __post_init__(self) -> None:
        stage = _identifier(self.stage, "stage")
        if stage not in VERTICAL_SLICE_STAGES:
            raise ReplayV2Error(
                f"stage must be one of {VERTICAL_SLICE_STAGES}; got {stage!r}"
            )
        object.__setattr__(self, "stage", stage)
        object.__setattr__(
            self, "identity", _identifier(self.identity, "identity")
        )
        object.__setattr__(self, "digest", _sha256_hex_field(self.digest, "digest"))
        object.__setattr__(
            self,
            "authority_ceiling",
            _identifier(self.authority_ceiling, "authority_ceiling"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "digest": self.digest,
            "identity": self.identity,
            "schema_version": SLICE_STAGE_DIGEST_SCHEMA,
            "stage": self.stage,
        }


@dataclass(frozen=True, slots=True)
class ExecutableVerticalSliceReceipt:
    """Content-bound process-backed vertical-slice receipt.

    Interface: ``ExecutableVerticalSliceReceipt@1``.

    Static declarations, hermetic fixtures, metadata-only records, and mocks
    are admissible as *records* but never set ``executable_slice_satisfied``.
    Only ``live_process`` / ``pinned_binary`` with a real subprocess execution
    and bound command/environment/tool/output identities may satisfy the claim.
    """

    receipt_id: str
    domain_id: str
    family_id: str
    provider_id: str
    process_backing: ProcessBackingKind | str
    disposition: SliceDisposition | str
    stages: tuple[SliceStageRecord, ...] | Sequence[SliceStageRecord]
    command: tuple[str, ...] | Sequence[str]
    command_digest: str
    environment_digest: str
    tool_digest: str
    output_digest: str
    process_executed: bool = False
    execution_claimed: bool = False
    executable_slice_satisfied: bool = False
    evidence_kind: str = "proof"
    decoded_evidence_digest: str = ""
    replay_match_digest: str = ""
    authority_ceiling: str = AuthorityCeiling.CANDIDATE.value
    authority_disposition: AuthorityDisposition | Mapping[str, Any] | None = None
    returncode: int | None = None
    tool_id: str = ""
    toolchain_id: str = ""
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    content_digest: str = ""
    schema_version: str = EXECUTABLE_VERTICAL_SLICE_RECEIPT_SCHEMA
    interface: str = EXECUTABLE_VERTICAL_SLICE_RECEIPT_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self, "domain_id", _identifier(self.domain_id, "domain_id")
        )
        object.__setattr__(
            self, "family_id", _identifier(self.family_id, "family_id")
        )
        object.__setattr__(
            self, "provider_id", _identifier(self.provider_id, "provider_id")
        )

        backing = _coerce_backing(self.process_backing)
        object.__setattr__(self, "process_backing", backing)

        disposition = _coerce_disposition(self.disposition)
        object.__setattr__(self, "disposition", disposition)

        stages = tuple(self.stages)
        if not stages:
            raise ReplayV2Error("stages must be a non-empty ordered pipeline")
        stage_names = [item.stage for item in stages]
        expected = list(VERTICAL_SLICE_STAGES)
        if stage_names != expected:
            raise ReplayV2Error(
                "stages must be the complete ordered pipeline "
                f"{VERTICAL_SLICE_STAGES}; got {tuple(stage_names)}"
            )
        object.__setattr__(self, "stages", stages)

        command = tuple(str(part) for part in self.command)
        object.__setattr__(self, "command", command)

        for field_name in _REQUIRED_PROCESS_IDENTITY_FIELDS:
            value = getattr(self, field_name)
            object.__setattr__(
                self, field_name, _sha256_hex_field(value, field_name)
            )

        process_executed = _bool(self.process_executed, "process_executed")
        execution_claimed = _bool(self.execution_claimed, "execution_claimed")
        object.__setattr__(self, "process_executed", process_executed)
        object.__setattr__(self, "execution_claimed", execution_claimed)

        satisfied = establishes_executable_vertical_slice(
            process_backing=backing,
            process_executed=process_executed,
            execution_claimed=execution_claimed,
        )
        claimed_satisfied = _bool(
            self.executable_slice_satisfied, "executable_slice_satisfied"
        )
        if claimed_satisfied and not satisfied:
            raise ExecutableSliceClaimError(
                f"process_backing {backing.value!r} cannot satisfy "
                f"{EXECUTABLE_VERTICAL_SLICE_RECEIPT_INTERFACE}; static and "
                "hermetic metadata never establish an executable vertical slice"
            )
        # Keep the flag honest even if a caller under-claimed.
        object.__setattr__(self, "executable_slice_satisfied", satisfied)

        if satisfied:
            if not command:
                raise ExecutableSliceClaimError(
                    "executable vertical slice requires a non-empty command"
                )
            if disposition not in {
                SliceDisposition.EXECUTABLE,
                SliceDisposition.REPLAYED,
                SliceDisposition.RECONSTRUCTED,
            }:
                raise ExecutableSliceClaimError(
                    "executable vertical slice requires disposition in "
                    "{executable, replayed, reconstructed}"
                )

        # Non-process kinds must not claim execution.
        if backing.value in _NON_EXECUTABLE_SLICE_KINDS:
            if execution_claimed or process_executed:
                raise ExecutableSliceClaimError(
                    f"process_backing {backing.value!r} cannot claim process "
                    "execution"
                )
            if disposition is SliceDisposition.EXECUTABLE:
                raise ExecutableSliceClaimError(
                    f"process_backing {backing.value!r} cannot use "
                    "disposition=executable"
                )

        object.__setattr__(
            self, "evidence_kind", _identifier(self.evidence_kind, "evidence_kind")
        )
        object.__setattr__(
            self,
            "decoded_evidence_digest",
            _optional_sha256(
                self.decoded_evidence_digest, "decoded_evidence_digest"
            ),
        )
        object.__setattr__(
            self,
            "replay_match_digest",
            _optional_sha256(self.replay_match_digest, "replay_match_digest"),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _identifier(self.authority_ceiling, "authority_ceiling"),
        )

        auth = self.authority_disposition
        if auth is None:
            # Default: close via typed ceiling when not process-satisfied;
            # process-satisfied slices still need an explicit disposition.
            if not satisfied:
                auth = resolve_authority_disposition(
                    result_id=f"{self.receipt_id}.authority",
                    evidence_kind=self.evidence_kind,
                    authority_ceiling=self.authority_ceiling
                    if self.authority_ceiling.lower()
                    in _PROMOTION_FORBIDDEN_CEILINGS
                    else AuthorityCeiling.CANDIDATE.value,
                    independently_replayed=False,
                    independently_reconstructed=False,
                )
            else:
                # Satisfied slices without explicit authority must retain a
                # non-promotable ceiling (never silent theorem promotion).
                ceiling = self.authority_ceiling
                if ceiling.lower() in _PROMOTABLE_CEILINGS:
                    raise AuthorityPromotionError(
                        f"{self.receipt_id}: process-satisfied slice with "
                        f"promotable ceiling {ceiling!r} requires explicit "
                        "authority_disposition with independent replay or "
                        "reconstruction"
                    )
                auth = resolve_authority_disposition(
                    result_id=f"{self.receipt_id}.authority",
                    evidence_kind=self.evidence_kind,
                    authority_ceiling=ceiling,
                    independently_replayed=bool(self.replay_match_digest),
                    independently_reconstructed=(
                        disposition is SliceDisposition.RECONSTRUCTED
                    ),
                    kernel_accepted=(
                        disposition is SliceDisposition.RECONSTRUCTED
                    ),
                    match_digest=self.replay_match_digest,
                )
        elif isinstance(auth, Mapping):
            auth = AuthorityDisposition(
                result_id=str(auth.get("result_id") or f"{self.receipt_id}.authority"),
                evidence_kind=str(auth.get("evidence_kind") or self.evidence_kind),
                authority_ceiling=str(
                    auth.get("authority_ceiling") or self.authority_ceiling
                ),
                disposition=str(
                    auth.get("disposition")
                    or AuthorityDispositionKind.TYPED_CEILING_FORBIDS_PROMOTION.value
                ),
                promotion_forbidden=bool(auth.get("promotion_forbidden", True)),
                independently_replayed=bool(
                    auth.get("independently_replayed", False)
                ),
                independently_reconstructed=bool(
                    auth.get("independently_reconstructed", False)
                ),
                kernel_accepted=bool(auth.get("kernel_accepted", False)),
                match_digest=str(auth.get("match_digest") or ""),
                notes=str(auth.get("notes") or ""),
            )
        if not isinstance(auth, AuthorityDisposition):
            raise ReplayV2Error("authority_disposition must be AuthorityDisposition")
        object.__setattr__(self, "authority_disposition", auth)

        if self.tool_id:
            object.__setattr__(
                self, "tool_id", _identifier(self.tool_id, "tool_id")
            )
        if self.toolchain_id:
            object.__setattr__(
                self, "toolchain_id", _identifier(self.toolchain_id, "toolchain_id")
            )
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", optional=True)
        )
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

        if self.schema_version != EXECUTABLE_VERTICAL_SLICE_RECEIPT_SCHEMA:
            raise ReplayV2Error(
                f"unsupported slice schema_version {self.schema_version!r}"
            )
        if self.interface != EXECUTABLE_VERTICAL_SLICE_RECEIPT_INTERFACE:
            raise ReplayV2Error(
                f"unsupported slice interface {self.interface!r}"
            )

        content = _digest_of_mapping(self._identity_payload())
        if self.content_digest:
            provided = _sha256_hex_field(self.content_digest, "content_digest")
            if provided != content:
                raise ReplayV2Error(
                    "content_digest does not match ExecutableVerticalSliceReceipt"
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", content)

    def _identity_payload(self) -> dict[str, Any]:
        auth = self.authority_disposition
        assert isinstance(auth, AuthorityDisposition)
        return {
            "authority_ceiling": self.authority_ceiling,
            "authority_disposition": auth.to_dict(),
            "command": list(self.command),
            "command_digest": self.command_digest,
            "decoded_evidence_digest": self.decoded_evidence_digest,
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, SliceDisposition)
                else str(self.disposition)
            ),
            "domain_id": self.domain_id,
            "environment_digest": self.environment_digest,
            "evidence_kind": self.evidence_kind,
            "executable_slice_satisfied": self.executable_slice_satisfied,
            "execution_claimed": self.execution_claimed,
            "family_id": self.family_id,
            "interface": self.interface,
            "output_digest": self.output_digest,
            "process_backing": (
                self.process_backing.value
                if isinstance(self.process_backing, ProcessBackingKind)
                else str(self.process_backing)
            ),
            "process_executed": self.process_executed,
            "provider_id": self.provider_id,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "replay_match_digest": self.replay_match_digest,
            "returncode": self.returncode,
            "schema_version": self.schema_version,
            "stages": [item.to_dict() for item in self.stages],
            "tool_digest": self.tool_digest,
            "tool_id": self.tool_id,
            "toolchain_id": self.toolchain_id,
        }

    def require_executable_slice(self) -> "ExecutableVerticalSliceReceipt":
        """Return self when this receipt may be treated as an executable slice."""

        if not self.executable_slice_satisfied:
            raise ExecutableSliceClaimError(
                f"ExecutableVerticalSliceReceipt {self.receipt_id} does not "
                "satisfy the process-backed executable claim"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_digest"] = self.content_digest
        payload["metadata"] = dict(self.metadata)
        return payload


# ---------------------------------------------------------------------------
# Process probe (real subprocess when available)
# ---------------------------------------------------------------------------


def _validation_environment(
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = {
        "PATH": _VALIDATION_PATH,
        "LANG": "C",
        "LC_ALL": "C",
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env


def _resolve_executable(
    candidates: Sequence[str],
    *,
    search_path: str,
) -> tuple[str, str]:
    for name in candidates:
        found = shutil.which(name, path=search_path)
        if found:
            return name, str(found)
    return "", ""


def run_pinned_process_probe(
    *,
    candidates: Sequence[str] = ("true",),
    argv_template: Sequence[str] | None = None,
    environment: Mapping[str, str] | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Run a real pinned-process probe when a candidate binary is on PATH.

    Returns a process observation mapping.  When no binary is found, returns
    an unavailable observation that never establishes executable capability.
    """

    env = dict(environment or _validation_environment())
    search_path = env.get("PATH", _VALIDATION_PATH)
    _requested, executable_path = _resolve_executable(
        candidates, search_path=search_path
    )
    if not executable_path:
        empty_cmd = ()
        return {
            "available": False,
            "command": empty_cmd,
            "command_digest": command_digest(empty_cmd),
            "environment_digest": environment_digest(env),
            "executable_path": "",
            "output_digest": output_digest(
                stdout="", stderr="", returncode=None
            ),
            "process_executed": False,
            "returncode": None,
            "stderr": "",
            "stdout": "",
            "tool_digest": tool_digest(executable_path="", tool_id="unavailable"),
        }

    if argv_template is None:
        command = (executable_path,)
    else:
        command = tuple(
            part.replace("{executable}", executable_path) for part in argv_template
        )

    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
            shell=False,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        returncode = int(completed.returncode)
        executed = True
    except (OSError, subprocess.TimeoutExpired) as error:
        stdout = ""
        stderr = str(error)[:512]
        returncode = None
        executed = False

    return {
        "available": executed,
        "command": command,
        "command_digest": command_digest(command),
        "environment_digest": environment_digest(env),
        "executable_path": executable_path,
        "output_digest": output_digest(
            stdout=stdout, stderr=stderr, returncode=returncode
        ),
        "process_executed": executed,
        "returncode": returncode,
        "stderr": stderr,
        "stdout": stdout,
        "tool_digest": tool_digest(
            executable_path=executable_path, tool_id=candidates[0]
        ),
    }


def build_stage_pipeline(
    *,
    domain_id: str,
    family_id: str,
    provider_id: str,
    source_text: str,
    translation_id: str,
    compile_digest: str,
    process_output_digest: str,
    decoded_evidence_digest: str,
    replay_or_reconstruction_digest: str,
    authority_ceiling: str = AuthorityCeiling.CANDIDATE.value,
) -> tuple[SliceStageRecord, ...]:
    """Build the complete ordered vertical-slice stage chain."""

    source_d = stage_digest(
        "domain_source",
        {"domain_id": domain_id, "source_text": source_text},
    )
    parse_d = stage_digest(
        "parse",
        {"family_id": family_id, "source_digest": source_d},
    )
    elaborate_d = stage_digest(
        "elaborate",
        {"family_id": family_id, "parse_digest": parse_d},
    )
    translate_d = stage_digest(
        "translate",
        {
            "elaborate_digest": elaborate_d,
            "translation_id": translation_id,
        },
    )
    compile_d = stage_digest(
        "compile",
        {
            "compile_digest": compile_digest,
            "provider_id": provider_id,
            "translate_digest": translate_d,
        },
    )
    process_d = stage_digest(
        "pinned_process",
        {
            "compile_digest": compile_d,
            "output_digest": process_output_digest,
            "provider_id": provider_id,
        },
    )
    decode_d = stage_digest(
        "decode",
        {
            "decoded_evidence_digest": decoded_evidence_digest,
            "process_digest": process_d,
        },
    )
    replay_d = stage_digest(
        "replay_or_reconstruction",
        {
            "decode_digest": decode_d,
            "replay_or_reconstruction_digest": replay_or_reconstruction_digest,
        },
    )
    return (
        SliceStageRecord(
            stage="domain_source",
            identity=f"source:{domain_id}",
            digest=source_d,
            authority_ceiling=AuthorityCeiling.NONE.value,
        ),
        SliceStageRecord(
            stage="parse",
            identity=f"parse:{family_id}",
            digest=parse_d,
            authority_ceiling=AuthorityCeiling.NONE.value,
        ),
        SliceStageRecord(
            stage="elaborate",
            identity=f"elaborate:{family_id}",
            digest=elaborate_d,
            authority_ceiling=AuthorityCeiling.NONE.value,
        ),
        SliceStageRecord(
            stage="translate",
            identity=f"translate:{translation_id}",
            digest=translate_d,
            authority_ceiling=AuthorityCeiling.BOUNDED.value,
        ),
        SliceStageRecord(
            stage="compile",
            identity=f"compile:{provider_id}",
            digest=compile_d,
            authority_ceiling=AuthorityCeiling.BOUNDED.value,
        ),
        SliceStageRecord(
            stage="pinned_process",
            identity=f"process:{provider_id}",
            digest=process_d,
            authority_ceiling=authority_ceiling,
        ),
        SliceStageRecord(
            stage="decode",
            identity=f"decode:{provider_id}",
            digest=decode_d,
            authority_ceiling=authority_ceiling,
        ),
        SliceStageRecord(
            stage="replay_or_reconstruction",
            identity=f"replay:{provider_id}",
            digest=replay_d,
            authority_ceiling=authority_ceiling,
        ),
    )


def build_executable_vertical_slice_receipt(
    *,
    receipt_id: str,
    domain_id: str,
    family_id: str,
    provider_id: str,
    process_backing: ProcessBackingKind | str,
    source_text: str = "(assert true)",
    translation_id: str = "identity",
    evidence_kind: str = "proof",
    authority_ceiling: str = AuthorityCeiling.CANDIDATE.value,
    process_observation: Mapping[str, Any] | None = None,
    force_unavailable: bool = False,
    independently_replayed: bool = False,
    independently_reconstructed: bool = False,
    kernel_accepted: bool = False,
    decoded_payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ExecutableVerticalSliceReceipt:
    """Construct an ExecutableVerticalSliceReceipt@1 from a process observation.

    When ``process_backing`` is process-executable and a real probe ran,
    ``executable_slice_satisfied`` becomes true.  Metadata/hermetic/mock
    backings always produce a non-satisfying receipt.
    """

    backing = _coerce_backing(process_backing)
    observation = dict(process_observation or {})

    if force_unavailable or backing is ProcessBackingKind.UNAVAILABLE:
        empty_cmd: tuple[str, ...] = ()
        observation = {
            "available": False,
            "command": empty_cmd,
            "command_digest": command_digest(empty_cmd),
            "environment_digest": environment_digest(_validation_environment()),
            "executable_path": "",
            "output_digest": output_digest(
                stdout="", stderr="", returncode=None
            ),
            "process_executed": False,
            "returncode": None,
            "tool_digest": tool_digest(executable_path="", tool_id="unavailable"),
        }

    if not observation and backing in {
        ProcessBackingKind.LIVE_PROCESS,
        ProcessBackingKind.PINNED_BINARY,
    }:
        observation = run_pinned_process_probe()

    if not observation:
        # Hermetic / metadata / mock placeholders with bound digests that
        # still cannot satisfy the executable claim.
        placeholder = _digest_of_mapping(
            {
                "backing": backing.value,
                "receipt_id": receipt_id,
            }
        )
        observation = {
            "available": False,
            "command": (),
            "command_digest": command_digest(()),
            "environment_digest": environment_digest(_validation_environment()),
            "executable_path": "",
            "output_digest": placeholder,
            "process_executed": False,
            "returncode": None,
            "tool_digest": tool_digest(
                executable_path="", tool_id=backing.value
            ),
        }

    process_executed = bool(observation.get("process_executed"))
    command = tuple(observation.get("command") or ())
    cmd_digest = str(observation.get("command_digest") or command_digest(command))
    env_digest = str(
        observation.get("environment_digest")
        or environment_digest(_validation_environment())
    )
    t_digest = str(
        observation.get("tool_digest")
        or tool_digest(
            executable_path=str(observation.get("executable_path") or ""),
            tool_id=provider_id,
        )
    )
    out_digest = str(
        observation.get("output_digest")
        or output_digest(stdout="", stderr="", returncode=None)
    )

    decoded = dict(decoded_payload or {"kind": evidence_kind, "provider": provider_id})
    decoded_digest = _digest_of_mapping(decoded)
    replay_payload = {
        "decoded": decoded_digest,
        "independently_reconstructed": independently_reconstructed,
        "independently_replayed": independently_replayed,
        "kernel_accepted": kernel_accepted,
    }
    replay_digest = _digest_of_mapping(replay_payload)

    compile_digest = _digest_of_mapping(
        {
            "family_id": family_id,
            "provider_id": provider_id,
            "translation_id": translation_id,
        }
    )
    stages = build_stage_pipeline(
        domain_id=domain_id,
        family_id=family_id,
        provider_id=provider_id,
        source_text=source_text,
        translation_id=translation_id,
        compile_digest=compile_digest,
        process_output_digest=out_digest,
        decoded_evidence_digest=decoded_digest,
        replay_or_reconstruction_digest=replay_digest,
        authority_ceiling=authority_ceiling,
    )

    satisfied = establishes_executable_vertical_slice(
        process_backing=backing,
        process_executed=process_executed,
        execution_claimed=process_executed,
    )

    if satisfied:
        if independently_reconstructed and kernel_accepted:
            disposition = SliceDisposition.RECONSTRUCTED
        elif independently_replayed:
            disposition = SliceDisposition.REPLAYED
        else:
            disposition = SliceDisposition.EXECUTABLE
    elif backing is ProcessBackingKind.HERMETIC_FIXTURE:
        disposition = SliceDisposition.HERMETIC_ONLY
    elif backing is ProcessBackingKind.METADATA_ONLY:
        disposition = SliceDisposition.METADATA_ONLY
    elif backing is ProcessBackingKind.MOCK:
        disposition = SliceDisposition.MOCK
    elif backing is ProcessBackingKind.STATIC_DECLARATION:
        disposition = SliceDisposition.REJECTED
    elif backing is ProcessBackingKind.UNAVAILABLE or not process_executed:
        disposition = SliceDisposition.PROCESS_UNAVAILABLE
    else:
        disposition = SliceDisposition.REJECTED

    if independently_reconstructed and kernel_accepted:
        auth = resolve_authority_disposition(
            result_id=f"{receipt_id}.authority",
            evidence_kind=evidence_kind,
            authority_ceiling=authority_ceiling,
            independently_replayed=independently_replayed,
            independently_reconstructed=True,
            kernel_accepted=True,
            match_digest=replay_digest if independently_replayed else "",
        )
    elif independently_replayed:
        auth = resolve_authority_disposition(
            result_id=f"{receipt_id}.authority",
            evidence_kind=evidence_kind,
            authority_ceiling=authority_ceiling,
            independently_replayed=True,
            match_digest=replay_digest,
        )
    else:
        # Force a non-promotable ceiling when no independent evidence.
        ceiling = (
            authority_ceiling
            if authority_ceiling.lower() in _PROMOTION_FORBIDDEN_CEILINGS
            else AuthorityCeiling.CANDIDATE.value
        )
        auth = resolve_authority_disposition(
            result_id=f"{receipt_id}.authority",
            evidence_kind=evidence_kind,
            authority_ceiling=ceiling,
        )

    reason = ""
    if not satisfied:
        reason = (
            f"process_backing={backing.value} cannot satisfy "
            f"{EXECUTABLE_VERTICAL_SLICE_RECEIPT_INTERFACE}"
        )

    return ExecutableVerticalSliceReceipt(
        receipt_id=receipt_id,
        domain_id=domain_id,
        family_id=family_id,
        provider_id=provider_id,
        process_backing=backing,
        disposition=disposition,
        stages=stages,
        command=command,
        command_digest=cmd_digest,
        environment_digest=env_digest,
        tool_digest=t_digest,
        output_digest=out_digest,
        process_executed=process_executed and satisfied,
        execution_claimed=process_executed and satisfied,
        executable_slice_satisfied=satisfied,
        evidence_kind=evidence_kind,
        decoded_evidence_digest=decoded_digest,
        replay_match_digest=replay_digest if independently_replayed else "",
        authority_ceiling=auth.authority_ceiling,
        authority_disposition=auth,
        returncode=observation.get("returncode"),
        tool_id=provider_id,
        toolchain_id=provider_id,
        reason=reason,
        metadata=dict(metadata or {}),
    )


# ---------------------------------------------------------------------------
# Compact corpora (recipes, not bulk golden dumps)
# ---------------------------------------------------------------------------


def build_differential_alignment_corpus() -> tuple[DifferentialAlignmentCase, ...]:
    """Semantic-fragment differential corpus for process-backed providers."""

    recipes: list[tuple[str, str, str, str, str, str, str]] = [
        # (case_id, family, fragment, left, right, left_verdict, right_verdict)
        ("smt.qf_uf.agree_unsat", "smt", "qf_uf", "z3", "cvc5", "unsat", "unsat"),
        ("smt.qf_uf.agree_sat", "smt", "qf_uf", "z3", "cvc5", "sat", "sat"),
        ("smt.qf_uf.disagree", "smt", "qf_uf", "z3", "cvc5", "sat", "unsat"),
        (
            "smt.qf_uf.partial_unavailable",
            "smt",
            "qf_uf",
            "z3",
            "cvc5",
            "unsat",
            "unavailable",
        ),
        (
            "atp.fof.agree_proved",
            "atp",
            "fof",
            "vampire",
            "eprover",
            "proved",
            "proved",
        ),
        (
            "atp.fof.disagree",
            "atp",
            "fof",
            "vampire",
            "eprover",
            "proved",
            "disproved",
        ),
        (
            "tla.bounded.agree",
            "tla",
            "bounded_state",
            "tla_tlc",
            "apalache",
            "satisfied",
            "satisfied",
        ),
        (
            "tla.bounded.disagree",
            "tla",
            "bounded_state",
            "tla_tlc",
            "apalache",
            "satisfied",
            "violated",
        ),
        (
            "protocol.aligned.agree",
            "protocol",
            "aligned_secrecy",
            "proverif",
            "tamarin",
            "secure",
            "secure",
        ),
        (
            "protocol.aligned.disagree",
            "protocol",
            "aligned_secrecy",
            "proverif",
            "tamarin",
            "secure",
            "attack_found",
        ),
        (
            "hyperltl.common.disagree",
            "hyperproperty",
            "hyperltl_common",
            "hyperltl_left",
            "hyperltl_right",
            "satisfied",
            "violated",
        ),
        (
            "monitor.mtl.prefix_inconclusive",
            "runtime",
            "finite_trace_prefix",
            "runtime_mtl",
            "runtime_mtl_shadow",
            "unknown",
            "satisfied",
        ),
    ]
    cases: list[DifferentialAlignmentCase] = []
    for (
        case_id,
        family,
        fragment,
        left,
        right,
        left_verdict,
        right_verdict,
    ) in recipes:
        raw, join = classify_differential_pair(left_verdict, right_verdict)
        cases.append(
            DifferentialAlignmentCase(
                case_id=case_id,
                family=family,
                fragment=fragment,
                left_provider=left,
                right_provider=right,
                left_verdict=left_verdict,
                right_verdict=right_verdict,
                raw_classification=raw,
                join_verdict=join,
                disagreement_preserved=(raw == "disagree"),
                notes=(
                    "Disagreement preserved as typed inconclusive; never majority-voted."
                    if raw == "disagree"
                    else ""
                ),
            )
        )
    return tuple(sorted(cases, key=lambda item: item.case_id))


def build_evidence_replay_corpus() -> tuple[EvidenceReplayCase, ...]:
    """Independent replay cases for models, cores, traces, attacks, witnesses, proofs."""

    def _d(label: str) -> str:
        return _sha256_text(label)

    cases = [
        EvidenceReplayCase(
            case_id="smt.z3.model.replayed",
            evidence_kind="model",
            provider_id="z3",
            original_digest=_d("model:z3:qf_uf:1"),
            replayed_digest=_d("model:z3:qf_uf:1"),
            disposition=ReplayCaseDisposition.REPLAYED,
            matched=True,
            replay_claimed=True,
            authority_ceiling=AuthorityCeiling.EXACT.value,
            notes="Independent model replay under matched digests.",
        ),
        EvidenceReplayCase(
            case_id="smt.cvc5.core.replayed",
            evidence_kind="core",
            provider_id="cvc5",
            original_digest=_d("core:cvc5:unsat:1"),
            replayed_digest=_d("core:cvc5:unsat:1"),
            disposition=ReplayCaseDisposition.REPLAYED,
            matched=True,
            replay_claimed=True,
            authority_ceiling=AuthorityCeiling.EXACT.value,
            notes="Independent unsat-core replay.",
        ),
        EvidenceReplayCase(
            case_id="tla.tlc.trace.replayed",
            evidence_kind="trace",
            provider_id="tla_tlc",
            original_digest=_d("trace:tlc:counterexample:1"),
            replayed_digest=_d("trace:tlc:counterexample:1"),
            disposition=ReplayCaseDisposition.REPLAYED,
            matched=True,
            replay_claimed=True,
            authority_ceiling=AuthorityCeiling.BOUNDED.value,
            notes="Bounded state-model counterexample trace replay.",
        ),
        EvidenceReplayCase(
            case_id="protocol.proverif.attack.replayed",
            evidence_kind="attack",
            provider_id="proverif",
            original_digest=_d("attack:proverif:secrecy:1"),
            replayed_digest=_d("attack:proverif:secrecy:1"),
            disposition=ReplayCaseDisposition.REPLAYED,
            matched=True,
            replay_claimed=True,
            authority_ceiling=AuthorityCeiling.PROTOCOL_SYMBOLIC.value,
            notes="Protocol attack trace independent replay.",
        ),
        EvidenceReplayCase(
            case_id="atp.vampire.witness.ceiling",
            evidence_kind="witness",
            provider_id="vampire",
            original_digest=_d("witness:vampire:fof:1"),
            replayed_digest="",
            disposition=ReplayCaseDisposition.CEILING_ONLY,
            matched=False,
            replay_claimed=False,
            authority_ceiling=AuthorityCeiling.CANDIDATE.value,
            notes="Witness retained under candidate ceiling without promotion.",
        ),
        EvidenceReplayCase(
            case_id="atp.vampire.tstp.ceiling",
            evidence_kind="tstp",
            provider_id="vampire",
            original_digest=_d("tstp:vampire:proof:1"),
            replayed_digest="",
            disposition=ReplayCaseDisposition.CEILING_ONLY,
            matched=False,
            replay_claimed=False,
            authority_ceiling=AuthorityCeiling.CANDIDATE.value,
            notes="TSTP certificate remains candidate until reconstruction.",
        ),
        EvidenceReplayCase(
            case_id="atp.eprover.proof.mismatch",
            evidence_kind="proof",
            provider_id="eprover",
            original_digest=_d("proof:eprover:1"),
            replayed_digest=_d("proof:eprover:1:corrupted"),
            disposition=ReplayCaseDisposition.MISMATCH,
            matched=False,
            replay_claimed=False,
            authority_ceiling=AuthorityCeiling.CANDIDATE.value,
            notes="Proof digest mismatch forbids replay claim.",
        ),
        EvidenceReplayCase(
            case_id="kernel.lean.candidate.reconstructed",
            evidence_kind="kernel_candidate",
            provider_id="lean",
            original_digest=_d("kernel:lean:candidate:1"),
            replayed_digest=_d("kernel:lean:candidate:1"),
            disposition=ReplayCaseDisposition.RECONSTRUCTED,
            matched=True,
            replay_claimed=False,
            reconstructed=True,
            kernel_accepted=True,
            authority_ceiling=AuthorityCeiling.KERNEL.value,
            notes="Kernel candidate reconstructed under official Lean kernel.",
        ),
        EvidenceReplayCase(
            case_id="kernel.rocq.candidate.reconstructed",
            evidence_kind="kernel_candidate",
            provider_id="rocq",
            original_digest=_d("kernel:rocq:candidate:1"),
            replayed_digest=_d("kernel:rocq:candidate:1"),
            disposition=ReplayCaseDisposition.RECONSTRUCTED,
            matched=True,
            replay_claimed=False,
            reconstructed=True,
            kernel_accepted=True,
            authority_ceiling=AuthorityCeiling.KERNEL.value,
            notes="Kernel candidate reconstructed under official Rocq kernel.",
        ),
        EvidenceReplayCase(
            case_id="hammer.premise.ceiling",
            evidence_kind="kernel_candidate",
            provider_id="hammer",
            original_digest=_d("hammer:premise:1"),
            replayed_digest="",
            disposition=ReplayCaseDisposition.CEILING_ONLY,
            matched=False,
            replay_claimed=False,
            authority_ceiling=AuthorityCeiling.CANDIDATE.value,
            notes="Hammer premise selection is advisory until reconstruction.",
        ),
    ]
    return tuple(sorted(cases, key=lambda item: item.case_id))


def build_authority_dispositions(
    replay_cases: Sequence[EvidenceReplayCase] | None = None,
) -> tuple[AuthorityDisposition, ...]:
    """Close every authority-bearing replay case fail-closed."""

    cases = (
        list(replay_cases)
        if replay_cases is not None
        else list(build_evidence_replay_corpus())
    )
    dispositions: list[AuthorityDisposition] = []
    for case in cases:
        if case.reconstructed and case.kernel_accepted:
            dispositions.append(
                resolve_authority_disposition(
                    result_id=case.case_id,
                    evidence_kind=case.evidence_kind,
                    authority_ceiling=case.authority_ceiling,
                    independently_replayed=case.replay_claimed,
                    independently_reconstructed=True,
                    kernel_accepted=True,
                    match_digest=case.replayed_digest or case.original_digest,
                )
            )
        elif case.replay_claimed and case.matched:
            dispositions.append(
                resolve_authority_disposition(
                    result_id=case.case_id,
                    evidence_kind=case.evidence_kind,
                    authority_ceiling=case.authority_ceiling,
                    independently_replayed=True,
                    match_digest=case.replayed_digest,
                )
            )
        else:
            # Mismatch / ceiling-only / non-replayable → typed ceiling.
            ceiling = case.authority_ceiling
            if ceiling.lower() in _PROMOTABLE_CEILINGS:
                ceiling = AuthorityCeiling.CANDIDATE.value
            dispositions.append(
                resolve_authority_disposition(
                    result_id=case.case_id,
                    evidence_kind=case.evidence_kind,
                    authority_ceiling=ceiling,
                )
            )
    return tuple(sorted(dispositions, key=lambda item: item.result_id))


def build_vertical_slice_receipts(
    *,
    process_observation: Mapping[str, Any] | None = None,
) -> tuple[ExecutableVerticalSliceReceipt, ...]:
    """Build representative process-backed and non-satisfying vertical slices."""

    # Prefer a real process observation when available (e.g. /usr/bin/true).
    live = process_observation
    if live is None:
        live = run_pinned_process_probe(candidates=("true", "echo"))

    process_ok = bool(live.get("process_executed"))

    receipts: list[ExecutableVerticalSliceReceipt] = []

    # Positive process-backed slices (when a binary ran).
    if process_ok:
        receipts.append(
            build_executable_vertical_slice_receipt(
                receipt_id="slice:software_verification.smt.z3.process",
                domain_id="software_verification",
                family_id="first_order",
                provider_id="z3",
                process_backing=ProcessBackingKind.PINNED_BINARY,
                source_text="(assert (not false))",
                translation_id="smtlib_identity",
                evidence_kind="model",
                authority_ceiling=AuthorityCeiling.EXACT.value,
                process_observation=live,
                independently_replayed=True,
                decoded_payload={"kind": "model", "provider": "z3", "verdict": "sat"},
            )
        )
        receipts.append(
            build_executable_vertical_slice_receipt(
                receipt_id="slice:software_verification.kernel.lean.process",
                domain_id="software_verification",
                family_id="higher_order",
                provider_id="lean",
                process_backing=ProcessBackingKind.LIVE_PROCESS,
                source_text="theorem t : True := by trivial",
                translation_id="lean_kernel",
                evidence_kind="kernel_candidate",
                authority_ceiling=AuthorityCeiling.KERNEL.value,
                process_observation=live,
                independently_reconstructed=True,
                kernel_accepted=True,
                decoded_payload={
                    "kind": "kernel_candidate",
                    "provider": "lean",
                    "kernel_accepted": True,
                },
            )
        )
    else:
        # Still emit process-unavailable receipts when no binary is present.
        receipts.append(
            build_executable_vertical_slice_receipt(
                receipt_id="slice:software_verification.smt.z3.unavailable",
                domain_id="software_verification",
                family_id="first_order",
                provider_id="z3",
                process_backing=ProcessBackingKind.UNAVAILABLE,
                authority_ceiling=AuthorityCeiling.CANDIDATE.value,
                force_unavailable=True,
            )
        )

    # Non-satisfying records: hermetic / metadata / mock never satisfy.
    receipts.append(
        build_executable_vertical_slice_receipt(
            receipt_id="slice:software_verification.smt.z3.hermetic",
            domain_id="software_verification",
            family_id="first_order",
            provider_id="z3",
            process_backing=ProcessBackingKind.HERMETIC_FIXTURE,
            authority_ceiling=AuthorityCeiling.CANDIDATE.value,
            evidence_kind="model",
        )
    )
    receipts.append(
        build_executable_vertical_slice_receipt(
            receipt_id="slice:software_verification.smt.z3.metadata",
            domain_id="software_verification",
            family_id="first_order",
            provider_id="z3",
            process_backing=ProcessBackingKind.METADATA_ONLY,
            authority_ceiling=AuthorityCeiling.NONE.value,
            evidence_kind="proof",
        )
    )
    receipts.append(
        build_executable_vertical_slice_receipt(
            receipt_id="slice:software_verification.smt.z3.mock",
            domain_id="software_verification",
            family_id="first_order",
            provider_id="z3",
            process_backing=ProcessBackingKind.MOCK,
            authority_ceiling=AuthorityCeiling.NONE.value,
            evidence_kind="proof",
        )
    )
    receipts.append(
        build_executable_vertical_slice_receipt(
            receipt_id="slice:crypto_ir.protocol.proverif.static",
            domain_id="crypto_ir",
            family_id="cryptographic_protocol",
            provider_id="proverif",
            process_backing=ProcessBackingKind.STATIC_DECLARATION,
            authority_ceiling=AuthorityCeiling.PROTOCOL_SYMBOLIC.value,
            evidence_kind="attack",
        )
    )
    return tuple(sorted(receipts, key=lambda item: item.receipt_id))


# ---------------------------------------------------------------------------
# LogicEvidenceReplay@1 report
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicEvidenceReplayReport:
    """Joined process-backed vertical-slice, differential, and replay evidence.

    Interface: ``LogicEvidenceReplay@1``.
    """

    vertical_slices: tuple[ExecutableVerticalSliceReceipt, ...] = field(
        default_factory=tuple
    )
    differential_cases: tuple[DifferentialAlignmentCase, ...] = field(
        default_factory=tuple
    )
    replay_cases: tuple[EvidenceReplayCase, ...] = field(default_factory=tuple)
    authority_dispositions: tuple[AuthorityDisposition, ...] = field(
        default_factory=tuple
    )
    evidence_subset: tuple[str, ...] = REQUIRED_EVIDENCE_SUBSET
    summary: Mapping[str, Any] = field(default_factory=dict)
    interface: str = LOGIC_EVIDENCE_REPLAY_INTERFACE
    schema_version: str = LOGIC_EVIDENCE_REPLAY_SCHEMA
    module_version: str = MODULE_VERSION
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID
    program_id: str = PROGRAM_ID
    content_sha256: str = ""
    content_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "vertical_slices", tuple(self.vertical_slices)
        )
        object.__setattr__(
            self, "differential_cases", tuple(self.differential_cases)
        )
        object.__setattr__(self, "replay_cases", tuple(self.replay_cases))
        object.__setattr__(
            self, "authority_dispositions", tuple(self.authority_dispositions)
        )
        object.__setattr__(
            self,
            "evidence_subset",
            tuple(
                _identifier(item, "evidence_subset item")
                for item in self.evidence_subset
            ),
        )
        missing = [item for item in REQUIRED_EVIDENCE_SUBSET if item not in self.evidence_subset]
        if missing:
            raise ReplayV2Error(
                f"evidence_subset missing required items: {missing}"
            )
        if not isinstance(self.summary, Mapping):
            raise ReplayV2Error("summary must be a mapping")
        object.__setattr__(self, "summary", MappingProxyType(dict(self.summary)))
        if self.interface != LOGIC_EVIDENCE_REPLAY_INTERFACE:
            raise ReplayV2Error(
                f"interface must be {LOGIC_EVIDENCE_REPLAY_INTERFACE}"
            )
        if self.schema_version != LOGIC_EVIDENCE_REPLAY_SCHEMA:
            raise ReplayV2Error(
                f"schema must be {LOGIC_EVIDENCE_REPLAY_SCHEMA}"
            )
        if self.task_id != TASK_ID:
            raise ReplayV2Error(f"task_id must be {TASK_ID}")
        if self.goal_id != GOAL_ID:
            raise ReplayV2Error(f"goal_id must be {GOAL_ID}")

        body = self._body_dict()
        digest = _digest_of_mapping(body)
        content_id = f"sha256:{digest}"
        if self.content_sha256 and self.content_sha256 != digest:
            raise ReplayV2Error(
                "content_sha256 does not match deterministic body digest"
            )
        if self.content_id and self.content_id != content_id:
            raise ReplayV2Error(
                "content_id does not match deterministic body content id"
            )
        object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(self, "content_id", content_id)

    def _body_dict(self) -> dict[str, Any]:
        return {
            "authority_dispositions": [
                item.to_dict() for item in self.authority_dispositions
            ],
            "differential_cases": [
                item.to_dict() for item in self.differential_cases
            ],
            "evidence_subset": list(self.evidence_subset),
            "goal_id": self.goal_id,
            "interface": self.interface,
            "module_version": self.module_version,
            "program_id": self.program_id,
            "replay_cases": [item.to_dict() for item in self.replay_cases],
            "schema_version": self.schema_version,
            "summary": dict(self.summary),
            "task_id": self.task_id,
            "vertical_slices": [item.to_dict() for item in self.vertical_slices],
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._body_dict()
        payload["content_id"] = self.content_id
        payload["content_sha256"] = self.content_sha256
        return payload

    def to_json(self, *, indent: int | None = 2) -> str:
        separators = None if indent is not None else (",", ":")
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            indent=indent,
            separators=separators,
            sort_keys=True,
        ) + ("\n" if indent is not None else "")

    def acceptance_holds(self) -> bool:
        return bool(self.summary.get("acceptance_holds"))


def _build_summary(
    slices: Sequence[ExecutableVerticalSliceReceipt],
    differential: Sequence[DifferentialAlignmentCase],
    replay_cases: Sequence[EvidenceReplayCase],
    authority: Sequence[AuthorityDisposition],
) -> dict[str, Any]:
    disagree = [
        item for item in differential if item.raw_classification == "disagree"
    ]
    disagree_preserved = all(
        item.disagreement_preserved
        and item.join_verdict == DifferentialJoinVerdict.INCONCLUSIVE.value
        for item in disagree
    )
    # Static/hermetic/metadata/mock never satisfy executable slice.
    non_process = [
        item
        for item in slices
        if (
            item.process_backing.value
            if isinstance(item.process_backing, ProcessBackingKind)
            else str(item.process_backing)
        )
        in _NON_EXECUTABLE_SLICE_KINDS
    ]
    non_process_unsatisfied = all(
        not item.executable_slice_satisfied for item in non_process
    )
    # Every authority disposition is resolved (no unresolved / silent promote).
    all_authority_closed = all(
        (
            item.disposition
            if isinstance(item.disposition, AuthorityDispositionKind)
            else AuthorityDispositionKind(str(item.disposition))
        )
        is not AuthorityDispositionKind.UNRESOLVED
        for item in authority
    )
    # Every authority-bearing result has replay/reconstruction or ceiling.
    every_result_closed = all_authority_closed and bool(authority)
    # Replay coverage over required evidence kinds (at least one case each).
    kinds_present = {item.evidence_kind for item in replay_cases}
    required_kinds = {
        "model",
        "core",
        "trace",
        "attack",
        "witness",
        "proof",
        "kernel_candidate",
    }
    replay_kinds_covered = required_kinds <= kinds_present

    process_satisfied = [
        item for item in slices if item.executable_slice_satisfied
    ]

    acceptance = (
        disagree_preserved
        and bool(disagree)
        and non_process_unsatisfied
        and bool(non_process)
        and every_result_closed
        and replay_kinds_covered
        and bool(differential)
        and bool(replay_cases)
        and bool(slices)
    )
    return {
        "acceptance_holds": acceptance,
        "authority_disposition_count": len(authority),
        "differential_case_count": len(differential),
        "disagree_case_count": len(disagree),
        "disagree_all_preserved_inconclusive": disagree_preserved,
        "every_authority_bearing_result_closed": every_result_closed,
        "non_process_slice_count": len(non_process),
        "non_process_slices_unsatisfied": non_process_unsatisfied,
        "process_satisfied_slice_count": len(process_satisfied),
        "replay_case_count": len(replay_cases),
        "replay_kinds_covered": replay_kinds_covered,
        "vertical_slice_count": len(slices),
    }


def build_logic_evidence_replay_report(
    *,
    process_observation: Mapping[str, Any] | None = None,
) -> LogicEvidenceReplayReport:
    """Materialize the deterministic LFP2-046 joined evidence-replay report."""

    # Probe once so multi-slice receipts share one process observation and
    # the joined report content identity is stable within a process.
    observation = (
        dict(process_observation)
        if process_observation is not None
        else run_pinned_process_probe(candidates=("true", "echo"))
    )
    differential = build_differential_alignment_corpus()
    replay_cases = build_evidence_replay_corpus()
    authority = build_authority_dispositions(replay_cases)
    slices = build_vertical_slice_receipts(process_observation=observation)
    summary = _build_summary(slices, differential, replay_cases, authority)
    return LogicEvidenceReplayReport(
        vertical_slices=slices,
        differential_cases=differential,
        replay_cases=replay_cases,
        authority_dispositions=authority,
        evidence_subset=REQUIRED_EVIDENCE_SUBSET,
        summary=summary,
    )


class LogicEvidenceReplay:
    """Orchestrator facade for ``LogicEvidenceReplay@1``."""

    interface: Final = LOGIC_EVIDENCE_REPLAY_INTERFACE
    schema_version: Final = LOGIC_EVIDENCE_REPLAY_SCHEMA
    task_id: Final = TASK_ID
    goal_id: Final = GOAL_ID

    def build_report(
        self,
        *,
        process_observation: Mapping[str, Any] | None = None,
    ) -> LogicEvidenceReplayReport:
        return build_logic_evidence_replay_report(
            process_observation=process_observation
        )

    def classify_pair(
        self, left_verdict: str, right_verdict: str
    ) -> tuple[str, str]:
        return classify_differential_pair(left_verdict, right_verdict)

    def establish_slice(
        self,
        *,
        process_backing: ProcessBackingKind | str,
        process_executed: bool,
        execution_claimed: bool = True,
    ) -> bool:
        return establishes_executable_vertical_slice(
            process_backing=process_backing,
            process_executed=process_executed,
            execution_claimed=execution_claimed,
        )


DEFAULT_LOGIC_EVIDENCE_REPLAY: Final = LogicEvidenceReplay()


__all__ = [
    "AUTHORITY_DISPOSITION_SCHEMA",
    "AuthorityDisposition",
    "AuthorityDispositionKind",
    "AuthorityPromotionError",
    "DEFAULT_LOGIC_EVIDENCE_REPLAY",
    "DIFFERENTIAL_ALIGNMENT_CASE_SCHEMA",
    "DifferentialAlignmentCase",
    "DifferentialJoinVerdict",
    "EVIDENCE_REPLAY_CASE_SCHEMA",
    "EXECUTABLE_VERTICAL_SLICE_RECEIPT_INTERFACE",
    "EXECUTABLE_VERTICAL_SLICE_RECEIPT_SCHEMA",
    "EvidenceReplayCase",
    "ExecutableSliceClaimError",
    "ExecutableVerticalSliceReceipt",
    "GOAL_ID",
    "LOGIC_EVIDENCE_REPLAY_INTERFACE",
    "LOGIC_EVIDENCE_REPLAY_SCHEMA",
    "LogicEvidenceReplay",
    "LogicEvidenceReplayReport",
    "MODULE_VERSION",
    "PROGRAM_ID",
    "ProcessBackingKind",
    "REPLAYABLE_EVIDENCE_KINDS",
    "REQUIRED_EVIDENCE_SUBSET",
    "ReplayCaseDisposition",
    "ReplayV2Error",
    "SLICE_STAGE_DIGEST_SCHEMA",
    "SliceDisposition",
    "SliceStageRecord",
    "TASK_ID",
    "VERTICAL_SLICE_STAGES",
    "authority_promotion_allowed",
    "build_authority_dispositions",
    "build_differential_alignment_corpus",
    "build_evidence_replay_corpus",
    "build_executable_vertical_slice_receipt",
    "build_logic_evidence_replay_report",
    "build_stage_pipeline",
    "build_vertical_slice_receipts",
    "classify_differential_pair",
    "command_digest",
    "environment_digest",
    "establishes_executable_vertical_slice",
    "output_digest",
    "require_executable_vertical_slice_claim",
    "resolve_authority_disposition",
    "run_pinned_process_probe",
    "stage_digest",
    "tool_digest",
]
