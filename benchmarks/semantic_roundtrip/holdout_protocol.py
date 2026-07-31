"""PLAT2-020 repair-development / blind-holdout population freeze and custody.

This module freezes three disjoint populations before repair-development
outcomes are inspected:

* ``pilot`` — sealed historical regression controls (visible fixture).
* ``repair_development`` — visible diagnostic population with source/gold.
* ``blind_holdout`` — access-controlled private corpus whose sources/gold live
  only in a custodian store outside agent and tuning worktrees.

Public artifacts expose only:

* population manifests for pilot and repair-development (with digests),
* a public blind seal with schema, count/strata, aggregate commitments to
  ordered private source/gold/provenance manifests, sample-size justification,
  and the seal CID,

and never per-case digests, source text, labels, gold IR, or semantic hints
for the blind population.

Leakage checks (exact, normalized, provenance, preregistered near-duplicate)
and prompt-example isolation reject cross-split contamination. An append-only
access ledger rejects access before PLAT2-055 authorization, repeated access,
and post-access tuning. Underpowered populations are exploratory and cannot
authorize promotion.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, Iterable

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.semantic_roundtrip.matrix import MatrixCase, load_matrix_cases
from benchmarks.semantic_roundtrip.residual_catalog import PILOT_CASE_IDS


# ---------------------------------------------------------------------------
# Interfaces and schema constants
# ---------------------------------------------------------------------------

SEMANTIC_ROUNDTRIP_POPULATION_MANIFEST_INTERFACE: Final = (
    "SemanticRoundtripPopulationManifest@1"
)
SEMANTIC_ROUNDTRIP_HOLDOUT_SEAL_INTERFACE: Final = (
    "SemanticRoundtripHoldoutSeal@1"
)
HOLDOUT_ACCESS_AUDIT_INTERFACE: Final = "HoldoutAccessAudit@1"

POPULATION_MANIFEST_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip.population-manifest.v1"
)
BLIND_HOLDOUT_SEAL_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip.plateau2-blind-holdout-seal.v1"
)
ACCESS_LEDGER_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip.holdout-access-ledger.v1"
)
ACCESS_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip.holdout-access-receipt.v1"
)
SAMPLE_SIZE_JUSTIFICATION_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip.sample-size-justification.v1"
)
LEAKAGE_POLICY_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip.leakage-policy.v1"
)

POPULATION_KIND_PILOT: Final = "pilot"
POPULATION_KIND_REPAIR_DEVELOPMENT: Final = "repair_development"
POPULATION_KIND_BLIND_HOLDOUT: Final = "blind_holdout"
POPULATION_KINDS: Final = (
    POPULATION_KIND_PILOT,
    POPULATION_KIND_REPAIR_DEVELOPMENT,
    POPULATION_KIND_BLIND_HOLDOUT,
)

SOURCE_NORMALIZATION_VERSION: Final = "unicode-nfkc-casefold-alnum-v1"
NEAR_DUPLICATE_JACCARD_THRESHOLD: Final = 0.8
PLAT2_055_AUTHORIZATION_GOAL: Final = "PLAT2-055"
AUTHORIZATION_GOAL_ID: Final = PLAT2_055_AUTHORIZATION_GOAL

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
PILOT_CASES_RELATIVE_PATH: Final = Path(
    "tests/fixtures/semantic_roundtrip/pilot_cases.json"
)
REPAIR_DEV_CASES_RELATIVE_PATH: Final = Path(
    "tests/fixtures/semantic_roundtrip/repair_dev_cases.json"
)
BLIND_SEAL_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "plateau2_blind_holdout_seal.json"
)

# Preregistered precision justification for the frozen blind population.
# Half-width target for paired case-cluster bootstrap CI on end-to-end delta.
FROZEN_BLIND_CASE_COUNT: Final = 12
FROZEN_BLIND_STRATA_COUNTS: Final = MappingProxyType(
    {
        "complexity_tier_1": 4,
        "complexity_tier_2": 8,
    }
)
FROZEN_TARGET_CI_HALF_WIDTH: Final = 0.05
FROZEN_ALPHA: Final = 0.05
FROZEN_ASSUMED_SD_PAIRED_DELTA: Final = 0.08
FROZEN_Z_CRITICAL: Final = 1.959963984540054  # Phi^{-1}(0.975)

# Private-content field names that must never appear on the public seal.
_FORBIDDEN_PUBLIC_SEAL_KEYS: Final = frozenset(
    {
        "case_ids",
        "cases",
        "case_id",
        "case_sha256s",
        "case_cids",
        "source_text",
        "source_texts",
        "source_sha256s",
        "source_text_cids",
        "normalized_source_sha256s",
        "gold_ir",
        "gold_irs",
        "gold_ir_cids",
        "labels",
        "label",
        "score_bindings",
        "semantic_hints",
        "residuals",
        "diagnostics",
        "per_case_digests",
        "per_case",
        "allowed_atoms",
        "allowed_atom_vocabulary",
    }
)

_SAFE_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")

_ACCESS_EVENTS: Final = frozenset(
    {
        "access_granted",
        "manifest_released",
        "premature_access",
        "repeated_access_rejected",
        "post_access_tuning_rejected",
        "unauthorized_access_rejected",
    }
)


class HoldoutProtocolError(ValueError):
    """Raised when a population, seal, leakage, or access boundary fails."""


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def canonical_json(value: object) -> str:
    """Return the unique UTF-8 JSON form used by protocol digests."""

    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha256_json(value: object) -> str:
    return sha256_hex(canonical_json(value))


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise HoldoutProtocolError(f"{field} must be an object with string keys")
    return value


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HoldoutProtocolError(f"{field} must be a nonblank string")
    return value


def _safe_id(value: object, field: str) -> str:
    text = _nonempty(value, field)
    if not _SAFE_ID_RE.fullmatch(text):
        raise HoldoutProtocolError(f"{field} is not a safe protocol id: {text!r}")
    return text


def _digest(value: object, field: str) -> str:
    text = _nonempty(value, field).lower()
    if not _SHA256_RE.fullmatch(text):
        raise HoldoutProtocolError(f"{field} must be a lowercase sha256 hex digest")
    return text


def _cid(value: object, field: str, *, codecs: Iterable[str]) -> str:
    text = _nonempty(value, field)
    try:
        return validate_cid(text, codecs=tuple(codecs))
    except ValueError as exc:
        raise HoldoutProtocolError(f"{field} is not a valid CID: {exc}") from exc


def _positive_int(value: object, field: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HoldoutProtocolError(f"{field} must be an integer")
    if allow_zero:
        if value < 0:
            raise HoldoutProtocolError(f"{field} must be nonnegative")
    elif value <= 0:
        raise HoldoutProtocolError(f"{field} must be a positive integer")
    return value


def _finite_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HoldoutProtocolError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise HoldoutProtocolError(f"{field} must be finite")
    return number


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise HoldoutProtocolError(f"{field} must be a boolean")
    return value


def _count_mapping(value: object, field: str) -> dict[str, int]:
    raw = _mapping(value, field)
    result: dict[str, int] = {}
    for key in sorted(raw):
        stratum = _safe_id(key, f"{field} key")
        count = _positive_int(raw[key], f"{field}.{stratum}")
        result[stratum] = count
    if not result:
        raise HoldoutProtocolError(f"{field} must be nonempty")
    return result


def _exact_keys(
    data: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    observed = set(data)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise HoldoutProtocolError(
            f"{field} keys mismatch; missing={missing!r} extra={extra!r}"
        )


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise HoldoutProtocolError(f"{field} must be an array of strings")
    return tuple(_safe_id(item, f"{field}[]") for item in value)


# ---------------------------------------------------------------------------
# Source normalization and leakage primitives
# ---------------------------------------------------------------------------


def normalize_source_text(value: str) -> str:
    """Return the frozen comparison form used for leakage detection.

    Compatibility characters are folded with NFKC, casing is removed with
    Unicode ``casefold``, and every run of punctuation or whitespace becomes
    one ASCII space.
    """

    if not isinstance(value, str) or not value.strip():
        raise HoldoutProtocolError("source_text must be a nonempty string")
    normalized = unicodedata.normalize("NFKC", value.strip()).casefold()
    result = " ".join(
        "".join(
            character if character.isalnum() else " " for character in normalized
        ).split()
    )
    if not result:
        raise HoldoutProtocolError(
            "source_text must contain alphanumeric content after normalization"
        )
    return result


def normalized_source_sha256(value: str) -> str:
    """Return the digest of :func:`normalize_source_text`."""

    return sha256_hex(normalize_source_text(value))


def _source_shingles(value: str) -> frozenset[tuple[str, ...]]:
    tokens = normalize_source_text(value).split()
    width = min(3, len(tokens))
    if width == 0:
        return frozenset()
    return frozenset(
        tuple(tokens[index : index + width])
        for index in range(len(tokens) - width + 1)
    )


def source_similarity(left: str, right: str) -> float:
    """Return deterministic token-shingle Jaccard similarity in ``[0, 1]``."""

    left_shingles = _source_shingles(left)
    right_shingles = _source_shingles(right)
    union = left_shingles | right_shingles
    if not union:
        return 0.0
    return len(left_shingles & right_shingles) / len(union)


def leakage_policy_payload() -> dict[str, object]:
    """Return the frozen leakage policy bound into seals and audits."""

    return {
        "schema": LEAKAGE_POLICY_SCHEMA,
        "normalization_version": SOURCE_NORMALIZATION_VERSION,
        "near_duplicate_jaccard_threshold": NEAR_DUPLICATE_JACCARD_THRESHOLD,
        "checks": [
            "exact_source",
            "normalized_source",
            "provenance_source_ref",
            "near_duplicate_shingle_jaccard",
            "prompt_example_overlap",
        ],
        "cross_split_pairs": [
            [POPULATION_KIND_PILOT, POPULATION_KIND_REPAIR_DEVELOPMENT],
            [POPULATION_KIND_PILOT, POPULATION_KIND_BLIND_HOLDOUT],
            [POPULATION_KIND_REPAIR_DEVELOPMENT, POPULATION_KIND_BLIND_HOLDOUT],
        ],
    }


def leakage_policy_cid() -> str:
    return cid_for_dag_json(leakage_policy_payload())


# ---------------------------------------------------------------------------
# Lightweight case view used by manifests and leakage checks
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PopulationCaseView:
    """Minimal case surface required for freeze and leakage checks."""

    case_id: str
    population_kind: str
    source_text: str
    source_ref: str
    stratum: str
    gold_ir: Mapping[str, object] | None
    prompt_exposure: str = "none"

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _safe_id(self.case_id, "case_id"))
        if self.population_kind not in POPULATION_KINDS:
            raise HoldoutProtocolError(
                f"unknown population_kind: {self.population_kind!r}"
            )
        if not isinstance(self.source_text, str) or not self.source_text.strip():
            raise HoldoutProtocolError("source_text must be a nonempty string")
        object.__setattr__(
            self, "source_ref", _nonempty(self.source_ref, "source_ref")
        )
        object.__setattr__(self, "stratum", _safe_id(self.stratum, "stratum"))
        if self.prompt_exposure not in {"none", "development", "pilot"}:
            raise HoldoutProtocolError(
                "prompt_exposure must be none, development, or pilot"
            )
        if (
            self.population_kind == POPULATION_KIND_BLIND_HOLDOUT
            and self.prompt_exposure != "none"
        ):
            raise HoldoutProtocolError(
                f"blind case {self.case_id} must have prompt_exposure=none"
            )
        if self.gold_ir is not None and not isinstance(self.gold_ir, Mapping):
            raise HoldoutProtocolError("gold_ir must be an object when present")

    @property
    def source_sha256(self) -> str:
        return sha256_hex(self.source_text)

    @property
    def normalized_source_sha256(self) -> str:
        return normalized_source_sha256(self.source_text)

    @property
    def gold_ir_cid(self) -> str | None:
        if self.gold_ir is None:
            return None
        return cid_for_dag_json(dict(self.gold_ir))

    @property
    def case_content_cid(self) -> str:
        payload: dict[str, object] = {
            "case_id": self.case_id,
            "population_kind": self.population_kind,
            "source_sha256": self.source_sha256,
            "source_ref": self.source_ref,
            "stratum": self.stratum,
        }
        if self.gold_ir is not None:
            payload["gold_ir_cid"] = self.gold_ir_cid
        return cid_for_dag_json(payload)


def _matrix_case_to_view(
    case: MatrixCase,
    *,
    population_kind: str,
    source_ref: str,
    stratum: str,
    raw: Mapping[str, object] | None = None,
) -> PopulationCaseView:
    ref = source_ref
    stratum_value = stratum
    prompt_exposure = "none"
    if raw is not None:
        if isinstance(raw.get("source_ref"), str) and raw["source_ref"].strip():
            ref = str(raw["source_ref"])
        family = raw.get("case_family")
        tier = raw.get("complexity_tier")
        if isinstance(family, str) and family.strip():
            stratum_value = family
        elif isinstance(tier, int) and not isinstance(tier, bool):
            stratum_value = f"complexity_tier_{tier}"
        exposure = raw.get("prompt_exposure")
        if isinstance(exposure, str) and exposure.strip():
            prompt_exposure = exposure
    return PopulationCaseView(
        case_id=case.case_id,
        population_kind=population_kind,
        source_text=case.source_text,
        source_ref=ref,
        stratum=stratum_value,
        gold_ir=case.gold_ir.to_dict(),
        prompt_exposure=prompt_exposure,
    )


def load_raw_case_dicts(path: str | Path) -> list[dict[str, object]]:
    """Load a JSON array of matrix-compatible case objects."""

    text = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HoldoutProtocolError(f"invalid case fixture JSON: {exc}") from exc
    if not isinstance(payload, list) or not payload:
        raise HoldoutProtocolError("case fixture must be a nonempty array")
    cases: list[dict[str, object]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise HoldoutProtocolError(f"case fixture entry {index} is not an object")
        cases.append(item)
    return cases


def load_population_case_views(
    path: str | Path,
    *,
    population_kind: str,
) -> tuple[PopulationCaseView, ...]:
    """Load fixture cases as protocol views (source/gold exposed)."""

    if population_kind not in {
        POPULATION_KIND_PILOT,
        POPULATION_KIND_REPAIR_DEVELOPMENT,
    }:
        raise HoldoutProtocolError(
            "only pilot and repair_development fixtures may expose source/gold"
        )
    raw_cases = load_raw_case_dicts(path)
    matrix_cases = load_matrix_cases(path)
    if len(raw_cases) != len(matrix_cases):
        raise HoldoutProtocolError("fixture length mismatch after matrix load")
    views: list[PopulationCaseView] = []
    for raw, case in zip(raw_cases, matrix_cases):
        default_stratum = (
            "pilot"
            if population_kind == POPULATION_KIND_PILOT
            else "repair_development"
        )
        views.append(
            _matrix_case_to_view(
                case,
                population_kind=population_kind,
                source_ref=f"{path}#{case.case_id}",
                stratum=default_stratum,
                raw=raw,
            )
        )
    return tuple(views)


# ---------------------------------------------------------------------------
# Sample-size / power justification
# ---------------------------------------------------------------------------


def required_case_count_for_precision(
    *,
    target_ci_half_width: float = FROZEN_TARGET_CI_HALF_WIDTH,
    assumed_sd: float = FROZEN_ASSUMED_SD_PAIRED_DELTA,
    alpha: float = FROZEN_ALPHA,
    z_critical: float = FROZEN_Z_CRITICAL,
) -> int:
    """Return the preregistered precision-based minimum case count.

    Uses the normal approximation ``n >= (z * sd / half_width)^2`` for a
    two-sided CI half-width on the mean paired end-to-end delta.
    """

    half = _finite_float(target_ci_half_width, "target_ci_half_width")
    sd = _finite_float(assumed_sd, "assumed_sd")
    a = _finite_float(alpha, "alpha")
    z = _finite_float(z_critical, "z_critical")
    if half <= 0.0 or sd <= 0.0:
        raise HoldoutProtocolError("precision inputs must be positive")
    if not 0.0 < a < 1.0:
        raise HoldoutProtocolError("alpha must be in (0, 1)")
    if z <= 0.0:
        raise HoldoutProtocolError("z_critical must be positive")
    raw = (z * sd / half) ** 2
    return max(1, int(math.ceil(raw - 1e-12)))


@dataclass(frozen=True, slots=True)
class SampleSizeJustification:
    """Preregistered precision/power justification for a population."""

    schema: str
    method: str
    alpha: float
    target_ci_half_width: float
    assumed_sd_paired_delta: float
    z_critical: float
    required_case_count: int
    actual_case_count: int
    strata_counts: Mapping[str, int]
    powered: bool
    exploratory: bool
    promotion_eligible: bool
    notes: str

    def __post_init__(self) -> None:
        if self.schema != SAMPLE_SIZE_JUSTIFICATION_SCHEMA:
            raise HoldoutProtocolError("unsupported sample-size justification schema")
        if self.method != "paired_case_cluster_bootstrap_precision":
            raise HoldoutProtocolError(
                "sample-size method must be "
                "paired_case_cluster_bootstrap_precision"
            )
        object.__setattr__(self, "alpha", _finite_float(self.alpha, "alpha"))
        object.__setattr__(
            self,
            "target_ci_half_width",
            _finite_float(self.target_ci_half_width, "target_ci_half_width"),
        )
        object.__setattr__(
            self,
            "assumed_sd_paired_delta",
            _finite_float(
                self.assumed_sd_paired_delta, "assumed_sd_paired_delta"
            ),
        )
        object.__setattr__(
            self, "z_critical", _finite_float(self.z_critical, "z_critical")
        )
        required = _positive_int(self.required_case_count, "required_case_count")
        actual = _positive_int(self.actual_case_count, "actual_case_count")
        object.__setattr__(self, "required_case_count", required)
        object.__setattr__(self, "actual_case_count", actual)
        strata = _count_mapping(dict(self.strata_counts), "strata_counts")
        if sum(strata.values()) != actual:
            raise HoldoutProtocolError(
                "strata_counts must sum to actual_case_count"
            )
        object.__setattr__(self, "strata_counts", MappingProxyType(strata))
        powered = _bool(self.powered, "powered")
        exploratory = _bool(self.exploratory, "exploratory")
        promotion = _bool(self.promotion_eligible, "promotion_eligible")
        expected_required = required_case_count_for_precision(
            target_ci_half_width=self.target_ci_half_width,
            assumed_sd=self.assumed_sd_paired_delta,
            alpha=self.alpha,
            z_critical=self.z_critical,
        )
        if required != expected_required:
            raise HoldoutProtocolError(
                "required_case_count does not match preregistered precision formula"
            )
        expected_powered = actual >= required
        if powered != expected_powered:
            raise HoldoutProtocolError(
                "powered flag must equal actual_case_count >= required_case_count"
            )
        if exploratory != (not powered):
            raise HoldoutProtocolError(
                "exploratory must be true exactly when the population is underpowered"
            )
        if promotion and not powered:
            raise HoldoutProtocolError(
                "underpowered population cannot be promotion_eligible"
            )
        if promotion != powered:
            # Powered populations may still be blocked by other gates, but
            # sample-size alone permits promotion eligibility only when powered.
            raise HoldoutProtocolError(
                "promotion_eligible must match powered for sample-size gate"
            )
        object.__setattr__(self, "powered", powered)
        object.__setattr__(self, "exploratory", exploratory)
        object.__setattr__(self, "promotion_eligible", promotion)
        object.__setattr__(self, "notes", _nonempty(self.notes, "notes"))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "method": self.method,
            "alpha": self.alpha,
            "target_ci_half_width": self.target_ci_half_width,
            "assumed_sd_paired_delta": self.assumed_sd_paired_delta,
            "z_critical": self.z_critical,
            "required_case_count": self.required_case_count,
            "actual_case_count": self.actual_case_count,
            "strata_counts": dict(self.strata_counts),
            "powered": self.powered,
            "exploratory": self.exploratory,
            "promotion_eligible": self.promotion_eligible,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: object) -> "SampleSizeJustification":
        data = _mapping(value, "sample_size_justification")
        _exact_keys(data, set(cls.__dataclass_fields__), "sample_size_justification")
        return cls(
            schema=_nonempty(data["schema"], "schema"),
            method=_nonempty(data["method"], "method"),
            alpha=data["alpha"],  # type: ignore[arg-type]
            target_ci_half_width=data["target_ci_half_width"],  # type: ignore[arg-type]
            assumed_sd_paired_delta=data[  # type: ignore[arg-type]
                "assumed_sd_paired_delta"
            ],
            z_critical=data["z_critical"],  # type: ignore[arg-type]
            required_case_count=data["required_case_count"],  # type: ignore[arg-type]
            actual_case_count=data["actual_case_count"],  # type: ignore[arg-type]
            strata_counts=_mapping(data["strata_counts"], "strata_counts"),
            powered=data["powered"],  # type: ignore[arg-type]
            exploratory=data["exploratory"],  # type: ignore[arg-type]
            promotion_eligible=data["promotion_eligible"],  # type: ignore[arg-type]
            notes=_nonempty(data["notes"], "notes"),
        )

    @classmethod
    def build(
        cls,
        *,
        actual_case_count: int,
        strata_counts: Mapping[str, int],
        notes: str,
        target_ci_half_width: float = FROZEN_TARGET_CI_HALF_WIDTH,
        assumed_sd_paired_delta: float = FROZEN_ASSUMED_SD_PAIRED_DELTA,
        alpha: float = FROZEN_ALPHA,
        z_critical: float = FROZEN_Z_CRITICAL,
    ) -> "SampleSizeJustification":
        required = required_case_count_for_precision(
            target_ci_half_width=target_ci_half_width,
            assumed_sd=assumed_sd_paired_delta,
            alpha=alpha,
            z_critical=z_critical,
        )
        powered = actual_case_count >= required
        return cls(
            schema=SAMPLE_SIZE_JUSTIFICATION_SCHEMA,
            method="paired_case_cluster_bootstrap_precision",
            alpha=alpha,
            target_ci_half_width=target_ci_half_width,
            assumed_sd_paired_delta=assumed_sd_paired_delta,
            z_critical=z_critical,
            required_case_count=required,
            actual_case_count=actual_case_count,
            strata_counts=strata_counts,
            powered=powered,
            exploratory=not powered,
            promotion_eligible=powered,
            notes=notes,
        )


# ---------------------------------------------------------------------------
# Population manifest (visible populations)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SemanticRoundtripPopulationManifest:
    """Frozen ordered identity of one visible population.

    Interface: ``SemanticRoundtripPopulationManifest@1``.
    Blind populations never construct this with source/gold material in-repo;
    they use :class:`BlindHoldoutSeal` instead.
    """

    interface: str
    schema: str
    population_kind: str
    fixture_path: str
    case_ids: tuple[str, ...]
    case_content_cids: tuple[str, ...]
    source_sha256s: tuple[str, ...]
    normalized_source_sha256s: tuple[str, ...]
    source_refs: tuple[str, ...]
    strata_counts: Mapping[str, int]
    case_count: int
    fixture_sha256: str
    fixture_cid: str
    sample_size_justification: SampleSizeJustification
    manifest_cid: str

    def __post_init__(self) -> None:
        if self.interface != SEMANTIC_ROUNDTRIP_POPULATION_MANIFEST_INTERFACE:
            raise HoldoutProtocolError(
                "unsupported population manifest interface"
            )
        if self.schema != POPULATION_MANIFEST_SCHEMA:
            raise HoldoutProtocolError("unsupported population manifest schema")
        if self.population_kind not in {
            POPULATION_KIND_PILOT,
            POPULATION_KIND_REPAIR_DEVELOPMENT,
        }:
            raise HoldoutProtocolError(
                "population manifest is only for pilot or repair_development; "
                "blind holdout uses the public seal"
            )
        object.__setattr__(
            self, "fixture_path", _nonempty(self.fixture_path, "fixture_path")
        )
        case_ids = tuple(
            _safe_id(item, "case_ids[]") for item in self.case_ids
        )
        if not case_ids or len(set(case_ids)) != len(case_ids):
            raise HoldoutProtocolError(
                "population manifest requires distinct ordered case ids"
            )
        object.__setattr__(self, "case_ids", case_ids)
        for field_name in (
            "case_content_cids",
            "source_sha256s",
            "normalized_source_sha256s",
            "source_refs",
        ):
            values = tuple(getattr(self, field_name))
            if len(values) != len(case_ids):
                raise HoldoutProtocolError(
                    f"{field_name} length does not match case_ids"
                )
            if field_name == "source_refs":
                normalized = tuple(
                    _nonempty(item, f"{field_name}[]") for item in values
                )
            elif field_name.endswith("sha256s"):
                normalized = tuple(
                    _digest(item, f"{field_name}[]") for item in values
                )
            else:
                normalized = tuple(
                    _cid(item, f"{field_name}[]", codecs=("dag-json",))
                    for item in values
                )
            if len(set(normalized)) != len(normalized):
                raise HoldoutProtocolError(f"{field_name} contains duplicates")
            object.__setattr__(self, field_name, normalized)
        case_count = _positive_int(self.case_count, "case_count")
        if case_count != len(case_ids):
            raise HoldoutProtocolError("case_count does not match case_ids")
        object.__setattr__(self, "case_count", case_count)
        strata = _count_mapping(dict(self.strata_counts), "strata_counts")
        if sum(strata.values()) != case_count:
            raise HoldoutProtocolError("strata_counts must sum to case_count")
        object.__setattr__(self, "strata_counts", MappingProxyType(strata))
        object.__setattr__(
            self, "fixture_sha256", _digest(self.fixture_sha256, "fixture_sha256")
        )
        object.__setattr__(
            self,
            "fixture_cid",
            _cid(self.fixture_cid, "fixture_cid", codecs=("raw",)),
        )
        if not isinstance(
            self.sample_size_justification, SampleSizeJustification
        ):
            raise HoldoutProtocolError(
                "sample_size_justification must be SampleSizeJustification"
            )
        if self.sample_size_justification.actual_case_count != case_count:
            raise HoldoutProtocolError(
                "sample_size_justification.actual_case_count must match"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if (
            _cid(self.manifest_cid, "manifest_cid", codecs=("dag-json",))
            != expected
        ):
            raise HoldoutProtocolError(
                "manifest_cid does not match population manifest content"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "interface": self.interface,
            "schema": self.schema,
            "population_kind": self.population_kind,
            "fixture_path": self.fixture_path,
            "case_ids": list(self.case_ids),
            "case_content_cids": list(self.case_content_cids),
            "source_sha256s": list(self.source_sha256s),
            "normalized_source_sha256s": list(self.normalized_source_sha256s),
            "source_refs": list(self.source_refs),
            "strata_counts": dict(self.strata_counts),
            "case_count": self.case_count,
            "fixture_sha256": self.fixture_sha256,
            "fixture_cid": self.fixture_cid,
            "sample_size_justification": self.sample_size_justification.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "manifest_cid": self.manifest_cid}

    @classmethod
    def from_dict(cls, value: object) -> "SemanticRoundtripPopulationManifest":
        data = _mapping(value, "population_manifest")
        _exact_keys(
            data, set(cls.__dataclass_fields__), "population_manifest"
        )
        return cls(
            interface=_nonempty(data["interface"], "interface"),
            schema=_nonempty(data["schema"], "schema"),
            population_kind=_nonempty(data["population_kind"], "population_kind"),
            fixture_path=_nonempty(data["fixture_path"], "fixture_path"),
            case_ids=_string_tuple(data["case_ids"], "case_ids"),
            case_content_cids=tuple(
                _cid(item, "case_content_cids[]", codecs=("dag-json",))
                for item in data["case_content_cids"]  # type: ignore[arg-type]
            ),
            source_sha256s=tuple(
                _digest(item, "source_sha256s[]")
                for item in data["source_sha256s"]  # type: ignore[arg-type]
            ),
            normalized_source_sha256s=tuple(
                _digest(item, "normalized_source_sha256s[]")
                for item in data["normalized_source_sha256s"]  # type: ignore[arg-type]
            ),
            source_refs=tuple(
                _nonempty(item, "source_refs[]")
                for item in data["source_refs"]  # type: ignore[arg-type]
            ),
            strata_counts=_mapping(data["strata_counts"], "strata_counts"),
            case_count=data["case_count"],  # type: ignore[arg-type]
            fixture_sha256=_digest(data["fixture_sha256"], "fixture_sha256"),
            fixture_cid=_cid(data["fixture_cid"], "fixture_cid", codecs=("raw",)),
            sample_size_justification=SampleSizeJustification.from_dict(
                data["sample_size_justification"]
            ),
            manifest_cid=_cid(
                data["manifest_cid"], "manifest_cid", codecs=("dag-json",)
            ),
        )


def build_population_manifest(
    views: Sequence[PopulationCaseView],
    *,
    population_kind: str,
    fixture_path: str | Path,
    fixture_bytes: bytes,
    notes: str,
) -> SemanticRoundtripPopulationManifest:
    """Build a validated population manifest from ordered case views."""

    if population_kind not in {
        POPULATION_KIND_PILOT,
        POPULATION_KIND_REPAIR_DEVELOPMENT,
    }:
        raise HoldoutProtocolError(
            "build_population_manifest is not for blind holdout"
        )
    ordered = tuple(views)
    if not ordered:
        raise HoldoutProtocolError("population requires at least one case")
    if any(view.population_kind != population_kind for view in ordered):
        raise HoldoutProtocolError("case views must match population_kind")
    case_ids = tuple(view.case_id for view in ordered)
    if len(set(case_ids)) != len(case_ids):
        raise HoldoutProtocolError("duplicate case ids in population")
    strata: dict[str, int] = {}
    for view in ordered:
        strata[view.stratum] = strata.get(view.stratum, 0) + 1
    justification = SampleSizeJustification.build(
        actual_case_count=len(ordered),
        strata_counts=strata,
        notes=notes,
    )
    path_text = Path(fixture_path).as_posix()
    identity = {
        "interface": SEMANTIC_ROUNDTRIP_POPULATION_MANIFEST_INTERFACE,
        "schema": POPULATION_MANIFEST_SCHEMA,
        "population_kind": population_kind,
        "fixture_path": path_text,
        "case_ids": list(case_ids),
        "case_content_cids": [view.case_content_cid for view in ordered],
        "source_sha256s": [view.source_sha256 for view in ordered],
        "normalized_source_sha256s": [
            view.normalized_source_sha256 for view in ordered
        ],
        "source_refs": [view.source_ref for view in ordered],
        "strata_counts": dict(sorted(strata.items())),
        "case_count": len(ordered),
        "fixture_sha256": sha256_hex(fixture_bytes),
        "fixture_cid": cid_for_bytes(fixture_bytes),
        "sample_size_justification": justification.to_dict(),
    }
    return SemanticRoundtripPopulationManifest(
        interface=SEMANTIC_ROUNDTRIP_POPULATION_MANIFEST_INTERFACE,
        schema=POPULATION_MANIFEST_SCHEMA,
        population_kind=population_kind,
        fixture_path=path_text,
        case_ids=case_ids,
        case_content_cids=tuple(view.case_content_cid for view in ordered),
        source_sha256s=tuple(view.source_sha256 for view in ordered),
        normalized_source_sha256s=tuple(
            view.normalized_source_sha256 for view in ordered
        ),
        source_refs=tuple(view.source_ref for view in ordered),
        strata_counts=strata,
        case_count=len(ordered),
        fixture_sha256=identity["fixture_sha256"],  # type: ignore[arg-type]
        fixture_cid=identity["fixture_cid"],  # type: ignore[arg-type]
        sample_size_justification=justification,
        manifest_cid=cid_for_dag_json(identity),
    )


def load_pilot_manifest(
    *,
    repository_root: str | Path | None = None,
) -> SemanticRoundtripPopulationManifest:
    root = Path(repository_root) if repository_root is not None else REPOSITORY_ROOT
    path = root / PILOT_CASES_RELATIVE_PATH
    views = load_population_case_views(
        path, population_kind=POPULATION_KIND_PILOT
    )
    if set(view.case_id for view in views) != set(PILOT_CASE_IDS) or len(
        views
    ) != len(PILOT_CASE_IDS):
        raise HoldoutProtocolError(
            "pilot fixture must contain exactly the sealed pilot case ids"
        )
    # Reorder to frozen pilot order for stable manifests.
    by_id = {view.case_id: view for view in views}
    ordered = tuple(by_id[case_id] for case_id in PILOT_CASE_IDS)
    return build_population_manifest(
        ordered,
        population_kind=POPULATION_KIND_PILOT,
        fixture_path=PILOT_CASES_RELATIVE_PATH.as_posix(),
        fixture_bytes=path.read_bytes(),
        notes=(
            "Sealed pilot regression controls; sample size is historical and "
            "not used alone for promotion. Pilot non-regression remains a gate."
        ),
    )


def load_repair_development_manifest(
    *,
    repository_root: str | Path | None = None,
) -> SemanticRoundtripPopulationManifest:
    root = Path(repository_root) if repository_root is not None else REPOSITORY_ROOT
    path = root / REPAIR_DEV_CASES_RELATIVE_PATH
    views = load_population_case_views(
        path, population_kind=POPULATION_KIND_REPAIR_DEVELOPMENT
    )
    return build_population_manifest(
        views,
        population_kind=POPULATION_KIND_REPAIR_DEVELOPMENT,
        fixture_path=REPAIR_DEV_CASES_RELATIVE_PATH.as_posix(),
        fixture_bytes=path.read_bytes(),
        notes=(
            "Visible repair-development population for residual diagnosis, "
            "packets, and deterministic edit waves. Source/gold are exposed "
            "intentionally. Underpowered for promotion on its own; promotion "
            "requires the authorized blind holdout decision after PLAT2-055."
        ),
    )


# ---------------------------------------------------------------------------
# Private blind records and public seal
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PrivateBlindCaseRecord:
    """Custodian-only blind case. Never serialize into agent worktrees."""

    case_id: str
    source_text: str
    gold_ir: Mapping[str, object]
    source_ref: str
    stratum: str
    provenance: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _safe_id(self.case_id, "case_id"))
        if not isinstance(self.source_text, str) or not self.source_text.strip():
            raise HoldoutProtocolError("blind source_text must be nonempty")
        gold = _mapping(self.gold_ir, "gold_ir")
        rules = gold.get("rules")
        if not isinstance(rules, list) or not rules:
            raise HoldoutProtocolError("blind gold_ir.rules must be nonempty")
        object.__setattr__(self, "gold_ir", MappingProxyType(dict(gold)))
        object.__setattr__(
            self, "source_ref", _nonempty(self.source_ref, "source_ref")
        )
        object.__setattr__(self, "stratum", _safe_id(self.stratum, "stratum"))
        provenance = _mapping(self.provenance, "provenance")
        if provenance.get("prompt_exposure") != "none":
            raise HoldoutProtocolError(
                "blind provenance.prompt_exposure must be 'none'"
            )
        object.__setattr__(
            self, "provenance", MappingProxyType(dict(provenance))
        )

    def as_view(self) -> PopulationCaseView:
        return PopulationCaseView(
            case_id=self.case_id,
            population_kind=POPULATION_KIND_BLIND_HOLDOUT,
            source_text=self.source_text,
            source_ref=self.source_ref,
            stratum=self.stratum,
            gold_ir=dict(self.gold_ir),
            prompt_exposure="none",
        )

    def ordered_source_entry(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "source_sha256": sha256_hex(self.source_text),
            "normalized_source_sha256": normalized_source_sha256(self.source_text),
        }

    def ordered_gold_entry(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "gold_ir_cid": cid_for_dag_json(dict(self.gold_ir)),
        }

    def ordered_provenance_entry(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "source_ref": self.source_ref,
            "stratum": self.stratum,
            "provenance": dict(self.provenance),
        }


def build_private_ordered_manifests(
    records: Sequence[PrivateBlindCaseRecord],
) -> dict[str, object]:
    """Build ordered private source/gold/provenance manifests (custodian only)."""

    ordered = tuple(records)
    if not ordered:
        raise HoldoutProtocolError("blind population requires cases")
    case_ids = tuple(item.case_id for item in ordered)
    if len(set(case_ids)) != len(case_ids):
        raise HoldoutProtocolError("blind case ids must be unique")
    source_manifest = {
        "kind": "ordered_source_manifest",
        "case_ids": list(case_ids),
        "entries": [item.ordered_source_entry() for item in ordered],
    }
    gold_manifest = {
        "kind": "ordered_gold_manifest",
        "case_ids": list(case_ids),
        "entries": [item.ordered_gold_entry() for item in ordered],
    }
    provenance_manifest = {
        "kind": "ordered_provenance_manifest",
        "case_ids": list(case_ids),
        "entries": [item.ordered_provenance_entry() for item in ordered],
    }
    return {
        "case_ids": case_ids,
        "source_manifest": source_manifest,
        "gold_manifest": gold_manifest,
        "provenance_manifest": provenance_manifest,
        "ordered_source_manifest_cid": cid_for_dag_json(source_manifest),
        "ordered_gold_manifest_cid": cid_for_dag_json(gold_manifest),
        "ordered_provenance_manifest_cid": cid_for_dag_json(provenance_manifest),
        "private_bundle_cid": cid_for_dag_json(
            {
                "source": source_manifest,
                "gold": gold_manifest,
                "provenance": provenance_manifest,
            }
        ),
    }


@dataclass(frozen=True, slots=True)
class BlindHoldoutSeal:
    """Public metadata for the access-controlled blind holdout.

    Interface: ``SemanticRoundtripHoldoutSeal@1``.

    Intentionally omits case identifiers, per-case digests, source text,
    labels, gold IR, and semantic hints. Only aggregate commitments to the
    ordered private manifests are visible before PLAT2-055 authorization.
    """

    interface: str
    schema: str
    case_count: int
    strata_counts: Mapping[str, int]
    aggregate_commitments: Mapping[str, str]
    sample_size_justification: SampleSizeJustification
    leakage_policy_cid: str
    access_ledger_authority_cid: str
    sealed_private_bundle_cid: str
    normalization_version: str
    near_duplicate_jaccard_threshold: float
    seal_cid: str

    def __post_init__(self) -> None:
        if self.interface != SEMANTIC_ROUNDTRIP_HOLDOUT_SEAL_INTERFACE:
            raise HoldoutProtocolError("unsupported blind holdout seal interface")
        if self.schema != BLIND_HOLDOUT_SEAL_SCHEMA:
            raise HoldoutProtocolError("unsupported blind holdout seal schema")
        case_count = _positive_int(self.case_count, "case_count")
        object.__setattr__(self, "case_count", case_count)
        strata = _count_mapping(dict(self.strata_counts), "strata_counts")
        if sum(strata.values()) != case_count:
            raise HoldoutProtocolError("strata_counts must sum to case_count")
        object.__setattr__(self, "strata_counts", MappingProxyType(strata))
        commitments = _mapping(
            self.aggregate_commitments, "aggregate_commitments"
        )
        required_commitment_keys = {
            "ordered_source_manifest_cid",
            "ordered_gold_manifest_cid",
            "ordered_provenance_manifest_cid",
        }
        if set(commitments) != required_commitment_keys:
            raise HoldoutProtocolError(
                "aggregate_commitments must exactly bind ordered "
                "source/gold/provenance manifest CIDs"
            )
        normalized_commitments = {
            key: _cid(
                commitments[key],
                f"aggregate_commitments.{key}",
                codecs=("dag-json",),
            )
            for key in sorted(commitments)
        }
        # Reject accidental per-case leakage inside commitment values by
        # requiring distinct aggregate CIDs.
        if len(set(normalized_commitments.values())) != len(
            normalized_commitments
        ):
            raise HoldoutProtocolError(
                "aggregate commitment CIDs must be distinct"
            )
        object.__setattr__(
            self,
            "aggregate_commitments",
            MappingProxyType(normalized_commitments),
        )
        if not isinstance(
            self.sample_size_justification, SampleSizeJustification
        ):
            raise HoldoutProtocolError(
                "sample_size_justification must be SampleSizeJustification"
            )
        if self.sample_size_justification.actual_case_count != case_count:
            raise HoldoutProtocolError(
                "sample_size_justification.actual_case_count must match case_count"
            )
        if dict(self.sample_size_justification.strata_counts) != dict(strata):
            raise HoldoutProtocolError(
                "sample_size_justification.strata_counts must match seal strata"
            )
        object.__setattr__(
            self,
            "leakage_policy_cid",
            _cid(
                self.leakage_policy_cid,
                "leakage_policy_cid",
                codecs=("dag-json",),
            ),
        )
        if self.leakage_policy_cid != leakage_policy_cid():
            raise HoldoutProtocolError(
                "leakage_policy_cid does not match frozen leakage policy"
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
            "sealed_private_bundle_cid",
            _cid(
                self.sealed_private_bundle_cid,
                "sealed_private_bundle_cid",
                codecs=("dag-json",),
            ),
        )
        if self.normalization_version != SOURCE_NORMALIZATION_VERSION:
            raise HoldoutProtocolError("unsupported normalization_version")
        threshold = _finite_float(
            self.near_duplicate_jaccard_threshold,
            "near_duplicate_jaccard_threshold",
        )
        if threshold != NEAR_DUPLICATE_JACCARD_THRESHOLD:
            raise HoldoutProtocolError(
                "near_duplicate_jaccard_threshold must match frozen policy"
            )
        object.__setattr__(self, "near_duplicate_jaccard_threshold", threshold)
        expected = cid_for_dag_json(self.identity_payload())
        if (
            _cid(self.seal_cid, "seal_cid", codecs=("dag-json",)) != expected
        ):
            raise HoldoutProtocolError(
                "seal_cid does not match public blind holdout seal metadata"
            )
        self._assert_no_forbidden_public_fields(self.to_dict())

    @staticmethod
    def _assert_no_forbidden_public_fields(payload: Mapping[str, object]) -> None:
        stack: list[object] = [payload]
        while stack:
            current = stack.pop()
            if isinstance(current, Mapping):
                for key, value in current.items():
                    if key in _FORBIDDEN_PUBLIC_SEAL_KEYS:
                        raise HoldoutProtocolError(
                            f"public blind seal must not expose {key!r}"
                        )
                    stack.append(value)
            elif isinstance(current, list):
                stack.extend(current)

    def identity_payload(self) -> dict[str, object]:
        return {
            "interface": self.interface,
            "schema": self.schema,
            "case_count": self.case_count,
            "strata_counts": dict(self.strata_counts),
            "aggregate_commitments": dict(self.aggregate_commitments),
            "sample_size_justification": self.sample_size_justification.to_dict(),
            "leakage_policy_cid": self.leakage_policy_cid,
            "access_ledger_authority_cid": self.access_ledger_authority_cid,
            "sealed_private_bundle_cid": self.sealed_private_bundle_cid,
            "normalization_version": self.normalization_version,
            "near_duplicate_jaccard_threshold": (
                self.near_duplicate_jaccard_threshold
            ),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "seal_cid": self.seal_cid}

    @classmethod
    def from_dict(cls, value: object) -> "BlindHoldoutSeal":
        data = _mapping(value, "blind_holdout_seal")
        cls._assert_no_forbidden_public_fields(data)
        _exact_keys(data, set(cls.__dataclass_fields__), "blind_holdout_seal")
        return cls(
            interface=_nonempty(data["interface"], "interface"),
            schema=_nonempty(data["schema"], "schema"),
            case_count=data["case_count"],  # type: ignore[arg-type]
            strata_counts=_mapping(data["strata_counts"], "strata_counts"),
            aggregate_commitments=_mapping(
                data["aggregate_commitments"], "aggregate_commitments"
            ),
            sample_size_justification=SampleSizeJustification.from_dict(
                data["sample_size_justification"]
            ),
            leakage_policy_cid=_nonempty(
                data["leakage_policy_cid"], "leakage_policy_cid"
            ),
            access_ledger_authority_cid=_nonempty(
                data["access_ledger_authority_cid"],
                "access_ledger_authority_cid",
            ),
            sealed_private_bundle_cid=_nonempty(
                data["sealed_private_bundle_cid"],
                "sealed_private_bundle_cid",
            ),
            normalization_version=_nonempty(
                data["normalization_version"], "normalization_version"
            ),
            near_duplicate_jaccard_threshold=data[  # type: ignore[arg-type]
                "near_duplicate_jaccard_threshold"
            ],
            seal_cid=_nonempty(data["seal_cid"], "seal_cid"),
        )


def access_ledger_authority_cid(
    *,
    sealed_private_bundle_cid: str,
    ledger_logical_id: str = "plateau2-blind-holdout-access-ledger",
) -> str:
    """Return the CID binding a seal to its append-only access ledger identity."""

    return cid_for_dag_json(
        {
            "kind": "holdout_access_ledger_authority",
            "sealed_private_bundle_cid": _cid(
                sealed_private_bundle_cid,
                "sealed_private_bundle_cid",
                codecs=("dag-json",),
            ),
            "ledger_logical_id": _safe_id(ledger_logical_id, "ledger_logical_id"),
            "authorization_goal_id": AUTHORIZATION_GOAL_ID,
            "single_use": True,
            "tuning_after_access_forbidden": True,
        }
    )


def build_blind_holdout_seal(
    records: Sequence[PrivateBlindCaseRecord],
    *,
    ledger_logical_id: str = "plateau2-blind-holdout-access-ledger",
    notes: str | None = None,
) -> BlindHoldoutSeal:
    """Construct a public seal from custodian-private records.

    The returned seal never embeds per-case digests or source/gold bodies.
    Callers must keep ``records`` outside agent worktrees.
    """

    ordered = tuple(records)
    manifests = build_private_ordered_manifests(ordered)
    strata: dict[str, int] = {}
    for record in ordered:
        strata[record.stratum] = strata.get(record.stratum, 0) + 1
    justification = SampleSizeJustification.build(
        actual_case_count=len(ordered),
        strata_counts=strata,
        notes=notes
        or (
            "Preregistered paired case-cluster bootstrap precision target for "
            "blind end-to-end delta. Underpowered seals are exploratory and "
            "cannot authorize promotion."
        ),
    )
    private_bundle_cid = manifests["private_bundle_cid"]
    assert isinstance(private_bundle_cid, str)
    authority = access_ledger_authority_cid(
        sealed_private_bundle_cid=private_bundle_cid,
        ledger_logical_id=ledger_logical_id,
    )
    identity = {
        "interface": SEMANTIC_ROUNDTRIP_HOLDOUT_SEAL_INTERFACE,
        "schema": BLIND_HOLDOUT_SEAL_SCHEMA,
        "case_count": len(ordered),
        "strata_counts": dict(sorted(strata.items())),
        "aggregate_commitments": {
            "ordered_source_manifest_cid": manifests[
                "ordered_source_manifest_cid"
            ],
            "ordered_gold_manifest_cid": manifests["ordered_gold_manifest_cid"],
            "ordered_provenance_manifest_cid": manifests[
                "ordered_provenance_manifest_cid"
            ],
        },
        "sample_size_justification": justification.to_dict(),
        "leakage_policy_cid": leakage_policy_cid(),
        "access_ledger_authority_cid": authority,
        "sealed_private_bundle_cid": private_bundle_cid,
        "normalization_version": SOURCE_NORMALIZATION_VERSION,
        "near_duplicate_jaccard_threshold": NEAR_DUPLICATE_JACCARD_THRESHOLD,
    }
    return BlindHoldoutSeal(
        interface=SEMANTIC_ROUNDTRIP_HOLDOUT_SEAL_INTERFACE,
        schema=BLIND_HOLDOUT_SEAL_SCHEMA,
        case_count=len(ordered),
        strata_counts=strata,
        aggregate_commitments=identity["aggregate_commitments"],  # type: ignore[arg-type]
        sample_size_justification=justification,
        leakage_policy_cid=leakage_policy_cid(),
        access_ledger_authority_cid=authority,
        sealed_private_bundle_cid=private_bundle_cid,
        normalization_version=SOURCE_NORMALIZATION_VERSION,
        near_duplicate_jaccard_threshold=NEAR_DUPLICATE_JACCARD_THRESHOLD,
        seal_cid=cid_for_dag_json(identity),
    )


def load_frozen_blind_holdout_seal(
    *,
    repository_root: str | Path | None = None,
) -> BlindHoldoutSeal:
    """Load and validate the checked-in public blind seal."""

    root = Path(repository_root) if repository_root is not None else REPOSITORY_ROOT
    path = root / BLIND_SEAL_RELATIVE_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HoldoutProtocolError(
            f"cannot load frozen blind holdout seal: {exc}"
        ) from exc
    seal = BlindHoldoutSeal.from_dict(payload)
    if seal.case_count != FROZEN_BLIND_CASE_COUNT:
        raise HoldoutProtocolError(
            "frozen blind seal case_count drifted from preregistered value"
        )
    if dict(seal.strata_counts) != dict(FROZEN_BLIND_STRATA_COUNTS):
        raise HoldoutProtocolError(
            "frozen blind seal strata_counts drifted from preregistered value"
        )
    return seal


# ---------------------------------------------------------------------------
# Cross-split leakage and prompt isolation
# ---------------------------------------------------------------------------


def validate_cross_split_leakage(
    populations: Mapping[str, Sequence[PopulationCaseView]],
) -> None:
    """Fail closed on exact, normalized, provenance, or near-duplicate leakage."""

    kinds = set(populations)
    if not kinds:
        raise HoldoutProtocolError("leakage check requires populations")
    unknown = kinds - set(POPULATION_KINDS)
    if unknown:
        raise HoldoutProtocolError(f"unknown population kinds: {sorted(unknown)}")

    all_views: list[PopulationCaseView] = []
    for kind, views in populations.items():
        for view in views:
            if view.population_kind != kind:
                raise HoldoutProtocolError(
                    f"view {view.case_id} population_kind mismatch"
                )
            all_views.append(view)

    case_ids = [view.case_id for view in all_views]
    if len(set(case_ids)) != len(case_ids):
        raise HoldoutProtocolError("case ids overlap across populations")

    for left_index, left in enumerate(all_views):
        for right in all_views[left_index + 1 :]:
            if left.population_kind == right.population_kind:
                continue
            pair = (
                f"{left.case_id} ({left.population_kind}) and "
                f"{right.case_id} ({right.population_kind})"
            )
            if left.source_sha256 == right.source_sha256:
                raise HoldoutProtocolError(
                    f"exact source duplicate across splits: {pair}"
                )
            if left.normalized_source_sha256 == right.normalized_source_sha256:
                raise HoldoutProtocolError(
                    f"normalized source duplicate across splits: {pair}"
                )
            if left.source_ref == right.source_ref:
                raise HoldoutProtocolError(
                    f"source provenance reused across splits: {pair}"
                )
            similarity = source_similarity(left.source_text, right.source_text)
            if similarity >= NEAR_DUPLICATE_JACCARD_THRESHOLD:
                raise HoldoutProtocolError(
                    "near-duplicate source across splits: "
                    f"{pair} (similarity={similarity:.6f}, "
                    f"threshold={NEAR_DUPLICATE_JACCARD_THRESHOLD:.6f})"
                )


def validate_prompt_example_isolation(
    blind_views: Sequence[PopulationCaseView],
    prompt_examples: Mapping[str, str],
) -> tuple[str, ...]:
    """Reject prompt-example overlap with blind sources; return example digests."""

    examples = _mapping(prompt_examples, "prompt_examples")
    digests: list[str] = []
    for example_id in sorted(examples):
        _safe_id(example_id, "prompt_examples key")
        prompt = _nonempty(examples[example_id], f"prompt_examples.{example_id}")
        for view in blind_views:
            if view.population_kind != POPULATION_KIND_BLIND_HOLDOUT:
                raise HoldoutProtocolError(
                    "prompt isolation requires blind holdout views"
                )
            if example_id == view.case_id:
                raise HoldoutProtocolError(
                    f"blind case id exposed as prompt example: {view.case_id}"
                )
            if normalized_source_sha256(prompt) == view.normalized_source_sha256:
                raise HoldoutProtocolError(
                    f"blind source exposed as prompt example: {view.case_id}"
                )
            similarity = source_similarity(prompt, view.source_text)
            if similarity >= NEAR_DUPLICATE_JACCARD_THRESHOLD:
                raise HoldoutProtocolError(
                    f"blind near-copy exposed as prompt example: {view.case_id}"
                )
        digests.append(
            sha256_json(
                {
                    "example_id": example_id,
                    "normalized_source": normalize_source_text(prompt),
                }
            )
        )
    return tuple(digests)


def validate_custodian_store_path(
    private_store_path: str | Path,
    *,
    worktree_path: str | Path,
) -> Path:
    """Validate that a private store path lies outside the agent worktree."""

    store = Path(private_store_path)
    worktree = Path(worktree_path)
    if not store.is_absolute() or not worktree.is_absolute():
        raise HoldoutProtocolError(
            "custodian store and worktree paths must be absolute"
        )
    if store.is_symlink():
        raise HoldoutProtocolError("custodian store path must not be a symlink")
    try:
        store.relative_to(worktree)
    except ValueError:
        pass
    else:
        raise HoldoutProtocolError(
            "custodian store must not be addressable inside the agent worktree"
        )
    try:
        resolved_store = store.resolve(strict=False)
        resolved_worktree = worktree.resolve(strict=True)
    except OSError as exc:
        raise HoldoutProtocolError(
            "custodian store path boundary cannot be resolved"
        ) from exc
    try:
        resolved_store.relative_to(resolved_worktree)
    except ValueError:
        return resolved_store
    raise HoldoutProtocolError(
        "custodian store must remain outside the agent worktree"
    )


# ---------------------------------------------------------------------------
# Append-only access ledger (HoldoutAccessAudit@1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HoldoutAccessReceipt:
    """One append-only access ledger event for the blind holdout.

    Interface family: ``HoldoutAccessAudit@1``.
    """

    interface: str
    schema: str
    sequence: int
    event: str
    seal_cid: str
    sealed_private_bundle_cid: str
    authorization_goal_id: str | None
    authorization_cid: str | None
    purpose: str
    executor_id: str
    tuning_permitted: bool
    previous_receipt_cid: str | None
    receipt_cid: str

    def __post_init__(self) -> None:
        if self.interface != HOLDOUT_ACCESS_AUDIT_INTERFACE:
            raise HoldoutProtocolError("unsupported holdout access interface")
        if self.schema != ACCESS_RECEIPT_SCHEMA:
            raise HoldoutProtocolError("unsupported access receipt schema")
        sequence = _positive_int(self.sequence, "sequence", allow_zero=True)
        object.__setattr__(self, "sequence", sequence)
        if self.event not in _ACCESS_EVENTS:
            raise HoldoutProtocolError(f"unsupported access event: {self.event!r}")
        object.__setattr__(
            self,
            "seal_cid",
            _cid(self.seal_cid, "seal_cid", codecs=("dag-json",)),
        )
        object.__setattr__(
            self,
            "sealed_private_bundle_cid",
            _cid(
                self.sealed_private_bundle_cid,
                "sealed_private_bundle_cid",
                codecs=("dag-json",),
            ),
        )
        if self.authorization_goal_id is not None:
            object.__setattr__(
                self,
                "authorization_goal_id",
                _safe_id(self.authorization_goal_id, "authorization_goal_id"),
            )
        if self.authorization_cid is not None:
            object.__setattr__(
                self,
                "authorization_cid",
                _cid(
                    self.authorization_cid,
                    "authorization_cid",
                    codecs=("dag-json",),
                ),
            )
        if self.purpose not in {"evaluation", "replay", "rejected"}:
            raise HoldoutProtocolError(
                "access purpose must be evaluation, replay, or rejected"
            )
        object.__setattr__(
            self, "executor_id", _safe_id(self.executor_id, "executor_id")
        )
        if self.tuning_permitted is not False:
            raise HoldoutProtocolError("tuning_permitted must be false")
        if self.previous_receipt_cid is not None:
            object.__setattr__(
                self,
                "previous_receipt_cid",
                _cid(
                    self.previous_receipt_cid,
                    "previous_receipt_cid",
                    codecs=("dag-json",),
                ),
            )
        expected = cid_for_dag_json(self.identity_payload())
        if (
            _cid(self.receipt_cid, "receipt_cid", codecs=("dag-json",))
            != expected
        ):
            raise HoldoutProtocolError(
                "receipt_cid does not match access receipt content"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "interface": self.interface,
            "schema": self.schema,
            "sequence": self.sequence,
            "event": self.event,
            "seal_cid": self.seal_cid,
            "sealed_private_bundle_cid": self.sealed_private_bundle_cid,
            "authorization_goal_id": self.authorization_goal_id,
            "authorization_cid": self.authorization_cid,
            "purpose": self.purpose,
            "executor_id": self.executor_id,
            "tuning_permitted": self.tuning_permitted,
            "previous_receipt_cid": self.previous_receipt_cid,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_cid": self.receipt_cid}

    @classmethod
    def from_dict(cls, value: object) -> "HoldoutAccessReceipt":
        data = _mapping(value, "holdout_access_receipt")
        _exact_keys(data, set(cls.__dataclass_fields__), "holdout_access_receipt")
        return cls(
            interface=_nonempty(data["interface"], "interface"),
            schema=_nonempty(data["schema"], "schema"),
            sequence=data["sequence"],  # type: ignore[arg-type]
            event=_nonempty(data["event"], "event"),
            seal_cid=_nonempty(data["seal_cid"], "seal_cid"),
            sealed_private_bundle_cid=_nonempty(
                data["sealed_private_bundle_cid"],
                "sealed_private_bundle_cid",
            ),
            authorization_goal_id=data["authorization_goal_id"],  # type: ignore[arg-type]
            authorization_cid=data["authorization_cid"],  # type: ignore[arg-type]
            purpose=_nonempty(data["purpose"], "purpose"),
            executor_id=_nonempty(data["executor_id"], "executor_id"),
            tuning_permitted=data["tuning_permitted"],  # type: ignore[arg-type]
            previous_receipt_cid=data["previous_receipt_cid"],  # type: ignore[arg-type]
            receipt_cid=_nonempty(data["receipt_cid"], "receipt_cid"),
        )

    @classmethod
    def build(
        cls,
        *,
        sequence: int,
        event: str,
        seal: BlindHoldoutSeal,
        authorization_goal_id: str | None,
        authorization_cid: str | None,
        purpose: str,
        executor_id: str,
        previous_receipt_cid: str | None,
    ) -> "HoldoutAccessReceipt":
        identity = {
            "interface": HOLDOUT_ACCESS_AUDIT_INTERFACE,
            "schema": ACCESS_RECEIPT_SCHEMA,
            "sequence": sequence,
            "event": event,
            "seal_cid": seal.seal_cid,
            "sealed_private_bundle_cid": seal.sealed_private_bundle_cid,
            "authorization_goal_id": authorization_goal_id,
            "authorization_cid": authorization_cid,
            "purpose": purpose,
            "executor_id": executor_id,
            "tuning_permitted": False,
            "previous_receipt_cid": previous_receipt_cid,
        }
        return cls(
            interface=HOLDOUT_ACCESS_AUDIT_INTERFACE,
            schema=ACCESS_RECEIPT_SCHEMA,
            sequence=sequence,
            event=event,
            seal_cid=seal.seal_cid,
            sealed_private_bundle_cid=seal.sealed_private_bundle_cid,
            authorization_goal_id=authorization_goal_id,
            authorization_cid=authorization_cid,
            purpose=purpose,
            executor_id=executor_id,
            tuning_permitted=False,
            previous_receipt_cid=previous_receipt_cid,
            receipt_cid=cid_for_dag_json(identity),
        )


@dataclass(frozen=True, slots=True)
class HoldoutAccessAuthorization:
    """PLAT2-055 authorization binding required before blind access."""

    goal_id: str
    authorization_cid: str
    seal_cid: str
    candidate_freeze_cid: str
    complete: bool
    holdout_authorized: bool
    outcomes_inspected: bool
    tuning_permitted: bool

    def __post_init__(self) -> None:
        if self.goal_id != AUTHORIZATION_GOAL_ID:
            raise HoldoutProtocolError(
                f"authorization goal_id must be {AUTHORIZATION_GOAL_ID}"
            )
        object.__setattr__(
            self,
            "authorization_cid",
            _cid(
                self.authorization_cid,
                "authorization_cid",
                codecs=("dag-json",),
            ),
        )
        object.__setattr__(
            self, "seal_cid", _cid(self.seal_cid, "seal_cid", codecs=("dag-json",))
        )
        object.__setattr__(
            self,
            "candidate_freeze_cid",
            _cid(
                self.candidate_freeze_cid,
                "candidate_freeze_cid",
                codecs=("dag-json",),
            ),
        )
        if self.complete is not True:
            raise HoldoutProtocolError("authorization must be complete")
        if self.holdout_authorized is not True:
            raise HoldoutProtocolError("authorization must set holdout_authorized")
        if self.outcomes_inspected is not False:
            raise HoldoutProtocolError(
                "authorization must not follow outcome inspection"
            )
        if self.tuning_permitted is not False:
            raise HoldoutProtocolError("authorization forbids tuning")
        expected = cid_for_dag_json(self.identity_payload())
        if self.authorization_cid != expected:
            raise HoldoutProtocolError(
                "authorization_cid does not match authorization content"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "seal_cid": self.seal_cid,
            "candidate_freeze_cid": self.candidate_freeze_cid,
            "complete": self.complete,
            "holdout_authorized": self.holdout_authorized,
            "outcomes_inspected": self.outcomes_inspected,
            "tuning_permitted": self.tuning_permitted,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "authorization_cid": self.authorization_cid,
        }

    @classmethod
    def build(
        cls,
        *,
        seal: BlindHoldoutSeal,
        candidate_freeze_cid: str,
    ) -> "HoldoutAccessAuthorization":
        identity = {
            "goal_id": AUTHORIZATION_GOAL_ID,
            "seal_cid": seal.seal_cid,
            "candidate_freeze_cid": _cid(
                candidate_freeze_cid,
                "candidate_freeze_cid",
                codecs=("dag-json",),
            ),
            "complete": True,
            "holdout_authorized": True,
            "outcomes_inspected": False,
            "tuning_permitted": False,
        }
        return cls(
            goal_id=AUTHORIZATION_GOAL_ID,
            authorization_cid=cid_for_dag_json(identity),
            seal_cid=seal.seal_cid,
            candidate_freeze_cid=identity["candidate_freeze_cid"],  # type: ignore[arg-type]
            complete=True,
            holdout_authorized=True,
            outcomes_inspected=False,
            tuning_permitted=False,
        )


class AppendOnlyAccessLedger:
    """Append-only JSONL ledger for blind-holdout access receipts."""

    def __init__(self, path: str | Path, *, seal: BlindHoldoutSeal) -> None:
        self.path = Path(path)
        self.seal = BlindHoldoutSeal.from_dict(seal.to_dict())
        if not self.path.is_absolute():
            raise HoldoutProtocolError("access ledger path must be absolute")

    def read_receipts(self) -> tuple[HoldoutAccessReceipt, ...]:
        if not self.path.exists():
            return ()
        if self.path.is_symlink() or not self.path.is_file():
            raise HoldoutProtocolError(
                "access ledger must be a regular non-symlink file"
            )
        raw = self.path.read_bytes()
        return _parse_access_ledger(raw, seal=self.seal)

    def has_successful_access(self) -> bool:
        return any(
            receipt.event == "manifest_released"
            for receipt in self.read_receipts()
        )

    def append(
        self,
        *,
        event: str,
        authorization: HoldoutAccessAuthorization | None,
        purpose: str,
        executor_id: str,
    ) -> HoldoutAccessReceipt:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_APPEND | os.O_CREAT | os.O_RDWR
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise HoldoutProtocolError(
                "access ledger cannot be opened append-only"
            ) from exc
        try:
            with os.fdopen(descriptor, "r+b", closefd=True) as handle:
                handle.seek(0)
                existing = _parse_access_ledger(handle.read(), seal=self.seal)
                previous_cid = (
                    existing[-1].receipt_cid if existing else None
                )
                sequence = len(existing)
                if event == "access_granted":
                    self._assert_grant_allowed(existing, authorization)
                elif event == "manifest_released":
                    self._assert_release_allowed(existing, authorization)
                elif event in {
                    "premature_access",
                    "unauthorized_access_rejected",
                    "repeated_access_rejected",
                    "post_access_tuning_rejected",
                }:
                    pass
                else:
                    raise HoldoutProtocolError(f"unsupported ledger event {event}")

                receipt = HoldoutAccessReceipt.build(
                    sequence=sequence,
                    event=event,
                    seal=self.seal,
                    authorization_goal_id=(
                        None
                        if authorization is None
                        else authorization.goal_id
                    ),
                    authorization_cid=(
                        None
                        if authorization is None
                        else authorization.authorization_cid
                    ),
                    purpose=purpose,
                    executor_id=executor_id,
                    previous_receipt_cid=previous_cid,
                )
                wrapper = {
                    "schema": ACCESS_LEDGER_SCHEMA,
                    "receipt": receipt.to_dict(),
                }
                line = canonical_json(wrapper).encode("utf-8") + b"\n"
                handle.seek(0, os.SEEK_END)
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
                return receipt
        except HoldoutProtocolError:
            raise
        except OSError as exc:
            raise HoldoutProtocolError(
                "access ledger append failed"
            ) from exc

    def _assert_grant_allowed(
        self,
        existing: tuple[HoldoutAccessReceipt, ...],
        authorization: HoldoutAccessAuthorization | None,
    ) -> None:
        if authorization is None:
            raise HoldoutProtocolError(
                "blind access requires PLAT2-055 authorization"
            )
        if authorization.seal_cid != self.seal.seal_cid:
            raise HoldoutProtocolError(
                "authorization seal_cid does not match ledger seal"
            )
        if any(item.event == "manifest_released" for item in existing):
            raise HoldoutProtocolError(
                "blind holdout access is single-use; seal already released"
            )
        if any(item.event == "access_granted" for item in existing):
            raise HoldoutProtocolError(
                "access grant already recorded; repeated access is forbidden"
            )

    def _assert_release_allowed(
        self,
        existing: tuple[HoldoutAccessReceipt, ...],
        authorization: HoldoutAccessAuthorization | None,
    ) -> None:
        if not existing or existing[-1].event != "access_granted":
            raise HoldoutProtocolError(
                "manifest release requires a preceding access grant"
            )
        if authorization is None:
            raise HoldoutProtocolError(
                "manifest release requires PLAT2-055 authorization"
            )
        grant = existing[-1]
        if grant.authorization_cid != authorization.authorization_cid:
            raise HoldoutProtocolError(
                "release authorization does not match the grant"
            )


def _parse_access_ledger(
    raw: bytes,
    *,
    seal: BlindHoldoutSeal,
) -> tuple[HoldoutAccessReceipt, ...]:
    if not raw:
        return ()
    records: list[HoldoutAccessReceipt] = []
    for line_number, line in enumerate(raw.splitlines(keepends=True), start=1):
        if not line.endswith(b"\n") or line == b"\n":
            raise HoldoutProtocolError(
                "access ledger must contain complete JSONL records"
            )
        try:
            text = line[:-1].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HoldoutProtocolError("access ledger must be UTF-8") from exc
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HoldoutProtocolError(
                f"access ledger line {line_number} is not JSON"
            ) from exc
        data = _mapping(value, f"access ledger line {line_number}")
        _exact_keys(
            data,
            {"schema", "receipt"},
            f"access ledger line {line_number}",
        )
        if data["schema"] != ACCESS_LEDGER_SCHEMA:
            raise HoldoutProtocolError("access ledger schema changed")
        receipt = HoldoutAccessReceipt.from_dict(data["receipt"])
        wrapper = {
            "schema": ACCESS_LEDGER_SCHEMA,
            "receipt": receipt.to_dict(),
        }
        if canonical_json(wrapper).encode("utf-8") != line[:-1]:
            raise HoldoutProtocolError(
                "access ledger record is not canonical JSON"
            )
        records.append(receipt)

    for sequence, receipt in enumerate(records):
        expected_previous = (
            None if sequence == 0 else records[sequence - 1].receipt_cid
        )
        if (
            receipt.sequence != sequence
            or receipt.previous_receipt_cid != expected_previous
        ):
            raise HoldoutProtocolError("access ledger chain is broken")
        if (
            receipt.seal_cid != seal.seal_cid
            or receipt.sealed_private_bundle_cid
            != seal.sealed_private_bundle_cid
        ):
            raise HoldoutProtocolError(
                "access ledger mixes distinct seals"
            )
    return tuple(records)


def request_blind_access(
    ledger: AppendOnlyAccessLedger,
    *,
    authorization: HoldoutAccessAuthorization | None,
    executor_id: str,
    purpose: str = "evaluation",
) -> HoldoutAccessReceipt:
    """Record a grant or a fail-closed rejection before PLAT2-055 / reuse."""

    if authorization is None:
        return ledger.append(
            event="unauthorized_access_rejected",
            authorization=None,
            purpose="rejected",
            executor_id=executor_id,
        )
    if authorization.goal_id != AUTHORIZATION_GOAL_ID:
        return ledger.append(
            event="unauthorized_access_rejected",
            authorization=None,
            purpose="rejected",
            executor_id=executor_id,
        )
    existing = ledger.read_receipts()
    if any(item.event == "manifest_released" for item in existing):
        return ledger.append(
            event="repeated_access_rejected",
            authorization=authorization,
            purpose="rejected",
            executor_id=executor_id,
        )
    if any(item.event == "access_granted" for item in existing):
        return ledger.append(
            event="repeated_access_rejected",
            authorization=authorization,
            purpose="rejected",
            executor_id=executor_id,
        )
    return ledger.append(
        event="access_granted",
        authorization=authorization,
        purpose=purpose,
        executor_id=executor_id,
    )


def release_blind_manifest(
    ledger: AppendOnlyAccessLedger,
    *,
    authorization: HoldoutAccessAuthorization,
    executor_id: str,
    purpose: str = "evaluation",
) -> HoldoutAccessReceipt:
    """Record the single-use private-manifest release after a valid grant."""

    return ledger.append(
        event="manifest_released",
        authorization=authorization,
        purpose=purpose,
        executor_id=executor_id,
    )


def reject_post_access_tuning(
    ledger: AppendOnlyAccessLedger,
    *,
    executor_id: str,
    attempted_change: str,
) -> HoldoutAccessReceipt:
    """Append a post-access tuning rejection after successful release."""

    _nonempty(attempted_change, "attempted_change")
    if not ledger.has_successful_access():
        raise HoldoutProtocolError(
            "post-access tuning rejection requires a prior successful access"
        )
    return ledger.append(
        event="post_access_tuning_rejected",
        authorization=None,
        purpose="rejected",
        executor_id=executor_id,
    )


def assert_promotion_sample_size_gate(seal: BlindHoldoutSeal) -> None:
    """Fail closed when the sealed population is exploratory/underpowered."""

    justification = seal.sample_size_justification
    if justification.exploratory or not justification.powered:
        raise HoldoutProtocolError(
            "underpowered/exploratory blind population cannot authorize promotion"
        )
    if not justification.promotion_eligible:
        raise HoldoutProtocolError(
            "blind population is not promotion_eligible under sample-size gate"
        )


# ---------------------------------------------------------------------------
# Frozen private blind population recipe (custodian materialization only)
# ---------------------------------------------------------------------------


def materialize_preregistered_blind_records() -> tuple[PrivateBlindCaseRecord, ...]:
    """Return the preregistered blind population for custodian sealing.

    These records are generated deterministically in memory for seal
    construction and tests. Production custody keeps equivalent bytes outside
    agent worktrees; this function must not write them into the repository.
    """

    records: list[PrivateBlindCaseRecord] = []
    # Tier-1 synthetic activation-style cases (disjoint sources from fixtures).
    tier1_specs = (
        (
            "blind_t1_retention_window",
            "The data steward shall purge staging logs within 14 days after export.",
            "O",
            "data_steward",
            "purge",
            "staging_logs",
            "within_14_days_after_export",
        ),
        (
            "blind_t1_consent_gate",
            "The processor may share analytics extracts only with prior written consent.",
            "P",
            "processor",
            "share",
            "analytics_extracts",
            "prior_written_consent",
        ),
        (
            "blind_t1_forbid_resale",
            "Vendors are forbidden to resell telemetry bundles to brokers.",
            "F",
            "vendors",
            "resell",
            "telemetry_bundles",
            "to_brokers",
        ),
        (
            "blind_t1_incident_page",
            "On-call engineers must page the duty officer within 15 minutes of severity-1 detection.",
            "O",
            "on_call_engineers",
            "page",
            "duty_officer",
            "within_15_minutes_of_severity_1_detection",
        ),
    )
    for case_id, source, modality, actor, action, obj, qualifier in tier1_specs:
        records.append(
            PrivateBlindCaseRecord(
                case_id=case_id,
                source_text=source,
                gold_ir={
                    "rules": [
                        {
                            "modality": modality,
                            "actor": actor,
                            "action": action,
                            "object": obj,
                            "conditions": [qualifier]
                            if modality == "P"
                            else [],
                            "exceptions": [],
                            "temporal": [qualifier]
                            if modality == "O" and "within" in qualifier
                            else [],
                        }
                    ]
                },
                source_ref=f"custodian://plateau2-blind-holdout/{case_id}",
                stratum="complexity_tier_1",
                provenance={
                    "prompt_exposure": "none",
                    "authoring_party": "independent_custodian",
                    "review_status": "preregistered",
                },
            )
        )

    # Tier-2 multi-rule legal-style cases with intentionally unique wording.
    tier2_specs = (
        (
            "blind_t2_export_controls",
            (
                "Export Control Memo 9: Licensed exporters must archive end-user "
                "certificates for seven years. Brokers cannot retransfer dual-use "
                "components without a fresh license. Customs officers may inspect "
                "bonded warehouses during declared audit windows."
            ),
            [
                {
                    "modality": "O",
                    "actor": "licensed_exporters",
                    "action": "archive",
                    "object": "end_user_certificates",
                    "conditions": [],
                    "exceptions": [],
                    "temporal": ["for_seven_years"],
                },
                {
                    "modality": "F",
                    "actor": "brokers",
                    "action": "retransfer",
                    "object": "dual_use_components",
                    "conditions": [],
                    "exceptions": ["fresh_license"],
                    "temporal": [],
                },
                {
                    "modality": "P",
                    "actor": "customs_officers",
                    "action": "inspect",
                    "object": "bonded_warehouses",
                    "conditions": ["during_declared_audit_windows"],
                    "exceptions": [],
                    "temporal": [],
                },
            ],
        ),
        (
            "blind_t2_clinical_trial",
            (
                "Trial sites shall report serious adverse events to the sponsor "
                "within 24 hours. Investigators must not unblind treatment arms "
                "except under medical emergency. Monitors may review source charts "
                "after site authorization."
            ),
            [
                {
                    "modality": "O",
                    "actor": "trial_sites",
                    "action": "report",
                    "object": "serious_adverse_events_to_sponsor",
                    "conditions": [],
                    "exceptions": [],
                    "temporal": ["within_24_hours"],
                },
                {
                    "modality": "F",
                    "actor": "investigators",
                    "action": "unblind",
                    "object": "treatment_arms",
                    "conditions": [],
                    "exceptions": ["medical_emergency"],
                    "temporal": [],
                },
                {
                    "modality": "P",
                    "actor": "monitors",
                    "action": "review",
                    "object": "source_charts",
                    "conditions": ["after_site_authorization"],
                    "exceptions": [],
                    "temporal": [],
                },
            ],
        ),
        (
            "blind_t2_municipal_procurement",
            (
                "City agencies must publish bid solicitations for purchases above "
                "the threshold. Award committees cannot accept late proposals. "
                "Vendors may request debriefings within ten business days."
            ),
            [
                {
                    "modality": "O",
                    "actor": "city_agencies",
                    "action": "publish",
                    "object": "bid_solicitations",
                    "conditions": ["purchases_above_threshold"],
                    "exceptions": [],
                    "temporal": [],
                },
                {
                    "modality": "F",
                    "actor": "award_committees",
                    "action": "accept",
                    "object": "late_proposals",
                    "conditions": [],
                    "exceptions": [],
                    "temporal": [],
                },
                {
                    "modality": "P",
                    "actor": "vendors",
                    "action": "request",
                    "object": "debriefings",
                    "conditions": [],
                    "exceptions": [],
                    "temporal": ["within_ten_business_days"],
                },
            ],
        ),
        (
            "blind_t2_energy_dispatch",
            (
                "Grid operators shall curtail non-firm generation during declared "
                "scarcity events. Retail suppliers must not withhold meter data "
                "from the independent system operator. Aggregators may bid demand "
                "response blocks when telemetry is certified."
            ),
            [
                {
                    "modality": "O",
                    "actor": "grid_operators",
                    "action": "curtail",
                    "object": "non_firm_generation",
                    "conditions": ["during_declared_scarcity_events"],
                    "exceptions": [],
                    "temporal": [],
                },
                {
                    "modality": "F",
                    "actor": "retail_suppliers",
                    "action": "withhold",
                    "object": "meter_data_from_independent_system_operator",
                    "conditions": [],
                    "exceptions": [],
                    "temporal": [],
                },
                {
                    "modality": "P",
                    "actor": "aggregators",
                    "action": "bid",
                    "object": "demand_response_blocks",
                    "conditions": ["telemetry_certified"],
                    "exceptions": [],
                    "temporal": [],
                },
            ],
        ),
        (
            "blind_t2_aviation_maintenance",
            (
                "Part 145 stations must log life-limited part removals before "
                "release to service. Technicians cannot approve return-to-service "
                "without dual inspection. Operators may ferry aircraft under a "
                "special flight permit."
            ),
            [
                {
                    "modality": "O",
                    "actor": "part_145_stations",
                    "action": "log",
                    "object": "life_limited_part_removals",
                    "conditions": [],
                    "exceptions": [],
                    "temporal": ["before_release_to_service"],
                },
                {
                    "modality": "F",
                    "actor": "technicians",
                    "action": "approve",
                    "object": "return_to_service",
                    "conditions": [],
                    "exceptions": ["dual_inspection"],
                    "temporal": [],
                },
                {
                    "modality": "P",
                    "actor": "operators",
                    "action": "ferry",
                    "object": "aircraft",
                    "conditions": ["special_flight_permit"],
                    "exceptions": [],
                    "temporal": [],
                },
            ],
        ),
        (
            "blind_t2_cyber_incident",
            (
                "Covered entities shall notify the sector coordinator of confirmed "
                "ransomware within 72 hours. Managed providers must not disable "
                "customer audit trails. Incident responders may isolate affected "
                "subnets when lateral movement is observed."
            ),
            [
                {
                    "modality": "O",
                    "actor": "covered_entities",
                    "action": "notify",
                    "object": "sector_coordinator_of_confirmed_ransomware",
                    "conditions": [],
                    "exceptions": [],
                    "temporal": ["within_72_hours"],
                },
                {
                    "modality": "F",
                    "actor": "managed_providers",
                    "action": "disable",
                    "object": "customer_audit_trails",
                    "conditions": [],
                    "exceptions": [],
                    "temporal": [],
                },
                {
                    "modality": "P",
                    "actor": "incident_responders",
                    "action": "isolate",
                    "object": "affected_subnets",
                    "conditions": ["lateral_movement_observed"],
                    "exceptions": [],
                    "temporal": [],
                },
            ],
        ),
        (
            "blind_t2_labor_scheduling",
            (
                "Employers must provide work schedules 14 days in advance. "
                "Supervisors cannot compel clopening without voluntary consent. "
                "Employees may decline mandatory overtime during protected leave."
            ),
            [
                {
                    "modality": "O",
                    "actor": "employers",
                    "action": "provide",
                    "object": "work_schedules",
                    "conditions": [],
                    "exceptions": [],
                    "temporal": ["14_days_in_advance"],
                },
                {
                    "modality": "F",
                    "actor": "supervisors",
                    "action": "compel",
                    "object": "clopening",
                    "conditions": [],
                    "exceptions": ["voluntary_consent"],
                    "temporal": [],
                },
                {
                    "modality": "P",
                    "actor": "employees",
                    "action": "decline",
                    "object": "mandatory_overtime",
                    "conditions": ["during_protected_leave"],
                    "exceptions": [],
                    "temporal": [],
                },
            ],
        ),
        (
            "blind_t2_water_quality",
            (
                "Utilities shall sample finished water for lead each calendar "
                "quarter. Contract labs must not alter chain-of-custody seals. "
                "Regulators may order public notice when action levels are exceeded."
            ),
            [
                {
                    "modality": "O",
                    "actor": "utilities",
                    "action": "sample",
                    "object": "finished_water_for_lead",
                    "conditions": [],
                    "exceptions": [],
                    "temporal": ["each_calendar_quarter"],
                },
                {
                    "modality": "F",
                    "actor": "contract_labs",
                    "action": "alter",
                    "object": "chain_of_custody_seals",
                    "conditions": [],
                    "exceptions": [],
                    "temporal": [],
                },
                {
                    "modality": "P",
                    "actor": "regulators",
                    "action": "order",
                    "object": "public_notice",
                    "conditions": ["action_levels_exceeded"],
                    "exceptions": [],
                    "temporal": [],
                },
            ],
        ),
    )
    for case_id, source, rules in tier2_specs:
        records.append(
            PrivateBlindCaseRecord(
                case_id=case_id,
                source_text=source,
                gold_ir={"rules": rules},
                source_ref=f"custodian://plateau2-blind-holdout/{case_id}",
                stratum="complexity_tier_2",
                provenance={
                    "prompt_exposure": "none",
                    "authoring_party": "independent_custodian",
                    "review_status": "preregistered",
                },
            )
        )

    if len(records) != FROZEN_BLIND_CASE_COUNT:
        raise HoldoutProtocolError(
            "preregistered blind record count drifted"
        )
    strata: dict[str, int] = {}
    for record in records:
        strata[record.stratum] = strata.get(record.stratum, 0) + 1
    if strata != dict(FROZEN_BLIND_STRATA_COUNTS):
        raise HoldoutProtocolError(
            "preregistered blind strata drifted"
        )
    return tuple(records)


def build_frozen_blind_holdout_seal() -> BlindHoldoutSeal:
    """Build the production public seal from preregistered private records."""

    records = materialize_preregistered_blind_records()
    return build_blind_holdout_seal(
        records,
        notes=(
            "PLAT2-020 preregistered blind holdout. Sample size follows the "
            "paired case-cluster bootstrap precision justification "
            f"(half-width={FROZEN_TARGET_CI_HALF_WIDTH}, "
            f"assumed_sd={FROZEN_ASSUMED_SD_PAIRED_DELTA}, "
            f"alpha={FROZEN_ALPHA}). Powered seals may authorize promotion only "
            "after PLAT2-055; exploratory underpowered seals cannot."
        ),
    )


def write_frozen_blind_holdout_seal(
    path: str | Path | None = None,
) -> BlindHoldoutSeal:
    """Write the public seal artifact (no private content)."""

    seal = build_frozen_blind_holdout_seal()
    target = (
        Path(path)
        if path is not None
        else REPOSITORY_ROOT / BLIND_SEAL_RELATIVE_PATH
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(seal.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return seal


def freeze_visible_populations(
    *,
    repository_root: str | Path | None = None,
) -> dict[str, SemanticRoundtripPopulationManifest]:
    """Load and return frozen pilot and repair-development manifests."""

    pilot = load_pilot_manifest(repository_root=repository_root)
    repair = load_repair_development_manifest(repository_root=repository_root)
    # Cross-check id and source disjointness between visible populations.
    validate_cross_split_leakage(
        {
            POPULATION_KIND_PILOT: load_population_case_views(
                (Path(repository_root) if repository_root else REPOSITORY_ROOT)
                / PILOT_CASES_RELATIVE_PATH,
                population_kind=POPULATION_KIND_PILOT,
            ),
            POPULATION_KIND_REPAIR_DEVELOPMENT: load_population_case_views(
                (Path(repository_root) if repository_root else REPOSITORY_ROOT)
                / REPAIR_DEV_CASES_RELATIVE_PATH,
                population_kind=POPULATION_KIND_REPAIR_DEVELOPMENT,
            ),
        }
    )
    return {
        POPULATION_KIND_PILOT: pilot,
        POPULATION_KIND_REPAIR_DEVELOPMENT: repair,
    }


def freeze_all_populations_with_private_blind(
    blind_records: Sequence[PrivateBlindCaseRecord],
    *,
    repository_root: str | Path | None = None,
    prompt_examples: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Freeze all three populations using custodian-provided blind records."""

    root = Path(repository_root) if repository_root is not None else REPOSITORY_ROOT
    visible = freeze_visible_populations(repository_root=root)
    seal = build_blind_holdout_seal(blind_records)
    pilot_views = load_population_case_views(
        root / PILOT_CASES_RELATIVE_PATH,
        population_kind=POPULATION_KIND_PILOT,
    )
    repair_views = load_population_case_views(
        root / REPAIR_DEV_CASES_RELATIVE_PATH,
        population_kind=POPULATION_KIND_REPAIR_DEVELOPMENT,
    )
    blind_views = tuple(record.as_view() for record in blind_records)
    validate_cross_split_leakage(
        {
            POPULATION_KIND_PILOT: pilot_views,
            POPULATION_KIND_REPAIR_DEVELOPMENT: repair_views,
            POPULATION_KIND_BLIND_HOLDOUT: blind_views,
        }
    )
    examples = prompt_examples if prompt_examples is not None else {}
    prompt_digests = validate_prompt_example_isolation(blind_views, examples)
    return {
        "pilot_manifest": visible[POPULATION_KIND_PILOT],
        "repair_development_manifest": visible[
            POPULATION_KIND_REPAIR_DEVELOPMENT
        ],
        "blind_holdout_seal": seal,
        "prompt_example_sha256s": prompt_digests,
    }


__all__ = [
    "ACCESS_LEDGER_SCHEMA",
    "ACCESS_RECEIPT_SCHEMA",
    "AUTHORIZATION_GOAL_ID",
    "AppendOnlyAccessLedger",
    "BLIND_HOLDOUT_SEAL_SCHEMA",
    "BLIND_SEAL_RELATIVE_PATH",
    "BlindHoldoutSeal",
    "FROZEN_ALPHA",
    "FROZEN_ASSUMED_SD_PAIRED_DELTA",
    "FROZEN_BLIND_CASE_COUNT",
    "FROZEN_BLIND_STRATA_COUNTS",
    "FROZEN_TARGET_CI_HALF_WIDTH",
    "HOLDOUT_ACCESS_AUDIT_INTERFACE",
    "HoldoutAccessAuthorization",
    "HoldoutAccessReceipt",
    "HoldoutProtocolError",
    "LEAKAGE_POLICY_SCHEMA",
    "NEAR_DUPLICATE_JACCARD_THRESHOLD",
    "PILOT_CASES_RELATIVE_PATH",
    "PLAT2_055_AUTHORIZATION_GOAL",
    "POPULATION_KIND_BLIND_HOLDOUT",
    "POPULATION_KIND_PILOT",
    "POPULATION_KIND_REPAIR_DEVELOPMENT",
    "POPULATION_KINDS",
    "POPULATION_MANIFEST_SCHEMA",
    "PopulationCaseView",
    "PrivateBlindCaseRecord",
    "REPAIR_DEV_CASES_RELATIVE_PATH",
    "REPOSITORY_ROOT",
    "SAMPLE_SIZE_JUSTIFICATION_SCHEMA",
    "SEMANTIC_ROUNDTRIP_HOLDOUT_SEAL_INTERFACE",
    "SEMANTIC_ROUNDTRIP_POPULATION_MANIFEST_INTERFACE",
    "SOURCE_NORMALIZATION_VERSION",
    "SampleSizeJustification",
    "SemanticRoundtripPopulationManifest",
    "access_ledger_authority_cid",
    "assert_promotion_sample_size_gate",
    "build_blind_holdout_seal",
    "build_frozen_blind_holdout_seal",
    "build_population_manifest",
    "build_private_ordered_manifests",
    "canonical_json",
    "freeze_all_populations_with_private_blind",
    "freeze_visible_populations",
    "leakage_policy_cid",
    "leakage_policy_payload",
    "load_frozen_blind_holdout_seal",
    "load_pilot_manifest",
    "load_population_case_views",
    "load_raw_case_dicts",
    "load_repair_development_manifest",
    "materialize_preregistered_blind_records",
    "normalize_source_text",
    "normalized_source_sha256",
    "reject_post_access_tuning",
    "release_blind_manifest",
    "request_blind_access",
    "required_case_count_for_precision",
    "sha256_hex",
    "sha256_json",
    "source_similarity",
    "validate_cross_split_leakage",
    "validate_custodian_store_path",
    "validate_prompt_example_isolation",
    "write_frozen_blind_holdout_seal",
]
