"""Deterministic Security IR adapter for the shared formalization contracts.

The adapter consumes immutable :class:`SecurityIR` declarations, or legacy
adapter inputs that can be converted to one, and emits source-grounded formal
samples and artifacts.  It never imports proof results, solver observations,
runtime traces, or counterexamples into declaration features.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Final

from ..formalization.compiler import (
    FormalizationArtifact,
    FormalizationCompiler,
    FormalizationCompilerConfig,
    UnsupportedSemanticsPolicy,
)
from ..formalization.samples import FormalizationSample
from ..formalization.views import (
    FormalFormula,
    FormalSymbol,
    FormalizationView,
    SymbolTable,
    ViewRegistry,
)
from ..ir_core.claims import Assumption, ProofObligation
from ..ir_core.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticLocation,
    DiagnosticReport,
    DiagnosticSeverity,
)
from ..ir_core.provenance import (
    ConfigBinding,
    ProducerBinding,
    Provenance,
    ProvenanceBinding,
    SourceRef,
    SourceReviewStatus,
)
from .adapter import LegacyAdapterResult, adapt_legacy_security_ir
from .model import (
    SecurityClaim,
    SecurityExtension,
    SecurityIR,
    SecuritySource,
    StateMachine,
    StateTransition,
    ThreatAssumption,
)


SECURITY_IR_FORMALIZATION_ADAPTER_VERSION: Final = (
    "security-ir-formalization-adapter/v1"
)
SECURITY_IR_FORMALIZATION_PRODUCER_ID: Final = (
    "security-ir-formalization-adapter"
)
SECURITY_IR_FORMALIZATION_CONFIG_ID: Final = (
    "security-ir-formalization-default"
)
SECURITY_IR_FORMALIZATION_DOMAIN: Final = "security"
# Legal-adapter-shaped spellings used by shared integration code.
SECURITY_IR_ADAPTER_PRODUCER_ID: Final = (
    SECURITY_IR_FORMALIZATION_PRODUCER_ID
)
SECURITY_IR_ADAPTER_CONFIG_ID: Final = SECURITY_IR_FORMALIZATION_CONFIG_ID
SECURITY_IR_DOMAIN: Final = SECURITY_IR_FORMALIZATION_DOMAIN

SECURITY_IR_THREAT_VIEW_ID: Final = "security-ir-view/threat/v1"
SECURITY_IR_POLICY_VIEW_ID: Final = "security-ir-view/policy/v1"
SECURITY_IR_TRANSITION_VIEW_ID: Final = "security-ir-view/transition/v1"
SECURITY_IR_CLAIM_VIEW_ID: Final = "security-ir-view/claim/v1"

_RESULT_FIELD_NAMES: Final = frozenset(
    {
        "proof_obligations",
        "disproof_vectors",
        "runtime_traces",
        "solver_results",
    }
)


class SecurityIRFormalizationAdapterError(ValueError):
    """Raised when a Security declaration cannot be safely formalized."""


SECURITY_IR_FORMALIZATION_VIEW_REGISTRY = ViewRegistry(
    (
        FormalizationView(
            view_id=SECURITY_IR_THREAT_VIEW_ID,
            logic_family="threat_model",
            description="Explicit threat premises and environmental assumptions.",
            capabilities=("assumptions", "source_grounding", "typed_symbols"),
            metadata={"security_constructs": ["threat_assumption"]},
        ),
        FormalizationView(
            view_id=SECURITY_IR_POLICY_VIEW_ID,
            logic_family="deontic",
            description="Declarative allow, deny, require, and audit policies.",
            capabilities=(
                "action_contracts",
                "deontic_modality",
                "source_grounding",
            ),
            metadata={"security_constructs": ["policy"]},
        ),
        FormalizationView(
            view_id=SECURITY_IR_TRANSITION_VIEW_ID,
            logic_family="transition_system",
            description="Finite-state machines and guarded security transitions.",
            capabilities=(
                "source_grounding",
                "state_transitions",
                "temporal_control",
            ),
            metadata={"security_constructs": ["state_machine", "transition"]},
        ),
        FormalizationView(
            view_id=SECURITY_IR_CLAIM_VIEW_ID,
            logic_family="verification_condition",
            description="Security claims and their solver-neutral obligations.",
            capabilities=(
                "assumptions",
                "proof_obligations",
                "source_grounding",
            ),
            metadata={"security_constructs": ["claim"]},
        ),
    ),
    registry_id="security-ir-formalization-views",
)
# Concise compatibility spelling for registry consumers.
SECURITY_IR_VIEW_REGISTRY = SECURITY_IR_FORMALIZATION_VIEW_REGISTRY


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _derived_id(prefix: str, value: str) -> str:
    """Create a readable stable identifier without exceeding kernel limits."""

    candidate = f"{prefix}:{value}"
    if len(candidate) <= 256:
        return candidate
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _binding_id(subject_id: str, purpose: str) -> str:
    digest = hashlib.sha256(
        f"{purpose}\0{subject_id}".encode("utf-8")
    ).hexdigest()
    return f"binding:security:{purpose}:{digest[:32]}"


def _review_status(value: str) -> SourceReviewStatus:
    try:
        return SourceReviewStatus(value)
    except ValueError:
        return SourceReviewStatus.UNREVIEWED


def _declaration_from_input(value: Any) -> SecurityIR:
    if isinstance(value, SecurityIR):
        value.validate()
        return value
    if isinstance(value, LegacyAdapterResult):
        value.declaration.validate()
        return value.declaration
    declaration = getattr(value, "declaration", None)
    if isinstance(declaration, SecurityIR):
        declaration.validate()
        return declaration
    if isinstance(value, Mapping) and (
        value.get("schema_version") == "security-ir/v1"
        or "declaration_id" in value
    ):
        try:
            return SecurityIR.from_dict(value)
        except (TypeError, ValueError) as exc:
            raise SecurityIRFormalizationAdapterError(
                f"invalid Security IR declaration: {exc}"
            ) from exc
    try:
        return adapt_legacy_security_ir(value).declaration
    except (TypeError, ValueError) as exc:
        raise SecurityIRFormalizationAdapterError(
            "expected a SecurityIR, a Security adapter result, or a valid "
            f"legacy SecurityModelIR input: {exc}"
        ) from exc


def _record_sources(
    source_ids: Sequence[str],
    *,
    known_source_ids: frozenset[str],
    declaration_source_id: str,
) -> tuple[str, ...]:
    resolved = tuple(dict.fromkeys(source_ids))
    unknown = set(resolved) - known_source_ids
    if unknown:
        # SecurityIR.validate normally makes this unreachable, but keeping the
        # check here prevents a future relaxed domain schema from fabricating
        # generic provenance.
        raise SecurityIRFormalizationAdapterError(
            "declaration node references unknown Security sources: "
            + ", ".join(sorted(unknown))
        )
    return resolved or (declaration_source_id,)


def _source_ref(source: SecuritySource) -> SourceRef:
    source_dict = source.to_dict()
    exact_content_address = bool(source.content_sha256)
    content_sha256 = source.content_sha256 or hashlib.sha256(
        _canonical_bytes(source_dict)
    ).hexdigest()
    source_uri = (
        source.uri
        if exact_content_address
        else f"urn:security-ir:source-descriptor:{source.source_id}"
    )
    metadata = {
        "content_binding": (
            "declared_source_bytes"
            if exact_content_address
            else "security_source_descriptor"
        ),
        "declared_review_status": source.review_status,
        "original_source_uri": source.uri,
        "security_source_attributes": source_dict["attributes"],
    }
    return SourceRef(
        ref_id=source.source_id,
        source_uri=source_uri,
        source_id=source.source_id,
        source_revision=source.revision or "unversioned",
        content_sha256=content_sha256,
        review_status=_review_status(source.review_status),
        metadata=metadata,
    )


def _input_node_id(kind: str, source_id: str) -> str:
    return _derived_id(f"security-node:{kind}", source_id)


def _formula_id(kind: str, source_id: str) -> str:
    return _derived_id(f"formula:security:{kind}", source_id)


def _symbol_id(kind: str, source_id: str) -> str:
    return _derived_id(f"symbol:security:{kind}", source_id)


def _transition_key(
    machine: StateMachine, transition: StateTransition, index: int
) -> str:
    semantic = {
        "index": index,
        "machine_id": machine.state_machine_id,
        "transition": transition.to_dict(),
    }
    suffix = hashlib.sha256(_canonical_bytes(semantic)).hexdigest()[:20]
    return f"{machine.state_machine_id}:{index}:{suffix}"


def _contains_result_fields(value: Any) -> bool:
    if isinstance(value, Mapping):
        if _RESULT_FIELD_NAMES.intersection(value):
            return True
        return any(_contains_result_fields(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return any(_contains_result_fields(item) for item in value)
    return False


class SecurityIRFormalizationAdapter(FormalizationCompiler):
    """Adapt Security IR v1 declarations to shared formalization artifacts."""

    producer_id: Final = SECURITY_IR_FORMALIZATION_PRODUCER_ID
    producer_version: Final = SECURITY_IR_FORMALIZATION_ADAPTER_VERSION
    view_registry: Final = SECURITY_IR_FORMALIZATION_VIEW_REGISTRY

    def adapt_sample(self, security_declaration: Any) -> FormalizationSample:
        """Create a declaration-only, source-grounded formalization sample."""

        declaration = _declaration_from_input(security_declaration)
        # Reparse canonical declaration JSON so set-like Security collections
        # have one order throughout payload construction, provenance node
        # numbering, and compilation.
        declaration_payload = json.loads(declaration.canonical_json())
        declaration = SecurityIR.from_dict(declaration_payload)
        if _contains_result_fields(declaration_payload):
            raise SecurityIRFormalizationAdapterError(
                "Security declaration unexpectedly contains verification-run fields"
            )

        declaration_bytes = declaration.canonical_bytes()
        declaration_sha256 = hashlib.sha256(declaration_bytes).hexdigest()
        declaration_source_id = (
            f"source:security-declaration:{declaration_sha256[:24]}"
        )
        sample_id = f"sample:security:{declaration_sha256[:32]}"

        sources = tuple(_source_ref(item) for item in declaration.sources)
        known_source_ids = frozenset(item.ref_id for item in sources)
        declaration_source = SourceRef(
            ref_id=declaration_source_id,
            source_uri=f"urn:security-ir:declaration:{declaration.declaration_id}",
            source_id=declaration.declaration_id,
            source_revision=declaration.schema_version,
            content_sha256=declaration_sha256,
            review_status=SourceReviewStatus.MACHINE_EXTRACTED,
            metadata={
                "content_binding": "canonical_security_ir_declaration",
                "declaration_cid": declaration.cid,
                "identity_digest": declaration.digest,
            },
        )

        assumptions: list[Assumption] = []
        bindings: list[ProvenanceBinding] = [
            ProvenanceBinding(
                binding_id=_binding_id(
                    declaration.declaration_id, "declaration"
                ),
                subject_id=declaration.declaration_id,
                source_ref_ids=(declaration_source_id,),
                metadata={
                    "adapter_schema_version": (
                        SECURITY_IR_FORMALIZATION_ADAPTER_VERSION
                    ),
                    "security_construct": "declaration",
                },
            )
        ]

        def bind_node(
            kind: str, record_id: str, source_ids: Sequence[str]
        ) -> tuple[str, tuple[str, ...]]:
            node_id = _input_node_id(kind, record_id)
            refs = _record_sources(
                source_ids,
                known_source_ids=known_source_ids,
                declaration_source_id=declaration_source_id,
            )
            bindings.append(
                ProvenanceBinding(
                    binding_id=_binding_id(node_id, "input"),
                    subject_id=node_id,
                    source_ref_ids=refs,
                    parent_subject_ids=(declaration.declaration_id,),
                    derived=True,
                    metadata={
                        "security_construct": kind,
                        "security_id": record_id,
                    },
                )
            )
            return node_id, refs

        for item in declaration.assumptions:
            node_id, refs = bind_node(
                "assumption", item.assumption_id, item.source_ids
            )
            assumptions.append(
                Assumption(
                    assumption_id=item.assumption_id,
                    statement=item.statement,
                    source_refs=refs,
                    metadata={
                        "attributes": item.to_dict()["attributes"],
                        "security_node_id": node_id,
                    },
                )
            )
        for item in declaration.policies:
            bind_node("policy", item.policy_id, item.source_ids)
        for machine in declaration.state_machines:
            bind_node(
                "state-machine", machine.state_machine_id, machine.source_ids
            )
            for index, transition in enumerate(machine.transitions):
                bind_node(
                    "transition",
                    _transition_key(machine, transition, index),
                    machine.source_ids,
                )
        for item in declaration.claims:
            bind_node("claim", item.claim_id, item.source_ids)
        for item in declaration.extensions:
            bind_node("extension", item.extension_id, item.source_ids)

        payload = {
            "adapter_schema_version": (
                SECURITY_IR_FORMALIZATION_ADAPTER_VERSION
            ),
            "declaration": declaration_payload,
            "declaration_identity": declaration.identity.to_dict(),
            "input_scope": "security_ir_declaration_only",
        }
        provenance = Provenance(
            provenance_id=f"provenance:security:{declaration_sha256[:32]}",
            sources=(*sources, declaration_source),
            bindings=tuple(bindings),
            metadata={
                "adapter_schema_version": (
                    SECURITY_IR_FORMALIZATION_ADAPTER_VERSION
                ),
                "declaration_digest": declaration.digest,
                "result_artifacts_excluded": True,
            },
        )
        return FormalizationSample(
            sample_id=sample_id,
            domain=SECURITY_IR_FORMALIZATION_DOMAIN,
            declaration_id=declaration.declaration_id,
            declaration_digest=declaration.digest,
            payload=payload,
            provenance=provenance,
            source_ref_ids=tuple(item.ref_id for item in provenance.sources),
            assumptions=tuple(assumptions),
            tags=("declaration", "security"),
            metadata={
                "adapter_schema_version": (
                    SECURITY_IR_FORMALIZATION_ADAPTER_VERSION
                ),
                "declaration_cid": declaration.cid,
                "result_artifacts_excluded": True,
            },
        )

    # Common shared-adapter spelling.
    to_formalization_sample = adapt_sample

    def default_config(
        self, sample_or_declaration: FormalizationSample | Any
    ) -> FormalizationCompilerConfig:
        sample = (
            sample_or_declaration
            if isinstance(sample_or_declaration, FormalizationSample)
            else self.adapt_sample(sample_or_declaration)
        )
        declaration = self._sample_declaration(sample)
        targets: set[str] = set()
        if declaration.assumptions:
            targets.add(SECURITY_IR_THREAT_VIEW_ID)
        if declaration.policies:
            targets.add(SECURITY_IR_POLICY_VIEW_ID)
        if declaration.state_machines:
            targets.add(SECURITY_IR_TRANSITION_VIEW_ID)
        if declaration.claims:
            targets.add(SECURITY_IR_CLAIM_VIEW_ID)
        if not targets:
            targets.add(SECURITY_IR_THREAT_VIEW_ID)
        return FormalizationCompilerConfig(
            compiler_id=self.producer_id,
            compiler_version=self.producer_version,
            target_view_ids=tuple(targets),
            config_id=SECURITY_IR_FORMALIZATION_CONFIG_ID,
            producer_id=self.producer_id,
            unsupported_policy=UnsupportedSemanticsPolicy.PRESERVE_OPAQUE,
            options={
                "adapter_schema_version": (
                    SECURITY_IR_FORMALIZATION_ADAPTER_VERSION
                ),
                "proof_backend_execution": False,
                "result_artifacts_are_features": False,
            },
        )

    def compile(
        self,
        sample: FormalizationSample,
        config: FormalizationCompilerConfig,
    ) -> FormalizationArtifact:
        """Compile a Security sample without invoking a solver or proof backend."""

        declaration = self._sample_declaration(sample)
        unknown_views = set(config.target_view_ids) - set(
            self.view_registry.view_ids
        )
        if unknown_views:
            raise SecurityIRFormalizationAdapterError(
                "Security compiler targets unknown views: "
                + ", ".join(sorted(unknown_views))
            )

        source_ids = frozenset(
            item.ref_id for item in sample.provenance.sources
        )
        declaration_source_id = next(
            (
                item.ref_id
                for item in sample.provenance.sources
                if item.metadata.get("content_binding")
                == "canonical_security_ir_declaration"
            ),
            "",
        )
        if not declaration_source_id:
            raise SecurityIRFormalizationAdapterError(
                "Security sample has no canonical declaration source"
            )

        formulas: list[FormalFormula] = []
        symbols: list[FormalSymbol] = []
        obligations: list[ProofObligation] = []
        diagnostics: list[Diagnostic] = []
        bindings = list(sample.provenance.bindings)
        binding_producer_id = config.producer_id or self.producer_id

        def refs_for(source_refs: Sequence[str]) -> tuple[str, ...]:
            return _record_sources(
                source_refs,
                known_source_ids=source_ids,
                declaration_source_id=declaration_source_id,
            )

        def emit(
            *,
            kind: str,
            record_id: str,
            name: str,
            view_id: str,
            expression: Mapping[str, Any],
            source_refs: Sequence[str],
            assumption_ids: Sequence[str] = (),
            metadata: Mapping[str, Any] | None = None,
        ) -> str:
            node_id = _input_node_id(kind, record_id)
            formula_id = _formula_id(kind, record_id)
            symbol_id = _symbol_id(kind, record_id)
            refs = refs_for(source_refs)
            symbol = FormalSymbol(
                symbol_id=symbol_id,
                name=name,
                kind=(
                    "relation"
                    if kind in {"transition", "state-machine"}
                    else "predicate"
                ),
                sort=kind,
                source_ref_ids=refs,
                metadata={
                    "security_construct": kind,
                    "security_id": record_id,
                },
            )
            formula = FormalFormula(
                formula_id=formula_id,
                view_id=view_id,
                expression=expression,
                symbol_ids=(symbol_id,),
                source_ref_ids=refs,
                assumption_ids=tuple(assumption_ids),
                input_node_ids=(node_id,),
                metadata={
                    "security_construct": kind,
                    "security_id": record_id,
                    **dict(metadata or {}),
                },
            )
            symbols.append(symbol)
            formulas.append(formula)
            bindings.extend(
                (
                    ProvenanceBinding(
                        binding_id=_binding_id(symbol_id, "symbol"),
                        subject_id=symbol_id,
                        source_ref_ids=refs,
                        producer_id=binding_producer_id,
                        config_id=config.config_id,
                        parent_subject_ids=(node_id,),
                        derived=True,
                    ),
                    ProvenanceBinding(
                        binding_id=_binding_id(formula_id, "formula"),
                        subject_id=formula_id,
                        source_ref_ids=refs,
                        producer_id=binding_producer_id,
                        config_id=config.config_id,
                        parent_subject_ids=(node_id,),
                        derived=True,
                    ),
                )
            )
            return formula_id

        if SECURITY_IR_THREAT_VIEW_ID in config.target_view_ids:
            for item in declaration.assumptions:
                emit(
                    kind="assumption",
                    record_id=item.assumption_id,
                    name=item.assumption_id,
                    view_id=SECURITY_IR_THREAT_VIEW_ID,
                    expression={
                        "kind": "threat_assumption",
                        "premise": item.to_dict(),
                    },
                    source_refs=item.source_ids,
                    assumption_ids=(item.assumption_id,),
                )

        if SECURITY_IR_POLICY_VIEW_ID in config.target_view_ids:
            for item in declaration.policies:
                emit(
                    kind="policy",
                    record_id=item.policy_id,
                    name=item.name,
                    view_id=SECURITY_IR_POLICY_VIEW_ID,
                    expression={
                        "kind": "security_policy",
                        "modality": item.effect.value,
                        "policy": item.to_dict(),
                    },
                    source_refs=item.source_ids,
                )

        if SECURITY_IR_TRANSITION_VIEW_ID in config.target_view_ids:
            for machine in declaration.state_machines:
                emit(
                    kind="state-machine",
                    record_id=machine.state_machine_id,
                    name=machine.state_machine_id,
                    view_id=SECURITY_IR_TRANSITION_VIEW_ID,
                    expression={
                        "kind": "state_machine",
                        "state_machine": machine.to_dict(),
                    },
                    source_refs=machine.source_ids,
                )
                for index, transition in enumerate(machine.transitions):
                    key = _transition_key(machine, transition, index)
                    emit(
                        kind="transition",
                        record_id=key,
                        name=transition.event,
                        view_id=SECURITY_IR_TRANSITION_VIEW_ID,
                        expression={
                            "index": index,
                            "kind": "state_transition",
                            "state_machine_id": machine.state_machine_id,
                            "transition": transition.to_dict(),
                        },
                        source_refs=machine.source_ids,
                        metadata={
                            "state_machine_id": machine.state_machine_id
                        },
                    )

        if SECURITY_IR_CLAIM_VIEW_ID in config.target_view_ids:
            assumptions_by_id = {
                item.assumption_id: item for item in declaration.assumptions
            }
            policies_by_id = {
                item.policy_id: item for item in declaration.policies
            }
            for item in declaration.claims:
                formula_id = emit(
                    kind="claim",
                    record_id=item.claim_id,
                    name=item.claim_id,
                    view_id=SECURITY_IR_CLAIM_VIEW_ID,
                    expression={
                        "claim": item.to_dict(),
                        "kind": "security_claim",
                    },
                    source_refs=item.source_ids,
                    assumption_ids=item.assumption_ids,
                )
                obligation_semantics = {
                    "assumptions": [
                        assumptions_by_id[identifier].to_dict()
                        for identifier in item.assumption_ids
                    ],
                    "claim": item.to_dict(),
                    "policies": [
                        policies_by_id[identifier].to_dict()
                        for identifier in item.policy_ids
                    ],
                }
                obligations.append(
                    ProofObligation(
                        obligation_id=_derived_id(
                            "obligation:security", item.claim_id
                        ),
                        statement=_canonical_bytes(
                            obligation_semantics
                        ).decode("utf-8"),
                        assumption_ids=item.assumption_ids,
                        logic_family="security_verification_condition",
                        source_refs=refs_for(item.source_ids),
                        metadata={
                            "claim_formula_id": formula_id,
                            "claim_id": item.claim_id,
                            # This binds the expected obligation to the complete
                            # declaration while remaining independent of runs.
                            "declaration_digest": sample.declaration_digest,
                            "semantic_input_sha256": hashlib.sha256(
                                _canonical_bytes(obligation_semantics)
                            ).hexdigest(),
                        },
                    )
                )

        severity = (
            DiagnosticSeverity.ERROR
            if config.strict_unsupported
            else DiagnosticSeverity.WARNING
        )
        for extension in declaration.extensions:
            diagnostics.append(
                self._unsupported_extension_diagnostic(
                    extension,
                    refs=refs_for(extension.source_ids),
                    severity=severity,
                    config=config,
                )
            )

        emitted_views = {item.view_id for item in formulas}
        for view_id in sorted(set(config.target_view_ids) - emitted_views):
            diagnostics.append(
                Diagnostic(
                    code=DiagnosticCode.UNSUPPORTED_FEATURE,
                    message=(
                        "Security declaration contains no construct for "
                        f"requested view {view_id}"
                    ),
                    severity=severity,
                    location=DiagnosticLocation(
                        subject_ids=(declaration.declaration_id,),
                        source_ref_ids=(declaration_source_id,),
                        field_path="/compiler_config/target_view_ids",
                    ),
                    producer_id=binding_producer_id,
                    config_id=config.config_id,
                    metadata={
                        "adapter_schema_version": (
                            SECURITY_IR_FORMALIZATION_ADAPTER_VERSION
                        ),
                        "view_id": view_id,
                    },
                )
            )

        producer = ProducerBinding(
            producer_id=binding_producer_id,
            name="Security IR shared-formalization adapter",
            version=config.compiler_version,
            metadata={"compiler_id": config.compiler_id},
        )
        config_binding = ConfigBinding(
            config_id=config.config_id,
            content_sha256=config.identity.hexdigest,
            schema_id=config.schema_version,
        )
        source_map = Provenance(
            provenance_id=sample.provenance.provenance_id,
            sources=sample.provenance.sources,
            spans=sample.provenance.spans,
            producers=tuple(
                {
                    item.producer_id: item
                    for item in (*sample.provenance.producers, producer)
                }.values()
            ),
            configs=tuple(
                {
                    item.config_id: item
                    for item in (*sample.provenance.configs, config_binding)
                }.values()
            ),
            bindings=tuple(bindings),
            metadata=sample.provenance.metadata,
        )
        report = DiagnosticReport(
            report_id=(
                f"diagnostics:security:{sample.digest[7:23]}:"
                f"{config.digest[7:23]}"
            ),
            diagnostics=tuple(
                sorted(diagnostics, key=lambda item: item.diagnostic_id)
            ),
            provenance_id=source_map.provenance_id,
            producer_id=binding_producer_id,
            config_id=config.config_id,
            metadata={
                "adapter_schema_version": (
                    SECURITY_IR_FORMALIZATION_ADAPTER_VERSION
                ),
                "result_artifacts_excluded": True,
                "unsupported_extension_count": len(declaration.extensions),
            },
        )
        return FormalizationArtifact.from_sample(
            sample,
            compiler_config=config,
            view_registry=self.view_registry,
            symbol_table=SymbolTable(
                table_id=_derived_id(
                    "symbols:security", declaration.declaration_id
                ),
                symbols=tuple(symbols),
                metadata={"domain": SECURITY_IR_FORMALIZATION_DOMAIN},
            ),
            formulas=tuple(formulas),
            proof_obligations=tuple(obligations),
            source_map=source_map,
            diagnostics=report,
            metadata={
                "adapter_schema_version": (
                    SECURITY_IR_FORMALIZATION_ADAPTER_VERSION
                ),
                "declaration_cid": declaration.cid,
                "proof_backend_executed": False,
                "result_artifacts_excluded": True,
            },
        )

    def adapt_artifact(
        self,
        security_declaration: Any,
        config: FormalizationCompilerConfig | None = None,
    ) -> FormalizationArtifact:
        sample = self.adapt_sample(security_declaration)
        return self.compile(sample, config or self.default_config(sample))

    # The complete adaptation is the artifact; source-only users can call
    # ``adapt_sample``/``to_formalization_sample``.
    adapt = adapt_artifact

    def _sample_declaration(
        self, sample: FormalizationSample
    ) -> SecurityIR:
        if (
            not isinstance(sample, FormalizationSample)
            or sample.domain != SECURITY_IR_FORMALIZATION_DOMAIN
        ):
            raise SecurityIRFormalizationAdapterError(
                "SecurityIRFormalizationAdapter requires a Security "
                "FormalizationSample"
            )
        payload = sample.payload.to_dict()
        if (
            payload.get("adapter_schema_version")
            != SECURITY_IR_FORMALIZATION_ADAPTER_VERSION
        ):
            raise SecurityIRFormalizationAdapterError(
                "sample was not produced by this Security adapter schema"
            )
        declaration_payload = payload.get("declaration")
        if not isinstance(declaration_payload, Mapping):
            raise SecurityIRFormalizationAdapterError(
                "Security sample declaration must be a mapping"
            )
        if _contains_result_fields(declaration_payload):
            raise SecurityIRFormalizationAdapterError(
                "Security sample declaration contains result artifacts"
            )
        try:
            declaration = SecurityIR.from_dict(declaration_payload)
        except (TypeError, ValueError) as exc:
            raise SecurityIRFormalizationAdapterError(
                f"invalid Security declaration in sample: {exc}"
            ) from exc
        if declaration.declaration_id != sample.declaration_id:
            raise SecurityIRFormalizationAdapterError(
                "Security sample declaration_id does not match its payload"
            )
        if declaration.digest != sample.declaration_digest:
            raise SecurityIRFormalizationAdapterError(
                "Security sample declaration digest does not match its payload"
            )
        return declaration

    def _unsupported_extension_diagnostic(
        self,
        extension: SecurityExtension,
        *,
        refs: tuple[str, ...],
        severity: DiagnosticSeverity,
        config: FormalizationCompilerConfig,
    ) -> Diagnostic:
        node_id = _input_node_id("extension", extension.extension_id)
        return Diagnostic(
            code=DiagnosticCode.UNSUPPORTED_FEATURE,
            message=(
                f"Security extension {extension.extension_id!r} from vocabulary "
                f"{extension.vocabulary!r} is preserved but has no reviewed "
                "shared-formalization lowering"
            ),
            severity=severity,
            location=DiagnosticLocation(
                subject_ids=(node_id,),
                source_ref_ids=refs,
                field_path="/declaration/extensions",
            ),
            producer_id=config.producer_id or self.producer_id,
            config_id=config.config_id,
            metadata={
                "adapter_schema_version": (
                    SECURITY_IR_FORMALIZATION_ADAPTER_VERSION
                ),
                "construct_id": node_id,
                "extension_id": extension.extension_id,
                "required": extension.required,
                "view_id": "",
                "vocabulary": extension.vocabulary,
                "vocabulary_version": extension.version,
            },
        )


# Architecture-plan shorthand.
SecurityIRAdapter = SecurityIRFormalizationAdapter
SecurityIRAdapterError = SecurityIRFormalizationAdapterError


def adapt_security_ir(
    security_declaration: Any,
    *,
    config: FormalizationCompilerConfig | None = None,
) -> FormalizationArtifact:
    """Functional convenience wrapper for Security IR formalization."""

    return SecurityIRFormalizationAdapter().adapt_artifact(
        security_declaration, config=config
    )


# Legal-adapter-shaped convenience spelling.
adapt_security_sample = adapt_security_ir


__all__ = [
    "SECURITY_IR_ADAPTER_CONFIG_ID",
    "SECURITY_IR_ADAPTER_PRODUCER_ID",
    "SECURITY_IR_CLAIM_VIEW_ID",
    "SECURITY_IR_DOMAIN",
    "SECURITY_IR_FORMALIZATION_ADAPTER_VERSION",
    "SECURITY_IR_FORMALIZATION_CONFIG_ID",
    "SECURITY_IR_FORMALIZATION_DOMAIN",
    "SECURITY_IR_FORMALIZATION_PRODUCER_ID",
    "SECURITY_IR_FORMALIZATION_VIEW_REGISTRY",
    "SECURITY_IR_POLICY_VIEW_ID",
    "SECURITY_IR_THREAT_VIEW_ID",
    "SECURITY_IR_TRANSITION_VIEW_ID",
    "SECURITY_IR_VIEW_REGISTRY",
    "SecurityIRAdapter",
    "SecurityIRAdapterError",
    "SecurityIRFormalizationAdapter",
    "SecurityIRFormalizationAdapterError",
    "adapt_security_ir",
    "adapt_security_sample",
]
