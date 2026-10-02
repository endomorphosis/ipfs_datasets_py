"""Source-bound typed referents and parameterized Lean fixture scaffolding.

Missing referents remain universally parameterized values. A graph binding or
caller fixture records modeling provenance, never an existence claim, graph
truth theorem, inferred fact, or an inhabited-type axiom. All generated Lean
identifiers are synthetic; caller labels never enter executable source.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil

from ..ir_core.provenance import SourceRef

ENV_SCHEMA = "formalization-typed-slot-environment/v1"
CONTEXT_SCHEMA = "formalization-slot-context/v1"
FIXTURE_SCHEMA = "formalization-parameterized-fixture/v1"
SORTS = frozenset({"Entity", "Agent", "Person", "Organization", "Resource", "Action", "Object",
    "Event", "Time", "State", "Value", "Document", "Location", "Role"})
_AUTHORITY = {"proof_authority": False, "execution_authority": False, "facts_asserted": False,
    "existence_asserted": False, "source_semantics_verified": False}


class TypedSlotError(ValueError):
    pass


def _wire(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise TypedSlotError("bounded_inert_json_required") from exc
    if len(raw) > 2_000_000:
        raise TypedSlotError("context_resource_bound")
    return raw


def canonical_slot_digest(value):
    """Stable digest for a checkpoint descriptor, graph snapshot or entity row."""
    return hashlib.sha256(_wire(value)).hexdigest()


def _text(value, label, *, empty=False):
    if type(value) is not str or (not value and not empty) or len(value) > 1024:
        raise TypedSlotError(label + "_invalid")
    if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise TypedSlotError(label + "_invalid_unicode")
    return value


def _sort(value):
    if value not in SORTS:
        raise TypedSlotError("unsupported_slot_sort")
    return value


def _refines(base, chosen):
    return base == chosen or base in {"Entity", "Object"} or (base == "Agent" and chosen in {"Person", "Organization"})


def prepare_typed_slot_environment(*, source_text, slots, context=None, checkpoint=None):
    """Bind declared slots to symbolic, explicit fixture or exact KG provenance.

    ``context`` carries a full native KnowledgeGraph snapshot and optional
    explicit slot/entity bindings. The SourceRef on each KG binding must name
    that exact canonical snapshot hash; cached or ambiguous bindings fail closed.
    """
    if type(source_text) is not str or len(source_text.encode()) > 1_000_000:
        raise TypedSlotError("bounded_source_text_required")
    source_hash = hashlib.sha256(source_text.encode()).hexdigest()
    report = {"schema": ENV_SCHEMA, "status": "unsupported", "source_sha256": source_hash,
        "checkpoint_sha256": canonical_slot_digest(checkpoint), "context_sha256": canonical_slot_digest(context),
        "declarations_sha256": canonical_slot_digest(slots), "slots": [], "diagnostics": [],
        "assumptions": ["Carrier types may be empty; no Nonempty or Inhabited instance is introduced.",
            "All referents, predicates and modal operators are parameters, not asserted facts.",
            "Explicit fixture and KG type declarations are modeling assumptions, not verified ontology truths."],
        "provider_calls": 0, "download_calls": 0, **_AUTHORITY}
    try:
        if type(slots) is not list or len(slots) > 64:
            raise TypedSlotError("bounded_slot_declarations_required")
        declared = {}
        for index, slot in enumerate(slots):
            if type(slot) is not dict or set(slot) != {"slot_id", "surface", "sort"}:
                raise TypedSlotError("closed_slot_declaration_required")
            key = _text(slot["slot_id"], "slot_id")
            if key in declared:
                raise TypedSlotError("duplicate_or_conflicting_slot_declaration:" + key)
            surface = _text(slot["surface"], "surface", empty=True)
            declared[key] = {"slot_id": key, "surface": surface, "declared_sort": _sort(slot["sort"]),
                "resolved_sort": slot["sort"], "lean_name": "v" + str(index), "origin": "symbolic",
                "provenance": None, "referent_resolved": False}
        selections = {}
        if context is not None:
            if (type(context) is not dict or set(context) - {"schema", "source_sha256", "fixtures", "knowledge_graph", "kg_bindings"}
                    or context.get("schema") != CONTEXT_SCHEMA or context.get("source_sha256") != source_hash):
                raise TypedSlotError("stale_or_invalid_source_context")
            fixtures = context.get("fixtures", [])
            bindings = context.get("kg_bindings", [])
            if type(fixtures) is not list or type(bindings) is not list or len(fixtures) + len(bindings) > 128:
                raise TypedSlotError("bounded_context_bindings_required")
            for item in fixtures:
                if type(item) is not dict or set(item) != {"slot_id", "sort", "label"}:
                    raise TypedSlotError("closed_fixture_binding_required")
                label = _text(item["label"], "fixture_label")
                selections.setdefault(item["slot_id"], []).append({"sort": _sort(item["sort"]), "origin": "fixture",
                    "provenance": {"label": label, "fixture_sha256": canonical_slot_digest(item)}, "resolved": True})
            if bindings:
                from ...knowledge_graphs.extraction.entities import Entity
                from ...knowledge_graphs.extraction.graph import KnowledgeGraph
                graph_wire = context.get("knowledge_graph")
                if type(graph_wire) is not dict or type(graph_wire.get("entities")) is not list or len(graph_wire["entities"]) > 1024:
                    raise TypedSlotError("bounded_native_knowledge_graph_required")
                graph = KnowledgeGraph.from_dict(graph_wire)
                if _wire(graph.to_dict()) != _wire(graph_wire):
                    raise TypedSlotError("native_knowledge_graph_roundtrip_changed")
                graph_hash = canonical_slot_digest(graph_wire)
                for item in bindings:
                    if type(item) is not dict or set(item) != {"slot_id", "entity_id", "entity_sha256", "source_ref"}:
                        raise TypedSlotError("closed_kg_binding_required")
                    entity = graph.entities.get(item["entity_id"])
                    if type(entity) is not Entity or canonical_slot_digest(entity.to_dict()) != item["entity_sha256"]:
                        raise TypedSlotError("stale_or_missing_kg_entity_binding")
                    ref = SourceRef.from_dict(item["source_ref"])
                    if _wire(ref.to_dict()) != _wire(item["source_ref"]):
                        raise TypedSlotError("native_source_ref_roundtrip_changed")
                    if ref.content_sha256 != graph_hash:
                        raise TypedSlotError("stale_kg_snapshot_source_ref")
                    if ref.review_status.value in {"rejected", "quarantined"}:
                        raise TypedSlotError("kg_source_review_refuses_binding")
                    entity_sort = {name.lower(): name for name in SORTS}.get(entity.entity_type)
                    if entity_sort is None:
                        raise TypedSlotError("unmapped_kg_entity_sort")
                    selections.setdefault(item["slot_id"], []).append({"sort": entity_sort, "origin": "knowledge_graph",
                        "resolved": True, "provenance": {"entity_id": entity.entity_id, "entity_sha256": item["entity_sha256"],
                            "graph_sha256": graph_hash, "source_ref": ref.to_dict(), "entity_name": entity.name}})
            elif context.get("knowledge_graph") is not None:
                # An unused graph never creates bindings automatically.
                report["diagnostics"].append({"code": "unselected_kg_snapshot", "severity": "info"})
        for key, alternatives in selections.items():
            if key not in declared:
                raise TypedSlotError("unbound_context_slot:" + str(key))
            if len(alternatives) != 1:
                raise TypedSlotError("ambiguous_slot_binding:" + key)
            chosen = alternatives[0]
            if not _refines(declared[key]["declared_sort"], chosen["sort"]):
                raise TypedSlotError("conflicting_slot_sort:" + key)
            declared[key].update(resolved_sort=chosen["sort"], origin=chosen["origin"],
                provenance=chosen["provenance"], referent_resolved=chosen["resolved"])
        report["slots"] = list(declared.values())
        for slot in report["slots"]:
            if slot["origin"] == "symbolic":
                report["diagnostics"].append({"code": "unresolved_referent_parameterized", "slot_id": slot["slot_id"], "severity": "info"})
        report["status"] = "ready"
    except (TypedSlotError, ValueError, TypeError, KeyError, AttributeError) as exc:
        report["diagnostics"].append({"code": str(exc), "severity": "error"})
        report["slots"] = []
    report["environment_sha256"] = canonical_slot_digest(report)
    return report


def render_parameterized_fixture(environment, formula):
    """Render closed predicate/modal syntax using only safe bound identifiers."""
    if type(environment) is not dict or environment.get("schema") != ENV_SCHEMA:
        raise TypedSlotError("typed_environment_required")
    original = {key: value for key, value in environment.items() if key != "environment_sha256"}
    if canonical_slot_digest(original) != environment.get("environment_sha256"):
        raise TypedSlotError("typed_environment_identity_changed")
    report = {"schema": FIXTURE_SCHEMA, "status": "unsupported", "environment": environment,
        "formula": formula, "formula_sha256": canonical_slot_digest(formula), "lean_source": None,
        "diagnostics": [], "syntax_typecheck_only": True, "claim_proved": False, **_AUTHORITY}
    if environment["status"] != "ready":
        report["diagnostics"] = [{"code": "slot_environment_not_ready", "severity": "error"}]
    else:
        try:
            if type(environment["slots"]) is not list or len(environment["slots"]) > 64:
                raise TypedSlotError("bounded_environment_slots_required")
            for index, slot in enumerate(environment["slots"]):
                if slot["lean_name"] != "v" + str(index):
                    raise TypedSlotError("unsafe_or_changed_generated_slot_identifier")
                _sort(slot["resolved_sort"])
            slots = {slot["slot_id"]: slot for slot in environment["slots"]}
            if len(slots) != len(environment["slots"]):
                raise TypedSlotError("duplicate_environment_slot")
            sorts = sorted({slot["resolved_sort"] for slot in slots.values()})
            carriers = {sort: "T" + str(i) for i, sort in enumerate(sorts)}
            predicates, modalities = {}, {}
            seen = 0

            def expression(node, depth=0):
                nonlocal seen
                seen += 1
                if seen > 512 or depth > 32 or type(node) is not dict:
                    raise TypedSlotError("bounded_typed_formula_required")
                op = node.get("op")
                if op == "predicate" and set(node) == {"op", "predicate", "arguments"}:
                    name = _text(node["predicate"], "predicate")
                    args = node["arguments"]
                    if type(args) is not list or len(args) > 16:
                        raise TypedSlotError("bounded_predicate_arguments_required")
                    selected = []
                    for arg in args:
                        if type(arg) is not dict or set(arg) != {"slot_id"} or arg["slot_id"] not in slots:
                            raise TypedSlotError("unbound_formula_slot")
                        selected.append(slots[arg["slot_id"]])
                    signature = tuple(slot["resolved_sort"] for slot in selected)
                    if name in predicates and predicates[name][1] != signature:
                        raise TypedSlotError("conflicting_predicate_signature")
                    predicates.setdefault(name, ("p" + str(len(predicates)), signature))
                    return "(" + " ".join([predicates[name][0]] + [slot["lean_name"] for slot in selected]) + ")"
                if op == "modal" and set(node) == {"op", "modality", "body"}:
                    name = _text(node["modality"], "modality")
                    modalities.setdefault(name, "m" + str(len(modalities)))
                    return "(" + modalities[name] + " " + expression(node["body"], depth + 1) + ")"
                if op == "not" and set(node) == {"op", "body"}:
                    return "(Not " + expression(node["body"], depth + 1) + ")"
                if op in {"and", "or", "implies"} and set(node) == {"op", "left", "right"}:
                    return "(" + expression(node["left"], depth + 1) + " " + {"and": "∧", "or": "∨", "implies": "→"}[op] + " " + expression(node["right"], depth + 1) + ")"
                raise TypedSlotError("unsupported_typed_formula")

            body = expression(formula)
            binders = ["(" + carrier + " : Type)" for carrier in carriers.values()]
            binders += ["(" + slot["lean_name"] + " : " + carriers[slot["resolved_sort"]] + ")" for slot in slots.values()]
            binders += ["(" + name + " : " + " → ".join([carriers[s] for s in signature] + ["Prop"]) + ")" for name, signature in predicates.values()]
            binders += ["(" + name + " : Prop → Prop)" for name in modalities.values()]
            report.update(status="candidate", lean_source="\n".join([
                "-- Parameterized syntax fixture; referents and modal operators are arbitrary inputs.",
                "namespace TypedSlotFixture", "set_option autoImplicit false",
                "def formula " + " ".join(binders) + " : Prop := " + body, "end TypedSlotFixture", ""]),
                carrier_map=carriers, predicate_signatures=[{"label": label, "lean_name": value[0], "sorts": list(value[1])} for label, value in predicates.items()],
                modality_map=modalities)
        except (TypedSlotError, KeyError, TypeError, RecursionError) as exc:
            report["diagnostics"] = [{"code": str(exc), "severity": "error"}]
    report["fixture_sha256"] = canonical_slot_digest(report)
    return report


def validate_parameterized_fixture(report, *, source_text, slots, context=None, checkpoint=None,
                                   lake_executable, timeout_seconds=30):
    """Regenerate source/context bindings before native Lake checks fixture syntax."""
    from ..backends.process import BoundedToolRunner, ToolRunRequest, ToolRunLimits
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
        raise TypedSlotError("bounded_lake_timeout_required")
    environment = prepare_typed_slot_environment(source_text=source_text, slots=slots, context=context, checkpoint=checkpoint)
    expected = render_parameterized_fixture(environment, report["formula"])
    if _wire(expected) != _wire(report):
        raise TypedSlotError("fixture_differs_from_source_context_replay")
    receipt = {"schema": "formalization-typed-slot-lake/v1", "status": "not_run", "fixture_sha256": report["fixture_sha256"],
        "backend_executed": False, "syntax_verified": False, "claim_proved": False, "observations": [], **_AUTHORITY}
    if report["status"] != "candidate": return receipt
    found = shutil.which(str(lake_executable))
    if found is None:
        receipt.update(status="unavailable", reason="lake_executable_missing")
        return receipt
    executable = Path(found).absolute()
    if executable.parent.name == "bin" and executable.parent.parent.name == ".elan":
        receipt.update(status="unavailable", reason="select_installed_native_lake_not_elan_shim")
        return receipt
    runner = BoundedToolRunner()
    probe = runner.run(ToolRunRequest(argv=(str(executable), "--version"), limits=ToolRunLimits(timeout_seconds=5, max_output_bytes=16384)))
    version = re.search(r"Lean version (\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)", probe.stdout)
    if not probe.ok or not version:
        receipt.update(status="unavailable", reason="native_lake_version_probe_failed")
        return receipt
    toolchain = "leanprover/lean4:v" + version.group(1)
    command = (str(executable), "build", "TypedSlotFixture")
    files = {"lakefile.toml": 'name = "typed_slot_fixture"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "TypedSlotFixture"\n',
        "lean-toolchain": toolchain + "\n", "TypedSlotFixture.lean": report["lean_source"]}
    run = runner.run(ToolRunRequest(argv=command, input_files=files, environment={"ELAN_TOOLCHAIN": toolchain},
        limits=ToolRunLimits(timeout_seconds=timeout_seconds, cpu_seconds=timeout_seconds, max_input_bytes=1048576,
            max_output_bytes=262144, max_workspace_bytes=32 * 1024 * 1024)))
    passed = run.ok and not run.output_truncated and not run.workspace_limit_exceeded
    receipt.update(status="passed" if passed else "failed", backend_executed=True, syntax_verified=passed,
        command=list(command), toolchain=toolchain, lean_source_sha256=hashlib.sha256(report["lean_source"].encode()).hexdigest(),
        observations=[{"returncode": run.returncode, "stdout": run.stdout, "stderr": run.stderr, "timed_out": run.timed_out}])
    return receipt
