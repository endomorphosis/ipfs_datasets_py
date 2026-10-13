"""Pure opt-in saved-score contracts; run directly with Python's unittest.

Package namespace stubs bypass optional top-level initialization. Real retained
leaf tokenizer, grammar and joint-selection sources execute without tensor,
SDK, encoder or model calls. No checkpoints, targets or resource APIs are read.
"""
from pathlib import Path
from types import ModuleType
import copy
import hashlib
import importlib
import importlib.abc
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[4]
PACKAGES = ("ipfs_datasets_py", "ipfs_datasets_py.logic", "ipfs_datasets_py.logic.legal_ir",
            "ipfs_datasets_py.optimizers", "ipfs_datasets_py.optimizers.logic_theorem_optimizer",
            "ipfs_datasets_py.utils")


class _NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"torch", "numpy", "transformers", "sentence_transformers", "huggingface_hub"}:
            raise AssertionError("numerical/model/SDK import forbidden: " + fullname)
        return None


class PresenceRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {name: module for name, module in sys.modules.copy().items()
                        if name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py.")}
        for name in cls.previous:
            del sys.modules[name]
        cls.blocker = _NoModels()
        sys.meta_path.insert(0, cls.blocker)
        try:
            for name in PACKAGES:
                module = ModuleType(name)
                module.__path__ = [str(ROOT.joinpath(*name.split(".")))]
                module.__file__ = str(ROOT.joinpath(*name.split("."), "__init__.py"))
                sys.modules[name] = module
            cls.subject = importlib.import_module("ipfs_datasets_py.logic.legal_ir.presence_routing")
            cls.joint = importlib.import_module("ipfs_datasets_py.logic.legal_ir.joint_span_selection")
            cls.owner = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_formula")
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        for name in list(sys.modules):
            if name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py."):
                del sys.modules[name]
        sys.modules.update(cls.previous)
        if cls.blocker in sys.meta_path:
            sys.meta_path.remove(cls.blocker)

    def packet(self, source, *, identifier="example"):
        tokens = [{key: token[key] for key in ("text", "start", "end")}
                  for token in self.owner.tokenize_source(source)]
        count = len(tokens)
        scores = {"schema": "joint-source-span-scores/v1", "tokens": tokens,
                  "modality_logits": [-6.0, 8.0, -4.0],
                  "presence_logits": {field: [5.0, -5.0] for field in self.joint.OPTIONAL_FIELDS},
                  "start_logits": {field: [-80.0] * count for field in self.joint.FIELDS},
                  "end_logits": {field: [-80.0] * count for field in self.joint.FIELDS}}
        self.point(scores, "actor", 0, 0)
        self.point(scores, "action", 1, 1)
        return {"id": identifier, "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(), "scores": scores}

    @staticmethod
    def point(scores, field, start, end):
        scores["start_logits"][field][start] = 40.0
        scores["end_logits"][field][end] = 40.0

    def late_example(self):
        source = "Ada files report after notice and review following consultation within 30 days."
        adapted = self.packet(source)
        tokens = adapted["scores"]["tokens"]
        start = next(i for i, token in enumerate(tokens) if token["text"] == "within")
        end = next(i for i, token in enumerate(tokens) if token["text"] == "days")
        self.assertGreater(start, 8)
        self.point(adapted["scores"], "temporal", start, end)
        adapted["scores"]["presence_logits"]["object"] = [-5.0, 5.0]
        self.point(adapted["scores"], "object", 2, 2)
        parent = copy.deepcopy(adapted)
        parent["scores"]["presence_logits"]["temporal"] = [-5.0, 5.0]
        parent["scores"]["modality_logits"] = [8.0, -6.0, -4.0]
        parent["scores"]["start_logits"]["temporal"] = [-80.0] * len(tokens)
        parent["scores"]["end_logits"]["temporal"] = [-80.0] * len(tokens)
        self.point(parent["scores"], "temporal", end - 1, end - 1)
        return source, parent, adapted

    def test_late_temporal_restoration_keeps_adapted_boundaries_and_modality(self):
        source, parent, adapted = self.late_example()
        before = self.joint.select_joint_spans(source, adapted["scores"])
        self.assertEqual(before["canonical_ir"]["rules"][0]["temporal"], [])
        result = self.subject.compose_presence_scores(source, parent, adapted)
        occurrence = result["occurrence"]
        for component in ("tokens", "modality_logits", "start_logits", "end_logits"):
            self.assertEqual(occurrence["scores"][component], adapted["scores"][component])
        after = self.joint.select_joint_spans(source, occurrence["scores"])
        self.assertEqual(after["status"], "selected")
        self.assertEqual(after["canonical_ir"]["rules"][0]["temporal"], ["within 30 days"])
        self.assertEqual(after["canonical_ir"]["rules"][0]["modality"], "P")
        self.assertFalse(result["provenance"]["actual_owner_report"])
        self.assertFalse(result["provenance"]["trained_model"])
        self.assertFalse(result["provenance"]["default_promoted"])
        self.assertFalse(result["provenance"]["semantic_correctness_verified"])

    def test_duration_in_actor_parent_false_positive_is_preserved_and_may_abstain(self):
        source = "Thirty Day LLC files report."
        adapted = self.packet(source)
        adapted["scores"]["start_logits"]["actor"] = [-80.0] * 6
        adapted["scores"]["end_logits"]["actor"] = [-80.0] * 6
        adapted["scores"]["start_logits"]["action"] = [-80.0] * 6
        adapted["scores"]["end_logits"]["action"] = [-80.0] * 6
        self.point(adapted["scores"], "actor", 0, 2)
        self.point(adapted["scores"], "action", 3, 3)
        self.point(adapted["scores"], "temporal", 0, 1)
        parent = copy.deepcopy(adapted)
        parent["scores"]["presence_logits"]["temporal"] = [-5.0, 5.0]
        result = self.subject.compose_presence_scores(source, parent, adapted)
        selected = self.joint.select_joint_spans(source, result["occurrence"]["scores"], top_k=1)
        self.assertTrue(selected["fixed_decisions"]["facets"]["temporal"]["present"])
        self.assertEqual(selected["status"], "abstained")
        self.assertEqual(selected["reason"], "no_compatible_assignment_in_retained_domain")
        self.assertIn("Parent presence errors", result["provenance"]["limitations"][0])

    def test_signed_zero_tie_is_preserved_and_joint_abstains(self):
        source, parent, adapted = self.late_example()
        parent["scores"]["presence_logits"]["temporal"] = [-0.0, 0.0]
        result = self.subject.compose_presence_scores(source, parent, adapted)
        vector = result["occurrence"]["scores"]["presence_logits"]["temporal"]
        self.assertEqual(b"".join(struct.pack("!f", x) for x in vector), bytes.fromhex("8000000000000000"))
        components = result["provenance"]["presence_components"]["temporal"]
        self.assertEqual(components["parent"]["binary32_sha256"], components["composed"]["binary32_sha256"])
        self.assertNotEqual(components["parent"]["binary32_sha256"], hashlib.sha256(b"\0" * 8).hexdigest())
        selected = self.joint.select_joint_spans(source, result["occurrence"]["scores"])
        self.assertEqual(selected["reason"], "ambiguous_fixed_head_decision")

    def test_all_optional_fields_and_canonical_subsets(self):
        source, parent, adapted = self.late_example()
        for fields in (("temporal",), ("object", "temporal"), self.joint.OPTIONAL_FIELDS):
            with self.subTest(fields=fields):
                result = self.subject.compose_presence_scores(source, parent, adapted, fields=fields)
                for field in self.joint.OPTIONAL_FIELDS:
                    donor = parent if field in fields else adapted
                    self.assertEqual(result["occurrence"]["scores"]["presence_logits"][field], donor["scores"]["presence_logits"][field])
                self.assertEqual(result["provenance"]["routed_fields"], list(fields))

    def test_invalid_field_profiles_reject(self):
        source, parent, adapted = self.late_example()
        for fields in ((), ["temporal"], "temporal", ("actor",), ("action",), ("unknown",),
                       ("temporal", "temporal"), ("temporal", "object"), ("temporal", None), True):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.subject.compose_presence_scores(source, parent, adapted, fields=fields)

    def test_source_identity_and_complete_tokens_reject(self):
        source, parent, adapted = self.late_example()
        for which in ("parent", "adapted"):
            for fault in ("id", "source", "offset", "text", "missing_token"):
                with self.subTest(which=which, fault=fault):
                    values = {"parent": copy.deepcopy(parent), "adapted": copy.deepcopy(adapted)}
                    target = values[which]
                    if fault == "id": target["id"] = "foreign"
                    elif fault == "source": target["source_sha256"] = "0" * 64
                    elif fault == "offset": target["scores"]["tokens"][0]["end"] += 1
                    elif fault == "text": target["scores"]["tokens"][0]["text"] = "foreign"
                    else: target["scores"]["tokens"].pop()
                    with self.assertRaises(ValueError):
                        self.subject.compose_presence_scores(source, values["parent"], values["adapted"])
        for invalid in ("", "  ", None, source + " different"):
            with self.subTest(source=invalid), self.assertRaises(ValueError):
                self.subject.compose_presence_scores(invalid, parent, adapted)

    def test_malformed_occurrence_and_scores_reject(self):
        source, parent, adapted = self.late_example()
        for fault in ("extra_occurrence", "missing_occurrence", "empty_id", "bool_id", "extra_scores", "extra_presence", "nan", "overflow", "nonbinary32", "bool_logit"):
            with self.subTest(fault=fault):
                target = copy.deepcopy(parent)
                if fault == "extra_occurrence": target["provenance"] = {}
                elif fault == "missing_occurrence": del target["source_sha256"]
                elif fault == "empty_id": target["id"] = "  "
                elif fault == "bool_id": target["id"] = True
                elif fault == "extra_scores": target["scores"]["unexpected"] = []
                elif fault == "extra_presence": target["scores"]["presence_logits"]["actor"] = [0.0, 1.0]
                else:
                    target["scores"]["presence_logits"]["temporal"][0] = {"nan": float("nan"), "overflow": 1e100, "nonbinary32": .1, "bool_logit": True}[fault]
                with self.assertRaises(ValueError):
                    self.subject.compose_presence_scores(source, target, adapted)

    def test_full_validation_includes_unused_parent_and_adapted_heads(self):
        source, parent, adapted = self.late_example()
        for which in ("parent", "adapted"):
            for component in ("modality_logits", "presence_logits", "start_logits", "end_logits"):
                with self.subTest(which=which, component=component):
                    values = {"parent": copy.deepcopy(parent), "adapted": copy.deepcopy(adapted)}
                    scores = values[which]["scores"]
                    vector = (scores[component] if component == "modality_logits" else
                              scores[component]["object" if component == "presence_logits" else "actor"])
                    vector[0] = float("nan")
                    with self.assertRaises(ValueError):
                        self.subject.compose_presence_scores(source, values["parent"], values["adapted"])

    def test_every_unrouted_head_retains_binary32_payload(self):
        source, parent, adapted = self.late_example()
        adapted["scores"]["modality_logits"][0] = -0.0
        adapted["scores"]["presence_logits"]["conditions"][0] = -0.0
        adapted["scores"]["start_logits"]["action"][0] = -0.0
        adapted["scores"]["end_logits"]["object"][0] = -0.0
        composed = self.subject.compose_presence_scores(source, parent, adapted)["occurrence"]["scores"]
        binary = lambda values: b"".join(struct.pack("!f", value) for value in values)
        self.assertEqual(binary(composed["modality_logits"]), binary(adapted["scores"]["modality_logits"]))
        for component in ("presence_logits", "start_logits", "end_logits"):
            for field, vector in composed[component].items():
                expected = parent if component == "presence_logits" and field == "temporal" else adapted
                self.assertEqual(binary(vector), binary(expected["scores"][component][field]))

    def test_inputs_outputs_and_provenance_are_fully_detached(self):
        source, parent, adapted = self.late_example()
        before = copy.deepcopy((parent, adapted))
        result = self.subject.compose_presence_scores(source, parent, adapted)
        self.assertEqual((parent, adapted), before)
        result["occurrence"]["scores"]["presence_logits"]["temporal"][0] = 77.0
        result["occurrence"]["scores"]["tokens"][0]["text"] = "changed"
        result["occurrence"]["scores"]["start_logits"]["actor"][0] = 77.0
        self.assertEqual((parent, adapted), before)
        snapshots = result["provenance"]["presence_components"]["temporal"]
        self.assertEqual(snapshots["composed"]["logits"], before[0]["scores"]["presence_logits"]["temporal"])
        snapshots["parent"]["logits"][0] = 88.0
        snapshots["composed"]["logits"][1] = 88.0
        result["provenance"]["routed_fields"].append("object")
        self.assertEqual((parent, adapted), before)
        self.assertEqual(snapshots["adapted"]["logits"], adapted["scores"]["presence_logits"]["temporal"])
        self.assertEqual(result["occurrence"]["scores"]["presence_logits"]["temporal"][1], 5.0)

    def test_digest_binds_both_donors_and_composed_occurrence(self):
        source, parent, adapted = self.late_example()
        result = self.subject.compose_presence_scores(source, parent, adapted)
        for role, value in (("parent", parent), ("adapted", adapted), ("composed", result["occurrence"])):
            self.assertEqual(result["provenance"][role + "_occurrence_sha256"], hashlib.sha256(self.joint._raw(value)).hexdigest())
        self.assertIsNone(result["provenance"]["model_checkpoint"])
        self.assertIsNone(result["provenance"]["semantic_accuracy"])
        for flag in self.joint.FALSE:
            self.assertIs(result["provenance"][flag], False)


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    unittest.main(verbosity=2)
