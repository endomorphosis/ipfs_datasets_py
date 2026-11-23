"""Prepare per-instance interpretation checks for complete native AST values.

Public import is standard-library only. The existing native-family owner keeps
the parser, native AST and emitted expression. This additional, narrow profile
reifies the actual complete JSON value independently and prepares kernel
obligations connecting it to an explicit unary FOL denotation. Preparation
executes no compiler and grants no source, legal, model or corpus authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

SCHEMA = "legal-native-ast-preservation-preparation/v1"
PROFILE = "native-unary-boolean-fol-json-value-preservation/v1"
RELATIONAL_PROFILE = "typed-relational-deontic-native-preservation/v1"
REVIEWED_SOURCE_USE_BINDING_SCHEMA = "legal-native-reviewed-source-use-binding/v1"
REVIEWED_SOURCE_USE_IDENTITY_PROFILE = "reviewed-source-use/v1"
RELATIONAL_SOURCE_USE_PROFILE = RELATIONAL_PROFILE + "+reviewed-source-use/v1"
RELATIONAL_PROJECT_ROOT = "LegalRelationalAstPreservation"
RELATIONAL_INPUT_SCHEMA = "legal-relational-ast-preservation-inputs/v1"
INPUT_SCHEMA = "legal-native-ast-preservation-inputs/v1"
PROJECT_ROOT = "LegalNativeAstPreservation"
MAX_RECORD_BYTES = 1024 * 1024
MAX_FRAGMENT_BYTES = MAX_RECORD_BYTES
MAX_PROJECT_BYTES = 8 * MAX_RECORD_BYTES
MAX_PREPARATION_BYTES = 20 * MAX_RECORD_BYTES
MAX_FILES = 7
MAX_MODULES = 4
MAX_THEOREMS = 3
MAX_AST_NODES = 4096
MAX_AST_DEPTH = 32
_TOOLCHAIN = re.compile(r"leanprover/lean4:v[0-9]+\.[0-9]+\.[0-9]+\Z")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_FRAGMENT_FIELDS = {
    "schema", "family", "formula", "formula_sha256", "native_ast",
    "native_ast_sha256", "printed", "parse_receipt", "printed_parse_receipt",
    "exact_native_ast_roundtrip", "lean_body", "lowering_details",
    "producer_pins", "source_bound", "source_semantics_verified",
    "cross_family_equivalence_verified", "backend_executed",
    "all_logic_families_supported", "admitted",
}
FALSE_FLAGS = dict.fromkeys(
    (
        "source_authenticity_verified", "publisher_authenticity_verified",
        "legal_currentness_verified", "source_semantics_verified",
        "source_to_model_equivalence_proved", "applicability_verified",
        "context_closure_verified", "independently_reviewed", "meaning_admitted",
        "admitted", "formalized", "semantic_graph_admitted", "proof_authority",
        "proof_checked", "kernel_proofs_checked", "translation_preservation_proved",
        "cross_family_equivalence_verified", "training_qualified",
        "training_gold_qualified", "evaluation_gold_qualified", "Lean_admitted",
        "model_executed", "learned_translation", "model_convergence_proved",
        "backend_executed", "lean_compilation_verified", "build_eligible",
        "installed_toolchain_verified", "toolchain_probed",
        "native_build_profile_registered", "native_ast_value_fidelity_verified",
        "native_ast_closed_verified", "native_ast_denotation_preserved",
    ), False,
)
AUTHORITY = dict.fromkeys(
    ("source", "legal", "review", "proof", "model", "training", "gold", "corpus_admission"),
    False,
)
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_OPERATION_PINS = None
_RELATIONAL_OPERATION_PINS = None


def _need(value, message):
    if not value:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value, label):
    _need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
          "independent lowercase SHA256 required: " + label)


def _wire(value, maximum, *, max_json_depth=96, max_json_items=100_000):
    """Bound ordinary finite JSON without importing operation owners."""
    _need(type(max_json_depth) is int and 0 < max_json_depth <= 256
          and type(max_json_items) is int and 0 < max_json_items <= 100_000,
          "finite existing preservation JSON capacities required")
    remaining, nodes = maximum, max_json_items

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= max_json_depth, "preservation JSON node/depth bound exceeded")
        if type(item) is dict:
            remaining -= 2 + 2 * len(item)
            for key, child in item.items():
                _need(type(key) is str, "ordinary preservation JSON keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            remaining -= 2 + len(item)
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= remaining,
                  "bounded preservation UTF8 text required")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise ValueError("valid preservation UTF8 text required") from error
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded preservation integer required")
            remaining -= 20
        elif type(item) is float:
            _need(math.isfinite(item), "finite preservation JSON required")
            remaining -= 32
        else:
            raise ValueError("ordinary preservation JSON values required")
        _need(remaining >= 0, "complete preservation JSON byte bound exceeded")

    visit(value, 0)
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError) as error:
        raise ValueError("bounded ordinary preservation JSON required") from error
    _need(len(raw) <= maximum, "complete preservation JSON byte bound exceeded")
    return raw


def _parse(raw, maximum, *, max_json_depth=96, max_json_items=100_000):
    _need(type(raw) is bytes and 0 < len(raw) <= maximum,
          "bounded original preservation JSON bytes required")

    def pairs(items):
        result = {}
        for name, value in items:
            _need(name not in result, "duplicate preservation JSON key")
            result[name] = value
        return result

    def constant(_):
        raise ValueError("nonfinite preservation JSON constant refused")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("invalid bounded preservation JSON bytes") from error
    _wire(value, maximum, max_json_depth=max_json_depth, max_json_items=max_json_items)
    return value


def _keys(value, keys, label):
    _need(type(value) is dict and set(value) == set(keys),
          "exact closed " + label + " fields required")


def _name(value):
    _need(type(value) is str and _NAME.fullmatch(value) is not None,
          "bounded native identifier required")
    return value


def _variable(value):
    _keys(value, {"node_type", "name", "sort"}, "native variable")
    _need(value["node_type"] == "Variable" and value["sort"] is None,
          "only exact null-sort native Variable supported")
    return _name(value["name"])


def _enum(value, name, allowed):
    _keys(value, {"enum", "value"}, "native enum")
    _need(value["enum"] == name and type(value["value"]) is str
          and value["value"] in allowed, "unsupported exact native enum/operator")
    return value["value"]


def _typed_ast(value):
    """Validate the closed profile and render typed syntax, never Lean meaning."""
    count = 0
    symbols = set()

    def visit(node, environment, depth):
        nonlocal count
        count += 1
        _need(count <= MAX_AST_NODES and depth <= MAX_AST_DEPTH,
              "bounded unary native AST required")
        _need(type(node) is dict, "exact native formula object required")
        kind = node.get("node_type")
        if kind == "Predicate":
            _keys(node, {"node_type", "name", "arguments"}, "unary native Predicate")
            name = _name(node["name"])
            _need(type(node["arguments"]) is list and len(node["arguments"]) == 1,
                  "exactly unary native Predicate required")
            variable = _variable(node["arguments"][0])
            count += 1
            _need(count <= MAX_AST_NODES, "bounded unary native AST required")
            _need(variable in environment, "free native variable refused")
            symbols.add(name)
            return "(.predicate " + _string(name) + " " + _string(variable) + ")"
        if kind == "UnaryFormula":
            _keys(node, {"node_type", "operator", "formula"}, "native unary formula")
            _enum(node["operator"], "LogicOperator", {"¬"})
            return "(.negation " + visit(node["formula"], environment, depth + 1) + ")"
        if kind == "BinaryFormula":
            _keys(node, {"node_type", "operator", "left", "right"}, "native binary formula")
            operator = _enum(node["operator"], "LogicOperator", {"∧", "∨", "→", "↔"})
            constructor = {"∧": "conjunction", "∨": "disjunction",
                           "→": "implication", "↔": "equivalence"}[operator]
            left = visit(node["left"], environment, depth + 1)
            right = visit(node["right"], environment, depth + 1)
            return "(." + constructor + " " + left + " " + right + ")"
        if kind == "QuantifiedFormula":
            _keys(node, {"node_type", "quantifier", "variable", "formula"},
                  "native quantified formula")
            _enum(node["quantifier"], "Quantifier", {"∀"})
            variable = _variable(node["variable"])
            count += 1
            _need(count <= MAX_AST_NODES, "bounded unary native AST required")
            return "(.universal " + _string(variable) + " " + visit(
                node["formula"], (variable, *environment), depth + 1) + ")"
        raise ValueError("unsupported unary Boolean/FOL native constructor: " + str(kind))

    result = visit(value, (), 0)
    return result, count, sorted(symbols)


def _string(value):
    # The supported native names are ASCII identifiers. Keys/tags/operators
    # below are fixed; JSON escaping agrees with Lean for this restricted set.
    return json.dumps(value, ensure_ascii=False)


def _native_value(value):
    """Independently reify every original JSON field without typed-AST dispatch."""
    if value is None:
        return ".null"
    if type(value) is str:
        return "(.string " + _string(value) + ")"
    if type(value) is list:
        return "(.array [" + ", ".join(_native_value(item) for item in value) + "])"
    if type(value) is dict:
        return "(.object [" + ", ".join(
            "(" + _string(key) + ", " + _native_value(value[key]) + ")"
            for key in sorted(value)) + "])"
    raise ValueError("unsupported value in exact native AST JSON reification")


def _preflight(fragment_raw, expected_fragment_file_sha256, toolchain):
    _pin(expected_fragment_file_sha256, "complete original native fragment file")
    _need(type(fragment_raw) is bytes and 0 < len(fragment_raw) <= MAX_FRAGMENT_BYTES,
          "bounded complete original native fragment bytes required")
    _need(_sha(fragment_raw) == expected_fragment_file_sha256,
          "independent original native fragment file pin differs")
    _need(type(toolchain) is str and len(toolchain) <= 128
          and _TOOLCHAIN.fullmatch(toolchain) is not None,
          "exact version-pinned Lean toolchain required")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "native AST preservation owner changed since import")
    value = _parse(fragment_raw, MAX_FRAGMENT_BYTES)
    _keys(value, _FRAGMENT_FIELDS, "original native fragment")
    _need(value["schema"] == "legal-native-family-route/v1"
          and value["family"] in ("fol", "tdfol"),
          "only original fol/tdfol native fragments supported")
    _need(type(value["formula"]) is str and 0 < len(value["formula"].encode()) <= 262144
          and type(value["lean_body"]) is str,
          "exact original native formula and Lean body required")
    typed, count, symbols = _typed_ast(value["native_ast"])
    _pin(value["native_ast_sha256"], "original native AST")
    _need(_sha(_wire(value["native_ast"], MAX_RECORD_BYTES)) == value["native_ast_sha256"],
          "original complete native AST pin differs")
    _pin(value["formula_sha256"], "original native formula")
    _need(_sha(value["formula"].encode()) == value["formula_sha256"],
          "original native formula pin differs")
    return value, typed, count, symbols


def _owners():
    from . import corpus_contracts, legal_family_routes
    from ..formalization.autoencoder import native_family_lean_emitters

    return legal_family_routes, native_family_lean_emitters, corpus_contracts


def _pins(owners):
    global _OPERATION_PINS
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "native AST preservation owner changed since import")
    pins = owners[0].producer_pins()
    pins.update({str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
                 for module in owners})
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(pins)
    _need(pins == _OPERATION_PINS,
          "native AST preservation operation owners changed since first use")
    return pins


SEMANTICS = '''set_option autoImplicit false

inductive NativeValue where
  | null
  | string (value : String)
  | array (values : List NativeValue)
  | object (fields : List (String × NativeValue))

inductive UnaryFOL where
  | predicate (name variableName : String)
  | negation (body : UnaryFOL)
  | conjunction (left right : UnaryFOL)
  | disjunction (left right : UnaryFOL)
  | implication (left right : UnaryFOL)
  | equivalence (left right : UnaryFOL)
  | universal (variableName : String) (body : UnaryFOL)

def enumValue (name value : String) : NativeValue :=
  .object [("enum", .string name), ("value", .string value)]

def variableValue (name : String) : NativeValue :=
  .object [("name", .string name), ("node_type", .string "Variable"), ("sort", .null)]

def binaryValue (operator : String) (left right : NativeValue) : NativeValue :=
  .object [("left", left), ("node_type", .string "BinaryFormula"),
    ("operator", enumValue "LogicOperator" operator), ("right", right)]

def toNativeValue : UnaryFOL → NativeValue
  | .predicate name variableName =>
      .object [("arguments", .array [variableValue variableName]), ("name", .string name),
        ("node_type", .string "Predicate")]
  | .negation body => .object [("formula", toNativeValue body),
      ("node_type", .string "UnaryFormula"), ("operator", enumValue "LogicOperator" "¬")]
  | .conjunction left right => binaryValue "∧" (toNativeValue left) (toNativeValue right)
  | .disjunction left right => binaryValue "∨" (toNativeValue left) (toNativeValue right)
  | .implication left right => binaryValue "→" (toNativeValue left) (toNativeValue right)
  | .equivalence left right => binaryValue "↔" (toNativeValue left) (toNativeValue right)
  | .universal variableName body => .object [("formula", toNativeValue body),
      ("node_type", .string "QuantifiedFormula"), ("quantifier", enumValue "Quantifier" "∀"),
      ("variable", variableValue variableName)]

def closed (bound : List String) : UnaryFOL → Bool
  | .predicate _ variableName => bound.contains variableName
  | .negation body => closed bound body
  | .conjunction left right => closed bound left && closed bound right
  | .disjunction left right => closed bound left && closed bound right
  | .implication left right => closed bound left && closed bound right
  | .equivalence left right => closed bound left && closed bound right
  | .universal variableName body => closed (variableName :: bound) body

def emptyEnvironment {Entity : Type} : String → Option Entity := fun _ => none

def updateEnvironment {Entity : Type} (environment : String → Option Entity)
    (name : String) (entity : Entity) : String → Option Entity :=
  fun queried => if queried = name then some entity else environment queried

def denote {Entity Agent : Type} (i : Interpretation Entity Agent) :
    UnaryFOL → (String → Option Entity) → Nat → Prop
  | .predicate name variableName, environment, t =>
      match environment variableName with
      | none => False
      | some entity => i.atom name [entity] t
  | .negation body, environment, t => ¬ denote i body environment t
  | .conjunction left right, environment, t =>
      denote i left environment t ∧ denote i right environment t
  | .disjunction left right, environment, t =>
      denote i left environment t ∨ denote i right environment t
  | .implication left right, environment, t =>
      denote i left environment t → denote i right environment t
  | .equivalence left right, environment, t =>
      denote i left environment t ↔ denote i right environment t
  | .universal variableName body, environment, t =>
      ∀ entity : Entity, denote i body (updateEnvironment environment variableName entity) t
'''


@dataclass(frozen=True)
class NativeAstPreservationPreparation:
    manifest_json: str
    files: tuple[tuple[str, str], ...]

    def to_dict(self):
        _need(type(self.manifest_json) is str, "original preservation manifest text required")
        value = _parse(self.manifest_json.encode("utf-8"), MAX_RECORD_BYTES)
        _need(type(value) is dict, "preservation manifest object required")
        return value


def preparation_sha256(preparation):
    """Full canonical manifest-and-files pin, distinct from the manifest pin."""
    _need(type(preparation) is NativeAstPreservationPreparation,
          "exact typed native AST preservation preparation required")
    manifest = preparation.to_dict()
    _need(type(preparation.files) is tuple and len(preparation.files) == MAX_FILES,
          "exact seven-file preservation project required")
    names, files, total = [], [], 0
    for item in preparation.files:
        _need(type(item) is tuple and len(item) == 2,
              "exact generated preservation path/text pairs required")
        name, body = item
        _need(type(name) is str and type(body) is str,
              "ordinary generated preservation path/text required")
        _need(len(name) <= 256
              and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?", name) is not None
              and all(part not in (".", "..") for part in name.split("/")),
              "closed two-level preservation project paths required")
        try:
            total += len(body.encode("utf-8"))
        except UnicodeError as error:
            raise ValueError("valid generated preservation UTF8 required") from error
        _need(total <= MAX_PROJECT_BYTES, "complete preservation project byte bound exceeded")
        names.append(name)
        files.append([name, body])
    _need(names == sorted(set(names)), "exact distinct sorted preservation files required")
    return _sha(_wire({"manifest": manifest, "files": files}, MAX_PREPARATION_BYTES))


def _file(module, imports, body):
    return ("".join("import " + item + "\n" for item in imports)
            + "namespace " + module + "\n" + body
            + "\nend " + module + "\n")


def prepare_native_ast_preservation(fragment_raw: bytes, *,
        expected_fragment_file_sha256, toolchain):
    """Replay the whole original fragment and prepare three kernel obligations."""
    fragment, typed, count, symbols = _preflight(
        fragment_raw, expected_fragment_file_sha256, toolchain)
    owners = _owners()
    routes, emitter, contracts = owners
    producers = _pins(owners)
    original = routes.prepare_native_fragment(
        family=fragment["family"], formula=fragment["formula"],
        expected_ast=fragment["native_ast"])
    _need(_wire(original, MAX_FRAGMENT_BYTES) == _wire(fragment, MAX_FRAGMENT_BYTES),
          "entire original native fragment differs from authoritative regeneration")
    actual = _native_value(fragment["native_ast"])
    canonical_fragment = _wire(fragment, MAX_FRAGMENT_BYTES)
    instance = PROJECT_ROOT + ".Instance" + _sha(_wire({
        "profile": PROFILE, "original_fragment_file_sha256": expected_fragment_file_sha256,
        "semantics_sha256": _sha(SEMANTICS.encode()),
    }, MAX_RECORD_BYTES))
    modules = [PROJECT_ROOT + ".Prelude", PROJECT_ROOT + ".Semantics", instance, PROJECT_ROOT]
    imports = {modules[0]: [], modules[1]: [modules[0]],
               instance: [modules[1]], PROJECT_ROOT: [instance]}
    theorems = [instance + "." + name for name in (
        "native_value_exact", "native_ast_closed", "denotation_matches_native")]
    body = (fragment["lean_body"]
            + "\n\ndef actualNativeValue : NativeValue := " + actual
            + "\ndef typedNativeAst : UnaryFOL := " + typed
            + "\ntheorem native_value_exact : toNativeValue typedNativeAst = actualNativeValue := by\n  rfl\n"
            + "#print axioms native_value_exact\n"
            + "theorem native_ast_closed : closed [] typedNativeAst = true := by\n  decide\n"
            + "#print axioms native_ast_closed\n"
            + "theorem denotation_matches_native {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat) :\n"
            + "    denote i typedNativeAst emptyEnvironment t ↔ formula_0 i t := by\n  rfl\n"
            + "#print axioms denotation_matches_native\n")
    inputs = {
        "schema": INPUT_SCHEMA, "profile": PROFILE,
        "original_fragment_file_sha256": expected_fragment_file_sha256,
        "original_fragment_file_bytes": len(fragment_raw),
        "original_fragment_canonical_sha256": _sha(canonical_fragment),
        "original_fragment_raw_utf8": fragment_raw.decode("utf-8"),
        "original_fragment": fragment,
    }
    files = {
        "lakefile.toml": 'name = "legal_native_ast_preservation"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = ["LegalNativeAstPreservation"]\n',
        "lean-toolchain": toolchain + "\n",
        "preservation-inputs.json": _wire(inputs, 4 * MAX_RECORD_BYTES).decode() + "\n",
        modules[0].replace(".", "/") + ".lean": _file(PROJECT_ROOT, [], emitter.PRELUDE),
        modules[1].replace(".", "/") + ".lean": _file(PROJECT_ROOT, imports[modules[1]], SEMANTICS),
        instance.replace(".", "/") + ".lean": _file(instance, imports[instance], body),
        PROJECT_ROOT + ".lean": "import " + instance + "\n",
    }
    _need(len(files) == MAX_FILES and len(set(modules)) == MAX_MODULES
          and sum(len(text.encode()) for text in files.values()) <= MAX_PROJECT_BYTES,
          "complete seven-file/four-module preservation project exceeds bounds")
    for module in modules:
        _need(re.findall(r"(?m)^import ([A-Za-z][A-Za-z0-9_.]*)$",
                         files[module.replace(".", "/") + ".lean"]) == imports[module],
              "exact closed preservation module imports required")
    manifest = contracts.seal_record({
        "schema": SCHEMA, "profile": PROFILE, "toolchain": toolchain, "target": "legal",
        "family": fragment["family"],
        "original_fragment_file_sha256": expected_fragment_file_sha256,
        "original_fragment_file_bytes": len(fragment_raw),
        "original_fragment_canonical_sha256": _sha(canonical_fragment),
        "native_ast_sha256": _sha(_wire(fragment["native_ast"], MAX_RECORD_BYTES)),
        "lean_body_sha256": _sha(fragment["lean_body"].encode()),
        "actual_native_lean_value_sha256": _sha(actual.encode()),
        "typed_native_lean_value_sha256": _sha(typed.encode()),
        "semantics_sha256": _sha(SEMANTICS.encode()),
        "prelude_sha256": _sha(emitter.PRELUDE.encode()),
        "native_ast_node_count": count, "native_predicates": symbols,
        "expected_modules": modules, "module_imports": imports,
        "file_sha256": {name: _sha(text.encode()) for name, text in sorted(files.items())},
        "theorems": theorems,
        "theorem_assumptions": [
            "Entity and Agent are arbitrary Type carriers; Entity need not be inhabited.",
            "Predicate meaning is supplied by the unchanged Interpretation.atom parameter at Nat time.",
            "The three generated obligations have not been executed or kernel checked during preparation.",
        ],
        "support_profile": {
            "families": ["fol", "tdfol"], "sort": "null_only",
            "terms": ["unary_Predicate_argument_Variable"],
            "formula_nodes": ["Predicate", "UnaryFormula", "BinaryFormula", "QuantifiedFormula"],
            "operators": ["¬", "∧", "∨", "→", "↔"], "quantifiers": ["∀"],
            "closed_only": True, "named_lexical_shadowing": True,
            "ordered_children_preserved": True, "duplicate_subformulas_preserved": True,
            "max_ast_nodes": MAX_AST_NODES, "max_ast_depth": MAX_AST_DEPTH,
        },
        "source_custody": {
            "scope": "exact original native fragment bytes and complete native-record replay only",
            "original_fragment_raw_retained_in": "preservation-inputs.json/original_fragment_raw_utf8",
            "original_source_bundle_replayed": False,
            "source_prose_to_ast_proved": False,
        },
        "trust_boundary": [
            "Python UTF8 JSON decoding, full-value reification and SHA256 commitments remain explicit custody assumptions.",
            "NativeValue is a total JSON-value mirror for null/string/array/object; it is not a JSON byte parser.",
            "Each instance compares the complete actual AST value and independent denotation against the unchanged native emitted expression.",
            "No generic emitter-correctness, prose-translation, source authenticity, legal meaning, family equivalence or model-convergence theorem is claimed.",
        ],
        "producer_pins": producers, "native_producer_pins": fragment["producer_pins"],
        "preparation_only": True, "authority": dict(AUTHORITY),
        "training_mask": 0, "evaluation_gold_mask": 0,
        **FALSE_FLAGS,
    })
    _need(_pins(owners) == producers, "native AST preservation producers changed during preparation")
    preparation = NativeAstPreservationPreparation(
        _wire(manifest, MAX_RECORD_BYTES).decode(), tuple(sorted(files.items())))
    preparation_sha256(preparation)
    return preparation


def validate_native_ast_preservation(preparation, fragment_raw: bytes, *,
        expected_preparation_sha256, expected_fragment_file_sha256, toolchain):
    """Verify an independent whole-project pin and replay every original input."""
    _pin(expected_preparation_sha256, "complete native AST preservation preparation")
    _need(preparation_sha256(preparation) == expected_preparation_sha256,
          "independent complete preservation preparation pin differs")
    expected = prepare_native_ast_preservation(
        fragment_raw, expected_fragment_file_sha256=expected_fragment_file_sha256,
        toolchain=toolchain)
    _need(expected == preparation,
          "preservation preparation differs from complete original native regeneration")
    return expected


# These are proof-witness syntax types, not an alternative production IR or
# emitter. The original relational owner still validates and lowers the request.
# This interpretation is deliberately separate from its emitted Lean expression.
RELATIONAL_SEMANTICS = SEMANTICS + '''

inductive RelationalFOL where
  | predicate (name : String) (variables : List String)
  | negation (body : RelationalFOL)
  | conjunction (left right : RelationalFOL)
  | disjunction (left right : RelationalFOL)
  | implication (left right : RelationalFOL)
  | equivalence (left right : RelationalFOL)
  | universal (variableName : String) (body : RelationalFOL)
  | existential (variableName : String) (body : RelationalFOL)
  | modal (operator : String) (body : RelationalFOL)

def relToNativeValue : RelationalFOL → NativeValue
  | .predicate name variables => .object [
      ("arguments", .array (variables.map variableValue)),
      ("name", .string name), ("node_type", .string "Predicate")]
  | .negation body => .object [("formula", relToNativeValue body),
      ("node_type", .string "UnaryFormula"), ("operator", enumValue "LogicOperator" "¬")]
  | .conjunction left right => binaryValue "∧" (relToNativeValue left) (relToNativeValue right)
  | .disjunction left right => binaryValue "∨" (relToNativeValue left) (relToNativeValue right)
  | .implication left right => binaryValue "→" (relToNativeValue left) (relToNativeValue right)
  | .equivalence left right => binaryValue "↔" (relToNativeValue left) (relToNativeValue right)
  | .universal variableName body => .object [("formula", relToNativeValue body),
      ("node_type", .string "QuantifiedFormula"), ("quantifier", enumValue "Quantifier" "∀"),
      ("variable", variableValue variableName)]
  | .existential variableName body => .object [("formula", relToNativeValue body),
      ("node_type", .string "QuantifiedFormula"), ("quantifier", enumValue "Quantifier" "∃"),
      ("variable", variableValue variableName)]
  | .modal operator body => .object [("agent", .null), ("context", .null),
      ("formula", relToNativeValue body), ("node_type", .string "DeonticFormula"),
      ("operator", enumValue "DeonticOperator" operator)]

def relClosed (bound : List String) : RelationalFOL → Bool
  | .predicate _ variables => variables.all bound.contains
  | .negation body => relClosed bound body
  | .conjunction left right => relClosed bound left && relClosed bound right
  | .disjunction left right => relClosed bound left && relClosed bound right
  | .implication left right => relClosed bound left && relClosed bound right
  | .equivalence left right => relClosed bound left && relClosed bound right
  | .universal name body => relClosed (name :: bound) body
  | .existential name body => relClosed (name :: bound) body
  | .modal _ body => relClosed bound body

def resolveArguments {Entity : Type} (environment : String → Option Entity) :
    List String → Option (List Entity)
  | [] => some []
  | variableName :: rest => do
      let value ← environment variableName
      let values ← resolveArguments environment rest
      pure (value :: values)

-- The preservation profile accepts exactly O/P/F. Literal keys avoid the
-- UTF8 proof dependencies of String.append; unsupported tags get no key.
def relationalNativeModalKey (operator : String) : Option String :=
  if operator = "O" then some "deontic:O" else
  if operator = "P" then some "deontic:P" else
  if operator = "F" then some "deontic:F" else none

def relDenote {Entity Agent : Type} (i : Interpretation Entity Agent) :
    RelationalFOL → (String → Option Entity) → Nat → Prop
  | .predicate name variables, environment, t =>
      match resolveArguments environment variables with
      | none => False
      | some values => i.atom name values t
  | .negation body, environment, t => ¬ relDenote i body environment t
  | .conjunction left right, environment, t =>
      relDenote i left environment t ∧ relDenote i right environment t
  | .disjunction left right, environment, t =>
      relDenote i left environment t ∨ relDenote i right environment t
  | .implication left right, environment, t =>
      relDenote i left environment t → relDenote i right environment t
  | .equivalence left right, environment, t =>
      relDenote i left environment t ↔ relDenote i right environment t
  | .universal name body, environment, t =>
      ∀ entity : Entity, relDenote i body (updateEnvironment environment name entity) t
  | .existential name body, environment, t =>
      ∃ entity : Entity, relDenote i body (updateEnvironment environment name entity) t
  | .modal operator body, environment, t =>
      match relationalNativeModalKey operator with
      | none => False
      | some key => i.modal key [] none (fun u => relDenote i body environment u) t

inductive RoleFormula where
  | predicate (name : String) (roles variables : List String)
  | negation (body : RoleFormula)
  | conjunction (left right : RoleFormula)
  | disjunction (left right : RoleFormula)
  | implication (left right : RoleFormula)
  | equivalence (left right : RoleFormula)
  | universal (variableName : String) (body : RoleFormula)
  | existential (variableName : String) (body : RoleFormula)
  | modal (operator : String) (body : RoleFormula)

def eraseRoles : RoleFormula → RelationalFOL
  | .predicate name _ variables => .predicate name variables
  | .negation body => .negation (eraseRoles body)
  | .conjunction left right => .conjunction (eraseRoles left) (eraseRoles right)
  | .disjunction left right => .disjunction (eraseRoles left) (eraseRoles right)
  | .implication left right => .implication (eraseRoles left) (eraseRoles right)
  | .equivalence left right => .equivalence (eraseRoles left) (eraseRoles right)
  | .universal name body => .universal name (eraseRoles body)
  | .existential name body => .existential name (eraseRoles body)
  | .modal operator body => .modal operator (eraseRoles body)

def roleInterpretation {Entity Agent : Type} (base : Interpretation Entity Agent)
    (atoms : String → List (String × Entity) → Nat → Prop)
    (roles : String → List String) : Interpretation Entity Agent :=
  { base with atom := fun name values t => atoms name ((roles name).zip values) t }

def roleDenote {Entity Agent : Type} (base : Interpretation Entity Agent)
    (atoms : String → List (String × Entity) → Nat → Prop) :
    RoleFormula → (String → Option Entity) → Nat → Prop
  | .predicate name roles variables, environment, t =>
      match resolveArguments environment variables with
      | none => False
      | some values => atoms name (roles.zip values) t
  | .negation body, environment, t => ¬ roleDenote base atoms body environment t
  | .conjunction left right, environment, t =>
      roleDenote base atoms left environment t ∧ roleDenote base atoms right environment t
  | .disjunction left right, environment, t =>
      roleDenote base atoms left environment t ∨ roleDenote base atoms right environment t
  | .implication left right, environment, t =>
      roleDenote base atoms left environment t → roleDenote base atoms right environment t
  | .equivalence left right, environment, t =>
      roleDenote base atoms left environment t ↔ roleDenote base atoms right environment t
  | .universal name body, environment, t =>
      ∀ entity : Entity, roleDenote base atoms body (updateEnvironment environment name entity) t
  | .existential name body, environment, t =>
      ∃ entity : Entity, roleDenote base atoms body (updateEnvironment environment name entity) t
  | .modal operator body, environment, t =>
      match relationalNativeModalKey operator with
      | none => False
      | some key => base.modal key [] none (fun u => roleDenote base atoms body environment u) t
'''


def _lean_list(values):
    return "[" + ", ".join(_string(value) for value in values) + "]"


def _relational_native_syntax(value):
    """Reify the complete supported native value, independently of the emitter."""
    count, predicates = 0, {}

    def visit(node, environment, depth):
        nonlocal count
        count += 1
        _need(count <= MAX_AST_NODES and depth <= MAX_AST_DEPTH,
              "bounded relational native AST required")
        _need(type(node) is dict, "ordinary relational native AST required")
        kind = node.get("node_type")
        if kind == "Predicate":
            _keys(node, {"node_type", "name", "arguments"}, "relational native predicate")
            name = _name(node["name"])
            arguments = node["arguments"]
            _need(type(arguments) is list and 1 <= len(arguments) <= 8,
                  "bounded ordered native variable arguments required")
            variables = [_variable(argument) for argument in arguments]
            count += len(variables)
            _need(count <= MAX_AST_NODES and all(v in environment for v in variables),
                  "free or unbounded relational native variables refused")
            _need(name not in predicates or predicates[name] == len(variables),
                  "inconsistent relational predicate arity")
            predicates[name] = len(variables)
            return "(.predicate " + _string(name) + " " + _lean_list(variables) + ")"
        if kind == "UnaryFormula":
            _keys(node, {"node_type", "operator", "formula"}, "relational native negation")
            _enum(node["operator"], "LogicOperator", {"¬"})
            return "(.negation " + visit(node["formula"], environment, depth + 1) + ")"
        if kind == "BinaryFormula":
            _keys(node, {"node_type", "operator", "left", "right"}, "relational native binary")
            op = _enum(node["operator"], "LogicOperator", {"∧", "∨", "→", "↔"})
            name = {"∧": "conjunction", "∨": "disjunction", "→": "implication", "↔": "equivalence"}[op]
            return "(." + name + " " + visit(node["left"], environment, depth + 1) + " " + visit(
                node["right"], environment, depth + 1) + ")"
        if kind == "QuantifiedFormula":
            _keys(node, {"node_type", "quantifier", "variable", "formula"}, "relational native quantifier")
            op = _enum(node["quantifier"], "Quantifier", {"∀", "∃"})
            name = _variable(node["variable"])
            _need(name not in environment, "relational binder shadowing refused")
            count += 1
            _need(count <= MAX_AST_NODES, "bounded relational native AST required")
            return "(." + ("universal" if op == "∀" else "existential") + " " + _string(name) + " " + visit(
                node["formula"], (name, *environment), depth + 1) + ")"
        if kind == "DeonticFormula":
            _keys(node, {"node_type", "operator", "formula", "agent", "context"}, "relational native modality")
            op = _enum(node["operator"], "DeonticOperator", {"O", "P", "F"})
            _need(node["agent"] is None and node["context"] is None,
                  "annotated native modality requires another preservation profile")
            return "(.modal " + _string(op) + " " + visit(node["formula"], environment, depth + 1) + ")"
        raise ValueError("unsupported relational native preservation constructor: " + str(kind))

    typed = visit(value, (), 0)
    return typed, count, sorted(predicates)


def _relational_source_syntax(root, roles):
    """Independent witness from the validated TypedExpression, before lowering."""
    def visit(node):
        kind = node["kind"]
        if kind == "predicate":
            name = node["symbol"]
            return "(.predicate " + _string(name) + " " + _lean_list(roles[name]) + " " + _lean_list(
                [child["symbol"] for child in node["arguments"]]) + ")"
        if kind in {"and", "or", "implies", "iff"}:
            name = {"and": "conjunction", "or": "disjunction", "implies": "implication", "iff": "equivalence"}[kind]
            return "(." + name + " " + visit(node["arguments"][0]) + " " + visit(node["arguments"][1]) + ")"
        if kind == "not":
            return "(.negation " + visit(node["arguments"][0]) + ")"
        if kind in {"forall", "exists"}:
            return "(." + ("universal" if kind == "forall" else "existential") + " " + _string(
                node["binders"][0]["name"]) + " " + visit(node["arguments"][0]) + ")"
        if kind == "extension":
            ext = node["extension"]
            return "(.modal " + _string(ext["payload"]["letter"]) + " " + visit(ext["children"][0]) + ")"
        raise ValueError("unsupported relational typed-source preservation constructor: " + str(kind))
    return visit(root)


def _relational_pins(owners, relational, report):
    global _RELATIONAL_OPERATION_PINS
    pins = dict(_pins(owners))
    pins.update(report["producer_pins"])
    path = Path(relational.__file__).resolve()
    pins[str(path)] = _sha(path.read_bytes())
    if _RELATIONAL_OPERATION_PINS is None:
        _RELATIONAL_OPERATION_PINS = dict(pins)
    _need(pins == _RELATIONAL_OPERATION_PINS,
          "relational preservation operation owners changed since first use")
    return pins


def _reviewed_source_use_identity(source_use_binding, expected_source_use_binding_sha256, *, contracts=None):
    """Detach a declared identity; current reviewed-source replay belongs upstream."""
    if source_use_binding is None and expected_source_use_binding_sha256 is None:
        return None, {}
    _need(source_use_binding is not None and expected_source_use_binding_sha256 is not None,
          "source-use binding and independent SHA256 must be supplied together")
    _need((REVIEWED_SOURCE_USE_BINDING_SCHEMA, REVIEWED_SOURCE_USE_IDENTITY_PROFILE,
            RELATIONAL_SOURCE_USE_PROFILE, MIXED_SOURCE_USE_PROFILE) == (
            "legal-native-reviewed-source-use-binding/v1", "reviewed-source-use/v1",
            "typed-relational-deontic-native-preservation/v1+reviewed-source-use/v1",
            "typed-many-sorted-relational-deontic-renderer-preservation/v1+reviewed-source-use/v1"),
          "fixed explicit reviewed source-use child identity domain required")
    fields = {"schema", "unit_id", "source_version_cid", "source_occurrence_cid", "complete_ir_sha256",
        "graph_unit_record_cid", "graph_ast_record_cid", "scope_record_cid", "interpretation_record_cid"}
    _keys(source_use_binding, fields, "reviewed source-use binding")
    _need(all(type(value) is str and 0 < len(value.encode("utf-8")) <= 512
              for value in source_use_binding.values()), "bounded ordinary source-use binding strings required")
    _need(source_use_binding["schema"] == REVIEWED_SOURCE_USE_BINDING_SCHEMA,
          "explicit reviewed source-use binding schema required")
    _pin(expected_source_use_binding_sha256, "complete reviewed source-use binding")
    _pin(source_use_binding["complete_ir_sha256"], "complete reviewed unit IR")
    raw = _wire(source_use_binding, MAX_RECORD_BYTES)
    _need(_sha(raw) == expected_source_use_binding_sha256, "independent reviewed source-use binding pin differs")
    detached = _parse(raw, MAX_RECORD_BYTES)
    if contracts is not None:
        for field in ("source_version_cid", "source_occurrence_cid", "graph_unit_record_cid",
                "graph_ast_record_cid", "scope_record_cid", "interpretation_record_cid"):
            contracts.require_cid(detached[field], "reviewed source-use " + field, codecs=("dag-json",))
    return raw, {"source_use_binding": detached,
        "source_use_binding_sha256": expected_source_use_binding_sha256,
        "instance_identity_profile": REVIEWED_SOURCE_USE_IDENTITY_PROFILE}


def prepare_relational_ast_preservation(report, request_raw: bytes, *,
        expected_report_sha256, expected_request_sha256, toolchain,
        source_use_binding=None, expected_source_use_binding_sha256=None):
    """Prepare source-role/native correspondence; no legal or proof admission.

    The exact existing authored relational request, report, role ledger and
    Object→null-sort mapping are retained. The independent role interpretation
    makes ordered labels part of the predicate inputs rather than a prose claim.
    Only the existing relational owner's closed fragment is supported.
    """
    _pin(expected_report_sha256, "complete relational report")
    _pin(expected_request_sha256, "complete relational request")
    report_raw = _wire(report, 8 * MAX_RECORD_BYTES)
    _need(_sha(report_raw) == expected_report_sha256, "independent relational report pin differs")
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_RECORD_BYTES // 2
          and _sha(request_raw) == expected_request_sha256,
          "independent bounded relational request pin differs")
    request = _parse(request_raw, MAX_RECORD_BYTES // 2)
    _need(type(request) is dict and type(report) is dict,
          "ordinary complete relational report/request required")
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain) is not None,
          "exact version-pinned Lean toolchain required")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "native AST preservation owner changed since import")
    identity_validator = _reviewed_source_use_identity
    identity_validator_code = identity_validator.__code__
    identity_raw, source_identity = identity_validator(source_use_binding, expected_source_use_binding_sha256)
    selected_profile = RELATIONAL_PROFILE if identity_raw is None else RELATIONAL_SOURCE_USE_PROFILE
    fragment = report.get("native_fragment")
    _keys(fragment, _FRAGMENT_FIELDS, "original relational native fragment")
    _need(fragment["schema"] == "legal-native-family-route/v1" and fragment["family"] == "deontic_fol",
          "existing deontic_fol relational fragment required")
    typed, count, symbols = _relational_native_syntax(fragment["native_ast"])
    # No operation import precedes independent input hashes and bounded shape.
    from . import legal_relational_norm_v1 as relational
    checked = relational.validate_relational_norm_v1(report, request_raw,
        expected_report_sha256=expected_report_sha256,
        expected_request_sha256=expected_request_sha256)
    owners = _owners()
    _, emitter, contracts = owners
    def source_identity_fence():
        if identity_raw is None:
            return
        _need(_reviewed_source_use_identity is identity_validator
              and identity_validator.__code__ is identity_validator_code,
              "reviewed source-use identity validator changed during preparation")
        current_raw, current_identity = identity_validator(source_use_binding,
            expected_source_use_binding_sha256, contracts=contracts)
        _need(current_raw == identity_raw and _wire(current_identity, MAX_RECORD_BYTES)
              == _wire(source_identity, MAX_RECORD_BYTES)
              and selected_profile == RELATIONAL_SOURCE_USE_PROFILE,
              "caller or detached reviewed source-use identity changed during preparation")

    source_identity_fence()
    producers = _relational_pins(owners, relational, checked)
    _need(checked["request"] == request, "relational original request replay differs")
    fragment = checked["native_fragment"]
    fragment_raw = _wire(fragment, MAX_FRAGMENT_BYTES)
    actual = _native_value(fragment["native_ast"])
    roles = {row["symbol"]: row["roles"] for row in checked["argument_roles"]}
    source = _relational_source_syntax(checked["typed_expression"]["root"], roles)
    semantics = RELATIONAL_SEMANTICS
    instance = RELATIONAL_PROJECT_ROOT + ".Instance" + _sha(_wire({
        "profile": selected_profile, "report_sha256": expected_report_sha256,
        "request_sha256": expected_request_sha256, "semantics_sha256": _sha(semantics.encode()),
        **source_identity,
    }, MAX_RECORD_BYTES))
    modules = [RELATIONAL_PROJECT_ROOT + ".Prelude", RELATIONAL_PROJECT_ROOT + ".Semantics", instance, RELATIONAL_PROJECT_ROOT]
    imports = {modules[0]: [], modules[1]: [modules[0]], instance: [modules[1]], RELATIONAL_PROJECT_ROOT: [instance]}
    names = ["native_value_exact", "native_ast_closed", "denotation_matches_native",
             "typed_source_lowering_exact", "role_denotation_matches_native"]
    role_lookup = "\n".join("  if name = " + _string(name) + " then " + _lean_list(roles[name]) + " else"
                            for name in sorted(roles)) + "\n  []"
    body = (fragment["lean_body"]
        + "\n\ndef actualNativeValue : NativeValue := " + actual
        + "\ndef typedNativeAst : RelationalFOL := " + typed
        + "\ndef typedSourceAst : RoleFormula := " + source
        + "\ndef predicateRoles (name : String) : List String :=\n" + role_lookup
        + "\ntheorem native_value_exact : relToNativeValue typedNativeAst = actualNativeValue := by\n  rfl\n"
        + "#print axioms native_value_exact\n"
        + "theorem native_ast_closed : relClosed [] typedNativeAst = true := by\n  decide\n"
        + "#print axioms native_ast_closed\n"
        + "theorem denotation_matches_native {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat) :\n"
        + "    relDenote i typedNativeAst emptyEnvironment t ↔ formula_0 i t := by\n  exact Iff.intro (fun h => h) (fun h => h)\n"
        + "#print axioms denotation_matches_native\n"
        + "theorem typed_source_lowering_exact : eraseRoles typedSourceAst = typedNativeAst := by\n  rfl\n"
        + "#print axioms typed_source_lowering_exact\n"
        + "theorem role_denotation_matches_native {Entity Agent : Type} (base : Interpretation Entity Agent)\n"
        + "    (atoms : String → List (String × Entity) → Nat → Prop) (t : Nat) :\n"
        + "    roleDenote base atoms typedSourceAst emptyEnvironment t ↔\n"
        + "      formula_0 (roleInterpretation base atoms predicateRoles) t := by\n  exact Iff.intro (fun h => h) (fun h => h)\n"
        + "#print axioms role_denotation_matches_native\n")
    inputs = {"schema": RELATIONAL_INPUT_SCHEMA, "profile": selected_profile, **source_identity,
        "original_fragment_file_sha256": _sha(fragment_raw), "original_fragment_file_bytes": len(fragment_raw),
        "original_fragment_canonical_sha256": _sha(fragment_raw),
        "original_fragment_raw_utf8": fragment_raw.decode(), "original_fragment": fragment,
        "relational_report": checked, "relational_report_sha256": expected_report_sha256,
        "original_request_raw_utf8": request_raw.decode(), "original_request_sha256": expected_request_sha256}
    files = {
        "lakefile.toml": 'name = "legal_native_ast_preservation"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = ["LegalRelationalAstPreservation"]\n',
        "lean-toolchain": toolchain + "\n",
        "preservation-inputs.json": _wire(inputs, 4 * MAX_RECORD_BYTES).decode() + "\n",
        modules[0].replace(".", "/") + ".lean": _file(RELATIONAL_PROJECT_ROOT, [], emitter.PRELUDE),
        modules[1].replace(".", "/") + ".lean": _file(RELATIONAL_PROJECT_ROOT, imports[modules[1]], semantics),
        instance.replace(".", "/") + ".lean": _file(instance, imports[instance], body),
        RELATIONAL_PROJECT_ROOT + ".lean": "import " + instance + "\n",
    }
    _need(len(files) == MAX_FILES and len(set(modules)) == MAX_MODULES
          and sum(len(text.encode()) for text in files.values()) <= MAX_PROJECT_BYTES,
          "complete relational preservation project exceeds bounds")
    manifest = contracts.seal_record({
        "schema": SCHEMA, "profile": selected_profile, "toolchain": toolchain, "target": "legal", **source_identity,
        "family": fragment["family"], "original_fragment_file_sha256": _sha(fragment_raw),
        "original_fragment_file_bytes": len(fragment_raw), "original_fragment_canonical_sha256": _sha(fragment_raw),
        "relational_report_sha256": expected_report_sha256, "original_request_sha256": expected_request_sha256,
        "typed_expression_sha256": checked["typed_expression_sha256"],
        "argument_roles_sha256": _sha(_wire(checked["argument_roles"], MAX_RECORD_BYTES)),
        "native_ast_sha256": _sha(_wire(fragment["native_ast"], MAX_RECORD_BYTES)),
        "lean_body_sha256": _sha(fragment["lean_body"].encode()),
        "actual_native_lean_value_sha256": _sha(actual.encode()), "typed_native_lean_value_sha256": _sha(typed.encode()),
        "typed_source_lean_value_sha256": _sha(source.encode()), "semantics_sha256": _sha(semantics.encode()),
        "prelude_sha256": _sha(emitter.PRELUDE.encode()), "native_ast_node_count": count, "native_predicates": symbols,
        "expected_modules": modules, "module_imports": imports,
        "file_sha256": {name: _sha(text.encode()) for name, text in sorted(files.items())},
        "theorems": [instance + "." + name for name in names],
        "theorem_assumptions": [
            "Entity and Agent are arbitrary Type carriers; Entity need not be inhabited.",
            "Typed Object variables map explicitly to native null-sort variables over Entity.",
            "Predicate interpretations consume ordered role/value pairs from the exact caller-declared ledger.",
            "O/P/F remain independent modal parameters; no modal axioms, statutory meaning or approvals are supplied.",
            "The five instance obligations have not been executed or kernel checked during preparation."],
        "support_profile": {"families": ["deontic_fol"], "typed_sort": "Object", "native_sort": None,
            "terms": ["bound_Variable"], "predicate_arity": [1, 8], "quantifiers": ["∀", "∃"],
            "operators": ["¬", "∧", "∨", "→", "↔", "O", "P", "F"],
            "closed_only": True, "named_lexical_shadowing": False, "ordered_children_preserved": True,
            "duplicate_subformulas_preserved": True, "ordered_role_labels_preserved": True,
            "modal_agent": None, "modal_context": None, "counting_supported": False,
            "max_ast_nodes": MAX_AST_NODES, "max_ast_depth": MAX_AST_DEPTH},
        "source_custody": {"scope": "whole authored typed request/report and unchanged native fragment replay",
            "original_fragment_raw_retained_in": "preservation-inputs.json/original_fragment_raw_utf8",
            "original_source_bundle_replayed": False, "source_prose_to_ast_proved": False},
        "trust_boundary": [
            "Complete original request/report hashes and current typed/native validators remain custody assumptions.",
            "RoleFormula and RelationalFOL are proof witnesses, not replacement production IRs or emitters.",
            "Each instance compares independently reified typed/source and native syntax with unchanged emitted Lean.",
            "No prose correspondence, reviewed legal role, governing definition, counting, calendar or deadline claim is made."],
        "producer_pins": producers, "native_producer_pins": fragment["producer_pins"],
        "preparation_only": True, "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        **FALSE_FLAGS,
    })
    _need(_relational_pins(owners, relational, checked) == producers,
          "relational preservation producers changed during preparation")
    preparation = NativeAstPreservationPreparation(_wire(manifest, MAX_RECORD_BYTES).decode(), tuple(sorted(files.items())))
    preparation_sha256(preparation)
    source_identity_fence()
    return preparation


def validate_relational_ast_preservation(preparation, report, request_raw: bytes, *,
        expected_preparation_sha256, expected_report_sha256, expected_request_sha256, toolchain,
        source_use_binding=None, expected_source_use_binding_sha256=None):
    """Replay whole typed/native inputs; never accept a merely resealed project."""
    _pin(expected_preparation_sha256, "complete relational preservation preparation")
    _need(preparation_sha256(preparation) == expected_preparation_sha256,
          "independent complete relational preservation pin differs")
    expected = prepare_relational_ast_preservation(report, request_raw,
        expected_report_sha256=expected_report_sha256, expected_request_sha256=expected_request_sha256,
        toolchain=toolchain, source_use_binding=source_use_binding,
        expected_source_use_binding_sha256=expected_source_use_binding_sha256)
    _need(expected == preparation, "relational preservation differs from complete original regeneration")
    return expected



COUNTED_PROFILE = "typed-many-sorted-fixed-three-counted-preservation/v1"
COUNTED_PROJECT_ROOT = "LegalCountedAstPreservation"
COUNTED_INPUT_SCHEMA = "legal-counted-ast-preservation-inputs/v1"
_COUNTED_OPERATION_PINS = None


# The existing NativeValue is reused solely as exact JSON proof-witness syntax.
# CountedVariable/CountedFormula are not production or decoder representations.
_SORTED_PROOF_TYPES = r'''inductive CountedSort where
  | object
  | event
  | time
  deriving BEq, DecidableEq

structure CountedVariable where
  nodeId : String
  name : String
  sort : CountedSort

'''

_SORTED_PROOF_VALUES = r'''def countedSortName : CountedSort → String
  | .object => "Object"
  | .event => "EventFrame"
  | .time => "TimeFrame"

def countedAtomicSortValue (sort : CountedSort) : NativeValue :=
  .object [("arguments", .array []), ("kind", .string "atomic"),
    ("name", .string (countedSortName sort)),
    ("schema_version", .string "syntax-logic-sort/v1")]

def countedBoolSortValue : NativeValue :=
  .object [("arguments", .array []), ("kind", .string "bool"),
    ("name", .string "Bool"), ("schema_version", .string "syntax-logic-sort/v1")]

def countedBinderValue (name : String) (sort : CountedSort) : NativeValue :=
  .object [("name", .string name), ("schema_version", .string "syntax-binder/v1"),
    ("sort", countedAtomicSortValue sort)]

def countedNodeValue (nodeId kind symbol : String) (sort : NativeValue)
    (arguments binders : List NativeValue) : NativeValue :=
  .object [("arguments", .array arguments), ("binders", .array binders),
    ("kind", .string kind), ("metadata", .object []), ("node_id", .string nodeId),
    ("schema_version", .string "syntax-logic-node/v1"),
    ("sort", sort), ("symbol", .string symbol)]

def countedVariableValue (boundVariable : CountedVariable) : NativeValue :=
  countedNodeValue boundVariable.nodeId "variable" boundVariable.name
    (countedAtomicSortValue boundVariable.sort) [] []

'''

_SORTED_PROOF_ENVIRONMENT = r'''structure CountedEnvironment (Object EventFrame TimeFrame : Type) where
  objects : String → Option Object
  events : String → Option EventFrame
  times : String → Option TimeFrame

def emptyCountedEnvironment {Object EventFrame TimeFrame : Type} :
    CountedEnvironment Object EventFrame TimeFrame :=
  ⟨fun _ => none, fun _ => none, fun _ => none⟩

def countedObjectValue {Object EventFrame TimeFrame : Type}
    (environment : CountedEnvironment Object EventFrame TimeFrame)
    (boundVariable : CountedVariable) : Option Object :=
  CountedSort.casesOn boundVariable.sort (environment.objects boundVariable.name) none none

def countedEventValue {Object EventFrame TimeFrame : Type}
    (environment : CountedEnvironment Object EventFrame TimeFrame)
    (boundVariable : CountedVariable) : Option EventFrame :=
  CountedSort.casesOn boundVariable.sort none (environment.events boundVariable.name) none

def countedTimeValue {Object EventFrame TimeFrame : Type}
    (environment : CountedEnvironment Object EventFrame TimeFrame)
    (boundVariable : CountedVariable) : Option TimeFrame :=
  CountedSort.casesOn boundVariable.sort none none (environment.times boundVariable.name)

def updateCountedObject {Object EventFrame TimeFrame : Type}
    (environment : CountedEnvironment Object EventFrame TimeFrame) (name : String)
    (entity : Object) : CountedEnvironment Object EventFrame TimeFrame :=
  { environment with objects := fun queried =>
      if queried = name then .some entity else environment.objects queried }
def updateCountedEvent {Object EventFrame TimeFrame : Type}
    (environment : CountedEnvironment Object EventFrame TimeFrame) (name : String)
    (frame : EventFrame) : CountedEnvironment Object EventFrame TimeFrame :=
  { environment with events := fun queried =>
      if queried = name then .some frame else environment.events queried }
def updateCountedTime {Object EventFrame TimeFrame : Type}
    (environment : CountedEnvironment Object EventFrame TimeFrame) (name : String)
    (instant : TimeFrame) : CountedEnvironment Object EventFrame TimeFrame :=
  { environment with times := fun queried =>
      if queried = name then .some instant else environment.times queried }

'''

COUNTED_SEMANTICS = (SEMANTICS
    + r'''

'''
    + _SORTED_PROOF_TYPES
    + r'''inductive CountedFormula where
  | member (nodeId : String) (object event time : CountedVariable)
  | equality (nodeId : String) (left right : CountedVariable)
  | conjunction (nodeId : String) (left right : CountedFormula)
  | disjunction (nodeId : String) (left right : CountedFormula)
  | implication (nodeId : String) (left right : CountedFormula)
  | universal (nodeId name : String) (sort : CountedSort) (body : CountedFormula)

'''
    + _SORTED_PROOF_VALUES
    + r'''def countedToTypedNodeValue : CountedFormula → NativeValue
  | .member nodeId object event time =>
      countedNodeValue nodeId "predicate" "Member" countedBoolSortValue
        [countedVariableValue object, countedVariableValue event, countedVariableValue time] []
  | .equality nodeId left right =>
      countedNodeValue nodeId "equality" "" countedBoolSortValue
        [countedVariableValue left, countedVariableValue right] []
  | .conjunction nodeId left right =>
      countedNodeValue nodeId "and" "" countedBoolSortValue
        [countedToTypedNodeValue left, countedToTypedNodeValue right] []
  | .disjunction nodeId left right =>
      countedNodeValue nodeId "or" "" countedBoolSortValue
        [countedToTypedNodeValue left, countedToTypedNodeValue right] []
  | .implication nodeId left right =>
      countedNodeValue nodeId "implies" "" countedBoolSortValue
        [countedToTypedNodeValue left, countedToTypedNodeValue right] []
  | .universal nodeId name sort body =>
      countedNodeValue nodeId "forall" "" countedBoolSortValue
        [countedToTypedNodeValue body] [countedBinderValue name sort]

def countedIdentityValue (space value : String) : NativeValue :=
  .object [("interface", .string "LogicIdentityNamespaces@1"),
    ("namespace", .string space), ("schema_version", .string "logic-identity-namespaces/v1"),
    ("value", .string value), ("version", .string "1.0.0")]

def countedSignatureValue (signatureId : String) : NativeValue :=
  .object [("family", countedIdentityValue "family" "first_order"),
    ("features", .array []), ("interface", .string "LogicSignature@1"),
    ("metadata", .object []), ("profile", countedIdentityValue "profile" "many_sorted"),
    ("schema_version", .string "syntax-logic-signature/v1"),
    ("signature_id", .string signatureId),
    ("sorts", .array [countedBoolSortValue, countedAtomicSortValue .object,
      countedAtomicSortValue .event, countedAtomicSortValue .time]),
    ("symbols", .array [.object [
      ("domain", .array [countedAtomicSortValue .object, countedAtomicSortValue .event,
        countedAtomicSortValue .time]),
      ("kind", .string "predicate"), ("metadata", .object []),
      ("name", .string "Member"), ("range", countedBoolSortValue),
      ("schema_version", .string "syntax-symbol-declaration/v1")]])]

def countedTypedExpressionValue (expressionId signatureId contentDigest : String)
    (ast : CountedFormula) : NativeValue :=
  .object [("content_digest", .string contentDigest), ("expression_id", .string expressionId),
    ("family", countedIdentityValue "family" "first_order"),
    ("interface", .string "TypedExpression@1"), ("metadata", .object []),
    ("profile", countedIdentityValue "profile" "many_sorted"),
    ("root", countedToTypedNodeValue ast),
    ("schema_version", .string "syntax-typed-expression/v1"),
    ("signature", countedSignatureValue signatureId)]

def countedVariableClosed (bound : List (CountedSort × String))
    (boundVariable : CountedVariable) : Bool :=
  bound.contains (boundVariable.sort, boundVariable.name)

def countedClosed (bound : List (CountedSort × String)) : CountedFormula → Bool
  | .member _ object event time =>
      (object.sort == .object) && (event.sort == .event) && (time.sort == .time) &&
        countedVariableClosed bound object && countedVariableClosed bound event &&
        countedVariableClosed bound time
  | .equality _ left right =>
      (left.sort == .object) && (right.sort == .object) &&
        countedVariableClosed bound left && countedVariableClosed bound right
  | .conjunction _ left right => countedClosed bound left && countedClosed bound right
  | .disjunction _ left right => countedClosed bound left && countedClosed bound right
  | .implication _ left right => countedClosed bound left && countedClosed bound right
  | .universal _ name sort body => countedClosed ((sort, name) :: bound) body

'''
    + _SORTED_PROOF_ENVIRONMENT
    + r'''def countedDenote {Object EventFrame TimeFrame : Type}
    (member : Object → EventFrame → TimeFrame → Prop) (ast : CountedFormula) :
    CountedEnvironment Object EventFrame TimeFrame → Prop :=
  CountedFormula.rec
    (fun _ object event time environment =>
      Option.casesOn (countedObjectValue environment object) False (fun o =>
        Option.casesOn (countedEventValue environment event) False (fun e =>
          Option.casesOn (countedTimeValue environment time) False (fun t => member o e t))))
    (fun _ left right environment =>
      Option.casesOn (countedObjectValue environment left) False (fun l =>
        Option.casesOn (countedObjectValue environment right) False (fun r => l = r)))
    (fun _ _ _ left right environment => left environment ∧ right environment)
    (fun _ _ _ left right environment => left environment ∨ right environment)
    (fun _ _ _ left right environment => left environment → right environment)
    (fun _ name sort _ child environment =>
      CountedSort.casesOn sort
        (∀ entity : Object, child (updateCountedObject environment name entity))
        (∀ frame : EventFrame, child (updateCountedEvent environment name frame))
        (∀ instant : TimeFrame, child (updateCountedTime environment name instant))) ast

-- Counterfactual proof specifications only: neither is a production counted API.
def counterfactualAtMostTwo {Object EventFrame TimeFrame : Type}
    (member : Object → EventFrame → TimeFrame → Prop) : Prop :=
  ∀ (event : EventFrame) (time : TimeFrame) (x0 x1 x2 : Object),
    ((member x0 event time ∧ member x1 event time) ∧ member x2 event time) →
      ((x0 = x1 ∨ x0 = x2) ∨ x1 = x2)

def counterfactualAtMostFour {Object EventFrame TimeFrame : Type}
    (member : Object → EventFrame → TimeFrame → Prop) : Prop :=
  ∀ (event : EventFrame) (time : TimeFrame) (x0 x1 x2 x3 x4 : Object),
    ((((member x0 event time ∧ member x1 event time) ∧ member x2 event time) ∧
      member x3 event time) ∧ member x4 event time) →
      (((((((((x0 = x1 ∨ x0 = x2) ∨ x0 = x3) ∨ x0 = x4) ∨ x1 = x2) ∨
        x1 = x3) ∨ x1 = x4) ∨ x2 = x3) ∨ x2 = x4) ∨ x3 = x4)
''')


def _counted_string(value):
    """Reuse ordinary Lean literals, with a codepoint route for arbitrary IDs.

    The original typed owner still enforces its ASCII identity grammar.
    This value encoder does not broaden that grammar or approve new IDs;
    JSON control escapes are not assumed to be Lean escapes.
    """
    _need(type(value) is str and len(value) <= 4096, "bounded counted witness string required")
    if all(32 <= ord(character) <= 126 for character in value):
        return _string(value)
    return "(String.ofList [" + ", ".join(
        "(Char.ofNat " + str(ord(character)) + ")" for character in value) + "])"


def _counted_json_value(value):
    """Reify every complete TypedExpression field, independently of dispatch."""
    if value is None:
        return ".null"
    if type(value) is str:
        return "(.string " + _counted_string(value) + ")"
    if type(value) is list:
        return "(.array [" + ", ".join(_counted_json_value(item) for item in value) + "])"
    if type(value) is dict:
        return "(.object [" + ", ".join(
            "(" + _counted_string(key) + ", " + _counted_json_value(value[key]) + ")"
            for key in sorted(value)) + "])"
    raise ValueError("unsupported value in exact counted TypedExpression witness")


def _counted_source_syntax(root):
    """Interpret actual typed constructors; never replace them with cap3 text."""
    count, identifiers = 0, set()
    sorts = {"Object": "object", "EventFrame": "event", "TimeFrame": "time"}

    def sort(value, *, formula=False):
        _keys(value, {"arguments", "kind", "name", "schema_version"}, "counted typed sort")
        name = value["name"]
        _need(value["schema_version"] == "syntax-logic-sort/v1" and value["arguments"] == [],
              "exact atomic counted sort required")
        if formula:
            _need(name == "Bool" and value["kind"] == "bool", "counted formula Bool sort required")
            return "bool"
        _need(type(name) is str and name in sorts and value["kind"] == "atomic",
              "unsupported counted term/binder sort")
        return sorts[name]

    def node(value, depth):
        nonlocal count
        _keys(value, {"arguments", "binders", "kind", "metadata", "node_id", "schema_version",
                      "sort", "symbol"}, "counted typed node")
        _need(type(value["node_id"]) is str and 0 < len(value["node_id"]) <= 512
              and value["node_id"] not in identifiers, "distinct bounded counted node IDs required")
        count += 1
        identifiers.add(value["node_id"])
        _need(count <= 49 and depth <= MAX_AST_DEPTH, "bounded exact counted AST required")
        _need(value["schema_version"] == "syntax-logic-node/v1" and value["metadata"] == {}
              and type(value["symbol"]) is str and type(value["arguments"]) is list
              and type(value["binders"]) is list, "exact unannotated counted node required")

    def variable(value, environment, depth, expected_sort):
        node(value, depth)
        _need(value["kind"] == "variable" and value["arguments"] == [] and value["binders"] == [],
              "only bound counted variables supported")
        found = sort(value["sort"])
        name = value["symbol"]
        _need(found == expected_sort and (found, name) in environment,
              "free, wrongly sorted or reordered counted variable")
        return "⟨" + _counted_string(value["node_id"]) + ", " + _counted_string(name) + ", ." + found + "⟩"

    def formula(value, environment, depth):
        node(value, depth)
        sort(value["sort"], formula=True)
        kind, arguments = value["kind"], value["arguments"]
        prefix = "(." + {"predicate": "member", "equality": "equality", "and": "conjunction",
                          "or": "disjunction", "implies": "implication",
                          "forall": "universal"}.get(kind, "unsupported") + " "
        prefix += _counted_string(value["node_id"]) + " "
        if kind == "predicate":
            _need(value["symbol"] == "Member" and value["binders"] == [] and len(arguments) == 3,
                  "ordered ternary Member required")
            return prefix + " ".join(variable(argument, environment, depth + 1, expected)
                for argument, expected in zip(arguments, ("object", "event", "time"), strict=True)) + ")"
        _need(value["symbol"] == "", "unexpected counted connective/equality symbol")
        if kind == "equality":
            _need(value["binders"] == [] and len(arguments) == 2, "binary built-in object equality required")
            return prefix + " ".join(variable(argument, environment, depth + 1, "object")
                                      for argument in arguments) + ")"
        if kind in {"and", "or", "implies"}:
            _need(value["binders"] == [] and len(arguments) == 2, "binary counted connective required")
            return prefix + formula(arguments[0], environment, depth + 1) + " " + formula(
                arguments[1], environment, depth + 1) + ")"
        if kind == "forall":
            _need(len(value["binders"]) == 1 and len(arguments) == 1, "single counted universal binder required")
            binder = value["binders"][0]
            _keys(binder, {"name", "schema_version", "sort"}, "counted typed binder")
            _need(binder["schema_version"] == "syntax-binder/v1" and type(binder["name"]) is str,
                  "exact counted binder required")
            found = sort(binder["sort"])
            name = binder["name"]
            _need(not any(name == bound_name for _, bound_name in environment),
                  "counted lexical binder shadowing unsupported")
            return prefix + _counted_string(name) + " ." + found + " " + formula(
                arguments[0], ((found, name), *environment), depth + 1) + ")"
        raise ValueError("unsupported counted preservation constructor: " + str(kind))

    result = formula(root, (), 0)
    _need(count == 49, "exact complete 49-node counted witness required")
    return result, count


def _counted_pins(owners, counted, checked):
    """Read only current owner-replayed producer paths, never offered paths."""
    global _COUNTED_OPERATION_PINS
    pins = dict(_pins(owners))
    supplied = checked["producer_pins"]
    _need(type(supplied) is dict and 1 <= len(supplied) <= 32,
          "bounded current counted producer pins required")
    for name, expected in supplied.items():
        _pin(expected, "current counted producer")
        path = Path(name)
        _need(path.is_absolute() and str(path.resolve()) == name
              and _sha(path.read_bytes()) == expected, "current counted producer bytes differ")
        pins[name] = expected
    path = Path(counted.__file__).resolve()
    pins[str(path)] = _sha(path.read_bytes())
    if _COUNTED_OPERATION_PINS is None:
        _COUNTED_OPERATION_PINS = dict(pins)
    _need(pins == _COUNTED_OPERATION_PINS,
          "counted preservation operation owners changed since first use")
    return pins




_COUNTED_BOUNDARY_PROOF_TEMPLATE = r'''def threeObjectMembers (_ : Fin 3) (_ : Unit) (_ : Unit) : Prop := True
def fourObjectMembers (_ : Fin 4) (_ : Unit) (_ : Unit) : Prop := True
@[elab_as_elim] def countedThreeObjectCases.{u} {motive : Fin 3 → Sort u} (h0 : motive (⟨0, (Nat.le.step (Nat.le.step Nat.le.refl))⟩ : Fin 3)) (h1 : motive (⟨1, (Nat.le.step Nat.le.refl)⟩ : Fin 3)) (h2 : motive (⟨2, Nat.le.refl⟩ : Fin 3)) : ∀ x, motive x := by
  intro x
  cases x with
  | mk v0 bound =>
    cases v0 with
    | zero => exact h0
    | succ v1 =>
      cases v1 with
      | zero => exact h1
      | succ v2 =>
        cases v2 with
        | zero => exact h2
        | succ v3 =>
          exact False.elim ((Nat.not_lt_zero v3) (Nat.lt_of_succ_lt_succ (Nat.lt_of_succ_lt_succ (Nat.lt_of_succ_lt_succ bound))))

@[elab_as_elim] def countedFourObjectCases.{u} {motive : Fin 4 → Sort u} (h0 : motive (⟨0, (Nat.le.step (Nat.le.step (Nat.le.step Nat.le.refl)))⟩ : Fin 4)) (h1 : motive (⟨1, (Nat.le.step (Nat.le.step Nat.le.refl))⟩ : Fin 4)) (h2 : motive (⟨2, (Nat.le.step Nat.le.refl)⟩ : Fin 4)) (h3 : motive (⟨3, Nat.le.refl⟩ : Fin 4)) : ∀ x, motive x := by
  intro x
  cases x with
  | mk v0 bound =>
    cases v0 with
    | zero => exact h0
    | succ v1 =>
      cases v1 with
      | zero => exact h1
      | succ v2 =>
        cases v2 with
        | zero => exact h2
        | succ v3 =>
          cases v3 with
          | zero => exact h3
          | succ v4 =>
            exact False.elim ((Nat.not_lt_zero v4) (Nat.lt_of_succ_lt_succ (Nat.lt_of_succ_lt_succ (Nat.lt_of_succ_lt_succ (Nat.lt_of_succ_lt_succ bound)))))


__COUNTED_FINITE_PIGEONHOLE_PROOFS__
theorem countedThreeObjectsViolateCapTwo : ¬ counterfactualAtMostTwo threeObjectMembers :=
  fun bound =>
    let bad := bound () () (⟨0, (Nat.le.step (Nat.le.step Nat.le.refl))⟩ : Fin 3) (⟨1, (Nat.le.step Nat.le.refl)⟩ : Fin 3) (⟨2, Nat.le.refl⟩ : Fin 3) (And.intro (And.intro (True.intro) True.intro) True.intro)
    Or.elim bad (fun leftDisjunction0 => Or.elim leftDisjunction0 (fun leftDisjunction1 => Nat.noConfusion (congrArg Fin.val leftDisjunction1)) (fun unequalPair1 => Nat.noConfusion (congrArg Fin.val unequalPair1))) (fun unequalPair0 => Nat.noConfusion (congrArg Fin.val unequalPair0) (fun innerEq0 => Nat.noConfusion (innerEq0)))

theorem countedFourObjectsViolateCapThree : ¬ countedAtMostThree fourObjectMembers :=
  fun bound =>
    let bad := bound () () (⟨0, (Nat.le.step (Nat.le.step (Nat.le.step Nat.le.refl)))⟩ : Fin 4) (⟨1, (Nat.le.step (Nat.le.step Nat.le.refl))⟩ : Fin 4) (⟨2, (Nat.le.step Nat.le.refl)⟩ : Fin 4) (⟨3, Nat.le.refl⟩ : Fin 4) (And.intro (And.intro (And.intro (True.intro) True.intro) True.intro) True.intro)
    Or.elim bad (fun leftDisjunction0 => Or.elim leftDisjunction0 (fun leftDisjunction1 => Or.elim leftDisjunction1 (fun leftDisjunction2 => Or.elim leftDisjunction2 (fun leftDisjunction3 => Or.elim leftDisjunction3 (fun leftDisjunction4 => Nat.noConfusion (congrArg Fin.val leftDisjunction4)) (fun unequalPair4 => Nat.noConfusion (congrArg Fin.val unequalPair4))) (fun unequalPair3 => Nat.noConfusion (congrArg Fin.val unequalPair3))) (fun unequalPair2 => Nat.noConfusion (congrArg Fin.val unequalPair2) (fun innerEq0 => Nat.noConfusion (innerEq0)))) (fun unequalPair1 => Nat.noConfusion (congrArg Fin.val unequalPair1) (fun innerEq0 => Nat.noConfusion (innerEq0)))) (fun unequalPair0 => Nat.noConfusion (congrArg Fin.val unequalPair0) (fun innerEq0 => Nat.noConfusion (innerEq0) (fun innerEq1 => Nat.noConfusion (innerEq1))))

theorem cap_two_counterexample :
    countedDenote threeObjectMembers typedCountedAst emptyCountedEnvironment ∧
      ¬ counterfactualAtMostTwo threeObjectMembers :=
  And.intro (fun _ _ a b c d _ => countedThreeObjectPigeonhole a b c d) countedThreeObjectsViolateCapTwo
#print axioms cap_two_counterexample
theorem cap_four_counterexample :
    ¬ countedDenote fourObjectMembers typedCountedAst emptyCountedEnvironment ∧
      counterfactualAtMostFour fourObjectMembers :=
  And.intro countedFourObjectsViolateCapThree (fun _ _ a b c d e _ => countedFourObjectPigeonhole a b c d e)
#print axioms cap_four_counterexample
'''

def _counted_boundary_proofs():
    """Emit closed Fin3/Fin4 certificates, checked by the unchanged Lean gate.

    Direct eliminators and proof terms avoid transitive propext in convenience
    case/decision procedures. The domains and original cap definitions remain
    unchanged. This constructs finite witnesses, never a premise asserting the
    desired bound or a replacement production counting compiler.
    """
    def value(n, i):
        proof = "Nat.le.refl"
        for _ in range(n - i - 1):
            proof = "(Nat.le.step " + proof + ")"
        return "(⟨" + str(i) + ", " + proof + "⟩ : Fin " + str(n) + ")"

    def disjunction(variables):
        pairs = [a + " = " + b for i, a in enumerate(variables) for b in variables[i + 1:]]
        result = pairs[0]
        for pair in pairs[1:]:
            result = "(" + result + " ∨ " + pair + ")"
        return result

    def leaf(n, values):
        pairs = [(i, j) for i in range(n + 1) for j in range(i + 1, n + 1)]
        index = next(k for k, (i, j) in enumerate(pairs)
                     if j < len(values) and values[i] == values[j])
        term = "Eq.refl " + value(n, values[pairs[index][0]])
        if index:
            term = "Or.inr (" + term + ")"
            left_count = len(pairs) - 1 - index
        else:
            left_count = len(pairs) - 1
        for _ in range(left_count):
            term = "Or.inl (" + term + ")"
        return term

    def tree(n, values=()):
        # A witnessed equal pair proves the full disjunction regardless of
        # remaining objects. Keep those universal binders, but avoid expanding
        # their irrelevant finite cases into a large compiled proof artifact.
        if len(set(values)) < len(values):
            remaining = "abcde"[len(values):n + 1]
            term = leaf(n, values)
            return ("fun " + " ".join(remaining) + " => " + term) if remaining else term
        name = "countedThreeObjectCases" if n == 3 else "countedFourObjectCases"
        return name + "\n" + "".join("  " * (len(values) + 2) + "(" + tree(n, values + (i,)) + ")\n"
                                      for i in range(n))

    proofs = []
    for n, name in ((3, "countedThreeObjectPigeonhole"), (4, "countedFourObjectPigeonhole")):
        variables = list("abcde"[:n + 1])
        proofs.append("set_option maxRecDepth 8192 in\nset_option maxHeartbeats 2000000 in\n"
            + "theorem " + name + " : ∀ " + " ".join(variables) + " : Fin " + str(n) + ", "
            + disjunction(variables) + " :=\n  " + tree(n).rstrip() + "\n")
    marker = "__COUNTED_FINITE_PIGEONHOLE_PROOFS__"
    _need(_COUNTED_BOUNDARY_PROOF_TEMPLATE.count(marker) == 1, "exact finite-proof template marker required")
    return _COUNTED_BOUNDARY_PROOF_TEMPLATE.replace(marker, "\n".join(proofs))


def prepare_counted_ast_preservation(report, request_raw: bytes, *,
        expected_report_sha256, expected_request_sha256, toolchain):
    """Prepare exact fixed-cap3 AST interpretation obligations, without a build.

    Existing public counted validation owns the request, complete report, typed
    AST and emitted Lean. Independent witness serialization and denotation do
    not call its private factory, recognize by cap text, or assume equivalence.
    """
    _pin(expected_report_sha256, "complete counted report")
    _pin(expected_request_sha256, "complete counted request")
    report_raw = _wire(report, MAX_RECORD_BYTES)
    _need(_sha(report_raw) == expected_report_sha256, "independent counted report pin differs")
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_RECORD_BYTES // 8
          and _sha(request_raw) == expected_request_sha256,
          "independent bounded counted request pin differs")
    request = _parse(request_raw, MAX_RECORD_BYTES // 8)
    _need(type(request) is dict and type(report) is dict, "ordinary complete counted report/request required")
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain) is not None,
          "exact version-pinned Lean toolchain required")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "native AST preservation owner changed since import")
    # No operation import precedes the complete independent input commitments.
    from . import legal_counted_frame_v1 as counted
    checked = counted.validate_counted_frame(report, request_raw,
        expected_report_sha256=expected_report_sha256,
        expected_request_sha256=expected_request_sha256)
    _need(checked["request"] == request and checked["maximum"] == 3
          and checked["profile"] == "authored-at-most-three-distinct-per-event-and-time/v1"
          and checked["source_binding"] is None and checked["native_TDFOL_route_used"] is False,
          "exact existing authored fixed-three counted replay required")
    owners = _owners()
    _, emitter, contracts = owners
    producers = _counted_pins(owners, counted, checked)
    expression = checked["typed_expression"]
    typed, count = _counted_source_syntax(expression["root"])
    actual = _counted_json_value(expression)
    semantics = COUNTED_SEMANTICS
    instance = COUNTED_PROJECT_ROOT + ".Instance" + _sha(_wire({
        "profile": COUNTED_PROFILE, "report_sha256": expected_report_sha256,
        "request_sha256": expected_request_sha256, "semantics_sha256": _sha(semantics.encode()),
    }, MAX_RECORD_BYTES))
    modules = [COUNTED_PROJECT_ROOT + ".Prelude", COUNTED_PROJECT_ROOT + ".Semantics", instance, COUNTED_PROJECT_ROOT]
    imports = {modules[0]: [], modules[1]: [modules[0]], instance: [modules[1]], COUNTED_PROJECT_ROOT: [instance]}
    names = ["counted_value_exact", "counted_ast_closed", "counted_denotation_matches_lowering",
             "cap_two_counterexample", "cap_four_counterexample"]
    reconstructed = ("countedTypedExpressionValue " + _counted_string(expression["expression_id"]) + " "
        + _counted_string(expression["signature"]["signature_id"]) + " "
        + _counted_string(expression["content_digest"]) + " typedCountedAst")
    body = (checked["lean_body"]
        + "\n\ndef actualTypedValue : NativeValue := " + actual
        + "\ndef typedCountedAst : CountedFormula := " + typed
        + "\ndef reconstructedTypedValue : NativeValue := " + reconstructed
        + "\ntheorem counted_value_exact : reconstructedTypedValue = actualTypedValue := by\n  rfl\n"
        + "#print axioms counted_value_exact\n"
        + "theorem counted_ast_closed : countedClosed [] typedCountedAst = true := by\n  decide\n"
        + "#print axioms counted_ast_closed\n"
        + "theorem counted_denotation_matches_lowering {Object EventFrame TimeFrame : Type}\n"
        + "    (member : Object → EventFrame → TimeFrame → Prop) :\n"
        + "    countedDenote member typedCountedAst emptyCountedEnvironment ↔ countedAtMostThree member := by\n"
        + "  exact Iff.intro (fun h => h) (fun h => h)\n#print axioms counted_denotation_matches_lowering\n"
        + _counted_boundary_proofs())
    inputs = {"schema": COUNTED_INPUT_SCHEMA, "profile": COUNTED_PROFILE,
        "counted_report": checked, "counted_report_sha256": expected_report_sha256,
        "original_request_raw_utf8": request_raw.decode("utf-8"),
        "original_request_sha256": expected_request_sha256,
        "typed_expression_sha256": checked["typed_expression_sha256"],
        "original_counted_lean_body_sha256": checked["lean_body_sha256"]}
    files = {
        "lakefile.toml": 'name = "legal_native_ast_preservation"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = ["LegalCountedAstPreservation"]\n',
        "lean-toolchain": toolchain + "\n",
        "preservation-inputs.json": _wire(inputs, 4 * MAX_RECORD_BYTES).decode() + "\n",
        modules[0].replace(".", "/") + ".lean": _file(COUNTED_PROJECT_ROOT, [], emitter.PRELUDE),
        modules[1].replace(".", "/") + ".lean": _file(COUNTED_PROJECT_ROOT, imports[modules[1]], semantics),
        instance.replace(".", "/") + ".lean": _file(instance, imports[instance], body),
        COUNTED_PROJECT_ROOT + ".lean": "import " + instance + "\n",
    }
    _need(len(files) == MAX_FILES and len(set(modules)) == MAX_MODULES
          and sum(len(text.encode()) for text in files.values()) <= MAX_PROJECT_BYTES,
          "complete counted preservation project exceeds bounds")
    manifest = contracts.seal_record({
        "schema": SCHEMA, "profile": COUNTED_PROFILE, "toolchain": toolchain, "target": "legal",
        "family": "first_order", "typed_profile": "many_sorted",
        "counted_report_sha256": expected_report_sha256, "original_request_sha256": expected_request_sha256,
        "typed_expression_sha256": checked["typed_expression_sha256"],
        "typed_expression_content_digest": checked["typed_expression_content_digest"],
        "lean_body_sha256": checked["lean_body_sha256"],
        "actual_typed_lean_value_sha256": _sha(actual.encode()),
        "typed_counted_lean_value_sha256": _sha(typed.encode()),
        "semantics_sha256": _sha(semantics.encode()), "prelude_sha256": _sha(emitter.PRELUDE.encode()),
        "typed_ast_node_count": count, "typed_predicates": ["Member"],
        "expected_modules": modules, "module_imports": imports,
        "file_sha256": {name: _sha(text.encode()) for name, text in sorted(files.items())},
        "theorems": [instance + "." + name for name in names],
        "theorem_assumptions": [
            "Object, EventFrame and TimeFrame are arbitrary Type carriers, not required to be inhabited.",
            "Member is an arbitrary ternary Prop relation in ordered object,event,time roles.",
            "Object equality uses Lean equality; each quantifier updates only its declared carrier environment.",
            "Physical IDs, signature, schema and content-digest metadata are preserved as values, not rehashed in Lean.",
            "Counterexamples use all-member Fin3/Fin4 Object carriers and Unit event/time carriers.",
            "No original bound, denotation equivalence or arbitrary Member bound is assumed.",
            "The five obligations and their axiom reports have not been executed or kernel checked."],
        "support_profile": {"source_owner": "legal_counted_frame_v1", "fixed_maximum": 3,
            "sorts": ["Object", "EventFrame", "TimeFrame"], "formula_sort": "Bool",
            "terms": ["bound_sorted_variable"], "predicate": "Member", "predicate_arity": 3,
            "ordered_argument_roles": ["object", "event", "time"], "quantifiers": ["∀"],
            "operators": ["∧", "∨", "→", "="], "builtin_object_equality": True,
            "closed_only": True, "named_lexical_shadowing": False,
            "ordered_children_preserved": True, "duplicate_subformulas_preserved": True,
            "event_time_policy": "per_event_and_time", "time_order_or_calendar": False,
            "native_TDFOL_route_used": False, "max_ast_nodes": 49, "max_ast_depth": MAX_AST_DEPTH},
        "counterfactual_boundary_specs": [
            {"name": "cap_two_counterexample", "objects": 3, "membership": "all_objects_one_frame",
             "actual_counted_denotation": True, "counterfactual_cap": 2,
             "counterfactual_denotation": False, "proof_observed": False},
            {"name": "cap_four_counterexample", "objects": 4, "membership": "all_objects_one_frame",
             "actual_counted_denotation": False, "counterfactual_cap": 4,
             "counterfactual_denotation": True, "proof_observed": False}],
        "source_custody": {"scope": "whole authored counted request/report and unchanged Lean definition replay",
            "original_request_raw_retained_in": "preservation-inputs.json/original_request_raw_utf8",
            "original_source_bundle_replayed": False, "source_prose_to_ast_proved": False},
        "trust_boundary": [
            "Current original counted validation authenticates the complete request/report and producer bindings.",
            "CountedFormula and CountedVariable are proof-witness syntax only, not production IR or a new compiler.",
            "Actual serialized AST and independent structural witness reconstruct every typed-expression field.",
            "Independent sorted denotation is compared with the unchanged original Lean definition.",
            "Cap2/cap4 are finite counterfactual proof specifications, not accepted fixed-v1 requests.",
            "No statutory counting unit, source meaning, applicability, calendar, deontic or model claim is made."],
        "producer_pins": producers, "counted_producer_pins": checked["producer_pins"],
        "preparation_only": True, "authority": dict(AUTHORITY),
        "training_mask": 0, "evaluation_gold_mask": 0, **FALSE_FLAGS,
    })
    _need(_wire(report, MAX_RECORD_BYTES) == report_raw,
          "caller counted report changed during preservation preparation")
    _need(_counted_pins(owners, counted, checked) == producers,
          "counted preservation producers changed during preparation")
    preparation = NativeAstPreservationPreparation(
        _wire(manifest, MAX_RECORD_BYTES).decode(), tuple(sorted(files.items())))
    preparation_sha256(preparation)
    return preparation


def validate_counted_ast_preservation(preparation, report, request_raw: bytes, *,
        expected_preparation_sha256, expected_report_sha256, expected_request_sha256, toolchain):
    """Require the whole preparation pin and replay the complete original pair."""
    _pin(expected_preparation_sha256, "complete counted preservation preparation")
    _need(preparation_sha256(preparation) == expected_preparation_sha256,
          "independent complete counted preservation pin differs")
    expected = prepare_counted_ast_preservation(report, request_raw,
        expected_report_sha256=expected_report_sha256, expected_request_sha256=expected_request_sha256,
        toolchain=toolchain)
    _need(expected == preparation, "counted preservation differs from complete original regeneration")
    return expected


MIXED_PROFILE = "typed-many-sorted-relational-deontic-renderer-preservation/v1"
MIXED_SOURCE_USE_PROFILE = MIXED_PROFILE + "+reviewed-source-use/v1"
MIXED_PROJECT_ROOT = "LegalMixedRelationalAstPreservation"
MIXED_INPUT_SCHEMA = "legal-mixed-relational-ast-preservation-inputs/v1"
MAX_MIXED_REPORT_BYTES = 8 * MAX_RECORD_BYTES
MAX_MIXED_REQUEST_BYTES = MAX_RECORD_BYTES // 2
MAX_MIXED_AST_NODES = 512
MAX_MIXED_AST_DEPTH = 48
_MIXED_OPERATION_PINS = None


# Shared Counted-prefixed types are three-carrier proof vocabulary only.
# No fixed Member syntax, counted denotation or cap premise enters this profile.
MIXED_SEMANTICS = (SEMANTICS + _SORTED_PROOF_TYPES + _SORTED_PROOF_VALUES
    + _SORTED_PROOF_ENVIRONMENT + r'''

abbrev MixedEntity (Object EventFrame TimeFrame : Type) :=
  Sum Unit (Sum Object (Sum EventFrame TimeFrame))

structure MixedPredicate where
  name : String
  domain : List CountedSort

structure MixedRoleRow where
  name : String
  roles : List String

inductive MixedFormula where
  | predicate (nodeId name : String) (variables : List CountedVariable)
  | equality (nodeId : String) (left right : CountedVariable)
  | negation (nodeId : String) (body : MixedFormula)
  | conjunction (nodeId : String) (left right : MixedFormula)
  | disjunction (nodeId : String) (left right : MixedFormula)
  | implication (nodeId : String) (left right : MixedFormula)
  | equivalence (nodeId : String) (left right : MixedFormula)
  | universal (nodeId name : String) (sort : CountedSort) (body : MixedFormula)
  | existential (nodeId name : String) (sort : CountedSort) (body : MixedFormula)
  | modal (nodeId extensionId operator : String) (body : MixedFormula)

def mixedIdentityValue (space value : String) : NativeValue :=
  .object [("interface", .string "LogicIdentityNamespaces@1"),
    ("namespace", .string space), ("schema_version", .string "logic-identity-namespaces/v1"),
    ("value", .string value), ("version", .string "1.0.0")]

def mixedModalKind (operator : String) : String :=
  if operator = "O" then "obligation" else
  if operator = "P" then "permission" else
  if operator = "F" then "forbidden" else "unsupported"

def mixedModalFeature (operator : String) : String :=
  if operator = "O" then "legacy.obligation" else
  if operator = "P" then "legacy.permission" else
  if operator = "F" then "legacy.forbidden" else "unsupported"

def mixedModalKey (operator : String) : Option String :=
  if operator = "O" then some "deontic:O" else
  if operator = "P" then some "deontic:P" else
  if operator = "F" then some "deontic:F" else none

def mixedTypedModalValue (nodeId extensionId operator : String)
    (child : NativeValue) : NativeValue :=
  .object [("arguments", .array []), ("binders", .array []),
    ("extension", .object [
      ("children", .array [child]), ("family", mixedIdentityValue "family" "tdfol"),
      ("features", .array [.string "legacy.classic_letter", .string (mixedModalFeature operator)]),
      ("interface", .string "LogicExtensionNode@1"), ("metadata", .object []),
      ("node_id", .string extensionId),
      ("payload", .object [("kind", .string (mixedModalKind operator)),
        ("letter", .string operator), ("resolution", .string "deontic"),
        ("schema_version", .string "legacy.deontic/v1")]),
      ("payload_schema", .string "legacy.deontic/v1"),
      ("profile", mixedIdentityValue "profile" "tdfol_default"),
      ("schema_version", .string "syntax-logic-extension-node/v1")]),
    ("kind", .string "extension"), ("metadata", .object []),
    ("node_id", .string nodeId), ("schema_version", .string "syntax-logic-node/v1"),
    ("sort", countedBoolSortValue), ("symbol", .string "")]

def mixedToTypedNodeValue : MixedFormula → NativeValue
  | .predicate nodeId name variables =>
      countedNodeValue nodeId "predicate" name countedBoolSortValue
        (variables.map countedVariableValue) []
  | .equality nodeId left right =>
      countedNodeValue nodeId "equality" "" countedBoolSortValue
        [countedVariableValue left, countedVariableValue right] []
  | .negation nodeId body =>
      countedNodeValue nodeId "not" "" countedBoolSortValue [mixedToTypedNodeValue body] []
  | .conjunction nodeId left right =>
      countedNodeValue nodeId "and" "" countedBoolSortValue
        [mixedToTypedNodeValue left, mixedToTypedNodeValue right] []
  | .disjunction nodeId left right =>
      countedNodeValue nodeId "or" "" countedBoolSortValue
        [mixedToTypedNodeValue left, mixedToTypedNodeValue right] []
  | .implication nodeId left right =>
      countedNodeValue nodeId "implies" "" countedBoolSortValue
        [mixedToTypedNodeValue left, mixedToTypedNodeValue right] []
  | .equivalence nodeId left right =>
      countedNodeValue nodeId "iff" "" countedBoolSortValue
        [mixedToTypedNodeValue left, mixedToTypedNodeValue right] []
  | .universal nodeId name sort body =>
      countedNodeValue nodeId "forall" "" countedBoolSortValue
        [mixedToTypedNodeValue body] [countedBinderValue name sort]
  | .existential nodeId name sort body =>
      countedNodeValue nodeId "exists" "" countedBoolSortValue
        [mixedToTypedNodeValue body] [countedBinderValue name sort]
  | .modal nodeId extensionId operator body =>
      mixedTypedModalValue nodeId extensionId operator (mixedToTypedNodeValue body)

def mixedPredicateValue (declaration : MixedPredicate) : NativeValue :=
  .object [("domain", .array (declaration.domain.map countedAtomicSortValue)),
    ("kind", .string "predicate"), ("metadata", .object []),
    ("name", .string declaration.name), ("range", countedBoolSortValue),
    ("schema_version", .string "syntax-symbol-declaration/v1")]

def mixedSignatureValue (signatureId : String) (sorts : List CountedSort)
    (predicates : List MixedPredicate) : NativeValue :=
  .object [("family", mixedIdentityValue "family" "tdfol"), ("features", .array []),
    ("interface", .string "LogicSignature@1"), ("metadata", .object []),
    ("profile", mixedIdentityValue "profile" "tdfol_default"),
    ("schema_version", .string "syntax-logic-signature/v1"),
    ("signature_id", .string signatureId),
    ("sorts", .array (countedBoolSortValue :: sorts.map countedAtomicSortValue)),
    ("symbols", .array (predicates.map mixedPredicateValue))]

def mixedRoleRowsValue (roles : List MixedRoleRow) : NativeValue :=
  .array (roles.map fun row => .object [
    ("roles", .array (row.roles.map NativeValue.string)), ("symbol", .string row.name)])

def mixedTypedExpressionValue (expressionId signatureId contentDigest : String)
    (sorts : List CountedSort) (predicates : List MixedPredicate) (ast : MixedFormula) : NativeValue :=
  .object [("content_digest", .string contentDigest), ("expression_id", .string expressionId),
    ("family", mixedIdentityValue "family" "tdfol"), ("interface", .string "TypedExpression@1"),
    ("metadata", .object []), ("profile", mixedIdentityValue "profile" "tdfol_default"),
    ("root", mixedToTypedNodeValue ast), ("schema_version", .string "syntax-typed-expression/v1"),
    ("signature", mixedSignatureValue signatureId sorts predicates)]

def mixedSourceValue (expressionId signatureId contentDigest : String)
    (sorts : List CountedSort) (predicates : List MixedPredicate)
    (roles : List MixedRoleRow) (ast : MixedFormula) : NativeValue :=
  .object [("argument_roles", mixedRoleRowsValue roles),
    ("typed_expression", mixedTypedExpressionValue expressionId signatureId contentDigest sorts predicates ast)]

def mixedRendererVariableValue (name : String) (sort : CountedSort) : NativeValue :=
  .object [("name", .string name), ("node_type", .string "Variable"),
    ("sort", .string (countedSortName sort))]

def mixedRendererBinaryValue (operator : String) (left right : NativeValue) : NativeValue :=
  .object [("left", left), ("node_type", .string "BinaryFormula"),
    ("operator", .object [("value", .string operator)]), ("right", right)]

def mixedRendererQuantifierValue (operator name : String) (sort : CountedSort)
    (body : NativeValue) : NativeValue :=
  .object [("formula", body), ("node_type", .string "QuantifiedFormula"),
    ("quantifier", .object [("value", .string operator)]),
    ("variable", mixedRendererVariableValue name sort)]

def mixedToRendererNodeValue : MixedFormula → NativeValue
  | .predicate _ name variables => .object [
      ("arguments", .array (variables.map fun boundVariable => mixedRendererVariableValue boundVariable.name boundVariable.sort)),
      ("name", .string name), ("node_type", .string "AtomicFormula")]
  | .equality _ left right => .object [
      ("left", mixedRendererVariableValue left.name left.sort),
      ("node_type", .string "EqualityFormula"),
      ("right", mixedRendererVariableValue right.name right.sort)]
  | .negation _ body => .object [("formula", mixedToRendererNodeValue body),
      ("node_type", .string "UnaryFormula"), ("operator", .object [("value", .string "¬")])]
  | .conjunction _ left right => mixedRendererBinaryValue "∧" (mixedToRendererNodeValue left) (mixedToRendererNodeValue right)
  | .disjunction _ left right => mixedRendererBinaryValue "∨" (mixedToRendererNodeValue left) (mixedToRendererNodeValue right)
  | .implication _ left right => mixedRendererBinaryValue "→" (mixedToRendererNodeValue left) (mixedToRendererNodeValue right)
  | .equivalence _ left right => mixedRendererBinaryValue "↔" (mixedToRendererNodeValue left) (mixedToRendererNodeValue right)
  | .universal _ name sort body => mixedRendererQuantifierValue "∀" name sort (mixedToRendererNodeValue body)
  | .existential _ name sort body => mixedRendererQuantifierValue "∃" name sort (mixedToRendererNodeValue body)
  | .modal _ _ operator body => .object [("agent", .null), ("context", .null),
      ("formula", mixedToRendererNodeValue body), ("node_type", .string "DeonticFormula"),
      ("operator", .object [("value", .string operator)])]

def mixedRendererValue (ast : MixedFormula) : NativeValue :=
  .object [("profile", .string "three-sort-variables-deontic-equality/v1"),
    ("root", mixedToRendererNodeValue ast),
    ("schema", .string "sorted-relational-renderer-ast/v1")]

def mixedDomain (predicates : List MixedPredicate) (name : String) : Option (List CountedSort) :=
  match predicates with
  | [] => none
  | declaration :: rest => if declaration.name = name then some declaration.domain else mixedDomain rest name

def mixedRoles (roles : List MixedRoleRow) (name : String) : List String :=
  match roles with
  | [] => []
  | row :: rest => if row.name = name then row.roles else mixedRoles rest name

def mixedVariableClosed (bound : List (CountedSort × String)) (boundVariable : CountedVariable) : Bool :=
  bound.contains (boundVariable.sort, boundVariable.name)

def mixedClosed (predicates : List MixedPredicate) (roles : List MixedRoleRow)
    (bound : List (CountedSort × String)) : MixedFormula → Bool
  | .predicate _ name variables =>
      match mixedDomain predicates name with
      | none => false
      | some domain => domain == variables.map CountedVariable.sort &&
          variables.all (mixedVariableClosed bound) &&
          decide ((mixedRoles roles name).length = variables.length)
  | .equality _ left right => left.sort == right.sort &&
      mixedVariableClosed bound left && mixedVariableClosed bound right
  | .negation _ body => mixedClosed predicates roles bound body
  | .conjunction _ left right => mixedClosed predicates roles bound left && mixedClosed predicates roles bound right
  | .disjunction _ left right => mixedClosed predicates roles bound left && mixedClosed predicates roles bound right
  | .implication _ left right => mixedClosed predicates roles bound left && mixedClosed predicates roles bound right
  | .equivalence _ left right => mixedClosed predicates roles bound left && mixedClosed predicates roles bound right
  | .universal _ name sort body => !(bound.map Prod.snd).contains name &&
      mixedClosed predicates roles ((sort, name) :: bound) body
  | .existential _ name sort body => !(bound.map Prod.snd).contains name &&
      mixedClosed predicates roles ((sort, name) :: bound) body
  | .modal _ _ operator body => (mixedModalKey operator).isSome && mixedClosed predicates roles bound body

def mixedWellFormed (sorts : List CountedSort) (predicates : List MixedPredicate)
    (roles : List MixedRoleRow) (ast : MixedFormula) : Bool :=
  decide (sorts.length = 3) && sorts.contains .object && sorts.contains .event && sorts.contains .time &&
  !(predicates.isEmpty) &&
  decide ((predicates.map MixedPredicate.name).eraseDups.length = predicates.length) &&
  decide (roles.length = predicates.length) &&
  decide ((roles.map MixedRoleRow.name).eraseDups.length = roles.length) &&
  predicates.all (fun declaration =>
    decide (1 ≤ declaration.domain.length ∧ declaration.domain.length ≤ 8) &&
    decide ((mixedRoles roles declaration.name).length = declaration.domain.length) &&
    decide ((mixedRoles roles declaration.name).eraseDups.length = declaration.domain.length)) &&
  mixedClosed predicates roles [] ast

def mixedArgumentValue {Object EventFrame TimeFrame : Type}
    (environment : CountedEnvironment Object EventFrame TimeFrame)
    (boundVariable : CountedVariable) : Option (MixedEntity Object EventFrame TimeFrame) :=
  CountedSort.casesOn boundVariable.sort
    (Option.casesOn (countedObjectValue environment boundVariable) none
      (fun value => some (Sum.inr (Sum.inl value))))
    (Option.casesOn (countedEventValue environment boundVariable) none
      (fun value => some (Sum.inr (Sum.inr (Sum.inl value)))))
    (Option.casesOn (countedTimeValue environment boundVariable) none
      (fun value => some (Sum.inr (Sum.inr (Sum.inr value)))))

def mixedArguments {Object EventFrame TimeFrame : Type}
    (environment : CountedEnvironment Object EventFrame TimeFrame) :
    List CountedVariable → Option (List (MixedEntity Object EventFrame TimeFrame))
  | [] => some []
  | boundVariable :: rest => do
      let value ← mixedArgumentValue environment boundVariable
      let values ← mixedArguments environment rest
      pure (value :: values)

def mixedEqualityDenote {Object EventFrame TimeFrame : Type}
    (environment : CountedEnvironment Object EventFrame TimeFrame)
    (left right : CountedVariable) : Prop :=
  CountedSort.casesOn left.sort
    (Option.casesOn (countedObjectValue environment left) False (fun l =>
      Option.casesOn (countedObjectValue environment right) False (fun r => l = r)))
    (Option.casesOn (countedEventValue environment left) False (fun l =>
      Option.casesOn (countedEventValue environment right) False (fun r => l = r)))
    (Option.casesOn (countedTimeValue environment left) False (fun l =>
      Option.casesOn (countedTimeValue environment right) False (fun r => l = r)))

def mixedDenote {Object EventFrame TimeFrame : Type}
    (i : Interpretation (MixedEntity Object EventFrame TimeFrame) Unit) :
    MixedFormula → CountedEnvironment Object EventFrame TimeFrame → Nat → Prop
  | .predicate _ name variables, environment, t =>
      match mixedArguments environment variables with
      | none => False
      | some values => i.atom name values t
  | .equality _ left right, environment, _ => mixedEqualityDenote environment left right
  | .negation _ body, environment, t => ¬ mixedDenote i body environment t
  | .conjunction _ left right, environment, t => mixedDenote i left environment t ∧ mixedDenote i right environment t
  | .disjunction _ left right, environment, t => mixedDenote i left environment t ∨ mixedDenote i right environment t
  | .implication _ left right, environment, t => mixedDenote i left environment t → mixedDenote i right environment t
  | .equivalence _ left right, environment, t => mixedDenote i left environment t ↔ mixedDenote i right environment t
  | .universal _ name sort body, environment, t =>
      CountedSort.casesOn sort
        (∀ entity : Object, mixedDenote i body (updateCountedObject environment name entity) t)
        (∀ frame : EventFrame, mixedDenote i body (updateCountedEvent environment name frame) t)
        (∀ instant : TimeFrame, mixedDenote i body (updateCountedTime environment name instant) t)
  | .existential _ name sort body, environment, t =>
      CountedSort.casesOn sort
        (∃ entity : Object, mixedDenote i body (updateCountedObject environment name entity) t)
        (∃ frame : EventFrame, mixedDenote i body (updateCountedEvent environment name frame) t)
        (∃ instant : TimeFrame, mixedDenote i body (updateCountedTime environment name instant) t)
  | .modal _ _ operator body, environment, t =>
      match mixedModalKey operator with
      | none => False
      | some key => i.modal key [] none (fun u => mixedDenote i body environment u) t

def mixedRoleInterpretation {Object EventFrame TimeFrame : Type}
    (base : Interpretation (MixedEntity Object EventFrame TimeFrame) Unit)
    (atoms : String → List (String × MixedEntity Object EventFrame TimeFrame) → Nat → Prop)
    (roles : List MixedRoleRow) : Interpretation (MixedEntity Object EventFrame TimeFrame) Unit :=
  { base with atom := fun name values t => atoms name ((mixedRoles roles name).zip values) t }

def mixedRoleDenote {Object EventFrame TimeFrame : Type}
    (base : Interpretation (MixedEntity Object EventFrame TimeFrame) Unit)
    (atoms : String → List (String × MixedEntity Object EventFrame TimeFrame) → Nat → Prop)
    (roles : List MixedRoleRow) :
    MixedFormula → CountedEnvironment Object EventFrame TimeFrame → Nat → Prop
  | .predicate _ name variables, environment, t =>
      match mixedArguments environment variables with
      | none => False
      | some values => atoms name ((mixedRoles roles name).zip values) t
  | .equality _ left right, environment, _ => mixedEqualityDenote environment left right
  | .negation _ body, environment, t => ¬ mixedRoleDenote base atoms roles body environment t
  | .conjunction _ left right, environment, t => mixedRoleDenote base atoms roles left environment t ∧ mixedRoleDenote base atoms roles right environment t
  | .disjunction _ left right, environment, t => mixedRoleDenote base atoms roles left environment t ∨ mixedRoleDenote base atoms roles right environment t
  | .implication _ left right, environment, t => mixedRoleDenote base atoms roles left environment t → mixedRoleDenote base atoms roles right environment t
  | .equivalence _ left right, environment, t => mixedRoleDenote base atoms roles left environment t ↔ mixedRoleDenote base atoms roles right environment t
  | .universal _ name sort body, environment, t =>
      CountedSort.casesOn sort
        (∀ entity : Object, mixedRoleDenote base atoms roles body (updateCountedObject environment name entity) t)
        (∀ frame : EventFrame, mixedRoleDenote base atoms roles body (updateCountedEvent environment name frame) t)
        (∀ instant : TimeFrame, mixedRoleDenote base atoms roles body (updateCountedTime environment name instant) t)
  | .existential _ name sort body, environment, t =>
      CountedSort.casesOn sort
        (∃ entity : Object, mixedRoleDenote base atoms roles body (updateCountedObject environment name entity) t)
        (∃ frame : EventFrame, mixedRoleDenote base atoms roles body (updateCountedEvent environment name frame) t)
        (∃ instant : TimeFrame, mixedRoleDenote base atoms roles body (updateCountedTime environment name instant) t)
  | .modal _ _ operator body, environment, t =>
      match mixedModalKey operator with
      | none => False
      | some key => base.modal key [] none (fun u => mixedRoleDenote base atoms roles body environment u) t
''')


def _mixed_identity(value, namespace, identity):
    _keys(value, {"interface", "namespace", "schema_version", "value", "version"},
          "mixed identity witness")
    _need(value == {"interface": "LogicIdentityNamespaces@1", "namespace": namespace,
          "schema_version": "logic-identity-namespaces/v1", "value": identity,
          "version": "1.0.0"}, "exact mixed identity namespace/version required")


def _mixed_sort(value, *, formula=False):
    _keys(value, {"arguments", "kind", "name", "schema_version"}, "mixed sort witness")
    _need(value["schema_version"] == "syntax-logic-sort/v1" and value["arguments"] == [],
          "exact atomic mixed sort required")
    if formula:
        _need(value["name"] == "Bool" and value["kind"] == "bool", "mixed formula Bool sort required")
        return "bool"
    names = {"Object": "object", "EventFrame": "event", "TimeFrame": "time"}
    _need(type(value["name"]) is str and value["name"] in names and value["kind"] == "atomic",
          "only original three source sorts are supported")
    return names[value["name"]]


def _mixed_source_witness(expression, role_rows):
    """Reconstruct every typed field independently of the production lowering.

    Identities and digest text remain exact values, not in-kernel hash claims.
    Signature, role and sort arrays retain their actual serialized order.
    """
    _keys(expression, {"content_digest", "expression_id", "family", "interface", "metadata",
                       "profile", "root", "schema_version", "signature"}, "mixed typed expression")
    _need(expression["interface"] == "TypedExpression@1"
          and expression["schema_version"] == "syntax-typed-expression/v1"
          and expression["metadata"] == {}, "exact unannotated mixed typed expression required")
    _mixed_identity(expression["family"], "family", "tdfol")
    _mixed_identity(expression["profile"], "profile", "tdfol_default")
    for key in ("expression_id", "content_digest"):
        _need(type(expression[key]) is str and 0 < len(expression[key]) <= 4096,
              "bounded exact mixed expression identity required")
    _pin(expression["content_digest"], "mixed typed content digest value")
    signature = expression["signature"]
    _keys(signature, {"family", "features", "interface", "metadata", "profile", "schema_version",
                      "signature_id", "sorts", "symbols"}, "mixed signature")
    _need(signature["interface"] == "LogicSignature@1"
          and signature["schema_version"] == "syntax-logic-signature/v1"
          and signature["metadata"] == {} and signature["features"] == []
          and type(signature["signature_id"]) is str and 0 < len(signature["signature_id"]) <= 4096,
          "exact closed mixed signature required")
    _mixed_identity(signature["family"], "family", "tdfol")
    _mixed_identity(signature["profile"], "profile", "tdfol_default")
    _need(type(signature["sorts"]) is list and len(signature["sorts"]) == 4,
          "complete original four-sort signature required")
    _mixed_sort(signature["sorts"][0], formula=True)
    sort_order = [_mixed_sort(value) for value in signature["sorts"][1:]]
    _need(set(sort_order) == {"object", "event", "time"}, "all three distinct source sorts required")
    declarations, domains = [], {}
    _need(type(signature["symbols"]) is list and 1 <= len(signature["symbols"]) <= 64,
          "bounded nonempty mixed predicate table required")
    for declaration in signature["symbols"]:
        _keys(declaration, {"domain", "kind", "metadata", "name", "range", "schema_version"},
              "mixed predicate declaration")
        name = _name(declaration["name"])
        _need(len(name) <= 64 and name not in domains and declaration["kind"] == "predicate"
              and declaration["metadata"] == {}
              and declaration["schema_version"] == "syntax-symbol-declaration/v1"
              and type(declaration["domain"]) is list and 1 <= len(declaration["domain"]) <= 8,
              "exact unique bounded mixed predicate declaration required")
        _mixed_sort(declaration["range"], formula=True)
        domain = [_mixed_sort(value) for value in declaration["domain"]]
        domains[name] = domain
        declarations.append("⟨" + _counted_string(name) + ", [" + ", ".join("." + x for x in domain) + "]⟩")
    _need(type(role_rows) is list and len(role_rows) == len(domains),
          "complete original mixed role ledger required")
    roles, role_terms = {}, []
    for row in role_rows:
        _keys(row, {"symbol", "roles"}, "mixed role row")
        name, labels = row["symbol"], row["roles"]
        _need(type(name) is str and name in domains and name not in roles
              and type(labels) is list and len(labels) == len(domains[name])
              and all(type(label) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,47}", label) for label in labels)
              and len(set(labels)) == len(labels), "exact ordered distinct mixed roles required")
        roles[name] = list(labels)
        role_terms.append("⟨" + _counted_string(name) + ", [" + ", ".join(_counted_string(x) for x in labels) + "]⟩")
    count, extension_count, identifiers, binder_names, used = 0, 0, set(), set(), set()

    def identity(value):
        _need(type(value) is str and 0 < len(value) <= 4096 and value not in identifiers,
              "distinct bounded original mixed node/extension identities required")
        identifiers.add(value)
        return _counted_string(value)

    def node(value, depth):
        nonlocal count
        _need(type(value) is dict and type(value.get("kind")) is str,
              "ordinary exact mixed typed node required")
        fields = {"arguments", "binders", "kind", "metadata", "node_id", "schema_version", "sort", "symbol"}
        if value["kind"] == "extension":
            fields.add("extension")
        _keys(value, fields, "mixed typed node")
        count += 1
        _need(count <= MAX_MIXED_AST_NODES and depth <= MAX_MIXED_AST_DEPTH,
              "original mixed AST node/depth bound exceeded")
        node_id = identity(value["node_id"])
        _need(value["schema_version"] == "syntax-logic-node/v1" and value["metadata"] == {}
              and type(value["arguments"]) is list and type(value["binders"]) is list
              and type(value["symbol"]) is str, "exact unannotated mixed typed node required")
        return node_id

    def variable(value, environment, depth, expected_sort=None):
        node_id = node(value, depth)
        _need(value["kind"] == "variable" and value["arguments"] == [] and value["binders"] == [],
              "only original bound mixed variables supported")
        found = _mixed_sort(value["sort"])
        name = _name(value["symbol"])
        _need(len(name) <= 64 and environment.get(name) == found
              and (expected_sort is None or expected_sort == found),
              "free, wrongly sorted or reordered mixed variable refused")
        return "⟨" + node_id + ", " + _counted_string(name) + ", ." + found + "⟩"

    def formula(value, environment, depth):
        nonlocal extension_count
        node_id = node(value, depth)
        _mixed_sort(value["sort"], formula=True)
        kind, arguments, binders = value["kind"], value["arguments"], value["binders"]
        if kind == "predicate":
            name = value["symbol"]
            _need(name in domains and binders == [] and len(arguments) == len(domains[name]),
                  "exact declared mixed predicate and domain required")
            used.add(name)
            variables = [variable(child, environment, depth + 1, sort)
                         for child, sort in zip(arguments, domains[name], strict=True)]
            return "(.predicate " + node_id + " " + _counted_string(name) + " [" + ", ".join(variables) + "])"
        _need(value["symbol"] == "", "mixed connective/quantifier/equality symbol must remain empty")
        if kind == "equality":
            _need(binders == [] and len(arguments) == 2, "binary original same-sort equality required")
            sort = _mixed_sort(arguments[0]["sort"])
            return "(.equality " + node_id + " " + variable(arguments[0], environment, depth + 1, sort) + " " + variable(arguments[1], environment, depth + 1, sort) + ")"
        if kind in {"and", "or", "implies", "iff"}:
            _need(binders == [] and len(arguments) == 2, "exact binary mixed connective required")
            name = {"and": "conjunction", "or": "disjunction", "implies": "implication", "iff": "equivalence"}[kind]
            return "(." + name + " " + node_id + " " + formula(arguments[0], environment, depth + 1) + " " + formula(arguments[1], environment, depth + 1) + ")"
        if kind == "not":
            _need(binders == [] and len(arguments) == 1, "exact original mixed negation required")
            return "(.negation " + node_id + " " + formula(arguments[0], environment, depth + 1) + ")"
        if kind in {"forall", "exists"}:
            _need(len(binders) == 1 and len(arguments) == 1, "single original mixed quantifier binder required")
            binder = binders[0]
            _keys(binder, {"name", "schema_version", "sort"}, "mixed binder")
            name = _name(binder["name"])
            sort = _mixed_sort(binder["sort"])
            _need(len(name) <= 64 and binder["schema_version"] == "syntax-binder/v1"
                  and name not in environment and name not in binder_names and name not in domains,
                  "globally distinct nonshadowing original mixed binder required")
            binder_names.add(name)
            return "(." + ("universal" if kind == "forall" else "existential") + " " + node_id + " " + _counted_string(name) + " ." + sort + " " + formula(arguments[0], {**environment, name: sort}, depth + 1) + ")"
        if kind == "extension":
            _need(arguments == [] and binders == [], "closed original mixed modal wrapper required")
            extension = value["extension"]
            _keys(extension, {"children", "family", "features", "interface", "metadata", "node_id",
                              "payload", "payload_schema", "profile", "schema_version"}, "mixed modal extension")
            extension_id = identity(extension["node_id"])
            _mixed_identity(extension["family"], "family", "tdfol")
            _mixed_identity(extension["profile"], "profile", "tdfol_default")
            _need(extension["interface"] == "LogicExtensionNode@1"
                  and extension["schema_version"] == "syntax-logic-extension-node/v1"
                  and extension["metadata"] == {} and extension["payload_schema"] == "legacy.deontic/v1"
                  and type(extension["children"]) is list and len(extension["children"]) == 1,
                  "exact original unannotated mixed extension required")
            payload = extension["payload"]
            _keys(payload, {"kind", "letter", "resolution", "schema_version"}, "mixed modal payload")
            letter = payload["letter"]
            kinds = {"O": "obligation", "P": "permission", "F": "forbidden"}
            _need(type(letter) is str and letter in kinds
                  and payload == {"kind": kinds[letter], "letter": letter, "resolution": "deontic",
                                  "schema_version": "legacy.deontic/v1"}
                  and extension["features"] == ["legacy.classic_letter", "legacy." + kinds[letter]],
                  "exact original O/P/F payload and ordered features required")
            extension_count += 1
            return "(.modal " + node_id + " " + extension_id + " " + _counted_string(letter) + " " + formula(extension["children"][0], environment, depth + 1) + ")"
        raise ValueError("unsupported mixed preservation constructor: " + str(kind))

    source = formula(expression["root"], {}, 0)
    _need(used == set(domains) and binder_names, "closed complete mixed predicate population required")
    return {"source": source, "count": count, "extension_count": extension_count,
            "sorts": "[" + ", ".join("." + x for x in sort_order) + "]",
            "predicates": "[" + ", ".join(declarations) + "]",
            "roles": "[" + ", ".join(role_terms) + "]",
            "expression_id": _counted_string(expression["expression_id"]),
            "signature_id": _counted_string(signature["signature_id"]),
            "content_digest": _counted_string(expression["content_digest"])}


def _mixed_pins(owners, relational, checked):
    """Authenticate only current freshly replayed producer paths."""
    global _MIXED_OPERATION_PINS
    current = relational._mixed_owners()[-1]
    _need(type(current) is dict and 1 <= len(current) <= 32
          and checked["producer_pins"] == current, "current complete mixed producer closure required")
    pins = dict(_pins(owners))
    for spelling, digest in current.items():
        _pin(digest, "current mixed producer")
        path = Path(spelling)
        _need(path.is_absolute() and str(path.resolve()) == spelling
              and _sha(path.read_bytes()) == digest, "current mixed producer source bytes differ")
        pins[spelling] = digest
    path = Path(relational.__file__).resolve()
    pins[str(path)] = _sha(path.read_bytes())
    if _MIXED_OPERATION_PINS is None:
        _MIXED_OPERATION_PINS = dict(pins)
    _need(pins == _MIXED_OPERATION_PINS, "mixed preservation operation owners changed since first use")
    return pins


def _mixed_callback_state(relational, owners):
    functions = (_reviewed_source_use_identity, _mixed_identity, _mixed_sort, _mixed_source_witness, _mixed_pins,
        _mixed_callback_state, prepare_mixed_relational_ast_preservation,
        validate_mixed_relational_ast_preservation, _counted_json_value, _counted_string,
        preparation_sha256, _owners, _pins, _wire, _parse, _sha, _pin, _keys, _name,
        _need, _string, _file, relational.validate_mixed_relational_norm_v1,
        relational.prepare_mixed_relational_norm_v1, relational._mixed_parse,
        relational._mixed_owners, relational._mixed_strict_expression, relational._mixed_lower,
        relational._mixed_callbacks, owners[1].sorted_relational_document, owners[2].seal_record)
    return tuple((function, getattr(function, "__code__", None)) for function in functions)


def prepare_mixed_relational_ast_preservation(report, request_raw: bytes, *,
        expected_report_sha256, expected_request_sha256, toolchain,
        source_use_binding=None, expected_source_use_binding_sha256=None):
    """Prepare independent concrete sorted-source/renderer obligations.

    The original mixed owner replays the complete request and report. The
    witness independently rebuilds full typed and renderer values and directly
    interprets source constructors; no TDFOL native AST or prose theorem is
    fabricated. Preparation executes no compiler, model or accepted transition.
    """
    _pin(expected_report_sha256, "complete mixed relational report")
    _pin(expected_request_sha256, "complete original mixed request")
    report_raw = _wire(report, MAX_MIXED_REPORT_BYTES)
    _need(_sha(report_raw) == expected_report_sha256, "independent complete mixed report pin differs")
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_MIXED_REQUEST_BYTES
          and _sha(request_raw) == expected_request_sha256, "independent bounded mixed request pin differs")
    request = _parse(request_raw, MAX_MIXED_REQUEST_BYTES)
    detached = _parse(report_raw, MAX_MIXED_REPORT_BYTES)
    _need(type(report) is dict and type(detached) is dict and type(request) is dict,
          "complete ordinary mixed report/request required")
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain) is not None,
          "exact version-pinned Lean toolchain required")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "native AST preservation owner changed since import")
    identity_validator = _reviewed_source_use_identity
    identity_validator_code = identity_validator.__code__
    identity_raw, source_identity = identity_validator(source_use_binding, expected_source_use_binding_sha256)
    selected_profile = MIXED_PROFILE if identity_raw is None else MIXED_SOURCE_USE_PROFILE
    _need(detached.get("schema") == "legal-mixed-relational-norm-report/v1"
          and detached.get("profile") == "authored-many-sorted-relational-deontic/v1"
          and detached.get("native_ast") is None and detached.get("native_parser_roundtrip") is False,
          "explicit original renderer-only mixed profile required")
    witness = _mixed_source_witness(detached.get("typed_expression"), detached.get("argument_roles"))
    renderer = detached.get("renderer_ast")
    _keys(renderer, {"schema", "profile", "root"}, "complete original mixed renderer record")
    _need(renderer["schema"] == "sorted-relational-renderer-ast/v1"
          and renderer["profile"] == "three-sort-variables-deontic-equality/v1",
          "explicit existing sorted renderer required")
    # All independent commitments and bounded source shapes precede operation imports.
    from . import legal_relational_norm_v1 as relational
    owners = _owners()
    _, emitter, contracts = owners
    def source_identity_fence():
        if identity_raw is None:
            return
        _need(_reviewed_source_use_identity is identity_validator
              and identity_validator.__code__ is identity_validator_code,
              "reviewed source-use identity validator changed during preparation")
        current_raw, current_identity = identity_validator(source_use_binding,
            expected_source_use_binding_sha256, contracts=contracts)
        _need(current_raw == identity_raw and _wire(current_identity, MAX_RECORD_BYTES)
              == _wire(source_identity, MAX_RECORD_BYTES)
              and selected_profile == MIXED_SOURCE_USE_PROFILE,
              "caller or detached reviewed source-use identity changed during preparation")

    source_identity_fence()
    callbacks = _mixed_callback_state(relational, owners)
    upstream_pins = relational._mixed_owners()[-1]
    authority, false_flags = dict(AUTHORITY), dict(FALSE_FLAGS)
    _need(authority and all(value is False for value in authority.values())
          and all(value is False for value in false_flags.values()), "mixed preparation cannot confer authority")
    policy = (SCHEMA, MIXED_PROFILE, MIXED_PROJECT_ROOT, MIXED_INPUT_SCHEMA, MIXED_SEMANTICS,
              MAX_MIXED_REPORT_BYTES, MAX_MIXED_REQUEST_BYTES, MAX_MIXED_AST_NODES,
              MAX_MIXED_AST_DEPTH, MAX_RECORD_BYTES, MAX_PROJECT_BYTES, MAX_PREPARATION_BYTES,
              MAX_FILES, MAX_MODULES)
    checked = None
    checked_raw = None

    def fence():
        source_identity_fence()
        _need(_wire(report, MAX_MIXED_REPORT_BYTES) == report_raw
              and _wire(detached, MAX_MIXED_REPORT_BYTES) == report_raw,
              "caller or detached mixed report changed during preservation")
        _need(_sha(request_raw) == expected_request_sha256
              and _wire(_parse(request_raw, MAX_MIXED_REQUEST_BYTES), MAX_MIXED_REQUEST_BYTES)
                  == _wire(request, MAX_MIXED_REQUEST_BYTES),
              "original mixed request changed during preservation")
        _need(_mixed_callback_state(relational, owners) == callbacks
              and relational._mixed_owners()[-1] == upstream_pins
              and _sha(Path(__file__).read_bytes()) == _SELF_PIN,
              "original mixed preservation callbacks or source producers changed")
        _need(AUTHORITY == authority and FALSE_FLAGS == false_flags
              and policy == (SCHEMA, MIXED_PROFILE, MIXED_PROJECT_ROOT, MIXED_INPUT_SCHEMA, MIXED_SEMANTICS,
                  MAX_MIXED_REPORT_BYTES, MAX_MIXED_REQUEST_BYTES, MAX_MIXED_AST_NODES,
                  MAX_MIXED_AST_DEPTH, MAX_RECORD_BYTES, MAX_PROJECT_BYTES, MAX_PREPARATION_BYTES,
                  MAX_FILES, MAX_MODULES), "mixed preservation policy changed")
        if checked is not None:
            _need(_wire(checked, MAX_MIXED_REPORT_BYTES) == checked_raw,
                  "freshly replayed mixed report changed during preservation")

    fence()
    checked = relational.validate_mixed_relational_norm_v1(detached, request_raw,
        expected_report_sha256=expected_report_sha256, expected_request_sha256=expected_request_sha256)
    checked_raw = _wire(checked, MAX_MIXED_REPORT_BYTES)
    _need(checked_raw == report_raw and _wire(checked["request"], MAX_MIXED_REQUEST_BYTES)
          == _wire(request, MAX_MIXED_REQUEST_BYTES), "complete original mixed replay differs")
    fence()
    producers = _mixed_pins(owners, relational, checked)
    _need(_mixed_source_witness(checked["typed_expression"], checked["argument_roles"]) == witness
          and witness["count"] == checked["counts"]["nodes"]
          and witness["extension_count"] == checked["counts"]["extension_payloads"],
          "complete independent mixed witness/count replay differs")
    expression = checked["typed_expression"]
    source_value = _counted_json_value({"typed_expression": expression,
                                      "argument_roles": checked["argument_roles"]})
    renderer_value = _counted_json_value(checked["renderer_ast"])
    semantics = MIXED_SEMANTICS
    instance = MIXED_PROJECT_ROOT + ".Instance" + _sha(_wire({
        "profile": selected_profile, "report_sha256": expected_report_sha256,
        "request_sha256": expected_request_sha256, "semantics_sha256": _sha(semantics.encode()),
        **source_identity,
    }, MAX_RECORD_BYTES))
    modules = [MIXED_PROJECT_ROOT + ".Prelude", MIXED_PROJECT_ROOT + ".Semantics", instance, MIXED_PROJECT_ROOT]
    imports = {modules[0]: [], modules[1]: [modules[0]], instance: [modules[1]], MIXED_PROJECT_ROOT: [instance]}
    suffixes = ["mixed_typed_value_exact", "mixed_renderer_value_exact", "mixed_ast_closed",
                "mixed_denotation_matches_lowering", "mixed_role_denotation_matches_lowering"]
    header = " ".join(witness[key] for key in ("expression_id", "signature_id", "content_digest"))
    body = (checked["lean_body"]
        + "\n\nnoncomputable def typedMixedAst : MixedFormula := " + witness["source"]
        + "\nnoncomputable def mixedSortOrder : List CountedSort := " + witness["sorts"]
        + "\nnoncomputable def mixedPredicateDeclarations : List MixedPredicate := " + witness["predicates"]
        + "\nnoncomputable def mixedArgumentRoles : List MixedRoleRow := " + witness["roles"]
        + "\nnoncomputable def actualMixedSourceValue : NativeValue := " + source_value
        + "\nnoncomputable def actualMixedRendererValue : NativeValue := " + renderer_value
        + "\nnoncomputable def typedMixedSourceValue : NativeValue := mixedSourceValue " + header
        + " mixedSortOrder mixedPredicateDeclarations mixedArgumentRoles typedMixedAst\n"
        + "\ntheorem mixed_typed_value_exact : typedMixedSourceValue = actualMixedSourceValue := by\n  rfl\n"
        + "#print axioms mixed_typed_value_exact\n"
        + "theorem mixed_renderer_value_exact : mixedRendererValue typedMixedAst = actualMixedRendererValue := by\n  rfl\n"
        + "#print axioms mixed_renderer_value_exact\n"
        + "theorem mixed_ast_closed : mixedWellFormed mixedSortOrder mixedPredicateDeclarations mixedArgumentRoles typedMixedAst = true := by\n  decide\n"
        + "#print axioms mixed_ast_closed\n"
        + "theorem mixed_denotation_matches_lowering {Object EventFrame TimeFrame : Type}\n"
        + "    (i : Interpretation (MixedEntity Object EventFrame TimeFrame) Unit) (t : Nat) :\n"
        + "    mixedDenote i typedMixedAst emptyCountedEnvironment t ↔ formula i t := by\n"
        + "  exact Iff.intro (fun h => h) (fun h => h)\n"
        + "#print axioms mixed_denotation_matches_lowering\n"
        + "theorem mixed_role_denotation_matches_lowering {Object EventFrame TimeFrame : Type}\n"
        + "    (base : Interpretation (MixedEntity Object EventFrame TimeFrame) Unit)\n"
        + "    (atoms : String → List (String × MixedEntity Object EventFrame TimeFrame) → Nat → Prop) (t : Nat) :\n"
        + "    mixedRoleDenote base atoms mixedArgumentRoles typedMixedAst emptyCountedEnvironment t ↔\n"
        + "      formula (mixedRoleInterpretation base atoms mixedArgumentRoles) t := by\n"
        + "  exact Iff.intro (fun h => h) (fun h => h)\n"
        + "#print axioms mixed_role_denotation_matches_lowering\n")
    inputs = {"schema": MIXED_INPUT_SCHEMA, "profile": selected_profile, **source_identity,
        "mixed_report": checked, "mixed_report_sha256": expected_report_sha256,
        "original_request_raw_utf8": request_raw.decode("utf-8"),
        "original_request_sha256": expected_request_sha256}
    files = {
        "lakefile.toml": 'name = "legal_native_ast_preservation"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = ["LegalMixedRelationalAstPreservation"]\n',
        "lean-toolchain": toolchain + "\n",
        "preservation-inputs.json": _wire(inputs, MAX_PROJECT_BYTES).decode("utf-8") + "\n",
        modules[0].replace(".", "/") + ".lean": _file(MIXED_PROJECT_ROOT, [], emitter.PRELUDE),
        modules[1].replace(".", "/") + ".lean": _file(MIXED_PROJECT_ROOT, imports[modules[1]], semantics),
        instance.replace(".", "/") + ".lean": _file(instance, imports[instance], body),
        MIXED_PROJECT_ROOT + ".lean": "import " + instance + "\n",
    }
    _need(len(files) == MAX_FILES and len(set(modules)) == MAX_MODULES
          and sum(len(text.encode("utf-8")) for text in files.values()) <= MAX_PROJECT_BYTES,
          "complete mixed preservation project exceeds original bounds")
    for module in modules:
        _need(re.findall(r"(?m)^import ([A-Za-z][A-Za-z0-9_.]*)$", files[module.replace(".", "/") + ".lean"])
              == imports[module], "exact closed mixed preservation imports required")
    fence()
    manifest = contracts.seal_record({
        "schema": SCHEMA, "profile": selected_profile, "toolchain": toolchain, "target": "legal", "family": "tdfol", **source_identity,
        "mixed_report_sha256": expected_report_sha256, "original_request_sha256": expected_request_sha256,
        "typed_expression_sha256": checked["typed_expression_sha256"],
        "typed_expression_content_digest": expression["content_digest"],
        "argument_roles_sha256": _sha(_wire(checked["argument_roles"], MAX_RECORD_BYTES)),
        "renderer_ast_sha256": checked["renderer_ast_sha256"], "lean_body_sha256": _sha(checked["lean_body"].encode("utf-8")),
        "typed_ast_node_count": witness["count"], "typed_extension_payload_count": witness["extension_count"],
        "actual_typed_and_roles_lean_value_sha256": _sha(source_value.encode("utf-8")),
        "actual_renderer_lean_value_sha256": _sha(renderer_value.encode("utf-8")),
        "typed_source_lean_value_sha256": _sha(witness["source"].encode("utf-8")),
        "source_sort_order_lean_value_sha256": _sha(witness["sorts"].encode("utf-8")),
        "predicate_table_lean_value_sha256": _sha(witness["predicates"].encode("utf-8")),
        "ordered_roles_lean_value_sha256": _sha(witness["roles"].encode("utf-8")),
        "semantics_sha256": _sha(semantics.encode("utf-8")), "prelude_sha256": _sha(emitter.PRELUDE.encode("utf-8")),
        "expected_modules": modules, "module_imports": imports,
        "file_sha256": {name: _sha(text.encode("utf-8")) for name, text in sorted(files.items())},
        "theorems": [instance + "." + name for name in suffixes],
        "theorem_assumptions": [
            "Object, EventFrame and TimeFrame are independent arbitrary Type carriers and may be empty.",
            "Only predicate arguments receive disjoint tags; binders and same-sort equality use their raw source carriers.",
            "Ambient Nat time is independent of authored TimeFrame; O/P/F are distinct unconstrained parameters.",
            "Predicate role interpretations consume the exact ordered declared role/value pairs.",
            "Concrete source denotation and unchanged emitted formula must reduce independently; no extensionality or modal congruence is assumed.",
            "The five obligations are unexecuted during preparation; no generic compiler or source-prose theorem is asserted."],
        "support_profile": {
            "sorts": ["Object", "EventFrame", "TimeFrame"], "formula_sort": "Bool",
            "predicate_arity": [1, 8], "max_predicates": 64,
            "constructors": ["predicate", "equality", "not", "and", "or", "implies", "iff", "forall", "exists", "extension"],
            "modal_operators": ["O", "P", "F"], "modal_payload_schema": "legacy.deontic/v1",
            "max_ast_nodes": MAX_MIXED_AST_NODES, "max_ast_depth": MAX_MIXED_AST_DEPTH,
            "closed_only": True, "ordered_children_preserved": True, "same_sort_builtin_equality": True,
            "source_array_order_preserved": True, "source_carriers_may_be_empty": True,
            "native_TDFOL_route_used": False, "native_parser_roundtrip": False},
        "source_custody": {
            "scope": "complete original authored mixed report/request, typed expression, ordered roles and renderer replay",
            "original_request_raw_retained_in": "preservation-inputs.json/original_request_raw_utf8",
            "original_report_retained_in": "preservation-inputs.json/mixed_report",
            "original_source_bundle_replayed": False, "source_prose_to_ast_proved": False,
            "reviewed_admission_or_graph_replayed": False},
        "trust_boundary": [
            "Python JSON decoding, complete value reification, content-digest validation and SHA256 remain explicit custody assumptions.",
            "NativeValue mirrors supported serialized strings/null/arrays/objects; it is not a JSON byte parser or hash implementation.",
            "Full typed expression/role and renderer values are compared against independent constructor mirrors, not merely digest literals.",
            "MixedFormula/CountedSort/CountedVariable and three-carrier environments are proof witnesses, not a replacement production IR.",
            "The original mixed renderer owns the unchanged emitted formula; native TDFOL AST/parser support is not created.",
            "No source authenticity, statutory meaning, applicability, corpus admission, universal compiler correctness or model convergence follows."],
        "producer_pins": producers, "mixed_producer_pins": dict(checked["producer_pins"]),
        "preparation_only": True, "authority": dict(authority), "training_mask": 0, "evaluation_gold_mask": 0,
        "native_ast": None, "native_TDFOL_route_used": False, "native_parser_roundtrip": False,
        "typed_ast_value_preservation_proved": False, "renderer_ast_value_preservation_proved": False,
        "mixed_ast_denotation_preservation_proved": False, "ordered_role_denotation_preservation_proved": False,
        **false_flags,
    })
    preparation = NativeAstPreservationPreparation(_wire(manifest, MAX_RECORD_BYTES).decode("utf-8"), tuple(sorted(files.items())))
    preparation_sha256(preparation)
    fence()
    _need(_mixed_pins(owners, relational, checked) == producers,
          "mixed preservation producers changed during complete serialization")
    source_identity_fence()
    return preparation


def validate_mixed_relational_ast_preservation(preparation, report, request_raw: bytes, *,
        expected_preparation_sha256, expected_report_sha256, expected_request_sha256, toolchain,
        source_use_binding=None, expected_source_use_binding_sha256=None):
    """Replay complete original source/renderer inputs and the whole project."""
    _pin(expected_preparation_sha256, "complete mixed preservation preparation")
    _need(preparation_sha256(preparation) == expected_preparation_sha256,
          "independent complete mixed preservation pin differs")
    expected = prepare_mixed_relational_ast_preservation(report, request_raw,
        expected_report_sha256=expected_report_sha256, expected_request_sha256=expected_request_sha256,
        toolchain=toolchain, source_use_binding=source_use_binding,
        expected_source_use_binding_sha256=expected_source_use_binding_sha256)
    _need(expected == preparation and preparation_sha256(preparation) == expected_preparation_sha256,
          "mixed preservation differs from complete original regeneration")
    return expected


# Explicit opt-in extension. Legacy fixed-three profiles and their bytes above
# remain unchanged; this reuses their sorted value/environment proof witnesses.
PARAMETRIC_COUNTED_PROFILE = "typed-many-sorted-parametric-counted-preservation/v3"
PARAMETRIC_COUNTED_INPUT_SCHEMA = "legal-counted-threshold-ast-preservation-inputs/v3"
_PARAMETRIC_COUNTED_OPERATION_PINS = None

PARAMETRIC_COUNTED_SEMANTICS = (SEMANTICS + "\n\n" + _SORTED_PROOF_TYPES + r'''
inductive CountedThresholdFormula where
  | falsity (nodeId : String)
  | member (nodeId : String) (object event time : CountedVariable)
  | equality (nodeId : String) (left right : CountedVariable)
  | conjunction (nodeId : String) (left right : CountedThresholdFormula)
  | disjunction (nodeId : String) (left right : CountedThresholdFormula)
  | implication (nodeId : String) (left right : CountedThresholdFormula)
  | universal (nodeId name : String) (sort : CountedSort) (body : CountedThresholdFormula)

''' + _SORTED_PROOF_VALUES + r'''
def thresholdToTypedNodeValue : CountedThresholdFormula → NativeValue
  | .falsity nodeId => countedNodeValue nodeId "false" "" countedBoolSortValue [] []
  | .member nodeId object event time =>
      countedNodeValue nodeId "predicate" "Member" countedBoolSortValue
        [countedVariableValue object, countedVariableValue event, countedVariableValue time] []
  | .equality nodeId left right =>
      countedNodeValue nodeId "equality" "" countedBoolSortValue
        [countedVariableValue left, countedVariableValue right] []
  | .conjunction nodeId left right =>
      countedNodeValue nodeId "and" "" countedBoolSortValue
        [thresholdToTypedNodeValue left, thresholdToTypedNodeValue right] []
  | .disjunction nodeId left right =>
      countedNodeValue nodeId "or" "" countedBoolSortValue
        [thresholdToTypedNodeValue left, thresholdToTypedNodeValue right] []
  | .implication nodeId left right =>
      countedNodeValue nodeId "implies" "" countedBoolSortValue
        [thresholdToTypedNodeValue left, thresholdToTypedNodeValue right] []
  | .universal nodeId name sort body =>
      countedNodeValue nodeId "forall" "" countedBoolSortValue
        [thresholdToTypedNodeValue body] [countedBinderValue name sort]

def countedIdentityValue (space value : String) : NativeValue :=
  .object [("interface", .string "LogicIdentityNamespaces@1"),
    ("namespace", .string space), ("schema_version", .string "logic-identity-namespaces/v1"),
    ("value", .string value), ("version", .string "1.0.0")]

def countedSignatureValue (signatureId : String) : NativeValue :=
  .object [("family", countedIdentityValue "family" "first_order"),
    ("features", .array []), ("interface", .string "LogicSignature@1"),
    ("metadata", .object []), ("profile", countedIdentityValue "profile" "many_sorted"),
    ("schema_version", .string "syntax-logic-signature/v1"),
    ("signature_id", .string signatureId),
    ("sorts", .array [countedBoolSortValue, countedAtomicSortValue .object,
      countedAtomicSortValue .event, countedAtomicSortValue .time]),
    ("symbols", .array [.object [
      ("domain", .array [countedAtomicSortValue .object, countedAtomicSortValue .event,
        countedAtomicSortValue .time]),
      ("kind", .string "predicate"), ("metadata", .object []),
      ("name", .string "Member"), ("range", countedBoolSortValue),
      ("schema_version", .string "syntax-symbol-declaration/v1")]])]

def thresholdTypedExpressionValue (expressionId signatureId contentDigest : String)
    (ast : CountedThresholdFormula) : NativeValue :=
  .object [("content_digest", .string contentDigest), ("expression_id", .string expressionId),
    ("family", countedIdentityValue "family" "first_order"),
    ("interface", .string "TypedExpression@1"), ("metadata", .object []),
    ("profile", countedIdentityValue "profile" "many_sorted"),
    ("root", thresholdToTypedNodeValue ast),
    ("schema_version", .string "syntax-typed-expression/v1"),
    ("signature", countedSignatureValue signatureId)]

def thresholdVariableClosed (bound : List (CountedSort × String))
    (boundVariable : CountedVariable) : Bool :=
  bound.contains (boundVariable.sort, boundVariable.name)

def thresholdClosed (bound : List (CountedSort × String)) : CountedThresholdFormula → Bool
  | .falsity _ => true
  | .member _ object event time =>
      (object.sort == .object) && (event.sort == .event) && (time.sort == .time) &&
        thresholdVariableClosed bound object && thresholdVariableClosed bound event &&
        thresholdVariableClosed bound time
  | .equality _ left right =>
      (left.sort == .object) && (right.sort == .object) &&
        thresholdVariableClosed bound left && thresholdVariableClosed bound right
  | .conjunction _ left right => thresholdClosed bound left && thresholdClosed bound right
  | .disjunction _ left right => thresholdClosed bound left && thresholdClosed bound right
  | .implication _ left right => thresholdClosed bound left && thresholdClosed bound right
  | .universal _ name sort body => thresholdClosed ((sort, name) :: bound) body

''' + _SORTED_PROOF_ENVIRONMENT + r'''
def thresholdDenote {Object EventFrame TimeFrame : Type}
    (member : Object → EventFrame → TimeFrame → Prop) (ast : CountedThresholdFormula) :
    CountedEnvironment Object EventFrame TimeFrame → Prop :=
  CountedThresholdFormula.rec
    (fun _ _ => False)
    (fun _ object event time environment =>
      Option.casesOn (countedObjectValue environment object) False (fun o =>
        Option.casesOn (countedEventValue environment event) False (fun e =>
          Option.casesOn (countedTimeValue environment time) False (fun t => member o e t))))
    (fun _ left right environment =>
      Option.casesOn (countedObjectValue environment left) False (fun l =>
        Option.casesOn (countedObjectValue environment right) False (fun r => l = r)))
    (fun _ _ _ left right environment => left environment ∧ right environment)
    (fun _ _ _ left right environment => left environment ∨ right environment)
    (fun _ _ _ left right environment => left environment → right environment)
    (fun _ name sort _ child environment =>
      CountedSort.casesOn sort
        (∀ entity : Object, child (updateCountedObject environment name entity))
        (∀ frame : EventFrame, child (updateCountedEvent environment name frame))
        (∀ instant : TimeFrame, child (updateCountedTime environment name instant))) ast

-- Positive finite-index collision semantics, defined independently of AST syntax.
-- No finiteness, inhabitant or decidable equality is required for Object.
-- No equivalence with a negated injective-witness proposition is assumed.
def thresholdCollisionBound {Object EventFrame TimeFrame : Type}
    (maximum : Nat) (member : Object → EventFrame → TimeFrame → Prop) : Prop :=
  ∀ (event : EventFrame) (time : TimeFrame) (objects : Fin (maximum + 1) → Object),
    (∀ i : Fin (maximum + 1), member (objects i) event time) →
      ∃ i : Fin (maximum + 1), ∃ j : Fin (maximum + 1), i ≠ j ∧ objects i = objects j


universe u

def thresholdFinCases {n : Nat} {motive : Fin (n + 1) → Sort u}
    (zeroCase : motive ⟨0, Nat.zero_lt_succ n⟩)
    (succCase : ∀ i : Fin n, motive ⟨i.val + 1, Nat.succ_lt_succ i.isLt⟩)
    (index : Fin (n + 1)) : motive index :=
  match index with
  | ⟨0, _⟩ => zeroCase
  | ⟨Nat.succ k, bound⟩ => succCase ⟨k, Nat.lt_of_succ_lt_succ bound⟩
''')


PARAMETRIC_EXPANDED_CAPACITY_PROFILE = "counted-nat-expanded-capacity/v1"


def _parametric_counted_capacity(capacity_profile):
    if capacity_profile is None:
        return dict(max_nodes=MAX_AST_NODES, max_depth=MAX_AST_DEPTH,
                    max_bytes=131072, max_json_depth=64, max_json_items=20000)
    _need(type(capacity_profile) is str and capacity_profile == PARAMETRIC_EXPANDED_CAPACITY_PROFILE,
          "explicit recognized counted capacity profile required")
    return dict(max_nodes=1024, max_depth=128, max_bytes=1048576,
                max_json_depth=256, max_json_items=65536)


def _parametric_counted_dimensions(maximum, *, capacity_profile=None):
    """Check derived expansion size before allocating syntax or proof text."""
    capacities = _parametric_counted_capacity(capacity_profile)
    _need(type(maximum) is int and 0 <= maximum <= capacities["max_nodes"],
          "natural counted threshold exceeds existing preservation capacity")
    size, pairs = maximum + 1, maximum * (maximum + 1) // 2
    nodes = 9 if maximum == 0 else 2 * maximum * maximum + 8 * maximum + 7
    depth = 5 if maximum == 0 else max(size + pairs + 3, 2 * size + 3)
    _need(nodes <= capacities["max_nodes"] and depth <= capacities["max_depth"]
          and 2 * depth + 4 <= capacities["max_json_depth"]
          and 128 * nodes + 4096 <= capacities["max_json_items"]
          and (capacity_profile is None or 8192 + 512 * nodes <= capacities["max_bytes"]),
          "counted threshold expansion exceeds existing node/depth/JSON capacity")
    return nodes, depth


def _parametric_counted_source_syntax(root, maximum, *, capacity_profile=None):
    """Walk actual v3 constructors with independent finite resource bounds."""
    capacities = _parametric_counted_capacity(capacity_profile)
    expected_nodes, _ = _parametric_counted_dimensions(maximum, capacity_profile=capacity_profile)
    count, identifiers = 0, set()
    sorts = {"Object": "object", "EventFrame": "event", "TimeFrame": "time"}

    def sort(value, *, formula=False):
        _keys(value, {"arguments", "kind", "name", "schema_version"}, "counted typed sort")
        name = value["name"]
        _need(value["schema_version"] == "syntax-logic-sort/v1" and value["arguments"] == [],
              "exact atomic counted sort required")
        if formula:
            _need(name == "Bool" and value["kind"] == "bool", "counted formula Bool sort required")
            return "bool"
        _need(type(name) is str and name in sorts and value["kind"] == "atomic",
              "unsupported counted term/binder sort")
        return sorts[name]

    def node(value, depth):
        nonlocal count
        _keys(value, {"arguments", "binders", "kind", "metadata", "node_id", "schema_version",
                      "sort", "symbol"}, "counted typed node")
        _need(type(value["node_id"]) is str and 0 < len(value["node_id"]) <= 512
              and value["node_id"] not in identifiers, "distinct bounded counted node IDs required")
        count += 1
        identifiers.add(value["node_id"])
        _need(count <= capacities["max_nodes"] and depth <= capacities["max_depth"], "bounded counted threshold AST required")
        _need(value["schema_version"] == "syntax-logic-node/v1" and value["metadata"] == {}
              and type(value["symbol"]) is str and type(value["arguments"]) is list
              and type(value["binders"]) is list, "exact unannotated counted node required")

    def variable(value, environment, depth, expected_sort):
        node(value, depth)
        _need(value["kind"] == "variable" and value["arguments"] == [] and value["binders"] == [],
              "only bound counted variables supported")
        found, name = sort(value["sort"]), value["symbol"]
        _need(found == expected_sort and (found, name) in environment,
              "free, wrongly sorted or reordered counted variable")
        return "⟨" + _counted_string(value["node_id"]) + ", " + _counted_string(name) + ", ." + found + "⟩"

    def formula(value, environment, depth):
        node(value, depth)
        sort(value["sort"], formula=True)
        kind, arguments = value["kind"], value["arguments"]
        prefix = "(." + {"false": "falsity", "predicate": "member", "equality": "equality",
                           "and": "conjunction", "or": "disjunction", "implies": "implication",
                           "forall": "universal"}.get(kind, "unsupported")
        prefix += " " + _counted_string(value["node_id"]) + " "
        if kind == "predicate":
            _need(value["symbol"] == "Member" and value["binders"] == [] and len(arguments) == 3,
                  "ordered ternary Member required")
            return prefix + " ".join(variable(argument, environment, depth + 1, expected)
                for argument, expected in zip(arguments, ("object", "event", "time"), strict=True)) + ")"
        _need(value["symbol"] == "", "unexpected counted connective/equality symbol")
        if kind == "false":
            _need(value["binders"] == [] and arguments == [], "exact counted False required")
            return prefix.rstrip() + ")"
        if kind == "equality":
            _need(value["binders"] == [] and len(arguments) == 2, "binary built-in object equality required")
            return prefix + " ".join(variable(argument, environment, depth + 1, "object")
                                      for argument in arguments) + ")"
        if kind in {"and", "or", "implies"}:
            _need(value["binders"] == [] and len(arguments) == 2, "binary counted connective required")
            return prefix + formula(arguments[0], environment, depth + 1) + " " + formula(
                arguments[1], environment, depth + 1) + ")"
        if kind == "forall":
            _need(len(value["binders"]) == 1 and len(arguments) == 1, "single counted universal binder required")
            binder = value["binders"][0]
            _keys(binder, {"name", "schema_version", "sort"}, "counted typed binder")
            _need(binder["schema_version"] == "syntax-binder/v1" and type(binder["name"]) is str,
                  "exact counted binder required")
            found, name = sort(binder["sort"]), binder["name"]
            _need(not any(name == bound_name for _, bound_name in environment),
                  "counted lexical binder shadowing unsupported")
            return prefix + _counted_string(name) + " ." + found + " " + formula(
                arguments[0], ((found, name), *environment), depth + 1) + ")"
        raise ValueError("unsupported counted threshold preservation constructor: " + str(kind))

    result = formula(root, (), 0)
    _need(count == expected_nodes, "exact complete threshold witness node count required")
    return result, count


def _parametric_counted_pins(owners, counted, checked):
    """Keep opt-in threshold replay pins separate from the fixed-v1 lane."""
    global _PARAMETRIC_COUNTED_OPERATION_PINS
    pins = dict(_pins(owners))
    supplied = checked["producer_pins"]
    _need(type(supplied) is dict and 1 <= len(supplied) <= 32,
          "bounded current counted producer pins required")
    for name, expected in supplied.items():
        _pin(expected, "current counted producer")
        path = Path(name)
        _need(path.is_absolute() and str(path.resolve()) == name
              and _sha(path.read_bytes()) == expected, "current counted producer bytes differ")
        pins[name] = expected
    path = Path(counted.__file__).resolve()
    pins[str(path)] = _sha(path.read_bytes())
    if _PARAMETRIC_COUNTED_OPERATION_PINS is None:
        _PARAMETRIC_COUNTED_OPERATION_PINS = dict(pins)
    _need(pins == _PARAMETRIC_COUNTED_OPERATION_PINS,
          "counted threshold preservation owners changed during operation")
    return pins


def _parametric_counted_collision_proof(maximum, *, capacity_profile=None):
    """Generate an unexecuted constructive, per-instance Fin proof candidate.

    Direct constructor elimination enumerates finite indices; Object remains an
    arbitrary type. The only decide terms compare closed finite indices.
    No proposition asserting a cardinality or equivalence is supplied as input.
    """
    _parametric_counted_dimensions(maximum, capacity_profile=capacity_profile)
    size = maximum + 1
    variables = ["x" + str(i) for i in range(size)]
    pairs = [(i, j) for i in range(size) for j in range(i + 1, size)]

    def fin(i):
        proof = "Nat.le.refl"
        for _ in range(size - i - 1):
            proof = "(Nat.le.step " + proof + ")"
        return "(⟨" + str(i) + ", " + proof + "⟩ : Fin " + str(size) + ")"

    def fold_and(values):
        result = values[0]
        for value in values[1:]:
            result = "(And.intro (" + result + ") (" + value + "))"
        return result

    def and_projection(value, index, length):
        if length == 1:
            return value
        if index == length - 1:
            return "(And.right " + value + ")"
        return and_projection("(And.left " + value + ")", index, length - 1)

    def or_intro(index, length, value):
        if length == 1:
            return value
        if index == length - 1:
            return "(Or.inr (" + value + "))"
        return "(Or.inl (" + or_intro(index, length - 1, value) + "))"

    def cases(branches, name="index", motive=lambda _index: "Object", offset=0):
        if not branches:
            return "(fun (" + name + " : Fin 0) => Fin.elim0 " + name + ")"
        size_here = len(branches)
        argument = name + "Value"
        lifted = argument
        if offset:
            proof = "(" + argument + ").isLt"
            for _ in range(offset):
                proof = "(Nat.succ_lt_succ " + proof + ")"
            lifted = "(⟨(" + argument + ").val + " + str(offset) + ", " + proof + (
                "⟩ : Fin " + str(size_here + offset) + ")")
        annotation = "(motive := fun (" + argument + " : Fin " + str(size_here) + (
            ") => " + motive(lifted) + ")")
        return "(fun (" + name + " : Fin " + str(size_here) + ") => thresholdFinCases " + (
            annotation + " (" + branches[0] + ") " + cases(
                branches[1:], name + "Tail", motive, offset + 1) + " " + name + ")")

    def witness(index, equality):
        left, right = pairs[index]
        return "(Exists.intro " + fin(left) + " (Exists.intro " + fin(right) + " (And.intro " + (
            "(by decide : " + fin(left) + " ≠ " + fin(right) + ")") + " (" + equality + "))))"

    def eliminate(value, length):
        if length == 1:
            return witness(0, value)
        return "(Or.elim (" + value + ") (fun earlier => " + eliminate("earlier", length - 1) + (
            ") (fun equality => " + witness(length - 1, "equality") + "))")

    offered = "h event time " + " ".join("(objects " + fin(i) + ")" for i in range(size))
    premise = fold_and(["members " + fin(i) for i in range(size)])
    forward = ("(fun h event time objects members => " +
        ("False.elim (" + offered + " (" + premise + "))" if maximum == 0 else
         eliminate(offered + " (" + premise + ")", len(pairs))) + ")")
    conclusion = "False"
    for index, (left, right) in enumerate(pairs):
        equality = variables[left] + " = " + variables[right]
        conclusion = equality if index == 0 else "(" + conclusion + " ∨ " + equality + ")"

    def pair_type(left, right):
        return "((" + left + ") ≠ (" + right + ") ∧ objects (" + left + ") = objects (" + (
            right + ")) → " + conclusion)

    object_function = cases(variables)
    members_function = cases([and_projection("membership", i, size) for i in range(size)],
        "memberIndex", lambda index: "member (objects (" + index + ")) event time")
    branches = []
    for i in range(size):
        row = []
        for j in range(size):
            if i == j:
                result = "False.elim (And.left pair (Eq.refl _))"
            else:
                index = pairs.index((min(i, j), max(i, j)))
                equality = "And.right pair" if i < j else "Eq.symm (And.right pair)"
                result = or_intro(index, len(pairs), equality)
            row.append("(fun pair => " + result + ")")
        branches.append(cases(row, "rightIndex",
            lambda right, left=i: pair_type(fin(left), right)))
    handlers = cases(branches, "leftIndex",
        lambda left: "∀ (j : Fin " + str(size) + "), " + pair_type(left, "j"))
    backward = ("(fun h event time " + " ".join(variables) + " membership =>\n"
        + "    let objects : Fin " + str(size) + " → Object := " + object_function + "\n"
        + "    let members : ∀ i : Fin " + str(size) + ", member (objects i) event time := " + members_function + "\n"
        + "    let conclude : ∀ (i j : Fin " + str(size) + "), (i ≠ j ∧ objects i = objects j) → "
        + conclusion + " := " + handlers + "\n"
        + "    Exists.elim (h event time objects members) (fun i remaining =>\n"
        + "      Exists.elim remaining (fun j pair => conclude i j pair)))")
    return ("theorem threshold_collision_equivalence {Object EventFrame TimeFrame : Type}\n"
        + "    (member : Object → EventFrame → TimeFrame → Prop) :\n"
        + "    countedAtMostThreshold member ↔ thresholdCollisionBound " + str(maximum) + " member := by\n"
        + "  exact Iff.intro\n    " + forward + "\n    " + backward + "\n"
        + "#print axioms threshold_collision_equivalence\n")


def prepare_counted_threshold_ast_preservation(report, request_raw: bytes, *,
        expected_report_sha256, expected_request_sha256, toolchain):
    """Prepare v3 exact-value/denotation obligations; perform no native build."""
    _pin(expected_report_sha256, "complete counted threshold report")
    _pin(expected_request_sha256, "complete counted threshold request")
    capacity_profile = report.get("capacity_profile") if type(report) is dict else None
    capacities = _parametric_counted_capacity(capacity_profile)
    def wire(value, maximum):
        return _wire(value, maximum, max_json_depth=(96 if capacity_profile is None else 256))
    report_raw = wire(report, MAX_RECORD_BYTES)
    _need(_sha(report_raw) == expected_report_sha256, "independent counted threshold report pin differs")
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_RECORD_BYTES // 8
          and _sha(request_raw) == expected_request_sha256, "independent bounded counted threshold request pin differs")
    request = _parse(request_raw, MAX_RECORD_BYTES // 8)
    _need(type(request) is dict and type(report) is dict, "ordinary complete counted threshold request/report required")
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain) is not None,
          "exact version-pinned Lean toolchain required")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "native AST preservation owner changed since import")
    from . import legal_counted_frame_threshold_v2 as counted
    checked = counted.validate_counted_threshold_v3(report, request_raw,
        expected_report_sha256=expected_report_sha256, expected_request_sha256=expected_request_sha256)
    _need(checked["request"] == request and checked["profile"] == counted.PARAMETRIC_PROFILE
          and checked.get("source_binding") is None and checked.get("native_TDFOL_route_used", False) is False,
          "exact authored parametric counted replay required")
    _need(type(checked["authority"]) is dict and not any(checked["authority"].values()),
          "parametric counted preparation grants no authority")
    _need(checked.get("capacity_profile") == capacity_profile
          and request.get("capacity_profile") == capacity_profile,
          "counted capacity request/report commitment differs")
    maximum = checked["maximum"]
    owners = _owners()
    _, emitter, contracts = owners
    producers = _parametric_counted_pins(owners, counted, checked)
    expression = checked["typed_expression"]
    typed, count = _parametric_counted_source_syntax(expression["root"], maximum, capacity_profile=capacity_profile)
    actual, semantics = _counted_json_value(expression), PARAMETRIC_COUNTED_SEMANTICS
    instance = COUNTED_PROJECT_ROOT + ".Instance" + _sha(wire({
        "profile": PARAMETRIC_COUNTED_PROFILE, "report_sha256": expected_report_sha256,
        "request_sha256": expected_request_sha256, "semantics_sha256": _sha(semantics.encode()),
    }, MAX_RECORD_BYTES))
    modules = [COUNTED_PROJECT_ROOT + ".Prelude", COUNTED_PROJECT_ROOT + ".Semantics", instance, COUNTED_PROJECT_ROOT]
    imports = {modules[0]: [], modules[1]: [modules[0]], instance: [modules[1]], COUNTED_PROJECT_ROOT: [instance]}
    reconstructed = ("thresholdTypedExpressionValue " + _counted_string(expression["expression_id"]) + " "
        + _counted_string(expression["signature"]["signature_id"]) + " "
        + _counted_string(expression["content_digest"]) + " typedCountedThresholdAst")
    names = ["threshold_value_exact", "threshold_ast_closed", "threshold_denotation_matches_lowering",
             "threshold_collision_equivalence"]
    body = (checked["lean_body"] + "\n\ndef actualTypedValue : NativeValue := " + actual
        + "\ndef typedCountedThresholdAst : CountedThresholdFormula := " + typed
        + "\ndef reconstructedTypedValue : NativeValue := " + reconstructed
        + "\ntheorem threshold_value_exact : reconstructedTypedValue = actualTypedValue := by\n  rfl\n"
        + "#print axioms threshold_value_exact\n"
        + "theorem threshold_ast_closed : thresholdClosed [] typedCountedThresholdAst = true := by\n  decide\n"
        + "#print axioms threshold_ast_closed\n"
        + "theorem threshold_denotation_matches_lowering {Object EventFrame TimeFrame : Type}\n"
        + "    (member : Object → EventFrame → TimeFrame → Prop) :\n"
        + "    thresholdDenote member typedCountedThresholdAst emptyCountedEnvironment ↔ countedAtMostThreshold member := by\n"
        + "  exact Iff.intro (fun h => h) (fun h => h)\n#print axioms threshold_denotation_matches_lowering\n"
        + _parametric_counted_collision_proof(maximum, capacity_profile=capacity_profile))
    inputs = {"schema": PARAMETRIC_COUNTED_INPUT_SCHEMA, "profile": PARAMETRIC_COUNTED_PROFILE,
        "counted_report": checked, "counted_report_sha256": expected_report_sha256,
        "original_request_raw_utf8": request_raw.decode("utf-8"), "original_request_sha256": expected_request_sha256,
        "typed_expression_sha256": checked["typed_expression_sha256"],
        "original_counted_lean_body_sha256": checked["lean_body_sha256"], "maximum": maximum}
    files = {
        "lakefile.toml": 'name = "legal_native_ast_preservation"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = ["LegalCountedAstPreservation"]\n',
        "lean-toolchain": toolchain + "\n",
        "preservation-inputs.json": wire(inputs, 4 * MAX_RECORD_BYTES).decode() + "\n",
        modules[0].replace(".", "/") + ".lean": _file(COUNTED_PROJECT_ROOT, [], emitter.PRELUDE),
        modules[1].replace(".", "/") + ".lean": _file(COUNTED_PROJECT_ROOT, imports[modules[1]], semantics),
        instance.replace(".", "/") + ".lean": _file(instance, imports[instance], body),
        COUNTED_PROJECT_ROOT + ".lean": "import " + instance + "\n"}
    if capacity_profile is not None:
        instance_path = instance.replace(".", "/") + ".lean"
        import_prefix = "".join("import " + module + "\n" for module in imports[instance])
        _need(files[instance_path].startswith(import_prefix),
              "counted instance imports changed before finite native capacity selection")
        files[instance_path] = (import_prefix + "set_option maxRecDepth 8192\n"
                                + files[instance_path][len(import_prefix):])
    _need(len(files) == MAX_FILES and len(set(modules)) == MAX_MODULES
          and sum(len(text.encode()) for text in files.values()) <= MAX_PROJECT_BYTES,
          "complete counted threshold preservation project exceeds existing bounds")
    manifest = contracts.seal_record({
        "schema": SCHEMA, "profile": PARAMETRIC_COUNTED_PROFILE, "toolchain": toolchain, "target": "legal",
        "family": "first_order", "typed_profile": "many_sorted", "maximum": maximum,
        "counted_report_sha256": expected_report_sha256, "original_request_sha256": expected_request_sha256,
        "typed_expression_sha256": checked["typed_expression_sha256"],
        "typed_expression_content_digest": expression["content_digest"], "lean_body_sha256": checked["lean_body_sha256"],
        "actual_typed_lean_value_sha256": _sha(actual.encode()), "typed_counted_lean_value_sha256": _sha(typed.encode()),
        "semantics_sha256": _sha(semantics.encode()), "prelude_sha256": _sha(emitter.PRELUDE.encode()),
        **({"capacity_profile": capacity_profile} if capacity_profile is not None else {}),
        "typed_ast_node_count": count, "typed_predicates": ["Member"],
        "expected_modules": modules, "module_imports": imports,
        "file_sha256": {name: _sha(text.encode()) for name, text in sorted(files.items())},
        "theorems": [instance + "." + name for name in names],
        "theorem_assumptions": [
            "Object, EventFrame and TimeFrame are arbitrary Type carriers, not assumed inhabited or finite.",
            "Member is an arbitrary ternary Prop relation in ordered object,event,time roles.",
            "Object equality is Lean equality; only closed Fin-index comparisons use decide.",
            "The positive Fin(maximum+1) collision specification is defined independently of the typed AST.",
            "No injective-witness negation equivalence, desired bound or preservation result is assumed.",
            "Physical identity/schema/digest fields are preserved as values, not rehashed in Lean.",
            "All four obligations, elaboration and axiom reports are unexecuted and unqualified."],
        "support_profile": {"source_owner": "legal_counted_frame_threshold_v2", "threshold_domain": "Nat subject to unchanged resource admission",
            "maximum": maximum, "sorts": ["Object", "EventFrame", "TimeFrame"], "formula_sort": "Bool",
            "authored_sort_names_generalized": False, "arbitrary_carrier_types": True,
            "predicate": "Member", "predicate_arity": 3, "ordered_argument_roles": ["object", "event", "time"],
            "operators": ["False", "∧", "∨", "→", "="], "quantifiers": ["∀"],
            "closed_only": True, "named_lexical_shadowing": False, "event_time_policy": "per_event_and_time",
            "native_TDFOL_route_used": False, "max_ast_nodes": capacities["max_nodes"], "max_ast_depth": capacities["max_depth"],
            "max_project_bytes": MAX_PROJECT_BYTES, "max_json_depth": capacities["max_json_depth"], "max_json_items": capacities["max_json_items"]},
        "proof_candidate": {"status": "UNQUALIFIED_NOT_EXECUTED", "native_execution": False,
            "kernel_checked": False, "extra_axioms_requested": [],
            "remaining": "Actual Lean syntax/elaboration, four theorem proofs and their exact axiom reports require the existing admitted native owner."},
        "source_custody": {"scope": "whole authored v3 threshold request/report and unchanged owner Lean definition replay",
            "original_request_raw_retained_in": "preservation-inputs.json/original_request_raw_utf8",
            "original_source_bundle_replayed": False, "source_prose_to_ast_proved": False},
        "producer_pins": producers, "counted_producer_pins": checked["producer_pins"],
        "preparation_only": True, "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        **FALSE_FLAGS})
    _need(wire(report, MAX_RECORD_BYTES) == report_raw, "caller counted threshold report changed during preservation preparation")
    _need(_parametric_counted_pins(owners, counted, checked) == producers,
          "counted threshold preservation owners changed during preparation")
    preparation = NativeAstPreservationPreparation(wire(manifest, MAX_RECORD_BYTES).decode(), tuple(sorted(files.items())))
    preparation_sha256(preparation)
    return preparation


def validate_counted_threshold_ast_preservation(preparation, report, request_raw: bytes, *,
        expected_preparation_sha256, expected_report_sha256, expected_request_sha256, toolchain):
    """Require all three commitments and whole original v3 regeneration."""
    _pin(expected_preparation_sha256, "complete counted threshold preservation preparation")
    _need(preparation_sha256(preparation) == expected_preparation_sha256,
          "independent complete counted threshold preservation pin differs")
    expected = prepare_counted_threshold_ast_preservation(report, request_raw,
        expected_report_sha256=expected_report_sha256, expected_request_sha256=expected_request_sha256,
        toolchain=toolchain)
    _need(expected == preparation and preparation_sha256(preparation) == expected_preparation_sha256,
          "counted threshold preservation differs from complete original regeneration")
    return expected


# Explicit positive-cardinality profile; preceding preservation APIs stay exact.
QUANTITY_COUNTED_PROFILE = "typed-many-sorted-positive-quantity-preservation/v4"
QUANTITY_COUNTED_INPUT_SCHEMA = "legal-counted-quantity-preservation-inputs/v4"

QUANTITY_FINITE_SEMANTICS = r"""
def quantityFiniteAtLeast {Object EventFrame TimeFrame : Type}
    (n : Nat) (member : Object → EventFrame → TimeFrame → Prop) : Prop :=
  ∀ event time, ∃ objects : Fin n → Object,
    Function.Injective objects ∧ ∀ index, member (objects index) event time

def quantityFiniteExactly {Object EventFrame TimeFrame : Type}
    (n : Nat) (member : Object → EventFrame → TimeFrame → Prop) : Prop :=
  ∀ event time, ∃ objects : Fin n → Object,
    Function.Injective objects ∧
      ∀ x, member x event time ↔ ∃ index, objects index = x

def quantityInterpretation {Object EventFrame TimeFrame : Type}
    (member : Object → EventFrame → TimeFrame → Prop)
    (base : Interpretation (MixedEntity Object EventFrame TimeFrame) Unit) :
    Interpretation (MixedEntity Object EventFrame TimeFrame) Unit :=
  { base with atom := fun name values atTime =>
      if name = "Member" then
        (List.casesOn values
          False
          (fun first rest1 =>
            (Sum.casesOn first
              (fun _ => False)
              (fun firstPayload =>
                (Sum.casesOn firstPayload
                  (fun object =>
                    (List.casesOn rest1
                      False
                      (fun second rest2 =>
                        (Sum.casesOn second
                          (fun _ => False)
                          (fun secondPayload =>
                            (Sum.casesOn secondPayload
                              (fun _ => False)
                              (fun secondFrames =>
                                (Sum.casesOn secondFrames
                                  (fun event =>
                                    (List.casesOn rest2
                                      False
                                      (fun third rest3 =>
                                        (Sum.casesOn third
                                          (fun _ => False)
                                          (fun thirdPayload =>
                                            (Sum.casesOn thirdPayload
                                              (fun _ => False)
                                              (fun thirdFrames =>
                                                (Sum.casesOn thirdFrames
                                                  (fun _ => False)
                                                  (fun time =>
                                                    (List.casesOn rest3
                                                      (member object event time)
                                                      (fun _ _ => False)))))))))))
                                  (fun _ => False)))))))))
                  (fun _ => False))))))
      else base.atom name values atTime }
"""


def _quantity_native_budget(quantity, threshold):
    """Independent finite resource preflight, before owners or proof expansion."""
    _need(type(quantity) is str and quantity in ("at_least", "exactly")
          and type(threshold) is int and 0 <= threshold <= MAX_MIXED_AST_NODES,
          "explicit positive quantity and natural bounded representation required")
    n, pairs = threshold, threshold * (threshold - 1) // 2
    if n == 0:
        nodes, depth = (12, 5) if quantity == "at_least" else (8, 5)
    else:
        leaves = n + pairs
        nodes, depth = 6 * n + 5 * pairs + 1, n + 2 + leaves
        if quantity == "exactly":
            nodes += 4 * n + 6
            depth = n + 3 + max(leaves, n + 2)
    proof_bound = 65536 + 8192 * (n + 1) ** 3
    _need(nodes <= MAX_MIXED_AST_NODES and depth <= MAX_MIXED_AST_DEPTH
          and 8192 + 512 * nodes <= 131072 and 2 * depth + 4 <= 64
          and 128 * nodes + 4096 <= 20000 and proof_bound <= MAX_PROJECT_BYTES,
          "quantity proof expansion exceeds existing node/depth/byte/JSON capacity")
    return {"nodes": nodes, "depth": depth, "proof_bytes_upper_bound": proof_bound}


def _quantity_lean_expansion(quantity, threshold):
    """Independent proof-witness expansion; never a production lowering route."""
    _quantity_native_budget(quantity, threshold)
    n = threshold
    def fold(values, operator):
        _need(bool(values), "nonempty quantity proof connective required")
        result = values[0]
        for value in values[1:]:
            result = "(" + result + " " + operator + " " + value + ")"
        return result
    if n == 0:
        body = ("∀ (zeroWitness : Object), member zeroWitness event time → member zeroWitness event time"
                if quantity == "at_least" else
                "∀ (zeroWitness : Object), ¬ member zeroWitness event time")
    else:
        names = ["x" + str(i) for i in range(n)]
        leaves = ["member " + name + " event time" for name in names]
        leaves += ["(¬ (" + names[i] + " = " + names[j] + "))"
                   for i in range(n) for j in range(i + 1, n)]
        if quantity == "exactly":
            leaves.append("(∀ (candidate : Object), member candidate event time ↔ "
                + fold(["candidate = " + name for name in names], "∨") + ")")
        body = "∃ (" + " ".join(names) + " : Object), " + fold(leaves, "∧")
    return ("def quantityExpansion {Object EventFrame TimeFrame : Type}\n"
        "    (member : Object → EventFrame → TimeFrame → Prop) : Prop :=\n"
        "  ∀ (event : EventFrame) (time : TimeFrame), " + body + "\n")


def _quantity_extra_semantics():
    """Reuse the already selected direct constructor-based finite eliminator."""
    marker = "\nuniverse u\n\ndef thresholdFinCases"
    _need(PARAMETRIC_COUNTED_SEMANTICS.count(marker) == 1
          and "def thresholdFinCases" not in MIXED_SEMANTICS,
          "exact existing direct Fin helper selection required")
    direct = PARAMETRIC_COUNTED_SEMANTICS[PARAMETRIC_COUNTED_SEMANTICS.index(marker):]
    return direct + "\n" + QUANTITY_FINITE_SEMANTICS


def _quantity_theorem_types(quantity, threshold):
    _quantity_native_budget(quantity, threshold)
    finite = "quantityFiniteAtLeast" if quantity == "at_least" else "quantityFiniteExactly"
    return {
        "quantity_lowering_matches_expansion":
            "formula (quantityInterpretation member base) t ↔ quantityExpansion member",
        "quantity_finite_equivalence":
            "quantityExpansion member ↔ " + finite + " " + str(threshold) + " member",
        "quantity_denotation_matches_finite":
            "mixedDenote (quantityInterpretation member base) typedMixedAst emptyCountedEnvironment t ↔ "
            + finite + " " + str(threshold) + " member"}


def _quantity_cardinality_obligations(quantity, threshold):
    budget = _quantity_native_budget(quantity, threshold)
    finite = "quantityFiniteAtLeast" if quantity == "at_least" else "quantityFiniteExactly"
    text = (_quantity_lean_expansion(quantity, threshold)
        + "\ntheorem quantity_lowering_matches_expansion {Object EventFrame TimeFrame : Type}\n"
          "    (member : Object → EventFrame → TimeFrame → Prop)\n"
          "    (base : Interpretation (MixedEntity Object EventFrame TimeFrame) Unit) (t : Nat) :\n"
          "    formula (quantityInterpretation member base) t ↔ quantityExpansion member := by\n"
          "  exact Iff.intro (fun h => h) (fun h => h)\n"
          "#print axioms quantity_lowering_matches_expansion\n"
        + _quantity_finite_equivalence_proof(quantity, threshold)
        + "\ntheorem quantity_denotation_matches_finite {Object EventFrame TimeFrame : Type}\n"
          "    (member : Object → EventFrame → TimeFrame → Prop)\n"
          "    (base : Interpretation (MixedEntity Object EventFrame TimeFrame) Unit) (t : Nat) :\n"
          "    mixedDenote (quantityInterpretation member base) typedMixedAst emptyCountedEnvironment t ↔ "
        + finite + " " + str(threshold) + " member := by\n"
          "  exact Iff.trans (mixed_denotation_matches_lowering (quantityInterpretation member base) t)\n"
          "    (Iff.trans (quantity_lowering_matches_expansion member base t) (quantity_finite_equivalence member))\n"
          "#print axioms quantity_denotation_matches_finite\n")
    _need(len(text.encode("utf-8")) <= budget["proof_bytes_upper_bound"],
          "complete quantity proof candidate exceeds its preflight")
    return text


def _quantity_preparation_inputs(report, request_raw, expected_report_sha256, expected_request_sha256):
    _pin(expected_report_sha256, "complete positive quantity report")
    _pin(expected_request_sha256, "original positive quantity request")
    raw = _wire(report, MAX_RECORD_BYTES)
    _need(_sha(raw) == expected_report_sha256 and type(request_raw) is bytes
          and 0 < len(request_raw) <= 131072 and _sha(request_raw) == expected_request_sha256,
          "independent complete quantity commitments required")
    request = _parse(request_raw, 131072)
    _need(type(request) is dict and "quantity" in request and "threshold" in request,
          "explicit quantity declaration required")
    _quantity_native_budget(request["quantity"], request["threshold"])
    return raw, request


def prepare_counted_quantity_ast_preservation(report, request_raw: bytes, *,
        expected_report_sha256, expected_request_sha256, toolchain):
    """Extend the genuine mixed preparation with constructive finite contracts."""
    report_raw, request = _quantity_preparation_inputs(report, request_raw,
        expected_report_sha256, expected_request_sha256)
    _need(type(toolchain) is str and _TOOLCHAIN.fullmatch(toolchain) is not None,
          "exact version-pinned Lean toolchain required")
    from . import legal_counted_frame_threshold_v2 as counted
    checked = counted.validate_counted_quantity_v4(report, request_raw,
        expected_report_sha256=expected_report_sha256, expected_request_sha256=expected_request_sha256)
    _need(checked["request"] == request and checked["profile"] == counted.QUANTITY_PROFILE
          and checked["source_binding"] is None and not any(checked["authority"].values()),
          "complete unreviewed positive quantity replay required")
    quantity, threshold = checked["quantity"], checked["threshold"]
    _quantity_native_budget(quantity, threshold)
    mixed_raw = checked["mixed_request_raw_utf8"].encode("utf-8")
    baseline = prepare_mixed_relational_ast_preservation(checked["mixed_report"], mixed_raw,
        expected_report_sha256=checked["mixed_report_sha256"],
        expected_request_sha256=checked["mixed_request_sha256"], toolchain=toolchain)
    base_manifest = baseline.to_dict()
    _need(base_manifest["profile"] == MIXED_PROFILE and len(base_manifest["expected_modules"]) == MAX_MODULES,
          "unchanged existing mixed preservation route required")
    modules = list(base_manifest["expected_modules"])
    semantics_module, instance = modules[1], modules[2]
    files = dict(baseline.files)
    files[semantics_module.replace(".", "/") + ".lean"] += "\n" + _file(MIXED_PROJECT_ROOT, [], _quantity_extra_semantics())
    files[instance.replace(".", "/") + ".lean"] += "\n" + _file(instance, [],
        _quantity_cardinality_obligations(quantity, threshold))
    inputs = {"schema": QUANTITY_COUNTED_INPUT_SCHEMA, "profile": QUANTITY_COUNTED_PROFILE,
        "quantity_report": checked, "quantity_report_sha256": expected_report_sha256,
        "original_request_raw_utf8": request_raw.decode("utf-8"),
        "original_request_sha256": expected_request_sha256,
        "genuine_mixed_preparation_sha256": preparation_sha256(baseline),
        "genuine_mixed_manifest": base_manifest}
    files["preservation-inputs.json"] = _wire(inputs, MAX_PROJECT_BYTES).decode("utf-8") + "\n"
    _need(len(files) == MAX_FILES and sum(len(value.encode("utf-8")) for value in files.values()) <= MAX_PROJECT_BYTES,
          "complete quantity project exceeds existing seven-file byte capacity")
    owners = _owners()
    contracts = owners[-1]
    extra_names = list(_quantity_theorem_types(quantity, threshold))
    manifest = contracts.seal_record({
        "schema": SCHEMA, "profile": QUANTITY_COUNTED_PROFILE, "toolchain": toolchain, "target": "legal",
        "quantity": quantity, "threshold": threshold, "family": "tdfol", "typed_profile": "tdfol_default",
        "quantity_report_sha256": expected_report_sha256, "original_request_sha256": expected_request_sha256,
        "typed_expression_sha256": checked["typed_expression_sha256"],
        "typed_expression_content_digest": checked["typed_expression_content_digest"],
        "genuine_mixed_preparation_sha256": preparation_sha256(baseline), "genuine_mixed_manifest": base_manifest,
        "expected_modules": modules, "module_imports": base_manifest["module_imports"],
        "file_sha256": {name: _sha(text.encode("utf-8")) for name, text in sorted(files.items())},
        "theorems": list(base_manifest["theorems"]) + [instance + "." + name for name in extra_names],
        "quantity_expected_theorem_types": _quantity_theorem_types(quantity, threshold),
        "expected_axioms": {name: [] for name in list(base_manifest["theorems"]) + [instance + "." + key for key in extra_names]},
        "mathematical_contract": "positive_injective_Fin_witness" if quantity == "at_least" else "explicit_injective_Fin_enumeration_with_membership_range_iff",
        "theorem_assumptions": [
            "Object/EventFrame/TimeFrame may be empty; quantification remains per event/time pair.",
            "Object equality is built-in; no DecidableEq Object, Classical, choice, funext or propext is requested.",
            "Positive witnesses and explicit enumeration are independent Fin contracts, not an AL-and-AM shortcut.",
            "Only closed Fin-index disequality controls use decide; existing direct Fin elimination is reused.",
            "All eight theorem proofs, elaboration, exact types and empty-axiom reports remain unexecuted until actual native qualification."],
        "support_profile": {"sorts": ["Object", "EventFrame", "TimeFrame"], "predicate": "Member",
            "roles": ["object", "event", "time"], "quantity": quantity, "threshold": threshold,
            "max_nodes": MAX_MIXED_AST_NODES, "max_depth": MAX_MIXED_AST_DEPTH,
            "max_project_bytes": MAX_PROJECT_BYTES, "source_carriers_may_be_empty": True},
        "source_custody": {"original_request": "preservation-inputs.json/original_request_raw_utf8",
            "whole_quantity_report": "preservation-inputs.json/quantity_report", "statutory_meaning_proved": False},
        "producer_pins": dict(base_manifest["producer_pins"]),
        "counted_producer_pins": dict(checked["producer_pins"]),
        "preparation_only": True, "authority": dict(AUTHORITY), "training_mask": 0,
        "evaluation_gold_mask": 0, "native_ast": None, "native_TDFOL_route_used": False,
        "native_parser_roundtrip": False, "quantity_cardinality_proved": False,
        **FALSE_FLAGS})
    _need(_wire(report, MAX_RECORD_BYTES) == report_raw,
          "offered quantity report changed during preservation preparation")
    final = NativeAstPreservationPreparation(_wire(manifest, MAX_RECORD_BYTES).decode("utf-8"), tuple(sorted(files.items())))
    preparation_sha256(final)
    # Closing regeneration still binds the complete original quantity declaration.
    _need(counted.validate_counted_quantity_v4(report, request_raw,
        expected_report_sha256=expected_report_sha256, expected_request_sha256=expected_request_sha256) == checked,
        "quantity operation owners changed during complete preparation")
    return final


def validate_counted_quantity_ast_preservation(preparation, report, request_raw: bytes, *,
        expected_preparation_sha256, expected_report_sha256, expected_request_sha256, toolchain):
    _pin(expected_preparation_sha256, "complete positive quantity preservation preparation")
    _need(preparation_sha256(preparation) == expected_preparation_sha256,
          "independent complete quantity preparation pin differs")
    expected = prepare_counted_quantity_ast_preservation(report, request_raw,
        expected_report_sha256=expected_report_sha256, expected_request_sha256=expected_request_sha256,
        toolchain=toolchain)
    _need(expected == preparation and preparation_sha256(expected) == expected_preparation_sha256,
          "quantity preparation differs from complete original regeneration")
    return expected

# PRIVATE UNIMPORTED / UNEXECUTED PROOF-GENERATION DATA.
# This fragment is not a maintained logic module or a qualification receipt.
# The caller owns resource preflight, the exact source lowerer, and admission.
# Required Lean names: thresholdFinCases, quantityExpansion,
# quantityFiniteAtLeast, quantityFiniteExactly.  No imports are generated.
# quantityExpansion must have precisely the source shape documented below.


def _quantity_finite_equivalence_proof(quantity, n):
    """Generate one constructive per-specialization Lean proof candidate.

    Accepted quantities are exactly at_least and exactly; n is a nonnegative
    plain Python int (not bool).  The caller must preflight all output budgets.

    Source contract, under forall event time:
      n=0 at_least: forall z, member z event time -> member z event time.
      n=0 exactly:  forall z, not (member z event time).
      n>0: nested exists x0 ... x(n-1), followed by a LEFT-associated
        conjunction whose leaves, in order, are:
          1. member xi event time, i ascending;
          2. not (xi = xj), pairs i<j in lexicographic order;
          3. for exactly only, forall x, member x event time iff the
             LEFT-associated disjunction [x = xi, i ascending].
        A singleton conjunction/disjunction is its sole leaf.

    The finite specifications are the requested independent definitions:
      AtLeast: exists f : Fin n -> Object, Injective f and all f i are members.
      Exactly: exists f : Fin n -> Object, Injective f and
                 forall x, member x event time iff exists i, f i = x.

    Only direct thresholdFinCases/Fin.elim0 elimination is used.  The only
    generated decide terms compare closed Fin literals.  Eq.mp/congrArg
    merely transport along supplied Object equality; they use no propext.
    This function and all generated Lean remain unexecuted and unqualified.
    """
    if (type(quantity) is not str or quantity not in ("at_least", "exactly")
            or type(n) is not int or n < 0):
        raise ValueError("quantity must be at_least/exactly and n a natural plain int")

    target = "quantityFiniteAtLeast" if quantity == "at_least" else "quantityFiniteExactly"

    def finish(forward, backward):
        return (
            "theorem quantity_finite_equivalence {Object EventFrame TimeFrame : Type}\n"
            "    (member : Object → EventFrame → TimeFrame → Prop) :\n"
            "    quantityExpansion member ↔ " + target + " " + str(n) + " member := by\n"
            "  exact Iff.intro\n    " + forward + "\n    " + backward + "\n"
            "#print axioms quantity_finite_equivalence\n"
        )

    if n == 0:
        empty_function = "(fun (index : Fin 0) => Fin.elim0 index)"
        empty_injective = "(fun {leftIndex} {rightIndex} equality => Fin.elim0 leftIndex)"
        if quantity == "at_least":
            forward = (
                "(fun h event time =>\n"
                "      let objects : Fin 0 → Object := " + empty_function + "\n"
                "      Exists.intro objects (And.intro " + empty_injective
                + " (fun index => Fin.elim0 index)))"
            )
            backward = "(fun h event time z membership => membership)"
        else:
            forward = (
                "(fun h event time =>\n"
                "      let objects : Fin 0 → Object := " + empty_function + "\n"
                "      Exists.intro objects (And.intro " + empty_injective
                + " (fun x => Iff.intro"
                + " (fun membership => False.elim (h event time x membership))"
                + " (fun enumeration => Exists.elim enumeration"
                + " (fun index equality => Fin.elim0 index)))))"
            )
            backward = (
                "(fun h event time x membership =>\n"
                "      Exists.elim (h event time) (fun objects evidence =>\n"
                "        Exists.elim (Iff.mp ((And.right evidence) x) membership)"
                " (fun index equality => Fin.elim0 index)))"
            )
        return finish(forward, backward)

    variables = ["x" + str(i) for i in range(n)]
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    pair_positions = {pair: n + k for k, pair in enumerate(pairs)}
    leaf_count = n + len(pairs) + (1 if quantity == "exactly" else 0)

    def fin(i):
        proof = "Nat.le.refl"
        for _ in range(n - i - 1):
            proof = "(Nat.le.step " + proof + ")"
        return "(⟨" + str(i) + ", " + proof + "⟩ : Fin " + str(n) + ")"

    def fold_and(values):
        result = values[0]
        for value in values[1:]:
            result = "(And.intro (" + result + ") (" + value + "))"
        return result

    def projection(value, index, length):
        if length == 1:
            return value
        if index == length - 1:
            return "(And.right " + value + ")"
        return projection("(And.left " + value + ")", index, length - 1)

    def or_type(values):
        result = values[0]
        for value in values[1:]:
            result = "(" + result + " ∨ " + value + ")"
        return result

    def or_intro(index, length, value):
        if length == 1:
            return value
        if index == length - 1:
            return "(Or.inr (" + value + "))"
        return "(Or.inl (" + or_intro(index, length - 1, value) + "))"

    def or_eliminate(value, length, leaf):
        if length == 1:
            return leaf(0, value)
        earlier = "earlier" + str(length)
        equality = "equality" + str(length - 1)
        return (
            "(Or.elim (" + value + ") (fun " + earlier + " => "
            + or_eliminate(earlier, length - 1, leaf) + ") (fun " + equality + " => "
            + leaf(length - 1, equality) + "))"
        )

    def cases(branches, name, motive, offset=0):
        # The lift and dependent motive deliberately follow the cached,
        # previously qualified thresholdFinCases constructor-elimination shape.
        if not branches:
            return "(fun (" + name + " : Fin 0) => Fin.elim0 " + name + ")"
        size_here = len(branches)
        argument = name + "Value"
        lifted = argument
        if offset:
            proof = "(" + argument + ").isLt"
            for _ in range(offset):
                proof = "(Nat.succ_lt_succ " + proof + ")"
            lifted = (
                "(⟨(" + argument + ").val + " + str(offset) + ", " + proof
                + "⟩ : Fin " + str(size_here + offset) + ")"
            )
        annotation = (
            "(motive := fun (" + argument + " : Fin " + str(size_here) + ") => "
            + motive(lifted) + ")"
        )
        return (
            "(fun (" + name + " : Fin " + str(size_here) + ") => thresholdFinCases "
            + annotation + " (" + branches[0] + ") "
            + cases(branches[1:], name + "Tail", motive, offset + 1) + " " + name + ")"
        )

    def injection_type(left, right):
        return (
            "(objects (" + left + ") = objects (" + right + ")) → ("
            + left + ") = (" + right + ")"
        )

    def source_forward(properties):
        objects = cases(variables, "objectIndex", lambda index: "Object")
        member_branches = [projection(properties, i, leaf_count) for i in range(n)]
        members = cases(
            member_branches, "memberIndex",
            lambda index: "member (objects (" + index + ")) event time"
        )
        rows = []
        for i in range(n):
            row = []
            for j in range(n):
                if i == j:
                    result = "Eq.refl " + fin(i)
                else:
                    pair = (min(i, j), max(i, j))
                    distinct = projection(properties, pair_positions[pair], leaf_count)
                    equality = "equality" if i < j else "(Eq.symm equality)"
                    result = "False.elim ((" + distinct + ") (" + equality + "))"
                row.append("(fun equality => " + result + ")")
            rows.append(cases(
                row, "rightIndex",
                lambda right, left=i: injection_type(fin(left), right)
            ))
        conclude = cases(
            rows, "leftIndex",
            lambda left: "∀ (j : Fin " + str(n) + "), " + injection_type(left, "j")
        )
        result = (
            "(let objects : Fin " + str(n) + " → Object := " + objects + "\n"
            "        let members : ∀ i : Fin " + str(n)
            + ", member (objects i) event time := " + members + "\n"
            "        let conclude : ∀ (i j : Fin " + str(n)
            + "), objects i = objects j → i = j := " + conclude + "\n"
            "        let injective : Function.Injective objects :="
            " (fun {i} {j} equality => conclude i j equality)\n"
        )
        if quantity == "at_least":
            return result + "        Exists.intro objects (And.intro injective members))"
        coverage = projection(properties, leaf_count - 1, leaf_count)
        source_disjunction = or_type(["x = " + variable for variable in variables])
        from_source = or_eliminate(
            "Iff.mp (cover x) membership", n,
            lambda i, equality: "(Exists.intro " + fin(i) + " (Eq.symm (" + equality + ")))"
        )
        to_member = (
            "(fun enumeration => Exists.elim enumeration (fun index equality => "
            "Eq.mp (congrArg (fun entity : Object => member entity event time) equality)"
            " (members index)))"
        )
        return (
            result + "        let cover : ∀ (x : Object), member x event time ↔ "
            + source_disjunction + " := " + coverage + "\n"
            "        Exists.intro objects (And.intro injective (fun x => Iff.intro "
            + "(fun membership => " + from_source + ") " + to_member + ")))"
        )

    def unpack_source(value, index):
        if index == n:
            return source_forward(value)
        remaining = "sourceRest" + str(index)
        return (
            "(Exists.elim (" + value + ") (fun " + variables[index] + " " + remaining
            + " => " + unpack_source(remaining, index + 1) + "))"
        )

    forward = "(fun h event time => " + unpack_source("h event time", 0) + ")"

    witness_values = ["(objects " + fin(i) + ")" for i in range(n)]
    if quantity == "at_least":
        backward_prefix = (
            "let members : ∀ i : Fin " + str(n)
            + ", member (objects i) event time := And.right evidence\n"
        )
        leaves = ["(members " + fin(i) + ")" for i in range(n)]
    else:
        backward_prefix = (
            "let cover : ∀ (x : Object), member x event time ↔ ∃ i : Fin "
            + str(n) + ", objects i = x := And.right evidence\n"
        )
        leaves = [
            "(Iff.mpr (cover (objects " + fin(i) + ")) (Exists.intro "
            + fin(i) + " (Eq.refl _)))"
            for i in range(n)
        ]
    for i, j in pairs:
        leaves.append(
            "(fun equality => (by decide : " + fin(i) + " ≠ " + fin(j)
            + ") (injective equality))"
        )
    if quantity == "exactly":
        source_disjunction = or_type(["x = " + value for value in witness_values])
        coverage_handlers = cases(
            [
                "(fun equality => " + or_intro(i, n, "(Eq.symm equality)") + ")"
                for i in range(n)
            ],
            "coverageIndex",
            lambda index: "(objects (" + index + ") = x) → " + source_disjunction
        )
        source_to_finite = or_eliminate(
            "sourceEquality", n,
            lambda i, equality: (
                "(Iff.mpr (cover x) (Exists.intro " + fin(i)
                + " (Eq.symm (" + equality + "))))"
            )
        )
        leaves.append(
            "(fun x => Iff.intro"
            " (fun membership => Exists.elim (Iff.mp (cover x) membership)"
            " (fun index equality => (" + coverage_handlers + ") index equality))"
            " (fun sourceEquality => " + source_to_finite + "))"
        )
    packed = fold_and(leaves)
    for value in reversed(witness_values):
        packed = "(Exists.intro " + value + " (" + packed + "))"
    backward = (
        "(fun h event time => Exists.elim (h event time) (fun objects evidence =>\n"
        "      let injective : Function.Injective objects := And.left evidence\n"
        "      " + backward_prefix + "      " + packed + "))"
    )
    return finish(forward, backward)
