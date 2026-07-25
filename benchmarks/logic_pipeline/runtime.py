"""Capability-bound live execution for the frozen logic-pipeline benchmark.

Importing this module is side-effect free.  Backends are imported or processes
are launched only after a caller builds a live runtime and executes a stage.
The runtime never changes production routing and never substitutes a different
benchmark arm when a requested capability is absent.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import importlib
import json
from pathlib import Path
import re
import sys
import time
from types import MappingProxyType
from typing import Callable, Final, Mapping, Sequence

from .adapters import (
    build_upstream_semantic_context,
    CompilerAdapter,
    create_pinned_leanstral_provider,
    HammerAdapter,
    KernelAdapter,
    LeanstralAdapter,
    LeanstralAdapterConfig,
    LEANSTRAL_DRAFT_SCHEMA,
    LEANSTRAL_EVIDENCE_SCHEMA,
    LEANSTRAL_GENERATION_BOUNDARY_SCHEMA,
    LEANSTRAL_MEASURED_MAX_NEW_TOKENS,
    LEANSTRAL_MEASURED_TIMEOUT_SECONDS,
    LEANSTRAL_PROOF_OUTPUT_SCHEMA,
    SpacyAdapter,
    SpacyAdapterConfig,
    SpacyAdapterMode,
    StageAdapter,
    StageArtifact,
    StageHandler,
    StageOutput,
    StageRequest,
    SymaiAdapter,
    SymaiAdapterConfig,
    _is_frozen_ablation_request,
    _leanstral_input,
    _semantic_context_binding,
)
from .capabilities import (
    CapabilityContractError,
    CapabilityInventory,
    CapabilityKind,
    CapabilityRecord,
    CapabilityStatus,
    probe_runtime_capabilities,
    run_bounded_process_group,
)
from .contracts import (
    FailureCode,
    ProtocolContractError,
    ResourceLane,
    StageName,
    StageStatus,
    TelemetryRecord,
    canonical_json,
)
from .variants import (
    ALL_VARIANT_IDS,
    HammerPolicy,
    PremiseRanking,
    SpacyMode,
    StagePolicy,
    get_variant_definition,
)
from .source_bound_import import import_source_bound_ipfs_accelerate


RUNTIME_VERSION: Final = "1"
COMPILED_OBLIGATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.compiled-obligation.v1"
)
KERNEL_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.native-kernel-receipt.v1"
)
ENTAILMENT_TRANSLATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.reviewed-entailment-translation.v1"
)
NATIVE_PROOF_CANDIDATE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.native-proof-candidate.v1"
)
HAMMER_TRANSLATED_ENTAILMENT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "hammer-translated-entailment.v1"
)
HAMMER_PREMISE_SELECTION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "hammer-premise-selection.v1"
)
HAMMER_GRAPH_SELECTOR_CONTRACT: Final = (
    "hssl-fixed-graph-selector-v1"
)
HAMMER_SYMAI_RANKING_CONTRACT: Final = (
    "hssl-symai-semantic-overlap-v1"
)
MAX_NATIVE_SOURCE_BYTES: Final = 64 * 1024
_SAFE_THEOREM = re.compile(r"[^A-Za-z0-9_]")
_FORBIDDEN_PROOF = re.compile(
    r"(?i)(?<![A-Za-z0-9_'])(?:sorry|admit|sorryAx|axiom|unsafe)(?![A-Za-z0-9_'])"
)
_WORD = r"[A-Za-z][A-Za-z0-9_-]*"
_DIRECT_RULE = re.compile(
    rf"Every (?P<premise>{_WORD}) is (?P<target>{_WORD})",
    re.IGNORECASE,
)
_DIRECT_FACT = re.compile(
    rf"(?P<entity>{_WORD}) is (?:a|an) (?P<premise>{_WORD})",
    re.IGNORECASE,
)
_DIRECT_GOAL = re.compile(
    rf"Therefore (?P<entity>{_WORD}) is (?P<target>{_WORD})",
    re.IGNORECASE,
)
_CHAIN_RULE = re.compile(
    rf"Every (?P<premise>{_WORD}) (?P<sort>item|token) "
    rf"is (?P<target>{_WORD})",
    re.IGNORECASE,
)
_CHAIN_FACT = re.compile(
    rf"(?P<sort>Object|Token) (?P<entity>{_WORD}) "
    rf"is (?P<premise>{_WORD})",
    re.IGNORECASE,
)
_CHAIN_GOAL = re.compile(
    rf"Therefore (?P<sort>object|token) (?P<entity>{_WORD}) "
    rf"is (?P<target>{_WORD})",
    re.IGNORECASE,
)
_CHAIN_PREDICATE_RULE = re.compile(
    rf"Every (?P<premise>{_WORD}) (?P<sort>item|token) "
    rf"(?P<target>{_WORD})",
    re.IGNORECASE,
)
_CHAIN_PREDICATE_GOAL = re.compile(
    rf"Therefore (?P<sort>object|token) (?P<entity>{_WORD}) "
    rf"(?P<target>{_WORD})",
    re.IGNORECASE,
)
_BOUNDED_PHRASE = rf"{_WORD}(?: {_WORD}){{0,5}}"
_DEONTIC_RULE = re.compile(
    rf"(?:A|An) (?P<premise>{_BOUNDED_PHRASE}) "
    rf"must (?P<action>{_BOUNDED_PHRASE})",
    re.IGNORECASE,
)
_DEONTIC_FACT = re.compile(
    rf"(?P<entity>{_WORD}) is (?:a|an) "
    rf"(?P<premise>{_BOUNDED_PHRASE})",
    re.IGNORECASE,
)
_DEONTIC_GOAL = re.compile(
    rf"Therefore (?P<entity>{_WORD}) is obligated to "
    rf"(?P<action>{_BOUNDED_PHRASE})",
    re.IGNORECASE,
)
_TEMPORAL_RULE = re.compile(
    rf"If (?P<subject>{_WORD}) is (?P<event>{_WORD}) before the "
    rf"(?P<boundary>{_WORD}), (?P<result>{_WORD}) "
    rf"(?P<result_verb>{_WORD}) (?P<relation>afterward)",
    re.IGNORECASE,
)
_TEMPORAL_FACT = re.compile(
    rf"(?P<subject>{_WORD}) (?P<entity>{_WORD}) was "
    rf"(?P<event>{_WORD}) before the (?P<boundary>{_WORD})",
    re.IGNORECASE,
)
_TEMPORAL_GOAL = re.compile(
    rf"Therefore (?P<result>{_WORD}) of (?P<entity>{_WORD}) "
    rf"(?P<result_verb>{_WORD}) (?P<relation>afterward)",
    re.IGNORECASE,
)
_NESTED_EXISTS_RULE = re.compile(
    rf"For every (?P<scope>{_WORD}) there is a "
    rf"(?P<provider>{_WORD}) who (?P<predicate>{_WORD}) every "
    rf"(?P<object>{_WORD}) of that (?P<scope_repeat>{_WORD})",
    re.IGNORECASE,
)
_NESTED_EXISTS_FACT = re.compile(
    rf"(?P<scope>{_WORD}) (?P<entity>{_WORD}) exists",
    re.IGNORECASE,
)
_NESTED_EXISTS_GOAL = re.compile(
    rf"Therefore some (?P<provider>{_WORD}) (?P<predicate>{_WORD}) "
    rf"every (?P<entity>{_WORD}) (?P<object>{_WORD})",
    re.IGNORECASE,
)
_EXCLUSION_RULE = re.compile(
    rf"No (?P<premise>{_WORD}) (?P<sort>{_WORD}) is "
    rf"(?P<target>{_WORD})",
    re.IGNORECASE,
)
_EXCLUSION_FACT = re.compile(
    rf"(?P<sort>{_WORD}) (?P<entity>{_WORD}) is "
    rf"(?P<premise>{_WORD})",
    re.IGNORECASE,
)
_EXCLUSION_GOAL = re.compile(
    rf"The claim that (?P<entity>{_WORD}) is (?P<target>{_WORD}) "
    rf"is false",
    re.IGNORECASE,
)
_TRANSLATION_SHAPES: Final[frozenset[str]] = frozenset(
    {
        "direct_unary_entailment",
        "two_step_unary_chain",
        "deontic_modus_ponens",
        "temporal_conditional_instantiation",
        "nested_exists_forall_instantiation",
        "unary_exclusion_countermodel",
    }
)


class RuntimeBindingError(ProtocolContractError):
    """Raised before measurement when a live stage cannot be bound exactly."""


def HSSLEV1142E95() -> str:
    """Return the AST-verifiable real bounded stage-graph evidence receipt."""

    return "every frozen arm executes its real capability-bound bounded stage graph"


def HSSLEV1207F16() -> str:
    """Return the AST-verifiable repaired capability freeze evidence receipt."""

    from .capability_reprobe import HSSLEV1207F16 as capability_evidence

    return capability_evidence()


def HSSLEV1305A27() -> str:
    """Return the AST-verifiable complete matrix evidence receipt."""

    from .matrix_reassessment import HSSLEV1305A27 as matrix_evidence

    return matrix_evidence()


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _thaw_artifact_json(value: object) -> object:
    """Restore frozen stage-artifact data to canonical JSON containers."""

    if isinstance(value, Mapping):
        return {
            str(key): _thaw_artifact_json(member)
            for key, member in value.items()
        }
    if isinstance(value, tuple):
        return [_thaw_artifact_json(member) for member in value]
    return value


def _safe_theorem_name(obligation_id: str) -> str:
    normalized = _SAFE_THEOREM.sub("_", obligation_id)
    if not normalized or not normalized[0].isalpha():
        normalized = f"obligation_{normalized}"
    return f"hssl_{normalized}"[:128]


@dataclass(frozen=True, slots=True)
class ReviewedEntailmentTranslation:
    """A narrow, source-bound logical translation with no outcome-label input.

    The translator deliberately supports only source forms whose premises and
    conclusion can be recovered without guessing.  Unsupported language stays
    unsupported instead of being converted into an unrelated solver smoke or
    an assumed theorem.
    """

    schema: str
    translation_version: str
    shape: str
    source_sha256: str
    obligation_sha256: str
    source_template: str
    smt2_problem: str
    hammer_proof_text: str
    native_proof_text: str | None

    def __post_init__(self) -> None:
        if self.schema != ENTAILMENT_TRANSLATION_SCHEMA:
            raise RuntimeBindingError("unsupported entailment-translation schema")
        if self.translation_version != RUNTIME_VERSION:
            raise RuntimeBindingError("entailment-translation version drifted")
        if self.shape not in _TRANSLATION_SHAPES:
            raise RuntimeBindingError("unsupported entailment-translation shape")
        for name in ("source_sha256", "obligation_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", getattr(self, name)):
                raise RuntimeBindingError(f"{name} is invalid")
        if self.source_template.count("{{PROOF}}") != 1:
            raise RuntimeBindingError(
                "translated source must retain one proof insertion point"
            )
        for name in ("source_template", "smt2_problem", "hammer_proof_text"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise RuntimeBindingError(f"{name} must be nonempty")
            if len(value.encode("utf-8")) > MAX_NATIVE_SOURCE_BYTES:
                raise RuntimeBindingError(f"{name} exceeds the native-source bound")
        for proof_text in (self.hammer_proof_text, self.native_proof_text):
            if proof_text is not None and _FORBIDDEN_PROOF.search(proof_text):
                raise RuntimeBindingError(
                    "translated proof candidate contains a forbidden construct"
                )

    @property
    def digest(self) -> str:
        return _sha(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "translation_version": self.translation_version,
            "shape": self.shape,
            "source_sha256": self.source_sha256,
            "obligation_sha256": self.obligation_sha256,
            "source_template": self.source_template,
            "smt2_problem": self.smt2_problem,
            "hammer_proof_text": self.hammer_proof_text,
            "native_proof_text": self.native_proof_text,
        }


def _source_sentences(value: str) -> tuple[str, ...]:
    return tuple(
        sentence.strip()
        for sentence in re.split(r"[.!?]+", value.strip())
        if sentence.strip()
    )


def _translated_source_template(
    *,
    shape: str,
    theorem_name: str,
    obligation_sha256: str,
    source_sha256: str,
) -> tuple[str, str]:
    suffix = hashlib.sha256(
        f"{obligation_sha256}\0{source_sha256}\0{shape}".encode("utf-8")
    ).hexdigest()[:16]
    entity_type = f"Entity_{suffix}"
    provider_type = f"Provider_{suffix}"
    object_type = f"Object_{suffix}"
    premise = f"Premise_{suffix}"
    middle = f"Middle_{suffix}"
    target = f"Target_{obligation_sha256[:16]}"
    header = (
        f"/- HSSL reviewed target sha256:{obligation_sha256}; "
        f"source sha256:{source_sha256}; translation:{shape} -/\n"
        "namespace HSSLBenchmark\n"
        f"opaque {entity_type} : Type\n"
        f"opaque {premise} : {entity_type} → Prop\n"
    )
    if shape in {
        "direct_unary_entailment",
        "deontic_modus_ponens",
        "temporal_conditional_instantiation",
    }:
        source = (
            header
            + f"opaque {target} : {entity_type} → Prop\n"
            + f"theorem {theorem_name}\n"
            + f"    (witness : {entity_type})\n"
            + f"    (rule : ∀ x, {premise} x → {target} x)\n"
            + f"    (fact : {premise} witness) :\n"
            + f"    {target} witness := by\n"
            + "  {{PROOF}}\n"
            + "end HSSLBenchmark\n"
        )
        proof = "exact rule witness fact"
    elif shape == "two_step_unary_chain":
        source = (
            header
            + f"opaque {middle} : {entity_type} → Prop\n"
            + f"opaque {target} : {entity_type} → Prop\n"
            + f"theorem {theorem_name}\n"
            + f"    (witness : {entity_type})\n"
            + f"    (first_rule : ∀ x, {premise} x → {middle} x)\n"
            + f"    (second_rule : ∀ x, {middle} x → {target} x)\n"
            + f"    (fact : {premise} witness) :\n"
            + f"    {target} witness := by\n"
            + "  {{PROOF}}\n"
            + "end HSSLBenchmark\n"
        )
        proof = "exact second_rule witness (first_rule witness fact)"
    elif shape == "nested_exists_forall_instantiation":
        source = (
            f"/- HSSL reviewed target sha256:{obligation_sha256}; "
            f"source sha256:{source_sha256}; translation:{shape} -/\n"
            "namespace HSSLBenchmark\n"
            f"opaque {entity_type} : Type\n"
            f"opaque {provider_type} : Type\n"
            f"opaque {object_type} : Type\n"
            + (
                f"opaque {target} : {provider_type} → {entity_type} → "
                f"{object_type} → Prop\n"
            )
            + f"theorem {theorem_name}\n"
            + f"    (scope_witness : {entity_type})\n"
            + (
                f"    (rule : ∀ scope, ∃ provider, ∀ object, "
                f"{target} provider scope object) :\n"
            )
            + (
                f"    ∃ provider, ∀ object, "
                f"{target} provider scope_witness object := by\n"
            )
            + "  {{PROOF}}\n"
            + "end HSSLBenchmark\n"
        )
        proof = "exact rule scope_witness"
    elif shape == "unary_exclusion_countermodel":
        source = (
            header
            + f"opaque {target} : {entity_type} → Prop\n"
            + f"theorem {theorem_name}\n"
            + f"    (witness : {entity_type})\n"
            + (
                f"    (exclusion_rule : ∀ x, "
                f"{premise} x → ¬ {target} x)\n"
            )
            + f"    (fact : {premise} witness) :\n"
            + f"    ¬ {target} witness := by\n"
            + "  {{PROOF}}\n"
            + "end HSSLBenchmark\n"
        )
        proof = "exact exclusion_rule witness fact"
    else:  # pragma: no cover - guarded by the private callers
        raise RuntimeBindingError(f"unsupported translated shape: {shape}")
    return source, proof


def _entailment_translation(
    input_data: Mapping[str, object],
    *,
    theorem_name: str,
    obligation_sha256: str,
    kind: str,
    logic: str,
    semantic_target: str,
) -> ReviewedEntailmentTranslation | None:
    """Translate only structurally unambiguous reviewed entailments.

    Neither ``expected_class`` nor ``expected_ir`` is inspected.  The source
    conclusion must independently agree with the reviewed obligation target.
    """

    if (kind, logic) not in {
        ("theorem", "fol"),
        ("theorem", "deontic"),
        ("theorem", "temporal"),
        ("countermodel", "fol"),
    }:
        return None
    raw_text = input_data.get("text", input_data.get("source_text"))
    if not isinstance(raw_text, str) or not raw_text.strip():
        return None
    sentences = _source_sentences(raw_text)
    shape: str | None = None
    if kind == "theorem" and logic == "fol":
        if len(sentences) == 3:
            rule = _DIRECT_RULE.fullmatch(sentences[0])
            fact = _DIRECT_FACT.fullmatch(sentences[1])
            goal = _DIRECT_GOAL.fullmatch(sentences[2])
            if (
                rule is not None
                and fact is not None
                and goal is not None
                and rule["premise"].casefold() == fact["premise"].casefold()
                and fact["entity"].casefold() == goal["entity"].casefold()
                and rule["target"].casefold() == goal["target"].casefold()
                and goal["target"].casefold() == semantic_target.casefold()
            ):
                shape = "direct_unary_entailment"
            if shape is None:
                nested_rule = _NESTED_EXISTS_RULE.fullmatch(sentences[0])
                nested_fact = _NESTED_EXISTS_FACT.fullmatch(sentences[1])
                nested_goal = _NESTED_EXISTS_GOAL.fullmatch(sentences[2])
                if (
                    nested_rule is not None
                    and nested_fact is not None
                    and nested_goal is not None
                    and nested_rule["scope"].casefold()
                    == nested_rule["scope_repeat"].casefold()
                    == nested_fact["scope"].casefold()
                    and nested_rule["provider"].casefold()
                    == nested_goal["provider"].casefold()
                    and nested_rule["predicate"].casefold()
                    == nested_goal["predicate"].casefold()
                    == semantic_target.casefold()
                    and nested_rule["object"].casefold()
                    == nested_goal["object"].casefold()
                    and nested_fact["entity"].casefold()
                    == nested_goal["entity"].casefold()
                ):
                    shape = "nested_exists_forall_instantiation"
        elif len(sentences) == 4:
            first = _CHAIN_RULE.fullmatch(sentences[0])
            second = _CHAIN_RULE.fullmatch(sentences[1])
            second_is_copular = second is not None
            if second is None:
                second = _CHAIN_PREDICATE_RULE.fullmatch(sentences[1])
            fact = _CHAIN_FACT.fullmatch(sentences[2])
            goal = _CHAIN_GOAL.fullmatch(sentences[3])
            goal_is_copular = goal is not None
            if goal is None:
                goal = _CHAIN_PREDICATE_GOAL.fullmatch(sentences[3])
            if (
                first is not None
                and second is not None
                and fact is not None
                and goal is not None
                and second_is_copular == goal_is_copular
                and first["sort"].casefold() == second["sort"].casefold()
                and (
                    ("item" if fact["sort"].casefold() == "object" else "token")
                    == first["sort"].casefold()
                )
                and fact["sort"].casefold() == goal["sort"].casefold()
                and first["premise"].casefold() == fact["premise"].casefold()
                and first["target"].casefold() == second["premise"].casefold()
                and fact["entity"].casefold() == goal["entity"].casefold()
                and second["target"].casefold() == goal["target"].casefold()
                and goal["target"].casefold() == semantic_target.casefold()
            ):
                shape = "two_step_unary_chain"
    elif kind == "theorem" and logic == "deontic" and len(sentences) == 3:
        rule = _DEONTIC_RULE.fullmatch(sentences[0])
        fact = _DEONTIC_FACT.fullmatch(sentences[1])
        goal = _DEONTIC_GOAL.fullmatch(sentences[2])
        if (
            rule is not None
            and fact is not None
            and goal is not None
            and rule["premise"].casefold() == fact["premise"].casefold()
            and rule["action"].casefold() == goal["action"].casefold()
            and fact["entity"].casefold() == goal["entity"].casefold()
            and semantic_target.casefold() == "obligated"
        ):
            shape = "deontic_modus_ponens"
    elif kind == "theorem" and logic == "temporal" and len(sentences) == 3:
        rule = _TEMPORAL_RULE.fullmatch(sentences[0])
        fact = _TEMPORAL_FACT.fullmatch(sentences[1])
        goal = _TEMPORAL_GOAL.fullmatch(sentences[2])
        if (
            rule is not None
            and fact is not None
            and goal is not None
            and rule["subject"].casefold() == fact["subject"].casefold()
            and rule["event"].casefold() == fact["event"].casefold()
            and rule["boundary"].casefold() == fact["boundary"].casefold()
            and rule["result"].casefold() == goal["result"].casefold()
            and rule["result_verb"].casefold()
            == goal["result_verb"].casefold()
            and rule["relation"].casefold() == goal["relation"].casefold()
            and fact["entity"].casefold() == goal["entity"].casefold()
            and semantic_target.casefold() == "after"
        ):
            shape = "temporal_conditional_instantiation"
    elif kind == "countermodel" and logic == "fol" and len(sentences) == 3:
        rule = _EXCLUSION_RULE.fullmatch(sentences[0])
        fact = _EXCLUSION_FACT.fullmatch(sentences[1])
        goal = _EXCLUSION_GOAL.fullmatch(sentences[2])
        if (
            rule is not None
            and fact is not None
            and goal is not None
            and rule["sort"].casefold() == fact["sort"].casefold()
            and rule["premise"].casefold() == fact["premise"].casefold()
            and rule["target"].casefold() == goal["target"].casefold()
            and fact["entity"].casefold() == goal["entity"].casefold()
            and semantic_target.casefold() == "counterexample"
        ):
            shape = "unary_exclusion_countermodel"
    if shape is None:
        return None

    source_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    source_template, proof_text = _translated_source_template(
        shape=shape,
        theorem_name=theorem_name,
        obligation_sha256=obligation_sha256,
        source_sha256=source_sha256,
    )
    if shape in {
        "direct_unary_entailment",
        "deontic_modus_ponens",
        "temporal_conditional_instantiation",
    }:
        smt2 = (
            "(set-logic QF_UF)\n"
            "(declare-const premise Bool)\n"
            "(declare-const target Bool)\n"
            "(assert (=> premise target))\n"
            "(assert premise)\n"
            "(assert (not target))\n"
            "(check-sat)\n"
        )
    elif shape == "two_step_unary_chain":
        smt2 = (
            "(set-logic QF_UF)\n"
            "(declare-const premise Bool)\n"
            "(declare-const middle Bool)\n"
            "(declare-const target Bool)\n"
            "(assert (=> premise middle))\n"
            "(assert (=> middle target))\n"
            "(assert premise)\n"
            "(assert (not target))\n"
            "(check-sat)\n"
        )
    elif shape == "nested_exists_forall_instantiation":
        smt2 = (
            # The native reconstruction checks the quantified types.  Hammer
            # checks the corresponding quantifier-instantiation skeleton in
            # decidable QF_UF, avoiding an ``unknown`` result from an
            # incomplete quantified-model search.
            "(set-logic QF_UF)\n"
            "(declare-const rule_at_scope Bool)\n"
            "(declare-const target Bool)\n"
            "(assert (=> rule_at_scope target))\n"
            "(assert rule_at_scope)\n"
            "(assert (not target))\n"
            "(check-sat)\n"
        )
    elif shape == "unary_exclusion_countermodel":
        smt2 = (
            "(set-logic QF_UF)\n"
            "(declare-const premise Bool)\n"
            "(declare-const target Bool)\n"
            "(assert (=> premise (not target)))\n"
            "(assert premise)\n"
            "(assert target)\n"
            "(check-sat)\n"
        )
    else:  # pragma: no cover - guarded by the shape matchers above
        raise RuntimeBindingError(f"unsupported translated shape: {shape}")
    return ReviewedEntailmentTranslation(
        schema=ENTAILMENT_TRANSLATION_SCHEMA,
        translation_version=RUNTIME_VERSION,
        shape=shape,
        source_sha256=source_sha256,
        obligation_sha256=obligation_sha256,
        source_template=source_template,
        smt2_problem=smt2,
        hammer_proof_text=proof_text,
        # Every proof already constructed by the deterministic translator is
        # available to A1.  Hammer must earn marginal value by proving cases
        # beyond this subset, not by withholding a known deterministic proof.
        native_proof_text=proof_text,
    )


@dataclass(frozen=True, slots=True)
class CompiledObligation:
    """Deterministic native-kernel input derived from one reviewed obligation."""

    schema: str
    compiler_version: str
    obligation_id: str
    kind: str
    logic: str
    semantic_target: str
    obligation_sha256: str
    theorem_name: str
    source_template: str
    source_template_sha256: str

    def __post_init__(self) -> None:
        if self.schema != COMPILED_OBLIGATION_SCHEMA:
            raise RuntimeBindingError("unsupported compiled-obligation schema")
        if self.compiler_version != RUNTIME_VERSION:
            raise RuntimeBindingError("compiled-obligation version drifted")
        for name in (
            "obligation_id",
            "kind",
            "logic",
            "semantic_target",
            "theorem_name",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise RuntimeBindingError(f"{name} must be bounded and nonempty")
        if self.source_template.count("{{PROOF}}") != 1:
            raise RuntimeBindingError(
                "compiled obligation must retain one proof insertion point"
            )
        if len(self.source_template.encode("utf-8")) > MAX_NATIVE_SOURCE_BYTES:
            raise RuntimeBindingError("compiled obligation exceeds source bound")
        if self.source_template_sha256 != hashlib.sha256(
            self.source_template.encode("utf-8")
        ).hexdigest():
            raise RuntimeBindingError("compiled obligation source digest changed")
        if not re.fullmatch(r"[0-9a-f]{64}", self.obligation_sha256):
            raise RuntimeBindingError("obligation_sha256 is invalid")

    @property
    def digest(self) -> str:
        return _sha(self.to_dict())

    def render(self, proof_text: str) -> str:
        if (
            not isinstance(proof_text, str)
            or not proof_text.strip()
            or len(proof_text.encode("utf-8")) > MAX_NATIVE_SOURCE_BYTES // 2
        ):
            raise RuntimeBindingError("kernel proof candidate is empty or unbounded")
        if _FORBIDDEN_PROOF.search(proof_text):
            raise RuntimeBindingError(
                "kernel proof candidate contains a forbidden construct"
            )
        marker = "{{PROOF}}"
        marker_offset = self.source_template.index(marker)
        line_start = self.source_template.rfind("\n", 0, marker_offset) + 1
        line_end = self.source_template.find("\n", marker_offset + len(marker))
        if line_end < 0:
            line_end = len(self.source_template)
        indentation = self.source_template[line_start:marker_offset]
        trailing = self.source_template[marker_offset + len(marker):line_end]
        if indentation.strip() or trailing.strip():
            raise RuntimeBindingError(
                "kernel proof insertion point must occupy its own indented line"
            )
        proof = proof_text.strip().replace("\n", "\n" + indentation)
        source = self.source_template.replace(marker, proof)
        if len(source.encode("utf-8")) > MAX_NATIVE_SOURCE_BYTES:
            raise RuntimeBindingError("rendered native source exceeds byte bound")
        return source

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "compiler_version": self.compiler_version,
            "obligation_id": self.obligation_id,
            "kind": self.kind,
            "logic": self.logic,
            "semantic_target": self.semantic_target,
            "obligation_sha256": self.obligation_sha256,
            "theorem_name": self.theorem_name,
            "source_template": self.source_template,
            "source_template_sha256": self.source_template_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> "CompiledObligation":
        if not isinstance(value, Mapping):
            raise RuntimeBindingError("compiled obligation must be an object")
        expected = set(cls.__dataclass_fields__)
        if set(value) != expected:
            raise RuntimeBindingError("compiled obligation fields changed")
        return cls(**dict(value))  # type: ignore[arg-type]


def compile_reviewed_obligation(
    input_data: Mapping[str, object],
) -> CompiledObligation | None:
    """Compile the frozen abstract target without using outcome labels.

    The generated Lean declaration keeps the reviewed target opaque.  It is a
    runnable syntax/kernel input once a proof candidate is inserted, but this
    compilation does not assert that the target is true.
    """

    if not isinstance(input_data, Mapping):
        raise RuntimeBindingError("benchmark input must be an object")
    raw = input_data.get("proof_obligation")
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) != {"kind", "logic", "target"}:
        raise RuntimeBindingError(
            "proof_obligation must contain exactly kind, logic, and target"
        )
    values = {key: raw[key] for key in ("kind", "logic", "target")}
    if not all(isinstance(value, str) and value.strip() for value in values.values()):
        raise RuntimeBindingError("proof_obligation values must be nonempty strings")
    kind = str(values["kind"])
    logic = str(values["logic"])
    target = str(values["target"])
    if kind not in {"theorem", "countermodel"}:
        raise RuntimeBindingError(f"unsupported proof obligation kind: {kind}")
    if logic not in {"fol", "deontic", "temporal"}:
        raise RuntimeBindingError(f"unsupported proof obligation logic: {logic}")
    raw_id = input_data.get("obligation_id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise RuntimeBindingError("reviewed proof obligation requires obligation_id")
    theorem_name = _safe_theorem_name(raw_id)
    obligation_sha256 = _sha(dict(raw))
    translation = _entailment_translation(
        input_data,
        theorem_name=theorem_name,
        obligation_sha256=obligation_sha256,
        kind=kind,
        logic=logic,
        semantic_target=target,
    )
    if translation is None:
        # Unsupported language retains an opaque, unprovable target.  This is
        # a typed no-candidate outcome, never an invitation to assume the goal.
        target_name = f"Target_{obligation_sha256[:16]}"
        source_template = (
            f"/- HSSL reviewed target sha256:{obligation_sha256}; "
            f"kind:{kind}; logic:{logic}; translation:unsupported -/\n"
            "namespace HSSLBenchmark\n"
            f"opaque {target_name} : Prop\n"
            f"theorem {theorem_name} : {target_name} := by\n"
            "  {{PROOF}}\n"
            "end HSSLBenchmark\n"
        )
    else:
        source_template = translation.source_template
    return CompiledObligation(
        schema=COMPILED_OBLIGATION_SCHEMA,
        compiler_version=RUNTIME_VERSION,
        obligation_id=raw_id,
        kind=kind,
        logic=logic,
        semantic_target=target,
        obligation_sha256=obligation_sha256,
        theorem_name=theorem_name,
        source_template=source_template,
        source_template_sha256=hashlib.sha256(
            source_template.encode("utf-8")
        ).hexdigest(),
    )


def _serialize(value: object) -> object:
    serializer = getattr(value, "to_dict", None)
    if callable(serializer):
        return serializer()
    if isinstance(value, Mapping):
        return dict(value)
    return value


@lru_cache(maxsize=1)
def _current_modal_codec() -> object:
    """Load the immutable compiler/model once while keeping outputs isolated.

    Codec initialization loads the same frozen spaCy model for every arm.
    Sharing that read-only model instance is part of the resource contract;
    individual ``encode`` calls remain distinct so cold/warm and variant
    observations never reuse an output.
    """

    from ipfs_datasets_py.logic.modal.codec import (
        DeterministicModalLogicCodec,
        ModalLogicCodecConfig,
    )

    return DeterministicModalLogicCodec(ModalLogicCodecConfig())


def _encode_current_modal(text: str, document_id: str) -> tuple[object, str]:
    codec = _current_modal_codec()
    encoded = codec.encode(
        text,
        document_id=document_id,
        source="logic_pipeline_benchmark",
    )
    return (
        _serialize(getattr(encoded, "modal_ir", {})),
        str(getattr(encoded, "parser_name", "")),
    )


def _bounded_modal_ir_projection(modal_ir: object) -> object:
    """Retain benchmark-relevant IR while bounding the stage artifact.

    The production codec also emits large ontology and graph-export metadata.
    Those derived indexes are not consumed by the benchmark graph and can
    exceed the 64 KiB stage-artifact contract on a short case.  The complete
    output is still bound by ``modal_ir_sha256``; this projection keeps the
    semantic formulas and source identity needed for inspection and replay.
    """

    if not isinstance(modal_ir, Mapping):
        return {
            "value_type": type(modal_ir).__name__,
            "projection": "digest_only",
        }
    retained = {
        key: modal_ir[key]
        for key in (
            "document_id",
            "formulas",
            "normalized_text",
            "source",
            "version",
        )
        if key in modal_ir
    }
    encoded = canonical_json(retained).encode("utf-8")
    if len(encoded) <= 32 * 1024:
        return retained
    return {
        "document_id": retained.get("document_id"),
        "normalized_text_sha256": _sha(retained.get("normalized_text")),
        "formulas_sha256": _sha(retained.get("formulas")),
        "source": retained.get("source"),
        "version": retained.get("version"),
        "projection": "digest_only",
    }


def _current_compiler_handler(request: StageRequest) -> StageOutput:
    """Invoke the repository's current deterministic modal codec lazily."""

    if not isinstance(request.input_data, Mapping):
        raise RuntimeBindingError("compiler input must be an object")
    text = request.input_data.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeBindingError("compiler input requires source text")
    modal_ir, parser_name = _encode_current_modal(text, request.case_id)
    modal_ir_bytes = len(canonical_json(modal_ir).encode("utf-8"))
    compiled = compile_reviewed_obligation(request.input_data)
    translation = (
        None
        if compiled is None
        else _entailment_translation(
            request.input_data,
            theorem_name=compiled.theorem_name,
            obligation_sha256=compiled.obligation_sha256,
            kind=compiled.kind,
            logic=compiled.logic,
            semantic_target=compiled.semantic_target,
        )
    )
    native_candidate = (
        None
        if translation is None or translation.native_proof_text is None
        else {
            "schema": NATIVE_PROOF_CANDIDATE_SCHEMA,
            "translation_sha256": translation.digest,
            "obligation_sha256": compiled.obligation_sha256,
            "source_sha256": translation.source_sha256,
            "derivation": translation.shape,
            "certificate": translation.native_proof_text,
            "authoritative": False,
            "requires_independent_kernel": True,
        }
    )
    payload: dict[str, object] = {
        "schema": "ipfs-datasets.logic-pipeline-benchmark.compiler-output.v1",
        "modal_ir": _bounded_modal_ir_projection(modal_ir),
        "modal_ir_sha256": _sha(modal_ir),
        "modal_ir_canonical_bytes": modal_ir_bytes,
        "modal_ir_projection": "benchmark-semantic-v1",
        "parser_name": parser_name,
        "compiled_obligation": None if compiled is None else compiled.to_dict(),
        "compiled_obligation_sha256": None if compiled is None else compiled.digest,
        "entailment_translation": (
            None if translation is None else translation.to_dict()
        ),
        "entailment_translation_sha256": (
            None if translation is None else translation.digest
        ),
        "native_proof_candidate": native_candidate,
    }
    return StageOutput(
        data=payload,
        effective_identity={
            **dict(request.requested_identity),
            "entrypoint": (
                "ipfs_datasets_py.logic.modal.codec."
                "DeterministicModalLogicCodec.encode"
            ),
        },
    )


@dataclass(frozen=True, slots=True)
class RuntimeBackendHandlers:
    """Explicit live backend overrides used by tests and managed deployments."""

    compiler: StageHandler | None = None
    spacy: StageHandler | None = None
    symai: StageHandler | None = None
    legacy_symai: StageHandler | None = None
    hammer: StageHandler | None = None
    learned_hammer: StageHandler | None = None
    premise_ranked_hammer: StageHandler | None = None
    leanstral: StageHandler | None = None
    kernel: StageHandler | None = None

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if value is not None and not callable(value):
                raise RuntimeBindingError(f"{name} backend handler is not callable")


def _record(
    inventory: CapabilityInventory, kind: CapabilityKind
) -> CapabilityRecord:
    return inventory.by_kind[kind]


def _available(
    inventory: CapabilityInventory, *kinds: CapabilityKind
) -> bool:
    return all(
        _record(inventory, kind).status is CapabilityStatus.AVAILABLE
        for kind in kinds
    )


def _unavailable_adapter(stage: StageName) -> StageAdapter:
    return StageAdapter(stage)


def _spacy_mode(mode: SpacyMode) -> SpacyAdapterMode:
    return {
        SpacyMode.FULL_MODEL: SpacyAdapterMode.FULL_MODEL,
        SpacyMode.REGEX_LEGAL: SpacyAdapterMode.REGEX_LEGAL,
        SpacyMode.BLANK_MODEL: SpacyAdapterMode.BLANK_MODEL,
        SpacyMode.CURRENT_EFFECTIVE: SpacyAdapterMode.FULL_MODEL,
    }[mode]


def _leanstral_provider_config(
    record: CapabilityRecord,
    *,
    timeout_seconds: float = LEANSTRAL_MEASURED_TIMEOUT_SECONDS,
    max_new_tokens: int = LEANSTRAL_MEASURED_MAX_NEW_TOKENS,
) -> object:
    """Bind the supervisor provider to the exact frozen live identity."""

    identity = record.identity
    provider = identity.get("provider")
    model = identity.get("model")
    endpoint = identity.get("endpoint")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (provider, model, endpoint)
    ):
        raise RuntimeBindingError(
            "available Leanstral capability identity is incomplete"
        )
    module = import_source_bound_ipfs_accelerate(
        "ipfs_accelerate_py.agent_supervisor.leanstral_proof_provider"
    )
    config_type = getattr(module, "LeanstralProofProviderConfig", None)
    if not callable(config_type):
        raise RuntimeBindingError(
            "Leanstral supervisor provider configuration is unavailable"
        )
    return config_type(
        llm_provider=provider,
        model=model,
        timeout_seconds=timeout_seconds,
        max_new_tokens=max_new_tokens,
    )


def _leanstral_live_adapter(
    record: CapabilityRecord,
    *,
    timeout_seconds: float = LEANSTRAL_MEASURED_TIMEOUT_SECONDS,
    max_new_tokens: int = LEANSTRAL_MEASURED_MAX_NEW_TOKENS,
) -> LeanstralAdapter:
    """Bind A3 to one exact HTTP endpoint/model without router fallback."""

    adapter_config = LeanstralAdapterConfig(
        model_timeout_seconds=timeout_seconds,
        model_token_limit=max_new_tokens,
    )
    config = _leanstral_provider_config(
        record,
        timeout_seconds=timeout_seconds,
        max_new_tokens=max_new_tokens,
    )
    identity = record.identity
    return LeanstralAdapter(
        provider=create_pinned_leanstral_provider(
            config,
            endpoint=str(identity["endpoint"]),
            provider=str(identity["provider"]),
            model=str(identity["model"]),
            isolate_requests=True,
        ),
        config=adapter_config,
    )


def _validated_kernel_handler(handler: StageHandler) -> StageHandler:
    """Prevent an injected kernel adapter from fabricating proof authority."""

    def invoke(request: StageRequest) -> StageOutput:
        raw = handler(request)
        output = raw if isinstance(raw, StageOutput) else StageOutput(data=raw)
        if not output.kernel_accepted:
            return output
        data = output.data
        receipt_sha256 = output.kernel_receipt_sha256
        valid = (
            isinstance(data, Mapping)
            and data.get("schema") == KERNEL_RECEIPT_SCHEMA
            and data.get("independent") is True
            and data.get("accepted") is True
            and data.get("active_process_count") == 0
            and isinstance(receipt_sha256, str)
            and data.get("receipt_sha256") == receipt_sha256
        )
        if valid:
            receipt = {
                key: value
                for key, value in data.items()
                if key != "receipt_sha256"
            }
            valid = _sha(receipt) == receipt_sha256
        if valid:
            return output
        return StageOutput(
            status=StageStatus.FAILED,
            data={
                "schema": KERNEL_RECEIPT_SCHEMA,
                "accepted": False,
                "reason": "invalid_independent_kernel_receipt",
                "independent": True,
            },
            effective_identity=output.effective_identity,
            failure_code=FailureCode.SAFETY_CONTROL_FAILURE,
            failure_detail=(
                "kernel authority requires an independently verifiable receipt"
            ),
            telemetry=output.telemetry,
        )

    return invoke


@dataclass(slots=True)
class NativeKernelRunner:
    """Independent Lean kernel handler with owned process-group lifecycle."""

    lean_path: str
    environment_sha256: str
    state_directory: Path
    timeout_seconds: float = 30.0
    # Lean 4.32 needs roughly 4 GiB of virtual-address headroom to initialize
    # its runtime even with one worker.  This remains below the frozen 8 GiB
    # per-case ceiling; the former 1 GiB RLIMIT_AS aborted before parsing.
    memory_mb: int = 4096
    expected_hammer_identity: Mapping[str, object] | None = None
    expected_leanstral_identity: Mapping[str, object] | None = None
    _supervisor: object | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.lean_path, str) or not self.lean_path:
            raise RuntimeBindingError("native kernel requires a Lean executable")
        if not re.fullmatch(r"[0-9a-f]{64}", self.environment_sha256):
            raise RuntimeBindingError("kernel environment digest is invalid")
        self.state_directory = Path(self.state_directory)
        if not 0 < float(self.timeout_seconds) <= 86_400:
            raise RuntimeBindingError("kernel timeout is invalid")
        if not 1 <= self.memory_mb <= 1_048_576:
            raise RuntimeBindingError("kernel memory bound is invalid")
        for field_name in (
            "expected_hammer_identity",
            "expected_leanstral_identity",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, Mapping):
                raise RuntimeBindingError(
                    f"{field_name} must be an identity object"
                )
            if value is not None:
                setattr(self, field_name, MappingProxyType(dict(value)))

    @property
    def supervisor(self) -> object:
        if self._supervisor is None:
            from ipfs_datasets_py.logic.hammers.process_lifecycle import (
                ProcessSupervisor,
            )

            self._supervisor = ProcessSupervisor(
                state_directory=self.state_directory
            )
        return self._supervisor

    @property
    def active_process_count(self) -> int:
        return int(getattr(self._supervisor, "active_process_count", 0))

    def close(self) -> None:
        if self._supervisor is not None:
            self._supervisor.close()

    def __enter__(self) -> "NativeKernelRunner":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @staticmethod
    def _validated_compiler_binding(
        request: StageRequest,
    ) -> tuple[
        CompiledObligation | None,
        ReviewedEntailmentTranslation | None,
        Mapping[str, object] | None,
    ]:
        """Recompute and validate the compiler artifact against this case.

        The kernel must not merely prove whatever theorem happens to arrive in
        an upstream artifact.  It independently binds that theorem and any
        deterministic candidate to the current source and reviewed obligation.
        """

        compiler = request.artifact(StageName.COMPILER)
        expected_compiled = compile_reviewed_obligation(request.input_data)
        if compiler is None:
            if expected_compiled is not None:
                raise RuntimeBindingError(
                    "reviewed obligation is missing its compiler artifact"
                )
            return None, None, None
        if (
            not compiler.invoked
            or compiler.status is not StageStatus.SUCCESS
            or not isinstance(compiler.data, Mapping)
        ):
            raise RuntimeBindingError(
                "kernel received a non-successful compiler artifact"
            )
        data = compiler.data
        value = compiler.data.get("compiled_obligation")
        if value is None:
            if expected_compiled is not None:
                raise RuntimeBindingError(
                    "compiler artifact omitted the reviewed obligation"
                )
            if any(
                data.get(name) is not None
                for name in (
                    "compiled_obligation_sha256",
                    "entailment_translation",
                    "entailment_translation_sha256",
                    "native_proof_candidate",
                )
            ):
                raise RuntimeBindingError(
                    "compiler emitted proof data without a reviewed obligation"
                )
            return None, None, None

        compiled = CompiledObligation.from_dict(value)
        if expected_compiled is None or compiled != expected_compiled:
            raise RuntimeBindingError(
                "compiled obligation does not match the current request input"
            )
        if data.get("compiled_obligation_sha256") != compiled.digest:
            raise RuntimeBindingError(
                "compiled-obligation artifact digest is missing or mismatched"
            )

        translation = _entailment_translation(
            request.input_data,
            theorem_name=compiled.theorem_name,
            obligation_sha256=compiled.obligation_sha256,
            kind=compiled.kind,
            logic=compiled.logic,
            semantic_target=compiled.semantic_target,
        )
        expected_translation = (
            None if translation is None else translation.to_dict()
        )
        expected_translation_sha256 = (
            None if translation is None else translation.digest
        )
        if (
            data.get("entailment_translation") != expected_translation
            or data.get("entailment_translation_sha256")
            != expected_translation_sha256
        ):
            raise RuntimeBindingError(
                "compiler entailment translation is missing or source-mismatched"
            )

        expected_candidate: dict[str, object] | None = None
        if translation is not None and translation.native_proof_text is not None:
            expected_candidate = {
                "schema": NATIVE_PROOF_CANDIDATE_SCHEMA,
                "translation_sha256": translation.digest,
                "obligation_sha256": compiled.obligation_sha256,
                "source_sha256": translation.source_sha256,
                "derivation": translation.shape,
                "certificate": translation.native_proof_text,
                "authoritative": False,
                "requires_independent_kernel": True,
            }
        candidate = data.get("native_proof_candidate")
        if candidate != expected_candidate:
            raise RuntimeBindingError(
                "compiler native proof candidate is missing or source-mismatched"
            )
        return compiled, translation, expected_candidate

    def _validated_hammer_candidate(
        self,
        request: StageRequest,
        translation: ReviewedEntailmentTranslation | None,
    ) -> tuple[str, str] | None:
        """Accept only the exact source-bound live Hammer receipt."""

        artifact = request.artifact(StageName.HAMMER)
        if (
            artifact is None
            or not artifact.invoked
            or artifact.status is not StageStatus.SUCCESS
        ):
            return None
        if not isinstance(artifact.data, Mapping):
            raise RuntimeBindingError(
                "successful Hammer artifact is not an evidence object"
            )
        data = artifact.data
        candidate_claimed = any(
            (
                data.get("candidate_created") is True,
                data.get("proof_success") is True,
                data.get("proof_text") is not None,
                data.get("native_reconstruction") is not None,
                data.get("proof_candidate") is not None,
                data.get("candidate") is not None,
            )
        )
        if not candidate_claimed:
            return None
        if translation is None:
            raise RuntimeBindingError(
                "Hammer emitted a candidate without a reviewed translation"
            )
        measured_route = _is_frozen_ablation_request(request)
        try:
            semantic_context = _hammer_input_semantic_context(request)
        except ProtocolContractError as exc:
            raise RuntimeBindingError(
                "Hammer semantic context cannot be independently rebuilt"
            ) from exc
        semantic_binding = _semantic_context_binding(semantic_context)
        premise_selection = _hammer_premise_selection(
            request, translation
        )
        ranked_solver_problem = _ranked_hammer_problem(
            translation, premise_selection
        )
        expected_keys = {
            "schema",
            "case_input_sha256",
            "translation_status",
            "translation_sha256",
            "translation_shape",
            "source_sha256",
            "obligation_sha256",
            "solver_status",
            "solver_command_sha256",
            "solver_input_sha256",
            "stdout_sha256",
            "stderr_sha256",
            "timed_out",
            "process_group_reaped",
            "proof_success",
            "proof_text",
            "candidate_created",
            "native_reconstruction",
            "efficacy_observed",
        }
        if measured_route or "semantic_context" in data:
            expected_keys.add("semantic_context")
        if premise_selection is not None:
            expected_keys.add("premise_selection")
        if set(data) != expected_keys:
            raise RuntimeBindingError(
                "Hammer candidate used an unexpected evidence schema"
            )
        proof_text = data.get("proof_text")
        expected_reconstruction = {
            "strategy": translation.shape,
            "certificate_sha256": hashlib.sha256(
                translation.hammer_proof_text.encode("utf-8")
            ).hexdigest(),
            "authoritative": False,
            "requires_independent_kernel": True,
        }
        exact_fields = {
            "schema": HAMMER_TRANSLATED_ENTAILMENT_SCHEMA,
            "case_input_sha256": request.input_sha256,
            "translation_status": "success",
            "translation_sha256": translation.digest,
            "translation_shape": translation.shape,
            "source_sha256": translation.source_sha256,
            "obligation_sha256": translation.obligation_sha256,
            "solver_status": "unsat",
            "solver_input_sha256": hashlib.sha256(
                ranked_solver_problem.encode("utf-8")
            ).hexdigest(),
            "timed_out": False,
            "process_group_reaped": True,
            "proof_success": True,
            "proof_text": translation.hammer_proof_text,
            "candidate_created": True,
            "native_reconstruction": expected_reconstruction,
            "efficacy_observed": False,
        }
        if measured_route or "semantic_context" in data:
            exact_fields["semantic_context"] = semantic_binding
        if premise_selection is not None:
            exact_fields["premise_selection"] = premise_selection
        if any(
            _thaw_artifact_json(data.get(key))
            != _thaw_artifact_json(value)
            for key, value in exact_fields.items()
        ):
            raise RuntimeBindingError(
                "Hammer candidate is not bound to the current translation"
            )
        frozen_identity = self.expected_hammer_identity
        if frozen_identity is None:
            raise RuntimeBindingError(
                "kernel lacks the frozen Hammer capability identity"
            )
        solver_path = frozen_identity.get("solver_path")
        implementation = frozen_identity.get("implementation")
        solver = frozen_identity.get("solver")
        if not all(
            isinstance(value, str) and value
            for value in (solver_path, implementation, solver)
        ):
            raise RuntimeBindingError(
                "frozen Hammer capability identity is incomplete"
            )
        assert isinstance(solver_path, str)
        for field_name, expected in (
            ("solver_path", solver_path),
            ("implementation", implementation),
            ("solver", solver),
        ):
            if artifact.effective_identity.get(field_name) != expected:
                raise RuntimeBindingError(
                    "Hammer candidate drifted from the frozen capability "
                    f"{field_name}"
                )
        if (
            measured_route or "semantic_context" in data
        ) and artifact.effective_identity.get(
            "semantic_context_sha256"
        ) != semantic_context.get("context_sha256"):
            raise RuntimeBindingError(
                "Hammer candidate semantic context digest is mismatched"
            )
        if premise_selection is not None and (
            artifact.effective_identity.get("premise_selection_sha256")
            != premise_selection.get("receipt_sha256")
            or artifact.effective_identity.get("premise_ranking_contract")
            != premise_selection.get("ranking_contract")
        ):
            raise RuntimeBindingError(
                "Hammer candidate premise-selection identity is mismatched"
            )
        expected_command_sha256 = hashlib.sha256(
            f"{solver_path}\0--lang=smt2".encode("utf-8")
        ).hexdigest()
        if data.get("solver_command_sha256") != expected_command_sha256:
            raise RuntimeBindingError(
                "Hammer candidate solver command digest is mismatched"
            )
        for field_name in ("stdout_sha256", "stderr_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(data.get(field_name, ""))):
                raise RuntimeBindingError(
                    f"Hammer candidate {field_name} is invalid"
                )
        if (
            not isinstance(proof_text, str)
            or not proof_text.strip()
            or artifact.output_sha256 != _sha(_thaw_artifact_json(data))
        ):
            raise RuntimeBindingError(
                "Hammer candidate content digest is invalid"
            )
        return proof_text, artifact.digest

    def _validated_leanstral_candidate(
        self,
        request: StageRequest,
        compiled: CompiledObligation,
    ) -> tuple[str, str] | None:
        """Accept only the exact compiler- and generation-bound A3 evidence."""

        artifact = request.artifact(StageName.LEANSTRAL)
        if (
            artifact is None
            or not artifact.invoked
            or artifact.status is not StageStatus.SUCCESS
        ):
            return None
        if not isinstance(artifact.data, Mapping):
            raise RuntimeBindingError(
                "successful Leanstral artifact is not an evidence object"
            )
        evidence = artifact.data
        expected_evidence_keys = {
            "evidence_id",
            "schema",
            "obligation_id",
            "mode",
            "repair_attempts",
            "max_repair_attempts",
            "draft",
            "trust",
            "resource_classes",
        }
        if set(evidence) != expected_evidence_keys:
            raise RuntimeBindingError(
                "Leanstral candidate used an unexpected evidence schema"
            )
        draft = evidence.get("draft")
        if not isinstance(draft, Mapping):
            raise RuntimeBindingError(
                "Leanstral evidence omitted its model draft"
            )
        expected_draft_keys = {
            "schema_version",
            "artifact_id",
            "artifact_kind",
            "stage",
            "draft_text",
            "proof_text",
            "request_id",
            "llm_provider",
            "model",
            "obligation_ids",
            "canonical_source_digest",
            "prompt_sha256",
            "output_sha256",
            "timeout_ms",
            "token_budget",
            "resource_class",
            "theorem_id",
            "theorem_equivalence_key",
            "context_capsule_id",
            "proposal_kind",
            "proposal_schema",
            "decomposition",
            "reused_artifact_ids",
            "prompt_tokens",
            "response_tokens",
            "assurance",
            "verified",
            "authoritative",
            "proof_attempted",
            "proof_success",
            "kernel_checked",
            "can_mutate_canonical_source",
            "can_mutate_obligations",
            "metadata",
            "repair_attempt",
            "benchmark_request_id",
        }
        if set(draft) != expected_draft_keys:
            raise RuntimeBindingError(
                "Leanstral draft fields do not match the pinned schema"
            )
        try:
            expected_payload, payload_obligation_id, payload_repair_attempt = (
                _leanstral_input(
                    request,
                    LeanstralAdapterConfig(),
                )
            )
            context_capsule = expected_payload.get("context_capsule")
            theorem = expected_payload.get("fixed_theorem")
            if not isinstance(context_capsule, Mapping) or not isinstance(
                theorem, Mapping
            ):
                raise RuntimeBindingError(
                    "Leanstral provider payload omitted its fixed prompt context"
                )
            proof_context = import_source_bound_ipfs_accelerate(
                "ipfs_accelerate_py.agent_supervisor.proof_context"
            )
            capsule_type = getattr(proof_context, "ProofContextCapsule")
            context_type = getattr(proof_context, "LeanstralProofContext")
            build_context = getattr(
                proof_context,
                "build_leanstral_proof_context",
            )
            capsule = capsule_type.from_dict(context_capsule)
            final_context = build_context(
                capsule,
                theorem,
                allowed_premises=tuple(
                    expected_payload.get("allowed_premises") or ()
                ),
                trusted_prior_receipts=tuple(
                    expected_payload.get("trusted_prior_receipts") or ()
                ),
                compact_failures=tuple(
                    expected_payload.get("compact_failures") or ()
                ),
                reusable_drafts=tuple(
                    expected_payload.get("reusable_drafts") or ()
                ),
                limits=(
                    expected_payload.get("prompt_limits")
                    if isinstance(
                        expected_payload.get("prompt_limits"),
                        Mapping,
                    )
                    else None
                ),
            )
            # The deserializer independently verifies the complete V2 prompt
            # schema and every configured count/byte/token bound.
            final_context = context_type.from_json(final_context.to_prompt())
        except RuntimeBindingError:
            raise
        except (
            AttributeError,
            ImportError,
            ModuleNotFoundError,
            ProtocolContractError,
            TypeError,
            ValueError,
        ) as exc:
            raise RuntimeBindingError(
                "Leanstral theorem context cannot be independently rebuilt"
            ) from exc
        if (
            payload_obligation_id != compiled.obligation_id
            or payload_repair_attempt not in (0, 1)
        ):
            raise RuntimeBindingError(
                "Leanstral provider payload identity is inconsistent"
            )
        capsule_semantics = {
            canonical_json(item.get("fields"))
            for item in context_capsule.get("untrusted_suggestions") or ()
            if (
                isinstance(item, Mapping)
                and item.get("kind") == "semantic_stage_context"
                and isinstance(item.get("fields"), Mapping)
            )
        }
        prompt_semantics = {
            canonical_json(item.semantic_context)
            for item in final_context.untrusted_semantic_hints
        }
        if capsule_semantics != prompt_semantics:
            raise RuntimeBindingError(
                "Leanstral final prompt omitted or changed semantic-stage input"
            )
        expected_prompt_sha256 = final_context.prompt_sha256
        proof_text = draft.get("proof_text")
        if not isinstance(proof_text, str) or not proof_text.strip():
            raise RuntimeBindingError("Leanstral proof candidate is empty")
        proof_sha256 = hashlib.sha256(proof_text.encode("utf-8")).hexdigest()
        repair_attempt = evidence.get("repair_attempts")
        if isinstance(repair_attempt, bool) or repair_attempt not in (0, 1):
            raise RuntimeBindingError(
                "Leanstral candidate repair identity is invalid"
            )
        if repair_attempt != payload_repair_attempt:
            raise RuntimeBindingError(
                "Leanstral candidate repair identity changed during projection"
            )
        expected_request_id = "leanstral-" + hashlib.sha256(
            (
                f"{request.run_id}:{request.case_id}:"
                f"{request.input_sha256}:{repair_attempt}"
            ).encode("utf-8")
        ).hexdigest()[:48]
        expected_draft_fields = {
            "schema_version": LEANSTRAL_DRAFT_SCHEMA,
            "artifact_kind": "llm_output",
            "stage": "model_draft",
            "draft_text": proof_text,
            "request_id": expected_request_id,
            "obligation_ids": (compiled.obligation_id,),
            "canonical_source_digest": (
                f"sha256:{compiled.source_template_sha256}"
            ),
            "output_sha256": proof_sha256,
            "resource_class": "model",
            "theorem_id": compiled.theorem_name,
            "theorem_equivalence_key": theorem.get("equivalence_key"),
            "context_capsule_id": context_capsule.get("capsule_id"),
            "prompt_sha256": expected_prompt_sha256,
            "prompt_tokens": final_context.prompt_tokens,
            "proposal_kind": "proof",
            "proposal_schema": LEANSTRAL_PROOF_OUTPUT_SCHEMA,
            "decomposition": (),
            "assurance": "unverified",
            "verified": False,
            "authoritative": False,
            "proof_attempted": False,
            "proof_success": False,
            "kernel_checked": False,
            "can_mutate_canonical_source": False,
            "can_mutate_obligations": False,
            "repair_attempt": repair_attempt,
            "benchmark_request_id": f"{request.run_id}:{request.case_id}",
        }
        if any(
            draft.get(key) != value
            for key, value in expected_draft_fields.items()
        ):
            raise RuntimeBindingError(
                "Leanstral draft is not bound to the current theorem"
            )
        timeout_ms = draft.get("timeout_ms")
        if (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or timeout_ms <= 0
            or timeout_ms
            > int(LEANSTRAL_MEASURED_TIMEOUT_SECONDS * 1000)
            or draft.get("token_budget")
            != LEANSTRAL_MEASURED_MAX_NEW_TOKENS
        ):
            raise RuntimeBindingError(
                "Leanstral draft generation budget drifted"
            )
        for field_name in ("prompt_tokens", "response_tokens"):
            value = draft.get(field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RuntimeBindingError(
                    f"Leanstral draft {field_name} is invalid"
                )
        reused_artifact_ids = draft.get("reused_artifact_ids")
        if (
            not isinstance(reused_artifact_ids, Sequence)
            or isinstance(reused_artifact_ids, (str, bytes, bytearray))
            or not all(
                isinstance(item, str) and item
                for item in reused_artifact_ids
            )
        ):
            raise RuntimeBindingError(
                "Leanstral draft reused_artifact_ids is invalid"
            )
        frozen_identity = self.expected_leanstral_identity
        if frozen_identity is None:
            raise RuntimeBindingError(
                "kernel lacks the frozen Leanstral capability identity"
            )
        frozen_provider = frozen_identity.get("provider")
        frozen_model = frozen_identity.get("model")
        frozen_endpoint = frozen_identity.get("endpoint")
        if not all(
            isinstance(value, str) and value
            for value in (
                frozen_provider,
                frozen_model,
                frozen_endpoint,
            )
        ):
            raise RuntimeBindingError(
                "frozen Leanstral capability identity is incomplete"
            )
        provider = draft.get("llm_provider")
        model = draft.get("model")
        if (
            provider != frozen_provider
            or model != frozen_model
            or artifact.effective_identity.get("provider") != provider
            or artifact.effective_identity.get("model") != model
        ):
            raise RuntimeBindingError(
                "Leanstral candidate provider/model identity is mismatched"
            )
        metadata = draft.get("metadata")
        if not isinstance(metadata, Mapping):
            raise RuntimeBindingError(
                "Leanstral draft metadata is not an evidence object"
            )
        if (
            metadata.get("fixed_theorem_identity_digest")
            != theorem.get("identity_digest")
            or metadata.get("structured_output") is not True
        ):
            raise RuntimeBindingError(
                "Leanstral draft theorem identity digest is mismatched"
            )
        boundary = metadata.get("benchmark_generation_boundary")
        if not isinstance(boundary, Mapping):
            raise RuntimeBindingError(
                "Leanstral draft omitted its generation-boundary receipt"
            )
        expected_boundary_keys = {
            "schema",
            "endpoint",
            "provider",
            "requested_model",
            "response_model",
            "prompt_sha256",
            "raw_model_content_sha256",
            "raw_model_content_bytes",
            "normalized_proposal_sha256",
            "normalized_proposal_bytes",
            "normalization",
        }
        if set(boundary) != expected_boundary_keys:
            raise RuntimeBindingError(
                "Leanstral generation-boundary schema is incomplete"
            )
        normalized_proposal = json.dumps(
            {
                "schema": LEANSTRAL_PROOF_OUTPUT_SCHEMA,
                "theorem_id": compiled.theorem_name,
                "proposal_kind": "proof",
                "proof_text": proof_text,
            },
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        exact_boundary_fields = {
            "schema": LEANSTRAL_GENERATION_BOUNDARY_SCHEMA,
            "endpoint": frozen_endpoint,
            "provider": frozen_provider,
            "requested_model": frozen_model,
            "response_model": frozen_model,
            "prompt_sha256": draft.get("prompt_sha256"),
            "normalized_proposal_sha256": hashlib.sha256(
                normalized_proposal
            ).hexdigest(),
            "normalized_proposal_bytes": len(normalized_proposal),
        }
        if any(
            boundary.get(key) != value
            for key, value in exact_boundary_fields.items()
        ):
            raise RuntimeBindingError(
                "Leanstral generation receipt is not bound to the draft"
            )
        endpoint = boundary.get("endpoint")
        raw_content_bytes = boundary.get("raw_model_content_bytes")
        if (
            not isinstance(endpoint, str)
            or not re.match(r"^https?://[^/?#]+(?:[/?#]|$)", endpoint)
            or boundary.get("normalization")
            not in {"none", "strip_single_leading_by"}
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(boundary.get("raw_model_content_sha256", "")),
            )
            or isinstance(raw_content_bytes, bool)
            or not isinstance(raw_content_bytes, int)
            or raw_content_bytes <= 0
        ):
            raise RuntimeBindingError(
                "Leanstral generation-boundary receipt is invalid"
            )
        identity = {
            "schema_version": LEANSTRAL_DRAFT_SCHEMA,
            "llm_provider": provider,
            "model": model,
            "obligation_ids": [compiled.obligation_id],
            "canonical_source_digest": (
                f"sha256:{compiled.source_template_sha256}"
            ),
            "theorem_id": compiled.theorem_name,
            "theorem_equivalence_key": theorem.get("equivalence_key"),
            "context_capsule_id": context_capsule.get("capsule_id"),
            "proposal_kind": "proof",
            "prompt_sha256": draft.get("prompt_sha256"),
            "output_sha256": proof_sha256,
        }
        expected_artifact_id = "leanstral-draft-" + hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if draft.get("artifact_id") != expected_artifact_id:
            raise RuntimeBindingError(
                "Leanstral draft content identity is mismatched"
            )
        expected_trust = {
            "assurance": "unverified",
            "verified": False,
            "authoritative": False,
            "kernel_checked": False,
        }
        expected_resources = {
            "model_inference": "model",
            "kernel_check": "kernel",
        }
        evidence_without_id = {
            key: value
            for key, value in evidence.items()
            if key != "evidence_id"
        }
        if (
            evidence.get("schema") != LEANSTRAL_EVIDENCE_SCHEMA
            or evidence.get("obligation_id") != compiled.obligation_id
            or evidence.get("mode")
            != ("repair" if repair_attempt else "synthesis")
            or evidence.get("max_repair_attempts") != 1
            or evidence.get("trust") != expected_trust
            or evidence.get("resource_classes") != expected_resources
            or evidence.get("evidence_id")
            != _sha(_thaw_artifact_json(evidence_without_id))
            or artifact.output_sha256
            != _sha(_thaw_artifact_json(evidence))
        ):
            raise RuntimeBindingError(
                "Leanstral evidence digest or trust boundary is invalid"
            )
        return proof_text, artifact.digest

    def _validated_proof_candidates(
        self,
        request: StageRequest,
        compiled: CompiledObligation,
        translation: ReviewedEntailmentTranslation | None,
        compiler_candidate: Mapping[str, object] | None,
    ) -> tuple[tuple[str, str, str], ...]:
        """Return all present candidates in their frozen source-bound order."""

        candidates: list[tuple[str, str, str]] = []
        compiler = request.artifact(StageName.COMPILER)
        if compiler is not None and compiler_candidate is not None:
            proof = compiler_candidate.get("certificate")
            if isinstance(proof, str) and proof.strip():
                # The deterministic translator explicitly exposes every proof
                # it already knows. Optional backends must earn marginal value
                # beyond that subset, not preempt a known deterministic proof.
                candidates.append(
                    (StageName.COMPILER.value, proof, compiler.digest)
                )

        for stage in get_variant_definition(request.variant_id).proof_order:
            if stage is StageName.HAMMER:
                candidate = self._validated_hammer_candidate(
                    request, translation
                )
            elif stage is StageName.LEANSTRAL:
                candidate = self._validated_leanstral_candidate(
                    request, compiled
                )
            else:  # pragma: no cover - guarded by VariantDefinition
                raise RuntimeBindingError(
                    f"unsupported proof candidate source: {stage.value}"
                )
            if candidate is not None:
                proof, artifact_sha256 = candidate
                candidates.append(
                    (stage.value, proof, artifact_sha256)
                )
        return tuple(candidates)

    def __call__(self, request: StageRequest) -> StageOutput:
        try:
            (
                compiled,
                translation,
                compiler_candidate,
            ) = self._validated_compiler_binding(request)
        except RuntimeBindingError as exc:
            receipt = {
                "schema": KERNEL_RECEIPT_SCHEMA,
                "run_id": request.run_id,
                "case_id": request.case_id,
                "variant_id": request.variant_id,
                "protocol_sha256": request.protocol_sha256,
                "case_manifest_sha256": request.case_manifest_sha256,
                "input_sha256": request.input_sha256,
                "split": request.split.value,
                "cache_mode": request.cache_mode.value,
                "environment_sha256": self.environment_sha256,
                "accepted": False,
                "independent": True,
                "active_process_count": self.active_process_count,
                "reason": "compiler_binding_invalid",
            }
            receipt_sha256 = _sha(receipt)
            return StageOutput(
                status=StageStatus.FAILED,
                data={**receipt, "receipt_sha256": receipt_sha256},
                effective_identity={
                    **dict(request.requested_identity),
                    "implementation": "lean-native-kernel",
                    "executable": self.lean_path,
                },
                failure_code=FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
                failure_detail=str(exc)[:512],
                telemetry=TelemetryRecord(resource_lane=ResourceLane.KERNEL),
            )
        try:
            semantic_context = _kernel_input_semantic_context(request)
        except ProtocolContractError as exc:
            receipt = {
                "schema": KERNEL_RECEIPT_SCHEMA,
                "run_id": request.run_id,
                "case_id": request.case_id,
                "variant_id": request.variant_id,
                "protocol_sha256": request.protocol_sha256,
                "case_manifest_sha256": request.case_manifest_sha256,
                "input_sha256": request.input_sha256,
                "split": request.split.value,
                "cache_mode": request.cache_mode.value,
                "environment_sha256": self.environment_sha256,
                "accepted": False,
                "independent": True,
                "active_process_count": self.active_process_count,
                "reason": "semantic_context_binding_invalid",
            }
            receipt_sha256 = _sha(receipt)
            return StageOutput(
                status=StageStatus.FAILED,
                data={**receipt, "receipt_sha256": receipt_sha256},
                effective_identity={
                    **dict(request.requested_identity),
                    "implementation": "lean-native-kernel",
                    "executable": self.lean_path,
                },
                failure_code=FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
                failure_detail=str(exc)[:512],
                telemetry=TelemetryRecord(resource_lane=ResourceLane.KERNEL),
            )
        semantic_binding = _semantic_context_binding(semantic_context)
        semantic_receipt_fields = {
            "semantic_context_sha256": semantic_binding["context_sha256"],
            "semantic_artifact_sha256s": semantic_binding[
                "artifact_sha256s"
            ],
        }
        try:
            candidates = (
                ()
                if compiled is None
                else self._validated_proof_candidates(
                    request,
                    compiled,
                    translation,
                    compiler_candidate,
                )
            )
            # Validate and render the complete present portfolio before
            # starting Lean. A later provenance failure must not be hidden by
            # an earlier accepted candidate.
            rendered_candidates = (
                ()
                if compiled is None
                else tuple(
                    (
                        candidate_source,
                        candidate_sha256,
                        compiled.render(proof_text),
                    )
                    for (
                        candidate_source,
                        proof_text,
                        candidate_sha256,
                    ) in candidates
                )
            )
        except RuntimeBindingError as exc:
            receipt = {
                "schema": KERNEL_RECEIPT_SCHEMA,
                "run_id": request.run_id,
                "case_id": request.case_id,
                "variant_id": request.variant_id,
                "protocol_sha256": request.protocol_sha256,
                "case_manifest_sha256": request.case_manifest_sha256,
                "input_sha256": request.input_sha256,
                "split": request.split.value,
                "cache_mode": request.cache_mode.value,
                "environment_sha256": self.environment_sha256,
                "accepted": False,
                "independent": True,
                "active_process_count": self.active_process_count,
                "reason": "proof_candidate_binding_invalid",
                **semantic_receipt_fields,
            }
            receipt_sha256 = _sha(receipt)
            return StageOutput(
                status=StageStatus.FAILED,
                data={**receipt, "receipt_sha256": receipt_sha256},
                effective_identity={
                    **dict(request.requested_identity),
                    "implementation": "lean-native-kernel",
                    "executable": self.lean_path,
                },
                failure_code=FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
                failure_detail=str(exc)[:512],
                telemetry=TelemetryRecord(resource_lane=ResourceLane.KERNEL),
            )
        if compiled is None or not rendered_candidates:
            reason = (
                "no_compiled_obligation"
                if compiled is None
                else "no_proof_candidate"
            )
            receipt = {
                "schema": KERNEL_RECEIPT_SCHEMA,
                "run_id": request.run_id,
                "case_id": request.case_id,
                "variant_id": request.variant_id,
                "protocol_sha256": request.protocol_sha256,
                "case_manifest_sha256": request.case_manifest_sha256,
                "input_sha256": request.input_sha256,
                "split": request.split.value,
                "cache_mode": request.cache_mode.value,
                "environment_sha256": self.environment_sha256,
                "accepted": False,
                "independent": True,
                "active_process_count": self.active_process_count,
                "reason": reason,
                **semantic_receipt_fields,
            }
            receipt_sha256 = _sha(receipt)
            return StageOutput(
                data={**receipt, "receipt_sha256": receipt_sha256},
                effective_identity={
                    **dict(request.requested_identity),
                    "implementation": "lean-native-kernel",
                    "executable": self.lean_path,
                },
                telemetry=TelemetryRecord(resource_lane=ResourceLane.KERNEL),
            )
        assert compiled is not None
        from ipfs_datasets_py.logic.hammers.process_lifecycle import (
            ProcessKind,
            ProcessLimits,
        )

        command_sha256 = hashlib.sha256(
            "\0".join(
                (self.lean_path, "-j", "1", "Main.lean")
            ).encode("utf-8")
        ).hexdigest()
        attempts: list[dict[str, object]] = []
        total_wall_time_ms = 0.0
        total_bytes_in = 0
        total_bytes_out = 0
        infrastructure_failure: tuple[FailureCode, str] | None = None
        for attempt_index, (
            candidate_source,
            candidate_sha256,
            source,
        ) in enumerate(rendered_candidates):
            with self.supervisor.temporary_directory(
                prefix=f"hssl-{request.case_id}-a{attempt_index}-"
            ) as temporary:
                source_path = Path(temporary) / "Main.lean"
                source_path.write_text(source, encoding="utf-8")
                # Lean otherwise sizes its worker pool from the host CPU count.
                # Under the benchmark's RLIMIT_AS that can fail before parsing
                # with "failed to create thread", even for a tiny valid proof.
                # One worker is deterministic and keeps the native-kernel
                # process inside the frozen memory and process bounds.
                command = (self.lean_path, "-j", "1", str(source_path))
                result = self.supervisor.run(
                    command,
                    kind=ProcessKind.LEAN,
                    limits=ProcessLimits(
                        wall_time_seconds=self.timeout_seconds,
                        cpu_seconds=self.timeout_seconds,
                        memory_mb=self.memory_mb,
                    ),
                    cwd=temporary,
                )
            source_bytes = source.encode("utf-8")
            stdout_bytes = result.stdout.encode("utf-8")
            stderr_bytes = result.stderr.encode("utf-8")
            active_process_count = self.active_process_count
            accepted = bool(
                result.returncode == 0
                and not result.timed_out
                and not result.cancelled
                and not result.resource_exhausted
                and result.error is None
                and active_process_count == 0
            )
            attempt_body = {
                "attempt_index": attempt_index,
                "candidate_source": candidate_source,
                "candidate_artifact_sha256": candidate_sha256,
                "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "command_sha256": command_sha256,
                "stdout_sha256": hashlib.sha256(stdout_bytes).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr_bytes).hexdigest(),
                "returncode": result.returncode,
                "timed_out": result.timed_out,
                "cancelled": result.cancelled,
                "resource_exhausted": result.resource_exhausted,
                "termination_reason": result.termination_reason,
                "active_process_count": active_process_count,
                "accepted": accepted,
            }
            attempt = {
                **attempt_body,
                "attempt_sha256": _sha(attempt_body),
            }
            attempts.append(attempt)
            total_wall_time_ms += result.wall_time_seconds * 1_000
            total_bytes_in += len(source_bytes)
            total_bytes_out += len(stdout_bytes) + len(stderr_bytes)

            if (
                result.timed_out
                or result.cancelled
                or result.resource_exhausted
                or result.error is not None
                or active_process_count
            ):
                failure_code = FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE
                failure_detail = "native kernel process failed"
                if active_process_count:
                    failure_code = FailureCode.ORPHANED_CHILD
                    failure_detail = "native kernel process was not reaped"
                elif result.resource_exhausted:
                    failure_code = FailureCode.OUT_OF_MEMORY
                    failure_detail = (
                        "native kernel resource bound was exhausted"
                    )
                elif result.timed_out or result.cancelled:
                    failure_code = FailureCode.RESOURCE_LEASE_CANCELLATION
                    failure_detail = (
                        "native kernel execution timed out or was cancelled"
                    )
                infrastructure_failure = (failure_code, failure_detail)
                break
            if accepted:
                break

        selected = attempts[-1]
        selected_attempt = {
            key: selected[key]
            for key in (
                "attempt_index",
                "candidate_source",
                "candidate_artifact_sha256",
                "attempt_sha256",
                "accepted",
            )
        }
        receipt = {
            "schema": KERNEL_RECEIPT_SCHEMA,
            "run_id": request.run_id,
            "case_id": request.case_id,
            "variant_id": request.variant_id,
            "protocol_sha256": request.protocol_sha256,
            "case_manifest_sha256": request.case_manifest_sha256,
            "input_sha256": request.input_sha256,
            "split": request.split.value,
            "cache_mode": request.cache_mode.value,
            "compiled_obligation_sha256": compiled.digest,
            "obligation_sha256": compiled.obligation_sha256,
            "candidate_source": selected["candidate_source"],
            "candidate_artifact_sha256": selected[
                "candidate_artifact_sha256"
            ],
            "source_sha256": selected["source_sha256"],
            **semantic_receipt_fields,
            "environment_sha256": self.environment_sha256,
            "command_sha256": selected["command_sha256"],
            "stdout_sha256": selected["stdout_sha256"],
            "stderr_sha256": selected["stderr_sha256"],
            "returncode": selected["returncode"],
            "timed_out": selected["timed_out"],
            "cancelled": selected["cancelled"],
            "resource_exhausted": selected["resource_exhausted"],
            "termination_reason": selected["termination_reason"],
            "active_process_count": selected["active_process_count"],
            "accepted": selected["accepted"],
            "independent": True,
            "candidate_attempts": attempts,
            "candidate_attempts_sha256": _sha(attempts),
            "selected_attempt": selected_attempt,
        }
        receipt_sha256 = _sha(receipt)
        telemetry = TelemetryRecord(
            wall_time_ms=total_wall_time_ms,
            bytes_in=total_bytes_in,
            bytes_out=total_bytes_out,
            resource_lane=ResourceLane.KERNEL,
        )
        if infrastructure_failure is not None:
            failure_code, failure_detail = infrastructure_failure
            return StageOutput(
                status=StageStatus.FAILED,
                data={**receipt, "receipt_sha256": receipt_sha256},
                effective_identity={
                    **dict(request.requested_identity),
                    "implementation": "lean-native-kernel",
                    "executable": self.lean_path,
                },
                failure_code=failure_code,
                failure_detail=failure_detail,
                telemetry=telemetry,
            )
        if selected["accepted"] is not True:
            return StageOutput(
                status=StageStatus.FAILED,
                data={**receipt, "receipt_sha256": receipt_sha256},
                effective_identity={
                    **dict(request.requested_identity),
                    "implementation": "lean-native-kernel",
                    "executable": self.lean_path,
                },
                failure_code=FailureCode.KERNEL_REJECTION,
                failure_detail="native kernel rejected the proof candidate",
                telemetry=telemetry,
            )
        return StageOutput(
            data={**receipt, "receipt_sha256": receipt_sha256},
            effective_identity={
                **dict(request.requested_identity),
                "implementation": "lean-native-kernel",
                "executable": self.lean_path,
            },
            telemetry=telemetry,
            kernel_accepted=True,
            kernel_receipt_sha256=receipt_sha256,
        )


@dataclass(slots=True)
class LiveRuntime:
    """Exact per-arm adapter assembly bound to one capability inventory."""

    inventory: CapabilityInventory
    adapters: Mapping[str, Mapping[StageName, StageAdapter]]
    kernel_runner: NativeKernelRunner | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.inventory, CapabilityInventory):
            raise RuntimeBindingError("inventory must be a CapabilityInventory")
        frozen: dict[str, Mapping[StageName, StageAdapter]] = {}
        for variant_id, route in self.adapters.items():
            definition = get_variant_definition(variant_id)
            if not isinstance(route, Mapping):
                raise RuntimeBindingError("runtime routes must be mappings")
            if set(route) != set(definition.stages):
                raise RuntimeBindingError(
                    f"{variant_id} live route does not exactly match frozen stages"
                )
            for stage, adapter in route.items():
                if not isinstance(adapter, StageAdapter) or adapter.stage is not stage:
                    raise RuntimeBindingError(
                        f"{variant_id}/{stage.value} adapter binding is invalid"
                    )
                requires_handler = (
                    stage is StageName.COMPILER
                    or (
                        stage is StageName.SPACY
                        and (
                            definition.spacy_mode is SpacyMode.REGEX_LEGAL
                            or _available(
                                self.inventory,
                                CapabilityKind.SPACY_PIPELINE,
                            )
                        )
                    )
                    or (
                        stage is StageName.SYMAI
                        and _available(
                            self.inventory,
                            CapabilityKind.SYMAI,
                            CapabilityKind.LLM_ROUTER,
                        )
                    )
                    or (
                        stage is StageName.HAMMER
                        and _available(
                            self.inventory, CapabilityKind.HAMMER
                        )
                    )
                    or (
                        stage is StageName.LEANSTRAL
                        and _available(
                            self.inventory,
                            CapabilityKind.LEANSTRAL_SERVICE,
                        )
                    )
                    or (
                        stage is StageName.KERNEL
                        and _available(
                            self.inventory,
                            CapabilityKind.LEAN_TOOLCHAIN,
                        )
                    )
                )
                if requires_handler and adapter.handler is None:
                    raise RuntimeBindingError(
                        f"{variant_id}/{stage.value} available stage remained inert"
                    )
            frozen[variant_id] = MappingProxyType(dict(route))
        self.adapters = MappingProxyType(frozen)

    def close(self) -> None:
        if self.kernel_runner is not None:
            self.kernel_runner.close()

    def __enter__(self) -> "LiveRuntime":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _capability_handler(
    *,
    inventory: CapabilityInventory,
    kind: CapabilityKind,
    stage: StageName,
    injected: StageHandler | None,
    default_factory: Callable[[], StageAdapter] | None,
) -> StageAdapter:
    record = _record(inventory, kind)
    if record.status is not CapabilityStatus.AVAILABLE:
        return _unavailable_adapter(stage)
    if injected is not None:
        return {
            StageName.SPACY: SpacyAdapter,
            StageName.SYMAI: SymaiAdapter,
            StageName.HAMMER: HammerAdapter,
            StageName.LEANSTRAL: LeanstralAdapter,
            StageName.KERNEL: KernelAdapter,
        }[stage](injected)
    if default_factory is None:
        raise RuntimeBindingError(
            f"available {kind.value} capability has no live {stage.value} handler"
        )
    adapter = default_factory()
    if adapter.handler is None:
        raise RuntimeBindingError(
            f"available {kind.value} capability remained inert"
        )
    return adapter


def _hammer_input_semantic_context(
    request: StageRequest,
) -> dict[str, object]:
    """Return the exact label-blind frontend evidence bound to Hammer."""

    definition = get_variant_definition(request.variant_id)
    measured_hammer_arm = (
        _is_frozen_ablation_request(request)
        and StageName.HAMMER in definition.stages
    )
    required_present: tuple[StageName, ...] = ()
    required_success: tuple[StageName, ...] = ()
    if measured_hammer_arm and StageName.SPACY in definition.stages:
        required_present = (StageName.SPACY,)
        required_success = (StageName.SPACY,)
    if measured_hammer_arm and StageName.SYMAI in definition.stages:
        required_present = (*required_present, StageName.SYMAI)
    return build_upstream_semantic_context(
        request,
        require_present=required_present,
        require_success=required_success,
    )


def _kernel_input_semantic_context(
    request: StageRequest,
) -> dict[str, object]:
    """Return semantic evidence the terminal kernel receipt must bind."""

    definition = get_variant_definition(request.variant_id)
    measured_route = _is_frozen_ablation_request(request)
    required_present: tuple[StageName, ...] = ()
    required_success: tuple[StageName, ...] = ()
    if measured_route and StageName.SPACY in definition.stages:
        required_present = (StageName.SPACY,)
        required_success = (StageName.SPACY,)
    if measured_route and StageName.SYMAI in definition.stages:
        required_present = (*required_present, StageName.SYMAI)
    return build_upstream_semantic_context(
        request,
        require_present=required_present,
        require_success=required_success,
    )


def _reviewed_source_premises(
    request: StageRequest,
    translation: ReviewedEntailmentTranslation,
) -> tuple[tuple[dict[str, object], ...], str]:
    """Recover the exact source premises used by a reviewed translation."""

    if not isinstance(request.input_data, Mapping):
        raise RuntimeBindingError(
            "premise selection requires an object-shaped benchmark input"
        )
    raw_text = request.input_data.get(
        "text", request.input_data.get("source_text")
    )
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise RuntimeBindingError(
            "premise selection requires bounded reviewed source text"
        )
    if hashlib.sha256(raw_text.encode("utf-8")).hexdigest() != (
        translation.source_sha256
    ):
        raise RuntimeBindingError(
            "premise selection source differs from the reviewed translation"
        )
    sentences = _source_sentences(raw_text)
    expected_counts = {
        "direct_unary_entailment": 2,
        "two_step_unary_chain": 3,
        "nested_exists_forall_instantiation": 2,
        "deontic_modus_ponens": 2,
        "temporal_conditional_instantiation": 2,
        "unary_exclusion_countermodel": 2,
    }
    expected_count = expected_counts.get(translation.shape)
    if expected_count is None or len(sentences) != expected_count + 1:
        raise RuntimeBindingError(
            "reviewed translation has no exact source-premise mapping"
        )
    premises: list[dict[str, object]] = []
    for source_index, statement in enumerate(sentences[:-1]):
        statement_sha256 = hashlib.sha256(
            statement.encode("utf-8")
        ).hexdigest()
        premises.append(
            {
                "premise_id": (
                    f"source-premise-{source_index:03d}-"
                    f"{statement_sha256[:16]}"
                ),
                "source_index": source_index,
                "statement": statement,
                "statement_sha256": statement_sha256,
            }
        )
    return tuple(premises), sentences[-1]


def _stamp_premise_selection_receipt(
    body: Mapping[str, object],
) -> dict[str, object]:
    payload = dict(body)
    payload["receipt_sha256"] = _sha(payload)
    return payload


def _learned_graph_premise_selection(
    request: StageRequest,
    translation: ReviewedEntailmentTranslation,
) -> dict[str, object]:
    """Run the repository's opt-in pinned graph selector for A10."""

    from ipfs_datasets_py.logic.hammers.corpus import (
        CorpusManifest,
        CorpusSource,
    )
    from ipfs_datasets_py.logic.hammers.learned_selector import (
        LearnedSelectorConfig,
        SelectorFallbackReason,
        build_default_graph_selector_artifact,
        select_premises_gated,
    )
    from ipfs_datasets_py.logic.hammers.models import (
        HammerPolicy as NativeHammerPolicy,
        ITPKind,
    )
    from ipfs_datasets_py.logic.hammers.premise_selection import GoalFeatures

    premises, conclusion = _reviewed_source_premises(request, translation)
    artifact = build_default_graph_selector_artifact()
    manifest = CorpusManifest(
        manifest_id="hssl-reviewed-source-premises-v1",
        metadata={
            "translation_sha256": translation.digest,
            "source_sha256": translation.source_sha256,
        },
    )
    corpus_id = "hssl-reviewed-source-v1"
    manifest.register_source(
        CorpusSource(
            corpus_id=corpus_id,
            name="HSSL reviewed source premises",
            source_itp=ITPKind.LEAN,
            version_ref=f"sha256:{translation.source_sha256}",
            license_id="LicenseRef-HSSL-Benchmark-Fixture",
            description=(
                "Ephemeral content-addressed source-premise view for the "
                "frozen A10 graph-selector ablation."
            ),
        )
    )
    for premise in premises:
        manifest.add_theorem(
            theorem_id=str(premise["premise_id"]),
            corpus_id=corpus_id,
            statement=str(premise["statement"]),
            metadata={
                "source_index": premise["source_index"],
                "source_sha256": translation.source_sha256,
            },
        )
    goal = GoalFeatures.from_statement(conclusion)
    result = select_premises_gated(
        manifest,
        goal,
        top_k=len(premises),
        policy=NativeHammerPolicy(
            allow_learned_premise_selector=True,
            max_premises=len(premises),
        ),
        learned_config=LearnedSelectorConfig(
            enabled=True,
            model_path="in-memory:pinned-default-graph-selector",
            pinned_model_digest=artifact.model_digest,
        ),
        model_artifact=artifact,
    )
    if (
        not result.used_learned_selector
        or result.fallback_reason is not SelectorFallbackReason.NONE
        or result.selection is None
        or len(result.selection.selected) != len(premises)
    ):
        raise RuntimeBindingError(
            "A10 pinned graph selector did not execute without fallback"
        )
    by_id = {str(item["premise_id"]): item for item in premises}
    selected: list[dict[str, object]] = []
    for ranked in result.selection.selected:
        source = by_id.get(ranked.premise_id)
        if source is None:
            raise RuntimeBindingError(
                "A10 graph selector returned an unknown source premise"
            )
        selected.append(
            {
                "premise_id": ranked.premise_id,
                "rank": ranked.rank,
                "score": ranked.score,
                "source_index": source["source_index"],
                "statement_sha256": source["statement_sha256"],
            }
        )
    candidate_projection = [
        {
            "premise_id": item["premise_id"],
            "source_index": item["source_index"],
            "statement_sha256": item["statement_sha256"],
        }
        for item in premises
    ]
    return _stamp_premise_selection_receipt(
        {
            "schema": HAMMER_PREMISE_SELECTION_SCHEMA,
            "policy": HammerPolicy.LEARNED_SELECTOR.value,
            "ranking_contract": HAMMER_GRAPH_SELECTOR_CONTRACT,
            "translation_sha256": translation.digest,
            "source_sha256": translation.source_sha256,
            "obligation_sha256": translation.obligation_sha256,
            "candidate_set_sha256": _sha(candidate_projection),
            "candidate_count": len(premises),
            "corpus_revision": manifest.revision,
            "top_k": len(premises),
            "selection_method": result.selection.selection_method,
            "model_id": result.model_id,
            "model_digest": result.model_digest,
            "feature_version": result.feature_version,
            "used_learned_selector": True,
            "fallback_reason": result.fallback_reason.value,
            "selected": selected,
        }
    )


_RANKING_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


def _collect_symai_ranking_strings(
    value: object,
    *,
    depth: int = 0,
) -> tuple[str, ...]:
    """Collect bounded semantic strings from a validated SyMAI candidate."""

    if depth > 8:
        return ()
    if isinstance(value, str):
        return (value[:256],)
    if isinstance(value, Mapping):
        strings: list[str] = []
        for key in sorted(value):
            strings.extend(
                _collect_symai_ranking_strings(value[key], depth=depth + 1)
            )
            if len(strings) >= 256:
                break
        return tuple(strings[:256])
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        strings = []
        for item in value[:256]:
            strings.extend(
                _collect_symai_ranking_strings(item, depth=depth + 1)
            )
            if len(strings) >= 256:
                break
        return tuple(strings[:256])
    return ()


def _symai_premise_selection(
    request: StageRequest,
    translation: ReviewedEntailmentTranslation,
) -> dict[str, object]:
    """Rank exact source premises from the frozen SyMAI semantic artifact."""

    premises, _conclusion = _reviewed_source_premises(request, translation)
    symai = request.artifact(StageName.SYMAI)
    if symai is None or symai.status is not StageStatus.SUCCESS:
        raise RuntimeBindingError(
            "A11 premise ranking requires a successful SyMAI stage artifact"
        )
    semantic_strings: tuple[str, ...] = ()
    if symai.invoked:
        if (
            not isinstance(symai.data, Mapping)
            or symai.data.get("schema") != (
                "ipfs-datasets.logic-pipeline-benchmark.symai-evidence.v1"
            )
            or not isinstance(symai.data.get("candidate_ir"), Mapping)
            or symai.data.get("candidate_ir_sha256")
            != _sha(
                _thaw_artifact_json(symai.data.get("candidate_ir"))
            )
        ):
            raise RuntimeBindingError(
                "A11 premise ranking requires validated SyMAI semantic evidence"
            )
        semantic_strings = _collect_symai_ranking_strings(
            {
                "candidate_ir": symai.data.get("candidate_ir"),
                "normalized_predicates": symai.data.get(
                    "normalized_predicates", ()
                ),
                "quantifiers": symai.data.get("quantifiers", ()),
                "entities": symai.data.get("entities", ()),
                "ambiguity_flags": symai.data.get("ambiguity_flags", ()),
            }
        )
    elif (
        not isinstance(symai.data, Mapping)
        or symai.data.get("invoked") is not False
        or symai.policy_reason != "frontend_ambiguity_gate_closed"
    ):
        raise RuntimeBindingError(
            "A11 non-invoked SyMAI artifact is not an ambiguity-gate receipt"
        )

    semantic_terms = frozenset(
        token.casefold()
        for value in semantic_strings
        for token in _RANKING_TOKEN.findall(value)
    )
    ranked: list[tuple[int, int, str, dict[str, object]]] = []
    for premise in premises:
        premise_terms = frozenset(
            token.casefold()
            for token in _RANKING_TOKEN.findall(str(premise["statement"]))
        )
        overlap = len(premise_terms & semantic_terms)
        union = len(premise_terms | semantic_terms)
        basis_points = 0 if union == 0 else (10_000 * overlap) // union
        ranked.append(
            (
                overlap,
                basis_points,
                str(premise["premise_id"]),
                premise,
            )
        )
    if symai.invoked:
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
        ranking_contract = HAMMER_SYMAI_RANKING_CONTRACT
    else:
        ranked.sort(key=lambda item: int(item[3]["source_index"]))
        ranking_contract = "ambiguity-gate-closed-source-order-v1"
    selected = [
        {
            "premise_id": item[2],
            "rank": rank,
            "overlap_count": item[0],
            "overlap_basis_points": item[1],
            "source_index": item[3]["source_index"],
            "statement_sha256": item[3]["statement_sha256"],
        }
        for rank, item in enumerate(ranked)
    ]
    candidate_projection = [
        {
            "premise_id": item["premise_id"],
            "source_index": item["source_index"],
            "statement_sha256": item["statement_sha256"],
        }
        for item in premises
    ]
    return _stamp_premise_selection_receipt(
        {
            "schema": HAMMER_PREMISE_SELECTION_SCHEMA,
            "policy": PremiseRanking.SYMAI_LLM.value,
            "ranking_contract": ranking_contract,
            "translation_sha256": translation.digest,
            "source_sha256": translation.source_sha256,
            "obligation_sha256": translation.obligation_sha256,
            "candidate_set_sha256": _sha(candidate_projection),
            "candidate_count": len(premises),
            "top_k": len(premises),
            "symai_invoked": symai.invoked,
            "symai_artifact_sha256": symai.digest,
            "symai_output_sha256": symai.output_sha256,
            "symai_identity_sha256": _sha(
                {
                    key: symai.effective_identity.get(key)
                    for key in (
                        "provider",
                        "model",
                        "effective_provider",
                        "effective_model",
                    )
                    if key in symai.effective_identity
                }
            ),
            "semantic_signal_sha256": _sha(sorted(semantic_terms)),
            "semantic_term_count": len(semantic_terms),
            "selected": selected,
        }
    )


def _hammer_premise_selection(
    request: StageRequest,
    translation: ReviewedEntailmentTranslation,
) -> dict[str, object] | None:
    if request.variant_id == "A10":
        return _learned_graph_premise_selection(request, translation)
    if request.variant_id == "A11":
        return _symai_premise_selection(request, translation)
    return None


def _ranked_hammer_problem(
    translation: ReviewedEntailmentTranslation,
    premise_selection: Mapping[str, object] | None,
) -> str:
    """Apply a verified complete ranking to the solver's premise assertions."""

    if premise_selection is None:
        return translation.smt2_problem
    expected_assertions = {
        "direct_unary_entailment": (
            "(assert (=> premise target))",
            "(assert premise)",
            "(assert (not target))",
        ),
        "two_step_unary_chain": (
            "(assert (=> premise middle))",
            "(assert (=> middle target))",
            "(assert premise)",
            "(assert (not target))",
        ),
        "nested_exists_forall_instantiation": (
            "(assert (=> rule_at_scope target))",
            "(assert rule_at_scope)",
            "(assert (not target))",
        ),
        "deontic_modus_ponens": (
            "(assert (=> premise target))",
            "(assert premise)",
            "(assert (not target))",
        ),
        "temporal_conditional_instantiation": (
            "(assert (=> premise target))",
            "(assert premise)",
            "(assert (not target))",
        ),
        "unary_exclusion_countermodel": (
            "(assert (=> premise (not target)))",
            "(assert premise)",
            "(assert target)",
        ),
    }.get(translation.shape)
    lines = translation.smt2_problem.splitlines()
    actual_assertions = tuple(
        line for line in lines if line.startswith("(assert ")
    )
    if expected_assertions is None or actual_assertions != expected_assertions:
        raise RuntimeBindingError(
            "premise ranking cannot map the reviewed solver assertions"
        )
    selected = premise_selection.get("selected")
    if not isinstance(selected, Sequence) or isinstance(
        selected, (str, bytes, bytearray)
    ):
        raise RuntimeBindingError(
            "premise-selection receipt omitted its selected order"
        )
    source_indices: list[int] = []
    for item in selected:
        if (
            not isinstance(item, Mapping)
            or isinstance(item.get("source_index"), bool)
            or not isinstance(item.get("source_index"), int)
        ):
            raise RuntimeBindingError(
                "premise-selection receipt has an invalid source index"
            )
        source_indices.append(int(item["source_index"]))
    premise_count = len(expected_assertions) - 1
    if sorted(source_indices) != list(range(premise_count)):
        raise RuntimeBindingError(
            "premise-selection receipt is not a complete source permutation"
        )
    first_assertion = lines.index(expected_assertions[0])
    prefix = lines[:first_assertion]
    suffix = lines[first_assertion + len(expected_assertions) :]
    ranked_assertions = [
        expected_assertions[index] for index in source_indices
    ]
    return "\n".join(
        [*prefix, *ranked_assertions, expected_assertions[-1], *suffix, ""]
    )


def _hammer_live_handler(record: CapabilityRecord) -> StageHandler:
    """Prove a source-bound translation before emitting a Lean candidate.

    Unsupported natural language never reaches the solver.  For a supported
    translation, cvc5 checks the premises together with the negated conclusion;
    only ``unsat`` authorizes the corresponding deterministic reconstruction
    to become an untrusted candidate for the independent Lean kernel.
    """

    solver_path = record.identity.get("solver_path")
    if not isinstance(solver_path, str) or not solver_path:
        raise RuntimeBindingError(
            "available Hammer has no live hammer handler: identity lacks "
            "solver_path"
        )

    def invoke(request: StageRequest) -> StageOutput:
        started = time.perf_counter()
        try:
            semantic_context = _hammer_input_semantic_context(request)
        except ProtocolContractError as exc:
            return StageOutput(
                status=StageStatus.FAILED,
                effective_identity=request.requested_identity,
                failure_code=FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
                failure_detail=str(exc)[:512],
                telemetry=TelemetryRecord(resource_lane=ResourceLane.SOLVER),
            )
        semantic_binding = _semantic_context_binding(semantic_context)
        compiler = request.artifact(StageName.COMPILER)
        compiled: CompiledObligation | None = None
        if (
            compiler is not None
            and compiler.invoked
            and compiler.status is StageStatus.SUCCESS
            and isinstance(compiler.data, Mapping)
            and compiler.data.get("compiled_obligation") is not None
        ):
            try:
                compiled = CompiledObligation.from_dict(
                    compiler.data["compiled_obligation"]
                )
            except RuntimeBindingError as exc:
                return StageOutput(
                    status=StageStatus.FAILED,
                    effective_identity=request.requested_identity,
                    failure_code=FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
                    failure_detail=str(exc)[:512],
                    telemetry=TelemetryRecord(resource_lane=ResourceLane.SOLVER),
                )
        translation = (
            None
            if compiled is None
            else _entailment_translation(
                request.input_data,
                theorem_name=compiled.theorem_name,
                obligation_sha256=compiled.obligation_sha256,
                kind=compiled.kind,
                logic=compiled.logic,
                semantic_target=compiled.semantic_target,
            )
        )
        if translation is None:
            return StageOutput(
                data={
                    "schema": (
                        "ipfs-datasets.logic-pipeline-benchmark."
                        "hammer-translation-terminal.v1"
                    ),
                    "case_input_sha256": request.input_sha256,
                    "translation_status": "unsupported",
                    "solver_status": "not_invoked",
                    "candidate_created": False,
                    "efficacy_observed": False,
                    "reason": "reviewed_source_not_in_sound_translation_subset",
                    "semantic_context": semantic_binding,
                },
                effective_identity={
                    **dict(request.requested_identity),
                    "implementation": record.identity.get("implementation"),
                    "solver": record.identity.get("solver"),
                    "solver_path": solver_path,
                    "translation": "reviewed-entailment-v1",
                    "semantic_context_sha256": semantic_context[
                        "context_sha256"
                    ],
                },
                telemetry=TelemetryRecord(
                    input_items=1,
                    output_items=1,
                    bytes_in=request.input_bytes,
                    resource_lane=ResourceLane.SOLVER,
                ),
            )
        recorded_translation = (
            compiler.data.get("entailment_translation")
            if compiler is not None and isinstance(compiler.data, Mapping)
            else None
        )
        recorded_digest = (
            compiler.data.get("entailment_translation_sha256")
            if compiler is not None and isinstance(compiler.data, Mapping)
            else None
        )
        if (
            recorded_translation != translation.to_dict()
            or recorded_digest != translation.digest
            or compiled is None
            or compiled.source_template != translation.source_template
        ):
            return StageOutput(
                status=StageStatus.FAILED,
                effective_identity=request.requested_identity,
                failure_code=FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
                failure_detail="compiler and Hammer entailment translations differ",
                telemetry=TelemetryRecord(resource_lane=ResourceLane.SOLVER),
            )
        try:
            premise_selection = _hammer_premise_selection(
                request, translation
            )
            source = _ranked_hammer_problem(
                translation, premise_selection
            )
        except (RuntimeBindingError, ValueError) as exc:
            return StageOutput(
                status=StageStatus.FAILED,
                effective_identity=request.requested_identity,
                failure_code=FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
                failure_detail=(
                    f"Hammer premise selection failed: {exc}"
                )[:512],
                telemetry=TelemetryRecord(resource_lane=ResourceLane.SOLVER),
            )
        try:
            process = run_bounded_process_group(
                (solver_path, "--lang=smt2"),
                timeout_seconds=5.0,
                max_output_bytes=4096,
                env=None,
                input_bytes=source.encode("utf-8"),
            )
        except Exception as exc:
            return StageOutput(
                status=StageStatus.FAILED,
                effective_identity=request.requested_identity,
                failure_code=FailureCode.SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE,
                failure_detail=f"Hammer solver launch failed: {type(exc).__name__}",
                telemetry=TelemetryRecord(
                    wall_time_ms=(time.perf_counter() - started) * 1000,
                    bytes_in=len(source.encode("utf-8")),
                    resource_lane=ResourceLane.SOLVER,
                ),
            )
        stdout_lines = [
            line.strip().casefold()
            for line in process.stdout.splitlines()
            if line.strip()
        ]
        solver_status = (
            stdout_lines[0]
            if stdout_lines and stdout_lines[0] in {"sat", "unsat", "unknown"}
            else "inconclusive"
        )
        candidate_created = bool(
            solver_status == "unsat"
            and process.returncode == 0
            and not process.timed_out
            and process.process_group_reaped
        )
        proof_text = (
            translation.hammer_proof_text if candidate_created else None
        )
        return StageOutput(
            data={
                "schema": (
                    "ipfs-datasets.logic-pipeline-benchmark."
                    "hammer-translated-entailment.v1"
                ),
                "case_input_sha256": request.input_sha256,
                "translation_status": "success",
                "translation_sha256": translation.digest,
                "translation_shape": translation.shape,
                "source_sha256": translation.source_sha256,
                "obligation_sha256": translation.obligation_sha256,
                "solver_status": solver_status,
                "solver_command_sha256": hashlib.sha256(
                    f"{solver_path}\0--lang=smt2".encode("utf-8")
                ).hexdigest(),
                "solver_input_sha256": hashlib.sha256(
                    source.encode("utf-8")
                ).hexdigest(),
                "stdout_sha256": hashlib.sha256(
                    process.stdout.encode("utf-8")
                ).hexdigest(),
                "stderr_sha256": hashlib.sha256(
                    process.stderr.encode("utf-8")
                ).hexdigest(),
                "timed_out": process.timed_out,
                "process_group_reaped": process.process_group_reaped,
                "proof_success": candidate_created,
                "proof_text": proof_text,
                "candidate_created": candidate_created,
                "native_reconstruction": (
                    None
                    if proof_text is None
                    else {
                        "strategy": translation.shape,
                        "certificate_sha256": hashlib.sha256(
                            proof_text.encode("utf-8")
                        ).hexdigest(),
                        "authoritative": False,
                        "requires_independent_kernel": True,
                    }
                ),
                "efficacy_observed": False,
                "semantic_context": semantic_binding,
                **(
                    {}
                    if premise_selection is None
                    else {"premise_selection": premise_selection}
                ),
            },
            effective_identity={
                **dict(request.requested_identity),
                "implementation": record.identity.get("implementation"),
                "solver": record.identity.get("solver"),
                "solver_path": solver_path,
                "translation": "reviewed-entailment-v1",
                "semantic_context_sha256": semantic_context[
                    "context_sha256"
                ],
                **(
                    {}
                    if premise_selection is None
                    else {
                        "premise_selection_sha256": premise_selection[
                            "receipt_sha256"
                        ],
                        "premise_ranking_contract": premise_selection[
                            "ranking_contract"
                        ],
                    }
                ),
            },
            telemetry=TelemetryRecord(
                wall_time_ms=(time.perf_counter() - started) * 1000,
                input_items=1,
                output_items=1,
                bytes_in=len(source.encode("utf-8")),
                bytes_out=len(process.stdout.encode("utf-8"))
                + len(process.stderr.encode("utf-8")),
                resource_lane=ResourceLane.SOLVER,
            ),
        )

    return invoke


def _legacy_symai_unavailable(request: StageRequest) -> StageOutput:
    """Retain S1 as a distinct diagnostic when no legacy identity was frozen."""

    return StageOutput(
        status=StageStatus.UNAVAILABLE,
        data={
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark."
                "legacy-symai-terminal.v1"
            ),
            "diagnostic_only": True,
            "authority_withheld": True,
            "reason": "legacy_symbolicai_identity_not_in_repaired_freeze",
        },
        effective_identity={
            **dict(request.requested_identity),
            "diagnostic_only": True,
            "legacy_identity_frozen": False,
        },
        failure_code=FailureCode.CAPABILITY_UNAVAILABLE,
        failure_detail=(
            "S1 legacy SymbolicAI identity was not part of the repaired "
            "capability freeze and cannot be substituted"
        ),
        telemetry=TelemetryRecord(resource_lane=ResourceLane.MODEL),
    )


def _configured_symai_engine_factory(
    state_directory: Path,
) -> Callable[[SymaiAdapterConfig, str], object]:
    """Import SyMAI against a run-scoped non-secret configuration."""

    config_root = state_directory / "symai-runtime"
    config_path = config_root / ".symai" / "symai.config.json"

    def factory(config: SymaiAdapterConfig, namespace: str) -> object:
        config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        value = {
            "NEUROSYMBOLIC_ENGINE_API_KEY": "ipfs",
            "NEUROSYMBOLIC_ENGINE_MODEL": f"ipfs:{config.model}",
            "SYMBOLIC_ENGINE": "ipfs",
        }
        raw = canonical_json(value) + "\n"
        if config_path.exists():
            if config_path.read_text(encoding="utf-8") != raw:
                raise RuntimeBindingError("run-scoped SyMAI configuration drifted")
        else:
            with config_path.open("x", encoding="utf-8") as handle:
                handle.write(raw)
        original_prefix = sys.prefix
        try:
            sys.prefix = str(config_root)
            importlib.import_module("symai")
        finally:
            sys.prefix = original_prefix
        engine_module = importlib.import_module(
            "ipfs_datasets_py.utils.symai_ipfs_engine"
        )
        engine_type = getattr(
            engine_module, "IPFSSyMAINeurosymbolicEngine", None
        )
        if not isinstance(engine_type, type):
            raise ImportError("IPFSSyMAINeurosymbolicEngine is unavailable")
        return engine_type(
            "neurosymbolic",
            "NEUROSYMBOLIC_ENGINE_MODEL",
            provider=config.provider,
            cache_namespace=namespace,
            allow_local_fallback=False,
            dry_run=config.dry_run,
            cache_enabled=(
                config.cache_enabled and namespace.endswith("/cache/warm")
            ),
            model_name=config.model,
            route_binding={
                "resolved_provider_name": config.expected_inner_provider,
                "resolved_model_name": config.expected_inner_model,
                "service_endpoint": config.expected_inner_endpoint,
                "routing_backend": config.expected_inner_backend,
            },
        )

    return factory


def build_live_runtime(
    inventory: CapabilityInventory,
    handlers: RuntimeBackendHandlers = RuntimeBackendHandlers(),
    *,
    variant_ids: Sequence[str] = ALL_VARIANT_IDS,
    state_directory: str | Path | None = None,
    kernel_timeout_seconds: float = 30.0,
    leanstral_timeout_seconds: float = LEANSTRAL_MEASURED_TIMEOUT_SECONDS,
    leanstral_max_new_tokens: int = LEANSTRAL_MEASURED_MAX_NEW_TOKENS,
) -> LiveRuntime:
    """Build exact live adapters for every requested frozen arm.

    Available capabilities must bind a callable handler.  Degraded or
    unavailable capabilities remain explicit unavailable adapters; they are
    never replaced with another provider or arm.
    """

    if not isinstance(inventory, CapabilityInventory):
        raise RuntimeBindingError("inventory must be a CapabilityInventory")
    if not isinstance(handlers, RuntimeBackendHandlers):
        raise RuntimeBindingError("handlers must be RuntimeBackendHandlers")
    if inventory.run_id.strip() == "":
        raise RuntimeBindingError("inventory run_id is empty")
    variants = tuple(variant_ids)
    if not variants or len(set(variants)) != len(variants):
        raise RuntimeBindingError("variant_ids must be nonempty and unique")
    for variant_id in variants:
        get_variant_definition(variant_id)

    kernel_runner: NativeKernelRunner | None = None
    if handlers.kernel is None and _available(
        inventory, CapabilityKind.LEAN_TOOLCHAIN
    ):
        lean_identity = _record(
            inventory, CapabilityKind.LEAN_TOOLCHAIN
        ).identity
        lean = lean_identity.get("lean")
        path = (
            lean.get("path")
            if isinstance(lean, Mapping)
            else lean_identity.get("lean_path")
        )
        if not isinstance(path, str) or not path:
            raise RuntimeBindingError(
                "available Lean toolchain lacks an executable path"
            )
        kernel_runner = NativeKernelRunner(
            path,
            inventory.sha256,
            Path(state_directory or ".hssl-runtime-processes")
            / inventory.run_id,
            timeout_seconds=kernel_timeout_seconds,
            expected_hammer_identity=(
                _record(inventory, CapabilityKind.HAMMER).identity
                if _available(inventory, CapabilityKind.HAMMER)
                else None
            ),
            expected_leanstral_identity=(
                _record(
                    inventory, CapabilityKind.LEANSTRAL_SERVICE
                ).identity
                if _available(
                    inventory, CapabilityKind.LEANSTRAL_SERVICE
                )
                else None
            ),
        )

    routes: dict[str, Mapping[StageName, StageAdapter]] = {}
    for variant_id in variants:
        definition = get_variant_definition(variant_id)
        route: dict[StageName, StageAdapter] = {}
        for stage in definition.stages:
            if stage is StageName.COMPILER:
                route[stage] = CompilerAdapter(
                    handlers.compiler or _current_compiler_handler
                )
            elif stage is StageName.SPACY:
                if definition.spacy_mode is SpacyMode.REGEX_LEGAL:
                    route[stage] = (
                        SpacyAdapter(handlers.spacy)
                        if handlers.spacy is not None
                        else SpacyAdapter(
                            config=SpacyAdapterConfig(
                                mode=SpacyAdapterMode.REGEX_LEGAL
                            )
                        )
                    )
                else:
                    requested = _record(
                        inventory, CapabilityKind.SPACY_PIPELINE
                    ).identity.get("requested_model", "en_core_web_sm")
                    route[stage] = _capability_handler(
                        inventory=inventory,
                        kind=CapabilityKind.SPACY_PIPELINE,
                        stage=stage,
                        injected=handlers.spacy,
                        default_factory=lambda mode=definition.spacy_mode, requested=requested: SpacyAdapter(
                            config=SpacyAdapterConfig(
                                requested_model=str(requested),
                                mode=_spacy_mode(mode),
                            )
                        ),
                    )
            elif stage is StageName.SYMAI:
                injected = (
                    handlers.legacy_symai
                    if definition.symai_policy is StagePolicy.LEGACY_DIAGNOSTIC
                    else handlers.symai
                )
                symai_record = _record(inventory, CapabilityKind.SYMAI)
                router_record = _record(inventory, CapabilityKind.LLM_ROUTER)
                leanstral_record = _record(
                    inventory, CapabilityKind.LEANSTRAL_SERVICE
                )
                if not _available(
                    inventory,
                    CapabilityKind.SYMAI,
                    CapabilityKind.LLM_ROUTER,
                    CapabilityKind.LEANSTRAL_SERVICE,
                ):
                    route[stage] = _unavailable_adapter(stage)
                elif injected is not None:
                    route[stage] = SymaiAdapter(injected)
                elif definition.symai_policy is StagePolicy.LEGACY_DIAGNOSTIC:
                    route[stage] = SymaiAdapter(_legacy_symai_unavailable)
                else:
                    provider = symai_record.identity.get(
                        "requested_provider",
                        symai_record.identity.get(
                            "provider",
                            router_record.identity.get(
                                "requested_provider",
                                router_record.identity.get("provider"),
                            ),
                        ),
                    )
                    model = symai_record.identity.get(
                        "requested_model",
                        symai_record.identity.get(
                            "model",
                            router_record.identity.get(
                                "requested_model",
                                router_record.identity.get("model"),
                            ),
                        ),
                    )
                    if not isinstance(provider, str) or not isinstance(model, str):
                        raise RuntimeBindingError(
                            "available SyMAI/router identity is incomplete"
                        )
                    inner_provider = leanstral_record.identity.get("provider")
                    inner_model = leanstral_record.identity.get("model")
                    inner_endpoint = leanstral_record.identity.get("endpoint")
                    inner_backend = leanstral_record.identity.get(
                        "routing_backend"
                    )
                    if not all(
                        isinstance(value, str) and value.strip()
                        for value in (
                            inner_provider,
                            inner_model,
                            inner_endpoint,
                            inner_backend,
                        )
                    ):
                        raise RuntimeBindingError(
                            "available Leanstral inner route identity is incomplete"
                        )
                    route[stage] = SymaiAdapter(
                        config=SymaiAdapterConfig(
                            provider=provider,
                            model=model,
                            expected_inner_provider=inner_provider,
                            expected_inner_model=inner_model,
                            expected_inner_endpoint=inner_endpoint,
                            expected_inner_backend=inner_backend,
                        ),
                        engine_factory=_configured_symai_engine_factory(
                            Path(state_directory or ".hssl-runtime-processes")
                            / inventory.run_id
                        ),
                    )
            elif stage is StageName.HAMMER:
                selected_hammer = handlers.hammer
                if definition.hammer_policy is HammerPolicy.LEARNED_SELECTOR:
                    selected_hammer = handlers.learned_hammer
                elif (
                    definition.premise_ranking
                    is PremiseRanking.SYMAI_LLM
                ):
                    selected_hammer = handlers.premise_ranked_hammer
                route[stage] = _capability_handler(
                    inventory=inventory,
                    kind=CapabilityKind.HAMMER,
                    stage=stage,
                    injected=selected_hammer,
                    default_factory=lambda: HammerAdapter(
                        _hammer_live_handler(
                            _record(inventory, CapabilityKind.HAMMER)
                        )
                    ),
                )
            elif stage is StageName.LEANSTRAL:
                leanstral_record = _record(
                    inventory, CapabilityKind.LEANSTRAL_SERVICE
                )
                route[stage] = _capability_handler(
                    inventory=inventory,
                    kind=CapabilityKind.LEANSTRAL_SERVICE,
                    stage=stage,
                    injected=handlers.leanstral,
                    default_factory=lambda record=leanstral_record: (
                        _leanstral_live_adapter(
                            record,
                            timeout_seconds=leanstral_timeout_seconds,
                            max_new_tokens=leanstral_max_new_tokens,
                        )
                    ),
                )
            elif stage is StageName.KERNEL:
                injected_kernel = (
                    None
                    if handlers.kernel is None
                    else _validated_kernel_handler(handlers.kernel)
                )
                route[stage] = _capability_handler(
                    inventory=inventory,
                    kind=CapabilityKind.LEAN_TOOLCHAIN,
                    stage=stage,
                    injected=injected_kernel,
                    default_factory=(
                        None
                        if kernel_runner is None
                        else lambda runner=kernel_runner: KernelAdapter(
                            _validated_kernel_handler(runner)
                        )
                    ),
                )
        routes[variant_id] = MappingProxyType(route)
    return LiveRuntime(inventory, MappingProxyType(routes), kernel_runner)


def build_live_adapters(
    inventory: CapabilityInventory,
    handlers: RuntimeBackendHandlers = RuntimeBackendHandlers(),
    **kwargs: object,
) -> Mapping[str, Mapping[StageName, StageAdapter]]:
    """Compatibility factory returning the strict per-variant adapter map."""

    return build_live_runtime(inventory, handlers, **kwargs).adapters


def _probe_cli(args: argparse.Namespace) -> int:
    from .capability_reprobe import (
        CapabilityFreezeError,
        freeze_live_capability_reprobe,
        run_live_capability_reprobe,
        validate_capability_snapshot,
        validate_frozen_capability_reprobe,
    )

    requested = [
        item.strip() for item in (args.require or "").split(",") if item.strip()
    ]
    duplicates = sorted({item for item in requested if requested.count(item) > 1})
    unknown = sorted(set(requested) - {kind.value for kind in CapabilityKind})
    if duplicates:
        raise RuntimeBindingError(
            f"duplicate required capabilities: {duplicates}"
        )
    if unknown:
        raise RuntimeBindingError(f"unknown required capabilities: {unknown}")
    try:
        if args.validate_freeze:
            reprobe = validate_frozen_capability_reprobe(
                repository_root=args.repository_root,
                expected_run_id=args.run_id,
                benchmark_root=args.benchmark_root,
                baseline_manifest=args.baseline_manifest,
                receipt_directory=args.receipt_directory,
            )
            validate_capability_snapshot(
                repository_root=args.repository_root,
                expected_run_id=args.run_id,
                benchmark_root=args.benchmark_root,
                receipt_directory=args.receipt_directory,
                snapshot_path=args.snapshot,
            )
        else:
            reprobe = run_live_capability_reprobe(
                repository_root=args.repository_root,
                run_id=args.run_id,
                benchmark_root=args.benchmark_root,
                baseline_manifest=args.baseline_manifest,
                legacy_probe=probe_runtime_capabilities,
            )
        # The six names in the operator command are the optional backends.
        # Eligibility always checks cache, scheduler, and native kernel too;
        # callers cannot weaken the matrix boundary by omitting them here.
        required = tuple(
            CapabilityKind(item) for item in requested
        ) or tuple(CapabilityKind)
        from .capabilities import require_capabilities

        require_capabilities(reprobe.inventory, required)
        if args.freeze:
            freeze_live_capability_reprobe(
                reprobe,
                repository_root=args.repository_root,
                benchmark_root=args.benchmark_root,
                baseline_manifest=args.baseline_manifest,
                receipt_directory=args.receipt_directory,
                snapshot_path=args.snapshot,
            )
    except (CapabilityFreezeError, CapabilityContractError) as exc:
        print(
            canonical_json(
                {
                    "schema": (
                        "ipfs-datasets.logic-pipeline-benchmark."
                        "capability-probe-failure.v1"
                    ),
                    "run_id": args.run_id,
                    "status": "ineligible",
                    "reason": str(exc),
                }
            )
        )
        return 1
    print(canonical_json(reprobe.inventory.to_dict()))
    return 0


def _execute_cli(args: argparse.Namespace) -> int:
    from . import matrix_reassessment
    from .ablation import AblationValidationError
    from .contracts import CacheMode, Split

    split_values = tuple(
        item.strip() for item in args.splits.split(",") if item.strip()
    )
    try:
        splits = tuple(Split(item) for item in split_values)
    except ValueError as exc:
        raise RuntimeBindingError("execute contains an unsupported split") from exc
    if args.cache_mode == "both":
        cache_modes = (CacheMode.COLD, CacheMode.WARM)
    else:
        try:
            cache_modes = (CacheMode(args.cache_mode),)
        except ValueError as exc:
            raise RuntimeBindingError(
                "execute contains an unsupported cache mode"
            ) from exc
    if not args.validate_complete:
        raise RuntimeBindingError(
            "matrix execution requires --validate-complete"
        )
    try:
        result = matrix_reassessment.execute_reassessment_matrix(
            repository_root=args.repository_root,
            run_id=args.run_id,
            benchmark_root=args.benchmark_root,
            receipt_directory=args.receipt_directory,
            baseline_manifest=args.baseline_manifest,
            output_root=(
                None if args.output_root is None else Path(args.output_root)
            ),
            snapshot_path=(
                None if args.snapshot is None else Path(args.snapshot)
            ),
            splits=splits,
            cache_modes=cache_modes,
            seed=args.seed,
            resume=True,
        )
    except (
        matrix_reassessment.MatrixReassessmentError,
        AblationValidationError,
        CapabilityContractError,
        ProtocolContractError,
        RuntimeBindingError,
    ) as exc:
        print(
            canonical_json(
                {
                    "schema": (
                        "ipfs-datasets.logic-pipeline-benchmark."
                        "reassessment-matrix-failure.v1"
                    ),
                    "run_id": args.run_id,
                    "status": "incomplete",
                    "reason": str(exc),
                }
            )
        )
        return 1
    print(canonical_json(dict(result)))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Frozen logic-pipeline live runtime"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    probe = subparsers.add_parser("probe")
    probe.add_argument("--run-id", default="reassessment-v2")
    probe.add_argument("--require", default="")
    probe.add_argument("--repository-root", default=".")
    probe.add_argument(
        "--benchmark-root",
        default="workspace/benchmarks/hammer-symai-spacy-leanstral",
    )
    probe.add_argument("--baseline-manifest")
    probe.add_argument("--receipt-directory")
    probe.add_argument("--snapshot")
    probe.add_argument(
        "--freeze",
        action="store_true",
        help="exclusively write the eligible live inventory and receipts",
    )
    probe.add_argument(
        "--validate-freeze",
        action="store_true",
        help="strictly validate the existing frozen evidence without live calls",
    )
    execute = subparsers.add_parser("execute")
    execute.add_argument("--run-id", required=True)
    execute.add_argument("--splits", default="pilot,development")
    execute.add_argument(
        "--cache-mode",
        choices=("cold", "warm", "both"),
        default="both",
    )
    execute.add_argument("--validate-complete", action="store_true")
    execute.add_argument("--repository-root", default=".")
    execute.add_argument(
        "--benchmark-root",
        default="workspace/benchmarks/hammer-symai-spacy-leanstral",
    )
    execute.add_argument("--baseline-manifest")
    execute.add_argument("--receipt-directory")
    execute.add_argument("--output-root")
    execute.add_argument("--snapshot")
    execute.add_argument("--seed", type=int, default=2737)
    args = parser.parse_args(argv)
    if args.command == "probe":
        return _probe_cli(args)
    if args.command == "execute":
        return _execute_cli(args)
    raise RuntimeBindingError(f"unsupported runtime command: {args.command}")


if __name__ == "__main__":  # pragma: no cover - exercised by operator CLI
    raise SystemExit(main())


__all__ = [
    "COMPILED_OBLIGATION_SCHEMA",
    "CompiledObligation",
    "ENTAILMENT_TRANSLATION_SCHEMA",
    "HAMMER_GRAPH_SELECTOR_CONTRACT",
    "HAMMER_PREMISE_SELECTION_SCHEMA",
    "HAMMER_SYMAI_RANKING_CONTRACT",
    "HAMMER_TRANSLATED_ENTAILMENT_SCHEMA",
    "HSSLEV1142E95",
    "HSSLEV1207F16",
    "HSSLEV1305A27",
    "KERNEL_RECEIPT_SCHEMA",
    "LEANSTRAL_MEASURED_MAX_NEW_TOKENS",
    "LEANSTRAL_MEASURED_TIMEOUT_SECONDS",
    "LiveRuntime",
    "NATIVE_PROOF_CANDIDATE_SCHEMA",
    "NativeKernelRunner",
    "ReviewedEntailmentTranslation",
    "RUNTIME_VERSION",
    "RuntimeBackendHandlers",
    "RuntimeBindingError",
    "build_live_adapters",
    "build_live_runtime",
    "compile_reviewed_obligation",
    "main",
]
