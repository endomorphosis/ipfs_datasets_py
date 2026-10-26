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
