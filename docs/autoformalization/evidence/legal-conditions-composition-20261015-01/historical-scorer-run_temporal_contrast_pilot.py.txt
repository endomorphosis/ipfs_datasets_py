"""Guarded, source-only authored temporal-role contrast experiment.

This script must run under the unchanged reviewed resource guardian. It forks
the genuine legacy span state of one exact historical warm parent, copies its
weights, and starts fresh Adam for each explicitly different data manifest.
Authored references are engineering declarations, never statutory gold.
"""
from contextlib import ExitStack
import argparse
import ctypes.util
import hashlib
import importlib
import importlib.abc
import itertools
import json
import math
import os
from pathlib import Path
import random
import re
import stat
import struct
import sys
import time
from types import ModuleType
from unittest.mock import patch

SCHEMA = "temporal-contrast-source-only-two-arm-plan/v1"
DATA_SCHEMA = "temporal-contrast-training-export/v1"
FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
OPTIONAL = FIELDS[2:]
FALSE = dict(qualified=False, admitted=False, formalized=False, proof_authority=False,
             semantic_correctness_verified=False, promotion_performed=False)
STATE = dict(created_output=None, stage="preparation", completed_updates=0,
             saved_states=[], in_progress_arm_updates_unknown=False,
             update_counter_scope="returned completed prefixes only; exceptions inside fit can leave partial updates unknown")
PLAN_FIELDS = {
    "schema", "package_root", "runner_path", "guardian_path", "source_owner_pins", "artifacts",
    "ctypes_dl_resolution", "historical_parent_file_pin", "historical_parent_canonical_sha256",
    "parent_base_canonical_sha256", "parent_model_state_sha256", "data_export", "arms",
    "tuning_population", "tuning_manifest_sha256", "diagnostic_panels", "context_contract",
    "resource_contract", "forbidden_reference_paths", "training_seconds_per_arm", "seed", "dimension",
    "latent_enabled", "encoder_execution_planned", "semantic_gold", "independent_semantic_holdout",
    "checkpoint_selection_executed", "default_promotion", "Lake_executed", "inert_audit_pin",
}


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def closed(value, keys, label):
    require(type(value) is dict and set(value) == set(keys), "closed " + label + " required")


def f32(value):
    require(type(value) in (int, float) and math.isfinite(value), "finite scalar score required")
    try:
        result = struct.unpack("!f", struct.pack("!f", value))[0]
    except (OverflowError, struct.error) as error:
        raise ValueError("finite float32 arithmetic required") from error
    require(math.isfinite(result), "finite float32 arithmetic required")
    return result


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path, "absolute contained regular path required")
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and not path.is_symlink(), "regular artifact required")
    result = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        opening = os.fstat(stream.fileno())
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(block)
            result.update(block)
        closing = os.fstat(stream.fileno())
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (opening.st_dev, opening.st_ino, opening.st_size, opening.st_mtime_ns) ==
            (closing.st_dev, closing.st_ino, closing.st_size, closing.st_mtime_ns)
            and size == before.st_size, "artifact changed during read")
    return dict(path=str(path), bytes=size, sha256=result.hexdigest())


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    raw = Path(path).read_bytes()
    require(len(raw) <= 128 * 1024 * 1024, "bounded JSON required")
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return pin(Path(path))


def bootstrap(root):
    require(not any(name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py.")
                    for name in sys.modules), "fresh numerical process required")
    sys.path.insert(0, str(root))
    for name in ("ipfs_datasets_py", "ipfs_datasets_py.logic", "ipfs_datasets_py.logic.legal_ir",
                 "ipfs_datasets_py.logic.formalization", "ipfs_datasets_py.logic.formalization.autoencoder",
                 "ipfs_datasets_py.optimizers", "ipfs_datasets_py.optimizers.logic_theorem_optimizer",
                 "ipfs_datasets_py.utils"):
        module = ModuleType(name)
        module.__path__ = [str(root.joinpath(*name.split(".")))]
        sys.modules[name] = module


class NoEncoder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"transformers", "sentence_transformers"}:
            raise AssertionError("encoder/teacher import forbidden: " + fullname)
        return None


def owner_origins(plan):
    observed = []
    for name, module in list(sys.modules.items()):
        if not (name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py.")):
            continue
        if not getattr(module, "__file__", None):
            continue  # Explicit namespace bootstrap is recorded separately.
        require(name in plan["source_owner_pins"], "unfrozen package producer: " + name)
        expected = plan["source_owner_pins"][name]
        require(Path(module.__file__).resolve() == Path(expected["path"])
                and pin(expected["path"]) == expected, "package producer origin or bytes differ: " + name)
        observed.append(name)
    for name in ("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_formula",
                 "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_continuation",
                 "ipfs_datasets_py.logic.legal_ir.joint_span_selection",
                 "ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture"):
        require(name in observed, "required loaded owner missing: " + name)
    return sorted(observed)


def schedule(examples, steps, *, seed=1729, batch_size=12):
    epoch = cursor = 0
    result = []
    for _ in range(steps):
        order = list(range(len(examples)))
        random.Random(seed + epoch).shuffle(order)
        indices = order[cursor:cursor + batch_size]
        result.append([examples[index]["id"] for index in indices])
        cursor += len(indices)
        if cursor == len(examples):
            epoch, cursor = epoch + 1, 0
    return dict(batch_ids=result, batch_ids_sha256=digest(result),
                final_progress=dict(epochs_completed=epoch, row_cursor=cursor, optimizer_steps=steps))


def validate_plan(plan):
    closed(plan, PLAN_FIELDS, "experiment plan")
    require(plan["schema"] == SCHEMA and plan["runner_path"] == str(Path(__file__).resolve()),
            "exact runner/plan required")
    require(plan["seed"] == 1729 and type(plan["seed"]) is int
            and plan["dimension"] == 384 and type(plan["dimension"]) is int
            and plan["latent_enabled"] is False, "source-only dormant384 experiment required")
    require(all(plan[name] is False for name in ("encoder_execution_planned", "semantic_gold",
            "independent_semantic_holdout", "checkpoint_selection_executed", "default_promotion", "Lake_executed")),
            "unqualified engineering experiment only")
    require(plan["resource_contract"] == dict(cpu_slots=2, rss_mib=1536, child_slots=1,
            storage_bytes=200000000, wall_seconds=300), "unchanged resource contract required")
    require(type(plan["training_seconds_per_arm"]) in (int, float)
            and math.isfinite(plan["training_seconds_per_arm"])
            and 0 < plan["training_seconds_per_arm"] <= 32, "training allowance exceeds prior envelope")
    require(type(plan["arms"]) is list and len(plan["arms"]) == 2, "two bounded arms required")
    for arm, name, count in zip(plan["arms"], ("control", "contrast"), (108, 168), strict=True):
        closed(arm, {"name", "training_population", "training_manifest_sha256", "training_count", "new_steps"}, "arm")
        require(arm["name"] == name and arm["training_population"] == name + "_train"
                and arm["training_count"] == count and type(arm["training_count"]) is int
                and arm["new_steps"] == 32 and type(arm["new_steps"]) is int, "frozen arm recipe differs")
    require(plan["tuning_population"] == "old_tune", "unchanged old authored tuning required")
    expected = [("old_tune", 96, True), ("fresh_tune", 36, True),
                ("fresh_challenge", 36, True), ("law", 8, False)]
    require(type(plan["diagnostic_panels"]) is list and len(plan["diagnostic_panels"]) == 4,
            "all four panels required")
    for panel, (name, count, reference) in zip(plan["diagnostic_panels"], expected, strict=True):
        closed(panel, {"name", "population", "count", "has_authored_reference", "provenance"}, "diagnostic panel")
        require(panel["name"] == panel["population"] == name and panel["count"] == count
                and type(panel["count"]) is int and panel["has_authored_reference"] is reference,
                "complete panel recipe differs")
        require(panel["provenance"] == ("authored_synthetic_not_legal_authority" if reference
                else "previously_exposed_unreviewed_law_source_only"), "ambiguous panel provenance")
    require(type(plan["forbidden_reference_paths"]) is list and plan["forbidden_reference_paths"],
            "explicit forbidden original target containers required")
    require(not set(plan["artifacts"]) & set(plan["forbidden_reference_paths"]), "forbidden input is admitted")
    for path in (plan["runner_path"], plan["guardian_path"], plan["data_export"]["path"],
                 plan["historical_parent_file_pin"]["path"], plan["inert_audit_pin"]["path"]):
        require(path in plan["artifacts"], "required artifact absent from closed bindings")


def validate_authored_pairs(rows, metadata, *, require_pairs=True):
    """Pure pre-fit pair custody; declarations do not establish legal meaning."""
    require(type(rows) is list and type(metadata) is list and len(rows) == len(metadata), "pair row/metadata count differs")
    require(type(require_pairs) is bool, "explicit pair requirement needed")
    pairs = {}
    seen = set()
    for row, meta in zip(rows, metadata, strict=True):
        closed(meta, {"id", "class_name", "group_id", "pair_id", "pair_variant"}, "authored pair metadata")
        require(row["id"] == meta["id"] and row["id"] not in seen, "pair occurrence order or uniqueness differs")
        seen.add(row["id"])
        require(type(meta["class_name"]) is str and meta["class_name"], "pair class missing")
        require(all(value is None or type(value) is str and value for value in
                    (meta["group_id"], meta["pair_id"], meta["pair_variant"])), "pair identity type differs")
        require((meta["group_id"] is None) == (meta["pair_id"] is None) == (meta["pair_variant"] is None), "partial pair identity")
        if meta["pair_id"] is None:
            require(not require_pairs, "fresh authored row has no pair")
            continue
        require(meta["pair_variant"] in ("temporal_present", "temporal_absent"), "unknown authored pair variant")
        reference = row["canonical_ir"]
        closed(reference, {"rules"}, "authored pair reference")
        require(type(reference["rules"]) is list and len(reference["rules"]) == 1, "one authored pair rule required")
        rule = reference["rules"][0]
        closed(rule, {"modality", *FIELDS}, "authored pair rule")
        require(rule["modality"] in ("O", "P", "F")
                and all(type(rule[field]) is str for field in FIELDS[:3])
                and rule["actor"] and rule["action"]
                and all(type(rule[field]) is list and len(rule[field]) <= 1
                        and all(type(value) is str and value for value in rule[field]) for field in FIELDS[3:]),
                "flat copied-span authored pair reference required")
        require((meta["pair_variant"] == "temporal_present") is bool(rule["temporal"]), "pair/reference temporal presence differs")
        pairs.setdefault(meta["pair_id"], []).append((row, meta, rule))
    group_classes = {}
    for pair_id, members in pairs.items():
        require(len(members) == 2 and {meta["pair_variant"] for _, meta, _ in members} ==
                {"temporal_present", "temporal_absent"}, "incomplete/repeated authored pair")
        require(len({meta["group_id"] for _, meta, _ in members}) ==
                len({meta["class_name"] for _, meta, _ in members}) == 1, "authored pair group/class differs")
        require(len({digest({key: value for key, value in rule.items() if key != "temporal"})
                     for _, _, rule in members}) == 1, "authored pair reference changes beyond temporal")
        group = members[0][1]["group_id"]
        class_name = members[0][1]["class_name"]
        require(group not in group_classes or group_classes[group] == class_name, "authored group class differs")
        group_classes[group] = class_name
    return dict(rows=len(rows), pairs=len(pairs), group_count=len(group_classes),
                provided_pair_geometry_valid=True, semantic_gold=False, **FALSE)


def validate_data(plan, data):
    closed(data, {"schema", "populations", "metadata", "semantic_gold", "provenance"}, "data export")
    require(data["schema"] == DATA_SCHEMA and data["semantic_gold"] is False
            and data["provenance"] == "authored_engineering_and_unreviewed_law_diagnostics_separate", "data provenance differs")
    names = {"control_train", "contrast_train", "old_tune", "fresh_tune", "fresh_challenge", "law"}
    require(type(data["populations"]) is dict and set(data["populations"]) == names
            and type(data["metadata"]) is dict and set(data["metadata"]) == names - {"law"}, "closed populations required")
    for name, rows in data["populations"].items():
        require(type(rows) is list and len(rows) == {"control_train": 108, "contrast_train": 168,
                "old_tune": 96, "fresh_tune": 36, "fresh_challenge": 36, "law": 8}[name], "population count differs")
        seen = set()
        for row in rows:
            closed(row, {"id", "source_text", "latent"} | ({"canonical_ir"} if name != "law" else set()), "data row")
            require(type(row["id"]) is str and row["id"] and row["id"] not in seen, "duplicate/missing occurrence ID")
            seen.add(row["id"])
            require(type(row["source_text"]) is str and row["source_text"].strip(), "empty source")
            require(type(row["latent"]) is list and len(row["latent"]) == 384
                    and all(type(v) in (int, float) and math.isfinite(v) and abs(v) <= 3.4028234e38
                            for v in row["latent"]), "finite 384-vector required")
        if name == "law":
            continue
        metadata = data["metadata"][name]
        require(type(metadata) is list and [m["id"] for m in metadata] == [r["id"] for r in rows], "metadata occurrence order differs")
        for meta in metadata:
            closed(meta, {"id", "class_name", "group_id", "pair_id", "pair_variant"}, "authored metadata")
            require(type(meta["class_name"]) is str and meta["class_name"], "class declaration missing")
            require(all(value is None or type(value) is str and value for value in
                        (meta["group_id"], meta["pair_id"], meta["pair_variant"])), "pair/group declaration differs")
            require((meta["group_id"] is None) == (meta["pair_id"] is None) == (meta["pair_variant"] is None), "partial pair identity")
            require(meta["pair_variant"] in (None, "temporal_present", "temporal_absent"), "unknown authored pair variant")
    for arm in plan["arms"]:
        require(digest(data["populations"][arm["training_population"]]) == arm["training_manifest_sha256"], "training manifest differs")
    require(digest(data["populations"]["old_tune"]) == plan["tuning_manifest_sha256"], "old tuning manifest differs")
    require(data["populations"]["control_train"][:96] == data["populations"]["contrast_train"][:96]
            and data["metadata"]["control_train"][:96] == data["metadata"]["contrast_train"][:96], "fixed96 rehearsal differs")
    contrast_fresh = data["populations"]["contrast_train"][96:]
    plain = [row for row, meta in zip(contrast_fresh, data["metadata"]["contrast_train"][96:], strict=True)
             if meta["class_name"] == "plain_deadline"]
    require(len(plain) == 12 and plain == data["populations"]["control_train"][96:], "control must contain exactly fresh plain12")
    plain_metadata = [meta for meta in data["metadata"]["contrast_train"][96:] if meta["class_name"] == "plain_deadline"]
    require(plain_metadata == data["metadata"]["control_train"][96:], "fresh control metadata differs from declared plain subset")
    for name in ("control_train", "contrast_train", "old_tune"):
        legacy = data["metadata"][name][:96]
        require(all(meta["class_name"] == "legacy_authored" and meta["group_id"] is None
                    and meta["pair_id"] is None and meta["pair_variant"] is None for meta in legacy), "legacy metadata misclassified as fresh")
    validate_authored_pairs(data["populations"]["control_train"][96:], data["metadata"]["control_train"][96:])
    for name in ("contrast_train", "fresh_tune", "fresh_challenge"):
        offset = 96 if name == "contrast_train" else 0
        validate_authored_pairs(data["populations"][name][offset:], data["metadata"][name][offset:])
        require(all(m["group_id"] is not None for m in data["metadata"][name][offset:]), "fresh split has missing groups")
        require(all(row["latent"] == [0.] * 384 for row in data["populations"][name][offset:]), "fresh disabled latent must be explicit zeros")
    for left, right in itertools.combinations(("contrast_train", "fresh_tune", "fresh_challenge", "old_tune"), 2):
        for key in ("id", "source_text"):
            require(not {r[key] for r in data["populations"][left]} & {r[key] for r in data["populations"][right]}, "split occurrence/source overlap")
        for key in ("group_id", "pair_id"):
            a = {m[key] for m in data["metadata"][left] if m[key] is not None}
            b = {m[key] for m in data["metadata"][right] if m[key] is not None}
            require(not a & b, "split group/pair overlap")


def captured_inference(torch, span, warm, checkpoint, rows, *, control="none"):
    """Capture untouched heads from the same target-free public inference call."""
    decoder = warm.SpanContinuationDecoder(checkpoint)
    ambient = torch.get_rng_state().clone()
    model_before = {name: value.tolist() for name, value in decoder.model.state_dict().items()}
    require(not decoder.model._forward_hooks and not decoder.model._forward_pre_hooks, "pre-existing model hooks")
    sources = [{key: row[key] for key in ("id", "source_text", "latent")} for row in rows]
    require(control in ("none", "zero", "disabled", "rotate"), "unknown latent control")
    tokens = [span.tokenize_source(row["source_text"]) for row in sources]
    captures = []

    def hook(module, incoming, output):
        position = len(captures)
        require(module is decoder.model and position < len(sources), "unexpected extra source forward")
        count = len(tokens[position])
        closed(output, {"modality", "presence", "start", "end"}, "same-forward output")
        for field, shape in {"modality": (1, 3), "presence": (1, 4, 2), "start": (1, 6, count), "end": (1, 6, count)}.items():
            value = output[field]
            require(torch.is_tensor(value) and tuple(value.shape) == shape and value.dtype == torch.float32
                    and value.device.type == "cpu" and not value.requires_grad and bool(torch.isfinite(value).all()), "finite CPU heads differ")
        captures.append(dict(schema="joint-source-span-scores/v1",
            tokens=[{key: token[key] for key in ("text", "start", "end")} for token in tokens[position]],
            modality_logits=output["modality"][0].tolist(),
            presence_logits=dict(zip(OPTIONAL, output["presence"][0].tolist(), strict=True)),
            start_logits=dict(zip(FIELDS, output["start"][0].tolist(), strict=True)),
            end_logits=dict(zip(FIELDS, output["end"][0].tolist(), strict=True))))
        return None

    handle = decoder.model.register_forward_hook(hook)
    try:
        with torch.random.fork_rng(devices=[]):
            report = decoder.decode_formal_logic([r["source_text"] for r in sources], [r["latent"] for r in sources],
                                                latent_ablation=control)
    finally:
        handle.remove()
    require(len(captures) == len(rows) == len(report["rows"]), "complete same-forward coverage required")
    require(not decoder.model._forward_hooks and model_before == {name: value.tolist()
            for name, value in decoder.model.state_dict().items()} and torch.equal(ambient, torch.get_rng_state()), "inference changed hooks/model/RNG")
    observer = sys.modules["ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture"]
    for source, scores, raw in zip(sources, captures, report["rows"], strict=True):
        require(raw["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest(), "raw source identity differs")
        observer._verify_greedy(source["source_text"], scores, raw)
    return dict(schema="temporal-contrast-target-free-head-capture/v1", inference=report,
                occurrences=[dict(id=source["id"], source_sha256=hashlib.sha256(source["source_text"].encode()).hexdigest(),
                                  scores=scores) for source, scores in zip(sources, captures, strict=True)],
                actual_source_forwards=len(rows), extra_capture_forwards=0, model_weights_unchanged=True,
                original_greedy_observations_verified=True, ambient_CPU_RNG_preserved=True,
                target_access=False, teacher_forcing=False, **FALSE)


def source_only_parity(torch, span, warm, checkpoint, rows, out, state_name):
    """Disabled-placeholder invariance; no genuine latent comparison is claimed."""
    sources = [{key: row[key] for key in ("id", "source_text", "latent")} for row in rows[:2]]
    alternate = [dict(row, latent=[.25 if index == 0 else -.25] * 384) for index, row in enumerate(sources)]
    controls = [("zeros", sources, "none"), ("alternate_placeholders", alternate, "none"),
                ("disabled", alternate, "disabled"), ("rotated_placeholders", alternate, "rotate")]
    captures = []
    projection = None
    for name, inputs, control in controls:
        report = captured_inference(torch, span, warm, checkpoint, inputs, control=control)
        observed = [dict(scores=capture["scores"], raw={key: raw.get(key) for key in
                    ("status", "reason", "canonical_ir", "span_diagnostics", "minimum_decision_logit_margin")})
                    for capture, raw in zip(report["occurrences"], report["inference"]["rows"], strict=True)]
        if projection is None:
            projection = observed
        require(observed == projection, "disabled source-only model changed under placeholder control")
        captures.append(dict(name=name, control=control, report=write(out / (state_name + "-parity-" + name + ".json"), report)))
    return write(out / (state_name + "-parity.json"), dict(schema="source-only-dormant384-placeholder-parity/v1",
                 passed=True, controls=captures, source_count=2, score_and_greedy_decisions_bit_equal=True,
                 genuine_latent_semantics_tested=False, actual_encoder_calls=0, **FALSE))


def score_panel(rows, metadata, raw, joint_rows):
    """Pure post-inference scoring; references never enter the model call."""
    scored = []
    classes = {}
    for incoming, meta, raw_row, capture, joint_row in zip(rows, metadata, raw["inference"]["rows"], raw["occurrences"], joint_rows, strict=True):
        require(incoming["id"] == meta["id"] == capture["id"] == joint_row["id"], "score occurrence join differs")
        closed(meta, {"id", "class_name", "group_id", "pair_id", "pair_variant"}, "score metadata")
        source_hash = hashlib.sha256(incoming["source_text"].encode()).hexdigest()
        require(raw_row["source_sha256"] == capture["source_sha256"] == joint_row["result"]["source_sha256"] == source_hash,
                "saved score/source identity differs")
        require(joint_row["result"]["scores_sha256"] == digest(capture["scores"]), "joint score identity differs")
        expected_tokens = [dict(text=match.group(), start=match.start(), end=match.end())
                           for match in re.finditer(r"\w+|[^\w\s]", incoming["source_text"], re.UNICODE)]
        require(capture["scores"]["tokens"] == expected_tokens, "saved score/source token geometry differs")
        reference = incoming["canonical_ir"]
        require(type(reference) is dict and set(reference) == {"rules"} and len(reference["rules"]) == 1, "one authored rule required")
        target = reference["rules"][0]
        closed(target, {"modality", *FIELDS}, "authored score rule")
        scores = capture["scores"]["presence_logits"]["temporal"]
        require(type(scores) is list and len(scores) == 2
                and all(type(v) is float and f32(v) == v for v in scores), "exact finite temporal float32 heads required")
        predicted = None if abs(f32(scores[1] - scores[0])) <= 1e-7 else scores[1] > scores[0]
        expected = bool(target["temporal"])
        require((meta["group_id"] is None) == (meta["pair_id"] is None) == (meta["pair_variant"] is None), "partial pair identity")
        require(meta["pair_variant"] in (None, "temporal_present", "temporal_absent"), "unknown authored pair variant")
        require(meta["pair_variant"] is None or (meta["pair_variant"] == "temporal_present") is expected,
                "authored pair/reference temporal presence differs")
        candidate = raw_row["canonical_ir"] if raw_row["status"] == "decoded" else None
        joint_candidate = joint_row["result"].get("canonical_ir")
        exact = candidate == reference
        joint_exact = joint_candidate == reference
        candidate_rule = candidate["rules"][0] if candidate is not None else None
        roles = {field: candidate_rule is not None and candidate_rule[field] == target[field] for field in FIELDS}
        joint_rule = joint_candidate["rules"][0] if joint_candidate is not None else None
        joint_roles = {field: joint_rule is not None and joint_rule[field] == target[field] for field in FIELDS}
        result = dict(id=incoming["id"], class_name=meta["class_name"], group_id=meta["group_id"],
            pair_id=meta["pair_id"], pair_variant=meta["pair_variant"], raw_decoded=candidate is not None,
            reference_non_temporal_sha256=digest({key: value for key, value in target.items() if key != "temporal"}),
            raw_exact_ir=exact, joint_exact_ir=joint_exact, role_exact=roles, joint_role_exact=joint_roles,
            modality_exact=candidate_rule is not None and candidate_rule["modality"] == target["modality"],
            joint_modality_exact=joint_rule is not None and joint_rule["modality"] == target["modality"],
            expected_temporal_presence=expected, predicted_temporal_presence=predicted,
            temporal_presence_correct=predicted is expected, temporal_false_positive=predicted is True and not expected,
            temporal_false_negative=predicted is False and expected, temporal_ambiguous=predicted is None)
        scored.append(result)
        bucket = classes.setdefault(meta["class_name"], dict(rows=0, raw_decoded=0, raw_exact_ir=0,
                joint_exact_ir=0, temporal_presence_correct=0, temporal_false_positive=0,
                temporal_false_negative=0, temporal_ambiguous=0, reference_temporal_present=0))
        bucket["rows"] += 1
        bucket["reference_temporal_present"] += int(expected)
        for key in tuple(bucket):
            if key not in ("rows", "reference_temporal_present"):
                bucket[key] += int(result[key])
    pairs = {}
    for row in scored:
        if row["pair_id"] is not None:
            pairs.setdefault(row["pair_id"], []).append(row)
    paired = []
    for pair_id, members in sorted(pairs.items()):
        require(len(members) == 2 and {r["pair_variant"] for r in members} == {"temporal_present", "temporal_absent"},
                "incomplete/repeated authored pair")
        require(len({r["group_id"] for r in members}) == len({r["class_name"] for r in members}) == 1,
                "authored pair group/class differs")
        require(len({r["reference_non_temporal_sha256"] for r in members}) == 1,
                "authored pair reference changes beyond temporal")
        pair_comparisons = list(itertools.combinations(members, 2))
        paired.append(dict(pair_id=pair_id, row_ids=[r["id"] for r in members], comparisons=len(pair_comparisons),
            raw_both_exact=sum(a["raw_exact_ir"] and b["raw_exact_ir"] for a, b in pair_comparisons),
            joint_both_exact=sum(a["joint_exact_ir"] and b["joint_exact_ir"] for a, b in pair_comparisons),
            temporal_both_correct=sum(a["temporal_presence_correct"] and b["temporal_presence_correct"] for a, b in pair_comparisons),
            all_raw_exact=all(r["raw_exact_ir"] for r in members), all_temporal_correct=all(r["temporal_presence_correct"] for r in members)))
    return dict(schema="authored-temporal-contrast-panel-score/v1", rows=scored, classes=classes,
                row_count=len(scored), raw_exact_ir=sum(r["raw_exact_ir"] for r in scored),
                joint_exact_ir=sum(r["joint_exact_ir"] for r in scored), raw_abstentions=sum(not r["raw_decoded"] for r in scored),
                temporal_presence_correct=sum(r["temporal_presence_correct"] for r in scored),
                temporal_false_positives=sum(r["temporal_false_positive"] for r in scored),
                temporal_false_negatives=sum(r["temporal_false_negative"] for r in scored),
                temporal_ambiguous=sum(r["temporal_ambiguous"] for r in scored), pairwise_consistency=paired,
                role_exact_counts={field: sum(row["role_exact"][field] for row in scored) for field in FIELDS},
                joint_role_exact_counts={field: sum(row["joint_role_exact"][field] for row in scored) for field in FIELDS},
                modality_exact=sum(row["modality_exact"] for row in scored),
                joint_modality_exact=sum(row["joint_modality_exact"] for row in scored),
                reference_scope="caller-authored engineering targets only", semantic_accuracy=None,
                used_for_updates_or_selection=False, **FALSE)


def diagnostics(torch, span, warm, joint, checkpoint, data, plan, out, state_name):
    reports = []
    for panel in plan["diagnostic_panels"]:
        rows = data["populations"][panel["population"]]
        raw = captured_inference(torch, span, warm, checkpoint, rows)
        raw_pin = write(out / (state_name + "-" + panel["name"] + "-raw.json"), raw)
        joint_rows = [dict(id=incoming["id"], result=joint.select_joint_spans(incoming["source_text"], capture["scores"],
                      top_k=8, max_search_nodes=50000)) for incoming, capture in zip(rows, raw["occurrences"], strict=True)]
        joint_pin = write(out / (state_name + "-" + panel["name"] + "-joint.json"), dict(
            schema="temporal-contrast-joint-panel/v1", rows=joint_rows, top_k=8, max_search_nodes=50000,
            raw_greedy_preserved=True, learned_presence_and_modality_fixed=True,
            semantic_accuracy=None, used_for_updates_or_selection=False, **FALSE))
        score = None
        if panel["has_authored_reference"]:
            score = write(out / (state_name + "-" + panel["name"] + "-score.json"),
                          score_panel(rows, data["metadata"][panel["name"]], raw, joint_rows))
        reports.append(dict(name=panel["name"], row_count=len(rows), raw=raw_pin, joint=joint_pin,
                            score=score, has_authored_reference=panel["has_authored_reference"], provenance=panel["provenance"]))
    return reports


def main(args):
    started = time.monotonic()
    plan = read(args.plan)
    validate_plan(plan)
    for path, expected in plan["artifacts"].items():
        require({key: pin(path)[key] for key in ("bytes", "sha256")} == expected, "opening artifact differs: " + path)
    for field in ("data_export", "historical_parent_file_pin", "inert_audit_pin"):
        require(pin(plan[field]["path"]) == plan[field], "input pin differs: " + field)
    out = Path(args.output)
    require(out.is_absolute() and out.resolve() == out and not out.exists(), "fresh absolute output required")
    out.mkdir(mode=0o700)
    STATE["created_output"] = str(out)
    forbidden = set(plan["forbidden_reference_paths"])

    def audit(event, values):
        if event.startswith(("subprocess.", "os.exec", "os.spawn", "socket.")) or event == "os.system":
            raise AssertionError("network/process event forbidden: " + event)
        if event == "open" and isinstance(values[0], (str, bytes)):
            require(str(Path(os.fsdecode(values[0])).absolute()) not in forbidden, "forbidden original target container")

    sys.addaudithook(audit)
    sys.meta_path.insert(0, NoEncoder())
    bootstrap(Path(plan["package_root"]))
    span = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_formula")
    warm = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_continuation")
    joint = importlib.import_module("ipfs_datasets_py.logic.legal_ir.joint_span_selection")
    importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture")
    opening_owners = owner_origins(plan)
    data = read(plan["data_export"]["path"])
    validate_data(plan, data)
    # The complete historical file enters only this admitted numerical child.
    historical = read(plan["historical_parent_file_pin"]["path"])
    require(digest(historical) == plan["historical_parent_canonical_sha256"], "historical canonical identity differs")
    parent = historical["base_checkpoint"]
    require(digest(parent) == plan["parent_base_canonical_sha256"]
            and digest(parent["model_state"]) == plan["parent_model_state_sha256"], "genuine saved span parent differs")
    require(parent["schema"] == span.SCHEMA and parent["config"]["latent_dimension"] == 384
            and parent["config"]["latent_enabled"] is False and parent["progress"] == dict(
                epochs_completed=4, row_cursor=192, optimizer_steps=400), "exact source-only400 parent required")
    pure_plans = [dict(name=arm["name"], training_count=arm["training_count"],
                  schedule=schedule(data["populations"][arm["training_population"]], 32)) for arm in plan["arms"]]
    write(out / "all-data-schedules-before-models.json", dict(arms=pure_plans, same_update_budget=True,
          same_batch_schedule=False, schedule_difference="different caller-authored data manifests and population sizes",
          parent_model_state_sha256=plan["parent_model_state_sha256"], model_imported=False, **FALSE))
    fix = plan["ctypes_dl_resolution"]
    for key in ("library_pin", "ctypes_util_pin", "cuda_pathfinder_pin"):
        require(pin(fix[key]["path"]) == fix[key], "libdl closure differs")
    require(ctypes.util.__file__ == fix["ctypes_util_pin"]["path"], "ctypes origin differs")
    queries = []
    results = []
    with ExitStack() as stack:
        def find_dl(name):
            require(name == "dl" and pin(fix["library_pin"]["path"]) == fix["library_pin"], "unlisted library query")
            queries.append(name)
            return fix["library_pin"]["path"]
        stack.enter_context(patch.object(ctypes.util, "find_library", find_dl))
        import torch
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        require(torch.__version__ == "2.13.0+cu130", "retained Torch runtime differs")
        old_tune = data["populations"]["old_tune"]
        for name, population in data["populations"].items():
            if name != "law":
                expressibility = span.audit_examples(population)
                require(expressibility["all_supported"], "unsupported authored population: " + name)

        def initial(arm):
            result = warm.build_checkpoint(parent, data["populations"][arm["training_population"]], old_tune,
                latent_enabled=False, seed=1729, context_contract=plan["context_contract"], learning_rate=.001, batch_size=12)
            require(result["initial_model_state_sha256"] == plan["parent_model_state_sha256"]
                    and result["base_checkpoint"]["progress"] == dict(epochs_completed=0, row_cursor=0, optimizer_steps=0)
                    and result["base_checkpoint"]["optimizer_state"] == dict(schema="adam-default-betas-eps/v1", parameters={}),
                    "new lineage must copy weights and start fresh Adam")
            return result

        baseline = initial(plan["arms"][0])
        baseline_parity = source_only_parity(torch, span, warm, baseline, data["populations"]["fresh_tune"], out, "baseline")
        baseline_reports = diagnostics(torch, span, warm, joint, baseline, data, plan, out, "baseline")
        write(out / "baseline.json", dict(checkpoint_sha256=warm.checkpoint_digest(baseline), panels=baseline_reports,
              parity=baseline_parity, original_parent_model_state_sha256=plan["parent_model_state_sha256"], fit_updates=0, **FALSE))
        del baseline
        for arm, prepared in zip(plan["arms"], pure_plans, strict=True):
            checkpoint = initial(arm)
            STATE.update(stage="training", arm=arm["name"], in_progress_arm_updates_unknown=True)
            trained = warm.train_decoder(checkpoint, data["populations"][arm["training_population"]], old_tune,
                                         max_steps=32, max_seconds=plan["training_seconds_per_arm"])
            STATE["in_progress_arm_updates_unknown"] = False
            actual = trained["report"]["optimizer_steps"]
            STATE["completed_updates"] += actual
            checkpoint_pin = warm.save_checkpoint(trained["checkpoint"], out / (arm["name"] + "-checkpoint.json"))
            checkpoint_pin.pop("schema")
            STATE["saved_states"].append(checkpoint_pin)
            training_pin = write(out / (arm["name"] + "-training.json"), trained["report"])
            require(actual == 32 and trained["report"]["stopped_reason"] == "step_limit"
                    and trained["checkpoint"]["base_checkpoint"]["progress"] == prepared["schedule"]["final_progress"],
                    "unequal or truncated fit: retain state, no equal-step comparison")
            STATE["stage"] = "postfit_diagnostics"
            parity = source_only_parity(torch, span, warm, trained["checkpoint"], data["populations"]["fresh_tune"], out, arm["name"])
            reports = diagnostics(torch, span, warm, joint, trained["checkpoint"], data, plan, out, arm["name"])
            results.append(dict(name=arm["name"], checkpoint=checkpoint_pin, training=training_pin,
                planned_data_schedule=prepared["schedule"], schedule_scope="frozen retained algorithm and final progress; no independent runtime batch-ID trace",
                actual_new_updates=actual, parity=parity, diagnostics=reports))
            del checkpoint, trained
    require(STATE["completed_updates"] == 64, "total completed update count differs")
    for path, expected in plan["artifacts"].items():
        require({key: pin(path)[key] for key in ("bytes", "sha256")} == expected, "closing artifact differs: " + path)
    require(digest(historical) == plan["historical_parent_canonical_sha256"], "historical object changed")
    closing_owners = owner_origins(plan)
    summary = dict(schema="temporal-contrast-source-only-two-arm-results/v1", status="completed", arms=results,
        baseline_panels=baseline_reports, baseline_parity=baseline_parity, actual_new_updates=64,
        actual_encoder_calls=0, equal_step_count=32,
        same_batch_schedule=False, same_parent_model=True, fresh_Adam_per_arm=True, inherited_optimizer_moments=False,
        parent_optimizer_steps=400, trained_dimensions=[384], latent_enabled=False,
        dimensional_scope="384D configured source-span model with dormant conditioning; no8D/768D evaluation",
        semantic_accuracy=None, legal_fidelity_qualified=False, independent_semantic_holdout=False,
        checkpoint_selection_executed=False, default_promotion=False, Lake_executed=False,
        full_third_party_import_graph_qualified=False, original_artifacts_byte_exact=True,
        opening_imported_owners=opening_owners, closing_imported_owners=closing_owners,
        ctypes_dl_resolution=dict(profile=fix, queries=queries, subprocess_fallback_executed=False),
        inert_audit_retained_not_trained=plan["inert_audit_pin"], elapsed_seconds=time.monotonic() - started,
        resource_scope="unchanged guardian: 2CPU/1536MiB/1child/200MB/300s", **FALSE)
    write(out / "summary.json", summary)
    print(json.dumps(dict(status="completed", actual_new_updates=64, actual_encoder_calls=0)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    try:
        main(parser.parse_args())
    except Exception as error:
        if STATE["created_output"]:
            write(Path(STATE["created_output"]) / "child-failure.json", dict(**STATE,
                  error_type=type(error).__name__, detail=str(error), semantic_accuracy=None, **FALSE))
        raise
