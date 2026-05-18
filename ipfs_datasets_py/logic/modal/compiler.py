"""Deterministic compiler for legal text into modal IR.

This module is deliberately rule-based and auditable.  It can surface
ambiguities for a neural or human advisor, but it does not use adaptive weights
to decide the canonical IR.
"""

from __future__ import annotations

import math
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
    DEFAULT_MODAL_REGISTRY,
    ModalLogicFamily,
    ModalRegistry,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_normative_modal_family,
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
            adaptive_ranking = self._adaptive_family_ranking_from_logits(encoding)
            if not adaptive_ranking:
                return []
            adaptive_family_shares = {
                str(candidate["family"]): self._ranking_share(candidate)
                for candidate in adaptive_ranking
            }
            return self._adaptive_family_margin_ambiguities(
                encoding,
                modal_ir=modal_ir,
                ranking=adaptive_ranking,
                family_shares=adaptive_family_shares,
                frame_selections=frame_selections,
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
            self._adaptive_family_margin_ambiguities(
                encoding,
                modal_ir=modal_ir,
                ranking=ranking,
                family_shares=family_shares,
                frame_selections=frame_selections,
            )
        )
        if len(ranking) < 2:
            return ambiguities

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
        return ambiguities

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
    ) -> List[ModalCompilationAmbiguity]:
        """Surface explicit ambiguities when strong legal families compete."""
        if not ranking:
            return []
        predicted_family = str(ranking[0]["family"])
        predicted_share = self._ranking_share(ranking[0])
        runner_up_family: Optional[str] = None
        runner_up_share = 0.0
        predicted_margin_to_runner_up: Optional[float] = None
        if len(ranking) > 1:
            runner_up_family = str(ranking[1]["family"])
            runner_up_share = self._ranking_share(ranking[1])
            predicted_margin_to_runner_up = predicted_share - runner_up_share
        signals = modal_ambiguity_signals(encoding)
        threshold = float(self.config.modal_adaptive_family_margin)
        has_frame_bm25_support = self._has_frame_bm25_support(frame_selections)
        compiled_modal_families = {
            str(formula.operator.family) for formula in modal_ir.formulas
        }
        compiled_primary_family = (
            str(modal_ir.formulas[0].operator.family)
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
        for policy_target_family in signal_free_adaptive_ambiguity_targets(
            predicted_family
        ):
            target_signal_by_family.setdefault(policy_target_family, False)
        if not target_signal_by_family:
            return []
        ambiguities: List[ModalCompilationAmbiguity] = []
        for target_family, has_signal in target_signal_by_family.items():
            is_self_pair = target_family == predicted_family
            if is_self_pair and (
                predicted_margin_to_runner_up is None
                or predicted_margin_to_runner_up > threshold
            ):
                continue
            target_share = float(family_shares.get(target_family, 0.0))
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
            is_priority_policy_pair = is_priority_signal_free_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )
            if (
                not has_target_signal_evidence
                and not supports_signal_free_pair_policy
            ):
                continue
            family_margin = target_share - predicted_share
            if family_margin > threshold:
                continue
            margin_direction = "outvoted" if (
                family_margin < 0.0
                or (family_margin <= 0.0 and is_priority_policy_pair)
            ) else "contested"
            requires_rule = margin_direction == "outvoted"
            explicit_type = self._adaptive_margin_explicit_type(
                predicted_family,
                target_family,
                margin_direction,
            )
            predicted_share_display = round(predicted_share, 6)
            target_share_display = round(target_share, 6)
            family_margin_display = round(
                target_share_display - predicted_share_display,
                6,
            )
            candidate_ids = (
                [predicted_family]
                if is_self_pair
                else [predicted_family, target_family]
            )
            base_metadata = {
                "adaptive_family_margin_threshold": threshold,
                "adaptive_margin_direction": margin_direction,
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
                "is_priority_policy_pair": is_priority_policy_pair,
                "predicted_family": predicted_family,
                "predicted_margin_to_runner_up_raw": predicted_margin_to_runner_up,
                "predicted_margin_to_runner_up": (
                    round(predicted_margin_to_runner_up, 6)
                    if predicted_margin_to_runner_up is not None
                    else None
                ),
                "runner_up_family": runner_up_family,
                "runner_up_share_raw": (
                    runner_up_share if runner_up_family is not None else None
                ),
                "runner_up_share": (
                    round(runner_up_share, 6)
                    if runner_up_family is not None
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
                    metadata=dict(base_metadata),
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
                        "adaptive_base_ambiguity_type": "adaptive_family_margin_low",
                    },
                )
            )
        if (
            compiled_primary_family is not None
            and compiled_primary_family != predicted_family
        ):
            ambiguities.extend(
                self._compiled_primary_family_adaptive_pair_ambiguities(
                    compiled_primary_family=compiled_primary_family,
                    competing_family=predicted_family,
                    ranking=ranking,
                    family_shares=family_shares,
                    threshold=threshold,
                    signals=signals,
                    has_frame_scope=has_frame_scope,
                    has_frame_bm25_support=has_frame_bm25_support,
                    compiled_modal_families=compiled_modal_families,
                )
            )
        return ambiguities

    def _adaptive_target_signal_by_family(
        self,
        predicted_family: str,
        *,
        signals: Mapping[str, bool],
        has_frame_scope: bool,
    ) -> Dict[str, bool]:
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
                ModalLogicFamily.ALETHIC.value: bool(
                    signals.get("has_alethic_scope")
                    or signals.get("has_alethic_cue")
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
                ),
            }
        elif predicted_family == ModalLogicFamily.HYBRID.value:
            target_signal_by_family = {
                ModalLogicFamily.FRAME.value: has_frame_scope,
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
                ModalLogicFamily.TEMPORAL.value: bool(
                    signals.get("has_temporal_scope")
                ),
            }
        elif predicted_family == ModalLogicFamily.CONDITIONAL_NORMATIVE.value:
            target_signal_by_family = {
                ModalLogicFamily.EPISTEMIC.value: bool(
                    signals.get("has_epistemic_cue")
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
    ) -> List[ModalCompilationAmbiguity]:
        if not self._supports_signal_free_adaptive_pair(
            compiled_primary_family,
            competing_family,
        ):
            return []
        primary_share = float(family_shares.get(compiled_primary_family, 0.0))
        competing_share = float(family_shares.get(competing_family, 0.0))
        family_margin = primary_share - competing_share
        if family_margin > threshold:
            return []
        target_signal_by_family = self._adaptive_target_signal_by_family(
            compiled_primary_family,
            signals=signals,
            has_frame_scope=has_frame_scope,
        )
        has_signal = bool(target_signal_by_family.get(competing_family, False))
        has_compiled_target_family_formula = competing_family in compiled_modal_families
        has_target_signal_evidence = bool(
            has_signal
            or competing_share > 0.0
            or has_compiled_target_family_formula
        )
        is_priority_policy_pair = is_priority_signal_free_adaptive_ambiguity_pair(
            compiled_primary_family,
            competing_family,
        )
        margin_direction = "outvoted" if (
            family_margin < 0.0
            or (family_margin <= 0.0 and is_priority_policy_pair)
        ) else "contested"
        requires_rule = margin_direction == "outvoted"
        explicit_type = self._adaptive_margin_explicit_type(
            compiled_primary_family,
            competing_family,
            margin_direction,
        )
        primary_share_display = round(primary_share, 6)
        competing_share_display = round(competing_share, 6)
        family_margin_display = round(
            primary_share_display - competing_share_display,
            6,
        )
        base_metadata = {
            "adaptive_family_margin_threshold": threshold,
            "adaptive_margin_direction": margin_direction,
            "adaptive_predicted_family_source": "compiled_primary_family",
            "explicit_ambiguity_type": explicit_type,
            "family_margin_raw": family_margin,
            "family_margin": family_margin_display,
            "family_ranking": list(ranking),
            "compiled_modal_families": sorted(compiled_modal_families),
            "has_target_signal_evidence": has_target_signal_evidence,
            "signal_free_pair_policy_applied": (
                not has_target_signal_evidence
            ),
            "has_compiled_target_family_formula": has_compiled_target_family_formula,
            "has_frame_bm25_support": has_frame_bm25_support,
            "lexical_signals": dict(sorted(signals.items())),
            "is_priority_policy_pair": is_priority_policy_pair,
            "predicted_family": compiled_primary_family,
            "predicted_margin_to_runner_up_raw": family_margin,
            "predicted_margin_to_runner_up": round(family_margin, 6),
            "runner_up_family": competing_family,
            "runner_up_share_raw": competing_share,
            "runner_up_share": competing_share_display,
            "predicted_share_raw": primary_share,
            "predicted_share": primary_share_display,
            "target_family": competing_family,
            "target_share_raw": competing_share,
            "target_share": competing_share_display,
            "is_self_pair": False,
        }
        return [
            ModalCompilationAmbiguity(
                ambiguity_type="adaptive_family_margin_low",
                message=(
                    "The compiled primary modal family is outvoted by competing "
                    "cue evidence; family selection is ambiguous."
                ),
                candidate_ids=[compiled_primary_family, competing_family],
                severity="requires_rule" if requires_rule else "review",
                metadata=dict(base_metadata),
            ),
            ModalCompilationAmbiguity(
                ambiguity_type=explicit_type,
                message=(
                    "Explicit adaptive modal-family conflict between the "
                    "compiled primary family and a competing cue-dominant "
                    "family."
                ),
                candidate_ids=[compiled_primary_family, competing_family],
                severity="requires_rule" if requires_rule else "review",
                metadata={
                    **base_metadata,
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

    def _supports_signal_free_adaptive_pair(
        self,
        predicted_family: str,
        target_family: str,
    ) -> bool:
        """Return whether this pair must surface adaptive ambiguity without lexical support."""
        return supports_signal_free_adaptive_ambiguity_pair(
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
        signals = modal_ambiguity_signals(encoding)
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
        signals = modal_ambiguity_signals(encoding)
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
        signals = modal_ambiguity_signals(encoding)
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
        signals = modal_ambiguity_signals(encoding)
        has_condition_scope = bool(signals.get("has_condition_or_exception_scope"))
        if not has_condition_scope and target_share <= 0.0:
            return []
        family_margin = target_share - predicted_share
        if family_margin >= self.config.modal_conditional_target_family_outvote_margin:
            return []
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
        signals = modal_ambiguity_signals(encoding)
        has_deontic_scope = bool(signals.get("has_deontic_scope"))
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
        signals = modal_ambiguity_signals(encoding)
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
        signals = modal_ambiguity_signals(encoding)
        has_target_scope = bool(
            signals.get("has_deontic_scope")
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
        signals = modal_ambiguity_signals(encoding)
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
