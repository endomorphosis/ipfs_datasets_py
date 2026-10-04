"""Audit retained GTE768 encoder evidence without promoting a failed head run.

The caller supplies the result SHA. Only encoder files and four producer copies
are read. Positive output establishes byte/report consistency, including finite
native-width vectors, token joins and retained CPU/CUDA numeric parity. Native
execution, model quality, process cleanup, semantics and proof remain unattested.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import types

SHARED_READER_SHA256 = "53aa58f1ca9f7196caa77ccf5553f664c74c168882dd407eaa2cd3dae68bc62f"
SHARED_READER_BYTES = 42806
ENCODER_SOURCE_PINS = (
    {"path": "ipfs_datasets_py/logic/formalization/autoencoder/source_embeddings_device_768.py", "bytes": 24293,
     "sha256": "5737f0863f72bd3383324db6862a45e45055a7c41bd02bf9d7063637faeea748"},
    {"path": "ipfs_datasets_py/logic/formalization/autoencoder/source_embeddings_768_complete.py", "bytes": 9556,
     "sha256": "6f781849dc87eba1b7f0929d292bb10f5724bb1ca5749989feb988cde243c609"},
    {"path": "ipfs_datasets_py/logic/formalization/autoencoder/source_embeddings_768.py", "bytes": 13375,
     "sha256": "cd4b23b87fefe3f80f234a5c85d9e4823139d5040a5507813b88385ee601b4ea"},
    {"path": "ipfs_datasets_py/logic/formalization/autoencoder/gte_multilingual_profile.py", "bytes": 15959,
     "sha256": "d6d6069c98c7f15bd4c6f8a43bd9ffb72032e04a452419a3ff5d9bd95bb06e8e"},
)
IMPLEMENTATION = dict(zip(("device_session", "complete_loader", "reference_producer", "asset_profile"),
                          (pin["sha256"] for pin in ENCODER_SOURCE_PINS)))
ENCODER_JSON_FILES = frozenset({"result.json", "source-rows.json", "encoder-reference.json",
    *[f"encoder-{lane}-warmup.json" for lane in ("cpu", "cuda")],
    *[f"encoder-{lane}-batch{count}.json" for lane in ("cpu", "cuda") for count in (1, 16, 32)]})
ENCODER_COPIES = tuple(f"producers/{i:02d}-{Path(pin['path']).name}" for i, pin in enumerate(ENCODER_SOURCE_PINS, 1))


def _load_shared_reader():
    """Run the known ordinary reader source; never execute archived producers."""
    path = Path(__file__).with_name("audit_native_768_device.py")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not (stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == SHARED_READER_BYTES):
            raise ValueError("frozen ordinary reader identity differs")
        raw = bytearray()
        while len(raw) <= SHARED_READER_BYTES:
            part = os.read(fd, min(65536, SHARED_READER_BYTES+1-len(raw)))
            if not part:
                break
            raw.extend(part)
        after = os.fstat(fd)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
                                 info.st_mtime_ns, info.st_ctime_ns)
        if identity(before) != identity(after) or len(raw) != SHARED_READER_BYTES or hashlib.sha256(raw).hexdigest() != SHARED_READER_SHA256:
            raise ValueError("frozen ordinary reader bytes changed")
    finally:
        os.close(fd)
    module = types.ModuleType("frozen_native768_device_reader")
    module.__file__ = str(path)
    exec(compile(bytes(raw), str(path), "exec"), module.__dict__)
    return module


shared = _load_shared_reader()


class _EncoderReader(shared._Reader):
    def _open(self, name):
        shared._require(name in ENCODER_JSON_FILES or name in ENCODER_COPIES, "encoder-only fixed path required")
        return super()._open(name)


def _current_source(reader, source, expected):
    """Read only a built-in source path; caller/report paths cannot select IO."""
    path = Path(__file__).absolute().parent.parent / source
    directory = shared._open_directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(fd)
            shared._require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == expected["bytes"],
                            "current encoder producer identity differs")
            raw = bytearray()
            while len(raw) <= shared.MAX_FILE_BYTES:
                part = os.read(fd, min(65536, shared.MAX_FILE_BYTES+1-len(raw)))
                if not part:
                    break
                raw.extend(part)
            shared._require(shared._identity(before) == shared._identity(os.fstat(fd)) and len(raw) == expected["bytes"]
                            and hashlib.sha256(raw).hexdigest() == expected["sha256"], "current encoder producer bytes differ")
            return {"path": str(path), "bytes": len(raw), "sha256": expected["sha256"]}, shared._identity(before)
        finally:
            os.close(fd)
    finally:
        os.close(directory)


def _checks(reader, report, check_current_sources):
    require = shared._require
    require(report["schema"] == "native768-device-qualification/v1" and type(report["qualified"]) is bool,
            "native768 report schema/status differs")
    for key in ("production_model_quality_qualified", "codebase768_scan_qualified", "leanstral4096_qualified",
                "proof_authority", "source_semantics_verified", "execution_attestation", "kernel_resource_enforcement"):
        require(report[key] is False, "native report widens qualification authority: " + key)
    pins = report["source_pins"]
    require(type(pins) is list and 5 <= len(pins) <= 32, "encoder producer pins missing")
    repo = Path(__file__).absolute().parent.parent
    current, identities = [], []
    for index, (expected, copy) in enumerate(zip(ENCODER_SOURCE_PINS, ENCODER_COPIES), 1):
        pin = pins[index]
        require(type(pin) is dict and set(pin) == {"path", "bytes", "sha256", "copy"}
                and pin == {"path": str(repo / expected["path"]), "bytes": expected["bytes"],
                            "sha256": expected["sha256"], "copy": copy}, "fixed four encoder producer pins differ")
        raw = reader.read(copy)
        require(len(raw) == expected["bytes"] and hashlib.sha256(raw).hexdigest() == expected["sha256"],
                "retained encoder producer copy differs")
        if check_current_sources:
            actual, identity = _current_source(reader, expected["path"], expected)
            current.append(actual)
            identities.append(identity)
    rows = reader.json("source-rows.json")
    texts = ["Lark must retain books.", "Wren may publish records.", "Finch must not destroy files.",
             *[f"def compare_{i}(a: int, b: int) -> bool:\n    return a < b\n" for i in range(29)]]
    require(rows == [{"id": f"native768-{i}", "source_text": text} for i, text in enumerate(texts)], "fixed32 source rows differ")
    reference = report["encoder_reference"]
    require(type(reference["repetitions"]) is int and reference["repetitions"] == 1
            and reference["profile_id"] == shared.REFERENCE_PROFILE, "single-observation reference metadata differs")
    reference_seconds = shared._number(reference["elapsed_seconds"])
    require(reference_seconds > 0, "positive reference duration required")
    baseline = reader.json("encoder-reference.json", reference["result"])
    require(baseline["schema"] == "gte-complete-native-embedding-production/v1" and baseline["status"] == "completed"
            and baseline["profile_id"] == shared.REFERENCE_PROFILE and baseline["input_row_count"] == baseline["receipt_count"] == 32
            and type(baseline["input_row_count"]) is int and type(baseline["receipt_count"]) is int
            and len(baseline["receipts"]) == 32 and baseline["training_executed"] is False
            and baseline["model_inference_executed"] is True and baseline["download_executed"] is False,
            "unchanged complete encoder reference differs")
    require(baseline["implementation"] == {key: value for key, value in IMPLEMENTATION.items() if key != "device_session"},
            "reference encoder producer source hashes differ")
    require(baseline["execution_profile"] == {"attention_implementation": "eager", "batch_size": 16, "device": "cpu",
            "dtype": "float32", "max_tokens_including_special_tokens": 8192, "normalization": "l2",
            "overlength_policy": "reject", "padding_side": "right", "pooling": "cls"}, "reference encoder numerical profile differs")
    shared._false_authority(baseline)
    vectors = shared._vectors([receipt["embedding"] for receipt in baseline["receipts"]], 32)
    for source, receipt, vector in zip(rows, baseline["receipts"], vectors):
        require(receipt["profile_id"] == shared.REFERENCE_PROFILE, "reference receipt profile differs")
        shared._receipt(receipt, source, vector)
    require(set(report["encoder"]) == {"cpu", "cuda"}, "exact CPU opt-out and CUDA encoder lanes required")
    device = "cuda:" + str(shared._integer(report["hardware"]["device_index"], 0, 255))
    errors, timings, cold = {}, {}, {}
    for lane in ("cpu", "cuda"):
        value = report["encoder"][lane]
        require(set(value["batches"]) == {"1", "16", "32"}, "exact1/16/32 encoder batches required")
        require(value["profile"]["implementation"] == IMPLEMENTATION, "resident encoder producer source hashes differ")
        cold[lane] = shared._number(value["cold_admission_seconds"])
        require(cold[lane] > 0, "positive single-observation cold admission duration required")
        expected_device = "cpu" if lane == "cpu" else device
        warmup = reader.json(f"encoder-{lane}-warmup.json", value["warmup"])
        shared._encoder(warmup, rows, baseline["receipts"], lane, expected_device, warmup=True)
        require(warmup["profile"] == value["profile"], "encoder warmup/lane profile differs")
        timings[lane] = {}
        for count in (1, 16, 32):
            batch = value["batches"][str(count)]
            shared._timing(batch)
            actual = reader.json(f"encoder-{lane}-batch{count}.json", batch["result"])
            error = shared._encoder(actual, rows[:count], baseline["receipts"][:count], lane, expected_device)
            require(actual["profile"] == value["profile"] and shared._number(batch["reference_max_abs_error"]) == error,
                    "encoder numeric error/profile summary differs")
            errors[f"{lane}-{count}"] = error
            timings[lane][str(count)] = {"samples_seconds": batch["samples_seconds"], "median_seconds": batch["median_seconds"]}
        require(value["reference_max_abs_error"] == error and value["token_parity_with_reference"] is True,
                "encoder final numeric/token parity summary differs")
    speedups = {count: timings["cpu"][count]["median_seconds"] / timings["cuda"][count]["median_seconds"]
                for count in ("1", "16", "32")}
    reference_over_cpu = reference_seconds / timings["cpu"]["32"]["median_seconds"]
    require(report["encoder_warm_speedups_cpu_over_cuda"] == speedups
            and shared._number(report["encoder_resident_cpu_speedup_over_single_reload_reference"]) == reference_over_cpu,
            "derived encoder speedup ratios differ")
    # Reopen the same fixed current sources and reject late identity changes.
    if check_current_sources:
        for expected, identity in zip(ENCODER_SOURCE_PINS, identities):
            _, final_identity = _current_source(reader, expected["path"], expected)
            require(final_identity == identity, "current encoder producer changed after entry")
    reader.final_check()
    return {"source_rows": 32, "encoder_batches": [1, 16, 32], "encoder_max_abs_errors": errors,
            "reference_observations": 1, "reference_seconds": reference_seconds,
            "cold_observations_per_lane": 1, "cold_admission_seconds": cold,
            "warm_samples_per_batch": 3, "warm_timings": timings,
            "warm_speedups_cpu_over_cuda": speedups,
            "resident_cpu32_over_single_reload_reference_speedup": reference_over_cpu,
            "ratio_scope": "reported_single_cold_and_reference_observations_and_three_sample_warm_medians",
            "encoder_source_pins": list(ENCODER_SOURCE_PINS), "current_source_pins": current,
            "current_sources_checked": check_current_sources}


def audit_encoder(root, *, expected_result_sha256, check_current_sources=True):
    """Check only the encoder subset against the caller's external result SHA."""
    result = {"schema": "native768-encoder-closed-audit/v1", "qualified": False,
        "encoder_artifacts_consistent": False, "native_combined_qualified": False,
        "head_artifacts_checked": False, "head_qualified": False, "models_loaded": False,
        "native_execution_attested": False, "resource_enforcement_attested": False,
        "process_cleanup_attested": False, "model_quality_qualified": False,
        "proof_authority": False, "source_semantics_verified": False, "leanstral4096_qualified": False,
        "scope": "ordinary_retained_encoder_bytes_and_report_consistency_only",
        "error": None, "retained_pins": []}
    reader = None
    try:
        shared._sha(expected_result_sha256)
        shared._require(type(check_current_sources) is bool, "current-source option must be boolean")
        reader = _EncoderReader(root)
        report = reader.json("result.json")
        shared._require(reader.pins["result.json"]["sha256"] == expected_result_sha256, "external result SHA256 differs")
        result["reported_native_combined_qualified"] = report.get("qualified")
        result["reported_native_error"] = report.get("error")
        result["checks"] = _checks(reader, report, check_current_sources)
        result["qualified"] = result["encoder_artifacts_consistent"] = True
    except (shared.AuditError, OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError, OverflowError) as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if reader is not None:
            result["retained_pins"] = list(reader.pins.values())
            reader.close()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-result-sha256", required=True)
    parser.add_argument("--skip-current-sources", action="store_true")
    args = parser.parse_args(argv)
    result = audit_encoder(args.root, expected_result_sha256=args.expected_result_sha256,
                           check_current_sources=not args.skip_current_sources)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
