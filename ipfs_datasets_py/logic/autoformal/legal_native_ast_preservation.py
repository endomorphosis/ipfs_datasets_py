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


def _wire(value, maximum):
    """Bound ordinary finite JSON without importing operation owners."""
    remaining, nodes = maximum, 100_000

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 96, "preservation JSON node/depth bound exceeded")
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


def _parse(raw, maximum):
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
    _wire(value, maximum)
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


def prepare_relational_ast_preservation(report, request_raw: bytes, *,
        expected_report_sha256, expected_request_sha256, toolchain):
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
    producers = _relational_pins(owners, relational, checked)
    _need(checked["request"] == request, "relational original request replay differs")
    fragment = checked["native_fragment"]
    fragment_raw = _wire(fragment, MAX_FRAGMENT_BYTES)
    actual = _native_value(fragment["native_ast"])
    roles = {row["symbol"]: row["roles"] for row in checked["argument_roles"]}
    source = _relational_source_syntax(checked["typed_expression"]["root"], roles)
    semantics = RELATIONAL_SEMANTICS
    instance = RELATIONAL_PROJECT_ROOT + ".Instance" + _sha(_wire({
        "profile": RELATIONAL_PROFILE, "report_sha256": expected_report_sha256,
        "request_sha256": expected_request_sha256, "semantics_sha256": _sha(semantics.encode()),
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
    inputs = {"schema": RELATIONAL_INPUT_SCHEMA, "profile": RELATIONAL_PROFILE,
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
        "schema": SCHEMA, "profile": RELATIONAL_PROFILE, "toolchain": toolchain, "target": "legal",
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
    return preparation


def validate_relational_ast_preservation(preparation, report, request_raw: bytes, *,
        expected_preparation_sha256, expected_report_sha256, expected_request_sha256, toolchain):
    """Replay whole typed/native inputs; never accept a merely resealed project."""
    _pin(expected_preparation_sha256, "complete relational preservation preparation")
    _need(preparation_sha256(preparation) == expected_preparation_sha256,
          "independent complete relational preservation pin differs")
    expected = prepare_relational_ast_preservation(report, request_raw,
        expected_report_sha256=expected_report_sha256, expected_request_sha256=expected_request_sha256,
        toolchain=toolchain)
    _need(expected == preparation, "relational preservation differs from complete original regeneration")
    return expected



COUNTED_PROFILE = "typed-many-sorted-fixed-three-counted-preservation/v1"
COUNTED_PROJECT_ROOT = "LegalCountedAstPreservation"
COUNTED_INPUT_SCHEMA = "legal-counted-ast-preservation-inputs/v1"
_COUNTED_OPERATION_PINS = None


# The existing NativeValue is reused solely as exact JSON proof-witness syntax.
# CountedVariable/CountedFormula are not production or decoder representations.
COUNTED_SEMANTICS = SEMANTICS + r'''

inductive CountedSort where
  | object
  | event
  | time
  deriving BEq, DecidableEq

structure CountedVariable where
  nodeId : String
  name : String
  sort : CountedSort

inductive CountedFormula where
  | member (nodeId : String) (object event time : CountedVariable)
  | equality (nodeId : String) (left right : CountedVariable)
  | conjunction (nodeId : String) (left right : CountedFormula)
  | disjunction (nodeId : String) (left right : CountedFormula)
  | implication (nodeId : String) (left right : CountedFormula)
  | universal (nodeId name : String) (sort : CountedSort) (body : CountedFormula)

def countedSortName : CountedSort → String
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

def countedVariableValue (variable : CountedVariable) : NativeValue :=
  countedNodeValue variable.nodeId "variable" variable.name
    (countedAtomicSortValue variable.sort) [] []

def countedToTypedNodeValue : CountedFormula → NativeValue
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
    (variable : CountedVariable) : Bool :=
  bound.contains (variable.sort, variable.name)

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

structure CountedEnvironment (Object EventFrame TimeFrame : Type) where
  objects : String → Option Object
  events : String → Option EventFrame
  times : String → Option TimeFrame

def emptyCountedEnvironment {Object EventFrame TimeFrame : Type} :
    CountedEnvironment Object EventFrame TimeFrame :=
  ⟨fun _ => none, fun _ => none, fun _ => none⟩

def countedObjectValue {Object EventFrame TimeFrame : Type}
    (environment : CountedEnvironment Object EventFrame TimeFrame)
    (variable : CountedVariable) : Option Object :=
  match variable.sort with
  | .object => environment.objects variable.name
  | _ => none

def countedEventValue {Object EventFrame TimeFrame : Type}
    (environment : CountedEnvironment Object EventFrame TimeFrame)
    (variable : CountedVariable) : Option EventFrame :=
  match variable.sort with
  | .event => environment.events variable.name
  | _ => none

def countedTimeValue {Object EventFrame TimeFrame : Type}
    (environment : CountedEnvironment Object EventFrame TimeFrame)
    (variable : CountedVariable) : Option TimeFrame :=
  match variable.sort with
  | .time => environment.times variable.name
  | _ => none

def countedDenote {Object EventFrame TimeFrame : Type}
    (member : Object → EventFrame → TimeFrame → Prop) :
    CountedFormula → CountedEnvironment Object EventFrame TimeFrame → Prop
  | .member _ object event time, environment =>
      match countedObjectValue environment object, countedEventValue environment event,
          countedTimeValue environment time with
      | some object, some event, some time => member object event time
      | _, _, _ => False
  | .equality _ left right, environment =>
      match countedObjectValue environment left, countedObjectValue environment right with
      | some left, some right => left = right
      | _, _ => False
  | .conjunction _ left right, environment =>
      countedDenote member left environment ∧ countedDenote member right environment
  | .disjunction _ left right, environment =>
      countedDenote member left environment ∨ countedDenote member right environment
  | .implication _ left right, environment =>
      countedDenote member left environment → countedDenote member right environment
  | .universal _ name .object body, environment =>
      ∀ object : Object, countedDenote member body
        { environment with objects := fun queried =>
            if queried = name then some object else environment.objects queried }
  | .universal _ name .event body, environment =>
      ∀ event : EventFrame, countedDenote member body
        { environment with events := fun queried =>
            if queried = name then some event else environment.events queried }
  | .universal _ name .time body, environment =>
      ∀ time : TimeFrame, countedDenote member body
        { environment with times := fun queried =>
            if queried = name then some time else environment.times queried }

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
'''


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
        + "def threeObjectMembers (_ : Fin 3) (_ : Unit) (_ : Unit) : Prop := True\n"
        + "def fourObjectMembers (_ : Fin 4) (_ : Unit) (_ : Unit) : Prop := True\n"
        + "theorem cap_two_counterexample :\n"
        + "    countedDenote threeObjectMembers typedCountedAst emptyCountedEnvironment ∧\n"
        + "      ¬ counterfactualAtMostTwo threeObjectMembers := by\n"
        + "  change countedAtMostThree threeObjectMembers ∧ ¬ counterfactualAtMostTwo threeObjectMembers\n"
        + "  decide\n#print axioms cap_two_counterexample\n"
        + "theorem cap_four_counterexample :\n"
        + "    ¬ countedDenote fourObjectMembers typedCountedAst emptyCountedEnvironment ∧\n"
        + "      counterfactualAtMostFour fourObjectMembers := by\n"
        + "  change ¬ countedAtMostThree fourObjectMembers ∧ counterfactualAtMostFour fourObjectMembers\n"
        + "  decide\n#print axioms cap_four_counterexample\n")
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
