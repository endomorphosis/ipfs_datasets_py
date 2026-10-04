from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


PROOF_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class SourceProvenance:
    source_path: str
    source_id: str
    source_span: Optional[str] = None


@dataclass(frozen=True)
class IRReference:
    kind: Literal["norm", "frame", "temporal", "definition", "event", "derived"]
    id: str


@dataclass
class ProofStep:
    step_id: str
    rule_id: str
    premises: List[str]
    conclusion: str
    ir_refs: List[IRReference] = field(default_factory=list)
    provenance: List[SourceProvenance] = field(default_factory=list)
    timestamp: Optional[str] = None
    confidence: float = 1.0


@dataclass
class ProofCertificate:
    certificate_id: str
    backend: str
    format: str
    theorem: str
    assumptions: List[str] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)
    normalized_hash: str = ""


@dataclass
class ProofObject:
    proof_id: str
    query: Dict[str, Any]
    root_conclusion: str
    steps: List[ProofStep]
    status: Literal["proved", "refuted", "inconclusive"]
    schema_version: str = PROOF_SCHEMA_VERSION
    proof_hash: str = ""
    created_at: Optional[str] = None
    certificates: List[ProofCertificate] = field(default_factory=list)
    certificate_trace_map: Dict[str, List[IRReference]] = field(default_factory=dict)
