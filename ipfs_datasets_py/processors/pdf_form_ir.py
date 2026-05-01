"""Form Knowledge Graph and Legal Intermediate Representation (IR).

This module bridges the PDF form layer and the deontic logic layer:

1. :class:`FormKnowledgeGraph` — a richer semantic graph on top of
   :class:`~ipfs_datasets_py.processors.pdf_form_filler.FormDependencyGraph`
   that adds entity, concept, and constraint nodes alongside the existing
   field nodes.

2. :class:`FormToLegalIR` — converts a ``FormKnowledgeGraph`` (or a plain
   :class:`~ipfs_datasets_py.processors.pdf_form_filler.FormAnalysisResult`)
   into a :class:`~ipfs_datasets_py.logic.integration.converters.deontic_logic_core.DeonticRuleSet`
   suitable for formal verification.

3. :func:`build_form_knowledge_graph` — convenience wrapper that calls
   :func:`~ipfs_datasets_py.processors.pdf_form_filler.analyze_pdf_form` and
   enriches the result with concept and statute nodes.

Design principles
-----------------
* **No hard dependencies** on the logic sub-package at import time; everything
  is imported lazily so the module can be used without the full logic stack.
* **Graceful degradation** — statute linking and entity extraction fall back
  to empty collections when optional dependencies are unavailable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Node / edge kind constants
# ---------------------------------------------------------------------------

NODE_KIND_FIELD = "field"
NODE_KIND_ENTITY = "entity"
NODE_KIND_CONCEPT = "concept"
NODE_KIND_CONSTRAINT = "constraint"
NODE_KIND_STATUTE = "statute"
NODE_KIND_DATA_TYPE = "data_type"

EDGE_EXPECTS_TYPE = "expects_type"
EDGE_DEPENDS_ON = "depends_on"
EDGE_COMPUTED_FROM = "computed_from"
EDGE_GOVERNED_BY = "governed_by"
EDGE_MENTIONS = "mentions"
EDGE_CONSTRAINS = "constrains"

# ---------------------------------------------------------------------------
# Statute / citation patterns
# ---------------------------------------------------------------------------

_STATUTE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(\d+)\s+U\.?S\.?C\.?\s+[§§]*\s*(\d[\d\-a-z()]*)", re.IGNORECASE),
    re.compile(r"\bIRC\s+[§§]*\s*(\d[\d\-a-z()]*)", re.IGNORECASE),
    re.compile(r"\bI\.?R\.?C\.?\s+[§§]*\s*(\d[\d\-a-z()]*)", re.IGNORECASE),
    re.compile(r"\bC\.?F\.?R\.?\s+[§§]*\s*(\d[\d\-a-z.()]*)", re.IGNORECASE),
    re.compile(r"\b(\d+)\s+C\.?F\.?R\.?\s+(?:Part|§)\s*(\d[\d\-a-z.()]*)", re.IGNORECASE),
    re.compile(r"\bPublic\s+Law\s+(\d+-\d+)", re.IGNORECASE),
]

# Form-purpose keywords mapped to concept labels
_FORM_PURPOSE_KEYWORDS: list[tuple[str, str]] = [
    ("tax return", "tax_return"),
    ("income tax", "income_tax"),
    ("rental agreement", "rental_agreement"),
    ("lease agreement", "rental_agreement"),
    ("building permit", "building_permit"),
    ("employment application", "employment_application"),
    ("benefit application", "benefit_application"),
    ("insurance claim", "insurance_claim"),
    ("medical form", "medical_form"),
    ("financial aid", "financial_aid"),
    ("visa application", "visa_application"),
    ("passport application", "passport_application"),
    ("deed", "property_deed"),
    ("power of attorney", "power_of_attorney"),
    ("consent form", "consent_form"),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class KGNode:
    """A node in the :class:`FormKnowledgeGraph`."""

    node_id: str
    kind: str  # one of NODE_KIND_* constants
    label: str
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "label": self.label,
            "properties": self.properties,
        }


@dataclass
class KGEdge:
    """A directed edge in the :class:`FormKnowledgeGraph`."""

    source_id: str
    target_id: str
    relation: str
    confidence: float = 1.0
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation": self.relation,
            "confidence": self.confidence,
            "properties": self.properties,
        }


@dataclass
class FormKnowledgeGraph:
    """Semantic knowledge graph for a PDF form.

    Nodes
    -----
    * **field** — one node per :class:`FormFieldSpec`; properties mirror the
      spec (data_type, required, page_index, rect, …).
    * **entity** — named persons, organisations, or roles extracted from the
      form's instructional text.
    * **concept** — the form's high-level purpose (e.g. "tax_return"),
      jurisdiction, and governing statute references.
    * **constraint** — conditional rules extracted from the form text (e.g.
      "If yes, complete Part II").
    * **data_type** — one node per distinct data type; field nodes point to
      their data-type node via ``"expects_type"`` edges.
    * **statute** — legal citations extracted from the form text.
    """

    form_id: str
    source_pdf: str
    nodes: Dict[str, KGNode] = field(default_factory=dict)
    edges: List[KGEdge] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    def add_node(self, node: KGNode) -> None:
        self.nodes[node.node_id] = node

    def add_edge(self, edge: KGEdge) -> None:
        self.edges.append(edge)

    def get_nodes_by_kind(self, kind: str) -> List[KGNode]:
        return [n for n in self.nodes.values() if n.kind == kind]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "form_id": self.form_id,
            "source_pdf": self.source_pdf,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
            "metadata": self.metadata,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------

def _extract_statutes(text: str) -> List[Tuple[str, str]]:
    """Return list of (statute_id, matched_text) pairs from *text*."""
    results: List[Tuple[str, str]] = []
    for pattern in _STATUTE_PATTERNS:
        for m in pattern.finditer(text):
            matched = m.group(0).strip()
            statute_id = "statute:" + re.sub(r"\s+", "_", matched.lower())
            results.append((statute_id, matched))
    return results


def _extract_form_concepts(text: str) -> List[str]:
    """Return list of form-purpose concept labels found in *text*."""
    text_lower = text.lower()
    return [concept for keyword, concept in _FORM_PURPOSE_KEYWORDS if keyword in text_lower]


def _extract_conditional_constraints(text: str) -> List[Tuple[str, str]]:
    """Heuristically extract conditional rules from form instructions."""
    patterns = [
        re.compile(r"if\s+(.{5,60}?),\s+(?:then\s+)?(.{5,80})", re.IGNORECASE),
        re.compile(r"(?:complete|fill in|attach)\s+(.{5,60}?)\s+if\s+(.{5,80})", re.IGNORECASE),
        re.compile(r"required\s+(?:only\s+)?if\s+(.{5,80})", re.IGNORECASE),
    ]
    constraints: List[Tuple[str, str]] = []
    for pat in patterns:
        for m in pat.finditer(text):
            groups = m.groups()
            antecedent = groups[0].strip() if groups else ""
            consequent = groups[1].strip() if len(groups) > 1 else ""
            if antecedent:
                constraint_text = m.group(0).strip()
                cid = "constraint:" + hashlib.md5(constraint_text.encode()).hexdigest()[:8]
                constraints.append((cid, constraint_text))
    return constraints


def build_form_knowledge_graph(
    analysis: Any,  # FormAnalysisResult
    *,
    page_texts: Optional[Sequence[str]] = None,
    jurisdiction: Optional[str] = None,
) -> "FormKnowledgeGraph":
    """Build a :class:`FormKnowledgeGraph` from a
    :class:`~ipfs_datasets_py.processors.pdf_form_filler.FormAnalysisResult`.

    Args:
        analysis: The ``FormAnalysisResult`` returned by ``analyze_pdf_form()``.
        page_texts: Override the page text used for concept/statute extraction.
            Defaults to ``analysis.page_text``.
        jurisdiction: Optional jurisdiction string (e.g. ``"US/Federal"``).

    Returns:
        A populated :class:`FormKnowledgeGraph`.
    """
    texts: Sequence[str] = page_texts or analysis.page_text
    full_text = "\n".join(texts)

    form_id = "form:" + hashlib.md5(str(analysis.source_pdf).encode()).hexdigest()[:10]
    kg = FormKnowledgeGraph(
        form_id=form_id,
        source_pdf=str(analysis.source_pdf),
        metadata={
            "page_count": analysis.metadata.get("page_count", 0),
            "field_count": analysis.metadata.get("field_count", 0),
            "jurisdiction": jurisdiction,
        },
    )

    # ------------------------------------------------------------------
    # 1. Field nodes
    # ------------------------------------------------------------------
    for spec in analysis.fields:
        fnode = KGNode(
            node_id=f"field:{spec.name}",
            kind=NODE_KIND_FIELD,
            label=spec.label,
            properties={
                "name": spec.name,
                "data_type": spec.data_type,
                "required": spec.required,
                "page_index": spec.page_index,
                "rect": list(spec.rect),
                "max_chars": spec.max_chars,
                "font_size": spec.font_size,
                "source": spec.source,
                "confidence": spec.confidence,
                "multiline": spec.multiline,
                "options": list(spec.options),
            },
        )
        kg.add_node(fnode)

        # Data-type node
        dt_id = f"type:{spec.data_type}"
        if dt_id not in kg.nodes:
            kg.add_node(KGNode(node_id=dt_id, kind=NODE_KIND_DATA_TYPE, label=spec.data_type))
        kg.add_edge(KGEdge(fnode.node_id, dt_id, EDGE_EXPECTS_TYPE, confidence=0.95))

    # Dependency edges from the existing FormDependencyGraph
    for edge in (analysis.dependency_graph.edges or ()):
        src = f"field:{edge.source}"
        tgt = f"field:{edge.target}"
        if src in kg.nodes and tgt in kg.nodes:
            kg.add_edge(KGEdge(src, tgt, edge.relation, confidence=edge.confidence))

    # ------------------------------------------------------------------
    # 2. Concept nodes (form purpose)
    # ------------------------------------------------------------------
    for concept_label in _extract_form_concepts(full_text):
        cnode = KGNode(
            node_id=f"concept:{concept_label}",
            kind=NODE_KIND_CONCEPT,
            label=concept_label,
            properties={"jurisdiction": jurisdiction},
        )
        kg.add_node(cnode)
        # Link all fields to the concept
        for spec in analysis.fields:
            kg.add_edge(KGEdge(f"field:{spec.name}", cnode.node_id, EDGE_GOVERNED_BY, confidence=0.6))

    # ------------------------------------------------------------------
    # 3. Statute nodes
    # ------------------------------------------------------------------
    for statute_id, statute_text in _extract_statutes(full_text):
        if statute_id not in kg.nodes:
            kg.add_node(
                KGNode(
                    node_id=statute_id,
                    kind=NODE_KIND_STATUTE,
                    label=statute_text,
                    properties={"citation": statute_text, "jurisdiction": jurisdiction},
                )
            )
        # Link concept nodes to statute
        for concept_node in kg.get_nodes_by_kind(NODE_KIND_CONCEPT):
            kg.add_edge(KGEdge(concept_node.node_id, statute_id, EDGE_GOVERNED_BY, confidence=0.7))

    # ------------------------------------------------------------------
    # 4. Constraint nodes
    # ------------------------------------------------------------------
    for constraint_id, constraint_text in _extract_conditional_constraints(full_text):
        if constraint_id not in kg.nodes:
            kg.add_node(
                KGNode(
                    node_id=constraint_id,
                    kind=NODE_KIND_CONSTRAINT,
                    label=constraint_text,
                    properties={"raw_text": constraint_text},
                )
            )
        # Link all fields to constraints (coarse; a future version can parse
        # the constraint text to identify specific fields)
        for spec in analysis.fields:
            label_lower = constraint_text.lower()
            if spec.label.lower() in label_lower or spec.name in label_lower:
                kg.add_edge(
                    KGEdge(constraint_id, f"field:{spec.name}", EDGE_CONSTRAINS, confidence=0.55)
                )

    return kg


# ---------------------------------------------------------------------------
# FormToLegalIR
# ---------------------------------------------------------------------------

class FormToLegalIR:
    """Convert a :class:`FormKnowledgeGraph` (or a raw
    :class:`~ipfs_datasets_py.processors.pdf_form_filler.FormAnalysisResult`)
    into a deontic ``DeonticRuleSet`` suitable for formal verification.

    Mapping rules
    -------------
    * **Required field** → ``O(fill(field_name))`` (obligation)
    * **Optional field** → ``P(fill(field_name))`` (permission)
    * **Conditional field** (has ``depends_on`` edge) →
      ``O(fill(B)) ← check(A)`` encoded as a conditional in the formula
    * **Computed field** (currency field with ``computed_from`` edges) →
      ``O(total = sum(amounts))`` as a deterministic rule
    * **Constraint node** → obligation derived from the constraint text

    Import note
    -----------
    The deontic logic sub-package is imported lazily to avoid hard coupling.
    If it is unavailable, :meth:`to_rule_set` raises ``ImportError``.
    """

    def __init__(
        self,
        *,
        jurisdiction: Optional[str] = None,
        confidence_threshold: float = 0.5,
    ) -> None:
        self.jurisdiction = jurisdiction
        self.confidence_threshold = confidence_threshold

    # ------------------------------------------------------------------

    def from_analysis(self, analysis: Any) -> "FormKnowledgeGraph":
        """Build the KG from a ``FormAnalysisResult`` and return it."""
        return build_form_knowledge_graph(analysis, jurisdiction=self.jurisdiction)

    # ------------------------------------------------------------------

    def to_rule_set(self, kg: "FormKnowledgeGraph") -> Any:
        """Convert *kg* to a ``DeonticRuleSet``.

        Returns
        -------
        ``DeonticRuleSet``

        Raises
        ------
        ImportError
            If the ``ipfs_datasets_py.logic`` sub-package is not available.
        """
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticFormula,
            DeonticOperator,
            DeonticRuleSet,
            LegalContext,
        )

        legal_ctx = LegalContext(
            jurisdiction=self.jurisdiction or "",
            legal_domain="form_compliance",
            applicable_law=kg.source_pdf,
        ) if True else None

        formulas: list[DeonticFormula] = []

        # Collect dependency edges for quick lookup
        dep_map: dict[str, list[str]] = {}  # field → [antecedent fields]
        computed_from: dict[str, list[str]] = {}
        for edge in kg.edges:
            if edge.relation == EDGE_DEPENDS_ON and edge.source_id.startswith("field:"):
                dep_map.setdefault(edge.source_id, []).append(edge.target_id)
            elif edge.relation == EDGE_COMPUTED_FROM and edge.source_id.startswith("field:"):
                computed_from.setdefault(edge.source_id, []).append(edge.target_id)

        for node in kg.get_nodes_by_kind(NODE_KIND_FIELD):
            field_name = node.properties.get("name", node.node_id.replace("field:", ""))
            prop = f"fill({field_name})"
            is_required = bool(node.properties.get("required", False))
            operator = DeonticOperator.OBLIGATION if is_required else DeonticOperator.PERMISSION

            antecedents = dep_map.get(node.node_id, [])
            conditions: list[str] = []
            for ant in antecedents:
                ant_name = ant.replace("field:", "")
                conditions.append(f"check({ant_name})")

            # Computed / total fields get a special obligation
            sources = computed_from.get(node.node_id, [])
            if sources:
                source_names = [s.replace("field:", "") for s in sources]
                prop = f"{field_name} = sum({', '.join(source_names)})"
                operator = DeonticOperator.OBLIGATION

            formula = DeonticFormula(
                operator=operator,
                proposition=prop,
                conditions=conditions,
                confidence=float(node.properties.get("confidence", 1.0)),
                source_text=node.label,
                legal_context=legal_ctx,
                variables={"field": field_name, "data_type": node.properties.get("data_type", "string")},
            )
            formulas.append(formula)

        # Constraint-derived obligations
        for node in kg.get_nodes_by_kind(NODE_KIND_CONSTRAINT):
            raw_text = node.properties.get("raw_text", node.label)
            formula = DeonticFormula(
                operator=DeonticOperator.OBLIGATION,
                proposition=f"satisfy_constraint({node.node_id})",
                conditions=[],
                confidence=0.55,
                source_text=raw_text,
                legal_context=legal_ctx,
            )
            formulas.append(formula)

        rule_set = DeonticRuleSet(
            name=f"form:{kg.form_id}",
            formulas=formulas,
            description=f"Auto-generated from PDF form {kg.source_pdf}",
            source_document=kg.source_pdf,
            legal_context=legal_ctx,
        )
        return rule_set


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def pdf_to_legal_ir(
    pdf_path: str | Path,
    *,
    jurisdiction: Optional[str] = None,
    ocr_provider: Any = None,
    layout_provider: Any = None,
    vlm_field_provider: Any = None,
) -> Tuple["FormKnowledgeGraph", Any]:
    """One-shot helper: parse a PDF, build its KG, and return (kg, rule_set).

    Returns
    -------
    tuple[FormKnowledgeGraph, DeonticRuleSet]

    Raises
    ------
    ImportError
        If ``ipfs_datasets_py.logic`` is unavailable (``DeonticRuleSet`` cannot
        be constructed).
    """
    from ipfs_datasets_py.processors.pdf_form_filler import analyze_pdf_form  # lazy

    kwargs: dict[str, Any] = {}
    if ocr_provider is not None:
        kwargs["ocr_provider"] = ocr_provider
    if layout_provider is not None:
        kwargs["layout_provider"] = layout_provider
    if vlm_field_provider is not None:
        kwargs["vlm_field_provider"] = vlm_field_provider

    analysis = analyze_pdf_form(pdf_path, **kwargs)
    converter = FormToLegalIR(jurisdiction=jurisdiction)
    kg = converter.from_analysis(analysis)
    rule_set = converter.to_rule_set(kg)
    return kg, rule_set


__all__ = [
    "EDGE_COMPUTED_FROM",
    "EDGE_CONSTRAINS",
    "EDGE_DEPENDS_ON",
    "EDGE_EXPECTS_TYPE",
    "EDGE_GOVERNED_BY",
    "EDGE_MENTIONS",
    "FormKnowledgeGraph",
    "FormToLegalIR",
    "KGEdge",
    "KGNode",
    "NODE_KIND_CONCEPT",
    "NODE_KIND_CONSTRAINT",
    "NODE_KIND_DATA_TYPE",
    "NODE_KIND_ENTITY",
    "NODE_KIND_FIELD",
    "NODE_KIND_STATUTE",
    "build_form_knowledge_graph",
    "pdf_to_legal_ir",
]
