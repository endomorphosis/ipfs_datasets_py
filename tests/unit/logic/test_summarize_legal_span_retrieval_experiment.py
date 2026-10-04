"""Independent analysis rejects broken bindings and counts paired outcomes."""
import copy
import importlib.util
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("span_analysis", ROOT / "scripts/ops/legal_ir/summarize_legal_span_retrieval_experiment.py")
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def sample():
    text = "Office shall retain records unless fire."
    rule = {"modality": "O", "actor": "Office", "action": "retain", "object": "records",
            "conditions": [], "exceptions": ["fire"], "temporal": []}
    ir = {"rules": [rule]}
    tokens = [{"text": match.group(), "start": match.start(), "end": match.end()}
              for match in re.finditer(r"\w+|[^\w\s]", text)]
    facets = {}
    for field in analysis.SPAN_FIELDS:
        value = rule[field]
        atom = value[0] if field in analysis.QUALIFIERS and value else value if field not in analysis.QUALIFIERS else None
        info = {"present": bool(atom), "token_start": None, "token_end_inclusive": None,
                "char_start": None, "char_end": None, "text": None}
        if atom:
            index = next(i for i, token in enumerate(tokens) if token["text"] == atom)
            info.update(token_start=index, token_end_inclusive=index, char_start=tokens[index]["start"],
                        char_end=tokens[index]["end"], text=atom)
        facets[field] = info
    source = {"id": "example", "source_text": text, "source_sha256": analysis.hashlib.sha256(text.encode()).hexdigest(),
              "family_group": "family-a", "canonical_ir": ir}
    prediction = {"source_sha256": source["source_sha256"], "target_access": False, "teacher_forcing": False,
                  "status": "decoded", "canonical_ir": ir, "formula_text": json.dumps(ir),
                  "span_diagnostics": {"tokens": tokens, "facets": facets},
                  "formal_outputs": [{"family": "deontic", "payload": rule}]}
    return source, prediction


def test_copy_audit_verifies_exact_offsets_and_full_formal_payload():
    source, prediction = sample()
    assert analysis.assert_source_copy(prediction, source) == 4
    prediction["span_diagnostics"]["facets"]["exceptions"]["char_start"] += 1
    with pytest.raises(ValueError, match="exact source span"):
        analysis.assert_source_copy(prediction, source)


def test_copy_audit_rejects_missing_qualifier_in_formal_payload():
    source, prediction = sample()
    prediction["formal_outputs"] = [{"family": "deontic", "payload": {"modality": "O"}}]
    with pytest.raises(ValueError, match="lost canonical fields"):
        analysis.assert_source_copy(prediction, source)


def test_unseen_facets_and_abstentions_have_explicit_denominators():
    source, prediction = sample()
    known = {field: set() for field in analysis.FIELDS}
    result = analysis.evaluate([prediction], [source], {source["id"]: source["canonical_ir"]}, known)
    assert result["exact"] == 1
    assert result["unseen_target_facet_accuracy"]["exceptions"] == {"support": 1, "correct": 1, "decoded": 1}
    assert result["unseen_target_facet_accuracy"]["conditions"] == {}
    abstained = {**prediction, "status": "abstained", "canonical_ir": None, "formal_outputs": []}
    result = analysis.evaluate([abstained], [source], {source["id"]: source["canonical_ir"]}, known)
    assert result["exact"] == 0 and result["abstained"] == 1
    assert result["qualifier_errors"]["exceptions"]["abstained_with_gold_present"] == 1
    assert not result["qualifier_errors"]["exceptions"].get("dropped", 0)


def test_paired_counts_preserve_family_clusters():
    def panel(bits):
        return {"exact": sum(bits), "rows": [{"id": str(i), "family_group": "family-a" if i < 2 else "family-b", "exact": flag}
                                             for i, flag in enumerate(bits)]}
    result = analysis.paired(panel([True, False, True, False]), panel([False, True, True, False]))
    assert result["exact_delta"] == 0
    assert result["candidate_only_correct"] == result["baseline_only_correct"] == 1
    assert result["both_correct"] == result["neither_correct"] == 1
    assert result["family_exact_deltas"] == {"family-a": 0, "family-b": 0}
    assert not result["independent_example_assumption"]


def test_unfinished_run_cannot_access_targets(tmp_path):
    with pytest.raises(ValueError, match="completion summary required"):
        analysis.summarize(tmp_path, tmp_path / "analysis.json")


@pytest.fixture
def completed_run(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
        return {"path": str(path), "sha256": analysis.sha(path)}
    arms = {"source_only": [False, "raw"], "raw_retrieval": [True, "raw"],
            "joint_retrieval": [True, "joint"], "random_retrieval": [True, "random"]}
    plan = {"arms": arms, "seeds": [1, 2, 3], "decoder_steps": 4, "producer_pins": {},
            "interventions": ["zero_context", "rotated_context", "disabled_context"]}
    plan_ref = write("plan.json", plan)
    heads, frozen = [], {}
    for seed in plan["seeds"]:
        for arm, (enabled, mode) in arms.items():
            name = f"{arm}-{seed}"
            checkpoint = write(name + "/checkpoint.json", {"progress": {"optimizer_steps": 4}})
            heads.append({"name": name, "arm": arm, "seed": seed, "latent_enabled": enabled,
                          "optimizer_steps": 4, "checkpoint": checkpoint, "initial_model_sha256": "same"})
            panels = ["challenge", "tuning", "oov"]
            if enabled:
                panels += ["challenge_" + item for item in plan["interventions"]]
            frozen[name] = {}
            for panel in panels:
                payload = {"generation_inputs_contained_references": False, "rows": [],
                           "reports": [{"target_access": False, "teacher_forcing": False,
                                        "checkpoint_sha256": checkpoint["sha256"], "rows": []}]}
                path = analysis.generation_path(tmp_path, name, panel)
                write(str(path.relative_to(tmp_path)), payload)
                frozen[name][panel] = analysis.digest(payload)
    summary = {"plan_sha256": plan_ref["sha256"], "challenge_targets_read_after_all_training_and_generation": True,
               "frozen_heads": write("frozen-heads.json", heads), "generation_frozen": write("generation-frozen.json", frozen),
               "runs": [{"name": item["name"]} for item in heads],
               "retriever_checkpoint": write("retriever-checkpoint.json", {"trained": True})}
    write("summary.json", summary)
    return tmp_path


def test_completion_gate_checks_every_declared_generation(completed_run):
    _, _, heads, generated = analysis.verify_completion(completed_run)
    assert len(heads) == len(generated) == 12
    assert sum(len(panels) for panels in generated.values()) == 63
    path = completed_run / "random_retrieval-3/challenge-disabled_context-generation.json"
    payload = json.loads(path.read_text())
    payload["generation_inputs_contained_references"] = True
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="generation changed"):
        analysis.verify_completion(completed_run)


def test_completion_gate_rejects_tampered_checkpoint(completed_run):
    path = completed_run / "joint_retrieval-2/checkpoint.json"
    path.write_text('{}')
    with pytest.raises(ValueError, match="artifact hash differs"):
        analysis.verify_completion(completed_run)
