"""Selection-only gates, full document metrics, and sealed target boundaries."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from scripts.ops.legal_ir import run_legal_construction_retention_experiment as runner


def stage(steps, earlier=96, document=70, temporal=100, prior_new=50):
    return {"steps": steps, "tuning_earlier_exact": earlier, "tuning_document_exact": document,
        "tuning_temporal_exact": temporal, "tuning_prior_new_exact": prior_new}


@pytest.mark.parametrize("earlier,document,eligible", [(95,69,True),(94,70,False),(96,68,False),(94,68,False)])
def test_both_gates_have_exact_one_row_tolerance(earlier, document, eligible):
    candidate = stage(400, earlier, document)
    choice = runner.select_retained_stage([candidate, stage(800, 0, 0)], 96, 70)
    assert (choice == candidate) is eligible


def test_ranking_temporal_then_document_then_prior_new_then_earlier_then_earliest():
    a, b = stage(400,96,72,100,96), stage(800,95,71,101,0)
    assert runner.select_retained_stage([a,b],96,72)==b
    b["tuning_temporal_exact"]=100
    assert runner.select_retained_stage([a,b],96,72)==a
    b["tuning_document_exact"]=72
    assert runner.select_retained_stage([a,b],96,72)==a
    b["tuning_prior_new_exact"]=96
    assert runner.select_retained_stage([a,b],96,72)==a
    b["tuning_earlier_exact"]=96
    assert runner.select_retained_stage([b,a],96,72)==a


def test_document_reference_is_baseline_and_failure_returns_no_candidate():
    candidates=[stage(400,96,50,120),stage(800,96,51,120)]
    assert runner.select_retained_stage(candidates,96,70) is None
    # A weaker source-parent document score would incorrectly admit candidates.
    assert runner.select_retained_stage(candidates,96,50) is not None
    with pytest.raises(ValueError,match="protocol error"):
        runner.validate_document_reference(stage(800,94,70),96)
    runner.validate_document_reference(stage(800,95,70),96)


@pytest.mark.parametrize("mutation", ["missing_stage","duplicate_stage","bad_document","bad_temporal","bool_count"])
def test_invalid_or_incomplete_candidate_counts_rejected(mutation):
    rows=[stage(400),stage(800)]
    if mutation=="missing_stage": rows.pop()
    elif mutation=="duplicate_stage": rows[1]["steps"]=400
    elif mutation=="bad_document": rows[0]["tuning_document_exact"]=73
    elif mutation=="bad_temporal": rows[0]["tuning_temporal_exact"]=121
    else: rows[0]["tuning_earlier_exact"]=True
    with pytest.raises(ValueError): runner.select_retained_stage(rows,96,70)


def doc_fixture():
    rule={"actor":"Agency"}
    references=[{"candidate_id":"a","source_sha256":"a","supported":True,
        "clauses":[{"rule":rule,"char_start":0,"char_end":10},{"rule":rule,"char_start":11,"char_end":21}]}]
    generation={"rows":[{"candidate_id":"a","source_sha256":"a","segmentation_status":"segmented",
        "composition":{"source_rule_list":[rule,rule],"source_plan":{"clauses":[
            {"char_start":0,"char_end":10},{"char_start":11,"char_end":21}]}}}]}
    return generation,references


def test_repeated_identical_rules_with_wrong_occurrence_boundaries_fail_joint_exact():
    generated,refs=doc_fixture()
    measured=runner.score_document_tuning(generated,refs)
    assert measured["exact"]==measured["canonical_rule_list_exact"]==measured["occurrence_boundaries_exact"]==1
    generated["rows"][0]["composition"]["source_plan"]["clauses"][0]["char_end"]=9
    measured=runner.score_document_tuning(generated,refs)
    assert measured["canonical_rule_list_exact"]==1
    assert measured["occurrence_boundaries_exact"]==measured["exact"]==0


@pytest.mark.parametrize("mutation", ["merge","split","missing_boundaries","unsupported_accepted","abstained"])
def test_bad_segmentation_count_or_scope_stays_in_denominator(mutation):
    generated,refs=doc_fixture()
    comp=generated["rows"][0]["composition"]
    if mutation=="merge": comp["source_rule_list"].pop(); comp["source_plan"]["clauses"].pop()
    elif mutation=="split": comp["source_rule_list"].append({"actor":"Agency"}); comp["source_plan"]["clauses"].append({"char_start":22,"char_end":30})
    elif mutation=="missing_boundaries": del comp["source_plan"]
    elif mutation=="unsupported_accepted": refs[0].update(supported=False,clauses=[])
    else: generated["rows"][0]["composition"]=None
    measured=runner.score_document_tuning(generated,refs)
    assert measured["count"]==1 and measured["exact"]==0
    if mutation=="unsupported_accepted": assert measured["unsupported_accepted"]==1 and measured["decision_exact"]==0


def test_document_metric_rejects_source_corruption_and_dropped_rows():
    generated,refs=doc_fixture()
    generated["rows"][0]["source_sha256"]="wrong"
    with pytest.raises(ValueError,match="source"):
        runner.score_document_tuning(generated,refs)
    with pytest.raises(ValueError,match="denominator"):
        runner.score_document_tuning({"rows":[]},refs)


def bank():
    parents=[{"name":f"parent-{seed}","arm":"parent","seed":seed,"checkpoint":{"sha256":str(seed)},
        "decoder_kind":"parent","selection":"unchanged_parent","enabled":False} for seed in runner.SEEDS]
    heads=[]
    for arm,settings in runner.historical.ARMS.items():
        for seed in runner.SEEDS:
            stages=[{**stage(steps,temporal=steps//10),"checkpoint":{"sha256":f"{arm}-{seed}-{steps}"}} for steps in (400,800)]
            heads.append({"name":f"{arm}-{seed}","arm":arm,"seed":seed,**settings,
                "requested_enabled":settings["enabled"],"parent":{"sha256":str(seed)},"parent_tuning_exact":{"earlier":96},
                "stages":stages,"checkpoint":stages[-1]["checkpoint"],"selected_steps":800,
                "decoder_kind":"mixed","selection":"candidate"})
    return {"schema":runner.historical.SCHEMA,"all_training_selection_and_generation_complete":True,
        "challenge_targets_opened":False,"regression_targets_opened":False,"models":heads+parents},heads


def test_historical_bank_rejoins_all_twelve_trials_and_three_parents():
    trials,parents=runner.historical_inventory(*bank())
    assert len(trials)==12 and len(parents)==3


@pytest.mark.parametrize("mutation",["selected400","wrong_parent","wrong_curriculum","dropped_stage","wrong_checkpoint"])
def test_historical_bank_rejects_attribution_or_selection_drift(mutation):
    frozen,heads=bank(); row=heads[0]
    if mutation=="selected400": row["selected_steps"]=400
    elif mutation=="wrong_parent": row["parent"]={"sha256":"wrong"}
    elif mutation=="wrong_curriculum": row["curriculum"]="other"
    elif mutation=="dropped_stage": row["stages"].pop()
    else: row["checkpoint"]={"sha256":"wrong"}
    with pytest.raises(ValueError): runner.historical_inventory(frozen,heads)


def test_baseline_fallback_keeps_its_architecture_checkpoint_and_curriculum():
    _,parents=runner.historical_inventory(*bank())
    trials=[]
    for architecture in runner.ARCHITECTURES:
        for seed in runner.SEEDS:
            trials.append({"architecture":architecture,"seed":seed,"parent":parents[seed]["checkpoint"],
                "prior_checkpoint":{"sha256":f"temporal-{architecture}-{seed}"},"checkpoint":{"sha256":f"baseline-{architecture}-{seed}"},
                "document_reference_checkpoint":{"sha256":f"baseline-{architecture}-{seed}"},"selected_steps":800,
                "selection":"baseline_fallback","selected_curriculum":"baseline","selection_record":{"sha256":"record"},
                "temporal_source_trial":"temporal-trial","baseline_source_trial":"baseline-trial"})
    models=runner.model_inventory(trials,parents)
    assert len(models)==15 and len({row["name"] for row in models})==15
    fallback=[row for row in models if row["selection"]=="baseline_fallback"]
    assert len(fallback)==6 and all(row["decoder_kind"]=="mixed" and row["curriculum"]=="baseline" for row in fallback)
    assert all(row["enabled"] is (row["architecture"]=="grounding") for row in fallback)
    assert all(row["checkpoint"]==row["document_reference_checkpoint"] and row["new_optimizer_steps"]==0 for row in fallback)


@pytest.fixture
def inputs(tmp_path,monkeypatch):
    from scripts.ops import legal_ir as package
    corpus=SimpleNamespace(load_selection_inputs=None)
    monkeypatch.setattr(package,"prepare_legal_construction_retention_corpus",corpus,raising=False)
    def put(name,value):
        path=tmp_path/name; path.write_text(json.dumps(value)); return runner.ref(path)
    def sealed(name): return {"path":str(tmp_path/name),"sha256":"a"*64,"bytes":100}
    def single(prefix,count): return [{"id":f"{prefix}-{i}","source_text":f"{prefix} source {i}"} for i in range(count)]
    def documents(prefix):
        return [{"candidate_id":f"{prefix}-{i}","source_text":f"{prefix} source {i}",
            "source_sha256":runner.boundary.text_sha(f"{prefix} source {i}")} for i in range(96)]
    tuning={name:single("tune-"+name,count) for name,count in (("earlier",96),("prior_new",96),("temporal",120))}
    doctune=[{**row,"supported":i<72,"clauses":[]} for i,row in enumerate(documents("doc-tune"))]
    fresh=single("fresh",180); freshdocs=documents("fresh-doc")
    manifest={"artifacts":{"challenge_targets":sealed("fresh-targets.json"),"anchor_targets":sealed("anchor-targets.json"),
        "document_challenge_targets":sealed("fresh-doc-targets.json")}}
    frozen,heads=bank()
    frozen.update(heads=put("heads.json",heads),plan=put("prior-plan.json",{"producer_pins":{}}),
        sources=put("prior-sources.json",{"tuning_"+name:runner.source_rows(rows) for name,rows in tuning.items()}))
    exposed_doc_sources=put("exposed-docs.json",documents("exposed-doc"))
    document_plan=put("doc-plan.json",{"producer_pins":{},"source_documents":exposed_doc_sources,"boundary_checkpoint":sealed("boundary.json")})
    old_documents=put("prior-documents.json",{"all_models_completed":True,"reference_targets_opened":False,"plan":document_plan})
    config={"schema":"legal-construction-retention-run-config/v1","corpus_manifest":put("manifest.json",manifest),
        "prior_generation":put("prior-generation.json",frozen),"prior_document_generation":old_documents,
        "exposed_document_sources":exposed_doc_sources,"exposed_document_targets":sealed("exposed-doc-targets.json"),
        "study_design":put("design.json",{}),"producer_files":[]}
    for name,count in (("earlier",192),("exposed",150),("mixed",144),("temporal",180)):
        rows=single("reg-"+name,count)
        config[name+"_regression_sources"]=put(name+"-sources.json",{"challenge":rows} if name=="earlier" else rows)
        config[name+"_regression_targets"]=sealed(name+"-targets.json")
    path=tmp_path/"config.json"; path.write_text(json.dumps(config))
    loaded={"manifest":manifest,"tuning":tuning,"document_tuning":doctune,"fresh_sources":fresh,
        "anchor_sources":single("anchor",30),"fresh_document_sources":freshdocs}
    corpus.load_selection_inputs=lambda _:loaded
    return path,loaded


def test_loader_reads_only_admitted_tuning_and_source_panels_with_all_test_targets_missing(inputs):
    path,_=inputs
    loaded=runner.load_config(path)
    assert [len(loaded["sources"][name]) for name in runner.NORMAL_PANELS]==[96,96,120,180,30,192,150,144,180]
    assert [len(loaded["document_sources"][name]) for name in runner.DOCUMENT_PANELS]==[96,96,96]
    assert len(loaded["trials"])==12 and len(loaded["parents"])==3


def test_loader_rejects_document_source_hash_corruption(inputs):
    path,loaded=inputs
    loaded["fresh_document_sources"][0]["source_sha256"]="wrong"
    with pytest.raises(ValueError,match="source hash"):
        runner.load_config(path)


def test_loader_rejects_overlap_with_single_tuning(inputs):
    path,loaded=inputs
    loaded["fresh_sources"][0]["source_text"]=loaded["tuning"]["earlier"][0]["source_text"]
    with pytest.raises(ValueError,match="overlap"):
        runner.load_config(path)


def test_loader_rejects_fresh_document_target_fields(inputs):
    path,loaded=inputs
    loaded["fresh_document_sources"][0]["clauses"]=[]
    with pytest.raises(ValueError,match="source-only"):
        runner.load_config(path)
