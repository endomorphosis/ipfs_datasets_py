"""Finite independent public-helper replay and training-proposal checks.

This recipe reads saved scores only. It does not reproduce the earlier full
independent scorer; that separately retained review used independent scoring
code executed from stdin. Run this recipe once against its original artifact
paths with Python -B. It never imports the experiment author's composer/scorer.
"""
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import io
import json
import math
import os
from pathlib import Path
import runpy
import stat
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parent
N4 = ROOT.parent / "legal-split-feature-20261013-01"
OUTPUT = ROOT / "code-and-plan-independent-review-v01.json"
WRITING = False
OBSERVED = {}
EXPECTED = {
    "datasets/ipfs_datasets_py/logic/legal_ir/presence_routing.py": (5564, "e443aa7e960f70da75665a08b7f699cf41828e35e6274e2bb5b62203865f2297"),
    "datasets/tests/unit/logic/legal_ir/test_presence_routing.py": (15252, "7141544d69df89d275e4a98e2e48d049c139554061bd5f0869ced321982b0f4c"),
    "datasets/docs/autoencoders/legal_temporal_presence_routing_20261013.md": (4432, "49f4f31a10937deadcaf06885dc1837f3c58ece8d3656764e7538df78fe1d6c1"),
    "workspace/implementation_plan/docs/106-legal-temporal-presence-routing-2026-10-13.md": (3158, "bfcaf4aef55f96e002381eec2963a2fb08baddca564add9c8001f32ea81a252c"),
    "temporal-presence-training-proposal-v02.md": (10585, "138b962c85519be7a9a364a2e2ac3d9ce01d04fdfc571f1b2dc3fa81ca1adce8"),
    "presence-routing-analysis-v01.json": (5157031, "284040c26ed56e3dbff94e88108d9635d49344a48be794cf7b53e1684f7d9226"),
    "presence-routing-independent-review-v01.json": (102106, "6d05160aa9cc3ab19fd49a22ea91fb5f94f89ec6117a3685731ee33bdea4bf66"),
}
FIELDS = ("object", "conditions", "exceptions", "temporal")
PANELS = ("old_tune", "fresh_tune", "fresh_challenge", "old_authored_eval", "authored_dev", "authored_eval", "law")


def require(value, message):
    if not value:
        raise AssertionError(message)


def audit(event, args):
    if event == "import":
        require(args[0].split(".")[0] not in {"torch", "numpy", "transformers", "sentence_transformers", "huggingface_hub"}, "Numerical/SDK import forbidden")
    if event.startswith(("subprocess.", "socket.", "os.exec", "os.spawn")) or event in {"os.system", "os.fork", "os.kill", "os.killpg", "os.mkdir", "os.remove", "os.rename", "os.replace", "os.unlink", "os.rmdir"}:
        raise AssertionError("No process, network or shared filesystem mutation")
    if event == "open":
        path, mode, flags = args
        write = isinstance(mode, str) and any(x in mode for x in "wax+")
        write |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if write:
            require(WRITING and isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)).absolute() == OUTPUT, "Only exclusive receipt write permitted")
    if event in {"os.chmod", "os.chown", "os.truncate", "os.utime", "os.link", "os.symlink"}:
        require(event == "os.chmod" and WRITING and Path(args[0]).absolute() == OUTPUT and args[1] == 0o444, "Only receipt freeze permitted")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read_raw(path, expected=None):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path, "Physical absolute path required")
    require("checkpoint" not in path.name and "private-runtime-snapshots" not in path.parts, "No checkpoint/private body reads")
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode) and (stat.S_ISREG(info.st_mode) if part == path else stat.S_ISDIR(info.st_mode)), "Ordinary raw input required")
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(identity(before) == identity(after), "Raw input drift")
    value = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    if expected is not None:
        require(value == {k: expected[k] for k in ("bytes", "sha256")}, "Expected input bytes differ")
        require("path" not in expected or expected["path"] == str(path), "Expected role path differs")
    require(str(path) not in OBSERVED or OBSERVED[str(path)] == value, "Input changed after opening")
    OBSERVED[str(path)] = value
    return raw


def read(path, expected=None):
    def unique(items):
        result = {}
        for k, v in items:
            require(k not in result, "Duplicate JSON key")
            result[k] = v
        return result
    raw = read_raw(path, expected)
    require(len(raw) < 16 * 1024 * 1024, "Bounded input required")
    result = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    read_raw(path, OBSERVED[str(path)])
    return result


def binary(value):
    if type(value) is dict:
        return b"".join(binary(value[k]) for k in sorted(value))
    if type(value) is list:
        return b"".join(binary(v) for v in value)
    require(type(value) in (float, int) and math.isfinite(value), "Finite scalar required")
    packed = struct.pack("!f", value)
    require(struct.unpack("!f", packed)[0] == value, "Exact binary32 required")
    return packed


class CountedResult(unittest.TextTestResult):
    successful_subtests = 0
    def addSubTest(self, test, subtest, err):
        if err is None:
            self.successful_subtests += 1
        super().addSubTest(test, subtest, err)


def main():
    global WRITING
    require(not OUTPUT.exists(), "Exclusive receipt required")
    for name, (size, sha) in EXPECTED.items():
        read_raw(ROOT / name, dict(bytes=size, sha256=sha))
    read_raw(Path(__file__).resolve())
    analysis = read(ROOT / "presence-routing-analysis-v01.json")
    independent = read(ROOT / "presence-routing-independent-review-v01.json")
    require(analysis["passed"] is True and independent["passed"] is True and independent["findings"] == [], "Qualified saved-score result required")
    freeze = read(N4 / "split-feature-output-freeze-v01.json", dict(bytes=20150, sha256="bcefd26d2b7ec9d96fd28d46ee3b6e69728d49a4cf13ababe50036a1d648c33b"))
    data = read(freeze["training_export"]["path"], freeze["training_export"])
    registration = read(freeze["registration"]["path"], freeze["registration"])
    test = runpy.run_path(str(ROOT / "datasets/tests/unit/logic/legal_ir/test_presence_routing.py"), run_name="independent_presence_test_recipe")
    case = test["PresenceRoutingTests"]
    stream = io.StringIO()
    outcome = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=CountedResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(case))
    require(outcome.wasSuccessful() and outcome.testsRun == 11 and outcome.successful_subtests == 45, "Direct standard-library tests differ")
    provenance = {(r["variant"], r["panel"], r["id"]): r for r in analysis["source_only_decision_provenance"]}
    require(len(provenance) == 1568, "Complete prior result provenance required")
    root = Path(freeze["cells"][0]["summary"]["path"]).parent
    saved = freeze["cells"][0]["results"]
    counts = {}
    loaded = {}
    case.setUpClass()
    try:
        for name, module in list(sys.modules.items()):
            if name.startswith("ipfs_datasets_py.") and name not in test["PACKAGES"]:
                require(name in registration["source_owner_pins"] or name == "ipfs_datasets_py.logic.legal_ir.presence_routing", "Unexpected producer import")
                actual_path = Path(module.__file__).resolve()
                expected = registration["source_owner_pins"].get(name)
                read_raw(actual_path, None if expected is None else {k: expected[k] for k in ("bytes", "sha256")})
                loaded[name] = dict(path=str(actual_path), **OBSERVED[str(actual_path)])
        for panel in PANELS:
            captures = {}
            for state in ("baseline", "trained"):
                path = root / (state + "-" + panel + "-raw.json")
                captures[state] = read(path, saved[str(path)])
            sources = data["diagnostic_populations"][panel]
            counts[panel] = {}
            for variant, fields in (("parent_temporal_presence", ("temporal",)), ("parent_all_optional_presence", FIELDS)):
                verified = 0
                for source, parent, adapted in zip(sources, captures["baseline"]["occurrences"], captures["trained"]["occurrences"], strict=True):
                    opening = (digest(parent), digest(adapted))
                    result = case.subject.compose_presence_scores(source["source_text"], parent, adapted, fields=fields)
                    require(set(result) == {"schema", "occurrence", "provenance"} and result["schema"] == "saved-presence-score-routing/v1", "Actual API contract differs")
                    occurrence = result["occurrence"]
                    p = result["provenance"]
                    known = provenance[variant, panel, source["id"]]
                    require(digest(occurrence["scores"]) == known["composed_scores_sha256"], "Actual helper differs from independently replayed scores")
                    require((digest(parent), digest(adapted)) == opening, "Input mutation")
                    require(p["parent_occurrence_sha256"] == opening[0] and p["adapted_occurrence_sha256"] == opening[1] and p["composed_occurrence_sha256"] == digest(occurrence), "Actual helper donor provenance differs")
                    for component in ("modality_logits", "start_logits", "end_logits"):
                        require(binary(occurrence["scores"][component]) == binary(adapted["scores"][component]), "Adapted score bytes changed")
                    for field in FIELDS:
                        donor = parent if field in fields else adapted
                        require(binary(occurrence["scores"]["presence_logits"][field]) == binary(donor["scores"]["presence_logits"][field]), "Presence donor bytes differ")
                        if field in fields:
                            c = p["presence_components"][field]
                            for role, owner in (("parent", parent), ("adapted", adapted), ("composed", occurrence)):
                                b = binary(owner["scores"]["presence_logits"][field])
                                require(binary(c[role]["logits"]) == b and c[role]["binary32_sha256"] == hashlib.sha256(b).hexdigest(), "Component provenance differs")
                    require(p["actual_owner_report"] is False and p["trained_model"] is False and p["model_checkpoint"] is None and all(p[k] is False for k in case.joint.FALSE), "Authority scope differs")
                    verified += 1
                counts[panel][variant] = verified
    finally:
        case.tearDownClass()
    require(sum(v["parent_temporal_presence"] for v in counts.values()) == sum(v["parent_all_optional_presence"] for v in counts.values()) == 392, "Complete two-route coverage required")
    rows = data["training_populations"]["mixed"]
    metadata = data["training_metadata"]["mixed"]
    require(len(rows) == len(metadata) == 168 and all(r["id"] == m["id"] for r, m in zip(rows, metadata)), "Exact training membership join required")
    require(digest(rows[:96]) == "4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995", "Original training prefix differs")
    strata = Counter()
    negative_classes = Counter()
    for i, (row, meta) in enumerate(zip(rows, metadata)):
        present = bool(row["canonical_ir"]["rules"][0]["temporal"])
        group = "legacy" if i < 96 else "authored"
        strata[group + ("_positive" if present else "_negative")] += 1
        if group == "authored" and not present:
            negative_classes[meta["class_name"]] += 1
    require(strata == dict(legacy_positive=48, legacy_negative=48, authored_positive=36, authored_negative=36), "Proposal training strata differ")
    require(negative_classes == {k: 6 for k in ("plain_deadline", "condition_duration", "exception_duration", "actor_duration_name", "object_duration_title", "condition_exception_duration")}, "Proposal authored negative class counts differ")
    train_ids = {r["id"] for r in rows}
    diagnostic_ids = {r["id"] for panel in PANELS for r in data["diagnostic_populations"][panel]}
    require(len(train_ids) == 168 and train_ids.isdisjoint(diagnostic_ids), "Training and diagnostic IDs overlap")
    positive_factor, negative_factor = Fraction(168, 2 * 48), Fraction(168, 2 * 36)
    require(positive_factor == Fraction(7, 4) and negative_factor == Fraction(7, 3) and positive_factor * 48 == negative_factor * 36 == 84, "Balanced global anchor arithmetic differs")
    proposal = read_raw(ROOT / "temporal-presence-training-proposal-v02.md").decode()
    require("L0 + (0.5 / 8) R" in proposal and "(7/4)" in proposal and "(7/3)" in proposal and "global count48" in proposal and "global count36" in proposal, "Reviewed objective declaration changed")
    for path, value in list(OBSERVED.items()):
        read_raw(Path(path), value)
    report = dict(schema="legal-temporal-presence-code-and-plan-independent-review/v1", passed=True, findings=[], observed_at_utc=datetime.now(timezone.utc).isoformat(),
        source_review=dict(full_helper_test_and_both_guides_read=True, exact_source_ID_hash_token_validation=True, unchanged_adapted_boundaries_modality_and_unrouted_presence=True, detached_binary32_component_provenance=True, no_automatic_readout_or_default_routing=True, score_validation_does_not_authenticate_producer=True),
        test_review=dict(tests=outcome.testsRun, successful_subtests=outcome.successful_subtests, failures=len(outcome.failures), errors=len(outcome.errors), output=stream.getvalue()),
        actual_helper_replay=dict(rows_per_route=392, routes=2, row_route_pairs=784, by_panel=counts, all_scores_equal_independently_verified_diagnostic=True, all_donor_component_bytes_and_provenance_verified=True, original_inputs_unchanged=True, additional_model_forwards=0),
        guide_review=dict(source_and_root_tables_match_independently_recounted_results=True, duration_false_positive_tradeoff_and_joint_coupling_accurately_described=True, law8_unscored_and_exposed_shared_templates_explicit=True, no_new_checkpoint_or_promotion_claim=True),
        proposal_review=dict(status="unimplemented_unexecuted_proposal", training_rows=168, legacy_prefix_sha256=digest(rows[:96]), training_IDs_disjoint_from_diagnostic_IDs=True, training_stratum_counts=dict(strata), authored_negative_class_counts=dict(negative_classes),
            targeted_L0="(2*modality + sum(six_legacy_facets))/8; only temporal CE/8 has an adapter gradient when all base34 tensors are frozen", auxiliary="(0.5/8) * batch_mean[(7/4)*legacy_positive*relu(1-z) + (7/3)*authored_negative*relu(1+z)]", balanced_global_group_mass=84,
            no_current_batch_eligible_count_normalization=True, CE_supervises_all_training_rows=True, selection_scope="retrospective exposed development engineering only; no automatic promotion", base_tensor_count=34, adapter_tensor_count=2, combined_tensor_count=36, inactive_adapter_rows=[0,1,2,3,4,5], trainable_adapter_rows=[6,7], numerical_storage_gradient_moment_and_parity_claims="requirements for a future qualified implementation, not executed or established by this review"),
        loaded_leaf_sources=loaded, artifacts={k: v for k, v in sorted(OBSERVED.items())}, closing_raw_pins_unchanged=True, numerical_imports=0, optimizer_updates=0, model_encoder_forwards=0, checkpoint_JSON_parses=0, network_requests=0, resource_API_calls=0, compiler_calls=0, default_promotion=False, semantic_accuracy=None)
    raw = json.dumps(report, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    require(len(raw) < 60000, "Finite receipt required")
    WRITING = True
    with OUTPUT.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    OUTPUT.chmod(0o444)
    print(json.dumps(dict(path=str(OUTPUT), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()), sort_keys=True))


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.addaudithook(audit)
    main()
