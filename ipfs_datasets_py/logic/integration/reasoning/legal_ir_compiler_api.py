"""Public LegalIR compiler API surfaces.

This module is the stable boundary for daemon-free compiler use.  It exposes
JSON-ready compile, decompile, validate, diff, explain, benchmark, artifact
export, and LSP diagnostic helpers while keeping production defaults
deterministic and proof-aware.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final

from .legal_ir_diagnostics import (
    LegalIRDiagnostic,
    LegalIRDiagnosticCode,
    LegalIRDiagnosticFamily,
    LegalIRDiagnosticReport,
    LegalIRDiagnosticSeverity,
    LegalIRDiagnosticSourceMap,
    LegalIRDiagnosticsBuilder,
    build_legal_ir_diagnostic_report,
)
from .legal_ir_incremental_compiler import (
    IncrementalPassCallable,
    LegalIRIncrementalCompilationSnapshot,
    LegalIRIncrementalCompileResult,
    compile_legal_ir_incremental,
)
from .legal_ir_pass_manager import (
    LegalIRInvalidationRule,
    LegalIRPassKind,
    LegalIRPassSpec,
    LegalIRProtectedMutationJustification,
)
from .legal_ir_proof_carrying_artifacts import (
    LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION,
    LegalIRProofCarryingArtifact,
    LegalIRProofVerificationPolicy,
    build_legal_ir_proof_carrying_artifact,
    validate_legal_ir_proof_carrying_artifact,
)
from .legal_ir_semantic_diff import compute_legal_ir_semantic_diff
from .legal_ir_source_maps import (
    LegalIRSourceMap,
    LegalIRSourceMapBuilder,
    LegalIRTransformationKind,
    validate_legal_ir_source_map,
)


LEGAL_IR_COMPILER_API_SCHEMA_VERSION: Final = "legal-ir-compiler-api-v1"
LEGAL_IR_COMPILER_ARTIFACT_SCHEMA_VERSION: Final = "legal-ir-compiler-artifact-v1"


class LegalIRCompilerExitCode(int, Enum):
    """Deterministic process/API exit codes for compiler surfaces."""

    OK = 0
    DIAGNOSTIC_ERROR = 1
    USAGE_ERROR = 2
    INTERNAL_ERROR = 70


class LegalIRCompilerOperation(str, Enum):
    """Stable public compiler operations."""

    COMPILE = "compile"
    DECOMPILE = "decompile"
    VALIDATE = "validate"
    DIFF = "diff"
    EXPLAIN = "explain"
    BENCHMARK = "benchmark"
    EXPORT_ARTIFACT = "export_artifact"


@dataclass(frozen=True)
class LegalIRCompilerOptions:
    """Operational flags shared by CLI, API, and LSP callers."""

    learned_guidance: bool = False
    learned_guidance_artifact: Mapping[str, Any] | None = None
    deterministic: bool = True
    proof_aware: bool = True
    include_lsp_diagnostics: bool = False
    fail_on_warnings: bool = False
    max_workers: int = 1
    resource_limits: Mapping[str, int] = field(default_factory=lambda: {"cpu": 1})
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deterministic": bool(self.deterministic),
            "fail_on_warnings": bool(self.fail_on_warnings),
            "include_lsp_diagnostics": bool(self.include_lsp_diagnostics),
            "learned_guidance": bool(self.learned_guidance),
            "learned_guidance_artifact": _json_ready(self.learned_guidance_artifact),
            "max_workers": int(self.max_workers or 1),
            "metadata": _json_ready(self.metadata),
            "proof_aware": bool(self.proof_aware),
            "resource_limits": {str(key): int(value) for key, value in sorted(self.resource_limits.items())},
        }


@dataclass(frozen=True)
class LegalIRCompilerResult:
    """JSON-ready result returned by every public compiler operation."""

    operation: str
    status: str
    exit_code: int
    payload: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: LegalIRDiagnosticReport = field(
        default_factory=lambda: LegalIRDiagnosticReport(report_id="", diagnostics=())
    )
    lsp_diagnostics: tuple[Mapping[str, Any], ...] = ()
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None
    options: LegalIRCompilerOptions = field(default_factory=LegalIRCompilerOptions)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    result_id: str = ""
    schema_version: str = LEGAL_IR_COMPILER_API_SCHEMA_VERSION

    def __post_init__(self) -> None:
        diagnostics = (
            self.diagnostics
            if isinstance(self.diagnostics, LegalIRDiagnosticReport)
            else LegalIRDiagnosticReport.from_dict(_mapping(self.diagnostics))
        )
        source_map = self.source_map
        if source_map is not None and not isinstance(source_map, LegalIRSourceMap):
            source_map = LegalIRSourceMap.from_dict(_mapping(source_map))
        result_id = self.result_id or "lir-compiler-result-" + _stable_hash(
            {
                "diagnostics": diagnostics.to_dict(),
                "operation": self.operation,
                "payload": self.payload,
                "schema_version": self.schema_version,
                "status": self.status,
            }
        )[:24]
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "source_map", source_map)
        object.__setattr__(self, "lsp_diagnostics", tuple(dict(item) for item in self.lsp_diagnostics))
        object.__setattr__(self, "metadata", _mapping(self.metadata))
        object.__setattr__(self, "result_id", result_id)

    @property
    def successful(self) -> bool:
        return int(self.exit_code) == LegalIRCompilerExitCode.OK.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": self.diagnostics.to_dict(),
            "exit_code": int(self.exit_code),
            "lsp_diagnostics": [_json_ready(item) for item in self.lsp_diagnostics],
            "metadata": _json_ready(self.metadata),
            "operation": self.operation,
            "options": self.options.to_dict(),
            "payload": _json_ready(self.payload),
            "result_id": self.result_id,
            "schema_version": self.schema_version,
            "source_map": self.source_map.to_dict() if isinstance(self.source_map, LegalIRSourceMap) else None,
            "status": self.status,
            "successful": self.successful,
        }


class LegalIRCompilerAPI:
    """Stable in-process API for LegalIR compiler operations."""

    def __init__(self, options: LegalIRCompilerOptions | Mapping[str, Any] | None = None) -> None:
        self.options = _options(options)

    def compile(
        self,
        source: str | Mapping[str, Any],
        *,
        passes: Sequence[LegalIRPassSpec | Mapping[str, Any]] | None = None,
        pass_functions: Mapping[str, IncrementalPassCallable] | None = None,
        previous: LegalIRIncrementalCompilationSnapshot | Mapping[str, Any] | None = None,
        sources: Mapping[str, Any] | Sequence[Any] | None = None,
        citations: Mapping[str, Any] | Sequence[Any] | None = None,
        symbols: Mapping[str, Any] | Sequence[Any] | None = None,
        temporal: Mapping[str, Any] | Sequence[Any] | None = None,
    ) -> LegalIRCompilerResult:
        initial = _initial_state(source)
        resolved_passes = tuple(passes or default_legal_ir_api_passes())
        resolved_functions = {**_default_pass_functions(), **dict(pass_functions or {})}
        if passes is not None and pass_functions is None:
            resolved_functions = {}
        if self.options.learned_guidance:
            initial["learned_guidance"] = _learned_guidance_state(
                active=True,
                artifact=self.options.learned_guidance_artifact,
            )
        else:
            initial.setdefault("learned_guidance", _learned_guidance_state(active=False))

        try:
            compile_result = compile_legal_ir_incremental(
                initial,
                resolved_functions,
                passes=resolved_passes,
                previous=previous,
                sources=sources,
                citations=citations,
                symbols=symbols,
                temporal=temporal,
                max_workers=self.options.max_workers,
                resource_limits=self.options.resource_limits,
            )
        except Exception as exc:  # noqa: BLE001 - public API normalizes failures
            diagnostics = _exception_report(
                LegalIRCompilerOperation.COMPILE.value,
                exc,
                source_map=_source_map_from_payload(initial),
            )
            return _result(
                LegalIRCompilerOperation.COMPILE,
                {},
                diagnostics,
                options=self.options,
                source_map=_source_map_from_payload(initial),
                status="failed",
            )

        payload = {
            "compile": compile_result.to_dict(),
            "compiled": _json_ready(compile_result.output_state),
            "deterministic_output_order": list(compile_result.deterministic_output_order),
            "incremental_snapshot": compile_result.snapshot.to_dict(),
            "learned_guidance": initial.get("learned_guidance"),
            "proof_aware": bool(self.options.proof_aware),
            "schema_version": LEGAL_IR_COMPILER_ARTIFACT_SCHEMA_VERSION,
        }
        source_map = _source_map_from_payload(compile_result.output_state)
        diagnostics = _compile_diagnostic_report(compile_result, source_map=source_map)
        return _result(
            LegalIRCompilerOperation.COMPILE,
            payload,
            diagnostics,
            options=self.options,
            source_map=source_map,
            metadata={"compile_digest": compile_result.snapshot.compile_digest},
        )

    def decompile(self, artifact: Mapping[str, Any] | str) -> LegalIRCompilerResult:
        payload = _artifact_payload(artifact)
        compiled = _compiled_payload(payload)
        source_map = _source_map_from_payload(compiled) or _source_map_from_payload(payload)
        statements = _decompiled_statements(compiled)
        text = "\n".join(statements)
        losses: list[dict[str, Any]] = []
        for index, obligation in enumerate(_sequence(compiled.get("obligations") or compiled.get("proof_obligations"))):
            row = _mapping(obligation)
            if not str(row.get("statement") or "").strip():
                losses.append(
                    {
                        "failure_id": f"decompile-loss-{index}",
                        "field_path": f"obligations.{index}.statement",
                        "formula_id": str(row.get("formula_id") or row.get("obligation_id") or ""),
                        "reason": "missing_statement",
                    }
                )
        diagnostics = build_legal_ir_diagnostic_report(
            {"decompiler_losses": losses},
            artifact_id=str(compiled.get("artifact_id") or ""),
            source_map=source_map,
        )
        return _result(
            LegalIRCompilerOperation.DECOMPILE,
            {
                "decompiled_text": text,
                "lossless": not losses,
                "schema_version": LEGAL_IR_COMPILER_ARTIFACT_SCHEMA_VERSION,
                "statements": statements,
            },
            diagnostics,
            options=self.options,
            source_map=source_map,
        )

    def validate(self, artifact: Mapping[str, Any] | str) -> LegalIRCompilerResult:
        payload = _artifact_payload(artifact)
        compiled = _compiled_payload(payload)
        source_map = _source_map_from_payload(compiled) or _source_map_from_payload(payload)
        diagnostic_inputs: list[Any] = [compiled]
        embedded_report = _mapping(payload.get("diagnostics"))
        if str(embedded_report.get("schema_version") or ""):
            diagnostic_inputs.append(embedded_report)
        elif payload is not compiled:
            diagnostic_inputs.append(payload)
        diagnostics = build_legal_ir_diagnostic_report(
            *diagnostic_inputs,
            artifact_id=str(compiled.get("artifact_id") or payload.get("artifact_id") or ""),
            source_map=source_map,
        )
        validation_payload: dict[str, Any] = {
            "diagnostics_valid": diagnostics.valid,
            "proof_aware": bool(self.options.proof_aware),
            "schema_version": LEGAL_IR_COMPILER_ARTIFACT_SCHEMA_VERSION,
        }
        if source_map is not None:
            source_map_validation = validate_legal_ir_source_map(source_map)
            validation_payload["source_map_validation"] = source_map_validation.to_dict()
            diagnostics = _merge_reports(
                diagnostics,
                _source_map_validation_diagnostics(source_map_validation, source_map=source_map),
            )
        if self.options.proof_aware and _is_proof_carrying_artifact(payload):
            proof_validation = validate_legal_ir_proof_carrying_artifact(payload)
            validation_payload["proof_artifact_validation"] = proof_validation.to_dict()
            proof_report = _proof_validation_diagnostics(proof_validation, source_map=source_map)
            diagnostics = _merge_reports(diagnostics, proof_report)
        validation_payload["valid"] = diagnostics.valid
        return _result(
            LegalIRCompilerOperation.VALIDATE,
            validation_payload,
            diagnostics,
            options=self.options,
            source_map=source_map,
        )

    def diff(
        self,
        before: Mapping[str, Any] | str,
        after: Mapping[str, Any] | str,
        *,
        compiler_impact_evidence: Any = None,
        include_codex_todos: bool = True,
    ) -> LegalIRCompilerResult:
        before_payload = _compiled_payload(_artifact_payload(before))
        after_payload = _compiled_payload(_artifact_payload(after))
        report = compute_legal_ir_semantic_diff(
            before_payload,
            after_payload,
            compiler_impact_evidence=compiler_impact_evidence,
            include_codex_todos=include_codex_todos,
            metadata={"source": "legal_ir_compiler_api"},
        )
        diagnostics = LegalIRDiagnosticReport(report_id="", diagnostics=())
        return _result(
            LegalIRCompilerOperation.DIFF,
            report.to_dict(),
            diagnostics,
            options=self.options,
            status="changed" if report.changed else "ok",
        )

    def explain(self, artifact: Mapping[str, Any] | str) -> LegalIRCompilerResult:
        validation = self.validate(artifact)
        payload = {
            "diagnostic_report": validation.diagnostics.to_dict(),
            "explanation_traces": [trace.to_dict() for trace in validation.diagnostics.traces],
            "schema_version": LEGAL_IR_COMPILER_ARTIFACT_SCHEMA_VERSION,
        }
        return _result(
            LegalIRCompilerOperation.EXPLAIN,
            payload,
            validation.diagnostics,
            options=self.options,
            source_map=validation.source_map,
        )

    def benchmark(
        self,
        source: str | Mapping[str, Any],
        *,
        iterations: int = 3,
    ) -> LegalIRCompilerResult:
        count = max(1, int(iterations or 1))
        timings: list[float] = []
        results: list[LegalIRCompilerResult] = []
        previous: Mapping[str, Any] | None = None
        for _ in range(count):
            start = time.perf_counter()
            result = self.compile(source, previous=previous)
            timings.append(time.perf_counter() - start)
            previous = _mapping(result.payload.get("incremental_snapshot"))
            results.append(result)
        diagnostics = _merge_many_reports([result.diagnostics for result in results])
        payload = {
            "iterations": count,
            "mean_wall_time_seconds": _stable_float(sum(timings) / len(timings)),
            "min_wall_time_seconds": _stable_float(min(timings)),
            "max_wall_time_seconds": _stable_float(max(timings)),
            "last_compile_digest": str(results[-1].metadata.get("compile_digest") or ""),
            "last_compile_metrics": _mapping(
                _mapping(results[-1].payload.get("compile")).get("metrics")
            ),
            "schema_version": LEGAL_IR_COMPILER_ARTIFACT_SCHEMA_VERSION,
        }
        return _result(
            LegalIRCompilerOperation.BENCHMARK,
            payload,
            diagnostics,
            options=self.options,
            source_map=results[-1].source_map,
        )

    def export_artifact(
        self,
        artifact: Mapping[str, Any] | str,
        *,
        verification_policy: LegalIRProofVerificationPolicy | Mapping[str, Any] | None = None,
    ) -> LegalIRCompilerResult:
        payload = _artifact_payload(artifact)
        compiled = _compiled_payload(payload)
        source_map = _source_map_from_payload(compiled) or _source_map_from_payload(payload)
        if _is_proof_carrying_artifact(payload):
            proof_artifact = LegalIRProofCarryingArtifact.from_dict(payload)
            proof_validation = validate_legal_ir_proof_carrying_artifact(
                proof_artifact,
                policy=verification_policy,
            )
            diagnostics = _proof_validation_diagnostics(proof_validation, source_map=source_map)
            return _result(
                LegalIRCompilerOperation.EXPORT_ARTIFACT,
                {
                    "artifact": proof_artifact.to_dict(),
                    "artifact_kind": "proof_carrying",
                    "proof_artifact_validation": proof_validation.to_dict(),
                },
                diagnostics,
                options=self.options,
                source_map=source_map,
            )

        if _can_build_proof_artifact(compiled):
            proof_artifact = build_legal_ir_proof_carrying_artifact(
                legal_ir_outputs=compiled.get("legal_ir_outputs"),
                proof_obligations=_sequence(compiled.get("proof_obligations")),
                hammer_guidance_artifacts=_sequence(compiled.get("hammer_guidance_artifacts")),
                translation_records=_sequence(compiled.get("translation_records")),
                reconstruction_receipts=_sequence(compiled.get("reconstruction_receipts")),
                route_results=_sequence(compiled.get("route_results")),
                unsupported_diagnostics=_sequence(compiled.get("unsupported_diagnostics")),
                source_map=source_map,
                build_manifest=_mapping(compiled.get("build_manifest")) or None,
                verification_policy=verification_policy,
                metadata={"exported_by": "legal_ir_compiler_api"},
            )
            proof_validation = validate_legal_ir_proof_carrying_artifact(proof_artifact)
            diagnostics = _proof_validation_diagnostics(proof_validation, source_map=source_map)
            return _result(
                LegalIRCompilerOperation.EXPORT_ARTIFACT,
                {
                    "artifact": proof_artifact.to_dict(),
                    "artifact_kind": "proof_carrying",
                    "proof_artifact_validation": proof_validation.to_dict(),
                },
                diagnostics,
                options=self.options,
                source_map=source_map,
            )

        diagnostics = _proof_readiness_report(compiled, source_map=source_map)
        envelope = {
            "artifact": {
                "compiled": _json_ready(compiled),
                "diagnostic_report": diagnostics.to_dict(),
                "proof_ready": False,
                "schema_version": LEGAL_IR_COMPILER_ARTIFACT_SCHEMA_VERSION,
                "source_map": source_map.to_dict() if source_map else None,
            },
            "artifact_kind": "compiler_artifact",
        }
        return _result(
            LegalIRCompilerOperation.EXPORT_ARTIFACT,
            envelope,
            diagnostics,
            options=self.options,
            source_map=source_map,
        )


def default_legal_ir_api_passes() -> tuple[LegalIRPassSpec, ...]:
    """Return the compact default pass list used by daemon-free API compiles."""

    source_map_justification = LegalIRProtectedMutationJustification(
        field_path="source_map",
        proof_obligation_ids=("legal-ir-api-source-map-preservation",),
        reason="Public API compiles must carry source-map provenance.",
    )
    proof_obligation_justification = LegalIRProtectedMutationJustification(
        field_path="proof_obligations",
        proof_obligation_ids=("legal-ir-api-proof-obligation-surface",),
        reason="Public API lowering emits proof obligations for downstream validation.",
    )
    return (
        LegalIRPassSpec(
            pass_id="legal_ir.api.ingest",
            title="Ingest LegalIR API source",
            kind=LegalIRPassKind.COMPILER,
            order=10,
            declared_inputs=("raw_document", "source"),
            declared_outputs=("normalized_document", "source_map"),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("obligations", "legal_ir_outputs", "decompiled_text"),
                    when_outputs_change=("normalized_document", "source_map"),
                    reason="Normalized source feeds all public API projections.",
                ),
            ),
            protected_mutation_justifications=(source_map_justification,),
            metadata={"estimated_seconds": 0.001, "work_units": 1.0},
        ),
        LegalIRPassSpec(
            pass_id="legal_ir.api.lower",
            title="Lower daemon-free LegalIR views",
            kind=LegalIRPassKind.COMPILER,
            order=20,
            declared_inputs=("normalized_document", "source_map", "obligations"),
            declared_outputs=("obligations", "proof_obligations", "legal_ir_outputs"),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("diagnostic_report", "decompiled_text"),
                    when_outputs_change=("obligations", "legal_ir_outputs"),
                    reason="Lowered obligations feed diagnostics and decompilation.",
                ),
            ),
            protected_mutation_justifications=(proof_obligation_justification,),
            metadata={"estimated_seconds": 0.001, "work_units": 2.0},
        ),
        LegalIRPassSpec(
            pass_id="legal_ir.api.explain",
            title="Collect API diagnostics",
            kind=LegalIRPassKind.DIAGNOSTIC,
            order=30,
            declared_inputs=("legal_ir_outputs", "source_map"),
            declared_outputs=("diagnostic_report", "decompiled_text"),
            metadata={"estimated_seconds": 0.001, "work_units": 1.0},
        ),
    )


def compile_legal_ir(
    source: str | Mapping[str, Any],
    *,
    options: LegalIRCompilerOptions | Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> LegalIRCompilerResult:
    return LegalIRCompilerAPI(options).compile(source, **kwargs)


def decompile_legal_ir(
    artifact: Mapping[str, Any] | str,
    *,
    options: LegalIRCompilerOptions | Mapping[str, Any] | None = None,
) -> LegalIRCompilerResult:
    return LegalIRCompilerAPI(options).decompile(artifact)


def validate_legal_ir(
    artifact: Mapping[str, Any] | str,
    *,
    options: LegalIRCompilerOptions | Mapping[str, Any] | None = None,
) -> LegalIRCompilerResult:
    return LegalIRCompilerAPI(options).validate(artifact)


def diff_legal_ir(
    before: Mapping[str, Any] | str,
    after: Mapping[str, Any] | str,
    *,
    options: LegalIRCompilerOptions | Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> LegalIRCompilerResult:
    return LegalIRCompilerAPI(options).diff(before, after, **kwargs)


def explain_legal_ir(
    artifact: Mapping[str, Any] | str,
    *,
    options: LegalIRCompilerOptions | Mapping[str, Any] | None = None,
) -> LegalIRCompilerResult:
    return LegalIRCompilerAPI(options).explain(artifact)


def benchmark_legal_ir(
    source: str | Mapping[str, Any],
    *,
    iterations: int = 3,
    options: LegalIRCompilerOptions | Mapping[str, Any] | None = None,
) -> LegalIRCompilerResult:
    return LegalIRCompilerAPI(options).benchmark(source, iterations=iterations)


def export_legal_ir_artifact(
    artifact: Mapping[str, Any] | str,
    *,
    options: LegalIRCompilerOptions | Mapping[str, Any] | None = None,
    verification_policy: LegalIRProofVerificationPolicy | Mapping[str, Any] | None = None,
) -> LegalIRCompilerResult:
    return LegalIRCompilerAPI(options).export_artifact(
        artifact,
        verification_policy=verification_policy,
    )


def legal_ir_lsp_diagnostics(
    diagnostics: LegalIRDiagnosticReport | Mapping[str, Any] | LegalIRCompilerResult,
) -> list[dict[str, Any]]:
    """Convert LegalIR diagnostics to LSP ``Diagnostic`` objects."""

    if isinstance(diagnostics, LegalIRCompilerResult):
        report = diagnostics.diagnostics
    elif isinstance(diagnostics, LegalIRDiagnosticReport):
        report = diagnostics
    else:
        report = LegalIRDiagnosticReport.from_dict(_mapping(diagnostics))
    return [_lsp_diagnostic(item) for item in report.diagnostics]


def read_legal_ir_json(path: str | Path) -> Any:
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text)


def write_legal_ir_json(path: str | Path, payload: Any, *, pretty: bool = True) -> None:
    Path(path).write_text(
        json.dumps(
            _json_ready(payload),
            allow_nan=False,
            ensure_ascii=True,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _default_pass_functions() -> Mapping[str, IncrementalPassCallable]:
    return {
        "legal_ir.api.ingest": _pass_ingest,
        "legal_ir.api.lower": _pass_lower,
        "legal_ir.api.explain": _pass_explain,
    }


def _pass_ingest(state: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = _mapping(state)
    text = _source_text(payload)
    normalized = " ".join(text.strip().split())
    source_map = _source_map_from_payload(payload) or _build_source_map(
        normalized,
        citation=str(payload.get("citation") or ""),
        source_document_id=str(payload.get("source_document_id") or payload.get("document_id") or "legal-ir-api-source"),
    )
    return {
        **payload,
        "normalized_document": {
            "citation": str(payload.get("citation") or ""),
            "normalized_text": normalized,
            "normalized_text_sha256": _content_hash(normalized),
            "source_document_id": str(payload.get("source_document_id") or payload.get("document_id") or "legal-ir-api-source"),
        },
        "source_map": source_map.to_dict(),
    }


def _pass_lower(state: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = _mapping(state)
    normalized = _mapping(payload.get("normalized_document"))
    text = str(normalized.get("normalized_text") or _source_text(payload))
    source_map = _source_map_from_payload(payload) or _build_source_map(text)
    obligations = _sequence(payload.get("obligations") or payload.get("proof_obligations"))
    if not obligations:
        obligations = [_obligation_from_text(text, source_map=source_map)]
    lowered = []
    proof_obligations = []
    for index, item in enumerate(obligations):
        row = _mapping(item)
        obligation_id = str(row.get("obligation_id") or row.get("id") or f"api-obligation-{index + 1:04d}")
        statement = str(row.get("statement") or row.get("text") or text)
        formula_id = str(row.get("formula_id") or f"formula-{obligation_id}")
        lowered_row = {
            "action": row.get("action", []),
            "citations": _sequence(row.get("citations") or ([normalized.get("citation")] if normalized.get("citation") else [])),
            "conditions": _sequence(row.get("conditions")),
            "exceptions": _sequence(row.get("exceptions")),
            "formula_id": formula_id,
            "object": row.get("object", []),
            "obligation_id": obligation_id,
            "operator": str(row.get("operator") or _operator_from_text(statement)),
            "proof_status": _mapping(row.get("proof_status")) or {"status": "unproved", "trust_status": "untrusted"},
            "source_node_ids": _sequence(row.get("source_node_ids")) or [formula_id],
            "statement": statement,
            "subject": row.get("subject", []),
        }
        lowered.append(lowered_row)
        proof_obligations.append(
            {
                "formula_id": formula_id,
                "kind": str(row.get("kind") or "compiler_surface_obligation"),
                "legal_ir_view": str(row.get("legal_ir_view") or "legal_ir.api"),
                "logic_family": str(row.get("logic_family") or "deontic"),
                "metadata": {"source": "legal_ir_compiler_api"},
                "obligation_id": obligation_id,
                "sample_id": str(row.get("sample_id") or normalized.get("source_document_id") or ""),
                "statement": statement,
            }
        )
    legal_ir_outputs = _mapping(payload.get("legal_ir_outputs")) or {
        "deontic": {"obligation_ids": [row["obligation_id"] for row in lowered]},
        "tdfol": {"formula_ids": [row["formula_id"] for row in lowered]},
    }
    return {
        **payload,
        "legal_ir_outputs": legal_ir_outputs,
        "obligations": lowered,
        "proof_obligations": proof_obligations,
        "source_map": source_map.to_dict(),
    }


def _pass_explain(state: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = _mapping(state)
    source_map = _source_map_from_payload(payload)
    diagnostics = build_legal_ir_diagnostic_report(payload, source_map=source_map)
    return {
        **payload,
        "decompiled_text": "\n".join(_decompiled_statements(payload)),
        "diagnostic_report": diagnostics.to_dict(),
    }


def _build_source_map(
    text: str,
    *,
    citation: str = "",
    source_document_id: str = "legal-ir-api-source",
) -> LegalIRSourceMap:
    citation = citation or f"uncited:{source_document_id}"
    source_map_id = "lir-source-map-" + _stable_hash(
        {"citation": citation, "source_document_id": source_document_id, "text": text}
    )[:24]
    builder = LegalIRSourceMapBuilder(source_map_id=source_map_id)
    builder.add_source_document(source_document_id, text, citation=citation)
    span = builder.add_span(
        source_document_id,
        0,
        len(text),
        transformation_step_id="legal_ir.api.ingest",
    )
    formula_id = "formula-" + _stable_hash({"source_map_id": source_map_id, "text": text})[:16]
    builder.add_node(
        formula_id,
        node_kind="compiler_formula",
        span_ids=(span.span_id,),
        emitted_fact=formula_id,
        transformation_step_id="legal_ir.api.lower",
    )
    return builder.to_source_map()


def _obligation_from_text(text: str, *, source_map: LegalIRSourceMap) -> dict[str, Any]:
    formula_node = next((node for node in source_map.nodes if node.node_kind == "compiler_formula"), None)
    formula_id = formula_node.node_id if formula_node else "formula-" + _stable_hash(text)[:16]
    obligation_id = "api-obligation-" + _stable_hash({"formula_id": formula_id, "text": text})[:16]
    return {
        "action": _action_terms(text),
        "formula_id": formula_id,
        "object": [],
        "obligation_id": obligation_id,
        "operator": _operator_from_text(text),
        "source_node_ids": [formula_id],
        "statement": text,
        "subject": [],
    }


def _compile_diagnostic_report(
    result: LegalIRIncrementalCompileResult,
    *,
    source_map: LegalIRSourceMap | None,
) -> LegalIRDiagnosticReport:
    builder = LegalIRDiagnosticsBuilder(source_map=source_map)
    for diagnostic in result.diagnostics:
        builder.add(
            LegalIRDiagnosticCode.COMPILER_DIAGNOSTIC,
            diagnostic.message,
            severity=diagnostic.severity,
            field_path=diagnostic.field_path,
            related_ids={"pass_id": (diagnostic.pass_id,), "code": (diagnostic.code,)},
            metadata=diagnostic.to_dict(),
        )
    nested = _mapping(result.output_state.get("diagnostic_report"))
    if nested:
        builder.extend(LegalIRDiagnosticReport.from_dict(nested).diagnostics)
    return builder.build()


def _result(
    operation: LegalIRCompilerOperation,
    payload: Mapping[str, Any],
    diagnostics: LegalIRDiagnosticReport,
    *,
    options: LegalIRCompilerOptions,
    source_map: LegalIRSourceMap | None = None,
    status: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> LegalIRCompilerResult:
    exit_code = _exit_code(diagnostics, options=options)
    resolved_status = status or ("ok" if exit_code == LegalIRCompilerExitCode.OK.value else "diagnostic_error")
    lsp = tuple(legal_ir_lsp_diagnostics(diagnostics)) if options.include_lsp_diagnostics else ()
    return LegalIRCompilerResult(
        operation=operation.value,
        status=resolved_status,
        exit_code=exit_code,
        payload=payload,
        diagnostics=diagnostics,
        lsp_diagnostics=lsp,
        source_map=source_map,
        options=options,
        metadata=dict(metadata or {}),
    )


def _exit_code(report: LegalIRDiagnosticReport, *, options: LegalIRCompilerOptions) -> int:
    if report.error_count:
        return LegalIRCompilerExitCode.DIAGNOSTIC_ERROR.value
    if options.fail_on_warnings and report.warning_count:
        return LegalIRCompilerExitCode.DIAGNOSTIC_ERROR.value
    return LegalIRCompilerExitCode.OK.value


def _exception_report(
    operation: str,
    exc: Exception,
    *,
    source_map: LegalIRSourceMap | None,
) -> LegalIRDiagnosticReport:
    builder = LegalIRDiagnosticsBuilder(source_map=source_map)
    builder.add(
        LegalIRDiagnosticCode.COMPILER_DIAGNOSTIC,
        f"LegalIR {operation} failed: {exc}",
        severity=LegalIRDiagnosticSeverity.FATAL,
        metadata={"exception_type": type(exc).__name__},
    )
    return builder.build()


def _proof_validation_diagnostics(validation: Any, *, source_map: LegalIRSourceMap | None) -> LegalIRDiagnosticReport:
    builder = LegalIRDiagnosticsBuilder(source_map=source_map)
    for diagnostic in validation.diagnostics:
        severity = LegalIRDiagnosticSeverity.ERROR if diagnostic.error else LegalIRDiagnosticSeverity.WARNING
        builder.add(
            LegalIRDiagnosticCode.PROOF_FAILURE,
            diagnostic.message,
            severity=severity,
            field_path=diagnostic.field_path,
            related_ids={
                "evidence_id": (diagnostic.evidence_id,),
                "obligation_id": (diagnostic.obligation_id,),
            },
            metadata=diagnostic.to_dict(),
        )
    return builder.build()


def _source_map_validation_diagnostics(validation: Any, *, source_map: LegalIRSourceMap | None) -> LegalIRDiagnosticReport:
    builder = LegalIRDiagnosticsBuilder(source_map=source_map)
    for issue in getattr(validation, "issues", ()):
        severity = (
            LegalIRDiagnosticSeverity.ERROR
            if str(issue.severity or "").lower() == "error"
            else LegalIRDiagnosticSeverity.WARNING
        )
        builder.add(
            LegalIRDiagnosticCode.SOURCE_MAP_UNTRACEABLE,
            issue.message,
            severity=severity,
            field_path=issue.field_path,
            related_ids={"source_map_issue": (issue.code,)},
            metadata=issue.to_dict(),
        )
    return builder.build()


def _proof_readiness_report(payload: Mapping[str, Any], *, source_map: LegalIRSourceMap | None) -> LegalIRDiagnosticReport:
    builder = LegalIRDiagnosticsBuilder(source_map=source_map)
    missing = []
    for field_name in (
        "proof_obligations",
        "hammer_guidance_artifacts",
        "translation_records",
        "reconstruction_receipts",
    ):
        if not _sequence(payload.get(field_name)):
            missing.append(field_name)
    for field_name in missing:
        builder.add_proof_failure(
            f"Cannot export proof-carrying artifact because {field_name} is missing.",
            field_path=field_name,
            related_ids={"missing_field": (field_name,)},
        )
    return builder.build()


def _merge_reports(left: LegalIRDiagnosticReport, right: LegalIRDiagnosticReport) -> LegalIRDiagnosticReport:
    return LegalIRDiagnosticReport(
        report_id="",
        diagnostics=(*left.diagnostics, *right.diagnostics),
        traces=(*left.traces, *right.traces),
        artifact_id=left.artifact_id or right.artifact_id,
        source_map_id=left.source_map_id or right.source_map_id,
        metadata={**dict(left.metadata), **dict(right.metadata)},
    )


def _merge_many_reports(reports: Sequence[LegalIRDiagnosticReport]) -> LegalIRDiagnosticReport:
    merged = LegalIRDiagnosticReport(report_id="", diagnostics=())
    for report in reports:
        merged = _merge_reports(merged, report)
    return merged


def _lsp_diagnostic(diagnostic: LegalIRDiagnostic) -> dict[str, Any]:
    source_map = diagnostic.source_map
    start = max(0, int(source_map.start_offset or 0))
    end = max(start, int(source_map.end_offset if source_map.end_offset is not None else start))
    return {
        "code": diagnostic.code,
        "data": diagnostic.to_dict(),
        "message": diagnostic.message,
        "range": {
            "end": {"character": end, "line": 0},
            "start": {"character": start, "line": 0},
        },
        "severity": _lsp_severity(diagnostic.severity),
        "source": "legal-ir-compiler",
    }


def _lsp_severity(severity: LegalIRDiagnosticSeverity) -> int:
    if severity in {LegalIRDiagnosticSeverity.ERROR, LegalIRDiagnosticSeverity.FATAL}:
        return 1
    if severity is LegalIRDiagnosticSeverity.WARNING:
        return 2
    return 3


def _options(value: LegalIRCompilerOptions | Mapping[str, Any] | None) -> LegalIRCompilerOptions:
    if isinstance(value, LegalIRCompilerOptions):
        return value
    data = _mapping(value)
    return LegalIRCompilerOptions(
        learned_guidance=bool(data.get("learned_guidance") or data.get("enable_learned_guidance")),
        learned_guidance_artifact=_mapping(data.get("learned_guidance_artifact")) or None,
        deterministic=bool(data.get("deterministic", True)),
        proof_aware=bool(data.get("proof_aware", True)),
        include_lsp_diagnostics=bool(data.get("include_lsp_diagnostics") or data.get("lsp")),
        fail_on_warnings=bool(data.get("fail_on_warnings", False)),
        max_workers=max(1, int(data.get("max_workers") or 1)),
        resource_limits=_mapping(data.get("resource_limits")) or {"cpu": max(1, int(data.get("max_workers") or 1))},
        metadata=_mapping(data.get("metadata")),
    )


def _initial_state(source: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, str):
        stripped = source.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, Mapping):
                return _mapping(parsed)
        return {"raw_document": source}
    return _mapping(source)


def _artifact_payload(artifact: Mapping[str, Any] | str) -> dict[str, Any]:
    if isinstance(artifact, str):
        stripped = artifact.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            loaded = json.loads(stripped)
            return _mapping(loaded)
        path = Path(artifact)
        if path.exists():
            return _mapping(read_legal_ir_json(path))
        return {"raw_document": artifact}
    return _mapping(artifact)


def _compiled_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("compiled"), Mapping):
        return _mapping(payload.get("compiled"))
    if isinstance(payload.get("payload"), Mapping):
        nested = _mapping(payload.get("payload"))
        if isinstance(nested.get("compiled"), Mapping):
            return _mapping(nested.get("compiled"))
    return _mapping(payload)


def _is_proof_carrying_artifact(payload: Mapping[str, Any]) -> bool:
    return str(payload.get("schema_version") or "") == LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION


def _can_build_proof_artifact(payload: Mapping[str, Any]) -> bool:
    return bool(
        payload.get("legal_ir_outputs") is not None
        and _sequence(payload.get("proof_obligations"))
        and _sequence(payload.get("hammer_guidance_artifacts"))
        and _sequence(payload.get("translation_records"))
        and _sequence(payload.get("reconstruction_receipts"))
    )


def _source_map_from_payload(payload: Mapping[str, Any]) -> LegalIRSourceMap | None:
    source_map = payload.get("source_map")
    if source_map is None and isinstance(payload.get("payload"), Mapping):
        source_map = _mapping(payload.get("payload")).get("source_map")
    if source_map is None:
        return None
    if isinstance(source_map, LegalIRSourceMap):
        return source_map
    data = _mapping(source_map)
    if not data:
        return None
    return LegalIRSourceMap.from_dict(data)


def _source_text(payload: Mapping[str, Any]) -> str:
    for key in ("raw_document", "source", "text", "normalized_text"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    normalized = _mapping(payload.get("normalized_document"))
    if normalized.get("normalized_text"):
        return str(normalized["normalized_text"])
    return ""


def _decompiled_statements(payload: Mapping[str, Any]) -> list[str]:
    if payload.get("decompiled_text"):
        return [line for line in str(payload["decompiled_text"]).splitlines() if line.strip()]
    statements = []
    for item in _sequence(payload.get("obligations") or payload.get("proof_obligations")):
        row = _mapping(item)
        statement = str(row.get("statement") or "").strip()
        if statement:
            statements.append(statement)
    if not statements and _source_text(payload):
        statements.append(_source_text(payload))
    return statements


def _learned_guidance_state(*, active: bool, artifact: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload = _mapping(artifact)
    return {
        "active": bool(active),
        "activation_mode": "explicit_flag" if active else "deterministic_default",
        "artifact_digest": _stable_hash(payload) if payload else "",
        "export_id": str(payload.get("export_id") or payload.get("guidance_id") or ""),
        "production_default": not bool(active),
    }


def _operator_from_text(text: str) -> str:
    lowered = text.lower()
    for token in ("shall not", "must not", "shall", "must", "may"):
        if token in lowered:
            return token
    return "shall"


def _action_terms(text: str) -> list[str]:
    words = [word.strip(".,;:()[]{}").lower() for word in text.split()]
    stop = {"the", "a", "an", "shall", "must", "may", "not", "within", "unless", "if"}
    return [word for word in words if word and word not in stop][:8]


def _proof_rank_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "proof_obligations": len(_sequence(payload.get("proof_obligations"))),
        "reconstruction_receipts": len(_sequence(payload.get("reconstruction_receipts"))),
        "translation_records": len(_sequence(payload.get("translation_records"))),
    }


def _stable_float(value: float) -> float:
    if not math.isfinite(float(value)):
        return 0.0
    return round(float(value), 9)


def _mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if hasattr(value, "to_dict"):
        return _mapping(value.to_dict())
    return {}


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return _json_ready(value.to_dict())
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    return str(value)


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_ready(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _content_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


__all__ = [
    "LEGAL_IR_COMPILER_API_SCHEMA_VERSION",
    "LEGAL_IR_COMPILER_ARTIFACT_SCHEMA_VERSION",
    "LegalIRCompilerAPI",
    "LegalIRCompilerExitCode",
    "LegalIRCompilerOperation",
    "LegalIRCompilerOptions",
    "LegalIRCompilerResult",
    "benchmark_legal_ir",
    "compile_legal_ir",
    "decompile_legal_ir",
    "default_legal_ir_api_passes",
    "diff_legal_ir",
    "explain_legal_ir",
    "export_legal_ir_artifact",
    "legal_ir_lsp_diagnostics",
    "read_legal_ir_json",
    "validate_legal_ir",
    "write_legal_ir_json",
]
