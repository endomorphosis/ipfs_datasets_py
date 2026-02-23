"""Profile A: MCP-IDL — CID-addressed interface contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = [
    "_canonicalize",
    "compute_cid",
    "_canonical_cid",
    "MethodSignature",
    "CompatibilityInfo",
    "InterfaceDescriptor",
    "CompatVerdict",
    "InterfaceRepository",
    "toolset_slice",
    "get_interface_repository",
]


def _canonicalize(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def compute_cid(content: bytes, *, prefix: str = "sha256:") -> str:
    digest = hashlib.sha256(content).hexdigest()
    return f"{prefix}{digest}"


def _canonical_cid(obj: Any) -> str:
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"bafy-mock-{digest[:32]}"


@dataclass
class MethodSignature:
    """A single method signature within an Interface Descriptor."""

    name: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    error_names: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    streaming: bool = False


@dataclass
class CompatibilityInfo:
    """Compatibility metadata for an Interface Descriptor."""

    compatible_with: List[str] = field(default_factory=list)
    supersedes: List[str] = field(default_factory=list)


@dataclass
class InterfaceDescriptor:
    """A canonical, content-addressed interface contract (Profile A)."""

    name: str
    namespace: str
    version: str
    methods: List[MethodSignature] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)
    compatibility: CompatibilityInfo | Dict[str, List[str]] = field(default_factory=CompatibilityInfo)
    semantic_tags: List[str] = field(default_factory=list)
    observability: Dict[str, bool] = field(default_factory=lambda: {"trace": False, "provenance": False})
    interaction_patterns: Dict[str, bool] = field(default_factory=lambda: {"request_response": True, "event_streams": False})
    resource_cost_hints: Optional[Dict[str, Any]] = None

    _interface_cid: Optional[str] = field(default=None, repr=False, compare=False)

    def _compat_dict(self) -> Dict[str, List[str]]:
        if isinstance(self.compatibility, CompatibilityInfo):
            return {
                "compatible_with": list(self.compatibility.compatible_with),
                "supersedes": list(self.compatibility.supersedes),
            }
        return {
            "compatible_with": list(self.compatibility.get("compatible_with", [])),
            "supersedes": list(self.compatibility.get("supersedes", [])),
        }

    def canonical_bytes(self) -> bytes:
        d = {
            "name": self.name,
            "namespace": self.namespace,
            "version": self.version,
            "methods": [
                {
                    "name": m.name,
                    "input_schema": m.input_schema,
                    "output_schema": m.output_schema,
                    "errors": sorted(m.errors or m.error_names),
                    "streaming": m.streaming,
                }
                for m in sorted(self.methods, key=lambda x: x.name)
            ],
            "errors": sorted(self.errors),
            "requires": sorted(self.requires),
            "compatibility": {
                "compatible_with": sorted(self._compat_dict().get("compatible_with", [])),
                "supersedes": sorted(self._compat_dict().get("supersedes", [])),
            },
            "semantic_tags": sorted(self.semantic_tags),
            "observability": self.observability,
            "interaction_patterns": self.interaction_patterns,
        }
        return _canonicalize(d)

    @property
    def interface_cid(self) -> str:
        if self._interface_cid is None:
            self._interface_cid = compute_cid(self.canonical_bytes())
        return self._interface_cid

    def to_dict(self) -> Dict[str, Any]:
        d = json.loads(self.canonical_bytes())
        d["interface_cid"] = self.interface_cid
        if self.resource_cost_hints:
            d["resource_cost_hints"] = self.resource_cost_hints
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InterfaceDescriptor":
        methods = [
            MethodSignature(
                name=m["name"],
                input_schema=m.get("input_schema", {}),
                output_schema=m.get("output_schema", {}),
                error_names=m.get("error_names", []) or m.get("errors", []),
                errors=m.get("errors", []) or m.get("error_names", []),
                streaming=m.get("streaming", False),
            )
            for m in data.get("methods", [])
        ]
        compat = data.get("compatibility", {"compatible_with": [], "supersedes": []})
        if isinstance(compat, dict):
            compat = CompatibilityInfo(
                compatible_with=compat.get("compatible_with", []),
                supersedes=compat.get("supersedes", []),
            )
        obj = cls(
            name=data["name"],
            namespace=data["namespace"],
            version=data["version"],
            methods=methods,
            errors=data.get("errors", []),
            requires=data.get("requires", []),
            compatibility=compat,
            semantic_tags=data.get("semantic_tags", []),
            observability=data.get("observability", {"trace": False, "provenance": False}),
            interaction_patterns=data.get(
                "interaction_patterns",
                {"request_response": True, "event_streams": False},
            ),
            resource_cost_hints=data.get("resource_cost_hints"),
        )
        return obj


@dataclass
class CompatVerdict:
    compatible: bool
    reasons: List[str] = field(default_factory=list)
    requires_missing: List[str] = field(default_factory=list)
    suggested_alternatives: List[str] = field(default_factory=list)


def check_compat(candidate: InterfaceDescriptor, required: InterfaceDescriptor) -> CompatVerdict:
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
        suggested_alternatives=candidate._compat_dict().get("supersedes", []),
    )


class InterfaceRepository:
    """In-memory Interface Repository implementing MCP-IDL APIs."""

    def __init__(self) -> None:
        self._store: Dict[str, InterfaceDescriptor] = {}

    def register(self, descriptor: InterfaceDescriptor) -> str:
        cid = descriptor.interface_cid
        self._store[cid] = descriptor
        return cid

    def list(self) -> List[str]:
        return list(self._store.keys())

    def get(self, interface_cid: str) -> Optional[Dict[str, Any]]:
        desc = self._store.get(interface_cid)
        return desc.to_dict() if desc else None

    def compat(
        self,
        interface_cid: str,
        *,
        required_cid: Optional[str] = None,
    ) -> CompatVerdict:
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

    def select(self, task_hint: str, budget: Optional[int] = None) -> List[str]:
        hint_words = set(task_hint.lower().split())
        scored: List[tuple[int, str]] = []
        for cid, desc in self._store.items():
            overlap = sum(1 for tag in desc.semantic_tags if tag.lower() in hint_words)
            if overlap > 0:
                scored.append((overlap, cid))
        scored.sort(key=lambda x: -x[0])
        result = [cid for _, cid in scored]
        if budget is not None:
            result = result[:budget]
        return result

    def toolset_slice(
        self,
        *,
        budget: Optional[int] = None,
        semantic_tags: Optional[List[str]] = None,
        required_capabilities: Optional[List[str]] = None,
    ) -> List[str]:
        cids = list(self._store.keys())
        if semantic_tags:
            allowed = set(tag.lower() for tag in semantic_tags)
            cids = [
                cid
                for cid in cids
                if any(t.lower() in allowed for t in self._store[cid].semantic_tags)
            ]
        if required_capabilities is not None:
            cids = [
                cid
                for cid in cids
                if all(req in self._store[cid].requires for req in required_capabilities)
            ]
        return toolset_slice(cids, budget=budget)

    def __len__(self) -> int:
        return len(self._store)


def toolset_slice(
    cids: List[str],
    budget: Optional[int] = None,
    sort_fn: Optional[Any] = None,
) -> List[str]:
    result = list(cids)
    if sort_fn is not None:
        result.sort(key=sort_fn)
    if budget is not None:
        result = result[:budget]
    return result


_global_repo: Optional[InterfaceRepository] = None


def get_interface_repository() -> InterfaceRepository:
    global _global_repo
    if _global_repo is None:
        _global_repo = InterfaceRepository()
    return _global_repo
