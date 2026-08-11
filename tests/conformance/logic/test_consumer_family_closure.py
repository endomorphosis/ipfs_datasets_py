"""Conformance: documentation + consumer-family static closure (LFP-045).

Acceptance:

* Static closure records every unregistered emitted ID, undocumented
  controlled syntax, stale consumer, and failing public example as an
  owner-scoped typed gap
* Historical plans are clearly nonnormative in the normative leaf
* LFP-046 (not this discovery task) owns the drained zero-drift fixed point

Interfaces: LogicConsumerClosure@1, LogicSyntaxAndFamilyContracts@1
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import pytest

from ipfs_datasets_py.logic.backends.registry import (
    EXECUTABLE_PROVIDER_ALIASES,
    EXECUTABLE_PROVIDER_IDS,
)
from ipfs_datasets_py.logic.families.generated_catalog import DEFAULT_GENERATED_CATALOG
from ipfs_datasets_py.logic.families.namespaces import (
    BASELINE_NAMESPACES,
    CANONICAL_NAMESPACE_KINDS,
    NamespaceKind,
)
from ipfs_datasets_py.logic.families.providers import (
    ADVISORY_PROVIDER_IDS,
    BASELINE_PROVIDER_IDS,
)
from ipfs_datasets_py.logic.families.registry import (
    BASELINE_FAMILY_IDS,
    DEFAULT_REGISTRY,
)
from ipfs_datasets_py.logic.parsers.catalog import DEFAULT_PARSER_CATALOG
from ipfs_datasets_py.logic.syntax_core.ast import NodeKind
from ipfs_datasets_py.logic.verification_api import (
    CANONICAL_LOGIC_DISCOVERY_INTERFACE,
    VERIFICATION_API_V2_INTERFACE,
    dual_read_label,
    get_canonical_discovery,
    list_logic_families,
    list_namespace_identities,
    list_namespaces,
    list_providers,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LOGIC_CONSUMER_CLOSURE_INTERFACE: Final = "LogicConsumerClosure@1"
LOGIC_SYNTAX_AND_FAMILY_CONTRACTS_INTERFACE: Final = (
    "LogicSyntaxAndFamilyContracts@1"
)
LOGIC_CONSUMER_CLOSURE_SCHEMA: Final = "logic-consumer-closure/v1"
LOGIC_CONSUMER_GAP_SCHEMA: Final = "logic-consumer-closure-gap/v1"
CLOSURE_REPORT_VERSION: Final = "1.0.0"
TASK_ID: Final = "LFP-045"
GOAL_ID: Final = "LFP-G090"
FIXED_POINT_OWNER_TASK_ID: Final = "LFP-046"
PROGRAM_ID: Final = "ipfs-datasets-logic-family-parser-v1"

REQUIRED_GAP_KINDS: Final[frozenset[str]] = frozenset(
    {
        "unregistered_emitted_id",
        "undocumented_controlled_syntax",
        "stale_consumer",
        "failing_public_example",
    }
)

# Normative architecture leaf owned by this task.
_NORMATIVE_DOC_RELATIVE: Final = (
    "docs/architecture/logic/LOGIC_SYNTAX_AND_FAMILY_CONTRACTS.md"
)

# Public example surfaces scanned for failing snippets / stale labels.
_PUBLIC_EXAMPLE_DOC_RELATIVES: Final[tuple[str, ...]] = (
    "docs/logic/QUICKSTART.md",
    "docs/logic/USAGE_EXAMPLES.md",
)

# Consumer modules scanned for stale free-form family writes (bounded roots).
_STALE_CONSUMER_SCAN_RELATIVES: Final[tuple[str, ...]] = (
    "ipfs_datasets_py/logic/api.py",
    "ipfs_datasets_py/logic/verification_api.py",
    "ipfs_datasets_py/logic/cli.py",
    "ipfs_datasets_py/logic/submodule_registry.py",
    "ipfs_datasets_py/logic/backends/registry.py",
    "ipfs_datasets_py/logic/formalization/views.py",
    "ipfs_datasets_py/logic/formalization/compiler.py",
    "ipfs_datasets_py/logic/software_verification/source_adapters.py",
    "ipfs_datasets_py/logic/crypto_ir/formalization/compiler.py",
    "ipfs_datasets_py/logic/legal_ir/typed_adapter.py",
    "ipfs_datasets_py/logic/security_ir/formalization_adapter_v2.py",
)

# Historical / nonnormative plan markers required in the normative leaf.
_NONNORMATIVE_MARKERS: Final[tuple[str, ...]] = (
    "nonnormative",
    "Historical plans are nonnormative",
    "historical / nonnormative",
    "*_PLAN.md",
)

# Controlled syntax forms that the normative leaf must document (NodeKind).
_CONTROLLED_NODE_KINDS: Final[tuple[str, ...]] = tuple(
    sorted(kind.value for kind in NodeKind)
)

# Controlled notation / encoding ids from the baseline namespace catalog.
_CONTROLLED_NOTATIONS: Final[tuple[str, ...]] = (
    "canonical_text",
    "smt_lib2",
    "tptp_fof",
    "tla_plus_source",
    "tamarin_spthy",
    "proverif_pv",
)
_CONTROLLED_ENCODINGS: Final[tuple[str, ...]] = (
    "smt_lib2",
    "tptp_tff",
    "lean4",
    "rocq",
    "isabelle_hol",
)

# Legacy free-form labels that must never be *written* as family ids.
_LEGACY_FAMILY_WRITE_FORBIDDEN: Final[frozenset[str]] = frozenset(
    {
        "fol",
        "smt",
        "smtlib2",
        "smt_lib",
        "protocol",
        "hyperltl",
        "tla_plus",
        "state_transition",
        "secpal",
        "policy",
        "vc",
        "VC",
        "runtime",
        "safety",
        "liveness",
        "lean",
        "rocq",
        "isabelle",
    }
)

# Assignment / dict-key contexts that indicate a family-id write surface.
_FAMILY_WRITE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "family",
        "family_id",
        "logic_family",
        "source_family",
        "target_family",
        "source_family_id",
        "target_family_id",
        "predicted_logic_family",
        "target_logic_family",
        "logic_families",
    }
)

_IMPORT_FROM_RE = re.compile(
    r"^\s*from\s+([A-Za-z_][\w.]*)\s+import\s+(.+)$",
    re.MULTILINE,
)
_IMPORT_RE = re.compile(
    r"^\s*import\s+([A-Za-z_][\w.]*(?:\s*,\s*[A-Za-z_][\w.]*)*)",
    re.MULTILINE,
)
_FENCE_RE = re.compile(r"```(?:python|py)\n(.*?)```", re.DOTALL | re.IGNORECASE)


class GapKind(StrEnum):
    """Closed gap taxonomy for LogicConsumerClosure@1."""

    UNREGISTERED_EMITTED_ID = "unregistered_emitted_id"
    UNDOCUMENTED_CONTROLLED_SYNTAX = "undocumented_controlled_syntax"
    STALE_CONSUMER = "stale_consumer"
    FAILING_PUBLIC_EXAMPLE = "failing_public_example"


class ConsumerClosureError(ValueError):
    """Raised when a consumer-closure contract is malformed."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ConsumerClosureError(f"{field_name} must be a non-empty trimmed string")
    if "\x00" in value:
        raise ConsumerClosureError(f"{field_name} must not contain NUL bytes")
    return value


def _stable_gap_id(
    gap_kind: GapKind | str,
    owner: str,
    subject: str,
    *,
    evidence: str = "",
) -> str:
    payload = "|".join(
        (
            str(gap_kind),
            owner,
            subject,
            evidence,
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"lfp045:{gap_kind}:{digest}"


@dataclass(frozen=True, slots=True)
class OwnerScopedTypedGap:
    """One owner-scoped typed gap discovered by static closure."""

    gap_id: str
    gap_kind: GapKind
    owner: str
    subject: str
    evidence: str
    refill_eligible: bool = True
    task_id: str = TASK_ID
    schema_version: str = LOGIC_CONSUMER_GAP_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _text(self.gap_id, "gap_id"))
        if not isinstance(self.gap_kind, GapKind):
            try:
                object.__setattr__(self, "gap_kind", GapKind(str(self.gap_kind)))
            except ValueError as error:
                raise ConsumerClosureError(
                    f"unknown gap_kind: {self.gap_kind!r}"
                ) from error
        object.__setattr__(self, "owner", _text(self.owner, "owner"))
        object.__setattr__(self, "subject", _text(self.subject, "subject"))
        evidence = self.evidence if isinstance(self.evidence, str) else str(self.evidence)
        object.__setattr__(self, "evidence", evidence.strip())
        if self.task_id != TASK_ID:
            raise ConsumerClosureError(
                f"discovery gaps must carry task_id={TASK_ID!r}"
            )
        if self.schema_version != LOGIC_CONSUMER_GAP_SCHEMA:
            raise ConsumerClosureError("unsupported gap schema_version")
        if self.gap_kind.value not in REQUIRED_GAP_KINDS:
            raise ConsumerClosureError(f"unknown gap_kind: {self.gap_kind!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence,
            "gap_id": self.gap_id,
            "gap_kind": self.gap_kind.value,
            "owner": self.owner,
            "refill_eligible": self.refill_eligible,
            "schema_version": self.schema_version,
            "subject": self.subject,
            "task_id": self.task_id,
        }


@dataclass(frozen=True, slots=True)
class LogicConsumerClosureReport:
    """Deterministic LogicConsumerClosure@1 discovery receipt."""

    gaps: tuple[OwnerScopedTypedGap, ...]
    emitted_ids: tuple[dict[str, str], ...]
    controlled_syntax_documented: tuple[str, ...]
    historical_plans_nonnormative: bool
    discovery_only: bool = True
    zero_drift: bool = False
    fixed_point_owner_task_id: str = FIXED_POINT_OWNER_TASK_ID
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID
    interface: str = LOGIC_CONSUMER_CLOSURE_INTERFACE
    schema_version: str = LOGIC_CONSUMER_CLOSURE_SCHEMA
    report_version: str = CLOSURE_REPORT_VERSION
    summary: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.interface != LOGIC_CONSUMER_CLOSURE_INTERFACE:
            raise ConsumerClosureError("interface must be LogicConsumerClosure@1")
        if self.fixed_point_owner_task_id != FIXED_POINT_OWNER_TASK_ID:
            raise ConsumerClosureError(
                "fixed-point owner must be LFP-046, not the discovery task"
            )
        if self.zero_drift and self.discovery_only:
            raise ConsumerClosureError(
                "discovery report cannot claim zero_drift fixed point"
            )
        if not self.historical_plans_nonnormative:
            raise ConsumerClosureError(
                "historical plans must be marked nonnormative before closure seal"
            )
        object.__setattr__(
            self,
            "gaps",
            tuple(
                sorted(
                    self.gaps,
                    key=lambda item: (
                        item.gap_kind.value,
                        item.owner,
                        item.subject,
                        item.gap_id,
                    ),
                )
            ),
        )
        object.__setattr__(self, "summary", MappingProxyType(dict(self.summary)))

    @property
    def gap_kinds_present(self) -> frozenset[str]:
        return frozenset(item.gap_kind.value for item in self.gaps)

    def gaps_of(self, kind: GapKind | str) -> tuple[OwnerScopedTypedGap, ...]:
        key = GapKind(kind) if not isinstance(kind, GapKind) else kind
        return tuple(item for item in self.gaps if item.gap_kind is key)

    def to_dict(self) -> dict[str, Any]:
        counts = {
            kind: len(self.gaps_of(kind)) for kind in sorted(REQUIRED_GAP_KINDS)
        }
        return {
            "controlled_syntax_documented": list(self.controlled_syntax_documented),
            "discovery_only": self.discovery_only,
            "emitted_ids": [dict(item) for item in self.emitted_ids],
            "fixed_point_owner_task_id": self.fixed_point_owner_task_id,
            "gap_count": len(self.gaps),
            "gap_counts_by_kind": counts,
            "gaps": [item.to_dict() for item in self.gaps],
            "goal_id": self.goal_id,
            "historical_plans_nonnormative": self.historical_plans_nonnormative,
            "interface": self.interface,
            "program_id": PROGRAM_ID,
            "report_version": self.report_version,
            "schema_version": self.schema_version,
            "summary": dict(self.summary),
            "task_id": self.task_id,
            "zero_drift": self.zero_drift,
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

    @property
    def digest(self) -> str:
        body = self.to_json(indent=None).encode("utf-8")
        return "sha256:" + hashlib.sha256(body).hexdigest()


class LogicConsumerClosure:
    """Static consumer-family closure scanner (LogicConsumerClosure@1).

    Discovery only: records owner-scoped typed gaps and never claims the
    LFP-046 drained zero-drift fixed point.
    """

    INTERFACE: Final = LOGIC_CONSUMER_CLOSURE_INTERFACE
    VERSION: Final = CLOSURE_REPORT_VERSION

    def __init__(self, *, package_root: Path | None = None) -> None:
        self._package_root = package_root or _default_package_root()

    @property
    def interface(self) -> str:
        return self.INTERFACE

    @property
    def package_root(self) -> Path:
        return self._package_root

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixed_point_owner_task_id": FIXED_POINT_OWNER_TASK_ID,
            "goal_id": GOAL_ID,
            "interface": self.INTERFACE,
            "package_root": str(self._package_root),
            "task_id": TASK_ID,
            "version": self.VERSION,
        }

    def scan(self) -> LogicConsumerClosureReport:
        """Run hermetic static closure and return a discovery report."""

        normative_path = self._package_root / _NORMATIVE_DOC_RELATIVE
        normative_text = _read_text(normative_path)
        historical_ok = _historical_plans_marked_nonnormative(normative_text)
        if not historical_ok:
            raise ConsumerClosureError(
                "normative leaf must mark historical plans as nonnormative"
            )

        registered = _registered_identity_index()
        emitted = _collect_emitted_ids()
        gaps: list[OwnerScopedTypedGap] = []

        gaps.extend(_gaps_unregistered_emitted(emitted, registered))
        documented, syntax_gaps = _gaps_undocumented_controlled_syntax(normative_text)
        gaps.extend(syntax_gaps)
        gaps.extend(_gaps_stale_consumers(self._package_root))
        gaps.extend(_gaps_failing_public_examples(self._package_root))

        # Ensure every gap is owner-scoped and uses the closed taxonomy.
        for gap in gaps:
            if not gap.owner:
                raise ConsumerClosureError("gap owner must be non-empty")
            if gap.gap_kind.value not in REQUIRED_GAP_KINDS:
                raise ConsumerClosureError(f"open gap kind: {gap.gap_kind}")

        summary = {
            "emitted_id_count": len(emitted),
            "registered_namespace_count": len(registered),
            "documented_controlled_syntax_count": len(documented),
            "gap_count": len(gaps),
            "discovery_only": True,
            "zero_drift_claimed": False,
            "fixed_point_owner_task_id": FIXED_POINT_OWNER_TASK_ID,
            "normative_document": _NORMATIVE_DOC_RELATIVE,
            "historical_plans_nonnormative": historical_ok,
            "interfaces": {
                "consumer_closure": LOGIC_CONSUMER_CLOSURE_INTERFACE,
                "syntax_and_family_contracts": (
                    LOGIC_SYNTAX_AND_FAMILY_CONTRACTS_INTERFACE
                ),
                "canonical_discovery": CANONICAL_LOGIC_DISCOVERY_INTERFACE,
                "verification_api_v2": VERIFICATION_API_V2_INTERFACE,
            },
        }
        return LogicConsumerClosureReport(
            gaps=tuple(gaps),
            emitted_ids=tuple(emitted),
            controlled_syntax_documented=tuple(sorted(documented)),
            historical_plans_nonnormative=historical_ok,
            discovery_only=True,
            zero_drift=False,
            fixed_point_owner_task_id=FIXED_POINT_OWNER_TASK_ID,
            summary=summary,
        )


def run_consumer_family_closure(
    *,
    package_root: Path | None = None,
) -> LogicConsumerClosureReport:
    """Convenience entry point for LogicConsumerClosure@1."""

    return LogicConsumerClosure(package_root=package_root).scan()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _default_package_root() -> Path:
    """Return the ipfs_datasets_py package root (parent of nested package)."""

    # tests/conformance/logic/this_file.py → parents[3] == ipfs_datasets_py/
    return Path(__file__).resolve().parents[3]


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise ConsumerClosureError(f"required path missing: {path}")
    return path.read_text(encoding="utf-8")


def _historical_plans_marked_nonnormative(text: str) -> bool:
    lowered = text.casefold()
    if "nonnormative" not in lowered:
        return False
    if "historical" not in lowered:
        return False
    # Require explicit fixed-point handoff language.
    if "lfp-046" not in lowered:
        return False
    if "zero-drift" not in lowered and "zero drift" not in lowered:
        return False
    # At least one explicit historical-plan marker phrase.
    return any(marker.casefold() in lowered for marker in _NONNORMATIVE_MARKERS)


# ---------------------------------------------------------------------------
# Registered / emitted identity indexes
# ---------------------------------------------------------------------------


def _registered_identity_index() -> dict[tuple[str, str], str]:
    """Map (namespace, canonical_value) → source for registration checks."""

    index: dict[tuple[str, str], str] = {}
    for identity in BASELINE_NAMESPACES.identities():
        index[(identity.namespace.value, identity.value)] = "baseline_namespaces"
    for family_id in BASELINE_FAMILY_IDS:
        index.setdefault(("family", family_id), "baseline_family_ids")
    for family_id in DEFAULT_REGISTRY.families:
        index.setdefault(("family", family_id), "default_registry")
    for provider_id in (
        set(BASELINE_PROVIDER_IDS)
        | set(EXECUTABLE_PROVIDER_IDS)
        | set(ADVISORY_PROVIDER_IDS)
        | set(DEFAULT_GENERATED_CATALOG.provider_ids)
    ):
        index.setdefault(("provider", provider_id), "provider_catalogs")
    for alias, canonical in EXECUTABLE_PROVIDER_ALIASES.items():
        # Aliases are dual-read only; registration index keeps canonicals.
        index.setdefault(("provider", canonical), "executable_aliases")
        _ = alias
    try:
        from ipfs_datasets_py.logic.backends.registry import declared_backend_catalog

        for entry in declared_backend_catalog():
            if isinstance(entry, Mapping):
                provider_id = entry.get("provider_id") or entry.get("id")
            else:
                provider_id = getattr(entry, "provider_id", None) or getattr(
                    entry, "id", None
                )
            if provider_id:
                index.setdefault(
                    ("provider", str(provider_id)), "declared_backends"
                )
    except Exception:
        pass
    try:
        from ipfs_datasets_py.logic.backends.secpal_style_authorization import (
            PRODUCTION_AUTHORIZATION_PROVIDER_ID,
        )

        index.setdefault(
            ("provider", PRODUCTION_AUTHORIZATION_PROVIDER_ID),
            "production_authorization",
        )
    except Exception:
        pass
    for contribution in DEFAULT_PARSER_CATALOG:
        family_id = contribution.family_id
        if family_id:
            index.setdefault(("family", family_id), "parser_catalog")
        key = contribution.descriptor.key
        index.setdefault(("notation", key.notation_id), "parser_catalog")
        index.setdefault(("profile", key.semantic_profile_id), "parser_catalog")
    return index


def _collect_emitted_ids() -> list[dict[str, str]]:
    """Collect IDs emitted by public discovery and catalog surfaces."""

    emitted: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(namespace: str, value: str, source: str) -> None:
        value = str(value).strip()
        namespace = str(namespace).strip()
        if not value or not namespace:
            return
        key = (namespace, value)
        if key in seen:
            return
        seen.add(key)
        emitted.append(
            {
                "namespace": namespace,
                "value": value,
                "source": source,
            }
        )

    # Namespace discovery.
    ns_response = list_namespaces()
    ns_result = ns_response.result if isinstance(ns_response.result, Mapping) else {}
    for item in ns_result.get("namespaces", ()) or ():
        if isinstance(item, Mapping):
            _add("meta_namespace", str(item.get("namespace", "")), "list_namespaces")

    for kind in CANONICAL_NAMESPACE_KINDS:
        listed = list_namespace_identities(kind.value)
        listed_result = listed.result if isinstance(listed.result, Mapping) else {}
        for item in listed_result.get("identities", ()) or ():
            if not isinstance(item, Mapping):
                continue
            _add(
                str(item.get("namespace", kind.value)),
                str(item.get("value", "")),
                "list_namespace_identities",
            )

    families = list_logic_families()
    family_result = families.result if isinstance(families.result, Mapping) else {}
    for item in family_result.get("families", ()) or ():
        if isinstance(item, Mapping):
            _add("family", str(item.get("family_id", "")), "list_logic_families")

    providers = list_providers()
    provider_result = providers.result if isinstance(providers.result, Mapping) else {}
    for item in provider_result.get("providers", ()) or ():
        if not isinstance(item, Mapping):
            continue
        provider_id = item.get("provider_id") or item.get("id") or ""
        _add("provider", str(provider_id), "list_providers")
        for family in item.get("logic_families", ()) or ():
            if isinstance(family, Mapping):
                _add(
                    "family",
                    str(family.get("family_id", family.get("value", ""))),
                    "list_providers.logic_families",
                )
            else:
                _add("family", str(family), "list_providers.logic_families")

    discovery = get_canonical_discovery()
    for kind in CANONICAL_NAMESPACE_KINDS:
        for identity in discovery.list_identities(kind.value):
            if isinstance(identity, Mapping):
                _add(
                    str(identity.get("namespace", kind.value)),
                    str(identity.get("value", "")),
                    "CanonicalLogicDiscovery",
                )
            else:
                _add(kind.value, str(getattr(identity, "value", identity)), "CanonicalLogicDiscovery")

    for provider_id in DEFAULT_GENERATED_CATALOG.provider_ids:
        _add("provider", provider_id, "generated_catalog")
    for family_id in BASELINE_FAMILY_IDS:
        _add("family", family_id, "baseline_family_ids")
    for contribution in DEFAULT_PARSER_CATALOG:
        if contribution.family_id:
            _add("family", contribution.family_id, "parser_catalog")
        key = contribution.descriptor.key
        _add("notation", key.notation_id, "parser_catalog")
        _add("profile", key.semantic_profile_id, "parser_catalog")

    emitted.sort(key=lambda item: (item["namespace"], item["value"], item["source"]))
    return emitted


def _is_registered(
    namespace: str,
    value: str,
    registered: Mapping[tuple[str, str], str],
) -> bool:
    if (namespace, value) in registered:
        return True
    # Dual-read may map aliases; registration requires the canonical value.
    if namespace in {kind.value for kind in NamespaceKind}:
        try:
            response = dual_read_label(namespace, value)
        except Exception:
            return False
        result = response.result or {}
        if not isinstance(result, Mapping):
            return False
        canonical = result.get("canonical")
        if canonical and (namespace, str(canonical)) in registered:
            return True
        identity = result.get("identity")
        if isinstance(identity, Mapping):
            canon_value = identity.get("value")
            if canon_value and (namespace, str(canon_value)) in registered:
                return True
    return False


def _gaps_unregistered_emitted(
    emitted: Sequence[Mapping[str, str]],
    registered: Mapping[tuple[str, str], str],
) -> list[OwnerScopedTypedGap]:
    gaps: list[OwnerScopedTypedGap] = []
    for item in emitted:
        namespace = item["namespace"]
        value = item["value"]
        source = item.get("source", "unknown")
        if namespace == "meta_namespace":
            # Namespace names themselves are structural, not identity values.
            continue
        if namespace not in {kind.value for kind in NamespaceKind}:
            # Only typed identity namespaces participate in registration.
            continue
        if _is_registered(namespace, value, registered):
            continue
        owner = _owner_for_emitted_source(source)
        subject = f"{namespace}:{value}"
        evidence = f"emitted by {source} without registry membership"
        gaps.append(
            OwnerScopedTypedGap(
                gap_id=_stable_gap_id(
                    GapKind.UNREGISTERED_EMITTED_ID,
                    owner,
                    subject,
                    evidence=evidence,
                ),
                gap_kind=GapKind.UNREGISTERED_EMITTED_ID,
                owner=owner,
                subject=subject,
                evidence=evidence,
            )
        )
    return gaps


def _owner_for_emitted_source(source: str) -> str:
    if source.startswith("list_") or source.startswith("Canonical"):
        return "ipfs_datasets_py/logic/verification_api.py"
    if source == "generated_catalog":
        return "ipfs_datasets_py/logic/families/generated_catalog.py"
    if source == "parser_catalog":
        return "ipfs_datasets_py/logic/parsers/catalog.py"
    if source == "baseline_family_ids":
        return "ipfs_datasets_py/logic/families/registry.py"
    return "ipfs_datasets_py/logic/families"


# ---------------------------------------------------------------------------
# Controlled syntax documentation coverage
# ---------------------------------------------------------------------------


def _gaps_undocumented_controlled_syntax(
    normative_text: str,
) -> tuple[set[str], list[OwnerScopedTypedGap]]:
    documented: set[str] = set()
    # Backtick-wrapped tokens and table cells are documentation surface forms.
    for match in re.finditer(r"`([a-z][a-z0-9_]*)`", normative_text):
        documented.add(match.group(1))
    for match in re.finditer(
        r"\|\s*`?([a-z][a-z0-9_]*)`?\s*\|",
        normative_text,
    ):
        documented.add(match.group(1))

    required = (
        list(_CONTROLLED_NODE_KINDS)
        + list(_CONTROLLED_NOTATIONS)
        + list(_CONTROLLED_ENCODINGS)
    )
    gaps: list[OwnerScopedTypedGap] = []
    owner = _NORMATIVE_DOC_RELATIVE
    for form in required:
        if form in documented:
            continue
        evidence = "controlled syntax form missing from normative catalog §5.2"
        gaps.append(
            OwnerScopedTypedGap(
                gap_id=_stable_gap_id(
                    GapKind.UNDOCUMENTED_CONTROLLED_SYNTAX,
                    owner,
                    form,
                    evidence=evidence,
                ),
                gap_kind=GapKind.UNDOCUMENTED_CONTROLLED_SYNTAX,
                owner=owner,
                subject=form,
                evidence=evidence,
            )
        )
    present = {form for form in required if form in documented}
    return present, gaps


# ---------------------------------------------------------------------------
# Stale consumer scan
# ---------------------------------------------------------------------------


def _gaps_stale_consumers(package_root: Path) -> list[OwnerScopedTypedGap]:
    gaps: list[OwnerScopedTypedGap] = []
    for relative in _STALE_CONSUMER_SCAN_RELATIVES:
        path = package_root / relative
        if not path.is_file():
            # Missing owned consumer is itself a stale/missing consumer gap.
            evidence = "declared consumer path missing from package tree"
            gaps.append(
                OwnerScopedTypedGap(
                    gap_id=_stable_gap_id(
                        GapKind.STALE_CONSUMER,
                        relative,
                        relative,
                        evidence=evidence,
                    ),
                    gap_kind=GapKind.STALE_CONSUMER,
                    owner=relative,
                    subject=relative,
                    evidence=evidence,
                )
            )
            continue
        source = path.read_text(encoding="utf-8")
        for subject, evidence in _find_stale_family_writes(source, relative):
            gaps.append(
                OwnerScopedTypedGap(
                    gap_id=_stable_gap_id(
                        GapKind.STALE_CONSUMER,
                        relative,
                        subject,
                        evidence=evidence,
                    ),
                    gap_kind=GapKind.STALE_CONSUMER,
                    owner=relative,
                    subject=subject,
                    evidence=evidence,
                )
            )

    # Documentation consumers that still present legacy family labels as if
    # they were write values (outside dual-read teaching context).
    for relative in _PUBLIC_EXAMPLE_DOC_RELATIVES:
        path = package_root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for legacy in sorted(_LEGACY_FAMILY_WRITE_FORBIDDEN):
            # Look for patterns like family_id = "fol" or family="protocol".
            pattern = re.compile(
                rf"""(?:family(?:_id)?|logic_family)\s*[:=]\s*['"]{re.escape(legacy)}['"]""",
                re.IGNORECASE,
            )
            if pattern.search(text):
                evidence = (
                    f"public example writes legacy family surface {legacy!r}"
                )
                subject = f"{relative}:{legacy}"
                gaps.append(
                    OwnerScopedTypedGap(
                        gap_id=_stable_gap_id(
                            GapKind.STALE_CONSUMER,
                            relative,
                            subject,
                            evidence=evidence,
                        ),
                        gap_kind=GapKind.STALE_CONSUMER,
                        owner=relative,
                        subject=subject,
                        evidence=evidence,
                    )
                )
    return gaps


def _find_stale_family_writes(
    source: str,
    relative: str,
) -> list[tuple[str, str]]:
    """AST-scan *source* for legacy labels written into family-id fields."""

    findings: list[tuple[str, str]] = []
    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as error:
        return [
            (
                relative,
                f"consumer module failed to parse: {error.msg}",
            )
        ]

    class _Visitor(ast.NodeVisitor):
        def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
            for target in node.targets:
                self._check_target_value(target, node.value)
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
            if node.value is not None:
                self._check_target_value(node.target, node.value)
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            for keyword in node.keywords:
                if keyword.arg and keyword.arg in _FAMILY_WRITE_KEYS:
                    self._check_const(keyword.value, keyword.arg)
            self.generic_visit(node)

        def visit_Dict(self, node: ast.Dict) -> None:  # noqa: N802
            for key_node, value_node in zip(node.keys, node.values):
                if isinstance(key_node, ast.Constant) and isinstance(
                    key_node.value, str
                ):
                    if key_node.value in _FAMILY_WRITE_KEYS:
                        self._check_const(value_node, key_node.value)
            self.generic_visit(node)

        def _check_target_value(self, target: ast.AST, value: ast.AST) -> None:
            name = _target_name(target)
            if name and name in _FAMILY_WRITE_KEYS:
                self._check_const(value, name)

        def _check_const(self, value: ast.AST, field_name: str) -> None:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                label = value.value
                if label in _LEGACY_FAMILY_WRITE_FORBIDDEN:
                    findings.append(
                        (
                            f"{field_name}={label}",
                            (
                                "legacy free-form label written into family "
                                f"field {field_name!r} without dual-read"
                            ),
                        )
                    )
            elif isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                for elt in value.elts:
                    self._check_const(elt, field_name)

    _Visitor().visit(tree)
    return findings


def _target_name(target: ast.AST) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Subscript):
        sl = target.slice
        if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
            return sl.value
    return None


# ---------------------------------------------------------------------------
# Failing public examples
# ---------------------------------------------------------------------------


def _gaps_failing_public_examples(package_root: Path) -> list[OwnerScopedTypedGap]:
    gaps: list[OwnerScopedTypedGap] = []
    for relative in _PUBLIC_EXAMPLE_DOC_RELATIVES:
        path = package_root / relative
        if not path.is_file():
            evidence = "public example document missing"
            gaps.append(
                OwnerScopedTypedGap(
                    gap_id=_stable_gap_id(
                        GapKind.FAILING_PUBLIC_EXAMPLE,
                        relative,
                        relative,
                        evidence=evidence,
                    ),
                    gap_kind=GapKind.FAILING_PUBLIC_EXAMPLE,
                    owner=relative,
                    subject=relative,
                    evidence=evidence,
                )
            )
            continue
        text = path.read_text(encoding="utf-8")
        for index, block in enumerate(_FENCE_RE.findall(text)):
            example_id = f"{relative}#python-{index}"
            failure = _evaluate_public_example_block(block)
            if failure is None:
                continue
            gaps.append(
                OwnerScopedTypedGap(
                    gap_id=_stable_gap_id(
                        GapKind.FAILING_PUBLIC_EXAMPLE,
                        relative,
                        example_id,
                        evidence=failure,
                    ),
                    gap_kind=GapKind.FAILING_PUBLIC_EXAMPLE,
                    owner=relative,
                    subject=example_id,
                    evidence=failure,
                )
            )
    return gaps


def _evaluate_public_example_block(block: str) -> str | None:
    """Return a failure reason when a public example cannot be admitted.

    Hermetic policy: only import-resolution and syntax checks.  Examples are
    not executed (no network, no prover, no side effects).
    """

    stripped = block.strip()
    if not stripped:
        return "empty python example fence"

    try:
        ast.parse(stripped)
    except SyntaxError as error:
        return f"syntax error: {error.msg} (line {error.lineno})"

    # Resolve from-import targets against the live package when they target
    # ipfs_datasets_py.logic*. Missing symbols are typed gaps.
    for match in _IMPORT_FROM_RE.finditer(stripped):
        module_name = match.group(1).strip()
        names_blob = match.group(2)
        if not module_name.startswith("ipfs_datasets_py"):
            continue
        # Strip parenthetical / trailing comments.
        names_blob = names_blob.split("#", 1)[0].strip()
        if names_blob.startswith("("):
            names_blob = names_blob.strip("() \n\t")
        imported_names = [
            part.strip().split(" as ", 1)[0].strip()
            for part in names_blob.split(",")
            if part.strip() and part.strip() != "*"
        ]
        try:
            module = __import__(module_name, fromlist=imported_names or ["*"])
        except Exception as error:  # pragma: no cover - environment gaps
            return f"import failed: {module_name}: {type(error).__name__}: {error}"
        for name in imported_names:
            if name == "*":
                continue
            if not hasattr(module, name):
                return f"missing symbol: {module_name}.{name}"

    for match in _IMPORT_RE.finditer(stripped):
        for module_name in match.group(1).split(","):
            module_name = module_name.strip()
            if not module_name.startswith("ipfs_datasets_py"):
                continue
            try:
                __import__(module_name)
            except Exception as error:  # pragma: no cover
                return f"import failed: {module_name}: {type(error).__name__}: {error}"
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def closure_report() -> LogicConsumerClosureReport:
    return run_consumer_family_closure()


@pytest.fixture(scope="module")
def normative_doc_text() -> str:
    path = _default_package_root() / _NORMATIVE_DOC_RELATIVE
    return _read_text(path)


def test_interface_identity() -> None:
    closure = LogicConsumerClosure()
    assert closure.interface == LOGIC_CONSUMER_CLOSURE_INTERFACE
    assert closure.interface == "LogicConsumerClosure@1"
    payload = closure.to_dict()
    assert payload["interface"] == "LogicConsumerClosure@1"
    assert payload["task_id"] == "LFP-045"
    assert payload["fixed_point_owner_task_id"] == "LFP-046"


def test_normative_document_exists_and_declares_interfaces(
    normative_doc_text: str,
) -> None:
    assert "LogicSyntaxAndFamilyContracts@1" in normative_doc_text
    assert "LogicConsumerClosure@1" in normative_doc_text
    assert "LFP-045" in normative_doc_text
    assert "LFP-046" in normative_doc_text
    assert "canonical" in normative_doc_text.casefold()


def test_historical_plans_are_clearly_nonnormative(
    normative_doc_text: str,
) -> None:
    assert _historical_plans_marked_nonnormative(normative_doc_text)
    lowered = normative_doc_text.casefold()
    assert "nonnormative" in lowered
    assert "historical" in lowered
    # Explicit section / phrase from the leaf.
    assert "historical plans are nonnormative" in lowered
    assert "*_plan.md" in lowered or "historical plan" in lowered


def test_fixed_point_owned_by_lfp046_not_discovery(
    closure_report: LogicConsumerClosureReport,
) -> None:
    assert closure_report.task_id == "LFP-045"
    assert closure_report.fixed_point_owner_task_id == "LFP-046"
    assert closure_report.discovery_only is True
    assert closure_report.zero_drift is False
    assert closure_report.summary.get("zero_drift_claimed") is False
    # Discovery must not pretend the refill fixed point is closed.
    assert "LFP-046" in closure_report.to_json()


def test_static_closure_is_deterministic() -> None:
    first = run_consumer_family_closure()
    second = LogicConsumerClosure().scan()
    assert first.digest == second.digest
    assert first.to_json() == second.to_json()
    assert first.interface == LOGIC_CONSUMER_CLOSURE_INTERFACE


def test_every_gap_is_owner_scoped_typed(
    closure_report: LogicConsumerClosureReport,
) -> None:
    assert set(REQUIRED_GAP_KINDS) == {
        GapKind.UNREGISTERED_EMITTED_ID.value,
        GapKind.UNDOCUMENTED_CONTROLLED_SYNTAX.value,
        GapKind.STALE_CONSUMER.value,
        GapKind.FAILING_PUBLIC_EXAMPLE.value,
    }
    for gap in closure_report.gaps:
        assert gap.gap_kind.value in REQUIRED_GAP_KINDS
        assert gap.owner.strip()
        assert gap.subject.strip()
        assert gap.gap_id.startswith("lfp045:")
        assert gap.task_id == "LFP-045"
        assert gap.refill_eligible is True
        assert gap.schema_version == LOGIC_CONSUMER_GAP_SCHEMA
        wire = gap.to_dict()
        assert wire["owner"] == gap.owner
        assert wire["gap_kind"] == gap.gap_kind.value


def test_closure_records_all_four_gap_kinds_when_present(
    closure_report: LogicConsumerClosureReport,
) -> None:
    """Discovery records each kind that exists; taxonomy remains closed.

    This is not a zero-drift assertion.  When a kind has no current
    instances the report still admits the kind (count may be zero) and
    must not invent open kinds.
    """

    counts = closure_report.to_dict()["gap_counts_by_kind"]
    assert set(counts) == REQUIRED_GAP_KINDS
    for kind, count in counts.items():
        assert count == len(closure_report.gaps_of(kind))
        assert count >= 0
    # No open / free-form kinds.
    assert closure_report.gap_kinds_present <= REQUIRED_GAP_KINDS


def test_unregistered_emitted_ids_are_recorded_as_typed_gaps(
    closure_report: LogicConsumerClosureReport,
) -> None:
    registered = _registered_identity_index()
    for item in closure_report.emitted_ids:
        namespace = item["namespace"]
        value = item["value"]
        if namespace not in {kind.value for kind in NamespaceKind}:
            continue
        if _is_registered(namespace, value, registered):
            continue
        # Must appear as an owner-scoped unregistered gap.
        subject = f"{namespace}:{value}"
        matches = [
            gap
            for gap in closure_report.gaps_of(GapKind.UNREGISTERED_EMITTED_ID)
            if gap.subject == subject
        ]
        assert matches, f"missing unregistered emitted gap for {subject}"
        assert matches[0].owner.strip()


def test_undocumented_controlled_syntax_is_recorded(
    closure_report: LogicConsumerClosureReport,
    normative_doc_text: str,
) -> None:
    documented, expected_gaps = _gaps_undocumented_controlled_syntax(
        normative_doc_text
    )
    # Node kinds and notations that are documented must be listed.
    for kind in _CONTROLLED_NODE_KINDS:
        if kind in documented:
            assert kind in closure_report.controlled_syntax_documented
    # Every undocumented form must appear as a typed gap.
    expected_subjects = {gap.subject for gap in expected_gaps}
    actual_subjects = {
        gap.subject
        for gap in closure_report.gaps_of(GapKind.UNDOCUMENTED_CONTROLLED_SYNTAX)
    }
    assert expected_subjects == actual_subjects
    for gap in closure_report.gaps_of(GapKind.UNDOCUMENTED_CONTROLLED_SYNTAX):
        assert gap.owner == _NORMATIVE_DOC_RELATIVE


def test_stale_consumers_are_owner_scoped(
    closure_report: LogicConsumerClosureReport,
) -> None:
    for gap in closure_report.gaps_of(GapKind.STALE_CONSUMER):
        assert gap.owner.strip()
        assert (
            gap.owner.endswith(".py")
            or gap.owner.endswith(".md")
            or "/" in gap.owner
        )
        assert "legacy" in gap.evidence.casefold() or "missing" in gap.evidence.casefold()


def test_failing_public_examples_are_owner_scoped(
    closure_report: LogicConsumerClosureReport,
) -> None:
    for gap in closure_report.gaps_of(GapKind.FAILING_PUBLIC_EXAMPLE):
        assert gap.owner in _PUBLIC_EXAMPLE_DOC_RELATIVES or gap.owner.endswith(
            ".md"
        )
        assert gap.subject
        assert gap.evidence


def test_report_wire_format_and_refill_eligibility(
    closure_report: LogicConsumerClosureReport,
) -> None:
    wire = closure_report.to_dict()
    assert wire["interface"] == "LogicConsumerClosure@1"
    assert wire["schema_version"] == LOGIC_CONSUMER_CLOSURE_SCHEMA
    assert wire["task_id"] == "LFP-045"
    assert wire["goal_id"] == "LFP-G090"
    assert wire["fixed_point_owner_task_id"] == "LFP-046"
    assert wire["discovery_only"] is True
    assert wire["zero_drift"] is False
    assert wire["historical_plans_nonnormative"] is True
    for gap in wire["gaps"]:
        assert gap["refill_eligible"] is True
        assert gap["task_id"] == "LFP-045"
        assert gap["gap_kind"] in REQUIRED_GAP_KINDS
        assert gap["owner"]
        assert gap["subject"]


def test_gap_record_rejects_open_kinds_and_wrong_fixed_point() -> None:
    with pytest.raises(ConsumerClosureError):
        OwnerScopedTypedGap(
            gap_id="x",
            gap_kind="not_a_real_kind",  # type: ignore[arg-type]
            owner="owner",
            subject="subject",
            evidence="e",
        )
    with pytest.raises(ConsumerClosureError):
        LogicConsumerClosureReport(
            gaps=(),
            emitted_ids=(),
            controlled_syntax_documented=(),
            historical_plans_nonnormative=True,
            discovery_only=True,
            zero_drift=True,  # forbidden for discovery
        )
    with pytest.raises(ConsumerClosureError):
        LogicConsumerClosureReport(
            gaps=(),
            emitted_ids=(),
            controlled_syntax_documented=(),
            historical_plans_nonnormative=True,
            fixed_point_owner_task_id="LFP-045",  # wrong owner
        )


def test_public_discovery_emits_only_canonical_family_writes() -> None:
    """Sanity: discovery family list never writes legacy free-form labels."""

    response = list_logic_families()
    result = response.result if isinstance(response.result, Mapping) else {}
    families = result.get("families", ()) or ()
    namespace_family_ids = {
        identity.value
        for identity in BASELINE_NAMESPACES.identities(NamespaceKind.FAMILY)
    }
    for item in families:
        if not isinstance(item, Mapping):
            continue
        family_id = str(item.get("family_id", ""))
        assert family_id not in {"fol", "protocol", "smt", "VC", "runtime"}
        assert family_id == family_id.casefold()
        # When the id is in the sealed namespace catalog, dual-read is identity.
        if family_id in namespace_family_ids:
            resolved = dual_read_label("family", family_id)
            assert resolved.result is not None
            assert resolved.result.get("canonical") == family_id


def test_controlled_syntax_catalog_covers_core_node_kinds(
    normative_doc_text: str,
) -> None:
    for kind in _CONTROLLED_NODE_KINDS:
        assert (
            f"`{kind}`" in normative_doc_text or f"| {kind} " in normative_doc_text
        ), f"NodeKind {kind!r} missing from normative controlled syntax catalog"
    for notation in _CONTROLLED_NOTATIONS:
        assert (
            f"`{notation}`" in normative_doc_text
            or notation in normative_doc_text
        )
    for encoding in _CONTROLLED_ENCODINGS:
        assert (
            f"`{encoding}`" in normative_doc_text
            or encoding in normative_doc_text
        )


def test_scan_records_injected_gaps_for_each_kind(tmp_path: Path) -> None:
    """Fixture package proves each gap kind is recorded with owner scope."""

    # Build a minimal package layout with intentional drift.
    root = tmp_path
    doc_path = root / _NORMATIVE_DOC_RELATIVE
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    # Incomplete controlled syntax (missing many node kinds) + nonnormative.
    doc_path.write_text(
        "\n".join(
            [
                "# fixture",
                "Interface: LogicSyntaxAndFamilyContracts@1, LogicConsumerClosure@1",
                "Task: LFP-045",
                "Historical plans are nonnormative.",
                "LFP-046 owns the zero-drift fixed point.",
                "Controlled: `constant` `variable`",
                "Notations: `canonical_text`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    # Stale consumer module.
    consumer_rel = _STALE_CONSUMER_SCAN_RELATIVES[0]
    consumer_path = root / consumer_rel
    consumer_path.parent.mkdir(parents=True, exist_ok=True)
    consumer_path.write_text(
        'family_id = "fol"\nlogic_family = "protocol"\n',
        encoding="utf-8",
    )
    # Failing public example.
    example_rel = _PUBLIC_EXAMPLE_DOC_RELATIVES[0]
    example_path = root / example_rel
    example_path.parent.mkdir(parents=True, exist_ok=True)
    example_path.write_text(
        "```python\n"
        "from ipfs_datasets_py.logic.this_module_does_not_exist import Missing\n"
        "```\n",
        encoding="utf-8",
    )

    # Run only the path-local gap extractors against the fixture root for
    # stale/docs kinds; unregistered emitted still uses live discovery.
    normative_text = doc_path.read_text(encoding="utf-8")
    assert _historical_plans_marked_nonnormative(normative_text)

    _, syntax_gaps = _gaps_undocumented_controlled_syntax(normative_text)
    stale_gaps = _gaps_stale_consumers(root)
    example_gaps = _gaps_failing_public_examples(root)

    assert syntax_gaps
    assert any(
        gap.gap_kind is GapKind.UNDOCUMENTED_CONTROLLED_SYNTAX
        for gap in syntax_gaps
    )
    assert any(gap.owner == _NORMATIVE_DOC_RELATIVE for gap in syntax_gaps)

    assert stale_gaps
    assert any(gap.gap_kind is GapKind.STALE_CONSUMER for gap in stale_gaps)
    assert any("fol" in gap.subject for gap in stale_gaps)

    assert example_gaps
    assert any(
        gap.gap_kind is GapKind.FAILING_PUBLIC_EXAMPLE for gap in example_gaps
    )
    assert all(gap.owner.strip() for gap in example_gaps)

    # Compose a discovery report and seal.
    report = LogicConsumerClosureReport(
        gaps=tuple(syntax_gaps + stale_gaps + example_gaps),
        emitted_ids=(),
        controlled_syntax_documented=("constant", "variable", "canonical_text"),
        historical_plans_nonnormative=True,
        discovery_only=True,
        zero_drift=False,
        summary={"fixture": True},
    )
    assert report.fixed_point_owner_task_id == "LFP-046"
    present = report.gap_kinds_present
    assert GapKind.UNDOCUMENTED_CONTROLLED_SYNTAX.value in present
    assert GapKind.STALE_CONSUMER.value in present
    assert GapKind.FAILING_PUBLIC_EXAMPLE.value in present
    for gap in report.gaps:
        assert gap.refill_eligible is True
        assert gap.owner


def test_unregistered_emitted_gap_helper_owner_scopes() -> None:
    registered = _registered_identity_index()
    fake_emitted = [
        {
            "namespace": "family",
            "value": "not_a_registered_family_xyz",
            "source": "list_logic_families",
        }
    ]
    gaps = _gaps_unregistered_emitted(fake_emitted, registered)
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.gap_kind is GapKind.UNREGISTERED_EMITTED_ID
    assert gap.owner == "ipfs_datasets_py/logic/verification_api.py"
    assert gap.subject == "family:not_a_registered_family_xyz"
    assert gap.refill_eligible is True
