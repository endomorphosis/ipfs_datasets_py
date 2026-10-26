"""Exact native snapshots to explicit Lean syntax; no legal-source claims.

Fixtures pass through the current native parser, AST snapshot and emitter owners.
The retained section 101 AST is embedded with its original AST/body commitments;
no historical sampled-source review receipt is replayed or silently resealed.
These tests prepare text only. Native kernel checks have a separate executor.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import subprocess
import sys
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import legal_family_routes as routes
from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation as owner
from ipfs_datasets_py.logic.autoformal import family_qualification
from ipfs_datasets_py.logic.autoformal import corpus_contracts
from ipfs_datasets_py.logic.intent_ir.formalize.modal_projections import _ast


TOOLCHAIN = "leanprover/lean4:v4.34.1"
SECTION_101_HEAD = "Dbd48f41add569aaa0eb3e500460119c4aa990ec31eb4867a98e24aa609ad6c3a"
SECTION_101_BODY = "Da40ab2d15eb233346a3c5255c6377439b1d0e46f75b030463de7697564fc9d1f"
SECTION_101_AST_SHA = "3d5ea9d4a02c3b6134b1e37f02b589d16fd4c0fdffbf568da7dac8f98480e500"
SECTION_101_LEAN_SHA = "e32ddc735bcab36e3f2bf1348e4d3f135ce660352ceb72475b82409f3b64b74d"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fragment_data(family="fol", formula=None):
    formula = formula or (
        "∀x.(↔ " + SECTION_101_HEAD + "(x) " + SECTION_101_BODY + "(x))"
    )
    ast = _ast(family_qualification._strict_tdfol(formula)[0])
    fragment = routes.prepare_native_fragment(
        family=family, formula=formula, expected_ast=ast,
    )
    return {"fragment": fragment, "fragment_raw": canonical(fragment),
            "toolchain": TOOLCHAIN}


def prepare(data, **overrides):
    return owner.prepare_native_ast_preservation(
        data["fragment_raw"], **({
            "expected_fragment_file_sha256": sha(data["fragment_raw"]),
            "toolchain": data["toolchain"],
        } | overrides),
    )


def validate(data, preparation, **overrides):
    return owner.validate_native_ast_preservation(
        preparation, data["fragment_raw"], **({
            "expected_preparation_sha256": owner.preparation_sha256(preparation),
            "expected_fragment_file_sha256": sha(data["fragment_raw"]),
            "toolchain": data["toolchain"],
        } | overrides),
    )


def manifest(preparation):
    return json.loads(preparation.manifest_json)


@pytest.fixture(scope="module")
def base():
    data = fragment_data()
    return data, prepare(data)


def change_ast(data, mutate):
    changed = deepcopy(data)
    mutate(changed["fragment"]["native_ast"])
    changed["fragment"]["native_ast_sha256"] = sha(
        canonical(changed["fragment"]["native_ast"])
    )
    changed["fragment_raw"] = canonical(changed["fragment"])
    return changed


def test_public_import_is_stdlib_only_without_operation_owners():
    script = r"""
import importlib.util,sys
blocked=('ipfs_datasets_py','torch','transformers','tensorflow','numpy','multiformats','cryptography','pyarrow','requests')
class Deny:
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==name or fullname.startswith(name+'.') for name in blocked):
            raise AssertionError('operation owner reached: '+fullname)
sys.meta_path.insert(0,Deny())
spec=importlib.util.spec_from_file_location('_preservation_cold',sys.argv[1])
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)
for name in ('NativeAstPreservationPreparation','prepare_native_ast_preservation','validate_native_ast_preservation','preparation_sha256'):
    assert hasattr(module,name),name
assert not any(any(name==prefix or name.startswith(prefix+'.') for prefix in blocked) for name in sys.modules)
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, owner.__file__],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_exact_retained_section_101_snapshot_and_existing_body_are_preserved(family):
    data = fragment_data(family)
    original = deepcopy(data)
    preparation = prepare(data)
    meta, files = manifest(preparation), dict(preparation.files)
    fragment = data["fragment"]
    assert sha(canonical(fragment["native_ast"])) == SECTION_101_AST_SHA
    assert sha(fragment["lean_body"].encode()) == SECTION_101_LEAN_SHA
    assert len(files) == len(preparation.files) == 7
    assert len(meta["expected_modules"]) == len(set(meta["expected_modules"])) == 4
    assert set(meta["file_sha256"]) == set(files)
    assert meta["file_sha256"] == {
        name: sha(text.encode("utf-8")) for name, text in sorted(files.items())
    }
    assert meta["original_fragment_file_sha256"] == sha(data["fragment_raw"])
    assert meta["original_fragment_canonical_sha256"] == sha(canonical(fragment))
    assert meta["native_ast_sha256"] == SECTION_101_AST_SHA
    assert meta["lean_body_sha256"] == SECTION_101_LEAN_SHA
    assert meta["family"] == family
    assert meta["source_custody"]["original_source_bundle_replayed"] is False
    assert meta["source_custody"]["source_prose_to_ast_proved"] is False
    assert all(value is False for value in meta["authority"].values())
    assert meta["preparation_only"] is True
    assert meta["training_mask"] == meta["evaluation_gold_mask"] == 0
    assert all(meta[name] is False for name in owner.FALSE_FLAGS)
    assert files["lean-toolchain"] == TOOLCHAIN + "\n"
    module_paths = {
        name.replace(".", "/") + ".lean" for name in meta["expected_modules"]
    }
    assert module_paths <= set(files)
    assert len(meta["theorems"]) == len(set(meta["theorems"])) == 3
    assert {name.rsplit(".", 1)[-1] for name in meta["theorems"]} == {
        "native_value_exact", "native_ast_closed", "denotation_matches_native",
    }
    source = "\n".join(files.values())
    assert fragment["lean_body"] in source
    inputs = json.loads(files["preservation-inputs.json"])
    assert inputs["original_fragment_raw_utf8"].encode() == data["fragment_raw"]
    assert inputs["original_fragment"] == fragment
    assert SECTION_101_HEAD in source and SECTION_101_BODY in source
    assert "inductive NativeValue" in source
    assert "#print axioms" in source
    assert not any(word in source.split() for word in ("sorry", "admit", "axiom", "unsafe"))
    assert validate(data, preparation) == preparation
    assert data == original


@pytest.mark.parametrize("formula", [
    "forall x. (Head(x) <-> (Registered(x) and (Active(x) or not Exempt(x))))",
    "forall x. (Head(x) <-> (Use(x) or Use(x)))",
    "forall x. (((One(x) and Two(x)) and Three(x)) -> Head(x))",
    "forall x. ((One(x) or Two(x)) <-> (Three(x) and not Four(x)))",
    "forall x. (One(x) -> forall y. (Two(y) <-> Three(x)))",
    "forall x. (One(x) -> forall x. (Two(x) <-> Three(x)))",
    "(forall x. (Donor(x) <-> Source(x))) and ((forall x. (Consumer(x) <-> (Use(x) or Use(x)))) and (forall x. (Use(x) <-> Donor(x))))",
])
@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_authored_boolean_order_duplicates_nested_quantifiers_and_shadowing(formula, family):
    data = fragment_data(family, formula)
    preparation = prepare(data)
    source = "\n".join(dict(preparation.files).values())
    assert data["fragment"]["lean_body"] in source
    assert validate(data, preparation) == preparation
    assert data["fragment"]["source_semantics_verified"] is False
    assert data["fragment"]["cross_family_equivalence_verified"] is False


@pytest.mark.parametrize("field,value", [
    ("expected_fragment_file_sha256", "0" * 64),
    ("expected_fragment_file_sha256", "A" * 64),
    ("expected_fragment_file_sha256", None),
    ("expected_fragment_file_sha256", True),
    ("toolchain", "main"), ("toolchain", "leanprover/lean4:latest"),
    ("toolchain", TOOLCHAIN + "\n"), ("toolchain", True),
])
def test_bad_independent_commitment_or_toolchain_refuses_before_lazy_owners(base, field, value):
    data, _ = base
    with patch.object(owner, "_owners", side_effect=AssertionError("operation import reached")):
        with pytest.raises(ValueError):
            prepare(data, **{field: value})


@pytest.mark.parametrize("value", ["0" * 64, "A" * 64, "short", None, True])
def test_bad_independent_preparation_commitment_refuses_before_owners(base, value):
    data, preparation = base
    with patch.object(owner, "_owners", side_effect=AssertionError("operation import reached")):
        with pytest.raises(ValueError):
            validate(data, preparation, expected_preparation_sha256=value)


@pytest.mark.parametrize("damage", [
    "mutable", "empty", "oversize", "duplicate", "nan", "infinity", "utf8",
    "array", "null", "surrogate", "extra_root",
])
def test_malformed_or_unbounded_json_refuses_before_lazy_owners(base, damage):
    data, _ = base
    changed = deepcopy(data)
    choices = {
        "mutable": bytearray(data["fragment_raw"]), "empty": b"",
        "oversize": b" " * (1024**2 + 1),
        "duplicate": b'{"family":"fol","family":"tdfol"}',
        "nan": b'{"bad":NaN}', "infinity": b'{"bad":Infinity}',
        "utf8": b'\xff', "array": b'[]', "null": b'null',
        "surrogate": b'{"bad":"\\ud800"}',
        "extra_root": canonical(data["fragment"] | {"unknown": True}),
    }
    changed["fragment_raw"] = choices[damage]
    with patch.object(owner, "_owners", side_effect=AssertionError("operation import reached")):
        with pytest.raises(ValueError):
            prepare(changed)


@pytest.mark.parametrize("damage", [
    "extra_formula", "extra_predicate", "extra_variable", "extra_enum",
    "wrong_enum", "object_sort", "named_sort", "two_arguments", "no_arguments",
    "free_variable", "constant", "function", "modal", "temporal", "existential",
    "unsupported_operator", "missing_child", "boolean_name", "empty_name",
])
def test_outside_exact_unary_closed_native_profile_refuses_before_owners(base, damage):
    data, _ = base
    def mutate(ast):
        predicate = ast["formula"]["left"]
        variable = predicate["arguments"][0]
        if damage == "extra_formula": ast["unknown"] = None
        elif damage == "extra_predicate": predicate["unknown"] = None
        elif damage == "extra_variable": variable["unknown"] = None
        elif damage == "extra_enum": ast["quantifier"]["unknown"] = None
        elif damage == "wrong_enum": ast["quantifier"]["enum"] = "LogicOperator"
        elif damage == "object_sort": variable["sort"] = {"enum": "Sort", "value": "Object"}
        elif damage == "named_sort": variable["sort"] = "Entity"
        elif damage == "two_arguments": predicate["arguments"].append(deepcopy(variable))
        elif damage == "no_arguments": predicate["arguments"] = []
        elif damage == "free_variable": variable["name"] = "unbound"
        elif damage == "constant": variable["node_type"] = "Constant"
        elif damage == "function": variable.update(node_type="FunctionApplication", function_name="f")
        elif damage == "modal": ast["formula"] = {"node_type": "DeonticFormula", "operator": {"enum": "DeonticOperator", "value": "O"}, "formula": ast["formula"], "agent": None, "context": None}
        elif damage == "temporal": ast["formula"] = {"node_type": "TemporalFormula", "operator": {"enum": "TemporalOperator", "value": "G"}, "formula": ast["formula"], "time_bound": None, "time": None}
        elif damage == "existential": ast["quantifier"]["value"] = "∃"
        elif damage == "unsupported_operator": ast["formula"]["operator"]["value"] = "xor"
        elif damage == "missing_child": del ast["formula"]["right"]
        elif damage == "boolean_name": predicate["name"] = True
        else: predicate["name"] = ""
    changed = change_ast(data, mutate)
    with patch.object(owner, "_owners", side_effect=AssertionError("operation import reached")):
        with pytest.raises(ValueError):
            prepare(changed)


@pytest.mark.parametrize("damage", ["formula", "lean_body", "ast", "family", "authority", "producer_pin"])
def test_repaired_local_transport_hash_cannot_replace_original_native_replay(base, damage):
    data, _ = base
    changed = deepcopy(data)
    fragment = changed["fragment"]
    if damage == "formula":
        fragment["formula"] = fragment["formula"].replace("↔", "→")
        fragment["formula_sha256"] = sha(fragment["formula"].encode())
    elif damage == "lean_body": fragment["lean_body"] = fragment["lean_body"].replace("↔", "→")
    elif damage == "ast":
        fragment["native_ast"]["formula"]["operator"]["value"] = "→"
        fragment["native_ast_sha256"] = sha(canonical(fragment["native_ast"]))
    elif damage == "family": fragment["family"] = "dcec"
    elif damage == "authority": fragment["source_semantics_verified"] = True
    else: fragment["producer_pins"][next(iter(fragment["producer_pins"]))] = "0" * 64
    changed["fragment_raw"] = canonical(fragment)
    with pytest.raises(ValueError):
        prepare(changed)


@pytest.mark.parametrize("damage", ["source", "missing", "extra", "module", "theorem", "authority", "native_ast"])
def test_self_consistent_preparation_mutants_do_not_replace_original_snapshot(base, damage):
    data, original = base
    meta, files = manifest(original), dict(original.files)
    if damage == "source":
        path = next(name for name in files if "/Instance" in name)
        files[path] = files[path].replace("↔", "→", 1)
    elif damage == "missing": files.pop("lean-toolchain")
    elif damage == "extra": files["Unexpected.lean"] = "def fake : Prop := True\n"
    elif damage == "module": meta["expected_modules"].pop(1)
    elif damage == "theorem": meta["theorems"][0] = "Foreign.fake"
    elif damage == "authority": meta["source_semantics_verified"] = True
    else: meta["native_ast_sha256"] = "0" * 64
    meta["file_sha256"] = {name: sha(text.encode()) for name, text in sorted(files.items())}
    meta = corpus_contracts.seal_record({
        key: value for key, value in meta.items() if key not in {"record_cid", "cid_scope"}
    })
    changed = replace(original, manifest_json=canonical(meta).decode(), files=tuple(sorted(files.items())))
    with pytest.raises(ValueError):
        validate(data, changed)


def test_transport_hash_is_distinct_from_native_ast_canonical_hash(base):
    data, preparation = base
    assert sha(data["fragment_raw"]) != sha(canonical(data["fragment"]["native_ast"]))
    changed = deepcopy(data)
    changed["fragment_raw"] = json.dumps(data["fragment"], ensure_ascii=False, indent=2).encode()
    alternate = prepare(changed)
    assert owner.preparation_sha256(alternate) != owner.preparation_sha256(preparation)
    assert validate(changed, alternate) == alternate


@pytest.mark.parametrize("damage", ["depth", "nodes"])
def test_oversized_native_tree_refuses_the_whole_candidate_before_owners(base, damage):
    data, _ = base
    def mutate(ast):
        predicate = deepcopy(ast["formula"]["left"])
        if damage == "depth":
            tree = predicate
            for _ in range(33):
                tree = {"node_type": "UnaryFormula", "operator": {"enum": "LogicOperator", "value": "¬"}, "formula": tree}
        else:
            tree = predicate
            for _ in range(11):
                tree = {"node_type": "BinaryFormula", "operator": {"enum": "LogicOperator", "value": "∧"}, "left": tree, "right": deepcopy(tree)}
        ast["formula"] = tree
    changed = change_ast(data, mutate)
    with patch.object(owner, "_owners", side_effect=AssertionError("operation import reached")):
        with pytest.raises(ValueError):
            prepare(changed)


def test_preparation_never_probes_compiler_or_runs_native_process(base):
    data, _ = base
    with patch.object(subprocess, "run", side_effect=AssertionError("process reached")), patch.object(
        subprocess, "Popen", side_effect=AssertionError("process reached")
    ):
        preparation = prepare(data)
        assert validate(data, preparation) == preparation
