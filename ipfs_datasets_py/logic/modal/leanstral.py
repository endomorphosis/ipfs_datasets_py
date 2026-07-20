"""Typed Leanstral shadow tasks for the deterministic legal modal IR.

Leanstral is allowed to construct a proof for a verifier-generated theorem and
to propose review-only compiler hints.  It never writes canonical IR directly:
the deterministic codec, source provenance, and the local Lean checker remain
the authorities.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_obligations import (
    generate_legal_ir_proof_obligations,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    LegalSample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ProverCompilationSignal,
)
from .lean_runtime import resolve_lean_executable
from .leanstral_theorems import (
    LEGAL_IR_THEOREM_LEAN_KERNEL,
    LeanstralTheoremRegistry,
    generate_legal_semantics_theorem_registry,
    lean_theorem_proof_rejection_reasons,
)


LEANSTRAL_PROPOSAL_SCHEMA_VERSION = "legal-ir-leanstral-proposal-v1"
LEANSTRAL_DRAFT_GUIDANCE_SCHEMA_VERSION = "legal-ir-leanstral-draft-guidance-v1"
LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION = "legal-ir-leanstral-hammer-candidate-v1"
_LEANSTRAL_DRAFTED_LOGIC_SCHEMA_VERSION = "legal-ir-leanstral-drafted-logic-v1"
_LEANSTRAL_DRAFTED_LOGIC_MAX_CANDIDATES = 6
_LEANSTRAL_DRAFTED_LOGIC_MAX_TEXT_CHARS = 240
_LEANSTRAL_PROOF_FORBIDDEN = re.compile(
    r"\b(?:admit|axiom|import|namespace|noncomputable|run_tac|set_option|sorry|theorem|unsafe)\b",
    re.IGNORECASE,
)
_SAFE_LEAN_IDENTIFIER = re.compile(r"[^A-Za-z0-9_]+")
_ALLOWED_RULE_HINT_ACTIONS = frozenset(
    {
        "add_or_refine_spacy_rule",
        "refine_decompiler_template",
        "refine_frame_selection_rule",
        "refine_modal_registry_rule",
    }
)

_COMPILER_CHANGE_CONTRACTS: Dict[str, Dict[str, Sequence[str] | str]] = {
    "refine_modal_family_cue_rules": {
        "allowed_paths": ("ipfs_datasets_py/logic/modal/codec.py",),
        "target_component": "modal.compiler.registry",
        "target_metrics": ("cross_entropy_loss", "legal_ir_view_cross_entropy_loss"),
        "theorem_templates": ("modal_operator_preserved", "source_provenance_preserved"),
        "mutation_cases": ("invert_modality", "remove_modal_cue"),
    },
    "refine_typed_ir_or_decompiler_slots": {
        "allowed_paths": (
            "ipfs_datasets_py/logic/modal/codec.py",
            "ipfs_datasets_py/logic/modal/decompiler.py",
        ),
        "target_component": "modal.ir_decompiler",
        "target_metrics": (
            "reconstruction_loss",
            "source_decompiled_text_embedding_cosine_loss",
        ),
        "theorem_templates": ("decompiler_round_trip", "source_provenance_preserved"),
        "mutation_cases": ("remove_exception", "alter_deadline"),
    },
    "refine_semantic_decompiler_reconstruction": {
        "allowed_paths": ("ipfs_datasets_py/logic/modal/decompiler.py",),
        "target_component": "modal.ir_decompiler",
        "target_metrics": (
            "source_decompiled_text_embedding_cosine_loss",
            "source_decompiled_text_token_loss",
        ),
        "theorem_templates": ("decompiler_round_trip", "exception_scope_preserved"),
        "mutation_cases": ("invert_modality", "remove_exception", "alter_deadline"),
    },
    "repair_multiview_legal_ir_loss": {
        "allowed_paths": (
            "ipfs_datasets_py/logic/modal/codec.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py",
        ),
        "target_component": "bridge.contracts",
        "target_metrics": ("legal_ir_view_cross_entropy_loss", "legal_ir_multiview_total_loss"),
        "theorem_templates": ("modal_operator_preserved", "decompiler_round_trip"),
        "mutation_cases": ("invert_modality", "alter_scope"),
    },
    "repair_multiview_legal_ir_graph_projection": {
        "allowed_paths": ("ipfs_datasets_py/logic/modal/kg_bridge.py",),
        "target_component": "knowledge_graphs.neo4j_compat",
        "target_metrics": ("legal_ir_multiview_graph_failure_penalty",),
        "theorem_templates": ("graph_has_no_dangling_edges", "source_provenance_preserved"),
        "mutation_cases": ("remove_relation_endpoint",),
    },
    "repair_multiview_legal_ir_prover_gate": {
        "allowed_paths": (
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/prover_integration.py",
            "ipfs_datasets_py/logic/external_provers/interactive/lean_prover_bridge.py",
        ),
        "target_component": "external_provers.router",
        "target_metrics": ("legal_ir_multiview_proof_failure_ratio",),
        "theorem_templates": ("modal_operator_preserved", "proof_route_is_distinct_from_proof"),
        "mutation_cases": ("unsupported_modal_system",),
    },
    "repair_deontic_bridge_quality_gate": {
        "allowed_paths": (
            "ipfs_datasets_py/logic/modal/codec.py",
            "ipfs_datasets_py/logic/modal/decompiler.py",
        ),
        "target_component": "deontic.ir",
        "target_metrics": ("deontic_decoder_slot_loss", "legal_ir_view_cross_entropy_loss"),
        "theorem_templates": ("modal_operator_preserved", "exception_scope_preserved"),
        "mutation_cases": ("invert_modality", "remove_exception"),
    },
}


_LEGAL_IR_LEAN_KERNEL = """namespace LegalIR

structure ModalFormula where
  formulaId : String
  family : String
  system : String
  symbol : String
  predicate : String
  sourceSpan : String
  deriving Repr, DecidableEq

def wellFormed (formula : ModalFormula) : Prop :=
  formula.formulaId.length > 0 /\\
  formula.family.length > 0 /\\
  formula.system.length > 0 /\\
  formula.symbol.length > 0 /\\
  formula.predicate.length > 0 /\\
  formula.sourceSpan.length > 0

def modalityMatches (formula : ModalFormula) (family : String) (symbol : String) : Prop :=
  formula.family = family /\\ formula.symbol = symbol

def sourceProvenancePresent (formula : ModalFormula) : Prop :=
  formula.sourceSpan.length > 0

end LegalIR
"""


LLMGenerateFn = Callable[..., str]


@dataclass(frozen=True)
class LeanstralConfig:
    """Configuration for the explicit, non-mutating Leanstral proof lane."""

    enabled: bool = False
    provider: str = "leanstral_local"
    model: str = "Leanstral"
    vibe_agent: str = "lean"
    timeout_seconds: float = 300.0
    max_new_tokens: int = 1400
    artifact_dir: Optional[str] = None
    repo_root: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectionEvidence:
    """Stable, compact evidence exported from a learned projection."""

    evidence_id: str
    sample_id: str
    modal_ir_hash: str
    source_span_hashes: Mapping[str, str]
    losses: Mapping[str, float]
    legal_ir_view_gaps: Mapping[str, float]
    ranked_features: Sequence[Mapping[str, Any]]
    synthesis_focus: Sequence[str]
    hint_id: str = ""
    action: str = ""
    target_component: str = ""

    @classmethod
    def from_sample(
        cls,
        sample: LegalSample,
        *,
        autoencoder_guidance: Mapping[str, Any],
        hint: Optional[Any] = None,
    ) -> "ProjectionEvidence":
        source_span_hashes = {
            formula.formula_id: _source_span_hash(sample, formula.provenance.start_char, formula.provenance.end_char)
            for formula in sample.modal_ir.formulas
        }
        losses = _numeric_mapping(autoencoder_guidance.get("legal_ir_view_metrics"))
        gaps = _numeric_mapping(autoencoder_guidance.get("legal_ir_view_gap_distribution"))
        hint_evidence = getattr(hint, "evidence", {}) if hint is not None else {}
        hint_evidence = hint_evidence if isinstance(hint_evidence, Mapping) else {}
        action = str(getattr(hint, "action", "") or "").strip()
        if not action:
            action = _action_from_focus(autoencoder_guidance.get("synthesis_focus"), losses)
        ranked_features = _mapping_sequence(autoencoder_guidance.get("ranked_guidance_features"))
        synthesis_focus = tuple(
            str(value)
            for value in autoencoder_guidance.get("synthesis_focus", ())
            if str(value).strip()
        )
        combined_losses = {**losses, **_numeric_mapping(hint_evidence)}
        payload = {
            "action": action,
            "hint_id": str(getattr(hint, "hint_id", "") or ""),
            "legal_ir_view_gaps": gaps,
            "losses": combined_losses,
            "modal_ir_hash": sample.modal_ir.canonical_hash(),
            "ranked_features": ranked_features,
            "sample_id": sample.sample_id,
            "source_span_hashes": source_span_hashes,
            "synthesis_focus": synthesis_focus,
            "target_component": str(getattr(hint, "target_component", "") or ""),
        }
        evidence_id = "projection-" + hashlib.sha256(
            json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return cls(
            evidence_id=evidence_id,
            sample_id=sample.sample_id,
            modal_ir_hash=sample.modal_ir.canonical_hash(),
            source_span_hashes=source_span_hashes,
            losses=combined_losses,
            legal_ir_view_gaps=gaps,
            ranked_features=ranked_features,
            synthesis_focus=synthesis_focus,
            hint_id=str(getattr(hint, "hint_id", "") or ""),
            action=action,
            target_component=str(getattr(hint, "target_component", "") or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "evidence_id": self.evidence_id,
            "hint_id": self.hint_id,
            "legal_ir_view_gaps": dict(sorted(self.legal_ir_view_gaps.items())),
            "losses": dict(sorted(self.losses.items())),
            "modal_ir_hash": self.modal_ir_hash,
            "ranked_features": [dict(item) for item in self.ranked_features],
            "sample_id": self.sample_id,
            "source_span_hashes": dict(sorted(self.source_span_hashes.items())),
            "synthesis_focus": list(self.synthesis_focus),
            "target_component": self.target_component,
        }


@dataclass(frozen=True)
class CompilerChangeSpec:
    """A bounded Python change surface derived from projection evidence."""

    spec_id: str
    evidence_id: str
    action: str
    target_component: str
    patchable: bool
    allowed_paths: Sequence[str] = field(default_factory=tuple)
    target_metrics: Sequence[str] = field(default_factory=tuple)
    theorem_templates: Sequence[str] = field(default_factory=tuple)
    mutation_cases: Sequence[str] = field(default_factory=tuple)

    @classmethod
    def from_evidence(cls, evidence: ProjectionEvidence) -> "CompilerChangeSpec":
        contract = _COMPILER_CHANGE_CONTRACTS.get(evidence.action, {})
        patchable = bool(contract)
        target_component = str(
            evidence.target_component or contract.get("target_component", "projection.review")
        )
        payload = {
            "action": evidence.action,
            "evidence_id": evidence.evidence_id,
            "target_component": target_component,
        }
        spec_id = "compiler-change-" + hashlib.sha256(
            json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return cls(
            spec_id=spec_id,
            evidence_id=evidence.evidence_id,
            action=evidence.action or "review_projection_evidence",
            target_component=target_component,
            patchable=patchable,
            allowed_paths=tuple(str(value) for value in contract.get("allowed_paths", ())),
            target_metrics=tuple(str(value) for value in contract.get("target_metrics", ())),
            theorem_templates=tuple(str(value) for value in contract.get("theorem_templates", ())),
            mutation_cases=tuple(str(value) for value in contract.get("mutation_cases", ())),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PythonPatchProposal:
    """A constrained unified diff proposed for one compiler change spec."""

    compiler_change_spec_id: str
    unified_diff: str
    summary: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PythonPatchProposal":
        return cls(
            compiler_change_spec_id=str(data.get("compiler_change_spec_id", "")).strip(),
            unified_diff=str(data.get("unified_diff", "")).strip(),
            summary=str(data.get("summary", "")).strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PythonPatchValidation:
    """Read-only worktree admission report for a proposed Python diff."""

    accepted: bool
    requested: bool
    reasons: Sequence[str] = field(default_factory=tuple)
    changed_paths: Sequence[str] = field(default_factory=tuple)
    git_output: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "changed_paths": list(self.changed_paths),
            "git_output": self.git_output,
            "reasons": list(self.reasons),
            "requested": self.requested,
        }


@dataclass(frozen=True)
class LegalIRLeanTask:
    """A fixed Lean theorem generated from one canonical modal IR formula."""

    task_id: str
    sample_id: str
    formula_id: str
    modal_ir_hash: str
    target_statement: str
    source_span: str
    modal_formula: Dict[str, Any]
    autoencoder_evidence: Dict[str, Any]
    prover_signal: Optional[Dict[str, Any]] = None
    projection_evidence: Optional[Dict[str, Any]] = None
    compiler_change_spec: Optional[Dict[str, Any]] = None
    theorem_registry: Optional[Dict[str, Any]] = None
    proof_obligations: Optional[Sequence[Dict[str, Any]]] = None

    @classmethod
    def from_sample(
        cls,
        sample: LegalSample,
        *,
        autoencoder_guidance: Mapping[str, Any],
        prover_signal: Optional[ProverCompilationSignal] = None,
        synthesis_hint: Optional[Any] = None,
    ) -> "LegalIRLeanTask":
        if not sample.modal_ir.formulas:
            raise ValueError("Leanstral shadow task requires at least one modal IR formula")

        formula = sample.modal_ir.formulas[0]
        span = sample.normalized_text[
            max(0, int(formula.provenance.start_char)) : max(
                0, int(formula.provenance.end_char)
            )
        ].strip()
        if not span:
            span = sample.text[
                max(0, int(formula.provenance.start_char)) : max(
                    0, int(formula.provenance.end_char)
                )
            ].strip()
        if not span:
            raise ValueError("Leanstral shadow task requires a non-empty source span")

        modal_formula = formula.to_dict()
        modal_ir_hash = sample.modal_ir.canonical_hash()
        theorem_registry = generate_legal_semantics_theorem_registry(sample)
        proof_obligations = generate_legal_ir_proof_obligations(sample)
        target_statement = _well_formed_target_statement(modal_formula, source_span=span)
        projection_evidence = ProjectionEvidence.from_sample(
            sample,
            autoencoder_guidance=autoencoder_guidance,
            hint=synthesis_hint,
        )
        compiler_change_spec = CompilerChangeSpec.from_evidence(projection_evidence)
        task_payload = {
            "compiler_change_spec_id": compiler_change_spec.spec_id,
            "formula_id": formula.formula_id,
            "modal_ir_hash": modal_ir_hash,
            "projection_evidence_id": projection_evidence.evidence_id,
            "sample_id": sample.sample_id,
            "target_statement": target_statement,
            "theorem_registry_hash": theorem_registry.registry_hash,
            "proof_obligation_hash": hashlib.sha256(
                json.dumps(
                    [obligation.to_dict() for obligation in proof_obligations],
                    ensure_ascii=True,
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest()[:16],
        }
        task_id = "leanstral-" + hashlib.sha256(
            json.dumps(task_payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return cls(
            task_id=task_id,
            sample_id=sample.sample_id,
            formula_id=formula.formula_id,
            modal_ir_hash=modal_ir_hash,
            target_statement=target_statement,
            source_span=span,
            modal_formula=modal_formula,
            autoencoder_evidence=_leanstral_evidence(autoencoder_guidance),
            prover_signal=prover_signal.to_dict() if prover_signal else None,
            projection_evidence=projection_evidence.to_dict(),
            compiler_change_spec=compiler_change_spec.to_dict(),
            theorem_registry=theorem_registry.to_dict(),
            proof_obligations=tuple(obligation.to_dict() for obligation in proof_obligations),
        )

    @property
    def theorem_name(self) -> str:
        suffix = _SAFE_LEAN_IDENTIFIER.sub("_", self.task_id).strip("_")
        return f"ir_well_formed_{suffix}"

    def render_lean_source(
        self,
        proof: str,
        *,
        theorem_proofs: Optional[Mapping[str, str]] = None,
    ) -> str:
        source = (
            _LEGAL_IR_LEAN_KERNEL
            + "\nnamespace LegalIR\n\n"
            + f"theorem {self.theorem_name} : {self.target_statement} := {proof.strip()}\n\n"
            + "end LegalIR\n"
        )
        theorem_source = _render_theorem_registry_source(
            self.theorem_registry,
            theorem_proofs or {},
        )
        if theorem_source:
            source += "\n" + theorem_source
        return source

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LeanstralProposal:
    """Model output constrained to a proof body and review-only rule hints."""

    schema_version: str
    task_id: str
    target_modal_ir_hash: str
    compiler_change_spec_id: str
    proof: str
    python_patch: Optional[PythonPatchProposal] = None
    deterministic_rule_hints: Sequence[Dict[str, str]] = field(default_factory=tuple)
    drafted_logic_candidates: Sequence[Dict[str, Any]] = field(default_factory=tuple)
    theorem_proofs: Mapping[str, str] = field(default_factory=dict)
    forbidden_statement_keys: Sequence[str] = field(default_factory=tuple)
    notes: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "LeanstralProposal":
        hints = data.get("deterministic_rule_hints", [])
        normalized_hints: list[Dict[str, str]] = []
        if isinstance(hints, Sequence) and not isinstance(hints, (str, bytes)):
            for hint in hints:
                if not isinstance(hint, Mapping):
                    continue
                normalized_hints.append(
                    {
                        "action": str(hint.get("action", "")).strip(),
                        "rationale": str(hint.get("rationale", "")).strip(),
                        "target_component": str(
                            hint.get("target_component", "")
                        ).strip(),
                    }
                )
        theorem_proofs = data.get("theorem_proofs", data.get("proofs", {}))
        normalized_theorem_proofs: Dict[str, str] = {}
        if isinstance(theorem_proofs, Mapping):
            normalized_theorem_proofs = {
                str(theorem_id).strip(): str(proof).strip()
                for theorem_id, proof in theorem_proofs.items()
                if str(theorem_id).strip()
            }
        forbidden_statement_keys = tuple(
            key
            for key in (
                "lean_source",
                "statement",
                "statements",
                "target_statement",
                "theorem",
                "theorem_statement",
                "theorems",
            )
            if key in data
        )
        return cls(
            schema_version=str(data.get("schema_version", "")).strip(),
            task_id=str(data.get("task_id", "")).strip(),
            target_modal_ir_hash=str(data.get("target_modal_ir_hash", "")).strip(),
            compiler_change_spec_id=str(data.get("compiler_change_spec_id", "")).strip(),
            proof=str(data.get("proof", "")).strip(),
            python_patch=PythonPatchProposal.from_mapping(data["python_patch"])
            if isinstance(data.get("python_patch"), Mapping)
            else None,
            deterministic_rule_hints=tuple(normalized_hints),
            drafted_logic_candidates=tuple(
                _drafted_logic_candidates(data.get("drafted_logic_candidates"))
            ),
            theorem_proofs=normalized_theorem_proofs,
            forbidden_statement_keys=forbidden_statement_keys,
            notes=str(data.get("notes", "")).strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compiler_change_spec_id": self.compiler_change_spec_id,
            "deterministic_rule_hints": [dict(hint) for hint in self.deterministic_rule_hints],
            "drafted_logic_candidates": [
                dict(candidate) for candidate in self.drafted_logic_candidates
            ],
            "notes": self.notes,
            "proof": self.proof,
            "python_patch": self.python_patch.to_dict() if self.python_patch else None,
            "schema_version": self.schema_version,
            "target_modal_ir_hash": self.target_modal_ir_hash,
            "task_id": self.task_id,
            "theorem_proofs": dict(sorted(self.theorem_proofs.items())),
            "forbidden_statement_keys": list(self.forbidden_statement_keys),
        }


@dataclass(frozen=True)
class LeanstralProofValidation:
    """Validation outcome for one bounded Leanstral proposal."""

    accepted: bool
    reasons: Sequence[str] = field(default_factory=tuple)
    lean_output: str = ""
    proof_sha256: str = ""
    python_patch_validation: Optional[PythonPatchValidation] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "lean_output": self.lean_output,
            "proof_sha256": self.proof_sha256,
            "python_patch_validation": self.python_patch_validation.to_dict()
            if self.python_patch_validation
            else None,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class LeanstralDraftGuidance:
    """Validated Leanstral proof output distilled into compiler guidance."""

    schema_version: str
    guidance_id: str
    source: str
    task_id: str
    sample_id: str
    modal_ir_hash: str
    compiler_change_spec_id: str
    action: str
    target_component: str
    accepted: bool
    trusted: bool
    intended_use: str
    validation_reasons: Sequence[str] = field(default_factory=tuple)
    proof_sha256: str = ""
    deterministic_rule_hints: Sequence[Dict[str, str]] = field(default_factory=tuple)
    drafted_logic_candidates: Sequence[Dict[str, Any]] = field(default_factory=tuple)
    ranked_guidance_features: Sequence[Dict[str, Any]] = field(default_factory=tuple)
    synthesis_focus: Sequence[str] = field(default_factory=tuple)
    feature_groups: Mapping[str, Sequence[str]] = field(default_factory=dict)
    legal_ir_view_gap_distribution: Mapping[str, float] = field(default_factory=dict)
    legal_ir_view_metrics: Mapping[str, float] = field(default_factory=dict)
    target_metrics: Sequence[str] = field(default_factory=tuple)
    allowed_paths: Sequence[str] = field(default_factory=tuple)
    theorem_templates: Sequence[str] = field(default_factory=tuple)
    mutation_cases: Sequence[str] = field(default_factory=tuple)
    proof_obligation_ids: Sequence[str] = field(default_factory=tuple)

    @property
    def report_only(self) -> bool:
        return not bool(self.trusted)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": bool(self.accepted),
            "action": self.action,
            "allowed_paths": list(self.allowed_paths),
            "compiler_change_spec_id": self.compiler_change_spec_id,
            "deterministic_rule_hints": [
                dict(hint) for hint in self.deterministic_rule_hints
            ],
            "drafted_logic_candidates": [
                dict(candidate) for candidate in self.drafted_logic_candidates
            ],
            "feature_groups": {
                str(key): [str(item) for item in value]
                for key, value in sorted(self.feature_groups.items())
            },
            "guidance_id": self.guidance_id,
            "intended_use": self.intended_use,
            "legal_ir_view_gap_distribution": dict(
                sorted(self.legal_ir_view_gap_distribution.items())
            ),
            "legal_ir_view_metrics": dict(sorted(self.legal_ir_view_metrics.items())),
            "modal_ir_hash": self.modal_ir_hash,
            "mutation_cases": list(self.mutation_cases),
            "proof_obligation_ids": list(self.proof_obligation_ids),
            "proof_sha256": self.proof_sha256,
            "ranked_guidance_features": [
                dict(feature) for feature in self.ranked_guidance_features
            ],
            "report_only": self.report_only,
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "source": self.source,
            "synthesis_focus": list(self.synthesis_focus),
            "target_component": self.target_component,
            "target_metrics": list(self.target_metrics),
            "task_id": self.task_id,
            "theorem_templates": list(self.theorem_templates),
            "trusted": bool(self.trusted),
            "validation_reasons": list(self.validation_reasons),
        }

    def to_compiler_guidance_overlay(self) -> Dict[str, Any]:
        """Return only fields shaped like AdaptiveModalAutoencoder guidance."""

        return {
            "feature_groups": {
                str(key): [str(item) for item in value]
                for key, value in sorted(self.feature_groups.items())
            },
            "legal_ir_view_gap_distribution": dict(
                sorted(self.legal_ir_view_gap_distribution.items())
            ),
            "legal_ir_view_metrics": dict(sorted(self.legal_ir_view_metrics.items())),
            "ranked_guidance_features": [
                dict(feature) for feature in self.ranked_guidance_features
            ],
            "synthesis_focus": list(self.synthesis_focus),
        }


@dataclass(frozen=True)
class LeanstralShadowResult:
    """Auditable output of a shadow-only autoencoder-to-Leanstral pass."""

    task: LegalIRLeanTask
    proposal: Optional[LeanstralProposal]
    validation: LeanstralProofValidation
    llm_called: bool
    raw_response: str = ""
    artifact_path: Optional[str] = None
    guidance: Optional[LeanstralDraftGuidance] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "guidance": self.guidance.to_dict() if self.guidance else None,
            "llm_called": self.llm_called,
            "proposal": self.proposal.to_dict() if self.proposal else None,
            "raw_response": self.raw_response,
            "task": self.task.to_dict(),
            "validation": self.validation.to_dict(),
        }


class LeanstralShadowRunner:
    """Ask Leanstral to prove fixed compiler facts without mutating the IR."""

    def __init__(
        self,
        config: Optional[LeanstralConfig] = None,
        *,
        llm_generate: Optional[LLMGenerateFn] = None,
        lean_executable: Optional[str] = None,
    ) -> None:
        self.config = config or LeanstralConfig()
        self.llm_generate = llm_generate
        self.lean_executable = lean_executable

    def run(
        self,
        sample: LegalSample,
        *,
        autoencoder: AdaptiveModalAutoencoder,
        prover_signal: Optional[ProverCompilationSignal] = None,
    ) -> LeanstralShadowResult:
        guidance = autoencoder.compiler_guidance_for_sample(sample)
        task = LegalIRLeanTask.from_sample(
            sample,
            autoencoder_guidance=guidance,
            prover_signal=prover_signal,
        )
        if not self.config.enabled:
            validation = LeanstralProofValidation(
                accepted=False,
                reasons=("leanstral_shadow_disabled",),
            )
            return LeanstralShadowResult(
                task=task,
                proposal=None,
                validation=validation,
                llm_called=False,
                guidance=leanstral_draft_guidance(
                    task,
                    None,
                    validation,
                ),
            )

        generate = self.llm_generate
        if generate is None:
            from ipfs_datasets_py import llm_router

            generate = llm_router.generate_text
        raw_response = generate(
            _leanstral_prompt(task),
            provider=self.config.provider,
            model_name=self.config.model,
            allow_local_fallback=False,
            disable_model_retry=True,
            max_new_tokens=int(self.config.max_new_tokens),
            mistral_vibe_agent=self.config.vibe_agent,
            temperature=0.0,
            timeout=float(self.config.timeout_seconds),
        )
        proposal = _proposal_from_response(raw_response)
        validation = validate_leanstral_proposal(
            task,
            proposal,
            lean_executable=self.lean_executable,
            timeout_seconds=self.config.timeout_seconds,
            repo_root=self.config.repo_root,
        )
        guidance = leanstral_draft_guidance(
            task,
            proposal,
            validation,
        )
        artifact_path = self._write_artifact(
            task=task,
            proposal=proposal,
            validation=validation,
            raw_response=raw_response,
            guidance=guidance,
        )
        return LeanstralShadowResult(
            task=task,
            proposal=proposal,
            validation=validation,
            llm_called=True,
            raw_response=raw_response,
            artifact_path=artifact_path,
            guidance=guidance,
        )

    def _write_artifact(
        self,
        *,
        task: LegalIRLeanTask,
        proposal: Optional[LeanstralProposal],
        validation: LeanstralProofValidation,
        raw_response: str,
        guidance: Optional[LeanstralDraftGuidance] = None,
    ) -> Optional[str]:
        if not self.config.artifact_dir:
            return None
        directory = Path(self.config.artifact_dir).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{task.task_id}.json"
        payload = {
            "guidance": guidance.to_dict() if guidance else None,
            "proposal": proposal.to_dict() if proposal else None,
            "raw_response": raw_response,
            "task": task.to_dict(),
            "validation": validation.to_dict(),
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=f".{task.task_id}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
            temporary_path = Path(handle.name)
        os.replace(temporary_path, path)
        return str(path)


def validate_leanstral_proposal(
    task: LegalIRLeanTask,
    proposal: Optional[LeanstralProposal],
    *,
    lean_executable: Optional[str] = None,
    timeout_seconds: float = 300.0,
    repo_root: Optional[str] = None,
) -> LeanstralProofValidation:
    """Check identity, patch safety, and Lean proof acceptance for one proposal."""

    if proposal is None:
        return LeanstralProofValidation(accepted=False, reasons=("invalid_json_proposal",))
    reasons = _proposal_rejection_reasons(task, proposal)
    proof_sha256 = hashlib.sha256(proposal.proof.encode("utf-8")).hexdigest()
    if reasons:
        return LeanstralProofValidation(
            accepted=False,
            reasons=tuple(reasons),
            proof_sha256=proof_sha256,
        )
    executable = resolve_lean_executable(lean_executable)
    if not executable:
        return LeanstralProofValidation(
            accepted=False,
            reasons=("lean_executable_unavailable",),
            proof_sha256=proof_sha256,
        )
    try:
        with tempfile.TemporaryDirectory(prefix="legal-ir-leanstral-") as directory:
            source_path = Path(directory) / "Task.lean"
            source_path.write_text(
                task.render_lean_source(
                    proposal.proof,
                    theorem_proofs=proposal.theorem_proofs,
                ),
                encoding="utf-8",
            )
            process = subprocess.run(
                [executable, str(source_path)],
                capture_output=True,
                check=False,
                text=True,
                timeout=max(1.0, float(timeout_seconds)),
            )
    except subprocess.TimeoutExpired:
        return LeanstralProofValidation(
            accepted=False,
            reasons=("lean_timeout",),
            proof_sha256=proof_sha256,
        )
    except OSError as exc:
        return LeanstralProofValidation(
            accepted=False,
            reasons=(f"lean_execution_error:{exc.__class__.__name__}",),
            proof_sha256=proof_sha256,
        )
    output = ((process.stdout or "") + (process.stderr or "")).strip()
    if process.returncode != 0:
        return LeanstralProofValidation(
            accepted=False,
            reasons=("lean_rejected_proof",),
            lean_output=output,
            proof_sha256=proof_sha256,
        )
    if "sorry" in output.lower():
        return LeanstralProofValidation(
            accepted=False,
            reasons=("lean_reported_sorry",),
            lean_output=output,
            proof_sha256=proof_sha256,
        )
    patch_validation = validate_python_patch_proposal(
        task,
        proposal.python_patch,
        repo_root=repo_root,
    )
    if not patch_validation.accepted:
        return LeanstralProofValidation(
            accepted=False,
            reasons=tuple(patch_validation.reasons),
            lean_output=output,
            proof_sha256=proof_sha256,
            python_patch_validation=patch_validation,
        )
    return LeanstralProofValidation(
        accepted=True,
        lean_output=output,
        proof_sha256=proof_sha256,
        python_patch_validation=patch_validation,
    )


def validate_python_patch_proposal(
    task: LegalIRLeanTask,
    proposal: Optional[PythonPatchProposal],
    *,
    repo_root: Optional[str] = None,
) -> PythonPatchValidation:
    """Validate a proposed diff without applying it or creating a worktree."""

    if proposal is None:
        return PythonPatchValidation(accepted=True, requested=False, reasons=("not_requested",))
    change_spec = task.compiler_change_spec or {}
    reasons: list[str] = []
    if proposal.compiler_change_spec_id != str(change_spec.get("spec_id", "")):
        reasons.append("compiler_change_spec_mismatch")
    if not bool(change_spec.get("patchable", False)):
        reasons.append("python_patch_for_nonpatchable_spec")
    diff = proposal.unified_diff
    if not diff:
        reasons.append("empty_python_patch")
    if "GIT binary patch" in diff:
        reasons.append("binary_python_patch_forbidden")
    changed_paths = _unified_diff_paths(diff)
    if not changed_paths:
        reasons.append("python_patch_has_no_paths")
    allowed_paths = {str(path) for path in change_spec.get("allowed_paths", ())}
    disallowed_paths = [path for path in changed_paths if path not in allowed_paths]
    if disallowed_paths:
        reasons.append("python_patch_touches_disallowed_path")
    if reasons:
        return PythonPatchValidation(
            accepted=False,
            requested=True,
            reasons=tuple(dict.fromkeys(reasons)),
            changed_paths=tuple(changed_paths),
        )
    root = Path(repo_root).expanduser() if repo_root else Path(__file__).resolve().parents[3]
    try:
        process = subprocess.run(
            ["git", "-C", str(root), "apply", "--check", "--whitespace=error", "-"],
            input=diff,
            text=True,
            capture_output=True,
            check=False,
            timeout=30.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return PythonPatchValidation(
            accepted=False,
            requested=True,
            reasons=(f"git_apply_check_error:{exc.__class__.__name__}",),
            changed_paths=tuple(changed_paths),
        )
    output = ((process.stdout or "") + (process.stderr or "")).strip()
    if process.returncode != 0:
        return PythonPatchValidation(
            accepted=False,
            requested=True,
            reasons=("git_apply_check_failed",),
            changed_paths=tuple(changed_paths),
            git_output=output,
        )
    return PythonPatchValidation(
        accepted=True,
        requested=True,
        changed_paths=tuple(changed_paths),
        git_output=output,
    )


def leanstral_draft_guidance(
    task: LegalIRLeanTask,
    proposal: Optional[LeanstralProposal],
    validation: LeanstralProofValidation,
) -> LeanstralDraftGuidance:
    """Distill one Leanstral result into guidance for autoencoder/Codex loops."""

    change_spec = task.compiler_change_spec if isinstance(task.compiler_change_spec, Mapping) else {}
    projection_evidence = (
        task.projection_evidence if isinstance(task.projection_evidence, Mapping) else {}
    )
    autoencoder_evidence = (
        task.autoencoder_evidence if isinstance(task.autoencoder_evidence, Mapping) else {}
    )
    action = str(change_spec.get("action") or projection_evidence.get("action") or "").strip()
    target_component = str(
        change_spec.get("target_component")
        or projection_evidence.get("target_component")
        or ""
    ).strip()
    accepted = bool(validation.accepted)
    candidates = (
        [dict(candidate) for candidate in proposal.drafted_logic_candidates]
        if proposal is not None
        else []
    )
    rule_hints = (
        [dict(hint) for hint in proposal.deterministic_rule_hints]
        if proposal is not None
        else []
    )
    legal_ir_view_metrics = _numeric_mapping(
        autoencoder_evidence.get("legal_ir_view_metrics")
        or projection_evidence.get("losses")
    )
    legal_ir_view_gaps = _numeric_mapping(
        autoencoder_evidence.get("legal_ir_view_gap_distribution")
        or projection_evidence.get("legal_ir_view_gaps")
    )
    proof_obligation_ids = _theorem_registry_ids(task.theorem_registry)
    target_metrics = _string_sequence(change_spec.get("target_metrics"))
    allowed_paths = _string_sequence(change_spec.get("allowed_paths"))
    theorem_templates = _string_sequence(change_spec.get("theorem_templates"))
    mutation_cases = _string_sequence(change_spec.get("mutation_cases"))
    ranked_features, feature_groups = _leanstral_guidance_features(
        action=action,
        target_component=target_component,
        accepted=accepted,
        drafted_logic_candidates=candidates,
        deterministic_rule_hints=rule_hints,
        target_metrics=target_metrics,
        theorem_templates=theorem_templates,
        proof_obligation_ids=proof_obligation_ids,
    )
    synthesis_focus = _unique_string_values(
        [
            *_string_sequence(autoencoder_evidence.get("synthesis_focus")),
            action,
            target_component,
            "leanstral_draft_logic_guidance",
        ]
    )
    payload = {
        "accepted": accepted,
        "action": action,
        "compiler_change_spec_id": str(change_spec.get("spec_id") or ""),
        "drafted_logic_candidates": candidates,
        "modal_ir_hash": task.modal_ir_hash,
        "proof_sha256": validation.proof_sha256,
        "rule_hints": rule_hints,
        "sample_id": task.sample_id,
        "target_component": target_component,
        "task_id": task.task_id,
        "validation_reasons": list(validation.reasons),
    }
    guidance_id = "leanstral-guidance-" + hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return LeanstralDraftGuidance(
        schema_version=LEANSTRAL_DRAFT_GUIDANCE_SCHEMA_VERSION,
        guidance_id=guidance_id,
        source="leanstral_shadow_proof",
        task_id=task.task_id,
        sample_id=task.sample_id,
        modal_ir_hash=task.modal_ir_hash,
        compiler_change_spec_id=str(change_spec.get("spec_id") or ""),
        action=action,
        target_component=target_component,
        accepted=accepted,
        trusted=accepted,
        intended_use="guidance_only",
        validation_reasons=tuple(str(reason) for reason in validation.reasons),
        proof_sha256=validation.proof_sha256,
        deterministic_rule_hints=tuple(rule_hints),
        drafted_logic_candidates=tuple(candidates),
        ranked_guidance_features=tuple(ranked_features),
        synthesis_focus=tuple(synthesis_focus),
        feature_groups=feature_groups,
        legal_ir_view_gap_distribution=legal_ir_view_gaps,
        legal_ir_view_metrics=legal_ir_view_metrics,
        target_metrics=tuple(target_metrics),
        allowed_paths=tuple(allowed_paths),
        theorem_templates=tuple(theorem_templates),
        mutation_cases=tuple(mutation_cases),
        proof_obligation_ids=tuple(proof_obligation_ids),
    )


def merge_leanstral_guidance_into_compiler_guidance(
    compiler_guidance: Mapping[str, Any],
    leanstral_guidance: Mapping[str, Any] | LeanstralDraftGuidance,
) -> Dict[str, Any]:
    """Overlay trusted Leanstral draft guidance onto autoencoder guidance."""

    base = dict(compiler_guidance or {})
    guidance = (
        leanstral_guidance.to_dict()
        if isinstance(leanstral_guidance, LeanstralDraftGuidance)
        else dict(leanstral_guidance or {})
    )
    if not guidance:
        return base
    external = [
        dict(item)
        for item in base.get("external_guidance", [])
        if isinstance(item, Mapping)
    ]
    external.append(guidance)
    base["external_guidance"] = external[-16:]
    base["latest_leanstral_guidance"] = guidance
    base["leanstral_guidance_hash"] = hashlib.sha256(
        json.dumps(guidance, ensure_ascii=True, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    if not bool(guidance.get("trusted")):
        return base

    overlay_feature_groups = guidance.get("feature_groups")
    if isinstance(overlay_feature_groups, Mapping):
        feature_groups = {
            str(key): [str(item) for item in value]
            for key, value in dict(base.get("feature_groups") or {}).items()
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        }
        for key, values in overlay_feature_groups.items():
            current = feature_groups.setdefault(str(key), [])
            for value in _string_sequence(values):
                if value not in current:
                    current.append(value)
        base["feature_groups"] = feature_groups

    ranked = [
        dict(item)
        for item in guidance.get("ranked_guidance_features", [])
        if isinstance(item, Mapping)
    ]
    ranked.extend(
        dict(item)
        for item in base.get("ranked_guidance_features", [])
        if isinstance(item, Mapping)
    )
    base["ranked_guidance_features"] = _dedupe_guidance_features(ranked)[:64]
    base["synthesis_focus"] = _unique_string_values(
        [
            *_string_sequence(base.get("synthesis_focus")),
            *_string_sequence(guidance.get("synthesis_focus")),
        ]
    )
    return base


def _proposal_rejection_reasons(
    task: LegalIRLeanTask,
    proposal: LeanstralProposal,
) -> list[str]:
    reasons: list[str] = []
    if proposal.schema_version != LEANSTRAL_PROPOSAL_SCHEMA_VERSION:
        reasons.append("unexpected_schema_version")
    if proposal.task_id != task.task_id:
        reasons.append("task_id_mismatch")
    if proposal.target_modal_ir_hash != task.modal_ir_hash:
        reasons.append("modal_ir_hash_mismatch")
    change_spec = task.compiler_change_spec or {}
    expected_spec_id = str(change_spec.get("spec_id", "")).strip()
    if proposal.compiler_change_spec_id != expected_spec_id:
        reasons.append("compiler_change_spec_mismatch")
    if proposal.forbidden_statement_keys:
        reasons.append("proposal_attempted_theorem_statement_override")
    if not proposal.proof.startswith("by"):
        reasons.append("proof_must_start_with_by")
    if len(proposal.proof) > 12000:
        reasons.append("proof_too_large")
    if _LEANSTRAL_PROOF_FORBIDDEN.search(proposal.proof):
        reasons.append("forbidden_proof_construct")
    reasons.extend(
        lean_theorem_proof_rejection_reasons(
            task.theorem_registry,
            proposal.theorem_proofs,
            forbidden_pattern=_LEANSTRAL_PROOF_FORBIDDEN,
        )
    )
    for hint in proposal.deterministic_rule_hints:
        if not bool(change_spec.get("patchable", False)):
            reasons.append("rule_hint_for_nonpatchable_spec")
            break
        if hint.get("action") not in _ALLOWED_RULE_HINT_ACTIONS:
            reasons.append("unsupported_rule_hint_action")
            break
        if not hint.get("rationale") or not hint.get("target_component"):
            reasons.append("incomplete_rule_hint")
            break
        if hint.get("target_component") != str(change_spec.get("target_component", "")):
            reasons.append("rule_hint_target_component_mismatch")
            break
    theorem_ids = set(_theorem_registry_ids(task.theorem_registry))
    obligation_ids = set(_legal_ir_proof_obligation_ids(task))
    accepted_obligation_ids = theorem_ids | obligation_ids
    for candidate in proposal.drafted_logic_candidates:
        candidate_text = str(candidate.get("candidate") or "").strip()
        if not candidate_text:
            reasons.append("missing_drafted_logic_candidate")
            break
        if len(candidate_text) > _LEANSTRAL_DRAFTED_LOGIC_MAX_TEXT_CHARS:
            reasons.append("drafted_logic_candidate_too_large")
            break
        proof_obligation_ids = _string_sequence(
            candidate.get("proof_obligation_ids")
            or candidate.get("proof_obligation_id")
            or candidate.get("obligation_id")
        )
        if accepted_obligation_ids and any(
            obligation_id not in accepted_obligation_ids
            for obligation_id in proof_obligation_ids
        ):
            reasons.append("unknown_drafted_logic_proof_obligation_id")
            break
        for key in (
            "compiler_surface",
            "expected_failure_mode",
            "logic_family",
            "premise_hints",
            "source_copy_policy",
            "target_view",
        ):
            if key not in candidate:
                reasons.append(f"missing_drafted_logic_{key}")
                break
        if reasons and str(reasons[-1]).startswith("missing_drafted_logic_"):
            break
        if _drafted_logic_candidate_copies_source_span(candidate_text, task.source_span):
            reasons.append("drafted_logic_candidate_copies_source_span")
            break
    return reasons


def _proposal_from_response(response: str) -> Optional[LeanstralProposal]:
    raw = str(response or "").strip()
    if raw.startswith("```json") and raw.endswith("```"):
        raw = raw[len("```json") : -len("```")].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, Mapping):
        return None
    return LeanstralProposal.from_mapping(parsed)


def _leanstral_evidence(guidance: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: guidance.get(key)
        for key in (
            "feature_groups",
            "legal_ir_predicted_view_distribution",
            "legal_ir_target_view_distribution",
            "legal_ir_view_gap_distribution",
            "legal_ir_view_metrics",
            "ranked_guidance_features",
            "synthesis_focus",
        )
        if key in guidance
    }


def _source_span_hash(sample: LegalSample, start_char: int, end_char: int) -> str:
    start = max(0, int(start_char))
    end = max(start, int(end_char))
    span = sample.normalized_text[start:end].strip() or sample.text[start:end].strip()
    return hashlib.sha256(span.encode("utf-8")).hexdigest()


def _numeric_mapping(value: Any) -> Dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    result: Dict[str, float] = {}
    for key, raw in value.items():
        try:
            number = float(raw)
        except (TypeError, ValueError):
            continue
        if number == number and number not in (float("inf"), float("-inf")):
            result[str(key)] = number
    return result


def _mapping_sequence(value: Any) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def _optional_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default


def _drafted_logic_candidates(value: Any) -> Sequence[Dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    candidates: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            continue
        candidate_text = str(
            item.get("candidate")
            or item.get("logic")
            or item.get("formula")
            or item.get("ir")
            or ""
        ).strip()
        if len(candidate_text) > _LEANSTRAL_DRAFTED_LOGIC_MAX_TEXT_CHARS:
            candidate_text = candidate_text[:_LEANSTRAL_DRAFTED_LOGIC_MAX_TEXT_CHARS].rstrip()
        if not candidate_text:
            continue
        logic_family = _feature_key_part(
            item.get("logic_family")
            or item.get("family")
            or item.get("view")
            or "legal_ir"
        )
        proof_obligation_ids = _string_sequence(
            item.get("proof_obligation_ids")
            or item.get("proof_obligation_id")
            or item.get("obligation_id")
        )
        premise_hints = _string_sequence(
            item.get("premise_hints")
            or item.get("selected_premises")
            or item.get("premises")
        )
        target_view = _feature_key_part(
            item.get("target_view")
            or item.get("legal_ir_view")
            or item.get("target_component")
            or item.get("compiler_surface")
            or logic_family
        )
        compiler_surface = _feature_key_part(
            item.get("compiler_surface")
            or item.get("target_component")
            or item.get("target_view")
            or target_view
        )
        expected_failure_mode = _feature_key_part(
            item.get("expected_failure_mode")
            or item.get("failure_mode")
            or item.get("failure_reason")
            or "unknown"
        )
        payload: Dict[str, Any] = {
            "candidate": candidate_text,
            "compiler_surface": compiler_surface,
            "expected_failure_mode": expected_failure_mode,
            "guidance_only": True,
            "intended_use": "guidance_only",
            "logic_family": logic_family,
            "premise_hints": premise_hints,
            "proof_obligation_ids": proof_obligation_ids,
            "schema_version": LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION,
            "source_copy_policy": "reject_full_span_copy",
            "source_copy_rejected": _optional_bool(
                item.get("source_copy_rejected")
                if "source_copy_rejected" in item
                else item.get("copy_source_span_rejected"),
                default=False,
            ),
            "target_view": target_view,
        }
        if proof_obligation_ids:
            payload["proof_obligation_id"] = proof_obligation_ids[0]
        for key in (
            "evidence_id",
            "example_id",
            "request_id",
            "source_span_hash",
            "target_component",
            "target_metric",
            "theorem_template",
        ):
            text = str(item.get(key) or "").strip()
            if text:
                payload[key] = text[:140].rstrip()
        target_metrics = _string_sequence(item.get("target_metrics"))
        if target_metrics:
            payload["target_metrics"] = target_metrics[:8]
        rationale = str(item.get("rationale") or "").strip()
        if rationale:
            payload["rationale"] = rationale[:140].rstrip()
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            confidence = float("nan")
        if confidence == confidence and confidence not in (float("inf"), float("-inf")):
            payload["confidence"] = max(0.0, min(1.0, confidence))
        else:
            payload["confidence"] = 0.0
        identity = json.dumps(
            {
                "candidate": payload.get("candidate"),
                "logic_family": payload.get("logic_family"),
                "proof_obligation_ids": payload.get("proof_obligation_ids"),
                "target_view": payload.get("target_view"),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(payload)
        if len(candidates) >= _LEANSTRAL_DRAFTED_LOGIC_MAX_CANDIDATES:
            break
    return tuple(candidates)


def _string_sequence(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        sequence: Sequence[Any] = (value,)
    elif isinstance(value, Sequence):
        sequence = value
    else:
        return []
    return _unique_string_values(str(item).strip() for item in sequence if str(item).strip())


def _unique_string_values(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _theorem_registry_ids(registry: Optional[Mapping[str, Any]]) -> list[str]:
    if not isinstance(registry, Mapping):
        return []
    raw_theorems = registry.get("theorems", ())
    if not isinstance(raw_theorems, Sequence) or isinstance(raw_theorems, (str, bytes)):
        return []
    return _unique_string_values(
        theorem.get("theorem_id")
        for theorem in raw_theorems
        if isinstance(theorem, Mapping)
    )


def _legal_ir_proof_obligations(task: "LegalIRLeanTask") -> list[Mapping[str, Any]]:
    raw_obligations = task.proof_obligations or ()
    if not isinstance(raw_obligations, Sequence) or isinstance(raw_obligations, (str, bytes)):
        return []
    return [dict(item) for item in raw_obligations if isinstance(item, Mapping)]


def _legal_ir_proof_obligation_ids(task: "LegalIRLeanTask") -> list[str]:
    return _unique_string_values(
        obligation.get("obligation_id")
        for obligation in _legal_ir_proof_obligations(task)
    )


def _first_theorem_id(task: LegalIRLeanTask) -> str:
    ids = _theorem_registry_ids(task.theorem_registry)
    return ids[0] if ids else ""


def _first_proof_obligation_id(task: LegalIRLeanTask) -> str:
    ids = _legal_ir_proof_obligation_ids(task)
    if ids:
        return ids[0]
    return _first_theorem_id(task)


def _first_proof_obligation_hints(task: LegalIRLeanTask) -> list[str]:
    obligations = _legal_ir_proof_obligations(task)
    if not obligations:
        return []
    return _string_sequence(obligations[0].get("premise_hints"))


def _first_proof_obligation_value(task: LegalIRLeanTask, key: str, fallback: str = "") -> str:
    obligations = _legal_ir_proof_obligations(task)
    if not obligations:
        return fallback
    return str(obligations[0].get(key) or fallback).strip()


def _leanstral_guidance_features(
    *,
    action: str,
    target_component: str,
    accepted: bool,
    drafted_logic_candidates: Sequence[Mapping[str, Any]],
    deterministic_rule_hints: Sequence[Mapping[str, Any]],
    target_metrics: Sequence[str],
    theorem_templates: Sequence[str],
    proof_obligation_ids: Sequence[str],
) -> tuple[list[Dict[str, Any]], Dict[str, list[str]]]:
    feature_groups: Dict[str, list[str]] = {
        "leanstral_drafted_logic": [],
        "leanstral_hammer_failure_modes": [],
        "leanstral_hammer_obligations": [],
        "leanstral_hammer_premise_hints": [],
        "leanstral_hammer_target_views": [],
        "leanstral_rule_hints": [],
        "leanstral_target_metrics": [],
        "leanstral_theorem_templates": [],
        "leanstral_proof_obligations": [],
    }
    features: list[Dict[str, Any]] = []
    trust_score = 1.0 if accepted else 0.0

    for candidate in drafted_logic_candidates:
        text = str(candidate.get("candidate") or "").strip()
        if not text:
            continue
        family = _feature_key_part(candidate.get("logic_family") or "legal_ir")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
        feature = f"leanstral:logic:{family}:{digest}"
        feature_groups["leanstral_drafted_logic"].append(feature)
        try:
            confidence = float(candidate.get("confidence", trust_score))
        except (TypeError, ValueError):
            confidence = trust_score
        score = trust_score * max(0.05, min(1.0, confidence))
        features.append(
            {
                "feature": feature,
                "score": round(score, 12),
                "logic_family": family,
                "source": "leanstral_drafted_logic",
            }
        )
        for obligation_id in _string_sequence(
            candidate.get("proof_obligation_ids")
            or candidate.get("proof_obligation_id")
            or candidate.get("obligation_id")
        )[:4]:
            obligation_feature = f"leanstral:hammer_obligation:{_feature_key_part(obligation_id)}"
            feature_groups["leanstral_hammer_obligations"].append(obligation_feature)
            features.append(
                {
                    "feature": obligation_feature,
                    "score": round(0.7 * score, 12),
                    "source": "leanstral_hammer_obligation",
                }
            )
        target_view = _feature_key_part(candidate.get("target_view") or candidate.get("legal_ir_view"))
        if target_view != "unknown":
            target_view_feature = f"leanstral:hammer_target_view:{target_view}"
            feature_groups["leanstral_hammer_target_views"].append(target_view_feature)
            features.append(
                {
                    "feature": target_view_feature,
                    "score": round(0.65 * score, 12),
                    "source": "leanstral_hammer_target_view",
                }
            )
        failure_mode = _feature_key_part(candidate.get("expected_failure_mode"))
        if failure_mode != "unknown":
            failure_feature = f"leanstral:hammer_failure_mode:{failure_mode}"
            feature_groups["leanstral_hammer_failure_modes"].append(failure_feature)
            features.append(
                {
                    "feature": failure_feature,
                    "score": round(0.55 * score, 12),
                    "source": "leanstral_hammer_failure_mode",
                }
            )
        for premise_hint in _string_sequence(candidate.get("premise_hints"))[:6]:
            premise_feature = f"leanstral:hammer_premise_hint:{_feature_key_part(premise_hint)}"
            feature_groups["leanstral_hammer_premise_hints"].append(premise_feature)
            features.append(
                {
                    "feature": premise_feature,
                    "score": round(0.5 * score, 12),
                    "source": "leanstral_hammer_premise_hint",
                }
            )

    for hint in deterministic_rule_hints:
        hint_action = _feature_key_part(hint.get("action") or "rule_hint")
        hint_target = _feature_key_part(hint.get("target_component") or target_component)
        feature = f"leanstral:rule_hint:{hint_action}:{hint_target}"
        feature_groups["leanstral_rule_hints"].append(feature)
        features.append(
            {
                "feature": feature,
                "score": round(0.9 * trust_score, 12),
                "source": "leanstral_rule_hint",
                "target_component": target_component,
            }
        )

    if action:
        action_feature = f"leanstral:action:{_feature_key_part(action)}"
        feature_groups.setdefault("leanstral_actions", []).append(action_feature)
        features.append(
            {
                "feature": action_feature,
                "score": round(0.85 * trust_score, 12),
                "source": "leanstral_compiler_change_spec",
                "target_component": target_component,
            }
        )
    for metric in target_metrics:
        feature = f"leanstral:target_metric:{_feature_key_part(metric)}"
        feature_groups["leanstral_target_metrics"].append(feature)
        features.append(
            {
                "feature": feature,
                "score": round(0.75 * trust_score, 12),
                "source": "leanstral_target_metric",
            }
        )
    for template in theorem_templates:
        feature = f"leanstral:theorem_template:{_feature_key_part(template)}"
        feature_groups["leanstral_theorem_templates"].append(feature)
        features.append(
            {
                "feature": feature,
                "score": round(0.65 * trust_score, 12),
                "source": "leanstral_theorem_template",
            }
        )
    for obligation_id in proof_obligation_ids[:8]:
        feature = f"leanstral:proof_obligation:{_feature_key_part(obligation_id)}"
        feature_groups["leanstral_proof_obligations"].append(feature)
        features.append(
            {
                "feature": feature,
                "score": round(0.55 * trust_score, 12),
                "source": "leanstral_proof_obligation",
            }
        )

    feature_groups = {
        key: _unique_string_values(values)
        for key, values in feature_groups.items()
        if values
    }
    return _dedupe_guidance_features(features), feature_groups


def _dedupe_guidance_features(features: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    deduped: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in sorted(
        (dict(feature) for feature in features if isinstance(feature, Mapping)),
        key=lambda feature: (
            -float(feature.get("score", 0.0) or 0.0),
            str(feature.get("feature") or ""),
        ),
    ):
        feature_name = str(item.get("feature") or "").strip()
        if not feature_name or feature_name in seen:
            continue
        seen.add(feature_name)
        deduped.append(item)
    return deduped


def _feature_key_part(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "_", text).strip("_")
    return text[:96] or "unknown"


def _drafted_logic_candidate_copies_source_span(
    candidate_text: str,
    source_span: str,
) -> bool:
    candidate = _plain_text_tokens(candidate_text)
    source = _plain_text_tokens(source_span)
    if len(candidate) < 40 or len(source) < 40:
        return False
    if candidate in source:
        return True
    candidate_terms = {term for term in candidate.split() if len(term) >= 4}
    source_terms = {term for term in source.split() if len(term) >= 4}
    if len(candidate_terms) < 8 or not source_terms:
        return False
    overlap = candidate_terms & source_terms
    return len(overlap) / len(candidate_terms) >= 0.75


def _plain_text_tokens(value: Any) -> str:
    return " ".join(re.findall(r"[A-Za-z0-9]+", str(value or "").lower()))


def _action_from_focus(value: Any, losses: Mapping[str, float]) -> str:
    focus = {str(item) for item in value or ()}
    if "repair_multiview_legal_ir_prover_gate" in focus:
        return "repair_multiview_legal_ir_prover_gate"
    if "repair_multiview_legal_ir_graph_projection" in focus:
        return "repair_multiview_legal_ir_graph_projection"
    if "repair_multiview_legal_ir_loss" in focus or "legal_ir_multiview" in focus:
        return "repair_multiview_legal_ir_loss"
    if "semantic_decompiler" in focus:
        return "refine_semantic_decompiler_reconstruction"
    if "autoencoder_embedding_head" in focus:
        return "refine_typed_ir_or_decompiler_slots"
    if float(losses.get("source_decompiled_text_token_loss", 0.0)) > 0.0:
        return "refine_semantic_decompiler_reconstruction"
    return ""


def _unified_diff_paths(diff: str) -> Sequence[str]:
    paths: list[str] = []
    for line in str(diff or "").splitlines():
        if not (line.startswith("--- ") or line.startswith("+++ ")):
            continue
        raw_path = line[4:].split("\t", 1)[0].strip()
        if raw_path == "/dev/null":
            continue
        if raw_path.startswith(("a/", "b/")):
            raw_path = raw_path[2:]
        if not raw_path or raw_path.startswith("/") or ".." in Path(raw_path).parts:
            return ()
        if raw_path not in paths:
            paths.append(raw_path)
    return tuple(paths)


def _well_formed_target_statement(
    modal_formula: Mapping[str, Any],
    *,
    source_span: str,
) -> str:
    operator = modal_formula.get("operator", {})
    predicate = modal_formula.get("predicate", {})
    operator = operator if isinstance(operator, Mapping) else {}
    predicate = predicate if isinstance(predicate, Mapping) else {}
    formula_literal = (
        "{ "
        + f"formulaId := {_lean_string(modal_formula.get('formula_id'))}, "
        + f"family := {_lean_string(operator.get('family'))}, "
        + f"system := {_lean_string(operator.get('system'))}, "
        + f"symbol := {_lean_string(operator.get('symbol'))}, "
        + f"predicate := {_lean_string(predicate.get('name'))}, "
        + f"sourceSpan := {_lean_string(source_span)} "
        + "}"
    )
    return (
        "LegalIR.wellFormed { "
        + formula_literal[2:]
        + " /\\ LegalIR.modalityMatches "
        + formula_literal
        + f" {_lean_string(operator.get('family'))} {_lean_string(operator.get('symbol'))}"
        + " /\\ LegalIR.sourceProvenancePresent "
        + formula_literal
    )


def _render_theorem_registry_source(
    registry: Optional[Mapping[str, Any] | LeanstralTheoremRegistry],
    theorem_proofs: Mapping[str, str],
) -> str:
    if not theorem_proofs or registry is None:
        return ""
    if isinstance(registry, LeanstralTheoremRegistry):
        return registry.render_lean_source(theorem_proofs)
    raw_theorems = registry.get("theorems", ()) if isinstance(registry, Mapping) else ()
    if not isinstance(raw_theorems, Sequence) or isinstance(raw_theorems, (str, bytes)):
        return ""
    theorem_blocks: list[str] = []
    for theorem in raw_theorems:
        if not isinstance(theorem, Mapping):
            continue
        theorem_id = str(theorem.get("theorem_id", "")).strip()
        proof = str(theorem_proofs.get(theorem_id, "")).strip()
        if not proof:
            continue
        theorem_name = str(theorem.get("theorem_name", "")).strip()
        statement = str(theorem.get("statement", "")).strip()
        if not theorem_name or not statement:
            continue
        theorem_blocks.append(f"theorem {theorem_name} : {statement} := {proof}")
    if not theorem_blocks:
        return ""
    return (
        LEGAL_IR_THEOREM_LEAN_KERNEL
        + "\nnamespace LegalIR\n\n"
        + "\n\n".join(theorem_blocks)
        + "\n\nend LegalIR\n"
    )


def _lean_string(value: Any) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def _leanstral_prompt(task: LegalIRLeanTask) -> str:
    payload = {
        "allowed_rule_hint_actions": sorted(_ALLOWED_RULE_HINT_ACTIONS),
        "instructions": [
            "Return strict JSON only.",
            "Return a Lean proof body beginning with by for the fixed theorem.",
            "For concrete String.length goals, prefer simp with String.length over decide, which can elaborate very slowly.",
            "Optional theorem_proofs may map verifier theorem IDs to Lean proof bodies only.",
            "Do not return theorem statements, Lean source files, imports, namespaces, or theorem declarations.",
            "Do not change the theorem, introduce axioms, imports, sorry, admit, or executable tactics.",
            "Rule hints are review-only and must be grounded in the supplied modal IR and source span.",
            "Optionally include drafted_logic_candidates as guidance-only compact frame/modal/deontic/TDFOL/KG/CEC/prover logic.",
            "Drafted logic candidates must use abstract predicates, slots, symbols, hashes, or theorem IDs; do not copy full source text spans.",
            "Every drafted_logic_candidate must cite Legal IR proof_obligation_ids when available and include premise_hints, target_view, logic_family, compiler_surface, expected_failure_mode, confidence, and source-copy metadata.",
            "When compiler_change_spec.patchable is false, do not propose a code change.",
            "When compiler_change_spec.patchable is true, rule hints may only target its allowed_paths and target_component.",
            "Set compiler_change_spec_id to task.compiler_change_spec.spec_id exactly.",
        ],
        "drafted_logic_candidate_shape": {
            "candidate": "obligation(actor, action) unless exception_condition",
            "compiler_surface": "task.compiler_change_spec.target_component",
            "confidence": 0.0,
            "expected_failure_mode": "hammer_unproved | syntax_rejected | reconstruction_failed | source_copy_rejected | unknown",
            "intended_use": "guidance_only",
            "logic_family": "deontic",
            "premise_hints": _first_proof_obligation_hints(task),
            "proof_obligation_id": _first_proof_obligation_id(task),
            "proof_obligation_ids": [_first_proof_obligation_id(task)] if _first_proof_obligation_id(task) else [],
            "schema_version": LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION,
            "source_copy_policy": "reject_full_span_copy",
            "source_copy_rejected": False,
            "target_view": _first_proof_obligation_value(task, "legal_ir_view", "modal.frame_logic"),
        },
        "proposal_schema_version": LEANSTRAL_PROPOSAL_SCHEMA_VERSION,
        "python_patch_shape": {
            "compiler_change_spec_id": "task.compiler_change_spec.spec_id",
            "summary": "short description",
            "unified_diff": "standard unified diff, only for allowed_paths",
        },
        "task": task.to_dict(),
        "trusted_lean_kernel": _LEGAL_IR_LEAN_KERNEL,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def verify_leanstral_audit(*args: Any, **kwargs: Any) -> Any:
    """Verify a structured Leanstral audit with local deterministic checkers."""

    from .leanstral_verifier import verify_leanstral_audit as _verify

    return _verify(*args, **kwargs)


def validate_leanstral_projected_change(*args: Any, **kwargs: Any) -> Any:
    """Validate a projected Leanstral compiler diff in an isolated worktree."""

    from .leanstral_validation import validate_leanstral_projected_change as _validate

    return _validate(*args, **kwargs)


def compare_leanstral_holdout_pareto(*args: Any, **kwargs: Any) -> Any:
    """Compare candidate held-out LegalIR metrics against a frozen baseline."""

    from .leanstral_validation import compare_leanstral_holdout_pareto as _compare

    return _compare(*args, **kwargs)


def __getattr__(name: str) -> Any:
    projected_validation_exports = {
        "LeanstralMetricComparison",
        "LeanstralProjectedChangeValidation",
        "LeanstralProjectedChangeValidator",
        "LeanstralProjectedValidationConfig",
        "LeanstralValidationCheck",
        "LeanstralValidationReason",
    }
    if name in projected_validation_exports:
        from . import leanstral_validation

        return getattr(leanstral_validation, name)
    raise AttributeError(name)


__all__ = [
    "LEANSTRAL_DRAFT_GUIDANCE_SCHEMA_VERSION",
    "LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION",
    "LEANSTRAL_PROPOSAL_SCHEMA_VERSION",
    "CompilerChangeSpec",
    "LegalIRLeanTask",
    "LeanstralConfig",
    "LeanstralDraftGuidance",
    "LeanstralMetricComparison",
    "LeanstralProjectedChangeValidation",
    "LeanstralProjectedChangeValidator",
    "LeanstralProjectedValidationConfig",
    "LeanstralProofValidation",
    "LeanstralProposal",
    "LeanstralShadowResult",
    "LeanstralShadowRunner",
    "LeanstralValidationCheck",
    "LeanstralValidationReason",
    "ProjectionEvidence",
    "PythonPatchProposal",
    "PythonPatchValidation",
    "compare_leanstral_holdout_pareto",
    "leanstral_draft_guidance",
    "merge_leanstral_guidance_into_compiler_guidance",
    "validate_leanstral_projected_change",
    "validate_leanstral_proposal",
    "validate_python_patch_proposal",
    "verify_leanstral_audit",
]
