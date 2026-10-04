"""Pure synthetic controls: no real corpus, encoder or proof execution."""
from collections import Counter
from copy import deepcopy
import json

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import authored_training_paraphrases as subject
from ipfs_datasets_py.logic.formalization.autoencoder import training_paraphrase_source_inputs as source


def inputs():
    b = subject.base
    codec = dict(schema="typed-json-lexical/v1", target_vocabulary=list(b.VOCABULARY))
    rows = []
    for offset in range(3):
        for index, actor in enumerate(b.ACTORS):
            action = b.ACTIONS[(index+offset)%5]
            for obj in b.OBJECTS:
                for modality in b.MODALITIES:
                    target = dict(rules=[dict(actor=actor, action=action, object=obj,
                        modality=modality, conditions=[], exceptions=[], temporal=[])])
                    for style in range(2):
                        predicate = ({"O":"must", "P":"may", "F":"must not"} if style == 0 else
                            {"O":"is required to", "P":"is allowed to", "F":"is forbidden to"})[modality]
                        rows.append(dict(id="synthetic-train:"+str(len(rows)),
                            source_text=f"The {actor} {predicate} {action} the {obj}.", target_ids=b._encode(target,codec)))
    prior = [{k:r[k] for k in ("id","source_text")} for r in rows]
    return dict(training_bank=rows, prior_sources_by_dataset={"train":prior}, codec=codec,
        sealed_recipe_sha256="a"*64, validate_rule=lambda value:dict(valid=True,canonical_ir=value))


def test_complete_balanced_training_derivation_and_source_only_plan():
    args = inputs(); before = deepcopy(args); result = subject.build(**args)
    assert args == before
    assert len(result["source_rows"]) == len(result["references"]) == 48
    assert Counter(r["clause_count"] for r in result["references"]) == {1:12,2:12,4:12,8:12}
    counts = Counter()
    for row, ref in zip(result["source_rows"],result["references"]):
        assert set(row)=={"id","source_text"} and ref["split"]=="train_augmentation"
        assert row["id"]==ref["id"] and row["source_text"]==ref["source_text"]
        assert json.loads("".join(subject.base.VOCABULARY[i] for i in ref["target_ids"][1:-1]))==ref["target"]
        assert len(ref["target_ids"])<=512
        for text,rule,derivation in zip(row["source_text"].split("\n\n"),ref["target"]["rules"],ref["derivations"]):
            assert text==subject.sentence(ref["template"],rule)
            assert derivation["rule_sha256"]==subject.digest(rule)
            assert len(derivation["original_train_sources"])==2
            counts[rule["modality"]]+=1
    assert counts=={"O":60,"P":60,"F":60}
    plan=source.source_plan(result["source_rows"],expected_source_rows_sha256=result["receipt"]["source_rows_sha256"],sealed_recipe_sha256="a"*64)
    assert source._plan(plan)==plan and plan["role"]=="train_augmentation"
    assert plan["shape_plan"]["unique_sources"]==216 and plan["target_access"] is False
    assert all(result["receipt"][k] is False for k in subject.FALSE)


@pytest.mark.parametrize("name",["train","dev","test","canary","r6","r8","v3"])
def test_prior_literal_and_casefold_whitespace_overlap_rejected(name):
    args=inputs(); row=subject.build(**args)["source_rows"][0]
    text=row["source_text"].split("\n\n")[0].upper().replace(" ","  ")
    args["prior_sources_by_dataset"].setdefault(name,[]).append(dict(id="prior-collision",source_text=text))
    with pytest.raises(ValueError,match="overlaps prior"): subject.build(**args)


@pytest.mark.parametrize("mutation",["missing","duplicate","boolean_token","unknown_token","unbalanced","extra_field","codec","validator"])
def test_invalid_original_training_rejected_without_repair(mutation):
    args=inputs()
    if mutation=="missing":args["training_bank"].pop()
    elif mutation=="duplicate":args["training_bank"][1]=deepcopy(args["training_bank"][0])
    elif mutation=="boolean_token":args["training_bank"][0]["target_ids"][0]=True
    elif mutation=="unknown_token":args["training_bank"][0]["target_ids"][3]=32
    elif mutation=="unbalanced":args["training_bank"][0]["target_ids"]=list(args["training_bank"][4]["target_ids"])
    elif mutation=="extra_field":args["training_bank"][0]["input"]=[0.]*384
    elif mutation=="codec":args["codec"]["target_vocabulary"].pop()
    elif mutation=="validator":args["validate_rule"]=lambda value:dict(valid=False)
    with pytest.raises(ValueError):subject.build(**args)


@pytest.mark.parametrize("key,value",[("role","holdout"),("target_access",True),("plan_sha256","0"*64)])
def test_training_plan_role_and_binding_fail_closed(key,value):
    built=subject.build(**inputs())
    p=source.source_plan(built["source_rows"],expected_source_rows_sha256=built["receipt"]["source_rows_sha256"],sealed_recipe_sha256="a"*64)
    p[key]=value
    with pytest.raises(ValueError):source._plan(p)


@pytest.mark.parametrize("dimension",[8,4096,True,384.0])
def test_no_width_substitution_or_fallback(dimension):
    with pytest.raises(ValueError,match="verified384/768"):
        source.produce_width({},dimension=dimension,asset_config={})


def test_authority_and_native_report_are_required():
    built=subject.build(**inputs())
    p=source.source_plan(built["source_rows"],expected_source_rows_sha256=built["receipt"]["source_rows_sha256"],sealed_recipe_sha256="a"*64)
    with pytest.raises(ValueError,match="binding differs"):source.validate_report(p,{"schema":source.REPORT})


def test_local_random_state_unchanged():
    import random
    before=random.getstate();subject.build(**inputs());assert random.getstate()==before


def runner():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).resolve().parents[5]/'scripts/ops/autoencoder/prepare_training_paraphrases.py'
    spec=importlib.util.spec_from_file_location('_test_training_prepare_runner',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('key,value', [('role','holdout'),('context_tokens',513),('output_tokens',1024),
    ('temperature',.1),('qualified',True),('workers',True),('dimensions',[8,384]),('training_executed',True)])
def test_preparation_recipe_cannot_acquire_training_or_qualification_authority(key,value):
    module=runner();plan=deepcopy(module.FIXED);module.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError):module.validate_plan(plan)
