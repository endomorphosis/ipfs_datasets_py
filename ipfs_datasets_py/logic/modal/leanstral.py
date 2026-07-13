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

from .leanstral_theorems import (
    LEGAL_IR_THEOREM_LEAN_KERNEL,
    LeanstralTheoremRegistry,
    generate_legal_semantics_theorem_registry,
    lean_theorem_proof_rejection_reasons,
)


LEANSTRAL_PROPOSAL_SCHEMA_VERSION = "legal-ir-leanstral-proposal-v1"
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
    provider: str = "mistral_vibe"
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
            theorem_proofs=normalized_theorem_proofs,
            forbidden_statement_keys=forbidden_statement_keys,
            notes=str(data.get("notes", "")).strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compiler_change_spec_id": self.compiler_change_spec_id,
            "deterministic_rule_hints": [dict(hint) for hint in self.deterministic_rule_hints],
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
class LeanstralShadowResult:
    """Auditable output of a shadow-only autoencoder-to-Leanstral pass."""

    task: LegalIRLeanTask
    proposal: Optional[LeanstralProposal]
    validation: LeanstralProofValidation
    llm_called: bool
    raw_response: str = ""
    artifact_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
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
            return LeanstralShadowResult(
                task=task,
                proposal=None,
                validation=LeanstralProofValidation(
                    accepted=False,
                    reasons=("leanstral_shadow_disabled",),
                ),
                llm_called=False,
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
        artifact_path = self._write_artifact(
            task=task,
            proposal=proposal,
            validation=validation,
            raw_response=raw_response,
        )
        return LeanstralShadowResult(
            task=task,
            proposal=proposal,
            validation=validation,
            llm_called=True,
            raw_response=raw_response,
            artifact_path=artifact_path,
        )

    def _write_artifact(
        self,
        *,
        task: LegalIRLeanTask,
        proposal: Optional[LeanstralProposal],
        validation: LeanstralProofValidation,
        raw_response: str,
    ) -> Optional[str]:
        if not self.config.artifact_dir:
            return None
        directory = Path(self.config.artifact_dir).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{task.task_id}.json"
        payload = {
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
            "When compiler_change_spec.patchable is false, do not propose a code change.",
            "When compiler_change_spec.patchable is true, rule hints may only target its allowed_paths and target_component.",
            "Set compiler_change_spec_id to task.compiler_change_spec.spec_id exactly.",
        ],
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
    "LEANSTRAL_PROPOSAL_SCHEMA_VERSION",
    "CompilerChangeSpec",
    "LegalIRLeanTask",
    "LeanstralConfig",
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
    "validate_leanstral_projected_change",
    "validate_leanstral_proposal",
    "validate_python_patch_proposal",
    "verify_leanstral_audit",
]
