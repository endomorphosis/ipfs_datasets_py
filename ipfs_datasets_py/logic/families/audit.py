"""Deterministic audit of canonical and free-form family identifiers.

``LogicFamilyAudit@1`` classifies every observed family-like string against the
pure default family registry and explicit non-family namespaces.  It never
imports solvers, probes the environment, or renames production strings.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from .registry import (
    DEFAULT_REGISTRY,
    LogicFamilyRegistry,
    LogicFamilyRegistryError,
    normalize_family_name,
)

AUDIT_SCHEMA_VERSION: Final = "logic-family-audit/v1"
AUDIT_INTERFACE: Final = "LogicFamilyAudit@1"
AUDIT_REPORT_VERSION: Final = "1.0.0"

# Relative to the ipfs_datasets_py package root (parent of ``logic/``).
DEFAULT_AUDIT_ROOTS: Final[tuple[str, ...]] = (
    "logic/backends",
    "logic/formalization",
    "logic/security_ir",
    "logic/crypto_ir",
    "logic/intent_ir",
    "logic/legal_ir",
    "logic/software_verification",
    "logic/families",
)

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$", re.IGNORECASE)
_FAMILY_CONTEXT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "family",
        "families",
        "family_id",
        "logic_family",
        "logic_families",
        "source_family",
        "target_family",
        "source_family_id",
        "target_family_id",
        "predicted_logic_family",
        "target_logic_family",
        "attempt_family",
        "source_format",
    }
)


class FamilyLabelKind(StrEnum):
    """Namespace role of an observed family-like label."""

    CANONICAL_FAMILY = "canonical_family"
    ALIAS = "alias"
    PROFILE = "profile"
    PROPERTY = "property"
    VIEW = "view"
    NOTATION = "notation"
    PROVIDER = "provider"
    LANE = "lane"
    EVIDENCE_KIND = "evidence_kind"
    UNKNOWN = "unknown"


class DriftSeverity(StrEnum):
    """How seriously a non-canonical label should be treated."""

    NONE = "none"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class LabelClassification:
    """Typed disposition for one observed family-like string."""

    observed: str
    normalized: str
    kind: FamilyLabelKind
    canonical_family_id: str | None = None
    notes: str = ""
    is_semantic_family: bool = False
    severity: DriftSeverity = DriftSeverity.NONE

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_family_id": self.canonical_family_id,
            "is_semantic_family": self.is_semantic_family,
            "kind": self.kind.value,
            "normalized": self.normalized,
            "notes": self.notes,
            "observed": self.observed,
            "severity": self.severity.value,
        }


@dataclass(frozen=True, slots=True)
class LabelObservation:
    """One occurrence of a family-like string under a configured root."""

    label: str
    source: str
    root: str
    line: int | None = None
    context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": self.context,
            "label": self.label,
            "line": self.line,
            "root": self.root,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class LogicFamilyAuditReport:
    """Deterministic ``LogicFamilyAudit@1`` envelope."""

    classifications: tuple[LabelClassification, ...]
    observations: tuple[LabelObservation, ...]
    drift: tuple[dict[str, Any], ...]
    roots: tuple[str, ...]
    canonical_family_ids: tuple[str, ...]
    summary: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = AUDIT_SCHEMA_VERSION
    interface: str = AUDIT_INTERFACE
    report_version: str = AUDIT_REPORT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_family_ids": list(self.canonical_family_ids),
            "classifications": [item.to_dict() for item in self.classifications],
            "drift": list(self.drift),
            "interface": self.interface,
            "observations": [item.to_dict() for item in self.observations],
            "report_version": self.report_version,
            "roots": list(self.roots),
            "schema_version": self.schema_version,
            "summary": dict(self.summary),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        separators = None if indent is not None else (",", ":")
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            indent=indent,
            separators=separators,
            sort_keys=True,
        ) + ("\n" if indent is not None else "")


# Explicit non-family dispositions from the logic-family parser plan.  These
# labels must never be treated as semantic families even if free-form code
# places them in a ``logic_families`` field.
_KNOWN_NON_FAMILY: Final[dict[str, tuple[FamilyLabelKind, str | None, str]]] = {
    # notations / encodings
    "smt": (FamilyLabelKind.NOTATION, None, "SMT notation/profile, not a family"),
    "smtlib2": (FamilyLabelKind.NOTATION, None, "SMT-LIB2 notation"),
    "smt_lib": (FamilyLabelKind.NOTATION, None, "SMT-LIB notation"),
    "smt-lib": (FamilyLabelKind.NOTATION, None, "SMT-LIB notation"),
    "smt-lib2": (FamilyLabelKind.NOTATION, None, "SMT-LIB2 notation"),
    "tptp": (FamilyLabelKind.NOTATION, None, "TPTP notation"),
    "pv": (
        FamilyLabelKind.NOTATION,
        "cryptographic_protocol",
        "ProVerif source notation, not a family",
    ),
    "spthy": (
        FamilyLabelKind.NOTATION,
        "cryptographic_protocol",
        "Tamarin source notation, not a family",
    ),
    "tla": (
        FamilyLabelKind.NOTATION,
        "transition_system",
        "TLA notation, not a family",
    ),
    "tla_plus": (
        FamilyLabelKind.PROFILE,
        "transition_system",
        "TLA+ profile over transition_system",
    ),
    "tla+": (
        FamilyLabelKind.PROFILE,
        "transition_system",
        "TLA+ profile over transition_system",
    ),
    "hyperltl": (
        FamilyLabelKind.PROFILE,
        "hyperproperty",
        "HyperLTL profile under hyperproperty",
    ),
    "secpal": (
        FamilyLabelKind.PROFILE,
        "authorization",
        "SecPAL profile under authorization",
    ),
    "policy": (
        FamilyLabelKind.PROFILE,
        "authorization",
        "policy profile under authorization",
    ),
    "qf_bv": (FamilyLabelKind.PROFILE, "first_order", "SMT QF_BV fragment/profile"),
    "quantifier_free": (
        FamilyLabelKind.PROFILE,
        "first_order",
        "quantifier-free first-order profile",
    ),
    "finite_fragment": (
        FamilyLabelKind.PROFILE,
        "first_order",
        "bounded finite first-order fragment",
    ),
    "horn": (FamilyLabelKind.PROFILE, "horn_chc", "Horn profile"),
    "s4": (FamilyLabelKind.PROFILE, "modal", "Kripke frame profile S4"),
    "s5": (FamilyLabelKind.PROFILE, "modal", "Kripke frame profile S5"),
    # properties / obligations
    "safety": (FamilyLabelKind.PROPERTY, None, "property kind"),
    "liveness": (FamilyLabelKind.PROPERTY, None, "property kind"),
    "noninterference": (
        FamilyLabelKind.PROPERTY,
        "hyperproperty",
        "property under hyperproperty",
    ),
    "validity": (FamilyLabelKind.PROPERTY, None, "property kind"),
    "satisfiability": (FamilyLabelKind.PROPERTY, None, "property kind"),
    "reachability": (FamilyLabelKind.PROPERTY, None, "property kind"),
    "termination": (FamilyLabelKind.PROPERTY, None, "property kind"),
    "invariant": (FamilyLabelKind.PROPERTY, None, "property kind"),
    "theorem": (FamilyLabelKind.PROPERTY, None, "property kind"),
    "authentication": (FamilyLabelKind.PROPERTY, None, "property kind"),
    "secrecy": (FamilyLabelKind.PROPERTY, None, "property kind"),
    "safety_liveness": (
        FamilyLabelKind.PROPERTY,
        "temporal",
        "combined safety/liveness property role",
    ),
    "vc": (FamilyLabelKind.VIEW, None, "verification-condition view/obligation role"),
    "verification_condition": (
        FamilyLabelKind.VIEW,
        None,
        "verification-condition view/obligation role",
    ),
    "security_verification_condition": (
        FamilyLabelKind.VIEW,
        None,
        "opaque security verification-condition view",
    ),
    # views / roles
    "graph_projection": (FamilyLabelKind.VIEW, None, "view role"),
    "structural_round_trip": (FamilyLabelKind.VIEW, None, "view role"),
    "source": (FamilyLabelKind.VIEW, None, "view role"),
    "normalized": (FamilyLabelKind.VIEW, None, "view role"),
    "proof_translation": (FamilyLabelKind.VIEW, None, "view role"),
    "threat_model": (FamilyLabelKind.VIEW, None, "domain view role"),
    "workflow_temporal": (
        FamilyLabelKind.VIEW,
        "temporal",
        "domain workflow temporal view",
    ),
    "dynamic_hoare": (
        FamilyLabelKind.VIEW,
        "program",
        "domain dynamic-Hoare view over program",
    ),
    "typed_first_order": (
        FamilyLabelKind.VIEW,
        "first_order",
        "typed first-order view, not a distinct family",
    ),
    "intention_deontic": (
        FamilyLabelKind.VIEW,
        "deontic",
        "intent-domain deontic view",
    ),
    "temporal_first_order": (
        FamilyLabelKind.PROFILE,
        "tdfol",
        "composition of temporal and first_order (tdfol compatibility)",
    ),
    "first_order_temporal": (
        FamilyLabelKind.PROFILE,
        "tdfol",
        "legacy first-order temporal composition profile",
    ),
    # providers / tools
    "z3": (FamilyLabelKind.PROVIDER, None, "provider tool name"),
    "cvc5": (FamilyLabelKind.PROVIDER, None, "provider tool name"),
    "vampire": (FamilyLabelKind.PROVIDER, None, "provider tool name"),
    "eprover": (FamilyLabelKind.PROVIDER, None, "provider tool name"),
    "e": (FamilyLabelKind.PROVIDER, None, "provider tool name"),
    "proverif": (FamilyLabelKind.PROVIDER, "cryptographic_protocol", "provider tool"),
    "tamarin": (FamilyLabelKind.PROVIDER, "cryptographic_protocol", "provider tool"),
    "lean": (FamilyLabelKind.PROVIDER, "higher_order", "kernel provider, not a family"),
    "lean4": (FamilyLabelKind.PROVIDER, "higher_order", "kernel provider, not a family"),
    "rocq": (FamilyLabelKind.PROVIDER, "higher_order", "kernel provider, not a family"),
    "coq": (FamilyLabelKind.PROVIDER, "higher_order", "kernel provider alias"),
    "coqc": (FamilyLabelKind.PROVIDER, "higher_order", "kernel provider alias"),
    "isabelle": (
        FamilyLabelKind.PROVIDER,
        "higher_order",
        "kernel provider, not a family",
    ),
    "tlc": (FamilyLabelKind.PROVIDER, "transition_system", "TLA TLC provider"),
    "tla_tlc": (FamilyLabelKind.PROVIDER, "transition_system", "TLA TLC provider"),
    "apalache": (
        FamilyLabelKind.PROVIDER,
        "transition_system",
        "Apalache provider",
    ),
    "hammer": (FamilyLabelKind.PROVIDER, None, "hammer portfolio provider"),
    "runtime_mtl": (FamilyLabelKind.PROVIDER, "temporal", "runtime MTL provider"),
    "datalog_secpal": (
        FamilyLabelKind.PROVIDER,
        "authorization",
        "authorization provider",
    ),
    "hyperltl_autohyper_mchyper": (
        FamilyLabelKind.PROVIDER,
        "hyperproperty",
        "hyperproperty provider bundle",
    ),
    "ergoai": (FamilyLabelKind.PROVIDER, "frame_logic", "advisor/provider surface"),
    "symbolicai": (FamilyLabelKind.PROVIDER, None, "advisor surface"),
    "production-authorization": (
        FamilyLabelKind.PROVIDER,
        "authorization",
        "project-owned authorization provider alias",
    ),
    "temporal-monitor": (
        FamilyLabelKind.PROVIDER,
        "temporal",
        "bounded temporal monitor provider",
    ),
    # execution lanes
    "runtime": (FamilyLabelKind.LANE, None, "execution/evidence lane"),
    "atp": (FamilyLabelKind.LANE, None, "execution lane"),
    "kernel": (FamilyLabelKind.LANE, None, "execution lane"),
    "state_model": (FamilyLabelKind.LANE, None, "execution lane"),
    "smt_lane": (FamilyLabelKind.LANE, None, "execution lane"),
    "protocol": (
        FamilyLabelKind.PROFILE,
        "cryptographic_protocol",
        "protocol profile/lane over cryptographic_protocol",
    ),
    "software_verification": (
        FamilyLabelKind.LANE,
        None,
        "domain/execution lane, not a semantic family",
    ),
    "advisor": (FamilyLabelKind.LANE, None, "tool participation role"),
    "advisors": (FamilyLabelKind.LANE, None, "tool participation role group"),
    "support": (FamilyLabelKind.LANE, None, "tool participation role"),
    "jvm": (FamilyLabelKind.LANE, None, "tool runtime family"),
    # domain labels that are not logic families
    "intent": (FamilyLabelKind.VIEW, None, "domain IR label"),
    "security": (FamilyLabelKind.VIEW, None, "domain IR label"),
    "shared": (FamilyLabelKind.VIEW, None, "shared domain view label"),
    "opaque": (FamilyLabelKind.VIEW, None, "non-executable payload family"),
    "prose": (FamilyLabelKind.VIEW, None, "non-executable payload family"),
    "unsupported": (FamilyLabelKind.VIEW, None, "unsupported disposition label"),
    "unspecified": (FamilyLabelKind.VIEW, None, "unspecified disposition label"),
    "secpal-style": (
        FamilyLabelKind.PROFILE,
        "authorization",
        "SecPAL-style authorization source profile",
    ),
    "dependent_type_theory": (
        FamilyLabelKind.PROFILE,
        "higher_order",
        "dependent-type profile/target, not a frozen baseline family",
    ),
    "dependent_type": (
        FamilyLabelKind.PROFILE,
        "higher_order",
        "dependent-type declaration-only candidate",
    ),
    # evidence kinds commonly misused as families
    "candidate": (FamilyLabelKind.EVIDENCE_KIND, None, "evidence kind"),
    "checked_proof": (FamilyLabelKind.EVIDENCE_KIND, None, "evidence kind"),
    "kernel_checked_proof": (FamilyLabelKind.EVIDENCE_KIND, None, "evidence kind"),
    "model": (FamilyLabelKind.EVIDENCE_KIND, None, "evidence kind"),
    "counterexample": (FamilyLabelKind.EVIDENCE_KIND, None, "evidence kind"),
    "trace": (FamilyLabelKind.EVIDENCE_KIND, None, "evidence kind"),
    "monitor_verdict": (FamilyLabelKind.EVIDENCE_KIND, None, "evidence kind"),
    "policy_decision": (FamilyLabelKind.EVIDENCE_KIND, None, "evidence kind"),
    "attestation": (FamilyLabelKind.EVIDENCE_KIND, None, "evidence kind"),
    "unsat_core": (FamilyLabelKind.EVIDENCE_KIND, None, "evidence kind"),
    "proof_certificate": (FamilyLabelKind.EVIDENCE_KIND, None, "evidence kind"),
    "declaration": (FamilyLabelKind.EVIDENCE_KIND, None, "evidence kind"),
    "reconstruction": (FamilyLabelKind.EVIDENCE_KIND, None, "evidence kind"),
    "zkp": (FamilyLabelKind.EVIDENCE_KIND, None, "zero-knowledge evidence kind"),
}

_KNOWN_NON_FAMILY_BY_NORMALIZED: Final[
    dict[str, tuple[FamilyLabelKind, str | None, str]]
] = {
    normalize_family_name(label): disposition
    for label, disposition in _KNOWN_NON_FAMILY.items()
}


# Labels that must never classify as a semantic family, even without registry hit.
_NEVER_SEMANTIC_FAMILY: Final[frozenset[str]] = frozenset(
    normalize_family_name(label) for label in _KNOWN_NON_FAMILY
) | frozenset(
    {
        "safety",
        "liveness",
        "verification_condition",
        "vc",
        "graph_projection",
        "z3",
        "cvc5",
        "lean",
        "rocq",
        "isabelle",
        "proverif",
        "tamarin",
        "vampire",
        "eprover",
        "hammer",
        "runtime",
        "noninterference",
    }
)


def package_root() -> Path:
    """Return the ``ipfs_datasets_py`` package directory."""

    # audit.py -> families -> logic -> ipfs_datasets_py (package)
    return Path(__file__).resolve().parents[2]


def datasets_repo_root() -> Path:
    """Return the nested ``ipfs_datasets_py`` repository root."""

    # audit.py -> families -> logic -> package -> repo root
    return Path(__file__).resolve().parents[3]


def default_baseline_report_path() -> Path:
    """Path of the checked-in baseline audit report."""

    return (
        datasets_repo_root()
        / "docs"
        / "architecture"
        / "logic"
        / "logic_parser_baseline"
        / "family_label_audit.json"
    )


def _safe_normalize(value: str) -> str | None:
    try:
        return normalize_family_name(value)
    except LogicFamilyRegistryError:
        return None


def _build_registry_lookups(
    registry: LogicFamilyRegistry,
) -> tuple[
    dict[str, str],
    dict[str, str],
    dict[str, str],
    dict[str, str],
    dict[str, str],
]:
    """Return normalized lookup maps for family/alias/fragment/property/evidence."""

    families: dict[str, str] = {}
    aliases: dict[str, str] = {}
    fragments: dict[str, str] = {}
    properties: dict[str, str] = {}
    evidence: dict[str, str] = {}

    for family_id, descriptor in registry.families.items():
        families[normalize_family_name(family_id)] = family_id
        for alias in descriptor.aliases:
            aliases[normalize_family_name(alias)] = family_id
        # family_id itself is also a valid resolve key
        aliases.setdefault(normalize_family_name(family_id), family_id)

    for fragment_id, descriptor in registry.fragments.items():
        fragments[normalize_family_name(fragment_id)] = fragment_id
        for alias in descriptor.aliases:
            fragments[normalize_family_name(alias)] = fragment_id

    for property_id, descriptor in registry.properties.items():
        properties[normalize_family_name(property_id)] = property_id
        for alias in descriptor.aliases:
            properties[normalize_family_name(alias)] = property_id

    for evidence_id in registry.evidence:
        evidence[normalize_family_name(evidence_id)] = evidence_id

    return families, aliases, fragments, properties, evidence


def classify_label(
    label: str,
    *,
    registry: LogicFamilyRegistry | None = None,
) -> LabelClassification:
    """Classify one family-like string into a typed namespace disposition.

    Tool names, property kinds, view roles, notations, providers, lanes, and
    evidence kinds are never reported as semantic families.
    """

    if not isinstance(label, str) or not label.strip():
        raise ValueError("label must be a non-empty string")

    observed = label.strip()
    normalized = _safe_normalize(observed)
    if normalized is None:
        return LabelClassification(
            observed=observed,
            normalized=observed.casefold(),
            kind=FamilyLabelKind.UNKNOWN,
            notes="label is not a normalizable identifier",
            severity=DriftSeverity.WARNING,
        )

    active = registry if registry is not None else DEFAULT_REGISTRY
    families, aliases, fragments, properties, evidence = _build_registry_lookups(
        active
    )

    # Explicit non-family catalog wins over accidental registry alias collisions
    # for tool/property/view labels that must never be semantic families.
    known = _KNOWN_NON_FAMILY.get(observed.casefold())
    if known is None:
        known = _KNOWN_NON_FAMILY_BY_NORMALIZED.get(normalized)
    if known is not None:
        kind, canonical, notes = known
        return LabelClassification(
            observed=observed,
            normalized=normalized,
            kind=kind,
            canonical_family_id=canonical,
            notes=notes,
            is_semantic_family=False,
            severity=(
                DriftSeverity.NONE
                if kind
                in {
                    FamilyLabelKind.PROFILE,
                    FamilyLabelKind.PROPERTY,
                    FamilyLabelKind.VIEW,
                    FamilyLabelKind.NOTATION,
                    FamilyLabelKind.PROVIDER,
                    FamilyLabelKind.LANE,
                    FamilyLabelKind.EVIDENCE_KIND,
                }
                else DriftSeverity.INFO
            ),
        )

    if normalized in families:
        family_id = families[normalized]
        return LabelClassification(
            observed=observed,
            normalized=normalized,
            kind=FamilyLabelKind.CANONICAL_FAMILY,
            canonical_family_id=family_id,
            notes="exact canonical family identifier",
            is_semantic_family=True,
            severity=DriftSeverity.NONE,
        )

    if normalized in aliases and normalized not in families:
        family_id = aliases[normalized]
        # Only treat as alias when the observed form is not the canonical id.
        if normalize_family_name(family_id) != normalized:
            return LabelClassification(
                observed=observed,
                normalized=normalized,
                kind=FamilyLabelKind.ALIAS,
                canonical_family_id=family_id,
                notes=f"alias of canonical family {family_id}",
                is_semantic_family=True,
                severity=DriftSeverity.INFO,
            )

    if normalized in fragments:
        return LabelClassification(
            observed=observed,
            normalized=normalized,
            kind=FamilyLabelKind.PROFILE,
            notes=f"registry fragment/profile {fragments[normalized]}",
            is_semantic_family=False,
            severity=DriftSeverity.NONE,
        )

    if normalized in properties:
        return LabelClassification(
            observed=observed,
            normalized=normalized,
            kind=FamilyLabelKind.PROPERTY,
            notes=f"registry property {properties[normalized]}",
            is_semantic_family=False,
            severity=DriftSeverity.NONE,
        )

    if normalized in evidence:
        return LabelClassification(
            observed=observed,
            normalized=normalized,
            kind=FamilyLabelKind.EVIDENCE_KIND,
            notes=f"registry evidence kind {evidence[normalized]}",
            is_semantic_family=False,
            severity=DriftSeverity.NONE,
        )

    # Registry resolve may accept human aliases not listed above.
    try:
        resolved = active.resolve(observed)
    except LogicFamilyRegistryError:
        resolved = None
    if resolved is not None:
        if resolved.family_id == observed or normalize_family_name(
            resolved.family_id
        ) == normalized:
            return LabelClassification(
                observed=observed,
                normalized=normalized,
                kind=FamilyLabelKind.CANONICAL_FAMILY,
                canonical_family_id=resolved.family_id,
                notes="resolved as canonical family",
                is_semantic_family=True,
                severity=DriftSeverity.NONE,
            )
        return LabelClassification(
            observed=observed,
            normalized=normalized,
            kind=FamilyLabelKind.ALIAS,
            canonical_family_id=resolved.family_id,
            notes=f"resolved alias of {resolved.family_id}",
            is_semantic_family=True,
            severity=DriftSeverity.INFO,
        )

    return LabelClassification(
        observed=observed,
        normalized=normalized,
        kind=FamilyLabelKind.UNKNOWN,
        notes="unregistered family-like label",
        is_semantic_family=False,
        severity=DriftSeverity.WARNING,
    )


def _is_family_like_literal(value: str) -> bool:
    if not value or len(value) > 64 or len(value) < 2:
        return False
    if any(character.isspace() for character in value):
        return False
    if not _IDENTIFIER_RE.fullmatch(value):
        return False
    # Drop pure numbers and single-letter noise except known single-letter tools.
    return not value.isdigit()


def _extract_string_constants(node: ast.AST) -> list[str]:
    results: list[str] = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        results.append(node.value)
    elif isinstance(node, ast.JoinedStr):
        return results
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for element in node.elts:
            results.extend(_extract_string_constants(element))
    return results


def _context_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _scan_python_source(
    path: Path,
    *,
    root_label: str,
    package: Path,
) -> list[LabelObservation]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    relative = path.relative_to(package).as_posix()
    observations: list[LabelObservation] = []
    seen_local: set[tuple[str, int | None, str]] = set()

    def add(label: str, line: int | None, context: str) -> None:
        if not _is_family_like_literal(label):
            return
        key = (label, line, context)
        if key in seen_local:
            return
        seen_local.add(key)
        observations.append(
            LabelObservation(
                label=label,
                source=relative,
                root=root_label,
                line=line,
                context=context,
            )
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.keyword):
            if node.arg in _FAMILY_CONTEXT_KEYS:
                for literal in _extract_string_constants(node.value):
                    add(literal, getattr(node, "lineno", None), node.arg or "")
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                name = _context_name(target)
                if name in _FAMILY_CONTEXT_KEYS or name.endswith(
                    ("_family", "_families", "LOGIC_FAMILIES")
                ):
                    for literal in _extract_string_constants(node.value):
                        add(literal, getattr(node, "lineno", None), name)
        elif isinstance(node, ast.AnnAssign):
            name = _context_name(node.target)
            if (
                name in _FAMILY_CONTEXT_KEYS
                or name.endswith(("_family", "_families"))
            ) and node.value is not None:
                for literal in _extract_string_constants(node.value):
                    add(literal, getattr(node, "lineno", None), name)
        elif isinstance(node, ast.Dict):
            for key_node, value_node in zip(node.keys, node.values, strict=True):
                key_name = _context_name(key_node)
                if key_name in _FAMILY_CONTEXT_KEYS:
                    for literal in _extract_string_constants(value_node):
                        add(literal, getattr(node, "lineno", None), key_name)
        elif isinstance(node, ast.Call):
            func_name = _context_name(node.func)
            if func_name in {
                "LogicFamily",
                "FormalizationView",
                "_matrix_entry",
                "_family",
            }:
                for arg in node.args:
                    for literal in _extract_string_constants(arg):
                        add(literal, getattr(node, "lineno", None), func_name)
                for keyword in node.keywords:
                    if keyword.arg in _FAMILY_CONTEXT_KEYS or keyword.arg in {
                        "family_id",
                        "family",
                    }:
                        for literal in _extract_string_constants(keyword.value):
                            add(
                                literal,
                                getattr(node, "lineno", None),
                                keyword.arg or func_name,
                            )
        elif isinstance(node, ast.ClassDef) and node.name in {
            "LogicFamily",
            "ModalLogicFamily",
        }:
            for statement in node.body:
                if isinstance(statement, ast.Assign) or (
                    isinstance(statement, ast.AnnAssign)
                    and statement.value is not None
                ):
                    for literal in _extract_string_constants(statement.value):
                        add(
                            literal,
                            getattr(statement, "lineno", None),
                            f"enum:{node.name}",
                        )

    return observations


def collect_observations(
    *,
    roots: Sequence[str] | None = None,
    package: Path | None = None,
    include_catalog: bool = True,
) -> tuple[LabelObservation, ...]:
    """Statically collect family-like labels under configured package roots.

    Roots are readable as plain files; no backend or domain module is imported.
    """

    package_path = package if package is not None else package_root()
    selected = tuple(roots) if roots is not None else DEFAULT_AUDIT_ROOTS
    collected: list[LabelObservation] = []

    for root_label in selected:
        root_path = package_path / root_label
        if not root_path.exists():
            continue
        if root_path.is_file() and root_path.suffix == ".py":
            collected.extend(
                _scan_python_source(
                    root_path, root_label=root_label, package=package_path
                )
            )
            continue
        if not root_path.is_dir():
            continue
        for path in sorted(root_path.rglob("*.py")):
            # Skip caches and tests nested under package roots.
            parts = set(path.parts)
            if "__pycache__" in parts or "tests" in parts:
                continue
            # Avoid treating this audit module's catalog literals as live drift.
            if path.name == "audit.py" and path.parent.name == "families":
                continue
            collected.extend(
                _scan_python_source(
                    path, root_label=root_label, package=package_path
                )
            )

    if include_catalog:
        # Always include the known non-family catalog so baseline drift is complete
        # even when a label is only documented, not yet scanned.
        for label in sorted(_KNOWN_NON_FAMILY):
            collected.append(
                LabelObservation(
                    label=label,
                    source="known_drift_catalog",
                    root="catalog",
                    line=None,
                    context="plan_migration_table",
                )
            )

    # Stable order: root, source, line, label, context.
    collected.sort(
        key=lambda item: (
            item.root,
            item.source,
            item.line if item.line is not None else -1,
            item.label,
            item.context,
        )
    )
    return tuple(collected)


def _unique_labels(observations: Iterable[LabelObservation]) -> tuple[str, ...]:
    labels = sorted(
        {item.label for item in observations},
        key=lambda value: (value.casefold(), value),
    )
    return tuple(labels)


def baseline_seed_labels(
    *,
    registry: LogicFamilyRegistry | None = None,
) -> tuple[str, ...]:
    """Deterministic seed labels for the checked-in baseline report."""

    active = registry if registry is not None else DEFAULT_REGISTRY
    labels: set[str] = set(_KNOWN_NON_FAMILY)
    labels.update(active.families)
    # Representative aliases that historically drift into free-form family fields.
    for alias in (
        "FOL",
        "predicate_logic",
        "state_transition",
        "protocol_logic",
        "dynamic_logic",
        "hoare_logic",
        "HOL",
        "CHC",
        "Horn",
        "HyperLTL",
        "SecPAL",
        "LTL",
        "MTL",
        "CTL",
        "FLogic",
        "Boolean_logic",
        "kripke_structure",
        "resource_logic",
        "separation",
        "constrained_horn_clauses",
        "policy_logic",
        "PL",
    ):
        labels.add(alias)
    # High-signal fragment/property samples that must never be families.
    labels.update(
        {
            "linear_time",
            "horn_clauses",
            "heap",
            "symbolic_crypto",
            "branching_time",
            "data_race_freedom",
            "trace_conformance",
        }
    )
    return tuple(sorted(labels, key=lambda value: (value.casefold(), value)))


def catalog_observations(
    *,
    registry: LogicFamilyRegistry | None = None,
) -> tuple[LabelObservation, ...]:
    """Observations from the plan catalog and default registry seed labels."""

    active = registry if registry is not None else DEFAULT_REGISTRY
    observed: list[LabelObservation] = []
    family_ids = set(active.families)
    family_aliases = {
        alias
        for descriptor in active.families.values()
        for alias in descriptor.aliases
    }
    for label in baseline_seed_labels(registry=active):
        if label in _KNOWN_NON_FAMILY:
            source, root, context = (
                "known_drift_catalog",
                "catalog",
                "plan_migration_table",
            )
        elif label in family_ids:
            source, root, context = (
                "default_registry",
                "registry",
                "family_id",
            )
        elif label in family_aliases:
            source, root, context = (
                "default_registry",
                "registry",
                "alias",
            )
        else:
            source, root, context = (
                "default_registry",
                "registry",
                "seed_sample",
            )
        observed.append(
            LabelObservation(
                label=label,
                source=source,
                root=root,
                context=context,
            )
        )
    return tuple(observed)


def audit_family_labels(
    *,
    roots: Sequence[str] | None = None,
    package: Path | None = None,
    registry: LogicFamilyRegistry | None = None,
    observations: Sequence[LabelObservation] | None = None,
    scan_roots: bool = True,
) -> LogicFamilyAuditReport:
    """Build a deterministic ``LogicFamilyAudit@1`` report.

    When ``scan_roots`` is true (default), configured package roots are scanned
    statically.  Catalog and registry labels are always included so known drift
    is complete even if a root is empty.
    """

    active = registry if registry is not None else DEFAULT_REGISTRY
    selected_roots = tuple(roots) if roots is not None else DEFAULT_AUDIT_ROOTS
    if observations is not None:
        observed = tuple(observations)
    else:
        combined: list[LabelObservation] = list(catalog_observations(registry=active))
        if scan_roots:
            combined.extend(
                collect_observations(
                    roots=selected_roots,
                    package=package,
                    include_catalog=False,
                )
            )
        combined.sort(
            key=lambda item: (
                item.root,
                item.source,
                item.line if item.line is not None else -1,
                item.label,
                item.context,
            )
        )
        # Deduplicate identical observation rows.
        deduped: list[LabelObservation] = []
        seen: set[tuple[Any, ...]] = set()
        for item in combined:
            key = (
                item.label,
                item.source,
                item.root,
                item.line,
                item.context,
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        observed = tuple(deduped)

    labels = _unique_labels(observed)
    classifications = tuple(
        classify_label(label, registry=active) for label in labels
    )

    by_normalized: dict[str, list[LabelObservation]] = {}
    for item in observed:
        key = _safe_normalize(item.label) or item.label.casefold()
        by_normalized.setdefault(key, []).append(item)

    drift_rows: list[dict[str, Any]] = []
    for classification in classifications:
        if classification.kind is FamilyLabelKind.CANONICAL_FAMILY:
            continue
        sources = sorted(
            {
                observation.source
                for observation in by_normalized.get(classification.normalized, ())
            }
        )
        drift_rows.append(
            {
                "canonical_family_id": classification.canonical_family_id,
                "kind": classification.kind.value,
                "normalized": classification.normalized,
                "notes": classification.notes,
                "observed": classification.observed,
                "severity": classification.severity.value,
                "sources": sources,
            }
        )
    drift_rows.sort(key=lambda row: (row["kind"], row["normalized"], row["observed"]))

    kind_counts: dict[str, int] = {}
    for classification in classifications:
        kind_counts[classification.kind.value] = (
            kind_counts.get(classification.kind.value, 0) + 1
        )

    semantic_misuse = sorted(
        classification.observed
        for classification in classifications
        if classification.normalized in _NEVER_SEMANTIC_FAMILY
        and classification.is_semantic_family
    )

    summary = {
        "classification_count": len(classifications),
        "drift_count": len(drift_rows),
        "kind_counts": {key: kind_counts[key] for key in sorted(kind_counts)},
        "observation_count": len(observed),
        "root_count": len(selected_roots),
        "scanned_roots": list(selected_roots) if scan_roots else [],
        "semantic_family_misuse_count": len(semantic_misuse),
        "semantic_family_misuses": semantic_misuse,
        "unique_label_count": len(labels),
    }

    return LogicFamilyAuditReport(
        classifications=classifications,
        observations=observed,
        drift=tuple(drift_rows),
        roots=selected_roots,
        canonical_family_ids=tuple(sorted(active.families)),
        summary=summary,
    )


def baseline_audit_dict(
    *,
    roots: Sequence[str] | None = None,
    package: Path | None = None,
    registry: LogicFamilyRegistry | None = None,
) -> dict[str, Any]:
    """Return the deterministic audit for the current configured roots.

    The checked-in report inventories live source labels, rather than merely
    copying registry and catalog seeds.  Static scanning keeps generation
    import-free while retaining exact source and line evidence.
    """

    report = audit_family_labels(
        roots=roots,
        package=package,
        registry=registry,
        scan_roots=True,
    )
    return report.to_dict()


def ensure_baseline_report(
    path: Path | str | None = None,
    *,
    roots: Sequence[str] | None = None,
    package: Path | None = None,
    registry: LogicFamilyRegistry | None = None,
) -> Path:
    """Write ``family_label_audit.json`` from the configured-root audit."""

    target = Path(path) if path is not None else default_baseline_report_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = baseline_audit_dict(
        roots=roots,
        package=package,
        registry=registry,
    )
    rendered = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(target)
    return target


def render_audit_report(report: LogicFamilyAuditReport) -> str:
    """Serialize an audit report with stable key ordering."""

    return report.to_json(indent=2)


def write_audit_report(
    report: LogicFamilyAuditReport | Mapping[str, Any],
    path: Path | str | None = None,
) -> Path:
    """Write an audit report atomically."""

    target = Path(path) if path is not None else default_baseline_report_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(report, LogicFamilyAuditReport):
        rendered = render_audit_report(report)
    else:
        rendered = (
            json.dumps(dict(report), ensure_ascii=True, indent=2, sort_keys=True)
            + "\n"
        )
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(target)
    return target


def load_audit_report(path: Path | str | None = None) -> dict[str, Any]:
    """Load a previously written audit report."""

    target = Path(path) if path is not None else default_baseline_report_path()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("audit report must be a JSON object")
    return payload


def assert_never_semantic_family(label: str) -> LabelClassification:
    """Classify ``label`` and assert it is not a semantic family."""

    classification = classify_label(label)
    if classification.is_semantic_family:
        raise AssertionError(
            f"{label!r} must not be treated as a semantic family; "
            f"got {classification.kind.value}"
        )
    return classification


__all__ = [
    "AUDIT_INTERFACE",
    "AUDIT_REPORT_VERSION",
    "AUDIT_SCHEMA_VERSION",
    "DEFAULT_AUDIT_ROOTS",
    "DriftSeverity",
    "FamilyLabelKind",
    "LabelClassification",
    "LabelObservation",
    "LogicFamilyAuditReport",
    "assert_never_semantic_family",
    "audit_family_labels",
    "baseline_audit_dict",
    "baseline_seed_labels",
    "catalog_observations",
    "classify_label",
    "collect_observations",
    "datasets_repo_root",
    "default_baseline_report_path",
    "ensure_baseline_report",
    "load_audit_report",
    "package_root",
    "render_audit_report",
    "write_audit_report",
]


if __name__ == "__main__":
    written = ensure_baseline_report()
    print(written)
