"""Opaque theorem-header lineage for replayed corpus-preservation packets.

This module declares engineering candidates. Exact retained source ranges,
declared import closures, and typed claim identities do not elaborate a Lean
type, authenticate historical execution, issue a theorem receipt, or establish
source meaning. Native issuance requires a separately qualified backend.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from types import ModuleType

SCHEMA = "legal-corpus-v2-preservation-theorem-lineage/v1"
PROFILE = "retained-corpus-preservation-opaque-theorem-lineage/v1"
DOMAIN = "engineering_corpus_preservation"
STATEMENT_KIND = "lean_declaration_header"
MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_THEOREMS = 15
_PACKET_ARGUMENTS = frozenset({
    "expected_preparation_sha256", "expected_corpus_preparation_sha256",
    "expected_assessment_file_sha256", "expected_receipt_file_sha256",
    "expected_bundle_sha256", "review_inputs", "toolchain", "expected_binary_sha256",
})
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_EXTRA_FALSE_FLAGS = dict.fromkeys((
    "elaborated_type_verified", "executable_kernel_target_prepared",
    "formalization_artifact_created", "backend_request_prepared",
    "typed_native_attempt_observed", "typed_theorem_result_observed",
    "theorem_receipt_issued", "compiled_artifact_execution_reused",
    "elaborated_term_dependencies_verified", "source_prose_correspondence_proved",
), False)

# Closed public inventory includes all retained-reader refusals plus this adapter's
# additional non-authorizing boundaries. The reader is still checked independently.
FALSE_FLAGS = dict.fromkeys((
    'source_authenticity_verified',
    'publisher_authenticity_verified',
    'legal_currentness_verified',
    'source_semantics_verified',
    'applicability_verified',
    'context_closure_verified',
    'independently_reviewed',
    'human_identity_verified',
    'human_independence_verified',
    'meaning_admitted',
    'admitted',
    'formalized',
    'semantic_graph_admitted',
    'proof_authority',
    'training_qualified',
    'training_gold_qualified',
    'evaluation_gold_qualified',
    'Lean_admitted',
    'model_executed',
    'learned_translation',
    'source_to_model_equivalence_proved',
    'source_fidelity_proved',
    'translation_preservation_proved',
    'cross_family_equivalence_verified',
    'general_emitter_preservation_proved',
    'general_serialized_AST_lowering_preservation_proved',
    'json_bytes_parser_verified',
    'json_bytes_parser_preservation_proved',
    'model_convergence_proved',
    'convergence_proved',
    'backend_executed',
    'lean_compilation_verified',
    'proof_checked',
    'kernel_proofs_checked',
    'corpus_native_AST_preservation_proved',
    'conditional_proofs_verified',
    'alias_assumption_proved',
    'legal_proof_cache_compatible',
    'proof_cache_admission_verified',
    'semantic_definition_binding_verified',
    'per_occurrence_lookup_verified',
    'accepted_view_eligible',
    'combined_use_review_verified',
    'native_execution_performed',
    'fresh_native_execution_performed',
    'proof_validation_performed',
    'olean_kernel_rechecked',
    'installed_compiler_revalidated',
    'cryptographic_authenticity_verified',
    'elaborated_type_verified',
    'executable_kernel_target_prepared',
    'formalization_artifact_created',
    'backend_request_prepared',
    'typed_native_attempt_observed',
    'typed_theorem_result_observed',
    'theorem_receipt_issued',
    'compiled_artifact_execution_reused',
    'elaborated_term_dependencies_verified',
    'source_prose_correspondence_proved',
), False)


def _need(value, message):
    if not value:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value, label):
    _need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
          "independent lowercase SHA256 required: " + label)


def _bound_tree(value, maximum=MAX_RECORD_BYTES):
    remaining, nodes = maximum, 1_000_000

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 96, "lineage input node/depth bound exceeded")
        if type(item) is dict:
            remaining -= 2 + 2 * len(item)
            for key, child in item.items():
                _need(type(key) is str, "ordinary lineage JSON keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            remaining -= 2 + len(item)
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= remaining, "bounded lineage text required")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise ValueError("valid lineage UTF8 required") from error
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded ordinary lineage integer required")
            remaining -= 20
        elif type(item) is float:
            _need(math.isfinite(item), "finite lineage JSON required")
            remaining -= 32
        else:
            raise ValueError("ordinary bounded lineage JSON required")
        _need(remaining >= 0, "complete lineage input byte bound exceeded")

    visit(value, 0)


def _wire(value):
    _bound_tree(value)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    _need(len(raw) <= MAX_RECORD_BYTES, "bounded complete lineage JSON required")
    return raw


def _parse(raw):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_RECORD_BYTES,
          "bounded ordinary lineage JSON bytes required")

    def pairs(items):
        result = {}
        for key, child in items:
            _need(key not in result, "duplicate lineage JSON key")
            result[key] = child
        return result

    def constant(_):
        raise ValueError("nonfinite lineage JSON refused")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        _wire(value)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("duplicate-free finite bounded lineage JSON required") from error
    return value


_CLAIM_FIELDS = {
    "IRClaim": ("claim_id", "statement", "assumptions", "obligations", "domain",
                "declaration_id", "source_refs", "metadata", "schema_version"),
    "Assumption": ("assumption_id", "statement", "source_refs", "metadata", "schema_version"),
    "ProofObligation": ("obligation_id", "statement", "assumption_ids", "logic_family",
                        "source_refs", "metadata", "schema_version"),
}
_CLAIMS_MODULE = "ipfs_datasets_py.logic.ir_core.claims"


def _claim_snapshot(value):
    """Bound slot storage without invoking caller-controlled conversion methods.

    Genuine input already requires its claims owner to be loaded. Resolve exact
    registered classes without importing operation owners or reading nominal
    class labels; a spoofed class can attach arbitrary property descriptors.
    """
    budget, nodes = MAX_RECORD_BYTES, 500_000
    module = sys.modules.get(_CLAIMS_MODULE)
    _need(type(module) is ModuleType, "already loaded genuine typed claim owner required")
    registered = vars(module)
    claim_types = {name: registered.get(name) for name in _CLAIM_FIELDS}
    frozen_type = registered.get("FrozenMap")
    _need(all(isinstance(owner, type) for owner in (*claim_types.values(), frozen_type)),
          "registered genuine typed claim classes required")

    def visit(item, depth):
        nonlocal budget, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 80, "typed lineage claim node/depth bound exceeded")
        kind = type(item)
        if item is None or kind is bool:
            budget -= 5
            result = item
        elif kind is str:
            _need("\x00" not in item and len(item) <= budget, "bounded typed claim text required")
            try:
                budget -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise ValueError("valid typed claim UTF8 required") from error
            result = item
        elif kind is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded typed claim integer required")
            budget -= 20
            result = item
        elif kind is float:
            _need(math.isfinite(item), "finite typed claim numbers required")
            budget -= 32
            result = item
        elif kind is tuple:
            budget -= 2 + len(item)
            result = [visit(child, depth + 1) for child in item]
        elif kind is frozen_type:
            storage = object.__getattribute__(item, "_items")
            _need(type(storage) is tuple and len(storage) <= 4096,
                  "bounded immutable typed claim mapping storage required")
            budget -= 2 + 2 * len(storage)
            result = {}
            previous = None
            for pair in storage:
                _need(type(pair) is tuple and len(pair) == 2 and type(pair[0]) is str
                      and (previous is None or previous < pair[0]),
                      "canonical closed typed claim mapping storage required")
                previous = pair[0]
                result[visit(pair[0], depth + 1)] = visit(pair[1], depth + 1)
        elif any(kind is owner for owner in claim_types.values()):
            budget -= 200
            fields = next(_CLAIM_FIELDS[name] for name, owner in claim_types.items() if kind is owner)
            result = {name: visit(object.__getattribute__(item, name), depth + 1)
                      for name in fields}
        else:
            raise ValueError("closed immutable typed lineage claim storage required")
        _need(budget >= 0, "complete typed lineage claim byte bound exceeded")
        return result

    _need(type(value) is tuple and len(value) == MAX_THEOREMS,
          "exact fifteen immutable typed lineage claims required")
    result = visit(value, 0)
    _bound_tree(result)
    return result


@dataclass(frozen=True, slots=True)
class RetainedCorpusTheoremLineage:
    lineage_json: str
    claims: tuple[object, ...]

    def to_dict(self):
        _need(type(self.lineage_json) is str and 0 < len(self.lineage_json) <= MAX_RECORD_BYTES,
              "bounded lineage text required")
        try:
            raw = self.lineage_json.encode("utf-8")
        except UnicodeError as error:
            raise ValueError("valid lineage UTF8 required") from error
        return _parse(raw)


def lineage_sha256(lineage):
    """Commit exact serialized lineage bytes; this does not validate a candidate."""
    _need(type(lineage) is RetainedCorpusTheoremLineage, "exact lineage storage type required")
    document = RetainedCorpusTheoremLineage.to_dict(lineage)
    claims = _claim_snapshot(lineage.claims)
    _need(type(document) is dict and _wire(document.get("claims")) == _wire(claims),
          "serialized and typed lineage claim storage differ")
    return _sha(lineage.lineage_json.encode("utf-8"))


def _ref(files, path):
    raw = files[path]
    return {"path": path, "bytes": len(raw), "sha256": _sha(raw)}


def _range(path, source, start, end):
    _need(type(start) is int and type(end) is int and 0 <= start < end <= len(source),
          "nonempty exact lineage source byte range required")
    raw = source[start:end]
    return {"path": path, "start_byte": start, "end_byte": end,
            "bytes": len(raw), "sha256": _sha(raw), "raw_utf8": raw.decode("utf-8")}


def _recipes(manifest):
    """Closed current owner recipes; never parse or lower arbitrary Lean."""
    rows = manifest["preservation_fragments"]
    _need([row["role"] for row in rows] == ["donor", "consumer", "alias", "joint"],
          "exact four current preservation roles required")
    by_role = {row["role"]: row for row in rows}
    donor, consumer, alias, joint = [by_role[role]["original_module"]
                                     for role in ("donor", "consumer", "alias", "joint")]
    parameters = [
        {"names": ["Entity", "Agent"], "binder": "{Entity Agent : Type}", "kind": "universal_type_parameters"},
        {"names": ["i"], "binder": "(i : Interpretation Entity Agent)", "kind": "universal_interpretation_parameter"},
        {"names": ["t"], "binder": "(t : Nat)", "kind": "universal_time_parameter"},
    ]
    common = " {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat)"
    specifications = [
        (alias, "consumer_predicate_iff_donor_body", "alias", "conditional",
         "theorem consumer_predicate_iff_donor_body" + common + " (entity : Entity)\n"
         "    (hDonor : " + donor + ".formula_0 i t) (hAlias : formula_0 i t) :\n"
         "    consumerPredicateAt i entity t ↔ " + donor + ".bodyAt i entity t",
         "  exact (hAlias entity).trans (hDonor entity)\n",
         [*parameters, {"names": ["entity"], "binder": "(entity : Entity)", "kind": "universal_entity_parameter"}],
         [("hDonor", donor + ".formula_0 i t", donor + ".formula_0"),
          ("hAlias", "formula_0 i t", alias + ".formula_0")]),
        (joint, "joint_of_components", "joint", "conditional",
         "theorem joint_of_components" + common + "\n"
         "    (hDonor : " + donor + ".formula_0 i t) (hConsumer : " + consumer + ".formula_0 i t)\n"
         "    (hAlias : " + alias + ".formula_0 i t) : formula_0 i t",
         "  exact And.intro hDonor (And.intro hConsumer hAlias)\n", parameters,
         [("hDonor", donor + ".formula_0 i t", donor + ".formula_0"),
          ("hConsumer", consumer + ".formula_0 i t", consumer + ".formula_0"),
          ("hAlias", alias + ".formula_0 i t", alias + ".formula_0")]),
        (joint, "joint_matches_original", "joint", "conditional",
         "theorem joint_matches_original" + common + " :\n    jointAt i t ↔ formula_0 i t",
         "  exact Iff.rfl\n", parameters, []),
    ]
    for row in rows:
        module, role, target = row["preservation_module"], row["role"], row["target_declaration"]
        specifications.extend([
            (module, "native_value_exact", role, "preservation",
             "theorem native_value_exact : toNativeValue typedNativeAst = actualNativeValue",
             "  rfl\n", [], []),
            (module, "native_ast_closed", role, "preservation",
             "theorem native_ast_closed : closed [] typedNativeAst = true",
             "  decide\n", [], []),
            (module, "denotation_matches_native", role, "preservation",
             "theorem denotation_matches_native" + common + " :\n"
             "    denote i typedNativeAst emptyEnvironment t ↔ " + target + " i t",
             "  rfl\n", parameters, []),
        ])
    _need([module + "." + suffix for module, suffix, *_ in specifications] == manifest["theorems"],
          "exact current fifteen theorem recipes and order required")
    return specifications, by_role


def _extract(files, specification):
    module, suffix, role, kind, header, proof, parameters, premises = specification
    path = "project/" + module.replace(".", "/") + ".lean"
    source = files[path]
    marker, axiom = " := by\n", "#print axioms " + suffix + "\n"
    block = (header + marker + proof + axiom).encode("utf-8")
    _need(source.count(block) == 1, "one exact current closed theorem block required: " + module + "." + suffix)
    start = source.index(block)
    _need(start == 0 or source[start - 1:start] == b"\n", "theorem block must start at a complete source line")
    _need(source.count(("theorem " + suffix + " ").encode()) == 1
          and source.count(("#print axioms " + suffix + "\n").encode()) == 1,
          "uniquely anchored theorem declaration and axiom command required")
    namespace = ("namespace " + module + "\n").encode()
    ending = ("end " + module + "\n").encode()
    _need(source.count(namespace) == 1 and source.index(namespace) < start
          and source.count(ending) == 1 and source.endswith(ending),
          "one exact current source namespace must enclose theorem declaration")
    ends = [start]
    for part in (header, marker, proof, axiom):
        ends.append(ends[-1] + len(part.encode("utf-8")))
    ranges = {name: _range(path, source, ends[index], ends[index + 1])
              for index, name in enumerate(("header", "proof_marker", "proof_body", "axiom_command"))}
    ranges["block"] = _range(path, source, start, ends[-1])
    header_raw = header.encode("utf-8")
    parameter_rows = []
    for parameter in parameters:
        raw = parameter["binder"].encode("utf-8")
        _need(header_raw.count(raw) == 1, "one exact current universal binder occurrence required")
        offset = start + header_raw.index(raw)
        parameter_rows.append({**parameter, "range": _range(path, source, offset, offset + len(raw))})
    premise_rows = []
    for name, proposition, target in premises:
        binder = "(" + name + " : " + proposition + ")"
        raw = binder.encode("utf-8")
        _need(header_raw.count(raw) == 1, "one exact current proposition binder occurrence required")
        offset = start + header_raw.index(raw)
        premise_rows.append({"binder_name": name, "binder": binder, "proposition": proposition,
                             "qualified_target": target,
                             "range": _range(path, source, offset, offset + len(raw))})
    _need(re.findall(rb"\(h(?:Donor|Consumer|Alias) :", header_raw)
          == [("(" + row["binder_name"] + " :").encode() for row in premise_rows],
          "complete exact proposition binder population required")
    return module, suffix, role, kind, header, ranges, parameter_rows, premise_rows


def _import_closure(module, manifest, files):
    imports, modules = manifest["module_imports"], manifest["expected_modules"]
    reached, active = set(), set()

    def visit(name):
        _need(name in imports and name in modules and name not in active,
              "closed acyclic declared theorem import closure required")
        if name in reached:
            return
        active.add(name)
        for dependency in imports[name]:
            visit(dependency)
        active.remove(name)
        reached.add(name)

    visit(module)
    closure = []
    for name in modules:
        if name in reached:
            relative = name.replace(".", "/")
            closure.append({"module": name, "direct_imports": imports[name],
                            "source": _ref(files, "project/" + relative + ".lean"),
                            "executed_source": _ref(files, "executed-inputs/" + relative + ".lean"),
                            "compiled_artifact": _ref(files, "compiled/" + relative + ".olean")})
    return closure


def _owner_pins(owners):
    result = {str(Path(__file__).resolve()): _SELF_PIN}
    for owner in owners:
        source = Path(owner.__file__).resolve()
        result[str(source)] = _sha(source.read_bytes())
    return result


def _check_claim_types(claims, owner):
    _need(type(claims) is tuple and len(claims) == MAX_THEOREMS,
          "exact fifteen immutable typed lineage claims required")
    nodes = 500_000

    def frozen(value, depth=0):
        nonlocal nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 80, "genuine typed claim metadata node/depth bound exceeded")
        if type(value) is owner.FrozenMap:
            for key, item in object.__getattribute__(value, "_items"):
                _need(type(key) is str, "ordinary typed claim mapping keys required")
                frozen(item, depth + 1)
        elif type(value) is tuple:
            for item in value:
                frozen(item, depth + 1)
        else:
            _need(value is None or type(value) in (str, int, float, bool),
                  "genuine recursively immutable typed claim metadata required")

    for claim in claims:
        _need(type(claim) is owner.IRClaim and type(claim.metadata) is owner.FrozenMap
              and type(claim.assumptions) is tuple and type(claim.obligations) is tuple
              and len(claim.obligations) == 1,
              "exact current typed claim and obligation owner required")
        frozen(claim.metadata)
        for item in claim.assumptions:
            _need(type(item) is owner.Assumption and type(item.metadata) is owner.FrozenMap,
                  "exact current typed premise owner required")
            frozen(item.metadata)
        for item in claim.obligations:
            _need(type(item) is owner.ProofObligation and type(item.metadata) is owner.FrozenMap,
                  "exact current typed obligation owner required")
            frozen(item.metadata)


def prepare_definition_use_preservation_theorem_lineage_v2(
        packet_files, corpus_preparation, assessment_raw, *,
        expected_packet_observation_sha256, **packet_arguments):
    """Replay trusted packet commitments and declare fifteen opaque candidates.

    The header includes the literal ``theorem`` command/name and every binder.
    Its following separator space belongs to the recorded `` := by\n`` marker.
    No header is promoted into an elaborated proposition or executable target.
    """
    _pin(expected_packet_observation_sha256, "exact current packet observation")
    _need(set(packet_arguments) == _PACKET_ARGUMENTS, "complete closed packet replay arguments required")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "theorem lineage owner changed since import")
    from . import legal_corpus_definition_use_preservation_packet_v2 as reader
    from . import legal_corpus_definition_use_preservation_index_v2 as index
    reader._bound_tree(packet_arguments, reader.MAX_INPUT_BYTES, allow_bytes=True)
    original_arguments = index._tree_digest(packet_arguments)
    original_corpus = _wire(reader._corpus_document(corpus_preparation))
    # Both helper modules are cold stdlib-only. Hash their exact source before
    # source/review owner replay, and recheck it at the final boundary.
    helpers_before = _owner_pins((reader, index))
    retained = reader.validate_definition_use_preservation_packet_v2(
        packet_files, corpus_preparation, assessment_raw, **packet_arguments)
    reader._bound_tree(packet_arguments, reader.MAX_INPUT_BYTES, allow_bytes=True)
    _need(index._tree_digest(packet_arguments) == original_arguments,
          "complete original packet arguments changed across theorem lineage replay")
    observation_raw = retained.observation_json.encode("utf-8")
    _need(_sha(observation_raw) == expected_packet_observation_sha256,
          "independent exact current packet observation pin differs")
    observation = retained.to_dict()
    _need(set(FALSE_FLAGS) == set(reader.FALSE_FLAGS) | set(_EXTRA_FALSE_FLAGS),
          "closed theorem lineage false-flag inventory differs from current reader")
    _need(all(observation[key] is False for key in reader.FALSE_FLAGS)
          and observation["authority"] == reader.AUTHORITY
          and all(value is False for value in observation["authority"].values())
          and type(observation["training_mask"]) is int and observation["training_mask"] == 0
          and type(observation["evaluation_gold_mask"]) is int and observation["evaluation_gold_mask"] == 0,
          "packet readback cannot grant theorem/source/review authority")
    files = dict(retained.files)
    manifest = reader._parse(files["project/corpus-manifest.json"])
    original_fragments = reader._parse(files["project/preservation-inputs.json"],
                                       reader.MAX_PROJECT_BYTES)["original_native_fragments"]
    from . import corpus_contracts as contracts
    from ..ir_core import claims as claim_owner
    extra_pins = _owner_pins((reader, index, contracts, claim_owner))
    _need(all(extra_pins[path] == pin for path, pin in helpers_before.items()),
          "theorem lineage helper changed during replay")
    producers = {**observation["current_producer_pins"], **extra_pins}
    specifications, by_role = _recipes(manifest)
    _need(type(original_fragments) is list and len(original_fragments) == 4,
          "exact four complete original native fragments required")
    native_families = {}
    for role, fragment in zip(("donor", "consumer", "alias", "joint"), original_fragments, strict=True):
        _need(type(fragment) is dict and fragment.get("family") in ("fol", "tdfol")
              and _sha(_wire(fragment)) == by_role[role]["native_fragment_canonical_sha256"],
              "exact original native fragment family and canonical identity required")
        native_families[role] = fragment["family"]
    shared_interpretation = {
        "nominal_type": "LegalCorpusV2.Interpretation",
        "prelude_module": "LegalCorpusV2.Prelude",
        "prelude_source": _ref(files, "project/LegalCorpusV2/Prelude.lean"),
        "prelude_executed_source": _ref(files, "executed-inputs/LegalCorpusV2/Prelude.lean"),
        "prelude_compiled_artifact": _ref(files, "compiled/LegalCorpusV2/Prelude.olean"),
        "semantics_module": manifest["semantics_module"],
        "semantics_source": _ref(files, "project/" + manifest["semantics_module"].replace(".", "/") + ".lean"),
        "semantics_executed_source": _ref(files, "executed-inputs/" + manifest["semantics_module"].replace(".", "/") + ".lean"),
        "semantics_compiled_artifact": _ref(files, "compiled/" + manifest["semantics_module"].replace(".", "/") + ".olean"),
        "semantics_body_sha256": manifest["semantics_sha256"],
        "body_hash_is_complete_module_hash": False,
    }
    context = {
        "profile": PROFILE, "packet_observation_sha256": expected_packet_observation_sha256,
        "packet_bundle_sha256": observation["packet_bundle_sha256"],
        "receipt_file_sha256": observation["receipt_file_sha256"],
        "preparation_full_canonical_sha256": observation["preparation_full_canonical_sha256"],
        "corpus_preparation_full_canonical_sha256": observation["corpus_preparation_full_canonical_sha256"],
        "assessment_file_sha256": observation["assessment_file_sha256"],
        "complete_packet_arguments_sha256": original_arguments,
        "toolchain": observation["toolchain"], "expected_binary_sha256": observation["expected_binary_sha256"],
        "producer_pins": producers, "shared_interpretation": shared_interpretation,
        "original_preparation_state": manifest["original_preparation_state"],
        "original_explanatory_theorem_assumptions": manifest["theorem_assumptions"],
        "review_intake_binding": manifest["review_intake_binding"],
        "review_dependency_manifest": manifest["review_dependency_manifest"],
        "reference_contract": manifest["reference_contract"],
        "native_families": native_families,
    }
    context_sha = _sha(_wire(context))
    entries, claims = [], []
    for specification in specifications:
        module, suffix, role, kind, header, ranges, parameters, premises = _extract(files, specification)
        name = module + "." + suffix
        source_ref = ranges["header"]["path"]
        assumptions = []
        for premise in premises:
            assumption_id = "lean_hypothesis:" + _sha(_wire({"theorem_name": name, **premise}))
            premise["assumption_id"] = assumption_id
            assumptions.append(claim_owner.Assumption(
                assumption_id=assumption_id, statement=premise["proposition"],
                source_refs=(source_ref,), metadata=claim_owner.FrozenMap({
                    "statement_kind": "lean_proposition_parameter", "source_namespace": module,
                    "binder_name": premise["binder_name"], "raw_binder_utf8": premise["binder"],
                    "binder_range": premise["range"], "qualified_target": premise["qualified_target"],
                    "engineering_hypothesis_only": True, "truth_established": False,
                })))
        closure = _import_closure(module, manifest, files)
        core = {
            "theorem_name": name, "theorem_kind": kind, "role": role,
            "source_module": module, "source_namespace": module,
            "statement_kind": STATEMENT_KIND, "logic_family": "lean4", "declaration_header": header,
            "native_family": native_families[role],
            "byte_ranges": ranges, "parameter_binders": parameters, "proposition_premises": premises,
            "declared_import_closure": closure,
            "dependency_scope": "declared_transitive_import_closure_not_elaborated_term_dependencies",
            "target_declaration": by_role[role]["target_declaration"],
            "native_fragment_binding": by_role[role], "shared_interpretation": shared_interpretation,
            "historical_axiom_dependencies": observation["historical_native_receipt"]["native_observations"]["theorem_axiom_dependencies"][name],
            "status": "candidate", "proof_usable": False,
        }
        core_sha = _sha(_wire(core))
        key = _sha(_wire({"lineage_context_sha256": context_sha, "entry_core_sha256": core_sha}))
        claim_id, declaration_id, obligation_id = ("lean_header_claim:" + key, name,
                                                  "lean_header_obligation:" + key)
        metadata = claim_owner.FrozenMap({
            "statement_kind": STATEMENT_KIND, "source_namespace": module,
            "theorem_name": name, "lineage_context_sha256": context_sha, "entry_core_sha256": core_sha,
            "declaration_header_sha256": ranges["header"]["sha256"],
            "theorem_block_sha256": ranges["block"]["sha256"],
            "declared_import_closure_sha256": _sha(_wire(closure)),
            "opaque_source_identity_only": True, "elaborated_type_verified": False,
            "executable_kernel_target_prepared": False, "proof_authority": False,
        })
        obligation = claim_owner.ProofObligation(
            obligation_id=obligation_id, statement=header,
            assumption_ids=tuple(item.assumption_id for item in assumptions), logic_family="lean4",
            source_refs=(source_ref,), metadata=metadata)
        claim = claim_owner.IRClaim(
            claim_id=claim_id, statement=header, assumptions=tuple(assumptions), obligations=(obligation,),
            domain=DOMAIN, declaration_id=declaration_id, source_refs=(source_ref,), metadata=metadata)
        entries.append({**core, "entry_core_sha256": core_sha,
                        "claim_id": claim_id, "declaration_id": declaration_id, "claim_digest": claim.digest,
                        "obligation_id": obligation_id, "obligation_digest": obligation.digest,
                        "assumption_ids": list(obligation.assumption_ids)})
        claims.append(claim)
    _need(len(entries) == len(claims) == MAX_THEOREMS
          and sum(len(claim.assumptions) for claim in claims) == 5
          and all(entry["historical_axiom_dependencies"] == [] for entry in entries),
          "exact fifteen candidates and five explicit proposition premises required")
    record = contracts.seal_record({
        "schema": SCHEMA, **context, "lineage_context_sha256": context_sha,
        "entries": entries, "claims": [claim.to_dict() for claim in claims],
        "theorem_count": MAX_THEOREMS, "proposition_premise_count": 5,
        "original_conditional_theorems": manifest["conditional_theorems"],
        "preservation_theorems": manifest["preservation_theorems"],
        "lineage_prepared": True, "current_packet_replayed": True,
        "source_custody": {
            "complete_current_packet_replayed": True, "original_review_state_unchanged": True,
            "exact_declaration_byte_ranges_retained": True,
            "declared_transitive_import_closure_retained": True,
            "hypothesis_binders_are_established_facts": False,
            "filesystem_acquisition_performed": False,
        },
        "future_native_handoff": {
            "status": "not_prepared",
            "required_bindings": [
                "qualified elaboration of the exact namespace-bound declaration header into a kernel proposition",
                "claim/declaration/obligation identities and exact assumption_ids",
                "request_digest, attempt_digest, result_digest and output_digest",
                "successful genuine typed bounded native attempt, backend identity/version and resource bounds/usage",
                "independently pinned compiler/environment and complete source/compiled import identities",
                "affirmative genuine ProofResult under request-scoped THEOREM_PROOF authority",
                "ProofReceipt.issue exact bindings; source/legal admission remains separate",
            ],
            "historical_receipt_can_issue_typed_proof_receipt": False,
        },
        "trust_boundary": [
            "Independent packet and observation pins retain their external provenance premises; hashing does not authenticate historical execution.",
            "IRClaim and ProofObligation statements are opaque exact Lean declaration headers including theorem command/name and binders, not elaborated types or executable kernel targets.",
            "Explicit proposition parameters remain hypotheses; empty historical axiom inventories do not prove the donor, consumer or alias facts.",
            "Import closure is the conservative declared transitive module closure, not Lean elaborated-term dependencies.",
            "Complete Prelude/semantics module source commitments are distinct from native-fragment Prelude/semantics body-template hashes.",
            "No FormalizationArtifact, BackendRequest, BackendAttempt, ProofResult or ProofReceipt is constructed; no installed compiler or olean is revalidated or executed.",
            "Original source/review eligibility, legal/cache authority and training/gold masks remain unchanged.",
        ],
        "proof_usable": False, "authority": dict(reader.AUTHORITY),
        "training_mask": 0, "evaluation_gold_mask": 0,
        **reader.FALSE_FLAGS, **_EXTRA_FALSE_FLAGS,
    })
    reader._bound_tree(packet_arguments, reader.MAX_INPUT_BYTES, allow_bytes=True)
    _need(index._tree_digest(packet_arguments) == original_arguments
          and reader.packet_sha256(packet_files) == observation["packet_bundle_sha256"]
          and _wire(reader._corpus_document(corpus_preparation)) == original_corpus
          and _owner_pins((reader, index, contracts, claim_owner)) == extra_pins
          and all(_sha(Path(path).read_bytes()) == pin for path, pin in producers.items())
          and _sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "theorem lineage inputs or producers changed during assembly")
    result = RetainedCorpusTheoremLineage(_wire(record).decode("utf-8"), tuple(claims))
    _check_claim_types(result.claims, claim_owner)
    lineage_sha256(result)
    return result


def validate_definition_use_preservation_theorem_lineage_v2(
        lineage, packet_files, corpus_preparation, assessment_raw, *,
        expected_lineage_sha256, expected_packet_observation_sha256, **packet_arguments):
    """Require exact regenerated bytes and genuine typed candidate objects.

    The independent commitment is checked before source/review owner imports.
    A matching self-seal, caller-constructed dataclass, or addressable receipt
    never substitutes for complete public packet/preparation replay.
    """
    _pin(expected_lineage_sha256, "exact opaque theorem lineage")
    _need(type(lineage) is RetainedCorpusTheoremLineage, "exact lineage storage type required")
    document = RetainedCorpusTheoremLineage.to_dict(lineage)
    snapshot = _claim_snapshot(lineage.claims)
    snapshot_raw = _wire(snapshot)
    _need(type(document) is dict and document.get("schema") == SCHEMA
          and document.get("profile") == PROFILE and _wire(document.get("claims")) == snapshot_raw,
          "serialized and typed candidate lineage storage differ")
    _need(all(document.get(name) is False for name in FALSE_FLAGS)
          and document.get("proof_usable") is False
          and type(document.get("authority")) is dict
          and set(document["authority"]) == {"source", "legal", "review", "proof", "model", "training", "gold", "corpus_admission"}
          and all(value is False for value in document["authority"].values())
          and type(document.get("training_mask")) is int and document["training_mask"] == 0
          and type(document.get("evaluation_gold_mask")) is int and document["evaluation_gold_mask"] == 0
          and type(document.get("entries")) is list and len(document["entries"]) == MAX_THEOREMS
          and type(document.get("theorem_count")) is int and document["theorem_count"] == MAX_THEOREMS
          and type(document.get("proposition_premise_count")) is int and document["proposition_premise_count"] == 5,
          "closed non-authorizing candidate lineage storage required")
    original_raw = lineage.lineage_json.encode("utf-8")
    _need(_sha(original_raw) == expected_lineage_sha256,
          "independent exact opaque theorem lineage pin differs")
    regenerated = prepare_definition_use_preservation_theorem_lineage_v2(
        packet_files, corpus_preparation, assessment_raw,
        expected_packet_observation_sha256=expected_packet_observation_sha256, **packet_arguments)
    from ..ir_core import claims as claim_owner
    _check_claim_types(lineage.claims, claim_owner)
    _need(lineage.lineage_json == regenerated.lineage_json
          and _wire(_claim_snapshot(lineage.claims)) == snapshot_raw
          and snapshot_raw == _wire(_claim_snapshot(regenerated.claims))
          and _sha(lineage.lineage_json.encode("utf-8")) == expected_lineage_sha256,
          "complete current theorem lineage or typed identities differ from regeneration")
    return regenerated


__all__ = ["RetainedCorpusTheoremLineage", "lineage_sha256",
           "prepare_definition_use_preservation_theorem_lineage_v2",
           "validate_definition_use_preservation_theorem_lineage_v2"]
