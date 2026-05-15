"""Cost-gated legal modal autoencoder loop.

This module orchestrates the cheap-first path:

1. spaCy/deterministic codec builds modal IR with embedded frame logic.
2. Frame logic is imported into the Neo4j-compatible graph engine.
3. Modal formulas are compiled through local theorem prover routing.
4. The adaptive autoencoder gate decides whether an expensive Codex repair
   call is justified.

Codex is never called unless ``allow_llm_repair`` is enabled and the gate
decides the expected benefit beats the configured call cost.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence as SequenceABC
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

from ipfs_datasets_py.optimizers.common.llm_defaults import (
    DEFAULT_CODEX_MODEL,
    DEFAULT_CODEX_PROVIDER,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    LegalSample,
    stable_mock_embedding,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    CodexCallCache,
    CodexCallDecision,
    CodexCallGateConfig,
    ProverCompilationSignal,
    evaluate_modal_prover_compilation,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFrameLogic,
)

from .codec import (
    DeterministicModalLogicCodec,
    ModalLogicCodecConfig,
    ModalLogicCodecResult,
)
from .kg_bridge import flogic_triples_to_graph_data, import_modal_ir_to_graph_engine

LLMGenerateFn = Callable[..., str]
_PATCH_PREDICATE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True)
class ModalAutoencoderLoopConfig:
    """Configuration for the legal modal autoencoder/Codex loop."""

    codec_config: ModalLogicCodecConfig = field(default_factory=ModalLogicCodecConfig)
    gate_config: CodexCallGateConfig = field(default_factory=CodexCallGateConfig)
    evaluate_provers: bool = True
    import_frame_logic_graph: bool = True
    check_external_prover_router: bool = False
    allow_llm_repair: bool = False
    apply_llm_frame_logic_patches: bool = False
    llm_provider: str = DEFAULT_CODEX_PROVIDER
    llm_model: str = DEFAULT_CODEX_MODEL
    llm_timeout: float = 900.0
    llm_max_new_tokens: int = 2048
    llm_temperature: float = 0.0
    codex_cache_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allow_llm_repair": self.allow_llm_repair,
            "apply_llm_frame_logic_patches": self.apply_llm_frame_logic_patches,
            "check_external_prover_router": self.check_external_prover_router,
            "codex_cache_path": self.codex_cache_path,
            "codec_config": self.codec_config.__dict__,
            "evaluate_provers": self.evaluate_provers,
            "gate_config": self.gate_config.to_dict(),
            "import_frame_logic_graph": self.import_frame_logic_graph,
            "llm_max_new_tokens": self.llm_max_new_tokens,
            "llm_model": self.llm_model,
            "llm_provider": self.llm_provider,
            "llm_temperature": self.llm_temperature,
            "llm_timeout": self.llm_timeout,
        }


@dataclass(frozen=True)
class FrameLogicPatchValidation:
    """Grounding report for Codex-proposed frame-logic triples."""

    accepted_triples: Sequence[Dict[str, str]] = field(default_factory=tuple)
    rejected_triples: Sequence[Dict[str, Any]] = field(default_factory=tuple)

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_triples)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_triples)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted_count": self.accepted_count,
            "accepted_triples": list(self.accepted_triples),
            "rejected_count": self.rejected_count,
            "rejected_triples": list(self.rejected_triples),
        }


@dataclass(frozen=True)
class ModalAutoencoderLoopResult:
    """Audit record for one autoencoder loop pass."""

    source_text: str
    codec_result: ModalLogicCodecResult
    sample: LegalSample
    codex_decision: CodexCallDecision
    accepted: bool
    graph_import_report: Dict[str, int] = field(default_factory=dict)
    prover_signal: Optional[ProverCompilationSignal] = None
    available_external_provers: Sequence[str] = field(default_factory=tuple)
    llm_called: bool = False
    llm_response: str = ""
    llm_patch: Optional[Dict[str, Any]] = None
    llm_patch_validation: Optional["FrameLogicPatchValidation"] = None
    repaired_modal_ir: Optional[ModalIRDocument] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def final_modal_ir(self) -> ModalIRDocument:
        return self.repaired_modal_ir or self.codec_result.modal_ir

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "available_external_provers": list(self.available_external_provers),
            "codex_decision": self.codex_decision.to_dict(),
            "codec_result": self.codec_result.to_dict(),
            "final_modal_ir": self.final_modal_ir.to_dict(),
            "graph_import_report": dict(self.graph_import_report),
            "llm_called": self.llm_called,
            "llm_patch": self.llm_patch,
            "llm_patch_validation": self.llm_patch_validation.to_dict()
            if self.llm_patch_validation
            else None,
            "llm_response": self.llm_response,
            "metadata": dict(sorted(self.metadata.items())),
            "prover_signal": self.prover_signal.to_dict() if self.prover_signal else None,
            "sample": self.sample.to_dict(),
            "source_text": self.source_text,
        }


class LegalModalAutoencoderLoop:
    """Run the deterministic legal modal codec plus a sparse Codex repair loop."""

    def __init__(
        self,
        config: Optional[ModalAutoencoderLoopConfig] = None,
        *,
        codec: Optional[DeterministicModalLogicCodec] = None,
        autoencoder: Optional[AdaptiveModalAutoencoder] = None,
        cache: Optional[CodexCallCache] = None,
        llm_generate: Optional[LLMGenerateFn] = None,
    ) -> None:
        self.config = config or ModalAutoencoderLoopConfig()
        self.cache_path = (
            Path(self.config.codex_cache_path).expanduser()
            if self.config.codex_cache_path
            else None
        )
        self.codec = codec or DeterministicModalLogicCodec(self.config.codec_config)
        self.autoencoder = autoencoder or AdaptiveModalAutoencoder(feature_codec=self.codec)
        self.cache = cache if cache is not None else self._load_cache()
        self.llm_generate = llm_generate

    def run(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "us_code",
        title: str = "modal",
        section: Optional[str] = None,
        source_embedding: Optional[Sequence[float]] = None,
        allow_llm_repair: Optional[bool] = None,
    ) -> ModalAutoencoderLoopResult:
        """Run one cheap-first legal text -> modal IR -> validation pass."""

        codec_result = self.codec.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
        )
        sample = _sample_from_codec_result(
            codec_result,
            title=title,
            section=section or document_id or codec_result.modal_ir.document_id,
            embedding_vector=source_embedding,
        )
        graph_report = self._import_graph(sample.modal_ir)
        prover_signal = self._evaluate_provers(sample)
        available_external_provers = self._external_prover_inventory()
        decision = self.autoencoder.codex_call_decision(
            sample,
            config=self.config.gate_config,
            cache=self.cache,
            prover_signal=prover_signal,
        )

        llm_called = False
        llm_response = ""
        llm_patch: Optional[Dict[str, Any]] = None
        llm_patch_validation: Optional[FrameLogicPatchValidation] = None
        repaired_modal_ir: Optional[ModalIRDocument] = None
        should_call_llm = (
            self.config.allow_llm_repair
            if allow_llm_repair is None
            else bool(allow_llm_repair)
        )

        if decision.should_call_codex and should_call_llm:
            llm_called = True
            self.cache.record_codex_call(decision)
            llm_response = self._call_llm_repair(codec_result, sample, decision, prover_signal)
            llm_patch = _parse_json_object(llm_response)
            if llm_patch:
                llm_patch_validation = validate_frame_logic_patch(sample.modal_ir, llm_patch)
            if self.config.apply_llm_frame_logic_patches and llm_patch:
                repaired_modal_ir = _apply_frame_logic_patch(
                    sample.modal_ir,
                    llm_patch,
                    validation=llm_patch_validation,
                )
            self.save_cache()
        elif not decision.reasons:
            self.cache.record_local_success(decision)
            self.save_cache()

        accepted = _accepted(
            decision,
            graph_report=graph_report,
            prover_signal=prover_signal,
            require_provers=self.config.evaluate_provers,
        )
        return ModalAutoencoderLoopResult(
            source_text=text,
            codec_result=codec_result,
            sample=sample,
            codex_decision=decision,
            accepted=accepted,
            graph_import_report=graph_report,
            prover_signal=prover_signal,
            available_external_provers=tuple(available_external_provers),
            llm_called=llm_called,
            llm_response=llm_response,
            llm_patch=llm_patch,
            llm_patch_validation=llm_patch_validation,
            repaired_modal_ir=repaired_modal_ir,
            metadata={
                "llm_model": self.config.llm_model if llm_called else "",
                "llm_provider": self.config.llm_provider if llm_called else "",
                "loop": "legal_modal_autoencoder_loop_v1",
                "codex_cache_path": str(self.cache_path) if self.cache_path else "",
            },
        )

    def run_many(
        self,
        records: Iterable[Mapping[str, Any] | str],
        *,
        allow_llm_repair: Optional[bool] = None,
        default_source: str = "us_code",
        default_title: str = "modal",
    ) -> Sequence[ModalAutoencoderLoopResult]:
        """Run multiple legal text records through one shared gate/cache."""

        results = []
        for index, record in enumerate(records):
            if isinstance(record, str):
                text = record
                kwargs: Dict[str, Any] = {
                    "source": default_source,
                    "title": default_title,
                }
            elif isinstance(record, Mapping):
                text = str(record.get("text") or "")
                kwargs = {
                    "citation": _optional_str(record.get("citation")),
                    "document_id": _optional_str(
                        record.get("document_id") or record.get("sample_id") or record.get("id")
                    ),
                    "section": _optional_str(record.get("section")),
                    "source": _optional_str(record.get("source")) or default_source,
                    "source_embedding": record.get("source_embedding")
                    or record.get("embedding_vector"),
                    "title": _optional_str(record.get("title")) or default_title,
                }
            else:
                raise TypeError(f"Unsupported record type at index {index}: {type(record)!r}")
            if not text.strip():
                raise ValueError(f"Loop record at index {index} has empty text")
            results.append(
                self.run(
                    text,
                    allow_llm_repair=allow_llm_repair,
                    **kwargs,
                )
            )
        return tuple(results)

    def save_cache(self) -> None:
        """Persist the Codex call gate cache when ``codex_cache_path`` is set."""

        if self.cache_path is None:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(
                self.cache.to_dict(),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )

    def _load_cache(self) -> CodexCallCache:
        if self.cache_path is None or not self.cache_path.exists():
            return CodexCallCache()
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(data, Mapping):
                return _codex_cache_from_mapping(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
        return CodexCallCache()

    def _import_graph(self, modal_ir: ModalIRDocument) -> Dict[str, int]:
        if not self.config.import_frame_logic_graph:
            return {}
        _, report = import_modal_ir_to_graph_engine(modal_ir)
        return report

    def _evaluate_provers(self, sample: LegalSample) -> Optional[ProverCompilationSignal]:
        if not self.config.evaluate_provers:
            return None
        return evaluate_modal_prover_compilation(sample)

    def _external_prover_inventory(self) -> Sequence[str]:
        if not self.config.check_external_prover_router:
            return ()
        try:
            from ipfs_datasets_py.logic.external_provers import ProverRouter

            router = ProverRouter(
                enable_z3=True,
                enable_cvc5=True,
                enable_lean=True,
                enable_coq=True,
                enable_native=False,
                enable_symbolicai=True,
                enable_cache=True,
            )
            return tuple(router.get_available_provers())
        except Exception:
            return ()

    def _call_llm_repair(
        self,
        codec_result: ModalLogicCodecResult,
        sample: LegalSample,
        decision: CodexCallDecision,
        prover_signal: Optional[ProverCompilationSignal],
    ) -> str:
        generate = self.llm_generate
        if generate is None:
            from ipfs_datasets_py import llm_router

            generate = llm_router.generate_text

        return generate(
            _repair_prompt(codec_result, sample, decision, prover_signal),
            provider=self.config.llm_provider,
            model_name=self.config.llm_model,
            allow_local_fallback=False,
            disable_model_retry=True,
            max_new_tokens=int(self.config.llm_max_new_tokens),
            temperature=float(self.config.llm_temperature),
            timeout=float(self.config.llm_timeout),
        )


def _sample_from_codec_result(
    codec_result: ModalLogicCodecResult,
    *,
    title: str,
    section: str,
    embedding_vector: Optional[Sequence[float]],
) -> LegalSample:
    modal_ir = codec_result.modal_ir
    return LegalSample(
        sample_id=modal_ir.document_id,
        source="us_code",
        title=str(title or "modal"),
        section=str(section or modal_ir.document_id),
        citation=_citation_for_modal_ir(modal_ir),
        text=codec_result.source_text,
        normalized_text=codec_result.normalized_text,
        embedding_model="provided" if embedding_vector is not None else "mock:stable-sha256",
        embedding_vector=list(embedding_vector)
        if embedding_vector is not None
        else stable_mock_embedding(
            codec_result.normalized_text,
            dimensions=len(codec_result.source_embedding),
        ),
        modal_ir=modal_ir,
        frame_candidates=list(codec_result.frame_candidates),
        selected_frame=codec_result.selected_frame,
        parser_trace={
            "deterministic_parser": codec_result.parser_name,
            "loop": "legal_modal_autoencoder_loop_v1",
        },
        losses=dict(codec_result.losses),
    )


def _codex_cache_from_mapping(data: Mapping[str, Any]) -> CodexCallCache:
    return CodexCallCache(
        codex_text_hashes={
            str(value)
            for value in data.get("codex_text_hashes", [])
            if str(value)
        },
        codex_feature_signature_hashes={
            str(value)
            for value in data.get("codex_feature_signature_hashes", [])
            if str(value)
        },
        local_success_feature_signature_hashes={
            str(value)
            for value in data.get("local_success_feature_signature_hashes", [])
            if str(value)
        },
        codex_call_count=max(0, int(data.get("codex_call_count", 0) or 0)),
    )


def _optional_str(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _accepted(
    decision: CodexCallDecision,
    *,
    graph_report: Mapping[str, int],
    prover_signal: Optional[ProverCompilationSignal],
    require_provers: bool,
) -> bool:
    if decision.reasons:
        return False
    if graph_report and int(graph_report.get("missing_endpoint_relationships", 0)) > 0:
        return False
    if require_provers and prover_signal is not None and not prover_signal.compiles:
        return False
    return True


def _repair_prompt(
    codec_result: ModalLogicCodecResult,
    sample: LegalSample,
    decision: CodexCallDecision,
    prover_signal: Optional[ProverCompilationSignal],
) -> str:
    payload = {
        "allowed_patch_shape": {
            "deterministic_rule_hints": [
                {
                    "action": "add_or_refine_spacy_rule",
                    "rationale": "short reason",
                    "target_component": "modal.compiler",
                }
            ],
            "frame_logic_triples": [
                {"object": "value", "predicate": "relation", "subject": "node"}
            ],
            "notes": "short explanation",
        },
        "decision": decision.to_dict(),
        "frame_logic_triples": codec_result.modal_ir.frame_logic.to_triples(),
        "losses": codec_result.losses,
        "modal_ir": codec_result.modal_ir.to_dict(),
        "prover_signal": prover_signal.to_dict() if prover_signal else None,
        "source_text": sample.text,
    }
    return (
        "You are repairing a deterministic legal modal IR. Return strict JSON only. "
        "Do not rewrite the law. Prefer deterministic spaCy/token/frame-logic rule "
        "hints over free-form translation. Only propose frame_logic_triples whose "
        "subject, predicate, and object are grounded in the source text or modal IR.\n\n"
        + json.dumps(payload, ensure_ascii=True, sort_keys=True)
    )


def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(stripped[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


def validate_frame_logic_patch(
    modal_ir: ModalIRDocument,
    patch: Mapping[str, Any],
) -> FrameLogicPatchValidation:
    """Return grounded triples from a Codex frame-logic patch."""

    triples = patch.get("frame_logic_triples")
    if not isinstance(triples, SequenceABC) or isinstance(triples, (str, bytes)):
        return FrameLogicPatchValidation(
            rejected_triples=(
                {
                    "reasons": ["missing_frame_logic_triples"],
                    "triple": triples,
                },
            )
        )

    existing = {
        (item["subject"], item["predicate"], item["object"])
        for item in modal_ir.frame_logic.to_triples()
    }
    accepted: list[Dict[str, str]] = []
    rejected: list[Dict[str, Any]] = []
    seen = set(existing)
    context = _grounding_context(modal_ir)

    for triple in triples:
        if not isinstance(triple, Mapping):
            rejected.append({"reasons": ["triple_not_object"], "triple": triple})
            continue
        subject = str(triple.get("subject", "")).strip()
        predicate = str(triple.get("predicate", "")).strip()
        obj = str(triple.get("object", "")).strip()
        normalized = {"subject": subject, "predicate": predicate, "object": obj}
        reasons = _frame_logic_triple_rejection_reasons(
            normalized,
            context=context,
            seen=seen,
        )
        if reasons:
            rejected.append({"reasons": reasons, "triple": normalized})
            continue
        key = (subject, predicate, obj)
        seen.add(key)
        accepted.append(normalized)

    return FrameLogicPatchValidation(
        accepted_triples=tuple(accepted),
        rejected_triples=tuple(rejected),
    )


def _apply_frame_logic_patch(
    modal_ir: ModalIRDocument,
    patch: Mapping[str, Any],
    *,
    validation: Optional[FrameLogicPatchValidation] = None,
) -> Optional[ModalIRDocument]:
    validation = validation or validate_frame_logic_patch(modal_ir, patch)
    normalized = list(validation.accepted_triples)
    if not normalized:
        return None
    all_triples = [*modal_ir.frame_logic.to_triples(), *normalized]
    graph_data = flogic_triples_to_graph_data(
        all_triples,
        graph_id=modal_ir.frame_logic.graph_id or f"{modal_ir.document_id}:flogic",
        metadata={
            "modal_ir_document_id": modal_ir.document_id,
            "modal_ir_hash": modal_ir.canonical_hash(),
            "modal_ir_version": modal_ir.version,
        },
    )
    graph_schema = graph_data.schema
    frame_logic = ModalIRFrameLogic.from_triples(
        all_triples,
        ontology_name=modal_ir.frame_logic.ontology_name,
        selected_frame=modal_ir.frame_logic.selected_frame,
        graph_id=graph_data.metadata.get("graph_id"),
        neo4j_node_labels=graph_schema.node_labels if graph_schema else [],
        neo4j_relationship_types=graph_schema.relationship_types
        if graph_schema
        else [],
        metadata={
            **modal_ir.frame_logic.metadata,
            "llm_patch_applied": True,
        },
    )
    return replace(
        modal_ir,
        frame_logic=frame_logic,
        metadata={
            **modal_ir.metadata,
            "llm_frame_logic_patch_count": len(normalized),
        },
    )


def _frame_logic_triple_rejection_reasons(
    triple: Mapping[str, str],
    *,
    context: Mapping[str, Any],
    seen: set[tuple[str, str, str]],
) -> list[str]:
    subject = str(triple.get("subject", "")).strip()
    predicate = str(triple.get("predicate", "")).strip()
    obj = str(triple.get("object", "")).strip()
    reasons: list[str] = []
    if not subject:
        reasons.append("empty_subject")
    if not predicate:
        reasons.append("empty_predicate")
    if not obj:
        reasons.append("empty_object")
    if predicate and not _PATCH_PREDICATE_RE.match(predicate):
        reasons.append("unsafe_predicate")
    if (subject, predicate, obj) in seen:
        reasons.append("duplicate_triple")
    if subject and not _is_grounded_value(
        subject,
        exact_values=context["subjects"],
        source_text=context["source_text"],
        modal_text=context["modal_text"],
    ):
        reasons.append("ungrounded_subject")
    if obj and not _is_grounded_value(
        obj,
        exact_values=context["values"],
        source_text=context["source_text"],
        modal_text=context["modal_text"],
    ):
        reasons.append("ungrounded_object")
    return reasons


def _grounding_context(modal_ir: ModalIRDocument) -> Dict[str, Any]:
    subjects = {modal_ir.document_id}
    values = {modal_ir.document_id, modal_ir.source, modal_ir.version}
    modal_payloads: list[Any] = [modal_ir.to_dict()]
    for triple in modal_ir.frame_logic.to_triples():
        subjects.add(str(triple.get("subject", "")))
        values.update(str(triple.get(key, "")) for key in ("subject", "predicate", "object"))
    for frame in modal_ir.frame_candidates:
        subjects.add(frame.frame_id)
        values.add(frame.frame_id)
        values.update(frame.matched_terms)
    for formula in modal_ir.formulas:
        subjects.add(formula.formula_id)
        values.add(formula.formula_id)
        values.add(formula.operator.family)
        values.add(formula.operator.system)
        values.add(formula.operator.symbol)
        values.add(formula.operator.label)
        values.add(formula.predicate.name)
        values.update(formula.predicate.arguments)
        values.update(formula.conditions)
        values.update(formula.exceptions)
        if formula.predicate.role:
            values.add(formula.predicate.role)
        if formula.provenance.citation:
            values.add(formula.provenance.citation)
    return {
        "modal_text": json.dumps(modal_payloads, ensure_ascii=True, sort_keys=True),
        "source_text": modal_ir.normalized_text,
        "subjects": {value for value in subjects if value},
        "values": {value for value in values if value},
    }


def _is_grounded_value(
    value: str,
    *,
    exact_values: set[str],
    source_text: str,
    modal_text: str,
) -> bool:
    if value in exact_values:
        return True
    normalized_value = _normalize_grounding_text(value)
    if not normalized_value:
        return False
    exact_normalized = {_normalize_grounding_text(item) for item in exact_values}
    if normalized_value in exact_normalized:
        return True
    return _contains_grounded_phrase(normalized_value, source_text) or _contains_grounded_phrase(
        normalized_value,
        modal_text,
    )


def _contains_grounded_phrase(normalized_value: str, haystack: str) -> bool:
    normalized_haystack = _normalize_grounding_text(haystack)
    if not normalized_value or not normalized_haystack:
        return False
    value_tokens = _WORD_RE.findall(normalized_value)
    if not value_tokens:
        return False
    if len(value_tokens) == 1:
        return value_tokens[0] in set(_WORD_RE.findall(normalized_haystack))
    return f" {normalized_value} " in f" {normalized_haystack} "


def _normalize_grounding_text(value: Any) -> str:
    return " ".join(_WORD_RE.findall(str(value or "").lower()))


def _citation_for_modal_ir(modal_ir: ModalIRDocument) -> str:
    for formula in modal_ir.formulas:
        citation = getattr(formula.provenance, "citation", None)
        if citation:
            return str(citation)
    return str(modal_ir.metadata.get("citation") or modal_ir.document_id)


__all__ = [
    "FrameLogicPatchValidation",
    "LegalModalAutoencoderLoop",
    "ModalAutoencoderLoopConfig",
    "ModalAutoencoderLoopResult",
    "validate_frame_logic_patch",
]
