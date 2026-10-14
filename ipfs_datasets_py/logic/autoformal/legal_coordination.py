"""Source-bound grouped duties under explicit caller interpretations.

The source group records do not determine how a legal modal scopes over an
alternative. This compiler requires that choice, retains its evidence, and
checks existing native syntax and Lean rendering. These engineering checks do
not review the caller's interpretation or promote legacy branch scaffolds.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..deontic import coordination
from ..formalization.autoencoder import native_family_lean_emitters as emitters
from . import family_qualification as qualification


SCHEMA = "legal-coordination-compilation/v1"
INTERPRETATION_SCHEMA = "legal-coordination-interpretation/v1"
DECLARATION_SCOPE = "caller_supplied_interpretation_not_source_translation"
_DECLARATION_FIELDS = {
    "schema", "group_id", "group_sha256", "source_sha256",
    "modal_scope", "connective", "binding_profile",
}


def digest(value: Any) -> str:
    """Digest bounded canonical UTF-8 JSON using this bridge's wire profile."""
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("canonical JSON value required") from error
    if len(encoded) > 1_048_576:
        raise ValueError("coordination artifact exceeds byte bound")
    return hashlib.sha256(encoded).hexdigest()


def _source_pins() -> dict[str, str]:
    from ..deontic import coordination_decoder
    from ..deontic.utils import deontic_parser
    from ..TDFOL import tdfol_core, tdfol_parser
    from ..intent_ir.formalize import modal_projections
    modules = (coordination, coordination_decoder, deontic_parser, qualification, emitters,
               tdfol_core, tdfol_parser, modal_projections)
    paths = [Path(module.__file__).resolve() for module in modules] + [Path(__file__).resolve()]
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


_IMPORTED_PINS = _source_pins()


def producer_pins() -> dict[str, str]:
    """Pin concrete producers, refusing source changes after module import."""
    if _source_pins() != _IMPORTED_PINS:
        raise ValueError("coordination producer changed since import")
    return dict(_IMPORTED_PINS)


def _group(value: coordination.CoordinationGroup) -> coordination.CoordinationGroup:
    if type(value) is not coordination.CoordinationGroup:
        raise ValueError("typed CoordinationGroup required")
    # Rebuild exact source evidence, including direct dataclass replacements.
    return coordination.CoordinationGroup.from_dict(value.to_dict())


def interpretation_skeleton(group: coordination.CoordinationGroup) -> dict[str, Any]:
    """Return missing choices explicitly; supply no default modal semantics."""
    group = _group(group)
    return {
        "schema": INTERPRETATION_SCHEMA,
        "group_id": group.group_id,
        "group_sha256": digest(group.to_dict()),
        "source_sha256": group.source_sha256,
        "modal_scope": None,
        "connective": None,
        "binding_profile": None,
    }


def _declaration(group, value):
    if type(value) is not dict or set(value) != _DECLARATION_FIELDS:
        raise ValueError("exact coordination interpretation fields required")
    expected = interpretation_skeleton(group)
    for key in ("schema", "group_id", "group_sha256", "source_sha256"):
        if type(value[key]) is not str or value[key] != expected[key]:
            raise ValueError("interpretation differs from current source group: " + key)
    allowed = {
        "modal_scope": {"modal_over_actions", "disjunction_of_norms"},
        "connective": {"inclusive_or"},
        "binding_profile": {"universal_actor_predicate"},
    }
    for key, choices in allowed.items():
        item = value[key]
        if item is not None and (type(item) is not str or item not in choices):
            raise ValueError("unsupported coordination interpretation: " + key)
    return dict(value)


def _identity(text: str, *, actor: bool) -> str:
    text = " ".join(text.split()).casefold()
    return text.removeprefix("the ") if actor else text


def _registry(members, slot):
    from ..deontic.coordination_decoder import coordination_symbol_registry
    return coordination_symbol_registry(tuple(getattr(member, slot) for member in members), slot)


def compile_coordination_group(
    group: coordination.CoordinationGroup, declaration: dict[str, Any],
) -> dict[str, Any]:
    """Compile one explicit interpretation while retaining legal review gates.

    A complete caller declaration enables structural compilation only. Missing
    choices or unsupported source structure yield a blocked, empty artifact.
    Malformed or stale source/declaration evidence raises ValueError.
    """
    before = producer_pins()
    group = _group(group)
    declaration = _declaration(group, declaration)
    blockers = []
    if not group.structure_supported:
        blockers.append("group_structure_unsupported")
    if any(declaration[key] is None for key in ("modal_scope", "connective", "binding_profile")):
        blockers.append("group_interpretation_incomplete")
    result = {
        "schema": SCHEMA, "declaration_scope": DECLARATION_SCOPE,
        "group": group.to_dict(), "group_id": group.group_id,
        "group_sha256": digest(group.to_dict()), "source_sha256": group.source_sha256,
        "declaration": declaration, "declaration_sha256": digest(declaration),
        "target_logic": "deontic_fol", "formula": "", "native_ast": None,
        "native_payload": None, "mapping": {"actor_symbols": [], "action_symbols": []},
        "family_validation": None, "lean_body": "", "native_validation": None,
        "structure_compiled": False, "source_semantics_verified": False,
        "semantic_equivalence_checked": False, "admitted": False, "formalized": False,
        "proof_ready": False, "requires_validation": True,
        "blockers": blockers, "producer_pins": before,
    }
    if not blockers:
        from ..deontic.coordination_decoder import (
            CoordinationDecodeRequest, render_coordination_request,
        )
        try:
            request = CoordinationDecodeRequest.from_dict(_semantic_request_payload(group, declaration))
            actor_rows, actors = _registry(group.members, "actor")
            action_rows, _ = _registry(group.members, "action")
        except ValueError:
            # Source grouping has a wider lexical contract. Preserve evidence
            # for labels outside the closed decoder profile without coercion.
            blockers.append("group_decoder_profile_unsupported")
        else:
            operators = [member.modality for member in group.members]
            if declaration["modal_scope"] == "modal_over_actions":
                if len(set(actors)) != 1 or len(set(operators)) != 1:
                    blockers.append("shared_modal_actor_or_operator_mismatch")
        if not blockers:
            decoded = render_coordination_request(request)
            result.update({
                "formula": decoded["formula"], "native_ast": decoded["native_ast"],
                "native_payload": decoded["native_payload"],
                "mapping": {"actor_symbols": actor_rows, "action_symbols": action_rows},
                "family_validation": decoded["family_validation"], "lean_body": decoded["lean_body"],
                "native_validation": decoded["native_validation"], "structure_compiled": True,
            })
    blockers.append("source_interpretation_unreviewed")
    if producer_pins() != before:
        raise ValueError("coordination producer changed during compilation")
    result["compilation_sha256"] = digest(result)
    return result


def reconstruct_compiled_group(record: dict[str, Any]) -> str:
    """Verify the entire artifact against current source before reconstruction."""
    if type(record) is not dict or "group" not in record or "declaration" not in record:
        raise ValueError("closed grouped compilation record required")
    group = coordination.CoordinationGroup.from_dict(record["group"])
    expected = compile_coordination_group(group, record["declaration"])
    # The digest helper bounds and rejects non-JSON/NaN/invalid UTF-8 payloads.
    # Equality still compares complete canonical bytes, not only their seals.
    digest(record)
    if json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False) != json.dumps(
        expected, sort_keys=True, ensure_ascii=False, allow_nan=False):
        raise ValueError("compiled group differs from current source and declared interpretation")
    return coordination.reconstruct_source(group)


def _semantic_request_payload(group, declaration):
    from ..deontic.coordination_decoder import COORDINATION_DECODE_REQUEST_SCHEMA
    return {
        "schema": COORDINATION_DECODE_REQUEST_SCHEMA,
        "modal_scope": declaration["modal_scope"],
        "connective": declaration["connective"],
        "binding_profile": declaration["binding_profile"],
        "members": [{"actor": _identity(member.actor, actor=True),
                     "modality": member.modality,
                     "action": _identity(member.action, actor=False)} for member in group.members],
    }


def coordination_decode_request_from_compiled(record: dict[str, Any]):
    """Build only semantic decoder fields from a validated compiled artifact.

    Source, provenance, reference formula and original formatting stay outside
    the request. Actor/action labels are intentionally retained as semantic IR.
    Preparation verifies source evidence; decoding consumes the detached request.
    """
    from ..deontic.coordination_decoder import CoordinationDecodeRequest
    reconstruct_compiled_group(record)
    if record["structure_compiled"] is not True:
        raise ValueError("only structurally compiled groups supply decoder requests")
    group = coordination.CoordinationGroup.from_dict(record["group"])
    return CoordinationDecodeRequest.from_dict(_semantic_request_payload(group, record["declaration"]))
