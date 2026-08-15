"""LPC-041: legal domain adapter conformance (TDFOL, DCEC, frame logic).

Acceptance:

* Adapter declares source domain, view, family/profile, property, notation,
  preserved/lost semantics, assumptions, unsupported constructs, proof-safety,
  and counterexample-safety.
* TDFOL, DCEC, and frame logic stay pairwise distinct and never collapse to
  generic FOL, monadic deontic alone, or untyped object framing.
* Each adapter lowers through an admitted DomainLogicSlice@2.

Durable note:
``data/agent_supervisor/logic_platform_canonicalization/notes/legal_domain_adapter.md``
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

import pytest

from ipfs_datasets_py.logic.families.namespaces import (
    family_id,
    notation_id,
    profile_id,
    property_id,
    view_id,
)
from ipfs_datasets_py.logic.families.registry import DEFAULT_REGISTRY
from ipfs_datasets_py.logic.formalization.artifacts_v3 import (
    DOMAIN_LOGIC_SLICE_V2_INTERFACE,
    DomainLogicSliceV2,
    DomainSliceAdmissionError,
    DomainSliceStatus,
)
from ipfs_datasets_py.logic.legal_ir.typed_adapter import (
    LEGAL_FORMALIZATION_ADAPTER_INTERFACE,
    LEGAL_LOGIC_ROUTE_CATALOG,
    NEVER_FAMILY_OPERATION_ROLES,
    ProofAuthorityRole,
    RouteNamespace,
    resolve_legal_route,
)
from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression, mk_predicate
from ipfs_datasets_py.logic.syntax_core.contracts import SourceDocument, SourceRange
from ipfs_datasets_py.logic.syntax_core.signatures import propositional_signature


# ---------------------------------------------------------------------------
# Paths and required declaration inventory
# ---------------------------------------------------------------------------


def _legal_domain_adapter_note() -> Path:
    note_relative = Path(
        "data/agent_supervisor/logic_platform_canonicalization/notes/"
        "legal_domain_adapter.md"
    )
    search_roots = (
        *Path(__file__).resolve().parents,
        Path.cwd().resolve(),
        *Path.cwd().resolve().parents,
    )
    seen: set[Path] = set()
    for root in search_roots:
        if root in seen:
            continue
        seen.add(root)
        candidate = root / note_relative
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[5] / note_relative


# LPC-041 acceptance fields every adapter must declare.
REQUIRED_ADAPTER_FIELDS: Final[tuple[str, ...]] = (
    "source_domain",
    "view",
    "family",
    "profile",
    "property",
    "notation",
    "preserved_semantics",
    "lost_semantics",
    "assumptions",
    "unsupported_constructs",
    "proof_safe",
    "counterexample_safe",
)

# Forbidden silent collapse targets (conflict policy).
FORBIDDEN_COLLAPSE_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        "first_order",
        "fol",
        "predicate_logic",
        "deontic",  # generic monadic/dyadic deontic alone is not TDFOL/DCEC/frame
        "object_framing",
        "object",
        "graph_projection",
        "knowledge_graphs",
    }
)

LEGAL_SOURCE_DOMAIN: Final = "legal"
LEGAL_IR_DOMAIN: Final = "legal_ir"


# ---------------------------------------------------------------------------
# Sealed adapter declarations (LPC-041 gate surface)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegalDomainAdapterDeclaration:
    """One legal domain adapter conformance record for DomainLogicSlice@2."""

    adapter_id: str
    source_domain: str
    view: str
    family: str
    profile: str
    property: str
    notation: str
    preserved_semantics: tuple[str, ...]
    lost_semantics: tuple[str, ...]
    assumptions: tuple[str, ...]
    unsupported_constructs: tuple[str, ...]
    proof_safe: bool
    counterexample_safe: bool
    features: tuple[str, ...]
    route_labels: tuple[str, ...]
    forbidden_collapse: tuple[str, ...]
    description: str = ""

    def __post_init__(self) -> None:
        if not self.adapter_id or not self.adapter_id.strip():
            raise ValueError("adapter_id must be non-empty")
        if self.source_domain not in {LEGAL_SOURCE_DOMAIN, LEGAL_IR_DOMAIN}:
            raise ValueError(
                f"source_domain must be legal/legal_ir; got {self.source_domain!r}"
            )
        for field_name in (
            "view",
            "family",
            "profile",
            "property",
            "notation",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        for field_name in (
            "preserved_semantics",
            "lost_semantics",
            "assumptions",
            "unsupported_constructs",
            "features",
            "route_labels",
            "forbidden_collapse",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or not value:
                raise ValueError(f"{field_name} must be a non-empty tuple")
        if not isinstance(self.proof_safe, bool):
            raise ValueError("proof_safe must be a bool")
        if not isinstance(self.counterexample_safe, bool):
            raise ValueError("counterexample_safe must be a bool")
        # Ontology non-collapse: declared family cannot be a forbidden target.
        if self.family in FORBIDDEN_COLLAPSE_FAMILIES:
            raise ValueError(
                f"adapter family {self.family!r} is a forbidden collapse target"
            )
        if self.family in NEVER_FAMILY_OPERATION_ROLES:
            raise ValueError(
                f"adapter family {self.family!r} is an operation role, not a family"
            )
        if self.family not in DEFAULT_REGISTRY.families:
            raise ValueError(
                f"adapter family {self.family!r} is not a registered semantic family"
            )
        # Family must not equal any of its own forbidden collapse targets.
        if self.family in self.forbidden_collapse:
            raise ValueError(
                f"adapter family {self.family!r} listed in its own forbidden_collapse"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "adapter_id": self.adapter_id,
            "assumptions": list(self.assumptions),
            "counterexample_safe": self.counterexample_safe,
            "description": self.description,
            "family": self.family,
            "features": list(self.features),
            "forbidden_collapse": list(self.forbidden_collapse),
            "lost_semantics": list(self.lost_semantics),
            "notation": self.notation,
            "preserved_semantics": list(self.preserved_semantics),
            "profile": self.profile,
            "proof_safe": self.proof_safe,
            "property": self.property,
            "route_labels": list(self.route_labels),
            "source_domain": self.source_domain,
            "unsupported_constructs": list(self.unsupported_constructs),
            "view": self.view,
        }

    def require_declaration_complete(self) -> "LegalDomainAdapterDeclaration":
        """Fail closed if any LPC-041 acceptance field is missing on the wire."""

        payload = self.to_dict()
        for field_name in REQUIRED_ADAPTER_FIELDS:
            if field_name not in payload:
                raise ValueError(f"missing declaration field {field_name}")
            value = payload[field_name]
            if value is None or value == "" or value == []:
                raise ValueError(f"declaration field {field_name} is empty")
        return self


def _declaration(**kwargs: object) -> LegalDomainAdapterDeclaration:
    return LegalDomainAdapterDeclaration(**kwargs)  # type: ignore[arg-type]


LEGAL_DOMAIN_ADAPTER_CATALOG: Final[tuple[LegalDomainAdapterDeclaration, ...]] = (
    _declaration(
        adapter_id="legal-adapter/tdfol/v1",
        source_domain=LEGAL_SOURCE_DOMAIN,
        view="tdfol",
        family="tdfol",
        profile="temporal_first_order",
        property="validity",
        notation="canonical_text",
        preserved_semantics=(
            "quantifier_scope",
            "temporal_anchor",
            "event_order",
            "deontic_force",
            "predicate_identity",
            "source_expression_digest",
        ),
        lost_semantics=(
            "dense_time_metrics",
            "unreviewed_natural_language_gloss",
            "kernel_theorem_authority",
            "infinite_trace_fairness",
        ),
        assumptions=(
            "asm:legal-domain",
            "asm:tdfol-temporal-first-order",
            "asm:finite-discrete-time",
            "asm:candidate-authority-ceiling",
        ),
        unsupported_constructs=(
            "unanchored_temporal_operator",
            "free_form_logic_family_metadata",
            "operation_role_as_family",
            "natural_language_only_claim",
        ),
        proof_safe=False,
        counterexample_safe=True,
        features=("first_order", "legal_ir", "tdfol", "temporal"),
        route_labels=("tdfol", "TDFOL", "temporal_first_order"),
        forbidden_collapse=(
            "first_order",
            "fol",
            "deontic",
            "object_framing",
            "graph_projection",
        ),
        description=(
            "Typed first-order temporal legal formula with explicit time anchors; "
            "never silently rewritten as bare FOL."
        ),
    ),
    _declaration(
        adapter_id="legal-adapter/dcec/v1",
        source_domain=LEGAL_SOURCE_DOMAIN,
        view="dcec",
        family="dcec",
        profile="dcec_default",
        property="reachability",
        notation="canonical_text",
        preserved_semantics=(
            "event_identity",
            "fluent_identity",
            "transition_direction",
            "time_anchor",
            "composition_deontic_event_modal",
            "source_expression_digest",
        ),
        lost_semantics=(
            "continuous_fluents",
            "unbounded_cognitive_nesting",
            "silent_rewrite_to_monadic_deontic",
            "kernel_theorem_authority",
        ),
        assumptions=(
            "asm:legal-domain",
            "asm:dcec-composition",
            "asm:event-fluent-identity",
            "asm:candidate-authority-ceiling",
        ),
        unsupported_constructs=(
            "event_without_fluent_or_time_anchor",
            "collapse_to_pure_deontic",
            "operation_role_as_family",
            "unversioned_multi_family_string",
        ),
        proof_safe=False,
        counterexample_safe=True,
        features=("dcec", "event", "fluent", "legal_ir"),
        route_labels=("dcec", "cec", "event_calculus", "CEC.native"),
        forbidden_collapse=(
            "deontic",
            "first_order",
            "fol",
            "object_framing",
            "graph_projection",
        ),
        description=(
            "DCEC retained composition identity over deontic + event_calculus + "
            "modal components; never collapsed to generic deontic or FOL."
        ),
    ),
    _declaration(
        adapter_id="legal-adapter/frame-logic/v1",
        source_domain=LEGAL_SOURCE_DOMAIN,
        view="frame_logic",
        family="frame_logic",
        profile="typed_frame",
        property="validity",
        notation="canonical_text",
        preserved_semantics=(
            "typed_role",
            "relation_direction",
            "selected_frame_id",
            "modal_operator_attachment",
            "exception_scope",
            "source_expression_digest",
        ),
        lost_semantics=(
            "untyped_object_bags",
            "graph_projection_operation_role",
            "kernel_theorem_authority",
            "full_flogic_inheritance_paths",
        ),
        assumptions=(
            "asm:legal-domain",
            "asm:frame-typed-roles",
            "asm:advisory-authority-ceiling",
        ),
        unsupported_constructs=(
            "object_framing_without_typed_roles",
            "graph_projection_as_family",
            "free_form_flogic_payload",
            "advisory_to_theorem_promotion",
        ),
        proof_safe=False,
        counterexample_safe=False,
        features=("frame_logic", "legal_ir", "typed_role"),
        route_labels=("frame_logic", "flogic", "modal.frame_logic"),
        forbidden_collapse=(
            "object_framing",
            "object",
            "first_order",
            "deontic",
            "graph_projection",
            "knowledge_graphs",
        ),
        description=(
            "Typed frame roles and relations; advisory evidence; never untyped "
            "object framing or graph-projection-as-family."
        ),
    ),
)

LEGAL_DOMAIN_ADAPTER_BY_ID: Final[Mapping[str, LegalDomainAdapterDeclaration]] = {
    item.adapter_id: item for item in LEGAL_DOMAIN_ADAPTER_CATALOG
}

LEGAL_DOMAIN_ADAPTER_BY_FAMILY: Final[Mapping[str, LegalDomainAdapterDeclaration]] = {
    item.family: item for item in LEGAL_DOMAIN_ADAPTER_CATALOG
}


class LegalDomainAdapterError(ValueError):
    """Raised when a legal domain adapter lowering request is invalid."""


def legal_domain_adapters() -> tuple[LegalDomainAdapterDeclaration, ...]:
    """Return the sealed LPC-041 legal domain adapter catalog."""

    return LEGAL_DOMAIN_ADAPTER_CATALOG


def get_legal_domain_adapter(family_or_id: str) -> LegalDomainAdapterDeclaration:
    """Resolve an adapter by family id or adapter_id; fail closed."""

    text = str(family_or_id or "").strip()
    if not text:
        raise LegalDomainAdapterError("adapter identity must be non-empty")
    if text in LEGAL_DOMAIN_ADAPTER_BY_ID:
        return LEGAL_DOMAIN_ADAPTER_BY_ID[text]
    if text in LEGAL_DOMAIN_ADAPTER_BY_FAMILY:
        return LEGAL_DOMAIN_ADAPTER_BY_FAMILY[text]
    # Common aliases.
    aliases = {
        "TDFOL": "tdfol",
        "temporal_first_order": "tdfol",
        "DCEC": "dcec",
        "cec": "dcec",
        "event_calculus": "dcec",
        "flogic": "frame_logic",
        "f_logic": "frame_logic",
        "modal.frame_logic": "frame_logic",
    }
    mapped = aliases.get(text, aliases.get(text.lower(), ""))
    if mapped and mapped in LEGAL_DOMAIN_ADAPTER_BY_FAMILY:
        return LEGAL_DOMAIN_ADAPTER_BY_FAMILY[mapped]
    raise LegalDomainAdapterError(f"unknown legal domain adapter {text!r}")


def _expression_for_adapter(
    adapter: LegalDomainAdapterDeclaration,
    *,
    expression_id: str,
    atom: str,
) -> TypedExpression:
    signature = propositional_signature(
        f"sig:legal-adapter:{adapter.family}",
        (atom,),
        family=adapter.family,
        profile=adapter.profile,
    )
    return TypedExpression(
        expression_id=expression_id,
        root=mk_predicate(f"n:legal-adapter:{adapter.family}", atom),
        signature=signature,
        family=family_id(adapter.family),
        profile=profile_id(adapter.profile),
        range=SourceRange(start=0, end=max(1, len(atom))),
    )


def lower_legal_domain_adapter(
    family_or_id: str,
    *,
    document: SourceDocument | None = None,
    statement: str = "",
    slice_id: str = "",
    expression_id: str = "",
    domain: str = LEGAL_IR_DOMAIN,
    unsupported: bool = False,
) -> DomainLogicSliceV2:
    """Lower one legal adapter declaration into a DomainLogicSlice@2.

    Fail-closed.  Refuses forbidden family collapse and operation-role families.
    When *unsupported* is True, stamps unsupported_constructs and status
    ``unsupported``; otherwise admits with empty unsupported_extensions.
    """

    adapter = get_legal_domain_adapter(family_or_id)
    adapter.require_declaration_complete()

    if adapter.family in FORBIDDEN_COLLAPSE_FAMILIES:
        raise LegalDomainAdapterError(
            f"refusing collapse family {adapter.family!r}"
        )
    if adapter.family in NEVER_FAMILY_OPERATION_ROLES:
        raise LegalDomainAdapterError(
            f"refusing operation role as family {adapter.family!r}"
        )

    body = statement or f"{adapter.family}_legal_claim"
    if document is None:
        document = SourceDocument.from_text(
            f"doc:legal-adapter:{adapter.family}",
            body,
            encoding="utf-8",
        )
    expr_id = expression_id or f"expr:legal-adapter:{adapter.family}"
    atom = "".join(ch if ch.isalnum() else "_" for ch in adapter.family.title()) or "Claim"
    if atom[0].isdigit():
        atom = f"F_{atom}"
    expression = _expression_for_adapter(adapter, expression_id=expr_id, atom=atom)

    sid = slice_id or f"slice:legal-adapter:{adapter.family}"
    view_value = view_id(adapter.view)
    if unsupported:
        return DomainLogicSliceV2(
            slice_id=sid,
            domain=domain,
            document_id=document.document_id,
            source_digest=document.content_digest,
            expression_id=expression.expression_id,
            expression_digest=expression.content_digest,
            family=family_id(adapter.family),
            profile=profile_id(adapter.profile),
            property=property_id(adapter.property),
            view=view_value,
            notation=notation_id(adapter.notation),
            status=DomainSliceStatus.UNSUPPORTED,
            source_range=SourceRange(start=0, end=min(len(body), 64)),
            features=adapter.features,
            assumption_ids=adapter.assumptions,
            unsupported_extensions=adapter.unsupported_constructs,
            metadata={
                "adapter_id": adapter.adapter_id,
                "proof_safe": adapter.proof_safe,
                "counterexample_safe": adapter.counterexample_safe,
                "producer": "lpc-041-legal-domain-adapter",
            },
        )

    slice_item = DomainLogicSliceV2.from_typed_expression(
        expression,
        slice_id=sid,
        domain=domain,
        document_id=document.document_id,
        source_digest=document.content_digest,
        property=property_id(adapter.property),
        view=view_value,
        notation=notation_id(adapter.notation),
        status=DomainSliceStatus.ADMITTED,
        source_range=SourceRange(start=0, end=min(len(body), 64)),
        features=adapter.features,
        assumption_ids=adapter.assumptions,
        unsupported_extensions=(),
        metadata={
            "adapter_id": adapter.adapter_id,
            "adapter_view": adapter.view,
            "proof_safe": adapter.proof_safe,
            "counterexample_safe": adapter.counterexample_safe,
            "preserved_semantics": list(adapter.preserved_semantics),
            "lost_semantics": list(adapter.lost_semantics),
            "producer": "lpc-041-legal-domain-adapter",
        },
    )
    return slice_item.require_admitted()


# ---------------------------------------------------------------------------
# Note presence
# ---------------------------------------------------------------------------


def test_legal_domain_adapter_note_declares_required_fields() -> None:
    note_path = _legal_domain_adapter_note()
    assert note_path.is_file(), f"missing {note_path}"
    text = note_path.read_text(encoding="utf-8")
    assert "LPC-041" in text
    assert "DomainLogicSlice@2" in text
    for family in ("TDFOL", "DCEC", "frame logic", "tdfol", "dcec", "frame_logic"):
        assert family in text or family.lower() in text.lower()
    for token in (
        "source domain",
        "view",
        "family",
        "profile",
        "property",
        "notation",
        "preserved",
        "lost",
        "assumptions",
        "unsupported",
        "proof-safety",
        "counterexample-safety",
    ):
        assert token.lower() in text.lower(), f"note missing declaration topic {token!r}"
    # Non-collapse rules named explicitly.
    assert "first_order" in text or "FOL" in text
    assert "deontic" in text.lower()
    assert "object framing" in text.lower() or "object_framing" in text


# ---------------------------------------------------------------------------
# Catalog integrity
# ---------------------------------------------------------------------------


def test_catalog_covers_tdfol_dcec_frame_logic_exactly() -> None:
    adapters = legal_domain_adapters()
    families = {item.family for item in adapters}
    assert families == {"tdfol", "dcec", "frame_logic"}
    assert len(adapters) == 3
    assert len({item.adapter_id for item in adapters}) == 3
    for item in adapters:
        item.require_declaration_complete()
        for field_name in REQUIRED_ADAPTER_FIELDS:
            assert field_name in item.to_dict()


def test_families_are_pairwise_distinct_and_registered() -> None:
    families = [item.family for item in LEGAL_DOMAIN_ADAPTER_CATALOG]
    assert len(families) == len(set(families))
    for family in families:
        assert family in DEFAULT_REGISTRY.families
        assert family not in FORBIDDEN_COLLAPSE_FAMILIES
        assert family not in NEVER_FAMILY_OPERATION_ROLES


def test_no_adapter_collapses_to_fol_deontic_or_object_framing() -> None:
    for adapter in LEGAL_DOMAIN_ADAPTER_CATALOG:
        assert adapter.family not in {
            "first_order",
            "fol",
            "deontic",
            "object_framing",
            "object",
        }
        for forbidden in adapter.forbidden_collapse:
            assert adapter.family != forbidden
        # Explicitly reject the three conflict-policy collapses for every adapter.
        assert "first_order" in adapter.forbidden_collapse or "fol" in adapter.forbidden_collapse
        assert "deontic" in adapter.forbidden_collapse
        assert (
            "object_framing" in adapter.forbidden_collapse
            or "object" in adapter.forbidden_collapse
        )


@pytest.mark.parametrize(
    "family",
    ["tdfol", "dcec", "frame_logic"],
)
def test_each_adapter_declares_full_acceptance_inventory(family: str) -> None:
    adapter = get_legal_domain_adapter(family)
    payload = adapter.to_dict()
    assert payload["source_domain"] == LEGAL_SOURCE_DOMAIN
    assert payload["view"]
    assert payload["family"] == family
    assert payload["profile"]
    assert payload["property"]
    assert payload["notation"] == "canonical_text"
    assert payload["preserved_semantics"]
    assert payload["lost_semantics"]
    assert payload["assumptions"]
    assert payload["unsupported_constructs"]
    assert isinstance(payload["proof_safe"], bool)
    assert isinstance(payload["counterexample_safe"], bool)


def test_proof_and_counterexample_safety_polarity() -> None:
    tdfol = get_legal_domain_adapter("tdfol")
    dcec = get_legal_domain_adapter("dcec")
    frame = get_legal_domain_adapter("frame_logic")
    # Candidate/advisory ceilings: no adapter is kernel proof-safe.
    assert tdfol.proof_safe is False
    assert dcec.proof_safe is False
    assert frame.proof_safe is False
    # Finite temporal/event fragments may surface checkable counterexamples.
    assert tdfol.counterexample_safe is True
    assert dcec.counterexample_safe is True
    # Frame structure is advisory only.
    assert frame.counterexample_safe is False


# ---------------------------------------------------------------------------
# DomainLogicSlice@2 lowering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family", ["tdfol", "dcec", "frame_logic"])
def test_lower_admits_domain_logic_slice_v2(family: str) -> None:
    adapter = get_legal_domain_adapter(family)
    document = SourceDocument.from_text(
        f"doc:lpc041:{family}",
        f"legal claim for {family}",
        encoding="utf-8",
    )
    slice_item = lower_legal_domain_adapter(
        family,
        document=document,
        statement=f"legal claim for {family}",
    )

    assert isinstance(slice_item, DomainLogicSliceV2)
    assert slice_item.interface == DOMAIN_LOGIC_SLICE_V2_INTERFACE
    assert slice_item.is_admitted
    assert slice_item.status is DomainSliceStatus.ADMITTED
    assert slice_item.domain == LEGAL_IR_DOMAIN
    assert slice_item.document_id == document.document_id
    assert slice_item.source_digest == document.content_digest
    assert slice_item.expression_id
    assert len(slice_item.expression_digest) == 64
    assert slice_item.family.value == family
    assert slice_item.profile.value == adapter.profile
    assert slice_item.property.value == adapter.property
    assert slice_item.view.value == adapter.view
    assert slice_item.notation.value == adapter.notation
    assert slice_item.unsupported_extensions == ()
    for assumption in adapter.assumptions:
        assert assumption in slice_item.assumption_ids
    for feature in adapter.features:
        assert feature in slice_item.features
    assert len(slice_item.content_digest) == 64
    # Safety flags are bound in metadata (not free-form routing keys).
    assert slice_item.metadata["adapter_id"] == adapter.adapter_id
    assert slice_item.metadata["proof_safe"] is adapter.proof_safe
    assert slice_item.metadata["counterexample_safe"] is adapter.counterexample_safe
    assert slice_item.metadata["preserved_semantics"] == list(adapter.preserved_semantics)
    assert slice_item.metadata["lost_semantics"] == list(adapter.lost_semantics)


def test_three_adapters_produce_distinct_family_slices() -> None:
    slices = [
        lower_legal_domain_adapter(family)
        for family in ("tdfol", "dcec", "frame_logic")
    ]
    family_values = [item.family.value for item in slices]
    assert family_values == ["tdfol", "dcec", "frame_logic"]
    assert len(set(family_values)) == 3
    # None may be rewritten to FOL / deontic / object framing.
    for value in family_values:
        assert value not in FORBIDDEN_COLLAPSE_FAMILIES


def test_unsupported_constructs_force_unsupported_status() -> None:
    adapter = get_legal_domain_adapter("tdfol")
    slice_item = lower_legal_domain_adapter("tdfol", unsupported=True)
    assert slice_item.status is DomainSliceStatus.UNSUPPORTED
    assert slice_item.is_admitted is False
    assert set(adapter.unsupported_constructs).issubset(
        set(slice_item.unsupported_extensions)
    )
    with pytest.raises(DomainSliceAdmissionError):
        slice_item.require_admitted()


def test_unknown_adapter_fails_closed() -> None:
    with pytest.raises(LegalDomainAdapterError, match="unknown"):
        get_legal_domain_adapter("not_a_legal_adapter_xyz")
    with pytest.raises(LegalDomainAdapterError, match="unknown"):
        lower_legal_domain_adapter("object_framing")


# ---------------------------------------------------------------------------
# Route catalog alignment (non-collapse vs typed routes)
# ---------------------------------------------------------------------------


def test_tdfol_and_frame_routes_keep_distinct_families() -> None:
    tdfol_route = resolve_legal_route("tdfol")
    frame_route = resolve_legal_route("frame_logic")
    fol_route = resolve_legal_route("first_order")
    deontic_route = resolve_legal_route("deontic")

    assert tdfol_route.family_id == "tdfol"
    assert frame_route.family_id == "frame_logic"
    assert fol_route.family_id == "first_order"
    assert deontic_route.family_id == "deontic"
    assert tdfol_route.family_id != fol_route.family_id
    assert tdfol_route.family_id != deontic_route.family_id
    assert frame_route.family_id != fol_route.family_id
    assert frame_route.family_id != deontic_route.family_id
    assert tdfol_route.family_id != frame_route.family_id


def test_dcec_alias_does_not_resolve_to_generic_deontic_or_fol() -> None:
    # Catalog may route the dcec alias to the CEC.native / event_calculus
    # component; it must not resolve to bare deontic or FOL.
    route = resolve_legal_route("dcec")
    assert route.family_id not in {"deontic", "first_order", "fol"}
    assert route.family_id in {"event_calculus", "dcec"}
    # Adapter declaration retains composition family dcec on the slice.
    adapter = get_legal_domain_adapter("dcec")
    assert adapter.family == "dcec"
    slice_item = lower_legal_domain_adapter("dcec")
    assert slice_item.family.value == "dcec"
    assert slice_item.family.value != "deontic"
    assert slice_item.family.value != "first_order"


def test_frame_logic_route_is_advisory_not_proof() -> None:
    route = resolve_legal_route("frame_logic")
    adapter = get_legal_domain_adapter("frame_logic")
    assert route.proof_authority is ProofAuthorityRole.ADVISORY
    assert adapter.proof_safe is False
    assert adapter.counterexample_safe is False


def test_operation_roles_never_appear_as_adapter_families() -> None:
    for adapter in LEGAL_DOMAIN_ADAPTER_CATALOG:
        assert adapter.family not in NEVER_FAMILY_OPERATION_ROLES
    for route in LEGAL_LOGIC_ROUTE_CATALOG:
        if route.namespace is RouteNamespace.VIEW_ROLE:
            assert route.family_id == ""
            assert route.view_role_id
            assert route.view_role_id not in {
                item.family for item in LEGAL_DOMAIN_ADAPTER_CATALOG
            }


def test_formalization_adapter_interface_still_present() -> None:
    # Cross-check dependency surface used by legal domain lowering.
    assert LEGAL_FORMALIZATION_ADAPTER_INTERFACE == "LegalFormalizationAdapter@2"
    assert DOMAIN_LOGIC_SLICE_V2_INTERFACE == "DomainLogicSlice@2"


def test_alias_resolution_for_common_labels() -> None:
    assert get_legal_domain_adapter("TDFOL").family == "tdfol"
    assert get_legal_domain_adapter("temporal_first_order").family == "tdfol"
    assert get_legal_domain_adapter("DCEC").family == "dcec"
    assert get_legal_domain_adapter("cec").family == "dcec"
    assert get_legal_domain_adapter("flogic").family == "frame_logic"
    assert get_legal_domain_adapter("legal-adapter/tdfol/v1").family == "tdfol"


def test_declaration_fields_match_acceptance_criteria() -> None:
    """Gate the LPC-041 acceptance field inventory against silent shrinkage."""

    required = set(REQUIRED_ADAPTER_FIELDS)
    for adapter in LEGAL_DOMAIN_ADAPTER_CATALOG:
        payload = adapter.to_dict()
        assert required.issubset(payload.keys())
        assert payload["source_domain"] in {LEGAL_SOURCE_DOMAIN, LEGAL_IR_DOMAIN}
        assert payload["family"] in {"tdfol", "dcec", "frame_logic"}
        assert payload["proof_safe"] is False
        assert isinstance(payload["counterexample_safe"], bool)
        assert payload["preserved_semantics"]
        assert payload["lost_semantics"]
        assert payload["assumptions"]
        assert payload["unsupported_constructs"]
