"""Numerical inverse recovery preserves output tokens and source meaning gates."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import rich_inverse_recovery as recovery
from ipfs_datasets_py.logic.intent_ir.formalize import rich_inverse_codec as codec
from ipfs_datasets_py.logic.intent_ir.formalize import rich_grammar as grammar
from ipfs_datasets_py.logic.intent_ir.formalize import rich_decoder as direct
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paired_copy import tokenize

SOURCE = "Create the .cfg local capsule beside compressed disk artifacts."


@pytest.fixture(scope="module")
def actual():
    import torch
    torch.set_num_threads(1)
    default = Path(__file__).resolve().parents[7] / "artifacts/ir-training-coverage-20261002/intent-01/source-training-02/descriptor.json"
    path = Path(os.environ.get("INTENT_SOURCE_FORM_CHECKPOINT", str(default)))
    if not path.exists():
        pytest.skip("set INTENT_SOURCE_FORM_CHECKPOINT to the explicit source-form pilot child")
    descriptor = json.loads(path.read_bytes())
    report = recovery.prepare_inverse_recovered_rich_intent(SOURCE, descriptor)
    return descriptor, report


def test_actual_neural_inverse_is_recovered_without_new_tokens_or_expected_slots(actual):
    descriptor, report = actual
    assert report["schema"] == recovery.SCHEMA
    assert report["status"] == "source_supported_token_faithful_inverse"
    assert report["direct_report"]["rich_ir"] is None
    assert report["learned"]["ast"] == grammar.parse_instruction(SOURCE)
    assert report["learned"]["normalized_text"] == "unspecified intends to create .cfg local capsule beside compressed disk artifacts."
    assert tokenize(report["learned"]["normalized_text"]) == tokenize(report["learned"]["decoder"]["generated_text"])
    weights = direct.load_rich_intent_checkpoint(descriptor)["backend"]["training"]["final_state_sha256"]
    assert report["learned"]["encoder"]["checkpoint_weights_sha256"] == weights
    assert report["learned"]["decoder"]["checkpoint_weights_sha256"] == weights
    assert report["counts"]["encoder_executions"] > 0 and report["counts"]["decoder_executions"] > 0
    assert report["additional_neural_executions"] == 0
    assert not report["codec_reads_source_or_expected_ast"]
    assert not report["source_semantics_verified"] and not report["proof_authority"]


def test_actual_report_replays_numerically_and_rejects_resigned_slot_tampering(actual):
    descriptor, report = actual
    assert recovery.validate_inverse_recovered_rich_intent(report, instruction=SOURCE, checkpoint_descriptor=descriptor) == report
    forged = deepcopy(report)
    forged["rich_ir"]["ast"]["object"] = "different capsule"
    forged["report_sha256"] = direct.sha(direct.wire({k: v for k, v in forged.items() if k != "report_sha256"}))
    with pytest.raises(ValueError, match="numerical replay"):
        recovery.validate_inverse_recovered_rich_intent(forged, instruction=SOURCE, checkpoint_descriptor=descriptor)


def test_codec_cannot_supply_missing_tokens_even_if_it_claims_equivalence(actual, monkeypatch):
    descriptor, report = actual
    baseline = deepcopy(report["direct_report"])
    monkeypatch.setattr(direct, "prepare_rich_intent_instruction", lambda *a, **k: deepcopy(baseline))
    def invented(generated_text):
        source = "unspecified intends to create invented capsule."
        return {"status": "candidate", "text": source, "ast": grammar.parse_instruction(source), "token_equivalent": True}
    monkeypatch.setattr(codec, "recover_generated_inverse", invented)
    result = recovery.prepare_inverse_recovered_rich_intent(SOURCE, descriptor)
    assert result["rich_ir"] is None and not result["source_agreement"]


def test_wrong_generated_object_cannot_be_repaired_using_source_slots(actual, monkeypatch):
    descriptor, report = actual
    baseline = deepcopy(report["direct_report"])
    wrong = deepcopy(report["learned"]["decoder"])
    wrong["generated_text"] = wrong["generated_text"].replace("capsule", "notebook")
    wrong["tokens"] = tokenize(wrong["generated_text"])
    baseline["decoder_searches"] = [{"rows": [wrong]}]
    monkeypatch.setattr(direct, "prepare_rich_intent_instruction", lambda *a, **k: deepcopy(baseline))
    result = recovery.prepare_inverse_recovered_rich_intent(SOURCE, descriptor)
    assert result["rich_ir"] is None and not result["source_agreement"]


def test_no_checkpoint_or_unsupported_source_stays_fail_open():
    for source in ("Create the local archive.", "Create every archive."):
        report = recovery.prepare_inverse_recovered_rich_intent(source)
        assert report["rich_ir"] is None
        assert report["counts"] == {"encoder_executions": 0, "decoder_executions": 0}


def test_external_resigned_base_reports_are_not_an_accepted_interface():
    with pytest.raises(TypeError):
        recovery.prepare_inverse_recovered_rich_intent(SOURCE, base_report={"forged": True})
