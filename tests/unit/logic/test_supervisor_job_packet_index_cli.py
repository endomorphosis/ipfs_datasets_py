"""Cold normal-package CLI integration over authored, file-bound metadata.

Only input factories are reused from the pure metadata tests. Each operation
starts the real CLI in a fresh interpreter; no production module is mocked or
AST-loaded in that process. These fixtures grant no native task acceptance.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "scripts/ops/legal_ir/run_autoformal_supervisor.py"
OWNER = ROOT / "ipfs_datasets_py/logic/autoformal/supervisor_loop.py"


def wire(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()


def pin(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


class JobPacketIndexCLITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="packet-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.primary = self.directory / "primary"
        self.primary.mkdir()
        self.output = self.primary / "workspace/out/index.json"
        self.output.parent.mkdir(parents=True)
        self.freeze = self.output.with_suffix(".freeze.json")
        self.verification = self.output.with_suffix(".verification.json")
        self.inputs_path = self.directory / "inputs.json"
        factory_path = ROOT / "tests/unit/logic/test_supervisor_job_packet_index.py"
        spec = importlib.util.spec_from_file_location("packet_cli_authored_input_factory", factory_path)
        fixture_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture_module)
        factory = fixture_module.JobPacketIndexTests()
        request = factory.fixture()
        tasks = request["current_snapshot"]["tasks"]
        parent_ids = [f"LIR-{i:02d}" for i in range(1, 25) if i not in (3, 16)]
        for i, task in enumerate(tasks):
            task["body"]["legacy_parent_task"] = parent_ids[(i-4) % 22] if 4 <= i <= 52 else None
        for i, parent in zip((53, 54, 55), ("LIR-03", "LIR-03", "LIR-16")):
            tasks[i]["body"]["legacy_parent_task"] = parent
        for task in tasks[4:11]:
            task["body"]["requires_product_change_scope"] = True
        tasks[2]["revision"] = 3
        logical = [str(p.relative_to(self.primary)) for p in (self.output, self.freeze, self.verification)]
        tasks[2]["outputs"] = [{"path": value} for value in logical]
        cap = self.put(self.primary / "workspace/capability.json", request["capability_report"])
        checked = self.put(self.primary / "workspace/capability-verification.json", request["capability_verification"])
        tasks[1]["body"]["completion_receipt"]["independent_verification"] = checked
        snapshot = self.put(self.primary / "workspace/current-snapshot.json", request["current_snapshot"])
        groups = [
            ("LIRAE-LIR03-IR-PACKET-01", ["LIR-04", "LIR-05", "LIR-06", "LIR-07", "LIR-08", "LIR-09", "LIR-10", "LIR-11"], 3, 3),
            ("LIRAE-LIR03-LEAN-PACKET-02", ["LIR-12", "LIR-13", "LIR-14", "LIR-15", "LIR-21", "LIR-22"], 4, 3),
            ("LIRAE-LIR03-MODEL-PACKET-01", ["LIR-01", "LIR-17", "LIR-18", "LIR-19", "LIR-20", "LIR-23"], 4, 3),
            ("LIRAE-LIR03-SOURCE-PACKET-01", ["LIR-02", "LIR-05", "LIR-24"], 2, 2),
        ]
        rows = []
        for group, parents, nsource, nevidence in groups:
            dependencies = {"owner_sources": [], "evidence": []}
            resolved, logical_sources = [], []
            for role, count in (("owner_sources", nsource), ("evidence", nevidence)):
                for i in range(count):
                    if role == "owner_sources":
                        logical_source = "ipfs_datasets_py/logic/autoformal/" + group.lower() + str(i) + ".py"
                        logical_sources.append(logical_source)
                        relative = "workspace/capture/owner-sources/" + logical_source
                        raw = b'raise AssertionError("retained source must never execute")\n'
                        self.put_raw(self.primary / logical_source, raw)
                        descriptor = self.put_raw(self.primary / relative, raw)
                    else:
                        relative = "workspace/capture/evidence/" + group.lower() + str(i) + ".json"
                        descriptor = self.put(self.primary / relative, {"authored_evidence": i})
                    declared = {**descriptor, "path": relative}
                    dependencies[role].append(declared)
                    resolved.append({"role": role, "declared": declared, "resolved_primary_R": descriptor})
            packet = {"schema": "legal-ir-programme-preparation/v1", "task_id": group,
                "metadata_complete": True, "snapshot_binding_only": True,
                **{key: False for key in ("admitted", "formalized", "dispatch_authorized", "mutation_authorized",
                    "model_executed", "training_executed", "scientific_parent_satisfied")},
                "admission_scope": {"native_binding": {"control_revision": None, "task_cid": None,
                    "status": "original_admission_required"}, "supporting_parents": [{"task_id": parent} for parent in parents],
                    "dependencies": dependencies, "logical_owner_paths": logical_sources}}
            packet_relative = "packets/" + group + "/packet.json"
            packet_pin = self.put(self.primary / packet_relative, packet)
            receipt_pin = self.put(self.primary / "packets" / group / "receipt.json", {
                "schema": "legal-ir-supervisor-task-receipt/v1", "task_id": group,
                "status": "implemented", "task_kind": "programme_preparation", "authority": {"admitted": False, "formalized": False},
                "artifacts": [{"kind": "packet", "path": packet_relative, "sha256": packet_pin["sha256"]}]})
            rows.append({"task_id": group, "packet": packet_pin, "receipt": receipt_pin,
                "supporting_parent_contexts": parents, "resolved_snapshot_dependencies": resolved,
                "historical_W_sources_differ": True})
        self.audit_path = self.primary / "workspace/reuse-audit.json"
        audit_pin = self.put(self.audit_path, {"schema": "legal-ir-LIR9003-completed-engineering-reuse/v1",
            "native_or_model_execution": False, "packets": rows})
        source_pins = [pin(CLI), pin(OWNER)]
        packet = factory.proposal(request)
        packet.update(task_alias=tasks[2]["task_alias"], task_cid=tasks[2]["task_cid"], revision=3,
            dependencies=[{"task_cid": tasks[1]["task_cid"], "revision": 4, "status": "completed"}],
            purpose="control_metadata_analysis", outputs=logical, exclusive_keys=tasks[2]["body"]["exclusive_keys"],
            source_descriptors=source_pins, entrypoint_source=source_pins[0], validation_source=source_pins[0],
            inputs=[{"role": "prior_evidence", "use": "verification", "descriptor": value}
                    for value in (snapshot, cap, checked, audit_pin)])
        packet["worker"]["principal"] = request["producer_principal"]
        packet["verifier"].update(principal="packet-reviewer", source_descriptor=source_pins[0])
        prefix = [sys.executable, "-B", str(CLI), "job-packet-index"]
        packet["argv"] = prefix + ["prepare", "--inputs", str(self.inputs_path), "--output", str(self.output), "--freeze-out", str(self.freeze)]
        packet["verifier"]["argv"] = prefix + ["verify", "--inputs", str(self.inputs_path), "--report", str(self.output),
            "--freeze", str(self.freeze), "--verifier-principal", "packet-reviewer", "--output", str(self.verification)]
        packet["validation_argv"] = copy.deepcopy(packet["verifier"]["argv"])
        source_context, evidence_context = {}, {}
        for retained in rows:
            for item in retained["resolved_snapshot_dependencies"]:
                ref = item["resolved_primary_R"]
                if item["role"] == "owner_sources":
                    logical_path = item["declared"]["path"].split("/owner-sources/", 1)[1]
                    source_context[logical_path] = {"logical_path": logical_path,
                        "current_primary": pin(self.primary / logical_path), "retained_snapshot": ref}
                else:
                    evidence_context[ref["path"]] = ref
        packet["review_context"] = {"schema": "legal-ir-job-packet-index-review-context/v1",
            "retained_preparations": sorted([{key: row[key] for key in
                ("task_id", "packet", "receipt", "supporting_parent_contexts")} for row in rows],
                key=lambda row: row["task_id"]),
            "current_primary_source_closure": [source_context[key] for key in sorted(source_context)],
            "retained_evidence_snapshots": [evidence_context[key] for key in sorted(evidence_context)],
            "supporting_parent_contexts": sorted(parent_ids),
            "current_native_child_bindings": sorted([{"task_alias": task["task_alias"],
                "task_cid": task["task_cid"], "revision": task["revision"],
                "preparations": [row["task_id"] for row in rows
                    if task["body"]["legacy_parent_task"] in row["supporting_parent_contexts"]]}
                for task in tasks[4:53]], key=lambda row: row["task_alias"]),
            "implementation_scope_gaps": sorted([{"task_alias": task["task_alias"],
                "task_cid": task["task_cid"], "revision": task["revision"],
                "current_code_edit_allowlist": [], "reviewed_implementation_packet_present": False,
                "unbound_requirements": ["exact_code_change_paths", "owning_test_paths", "shared_file_lease_keys",
                    "independent_implementation_acceptance"]} for task in tasks[4:11]],
                key=lambda row: row["task_alias"]),
            "historical_W_comparisons_are_context_only": True, "native_binding_authority": False}
        self.spec = {"schema": "legal-ir-job-packet-index-cli-inputs/v1", "canonical_owner": pin(OWNER),
            "inputs": {"current_snapshot": snapshot, "capability_report": cap, "capability_verification": checked},
            "reuse_audit": audit_pin, "primary_snapshot_root": str(self.primary), "packet_proposals": [packet],
            "producer_principal": request["producer_principal"], "expected_task_revision": 3}
        self.put(self.inputs_path, self.spec)

    def put_raw(self, path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return pin(path)

    def put(self, path, value):
        return self.put_raw(path, wire(value))

    def run_cli(self, operation="prepare", **changes):
        args = ["--inputs", str(self.inputs_path)]
        if operation == "prepare":
            args += ["--output", str(changes.get("output", self.output)), "--freeze-out", str(self.freeze)]
        else:
            args += ["--report", str(self.output), "--freeze", str(self.freeze),
                "--verifier-principal", changes.get("principal", "packet-reviewer"), "--output", str(self.verification)]
        env = dict(os.environ, IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", IPFS_DATASETS_AUTO_INSTALL="0",
            IPFS_AUTO_INSTALL="false", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTHONPATH="")
        return subprocess.run([sys.executable, "-B", str(CLI), "job-packet-index", operation, *args],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)

    def test_cold_normal_import_prepares_freezes_and_independently_verifies(self):
        prepared = self.run_cli()
        self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        observation = json.loads(prepared.stdout)
        self.assertEqual(observation["owner_path"], str(OWNER))
        self.assertEqual(observation["reuse"]["current_primary_sources_matching"], 13)
        self.assertEqual(observation["reuse"]["current_native_children_bound"], 49)
        report = json.loads(self.output.read_bytes())
        self.assertEqual(report["counts"]["metadata_bound_pending_review"], 1)
        self.assertEqual(observation["reuse"]["implementation_scope_gaps"], 7)
        frozen_self = next(row["packet_proposal"] for row in report["entries"] if row["task_alias"] == "LIR-9003")
        self.assertEqual(frozen_self["review_context"], self.spec["packet_proposals"][0]["review_context"])
        self.assertFalse(report["task_acceptance_satisfied"])
        verified = self.run_cli("verify")
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        result = json.loads(self.verification.read_bytes())
        self.assertTrue(result["valid"]); self.assertFalse(result["native_admission"])

    def test_retained_metadata_or_current_primary_source_changes_refuse_before_output(self):
        source = self.primary / "ipfs_datasets_py/logic/autoformal/lirae-lir03-ir-packet-010.py"
        original = source.read_bytes()
        source.write_bytes(b"changed current source\n")
        refused = self.run_cli()
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn("metadata descriptor", refused.stdout)
        self.assertFalse(self.output.exists())
        source.write_bytes(original)
        audit = json.loads(self.audit_path.read_bytes())
        Path(audit["packets"][0]["packet"]["path"]).write_bytes(b"changed retained packet\n")
        refused = self.run_cli()
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertFalse(self.output.exists())

    def test_missing_concrete_self_packet_remains_a_pure_preview(self):
        self.spec["packet_proposals"] = []
        self.put(self.inputs_path, self.spec)
        refused = self.run_cli()
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn("concrete9003", refused.stdout)
        self.assertFalse(self.output.exists())

    def test_input_file_cannot_hash_itself_or_claim_unbound_actual_arguments(self):
        original = copy.deepcopy(self.spec)
        self.spec["packet_proposals"][0]["review_context"]["current_native_child_bindings"][0]["revision"] += 1
        self.put(self.inputs_path, self.spec)
        refused = self.run_cli()
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn("review_context", refused.stdout)
        self.assertFalse(self.output.exists())
        self.spec = copy.deepcopy(original)
        self.spec["packet_proposals"][0]["argv"][-1] = str(self.directory / "another-freeze.json")
        self.put(self.inputs_path, self.spec)
        refused = self.run_cli()
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn("actual producer/verifier command", refused.stdout)
        self.assertFalse(self.output.exists())
        self.spec = original
        self.spec["packet_proposals"][0]["inputs"].append({"role": "prior_evidence", "use": "verification",
            "descriptor": {"path": str(self.inputs_path), "bytes": 1, "sha256": "0"*64}})
        self.put(self.inputs_path, self.spec)
        refused = self.run_cli()
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn("self input-file hash", refused.stdout)
        self.assertFalse(self.output.exists())

    def test_preexisting_output_and_symlink_inputs_preserve_originals(self):
        self.output.write_bytes(b"original output")
        refused = self.run_cli()
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertEqual(self.output.read_bytes(), b"original output")
        self.inputs_path.unlink()
        self.inputs_path.symlink_to(self.audit_path)
        refused = self.run_cli(output=self.directory / "unused.json")
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertTrue(self.inputs_path.is_symlink())

    def test_noncanonical_report_and_same_verifier_cannot_create_acceptance(self):
        prepared = self.run_cli(); self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        original = self.output.read_bytes()
        self.output.write_bytes(json.dumps(json.loads(original), indent=2).encode())
        refused = self.run_cli("verify")
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertFalse(self.verification.exists())
        self.output.write_bytes(original)
        refused = self.run_cli("verify", principal=self.spec["producer_principal"])
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertFalse(self.verification.exists())

    def test_duplicate_or_nonfinite_input_metadata_is_rejected(self):
        for raw in (b'{"schema":"one","schema":"two"}', b'{"value":NaN}'):
            with self.subTest(raw=raw):
                self.inputs_path.write_bytes(raw)
                refused = self.run_cli()
                self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
                self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
