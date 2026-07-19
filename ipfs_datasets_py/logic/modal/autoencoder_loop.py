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
import time
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
from ipfs_datasets_py.logic.bridge import DEFAULT_LEGAL_IR_BRIDGE_NAMES

from .codec import (
    DeterministicModalLogicCodec,
    ModalLogicCodecConfig,
    ModalLogicCodecResult,
)
from .kg_bridge import flogic_triples_to_graph_data, import_modal_ir_to_graph_engine
from .leanstral import (
    LeanstralConfig,
    LeanstralShadowResult,
    LeanstralShadowRunner,
)

LLMGenerateFn = Callable[..., str]
_PATCH_PREDICATE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
MODAL_INTROSPECTION_MODES = frozenset({"off", "export", "shadow", "seed", "enforce"})


@dataclass(frozen=True)
class ModalIntrospectionSummary:
    """Rollout-control summary for learned LegalIR introspection."""

    mode: str = "off"
    alive: bool = True
    productive: bool = False
    audits_attempted: int = 0
    audits_exported: int = 0
    todos_seeded: int = 0
    target_scope_matched: bool = True
    prover_confirmed: bool = True
    enforce_allowed: bool = True
    blocked_reasons: Sequence[str] = field(default_factory=tuple)
    target_scopes: Sequence[str] = field(default_factory=tuple)
    export_path: str = ""
    sample_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alive": bool(self.alive),
            "audits_attempted": int(self.audits_attempted),
            "audits_exported": int(self.audits_exported),
            "blocked_reasons": list(self.blocked_reasons),
            "enforce_allowed": bool(self.enforce_allowed),
            "export_path": self.export_path,
            "mode": self.mode,
            "productive": bool(self.productive),
            "prover_confirmed": bool(self.prover_confirmed),
            "sample_id": self.sample_id,
            "target_scope_matched": bool(self.target_scope_matched),
            "target_scopes": list(self.target_scopes),
            "todos_seeded": int(self.todos_seeded),
        }


@dataclass(frozen=True)
class ModalAutoencoderLoopConfig:
    """Configuration for the legal modal autoencoder/Codex loop."""

    codec_config: ModalLogicCodecConfig = field(default_factory=ModalLogicCodecConfig)
    gate_config: CodexCallGateConfig = field(default_factory=CodexCallGateConfig)
    evaluate_provers: bool = True
    import_frame_logic_graph: bool = True
    check_external_prover_router: bool = False
    legal_ir_bridge_names: Sequence[str] = DEFAULT_LEGAL_IR_BRIDGE_NAMES
    allow_llm_repair: bool = False
    apply_llm_frame_logic_patches: bool = False
    llm_provider: str = DEFAULT_CODEX_PROVIDER
    llm_model: str = DEFAULT_CODEX_MODEL
    llm_timeout: float = 900.0
    llm_max_new_tokens: int = 2048
    llm_temperature: float = 0.0
    codex_cache_path: Optional[str] = None
    leanstral_config: LeanstralConfig = field(default_factory=LeanstralConfig)
    introspection_mode: str = "off"
    max_audits_per_cycle: int = 0
    max_todos_per_cycle: int = 0
    target_scope_filters: Sequence[str] = field(default_factory=tuple)
    require_prover_confirmation: bool = True
    introspection_export_path: Optional[str] = None

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
            "legal_ir_bridge_names": list(_normalise_bridge_names(self.legal_ir_bridge_names)),
            "llm_max_new_tokens": self.llm_max_new_tokens,
            "llm_model": self.llm_model,
            "llm_provider": self.llm_provider,
            "llm_temperature": self.llm_temperature,
            "llm_timeout": self.llm_timeout,
            "leanstral_config": self.leanstral_config.to_dict(),
            "introspection_export_path": self.introspection_export_path,
            "introspection_mode": _normalise_introspection_mode(self.introspection_mode),
            "max_audits_per_cycle": max(0, int(self.max_audits_per_cycle or 0)),
            "max_todos_per_cycle": max(0, int(self.max_todos_per_cycle or 0)),
            "require_prover_confirmation": bool(self.require_prover_confirmation),
            "target_scope_filters": list(_normalise_scope_filters(self.target_scope_filters)),
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
    leanstral_shadow: Optional[LeanstralShadowResult] = None
    introspection: Optional[Dict[str, Any]] = None
    introspection_summary: ModalIntrospectionSummary = field(
        default_factory=ModalIntrospectionSummary
    )
    cache_counters: Dict[str, int] = field(default_factory=dict)
    phase_timings: Dict[str, float] = field(default_factory=dict)
    state_to_compiler_patch_lag: Dict[str, int] = field(default_factory=dict)
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
            "leanstral_shadow": self.leanstral_shadow.to_dict()
            if self.leanstral_shadow
            else None,
            "introspection": self.introspection,
            "introspection_summary": self.introspection_summary.to_dict(),
            "cache_counters": dict(sorted(self.cache_counters.items())),
            "metadata": dict(sorted(self.metadata.items())),
            "phase_timings": dict(sorted(self.phase_timings.items())),
            "prover_signal": self.prover_signal.to_dict() if self.prover_signal else None,
            "sample": self.sample.to_dict(),
            "source_text": self.source_text,
            "state_to_compiler_patch_lag": dict(
                sorted(self.state_to_compiler_patch_lag.items())
            ),
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
        leanstral_generate: Optional[LLMGenerateFn] = None,
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
        self.leanstral_runner = LeanstralShadowRunner(
            self.config.leanstral_config,
            llm_generate=leanstral_generate,
        )

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
        _cycle_budget: Optional[Dict[str, int]] = None,
    ) -> ModalAutoencoderLoopResult:
        """Run one cheap-first legal text -> modal IR -> validation pass."""

        phase_timings: Dict[str, float] = {}

        def mark_timing(name: str, started: float) -> None:
            phase_timings[name] = round(phase_timings.get(name, 0.0) + time.time() - started, 6)

        started = time.time()
        codec_result = self.codec.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
        )
        mark_timing("codec", started)
        started = time.time()
        sample = _sample_from_codec_result(
            codec_result,
            title=title,
            section=section or document_id or codec_result.modal_ir.document_id,
            embedding_vector=source_embedding,
        )
        mark_timing("sample", started)
        started = time.time()
        graph_report = self._import_graph(sample.modal_ir)
        mark_timing("graph_import", started)
        started = time.time()
        prover_signal = self._evaluate_provers(sample)
        mark_timing("prover", started)
        started = time.time()
        available_external_provers = self._external_prover_inventory()
        mark_timing("external_prover_inventory", started)
        legal_ir_bridge_names = _normalise_bridge_names(self.config.legal_ir_bridge_names)
        started = time.time()
        decision = self.autoencoder.codex_call_decision(
            sample,
            config=self.config.gate_config,
            cache=self.cache,
            prover_signal=prover_signal,
            legal_ir_bridge_names=legal_ir_bridge_names,
        )
        mark_timing("codex_gate", started)

        llm_called = False
        llm_response = ""
        llm_patch: Optional[Dict[str, Any]] = None
        llm_patch_validation: Optional[FrameLogicPatchValidation] = None
        repaired_modal_ir: Optional[ModalIRDocument] = None
        leanstral_shadow: Optional[LeanstralShadowResult] = None
        leanstral_shadow_error = ""
        should_call_llm = (
            self.config.allow_llm_repair
            if allow_llm_repair is None
            else bool(allow_llm_repair)
        )

        if decision.should_call_codex and should_call_llm:
            started = time.time()
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
            mark_timing("llm_repair", started)
        elif not decision.reasons:
            started = time.time()
            self.cache.record_local_success(decision)
            self.save_cache()
            mark_timing("cache_save", started)

        if self.config.leanstral_config.enabled:
            started = time.time()
            try:
                leanstral_shadow = self.leanstral_runner.run(
                    sample,
                    autoencoder=self.autoencoder,
                    prover_signal=prover_signal,
                )
            except Exception as exc:
                # The Leanstral lane is intentionally shadow-only. A provider
                # issue must not interrupt deterministic compilation or Codex.
                leanstral_shadow_error = f"{exc.__class__.__name__}: {exc}"
            mark_timing("leanstral_shadow", started)

        started = time.time()
        introspection, introspection_summary = self._run_introspection(
            sample,
            prover_signal=prover_signal,
            leanstral_shadow=leanstral_shadow,
            cycle_budget=_cycle_budget,
        )
        mark_timing("introspection", started)

        accepted = _accepted(
            decision,
            graph_report=graph_report,
            prover_signal=prover_signal,
            require_provers=self.config.evaluate_provers,
        )
        if introspection_summary.mode == "enforce" and not introspection_summary.enforce_allowed:
            accepted = False
        cache_counters = self._cache_counters()
        state_lag = _state_to_compiler_patch_lag(
            state_update_count=_state_update_count(self.autoencoder),
            compiler_patch_count=(
                llm_patch_validation.accepted_count
                if llm_patch_validation is not None
                else 0
            ),
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
            leanstral_shadow=leanstral_shadow,
            introspection=introspection,
            introspection_summary=introspection_summary,
            cache_counters=cache_counters,
            phase_timings=phase_timings,
            state_to_compiler_patch_lag=state_lag,
            metadata={
                "llm_model": self.config.llm_model if llm_called else "",
                "llm_provider": self.config.llm_provider if llm_called else "",
                "loop": "legal_modal_autoencoder_loop_v1",
                "codex_cache_path": str(self.cache_path) if self.cache_path else "",
                "legal_ir_bridge_names": list(legal_ir_bridge_names),
                "leanstral_shadow_error": leanstral_shadow_error,
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
        cycle_budget = {
            "audits": max(0, int(self.config.max_audits_per_cycle or 0)),
            "todos": max(0, int(self.config.max_todos_per_cycle or 0)),
            "used_audits": 0,
            "used_todos": 0,
        }
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
                    _cycle_budget=cycle_budget,
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

    def _run_introspection(
        self,
        sample: LegalSample,
        *,
        prover_signal: Optional[ProverCompilationSignal],
        leanstral_shadow: Optional[LeanstralShadowResult] = None,
        cycle_budget: Optional[Dict[str, int]] = None,
    ) -> tuple[Optional[Dict[str, Any]], ModalIntrospectionSummary]:
        mode = _normalise_introspection_mode(self.config.introspection_mode)
        target_scopes = _normalise_scope_filters(self.config.target_scope_filters)
        if mode == "off":
            return None, ModalIntrospectionSummary(mode="off", sample_id=sample.sample_id)

        blocked: list[str] = []
        scopes = _sample_target_scopes(sample)
        target_scope_matched = not target_scopes or bool(set(target_scopes) & scopes)
        if not target_scope_matched:
            blocked.append("target_scope_filtered")

        prover_confirmed = True
        if self.config.require_prover_confirmation:
            prover_confirmed = bool(prover_signal is not None and prover_signal.compiles)
            if not prover_confirmed:
                blocked.append("prover_confirmation_required")

        if cycle_budget is None:
            cycle_budget = {
                "audits": max(0, int(self.config.max_audits_per_cycle or 0)),
                "todos": max(0, int(self.config.max_todos_per_cycle or 0)),
                "used_audits": 0,
                "used_todos": 0,
            }
        audits_allowed = _consume_cycle_budget(cycle_budget, "audits")
        if not audits_allowed:
            blocked.append("max_audits_per_cycle_exhausted")

        introspection: Optional[Dict[str, Any]] = None
        audits_attempted = 0
        audits_exported = 0
        todos_seeded = 0
        export_path = ""
        if target_scope_matched and prover_confirmed and audits_allowed:
            audits_attempted = 1
            introspection = self.autoencoder.introspect_sample(sample).to_dict()
            if mode in {"export", "shadow", "seed", "enforce"}:
                export_path = self._export_introspection(
                    sample,
                    introspection,
                    leanstral_shadow=leanstral_shadow,
                )
                audits_exported = 1 if export_path else 0
            if mode in {"seed", "enforce"} and _consume_cycle_budget(cycle_budget, "todos"):
                todos_seeded = 1
            elif mode in {"seed", "enforce"}:
                blocked.append("max_todos_per_cycle_exhausted")

        enforce_allowed = True
        if mode == "enforce":
            enforce_allowed = bool(
                introspection is not None
                and target_scope_matched
                and prover_confirmed
                and audits_allowed
            )
        productive = bool(audits_attempted or todos_seeded or audits_exported)
        return introspection, ModalIntrospectionSummary(
            mode=mode,
            alive=True,
            productive=productive,
            audits_attempted=audits_attempted,
            audits_exported=audits_exported,
            todos_seeded=todos_seeded,
            target_scope_matched=target_scope_matched,
            prover_confirmed=prover_confirmed,
            enforce_allowed=enforce_allowed,
            blocked_reasons=tuple(dict.fromkeys(blocked)),
            target_scopes=tuple(sorted(scopes)),
            export_path=export_path,
            sample_id=sample.sample_id,
        )

    def _export_introspection(
        self,
        sample: LegalSample,
        introspection: Mapping[str, Any],
        *,
        leanstral_shadow: Optional[LeanstralShadowResult] = None,
    ) -> str:
        raw_path = str(self.config.introspection_export_path or "").strip()
        if not raw_path:
            return ""
        target = Path(raw_path).expanduser()
        if target.suffix.lower() != ".json":
            target = target / f"{sample.sample_id}.introspection.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        leanstral_guidance = (
            leanstral_shadow.guidance.to_dict()
            if leanstral_shadow is not None and leanstral_shadow.guidance is not None
            else None
        )
        target.write_text(
            json.dumps(
                {
                    "introspection": dict(introspection),
                    "leanstral_guidance": leanstral_guidance,
                    "sample_id": sample.sample_id,
                    "schema_version": "legal-modal-autoencoder-introspection-loop-v1",
                },
                ensure_ascii=True,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return str(target)

    def _cache_counters(self) -> Dict[str, int]:
        return {
            "autoencoder_legal_ir_loss_target_cache_entries": len(
                getattr(self.autoencoder, "_legal_ir_loss_target_cache", {}) or {}
            ),
            "autoencoder_legal_ir_view_target_cache_entries": len(
                getattr(self.autoencoder, "_legal_ir_view_target_cache", {}) or {}
            ),
            "autoencoder_sample_feature_cache_entries": len(
                getattr(self.autoencoder, "_sample_feature_cache", {}) or {}
            ),
            "codex_call_count": int(self.cache.codex_call_count),
            "codex_feature_signature_hash_count": len(self.cache.codex_feature_signature_hashes),
            "codex_text_hash_count": len(self.cache.codex_text_hashes),
            "local_success_feature_signature_hash_count": len(
                self.cache.local_success_feature_signature_hashes
            ),
        }


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


def _normalise_bridge_names(bridge_names: Sequence[str] | str) -> tuple[str, ...]:
    if isinstance(bridge_names, str):
        raw_names: Iterable[str] = bridge_names.split(",")
    else:
        raw_names = bridge_names
    return tuple(
        dict.fromkeys(
            str(name).strip()
            for name in raw_names
            if str(name).strip() and str(name).strip().lower() not in {"none", "off", "false"}
        )
    )


def _normalise_introspection_mode(mode: str) -> str:
    normalized = str(mode or "off").strip().lower()
    if normalized in {"0", "false", "no", "none", "disabled"}:
        return "off"
    if normalized not in MODAL_INTROSPECTION_MODES:
        return "off"
    return normalized


def _normalise_scope_filters(scopes: Sequence[str] | str) -> tuple[str, ...]:
    raw_values: Iterable[str]
    if isinstance(scopes, str):
        raw_values = scopes.split(",")
    else:
        raw_values = scopes
    return tuple(
        dict.fromkeys(
            str(value).strip()
            for value in raw_values
            if str(value).strip()
            and str(value).strip().lower() not in {"all", "none", "off", "false"}
        )
    )


def _sample_target_scopes(sample: LegalSample) -> set[str]:
    scopes = {
        str(getattr(sample, "source", "") or ""),
        str(getattr(sample, "title", "") or ""),
        str(getattr(sample, "section", "") or ""),
        str(getattr(sample, "selected_frame", "") or ""),
    }
    modal_ir = getattr(sample, "modal_ir", None)
    if modal_ir is not None:
        scopes.add(str(getattr(modal_ir, "source", "") or ""))
        for formula in getattr(modal_ir, "formulas", ()) or ():
            operator = getattr(formula, "operator", None)
            scopes.add(str(getattr(operator, "family", "") or ""))
            scopes.add(f"modal.{str(getattr(operator, 'family', '') or '')}")
    return {scope for scope in scopes if scope}


def _consume_cycle_budget(cycle_budget: Optional[Dict[str, int]], key: str) -> bool:
    if cycle_budget is None:
        return True
    limit = max(0, int(cycle_budget.get(key, 0) or 0))
    if limit <= 0:
        return False
    used_key = f"used_{key}"
    used = max(0, int(cycle_budget.get(used_key, 0) or 0))
    if used >= limit:
        return False
    cycle_budget[used_key] = used + 1
    return True


def _state_update_count(autoencoder: AdaptiveModalAutoencoder) -> int:
    state = getattr(autoencoder, "state", None)
    if state is None:
        return 0
    telemetry = state.telemetry() if hasattr(state, "telemetry") else {}
    return max(
        0,
        int(telemetry.get("applied_todo_count", 0) or 0)
        + int(telemetry.get("generalizable_entry_count", 0) or 0),
    )


def _state_to_compiler_patch_lag(
    *,
    state_update_count: int,
    compiler_patch_count: int,
) -> Dict[str, int]:
    state_updates = max(0, int(state_update_count or 0))
    compiler_patches = max(0, int(compiler_patch_count or 0))
    return {
        "compiler_patch_count": compiler_patches,
        "lag": max(0, state_updates - compiler_patches),
        "state_update_count": state_updates,
    }


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
    "DEFAULT_LEGAL_IR_BRIDGE_NAMES",
    "MODAL_INTROSPECTION_MODES",
    "ModalIntrospectionSummary",
    "ModalAutoencoderLoopConfig",
    "ModalAutoencoderLoopResult",
    "validate_frame_logic_patch",
]
