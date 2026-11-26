"""Prepare exact namespace-bound elaboration probes for engineering lineage.

The complete current retained-packet and typed lineage validators own source
and review replay. This additive preparation copies each exact header, changes
only its theorem name, and supplies the original theorem at every explicit
parameter. Generated Lean checks closed original/alias theorem types using
structural expression equality and the official kernel APIs. Preparation
executes nothing and issues no proof result, receipt, or legal artifact.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

SCHEMA = "legal-corpus-v2-definition-use-preservation-elaboration-preparation/v1"
PROFILE = "replayed-corpus-preservation-exact-header-elaboration/v1"
OBSERVATION_SCHEMA = "legal-corpus-v2-native-theorem-type-check/v1"
OBSERVATION_PREFIX = "CORPUS_TYPE_CHECK:"
PROJECT_ROOT = "LegalCorpusV2Elaboration"
PHYSICAL_PROBE_SCHEMA = "legal-corpus-v4-planned-physical-whole-norm-elaboration-preparation/v1"
PHYSICAL_PROBE_PROFILE = "independent-physical-whole-norm-proposition-elaboration/v1"
PHYSICAL_TYPE_OBSERVATION_SCHEMA = "legal-physical-whole-norm-closed-type-probe/v1"
PHYSICAL_PROBE_MODULE = "PhysicalWholeNormElaboration"
MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_FILES = 17
MAX_MODULES = 13
MAX_THEOREMS = 30
_PACKET_ARGUMENTS = frozenset({
    "expected_preparation_sha256", "expected_corpus_preparation_sha256",
    "expected_assessment_file_sha256", "expected_receipt_file_sha256",
    "expected_bundle_sha256", "review_inputs", "toolchain", "expected_binary_sha256",
})
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
FALSE_FLAGS = dict.fromkeys((
    "source_authenticity_verified", "publisher_authenticity_verified",
    "legal_currentness_verified", "source_semantics_verified", "applicability_verified",
    "context_closure_verified", "independently_reviewed", "human_identity_verified",
    "human_independence_verified", "meaning_admitted", "admitted", "formalized",
    "semantic_graph_admitted", "proof_authority", "training_qualified",
    "training_gold_qualified", "evaluation_gold_qualified", "Lean_admitted",
    "model_executed", "learned_translation", "source_to_model_equivalence_proved",
    "source_fidelity_proved", "translation_preservation_proved",
    "cross_family_equivalence_verified", "general_emitter_preservation_proved",
    "general_serialized_AST_lowering_preservation_proved", "json_bytes_parser_verified",
    "json_bytes_parser_preservation_proved", "model_convergence_proved", "convergence_proved",
    "backend_executed", "lean_compilation_verified", "proof_checked", "kernel_proofs_checked",
    "corpus_native_AST_preservation_proved", "conditional_proofs_verified",
    "alias_assumption_proved", "legal_proof_cache_compatible", "proof_cache_admission_verified",
    "semantic_definition_binding_verified", "per_occurrence_lookup_verified",
    "accepted_view_eligible", "combined_use_review_verified", "native_execution_performed",
    "fresh_native_execution_performed", "proof_validation_performed",
    "olean_kernel_rechecked", "installed_compiler_revalidated", "cryptographic_authenticity_verified",
    "elaborated_type_verified", "executable_kernel_target_prepared",
    "formalization_artifact_created", "backend_request_prepared",
    "typed_native_attempt_observed", "typed_theorem_result_observed",
    "theorem_receipt_issued", "compiled_artifact_execution_reused",
    "elaborated_term_dependencies_verified", "source_prose_correspondence_proved",
    "installed_stdlib_artifact_closure_verified",
), False)
AUTHORITY = dict.fromkeys(
    ("source", "legal", "review", "proof", "model", "training", "gold", "corpus_admission"), False)

# Serialization is a bounded observation of Lean's elaborated Expr, not a new
# source-to-logic translator. Metadata/free/metavariable constructors refuse
# this deliberately closed profile rather than being silently erased.
LEAN_CHECKER = r'''namespace CorpusPreservationElaboration
open Lean

private def nameJson : Name → Json
  | .anonymous => Json.mkObj [("kind", toJson "anonymous")]
  | .str parent value => Json.mkObj [("kind", toJson "str"), ("parent", nameJson parent), ("value", toJson value)]
  | .num parent value => Json.mkObj [("kind", toJson "num"), ("parent", nameJson parent), ("value", toJson value)]

private partial def levelJson : Level → Elab.Term.TermElabM Json
  | .zero => pure <| Json.mkObj [("kind", toJson "zero")]
  | .succ value => do pure <| Json.mkObj [("kind", toJson "succ"), ("of", ← levelJson value)]
  | .max left right => do pure <| Json.mkObj [("kind", toJson "max"), ("left", ← levelJson left), ("right", ← levelJson right)]
  | .imax left right => do pure <| Json.mkObj [("kind", toJson "imax"), ("left", ← levelJson left), ("right", ← levelJson right)]
  | .param name => pure <| Json.mkObj [("kind", toJson "param"), ("name", nameJson name)]
  | .mvar _ => throwError "corpus type mismatch: unresolved universe metavariable"

private def binderJson : BinderInfo → Json
  | .default => toJson "default"
  | .implicit => toJson "implicit"
  | .strictImplicit => toJson "strictImplicit"
  | .instImplicit => toJson "instImplicit"

private partial def exprJson : Expr → Elab.Term.TermElabM Json
  | .bvar index => pure <| Json.mkObj [("kind", toJson "bvar"), ("index", toJson index)]
  | .sort level => do pure <| Json.mkObj [("kind", toJson "sort"), ("level", ← levelJson level)]
  | .const name levels => do
      pure <| Json.mkObj [("kind", toJson "const"), ("name", nameJson name), ("levels", toJson (← levels.mapM levelJson))]
  | .app fn arg => do
      pure <| Json.mkObj [("kind", toJson "app"), ("fn", ← exprJson fn), ("arg", ← exprJson arg)]
  | .lam name type body info => do
      pure <| Json.mkObj [("kind", toJson "lam"), ("binder_name", nameJson name), ("binder_info", binderJson info), ("binder_type", ← exprJson type), ("body", ← exprJson body)]
  | .forallE name type body info => do
      pure <| Json.mkObj [("kind", toJson "forallE"), ("binder_name", nameJson name), ("binder_info", binderJson info), ("binder_type", ← exprJson type), ("body", ← exprJson body)]
  | .letE name type value body nondep => do
      pure <| Json.mkObj [("kind", toJson "letE"), ("name", nameJson name), ("type", ← exprJson type), ("value", ← exprJson value), ("body", ← exprJson body), ("nondep", toJson nondep)]
  | .lit (.natVal value) => pure <| Json.mkObj [("kind", toJson "natVal"), ("value", toJson value)]
  | .lit (.strVal value) => pure <| Json.mkObj [("kind", toJson "strVal"), ("value", toJson value)]
  | .proj name index value => do
      pure <| Json.mkObj [("kind", toJson "proj"), ("name", nameJson name), ("index", toJson index), ("value", ← exprJson value)]
  | .fvar _ => throwError "corpus type mismatch: unresolved free variable"
  | .mvar _ => throwError "corpus type mismatch: unresolved expression metavariable"
  | .mdata _ _ => throwError "corpus type mismatch: expression metadata outside closed observation profile"

def check (originalName aliasName : Name) : Elab.Term.TermElabM Unit := do
  let originalInfo ← getConstInfo originalName
  let aliasInfo ← getConstInfo aliasName
  let .thmInfo original := originalInfo
    | throwError "corpus type mismatch: original is not a theorem"
  let .thmInfo alias := aliasInfo
    | throwError "corpus type mismatch: alias is not a theorem"
  if original.type.hasFVar || original.type.hasMVar || original.type.hasLooseBVars ||
      alias.type.hasFVar || alias.type.hasMVar || alias.type.hasLooseBVars then
    throwError "corpus type mismatch: theorem type is not closed"
  unless original.levelParams == alias.levelParams do
    throwError "corpus type mismatch: universe parameter inventory differs"
  unless Expr.equal original.type alias.type do
    throwError "corpus type mismatch: exact original and alias expressions differ"
  let env ← getEnv
  match Kernel.isDefEq env {} original.type alias.type with
  | .ok true => pure ()
  | _ => throwError "corpus type mismatch: kernel definitional equality rejected"
  match Kernel.check env {} original.type with
  | .ok (.sort .zero) => pure ()
  | _ => throwError "corpus type mismatch: original theorem type is not a kernel proposition"
  match Kernel.check env {} alias.type with
  | .ok (.sort .zero) => pure ()
  | _ => throwError "corpus type mismatch: alias theorem type is not a kernel proposition"
  match Kernel.check env {} (mkConst originalName (original.levelParams.map Level.param)) with
  | .ok checked => unless Expr.equal checked original.type do
      throwError "corpus type mismatch: original constant kernel type differs"
  | _ => throwError "corpus type mismatch: original constant kernel check rejected"
  match Kernel.check env {} (mkConst aliasName (alias.levelParams.map Level.param)) with
  | .ok checked => unless Expr.equal checked alias.type do
      throwError "corpus type mismatch: alias constant kernel type differs"
  | _ => throwError "corpus type mismatch: alias constant kernel check rejected"
  let originalType ← exprJson original.type
  let aliasType ← exprJson alias.type
  let record := Json.mkObj [
    ("schema", toJson "legal-corpus-v2-native-theorem-type-check/v1"),
    ("original_name", toJson originalName.toString), ("alias_name", toJson aliasName.toString),
    ("original_type", originalType), ("alias_type", aliasType),
    ("original_level_params", toJson (original.levelParams.map nameJson)),
    ("alias_level_params", toJson (alias.levelParams.map nameJson)),
    ("expr_equal", toJson true), ("kernel_defeq", toJson true),
    ("original_kernel_check", toJson true), ("alias_kernel_check", toJson true),
    ("closed_types", toJson true), ("prop_type", toJson true), ("level_params_equal", toJson true)]
  logInfo ("CORPUS_TYPE_CHECK:" ++ record.compress)

end CorpusPreservationElaboration
'''


def _need(value, message):
    if not value:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value, label):
    _need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
          "independent lowercase SHA256 required: " + label)


def _wire(value):
    # The already qualified bounded JSON owner is cold stdlib-only. Imports
    # of source/review/claim operation owners remain behind exact preflight.
    from . import legal_corpus_definition_use_preservation_theorem_lineage_v2 as lineage_owner
    return lineage_owner._wire(value)


def _parse(raw):
    from . import legal_corpus_definition_use_preservation_theorem_lineage_v2 as lineage_owner
    return lineage_owner._parse(raw)


@dataclass(frozen=True, slots=True)
class ElaborationPreparation:
    manifest_json: str
    files: tuple[tuple[str, str], ...]

    def to_dict(self):
        _need(type(self.manifest_json) is str and 0 < len(self.manifest_json) <= MAX_RECORD_BYTES,
              "bounded elaboration preparation manifest text required")
        try:
            raw = self.manifest_json.encode("utf-8")
        except UnicodeError as error:
            raise ValueError("valid elaboration manifest UTF8 required") from error
        return _parse(raw)


def _envelope(preparation):
    _need(type(preparation) is ElaborationPreparation, "exact elaboration preparation storage type required")
    manifest = ElaborationPreparation.to_dict(preparation)
    _need(type(manifest) is dict, "exact elaboration preparation manifest required")
    key = (manifest.get("schema"), manifest.get("profile"))
    _need(key in ((SCHEMA, PROFILE), (PHYSICAL_PROBE_SCHEMA, PHYSICAL_PROBE_PROFILE)),
          "exact elaboration preparation schema/profile required")
    _need(type(preparation.files) is tuple, "exact immutable elaboration preparation files required")
    if key == (SCHEMA, PROFILE):
        _need(len(preparation.files) == MAX_FILES, "exact seventeen immutable elaboration preparation files required")
    else:
        from . import legal_corpus_definition_use_native_v2 as native
        _need(2 <= len(preparation.files) <= native.MAX_REVIEWED_PRESERVATION_FILES + 1,
              "bounded additive physical elaboration sources required")
    rows, previous, budget = [], None, MAX_RECORD_BYTES
    for pair in preparation.files:
        _need(type(pair) is tuple and len(pair) == 2 and type(pair[0]) is str and type(pair[1]) is str,
              "ordinary immutable elaboration path/text pairs required")
        name, body = pair
        path = PurePosixPath(name)
        _need(0 < len(name) <= 256 and not path.is_absolute() and str(path) == name
              and len(path.parts) <= 3 and all(part not in ("", ".", "..") for part in path.parts)
              and re.fullmatch(r"[A-Za-z0-9_./-]+", name) is not None
              and (previous is None or previous < name),
              "unique sorted safe closed elaboration project paths required")
        previous = name
        _need(len(body) <= budget and "\x00" not in body, "bounded elaboration source text required")
        try:
            budget -= len(name.encode("utf-8")) + len(body.encode("utf-8"))
        except UnicodeError as error:
            raise ValueError("valid elaboration source UTF8 required") from error
        _need(budget >= 0, "complete elaboration preparation project byte bound exceeded")
        rows.append([name, body])
    _need(all(manifest.get(key) is False for key in FALSE_FLAGS)
          and type(manifest.get("authority")) is dict and manifest["authority"] == AUTHORITY
          and all(value is False for value in manifest["authority"].values())
          and type(manifest.get("training_mask")) is int and manifest["training_mask"] == 0
          and type(manifest.get("evaluation_gold_mask")) is int and manifest["evaluation_gold_mask"] == 0,
          "non-authorizing pure elaboration preparation required")
    return {"manifest_json": preparation.manifest_json, "files": rows}


def preparation_sha256(preparation):
    return _sha(_wire(_envelope(preparation)))


elaboration_preparation_sha256 = preparation_sha256


def _producer_pins(document, owners):
    pins = dict(document["producer_pins"])
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    for owner in owners:
        source = Path(owner.__file__).resolve()
        digest = _sha(source.read_bytes())
        _need(str(source) not in pins or pins[str(source)] == digest,
              "qualified lineage producer identity changed")
        pins[str(source)] = digest
    return pins


def _probe_binding(entry, expected_lineage_sha256):
    original, header = entry["theorem_name"], entry["declaration_header"]
    module, short = original.rsplit(".", 1)
    _need(entry["source_namespace"] == module and entry["source_module"] == module
          and header.startswith("theorem " + short + " ")
          and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", original) is not None,
          "exact original namespaced theorem header required")
    alias_short = "lineage_type_" + _sha(_wire({
        "profile": PROFILE, "lineage_sha256": expected_lineage_sha256,
        "original_theorem_name": original, "claim_digest": entry["claim_digest"],
        "obligation_digest": entry["obligation_digest"],
    }))
    probe_header = "theorem " + alias_short + header[len("theorem " + short):]
    arguments = [name for binder in entry["parameter_binders"] for name in binder["names"]]
    arguments.extend(premise["binder_name"] for premise in entry["proposition_premises"])
    expected_arguments = {
        "consumer_predicate_iff_donor_body": ["Entity", "Agent", "i", "t", "entity", "hDonor", "hAlias"],
        "joint_of_components": ["Entity", "Agent", "i", "t", "hDonor", "hConsumer", "hAlias"],
        "joint_matches_original": ["Entity", "Agent", "i", "t"],
        "native_value_exact": [], "native_ast_closed": [],
        "denotation_matches_native": ["Entity", "Agent", "i", "t"],
    }
    _need(short in expected_arguments and arguments == expected_arguments[short],
          "complete closed explicit original theorem argument vector required")
    probe_name = module + "." + alias_short
    proof = "  exact @" + original + (" " + " ".join(arguments) if arguments else "") + "\n"
    block = ("namespace " + module + "\n" + probe_header + " := by\n" + proof
             + "#print axioms " + alias_short + "\nend " + module + "\n")
    check = "run_elab CorpusPreservationElaboration.check `" + original + " `" + probe_name + "\n"
    return {
        "original_theorem_name": original, "probe_theorem_name": probe_name,
        "original_header": header, "probe_header": probe_header, "argument_names": arguments,
        "probe_block": block, "probe_proof_body": proof, "check_command": check,
        "probe_block_sha256": _sha(block.encode("utf-8")),
        "original_header_sha256": entry["byte_ranges"]["header"]["sha256"],
        "probe_header_sha256": _sha(probe_header.encode("utf-8")),
        "source_namespace": module, "role": entry["role"], "native_family": entry["native_family"],
        "claim_id": entry["claim_id"], "claim_digest": entry["claim_digest"],
        "declaration_id": entry["declaration_id"],
        "obligation_id": entry["obligation_id"], "obligation_digest": entry["obligation_digest"],
        "assumption_ids": entry["assumption_ids"],
        "proposition_premises": entry["proposition_premises"], "parameter_binders": entry["parameter_binders"],
        "original_byte_ranges": entry["byte_ranges"],
        "declared_import_closure": entry["declared_import_closure"],
        "target_declaration": entry["target_declaration"],
        "native_fragment_binding": entry["native_fragment_binding"],
    }


def prepare_definition_use_preservation_elaboration_v2(
        lineage, packet_files, corpus_preparation, assessment_raw, *,
        expected_lineage_sha256, expected_packet_observation_sha256, **packet_arguments):
    """Replay exact typed lineage and prepare a fresh source-only probe project.

    No retained olean is an input. Installed standard/dynamic libraries are a
    trusted external toolchain premise; their complete closure is not scanned.
    All original donor/consumer/alias hypotheses and review state are retained.
    """
    _pin(expected_lineage_sha256, "complete current opaque theorem lineage")
    _pin(expected_packet_observation_sha256, "exact current packet observation")
    _need(set(packet_arguments) == _PACKET_ARGUMENTS, "complete closed original packet arguments required")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "elaboration preparation owner changed since import")
    from . import legal_corpus_definition_use_preservation_theorem_lineage_v2 as lineage_owner
    from . import legal_corpus_definition_use_preservation_packet_v2 as reader
    from . import legal_corpus_definition_use_preservation_index_v2 as index
    reader._bound_tree(packet_arguments, reader.MAX_INPUT_BYTES, allow_bytes=True)
    argument_pin = index._tree_digest(packet_arguments)
    original_corpus = reader._wire(reader._corpus_document(corpus_preparation), 20 * reader.MAX_RECORD_BYTES)
    original_lineage_pin = lineage_owner.lineage_sha256(lineage)
    _need(original_lineage_pin == expected_lineage_sha256, "independent exact original lineage pin differs")
    original_claims = lineage_owner._wire(lineage_owner._claim_snapshot(lineage.claims))
    validated = lineage_owner.validate_definition_use_preservation_theorem_lineage_v2(
        lineage, packet_files, corpus_preparation, assessment_raw,
        expected_lineage_sha256=expected_lineage_sha256,
        expected_packet_observation_sha256=expected_packet_observation_sha256, **packet_arguments)
    reader._bound_tree(packet_arguments, reader.MAX_INPUT_BYTES, allow_bytes=True)
    _need(index._tree_digest(packet_arguments) == argument_pin
          and lineage_owner.lineage_sha256(lineage) == original_lineage_pin
          and lineage_owner._wire(lineage_owner._claim_snapshot(lineage.claims)) == original_claims,
          "original typed lineage or complete arguments changed during elaboration replay")
    document = validated.to_dict()
    from . import corpus_contracts as contracts
    producers = _producer_pins(document, (lineage_owner, reader, index, contracts))
    packet = dict(packet_files)
    original_manifest = reader._parse(packet["project/corpus-manifest.json"])
    files = {path.removeprefix("project/"): raw.decode("utf-8")
             for path, raw in packet.items() if path.startswith("project/") and path != "project/corpus-manifest.json"}
    _need(len(files) == 16 and set(files) == set(original_manifest["file_sha256"]),
          "exact unchanged original sixteen-file preservation project required")
    old_files = dict(files)
    lake = files["lakefile.toml"]
    old_roots = 'roots = ["LegalCorpusV2", "LegalCorpusV2Preservation"]'
    _need(lake.count(old_roots) == 1, "exact original two-root Lake registration required")
    files["lakefile.toml"] = lake.replace(old_roots, old_roots[:-1] + ', "' + PROJECT_ROOT + '"]', 1)
    bindings = [_probe_binding(entry, expected_lineage_sha256) for entry in document["entries"]]
    original_theorems = [binding["original_theorem_name"] for binding in bindings]
    probe_theorems = [binding["probe_theorem_name"] for binding in bindings]
    _need(len(bindings) == len(set(probe_theorems)) == 15
          and original_theorems == original_manifest["theorems"]
          and all(name not in original_theorems for name in probe_theorems),
          "exact collision-free fifteen original and fifteen probe theorem names required")
    for binding in bindings:
        short = binding["probe_theorem_name"].rsplit(".", 1)[1]
        _need(not any(re.search(r"\b" + re.escape(short) + r"\b", body) for body in old_files.values()),
              "probe theorem name collides with an original source identifier")
    imports = ["Lean", "LegalCorpusV2", "LegalCorpusV2Preservation"]
    probe_source = ("".join("import " + name + "\n" for name in imports) + "\n"
                    + LEAN_CHECKER + "\n"
                    + "\n".join(binding["probe_block"] for binding in bindings) + "\n"
                    + "".join(binding["check_command"] for binding in bindings))
    files[PROJECT_ROOT + ".lean"] = probe_source
    modules = [*original_manifest["expected_modules"], PROJECT_ROOT]
    module_imports = {**original_manifest["module_imports"], PROJECT_ROOT: imports}
    _need(len(files) == MAX_FILES and len(modules) == len(set(modules)) == MAX_MODULES
          and all(files[path] == body for path, body in old_files.items() if path != "lakefile.toml"),
          "exact seventeen-file/thirteen-module additive elaboration project required")
    manifest = contracts.seal_record({
        "schema": SCHEMA, "profile": PROFILE, "toolchain": packet_arguments["toolchain"], "target": "legal",
        "lineage_file_sha256": expected_lineage_sha256, "lineage_record_cid": document["record_cid"],
        "lineage_context_sha256": document["lineage_context_sha256"],
        "packet_observation_sha256": expected_packet_observation_sha256,
        "packet_bundle_sha256": packet_arguments["expected_bundle_sha256"],
        "receipt_file_sha256": packet_arguments["expected_receipt_file_sha256"],
        "preservation_preparation_full_canonical_sha256": packet_arguments["expected_preparation_sha256"],
        "corpus_preparation_full_canonical_sha256": packet_arguments["expected_corpus_preparation_sha256"],
        "assessment_file_sha256": packet_arguments["expected_assessment_file_sha256"],
        "complete_packet_arguments_sha256": argument_pin,
        "expected_binary_sha256": document["expected_binary_sha256"],
        "original_manifest_file_sha256": _sha(packet["project/corpus-manifest.json"]),
        "original_source_file_sha256": original_manifest["file_sha256"],
        "original_preparation_state": document["original_preparation_state"],
        "original_explanatory_theorem_assumptions": document["original_explanatory_theorem_assumptions"],
        "review_intake_binding": document["review_intake_binding"],
        "review_dependency_manifest": document["review_dependency_manifest"],
        "reference_contract": document["reference_contract"],
        "native_families": document["native_families"], "shared_interpretation": document["shared_interpretation"],
        "expected_modules": modules, "module_imports": module_imports,
        "file_sha256": {path: _sha(body.encode("utf-8")) for path, body in sorted(files.items())},
        "probe_module": PROJECT_ROOT, "probe_source_sha256": _sha(probe_source.encode("utf-8")),
        "checker_template_sha256": _sha(LEAN_CHECKER.encode("utf-8")),
        "probe_bindings": bindings, "original_theorems": original_theorems,
        "probe_theorems": probe_theorems, "theorems": [*original_theorems, *probe_theorems],
        "observation_schema": OBSERVATION_SCHEMA, "observation_prefix": OBSERVATION_PREFIX,
        "expected_type_observations": 15,
        "expected_theorem_axiom_dependencies": {name: [] for name in [*original_theorems, *probe_theorems]},
        "source_custody": {
            "complete_current_typed_lineage_replayed": True,
            "original_source_review_state_unchanged": True,
            "original_project_sources_unchanged_except_lake_root_registration": True,
            "exact_original_namespace_and_header_binders_retained": True,
            "probe_name_is_only_header_edit": True,
            "all_original_theorem_arguments_supplied_explicitly": True,
            "retained_compiled_artifacts_used_as_build_inputs": False,
            "filesystem_acquisition_performed": False,
        },
        "trust_boundary": [
            "The qualified retained packet and theorem-lineage owners replay complete current source/review inputs; independent expected pins retain their external provenance premise.",
            "Only the declaration name changes in each copied header, inside its exact original namespace; the original theorem is applied to every ordered explicit carrier, parameter and proposition hypothesis.",
            "The Lean checker requires theorem ConstantInfo, closed complete types, exact universe inventories, Expr.equal including binder annotations/names, Kernel.isDefEq and kernel checks of the proposition types and both theorem constants.",
            "Structured Expr/Level JSON records are engineering observations from the pinned Lean implementation; no Python parser or serializer establishes a kernel proof.",
            "The installed standard and dynamic libraries are a trusted external toolchain-installation premise. Only Lean/Lake binaries and project sources/artifacts are pinned; the installed library artifact closure is not verified.",
            "Preparation runs no compiler, constructs no backend request/result/proof receipt or FormalizationArtifact, and grants no source, legal, review, cache or training authority.",
        ],
        "producer_pins": producers, "preparation_only": True,
        "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        **FALSE_FLAGS,
    })
    reader._bound_tree(packet_arguments, reader.MAX_INPUT_BYTES, allow_bytes=True)
    _need(index._tree_digest(packet_arguments) == argument_pin
          and reader.packet_sha256(packet_files) == packet_arguments["expected_bundle_sha256"]
          and reader._wire(reader._corpus_document(corpus_preparation), 20 * reader.MAX_RECORD_BYTES) == original_corpus
          and lineage_owner.lineage_sha256(lineage) == original_lineage_pin
          and lineage_owner._wire(lineage_owner._claim_snapshot(lineage.claims)) == original_claims
          and all(_sha(Path(path).read_bytes()) == pin for path, pin in producers.items())
          and _sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "complete elaboration preparation inputs or producers changed during assembly")
    result = ElaborationPreparation(_wire(manifest).decode("utf-8"), tuple(sorted(files.items())))
    preparation_sha256(result)
    return result


def validate_definition_use_preservation_elaboration_v2(
        preparation, lineage, packet_files, corpus_preparation, assessment_raw, *,
        expected_elaboration_preparation_sha256, expected_lineage_sha256,
        expected_packet_observation_sha256, **packet_arguments):
    """Regenerate all seventeen files and full current typed/source bindings."""
    _need(type(preparation) is ElaborationPreparation
          and preparation.to_dict().get("schema") == SCHEMA,
          "exact elaboration preparation schema/profile required")
    _pin(expected_elaboration_preparation_sha256, "complete current elaboration preparation")
    envelope = _envelope(preparation)
    original = _wire(envelope)
    _need(_sha(original) == expected_elaboration_preparation_sha256,
          "independent complete elaboration preparation pin differs")
    regenerated = prepare_definition_use_preservation_elaboration_v2(
        lineage, packet_files, corpus_preparation, assessment_raw,
        expected_lineage_sha256=expected_lineage_sha256,
        expected_packet_observation_sha256=expected_packet_observation_sha256, **packet_arguments)
    _need(_wire(_envelope(preparation)) == original == _wire(_envelope(regenerated)),
          "complete current elaboration preparation differs from regeneration")
    return regenerated


__all__ = ["ElaborationPreparation", "preparation_sha256", "elaboration_preparation_sha256",
           "prepare_definition_use_preservation_elaboration_v2",
           "validate_definition_use_preservation_elaboration_v2",
           "prepare_planned_physical_whole_norm_type_probe_v2"]


def prepare_planned_physical_whole_norm_type_probe_v2(
        request, original_files, *, expected_request_sha256):
    """Prepare one source-only type probe over an independently pinned physical request.

    The request pin must come from the original verified planning or execution
    boundary. This assembler neither dispatches Lean nor authenticates custody.
    """
    from . import corpus_contracts as contracts
    from . import legal_corpus_definition_use_native_v2 as native
    from . import legal_corpus_definition_use_preservation_kernel_requests_v2 as planner

    _pin(expected_request_sha256, "exact planned physical request")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "elaboration preparation owner changed")
    binding = native._physical_whole_norm_request_wire(request, expected_request_sha256)
    row = native._parse(binding[1], native.MAX_RECORD_BYTES)
    payload = row["payload"]
    _need(payload["schema"] == planner.PHYSICAL_WHOLE_PROJECT_REQUEST_SCHEMA
          and payload["premise_remains_quantified"] is True
          and all(payload[key] is False for key in (
              "elaborated_type_verified", "dispatch_qualified", "execution_profile_qualified"))
          and payload["authority"] == AUTHORITY and all(value is False for value in payload["authority"].values()),
          "exact planned whole-project source proposition required")
    context = payload["context"]
    project = payload["project"]
    theorem = row["declaration_id"]
    namespace, separator, short = theorem.rpartition(".")
    identifier = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*\Z")
    source_path = namespace.replace(".", "/") + ".lean"
    _need(bool(separator) and identifier.fullmatch(theorem) is not None
          and theorem == context["theorem"] and namespace == context["source_namespace"]
          and source_path == context["source_path"]
          and _sha(native._wire(context, native.MAX_RECORD_BYTES)) == payload["context_sha256"]
          and context["theorem_binding"]["kind"] == "whole_norm_definition_expansion"
          and context["theorem_binding"]["premise_kind"] == "independently_denoted_source_definition"
          and context["theorem_binding"]["desired_equivalence_hypothesis"] is False,
          "exact namespaced conditional whole-norm theorem required")

    modules = project["expected_modules"]
    _need(type(modules) is list and 1 <= len(modules) <= native.MAX_REVIEWED_PRESERVATION_MODULES
          and all(type(name) is str and identifier.fullmatch(name) for name in modules)
          and len(set(modules)) == len(modules) and namespace in modules
          and PHYSICAL_PROBE_MODULE not in modules and set(project["module_imports"]) == set(modules)
          and project["target"] == "legal", "exact original source-only Lake module roster required")
    _need(type(original_files) is tuple and 1 <= len(original_files) <= native.MAX_REVIEWED_PRESERVATION_FILES,
          "bounded immutable original source files required")
    pins = []
    files = {}
    budget = MAX_RECORD_BYTES
    for item in original_files:
        _need(type(item) is tuple and len(item) == 2 and all(type(v) is str for v in item),
              "exact immutable original path and source text required")
        path, source = item
        _need(0 < len(path) <= 256 and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", path)
              and all(part not in {"", ".", "..", ".lake"} for part in path.split("/"))
              and (path.endswith((".lean", ".toml", ".txt", ".json")) or path == "lean-toolchain")
              and path not in files, "unique safe original source-only path required")
        _need(len(source) <= budget and "\x00" not in source, "bounded original UTF-8 source text required")
        raw = source.encode("utf-8")
        budget -= len(raw)
        _need(budget >= 0, "complete original source byte bound exceeded")
        files[path] = source
        pins.append({"path": path, "bytes": len(raw), "sha256": _sha(raw)})
    _need(pins == project["files"] and list(files) == sorted(files)
          and set(modules) == {path[:-5].replace("/", ".") for path in files if path.endswith(".lean")}
          and files.get("lean-toolchain") == project["toolchain"] + "\n",
          "exact independently pinned original UTF-8 project required")

    proposition = payload["proposition_source"]
    _need(type(proposition) is str and bool(proposition)
          and _sha(proposition.encode("utf-8")) == context["proposition_utf8_sha256"]
          and files[source_path].count("\nnamespace " + namespace + "\n") == 1
          and files[source_path].count("\nexample : " + proposition + " := @" + short + "\n") == 1,
          "independent proposition must match the original namespace ABI exactly")
    checker = _physical_type_checker()
    alias_short = "physical_whole_norm_type_" + expected_request_sha256
    _need(not any(alias_short in body for body in files.values()), "physical probe alias would shadow original source")
    alias = namespace + "." + alias_short
    roots = "roots = " + json.dumps(modules, separators=(",", ":")) + "\n"
    next_modules = [*modules, PHYSICAL_PROBE_MODULE]
    next_roots = "roots = " + json.dumps(next_modules, separators=(",", ":")) + "\n"
    lake = files.get("lakefile.toml", "")
    _need(lake.count(roots) == 1 and lake.count("roots = ") == 1, "exact original Lake roots required")
    files["lakefile.toml"] = lake.replace(roots, next_roots, 1)
    prefix = (
        "import Lean\nimport " + namespace + "\n\n" + checker + "\n"
        "namespace " + namespace + "\n"
        "theorem " + alias_short + " : " + proposition + " := @_root_." + theorem + "\n"
    )
    axiom_line = prefix.count("\n") + 1
    prefix += "#print axioms " + alias_short + "\nend " + namespace + "\n\n"
    type_line = prefix.count("\n") + 1
    probe = prefix + "run_elab CorpusPreservationElaboration.check `" + theorem + " `" + alias + "\n"
    probe_path = PHYSICAL_PROBE_MODULE + ".lean"
    files[probe_path] = probe
    manifest = contracts.seal_record({
        "schema": PHYSICAL_PROBE_SCHEMA, "profile": PHYSICAL_PROBE_PROFILE,
        "request_sha256": expected_request_sha256, "request_context_sha256": payload["context_sha256"],
        "claim_digest": row["claim_digest"], "obligation_digest": row["obligation_digest"],
        "source_path": source_path, "original_theorem": theorem, "alias_theorem": alias,
        "proposition_utf8_sha256": context["proposition_utf8_sha256"], "probe_module": PHYSICAL_PROBE_MODULE,
        "probe_source_sha256": _sha(probe.encode("utf-8")), "checker_template_sha256": _sha(checker.encode("utf-8")),
        "alias_axiom_report_line": axiom_line, "type_report_line": type_line,
        "expected_modules": next_modules, "original_file_pins": pins, "toolchain": project["toolchain"],
        "file_sha256": {path: _sha(body.encode("utf-8")) for path, body in files.items()},
        "preparation_only": True, "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        **FALSE_FLAGS,
    })
    preparation = ElaborationPreparation(_wire(manifest).decode("utf-8"), tuple(sorted(files.items())))
    preparation_sha256(preparation)
    _need(request.digest == expected_request_sha256 and _sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "planned request or elaboration owner changed during preparation")
    return preparation


def _physical_type_checker():
    # The independent ABI spells the premise as an anonymous arrow. Record
    # exact Expr equality, and let Lean decide kernel definitional equality.
    result = LEAN_CHECKER
    for before, after in (
        ('  unless Expr.equal original.type alias.type do\n    throwError "corpus type mismatch: exact original and alias expressions differ"',
         "  let exactExpr := Expr.equal original.type alias.type"),
        ('("schema", toJson "legal-corpus-v2-native-theorem-type-check/v1")',
         '("schema", toJson "' + PHYSICAL_TYPE_OBSERVATION_SCHEMA + '")'),
        ('("expr_equal", toJson true)', '("expr_equal", toJson exactExpr)'),
    ):
        _need(result.count(before) == 1, "closed exact physical type checker derivation required")
        result = result.replace(before, after, 1)
    return result
