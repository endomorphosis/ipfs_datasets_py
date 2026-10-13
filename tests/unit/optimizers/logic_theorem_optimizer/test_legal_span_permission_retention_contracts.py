"""Pure partition/lineage contracts; no producer or numerical library imports.

AST-detached functions execute against explicit scalar and parameter fakes.
They do not qualify PyTorch execution, held-out legal meaning or model custody.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
from pathlib import Path
import random
import re
import struct
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).resolve().parents[4] / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_permission_retention.py"
TARGETED = SOURCE.with_name("legal_span_targeted_loss.py")
NAMES = (
    "byte_embedding.weight", "token_projection.weight", "token_projection.bias",
    "encoder.weight_ih_l0", "encoder.weight_hh_l0", "encoder.bias_ih_l0", "encoder.bias_hh_l0",
    "encoder.weight_ih_l0_reverse", "encoder.weight_hh_l0_reverse", "encoder.bias_ih_l0_reverse", "encoder.bias_hh_l0_reverse",
    "modality.weight", "modality.bias", "presence.weight", "presence.bias", "start.weight", "start.bias", "end.weight", "end.bias",
    "latent_down.weight", "latent_down.bias", "latent_up.weight", "latent_up.bias")
FACETS = ("presence.weight", "presence.bias", "start.weight", "start.bias", "end.weight", "end.bias")
FLAGS = ("qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority", "semantic_correctness_verified",
    "promotion_performed", "publication_performed")
ZERO = dict(epochs_completed=0, row_cursor=0, optimizer_steps=0)


def detach(path, names, namespace):
    tree = ast.parse(path.read_bytes())
    selected = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names}
    if set(selected) != set(names): raise AssertionError("missing detached contract definitions")
    for node in selected.values():
        if node.decorator_list or any(isinstance(item, (ast.Import, ast.ImportFrom)) for item in ast.walk(node)):
            raise AssertionError("detached contracts refuse imports and decorators")
    exec(compile(ast.Module(body=[selected[name] for name in names], type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def helpers():
    base = dict(json=json, hashlib=hashlib, math=math, random=random, struct=struct, copy=copy,
        SPAN_FIELDS=("actor", "action", "object", "conditions", "exceptions", "temporal"),
        MAX_SOURCE_TOKENS=128, MAX_NEW_STEPS=32, MAX_SECONDS=32, MAX_BYTES=128 * 1024 * 1024,
        POLICY_SCHEMA="bounded-source-span-targeted-loss-policy/v1",
        LEGACY96_SHA256="4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995")
    detach(TARGETED, ("_require", "_raw", "checkpoint_digest", "_policy", "_validate_policy", "_f32", "_progress", "_batch_indices"), base)
    targeted = SimpleNamespace(**{key: base[key] for key in ("_policy", "_f32", "_progress", "_batch_indices")},
        SOURCE_PARENT_SHA256="a" * 64, SOURCE_MODEL_SHA256="b" * 64)
    ns = dict(copy=copy, hashlib=hashlib, json=json, math=math, MODEL_PARAMETER_NAMES=NAMES,
        FACET_PARAMETER_NAMES=FACETS, MAX_NEW_STEPS=32, MAX_SECONDS=32, MAX_BYTES=128 * 1024 * 1024,
        POLICY_SCHEMA="bounded-source-span-permission-retention-policy/v1", targeted=targeted,
        _require=base["_require"], _raw=base["_raw"], checkpoint_digest=base["checkpoint_digest"],
        span=SimpleNamespace(_SHA=re.compile(r"[0-9a-f]{64}\Z")),
        SCHEMA="bounded-permission-retention-span-legal-formula-checkpoint/v1", LINEAGE_ID="bounded_source_span_permission_retention_v1",
        FALSE={key: False for key in FLAGS}, _implementation=lambda: {"test_producer": "c" * 64},
        continuation=SimpleNamespace(_validated=lambda child: child["base_checkpoint"]))
    detach(SOURCE, ("_partition", "_policy", "_validate_policy", "_state_digest", "_configure_parameters",
        "_validate_optimizer_state", "_origin", "_validated", "_modal_rows", "_freeze_entry", "_freeze_summary"), ns)
    return ns


def checkpoint(ns, mode="span-heads-only", steps=0):
    config = dict(latent_dimension=384, latent_enabled=False, seed=1729, learning_rate=.001, batch_size=12)
    state = {name: [float(index)] for index, name in enumerate(NAMES)}
    initial = dict(config=config, training_manifest_sha256="d" * 64, tuning_manifest_sha256="e" * 64,
        training_count=168, tuning_count=96, model_state=copy.deepcopy(state),
        optimizer_state=dict(schema="adam-default-betas-eps/v1", parameters={}), progress=dict(ZERO))
    child = dict(base_checkpoint=initial, source_parent_checkpoint_sha256="a" * 64,
        initial_model_state_sha256="b" * 64, source_parent_optimizer_steps=400, parent_checkpoint_sha256=None)
    policy = ns["_policy"](mode)
    value = dict(schema=ns["SCHEMA"], lineage_id=ns["LINEAGE_ID"], implementation=ns["_implementation"](),
        training_policy=policy, training_policy_sha256=ns["checkpoint_digest"](policy),
        initial_training_policy_sha256=ns["checkpoint_digest"](policy), initial_continuation_checkpoint=child,
        initial_continuation_checkpoint_sha256=ns["checkpoint_digest"](child), source_parent_checkpoint_sha256="a" * 64,
        source_parent_model_state_sha256="b" * 64, config=copy.deepcopy(config), training_manifest_sha256="d" * 64,
        tuning_manifest_sha256="e" * 64, training_count=168, tuning_count=96, model_state=state,
        optimizer_state=dict(schema="adam-default-betas-eps/v1", parameters={}), progress=dict(ZERO),
        parent_checkpoint_sha256=None, **ns["FALSE"])
    value["initial_checkpoint_sha256"] = ns["checkpoint_digest"](value)
    if steps:
        value["progress"] = dict(epochs_completed=steps // 14, row_cursor=(steps % 14) * 12, optimizer_steps=steps)
        value["parent_checkpoint_sha256"] = "f" * 64
        value["optimizer_state"]["parameters"] = {name: dict(step=steps, exp_avg=[0.], exp_avg_sq=[0.])
            for name in policy["parameter_partition"]["trainable_parameter_names"]}
        value["model_state"]["start.weight"] = [99.]
    return value


class Parameter:
    def __init__(self, value): self.value, self.requires_grad, self.grad = value, True, "stale-gradient"
    def requires_grad_(self, flag): self.requires_grad = flag; return self
    def detach(self): return self
    def tolist(self): return [float(self.value)]


class Model:
    def __init__(self): self.named = {name: Parameter(index) for index, name in enumerate(NAMES)}
    def named_parameters(self): return iter(self.named.items())
    def state_dict(self): return self.named


def freeze_fixture(ns, mode="span-heads-only"):
    part = ns["_partition"](mode)
    records = [dict(id="row-0", source_text="Alpha may inspect records."), dict(id="row-1", source_text="Beta shall file notices.")]
    modal = [[1., 2., 3.], [4., 5., 6.]]
    entry = ns["_freeze_entry"](1, [1, 4], records, part, "7" * 64, "7" * 64, ["start.weight"], modal, copy.deepcopy(modal))
    batch = dict(optimizer_step=1, indices=[1, 4], ids=["row-0", "row-1"])
    return part, entry, batch, records, modal


class PermissionRetentionContracts(unittest.TestCase):
    def setUp(self): self.ns = helpers()

    def test_closed_source_names_have23_distinct_tensors(self):
        self.assertEqual(len(NAMES), 23); self.assertEqual(len(set(NAMES)), 23)
        tree = ast.parse(SOURCE.read_bytes())
        assignments = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in ("MODEL_PARAMETER_NAMES", "FACET_PARAMETER_NAMES")}
        self.assertEqual(assignments["MODEL_PARAMETER_NAMES"], NAMES)
        self.assertEqual(assignments["FACET_PARAMETER_NAMES"], FACETS)

    def test_partition_has_all_shared_and_modality_frozen(self):
        part = self.ns["_partition"]("span-heads-only")
        self.assertEqual(part["trainable_parameter_names"], list(FACETS))
        self.assertEqual(len(part["frozen_parameter_names"]), 17)
        self.assertEqual(set(part["frozen_parameter_names"]), set(NAMES) - set(FACETS))
        self.assertTrue(part["shared_features_and_modality_frozen"])

    def test_full_partition_keeps_exact_named_optimizer_order(self):
        part = self.ns["_partition"]("all-parameters")
        self.assertEqual(part["optimizer_parameter_order"], list(NAMES)); self.assertEqual(part["frozen_parameter_names"], [])

    def test_policy_refuses_unknown_mode_and_nonfixed_recipe(self):
        for mode in (None, True, "modality-only", "span-heads", "all-parameters "):
            with self.subTest(mode=mode), self.assertRaises(ValueError): self.ns["_partition"](mode)
        for kwargs in (dict(seed=42), dict(seed=True), dict(batch_order_seed=3), dict(batch_size=6)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): self.ns["_policy"]("all-parameters", **kwargs)

    def test_fixed_objective_is_exact_off_presence1_modality2(self):
        policy = self.ns["_policy"]("span-heads-only")
        objective = policy["objective_policy"]
        self.assertFalse(objective["actor_ranking_enabled"]); self.assertEqual(objective["presence_ce_weight"], 1)
        self.assertEqual(objective["modality_loss_weight"], 2)
        self.assertEqual(self.ns["_validate_policy"](policy), policy)

    def test_policy_rehash_does_not_allow_partition_or_loss_changes(self):
        for field, replacement in (("automatic_selection_or_promotion", True), ("max_seconds", 64), ("new_field", 0)):
            value = self.ns["_policy"]("span-heads-only"); value[field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError): self.ns["_validate_policy"](value)
        value = self.ns["_policy"]("span-heads-only"); value["objective_policy"]["actor_ranking_enabled"] = True
        with self.assertRaises(ValueError): self.ns["_validate_policy"](value)

    def test_configure_exact_subset_resets_frozen_gradients(self):
        model = Model(); named, selected = self.ns["_configure_parameters"](model, self.ns["_partition"]("span-heads-only"))
        self.assertEqual([id(p) for p in selected], [id(named[n]) for n in FACETS])
        self.assertTrue(all(named[n].requires_grad == (n in FACETS) and named[n].grad is None for n in NAMES))

    def test_configure_full_keeps_latent_zero_gated_tensors_trainable(self):
        model = Model(); named, selected = self.ns["_configure_parameters"](model, self.ns["_partition"]("all-parameters"))
        self.assertEqual(len(selected), 23); self.assertTrue(all(p.requires_grad for p in named.values()))

    def test_configure_refuses_parameter_alias_unknown_or_order(self):
        for kind in ("unknown", "order", "alias"):
            model = Model()
            if kind == "unknown": model.named["rogue.weight"] = Parameter(0.)
            elif kind == "order": model.named = dict(reversed(list(model.named.items())))
            else: model.named["start.weight"] = model.named["end.weight"]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.ns["_configure_parameters"](model, self.ns["_partition"]("span-heads-only"))

    def test_parameter_digest_binds_values_and_subset(self):
        model = Model(); old = self.ns["_state_digest"](model)
        frozen = self.ns["_partition"]("span-heads-only")["frozen_parameter_names"]
        frozen_old = self.ns["_state_digest"](model, frozen)
        model.named["start.weight"].value += 1
        self.assertNotEqual(old, self.ns["_state_digest"](model)); self.assertEqual(frozen_old, self.ns["_state_digest"](model, frozen))
        model.named["modality.weight"].value += 1
        self.assertNotEqual(frozen_old, self.ns["_state_digest"](model, frozen))

    def test_true_subset_adam_moments_and_zero_step(self):
        part = self.ns["_partition"]("span-heads-only")
        for steps in (0, 1, 32):
            state = checkpoint(self.ns, steps=steps)["optimizer_state"]
            self.ns["_validate_optimizer_state"](state, part, steps)

    def test_subset_adam_refuses_fabricated_frozen_moments_missing_or_stale(self):
        part = self.ns["_partition"]("span-heads-only")
        for kind in ("frozen", "missing", "stale", "extra", "bool_step"):
            state = checkpoint(self.ns, steps=1)["optimizer_state"]
            if kind == "frozen": state["parameters"]["modality.weight"] = dict(step=1, exp_avg=[0.], exp_avg_sq=[0.])
            elif kind == "missing": state["parameters"].pop("start.weight")
            elif kind == "stale": state["parameters"]["start.weight"]["step"] = 0
            elif kind == "extra": state["schema"] = "adam-default-betas-eps/v2"
            else: state["parameters"]["start.weight"]["step"] = True
            with self.subTest(kind=kind), self.assertRaises(ValueError): self.ns["_validate_optimizer_state"](state, part, 1)

    def test_closed_outer_initial_and_trained_subsets_validate(self):
        for mode in ("all-parameters", "span-heads-only"):
            for steps in (0, 1, 14, 32):
                with self.subTest(mode=mode, steps=steps): self.ns["_validated"](checkpoint(self.ns, mode, steps))

    def test_outer_refuses_oldschema_authority_or_source_drift(self):
        for key, value in (("schema", "warm-start-span-legal-formula-checkpoint/v1"), ("qualified", True),
            ("implementation", {"test_producer": "d" * 64}), ("extra", None)):
            cp = checkpoint(self.ns); cp[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.ns["_validated"](cp)

    def test_outer_refuses_frozen_parameter_mutation_even_after_outer_rehash(self):
        cp = checkpoint(self.ns, steps=1); cp["model_state"]["encoder.bias_ih_l0"] = [1.]
        with self.assertRaises(ValueError): self.ns["_validated"](cp)

    def test_outer_refuses_initial_boundary_moment_or_progress_mutation(self):
        for kind in ("moment", "progress", "parent", "model", "manifest", "config"):
            cp = checkpoint(self.ns)
            if kind == "moment": cp["optimizer_state"]["parameters"]["start.weight"] = dict(step=0, exp_avg=[0.], exp_avg_sq=[0.])
            elif kind == "progress": cp["progress"]["row_cursor"] = 1
            elif kind == "parent": cp["parent_checkpoint_sha256"] = "f" * 64
            elif kind == "model": cp["model_state"]["start.weight"] = [99.]
            elif kind == "manifest": cp["training_manifest_sha256"] = "f" * 64
            else: cp["config"]["latent_enabled"] = True
            with self.subTest(kind=kind), self.assertRaises(ValueError): self.ns["_validated"](cp)

    def test_outer_refuses_rehashed_new_objective_or_policy(self):
        cp = checkpoint(self.ns, steps=1); cp["training_policy"]["objective_policy"]["presence_ce_weight"] = 2
        cp["training_policy_sha256"] = cp["initial_training_policy_sha256"] = self.ns["checkpoint_digest"](cp["training_policy"])
        with self.assertRaises(ValueError): self.ns["_validated"](cp)

    def test_modal_rows_bind_source_and_float32(self):
        records = [dict(id="a", source_text="Permitted.")]
        value = self.ns["_modal_rows"](records, [[1., 2., 3.]])[0]
        self.assertEqual(value["source_sha256"], hashlib.sha256(b"Permitted.").hexdigest())
        for vector in ([1., 2.], [1, 2., 3.], [math.inf, 2., 3.], [0.1, 2., 3.]):
            with self.subTest(vector=vector), self.assertRaises(ValueError): self.ns["_modal_rows"](records, [vector])

    def test_completed_frozen_update_enforces_modality_and_digest_parity(self):
        part, entry, batch, _, _ = freeze_fixture(self.ns)
        summary = self.ns["_freeze_summary"]([entry], [batch], part)
        self.assertEqual(summary["completed_updates"], 1)
        self.assertEqual(summary["batches_sha256"], self.ns["checkpoint_digest"]([entry]))
        self.assertFalse(summary["independent_tensor_custody_attested"])

    def test_full_update_can_record_changed_modality_without_claiming_freeze(self):
        part, _, batch, records, modal = freeze_fixture(self.ns, "all-parameters")
        after = copy.deepcopy(modal); after[0][0] += 1.
        entry = self.ns["_freeze_entry"](1, [1, 4], records, part, "7" * 64, "7" * 64, ["modality.weight"], modal, after)
        self.assertFalse(entry["same_batch_modality_logits_bit_equal"])
        self.ns["_freeze_summary"]([entry], [batch], part)

    def test_freeze_entry_refuses_wrong_update_names_geometry_digest_or_modality(self):
        part, _, _, records, modal = freeze_fixture(self.ns)
        args = [1, [1, 4], records, part, "7" * 64, "7" * 64, ["start.weight"], modal, copy.deepcopy(modal)]
        cases = [(0, 0), (1, [1, 1]), (5, "8" * 64), (6, ["modality.weight"]),
            (6, ["start.weight", "start.weight"]), (8, [[2., 2., 3.], [4., 5., 6.]])]
        for position, value in cases:
            altered = copy.deepcopy(args); altered[position] = value
            with self.subTest(position=position, value=value), self.assertRaises(ValueError): self.ns["_freeze_entry"](*altered)

    def test_freeze_summary_refuses_trace_state_parity_join_and_authority_faults(self):
        part, original, batch, _, _ = freeze_fixture(self.ns)
        mutations = {
            "step": lambda e: e.update(optimizer_step=2), "ids": lambda e: e.update(ids=["wrong", "row-1"]),
            "digest": lambda e: e.update(frozen_parameters_sha256_after="8" * 64),
            "gradient": lambda e: e.update(frozen_gradients_none_before_and_after=False),
            "names": lambda e: e.update(changed_parameter_names=["modality.weight"]),
            "partition": lambda e: e.update(optimizer_parameter_order=list(reversed(FACETS))),
            "extra": lambda e: e.update(qualified=True),
            "source": lambda e: e["modality_after"][0].update(source_sha256="9" * 64),
            "score": lambda e: e["modality_after"][0]["modality_logits"].__setitem__(0, 9.),
            "false_equal": lambda e: e.update(same_batch_modality_logits_bit_equal=False),
            "nonf32": lambda e: e["modality_after"][0]["modality_logits"].__setitem__(0, 0.1),
        }
        for name, mutate in mutations.items():
            entry = copy.deepcopy(original); mutate(entry)
            with self.subTest(name=name), self.assertRaises(ValueError): self.ns["_freeze_summary"]([entry], [batch], part)

    def test_legacy_producers_are_not_mutated_by_new_runtime(self):
        tree = ast.parse(SOURCE.read_bytes())
        imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertFalse(any(any(alias.name in ("torch", "numpy", "transformers", "datasets") for alias in node.names) for node in imports))
        self.assertEqual(sum(isinstance(node, ast.Import) and any(alias.name == "torch" for alias in node.names)
            for node in ast.walk(tree)), 1)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                self.assertFalse(any(isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                    and target.value.id in ("span", "targeted", "continuation") for target in node.targets))


if __name__ == "__main__": unittest.main()
