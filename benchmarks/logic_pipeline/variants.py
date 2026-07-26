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
    CAUSAL_PROOF_PROTOCOL_V2_CID,
    CAUSAL_PROOF_VARIANT_PROFILE_SCHEMA_V2,
    CAUSAL_PROOF_VARIANT_PROFILE_V2_CID,
    DEFAULT_PROTOCOL,
    ProtocolContractError,
    StageName,
    canonical_json,
    causal_proof_variant_profile_v2,
)
from .content_addressing import cid_for_dag_json


VARIANT_REGISTRY_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.variant-registry.v1"
)


def _freeze_profile_json(value: object) -> object:
    """Deeply detach and freeze the small causal-route JSON documents."""

    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ProtocolContractError(
                "causal profile route keys must be strings"
            )
        return MappingProxyType(
            {
                str(key): _freeze_profile_json(member)
                for key, member in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_profile_json(member) for member in value)
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise ProtocolContractError(
        "causal profile route contains a non-JSON value"
    )


def _thaw_profile_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _thaw_profile_json(member)
            for key, member in value.items()
        }
    if isinstance(value, tuple):
        return [_thaw_profile_json(member) for member in value]
    return value


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


@dataclass(frozen=True, slots=True)
class CausalProofVariantProfile:
    """Typed view of one additive G210 route.

    This profile never mutates :class:`VariantDefinition`; callers must opt in
    with the exact causal-proof protocol CID before using ``effective_stages``.
    """

    variant_id: str
    effective_stages: tuple[StageName, ...]
    optional_order: tuple[StageName, ...]
    optional_routes: tuple[Mapping[str, object], ...]
    compiler_reference_kernel_policy: str
    proof_authority: str

    def __post_init__(self) -> None:
        base = get_variant_definition(self.variant_id)
        if (
            not isinstance(self.optional_routes, tuple)
            or not all(
                isinstance(route, Mapping)
                for route in self.optional_routes
            )
        ):
            raise ProtocolContractError(
                "causal optional routes must be an immutable mapping tuple"
            )
        frozen_routes = tuple(
            _freeze_profile_json(route) for route in self.optional_routes
        )
        object.__setattr__(self, "optional_routes", frozen_routes)
        if self.variant_id == "S1":
            raise ProtocolContractError("S1 is outside the causal proof profile")
        if not self.effective_stages or self.effective_stages[-1] is not _K:
            raise ProtocolContractError(
                "causal proof routes require a terminal kernel stage"
            )
        expected_stages = (
            (*base.stages, _K) if self.variant_id == "A0" else base.stages
        )
        if self.effective_stages != expected_stages:
            raise ProtocolContractError(
                f"{self.variant_id} causal route changed a non-kernel v1 stage"
            )
        if set(self.optional_order) != {
            stage
            for stage in base.proof_order
        } or len(self.optional_order) != len(base.proof_order):
            raise ProtocolContractError(
                f"{self.variant_id} causal optional stages drifted"
            )
        if tuple(route.get("source") for route in self.optional_routes) != tuple(
            stage.value for stage in self.optional_order
        ):
            raise ProtocolContractError(
                f"{self.variant_id} causal trigger order drifted"
            )
        if (
            self.compiler_reference_kernel_policy
            != "identical_independent_check"
            or self.proof_authority != "native_kernel"
        ):
            raise ProtocolContractError(
                f"{self.variant_id} causal proof authority drifted"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": CAUSAL_PROOF_VARIANT_PROFILE_SCHEMA_V2,
            "variant_id": self.variant_id,
            "effective_stages": [
                stage.value for stage in self.effective_stages
            ],
            "compiler_reference_kernel_policy": (
                self.compiler_reference_kernel_policy
            ),
            "optional_order": [
                stage.value for stage in self.optional_order
            ],
            "optional_routes": [
                _thaw_profile_json(route)
                for route in self.optional_routes
            ],
            "symai_can_receive_proof_credit": False,
            "terminal_proof_authority": self.proof_authority,
        }

    @property
    def cid(self) -> str:
        return cid_for_dag_json(self.to_dict())


def _build_causal_proof_variant_profiles() -> Mapping[
    str, CausalProofVariantProfile
]:
    document = causal_proof_variant_profile_v2()
    profiles = document.get("profiles")
    if not isinstance(profiles, list):
        raise RuntimeError("causal proof profile document is invalid")
    result: dict[str, CausalProofVariantProfile] = {}
    for value in profiles:
        if not isinstance(value, Mapping):
            raise RuntimeError("causal proof variant profile is invalid")
        variant_id = value.get("variant_id")
        stages = value.get("effective_stages")
        optional_order = value.get("optional_order")
        optional_routes = value.get("optional_routes")
        if (
            not isinstance(variant_id, str)
            or not isinstance(stages, list)
            or not isinstance(optional_order, list)
            or not isinstance(optional_routes, list)
            or not all(isinstance(item, Mapping) for item in optional_routes)
        ):
            raise RuntimeError("causal proof variant profile is incomplete")
        profile = CausalProofVariantProfile(
            variant_id=variant_id,
            effective_stages=tuple(StageName(item) for item in stages),
            optional_order=tuple(StageName(item) for item in optional_order),
            optional_routes=tuple(
                MappingProxyType(dict(item)) for item in optional_routes
            ),
            compiler_reference_kernel_policy=str(
                value.get("compiler_reference_kernel_policy")
            ),
            proof_authority=str(value.get("terminal_proof_authority")),
        )
        if variant_id in result:
            raise RuntimeError("duplicate causal proof variant profile")
        result[variant_id] = profile
    expected = {f"A{index}" for index in range(13)}
    if set(result) != expected:
        raise RuntimeError("causal proof profile must contain exactly A0-A12")
    if cid_for_dag_json(document) != CAUSAL_PROOF_VARIANT_PROFILE_V2_CID:
        raise RuntimeError("causal proof variant profile CID drifted")
    return MappingProxyType(result)


CAUSAL_PROOF_VARIANT_PROFILES: Final = (
    _build_causal_proof_variant_profiles()
)


def get_causal_proof_variant_profile(
    variant_id: str,
) -> CausalProofVariantProfile:
    """Return one exact G210 profile without falling back to revision 1."""

    try:
        return CAUSAL_PROOF_VARIANT_PROFILES[variant_id]
    except (KeyError, TypeError) as exc:
        raise ProtocolContractError(
            f"variant is not in the causal proof profile: {variant_id!r}"
        ) from exc


def effective_variant_stages(
    variant_id: str,
    *,
    causal_proof_protocol_cid: str | None = None,
) -> tuple[StageName, ...]:
    """Resolve stages under an explicitly selected additive protocol."""

    if causal_proof_protocol_cid is None:
        return get_variant_definition(variant_id).stages
    if causal_proof_protocol_cid != CAUSAL_PROOF_PROTOCOL_V2_CID:
        raise ProtocolContractError("unsupported causal proof protocol CID")
    return get_causal_proof_variant_profile(variant_id).effective_stages


__all__ = [
    "ALL_VARIANT_IDS",
    "CAUSAL_PROOF_VARIANT_PROFILES",
    "CausalProofVariantProfile",
    "HammerPolicy",
    "PremiseRanking",
    "SpacyMode",
    "StagePolicy",
    "VARIANTS",
    "VARIANT_REGISTRY",
    "VARIANT_REGISTRY_SCHEMA",
    "VARIANT_REGISTRY_SHA256",
    "VariantDefinition",
    "effective_variant_stages",
    "get_causal_proof_variant_profile",
    "get_variant_definition",
]
