"""Finite source/control-flow qualification for the warmstart BOS adapter.

Checkpoint checks, model objects, numerical scores and most producer reports
are explicit authored doubles. Only NEW adapter seams are replaced. Genuine
bounded input/copy helpers, a source-only factory, whole-report refusal and two
fixed537 grammar/budget controls are identified separately. The twenty ordinary tests do not read checkpoint files, restore Torch models,
construct optimizers, execute real forwards or establish statutory meaning.
The run_qualification entrypoint additionally observes four genuine BOS forwards
inside the original admitted worker. Its actual-checkpoint evidence remains
separate from these simulations; all paths perform zero training updates.
"""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import (
    legal_compact_content_role_warmstart_runtime_v1 as subject,
    legal_compact_content_prepared_runtime_v3 as prepared,
    legal_compact_content_role_training_v1 as role,
    legal_compact_content_role_trained_runtime_v1 as old_runtime,
)


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


class AuthoredSimulation:
    """Scripted checkpoint/session/producer doubles with genuine pure helpers."""

    def __init__(self, monkeypatch, *, objective_kind="full537", emitted=(3, 2), blocked=False):
        self.emitted, self.blocked = tuple(emitted), blocked
        self.allocations = self.forwards = self.closes = self.checked = 0
        self.events, self.forward_prefixes, self.serving_views = [], [], []
        self.on_forward = self.forward_error = None
        self.damage = None
        self.raw_context = b"authored context: no legal meaning or source permission"
        self.context_hash = hashlib.sha256(self.raw_context).hexdigest()
        self.codec_hash = "c" * 64
        self.budget_pins = [dict(path="/authored/legal_compact_content_scope_filter_v1.py", sha256="a" * 64),
                            dict(path="/authored/legal_compact_content_completion_budget_v1.py", sha256="b" * 64)]
        self.parameter_order = ["authored_parameter_" + str(index) for index in range(13)]
        self.value = dict(schema="legal-compact-role-warmstart-training-checkpoint/v1",
            profile="authored-checkpoint-double-not-a-real-checkpoint",
            objective_policy=dict(objective_kind=objective_kind, weighting="semantic_priority"),
            weights_sha256="1" * 64, codec_sha256=self.codec_hash,
            progress=dict(optimizer_steps=2, epochs_completed=1, row_cursor=0),
            warmstart_parent_checkpoint_sha256="2" * 64, warmstart_parent_policy_sha256="3" * 64,
            historical_parent_optimizer_state_sha256="4" * 64,
            initial_checkpoint_sha256="5" * 64, parent_checkpoint_sha256="6" * 64,
            runtime={"authored_simulation": "not a numerical runtime"}, config={"authored": True},
            codec={"authored": "not a real codec"}, parameter_order=self.parameter_order,
            model_state={name: [float(index)] for index, name in enumerate(self.parameter_order)},
            warmstart_parent_checkpoint={"target_marker": "excluded exposed historical labels"},
            optimizer_state={"optimizer_marker": "excluded authored Adam payload"})
        self.budget = SimpleNamespace(POLICY="authored-budget-policy", PREFIX_SCHEMA="authored-prefix/v1",
            SELECTION_SCHEMA="authored-selection/v1", allowed_token_ids=self.allowed, select_token=self.select)
        self.helper = SimpleNamespace(_fingerprint=prepared._fingerprint, _digest=prepared._digest,
            _producer_rows=lambda *_args: None, _PreparedModel=self.allocate,
            PREFIX_ORIGINS=prepared.PREFIX_ORIGINS, CONTEXT_ORIGINS=prepared.CONTEXT_ORIGINS)
        self.loaded = (Path("/authored/ipfs_datasets_py"), None,
            {"tokens": SimpleNamespace(decode_compact_content_tokens_v1=self.decode),
             "legacy_head": SimpleNamespace(_finish=self.finish)})
        self.original = self.snapshot = self.fingerprint = None
        # Old owners/functions remain untouched. Input checking, identity and
        # serving projection below still execute the NEW product's real code.
        monkeypatch.setattr(subject, "_operation", self.operation)
        monkeypatch.setattr(subject, "_checked", self.check)
        monkeypatch.setattr(subject, "_owners", lambda: (None, old_runtime, self.budget, None, []))

    def operation(self, original, work):
        self.original = original
        self.snapshot = prepared._copy(original, prepared.MAX_INPUT_BYTES, allow_bytes=True)
        self.fingerprint = prepared._fingerprint(self.snapshot)
        self.fence()
        result = work(self.snapshot, dict(prepared=self.helper, scope=self.budget, role=role,
                      warmstart=SimpleNamespace(authored_checkpoint_double=True)), {}, self.loaded,
                      deepcopy(self.budget_pins), deepcopy(self.budget_pins), self.fence)
        # Use the actual original whole-report bound, rather than a fake writer.
        raw = prepared._wire(result, subject.MAX_REPORT_BYTES)
        self.fence()
        return json.loads(raw)

    def fence(self):
        if self.fingerprint is not None:
            if (prepared._fingerprint(self.original) != self.fingerprint
                    or prepared._fingerprint(self.snapshot) != self.fingerprint):
                raise ValueError("authored outer operation input changed")

    def check(self, *_args):
        self.checked += 1
        return deepcopy(self.value)

    def report(self, ids, remaining):
        complete = len(ids) > 1 and ids[-1] == 2
        choices = [] if complete or self.blocked or not remaining else [self.emitted[len(ids) - 1]]
        report = dict(schema=self.budget.PREFIX_SCHEMA, policy=self.budget.POLICY,
            owner_pins=deepcopy(self.budget_pins), authority={"accepted": False},
            training_mask=0, evaluation_gold_mask=0,
            baseline_prefix_report=dict(allowed_token_ids=list(choices)),
            offered_ids=list(ids), allowed_token_ids=choices,
            remaining_new_tokens=remaining, context_raw_sha256=self.context_hash,
            context_sha256=self.context_hash, codec_sha256=self.codec_hash,
            status="complete" if complete else "prefix" if choices else "budget_exhausted",
            reason=None if complete or choices else "no_scope_continuation_within_remaining_budget")
        if self.damage == "prefix_authority":
            report["authority"]["accepted"] = True
        return report

    def allowed(self, ids, raw, *, remaining_new_tokens, **options):
        assert raw == self.raw_context and options["expected_context_sha256"] == self.context_hash
        assert options["expected_codec_sha256"] == self.codec_hash
        self.events.append(("prefix", remaining_new_tokens, list(ids)))
        return self.report(ids, remaining_new_tokens)

    def select(self, scores, ids, raw, *, remaining_new_tokens, **options):
        assert raw == self.raw_context and options["expected_context_sha256"] == self.context_hash
        self.events.append(("selection", remaining_new_tokens, list(ids)))
        prefix = self.report(ids, remaining_new_tokens)
        token = prefix["allowed_token_ids"][0]
        result = dict(schema=self.budget.SELECTION_SCHEMA, policy=self.budget.POLICY,
            owner_pins=deepcopy(self.budget_pins), prefix_report=prefix,
            baseline_selection={"prefix_report": deepcopy(prefix["baseline_prefix_report"])},
            offered_prefix_ids=list(ids), logits=list(scores), logits_sha256=prepared._digest(scores),
            selection_performed=True, selected_token_id=token, next_prefix_ids=list(ids) + [token],
            authority={"accepted": False}, training_mask=0, evaluation_gold_mask=0)
        if self.damage == "selection_logits":
            result["logits"][0] += 1.0
        elif self.damage == "selection_budget":
            result["prefix_report"]["remaining_new_tokens"] += 1
        elif self.damage == "selection_next_prefix":
            result["next_prefix_ids"][-1] = 99
        return result

    def scores(self, ids):
        return [0.0] * 537

    def allocate(self, view, conditioning, loaded, fence):
        self.allocations += 1
        self.serving_views.append(deepcopy(view))
        assert loaded is self.loaded and len(conditioning) == 384
        assert view["schema"] == subject.SERVING_SCHEMA
        outer = self

        class Session:
            def _guard(self):
                fence()

            def forward(self, ids):
                outer.forwards += 1
                outer.forward_prefixes.append(list(ids))
                if outer.forward_error is not None:
                    raise outer.forward_error
                if outer.on_forward is not None:
                    outer.on_forward(view, conditioning, ids)
                result = dict(logits=outer.scores(ids), runtime=deepcopy(outer.value["runtime"]),
                              output_shape=[1, len(ids), 537])
                if outer.damage == "runtime":
                    result["runtime"] = {"different_authored_runtime": True}
                elif outer.damage == "shape":
                    result["output_shape"][-1] = 536
                return result

            def close(self):
                outer.closes += 1

        return Session()

    def decode(self, ids, raw, **options):
        assert raw == self.raw_context
        return dict(generated_ids=list(ids), context_raw_sha256=self.context_hash,
            context_sha256=self.context_hash, codec_sha256=self.codec_hash,
            status="valid_candidate" if ids[-1] == 2 else "authored_incomplete")

    @staticmethod
    def finish(failure, close):
        try:
            close()
        except BaseException:
            if failure is None:
                raise

    def call(self, *, score=False, max_new_tokens=2, **overrides):
        options = dict(checkpoint={"authored": "not a checkpoint"}, conditioning=[0.5] * 384,
            context_raw=self.raw_context, expected_checkpoint_sha256="d" * 64,
            expected_policy_sha256="e" * 64, expected_context_sha256=self.context_hash,
            context_origin="authored_fixture")
        options.update(overrides)
        if score:
            return subject.score_from_bos(**options)
        return subject.generate_from_bos(max_new_tokens=max_new_tokens, **options)


def authored_grammar():
    """Independent fictional101-ID expression and lexical oracle, not a law."""
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens
    import re
    obj = dict(arguments=[], kind="atomic", name="Object", schema_version="syntax-logic-sort/v1")
    boolean = dict(arguments=[], kind="bool", name="Bool", schema_version="syntax-logic-sort/v1")
    def identity(namespace, value):
        return dict(interface="LogicIdentityNamespaces@1", namespace=namespace,
                    schema_version="logic-identity-namespaces/v1", value=value, version="1.0.0")
    names = ["FixtureHand", "FixtureTake", "FixtureMark"]
    symbols = [dict(domain=[deepcopy(obj), deepcopy(obj)], kind="predicate", metadata={}, name=name,
        range=deepcopy(boolean), schema_version="syntax-symbol-declaration/v1") for name in names]
    context = dict(schema="legal-relational-compact-context/v1",
        argument_roles=[dict(symbol=name, roles=["first", "second"]) for name in names],
        signature=dict(family=identity("family", "tdfol"), features=[], interface="LogicSignature@1",
            metadata={}, profile=identity("profile", "tdfol_default"), schema_version="syntax-logic-signature/v1",
            sorts=[boolean, obj], symbols=symbols))
    def atom(index, left, right):
        return ["predicate", index, [["variable", left], ["variable", right]]]
    document = dict(schema="legal-relational-compact-content/v1", tree=["forall", 0,
        ["exists", 1, ["forall", 2, ["and", ["extension", "F", ["implies",
            atom(0, 0, 1), atom(1, 1, 0)]], atom(2, 2, 1)]]]])
    raw = wire(document).decode()
    pieces = re.findall(r'"(?:[^"\\]|\\.)*"|0|[1-9][0-9]*|[{}\[\],:]', raw)
    assert "".join(pieces) == raw
    codec = tokens.build_compact_content_token_codec_v1()
    lookup = {spelling: index for index, spelling in enumerate(codec["vocabulary"])}
    ids = [codec["bos_id"], *(lookup[piece] for piece in pieces), codec["eos_id"]]
    assert len(ids) == 101
    return tokens, codec, wire(context), document, ids


class GenuineGrammarSimulation(AuthoredSimulation):
    """Real grammar/budget/selector; fake checkpoint, session and scripted scores."""

    def __init__(self, monkeypatch):
        super().__init__(monkeypatch)
        from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_completion_budget_v1 as budget
        tokens, codec, self.raw_context, self.document, self.ids = authored_grammar()
        self.budget = budget
        _, _, actual_tokens, pins = budget._owners()
        assert actual_tokens is tokens
        self.budget_pins = deepcopy(pins)
        self.token_pins = deepcopy(tokens._owner()[1])
        self.loaded = (Path(tokens.__file__).absolute().parents[3], None,
            {"tokens": tokens, "legacy_head": SimpleNamespace(_finish=self.finish)})
        self.context_hash = hashlib.sha256(self.raw_context).hexdigest()
        self.codec_hash = tokens.compact_content_token_codec_sha256(codec)
        self.value.update(codec=codec, codec_sha256=self.codec_hash)
        self.helper._producer_rows = self.producer_rows

    def producer_rows(self, report, loaded, expected_paths):
        assert loaded is self.loaded
        actual = {row["path"]: row for row in report["owner_pins"]}
        expected = {row["path"]: row for row in self.token_pins}
        assert len(actual) == len(report["owner_pins"]) and len(expected) == len(self.token_pins)
        assert actual == expected and set(actual) == expected_paths
        assert loaded[2]["tokens"]._owner()[1] == self.token_pins
        assert report["authority"] and all(value is False for value in report["authority"].values())
        assert report["training_mask"] == report["evaluation_gold_mask"] == 0

    def scores(self, ids):
        assert ids == self.ids[:len(ids)]
        result = [-1.0] * 537
        result[self.ids[len(ids)]] = 1.0
        return result


def test_public_bos_surfaces_have_no_prefix_target_or_reference(monkeypatch):
    for api in (subject.score_from_bos, subject.generate_from_bos):
        names = set(inspect.signature(api).parameters)
        assert not names.intersection({"prefix_ids", "prefixes_ids", "target_ids", "target", "reference", "row_cursor"})
        assert {"checkpoint", "conditioning", "context_raw", "context_origin"} <= names
    assert "max_new_tokens" in inspect.signature(subject.generate_from_bos).parameters


def test_real_metadata_factory_reuses_exact_owners_without_model_work(monkeypatch):
    def work(data, owners, modules, loaded, pins, budget_pins, fence):
        assert data == {"metadata_factory_only": True}
        assert modules["role_training"] is owners["role"]
        assert owners["warmstart"]._owners()[1]["role_training"] is owners["role"]
        assert owners["scope"]._owners()[1] is loaded[2]["selection"]
        assert owners["scope"]._owners()[2] is loaded[2]["tokens"]
        assert len({row["path"] for row in pins}) == len(pins)
        assert {Path(row["path"]).name for row in pins} >= {
            "legal_compact_content_role_warmstart_runtime_v1.py",
            "legal_compact_content_role_warmstart_training_v1.py",
            "legal_compact_content_role_budget_runtime_v1.py"}
        fence()
        return {"metadata_only": True, "model_or_optimizer_called": False}
    assert subject._operation({"metadata_factory_only": True}, work) == {
        "metadata_only": True, "model_or_optimizer_called": False}


def test_real_metadata_operation_refuses_whole_report_overflow(monkeypatch):
    def work(*_args):
        return {"authored_oversized_metadata": "x" * (subject.MAX_REPORT_BYTES + 1)}
    with pytest.raises(ValueError):
        subject._operation({"metadata_report_bound_only": True}, work)


def test_real_serving_projection_excludes_nested_targets_and_adam(monkeypatch):
    for kind in ("scope_conditional", "full537"):
        sim = AuthoredSimulation(monkeypatch, objective_kind=kind)
        report = sim.call(score=True)
        view = sim.serving_views[0]
        assert view["objective_kind"] == report["objective_kind"] == kind
        assert view["model_state"] == sim.value["model_state"] and len(view["parameter_order"]) == 13
        assert view["warmstart_parent_checkpoint_sha256"] == sim.value["warmstart_parent_checkpoint_sha256"]
        assert not {"warmstart_parent_checkpoint", "optimizer_state", "basis_checkpoint", "role_inventories"}.intersection(view)
        assert "target_marker" not in wire(view).decode() and "optimizer_marker" not in wire(view).decode()
        assert report["checkpoint_schema_conversion_performed"] is False


def test_scoring_observes_one_fixed_bos_and_never_selects(monkeypatch):
    sim = AuthoredSimulation(monkeypatch)
    result = sim.call(score=True)
    assert result["schema"] == subject.SCORE_SCHEMA and result["status"] == "scored"
    assert result["logits"] == [0.0] * 537 and result["generated_ids"] == [1]
    assert result["selected_token_ids"] == result["trace"] == []
    assert sim.forward_prefixes == [[1]] and sim.allocations == sim.forwards == sim.closes == 1
    assert all(event[0] != "selection" for event in sim.events)


def test_nonfinite_full_vocabulary_scores_refuse_and_close(monkeypatch):
    for bad in (float("nan"), float("inf")):
        sim = AuthoredSimulation(monkeypatch)
        sim.scores = lambda _ids, bad=bad: [bad] + [0.0] * 536
        with pytest.raises(ValueError):
            sim.call(score=True)
        assert sim.allocations == sim.forwards == sim.closes == 1
        assert all(event[0] != "selection" for event in sim.events)


def test_generation_reuses_one_lifetime_and_counts_eos(monkeypatch):
    sim = AuthoredSimulation(monkeypatch)
    result = sim.call(max_new_tokens=2)
    assert result["status"] == "complete" and result["generated_ids"] == [1, 3, 2]
    assert sim.allocations == sim.closes == 1 and sim.forwards == 2
    assert sim.forward_prefixes == [[1], [1, 3]]
    assert sim.events == [("prefix", 2, [1]), ("selection", 2, [1]),
                          ("prefix", 1, [1, 3]), ("selection", 1, [1, 3]), ("prefix", 0, [1, 3, 2])]
    assert result["settings"]["eos_counted_in_new_token_budget"] is True


def test_allowance_endpoints_are_explicit_and_eos_stops_early(monkeypatch):
    for maximum in (1, 100):
        sim = AuthoredSimulation(monkeypatch, emitted=(2,))
        result = sim.call(max_new_tokens=maximum)
        assert result["settings"]["max_new_tokens"] == maximum
        assert result["generated_ids"] == [1, 2] and sim.forwards == sim.closes == 1


def test_invalid_allowances_refuse_before_checkpoint_or_simulated_model(monkeypatch):
    for bad in (0, 101, True, False, 1.0, None):
        sim = AuthoredSimulation(monkeypatch)
        with pytest.raises(ValueError):
            sim.call(max_new_tokens=bad)
        assert sim.checked == sim.allocations == sim.forwards == sim.closes == 0


def test_initial_budget_block_never_allocates_simulated_model(monkeypatch):
    sim = AuthoredSimulation(monkeypatch, blocked=True)
    result = sim.call()
    assert result["status"] == "blocked" and result["generated_ids"] == [1]
    assert result["final_decoding"] is None and result["trace"] == []
    assert sim.allocations == sim.forwards == sim.closes == 0


def test_exhausted_non_eos_output_is_retained_without_repair(monkeypatch):
    sim = AuthoredSimulation(monkeypatch, emitted=(3, 4, 2))
    result = sim.call(max_new_tokens=1)
    assert result["status"] in ("blocked", "unfinished")
    assert result["generated_ids"] == [1, 3] and result["selected_token_ids"] == [3]
    assert result["final_decoding"]["status"] != "valid_candidate"
    assert sim.allocations == sim.forwards == sim.closes == 1


def test_mismatched_selection_receipts_refuse_and_close(monkeypatch):
    for damage in ("selection_logits", "selection_budget", "selection_next_prefix"):
        sim = AuthoredSimulation(monkeypatch)
        sim.damage = damage
        with pytest.raises(ValueError):
            sim.call()
        assert sim.allocations == sim.forwards == sim.closes == 1


def test_interrupted_forward_preserves_original_error_and_closes(monkeypatch):
    sim = AuthoredSimulation(monkeypatch)
    error = KeyboardInterrupt("authored forward interruption")
    sim.forward_error = error
    with pytest.raises(KeyboardInterrupt) as raised:
        sim.call()
    assert raised.value is error and sim.allocations == sim.forwards == sim.closes == 1


def test_serving_view_mutation_cannot_return_a_success(monkeypatch):
    sim = AuthoredSimulation(monkeypatch)
    sim.on_forward = lambda view, *_args: view["model_state"].update(unexpected=[1.0])
    with pytest.raises(ValueError):
        sim.call(score=True)
    assert sim.allocations == sim.forwards == sim.closes == 1


def test_original_caller_mutation_is_seen_by_genuine_snapshot_fence(monkeypatch):
    sim = AuthoredSimulation(monkeypatch)
    offered = {"authored": "not a checkpoint"}
    sim.on_forward = lambda *_args: offered.update(changed=True)
    with pytest.raises(ValueError):
        sim.call(score=True, checkpoint=offered)
    assert sim.allocations == sim.forwards == sim.closes == 1


def test_genuine_role_input_checks_refuse_context_and_conditioning_drift(monkeypatch):
    cases = [dict(expected_context_sha256="0" * 64), dict(context_origin="source_derived"),
             dict(conditioning=[0.5]), dict(conditioning=[float("inf")] * 384)]
    for damage in cases:
        sim = AuthoredSimulation(monkeypatch)
        with pytest.raises(ValueError):
            sim.call(score=True, **damage)
        assert sim.checked == sim.allocations == sim.forwards == sim.closes == 0


def test_wrong_runtime_shape_and_prefix_authority_are_refused(monkeypatch):
    for damage in ("runtime", "shape", "prefix_authority"):
        sim = AuthoredSimulation(monkeypatch)
        sim.damage = damage
        with pytest.raises(ValueError):
            sim.call(score=True)
        assert sim.closes == sim.allocations
        assert sim.forwards == (0 if damage == "prefix_authority" else 1)


def test_genuine_policy_accepts101_authored_ids_with_scripted_scores(monkeypatch):
    sim = GenuineGrammarSimulation(monkeypatch)
    result = sim.call(max_new_tokens=100)
    assert result["status"] == "complete" and result["generated_ids"] == sim.ids
    assert len(result["trace"]) == sim.forwards == 100
    assert sim.allocations == sim.closes == 1
    assert result["final_decoding"]["status"] == "valid_candidate"
    assert result["final_decoding"]["generated_ids"] == sim.ids
    assert result["final_decoding"]["codec_sha256"] == sim.codec_hash
    assert result["final_decoding"]["context_raw_sha256"] == sim.context_hash
    assert sim.forward_prefixes == [sim.ids[:length] for length in range(1, 101)]
    assert sim.loaded[2]["tokens"]._owner()[1] == sim.token_pins


def test_genuine_policy_refuses_a_missing_final_eos_budget_slot(monkeypatch):
    sim = GenuineGrammarSimulation(monkeypatch)
    # A100-ID scripted continuation is not a global language minimum. At the
    # actually authored prefix after98 emissions, the final object close and
    # EOS still need two slots. A99-total-new allowance leaves only one here.
    prefix = sim.ids[:-2]
    assert len(prefix) == 99
    options = dict(expected_context_sha256=sim.context_hash, codec=sim.value["codec"],
                   expected_codec_sha256=sim.codec_hash)
    blocked = sim.budget.allowed_token_ids(prefix, sim.raw_context,
        remaining_new_tokens=1, **options)
    sufficient = sim.budget.allowed_token_ids(prefix, sim.raw_context,
        remaining_new_tokens=2, **options)
    assert blocked["remaining_new_tokens"] == 1 and blocked["allowed_token_ids"] == []
    assert blocked["reason"] == "no_scope_continuation_within_remaining_budget"
    assert sim.ids[-2] in sufficient["allowed_token_ids"]
    assert sim.allocations == sim.forwards == sim.closes == 0


def test_simulated_results_keep_exposure_and_all_authority_limits(monkeypatch):
    sim = AuthoredSimulation(monkeypatch, objective_kind="full537")
    result = sim.call(score=True, context_origin="target_derived_label")
    assert result["objective_kind"] == "full537" and result["prefix_origin"] == "bos_seed"
    assert result["supplied_context_target_access_declared"] is True
    assert result["target_access_for_checkpoint_validation"] is True
    assert result["serving_view_contains_training_targets"] is False
    assert result["serving_view_contains_optimizer_state"] is False
    assert all(value is False for value in result["authority"].values())
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    assert result["optimizer_constructed"] is result["optimizer_state_restored"] is result["training_executed"] is False


SIMULATION_TEST_NAMES = (
    "test_public_bos_surfaces_have_no_prefix_target_or_reference",
    "test_real_metadata_factory_reuses_exact_owners_without_model_work",
    "test_real_metadata_operation_refuses_whole_report_overflow",
    "test_real_serving_projection_excludes_nested_targets_and_adam",
    "test_scoring_observes_one_fixed_bos_and_never_selects",
    "test_nonfinite_full_vocabulary_scores_refuse_and_close",
    "test_generation_reuses_one_lifetime_and_counts_eos",
    "test_allowance_endpoints_are_explicit_and_eos_stops_early",
    "test_invalid_allowances_refuse_before_checkpoint_or_simulated_model",
    "test_initial_budget_block_never_allocates_simulated_model",
    "test_exhausted_non_eos_output_is_retained_without_repair",
    "test_mismatched_selection_receipts_refuse_and_close",
    "test_interrupted_forward_preserves_original_error_and_closes",
    "test_serving_view_mutation_cannot_return_a_success",
    "test_original_caller_mutation_is_seen_by_genuine_snapshot_fence",
    "test_genuine_role_input_checks_refuse_context_and_conditioning_drift",
    "test_wrong_runtime_shape_and_prefix_authority_are_refused",
    "test_genuine_policy_accepts101_authored_ids_with_scripted_scores",
    "test_genuine_policy_refuses_a_missing_final_eos_budget_slot",
    "test_simulated_results_keep_exposure_and_all_authority_limits",
)


def run_simulation_qualification():
    """Optional existing-owned-worker entry; no fixture discovery or collection."""
    assert len(SIMULATION_TEST_NAMES) == len(set(SIMULATION_TEST_NAMES)) == 20
    passed = []
    for name in SIMULATION_TEST_NAMES:
        with pytest.MonkeyPatch.context() as monkeypatch:
            globals()[name](monkeypatch=monkeypatch)
        passed.append(name)
    return dict(schema="legal-warmstart-BOS-simulation-controls/v1", passed=passed,
        controls=20, checkpoint_model_and_scores_are_authored_doubles=True,
        real_policy_101_id_trajectory_and_final_eos_budget_refusal=True,
        actual_checkpoint_or_Torch_model_execution=False,
        simulated_model_forwards_are_not_real_model_forwards=True)


SELECTED = ['contract_refusals', 'four_saved_BOS_scores', 'scripted_generation_controls']



def run_qualification(*, owner, cases, torch, save, read_saved):
    """Twenty authored controls plus exactly four real model-only BOS forwards.

    The worker supplies four independently pinned before-state/logit pairs. It
    extracts only the first BOS score vector from each retained teacher-forced
    report. Labels and complete reference ASTs are never passed to the consumer.
    This is score transport and serving mechanics, not autonomous quality.
    """
    import hashlib
    import json
    import math
    from copy import deepcopy
    from pathlib import Path
    import pytest

    selected = ['contract_refusals', 'four_saved_BOS_scores', 'scripted_generation_controls']

    def need(value, message):
        if not value:
            raise ValueError(message)

    def wire(value):
        return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()

    def digest(value):
        return hashlib.sha256(wire(value)).hexdigest()

    artifacts = {}

    def put(name, value):
        need(Path(name).name == name and name not in artifacts, 'fresh direct report required')
        before = digest(value)
        descriptor = save(name, value)
        raw = read_saved(descriptor)
        need(digest(value) == before and len(raw) == descriptor['bytes']
             and hashlib.sha256(raw).hexdigest() == descriptor['sha256']
             and json.loads(raw) == value, 'saved complete report differs')
        artifacts[name] = descriptor

    need(type(cases) is list and len(cases) == 4, 'exact four-case saved-score cohort required')
    # The unchanged custody operation exposes the original numerical owner graph
    # without requiring any checkpoint or allocating a model.
    prepared = __import__('ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_prepared_runtime_v3',
                          fromlist=['_owners'])
    loaded = prepared._owners()
    head = loaded[2]['legacy_head']
    numerical = head._owners(numeric=True)['modules']['numerical']
    counts = dict(model_allocations=0,model_forward_entered=0,model_forward_completed=0,
        gru_entered=0,gru_completed=0,adam_allocations=0,optimizer_base_allocations=0,
        backward_entered=0,backward_completed=0,optimizer_step_entered=0,
        optimizer_step_completed=0,gradient_clip_calls=0,autograd_grad_calls=0,forbidden_calls=0)
    active = {'case':None,'model':None,'forward':False,'gru':False,'scores':None}
    handles = []
    rng = torch.get_rng_state().clone()
    real_model = numerical._model
    real_gru = torch.nn.GRU.forward

    def deny(*args, **kwargs):
        counts['forbidden_calls'] += 1
        raise ValueError('no optimizer, backward, differentiation, update or training API admitted')

    def state(model):
        return {name:value.detach().tolist() for name,value in model.state_dict().items()}

    def before_forward(model, args):
        case=active['case']
        need(case is not None and model is active['model'] and not active['forward']
             and counts['model_forward_entered'] < 4, 'undeclared BOS forward')
        vector,prefix=args
        need(not model.training and not torch.is_grad_enabled() and torch.is_inference_mode_enabled()
             and vector.dtype is torch.float32 and vector.device.type == 'cpu'
             and list(vector.shape) == [1,384]
             and vector.detach().tolist()[0] == torch.tensor(case['conditioning'],dtype=torch.float32).tolist()
             and prefix.dtype is torch.long and prefix.device.type == 'cpu'
             and prefix.detach().tolist() == [[1]]
             and state(model) == case['checkpoint']['model_state'],
             'actual BOS vector/prefix/state/eval mode differs')
        counts['model_forward_entered'] += 1
        active['forward']=True

    def after_forward(model, args, output):
        projected,logits=output
        need(model is active['model'] and active['gru'] and active['scores'] is None
             and list(projected.shape)==[1,384] and list(logits.shape)==[1,1,537]
             and logits.dtype is torch.float32 and logits.device.type=='cpu'
             and not logits.requires_grad and bool(torch.isfinite(logits).all()),
             'actual complete BOS output differs')
        active['scores']=logits[0,0].detach().tolist()
        counts['model_forward_completed']+=1

    def construct_model(*args, **kwargs):
        case=active['case']
        if case is None:
            counts['forbidden_calls']+=1
            raise ValueError('real numerical allocation forbidden during authored controls')
        need(case is not None and active['model'] is None and counts['model_allocations']<4,
             'undeclared model allocation')
        counts['model_allocations']+=1
        model=real_model(*args, **kwargs)
        active['model']=model
        handles.extend((model.register_forward_pre_hook(before_forward),
                        model.register_forward_hook(after_forward)))
        return model

    def gru(module, *args, **kwargs):
        need(active['model'] is not None and module is active['model'].decoder
             and active['forward'] and not active['gru'] and counts['gru_entered']<4,
             'undeclared recurrent forward')
        active['gru']=True;counts['gru_entered']+=1
        result=real_gru(module,*args,**kwargs)
        counts['gru_completed']+=1
        return result

    reports=[]
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(numerical,'_model',construct_model)
            patch.setattr(torch.nn.GRU,'forward',gru)
            for target,name in [(torch.optim.Adam,'__init__'),(torch.optim.Optimizer,'__init__'),
                (torch.optim.Adam,'step'),(torch.autograd,'backward'),(torch.autograd,'grad'),
                (torch.Tensor,'backward'),(torch.nn.utils,'clip_grad_norm_')]:
                patch.setattr(target,name,deny)
            warmstart=owner._owners()[3]
            for name in ['restore','training_row','objective','pack','create']:
                patch.setattr(warmstart,name,deny)
            # Run the authored controls inside the same actual numerical caps.
            # Every NEW-module seam is restored before genuine score intake.
            simulated=run_simulation_qualification()
            need(simulated['controls']==20 and len(simulated['passed'])==20,
                 'complete twenty-control authored cohort required')
            put('simulation-controls.json',simulated)
            for case in cases:
                need(type(case['label']) is str and case['label'] not in [r['label'] for r in reports]
                     and len(case['expected_bos_logits'])==537
                     and all(type(x) is float and math.isfinite(x) for x in case['expected_bos_logits']),
                     'finite independently bound BOS oracle required')
                before=deepcopy(case)
                active.update(case=case,model=None,forward=False,gru=False,scores=None)
                observed=owner.score_from_bos(case['checkpoint'],case['conditioning'],case['context_raw'],
                    expected_checkpoint_sha256=case['expected_checkpoint_sha256'],
                    expected_policy_sha256=case['expected_policy_sha256'],
                    expected_context_sha256=case['expected_context_sha256'],context_origin=case['context_origin'])
                need(case==before and observed['status']=='scored'
                     and observed['initial_prefix_ids']==observed['generated_ids']==[1]
                     and observed['selected_token_ids']==observed['trace']==[]
                     and observed['model_restore_count']==observed['numerical_forward_count']==1
                     and observed['checkpoint_sha256']==case['expected_checkpoint_sha256']
                     and observed['objective_policy_sha256']==case['expected_policy_sha256']
                     and observed['objective_kind']==case['checkpoint']['objective_policy']['objective_kind']
                     and observed['logits']==active['scores']
                     and all(math.isclose(actual,expected,rel_tol=2e-6,abs_tol=2e-6)
                             for actual,expected in zip(observed['logits'],case['expected_bos_logits']))
                     and observed['optimizer_constructed'] is observed['optimizer_state_restored']
                         is observed['training_executed'] is False
                     and all(x is False for x in observed['authority'].values())
                     and state(active['model'])==case['checkpoint']['model_state']
                     and all(p.grad is None for p in active['model'].parameters())
                     and torch.equal(rng,torch.get_rng_state()),
                     'saved BOS numerical parity, caller state, serving identity or no-training contract differ')
                record=dict(label=case['label'],checkpoint_sha256=case['expected_checkpoint_sha256'],
                    objective_kind=observed['objective_kind'],oracle_report_ref=case['oracle_report_ref'],
                    checked_scores=537,exact_scores=sum(a==b for a,b in zip(observed['logits'],case['expected_bos_logits'])),
                    maximum_absolute_error=max(abs(a-b) for a,b in zip(observed['logits'],case['expected_bos_logits'])),
                    oracle_comparison=dict(rel_tol=2e-6,abs_tol=2e-6,
                        reason='retained46-token training versus1-token inference float32 matrix shapes'),
                    scores_sha256=digest(observed['logits']),
                    inherited_tensors=len(case['checkpoint']['model_state']),report=observed)
                put(case['label']+'-bos.json',record)
                reports.append({key:value for key,value in record.items() if key!='report'})
                active.update(case=None,model=None)
    finally:
        for handle in handles:handle.remove()
    need(all(counts[key]==4 for key in ['model_allocations','model_forward_entered','model_forward_completed',
             'gru_entered','gru_completed'])
         and all(counts[key]==0 for key in ['adam_allocations','optimizer_base_allocations',
             'backward_entered','backward_completed','optimizer_step_entered','optimizer_step_completed',
             'gradient_clip_calls','autograd_grad_calls','forbidden_calls'])
         and len(reports)==4 and torch.equal(rng,torch.get_rng_state()), 'exact finite physical counts differ')
    put('actual-counts.json',counts)
    summary=dict(status='pass',completed_checks=selected,actual_gru_forward_count=4,
        model_allocations=4,optimizer_allocations=0,optimizer_updates=0,backward_calls=0,
        generation_performed=False,genuine_generation_forwards=0,training_performed=False,
        simulation_cases=20,checked_saved_score_coordinates=4*537,
        exact_value_equal_score_coordinates=sum(row['exact_scores'] for row in reports),
        maximum_absolute_score_error=max(row['maximum_absolute_error'] for row in reports),
        score_comparison=dict(rel_tol=2e-6,abs_tol=2e-6),
        source_encoder_authenticated=False,reconstruction_efficacy_measured=False,
        legal_or_holdout_accuracy_established=False)
    put('summary.json',summary)
    return dict(summary=summary,physical_counts=counts,artifacts=artifacts,parity_reports=reports)