"""Read-only ledger/receipt closeout; deliberately performs no inventory scan."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE = Path(__file__).resolve().parent

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def ref(path):
    raw = path.read_bytes()
    return {"path": str(path), "sha256": sha(raw), "bytes": len(raw)}

before_raw = (BASE / "ledger-before.json").read_bytes()
before = json.loads(before_raw)
receipts = {}
for label in ("baseline", "serial", "parallel"):
    paths = list((BASE / label / "cycles").glob("*/resources.json"))
    assert len(paths) == 1, (label, paths)
    receipts[label] = (paths[0], json.loads(paths[0].read_bytes()))
ledger_path = Path(receipts["baseline"][1]["ledger_path"])
after_raw = ledger_path.read_bytes()
after = json.loads(after_raw)
old, current = before["reservations"], after["reservations"]
missing = sorted(set(old) - set(current))
modified = sorted(key for key in set(old) & set(current) if old[key] != current[key])
new = set(current) - set(old)
owned = {receipt["reservation_id"] for _, receipt in receipts.values()}
owned_records = []
for label, (path, receipt) in receipts.items():
    rid = receipt["reservation_id"]
    record = current.get(rid, {})
    owned_records.append({"run": label, "reservation_id": rid,
        **{key: record.get(key) for key in ("status", "storage_bytes", "cpu_slots", "child_process_slots",
            "memory_mb", "released_at", "artifacts_durable_asserted", "last_usage", "final_accounting")},
        "receipt": ref(path), "receipt_record_matches_ledger": receipt["record"] == record,
        "receipt_status": receipt["status"], "cleanup_error": receipt["cleanup_error"],
        "attempt_directory_matches": record.get("attempt_directory", {}).get("path") == str(BASE / label)})
seed = ROOT / "workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json"
seed_ref = ref(seed)
seed_ok = seed_ref["sha256"] == "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd" and seed_ref["bytes"] == 25895338
cli = ROOT / "scripts/ops/legal_ir/run_incremental_autoencoders.py"
cli_raw = cli.read_bytes()
cap_lines = [(index, line) for index, line in enumerate(cli_raw.decode().splitlines(), 1)
             if 'not 1 <= args.storage_bytes <= 50_000_000_000' in line]
resource_source = ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py"
resource_raw = resource_source.read_bytes()
nonrecords_same = {key: value for key, value in before.items() if key != "reservations"} == {key: value for key, value in after.items() if key != "reservations"}
stable = ledger_path.read_bytes() == after_raw
retained = [row for row in current.values() if row["status"] == "retained"]
report = {"schema": "read-only-resource-closeout/v1", "checked_at": datetime.now(timezone.utc).isoformat(),
    "admitted": False, "global_storage_cap_bytes": after["limit_bytes"],
    "ledger": {"path": str(ledger_path), "before_sha256": sha(before_raw), "after_sha256": sha(after_raw),
        "prior_record_count": len(old), "current_record_count": len(current),
        "status_counts_before": dict(Counter(row["status"] for row in old.values())),
        "status_counts_after": dict(Counter(row["status"] for row in current.values())),
        "retained_claim_count": len(retained), "retained_full_reservations_bytes": sum(row["storage_bytes"] for row in retained),
        "missing_prior_records": missing, "modified_prior_records": modified,
        "all_prior_records_exactly_preserved": not missing and not modified,
        "roots_schema_and_limit_unchanged": nonrecords_same,
        "new_records_exactly_owned_completed_runs": new == owned,
        "owned_record_ids": sorted(owned), "unrelated_new_record_ids": sorted(new - owned),
        "missing_owned_record_ids": sorted(owned - new), "unchanged_during_read": stable},
    "owned_reservations": owned_records,
    "protected_checkpoint": {**seed_ref, "unchanged": seed_ok},
    "per_worker_cli_storage_cap": {"bytes": 50_000_000_000, "source": str(cli),
        "source_sha256": sha(cli_raw), "line": cap_lines[0][0] if len(cap_lines) == 1 else None,
        "validated": len(cap_lines) == 1},
    "global_cap_source": {"path": str(resource_source), "sha256": sha(resource_raw),
        "validated": b"MAX_STORAGE_BYTES = 80_000_000_000" in resource_raw},
    "scope": "Reads ledger and immutable run resource receipts, checks protected checkpoint bytes and cap source. No ledger writes, release operations or filesystem inventory rescans; existing last_usage/final_accounting observations retain their original timestamps and are not fresh headroom estimates. Process liveness was not re-probed."}
report["passed"] = all((not missing, not modified, nonrecords_same, stable, new == owned,
    len(old) == 164, len(retained) == 61, after["limit_bytes"] == 80_000_000_000,
    seed_ok, len(cap_lines) == 1, report["global_cap_source"]["validated"],
    all(row["status"] == "released" and row["receipt_status"] == "released" and row["artifacts_durable_asserted"] is True
        and row["receipt_record_matches_ledger"] and row["attempt_directory_matches"] and row["cleanup_error"] is None
        for row in owned_records)))
(BASE / "resource-closeout.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
print(json.dumps({"passed": report["passed"], "records": len(current), "new_owned": len(owned),
    "retained": len(retained), "unrelated_new": sorted(new - owned), "seed_unchanged": seed_ok}))
