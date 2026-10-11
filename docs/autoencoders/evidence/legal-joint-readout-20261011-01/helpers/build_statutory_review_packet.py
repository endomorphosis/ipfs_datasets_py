"""Build blank review inputs only; never infer or manufacture annotations."""
from __future__ import annotations

import hashlib
import importlib.abc
import json
from pathlib import Path
import sys
from types import ModuleType

F = Path(__file__).resolve().parent
PACKAGE = F / "datasets"
PREVIOUS = F.parent / "legal-open-vocabulary-20261011-01"
NATIVE = F.parent / "legal-native-cache-20261011-01"
RUNS = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01")


class DenyModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"torch", "transformers", "sentence_transformers", "numpy"}:
            raise AssertionError("numerical imports prohibited in blank source review")
        return None


def audit(event, values):
    if event in {"socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system"}:
        raise AssertionError("network/process execution prohibited in blank source review")


def pin(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write(name, value):
    path = F / name
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return pin(path)


def main():
    sys.meta_path.insert(0, DenyModels())
    sys.addaudithook(audit)
    for name in ("ipfs_datasets_py", "ipfs_datasets_py.logic", "ipfs_datasets_py.logic.legal_ir"):
        module = ModuleType(name)
        module.__path__ = [str(PACKAGE.joinpath(*name.split(".")))]
        sys.modules[name] = module
    from ipfs_datasets_py.logic.legal_ir.statutory_source_review import (
        create_blank_packet, digest, review_template, validate_blank_packet,
    )

    old_packet_path = PREVIOUS / "real-law-review-packet.json"
    old_packet_pin = pin(old_packet_path)
    old_packet = json.loads(old_packet_path.read_bytes())
    artifact_paths = json.loads((NATIVE / "source-artifact-pins.json").read_bytes())
    provenance_path = NATIVE / "source-view-provenance.json"
    provenance = pin(provenance_path)
    artifact_paths[provenance["sha256"]] = provenance
    native_receipt = pin(RUNS / "arbitrary-native-cache-20261011-02/results/source-production/native384-receipt-001.json")
    previous_run = pin(RUNS / "retained-pointer-cache-20261011-03/results/summary.json")
    opened_refs = []

    def resolver(ref):
        binding = artifact_paths[ref["sha256"]]
        assert binding["bytes"] == ref["bytes"]
        opened_refs.append(ref)
        return Path(binding["path"])

    rows = []
    for original in old_packet["rows"]:
        identity = original["record_id"]
        events = [{"stage": stage, "case_id": identity,
                   "source_text_sha256": original["source_text_sha256"],
                   "evidence_artifact": {key: evidence[key] for key in ("sha256", "bytes")}}
                  for stage, evidence in (("arbitrary-native384-input", native_receipt),
                                          ("frozen-retained-pointer-comparison", previous_run))]
        offsets = original["context"]["selected_span_character_offsets"]
        rows.append({"id": identity, "source_text": original["source_text"], "source": original["source"],
                     "physical_origin": {"provenance_artifact": {key: provenance[key] for key in ("sha256", "bytes")},
                                         "provenance_record_id": identity},
                     "context": {"artifact": original["source"]["artifact"], "selected_char_start": offsets[0],
                                 "selected_char_end": offsets[1], "complete_raw_section": True, "normalization": "identity"},
                     "exposure": {"status": "previously_exposed_development", "prior_exposure_complete": False,
                                  "events": events}})
    packet = create_blank_packet(rows, artifact_resolver=resolver)
    packet_sha = digest(packet)
    validation = validate_blank_packet(packet, expected_packet_sha256=packet_sha, artifact_resolver=resolver)
    template = review_template(packet, expected_packet_sha256=packet_sha, artifact_resolver=resolver)
    assert packet["item_count"] == 8 and packet["selected_source_bytes"] == 2070
    assert packet["complete_context_bytes"] == 148931 and len(packet["context_views"]) == 8
    assert all(value == 0 for value in packet["admission_masks"].values())
    assert pin(old_packet_path) == old_packet_pin
    closed_pins = {str(Path(value["path"])): pin(Path(value["path"])) for value in artifact_paths.values()}
    for value in artifact_paths.values():
        assert closed_pins[value["path"]] == value
    packet_file = write("statutory-source-review-packet.json", packet)
    template_file = write("statutory-source-review-template.json", template)
    write("statutory-source-review-validation.json", validation)
    write("statutory-source-review-packet-build.json", {
        "schema": "statutory-blank-packet-local-build/v1", "passed": True, "findings": [],
        "packet_file_pin": packet_file, "packet_canonical_sha256": packet_sha,
        "packet_body_content_sha256": packet["content_sha256"], "template_file_pin": template_file,
        "builder_pin": pin(Path(__file__).resolve()), "source_owner_pin": pin(PACKAGE / "ipfs_datasets_py/logic/legal_ir/statutory_source_review.py"),
        "input_packet_pin": old_packet_pin, "raw_source_and_provenance_pins": closed_pins,
        "exposure_evidence_content_refs": [{key: value[key] for key in ("sha256", "bytes")} for value in (native_receipt, previous_run)],
        "exposure_evidence_bodies_parsed": False, "exposure_refs_authenticated": False,
        "model_outputs_used_as_annotations": False, "original_parent_export_reopened": False,
        "official_current_law_authenticated": False, "numerical_execution": False,
        "human_labels": 0, "review_submissions": 0, "training_admissions": 0,
        "selected_source_bytes": 2070, "complete_context_bytes": 148931, "physical_items": 8,
        "blank_inputs_only": True, "validation": validation,
    })
    print(json.dumps({"passed": True, "items": 8, "packet_canonical_sha256": packet_sha, "packet_file_sha256": packet_file["sha256"]}))


if __name__ == "__main__":
    main()
