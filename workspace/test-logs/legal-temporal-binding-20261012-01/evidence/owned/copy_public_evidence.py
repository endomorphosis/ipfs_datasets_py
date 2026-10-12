"""Propose or copy a finite owned evidence list; no weights or ledger backups.

Only root may invoke the copy step after its final-result decision. Proposal
records bytes without copying. Explicit source names, expected manifest SHA and
two fixed contribution destinations prevent broad filesystem discovery.
"""
from pathlib import Path
import hashlib
import json
import os
import sys

F = Path(__file__).resolve().parent
D = F / "datasets"
W = F / "workspace"
ATTEMPT = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01/temporal-role-contrast-20261012-01")
ATTEMPT_TWO = ATTEMPT.with_name("temporal-role-contrast-20261012-02")
DESTINATIONS = (
    D / "workspace/test-logs/legal-temporal-binding-20261012-01/evidence",
    W / "artifacts/legal-temporal-binding-20261012-01/evidence",
)
MAX_BYTES = 25_000_000
# This finite catalogue contains public owned metadata/code only. Optional
# future review names remain visible in the proposal's missing catalogue list.
OWNED_FILES = (
    "canonical-intake.json", "parallel-main-review-v01.json", "parallel-main-review-v02.json", "temporal-recovery-review-v01.json",
    "contribution.md", "contribution-draft-v01.md", "contribution-draft-v02.md", "final-contribution-independent-review-v01.json",
    "recipe-preflight-v01.json", "experiment-plan-v01.json", "training-export-v01.json",
    "authored-temporal-contrast-corpus-v01.json", "inert-ambiguity-audit-v01.json",
    "inert-test-observation-v02.json", "inert-boundary-tests-v01.log", "inert-boundary-tests-v01.xml",
    "inert-new-boundary-tests-v02.log", "inert-new-boundary-tests-v02.xml",
    "inert-recipe-tests-v01.log", "inert-recipe-tests-v01.xml", "preparation-execution-v01.log",
    "prepare_temporal_contrast_pilot.py", "run_temporal_contrast_pilot.py", "run_scope_guardian.py",
    "prepare_temporal_contrast_pilot_v02.py", "experiment-plan-v02.json", "plan-import-closure-preflight-v02.json",
    "plan-import-closure-independent-review-v02.json",
    "bootstrap_inert.py", "run_inert_tests.py", "tests/test_temporal_contrast_recipe.py",
    "corpus-independent-review-v02.json", "temporal-binding-design-v01.md",
    "temporal-binding-implementation-handoff-v01.json", "temporal-binding-code-independent-review-v01.json",
    "temporal-binding-guide-independent-review-v01.json", "training-protocol-independent-review-v01.json",
    "temporal_bindings-draft-v01.py", "duration_bound_qualified-draft-v01.py",
    "test_temporal_bindings-draft-v01.py", "test_duration_bound_qualified-draft-v01.py",
    "resource-compatibility-v01.json", "post-migration-resource-compatibility-v01.json",
    "migration-post-closure-independent-review-v01.json", "storage-independent-review-v01.json",
    "storage-resource-endpoints-post-migration-v01.json",
    "migrate_ephemeral_resource_root.py", "ephemeral-root-migration-protocol-v03.json",
    "ephemeral-root-migration-prepared-source-receipt-v03.json", "ephemeral-root-migration-independent-review-v01.json",
    "migration-execution-v01.log", "ephemeral-root-migration-attempt-01/attempt-started.json",
    "ephemeral-root-migration-attempt-01/planned-mutation.json", "ephemeral-root-migration-attempt-01/completion.json",
    "storage-admission-diagnosis-v01.json", "storage-admission-diagnosis-post-migration-v01.json",
    "storage-recheck-receipt-v01.json", "storage-recheck-receipt-post-migration-v01.json",
    "guardian-execution-v01.log", "failed-attempt-independent-review-v01.json",
    "training-runtime-resource-audit-v01.json", "storage-census-after-refusal-v01.json",
    "owned-gated-refusal-preflight-history-v01.json", "owned-gated-refusal-reconciliation-independent-review-v01.json",
    "owned-gated-refusal-reconciliation-protocol-v01.json", "owned-gated-refusal-reconciliation-protocol-v02.json",
    "owned-claim-reconciliation-execution-v01.log", "owned-gated-refusal-reconciliation-attempt-01/attempt-started.json",
    "reconcile_owned_gated_refusal-draft-v02.py", "reconcile_owned_gated_refusal-draft-v03.py",
    "reconcile_owned_gated_refusal.py", "owned_closeout_write_gate.py", "run_write_gate_boundary_tests.py",
    "stdlib-tempfile-open-events-v01.json", "write-gate-boundary-fixture-02/output/result.json",
    "owned-claim-closeout-attempt-01-failure-closure-v01.json", "owned-claim-wrapper-refusal-independent-review-v01.json",
    "owned-gated-refusal-reconciliation-protocol-v03.json",
    "owned-gated-refusal-reconciliation-protocol-v04.json", "owned-gated-refusal-reconciliation-independent-review-v02.json",
    "owned-claim-reconciliation-execution-v02.log", "owned-gated-refusal-reconciliation-attempt-02/attempt-started.json",
    "owned-gated-refusal-reconciliation-attempt-02/planned-mutation.json", "owned-gated-refusal-reconciliation-attempt-02/completion.json",
    "owned-gated-refusal-reconciliation-postclosure-independent-review-v01.json",
    "audit_training_runtime_resources.py", "runtime-resource-audit-procedure-v03.json",
    "audit_closeout_and_retry_census.py", "resource-compatibility-v02.json", "training-protocol-independent-review-v02.json",
    "retry-storage-census-01.json", "retry-storage-census-02.json", "own-claim-closeout-postaudit-v01.json",
    "fresh-retry-census-independent-review-v01.json",
    "audit_training_runtime_resources_v02.py", "runtime-resource-audit-procedure-v04.json",
    "runtime-resource-v02-preparation-refusal-v01.json", "guardian-execution-v02.log",
    "training-runtime-resource-audit-v02.json", "training-runtime-resource-independent-review-v02.json",
    "audit_preparation_refusal_v02.py", "training-preparation-refusal-audit-v02.json",
    "reconcile_owned_preparation_refusal.py", "owned-preparation-refusal-reconciliation-protocol-v01.json",
    "owned-preparation-refusal-reconciliation-independent-review-v01.json",
    "owned-preparation-claim-reconciliation-execution-v01.log",
    "owned-preparation-refusal-reconciliation-attempt-01/attempt-started.json",
    "owned-preparation-refusal-reconciliation-attempt-01/failure-primary.json",
    "audit_preparation_closeout_and_retry_census.py",
    "audit_preparation_claim_closeout_refusal.py", "storage-census-after-closeout-refusal-v02.json",
    "owned-preparation-refusal-reconciliation-failure-independent-review-v01.json",
    "final-capacity-refusal-independent-review-v02.json",
    "prepare_hf_release.py", "publish_hf_release.py", "hf-helper-design-v01.md",
    "hf-helper-implementation-handoff-v01.json", "hf-helper-static-review-v01.json",
    "prepare_hf_release_v02.py", "publish_hf_release_v02.py", "hf-helper-design-v02.md",
    "hf-helper-implementation-handoff-v02.json", "hf-helper-static-review-v02.json",
    "prepare_hf_release_v03.py", "publish_hf_release_v03.py", "hf-helper-design-v03.md",
    "hf-helper-implementation-handoff-v03.json", "hf-helper-static-review-v03.json",
    "hf-parent-live-intake-v01.json", "hf-parent-download-v01.log", "hf-parent-readback-receipt-v01.json",
    "hf-parent-independent-review-v01.json",
    "copy_public_evidence.py", "record_closed_stage.py", "public-evidence-copy-design-v01.md",
    "public-evidence-copy-independent-review-v01.json",
    "record_merged_publication.py", "merged-publication-observer-static-review-v01.json",
)
SOURCE_FILES = (
    "ipfs_datasets_py/logic/legal_ir/temporal_bindings.py",
    "ipfs_datasets_py/logic/legal_ir/duration_bound_qualified.py",
    "tests/unit/logic/legal_ir/test_temporal_bindings.py",
    "tests/unit/logic/legal_ir/test_duration_bound_qualified.py",
    "docs/autoencoders/legal_temporal_occurrence_bindings_20261012.md",
)
FAILED_FILES = (
    "child-exit.json", "child-identity.json", "child.log", "command.json", "failure-primary.json",
    "group-rss-observations.jsonl", "group-rss-summary.json", "guardian-exit.json", "lease-binding.json",
    "lease-observations.jsonl", "pre-admission.json", "resources-final-failure.json", "scheduler-adoption.json",
)
FAILED_TWO_FILES = (*FAILED_FILES, "resources-start.json", "results/child-failure.json")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink(),
            "ordinary absolute owned source required")
    data = path.read_bytes()
    return dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=pairs,
        parse_float=lambda value: (_ for _ in ()).throw(ValueError("float metadata refused")),
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite metadata refused")))


def catalogue():
    values = {"owned/" + name: F / name for name in OWNED_FILES}
    values.update({"source/" + name: D / name for name in SOURCE_FILES})
    values.update({"failed-training-attempt-01/" + name: ATTEMPT / name for name in FAILED_FILES})
    values.update({"failed-training-attempt-02/" + name: ATTEMPT_TWO / name for name in FAILED_TWO_FILES})
    require(len(values) == len(OWNED_FILES) + len(SOURCE_FILES) + len(FAILED_FILES) + len(FAILED_TWO_FILES), "duplicate finite source entry")
    return values


def write(path, value):
    path = Path(path)
    require(path.parent == F and path.resolve() == path and not path.exists(), "new owned receipt filename required")
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(F, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def propose(name):
    entries, missing = {}, []
    for relative, source in catalogue().items():
        if source.exists():
            entries[relative] = pin(source)
        else:
            missing.append(dict(relative=relative, source=str(source)))
    require(sum(row["bytes"] for row in entries.values()) <= MAX_BYTES, "public evidence byte bound exceeded")
    value = dict(schema="temporal-binding-public-evidence-inventory/v1", status="proposed_for_root_final_result_decision",
                 entries=entries, missing_finite_catalogue=missing, destinations=[str(path) for path in DESTINATIONS],
                 files=len(entries), bytes=sum(row["bytes"] for row in entries.values()),
                 weights_included=False, full_ledger_bodies_included=False, foreign_bodies_included=False,
                 source_scope="Explicit current-owned metadata/code and immutable failed-attempt evidence only.")
    write(F / name, value)
    print(json.dumps(dict(status="proposed_only_no_copy", files=len(entries), bytes=value["bytes"])))


def copy(manifest_path, expected_sha256, receipt_name):
    manifest_path = Path(manifest_path)
    require(manifest_path.parent == F and pin(manifest_path)["sha256"] == expected_sha256,
            "exact root-selected proposed inventory SHA required")
    value = read(manifest_path)
    require(set(value) == {"schema", "status", "entries", "missing_finite_catalogue", "destinations", "files", "bytes",
                           "weights_included", "full_ledger_bodies_included", "foreign_bodies_included", "source_scope"},
            "closed public evidence inventory required")
    require(value["schema"] == "temporal-binding-public-evidence-inventory/v1"
            and value["weights_included"] is value["full_ledger_bodies_included"] is value["foreign_bodies_included"] is False,
            "public metadata-only scope required")
    allowed = catalogue()
    entries = value["entries"]
    require(type(entries) is dict and set(entries) <= set(allowed) and value["destinations"] == [str(path) for path in DESTINATIONS],
            "selected inventory leaves finite catalogue/fixed destinations")
    require(type(value["files"]) is int and value["files"] == len(entries) > 0
            and type(value["bytes"]) is int and value["bytes"] == sum(row["bytes"] for row in entries.values()) <= MAX_BYTES,
            "closed selected evidence count/byte bound differs")
    payload = {}
    for relative, expected in entries.items():
        require(type(expected) is dict and set(expected) == {"path", "bytes", "sha256"}
                and type(expected["bytes"]) is int and expected["bytes"] >= 0
                and type(expected["sha256"]) is str and len(expected["sha256"]) == 64,
                "closed ordinary expected source pin required")
        require(not Path(relative).is_absolute() and ".." not in Path(relative).parts
                and pin(allowed[relative]) == expected, "exact selected source bytes differ")
        payload[relative] = allowed[relative].read_bytes()
        require(len(payload[relative]) == expected["bytes"] and hashlib.sha256(payload[relative]).hexdigest() == expected["sha256"],
                "selected source changed while capturing immutable bytes")
    for destination in DESTINATIONS:
        require(destination.resolve() == destination and not destination.exists(), "new fixed ordinary contribution destination required")
    copies = {}
    for destination in DESTINATIONS:
        destination.mkdir(parents=True)
        files, directories = {}, {destination, destination.parent}
        for relative, data in payload.items():
            target = destination / relative
            require(target.resolve().is_relative_to(destination), "contribution path escapes fixed destination")
            target.parent.mkdir(parents=True, exist_ok=True)
            directory = target.parent
            while directory.is_relative_to(destination):
                directories.add(directory)
                if directory == destination:
                    break
                directory = directory.parent
            with target.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            files[relative] = pin(target)
            require(files[relative]["bytes"] == entries[relative]["bytes"]
                    and files[relative]["sha256"] == entries[relative]["sha256"], "contribution copy bytes differ")
        for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        copies[str(destination)] = files
    require(all(pin(allowed[relative]) == expected for relative, expected in entries.items()), "closing selected source bytes differ")
    write(F / receipt_name, dict(schema="temporal-binding-public-evidence-copy/v1", passed=True, findings=[],
        inventory=pin(manifest_path), copied_files_per_destination=len(entries), copied_bytes_per_destination=value["bytes"],
        copies=copies, weights_included=False, full_ledger_bodies_included=False, foreign_bodies_included=False))
    print(json.dumps(dict(status="copied_selected_owned_evidence", files=len(entries), copies=len(copies))))


def main():
    if sys.argv[1] == "--propose":
        require(len(sys.argv) == 3, "proposal needs a new receipt filename")
        propose(sys.argv[2])
    elif sys.argv[1] == "--copy":
        require(len(sys.argv) == 5, "copy needs root-selected inventory, exact SHA and new receipt filename")
        copy(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        raise ValueError("explicit --propose or root-final-decision --copy mode required")


if __name__ == "__main__":
    main()
