"""Fail-closed adversarial controls for logic-pipeline benchmark claims.

The benchmark may only count an improvement after this dependency-free trust
boundary has classified the candidate.  The bundled controls exercise every
pre-registered negative class and are stored as canonical JSONL with a
digest-bound manifest.  A control remains ineligible even if an upstream
component labels it verified or presents a syntactically valid receipt digest.

Importing this module performs no filesystem I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Final, Iterable, Mapping, Self
import unicodedata

from .contracts import FailureCode


CONTROL_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.adversarial-control.v1"
)
CONTROL_MANIFEST_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.adversarial-manifest.v1"
)
CONTROL_SUITE_ID: Final = "hammer-symai-spacy-leanstral-adversarial-v1"
CONTROL_SUITE_VERSION: Final = 1
DEFAULT_ADVERSARIAL_DIRECTORY: Final = (
    Path(__file__).parents[2]
    / "tests"
    / "fixtures"
    / "logic_pipeline_benchmark"
    / "adversarial"
)
DEFAULT_CONTROLS_PATH: Final = DEFAULT_ADVERSARIAL_DIRECTORY / "controls.jsonl"
DEFAULT_MANIFEST_PATH: Final = DEFAULT_ADVERSARIAL_DIRECTORY / "manifest.json"

# These constants bind the reviewed bytes, not merely the values decoded from
# them.  They are updated only when the adversarial corpus receives a version.
FROZEN_CONTROLS_SHA256: Final = (
    "41cf374ccc4cbf9fd0605ee1156f78d7656b213f3b0cfb9b4bdf3715f599974b"
)
FROZEN_MANIFEST_SHA256: Final = (
    "3bd5ef467195f246f66e2ecd07251e1a942608adaba2babd2ad401d01bc0e235"
)

_SAFE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PROMPT_LIKE = re.compile(
    r"(?:ignore\s+(?:all\s+)?previous|system\s*prompt|"
    r"<\|(?:system|assistant|user)\|>|report\s+verified|"
    r"do\s+not\s+(?:invoke|run|call)\s+(?:the\s+)?kernel)",
    re.IGNORECASE,
)
_SORRY = re.compile(r"\bsorry\b", re.IGNORECASE)
_ADMIT = re.compile(r"\badmit\b", re.IGNORECASE)
_UNSUPPORTED = re.compile(
    r"(?:\bunsafe\b|\bunrestrictedio\b|\bunknown\.[A-Za-z0-9_.]+\b|"
    r"^\s*#eval\b|^\s*axiom\b)",
    re.IGNORECASE | re.MULTILINE,
)
_CONTRADICTORY = re.compile(
    r"(?:\bcontradiction\b|∧\s*¬|and\s+not\s+|"
    r"\b(?:true\s+and\s+false|false\s+and\s+true)\b)",
    re.IGNORECASE,
)
_OBVIOUSLY_INVALID = re.compile(
    r"(?:\bsyntax[_ -]?error\b|:=\s*by\s*\Z|"
    r"\btheorem\s+[A-Za-z0-9_]+\s*:\s*:=)",
    re.IGNORECASE,
)


class AdversarialContractError(ValueError):
    """Raised when controls or claims violate the trust-boundary contract."""


class ControlKind(str, Enum):
    """Complete negative-control taxonomy in stable evaluation order."""

    INVALID = "invalid"
    CONTRADICTORY = "contradictory"
    UNSUPPORTED = "unsupported"
    PROMPT_LIKE = "prompt_like"
    COPIED = "copied"
    SORRY_BEARING = "sorry_bearing"
    ADMIT_BEARING = "admit_bearing"


REQUIRED_CONTROL_KINDS: Final = tuple(ControlKind)


class CandidateDisposition(str, Enum):
    """A candidate's status at the adversarial trust boundary."""

    ELIGIBLE = "eligible"
    NOT_VERIFIED = "not_verified"
    REJECTED = "rejected"
    SAFETY_INCIDENT = "safety_incident"


def HSSLEV0224A96() -> str:
    """Return AST-verifiable evidence for adversarial negative controls."""

    return "adversarial and negative proof controls fail closed"


def canonical_json(value: object) -> str:
    """Return the sole accepted JSON encoding for control records."""

    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise AdversarialContractError(
            "value is not canonical JSON data"
        ) from exc


def _nonempty(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
    ):
        raise AdversarialContractError(
            f"{field} must be a nonempty string without edge whitespace"
        )
    return value


def _safe_id(value: object, field: str) -> str:
    result = _nonempty(value, field)
    if not _SAFE_ID.fullmatch(result) or result in {".", ".."}:
        raise AdversarialContractError(
            f"{field} must be a safe lowercase identifier"
        )
    return result


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise AdversarialContractError(
            f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AdversarialContractError(f"{field} must be a positive integer")
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise AdversarialContractError(f"{field} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, object], expected: set[str], field: str
) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing {sorted(missing)!r}")
        if unknown:
            details.append(f"unknown {sorted(unknown)!r}")
        raise AdversarialContractError(
            f"{field} fields invalid: {', '.join(details)}"
        )


def _duplicate_rejecting_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AdversarialContractError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _decode_json(text: str, context: str) -> object:
    try:
        return json.loads(text, object_pairs_hook=_duplicate_rejecting_object)
    except AdversarialContractError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise AdversarialContractError(
            f"{context} is not valid strict JSON: {exc}"
        ) from exc


def _control_kind(value: object, field: str = "control_kind") -> ControlKind:
    if not isinstance(value, str):
        raise AdversarialContractError(f"{field} must be a string")
    try:
        return ControlKind(value)
    except ValueError as exc:
        raise AdversarialContractError(
            f"unsupported {field}: {value!r}"
        ) from exc


def _normalized_copy_text(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(folded.split())


def _has_unbalanced_delimiters(value: str) -> bool:
    """Conservatively detect malformed bracket structure without a parser."""

    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    for character in value:
        if character in "([{":
            stack.append(character)
        elif character in pairs:
            if not stack or stack.pop() != pairs[character]:
                return True
    return bool(stack)


@dataclass(frozen=True, slots=True)
class AdversarialControl:
    """One reviewed candidate that must never count as an improvement."""

    schema: str
    control_id: str
    control_kind: ControlKind
    source_text: str
    candidate_text: str
    protected_text: str | None
    rationale: str

    def __post_init__(self) -> None:
        if self.schema != CONTROL_SCHEMA:
            raise AdversarialContractError("unsupported control schema")
        _safe_id(self.control_id, "control_id")
        if not isinstance(self.control_kind, ControlKind):
            raise AdversarialContractError(
                "control_kind must be a ControlKind"
            )
        _nonempty(self.source_text, "source_text")
        _nonempty(self.candidate_text, "candidate_text")
        if self.protected_text is not None:
            _nonempty(self.protected_text, "protected_text")
        if (
            self.control_kind is ControlKind.COPIED
            and self.protected_text is None
        ):
            raise AdversarialContractError(
                "copied controls require protected_text"
            )
        if (
            self.control_kind is not ControlKind.COPIED
            and self.protected_text is not None
        ):
            raise AdversarialContractError(
                "only copied controls may carry protected_text"
            )
        _nonempty(self.rationale, "rationale")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "control_id": self.control_id,
            "control_kind": self.control_kind.value,
            "source_text": self.source_text,
            "candidate_text": self.candidate_text,
            "protected_text": self.protected_text,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "control")
        _exact_keys(data, set(cls.__dataclass_fields__), "control")
        protected = data["protected_text"]
        return cls(
            schema=_nonempty(data["schema"], "schema"),
            control_id=_safe_id(data["control_id"], "control_id"),
            control_kind=_control_kind(data["control_kind"]),
            source_text=_nonempty(data["source_text"], "source_text"),
            candidate_text=_nonempty(
                data["candidate_text"], "candidate_text"
            ),
            protected_text=(
                None
                if protected is None
                else _nonempty(protected, "protected_text")
            ),
            rationale=_nonempty(data["rationale"], "rationale"),
        )

    @property
    def sha256(self) -> str:
        return control_sha256(self)


def control_sha256(control: AdversarialControl) -> str:
    if not isinstance(control, AdversarialControl):
        raise AdversarialContractError(
            "control must be an AdversarialControl"
        )
    return hashlib.sha256(
        canonical_json(control.to_dict()).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ControlDigest:
    """Manifest identity for one ordered control record."""

    control_id: str
    control_sha256: str

    def __post_init__(self) -> None:
        _safe_id(self.control_id, "control_id")
        _digest(self.control_sha256, "control_sha256")

    def to_dict(self) -> dict[str, str]:
        return {
            "control_id": self.control_id,
            "control_sha256": self.control_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "control_digest")
        _exact_keys(data, set(cls.__dataclass_fields__), "control_digest")
        return cls(
            control_id=_safe_id(data["control_id"], "control_id"),
            control_sha256=_digest(
                data["control_sha256"], "control_sha256"
            ),
        )


@dataclass(frozen=True, slots=True)
class ControlManifest:
    """Immutable manifest binding coverage, order, and exact JSONL bytes."""

    schema: str
    suite_id: str
    suite_version: int
    evidence: str
    controls_file: str
    controls_sha256: str
    control_count: int
    required_control_kinds: tuple[ControlKind, ...]
    controls: tuple[ControlDigest, ...]

    def __post_init__(self) -> None:
        if self.schema != CONTROL_MANIFEST_SCHEMA:
            raise AdversarialContractError("unsupported manifest schema")
        if self.suite_id != CONTROL_SUITE_ID:
            raise AdversarialContractError("unsupported control suite")
        if self.suite_version != CONTROL_SUITE_VERSION:
            raise AdversarialContractError("unsupported control suite version")
        if self.evidence != HSSLEV0224A96():
            raise AdversarialContractError(
                "manifest does not bind objective evidence"
            )
        if self.controls_file != "controls.jsonl":
            raise AdversarialContractError(
                "controls_file must be controls.jsonl"
            )
        _digest(self.controls_sha256, "controls_sha256")
        _positive_integer(self.control_count, "control_count")
        if (
            not isinstance(self.required_control_kinds, tuple)
            or self.required_control_kinds != REQUIRED_CONTROL_KINDS
        ):
            raise AdversarialContractError(
                "required_control_kinds must list the complete frozen taxonomy"
            )
        if not isinstance(self.controls, tuple) or not all(
            isinstance(item, ControlDigest) for item in self.controls
        ):
            raise AdversarialContractError(
                "controls must be an immutable tuple of ControlDigest records"
            )
        if self.control_count != len(self.controls):
            raise AdversarialContractError(
                "control_count does not match controls"
            )
        ids = tuple(item.control_id for item in self.controls)
        if len(ids) != len(set(ids)):
            raise AdversarialContractError(
                "manifest contains duplicate control ids"
            )
        if ids != tuple(sorted(ids)):
            raise AdversarialContractError(
                "manifest controls must be ordered by control_id"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "suite_id": self.suite_id,
            "suite_version": self.suite_version,
            "evidence": self.evidence,
            "controls_file": self.controls_file,
            "controls_sha256": self.controls_sha256,
            "control_count": self.control_count,
            "required_control_kinds": [
                kind.value for kind in self.required_control_kinds
            ],
            "controls": [item.to_dict() for item in self.controls],
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "manifest")
        _exact_keys(data, set(cls.__dataclass_fields__), "manifest")
        raw_kinds = data["required_control_kinds"]
        raw_controls = data["controls"]
        if not isinstance(raw_kinds, list):
            raise AdversarialContractError(
                "required_control_kinds must be an array"
            )
        if not isinstance(raw_controls, list):
            raise AdversarialContractError("controls must be an array")
        return cls(
            schema=_nonempty(data["schema"], "schema"),
            suite_id=_nonempty(data["suite_id"], "suite_id"),
            suite_version=_positive_integer(
                data["suite_version"], "suite_version"
            ),
            evidence=_nonempty(data["evidence"], "evidence"),
            controls_file=_nonempty(
                data["controls_file"], "controls_file"
            ),
            controls_sha256=_digest(
                data["controls_sha256"], "controls_sha256"
            ),
            control_count=_positive_integer(
                data["control_count"], "control_count"
            ),
            required_control_kinds=tuple(
                _control_kind(item, "required_control_kinds[]")
                for item in raw_kinds
            ),
            controls=tuple(
                ControlDigest.from_dict(item) for item in raw_controls
            ),
        )


@dataclass(frozen=True, slots=True)
class ControlSuite:
    """A completely validated control corpus and its byte identities."""

    manifest: ControlManifest
    controls: tuple[AdversarialControl, ...]
    manifest_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, ControlManifest):
            raise AdversarialContractError(
                "manifest must be a ControlManifest"
            )
        if not isinstance(self.controls, tuple) or not all(
            isinstance(item, AdversarialControl) for item in self.controls
        ):
            raise AdversarialContractError(
                "controls must be an immutable tuple"
            )
        _digest(self.manifest_sha256, "manifest_sha256")
        expected_manifest_sha256 = hashlib.sha256(
            (canonical_json(self.manifest.to_dict()) + "\n").encode("utf-8")
        ).hexdigest()
        if self.manifest_sha256 != expected_manifest_sha256:
            raise AdversarialContractError(
                "manifest_sha256 does not match canonical manifest bytes"
            )
        validate_control_coverage(self.controls)
        expected = tuple(
            ControlDigest(item.control_id, item.sha256)
            for item in self.controls
        )
        if self.manifest.controls != expected:
            raise AdversarialContractError(
                "manifest record identities do not match controls"
            )

    @property
    def by_id(self) -> Mapping[str, AdversarialControl]:
        """Return a fresh read-only id lookup."""

        from types import MappingProxyType

        return MappingProxyType(
            {control.control_id: control for control in self.controls}
        )


def classify_candidate(
    candidate_text: object,
    *,
    protected_texts: Iterable[object] = (),
) -> tuple[ControlKind, ...]:
    """Classify negative evidence deterministically and fail closed.

    This is deliberately a lexical trust boundary, not a theorem prover.  It
    rejects known unsafe constructs before any proof receipt can enter the
    improvement statistics.  Parser or input failures classify as ``invalid``.
    """

    found: set[ControlKind] = set()
    if not isinstance(candidate_text, str) or not candidate_text.strip():
        return (ControlKind.INVALID,)
    if (
        "\x00" in candidate_text
        or _has_unbalanced_delimiters(candidate_text)
        or _OBVIOUSLY_INVALID.search(candidate_text)
    ):
        found.add(ControlKind.INVALID)
    if _CONTRADICTORY.search(candidate_text):
        found.add(ControlKind.CONTRADICTORY)
    if _UNSUPPORTED.search(candidate_text):
        found.add(ControlKind.UNSUPPORTED)
    if _PROMPT_LIKE.search(candidate_text):
        found.add(ControlKind.PROMPT_LIKE)
    if _SORRY.search(candidate_text):
        found.add(ControlKind.SORRY_BEARING)
    if _ADMIT.search(candidate_text):
        found.add(ControlKind.ADMIT_BEARING)

    normalized_candidate = _normalized_copy_text(candidate_text)
    try:
        for protected in protected_texts:
            if not isinstance(protected, str) or not protected.strip():
                found.add(ControlKind.INVALID)
                continue
            normalized_protected = _normalized_copy_text(protected)
            if (
                normalized_candidate == normalized_protected
                or normalized_protected in normalized_candidate
            ):
                found.add(ControlKind.COPIED)
    except (TypeError, ValueError):
        found.add(ControlKind.INVALID)
    return tuple(kind for kind in REQUIRED_CONTROL_KINDS if kind in found)


def validate_control_coverage(
    controls: Iterable[AdversarialControl],
) -> None:
    """Require unique, sorted, executable coverage of the frozen taxonomy."""

    if isinstance(controls, (str, bytes)):
        raise AdversarialContractError(
            "controls must contain AdversarialControl records"
        )
    try:
        records = tuple(controls)
    except TypeError as exc:
        raise AdversarialContractError("controls must be iterable") from exc
    if not records or not all(
        isinstance(item, AdversarialControl) for item in records
    ):
        raise AdversarialContractError(
            "controls must contain AdversarialControl records"
        )
    ids = tuple(item.control_id for item in records)
    if len(ids) != len(set(ids)):
        raise AdversarialContractError("controls contain duplicate ids")
    if ids != tuple(sorted(ids)):
        raise AdversarialContractError(
            "controls must be ordered by control_id"
        )
    covered = {item.control_kind for item in records}
    missing = set(REQUIRED_CONTROL_KINDS) - covered
    if missing:
        raise AdversarialContractError(
            "control coverage missing "
            + ", ".join(sorted(kind.value for kind in missing))
        )
    repeated = tuple(
        kind
        for kind in REQUIRED_CONTROL_KINDS
        if sum(item.control_kind is kind for item in records) != 1
    )
    if repeated:
        raise AdversarialContractError(
            "frozen suite must contain exactly one control for "
            + ", ".join(kind.value for kind in repeated)
        )
    for item in records:
        detected = classify_candidate(
            item.candidate_text,
            protected_texts=(
                () if item.protected_text is None else (item.protected_text,)
            ),
        )
        if item.control_kind not in detected:
            raise AdversarialContractError(
                f"{item.control_id} does not exercise "
                f"{item.control_kind.value}"
            )


@dataclass(frozen=True, slots=True)
class CandidateClaim:
    """Untrusted candidate and its upstream verification claim."""

    candidate_id: str
    candidate_text: str
    claimed_verified: bool
    kernel_accepted: bool
    kernel_receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        _safe_id(self.candidate_id, "candidate_id")
        _nonempty(self.candidate_text, "candidate_text")
        if type(self.claimed_verified) is not bool:
            raise AdversarialContractError(
                "claimed_verified must be a boolean"
            )
        if type(self.kernel_accepted) is not bool:
            raise AdversarialContractError(
                "kernel_accepted must be a boolean"
            )
        if self.kernel_receipt_sha256 is not None:
            _digest(
                self.kernel_receipt_sha256,
                "kernel_receipt_sha256",
            )


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    """Immutable result of applying the negative-control gate."""

    candidate_id: str
    candidate_sha256: str
    classifications: tuple[ControlKind, ...]
    disposition: CandidateDisposition
    eligible_for_verified_improvement: bool
    failure_code: FailureCode | None
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _safe_id(self.candidate_id, "candidate_id")
        _digest(self.candidate_sha256, "candidate_sha256")
        if (
            not isinstance(self.classifications, tuple)
            or any(
                not isinstance(kind, ControlKind)
                for kind in self.classifications
            )
            or self.classifications
            != tuple(
                kind
                for kind in REQUIRED_CONTROL_KINDS
                if kind in self.classifications
            )
        ):
            raise AdversarialContractError(
                "classifications must be unique and in frozen order"
            )
        if not isinstance(self.disposition, CandidateDisposition):
            raise AdversarialContractError(
                "disposition must be a CandidateDisposition"
            )
        if type(self.eligible_for_verified_improvement) is not bool:
            raise AdversarialContractError(
                "eligible_for_verified_improvement must be a boolean"
            )
        if self.failure_code is not None and not isinstance(
            self.failure_code, FailureCode
        ):
            raise AdversarialContractError(
                "failure_code must be a FailureCode"
            )
        if (
            not isinstance(self.reasons, tuple)
            or not self.reasons
            or any(
                not isinstance(reason, str) or not reason
                for reason in self.reasons
            )
        ):
            raise AdversarialContractError(
                "reasons must be a nonempty immutable tuple"
            )
        if self.classifications and self.eligible_for_verified_improvement:
            raise AdversarialContractError(
                "adversarial candidates can never be verified improvements"
            )
        if self.eligible_for_verified_improvement:
            if (
                self.disposition is not CandidateDisposition.ELIGIBLE
                or self.failure_code is not None
            ):
                raise AdversarialContractError(
                    "eligible assessment has inconsistent status"
                )
        elif self.disposition is CandidateDisposition.ELIGIBLE:
            raise AdversarialContractError(
                "eligible disposition requires improvement eligibility"
            )


def gate_candidate(
    claim: CandidateClaim,
    *,
    control: AdversarialControl | None = None,
    protected_texts: Iterable[object] = (),
) -> CandidateAssessment:
    """Apply the fail-closed boundary before candidate statistics.

    A declared control is adversarial by construction.  If it is nevertheless
    presented as kernel-accepted and verified, the gate emits the protocol's
    fatal ``INVALID_CONTROL_VERIFIED`` incident while keeping it ineligible.
    """

    if not isinstance(claim, CandidateClaim):
        raise AdversarialContractError("claim must be a CandidateClaim")
    if control is not None and not isinstance(control, AdversarialControl):
        raise AdversarialContractError(
            "control must be an AdversarialControl"
        )
    references: list[object] = list(protected_texts)
    if control is not None and control.protected_text is not None:
        references.append(control.protected_text)
    try:
        found = set(
            classify_candidate(
                claim.candidate_text,
                protected_texts=references,
            )
        )
    except Exception:
        # A classifier failure is itself invalid evidence; no exception may
        # accidentally skip the safety boundary.
        found = {ControlKind.INVALID}
    if control is not None:
        found.add(control.control_kind)
    classifications = tuple(
        kind for kind in REQUIRED_CONTROL_KINDS if kind in found
    )
    candidate_digest = hashlib.sha256(
        claim.candidate_text.encode("utf-8")
    ).hexdigest()

    valid_kernel_claim = (
        claim.claimed_verified
        and claim.kernel_accepted
        and claim.kernel_receipt_sha256 is not None
    )
    if classifications:
        incident = valid_kernel_claim
        return CandidateAssessment(
            candidate_id=claim.candidate_id,
            candidate_sha256=candidate_digest,
            classifications=classifications,
            disposition=(
                CandidateDisposition.SAFETY_INCIDENT
                if incident
                else CandidateDisposition.REJECTED
            ),
            eligible_for_verified_improvement=False,
            failure_code=(
                FailureCode.INVALID_CONTROL_VERIFIED
                if incident
                else FailureCode.SAFETY_CONTROL_FAILURE
            ),
            reasons=tuple(
                f"candidate classified as {kind.value}"
                for kind in classifications
            ),
        )
    if valid_kernel_claim:
        return CandidateAssessment(
            candidate_id=claim.candidate_id,
            candidate_sha256=candidate_digest,
            classifications=(),
            disposition=CandidateDisposition.ELIGIBLE,
            eligible_for_verified_improvement=True,
            failure_code=None,
            reasons=("native-kernel verification claim is structurally complete",),
        )
    return CandidateAssessment(
        candidate_id=claim.candidate_id,
        candidate_sha256=candidate_digest,
        classifications=(),
        disposition=CandidateDisposition.NOT_VERIFIED,
        eligible_for_verified_improvement=False,
        failure_code=FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
        reasons=("candidate lacks a complete native-kernel verification claim",),
    )


def _read_bytes(path: Path, field: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise AdversarialContractError(
            f"unable to read {field}: {path}"
        ) from exc


def load_control_suite(
    controls_path: str | Path = DEFAULT_CONTROLS_PATH,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> ControlSuite:
    """Load and fully authenticate a control suite from canonical files."""

    controls_file = Path(controls_path)
    manifest_file = Path(manifest_path)
    controls_bytes = _read_bytes(controls_file, "controls")
    manifest_bytes = _read_bytes(manifest_file, "manifest")
    controls_digest = hashlib.sha256(controls_bytes).hexdigest()
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    using_defaults = (
        controls_file.resolve(strict=False)
        == DEFAULT_CONTROLS_PATH.resolve(strict=False)
        and manifest_file.resolve(strict=False)
        == DEFAULT_MANIFEST_PATH.resolve(strict=False)
    )
    if using_defaults and controls_digest != FROZEN_CONTROLS_SHA256:
        raise AdversarialContractError(
            "bundled controls do not match the frozen revision"
        )
    if using_defaults and manifest_digest != FROZEN_MANIFEST_SHA256:
        raise AdversarialContractError(
            "bundled manifest does not match the frozen revision"
        )
    try:
        controls_text = controls_bytes.decode("utf-8")
        manifest_text = manifest_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AdversarialContractError(
            "control files must be valid UTF-8"
        ) from exc
    if not controls_text or not controls_text.endswith("\n"):
        raise AdversarialContractError(
            "controls JSONL must end with exactly one record newline"
        )
    lines = controls_text.splitlines()
    if any(not line for line in lines):
        raise AdversarialContractError(
            "controls JSONL must not contain blank lines"
        )
    controls: list[AdversarialControl] = []
    for index, line in enumerate(lines, start=1):
        decoded = _decode_json(line, f"controls line {index}")
        control = AdversarialControl.from_dict(decoded)
        if line != canonical_json(control.to_dict()):
            raise AdversarialContractError(
                f"controls line {index} is not canonical JSON"
            )
        controls.append(control)
    decoded_manifest = _decode_json(manifest_text, "manifest")
    manifest = ControlManifest.from_dict(decoded_manifest)
    if manifest_text != canonical_json(manifest.to_dict()) + "\n":
        raise AdversarialContractError(
            "manifest is not canonical JSON with one trailing newline"
        )
    if manifest.controls_sha256 != controls_digest:
        raise AdversarialContractError(
            "manifest controls_sha256 does not match controls bytes"
        )
    suite = ControlSuite(
        manifest=manifest,
        controls=tuple(controls),
        manifest_sha256=manifest_digest,
    )
    if suite.manifest.control_count != len(suite.controls):
        raise AdversarialContractError(
            "manifest control_count does not match JSONL"
        )
    return suite


__all__ = [
    "AdversarialContractError",
    "AdversarialControl",
    "CandidateAssessment",
    "CandidateClaim",
    "CandidateDisposition",
    "CONTROL_MANIFEST_SCHEMA",
    "CONTROL_SCHEMA",
    "CONTROL_SUITE_ID",
    "CONTROL_SUITE_VERSION",
    "ControlDigest",
    "ControlKind",
    "ControlManifest",
    "ControlSuite",
    "DEFAULT_ADVERSARIAL_DIRECTORY",
    "DEFAULT_CONTROLS_PATH",
    "DEFAULT_MANIFEST_PATH",
    "FROZEN_CONTROLS_SHA256",
    "FROZEN_MANIFEST_SHA256",
    "HSSLEV0224A96",
    "REQUIRED_CONTROL_KINDS",
    "canonical_json",
    "classify_candidate",
    "control_sha256",
    "gate_candidate",
    "load_control_suite",
    "validate_control_coverage",
]
