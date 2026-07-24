"""Immutable stage-aware definitions for the preregistered ablation arms.

The frozen protocol describes the scientific meaning of A0--A12 and S1.  This
module turns those descriptions into executable, dependency-free routing
metadata.  It does not import an optional backend or configure production
routing.

Stage records always use :class:`~benchmarks.logic_pipeline.contracts.StageName`
wire order.  Proof ordering is therefore a separate explicit policy consumed
by the Hammer/Leanstral orchestration handlers; this keeps A6 and A12
Leanstral-first without creating non-canonical provenance records.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from types import MappingProxyType
from typing import Final, Mapping

from .contracts import (
    DEFAULT_PROTOCOL,
    ProtocolContractError,
    StageName,
    canonical_json,
)


VARIANT_REGISTRY_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.variant-registry.v1"
)


class StagePolicy(str, Enum):
    """Bounded activation policies understood by benchmark stage handlers."""

    OFF = "off"
    ALWAYS = "always"
    AMBIGUITY_GATED = "ambiguity_gated"
    PROOF_FAILURE_FALLBACK = "proof_failure_fallback"
    LEGACY_DIAGNOSTIC = "legacy_diagnostic"


class SpacyMode(str, Enum):
    """The requested linguistic route for an ablation arm."""

    CURRENT_EFFECTIVE = "current_effective"
    FULL_MODEL = "full_model"
    REGEX_LEGAL = "regex_legal"
    BLANK_MODEL = "blank_model"


class HammerPolicy(str, Enum):
    """The requested proof-search selector."""

    OFF = "off"
    DETERMINISTIC = "deterministic"
    LEARNED_SELECTOR = "learned_selector"
    ALWAYS = "always"


class PremiseRanking(str, Enum):
    """The source used to rank proof premises."""

    DETERMINISTIC = "deterministic"
    SYMAI_LLM = "symai_llm"


@dataclass(frozen=True, slots=True)
class VariantDefinition:
    """Complete requested configuration for one preregistered arm."""

    variant_id: str
    configuration: str
    purpose: str
    stages: tuple[StageName, ...]
    spacy_mode: SpacyMode
    symai_policy: StagePolicy
    hammer_policy: HammerPolicy
    leanstral_policy: StagePolicy
    proof_order: tuple[StageName, ...]
    premise_ranking: PremiseRanking = PremiseRanking.DETERMINISTIC
    paired_against: str | None = "A0"
    primary_candidate: bool = True
    safety_diagnostic_only: bool = False

    def __post_init__(self) -> None:
        protocol_spec = DEFAULT_PROTOCOL.variant_map.get(self.variant_id)
        if protocol_spec is None:
            raise ProtocolContractError(
                f"variant is not preregistered: {self.variant_id!r}"
            )
        if self.configuration != protocol_spec.configuration:
            raise ProtocolContractError(
                f"{self.variant_id} configuration differs from frozen protocol"
            )
        if self.purpose != protocol_spec.purpose:
            raise ProtocolContractError(
                f"{self.variant_id} purpose differs from frozen protocol"
            )
        if self.paired_against != protocol_spec.paired_against:
            raise ProtocolContractError(
                f"{self.variant_id} pairing differs from frozen protocol"
            )
        if self.primary_candidate is not protocol_spec.primary_candidate:
            raise ProtocolContractError(
                f"{self.variant_id} primary-candidate flag differs from protocol"
            )
        if (
            self.safety_diagnostic_only
            is not protocol_spec.safety_diagnostic_only
        ):
            raise ProtocolContractError(
                f"{self.variant_id} safety flag differs from frozen protocol"
            )
        if not isinstance(self.stages, tuple) or not self.stages:
            raise ProtocolContractError("variant stages must be a nonempty tuple")
        if len(set(self.stages)) != len(self.stages):
            raise ProtocolContractError("variant stages must be unique")
        if any(not isinstance(stage, StageName) for stage in self.stages):
            raise ProtocolContractError("variant stages must use StageName values")
        positions = [tuple(StageName).index(stage) for stage in self.stages]
        if positions != sorted(positions):
            raise ProtocolContractError(
                "durable variant stages must follow canonical wire order"
            )
        if StageName.KERNEL in self.stages and self.stages[-1] is not StageName.KERNEL:
            raise ProtocolContractError("kernel must be the terminal stage")
        if not isinstance(self.proof_order, tuple):
            raise ProtocolContractError("proof_order must be a tuple")
        if len(set(self.proof_order)) != len(self.proof_order):
            raise ProtocolContractError("proof_order must not contain duplicates")
        if any(
            stage not in {StageName.HAMMER, StageName.LEANSTRAL}
            for stage in self.proof_order
        ):
            raise ProtocolContractError(
                "proof_order may contain only Hammer and Leanstral"
            )
        enabled_proof_stages = {
            stage
            for stage in self.stages
            if stage in {StageName.HAMMER, StageName.LEANSTRAL}
        }
        if set(self.proof_order) != enabled_proof_stages:
            raise ProtocolContractError(
                "proof_order must name every enabled proof stage exactly once"
            )
        if self.symai_policy is StagePolicy.OFF and StageName.SYMAI in self.stages:
            raise ProtocolContractError("SyMAI cannot be routed with policy off")
        if self.symai_policy is not StagePolicy.OFF and StageName.SYMAI not in self.stages:
            raise ProtocolContractError("enabled SyMAI policy requires its stage")
        if self.hammer_policy is HammerPolicy.OFF and StageName.HAMMER in self.stages:
            raise ProtocolContractError("Hammer cannot be routed with policy off")
        if self.hammer_policy is not HammerPolicy.OFF and StageName.HAMMER not in self.stages:
            raise ProtocolContractError("enabled Hammer policy requires its stage")
        if (
            self.leanstral_policy is StagePolicy.OFF
            and StageName.LEANSTRAL in self.stages
        ):
            raise ProtocolContractError("Leanstral cannot be routed with policy off")
        if (
            self.leanstral_policy is not StagePolicy.OFF
            and StageName.LEANSTRAL not in self.stages
        ):
            raise ProtocolContractError("enabled Leanstral policy requires its stage")
        if (
            self.premise_ranking is PremiseRanking.SYMAI_LLM
            and self.symai_policy is StagePolicy.OFF
        ):
            raise ProtocolContractError("SyMAI premise ranking requires SyMAI")

    @property
    def required_capabilities(self) -> tuple[str, ...]:
        """Return the exact runtime capabilities requested by this arm."""

        capabilities: list[str] = []
        if self.variant_id == "A0":
            capabilities.append("current_modal_codec")
        elif StageName.SPACY in self.stages:
            capabilities.append(
                {
                    SpacyMode.FULL_MODEL: "spacy_full_model",
                    SpacyMode.REGEX_LEGAL: "regex_legal_parser",
                    SpacyMode.BLANK_MODEL: "spacy_blank_model",
                    SpacyMode.CURRENT_EFFECTIVE: "spacy_current_effective",
                }[self.spacy_mode]
            )
        if StageName.SYMAI in self.stages:
            capabilities.append(
                "legacy_symbolicai"
                if self.symai_policy is StagePolicy.LEGACY_DIAGNOSTIC
                else "symai"
            )
        if StageName.HAMMER in self.stages:
            capabilities.append("hammer")
        if StageName.LEANSTRAL in self.stages:
            capabilities.append("leanstral")
        if StageName.KERNEL in self.stages:
            capabilities.append("native_kernel")
        return tuple(capabilities)

    def requested_identity(self, stage: StageName) -> Mapping[str, object]:
        """Return immutable stage-specific requested identity and policy."""

        if stage not in self.stages:
            raise ProtocolContractError(
                f"{stage.value} is not routed by {self.variant_id}"
            )
        common: dict[str, object] = {
            "variant_id": self.variant_id,
            "configuration_sha256": self.digest,
        }
        if stage is StageName.SPACY:
            common["mode"] = self.spacy_mode.value
        elif stage is StageName.SYMAI:
            common["policy"] = self.symai_policy.value
            common["premise_ranking"] = self.premise_ranking.value
        elif stage is StageName.HAMMER:
            common["policy"] = self.hammer_policy.value
            common["proof_order"] = tuple(
                item.value for item in self.proof_order
            )
        elif stage is StageName.LEANSTRAL:
            common["policy"] = self.leanstral_policy.value
            common["proof_order"] = tuple(
                item.value for item in self.proof_order
            )
        elif stage is StageName.KERNEL and self.safety_diagnostic_only:
            common["diagnostic_only"] = True
        return MappingProxyType(common)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": VARIANT_REGISTRY_SCHEMA,
            "variant_id": self.variant_id,
            "configuration": self.configuration,
            "purpose": self.purpose,
            "stages": [stage.value for stage in self.stages],
            "spacy_mode": self.spacy_mode.value,
            "symai_policy": self.symai_policy.value,
            "hammer_policy": self.hammer_policy.value,
            "leanstral_policy": self.leanstral_policy.value,
            "proof_order": [stage.value for stage in self.proof_order],
            "premise_ranking": self.premise_ranking.value,
            "paired_against": self.paired_against,
            "primary_candidate": self.primary_candidate,
            "safety_diagnostic_only": self.safety_diagnostic_only,
            "required_capabilities": list(self.required_capabilities),
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()


_C = StageName.COMPILER
_S = StageName.SPACY
_Y = StageName.SYMAI
_H = StageName.HAMMER
_L = StageName.LEANSTRAL
_K = StageName.KERNEL


def _definition(
    variant_id: str,
    stages: tuple[StageName, ...],
    *,
    spacy: SpacyMode = SpacyMode.FULL_MODEL,
    symai: StagePolicy = StagePolicy.OFF,
    hammer: HammerPolicy = HammerPolicy.OFF,
    leanstral: StagePolicy = StagePolicy.OFF,
    proof_order: tuple[StageName, ...] = (),
    premise_ranking: PremiseRanking = PremiseRanking.DETERMINISTIC,
) -> VariantDefinition:
    spec = DEFAULT_PROTOCOL.variant_map[variant_id]
    return VariantDefinition(
        variant_id=variant_id,
        configuration=spec.configuration,
        purpose=spec.purpose,
        stages=stages,
        spacy_mode=spacy,
        symai_policy=symai,
        hammer_policy=hammer,
        leanstral_policy=leanstral,
        proof_order=proof_order,
        premise_ranking=premise_ranking,
        paired_against=spec.paired_against,
        primary_candidate=spec.primary_candidate,
        safety_diagnostic_only=spec.safety_diagnostic_only,
    )


_DEFINITIONS = (
    _definition("A0", (_C,), spacy=SpacyMode.CURRENT_EFFECTIVE),
    _definition("A1", (_C, _S, _K)),
    _definition(
        "A2",
        (_C, _S, _H, _K),
        hammer=HammerPolicy.DETERMINISTIC,
        proof_order=(_H,),
    ),
    _definition(
        "A3",
        (_C, _S, _H, _L, _K),
        hammer=HammerPolicy.DETERMINISTIC,
        leanstral=StagePolicy.PROOF_FAILURE_FALLBACK,
        proof_order=(_H, _L),
    ),
    _definition(
        "A4",
        (_C, _S, _Y, _H, _L, _K),
        symai=StagePolicy.AMBIGUITY_GATED,
        hammer=HammerPolicy.DETERMINISTIC,
        leanstral=StagePolicy.PROOF_FAILURE_FALLBACK,
        proof_order=(_H, _L),
    ),
    _definition(
        "A5",
        (_C, _S, _Y, _H, _L, _K),
        symai=StagePolicy.ALWAYS,
        hammer=HammerPolicy.DETERMINISTIC,
        leanstral=StagePolicy.PROOF_FAILURE_FALLBACK,
        proof_order=(_H, _L),
    ),
    _definition(
        "A6",
        (_C, _S, _Y, _H, _L, _K),
        symai=StagePolicy.AMBIGUITY_GATED,
        hammer=HammerPolicy.DETERMINISTIC,
        leanstral=StagePolicy.ALWAYS,
        proof_order=(_L, _H),
    ),
    _definition(
        "A7",
        (_C, _S, _Y, _H, _L, _K),
        spacy=SpacyMode.REGEX_LEGAL,
        symai=StagePolicy.AMBIGUITY_GATED,
        hammer=HammerPolicy.DETERMINISTIC,
        leanstral=StagePolicy.PROOF_FAILURE_FALLBACK,
        proof_order=(_H, _L),
    ),
    _definition(
        "A8",
        (_C, _S, _Y, _H, _L, _K),
        spacy=SpacyMode.BLANK_MODEL,
        symai=StagePolicy.AMBIGUITY_GATED,
        hammer=HammerPolicy.DETERMINISTIC,
        leanstral=StagePolicy.PROOF_FAILURE_FALLBACK,
        proof_order=(_H, _L),
    ),
    _definition(
        "A9",
        (_C, _S, _Y, _L, _K),
        symai=StagePolicy.AMBIGUITY_GATED,
        leanstral=StagePolicy.PROOF_FAILURE_FALLBACK,
        proof_order=(_L,),
    ),
    _definition(
        "A10",
        (_C, _S, _Y, _H, _L, _K),
        symai=StagePolicy.AMBIGUITY_GATED,
        hammer=HammerPolicy.LEARNED_SELECTOR,
        leanstral=StagePolicy.PROOF_FAILURE_FALLBACK,
        proof_order=(_H, _L),
    ),
    _definition(
        "A11",
        (_C, _S, _Y, _H, _L, _K),
        symai=StagePolicy.AMBIGUITY_GATED,
        hammer=HammerPolicy.DETERMINISTIC,
        leanstral=StagePolicy.PROOF_FAILURE_FALLBACK,
        proof_order=(_H, _L),
        premise_ranking=PremiseRanking.SYMAI_LLM,
    ),
    _definition(
        "A12",
        (_C, _S, _Y, _H, _L, _K),
        symai=StagePolicy.ALWAYS,
        hammer=HammerPolicy.ALWAYS,
        leanstral=StagePolicy.ALWAYS,
        proof_order=(_L, _H),
    ),
    _definition(
        "S1",
        (_Y, _K),
        symai=StagePolicy.LEGACY_DIAGNOSTIC,
    ),
)

VARIANT_REGISTRY: Final[Mapping[str, VariantDefinition]] = MappingProxyType(
    {item.variant_id: item for item in _DEFINITIONS}
)
"""Read-only registry containing exactly A0--A12 and S1."""

VARIANTS = VARIANT_REGISTRY
"""Compatibility alias for callers that use the shorter registry name."""

ALL_VARIANT_IDS: Final = tuple(
    [*(f"A{index}" for index in range(13)), "S1"]
)

if tuple(VARIANT_REGISTRY) != ALL_VARIANT_IDS:  # pragma: no cover - import invariant
    raise RuntimeError("variant registry order/content is not A0--A12 plus S1")
if set(VARIANT_REGISTRY) != set(DEFAULT_PROTOCOL.variant_map):  # pragma: no cover
    raise RuntimeError("variant registry differs from frozen protocol")

VARIANT_REGISTRY_SHA256: Final = hashlib.sha256(
    canonical_json(
        [VARIANT_REGISTRY[item].to_dict() for item in ALL_VARIANT_IDS]
    ).encode("utf-8")
).hexdigest()


def get_variant_definition(variant_id: str) -> VariantDefinition:
    """Return a registered arm or fail without selecting a substitute."""

    try:
        return VARIANT_REGISTRY[variant_id]
    except (KeyError, TypeError) as exc:
        raise ProtocolContractError(
            f"variant is not registered: {variant_id!r}"
        ) from exc


__all__ = [
    "ALL_VARIANT_IDS",
    "HammerPolicy",
    "PremiseRanking",
    "SpacyMode",
    "StagePolicy",
    "VARIANTS",
    "VARIANT_REGISTRY",
    "VARIANT_REGISTRY_SCHEMA",
    "VARIANT_REGISTRY_SHA256",
    "VariantDefinition",
    "get_variant_definition",
]
