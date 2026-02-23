"""Profile A: MCP-IDL — CID-Addressed Interface Contracts.

Implements the MCP++ Profile A specification from:
https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/spec/mcp-idl.md

An Interface Descriptor is a canonical, content-addressed contract describing a
tool/resource interface. Its CID is used for deterministic compatibility checks
and runtime discovery without fragmentation.

Profiles supported:
- ``interfaces/list``   — list all known interface CIDs
- ``interfaces/get``    — retrieve an Interface Descriptor by CID
- ``interfaces/compat`` — check compatibility with a given interface CID
- ``interfaces/select`` — toolset slicing under a context/token budget
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helper: canonical JSON → CID (SHA-256 hex, prefixed "bafy-mock-")
# ---------------------------------------------------------------------------

def _canonical_cid(obj: Any) -> str:
    """Compute a deterministic mock-CID for any JSON-serialisable object.

    In production this should use DAG-JSON or DAG-CBOR canonicalisation and a
    real multihash, but a stable SHA-256 hex is sufficient for the current
    implementation stage.

    Args:
        obj: Any JSON-serialisable Python object.

    Returns:
        A stable, content-derived string identifier prefixed ``"bafy-mock-"``.
    """
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"bafy-mock-{digest[:32]}"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MethodSignature:
    """A single method signature within an Interface Descriptor.

    Attributes:
        name: Stable method name.
        input_schema: JSON Schema dict for input parameters.
        output_schema: JSON Schema dict for the return value.
        error_names: Names of errors this method may raise.
    """

    name: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    error_names: List[str] = field(default_factory=list)


@dataclass
class CompatibilityInfo:
    """Compatibility metadata for an Interface Descriptor.

    Attributes:
        compatible_with: Interface CIDs this descriptor is backward-compatible with.
        supersedes: Interface CIDs that this descriptor replaces.
    """

    compatible_with: List[str] = field(default_factory=list)
    supersedes: List[str] = field(default_factory=list)


@dataclass
class InterfaceDescriptor:
    """A canonical, content-addressed interface contract (Profile A).

    Implements the normative "Interface Descriptor" shape from MCP++ MCP-IDL spec.

    Required fields per spec:
        name, namespace, version, methods, errors, requires, compatibility

    Attributes:
        name: Stable human identifier for the interface.
        namespace: Grouping / ownership scope (e.g. ``"com.example.tools"``).
        version: Semantic version string (e.g. ``"1.0.0"``).
        methods: Method signatures exposed by this interface.
        errors: Error type names surfaced by the interface.
        requires: Capability/extension identifiers required at runtime.
        compatibility: Compatibility metadata (supersedes / compatible_with).
        semantic_tags: Optional stable tags for retrieval and tool selection.
        resource_cost_hints: Optional runtime/token/network cost hints.
    """

    name: str
    namespace: str
    version: str
    methods: List[MethodSignature] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)
    compatibility: CompatibilityInfo = field(default_factory=CompatibilityInfo)
    semantic_tags: List[str] = field(default_factory=list)
    resource_cost_hints: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Derived / cached
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict suitable for JSON canonicalisation.

        Returns:
            Ordered dict representation of this descriptor.
        """
        return {
            "name": self.name,
            "namespace": self.namespace,
            "version": self.version,
            "methods": [
                {
                    "name": m.name,
                    "input_schema": m.input_schema,
                    "output_schema": m.output_schema,
                    "error_names": m.error_names,
                }
                for m in self.methods
            ],
            "errors": self.errors,
            "requires": self.requires,
            "compatibility": {
                "compatible_with": self.compatibility.compatible_with,
                "supersedes": self.compatibility.supersedes,
            },
            "semantic_tags": self.semantic_tags,
            "resource_cost_hints": self.resource_cost_hints,
        }

    @property
    def interface_cid(self) -> str:
        """Content-addressed CID of this descriptor.

        Returns:
            Stable, deterministic CID string derived from canonical bytes.
        """
        return _canonical_cid(self.to_dict())


# ---------------------------------------------------------------------------
# Compatibility verdict
# ---------------------------------------------------------------------------

@dataclass
class CompatVerdict:
    """Result of an ``interfaces/compat`` check.

    Attributes:
        compatible: Whether the queried interface is compatible with this repo.
        reasons: Human-readable reasons for any incompatibility.
        requires_missing: Capability identifiers absent from the local server.
        suggested_alternatives: CIDs that may satisfy the requester's intent.
    """

    compatible: bool
    reasons: List[str] = field(default_factory=list)
    requires_missing: List[str] = field(default_factory=list)
    suggested_alternatives: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Interface Repository (Profile A APIs)
# ---------------------------------------------------------------------------

class InterfaceRepository:
    """Runtime-queryable registry of Interface Descriptors (Profile A).

    Implements the three normative API endpoints from the MCP++ MCP-IDL spec:

    - ``list()``                 → ``interfaces/list``
    - ``get(interface_cid)``     → ``interfaces/get``
    - ``check_compat(...)``      → ``interfaces/compat``

    And the optional toolset-slicing endpoint:

    - ``toolset_slice(...)``     → ``interfaces/select``

    Attributes:
        _store: Internal mapping from ``interface_cid`` to ``InterfaceDescriptor``.
    """

    def __init__(self) -> None:
        """Initialise an empty Interface Repository."""
        self._store: Dict[str, InterfaceDescriptor] = {}

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def register(self, descriptor: InterfaceDescriptor) -> str:
        """Register an Interface Descriptor and return its CID.

        Args:
            descriptor: The descriptor to register.

        Returns:
            The ``interface_cid`` under which the descriptor is stored.
        """
        cid = descriptor.interface_cid
        self._store[cid] = descriptor
        return cid

    # ------------------------------------------------------------------
    # interfaces/list
    # ------------------------------------------------------------------

    def list(self) -> List[str]:
        """Return all known interface CIDs.

        Returns:
            List of ``interface_cid`` strings registered in this repository.
        """
        return list(self._store.keys())

    # ------------------------------------------------------------------
    # interfaces/get
    # ------------------------------------------------------------------

    def get(self, interface_cid: str) -> Optional[InterfaceDescriptor]:
        """Retrieve an Interface Descriptor by CID.

        Args:
            interface_cid: The CID to look up.

        Returns:
            The matching ``InterfaceDescriptor``, or ``None`` if not found.
        """
        return self._store.get(interface_cid)

    # ------------------------------------------------------------------
    # interfaces/compat
    # ------------------------------------------------------------------

    def check_compat(
        self,
        interface_cid: str,
        local_capabilities: Optional[List[str]] = None,
    ) -> CompatVerdict:
        """Check whether a given interface CID is compatible with this server.

        An interface is compatible when:
        1. It is registered in this repository, OR its CID appears in the
           ``compatibility.compatible_with`` list of a registered descriptor.
        2. All ``requires`` capabilities are present in *local_capabilities*.

        Args:
            interface_cid: CID of the interface to check.
            local_capabilities: Capabilities supported by the local server.

        Returns:
            A ``CompatVerdict`` describing compatibility status and reasons.
        """
        local_caps: List[str] = local_capabilities or []

        # Direct match
        if interface_cid in self._store:
            descriptor = self._store[interface_cid]
            missing = [r for r in descriptor.requires if r not in local_caps]
            if missing:
                return CompatVerdict(
                    compatible=False,
                    reasons=[f"Missing required capabilities: {missing}"],
                    requires_missing=missing,
                )
            return CompatVerdict(compatible=True)

        # Check via compatibility.compatible_with on registered descriptors
        alternatives: List[str] = []
        for cid, desc in self._store.items():
            if interface_cid in desc.compatibility.compatible_with:
                alternatives.append(cid)

        if alternatives:
            return CompatVerdict(
                compatible=True,
                reasons=["Compatible via registered superseding descriptor"],
                suggested_alternatives=alternatives,
            )

        # Not found at all
        return CompatVerdict(
            compatible=False,
            reasons=[f"Interface CID {interface_cid!r} not found in repository"],
            suggested_alternatives=list(self._store.keys())[:5],
        )

    # ------------------------------------------------------------------
    # interfaces/select  (toolset slicing)
    # ------------------------------------------------------------------

    def toolset_slice(
        self,
        semantic_tags: Optional[List[str]] = None,
        budget: Optional[int] = None,
        required_capabilities: Optional[List[str]] = None,
    ) -> List[str]:
        """Select a subset of interface CIDs that match constraints (Profile A).

        This implements the optional ``interfaces/select`` endpoint for toolset
        slicing under context/token budgets.

        Args:
            semantic_tags: If provided, only return interfaces whose
                ``semantic_tags`` overlap with this list.
            budget: Maximum number of interfaces to return. ``None`` means no cap.
            required_capabilities: Only return interfaces whose ``requires``
                list is a subset of *required_capabilities* (i.e. all requirements
                are satisfied by the caller).

        Returns:
            List of ``interface_cid`` strings satisfying all constraints.
        """
        results: List[str] = []
        for cid, desc in self._store.items():
            # Tag filter
            if semantic_tags:
                if not any(t in desc.semantic_tags for t in semantic_tags):
                    continue
            # Capability filter
            if required_capabilities is not None:
                if any(r not in required_capabilities for r in desc.requires):
                    continue
            results.append(cid)
            if budget is not None and len(results) >= budget:
                break
        return results

    def __len__(self) -> int:
        """Return the number of registered descriptors."""
        return len(self._store)

    def __repr__(self) -> str:  # pragma: no cover
        return f"InterfaceRepository({len(self._store)} descriptors)"
