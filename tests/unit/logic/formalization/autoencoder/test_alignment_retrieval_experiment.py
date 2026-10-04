"""No-gold selection boundaries, artifact integrity, and integration controls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_retrieval_experiment as subject,
)

ROOT = Path(__file__).resolve().parents[5]
CONFIG = ROOT/"configs/autoencoders/alignment_retrieval_development_v1.json"


@pytest.mark.parametrize("field,value", [("policies",["cosine"]),("top_k",True),("shortlist",1),
    ("diversity_lambda",float("nan")),("ridge_regularization",0),("include_formal_geometries",1),("max_seconds",301)])
def test_closed_controls_reject_relabeling_and_invalid_budgets(tmp_path,field,value):
    config = json.loads(CONFIG.read_text())
    config[field] = value
    path = tmp_path/"config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        subject.load_retrieval_config(path)


def test_config_exact_bytes_bound_and_unknown_fields_rejected(tmp_path):
    settings,binding = subject.load_retrieval_config(CONFIG)
    assert binding["sha256"] == hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    settings["query_gold"] = "forbidden"
    path=tmp_path/"config.json"
    path.write_text(json.dumps(settings))
    with pytest.raises(ValueError,match="closed"):
        subject.load_retrieval_config(path)


def test_configuration_binding_uses_the_same_read_as_parsed_settings(tmp_path,monkeypatch):
    path=tmp_path/"config.json"
    raw=CONFIG.read_bytes()
    original_read=subject._bounded_bytes
    def racing_read(source,limit):
        result=original_read(source,limit)
        source.write_text("changed after reading")
        return result
    path.write_bytes(raw)
    monkeypatch.setattr(subject,"_bounded_bytes",racing_read)
    settings,binding=subject.load_retrieval_config(path)
    assert settings["top_k"]==5
    assert binding["sha256"]==hashlib.sha256(raw).hexdigest()
    assert binding["sha256"]!=hashlib.sha256(path.read_bytes()).hexdigest()


def test_artifact_digest_and_parse_share_one_read(tmp_path,monkeypatch):
    path=tmp_path/"report.json"
    raw=b'{"executed":"pinned"}'
    path.write_bytes(raw)
    original_read=subject._bounded_bytes
    def racing_read(source,limit):
        result=original_read(source,limit)
        source.write_text('{"executed":"changed"}')
        return result
    monkeypatch.setattr(subject,"_bounded_bytes",racing_read)
    _,payload=subject._read_bound_json(tmp_path,{"path":"report.json","sha256":hashlib.sha256(raw).hexdigest()})
    assert payload=={"executed":"pinned"}


def test_external_and_modified_artifact_paths_fail_closed(tmp_path):
    folder=tmp_path/"workspace"
    folder.mkdir()
    file=tmp_path/"outside.json"
    file.write_text("{}")
    binding={"path":str(file),"sha256":hashlib.sha256(file.read_bytes()).hexdigest()}
    with pytest.raises(ValueError,match="inside workspace"):
        subject._bound_artifact(folder,binding)
    binding={"path":"../outside.json","sha256":binding["sha256"]}
    with pytest.raises(ValueError,match="inside the workspace"):
        subject._bound_artifact(folder,binding)
    file=folder/"inside.json"
    file.write_text("{}")
    with pytest.raises(ValueError,match="digest"):
        subject._bound_artifact(folder,{"path":"inside.json","sha256":"0"*64})


def test_repository_and_existing_output_rejected_before_numerics(tmp_path):
    with pytest.raises(ValueError,match="executing study"):
        subject.run_retrieval_experiment(CONFIG,tmp_path,tmp_path,tmp_path/"run")
    with pytest.raises(ValueError,match="fresh output"):
        subject.run_retrieval_experiment(CONFIG,ROOT,tmp_path,tmp_path)


def test_preloaded_module_origin_must_match_manifest(tmp_path,monkeypatch):
    relative="ipfs_datasets_py/logic/formalization/autoencoder/alignment_retrieval.py"
    monkeypatch.setitem(subject.sys.modules,relative[:-3].replace("/","."),SimpleNamespace(__file__=str(tmp_path/"other.py")))
    with pytest.raises(ValueError,match="another tree"):
        subject._verify_origins(ROOT,[{"path":relative}])


def test_ranking_api_forwards_only_source_vectors_and_predicted_facets(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_retrieval

    calls=[]
    def select(identity,query,candidates,**kwargs):
        assert kwargs["predicted_facets"] is None or kwargs["predicted_facets"] == {"inferred":True}
        assert "query_target" not in kwargs
        calls.append(kwargs["policy"])
        return {"id":identity,"retrieved":[{"candidate_id":"candidate","cosine_similarity":1.,"selection_score":1.}],
                "trace":{"shortlist":[{"candidate_id":"candidate","cosine_similarity":1.}],"query_target_consumed":False}}
    monkeypatch.setattr(alignment_retrieval,"rerank_candidates",select)
    monkeypatch.setattr(alignment_retrieval,"prepare_training_candidates",lambda candidates,**kwargs:candidates)
    rankings,shortlist=subject.rank_retrieval_geometry(["dev"],[[1.]+[0.]*383],
        [{"candidate_id":"candidate"}],[[1.]+[0.]*383],[{"inferred":True}],
        {"policies":["cosine","mmr","facet_cover"],"top_k":1,"shortlist":1,"diversity_lambda":.7})
    assert calls == ["cosine","mmr","facet_cover"] and set(rankings)==set(calls)
    assert shortlist[0]["retrieved"][0]["candidate_id"] == "candidate"
    assert "shortlist_sha256" in rankings["cosine"][0]["selection_trace"]


def test_full_pipeline_dev_target_mutation_preserves_probe_predictions_and_all_rankings(tmp_path):
    pytest.importorskip("torch")
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_experiment import (
        run_projection_experiment,
    )

    def target(actor,action,modality="O"):
        return {"rules":[{"actor":actor,"action":action,"modality":modality,"object":"certificate",
                          "conditions":[],"exceptions":[],"temporal":[]}]}
    def binding(path):
        return {"path":str(path.relative_to(tmp_path)),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
    def row(identity,actor,action,vector,split):
        text=f"The {actor} must {action} the certificate."
        return {"id":identity,"group_id":"group-"+identity,"split":split,"source_text":text,
                "source_sha256":hashlib.sha256(text.encode()).hexdigest(),"embedding":vector,
                "embedding_sha256":subject._digest(vector),"target":target(actor,action)}
    base=json.loads((ROOT/"configs/autoencoders/alignment_study_development_v1.json").read_text())
    projection=json.loads((ROOT/"configs/autoencoders/alignment_projection_development_v1.json").read_text())
    projection.update(shared_dimensions=[384],seeds=[0],negative_weights=[1],steps=2)
    settings=json.loads(CONFIG.read_text())
    settings.update(top_k=2,shortlist=2)
    (tmp_path/"protocol.md").write_text("protected")
    (tmp_path/"provenance.json").write_text("{}")
    base["protected_protocols"]=[binding(tmp_path/"protocol.md")]
    base["corpus"]["provenance"]=[binding(tmp_path/"provenance.json")]
    train=[row("a","clerk","retain",[1.,0.]+[0.]*382,"train"),
           row("b","officer","issue",[0.,1.]+[0.]*382,"train")]
    dev=[row("dev","executor","register",[.8,.6]+[0.]*382,"validation")]
    (tmp_path/"train.json").write_text(json.dumps({"rows":train}))
    base["corpus"]["train"]=binding(tmp_path/"train.json")
    def execute(identity):
        (tmp_path/"validation.json").write_text(json.dumps({"rows":dev}))
        base["corpus"]["development"]=binding(tmp_path/"validation.json")
        (tmp_path/"base.json").write_text(json.dumps(base))
        projection["study_config"]=binding(tmp_path/"base.json")
        (tmp_path/"projection.json").write_text(json.dumps(projection))
        run_projection_experiment(tmp_path/"projection.json",ROOT,tmp_path,tmp_path/(identity+"-projection"))
        settings["projection_report"]=binding(tmp_path/(identity+"-projection")/"report.json")
        (tmp_path/"retrieval.json").write_text(json.dumps(settings))
        return subject.run_retrieval_experiment(tmp_path/"retrieval.json",ROOT,tmp_path,tmp_path/(identity+"-retrieval"))
    first=execute("first")
    dev[0]["target"]=target("executor","register","F")
    second=execute("second")
    assert first["probe"]["sha256"]==second["probe"]["sha256"]
    assert first["predictions"]["sha256"]==second["predictions"]["sha256"]
    for a,b in zip(first["geometries"],second["geometries"],strict=True):
        assert a["id"]==b["id"]
        for policy in settings["policies"]:
            assert [r["retrieved"] for r in a["policies"][policy]["rows"]]==[r["retrieved"] for r in b["policies"][policy]["rows"]]
            assert [r["selection_trace"] for r in a["policies"][policy]["rows"]]==[r["selection_trace"] for r in b["policies"][policy]["rows"]]
    assert first["primary_fidelity"]["status"]=="unavailable" and not first["qualified"]
    admission=json.loads(Path(first["review_admission"]["path"]).read_text())
    assert admission["status"]=="pending"
