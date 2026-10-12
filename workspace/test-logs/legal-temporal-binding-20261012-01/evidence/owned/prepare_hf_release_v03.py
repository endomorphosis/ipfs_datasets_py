"""Stage reviewed model-only results; importing this helper performs no work.

This is a future static helper until a complete paired result and concrete
independent result review exist. It uploads nothing. The new temporal custody
code is separately reviewed engineering evidence, not a model head or a measured
legal-fidelity gain. No private ledger/claim body is in the closed input list.
"""
from pathlib import Path
import hashlib
import json
import math
import os
import sys

F = Path(__file__).resolve().parent
P = F.parent / "legal-temporal-contrast-20261011-01"
REPO = "Publicus/legal-ir-autoencoder"
PREFIX = "releases/20261012-temporal-role-contrast-v3"
MAX_PAYLOAD_BYTES = 200_000_000
RUN_ROOT = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01")
ACTUAL_ATTEMPT = RUN_ROOT / "temporal-role-contrast-20261012-03"
ACTUAL_PROTOCOL = F / "training-protocol-independent-review-v03.json"
ACTUAL_COMPATIBILITY = F / "resource-compatibility-v03.json"
ACTUAL_RUNTIME_AUDIT = F / "training-runtime-resource-audit-v03.json"
ACTUAL_RUNTIME_REVIEW = F / "training-runtime-resource-independent-review-v03.json"
SUCCESSFUL_GUARDIAN_FILES = (
    "pre-admission.json", "scheduler-adoption.json", "lease-binding.json", "command.json",
    "child-identity.json", "resources-start.json", "resource-observations.json", "child-exit.json",
    "group-rss-summary.json", "owned-group-final.json", "resources-final.json", "guardian-exit.json",
    "lease-observations.jsonl", "group-rss-observations.jsonl", "child.log",
)
CORPUS_REVIEW_SHA256 = "423d775253dc04ec4b182f3db0ae800215d8acde6a30f53a2eee27b78089b0b5"
BOUNDARY_FILES = (
    "ipfs_datasets_py/logic/legal_ir/temporal_bindings.py",
    "ipfs_datasets_py/logic/legal_ir/duration_bound_qualified.py",
    "tests/unit/logic/legal_ir/test_temporal_bindings.py",
    "tests/unit/logic/legal_ir/test_duration_bound_qualified.py",
)
EVIDENCE = (
    "training-export-v01.json", "authored-temporal-contrast-corpus-v01.json",
    "inert-ambiguity-audit-v01.json", "inert-test-observation-v02.json",
    "result-independent-review-v03.json",
    "plan-import-closure-preflight-v02.json", "plan-import-closure-independent-review-v02.json",
    "temporal-recovery-review-v01.json", "temporal-binding-code-independent-review-v01.json",
    "migration-post-closure-independent-review-v01.json", "post-migration-resource-compatibility-v01.json",
    "storage-admission-diagnosis-post-migration-v01.json", "inert-boundary-tests-v01.xml",
    "inert-new-boundary-tests-v02.xml", "inert-recipe-tests-v01.xml",
)
RECIPES = (
    "prepare_temporal_contrast_pilot.py", "prepare_temporal_contrast_pilot_v02.py", "run_temporal_contrast_pilot.py", "run_scope_guardian.py",
    "bootstrap_inert.py", "run_inert_tests.py", "prepare_hf_release_v03.py", "publish_hf_release_v03.py",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink(),
            "exact absolute regular source path required")
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def finite_number(value):
        result = float(value)
        require(math.isfinite(result), "nonfinite JSON number")
        return result

    raw = Path(path).read_bytes()
    require(len(raw) <= MAX_PAYLOAD_BYTES, "JSON byte bound exceeded")
    return json.loads(raw, object_pairs_hook=unique, parse_float=finite_number,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def canonical_digest(value):
    """Match retained span checkpoint digest encoding; not a file SHA."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def checked_review(path):
    value = read(path)
    require(value["passed"] is True and value["findings"] == [], "independent review did not pass")
    return value


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_exclusive(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    fsync_directory(Path(path).parent)


def actual_successful_attempt(result_root):
    """Join the actual successful retry's immutable authorization and runtime.

    Historical protocol v01 is never substituted for this attempt's review.
    A passed source protocol is insufficient: terminal success, independent
    runtime review, concrete audit and exact attempt evidence are mandatory.
    """
    require(result_root == ACTUAL_ATTEMPT / "results" and ACTUAL_ATTEMPT.resolve() == ACTUAL_ATTEMPT
            and ACTUAL_ATTEMPT.is_dir() and not ACTUAL_ATTEMPT.is_symlink(), "exact successful retry-03 result root required")
    require({path.name for path in ACTUAL_ATTEMPT.iterdir()} == set(SUCCESSFUL_GUARDIAN_FILES) | {"results"}
            and all((ACTUAL_ATTEMPT / name).is_file() and not (ACTUAL_ATTEMPT / name).is_symlink()
                    for name in SUCCESSFUL_GUARDIAN_FILES)
            and result_root.is_dir() and not result_root.is_symlink(), "closed successful guardian evidence inventory differs")
    pre = read(ACTUAL_ATTEMPT / "pre-admission.json")
    protocol = checked_review(ACTUAL_PROTOCOL)
    compatibility = checked_review(ACTUAL_COMPATIBILITY)
    audit = checked_review(ACTUAL_RUNTIME_AUDIT)
    review = checked_review(ACTUAL_RUNTIME_REVIEW)
    require(type(review["schema"]) is str and bool(review["schema"])
            and type(review["artifacts"]) is dict, "actual successful-runtime independent review required")
    require(pin(ACTUAL_PROTOCOL) == pre["review"], "actual pre-admission protocol review pin differs; no historical substitution")
    require(protocol["phase"] == "training" and protocol["package_root"] == str(F / "datasets")
            and protocol["run_root"] == str(RUN_ROOT)
            and protocol["fresh_resource_endpoints"]["new_attempt_path"] == str(ACTUAL_ATTEMPT),
            "actual protocol attempt/phase/roots differ")
    plan_path = Path(protocol["plan_path"])
    require(plan_path.is_absolute() and plan_path.parent == F and plan_path.name.startswith("experiment-plan-")
            and plan_path.suffix == ".json" and pin(plan_path) == pre["plan"], "actual protocol/guardian plan file differs")
    for field, path in (("runner", F / "run_temporal_contrast_pilot.py"), ("guardian", F / "run_scope_guardian.py")):
        require(pin(path) == pre[field] and protocol[field + "_sha256"] == pin(path)["sha256"],
                "actual pre-admission producer differs: " + field)
    require(protocol["plan_sha256"] == pre["plan"]["sha256"], "actual protocol plan SHA differs")
    for path in (plan_path, F / "run_temporal_contrast_pilot.py", F / "run_scope_guardian.py", ACTUAL_COMPATIBILITY):
        require(protocol["artifacts"][str(path)] == {key: pin(path)[key] for key in ("bytes", "sha256")},
                "actual protocol complete source/resource receipt binding differs")
    require(compatibility["physical_run_root"] == str(RUN_ROOT)
            and pre["compatibility"]["resources"] == compatibility["resources"]
            and pre["compatibility"]["shared_config"] == compatibility["shared_config"],
            "actual pre-admission resource envelope/configuration differs")
    terminal = read(ACTUAL_ATTEMPT / "guardian-exit.json")
    child = read(ACTUAL_ATTEMPT / "child-exit.json")
    final = read(ACTUAL_ATTEMPT / "resources-final.json")
    rss = read(ACTUAL_ATTEMPT / "group-rss-summary.json")
    require(type(terminal["returncode"]) is int and terminal["returncode"] == 0
            and type(terminal["child_returncode"]) is int and terminal["child_returncode"] == 0
            and type(child["returncode"]) is int and child["returncode"] == 0 and child["leader_reaped"] is True
            and terminal["artifacts_durable"] is True and terminal["resource_reservation_released"] is True,
            "completed/reaped/durable/released actual guardian evidence required")
    require(rss["model_gate_permitted_at_monotonic"] is not None
            and type(rss["model_phase_sample_count"]) is int and rss["model_phase_sample_count"] > 0
            and rss["sampled_peak_only"] is True and rss["absolute_peak_measured"] is False
            and rss["continuous_coverage_claimed"] is False and terminal["kernel_hard_memory_cap"] is False,
            "actual observed model phase required without invented hard/continuous coverage")
    require(final["owner"]["record"]["status"] == "released" and final["lease_absent"]["lease_present"] is False
            and final["continuous_lease_coverage_claimed"] is False, "actual terminal release evidence differs")
    require(audit["schema"] == "temporal-binding-training-runtime-resource-audit/v1"
            and audit["physical_attempt"] == str(ACTUAL_ATTEMPT) and audit["outcome"] == "completed"
            and audit["runtime_completed_and_released_qualified"] is True and audit["failed_before_model_gate"] is False
            and audit["old_511_record_bodies_unchanged"] is True and audit["owned_record_status"] == "released"
            and audit["total_actual_updates_known_from_complete_summary"] is True
            and type(audit["recorded_returned_prefix_updates"]) is int and audit["recorded_returned_prefix_updates"] == 64,
            "concrete successful runtime audit required")
    for path, expected in review["artifacts"].items():
        # Review closure can name sensitive local files as metadata; publication
        # checks only the finite public prerequisite set and never reads backups.
        require(type(expected) is dict and set(expected) == {"bytes", "sha256"}, "closed runtime-review artifact metadata required")
    public = {str(ACTUAL_ATTEMPT / name): "actual-run/" + name for name in SUCCESSFUL_GUARDIAN_FILES}
    public.update({str(ACTUAL_PROTOCOL): "evidence/actual-training-protocol-independent-review-v03.json",
                   str(ACTUAL_COMPATIBILITY): "evidence/actual-resource-compatibility-v03.json",
                   str(ACTUAL_RUNTIME_AUDIT): "evidence/actual-training-runtime-resource-audit-v03.json"})
    for path in public:
        require(review["artifacts"][path] == {key: pin(path)[key] for key in ("bytes", "sha256")},
                "actual successful-runtime public artifact bytes differ")
    public[str(ACTUAL_RUNTIME_REVIEW)] = "evidence/actual-training-runtime-resource-independent-review-v03.json"
    return dict(attempt_root=str(ACTUAL_ATTEMPT), pre_admission=pin(ACTUAL_ATTEMPT / "pre-admission.json"),
                protocol_review=pin(ACTUAL_PROTOCOL), resource_compatibility=pin(ACTUAL_COMPATIBILITY),
                runtime_audit=pin(ACTUAL_RUNTIME_AUDIT), runtime_independent_review=pin(ACTUAL_RUNTIME_REVIEW),
                plan=pin(plan_path), public_runtime_evidence=public,
                authority_scope="actual attempt-03 pre-admission and qualified terminal runtime; historical v01 not substituted")


def completed_lineage(summary, plan, result_root):
    require(summary["schema"] == "temporal-contrast-source-only-two-arm-results/v1"
            and summary["status"] == "completed", "completed paired result required")
    require(type(summary["actual_new_updates"]) is int and summary["actual_new_updates"] == 64
            and type(summary["equal_step_count"]) is int and summary["equal_step_count"] == 32,
            "exact 64 total and 32 per-arm updates required")
    require(type(summary["actual_encoder_calls"]) is int and summary["actual_encoder_calls"] == 0,
            "source-only result must have zero encoder calls")
    require(summary["same_parent_model"] is True and summary["fresh_Adam_per_arm"] is True
            and summary["inherited_optimizer_moments"] is False and summary["same_batch_schedule"] is False,
            "retained parent/fresh Adam/different-population contract differs")
    require(type(summary["trained_dimensions"]) is list and len(summary["trained_dimensions"]) == 1
            and type(summary["trained_dimensions"][0]) is int and summary["trained_dimensions"] == [384]
            and summary["latent_enabled"] is False
            and summary["semantic_accuracy"] is None and summary["legal_fidelity_qualified"] is False
            and summary["independent_semantic_holdout"] is False and summary["checkpoint_selection_executed"] is False
            and summary["default_promotion"] is False and summary["Lake_executed"] is False,
            "model-only diagnostic scope differs")
    require(type(summary["parent_optimizer_steps"]) is int and summary["parent_optimizer_steps"] == 400,
            "retained source-only400 summary boundary differs")
    require(type(summary["arms"]) is list and [arm["name"] for arm in summary["arms"]] == ["control", "contrast"],
            "complete ordered control/contrast arms required")
    for arm in summary["arms"]:
        name = arm["name"]
        require(type(arm["actual_new_updates"]) is int and arm["actual_new_updates"] == 32,
                "a truncated arm cannot be published as a completed pair")
        checkpoint_path = result_root / (name + "-checkpoint.json")
        training_path = result_root / (name + "-training.json")
        require(pin(checkpoint_path) == arm["checkpoint"] and pin(training_path) == arm["training"],
                "actual saved checkpoint/training file pins differ")
        checkpoint, training = read(checkpoint_path), read(training_path)
        require(type(training["optimizer_steps"]) is int and training["optimizer_steps"] == 32
                and training["stopped_reason"] == "step_limit" and training["training_executed"] is True,
                "completed optimizer-step training record required")
        require(checkpoint["schema"] == "warm-start-span-legal-formula-checkpoint/v1"
                and checkpoint["lineage_id"] == "warm_start_source_span_formula_v1",
                "retained warm-start checkpoint lineage differs")
        require(checkpoint["source_parent_checkpoint_sha256"] == plan["parent_base_canonical_sha256"]
                and canonical_digest(checkpoint["source_parent_checkpoint"]) == plan["parent_base_canonical_sha256"]
                and checkpoint["initial_model_state_sha256"] == plan["parent_model_state_sha256"]
                and canonical_digest(checkpoint["source_parent_checkpoint"]["model_state"]) == plan["parent_model_state_sha256"],
                "exact copied parent weight lineage differs")
        require(type(checkpoint["source_parent_optimizer_steps"]) is int and checkpoint["source_parent_optimizer_steps"] == 400,
                "retained parent optimizer boundary differs")
        require(checkpoint["initialization"]["all_parent_model_tensors_copied"] is True
                and checkpoint["initialization"]["parent_optimizer_moments_transferred"] is False
                and checkpoint["initialization"]["mode"] == "warm_start_all_source_parent_model_tensors",
                "checkpoint initialization contract differs")
        base = checkpoint["base_checkpoint"]
        require(type(base["config"]["latent_dimension"]) is int and base["config"]["latent_dimension"] == 384
                and base["config"]["latent_enabled"] is False
                and canonical_digest(checkpoint["context_contract"]) == canonical_digest(plan["context_contract"]),
                "dormant384 source-only configuration differs")
        require(type(base["progress"]["optimizer_steps"]) is int and base["progress"]["optimizer_steps"] == 32
                and base["progress"] == arm["planned_data_schedule"]["final_progress"],
                "saved final optimizer progress differs")


def main():
    result_root = Path(sys.argv[1])
    require(result_root.is_absolute() and result_root.resolve() == result_root and result_root.is_dir()
            and not result_root.is_symlink(), "exact contained result directory required")
    actual_run = actual_successful_attempt(result_root)
    plan_path = Path(actual_run["plan"]["path"])
    plan = read(plan_path)
    require(plan_path == F / "experiment-plan-v02.json" and len(plan["artifacts"]) == 97
            and len(plan["source_owner_pins"]) == 28, "actual closure-fixed97-artifact/28-owner plan required")
    summary = read(result_root / "summary.json")
    result_review = checked_review(F / "result-independent-review-v03.json")
    require(set(result_review) == {"schema", "passed", "findings", "result_root", "artifacts", "scope", "limitations"},
            "closed independent result review required")
    require(result_review["schema"] == "temporal-contrast-result-independent-review/v1"
            and result_review["result_root"] == str(result_root), "independent result review identity differs")
    result_files = sorted(result_root.glob("*.json"))
    reviewed_files = {Path(path) for path in result_review["artifacts"]
                      if Path(path).parent == result_root and Path(path).suffix == ".json"}
    require(set(result_files) == reviewed_files, "closed result JSON inventory differs from independent review")
    for path in result_files:
        require({key: pin(path)[key] for key in ("bytes", "sha256")} == result_review["artifacts"][str(path)],
                "reviewed result bytes differ")
    completed_lineage(summary, plan, result_root)
    for path, expected in plan["artifacts"].items():
        require({key: pin(path)[key] for key in ("bytes", "sha256")} == expected, "current planned artifact bytes differ")
    observation = read(F / "inert-test-observation-v02.json")
    require(observation["passed"] is True and observation["findings"] == []
            and type(observation["current_distinct_passed"]) is int and observation["current_distinct_passed"] == 417
            and type(observation["current_skipped"]) is int and observation["current_skipped"] == 2
            and type(observation["current_failed"]) is int and observation["current_failed"] == 0,
            "final 417-case/2-skip deduplicated observation required")
    boundary_review = checked_review(F / "temporal-binding-code-independent-review-v01.json")
    require({row["path"] for row in boundary_review["final_source_and_test_pins"]}
            == {str(F / "datasets" / path) for path in BOUNDARY_FILES}, "closed additive source/test review inventory differs")
    for row in boundary_review["final_source_and_test_pins"]:
        require(pin(row["path"]) == row, "reviewed additive source/test bytes differ")
    for name in ("migration-post-closure-independent-review-v01.json",):
        checked_review(F / name)
    old_review_path = P / "corpus-independent-review-v02.json"
    require(pin(old_review_path)["sha256"] == CORPUS_REVIEW_SHA256, "original corpus independent review differs")
    checked_review(old_review_path)
    reuse = {}
    for relative in ("authored-temporal-contrast-corpus-v01.json", "datasets/ipfs_datasets_py/logic/legal_ir/temporal_role_contrast_corpus.py",
                     "datasets/tests/unit/logic/legal_ir/test_temporal_role_contrast_corpus.py"):
        old, current = pin(P / relative), pin(F / relative)
        require({k: old[k] for k in ("bytes", "sha256")} == {k: current[k] for k in ("bytes", "sha256")},
                "reused corpus review requires exact body identity")
        reuse[relative] = dict(original=old, current=current)
    root = F / "hf-upload-v03"
    root.mkdir()
    inputs = {}

    def copy(source, relative):
        before = pin(source)
        target = root / PREFIX / relative
        require(not Path(relative).is_absolute() and ".." not in Path(relative).parts
                and target.resolve().is_relative_to((root / PREFIX).resolve()) and not target.exists(),
                "new contained release-prefix upload path required")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(Path(source).read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        require(pin(source) == before and pin(target)["sha256"] == before["sha256"], "source changed during exclusive staging")
        fsync_directory(target.parent)
        inputs[relative] = before

    for path in result_files:
        copy(path, "results/" + path.name)
    copy(plan_path, "evidence/actual-experiment-plan.json")
    for source, relative in actual_run["public_runtime_evidence"].items():
        copy(source, relative)
    for name in EVIDENCE:
        copy(F / name, "evidence/" + name)
    copy(old_review_path, "evidence/historical-corpus-independent-review-v02.json")
    for name in RECIPES:
        copy(F / name, "recipe/" + name)
    copy(F / "tests/test_temporal_contrast_recipe.py", "tests/test_temporal_contrast_recipe.py")
    copy(F / "datasets/tests/unit/logic/legal_ir/test_temporal_role_contrast_corpus.py", "tests/test_temporal_role_contrast_corpus.py")
    for module, owner in plan["source_owner_pins"].items():
        require(pin(owner["path"]) == owner, "current model producer bytes differ")
        copy(owner["path"], "source/" + module.replace(".", "/") + ".py")
    for relative in BOUNDARY_FILES:
        copy(F / "datasets" / relative, "boundary/" + relative)
    copy(F / "temporal-binding-design-v01.md", "boundary/temporal-binding-design-v01.md")
    copy(F / "contribution.md", "README.md")
    manifest = dict(schema="temporal-contrast-Hub-release-manifest/v1", repository=REPO, prefix=PREFIX,
        source_inputs=inputs, actual_run=actual_run, actual_updates=64, updates_per_arm=32, arms=2, source_only=True,
        configured_dimension=384, latent_enabled=False, semantic_accuracy=None, independent_statutory_gold=False,
        default_promotion=False, final_inert_passed_cases=417, final_inert_skipped_cases=2, corpus_review_reuse=reuse,
        model_only_scope="Source-only fresh-Adam paired weights and authored diagnostics; boundary source is separate engineering evidence, not fitted model capability or legal qualification.",
        private_ledger_and_claim_bodies_included=False,
        reproducibility_scope="Frozen JSON states, inputs and source; absolute historical recipe paths need explicit environment binding.")
    write_exclusive(root / PREFIX / "release-manifest.json", manifest)
    entries = {path.relative_to(root).as_posix(): pin(path) for path in sorted(root.rglob("*")) if path.is_file()}
    require(all(not path.is_symlink() for path in root.rglob("*")), "symlink in upload tree")
    require(0 < len(entries) <= 1000 and sum(value["bytes"] for value in entries.values()) <= MAX_PAYLOAD_BYTES,
            "closed payload count/byte bound exceeded")
    require(all(not name.endswith(".local.json") and "ledger-" not in name and "claims" not in name for name in entries),
            "private ledger or claims path in payload")
    baseline = read(F / "hf-before-file-identities-v01.json")
    require(baseline["repo"] == REPO and not any(name.startswith(PREFIX + "/") for name in baseline["files"]),
            "new prefix must be absent from correct immutable baseline")
    receipt = dict(schema="temporal-contrast-Hub-preparation/v1", repository=REPO, release_prefix=PREFIX,
        expected_parent_revision=baseline["revision"], upload_root=str(root), complete_upload_files=entries,
        payload_files=len(entries), payload_bytes=sum(value["bytes"] for value in entries.values()),
        baseline_pin=pin(F / "hf-before-file-identities-v01.json"), result_review=pin(F / "result-independent-review-v03.json"),
        default_promotion=False, additive_only=True)
    write_exclusive(F / "hf-preparation-receipt-v03.json", receipt)
    print(json.dumps(dict(files=len(entries), bytes=receipt["payload_bytes"])))


if __name__ == "__main__":
    main()
