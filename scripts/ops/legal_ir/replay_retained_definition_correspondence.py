#!/usr/bin/env python3
"""Replay retained section 101 source into unsigned V2 review correspondence.

Run only through the admitted owned-validation owner. This standalone driver
uses private regular output files and no model, network, signatures or compiler.
The explicit definition and scope remain unreviewed caller declarations.
"""
from __future__ import annotations

import argparse
import builtins
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


ROOT = Path(__file__).resolve().parents[3]
SELECTED_CHECK = "retained-section101-definition-review-correspondence-fol-tdfol-with-eight-refusals"
SCHEMA = "legal-ir-retained-definition-correspondence-replay/v1"
DESCRIPTOR_SCHEMA = "retained-definition-correspondence-inputs/v1"
MAX_DESCRIPTOR_BYTES = 64 * 1024
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_EXPORT_BYTES = 30_000_000
MAX_EXPORT_FILES = 128
C02 = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-validation-runs/legal-ir-definition-use-review-v2-integration-20261015-c-02/exports")
SAMPLER = Path("/home/barberb/lift_coding/artifacts/legal-corpus-source-structured-sampling-20261015-01/actual-section101-01")
INPUT_FILES = (
    ("c02_receipt", C02 / "replay-receipt.json"),
    ("source_review_receipt", C02 / "prior-replay-receipt.json"),
    ("sampler_receipt", SAMPLER / "integration-receipt.json"),
    ("bundle", C02 / "review-bundle.json"),
    ("raw_html", C02 / "source.html"),
    ("descriptor", C02 / "acquisition-descriptor.json"),
    ("acquisition_receipt", C02 / "acquisition-receipt.json"),
    ("sampling_report", SAMPLER / "sampling-report.json"),
    ("fol_request", C02 / "actual-fol-request.json"),
    ("tdfol_request", C02 / "actual-tdfol-request.json"),
    ("fol_result", C02 / "actual-fol-result.json"),
    ("tdfol_result", C02 / "actual-tdfol-result.json"),
    ("actual_responses", C02 / "actual-responses.json"),
)


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return sha(wire(value))


def load(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            need(key not in value, "duplicate original JSON key")
            value[key] = item
        return value

    def constant(_):
        raise ValueError("nonfinite original JSON")

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_exact(path, length, expected, *, maximum=MAX_INPUT_BYTES):
    path = Path(path)
    need(path.is_absolute() and path.resolve(strict=True) == path,
         "absolute unaliased retained input path required")
    need(type(length) is int and 0 < length <= maximum
         and type(expected) is str and re.fullmatch(r"[0-9a-f]{64}", expected) is not None,
         "bounded exact file length and independent SHA256 required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
             and before.st_size == length, "unaliased regular retained input differs")
        raw = stream.read(length + 1)
        after = os.fstat(stream.fileno())
    need(identity(before) == identity(after) == identity(path.lstat())
         and len(raw) == length and sha(raw) == expected,
         "retained file identity, original length or independent pin differs")
    return raw, identity(after)


def original_descriptor(path, expected):
    path = Path(path)
    info = path.lstat()
    raw, witness = read_exact(path, info.st_size, expected, maximum=MAX_DESCRIPTOR_BYTES)
    value = load(raw)
    need(type(value) is dict and set(value) == {"schema", "inputs"}
         and value["schema"] == DESCRIPTOR_SCHEMA, "closed retained input descriptor required")
    rows = value["inputs"]
    need(type(rows) is list and len(rows) == len(INPUT_FILES), "complete ordered retained inputs required")
    for row, (name, expected_path) in zip(rows, INPUT_FILES, strict=True):
        need(type(row) is dict and set(row) == {"name", "path", "bytes", "sha256"}
             and row["name"] == name and row["path"] == str(expected_path),
             "retained input role, fixed original path or field set differs")
        need(type(row["bytes"]) is int and 0 < row["bytes"] <= MAX_INPUT_BYTES,
             "bounded original retained input size required")
    need(sum(row["bytes"] for row in rows) <= MAX_INPUT_BYTES, "aggregate retained input bound exceeded")
    return value, raw, witness


def no_authority(value):
    if type(value) is dict:
        if "authority" in value:
            need(type(value["authority"]) is dict and value["authority"]
                 and all(flag is False for flag in value["authority"].values()),
                 "an authority flag was raised")
        for key in ("training_mask", "evaluation_gold_mask"):
            if key in value:
                need(type(value[key]) is int and value[key] == 0, "a gold mask was raised")
        for item in value.values():
            no_authority(item)
    elif type(value) is list:
        for item in value:
            no_authority(item)


class Exports:
    def __init__(self, path):
        self.path = Path(path)
        need(self.path.is_absolute() and self.path.resolve(strict=True) == self.path,
             "real absolute existing output directory required")
        info = self.path.lstat()
        need(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
             and info.st_uid == os.getuid() and not any(self.path.iterdir()),
             "private empty owned 0700 export directory required")
        temporary = Path(os.environ.get("TMPDIR", ""))
        need(temporary.is_absolute() and temporary.resolve(strict=True) == temporary
             and temporary.is_dir() and temporary.name == "tmp"
             and self.path == temporary.parent / "exports"
             and Path.cwd().resolve() == ROOT,
             "native owned-validation layout and exact repository cwd required")
        self.directory = (info.st_dev, info.st_ino, info.st_uid, info.st_mode)
        self.files, self.total = {}, 0

    def check(self):
        info = self.path.lstat()
        need((info.st_dev, info.st_ino, info.st_uid, info.st_mode) == self.directory
             and {path.name for path in self.path.iterdir()} == set(self.files),
             "owned output directory or closed file population changed")

    def add(self, name, raw):
        need(type(raw) is bytes and Path(name).name == name
             and re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,100}", name) is not None
             and name not in self.files, "unique flat output filename and original bytes required")
        need(len(self.files) < MAX_EXPORT_FILES and self.total + len(raw) <= MAX_EXPORT_BYTES,
             "closed export count or aggregate byte budget exceeded")
        self.check()
        fd = os.open(self.path / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        row = {"path": name, "bytes": len(raw), "sha256": sha(raw)}
        read_exact(self.path / name, row["bytes"], row["sha256"], maximum=MAX_EXPORT_BYTES)
        self.files[name] = row
        self.total += len(raw)
        self.check()
        return dict(row)

    def json(self, name, value):
        return self.add(name, wire(value) + b"\n")

    def read(self, row):
        need(self.files.get(row["path"]) == row, "retained output reference differs")
        return read_exact(self.path / row["path"], row["bytes"], row["sha256"],
                          maximum=MAX_EXPORT_BYTES)[0]

    def verify(self):
        self.check()
        for row in self.files.values():
            self.read(row)
        need(sum(path.lstat().st_size for path in self.path.iterdir()) == self.total,
             "actual aggregate export population differs")


def external_operation_guards():
    forbidden = ("symai", "torch", "transformers", "tensorflow")
    attempts = []

    def prohibited(name):
        return any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)

    need(not any(prohibited(name) for name in sys.modules), "optional model runtime already loaded")
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if prohibited(name):
            attempts.append(name)
            raise AssertionError("optional model runtime import during source replay: " + name)
        return original_import(name, *args, **kwargs)

    class Guard:
        def find_spec(self, fullname, path=None, target=None):
            if prohibited(fullname):
                attempts.append(fullname)
                raise AssertionError("optional model import lookup during source replay: " + fullname)
            return None

    def audit(event, args):
        if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "socket.connect"}:
            attempts.append(event)
            raise AssertionError("external operation during retained source replay: " + event)

    builtins.__import__ = guarded_import
    sys.meta_path.insert(0, Guard())
    sys.addaudithook(audit)
    return attempts, prohibited


def main():
    os.umask(0o077)
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-descriptor", required=True)
    parser.add_argument("--expected-input-descriptor-sha256", required=True)
    parser.add_argument("--output-directory", required=True)
    options = parser.parse_args()
    exports = Exports(options.output_directory)
    driver_raw = Path(__file__).read_bytes()
    descriptor, descriptor_raw, descriptor_witness = original_descriptor(
        options.input_descriptor, options.expected_input_descriptor_sha256)
    rows = {row["name"]: row for row in descriptor["inputs"]}
    retained, witnesses = {}, {}
    for name, row in rows.items():
        retained[name], witnesses[name] = read_exact(row["path"], row["bytes"], row["sha256"])

    def recheck_inputs():
        current, witness = read_exact(options.input_descriptor, len(descriptor_raw),
                                     options.expected_input_descriptor_sha256,
                                     maximum=MAX_DESCRIPTOR_BYTES)
        need(current == descriptor_raw and witness == descriptor_witness, "input descriptor changed")
        for name, row in rows.items():
            current, witness = read_exact(row["path"], row["bytes"], row["sha256"])
            need(current == retained[name] and witness == witnesses[name], "retained input changed: " + name)

    checks, controls, calls = [], [], []

    def passed(name):
        need(name not in checks, "duplicate named check")
        checks.append(name)

    def call(name, function, *args, **kwargs):
        recheck_inputs()
        calls.append(name)
        try:
            return function(*args, **kwargs)
        finally:
            recheck_inputs()

    c02, previous, sampler_receipt = [load(retained[name]) for name in (
        "c02_receipt", "source_review_receipt", "sampler_receipt")]
    need(c02["schema"] == "legal-ir-definition-candidate-binding-replay/v1"
         and previous["schema"] == "legal-ir-sampled-source-review-replay/v1"
         and sampler_receipt["schema"] == "legal-source-structured-sampling-actual/v1"
         and all(item["all_checks_passed"] is True for item in (c02, previous, sampler_receipt)),
         "retained successful receipt chain differs")
    for receipt, selected in ((c02, [name for name, path in INPUT_FILES if path.parent == C02
                                    and name != "c02_receipt"]),
                              (previous, ["bundle", "raw_html", "descriptor", "acquisition_receipt"])):
        index = {row["path"]: row for row in receipt["outputs"]}
        need(len(index) == len(receipt["outputs"]), "duplicate historical output filename")
        for name in selected:
            row = rows[name]
            need(index[Path(row["path"]).name] == {"path": Path(row["path"]).name,
                 "bytes": row["bytes"], "sha256": row["sha256"]}, "historical output receipt differs: " + name)
    need(sampler_receipt["report"] == {key: rows["sampling_report"][key]
         for key in ("path", "bytes", "sha256")}
         and c02["prior_receipt_sha256"] == rows["source_review_receipt"]["sha256"],
         "sampler or earlier source-review receipt commitment differs")
    bundle, sampling, acquisition_descriptor, acquisition = [load(retained[name]) for name in (
        "bundle", "sampling_report", "descriptor", "acquisition_receipt")]
    responses = load(retained["actual_responses"])
    need(responses == [] and type(responses) is list
         and bundle["sampling_report"] == sampling
         and digest(bundle) == c02["bundle_full_canonical_sha256"] == previous["bundle_full_canonical_sha256"]
         and digest(sampling) == sampler_receipt["full_canonical_report_sha256"]
         == c02["original_sampling_full_canonical_sha256"] == previous["original_sampling_full_canonical_sha256"]
         and digest(acquisition_descriptor) == c02["descriptor_full_canonical_sha256"]
         == acquisition["descriptor_canonical_sha256"]
         and acquisition["source_or_meaning_reviewed"] is False,
         "complete original source transport/canonical correspondence differs")
    passed("independently_pinned_original_receipt_source_and_request_chain")
    attempts, prohibited = external_operation_guards()
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
    from ipfs_datasets_py.logic.autoformal import corpus_definition_adapter_v2 as adapter
    from ipfs_datasets_py.logic.autoformal import corpus_definition_review_v2 as review
    from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
    from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampler
    from ipfs_datasets_py.logic.autoformal import legal_source_sampling_definition_binding_v2 as binding
    from ipfs_datasets_py.logic.autoformal import legal_source_sampling_definition_review_v2 as correspondence
    from ipfs_datasets_py.logic.autoformal import legal_statutory_context_v2 as context

    modules = (contracts, adapter, review, dependencies, sampler, binding, correspondence, context)

    def producers():
        observed = {}
        for module in modules:
            path = Path(module.__file__).resolve()
            need(path.is_relative_to(ROOT), "actual owner imported outside the selected repository")
            observed[str(path)] = sha(path.read_bytes())
        return observed

    source_pins = producers()
    need(digest(sampling) == sampler.source_sampling_report_sha256(sampling), "public sampler hash differs")
    units = [row for row in sampling["records"] if row["schema"] == sampler.UNIT_SCHEMA]
    original_contexts = [row for row in sampling["records"] if row["schema"] == "legal-corpus-context-declaration/v1"]
    need(sampling["counts"]["blocks"] == len(units) == len(bundle["guides"]) == 560
         and len(sampling["records"]) == 1681
         and sum(bool(row["candidate_input"]) for row in units) == 134
         and len(original_contexts) == 560
         and sum(len(row["missing_requirements"]) for row in original_contexts) == 3360
         and sum(len(row["unanswered_question_ids"]) for row in bundle["guides"]) == 8400
         and c02["actual_response_count"] == c02["actual_reviews"] == previous["actual_reviews"] == 0,
         "complete 560-subject source denominator differs")
    no_authority(bundle)
    passed("complete_560_subjects_134_candidates_426_controls_8400_blanks_3360_original_obligations")
    original_refs = {name: exports.add("retained-" + name.replace("_", "-") + (".html" if name == "raw_html" else ".json"), raw)
                     for name, raw in retained.items()}
    descriptor_ref = exports.add("input-descriptor.json", descriptor_raw)
    original_binding = bundle["manifest"]["input_binding"]
    required_binding_fields = {
        "descriptor", "expected_descriptor_sha256", "expected_raw_sha256", "expected_raw_bytes",
    }
    need(type(original_binding) is dict
         and required_binding_fields <= set(original_binding)
         <= required_binding_fields | {"view_limits", "sampling_limits"},
         "closed original sampler input binding required")
    need(original_binding["descriptor"] == acquisition_descriptor
         and original_binding["expected_descriptor_sha256"] == digest(acquisition_descriptor)
         and original_binding["expected_raw_sha256"] == sha(retained["raw_html"])
         and type(original_binding["expected_raw_bytes"]) is int
         and original_binding["expected_raw_bytes"] == len(retained["raw_html"]),
         "original sampler input binding differs from retained descriptor/source pins")
    replay = deepcopy(original_binding)
    replay["expected_sampling_report_sha256"] = digest(sampling)
    need({key: value for key, value in replay.items() if key != "expected_sampling_report_sha256"}
         == original_binding, "original omitted-versus-provided replay inputs changed")
    families, summaries, comparisons = {}, [], []
    for family in ("fol", "tdfol"):
        prefix = "actual-" + family + "-"
        request_raw = retained[family + "_request"]
        request = load(request_raw)
        historical = load(retained[family + "_result"])
        need(request["family"] == historical["definition_report"]["family"] == family
             and request["declaration"] == historical["definition_report"]["declaration"],
             "original family request/declaration differs from C02")
        result = call(family + "_binding_prepare", binding.prepare_definition_binding_v2,
            request_raw, bundle, [], retained["raw_html"],
            expected_request_sha256=sha(request_raw), expected_bundle_sha256=digest(bundle),
            expected_response_sha256s=[], **replay)
        report, candidate, population = result["definition_report"], result["candidate"], result["population"]
        need(population["subject_count"] == population["counts"]["pending"] == 560
             and population["response_count"] == 0
             and result["binding"]["selected_subject_count"] == 2
             and result["binding"]["status"] == "pending"
             and all(row["state"] == "pending" and row["response_refs"] == [] for row in result["binding"]["required_subjects"])
             and all(candidate[key] is False for key in adapter.FALSE_FLAGS), "current binding acquired authority or lost population")
        stable = ("declaration", "native_ast", "lean_body", "symbols", "source_version",
                  "source_occurrences", "source_bindings", "source_context_frontier")
        need(all(report[key] == historical["definition_report"][key] for key in stable),
             "current generation changed the retained declared source/native structure")
        frontier = report["source_context_frontier"]
        need(frontier["original_units"] == 560 and frontier["original_open_context_obligations"] == 3360
             and frontier["selected_original_occurrences"] == 2 and frontier["derived_role_occurrences"] == 4
             and frontier["selected_physical_occurrences"] == 6 and frontier["selected_open_context_obligations"] == 36
             and frontier["unselected_original_occurrences"] == 558, "selected and whole-source populations were conflated")
        graph = candidate["graph"]
        nodes = {row["record_cid"] for row in graph["nodes"]}
        need(len(graph["nodes"]) == 15 and len(graph["edges"]) == 26
             and all(edge["src_cid"] in nodes and edge["dst_cid"] in nodes for edge in graph["edges"])
             and sum(edge["relation"] == "DEFINES" for edge in graph["edges"]) == 1
             and not any(edge["relation"] == "USES_DEFINITION" for edge in graph["edges"]),
             "definition-only closed graph changed its supported structure")
        six_refs = {
            "candidate_raw": exports.add(prefix + "candidate-input.json", wire(candidate) + b"\n"),
            "report_raw": exports.add(prefix + "report-input.json", wire(report)),
            "request_raw": original_refs[family + "_request"],
            "raw_html": original_refs["raw_html"],
            "sampling_report_raw": original_refs["sampling_report"],
            "descriptor_raw": original_refs["descriptor"],
        }
        inputs = {key: exports.read(row) for key, row in six_refs.items()}
        pins = {
            "candidate_sha256": sha(inputs["candidate_raw"]), "candidate_cid": candidate["record_cid"],
            "graph_cid": graph["record_cid"], "request_sha256": sha(inputs["request_raw"]),
            "report_sha256": sha(inputs["report_raw"]), "raw_sha256": sha(inputs["raw_html"]),
            "raw_bytes": len(inputs["raw_html"]), "extracted_sha256": candidate["source_version"]["extracted_view"]["sha256"],
            "sampling_report_sha256": sha(inputs["sampling_report_raw"]), "sampling_report_full_canonical_sha256": digest(sampling),
            "descriptor_sha256": sha(inputs["descriptor_raw"]), "descriptor_full_canonical_sha256": digest(acquisition_descriptor),
        }
        need(pins["report_sha256"] == result["binding"]["definition_report_ref"]["sha256"]
             and not inputs["report_raw"].endswith(b"\n"), "exact compact candidate report transport was changed")
        custody_ref = exports.json(prefix + "original-input-custody.json", {
            "schema": "retained-definition-original-input-custody/v1", "family": family,
            "inputs": six_refs, "candidate_pin": pins,
            "retained_originals": ["request_raw", "raw_html", "sampling_report_raw", "descriptor_raw"],
            "newly_frozen_current_generation_inputs": ["candidate_raw", "report_raw"],
            "historical_exported_report_is_not_candidate_report_transport": True,
        })
        packets, packet_pins, packet_refs = [], [], []
        for ordinal, occurrence in enumerate(candidate["source_occurrences"]):
            packet = call(family + "_context_" + str(ordinal), context.build_context_packet_v2,
                sampling["document_view_report"], inputs["raw_html"], char_start=occurrence["start_char"],
                char_end=occurrence["end_char"], expected_report_sha256=sampling["document_view_report_sha256"],
                descriptor=acquisition_descriptor, expected_descriptor_sha256=digest(acquisition_descriptor),
                expected_raw_sha256=pins["raw_sha256"], expected_raw_bytes=pins["raw_bytes"],
                limits=sampling["document_view_report"]["limits"])
            ref = exports.json(prefix + f"context-{ordinal:02d}.json", packet)
            packets.append({"source_occurrence_cid": occurrence["record_cid"],
                            "packet_raw": exports.read(ref), "dependency_requests": None})
            packet_pins.append({"source_occurrence_cid": occurrence["record_cid"], "packet_sha256": ref["sha256"]})
            packet_refs.append({"source_occurrence_cid": occurrence["record_cid"], "packet": ref,
                                "packet_canonical_sha256": digest(packet), "dependency_requests": None})
        need(len(packets) == 6 and sum(len(load(row["packet_raw"])["dependency_slots"]) for row in packets) == 36,
             "six physical contexts and 36 open slots required")
        context_ref = exports.json(prefix + "context-index.json", {"schema": "retained-definition-context-index/v1",
            "contexts": packet_refs, "expected_context_population": packet_pins})
        evidence = dict(candidate_inputs=inputs, expected_candidate_pin=pins, context_inputs=packets,
                        expected_context_population=packet_pins)
        preparation = call(family + "_review_prepare", review.prepare_definition_review_evidence_v2, **evidence)
        manifest = call(family + "_manifest", dependencies.build_dependency_manifest,
            preparation["artifacts"], preparation["edges"], expected_artifact_ids=preparation["expected_artifact_ids"])
        subject = call(family + "_subject", review.build_definition_review_subject_v2, preparation, manifest,
            **evidence, expected_manifest_sha256=manifest["manifest_sha256"], required_dependency_ids=preparation["expected_artifact_ids"])
        result_ref = exports.json(prefix + "binding-result.json", result)
        preparation_ref = exports.json(prefix + "review-preparation.json", preparation)
        manifest_ref = exports.json(prefix + "dependency-manifest.json", manifest)
        subject_ref = exports.json(prefix + "review-subject.json", subject)
        arguments = dict(expected_binding_sha256=digest(result), expected_subject_sha256=digest(subject),
            binding_replay_inputs={"request_raw": inputs["request_raw"], "bundle": bundle, "responses": [],
                "raw_html": inputs["raw_html"], "expected_request_sha256": pins["request_sha256"],
                "expected_bundle_sha256": digest(bundle), "expected_response_sha256s": [],
                "sampling_replay_inputs": replay}, **evidence, dependency_manifest=manifest,
            expected_manifest_sha256=manifest["manifest_sha256"], required_dependency_ids=preparation["expected_artifact_ids"])
        link = call(family + "_correspondence_prepare", correspondence.prepare_definition_review_correspondence_v2,
                    result, subject, **arguments)
        need(link["population_subjects"] == population["subjects"] and link["population_counts"] == population["counts"]
             and link["population_subject_count"] == 560 and link["response_count"] == 0
             and link["required_subjects"] == result["binding"]["required_subjects"]
             and link["source_role_bindings"] == result["binding"]["source_role_bindings"]
             and link["source_identity"] == result["binding"]["source_identity"]
             and len(link["occurrence_context_links"]) == 6 and len(link["context_slot_ids"]) == 36
             and link["context_slot_ids"] == subject["context_slot_ids"]
             and link["unsigned"] is True and link["assessment_created"] is False,
             "complete unsigned source-to-subject correspondence differs")
        for row, occurrence, packet in zip(link["occurrence_context_links"], candidate["source_occurrences"], packet_refs, strict=True):
            need(row["occurrence_ref"] == {"schema": occurrence["schema"], "record_cid": occurrence["record_cid"], "sha256": digest(occurrence)}
                 and row["packet_sha256"] == packet["packet"]["sha256"]
                 and row["packet_canonical_sha256"] == packet["packet_canonical_sha256"]
                 and row["source_role_bindings"] == [role for role in result["binding"]["source_role_bindings"]
                     if role["source_occurrence_cid"] == occurrence["record_cid"]], "exact physical occurrence/context/role join differs")
        link_ref = exports.json(prefix + "correspondence.json", link)
        need(call(family + "_correspondence_validate", correspondence.validate_definition_review_correspondence_v2,
             load(exports.read(link_ref)), load(exports.read(result_ref)), load(exports.read(subject_ref)),
             expected_correspondence_sha256=digest(link), **arguments) == link,
             "public correspondence regeneration from retained artifacts differs")
        no_authority(result)
        no_authority(link)
        need(all(preparation[key] is False for key in review.FALSE_FLAGS), "review preparation acquired authority")
        comparison = {"family": family, "unchanged_declared_fields": list(stable),
            "historical_result": original_refs[family + "_result"], "current_result": result_ref,
            "historical_candidate_cid": historical["candidate"]["record_cid"], "current_candidate_cid": candidate["record_cid"],
            "historical_producer_pins": historical["definition_report"]["producer_pins"],
            "current_producer_pins": report["producer_pins"], "generation_identity_is_not_semantic_admission": True}
        comparison_ref = exports.json(prefix + "source-generation-comparison.json", comparison)
        index_ref = exports.json(prefix + "replay-index.json", {
            "schema": "retained-definition-correspondence-family-index/v1", "family": family,
            "original_inputs": custody_ref, "contexts": context_ref, "binding_result": result_ref,
            "preparation": preparation_ref, "manifest": manifest_ref, "subject": subject_ref,
            "correspondence": link_ref, "generation_comparison": comparison_ref,
            "binding_full_canonical_sha256": digest(result), "subject_full_canonical_sha256": digest(subject),
            "manifest_internal_sha256": manifest["manifest_sha256"], "manifest_full_canonical_sha256": digest(manifest),
            "correspondence_full_canonical_sha256": digest(link), "required_dependency_ids": preparation["expected_artifact_ids"],
        })
        families[family] = dict(result=result, subject=subject, arguments=arguments, link=link, index=index_ref,
                                packets=packet_refs, link_ref=link_ref)
        summaries.append({"family": family, "replay_index": index_ref, "selected_subjects": 2,
            "physical_context_occurrences": 6, "selected_open_context_slots": 36, "whole_population_pending": 560,
            "actual_responses": 0, "actual_reviews": 0, "graph_nodes": 15, "graph_edges": 26,
            "native_ast_sha256": digest(report["native_ast"]), "correspondence_sha256": digest(link)})
        comparisons.append(comparison_ref)
        passed(family + "_exact_original_inputs_six_contexts_current_subject_and_full_population_link")
        passed(family + "_public_full_regeneration_preserves_unsigned_authority_and_retained_artifacts")

    need(all(families["fol"]["result"]["definition_report"][key]
             == families["tdfol"]["result"]["definition_report"][key]
             for key in ("native_ast", "lean_body", "symbols")),
         "declared pure first-order subset differs between family routes")
    passed("declared_pure_first_order_subset_matches_both_family_routes")
    base = families["fol"]

    def refuse(label, *, args=None, offered=None, expected=None, changes):
        payload_ref = exports.json("negative-" + label + "-control.json", {
            "schema": "retained-definition-correspondence-refusal-input/v1", "control": label,
            "base_family_index": base["index"], "changes": changes,
            "self_recomputed_pins_authenticate_nothing": True})
        try:
            call("negative_" + label, correspondence.validate_definition_review_correspondence_v2,
                 base["link"] if offered is None else offered, base["result"], base["subject"],
                 expected_correspondence_sha256=digest(base["link"]) if expected is None else expected,
                 **(base["arguments"] if args is None else args))
        except ValueError as error:
            controls.append({"name": label, "refused": True, "input": payload_ref,
                             "exception_type": type(error).__name__, "reason": str(error)[:2000]})
            passed("negative_" + label + "_refused")
        else:
            raise ValueError("negative control unexpectedly accepted: " + label)

    wrong_pin = sha(b"independent-other-correspondence")
    refuse("independent-link-pin", expected=wrong_pin, changes={"expected_correspondence_sha256": wrong_pin})
    altered = deepcopy(base["link"])
    required = {digest(row["subject_ref"]) for row in altered["required_subjects"]}
    index = next(i for i, row in enumerate(altered["population_subjects"]) if digest(row["subject_ref"]) not in required)
    removed = altered["population_subjects"].pop(index)
    altered = contracts.seal_record({key: value for key, value in altered.items() if key not in {"record_cid", "cid_scope"}})
    ref = exports.json("negative-omitted-unselected-link.json", altered)
    refuse("omitted-unselected-population", offered=altered, expected=digest(altered),
           changes={"correspondence": ref, "removed_subject_ref": removed["subject_ref"], "expected_correspondence_sha256": digest(altered)})
    arguments = dict(base["arguments"])
    inputs, pins = dict(arguments["candidate_inputs"]), dict(arguments["expected_candidate_pin"])
    pretty = json.dumps(load(inputs["report_raw"]), sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False).encode() + b"\n"
    need(load(pretty) == load(inputs["report_raw"]) and sha(pretty) != sha(inputs["report_raw"]), "pretty report control does not change original transport")
    ref = exports.add("negative-pretty-report-input.json", pretty)
    inputs["report_raw"], pins["report_sha256"] = pretty, sha(pretty)
    arguments.update(candidate_inputs=inputs, expected_candidate_pin=pins)
    refuse("pretty-report-transport", args=arguments, changes={"report_raw": ref, "report_sha256": sha(pretty)})
    for label in ("missing-context", "reordered-context", "swapped-context-packet"):
        arguments = dict(base["arguments"])
        packets = [dict(row) for row in arguments["context_inputs"]]
        population = deepcopy(arguments["expected_context_population"])
        refs = deepcopy(base["packets"])
        if label == "missing-context":
            packets.pop()
            population.pop()
            refs.pop()
        elif label == "reordered-context":
            packets.reverse()
            population.reverse()
            refs.reverse()
        else:
            packets[0]["packet_raw"] = packets[1]["packet_raw"]
            population[0]["packet_sha256"] = sha(packets[0]["packet_raw"])
            refs[0]["packet"] = refs[1]["packet"]
            refs[0]["packet_canonical_sha256"] = refs[1]["packet_canonical_sha256"]
        arguments.update(context_inputs=packets, expected_context_population=population)
        ref = exports.json("negative-" + label + "-context-index.json", {
            "contexts": refs, "expected_context_population": population})
        refuse(label, args=arguments, changes={"context_index": ref})
    arguments = dict(base["arguments"])
    need(len(arguments["required_dependency_ids"]) > 1, "meaningful dependency closure required")
    arguments["required_dependency_ids"] = arguments["required_dependency_ids"][:-1]
    refuse("incomplete-dependency-closure", args=arguments,
           changes={"required_dependency_ids": arguments["required_dependency_ids"]})
    arguments = dict(base["arguments"])
    arguments.update(candidate_inputs=families["tdfol"]["arguments"]["candidate_inputs"],
                     expected_candidate_pin=families["tdfol"]["arguments"]["expected_candidate_pin"])
    refuse("mixed-family-candidate", args=arguments, changes={"candidate_inputs_from_family_index": families["tdfol"]["index"]})
    need(len(controls) == 8 and all(row["refused"] is True for row in controls), "eight refusal outcomes required")
    exports.json("negative-control-results.json", {"schema": "retained-definition-correspondence-refusals/v1",
        "controls": controls, "rejected_payloads_are_primary_results": False})
    recheck_inputs()
    need(producers() == source_pins and Path(__file__).read_bytes() == driver_raw,
         "driver or observed public operation owner changed")
    need(not attempts and not any(prohibited(name) for name in sys.modules), "an external operation was attempted")
    exports.verify()
    passed("all_original_inputs_new_originals_and_public_owner_bytes_retained")
    passed("closed_bounded_primary_artifact_inventory_exact_readback")
    receipt = {
        "schema": SCHEMA, "selected_check": SELECTED_CHECK,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(), "all_checks_passed": True,
        "named_checks": checks, "named_check_count": len(checks), "negative_controls_refused": 8,
        "public_operation_calls": calls, "input_descriptor": descriptor_ref,
        "input_descriptor_sha256": options.expected_input_descriptor_sha256,
        "original_inputs": original_refs, "source_counts": sampling["counts"],
        "families": summaries, "source_generation_comparisons": comparisons,
        "whole_source_subjects": 560, "candidate_statute_paragraphs": 134, "retained_context_controls": 426,
        "blank_question_slots": 8400, "original_open_context_obligations": 3360,
        "actual_response_count": 0, "actual_reviews": 0, "assessments_created": 0,
        "signatures_created": 0, "model_encoder_or_training_calls": 0,
        "network_or_native_compiler_calls": 0, "norms_created": 0, "definition_use_bindings": 0,
        "producer_pins": source_pins, "driver_sha256": sha(driver_raw), "source_repository": str(ROOT),
        "source_cohort_is_complete_dynamic_import_closure": False,
        "new_candidate_and_report_originals_are_historical_original_files": False,
        "original_request_source_sampler_descriptor_transport_preserved": True,
        "historical_and_current_candidate_cids_are_claimed_equal": False,
        "hash_recipes": {"original_files": "SHA256 of independently retained original byte inputs",
            "canonical_records": "SHA256 of compact sorted UTF8 JSON including CIDs and internal digests",
            "manifest_internal": "existing dependency owner manifest_sha256; distinct from full canonical/file SHA"},
        "authority": {key: False for key in families["fol"]["link"]["authority"]},
        "training_mask": 0, "evaluation_gold_mask": 0,
        "aggregate_export_byte_limit": MAX_EXPORT_BYTES,
        "outputs": list(exports.files.values()),
        "closed_export_names": sorted([*exports.files, "replay-receipt.json", "file-index.json"]),
        "file_index_scope": "file-index.json binds all prior files including this receipt; its own hash is externally bound by driver completion/native durability",
    }
    receipt_ref = exports.json("replay-receipt.json", receipt)
    index_ref = exports.json("file-index.json", {"schema": "retained-definition-correspondence-file-index/v1",
        "files": list(exports.files.values()), "self_file": "file-index.json",
        "closed_export_names": sorted([*exports.files, "file-index.json"]),
        "listed_bytes_excluding_self": exports.total, "aggregate_byte_limit": MAX_EXPORT_BYTES})
    exports.verify()
    recheck_inputs()
    need(producers() == source_pins and Path(__file__).read_bytes() == driver_raw
         and not attempts, "final input/source/external-operation closing check failed")
    print(json.dumps({"schema": SCHEMA, "selected_check": SELECTED_CHECK, "all_checks_passed": True,
        "receipt": receipt_ref, "file_index": index_ref, "export_files": len(exports.files),
        "export_bytes": exports.total, "named_check_count": len(checks), "negative_controls_refused": 8,
        "families": ["fol", "tdfol"], "actual_reviews": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
