"""Domain adapters that lower Intent and Security views into shared IR.

``IntentSoftwareVerificationAdapter@1`` preserves stable Intent domain
identities while projecting dynamic-Hoare, workflow, safety, and VC fixtures
into :class:`SoftwareVerificationIR`.  ``SecuritySoftwareVerificationAdapter@1``
does the same for transition-system and VC views, optionally enriching from
supervisor code-security observations without elevating them to proof
authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ipfs_datasets_py.logic.families.models import BoundednessKind
from ipfs_datasets_py.logic.ir_core.artifacts import Artifact, ArtifactRole
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticLocation,
    DiagnosticSeverity,
)
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan

from .ir import (
    DeclarationKind,
    SoftwareVerificationIR,
    VerificationBound,
    VerificationDeclaration,
    unsupported_construct_diagnostic,
)
from .properties import (
    AssumptionKind,
    PropertyKind,
    VerificationAssumption,
    VerificationProperty,
)
from .source_adapters import (
    CANONICAL_BACKEND_REQUEST_SCHEMA,
    CanonicalBackendRequest,
    SourceAdapterResult,
    SourceAdapterStatus,
    SourceSoftwareVerificationAdapter,
    adapt_source_to_software_verification,
)


INTENT_SOFTWARE_VERIFICATION_ADAPTER: Final = "IntentSoftwareVerificationAdapter@1"
SECURITY_SOFTWARE_VERIFICATION_ADAPTER: Final = "SecuritySoftwareVerificationAdapter@1"
DOMAIN_ADAPTER_VERSION: Final = "software-verification-domain-adapter/v1"
DOMAIN_ADAPTER_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software-verification/domain-adapter-result@1"
)

_INTENT_KINDS = frozenset({"dynamic_hoare", "workflow", "safety", "vc"})
_SECURITY_KINDS = frozenset({"transition_system", "vc"})


class DomainAdapterError(ValueError):
    """Raised when a domain adaptation request is malformed."""


class DomainKind(str, Enum):
    INTENT = "intent"
    SECURITY = "security"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise DomainAdapterError(
            f"{label} must be a non-empty string without surrounding whitespace"
        )
    if "\x00" in value:
        raise DomainAdapterError(f"{label} must not contain NUL bytes")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DomainAdapterError(f"{label} must be a mapping")
    return value


def _sha256_hex(payload: Any) -> str:
    if isinstance(payload, str):
        data = payload.encode("utf-8")
    elif isinstance(payload, (bytes, bytearray)):
        data = bytes(payload)
    else:
        data = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _safe_id(prefix: str, *parts: str) -> str:
    body = ".".join(str(part).replace(" ", "_") for part in parts if part)
    body = body.strip("._:/-") or "anon"
    candidate = f"{prefix}:{body}"
    if len(candidate) > 256:
        digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:24]
        candidate = f"{prefix}:{digest}"
    return candidate


def _require_domain_identity(value: Mapping[str, Any], *, domain: str) -> str:
    identity = value.get("domain_identity") or value.get("identity") or value.get("id")
    if not isinstance(identity, str) or not identity.strip():
        raise DomainAdapterError(
            f"{domain} fixture requires a stable domain_identity (or identity/id)"
        )
    return identity.strip()


def _source_from_fixture(
    fixture: Mapping[str, Any],
    *,
    domain: str,
    domain_identity: str,
) -> tuple[SourceRef, SourceSpan, str]:
    source_payload = fixture.get("source", {})
    if source_payload and not isinstance(source_payload, Mapping):
        raise DomainAdapterError("source must be a mapping when provided")
    source_payload = source_payload or {}
    text = source_payload.get("text") or source_payload.get("content") or ""
    if not isinstance(text, str):
        text = ""
    path = str(
        source_payload.get("path")
        or fixture.get("path")
        or f"{domain}/{domain_identity.replace(':', '/')}.fixture"
    ).replace("\\", "/")
    digest = (
        str(source_payload.get("content_sha256") or "").strip()
        or _sha256_hex(text or domain_identity)
    )
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
        digest = _sha256_hex(digest)
    ref = SourceRef(
        ref_id=_safe_id("source", domain, domain_identity),
        source_uri=str(source_payload.get("source_uri") or f"fixture://{path}"),
        source_id=str(source_payload.get("source_id") or path.rsplit("/", 1)[-1]),
        source_revision=str(
            source_payload.get("source_revision")
            or fixture.get("revision")
            or f"domain:{domain_identity}"
        ),
        content_sha256=digest.lower(),
        metadata={
            "domain": domain,
            "domain_identity": domain_identity,
            "path": path,
            "byte_length": len(text.encode("utf-8")) if text else 1,
        },
    )
    end_byte = max(1, len(text.encode("utf-8")) if text else 1)
    span = SourceSpan(
        span_id=_safe_id("span", domain, domain_identity, "root"),
        source_ref_id=ref.ref_id,
        start_byte=0,
        end_byte=end_byte,
        start_line=1,
        start_column=1,
        end_line=max(1, text.count("\n") + 1) if text else 1,
        end_column=1,
    )
    return ref, span, text


@dataclass(frozen=True, slots=True)
class DomainAdapterResult:
    """Accounted outcome of one Intent or Security domain lowering."""

    domain: DomainKind | str
    domain_identity: str
    status: SourceAdapterStatus | str
    document: SoftwareVerificationIR | None = None
    source_result: SourceAdapterResult | None = None
    backend_requests: tuple[CanonicalBackendRequest, ...] = ()
    unsupported_constructs: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    interface: str = ""
    adapter_version: str = DOMAIN_ADAPTER_VERSION
    schema: str = DOMAIN_ADAPTER_SCHEMA

    def __post_init__(self) -> None:
        domain = (
            self.domain if isinstance(self.domain, DomainKind) else DomainKind(str(self.domain))
        )
        status = (
            self.status
            if isinstance(self.status, SourceAdapterStatus)
            else SourceAdapterStatus(str(self.status))
        )
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "domain_identity", _text(self.domain_identity, "domain_identity"))
        object.__setattr__(self, "backend_requests", tuple(self.backend_requests))
        object.__setattr__(
            self,
            "unsupported_constructs",
            tuple(sorted(set(self.unsupported_constructs))),
        )
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        if not self.interface:
            default = (
                INTENT_SOFTWARE_VERIFICATION_ADAPTER
                if domain is DomainKind.INTENT
                else SECURITY_SOFTWARE_VERIFICATION_ADAPTER
            )
            object.__setattr__(self, "interface", default)

    @property
    def identity_stable(self) -> bool:
        """True when the fixture domain identity was preserved on the document."""

        if self.document is None:
            return False
        meta = self.document.metadata.to_dict()
        return meta.get("domain_identity") == self.domain_identity

    @property
    def fake_backend_success(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_version": self.adapter_version,
            "backend_requests": [item.to_dict() for item in self.backend_requests],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "document": self.document.to_dict() if self.document is not None else None,
            "domain": self.domain.value,
            "domain_identity": self.domain_identity,
            "fake_backend_success": self.fake_backend_success,
            "identity_stable": self.identity_stable,
            "interface": self.interface,
            "schema": self.schema,
            "source_result": (
                self.source_result.to_dict() if self.source_result is not None else None
            ),
            "status": self.status.value,
            "unsupported_constructs": list(self.unsupported_constructs),
        }


def _intent_kind(fixture: Mapping[str, Any]) -> str:
    kind = str(fixture.get("kind") or fixture.get("view_kind") or "safety").strip()
    if kind not in _INTENT_KINDS:
        raise DomainAdapterError(
            f"intent kind must be one of {sorted(_INTENT_KINDS)}; got {kind!r}"
        )
    return kind


def _security_kind(fixture: Mapping[str, Any]) -> str:
    kind = str(
        fixture.get("kind") or fixture.get("view_kind") or "transition_system"
    ).strip()
    if kind not in _SECURITY_KINDS:
        raise DomainAdapterError(
            f"security kind must be one of {sorted(_SECURITY_KINDS)}; got {kind!r}"
        )
    return kind


def _property_kind_for_intent(kind: str) -> PropertyKind:
    return {
        "dynamic_hoare": PropertyKind.CONTRACT,
        "workflow": PropertyKind.TRACE_CONFORMANCE,
        "safety": PropertyKind.SAFETY,
        "vc": PropertyKind.VALIDITY,
    }[kind]


def _property_kind_for_security(kind: str) -> PropertyKind:
    return {
        "transition_system": PropertyKind.SAFETY,
        "vc": PropertyKind.VALIDITY,
    }[kind]


def _backend_request(
    *,
    domain: str,
    domain_identity: str,
    subject_ids: Sequence[str],
    statement: str,
    source_ref_id: str,
    goal_kind: str,
) -> CanonicalBackendRequest:
    return CanonicalBackendRequest(
        request_id=_safe_id("backend-request", domain, domain_identity, goal_kind),
        goal_kind=goal_kind,
        subject_ids=tuple(subject_ids),
        obligation_statement=statement,
        logic_family="smt" if goal_kind in {"verification_condition", "reachability"} else "shared",
        theory_tags=("equality",),
        source_ref_ids=(source_ref_id,),
        attributes={
            "domain": domain,
            "domain_identity": domain_identity,
            "requires_canonical_backend": True,
            "fake_success_forbidden": True,
            "schema": CANONICAL_BACKEND_REQUEST_SCHEMA,
        },
    )


def adapt_intent_view(
    fixture: Mapping[str, Any],
    *,
    source_adapter: SourceSoftwareVerificationAdapter | None = None,
) -> DomainAdapterResult:
    """Lower an Intent dynamic-Hoare/workflow/safety/VC fixture into shared IR."""

    fixture = _mapping(fixture, "intent fixture")
    domain_identity = _require_domain_identity(fixture, domain="intent")
    kind = _intent_kind(fixture)
    source_ref, span, text = _source_from_fixture(
        fixture, domain="intent", domain_identity=domain_identity
    )
    diagnostics: list[Diagnostic] = []
    unsupported: list[str] = []
    source_result: SourceAdapterResult | None = None

    # Optional embedded source lowering (Python/JS) without changing domain identity.
    if text.strip() and (
        fixture.get("lower_source")
        or str(fixture.get("source", {}).get("language", "")).lower()
        in {"python", "javascript", "typescript", "jsx", "tsx"}
    ):
        language = str(fixture.get("source", {}).get("language") or "python")
        adapter = source_adapter or SourceSoftwareVerificationAdapter()
        source_result = adapter.adapt(
            text,
            path=str(fixture.get("source", {}).get("path") or f"{domain_identity}.py"),
            language=language,
        )
        unsupported.extend(source_result.unsupported_constructs)
        diagnostics.extend(source_result.diagnostics)

    decl_id = _safe_id("decl", "intent", domain_identity)
    declarations: list[VerificationDeclaration] = [
        VerificationDeclaration(
            declaration_id=decl_id,
            kind=DeclarationKind.POLICY if kind in {"workflow", "safety"} else DeclarationKind.CONTRACT,
            name=domain_identity,
            payload={
                "domain": "intent",
                "domain_identity": domain_identity,
                "view_kind": kind,
                "hoare": fixture.get("hoare") or fixture.get("dynamic_hoare") or {},
                "workflow": fixture.get("workflow") or {},
                "safety": fixture.get("safety") or {},
                "vc": fixture.get("vc") or fixture.get("verification_conditions") or {},
            },
            source_ref_ids=(source_ref.ref_id,),
            span_ids=(span.span_id,),
            extensions={"lfv.domain.intent": True},
        )
    ]

    # Preserve nested obligation identifiers as dependent declarations when present.
    for index, obligation in enumerate(fixture.get("obligations") or ()):
        if not isinstance(obligation, Mapping):
            unsupported.append("intent.obligation.malformed")
            continue
        oid = str(
            obligation.get("obligation_id")
            or obligation.get("id")
            or f"{domain_identity}.obligation.{index}"
        )
        declarations.append(
            VerificationDeclaration(
                declaration_id=_safe_id("decl", "intent-obligation", oid),
                kind=DeclarationKind.AXIOM,
                name=oid,
                payload={
                    "domain_identity": domain_identity,
                    "statement": obligation.get("statement") or obligation.get("goal") or "",
                    "kind": obligation.get("kind") or "vc",
                },
                source_ref_ids=(source_ref.ref_id,),
                span_ids=(span.span_id,),
                depends_on=(decl_id,),
            )
        )

    for construct in fixture.get("unsupported") or ():
        name = str(construct)
        unsupported.append(name)
        diagnostics.append(
            unsupported_construct_diagnostic(
                construct=name,
                subject_ids=(decl_id,),
                source_ref_ids=(source_ref.ref_id,),
                span_ids=(span.span_id,),
            )
        )

    assumptions = (
        VerificationAssumption(
            assumption_id=_safe_id("assumption", "intent", domain_identity, "environment"),
            kind=AssumptionKind.ENVIRONMENT,
            statement=(
                "Intent fixture environment assumptions are carried as modeling "
                "premises; they do not authorize completion."
            ),
            expression={"domain": "intent", "domain_identity": domain_identity},
            subject_ids=(decl_id,),
            span_ids=(span.span_id,),
        ),
        VerificationAssumption(
            assumption_id=_safe_id("assumption", "intent", domain_identity, "translation"),
            kind=AssumptionKind.TRANSLATION,
            statement=(
                "Intent domain identity is preserved byte-for-byte in shared IR "
                "metadata; translation does not invent proof."
            ),
            expression={"preservation": "domain_identity"},
            subject_ids=(decl_id,),
            span_ids=(span.span_id,),
        ),
    )
    prop = VerificationProperty(
        property_id=_safe_id("property", "intent", domain_identity, kind),
        kind=_property_kind_for_intent(kind),
        statement=str(
            fixture.get("statement")
            or f"Intent {kind} view for {domain_identity} holds under declared assumptions."
        ),
        expression={
            "domain": "intent",
            "domain_identity": domain_identity,
            "view_kind": kind,
        },
        logic_family="intent",
        subject_ids=(decl_id,),
        assumption_ids=tuple(item.assumption_id for item in assumptions),
        source_ref_ids=(source_ref.ref_id,),
        span_ids=(span.span_id,),
        extensions={"lfv.domain.intent": True},
    )
    bound = VerificationBound(
        bound_id=_safe_id("bound", "intent", domain_identity),
        kind=BoundednessKind.NOT_APPLICABLE
        if kind != "vc"
        else BoundednessKind.STEP_BOUNDED,
        limits={} if kind != "vc" else {"max_vc_steps": int(fixture.get("max_vc_steps") or 64)},
        description="Intent view bound carried into shared IR.",
        source_ref_ids=(source_ref.ref_id,),
    )
    if kind == "vc":
        prop = VerificationProperty(
            property_id=prop.property_id,
            kind=prop.kind,
            statement=prop.statement,
            expression=prop.expression,
            logic_family=prop.logic_family,
            subject_ids=prop.subject_ids,
            assumption_ids=prop.assumption_ids,
            bound_ids=(bound.bound_id,),
            source_ref_ids=prop.source_ref_ids,
            span_ids=prop.span_ids,
            extensions=prop.extensions,
        )

    backend_requests = (
        _backend_request(
            domain="intent",
            domain_identity=domain_identity,
            subject_ids=(decl_id,),
            statement=(
                f"Discharge Intent {kind} obligations for {domain_identity} through "
                "canonical shared backends; adapter success is not a prover verdict."
            ),
            source_ref_id=source_ref.ref_id,
            goal_kind="verification_condition" if kind in {"vc", "dynamic_hoare"} else "safety",
        ),
    )
    if source_result is not None:
        backend_requests = backend_requests + source_result.backend_requests

    artifact = Artifact(
        artifact_id=_safe_id("artifact", "intent", domain_identity),
        role=ArtifactRole.INPUT,
        content_sha256=source_ref.content_sha256,
        size=max(1, int(source_ref.metadata.get("byte_length", 1))),
        path=str(source_ref.metadata.get("path") or f"intent/{domain_identity}.json"),
        media_type="application/json",
        schema_id="intent-software-verification-fixture",
        schema_version="v1",
        metadata={"domain_identity": domain_identity, "view_kind": kind},
    )
    document = SoftwareVerificationIR(
        sources=(source_ref,),
        spans=(span,),
        declarations=tuple(declarations),
        properties=(prop,),
        assumptions=assumptions,
        bounds=(bound,),
        diagnostics=tuple(diagnostics),
        artifacts=(artifact,),
        metadata={
            "domain": "intent",
            "domain_identity": domain_identity,
            "view_kind": kind,
            "adapter": INTENT_SOFTWARE_VERIFICATION_ADAPTER,
        },
        extensions={
            "lfv.domain.intent": True,
            "lfv.domain.identity": domain_identity,
        },
        observations={
            "adapter_version": DOMAIN_ADAPTER_VERSION,
            "backend_requests": [item.to_dict() for item in backend_requests],
            "source_adapter_status": (
                source_result.status.value if source_result is not None else None
            ),
        },
    )
    status = SourceAdapterStatus.SUCCESS
    if unsupported or (source_result is not None and source_result.status is not SourceAdapterStatus.SUCCESS):
        status = SourceAdapterStatus.PARTIAL
    return DomainAdapterResult(
        domain=DomainKind.INTENT,
        domain_identity=domain_identity,
        status=status,
        document=document,
        source_result=source_result,
        backend_requests=backend_requests,
        unsupported_constructs=tuple(unsupported),
        diagnostics=tuple(diagnostics),
        interface=INTENT_SOFTWARE_VERIFICATION_ADAPTER,
    )


def _load_code_security_facts():
    try:
        from ipfs_accelerate_py.agent_supervisor.code_security_facts import (  # type: ignore
            CodeSecurityFactSet,
            extract_code_security_facts,
        )
    except Exception:  # pragma: no cover
        return None, None
    return CodeSecurityFactSet, extract_code_security_facts


def adapt_security_view(
    fixture: Mapping[str, Any],
    *,
    changed_diff: Any = None,
) -> DomainAdapterResult:
    """Lower a Security transition-system/VC fixture into shared IR."""

    fixture = _mapping(fixture, "security fixture")
    domain_identity = _require_domain_identity(fixture, domain="security")
    kind = _security_kind(fixture)
    source_ref, span, _text_body = _source_from_fixture(
        fixture, domain="security", domain_identity=domain_identity
    )
    diagnostics: list[Diagnostic] = []
    unsupported: list[str] = []
    security_observation: Mapping[str, Any] | None = None

    CodeSecurityFactSet, extract_code_security_facts = _load_code_security_facts()
    if changed_diff is not None and extract_code_security_facts is not None:
        try:
            fact_set = extract_code_security_facts(changed_diff)
            security_observation = (
                fact_set.to_dict() if hasattr(fact_set, "to_dict") else dict(fact_set)
            )
            # Observations never authorize completion or elevate to proof.
            if security_observation and security_observation.get("status") not in {
                None,
                "extracted",
                "partial",
            }:
                unsupported.append("security.facts.incomplete")
        except Exception as exc:  # keep fail-closed for bad diffs without aborting fixture
            diagnostics.append(
                Diagnostic(
                    code=DiagnosticCode.VALIDATION_FAILED,
                    message=f"code security fact extraction failed: {exc}",
                    severity=DiagnosticSeverity.WARNING,
                    location=DiagnosticLocation(
                        subject_ids=(source_ref.ref_id,),
                        source_ref_ids=(source_ref.ref_id,),
                    ),
                )
            )
            unsupported.append("security.facts.extraction_failed")

    decl_id = _safe_id("decl", "security", domain_identity)
    states = fixture.get("states") or fixture.get("state_variables") or ()
    transitions = fixture.get("transitions") or fixture.get("actions") or ()
    if not isinstance(states, Sequence) or isinstance(states, (str, bytes, bytearray)):
        raise DomainAdapterError("states must be a sequence when provided")
    if not isinstance(transitions, Sequence) or isinstance(
        transitions, (str, bytes, bytearray)
    ):
        raise DomainAdapterError("transitions must be a sequence when provided")

    declarations: list[VerificationDeclaration] = [
        VerificationDeclaration(
            declaration_id=decl_id,
            kind=DeclarationKind.STATE if kind == "transition_system" else DeclarationKind.CONTRACT,
            name=domain_identity,
            payload={
                "domain": "security",
                "domain_identity": domain_identity,
                "view_kind": kind,
                "state_count": len(tuple(states)),
                "transition_count": len(tuple(transitions)),
                "vc": fixture.get("vc") or fixture.get("verification_conditions") or {},
            },
            source_ref_ids=(source_ref.ref_id,),
            span_ids=(span.span_id,),
            extensions={"lfv.domain.security": True},
        )
    ]

    for index, state in enumerate(states):
        if not isinstance(state, Mapping):
            unsupported.append("security.state.malformed")
            continue
        sid = str(state.get("state_id") or state.get("id") or f"state.{index}")
        declarations.append(
            VerificationDeclaration(
                declaration_id=_safe_id("decl", "security-state", domain_identity, sid),
                kind=DeclarationKind.STATE,
                name=sid,
                payload={
                    "domain_identity": domain_identity,
                    "label": state.get("label") or sid,
                    "variables": state.get("variables") or {},
                },
                source_ref_ids=(source_ref.ref_id,),
                span_ids=(span.span_id,),
                depends_on=(decl_id,),
            )
        )

    for index, transition in enumerate(transitions):
        if not isinstance(transition, Mapping):
            unsupported.append("security.transition.malformed")
            continue
        tid = str(
            transition.get("transition_id")
            or transition.get("action_id")
            or transition.get("id")
            or f"transition.{index}"
        )
        declarations.append(
            VerificationDeclaration(
                declaration_id=_safe_id("decl", "security-transition", domain_identity, tid),
                kind=DeclarationKind.TRANSITION,
                name=tid,
                payload={
                    "domain_identity": domain_identity,
                    "source": transition.get("source") or transition.get("from"),
                    "target": transition.get("target") or transition.get("to"),
                    "guard": transition.get("guard") or {},
                    "effect": transition.get("effect") or transition.get("action") or {},
                },
                source_ref_ids=(source_ref.ref_id,),
                span_ids=(span.span_id,),
                depends_on=(decl_id,),
            )
        )

    for construct in fixture.get("unsupported") or ():
        name = str(construct)
        unsupported.append(name)
        diagnostics.append(
            unsupported_construct_diagnostic(
                construct=name,
                subject_ids=(decl_id,),
                source_ref_ids=(source_ref.ref_id,),
                span_ids=(span.span_id,),
            )
        )

    assumptions = (
        VerificationAssumption(
            assumption_id=_safe_id("assumption", "security", domain_identity, "attacker"),
            kind=AssumptionKind.ENVIRONMENT,
            statement=(
                "Security fixture attacker/environment model is an explicit premise; "
                "code-security facts remain observational."
            ),
            expression={"domain": "security", "domain_identity": domain_identity},
            subject_ids=(decl_id,),
            span_ids=(span.span_id,),
        ),
        VerificationAssumption(
            assumption_id=_safe_id("assumption", "security", domain_identity, "authority"),
            kind=AssumptionKind.TRUST,
            statement=(
                "Supervisor code-security fact extraction never grants proof or "
                "completion authority."
            ),
            expression={"code_security_authoritative": False},
            subject_ids=(decl_id,),
            span_ids=(span.span_id,),
        ),
    )
    prop = VerificationProperty(
        property_id=_safe_id("property", "security", domain_identity, kind),
        kind=_property_kind_for_security(kind),
        statement=str(
            fixture.get("statement")
            or f"Security {kind} view for {domain_identity} is source-bound and obligation-ready."
        ),
        expression={
            "domain": "security",
            "domain_identity": domain_identity,
            "view_kind": kind,
        },
        logic_family="security",
        subject_ids=(decl_id,),
        assumption_ids=tuple(item.assumption_id for item in assumptions),
        source_ref_ids=(source_ref.ref_id,),
        span_ids=(span.span_id,),
        extensions={"lfv.domain.security": True},
    )
    bound = VerificationBound(
        bound_id=_safe_id("bound", "security", domain_identity),
        kind=BoundednessKind.STEP_BOUNDED,
        limits={"max_transitions": int(fixture.get("max_transitions") or max(len(tuple(transitions)), 1))},
        description="Security transition exploration bound.",
        source_ref_ids=(source_ref.ref_id,),
    )
    prop = VerificationProperty(
        property_id=prop.property_id,
        kind=prop.kind,
        statement=prop.statement,
        expression=prop.expression,
        logic_family=prop.logic_family,
        subject_ids=prop.subject_ids,
        assumption_ids=prop.assumption_ids,
        bound_ids=(bound.bound_id,),
        source_ref_ids=prop.source_ref_ids,
        span_ids=prop.span_ids,
        extensions=prop.extensions,
    )
    backend_requests = (
        _backend_request(
            domain="security",
            domain_identity=domain_identity,
            subject_ids=(decl_id,),
            statement=(
                f"Check Security {kind} reachability/VC obligations for "
                f"{domain_identity} via canonical backends; never treat fact "
                "extraction as proof."
            ),
            source_ref_id=source_ref.ref_id,
            goal_kind="reachability" if kind == "transition_system" else "verification_condition",
        ),
    )
    artifact = Artifact(
        artifact_id=_safe_id("artifact", "security", domain_identity),
        role=ArtifactRole.INPUT,
        content_sha256=source_ref.content_sha256,
        size=max(1, int(source_ref.metadata.get("byte_length", 1))),
        path=str(source_ref.metadata.get("path") or f"security/{domain_identity}.json"),
        media_type="application/json",
        schema_id="security-software-verification-fixture",
        schema_version="v1",
        metadata={"domain_identity": domain_identity, "view_kind": kind},
    )
    observations: dict[str, Any] = {
        "adapter_version": DOMAIN_ADAPTER_VERSION,
        "backend_requests": [item.to_dict() for item in backend_requests],
        "code_security_authoritative": False,
    }
    if security_observation is not None:
        observations["code_security_fact_set"] = {
            "status": security_observation.get("status"),
            "fact_count": len(security_observation.get("facts") or ()),
            "diagnostic_count": len(security_observation.get("diagnostics") or ()),
            "tree_id": security_observation.get("tree_id"),
            "diff_id": security_observation.get("diff_id"),
        }
    document = SoftwareVerificationIR(
        sources=(source_ref,),
        spans=(span,),
        declarations=tuple(declarations),
        properties=(prop,),
        assumptions=assumptions,
        bounds=(bound,),
        diagnostics=tuple(diagnostics),
        artifacts=(artifact,),
        metadata={
            "domain": "security",
            "domain_identity": domain_identity,
            "view_kind": kind,
            "adapter": SECURITY_SOFTWARE_VERIFICATION_ADAPTER,
        },
        extensions={
            "lfv.domain.security": True,
            "lfv.domain.identity": domain_identity,
        },
        observations=observations,
    )
    status = (
        SourceAdapterStatus.PARTIAL if unsupported or diagnostics else SourceAdapterStatus.SUCCESS
    )
    return DomainAdapterResult(
        domain=DomainKind.SECURITY,
        domain_identity=domain_identity,
        status=status,
        document=document,
        backend_requests=backend_requests,
        unsupported_constructs=tuple(unsupported),
        diagnostics=tuple(diagnostics),
        interface=SECURITY_SOFTWARE_VERIFICATION_ADAPTER,
    )


@dataclass(frozen=True, slots=True)
class IntentSoftwareVerificationAdapter:
    """Stable interface object for ``IntentSoftwareVerificationAdapter@1``."""

    interface: str = INTENT_SOFTWARE_VERIFICATION_ADAPTER
    version: str = DOMAIN_ADAPTER_VERSION

    def adapt(self, fixture: Mapping[str, Any]) -> DomainAdapterResult:
        return adapt_intent_view(fixture)


@dataclass(frozen=True, slots=True)
class SecuritySoftwareVerificationAdapter:
    """Stable interface object for ``SecuritySoftwareVerificationAdapter@1``."""

    interface: str = SECURITY_SOFTWARE_VERIFICATION_ADAPTER
    version: str = DOMAIN_ADAPTER_VERSION

    def adapt(
        self,
        fixture: Mapping[str, Any],
        *,
        changed_diff: Any = None,
    ) -> DomainAdapterResult:
        return adapt_security_view(fixture, changed_diff=changed_diff)


__all__ = [
    "DOMAIN_ADAPTER_SCHEMA",
    "DOMAIN_ADAPTER_VERSION",
    "INTENT_SOFTWARE_VERIFICATION_ADAPTER",
    "SECURITY_SOFTWARE_VERIFICATION_ADAPTER",
    "DomainAdapterError",
    "DomainAdapterResult",
    "DomainKind",
    "IntentSoftwareVerificationAdapter",
    "SecuritySoftwareVerificationAdapter",
    "adapt_intent_view",
    "adapt_security_view",
    "adapt_source_to_software_verification",
]
