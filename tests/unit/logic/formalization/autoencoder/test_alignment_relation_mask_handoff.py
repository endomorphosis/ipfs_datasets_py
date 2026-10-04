"""Invented fixture masks test engineering associations, never human semantics."""
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_relation_mask_handoff as subject,
)

_spec = importlib.util.spec_from_file_location("_handoff_relation_fixtures", Path(__file__).with_name(
    "test_alignment_relation_declarations.py"))
fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures)


def bindings(declaration, snapshot, policy):
    return {"declaration_sha256": subject._digest(declaration), "declaration_roles": fixtures.pins(declaration),
            "snapshot_sha256": subject._digest(snapshot), "policy_sha256": subject._digest(policy)}


def refresh(declaration, snapshot, policy):
    fixtures.seal(policy)
    snapshot["declaration_sha256"] = subject._digest(declaration)
    snapshot["policy_sha256"] = subject._digest(policy)
    fixtures.seal(snapshot)
    return bindings(declaration, snapshot, policy)


def synthetic(n=3, unavailable=(), same_formal=False):
    declaration = fixtures.declaration(n=n, unavailable=unavailable, same_formal=same_formal)
    declaration["relation_policy"]["target_family_id"] = "declared-family-only"
    fixtures.refresh(declaration)
    prepared = subject.prepare_unavailable_relation_handoff(declaration, expected_declaration_bindings=fixtures.pins(declaration))
    snapshot, policy = prepared["snapshot"], prepared["policy"]
    policy.update(mode=subject.SYNTHETIC, source_family_id="declared-family-only", target_family_id="declared-family-only",
                  source_semantic_profile_sha256="d" * 64, target_semantic_profile_sha256="d" * 64)
    snapshot["provenance"] = "synthetic_fixture_not_human_review"
    for row in snapshot["endpoint_rows"]:
        row.update(source_fidelity="synthetic_complete", formal_fidelity="synthetic_complete",
                   source_review_sha256=subject._digest({"invented_source": row["id"]}),
                   formal_review_sha256=subject._digest({"invented_formal": row["id"]}))
    for index, pair in enumerate(snapshot["pair_rows"]):
        pair.update(relation="synthetic_positive" if index // n == index % n else "synthetic_negative",
                    review_sha256=subject._digest({"invented_review": index}),
                    adjudication_sha256=subject._digest({"invented_adjudication": index}), reason="invented fixture claim")
    return declaration, snapshot, policy, refresh(declaration, snapshot, policy)


def compile_fixture(declaration, snapshot, policy, expected=None):
    return subject.compile_train_relation_masks(declaration, snapshot, policy,
        expected_bindings=bindings(declaration, snapshot, policy) if expected is None else expected)


def test_handoff_unavailable_preparer_retains_all_train_anchors_and_weak_identity_enables_nothing():
    declaration = fixtures.declaration(n=16, same_formal=True, unavailable=(2,))
    original = deepcopy(declaration)
    prepared = subject.prepare_unavailable_relation_handoff(declaration, expected_declaration_bindings=fixtures.pins(declaration))
    assert set(prepared) == {"snapshot", "policy", "expected_bindings", "validation"}
    result = prepared["validation"]
    assert result["train_row_count"] == 16 and result["pair_count"] == 256
    assert result["declared_relation_counts"] == {"unknown": 256}
    assert result["objective_positive_pair_count"] == result["objective_permitted_negative_pair_count"] == 0
    assert result["missing_positive_row_ids"] == result["missing_positive_column_ids"] == ["train_" + str(i) for i in range(16)]
    assert result["no_negative_row_ids"] == result["no_negative_column_ids"] == result["missing_positive_row_ids"]
    for name in ("objective_positive_mask", "objective_permitted_negative_mask", "admitted_positive_mask", "admitted_permitted_negative_mask"):
        assert result[name] == [[False] * 16 for _ in range(16)]
        assert result["matrix_sha256"][name] == subject._digest(result[name])
    assert prepared["snapshot"]["declaration_sha256"] == subject._digest(declaration)
    assert prepared["snapshot"]["policy_sha256"] == subject._digest(prepared["policy"])
    assert result["status"] == "mask_preflight_blocked" and result["synthetic_objective_mask_ready"] is False
    assert result["masks"] == dict.fromkeys(subject.MASKS, 0)
    assert all(result[key] is False for key in subject.FALSE)
    assert all(type(result[key]) is int and result[key] == 0 for key in subject.COUNTERS)
    assert declaration == original
    assert prepared == subject.prepare_unavailable_relation_handoff(declaration, expected_declaration_bindings=fixtures.pins(declaration))


def test_handoff_synthetic_masks_can_be_ready_while_every_real_admission_and_execution_stays_blocked():
    declaration, snapshot, policy, expected = synthetic()
    original = deepcopy((declaration, snapshot, policy, expected))
    result = compile_fixture(declaration, snapshot, policy, expected)
    assert result["objective_positive_pair_count"] == 3 and result["objective_permitted_negative_pair_count"] == 6
    assert result["row_positive_counts"] == result["column_positive_counts"] == [1, 1, 1]
    assert result["synthetic_objective_mask_ready"] is True and result["objective_blockers"] == []
    assert result["status"] == "synthetic_mask_preflight_ready"
    assert result["declared_semantic_scope"]["source_semantic_profile_sha256"] != result["representation_profile_sha256"]
    assert result["admitted_positive_mask"] == result["admitted_permitted_negative_mask"] == [[False] * 3 for _ in range(3)]
    assert all(result[key] is False for key in subject.FALSE)
    assert result["masks"] == dict.fromkeys(subject.MASKS, 0)
    assert (declaration, snapshot, policy, expected) == original
    assert result == compile_fixture(declaration, snapshot, policy, expected)
    result["endpoint_rows"][0]["source_fidelity"] = "unavailable"
    result["expected_bindings"]["snapshot_sha256"] = "a" * 64
    result["objective_positive_mask"][0][0] = False
    assert (declaration, snapshot, policy, expected) == original
    assert compile_fixture(declaration, snapshot, policy, expected)["objective_positive_mask"][0][0] is True


def test_handoff_unknowns_equal_formals_diagonal_and_symmetry_do_not_infer_objective_relations():
    declaration, snapshot, policy, _ = synthetic(same_formal=True)
    for pair in snapshot["pair_rows"]:
        pair.update(relation="unknown", review_sha256=None, adjudication_sha256=None)
    snapshot["pair_rows"][1].update(relation="synthetic_positive", review_sha256="e" * 64, adjudication_sha256="f" * 64)
    refresh(declaration, snapshot, policy)
    result = compile_fixture(declaration, snapshot, policy)
    assert result["objective_positive_mask"] == [[False, True, False], [False] * 3, [False] * 3]
    assert result["objective_permitted_negative_pair_count"] == 0
    assert result["missing_positive_row_ids"] == ["train_1", "train_2"]
    assert result["missing_positive_column_ids"] == ["train_0", "train_2"]
    assert "missing_positive_rows" in result["objective_blockers"] and "missing_positive_columns" in result["objective_blockers"]


def test_handoff_asymmetric_directed_fixture_is_not_closed_by_symmetry_or_transitivity():
    declaration, snapshot, policy, _ = synthetic()
    for pair in snapshot["pair_rows"]:
        pair["relation"] = "unknown"
    for index in (1, 5, 6):
        snapshot["pair_rows"][index]["relation"] = "synthetic_positive"
    snapshot["pair_rows"][0]["relation"] = "synthetic_negative"
    refresh(declaration, snapshot, policy)
    result = compile_fixture(declaration, snapshot, policy)
    assert result["objective_positive_mask"] == [[False, True, False], [False, False, True], [True, False, False]]
    assert result["synthetic_objective_mask_ready"] is True
    assert result["no_negative_row_ids"] == ["train_1", "train_2"]
    assert result["no_negative_column_ids"] == ["train_1", "train_2"]


def test_handoff_all_positive_fixture_has_no_separation_and_retains_all_rows():
    declaration, snapshot, policy, _ = synthetic()
    for pair in snapshot["pair_rows"]:
        pair["relation"] = "synthetic_positive"
    refresh(declaration, snapshot, policy)
    result = compile_fixture(declaration, snapshot, policy)
    assert result["objective_positive_pair_count"] == 9
    assert result["missing_positive_row_ids"] == result["missing_positive_column_ids"] == []
    assert result["objective_blockers"] == ["no_negative_separation"]
    assert result["synthetic_objective_mask_ready"] is False


@pytest.mark.parametrize("key,value,reason", [
    ("source_family_id", None, "family_unknown"), ("target_family_id", "foreign-family", "family_mismatch"),
    ("source_semantic_profile_sha256", None, "semantic_profile_unknown"),
    ("target_semantic_profile_sha256", "e" * 64, "semantic_profile_mismatch")])
def test_handoff_incomplete_or_different_semantic_scope_excludes_all_declared_pairs(key, value, reason):
    declaration, snapshot, policy, _ = synthetic()
    policy[key] = value
    refresh(declaration, snapshot, policy)
    result = compile_fixture(declaration, snapshot, policy)
    assert reason in result["scope_exclusion_reasons"]
    assert result["objective_positive_pair_count"] == result["objective_permitted_negative_pair_count"] == 0
    assert result["train_row_count"] == 3 and result["pair_count"] == 9


def test_handoff_known_scope_must_match_frozen_family_declarations_even_when_both_new_families_match():
    declaration, snapshot, policy, _ = synthetic()
    policy["source_family_id"] = policy["target_family_id"] = "foreign-family"
    refresh(declaration, snapshot, policy)
    result = compile_fixture(declaration, snapshot, policy)
    assert "declared_family_binding_incomplete_or_different" in result["scope_exclusion_reasons"]
    assert result["objective_positive_pair_count"] == 0


def test_handoff_fidelity_checks_only_left_source_and_right_formal_and_preserve_other_pairs():
    declaration, snapshot, policy, _ = synthetic()
    snapshot["endpoint_rows"][0]["formal_fidelity"] = "synthetic_incomplete"
    snapshot["endpoint_rows"][1]["source_fidelity"] = "synthetic_incomplete"
    refresh(declaration, snapshot, policy)
    result = compile_fixture(declaration, snapshot, policy)
    assert result["objective_positive_mask"] == [[False] * 3, [False] * 3, [False, False, True]]
    assert result["objective_permitted_negative_mask"][0][1] is True
    assert result["objective_permitted_negative_mask"][1][0] is False
    assert result["objective_permitted_negative_mask"][2][1] is True
    assert "source_fidelity_not_complete" not in result["pair_rows"][1]["exclusion_reasons"]
    assert "formal_fidelity_not_complete" not in result["pair_rows"][1]["exclusion_reasons"]


@pytest.mark.parametrize("kind,key,reason", [
    ("endpoint", "source_review_sha256", "source_review_unbound"),
    ("endpoint", "formal_review_sha256", "formal_review_unbound"),
    ("pair", "review_sha256", "relation_review_unbound"),
    ("pair", "adjudication_sha256", "adjudication_unbound")])
def test_handoff_missing_fixture_references_exclude_without_fabricating_replacements(kind, key, reason):
    declaration, snapshot, policy, _ = synthetic()
    snapshot["endpoint_rows" if kind == "endpoint" else "pair_rows"][0][key] = None
    refresh(declaration, snapshot, policy)
    result = compile_fixture(declaration, snapshot, policy)
    assert result["objective_positive_mask"][0][0] is False
    assert reason in result["pair_rows"][0]["exclusion_reasons"]


def test_handoff_snapshot_cannot_override_frozen_unavailable_representation():
    declaration, snapshot, policy, _ = synthetic(unavailable=(1,))
    result = compile_fixture(declaration, snapshot, policy)
    assert result["objective_positive_mask"][1][1] is False
    assert result["objective_positive_pair_count"] == 2
    assert "source_representation_unavailable" in result["pair_rows"][3]["exclusion_reasons"]
    assert "formal_endpoint_representation_unavailable" in result["pair_rows"][1]["exclusion_reasons"]
    assert result["missing_positive_row_ids"] == result["missing_positive_column_ids"] == ["train_1"]


def test_handoff_ablation_zero_retained_representation_is_excluded_from_objective():
    declaration, snapshot, policy, _ = synthetic()
    row = declaration["lane_validation"]["rows"][1]
    row.update(status="ablation_zero", reason="invented zero ablation", vector_sha256=subject._digest([0.0] * 8))
    row["producer_row_sha256"] = subject._digest({key: row[key] for key in subject.relations.stages.ROW_BINDING_FIELDS})
    declaration["lane_validation"].update(available_count=2, zero_ablation_count=1)
    declaration["train_manifest"]["rows"][1].update(status=row["status"], reason=row["reason"], representation_sha256=row["vector_sha256"])
    fixtures.refresh(declaration)
    refresh(declaration, snapshot, policy)
    assert compile_fixture(declaration, snapshot, policy)["objective_positive_pair_count"] == 2


@pytest.mark.parametrize("mutation", ["source_fidelity", "formal_fidelity", "endpoint_review", "pair_relation", "pair_review", "scope"])
def test_handoff_unavailable_mode_rejects_fabricated_fidelity_relation_review_or_scope(mutation):
    declaration = fixtures.declaration()
    prepared = subject.prepare_unavailable_relation_handoff(declaration, expected_declaration_bindings=fixtures.pins(declaration))
    snapshot, policy = prepared["snapshot"], prepared["policy"]
    if mutation in {"source_fidelity", "formal_fidelity"}:
        snapshot["endpoint_rows"][0][mutation] = "synthetic_complete"
    elif mutation == "endpoint_review":
        snapshot["endpoint_rows"][0]["source_review_sha256"] = "e" * 64
    elif mutation == "pair_relation":
        snapshot["pair_rows"][0]["relation"] = "synthetic_positive"
    elif mutation == "pair_review":
        snapshot["pair_rows"][0]["review_sha256"] = "e" * 64
    else:
        policy["source_family_id"] = "declared-family-only"
    refresh(declaration, snapshot, policy)
    with pytest.raises(ValueError, match="unavailable"):
        compile_fixture(declaration, snapshot, policy)


@pytest.mark.parametrize("role", ["declaration", "snapshot", "policy"])
def test_handoff_resealing_selected_values_cannot_replace_external_generation_pins(role):
    declaration, snapshot, policy, expected = synthetic()
    if role == "declaration":
        declaration["pair_ledger"]["rows"][0]["reason"] = "changed declaration"
        fixtures.refresh(declaration)
    elif role == "snapshot":
        snapshot["pair_rows"][0]["reason"] = "changed fixture assertion"
    else:
        policy["assumptions_sha256"] = "f" * 64
    refresh(declaration, snapshot, policy)
    with pytest.raises(ValueError, match="selected .* differs"):
        compile_fixture(declaration, snapshot, policy, expected)


@pytest.mark.parametrize("key", sorted(subject.JOIN_FIELDS))
def test_handoff_pair_endpoint_cross_swap_rejects_even_if_snapshot_and_external_pins_resealed(key):
    declaration, snapshot, policy, _ = synthetic()
    snapshot["pair_rows"][1][key] = "foreign" if key.endswith("_id") else "f" * 64
    refresh(declaration, snapshot, policy)
    with pytest.raises(ValueError, match="endpoint binding differs"):
        compile_fixture(declaration, snapshot, policy)


@pytest.mark.parametrize("mutation", ["reorder", "missing", "duplicate", "extra"])
def test_handoff_complete_endpoint_and_pair_ledgers_cannot_drop_or_reorder_rows(mutation):
    declaration, snapshot, policy, _ = synthetic()
    pairs = snapshot["pair_rows"]
    if mutation == "reorder":
        pairs[1], pairs[3] = pairs[3], pairs[1]
    elif mutation == "missing":
        pairs.pop()
    elif mutation == "duplicate":
        pairs[1] = deepcopy(pairs[0])
    else:
        pairs.append(deepcopy(pairs[0]))
    refresh(declaration, snapshot, policy)
    with pytest.raises(ValueError):
        compile_fixture(declaration, snapshot, policy)


def test_handoff_endpoint_reorder_rejects_and_snapshot_must_bind_current_policy_and_declaration():
    declaration, snapshot, policy, _ = synthetic()
    snapshot["endpoint_rows"][0], snapshot["endpoint_rows"][1] = snapshot["endpoint_rows"][1], snapshot["endpoint_rows"][0]
    refresh(declaration, snapshot, policy)
    with pytest.raises(ValueError, match="endpoint identity"):
        compile_fixture(declaration, snapshot, policy)
    declaration, snapshot, policy, _ = synthetic()
    policy["assumptions_sha256"] = "e" * 64
    fixtures.seal(policy)
    with pytest.raises(ValueError, match="snapshot policy_sha256 differs"):
        compile_fixture(declaration, snapshot, policy)
    snapshot["policy_sha256"] = subject._digest(policy)
    snapshot["declaration_sha256"] = "f" * 64
    fixtures.seal(snapshot)
    with pytest.raises(ValueError, match="snapshot declaration_sha256 differs"):
        compile_fixture(declaration, snapshot, policy)


@pytest.mark.parametrize("value", [False, True, 0, 1, "true"])
def test_handoff_policy_separation_flag_is_exact_true(value):
    declaration, snapshot, policy, _ = synthetic()
    policy["separation_required"] = value
    refresh(declaration, snapshot, policy)
    if value is True:
        assert compile_fixture(declaration, snapshot, policy)["synthetic_objective_mask_ready"] is True
    else:
        with pytest.raises(ValueError, match="exact true"):
            compile_fixture(declaration, snapshot, policy)


@pytest.mark.parametrize("mutation", ["authority", "unknown_mode", "verified_provenance", "invalid_sha", "invalid_status", "nonfinite", "nonutf8", "tuple"])
def test_handoff_closed_plain_finite_json_and_no_self_declared_authentication(mutation):
    declaration, snapshot, policy, _ = synthetic()
    if mutation == "authority":
        snapshot["verified"] = True
    elif mutation == "unknown_mode":
        policy["mode"] = "authenticated_review/v1"
    elif mutation == "verified_provenance":
        snapshot["provenance"] = "real_human_verified"
    elif mutation == "invalid_sha":
        snapshot["pair_rows"][0]["adjudication_sha256"] = "not-a-hash"
    elif mutation == "invalid_status":
        snapshot["endpoint_rows"][0]["source_fidelity"] = True
    elif mutation == "nonfinite":
        snapshot["pair_rows"][0]["reason"] = float("nan")
    elif mutation == "nonutf8":
        snapshot["pair_rows"][0]["reason"] = "\ud800"
    else:
        snapshot["endpoint_rows"] = tuple(snapshot["endpoint_rows"])
    with pytest.raises(ValueError):
        refresh(declaration, snapshot, policy)
        compile_fixture(declaration, snapshot, policy)


def test_handoff_external_role_pins_stay_mandatory_even_if_outer_declaration_reselected():
    declaration, snapshot, policy, expected = synthetic()
    declaration["pair_ledger"]["rows"][0]["reason"] = "stale external role selection"
    fixtures.refresh(declaration)
    refresh(declaration, snapshot, policy)
    updated = bindings(declaration, snapshot, policy)
    updated["declaration_roles"] = expected["declaration_roles"]
    with pytest.raises(ValueError, match="pin"):
        compile_fixture(declaration, snapshot, policy, updated)


@pytest.mark.parametrize("mutation", ["fit", "admitted_mask", "supervision", "endpoint", "count", "extra", "numeric_alias"])
def test_handoff_saved_receipt_reseal_cannot_promote_or_change_any_mechanical_field(mutation):
    declaration, snapshot, policy, expected = synthetic()
    receipt = compile_fixture(declaration, snapshot, policy)
    validation = subject.validate_train_relation_mask_handoff(receipt, declaration, snapshot, policy, expected_bindings=expected)
    assert validation["status"] == "validated_exact_mask_preflight_replay"
    assert all(validation[key] is False for key in subject.FALSE)
    if mutation == "fit":
        receipt["actual_fit_authorized"] = True
    elif mutation == "admitted_mask":
        receipt["admitted_positive_mask"][0][0] = True
    elif mutation == "supervision":
        receipt["masks"]["contrastive_supervision"] = 1
    elif mutation == "endpoint":
        receipt["endpoint_rows"][0]["source_fidelity"] = "unavailable"
    elif mutation == "count":
        receipt["objective_positive_pair_count"] = 2
    elif mutation == "extra":
        receipt["verifier_approved"] = True
    else:
        receipt["model_calls"] = False
    fixtures.seal(receipt)
    with pytest.raises(ValueError, match="exact replay"):
        subject.validate_train_relation_mask_handoff(receipt, declaration, snapshot, policy, expected_bindings=expected)


def test_handoff_one_train_anchor_has_positive_coverage_but_no_negative_separation():
    declaration, snapshot, policy, _ = synthetic(n=1)
    result = compile_fixture(declaration, snapshot, policy)
    assert result["objective_positive_mask"] == [[True]]
    assert result["objective_permitted_negative_mask"] == [[False]]
    assert result["objective_blockers"] == ["no_negative_separation"]


def test_handoff_malformed_declaration_and_payload_bounds_fail_closed(monkeypatch):
    declaration, snapshot, policy, expected = synthetic()
    invalid = {"schema": "bad"}
    expected["declaration_sha256"] = subject._digest(invalid)
    with pytest.raises(ValueError):
        compile_fixture(invalid, snapshot, policy, expected)
    monkeypatch.setattr(subject, "MAX_BYTES", 1000)
    with pytest.raises(ValueError, match="byte bound"):
        compile_fixture(declaration, snapshot, policy)


def test_handoff_no_optional_stack_verifier_numerics_or_io_during_prepare_compile_and_replay(tmp_path):
    root = Path(__file__).resolve().parents[5]
    declaration = fixtures.declaration()
    payload = json.dumps({"declaration": declaration, "expected": fixtures.pins(declaration)})
    code = '''
import importlib.abc,json,sys,types
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root))
for name,relative in [('ipfs_datasets_py','ipfs_datasets_py'),('ipfs_datasets_py.logic','ipfs_datasets_py/logic'),('ipfs_datasets_py.logic.formalization','ipfs_datasets_py/logic/formalization'),('ipfs_datasets_py.logic.formalization.autoencoder','ipfs_datasets_py/logic/formalization/autoencoder')]:
 m=types.ModuleType(name);m.__path__=[str(root/relative)];m.__package__=name;sys.modules[name]=m
blocked={'torch','numpy','scipy','transformers','sentence_transformers','spacy','safetensors','tensorflow','jax','lean','z3','cvc5'}
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in blocked: raise RuntimeError('optional stack import')
sys.meta_path.insert(0,Guard())
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_relation_mask_handoff as subject
request=json.loads(sys.stdin.read())
def deny(event,args):
 if event in {'open','os.listdir','os.scandir','subprocess.Popen','socket.__new__'}: raise RuntimeError('I/O during mask handoff')
sys.addaudithook(deny)
prepared=subject.prepare_unavailable_relation_handoff(request['declaration'],expected_declaration_bindings=request['expected'])
result=subject.compile_train_relation_masks(request['declaration'],prepared['snapshot'],prepared['policy'],expected_bindings=prepared['expected_bindings'])
subject.validate_train_relation_mask_handoff(result,request['declaration'],prepared['snapshot'],prepared['policy'],expected_bindings=prepared['expected_bindings'])
assert not blocked.intersection(sys.modules)
assert result['actual_fit_authorized'] is False
print(json.dumps({'pair_count':result['pair_count'],'calls':result['model_calls']+result['prover_calls']}))
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(root)], input=payload,
                            text=True, capture_output=True, cwd=tmp_path, timeout=10, check=True)
    assert json.loads(result.stdout) == {"pair_count": 9, "calls": 0}
