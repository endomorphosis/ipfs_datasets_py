"""Standalone static release-reference checks using authored temporary files.

These fixtures are not model checkpoints, captures, embeddings or qualifications.
The script is loaded directly so importing the IPFS package is unnecessary.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/ops/autoencoder/audit_ir_release_bundle.py"
SCHEMA = "ir-release-bundle-preflight-manifest/v1"
AUTHORITY_FIELDS = (
    "runtime_readiness_qualified",
    "model_task_qualification",
    "proof_authority",
    "effects_authorized",
)


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ReleaseBundleAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("standalone_ir_release_bundle_audit", SCRIPT)
        if spec is None or spec.loader is None:
            raise RuntimeError("standalone audit script cannot be loaded")
        cls.audit = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.audit
        spec.loader.exec_module(cls.audit)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ir-release-reference-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source_root = self.base / "original"
        self.source_root.mkdir()
        self.asset = self._file("asset", "assets/checkpoint.json", _json_bytes({"authored_fixture": 1}))
        self.inventory = self._file(
            "inventory",
            "inventories/codebase_ir/8d.json",
            _json_bytes({
                "schema": "ir-family-dimension-inventory-plan/v1",
                "status": "declarative_plan_not_runtime_inventory",
                "cell_id": "codebase_ir_8d",
                "ir_family_id": "codebase_ir",
                "dimension": 8,
                "existing_checkpoint_evidence": [{
                    "role": "authored byte-reference fixture",
                    "receipt": self._original_receipt(self.asset),
                    "dimension_role": "internal_latent",
                    "input_width": 53,
                    "latent_width": 8,
                    "formal_decoder": False,
                }],
            }),
        )
        self.manifest = {
            "schema": SCHEMA,
            "roots": {"fixture": str(self.source_root)},
            "files": [self.inventory, self.asset],
            "cells": [{
                "cell_id": "codebase_ir_8d",
                "ir_family_id": "codebase_ir",
                "dimension": 8,
                "inventory_file_id": "inventory",
            }],
            "asset_links": [{
                "cell_id": "codebase_ir_8d",
                "inventory_pointer": "/existing_checkpoint_evidence/0/receipt",
                "asset_file_id": "asset",
            }],
            "inventory_index_file_id": None,
            "closure_complete": False,
        }

    def _file(self, file_id, relative_path, raw):
        path = self.source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {
            "file_id": file_id,
            "root_id": "fixture",
            "relative_path": relative_path,
            "bytes": len(raw),
            "sha256": _sha(raw),
            "roles": ["cell_inventory" if file_id == "inventory" else "inherited_asset"],
            "capabilities": ["model_reuse"],
            "source_path": str(path),
        }

    @staticmethod
    def _original_receipt(item):
        return {"path": item["source_path"], "bytes": item["bytes"], "sha256": item["sha256"]}

    def _manifest_file(self, manifest=None, *, raw=None):
        if raw is None:
            raw = _json_bytes(self.manifest if manifest is None else manifest)
        path = self.base / "bundle.json"
        path.write_bytes(raw)
        return path, _sha(raw)

    def _full_index_manifest(self, *, wrong_index_path=False):
        manifest = deepcopy(self.manifest)
        index_cells = []
        for family in ("codebase_ir", "security_ir", "legal_ir", "intent_ir"):
            for dimension in (8, 384, 768):
                cell_id = f"{family}_{dimension}d"
                relative = f"inventories/{family}/{dimension}d.json"
                if cell_id != "codebase_ir_8d":
                    file_id = "inventory_" + cell_id
                    item = self._file(file_id, relative, _json_bytes({
                        "schema": "ir-family-dimension-inventory-plan/v1",
                        "cell_id": cell_id,
                        "ir_family_id": family,
                        "dimension": dimension,
                    }))
                    item["roles"] = ["cell_inventory"]
                    manifest["files"].append(item)
                    manifest["cells"].append({
                        "cell_id": cell_id,
                        "ir_family_id": family,
                        "dimension": dimension,
                        "inventory_file_id": file_id,
                    })
                index_cells.append({
                    "cell_id": cell_id,
                    "ir_family_id": family,
                    "dimension": dimension,
                    "inventory_manifest": relative,
                })
        if wrong_index_path:
            index_cells[-1]["inventory_manifest"] = "inventories/legal_ir/768d.json"
        index = self._file("index", "inventory-index.json", _json_bytes({
            "schema": "ir-family-dimension-inventory-directory-plan/v1",
            "cells": index_cells,
        }))
        index["roles"] = ["inventory_index"]
        manifest["files"].append(index)
        manifest["inventory_index_file_id"] = "index"
        return manifest

    def _run(self, manifest=None, *, root_overrides=None):
        path, expected = self._manifest_file(manifest)
        return self.audit.audit_file(path, expected, root_overrides=root_overrides)

    def _assert_no_authority(self, report):
        for key in AUTHORITY_FIELDS:
            with self.subTest(authority_field=key):
                self.assertIn(key, report)
                self.assertIs(report[key], False)

    def _assert_success(self, report):
        self.assertEqual(report["status"], "declared_receipts_match")
        self.assertTrue(report["items"])
        self.assertTrue(all(item["status"] == "matched" for item in report["items"]))
        self.assertTrue(all(cell["status"] == "inventory_matched" for cell in report["cells"]))
        self._assert_no_authority(report)

    def _assert_cell_rejected(self, report):
        self.assertEqual(report["status"], "receipt_failures")
        self.assertEqual(report["cells"][0]["status"], "inventory_rejected")
        self._assert_no_authority(report)

    def _assert_association_rejected(self, report):
        self.assertEqual(report["status"], "receipt_failures")
        self.assertEqual(report["cells"][0]["status"], "inventory_matched")
        self.assertEqual(report["asset_links"][0]["status"], "association_rejected")
        self._assert_no_authority(report)

    def test_authentic_subset_references_pass_without_runtime_authority(self):
        report = self._run()
        self._assert_success(report)
        self.assertEqual({item["file_id"] for item in report["items"]}, {"inventory", "asset"})
        self.assertEqual([cell["cell_id"] for cell in report["cells"]], ["codebase_ir_8d"])

    def test_complete_twelve_cell_index_preserves_separate_inventory_bindings(self):
        report = self._run(self._full_index_manifest())
        self._assert_success(report)
        self.assertEqual(len(report["cells"]), 12)
        self.assertEqual(report["inventory_index_status"], "inventory_index_matched")

    def test_authentic_index_cannot_route_a_cell_to_another_inventory(self):
        report = self._run(self._full_index_manifest(wrong_index_path=True))
        self.assertTrue(all(item["status"] == "matched" for item in report["items"]))
        self.assertTrue(all(cell["status"] == "inventory_matched" for cell in report["cells"]))
        self.assertEqual(report["inventory_index_status"], "inventory_index_rejected")
        self.assertEqual(report["status"], "receipt_failures")
        self._assert_no_authority(report)

    def test_top_manifest_tamper_does_not_accept_old_trusted_sha(self):
        path, expected = self._manifest_file()
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(self.audit.AuditError):
            self.audit.audit_file(path, expected)

    def test_expected_manifest_sha_is_required_and_strict(self):
        path, _ = self._manifest_file()
        for expected in (None, "", "f" * 63, "G" * 64, True):
            with self.subTest(expected=expected), self.assertRaises(self.audit.AuditError):
                self.audit.audit_file(path, expected)

    def test_source_byte_drift_is_reported_even_when_manifest_is_authentic(self):
        Path(self.asset["source_path"]).write_bytes(b"changed asset bytes")
        report = self._run()
        self.assertEqual(report["status"], "receipt_failures")
        item = next(item for item in report["items"] if item["file_id"] == "asset")
        self.assertEqual(item["status"], "pin_mismatch")
        self._assert_no_authority(report)

    def test_missing_item_is_explicit_unavailable(self):
        Path(self.asset["source_path"]).unlink()
        report = self._run()
        self.assertEqual(report["status"], "receipt_failures")
        item = next(item for item in report["items"] if item["file_id"] == "asset")
        self.assertEqual(item["status"], "unavailable")
        self._assert_no_authority(report)

    def test_parent_traversal_is_invalid_before_reading(self):
        manifest = deepcopy(self.manifest)
        manifest["files"][1]["relative_path"] = "../outside.json"
        with self.assertRaises(self.audit.AuditError):
            self._run(manifest)

    def test_absolute_locator_is_invalid(self):
        manifest = deepcopy(self.manifest)
        manifest["files"][1]["relative_path"] = self.asset["source_path"]
        with self.assertRaises(self.audit.AuditError):
            self._run(manifest)

    def test_source_provenance_path_must_be_absolute(self):
        manifest = deepcopy(self.manifest)
        manifest["files"][1]["source_path"] = "assets/checkpoint.json"
        with self.assertRaises(self.audit.AuditError):
            self._run(manifest)

    def test_symlink_file_is_read_rejected(self):
        manifest = deepcopy(self.manifest)
        link = self.source_root / "assets/linked.json"
        link.symlink_to(Path(self.asset["source_path"]))
        manifest["files"][1]["relative_path"] = "assets/linked.json"
        report = self._run(manifest)
        item = next(item for item in report["items"] if item["file_id"] == "asset")
        self.assertEqual(item["status"], "read_rejected")
        self.assertEqual(report["status"], "receipt_failures")

    def test_symlink_directory_is_read_rejected(self):
        manifest = deepcopy(self.manifest)
        (self.source_root / "linked-assets").symlink_to(self.source_root / "assets", target_is_directory=True)
        manifest["files"][1]["relative_path"] = "linked-assets/checkpoint.json"
        report = self._run(manifest)
        item = next(item for item in report["items"] if item["file_id"] == "asset")
        self.assertEqual(item["status"], "read_rejected")
        self.assertEqual(report["status"], "receipt_failures")

    def _assert_directory_swap_does_not_read_outside(self, *, after_parent_open):
        if not self.audit.DIR_FD_READS_SUPPORTED:
            self.skipTest("directory descriptor reads require POSIX no-follow support")
        path, expected = self._manifest_file()
        assets_directory = self.source_root / "assets"
        retained_directory = self.source_root / "assets-retained"
        outside_directory = self.base / "outside"
        outside_directory.mkdir()
        outside_path = outside_directory / "checkpoint.json"
        outside_payload = _json_bytes({"authored_fixture": 2})
        self.assertEqual(len(outside_payload), self.asset["bytes"])
        self.assertNotEqual(_sha(outside_payload), self.asset["sha256"])
        outside_path.write_bytes(outside_payload)
        outside_stat = outside_path.stat()
        outside_identity = (outside_stat.st_dev, outside_stat.st_ino)
        actual_open, actual_fdopen = os.open, os.fdopen
        triggered = []
        reads = []

        def swap_parent():
            assets_directory.rename(retained_directory)
            assets_directory.symlink_to(outside_directory, target_is_directory=True)

        def opening_under_race(name, flags, mode=0o777, *, dir_fd=None):
            if name == "assets" and dir_fd is not None:
                self.assertFalse(triggered, "authored race should trigger only once")
                self.assertTrue(flags & os.O_DIRECTORY)
                self.assertTrue(flags & os.O_NOFOLLOW)
                triggered.append(True)
                if after_parent_open:
                    anchored_fd = actual_open(name, flags, mode, dir_fd=dir_fd)
                    swap_parent()
                    return anchored_fd
                swap_parent()
            return actual_open(name, flags, mode, dir_fd=dir_fd)

        class TrackedStream:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                self.stream.__enter__()
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def fileno(self):
                return self.stream.fileno()

            def read(self, limit=-1):
                opened = os.fstat(self.stream.fileno())
                data = self.stream.read(limit)
                reads.append(((opened.st_dev, opened.st_ino), data))
                return data

        def tracking_fdopen(*args, **kwargs):
            return TrackedStream(actual_fdopen(*args, **kwargs))

        with patch.object(self.audit.os, "open", side_effect=opening_under_race), \
                patch.object(self.audit.os, "fdopen", side_effect=tracking_fdopen):
            report = self.audit.audit_file(path, expected)
        self.assertEqual(triggered, [True], "the race must reach the declared parent open")
        self.assertTrue(assets_directory.is_symlink())
        self.assertFalse(any(identity == outside_identity for identity, _ in reads))
        self.assertNotIn(outside_payload, [data for _, data in reads])
        self._assert_no_authority(report)
        if after_parent_open:
            self._assert_success(report)
            self.assertIn(Path(retained_directory / "checkpoint.json").read_bytes(),
                          [data for _, data in reads])
        else:
            item = next(item for item in report["items"] if item["file_id"] == "asset")
            self.assertEqual(item["status"], "read_rejected")
            self.assertEqual(item["bytes_read"], 0)
            self.assertEqual(report["status"], "receipt_failures")

    def test_parent_swapped_to_symlink_before_open_rejects_without_outside_read(self):
        self._assert_directory_swap_does_not_read_outside(after_parent_open=False)

    def test_parent_swapped_to_symlink_after_open_reads_only_anchored_original(self):
        self._assert_directory_swap_does_not_read_outside(after_parent_open=True)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO admission check requires POSIX")
    def test_fifo_is_rejected_without_blocking(self):
        manifest = deepcopy(self.manifest)
        os.mkfifo(self.source_root / "assets/pipe.json")
        manifest["files"][1]["relative_path"] = "assets/pipe.json"
        path, expected = self._manifest_file(manifest)
        program = (
            "import importlib.util,json,pathlib,sys; "
            "s=importlib.util.spec_from_file_location('isolated_bundle_audit',sys.argv[1]); "
            "m=importlib.util.module_from_spec(s); sys.modules[s.name]=m; s.loader.exec_module(m); "
            "r=m.audit_file(pathlib.Path(sys.argv[2]),sys.argv[3]); "
            "print(json.dumps({'status':r['status'],'items':r['items']}))"
        )
        completed = subprocess.run(
            [sys.executable, "-I", "-B", "-c", program, str(SCRIPT), str(path), expected],
            capture_output=True, text=True, timeout=5, check=True,
        )
        report = json.loads(completed.stdout)
        item = next(item for item in report["items"] if item["file_id"] == "asset")
        self.assertEqual(item["status"], "read_rejected")
        self.assertEqual(report["status"], "receipt_failures")

    def test_root_relocation_checks_copy_and_preserves_original_provenance(self):
        relocated = self.base / "relocated"
        shutil.copytree(self.source_root, relocated)
        shutil.rmtree(self.source_root)
        report = self._run(root_overrides={"fixture": str(relocated)})
        self._assert_success(report)

    def test_authentic_inventory_cannot_be_relabelled_to_another_cell(self):
        manifest = deepcopy(self.manifest)
        manifest["cells"][0].update(cell_id="security_ir_8d", ir_family_id="security_ir")
        manifest["asset_links"][0]["cell_id"] = "security_ir_8d"
        report = self._run(manifest)
        self.assertTrue(all(item["status"] == "matched" for item in report["items"]))
        self._assert_cell_rejected(report)

    def test_matching_width_does_not_override_inventory_cell_identity(self):
        manifest = deepcopy(self.manifest)
        manifest["cells"][0].update(cell_id="legal_ir_8d", ir_family_id="legal_ir")
        manifest["asset_links"][0]["cell_id"] = "legal_ir_8d"
        report = self._run(manifest)
        self._assert_cell_rejected(report)

    def test_authentic_other_asset_does_not_satisfy_inventory_receipt_pointer(self):
        other = self._file("other_asset", "assets/other.json", _json_bytes({"authored_fixture": 2}))
        manifest = deepcopy(self.manifest)
        manifest["files"].append(other)
        manifest["asset_links"][0]["asset_file_id"] = "other_asset"
        report = self._run(manifest)
        self.assertTrue(all(item["status"] == "matched" for item in report["items"]))
        self._assert_association_rejected(report)

    def test_missing_inventory_json_pointer_rejects_association(self):
        manifest = deepcopy(self.manifest)
        manifest["asset_links"][0]["inventory_pointer"] = "/existing_checkpoint_evidence/9/receipt"
        self._assert_association_rejected(self._run(manifest))

    def test_declared_inventory_asset_cannot_be_omitted_from_associations(self):
        manifest = deepcopy(self.manifest)
        manifest["asset_links"] = []
        report = self._run(manifest)
        self.assertTrue(all(item["status"] == "matched" for item in report["items"]))
        self.assertEqual(report["status"], "receipt_failures")
        self._assert_no_authority(report)

    def test_pointer_must_resolve_to_closed_receipt_not_checkpoint_metadata(self):
        manifest = deepcopy(self.manifest)
        manifest["asset_links"][0]["inventory_pointer"] = "/existing_checkpoint_evidence/0"
        self._assert_association_rejected(self._run(manifest))

    def test_cell_dimension_rejects_booleans_and_786(self):
        for dimension in (True, False, 786):
            manifest = deepcopy(self.manifest)
            manifest["cells"][0]["dimension"] = dimension
            with self.subTest(dimension=dimension), self.assertRaises(self.audit.AuditError):
                self._run(manifest)

    def test_unknown_top_field_and_authority_escalation_are_invalid(self):
        for key, value in (("unknown_field", 1), ("proof_authority", True), ("model_task_qualification", True)):
            manifest = deepcopy(self.manifest)
            manifest[key] = value
            with self.subTest(key=key), self.assertRaises(self.audit.AuditError):
                self._run(manifest)

    def test_unknown_nested_file_field_is_invalid(self):
        manifest = deepcopy(self.manifest)
        manifest["files"][0]["qualified"] = True
        with self.assertRaises(self.audit.AuditError):
            self._run(manifest)

    def test_duplicate_json_object_fields_are_invalid(self):
        raw = _json_bytes(self.manifest)
        duplicate = b'{"schema":' + _json_bytes(SCHEMA) + b"," + raw[1:]
        path, expected = self._manifest_file(raw=duplicate)
        with self.assertRaises(self.audit.AuditError):
            self.audit.audit_file(path, expected)

    def test_duplicate_nested_json_fields_are_invalid(self):
        raw = _json_bytes(self.manifest)
        duplicate = raw.replace(b'"file_id":"asset"', b'"file_id":"asset","file_id":"asset"', 1)
        self.assertNotEqual(raw, duplicate)
        path, expected = self._manifest_file(raw=duplicate)
        with self.assertRaises(self.audit.AuditError):
            self.audit.audit_file(path, expected)

    def test_overflowing_json_float_in_authentic_inventory_is_read_rejected(self):
        original_raw = Path(self.inventory["source_path"]).read_bytes()
        for literal in (b"1e999", b"-1e999"):
            with self.subTest(literal=literal):
                raw = original_raw[:-1] + b',"diagnostic_loss":' + literal + b"}"
                manifest = deepcopy(self.manifest)
                manifest["files"][0] = self._file("inventory", self.inventory["relative_path"], raw)
                report = self._run(manifest)
                item = next(item for item in report["items"] if item["file_id"] == "inventory")
                self.assertEqual(item["bytes_read"], len(raw))
                self.assertEqual(item["content_sha256"], _sha(raw))
                self.assertEqual(item["status"], "read_rejected")
                self.assertEqual(report["status"], "receipt_failures")
                self._assert_no_authority(report)

    def test_finite_json_float_in_inventory_metadata_remains_allowed(self):
        original_raw = Path(self.inventory["source_path"]).read_bytes()
        raw = original_raw[:-1] + b',"diagnostic_loss":1.25e-3}'
        manifest = deepcopy(self.manifest)
        manifest["files"][0] = self._file("inventory", self.inventory["relative_path"], raw)
        self._assert_success(self._run(manifest))

    def test_duplicate_file_ids_are_invalid(self):
        manifest = deepcopy(self.manifest)
        distinct = self._file("asset", "assets/id-collision.json", b"different authored bytes")
        manifest["files"].append(distinct)
        with self.assertRaises(self.audit.AuditError):
            self._run(manifest)

    def test_duplicate_locators_under_distinct_file_ids_are_invalid(self):
        manifest = deepcopy(self.manifest)
        alias = deepcopy(manifest["files"][1])
        alias["file_id"] = "asset_alias"
        alias["source_path"] = str(self.base / "distinct-original-provenance.json")
        manifest["files"].append(alias)
        with self.assertRaises(self.audit.AuditError):
            self._run(manifest)

    def test_duplicate_cells_are_invalid(self):
        manifest = deepcopy(self.manifest)
        manifest["cells"].append(deepcopy(manifest["cells"][0]))
        with self.assertRaises(self.audit.AuditError):
            self._run(manifest)

    def test_empty_roles_or_capabilities_are_invalid(self):
        for field in ("roles", "capabilities"):
            manifest = deepcopy(self.manifest)
            manifest["files"][0][field] = []
            with self.subTest(field=field), self.assertRaises(self.audit.AuditError):
                self._run(manifest)

    def test_boolean_file_size_is_invalid(self):
        manifest = deepcopy(self.manifest)
        manifest["files"][1]["bytes"] = True
        with self.assertRaises(self.audit.AuditError):
            self._run(manifest)

    def test_declared_complete_closure_cannot_grant_static_readiness(self):
        manifest = deepcopy(self.manifest)
        manifest["closure_complete"] = True
        with self.assertRaises(self.audit.AuditError):
            self._run(manifest)


if __name__ == "__main__":
    unittest.main()
