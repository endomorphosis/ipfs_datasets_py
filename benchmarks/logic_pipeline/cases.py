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
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Final, Mapping, Self
import unicodedata

from .contracts import (
    DEFAULT_PROTOCOL_SHA256,
    RUN_CONTRACT_SCHEMA,
    RunContract,
    Split,
)
from .content_addressing import cid_for_dag_json, validate_cid


CASE_SCHEMA: Final = "ipfs-datasets.logic-pipeline-benchmark.case.v1"
REVIEW_SCHEMA: Final = "ipfs-datasets.logic-pipeline-benchmark.review.v1"
CORPUS_MANIFEST_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.corpus-manifest.v1"
)
SPLIT_MANIFEST_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.split-manifest.v1"
)
SPLIT_INTEGRITY_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.split-integrity.v1"
)
HOLDOUT_ACCESS_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.holdout-access.v1"
)
REPLACEMENT_HOLDOUT_SEAL_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.replacement-holdout-seal.v2"
)
REPLACEMENT_HOLDOUT_LEDGER_AUTHORITY_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "replacement-holdout-ledger-authority.v1"
)
REPLACEMENT_HOLDOUT_PROTOCOL_KEYS: Final = frozenset(
    {
        "access_policy",
        "causal_proof",
        "holdout_execution",
        "independent_authorship",
        "independent_review",
        "semantic",
    }
)
CORPUS_ID: Final = "hammer-symai-spacy-leanstral-reviewed-v1"
CORPUS_VERSION: Final = 1
SOURCE_NORMALIZATION_VERSION: Final = "unicode-nfkc-casefold-alnum-v1"
NEAR_DUPLICATE_JACCARD_THRESHOLD: Final = 0.8
FROZEN_CORPUS_MANIFEST_SHA256: Final = (
    "58b9122c24e4d9d4cc2ad01c7437dfeb45c80ad2535df769d81a89acbda24a26"
)
# These identities bind the reviewed revision-1 membership, order, exact case
# bytes, source bytes, and normalized source text.  They are filled from the
# canonical split records below and deliberately do not depend on runtime I/O.
FROZEN_SPLIT_SHA256: Final[Mapping[Split, str]] = MappingProxyType(
    {
        Split.PILOT: (
            "a050371dae1248deecfb17f2d9e610124c6e493a1a227ec3c161008891ce1881"
        ),
        Split.DEVELOPMENT: (
            "530860019b164c9750083ec5affd6ae71202b695c8c8042400d0f02488436b74"
        ),
        Split.HOLDOUT: (
            "c7b969ed19a1248143740068e2853ca6132ba3d65dfeec4133e37fad55dbab4a"
        ),
    }
)
FROZEN_SPLIT_INTEGRITY_SHA256: Final = (
    "dd68177636a3db87752de54399ed8f066d5fdefe568649d9551bb29a0fb529d0"
)
DEFAULT_FIXTURE_DIRECTORY: Final = (
    Path(__file__).parents[2]
    / "tests"
    / "fixtures"
    / "logic_pipeline_benchmark"
)
DEFAULT_CORPUS_PATH: Final = DEFAULT_FIXTURE_DIRECTORY / "corpus.jsonl"
DEFAULT_MANIFEST_PATH: Final = DEFAULT_FIXTURE_DIRECTORY / "manifest.json"

_SAFE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_PROTOCOL_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
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


def HSSLEV0232D57() -> str:
    """Return the objective evidence bound to split and holdout integrity."""

    return "frozen split integrity and audited leakage-free holdout access"


def canonical_json(value: object) -> str:
    """Return the unique UTF-8 JSON representation used by corpus digests."""

    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def normalize_source_text(value: str) -> str:
    """Return the frozen comparison form used for leakage detection.

    Compatibility characters are folded with NFKC, casing is removed with
    Unicode ``casefold``, and every run of punctuation or whitespace becomes
    one ASCII space.  Keeping alphanumeric Unicode characters makes this
    deterministic without an optional tokenizer or locale dependency.
    """

    if not isinstance(value, str) or not value.strip():
        raise CorpusContractError("source_text must be a nonempty string")
    text = value.strip()
    normalized = unicodedata.normalize("NFKC", text).casefold()
    result = " ".join(
        "".join(character if character.isalnum() else " " for character in normalized)
        .split()
    )
    if not result:
        raise CorpusContractError(
            "source_text must contain alphanumeric content after normalization"
        )
    return result


def normalized_source_sha256(value: str) -> str:
    """Return the digest of :func:`normalize_source_text`."""

    return hashlib.sha256(normalize_source_text(value).encode("utf-8")).hexdigest()


def _source_shingles(value: str) -> frozenset[tuple[str, ...]]:
    tokens = normalize_source_text(value).split()
    width = min(3, len(tokens))
    return frozenset(
        tuple(tokens[index:index + width])
        for index in range(len(tokens) - width + 1)
    )


def source_similarity(left: str, right: str) -> float:
    """Return deterministic token-shingle Jaccard similarity in ``[0, 1]``."""

    left_shingles = _source_shingles(left)
    right_shingles = _source_shingles(right)
    union = left_shingles | right_shingles
    return len(left_shingles & right_shingles) / len(union)


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


def _protocol_safe_id(value: object, field_name: str) -> str:
    result = _nonempty(value, field_name)
    if not _PROTOCOL_SAFE_ID.fullmatch(result):
        raise CorpusContractError(
            f"{field_name} must be a safe protocol identifier"
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


def _cid(
    value: object,
    field_name: str,
    *,
    codecs: tuple[str, ...],
) -> str:
    try:
        return validate_cid(value, codecs=codecs)
    except (TypeError, ValueError) as exc:
        raise CorpusContractError(
            f"{field_name} must be a canonical CIDv1/base32/sha2-256 "
            f"using one of {codecs!r}"
        ) from exc


def replacement_holdout_ledger_authority_cid(
    sealed_manifest_cid: str,
    ledger_path: str | Path,
) -> str:
    """Commit one sealed manifest to one canonical access-ledger authority.

    The public seal exposes only this CID, not the ledger path.  The path is
    deliberately lexical rather than filesystem-resolved: seal construction
    may precede directory creation, while the append path separately rejects
    symbolic links and aliases before opening the ledger.
    """

    manifest_cid = _cid(
        sealed_manifest_cid,
        "sealed_manifest_cid",
        codecs=("raw",),
    )
    try:
        raw_path = os.fspath(ledger_path)
    except TypeError as exc:
        raise CorpusContractError(
            "replacement access ledger path must be path-like"
        ) from exc
    if not isinstance(raw_path, str) or not raw_path:
        raise CorpusContractError(
            "replacement access ledger path must be a nonempty string"
        )
    path = Path(raw_path)
    if not path.is_absolute():
        raise CorpusContractError(
            "replacement access ledger path must be absolute"
        )
    if ".." in path.parts:
        raise CorpusContractError(
            "replacement access ledger path must not contain '..'"
        )
    canonical_path = Path(os.path.normpath(str(path)))
    if str(path) != str(canonical_path):
        raise CorpusContractError(
            "replacement access ledger path must use canonical absolute "
            "spelling"
        )
    return cid_for_dag_json(
        {
            "schema": REPLACEMENT_HOLDOUT_LEDGER_AUTHORITY_SCHEMA,
            "sealed_manifest_cid": manifest_cid,
            "canonical_absolute_ledger_path": str(canonical_path),
        }
    )


@dataclass(frozen=True, slots=True)
class ReplacementHoldoutSeal:
    """Opaque public metadata for an independently held revision-2 holdout.

    This object intentionally has no filename, case identifiers, source text,
    labels, expected IR, proof obligations, or outcomes.  The sealed manifest
    remains an uninterpreted raw block outside the tuning worktree.  Only the
    independently published count/strata metadata and protocol identities are
    visible before a later HSSL-G230 authorization.

    Constructing a value validates metadata but does not create a replacement
    holdout, attest independent authorship, or authorize access.
    """

    schema: str
    sealed_manifest_cid: str
    case_count: int
    strata_counts: Mapping[str, int]
    protocol_cids: Mapping[str, str]
    access_ledger_authority_cid: str
    seal_contract_cid: str

    def __post_init__(self) -> None:
        if self.schema != REPLACEMENT_HOLDOUT_SEAL_SCHEMA:
            raise CorpusContractError(
                "unsupported replacement-holdout seal schema"
            )
        object.__setattr__(
            self,
            "sealed_manifest_cid",
            _cid(
                self.sealed_manifest_cid,
                "sealed_manifest_cid",
                codecs=("raw",),
            ),
        )
        case_count = _positive_int(self.case_count, "case_count")
        strata_counts = _count_mapping(self.strata_counts, "strata_counts")
        if sum(strata_counts.values()) != case_count:
            raise CorpusContractError(
                "replacement-holdout strata counts must sum to case_count"
            )
        object.__setattr__(self, "case_count", case_count)
        object.__setattr__(self, "strata_counts", strata_counts)

        protocols = _mapping(self.protocol_cids, "protocol_cids")
        if set(protocols) != REPLACEMENT_HOLDOUT_PROTOCOL_KEYS:
            raise CorpusContractError(
                "replacement-holdout protocol identities must exactly bind "
                f"{sorted(REPLACEMENT_HOLDOUT_PROTOCOL_KEYS)!r}"
            )
        normalized_protocols = {
            key: _cid(
                protocols[key],
                f"protocol_cids.{key}",
                codecs=("dag-json",),
            )
            for key in sorted(protocols)
        }
        object.__setattr__(
            self,
            "protocol_cids",
            MappingProxyType(normalized_protocols),
        )
        object.__setattr__(
            self,
            "access_ledger_authority_cid",
            _cid(
                self.access_ledger_authority_cid,
                "access_ledger_authority_cid",
                codecs=("dag-json",),
            ),
        )
        object.__setattr__(
            self,
            "seal_contract_cid",
            _cid(
                self.seal_contract_cid,
                "seal_contract_cid",
                codecs=("dag-json",),
            ),
        )
        if self.seal_contract_cid != cid_for_dag_json(
            self.identity_payload()
        ):
            raise CorpusContractError(
                "seal_contract_cid does not match public replacement seal "
                "metadata"
            )

    def identity_payload(self) -> dict[str, object]:
        """Return only the metadata permitted before G230 authorization."""

        return {
            "schema": self.schema,
            "sealed_manifest_cid": self.sealed_manifest_cid,
            "case_count": self.case_count,
            "strata_counts": dict(self.strata_counts),
            "protocol_cids": dict(self.protocol_cids),
            "access_ledger_authority_cid": (
                self.access_ledger_authority_cid
            ),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "seal_contract_cid": self.seal_contract_cid,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "replacement holdout seal")
        _exact_keys(
            data,
            set(cls.__dataclass_fields__),
            "replacement holdout seal",
        )
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            sealed_manifest_cid=data["sealed_manifest_cid"],  # type: ignore[arg-type]
            case_count=data["case_count"],  # type: ignore[arg-type]
            strata_counts=_mapping(
                data["strata_counts"], "strata_counts"
            ),  # type: ignore[arg-type]
            protocol_cids=_mapping(
                data["protocol_cids"], "protocol_cids"
            ),  # type: ignore[arg-type]
            access_ledger_authority_cid=data[
                "access_ledger_authority_cid"
            ],  # type: ignore[arg-type]
            seal_contract_cid=data["seal_contract_cid"],  # type: ignore[arg-type]
        )


def validate_replacement_holdout_external_path(
    sealed_manifest_path: str | Path,
    *,
    tuning_worktree: str | Path,
) -> Path:
    """Validate an opaque sealed block without opening or decoding it.

    The replacement must be a private regular file at an absolute path outside
    the tuning worktree.  A later authorized executor still receives bytes
    only through its external custodian; this function performs metadata-only
    path validation and is not a loader.
    """

    path = Path(sealed_manifest_path)
    worktree = Path(tuning_worktree)
    if not path.is_absolute() or not worktree.is_absolute():
        raise CorpusContractError(
            "replacement holdout and tuning worktree paths must be absolute"
        )
    if path.is_symlink():
        raise CorpusContractError(
            "replacement holdout path must not be a symbolic link"
        )
    try:
        path.relative_to(worktree)
    except ValueError:
        pass
    else:
        raise CorpusContractError(
            "replacement holdout path must not be addressable inside the "
            "tuning worktree"
        )
    if any(parent.is_symlink() for parent in path.parents):
        raise CorpusContractError(
            "replacement holdout path must not traverse symbolic links"
        )
    try:
        resolved_path = path.resolve(strict=True)
        resolved_worktree = worktree.resolve(strict=True)
    except OSError as exc:
        raise CorpusContractError(
            "replacement holdout path boundary cannot be resolved"
        ) from exc
    try:
        resolved_path.relative_to(resolved_worktree)
    except ValueError:
        pass
    else:
        raise CorpusContractError(
            "replacement holdout must remain outside the tuning worktree"
        )
    if not resolved_path.is_file():
        raise CorpusContractError(
            "replacement holdout path must identify a regular file"
        )
    try:
        metadata = resolved_path.stat()
    except OSError as exc:
        raise CorpusContractError(
            "replacement holdout path metadata is inaccessible"
        ) from exc
    if metadata.st_nlink != 1:
        raise CorpusContractError(
            "replacement holdout file must not have hard-link aliases"
        )
    if metadata.st_mode & 0o077:
        raise CorpusContractError(
            "replacement holdout file must deny group and other access"
        )
    return resolved_path


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


def _split_manifest_payload(
    *,
    schema: str,
    corpus_manifest_sha256_value: str,
    split: Split,
    case_ids: tuple[str, ...],
    case_sha256s: tuple[str, ...],
    source_sha256s: tuple[str, ...],
    normalized_source_sha256s: tuple[str, ...],
) -> dict[str, object]:
    return {
        "schema": schema,
        "corpus_manifest_sha256": corpus_manifest_sha256_value,
        "split": split.value,
        "case_ids": list(case_ids),
        "case_sha256s": list(case_sha256s),
        "source_sha256s": list(source_sha256s),
        "normalized_source_sha256s": list(normalized_source_sha256s),
    }


@dataclass(frozen=True, slots=True)
class SplitManifest:
    """Canonical identity of one ordered, immutable corpus partition."""

    schema: str
    corpus_manifest_sha256: str
    split: Split
    case_ids: tuple[str, ...]
    case_sha256s: tuple[str, ...]
    source_sha256s: tuple[str, ...]
    normalized_source_sha256s: tuple[str, ...]
    split_sha256: str

    def __post_init__(self) -> None:
        if self.schema != SPLIT_MANIFEST_SCHEMA:
            raise CorpusContractError("unsupported split-manifest schema")
        _digest(self.corpus_manifest_sha256, "corpus_manifest_sha256")
        if not isinstance(self.split, Split):
            raise CorpusContractError("split manifest split must be a Split value")

        case_ids = tuple(
            _safe_id(value, "split_manifest.case_ids[]")
            for value in self.case_ids
        )
        if not case_ids or len(set(case_ids)) != len(case_ids):
            raise CorpusContractError(
                "split manifest requires distinct ordered case ids"
            )
        object.__setattr__(self, "case_ids", case_ids)

        digest_fields = (
            "case_sha256s",
            "source_sha256s",
            "normalized_source_sha256s",
        )
        for field_name in digest_fields:
            values = tuple(
                _digest(value, f"split_manifest.{field_name}[]")
                for value in getattr(self, field_name)
            )
            if len(values) != len(case_ids):
                raise CorpusContractError(
                    f"split manifest {field_name} length does not match case ids"
                )
            if len(set(values)) != len(values):
                raise CorpusContractError(
                    f"split manifest {field_name} contains duplicates"
                )
            object.__setattr__(self, field_name, values)

        expected = hashlib.sha256(
            canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()
        if _digest(self.split_sha256, "split_sha256") != expected:
            raise CorpusContractError(
                "split_sha256 does not match split manifest content"
            )
        if (
            self.corpus_manifest_sha256 == FROZEN_CORPUS_MANIFEST_SHA256
            and self.split_sha256 != FROZEN_SPLIT_SHA256[self.split]
        ):
            raise CorpusContractError(
                f"{self.split.value} split identity is not frozen revision 1"
            )

    def identity_payload(self) -> dict[str, object]:
        return _split_manifest_payload(
            schema=self.schema,
            corpus_manifest_sha256_value=self.corpus_manifest_sha256,
            split=self.split,
            case_ids=self.case_ids,
            case_sha256s=self.case_sha256s,
            source_sha256s=self.source_sha256s,
            normalized_source_sha256s=self.normalized_source_sha256s,
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "split_sha256": self.split_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "split_manifest")
        _exact_keys(data, set(cls.__dataclass_fields__), "split_manifest")
        tuple_fields: dict[str, tuple[str, ...]] = {}
        for field_name in (
            "case_ids",
            "case_sha256s",
            "source_sha256s",
            "normalized_source_sha256s",
        ):
            tuple_fields[field_name] = _string_tuple(
                data[field_name], f"split_manifest.{field_name}"
            )
        return cls(
            schema=_nonempty(data["schema"], "split_manifest.schema"),
            corpus_manifest_sha256=_digest(
                data["corpus_manifest_sha256"],
                "split_manifest.corpus_manifest_sha256",
            ),
            split=_enum(  # type: ignore[arg-type]
                Split, data["split"], "split_manifest.split"
            ),
            split_sha256=_digest(
                data["split_sha256"], "split_manifest.split_sha256"
            ),
            **tuple_fields,  # type: ignore[arg-type]
        )


def _integrity_manifest_payload(
    *,
    schema: str,
    corpus_manifest_sha256_value: str,
    normalization_version: str,
    near_duplicate_jaccard_threshold: float,
    splits: tuple[SplitManifest, ...],
) -> dict[str, object]:
    return {
        "schema": schema,
        "corpus_manifest_sha256": corpus_manifest_sha256_value,
        "normalization_version": normalization_version,
        "near_duplicate_jaccard_threshold": near_duplicate_jaccard_threshold,
        "splits": [split.to_dict() for split in splits],
    }


@dataclass(frozen=True, slots=True)
class SplitIntegrityManifest:
    """Frozen aggregate of all split identities and leakage policy."""

    schema: str
    corpus_manifest_sha256: str
    normalization_version: str
    near_duplicate_jaccard_threshold: float
    splits: tuple[SplitManifest, ...]
    integrity_sha256: str

    def __post_init__(self) -> None:
        if self.schema != SPLIT_INTEGRITY_SCHEMA:
            raise CorpusContractError("unsupported split-integrity schema")
        _digest(self.corpus_manifest_sha256, "corpus_manifest_sha256")
        if self.normalization_version != SOURCE_NORMALIZATION_VERSION:
            raise CorpusContractError("unsupported source normalization version")
        threshold = self.near_duplicate_jaccard_threshold
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not math.isfinite(float(threshold))
            or float(threshold) != NEAR_DUPLICATE_JACCARD_THRESHOLD
        ):
            raise CorpusContractError(
                "near-duplicate threshold must match the frozen policy"
            )
        object.__setattr__(
            self, "near_duplicate_jaccard_threshold", float(threshold)
        )

        splits = tuple(self.splits)
        object.__setattr__(self, "splits", splits)
        if tuple(item.split for item in splits) != tuple(Split):
            raise CorpusContractError(
                "split integrity manifest must contain pilot, development, "
                "and holdout in frozen order"
            )
        if any(
            item.corpus_manifest_sha256 != self.corpus_manifest_sha256
            for item in splits
        ):
            raise CorpusContractError(
                "split manifest corpus identities do not match"
            )
        case_ids = tuple(
            case_id for split in splits for case_id in split.case_ids
        )
        if len(set(case_ids)) != len(case_ids):
            raise CorpusContractError("case ids overlap between split manifests")
        source_digests = tuple(
            digest for split in splits for digest in split.source_sha256s
        )
        normalized_digests = tuple(
            digest
            for split in splits
            for digest in split.normalized_source_sha256s
        )
        if len(set(source_digests)) != len(source_digests):
            raise CorpusContractError("exact source content overlaps splits")
        if len(set(normalized_digests)) != len(normalized_digests):
            raise CorpusContractError("normalized source content overlaps splits")

        expected = hashlib.sha256(
            canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()
        if _digest(self.integrity_sha256, "integrity_sha256") != expected:
            raise CorpusContractError(
                "integrity_sha256 does not match split integrity content"
            )
        if (
            self.corpus_manifest_sha256 == FROZEN_CORPUS_MANIFEST_SHA256
            and self.integrity_sha256 != FROZEN_SPLIT_INTEGRITY_SHA256
        ):
            raise CorpusContractError(
                "split-integrity identity is not frozen revision 1"
            )

    @property
    def holdout(self) -> SplitManifest:
        return self.splits[-1]

    @property
    def by_split(self) -> Mapping[Split, SplitManifest]:
        return MappingProxyType({item.split: item for item in self.splits})

    def identity_payload(self) -> dict[str, object]:
        return _integrity_manifest_payload(
            schema=self.schema,
            corpus_manifest_sha256_value=self.corpus_manifest_sha256,
            normalization_version=self.normalization_version,
            near_duplicate_jaccard_threshold=(
                self.near_duplicate_jaccard_threshold
            ),
            splits=self.splits,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "integrity_sha256": self.integrity_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "split_integrity_manifest")
        _exact_keys(
            data,
            set(cls.__dataclass_fields__),
            "split_integrity_manifest",
        )
        raw_splits = data["splits"]
        if not isinstance(raw_splits, list):
            raise CorpusContractError(
                "split_integrity_manifest.splits must be an array"
            )
        threshold = data["near_duplicate_jaccard_threshold"]
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise CorpusContractError(
                "near_duplicate_jaccard_threshold must be numeric"
            )
        return cls(
            schema=_nonempty(
                data["schema"], "split_integrity_manifest.schema"
            ),
            corpus_manifest_sha256=_digest(
                data["corpus_manifest_sha256"],
                "split_integrity_manifest.corpus_manifest_sha256",
            ),
            normalization_version=_nonempty(
                data["normalization_version"],
                "split_integrity_manifest.normalization_version",
            ),
            near_duplicate_jaccard_threshold=float(threshold),
            splits=tuple(SplitManifest.from_dict(item) for item in raw_splits),
            integrity_sha256=_digest(
                data["integrity_sha256"],
                "split_integrity_manifest.integrity_sha256",
            ),
        )


def _make_split_manifest(
    corpus_manifest_digest: str,
    split: Split,
    split_cases: tuple[BenchmarkCase, ...],
) -> SplitManifest:
    payload = _split_manifest_payload(
        schema=SPLIT_MANIFEST_SCHEMA,
        corpus_manifest_sha256_value=corpus_manifest_digest,
        split=split,
        case_ids=tuple(case.case_id for case in split_cases),
        case_sha256s=tuple(case_sha256(case) for case in split_cases),
        source_sha256s=tuple(case.source_sha256 for case in split_cases),
        normalized_source_sha256s=tuple(
            normalized_source_sha256(case.source_text) for case in split_cases
        ),
    )
    split_digest = hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return SplitManifest(
        schema=SPLIT_MANIFEST_SCHEMA,
        corpus_manifest_sha256=corpus_manifest_digest,
        split=split,
        case_ids=tuple(case.case_id for case in split_cases),
        case_sha256s=tuple(case_sha256(case) for case in split_cases),
        source_sha256s=tuple(case.source_sha256 for case in split_cases),
        normalized_source_sha256s=tuple(
            normalized_source_sha256(case.source_text) for case in split_cases
        ),
        split_sha256=split_digest,
    )


def _make_split_integrity_manifest(
    manifest: CorpusManifest,
    cases: tuple[BenchmarkCase, ...],
) -> SplitIntegrityManifest:
    corpus_digest = corpus_manifest_sha256(manifest)
    splits = tuple(
        _make_split_manifest(
            corpus_digest,
            split,
            tuple(case for case in cases if case.split is split),
        )
        for split in Split
    )
    payload = _integrity_manifest_payload(
        schema=SPLIT_INTEGRITY_SCHEMA,
        corpus_manifest_sha256_value=corpus_digest,
        normalization_version=SOURCE_NORMALIZATION_VERSION,
        near_duplicate_jaccard_threshold=NEAR_DUPLICATE_JACCARD_THRESHOLD,
        splits=splits,
    )
    return SplitIntegrityManifest(
        schema=SPLIT_INTEGRITY_SCHEMA,
        corpus_manifest_sha256=corpus_digest,
        normalization_version=SOURCE_NORMALIZATION_VERSION,
        near_duplicate_jaccard_threshold=NEAR_DUPLICATE_JACCARD_THRESHOLD,
        splits=splits,
        integrity_sha256=hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest(),
    )


@dataclass(frozen=True, slots=True)
class ReviewedCorpus:
    """A manifest-verified, deeply immutable ordered case collection."""

    manifest: CorpusManifest
    cases: tuple[BenchmarkCase, ...]
    by_id: Mapping[str, BenchmarkCase] = field(init=False, repr=False)
    split_integrity: SplitIntegrityManifest = field(init=False)

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
        validate_split_integrity(cases)
        split_integrity = _make_split_integrity_manifest(self.manifest, cases)
        if self.manifest_sha256 != FROZEN_CORPUS_MANIFEST_SHA256:
            raise CorpusContractError(
                "reviewed corpus manifest identity is not frozen revision 1"
            )
        for split, expected in FROZEN_SPLIT_SHA256.items():
            if split_integrity.by_split[split].split_sha256 != expected:
                raise CorpusContractError(
                    f"{split.value} split identity is not frozen revision 1"
                )
        if (
            split_integrity.integrity_sha256
            != FROZEN_SPLIT_INTEGRITY_SHA256
        ):
            raise CorpusContractError(
                "split-integrity identity is not frozen revision 1"
            )
        object.__setattr__(self, "split_integrity", split_integrity)
        object.__setattr__(
            self,
            "by_id",
            MappingProxyType({case.case_id: case for case in cases}),
        )

    @property
    def manifest_sha256(self) -> str:
        """Return the digest a benchmark run records as its corpus identity."""

        return corpus_manifest_sha256(self.manifest)


def validate_split_integrity(
    cases: ReviewedCorpus | tuple[BenchmarkCase, ...],
) -> None:
    """Fail closed on split membership, duplicate, prompt, or copy leakage."""

    records = cases.cases if isinstance(cases, ReviewedCorpus) else tuple(cases)
    if not records or any(not isinstance(case, BenchmarkCase) for case in records):
        raise CorpusContractError(
            "split integrity requires BenchmarkCase records"
        )
    case_ids = tuple(case.case_id for case in records)
    if len(set(case_ids)) != len(case_ids):
        raise CorpusContractError("split integrity found duplicate case ids")
    if {case.split for case in records} != set(Split):
        raise CorpusContractError(
            "split integrity requires pilot, development, and holdout cases"
        )
    for case in records:
        if (
            case.split is Split.HOLDOUT
            and case.provenance["prompt_exposure"] != "none"
        ):
            raise CorpusContractError(
                f"holdout prompt leakage for case {case.case_id}: "
                "provenance.prompt_exposure must be 'none'"
            )

    for left_index, left in enumerate(records):
        for right in records[left_index + 1:]:
            if left.split is right.split:
                continue
            pair = (
                f"{left.case_id} ({left.split.value}) and "
                f"{right.case_id} ({right.split.value})"
            )
            if left.source_sha256 == right.source_sha256:
                raise CorpusContractError(
                    f"exact source duplicate across splits: {pair}"
                )
            if (
                normalized_source_sha256(left.source_text)
                == normalized_source_sha256(right.source_text)
            ):
                raise CorpusContractError(
                    f"normalized source duplicate across splits: {pair}"
                )
            left_ref = left.provenance["source_ref"]
            right_ref = right.provenance["source_ref"]
            if left_ref == right_ref:
                raise CorpusContractError(
                    f"source provenance reused across splits: {pair}"
                )
            similarity = source_similarity(left.source_text, right.source_text)
            if similarity >= NEAR_DUPLICATE_JACCARD_THRESHOLD:
                raise CorpusContractError(
                    "near-duplicate source across splits: "
                    f"{pair} (similarity={similarity:.6f}, "
                    f"threshold={NEAR_DUPLICATE_JACCARD_THRESHOLD:.6f})"
                )


def build_split_integrity_manifest(
    corpus: ReviewedCorpus,
) -> SplitIntegrityManifest:
    """Return the validated frozen split manifest for a reviewed corpus."""

    if not isinstance(corpus, ReviewedCorpus):
        raise CorpusContractError("corpus must be a ReviewedCorpus")
    validate_split_integrity(corpus.cases)
    rebuilt = _make_split_integrity_manifest(corpus.manifest, corpus.cases)
    if rebuilt != corpus.split_integrity:
        raise CorpusContractError("stored split integrity manifest is inconsistent")
    return rebuilt


def frozen_holdout_manifest(corpus: ReviewedCorpus) -> SplitManifest:
    """Return the immutable holdout member of the frozen split manifest."""

    return build_split_integrity_manifest(corpus).holdout


def validate_holdout_prompt_isolation(
    corpus: ReviewedCorpus,
    prompt_examples: Mapping[str, str],
) -> tuple[str, ...]:
    """Return prompt-example digests after proving no holdout copy leakage.

    Prompt IDs and normalized prompt text are compared with every holdout case.
    Near copies at or above the frozen shingle threshold are rejected too.
    The returned ordered digests can be bound into a holdout access audit.
    """

    if not isinstance(corpus, ReviewedCorpus):
        raise CorpusContractError("corpus must be a ReviewedCorpus")
    examples = _mapping(prompt_examples, "prompt_examples")
    holdout_cases = tuple(
        case for case in corpus.cases if case.split is Split.HOLDOUT
    )
    digests: list[str] = []
    for example_id in sorted(examples):
        _safe_id(example_id, "prompt_examples key")
        prompt = _nonempty(examples[example_id], f"prompt_examples.{example_id}")
        for case in holdout_cases:
            if example_id == case.case_id:
                raise CorpusContractError(
                    f"holdout case id exposed as prompt example: {case.case_id}"
                )
            if normalized_source_sha256(prompt) == normalized_source_sha256(
                case.source_text
            ):
                raise CorpusContractError(
                    f"holdout source exposed as prompt example: {case.case_id}"
                )
            similarity = source_similarity(prompt, case.source_text)
            if similarity >= NEAR_DUPLICATE_JACCARD_THRESHOLD:
                raise CorpusContractError(
                    f"holdout near-copy exposed as prompt example: {case.case_id}"
                )
        digests.append(
            hashlib.sha256(
                canonical_json(
                    {
                        "example_id": example_id,
                        "normalized_source": normalize_source_text(prompt),
                    }
                ).encode("utf-8")
            ).hexdigest()
        )
    return tuple(digests)


def _holdout_access_payload(
    *,
    schema: str,
    audit_id: str,
    sequence: int,
    purpose: str,
    run_contract_sha256: str,
    run_id: str,
    protocol_sha256: str,
    variant_id: str,
    cache_namespace: str,
    cache_mode: str,
    corpus_manifest_sha256_value: str,
    holdout_split_sha256: str,
    accessed_case_ids: tuple[str, ...],
    configuration_sha256: str,
    prompts_sha256: str,
    policy_sha256: str,
    model_identities_sha256: str,
    thresholds_sha256: str,
    prompt_example_sha256s: tuple[str, ...],
    prompts_frozen: bool,
    policy_frozen: bool,
    model_identities_frozen: bool,
    thresholds_frozen: bool,
    tuning_permitted: bool,
) -> dict[str, object]:
    return {
        "schema": schema,
        "audit_id": audit_id,
        "sequence": sequence,
        "purpose": purpose,
        "run_contract_sha256": run_contract_sha256,
        "run_id": run_id,
        "protocol_sha256": protocol_sha256,
        "variant_id": variant_id,
        "cache_namespace": cache_namespace,
        "cache_mode": cache_mode,
        "corpus_manifest_sha256": corpus_manifest_sha256_value,
        "holdout_split_sha256": holdout_split_sha256,
        "accessed_case_ids": list(accessed_case_ids),
        "configuration_sha256": configuration_sha256,
        "prompts_sha256": prompts_sha256,
        "policy_sha256": policy_sha256,
        "model_identities_sha256": model_identities_sha256,
        "thresholds_sha256": thresholds_sha256,
        "prompt_example_sha256s": list(prompt_example_sha256s),
        "prompts_frozen": prompts_frozen,
        "policy_frozen": policy_frozen,
        "model_identities_frozen": model_identities_frozen,
        "thresholds_frozen": thresholds_frozen,
        "tuning_permitted": tuning_permitted,
    }


@dataclass(frozen=True, slots=True)
class HoldoutAccessAudit:
    """Immutable receipt for one no-tuning access to frozen holdout cases."""

    schema: str
    audit_id: str
    sequence: int
    purpose: str
    run_contract_sha256: str
    run_id: str
    protocol_sha256: str
    variant_id: str
    cache_namespace: str
    cache_mode: str
    corpus_manifest_sha256: str
    holdout_split_sha256: str
    accessed_case_ids: tuple[str, ...]
    configuration_sha256: str
    prompts_sha256: str
    policy_sha256: str
    model_identities_sha256: str
    thresholds_sha256: str
    prompt_example_sha256s: tuple[str, ...]
    prompts_frozen: bool
    policy_frozen: bool
    model_identities_frozen: bool
    thresholds_frozen: bool
    tuning_permitted: bool
    audit_sha256: str

    def __post_init__(self) -> None:
        if self.schema != HOLDOUT_ACCESS_SCHEMA:
            raise CorpusContractError("unsupported holdout-access schema")
        _protocol_safe_id(self.audit_id, "audit_id")
        _positive_int(self.sequence, "sequence", allow_zero=True)
        if self.purpose not in {"evaluation", "replay"}:
            raise CorpusContractError(
                "holdout access purpose must be evaluation or replay"
            )
        _protocol_safe_id(self.run_id, "run_id")
        _protocol_safe_id(self.variant_id, "variant_id")
        for field_name in (
            "run_contract_sha256",
            "protocol_sha256",
            "corpus_manifest_sha256",
            "holdout_split_sha256",
            "configuration_sha256",
            "prompts_sha256",
            "policy_sha256",
            "model_identities_sha256",
            "thresholds_sha256",
            "audit_sha256",
        ):
            _digest(getattr(self, field_name), field_name)
        if (
            not isinstance(self.cache_namespace, str)
            or f"/run/{self.run_id}/" not in self.cache_namespace
            or f"/variant/{self.variant_id}/" not in self.cache_namespace
            or "/split/holdout/" not in self.cache_namespace
            or not self.cache_namespace.endswith(f"/cache/{self.cache_mode}")
        ):
            raise CorpusContractError(
                "holdout cache namespace must bind run, variant, holdout "
                "split, and cache mode"
            )
        if self.cache_mode not in {"cold", "warm"}:
            raise CorpusContractError("unsupported holdout cache mode")
        case_ids = tuple(
            _safe_id(value, "accessed_case_ids[]")
            for value in self.accessed_case_ids
        )
        if not case_ids or len(case_ids) != len(set(case_ids)):
            raise CorpusContractError(
                "holdout access requires distinct accessed case ids"
            )
        object.__setattr__(self, "accessed_case_ids", case_ids)
        prompt_digests = tuple(
            _digest(value, "prompt_example_sha256s[]")
            for value in self.prompt_example_sha256s
        )
        if len(prompt_digests) != len(set(prompt_digests)):
            raise CorpusContractError(
                "prompt example fingerprints must be distinct"
            )
        object.__setattr__(
            self, "prompt_example_sha256s", prompt_digests
        )
        if not all(
            (
                self.prompts_frozen is True,
                self.policy_frozen is True,
                self.model_identities_frozen is True,
                self.thresholds_frozen is True,
            )
        ):
            raise CorpusContractError(
                "all selection inputs must be frozen before holdout access"
            )
        if self.tuning_permitted is not False:
            raise CorpusContractError("tuning is forbidden for holdout access")
        expected = hashlib.sha256(
            canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()
        if self.audit_sha256 != expected:
            raise CorpusContractError(
                "audit_sha256 does not match holdout access content"
            )

    def identity_payload(self) -> dict[str, object]:
        return _holdout_access_payload(
            schema=self.schema,
            audit_id=self.audit_id,
            sequence=self.sequence,
            purpose=self.purpose,
            run_contract_sha256=self.run_contract_sha256,
            run_id=self.run_id,
            protocol_sha256=self.protocol_sha256,
            variant_id=self.variant_id,
            cache_namespace=self.cache_namespace,
            cache_mode=self.cache_mode,
            corpus_manifest_sha256_value=self.corpus_manifest_sha256,
            holdout_split_sha256=self.holdout_split_sha256,
            accessed_case_ids=self.accessed_case_ids,
            configuration_sha256=self.configuration_sha256,
            prompts_sha256=self.prompts_sha256,
            policy_sha256=self.policy_sha256,
            model_identities_sha256=self.model_identities_sha256,
            thresholds_sha256=self.thresholds_sha256,
            prompt_example_sha256s=self.prompt_example_sha256s,
            prompts_frozen=self.prompts_frozen,
            policy_frozen=self.policy_frozen,
            model_identities_frozen=self.model_identities_frozen,
            thresholds_frozen=self.thresholds_frozen,
            tuning_permitted=self.tuning_permitted,
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "audit_sha256": self.audit_sha256}

    def validate_against(self, corpus: ReviewedCorpus) -> None:
        integrity = build_split_integrity_manifest(corpus)
        if self.corpus_manifest_sha256 != corpus.manifest_sha256:
            raise CorpusContractError(
                "holdout audit corpus manifest does not match corpus"
            )
        if self.holdout_split_sha256 != integrity.holdout.split_sha256:
            raise CorpusContractError(
                "holdout audit split identity does not match corpus"
            )
        positions = {
            case_id: index
            for index, case_id in enumerate(integrity.holdout.case_ids)
        }
        if any(case_id not in positions for case_id in self.accessed_case_ids):
            raise CorpusContractError("audit includes a non-holdout case id")
        if tuple(positions[item] for item in self.accessed_case_ids) != tuple(
            sorted(positions[item] for item in self.accessed_case_ids)
        ):
            raise CorpusContractError(
                "holdout access case ids are not in frozen manifest order"
            )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "holdout_access")
        _exact_keys(data, set(cls.__dataclass_fields__), "holdout_access")
        string_fields = (
            "schema",
            "audit_id",
            "purpose",
            "run_contract_sha256",
            "run_id",
            "protocol_sha256",
            "variant_id",
            "cache_namespace",
            "cache_mode",
            "corpus_manifest_sha256",
            "holdout_split_sha256",
            "configuration_sha256",
            "prompts_sha256",
            "policy_sha256",
            "model_identities_sha256",
            "thresholds_sha256",
            "audit_sha256",
        )
        values = {
            field_name: _nonempty(data[field_name], field_name)
            for field_name in string_fields
        }
        return cls(
            sequence=_positive_int(
                data["sequence"], "sequence", allow_zero=True
            ),
            accessed_case_ids=_string_tuple(
                data["accessed_case_ids"], "accessed_case_ids"
            ),
            prompt_example_sha256s=_string_tuple(
                data["prompt_example_sha256s"],
                "prompt_example_sha256s",
            ),
            prompts_frozen=data["prompts_frozen"],  # type: ignore[arg-type]
            policy_frozen=data["policy_frozen"],  # type: ignore[arg-type]
            model_identities_frozen=data[  # type: ignore[arg-type]
                "model_identities_frozen"
            ],
            thresholds_frozen=data["thresholds_frozen"],  # type: ignore[arg-type]
            tuning_permitted=data["tuning_permitted"],  # type: ignore[arg-type]
            **values,  # type: ignore[arg-type]
        )

    @classmethod
    def from_run_contract(
        cls,
        corpus: ReviewedCorpus,
        run_contract: RunContract,
        *,
        prompts_sha256: str,
        policy_sha256: str,
        model_identities_sha256: str,
        thresholds_sha256: str,
        prompt_examples: Mapping[str, str],
        accessed_case_ids: tuple[str, ...] | None = None,
        sequence: int = 0,
        purpose: str = "evaluation",
    ) -> Self:
        """Create an audit receipt after validating all holdout boundaries."""

        if not isinstance(run_contract, RunContract):
            raise CorpusContractError("run_contract must be a RunContract")
        if run_contract.schema != RUN_CONTRACT_SCHEMA:
            raise CorpusContractError("unsupported run contract")
        if run_contract.split is not Split.HOLDOUT:
            raise CorpusContractError(
                "a holdout audit requires a holdout run contract"
            )
        if run_contract.case_manifest_sha256 != corpus.manifest_sha256:
            raise CorpusContractError(
                "run contract does not bind the reviewed corpus manifest"
            )
        integrity = build_split_integrity_manifest(corpus)
        selected = (
            integrity.holdout.case_ids
            if accessed_case_ids is None
            else tuple(accessed_case_ids)
        )
        prompt_digests = validate_holdout_prompt_isolation(
            corpus, prompt_examples
        )
        run_payload = run_contract.to_dict()
        run_digest = hashlib.sha256(
            canonical_json(run_payload).encode("utf-8")
        ).hexdigest()
        payload = _holdout_access_payload(
            schema=HOLDOUT_ACCESS_SCHEMA,
            audit_id=run_contract.holdout_access_log_id or "",
            sequence=sequence,
            purpose=purpose,
            run_contract_sha256=run_digest,
            run_id=run_contract.run_id,
            protocol_sha256=run_contract.protocol_sha256,
            variant_id=run_contract.requested_variant_id,
            cache_namespace=run_contract.cache_namespace,
            cache_mode=run_contract.cache_mode.value,
            corpus_manifest_sha256_value=corpus.manifest_sha256,
            holdout_split_sha256=integrity.holdout.split_sha256,
            accessed_case_ids=selected,
            configuration_sha256=run_contract.configuration_sha256,
            prompts_sha256=_digest(prompts_sha256, "prompts_sha256"),
            policy_sha256=_digest(policy_sha256, "policy_sha256"),
            model_identities_sha256=_digest(
                model_identities_sha256, "model_identities_sha256"
            ),
            thresholds_sha256=_digest(
                thresholds_sha256, "thresholds_sha256"
            ),
            prompt_example_sha256s=prompt_digests,
            prompts_frozen=run_contract.prompts_frozen,
            policy_frozen=run_contract.policy_frozen,
            model_identities_frozen=run_contract.model_identities_frozen,
            thresholds_frozen=run_contract.thresholds_frozen,
            tuning_permitted=run_contract.tuning_permitted,
        )
        result = cls(
            **payload,  # type: ignore[arg-type]
            audit_sha256=hashlib.sha256(
                canonical_json(payload).encode("utf-8")
            ).hexdigest(),
        )
        result.validate_against(corpus)
        return result


def validate_holdout_access_log(
    corpus: ReviewedCorpus,
    records: tuple[HoldoutAccessAudit, ...],
) -> None:
    """Validate a complete ordered log of immutable holdout accesses."""

    audits = tuple(records)
    if not audits or any(
        not isinstance(record, HoldoutAccessAudit) for record in audits
    ):
        raise CorpusContractError(
            "holdout access log requires HoldoutAccessAudit records"
        )
    if tuple(record.sequence for record in audits) != tuple(range(len(audits))):
        raise CorpusContractError(
            "holdout access sequences must be contiguous and ordered"
        )
    audit_ids = tuple(record.audit_id for record in audits)
    if len(set(audit_ids)) != len(audit_ids):
        raise CorpusContractError("holdout access log contains duplicate audit ids")
    for record in audits:
        record.validate_against(corpus)


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


def load_unsealed_pilot_development(
    corpus_path: str | Path = DEFAULT_CORPUS_PATH,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> tuple[CorpusManifest, tuple[BenchmarkCase, ...]]:
    """Load only the manifest-bound pilot/development prefix.

    This is the pre-authorization corpus boundary.  It deliberately uses
    unbuffered, line-oriented binary I/O and stops after the last declared
    development record, so the holdout tail is neither prefetched nor
    deserialized.  The frozen manifest still binds every selected record and
    proves that every remaining record belongs to the sealed holdout split.
    """

    manifest = load_manifest(manifest_path)
    if corpus_manifest_sha256(manifest) != FROZEN_CORPUS_MANIFEST_SHA256:
        raise CorpusContractError(
            "unsealed corpus loader requires frozen reviewed manifest revision 1"
        )
    split_counts = manifest.split_counts
    pilot_count = split_counts.get(Split.PILOT.value)
    development_count = split_counts.get(Split.DEVELOPMENT.value)
    holdout_count = split_counts.get(Split.HOLDOUT.value)
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in (pilot_count, development_count, holdout_count)
    ):
        raise CorpusContractError("frozen manifest split counts are invalid")
    assert isinstance(pilot_count, int)
    assert isinstance(development_count, int)
    assert isinstance(holdout_count, int)
    selected_count = pilot_count + development_count
    if selected_count + holdout_count != manifest.case_count:
        raise CorpusContractError("frozen manifest split counts do not cover corpus")
    expected_entries = manifest.cases[:selected_count]
    sealed_entries = manifest.cases[selected_count:]
    if (
        tuple(entry.ordinal for entry in expected_entries)
        != tuple(range(selected_count))
        or tuple(entry.ordinal for entry in sealed_entries)
        != tuple(range(selected_count, manifest.case_count))
        or sum(entry.split is Split.PILOT for entry in expected_entries)
        != pilot_count
        or sum(entry.split is Split.DEVELOPMENT for entry in expected_entries)
        != development_count
        or any(entry.split is Split.HOLDOUT for entry in expected_entries)
        or len(sealed_entries) != holdout_count
        or any(entry.split is not Split.HOLDOUT for entry in sealed_entries)
    ):
        raise CorpusContractError("manifest split seal or ordering drifted")

    path = Path(corpus_path)
    if path.is_symlink():
        raise CorpusContractError("unsealed corpus path must not be a symlink")
    cases: list[BenchmarkCase] = []
    try:
        with path.open("rb", buffering=0) as handle:
            for ordinal, entry in enumerate(expected_entries):
                raw = handle.readline()
                if not raw.endswith(b"\n") or not raw.strip():
                    raise CorpusContractError(
                        f"unsealed corpus line {ordinal + 1} is incomplete"
                    )
                try:
                    text = raw[:-1].decode("utf-8")
                    case = BenchmarkCase.from_dict(
                        _decode_json(text, f"unsealed corpus line {ordinal + 1}")
                    )
                except (UnicodeError, ValueError, CorpusContractError) as exc:
                    raise CorpusContractError(
                        f"unsealed corpus line {ordinal + 1} is invalid"
                    ) from exc
                if canonical_json(case.to_dict()) != text:
                    raise CorpusContractError(
                        f"unsealed corpus line {ordinal + 1} is not canonical"
                    )
                if (
                    case.case_id != entry.case_id
                    or case.split is not entry.split
                    or case.stratum != entry.stratum
                    or case.source_sha256 != entry.source_sha256
                    or case_sha256(case) != entry.case_sha256
                ):
                    raise CorpusContractError(
                        f"unsealed corpus line {ordinal + 1} drifted"
                    )
                cases.append(case)
    except CorpusContractError:
        raise
    except OSError as exc:
        raise CorpusContractError("cannot open unsealed corpus prefix") from exc
    return manifest, tuple(cases)


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
    "FROZEN_CORPUS_MANIFEST_SHA256",
    "FROZEN_SPLIT_INTEGRITY_SHA256",
    "FROZEN_SPLIT_SHA256",
    "HOLDOUT_ACCESS_SCHEMA",
    "NEAR_DUPLICATE_JACCARD_THRESHOLD",
    "REPLACEMENT_HOLDOUT_PROTOCOL_KEYS",
    "REPLACEMENT_HOLDOUT_LEDGER_AUTHORITY_SCHEMA",
    "REPLACEMENT_HOLDOUT_SEAL_SCHEMA",
    "REVIEW_SCHEMA",
    "SOURCE_NORMALIZATION_VERSION",
    "SPLIT_INTEGRITY_SCHEMA",
    "SPLIT_MANIFEST_SCHEMA",
    "BenchmarkCase",
    "CorpusContractError",
    "CorpusManifest",
    "Difficulty",
    "ExpectedClass",
    "HSSLEV0201B64",
    "HSSLEV0232D57",
    "HoldoutAccessAudit",
    "ManifestCase",
    "ReviewAttestation",
    "ReplacementHoldoutSeal",
    "ReviewedCorpus",
    "SplitIntegrityManifest",
    "SplitManifest",
    "build_split_integrity_manifest",
    "canonical_json",
    "case_sha256",
    "corpus_manifest_sha256",
    "frozen_holdout_manifest",
    "load_corpus",
    "load_manifest",
    "load_reviewed_corpus",
    "load_unsealed_pilot_development",
    "normalize_source_text",
    "normalized_source_sha256",
    "replacement_holdout_ledger_authority_cid",
    "source_similarity",
    "validate_holdout_access_log",
    "validate_holdout_prompt_isolation",
    "validate_replacement_holdout_external_path",
    "validate_split_integrity",
]
