"""Deterministic compiler for legal text into modal IR.

This module is deliberately rule-based and auditable.  It can surface
ambiguities for a neural or human advisor, but it does not use adaptive weights
to decide the canonical IR.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, List, Optional, Sequence

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
    is_normative_modal_family,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    SpaCyLegalEncoder,
    SpaCyLegalEncoding,
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
    modal_primary_family_outvote_margin: float = 0.0
    modal_temporal_target_family_outvote_margin: float = 0.0


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
            *self._family_ambiguities(encoding, modal_ir=modal_ir),
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

    def _family_ambiguities(
        self,
        encoding: SpaCyLegalEncoding,
        *,
        modal_ir: ModalIRDocument,
    ) -> List[ModalCompilationAmbiguity]:
        ranking = ranked_modal_families(encoding)
        if not ranking:
            return []

        ambiguities: List[ModalCompilationAmbiguity] = []
        family_shares = {
            str(candidate["family"]): float(candidate["share"])
            for candidate in ranking
        }
        if modal_ir.formulas:
            primary_family = str(modal_ir.formulas[0].operator.family)
            primary_share = next(
                (
                    float(candidate["share"])
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
                    float(candidate["share"]),
                    str(candidate["family"]),
                ),
                default=None,
            )
            if best_other is not None:
                best_other_family = str(best_other["family"])
                best_other_share = float(best_other["share"])
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
        if len(ranking) < 2:
            return ambiguities

        top, runner_up = ranking[0], ranking[1]
        share_margin = float(top["share"]) - float(runner_up["share"])
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
                    float(candidate["share"]),
                    str(candidate["family"]),
                ),
                default=None,
            )
            if best_non_frame is not None:
                competing_family = str(best_non_frame["family"])
                competing_share = float(best_non_frame["share"])
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
            if float(candidate["share"]) >= self.config.modal_family_secondary_share_floor
        ]
        contender_families = {
            str(candidate["family"]) for candidate in strong_contenders
        }
        has_temporal = ModalLogicFamily.TEMPORAL.value in contender_families
        has_normative = any(
            is_normative_modal_family(str(candidate["family"]))
            for candidate in strong_contenders
        )
        runner_share = float(runner_up["share"])
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
        temporal_share = float(ranking[0]["share"])
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
        predicted_share = float(ranking[0]["share"])
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
