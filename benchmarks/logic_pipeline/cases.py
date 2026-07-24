"""Reviewed, immutable fixture contract for the logic-pipeline benchmark.

The corpus is ground truth, not model output.  This module therefore validates
the review attestation and provenance as strictly as it validates the semantic
target and proof obligation.  Loading is side-effect free and fail-closed:
unknown fields, duplicate JSON keys, non-canonical JSONL, reordered cases, or
digest mismatches invalidate the entire corpus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Final, Mapping, Self

from .contracts import DEFAULT_PROTOCOL_SHA256, Split


CASE_SCHEMA: Final = "ipfs-datasets.logic-pipeline-benchmark.case.v1"
REVIEW_SCHEMA: Final = "ipfs-datasets.logic-pipeline-benchmark.review.v1"
CORPUS_MANIFEST_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.corpus-manifest.v1"
)
CORPUS_ID: Final = "hammer-symai-spacy-leanstral-reviewed-v1"
CORPUS_VERSION: Final = 1
DEFAULT_FIXTURE_DIRECTORY: Final = (
    Path(__file__).parents[2]
    / "tests"
    / "fixtures"
    / "logic_pipeline_benchmark"
)
DEFAULT_CORPUS_PATH: Final = DEFAULT_FIXTURE_DIRECTORY / "corpus.jsonl"
DEFAULT_MANIFEST_PATH: Final = DEFAULT_FIXTURE_DIRECTORY / "manifest.json"

_SAFE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class CorpusContractError(ValueError):
    """Raised when a case or manifest violates the frozen corpus contract."""


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class ExpectedClass(str, Enum):
    PROVED = "proved"
    DISPROVED = "disproved"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


def HSSLEV0201B64() -> str:
    """Return the objective evidence bound to the reviewed corpus contract."""

    return "reviewed immutable semantic and proof benchmark corpus"


def canonical_json(value: object) -> str:
    """Return the unique UTF-8 JSON representation used by corpus digests."""

    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _duplicate_rejecting_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CorpusContractError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _decode_json(text: str, context: str) -> object:
    try:
        return json.loads(text, object_pairs_hook=_duplicate_rejecting_object)
    except CorpusContractError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise CorpusContractError(f"{context} is not valid strict JSON: {exc}") from exc


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise CorpusContractError(f"{field_name} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    field_name: str,
) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing or unknown:
        parts = []
        if missing:
            parts.append(f"missing {sorted(missing)!r}")
        if unknown:
            parts.append(f"unknown {sorted(unknown)!r}")
        raise CorpusContractError(f"{field_name} fields invalid: {', '.join(parts)}")


def _nonempty(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CorpusContractError(
            f"{field_name} must be a nonempty string without edge whitespace"
        )
    return value


def _safe_id(value: object, field_name: str) -> str:
    result = _nonempty(value, field_name)
    if not _SAFE_ID.fullmatch(result):
        raise CorpusContractError(
            f"{field_name} must contain only lowercase letters, digits, '.', "
            "'_', or '-' and start with a letter or digit"
        )
    return result


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise CorpusContractError(f"{field_name} must be a lowercase SHA-256")
    return value


def _positive_int(value: object, field_name: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "nonnegative" if allow_zero else "positive"
        raise CorpusContractError(f"{field_name} must be a {qualifier} integer")
    return value


def _enum(enum_type: type[Enum], value: object, field_name: str) -> Enum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CorpusContractError(f"{field_name} has an unsupported value") from exc


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise CorpusContractError(f"{field_name} must be an array")
    result = tuple(
        _nonempty(item, f"{field_name}[]")
        for item in value
    )
    if len(set(result)) != len(result):
        raise CorpusContractError(f"{field_name} must not contain duplicates")
    return result


def _freeze_json(value: object, field_name: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CorpusContractError(f"{field_name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise CorpusContractError(f"{field_name} contains a non-string key")
        return MappingProxyType(
            {
                key: _freeze_json(value[key], f"{field_name}.{key}")
                for key in sorted(value)
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, f"{field_name}[]")
            for item in value
        )
    raise CorpusContractError(f"{field_name} is not canonical JSON data")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _nonempty_frozen_mapping(value: object, field_name: str) -> Mapping[str, object]:
    result = _mapping(value, field_name)
    if not result:
        raise CorpusContractError(f"{field_name} must not be empty")
    frozen = _freeze_json(result, field_name)
    assert isinstance(frozen, Mapping)
    return frozen


@dataclass(frozen=True, slots=True)
class ReviewAttestation:
    """Independent review evidence for a case's semantic ground truth."""

    schema: str
    status: str
    reviewer_ids: tuple[str, ...]
    review_method: str
    semantic_target_approved: bool
    proof_obligation_approved: bool
    model_output_used: bool
    notes: str

    def __post_init__(self) -> None:
        if self.schema != REVIEW_SCHEMA:
            raise CorpusContractError(f"unsupported review schema: {self.schema!r}")
        if self.status != "approved":
            raise CorpusContractError("review status must be approved")
        reviewer_ids = tuple(
            _safe_id(value, "review.reviewer_ids[]")
            for value in self.reviewer_ids
        )
        if len(reviewer_ids) < 2 or len(set(reviewer_ids)) != len(reviewer_ids):
            raise CorpusContractError(
                "review requires at least two distinct reviewer roles"
            )
        object.__setattr__(self, "reviewer_ids", reviewer_ids)
        if _nonempty(self.review_method, "review.review_method") not in {
            "manual_deductive_review",
            "manual_countermodel_review",
            "manual_schema_adjudication",
        }:
            raise CorpusContractError("review.review_method is not allowlisted")
        if self.semantic_target_approved is not True:
            raise CorpusContractError("review must approve the semantic target")
        if not isinstance(self.proof_obligation_approved, bool):
            raise CorpusContractError(
                "review.proof_obligation_approved must be boolean"
            )
        if self.model_output_used is not False:
            raise CorpusContractError(
                "model output may not be used to establish corpus ground truth"
            )
        _nonempty(self.notes, "review.notes")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "status": self.status,
            "reviewer_ids": list(self.reviewer_ids),
            "review_method": self.review_method,
            "semantic_target_approved": self.semantic_target_approved,
            "proof_obligation_approved": self.proof_obligation_approved,
            "model_output_used": self.model_output_used,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "review")
        _exact_keys(data, set(cls.__dataclass_fields__), "review")
        return cls(
            schema=_nonempty(data["schema"], "review.schema"),
            status=_nonempty(data["status"], "review.status"),
            reviewer_ids=_string_tuple(data["reviewer_ids"], "review.reviewer_ids"),
            review_method=_nonempty(data["review_method"], "review.review_method"),
            semantic_target_approved=data["semantic_target_approved"],  # type: ignore[arg-type]
            proof_obligation_approved=data["proof_obligation_approved"],  # type: ignore[arg-type]
            model_output_used=data["model_output_used"],  # type: ignore[arg-type]
            notes=_nonempty(data["notes"], "review.notes"),
        )


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """One immutable semantic-conversion and formal-proof benchmark unit."""

    schema: str
    case_id: str
    split: Split
    stratum: str
    difficulty: Difficulty
    source_text: str
    source_sha256: str
    expected_class: ExpectedClass
    expected_ir: Mapping[str, object]
    required_predicates: tuple[str, ...]
    required_entities: tuple[str, ...]
    proof_obligation: Mapping[str, object] | None
    negative_controls: tuple[str, ...]
    provenance: Mapping[str, object]
    review: ReviewAttestation

    def __post_init__(self) -> None:
        if self.schema != CASE_SCHEMA:
            raise CorpusContractError(f"unsupported case schema: {self.schema!r}")
        _safe_id(self.case_id, "case_id")
        if not isinstance(self.split, Split):
            raise CorpusContractError("split must be a Split value")
        _safe_id(self.stratum, "stratum")
        if not isinstance(self.difficulty, Difficulty):
            raise CorpusContractError("difficulty must be a Difficulty value")
        _nonempty(self.source_text, "source_text")
        source_digest = hashlib.sha256(self.source_text.encode("utf-8")).hexdigest()
        if _digest(self.source_sha256, "source_sha256") != source_digest:
            raise CorpusContractError("source_sha256 does not match source_text")
        if not isinstance(self.expected_class, ExpectedClass):
            raise CorpusContractError(
                "expected_class must be an ExpectedClass value"
            )
        object.__setattr__(
            self,
            "expected_ir",
            _nonempty_frozen_mapping(self.expected_ir, "expected_ir"),
        )
        predicates = tuple(
            _safe_id(value, "required_predicates[]")
            for value in self.required_predicates
        )
        entities = tuple(
            _safe_id(value, "required_entities[]")
            for value in self.required_entities
        )
        controls = tuple(
            _safe_id(value, "negative_controls[]")
            for value in self.negative_controls
        )
        for field_name, values in (
            ("required_predicates", predicates),
            ("required_entities", entities),
            ("negative_controls", controls),
        ):
            if len(set(values)) != len(values):
                raise CorpusContractError(f"{field_name} contains duplicates")
        object.__setattr__(self, "required_predicates", predicates)
        object.__setattr__(self, "required_entities", entities)
        object.__setattr__(self, "negative_controls", controls)

        proof = self.proof_obligation
        proof_required = self.expected_class in {
            ExpectedClass.PROVED,
            ExpectedClass.DISPROVED,
        }
        if proof_required and proof is None:
            raise CorpusContractError(
                "proved and disproved cases require a proof_obligation"
            )
        if proof is not None:
            object.__setattr__(
                self,
                "proof_obligation",
                _nonempty_frozen_mapping(proof, "proof_obligation"),
            )
        if self.review.proof_obligation_approved is not (proof is not None):
            raise CorpusContractError(
                "review proof approval must match proof_obligation applicability"
            )

        provenance = _nonempty_frozen_mapping(self.provenance, "provenance")
        required_provenance = {
            "source_kind",
            "source_ref",
            "license",
            "ground_truth_method",
            "model_generated_ground_truth",
            "prompt_exposure",
        }
        missing = required_provenance - set(provenance)
        if missing:
            raise CorpusContractError(
                f"provenance missing required fields: {sorted(missing)!r}"
            )
        for name in required_provenance - {"model_generated_ground_truth"}:
            _nonempty(provenance[name], f"provenance.{name}")
        if provenance["model_generated_ground_truth"] is not False:
            raise CorpusContractError(
                "provenance may not identify model-generated ground truth"
            )
        object.__setattr__(self, "provenance", provenance)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "case_id": self.case_id,
            "split": self.split.value,
            "stratum": self.stratum,
            "difficulty": self.difficulty.value,
            "source_text": self.source_text,
            "source_sha256": self.source_sha256,
            "expected_class": self.expected_class.value,
            "expected_ir": _thaw_json(self.expected_ir),
            "required_predicates": list(self.required_predicates),
            "required_entities": list(self.required_entities),
            "proof_obligation": (
                None
                if self.proof_obligation is None
                else _thaw_json(self.proof_obligation)
            ),
            "negative_controls": list(self.negative_controls),
            "provenance": _thaw_json(self.provenance),
            "review": self.review.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "case")
        _exact_keys(data, set(cls.__dataclass_fields__), "case")
        proof = data["proof_obligation"]
        return cls(
            schema=_nonempty(data["schema"], "schema"),
            case_id=_safe_id(data["case_id"], "case_id"),
            split=_enum(Split, data["split"], "split"),  # type: ignore[arg-type]
            stratum=_safe_id(data["stratum"], "stratum"),
            difficulty=_enum(  # type: ignore[arg-type]
                Difficulty, data["difficulty"], "difficulty"
            ),
            source_text=_nonempty(data["source_text"], "source_text"),
            source_sha256=_digest(data["source_sha256"], "source_sha256"),
            expected_class=_enum(  # type: ignore[arg-type]
                ExpectedClass, data["expected_class"], "expected_class"
            ),
            expected_ir=_mapping(data["expected_ir"], "expected_ir"),
            required_predicates=_string_tuple(
                data["required_predicates"], "required_predicates"
            ),
            required_entities=_string_tuple(
                data["required_entities"], "required_entities"
            ),
            proof_obligation=(
                None
                if proof is None
                else _mapping(proof, "proof_obligation")
            ),
            negative_controls=_string_tuple(
                data["negative_controls"], "negative_controls"
            ),
            provenance=_mapping(data["provenance"], "provenance"),
            review=ReviewAttestation.from_dict(data["review"]),
        )


def case_sha256(case: BenchmarkCase) -> str:
    return hashlib.sha256(canonical_json(case.to_dict()).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ManifestCase:
    ordinal: int
    case_id: str
    split: Split
    stratum: str
    case_sha256: str
    source_sha256: str

    def __post_init__(self) -> None:
        _positive_int(self.ordinal, "ordinal", allow_zero=True)
        _safe_id(self.case_id, "case_id")
        if not isinstance(self.split, Split):
            raise CorpusContractError("manifest entry split must be a Split value")
        _safe_id(self.stratum, "stratum")
        _digest(self.case_sha256, "case_sha256")
        _digest(self.source_sha256, "source_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "case_id": self.case_id,
            "split": self.split.value,
            "stratum": self.stratum,
            "case_sha256": self.case_sha256,
            "source_sha256": self.source_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "manifest.cases[]")
        _exact_keys(data, set(cls.__dataclass_fields__), "manifest.cases[]")
        return cls(
            ordinal=_positive_int(
                data["ordinal"], "ordinal", allow_zero=True
            ),
            case_id=_safe_id(data["case_id"], "case_id"),
            split=_enum(Split, data["split"], "split"),  # type: ignore[arg-type]
            stratum=_safe_id(data["stratum"], "stratum"),
            case_sha256=_digest(data["case_sha256"], "case_sha256"),
            source_sha256=_digest(data["source_sha256"], "source_sha256"),
        )


def _count_mapping(value: object, field_name: str) -> Mapping[str, int]:
    data = _mapping(value, field_name)
    frozen: dict[str, int] = {}
    for key in sorted(data):
        _safe_id(key, f"{field_name} key")
        frozen[key] = _positive_int(data[key], f"{field_name}.{key}")
    if not frozen:
        raise CorpusContractError(f"{field_name} must not be empty")
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    schema: str
    corpus_id: str
    corpus_version: int
    case_schema: str
    protocol_sha256: str
    corpus_file: str
    corpus_sha256: str
    semantic_sha256: str
    case_count: int
    split_counts: Mapping[str, int]
    stratum_counts: Mapping[str, int]
    expected_class_counts: Mapping[str, int]
    cases: tuple[ManifestCase, ...]
    frozen: bool
    ground_truth_policy: str

    def __post_init__(self) -> None:
        if self.schema != CORPUS_MANIFEST_SCHEMA:
            raise CorpusContractError(f"unsupported manifest schema: {self.schema!r}")
        if self.corpus_id != CORPUS_ID:
            raise CorpusContractError(f"unsupported corpus id: {self.corpus_id!r}")
        if self.corpus_version != CORPUS_VERSION:
            raise CorpusContractError("unsupported corpus version")
        if self.case_schema != CASE_SCHEMA:
            raise CorpusContractError("manifest case_schema is unsupported")
        if self.protocol_sha256 != DEFAULT_PROTOCOL_SHA256:
            raise CorpusContractError("manifest protocol digest is not frozen protocol v1")
        if self.corpus_file != "corpus.jsonl":
            raise CorpusContractError("manifest corpus_file must be corpus.jsonl")
        _digest(self.corpus_sha256, "corpus_sha256")
        _digest(self.semantic_sha256, "semantic_sha256")
        _positive_int(self.case_count, "case_count")
        object.__setattr__(
            self, "split_counts", _count_mapping(self.split_counts, "split_counts")
        )
        object.__setattr__(
            self,
            "stratum_counts",
            _count_mapping(self.stratum_counts, "stratum_counts"),
        )
        object.__setattr__(
            self,
            "expected_class_counts",
            _count_mapping(self.expected_class_counts, "expected_class_counts"),
        )
        cases = tuple(self.cases)
        object.__setattr__(self, "cases", cases)
        if len(cases) != self.case_count:
            raise CorpusContractError("case_count does not match manifest cases")
        if tuple(entry.ordinal for entry in cases) != tuple(range(self.case_count)):
            raise CorpusContractError("manifest ordinals must be contiguous and ordered")
        case_ids = tuple(entry.case_id for entry in cases)
        if len(set(case_ids)) != len(case_ids):
            raise CorpusContractError("manifest contains duplicate case ids")
        entry_split_counts = _counts(tuple(entry.split.value for entry in cases))
        if entry_split_counts != dict(self.split_counts):
            raise CorpusContractError(
                "manifest split counts do not match manifest entries"
            )
        if set(entry_split_counts) != {split.value for split in Split}:
            raise CorpusContractError(
                "manifest must contain pilot, development, and holdout entries"
            )
        entry_stratum_counts = _counts(tuple(entry.stratum for entry in cases))
        if entry_stratum_counts != dict(self.stratum_counts):
            raise CorpusContractError(
                "manifest stratum counts do not match manifest entries"
            )
        if set(self.expected_class_counts) != {
            expected.value for expected in ExpectedClass
        } or sum(self.expected_class_counts.values()) != self.case_count:
            raise CorpusContractError(
                "manifest expected-class counts must cover every class and case"
            )
        if self.frozen is not True:
            raise CorpusContractError("corpus manifest must be frozen")
        if self.ground_truth_policy != "manual_review_no_model_output":
            raise CorpusContractError("manifest ground-truth policy is unsupported")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "corpus_id": self.corpus_id,
            "corpus_version": self.corpus_version,
            "case_schema": self.case_schema,
            "protocol_sha256": self.protocol_sha256,
            "corpus_file": self.corpus_file,
            "corpus_sha256": self.corpus_sha256,
            "semantic_sha256": self.semantic_sha256,
            "case_count": self.case_count,
            "split_counts": dict(self.split_counts),
            "stratum_counts": dict(self.stratum_counts),
            "expected_class_counts": dict(self.expected_class_counts),
            "cases": [entry.to_dict() for entry in self.cases],
            "frozen": self.frozen,
            "ground_truth_policy": self.ground_truth_policy,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "manifest")
        _exact_keys(data, set(cls.__dataclass_fields__), "manifest")
        raw_cases = data["cases"]
        if not isinstance(raw_cases, list):
            raise CorpusContractError("manifest.cases must be an array")
        return cls(
            schema=_nonempty(data["schema"], "schema"),
            corpus_id=_safe_id(data["corpus_id"], "corpus_id"),
            corpus_version=_positive_int(data["corpus_version"], "corpus_version"),
            case_schema=_nonempty(data["case_schema"], "case_schema"),
            protocol_sha256=_digest(data["protocol_sha256"], "protocol_sha256"),
            corpus_file=_nonempty(data["corpus_file"], "corpus_file"),
            corpus_sha256=_digest(data["corpus_sha256"], "corpus_sha256"),
            semantic_sha256=_digest(data["semantic_sha256"], "semantic_sha256"),
            case_count=_positive_int(data["case_count"], "case_count"),
            split_counts=_count_mapping(data["split_counts"], "split_counts"),
            stratum_counts=_count_mapping(data["stratum_counts"], "stratum_counts"),
            expected_class_counts=_count_mapping(
                data["expected_class_counts"], "expected_class_counts"
            ),
            cases=tuple(ManifestCase.from_dict(item) for item in raw_cases),
            frozen=data["frozen"],  # type: ignore[arg-type]
            ground_truth_policy=_nonempty(
                data["ground_truth_policy"], "ground_truth_policy"
            ),
        )


def corpus_manifest_sha256(manifest: CorpusManifest) -> str:
    """Return the canonical manifest identity used by run contracts."""

    if not isinstance(manifest, CorpusManifest):
        raise CorpusContractError("manifest must be a CorpusManifest")
    return hashlib.sha256(
        canonical_json(manifest.to_dict()).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ReviewedCorpus:
    """A manifest-verified, deeply immutable ordered case collection."""

    manifest: CorpusManifest
    cases: tuple[BenchmarkCase, ...]
    by_id: Mapping[str, BenchmarkCase] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        cases = tuple(self.cases)
        object.__setattr__(self, "cases", cases)
        if len(cases) != self.manifest.case_count:
            raise CorpusContractError(
                "reviewed corpus case count does not match manifest"
            )
        ids = tuple(case.case_id for case in cases)
        if len(set(ids)) != len(ids):
            raise CorpusContractError("reviewed corpus contains duplicate case ids")
        for ordinal, (case, entry) in enumerate(zip(cases, self.manifest.cases)):
            if (
                entry.ordinal != ordinal
                or entry.case_id != case.case_id
                or entry.split is not case.split
                or entry.stratum != case.stratum
                or entry.case_sha256 != case_sha256(case)
                or entry.source_sha256 != case.source_sha256
            ):
                raise CorpusContractError(
                    "reviewed corpus order or content does not match manifest "
                    f"at ordinal {ordinal}"
                )
        split_counts = _counts(tuple(case.split.value for case in cases))
        if split_counts != dict(self.manifest.split_counts):
            raise CorpusContractError("reviewed corpus split counts do not match")
        stratum_counts = _counts(tuple(case.stratum for case in cases))
        if stratum_counts != dict(self.manifest.stratum_counts):
            raise CorpusContractError("reviewed corpus stratum counts do not match")
        class_counts = _counts(
            tuple(case.expected_class.value for case in cases)
        )
        if class_counts != dict(self.manifest.expected_class_counts):
            raise CorpusContractError(
                "reviewed corpus expected-class counts do not match"
            )
        if len(stratum_counts) < 8:
            raise CorpusContractError(
                "reviewed corpus is not representative across strata"
            )
        if _semantic_sha256(cases) != self.manifest.semantic_sha256:
            raise CorpusContractError(
                "reviewed corpus semantic target digest does not match"
            )
        object.__setattr__(
            self,
            "by_id",
            MappingProxyType({case.case_id: case for case in cases}),
        )

    @property
    def manifest_sha256(self) -> str:
        """Return the digest a benchmark run records as its corpus identity."""

        return corpus_manifest_sha256(self.manifest)


def _semantic_sha256(cases: tuple[BenchmarkCase, ...]) -> str:
    payload = [
        {
            "case_id": case.case_id,
            "expected_class": case.expected_class.value,
            "expected_ir": _thaw_json(case.expected_ir),
            "proof_obligation": (
                None
                if case.proof_obligation is None
                else _thaw_json(case.proof_obligation)
            ),
            "review": case.review.to_dict(),
        }
        for case in cases
    ]
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _read_bytes(path: str | Path, field_name: str) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise CorpusContractError(f"cannot read {field_name}: {exc}") from exc


def load_corpus(path: str | Path = DEFAULT_CORPUS_PATH) -> tuple[BenchmarkCase, ...]:
    """Parse canonical JSONL cases without consulting a manifest."""

    raw = _read_bytes(path, "corpus")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorpusContractError("corpus must be UTF-8") from exc
    if not text or not text.endswith("\n"):
        raise CorpusContractError("corpus must be nonempty and newline-terminated")
    lines = text.splitlines()
    if any(not line for line in lines):
        raise CorpusContractError("corpus must not contain blank lines")
    cases: list[BenchmarkCase] = []
    for ordinal, line in enumerate(lines):
        value = _decode_json(line, f"corpus line {ordinal + 1}")
        case = BenchmarkCase.from_dict(value)
        if canonical_json(case.to_dict()) != line:
            raise CorpusContractError(
                f"corpus line {ordinal + 1} is not canonical JSON"
            )
        cases.append(case)
    ids = [case.case_id for case in cases]
    if len(set(ids)) != len(ids):
        raise CorpusContractError("corpus contains duplicate case ids")
    return tuple(cases)


def load_manifest(path: str | Path = DEFAULT_MANIFEST_PATH) -> CorpusManifest:
    raw = _read_bytes(path, "manifest")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorpusContractError("manifest must be UTF-8") from exc
    if not text.endswith("\n"):
        raise CorpusContractError("manifest must be newline-terminated")
    value = _decode_json(text, "manifest")
    manifest = CorpusManifest.from_dict(value)
    if canonical_json(manifest.to_dict()) + "\n" != text:
        raise CorpusContractError("manifest is not canonical JSON")
    return manifest


def _counts(values: tuple[str, ...]) -> dict[str, int]:
    return {
        value: values.count(value)
        for value in sorted(set(values))
    }


def load_reviewed_corpus(
    corpus_path: str | Path = DEFAULT_CORPUS_PATH,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> ReviewedCorpus:
    """Load and verify the complete ordered corpus against its frozen manifest."""

    corpus_bytes = _read_bytes(corpus_path, "corpus")
    manifest = load_manifest(manifest_path)
    actual_corpus_sha256 = hashlib.sha256(corpus_bytes).hexdigest()
    if actual_corpus_sha256 != manifest.corpus_sha256:
        raise CorpusContractError("corpus byte digest does not match manifest")
    cases = load_corpus(corpus_path)
    if len(cases) != manifest.case_count:
        raise CorpusContractError("loaded case count does not match manifest")

    return ReviewedCorpus(manifest=manifest, cases=cases)


__all__ = [
    "CASE_SCHEMA",
    "CORPUS_ID",
    "CORPUS_MANIFEST_SCHEMA",
    "CORPUS_VERSION",
    "DEFAULT_CORPUS_PATH",
    "DEFAULT_FIXTURE_DIRECTORY",
    "DEFAULT_MANIFEST_PATH",
    "REVIEW_SCHEMA",
    "BenchmarkCase",
    "CorpusContractError",
    "CorpusManifest",
    "Difficulty",
    "ExpectedClass",
    "HSSLEV0201B64",
    "ManifestCase",
    "ReviewAttestation",
    "ReviewedCorpus",
    "canonical_json",
    "case_sha256",
    "corpus_manifest_sha256",
    "load_corpus",
    "load_manifest",
    "load_reviewed_corpus",
]
