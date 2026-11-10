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
