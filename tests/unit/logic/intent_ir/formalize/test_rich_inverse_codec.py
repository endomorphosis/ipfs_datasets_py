"""Source-free inverse rendering contracts; no neural execution is simulated."""
import hashlib
import inspect
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import rich_grammar as grammar
from ipfs_datasets_py.logic.intent_ir.formalize import rich_inverse_codec as api
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paired_text import tokenize


@pytest.mark.parametrize("source", [
    "agent must inspect cache.",
    "unspecified intends to create .cfg local capsule.",
    "operator should inspect /Src/Cache.py.",
    "agent must not delete ../Cache.py.",
    "agent may inspect ./README.md.",
    "agent intends to inspect API:Result_v2.",
    "agent must inspect `Src/Cache-v2.py`.",
    "operator must run `python script.py`.",
    "agent must inspect .cache and reviewer may approve /Report.md.",
    "agent must inspect .cache or reviewer may approve `Report.md`.",
    "agent must inspect .cache then reviewer should archive ../Report.md.",
    "if .cache is Empty, agent must create .cfg.",
    "if Src/Cache.py is not Empty_State, agent must not delete .cfg.",
])
def test_canonical_slots_and_scopes_round_trip_from_generated_tokens_alone(source):
    expected = grammar.parse_instruction(source, normalized_inverse=True)
    generated = " ".join(tokenize(grammar.ast_to_text(expected)))
    report = api.recover_generated_inverse(generated)
    assert report["status"] == "candidate", report
    assert report["ast"] == expected
    assert tokenize(report["text"]) == tokenize(generated)
    assert report["token_equivalent"] and report["candidate_count"] == 1
    assert grammar.parse_instruction(report["text"], normalized_inverse=True) == expected
    assert report["method"] == api.METHOD
    assert not report["source_supplied"] and not report["expected_ast_supplied"]
    assert not report["proof_authority"] and not report["source_semantics_verified"]
    assert report["neural_forward_count"] == 0


def test_leading_extension_never_fuses_into_generated_action():
    generated = "unspecified intends to create . cfg local capsule ."
    assert grammar._unspace(generated) == "unspecified intends to create.cfg local capsule."
    recovered = api.recover_generated_inverse(generated)
    assert recovered["ast"]["action"] == "create"
    assert recovered["ast"]["object"] == ".cfg local capsule"
    assert recovered["text"] == "unspecified intends to create .cfg local capsule."


def test_missing_sentence_period_is_not_invented():
    generated = "agent must inspect . cfg"
    recovered = api.recover_generated_inverse(generated)
    assert recovered["status"] == "candidate"
    assert recovered["text"] == "agent must inspect .cfg"
    assert tokenize(recovered["text"]) == tokenize(generated)


@pytest.mark.parametrize("generated", [
    "agent must sign - off report .",
    "agent must inspect cache and reviewer may sign - off report .",
    "if cache is empty , agent must sign - off report .",
])
def test_competing_action_slot_boundaries_are_refused_without_source_disambiguation(generated):
    report = api.recover_generated_inverse(generated)
    assert report["status"] == "ambiguous"
    assert report["candidate_count"] > 1
    assert report["ast"] is None and report["text"] is None
    assert not report["token_equivalent"]
    assert "multiple_generated_grammar_interpretations" in report["frontier"]


@pytest.mark.parametrize("generated", [
    "", None, 4,
    "agent must inspect cache\n",
    "agent must inspect caché .",
    "<actor> agent <action> inspect <object> cache <modality> required",
    "inspect cache .",
    "agent must inspect this .",
    "agent must inspect cache and approve report .",
    "agent must inspect cache ; reviewer may approve report .",
    "agent must inspect cache . reviewer may approve report .",
    "if cache is empty , if report is ready , agent must inspect cache .",
    "agent must inspect cache and reviewer may approve report and operator must archive log .",
    "operator must run 'python script.py' .",
    'operator must run "python script.py" .',
    "operator must run `python script.py .",
])
def test_scope_punctuation_and_input_frontiers_never_return_partial_candidate(generated):
    report = api.recover_generated_inverse(generated)
    assert report["status"] == "unsupported"
    assert report["ast"] is None and report["text"] is None
    assert not report["token_equivalent"] and report["frontier"]


def test_tokenizer_spaces_are_not_claimed_to_preserve_command_semantics():
    report = api.recover_generated_inverse("operator must run ` python - m pytest ` .")
    assert report["status"] == "candidate"
    assert report["ast"]["object"] == "`python-m pytest`"
    assert "tokenizer_whitespace_is_lossy" in report["limitations"]
    assert "learned_forward_AST_and_complete_source_agreement_required" in report["limitations"]
    assert report["ast"] != grammar.parse_instruction("operator must run `python -m pytest`.", normalized_inverse=True)


def test_no_source_or_expected_slots_are_accepted_by_public_api():
    assert tuple(inspect.signature(api.recover_generated_inverse).parameters) == ("generated_text",)
    with pytest.raises(TypeError):
        api.recover_generated_inverse("agent must inspect cache .", source="agent must inspect cache.")
    with pytest.raises(TypeError):
        api.recover_generated_inverse("agent must inspect cache .", expected_ast={})


def test_all_pins_match_real_source_and_token_digest_ignores_only_spacing():
    import importlib
    a = api.recover_generated_inverse("agent must inspect . cfg .")
    b = api.recover_generated_inverse("agent  must inspect .cfg.")
    assert a["generated_tokens_sha256"] == b["generated_tokens_sha256"]
    assert a["generated_text_sha256"] != b["generated_text_sha256"]
    assert a["ast"] == b["ast"]
    for name, digest in a["producer_pins"].items():
        assert digest == hashlib.sha256(Path(importlib.import_module(name).__file__).read_bytes()).hexdigest()


def test_resource_bounds_fail_closed_without_any_partial_output(monkeypatch):
    report = api.recover_generated_inverse("x " * 161)
    assert report["status"] == "unsupported"
    assert report["frontier"] == ["generated_token_bound_exceeded"]
    monkeypatch.setattr(api, "MAX_PARTITIONS", 1)
    report = api.recover_generated_inverse("agent must inspect cache .")
    assert report["status"] == "unsupported"
    assert report["ast"] is None and report["text"] is None
    assert report["frontier"] == ["generated_grammar_partition_bound_exceeded"]
