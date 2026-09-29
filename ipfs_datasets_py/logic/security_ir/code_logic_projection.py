"""Join exact CVEfixes code bodies to explicitly supplied native code IRs.

This is a source-binding and structural projection service, not a code
translator or prover. CWE labels, snippets, and classifier scores cannot
manufacture contracts, heap models, transition relations, or flow policies.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Sequence

from ..ir_core.identity import canonical_identity
from ..ir_core.provenance import SourceRef
from ..software_verification.contracts import ProgramContract
from ..software_verification.program import ProgramIR
from ..software_verification.transitions import StateTransitionIR
from ..software_verification.temporal import TemporalFormula, TemporalLogic
from ..software_verification.heap import HeapModel
from ..software_verification.separation import SeparationLogicIR
from ..software_verification.hyperproperties import HyperpropertyIR
from ..software_verification.syntax_bridge import SoftwareVerificationSyntaxBridge, SoftwareVerificationBridgeError
from .cvefixes.schemas import CodeUnit

SCHEMA = "security-code-logic-projection/v1"
PROFILE_SCHEMA = "security-code-logic-projection-profile/v1"
# These are existing typed-owner kinds, not a new semantic family registry.
_OWNERS = {"program": ProgramIR, "contract": ProgramContract,
           "transition": StateTransitionIR, "temporal": TemporalFormula,
           "heap": HeapModel, "separation": SeparationLogicIR,
           "hyperproperty": HyperpropertyIR}
SUPPORTED_KINDS = tuple(_OWNERS)
_AUTHORITY = {"authority": "candidate_declaration", "proof_authority": False,
              "execution_authority": False, "completion_authority": False,
              "source_semantics_verified": False}
_MAX_BYTES = 4_000_000


class CodeLogicProjectionError(ValueError):
    """Malformed or stale source/IR bindings are rejected."""


def _wire(value: Any) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise CodeLogicProjectionError("bounded JSON projection required") from exc
    if len(raw) > _MAX_BYTES:
        raise CodeLogicProjectionError("code logic projection exceeds byte bound")
    return raw


def _identity(value: dict, schema: str) -> str:
    return canonical_identity(value, domain="security-ir/code-logic", schema_version=schema).cid


def describe_code_logic_projection_profile() -> dict:
    """Describe existing native routes and the evidence needed to use them."""
    bridge = SoftwareVerificationSyntaxBridge()
    targets = []
    for kind, owner in _OWNERS.items():
        route = bridge.route_for(kind).to_dict()
        targets.append({"kind": kind, "typed_owner": owner.__name__,
            "family": route["family_id"], "profile": route["profile_id"],
            "owner_schema": route["domain_schema"],
            "view_role": route["view_role"], "payload_schema": route["payload_schema"],
            "requires_program_binding": kind == "contract",
            "requires_explicit_source_ref": True,
            "available_without_typed_evidence": False})
    value = {"schema": PROFILE_SCHEMA, "projections": targets,
        "supported_kinds": list(SUPPORTED_KINDS),
        "source_contract": "CodeUnit body_sha256 + body_cid verified against exact UTF-8 bytes",
        "missing_source_policy": "quarantine_without_targets",
        "bridge": bridge.INTERFACE, "source_binding_is_semantic_verification": False,
        "label_to_formula_inference": False, "backend_calls": 0, "provider_calls": 0,
        "tla_encoding": {"kind": "transition", "encoding": "tla+",
                         "compiler": "TLACompiler", "bounded": True,
                         "losses_preserved": True, "model_checker_executed": False},
        "unsupported_frontiers": ["automatic_code_to_ir_semantic_translation",
            "unbounded_proof", "cwe_label_to_formula", "separation_without_heap",
            "information_flow_without_explicit_policy", "non_ltl_temporal_profile",
            "concurrency_and_protocol_source_join"], **_AUTHORITY}
    return {**value, "profile_cid": _identity(value, PROFILE_SCHEMA)}


@dataclass(frozen=True, slots=True)
class CodeLogicEvidence:
    """An explicit modeling declaration bound to one exact source body."""
    document: Any
    source: SourceRef

    def __post_init__(self):
        if type(self.document) not in _OWNERS.values() or type(self.source) is not SourceRef:
            raise CodeLogicProjectionError("native typed document and SourceRef required")
        self.source.validate()


def _kind(document) -> str:
    for kind, owner in _OWNERS.items():
        if type(document) is owner:
            return kind
    raise CodeLogicProjectionError("unsupported typed code owner")


def _source_binding(code_unit, source_bytes):
    if type(code_unit) is not CodeUnit:
        raise CodeLogicProjectionError("native CodeUnit required; labels are not source evidence")
    # Reconstruct the native record so its claimed identity is checked again.
    _wire(code_unit.to_dict())
    CodeUnit.from_dict(code_unit.to_dict())
    if source_bytes is not None and (type(source_bytes) is not bytes or len(source_bytes) > _MAX_BYTES):
        raise CodeLogicProjectionError("bounded immutable source_bytes required")
    body_sha = code_unit.payload.get("body_sha256")
    body_cid = code_unit.payload.get("body_cid")
    binding = {"code_unit_cid": code_unit.cid, "source_cids": list(code_unit.source_cids),
        "path": code_unit.path, "language": code_unit.language, "polarity": code_unit.polarity,
        "body_sha256": body_sha, "body_cid": body_cid}
    if not body_sha or not body_cid:
        return binding, "missing_code_body_identity"
    if source_bytes is None:
        return binding, "missing_exact_source_bytes"
    if hashlib.sha256(source_bytes).hexdigest() != body_sha:
        raise CodeLogicProjectionError("source body SHA differs from CodeUnit")
    try:
        body = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CodeLogicProjectionError("native code-body profile requires UTF-8") from exc
    actual = canonical_identity({"body": body}, domain="cvefixes-security-ir/code-body",
                                schema_version="cvefixes-code-body/v1").cid
    if actual != body_cid:
        raise CodeLogicProjectionError("source body CID differs from CodeUnit")
    return binding, ""


def _validate_mapped_refs(value, source, body_size):
    """Reject a native document's intrinsic source map if it contradicts the join."""
    if isinstance(value, dict):
        if "source_ref_ids" in value and any(ref != source.ref_id for ref in value["source_ref_ids"]):
            raise CodeLogicProjectionError("typed document references a different code unit")
        if "source_ref_id" in value and value["source_ref_id"] != source.ref_id:
            raise CodeLogicProjectionError("typed span references a different code unit")
        if "start_byte" in value and "end_byte" in value:
            if not (0 <= value["start_byte"] <= value["end_byte"] <= body_size):
                raise CodeLogicProjectionError("typed source span exceeds exact code body")
        if "ref_id" in value and "content_sha256" in value:
            if value != source.to_dict():
                raise CodeLogicProjectionError("embedded native SourceRef differs from explicit binding")
        for child in value.values():
            _validate_mapped_refs(child, source, body_size)
    elif isinstance(value, list):
        for child in value:
            _validate_mapped_refs(child, source, body_size)


def project_code_logic(*, code_unit: CodeUnit, source_bytes: bytes | None,
                       typed_inputs: Sequence[CodeLogicEvidence] = (),
                       requested_kinds: Sequence[str] | None = None) -> dict:
    """Publish source-bound native declarations, preserving missing-evidence frontiers.

    The caller supplies the modeling declarations. A correct byte binding does
    not establish that a declaration faithfully models the program's behavior.
    """
    requested = tuple(SUPPORTED_KINDS if requested_kinds is None else requested_kinds)
    if (not requested or len(requested) > len(SUPPORTED_KINDS)
            or len(set(requested)) != len(requested) or any(k not in _OWNERS for k in requested)):
        raise CodeLogicProjectionError("closed unique native projection kinds required")
    requested = sorted(requested)
    if isinstance(typed_inputs, (str, bytes, dict)) or len(typed_inputs) > len(_OWNERS):
        raise CodeLogicProjectionError("bounded typed_inputs sequence required")
    source, quarantine = _source_binding(code_unit, source_bytes)
    inputs, documents = [], {}
    for item in typed_inputs:
        if type(item) is not CodeLogicEvidence:
            raise CodeLogicProjectionError("CodeLogicEvidence required; raw labels/formulas rejected")
        kind = _kind(item.document)
        if kind in documents:
            raise CodeLogicProjectionError("duplicate typed code owner kind")
        if (item.source.ref_id != code_unit.cid or item.source.content_sha256 != source["body_sha256"]
                or item.source.content_cid != source["body_cid"] or item.source.source_id != code_unit.path):
            raise CodeLogicProjectionError("explicit SourceRef differs from CodeUnit identity")
        item.source.validate()
        # Normalize tuple-capable native payloads before traversing maps. The
        # JSON form is also the exact representation retained for replay.
        wire = json.loads(_wire(item.document.to_dict()))
        if not quarantine:
            _validate_mapped_refs(wire, item.source, len(source_bytes))
        reconstructed = _OWNERS[kind].from_dict(wire)
        if _wire(reconstructed.to_dict()) != _wire(wire):
            raise CodeLogicProjectionError("native typed reconstruction changed declaration")
        documents[kind] = reconstructed
        inputs.append({"kind": kind, "source": item.source.to_dict(), "document": wire})
    inputs.sort(key=lambda row: row["kind"])
    bridge = SoftwareVerificationSyntaxBridge()
    targets, frontiers = [], []
    for kind in requested:
        if quarantine or kind not in documents:
            frontiers.append({"kind": kind, "reason": quarantine or "missing_typed_evidence"})
            continue
        document = documents[kind]
        if kind == "contract":
            if "program" not in documents:
                frontiers.append({"kind": kind, "reason": "missing_typed_program_for_contract"})
                continue
            document.validate_against(documents["program"])
        if kind == "temporal" and document.logic is not TemporalLogic.LTL:
            frontiers.append({"kind": kind, "reason": "non_ltl_temporal_profile"})
            continue
        try:
            projected = bridge.round_trip(document)
        except SoftwareVerificationBridgeError as exc:
            frontiers.append({"kind": kind, "reason": "native_bridge_unsupported",
                              "diagnostic": exc.to_dict()})
            continue
        if not projected.exact:
            frontiers.append({"kind": kind, "reason": "native_bridge_not_exact",
                              "bridge": projected.to_dict()})
            continue
        route = bridge.route_for(kind)
        target = {"kind": kind, "family_id": route.family_id, "profile_id": route.profile_id,
            "bridge": projected.to_dict(), "native_document": document.to_dict(),
            "program_binding_validated": kind == "contract", **_AUTHORITY}
        if kind == "transition":
            from ..backends.tla.compiler import TLACompiler, TLACompilerError
            try:
                artifact = TLACompiler().compile_state(document, module_name="CodeTransition")
                target["encoding"] = {"format": "tla+", "artifact": artifact.to_dict(),
                                      "model_checker_executed": False, "proof_authority": False}
            except TLACompilerError as exc:
                frontiers.append({"kind": kind, "reason": "tla_encoding_unsupported",
                                  "diagnostic": str(exc)})
        targets.append(target)
    value = {"schema": SCHEMA, "profile_cid": describe_code_logic_projection_profile()["profile_cid"],
        "status": "quarantined" if quarantine else ("projected" if targets else "unsupported"),
        "source": source, "requested_kinds": requested, "typed_inputs": inputs,
        "targets": targets, "unsupported": frontiers, "backend_calls": 0,
        "provider_calls": 0, "label_to_formula_inference": False, **_AUTHORITY}
    _wire(value)
    return {**value, "projection_cid": _identity(value, SCHEMA)}


def validate_code_logic_projection(payload: dict, *, code_unit: CodeUnit,
                                   source_bytes: bytes | None) -> dict:
    """Reconstruct native owners and regenerate the entire byte-bound projection."""
    if type(payload) is not dict:
        raise CodeLogicProjectionError("projection payload must be an object")
    _wire(payload)
    rows = payload.get("typed_inputs")
    if type(rows) is not list or len(rows) > len(_OWNERS):
        raise CodeLogicProjectionError("bounded serialized typed inputs required")
    inputs = []
    for row in rows:
        if type(row) is not dict or set(row) != {"kind", "source", "document"} or row["kind"] not in _OWNERS:
            raise CodeLogicProjectionError("closed serialized typed input required")
        inputs.append(CodeLogicEvidence(_OWNERS[row["kind"]].from_dict(row["document"]),
                                        SourceRef.from_dict(row["source"])))
    rebuilt = project_code_logic(code_unit=code_unit, source_bytes=source_bytes,
        typed_inputs=inputs, requested_kinds=payload.get("requested_kinds"))
    if _wire(rebuilt) != _wire(payload):
        raise CodeLogicProjectionError("code logic projection identity or content differs")
    return rebuilt


__all__ = ["CodeLogicEvidence", "CodeLogicProjectionError", "SUPPORTED_KINDS",
           "describe_code_logic_projection_profile", "project_code_logic",
           "validate_code_logic_projection"]
