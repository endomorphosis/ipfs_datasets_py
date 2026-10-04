"""Benchmark admission/control helpers only; no neural or native workloads."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SPEC = importlib.util.spec_from_file_location("source_fidelity_benchmark_subject",
    ROOT / "scripts/ops/autoencoder/benchmark_decoder_source_fidelity.py")
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def control_rows():
    rows = [dict(id=identity, source_text="Original source "+identity,
        target_ids=[1,3+index,2], input=[float(index), float(index+1)])
        for index,identity in enumerate(("two-b","one-b","two-a","one-a"))]
    references=[dict(id=row["id"],clause_count=1 if row["id"].startswith("one") else 2)
        for row in rows]
    return rows,references


def test_source_shuffle_is_deterministic_equal_length_derangement_and_preserves_gold():
    rows,references=control_rows();before=deepcopy((rows,references))
    changed,receipt=subject.shuffle_inputs(rows,references)
    assert (rows,references)==before
    assert [row["id"] for row in changed]==[row["id"] for row in rows]
    assignment=receipt["source_assignment"]
    by_id={row["id"]:row for row in rows};lengths={row["id"]:row["clause_count"] for row in references}
    assert set(assignment)==set(assignment.values())==set(by_id)
    for old,new in zip(rows,changed):
        donor=assignment[old["id"]]
        assert donor != old["id"] and lengths[donor]==lengths[old["id"]]
        assert new["source_text"]==old["source_text"] and new["target_ids"]==old["target_ids"]
        assert new["input"]==by_id[donor]["input"]
        hashes=receipt["input_substitutions"][old["id"]]
        assert hashes["original_input_sha256"]==hashlib.sha256(subject.raw(old["input"])).hexdigest()
        assert hashes["substituted_input_sha256"]==hashlib.sha256(subject.raw(new["input"])).hexdigest()
    repeated,repeated_receipt=subject.shuffle_inputs(rows,list(reversed(references)))
    assert changed==repeated and receipt==repeated_receipt
    changed[0]["input"][0]=100000.
    assert (rows,references)==before


@pytest.mark.parametrize("bad", ["duplicate_rows","duplicate_references","unknown_reference",
    "missing_reference","missing_row","one_member_stratum","duplicate_vectors","empty"])
def test_shuffle_refuses_ambiguous_or_ineffective_controls(bad):
    rows,references=control_rows()
    if bad=="duplicate_rows":rows[1]=deepcopy(rows[0])
    if bad=="duplicate_references":references[1]=deepcopy(references[0])
    if bad=="unknown_reference":references[0]["id"]="unknown"
    if bad=="missing_reference":references.pop()
    if bad=="missing_row":rows.pop()
    if bad=="one_member_stratum":references[0]["clause_count"]=4
    if bad=="duplicate_vectors":rows[2]["input"]=deepcopy(rows[0]["input"])
    if bad=="empty":rows,references=[],[]
    with pytest.raises(ValueError):subject.shuffle_inputs(rows,references)


@pytest.mark.parametrize("count", [True,0,-1,1.0,"1",None])
def test_shuffle_requires_positive_integer_clause_count(count):
    rows,references=control_rows();references[0]["clause_count"]=count
    with pytest.raises(ValueError):subject.shuffle_inputs(rows,references)


def manifest(tmp_path):
    result={"inputs":{}}
    for key in ("donor","paragraphs","embeddings","curriculum","curriculum_inputs"):
        path=tmp_path/(key+".json");path.write_text('{}\n')
        result[key]=str(path)
        result["inputs"][str(path)]=subject.sha(path)
    return result


def test_manifest_requires_all_designated_inputs_to_be_pinned_and_unchanged(tmp_path):
    value=manifest(tmp_path);before=deepcopy(value)
    assert subject.validate_manifest_inputs(value) is None
    assert value==before
    Path(value["paragraphs"]).write_text('{"changed":true}\n')
    with pytest.raises(ValueError):subject.validate_manifest_inputs(value)


@pytest.mark.parametrize("key", ["donor","paragraphs","embeddings","curriculum","curriculum_inputs"])
def test_omitted_required_pointer_pin_cannot_escape_hash_checks(tmp_path,key):
    value=manifest(tmp_path);value["inputs"].pop(value[key])
    with pytest.raises(ValueError):subject.validate_manifest_inputs(value)


@pytest.mark.parametrize("key", ["donor","paragraphs","embeddings","curriculum","curriculum_inputs"])
def test_missing_designated_input_refused_before_training(tmp_path,key):
    value=manifest(tmp_path);del value[key]
    with pytest.raises(ValueError):subject.validate_manifest_inputs(value)


def test_all_extra_pinned_inputs_are_checked_too(tmp_path):
    value=manifest(tmp_path);path=tmp_path/"extra.json";path.write_text('{}')
    value["inputs"][str(path)]=subject.sha(path)
    subject.validate_manifest_inputs(value)
    path.write_text('[]')
    with pytest.raises(ValueError):subject.validate_manifest_inputs(value)


def plan():
    return dict(schema="long-source-fidelity-ablation-plan/v1",representations=[384],
        architecture_arms=["first_step","every_step"],loss_arms=["reference_ce","semantic_fields"],
        seed_order=[1729,2718],epochs_per_source_stage=20,expected_optimizer_steps_per_arm=340,
        expected_training_token_presentations_per_arm=225840,batch_size=8,learning_rate=.001,
        max_seconds_per_arm=45,validation_interval=4,fixed_encoder_context_tokens=512,
        fixed_decoder_output_limit=512,projection_frozen=True,teacher_distillation_used=False,
        controls=["zero_condition","source_shuffle_within_clause_count"],
        control_use="after_checkpoint_frozen; nevertrainorselect",strict_gates_changed=False,no_downloads=True)


def test_plan_accepts_exact_predeclared_2x2_with_descriptive_metadata():
    value=plan();value["scope_note"]="Exposed diagnostics, not a fresh holdout"
    original=deepcopy(value)
    subject.validate_plan(value)
    assert value==original


@pytest.mark.parametrize("key,value", [
    ("architecture_arms",["initial_condition","persistent_condition"]),
    ("architecture_arms",["first_step","first_step"]),
    ("architecture_arms",["every_step","first_step"]),
    ("loss_arms",["reference_ce","unknown_loss"]),
    ("seed_order",[1729,1729]),("representations",[8,384,768]),
    ("epochs_per_source_stage",21),("expected_optimizer_steps_per_arm",339),
    ("expected_training_token_presentations_per_arm",225839),("batch_size",16),
    ("learning_rate",.01),("max_seconds_per_arm",46),("validation_interval",5),
    ("fixed_encoder_context_tokens",1024),("fixed_decoder_output_limit",1024),
    ("projection_frozen",False),("teacher_distillation_used",True),
    ("controls",["zero_condition"]),("strict_gates_changed",True),("no_downloads",False)])
def test_unregistered_plan_changes_refused(key,value):
    data=plan();data[key]=value
    with pytest.raises(ValueError):subject.validate_plan(data)


@pytest.mark.parametrize("key", ["projection_frozen","teacher_distillation_used","strict_gates_changed","no_downloads"])
def test_plan_boolean_flags_cannot_be_relabelled_as_integer_truth_values(key):
    data=plan();data[key]=int(data[key])
    with pytest.raises(ValueError):subject.validate_plan(data)


@pytest.mark.parametrize("label", ["validation","training","zero-condition","source-shuffle"])
def test_evaluation_files_are_distinct_from_training_receipts_and_immutable(tmp_path,label):
    training={"optimizer_steps":340,"scope":"original training receipt"}
    subject.save(tmp_path/"training.json",training)
    original=(tmp_path/"training.json").read_bytes()
    evaluation={"scope":"postfit evaluation","label":label}
    descriptor=subject.save_evaluation(tmp_path,label,evaluation)
    assert Path(descriptor["path"])==tmp_path/("evaluation-"+label+".json")
    assert (tmp_path/"training.json").read_bytes()==original
    assert (tmp_path/("evaluation-"+label+".json")).read_bytes()==subject.raw(evaluation)+b"\n"
    with pytest.raises(FileExistsError):subject.save_evaluation(tmp_path,label,evaluation)


@pytest.mark.parametrize("label", ["", "train", "training.json", "../training", "validation/other", None, 1])
def test_unknown_evaluation_label_fails_before_writing_any_artifact(tmp_path,label):
    with pytest.raises(ValueError):subject.save_evaluation(tmp_path,label,{"scope":"test"})
    assert list(tmp_path.iterdir())==[]
