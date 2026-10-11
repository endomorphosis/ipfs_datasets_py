"""Prepare a fresh, closed Hugging Face release from saved JSON and exact bytes.

No model import, inference, fit, subprocess, network or Hub operation occurs.
All paths are explicit or closed saved-result references. Source and evidence
files are copied by bytes, then rechecked at closure. Publication remains a
separate root-owned compare-and-swap operation after independent review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

F = Path(__file__).resolve().parent
REPOSITORY = "Publicus/legal-ir-autoencoder"
PARENT_REVISION = "8279ea69452c0c72560211a1eda505ff1b1b5713"
RELEASE_PREFIX = "releases/20261011-structured-span-probability-v1"
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_PAYLOAD_BYTES = 200_000_000
MAX_FILES = 160
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SAFE = re.compile(r"[a-zA-Z0-9_.-]{1,128}\Z")
_FALSE = ("qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority",
          "semantic_correctness_verified", "promotion_performed", "publication_performed")
_NEW_OWNERS = {
    "ipfs_datasets_py.logic.legal_ir.structured_span_objective",
    "ipfs_datasets_py.logic.formalization.autoencoder.structured_span_continuation",
    "ipfs_datasets_py.logic.legal_ir.joint_span_selection",
}


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    canonical(value)
    return value


def read_bytes(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path, "canonical absolute input path required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_FILE_BYTES,
                "bounded nonempty ordinary input file required")
        raw = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
    require(len(raw) <= MAX_FILE_BYTES and len(raw) == before.st_size
            and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), "input changed while reading")
    return raw


def pin(path, raw=None):
    raw = read_bytes(path) if raw is None else raw
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def checked_ref(ref):
    require(type(ref) is dict and set(ref) == {"path", "bytes", "sha256"}, "closed saved-file reference required")
    require(type(ref["bytes"]) is int and 0 < ref["bytes"] <= MAX_FILE_BYTES
            and type(ref["sha256"]) is str and _SHA.fullmatch(ref["sha256"]), "saved-file reference bound/hash differs")
    raw = read_bytes(ref["path"])
    require(pin(ref["path"], raw) == ref, "saved artifact differs from its byte pin")
    return raw


def path_under(relative):
    require(type(relative) is str and relative and "\\" not in relative, "ordinary relative Hub path required")
    path = PurePosixPath(relative)
    require(not path.is_absolute() and all(part not in ("", ".", "..") for part in path.parts)
            and str(path) == relative, "normalized relative release path required")
    return path


def contains_target(value):
    if type(value) is dict:
        return any(key in {"source_text", "canonical_ir", "targets", "training_examples", "tuning_examples"}
                   or contains_target(child) for key, child in value.items())
    return type(value) is list and any(contains_target(child) for child in value)


class Bundle:
    def __init__(self):
        self.entries = {}
        self.inputs = {}

    def file(self, source, relative, *, expected=None):
        source = Path(source)
        raw = checked_ref(expected) if expected is not None else read_bytes(source)
        reference = pin(source, raw)
        require(expected is None or str(source) == expected["path"], "copy source/reference path mismatch")
        self.inputs[str(source)] = reference
        self.add(relative, raw, {"kind": "exact_source_bytes", "source": reference})
        return parse(raw) if source.suffix == ".json" else None

    def json(self, value, relative, *, origin):
        raw = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False).encode("utf-8") + b"\n"
        self.add(relative, raw, {"kind": "generated_json_projection", "origin": origin})

    def add(self, relative, raw, provenance):
        path_under(relative)
        require(relative not in self.entries, "duplicate release destination")
        require(type(raw) is bytes and 0 < len(raw) <= MAX_FILE_BYTES, "bounded nonempty release bytes required")
        require(len(self.entries) < MAX_FILES and sum(len(entry["raw"]) for entry in self.entries.values()) + len(raw)
                <= MAX_PAYLOAD_BYTES, "release payload bound exceeded")
        self.entries[relative] = {"raw": raw, "provenance": provenance}

    def close_inputs(self):
        for source, expected in self.inputs.items():
            require(pin(source) == expected, "release source changed across preparation: " + source)

    def records(self):
        return {relative: {"bytes": len(entry["raw"]), "sha256": hashlib.sha256(entry["raw"]).hexdigest(),
                           "provenance": entry["provenance"]}
                for relative, entry in sorted(self.entries.items())}


def passed_review(value, label):
    require(type(value) is dict and value.get("passed") is True and value.get("findings") == [],
            label + " must be an exact passed review with no open findings")


def review_references(value):
    """Read both named-pin and absolute-path artifact maps without opening files."""
    references = {}
    def visit(node):
        if type(node) is dict:
            if {"path", "bytes", "sha256"} <= set(node) and type(node["path"]) is str:
                references[node["path"]] = {key: node[key] for key in ("path", "bytes", "sha256")}
            for key, child in node.items():
                if type(key) is str and key.startswith("/") and type(child) is dict and {"bytes", "sha256"} <= set(child):
                    references[key] = {"path": key, "bytes": child["bytes"], "sha256": child["sha256"]}
                visit(child)
        elif type(node) is list:
            for child in node:
                visit(child)
    visit(value)
    return references


def state_checks(checkpoint, training, arm, export):
    require(checkpoint.get("schema") == "objective-resumed-source-span-checkpoint/v1"
            and checkpoint.get("lineage_id") == "objective_resumed_source_span_v1"
            and all(checkpoint.get(key) is False for key in _FALSE), "new checkpoint lineage/authority differs")
    require(checkpoint["objective"]["schema"] == "source-span-order-overlap-probability/v1"
            and checkpoint["objective"]["structure_weight"] == arm["structure_weight"], "authoritative objective arm mismatch")
    require(checkpoint["historical_parent_sha256"] == arm["parent_canonical_sha256"]
            == digest(checkpoint["historical_parent"]), "embedded parent canonical digest differs")
    require(checkpoint["progress"] == {"inherited_optimizer_steps": 400, "new_optimizer_steps": 32,
            "absolute_optimizer_steps": 432, "epochs_completed": 4, "row_cursor": 576}, "actual full32 update boundary differs")
    state = checkpoint["state"]
    require(set(state) == {"model_state", "optimizer_state"} and not contains_target(checkpoint),
            "checkpoint must contain numerical state and hashed external manifests, no example text or target")
    moments = state["optimizer_state"]
    require(moments["schema"] == "adam-default-betas-eps/v1" and len(state["model_state"]) == 23
            and set(moments["parameters"]) == set(state["model_state"])
            and all(type(value["step"]) is int and value["step"] == 432 for value in moments["parameters"].values()),
            "full23 Adam432 parameter custody differs")
    for field, split in (("training", "train"), ("tuning", "tuning")):
        require(checkpoint[field + "_manifest_sha256"] == export["manifests"][split], "external split manifest differs")
    require(training.get("complete") is True and training.get("actual_new_updates") == 32
            and training.get("requested_new_updates") == 32 and training.get("actual_TRAIN_rows") == 384
            and training.get("checkpoint_sha256") == digest(checkpoint)
            and training.get("progress") == checkpoint["progress"] and training.get("training_executed") is True
            and training.get("tuning_used_for_updates") is False, "actual training report mismatch")
    require(type(training["batch_ids"]) is list and len(training["batch_ids"]) == 32
            and all(type(row) is list and len(row) == 12 for row in training["batch_ids"])
            and training["batch_ids_sha256"] == digest(training["batch_ids"]), "training schedule witness differs")


def README(summary, arm_rows, validation, plan_sha):
    rows = "\n".join("| {name} | {weight} | 32 | {tuning}/96 | {greedy}/8 | {joint}/8 |".format(**row) for row in arm_rows)
    return ("""# Structured copied-span continuation: preserved experimental states

This release preserves four actual custom JSON decoder states from a paired
geometry experiment. Each state resumes all retained model tensors and full Adam
moments at step 400, epoch 4 / cursor 192, then performs 32 new updates: Adam 432,
epoch 4 / cursor 576. Source-only and raw384 parents each fork CE0 and probability 0.1
arms with identical ordered batches. No arm was selected or made a default.

The objective is `CE + weight * (validity + overlap) / 2`. CE keeps the retained
modality/presence/pointer arithmetic. Validity penalizes negative log mass on
`start <= end`; overlap measures exact overlap probability between independently
normalized valid intervals. Authored reference presence gates the training term.
The float64 structural accumulator consumes CPU float32 head outputs from the
same forward. The source-only arm retains its dormant 384D conditioning tensors.

The included 1,152 TRAIN and 96 TUNE rows are previously exposed authored synthetic
engineering rules with cached source embeddings. They are not reviewed statutory
gold. TRAIN fitting uses 384 rows per arm in these 32 steps. The eight real US Code
occurrences are previously exposed source-only diagnostics: no reviewed role
labels, no fit/weight selection, all review admission masks remain 0. Syntax-valid
copied proposals, structural probabilities and preserved authored tuning scores
do not establish legal accuracy. The common tuning diagnostic uses weight 0.1 on
every arm; CE0 training's uncomputed structural zeros are not diagnostic results.

| Arm | Fit weight | New updates | Authored tuning exact | Raw copied proposals, none | Joint copied proposals, none |
| --- | ---: | ---: | ---: | ---: | ---: |
""" + rows + """

Real-source raw reports preserve the learned outputs and complete same-forward
head scores. Joint reports are separate bounded K8 / nonoverlap proposals, preserving
learned modality and optional-facet presence. These counts are diagnostic syntax
coverage. Detailed observations and limits are in `guide.md` and
`evidence/analyzer-outcomes.json`; no general semantic improvement is claimed here.

There are 128 actual new updates and zero new encoder calls. Local inert validation
records {tests} unique cases that passed across a full suite and a separate
recheck. The full {full_cases}-case run had {full_passed} passes and
{full_failures} cwd-dependent pre-existing failure; that case passed in a separate
one-case recheck from the required isolated package directory. A clean full-suite
rerun is not claimed. An earlier fake-clock fixture failure was fixed in the test
only; all 88 worker cases passed in the full suite without changing the worker
source. Hosted CI and independent legal fidelity are separate from these controls.
No new 8D / 768D encoder training, broad logic-family promotion,
proof authority, `lake build legal` claim, reviewer authentication or default
promotion occurred. The checkpoint's authoritative outer schema is
`objective-resumed-source-span-checkpoint/v1`, lineage
`objective_resumed_source_span_v1`. Embedded historical constructor `loss` and
`from_scratch` fields describe old topology only. Old checkpoint loaders reject
the new outer schema. These are custom JSON states, not a Transformers model or
LLM fine-tune; there is no AutoModel or safetensors entry point.

## Load in an existing compatible environment

The 27 selected source-owner snapshots are exact preserved bytes, not a complete
wheel or independently qualified third-party import graph. Full local dependency
installation and the retained PyTorch 2.13.0+cu130 runtime are required. Old absolute
paths in recipes and receipts describe original custody; downloading this folder
does not recreate those paths, the original native encoder assets, or admission
evidence. Downloaded numerical replay has not been performed by this preparation
helper. Use a fresh Python process and consciously bootstrap only these selected
namespaces, then load against the manifest's exact file-byte hash:

```python
from pathlib import Path
from types import ModuleType
import json
import sys

release = Path("/absolute/path/to/20261011-structured-span-probability-v1")
source = release / "source"
namespaces = (
    "ipfs_datasets_py", "ipfs_datasets_py.logic", "ipfs_datasets_py.logic.legal_ir",
    "ipfs_datasets_py.logic.formalization", "ipfs_datasets_py.logic.formalization.autoencoder",
    "ipfs_datasets_py.optimizers", "ipfs_datasets_py.optimizers.logic_theorem_optimizer",
    "ipfs_datasets_py.utils",
)
for name in namespaces:
    if name in sys.modules:
        raise RuntimeError("Use a fresh process for this explicitly scoped bootstrap")
    package = ModuleType(name)
    package.__path__ = [str(source.joinpath(*name.split(".")))]
    sys.modules[name] = package

from ipfs_datasets_py.logic.formalization.autoencoder import structured_span_continuation as worker
from ipfs_datasets_py.logic.legal_ir import joint_span_selection

manifest = json.loads((release / "release-manifest.json").read_text())
relative = "states/raw384-1729-probability01/checkpoint.json"
checkpoint = worker.load_checkpoint(
    release / relative, expected_sha256=manifest["files"][relative]["sha256"]
)
runtime = worker.open_checkpoint(checkpoint)  # Actual local numerical restoration.
rows = json.loads((release / "data/exposed-law-source-only.json").read_text())["rows"]
report = runtime.infer(rows[:2], control="none", capture_scores=True)
proposals = [
    joint_span_selection.select_joint_spans(row["source_text"], observed["scores"])
    for row, observed in zip(rows[:2], report["rows"], strict=True)
    if observed["scores"] is not None
]
```

`source_text` and finite 384D `latent` vectors are explicit target-free inference
inputs; the example reuses the included previously cached vectors, without an
encoder call. Arbitrary texts require authentic compatible source embeddings
and context review. Token/byte limits refuse unsupported inputs; no truncation,
paraphrase, multi-rule or multiple-qualifier support is inferred from this example.
Canonical parent digests, manifest digests and file-byte hashes have different
scopes; `load_checkpoint(expected_sha256=...)` always expects exact file bytes.

## Preservation and publication boundary

`release-manifest.json` pins every release payload file except itself; the separate
preparation receipt pins the complete upload tree including the manifest. Each
source/report copy is byte-identical to the pinned input, with opening/closing
checks. Generated common-loss projections retain the original saved summary as
their source. There is no claimed self-hash of a manifest or circular receipt.

The intended destination is `{repository}/{prefix}`, based on immutable Hub parent
`{parent}`. This helper prepares files only; it does not upload, delete old files,
edit the repository model card, move defaults, or attest the remote tree. Root must
independently review the prepared tree and use a parent-commit compare-and-swap.
The exact experiment plan file-byte SHA is `{plan_sha}`.
""".format(tests=validation["unique_cases_passed"], full_cases=validation["full_suite_cases"],
             full_passed=validation["full_suite_passed"], full_failures=validation["full_suite_failures"],
             repository=REPOSITORY, prefix=RELEASE_PREFIX, parent=PARENT_REVISION, plan_sha=plan_sha)).encode("utf-8")


def prepare(args):
    bundle = Bundle()
    plan = bundle.file(args.plan, "evidence/experiment-plan.json")
    summary = bundle.file(args.summary, "evidence/saved-summary.json")
    outcomes = bundle.file(args.outcomes, "evidence/analyzer-outcomes.json")
    validation = bundle.file(args.validation, "evidence/inert-validation.json")
    resource = bundle.file(args.resource_review, "evidence/results-resource-review.json")
    passed_review(validation, "local validation")
    passed_review(resource, "saved outcome/resource review")
    require(type(outcomes) is dict and outcomes.get("schema") and outcomes.get("semantic_accuracy") in (None,),
            "explicit analyzer outcome object required; no semantic accuracy claim permitted")
    require(plan["schema"] == "structured-source-span-four-arm-plan/v1" and len(plan["arms"]) == 4
            and plan["total_new_updates_requested"] == 128 and plan["weights"] == [0., .1]
            and plan["training_count"] == 1152 and plan["tuning_count"] == 96
            and plan["controls"] == ["none", "zero", "disabled", "rotate"]
            and plan["encoder_execution_planned"] is False and plan["semantic_gold"] is False
            and plan["checkpoint_selection_executed"] is False and plan["default_promotion"] is False,
            "exact completed paired plan required")
    require(summary["schema"] == "structured-span-four-arm-results/v1" and summary["status"] == "completed"
            and len(summary["arms"]) == 4 and summary["actual_new_updates"] == 128
            and summary["actual_encoder_calls"] == 0 and summary["equal_step_count"] == 32
            and summary["equal_batch_schedule"] is True and summary["original_artifacts_byte_exact"] is True
            and summary["semantic_accuracy"] is None and summary["legal_fidelity_qualified"] is False
            and summary["checkpoint_selection_executed"] is False and summary["default_promotion"] is False
            and summary["eight_dimensional_trained"] is False and summary["seven_sixty_eight_trained"] is False
            and summary["Lake_executed"] is False, "completed saved results required without promotion/fidelity claims")
    require(len(args.review) >= 3, "current objective, worker and protocol reviews must be supplied")
    review_pins, reviewed_sources, protocol_matches = [], {}, []
    for index, path in enumerate(args.review):
        reviewed = bundle.file(path, "evidence/reviews/{:02d}-{}.json".format(index, Path(path).stem))
        passed_review(reviewed, "current review")
        review_pins.append(pin(Path(path)))
        reviewed_sources.update(review_references(reviewed))
        if reviewed.get("plan_sha256") == pin(Path(args.plan))["sha256"]:
            require(reviewed.get("runner_sha256") == plan["artifacts"][plan["runner_path"]]["sha256"],
                    "current protocol runner pin differs")
            protocol_matches.append(reviewed)
    require(protocol_matches, "passed current protocol review must bind the exact experiment plan and runner")
    for reference in plan["additional_owner_pins"].values():
        require(reviewed_sources.get(reference["path"]) == reference,
                "current reviews do not bind a required new source owner")
    bundle.file(args.source_guide, "guide.md")
    bundle.file(args.analysis_source, "recipe/saved-results-analyzer.py")
    if args.analysis_receipt:
        bundle.file(args.analysis_receipt, "evidence/analyzer-receipt.json")
    bundle.file(plan["runner_path"], "recipe/run_structured_span_pilot.py",
                expected={"path": plan["runner_path"], **plan["artifacts"][plan["runner_path"]]})
    bundle.file(F / "prepare_structured_span_pilot.py", "recipe/prepare_structured_span_pilot.py",
                expected={"path": str(F / "prepare_structured_span_pilot.py"),
                          **plan["artifacts"][str(F / "prepare_structured_span_pilot.py")]})
    bundle.file(F / "run_scope_guardian.py", "recipe/run_scope_guardian.py",
                expected={"path": str(F / "run_scope_guardian.py"),
                          **plan["artifacts"][str(F / "run_scope_guardian.py")]})
    bundle.file(Path(__file__).resolve(), "recipe/prepare_structured_hf_release.py")
    exported = bundle.file(plan["train_tune_export"]["path"], "data/authored-train-tune-only.json",
                           expected=plan["train_tune_export"])
    require(exported["schema"] == "authored-span-train-tune-export/v1"
            and set(exported["populations"]) == {"train", "tuning"}
            and len(exported["populations"]["train"]) == 1152 and len(exported["populations"]["tuning"]) == 96
            and exported["provenance"] == "authored_synthetic_not_legal_authority"
            and exported["semantic_gold"] is False
            and all(digest(rows) == exported["manifests"][split] for split, rows in exported["populations"].items()),
            "authored-only exposed TRAIN/TUNE export differs")
    bundle.file(F / "authored-export-receipt.json", "data/authored-export-receipt.json",
                expected={"path": str(F / "authored-export-receipt.json"),
                          **plan["artifacts"][str(F / "authored-export-receipt.json")]})
    law = bundle.file(plan["law_diagnostic_export"]["path"], "data/exposed-law-source-only.json",
                      expected=plan["law_diagnostic_export"])
    require(law["schema"] == "exposed-law-source-only-diagnostics/v1" and len(law["rows"]) == 8
            and law["semantic_gold"] is False and law["previously_exposed"] is True
            and law["used_for_updates_or_selection"] is False, "eight exposed source-only diagnostics required")
    bundle.file(plan["raw384_equivalence_pin"]["path"], "evidence/raw384-equivalence.json",
                expected=plan["raw384_equivalence_pin"])
    require(len(plan["source_owner_pins"]) == 24 and set(plan["additional_owner_pins"]) == _NEW_OWNERS,
            "exact24 retained and3 new source owners required")
    source_records = {}
    package = Path(plan["package_root"])
    for name, reference in sorted({**plan["source_owner_pins"], **plan["additional_owner_pins"]}.items()):
        relative = Path(reference["path"]).relative_to(package).as_posix()
        require(relative == name.replace(".", "/") + ".py", "source owner module/path identity differs")
        bundle.file(reference["path"], "source/" + relative, expected=reference)
        source_records[name] = {"path": "source/" + relative, "bytes": reference["bytes"], "sha256": reference["sha256"]}
    bundle.json(source_records, "source-owner-pins.json", origin={"experiment_plan": pin(Path(args.plan))})
    result_folder = Path(args.summary).parent
    probes = bundle.file(result_folder / "numerical-probes.json", "evidence/numerical-probes.json")
    passed_review(probes, "saved numerical probes")
    bundle.file(result_folder / "all-arm-plans-before-opening.json", "evidence/all-arm-plans-before-opening.json")
    bundle.file(result_folder / "baseline-tuning.json", "reports/baseline-common-tuning.json")
    expected_arms = {arm["name"]: arm for arm in plan["arms"]}
    require(len(expected_arms) == 4 and {arm["name"] for arm in summary["arms"]} == set(expected_arms),
            "exact saved arm identities differ")
    arm_rows, schedules = [], []
    expected_law_ids = [row["id"] for row in law["rows"]]
    for baseline in summary["baseline_tuning"]:
        require(_SAFE.fullmatch(baseline["name"]), "safe baseline identifier required")
        bundle.file(baseline["authored_greedy"]["path"], "reports/baselines/" + baseline["name"] + "-tuning-greedy.json",
                    expected=baseline["authored_greedy"])
    for arm_result in summary["arms"]:
        name = arm_result["name"]
        require(_SAFE.fullmatch(name), "safe saved arm identifier required")
        arm = expected_arms[name]
        checkpoint = bundle.file(arm_result["checkpoint"]["path"], "states/" + name + "/checkpoint.json",
                                 expected=arm_result["checkpoint"])
        training = bundle.file(arm_result["training"]["path"], "reports/" + name + "/training.json",
                               expected=arm_result["training"])
        state_checks(checkpoint, training, arm, exported)
        require(checkpoint["implementation"]["worker_sha256"] == plan["additional_owner_pins"][
            "ipfs_datasets_py.logic.formalization.autoencoder.structured_span_continuation"]["sha256"]
            and checkpoint["implementation"]["objective_sha256"] == plan["additional_owner_pins"][
            "ipfs_datasets_py.logic.legal_ir.structured_span_objective"]["sha256"], "new state source-owner binding differs")
        schedules.append(training["batch_ids"])
        tuning = bundle.file(arm_result["tuning_greedy"]["path"], "reports/" + name + "/tuning-greedy.json",
                             expected=arm_result["tuning_greedy"])
        require(len(tuning["rows"]) == 96 and tuning["target_access"] is False, "authored target-free tuning denominator differs")
        common = arm_result["tuning_diagnostic"]
        require(common["rows"] == 96 and common["diagnostic_structure_weight"] == .1
                and common["used_for_selection"] is False and common["semantic_accuracy"] is None,
                "common tuning geometry diagnostic differs")
        bundle.json(common, "reports/" + name + "/common-tuning-loss.json",
                    origin={"summary": pin(Path(args.summary)), "projection": "arms[name=" + name + "].tuning_diagnostic"})
        controls = arm_result["law_controls"]
        require([entry["control"] for entry in controls] == plan["controls"], "real-source control denominator differs")
        none_counts = None
        for control in controls:
            label = control["control"]
            raw = bundle.file(control["raw_inference"]["path"], "reports/" + name + "/law-" + label + "-raw.json",
                              expected=control["raw_inference"])
            joint = bundle.file(control["joint"]["path"], "reports/" + name + "/law-" + label + "-joint.json",
                                expected=control["joint"])
            require([row["id"] for row in raw["rows"]] == expected_law_ids
                    == [row["id"] for row in joint["rows"]]
                    and raw["target_access"] is False and raw["optimizer_updates"] == 0
                    and raw["additional_model_forwards"] == 0 and raw["same_forward_scores"] is True
                    and raw["legal_accuracy"] is None and joint["semantic_accuracy"] is None
                    and joint["used_for_updates_or_selection"] is False, "real-source reports changed exposure/authority/denominator")
            if label == "none":
                none_counts = (sum(row["decoder_row"]["status"] == "decoded" for row in raw["rows"]),
                               sum(row["result"] is not None and row["result"]["status"] == "selected" for row in joint["rows"]))
        arm_rows.append({"name": name, "weight": arm["structure_weight"], "tuning": common["exact_canonical_ir"],
                         "greedy": none_counts[0], "joint": none_counts[1]})
    require(all(schedule == schedules[0] for schedule in schedules), "completed paired ordered batches differ")
    bundle.add("README.md", README(summary, arm_rows, validation, pin(Path(args.plan))["sha256"]),
               {"kind": "generated_release_readme", "observations": "exact completed saved reports; no model replay"})
    bundle.close_inputs()
    manifest = {"schema": "structured-span-hf-release-manifest/v1", "repository": REPOSITORY,
                "release_prefix": RELEASE_PREFIX, "expected_parent_revision": PARENT_REVISION,
                "scope": "all_payload_files_except_this_manifest; complete_tree_pins_in_external_preparation_receipt",
                "payload_file_count": len(bundle.entries), "payload_bytes_excluding_manifest": sum(len(entry["raw"]) for entry in bundle.entries.values()),
                "files": bundle.records(), "actual_new_updates": 128, "checkpoint_count": 4,
                "authored_training_count": 1152, "authored_tuning_count": 96, "legal_diagnostic_count": 8,
                "semantic_gold": False, "legal_accuracy": None, "Lake_qualified": False,
                "default_promotion": False, "upload_performed": False}
    bundle.json(manifest, "release-manifest.json", origin={"kind": "closed_payload_manifest_without_self_hash"})
    destination = Path(args.output)
    require(destination.is_absolute() and destination.parent == F and destination.name.startswith("hf-upload")
            and destination.parent.resolve(strict=True) == destination.parent and not destination.exists(),
            "fresh owned F/hf-upload destination required")
    receipt_path = Path(args.receipt)
    require(receipt_path.is_absolute() and receipt_path.parent == F and not receipt_path.exists()
            and receipt_path != destination, "fresh external preparation receipt path required")
    destination.mkdir(mode=0o700)
    upload_root = destination / RELEASE_PREFIX
    for relative, entry in sorted(bundle.entries.items()):
        path = upload_root / path_under(relative)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(entry["raw"])
            stream.flush()
            os.fsync(stream.fileno())
        require(read_bytes(path) == entry["raw"], "release copy differs after write")
    bundle.close_inputs()
    actual = {path.relative_to(destination).as_posix(): pin(path) for path in destination.rglob("*") if path.is_file()}
    expected = {RELEASE_PREFIX + "/" + relative for relative in bundle.entries}
    require(set(actual) == expected and all(path.resolve(strict=True) == path and not path.is_symlink()
            for path in destination.rglob("*")), "prepared upload tree contains unexpected files/links")
    receipt = {"schema": "structured-span-hf-preparation-receipt/v1", "status": "prepared_not_published",
               "upload_root": str(destination), "repository": REPOSITORY, "release_prefix": RELEASE_PREFIX,
               "expected_parent_revision": PARENT_REVISION, "complete_upload_file_count": len(actual),
               "complete_upload_bytes": sum(value["bytes"] for value in actual.values()),
               "complete_upload_files": actual, "input_files": bundle.inputs, "current_review_pins": review_pins,
               "release_manifest": pin(upload_root / "release-manifest.json"), "arm_observations": arm_rows,
               "four_new_custom_JSON_states": True, "old_standalone_state_files_added": False,
               "historical_parent_states_preserved_inside_new_checkpoints": True,
               "authored_only_export_included": True, "raw_and_joint_reports_separate": True,
               "source_owner_count": 27, "all_opening_closing_input_pins_exact": True,
               "model_imported": False, "model_replayed": False, "training_executed_by_helper": False,
               "network_accessed": False, "Hub_operation_performed": False, "old_file_deletion_planned": False,
               "root_model_card_change_planned": False, "default_promotion": False, "semantic_gold": False,
               "legal_accuracy": None, "Lake_qualified": False,
               "publication_requirement": "Root independent prepared-tree review then previously authorized parent_commit compare-and-swap upload"}
    raw = json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False).encode("utf-8") + b"\n"
    descriptor = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"preparation_receipt": pin(receipt_path), "upload_file_count": len(actual),
                      "upload_bytes": receipt["complete_upload_bytes"], "upload_performed": False}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "summary", "outcomes", "analysis-source", "validation", "resource-review", "source-guide"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--review", action="append", default=[])
    parser.add_argument("--analysis-receipt")
    parser.add_argument("--output", default=str(F / "hf-upload"))
    parser.add_argument("--receipt", default=str(F / "hf-preparation-receipt-v01.json"))
    prepare(parser.parse_args())


if __name__ == "__main__":
    main()
