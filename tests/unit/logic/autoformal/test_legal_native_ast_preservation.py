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


# Additive relational profile controls. The legacy tests above remain intact.
# These fixtures are fictional declarations, not reviewed statutory targets.
@pytest.fixture(scope="module")
def relational_preservation_fixtures():
    """Reuse the existing relational builder and independent finite semantics."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).with_name("test_legal_relational_norm_v1.py")
    spec = importlib.util.spec_from_file_location(
        "_native_ast_preservation_existing_relational_fixtures", path,
    )
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    return fixtures


def _relational_preservation_capture(fixtures, request):
    raw = canonical(request)
    return fixtures.prepare(request), raw


def _prepare_relational_preservation(captured, **overrides):
    report, raw = captured
    return owner.prepare_relational_ast_preservation(
        report, raw, **({
            "expected_report_sha256": sha(canonical(report)),
            "expected_request_sha256": sha(raw),
            "toolchain": TOOLCHAIN,
        } | overrides),
    )


def _validate_relational_preservation(captured, preparation, **overrides):
    report, raw = captured
    return owner.validate_relational_ast_preservation(
        preparation, report, raw, **({
            "expected_preparation_sha256": owner.preparation_sha256(preparation),
            "expected_report_sha256": sha(canonical(report)),
            "expected_request_sha256": sha(raw),
            "toolchain": TOOLCHAIN,
        } | overrides),
    )


@pytest.fixture(scope="module")
def relational_preservation_base(relational_preservation_fixtures):
    fixtures = relational_preservation_fixtures
    captured = _relational_preservation_capture(fixtures, fixtures.approval_request())
    return captured, _prepare_relational_preservation(captured)


def test_relational_profile_replays_whole_report_request_and_unchanged_emitted_body(
        relational_preservation_base):
    captured, preparation = relational_preservation_base
    report, raw = captured
    before = deepcopy(captured)
    assert _validate_relational_preservation(captured, preparation) == preparation
    assert captured == before
    meta = manifest(preparation)
    assert owner.RELATIONAL_PROFILE == "typed-relational-deontic-native-preservation/v1"
    assert meta["profile"] == owner.RELATIONAL_PROFILE != owner.PROFILE
    source = "\n".join(text for _, text in preparation.files)
    assert report["native_fragment"]["lean_body"] == report["lean_body"]
    assert report["lean_body"] in source
    assert report["argument_roles"] == report["request"]["argument_roles"]
    assert report["request_raw_utf8"].encode() == raw
    assert not any(meta["authority"].values())
    assert meta["training_mask"] == meta["evaluation_gold_mask"] == 0
    assert meta["proof_checked"] is meta["source_semantics_verified"] is False


@pytest.mark.parametrize("field", ["expected_report_sha256", "expected_request_sha256"])
@pytest.mark.parametrize("pin", ["0" * 64, "A" * 64, "short", None, True])
def test_relational_profile_requires_independent_complete_original_pins(
        relational_preservation_base, field, pin):
    captured, _ = relational_preservation_base
    with pytest.raises(ValueError):
        _prepare_relational_preservation(captured, **{field: pin})


@pytest.mark.parametrize("field", [
    "expected_preparation_sha256", "expected_report_sha256", "expected_request_sha256",
])
def test_relational_validation_retains_all_three_independent_commitments(
        relational_preservation_base, field):
    captured, preparation = relational_preservation_base
    with pytest.raises(ValueError):
        _validate_relational_preservation(captured, preparation, **{field: "0" * 64})


@pytest.mark.parametrize("damage", [
    "roles", "argument_order", "quantifier", "modality", "body", "typed_tree",
    "mapping", "authority", "source_binding", "extra_report_field",
])
def test_relational_resealed_report_cannot_replace_original_semantics(
        relational_preservation_base, damage):
    captured, _ = relational_preservation_base
    report, raw = deepcopy(captured)

    def native_nodes(node):
        yield node
        if type(node) is dict:
            for child in node.values():
                if type(child) in (dict, list):
                    yield from native_nodes(child)
        elif type(node) is list:
            for child in node:
                yield from native_nodes(child)

    if damage == "roles":
        report["argument_roles"][0]["roles"].reverse()
    elif damage == "argument_order":
        predicate = next(node for node in native_nodes(report["native_ast"])
                         if type(node) is dict and node.get("node_type") == "Predicate"
                         and len(node["arguments"]) > 1)
        predicate["arguments"].reverse()
    elif damage == "quantifier":
        report["native_ast"]["quantifier"]["value"] = "∃"
    elif damage == "modality":
        modal = next(node for node in native_nodes(report["native_ast"])
                     if type(node) is dict and node.get("node_type") == "DeonticFormula")
        modal["operator"]["value"] = "O"
    elif damage == "body":
        report["lean_body"] = report["lean_body"].replace('"deontic:P"', '"deontic:O"')
    elif damage == "typed_tree":
        report["typed_expression"]["root"]["binders"][0]["name"] = "substitute_actor"
    elif damage == "mapping":
        report["structural_mapping"].pop()
    elif damage == "authority":
        report["authority"]["accepted"] = True
    elif damage == "source_binding":
        report["source_binding"] = {"fictional_unreviewed_substitution": True}
    else:
        report["unexpected"] = "not part of the original report"
    with pytest.raises(ValueError):
        # The helper deliberately recomputes the offered report hash. Replay of
        # the independently pinned original request must still reject it.
        _prepare_relational_preservation((report, raw))


def test_relational_report_and_different_genuine_request_cannot_be_cross_joined(
        relational_preservation_base, relational_preservation_fixtures):
    captured, _ = relational_preservation_base
    changed_request = relational_preservation_fixtures.approval_request(operator="O")
    with pytest.raises(ValueError):
        _prepare_relational_preservation((captured[0], canonical(changed_request)))


def test_relational_role_ledger_is_part_of_preserved_subject_even_when_body_is_identical(
        relational_preservation_fixtures):
    fixtures = relational_preservation_fixtures
    request = fixtures.approval_request()
    changed = deepcopy(request)
    changed["argument_roles"][0]["roles"].reverse()
    original = _relational_preservation_capture(fixtures, request)
    alternate = _relational_preservation_capture(fixtures, changed)
    assert original[0]["native_ast"] == alternate[0]["native_ast"]
    assert original[0]["lean_body"] == alternate[0]["lean_body"]
    original_project = _prepare_relational_preservation(original)
    alternate_project = _prepare_relational_preservation(alternate)
    assert owner.preparation_sha256(original_project) != owner.preparation_sha256(alternate_project)
    assert _validate_relational_preservation(original, original_project) == original_project
    assert _validate_relational_preservation(alternate, alternate_project) == alternate_project
    with pytest.raises(ValueError):
        _validate_relational_preservation(original, alternate_project)


@pytest.mark.parametrize("mutation", ["swapped", "reversed_direction"])
def test_relational_actor_and_direction_mutants_keep_distinct_preservation_subjects(
        relational_preservation_fixtures, mutation):
    fixtures = relational_preservation_fixtures
    original = _relational_preservation_capture(fixtures, fixtures.role_request())
    changed = _relational_preservation_capture(fixtures, fixtures.role_request(**{mutation: True}))

    def atoms(name, args, at):
        if name == "Move":
            return args == (0, 1, 0, 1)
        return args == ((0,) if name in {"Actor", "Origin"} else (1,))

    assert fixtures.evaluate(original[0]["native_ast"], atoms) is True
    assert fixtures.evaluate(changed[0]["native_ast"], atoms) is False
    projects = [_prepare_relational_preservation(item) for item in (original, changed)]
    assert projects[0] != projects[1]
    for captured, project in zip((original, changed), projects):
        assert _validate_relational_preservation(captured, project) == project
    with pytest.raises(ValueError):
        _validate_relational_preservation(original, projects[1])


def test_relational_forall_exists_order_preserves_independently_distinct_meanings(
        relational_preservation_fixtures):
    fixtures = relational_preservation_fixtures
    captured = []
    for binders in ([('actor', 'forall'), ('recipient', 'exists')],
                    [('recipient', 'exists'), ('actor', 'forall')]):
        builder = fixtures.Builder()
        request = fixtures.request_for(builder, builder.atom("Match", "actor", "recipient"),
                                       [("Match", ("actor", "recipient"))], binders)
        captured.append(_relational_preservation_capture(fixtures, request))
    atoms = lambda name, args, at: args[0] == args[1]
    assert [fixtures.evaluate(item[0]["native_ast"], atoms) for item in captured] == [True, False]
    projects = [_prepare_relational_preservation(item) for item in captured]
    assert projects[0] != projects[1]
    for item, project in zip(captured, projects):
        assert _validate_relational_preservation(item, project) == project
    with pytest.raises(ValueError):
        _validate_relational_preservation(captured[0], projects[1])


def test_relational_o_p_f_remain_distinct_unconstrained_interpretation_parameters(
        relational_preservation_fixtures):
    fixtures = relational_preservation_fixtures
    captured = {letter: _relational_preservation_capture(fixtures,
        fixtures.approval_request(sufficient=True, operator=letter)) for letter in ("O", "P", "F")}
    projects = {letter: _prepare_relational_preservation(item) for letter, item in captured.items()}
    assert len({owner.preparation_sha256(project) for project in projects.values()}) == 3
    for selected in ("O", "P", "F"):
        modal = lambda operator, body, at: operator == selected and body(at)
        assert {letter: fixtures.evaluate(item[0]["native_ast"], lambda *_: True, modal=modal)
                for letter, item in captured.items()} == {letter: letter == selected for letter in captured}
    for letter, item in captured.items():
        assert _validate_relational_preservation(item, projects[letter]) == projects[letter]


def _relational_exception_request(fixtures, *, drop_exception=False, guard_inside=False):
    builder = fixtures.Builder()
    guard = builder.atom("Eligible", "actor")
    declarations = [("Eligible", ("subject",))]
    if not drop_exception:
        exception = fixtures.ast.mk_not(builder.nid(), builder.atom("Exempt", "actor"))
        guard = builder.binary("and", guard, exception)
        declarations.append(("Exempt", ("subject",)))
    action = builder.atom("Assign", "actor", "recipient")
    declarations.append(("Assign", ("actor", "recipient")))
    body = (builder.modal("O", builder.binary("implies", guard, action)) if guard_inside
            else builder.binary("implies", guard, builder.modal("O", action)))
    return fixtures.request_for(builder, body, declarations,
                                [("actor", "forall"), ("recipient", "forall")])


@pytest.mark.parametrize("mutation", ["omitted", "scope"])
def test_relational_exception_presence_and_modal_scope_have_independent_countermodels(
        relational_preservation_fixtures, mutation):
    fixtures = relational_preservation_fixtures
    original = _relational_preservation_capture(fixtures, _relational_exception_request(fixtures))
    changed = _relational_preservation_capture(fixtures, _relational_exception_request(
        fixtures, drop_exception=mutation == "omitted", guard_inside=mutation == "scope"))
    if mutation == "omitted":
        atoms = lambda name, args, at: name in {"Eligible", "Exempt"}
        modal = lambda operator, body, at: body(at)
    else:
        atoms = lambda name, args, at: name == "Eligible" and at == 1
        modal = lambda operator, body, at: body(1)
    assert fixtures.evaluate(original[0]["native_ast"], atoms, modal=modal) is True
    assert fixtures.evaluate(changed[0]["native_ast"], atoms, modal=modal) is False
    projects = [_prepare_relational_preservation(item) for item in (original, changed)]
    assert projects[0] != projects[1]
    for item, project in zip((original, changed), projects):
        assert _validate_relational_preservation(item, project) == project
    with pytest.raises(ValueError):
        _validate_relational_preservation(original, projects[1])


def test_relational_resealed_generated_body_cannot_replace_whole_project_replay(
        relational_preservation_base):
    captured, original = relational_preservation_base
    meta, files = manifest(original), dict(original.files)
    path = next(name for name, text in files.items() if captured[0]["lean_body"] in text)
    changed_body = captured[0]["lean_body"].replace('"deontic:P"', '"deontic:O"')
    assert changed_body != captured[0]["lean_body"]
    files[path] = files[path].replace(captured[0]["lean_body"], changed_body, 1)
    meta["file_sha256"] = {name: sha(text.encode()) for name, text in sorted(files.items())}
    meta = corpus_contracts.seal_record({
        key: value for key, value in meta.items() if key not in {"record_cid", "cid_scope"}
    })
    changed = replace(original, manifest_json=canonical(meta).decode(), files=tuple(sorted(files.items())))
    with pytest.raises(ValueError):
        _validate_relational_preservation(captured, changed)


def test_relational_opt_in_does_not_widen_or_rewrite_legacy_unary_profile(
        base, relational_preservation_base):
    legacy_data, original = base
    captured, _ = relational_preservation_base
    assert owner.PROFILE == "native-unary-boolean-fol-json-value-preservation/v1"
    assert prepare(legacy_data) == original
    assert validate(legacy_data, original) == original
    fragment_raw = canonical(captured[0]["native_fragment"])
    with pytest.raises(ValueError):
        owner.prepare_native_ast_preservation(fragment_raw,
            expected_fragment_file_sha256=sha(fragment_raw), toolchain=TOOLCHAIN)


def test_relational_preparation_and_validation_never_run_a_native_process(
        relational_preservation_base):
    captured, _ = relational_preservation_base
    with patch.object(subprocess, "run", side_effect=AssertionError("process reached")), patch.object(
        subprocess, "Popen", side_effect=AssertionError("process reached")
    ):
        project = _prepare_relational_preservation(captured)
        assert _validate_relational_preservation(captured, project) == project


@pytest.fixture(scope="module")
def counted_preservation_fixtures():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).with_name("test_legal_counted_frame_v1.py")
    spec = importlib.util.spec_from_file_location("_preservation_existing_counted_fixtures", path)
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    return fixtures


def _counted_preservation_capture(fixtures, request=None):
    request = fixtures.counted.authored_counted_frame_request() if request is None else request
    return fixtures.prepare(request), canonical(request)


def _prepare_counted_preservation(captured, **overrides):
    report, raw = captured
    return owner.prepare_counted_ast_preservation(report, raw, **({
        "expected_report_sha256": sha(canonical(report)),
        "expected_request_sha256": sha(raw), "toolchain": TOOLCHAIN,
    } | overrides))


def _validate_counted_preservation(captured, preparation, **overrides):
    report, raw = captured
    return owner.validate_counted_ast_preservation(preparation, report, raw, **({
        "expected_preparation_sha256": owner.preparation_sha256(preparation),
        "expected_report_sha256": sha(canonical(report)),
        "expected_request_sha256": sha(raw), "toolchain": TOOLCHAIN,
    } | overrides))


@pytest.fixture(scope="module")
def counted_preservation_base(counted_preservation_fixtures):
    captured = _counted_preservation_capture(counted_preservation_fixtures)
    return captured, _prepare_counted_preservation(captured)


def test_counted_preservation_replays_full_sorted_ast_and_original_lowering(counted_preservation_base):
    captured, preparation = counted_preservation_base
    report, raw = captured
    before = deepcopy(captured)
    assert _validate_counted_preservation(captured, preparation) == preparation
    assert captured == before
    meta, files = manifest(preparation), dict(preparation.files)
    assert meta["profile"] == owner.COUNTED_PROFILE
    assert meta["typed_expression_sha256"] == report["typed_expression_sha256"]
    assert meta["typed_ast_node_count"] == 49
    assert meta["support_profile"]["sorts"] == ["Object", "EventFrame", "TimeFrame"]
    assert meta["support_profile"]["builtin_object_equality"] is True
    source = "\n".join(files.values())
    assert report["lean_body"] in source
    inputs = json.loads(files["preservation-inputs.json"])
    assert inputs["counted_report"] == report and inputs["original_request_raw_utf8"].encode() == raw
    assert len(files) == 7 and len(meta["expected_modules"]) == 4
    assert {name.rsplit(".", 1)[-1] for name in meta["theorems"]} == {
        "counted_value_exact", "counted_ast_closed", "counted_denotation_matches_lowering",
        "cap_two_counterexample", "cap_four_counterexample"}
    assert not any(meta["authority"].values())
    assert all(meta[field] is False for field in owner.FALSE_FLAGS)
    assert meta["training_mask"] == meta["evaluation_gold_mask"] == 0


@pytest.mark.parametrize("field", ["expected_report_sha256", "expected_request_sha256"])
@pytest.mark.parametrize("pin", ["0" * 64, "A" * 64, None, True])
def test_counted_preservation_needs_independent_input_commitments(counted_preservation_base, field, pin):
    captured, _ = counted_preservation_base
    with pytest.raises(ValueError):
        _prepare_counted_preservation(captured, **{field: pin})


@pytest.mark.parametrize("damage", ["expression", "body", "maximum", "producer", "authority", "extra"])
def test_counted_resealed_report_cannot_replace_original_fixed_subject(counted_preservation_base, damage):
    captured, _ = counted_preservation_base
    report, raw = deepcopy(captured)
    if damage == "expression":
        report["typed_expression"]["root"]["binders"][0]["name"] = "changed_event"
    elif damage == "body": report["lean_body"] += "\n-- replacement\n"
    elif damage == "maximum": report["maximum"] = 2
    elif damage == "producer": report["producer_pins"]["/untrusted/never-open-this.py"] = "0" * 64
    elif damage == "authority": report["authority"]["accepted"] = True
    else: report["unrecognized"] = True
    with pytest.raises(ValueError):
        _prepare_counted_preservation((report, raw))


def test_counted_finite_boundaries_are_semantic_specs_not_schema_refusals(
        counted_preservation_base, counted_preservation_fixtures):
    captured, preparation = counted_preservation_base
    request = json.loads(captured[1])
    fixtures = counted_preservation_fixtures
    # Independent existing evaluator interprets the actual sorted AST. The
    # proposed Lean obligations separately compare cap2 and cap4, without
    # presenting an unexecuted proof as observed or a schema error as semantics.
    assert fixtures.truth(request, [(i, "e", "t") for i in range(3)], objects=(0, 1, 2))
    assert not fixtures.truth(request, [(i, "e", "t") for i in range(4)])
    specs = manifest(preparation)["counterfactual_boundary_specs"]
    assert [(r["actual_counted_denotation"], r["counterfactual_cap"], r["counterfactual_denotation"])
            for r in specs] == [(True, 2, False), (False, 4, True)]
    assert all(r["proof_observed"] is False for r in specs)


def test_counted_preservation_retains_arbitrary_physical_identity_values(counted_preservation_fixtures):
    fixtures = counted_preservation_fixtures
    request = fixtures.counted.authored_counted_frame_request()
    for index, node in enumerate(fixtures.nodes(request["expression"]["root"])):
        node["node_id"] = "fictional:counted:node:" + str(index)
    request["expression"]["expression_id"] = "fictional:counted:expression"
    request["expression"]["signature"]["signature_id"] = "fictional:counted:signature"
    captured = _counted_preservation_capture(fixtures, fixtures.reseal(request))
    preparation = _prepare_counted_preservation(captured)
    assert _validate_counted_preservation(captured, preparation) == preparation
    assert "fictional:counted:node:" in "\n".join(body for _, body in preparation.files)


def test_counted_generated_bound_cannot_be_resealed_as_original_preservation(counted_preservation_base):
    captured, original = counted_preservation_base
    meta, files = manifest(original), dict(original.files)
    path = next(name for name, text in files.items() if captured[0]["lean_body"] in text)
    files[path] = files[path].replace("x0 = x1", "x0 = x0", 1)
    assert files[path] != dict(original.files)[path]
    meta["file_sha256"] = {name: sha(text.encode()) for name, text in sorted(files.items())}
    meta = corpus_contracts.seal_record({key: value for key, value in meta.items()
                                       if key not in {"record_cid", "cid_scope"}})
    changed = replace(original, manifest_json=canonical(meta).decode(), files=tuple(sorted(files.items())))
    with pytest.raises(ValueError):
        _validate_counted_preservation(captured, changed)


def test_counted_preparation_keeps_compiler_execution_separate(counted_preservation_base):
    captured, _ = counted_preservation_base
    with patch.object(subprocess, "run", side_effect=AssertionError("process reached")), patch.object(
        subprocess, "Popen", side_effect=AssertionError("process reached")):
        preparation = _prepare_counted_preservation(captured)
        assert _validate_counted_preservation(captured, preparation) == preparation


def test_relational_and_counted_preservation_modules_can_coexist(
        relational_preservation_base, counted_preservation_base):
    # Distinct semantic libraries must not reuse one module path with different
    # bodies when the existing shared corpus owner composes their projects.
    relational = relational_preservation_base[1]
    counted = counted_preservation_base[1]
    left = {name for name, _ in relational.files if name.endswith(".lean")}
    right = {name for name, _ in counted.files if name.endswith(".lean")}
    assert not left & right
    assert manifest(relational)["expected_modules"][0].startswith(owner.RELATIONAL_PROJECT_ROOT + ".")
    assert manifest(counted)["expected_modules"][0].startswith(owner.COUNTED_PROJECT_ROOT + ".")
    assert owner.PROJECT_ROOT == "LegalNativeAstPreservation"


@pytest.mark.parametrize("operator", ["O", "P", "F"])
@pytest.mark.parametrize("damage", ["wrong_key", "legacy_concat", "unsupported_default"])
def test_relational_literal_modal_denotation_cannot_be_replaced_by_resealed_templates(
        relational_preservation_fixtures, operator, damage):
    # Actual installed-Lean O/P/F cases separately check axiom dependencies.
    # Here the existing independent evaluator fixes the meanings; whole replay
    # refuses even hash-resealed alternate proof-witness templates.
    fixtures = relational_preservation_fixtures
    captured = _relational_preservation_capture(fixtures,
        fixtures.approval_request(sufficient=True, operator=operator))
    preparation = _prepare_relational_preservation(captured)
    assert _validate_relational_preservation(captured, preparation) == preparation
    for selected in ("O", "P", "F"):
        modal = lambda letter, body, at: letter == selected and body(at)
        assert fixtures.evaluate(captured[0]["native_ast"], lambda *_: True, modal=modal) is (operator == selected)
    meta, files = manifest(preparation), dict(preparation.files)
    assert len(meta["theorems"]) == 5
    assert captured[0]["lean_body"] in "\n".join(files.values())
    semantics = owner.RELATIONAL_SEMANTICS
    if damage == "wrong_key":
        other = {"O": "P", "P": "F", "F": "O"}[operator]
        changed_semantics = semantics.replace('some "deontic:' + operator + '"',
                                              'some "deontic:' + other + '"', 1)
    elif damage == "legacy_concat":
        start = semantics.index("def relationalNativeModalKey ")
        end = semantics.index("\ndef relDenote ", start)
        changed_semantics = (semantics[:start]
            + 'def relationalNativeModalKey (operator : String) : Option String :=\n'
            + '  some ("deontic:" ++ operator)\n' + semantics[end:])
    else:
        changed_semantics = semantics.replace('if operator = "F" then some "deontic:F" else none',
            'if operator = "F" then some "deontic:F" else some "deontic:' + operator + '"', 1)
    assert changed_semantics != semantics
    path = owner.RELATIONAL_PROJECT_ROOT + "/Semantics.lean"
    assert files[path].count(semantics) == 1
    files[path] = files[path].replace(semantics, changed_semantics, 1)
    meta["semantics_sha256"] = sha(changed_semantics.encode())
    meta["file_sha256"] = {name: sha(text.encode()) for name, text in sorted(files.items())}
    meta = corpus_contracts.seal_record({key: value for key, value in meta.items()
                                       if key not in {"record_cid", "cid_scope"}})
    changed = replace(preparation, manifest_json=canonical(meta).decode(), files=tuple(sorted(files.items())))
    with pytest.raises(ValueError):
        _validate_relational_preservation(captured, changed)


@pytest.mark.parametrize("operator", ["", "o", "X", "OP", "deontic:O", "obligation"])
def test_unsupported_relational_modal_keys_refuse_before_lazy_operation_owners(
        relational_preservation_base, relational_preservation_fixtures, operator):
    report, raw = deepcopy(relational_preservation_base[0])
    def nodes(value):
        if type(value) is dict:
            yield value
            for child in value.values():
                yield from nodes(child)
        elif type(value) is list:
            for child in value:
                yield from nodes(child)
    modal = next(node for node in nodes(report["native_fragment"]["native_ast"])
                 if node.get("node_type") == "DeonticFormula")
    modal["operator"]["value"] = operator
    fixtures = relational_preservation_fixtures
    with patch.object(owner, "_owners", side_effect=AssertionError("operation owner reached")), \
            patch.object(fixtures.bridge, "validate_relational_norm_v1",
                         side_effect=AssertionError("original relational validator reached")):
        with pytest.raises(ValueError, match="unsupported exact native enum/operator"):
            _prepare_relational_preservation((report, raw))


@pytest.mark.parametrize("profile,theorem", [
    ("relational", "denotation_matches_native"),
    ("relational", "role_denotation_matches_native"),
    ("counted", "counted_denotation_matches_lowering"),
])
@pytest.mark.parametrize("proof_replacement", ["legacy_rfl", "propext_cast"])
def test_equivalence_proof_replay_rejects_resealed_legacy_or_axiomatic_replacement(
        relational_preservation_base, counted_preservation_base, profile, theorem, proof_replacement):
    # The installed-Lean tests separately check actual empty axiom reports.
    # Here even a fully resealed alternate proof cannot substitute for the
    # exact current project: a logically reflexive propext cast still escapes
    # the required empty-axiom contract, while the retained legacy generation had nonempty
    # dependency reports; String.append in the denotation type is repaired separately. No compiler result is manufactured by this test.
    captured, preparation = (relational_preservation_base if profile == "relational"
                             else counted_preservation_base)
    meta, files = manifest(preparation), dict(preparation.files)
    qualified = next(name for name in meta["theorems"] if name.rsplit(".", 1)[-1] == theorem)
    path = qualified.rsplit(".", 1)[0].replace(".", "/") + ".lean"
    source = files[path]
    start = source.index("theorem " + theorem + " ")
    end = source.index("#print axioms " + theorem, start)
    declaration = source[start:end]
    statement, _ = declaration.rsplit(" := by\n", 1)
    term = ("  rfl\n" if proof_replacement == "legacy_rfl" else
            "  exact Iff.of_eq (propext (Iff.intro (fun h => h) (fun h => h)))\n")
    replacement = statement + " := by\n" + term
    assert replacement != declaration
    files[path] = source[:start] + replacement + source[end:]
    assert "#print axioms " + theorem in files[path]
    assert manifest(preparation)["theorems"] == meta["theorems"]
    meta["file_sha256"] = {name: sha(text.encode()) for name, text in sorted(files.items())}
    meta = corpus_contracts.seal_record({key: value for key, value in meta.items()
                                       if key not in {"record_cid", "cid_scope"}})
    changed = replace(preparation, manifest_json=canonical(meta).decode(),
                      files=tuple(sorted(files.items())))
    validator = (_validate_relational_preservation if profile == "relational"
                 else _validate_counted_preservation)
    with pytest.raises(ValueError):
        validator(captured, changed)


@pytest.mark.parametrize("declaration", ["countedVariableValue", "countedVariableClosed",
    "countedObjectValue", "countedEventValue", "countedTimeValue"])
def test_counted_reserved_lean_binders_cannot_reenter_a_resealed_preparation(
        counted_preservation_base, declaration):
    # Actual Lean rejected `variable` as a binder in the retained native v01.
    # Replay must also reject reintroduction into any one of the five functions.
    captured, preparation = counted_preservation_base
    meta, files = manifest(preparation), dict(preparation.files)
    path = owner.COUNTED_PROJECT_ROOT + "/Semantics.lean"
    semantics = owner.COUNTED_SEMANTICS
    start = semantics.index("def " + declaration + " ")
    end = semantics.index("\ndef ", start + 1)
    definition = semantics[start:end]
    assert "(boundVariable : CountedVariable)" in definition
    legacy = definition.replace("boundVariable", "variable")
    changed_semantics = semantics[:start] + legacy + semantics[end:]
    files[path] = files[path].replace(semantics, changed_semantics, 1)
    meta["semantics_sha256"] = sha(changed_semantics.encode())
    meta["file_sha256"] = {name: sha(body.encode()) for name, body in sorted(files.items())}
    meta = corpus_contracts.seal_record({key: value for key, value in meta.items()
                                       if key not in {"record_cid", "cid_scope"}})
    changed = replace(preparation, manifest_json=canonical(meta).decode(), files=tuple(sorted(files.items())))
    with pytest.raises(ValueError):
        _validate_counted_preservation(captured, changed)



# Reuse the existing complete fictional V3 admission/graph fixture. This test
# reaches the missing preservation interface only after genuine positive replay.
def test_mixed_preservation_requires_explicit_profile_after_genuine_reviewed_graph(
        tmp_path_factory):
    from tests.unit.logic.autoformal import test_corpus_norm_definition_adapter as graph_fixture
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational

    baseline = graph_fixture.reviewed_graph_baseline_v3.__wrapped__(tmp_path_factory)
    baseline["helper"].assert_signatures_valid(baseline["case"])
    admission = baseline["admission"]
    assert admission["semantic_use_eligible"] is True and admission["fixture_only"] is True
    assert admission["blockers"] == []
    assert {"formalization", "proof_obligation"} <= set(admission["permitted_uses"])
    graph = graph_fixture.build_reviewed_graph_fixture_v3(baseline)
    assert graph_fixture.validate_reviewed_graph_fixture_v3(baseline, graph) == graph
    assert graph["schema"] == "legal-corpus-reviewed-norm-candidate-graph/v3"
    assert len(graph["unit_records"]) == len(graph["ast_records"]) == len(admission["units"]) == 3
    assert graph["semantic_use_eligible"] is False and not any(graph["authority"].values())
    assert all(type(graph[key]) is int and graph[key] == 0
               for key in ("training_mask", "evaluation_gold_mask"))

    declaration = baseline["case"]["declaration"]
    selected = [(index, unit) for index, unit in enumerate(declaration["units"])
                if unit["relational_profile"] == relational.MIXED_PROFILE]
    assert len(selected) == 1
    index, unit = selected[0]
    inputs = baseline["case"]["relational_inputs"][unit["unit_id"]]
    report, raw = inputs["report"], inputs["request_raw"]
    original_report = canonical(report)
    checked = relational.validate_mixed_relational_norm_v1(report, raw,
        expected_report_sha256=inputs["expected_report_sha256"],
        expected_request_sha256=unit["relational_request_sha256"])
    assert checked == report and canonical(report) == original_report
    assert report["native_ast"] is None and report["native_parser_roundtrip"] is False
    assert report["native_build_executed"] is False and report["source_bound"] is False
    assert {row["name"] for row in report["typed_expression"]["signature"]["sorts"]} == {
        "Bool", "Object", "EventFrame", "TimeFrame"}
    complete_ir = json.loads(graph["ast_records"][index]["ast_json"])
    assert canonical(complete_ir) == canonical(admission["units"][index]["canonical_ir"])
    assert canonical(complete_ir["typed_expression"]) == canonical(report["typed_expression"])
    assert complete_ir["argument_roles"] == report["argument_roles"]
    assert complete_ir["source_binding"]["source_version_cid"] == unit["source_version"]["record_cid"]
    assert complete_ir["source_binding"]["occurrence_cid"] == unit["occurrence"]["record_cid"]

    # Existing Object/native-fragment preservation must keep its narrower domain.
    with pytest.raises(ValueError, match="exact closed original relational native fragment fields required"):
        owner.prepare_relational_ast_preservation(report, raw,
            expected_report_sha256=inputs["expected_report_sha256"],
            expected_request_sha256=unit["relational_request_sha256"],
            toolchain=TOOLCHAIN)
    assert canonical(report) == original_report
    assert callable(getattr(owner, "prepare_mixed_relational_ast_preservation", None)), (
        "explicit concrete mixed-sort preservation builder missing after accepted V3 admission and graph replay")

    captured = {"report": report, "request_raw": raw}
    prepared = _prepare_mixed_preservation(captured)
    assert _validate_mixed_preservation(captured, prepared) == prepared
    meta = manifest(prepared)
    assert meta["mixed_report_sha256"] == inputs["expected_report_sha256"]
    assert meta["source_custody"]["reviewed_admission_or_graph_replayed"] is False
    assert meta["native_ast"] is None and meta["native_parser_roundtrip"] is False
    assert not any(meta["authority"].values())


MIXED_THEOREM_SUFFIXES = (
    "mixed_typed_value_exact", "mixed_renderer_value_exact", "mixed_ast_closed",
    "mixed_denotation_matches_lowering", "mixed_role_denotation_matches_lowering",
)


@pytest.fixture(scope="module")
def mixed_preservation_fixtures():
    from tests.unit.logic.autoformal import test_legal_relational_norm_v1 as fixtures
    return fixtures


def _mixed_preservation_capture(fixtures, request=None):
    request = fixtures.mixed_member_request() if request is None else request
    raw = canonical(request)
    report = fixtures.bridge.prepare_mixed_relational_norm_v1(
        raw, expected_request_sha256=sha(raw))
    return {"report": report, "request_raw": raw, "request": request}


def _prepare_mixed_preservation(captured, **overrides):
    return owner.prepare_mixed_relational_ast_preservation(
        captured["report"], captured["request_raw"], **({
            "expected_report_sha256": sha(canonical(captured["report"])),
            "expected_request_sha256": sha(captured["request_raw"]),
            "toolchain": TOOLCHAIN,
        } | overrides))


def _validate_mixed_preservation(captured, preparation, **overrides):
    return owner.validate_mixed_relational_ast_preservation(
        preparation, captured["report"], captured["request_raw"], **({
            "expected_preparation_sha256": owner.preparation_sha256(preparation),
            "expected_report_sha256": sha(canonical(captured["report"])),
            "expected_request_sha256": sha(captured["request_raw"]),
            "toolchain": TOOLCHAIN,
        } | overrides))


@pytest.fixture(scope="module")
def mixed_preservation_base(mixed_preservation_fixtures):
    captured = _mixed_preservation_capture(mixed_preservation_fixtures)
    return captured, _prepare_mixed_preservation(captured)


def _mixed_reseal(preparation, meta, files):
    meta = deepcopy(meta)
    meta["file_sha256"] = {path: sha(text.encode()) for path, text in sorted(files.items())}
    meta = corpus_contracts.seal_record({key: value for key, value in meta.items()
        if key not in {"record_cid", "cid_scope"}})
    return replace(preparation, manifest_json=canonical(meta).decode(), files=tuple(sorted(files.items())))


def test_mixed_preservation_retains_complete_values_roles_and_five_exact_obligations(mixed_preservation_base):
    captured, prepared = mixed_preservation_base
    report, raw = captured["report"], captured["request_raw"]
    before = deepcopy(captured)
    assert _validate_mixed_preservation(captured, prepared) == prepared and captured == before
    meta, files = manifest(prepared), dict(prepared.files)
    assert owner.MIXED_PROFILE == "typed-many-sorted-relational-deontic-renderer-preservation/v1"
    assert meta["profile"] == owner.MIXED_PROFILE
    assert owner.MIXED_PROJECT_ROOT == "LegalMixedRelationalAstPreservation"
    assert len(files) == 7 and len(meta["expected_modules"]) == 4
    instance = meta["expected_modules"][2]
    assert meta["theorems"] == [instance + "." + suffix for suffix in MIXED_THEOREM_SUFFIXES]
    body = files[instance.replace(".", "/") + ".lean"]
    assert report["lean_body"] in body
    assert all(body.count("#print axioms " + suffix + "\n") == 1 for suffix in MIXED_THEOREM_SUFFIXES)
    assert "mixedDenote i typedMixedAst emptyCountedEnvironment t ↔ formula i t" in body
    assert "mixedRoleDenote base atoms mixedArgumentRoles typedMixedAst" in body
    assert "formula (mixedRoleInterpretation base atoms mixedArgumentRoles) t" in body
    inputs = json.loads(files["preservation-inputs.json"])
    assert inputs["mixed_report"] == report and inputs["original_request_raw_utf8"].encode() == raw
    assert inputs["schema"] == owner.MIXED_INPUT_SCHEMA
    for key, value in {
        "mixed_report_sha256": sha(canonical(report)), "original_request_sha256": sha(raw),
        "typed_expression_sha256": report["typed_expression_sha256"],
        "typed_expression_content_digest": report["typed_expression_content_digest"],
        "argument_roles_sha256": sha(canonical(report["argument_roles"])),
        "renderer_ast_sha256": report["renderer_ast_sha256"],
        "lean_body_sha256": sha(report["lean_body"].encode()),
        "typed_ast_node_count": report["counts"]["nodes"],
    }.items():
        assert meta[key] == value
    assert meta["support_profile"]["max_ast_nodes"] == 512
    assert meta["support_profile"]["max_ast_depth"] == 48
    assert meta["native_ast"] is None
    assert meta["native_TDFOL_route_used"] is meta["native_parser_roundtrip"] is False
    assert meta["preparation_only"] is True and all(value is False for value in meta["authority"].values())
    assert all(meta[key] is False for key in owner.FALSE_FLAGS)
    assert all(meta[key] is False for key in ("typed_ast_value_preservation_proved",
        "renderer_ast_value_preservation_proved", "mixed_ast_denotation_preservation_proved",
        "ordered_role_denotation_preservation_proved"))
    assert all(type(meta[key]) is int and meta[key] == 0 for key in ("training_mask", "evaluation_gold_mask"))
    assert meta["source_custody"]["original_source_bundle_replayed"] is False
    assert meta["source_custody"]["source_prose_to_ast_proved"] is False


@pytest.mark.parametrize("field", ["expected_report_sha256", "expected_request_sha256"])
@pytest.mark.parametrize("pin", ["0" * 64, "A" * 64, "short", None, True])
def test_mixed_preservation_independent_pins_precede_lazy_owners(mixed_preservation_base, field, pin):
    captured, _ = mixed_preservation_base
    with patch.object(owner, "_owners", side_effect=AssertionError("lazy operation reached")):
        with pytest.raises(ValueError):
            _prepare_mixed_preservation(captured, **{field: pin})


@pytest.mark.parametrize("field", ["expected_preparation_sha256", "expected_report_sha256", "expected_request_sha256"])
def test_mixed_preservation_validation_requires_all_three_independent_pins(mixed_preservation_base, field):
    captured, prepared = mixed_preservation_base
    with patch.object(owner, "_owners", side_effect=AssertionError("lazy operation reached")):
        with pytest.raises(ValueError):
            _validate_mixed_preservation(captured, prepared, **{field: "0" * 64})


@pytest.mark.parametrize("damage", ["typed_argument", "roles", "renderer", "lean_body", "request_echo",
    "producer", "counts", "source_bound", "parser_roundtrip", "renderer_digest"])
def test_mixed_preservation_rehashed_report_cannot_replace_fresh_original_replay(mixed_preservation_base, damage):
    captured = deepcopy(mixed_preservation_base[0])
    report = captured["report"]
    if damage == "typed_argument":
        report["typed_expression"]["root"]["arguments"][0]["arguments"][0]["binders"][0]["name"] = "other_moment"
    elif damage == "roles":
        report["argument_roles"][0]["roles"][0] = "other_actor"
    elif damage == "renderer":
        report["renderer_ast"]["root"]["quantifier"]["value"] = "∃"
    elif damage == "lean_body":
        report["lean_body"] = report["lean_body"].replace("∀", "∃", 1)
    elif damage == "request_echo":
        report["request_raw_utf8"] += "\n"
    elif damage == "producer":
        report["producer_pins"]["/fixture/offered-producer-must-not-be-authoritative.py"] = "0" * 64
    elif damage == "counts":
        report["counts"]["nodes"] += 1
    elif damage == "source_bound":
        report["source_bound"] = True
    elif damage == "parser_roundtrip":
        report["native_parser_roundtrip"] = True
    else:
        report["renderer_ast_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        _prepare_mixed_preservation(captured)


@pytest.mark.parametrize("damage", ["native_ast", "parser_roundtrip", "expression_metadata", "signature_metadata",
    "unknown_sort", "missing_roles", "unsupported_constructor", "bad_toolchain"])
def test_mixed_preservation_unsupported_shapes_refuse_before_lazy_owners(mixed_preservation_base, damage):
    captured = deepcopy(mixed_preservation_base[0])
    report = captured["report"]
    override = {}
    if damage == "native_ast": report["native_ast"] = {}
    elif damage == "parser_roundtrip": report["native_parser_roundtrip"] = True
    elif damage == "expression_metadata": report["typed_expression"]["metadata"] = {"hidden": "source"}
    elif damage == "signature_metadata": report["typed_expression"]["signature"]["metadata"] = {"trusted": "true"}
    elif damage == "unknown_sort": report["typed_expression"]["signature"]["sorts"][1]["name"] = "CivilDate"
    elif damage == "missing_roles": report["argument_roles"] = []
    elif damage == "unsupported_constructor": report["typed_expression"]["root"]["kind"] = "true"
    else: override["toolchain"] = "leanprover/lean4:latest"
    with patch.object(owner, "_owners", side_effect=AssertionError("lazy operation reached")):
        with pytest.raises(ValueError):
            _prepare_mixed_preservation(captured, **override)


@pytest.mark.parametrize("damage", ["typed_source_value", "renderer_value", "typed_ast", "roles", "sorts",
    "vacuous_theorem", "axiomatic_proof", "semantics_modal_key", "extra_import", "source_binding",
    "promoted_flags", "toolchain_file"])
def test_mixed_preservation_resealed_complete_project_requires_regeneration(mixed_preservation_base, damage):
    captured, prepared = mixed_preservation_base
    meta, files = manifest(prepared), dict(prepared.files)
    path = meta["expected_modules"][2].replace(".", "/") + ".lean"
    body = files[path]
    if damage in {"typed_source_value", "renderer_value", "typed_ast", "roles", "sorts"}:
        symbol, before, after, digest = {
            "typed_source_value": ("actualMixedSourceValue", '"Member"', '"ChangedMember"', "actual_typed_and_roles_lean_value_sha256"),
            "renderer_value": ("actualMixedRendererValue", '"Member"', '"ChangedMember"', "actual_renderer_lean_value_sha256"),
            "typed_ast": ("typedMixedAst", '"Member"', '"ChangedMember"', "typed_source_lean_value_sha256"),
            "roles": ("mixedArgumentRoles", '"actor"', '"other_actor"', "ordered_roles_lean_value_sha256"),
            "sorts": ("mixedSortOrder", ".object", ".event", "source_sort_order_lean_value_sha256"),
        }[damage]
        start = body.index("def " + symbol + " ")
        end = body.index("\n", start)
        definition = body[start:end]
        assert before in definition
        changed = definition.replace(before, after, 1)
        files[path] = body[:start] + changed + body[end:]
        meta[digest] = sha(changed.rsplit(" := ", 1)[1].encode())
    elif damage in {"vacuous_theorem", "axiomatic_proof"}:
        suffix = "mixed_denotation_matches_lowering"
        start = body.index("theorem " + suffix + " ")
        end = body.index("#print axioms " + suffix, start)
        if damage == "vacuous_theorem":
            replacement = "theorem " + suffix + " : True := by\n  trivial\n"
        else:
            declaration = body[start:end]
            statement = declaration.rsplit(" := by\n", 1)[0]
            replacement = statement + " := by\n  exact Iff.of_eq (propext (Iff.intro (fun h => h) (fun h => h)))\n"
        files[path] = body[:start] + replacement + body[end:]
        assert meta["theorems"] == manifest(prepared)["theorems"]
    elif damage == "semantics_modal_key":
        semantics_path = owner.MIXED_PROJECT_ROOT + "/Semantics.lean"
        old = owner.MIXED_SEMANTICS
        assert '"deontic:O"' in old
        changed = old.replace('"deontic:O"', '"deontic:P"', 1)
        files[semantics_path] = files[semantics_path].replace(old, changed, 1)
        meta["semantics_sha256"] = sha(changed.encode())
    elif damage == "extra_import":
        files[path] = "import Lean\n" + body
        meta["module_imports"][meta["expected_modules"][2]].insert(0, "Lean")
    elif damage == "source_binding":
        meta["mixed_report_sha256"] = "0" * 64
    elif damage == "promoted_flags":
        meta["typed_ast_value_preservation_proved"] = True
        meta["authority"]["proof"] = True
    else:
        files["lean-toolchain"] = "leanprover/lean4:v4.34.2\n"
        meta["toolchain"] = "leanprover/lean4:v4.34.2"
    changed = _mixed_reseal(prepared, meta, files)
    assert changed != prepared
    with pytest.raises(ValueError):
        _validate_mixed_preservation(captured, changed)


@pytest.mark.parametrize("damage", ["caller", "detached", "fresh_return", "producer", "policy", "source_code"])
def test_mixed_preservation_fences_inputs_fresh_return_and_current_producers(mixed_preservation_base,
        mixed_preservation_fixtures, monkeypatch, damage):
    from functools import wraps
    from pathlib import Path
    captured = deepcopy(mixed_preservation_base[0])
    relational = mixed_preservation_fixtures.bridge
    original = relational.validate_mixed_relational_norm_v1
    actual_read = Path.read_bytes
    original_owner_path = Path(owner.__file__).resolve()
    original_owner_bytes = actual_read(original_owner_path)
    reached = []
    @wraps(original)
    def changed_after_original(detached, raw, **kwargs):
        checked = original(detached, raw, **kwargs)
        reached.append(True)
        if damage == "caller": captured["report"]["source_bound"] = True
        elif damage == "detached": detached["source_bound"] = True
        elif damage == "fresh_return": checked["source_bound"] = True
        elif damage == "producer":
            from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as emit
            monkeypatch.setattr(emit, "sorted_relational_document", lambda *a, **k: None)
        elif damage == "policy": monkeypatch.setattr(owner, "MAX_MIXED_AST_NODES", 511)
        else:
            monkeypatch.setattr(Path, "read_bytes", lambda path:
                original_owner_bytes + b"\n# changed observation\n" if path.resolve() == original_owner_path else actual_read(path))
        return checked
    monkeypatch.setattr(relational, "validate_mixed_relational_norm_v1", changed_after_original)
    with pytest.raises(ValueError):
        _prepare_mixed_preservation(captured)
    assert reached == [True]


def test_mixed_preservation_role_only_change_keeps_same_renderer_but_distinct_subject(mixed_preservation_base,
        mixed_preservation_fixtures):
    captured, prepared = mixed_preservation_base
    request = deepcopy(captured["request"])
    request["argument_roles"][0]["roles"][0] = "regulated_subject"
    changed = _mixed_preservation_capture(mixed_preservation_fixtures, request)
    assert changed["report"]["lean_body"] == captured["report"]["lean_body"]
    assert changed["report"]["renderer_ast"] == captured["report"]["renderer_ast"]
    assert changed["report"]["typed_expression"] == captured["report"]["typed_expression"]
    current = _prepare_mixed_preservation(changed)
    assert _validate_mixed_preservation(changed, current) == current
    old_meta, new_meta = manifest(prepared), manifest(current)
    for key in ("mixed_report_sha256", "original_request_sha256", "argument_roles_sha256",
                "ordered_roles_lean_value_sha256"):
        assert old_meta[key] != new_meta[key]
    assert old_meta["expected_modules"][2] != new_meta["expected_modules"][2]
    with pytest.raises(ValueError):
        _validate_mixed_preservation(changed, prepared)


def _mixed_sorted_request(fixtures, *, mode="grammar", modal="O", altered=False):
    ast, sig, b = fixtures.ast, fixtures.signatures, fixtures.Builder()
    sorts = {name: sig.LogicSort(name) for name in ("Object", "EventFrame", "TimeFrame")}
    names = {"x": "Object", "y": "Object", "event": "EventFrame", "moment": "TimeFrame"}
    def var(name): return ast.mk_variable(b.nid(), name, sorts[names[name]])
    def atom(name, *variables): return ast.mk_predicate(b.nid(), name, [var(v) for v in variables])
    def eq(left, right): return ast.mk_equality(b.nid(), var(left), var(right))
    declarations = [("Link", ("Object", "Object"), ("actor", "recipient"))]
    quantified = [("x", "forall"), ("y", "exists")]
    if mode == "grammar":
        declarations += [("Guard", ("Object",), ("subject",)), ("Excepted", ("Object",), ("subject",))]
        condition = b.binary("and", atom("Guard", "x"), ast.mk_not(b.nid(), atom("Excepted", "x")))
        equality = b.binary("or", eq("x", "y"), b.binary("and", eq("event", "event"), eq("moment", "moment")))
        body = b.binary("implies", condition, b.modal(modal, b.binary("iff", atom("Link", "x", "y"), equality)))
    elif mode == "actor_order":
        body = atom("Link", *( ("y", "x") if altered else ("x", "y") ))
    elif mode == "quantifier_order":
        body = atom("Link", "x", "y")
        if altered: quantified = [("y", "exists"), ("x", "forall")]
    elif mode == "exception":
        quantified = [("x", "forall"), ("y", "forall")]
        body = atom("Link", "x", "y")
        if not altered:
            declarations += [("Excepted", ("Object",), ("subject",))]
            body = b.binary("implies", ast.mk_not(b.nid(), atom("Excepted", "x")), body)
    elif mode == "modal_scope":
        declarations += [("Guard", ("Object",), ("subject",))]
        guarded = b.binary("implies", atom("Guard", "x"), atom("Link", "x", "y")) if altered else None
        body = b.modal("O", guarded) if altered else b.binary("implies", atom("Guard", "x"), b.modal("O", atom("Link", "x", "y")))
    else:
        assert mode == "modality"
        body = b.modal("P" if altered else "O", atom("Link", "x", "y"))
    for name, quantifier in reversed([("event", "forall"), ("moment", "forall")] + quantified):
        body = (ast.mk_forall if quantifier == "forall" else ast.mk_exists)(b.nid(),
            [ast.Binder(name, sorts[names[name]])], body)
    signature = sig.LogicSignature("fixture:mixed-preservation:" + mode, family="tdfol", profile="tdfol_default",
        sorts=tuple(sorts.values()), symbols=tuple(sig.declare_predicate(name,
            tuple(sorts[sort] for sort in domain)) for name, domain, _ in declarations))
    expression = ast.TypedExpression("fixture:mixed-preservation:" + mode, body, signature)
    return {"schema": fixtures.bridge.MIXED_REQUEST_SCHEMA, "profile": fixtures.bridge.MIXED_PROFILE,
        "interpretation_status": "authored_unreviewed_declaration", "expression": expression.to_dict(),
        "argument_roles": [{"symbol": name, "roles": list(roles)} for name, _, roles in declarations],
        "source_binding": None}


@pytest.mark.parametrize("modal", ["O", "P", "F"])
def test_mixed_preservation_covers_full_closed_sorted_boolean_and_modal_grammar(mixed_preservation_fixtures, modal):
    fixtures = mixed_preservation_fixtures
    captured = _mixed_preservation_capture(fixtures, _mixed_sorted_request(fixtures, modal=modal))
    prepared = _prepare_mixed_preservation(captured)
    assert _validate_mixed_preservation(captured, prepared) == prepared
    report = captured["report"]
    kinds = {node["kind"] for _, node in fixtures._mixed_typed_nodes(report["typed_expression"]["root"])}
    assert {"predicate", "equality", "not", "and", "or", "implies", "iff", "forall", "exists", "extension"} <= kinds
    assert report["counts"]["equality_occurrences"] == 3
    assert 'i.modal "deontic:' + modal + '" [] none' in report["lean_body"]
    meta = manifest(prepared)
    assert meta["typed_ast_node_count"] == report["counts"]["nodes"] <= 512
    assert meta["support_profile"]["source_carriers_may_be_empty"] is True


@pytest.mark.parametrize("facet", ["actor_order", "quantifier_order", "exception", "modal_scope", "modality"])
def test_mixed_preservation_retains_independent_semantic_countermodels(mixed_preservation_fixtures, facet):
    fixtures = mixed_preservation_fixtures
    rows = [_mixed_preservation_capture(fixtures, _mixed_sorted_request(fixtures, mode=facet, altered=altered))
            for altered in (False, True)]
    domains = {"Object": (0, 1), "EventFrame": ("event",), "TimeFrame": ("authored-time",)}
    def atoms(name, values, ambient):
        if facet == "actor_order": return values[0] == 0
        if facet == "quantifier_order": return values[0] == values[1]
        if facet == "exception": return name == "Excepted"
        if facet == "modal_scope": return name == "Guard" and ambient == 1
        return True
    def modal(operator, body, ambient):
        if facet == "modal_scope": return body(1)
        if facet == "modality": return operator == "O" and body(ambient)
        return body(ambient)
    observed = []
    for row in rows:
        prepared = _prepare_mixed_preservation(row)
        assert _validate_mixed_preservation(row, prepared) == prepared
        original = fixtures._mixed_typed_truth(row["request"]["expression"]["root"], domains, atoms, modal)
        rendered = fixtures._mixed_renderer_truth(row["report"]["renderer_ast"]["root"], domains, atoms, modal)
        assert original == rendered
        observed.append(original)
    assert observed == ([False, True] if facet == "actor_order" else [True, False])


@pytest.fixture(scope="module")
def mixed_retained_preservation_reports(mixed_preservation_fixtures, tmp_path_factory):
    # Retain the existing fixture's seven real DATA writes and exact packet pin.
    return mixed_preservation_fixtures.mixed_retained_reports.__wrapped__(tmp_path_factory)


@pytest.mark.parametrize("alternative", [0, 1])
def test_mixed_preservation_replays_both_complete_unselected_retained_alternatives(
        mixed_retained_preservation_reports, alternative):
    row = mixed_retained_preservation_reports[alternative]
    captured = {"report": row["report"], "request_raw": row["request_raw"], "request": row["request"]}
    prepared = _prepare_mixed_preservation(captured)
    assert _validate_mixed_preservation(captured, prepared) == prepared
    meta = manifest(prepared)
    assert meta["typed_ast_node_count"] == 98
    assert row["report"]["counts"]["equality_occurrences"] == 6
    assert row["report"]["selected_interpretation"] is None
    assert meta["source_custody"]["original_source_bundle_replayed"] is False
    assert all(value is False for value in meta["authority"].values())


@pytest.mark.parametrize("amount", [0, 3, 4])
def test_mixed_preservation_keeps_existing_cap_and_permission_countermodels(
        mixed_preservation_fixtures, mixed_retained_preservation_reports, amount):
    mixed_preservation_fixtures.test_mixed_counting_and_permission_scope_keep_authored_finite_countermodels(
        mixed_retained_preservation_reports, amount)


@pytest.mark.parametrize("empty_sort", ["Object", "EventFrame", "TimeFrame"])
def test_mixed_preservation_empty_source_carriers_remain_uninhabited_without_added_axioms(
        mixed_preservation_base, mixed_preservation_fixtures, empty_sort):
    captured, prepared = mixed_preservation_base
    domains = {"Object": (0,), "EventFrame": ("event",), "TimeFrame": ("authored-time",)}
    domains[empty_sort] = ()
    atoms = lambda name, values, ambient: False
    modal = lambda operator, body, ambient: body(ambient)
    assert mixed_preservation_fixtures._mixed_typed_truth(captured["request"]["expression"]["root"], domains, atoms, modal) is True
    assert mixed_preservation_fixtures._mixed_renderer_truth(captured["report"]["renderer_ast"]["root"], domains, atoms, modal) is True
    assert _validate_mixed_preservation(captured, prepared) == prepared
    assert all("[Inhabited" not in text and "[Nonempty" not in text for _, text in prepared.files)


def test_mixed_preservation_authored_time_is_separate_from_ambient_modal_time(
        mixed_preservation_fixtures, mixed_retained_preservation_reports):
    mixed_preservation_fixtures.test_mixed_authored_time_frame_is_independent_of_modal_nat_index(
        mixed_retained_preservation_reports)


def test_mixed_pure_preparation_never_runs_a_compiler_or_model(mixed_preservation_base):
    captured, _ = mixed_preservation_base
    with patch.object(subprocess, "run", side_effect=AssertionError("subprocess reached")), patch.object(
            subprocess, "Popen", side_effect=AssertionError("child reached")):
        prepared = _prepare_mixed_preservation(captured)
        assert _validate_mixed_preservation(captured, prepared) == prepared


def test_mixed_profile_preserves_existing_unary_relational_and_counted_domains(
        base, relational_preservation_base, counted_preservation_base, mixed_preservation_base):
    old_data, old_prepared = base
    relational_captured, relational_prepared = relational_preservation_base
    counted_captured, counted_prepared = counted_preservation_base
    captured, prepared = mixed_preservation_base
    assert prepare(old_data) == old_prepared and validate(old_data, old_prepared) == old_prepared
    assert _validate_relational_preservation(relational_captured, relational_prepared) == relational_prepared
    assert _validate_counted_preservation(counted_captured, counted_prepared) == counted_prepared
    assert _validate_mixed_preservation(captured, prepared) == prepared
    assert len({manifest(p)["profile"] for p in (old_prepared, relational_prepared, counted_prepared, prepared)}) == 4
    assert sha(owner.COUNTED_SEMANTICS.encode()) == "fdcff83f56b84d34222f7b567950f5594b8e71303446b8d8d32093939224f091"
    assert len(owner.COUNTED_SEMANTICS.encode()) == 13993
    with pytest.raises(ValueError):
        _prepare_relational_preservation((captured["report"], captured["request_raw"]))
    with pytest.raises(ValueError):
        _prepare_counted_preservation((captured["report"], captured["request_raw"]))


# Declared identity DATA only: current source/review/graph replay is tested by
# the shared aggregate owner, not authenticated by these child-level fixtures.
def _reviewed_source_use_binding_fixture(unit_id="fixture:source-use-one"):
    fields = ("source_version_cid", "source_occurrence_cid", "graph_unit_record_cid",
              "graph_ast_record_cid", "scope_record_cid", "interpretation_record_cid")
    binding = {"schema": "legal-native-reviewed-source-use-binding/v1", "unit_id": unit_id,
               "complete_ir_sha256": "a" * 64}
    for field in fields:
        binding[field] = corpus_contracts.seal_record({"schema": "fictional-source-use-coordinate/v1",
            "unit_id": unit_id, "coordinate": field})["record_cid"]
    return binding


def _reviewed_source_use_options(binding):
    return dict(source_use_binding=binding, expected_source_use_binding_sha256=sha(canonical(binding)))


def _reviewed_source_use_child_case(kind, relational_preservation_base, mixed_preservation_base):
    if kind == "object":
        captured, legacy = relational_preservation_base
        return captured, legacy, _prepare_relational_preservation, _validate_relational_preservation, owner.RELATIONAL_PROFILE
    assert kind == "mixed"
    captured, legacy = mixed_preservation_base
    return captured, legacy, _prepare_mixed_preservation, _validate_mixed_preservation, owner.MIXED_PROFILE


@pytest.mark.parametrize("kind", ["object", "mixed"])
def test_reviewed_source_use_child_explicit_identity_keeps_defaults_values_and_five_obligations(
        relational_preservation_base, mixed_preservation_base, kind):
    captured, legacy, prepare, validate, old_profile = _reviewed_source_use_child_case(
        kind, relational_preservation_base, mixed_preservation_base)
    assert prepare(captured, source_use_binding=None, expected_source_use_binding_sha256=None) == legacy
    assert validate(captured, legacy) == legacy
    original_meta, original_files = manifest(legacy), dict(legacy.files)
    original_inputs = json.loads(original_files["preservation-inputs.json"])
    new_keys = {"source_use_binding", "source_use_binding_sha256", "instance_identity_profile"}
    assert not new_keys & set(original_meta) and not new_keys & set(original_inputs)
    report_key = "relational_report_sha256" if kind == "object" else "mixed_report_sha256"
    old_payload = {"profile": old_profile, "report_sha256": original_meta[report_key],
        "request_sha256": original_meta["original_request_sha256"],
        "semantics_sha256": original_meta["semantics_sha256"]}
    old_instance = original_meta["expected_modules"][2]
    assert old_instance.rsplit(".Instance", 1)[1] == sha(canonical(old_payload))
    binding = _reviewed_source_use_binding_fixture()
    unchanged = deepcopy(binding)
    prepared = prepare(captured, **_reviewed_source_use_options(binding))
    assert validate(captured, prepared, **_reviewed_source_use_options(binding)) == prepared
    assert binding == unchanged
    meta, files = manifest(prepared), dict(prepared.files)
    assert meta["profile"] == old_profile + "+reviewed-source-use/v1"
    assert meta["instance_identity_profile"] == "reviewed-source-use/v1"
    assert meta["source_use_binding"] == unchanged and meta["source_use_binding_sha256"] == sha(canonical(unchanged))
    inputs = json.loads(files["preservation-inputs.json"])
    for key in new_keys:
        assert inputs[key] == meta[key]
    restored_inputs = {key: value for key, value in inputs.items() if key not in new_keys}
    restored_inputs["profile"] = original_inputs["profile"]
    assert restored_inputs == original_inputs
    assert len(files) == 7 and len(meta["expected_modules"]) == 4 and len(meta["theorems"]) == 5
    new_instance = meta["expected_modules"][2]
    assert new_instance != old_instance
    assert files[new_instance.replace(".", "/") + ".lean"] == original_files[
        old_instance.replace(".", "/") + ".lean"].replace(old_instance, new_instance)
    for module in original_meta["expected_modules"][:2]:
        assert files[module.replace(".", "/") + ".lean"] == original_files[module.replace(".", "/") + ".lean"]
    assert [name.rsplit(".", 1)[1] for name in meta["theorems"]] == [name.rsplit(".", 1)[1] for name in original_meta["theorems"]]
    assert meta["file_sha256"] == {name: sha(body.encode()) for name, body in prepared.files}
    assert meta["preparation_only"] is True and not any(meta["authority"].values())
    assert all(meta[key] is False for key in owner.FALSE_FLAGS)
    assert meta["training_mask"] == meta["evaluation_gold_mask"] == 0
    assert meta["source_custody"]["original_source_bundle_replayed"] is False
    assert meta["source_custody"]["source_prose_to_ast_proved"] is False


@pytest.mark.parametrize("kind", ["object", "mixed"])
@pytest.mark.parametrize("damage", ["missing_binding", "missing_digest", "missing_field", "extra_field", "wrong_schema",
    "wrong_digest", "bad_cid", "unit_type", "empty_unit", "full_ir_bad"])
def test_reviewed_source_use_child_requires_closed_independently_pinned_binding(
        relational_preservation_base, mixed_preservation_base, kind, damage):
    captured, _, prepare, validate, _ = _reviewed_source_use_child_case(
        kind, relational_preservation_base, mixed_preservation_base)
    binding = _reviewed_source_use_binding_fixture()
    healthy = prepare(captured, **_reviewed_source_use_options(binding))
    assert validate(captured, healthy, **_reviewed_source_use_options(binding)) == healthy
    changed = deepcopy(binding)
    if damage == "missing_field": del changed["interpretation_record_cid"]
    elif damage == "extra_field": changed["ordinal"] = 0
    elif damage == "wrong_schema": changed["schema"] = "legal-native-reviewed-source-use-binding/v0"
    elif damage == "bad_cid": changed["source_occurrence_cid"] = "not-a-canonical-cid"
    elif damage == "unit_type": changed["unit_id"] = False
    elif damage == "empty_unit": changed["unit_id"] = ""
    elif damage == "full_ir_bad": changed["complete_ir_sha256"] = "A" * 64
    options = _reviewed_source_use_options(changed)
    if damage == "missing_binding": options["source_use_binding"] = None
    elif damage == "missing_digest": options["expected_source_use_binding_sha256"] = None
    elif damage == "wrong_digest": options["expected_source_use_binding_sha256"] = "0" * 64
    if damage == "bad_cid":
        # Existing canonical CID validation occurs at the existing lazy owner boundary.
        with pytest.raises(ValueError):
            prepare(captured, **options)
    else:
        with patch.object(owner, "_owners", side_effect=AssertionError("invalid binding reached operation owners")):
            with pytest.raises(ValueError):
                prepare(captured, **options)
    if damage == "wrong_digest":
        with pytest.raises(ValueError):
            prepare(captured, source_use_binding=binding, expected_source_use_binding_sha256=True)


@pytest.mark.parametrize("kind", ["object", "mixed"])
def test_reviewed_source_use_child_does_not_infer_selection_or_cross_join_other_bindings(
        relational_preservation_base, mixed_preservation_base, kind):
    captured, legacy, prepare, validate, _ = _reviewed_source_use_child_case(
        kind, relational_preservation_base, mixed_preservation_base)
    first = _reviewed_source_use_binding_fixture()
    second = _reviewed_source_use_binding_fixture("fixture:source-use-two")
    one = prepare(captured, **_reviewed_source_use_options(first))
    two = prepare(captured, **_reviewed_source_use_options(second))
    assert one != two and manifest(one)["expected_modules"][2] != manifest(two)["expected_modules"][2]
    assert validate(captured, one, **_reviewed_source_use_options(first)) == one
    assert validate(captured, two, **_reviewed_source_use_options(second)) == two
    for offered, options in ((one, {}), (legacy, _reviewed_source_use_options(first)),
                             (one, _reviewed_source_use_options(second)), (two, _reviewed_source_use_options(first))):
        with pytest.raises(ValueError):
            validate(captured, offered, **options)


@pytest.mark.parametrize("kind", ["object", "mixed"])
def test_reviewed_source_use_child_repaired_foreign_binding_metadata_requires_regeneration(
        relational_preservation_base, mixed_preservation_base, kind):
    captured, _, prepare, validate, _ = _reviewed_source_use_child_case(
        kind, relational_preservation_base, mixed_preservation_base)
    first = _reviewed_source_use_binding_fixture()
    second = _reviewed_source_use_binding_fixture("fixture:source-use-two")
    prepared = prepare(captured, **_reviewed_source_use_options(first))
    genuine_second = prepare(captured, **_reviewed_source_use_options(second))
    assert validate(captured, genuine_second, **_reviewed_source_use_options(second)) == genuine_second
    meta, files = manifest(prepared), dict(prepared.files)
    meta["source_use_binding"] = deepcopy(second)
    meta["source_use_binding_sha256"] = sha(canonical(second))
    inputs = json.loads(files["preservation-inputs.json"])
    inputs["source_use_binding"] = deepcopy(second)
    inputs["source_use_binding_sha256"] = sha(canonical(second))
    files["preservation-inputs.json"] = canonical(inputs).decode() + "\n"
    forged = _mixed_reseal(prepared, meta, files)
    assert forged != genuine_second
    with pytest.raises(ValueError):
        validate(captured, forged, **_reviewed_source_use_options(second))


@pytest.mark.parametrize("kind", ["object", "mixed"])
@pytest.mark.parametrize("changed_target", ["caller", "detached"])
def test_reviewed_source_use_child_late_binding_mutation_cannot_return_preparation(
        relational_preservation_base, mixed_preservation_base, monkeypatch, kind, changed_target):
    captured, _, prepare, validate, old_profile = _reviewed_source_use_child_case(
        kind, relational_preservation_base, mixed_preservation_base)
    binding = _reviewed_source_use_binding_fixture()
    healthy = prepare(captured, **_reviewed_source_use_options(binding))
    assert validate(captured, healthy, **_reviewed_source_use_options(binding)) == healthy
    original_binding = deepcopy(binding)
    other_cid = _reviewed_source_use_binding_fixture("fixture:late-other-use")["scope_record_cid"]
    original_seal = corpus_contracts.seal_record
    hits = []

    def change_after_original_seal(value):
        result = original_seal(value)
        if value.get("schema") == owner.SCHEMA and value.get("profile") == old_profile + "+reviewed-source-use/v1":
            hits.append(True)
            changed = binding if changed_target == "caller" else value["source_use_binding"]
            changed["scope_record_cid"] = other_cid
        return result

    monkeypatch.setattr(corpus_contracts, "seal_record", change_after_original_seal)
    with pytest.raises(ValueError):
        prepare(captured, source_use_binding=binding,
            expected_source_use_binding_sha256=sha(canonical(original_binding)))
    assert hits == [True]
    assert (binding == original_binding) is (changed_target == "detached")


@pytest.mark.parametrize("kind", ["object", "mixed"])
def test_reviewed_source_use_child_late_identity_validator_replacement_refuses(
        relational_preservation_base, mixed_preservation_base, monkeypatch, kind):
    captured, _, prepare, validate, old_profile = _reviewed_source_use_child_case(
        kind, relational_preservation_base, mixed_preservation_base)
    binding = _reviewed_source_use_binding_fixture()
    healthy = prepare(captured, **_reviewed_source_use_options(binding))
    assert validate(captured, healthy, **_reviewed_source_use_options(binding)) == healthy
    original_identity = owner._reviewed_source_use_identity
    original_seal = corpus_contracts.seal_record
    hits = []

    def changed_identity(*args, **kwargs):
        return original_identity(*args, **kwargs)

    def replace_after_original_seal(value):
        result = original_seal(value)
        if value.get("schema") == owner.SCHEMA and value.get("profile") == old_profile + "+reviewed-source-use/v1":
            hits.append(True)
            monkeypatch.setattr(owner, "_reviewed_source_use_identity", changed_identity)
        return result

    monkeypatch.setattr(corpus_contracts, "seal_record", replace_after_original_seal)
    with pytest.raises(ValueError):
        prepare(captured, **_reviewed_source_use_options(binding))
    assert hits == [True]


def _parametric_counted_capture(maximum):
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_threshold_v2 as counted
    request = counted.authored_counted_threshold_request_v3(maximum)
    raw = canonical(request)
    report = counted.prepare_counted_threshold_v3(raw, expected_request_sha256=sha(raw))
    return report, raw


def _prepare_parametric_counted(captured, **overrides):
    report, raw = captured
    return owner.prepare_counted_threshold_ast_preservation(report, raw, **({
        "expected_report_sha256": sha(canonical(report)),
        "expected_request_sha256": sha(raw), "toolchain": TOOLCHAIN,
    } | overrides))


def _validate_parametric_counted(captured, prepared, **overrides):
    report, raw = captured
    return owner.validate_counted_threshold_ast_preservation(prepared, report, raw, **({
        "expected_preparation_sha256": owner.preparation_sha256(prepared),
        "expected_report_sha256": sha(canonical(report)),
        "expected_request_sha256": sha(raw), "toolchain": TOOLCHAIN,
    } | overrides))


@pytest.mark.parametrize("maximum", [0, 1, 3, 4, 5])
def test_parametric_counted_preservation_replays_complete_subject_without_native_credit(maximum):
    captured = _parametric_counted_capture(maximum)
    before = deepcopy(captured)
    prepared = _prepare_parametric_counted(captured)
    assert _validate_parametric_counted(captured, prepared) == prepared
    assert captured == before
    report, raw = captured
    meta, files = manifest(prepared), dict(prepared.files)
    assert meta["profile"] == owner.PARAMETRIC_COUNTED_PROFILE
    assert meta["maximum"] == maximum
    assert meta["typed_ast_node_count"] == (9 if maximum == 0 else 2 * maximum * maximum + 8 * maximum + 7)
    assert meta["support_profile"]["max_ast_nodes"] == owner.MAX_AST_NODES == 4096
    assert meta["support_profile"]["max_ast_depth"] == owner.MAX_AST_DEPTH == 32
    assert meta["support_profile"]["max_project_bytes"] == owner.MAX_PROJECT_BYTES == 8 * 1024**2
    assert meta["support_profile"]["max_json_depth"] == 64
    assert meta["support_profile"]["max_json_items"] == 20000
    assert meta["support_profile"]["authored_sort_names_generalized"] is False
    assert meta["support_profile"]["arbitrary_carrier_types"] is True
    assert meta["proof_candidate"]["status"] == "UNQUALIFIED_NOT_EXECUTED"
    assert meta["proof_candidate"]["native_execution"] is False
    assert meta["proof_candidate"]["kernel_checked"] is False
    assert meta["proof_candidate"]["extra_axioms_requested"] == []
    assert len(meta["theorems"]) == 4 and len(files) == 7
    assert report["lean_body"] in "\n".join(files.values())
    inputs = json.loads(files["preservation-inputs.json"])
    assert inputs["counted_report"] == report and inputs["original_request_raw_utf8"].encode() == raw
    assert not any(meta["authority"].values())
    assert all(meta[field] is False for field in owner.FALSE_FLAGS)
    assert meta["training_mask"] == meta["evaluation_gold_mask"] == 0


@pytest.mark.parametrize("field", ["expected_report_sha256", "expected_request_sha256"])
@pytest.mark.parametrize("pin", ["0" * 64, "A" * 64, None, True])
def test_parametric_counted_independent_commitments_cannot_be_replaced(field, pin):
    with pytest.raises(ValueError):
        _prepare_parametric_counted(_parametric_counted_capture(4), **{field: pin})


@pytest.mark.parametrize("damage", ["maximum", "expression", "lowering", "authority", "producer", "extra"])
def test_parametric_counted_resealed_report_still_requires_original_v3_replay(damage):
    report, raw = deepcopy(_parametric_counted_capture(4))
    if damage == "maximum":
        report["maximum"] = 5
    elif damage == "expression":
        report["typed_expression"]["root"]["binders"][0]["name"] = "different_event"
    elif damage == "lowering":
        report["lean_body"] = report["lean_body"].replace("x0 = x1", "x0 = x0", 1)
    elif damage == "authority":
        report["authority"][next(iter(report["authority"]))] = True
    elif damage == "producer":
        report["producer_pins"]["/untrusted/never-open-this.py"] = "0" * 64
    else:
        report["extra"] = True
    with pytest.raises(ValueError):
        _prepare_parametric_counted((report, raw))


@pytest.mark.parametrize("damage", ["collision_distinctness", "collision_maximum", "source_denotation"])
def test_parametric_counted_resealed_project_cannot_change_independent_meaning(damage):
    captured = _parametric_counted_capture(4)
    original = _prepare_parametric_counted(captured)
    meta, files = manifest(original), dict(original.files)
    if damage == "collision_distinctness":
        path = owner.COUNTED_PROJECT_ROOT + "/Semantics.lean"
        changed = files[path].replace("i ≠ j ∧ objects i = objects j", "i = j ∧ objects i = objects j", 1)
    else:
        path = next(name for name, text in files.items() if "theorem threshold_collision_equivalence" in text)
        old, new = (("thresholdCollisionBound 4 member", "thresholdCollisionBound 5 member")
                    if damage == "collision_maximum" else
                    ("thresholdDenote member typedCountedThresholdAst", "countedAtMostThreshold member"))
        changed = files[path].replace(old, new, 1)
    assert changed != files[path]
    files[path] = changed
    meta["file_sha256"] = {name: sha(text.encode()) for name, text in sorted(files.items())}
    meta = corpus_contracts.seal_record({key: value for key, value in meta.items()
                                       if key not in {"record_cid", "cid_scope"}})
    altered = replace(original, manifest_json=canonical(meta).decode(), files=tuple(sorted(files.items())))
    with pytest.raises(ValueError):
        _validate_parametric_counted(captured, altered)


def test_parametric_counted_zero_has_false_witness_without_rewriting_actual_target():
    captured = _parametric_counted_capture(0)
    prepared = _prepare_parametric_counted(captured)
    files = dict(prepared.files)
    body = next(text for text in files.values() if "def typedCountedThresholdAst" in text)
    assert "(.falsity " in body
    assert captured[0]["lean_body"] in body
    assert json.loads(files["preservation-inputs.json"])["counted_report"] == captured[0]
    assert "| .falsity nodeId => countedNodeValue nodeId \"false\" \"\"" in owner.PARAMETRIC_COUNTED_SEMANTICS


def test_parametric_counted_preservation_keeps_legacy_profile_and_independent_pin_state(
        counted_preservation_base):
    legacy_capture, legacy_prepared = counted_preservation_base
    old_semantics = owner.COUNTED_SEMANTICS
    parametric_capture = _parametric_counted_capture(4)
    parametric_prepared = _prepare_parametric_counted(parametric_capture)
    assert _validate_counted_preservation(legacy_capture, legacy_prepared) == legacy_prepared
    assert _validate_parametric_counted(parametric_capture, parametric_prepared) == parametric_prepared
    assert owner.COUNTED_SEMANTICS == old_semantics
    assert sha(old_semantics.encode()) == "fdcff83f56b84d34222f7b567950f5594b8e71303446b8d8d32093939224f091"
    assert manifest(legacy_prepared)["profile"] == owner.COUNTED_PROFILE
    assert manifest(legacy_prepared)["typed_ast_node_count"] == 49
    assert manifest(parametric_prepared)["profile"] != owner.COUNTED_PROFILE


@pytest.mark.parametrize("maximum", [True, -1, 6, 7, 4097, 10**100])
def test_parametric_counted_pure_witness_and_proof_preflight_capacity_before_expansion(maximum):
    with pytest.raises(ValueError):
        owner._parametric_counted_source_syntax(None, maximum)
    with pytest.raises(ValueError):
        owner._parametric_counted_collision_proof(maximum)


def test_parametric_counted_preparation_does_not_execute_compiler_or_model():
    captured = _parametric_counted_capture(4)
    with patch.object(subprocess, "run", side_effect=AssertionError("process reached")), patch.object(
            subprocess, "Popen", side_effect=AssertionError("process reached")):
        prepared = _prepare_parametric_counted(captured)
        assert _validate_parametric_counted(captured, prepared) == prepared



def _counted_check_or_injection_arity(text):
    """Independent application grouping check for generated Lean proof terms."""
    import re
    stack = [[]]
    for token in re.findall(r"\(|\)|[^\s()]+", text):
        if token == '(':
            stack.append([])
        elif token == ')':
            assert len(stack) > 1
            group = stack.pop()
            if group and group[0] == 'Or.inl':
                assert len(group) == 2, 'Or.inl must receive one grouped proof argument'
            stack[-1].append(group)
        else:
            stack[-1].append(token)
    assert len(stack) == 1


@pytest.mark.parametrize('maximum', [0, 1, 3, 4])
def test_counted_collision_proof_groups_injected_terms_after_native_elaborator_red(maximum):
    # This guards argument boundaries only. The existing Native case builds
    # remain the regression for dependent motives and theorem correctness.
    _counted_check_or_injection_arity(owner._parametric_counted_collision_proof(maximum))


def test_counted_application_grouping_guard_detects_the_actual_latent_injection_error():
    with pytest.raises(AssertionError):
        _counted_check_or_injection_arity('(Or.inl And.right pair)')
    _counted_check_or_injection_arity('(Or.inl (And.right pair))')


@pytest.mark.parametrize('maximum', [0, 1, 3, 4, 5])
def test_parametric_collision_avoids_the_measured_unsafe_Fin_cases_dependency(maximum):
    # Native probe measured Fin.cases=[propext], direct dependent helper=[].
    # This prevents that known dependency from reentering generated proofs;
    # it does not replace the separate Native theorem/axiom qualification.
    proof = owner._parametric_counted_collision_proof(maximum)
    assert 'Fin.cases ' not in proof
    assert 'thresholdFinCases (motive :=' in proof
    _counted_check_or_injection_arity(proof)


# Additive quantity preservation controls, separate from actual Native execution.
def _positive_quantity_preservation_capture(quantity, threshold):
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_threshold_v2 as counted
    request = counted.authored_counted_quantity_request_v4(quantity, threshold)
    raw = canonical(request)
    report = counted.prepare_counted_quantity_v4(raw, expected_request_sha256=sha(raw))
    return report, raw


def _positive_quantity_prepare(captured, **overrides):
    report, raw = captured
    return owner.prepare_counted_quantity_ast_preservation(report, raw, **({
        'expected_report_sha256':sha(canonical(report)), 'expected_request_sha256':sha(raw),
        'toolchain':TOOLCHAIN} | overrides))


@pytest.mark.parametrize('quantity', ['at_least','exactly'])
@pytest.mark.parametrize('threshold', [0,1,2,4])
def test_positive_quantity_preservation_reuses_mixed_route_and_independent_Fin_contract(quantity, threshold):
    captured = _positive_quantity_preservation_capture(quantity,threshold)
    prepared = _positive_quantity_prepare(captured)
    report, raw = captured
    assert owner.validate_counted_quantity_ast_preservation(prepared,report,raw,
        expected_preparation_sha256=owner.preparation_sha256(prepared),
        expected_report_sha256=sha(canonical(report)),expected_request_sha256=sha(raw),toolchain=TOOLCHAIN) == prepared
    meta, files = manifest(prepared), dict(prepared.files)
    assert meta['profile'] == owner.QUANTITY_COUNTED_PROFILE
    assert meta['quantity'] == quantity and meta['threshold'] == threshold
    assert len(files) == owner.MAX_FILES == 7 and len(meta['expected_modules']) == 4
    assert len(meta['theorems']) == 8 and len(set(meta['theorems'])) == 8
    assert set(meta['expected_axioms']) == set(meta['theorems'])
    assert all(value == [] for value in meta['expected_axioms'].values())
    assert meta['genuine_mixed_manifest']['profile'] == owner.MIXED_PROFILE
    assert meta['genuine_mixed_preparation_sha256']
    assert meta['authority'] and not any(meta['authority'].values())
    assert meta['training_mask'] == meta['evaluation_gold_mask'] == 0
    assert meta['quantity_cardinality_proved'] is False
    assert meta['native_TDFOL_route_used'] is meta['native_parser_roundtrip'] is False
    for path,text in files.items():assert sha(text.encode()) == meta['file_sha256'][path]
    semantics = files[meta['expected_modules'][1].replace('.','/')+'.lean']
    instance = files[meta['expected_modules'][2].replace('.','/')+'.lean']
    assert 'def mixedDenote' in semantics and 'def thresholdFinCases' in semantics
    assert 'def quantityFiniteAtLeast' in semantics and 'def quantityFiniteExactly' in semantics
    assert 'Function.Injective objects' in semantics
    assert 'member x event time ↔ ∃ index, objects index = x' in semantics
    assert 'quantityExpansion member ↔ quantityFinite' in instance
    assert 'quantity_denotation_matches_finite' in instance
    assert ('quantityFiniteAtLeast' if quantity == 'at_least' else 'quantityFiniteExactly')+' '+str(threshold)+' member' in instance
    assert all(token not in semantics+instance for token in ['Classical.','DecidableEq Object','sorry','admit','axiom '])
    if threshold == 0:
        assert 'Fin 0' in instance and 'Fin.elim0' in instance
        if quantity == 'at_least':assert 'member zeroWitness event time → member zeroWitness event time' in instance
    assert 'AL-and-AM shortcut' in '\n'.join(meta['theorem_assumptions'])


@pytest.mark.parametrize('pin', ['expected_report_sha256','expected_request_sha256'])
def test_positive_quantity_preservation_independent_pins_precede_operation_owners(monkeypatch,pin):
    report, raw = _positive_quantity_preservation_capture('exactly',2)
    options = dict(expected_report_sha256=sha(canonical(report)),expected_request_sha256=sha(raw),toolchain=TOOLCHAIN)
    options[pin] = '0'*64
    monkeypatch.setattr(owner,'_owners',lambda:pytest.fail('bad independent quantity pin reached operation owners'))
    with pytest.raises(ValueError):owner.prepare_counted_quantity_ast_preservation(report,raw,**options)


@pytest.mark.parametrize('damage', ['quantity','threshold','coverage','member_sort','member_roles'])
def test_positive_quantity_rehashed_report_requires_original_declared_subject(damage):
    report, raw = _positive_quantity_preservation_capture('exactly',2)
    altered = deepcopy(report)
    if damage == 'quantity':altered['quantity'] = 'at_least'
    elif damage == 'threshold':altered['threshold'] = 1
    elif damage == 'member_roles':altered['argument_roles'][0]['roles'] = ['event','object','time']
    else:
        def first(root,predicate):
            if predicate(root):return root
            for child in root['arguments']:
                found=first(child,predicate)
                if found is not None:return found
            return None
        root=altered['typed_expression']['root']
        if damage=='coverage':first(root,lambda x:x['kind']=='iff')['kind']='implies'
        else:first(root,lambda x:x['kind']=='predicate')['arguments'][0]['sort']['name']='TimeFrame'
    with pytest.raises(ValueError):_positive_quantity_prepare((altered,raw))


@pytest.mark.parametrize('damage', ['Fin_bound','finite_contract','Member_interpretation','source_expansion'])
def test_positive_quantity_resealed_complete_project_cannot_change_independent_cardinality(damage):
    captured = _positive_quantity_preservation_capture('exactly',4)
    prepared = _positive_quantity_prepare(captured)
    meta, files = manifest(prepared), dict(prepared.files)
    instance=meta['expected_modules'][2].replace('.','/')+'.lean'
    semantics=meta['expected_modules'][1].replace('.','/')+'.lean'
    if damage=='Fin_bound':
        assert 'quantityFiniteExactly 4 member' in files[instance]
        files[instance]=files[instance].replace('quantityFiniteExactly 4 member','quantityFiniteExactly 3 member',1)
    elif damage=='finite_contract':
        assert 'Function.Injective objects' in files[semantics]
        files[semantics]=files[semantics].replace('Function.Injective objects','True',1)
    elif damage=='Member_interpretation':
        assert 'member object event time' in files[semantics]
        files[semantics]=files[semantics].replace('member object event time','False',1)
    else:
        assert 'member candidate event time ↔' in files[instance]
        files[instance]=files[instance].replace('member candidate event time ↔','member candidate event time →',1)
    meta['file_sha256']={name:sha(text.encode())for name,text in sorted(files.items())}
    # Even self-consistent local hashes cannot replace complete original regeneration.
    altered=owner.NativeAstPreservationPreparation(canonical(meta).decode(),tuple(sorted(files.items())))
    report,raw=captured
    with pytest.raises(ValueError):owner.validate_counted_quantity_ast_preservation(altered,report,raw,
        expected_preparation_sha256=owner.preparation_sha256(altered),
        expected_report_sha256=sha(canonical(report)),expected_request_sha256=sha(raw),toolchain=TOOLCHAIN)


@pytest.mark.parametrize('quantity,threshold',[('at_least',True),('exactly',-1),('at_most',2),('exactly',10**100)])
def test_positive_quantity_native_preflight_refuses_before_expansion(quantity,threshold):
    with pytest.raises(ValueError):owner._quantity_native_budget(quantity,threshold)
    with pytest.raises(ValueError):owner._quantity_lean_expansion(quantity,threshold)


def test_positive_quantity_preservation_leaves_v3_legacy_project_replay_exact():
    legacy=_parametric_counted_capture(4)
    prior=_prepare_parametric_counted(legacy)
    _positive_quantity_prepare(_positive_quantity_preservation_capture('at_least',2))
    _positive_quantity_prepare(_positive_quantity_preservation_capture('exactly',2))
    assert _prepare_parametric_counted(legacy)==prior
    assert _validate_parametric_counted(legacy,prior)==prior
    assert manifest(prior)['profile']==owner.PARAMETRIC_COUNTED_PROFILE



def test_expanded_counted_nat_capacity_keeps_frozen_default_proof_strings():
    profile = owner.PARAMETRIC_EXPANDED_CAPACITY_PROFILE
    with pytest.raises(ValueError):owner._parametric_counted_dimensions(10)
    assert owner._parametric_counted_dimensions(10, capacity_profile=profile) == (287, 69)
    for maximum in (0, 1, 3, 4, 5):
        assert owner._parametric_counted_collision_proof(maximum) == owner._parametric_counted_collision_proof(maximum, capacity_profile=None)
    text = owner._parametric_counted_collision_proof(10, capacity_profile=profile)
    assert 'thresholdCollisionBound 10 member' in text
    assert '#print axioms threshold_collision_equivalence' in text
    assert all(token not in text for token in ('Classical.', 'sorry', 'admit', 'axiom '))


def test_expanded_counted_nat_public_preparation_retains_exact_capacity_commitment():
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_threshold_v2 as counted
    profile = counted.PARAMETRIC_EXPANDED_CAPACITY_PROFILE
    request = counted.authored_counted_threshold_request_v3(10, capacity_profile=profile)
    raw = canonical(request)
    report = counted.prepare_counted_threshold_v3(raw, expected_request_sha256=sha(raw))
    prepared = owner.prepare_counted_threshold_ast_preservation(report, raw,
        expected_report_sha256=sha(canonical(report)), expected_request_sha256=sha(raw), toolchain=TOOLCHAIN)
    meta = manifest(prepared)
    assert meta['capacity_profile'] == profile
    assert meta['support_profile']['max_ast_depth'] == 128
    assert meta['support_profile']['max_json_depth'] == 256
    assert meta['support_profile']['max_json_items'] == 65536
    assert len(prepared.files) == 7 and len(meta['theorems']) == 4
    assert owner.validate_counted_threshold_ast_preservation(prepared, report, raw,
        expected_preparation_sha256=owner.preparation_sha256(prepared), expected_report_sha256=sha(canonical(report)),
        expected_request_sha256=sha(raw), toolchain=TOOLCHAIN) == prepared
    damaged = deepcopy(report); damaged['capacity_profile'] = None
    with pytest.raises(ValueError):owner.prepare_counted_threshold_ast_preservation(damaged, raw,
        expected_report_sha256=sha(canonical(damaged)), expected_request_sha256=sha(raw), toolchain=TOOLCHAIN)


def test_expanded_counted_nat_public_project_selects_bounded_native_recursion_only_when_opted_in():
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_threshold_v2 as counted
    option = "set_option maxRecDepth 8192\n"
    profile = counted.PARAMETRIC_EXPANDED_CAPACITY_PROFILE
    request = counted.authored_counted_threshold_request_v3(10, capacity_profile=profile)
    raw = canonical(request)
    report = counted.prepare_counted_threshold_v3(raw, expected_request_sha256=sha(raw))
    prepared = owner.prepare_counted_threshold_ast_preservation(report, raw,
        expected_report_sha256=sha(canonical(report)), expected_request_sha256=sha(raw), toolchain=TOOLCHAIN)
    meta, files = manifest(prepared), dict(prepared.files)
    instance_path = meta["expected_modules"][2].replace(".", "/") + ".lean"
    assert files[instance_path].startswith("import " + meta["expected_modules"][1] + "\n" + option)
    assert files[instance_path].count(option) == 1
    assert meta["file_sha256"][instance_path] == sha(files[instance_path].encode())
    assert len(files) == 7 and len(meta["theorems"]) == 4
    assert owner.validate_counted_threshold_ast_preservation(prepared, report, raw,
        expected_preparation_sha256=owner.preparation_sha256(prepared), expected_report_sha256=sha(canonical(report)),
        expected_request_sha256=sha(raw), toolchain=TOOLCHAIN) == prepared
    for maximum in (0, 4):
        default = _prepare_parametric_counted(_parametric_counted_capture(maximum))
        assert all(option not in body for name, body in default.files if name.endswith(".lean"))
