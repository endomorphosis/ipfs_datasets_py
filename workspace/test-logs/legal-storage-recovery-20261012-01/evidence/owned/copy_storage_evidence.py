"""Copy a finite reviewed storage evidence set; no ledger or weight containers."""
from pathlib import Path
import hashlib
import json
import math
import os
import sys

F = Path(__file__).resolve().parent
OLD = F.parent / "legal-temporal-binding-20261012-01"
FILES = (
    "canonical-intake-v01.json", "storage-plan.md", "storage-documentation-independent-review-v01.json",
    "parallel-main-independent-review-v01.json", "filesystem-intake-v01.json", "ledger-aggregate-intake-v01.json",
    "du-allocated-deduplicated-v01.tsv", "du-count-links-apparent-depth1-v01.tsv",
    "largest-candidates-depth2-v01.tsv", "pytest-metadata-v01.json", "scan_storage_metadata.py",
    "scan_storage_metadata_v02.py", "named-root-metadata-census-v01.json", "named-root-metadata-census-v02.json",
    "metadata-census-execution-v01.log", "metadata-census-execution-v02.log", "storage-capacity-intake-v01.json",
    "retained-claims-metadata-intake-v01.json", "retained-claims-owner-api-analysis-v01.json",
    "storage-remediation-next-actions-v01.json", "administrative-storage-closeout-design-v01.json",
    "administrative-storage-closeout-implementation-handoff-v01.json",
    "administrative-storage-closeout-independent-review-v01.json", "inert-test-observation-v01.json",
    "inert_resource_tests.py", "inert_resource_tests-draft-v01.py", "inert_resource_tests-draft-v02.py",
    "recovery-tests-v01.log", "recovery-tests-v02.log", "recovery-tests-v03.log", "recovery-tests-v03.xml",
    "recovery-tests-v04.log", "recovery-tests-v04.xml", "recovery-tests-v05.log", "recovery-tests-v05.xml",
    "owner-regression-tests-v01.log", "owner-regression-tests-v01.xml",
    "reconcile_owned_preparation_refusal_administrative.py",
    "owned-preparation-administrative-closeout-protocol-v01.json",
    "owned-preparation-administrative-closeout-independent-review-v01.json",
    "owned-preparation-administrative-closeout-independent-review-v02.json",
    "owned-preparation-administrative-closeout-preflight-v01.log",
    "administrative-closeout-execution-v01.log", "review_owned_administrative_closeout.py",
    "review_owned_administrative_postclosure.py",
    "owned-preparation-administrative-closeout-attempt-01/attempt-started.json",
    "owned-preparation-administrative-closeout-attempt-01/planned-mutation.json",
    "owned-preparation-administrative-closeout-attempt-01/completion.json",
    "owned-preparation-administrative-closeout-attempt-01/actual-postwrite-census.json",
    "owned-preparation-administrative-closeout-postclosure-independent-review-v01.json",
    "prepare_generated_field_4gb_closeout.py", "generated-field-4gb-closeout-preparation-execution-v01.log",
    "generated-field-4gb-closeout-preparation-v01.json", "copy_storage_evidence.py",
    "storage-evidence-copy-source-independent-review-v01.json",
)
SOURCE = (
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_resource_recovery.py",
    "tests/unit/optimizers/logic_theorem_optimizer/test_autoencoder_resource_recovery.py",
    "docs/autoencoders/storage_accounting_recovery_20261012.md",
)
DESTINATIONS = (
    F / "datasets/workspace/test-logs/legal-storage-recovery-20261012-01/evidence",
    F / "workspace/artifacts/legal-storage-recovery-20261012-01/evidence",
)
MAX_BYTES = 5_000_000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pin(path):
    require(path.resolve() == path and path.is_file() and not path.is_symlink(), "ordinary exact owned artifact required")
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def catalogue():
    result = {"owned/" + n: F / n for n in FILES}
    result.update({"source/" + n: F / "datasets" / n for n in SOURCE})
    result.update({"prior/" + n: OLD / n for n in ("owned_closeout_write_gate.py", "run_scope_guardian.py")})
    require(len(result) == len(FILES) + len(SOURCE) + 2, "unique finite catalogue required")
    return result


def fsync_dir(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save(path, value):
    require(path.parent == F and path.resolve() == path and not path.exists(), "new owned receipt required")
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    fsync_dir(F)


def check_public_json(value):
    if isinstance(value, dict):
        require(not {"schema", "roots", "limit_bytes", "reservations"} <= set(value), "full ledger prohibited")
        require(not {"reservation_id", "status", "storage_bytes", "owner_pid", "created_at"} <= set(value), "full reservation body prohibited")
        require(not {"model_state", "optimizer_state", "state_dict", "weights"} & set(value), "model state prohibited")
        require("lease_key" not in value and "HF_TOKEN" not in value, "private credential field prohibited")
        for item in value.values():
            check_public_json(item)
    elif isinstance(value, list):
        for item in value:
            check_public_json(item)


def unique(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate metadata JSON key")
        result[key] = value
    return result


def read_json(raw):
    def finite_float(value):
        result = float(value)
        require(math.isfinite(result), "nonfinite metadata refused")
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_float=finite_float,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON refused")))


def main():
    require(len(sys.argv) in {3, 5}, "explicit prepare or reviewed-copy arguments required")
    known = catalogue()
    if sys.argv[1] == "--prepare":
        require(len(sys.argv) == 3, "prepare needs new owned inventory name")
        entries = {n: pin(p) for n, p in known.items()}
        require(sum(p["bytes"] for p in entries.values()) <= MAX_BYTES, "finite public evidence bound")
        for name, p in known.items():
            if p.suffix == ".json":
                check_public_json(read_json(p.read_bytes()))
        save(F / sys.argv[2], dict(schema="storage-evidence-inventory/v1", entries=entries,
             files=len(entries), bytes=sum(p["bytes"] for p in entries.values()),
             destinations=[str(d) for d in DESTINATIONS], private_ledgers_included=False,
             foreign_record_bodies_included=False, model_weights_included=False))
        print(json.dumps(dict(prepared_only=True, files=len(entries))))
        return
    require(sys.argv[1] == "--copy" and len(sys.argv) == 5, "reviewed-copy requires inventory, SHA and new receipt")
    inventory = F / sys.argv[2]
    identity = pin(inventory)
    require(inventory.parent == F and identity["sha256"] == sys.argv[3], "exact selected inventory SHA required")
    value = read_json(inventory.read_bytes())
    require(set(value) == {"schema", "entries", "files", "bytes", "destinations", "private_ledgers_included",
                          "foreign_record_bodies_included", "model_weights_included"}, "closed inventory required")
    require(value["schema"] == "storage-evidence-inventory/v1" and set(value["entries"]) == set(known), "exact finite source set required")
    require(value["destinations"] == [str(d) for d in DESTINATIONS]
            and value["private_ledgers_included"] is value["foreign_record_bodies_included"] is value["model_weights_included"] is False,
            "fixed destinations and public metadata scope required")
    for row in value["entries"].values():
        require(type(row) is dict and set(row) == {"path", "bytes", "sha256"}
                and type(row["path"]) is str and type(row["bytes"]) is int and row["bytes"] >= 0
                and type(row["sha256"]) is str and len(row["sha256"]) == 64, "closed exact source pin required")
    require(type(value["files"]) is int and value["files"] == len(known)
            and type(value["bytes"]) is int and value["bytes"] == sum(p["bytes"] for p in value["entries"].values()) <= MAX_BYTES,
            "exact inventory totals required")
    payload = {}
    for name, path in known.items():
        require(pin(path) == value["entries"][name], "selected source pin changed")
        raw = path.read_bytes()
        require(len(raw) == value["entries"][name]["bytes"] and hashlib.sha256(raw).hexdigest() == value["entries"][name]["sha256"], "captured bytes changed")
        if path.suffix == ".json":
            check_public_json(read_json(raw))
        payload[name] = raw
    for dest in DESTINATIONS:
        require(dest.resolve() == dest and not dest.exists(), "fresh fixed contribution destination required")
    for dest in DESTINATIONS:
        dest.mkdir(parents=True)
        directories = {dest, dest.parent}
        for name, raw in payload.items():
            path = dest / name
            require(path.resolve().is_relative_to(dest), "copy path escapes destination")
            path.parent.mkdir(parents=True, exist_ok=True)
            directory = path.parent
            while directory.is_relative_to(dest):
                directories.add(directory)
                if directory == dest:
                    break
                directory = directory.parent
            with path.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            require({k: pin(path)[k] for k in ("bytes", "sha256")} == {k: value["entries"][name][k] for k in ("bytes", "sha256")}, "copy bytes differ")
        for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
            fsync_dir(directory)
    require(all(pin(p) == value["entries"][n] for n, p in known.items()), "closing source pins changed")
    save(F / sys.argv[4], dict(schema="storage-evidence-copy/v1", passed=True, findings=[], inventory=identity,
         files_per_destination=len(payload), bytes_per_destination=value["bytes"], destinations=[str(d) for d in DESTINATIONS],
         private_ledgers_included=False, foreign_record_bodies_included=False, model_weights_included=False))
    print(json.dumps(dict(copied=True, files=len(payload), destinations=2)))


if __name__ == "__main__":
    main()
