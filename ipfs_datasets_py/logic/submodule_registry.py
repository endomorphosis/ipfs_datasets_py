"""Machine-readable integration map for the logic package.

The logic tree has grown into several semi-independent families: FOL,
deontic, modal/frame-logic, TDFOL, CEC, external provers, ZKP, graph bridges,
and shared infrastructure.  This module keeps that topology explicit without
importing heavy optional dependencies at package import time.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class LogicSubmoduleSpec:
    """Static description of one logic submodule or integration endpoint."""

    name: str
    module: str
    description: str
    roles: tuple[str, ...]
    optimizer_components: tuple[str, ...] = ()
    target_files: tuple[str, ...] = ()
    ast_scope: str = ""
    required: bool = True
    import_check: bool = True
    optional_dependencies: tuple[str, ...] = ()
    public_symbols: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable manifest entry."""

        return {
            "ast_scope": self.ast_scope,
            "description": self.description,
            "import_check": self.import_check,
            "module": self.module,
            "name": self.name,
            "notes": self.notes,
            "optimizer_components": list(self.optimizer_components),
            "optional_dependencies": list(self.optional_dependencies),
            "public_symbols": list(self.public_symbols),
            "required": self.required,
            "roles": list(self.roles),
            "target_files": list(self.target_files),
        }


_SPECS: tuple[LogicSubmoduleSpec, ...] = (
    LogicSubmoduleSpec(
        name="common",
        module="ipfs_datasets_py.logic.common",
        description="Shared errors, converter primitives, caches, feature detection, and validators.",
        roles=("foundation", "cache", "validation", "converter_contract"),
        optimizer_components=("common.cache", "common.validation"),
        target_files=(
            "ipfs_datasets_py/logic/common/converters.py",
            "ipfs_datasets_py/logic/common/proof_cache.py",
            "ipfs_datasets_py/logic/common/validators.py",
        ),
        ast_scope="common",
        public_symbols=("LogicConverter", "ConversionResult", "ProofCache"),
    ),
    LogicSubmoduleSpec(
        name="types",
        module="ipfs_datasets_py.logic.types",
        description="Canonical shared logic, proof, bridge, translation, and FOL type aliases.",
        roles=("foundation", "ir_types", "type_contract"),
        optimizer_components=("types.contracts",),
        target_files=(
            "ipfs_datasets_py/logic/types/__init__.py",
            "ipfs_datasets_py/logic/types/bridge_types.py",
            "ipfs_datasets_py/logic/types/translation_types.py",
        ),
        ast_scope="types",
        public_symbols=("Formula", "Predicate", "TranslationResult", "BridgeConfig"),
    ),
    LogicSubmoduleSpec(
        name="bridge",
        module="ipfs_datasets_py.logic.bridge",
        description="Canonical legal IR bridge contracts and adapter registry for optimizer/prover/KG routing.",
        roles=("bridge", "legal_ir", "loss", "prover", "kg", "optimizer_contract"),
        optimizer_components=("bridge.contracts", "bridge.registry"),
        target_files=(
            "ipfs_datasets_py/logic/bridge/__init__.py",
            "ipfs_datasets_py/logic/bridge/types.py",
            "ipfs_datasets_py/logic/bridge/registry.py",
            "ipfs_datasets_py/logic/bridge/modal_frame_logic.py",
            "ipfs_datasets_py/logic/bridge/deontic_norms.py",
        ),
        ast_scope="bridge",
        public_symbols=(
            "LegalIRDocument",
            "BridgeEvaluationReport",
            "logic_bridge_manifest",
        ),
    ),
    LogicSubmoduleSpec(
        name="fol",
        module="ipfs_datasets_py.logic.fol",
        description="First-order logic conversion and predicate extraction from natural language.",
        roles=("legal_ir", "fol", "compiler", "nlp_parse"),
        optimizer_components=("fol.converter", "fol.predicate_extractor"),
        target_files=(
            "ipfs_datasets_py/logic/fol/__init__.py",
            "ipfs_datasets_py/logic/fol/fol_converter.py",
            "ipfs_datasets_py/logic/fol/utils/nlp_predicate_extractor.py",
        ),
        ast_scope="fol",
        public_symbols=("FOLConverter", "convert_text_to_fol"),
    ),
    LogicSubmoduleSpec(
        name="deontic",
        module="ipfs_datasets_py.logic.deontic",
        description="Legal norm IR, deontic conversion, proof/export tables, graphs, and knowledge base.",
        roles=("legal_ir", "deontic", "compiler", "prover_input", "graph"),
        optimizer_components=(
            "deontic.converter",
            "deontic.ir",
            "deontic.formula_builder",
            "deontic.exports",
            "deontic.graph",
            "deontic.knowledge_base",
        ),
        target_files=(
            "ipfs_datasets_py/logic/deontic/converter.py",
            "ipfs_datasets_py/logic/deontic/ir.py",
            "ipfs_datasets_py/logic/deontic/formula_builder.py",
            "ipfs_datasets_py/logic/deontic/exports.py",
            "ipfs_datasets_py/logic/deontic/graph.py",
            "ipfs_datasets_py/logic/deontic/knowledge_base.py",
        ),
        ast_scope="deontic",
        public_symbols=("DeonticConverter", "LegalNormIR", "build_deontic_formula_from_ir"),
    ),
    LogicSubmoduleSpec(
        name="modal",
        module="ipfs_datasets_py.logic.modal",
        description="Deterministic modal compiler, IR codec, decompiler, autoencoder loop, and frame-logic KG bridge.",
        roles=("legal_ir", "modal", "compiler", "decoder", "autoencoder", "frame_logic", "kg"),
        optimizer_components=(
            "modal.compiler",
            "modal.compiler.registry",
            "modal.compiler.ambiguity",
            "modal.ir_decompiler",
            "modal.frame_logic",
        ),
        target_files=(
            "ipfs_datasets_py/logic/modal/compiler.py",
            "ipfs_datasets_py/logic/modal/codec.py",
            "ipfs_datasets_py/logic/modal/decompiler.py",
            "ipfs_datasets_py/logic/modal/kg_bridge.py",
            "ipfs_datasets_py/logic/modal/synthesis.py",
            "ipfs_datasets_py/logic/modal/autoencoder_loop.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_ir.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_registry.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py",
        ),
        ast_scope="modal",
        public_symbols=("DeterministicModalLogicCodec", "LegalModalAutoencoderLoop"),
    ),
    LogicSubmoduleSpec(
        name="flogic",
        module="ipfs_datasets_py.logic.flogic",
        description="Frame-logic types, ErgoAI wrapper, proof cache, semantic normalizer, and ZKP bridge.",
        roles=("legal_ir", "frame_logic", "ontology", "prover_input", "zkp"),
        optimizer_components=("flogic.ontology", "flogic.semantic_normalizer", "flogic.zkp"),
        target_files=(
            "ipfs_datasets_py/logic/flogic/flogic_types.py",
            "ipfs_datasets_py/logic/flogic/ergoai_wrapper.py",
            "ipfs_datasets_py/logic/flogic/flogic_proof_cache.py",
            "ipfs_datasets_py/logic/flogic/flogic_zkp_integration.py",
            "ipfs_datasets_py/logic/flogic/semantic_normalizer.py",
        ),
        ast_scope="flogic",
        optional_dependencies=("ErgoAI/ErgoEngine",),
        public_symbols=("FLogicFrame", "FLogicOntology", "CachedErgoAIWrapper"),
    ),
    LogicSubmoduleSpec(
        name="flogic_optimizer",
        module="ipfs_datasets_py.logic.flogic_optimizer",
        description="Loss-aware frame-logic semantic optimizer for round-trip and ontology alignment.",
        roles=("optimizer", "frame_logic", "loss", "semantic_similarity"),
        optimizer_components=("flogic.optimizer",),
        target_files=(
            "ipfs_datasets_py/logic/flogic_optimizer.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/frame_bm25_selector.py",
        ),
        ast_scope="frame_logic",
        public_symbols=("FLogicSemanticOptimizer", "FLogicOptimizerConfig"),
    ),
    LogicSubmoduleSpec(
        name="TDFOL",
        module="ipfs_datasets_py.logic.TDFOL",
        description="Temporal deontic first-order logic core, parser, prover, strategies, NL bridge, and ZKP integration.",
        roles=("legal_ir", "tdfol", "temporal", "deontic", "prover", "strategy", "zkp"),
        optimizer_components=(
            "TDFOL.core",
            "TDFOL.parser",
            "TDFOL.prover",
            "TDFOL.inference_rules",
            "TDFOL.strategies",
            "TDFOL.nl",
            "TDFOL.zkp",
        ),
        target_files=(
            "ipfs_datasets_py/logic/TDFOL/tdfol_core.py",
            "ipfs_datasets_py/logic/TDFOL/tdfol_parser.py",
            "ipfs_datasets_py/logic/TDFOL/tdfol_prover.py",
            "ipfs_datasets_py/logic/TDFOL/inference_rules",
            "ipfs_datasets_py/logic/TDFOL/strategies",
            "ipfs_datasets_py/logic/TDFOL/nl",
            "ipfs_datasets_py/logic/TDFOL/zkp_integration.py",
        ),
        ast_scope="tdfol",
        public_symbols=("TDFOLKnowledgeBase", "Predicate", "create_obligation"),
    ),
    LogicSubmoduleSpec(
        name="CEC",
        module="ipfs_datasets_py.logic.CEC",
        description="Cognitive Event Calculus wrappers, native DCEC implementation, NL compiler, and theorem proving.",
        roles=("legal_ir", "cec", "event_calculus", "prover", "nlp_parse"),
        optimizer_components=("CEC.framework", "CEC.native", "CEC.nl", "CEC.provers"),
        target_files=(
            "ipfs_datasets_py/logic/CEC/__init__.py",
            "ipfs_datasets_py/logic/CEC/native",
            "ipfs_datasets_py/logic/CEC/nl",
            "ipfs_datasets_py/logic/CEC/provers",
        ),
        ast_scope="cec",
        optional_dependencies=("SPASS", "ShadowProver"),
        public_symbols=("CECFramework", "TalosWrapper", "ShadowProverWrapper"),
    ),
    LogicSubmoduleSpec(
        name="external_provers",
        module="ipfs_datasets_py.logic.external_provers",
        description="Lazy routed Z3, CVC5, Lean, Coq, and SymbolicAI theorem prover bridges and installers.",
        roles=("prover", "installer", "router", "smt", "interactive", "neural"),
        optimizer_components=(
            "external_provers.router",
            "external_provers.smt",
            "external_provers.interactive",
            "external_provers.neural",
        ),
        target_files=(
            "ipfs_datasets_py/logic/external_provers/__init__.py",
            "ipfs_datasets_py/logic/external_provers/lazy_installer.py",
            "ipfs_datasets_py/logic/external_provers/prover_router.py",
            "ipfs_datasets_py/logic/external_provers/smt",
            "ipfs_datasets_py/logic/external_provers/interactive",
            "ipfs_datasets_py/logic/external_provers/neural",
        ),
        ast_scope="external_provers",
        optional_dependencies=("z3-solver", "cvc5", "lean", "coq", "symbolicai"),
        public_symbols=("ProverRouter", "lazy_install_prover", "get_available_provers"),
    ),
    LogicSubmoduleSpec(
        name="integration",
        module="ipfs_datasets_py.logic.integration",
        description="High-level bridges, converters, domain reasoning, caching, symbolic, and UCAN integrations.",
        roles=("bridge", "converter", "reasoning", "symbolic", "ucan", "cache"),
        optimizer_components=(
            "integration.bridges",
            "integration.converters",
            "integration.reasoning",
            "integration.symbolic",
            "integration.caching",
            "integration.domain",
        ),
        target_files=(
            "ipfs_datasets_py/logic/integration/__init__.py",
            "ipfs_datasets_py/logic/integration/bridges",
            "ipfs_datasets_py/logic/integration/converters",
            "ipfs_datasets_py/logic/integration/reasoning",
            "ipfs_datasets_py/logic/integration/symbolic",
            "ipfs_datasets_py/logic/integration/caching",
            "ipfs_datasets_py/logic/integration/domain",
        ),
        ast_scope="integration",
        optional_dependencies=("symbolicai", "py-ucan"),
        public_symbols=("enable_symbolicai",),
    ),
    LogicSubmoduleSpec(
        name="integrations",
        module="ipfs_datasets_py.logic.integrations",
        description="GraphRAG, UnixFS, and phase integration adapters outside the core theorem bridge tree.",
        roles=("bridge", "graphrag", "storage", "unixfs"),
        optimizer_components=("integrations.graphrag", "integrations.unixfs", "integrations.phase7"),
        target_files=("ipfs_datasets_py/logic/integrations/__init__.py",),
        ast_scope="integrations",
    ),
    LogicSubmoduleSpec(
        name="zkp",
        module="ipfs_datasets_py.logic.zkp",
        description="Zero-knowledge proof circuits and simulation backend for logic proof attestations.",
        roles=("zkp", "proof_attestation", "circuit"),
        optimizer_components=("zkp.circuits", "zkp.backends"),
        target_files=(
            "ipfs_datasets_py/logic/zkp/__init__.py",
            "ipfs_datasets_py/logic/zkp/form_circuit.py",
            "ipfs_datasets_py/logic/zkp/backends",
        ),
        ast_scope="zkp",
        optional_dependencies=("circom/snarkjs",),
        public_symbols=("ZKPProver", "ZKPVerifier", "create_implication_circuit"),
    ),
    LogicSubmoduleSpec(
        name="security",
        module="ipfs_datasets_py.logic.security",
        description="Input validation, rate limiting, audit logging, and LLM circuit breaker controls.",
        roles=("security", "validation", "rate_limit", "audit", "llm_guard"),
        optimizer_components=("security.input_validation", "security.rate_limiting", "security.llm_circuit_breaker"),
        target_files=(
            "ipfs_datasets_py/logic/security/input_validation.py",
            "ipfs_datasets_py/logic/security/rate_limiting.py",
            "ipfs_datasets_py/logic/security/audit_log.py",
            "ipfs_datasets_py/logic/security/llm_circuit_breaker.py",
        ),
        ast_scope="security",
        public_symbols=("InputValidator", "LLMCircuitBreaker"),
    ),
    LogicSubmoduleSpec(
        name="observability",
        module="ipfs_datasets_py.logic.observability",
        description="Structured logs, performance spans, and log analysis helpers for logic/prover runs.",
        roles=("observability", "logging", "metrics"),
        optimizer_components=("observability.structured_logging",),
        target_files=("ipfs_datasets_py/logic/observability/structured_logging.py",),
        ast_scope="observability",
        public_symbols=("get_logger", "log_performance"),
    ),
    LogicSubmoduleSpec(
        name="ml_confidence",
        module="ipfs_datasets_py.logic.ml_confidence",
        description="Optional ML confidence scoring for logic conversion quality.",
        roles=("loss", "confidence", "quality_signal"),
        optimizer_components=("ml_confidence.scoring",),
        target_files=("ipfs_datasets_py/logic/ml_confidence.py",),
        ast_scope="loss",
        required=False,
        optional_dependencies=("scikit-learn", "numpy"),
    ),
    LogicSubmoduleSpec(
        name="batch_processing",
        module="ipfs_datasets_py.logic.batch_processing",
        description="Batch conversion helpers for large legal or policy corpora.",
        roles=("batch", "pipeline"),
        optimizer_components=("batch_processing",),
        target_files=("ipfs_datasets_py/logic/batch_processing.py",),
        ast_scope="batch",
        required=False,
    ),
    LogicSubmoduleSpec(
        name="benchmarks",
        module="ipfs_datasets_py.logic.benchmarks",
        description="Logic conversion/prover benchmarking helpers.",
        roles=("benchmark", "quality_signal"),
        optimizer_components=("benchmarks",),
        target_files=("ipfs_datasets_py/logic/benchmarks.py", "ipfs_datasets_py/logic/phase7_4_benchmarks.py"),
        ast_scope="benchmark",
        required=False,
    ),
    LogicSubmoduleSpec(
        name="monitoring",
        module="ipfs_datasets_py.logic.monitoring",
        description="Logic monitoring utilities used by long-running optimizer/daemon workflows.",
        roles=("observability", "daemon", "metrics"),
        optimizer_components=("monitoring",),
        target_files=("ipfs_datasets_py/logic/monitoring.py",),
        ast_scope="observability",
        required=False,
    ),
    LogicSubmoduleSpec(
        name="knowledge_graphs",
        module="ipfs_datasets_py.knowledge_graphs",
        description="Neo4j-compatible decentralized graph engine that consumes modal/frame-logic graph data.",
        roles=("kg", "neo4j_compat", "ipld", "storage"),
        optimizer_components=("knowledge_graphs.core", "knowledge_graphs.neo4j_compat"),
        target_files=(
            "ipfs_datasets_py/knowledge_graphs/core",
            "ipfs_datasets_py/knowledge_graphs/neo4j_compat",
            "ipfs_datasets_py/knowledge_graphs/storage",
            "ipfs_datasets_py/logic/modal/kg_bridge.py",
        ),
        ast_scope="knowledge_graphs",
        public_symbols=("GraphEngine", "GraphDatabase"),
        notes="Cross-package endpoint included so frame-logic IR import remains visible from the logic manifest.",
    ),
    LogicSubmoduleSpec(
        name="tools",
        module="ipfs_datasets_py.logic.tools",
        description="Deprecated compatibility namespace redirected toward logic.integration.",
        roles=("deprecated", "compatibility"),
        optimizer_components=("tools.compatibility",),
        target_files=("ipfs_datasets_py/logic/tools",),
        ast_scope="compatibility",
        required=False,
        notes="Kept in the manifest so migration work remains visible; new code should use logic.integration.",
    ),
    LogicSubmoduleSpec(
        name="ErgoAI",
        module="",
        description="Placeholder/vendor location for ErgoAI/ErgoEngine frame-logic prover assets.",
        roles=("external_binary", "frame_logic", "prover"),
        optimizer_components=("ErgoAI.asset",),
        target_files=("ipfs_datasets_py/logic/ErgoAI",),
        ast_scope="external_binary",
        required=False,
        import_check=False,
        optional_dependencies=("ErgoAI/ErgoEngine",),
    ),
)


_SPECS_BY_NAME: Mapping[str, LogicSubmoduleSpec] = {spec.name: spec for spec in _SPECS}


def logic_submodule_specs() -> tuple[LogicSubmoduleSpec, ...]:
    """Return all known logic submodule specs in deterministic order."""

    return _SPECS


def logic_submodule_names(*, required_only: bool = False) -> tuple[str, ...]:
    """Return all registered submodule names."""

    return tuple(
        spec.name
        for spec in _SPECS
        if not required_only or spec.required
    )


def logic_submodule_spec(name: str) -> LogicSubmoduleSpec:
    """Return the spec for *name* or raise ``KeyError``."""

    return _SPECS_BY_NAME[name]


def logic_integration_manifest() -> dict[str, Any]:
    """Return the canonical logic integration manifest."""

    specs = [spec.to_dict() for spec in _SPECS]
    roles: dict[str, list[str]] = {}
    for spec in _SPECS:
        for role in spec.roles:
            roles.setdefault(role, []).append(spec.name)
    return {
        "manifest_version": 1,
        "submodule_count": len(specs),
        "submodules": specs,
        "required_submodules": list(logic_submodule_names(required_only=True)),
        "roles": {role: sorted(names) for role, names in sorted(roles.items())},
        "optimizer_target_file_hints": {
            key: list(value)
            for key, value in sorted(logic_optimizer_target_file_hints().items())
        },
    }


def logic_submodule_import_report(
    *,
    include_optional: bool = False,
) -> dict[str, dict[str, Any]]:
    """Import-check registered modules without touching disabled optional entries."""

    report: dict[str, dict[str, Any]] = {}
    for spec in _SPECS:
        if not spec.import_check:
            report[spec.name] = {
                "module": spec.module,
                "ok": None,
                "skipped": True,
                "reason": "import_check_disabled",
            }
            continue
        if not include_optional and not spec.required:
            report[spec.name] = {
                "module": spec.module,
                "ok": None,
                "skipped": True,
                "reason": "optional_submodule",
            }
            continue
        try:
            module = importlib.import_module(spec.module)
        except Exception as exc:  # pragma: no cover - exercised in failure diagnostics
            report[spec.name] = {
                "error": f"{type(exc).__name__}: {exc}",
                "module": spec.module,
                "ok": False,
                "skipped": False,
            }
        else:
            report[spec.name] = {
                "module": spec.module,
                "ok": True,
                "skipped": False,
                "version": module.__dict__.get("__version__"),
            }
    return report


def logic_optimizer_target_file_hints() -> dict[str, tuple[str, ...]]:
    """Return target component -> file hints for Codex work packets."""

    hints: dict[str, list[str]] = {}
    for spec in _SPECS:
        for component in spec.optimizer_components:
            bucket = hints.setdefault(component, [])
            for file_path in spec.target_files:
                if file_path not in bucket:
                    bucket.append(file_path)

    # Modal runner compatibility aliases used by existing TODOs.
    _extend_unique(
        hints.setdefault("modal.compiler", []),
        (
            "ipfs_datasets_py/logic/modal/compiler.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_modal_parser.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py",
        ),
    )
    _extend_unique(
        hints.setdefault("modal.compiler.registry", []),
        (
            "ipfs_datasets_py/logic/modal/compiler.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_registry.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py",
        ),
    )
    _extend_unique(
        hints.setdefault("modal.compiler.ambiguity", []),
        (
            "ipfs_datasets_py/logic/modal/compiler.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_registry.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py",
        ),
    )
    _extend_unique(
        hints.setdefault("modal.ir_decompiler", []),
        (
            "ipfs_datasets_py/logic/modal/codec.py",
            "ipfs_datasets_py/logic/modal/decompiler.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_ir.py",
        ),
    )
    _extend_unique(
        hints.setdefault("modal.frame_logic", []),
        (
            "ipfs_datasets_py/logic/modal/codec.py",
            "ipfs_datasets_py/logic/modal/kg_bridge.py",
            "ipfs_datasets_py/logic/flogic_optimizer.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/frame_bm25_selector.py",
        ),
    )

    return {key: tuple(value) for key, value in sorted(hints.items())}


def logic_optimizer_scope_for_component(
    target_component: str,
    *,
    action: str = "",
) -> str:
    """Return a merge-safe AST/write lane for an optimizer target component."""

    target = str(target_component or "").strip()
    if not target:
        return str(action or "").replace("-", "_").replace(".", "_")

    explicit = {
        "modal.frame_logic": "frame_logic",
        "modal.ir_decompiler": "ir_decompiler",
        "modal.compiler.ambiguity": "compiler_ambiguity",
        "modal.compiler.registry": "compiler_registry",
        "modal.compiler": "compiler_parser",
    }
    for prefix, scope in explicit.items():
        if target.startswith(prefix):
            return scope

    for spec in _SPECS:
        if any(target.startswith(component) for component in spec.optimizer_components):
            return spec.ast_scope or spec.name

    return target.replace("-", "_").replace(".", "_")


def _extend_unique(values: list[str], additions: tuple[str, ...]) -> None:
    for value in additions:
        if value not in values:
            values.append(value)


__all__ = [
    "LogicSubmoduleSpec",
    "logic_integration_manifest",
    "logic_optimizer_scope_for_component",
    "logic_optimizer_target_file_hints",
    "logic_submodule_import_report",
    "logic_submodule_names",
    "logic_submodule_spec",
    "logic_submodule_specs",
]
