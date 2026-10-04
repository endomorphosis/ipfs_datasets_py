"""Closed diagnostic relation metadata never authorizes contrastive labels."""
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import alignment_lane_bundle as lane
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_relation_declarations as subject,
)


def seal(value):
    value["content_sha256"] = subject._digest({key: item for key, item in value.items() if key != "content_sha256"})
    return value


def role(schema, **fields):
    return seal({"schema": schema, **fields})


def pins(declaration):
    return subject.stages._bindings({key: value for key, value in declaration.items()
                                     if key not in {"schema", "content_sha256"}})


def declaration(n=3, same_formal=False, unavailable=()):
    profile = role(lane.PROFILE_SCHEMA, lane_id="legacy8", stage="historical_linguistic_features", dimension=8,
        producer={"profile_id": "relation-fixture-only", "model_id": "no-model-fixture", "model_revision": "fixture-v1",
                  "code_sha256": "a" * 64, "model_assets_sha256": "b" * 64, "checkpoint_sha256": None},
        pooling={"method": "none", "endpoint": "linguistic_features"}, normalization={"kind": "none", "unit_tolerance": None},
        precision="decimal6", fit_input_recipe="exact_source_only/v1", inference_input_recipe="exact_source_only/v1")
    rows, bound, inputs = [], [], []
    for index in range(n):
        identity, text = "train_" + str(index), "Independent source statement " + str(index)
        request = {"source_text": text, "context": {"role": "none_required", "text": "", "bindings": {},
                   "sha256": hashlib.sha256(b"").hexdigest()}}
        vector = [float(index + 1), *([0.0] * 7)]
        status, reason = "available", None
        if index in unavailable:
            status, reason, vector = "unavailable", "historical representation unavailable", None
        binding = {"id": identity, "input_sha256": subject._digest(request),
                   "encoder_text_sha256": hashlib.sha256(text.encode()).hexdigest(), "status": status, "reason": reason,
                   "vector_sha256": subject._digest(vector) if vector is not None else None,
                   "upstream_vector_sha256": None, "token_receipt_sha256": None}
        bound.append(binding)
        inputs.append({"id": identity, "input_sha256": binding["input_sha256"]})
        rows.append({**binding, "input": request, "encoder_text": text, "vector": vector,
                     "producer_row_sha256": subject._digest(binding)})
    producer = role(lane.PRODUCER_SCHEMA, profile_sha256=subject._digest(profile), rows=bound,
                    artifact_binding={"path": "never-opened-fixture.json", "bytes": 1, "sha256": "c" * 64})
    bundle = role(lane.SCHEMA, profile=profile, producer_receipt=producer, rows=rows)
    receipt = lane.validate_lane_bundle(bundle, expected_bindings={"profile_sha256": subject._digest(profile),
        "producer_receipt_sha256": subject._digest(producer), "inputs": inputs})
    train_rows = [{"id": row["id"], "input_sha256": row["input_sha256"], "representation_sha256": row["vector_sha256"],
                   "status": row["status"], "reason": row["reason"], "split": "train",
                   "formal_view_sha256": subject._digest({"fixture_formal": 0 if same_formal and index < 2 else index}),
                   "masks": dict.fromkeys(lane.MASKS, 0)} for index, row in enumerate(bound)]
    train = role("alignment-train-manifest/v1", rows=train_rows, file_binding=None)
    policy = role(subject.POLICY_SCHEMA, mode=subject.MODE, pair_order=subject.PAIR_ORDER,
        weak_structural_policy=subject.WEAK_STRUCTURAL_POLICY, family_coercion_policy=subject.FAMILY_COERCION_POLICY,
        source_family_id="declared-family-only", target_family_id=None, source_profile_sha256=receipt["profile_sha256"],
        target_profile_sha256=None)
    pairs = [{"left_id": left["id"], "right_id": right["id"],
              "left_input_sha256": left["input_sha256"], "right_input_sha256": right["input_sha256"],
              "left_formal_view_sha256": left["formal_view_sha256"], "right_formal_view_sha256": right["formal_view_sha256"],
              "relation_status": "weak_structural_identity" if left["formal_view_sha256"] == right["formal_view_sha256"] else "unknown",
              "evidence_sha256": None, "reason": "fixture declaration; not semantic evidence",
              "positive_mask": False, "permitted_negative_mask": False} for left in train_rows for right in train_rows]
    ledger = role(subject.LEDGER_SCHEMA, rows=pairs)
    return role(subject.SCHEMA, lane_validation=receipt, train_manifest=train, relation_policy=policy, pair_ledger=ledger)


def refresh(value):
    for name in ("lane_validation", "train_manifest", "relation_policy", "pair_ledger"):
        seal(value[name])
    return seal(value)


def validate(value, expected=None):
    return subject.validate_relation_declaration(value, expected_bindings=pins(value) if expected is None else expected)


def test_complete_ledger_is_deterministic_detached_and_entirely_blocked():
    value = declaration()
    original = deepcopy(value)
    result = validate(value)
    assert result == validate(value) and value == original
    assert result["pair_count"] == 9 and result["train_row_count"] == 3
    assert result["declared_relation_counts"] == {"unknown": 6, "weak_structural_identity": 3,
                                                "declared_positive": 0, "declared_negative": 0}
    assert all(result[key] is False for key in subject.FALSE)
    assert result["eligibility"] == subject.ELIGIBILITY
    assert result["masks"] == dict.fromkeys(lane.MASKS, 0)
    assert result["positive_mask"] == result["permitted_negative_mask"] == [[False] * 3 for _ in range(3)]
    assert all(row["positive_mask"] is row["permitted_negative_mask"] is False for row in result["rows"])
    assert result["weak_diagnostic_policy_required"] is True
    assert result["content_sha256"] == subject._digest({key: item for key, item in result.items() if key != "content_sha256"})
    result["rows"][0]["reason"] = "changed output"
    result["positive_mask"][0][0] = True
    assert value == original and validate(value)["positive_mask"][0][0] is False


def test_sixteen_distinct_train_formal_views_have_256_pairs_unknown240_weak16():
    result = validate(declaration(16))
    assert result["pair_count"] == 256
    assert result["declared_relation_counts"]["unknown"] == 240
    assert result["declared_relation_counts"]["weak_structural_identity"] == 16
    assert result["exact_formal_identity_pair_count"] == 16
    assert result["admitted_positive_pair_count"] == result["permitted_negative_pair_count"] == 0


def test_equal_formal_views_across_distinct_sources_remain_weak_only():
    value = declaration(same_formal=True)
    result = validate(value)
    assert result["exact_formal_identity_pair_count"] == result["declared_relation_counts"]["weak_structural_identity"] == 5
    assert result["semantic_positive_pair_count"] == 0
    assert all(not cell for row in result["positive_mask"] for cell in row)


def test_declared_relations_evidence_and_cross_family_scope_never_enable_masks():
    value = declaration()
    pairs = value["pair_ledger"]["rows"]
    pairs[1].update(relation_status="declared_positive", evidence_sha256="d" * 64)
    pairs[3].update(relation_status="declared_negative", evidence_sha256="e" * 64)
    value["relation_policy"].update(target_family_id="another-declared-family", target_profile_sha256="f" * 64)
    result = validate(refresh(value))
    assert result["declared_relation_counts"]["declared_positive"] == result["declared_relation_counts"]["declared_negative"] == 1
    assert result["declared_evidence_count"] == 2 and result["admitted_evidence_count"] == 0
    assert result["rows"][1]["evidence_status"] == "declared_unverified_unadmitted"
    assert result["declared_family_profile_scope"]["target_profile_sha256"] == "f" * 64
    assert result["family_profile_scope_verified"] is result["evidence_contents_verified"] is False
    assert all(not cell for row in result["permitted_negative_mask"] for cell in row)


def test_even_contradictory_declarations_are_metadata_and_identity_does_not_auto_admit():
    value = declaration()
    value["pair_ledger"]["rows"][0]["relation_status"] = "declared_negative"
    result = validate(refresh(value))
    assert result["declared_relation_counts"]["declared_negative"] == 1
    assert result["exact_formal_identity_pair_count"] == 3
    assert result["permitted_negative_pair_count"] == 0


def test_missing_representation_is_retained_not_dropped_from_cartesian_ledger():
    result = validate(declaration(unavailable=(1,)))
    assert result["train_row_count"] == 3 and result["pair_count"] == 9
    assert result["eligibility"] == subject.ELIGIBILITY


@pytest.mark.parametrize("field", ["left_id", "right_id", "left_input_sha256", "right_input_sha256",
                                   "left_formal_view_sha256", "right_formal_view_sha256"])
def test_resealed_pair_foreign_join_rejects_even_when_its_role_is_repinned(field):
    value = declaration()
    value["pair_ledger"]["rows"][1][field] = "foreign" if field.endswith("_id") else "f" * 64
    with pytest.raises(ValueError, match="binding differs"):
        validate(refresh(value))


@pytest.mark.parametrize("operation", ["reorder", "missing", "duplicate", "extra"])
def test_pair_ledger_is_complete_exactly_once_and_in_train_row_major_order(operation):
    value = declaration()
    pairs = value["pair_ledger"]["rows"]
    if operation == "reorder":
        pairs[1], pairs[3] = pairs[3], pairs[1]
    elif operation == "missing":
        pairs.pop()
    elif operation == "duplicate":
        pairs[1] = deepcopy(pairs[0])
    else:
        pairs.append(deepcopy(pairs[0]))
    with pytest.raises(ValueError):
        validate(refresh(value))


def test_weak_identity_cannot_be_claimed_for_different_formal_hashes():
    value = declaration()
    value["pair_ledger"]["rows"][1]["relation_status"] = "weak_structural_identity"
    with pytest.raises(ValueError, match="exact formal-view identity"):
        validate(refresh(value))


@pytest.mark.parametrize("field,value", [("positive_mask", True), ("positive_mask", 0),
                                        ("permitted_negative_mask", True), ("permitted_negative_mask", 0)])
def test_declared_pair_masks_are_exact_false_not_bool_integer_aliases(field, value):
    item = declaration()
    item["pair_ledger"]["rows"][1][field] = value
    with pytest.raises(ValueError, match="exact boolean false"):
        validate(refresh(item))


@pytest.mark.parametrize("location", ["declaration", "policy", "ledger", "pair", "train"])
def test_authority_or_review_fields_are_closed_not_implicitly_admitted(location):
    value = declaration()
    targets = {"declaration": value, "policy": value["relation_policy"], "ledger": value["pair_ledger"],
               "pair": value["pair_ledger"]["rows"][0], "train": value["train_manifest"]}
    targets[location]["semantic_label_admission"] = True
    with pytest.raises(ValueError, match="closed"):
        validate(refresh(value))


@pytest.mark.parametrize("name", ["lane_validation", "train_manifest", "relation_policy", "pair_ledger"])
def test_local_resealing_cannot_replace_an_externally_selected_role(name):
    value = declaration()
    expected = pins(value)
    if name == "lane_validation":
        value[name]["bundle_sha256"] = "f" * 64
    elif name == "train_manifest":
        value[name]["rows"][0]["formal_view_sha256"] = "f" * 64
    elif name == "relation_policy":
        value[name]["target_family_id"] = "new-family-declaration"
    else:
        value[name]["rows"][0]["reason"] = "new evidence declaration"
    with pytest.raises(ValueError, match="externally pinned"):
        validate(refresh(value), expected)


def test_external_pins_include_ordered_pair_rows_digest_and_full_sealed_value():
    value = declaration()
    expected = pins(value)
    expected["pair_ledger"]["rows_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="ordered rows"):
        validate(value, expected)
    expected = pins(value)
    expected["pair_ledger"]["value_sha256"] = subject._digest(value["pair_ledger"]["rows"])
    with pytest.raises(ValueError, match="externally pinned"):
        validate(value, expected)


def test_required_external_roles_and_their_separate_byte_bound_are_enforced():
    value = declaration()
    expected = pins(value)
    expected.pop("pair_ledger")
    with pytest.raises(ValueError, match="closed"):
        validate(value, expected)
    expected = pins(value)
    expected["extra"] = "x" * (subject.MAX_EXPECTED_BYTES + 1)
    with pytest.raises(ValueError, match="external relation pins byte bound"):
        validate(value, expected)


def test_train_source_profile_input_and_vector_receipt_joins_are_independent():
    for key in ("input_sha256", "representation_sha256"):
        value = declaration()
        value["train_manifest"]["rows"][0][key] = "f" * 64
        with pytest.raises(ValueError, match="ordered ledger differs"):
            validate(refresh(value))
    value = declaration()
    value["relation_policy"]["source_profile_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="source profile differs"):
        validate(refresh(value))


@pytest.mark.parametrize("field,value", [("split", "validation"), ("masks", dict.fromkeys(lane.MASKS, 1)),
                                        ("masks", dict.fromkeys(lane.MASKS, False))])
def test_only_train_and_exact_integer_zero_supervision_masks_are_accepted(field, value):
    item = declaration()
    item["train_manifest"]["rows"][0][field] = value
    with pytest.raises(ValueError):
        validate(refresh(item))


@pytest.mark.parametrize("field,value", [("mode", "train_now"), ("pair_order", "unordered"),
                                        ("weak_structural_policy", "semantic_equivalence"),
                                        ("family_coercion_policy", "coerce_all_families")])
def test_policy_cannot_enable_fitting_coercion_or_implicit_relations(field, value):
    item = declaration()
    item["relation_policy"][field] = value
    with pytest.raises(ValueError, match="differs"):
        validate(refresh(item))


@pytest.mark.parametrize("field,value", [("evidence_sha256", "not-a-sha"), ("reason", ""),
                                        ("reason", "x" * 4097), ("relation_status", "admitted_positive")])
def test_pair_metadata_is_bounded_closed_and_not_an_admission_receipt(field, value):
    item = declaration()
    item["pair_ledger"]["rows"][0][field] = value
    with pytest.raises(ValueError):
        validate(refresh(item))


def test_empty_oversized_nonfinite_and_nonordinary_json_fail_closed():
    value = declaration()
    value["train_manifest"]["rows"] = []
    with pytest.raises(ValueError):
        validate(refresh(value))
    with pytest.raises(ValueError):
        validate(declaration(0))
    with pytest.raises(ValueError):
        validate(declaration(129))
    value = declaration()
    value["pair_ledger"]["rows"][0]["reason"] = float("nan")
    with pytest.raises(ValueError):
        subject.validate_relation_declaration(value, expected_bindings={})
    value["pair_ledger"]["rows"][0]["reason"] = object()
    with pytest.raises(ValueError):
        subject.validate_relation_declaration(value, expected_bindings={})
    value = declaration()
    value["extra"] = "x" * (subject.MAX_BYTES + 1)
    with pytest.raises(ValueError, match="byte bound"):
        subject.validate_relation_declaration(value, expected_bindings={})


def test_no_file_model_or_prover_access_during_validation_and_no_optional_imports(tmp_path):
    root = Path(__file__).resolve().parents[5]
    value = declaration()
    payload = json.dumps({"declaration": value, "expected": pins(value)})
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
from ipfs_datasets_py.logic.formalization.autoencoder.alignment_relation_declarations import validate_relation_declaration
request=json.loads(sys.stdin.read())
def deny(event,args):
 if event in {'open','os.listdir','os.scandir','subprocess.Popen','socket.__new__'}: raise RuntimeError('I/O during relation validation')
sys.addaudithook(deny)
result=validate_relation_declaration(request['declaration'],expected_bindings=request['expected'])
assert result['eligibility']=='blocked_no_admitted_relations'
assert not blocked.intersection(sys.modules)
print(json.dumps({'pair_count':result['pair_count'],'calls':result['model_calls']+result['prover_calls']}))
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(root)], input=payload,
                            text=True, capture_output=True, cwd=tmp_path, timeout=10, check=True)
    assert json.loads(result.stdout) == {"pair_count": 9, "calls": 0}
