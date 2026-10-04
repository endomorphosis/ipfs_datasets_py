"""Replayable structural targets for a closed captured-source code profile.

This adapter compiles exact bytes with the existing integer-offset source
correspondence checks. Its features describe the ordered, typed body assumption
and requested contract goal. Source identities and spans remain in the replay
evidence rather than the numerical vocabulary. Preparation does not execute
repository code, invoke a solver, or establish behavior or proof authority.

Only the already supported ``python-integer-offset@1`` fragment is admitted.
In particular, guards, comparisons, calls and additional statements fail
closed; this is not a general Python source decoder.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .domain_targets import DomainTargetEnvelope, build_target_envelope
from ...backends.smt.compiler import SmtTerm, SmtTermKind
from ...software_contracts import codebase_integer_profile as native
from ...software_contracts.content import cid_for_structured

DOMAIN_ID = "codebase_ir"
PROFILE = native.PROFILE
TARGET_PROFILE = "codebase-integer-offset-features@1"
TARGET_SCHEMA = "codebase-integer-offset-target@1"
PROJECTION_ID = "codebase-integer-offset-smt@1"
PRODUCER_ID = "codebase-integer-offset-target-adapter"
VALIDATOR_ID = "codebase_ir.integer_offset_source_replay"
MAX_TARGET_BYTES = 256 * 1024


class CodebaseTargetError(ValueError):
    """The envelope is not the exact bounded output of this native producer."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CodebaseTargetError(message)


def _expression(compiled: native.CompiledIntegerOffset) -> dict[str, Any]:
    """Alpha-rename only the two checked symbols; retain every native term."""
    obligation = compiled.pipeline.obligation_results[0].smt_obligation
    goal = obligation.goal
    # compile_integer_offset independently checked this exact goal/body shape
    # against the source AST and authored contract before this projection.
    result_name = goal.arguments[0].value
    parameter_name = goal.arguments[1].arguments[0].value
    roles = {parameter_name: "parameter", result_name: "result"}
    _require(len(roles) == 2, "native parameter/result symbols must be distinct")

    def term(value: SmtTerm) -> dict[str, Any]:
        _require(not value.binders and value.sort is None,
                 "unexpected binder or explicit sort in closed integer target")
        _require(value.kind in {SmtTermKind.SYMBOL, SmtTermKind.INT,
                               SmtTermKind.ADD, SmtTermKind.SUB,
                               SmtTermKind.NEG, SmtTermKind.EQ},
                 "native expression is outside the closed integer target")
        payload = value.value
        if value.kind is SmtTermKind.SYMBOL:
            _require(payload in roles, "unbound native symbol in integer target")
            payload = roles[payload]
        return {"kind": value.kind.value, "sort": "Bool" if value.kind is SmtTermKind.EQ else "Int",
                "value": payload, "arguments": [term(child) for child in value.arguments]}

    return {
        "schema": TARGET_PROFILE,
        "query_mode": obligation.query_mode.value,
        "declarations": [{"role": "parameter", "sort": "Int"}, {"role": "result", "sort": "Int"}],
        "assumptions": [{"role": "source_body", "formula": term(obligation.assumptions[0].formula)}],
        "goal": term(goal),
    }


def prepare_codebase_targets(
    source: bytes, contract: native.IntegerOffsetContract, *, revision: str,
) -> DomainTargetEnvelope:
    """Compile captured source and an explicit contract into one program view.

    ``revision`` is the caller's exact captured snapshot identity. No live
    repository reads occur. The source is retained, within the compiler's
    64 KiB limit, so a consumer can independently replay the complete target.
    Role assignment, training, resource admission and current-head checks are
    responsibilities of the owning service, outside this pure adapter.
    """
    compiled = native.compile_integer_offset(source, contract, revision=revision)
    pipeline = compiled.pipeline
    obligation = pipeline.obligation_results[0]
    artifacts = {
        "program": pipeline.program.to_dict(),
        "program_contract": pipeline.contracts[0].to_dict(),
        "vc_set": pipeline.vc_sets[0].to_dict(),
        "smt_obligation": obligation.smt_obligation.to_dict(),
        "compiled": compiled.to_dict(),
    }
    binding = {
        "schema": TARGET_SCHEMA, "profile": PROFILE,
        "source_cid": compiled.source_cid,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "contract_cid": contract.cid, "revision": revision,
        "artifact_cids": {name: cid_for_structured(value) for name, value in artifacts.items()},
        "producer_sha256": {
            "codebase_targets": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "codebase_integer_profile": hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest(),
        },
    }
    # The envelope uses a SHA-256 digest, while the native artifacts retain
    # their independently recomputable repository CAS CIDs.
    source_digest = hashlib.sha256(cid_for_structured(binding).encode("ascii")).hexdigest()
    result = build_target_envelope(
        domain_id=DOMAIN_ID, source_digest=source_digest,
        projections=[{
            "projection_id": PROJECTION_ID, "view_id": PROJECTION_ID,
            "logic_family": "program", "profile": TARGET_PROFILE,
            "properties": [], "view_role": None,
            "representation_kind": "ordered_typed_smt_obligation",
            "producer_id": PRODUCER_ID, "producer_version": TARGET_SCHEMA,
            "expression": _expression(compiled),
        }],
        validation=[{
            "validator_id": VALIDATOR_ID, "stage": "target", "required": True,
            "status": "passed", "details": {
                "schema": TARGET_SCHEMA,
                "inputs": {"source_ascii": source.decode("ascii"),
                           "contract": contract.to_dict(), "revision": revision},
                "binding": binding, "native_artifacts": artifacts,
                "assumptions": list(native.ASSUMPTIONS),
                "source_executed": False, "solver_executed": False,
                "kernel_checked": False, "behavior_authority": False,
                "training_executed": False,
            },
        }],
        qualification_gaps=(
            "structural_compiler_features_only_not_a_learned_source_decoder",
            "integer_profile_runtime_assumptions_remain_conditional",
            "backend_proofs_not_run", "kernel_certificate_not_checked",
            "behavior_and_execution_authority_not_granted",
        ),
    )
    _require(len(result.canonical_bytes) <= MAX_TARGET_BYTES, "codebase target exceeds byte bound")
    return result


def validate_codebase_targets(target: DomainTargetEnvelope) -> DomainTargetEnvelope:
    """Recompile captured bytes and compare the complete canonical envelope.

    Envelope shape or a recomputed digest alone is insufficient: every native
    artifact, source binding, semantic feature and authority field must match
    the installed producer's replay. Comparison is byte exact, including the
    distinction between JSON booleans and numbers.
    """
    _require(type(target) is DomainTargetEnvelope, "exact DomainTargetEnvelope required")
    _require(type(target.canonical_bytes) is bytes and len(target.canonical_bytes) <= MAX_TARGET_BYTES,
             "codebase target exceeds byte bound")
    # Reconstruct the frozen object as well: object.__setattr__ can bypass a
    # dataclass's normal immutability, and a caller-owned instance is not trust.
    target = DomainTargetEnvelope(target.canonical_bytes)
    value = target.to_dict()
    _require(value["domain_id"] == DOMAIN_ID, "target belongs to another domain")
    checks = value["validation"]
    _require(len(checks) == 1 and checks[0].get("validator_id") == VALIDATOR_ID,
             "closed codebase replay validator required")
    details = checks[0]["details"]
    _require(details.get("schema") == TARGET_SCHEMA, "unknown codebase target schema")
    inputs = details.get("inputs")
    _require(type(inputs) is dict and set(inputs) == {"source_ascii", "contract", "revision"},
             "closed captured-source replay inputs required")
    source = inputs["source_ascii"]
    _require(type(source) is str and source.isascii() and 0 < len(source) <= native.MAX_SOURCE_BYTES,
             "bounded exact ASCII source required")
    contract = native.IntegerOffsetContract.from_dict(inputs["contract"])
    expected = prepare_codebase_targets(source.encode("ascii"), contract, revision=inputs["revision"])
    _require(expected.canonical_bytes == target.canonical_bytes,
             "codebase target differs from exact captured-source producer replay")
    return expected


__all__ = [
    "DOMAIN_ID", "PROFILE", "TARGET_PROFILE", "TARGET_SCHEMA", "PROJECTION_ID",
    "PRODUCER_ID", "VALIDATOR_ID", "MAX_TARGET_BYTES", "CodebaseTargetError",
    "prepare_codebase_targets", "validate_codebase_targets",
]
