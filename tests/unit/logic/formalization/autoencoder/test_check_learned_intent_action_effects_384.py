"""The smoke harness exposes original instructions, never stored targets/vectors."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[5] / "scripts/ops/autoencoder/check_learned_intent_action_effects_384.py"
spec = importlib.util.spec_from_file_location("learned_intent_action_smoke", SCRIPT)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def test_target_and_stored_embedding_changes_cannot_affect_source_only_inference_view(tmp_path):
    rows = [dict(id="row", split="test", source_text="  the agent may read the report.  ",
        target={"claimed_result": "perfect"}, embedding=[1.0] * 384, group_id="held-out-combination")]
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps(rows))
    original = subject.source_instructions(path)
    rows[0].update(target={"replace_source_with": "another instruction", "proof_authority": True},
        embedding="deliberately invalid precomputed vector", group_id="changed-unused-metadata")
    path.write_text(json.dumps(rows))
    assert subject.source_instructions(path) == original
    assert original == [dict(id="row", split="test", instruction=rows[0]["source_text"],
        source_sha256=subject.sha(rows[0]["source_text"].encode()))]


@pytest.mark.parametrize("change", ["duplicate_id", "training_row", "missing_source", "empty_source"])
def test_incomplete_or_ambiguous_source_populations_are_not_silently_filtered(tmp_path, change):
    rows = [dict(id="row", split="test", source_text="exact source")]
    if change == "duplicate_id": rows *= 2
    elif change == "training_row": rows[0]["split"] = "train"
    elif change == "missing_source": rows[0].pop("source_text")
    else: rows[0]["source_text"] = "  "
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError): subject.source_instructions(path)
