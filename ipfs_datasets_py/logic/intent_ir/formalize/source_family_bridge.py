"""Actual learned source clauses to existing logic families and typed fixtures.

This additive bridge leaves frozen decoders and their checkpoints unchanged.
Context is a source-bound caller premise, never inferred evidence that an event
occurred, a person exists, or a norm is satisfied. Unsupported families remain
visible across the complete canonical registry.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from . import document_roundtrip
from .extended_projections import project_intent_families, DEFAULT_FAMILIES, ADDITIONAL_REQUIREMENTS
from .projection_contracts import source_ir_sha256, validated_document
from .roundtrip import intent_ir_to_frame

SCHEMA = "source-intent-family-bridge/v1"
CONTEXT_SCHEMA = "source-intent-family-context/v1"
MAX_CONTEXT_BYTES = 262_144
MAX_REPORT_BYTES = 32 * 1024 * 1024
AUTHORITY = {"proof_authority": False, "execution_authority": False, "completion_authority": False,
             "source_semantics_verified": False, "external_context_truth_verified": False}


def _wire(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("source family report exceeds explicit byte bound")
    return raw


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _checkpoint_sha(checkpoint):
    return _sha(_wire(checkpoint))


def _candidate_map(document_report):
    units = {row["unit_id"]: row for row in document_report["units"]}
    result = {}
    for candidate in document_report["candidates"]:
        unit = units[candidate["unit_id"]]
        if not unit["accepted"] or not unit["source_agreement"]["matched"]:
            raise ValueError("family projection requires independently source-supported learned candidate")
        result[candidate["unit_id"]] = (candidate, unit)
    return result


def make_source_intent_family_context(document_report, bindings):
    """Bind explicit per-clause fixture/family premises to exact learned inputs.

    This helper constructs data only. Projection subsequently checks every
    binding against fresh actual inference; a forged document cannot grant a
    context binding or substitute a candidate.
    """
    if type(bindings) is not list or len(bindings) > 128:
        raise ValueError("bounded per-clause context list required")
    candidates = _candidate_map(document_report)
    selected, seen = [], set()
    for row in bindings:
        if (type(row) is not dict or set(row) - {"unit_id", "family_context", "slot_context"}
                or "unit_id" not in row or row["unit_id"] not in candidates or row["unit_id"] in seen):
            raise ValueError("unique known candidate unit context required")
        candidate, unit = candidates[row["unit_id"]]
        family_context = row.get("family_context", {})
        slot_context = row.get("slot_context")
        if type(family_context) is not dict or slot_context is not None and type(slot_context) is not dict:
            raise ValueError("structured explicit family and slot context required")
        selected.append({"unit_id": row["unit_id"], "source_ir_sha256": source_ir_sha256(candidate["candidate_intent_ir"]),
            "clause_sha256": _sha(unit["normalized_text"].encode()),
            "family_context": family_context, "slot_context": slot_context})
        seen.add(row["unit_id"])
    value = {"schema": CONTEXT_SCHEMA, "source_sha256": document_report["source_sha256"],
        "checkpoint_sha256": _checkpoint_sha(document_report["checkpoint_descriptor"]),
        "units": sorted(selected, key=lambda row: row["unit_id"])}
    value["context_sha256"] = _sha(_wire(value))
    if len(_wire(value)) > MAX_CONTEXT_BYTES:
        raise ValueError("source family context exceeds explicit byte bound")
    return json.loads(_wire(value))


def _context(context, document_report):
    if context is None:
        return None, {}
    if (type(context) is not dict or set(context) != {"schema", "source_sha256", "checkpoint_sha256", "units", "context_sha256"}
            or context["schema"] != CONTEXT_SCHEMA or type(context["units"]) is not list):
        raise ValueError("closed source-bound family context required")
    if len(context["units"]) > 128 or len(_wire(context)) > MAX_CONTEXT_BYTES:
        raise ValueError("bounded source family context required")
    bindings = []
    for row in context["units"]:
        if type(row) is not dict or set(row) != {"unit_id", "source_ir_sha256", "clause_sha256", "family_context", "slot_context"}:
            raise ValueError("closed candidate context binding required")
        bindings.append({key: row[key] for key in ("unit_id", "family_context", "slot_context")})
    expected = make_source_intent_family_context(document_report, bindings)
    if _wire(context) != _wire(expected):
        raise ValueError("context differs from exact source, checkpoint, candidate or clause binding")
    return expected, {row["unit_id"]: row for row in expected["units"]}


def _families(requested):
    from ...families.registry import DEFAULT_REGISTRY
    values = sorted(DEFAULT_REGISTRY.families) if requested is None else requested
    if (type(values) not in (list, tuple) or not 1 <= len(values) <= len(DEFAULT_REGISTRY.families)
            or any(type(family) is not str or family not in DEFAULT_REGISTRY.families for family in values)
            or len(set(values)) != len(values)):
        raise ValueError("unique canonical logic families required; backend names are not families")
    return sorted(values)


def _inventory(rows, requested):
    from ...families.registry import DEFAULT_REGISTRY
    inventory = []
    for family in sorted(DEFAULT_REGISTRY.families):
        native, extensions, fixtures = [], [], []
        for row in rows:
            native += [{"unit_id": row["unit_id"], "projection_id": p["projection_id"]}
                for p in row["selected_native_targets"] if p.get("logic_family") == family]
            extensions += [{"unit_id": row["unit_id"], "projection_id": p["projection_id"],
                "status": p["status"], "unsupported": p["unsupported"]}
                for p in row["family_projections"] if p["family_id"] == family]
            if family == "higher_order" and row["typed_fixture_available"]:
                fixtures.append(row["unit_id"])
        usable = [p for p in extensions if p["status"] in {"projected", "partial"}]
        # Native targets and declarations cover particular views, never every
        # obligation represented by a registered family.
        status = ("available_views" if native or usable or fixtures else "unsupported") if family in requested else "not_requested"
        inventory.append({"family_id": family, "requested": family in requested, "status": status,
            "native_targets": native, "extension_projections": extensions, "typed_fixture_units": fixtures,
            "reason": None if status == "available_views" else ADDITIONAL_REQUIREMENTS.get(family,
                "No source-supported typed projection or required domain model was supplied.")})
    return inventory


def project_source_intent_families(source_text, checkpoint_descriptor=None, *, start_char=0, end_char=None,
                                    context=None, requested_families=None):
    """Decode once, then project only accepted source-bound learned clauses."""
    from ...formalization import typed_slots
    from ...formalization.autoencoder.domain_targets import prepare_intent_targets
    requested = _families(requested_families)
    document_report = document_roundtrip.prepare_intent_document(source_text, checkpoint_descriptor,
        start_char=start_char, end_char=end_char)
    selected_context, context_rows = _context(context, document_report)
    extension_families = [f for f in requested if f in {*DEFAULT_FAMILIES, *ADDITIONAL_REQUIREMENTS}]
    rows, counts = [], Counter({key: 0 for key in ("accepted_clauses", "native_targets", "extension_projections",
        "extension_available_views", "typed_fixtures", "canonical_families", "families_with_available_views")})
    for unit_id, (candidate, unit) in _candidate_map(document_report).items():
        document = validated_document(candidate["candidate_intent_ir"])
        frame = intent_ir_to_frame(document)
        bound = context_rows.get(unit_id, {})
        family_context, slot_context = bound.get("family_context", {}), bound.get("slot_context")
        if slot_context is not None and "higher_order" not in requested:
            raise ValueError("slot context requires selected higher_order typed fixture; native family terms are unchanged")
        if extension_families:
            extended = project_intent_families(document, context=family_context, requested_families=extension_families)
            native, projections = extended["native_targets"], extended["projections"]
            pins = extended["producer_pins"]
        else:
            if family_context:
                raise ValueError("family context requires an explicitly selected extension family")
            native, projections, pins = prepare_intent_targets(document).to_dict(), [], {}
        slots = [{"slot_id": "actor", "surface": frame["actor"], "sort": "Agent"},
                 {"slot_id": "object", "surface": frame["object"], "sort": "Entity"}]
        environment = typed_slots.prepare_typed_slot_environment(source_text=unit["normalized_text"], slots=slots,
            context=slot_context, checkpoint=checkpoint_descriptor)
        formula = {"op": "modal", "modality": frame["modality"], "body": {"op": "predicate",
            "predicate": frame["action"], "arguments": [{"slot_id": "actor"}, {"slot_id": "object"}]}}
        fixture = (typed_slots.render_parameterized_fixture(environment, formula)
            if environment["status"] == "ready" and "higher_order" in requested else None)
        selected_native = [p for p in native["projections"] if p.get("logic_family") in requested]
        fixture_available = fixture is not None and fixture["status"] == "candidate"
        row = {"unit_id": unit_id, "start_char": unit["start_char"], "end_char": unit["end_char"],
            "start_byte": unit["start_byte"], "end_byte": unit["end_byte"],
            "source_ir_sha256": source_ir_sha256(document), "clause_sha256": _sha(unit["normalized_text"].encode()),
            "inference_report_sha256": candidate["inference_report_sha256"],
            "candidate_intent_ir": document.to_dict(), "frame": frame,
            "native_targets": native, "selected_native_targets": selected_native, "family_projections": projections, "family_producer_pins": pins,
            "slot_environment": environment, "typed_fixture": fixture, "typed_fixture_available": fixture_available,
            "typed_fixture_inputs": {"source_text": unit["normalized_text"], "slots": slots,
                "context": slot_context, "checkpoint": checkpoint_descriptor},
            "context_binding": bound or None,
            "semantics": "Typed slots parameterize the supplemental Lean fixture; native family artifacts preserve original Intent declaration identities.",
            **AUTHORITY}
        rows.append(row)
        counts["accepted_clauses"] += 1
        counts["native_targets"] += len(selected_native)
        counts["extension_projections"] += len(projections)
        counts["extension_available_views"] += sum(p["status"] in {"projected", "partial"} for p in projections)
        counts["typed_fixtures"] += fixture_available
    inventory = _inventory(rows, requested)
    counts["canonical_families"] = len(inventory)
    counts["families_with_available_views"] = sum(r["status"] == "available_views" for r in inventory)
    value = {"schema": SCHEMA, "status": "partial_source_bound_views" if rows else "fail_open_no_candidates",
        "source_sha256": document_report["source_sha256"], "checkpoint_descriptor": checkpoint_descriptor,
        "selection": {"start_char": start_char, "end_char": len(source_text) if end_char is None else end_char},
        "context": selected_context, "requested_families": requested, "document_report": document_report,
        "units": rows, "family_inventory": inventory, "counts": dict(counts),
        "producer_pins": {__name__: _sha(Path(__file__).read_bytes()),
            typed_slots.__name__: _sha(Path(typed_slots.__file__).read_bytes())},
        "training_steps": 0, "provider_calls": 0, "external_backend_calls": 0,
        "whole_document_formalized": False, "raw_instruction_preserved": True,
        "limitations": ["Typed fixture and KG bindings are caller assumptions, not facts learned or proved by the decoder.",
            "Missing event, temporal, heap, epistemic or trace models remain explicit family frontiers.",
            "Family availability records particular declarations/views, not full semantics or arbitrary program correctness.",
            "Typed slot specialization applies to the supplemental Lean fixture; native family projections retain their declared representation scope."],
        **AUTHORITY}
    value["report_sha256"] = _sha(_wire(value))
    return value


def validate_source_family_lean(report, *, source_text, checkpoint_descriptor=None, lake_executable, timeout_seconds=30):
    """Replay the whole learned bridge once, then build regenerated typed fixtures.

    ``document_report`` may be omitted by a containing transport to avoid a
    duplicate copy; all other fields must match the complete regenerated report.
    """
    from ...formalization.typed_slots import validate_parameterized_fixture
    if type(report) is not dict or report.get("schema") != SCHEMA:
        raise ValueError("source Intent family report required")
    expected = project_source_intent_families(source_text, checkpoint_descriptor,
        start_char=report["selection"]["start_char"], end_char=report["selection"]["end_char"],
        context=report["context"], requested_families=report["requested_families"])
    expected_transport = expected if "document_report" in report else {k:v for k,v in expected.items() if k != "document_report"}
    if _wire(report) != _wire(expected_transport):
        raise ValueError("source family bridge differs from actual frozen inference replay")
    receipts = []
    for row in expected["units"]:
        if row["typed_fixture_available"]:
            receipt = validate_parameterized_fixture(row["typed_fixture"], **row["typed_fixture_inputs"],
                lake_executable=lake_executable, timeout_seconds=timeout_seconds)
            receipts.append({"unit_id": row["unit_id"], "receipt": receipt})
    counts = expected["document_report"]["counts"]
    return {"schema": "source-intent-family-lake/v1", "source_sha256": expected["source_sha256"],
        "family_report_sha256": expected["report_sha256"], "receipts": receipts,
        "validated_scope": "supplemental_parameterized_lean_fixture_only",
        "other_family_backends_executed": False, "syntax_typecheck_only": True, "claim_proved": False,
        "validation_inference_replays": 1,
        "validation_encoder_executions": counts.get("encoder_executions", 0),
        "validation_decoder_executions": counts.get("decoder_executions", 0),
        "lake_attempts": sum(bool(r["receipt"].get("backend_executed")) for r in receipts),
        "lake_passes": sum(r["receipt"]["status"] == "passed" for r in receipts),
        "status": "passed" if receipts and all(r["receipt"]["status"] == "passed" for r in receipts) else "not_all_passed",
        **AUTHORITY}


__all__ = ["project_source_intent_families", "make_source_intent_family_context", "validate_source_family_lean"]
