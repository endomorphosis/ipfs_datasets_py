"""Small exact ridge/readout controls; no pretrained models or corpus fitting."""
from copy import deepcopy
import hashlib
import random

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_source_slot_probe as subject
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from .test_long_span_cardinality_training import validate_rule


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def data(kind="conditioning", split="train"):
    width = {"conditioning":48, "projected_source":384, "intercept":0}[kind]
    spec = dict(id="synthetic-"+kind, kind=kind, dimension=width,
        provenance=dict(scope="synthetic-only", model_forward_executed=False))
    features, refs = [], []
    for i in range(2):
        identity = split+str(i)
        source = "synthetic "+identity
        digest = hashlib.sha256(source.encode()).hexdigest()
        value = [-1.+2*i]+[0.]*(width-1) if width else []
        rule = dict(actor="left" if i == 0 else "right", action="retain", modality="O", object="file",
            conditions=[], exceptions=[], temporal=[])
        features.append(dict(id=identity, source_sha256=digest, features=value))
        refs.append(dict(id=identity, source_sha256=digest, source_text=source,
            target={"rules":[deepcopy(rule)]*(i+1)}, clause_count=i+1))
    return features, refs, spec


def fit(kind="conditioning"):
    rows,refs,spec = data(kind)
    result = subject.fit_probe(rows,refs,feature_specification=spec,validate_rule=validate_rule,validator_id="synthetic/v1")
    return result, rows, refs


def evaluate(probe, rows, refs, *, source=None, kind="conditioned", **kwargs):
    source = source or rows
    ids = [r["id"] for r in rows]
    assignment = dict(zip(ids, list(reversed(ids)) if kind in ("source_shuffle","cross_length_shuffle") else ids))
    return subject.evaluate_probe(probe,rows,refs,source_features=source,
        control=dict(kind=kind,source_assignment=assignment),validate_rule=validate_rule,validator_id="synthetic/v1",**kwargs)


@pytest.mark.parametrize("kind",["conditioning","projected_source","intercept"])
def test_fits_training_only_full_slots_count_and_valid_normal_equations(kind):
    result,rows,refs = fit(kind);probe=result["probe"];report=result["report"]
    assert len(probe["heads"]) == 33 and probe["fields"] == list(subject.FIELDS)
    assert probe["heads"][0]["classes"][0] == {"kind":"absent"}
    assert probe["heads"][-1]["classes"] == [{"kind":"count","value":n} for n in range(1,9)]
    assert report["normal_equation"]["verified"] and report["normal_equation"]["max_abs_residual"] < 1e-10
    assert report["ridge_lambda"] == .001 and report["dual_diagonal_regularizer"] == .002
    assert report["validation_rows_used_for_fitting"] == 0 and report["probe_fitting_executed"]
    assert all(report[k] is False for k in subject.FALSE)
    actual=evaluate(probe,rows,refs)
    assert actual["report"]["aggregates"]["gold_present_scalar_values"]["total"] == 12
    assert actual["report"]["aggregates"]["gold_absent_slots"]["total"] == 52
    assert all(len(r["prediction"]["slots"]) == 8 for r in actual["rows"])
    assert not actual["report"]["oracle_count_mask_applied"]
    if kind != "intercept":
        assert actual["report"]["aggregates"]["scalar_slots_and_count_exact"] == 2
        assert report["transform"]["mean_training_centered_row_squared_norm"] == 1.
    else:
        assert probe["coefficients"] == [] and probe["transform"]["constant_training_features"]
        assert actual["rows"][0]["prediction"]["scores"] == actual["rows"][1]["prediction"]["scores"]


def test_analytic_two_row_solution_and_primal_certificate_independent_of_dual_solver():
    result,_,_=fit();p=result["probe"];r=result["report"]
    h=p["heads"][0];left=h["classes"].index({"kind":"value","value":"left"})
    column=h["start"]+left
    assert p["intercept"][column] == .5
    assert p["coefficients"][0][column] == pytest.approx(-.5/(1.+.001),abs=1e-14)
    assert all(row[column] == 0. for row in p["coefficients"][1:])
    x=torch.tensor(r["raw_training_feature_matrix"],dtype=torch.float64)
    z=(x-torch.tensor(p["transform"]["mean"]))/p["transform"]["scale"]
    y=torch.tensor(r["training_onehot_matrix"],dtype=torch.float64)
    w=torch.tensor(p["coefficients"],dtype=torch.float64);bias=torch.tensor(p["intercept"],dtype=torch.float64)
    residual=z.T@(z@w+bias-y)/len(x)+.001*w
    assert float(residual.abs().max()) <= r["normal_equation"]["absolute_tolerance"]


def test_global_rms_fair_across_duplicated_dimensions_not_per_column_standardization():
    rows,refs,spec=data()
    one=subject.fit_probe(rows,refs,feature_specification=spec,validate_rule=validate_rule,validator_id="synthetic/v1")
    doubled=deepcopy(rows)
    for row in doubled:row["features"][1]=row["features"][0]
    two=subject.fit_probe(doubled,refs,feature_specification=spec,validate_rule=validate_rule,validator_id="synthetic/v1")
    assert two["probe"]["transform"]["scale"] == pytest.approx(2**.5)
    p1=subject.predict_probe(one["probe"],rows)["predictions"]
    p2=subject.predict_probe(two["probe"],doubled)["predictions"]
    for a,b in zip(p1,p2):assert a["scores"] == pytest.approx(b["scores"],abs=1e-12)


def test_zero_normalized_features_equal_training_class_prior_and_intercept_baseline():
    result,rows,_=fit();baseline,empty,_=fit("intercept")
    zero=subject.predict_probe(result["probe"],rows,zero_features=True)
    prior=subject.predict_probe(baseline["probe"],empty)
    assert zero["report"]["zero_scope"] == "normalized_zero_equals_training_mean_features_intercept_only"
    for a,b in zip(zero["predictions"],prior["predictions"]):
        assert a["scores"] == b["scores"] == result["probe"]["intercept"]
        assert a["class_indices"] == b["class_indices"]


def test_prediction_api_is_reference_free_and_field_value_absent_is_not_structural_absence():
    rows,refs,spec=data(); refs[0]["target"]["rules"][0]["actor"]="ABSENT"
    result=subject.fit_probe(rows,refs,feature_specification=spec,validate_rule=validate_rule,validator_id="synthetic/v1")
    classes=result["probe"]["heads"][0]["classes"]
    assert {"kind":"absent"} in classes and {"kind":"value","value":"ABSENT"} in classes
    assert subject.predict_probe(result["probe"],rows)["predictions"][0]["slots"][0]["actor"] == {"kind":"value","value":"ABSENT"}
    with pytest.raises(TypeError):subject.predict_probe(result["probe"],rows,references=refs)


def test_validation_unseen_values_are_wrong_and_never_expand_training_classes():
    result,_,_=fit();rows,refs,_=data(split="validation");before=deepcopy(result["probe"])
    refs[0]["target"]["rules"][0]["actor"]="unseen"
    evaluated=evaluate(result["probe"],rows,refs)
    assert evaluated["report"]["aggregates"]["by_facet"]["actor"]["out_of_training_inventory"] == 1
    assert evaluated["rows"][0]["scalar_slots"][0]["correct"] is False
    assert result["probe"] == before


def test_no_gold_count_mask_or_repair_when_predicted_presence_disagrees():
    result,rows,refs=fit("intercept");probe=deepcopy(result["probe"])
    probe["intercept"]=[0.]*len(probe["intercept"])
    for h in probe["heads"]:
        index=0 if h["name"] == "count" else 1
        probe["intercept"][h["start"]+index]=1.
    probe["probe_sha256"]=core.digest({k:v for k,v in probe.items() if k!="probe_sha256"})
    actual=evaluate(probe,rows,refs)
    assert all(r["prediction"]["predicted_count"] == 1 for r in actual["rows"])
    assert all(all(v["kind"]=="value" for slot in r["prediction"]["slots"] for v in slot.values()) for r in actual["rows"])
    assert actual["report"]["aggregates"]["count_and_slot_presence_consistent"] == 0
    assert actual["report"]["aggregates"]["scalar_slots_and_count_exact"] == 0


@pytest.mark.parametrize("kind",["conditioned","source_shuffle","cross_length_shuffle","zero_features"])
def test_controls_verify_exact_assignments_and_count_strata(kind):
    result,originals,refs=fit();rows=deepcopy(originals)
    if kind in ("source_shuffle","cross_length_shuffle"):
        rows[0]["features"],rows[1]["features"]=rows[1]["features"],rows[0]["features"]
    if kind=="source_shuffle":
        with pytest.raises(ValueError,match="count stratum"):evaluate(result["probe"],rows,refs,source=originals,kind=kind)
    else:
        actual=evaluate(result["probe"],rows,refs,source=originals,kind=kind)
        assert actual["report"]["count_labels_preserved_by_assignment"] == (kind!="cross_length_shuffle")
        if kind=="cross_length_shuffle":assert actual["report"]["aggregates"]["count_correct"] == 0


def test_same_length_shuffle_preserves_counts_but_changes_source_features():
    rows,refs,spec=data()
    refs[1]["target"]["rules"]=refs[1]["target"]["rules"][:1];refs[1]["clause_count"]=1
    result=subject.fit_probe(rows,refs,feature_specification=spec,validate_rule=validate_rule,validator_id="synthetic/v1")
    shuffled=deepcopy(rows);shuffled[0]["features"],shuffled[1]["features"]=shuffled[1]["features"],shuffled[0]["features"]
    actual=evaluate(result["probe"],shuffled,refs,source=rows,kind="source_shuffle")
    assert actual["report"]["aggregates"]["count_correct"] == 2
    assert actual["report"]["aggregates"]["by_facet"]["actor"]["correct"] == 0


@pytest.mark.parametrize("failure",["source","duplicate","too_many_slots","nonfinite","wrong_width","lambda","validator_mutation"])
def test_fit_rejects_incomplete_provenance_or_protocol_changes(failure):
    rows,refs,spec=data();kwargs={}
    validator=validate_rule
    if failure=="source":refs[0]["source_text"]+="changed"
    elif failure=="duplicate":rows[1]["id"]=rows[0]["id"]
    elif failure=="too_many_slots":refs[0]["target"]["rules"]*=9;refs[0]["clause_count"]=9
    elif failure=="nonfinite":rows[0]["features"][0]=float("nan")
    elif failure=="wrong_width":rows[0]["features"].pop()
    elif failure=="lambda":kwargs["ridge_lambda"]=1.
    else:
        def validator(value):value["rules"][0]["actor"]="changed";return {"valid":True}
    with pytest.raises(ValueError):subject.fit_probe(rows,refs,feature_specification=spec,validate_rule=validator,validator_id="synthetic/v1",**kwargs)


def test_fit_predict_evaluate_preserve_inputs_and_rng_including_validator():
    rows,refs,spec=data();before=deepcopy((rows,refs,spec));rng=torch.get_rng_state().clone();py=random.getstate()
    def validator(value):random.random();torch.rand(1);return validate_rule(value)
    result=subject.fit_probe(rows,refs,feature_specification=spec,validate_rule=validator,validator_id="synthetic/v1")
    subject.predict_probe(result["probe"],rows)
    subject.evaluate_probe(result["probe"],rows,refs,source_features=rows,
        control=dict(kind="conditioned",source_assignment={r["id"]:r["id"] for r in rows}),validate_rule=validator,validator_id="synthetic/v1")
    assert (rows,refs,spec)==before
    assert torch.equal(rng,torch.get_rng_state()) and py==random.getstate()


def test_memory_preflight_rejects_before_solver(monkeypatch):
    rows,refs,spec=data()
    def forbidden(*args,**kwargs):raise AssertionError("solver before memory guard")
    monkeypatch.setattr(torch.linalg,"solve",forbidden)
    with pytest.raises(ValueError,match="memory"):subject.fit_probe(rows,refs,feature_specification=spec,
        validate_rule=validate_rule,validator_id="synthetic/v1",max_memory_bytes=1048576)


def test_deadline_includes_postsolve_cleanup_and_does_not_return_completed_probe(monkeypatch):
    rows,refs,spec=data();clock=[0.];original=torch.linalg.solve
    def solve(*args,**kwargs):
        result=original(*args,**kwargs);clock[0]=31.;return result
    monkeypatch.setattr(torch.linalg,"solve",solve)
    monkeypatch.setattr(subject.time,"monotonic",lambda:clock[0])
    rng=torch.get_rng_state().clone();py=random.getstate()
    with pytest.raises(TimeoutError):subject.fit_probe(rows,refs,feature_specification=spec,
        validate_rule=validate_rule,validator_id="synthetic/v1")
    assert torch.equal(rng,torch.get_rng_state()) and py==random.getstate()


def test_tampered_coefficients_fail_digest_before_prediction():
    result,rows,_=fit();result["probe"]["coefficients"][0][0]+=1
    with pytest.raises(ValueError,match="digest"):subject.predict_probe(result["probe"],rows)
