"""Small authored controls for the current ordinary CG4 closure assembler.

The temporary selection contains fictional diagnostic receipts, never native
model evidence. Only historical RPI row bytes are copied for the one CID
roundtrip. No producer, tensor library, model or scheduler executes here.
"""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

WORKSPACE = Path(__file__).absolute().parents[6]
SOURCE = WORKSPACE / "artifacts/codebase_ir_terminal_bench/assemble_guard_cost_review_20261004.py"
SOURCE_SHA = "eb64a8dbf134dfef6142abe88c67d6a4342776d5224008fab48efaf0914b90ce"
TABLE = "external/ipfs_accelerate/docs/architecture/repository_proof_index_and_codebase_ir.todo.md"


def load_current():
    before = SOURCE.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= 1024**2:
        raise ValueError("bounded current assembler source required")
    descriptor = os.open(SOURCE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(1024**2 + 1)
        final = os.fstat(stream.fileno())
    after = SOURCE.lstat()
    identities = [(item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns, item.st_ctime_ns, item.st_nlink)
                  for item in (before, opened, final, after)]
    if any(item != identities[0] for item in identities[1:]) or hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError("current assembler source changed")
    specification = importlib.util.spec_from_file_location("_current_authored_guard_cost_assembler", SOURCE)
    module = importlib.util.module_from_spec(specification)
    # Execute only externally pinned CURRENT stdlib source; no retained code.
    exec(compile(raw, str(SOURCE), "exec"), module.__dict__)
    if SOURCE.read_bytes() != raw:
        raise ValueError("current assembler source changed during import")
    return module


class OrdinaryGuardCostAssemblyControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assembler = load_current()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.base = self.root / "artifacts"
        self.base.mkdir()
        self.root_patch = patch.object(self.assembler, "ROOT", self.root)
        self.base_patch = patch.object(self.assembler, "BASE", self.base)
        self.root_patch.start()
        self.base_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.base_patch.stop)
        self.addCleanup(self.temporary.cleanup)

    def write(self, relative, value=None, *, raw=None):
        data = raw if raw is not None else self.assembler.wire(value)
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        path.write_bytes(data)
        path.chmod(0o444)
        return {"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def selection(self, *, allocated=None):
        allocation = {"cpu_slots": 0, "memory_mb": 0} if allocated is None else allocated
        snapshot = {"allocated": allocation, **{name: 0 for name in (
            "active_lease_count", "active_child_lease_count", "active_root_lease_count", "allocated_gpu_memory_mb",
            "allocated_unified_memory_mb", "allocated_child_process_slots", "waiting_request_count")}}
        pins = {"review": self.write("review.json", {"diagnostic_only": True, "performance_qualified": False,
            "selected_existing_profile_changed": False, "current_passing_test_cases": 2}),
            "report": self.write("report.md", raw=b"Authored ordinary diagnostic fixture.\n"),
            "plan": self.write("plan.json", {"fictional_fixture": True, "proof_authority": False}),
            "controls": self.write("controls.json", {"qualified": True, "tests": 2, "errors": 0, "failures": 0, "skipped": 0}),
            "resource_observation": self.write("resources.json", {"resources_after": snapshot})}
        audits = [self.write(f"audit-{index}.json", {"qualified": True, "closed_artifacts_consistent": True,
            "error": None, "fictional_fixture": True, "fixture_id": index, "execution_attestation": False}) for index in range(3)]
        self.write("archive/authored.json", {"fixture_id": "ordinary_cid_data", "proof_authority": False})
        value = {"schema": "guard-cost-review-selection/v1", **pins, "files": [*pins.values(), *audits],
            "directories": {"authored": "archive"}, "audits": audits, "production_table_path": TABLE}
        return value, self.write("selection.json", value)

    def test_strict_json_rejects_duplicate_nonfinite_numbers(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":1e999}', b'{"x":-1e999}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    self.assembler.strict_json(raw)

    def test_written_manifest_must_match_intended_wire_bytes(self):
        real_read = self.assembler.read
        def substitute(relative):
            self.write(relative, raw=b'{"v":2}')
            return real_read(relative)
        with patch.object(self.assembler, "read", substitute):
            with self.assertRaisesRegex(ValueError, "written closure differs"):
                self.assembler.save(self.base, "fixture.json", {"v": 1})

    def test_allocation_zeros_require_plain_ints(self):
        for field in ("cpu_slots", "memory_mb"):
            for alias in (False, 0.0):
                with self.subTest(field=field, alias=alias):
                    _, pin = self.selection(allocated={"cpu_slots": 0, "memory_mb": 0, field: alias})
                    with self.assertRaisesRegex(ValueError, "closed resource observation"):
                        self.assembler.run(self.root / pin["path"], pin["sha256"], "unused-output")

    def test_ordinary_leaf_symlink_hardlink_and_write_refusals(self):
        pin = self.write("ordinary.json", {"v": 1})
        source = self.root / pin["path"]
        alias = self.root / "alias.json"
        alias.symlink_to(source)
        with self.assertRaises((ValueError, OSError)):
            self.assembler.read("alias.json")
        alias.unlink()
        os.link(source, alias)
        with self.assertRaises(ValueError):
            self.assembler.read("ordinary.json")
        alias.unlink()
        source.chmod(0o644)
        with self.assertRaises(ValueError):
            self.assembler.read("ordinary.json")

    def test_parent_directory_replacement_during_read_refused(self):
        self.write("parent/ordinary.json", {"v": 1})
        parent, calls = self.root / "parent", 0
        real_directory_fd = self.assembler.directory_fd
        def replace_on_reopen(path):
            nonlocal calls
            if Path(path) == parent:
                calls += 1
                if calls == 2:
                    parent.rename(self.root / "old-parent")
                    parent.mkdir()
                    self.write("parent/ordinary.json", {"v": 1})
            return real_directory_fd(path)
        with patch.object(self.assembler, "directory_fd", replace_on_reopen):
            with self.assertRaisesRegex(ValueError, "parent changed"):
                self.assembler.read("parent/ordinary.json")

    def test_manifest_saved_bytes_and_local_cid_roundtrip(self):
        _, pin = self.selection()
        # Copy only the exact historical byte facts needed by the assembler's
        # mandatory unchanged production-table check, without executing code.
        rows = b"".join(row for row in (WORKSPACE / TABLE).read_bytes().splitlines(keepends=True)
                        if row.startswith(b"| RPI-"))
        self.assertEqual(len(rows), 19064)
        self.assertEqual(hashlib.sha256(rows).hexdigest(), "47cd2793d08d24d26eec92eff5eb63d323cebfcd24b204640e6920da00983190")
        self.write(TABLE, raw=rows)
        output_pin = self.assembler.run(self.root / pin["path"], pin["sha256"], "authored-assembly")
        closure = self.assembler.strict_json(self.assembler.checked(output_pin))
        self.assertTrue(closure["assembled"])
        self.assertFalse(closure["proof_authority"])
        self.assertFalse(closure["performance_qualified"])
        descriptor = closure["directory_manifests"]["authored"]
        raw = self.assembler.checked(descriptor["manifest"])
        body = self.assembler.strict_json(raw)
        self.assertEqual(body, self.assembler.manifest("archive"))
        self.assertEqual(body["member_count"], 1)
        encoded = descriptor["cidv1_dag_json"]
        self.assertEqual(encoded[0], "b")
        payload = base64.b32decode(encoded[1:].upper() + "=" * (-len(encoded[1:]) % 8))
        self.assertEqual(payload[:5], bytes((1, 0xa9, 2, 0x12, 0x20)))
        self.assertEqual(payload[5:], hashlib.sha256(raw).digest())

    def test_wrong_external_selection_pin_refused(self):
        _, pin = self.selection()
        with self.assertRaisesRegex(ValueError, "external review selection pin"):
            self.assembler.run(self.root / pin["path"], "0" * 64, "unused-output")

    def test_manifest_bounds_apply_before_collecting_all_members(self):
        self.write("bounded/one.json", {"v": 1})
        self.write("bounded/two.json", {"v": 2})
        with patch.object(self.assembler, "MAX_FILES", 1):
            with self.assertRaisesRegex(ValueError, "manifest file budget"):
                self.assembler.manifest("bounded")


if __name__ == "__main__":
    unittest.main()
