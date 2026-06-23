"""Deterministic compiler for legal text into modal IR.

This module is deliberately rule-based and auditable.  It can surface
ambiguities for a neural or human advisor, but it does not use adaptive weights
to decide the canonical IR.
"""

from __future__ import annotations

import math
import sys
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
    BM25FrameSelector,
    DEFAULT_LEGAL_FRAME_FIXTURE,
    FrameSelection,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_modal_parser import (
    LegalModalParser,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFrame,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_weak_typed_self_family_cue_margin_buffer,
    compiler_required_adaptive_ambiguity_targets,
    DEFAULT_MODAL_REGISTRY,
    is_compiler_ambiguity_policy_pair,
    ModalLogicFamily,
    ModalRegistry,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    is_normative_modal_family,
    prefers_contested_zero_margin_adaptive_ambiguity_pair,
    priority_signal_free_adaptive_ambiguity_targets,
    signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    SpaCyLegalEncoder,
    SpaCyLegalEncoding,
    SpaCyModalDecoder,
    SpaCyModalIRCompiler,
    modal_ambiguity_signals,
    ranked_modal_families,
)


def _current_compiler_attr(name: str, fallback: Any) -> Any:
    """Resolve patchable policy hooks from the current compiler module.

    Some import-quiet tests intentionally purge ``ipfs_datasets_py.*`` from
    ``sys.modules`` and re-import a fresh package while already-imported test
    modules still hold older class objects. Looking up monkeypatchable hooks
    through ``sys.modules`` keeps those old class objects aligned with the
    current module-level policy functions.
    """

    module = sys.modules.get(__name__)
    if module is None:
        return fallback
    return getattr(module, name, fallback)


def _modal_ambiguity_signals(encoding: SpaCyLegalEncoding) -> Mapping[str, bool]:
    resolver = _current_compiler_attr("modal_ambiguity_signals", modal_ambiguity_signals)
    return resolver(encoding)


def _canonical_modal_family_token(value: Any) -> str:
    """Normalize modal-family tokens for policy table lookups."""
    resolved = str(value or "").strip()
    if not resolved:
        return ""
    if "->" in resolved:
        _, target_family = resolved.split("->", maxsplit=1)
        target_family = target_family.strip()
        if target_family:
            resolved = target_family
    candidate_tokens: List[str] = []
    seen_tokens: set[str] = set()

    def _remember(token: str) -> None:
        normalized = str(token).strip()
        if not normalized or normalized in seen_tokens:
            return
        seen_tokens.add(normalized)
        candidate_tokens.append(normalized)

    leaf_dot = resolved.rsplit(".", maxsplit=1)[-1].strip()
    leaf_colon = leaf_dot.rsplit(":", maxsplit=1)[-1].strip()
    leaf_slash = leaf_colon.rsplit("/", maxsplit=1)[-1].strip()
    leaf_pipe = leaf_slash.rsplit("|", maxsplit=1)[-1].strip()
    split_tokens: List[str] = []
    for delimiter in (".", ":", "/", "|"):
        if delimiter not in resolved:
            continue
        split_tokens.extend(
            part.strip()
            for part in resolved.split(delimiter)
            if str(part).strip()
        )
    for token in (
        resolved,
        leaf_dot,
        leaf_colon,
        leaf_slash,
        leaf_pipe,
        *split_tokens,
    ):
        _remember(token)
        lowered = token.lower()
        _remember(lowered)
        _remember(lowered.replace("-", "_").replace(" ", "_"))

    for candidate in candidate_tokens:
        try:
            return ModalLogicFamily(candidate).value
        except ValueError:
            continue
    return leaf_pipe.lower().replace("-", "_").replace(" ", "_")


def _priority_signal_free_adaptive_ambiguity_targets(family: str) -> Sequence[str]:
    resolver = _current_compiler_attr(
        "priority_signal_free_adaptive_ambiguity_targets",
        priority_signal_free_adaptive_ambiguity_targets,
    )
    return tuple(resolver(family))


def _compiler_required_adaptive_ambiguity_targets(family: str) -> Sequence[str]:
    resolver = _current_compiler_attr(
        "compiler_required_adaptive_ambiguity_targets",
        compiler_required_adaptive_ambiguity_targets,
    )
    return tuple(resolver(family))


def _signal_free_adaptive_ambiguity_targets(family: str) -> Sequence[str]:
    resolver = _current_compiler_attr(
        "signal_free_adaptive_ambiguity_targets",
        signal_free_adaptive_ambiguity_targets,
    )
    return tuple(resolver(family))


def _compiler_ambiguity_policy_targets(family: str) -> Sequence[str]:
    resolver = _current_compiler_attr(
        "compiler_ambiguity_policy_targets",
        compiler_ambiguity_policy_targets,
    )
    return tuple(resolver(family))


def _compiler_refined_modal_family_cue_margin_buffer(
    predicted_family: str,
    target_family: str,
) -> float:
    resolver = _current_compiler_attr(
        "compiler_refined_modal_family_cue_margin_buffer",
        compiler_refined_modal_family_cue_margin_buffer,
    )
    try:
        resolved = float(resolver(predicted_family, target_family))
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(resolved):
        return 0.0
    return max(0.0, resolved)


def _compiler_weak_typed_self_family_cue_margin_buffer(
    predicted_family: str,
    target_family: str,
) -> float:
    resolver = _current_compiler_attr(
        "compiler_weak_typed_self_family_cue_margin_buffer",
        compiler_weak_typed_self_family_cue_margin_buffer,
    )
    try:
        resolved = float(resolver(predicted_family, target_family))
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(resolved):
        return 0.0
    return max(0.0, resolved)


def _is_priority_signal_free_adaptive_ambiguity_pair(
    predicted_family: str,
    target_family: str,
) -> bool:
    return _canonical_modal_family_token(
        target_family
    ) in _priority_signal_free_adaptive_ambiguity_targets(
        predicted_family
    )


def _is_compiler_required_adaptive_ambiguity_pair(
    predicted_family: str,
    target_family: str,
) -> bool:
    return _canonical_modal_family_token(
        target_family
    ) in _compiler_required_adaptive_ambiguity_targets(
        predicted_family
    )


def _is_compiler_ambiguity_policy_pair(
    predicted_family: str,
    target_family: str,
) -> bool:
    resolver = _current_compiler_attr(
        "is_compiler_ambiguity_policy_pair",
        is_compiler_ambiguity_policy_pair,
    )
    return bool(resolver(predicted_family, target_family))


def _is_signal_free_adaptive_ambiguity_pair(
    predicted_family: str,
    target_family: str,
) -> bool:
    resolver = _current_compiler_attr(
        "is_signal_free_adaptive_ambiguity_pair",
        is_signal_free_adaptive_ambiguity_pair,
    )
    return bool(resolver(predicted_family, target_family))


def _prefers_contested_zero_margin_adaptive_ambiguity_pair(
    predicted_family: str,
    target_family: str,
) -> bool:
    resolver = _current_compiler_attr(
        "prefers_contested_zero_margin_adaptive_ambiguity_pair",
        prefers_contested_zero_margin_adaptive_ambiguity_pair,
    )
    return bool(resolver(predicted_family, target_family))


def _supports_signal_free_adaptive_ambiguity_pair(
    predicted_family: str,
    target_family: str,
) -> bool:
    resolved_target_family = _canonical_modal_family_token(target_family)
    return (
        _is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            resolved_target_family,
        )
        or _is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            resolved_target_family,
        )
        or resolved_target_family
        in _signal_free_adaptive_ambiguity_targets(predicted_family)
        or _is_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            resolved_target_family,
        )
        or _is_compiler_ambiguity_policy_pair(
            predicted_family,
            resolved_target_family,
        )
    )


@dataclass(frozen=True)
class ModalCompilerConfig:
    """Configuration for deterministic modal compilation."""

    parser_backend: str = "spacy"
    spacy_model_name: str = "en_core_web_sm"
    top_k_frames: int = 3
    frame_domain: Optional[str] = None
    frame_score_margin: float = 0.05
    modal_family_share_margin: float = 0.34
    modal_family_secondary_share_floor: float = 0.2
    modal_primary_family_margin: float = 0.15
    modal_adaptive_family_margin: float = 0.15
    modal_primary_family_outvote_margin: float = 0.0
    modal_conditional_target_family_outvote_margin: float = 0.0
    modal_deontic_target_family_outvote_margin: float = 0.0
    modal_dynamic_target_family_outvote_margin: float = 0.0
    modal_alethic_target_family_outvote_margin: float = 0.0
    modal_temporal_target_family_outvote_margin: float = 0.0
    modal_frame_target_family_outvote_margin: float = 0.0


@dataclass(frozen=True)
class ModalCompilationAmbiguity:
    """A compiler-detected ambiguity requiring review or advisor help."""

    ambiguity_type: str
    message: str
    candidate_ids: List[str] = field(default_factory=list)
    severity: str = "review"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModalCompilationResult:
    """Result of deterministic legal text compilation."""

    modal_ir: ModalIRDocument
    parser_name: str
    normalized_text: str
    frame_candidates: List[Dict[str, Any]]
    selected_frame: Optional[str]
    ambiguities: List[ModalCompilationAmbiguity] = field(default_factory=list)
    encoding: Optional[SpaCyLegalEncoding] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ambiguities": [ambiguity.to_dict() for ambiguity in self.ambiguities],
            "encoding": self.encoding.to_dict() if self.encoding is not None else None,
            "frame_candidates": list(self.frame_candidates),
            "metadata": dict(sorted(self.metadata.items())),
            "modal_ir": self.modal_ir.to_dict(),
            "normalized_text": self.normalized_text,
            "parser_name": self.parser_name,
            "selected_frame": self.selected_frame,
        }


class DeterministicModalCompiler:
    """Compile legal text into modal IR with explainable frame selection."""

    def __init__(
        self,
        config: Optional[ModalCompilerConfig] = None,
        *,
        registry: ModalRegistry = DEFAULT_MODAL_REGISTRY,
        frame_selector: Optional[BM25FrameSelector] = None,
    ) -> None:
        self.config = config or ModalCompilerConfig()
        self.registry = registry
        self.parser = LegalModalParser(registry=registry)
        self.encoder = SpaCyLegalEncoder(
            model_name=self.config.spacy_model_name,
            registry=registry,
        )
        self.decoder = SpaCyModalDecoder()
        self.ir_compiler = SpaCyModalIRCompiler()
        self.frame_selector = frame_selector or BM25FrameSelector(DEFAULT_LEGAL_FRAME_FIXTURE)

    def compile(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "legal_text",
    ) -> ModalCompilationResult:
        """Compile text into modal IR using deterministic rules only."""
        normalized_text = self.parser.normalize_text(text)
        backend = self.config.parser_backend.lower().strip()
        encoding: Optional[SpaCyLegalEncoding] = self.encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
        )
        if backend in {"regex", "legal", "legal_modal_parser", "deontic", "deontic:d"}:
            modal_ir = self.parser.parse(
                text,
                document_id=document_id or encoding.document_id,
                citation=citation,
                source=source,
            )
            parser_name = "legal_modal_parser_v1"
        else:
            modal_ir = self.ir_compiler.compile(encoding)
            parser_name = "spacy_modal_codec_v1"

        frame_selections = self.frame_selector.rank(
            normalized_text,
            top_k=self.config.top_k_frames,
            domain=self.config.frame_domain,
        )
        frame_candidates = [selection.to_dict() for selection in frame_selections]
        selected_frame = str(frame_candidates[0]["frame_id"]) if frame_candidates else None
        ambiguities = [
            *self._formula_ambiguities(modal_ir),
            *self._family_ambiguities(
                encoding,
                modal_ir=modal_ir,
                frame_selections=frame_selections,
            ),
            *self._frame_ambiguities(frame_selections),
        ]
        if normalized_text and not modal_ir.formulas:
            ambiguities.append(
                ModalCompilationAmbiguity(
                    ambiguity_type="missing_modal_formula",
                    message="No deterministic modal formula was produced for non-empty text.",
                    severity="requires_rule",
                )
            )

        modal_ir = self._attach_metadata(
            modal_ir,
            frame_selections,
            parser_name=parser_name,
            selected_frame=selected_frame,
            ambiguity_count=len(ambiguities),
            encoding=encoding,
        )
        return ModalCompilationResult(
            modal_ir=modal_ir,
            parser_name=parser_name,
            normalized_text=normalized_text,
            frame_candidates=frame_candidates,
            selected_frame=selected_frame,
            ambiguities=ambiguities,
            encoding=encoding,
            metadata={
                "ambiguity_count": len(ambiguities),
                "deterministic_compiler": "modal_compiler_v1",
                "frame_selector": "bm25_v1",
                "llm_call_count": 0,
                "parser_backend": self.config.parser_backend,
            },
        )

    def _attach_metadata(
        self,
        modal_ir: ModalIRDocument,
        frame_selections: Sequence[FrameSelection],
        *,
        parser_name: str,
        selected_frame: Optional[str],
        ambiguity_count: int,
        encoding: SpaCyLegalEncoding,
    ) -> ModalIRDocument:
        frame_candidates = [
            ModalIRFrame(
                frame_id=selection.frame.frame_id,
                score=selection.score,
                matched_terms=list(selection.matched_terms),
                explanation=selection.explanation,
            )
            for selection in frame_selections
        ]
        metadata = {
            **modal_ir.metadata,
            "ambiguity_count": ambiguity_count,
            "deterministic_compiler": "modal_compiler_v1",
            "deterministic_parser": parser_name,
            "frame_selector": "bm25_v1",
            "llm_call_count": 0,
            "modal_family_counts": encoding.modal_family_counts(),
            "selected_frame": selected_frame,
        }
        return replace(modal_ir, frame_candidates=frame_candidates, metadata=metadata)

    def _formula_ambiguities(
        self,
        modal_ir: ModalIRDocument,
    ) -> List[ModalCompilationAmbiguity]:
        by_span: Dict[tuple[int, int], List[str]] = {}
        for formula in modal_ir.formulas:
            span = (formula.provenance.start_char, formula.provenance.end_char)
            candidate = (
                f"{formula.formula_id}:{formula.operator.family}:"
                f"{formula.operator.system}:{formula.operator.symbol}"
            )
            by_span.setdefault(span, []).append(candidate)

        ambiguities: List[ModalCompilationAmbiguity] = []
        for span, candidates in sorted(by_span.items()):
            families = {candidate.split(":")[1] for candidate in candidates}
            if len(candidates) > 1 and len(families) > 1:
                ambiguities.append(
                    ModalCompilationAmbiguity(
                        ambiguity_type="multi_family_same_span",
                        message="Multiple modal families were compiled from the same text span.",
                        candidate_ids=sorted(candidates),
                        metadata={"span": list(span)},
                    )
                )
        return ambiguities

    @staticmethod
    def _ranking_share(candidate: Dict[str, Any]) -> float:
        """Return share value, preferring unrounded values when present."""
        raw_share = candidate.get("share_raw", candidate.get("share", 0.0))
        try:
            return float(raw_share)
        except (TypeError, ValueError):
            return 0.0

    def _family_ambiguities(
        self,
        encoding: SpaCyLegalEncoding,
        *,
        modal_ir: ModalIRDocument,
        frame_selections: Sequence[FrameSelection] = (),
    ) -> List[ModalCompilationAmbiguity]:
        ranking = ranked_modal_families(encoding)
        if not ranking:
            if not encoding.normalized_text:
                return []
            ambiguities = self._vacant_section_scope_ambiguities(
                encoding,
                modal_ir=modal_ir,
                ranking=(),
            )
            adaptive_ranking = self._adaptive_family_ranking_from_logits(encoding)
            if not adaptive_ranking:
                return ambiguities
            adaptive_family_shares = {
                str(candidate["family"]): self._ranking_share(candidate)
                for candidate in adaptive_ranking
            }
            return self._ensure_explicit_adaptive_ambiguities(
                [
                    *ambiguities,
                    *self._adaptive_family_margin_ambiguities(
                        encoding,
                        modal_ir=modal_ir,
                        ranking=adaptive_ranking,
                        family_shares=adaptive_family_shares,
                        frame_selections=frame_selections,
                        predicted_family_source="adaptive_logits_fallback",
                    ),
                ]
            )

        ambiguities: List[ModalCompilationAmbiguity] = []
        family_shares = {
            str(candidate["family"]): self._ranking_share(candidate)
            for candidate in ranking
        }
        if modal_ir.formulas:
            primary_family = str(modal_ir.formulas[0].operator.family)
            primary_share = next(
                (
                    self._ranking_share(candidate)
                    for candidate in ranking
                    if str(candidate["family"]) == primary_family
                ),
                0.0,
            )
            best_other = max(
                (
                    candidate
                    for candidate in ranking
                    if str(candidate["family"]) != primary_family
                ),
                key=lambda candidate: (
                    self._ranking_share(candidate),
                    str(candidate["family"]),
                ),
                default=None,
            )
            if best_other is not None:
                best_other_family = str(best_other["family"])
                best_other_share = self._ranking_share(best_other)
                family_margin = primary_share - best_other_share
                if family_margin < self.config.modal_primary_family_outvote_margin:
                    ambiguities.append(
                        ModalCompilationAmbiguity(
                            ambiguity_type="primary_modal_family_outvoted",
                            message=(
                                "Cue evidence favors a competing modal family over the primary "
                                "compiled family; interpretation requires review."
                            ),
                            candidate_ids=[primary_family, best_other_family],
                            severity="requires_rule",
                            metadata={
                                "best_other_family": best_other_family,
                                "best_other_share": round(best_other_share, 6),
                                "family_margin": round(family_margin, 6),
                                "family_ranking": ranking,
                                "outvote_margin_threshold": self.config.modal_primary_family_outvote_margin,
                                "primary_family": primary_family,
                                "primary_share": round(primary_share, 6),
                            },
                        )
                    )
                if family_margin <= self.config.modal_primary_family_margin:
                    ambiguities.append(
                        ModalCompilationAmbiguity(
                            ambiguity_type="low_primary_modal_family_margin",
                            message=(
                                "The primary compiled modal family has a low margin "
                                "against competing cue evidence."
                            ),
                            candidate_ids=[primary_family, best_other_family],
                            metadata={
                                "best_other_family": best_other_family,
                                "best_other_share": round(best_other_share, 6),
                                "family_margin": round(family_margin, 6),
                                "family_ranking": ranking,
                                "primary_family": primary_family,
                                "primary_family_margin_threshold": self.config.modal_primary_family_margin,
                                "primary_share": round(primary_share, 6),
                            },
                        )
                    )
        ambiguities.extend(
            self._temporal_target_family_ambiguities(
                encoding,
                ranking=ranking,
                family_shares=family_shares,
            )
        )
        ambiguities.extend(
            self._temporal_scope_target_family_ambiguities(
                encoding,
                ranking=ranking,
                family_shares=family_shares,
            )
        )
        ambiguities.extend(
            self._frame_scope_target_family_ambiguities(
                encoding,
                ranking=ranking,
                family_shares=family_shares,
            )
        )
        ambiguities.extend(
            self._conditional_scope_target_family_ambiguities(
                encoding,
                ranking=ranking,
                family_shares=family_shares,
            )
        )
        ambiguities.extend(
            self._deontic_scope_target_family_ambiguities(
                encoding,
                ranking=ranking,
                family_shares=family_shares,
            )
        )
        ambiguities.extend(
            self._temporal_deontic_scope_family_ambiguities(
                encoding,
                ranking=ranking,
                family_shares=family_shares,
            )
        )
        ambiguities.extend(
            self._dynamic_scope_target_family_ambiguities(
                encoding,
                ranking=ranking,
                family_shares=family_shares,
            )
        )
        ambiguities.extend(
            self._alethic_scope_target_family_ambiguities(
                encoding,
                ranking=ranking,
                family_shares=family_shares,
            )
        )
        ambiguities.extend(
            self._vacant_section_scope_ambiguities(
                encoding,
                modal_ir=modal_ir,
                ranking=ranking,
            )
        )
        ambiguities.extend(
            self._adaptive_family_margin_ambiguities(
                encoding,
                modal_ir=modal_ir,
                ranking=ranking,
                family_shares=family_shares,
                frame_selections=frame_selections,
                predicted_family_source="ranked_modal_families",
            )
        )
        adaptive_ranking = self._adaptive_family_ranking_from_logits(encoding)
        if adaptive_ranking:
            adaptive_family_shares = {
                str(candidate["family"]): self._ranking_share(candidate)
                for candidate in adaptive_ranking
            }
            ambiguities.extend(
                self._adaptive_family_margin_ambiguities(
                    encoding,
                    modal_ir=modal_ir,
                    ranking=adaptive_ranking,
                    family_shares=adaptive_family_shares,
                    frame_selections=frame_selections,
                    predicted_family_source="adaptive_logits",
                )
            )
        if len(ranking) < 2:
            return self._ensure_explicit_adaptive_ambiguities(ambiguities)

        top, runner_up = ranking[0], ranking[1]
        share_margin = self._ranking_share(top) - self._ranking_share(runner_up)
        if share_margin <= self.config.modal_family_share_margin:
            ambiguities.append(
                ModalCompilationAmbiguity(
                    ambiguity_type="close_modal_family_shares",
                    message="Top modal families are close enough that legal family selection is ambiguous.",
                    candidate_ids=[str(top["family"]), str(runner_up["family"])],
                    metadata={
                        "family_margin": round(share_margin, 6),
                        "family_ranking": ranking,
                        "share_margin": round(share_margin, 6),
                        "top_family": str(top["family"]),
                        "runner_up_family": str(runner_up["family"]),
                    },
                )
            )

        has_frame_formula = any(
            str(formula.operator.family) == ModalLogicFamily.FRAME.value
            for formula in modal_ir.formulas
        )
        if has_frame_formula:
            frame_share = family_shares.get(ModalLogicFamily.FRAME.value, 0.0)
            best_non_frame = max(
                (
                    candidate
                    for candidate in ranking
                    if str(candidate["family"]) != ModalLogicFamily.FRAME.value
                ),
                key=lambda candidate: (
                    self._ranking_share(candidate),
                    str(candidate["family"]),
                ),
                default=None,
            )
            if best_non_frame is not None:
                competing_family = str(best_non_frame["family"])
                competing_share = self._ranking_share(best_non_frame)
                frame_margin = frame_share - competing_share
                if frame_margin < self.config.modal_primary_family_outvote_margin:
                    ambiguities.append(
                        ModalCompilationAmbiguity(
                            ambiguity_type="frame_modal_family_outvoted",
                            message=(
                                "Cue evidence favors a non-frame modal family over the compiled "
                                "frame interpretation."
                            ),
                            candidate_ids=[ModalLogicFamily.FRAME.value, competing_family],
                            severity="requires_rule",
                            metadata={
                                "competing_family": competing_family,
                                "competing_share": round(competing_share, 6),
                                "family_margin": round(frame_margin, 6),
                                "family_ranking": ranking,
                                "frame_share": round(frame_share, 6),
                                "outvote_margin_threshold": self.config.modal_primary_family_outvote_margin,
                            },
                        )
                    )
                if frame_margin <= self.config.modal_primary_family_margin:
                    ambiguities.append(
                        ModalCompilationAmbiguity(
                            ambiguity_type="low_frame_modal_family_margin",
                            message=(
                                "Frame-family evidence is weak relative to competing modal cues; "
                                "family interpretation requires review."
                            ),
                            candidate_ids=[ModalLogicFamily.FRAME.value, competing_family],
                            metadata={
                                "competing_family": competing_family,
                                "competing_share": round(competing_share, 6),
                                "family_margin": round(frame_margin, 6),
                                "family_ranking": ranking,
                                "frame_share": round(frame_share, 6),
                                "primary_family_margin_threshold": self.config.modal_primary_family_margin,
                            },
                        )
                    )

            frame_family = ModalLogicFamily.FRAME.value
            top_family = (
                self._canonical_modal_family_name(ranking[0].get("family"))
                or str(ranking[0]["family"])
            )
            if top_family != frame_family:
                frame_policy_signals = _modal_ambiguity_signals(encoding)
                has_frame_bm25_support = self._has_frame_bm25_support(frame_selections)
                compiled_modal_families = {
                    self._canonical_modal_family_name(formula.operator.family)
                    or str(formula.operator.family)
                    for formula in modal_ir.formulas
                }
                frame_target_signals = self._adaptive_target_signal_by_family(
                    frame_family,
                    signals=frame_policy_signals,
                    has_frame_scope=bool(
                        frame_policy_signals.get("has_frame_context")
                        or frame_policy_signals.get("has_frame_cue")
                        or frame_policy_signals.get("has_statutory_scope_reference")
                        or has_frame_bm25_support
                    ),
                )
                for policy_target_family in self._ordered_policy_target_families(
                    frame_family
                ):
                    if policy_target_family == frame_family:
                        continue
                    has_policy_target_evidence = bool(
                        family_shares.get(policy_target_family, 0.0) > 0.0
                        or policy_target_family in compiled_modal_families
                        or frame_target_signals.get(policy_target_family)
                    )
                    if not has_policy_target_evidence:
                        continue
                    ambiguities.extend(
                        self._compiled_primary_family_adaptive_pair_ambiguities(
                            compiled_primary_family=frame_family,
                            competing_family=policy_target_family,
                            ranking=ranking,
                            family_shares=family_shares,
                            threshold=self.config.modal_adaptive_family_margin,
                            signals=frame_policy_signals,
                            has_frame_scope=bool(
                                frame_policy_signals.get("has_frame_context")
                                or frame_policy_signals.get("has_frame_cue")
                                or frame_policy_signals.get(
                                    "has_statutory_scope_reference"
                                )
                                or has_frame_bm25_support
                            ),
                            has_frame_bm25_support=has_frame_bm25_support,
                            compiled_modal_families=compiled_modal_families,
                            predicted_family_source="compiled_frame_family",
                        )
                    )

        strong_contenders = [
            candidate
            for candidate in ranking
            if self._ranking_share(candidate)
            >= self.config.modal_family_secondary_share_floor
        ]
        contender_families = {
            str(candidate["family"]) for candidate in strong_contenders
        }
        has_temporal = ModalLogicFamily.TEMPORAL.value in contender_families
        has_normative = any(
            is_normative_modal_family(str(candidate["family"]))
            for candidate in strong_contenders
        )
        runner_share = self._ranking_share(runner_up)
        if (
            has_temporal
            and has_normative
            and len(contender_families) > 1
        ):
            ambiguities.append(
                ModalCompilationAmbiguity(
                    ambiguity_type="temporal_normative_overlap",
                    message=(
                        "Temporal scope and normative force both have strong cue evidence; "
                        "family interpretation requires review."
                    ),
                    candidate_ids=sorted(contender_families),
                    metadata={
                        "family_ranking": ranking,
                        "runner_up_share": round(runner_share, 6),
                        "secondary_share_floor": self.config.modal_family_secondary_share_floor,
                    },
                )
            )
        return self._ensure_explicit_adaptive_ambiguities(ambiguities)

    def _vacant_section_scope_ambiguities(
        self,
        encoding: SpaCyLegalEncoding,
        *,
        modal_ir: ModalIRDocument,
        ranking: Sequence[Dict[str, Any]],
    ) -> List[ModalCompilationAmbiguity]:
        signals = _modal_ambiguity_signals(encoding)
        if not bool(signals.get("has_vacant_section_scope")):
            return []
        compiled_families = sorted(
            {
                self._canonical_modal_family_name(formula.operator.family)
                or str(formula.operator.family)
                for formula in modal_ir.formulas
            }
        )
        candidate_ids = compiled_families or [ModalLogicFamily.FRAME.value]
        return [
            ModalCompilationAmbiguity(
                ambiguity_type="vacant_section_modal_scope",
                message=(
                    "A vacant statutory section contains editorial/status text; "
                    "compiled modal cues should be reviewed as non-operative scope."
                ),
                candidate_ids=candidate_ids,
                severity="requires_rule",
                metadata={
                    "ambiguity_policy_bundle": "compiler_ambiguity",
                    "compiled_modal_families": compiled_families,
                    "family_ranking": list(ranking),
                    "lexical_signals": dict(sorted(signals.items())),
                    "target_family": ModalLogicFamily.FRAME.value,
                },
            )
        ]

    @staticmethod
    def _adaptive_explicit_ambiguity_key(
        ambiguity: ModalCompilationAmbiguity,
    ) -> tuple[str, tuple[str, ...], str, str]:
        metadata = ambiguity.metadata if isinstance(ambiguity.metadata, dict) else {}
        return (
            str(ambiguity.ambiguity_type),
            tuple(str(candidate_id) for candidate_id in ambiguity.candidate_ids),
            str(metadata.get("adaptive_policy_pair") or ""),
            str(metadata.get("adaptive_predicted_family_source") or ""),
        )

    def _ensure_explicit_adaptive_ambiguities(
        self,
        ambiguities: Sequence[ModalCompilationAmbiguity],
    ) -> List[ModalCompilationAmbiguity]:
        """Backfill explicit adaptive ambiguity variants from base low-margin records."""
        resolved_ambiguities = list(ambiguities)
        existing_explicit_keys = {
            self._adaptive_explicit_ambiguity_key(ambiguity)
            for ambiguity in resolved_ambiguities
            if ambiguity.ambiguity_type.startswith("adaptive_")
            and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        }
        for ambiguity in list(resolved_ambiguities):
            if ambiguity.ambiguity_type != "adaptive_family_margin_low":
                continue
            metadata = (
                ambiguity.metadata
                if isinstance(ambiguity.metadata, dict)
                else {}
            )
            explicit_type = self._derive_explicit_adaptive_ambiguity_type(ambiguity)
            if not explicit_type:
                continue
            predicted_family, target_family, is_self_pair = (
                self._adaptive_policy_families(ambiguity)
            )
            explicit_candidate_ids = list(ambiguity.candidate_ids)
            if predicted_family and target_family:
                explicit_candidate_ids = (
                    [predicted_family]
                    if is_self_pair or predicted_family == target_family
                    else [predicted_family, target_family]
                )
            explicit_key = (
                explicit_type,
                tuple(str(candidate_id) for candidate_id in explicit_candidate_ids),
                str(metadata.get("adaptive_policy_pair") or ""),
                str(metadata.get("adaptive_predicted_family_source") or ""),
            )
            if explicit_key in existing_explicit_keys:
                continue
            explicit_message = (
                "Explicit adaptive low-margin ambiguity for the predicted modal "
                "family against close competing families."
                if bool(metadata.get("is_self_pair"))
                else (
                    "Explicit adaptive modal-family conflict between the predicted "
                    "family and a competing legal family."
                )
            )
            resolved_ambiguities.append(
                ModalCompilationAmbiguity(
                    ambiguity_type=explicit_type,
                    message=explicit_message,
                    candidate_ids=explicit_candidate_ids,
                    severity=ambiguity.severity,
                    metadata={
                        **metadata,
                        "predicted_family": (
                            predicted_family or metadata.get("predicted_family")
                        ),
                        "target_family": (
                            target_family or metadata.get("target_family")
                        ),
                        "is_explicit_adaptive_ambiguity": True,
                        "adaptive_base_ambiguity_type": "adaptive_family_margin_low",
                    },
                )
            )
            existing_explicit_keys.add(explicit_key)
        return resolved_ambiguities

    def _derive_explicit_adaptive_ambiguity_type(
        self,
        ambiguity: ModalCompilationAmbiguity,
    ) -> Optional[str]:
        """Resolve explicit adaptive ambiguity type from base metadata."""
        metadata = ambiguity.metadata if isinstance(ambiguity.metadata, dict) else {}
        explicit_type = str(metadata.get("explicit_ambiguity_type") or "").strip()
        if explicit_type and explicit_type != "adaptive_family_margin_low":
            return explicit_type

        predicted_family, target_family, is_self_pair = (
            self._adaptive_policy_families(ambiguity)
        )
        if is_self_pair and predicted_family and not target_family:
            target_family = predicted_family
        if not predicted_family or not target_family:
            return None

        margin_direction = str(metadata.get("adaptive_margin_direction") or "").strip().lower()
        if margin_direction not in {"contested", "outvoted"}:
            family_margin = metadata.get("family_margin_raw", metadata.get("family_margin"))
            try:
                margin_direction = "outvoted" if float(family_margin) <= 0.0 else "contested"
            except (TypeError, ValueError):
                margin_direction = "outvoted"
        return self._adaptive_margin_explicit_type(
            predicted_family,
            target_family,
            margin_direction,
        )

    @staticmethod
    def _canonical_modal_family_name(
        value: Any,
        *,
        prefer_target_side: bool = False,
    ) -> str:
        """Normalize modal family tokens for stable explicit ambiguity typing."""
        resolved = str(value or "").strip()
        if not resolved:
            return ""
        if "->" in resolved:
            source_family, _ = resolved.split("->", maxsplit=1)
            directional_side = source_family.strip()
            source_family, target_family = resolved.split("->", maxsplit=1)
            directional_side = target_family if prefer_target_side else source_family
            directional_side = directional_side.strip()
            if directional_side:
                resolved = directional_side
        candidate_tokens: List[str] = []
        seen_tokens: set[str] = set()

        def _remember(token: str) -> None:
            normalized = str(token).strip()
            if not normalized or normalized in seen_tokens:
                return
            seen_tokens.add(normalized)
            candidate_tokens.append(normalized)

        leaf_dot = resolved.rsplit(".", maxsplit=1)[-1].strip()
        leaf_colon = leaf_dot.rsplit(":", maxsplit=1)[-1].strip()
        leaf_slash = leaf_colon.rsplit("/", maxsplit=1)[-1].strip()
        leaf_pipe = leaf_slash.rsplit("|", maxsplit=1)[-1].strip()
        split_tokens: List[str] = []
        delimiters = ("->", ".", ":", "/", "|")
        for delimiter in delimiters:
            if delimiter not in resolved:
                continue
            split_tokens.extend(
                part.strip()
                for part in resolved.split(delimiter)
                if str(part).strip()
            )
        for token in (
            resolved,
            leaf_dot,
            leaf_colon,
            leaf_slash,
            leaf_pipe,
            *split_tokens,
        ):
            _remember(token)
            lowered = token.lower()
            _remember(lowered)
            _remember(lowered.replace("-", "_").replace(" ", "_"))
        for candidate in candidate_tokens:
            if not candidate:
                continue
            try:
                return ModalLogicFamily(candidate).value
            except ValueError:
                continue
        return leaf_pipe.lower().replace("-", "_").replace(" ", "_")

    @staticmethod
    def _canonical_registered_modal_family_name(
        value: Any,
        *,
        prefer_target_side: bool = False,
    ) -> str:
        """Resolve a canonical modal family only when it is registry-backed."""
        canonical_name = DeterministicModalCompiler._canonical_modal_family_name(
            value,
            prefer_target_side=prefer_target_side,
        )
        if not canonical_name:
            return ""
        try:
            return ModalLogicFamily(canonical_name).value
        except ValueError:
            return ""

    def _adaptive_policy_families(
        self,
        ambiguity: ModalCompilationAmbiguity,
    ) -> tuple[str, str, bool]:
        """Resolve canonical predicted/target family names from ambiguity metadata."""
        metadata = ambiguity.metadata if isinstance(ambiguity.metadata, dict) else {}
        predicted_family = self._canonical_registered_modal_family_name(
            metadata.get("predicted_family")
        )
        target_family = self._canonical_registered_modal_family_name(
            metadata.get("target_family"),
            prefer_target_side=True,
        )
        if not predicted_family and ambiguity.candidate_ids:
            predicted_family = self._canonical_registered_modal_family_name(
                ambiguity.candidate_ids[0]
            )
        if not target_family and len(ambiguity.candidate_ids) > 1:
            target_family = self._canonical_registered_modal_family_name(
                ambiguity.candidate_ids[1],
                prefer_target_side=True,
            )

        policy_pair = str(metadata.get("adaptive_policy_pair") or "").strip()
        if "->" in policy_pair:
            policy_predicted, policy_target = policy_pair.split("->", maxsplit=1)
            if not predicted_family:
                predicted_family = self._canonical_registered_modal_family_name(
                    policy_predicted
                )
            if not target_family:
                target_family = self._canonical_registered_modal_family_name(
                    policy_target,
                    prefer_target_side=True,
                )

        is_self_pair = bool(metadata.get("is_self_pair")) or (
            len(ambiguity.candidate_ids) == 1
        )
        return predicted_family, target_family, is_self_pair

    def _adaptive_family_ranking_from_logits(
        self,
        encoding: SpaCyLegalEncoding,
    ) -> List[Dict[str, float]]:
        """Build fallback family ranking from deterministic decoder logits."""
        modal_families = [family.value for family in ModalLogicFamily]
        logits = self.decoder.family_logits(
            encoding,
            modal_families=modal_families,
        )
        if not logits:
            return []
        max_logit = max(float(value) for value in logits.values())
        exp_by_family = {
            family: math.exp(float(logit) - max_logit)
            for family, logit in logits.items()
        }
        total = sum(exp_by_family.values())
        if total <= 0.0:
            return []
        ranking: List[Dict[str, float]] = []
        for family in sorted(
            exp_by_family,
            key=lambda key: (-exp_by_family[key], key),
        ):
            share_raw = exp_by_family[family] / total
            ranking.append(
                {
                    "family": family,
                    "count": 0,
                    "logit": round(float(logits[family]), 6),
                    "share_raw": share_raw,
                    "share": round(share_raw, 6),
                    "source": "logit_softmax_fallback",
                }
            )
        return ranking

    def _adaptive_family_margin_ambiguities(
        self,
        encoding: SpaCyLegalEncoding,
        *,
        modal_ir: ModalIRDocument,
        ranking: Sequence[Dict[str, Any]],
        family_shares: Dict[str, float],
        frame_selections: Sequence[FrameSelection] = (),
        predicted_family_source: str = "ranked_modal_families",
    ) -> List[ModalCompilationAmbiguity]:
        """Surface explicit ambiguities when strong legal families compete."""
        if not ranking:
            return []
        canonical_family_shares = self._canonicalized_family_shares(
            ranking=ranking,
            family_shares=family_shares,
        )
        predicted_family = self._canonical_modal_family_name(
            ranking[0].get("family")
        ) or str(ranking[0]["family"])
        predicted_family_shares_in_ranking = self._family_shares_in_ranking(
            ranking=ranking,
            family=predicted_family,
        )
        duplicate_predicted_family_share = (
            predicted_family_shares_in_ranking[1]
            if len(predicted_family_shares_in_ranking) > 1
            else None
        )
        predicted_share = float(
            canonical_family_shares.get(
                predicted_family,
                self._ranking_share(ranking[0]),
            )
        )
        if duplicate_predicted_family_share is not None:
            predicted_share = self._ranking_share(ranking[0])
        runner_up_family: Optional[str] = None
        runner_up_share = 0.0
        predicted_margin_to_runner_up: Optional[float] = None
        runner_up_candidate = max(
            (
                candidate
                for candidate in ranking
                if (
                    self._canonical_modal_family_name(candidate.get("family"))
                    or str(candidate.get("family", ""))
                )
                != predicted_family
            ),
            key=lambda candidate: (
                self._ranking_share(candidate),
                str(candidate.get("family", "")),
            ),
            default=None,
        )
        if runner_up_candidate is not None:
            runner_up_family = (
                self._canonical_modal_family_name(runner_up_candidate.get("family"))
                or str(runner_up_candidate.get("family", ""))
            )
            runner_up_share = float(
                canonical_family_shares.get(
                    runner_up_family,
                    self._ranking_share(runner_up_candidate),
                )
            )
            predicted_margin_to_runner_up = predicted_share - runner_up_share
        signals = _modal_ambiguity_signals(encoding)
        threshold = float(self.config.modal_adaptive_family_margin)
        has_frame_bm25_support = self._has_frame_bm25_support(frame_selections)
        compiled_modal_families = {
            self._canonical_modal_family_name(formula.operator.family)
            or str(formula.operator.family)
            for formula in modal_ir.formulas
        }
        compiled_primary_family = (
            (
                self._canonical_modal_family_name(
                    modal_ir.formulas[0].operator.family
                )
                or str(modal_ir.formulas[0].operator.family)
            )
            if modal_ir.formulas
            else None
        )
        has_frame_scope = bool(
            signals.get("has_frame_context")
            or signals.get("has_frame_cue")
            or signals.get("has_statutory_scope_reference")
            or has_frame_bm25_support
        )
        target_signal_by_family = self._adaptive_target_signal_by_family(
            predicted_family,
            signals=signals,
            has_frame_scope=has_frame_scope,
        )
        for policy_target_family in self._ordered_policy_target_families(
            predicted_family
        ):
            target_signal_by_family.setdefault(policy_target_family, False)
        ordered_target_families = self._ordered_adaptive_target_families(
            predicted_family=predicted_family,
            target_signal_by_family=target_signal_by_family,
        )
        ambiguities: List[ModalCompilationAmbiguity] = []
        for target_family in ordered_target_families:
            has_signal = bool(target_signal_by_family.get(target_family, False))
            is_self_pair = target_family == predicted_family
            pair_threshold = self._adaptive_pair_margin_threshold(
                predicted_family=predicted_family,
                target_family=target_family,
                base_threshold=threshold,
            )
            self_pair_margin = (
                duplicate_predicted_family_share - predicted_share
                if (
                    is_self_pair
                    and duplicate_predicted_family_share is not None
                )
                else (
                    predicted_margin_to_runner_up
                    if predicted_margin_to_runner_up is not None
                    else predicted_share
                )
            )
            runner_up_family_value = (
                predicted_family
                if (
                    is_self_pair
                    and duplicate_predicted_family_share is not None
                )
                else runner_up_family
            )
            weak_typed_self_family_buffer = (
                self._weak_typed_self_family_margin_buffer(
                    predicted_family=predicted_family,
                    target_family=target_family,
                    predicted_share=predicted_share,
                    compiled_primary_family=compiled_primary_family,
                )
                if is_self_pair
                else 0.0
            )
            pair_threshold += weak_typed_self_family_buffer
            pair_margin_buffer = max(0.0, pair_threshold - threshold)
            runner_up_is_priority_policy_pair = bool(
                is_self_pair
                and runner_up_family_value is not None
                and _is_priority_signal_free_adaptive_ambiguity_pair(
                    predicted_family,
                    runner_up_family_value,
                )
            )
            runner_up_is_compiler_required_policy_pair = bool(
                is_self_pair
                and runner_up_family_value is not None
                and _is_compiler_required_adaptive_ambiguity_pair(
                    predicted_family,
                    runner_up_family_value,
                )
            )
            if is_self_pair and (
                not self._adaptive_margin_within_threshold(
                    family_margin=self_pair_margin,
                    threshold=pair_threshold,
                )
            ):
                continue
            target_share = (
                duplicate_predicted_family_share
                if (
                    is_self_pair
                    and duplicate_predicted_family_share is not None
                )
                else float(canonical_family_shares.get(target_family, 0.0))
            )
            has_compiled_target_family_formula = target_family in compiled_modal_families
            has_target_signal_evidence = bool(
                has_signal
                or target_share > 0.0
                or has_compiled_target_family_formula
            )
            supports_signal_free_pair_policy = self._supports_signal_free_adaptive_pair(
                predicted_family,
                target_family,
            )
            direct_is_priority_policy_pair = _is_priority_signal_free_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )
            is_priority_policy_pair = (
                direct_is_priority_policy_pair
                or runner_up_is_priority_policy_pair
            )
            is_compiler_required_policy_pair = (
                _is_compiler_required_adaptive_ambiguity_pair(
                    predicted_family,
                    target_family,
                )
                or runner_up_is_compiler_required_policy_pair
            )
            if (
                not has_target_signal_evidence
                and not supports_signal_free_pair_policy
            ):
                continue
            family_margin = (
                self_pair_margin
                if is_self_pair
                else target_share - predicted_share
            )
            if not self._adaptive_margin_within_threshold(
                family_margin=family_margin,
                threshold=pair_threshold,
            ):
                continue
            margin_direction = self._adaptive_margin_direction(
                family_margin=family_margin,
                predicted_family=predicted_family,
                target_family=target_family,
                is_priority_policy_pair=is_priority_policy_pair,
                is_compiler_required_policy_pair=is_compiler_required_policy_pair,
                direct_is_priority_policy_pair=direct_is_priority_policy_pair,
                runner_up_is_priority_policy_pair=runner_up_is_priority_policy_pair,
            )
            requires_rule = margin_direction == "outvoted"
            explicit_type = self._adaptive_margin_explicit_type(
                predicted_family,
                target_family,
                margin_direction,
            )
            predicted_share_display = round(predicted_share, 6)
            target_share_display = round(target_share, 6)
            # Round the raw margin directly so metadata preserves tiny negative/positive
            # outvote deltas that can disappear when subtracting rounded shares.
            family_margin_display = round(family_margin, 6)
            candidate_ids = (
                [predicted_family]
                if is_self_pair
                else [predicted_family, target_family]
            )
            is_compiler_ambiguity_bundle_pair = _is_compiler_ambiguity_policy_pair(
                predicted_family,
                target_family,
            )
            runner_up_is_compiler_ambiguity_bundle_pair = bool(
                is_self_pair
                and runner_up_family_value is not None
                and _is_compiler_ambiguity_policy_pair(
                    predicted_family,
                    runner_up_family_value,
                )
            )
            effective_is_compiler_ambiguity_bundle_pair = (
                is_compiler_ambiguity_bundle_pair
                or runner_up_is_compiler_ambiguity_bundle_pair
            )
            effective_compiler_ambiguity_policy_pair = (
                f"{predicted_family}->{runner_up_family_value}"
                if runner_up_is_compiler_ambiguity_bundle_pair
                and runner_up_family_value is not None
                else f"{predicted_family}->{target_family}"
            )
            adaptive_priority = self._adaptive_margin_priority(
                family_margin=family_margin,
                threshold=threshold,
            )
            runner_up_share_value = (
                duplicate_predicted_family_share
                if (
                    is_self_pair
                    and duplicate_predicted_family_share is not None
                )
                else (runner_up_share if runner_up_family is not None else None)
            )
            predicted_margin_to_runner_up_value = (
                self_pair_margin if is_self_pair else predicted_margin_to_runner_up
            )
            base_metadata = {
                "adaptive_family_margin_threshold": threshold,
                "adaptive_effective_family_margin_threshold": pair_threshold,
                "adaptive_pair_margin_buffer": pair_margin_buffer,
                "weak_typed_self_family_margin_buffer": (
                    weak_typed_self_family_buffer
                ),
                "adaptive_margin_direction": margin_direction,
                "adaptive_margin_abs": abs(family_margin),
                "adaptive_priority": adaptive_priority,
                "priority": adaptive_priority,
                "adaptive_predicted_family_source": predicted_family_source,
                "adaptive_policy_pair": f"{predicted_family}->{target_family}",
                "explicit_ambiguity_type": explicit_type,
                "family_margin_raw": family_margin,
                "family_margin": family_margin_display,
                "family_ranking": list(ranking),
                "compiled_modal_families": sorted(compiled_modal_families),
                "has_target_signal_evidence": has_target_signal_evidence,
                "signal_free_pair_policy_applied": (
                    not has_target_signal_evidence
                    and supports_signal_free_pair_policy
                ),
                "has_compiled_target_family_formula": has_compiled_target_family_formula,
                "has_frame_bm25_support": has_frame_bm25_support,
                "lexical_signals": dict(sorted(signals.items())),
                "is_compiler_required_policy_pair": is_compiler_required_policy_pair,
                "runner_up_is_compiler_required_policy_pair": (
                    runner_up_is_compiler_required_policy_pair
                ),
                "is_priority_policy_pair": is_priority_policy_pair,
                "runner_up_is_priority_policy_pair": runner_up_is_priority_policy_pair,
                "is_compiler_ambiguity_bundle_pair": is_compiler_ambiguity_bundle_pair,
                "ambiguity_policy_bundle": (
                    "compiler_ambiguity"
                    if is_compiler_ambiguity_bundle_pair
                    else None
                ),
                "runner_up_is_compiler_ambiguity_bundle_pair": (
                    runner_up_is_compiler_ambiguity_bundle_pair
                ),
                "effective_is_compiler_ambiguity_bundle_pair": (
                    effective_is_compiler_ambiguity_bundle_pair
                ),
                "effective_compiler_ambiguity_policy_pair": (
                    effective_compiler_ambiguity_policy_pair
                ),
                "effective_ambiguity_policy_bundle": (
                    "compiler_ambiguity"
                    if effective_is_compiler_ambiguity_bundle_pair
                    else None
                ),
                "predicted_family": predicted_family,
                "predicted_margin_to_runner_up_raw": predicted_margin_to_runner_up_value,
                "predicted_margin_to_runner_up": (
                    round(predicted_margin_to_runner_up_value, 6)
                    if predicted_margin_to_runner_up_value is not None
                    else None
                ),
                "runner_up_family": runner_up_family_value,
                "runner_up_share_raw": runner_up_share_value,
                "runner_up_share": (
                    round(runner_up_share_value, 6)
                    if runner_up_share_value is not None
                    else None
                ),
                "predicted_share_raw": predicted_share,
                "predicted_share": predicted_share_display,
                "target_family": target_family,
                "target_share_raw": target_share,
                "target_share": target_share_display,
                "is_self_pair": is_self_pair,
            }
            base_message = (
                "A predicted modal family has a low lead over competing legal "
                "families; family selection is ambiguous."
                if is_self_pair
                else (
                    "A dominant modal family outvotes another legal modal family "
                    "despite competing scope/context evidence; family selection is "
                    "ambiguous."
                )
            )
            explicit_message = (
                "Explicit adaptive low-margin ambiguity for the predicted modal "
                "family against close competing families."
                if is_self_pair
                else (
                    "Explicit adaptive modal-family conflict between the predicted "
                    "family and a competing legal family."
                )
            )
            ambiguities.append(
                ModalCompilationAmbiguity(
                    ambiguity_type="adaptive_family_margin_low",
                    message=base_message,
                    candidate_ids=candidate_ids,
                    severity="requires_rule" if requires_rule else "review",
                    metadata={
                        **base_metadata,
                        "is_explicit_adaptive_ambiguity": False,
                    },
                )
            )
            ambiguities.append(
                ModalCompilationAmbiguity(
                    ambiguity_type=explicit_type,
                    message=explicit_message,
                    candidate_ids=candidate_ids,
                    severity="requires_rule" if requires_rule else "review",
                    metadata={
                        **base_metadata,
                        "is_explicit_adaptive_ambiguity": True,
                        "adaptive_base_ambiguity_type": "adaptive_family_margin_low",
                    },
                )
            )
        if (
            compiled_primary_family is not None
            and compiled_primary_family != predicted_family
        ):
            compiled_primary_targets: List[str] = [predicted_family]
            compiled_primary_signal_targets = self._adaptive_target_signal_by_family(
                compiled_primary_family,
                signals=signals,
                has_frame_scope=has_frame_scope,
            )
            for target_family in compiled_primary_signal_targets:
                if (
                    target_family != compiled_primary_family
                    and target_family not in compiled_primary_targets
                ):
                    compiled_primary_targets.append(target_family)
            # Preserve all declared directional policy pairs for the compiled
            # primary family, not just a hard-coded subset.
            for target_family in self._ordered_policy_target_families(
                compiled_primary_family
            ):
                if (
                    target_family != compiled_primary_family
                    and target_family not in compiled_primary_targets
                ):
                    compiled_primary_targets.append(target_family)
            seen_competing_families: set[str] = set()
            for competing_family in compiled_primary_targets:
                if competing_family in seen_competing_families:
                    continue
                seen_competing_families.add(competing_family)
                ambiguities.extend(
                    self._compiled_primary_family_adaptive_pair_ambiguities(
                        compiled_primary_family=compiled_primary_family,
                        competing_family=competing_family,
                        ranking=ranking,
                        family_shares=family_shares,
                        threshold=threshold,
                        signals=signals,
                        has_frame_scope=has_frame_scope,
                        has_frame_bm25_support=has_frame_bm25_support,
                        compiled_modal_families=compiled_modal_families,
                    )
                )
            ambiguities.extend(
                self._compiled_primary_family_self_adaptive_pair_ambiguities(
                    compiled_primary_family=compiled_primary_family,
                    ranking=ranking,
                    family_shares=family_shares,
                    threshold=threshold,
                    signals=signals,
                    has_frame_bm25_support=has_frame_bm25_support,
                    compiled_modal_families=compiled_modal_families,
                )
            )
        return self._ensure_explicit_adaptive_ambiguities(ambiguities)

    def _canonicalized_family_shares(
        self,
        *,
        ranking: Sequence[Dict[str, Any]],
        family_shares: Mapping[str, float],
    ) -> Dict[str, float]:
        """Normalize family-share keys so policy matching is resilient to token forms."""
        canonical_shares: Dict[str, float] = {}
        for family, share in family_shares.items():
            canonical_family = self._canonical_modal_family_name(family)
            if not canonical_family:
                continue
            try:
                resolved_share = float(share)
            except (TypeError, ValueError):
                continue
            if canonical_family in canonical_shares:
                canonical_shares[canonical_family] = max(
                    canonical_shares[canonical_family],
                    resolved_share,
                )
            else:
                canonical_shares[canonical_family] = resolved_share
        for candidate in ranking:
            canonical_family = self._canonical_modal_family_name(
                candidate.get("family")
            )
            if not canonical_family:
                continue
            candidate_share = self._ranking_share(candidate)
            if canonical_family in canonical_shares:
                canonical_shares[canonical_family] = max(
                    canonical_shares[canonical_family],
                    candidate_share,
                )
            else:
                canonical_shares[canonical_family] = candidate_share
        return canonical_shares

    def _family_shares_in_ranking(
        self,
        *,
        ranking: Sequence[Dict[str, Any]],
        family: str,
    ) -> List[float]:
        """Return ordered shares for one family as they appear in ranking."""
        canonical_family = self._canonical_modal_family_name(family) or str(family)
        shares: List[float] = []
        for candidate in ranking:
            candidate_family = (
                self._canonical_modal_family_name(candidate.get("family"))
                or str(candidate.get("family", ""))
            )
            if candidate_family != canonical_family:
                continue
            shares.append(self._ranking_share(candidate))
        return shares

    @staticmethod
    def _ordered_adaptive_target_families(
        *,
        predicted_family: str,
        target_signal_by_family: Mapping[str, bool],
    ) -> List[str]:
        canonical_predicted_family = (
            DeterministicModalCompiler._canonical_modal_family_name(predicted_family)
            or str(predicted_family)
        )
        ordered_targets: List[str] = []
        seen_targets: set[str] = set()
        for target_family in DeterministicModalCompiler._ordered_policy_target_families(
            canonical_predicted_family
        ):
            if target_family not in seen_targets:
                ordered_targets.append(target_family)
                seen_targets.add(target_family)
        for target_family in target_signal_by_family:
            canonical_target_family = (
                DeterministicModalCompiler._canonical_modal_family_name(target_family)
                or str(target_family)
            )
            if canonical_target_family not in seen_targets:
                ordered_targets.append(canonical_target_family)
                seen_targets.add(canonical_target_family)
        return ordered_targets

    @staticmethod
    def _ordered_policy_target_families(
        predicted_family: str,
    ) -> List[str]:
        canonical_predicted_family = (
            DeterministicModalCompiler._canonical_modal_family_name(predicted_family)
            or str(predicted_family)
        )
        ordered_targets: List[str] = []
        seen_targets: set[str] = set()
        for raw_target_family in _priority_signal_free_adaptive_ambiguity_targets(
            canonical_predicted_family
        ):
            target_family = (
                DeterministicModalCompiler._canonical_modal_family_name(
                    raw_target_family,
                    prefer_target_side=True,
                )
                or str(raw_target_family)
            )
            if target_family not in seen_targets:
                ordered_targets.append(target_family)
                seen_targets.add(target_family)
        for raw_target_family in _compiler_required_adaptive_ambiguity_targets(
            canonical_predicted_family
        ):
            target_family = (
                DeterministicModalCompiler._canonical_modal_family_name(
                    raw_target_family,
                    prefer_target_side=True,
                )
                or str(raw_target_family)
            )
            if target_family not in seen_targets:
                ordered_targets.append(target_family)
                seen_targets.add(target_family)
        for raw_target_family in _compiler_ambiguity_policy_targets(
            canonical_predicted_family
        ):
            target_family = (
                DeterministicModalCompiler._canonical_modal_family_name(
                    raw_target_family,
                    prefer_target_side=True,
                )
                or str(raw_target_family)
            )
            if target_family not in seen_targets:
                ordered_targets.append(target_family)
                seen_targets.add(target_family)
        for raw_target_family in _signal_free_adaptive_ambiguity_targets(
            canonical_predicted_family
        ):
            target_family = (
                DeterministicModalCompiler._canonical_modal_family_name(
                    raw_target_family,
                    prefer_target_side=True,
                )
                or str(raw_target_family)
            )
            if target_family not in seen_targets:
                ordered_targets.append(target_family)
                seen_targets.add(target_family)
        return ordered_targets

    def _adaptive_target_signal_by_family(
        self,
        predicted_family: str,
        *,
        signals: Mapping[str, bool],
        has_frame_scope: bool,
    ) -> Dict[str, bool]:
        predicted_family = (
            self._canonical_modal_family_name(predicted_family) or str(predicted_family)
        )
        target_signal_by_family: Dict[str, bool]
        if predicted_family == ModalLogicFamily.DEONTIC.value:
            target_signal_by_family = {
                ModalLogicFamily.FRAME.value: has_frame_scope,
                ModalLogicFamily.CONDITIONAL_NORMATIVE.value: bool(
                    signals.get("has_condition_or_exception_scope")
                ),
                ModalLogicFamily.TEMPORAL.value: bool(
                    signals.get("has_temporal_scope")
                ),
                ModalLogicFamily.EPISTEMIC.value: bool(
                    signals.get("has_epistemic_scope")
                    or signals.get("has_epistemic_cue")
                ),
                ModalLogicFamily.ALETHIC.value: bool(
                    signals.get("has_alethic_scope")
                    or signals.get("has_alethic_cue")
                ),
                ModalLogicFamily.DYNAMIC.value: bool(
                    signals.get("has_dynamic_scope")
                    or signals.get("has_dynamic_cue")
                ),
            }
        elif predicted_family == ModalLogicFamily.TEMPORAL.value:
            target_signal_by_family = {
                ModalLogicFamily.FRAME.value: has_frame_scope,
                ModalLogicFamily.CONDITIONAL_NORMATIVE.value: bool(
                    signals.get("has_condition_or_exception_scope")
                ),
                ModalLogicFamily.DEONTIC.value: bool(
                    signals.get("has_deontic_scope")
                    or signals.get("has_deontic_cue")
                ),
                ModalLogicFamily.ALETHIC.value: bool(
                    signals.get("has_alethic_scope")
                    or signals.get("has_alethic_cue")
                ),
                ModalLogicFamily.EPISTEMIC.value: bool(
                    signals.get("has_epistemic_scope")
                    or signals.get("has_epistemic_cue")
                ),
                ModalLogicFamily.DYNAMIC.value: bool(
                    signals.get("has_dynamic_scope")
                    or signals.get("has_dynamic_cue")
                ),
                ModalLogicFamily.DOXASTIC.value: bool(
                    signals.get("has_doxastic_scope")
                    or signals.get("has_doxastic_cue")
                ),
                ModalLogicFamily.DYNAMIC.value: bool(
                    signals.get("has_dynamic_scope")
                    or signals.get("has_dynamic_cue")
                ),
            }
        elif predicted_family == ModalLogicFamily.HYBRID.value:
            target_signal_by_family = {
                ModalLogicFamily.FRAME.value: has_frame_scope,
            }
        elif predicted_family == ModalLogicFamily.EPISTEMIC.value:
            target_signal_by_family = {
                ModalLogicFamily.CONDITIONAL_NORMATIVE.value: bool(
                    signals.get("has_condition_or_exception_scope")
                ),
                ModalLogicFamily.DEONTIC.value: bool(
                    signals.get("has_deontic_scope")
                    or signals.get("has_deontic_cue")
                ),
                ModalLogicFamily.TEMPORAL.value: bool(
                    signals.get("has_temporal_scope")
                ),
            }
        elif predicted_family == ModalLogicFamily.DOXASTIC.value:
            target_signal_by_family = {
                ModalLogicFamily.EPISTEMIC.value: bool(
                    signals.get("has_epistemic_scope")
                    or signals.get("has_epistemic_cue")
                    or signals.get("has_epistemic_scope_phrase")
                ),
            }
        elif predicted_family == ModalLogicFamily.FRAME.value:
            target_signal_by_family = {
                ModalLogicFamily.CONDITIONAL_NORMATIVE.value: bool(
                    signals.get("has_condition_or_exception_scope")
                ),
                ModalLogicFamily.DEONTIC.value: bool(
                    signals.get("has_deontic_scope")
                    or signals.get("has_deontic_cue")
                ),
                ModalLogicFamily.ALETHIC.value: bool(
                    signals.get("has_alethic_scope")
                    or signals.get("has_alethic_cue")
                ),
                ModalLogicFamily.EPISTEMIC.value: bool(
                    signals.get("has_epistemic_scope")
                    or signals.get("has_epistemic_cue")
                ),
                ModalLogicFamily.DOXASTIC.value: bool(
                    signals.get("has_doxastic_scope")
                    or signals.get("has_doxastic_cue")
                ),
                ModalLogicFamily.TEMPORAL.value: bool(
                    signals.get("has_temporal_scope")
                ),
                ModalLogicFamily.DYNAMIC.value: bool(
                    signals.get("has_dynamic_scope")
                    or signals.get("has_dynamic_cue")
                ),
            }
        elif predicted_family == ModalLogicFamily.CONDITIONAL_NORMATIVE.value:
            target_signal_by_family = {
                ModalLogicFamily.DEONTIC.value: bool(
                    signals.get("has_deontic_scope")
                    or signals.get("has_deontic_cue")
                ),
                ModalLogicFamily.ALETHIC.value: bool(
                    signals.get("has_alethic_scope")
                    or signals.get("has_alethic_cue")
                ),
                ModalLogicFamily.EPISTEMIC.value: bool(
                    signals.get("has_epistemic_scope")
                    or signals.get("has_epistemic_cue")
                ),
                ModalLogicFamily.TEMPORAL.value: bool(
                    signals.get("has_temporal_scope")
                ),
                ModalLogicFamily.FRAME.value: has_frame_scope,
                ModalLogicFamily.DYNAMIC.value: bool(
                    signals.get("has_dynamic_scope")
                    or signals.get("has_dynamic_cue")
                ),
            }
        elif predicted_family == ModalLogicFamily.DYNAMIC.value:
            target_signal_by_family = {
                ModalLogicFamily.TEMPORAL.value: bool(
                    signals.get("has_temporal_scope")
                ),
                ModalLogicFamily.DEONTIC.value: bool(
                    signals.get("has_deontic_scope")
                    or signals.get("has_deontic_cue")
                ),
                ModalLogicFamily.CONDITIONAL_NORMATIVE.value: bool(
                    signals.get("has_condition_or_exception_scope")
                ),
                ModalLogicFamily.FRAME.value: has_frame_scope,
            }
        elif predicted_family == ModalLogicFamily.ALETHIC.value:
            target_signal_by_family = {
                ModalLogicFamily.FRAME.value: has_frame_scope,
                ModalLogicFamily.CONDITIONAL_NORMATIVE.value: bool(
                    signals.get("has_condition_or_exception_scope")
                ),
                ModalLogicFamily.DEONTIC.value: bool(
                    signals.get("has_deontic_scope")
                    or signals.get("has_deontic_cue")
                ),
                ModalLogicFamily.EPISTEMIC.value: bool(
                    signals.get("has_epistemic_scope")
                    or signals.get("has_epistemic_cue")
                ),
                ModalLogicFamily.TEMPORAL.value: bool(
                    signals.get("has_temporal_scope")
                ),
                ModalLogicFamily.DYNAMIC.value: bool(
                    signals.get("has_dynamic_scope")
                    or signals.get("has_dynamic_cue")
                ),
            }
        else:
            target_signal_by_family = {}
        return target_signal_by_family

    def _compiled_primary_family_adaptive_pair_ambiguities(
        self,
        *,
        compiled_primary_family: str,
        competing_family: str,
        ranking: Sequence[Dict[str, Any]],
        family_shares: Dict[str, float],
        threshold: float,
        signals: Mapping[str, bool],
        has_frame_scope: bool,
        has_frame_bm25_support: bool,
        compiled_modal_families: Sequence[str],
        predicted_family_source: str = "compiled_primary_family",
    ) -> List[ModalCompilationAmbiguity]:
        resolved_compiled_primary_family = (
            self._canonical_modal_family_name(compiled_primary_family)
            or str(compiled_primary_family)
        )
        resolved_competing_family = (
            self._canonical_modal_family_name(competing_family)
            or str(competing_family)
        )
        canonical_family_shares = self._canonicalized_family_shares(
            ranking=ranking,
            family_shares=family_shares,
        )
        canonical_compiled_modal_families = {
            self._canonical_modal_family_name(family) or str(family)
            for family in compiled_modal_families
        }
        supports_signal_free_pair_policy = self._supports_signal_free_adaptive_pair(
            resolved_compiled_primary_family,
            resolved_competing_family,
        )
        is_self_pair = resolved_compiled_primary_family == resolved_competing_family
        primary_share = float(
            canonical_family_shares.get(resolved_compiled_primary_family, 0.0)
        )
        competing_share = float(
            canonical_family_shares.get(resolved_competing_family, 0.0)
        )
        runner_up_family: Optional[str] = resolved_competing_family
        runner_up_share: Optional[float] = competing_share
        if is_self_pair:
            runner_up_family = None
            runner_up_share = None
            for candidate in ranking:
                candidate_family = (
                    self._canonical_modal_family_name(candidate.get("family"))
                    or str(candidate.get("family", ""))
                )
                if candidate_family == resolved_compiled_primary_family:
                    continue
                runner_up_family = candidate_family
                runner_up_share = float(
                    canonical_family_shares.get(
                        candidate_family,
                        self._ranking_share(candidate),
                    )
                )
                break
        family_margin = (
            primary_share - runner_up_share
            if is_self_pair and runner_up_share is not None
            else primary_share - competing_share
        )
        pair_threshold = self._adaptive_pair_margin_threshold(
            predicted_family=resolved_compiled_primary_family,
            target_family=resolved_competing_family,
            base_threshold=threshold,
        )
        pair_margin_buffer = max(0.0, pair_threshold - threshold)
        if not self._adaptive_margin_within_threshold(
            family_margin=family_margin,
            threshold=pair_threshold,
        ):
            return []
        target_signal_by_family = self._adaptive_target_signal_by_family(
            resolved_compiled_primary_family,
            signals=signals,
            has_frame_scope=has_frame_scope,
        )
        has_signal = bool(target_signal_by_family.get(resolved_competing_family, False))
        has_compiled_target_family_formula = (
            resolved_competing_family in canonical_compiled_modal_families
        )
        has_target_signal_evidence = bool(
            has_signal
            or competing_share > 0.0
            or has_compiled_target_family_formula
        )
        if not has_target_signal_evidence and not supports_signal_free_pair_policy:
            return []
        runner_up_is_priority_policy_pair = bool(
            is_self_pair
            and runner_up_family is not None
            and _is_priority_signal_free_adaptive_ambiguity_pair(
                resolved_compiled_primary_family,
                runner_up_family,
            )
        )
        runner_up_is_compiler_required_policy_pair = bool(
            is_self_pair
            and runner_up_family is not None
            and _is_compiler_required_adaptive_ambiguity_pair(
                resolved_compiled_primary_family,
                runner_up_family,
            )
        )
        direct_is_priority_policy_pair = _is_priority_signal_free_adaptive_ambiguity_pair(
            resolved_compiled_primary_family,
            resolved_competing_family,
        )
        is_priority_policy_pair = (
            direct_is_priority_policy_pair
            or runner_up_is_priority_policy_pair
        )
        is_compiler_required_policy_pair = (
            _is_compiler_required_adaptive_ambiguity_pair(
                resolved_compiled_primary_family,
                resolved_competing_family,
            )
            or runner_up_is_compiler_required_policy_pair
        )
        margin_direction = self._adaptive_margin_direction(
            family_margin=family_margin,
            predicted_family=resolved_compiled_primary_family,
            target_family=resolved_competing_family,
            is_priority_policy_pair=is_priority_policy_pair,
            is_compiler_required_policy_pair=is_compiler_required_policy_pair,
            direct_is_priority_policy_pair=direct_is_priority_policy_pair,
            runner_up_is_priority_policy_pair=runner_up_is_priority_policy_pair,
            prefer_runner_up_priority_over_contested=True,
        )
        requires_rule = margin_direction == "outvoted"
        explicit_type = self._adaptive_margin_explicit_type(
            resolved_compiled_primary_family,
            resolved_competing_family,
            margin_direction,
        )
        primary_share_display = round(primary_share, 6)
        competing_share_display = round(competing_share, 6)
        runner_up_share_display = (
            round(runner_up_share, 6)
            if runner_up_share is not None
            else None
        )
        # Round the raw margin directly so metadata preserves tiny negative/positive
        # outvote deltas that can disappear when subtracting rounded shares.
        family_margin_display = round(family_margin, 6)
        candidate_ids = (
            [resolved_compiled_primary_family]
            if is_self_pair
            else [resolved_compiled_primary_family, resolved_competing_family]
        )
        is_compiler_ambiguity_bundle_pair = _is_compiler_ambiguity_policy_pair(
            resolved_compiled_primary_family,
            resolved_competing_family,
        )
        runner_up_is_compiler_ambiguity_bundle_pair = bool(
            is_self_pair
            and runner_up_family is not None
            and _is_compiler_ambiguity_policy_pair(
                resolved_compiled_primary_family,
                runner_up_family,
            )
        )
        effective_is_compiler_ambiguity_bundle_pair = (
            is_compiler_ambiguity_bundle_pair
            or runner_up_is_compiler_ambiguity_bundle_pair
        )
        effective_compiler_ambiguity_policy_pair = (
            f"{resolved_compiled_primary_family}->{runner_up_family}"
            if runner_up_is_compiler_ambiguity_bundle_pair
            and runner_up_family is not None
            else f"{resolved_compiled_primary_family}->{resolved_competing_family}"
        )
        adaptive_priority = self._adaptive_margin_priority(
            family_margin=family_margin,
            threshold=threshold,
        )
        base_metadata = {
            "adaptive_family_margin_threshold": threshold,
            "adaptive_effective_family_margin_threshold": pair_threshold,
            "adaptive_pair_margin_buffer": pair_margin_buffer,
            "adaptive_margin_direction": margin_direction,
            "adaptive_margin_abs": abs(family_margin),
            "adaptive_priority": adaptive_priority,
            "priority": adaptive_priority,
            "adaptive_predicted_family_source": predicted_family_source,
            "adaptive_policy_pair": (
                f"{resolved_compiled_primary_family}->{resolved_competing_family}"
            ),
            "adaptive_runner_up_policy_pair": (
                f"{resolved_compiled_primary_family}->{runner_up_family}"
                if runner_up_family is not None
                else None
            ),
            "explicit_ambiguity_type": explicit_type,
            "family_margin_raw": family_margin,
            "family_margin": family_margin_display,
            "family_ranking": list(ranking),
            "compiled_modal_families": sorted(canonical_compiled_modal_families),
            "has_target_signal_evidence": has_target_signal_evidence,
            "signal_free_pair_policy_applied": (
                not has_target_signal_evidence
                and supports_signal_free_pair_policy
            ),
            "has_compiled_target_family_formula": has_compiled_target_family_formula,
            "has_frame_bm25_support": has_frame_bm25_support,
            "lexical_signals": dict(sorted(signals.items())),
            "is_compiler_required_policy_pair": is_compiler_required_policy_pair,
            "runner_up_is_compiler_required_policy_pair": (
                runner_up_is_compiler_required_policy_pair
            ),
            "is_priority_policy_pair": is_priority_policy_pair,
            "runner_up_is_priority_policy_pair": runner_up_is_priority_policy_pair,
            "is_compiler_ambiguity_bundle_pair": is_compiler_ambiguity_bundle_pair,
            "ambiguity_policy_bundle": (
                "compiler_ambiguity"
                if is_compiler_ambiguity_bundle_pair
                else None
            ),
            "runner_up_is_compiler_ambiguity_bundle_pair": (
                runner_up_is_compiler_ambiguity_bundle_pair
            ),
            "effective_is_compiler_ambiguity_bundle_pair": (
                effective_is_compiler_ambiguity_bundle_pair
            ),
            "effective_compiler_ambiguity_policy_pair": (
                effective_compiler_ambiguity_policy_pair
            ),
            "effective_ambiguity_policy_bundle": (
                "compiler_ambiguity"
                if effective_is_compiler_ambiguity_bundle_pair
                else None
            ),
            "predicted_family": resolved_compiled_primary_family,
            "predicted_margin_to_runner_up_raw": family_margin,
            "predicted_margin_to_runner_up": round(family_margin, 6),
            "runner_up_family": runner_up_family,
            "runner_up_share_raw": runner_up_share,
            "runner_up_share": runner_up_share_display,
            "predicted_share_raw": primary_share,
            "predicted_share": primary_share_display,
            "target_family": resolved_competing_family,
            "target_share_raw": competing_share,
            "target_share": competing_share_display,
            "is_self_pair": is_self_pair,
        }
        base_message = (
            "The compiled primary modal family has a low lead over competing "
            "cue evidence; family selection is ambiguous."
            if is_self_pair
            else (
                "The compiled primary modal family is outvoted by competing "
                "cue evidence; family selection is ambiguous."
            )
        )
        explicit_message = (
            "Explicit adaptive low-margin ambiguity for the compiled primary "
            "modal family against close competing families."
            if is_self_pair
            else (
                "Explicit adaptive modal-family conflict between the "
                "compiled primary family and a competing cue-dominant "
                "family."
            )
        )
        return [
            ModalCompilationAmbiguity(
                ambiguity_type="adaptive_family_margin_low",
                message=base_message,
                candidate_ids=candidate_ids,
                severity="requires_rule" if requires_rule else "review",
                metadata={
                    **base_metadata,
                    "is_explicit_adaptive_ambiguity": False,
                },
            ),
            ModalCompilationAmbiguity(
                ambiguity_type=explicit_type,
                message=explicit_message,
                candidate_ids=candidate_ids,
                severity="requires_rule" if requires_rule else "review",
                metadata={
                    **base_metadata,
                    "is_explicit_adaptive_ambiguity": True,
                    "adaptive_base_ambiguity_type": "adaptive_family_margin_low",
                },
            ),
        ]

    def _compiled_primary_family_self_adaptive_pair_ambiguities(
        self,
        *,
        compiled_primary_family: str,
        ranking: Sequence[Dict[str, Any]],
        family_shares: Dict[str, float],
        threshold: float,
        signals: Mapping[str, bool],
        has_frame_bm25_support: bool,
        compiled_modal_families: Sequence[str],
    ) -> List[ModalCompilationAmbiguity]:
        resolved_compiled_primary_family = (
            self._canonical_modal_family_name(compiled_primary_family)
            or str(compiled_primary_family)
        )
        canonical_family_shares = self._canonicalized_family_shares(
            ranking=ranking,
            family_shares=family_shares,
        )
        canonical_compiled_modal_families = {
            self._canonical_modal_family_name(family) or str(family)
            for family in compiled_modal_families
        }
        if not self._supports_signal_free_adaptive_pair(
            resolved_compiled_primary_family,
            resolved_compiled_primary_family,
        ):
            return []
        compiled_primary_family_shares_in_ranking = self._family_shares_in_ranking(
            ranking=ranking,
            family=resolved_compiled_primary_family,
        )
        duplicate_compiled_primary_family_share = (
            compiled_primary_family_shares_in_ranking[1]
            if len(compiled_primary_family_shares_in_ranking) > 1
            else None
        )
        runner_up = max(
            (
                candidate
                for candidate in ranking
                if (
                    self._canonical_modal_family_name(candidate.get("family"))
                    or str(candidate.get("family"))
                )
                != resolved_compiled_primary_family
            ),
            key=lambda candidate: (
                self._ranking_share(candidate),
                str(candidate["family"]),
            ),
            default=None,
        )
        if runner_up is None and duplicate_compiled_primary_family_share is None:
            return []
        primary_share = (
            compiled_primary_family_shares_in_ranking[0]
            if compiled_primary_family_shares_in_ranking
            else float(canonical_family_shares.get(resolved_compiled_primary_family, 0.0))
        )
        runner_up_family = (
            self._canonical_modal_family_name(runner_up.get("family"))
            or str(runner_up["family"])
        ) if runner_up is not None else None
        runner_up_share = (
            float(
                canonical_family_shares.get(
                    runner_up_family,
                    self._ranking_share(runner_up),
                )
            )
            if runner_up is not None and runner_up_family is not None
            else 0.0
        )
        family_margin = (
            duplicate_compiled_primary_family_share - primary_share
            if duplicate_compiled_primary_family_share is not None
            else primary_share - runner_up_share
        )
        runner_up_family_value = (
            resolved_compiled_primary_family
            if duplicate_compiled_primary_family_share is not None
            else runner_up_family
        )
        runner_up_share_value = (
            duplicate_compiled_primary_family_share
            if duplicate_compiled_primary_family_share is not None
            else (runner_up_share if runner_up_family is not None else None)
        )
        pair_threshold = self._adaptive_pair_margin_threshold(
            predicted_family=resolved_compiled_primary_family,
            target_family=resolved_compiled_primary_family,
            base_threshold=threshold,
        )
        pair_margin_buffer = max(0.0, pair_threshold - threshold)
        if not self._adaptive_margin_within_threshold(
            family_margin=family_margin,
            threshold=pair_threshold,
        ):
            return []
        runner_up_is_priority_policy_pair = _is_priority_signal_free_adaptive_ambiguity_pair(
            resolved_compiled_primary_family,
            runner_up_family_value or "",
        )
        runner_up_is_compiler_required_policy_pair = (
            _is_compiler_required_adaptive_ambiguity_pair(
                resolved_compiled_primary_family,
                runner_up_family_value or "",
            )
        )
        direct_is_priority_policy_pair = _is_priority_signal_free_adaptive_ambiguity_pair(
            resolved_compiled_primary_family,
            resolved_compiled_primary_family,
        )
        is_priority_policy_pair = (
            direct_is_priority_policy_pair
            or runner_up_is_priority_policy_pair
        )
        is_compiler_required_policy_pair = (
            _is_compiler_required_adaptive_ambiguity_pair(
                resolved_compiled_primary_family,
                resolved_compiled_primary_family,
            )
            or runner_up_is_compiler_required_policy_pair
        )
        margin_direction = self._adaptive_margin_direction(
            family_margin=family_margin,
            predicted_family=resolved_compiled_primary_family,
            target_family=resolved_compiled_primary_family,
            is_priority_policy_pair=is_priority_policy_pair,
            is_compiler_required_policy_pair=is_compiler_required_policy_pair,
            direct_is_priority_policy_pair=direct_is_priority_policy_pair,
            runner_up_is_priority_policy_pair=runner_up_is_priority_policy_pair,
            prefer_runner_up_priority_over_contested=True,
        )
        requires_rule = margin_direction == "outvoted"
        explicit_type = self._adaptive_margin_explicit_type(
            resolved_compiled_primary_family,
            resolved_compiled_primary_family,
            margin_direction,
        )
        primary_share_display = round(primary_share, 6)
        family_margin_display = round(family_margin, 6)
        has_compiled_target_family_formula = resolved_compiled_primary_family in (
            canonical_compiled_modal_families
        )
        has_target_signal_evidence = bool(
            primary_share > 0.0
            or has_compiled_target_family_formula
        )
        adaptive_priority = self._adaptive_margin_priority(
            family_margin=family_margin,
            threshold=threshold,
        )
        is_compiler_ambiguity_bundle_pair = _is_compiler_ambiguity_policy_pair(
            resolved_compiled_primary_family,
            resolved_compiled_primary_family,
        )
        runner_up_is_compiler_ambiguity_bundle_pair = _is_compiler_ambiguity_policy_pair(
            resolved_compiled_primary_family,
            runner_up_family_value or "",
        )
        effective_is_compiler_ambiguity_bundle_pair = (
            is_compiler_ambiguity_bundle_pair
            or runner_up_is_compiler_ambiguity_bundle_pair
        )
        effective_compiler_ambiguity_policy_pair = (
            f"{resolved_compiled_primary_family}->{runner_up_family_value}"
            if runner_up_is_compiler_ambiguity_bundle_pair
            else f"{resolved_compiled_primary_family}->{resolved_compiled_primary_family}"
        )
        base_metadata = {
            "adaptive_family_margin_threshold": threshold,
            "adaptive_effective_family_margin_threshold": pair_threshold,
            "adaptive_pair_margin_buffer": pair_margin_buffer,
            "adaptive_margin_direction": margin_direction,
            "adaptive_margin_abs": abs(family_margin),
            "adaptive_priority": adaptive_priority,
            "priority": adaptive_priority,
            "adaptive_predicted_family_source": "compiled_primary_family",
            "adaptive_policy_pair": (
                f"{resolved_compiled_primary_family}->{resolved_compiled_primary_family}"
            ),
            "adaptive_runner_up_policy_pair": (
                f"{resolved_compiled_primary_family}->{runner_up_family_value}"
            ),
            "explicit_ambiguity_type": explicit_type,
            "family_margin_raw": family_margin,
            "family_margin": family_margin_display,
            "family_ranking": list(ranking),
            "compiled_modal_families": sorted(canonical_compiled_modal_families),
            "has_target_signal_evidence": has_target_signal_evidence,
            "signal_free_pair_policy_applied": (
                not has_target_signal_evidence
            ),
            "has_compiled_target_family_formula": has_compiled_target_family_formula,
            "has_frame_bm25_support": has_frame_bm25_support,
            "lexical_signals": dict(sorted(signals.items())),
            "is_compiler_required_policy_pair": is_compiler_required_policy_pair,
            "runner_up_is_compiler_required_policy_pair": (
                runner_up_is_compiler_required_policy_pair
            ),
            "is_priority_policy_pair": is_priority_policy_pair,
            "runner_up_is_priority_policy_pair": runner_up_is_priority_policy_pair,
            "is_compiler_ambiguity_bundle_pair": is_compiler_ambiguity_bundle_pair,
            "ambiguity_policy_bundle": (
                "compiler_ambiguity"
                if is_compiler_ambiguity_bundle_pair
                else None
            ),
            "runner_up_is_compiler_ambiguity_bundle_pair": (
                runner_up_is_compiler_ambiguity_bundle_pair
            ),
            "effective_is_compiler_ambiguity_bundle_pair": (
                effective_is_compiler_ambiguity_bundle_pair
            ),
            "effective_compiler_ambiguity_policy_pair": (
                effective_compiler_ambiguity_policy_pair
            ),
            "effective_ambiguity_policy_bundle": (
                "compiler_ambiguity"
                if effective_is_compiler_ambiguity_bundle_pair
                else None
            ),
            "predicted_family": resolved_compiled_primary_family,
            "predicted_margin_to_runner_up_raw": family_margin,
            "predicted_margin_to_runner_up": family_margin_display,
            "runner_up_family": runner_up_family_value,
            "runner_up_share_raw": runner_up_share_value,
            "runner_up_share": (
                round(runner_up_share_value, 6)
                if runner_up_share_value is not None
                else None
            ),
            "predicted_share_raw": primary_share,
            "predicted_share": primary_share_display,
            "target_family": resolved_compiled_primary_family,
            "target_share_raw": (
                duplicate_compiled_primary_family_share
                if duplicate_compiled_primary_family_share is not None
                else primary_share
            ),
            "target_share": (
                round(duplicate_compiled_primary_family_share, 6)
                if duplicate_compiled_primary_family_share is not None
                else primary_share_display
            ),
            "is_self_pair": True,
        }
        return [
            ModalCompilationAmbiguity(
                ambiguity_type="adaptive_family_margin_low",
                message=(
                    "A predicted modal family has a low lead over competing legal "
                    "families; family selection is ambiguous."
                ),
                candidate_ids=[resolved_compiled_primary_family],
                severity="requires_rule" if requires_rule else "review",
                metadata={
                    **base_metadata,
                    "is_explicit_adaptive_ambiguity": False,
                },
            ),
            ModalCompilationAmbiguity(
                ambiguity_type=explicit_type,
                message=(
                    "Explicit adaptive low-margin ambiguity for the predicted modal "
                    "family against close competing families."
                ),
                candidate_ids=[resolved_compiled_primary_family],
                severity="requires_rule" if requires_rule else "review",
                metadata={
                    **base_metadata,
                    "is_explicit_adaptive_ambiguity": True,
                    "adaptive_base_ambiguity_type": "adaptive_family_margin_low",
                },
            ),
        ]

    def _has_frame_bm25_support(
        self,
        frame_selections: Sequence[FrameSelection],
    ) -> bool:
        if not frame_selections:
            return False
        return any(
            bool(selection.matched_terms) and float(selection.score) > 0.0
            for selection in frame_selections
        )

    def _adaptive_margin_explicit_type(
        self,
        predicted_family: str,
        target_family: str,
        margin_direction: str,
    ) -> str:
        return "_".join(
            (
                "adaptive",
                predicted_family,
                target_family,
                margin_direction,
                "margin_low",
            )
        )

    def _adaptive_margin_direction(
        self,
        *,
        family_margin: float,
        predicted_family: str,
        target_family: str,
        is_priority_policy_pair: bool,
        is_compiler_required_policy_pair: bool,
        direct_is_priority_policy_pair: Optional[bool] = None,
        runner_up_is_priority_policy_pair: bool = False,
        prefer_runner_up_priority_over_contested: bool = False,
        epsilon: float = 1e-12,
    ) -> str:
        """Classify adaptive low-margin conflicts as contested vs. outvoted."""
        resolved_margin = float(family_margin)
        resolved_epsilon = max(0.0, float(epsilon))
        direct_priority = (
            bool(direct_is_priority_policy_pair)
            if direct_is_priority_policy_pair is not None
            else bool(is_priority_policy_pair)
        )
        runner_up_priority = bool(runner_up_is_priority_policy_pair)
        if resolved_margin < -resolved_epsilon:
            return "outvoted"
        if (
            abs(resolved_margin) <= resolved_epsilon
            and _prefers_contested_zero_margin_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )
        ):
            return "contested"
        if resolved_margin <= resolved_epsilon and direct_priority:
            return "outvoted"
        if (
            resolved_margin <= resolved_epsilon
            and runner_up_priority
            and prefer_runner_up_priority_over_contested
        ):
            return "outvoted"
        if resolved_margin <= resolved_epsilon and runner_up_priority:
            return "outvoted"
        if resolved_margin <= resolved_epsilon and is_compiler_required_policy_pair:
            return "outvoted"
        return "contested"

    @staticmethod
    def _adaptive_margin_priority(*, family_margin: float, threshold: float) -> float:
        """Return deterministic ambiguity priority from policy margin settings.

        For contested low-margin cases (positive margin below threshold), a
        smaller gap to the threshold carries higher urgency. For outvoted
        cases (zero/negative margin), severity increases with outvote depth.
        """
        resolved_margin = float(family_margin)
        resolved_threshold = max(0.0, float(threshold))
        if resolved_margin > 0.0:
            return max(0.0, resolved_threshold - resolved_margin)
        return abs(resolved_margin) + resolved_threshold

    @staticmethod
    def _adaptive_margin_within_threshold(
        *,
        family_margin: float,
        threshold: float,
        epsilon: float = 1e-12,
    ) -> bool:
        """Return whether the margin is at or below threshold with float tolerance."""
        resolved_margin = float(family_margin)
        resolved_threshold = float(threshold)
        resolved_epsilon = max(0.0, float(epsilon))
        return resolved_margin <= (resolved_threshold + resolved_epsilon)

    def _adaptive_pair_margin_threshold(
        self,
        *,
        predicted_family: str,
        target_family: str,
        base_threshold: float,
    ) -> float:
        """Return per-pair adaptive threshold with refined cue-policy buffer."""
        resolved_threshold = float(base_threshold)
        margin_buffer = _compiler_refined_modal_family_cue_margin_buffer(
            predicted_family,
            target_family,
        )
        return resolved_threshold + margin_buffer

    @staticmethod
    def _weak_typed_self_family_margin_buffer(
        *,
        predicted_family: str,
        target_family: str,
        predicted_share: float,
        compiled_primary_family: Optional[str],
    ) -> float:
        """Return extra self-pair threshold for weak but typed modal evidence."""
        if predicted_family != target_family:
            return 0.0
        if compiled_primary_family != predicted_family:
            return 0.0
        if float(predicted_share) >= 0.5:
            return 0.0
        return _compiler_weak_typed_self_family_cue_margin_buffer(
            predicted_family,
            target_family,
        )

    def _supports_signal_free_adaptive_pair(
        self,
        predicted_family: str,
        target_family: str,
    ) -> bool:
        """Return whether this pair must surface adaptive ambiguity without lexical support."""
        return _supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )

    def _temporal_target_family_ambiguities(
        self,
        encoding: SpaCyLegalEncoding,
        *,
        ranking: Sequence[Dict[str, Any]],
        family_shares: Dict[str, float],
    ) -> List[ModalCompilationAmbiguity]:
        if not ranking:
            return []
        top_family = str(ranking[0]["family"])
        if top_family != ModalLogicFamily.TEMPORAL.value:
            return []
        temporal_share = self._ranking_share(ranking[0])
        signals = _modal_ambiguity_signals(encoding)
        target_specs = (
            (
                ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
                bool(signals.get("has_condition_or_exception_scope")),
                "temporal_conditional_normative_family_outvoted",
                (
                    "Conditional or exception scope markers are present, but temporal cues "
                    "outvote conditional-normative family evidence."
                ),
            ),
            (
                ModalLogicFamily.FRAME.value,
                bool(signals.get("has_frame_context") or signals.get("has_frame_cue")),
                "temporal_frame_family_outvoted",
                (
                    "Frame-context markers are present, but temporal cues outvote frame-family "
                    "evidence."
                ),
            ),
        )
        ambiguities: List[ModalCompilationAmbiguity] = []
        for target_family, has_signal, ambiguity_type, message in target_specs:
            target_share = float(family_shares.get(target_family, 0.0))
            family_margin = target_share - temporal_share
            if not has_signal and target_share <= 0.0:
                continue
            if family_margin >= self.config.modal_temporal_target_family_outvote_margin:
                continue
            ambiguities.append(
                ModalCompilationAmbiguity(
                    ambiguity_type=ambiguity_type,
                    message=message,
                    candidate_ids=[ModalLogicFamily.TEMPORAL.value, target_family],
                    severity="requires_rule",
                    metadata={
                        "family_margin": round(family_margin, 6),
                        "family_ranking": list(ranking),
                        "lexical_signals": dict(sorted(signals.items())),
                        "outvote_margin_threshold": self.config.modal_temporal_target_family_outvote_margin,
                        "predicted_family": ModalLogicFamily.TEMPORAL.value,
                        "target_family": target_family,
                        "target_share": round(target_share, 6),
                        "temporal_share": round(temporal_share, 6),
                    },
                )
            )
        return ambiguities

    def _temporal_scope_target_family_ambiguities(
        self,
        encoding: SpaCyLegalEncoding,
        *,
        ranking: Sequence[Dict[str, Any]],
        family_shares: Dict[str, float],
    ) -> List[ModalCompilationAmbiguity]:
        if not ranking:
            return []
        predicted_family = str(ranking[0]["family"])
        if predicted_family == ModalLogicFamily.TEMPORAL.value:
            return []
        predicted_share = self._ranking_share(ranking[0])
        target_family = ModalLogicFamily.TEMPORAL.value
        target_share = float(family_shares.get(target_family, 0.0))
        signals = _modal_ambiguity_signals(encoding)
        if not bool(signals.get("has_temporal_scope")) and target_share <= 0.0:
            return []
        family_margin = target_share - predicted_share
        if family_margin >= self.config.modal_temporal_target_family_outvote_margin:
            return []
        return [
            ModalCompilationAmbiguity(
                ambiguity_type="temporal_scope_family_outvoted",
                message=(
                    "Temporal-scope markers are present, but non-temporal cue evidence "
                    "outvotes temporal family evidence."
                ),
                candidate_ids=[predicted_family, target_family],
                severity="requires_rule",
                metadata={
                    "family_margin": round(family_margin, 6),
                    "family_ranking": list(ranking),
                    "lexical_signals": dict(sorted(signals.items())),
                    "outvote_margin_threshold": self.config.modal_temporal_target_family_outvote_margin,
                    "predicted_family": predicted_family,
                    "predicted_share": round(predicted_share, 6),
                    "target_family": target_family,
                    "target_share": round(target_share, 6),
                },
            )
        ]

    def _frame_scope_target_family_ambiguities(
        self,
        encoding: SpaCyLegalEncoding,
        *,
        ranking: Sequence[Dict[str, Any]],
        family_shares: Dict[str, float],
    ) -> List[ModalCompilationAmbiguity]:
        if not ranking:
            return []
        predicted_family = str(ranking[0]["family"])
        if predicted_family in {ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.FRAME.value}:
            return []
        predicted_share = self._ranking_share(ranking[0])
        target_family = ModalLogicFamily.FRAME.value
        target_share = float(family_shares.get(target_family, 0.0))
        signals = _modal_ambiguity_signals(encoding)
        has_frame_scope = bool(
            signals.get("has_frame_context")
            or signals.get("has_frame_cue")
            or signals.get("has_statutory_scope_reference")
        )
        if not has_frame_scope and target_share <= 0.0:
            return []
        family_margin = target_share - predicted_share
        if family_margin >= self.config.modal_frame_target_family_outvote_margin:
            return []
        return [
            ModalCompilationAmbiguity(
                ambiguity_type="frame_scope_family_outvoted",
                message=(
                    "Frame-context markers are present, but non-frame cue evidence "
                    "outvotes frame family evidence."
                ),
                candidate_ids=[predicted_family, target_family],
                severity="requires_rule",
                metadata={
                    "family_margin": round(family_margin, 6),
                    "family_ranking": list(ranking),
                    "lexical_signals": dict(sorted(signals.items())),
                    "outvote_margin_threshold": self.config.modal_frame_target_family_outvote_margin,
                    "predicted_family": predicted_family,
                    "predicted_share": round(predicted_share, 6),
                    "target_family": target_family,
                    "target_share": round(target_share, 6),
                },
            )
        ]

    def _conditional_scope_target_family_ambiguities(
        self,
        encoding: SpaCyLegalEncoding,
        *,
        ranking: Sequence[Dict[str, Any]],
        family_shares: Dict[str, float],
    ) -> List[ModalCompilationAmbiguity]:
        if not ranking:
            return []
        predicted_family = str(ranking[0]["family"])
        target_family = ModalLogicFamily.CONDITIONAL_NORMATIVE.value
        if predicted_family == target_family:
            return []
        predicted_share = self._ranking_share(ranking[0])
        target_share = float(family_shares.get(target_family, 0.0))
        signals = _modal_ambiguity_signals(encoding)
        has_condition_scope = bool(signals.get("has_condition_or_exception_scope"))
        if not has_condition_scope and target_share <= 0.0:
            return []
        family_margin = target_share - predicted_share
        if family_margin >= self.config.modal_conditional_target_family_outvote_margin:
            return []
        is_compiler_ambiguity_bundle_pair = _is_compiler_ambiguity_policy_pair(
            predicted_family,
            target_family,
        )
        return [
            ModalCompilationAmbiguity(
                ambiguity_type="conditional_scope_family_outvoted",
                message=(
                    "Conditional or exception scope markers are present, but non-conditional "
                    "cue evidence outvotes conditional-normative family evidence."
                ),
                candidate_ids=[predicted_family, target_family],
                severity="requires_rule",
                metadata={
                    "family_margin": round(family_margin, 6),
                    "family_ranking": list(ranking),
                    "is_compiler_ambiguity_bundle_pair": (
                        is_compiler_ambiguity_bundle_pair
                    ),
                    "ambiguity_policy_bundle": (
                        "compiler_ambiguity"
                        if is_compiler_ambiguity_bundle_pair
                        else None
                    ),
                    "compiler_ambiguity_policy_pair": (
                        f"{predicted_family}->{target_family}"
                        if is_compiler_ambiguity_bundle_pair
                        else None
                    ),
                    "lexical_signals": dict(sorted(signals.items())),
                    "outvote_margin_threshold": self.config.modal_conditional_target_family_outvote_margin,
                    "predicted_family": predicted_family,
                    "predicted_share": round(predicted_share, 6),
                    "target_family": target_family,
                    "target_share": round(target_share, 6),
                },
            )
        ]

    def _deontic_scope_target_family_ambiguities(
        self,
        encoding: SpaCyLegalEncoding,
        *,
        ranking: Sequence[Dict[str, Any]],
        family_shares: Dict[str, float],
    ) -> List[ModalCompilationAmbiguity]:
        if not ranking:
            return []
        predicted_family = str(ranking[0]["family"])
        target_family = ModalLogicFamily.DEONTIC.value
        if predicted_family == target_family:
            return []
        predicted_share = self._ranking_share(ranking[0])
        target_share = float(family_shares.get(target_family, 0.0))
        signals = _modal_ambiguity_signals(encoding)
        has_deontic_scope = bool(
            signals.get("has_deontic_scope")
            or signals.get("has_deontic_cue")
        )
        if not has_deontic_scope and target_share <= 0.0:
            return []
        family_margin = target_share - predicted_share
        if family_margin >= self.config.modal_deontic_target_family_outvote_margin:
            return []
        return [
            ModalCompilationAmbiguity(
                ambiguity_type="deontic_scope_family_outvoted",
                message=(
                    "Deontic-force cues are present, but non-deontic cue evidence "
                    "outvotes deontic family evidence."
                ),
                candidate_ids=[predicted_family, target_family],
                severity="requires_rule",
                metadata={
                    "family_margin": round(family_margin, 6),
                    "family_ranking": list(ranking),
                    "lexical_signals": dict(sorted(signals.items())),
                    "outvote_margin_threshold": self.config.modal_deontic_target_family_outvote_margin,
                    "predicted_family": predicted_family,
                    "predicted_share": round(predicted_share, 6),
                    "target_family": target_family,
                    "target_share": round(target_share, 6),
                },
            )
        ]

    def _alethic_scope_target_family_ambiguities(
        self,
        encoding: SpaCyLegalEncoding,
        *,
        ranking: Sequence[Dict[str, Any]],
        family_shares: Dict[str, float],
    ) -> List[ModalCompilationAmbiguity]:
        if not ranking:
            return []
        predicted_family = str(ranking[0]["family"])
        target_family = ModalLogicFamily.ALETHIC.value
        if predicted_family == target_family:
            return []
        predicted_share = self._ranking_share(ranking[0])
        target_share = float(family_shares.get(target_family, 0.0))
        signals = _modal_ambiguity_signals(encoding)
        has_alethic_scope = bool(
            signals.get("has_alethic_scope") or signals.get("has_alethic_cue")
        )
        if not has_alethic_scope and target_share <= 0.0:
            return []
        family_margin = target_share - predicted_share
        if family_margin >= self.config.modal_alethic_target_family_outvote_margin:
            return []
        return [
            ModalCompilationAmbiguity(
                ambiguity_type="alethic_scope_family_outvoted",
                message=(
                    "Alethic necessity/possibility markers are present, but non-alethic "
                    "cue evidence outvotes alethic family evidence."
                ),
                candidate_ids=[predicted_family, target_family],
                severity="requires_rule",
                metadata={
                    "family_margin": round(family_margin, 6),
                    "family_ranking": list(ranking),
                    "lexical_signals": dict(sorted(signals.items())),
                    "outvote_margin_threshold": self.config.modal_alethic_target_family_outvote_margin,
                    "predicted_family": predicted_family,
                    "predicted_share": round(predicted_share, 6),
                    "target_family": target_family,
                    "target_share": round(target_share, 6),
                },
            )
        ]

    def _temporal_deontic_scope_family_ambiguities(
        self,
        encoding: SpaCyLegalEncoding,
        *,
        ranking: Sequence[Dict[str, Any]],
        family_shares: Dict[str, float],
    ) -> List[ModalCompilationAmbiguity]:
        if not ranking:
            return []
        predicted_family = str(ranking[0]["family"])
        if predicted_family not in {
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
        }:
            return []
        predicted_share = self._ranking_share(ranking[0])
        target_family = (
            ModalLogicFamily.DEONTIC.value
            if predicted_family == ModalLogicFamily.TEMPORAL.value
            else ModalLogicFamily.TEMPORAL.value
        )
        target_share = float(family_shares.get(target_family, 0.0))
        signals = _modal_ambiguity_signals(encoding)
        has_target_scope = bool(
            signals.get("has_deontic_scope")
            or signals.get("has_deontic_cue")
            if target_family == ModalLogicFamily.DEONTIC.value
            else signals.get("has_temporal_scope")
        )
        if not has_target_scope and target_share <= 0.0:
            return []
        family_margin = target_share - predicted_share
        outvote_margin_threshold = (
            self.config.modal_deontic_target_family_outvote_margin
            if target_family == ModalLogicFamily.DEONTIC.value
            else self.config.modal_temporal_target_family_outvote_margin
        )
        if family_margin >= outvote_margin_threshold:
            return []
        return [
            ModalCompilationAmbiguity(
                ambiguity_type="temporal_deontic_scope_family_outvoted",
                message=(
                    "Temporal-scope and deontic-force evidence compete; the top modal family "
                    "outvotes the opposite family and requires review."
                ),
                candidate_ids=[predicted_family, target_family],
                severity="requires_rule",
                metadata={
                    "family_margin": round(family_margin, 6),
                    "family_ranking": list(ranking),
                    "lexical_signals": dict(sorted(signals.items())),
                    "outvote_margin_threshold": outvote_margin_threshold,
                    "predicted_family": predicted_family,
                    "predicted_share": round(predicted_share, 6),
                    "target_family": target_family,
                    "target_share": round(target_share, 6),
                },
            )
        ]

    def _dynamic_scope_target_family_ambiguities(
        self,
        encoding: SpaCyLegalEncoding,
        *,
        ranking: Sequence[Dict[str, Any]],
        family_shares: Dict[str, float],
    ) -> List[ModalCompilationAmbiguity]:
        if not ranking:
            return []
        predicted_family = str(ranking[0]["family"])
        target_family = ModalLogicFamily.DYNAMIC.value
        if predicted_family == target_family:
            return []
        predicted_share = self._ranking_share(ranking[0])
        target_share = float(family_shares.get(target_family, 0.0))
        signals = _modal_ambiguity_signals(encoding)
        has_dynamic_scope = bool(
            signals.get("has_dynamic_scope") or signals.get("has_dynamic_cue")
        )
        if not has_dynamic_scope and target_share <= 0.0:
            return []
        family_margin = target_share - predicted_share
        if family_margin >= self.config.modal_dynamic_target_family_outvote_margin:
            return []
        return [
            ModalCompilationAmbiguity(
                ambiguity_type="dynamic_scope_family_outvoted",
                message=(
                    "Action-transition markers are present, but non-dynamic cue evidence "
                    "outvotes dynamic family evidence."
                ),
                candidate_ids=[predicted_family, target_family],
                severity="requires_rule",
                metadata={
                    "family_margin": round(family_margin, 6),
                    "family_ranking": list(ranking),
                    "lexical_signals": dict(sorted(signals.items())),
                    "outvote_margin_threshold": self.config.modal_dynamic_target_family_outvote_margin,
                    "predicted_family": predicted_family,
                    "predicted_share": round(predicted_share, 6),
                    "target_family": target_family,
                    "target_share": round(target_share, 6),
                },
            )
        ]

    def _frame_ambiguities(
        self,
        frame_selections: Sequence[FrameSelection],
    ) -> List[ModalCompilationAmbiguity]:
        if len(frame_selections) < 2:
            return []
        first, second = frame_selections[0], frame_selections[1]
        margin = float(first.score) - float(second.score)
        if margin > self.config.frame_score_margin:
            return []
        return [
            ModalCompilationAmbiguity(
                ambiguity_type="close_bm25_frame_scores",
                message="Top ontology frame choices are close enough to require review.",
                candidate_ids=[first.frame.frame_id, second.frame.frame_id],
                metadata={
                    "margin": round(margin, 6),
                    "top_score": first.score,
                    "runner_up_score": second.score,
                },
            )
        ]


__all__ = [
    "DeterministicModalCompiler",
    "ModalCompilationAmbiguity",
    "ModalCompilationResult",
    "ModalCompilerConfig",
]
