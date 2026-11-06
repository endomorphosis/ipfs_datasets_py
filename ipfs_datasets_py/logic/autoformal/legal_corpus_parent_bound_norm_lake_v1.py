"""Prepare conditional parent norm/definition projects without native execution.

This narrow consumer delegates the existing Lake renderer and storage contract.
Its separate owner preserves the raw-pinned legacy Lake source and receipts.
Complete parent nominations are replayed; legal meaning remains unresolved.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import legal_bound_variable_definition_v1 as bound
from . import legal_corpus_definition_use_lake_v2 as lake


PARENT_BOUND_NORM_SCHEMA = "legal-corpus-parent-bound-norm-definition-lake-preparation/v1"
PARENT_BOUND_NORM_PROFILE = "replayed-parent-bound-norm-definition-conditional-project/v1"
PARENT_BOUND_NORM_INPUT_BINDING_SCHEMA = "legal-corpus-parent-bound-norm-definition-input-binding/v1"
PARENT_BOUND_NORM_INPUT_FILE_SCHEMA = "legal-corpus-parent-bound-norm-original-inputs/v1"
PARENT_BOUND_NORM_CONTEXT_BINDINGS_SCHEMA = "legal-corpus-parent-bound-norm-context-bindings/v1"
PARENT_BOUND_NORM_FALSE_FLAGS = {**lake.PARENT_NORM_FALSE_FLAGS, **lake.BOUND_NORM_FALSE_FLAGS}
LEGACY_LAKE_SOURCE_SHA256 = "5c98152db328b75583f6c0cd181e2724ca5f7392870ec0faf1e4d870cbb76b32"
DefinitionUseCorpusPreparation = lake.DefinitionUseCorpusPreparation
_PARENT_BOUND_NORM_OPERATION_PINS = None


def _pure_pins():
    observed = lake._pure_pins()
    lake_path = str(Path(lake.__file__).resolve())
    lake._need(observed[lake_path] == LEGACY_LAKE_SOURCE_SHA256,
               "exact existing Lake renderer generation required")
    for path, pin in bound._pure_pins().items():
        lake._need(path not in observed or observed[path] == pin,
                   "parent bound norm pure producer observations disagree")
        observed[path] = pin
    observed[str(Path(__file__).resolve())] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return observed


_IMPORTED_PURE_PINS = _pure_pins()


def _parent_bound_norm_storage(preparation):
    offered = lake._bound_norm_storage(preparation)
    raw = offered["manifest_json"].encode("utf-8")
    manifest = lake.contracts.load_record_bytes(raw, expected_sha256=lake._sha(raw))
    lake._need(manifest.get("schema") == PARENT_BOUND_NORM_SCHEMA
               and manifest.get("profile") == PARENT_BOUND_NORM_PROFILE,
               "explicit parent bound norm project profile required")
    return offered


def parent_bound_norm_definition_preparation_sha256(preparation):
    """Commit the full exact-profile manifest and nine files, without authority."""
    _parent_bound_norm_storage(preparation)
    return lake.bound_norm_definition_preparation_sha256(preparation)


def _parent_bound_norm_capture(original, offered=None):
    # This established outer profile is intentionally smaller than the parent
    # bound owner's maximum. Complete overflow refuses before syntax imports.
    copied, commitment, base_commitment = lake._bound_norm_capture(original, offered)
    report = copied["bound_report"]
    lake._need(report.get("schema") == bound.PARENT_SCHEMA
               and report.get("profile") == bound.PARENT_PROFILE,
               "complete explicit parent bound-variable report required")
    if offered is not None:
        _parent_bound_norm_storage(offered)
    return copied, commitment, base_commitment


def _parent_bound_norm_preflight(copied):
    replay = dict(copied["bound_definition_inputs"], offered=copied["bound_report"],
        expected_report_sha256=copied["expected_bound_report_sha256"], validating=True)
    return bound._parent_bound_preflight(replay)


def _parent_bound_norm_pins(owners, bound_owners, evidence_owners):
    global _PARENT_BOUND_NORM_OPERATION_PINS
    observed = _pure_pins()
    lake._need(observed == _IMPORTED_PURE_PINS, "parent bound norm pure producers changed since import")
    for source in (bound._parent_bound_pins(bound_owners, evidence_owners), lake._pins(owners)):
        for path, pin in source.items():
            lake._need(path not in observed or observed[path] == pin,
                       "parent bound norm producer observations disagree")
            observed[path] = pin
    if _PARENT_BOUND_NORM_OPERATION_PINS is None:
        _PARENT_BOUND_NORM_OPERATION_PINS = dict(observed)
    lake._need(observed == _PARENT_BOUND_NORM_OPERATION_PINS,
               "parent bound norm source producers changed since first use")
    return observed


def _parent_bound_norm_callbacks(owners, bound_owners, evidence_owners):
    functions = (_pure_pins, _parent_bound_norm_storage, _parent_bound_norm_capture,
        _parent_bound_norm_preflight, _parent_bound_norm_pins, _parent_bound_norm_callbacks,
        _parent_bound_norm_runtime, _parent_bound_norm_serialized_fence,
        _parent_bound_norm_operation, _parent_bound_norm_manifest,
        _parent_bound_norm_context_populations, _parent_bound_norm_context_bindings,
        _parent_bound_norm_repackage,
        parent_bound_norm_definition_preparation_sha256,
        prepare_parent_bound_norm_definition_corpus_v1,
        validate_parent_bound_norm_definition_corpus_v1,
        lake._pure_pins, lake._pins, lake._owners, lake._bound_norm_storage,
        lake._bound_norm_capture, lake._parent_offered,
        lake.bound_norm_definition_preparation_sha256,
        lake._ParentInputBudget.__init__, lake._ParentInputBudget.copy, lake._ParentInputBudget.charge,
        lake._parent_commitment, lake._emit_parent_replay_value,
        lake._render_bound_norm_definition, lake._file, lake._digest, lake._sha,
        lake.contracts.seal_record, lake.contracts.load_record_bytes,
        lake.canonical_dag_json_bytes, lake.DefinitionUseCorpusPreparation.to_dict,
        owners[0].prepare_native_fragment, owners[0].producer_pins,
        json.dumps, json.loads)
    return bound._parent_bound_callbacks(bound_owners, evidence_owners) + tuple(
        (function, getattr(function, "__code__", None), id(getattr(function, "__defaults__", None)),
         id(getattr(function, "__kwdefaults__", None))) for function in functions)


def _parent_bound_norm_runtime(owners, bound_owners, evidence_owners):
    return {"schema": PARENT_BOUND_NORM_SCHEMA, "profile": PARENT_BOUND_NORM_PROFILE,
        "binding_schema": PARENT_BOUND_NORM_INPUT_BINDING_SCHEMA,
        "input_file_schema": PARENT_BOUND_NORM_INPUT_FILE_SCHEMA,
        "context_bindings_schema": PARENT_BOUND_NORM_CONTEXT_BINDINGS_SCHEMA,
        "authority": dict(PARENT_BOUND_NORM_FALSE_FLAGS), "legacy_lake_sha256": LEGACY_LAKE_SOURCE_SHA256,
        "namespace": lake._BOUND_NORM_NAMESPACE, "prelude": owners[1].PRELUDE,
        "input_bytes": lake.MAX_INPUT_BYTES, "expanded_values": 1_000_000, "depth": 48,
        "manifest_bytes": lake.contracts.MAX_RECORD_BYTES, "project_bytes": lake.MAX_PROJECT_BYTES,
        "files": lake.MAX_FILES, "preparation_wire_bytes": 20 * 1024 * 1024,
        "input_fields": sorted(lake._BOUND_NORM_INPUT_FIELDS),
        "bound_definition_fields": sorted(lake._BOUND_DEFINITION_INPUT_FIELDS),
        "toolchain_pattern": lake._TOOLCHAIN.pattern, "refused_pattern": lake._REFUSED.pattern,
        "parent_bound": bound._parent_bound_runtime(bound_owners, evidence_owners)}


def _parent_bound_norm_serialized_fence(preparation, expected_storage):
    lake._need(_parent_bound_norm_storage(preparation) == expected_storage,
               "parent bound norm preparation changed after final serialization")


def _parent_bound_norm_context_populations(companion):
    """Retain each original parent context under its actual parent schema."""
    norm = companion["norm_preparation"]
    return {"norm": {"preparation_sha256": companion["norm_preparation_sha256"],
                "source_identity": norm["source_identity"],
                "original_parent_context": norm["original_parent_context"],
                "obligations": norm["obligations"], "obligation_ids": norm["obligation_ids"],
                "context_obligation_ids": norm["context_obligation_ids"],
                "producer_pins": norm["producer_pins"]},
        "definitions": [{"ordinal": ordinal, "alternative_id": row["alternative_id"],
            "preparation_sha256": row["preparation_sha256"],
            "producer_pins": row["preparation"]["producer_pins"],
            "parent_source_binding": row["preparation"]["parent_source_binding"],
            "contexts": row["preparation"]["contexts"],
            "context_slot_ids": row["preparation"]["context_slot_ids"],
            "expected_context_population": row["preparation"]["expected_context_population"]}
            for ordinal, row in enumerate(companion["definitions"])]}


def _parent_bound_norm_repackage(checked, binding, rendered):
    """Store one whole report in the existing JSON file, without changing Lean."""
    files = dict(rendered[0])
    name = "bound-norm-input-bindings.json"
    lake._need(files[name] == lake.canonical_dag_json_bytes(binding).decode("utf-8") + "\n",
               "existing renderer must retain the exact original sealed input binding")
    container = {"schema": PARENT_BOUND_NORM_INPUT_FILE_SCHEMA,
        "profile": PARENT_BOUND_NORM_PROFILE, "review_intake_binding": binding,
        "parent_bound_definition_report": checked}
    raw = lake.canonical_dag_json_bytes(container) + b"\n"
    files[name] = raw.decode("utf-8")
    lake._need(len(files) == lake.MAX_FILES
               and sum(len(text.encode("utf-8")) for text in files.values()) <= lake.MAX_PROJECT_BYTES,
               "complete repackaged parent bound norm project exceeds existing byte bound")
    reference = {"file": name, "file_sha256": lake._sha(raw),
        "json_pointer": "/parent_bound_definition_report",
        "report_sha256": bound.bound_variable_definition_sha256(checked),
        "binding_json_pointer": "/review_intake_binding",
        "schema": PARENT_BOUND_NORM_INPUT_FILE_SCHEMA, "profile": PARENT_BOUND_NORM_PROFILE}
    return (files, *rendered[1:]), container, reference


def _parent_bound_norm_context_bindings(contexts, reference):
    """Bind exact body locations in the one retained whole original report."""
    digest = bound.evidence.norm.norm_review_sha256
    root = "/parent_bound_definition_report/companion"
    norm = contexts["norm"]
    return {"schema": PARENT_BOUND_NORM_CONTEXT_BINDINGS_SCHEMA,
        "report_ref_sha256": digest(reference), "projection_sha256": digest(contexts),
        "norm": {"preparation_sha256": norm["preparation_sha256"],
            "preparation_sha256_pointer": root + "/norm_preparation_sha256",
            "fields": {key: {"json_pointer": root + "/norm_preparation/" + key,
                              "sha256": digest(norm[key])}
                for key in ("source_identity", "original_parent_context", "obligations", "obligation_ids",
                            "context_obligation_ids", "producer_pins")}},
        "definitions": [{"ordinal": row["ordinal"], "alternative_id": row["alternative_id"],
            "alternative_id_pointer": root + "/definitions/" + str(row["ordinal"]) + "/alternative_id",
            "preparation_sha256": row["preparation_sha256"],
            "preparation_sha256_pointer": root + "/definitions/" + str(row["ordinal"]) + "/preparation_sha256",
            "fields": {key: {"json_pointer": root + "/definitions/" + str(row["ordinal"]) + "/preparation/" + key,
                              "sha256": digest(row[key])}
                for key in ("producer_pins", "parent_source_binding", "contexts", "context_slot_ids",
                            "expected_context_population")}}
            for row in contexts["definitions"]]}


def _parent_bound_norm_manifest(checked, norm, copied, input_commitment, pins, rendered,
                                binding, context_bindings, report_ref):
    files, fragments, modules, imports, theorems, source_binding = rendered
    companion = checked["companion"]
    original = checked["original_norm"]
    lake._need(report_ref["report_sha256"] == copied["expected_bound_report_sha256"]
               and files[report_ref["file"]].encode("utf-8")
                   == lake.canonical_dag_json_bytes({"schema": PARENT_BOUND_NORM_INPUT_FILE_SCHEMA,
                       "profile": PARENT_BOUND_NORM_PROFILE, "review_intake_binding": binding,
                       "parent_bound_definition_report": checked}) + b"\n",
               "complete original parent-bound project input container differs")
    return lake.contracts.seal_record({"schema": PARENT_BOUND_NORM_SCHEMA,
        "profile": PARENT_BOUND_NORM_PROFILE, "toolchain": copied["toolchain"],
        "review_intake_binding": binding, "original_input_commitment_sha256": input_commitment,
        "bound_definition_report_sha256": copied["expected_bound_report_sha256"],
        "parent_bound_definition_report_ref": report_ref, "original_norm": original,
        "occurrence_binding": checked["occurrence_binding"], "selected_link": checked["selected_link"],
        "definition_alternative_refs": checked["definition_alternative_refs"],
        "nomination_inventory": checked["nomination_inventory"],
        "bound_definition_mode": checked["request"]["mode"],
        "conditional_theorem_statements": checked["conditional_theorem_statements"],
        "original_parent_context_bindings": context_bindings,
        "conditional_source_binding": source_binding,
        "review_evidence_status": "unsigned_pending_source_meaning_and_applicability",
        "review_blockers": {"norm_obligations": context_bindings["norm"]["fields"]["obligations"],
            "definition_context_slot_ids": [{"ordinal": row["ordinal"],
                "alternative_id": row["alternative_id"],
                "context_slot_ids": row["fields"]["context_slot_ids"]}
                for row in context_bindings["definitions"]]},
        "review_prerequisites_satisfied_under_selected_trust": False,
        "native_fragments": fragments, "expected_modules": modules, "module_imports": imports,
        "file_sha256": {name: lake._sha(text.encode("utf-8")) for name, text in sorted(files.items())},
        "conditional_theorems": theorems,
        "theorem_assumptions": [
            "The complete supplied norm and unary donor use the same arbitrary Entity carrier, Interpretation and fixed formal Nat time.",
            "hDefinition remains an explicit unverified premise; body mode additionally assumes exact matching hMembership.",
            "Only conditional definition instances and unchanged original-norm alias identity are prepared; norm truth, actual membership and applicability are not inferred.",
            "Every parent norm/definition population, unresolved context, alternative and nomination remains retained in the complete original parent-bound report in the project input file.",
            "No definition substitution, modal rewrite, statutory meaning, civil legal-as-of decision, graph admission or learning target is supplied.",
        ],
        "producer_pins": pins, "native_producer_pins": fragments[0]["native"]["producer_pins"],
        "renderer_compatibility": {"owner": "ipfs_datasets_py.logic.autoformal.legal_corpus_definition_use_lake_v2",
            "source_sha256": LEGACY_LAKE_SOURCE_SHA256, "existing_project_renderer_reused": True,
            "legacy_owner_source_unchanged": True, "namespace_packaging_only": True},
        "execution_handoff": {"status": "parent_bound_norm_execution_adapter_not_registered", "target": "legal",
            "argv_recipe": ["<verified-native-lake>", "--offline", "--no-cache", "build", "legal"],
            "expected_olean_paths": [".lake/build/lib/lean/" + name.replace(".", "/") + ".olean" for name in modules],
            "expected_theorem_axiom_dependencies": {name: [] for name in theorems},
            "observed_theorem_axiom_dependencies": None, "installed_binary_pins": None,
            "processes_executed": 0, "build_eligible": False},
        "input_budget": {"bytes": lake.MAX_INPUT_BYTES, "expanded_values": 1_000_000, "depth": 48,
            "complete_overflow_refused": True},
        "preparation_only": True, "lean_compilation_status": "not_run", "proof_status": "pending",
        "authority": {**dict(bound.AUTHORITY), **PARENT_BOUND_NORM_FALSE_FLAGS},
        "native_ast_rewritten": False, "norm_interpretation_ready": False,
        "selected_interpretation": None, "governing_definition_use": None,
        "semantic_mask": 0, "consumer_mask": 0, "training_mask": 0, "evaluation_gold_mask": 0,
        "external_complete_inputs_required": True, **PARENT_BOUND_NORM_FALSE_FLAGS})


def _parent_bound_norm_operation(original, offered=None, expected_preparation_sha256=None):
    lake._need(_pure_pins() == _IMPORTED_PURE_PINS,
               "parent bound norm pure producers changed since import")
    if offered is not None:
        lake.contracts.require_sha256(expected_preparation_sha256, "independent complete parent bound norm project")
        lake._need(parent_bound_norm_definition_preparation_sha256(offered) == expected_preparation_sha256,
                   "independent complete parent bound norm project pin differs")
    copied, commitment, base_commitment = _parent_bound_norm_capture(original, offered)
    preflight = _parent_bound_norm_preflight(copied)
    owners, bound_owners = lake._owners(), bound._owners()
    evidence_owners = bound.evidence._parent_definition_owners()
    _, lineage, scope = evidence_owners
    pins = _parent_bound_norm_pins(owners, bound_owners, evidence_owners)
    callbacks = _parent_bound_norm_callbacks(owners, bound_owners, evidence_owners)
    runtime = lake._parent_commitment(lake._ParentInputBudget().copy(
        _parent_bound_norm_runtime(owners, bound_owners, evidence_owners)))
    held, physical = [], []
    started = False
    state = {"opened": None, "closed": None, "preparation": None, "storage": None}
    primary = None

    def hold(value, label):
        snapshot = lake._parent_commitment(lake._ParentInputBudget().copy(value))
        held.append((value, snapshot, label))
        return value

    # The upstream pure preflight returns a tuple. Preserve its complete ordinary
    # detached values without introducing a tuple into the inherited JSON fence.
    hold(list(preflight), "complete pure parent-bound preflight")

    def fence():
        lake._need(_parent_bound_norm_callbacks(owners, bound_owners, evidence_owners) == callbacks,
                   "parent bound norm replay, rendering or custody callback changed")
        lake._need(lake._parent_commitment(lake._ParentInputBudget().copy(
                       _parent_bound_norm_runtime(owners, bound_owners, evidence_owners))) == runtime,
                   "parent bound norm profile policy or bounds changed")
        lake._need(_parent_bound_norm_pins(owners, bound_owners, evidence_owners) == pins,
                   "parent bound norm source producer changed")
        for plan, witness, frozen in physical:
            lake._need(lake._parent_commitment(lake._ParentInputBudget().copy(plan)) == frozen,
                       "parent bound norm physical file plan changed")
            lake._need(bound.evidence._parent_definition_file_witness(plan, lineage) == witness,
                       "original parent bound norm or definition physical file changed")
        lake._need(_parent_bound_norm_capture(original, offered)[1] == commitment,
                   "original parent bound norm inputs or offered project changed")
        lake._need(lake._parent_commitment(lake._ParentInputBudget().copy(copied)) == commitment,
                   "detached parent bound norm inputs changed")
        for value, snapshot, label in held:
            lake._need(lake._parent_commitment(lake._ParentInputBudget().copy(value)) == snapshot,
                       "retained parent bound norm actual return changed: " + label)
        if state["preparation"] is not None:
            lake._need(_parent_bound_norm_storage(state["preparation"]) == state["storage"],
                       "parent bound norm project changed after genuine serialization")

    def replay(label):
        checked = bound.validate_parent_bound_variable_definition_v1(copied["bound_report"],
            expected_report_sha256=copied["expected_bound_report_sha256"],
            **copied["bound_definition_inputs"])
        hold(checked, label)
        lake._need(bound.bound_variable_definition_sha256(checked) == copied["expected_bound_report_sha256"],
                   "genuine complete parent-bound regeneration differs")
        return checked

    def closing_replay():
        if started:
            fence()
            state["closed"] = replay("closing genuine parent-bound report")
            if state["opened"] is not None:
                lake._need(lake._parent_commitment(state["closed"]) == lake._parent_commitment(state["opened"]),
                           "closing parent-bound report differs from opening")

    def final_storage():
        if state["preparation"] is not None:
            _parent_bound_norm_serialized_fence(state["preparation"], state["storage"])

    try:
        fence()
        started = True
        checked = replay("opening genuine parent-bound report")
        state["opened"] = checked
        fence()
        inputs = copied["bound_definition_inputs"]["companion_inputs"]
        replays = [inputs["norm_inputs"]["correspondence_inputs"]["scope_replay_inputs"]["replay_inputs"]]
        replays.extend(endpoint["preparation_inputs"]["parent_inputs"]["replay_inputs"]
                       for endpoint in inputs["definitions"])
        for replay_inputs in replays:
            fence()
            plan = hold(bound.evidence._parent_definition_file_plan(replay_inputs, lineage),
                        "complete actual parent/definition physical plan")
            frozen = lake._parent_commitment(lake._ParentInputBudget().copy(plan))
            witness = hold(bound.evidence._parent_definition_file_witness(plan, lineage),
                           "complete actual parent/definition physical witness")
            physical.append((plan, witness, frozen))
            fence()
        companion = checked["companion"]
        contexts = hold(_parent_bound_norm_context_populations(companion),
                        "complete original parent norm and every definition context")
        preparation = companion["norm_preparation"]
        norm = preparation["correspondence"]["relational_fragment"]
        digest = bound.evidence.norm.norm_review_sha256
        original_norm = checked["original_norm"]
        lake._need(original_norm["unchanged"] is True
                   and original_norm["preparation_sha256"] == inputs["expected_norm_preparation_sha256"]
                   and original_norm["correspondence_sha256"] == preparation["correspondence_sha256"]
                   and original_norm["ast_sha256"] == digest(norm["typed_expression"])
                   and original_norm["native_ast_sha256"] == digest(norm["native_ast"]),
                   "complete original parent norm/AST commitments differ")
        lake._need(norm["source_binding"] is None and norm["source_bound"] is False
                   and checked["selected_interpretation"] is None and checked["governing_definition_use"] is None
                   and all(value is False for value in checked["authority"].values())
                   and all(type(checked[key]) is int and checked[key] == 0 for key in
                           ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask")),
                   "original parent-bound null decisions and zero authority must remain unchanged")
        binding = hold(lake.contracts.seal_record({"schema": PARENT_BOUND_NORM_INPUT_BINDING_SCHEMA,
            "profile": PARENT_BOUND_NORM_PROFILE, "original_input_commitment_sha256": base_commitment,
            "bound_definition_report_sha256": copied["expected_bound_report_sha256"],
            "bound_definition_request_sha256": checked["request_sha256"],
            "companion_sha256": checked["companion_sha256"], "original_norm": original_norm,
            "source_context_sha256": digest(contexts),
            "selected_link_sha256": digest(checked["selected_link"]),
            "occurrence_binding_sha256": digest(checked["occurrence_binding"]),
            "definition_alternative_refs_sha256": digest(checked["definition_alternative_refs"]),
            "nomination_inventory_sha256": digest(checked["nomination_inventory"]),
            "bound_definition_mode": checked["request"]["mode"]}), "sealed parent bound norm input binding")
        original_rendered = lake._render_bound_norm_definition(checked, norm, copied["toolchain"], binding, owners)
        hold(list(original_rendered), "whole actual existing Lake renderer return")
        rendered, container, report_ref = _parent_bound_norm_repackage(checked, binding, original_rendered)
        hold(list(rendered), "complete repackaged project with one original report")
        hold(container, "complete original report project input container")
        hold(report_ref, "complete original report file reference")
        context_bindings = hold(_parent_bound_norm_context_bindings(contexts, report_ref),
                                "exact full original context hash and file-pointer bindings")
        fence()
        manifest = hold(_parent_bound_norm_manifest(checked, norm, copied, base_commitment, pins, rendered,
                                                   binding, context_bindings, report_ref),
                        "sealed complete parent bound norm manifest")
        text = lake.canonical_dag_json_bytes(manifest).decode("utf-8")
        result = DefinitionUseCorpusPreparation(text, tuple(sorted(rendered[0].items())))
        state["preparation"] = result
        state["storage"] = lake._ParentInputBudget().copy(_parent_bound_norm_storage(result))
        parent_bound_norm_definition_preparation_sha256(result)
        if offered is not None:
            lake._need(copied["offered"] == state["storage"],
                       "parent bound norm project differs from complete original regeneration")
        fence()
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        scope._parent_finish((fence, closing_replay, fence, final_storage, fence,
                              final_storage, fence), primary)


def prepare_parent_bound_norm_definition_corpus_v1(bound_report, *, expected_bound_report_sha256,
        bound_definition_inputs, toolchain):
    """Prepare one unchanged parent norm and conditional definition project.

    The inherited 48-MiB/depth48/one-million-value outer profile refuses complete
    overflow. Preparation does not write files, probe tools or execute a build.
    """
    return _parent_bound_norm_operation(dict(bound_report=bound_report,
        expected_bound_report_sha256=expected_bound_report_sha256,
        bound_definition_inputs=bound_definition_inputs, toolchain=toolchain))


def validate_parent_bound_norm_definition_corpus_v1(preparation, bound_report, *,
        expected_preparation_sha256, expected_bound_report_sha256, bound_definition_inputs, toolchain):
    """Regenerate every project byte from independently pinned parent inputs."""
    return _parent_bound_norm_operation(dict(bound_report=bound_report,
        expected_bound_report_sha256=expected_bound_report_sha256,
        bound_definition_inputs=bound_definition_inputs, toolchain=toolchain),
        preparation, expected_preparation_sha256)


__all__ = ["PARENT_BOUND_NORM_SCHEMA", "PARENT_BOUND_NORM_PROFILE",
    "PARENT_BOUND_NORM_INPUT_BINDING_SCHEMA", "PARENT_BOUND_NORM_INPUT_FILE_SCHEMA",
    "PARENT_BOUND_NORM_CONTEXT_BINDINGS_SCHEMA", "PARENT_BOUND_NORM_FALSE_FLAGS",
    "DefinitionUseCorpusPreparation", "prepare_parent_bound_norm_definition_corpus_v1",
    "validate_parent_bound_norm_definition_corpus_v1", "parent_bound_norm_definition_preparation_sha256"]
