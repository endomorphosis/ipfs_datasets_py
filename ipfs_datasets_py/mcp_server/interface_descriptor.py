"""
Profile A: MCP-IDL — CID-Addressed Interface Contracts

Implements the MCP-IDL profile from the MCP++ specification:
  https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/spec/mcp-idl.md

This module provides:
- InterfaceDescriptor: canonical, content-addressed tool/resource contract
- InterfaceRepository: runtime query APIs (list / get / compat)
- toolset_slice(): optional budget-aware interface selection

Backward-compatible: does not change any MCP JSON-RPC message semantics.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── canonicalization ────────────────────────────────────────────────────────


def _canonicalize(obj: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes (sorted keys, no extra whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def compute_cid(content: bytes, *, prefix: str = "sha256:") -> str:
    """Compute a CID-like identifier from raw bytes.

    In a full deployment this would use the multihash / CIDv1 spec.
    For now we use a ``sha256:<hex>`` prefix that is deterministic and
    collision-resistant, keeping the implementation dependency-free.
    """
    digest = hashlib.sha256(content).hexdigest()
    return f"{prefix}{digest}"


# ─── data model ─────────────────────────────────────────────────────────────


@dataclass
class MethodSignature:
    """A single method exposed by an interface."""
    name: str
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)
    streaming: bool = False


@dataclass
class InterfaceDescriptor:
    """
    Content-addressed interface contract (Profile A: MCP-IDL).

    Attributes match the normative fields from the spec:
      name, namespace, version, methods, errors, requires, compatibility,
      semantic_tags, observability, interaction_patterns, resource_cost_hints.
    """
    # Required fields (spec §4.1)
    name: str
    namespace: str
    version: str
    methods: List[MethodSignature] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)
    compatibility: Dict[str, List[str]] = field(
        default_factory=lambda: {"compatible_with": [], "supersedes": []}
    )
    # Recommended fields (spec §4.2)
    semantic_tags: List[str] = field(default_factory=list)
    observability: Dict[str, bool] = field(
        default_factory=lambda: {"trace": False, "provenance": False}
    )
    interaction_patterns: Dict[str, bool] = field(
        default_factory=lambda: {"request_response": True, "event_streams": False}
    )
    resource_cost_hints: Optional[Dict[str, Any]] = None

    # ── derived (not persisted) ───────────────────────────────────────────────
    _interface_cid: Optional[str] = field(default=None, repr=False, compare=False)

    @property
    def interface_cid(self) -> str:
        """Lazily compute the interface_cid from canonical bytes."""
        if self._interface_cid is None:
            self._interface_cid = compute_cid(self.canonical_bytes())
        return self._interface_cid

    def canonical_bytes(self) -> bytes:
        """Return the canonical serialisation of this descriptor."""
        d = {
            "name": self.name,
            "namespace": self.namespace,
            "version": self.version,
            "methods": [
                {
                    "name": m.name,
                    "input_schema": m.input_schema,
                    "output_schema": m.output_schema,
                    "errors": sorted(m.errors),
                    "streaming": m.streaming,
                }
                for m in sorted(self.methods, key=lambda x: x.name)
            ],
            "errors": sorted(self.errors),
            "requires": sorted(self.requires),
            "compatibility": {
                "compatible_with": sorted(self.compatibility.get("compatible_with", [])),
                "supersedes": sorted(self.compatibility.get("supersedes", [])),
            },
            "semantic_tags": sorted(self.semantic_tags),
            "observability": self.observability,
            "interaction_patterns": self.interaction_patterns,
        }
        return _canonicalize(d)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict including the interface_cid."""
        d = json.loads(self.canonical_bytes())
        d["interface_cid"] = self.interface_cid
        if self.resource_cost_hints:
            d["resource_cost_hints"] = self.resource_cost_hints
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InterfaceDescriptor":
        """Reconstruct from a dict (e.g. from JSON)."""
        methods = [
            MethodSignature(
                name=m["name"],
                input_schema=m.get("input_schema"),
                output_schema=m.get("output_schema"),
                errors=m.get("errors", []),
                streaming=m.get("streaming", False),
            )
            for m in data.get("methods", [])
        ]
        obj = cls(
            name=data["name"],
            namespace=data["namespace"],
            version=data["version"],
            methods=methods,
            errors=data.get("errors", []),
            requires=data.get("requires", []),
            compatibility=data.get("compatibility",
                                   {"compatible_with": [], "supersedes": []}),
            semantic_tags=data.get("semantic_tags", []),
            observability=data.get("observability",
                                   {"trace": False, "provenance": False}),
            interaction_patterns=data.get("interaction_patterns",
                                          {"request_response": True,
                                           "event_streams": False}),
            resource_cost_hints=data.get("resource_cost_hints"),
        )
        return obj


# ─── compat logic ────────────────────────────────────────────────────────────


@dataclass
class CompatVerdict:
    """Result of interfaces/compat."""
    compatible: bool
    reasons: List[str] = field(default_factory=list)
    requires_missing: List[str] = field(default_factory=list)
    suggested_alternatives: List[str] = field(default_factory=list)


def check_compat(
    candidate: InterfaceDescriptor,
    required: InterfaceDescriptor,
) -> CompatVerdict:
    """Check whether *candidate* satisfies *required*'s method surface."""
    reasons: List[str] = []
    missing_requires: List[str] = []

    required_methods = {m.name for m in required.methods}
    candidate_methods = {m.name for m in candidate.methods}
    missing = required_methods - candidate_methods
    if missing:
        reasons.append(f"Missing methods: {sorted(missing)}")

    for req in required.requires:
        if req not in candidate.requires:
            missing_requires.append(req)
            reasons.append(f"Missing capability requirement: {req}")

    compatible = len(reasons) == 0
    return CompatVerdict(
        compatible=compatible,
        reasons=reasons,
        requires_missing=missing_requires,
        suggested_alternatives=candidate.compatibility.get("supersedes", []),
    )


# ─── repository ──────────────────────────────────────────────────────────────


class InterfaceRepository:
    """
    In-memory Interface Repository implementing the MCP-IDL APIs.

    MCP-IDL servers MUST expose (spec §5):
      interfaces/list
      interfaces/get(interface_cid)
      interfaces/compat(interface_cid)

    Optional:
      interfaces/select(task_hint_cid, budget)
    """

    def __init__(self) -> None:
        self._store: Dict[str, InterfaceDescriptor] = {}

    # ── write ─────────────────────────────────────────────────────────────────

    def register(self, descriptor: InterfaceDescriptor) -> str:
        """Store a descriptor and return its interface_cid."""
        cid = descriptor.interface_cid
        self._store[cid] = descriptor
        logger.debug("Registered interface %s (%s)", descriptor.name, cid)
        return cid

    # ── read (spec §5) ────────────────────────────────────────────────────────

    def list(self) -> List[str]:
        """interfaces/list → list of known interface_cids."""
        return list(self._store.keys())

    def get(self, interface_cid: str) -> Optional[Dict[str, Any]]:
        """interfaces/get → canonical descriptor dict, or None."""
        desc = self._store.get(interface_cid)
        return desc.to_dict() if desc else None

    def compat(
        self,
        interface_cid: str,
        *,
        required_cid: Optional[str] = None,
    ) -> CompatVerdict:
        """interfaces/compat → CompatVerdict.

        If *required_cid* is given, check whether the named interface satisfies
        the required one.  Otherwise return a trivially-compatible verdict.
        """
        candidate = self._store.get(interface_cid)
        if candidate is None:
            return CompatVerdict(
                compatible=False,
                reasons=[f"Unknown interface_cid: {interface_cid}"],
            )

        if required_cid is None:
            return CompatVerdict(compatible=True)

        required = self._store.get(required_cid)
        if required is None:
            return CompatVerdict(
                compatible=False,
                reasons=[f"Unknown required interface_cid: {required_cid}"],
            )

        return check_compat(candidate, required)

    def select(
        self,
        task_hint: str,
        budget: Optional[int] = None,
    ) -> List[str]:
        """interfaces/select → recommended subset of interface CIDs.

        Non-normative: returns all interfaces whose semantic_tags overlap with
        words in *task_hint*, limited to *budget* entries.
        """
        hint_words = set(task_hint.lower().split())
        scored: List[tuple[int, str]] = []
        for cid, desc in self._store.items():
            overlap = sum(
                1 for tag in desc.semantic_tags
                if tag.lower() in hint_words
            )
            if overlap > 0:
                scored.append((overlap, cid))

        scored.sort(key=lambda x: -x[0])
        result = [cid for _, cid in scored]
        if budget is not None:
            result = result[:budget]
        return result

    def __len__(self) -> int:
        return len(self._store)


# ─── budget-aware toolset slice (spec §7) ────────────────────────────────────


def toolset_slice(
    cids: List[str],
    budget: Optional[int] = None,
    sort_fn: Optional[Any] = None,
) -> List[str]:
    """Return a budget-bounded slice of interface CIDs.

    Args:
        cids:    Ordered list of interface CID strings (most-preferred first).
        budget:  Maximum number of CIDs to return.  ``None`` means no limit.
        sort_fn: Optional callable ``(cid: str) -> comparable`` used to
                 re-rank *cids* before slicing.  The list is sorted in
                 *ascending* order of the key (lowest key = most preferred).

    Returns:
        A new list of at most *budget* CIDs, optionally reranked.

    Example::

        repo = get_interface_repository()
        scored = repo.select("embedding search", budget=None)
        top3 = toolset_slice(scored, budget=3)
    """
    result = list(cids)
    if sort_fn is not None:
        result.sort(key=sort_fn)
    if budget is not None:
        result = result[:budget]
    return result


# ─── module-level singleton ───────────────────────────────────────────────────

_global_repo: Optional[InterfaceRepository] = None


def get_interface_repository() -> InterfaceRepository:
    """Return the process-global Interface Repository (lazy-init)."""
    global _global_repo
    if _global_repo is None:
        _global_repo = InterfaceRepository()
    return _global_repo
