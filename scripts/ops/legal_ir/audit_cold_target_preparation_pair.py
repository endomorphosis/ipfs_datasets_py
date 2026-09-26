#!/usr/bin/env python3
"""Compare two completed native preparation runs after their timers stop.

This stdlib-only audit imports no package code, constructs no native targets,
and rewrites no artifact. It hashes actual compressed and expanded shards and
walks every ordered tagged-JSON node. The sole permitted content differences
are the two explicitly observed deontic graph wall timestamps at fixed typed
paths. Their original values remain in the receipt; raw byte/hash parity is
reported separately and is never relabeled as exact parity.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import zlib


ROOT = Path(__file__).resolve().parents[3]
MAX_ARTIFACT = 256 * 1024 * 1024
MAX_SHARD = 64 * 1024 * 1024
MAX_MANIFEST = 16 * 1024 * 1024
MAX_RECEIPT = 32 * 1024 * 1024
ALLOWED_SOURCE = "ipfs_datasets_py/optimizers/logic_theorem_optimizer/frame_bm25_selector.py"
NATIVE_HARNESS_SHA = "7e7cbd507314846d64acec5719c9267d27111a57c358f2372cf17c5383446a29"
COLD_HARNESS_SHA = "bc3e19730caa378d8c5ffe375a7170a04143c485d4d8bcaca983f9160fc50bc1"
BRIDGES = {"modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec", "external_prover_router"}
POINTER_PREFIX = "/fields/items/1/1/fields/items/5/1/items/8/1/fields/items/1/1/items/0/1/items/"
LOGICAL_PREFIX = "/fields/document/fields/views/deontic_norms.deontic_graph/fields/payload/metadata/"
ALLOWED_TIMESTAMPS = {
    POINTER_PREFIX + "0/1": LOGICAL_PREFIX + "created_at",
    POINTER_PREFIX + "1/1": LOGICAL_PREFIX + "last_updated",
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def same(left, right):
    return canonical(left) == canonical(right)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fingerprint(handle):
    info = os.fstat(handle.fileno())
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_exact(handle, count):
    raw = handle.read(count)
    require(len(raw) == count, "truncated artifact")
    return raw


def complete_reports(prepared):
    reports, statuses = prepared["bridge_report_telemetry"], prepared["statuses"]
    return (len(statuses) == 6 and set(reports) == set(statuses)
        and all(value == "ready" for value in statuses.values())
        and all(report["report_received"] is True
            and report["attempted_bridge_count"] == report["implemented_bridge_count"] == 5
            and len(report["attempted_bridge_names"]) == len(report["implemented_bridge_names"]) == 5
            and set(report["attempted_bridge_names"]) == set(report["implemented_bridge_names"]) == BRIDGES
            and report["failed_bridge_count"] == 0 and report["failed_bridge_names"] == []
            and report["failures"] == {} and report["outer_timeout"] is None
            for report in reports.values()))


class VerifiedBundle:
    def __init__(self, receipt):
        self.artifact = receipt["target_preparation"]["artifact"]
        path = Path(self.artifact["path"])
        require(ROOT in path.resolve().parents, "bundle is outside the canonical workspace")
        self.handle = os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb")
        try:
            self.initial = fingerprint(self.handle)
            require(stat.S_ISREG(os.fstat(self.handle.fileno()).st_mode)
                    and self.initial[2] == self.artifact["bytes"] <= MAX_ARTIFACT, "artifact byte/type bound")
            self.verify_unchanged()
            self.handle.seek(0)
            magic, size = struct.unpack(">8sQ", read_exact(self.handle, 16))
            require(magic == b"LIRTB01\n" and 0 < size <= MAX_MANIFEST, "bundle header")
            self.manifest = json.loads(read_exact(self.handle, size))
            self.payload_offset = 16 + size
            manifest = self.manifest
            require(manifest["schema_version"] == "legal-ir-target-bundle-v1"
                    and manifest["codec"] == "zlib:legal-ir-target-snapshot-v1-tagged-json", "bundle codec")
            require(manifest["snapshot_id"] == "sha256:" + digest(canonical(
                {key: value for key, value in manifest.items() if key != "snapshot_id"})), "manifest identity")
            inventory = receipt["verified_target_bundle_inventory"]
            require(same(manifest["records"], inventory["records"])
                    and same(manifest["shards"], inventory["shards"]), "retained inventory differs from actual artifact")
            require(manifest["snapshot_id"] == receipt["target_preparation"]["target_snapshot_id"], "snapshot identity")
            require(len(manifest["records"]) == len({row["sample_id"] for row in manifest["records"]}) == 6,
                    "exact six unique target records required")
            extent, self.shards = 0, {}
            for shard in manifest["shards"]:
                require(type(shard["offset"]) is int and shard["offset"] == extent
                        and type(shard["uncompressed_bytes"]) is int and 0 < shard["uncompressed_bytes"] <= MAX_SHARD
                        and type(shard["compressed_bytes"]) is int
                        and 0 < shard["compressed_bytes"] <= MAX_SHARD + (MAX_SHARD >> 12) + (MAX_SHARD >> 14) + (MAX_SHARD >> 25) + 13,
                        "shard extent/size bound")
                require(shard["target_sha256"] not in self.shards, "duplicate shard descriptor")
                self.shards[shard["target_sha256"]] = shard
                extent += shard["compressed_bytes"]
            require(self.payload_offset + extent == self.initial[2], "unindexed artifact bytes")
            require({row["target_sha256"] for row in manifest["records"]} == set(self.shards)
                    and all(row["has_target"] is True and row["status"] == "ready" for row in manifest["records"]),
                    "incomplete/unreferenced targets")
            require(sum(self.shards[row["target_sha256"]]["uncompressed_bytes"] for row in manifest["records"])
                    <= MAX_ARTIFACT, "referenced expanded target byte bound")
            require({"ipfs_datasets_py/" + path: value for path, value in manifest["config"]["code_sha256"].items()}
                    == receipt["package_source_hashes_before"], "embedded config differs from native source identity")
        except BaseException:
            self.handle.close()
            raise

    def verify_unchanged(self):
        require(fingerprint(self.handle) == self.initial, "artifact fingerprint changed")
        self.handle.seek(0)
        require(hashlib.file_digest(self.handle, "sha256").hexdigest() == self.artifact["sha256"], "artifact SHA-256")
        require(fingerprint(self.handle) == self.initial, "artifact changed during hash")

    def compressed(self, shard):
        self.handle.seek(self.payload_offset + shard["offset"])
        raw = read_exact(self.handle, shard["compressed_bytes"])
        require(digest(raw) == shard["compressed_sha256"], "actual compressed shard SHA-256")
        return raw

    def close(self):
        self.handle.close()


def expand(compressed, shard):
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, shard["uncompressed_bytes"] + 1)
    require(decoder.eof and not decoder.unconsumed_tail and not decoder.unused_data
            and len(raw) == shard["uncompressed_bytes"] and digest(raw) == shard["target_sha256"],
            "expanded shard bound/SHA-256")
    return raw


def bounded_value(value):
    if type(value) is str and len(value) > 512:
        return {"length": len(value), "sha256_utf8": digest(value.encode()), "preview": value[:512]}
    if type(value) is list and len(value) > 64:
        return {"length": len(value), "sha256_canonical_json": digest(canonical(value)), "preview": value[:64]}
    return value


def compare_tagged_values(left, right):
    changes, count, visited = [], 0, 0

    def note(pointer, logical, a, b, kind):
        nonlocal count
        count += 1
        if len(changes) < 64:
            changes.append({"json_pointer": pointer, "logical_path": logical, "kind": kind,
                            "reference": bounded_value(a), "candidate": bounded_value(b),
                            "reference_type": type(a).__name__, "candidate_type": type(b).__name__})

    def walk(a, b, pointer, logical):
        nonlocal visited
        visited += 1
        if type(a) is not type(b):
            note(pointer, logical, type(a).__name__, type(b).__name__, "type")
        elif isinstance(a, dict):
            if list(a) != list(b):
                note(pointer, logical, list(a), list(b), "ordered_object_keys")
            elif a.get("type") == b.get("type") == "mapping" and set(a) == {"type", "items"}:
                walk(a["type"], b["type"], pointer + "/type", logical + "/@type")
                if len(a["items"]) != len(b["items"]):
                    note(pointer + "/items", logical, len(a["items"]), len(b["items"]), "mapping_length")
                    return
                for i, (x, y) in enumerate(zip(a["items"], b["items"])):
                    require(len(x) == len(y) == 2, "tagged mapping pair shape")
                    walk(x[0], y[0], pointer + f"/items/{i}/0", logical + f"/@key/{i}")
                    label = x[0] if type(x[0]) is str else f"<nonstring-key-{i}>"
                    walk(x[1], y[1], pointer + f"/items/{i}/1", logical + "/" + label)
            else:
                for key in a:
                    walk(a[key], b[key], pointer + "/" + key, logical + "/" + key)
        elif isinstance(a, list):
            if len(a) != len(b):
                note(pointer, logical, len(a), len(b), "array_length")
            else:
                for i, (x, y) in enumerate(zip(a, b)):
                    walk(x, y, pointer + f"/{i}", logical + f"/{i}")
        elif (struct.pack("!d", a) != struct.pack("!d", b)) if type(a) is float else a != b:
            note(pointer, logical, a, b, "scalar_value")

    walk(left, right, "", "")
    return {"difference_count": count, "differences": changes,
            "all_differences_retained": count == len(changes), "nodes_compared": visited}


def permitted_timestamp_changes(diff):
    if diff["difference_count"] == 0:
        return True
    allowed = (diff["difference_count"] == 2 and diff["all_differences_retained"]
               and {row["json_pointer"] for row in diff["differences"]} == set(ALLOWED_TIMESTAMPS))
    for row in diff["differences"]:
        acceptable = (row["json_pointer"] in ALLOWED_TIMESTAMPS
            and row["logical_path"] == ALLOWED_TIMESTAMPS[row["json_pointer"]]
            and row["kind"] == "scalar_value" and row["reference_type"] == row["candidate_type"] == "str")
        if acceptable:
            try:
                acceptable = all(datetime.fromisoformat(row[key]).utcoffset().total_seconds() == 0
                                 for key in ("reference", "candidate"))
            except (ValueError, TypeError, AttributeError):
                acceptable = False
        row["explicit_permitted_difference"] = acceptable
        allowed = allowed and acceptable
    return bool(allowed)


def audit(paths, result):
    raw_receipts = [path.read_bytes() for path in paths]
    require(all(len(raw) <= MAX_RECEIPT for raw in raw_receipts), "receipt byte budget")
    receipts = [json.loads(raw) for raw in raw_receipts]
    a, b = receipts
    result["input_receipts"] = {name: {"path": str(path), "sha256": digest(raw)}
                                for name, path, raw in zip(("reference", "candidate"), paths, raw_receipts)}
    sa, sb = a["package_source_hashes_before"], b["package_source_hashes_before"]
    result["package_source_changes"] = {path: {"reference": sa.get(path), "candidate": sb.get(path)}
        for path in sorted(set(sa) | set(sb)) if sa.get(path) != sb.get(path)}
    guards = result["guards"] = {
        "both_receipts_passed": all(row["passed"] is True for row in receipts),
        "both_source_manifests_stable": all(row["source_unchanged"] is True
            and row["package_source_hashes_before"] == row["package_source_hashes_after"] for row in receipts),
        "only_expected_source_changed": set(result["package_source_changes"]) == {ALLOWED_SOURCE},
        "same_native_benchmark_harness": all(row["benchmark_harness"]["sha256"] == NATIVE_HARNESS_SHA
            and row["benchmark_harness"]["source_unchanged"] is True
            and row["benchmark_harness"]["package_callables_replaced"] is False for row in receipts),
        "same_frozen_harness": all(row["profile_script_sha256"] == COLD_HARNESS_SHA for row in receipts),
        "both_uninstrumented": all(row["native_preparation_only"] is True and row["cprofile_used"] is False
            and row["observations"]["function_wrappers_installed"] is False
            and row["observations"]["gc_callbacks_installed"] is False
            and row["observations"]["cprofile_enabled"] is False
            and row["benchmark_harness"]["checkpoint_loaded"] is False for row in receipts),
        "complete_six_by_five_reports": all(complete_reports(row["target_preparation"]) for row in receipts),
    }
    for key in ("ordered_training_samples", "ordered_validation_samples", "effective_training_config",
                "environment_settings", "selection", "parent_job_spec_canonical_sha256"):
        guards["same_" + key] = same(a[key], b[key])
    guards["same_full_bridge_report_telemetry"] = same(a["target_preparation"]["bridge_report_telemetry"],
                                                     b["target_preparation"]["bridge_report_telemetry"])
    require(all(guards.values()), "receipt/source/input guard failed")
    bundles = []
    try:
        for receipt in receipts:
            bundles.append(VerifiedBundle(receipt))
        ma, mb = [bundle.manifest for bundle in bundles]
        result["embedded_configs"] = {"reference": ma["config"], "candidate": mb["config"]}
        result["bundle_snapshot_ids"] = {"reference": ma["snapshot_id"], "candidate": mb["snapshot_id"]}
        result["bundle_artifacts"] = {name: bundle.artifact for name, bundle in zip(("reference", "candidate"), bundles)}
        guards["same_embedded_config_except_recorded_code_identity"] = same(
            {key: value for key, value in ma["config"].items() if key != "code_sha256"},
            {key: value for key, value in mb["config"].items() if key != "code_sha256"})
        guards["embedded_configs_match_native_source_manifests"] = True
        guards["same_ordered_target_membership"] = same(
            [{key: value for key, value in row.items() if key != "target_sha256"} for row in ma["records"]],
            [{key: value for key, value in row.items() if key != "target_sha256"} for row in mb["records"]])
        require(all(guards.values()), "bundle config or ordered sample binding differs")
        for ordinal, (ra, rb) in enumerate(zip(ma["records"], mb["records"])):
            shards = [bundle.shards[row["target_sha256"]] for bundle, row in zip(bundles, (ra, rb))]
            compressed = [bundle.compressed(shard) for bundle, shard in zip(bundles, shards)]
            compressed_equal = compressed[0] == compressed[1]
            raw_a = expand(compressed[0], shards[0]); compressed[0] = b""
            raw_b = expand(compressed[1], shards[1]); compressed[1] = b""
            raw_equal = raw_a == raw_b
            left, right = json.loads(raw_a), json.loads(raw_b)
            del raw_a, raw_b
            diff = compare_tagged_values(left, right)
            del left, right
            permitted = permitted_timestamp_changes(diff)
            result["per_target"].append({
                "ordinal": ordinal, "split": "training" if ordinal < 3 else "validation", "sample_id": ra["sample_id"],
                "record_descriptors": {"reference": ra, "candidate": rb},
                "shard_descriptors": {"reference": shards[0], "candidate": shards[1]},
                "compressed_sha256_independently_verified": True, "expanded_sha256_independently_verified": True,
                "compressed_bytes_exactly_equal": compressed_equal, "expanded_bytes_exactly_equal": raw_equal,
                "record_descriptors_exactly_equal": same(ra, rb), "shard_descriptors_exactly_equal": same(*shards),
                "ordered_tagged_json_diff": diff, "all_other_ordered_tagged_json_exactly_equal": permitted,
            })
            print(json.dumps({"sample_id": ra["sample_id"], "raw_byte_parity": raw_equal,
                              "differences": diff["difference_count"], "explicit_path_parity": permitted}), flush=True)
        for bundle in bundles:
            bundle.verify_unchanged()
        guards["all_artifacts_unchanged_during_audit"] = True
    finally:
        for bundle in bundles:
            bundle.close()
    guards["receipt_files_unchanged_during_audit"] = all(path.read_bytes() == raw for path, raw in zip(paths, raw_receipts))
    result["raw_expanded_byte_parity"] = all(row["expanded_bytes_exactly_equal"] for row in result["per_target"])
    result["raw_compressed_byte_parity"] = all(row["compressed_bytes_exactly_equal"] for row in result["per_target"])
    result["ordered_target_content_parity_except_explicit_timestamp_paths"] = all(
        row["all_other_ordered_tagged_json_exactly_equal"] for row in result["per_target"])
    result["full_bridge_report_telemetry"] = {name: row["target_preparation"]["bridge_report_telemetry"]
                                            for name, row in zip(("reference", "candidate"), receipts)}
    result["observed_pair_timings"] = {key: {
        "reference_seconds": a["target_preparation"][key], "candidate_seconds": b["target_preparation"][key],
        "reference_seconds_per_span": a["target_preparation"][key] / 6,
        "candidate_seconds_per_span": b["target_preparation"][key] / 6}
        for key in ("elapsed_seconds", "target_generation_seconds", "target_generation_and_artifact_seconds")}
    result["passed"] = all(guards.values()) and len(result["per_target"]) == 6 and result[
        "ordered_target_content_parity_except_explicit_timestamp_paths"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("use a new audit receipt path")
    script_hash = digest(Path(__file__).read_bytes())
    result = {"schema": "native-cold-target-pair-content-audit-v1", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "audit_script_sha256": script_hash, "passed": False, "training_qualification": False,
        "admitted": False, "wall_speed_claim": False, "artifact_rewrites_performed": False,
        "native_objects_hydrated": False, "package_imported": False, "per_target": [],
        "audit_scope": "after timers; independent compressed/expanded hashes and every ordered tagged-JSON node",
        "bounds": {"artifact_bytes": MAX_ARTIFACT, "manifest_bytes": MAX_MANIFEST,
                   "expanded_bytes_per_shard": MAX_SHARD, "referenced_expanded_bytes_per_artifact": MAX_ARTIFACT,
                   "receipt_bytes": MAX_RECEIPT, "pair_at_a_time": True, "retained_difference_limit_per_target": 64},
        "timestamp_exception_policy": {"exact_json_pointer_to_logical_path": ALLOWED_TIMESTAMPS,
            "all_other_mapping_order_array_order_types_and_scalar_values_compared": True,
            "generic_timestamp_stripping": False, "before_after_values_retained": True},
        "pass_scope": "source/config/input integrity and complete ordered content equality except the two exact wall timestamp paths; raw hashes remain separate; no training qualification or speed claim"}
    try:
        audit([args.reference.resolve(), args.candidate.resolve()], result)
    except BaseException as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        result["passed"] = False
    result["audit_script_unchanged"] = digest(Path(__file__).read_bytes()) == script_hash
    result["passed"] = result["passed"] and result["audit_script_unchanged"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"receipt": str(args.output), "passed": result["passed"], "error": result.get("error")}), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
