"""Pure runtime-loop simulations, separate from genuine checkpoint qualification.

The outer checkpoint/head/runtime/model interfaces below are explicitly fake.
They allocate no Torch/GRU/model tensors and open no checkpoint/vector/report
payloads. Original source-owner guards and real grammar/selector APIs remain
active. Two terminal controls label a scripted selector result as having NO
policy proof; they test loop accounting, not the selector's proof soundness.
The fictional EOS score script is test input, never production/model evidence.
"""
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_branch_selection_v1 as selector
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_completion_budget_v1 as old_budget
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_persistent_runtime_v3 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_selection_v1 as selection
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens

_HELPER_PATH = Path(__file__).absolute().with_name("test_legal_compact_content_completion_budget_v1.py")
_HELPER_SHA = "5f31d2c05057167a1b3aac624c9f87fc36ebea6987a00d96af159279679747ab"
assert hashlib.sha256(_HELPER_PATH.read_bytes()).hexdigest() == _HELPER_SHA
from tests.unit.logic.autoformal import test_legal_compact_content_completion_budget_v1 as authored
assert Path(authored.__file__).absolute() == _HELPER_PATH


def wire(value, maximum=64*1024**2):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode()
    assert len(raw) <= maximum
    return raw


def digest(value, maximum=64*1024**2):
    return hashlib.sha256(wire(value, maximum)).hexdigest()


class FakeTensor:
    def __init__(self, values):
        self.values = deepcopy(values)

    def tolist(self):
        return deepcopy(self.values)

    def clone(self):
        return FakeTensor(self.values)

    def __getitem__(self, index):
        assert type(index) is int
        return deepcopy(self.values[index])


class FakeLogits:
    shape = (1, 1, 537)

    def __init__(self, scores):
        self.scores = list(scores)

    def __getitem__(self, index):
        assert index == (0, -1)
        return FakeTensor(self.scores)


class FakeTorch:
    float32, long = "SIMULATED_FLOAT32", "SIMULATED_LONG"

    @staticmethod
    def get_rng_state():
        return FakeTensor([17, 31])

    @staticmethod
    def equal(a, b):
        return a.tolist() == b.tolist()

    @staticmethod
    def tensor(values, dtype):
        assert dtype in (FakeTorch.float32, FakeTorch.long)
        return FakeTensor(values)

    @staticmethod
    def no_grad():
        return nullcontext()


class FakeHead:
    """Only the explicitly simulated outer numerical contract, not a validator."""
    _wire = staticmethod(wire)
    _digest = staticmethod(digest)
    _fingerprint = staticmethod(digest)

    @staticmethod
    def _copy(value, maximum):
        wire(value, maximum)
        return deepcopy(value)

    @staticmethod
    def _conditioning(value):
        assert value == [0.0]*384
        return list(value)

    @staticmethod
    def _torch(loaded):
        return FakeTorch

    @staticmethod
    def _closing(loaded):
        assert loaded["SIMULATED_OUTER_CONTRACT"] is True

    @staticmethod
    def _finish(failure, fence):
        fence()


class FakeIncrementalModel:
    def __init__(self, ids, counts):
        self.ids, self.counts = ids, counts

    def project(self, vector):
        assert vector.tolist() == [[0.0]*384]
        return "SIMULATED_PROJECTION"

    def start(self, projected):
        assert projected == "SIMULATED_PROJECTION"
        return None, None, FakeTensor([0])

    def next_logits(self, inputs, state):
        ids = inputs.tolist()
        assert len(ids) == len(ids[0]) == 1
        index = len(self.counts["inputs"])
        expected = 1 if index == 0 else self.ids[index]
        assert ids == [[expected]]
        self.counts["inputs"].append(ids[0])
        scores = [-100.0]*537
        scores[self.ids[index+1]] = 100.0
        return FakeLogits(scores), (None, None, FakeTensor([state[2].tolist()[0]+1]))


@pytest.fixture
def simulated_outer(monkeypatch):
    """No genuine checkpoint/model claims can be inferred from this fixture."""
    codec = tokens.build_compact_content_token_codec_v1()
    raw, options = authored.options(authored.context(), codec)
    ids = authored.ids_for(["forall", 0, authored.atom()], codec)
    checkpoint = dict(initial_checkpoint=dict(torch_version="SIMULATED", config={}, codec=codec,
        model_state={}), conditioning_mode="first_step", source_space="SIMULATED_UNVERIFIED_SPACE",
        model_state={}, parameter_order=[], weights_sha256="a"*64,
        codec=codec, codec_sha256=options["expected_codec_sha256"])
    counts = dict(restores=0, inputs=[], original_root_calls=[], checkpoint_seam_calls=0)
    loaded = dict(SIMULATED_OUTER_CONTRACT=True,
                  modules=dict(tokens=tokens, selection=selection))
    adapter = SimpleNamespace(tensor_digest=lambda model: "SIMULATED_PARAMETERS")

    def operation(data, work):
        return work(deepcopy(data), FakeHead, loaded, adapter)

    def checked(value, expected, mode, space, head, original_loaded):
        assert value == checkpoint and expected == digest(checkpoint)
        assert mode == checkpoint["conditioning_mode"] and space == checkpoint["source_space"]
        counts["checkpoint_seam_calls"] += 1
        return deepcopy(value), None

    def restore(value, head, original_loaded, original_adapter, *, with_optimizer):
        assert with_optimizer is False
        assert set(value) == {"initial_checkpoint", "conditioning_mode", "model_state", "parameter_order", "weights_sha256"}
        counts["restores"] += 1
        return FakeIncrementalModel(ids, counts)

    real_root = old_budget.allowed_token_ids

    def root(*args, **kwargs):
        counts["original_root_calls"].append((list(args[0]), kwargs["remaining_new_tokens"]))
        return real_root(*args, **kwargs)

    monkeypatch.setattr(subject.training, "_operation", operation)
    monkeypatch.setattr(subject.training, "_checkpoint", checked)
    monkeypatch.setattr(subject.training, "_restore", restore)
    monkeypatch.setattr(subject.training.base, "_runtime", lambda head, original_loaded: {"SIMULATED_RUNTIME": True})
    monkeypatch.setattr(old_budget, "allowed_token_ids", root)

    def run(*, total=1024, new_tokens=100):
        return subject.generate_from_bos(checkpoint, [0.0]*384, raw,
            expected_checkpoint_sha256=digest(checkpoint),
            expected_context_sha256=options["expected_context_sha256"],
            expected_conditioning_mode=checkpoint["conditioning_mode"],
            expected_source_space=checkpoint["source_space"], max_new_tokens=new_tokens,
            max_prefix_inspections_per_decision=1,
            max_prefix_inspections_per_generation=total)

    yield SimpleNamespace(run=run, counts=counts, ids=ids, raw=raw, options=options)
    assert hashlib.sha256(_HELPER_PATH.read_bytes()).hexdigest() == _HELPER_SHA


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0


def test_simulated_initial_single_inspection_budget_stops_before_restore_or_forward(simulated_outer):
    sim = simulated_outer
    report = sim.run(total=1)
    assert report["status"] == "grammar_budget_exhausted"
    assert report["generated_ids"] == [1] and report["trace"] == []
    assert report["terminal_no_selection_trace"] is None
    assert report["numerical_forward_count"] == report["model_restore_count"] == 0
    assert report["grammar_accounting"]["actual_prefix_inspections"] == 1
    assert report["grammar_accounting"]["remaining_prefix_inspections"] == 0
    assert sim.counts["restores"] == 0 and sim.counts["inputs"] == []
    assert sim.counts["original_root_calls"] == [([1], 100)]
    assert report["final_typed_decode_count"] == 1
    no_authority(report)


def test_simulated_single_output_token_budget_uses_real_empty_root_without_model(simulated_outer):
    sim = simulated_outer
    report = sim.run(new_tokens=1)
    assert report["status"] == "blocked" and report["generated_ids"] == [1]
    assert report["initial_prefix_report"]["allowed_token_ids"] == []
    assert report["numerical_forward_count"] == report["model_restore_count"] == 0
    assert report["grammar_accounting"]["actual_prefix_inspections"] == 1
    assert sim.counts["restores"] == 0 and sim.counts["inputs"] == []
    assert sim.counts["original_root_calls"] == [([1], 1)]
    no_authority(report)


def test_simulated_residual_budget_stops_before_an_extra_forward_and_retains_unqueried_choices(simulated_outer):
    sim = simulated_outer
    report = sim.run(total=2)
    assert report["status"] == "grammar_budget_exhausted"
    assert report["generated_ids"] == sim.ids[:2]
    assert report["numerical_forward_count"] == report["selector_decision_count"] == 1
    assert report["selected_token_decisions"] == report["state_positions_consumed"] == 1
    assert report["terminal_no_selection_decisions"] == 0
    assert report["grammar_accounting"]["actual_prefix_inspections"] == 2
    assert report["grammar_accounting"]["remaining_prefix_inspections"] == 0
    selected = report["trace"][0]["selection_report"]
    assert selected["witness_calls"] == 0 and selected["certificates"] == []
    assert selected["allowed_token_ids"] == selected["baseline_prefix_report"]["allowed_token_ids"]
    assert selected["candidate_results"][0]["disposition"] == "keep_unqueried"
    assert len(sim.counts["inputs"]) == 1 and len(sim.counts["original_root_calls"]) == 2
    no_authority(report)


@pytest.mark.parametrize("selected_before_terminal", [0, 1])
def test_scripted_no_selection_retains_terminal_forward_without_a_fabricated_dead_proof(
        simulated_outer, monkeypatch, selected_before_terminal):
    sim = simulated_outer
    real_select = selector.select_token
    decisions = []

    def scripted(*args, **kwargs):
        report = real_select(*args, **kwargs)
        decisions.append(list(args[1]))
        if len(decisions) <= selected_before_terminal:
            return report
        # Deliberately NOT a real policy result. No DEAD_END certificate is
        # invented; this tests only a terminal response's numerical-loop shape.
        # Pure selector soundness has its separate genuine30-case owner.
        report.update(status="no_selection", reason="SCRIPTED_CONTROL_NO_POLICY_PROOF",
            selected_token_id=None, selected_score=None, allowed_token_ids=[],
            next_prefix_ids=list(args[1]), selection_performed=False, tokens_appended=0,
            scripted_control_not_real_policy_result=True)
        assert report["certificates"] == [] and report["removed_token_ids"] == []
        return report

    monkeypatch.setattr(selector, "select_token", scripted)
    report = sim.run()
    assert report["status"] == "blocked" and report["reason"] == "SCRIPTED_CONTROL_NO_POLICY_PROOF"
    assert report["generated_ids"] == sim.ids[:1+selected_before_terminal]
    assert len(report["trace"]) == report["selected_token_decisions"] == selected_before_terminal
    assert report["terminal_no_selection_decisions"] == 1
    assert report["numerical_forward_count"] == report["selector_decision_count"] == selected_before_terminal+1
    assert report["state_positions_consumed"] == len(report["generated_ids"])
    terminal = report["terminal_no_selection_trace"]
    assert terminal["prefix_ids"] == report["generated_ids"]
    assert terminal["selected_token_id"] is None and len(terminal["logits"]) == 537
    assert terminal["selection_report"]["scripted_control_not_real_policy_result"] is True
    assert terminal["selection_report"]["certificates"] == []
    assert len(sim.counts["inputs"]) == selected_before_terminal+1
    assert len(sim.counts["original_root_calls"]) == selected_before_terminal+2
    assert sim.counts["restores"] == 1
    no_authority(report)


def test_simulated_scored_eos_uses_real_policy_and_typed_decode_without_suffix_injection(simulated_outer):
    sim = simulated_outer
    report = sim.run()
    count = len(sim.ids)-1
    assert report["status"] == "complete" and report["generated_ids"] == sim.ids
    assert report["selected_token_ids"] == sim.ids[1:] and sim.ids[-1] == 2
    assert report["selected_token_decisions"] == report["numerical_forward_count"] == count
    assert report["state_positions_consumed"] == count
    assert report["terminal_no_selection_trace"] is None and report["terminal_no_selection_decisions"] == 0
    assert report["grammar_accounting"]["actual_prefix_inspections"] == count+1
    assert report["grammar_accounting"]["witness_calls"] == 0
    assert report["final_decoding"]["status"] == "valid_candidate"
    assert sim.counts["inputs"] == [[token] for token in sim.ids[:-1]]
    assert [2] not in sim.counts["inputs"]
    assert len(sim.counts["original_root_calls"]) == count+1
    assert sim.counts["restores"] == 1
    assert all(step["selection_report"]["witness_suffix_injected"] is False for step in report["trace"])
    assert all(step["selection_report"]["certificates"] == [] for step in report["trace"])
    no_authority(report)
