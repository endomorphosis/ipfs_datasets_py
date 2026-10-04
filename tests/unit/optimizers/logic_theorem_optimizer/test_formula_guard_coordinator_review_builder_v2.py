"""Lightweight authored stdlib assembler refusals; no native work executes.

Only the CURRENT, externally pinned stdlib builder is loaded. Temporary files
contain fictional ordinary bytes, never models, production evidence or retained
Python. These controls do not build or walk any real benchmark archive.
"""
from copy import deepcopy
import base64
import hashlib
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

_WORKSPACE = Path(__file__).absolute().parents[4].parent.parent
_BUILDER = _WORKSPACE / "artifacts/codebase_ir_terminal_bench/formula-guard-coordinator-review-builder-v2-20261004-01.py"
_EXPECTED_BUILDER_SHA = "30aab60873e2a00e73b5fbff7b4dfd01ef15aea31e56a042c78892e4496fb942"
_descriptor = os.open(_BUILDER, os.O_RDONLY | os.O_NOFOLLOW)
try:
    _before = os.fstat(_descriptor)
    _raw = os.read(_descriptor, 8 * 1024**2 + 1)
    _after = os.fstat(_descriptor)
finally:
    os.close(_descriptor)
if ((_before.st_dev, _before.st_ino, _before.st_size, _before.st_mtime_ns, _before.st_ctime_ns)
        != (_after.st_dev, _after.st_ino, _after.st_size, _after.st_mtime_ns, _after.st_ctime_ns)
        or len(_raw) != _before.st_size or hashlib.sha256(_raw).hexdigest() != _EXPECTED_BUILDER_SHA):
    raise ValueError("current stdlib builder pin differs")
module = types.ModuleType("checked_current_guard_workload_assembler_controls")
module.__file__ = str(_BUILDER)
exec(compile(_raw, str(_BUILDER), "exec"), module.__dict__)


class FormulaCoordinatorBuilderControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.base = self.root / "archives"
        self.base.mkdir()
        self.output = self.base / "assembly"
        self.target = self.root / "docs/review.json"
        self.target.parent.mkdir()
        self.patches = [patch.object(module, "ROOT", self.root), patch.object(module, "BASE", self.base),
                        patch.object(module, "OUTPUT", self.output), patch.object(module, "TARGET", self.target)]
        for item in self.patches:
            item.start()
        self.inputs = module.OrdinaryInputs()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def member(self, filename="source.txt", raw=b"explicitly fictional ordinary bytes", *, readonly=True):
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        if readonly:
            path.chmod(0o444)
        return path

    def namespace(self):
        path = self.base / "fixture"
        path.mkdir()
        self.member("archives/fixture/ordinary.txt")
        return path

    def native_pair(self):
        path = self.member("archives/native/result.json", b'{"qualified":true,"proof_authority":false}')
        result = self.inputs.pin(path)
        audit = {"qualified": True, "closed_artifacts_consistent": True, "error": None,
                 "retained_pins": [{"path": "result.json", "bytes": result["bytes"], "sha256": result["sha256"]}]}
        return result, audit

    def test_external_input_specification_sha_is_required_before_any_output(self):
        path = self.member("inputs.json", b'{"schema":"fictional"}')
        with self.assertRaises(module.AssemblyError):
            module.assemble(path, expected_inputs_sha256="0" * 64)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.target.exists())

    def test_duplicate_json_keys_are_refused(self):
        with self.assertRaises(module.AssemblyError):
            module.decode(b'{"role":1,"role":2}')

    def test_nonfinite_json_constants_and_float_overflow_are_refused(self):
        for raw in (b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}', b'{"x":1e10000}'):
            with self.subTest(raw=raw):
                with self.assertRaises(module.AssemblyError):
                    module.decode(raw)

    def test_json_depth_is_bounded(self):
        with self.assertRaises((module.AssemblyError, RecursionError)):
            module.decode(b'[' * 66 + b'0' + b']' * 66)

    def test_boolean_integer_alias_is_refused(self):
        with self.assertRaises(module.AssemblyError):
            module.integer(True)

    def test_paths_cannot_escape_workspace_or_use_parent_traversal(self):
        for value in ("../escape.txt", "/etc/passwd", "archives/../escape.txt"):
            with self.subTest(path=value):
                with self.assertRaises(module.AssemblyError):
                    module.path_of(value)

    def test_symlink_leaf_is_refused_without_opening_its_target(self):
        real = self.member()
        alias = self.root / "alias.txt"
        alias.symlink_to(real)
        with self.assertRaises((module.AssemblyError, OSError)):
            self.inputs.pin(alias)

    def test_symlink_parent_directory_is_refused(self):
        real = self.member("real/ordinary.txt")
        alias = self.root / "alias"
        alias.symlink_to(real.parent, target_is_directory=True)
        with self.assertRaises((module.AssemblyError, OSError)):
            self.inputs.pin(alias / real.name)

    def test_hardlinked_leaf_is_refused(self):
        real = self.member()
        os.link(real, self.root / "second-owner.txt")
        with self.assertRaises(module.AssemblyError):
            self.inputs.pin(real)

    def test_writable_manifest_leaf_is_refused(self):
        path = self.base / "fixture"
        path.mkdir()
        self.member("archives/fixture/writable.txt", readonly=False)
        with self.assertRaises(module.AssemblyError):
            module.manifest(self.inputs, path)

    def test_fifo_or_nonordinary_manifest_member_is_refused(self):
        path = self.namespace()
        os.mkfifo(path / "fifo")
        with self.assertRaises(module.AssemblyError):
            module.manifest(self.inputs, path)

    def test_declared_file_pin_cannot_keep_old_sha_after_byte_replacement(self):
        path = self.member()
        expected = self.inputs.pin(path)
        path.chmod(0o600)
        path.write_bytes(b"ordinary replacement")
        path.chmod(0o444)
        with self.assertRaises(module.AssemblyError):
            self.inputs.verify(expected)

    def test_replaced_inode_is_detected_in_final_member_revalidation(self):
        path = self.member()
        self.inputs.pin(path)
        old = self.root / "old-copy.txt"
        path.rename(old)
        path.write_bytes(old.read_bytes())
        path.chmod(0o444)
        with self.assertRaises(module.AssemblyError):
            self.inputs.final_check()

    def test_new_member_changes_directory_identity_after_manifest(self):
        path = self.namespace()
        _, _, directories = module.manifest(self.inputs, path)
        self.member("archives/fixture/new-member.txt")
        with self.assertRaises(module.AssemblyError):
            module.verify_manifest_directories(path, directories)

    def test_default512_file_namespace_limit_is_preserved(self):
        path = self.base / "fixture"
        path.mkdir()
        for index in range(513):
            self.member(f"archives/fixture/{index:03d}.txt", b"x")
        with self.assertRaises(module.AssemblyError):
            module.manifest(self.inputs, path)

    def test_per_file_size_limit_is_checked_before_read(self):
        path = self.namespace()
        with patch.object(module, "MAX_FILE_BYTES", 1):
            with self.assertRaises(module.AssemblyError):
                module.manifest(self.inputs, path)

    def test_namespace_total_byte_limit_is_checked_before_read(self):
        path = self.namespace()
        with patch.object(module, "MAX_DIRECTORY_BYTES", 1):
            with self.assertRaises(module.AssemblyError):
                module.manifest(self.inputs, path)

    def test_manifest_walk_refuses_base_or_nested_unlisted_namespace_roots(self):
        nested = self.base / "one/two"
        nested.mkdir(parents=True)
        for path in (self.base, nested, self.output):
            with self.subTest(path=path):
                with self.assertRaises(module.AssemblyError):
                    module.manifest(self.inputs, path)

    def test_empty_namespace_cannot_produce_content_manifest(self):
        path = self.base / "fixture"
        path.mkdir()
        with self.assertRaises(module.AssemblyError):
            module.manifest(self.inputs, path)

    def test_manifest_cid_is_independently_recomputed_from_canonical_bytes(self):
        body, cid, _ = module.manifest(self.inputs, self.namespace())
        encoded = cid[1:].upper()
        actual = base64.b32decode(encoded + "=" * ((-len(encoded)) % 8))
        self.assertEqual(actual[:5], bytes((1, 0xA9, 2, 0x12, 0x20)))
        self.assertEqual(actual[5:], hashlib.sha256(module.wire(body)).digest())
        forged = deepcopy(body)
        forged["members"][0]["sha256"] = "0" * 64
        self.assertNotEqual(actual[5:], hashlib.sha256(module.wire(forged)).digest())

    def test_resource_snapshot_with_open_lease_is_refused(self):
        with self.assertRaises(module.AssemblyError):
            module.closed_resources({"active_lease_count": 1})

    def test_resource_snapshot_with_nonzero_allocations_is_refused(self):
        for field in ("allocated_gpu_memory_mb", "active_child_lease_count", "allocated_unified_memory_mb"):
            with self.subTest(field=field):
                with self.assertRaises(module.AssemblyError):
                    module.closed_resources({"active_lease_count": 0, field: 1})
        with self.assertRaises(module.AssemblyError):
            module.closed_resources({"active_lease_count": 0, "allocated": {"cpu_slots": 1, "memory_mb": 0}})

    def test_empty_or_absent_native_audit_cannot_bind_result(self):
        result, audit = self.native_pair()
        for retained in (None, []):
            with self.subTest(retained=retained):
                audit["retained_pins"] = retained
                with self.assertRaises(module.AssemblyError):
                    module.native_result_audit_join(result, audit)

    def test_unrelated_native_audit_result_sha_is_refused(self):
        result, audit = self.native_pair()
        audit["retained_pins"][0]["sha256"] = "0" * 64
        with self.assertRaises(module.AssemblyError):
            module.native_result_audit_join(result, audit)

    def test_consistent_native_audit_cannot_retain_contradictory_error(self):
        result, audit = self.native_pair()
        audit["error"] = {"type": "AuditError", "message": "contradictory fictional failure"}
        with self.assertRaises(module.AssemblyError):
            module.native_result_audit_join(result, audit)

    def test_native_audit_requires_explicit_error_none(self):
        result, audit = self.native_pair()
        audit.pop("error")
        with self.assertRaises(module.AssemblyError):
            module.native_result_audit_join(result, audit)

    def test_duplicate_native_result_pin_is_refused(self):
        result, audit = self.native_pair()
        audit["retained_pins"].append(deepcopy(audit["retained_pins"][0]))
        with self.assertRaises(module.AssemblyError):
            module.native_result_audit_join(result, audit)

    def test_native_audit_result_byte_count_is_exact(self):
        result, audit = self.native_pair()
        audit["retained_pins"][0]["bytes"] += 1
        with self.assertRaises(module.AssemblyError):
            module.native_result_audit_join(result, audit)

    def test_native_audit_retained_path_escape_is_refused(self):
        result, audit = self.native_pair()
        audit["retained_pins"][0]["path"] = "../result.json"
        with self.assertRaises(module.AssemblyError):
            module.native_result_audit_join(result, audit)

    def test_matching_native_result_join_is_ordinary_bytes_only(self):
        result, audit = self.native_pair()
        module.native_result_audit_join(result, audit)
        self.assertTrue(audit["qualified"])
        self.assertFalse(module.decode(self.inputs.read(module.path_of(result["path"]))) ["proof_authority"])

    def test_nested_falseauthority_widening_is_refused(self):
        for flag in ("proof_authority", "production_qualified", "execution_attestation", "kernel_resource_enforcement",
                     "trusted_native_owner_verified", "native_leanstral_encoder_available", "native_leanstral_head_qualified",
                     "native_cuda_qualified", "semantic_qualification", "target_access", "teacher_forcing", "training_executed"):
            with self.subTest(flag=flag):
                with self.assertRaises(module.AssemblyError):
                    module.authority_closed({"ordinary_observations": [{flag: True}]})

    def test_source_current_and_retained_join_requires_equal_bytes(self):
        current = self.inputs.pin(self.member("current.py", b"# fictional current stdlib bytes"))
        retained = self.inputs.pin(self.member("retained.py", b"# different ordinary source"))
        with self.assertRaises(module.AssemblyError):
            module.source_joins(self.inputs, [{"current": current, "retained_copy": retained}])

    def test_plain_json_assertions_preserve_boolean_and_integer_types(self):
        with self.assertRaises(module.AssemblyError):
            module.assertions({"zero": False}, [{"path": ["zero"], "equals": 0}])
        module.assertions({"zero": 0}, [{"path": ["zero"], "equals": 0}])

    def test_new_outputs_are_exclusive_immutable_ordinary_files(self):
        output = self.root / "result.json"
        result = module.write(self.inputs, output, {"proof_authority": False})
        self.assertEqual(result["sha256"], hashlib.sha256(module.wire({"proof_authority": False})).hexdigest())
        self.assertFalse(output.stat().st_mode & 0o222)
        with self.assertRaises(OSError):
            module.write(self.inputs, output, {"proof_authority": False})

    def test_output_substitution_cannot_break_manifest_cid_intended_byte_join(self):
        output = self.root / "substituted.json"
        original_pin = self.inputs.pin
        def substitute(path, *, readonly=False):
            path.chmod(0o600)
            path.write_bytes(module.wire({"proof_authority": False, "injected_member": "different bytes"}))
            path.chmod(0o444)
            return original_pin(path, readonly=readonly)
        with patch.object(self.inputs, "pin", side_effect=substitute):
            with self.assertRaises(module.AssemblyError):
                module.write(self.inputs, output, {"proof_authority": False})

    def test_successful_closure_is_not_written_before_final_changed_member_refusal(self):
        self.output.mkdir()
        path = self.member()
        self.inputs.pin(path)
        path.chmod(0o600)
        path.write_bytes(b"changed before closure commit")
        path.chmod(0o444)
        with self.assertRaises(module.AssemblyError):
            module.close_record(self.inputs, [], {"assembled": True, "proof_authority": False})
        self.assertFalse((self.output / "closure.json").exists())

    def test_successful_closure_is_not_written_before_final_directory_refusal(self):
        self.output.mkdir()
        namespace = self.namespace()
        body, cid, directories = module.manifest(self.inputs, namespace)
        pending = [("fixture", namespace, body, cid, directories)]
        self.member("archives/fixture/added-after-manifest.txt")
        with self.assertRaises(module.AssemblyError):
            module.close_record(self.inputs, pending, {"assembled": True, "proof_authority": False})
        self.assertFalse((self.output / "closure.json").exists())


    def coordinator_result(self):
        return {"schema": "retained-trained-formula-guard-coordinator-qualification/v1",
                "total_return_count": 240, "timed_return_count": 216,
                "formula_projection_count": 240, "optimizer_constructor_calls": 12,
                "optimizer_restore_attempts": 12, "own_root_lease_released": True,
                "selected_existing_profile_changed": False, "training_calls": 0,
                "optimizer_steps": 0, "new_training_fits": 0, "training_mode_true_calls": 0,
                "encoder_calls": 0, "evidence_limits": {"max_files": 1024,
                    "max_file_bytes": 8388608, "max_total_bytes": 67108864,
                    "result_included_in_limits": True}}

    def test_architecture_replay_does_not_grant_default_adoption(self):
        result = self.coordinator_result()
        module.formula_coordinator_scope(result)
        result["selected_existing_profile_changed"] = True
        with self.assertRaises(module.AssemblyError):
            module.formula_coordinator_scope(result)

    def test_formula_coordinator_panel_and_cold_restore_coverage_are_exact(self):
        for key in ("total_return_count", "timed_return_count", "formula_projection_count",
                    "optimizer_constructor_calls", "optimizer_restore_attempts"):
            with self.subTest(key=key):
                result = self.coordinator_result()
                result[key] -= 1
                with self.assertRaises(module.AssemblyError):
                    module.formula_coordinator_scope(result)

    def test_formula_coordinator_counts_cannot_use_boolean_aliases(self):
        result = self.coordinator_result()
        result["optimizer_restore_attempts"] = True
        with self.assertRaises(module.AssemblyError):
            module.formula_coordinator_scope(result)

    def test_formula_coordinator_cannot_widen_archive_allocation(self):
        for key in ("max_files", "max_file_bytes", "max_total_bytes"):
            with self.subTest(key=key):
                result = self.coordinator_result()
                result["evidence_limits"][key] += 1
                with self.assertRaises(module.AssemblyError):
                    module.formula_coordinator_scope(result)

    def test_formula_coordinator_must_include_result_in_archive_bound(self):
        result = self.coordinator_result()
        result["evidence_limits"]["result_included_in_limits"] = False
        with self.assertRaises(module.AssemblyError):
            module.formula_coordinator_scope(result)

    def test_formula_coordinator_cannot_smuggle_new_training_into_restore_counts(self):
        for key in ("training_calls", "optimizer_steps", "new_training_fits", "training_mode_true_calls", "encoder_calls"):
            with self.subTest(key=key):
                result = self.coordinator_result()
                result[key] = 1
                with self.assertRaises(module.AssemblyError):
                    module.formula_coordinator_scope(result)

    def test_formula_coordinator_requires_owned_root_cleanup(self):
        result = self.coordinator_result()
        result["own_root_lease_released"] = False
        with self.assertRaises(module.AssemblyError):
            module.formula_coordinator_scope(result)

    def test_unrelated_replay_schema_cannot_receive_formula_bound_override(self):
        result = self.coordinator_result()
        result["schema"] = "retained-trained-head-bitwise-device-qualification/v1"
        with self.assertRaises(module.AssemblyError):
            module.formula_coordinator_scope(result)


    def epoch_review(self):
        current = {"path": "current.py", "bytes": 97272, "sha256": module.SCHEDULER_SHA}
        prior = {"path": "prior.py", "bytes": 95569, "sha256": "9cb9f263c5a72cd1b1fa2dd9dcd070a549e11bd5483937d35508c6a86d929166"}
        epoch = {"schema": "formula-coordinator-scheduler-source-epoch-review/v1", "current": current,
            "prior": prior, "retained_current": {**current, "path": "copy-current.py"},
            "retained_prior": {**prior, "path": "copy-prior.py"},
            "full_module_ast_equal_after_removing_exact_timeout_diagnostics": True,
            "grant_pressure_cancellation_renewal_and_state_persistence_ast_unchanged": True,
            "current_matches_native_retained_source": True, "resource_configuration_changed": False,
            "scheduler_modified_by_this_turn": False, "execution_attestation": False,
            "proof_authority": False, "production_qualified": False,
            "removed_ast_nodes": {"optional_timeout_argument": 1, "exception_diagnostic_attribute": 1,
                "local_timeout_diagnostic": 1, "terminal_timeout_diagnostic_dict": 1,
                "exception_diagnostic_keyword": 1}}
        return epoch, current

    def test_timeout_diagnostics_do_not_allow_resource_configuration_changes(self):
        epoch, current = self.epoch_review()
        module.scheduler_epoch_scope(epoch, current)
        for field in ("resource_configuration_changed", "scheduler_modified_by_this_turn", "execution_attestation",
                      "proof_authority", "production_qualified"):
            with self.subTest(field=field):
                altered = deepcopy(epoch)
                altered[field] = True
                with self.assertRaises(module.AssemblyError):
                    module.scheduler_epoch_scope(altered, current)

    def test_timeout_diagnostics_need_exact_delta_and_current_native_source(self):
        epoch, current = self.epoch_review()
        for field in ("full_module_ast_equal_after_removing_exact_timeout_diagnostics",
                      "grant_pressure_cancellation_renewal_and_state_persistence_ast_unchanged",
                      "current_matches_native_retained_source"):
            with self.subTest(field=field):
                altered = deepcopy(epoch)
                altered[field] = False
                with self.assertRaises(module.AssemblyError):
                    module.scheduler_epoch_scope(altered, current)
        altered = deepcopy(epoch)
        altered["removed_ast_nodes"]["local_timeout_diagnostic"] = 2
        with self.assertRaises(module.AssemblyError):
            module.scheduler_epoch_scope(altered, current)

    def test_scheduler_epoch_cannot_alias_old_or_fabricated_copy_pins(self):
        epoch, current = self.epoch_review()
        for field in ("current", "prior", "retained_current", "retained_prior"):
            with self.subTest(field=field):
                altered = deepcopy(epoch)
                altered[field]["sha256"] = "0" * 64
                with self.assertRaises(module.AssemblyError):
                    module.scheduler_epoch_scope(altered, current)


if __name__ == "__main__":
    unittest.main()
