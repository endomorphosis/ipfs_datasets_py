"""Prepare exact unreviewed §101 V2 subjects; never assess or authenticate reviews."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

REPOSITORY = Path(__file__).resolve().parents[4]
BASE = REPOSITORY / "docs/autoencoders/evidence/legal-ir-definition-v2-integration-20261015/real_source_probe.py"
BASE_SHA256 = "0703a0729a53514048dbfc3389eb878c114b20ac49f6fcfe89454e4cacd9279f"


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def meta(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def save(path, value, *, raw=False):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value if raw else wire(value))


def check(receipt, name, condition):
    receipt["checks"].append({"check": name, "passed": bool(condition)})
    if not condition:
        raise RuntimeError(name)


def load_base(receipt):
    check(receipt, "reused base driver exact frozen SHA256", meta(BASE)["sha256"] == BASE_SHA256)
    spec = importlib.util.spec_from_file_location("retained_definition_v2_engineering_probe", BASE)
    if spec is None or spec.loader is None:
        raise RuntimeError("retained base driver loader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    check(receipt, "reused base driver selects new checkout", module.REPOSITORY == REPOSITORY)
    receipt["reused_base_driver"] = meta(BASE)
    return module


def original_inputs(output, directory):
    paths = {"candidate_raw": directory / "companion.json", "report_raw": directory / "report.json",
        "request_raw": directory / "request.json", "raw_html": output / "source.html",
        "sampling_report_raw": output / "sampling-report.json",
        "descriptor_raw": output / "acquisition-descriptor.json"}
    return {name: path.read_bytes() for name, path in paths.items()}, paths


def subjects(output, receipt, base):
    from ipfs_datasets_py.logic.autoformal import corpus_definition_review_v2 as review
    from ipfs_datasets_py.logic.autoformal import legal_statutory_context_v2 as contexts
    from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
    from ipfs_datasets_py.logic.autoformal import corpus_graph_exchange as exchange

    check(receipt, "subject owners loaded from selected checkout", all(
        Path(owner.__file__).resolve().is_relative_to(REPOSITORY)
        for owner in (review, contexts, dependencies, exchange)))
    receipt["subject_families"] = {}
    for family in ("fol", "tdfol"):
        directory = output / family
        inputs, paths = original_inputs(output, directory)
        candidate = json.loads(inputs["candidate_raw"])
        sampling = json.loads(inputs["sampling_report_raw"])
        descriptor = json.loads(inputs["descriptor_raw"])
        hashes = {name: base.sha(raw) for name, raw in inputs.items()}
        pins = dict(candidate_sha256=hashes["candidate_raw"], candidate_cid=candidate["record_cid"],
            graph_cid=candidate["graph"]["record_cid"], request_sha256=hashes["request_raw"],
            report_sha256=hashes["report_raw"], raw_sha256=hashes["raw_html"], raw_bytes=len(inputs["raw_html"]),
            extracted_sha256=candidate["source_version"]["extracted_view"]["sha256"],
            sampling_report_sha256=hashes["sampling_report_raw"],
            sampling_report_full_canonical_sha256=receipt["sampling_full_canonical_sha256"],
            descriptor_sha256=hashes["descriptor_raw"], descriptor_full_canonical_sha256=base.DESCRIPTOR_CANONICAL)
        save(directory / "candidate-input-pins.json", pins)
        save(directory / "candidate-input-files.json", {name: meta(path) for name, path in paths.items()})
        physical = candidate["source_occurrences"]
        check(receipt, family + " six physical occurrences retained", len(physical) == 6)
        packets, population, packet_files = [], [], []
        packet_directory = directory / "contexts"
        packet_directory.mkdir(mode=0o700)
        for index, occurrence in enumerate(physical):
            packet = contexts.build_context_packet_v2(sampling["document_view_report"], inputs["raw_html"],
                char_start=occurrence["start_char"], char_end=occurrence["end_char"],
                expected_report_sha256=sampling["document_view_report_sha256"], descriptor=descriptor,
                expected_descriptor_sha256=pins["descriptor_full_canonical_sha256"],
                expected_raw_sha256=pins["raw_sha256"], expected_raw_bytes=pins["raw_bytes"],
                limits=sampling["document_view_report"]["limits"], dependency_requests=None)
            raw = wire(packet)
            path = packet_directory / (str(index).zfill(4) + ".json")
            save(path, raw, raw=True)
            identity = occurrence["record_cid"]
            packets.append(dict(source_occurrence_cid=identity, packet_raw=raw, dependency_requests=None))
            population.append(dict(source_occurrence_cid=identity, packet_sha256=base.sha(raw)))
            packet_files.append(dict(source_occurrence_cid=identity, file=path.name, **meta(path)))
            check(receipt, family + " exact open packet " + str(index), len(packet["dependency_slots"]) == 6
                and all(slot["open"] is True and slot["status"] == "open_missing"
                        and slot["attachments"] == [] and slot["semantic_attachment_verified"] is False
                        for slot in packet["dependency_slots"])
                and packet["context_closure_verified"] is False
                and all(value is False for value in packet["authority"].values()))
        save(directory / "expected-context-population.json", population)
        save(directory / "context-input-files.json", packet_files)
        replay = dict(candidate_inputs=inputs, expected_candidate_pin=pins,
            context_inputs=packets, expected_context_population=population)
        preparation = review.prepare_definition_review_evidence_v2(**replay)
        manifest = dependencies.build_dependency_manifest(preparation["artifacts"], preparation["edges"],
            expected_artifact_ids=preparation["expected_artifact_ids"])
        required = preparation["expected_artifact_ids"]
        subject = review.build_definition_review_subject_v2(preparation, manifest, **replay,
            expected_manifest_sha256=manifest["manifest_sha256"], required_dependency_ids=required)
        for name, body in (("preparation.json", preparation), ("dependency-manifest.json", manifest),
                           ("required-dependency-ids.json", required), ("subject.json", subject)):
            save(directory / name, body)
        check(receipt, family + " all 36 slots open and no authority granted",
            len(preparation["context_slot_ids"]) == len(set(preparation["context_slot_ids"])) == 36
            and all(preparation[key] is False for key in review.FALSE_FLAGS)
            and all(subject["native_binding"][key] is False for key in review.FALSE_FLAGS))
        cold_inputs, _ = original_inputs(output, directory)
        cold_packets = []
        for item in json.loads((directory / "context-input-files.json").read_bytes()):
            raw = (packet_directory / item["file"]).read_bytes()
            check(receipt, family + " cold packet transport pin " + item["file"],
                  len(raw) == item["bytes"] and base.sha(raw) == item["sha256"])
            cold_packets.append(dict(source_occurrence_cid=item["source_occurrence_cid"],
                                     packet_raw=raw, dependency_requests=None))
        cold_replay = dict(candidate_inputs=cold_inputs,
            expected_candidate_pin=json.loads((directory / "candidate-input-pins.json").read_bytes()),
            context_inputs=cold_packets,
            expected_context_population=json.loads((directory / "expected-context-population.json").read_bytes()))
        cold_subject = review.build_definition_review_subject_v2(
            json.loads((directory / "preparation.json").read_bytes()),
            json.loads((directory / "dependency-manifest.json").read_bytes()), **cold_replay,
            expected_manifest_sha256=manifest["manifest_sha256"],
            required_dependency_ids=json.loads((directory / "required-dependency-ids.json").read_bytes()))
        check(receipt, family + " cold complete subject equals saved original", cold_subject == subject
              == json.loads((directory / "subject.json").read_bytes()))
        loaded = exchange.load_graph_bundle(directory / "graph-bundle",
            expected_manifest_sha256=receipt["families"][family]["graph_manifest_sha256"])
        check(receipt, family + " subject binds exact exported graph", subject["graph_id"]
              == loaded["snapshot"]["record_cid"] == candidate["graph"]["record_cid"]
              and loaded["snapshot"] == candidate["graph"])
        receipt["subject_families"][family] = dict(status="subject_prepared_awaiting_actual_reviews",
            subject=meta(directory / "subject.json"), preparation_cid=preparation["record_cid"],
            graph_cid=subject["graph_id"], context_packets=6, open_slots=36,
            dependency_artifacts=len(preparation["artifacts"]), dependency_edges=len(preparation["edges"]),
            producer_pins=preparation["producer_pins"], native_producer_pins=preparation["native_producer_pins"],
            reviews=0, assessment_performed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", required=True, type=Path)
    output = parser.parse_args().output_directory.resolve()
    os.umask(0o077)
    sys.dont_write_bytecode = True
    output.mkdir(mode=0o700, exist_ok=False)
    started, base, before = time.monotonic(), None, None
    receipt = dict(schema="legal-ir-definition-v2-real-source-review-subject-probe/v1", status="failed", checks=[],
        driver=meta(Path(__file__).resolve()), repository=str(REPOSITORY),
        subject_status="subject_preparation_incomplete", reviews=0, assessment_performed=False,
        registry_policy_keys_signer_or_review_evaluation_clock_selected=False,
        source_meaning_reviewed=False, context_closure_verified=False, admitted=False,
        training_gold_qualified=False, lean_compilation_verified=False, proof_authority=False,
        limitations=["Real source is retained, but the whole post-means list remains ONE opaque caller-declared atom.",
            "Legal applicability is unreviewed and the legal as-of date remains unknown.",
            "This probe prepares subjects only: no registry, policy, keys, signing, assessment or actual reviews are chosen.",
            "Open context slots are not exhaustive legal dependency closure; no semantic/training/Lean admission follows.",
            "Disk replay uses current public owners in this process, not a separate interpreter or native Lean build."])
    try:
        base = load_base(receipt)
        before = {name: meta(path) for name, (path, _, _) in base.INPUTS.items()}
        receipt["historical_inputs_before"] = before
        base.run(output, receipt)
        subjects(output, receipt, base)
        receipt["subject_status"] = "subject_prepared_awaiting_actual_reviews"
        check(receipt, "all output files and directories private", all(
            p.stat().st_mode & 0o077 == 0 for p in [output, *output.rglob("*")]))
    except Exception as error:
        receipt["error"] = {"type": type(error).__name__, "message": str(error)[:4096]}
    try:
        check(receipt, "reused base driver unchanged", meta(BASE)["sha256"] == BASE_SHA256)
        if before is not None:
            after = {name: meta(path) for name, (path, _, _) in base.INPUTS.items()}
            receipt["historical_inputs_after"] = after
            check(receipt, "historical source inputs unchanged", before == after)
    except Exception as error:
        receipt["guard_error"] = {"type": type(error).__name__, "message": str(error)[:4096]}
    receipt["status"] = "pass" if "error" not in receipt and "guard_error" not in receipt else "failed"
    receipt["elapsed_seconds"] = time.monotonic() - started
    receipt["files"] = [meta(path) for path in sorted(output.rglob("*")) if path.is_file()]
    save(output / "probe-receipt.json", receipt)
    print(json.dumps({"status": receipt["status"], "receipt": str(output / "probe-receipt.json")}))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
